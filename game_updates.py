"""
game_updates.py - Suivi des mises à jour officielles de plateformes et jeux.

Concept : permettre à l'owner de tracker dans un salon Discord les vraies
mises à jour (patch notes, dev updates) d'une plateforme/jeu spécifique.
PAS les events, ni les promos, ni le contenu social — UNIQUEMENT les
patch notes / changelogs / dev updates officiels.

Sources utilisées (priorité fiabilité 2026) :

PLATEFORMES :
- Roblox          → devforum.roblox.com/c/updates.json (catégorie "Updates")
- Steam           → store.steampowered.com news (par appid)
- Epic Games      → store.epicgames.com/blog feed
- Battle.net      → news.blizzard.com RSS
- Minecraft       → feedback.minecraft.net (Mojang RSS)

JEUX POPULAIRES (via Steam News API ou source officielle) :
- Subnautica 2 (Unknown Worlds)         → Steam appid TBD (early access)
- World of Warcraft                     → news.blizzard.com/wow
- Counter-Strike 2                      → Steam appid 730
- Cyberpunk 2077                        → Steam appid 1091500
- Helldivers 2                          → Steam appid 553850
- PUBG                                  → Steam appid 578080
- Apex Legends                          → ea.com/games/apex-legends/news
- Fortnite                              → fortnite.com/news
- Genshin Impact                        → hoyoverse.com/news/genshin
- Honkai Star Rail                      → hoyoverse.com/news/hsr
- Diablo 4                              → news.blizzard.com/diablo4
- Overwatch 2                           → news.blizzard.com/overwatch
- League of Legends                     → leagueoflegends.com/news/game-updates
- Valorant                              → playvalorant.com/news/game-updates
- Path of Exile 2                       → pathofexile.com/forum/view-forum/news
- Destiny 2                             → bungie.net/destiny/news

API :
    GAME_SOURCES — dict mapping game_key → fetcher config
    fetch_updates(session, game_key, last_seen_id) → list[Update]
    Update : dataclass avec title, url, timestamp, summary, image_url
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp


# =============================================================================
# MODÈLE
# =============================================================================

@dataclass
class GameUpdate:
    """Une mise à jour de plateforme/jeu."""

    game_key: str           # ex: "roblox", "steam:730", "wow", etc.
    update_id: str          # ID unique de l'update
    title: str
    url: str
    summary: str = ""       # description courte (1-3 lignes)
    image_url: str = ""     # image principale si dispo
    posted_at: float = field(default_factory=lambda: time.time())
    update_type: str = "update"  # "patch", "hotfix", "major", "dev_update"


# =============================================================================
# CONFIGURATION DES SOURCES
# =============================================================================

# Métadonnées pour chaque jeu/plateforme suivi
# Format : game_key → {name, emoji, color, source_type, source_url, [extra]}
GAME_SOURCES = {
    # ─── PLATEFORMES ───
    "roblox": {
        "name": "Roblox (plateforme)",
        "emoji": "🟢",
        "color": 0x00A2FF,
        "source_type": "discourse",  # devforum est sous Discourse
        "source_url": "https://devforum.roblox.com/c/updates/announcements.json",
        "category": "Roblox Updates",
        "filter_keywords": ["update", "release notes", "patch", "improvement", "fix"],
    },
    "steam": {
        "name": "Steam (plateforme)",
        "emoji": "🟦",
        "color": 0x1B2838,
        "source_type": "steam_news",
        "appid": 593110,  # Steam app id pour Steam Client beta news
    },
    "epic": {
        "name": "Epic Games (plateforme)",
        "emoji": "⬛",
        "color": 0x2A2A2A,
        "source_type": "rss",
        "source_url": "https://store.epicgames.com/en-US/blog.rss",
    },
    "blizzard": {
        "name": "Blizzard (plateforme)",
        "emoji": "🔵",
        "color": 0x00A2FF,
        "source_type": "rss",
        "source_url": "https://news.blizzard.com/en-us/rss",
    },
    "minecraft": {
        "name": "Minecraft (Mojang)",
        "emoji": "🟫",
        "color": 0x62B47A,
        "source_type": "rss",
        "source_url": "https://www.minecraft.net/en-us/feeds/community-content/rss",
    },

    # ─── JEUX VIA STEAM NEWS API (n'importe quel jeu Steam) ───
    "cs2": {
        "name": "Counter-Strike 2",
        "emoji": "🔫",
        "color": 0xFF7B00,
        "source_type": "steam_news",
        "appid": 730,
    },
    "subnautica_2": {
        "name": "Subnautica 2",
        "emoji": "🐟",
        "color": 0x00ACEE,
        "source_type": "steam_news",
        "appid": 1922110,  # Subnautica 2 early access
    },
    "cyberpunk": {
        "name": "Cyberpunk 2077",
        "emoji": "💛",
        "color": 0xFCEE0A,
        "source_type": "steam_news",
        "appid": 1091500,
    },
    "helldivers2": {
        "name": "Helldivers 2",
        "emoji": "💂",
        "color": 0xFFD700,
        "source_type": "steam_news",
        "appid": 553850,
    },
    "pubg": {
        "name": "PUBG",
        "emoji": "🪖",
        "color": 0xF99500,
        "source_type": "steam_news",
        "appid": 578080,
    },
    "pathofexile2": {
        "name": "Path of Exile 2",
        "emoji": "⚔️",
        "color": 0x8B0000,
        "source_type": "steam_news",
        "appid": 2694490,
    },
    "valheim": {
        "name": "Valheim",
        "emoji": "🪓",
        "color": 0x5C4033,
        "source_type": "steam_news",
        "appid": 892970,
    },
    "rust": {
        "name": "Rust",
        "emoji": "🔧",
        "color": 0xCD5C5C,
        "source_type": "steam_news",
        "appid": 252490,
    },
    "ark": {
        "name": "ARK: Survival Ascended",
        "emoji": "🦖",
        "color": 0x6B8E23,
        "source_type": "steam_news",
        "appid": 2399830,
    },
    "satisfactory": {
        "name": "Satisfactory",
        "emoji": "🏭",
        "color": 0xF9A21E,
        "source_type": "steam_news",
        "appid": 526870,
    },
    "noita": {
        "name": "Terraria",
        "emoji": "🌳",
        "color": 0x1CB000,
        "source_type": "steam_news",
        "appid": 105600,
    },
    "factorio": {
        "name": "Factorio",
        "emoji": "🏗️",
        "color": 0xFFA500,
        "source_type": "steam_news",
        "appid": 427520,
    },

    # ─── JEUX BLIZZARD (RSS spécifiques) ───
    "wow": {
        "name": "World of Warcraft",
        "emoji": "⚔️",
        "color": 0x2E6BA8,
        "source_type": "rss",
        "source_url": "https://news.blizzard.com/en-us/world-of-warcraft/rss",
    },
    "diablo4": {
        "name": "Diablo IV",
        "emoji": "👹",
        "color": 0x8B0000,
        "source_type": "rss",
        "source_url": "https://news.blizzard.com/en-us/diablo4/rss",
    },
    "overwatch": {
        "name": "Overwatch 2",
        "emoji": "🟧",
        "color": 0xFA9C1B,
        "source_type": "rss",
        "source_url": "https://news.blizzard.com/en-us/overwatch/rss",
    },
    "hearthstone": {
        "name": "Hearthstone",
        "emoji": "🃏",
        "color": 0xE5A300,
        "source_type": "rss",
        "source_url": "https://news.blizzard.com/en-us/hearthstone/rss",
    },

    # ─── JEUX RIOT GAMES ───
    "league": {
        "name": "League of Legends",
        "emoji": "🛡️",
        "color": 0xC8AA6E,
        "source_type": "rss_generic",
        "source_url": "https://www.leagueoflegends.com/page-data/en-us/news/sitemap/page-data.json",
    },
    "valorant": {
        "name": "Valorant",
        "emoji": "🎯",
        "color": 0xFF4655,
        "source_type": "rss_generic",
        "source_url": "https://playvalorant.com/page-data/en-us/news/sitemap/page-data.json",
    },

    # ─── HOYOVERSE ───
    "genshin": {
        "name": "Genshin Impact",
        "emoji": "⛩️",
        "color": 0x1F8DF5,
        "source_type": "rss",
        "source_url": "https://genshin.hoyoverse.com/en/news.rss",
    },
    "honkai_starrail": {
        "name": "Honkai: Star Rail",
        "emoji": "🚂",
        "color": 0xB8860B,
        "source_type": "rss",
        "source_url": "https://hsr.hoyoverse.com/en/news.rss",
    },
}


# =============================================================================
# FETCHERS
# =============================================================================

async def _fetch_steam_news(session: aiohttp.ClientSession, appid: int, max_count: int = 5) -> list[GameUpdate]:
    """Fetch news Steam pour un appid donné via Steam News API officielle."""
    url = (
        f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        f"?appid={appid}&count={max_count}&maxlength=400&format=json"
    )
    out = []
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return out
            data = await resp.json()
        news_items = data.get('appnews', {}).get('newsitems', [])
        for item in news_items:
            # Filtrer : on veut surtout les news officielles du dev (feedlabel "Community Announcements" ou "Developer Notes")
            feedlabel = (item.get('feedlabel', '') or '').lower()
            if 'community' not in feedlabel and 'developer' not in feedlabel and 'announce' not in feedlabel and 'steam' not in feedlabel:
                continue
            update_id = str(item.get('gid', '')) or str(item.get('url', ''))
            if not update_id:
                continue
            # Extraire image du contenu HTML / BBCode
            contents = item.get('contents', '') or ''
            image_url = ''
            img_m = re.search(r'\[img\](https?://[^\[]+)\[/img\]', contents)
            if img_m:
                image_url = img_m.group(1)
            else:
                img_m2 = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', contents)
                if img_m2:
                    image_url = img_m2.group(1)
            summary = re.sub(r'\[/?[a-z]+(?:=[^\]]+)?\]', '', contents)[:300]
            summary = re.sub(r'<[^>]+>', '', summary).strip()
            out.append(GameUpdate(
                game_key=f"steam:{appid}",
                update_id=update_id,
                title=item.get('title', 'Sans titre')[:200],
                url=item.get('url', f'https://store.steampowered.com/news/app/{appid}'),
                summary=summary,
                image_url=image_url,
                posted_at=float(item.get('date', time.time())),
                update_type="patch",
            ))
    except Exception as ex:
        print(f"[game_updates _fetch_steam_news appid={appid}] {ex}")
    return out


async def _fetch_rss(session: aiohttp.ClientSession, url: str, max_count: int = 5) -> list[dict]:
    """Parse un flux RSS générique. Retourne liste de dicts {title, link, guid, summary, image, pub_date}."""
    items = []
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return items
            text = await resp.text()
        root = ET.fromstring(text)
        # RSS 2.0 : channel/item
        for item in root.findall('.//item')[:max_count]:
            title = item.findtext('title') or ''
            link = item.findtext('link') or ''
            guid = item.findtext('guid') or link
            desc = item.findtext('description') or ''
            pub_date = item.findtext('pubDate') or ''
            # Extraire image depuis description ou enclosure
            image = ''
            enc = item.find('enclosure')
            if enc is not None and enc.get('url'):
                image = enc.get('url')
            if not image and desc:
                img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc)
                if img_m:
                    image = img_m.group(1)
            # Clean description
            summary = re.sub(r'<[^>]+>', '', desc)[:300].strip()
            items.append({
                'title': title, 'link': link, 'guid': guid,
                'summary': summary, 'image': image, 'pub_date': pub_date,
            })
        # Atom : feed/entry (fallback)
        if not items:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry in root.findall('.//atom:entry', ns)[:max_count]:
                title = entry.findtext('atom:title', namespaces=ns) or ''
                link_el = entry.find('atom:link', namespaces=ns)
                link = link_el.get('href') if link_el is not None else ''
                guid = entry.findtext('atom:id', namespaces=ns) or link
                summary = entry.findtext('atom:summary', namespaces=ns) or ''
                summary = re.sub(r'<[^>]+>', '', summary)[:300].strip()
                items.append({
                    'title': title, 'link': link, 'guid': guid,
                    'summary': summary, 'image': '', 'pub_date': '',
                })
    except Exception as ex:
        print(f"[game_updates _fetch_rss {url}] {ex}")
    return items


async def _fetch_discourse(session: aiohttp.ClientSession, url: str, max_count: int = 10, filter_kw: Optional[list[str]] = None) -> list[dict]:
    """Parse une catégorie Discourse (utilisé pour Roblox devforum)."""
    items = []
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return items
            data = await resp.json()
        topics = data.get('topic_list', {}).get('topics', [])
        for t in topics[:max_count]:
            title = t.get('title', '').strip()
            if not title:
                continue
            # Filtre keywords si fourni
            if filter_kw:
                tl = title.lower()
                if not any(kw.lower() in tl for kw in filter_kw):
                    continue
            slug = t.get('slug', '')
            topic_id = t.get('id', 0)
            link = f"https://devforum.roblox.com/t/{slug}/{topic_id}"
            items.append({
                'title': title,
                'link': link,
                'guid': str(topic_id),
                'summary': (t.get('excerpt') or '')[:300].strip(),
                'image': t.get('image_url') or '',
                'pub_date': t.get('created_at', ''),
            })
    except Exception as ex:
        print(f"[game_updates _fetch_discourse {url}] {ex}")
    return items


# =============================================================================
# API PUBLIQUE
# =============================================================================

async def fetch_updates(session: aiohttp.ClientSession, game_key: str, max_count: int = 5) -> list[GameUpdate]:
    """Récupère les dernières mises à jour pour un game_key donné.

    Retourne une liste de GameUpdate, triés du plus récent au plus ancien.
    """
    spec = GAME_SOURCES.get(game_key)
    if not spec:
        return []

    source_type = spec.get('source_type')

    if source_type == 'steam_news':
        return await _fetch_steam_news(session, spec['appid'], max_count=max_count)

    elif source_type == 'discourse':
        raw = await _fetch_discourse(
            session,
            spec['source_url'],
            max_count=max_count,
            filter_kw=spec.get('filter_keywords'),
        )
        return [
            GameUpdate(
                game_key=game_key,
                update_id=r['guid'],
                title=r['title'][:200],
                url=r['link'],
                summary=r['summary'],
                image_url=r['image'],
                update_type="dev_update",
            )
            for r in raw
        ]

    elif source_type == 'rss':
        raw = await _fetch_rss(session, spec['source_url'], max_count=max_count)
        return [
            GameUpdate(
                game_key=game_key,
                update_id=r['guid'],
                title=r['title'][:200],
                url=r['link'],
                summary=r['summary'],
                image_url=r['image'],
                update_type="update",
            )
            for r in raw
        ]

    return []


def get_game_meta(game_key: str) -> dict:
    """Retourne les métadonnées d'un game_key (name, emoji, color) ou {} si inconnu."""
    spec = GAME_SOURCES.get(game_key, {})
    return {
        'name': spec.get('name', game_key.title()),
        'emoji': spec.get('emoji', '🎮'),
        'color': spec.get('color', 0x5865F2),
    }


def list_available_games() -> list[tuple[str, str, str]]:
    """Retourne liste de (key, emoji, name) pour tous les jeux supportés.

    Triés : plateformes en premier, puis jeux alphabétiquement.
    """
    platform_keys = ['roblox', 'steam', 'epic', 'blizzard', 'minecraft']
    out = []
    for k in platform_keys:
        if k in GAME_SOURCES:
            spec = GAME_SOURCES[k]
            out.append((k, spec['emoji'], spec['name']))
    game_keys = [k for k in GAME_SOURCES if k not in platform_keys]
    for k in sorted(game_keys, key=lambda x: GAME_SOURCES[x]['name'].lower()):
        spec = GAME_SOURCES[k]
        out.append((k, spec['emoji'], spec['name']))
    return out


__all__ = [
    "GameUpdate",
    "GAME_SOURCES",
    "fetch_updates",
    "get_game_meta",
    "list_available_games",
]
