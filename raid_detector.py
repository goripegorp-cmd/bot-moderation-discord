"""
raid_detector.py — Anti-raid moderne 2026 (Phase 147).

🎯 OBJECTIF : détecter les raids COORDONNÉS sans déclencher de faux
positifs sur les surges légitimes (streams, partages réseaux sociaux).

⚠️ CONTEXTE OWNER : le owner est créateur de contenu. Quand il fait un
live, le serveur peut passer de 0 à 100+ joins en quelques heures sans
que ce soit un raid. La logique doit DISCRIMINER :

✅ SURGE LÉGITIME (NE PAS bloquer) :
  - Comptes d'âges variés (mix entre nouveaux et anciens Discord users)
  - Avatars personnalisés (utilisateurs réels avec leur perso)
  - Pseudos lisibles (humains, pas random)
  - Joining étalé sur 30-60min (viewers qui découvrent le lien)

❌ RAID 2026 (alerter) :
  - 80%+ comptes < 7 jours
  - 60%+ comptes sans avatar custom (default Discord)
  - Pseudos en patterns (User1234, Abc-Def, Xx_target_xX)
  - Joining cluster en < 5 min

Le module utilise des proxies résidentiels rendant l'IP-rate-limit
inutile. On se base UNIQUEMENT sur les signatures de compte.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- on_member_join(member) — à hook depuis bot.py
- get_alert_panel(guild) -> LayoutView pour le owner (review + lockdown)
- run_lockdown(guild, duration_min) -> active la quarantaine

DB tables :
- raid_join_log (guild_id, user_id, joined_at, account_age_days,
                 has_custom_avatar, pseudo_score, total_score)
- raid_alerts (guild_id, alert_id PK, created_at, members_jsonb, status)

⚠️ RULES.md : pas de bans automatiques. Tout passe par alerte owner +
bouton "Lockdown 30min" ou "Faux positif (ignore)".
"""
from __future__ import annotations

import re
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ui import Button

import owner_ids as _owner_ids  # FIX sécu : source UNIQUE de super-owners

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Seuils de scoring (réglables)
SCORE_RECENT_30D = 2     # compte créé < 30 jours
SCORE_RECENT_7D = 3      # compte créé < 7 jours (cumul)
SCORE_VERY_RECENT_24H = 5  # compte créé < 24h (cumul fort)
SCORE_NO_AVATAR = 2      # avatar default Discord
SCORE_BOT_PATTERN = 3    # pseudo en pattern bot-like
SCORE_PSEUDO_TWIN = 4    # même pattern qu'un autre joiner récent

# Seuils d'alerte
SUSPICIOUS_THRESHOLD = 8       # score individuel >= 8 = compte suspect
MIN_SUSPICIOUS_FOR_ALERT = 5   # 5+ comptes suspects pour alerter
CLUSTER_WINDOW_MIN = 10        # tous ces comptes doivent join en < 10 min
ROLLING_WINDOW_SIZE = 30       # garde les 30 derniers joins par guild

