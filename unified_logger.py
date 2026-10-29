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

import copy
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Any

import discord

import registre
import stockage
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
    SEC_ESCALATION = "sec.escalation"
    SEC_MINEURS = "sec.mineurs"   # 29/10/2026 : approche prédatrice — plus classée « Scam »

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
    VOICE_MUTE = "voice.mute"
    VOICE_STREAM = "voice.stream"

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
    EventType.SEC_ESCALATION:{"icon": "🚨", "color": 0xC0392B, "label": "Membre à surveiller",  "cat": "Sécurité"},
    EventType.SEC_MINEURS:   {"icon": "🧒", "color": 0xC0392B, "label": "Protection des mineurs", "cat": "Sécurité"},

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
    EventType.VOICE_MUTE:    {"icon": "🔇", "color": 0xE67E22, "label": "Server-mute / deaf",  "cat": "Vocal"},
    EventType.VOICE_STREAM:  {"icon": "📺", "color": 0x9B59B6, "label": "Stream / caméra",     "cat": "Vocal"},

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


_CFG: dict = {}  # guild_id → (date de modification, configuration) : relue seulement si elle change


def _lire(guild_id: int) -> dict:
    """La configuration (une COPIE). 20/10/2026 : relue à chaque appel, jusqu'à 4 fois par évènement.
    Abîmée : la copie .bak, puis la dernière version lue ; sinon `stockage.Illisible` — jamais {},
    sinon le réglage suivant écraserait tout (mode site compris)."""
    p = _cfg_path(guild_id)
    try:
        cle = p.stat().st_mtime_ns
    except FileNotFoundError:
        _CFG.pop(guild_id, None)
        return {}
    connu = _CFG.get(guild_id)
    if connu is not None and connu[0] == cle:
        return copy.deepcopy(connu[1])
    try:
        data = stockage.lire_json_sur(p) or {}
    except stockage.Illisible:
        if connu is None:
            raise
        print("[UNIFIED_LOGGER][E3] configuration illisible, dernière version gardée")
        print(f"[UNIFIED_LOGGER][E3:DETAIL] {guild_id}")
        return copy.deepcopy(connu[1])
    _CFG[guild_id] = (cle, data)
    return copy.deepcopy(data)


def _ecrire(guild_id: int, data: dict) -> None:
    """Écriture sûre (nom temporaire unique, fsync, .bak) — avant : `write_text`, et une coupure en
    pleine écriture abîmait le fichier."""
    stockage.ecrire_json_sur(_cfg_path(guild_id), json.dumps(data, indent=2, ensure_ascii=False))
    _CFG.pop(guild_id, None)


