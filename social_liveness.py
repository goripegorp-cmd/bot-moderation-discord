"""
social_liveness.py - Verifie si une publication source est toujours en ligne (Phase 1.8).

Pour chaque plateforme : un check leger qui retourne True si le post existe
encore, False si supprime (404 / gone / unavailable).

Utilise par tracking_layer.cleanup_deleted_sources() pour declencher la
suppression automatique des annonces Discord dont la source a disparu.

API:
    is_alive(session, tracked_post) -> bool
    cleanup_for_guild(session, guild, *, only_platforms=None, max=50) -> dict

Strategy par plateforme :
    youtube       - GET oembed endpoint, 401/404 = gone
    twitter       - GET syndication, check tweet_id present
    tiktok        - GET URL, look for "video unavailable" markers
    reddit        - GET .json, check existence
    rosocial      - GET URL, check 404
    roblox_ugc    - API catalog details, check exists
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import aiohttp

from tracking_layer import TrackedPost, _cache, _load_guild, _save_guild


# =============================================================================
# CHECKS PAR PLATEFORME
# =============================================================================

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}

_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _is_alive_youtube(session, post: TrackedPost) -> bool:
    """Check via oembed : retourne 401 si prive, 404 si supprime."""
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={post.post_id}&format=json"
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True) as resp:
            return resp.status == 200
    except Exception:
        return True  # erreur reseau - on garde par defaut


async def _is_alive_twitter(session, post: TrackedPost) -> bool:
    """Check via syndication : si le tweet n'est plus dans les recent tweets, on assume supprime.

    Nuance : Twitter ne retient que les ~20 derniers tweets, donc un tweet ancien
    sortira naturellement. Pour limiter les faux positifs, on ne supprime que si
    le post a < 14 jours (apres ca, on assume qu'il est juste sorti du feed).
    """
    import time
    age_days = (time.time() - post.posted_at) / 86400
    if age_days > 14:
        return True  # trop vieux pour juger, on garde

    synd_url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{post.username}"
    try:
        async with session.get(synd_url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return True
            html = await resp.text()
        # Cherche le tweet_id dans la reponse
        if post.post_id in html:
            return True
        return False
    except Exception:
        return True


async def _is_alive_tiktok(session, post: TrackedPost) -> bool:
    """Check via URL directe : cherche les markers d'erreur dans la page."""
    url = post.url or f"https://www.tiktok.com/@{post.username}/video/{post.post_id}"
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True) as resp:
            if resp.status == 404:
                return False
            if resp.status != 200:
                return True
            html = await resp.text()
        # Markers TikTok "video unavailable"
        markers = [
            "Video currently unavailable",
            "video has been removed",
            "Cette vidéo n'est pas disponible",
            "page-not-found",
            'data-e2e="video-unavailable"',
        ]
        return not any(m.lower() in html.lower() for m in markers)
    except Exception:
        return True


async def _is_alive_reddit(session, post: TrackedPost) -> bool:
    """Check via .json - retourne 404 si post supprime."""
    url = post.url
    if not url:
        return True
    if not url.endswith("/"):
        url += "/"
    json_url = url + ".json"
    try:
        async with session.get(json_url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status == 404:
                return False
            if resp.status != 200:
                return True
            data = await resp.json()
        # Reddit retourne souvent un truc meme si supprime. Check si le post est removed
        try:
            post_data = data[0]['data']['children'][0]['data']
            if post_data.get('removed_by_category'):
                return False
            if post_data.get('selftext') == '[deleted]' and post_data.get('author') == '[deleted]':
                return False
        except (KeyError, IndexError, TypeError):
            pass
        return True
    except Exception:
        return True


async def _is_alive_rosocial(session, post: TrackedPost) -> bool:
    url = post.url or f"https://rosocial.net/posts/{post.post_id}"
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True) as resp:
            return resp.status not in (404, 410)
    except Exception:
        return True


async def _is_alive_roblox_ugc(session, post: TrackedPost) -> bool:
    """Pour Roblox UGC, post_id est composite. On extrait l'item_id."""
    parts = post.post_id.split("_")
    if len(parts) < 3:
        return True  # format inattendu, on garde
    try:
        item_id = parts[2]
        url = f"https://catalog.roblox.com/v1/catalog/items/{item_id}/details?itemType=Asset"
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status in (400, 404, 410):
                return False
            return True
    except Exception:
        return True


_PLATFORM_CHECKS = {
    "youtube":    _is_alive_youtube,
    "twitter":    _is_alive_twitter,
    "tiktok":     _is_alive_tiktok,
    "reddit":     _is_alive_reddit,
    "rosocial":   _is_alive_rosocial,
    "roblox_ugc": _is_alive_roblox_ugc,
}


# =============================================================================
# API PUBLIQUE
# =============================================================================

async def is_alive(session, post: TrackedPost) -> bool:
    """True si la source est toujours en ligne. False si supprimee."""
    check = _PLATFORM_CHECKS.get(post.platform)
    if check is None:
        return True  # plateforme inconnue, on garde par securite
    try:
        return await check(session, post)
    except Exception:
        return True


async def cleanup_for_guild(
    session,
    guild,
    *,
    only_platforms: Optional[list[str]] = None,
    max_to_check: int = 50,
    bot_get_channel_cb=None,
) -> dict:
    """Pour un guild, verifie la liveness des annonces et supprime les messages Discord obsoletes.

    Retourne un rapport {"checked": N, "deleted": M, "errors": [...]}.
    """
    await _load_guild(guild.id)
    report = {"checked": 0, "deleted": 0, "errors": []}

    candidates = []
    for tp in _cache.get(guild.id, {}).values():
        if tp.deleted:
            continue
        if only_platforms and tp.platform not in only_platforms:
            continue
        if tp.discord_message_id == 0:
            continue  # pas de message Discord a supprimer (envoi rate ou webhook KO)
        candidates.append(tp)

    # Plus vieux d'abord (plus susceptibles d'etre supprimes)
    candidates.sort(key=lambda t: t.posted_at)
    candidates = candidates[:max_to_check]

    for tp in candidates:
        report["checked"] += 1
        try:
            alive = await is_alive(session, tp)
        except Exception as ex:
            report["errors"].append(f"{tp.key}: {ex}")
            continue

        if alive:
            continue

        # Source disparue : on supprime le message Discord
        try:
            chan = None
            if bot_get_channel_cb:
                chan = bot_get_channel_cb(tp.discord_channel_id)
            if chan is None:
                chan = guild.get_channel(tp.discord_channel_id)

            if chan is not None:
                try:
                    msg = await chan.fetch_message(tp.discord_message_id)
                    await msg.delete()
                except Exception:
                    pass  # deja supprime / inaccessible

            tp.deleted = True
            report["deleted"] += 1
        except Exception as ex:
            report["errors"].append(f"{tp.key}: delete error {ex}")

        # petit delai pour pas hammer
        await asyncio.sleep(0.5)

    if report["deleted"] > 0:
        await _save_guild(guild.id)

    return report


__all__ = [
    "is_alive",
    "cleanup_for_guild",
]
