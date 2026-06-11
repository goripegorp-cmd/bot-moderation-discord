"""
dormant_wakeup.py — Réveil intelligent des membres dormants (Phase 145).

🎯 OBJECTIF CENTRAL : ramener les membres qui dorment sur le serveur, SANS
spammer, SANS être pénible, en s'appuyant sur la saison active.

Stratégie multi-couche :

1. **Détection** : un membre est dormant s'il n'a pas posté de message
   depuis 7 jours (configurable).

2. **DM personnalisé** : 1× par 30 jours max par membre. Le DM mentionne
   la saison active + 1 event qui se déroule cette semaine.

3. **Reward "Comeback"** : si un dormant DM'd poste dans les 7 jours qui
   suivent le DM → +500 coins automatique 1× (incentive concret).

4. **Anti-spam Discord** : max 5 DMs par run de la task, throttle 2s entre
   chaque DM. La task tourne 1× par jour à 14h FR (heure d'activité max).

5. **Opt-out** : respect strict de quiet_hours_module / DM permission. Si
   un user a DMs désactivés, on log et skip silencieusement.

6. **Track stats** : combien de membres réveillés sur les 7 derniers jours
   → affichable via /dormant stats pour le staff.

DB tables (créées à la volée) :
- dormant_dm_log (guild_id, user_id PK, last_dm_at, season_key_at_dm,
                  comeback_claimed)
- dormant_comeback_pending (guild_id, user_id PK, dm_sent_at, expires_at)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, seasonal_module=None,
        add_coins_fn=None)
- check_and_reward_comeback(member) — à hook depuis on_message
- run_dormant_dispatch() — manual trigger pour tests owner
- get_stats(guild_id, days=7) -> dict
- build_stats_panel(stats, guild) -> LayoutView V2
- dormant_dispatch_task (loop daily 14h FR)

⚠️ RULES.md : DM contiennent ZÉRO contenu romantique/copain-copain.
Focus purement sur "il y a des choses à faire, viens jouer".
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# ─── Configuration ───────────────────────────────────────────────────────
DORMANT_THRESHOLD_DAYS = 7         # 7 jours sans message = dormant
DM_COOLDOWN_DAYS = 30              # Max 1 DM/membre/30j
COMEBACK_WINDOW_DAYS = 7           # Si dormant poste dans 7j après DM → reward
COMEBACK_REWARD_COINS = 500
MAX_DMS_PER_RUN = 5                # Anti-spam Discord API
DM_THROTTLE_SECONDS = 2.0
DISPATCH_HOUR_FR = 14              # 14h Europe/Paris (heure de pic)

# Variantes de messages pour ne pas envoyer le même 30j plus tard
DM_TEMPLATES = [
    "Salut **{name}**, on ne t'a pas vu sur **{guild}** depuis un moment !\n\n"
    "{season_emoji} On est en **{season_name}** — {season_tagline}\n\n"
    "Quand tu reviens poster ton premier message dans la semaine, tu reçois "
    "automatiquement **+{reward} coins** de bienvenue. Pas de fla-fla, juste un boost.\n\n"
    "_Tu peux désactiver ces messages via `/notifs` dans le serveur._",

    "Hey **{name}**, ça fait un bail !\n\n"
    "{season_emoji} La saison **{season_name}** vient de commencer sur **{guild}** — "
    "{season_tagline}\n\n"
    "Si tu reviens cette semaine, **+{reward} coins** t'attendent dès ton premier message. "
    "C'est notre façon de dire merci d'être passé.\n\n"
    "_DMs configurables via `/notifs`._",

    "**{name}** ! On garde une place pour toi sur **{guild}**.\n\n"
    "{season_emoji} Saison actuelle : **{season_name}** — {season_tagline}\n\n"
    "Ton retour vaut **+{reward} coins** (1× automatique, dès que tu postes). "
    "Aucune obligation, juste un petit cadeau.\n\n"
    "_Pour ne plus recevoir ces messages : `/notifs` sur le serveur._",
]


# Références injectées
_bot = None
_get_db = None
_db_get = None
_v2_helpers = None
_seasonal_module = None
_add_coins_fn = None
_tables_initialized = False


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    seasonal_module=None, add_coins_fn=None,
):
    """Configure le module.

    seasonal_module : référence à seasonal_engine pour personnaliser le DM
    add_coins_fn    : fonction async (guild_id, user_id, amount) → solde
    """
    global _bot, _get_db, _db_get, _v2_helpers, _seasonal_module, _add_coins_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2_helpers = v2_helpers
    _seasonal_module = seasonal_module
    _add_coins_fn = add_coins_fn


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Tables
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS dormant_dm_log (
                guild_id INTEGER,
                user_id INTEGER,
                last_dm_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                season_key_at_dm TEXT,
                comeback_claimed INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS dormant_comeback_pending (
                guild_id INTEGER,
                user_id INTEGER,
                dm_sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_dormant_pending_expires "
                "ON dormant_comeback_pending(expires_at)"
            )
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[dormant_wakeup _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# DETECT DORMANTS
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_dormant_candidates(
    guild_id: int, limit: int = MAX_DMS_PER_RUN
) -> list[int]:
    """Liste les user_ids dormants éligibles à un DM.

    Critères :
    - Dernier message > 7 jours
    - Pas de DM envoyé dans les 30 derniers jours
    - Pas un bot (filtré en post-fetch via guild.get_member)
    """
    if _get_db is None:
        return []
    await _ensure_tables()
    cutoff_dormant = (
        datetime.now(timezone.utc) - timedelta(days=DORMANT_THRESHOLD_DAYS)
    ).isoformat()
    cutoff_dm = (
        datetime.now(timezone.utc) - timedelta(days=DM_COOLDOWN_DAYS)
    ).isoformat()
    try:
        async with _get_db() as db:
            # Filtre via activity_tracking (table existante)
            # user_id qui a last_message ancien ET qui n'a pas eu de DM récent
            async with db.execute(
                "SELECT at.user_id FROM activity_tracking at "
                "LEFT JOIN dormant_dm_log d "
                "  ON d.guild_id = at.guild_id AND d.user_id = at.user_id "
                "WHERE at.guild_id = ? "
                "  AND at.last_message IS NOT NULL "
                "  AND datetime(at.last_message) < datetime(?) "
                "  AND (d.last_dm_at IS NULL OR datetime(d.last_dm_at) < datetime(?)) "
                "ORDER BY at.last_message ASC "  # plus anciens en premier
                "LIMIT ?",
                (guild_id, cutoff_dormant, cutoff_dm, int(limit) * 3),
                # ×3 pour avoir une marge si certains DMs échouent (DMs off)
            ) as cur:
                rows = await cur.fetchall()
        return [int(r[0]) for r in rows if r[0]]
    except Exception as ex:
        print(f"[dormant_wakeup _get_dormant_candidates] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# SEND DM
# ═══════════════════════════════════════════════════════════════════════════════

def _pick_dm_text(member: discord.Member, season: dict, guild_name: str) -> str:
    template = random.choice(DM_TEMPLATES)
    return template.format(
        name=member.display_name,
        guild=guild_name,
        season_emoji=season.get("emoji", "✨"),
        season_name=season.get("name", "saison actuelle"),
        season_tagline=season.get("tagline", "")
            .replace("_", "").strip()
            .replace(member.display_name, "tu sais qui"),  # safe replace
        reward=COMEBACK_REWARD_COINS,
    )


async def _send_dormant_dm(
    member: discord.Member, season: dict
) -> bool:
    """Envoie le DM, log dans dormant_dm_log + dormant_comeback_pending.

    Retourne True si DM envoyé OK.
    """
    # Phase 257 : WAKE-UP MP DÉSACTIVÉ (directive owner — zéro MP membre).
    return False
    if _get_db is None or not member or member.bot:
        return False
    try:
        text = _pick_dm_text(member, season, member.guild.name)
        try:
            await member.send(text)
        except (discord.Forbidden, discord.HTTPException):
            # DMs désactivés ou bloqué : on log quand même pour ne pas
            # ré-essayer dans les 30j, et on évite spam d'erreurs.
            await _log_dm_attempt(member, season, dm_ok=False)
            return False

        # Log succès + pending comeback
        await _log_dm_attempt(member, season, dm_ok=True)
        return True
    except Exception as ex:
        print(f"[dormant_wakeup _send_dormant_dm member={member.id}] {ex}")
        return False


async def _log_dm_attempt(
    member: discord.Member, season: dict, dm_ok: bool
):
    """Log l'attempt (même si fail) pour ne pas ré-essayer 30j."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO dormant_dm_log "
                "(guild_id, user_id, last_dm_at, season_key_at_dm, comeback_claimed) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, ?, 0) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "last_dm_at=CURRENT_TIMESTAMP, "
                "season_key_at_dm=excluded.season_key_at_dm, "
                "comeback_claimed=0",
                (member.guild.id, member.id, season.get("key", "?")),
            )
            if dm_ok:
                expires = (
                    datetime.now(timezone.utc) +
                    timedelta(days=COMEBACK_WINDOW_DAYS)
                ).isoformat()
                await db.execute(
                    "INSERT INTO dormant_comeback_pending "
                    "(guild_id, user_id, dm_sent_at, expires_at) "
                    "VALUES (?, ?, CURRENT_TIMESTAMP, ?) "
                    "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                    "dm_sent_at=CURRENT_TIMESTAMP, expires_at=excluded.expires_at",
                    (member.guild.id, member.id, expires),
                )
            await db.commit()
    except Exception as ex:
        print(f"[dormant_wakeup _log_dm_attempt] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# COMEBACK REWARD — hook on_message
# ═══════════════════════════════════════════════════════════════════════════════

async def check_and_reward_comeback(
    member: discord.Member
) -> tuple[bool, int]:
    """À call depuis on_message : check si user a un comeback pending + reward.

    Retourne (rewarded, amount) si OK, sinon (False, 0).
    """
    if _get_db is None or not member or member.bot:
        return False, 0
    if not _add_coins_fn:
        return False, 0
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT expires_at FROM dormant_comeback_pending "
                "WHERE guild_id=? AND user_id=?",
                (member.guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return False, 0
            # Check expiration
            try:
                exp_dt = datetime.fromisoformat(row[0])
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    # Expired → cleanup
                    await db.execute(
                        "DELETE FROM dormant_comeback_pending "
                        "WHERE guild_id=? AND user_id=?",
                        (member.guild.id, member.id),
                    )
                    await db.commit()
                    return False, 0
            except Exception:
                pass

            # Reward !
            try:
                await _add_coins_fn(
                    member.guild.id, member.id, COMEBACK_REWARD_COINS
                )
            except Exception as ex:
                print(f"[dormant_wakeup add_coins] {ex}")
                return False, 0

            # Mark claimed
            await db.execute(
                "DELETE FROM dormant_comeback_pending "
                "WHERE guild_id=? AND user_id=?",
                (member.guild.id, member.id),
            )
            await db.execute(
                "UPDATE dormant_dm_log SET comeback_claimed=1 "
                "WHERE guild_id=? AND user_id=?",
                (member.guild.id, member.id),
            )
            await db.commit()
        return True, COMEBACK_REWARD_COINS
    except Exception as ex:
        print(f"[dormant_wakeup check_and_reward_comeback] {ex}")
        return False, 0


# ═══════════════════════════════════════════════════════════════════════════════
# DISPATCH TASK — daily 14h FR
# ═══════════════════════════════════════════════════════════════════════════════

async def run_dormant_dispatch_for_guild(guild) -> int:
    """Exécute un cycle de DMs pour un guild. Retourne nb envoyés OK."""
    if _bot is None or _get_db is None:
        return 0
    if _seasonal_module is None:
        return 0  # On a besoin de la saison pour personnaliser

    season = _seasonal_module.current_season()
    sent_ok = 0
    candidates = await _get_dormant_candidates(guild.id, limit=MAX_DMS_PER_RUN)
    for uid in candidates:
        if sent_ok >= MAX_DMS_PER_RUN:
            break
        try:
            member = guild.get_member(int(uid))
            if not member or member.bot:
                continue
            ok = await _send_dormant_dm(member, season)
            if ok:
                sent_ok += 1
            # Throttle peu importe le résultat
            await asyncio.sleep(DM_THROTTLE_SECONDS)
        except Exception as ex:
            print(f"[dormant_wakeup dispatch_for_guild={guild.id} uid={uid}] {ex}")
    return sent_ok


@tasks.loop(minutes=30)
async def dormant_dispatch_task():
    """Tourne toutes les 30 min — agit à 14h-14h30 FR (1× / jour)."""
    try:
        if _bot is None or _seasonal_module is None:
            return
        now_local = datetime.now(_PARIS_TZ)
        if now_local.hour != DISPATCH_HOUR_FR:
            return
        # Anti-doublon dans la même heure
        if now_local.minute >= 30:
            return

        total = 0
        for guild in list(_bot.guilds):
            try:
                n = await run_dormant_dispatch_for_guild(guild)
                total += n
            except Exception as ex:
                print(f"[dormant_wakeup task guild={guild.id}] {ex}")
        if total > 0:
            print(f"💌 [dormant_wakeup] {total} DM(s) de réveil envoyés")
    except Exception as ex:
        print(f"[dormant_wakeup dispatch_task] {ex}")


@dormant_dispatch_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════════
# STATS + PANEL
# ═══════════════════════════════════════════════════════════════════════════════

async def get_stats(guild_id: int, days: int = 7) -> dict:
    """Stats des DMs + comebacks sur les N derniers jours."""
    out = {
        "dms_sent": 0,
        "comebacks_claimed": 0,
        "comebacks_pending": 0,
        "window_days": days,
    }
    if _get_db is None:
        return out
    await _ensure_tables()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM dormant_dm_log "
                "WHERE guild_id=? AND datetime(last_dm_at) >= datetime(?)",
                (guild_id, cutoff),
            ) as cur:
                row = await cur.fetchone()
            out["dms_sent"] = int(row[0] or 0) if row else 0

            async with db.execute(
                "SELECT COUNT(*) FROM dormant_dm_log "
                "WHERE guild_id=? AND comeback_claimed=1 "
                "AND datetime(last_dm_at) >= datetime(?)",
                (guild_id, cutoff),
            ) as cur:
                row = await cur.fetchone()
            out["comebacks_claimed"] = int(row[0] or 0) if row else 0

            async with db.execute(
                "SELECT COUNT(*) FROM dormant_comeback_pending WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            out["comebacks_pending"] = int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[dormant_wakeup get_stats] {ex}")
    return out


def build_stats_panel(stats: dict, guild_name: str = ""):
    """Panel V2 — stats des réveils."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    rate = 0.0
    if stats["dms_sent"] > 0:
        rate = stats["comebacks_claimed"] / stats["dms_sent"] * 100

    class _StatsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("💌  RÉVEIL DES DORMANTS"))
            items.append(v2_subtitle(
                f"_Stats sur {stats['window_days']} derniers jours — {guild_name}_"
            ))
            items.append(v2_divider())

            items.append(v2_body(
                f"📨 **DMs envoyés :** `{stats['dms_sent']}`\n"
                f"🎉 **Membres revenus :** `{stats['comebacks_claimed']}` "
                f"({rate:.1f}% taux de retour)\n"
                f"⏳ **Comebacks en attente :** `{stats['comebacks_pending']}`"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                f"### ⚙️ CONFIGURATION\n"
                f"• Seuil dormance : **{DORMANT_THRESHOLD_DAYS} jours** sans message\n"
                f"• Cooldown DM : **{DM_COOLDOWN_DAYS} jours** entre 2 DMs/membre\n"
                f"• Fenêtre comeback : **{COMEBACK_WINDOW_DAYS} jours** pour claim\n"
                f"• Récompense : **{COMEBACK_REWARD_COINS}** coins (1× auto)\n"
                f"• Cap DMs/run : **{MAX_DMS_PER_RUN}** (anti-spam Discord)\n"
                f"• Heure dispatch : **{DISPATCH_HOUR_FR}h Europe/Paris**"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 Le bot DM 1× par 30j max à un dormant. Si la personne "
                "a désactivé les DMs ou bloqué le bot, on retry pas. Opt-out total "
                "via `/notifs` sur le serveur._"
            ))

            self.add_item(v2_container(*items, color=0x9B59B6))

    return _StatsPanel()


__all__ = [
    "setup",
    "check_and_reward_comeback",
    "run_dormant_dispatch_for_guild",
    "get_stats",
    "build_stats_panel",
    "dormant_dispatch_task",
    # Constants
    "DORMANT_THRESHOLD_DAYS",
    "DM_COOLDOWN_DAYS",
    "COMEBACK_REWARD_COINS",
]