async def get_log_channel(guild_id: int) -> Optional[int]:
    """Recupere l'ID du salon de logs configure pour ce serveur.
    Mode site : aucun (24/10/2026 — un salon posé après le passage au site recevait encore la purge
    des 30 jours et, en repli, les alertes d'escalade)."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return None
    try:
        data = _lire(guild_id)
        if data.get("site"):
            return None
        cid = data.get("channel_id", 0)
        return int(cid) if cid else None
    except (stockage.Illisible, OSError, ValueError):
        return None


def salons_de_logs(guild_id: int) -> set[int]:
    """Tous les salons où ce journal écrit : global, par catégorie, par évènement.
    Mode site : aucun — les alertes ont leur propre salon (`salon_alertes`). 24/10/2026 : un salon
    choisi par `/logs setchannel` après le passage au site était purgé toutes les 12 h (`menage`)."""
    p = _cfg_path(guild_id)
    try:
        data = _lire(guild_id)
    except (stockage.Illisible, OSError):
        return set()
    if data.get("site"):
        return set()
    ids = {data.get("channel_id")}
    for cle in ("category_channels", "event_channels"):
        ids |= set((data.get(cle) or {}).values())
    out = set()
    for v in ids:
        try:
            if int(v or 0):
                out.add(int(v))
        except (TypeError, ValueError):
            continue
    return out


def remplacer_salon(guild_id: int, ancien: int, nouveau: int) -> None:
    """Un salon de logs recréé : sa nouvelle identité partout dans la configuration."""
    import nettoyage
    p = _cfg_path(guild_id)
    if not p.exists():
        return
    _ecrire(guild_id, nettoyage.remplacer_id(_lire(guild_id), ancien, nouveau))


#  19/10/2026 : « il n'y aura plus de logs sur le serveur Discord, tout sera sur le site ».
#  En mode site, chaque évènement part au registre ; seules ces alertes, qui demandent une
#  réaction humaine, vont encore dans Discord — dans le salon unique. Le raid n'y est pas : ses
#  deux détecteurs postent déjà leur propre alerte (avec les boutons) dans ce salon.
ALERTES = {"sec.escalation"}
#  Branché par le bot : les boutons sous une alerte (« Géré », la fiche sur le site).
vue_alerte = None


def _lire_cfg(guild_id: int) -> dict:
    try:
        return _lire(guild_id)
    except stockage.Illisible:
        print("[UNIFIED_LOGGER][E4] configuration illisible")
        print(f"[UNIFIED_LOGGER][E4:DETAIL] {guild_id}")
        return {}


async def mode_site(guild_id: int) -> bool:
    return bool(_lire_cfg(guild_id).get("site"))


async def salon_alertes(guild_id: int) -> Optional[int]:
    cid = _lire_cfg(guild_id).get("alertes", 0)
    return int(cid) if cid else None


async def activer_site(guild_id: int, alertes_id: int) -> set[int]:
    """Plus aucun salon de logs : l'ancienne configuration est gardée de côté (pour annuler),
    les alertes vont dans `alertes_id`. Rend les salons qui servaient jusque-là."""
    data = _lire_cfg(guild_id)
    anciens = salons_de_logs(guild_id)
    if not data.get("site"):
        data["ancien"] = {k: data.get(k) for k in ("channel_id", "category_channels", "event_channels")}
    data.update({"site": True, "alertes": int(alertes_id or 0), "channel_id": 0,
                 "category_channels": {}, "event_channels": {},
                 "updated_at": datetime.now(timezone.utc).isoformat()})
    _ecrire(guild_id, data)
    return anciens


def _nom_de(x) -> str:
    return getattr(x, "display_name", None) or getattr(x, "name", None) or ""


async def _ecarte(guild_id: int, ev_val, user, moderator) -> bool:
    """Évènement désactivé, ou rôle épargné (Phase 26.3) : ni Discord, ni le site."""
    try:
        if ev_val in await get_disabled_events(guild_id):
            return True
        exclus = (await get_role_exclusions(guild_id)).get(ev_val, []) or []
        return bool(exclus) and (_user_has_excluded_role(user, exclus) or _user_has_excluded_role(moderator, exclus))
    except Exception as ex:  # réglages illisibles : on consigne plutôt que de perdre l'évènement
        print("[UNIFIED_LOGGER][E2] filtres illisibles")
        print(f"[UNIFIED_LOGGER][E2:DETAIL] {guild_id} {type(ex).__name__} {ex}")
        return False


async def _consigner(guild, event_type, meta, *, title_override, description, user, moderator,
                     channel, reason, content, extra) -> None:
    """La version « site » d'un log : une phrase lisible et un détail court, par personne."""
    cat = (meta or {}).get("cat", "Autre")
    if getattr(user, "bot", False) and cat in ("Messages", "Vocal"):
        return
    lib = title_override or (meta or {}).get("label", "Évènement")
    texte = registre.propre(description, guild) if description else ""
    if not texte:
        qui = _nom_de(user)
        texte = f"{lib}" + (f" · {qui}" if qui else "") + (f" · #{getattr(channel, 'name', '')}" if channel else "")
    elif lib and lib.lower() not in texte.lower():
        texte = f"{lib} · {texte}"
    morceaux = [str(content or "").strip(), str(reason or "").strip()]
    morceaux += [f"{registre.propre(str(k))} : {registre.propre(str(v))}" for k, v in (extra or {}).items()]
    await registre.noter(guild.id, cat, getattr(event_type, "value", str(event_type)), texte,
                         membre_id=getattr(user, "id", 0) or 0, auteur_id=getattr(moderator, "id", 0) or 0,
                         salon_id=getattr(channel, "id", 0) or 0,
                         detail=" · ".join(m for m in morceaux if m)[:600],
                         gravite=2 if getattr(event_type, "value", "") in ALERTES else 0)


