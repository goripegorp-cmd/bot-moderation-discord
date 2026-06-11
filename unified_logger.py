"""
unified_logger.py - Logger unifie (Phase 3.7).

Tous les evenements du bot vont dans UN SEUL salon de logs (configurable
par le owner), differencies par type avec couleur + icone + format clair
en francais.

Types d'evenements supportes (extensible) :
    - MOD_BAN, MOD_KICK, MOD_MUTE, MOD_TIMEOUT, MOD_WARN, MOD_UNWARN, MOD_PURGE
    - SECURITY_SPAM, SECURITY_RAID, SECURITY_PHISHING, SECURITY_SCAM,
      SECURITY_BADWORD, SECURITY_BLOCKED_USER
    - MEMBER_JOIN, MEMBER_LEAVE, MEMBER_BAN, MEMBER_UNBAN, MEMBER_UPDATE
    - MESSAGE_DELETE, MESSAGE_EDIT, MESSAGE_BULK_DELETE
    - VOICE_JOIN, VOICE_LEAVE, VOICE_MOVE
    - CHANNEL_CREATE, CHANNEL_DELETE, CHANNEL_UPDATE
    - ROLE_CREATE, ROLE_DELETE, ROLE_UPDATE
    - TICKET_OPEN, TICKET_CLOSE, TICKET_CLAIM
    - CONFIG_CHANGE, COMMAND_EXEC

API :
    set_log_channel(guild_id, channel_id) - configurer le salon
    get_log_channel(guild_id) -> int
    log_event(bot, guild_id, event_type, **details) - envoyer un log
    log_*(bot, guild, ...) helpers pratiques par type
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Any

import discord

from paths import module_dir


DATA_DIR = module_dir("unified_logs")


# =============================================================================
# TYPES D'EVENEMENTS
# =============================================================================

class EventType(str, Enum):
    # Moderation
    MOD_BAN = "mod.ban"
    MOD_UNBAN = "mod.unban"
    MOD_KICK = "mod.kick"
    MOD_MUTE = "mod.mute"
    MOD_UNMUTE = "mod.unmute"
    MOD_TIMEOUT = "mod.timeout"
    MOD_WARN = "mod.warn"
    MOD_UNWARN = "mod.unwarn"
    MOD_PURGE = "mod.purge"
    MOD_LOCK = "mod.lock"
    MOD_UNLOCK = "mod.unlock"
    MOD_SLOWMODE = "mod.slowmode"

    # Securite / Automod
    SEC_SPAM = "sec.spam"
    SEC_RAID = "sec.raid"
    SEC_PHISHING = "sec.phishing"
    SEC_SCAM = "sec.scam"
    SEC_BADWORD = "sec.badword"
    SEC_LINK = "sec.link"
    SEC_INVITE = "sec.invite"
    SEC_MENTION = "sec.mention"
    SEC_IMAGE = "sec.image"
    SEC_NEWACCOUNT = "sec.newaccount"
    SEC_ALT = "sec.alt"
    SEC_QRCODE = "sec.qrcode"
    SEC_NSFW = "sec.nsfw"

    # Membres
    MEMBER_JOIN = "member.join"
    MEMBER_LEAVE = "member.leave"
    MEMBER_UPDATE = "member.update"
    MEMBER_BOOSTED = "member.boosted"

    # Messages
    MSG_DELETE = "msg.delete"
    MSG_EDIT = "msg.edit"
    MSG_BULK_DELETE = "msg.bulk_delete"

    # Vocal
    VOICE_JOIN = "voice.join"
    VOICE_LEAVE = "voice.leave"
    VOICE_MOVE = "voice.move"

    # Channels / Roles
    CHAN_CREATE = "chan.create"
    CHAN_DELETE = "chan.delete"
    CHAN_UPDATE = "chan.update"
    ROLE_CREATE = "role.create"
    ROLE_DELETE = "role.delete"
    ROLE_UPDATE = "role.update"

    # Tickets
    TICKET_OPEN = "ticket.open"
    TICKET_CLOSE = "ticket.close"
    TICKET_CLAIM = "ticket.claim"

    # Config
    CONFIG_CHANGE = "config.change"
    COMMAND_EXEC = "command.exec"
    BOT_INFO = "bot.info"


# Metadata par type : icone + couleur + label + categorie
EVENT_META: dict[EventType, dict] = {
    # MODERATION (rouge / orange selon severite)
    EventType.MOD_BAN:       {"icon": "🔨", "color": 0xE74C3C, "label": "Bannissement",        "cat": "Modération"},
    EventType.MOD_UNBAN:     {"icon": "🔓", "color": 0x2ECC71, "label": "Débannissement",      "cat": "Modération"},
    EventType.MOD_KICK:      {"icon": "👢", "color": 0xE67E22, "label": "Expulsion",           "cat": "Modération"},
    EventType.MOD_MUTE:      {"icon": "🔇", "color": 0xE67E22, "label": "Mute",                "cat": "Modération"},
    EventType.MOD_UNMUTE:    {"icon": "🔊", "color": 0x2ECC71, "label": "Unmute",              "cat": "Modération"},
    EventType.MOD_TIMEOUT:   {"icon": "⏱️", "color": 0xE67E22, "label": "Timeout",             "cat": "Modération"},
    EventType.MOD_WARN:      {"icon": "⚠️", "color": 0xF1C40F, "label": "Avertissement",       "cat": "Modération"},
    EventType.MOD_UNWARN:    {"icon": "✅", "color": 0x2ECC71, "label": "Avertissement retiré","cat": "Modération"},
    EventType.MOD_PURGE:     {"icon": "🧹", "color": 0x9B59B6, "label": "Purge messages",      "cat": "Modération"},
    EventType.MOD_LOCK:      {"icon": "🔒", "color": 0xE67E22, "label": "Salon verrouillé",    "cat": "Modération"},
    EventType.MOD_UNLOCK:    {"icon": "🔓", "color": 0x2ECC71, "label": "Salon déverrouillé",  "cat": "Modération"},
    EventType.MOD_SLOWMODE:  {"icon": "🐢", "color": 0x95A5A6, "label": "Slowmode",            "cat": "Modération"},

    # SECURITE (rouge automod)
    EventType.SEC_SPAM:      {"icon": "🚫", "color": 0xE74C3C, "label": "Spam détecté",        "cat": "Sécurité"},
    EventType.SEC_RAID:      {"icon": "⚔️", "color": 0xC0392B, "label": "Raid détecté",        "cat": "Sécurité"},
    EventType.SEC_PHISHING:  {"icon": "🎣", "color": 0xC0392B, "label": "Phishing détecté",    "cat": "Sécurité"},
    EventType.SEC_SCAM:      {"icon": "💰", "color": 0xC0392B, "label": "Scam détecté",        "cat": "Sécurité"},
    EventType.SEC_BADWORD:   {"icon": "🤬", "color": 0xE67E22, "label": "Mot interdit",        "cat": "Sécurité"},
    EventType.SEC_LINK:      {"icon": "🔗", "color": 0xE67E22, "label": "Lien non autorisé",   "cat": "Sécurité"},
    EventType.SEC_INVITE:    {"icon": "📨", "color": 0xE67E22, "label": "Invite Discord",       "cat": "Sécurité"},
    EventType.SEC_MENTION:   {"icon": "📢", "color": 0xE67E22, "label": "Mass mention",        "cat": "Sécurité"},
    EventType.SEC_IMAGE:     {"icon": "🖼️", "color": 0xE67E22, "label": "Image bloquée",       "cat": "Sécurité"},
    EventType.SEC_NEWACCOUNT:{"icon": "🆕", "color": 0xF1C40F, "label": "Compte récent",       "cat": "Sécurité"},
    EventType.SEC_ALT:       {"icon": "👥", "color": 0xC0392B, "label": "Alt détecté",         "cat": "Sécurité"},
    EventType.SEC_QRCODE:    {"icon": "📱", "color": 0xC0392B, "label": "QR code détecté",     "cat": "Sécurité"},
    EventType.SEC_NSFW:      {"icon": "🔞", "color": 0xE67E22, "label": "NSFW détecté",        "cat": "Sécurité"},

    # MEMBRES (vert / bleu)
    EventType.MEMBER_JOIN:   {"icon": "👋", "color": 0x2ECC71, "label": "Arrivée membre",      "cat": "Membres"},
    EventType.MEMBER_LEAVE:  {"icon": "🚪", "color": 0x95A5A6, "label": "Départ membre",       "cat": "Membres"},
    EventType.MEMBER_UPDATE: {"icon": "✏️", "color": 0x3498DB, "label": "Membre modifié",      "cat": "Membres"},
    EventType.MEMBER_BOOSTED:{"icon": "💎", "color": 0xEB459E, "label": "Boost serveur",       "cat": "Membres"},

    # MESSAGES (gris)
    EventType.MSG_DELETE:    {"icon": "🗑️", "color": 0xE74C3C, "label": "Message supprimé",     "cat": "Messages"},
    EventType.MSG_EDIT:      {"icon": "✏️", "color": 0x3498DB, "label": "Message édité",       "cat": "Messages"},
    EventType.MSG_BULK_DELETE:{"icon": "🧹", "color": 0x9B59B6, "label": "Purge messages",     "cat": "Messages"},

    # VOCAL (cyan)
    EventType.VOICE_JOIN:    {"icon": "🎤", "color": 0x1ABC9C, "label": "Connexion vocal",     "cat": "Vocal"},
    EventType.VOICE_LEAVE:   {"icon": "🚪", "color": 0x95A5A6, "label": "Déconnexion vocal",   "cat": "Vocal"},
    EventType.VOICE_MOVE:    {"icon": "↔️", "color": 0x1ABC9C, "label": "Déplacement vocal",   "cat": "Vocal"},

    # SERVEUR (bleu)
    EventType.CHAN_CREATE:   {"icon": "➕", "color": 0x2ECC71, "label": "Salon créé",          "cat": "Serveur"},
    EventType.CHAN_DELETE:   {"icon": "➖", "color": 0xE74C3C, "label": "Salon supprimé",      "cat": "Serveur"},
    EventType.CHAN_UPDATE:   {"icon": "✏️", "color": 0x3498DB, "label": "Salon modifié",      "cat": "Serveur"},
    EventType.ROLE_CREATE:   {"icon": "🎭", "color": 0x2ECC71, "label": "Rôle créé",           "cat": "Serveur"},
    EventType.ROLE_DELETE:   {"icon": "🎭", "color": 0xE74C3C, "label": "Rôle supprimé",       "cat": "Serveur"},
    EventType.ROLE_UPDATE:   {"icon": "🎭", "color": 0x3498DB, "label": "Rôle modifié",        "cat": "Serveur"},

    # TICKETS (violet)
    EventType.TICKET_OPEN:   {"icon": "🎫", "color": 0x9B59B6, "label": "Ticket ouvert",       "cat": "Tickets"},
    EventType.TICKET_CLOSE:  {"icon": "🔒", "color": 0x95A5A6, "label": "Ticket fermé",        "cat": "Tickets"},
    EventType.TICKET_CLAIM:  {"icon": "🙋", "color": 0x3498DB, "label": "Ticket assigné",      "cat": "Tickets"},

    # CONFIG (gris)
    EventType.CONFIG_CHANGE: {"icon": "⚙️", "color": 0x95A5A6, "label": "Configuration",      "cat": "Config"},
    EventType.COMMAND_EXEC:  {"icon": "⚡", "color": 0x95A5A6, "label": "Commande utilisée",   "cat": "Config"},
    EventType.BOT_INFO:      {"icon": "ℹ️", "color": 0x3498DB, "label": "Info bot",            "cat": "Config"},
}


# =============================================================================
# CONFIG (1 salon par guild)
# =============================================================================

def _cfg_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}.json"


async def get_log_channel(guild_id: int) -> Optional[int]:
    """Recupere l'ID du salon de logs configure pour ce serveur."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cid = data.get("channel_id", 0)
        return int(cid) if cid else None
    except (json.JSONDecodeError, OSError, ValueError):
        return None


