"""
tracking_layer.py - Couche de tracage persistant pour le systeme social existant
                    de bot.py (check_youtube/twitch/tiktok/twitter/instagram_feeds).

Probleme resolu :
    Le bot.py existant utilise un dict en RAM `posted_content` pour le dedup.
    Probleme : au redemarrage, ce dict est vide -> le bot reposte tous les
    derniers contenus. Et il ne stocke pas l'ID du message Discord cree, donc
    impossible de le supprimer si la source disparait.

Cette couche fournit :
    - Dedup PERSISTANT (JSON sur disque, garde un historique de TOUS les posts)
    - Tracking du couple (post_id <-> discord_message_id) pour suppression
    - API simple pour patcher chaque check_*_feeds avec 5-6 lignes max

API :
    await was_posted(guild_id, platform, username, post_id) -> bool
    await record_post(guild_id, platform, username, post_id, *,
                      channel_id, message_id, title, url, post_type) -> None
    await list_announcements(guild_id, platform=None, username=None) -> list[Announcement]
    await mark_deleted(guild_id, platform, username, post_id) -> None
    await prune_old(guild_id, max_days=180) -> int

Cleanup helper (a brancher dans une boucle bot.py) :
    await cleanup_deleted_sources(guild, fetch_url_alive_callback) -> int
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from paths import module_dir


DATA_DIR = module_dir("posted_tracking")


# =============================================================================
# MODELE
# =============================================================================

@dataclass
class TrackedPost:
    """Une publication annoncee dans Discord."""

    guild_id: int
    platform: str          # "twitter", "youtube", "twitch", "tiktok", "instagram", "kick", "rosocial"
    username: str          # handle (lower)
    post_id: str           # ID unique du post / video / stream / tweet
    discord_channel_id: int
    discord_message_id: int
    post_type: str         # "video", "live", "post", "tweet", "short"
    title: str = ""
    url: str = ""
    posted_at: float = field(default_factory=lambda: time.time())
    deleted: bool = False  # True si on a supprime le message Discord
    # Phase 14 : URL d'image résolue à la capture (fiable, plus de 404 sur les
    # patterns deprecated). Vide = la galerie tentera de deviner.
    thumbnail_url: str = ""
    # Phase 14 : nom d'affichage propre du créateur/auteur (différent de username
    # qui est utilisé pour le dedup). Optionnel.
    display_author: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.username.lower()}:{self.post_id}"


# =============================================================================
# STOCKAGE (1 JSON par guild)
# =============================================================================

_io_lock = asyncio.Lock()
_cache: dict[int, dict[str, TrackedPost]] = {}  # guild_id -> {key -> TrackedPost}
_loaded_guilds: set[int] = set()


def _path(guild_id: int):
    return DATA_DIR / f"{guild_id}.json"


async def _load_guild(guild_id: int) -> None:
    if guild_id in _loaded_guilds:
        return
    async with _io_lock:
        if guild_id in _loaded_guilds:
            return
        path = _path(guild_id)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                store: dict[str, TrackedPost] = {}
                # Phase 14 : robust loading — filtre les champs inconnus du JSON
                # (pour gérer rolling updates où les anciens JSON ont moins de
                # champs ou les nouveaux JSON ont plus de champs que la dataclass)
                valid_fields = set(TrackedPost.__dataclass_fields__.keys())
                for d in raw:
                    try:
                        if not isinstance(d, dict):
                            continue
                        filtered = {k: v for k, v in d.items() if k in valid_fields}
                        tp = TrackedPost(**filtered)
                        store[tp.key] = tp
                    except (KeyError, TypeError, ValueError):
                        continue
                _cache[guild_id] = store
            except (json.JSONDecodeError, OSError):
                _cache[guild_id] = {}
        else:
            _cache[guild_id] = {}
        _loaded_guilds.add(guild_id)


async def _save_guild(guild_id: int) -> None:
    async with _io_lock:
        store = _cache.get(guild_id, {})
        payload = [asdict(tp) for tp in store.values()]
        _path(guild_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# =============================================================================
# API
# =============================================================================

async def was_posted(
    guild_id: int, platform: str, username: str, post_id: str
) -> bool:
    """True si ce post a deja ete annonce (meme si on l'a depuis supprime).

    Empeche le re-post au redemarrage ou si la source revient en ligne.
    """
    await _load_guild(guild_id)
    key = f"{platform}:{username.lower()}:{post_id}"
    return key in _cache.get(guild_id, {})


async def has_active_announcement(
    guild_id: int, platform: str, username: str, post_id: str
) -> bool:
    """True si une annonce existe et n'a pas ete supprimee."""
    await _load_guild(guild_id)
    key = f"{platform}:{username.lower()}:{post_id}"
    tp = _cache.get(guild_id, {}).get(key)
    return tp is not None and not tp.deleted


async def record_post(
    guild_id: int,
    platform: str,
    username: str,
    post_id: str,
    *,
    channel_id: int,
    message_id: int,
    post_type: str = "post",
    title: str = "",
    url: str = "",
    thumbnail_url: str = "",
    display_author: str = "",
) -> TrackedPost:
    """Enregistre une nouvelle annonce.

    Phase 14 : ajout de `thumbnail_url` et `display_author` pour les
    galleries (Roblox UGC, RoSocial) qui ont besoin d'une image fiable
    + nom d'affichage propre du créateur.
    """
    await _load_guild(guild_id)
    tp = TrackedPost(
        guild_id=guild_id,
        platform=platform,
        username=username.lower(),
        post_id=str(post_id),
        discord_channel_id=channel_id,
        discord_message_id=message_id,
        post_type=post_type,
        title=title[:200] if title else "",
        url=url,
        thumbnail_url=thumbnail_url or "",
        display_author=display_author or "",
    )
    _cache.setdefault(guild_id, {})[tp.key] = tp
    await _save_guild(guild_id)
    return tp


async def update_post(
    guild_id: int,
    platform: str,
    username: str,
    post_id: str,
    *,
    title: Optional[str] = None,
    url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    display_author: Optional[str] = None,
) -> bool:
    """Phase 14 : met à jour les champs (title/url/thumbnail/author) d'un post
    existant. Utilisé pour le backfill des anciennes entrées qui n'ont pas
    `thumbnail_url` ou `display_author` (capturées avant Phase 14).

    Retourne True si la mise à jour a été faite, False si la clé n'existe pas.
    """
    await _load_guild(guild_id)
    key = f"{platform}:{username.lower()}:{post_id}"
    tp = _cache.get(guild_id, {}).get(key)
    if tp is None:
        return False
    changed = False
    if title is not None and tp.title != title[:200]:
        tp.title = title[:200]
        changed = True
    if url is not None and tp.url != url:
        tp.url = url
        changed = True
    if thumbnail_url is not None and tp.thumbnail_url != thumbnail_url:
        tp.thumbnail_url = thumbnail_url
        changed = True
    if display_author is not None and tp.display_author != display_author:
        tp.display_author = display_author
        changed = True
    if changed:
        await _save_guild(guild_id)
    return changed


async def list_announcements(
    guild_id: int,
    platform: Optional[str] = None,
    username: Optional[str] = None,
    only_active: bool = True,
) -> list[TrackedPost]:
    """Liste les annonces, filtrable par platform/username."""
    await _load_guild(guild_id)
    out = []
    for tp in _cache.get(guild_id, {}).values():
        if only_active and tp.deleted:
            continue
        if platform and tp.platform != platform:
            continue
        if username and tp.username != username.lower():
            continue
        out.append(tp)
    return out


async def mark_deleted(
    guild_id: int, platform: str, username: str, post_id: str
) -> bool:
    """Marque une annonce comme supprimee dans le tracker."""
    await _load_guild(guild_id)
    key = f"{platform}:{username.lower()}:{post_id}"
    tp = _cache.get(guild_id, {}).get(key)
    if tp is None or tp.deleted:
        return False
    tp.deleted = True
    await _save_guild(guild_id)
    return True


async def remove_record(
    guild_id: int, platform: str, username: str, post_id: str
) -> bool:
    """Supprime entierement le record (cas ou l'owner supprime un compte tracke)."""
    await _load_guild(guild_id)
    key = f"{platform}:{username.lower()}:{post_id}"
    if key not in _cache.get(guild_id, {}):
        return False
    del _cache[guild_id][key]
    await _save_guild(guild_id)
    return True


async def rebind_channel(guild_id: int, platform: str, new_channel_id: int) -> int:
    """Met a jour le channel_id de toutes les entries de cette plateforme.

    Phase 3.7 : si l'owner change le salon configure pour cette plateforme,
    on doit propager le nouveau channel_id aux entries existantes pour que
    la galerie les retrouve correctement.

    Retourne le nombre d'entries mises a jour.
    """
    await _load_guild(guild_id)
    updated = 0
    store = _cache.get(guild_id, {})
    for tp in store.values():
        if tp.platform != platform:
            continue
        if tp.discord_channel_id == new_channel_id:
            continue
        tp.discord_channel_id = new_channel_id
        updated += 1
    if updated > 0:
        await _save_guild(guild_id)
    return updated


async def prune_old(guild_id: int, max_days: int = 180) -> int:
    """Supprime les annonces > max_days et marquees deleted, pour eviter la croissance infinie."""
    await _load_guild(guild_id)
    cutoff = time.time() - (max_days * 86400)
    store = _cache.get(guild_id, {})
    keys_to_remove = [
        k for k, tp in store.items()
        if tp.deleted and tp.posted_at < cutoff
    ]
    for k in keys_to_remove:
        del store[k]
    if keys_to_remove:
        await _save_guild(guild_id)
    return len(keys_to_remove)


# =============================================================================
# CLEANUP HELPER
# =============================================================================

# Callback type : prend un TrackedPost, retourne True si la source existe encore.
# Si retourne False, on supprime le message Discord et on marque deleted.
SourceLivenessCallback = Callable[[TrackedPost], Awaitable[bool]]


async def cleanup_deleted_sources(
    guild,
    is_alive_cb: SourceLivenessCallback,
    *,
    bot_get_channel_cb: Callable[[int], Any] = None,
    only_platforms: Optional[list[str]] = None,
    max_to_check: int = 50,
) -> dict:
    """Pour chaque annonce active, verifie si la source existe encore.

    - `is_alive_cb` : async callable, prend un TrackedPost, retourne bool
    - `bot_get_channel_cb` : optionnel, pour resoudre les channels (bot.get_channel)
    - `only_platforms` : limite aux plateformes specifiees
    - `max_to_check` : limite par run pour eviter rate-limit

    Retourne {"checked": N, "deleted": M, "errors": [...]}.
    """
    await _load_guild(guild.id)
    report = {"checked": 0, "deleted": 0, "errors": []}

    candidates = []
    for tp in _cache.get(guild.id, {}).values():
        if tp.deleted:
            continue
        if only_platforms and tp.platform not in only_platforms:
            continue
        candidates.append(tp)

    # Sort par anciennete (oldest first - plus susceptibles d'etre deja supprimes)
    candidates.sort(key=lambda t: t.posted_at)
    candidates = candidates[:max_to_check]

    for tp in candidates:
        report["checked"] += 1
        try:
            still_alive = await is_alive_cb(tp)
        except Exception as ex:
            report["errors"].append(f"{tp.key}: liveness check failed ({ex})")
            continue

        if still_alive:
            continue

        # La source n'existe plus -> supprimer le message Discord
        try:
            chan = None
            if bot_get_channel_cb:
                chan = bot_get_channel_cb(tp.discord_channel_id)
            if chan is None:
                chan = guild.get_channel(tp.discord_channel_id)
            if chan is None:
                # Salon plus accessible : on marque quand meme deleted pour eviter de re-check
                tp.deleted = True
                report["deleted"] += 1
                continue

            try:
                msg = await chan.fetch_message(tp.discord_message_id)
                await msg.delete()
            except Exception:
                # Message deja supprime / inaccessible : on marque quand meme
                pass

            tp.deleted = True
            report["deleted"] += 1
        except Exception as ex:
            report["errors"].append(f"{tp.key}: delete failed ({ex})")

    if report["deleted"] > 0:
        await _save_guild(guild.id)

    return report


__all__ = [
    "TrackedPost",
    "was_posted",
    "has_active_announcement",
    "record_post",
    "list_announcements",
    "mark_deleted",
    "remove_record",
    "prune_old",
    "cleanup_deleted_sources",
]