async def set_log_channel(guild_id: int, channel_id: int) -> None:
    """Configure le salon de logs pour ce serveur (preserve les autres champs)."""
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    data["channel_id"] = int(channel_id)  # le mode (site ou Discord) ne change pas : il a son propre réglage
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


async def get_enabled_categories(guild_id: int) -> set[str]:
    """Categories de logs activees pour ce guild (par defaut : toutes)."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return set(c["cat"] for c in EVENT_META.values())
    try:
        data = _lire(guild_id)
        cats = data.get("enabled_categories")
        if cats is None:
            return set(c["cat"] for c in EVENT_META.values())
        return set(cats)
    except Exception:
        return set(c["cat"] for c in EVENT_META.values())


async def set_enabled_categories(guild_id: int, categories: set[str]) -> None:
    """Configure les categories de logs activees."""
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    data["enabled_categories"] = sorted(categories)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


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
        data = _lire(guild_id)
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
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    cc = data.get("category_channels", {}) or {}
    if channel_id:
        cc[str(category)] = int(channel_id)
    else:
        cc.pop(str(category), None)
    data["category_channels"] = cc
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


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
        data = _lire(guild_id)
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
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    ec = data.get("event_channels", {}) or {}
    if channel_id:
        ec[str(event_value)] = int(channel_id)
    else:
        ec.pop(str(event_value), None)
    data["event_channels"] = ec
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


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
        return bool(_lire(guild_id).get("webhook_mode", False))
    except Exception:
        return False


async def set_webhook_mode(guild_id: int, on: bool) -> None:
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    data["webhook_mode"] = bool(on)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


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
        data = _lire(guild_id)
        return set(data.get("disabled_events", []) or [])
    except Exception:
        return set()


async def set_disabled_events(guild_id: int, events: set[str]) -> None:
    """Persiste la liste des event_type desactives."""
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    data["disabled_events"] = sorted(events)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


async def get_role_exclusions(guild_id: int) -> dict:
    """Retourne { event_type_str: [role_id, ...] } — roles epargnes pour chaque event."""
    p = _cfg_path(guild_id)
    if not p.exists():
        return {}
    try:
        data = _lire(guild_id)
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
    data = _lire(guild_id)  # illisible : Illisible — jamais {}, on écraserait tout
    sanitized = {}
    for k, v in (exclusions or {}).items():
        if isinstance(v, list):
            sanitized[str(k)] = [int(x) for x in v if str(x).lstrip('-').isdigit()]
    data["role_exclusions"] = sanitized
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _ecrire(guild_id, data)


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
    embed.set_author(name=str(title_override or meta['label'])[:256])

    if user is not None:
        embed.add_field(name="Concerné", value=_format_user(user), inline=False)
    if moderator is not None:
        embed.add_field(name="Modérateur", value=_format_user(moderator), inline=False)
    if channel is not None:
        embed.add_field(name="Salon", value=_format_channel(channel), inline=False)
    if reason:
        embed.add_field(name="Raison", value=reason[:1024], inline=False)
    if content:
        embed.add_field(name="Contenu", value=f"```\n{content[:900]}\n```", inline=False)
    if extra:
        for k, v in extra.items():
            embed.add_field(name=str(k)[:256], value=str(v)[:1024], inline=False)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=str(name)[:256], value=str(value)[:1024], inline=bool(inline))

    embed.set_footer(text=str(meta['cat']))
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
    """Envoie un log dans le salon de la categorie (sinon salon global). Retourne le message ou None.
    Toujours consigné au registre (le site) ; en mode site, seules les alertes vont dans Discord."""
    try:
        meta = EVENT_META.get(event_type)
        _ev_val = getattr(event_type, "value", None) or (str(event_type) if event_type else None)
        site = await mode_site(guild.id)
        #  En mode site, une alerte passe toujours : plus aucun autre salon ne la rattraperait.
        alerte = site and _ev_val in ALERTES
        if not alerte and await _ecarte(guild.id, _ev_val, user, moderator):
            return None
        try:
            await _consigner(guild, event_type, meta, title_override=title_override,
                             description=description, user=user, moderator=moderator, channel=channel,
                             reason=reason, content=content, extra=extra)
        except Exception as ex:  # le registre ne doit jamais empêcher l'alerte
            print("[UNIFIED_LOGGER][E1] registre indisponible")
            print(f"[UNIFIED_LOGGER][E1:DETAIL] {type(ex).__name__} {ex}")
        # Une catégorie décochée ne part plus dans Discord ; le site, lui, garde tout (19/10/2026 :
        # le filtre passait avant le registre, et la catégorie disparaissait aussi du site).
        if meta and not alerte:
            enabled = await get_enabled_categories(guild.id)
            if meta["cat"] not in enabled:
                return None
        if site:
            if not alerte:
                return None
            cid = await salon_alertes(guild.id)
            cible = bot.get_channel(int(cid)) if cid else None
            if cible is None:
                return None
            vue = vue_alerte(getattr(user, "id", 0) or 0) if vue_alerte is not None else None
            from ui_v2 import carte_embed
            return await cible.send(view=carte_embed(build_log_embed(
                event_type, title_override=title_override, description=description, fields=fields,
                user=user, moderator=moderator, channel=channel, reason=reason, content=content,
                extra=extra), vue), allowed_mentions=discord.AllowedMentions.none())

        # Phase 268 : routage évènement > catégorie > salon global.
        chan_id = await resolve_channel_for_event(guild.id, _ev_val, meta["cat"] if meta else None)
        if not chan_id:
            return None
        target = bot.get_channel(int(chan_id))
        if target is None:
            return None

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
        #  19/10/2026 : un fil par jour (« 📋 JJ/MM/AAAA ») — supprimé d'un coup à 30 jours.
        try:
            import nettoyage
            target = await nettoyage.fil_du_jour(target)
        except discord.HTTPException as ex:
            print(f"[unified_logger fil du jour] {ex}")
        parent = target.parent if isinstance(target, discord.Thread) else target
        try:
            if meta and await get_webhook_mode(guild.id) and hasattr(parent, "create_webhook"):
                wh = await _get_or_create_log_webhook(parent)
                if wh is not None:
                    cat = meta["cat"]
                    uname = f"{_CAT_ICON.get(cat, '📋')} {cat}"[:80]
                    av = guild.icon.url if guild.icon else None
                    from ui_v2 import carte_embed
                    kw = {"view": carte_embed(embed), "username": uname, "avatar_url": av, "wait": True,
                          "allowed_mentions": discord.AllowedMentions.none()}
                    if isinstance(target, discord.Thread):
                        kw["thread"] = target
                    try:
                        return await wh.send(**kw)
                    except Exception:
                        _log_webhook_cache.pop(parent.id, None)  # webhook périmé → repli
        except Exception:
            pass
        from ui_v2 import carte_embed
        return await target.send(view=carte_embed(embed), allowed_mentions=discord.AllowedMentions.none())
    except Exception as ex:
        import traceback
        print(f"[UNIFIED_LOGGER] erreur log_event {event_type}: {ex}")
        traceback.print_exc()
        return None


# =============================================================================
# HELPERS PRATIQUES PAR TYPE
# =============================================================================


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


# Anti double-alerte : (guild_id, member_id, total_warns) -> ts epoch. Borne mémoire.
_ESCALATION_SEEN: dict = {}
_ESCALATION_DEDUP_WINDOW = 120.0

# COUPE-CIRCUIT GLOBAL (owner 2026-06-18) : le dedup ci-dessus est PAR (membre, compteur)
# → il n'empêche PAS un flood d'alertes sur des membres DIFFÉRENTS (raid, module bugué).
# Au-delà de _ESCALATION_GLOBAL_MAX escalades / guilde / heure, on SUPPRIME les suivantes
# (l'owner DÉTESTE être spammé) et on poste UNE seule note « N alertes regroupées ». État
# mémoire (reset au reboot), fail-open. {guild_id: [ts...]} + {guild_id: ts_derniere_note}.
_ESCALATION_GLOBAL: dict = {}
_ESCALATION_FLOOD_NOTED: dict = {}
_ESCALATION_GLOBAL_MAX = 12
_ESCALATION_GLOBAL_WINDOW = 3600.0

# TASK A8 : sévérités qui déclenchent une MENTION du fondateur (en plus de l'embed).
_ESCALATION_PING_SEVERITIES = {"haute", "critique"}


def _founder_ids() -> set:
    """IDs des super-owners (fondateur). Source unique = owner_ids.py ; repli sur
    EXTRA_OWNER_IDS / l'ID GoRipe connu si l'import échoue. Fail-safe."""
    ids: set = set()
    try:
        import owner_ids as _oi
        ids |= set(getattr(_oi, "SUPER_OWNER_IDS", set()) or set())
    except Exception:
        pass
    if not ids:
        import os
        raw = os.getenv("EXTRA_OWNER_IDS", "") or ""
        for tok in raw.replace(";", ",").split(","):
            tok = tok.strip()
            if tok.isdigit():
                ids.add(int(tok))
        ids.add(781205382923288593)  # GoRipe — super-owner confirmé (repli ultime)
    return ids


async def _ping_founder_in_channel(channel, member, severity, palier):
    """TASK A8 : poste une MENTION du fondateur dans le MÊME salon que l'alerte
    d'escalade, scoppée allowed_mentions au(x) seul(s) fondateur(s). JAMAIS
    @everyone, JAMAIS de MP à un membre lambda. Fail-safe (ne casse rien)."""
    try:
        if channel is None:
            return
        ids = [i for i in _founder_ids() if i]
        if not ids:
            return
        mentions = " ".join(f"<@{i}>" for i in ids)
        try:
            mname = getattr(member, "display_name", None) or str(member)
        except Exception:
            mname = str(member)
        txt = (f"{mentions} ⚠️ Escalade **{severity}** — **{mname}** "
               f"(palier {palier}). Décision requise.")
        # allowed_mentions : UNIQUEMENT ces user-ids, jamais everyone/roles.
        am = discord.AllowedMentions(
            everyone=False, roles=False,
            users=[discord.Object(id=i) for i in ids],
        )
        await channel.send(txt, allowed_mentions=am)
    except Exception as ex:
        print(f"[_ping_founder_in_channel] {ex}")


async def log_member_escalation(bot, guild, member, total_warns, palier,
                                reason="", moderator=None, severity="haute"):
    """ALERTE « membre à surveiller » poussée dans le salon de LOGS DE BASE.

    Cœur de la demande owner : quand un membre franchit un palier critique
    (avertissements répétés, sanction auto grave), le bot SIGNALE clairement QUI
    pose problème dans les logs — et l'alerte n'est JAMAIS perdue : si la
    catégorie Sécurité est désactivée ou si aucun salon de catégorie n'est routé,
    on poste DIRECTEMENT dans le salon de logs de base (get_log_channel).
    100% fail-soft : ne casse jamais la sanction qui l'a déclenchée.
    """
    try:
        try:
            mention = getattr(member, "mention", str(member))
            mid = getattr(member, "id", "?")
            dname = getattr(member, "display_name", None) or str(member)
        except Exception:
            mention, mid, dname = str(member), "?", str(member)

        # Dédup : 1 seule alerte par (membre, compteur) dans une fenêtre courte
        # (évite la double-alerte si warn manuel + filtre auto atteignent le même
        # palier quasi simultanément).
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            key = (getattr(guild, "id", 0), getattr(member, "id", 0), int(total_warns))
            if now_ts - _ESCALATION_SEEN.get(key, 0) < _ESCALATION_DEDUP_WINDOW:
                return None
            _ESCALATION_SEEN[key] = now_ts
            if len(_ESCALATION_SEEN) > 2000:
                cutoff = now_ts - _ESCALATION_DEDUP_WINDOW
                for k in [k for k, v in list(_ESCALATION_SEEN.items()) if v < cutoff]:
                    _ESCALATION_SEEN.pop(k, None)
        except Exception:
            pass

        # COUPE-CIRCUIT GLOBAL (anti-flood owner) : au-delà de _ESCALATION_GLOBAL_MAX
        # escalades sur CETTE guilde dans la fenêtre, on suppresse les suivantes et on
        # poste UNE seule note de regroupement par fenêtre. Fail-open (toute erreur →
        # on laisse passer l'alerte normalement). Cf. constantes _ESCALATION_GLOBAL_*.
        try:
            _gid = int(getattr(guild, "id", 0) or 0)
            _now = datetime.now(timezone.utc).timestamp()
            _buf = [t for t in _ESCALATION_GLOBAL.get(_gid, [])
                    if _now - t < _ESCALATION_GLOBAL_WINDOW]
            _buf.append(_now)
            _ESCALATION_GLOBAL[_gid] = _buf
            if len(_ESCALATION_GLOBAL) > 500:  # borne mémoire : purge guildes inactives
                for _g in [g for g, ts in list(_ESCALATION_GLOBAL.items())
                           if not ts or _now - ts[-1] > _ESCALATION_GLOBAL_WINDOW]:
                    _ESCALATION_GLOBAL.pop(_g, None)
                    _ESCALATION_FLOOD_NOTED.pop(_g, None)
            if len(_buf) > _ESCALATION_GLOBAL_MAX:
                if _now - _ESCALATION_FLOOD_NOTED.get(_gid, 0) > _ESCALATION_GLOBAL_WINDOW:
                    _ESCALATION_FLOOD_NOTED[_gid] = _now
                    try:
                        await log_event(
                            bot, guild, EventType.SEC_ESCALATION,
                            description=(
                                f"⚠️ **Trop d'alertes d'escalade** ({len(_buf)} en 1 h) — "
                                f"les suivantes sont **regroupées en silence** pour éviter "
                                f"le flood. Voir /infractions pour le détail."),
                        )
                    except Exception:
                        pass
                return None  # flood → alerte suivante supprimée
        except Exception:
            pass

        desc = (
            f"🚨 **{dname}** atteint un palier critique "
            f"(**{total_warns}** avertissement(s) · palier {palier}). "
            f"À surveiller — envisager une sanction."
        )
        fields = [
            ("👤 Membre", f"{mention} `{mid}`", True),
            ("📊 Compteur", f"{total_warns} warns · palier {palier}", True),
            ("⚠️ Gravité", str(severity), True),
            ("📝 Déclencheur", (reason or "—")[:1000], False),
            ("🔎 Historique", "Voir /infractions pour la fiche complète", False),
        ]

        # 1) Voie normale : routage catégorie Sécurité (salon dédié) ou global.
        msg = None
        try:
            msg = await log_event(
                bot, guild, EventType.SEC_ESCALATION,
                description=desc, fields=fields,
                user=member, moderator=moderator, reason=reason,
            )
        except Exception:
            msg = None
        if msg is not None:
            # TASK A8 : ping fondateur (haute/critique) dans le MÊME salon. La dédup
            # en tête de fonction garantit l'anti-spam (1 alerte = 1 ping max).
            try:
                if str(severity).lower() in _ESCALATION_PING_SEVERITIES:
                    await _ping_founder_in_channel(
                        getattr(msg, "channel", None), member, severity, palier)
            except Exception as ex_p:
                print(f"[log_member_escalation ping] {ex_p}")
            return msg

        # 2) FALLBACK GARANTI : catégorie Sécurité OFF ou pas de salon routé →
        #    on poste DIRECTEMENT dans le salon de logs de base. Zéro alerte perdue.
        try:
            cid = await get_log_channel(guild.id)
            if cid:
                target = bot.get_channel(int(cid))
                if target is not None:
                    embed = build_log_embed(
                        EventType.SEC_ESCALATION,
                        description=desc, fields=fields,
                        user=member, moderator=moderator, reason=reason,
                    )
                    from ui_v2 import carte_embed
                    sent = await target.send(view=carte_embed(embed), allowed_mentions=discord.AllowedMentions.none())
                    # TASK A8 : ping fondateur (haute/critique) dans ce même salon.
                    try:
                        if str(severity).lower() in _ESCALATION_PING_SEVERITIES:
                            await _ping_founder_in_channel(
                                target, member, severity, palier)
                    except Exception as ex_p:
                        print(f"[log_member_escalation ping fallback] {ex_p}")
                    return sent
        except Exception as ex:
            print(f"[log_member_escalation fallback] {ex}")
        return None
    except Exception as ex:
        print(f"[log_member_escalation] {ex}")
        return None


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


__all__ = [
    "EventType",
    "EVENT_META",
    "get_log_channel",
    "set_log_channel",
    "get_enabled_categories",
    "set_enabled_categories",
    "build_log_embed",
    "log_event",
    "log_security_event",
    "log_member_join",
    "log_member_leave",
    "log_message_delete",
]