# Regex pour détecter pseudos suspects
_RX_BOT_PATTERN = re.compile(
    r"^(?:user|discord|member|guest|player|test|bot|raid|attack)"
    r"[._-]?\d{3,}$|^[a-z]{3,8}\d{4,}$|^[A-Z][a-z]{2,8}_?[A-Z][a-z]{2,8}\d*$",
    re.IGNORECASE,
)
_RX_ALL_RANDOM = re.compile(r"^[a-z]{6,}\d{4,}$", re.IGNORECASE)
_RX_REPEATED_CHARS = re.compile(r"(.)\1{4,}")  # aaaaa, 11111
_RX_XX_PATTERN = re.compile(r"^[xX]+[\w._-]+[xX]+$")


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    """Configure le module. Crée les tables DB si nécessaire."""
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    """Crée les tables nécessaires (idempotent)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS raid_join_log (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    account_age_days INTEGER,
                    has_custom_avatar INTEGER,
                    pseudo_score INTEGER,
                    total_score INTEGER,
                    PRIMARY KEY (guild_id, user_id, joined_at)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS raid_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    members_jsonb TEXT,
                    avg_score REAL,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_raid_join_log_recent "
                "ON raid_join_log(guild_id, joined_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[raid_detector init_db] {ex}")


# ─── Scoring ────────────────────────────────────────────────────────────────

def _score_pseudo(name: str) -> int:
    """Note un pseudo selon des heuristiques anti-bot."""
    if not name:
        return SCORE_BOT_PATTERN
    n = name.strip()
    if _RX_BOT_PATTERN.search(n):
        return SCORE_BOT_PATTERN
    if _RX_ALL_RANDOM.search(n):
        return SCORE_BOT_PATTERN
    if _RX_REPEATED_CHARS.search(n):
        return SCORE_BOT_PATTERN
    if _RX_XX_PATTERN.search(n):
        return SCORE_BOT_PATTERN
    # Pseudo très court ou tout en chiffres
    if len(n) < 3 or n.isdigit():
        return SCORE_BOT_PATTERN
    return 0


def _score_account(member: discord.Member) -> dict:
    """Calcule un score complet pour un membre qui vient de join."""
    score = 0
    parts = {}

    # Age du compte
    try:
        age_days = (discord.utils.utcnow() - member.created_at).days
    except Exception:
        age_days = 999
    parts["account_age_days"] = age_days
    if age_days < 1:
        score += SCORE_RECENT_30D + SCORE_RECENT_7D + SCORE_VERY_RECENT_24H
    elif age_days < 7:
        score += SCORE_RECENT_30D + SCORE_RECENT_7D
    elif age_days < 30:
        score += SCORE_RECENT_30D

    # Avatar
    has_custom = member.avatar is not None
    parts["has_custom_avatar"] = 1 if has_custom else 0
    if not has_custom:
        score += SCORE_NO_AVATAR

    # Pseudo
    pseudo_score = _score_pseudo(member.name)
    parts["pseudo_score"] = pseudo_score
    score += pseudo_score

    parts["total_score"] = score
    return parts


def _detect_pseudo_twins(joins: list[dict], current_name: str) -> int:
    """Si un autre joiner récent partage la même 'racine' de pseudo,
    bonus suspicion."""
    if not current_name or len(current_name) < 4:
        return 0
    cur = current_name.lower()
    # On extrait la "racine alpha" en virant les chiffres
    root = re.sub(r"\d+$", "", cur)[:6]
    if len(root) < 3:
        return 0
    for j in joins:
        other = (j.get("name") or "").lower()
        if not other or other == cur:
            continue
        other_root = re.sub(r"\d+$", "", other)[:6]
        if other_root == root:
            return SCORE_PSEUDO_TWIN
    return 0


# ─── Hook principal ─────────────────────────────────────────────────────────

async def on_member_join(member: discord.Member):
    """À hook depuis bot.py on_member_join. Score + check cluster."""
    if _get_db is None or member.bot:
        return
    try:
        scored = _score_account(member)
        # Récupère les joins récents (10 min)
        recent = await _get_recent_joins(member.guild.id, minutes=CLUSTER_WINDOW_MIN)
        twin_bonus = _detect_pseudo_twins(recent, member.name)
        scored["total_score"] += twin_bonus

        # Log dans DB
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO raid_join_log "
                "(guild_id, user_id, account_age_days, has_custom_avatar, "
                "pseudo_score, total_score) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    member.guild.id,
                    member.id,
                    scored["account_age_days"],
                    scored["has_custom_avatar"],
                    scored["pseudo_score"],
                    scored["total_score"],
                ),
            )
            await db.commit()

        # Check cluster
        recent_after = await _get_recent_joins(
            member.guild.id, minutes=CLUSTER_WINDOW_MIN
        )
        suspicious = [
            j for j in recent_after
            if j.get("total_score", 0) >= SUSPICIOUS_THRESHOLD
        ]
        if len(suspicious) >= MIN_SUSPICIOUS_FOR_ALERT:
            # Vérifier qu'on n'a pas déjà alerté pour ce cluster
            recent_alert = await _has_recent_alert(member.guild.id, minutes=30)
            if not recent_alert:
                await _create_alert(member.guild, suspicious)
    except Exception as ex:
        print(f"[raid_detector on_member_join] {ex}")


async def _get_recent_joins(guild_id: int, minutes: int) -> list[dict]:
    """Renvoie les joins des N dernières minutes pour ce guild."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, joined_at, account_age_days, "
                "has_custom_avatar, pseudo_score, total_score "
                "FROM raid_join_log "
                "WHERE guild_id=? AND joined_at >= ? "
                "ORDER BY joined_at DESC LIMIT ?",
                (guild_id, cutoff.strftime("%Y-%m-%d %H:%M:%S"),
                 ROLLING_WINDOW_SIZE),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "user_id": int(r[0]),
                "joined_at": r[1],
                "account_age_days": int(r[2] or 0),
                "has_custom_avatar": int(r[3] or 0),
                "pseudo_score": int(r[4] or 0),
                "total_score": int(r[5] or 0),
                "name": "",  # rempli côté caller si nécessaire
            })
        return out
    except Exception as ex:
        print(f"[raid_detector _get_recent_joins] {ex}")
        return []