async def set_log_channel(guild_id: int, channel_id: int) -> None:
    """Configure le salon de logs pour ce serveur (preserve les autres champs)."""
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    data["channel_id"] = int(channel_id)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def get_enabled_categories(guild_id: int) -> set[str]:
    """Categories de logs activees pour ce guild (par defaut : toutes)."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return set(c["cat"] for c in EVENT_META.values())
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cats = data.get("enabled_categories")
        if cats is None:
            return set(c["cat"] for c in EVENT_META.values())
        return set(cats)
    except Exception:
        return set(c["cat"] for c in EVENT_META.values())


async def set_enabled_categories(guild_id: int, categories: set[str]) -> None:
    """Configure les categories de logs activees."""
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    data["enabled_categories"] = sorted(categories)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# =============================================================================
# ROUTAGE PAR CATEGORIE (Phase 268 — demande owner : 1 salon par type de log)
# =============================================================================
# Chaque categorie de logs (Modération, Sécurité, Membres, Messages, Vocal,
# Serveur, Tickets, Config) peut etre envoyee dans un salon DEDIE. Si aucun salon
# n'est defini pour une categorie, on retombe sur le salon GLOBAL (set_log_channel).

# Liste canonique des categories (ordre d'affichage), derivee de EVENT_META.
LOG_CATEGORIES: list[str] = []
for _m in EVENT_META.values():
    if _m["cat"] not in LOG_CATEGORIES:
        LOG_CATEGORIES.append(_m["cat"])


async def get_category_channels(guild_id: int) -> dict[str, int]:
    """Retourne { categorie: channel_id } pour les categories routees explicitement."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("category_channels", {}) or {}
        out: dict[str, int] = {}
        for k, v in raw.items():
            try:
                cid = int(v)
                if cid:
                    out[str(k)] = cid
            except (TypeError, ValueError):
                continue
        return out
    except Exception:
        return {}


