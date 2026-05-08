"""
activity_tracker.py - Tracker d'activite multi-fenetre (Phase 1.7).

Suit l'activite des membres pour alimenter :
    - Member spotlight (community_features)
    - Trust score (protection_guards)
    - Weekly digest (community_features)
    - Stats panel owner

Donnees suivies :
    - Messages textuels (par user, par salon, par jour)
    - Temps en vocal (par user, par jour)
    - Reactions "helpful" (👍 ❤️ 🤝 🙏 ⭐ etc.) recues sur ses messages
    - Premier / dernier message (anciennete d'activite)

Persistance : JSON par jour (data/activity/{guild_id}/YYYY-MM-DD.json),
ce qui permet :
    - Aggregation rapide par fenetre (7j, 30j, 90j)
    - Pruning facile (suppression des fichiers > 90j)
    - Pas de DB lourde

API:
    track_message(guild_id, user_id, channel_id, dt=None)
    track_voice_join(guild_id, user_id, dt=None)
    track_voice_leave(guild_id, user_id, dt=None)
    track_helpful_reaction(guild_id, message_author_id, dt=None)

    get_user_stats(guild_id, user_id, days=7) -> UserStats
    get_top_contributors(guild_id, days=7, limit=10) -> list[UserStats]
    get_guild_stats(guild_id, days=7) -> GuildStats
    get_member_activity(guild_id, days=7) -> list[MemberActivity]
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from paths import module_dir
from community_features import MemberActivity


DATA_DIR = module_dir("activity")


# =============================================================================
# MODELES
# =============================================================================

@dataclass
class UserStats:
    """Stats agregees d'un utilisateur sur une fenetre."""

    user_id: int
    message_count: int = 0
    voice_minutes: int = 0
    helpful_reactions: int = 0
    channels_active: int = 0
    first_message_at: Optional[str] = None
    last_message_at: Optional[str] = None


@dataclass
class GuildStats:
    """Stats agregees d'un serveur sur une fenetre."""

    total_messages: int = 0
    voice_hours: int = 0
    new_members: int = 0
    most_active_channel: Optional[tuple[int, int]] = None  # (channel_id, count)
    top_contributors: list[tuple[int, int]] = field(default_factory=list)  # [(uid, count)]


# =============================================================================
# STOCKAGE PAR JOUR
# =============================================================================
# Phase 3.0e : refonte buffer en memoire + flush periodique pour eviter le
# disk-thrashing par message (1 read+write disque/message = goulot Asyncio).
# Maintenant : modifications RAM only, flush toutes les 60s par flush_buffer().

_io_lock = asyncio.Lock()
_voice_active: dict[tuple[int, int], datetime] = {}  # (guild, user) -> joined_at

# Buffer in-memory : (guild_id, "YYYY-MM-DD") -> day_data dict
_buffer: dict[tuple[int, str], dict] = {}
_buffer_dirty: set[tuple[int, str]] = set()
_buffer_loaded: set[tuple[int, str]] = set()