async def _has_recent_alert(guild_id: int, minutes: int) -> bool:
    """True si un alert pending existe dans la fenêtre."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM raid_alerts "
                "WHERE guild_id=? AND created_at >= ? AND status='pending'",
                (guild_id, cutoff.strftime("%Y-%m-%d %H:%M:%S")),
            ) as cur:
                row = await cur.fetchone()
        return bool(row and int(row[0] or 0) > 0)
    except Exception:
        return False


async def _create_alert(guild: discord.Guild, suspicious: list[dict]):
    """Crée une alerte + DM owner + log."""
    try:
        avg = sum(s.get("total_score", 0) for s in suspicious) / max(1, len(suspicious))
        members_payload = []
        for s in suspicious[:15]:
            m = guild.get_member(int(s["user_id"]))
            members_payload.append({
                "user_id": s["user_id"],
                "name": m.name if m else f"User-{s['user_id']}",
                "score": s["total_score"],
                "age_days": s["account_age_days"],
            })

        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO raid_alerts (guild_id, members_jsonb, avg_score) "
                "VALUES (?, ?, ?)",
                (guild.id, json.dumps(members_payload), avg),
            )
            alert_id = cur.lastrowid
            await db.commit()

        # DM owner
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except Exception:
                owner = None
        if owner:
            try:
                lines = [
                    f"🚨 **ALERTE RAID DÉTECTÉ — {guild.name}**",
                    f"",
                    f"**{len(suspicious)}** comptes suspects ont rejoint en "
                    f"< {CLUSTER_WINDOW_MIN} min.",
                    f"Score moyen : `{avg:.1f}` / 13 (seuil : {SUSPICIOUS_THRESHOLD})",
                    f"",
                    f"**Échantillon (top 5) :**",
                ]
                for m in members_payload[:5]:
                    age = m["age_days"]
                    age_str = f"{age}j" if age < 90 else f"{age // 30}m"
                    lines.append(
                        f"• `{m['name']}` — compte créé il y a **{age_str}** "
                        f"— score `{m['score']}`"
                    )
                lines.append("")
                lines.append(
                    "_Ouvre le panel Sécurité pour décider : "
                    "Lockdown 30 min ou Ignorer (faux positif)._"
                )
                lines.append(f"_Alert ID : `{alert_id}`_")

                await owner.send("\n".join(lines))

                # Envoyer le panel avec les boutons (DynamicItem persistants)
                try:
                    panel = build_alert_panel(guild, alert_id)
                    if panel:
                        await owner.send(view=panel)
                except Exception as ex:
                    print(f"[raid_detector DM panel] {ex}")
            except Exception as ex:
                print(f"[raid_detector DM owner] {ex}")
    except Exception as ex:
        print(f"[raid_detector _create_alert] {ex}")


# ─── Lockdown ───────────────────────────────────────────────────────────────

async def run_lockdown(guild: discord.Guild, duration_min: int = 30) -> dict:
    """Active la quarantaine : désactive invites + crée rôle 'Vérification'
    pour les nouveaux arrivants pendant duration_min minutes.
    """
    out = {"invites_disabled": 0, "verify_role_id": None, "errors": []}
    try:
        # 1) Désactive toutes les invitations existantes
        try:
            invites = await guild.invites()
            for inv in invites:
                try:
                    await inv.delete(reason="Anti-raid lockdown")
                    out["invites_disabled"] += 1
                except Exception:
                    pass
        except Exception as ex:
            out["errors"].append(f"invites: {ex}")

        # 2) Crée ou trouve le rôle Vérification
        verify_role = None
        for r in guild.roles:
            if r.name.lower() in ("vérification", "verification", "verify",
                                  "quarantaine"):
                verify_role = r
                break
        if verify_role is None:
            try:
                verify_role = await guild.create_role(
                    name="Vérification",
                    reason="Anti-raid auto",
                    color=discord.Color.dark_grey(),
                )
                # Restreindre permissions par défaut sur tous les salons
                for ch in guild.channels:
                    try:
                        await ch.set_permissions(
                            verify_role,
                            send_messages=False,
                            add_reactions=False,
                            speak=False,
                            reason="Anti-raid lockdown",
                        )
                    except Exception:
                        pass
            except Exception as ex:
                out["errors"].append(f"role: {ex}")

        if verify_role:
            out["verify_role_id"] = verify_role.id

        # 3) Enregistre la fin du lockdown dans config
        if _db_get is not None:
            try:
                async with _get_db() as db:
                    expires = (datetime.now(timezone.utc)
                               + timedelta(minutes=duration_min))
                    await db.execute(
                        "INSERT OR REPLACE INTO raid_alerts "
                        "(alert_id, guild_id, members_jsonb, avg_score, status) "
                        "SELECT alert_id, guild_id, members_jsonb, avg_score, "
                        "'locked_until_' || ? FROM raid_alerts "
                        "WHERE guild_id=? AND status='pending' "
                        "ORDER BY alert_id DESC LIMIT 1",
                        (expires.isoformat(), guild.id),
                    )
                    await db.commit()
            except Exception:
                pass

    except Exception as ex:
        out["errors"].append(f"general: {ex}")
    return out


async def end_lockdown(guild: discord.Guild) -> bool:
    """Désactive le rôle Vérification (le supprime) — appelé par scheduler
    ou manuellement par owner."""
    try:
        for r in guild.roles:
            if r.name.lower() in ("vérification", "verification", "verify"):
                try:
                    await r.delete(reason="Fin du lockdown anti-raid")
                except Exception:
                    pass
        # Marquer les alerts comme resolved
        async with _get_db() as db:
            await db.execute(
                "UPDATE raid_alerts SET status='resolved' "
                "WHERE guild_id=? AND status LIKE 'locked%'",
                (guild.id,),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[raid_detector end_lockdown] {ex}")
        return False


# ─── DynamicItem pour les boutons d'alerte raid (Phase 150) ───────────────
# Pattern : raid_<action>_<guild_id>_<alert_id>
# Actions : lockdown, ignore, details

_RAID_ACTION_LABELS = {
    "lockdown": ("🔒 Lockdown 30 min", discord.ButtonStyle.danger),
    "ignore":   ("✅ Ignorer (faux positif)", discord.ButtonStyle.success),
    "details":  ("📋 Voir détails", discord.ButtonStyle.secondary),
}


class RaidAlertButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"raid_(?P<action>lockdown|ignore|details)_(?P<gid>\d+)_(?P<aid>\d+)",
):
    """Bouton persistant pour les alertes raid. Survit aux reboots."""

    def __init__(self, action: str, guild_id: int, alert_id: int):
        label, style = _RAID_ACTION_LABELS.get(
            action, ("?", discord.ButtonStyle.secondary)
        )
        super().__init__(
            Button(
                label=label,
                style=style,
                custom_id=f"raid_{action}_{guild_id}_{alert_id}",
            )
        )
        self.action = action
        self.guild_id = guild_id
        self.alert_id = alert_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction,
        item: discord.ui.Button, match: re.Match,
    ):
        return cls(
            match["action"], int(match["gid"]), int(match["aid"])
        )

    async def callback(self, interaction: discord.Interaction):
        await _handle_alert_action(
            interaction, self.guild_id, self.alert_id, self.action
        )


async def _handle_alert_action(
    i: discord.Interaction, guild_id: int, alert_id: int, action: str,
):
    """Traite le clic sur un bouton d'alerte raid."""
    try:
        # Owner / super-owner / admin uniquement
        is_authorized = False
        if _owner_ids.is_super_owner(i.user.id):  # super-owner (GoRipe inclus)
            is_authorized = True
        if i.guild and i.user.id == i.guild.owner_id:
            is_authorized = True
        if i.guild:
            try:
                m = i.guild.get_member(i.user.id)
                if m and m.guild_permissions.administrator:
                    is_authorized = True
            except Exception:
                pass
        if not is_authorized:
            return await i.response.send_message(
                "🔒 Owner ou admin uniquement.", ephemeral=True
            )

        await i.response.defer(ephemeral=True)
        guild = i.guild or (_bot.get_guild(guild_id) if _bot else None)
        if not guild:
            return await i.followup.send(
                "❌ Guild introuvable.", ephemeral=True
            )

        if action == "lockdown":
            result = await run_lockdown(guild, duration_min=30)
            await i.followup.send(
                f"🔒 **Lockdown 30 min activé.**\n"
                f"• Invitations désactivées : `{result['invites_disabled']}`\n"
                f"• Rôle Vérification : "
                f"`{result.get('verify_role_id') or 'non créé'}`\n"
                f"• Erreurs : `{len(result.get('errors', []))}`",
                ephemeral=True,
            )

        elif action == "ignore":
            # Marque l'alerte comme false positive
            if _get_db is not None:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE raid_alerts SET status='false_positive' "
                        "WHERE alert_id=?",
                        (alert_id,),
                    )
                    await db.commit()
            await i.followup.send(
                "✅ **Alerte marquée comme faux positif.**\n"
                "_Aucune action prise. Surge légitime confirmé._",
                ephemeral=True,
            )

        elif action == "details":
            if _get_db is None:
                return await i.followup.send("❌ DB indispo.", ephemeral=True)
            async with _get_db() as db:
                async with db.execute(
                    "SELECT members_jsonb, avg_score, created_at "
                    "FROM raid_alerts WHERE alert_id=?",
                    (alert_id,),
                ) as cur:
                    row = await cur.fetchone()
            if not row:
                return await i.followup.send(
                    "❌ Alerte introuvable.", ephemeral=True
                )
            members = json.loads(row[0]) if row[0] else []
            lines = [
                f"📋 **Alerte raid #`{alert_id}`**",
                f"_Score moyen : `{float(row[1] or 0):.1f}`_",
                f"_Créée : `{row[2]}`_",
                "",
                "**Comptes suspects :**",
            ]
            for m in members[:15]:
                age = m.get("age_days", 0)
                age_str = f"{age}j" if age < 90 else f"{age // 30}m"
                lines.append(
                    f"• `{m.get('name', '?')}` — créé il y a **{age_str}** "
                    f"— score `{m.get('score', 0)}`"
                )
            await i.followup.send("\n".join(lines), ephemeral=True)

        # Supprime le panel après action (sauf details)
        if action in ("lockdown", "ignore"):
            try:
                if i.message:
                    await i.message.delete()
            except Exception:
                pass
    except Exception as ex:
        print(f"[_handle_alert_action] {ex}")
        try:
            if not i.response.is_done():
                await i.response.send_message(
                    f"❌ Erreur : `{ex}`", ephemeral=True
                )
            else:
                await i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
        except Exception:
            pass


