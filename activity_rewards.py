"""
activity_rewards.py — Récompense VIP des membres les plus actifs (Phase 174.2).

🎯 OBJECTIF : remercier et récompenser, chaque semaine, les membres les plus
actifs (messages) ET les plus présents en vocal, en leur offrant un rôle
TEMPORAIRE (VIP / VIP+) pendant 2 semaines, avec un message de remerciement.

PHILOSOPHIE :
- Reconnaissance publique + accès temporaire (le rôle peut donner des
  permissions/salons spéciaux que l'owner configure côté Discord).
- VIP+ pour le membre le plus actif TOUS canaux confondus (messages+vocal).
- VIP pour le top messages + le top vocal.
- Rôle auto-retiré à expiration (2 semaines).
- Seuils minimaux : on ne récompense pas une semaine morte.
- Les rôles VIP/VIP+ sont AUTO-CRÉÉS s'ils n'existent pas (cosmétiques,
  l'owner peut ensuite leur donner des accès). Conforme RULES.md : ce sont
  des RÔLES, pas des salons auto-créés.

API :
- setup(bot, get_db, db_get, v2)
- init_db()
- compute_top_active(guild_id) -> dict
- run_weekly_rewards(guild) -> dict (résumé)
- remove_expired(guild_id) -> int
- weekly_reward_task (loop hourly : fire lundi 11h FR + retrait expirés)

DB :
- activity_vip_roles (guild_id PK, vip_role_id, vip_plus_role_id)
- activity_vip_grants (id PK, guild_id, user_id, role_id, tier,
                       granted_at, expires_at, removed)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Quand distribuer (lundi 11h FR — après le récap hebdo de 9h)
REWARD_WEEKDAY = 0  # lundi
REWARD_HOUR = 11
# Durée du rôle VIP (2 semaines)
VIP_DURATION_DAYS = 14
# Combien de membres récompensés par catégorie
TOP_MESSAGES = 3
TOP_VOICE = 3
# Seuils minimaux pour qualifier (anti "semaine morte")
MIN_MESSAGES = 30
MIN_VOICE_MINUTES = 30
# Noms + couleurs des rôles auto-créés
VIP_ROLE_NAME = "🌟 VIP"
VIP_PLUS_ROLE_NAME = "💎 VIP+"
VIP_COLOR = 0x3498DB
VIP_PLUS_COLOR = 0x9B59B6


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_vip_roles (
                    guild_id INTEGER PRIMARY KEY,
                    vip_role_id INTEGER DEFAULT 0,
                    vip_plus_role_id INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_vip_grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    tier TEXT NOT NULL,
                    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    removed INTEGER DEFAULT 0
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vip_grants_active "
                "ON activity_vip_grants(guild_id, removed, expires_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[activity_rewards init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Time helpers
# ═══════════════════════════════════════════════════════════════════════════

def _now_paris() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc)


def _is_reward_window() -> bool:
    now = _now_paris()
    return now.weekday() == REWARD_WEEKDAY and now.hour == REWARD_HOUR


def _week_key() -> str:
    iso = _now_paris().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ═══════════════════════════════════════════════════════════════════════════
#  Compute leaders
# ═══════════════════════════════════════════════════════════════════════════

async def compute_top_active(guild_id: int) -> dict:
    """Calcule les membres les plus actifs (7 derniers jours).

    Retourne {
        "messages": [(user_id, msg_count), ...],   # triés desc
        "voice":    [(user_id, voice_minutes), ...],
        "overall":  user_id | None,                # plus actif combiné
    }
    """
    out = {"messages": [], "voice": [], "overall": None}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            # Top messages (7j)
            async with db.execute(
                "SELECT user_id, COUNT(*) as c FROM member_activity "
                "WHERE guild_id=? AND activity_type='message' "
                "AND datetime(created_at) > datetime('now', '-7 days') "
                "GROUP BY user_id HAVING c >= ? "
                "ORDER BY c DESC LIMIT ?",
                (guild_id, MIN_MESSAGES, TOP_MESSAGES),
            ) as cur:
                out["messages"] = [(int(r[0]), int(r[1])) for r in await cur.fetchall()]

            # Top vocal (7j) — somme des durées en minutes
            async with db.execute(
                "SELECT user_id, SUM(duration_seconds)/60 as m FROM voice_activity_log "
                "WHERE guild_id=? AND datetime(joined_at) > datetime('now', '-7 days') "
                "GROUP BY user_id HAVING m >= ? "
                "ORDER BY m DESC LIMIT ?",
                (guild_id, MIN_VOICE_MINUTES, TOP_VOICE),
            ) as cur:
                out["voice"] = [(int(r[0]), int(r[1] or 0)) for r in await cur.fetchall()]

        # Score combiné pour désigner le VIP+ : 1 pt / message + 1 pt / 2 min vocal
        score: dict[int, float] = {}
        for uid, c in out["messages"]:
            score[uid] = score.get(uid, 0) + c
        for uid, m in out["voice"]:
            score[uid] = score.get(uid, 0) + (m / 2.0)
        if score:
            out["overall"] = max(score.items(), key=lambda kv: kv[1])[0]
    except Exception as ex:
        print(f"[compute_top_active] {ex}")
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Roles (auto-create)
# ═══════════════════════════════════════════════════════════════════════════

async def _get_role_ids(guild_id: int) -> tuple[int, int]:
    if _get_db is None:
        return (0, 0)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT vip_role_id, vip_plus_role_id FROM activity_vip_roles "
                "WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return (int(row[0] or 0), int(row[1] or 0))
    except Exception:
        pass
    return (0, 0)


async def _save_role_ids(guild_id: int, vip_id: int, vip_plus_id: int) -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activity_vip_roles (guild_id, vip_role_id, vip_plus_role_id) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET "
                "vip_role_id=excluded.vip_role_id, "
                "vip_plus_role_id=excluded.vip_plus_role_id",
                (guild_id, vip_id, vip_plus_id),
            )
            await db.commit()
    except Exception:
        pass


async def _ensure_vip_roles(guild: discord.Guild):
    """Retourne (vip_role, vip_plus_role). Auto-crée si absents (fail-soft si
    pas la permission Manage Roles)."""
    vip_id, vip_plus_id = await _get_role_ids(guild.id)
    vip_role = guild.get_role(vip_id) if vip_id else None
    vip_plus_role = guild.get_role(vip_plus_id) if vip_plus_id else None

    can_manage = False
    try:
        can_manage = bool(guild.me and guild.me.guild_permissions.manage_roles)
    except Exception:
        can_manage = False

    if vip_role is None:
        vip_role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
        if vip_role is None and can_manage:
            try:
                vip_role = await guild.create_role(
                    name=VIP_ROLE_NAME, colour=discord.Colour(VIP_COLOR),
                    hoist=True, mentionable=False,
                    reason="Récompense activité hebdomadaire (Phase 174)",
                )
            except Exception as ex:
                print(f"[activity_rewards create VIP role] {ex}")

    if vip_plus_role is None:
        vip_plus_role = discord.utils.get(guild.roles, name=VIP_PLUS_ROLE_NAME)
        if vip_plus_role is None and can_manage:
            try:
                vip_plus_role = await guild.create_role(
                    name=VIP_PLUS_ROLE_NAME, colour=discord.Colour(VIP_PLUS_COLOR),
                    hoist=True, mentionable=False,
                    reason="Récompense activité hebdomadaire (Phase 174)",
                )
            except Exception as ex:
                print(f"[activity_rewards create VIP+ role] {ex}")

    await _save_role_ids(
        guild.id,
        vip_role.id if vip_role else 0,
        vip_plus_role.id if vip_plus_role else 0,
    )
    return vip_role, vip_plus_role


# ═══════════════════════════════════════════════════════════════════════════
#  Grant
# ═══════════════════════════════════════════════════════════════════════════

async def _grant(
    guild: discord.Guild, member: discord.Member, role: discord.Role,
    tier: str, days: int,
) -> bool:
    if not member or not role:
        return False
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    try:
        if role not in member.roles:
            await member.add_roles(role, reason=f"Récompense activité ({tier})")
    except Exception as ex:
        print(f"[activity_rewards grant add_roles] {ex}")
        return False
    if _get_db is not None:
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO activity_vip_grants "
                    "(guild_id, user_id, role_id, tier, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (guild.id, member.id, role.id, tier, expires.isoformat()),
                )
                await db.commit()
        except Exception:
            pass
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Run weekly rewards
# ═══════════════════════════════════════════════════════════════════════════

async def _already_ran_this_week(guild_id: int) -> bool:
    """Anti-doublon : a-t-on déjà distribué cette semaine ?"""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM activity_vip_grants "
                "WHERE guild_id=? AND datetime(granted_at) > datetime('now', '-5 days') "
                "LIMIT 1",
                (guild_id,),
            ) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def run_weekly_rewards(guild: discord.Guild) -> dict:
    """Distribue les rôles VIP/VIP+ aux plus actifs + message de remerciement."""
    result = {"vip": [], "vip_plus": None, "skipped": False}
    if not guild or _get_db is None:
        result["skipped"] = True
        return result

    if await _already_ran_this_week(guild.id):
        result["skipped"] = True
        return result

    leaders = await compute_top_active(guild.id)
    msg_leaders = leaders["messages"]
    voice_leaders = leaders["voice"]
    overall = leaders["overall"]

    if not msg_leaders and not voice_leaders:
        result["skipped"] = True
        return result

    vip_role, vip_plus_role = await _ensure_vip_roles(guild)

    granted_vip: list[tuple[int, str]] = []  # (user_id, reason)
    vip_plus_granted: Optional[int] = None

    # VIP+ pour le plus actif global
    if overall and vip_plus_role:
        m = guild.get_member(overall)
        if m and not m.bot:
            if await _grant(guild, m, vip_plus_role, "vip_plus", VIP_DURATION_DAYS):
                vip_plus_granted = overall

    # VIP pour les autres tops (messages + vocal), sauf le VIP+
    union_ids = []
    for uid, _ in msg_leaders:
        union_ids.append((uid, "messages"))
    for uid, _ in voice_leaders:
        union_ids.append((uid, "vocal"))

    seen = set()
    if vip_plus_granted:
        seen.add(vip_plus_granted)  # le VIP+ ne reçoit pas aussi VIP
    for uid, reason in union_ids:
        if uid in seen:
            continue
        seen.add(uid)
        if not vip_role:
            continue
        m = guild.get_member(uid)
        if m and not m.bot:
            if await _grant(guild, m, vip_role, "vip", VIP_DURATION_DAYS):
                granted_vip.append((uid, reason))

    result["vip"] = granted_vip
    result["vip_plus"] = vip_plus_granted

    # Annonce de remerciement
    await _announce_rewards(guild, granted_vip, vip_plus_granted, leaders)

    print(
        f"[activity_rewards] guild={guild.id} vip+={vip_plus_granted} "
        f"vip={[u for u, _ in granted_vip]}"
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Announce
# ═══════════════════════════════════════════════════════════════════════════

async def _find_announce_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    if _db_get is None:
        return None
    try:
        cfg = await _db_get(guild.id)
        for key in ("vip_announce_channel_id", "hub_channel",
                    "welcome_channel", "general_channel"):
            ch_id = int(cfg.get(key, 0) or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch:
                    return ch
    except Exception:
        pass
    # Fallback : premier salon écrivable non-restreint. Liste alignée sur la liste
    # canonique _BAD de daily_prompt (l'annonce VIP est PERSISTANTE → ne doit jamais
    # atterrir dans un journal/combat/arène/accueil/lecture-seule et y rester à vie).
    avoid = ("ticket", "log", "audit", "annonce", "announce", "règl", "regl",
             "rule", "staff", "admin", "mod", "welcome", "bienvenue", "info",
             "chronique", "combat", "arène", "arene", "vente", "shop", "boutique")
    try:
        me = guild.me
        for ch in guild.text_channels:
            n = (ch.name or "").lower()
            if any(a in n for a in avoid):
                continue
            if me and ch.permissions_for(me).send_messages:
                return ch
    except Exception:
        pass
    return None


async def _announce_rewards(
    guild: discord.Guild, granted_vip: list, vip_plus_id: Optional[int],
    leaders: dict,
) -> None:
    ch = await _find_announce_channel(guild)
    if not ch:
        return

    lines = [
        "🌟 **MERCI À NOS MEMBRES LES PLUS ACTIFS !** 🌟",
        "",
        "_Chaque semaine, le serveur récompense celles et ceux qui le font "
        "vivre — par leurs messages et leur présence en vocal. Voici les "
        "héros de la semaine, qui gagnent un rôle spécial pendant "
        f"**{VIP_DURATION_DAYS} jours** :_",
        "",
    ]

    if vip_plus_id:
        m = guild.get_member(vip_plus_id)
        nm = m.mention if m else f"<@{vip_plus_id}>"
        lines.append(f"💎 **VIP+ — Membre le plus actif** : {nm}")
        lines.append("_Le plus présent toutes catégories confondues. Chapeau !_")
        lines.append("")

    if granted_vip:
        lines.append("🌟 **VIP de la semaine** :")
        for uid, reason in granted_vip:
            m = guild.get_member(uid)
            nm = m.mention if m else f"<@{uid}>"
            tag = "💬 messages" if reason == "messages" else "🎙️ vocal"
            lines.append(f"• {nm} _(top {tag})_")
        lines.append("")

    lines.append(
        "_Merci pour votre énergie 💪 — vos rôles vous donnent des accès "
        "spéciaux pendant 2 semaines. Continuez comme ça !_"
    )

    # RULES.md : max 3 mentions RÉELLES (pings) par message (TOS Discord).
    # Les noms au-delà des 3 premiers s'affichent quand même (rendu mention)
    # mais ne déclenchent PAS de notification.
    ordered_ids: list[int] = []
    if vip_plus_id:
        ordered_ids.append(vip_plus_id)
    for uid, _ in granted_vip:
        if uid not in ordered_ids:
            ordered_ids.append(uid)
    ping_objs = [discord.Object(id=u) for u in ordered_ids[:3]]

    try:
        allowed = discord.AllowedMentions(
            users=ping_objs, roles=False, everyone=False,
        )
        await ch.send("\n".join(lines), allowed_mentions=allowed)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Expiry
# ═══════════════════════════════════════════════════════════════════════════

async def remove_expired(guild_id: int) -> int:
    """Retire les rôles VIP expirés. Retourne le nb retiré."""
    if _get_db is None or _bot is None:
        return 0
    guild = _bot.get_guild(guild_id)
    if not guild:
        return 0
    removed = 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, user_id, role_id FROM activity_vip_grants "
                "WHERE guild_id=? AND removed=0 "
                "AND datetime(expires_at) <= datetime('now')",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        for gid_row in rows:
            grant_id, user_id, role_id = int(gid_row[0]), int(gid_row[1]), int(gid_row[2])
            member = guild.get_member(user_id)
            role = guild.get_role(role_id)
            # Ne retire le rôle que si le membre ne l'a pas via une AUTRE grant
            # encore active (ex : VIP gagné 2 semaines de suite).
            still_active = False
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT 1 FROM activity_vip_grants "
                        "WHERE guild_id=? AND user_id=? AND role_id=? AND removed=0 "
                        "AND datetime(expires_at) > datetime('now') LIMIT 1",
                        (guild_id, user_id, role_id),
                    ) as cur:
                        still_active = await cur.fetchone() is not None
            except Exception:
                pass
            if member and role and not still_active:
                try:
                    if role in member.roles:
                        await member.remove_roles(role, reason="Récompense VIP expirée")
                except Exception:
                    pass
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE activity_vip_grants SET removed=1 WHERE id=?",
                        (grant_id,),
                    )
                    await db.commit()
            except Exception:
                pass
            removed += 1
    except Exception as ex:
        print(f"[activity_rewards remove_expired] {ex}")
    return removed


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def weekly_reward_task():
    """Toutes les 30 min : distribue lundi 11h FR + retire les rôles expirés."""
    if _bot is None or _get_db is None:
        return
    try:
        # Distribution hebdo
        if _is_reward_window():
            for guild in _bot.guilds:
                try:
                    await run_weekly_rewards(guild)
                except Exception as ex:
                    print(f"[weekly_reward_task run g={guild.id}] {ex}")

        # Retrait des rôles expirés (à chaque tick)
        for guild in _bot.guilds:
            try:
                await remove_expired(guild.id)
            except Exception as ex:
                print(f"[weekly_reward_task expire g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[weekly_reward_task] {ex}")


@weekly_reward_task.before_loop
async def _reward_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "REWARD_WEEKDAY",
    "REWARD_HOUR",
    "VIP_DURATION_DAYS",
    "TOP_MESSAGES",
    "TOP_VOICE",
    "MIN_MESSAGES",
    "MIN_VOICE_MINUTES",
    "setup",
    "init_db",
    "compute_top_active",
    "run_weekly_rewards",
    "remove_expired",
    "weekly_reward_task",
]