def _guild_dir(guild_id: int) -> Path:
    p = DATA_DIR / str(guild_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _day_path(guild_id: int, day: datetime) -> Path:
    return _guild_dir(guild_id) / f"{day.strftime('%Y-%m-%d')}.json"


def _load_day(guild_id: int, day: datetime) -> dict:
    """Schema:
    {
        "messages": {user_id: {channel_id: count}},
        "voice_minutes": {user_id: int},
        "helpful_reactions": {user_id: int},
        "first_message_at": {user_id: iso},
        "last_message_at": {user_id: iso},
    }
    """
    path = _day_path(guild_id, day)
    if not path.exists():
        return {
            "messages": {},
            "voice_minutes": {},
            "helpful_reactions": {},
            "first_message_at": {},
            "last_message_at": {},
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "messages": {},
            "voice_minutes": {},
            "helpful_reactions": {},
            "first_message_at": {},
            "last_message_at": {},
        }


def _save_day(guild_id: int, day: datetime, data: dict) -> None:
    path = _day_path(guild_id, day)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# =============================================================================
# TRACKING (a appeler depuis bot.py sur les events)
# =============================================================================

def _ensure_buffered(guild_id: int, dt: datetime) -> dict:
    """Charge le jour depuis le disque dans le buffer si pas deja la. Sync, no IO si cache."""
    day_str = dt.strftime("%Y-%m-%d")
    key = (guild_id, day_str)
    if key not in _buffer_loaded:
        _buffer[key] = _load_day(guild_id, dt)
        _buffer_loaded.add(key)
    return _buffer[key]


def _mark_dirty(guild_id: int, dt: datetime) -> None:
    day_str = dt.strftime("%Y-%m-%d")
    _buffer_dirty.add((guild_id, day_str))


async def track_message(
    guild_id: int,
    user_id: int,
    channel_id: int,
    dt: Optional[datetime] = None,
) -> None:
    """Enregistre l'envoi d'un message (RAM only, flush async).

    Lockless : risk negligeable de race sur les compteurs (un message
    rate de temps en temps n'est pas critique pour des stats).
    """
    dt = dt or datetime.now(timezone.utc)
    try:
        data = _ensure_buffered(guild_id, dt)
        msgs = data["messages"].setdefault(str(user_id), {})
        msgs[str(channel_id)] = msgs.get(str(channel_id), 0) + 1
        first = data["first_message_at"].get(str(user_id))
        if not first:
            data["first_message_at"][str(user_id)] = dt.isoformat()
        data["last_message_at"][str(user_id)] = dt.isoformat()
        _mark_dirty(guild_id, dt)
    except Exception:
        pass  # ne jamais faire planter on_message


async def track_voice_join(
    guild_id: int, user_id: int, dt: Optional[datetime] = None
) -> None:
    """Marque l'entree en vocal d'un membre (RAM only)."""
    dt = dt or datetime.now(timezone.utc)
    _voice_active[(guild_id, user_id)] = dt


async def track_voice_leave(
    guild_id: int, user_id: int, dt: Optional[datetime] = None
) -> None:
    """Cloture une session vocal et enregistre les minutes (RAM only, flush async)."""
    dt = dt or datetime.now(timezone.utc)
    joined = _voice_active.pop((guild_id, user_id), None)
    if joined is None:
        return
    minutes = max(0, int((dt - joined).total_seconds() // 60))
    if minutes <= 0:
        return
    try:
        data = _ensure_buffered(guild_id, dt)
        cur = data["voice_minutes"].get(str(user_id), 0)
        data["voice_minutes"][str(user_id)] = cur + minutes
        _mark_dirty(guild_id, dt)
    except Exception:
        pass


async def track_helpful_reaction(
    guild_id: int,
    message_author_id: int,
    dt: Optional[datetime] = None,
) -> None:
    """Enregistre qu'un membre a recu une reaction helpful sur son message (RAM only)."""
    dt = dt or datetime.now(timezone.utc)
    try:
        data = _ensure_buffered(guild_id, dt)
        cur = data["helpful_reactions"].get(str(message_author_id), 0)
        data["helpful_reactions"][str(message_author_id)] = cur + 1
        _mark_dirty(guild_id, dt)
    except Exception:
        pass


# =============================================================================
# FLUSH (a appeler periodiquement par bot.py)
# =============================================================================

async def flush_buffer() -> int:
    """Flush les jours dirty vers le disque. Retourne le nombre de fichiers ecrits."""
    if not _buffer_dirty:
        return 0
    keys_to_flush = list(_buffer_dirty)
    _buffer_dirty.clear()
    written = 0
    async with _io_lock:
        for guild_id, day_str in keys_to_flush:
            data = _buffer.get((guild_id, day_str))
            if data is None:
                continue
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                _save_day(guild_id, day, data)
                written += 1
            except Exception:
                # Si l'ecriture echoue, on remet en dirty pour reessayer plus tard
                _buffer_dirty.add((guild_id, day_str))
    return written


# =============================================================================
# REQUETES D'AGREGATION
# =============================================================================

async def _aggregate_window(guild_id: int, days: int) -> dict:
    """Fusionne les donnees des N derniers jours.

    Inclut a la fois le disque ET le buffer en memoire (pour voir les
    donnees du jour en cours sans attendre le flush periodique).
    """
    now = datetime.now(timezone.utc)
    aggregated = {
        "messages": defaultdict(lambda: defaultdict(int)),  # user -> channel -> count
        "voice_minutes": defaultdict(int),
        "helpful_reactions": defaultdict(int),
        "first_message_at": {},
        "last_message_at": {},
    }
    async with _io_lock:
        for offset in range(days):
            day = now - timedelta(days=offset)
            day_str = day.strftime("%Y-%m-%d")
            buffer_key = (guild_id, day_str)
            # Prefere le buffer (frais) si dispo, sinon disque
            if buffer_key in _buffer:
                data = _buffer[buffer_key]
            else:
                data = _load_day(guild_id, day)
            for uid, channels in data.get("messages", {}).items():
                for ch_id, count in channels.items():
                    aggregated["messages"][uid][ch_id] += count
            for uid, mins in data.get("voice_minutes", {}).items():
                aggregated["voice_minutes"][uid] += mins
            for uid, count in data.get("helpful_reactions", {}).items():
                aggregated["helpful_reactions"][uid] += count
            for uid, ts in data.get("first_message_at", {}).items():
                cur = aggregated["first_message_at"].get(uid)
                if cur is None or ts < cur:
                    aggregated["first_message_at"][uid] = ts
            for uid, ts in data.get("last_message_at", {}).items():
                cur = aggregated["last_message_at"].get(uid)
                if cur is None or ts > cur:
                    aggregated["last_message_at"][uid] = ts
    return aggregated


async def get_user_stats(guild_id: int, user_id: int, days: int = 7) -> UserStats:
    """Stats d'un user sur les N derniers jours."""
    agg = await _aggregate_window(guild_id, days)
    uid = str(user_id)
    messages_per_chan = agg["messages"].get(uid, {})
    total_msgs = sum(messages_per_chan.values())
    return UserStats(
        user_id=user_id,
        message_count=total_msgs,
        voice_minutes=agg["voice_minutes"].get(uid, 0),
        helpful_reactions=agg["helpful_reactions"].get(uid, 0),
        channels_active=len(messages_per_chan),
        first_message_at=agg["first_message_at"].get(uid),
        last_message_at=agg["last_message_at"].get(uid),
    )


async def get_top_contributors(
    guild_id: int, days: int = 7, limit: int = 10
) -> list[UserStats]:
    """Top N contributeurs par messages sur la fenetre."""
    agg = await _aggregate_window(guild_id, days)
    users_messages = {
        uid: sum(channels.values())
        for uid, channels in agg["messages"].items()
    }
    sorted_uids = sorted(users_messages, key=users_messages.get, reverse=True)[:limit]
    out: list[UserStats] = []
    for uid in sorted_uids:
        out.append(UserStats(
            user_id=int(uid),
            message_count=users_messages[uid],
            voice_minutes=agg["voice_minutes"].get(uid, 0),
            helpful_reactions=agg["helpful_reactions"].get(uid, 0),
            channels_active=len(agg["messages"].get(uid, {})),
            first_message_at=agg["first_message_at"].get(uid),
            last_message_at=agg["last_message_at"].get(uid),
        ))
    return out


async def get_guild_stats(guild_id: int, days: int = 7) -> GuildStats:
    """Stats globales du serveur."""
    agg = await _aggregate_window(guild_id, days)

    total_messages = sum(
        sum(channels.values()) for channels in agg["messages"].values()
    )
    voice_minutes = sum(agg["voice_minutes"].values())

    # Salon le plus actif
    channel_counts: dict[str, int] = defaultdict(int)
    for channels in agg["messages"].values():
        for ch_id, c in channels.items():
            channel_counts[ch_id] += c
    most_active = None
    if channel_counts:
        ch_id, count = max(channel_counts.items(), key=lambda x: x[1])
        most_active = (int(ch_id), count)

    # Top contributeurs
    users_msgs = {
        uid: sum(channels.values())
        for uid, channels in agg["messages"].items()
    }
    top = sorted(users_msgs.items(), key=lambda x: x[1], reverse=True)[:10]
    top_pairs = [(int(uid), c) for uid, c in top]

    return GuildStats(
        total_messages=total_messages,
        voice_hours=voice_minutes // 60,
        new_members=0,  # bot.py doit fournir cette donnee separement
        most_active_channel=most_active,
        top_contributors=top_pairs,
    )


async def get_member_activity(
    guild_id: int, days: int = 7, limit: int = 50
) -> list[MemberActivity]:
    """Convertit les top contributeurs en MemberActivity (pour spotlight)."""
    top = await get_top_contributors(guild_id, days=days, limit=limit)
    out = []
    for stats in top:
        out.append(MemberActivity(
            user_id=stats.user_id,
            user_name="",  # bot.py remplit ce champ apres
            message_count=stats.message_count,
            voice_minutes=stats.voice_minutes,
            helpful_reactions=stats.helpful_reactions,
        ))
    return out


# =============================================================================
# MAINTENANCE
# =============================================================================

async def prune_old_data(guild_id: int, max_age_days: int = 90) -> int:
    """Supprime les fichiers de donnees plus vieux que `max_age_days`."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    deleted = 0
    async with _io_lock:
        gdir = _guild_dir(guild_id)
        for path in gdir.glob("*.json"):
            try:
                day = datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if day < cutoff:
                    path.unlink()
                    deleted += 1
            except ValueError:
                continue
    return deleted


# =============================================================================
# RECONCILE TRUST SCORE (interface protection_guards)
# =============================================================================

async def get_account_age_for_trust(guild_id: int, user_id: int) -> tuple[int, int, int]:
    """Retourne (account_age_days, server_age_days, message_count) pour le trust score.

    Note: account_age_days et server_age_days viennent normalement de Discord
    (member.created_at / member.joined_at). Cette fonction retourne juste le
    message_count basé sur les 90 derniers jours d'activite.
    """
    stats = await get_user_stats(guild_id, user_id, days=90)
    return (0, 0, stats.message_count)


# =============================================================================
# REACTION HELPFUL (helper pour bot.py)
# =============================================================================

# Emoji consideres comme "helpful" (le membre a aide quelqu'un)
HELPFUL_EMOJIS = {
    "👍", "❤️", "🤝", "🙏", "⭐", "🌟", "💯", "🎉",
    "✅", "🆒", "🔥", "👏", "🫶",
}


def is_helpful_reaction(emoji_str: str) -> bool:
    """True si l'emoji est dans la liste 'helpful'."""
    return emoji_str in HELPFUL_EMOJIS


__all__ = [
    "UserStats",
    "GuildStats",
    "track_message",
    "track_voice_join",
    "track_voice_leave",
    "track_helpful_reaction",
    "flush_buffer",
    "get_user_stats",
    "get_top_contributors",
    "get_guild_stats",
    "get_member_activity",
    "prune_old_data",
    "get_account_age_for_trust",
    "HELPFUL_EMOJIS",
    "is_helpful_reaction",
]