def register_persistent_views(bot_instance):
    """Enregistre le DynamicItem pour les boutons d'alerte raid."""
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(RaidAlertButton)
    except Exception as ex:
        print(f"[raid_detector register_persistent_views] {ex}")


# ─── Panel V2 review (utilisé via bouton DM ou panel sécurité) ─────────────

def build_alert_panel(guild: discord.Guild, alert_id: int):
    """LayoutView V2 pour review d'une alerte + actions."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _AlertPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            items = []
            items.append(v2_title("🚨  ALERTE RAID"))
            items.append(v2_body(
                f"Serveur : **{guild.name}**\n"
                f"Alert ID : `{alert_id}`\n\n"
                f"Le système a détecté **5+** comptes suspects qui ont "
                f"rejoint en moins de **{CLUSTER_WINDOW_MIN} min**.\n"
                f"Signatures combinées : âge compte, avatar, pseudo, twins."
            ))
            items.append(v2_divider())
            items.append(v2_body(
                "**Décision :**\n"
                "• `Lockdown 30 min` — désactive invites + rôle Vérification\n"
                "• `Ignorer` — faux positif (surge live/partenariat)\n"
                "• `Voir détails` — liste des comptes suspects"
            ))
            self.add_item(v2_container(*items, color=0xE74C3C))

            # Phase 235.5 : un DynamicItem ne peut PAS être un composant
            # top-level d'une LayoutView (400 50035 à l'envoi). On crée des Button
            # NORMAUX portant le MÊME custom_id `raid_<action>_<gid>_<aid>` : le
            # DynamicItem RaidAlertButton enregistré au boot (add_dynamic_items)
            # matche ce custom_id au clic → comportement + persistance identiques.
            _raid_btns = []
            for action in ("lockdown", "ignore", "details"):
                _lbl, _sty = _RAID_ACTION_LABELS.get(
                    action, ("?", discord.ButtonStyle.secondary)
                )
                _raid_btns.append(Button(
                    label=_lbl,
                    style=_sty,
                    custom_id=f"raid_{action}_{guild.id}_{alert_id}",
                ))
            try:
                self.add_item(discord.ui.ActionRow(*_raid_btns))
            except Exception as ex:
                print(f"[build_alert_panel add row] {ex}")

    return _AlertPanel()


__all__ = [
    "setup",
    "init_db",
    "on_member_join",
    "run_lockdown",
    "end_lockdown",
    "build_alert_panel",
]