async def set_category_channel(guild_id: int, category: str, channel_id: Optional[int]) -> None:
    """Route une categorie vers un salon. channel_id None/0 => retire le routage
    (la categorie retombe alors sur le salon global)."""
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    cc = data.get("category_channels", {}) or {}
    if channel_id:
        cc[str(category)] = int(channel_id)
    else:
        cc.pop(str(category), None)
    data["category_channels"] = cc
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def resolve_channel_for_category(guild_id: int, category: Optional[str]) -> Optional[int]:
    """Salon cible pour une categorie : salon dedie si defini, sinon salon global."""
    if category:
        try:
            cc = await get_category_channels(guild_id)
            if category in cc:
                return cc[category]
        except Exception:
            pass
    return await get_log_channel(guild_id)


# Routage encore plus fin : 1 salon pour un EVENT_TYPE precis (ex: sec.phishing seul).
# Priorite de resolution : évènement précis > catégorie > salon global.

async def get_event_channels(guild_id: int) -> dict[str, int]:
    """Retourne { event_type_value: channel_id } pour les évènements routés explicitement."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("event_channels", {}) or {}
        out: dict[str, int] = {}
        for k, v in raw.items():
            try:
                cid = int(v)
                if cid:
                    out[str(k)] = cid
            except (TypeError, ValueError):
                continue
        return out
    except Exception:
        return {}


async def set_event_channel(guild_id: int, event_value: str, channel_id: Optional[int]) -> None:
    """Route un évènement précis vers un salon. channel_id None/0 ⇒ retire l'override
    (l'évènement retombe alors sur le salon de sa catégorie, sinon le salon global)."""
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    ec = data.get("event_channels", {}) or {}
    if channel_id:
        ec[str(event_value)] = int(channel_id)
    else:
        ec.pop(str(event_value), None)
    data["event_channels"] = ec
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def resolve_channel_for_event(guild_id: int, event_value: Optional[str],
                                    category: Optional[str]) -> Optional[int]:
    """Salon cible : override évènement si défini, sinon salon de catégorie, sinon global."""
    if event_value:
        try:
            ec = await get_event_channels(guild_id)
            if event_value in ec:
                return ec[event_value]
        except Exception:
            pass
    return await resolve_channel_for_category(guild_id, category)


# =============================================================================
# MODE WEBHOOK (Phase 268 — rendu "pro") : poster les logs via un webhook dont le
# nom = la catégorie (« 🛡️ Sécurité », « 🔨 Modération »…). OFF par défaut →
# aucun changement de comportement tant que l'owner ne l'active pas. Repli auto
# sur l'envoi normal en cas d'échec.
# =============================================================================

_CAT_ICON = {
    "Modération": "🔨", "Sécurité": "🛡️", "Membres": "👥", "Messages": "💬",
    "Vocal": "🎤", "Serveur": "🏷️", "Tickets": "🎫", "Config": "⚙️",
}
_log_webhook_cache: dict = {}  # channel_id -> discord.Webhook


async def get_webhook_mode(guild_id: int) -> bool:
    p = _cfg_path(guild_id)
    if not p.exists():
        return False
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")).get("webhook_mode", False))
    except Exception:
        return False


async def set_webhook_mode(guild_id: int, on: bool) -> None:
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    data["webhook_mode"] = bool(on)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def _get_or_create_log_webhook(channel):
    """Webhook « Abylumis Logs » du salon (réutilisé si existant, sinon créé), mis en
    cache par channel_id. Renvoie None si impossible (perms, type de salon)."""
    try:
        cid = channel.id
        cached = _log_webhook_cache.get(cid)
        if cached is not None:
            return cached
        if not hasattr(channel, "create_webhook"):
            return None  # threads / types sans webhook
        try:
            for w in await channel.webhooks():
                if w.name == "Abylumis Logs":
                    _log_webhook_cache[cid] = w
                    return w
        except Exception:
            pass
        w = await channel.create_webhook(name="Abylumis Logs",
                                         reason="Logs unifiés (mode webhook)")
        _log_webhook_cache[cid] = w
        return w
    except Exception:
        return None


# =============================================================================
# PHASE 26.3 : EXCLUSIONS PAR EVENEMENT + EVENEMENTS DESACTIVES PRECISEMENT
# =============================================================================

async def get_disabled_events(guild_id: int) -> set[str]:
    """Liste des event_type DESACTIVES specifiquement (en plus des categories)."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return set(data.get("disabled_events", []) or [])
    except Exception:
        return set()


async def set_disabled_events(guild_id: int, events: set[str]) -> None:
    """Persiste la liste des event_type desactives."""
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    data["disabled_events"] = sorted(events)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def get_role_exclusions(guild_id: int) -> dict:
    """Retourne { event_type_str: [role_id, ...] } — roles epargnes pour chaque event."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = data.get("role_exclusions", {}) or {}
        # Sanitize : convertir les role_id en int
        out = {}
        for k, v in raw.items():
            if isinstance(v, list):
                out[str(k)] = [int(x) for x in v if str(x).lstrip('-').isdigit()]
        return out
    except Exception:
        return {}


async def set_role_exclusions(guild_id: int, exclusions: dict) -> None:
    """Persiste { event_type_str: [role_id, ...] }."""
    p = _cfg_path(guild_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    sanitized = {}
    for k, v in (exclusions or {}).items():
        if isinstance(v, list):
            sanitized[str(k)] = [int(x) for x in v if str(x).lstrip('-').isdigit()]
    data["role_exclusions"] = sanitized
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _user_has_excluded_role(user, excluded_role_ids: list[int]) -> bool:
    """True si l'utilisateur a au moins l'un des roles dans la liste d'exclusion."""
    if not user or not excluded_role_ids:
        return False
    try:
        user_role_ids = {r.id for r in getattr(user, 'roles', []) or []}
        return any(int(rid) in user_role_ids for rid in excluded_role_ids)
    except Exception:
        return False


# =============================================================================
# BUILD EVENT VIEW
# =============================================================================

def _format_user(user) -> str:
    """Format mention + tag d'un user."""
    if user is None:
        return "_inconnu_"
    try:
        return f"{user.mention} (`{user}` · `{user.id}`)"
    except Exception:
        return f"`{user}`"


def _format_channel(channel) -> str:
    if channel is None:
        return "_inconnu_"
    try:
        return f"{channel.mention} (`#{channel.name}` · `{channel.id}`)"
    except Exception:
        return f"`{channel}`"


def build_log_embed(
    event_type: EventType,
    *,
    title_override: Optional[str] = None,
    description: str = "",
    fields: Optional[list[tuple[str, str, bool]]] = None,
    user: Optional[Any] = None,
    moderator: Optional[Any] = None,
    channel: Optional[Any] = None,
    reason: Optional[str] = None,
    content: Optional[str] = None,
    extra: Optional[dict] = None,
) -> discord.Embed:
    """Construit un embed propre pour un evenement.

    Format pro avec :
    - Couleur par type
    - Titre [icone + label]
    - Description claire
    - Fields user/moderator/channel/reason/content
    - Footer avec event type et timestamp
    """
    meta = EVENT_META.get(event_type, {
        "icon": "📋", "color": 0x95A5A6, "label": "Évenement", "cat": "Autre",
    })

    embed = discord.Embed(
        color=meta["color"],
        timestamp=datetime.now(timezone.utc),
        description=description[:4000] if description else None,
    )
    embed.set_author(name=f"{meta['icon']} {title_override or meta['label']}")

    if user is not None:
        embed.add_field(name="👤 Concerné", value=_format_user(user), inline=False)
    if moderator is not None:
        embed.add_field(name="🛡️ Modérateur", value=_format_user(moderator), inline=False)
    if channel is not None:
        embed.add_field(name="📺 Salon", value=_format_channel(channel), inline=False)
    if reason:
        embed.add_field(name="📝 Raison", value=reason[:1024], inline=False)
    if content:
        embed.add_field(name="💬 Contenu", value=f"```\n{content[:900]}\n```", inline=False)
    if extra:
        for k, v in extra.items():
            embed.add_field(name=str(k)[:256], value=str(v)[:1024], inline=False)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=str(name)[:256], value=str(value)[:1024], inline=bool(inline))

    embed.set_footer(text=f"[{meta['cat']}] · type={event_type.value}")
    return embed


# =============================================================================
# LOG EVENT
# =============================================================================

async def log_event(
    bot: discord.Client,
    guild: discord.Guild,
    event_type: EventType,
    *,
    title_override: Optional[str] = None,
    description: str = "",
    fields: Optional[list[tuple[str, str, bool]]] = None,
    user: Optional[Any] = None,
    moderator: Optional[Any] = None,
    channel: Optional[Any] = None,
    reason: Optional[str] = None,
    content: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Optional[discord.Message]:
    """Envoie un log dans le salon de la categorie (sinon salon global). Retourne le message ou None."""
    try:
        meta = EVENT_META.get(event_type)

        # Verifier que la categorie est activee (avant toute resolution de salon)
        if meta:
            enabled = await get_enabled_categories(guild.id)
            if meta["cat"] not in enabled:
                return None

        # Phase 268 : routage évènement > catégorie > salon global.
        _ev_val = getattr(event_type, "value", None) or (str(event_type) if event_type else None)
        chan_id = await resolve_channel_for_event(guild.id, _ev_val, meta["cat"] if meta else None)
        if not chan_id:
            return None
        target = bot.get_channel(int(chan_id))
        if target is None:
            return None

        # Phase 26.3 : event-type desactive specifiquement ?
        try:
            disabled = await get_disabled_events(guild.id)
            if event_type.value in disabled:
                return None
        except Exception:
            pass

        # Phase 26.3 : roles epargnes ?
        try:
            exclusions = await get_role_exclusions(guild.id)
            excluded_ids = exclusions.get(event_type.value, []) or []
            if excluded_ids:
                # Si user OU moderator a un role epargne, on skippe le log
                if _user_has_excluded_role(user, excluded_ids) or _user_has_excluded_role(moderator, excluded_ids):
                    return None
        except Exception:
            pass

        embed = build_log_embed(
            event_type,
            title_override=title_override,
            description=description,
            fields=fields,
            user=user,
            moderator=moderator,
            channel=channel,
            reason=reason,
            content=content,
            extra=extra,
        )
        # Mode webhook (Phase 268) : poster via un expéditeur au nom de la catégorie.
        # OFF par défaut → on garde l'envoi normal. Repli auto sur target.send si échec.
        try:
            if meta and await get_webhook_mode(guild.id) and hasattr(target, "create_webhook"):
                wh = await _get_or_create_log_webhook(target)
                if wh is not None:
                    cat = meta["cat"]
                    uname = f"{_CAT_ICON.get(cat, '📋')} {cat}"[:80]
                    av = guild.icon.url if guild.icon else None
                    try:
                        return await wh.send(embed=embed, username=uname,
                                             avatar_url=av, wait=True)
                    except Exception:
                        _log_webhook_cache.pop(target.id, None)  # webhook périmé → repli
        except Exception:
            pass
        return await target.send(embed=embed)
    except Exception as ex:
        import traceback
        print(f"[UNIFIED_LOGGER] erreur log_event {event_type}: {ex}")
        traceback.print_exc()
        return None


# =============================================================================
# HELPERS PRATIQUES PAR TYPE
# =============================================================================

async def log_ban(bot, guild, target_user, moderator, reason=""):
    return await log_event(
        bot, guild, EventType.MOD_BAN,
        description=f"**{target_user}** a été banni du serveur.",
        user=target_user, moderator=moderator, reason=reason,
    )


async def log_kick(bot, guild, target_user, moderator, reason=""):
    return await log_event(
        bot, guild, EventType.MOD_KICK,
        description=f"**{target_user}** a été expulsé du serveur.",
        user=target_user, moderator=moderator, reason=reason,
    )


async def log_mute(bot, guild, target_user, moderator, duration_min=0, reason=""):
    duration_str = f"{duration_min} min" if duration_min else "permanent"
    return await log_event(
        bot, guild, EventType.MOD_MUTE,
        description=f"**{target_user}** a été mute (durée : **{duration_str}**).",
        user=target_user, moderator=moderator, reason=reason,
        extra={"⏱️ Durée": duration_str} if duration_min else None,
    )


async def log_warn(bot, guild, target_user, moderator, reason=""):
    return await log_event(
        bot, guild, EventType.MOD_WARN,
        description=f"**{target_user}** a reçu un avertissement.",
        user=target_user, moderator=moderator, reason=reason,
    )


async def log_purge(bot, guild, moderator, channel, count: int):
    return await log_event(
        bot, guild, EventType.MOD_PURGE,
        description=f"**{count}** message(s) supprimés dans {channel.mention if channel else '_un salon_'}.",
        moderator=moderator, channel=channel,
        extra={"🧹 Quantité": str(count)},
    )


async def log_security_event(bot, guild, event_type, target_user, *,
                              channel=None, content_preview=None, reason=""):
    """Log generique pour les detections automod."""
    meta = EVENT_META.get(event_type, {"label": "Sécurité"})
    return await log_event(
        bot, guild, event_type,
        description=(
            f"**{meta['label']}** détecté sur **{target_user}**." if target_user
            else f"**{meta['label']}** détecté."
        ),
        user=target_user, channel=channel, reason=reason,
        content=content_preview,
    )


async def log_member_join(bot, guild, member):
    days_old = (datetime.now(timezone.utc) - member.created_at).days
    return await log_event(
        bot, guild, EventType.MEMBER_JOIN,
        description=f"👋 **{member}** vient de rejoindre le serveur.",
        user=member,
        extra={
            "📅 Compte créé": f"il y a {days_old} jours",
            "👥 Membres total": str(guild.member_count),
        },
    )


async def log_member_leave(bot, guild, member):
    try:
        joined_str = "_inconnu_"
        if member.joined_at:
            days_in = (datetime.now(timezone.utc) - member.joined_at).days
            joined_str = f"il y a {days_in} jours"
    except Exception:
        joined_str = "_inconnu_"
    return await log_event(
        bot, guild, EventType.MEMBER_LEAVE,
        description=f"🚪 **{member}** a quitté le serveur.",
        user=member,
        extra={"📅 A rejoint": joined_str, "👥 Membres restants": str(guild.member_count)},
    )


async def log_message_delete(bot, guild, message, deleted_by=None):
    if message is None or message.author is None:
        return None
    return await log_event(
        bot, guild, EventType.MSG_DELETE,
        description=(
            f"🗑️ Message de **{message.author}** supprimé dans "
            f"{message.channel.mention if message.channel else '_inconnu_'}."
        ),
        user=message.author, moderator=deleted_by, channel=message.channel,
        content=message.content or "_(contenu vide ou embed)_",
    )


async def log_config_change(bot, guild, moderator, what: str, old=None, new=None):
    return await log_event(
        bot, guild, EventType.CONFIG_CHANGE,
        description=f"⚙️ Configuration modifiée : **{what}**",
        moderator=moderator,
        extra={
            "📝 Avant": str(old) if old is not None else "_(non défini)_",
            "✅ Après": str(new) if new is not None else "_(non défini)_",
        },
    )


__all__ = [
    "EventType",
    "EVENT_META",
    "get_log_channel",
    "set_log_channel",
    "get_enabled_categories",
    "set_enabled_categories",
    "build_log_embed",
    "log_event",
    "log_ban",
    "log_kick",
    "log_mute",
    "log_warn",
    "log_purge",
    "log_security_event",
    "log_member_join",
    "log_member_leave",
    "log_message_delete",
    "log_config_change",
]
