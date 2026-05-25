"""
social_gallery.py - Galerie de publications pour reseaux sociaux (Phase 3.1).

Au lieu d'envoyer 1 message par publication detectee (ce qui produit des
milliers de messages pour les comptes prolixes - typiquement Roblox UGC),
on maintient UNE galerie par (guild, plateforme, salon) qui s'auto-update
avec les N publications les plus recentes.

UX cible :
- 1 seul message par salon par plateforme
- Layout V2 Container avec N sections (1 par publication)
- Chaque section : thumbnail + titre cliquable + horodatage relatif
- Tri : plus recent en haut, plus ancien en bas
- Limite : N=10 publications visibles, les anciennes sortent automatiquement
- Re-render quand une nouvelle publication arrive

Interaction avec tracking_layer :
- La source de verite c'est `tracking_layer` (post_id, url, title, posted_at,
  deleted). La galerie est juste un VIEW de ces donnees.
- Quand `tracking_layer.record_post(...)` est appele, on peut declencher un
  `render(...)` pour mettre a jour la galerie.

API :
    set_gallery_msg_id(guild_id, platform, channel_id, msg_id)
    get_gallery_msg_id(guild_id, platform, channel_id) -> int | None
    build_gallery_view(guild_id, platform, channel_id) -> ui.LayoutView
    render(bot, guild_id, platform, channel_id) -> int | None
        Cree (ou edite) le message de galerie. Retourne le message_id.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import ui

from paths import module_dir
import tracking_layer


DATA_DIR = module_dir("social_galleries")
# Phase 19 : max 5 items par galerie pour optimiser ressources + lisibilité
# Quand un nouveau post arrive, les anciens >5 sortent automatiquement
MAX_ITEMS = 5
RENDER_DEBOUNCE_SECONDS = 5  # eviter spam d'edits si plusieurs posts arrivent en 1s


_io_lock = asyncio.Lock()
# (guild_id, platform, channel_id) -> last render timestamp
_last_render: dict[tuple[int, str, int], float] = {}


def _state_path(guild_id: int, platform: str, channel_id: int) -> Path:
    p = DATA_DIR / str(guild_id)
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{platform}_{channel_id}.json"


def _load_state(guild_id: int, platform: str, channel_id: int) -> dict:
    path = _state_path(guild_id, platform, channel_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(guild_id: int, platform: str, channel_id: int, state: dict) -> None:
    path = _state_path(guild_id, platform, channel_id)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# =============================================================================
# API
# =============================================================================

async def set_gallery_msg_id(
    guild_id: int, platform: str, channel_id: int, msg_id: int
) -> None:
    async with _io_lock:
        state = _load_state(guild_id, platform, channel_id)
        state["message_id"] = msg_id
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(guild_id, platform, channel_id, state)


def get_gallery_msg_id(
    guild_id: int, platform: str, channel_id: int
) -> Optional[int]:
    state = _load_state(guild_id, platform, channel_id)
    msg_id = state.get("message_id")
    return int(msg_id) if msg_id else None


def get_gallery_posts(
    guild_id: int, platform: str, channel_id: int, limit: int = MAX_ITEMS
) -> list[tracking_layer.TrackedPost]:
    """Recupere les N dernieres publications pour ce salon, plus recente en premier."""
    # tracking_layer charge en sync via le cache (deja loaded apres premier appel async)
    store = tracking_layer._cache.get(guild_id, {})
    matching = []
    for tp in store.values():
        if tp.platform != platform:
            continue
        if tp.discord_channel_id != channel_id:
            continue
        if tp.deleted:
            continue
        matching.append(tp)
    matching.sort(key=lambda t: t.posted_at, reverse=True)
    return matching[:limit]


# =============================================================================
# RENDERING
# =============================================================================

PLATFORM_DISPLAY = {
    "youtube":    {"name": "YouTube",   "icon": "🔴", "color": 0xFF0000},
    "twitch":     {"name": "Twitch",    "icon": "🟣", "color": 0x9146FF},
    "tiktok":     {"name": "TikTok",    "icon": "🎵", "color": 0x69C9D0},
    "twitter":    {"name": "Twitter",   "icon": "🐦", "color": 0x1DA1F2},
    "reddit":     {"name": "Reddit",    "icon": "🟠", "color": 0xFF4500},
    "rosocial":   {"name": "RoSocial",  "icon": "🎮", "color": 0x00B894},
    "roblox_ugc": {"name": "Roblox UGC", "icon": "🟢", "color": 0x00A86B},
    "discord":    {"name": "Discord",   "icon": "📡", "color": 0x5865F2},
}


def _relative_time(epoch_seconds: float) -> str:
    """Retourne un timestamp relatif type 'il y a 2h', '3j' etc."""
    delta = max(0, time.time() - epoch_seconds)
    if delta < 60:
        return "à l'instant"
    if delta < 3600:
        return f"il y a {int(delta // 60)} min"
    if delta < 86400:
        return f"il y a {int(delta // 3600)} h"
    if delta < 604800:
        return f"il y a {int(delta // 86400)} j"
    return f"il y a {int(delta // 604800)} sem"


def build_gallery_view(
    guild_id: int, platform: str, channel_id: int,
    ignore_channel_filter: bool = True,
) -> ui.LayoutView:
    """Construit la LayoutView contenant la galerie.

    Phase 3.7 : design plus pro avec V2 Components.
    ignore_channel_filter=True : montre TOUS les items de cette plateforme
    pour ce guild (gere les changements de channel_id).
    """
    if ignore_channel_filter:
        # On filtre seulement par guild_id + platform (channel_id ignore)
        store = tracking_layer._cache.get(guild_id, {})
        matching = []
        for tp in store.values():
            if tp.platform != platform:
                continue
            if tp.deleted:
                continue
            matching.append(tp)
        matching.sort(key=lambda t: t.posted_at, reverse=True)
        posts = matching[:MAX_ITEMS]
    else:
        posts = get_gallery_posts(guild_id, platform, channel_id, limit=MAX_ITEMS)
    plat_info = PLATFORM_DISPLAY.get(platform, {"name": platform.title(), "icon": "📡", "color": 0x5865F2})

    view = ui.LayoutView(timeout=None)

    items = []

    # En-tete plus riche
    header_text = (
        f"# {plat_info['icon']} {plat_info['name']}\n"
        f"-# Galerie des publications · {len(posts)} item(s) · plus récent en haut"
    )
    items.append(ui.TextDisplay(header_text))
    items.append(ui.Separator())

    if not posts:
        items.append(ui.TextDisplay(
            "📭 **Aucune publication détectée pour le moment.**\n"
            "-# Le bot vérifie automatiquement les nouveaux contenus toutes les 5 minutes. "
            "Patiente, ou ajoute des comptes/groupes à suivre."
        ))
    else:
        # Chaque post = une Section avec thumbnail + texte propre
        for tp in posts:
            # Phase 14 : utilise title et url propres + display_author (nom au lieu d'ID)
            title = (getattr(tp, 'title', None) or 'Voir la publication').strip()[:90]
            url = getattr(tp, 'url', None) or 'https://discord.com'

            # Auteur : utilise display_author si dispo (nom propre du créateur),
            # sinon fallback sur username (qui peut être numeric pour anciennes données)
            display_author = (getattr(tp, 'display_author', '') or '').strip()
            author_text = display_author or tp.username
            # Si l'auteur ressemble à un nombre (ancien tracking par creator_id), on cache le @
            if author_text.isdigit():
                author_text = f"_créateur #{author_text}_"
            else:
                author_text = f"@{author_text}"

            # Construction du body text avec icone par type
            type_icon = {
                "video":     "🎥",
                "live":      "🔴",
                "short":     "📱",
                "post":      "📝",
                "tweet":     "🐦",
                "ugc":       "🎨",
            }.get(tp.post_type, "📄")

            time_str = _relative_time(tp.posted_at)
            text = (
                f"### {type_icon} [{title}]({url})\n"
                f"-# Par **{author_text}** · {time_str}"
            )

            # Phase 14 : thumbnail_url stocké au record time est prioritaire sur le devine
            thumb_url = (getattr(tp, 'thumbnail_url', '') or '').strip()
            if not thumb_url:
                thumb_url = _thumbnail_for(tp)

            if _looks_like_image_url(thumb_url):
                # Section avec thumbnail
                items.append(ui.Section(
                    ui.TextDisplay(text),
                    accessory=ui.Thumbnail(media=thumb_url),
                ))
            else:
                items.append(ui.TextDisplay(text))
            items.append(ui.Separator())

    # Footer
    items.append(ui.TextDisplay(
        "-# 🔄 Cette galerie se met à jour automatiquement · "
        "Clique sur un titre pour voir la publication originale"
    ))

    container = ui.Container(*items, accent_color=discord.Color(plat_info["color"]))
    view.add_item(container)
    return view


def _thumbnail_for(tp: tracking_layer.TrackedPost) -> str:
    """Devine une URL thumbnail pour la publication selon la plateforme."""
    # YouTube : thumbnail standard via id
    if tp.platform == "youtube":
        return f"https://img.youtube.com/vi/{tp.post_id}/hqdefault.jpg"
    # Roblox UGC : thumbnail via API endpoint
    if tp.platform == "roblox_ugc":
        # post_id format: "User_<id>_<item_id>_<type>" or "Group_<id>_<item_id>_<type>"
        parts = tp.post_id.split("_")
        if len(parts) >= 3:
            item_id = parts[2]
            return f"https://www.roblox.com/asset-thumbnail/image?assetId={item_id}&width=420&height=420&format=png"
    # Twitch : icone generique sur cdn (les vrais thumbnails de vod necessitent l'API auth)
    if tp.platform == "twitch":
        # Generique : on retourne rien pour laisser TextDisplay seul
        return ""
    # TikTok / Twitter / Reddit / RoSocial : on n'a pas d'URL image fiable depuis
    # tracking_layer (pas de champ image_url stocke). Retourne vide.
    return ""


def _looks_like_image_url(url: str) -> bool:
    if not url:
        return False
    return url.startswith(("http://", "https://"))


# =============================================================================
# RENDER (cree ou edite le message Discord)
# =============================================================================

async def render(bot, guild_id: int, platform: str, channel_id: int) -> Optional[int]:
    """Cree (ou edite) le message de galerie. Retourne le message_id."""
    # Debounce : si on vient de render < 5s, on attend
    key = (guild_id, platform, channel_id)
    now = time.time()
    last = _last_render.get(key, 0)
    if now - last < RENDER_DEBOUNCE_SECONDS:
        await asyncio.sleep(RENDER_DEBOUNCE_SECONDS - (now - last) + 0.1)
    _last_render[key] = time.time()

    chan = bot.get_channel(channel_id)
    if chan is None:
        return None

    view = build_gallery_view(guild_id, platform, channel_id)
    existing_msg_id = get_gallery_msg_id(guild_id, platform, channel_id)

    # Tente d'editer le message existant
    if existing_msg_id:
        try:
            msg = await chan.fetch_message(existing_msg_id)
            await msg.edit(view=view, embeds=[], attachments=[])
            return existing_msg_id
        except (discord.NotFound, discord.HTTPException):
            # Le message a ete supprime, on en cree un nouveau
            pass
        except Exception as ex:
            print(f"[GALLERY] edit echoue {guild_id}/{platform}/{channel_id}: {ex}")
            return existing_msg_id  # on garde le message_id meme si edit a fail

    # Cree un nouveau message
    try:
        new_msg = await chan.send(view=view)
        await set_gallery_msg_id(guild_id, platform, channel_id, new_msg.id)
        return new_msg.id
    except Exception as ex:
        print(f"[GALLERY] send echoue {guild_id}/{platform}/{channel_id}: {ex}")
        return None


async def render_after_post(bot, guild_id: int, platform: str, channel_id: int) -> Optional[int]:
    """Helper a appeler apres tracking_layer.record_post pour declencher un re-render."""
    return await render(bot, guild_id, platform, channel_id)


__all__ = [
    "MAX_ITEMS",
    "set_gallery_msg_id",
    "get_gallery_msg_id",
    "get_gallery_posts",
    "build_gallery_view",
    "render",
    "render_after_post",
]
