"""
game_updates.py - Suivi des mises à jour officielles de plateformes et jeux.

Phase 17.1 (mai 2026) — Sources VÉRIFIÉES fonctionnelles.

Concept : permettre à l'owner de tracker dans un salon Discord les vraies
mises à jour (patch notes, dev updates) d'une plateforme/jeu spécifique.
PAS les events, ni les promos, ni le contenu social — UNIQUEMENT les
patch notes / changelogs / dev updates officiels.

═══ SOURCES VÉRIFIÉES (testées le 25 mai 2026) ═══

✅ Steam News API — fonctionne pour n'importe quel jeu Steam (par appid)
   Endpoint : api.steampowered.com/ISteamNews/GetNewsForApp/v2/
   Filtre : feedlabel contient "community" / "developer" / "announce" / "steam"

✅ Roblox DevForum — catégorie "Updates" (announcements.json)
   Endpoint : devforum.roblox.com/c/updates/announcements.json
   Filtre : keywords (update, release notes, patch, fix, improvement)

✅ BlizzardWatch — community RSS pour les jeux Blizzard sans RSS officiel
   (WoW, Hearthstone)
   Endpoint : blizzardwatch.com/feed/

═══ SOURCES SUPPRIMÉES (cassées en mai 2026) ═══

❌ news.blizzard.com/en-us/rss → 404 (pas d'API officielle Blizzard)
❌ store.epicgames.com/en-US/blog.rss → 403 (Cloudflare)
❌ genshin.hoyoverse.com/en/news.rss → 404 (HoYoverse n'expose pas de RSS)
❌ hsr.hoyoverse.com/en/news.rss → 404
❌ www.minecraft.net/en-us/feeds/community-content/rss → timeout/deprecated
❌ leagueoflegends.com page-data.json → format imprévisible
❌ playvalorant.com page-data.json → format imprévisible

═══ JEUX BLIZZARD SUR STEAM (utilisés à la place de RSS officiel) ═══

- Diablo IV : Steam appid 2344520 ✅ (vérifié)
- Overwatch 2 : Steam appid 2357570 ✅ (vérifié)

API publique :
    GAME_SOURCES — dict mapping game_key → fetcher config
    fetch_updates(session, game_key, last_seen_id) → list[GameUpdate]
    get_game_meta(game_key) → dict
    list_available_games() → list[tuple[key, emoji, name]]
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

    game_key: str
    update_id: str
    title: str
    url: str
    summary: str = ""
    image_url: str = ""
    posted_at: float = field(default_factory=lambda: time.time())
    update_type: str = "update"


# =============================================================================
# CONFIGURATION DES SOURCES (UNIQUEMENT CELLES VÉRIFIÉES FONCTIONNELLES)
# =============================================================================

# Filter pour BlizzardWatch : on garde uniquement si le titre/contenu contient
# un keyword associé au jeu (sinon on récupère tout le mélange)
_BLIZZ_FILTERS = {
    'wow': ['wow', 'world of warcraft', 'azeroth', 'mythic', 'raid', 'patch 11', 'patch 12',
            'expansion', 'dragonflight', 'war within'],
    'hearthstone': ['hearthstone', 'card', 'meta', 'deck'],
}


GAME_SOURCES = {
    # ════ PLATEFORMES ════

    "roblox": {
        "name": "Roblox (plateforme)",
        "emoji": "🟢",
        "color": 0x00A2FF,
        "source_type": "discourse",
        "source_url": "https://devforum.roblox.com/c/updates/announcements.json",
        "filter_keywords": ["update", "release notes", "patch", "improvement", "fix", "weekly recap"],
    },
    "steam_client": {
        "name": "Steam Client (plateforme)",
        "emoji": "🟦",
        "color": 0x1B2838,
        "source_type": "steam_news",
        "appid": 593110,
    },

    # ════ JEUX BLIZZARD VIA STEAM NEWS (officielles, vérifiées) ════

    "diablo4": {
        "name": "Diablo IV",
        "emoji": "👹",
        "color": 0x8B0000,
        "source_type": "steam_news",
        "appid": 2344520,
    },
    "overwatch": {
        "name": "Overwatch 2",
        "emoji": "🟧",
        "color": 0xFA9C1B,
        "source_type": "steam_news",
        "appid": 2357570,
    },

    # ════ JEUX BLIZZARD SANS STEAM (via blizzardwatch.com community filtré) ════

    "wow": {
        "name": "World of Warcraft",
        "emoji": "⚔️",
        "color": 0x2E6BA8,
        "source_type": "rss_filtered",
        "source_url": "https://blizzardwatch.com/feed/",
        "filter_keywords": _BLIZZ_FILTERS['wow'],
    },

    # ════ JEUX STEAM POPULAIRES (vérifiés via API officielle) ════

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
        "appid": 1922110,
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
        "name": "PUBG: Battlegrounds",
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
    "terraria": {
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
    "dota2": {
        "name": "Dota 2",
        "emoji": "⚡",
        "color": 0xE53935,
        "source_type": "steam_news",
        "appid": 570,
    },
    "tf2": {
        "name": "Team Fortress 2",
        "emoji": "🎩",
        "color": 0x5D7E84,
        "source_type": "steam_news",
        "appid": 440,
    },
    "elden_ring": {
        "name": "Elden Ring",
        "emoji": "⚔️",
        "color": 0xC9A227,
        "source_type": "steam_news",
        "appid": 1245620,
    },
    "destiny2": {
        "name": "Destiny 2",
        "emoji": "🌌",
        "color": 0x4A6FA5,
        "source_type": "steam_news",
        "appid": 1085660,
    },
    "warthunder": {
        "name": "War Thunder",
        "emoji": "✈️",
        "color": 0x4F5D73,
        "source_type": "steam_news",
        "appid": 236390,
    },
    "warframe": {
        "name": "Warframe",
        "emoji": "🤖",
        "color": 0x3C3F41,
        "source_type": "steam_news",
        "appid": 230410,
    },
    "marvelrivals": {
        "name": "Marvel Rivals",
        "emoji": "🦸",
        "color": 0xED1D24,
        "source_type": "steam_news",
        "appid": 2767030,
    },
    "deltaforce": {
        "name": "Delta Force",
        "emoji": "🎖️",
        "color": 0x2D572C,
        "source_type": "steam_news",
        "appid": 2507950,
    },
    "monster_hunter_wilds": {
        "name": "Monster Hunter Wilds",
        "emoji": "🐉",
        "color": 0xB45A1B,
        "source_type": "steam_news",
        "appid": 2246340,
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
            feedlabel = (item.get('feedlabel', '') or '').lower()
            # Filtrer : community announcements, developer notes, steam news officielles
            if not any(kw in feedlabel for kw in ['community', 'developer', 'announce', 'steam']):
                continue
            update_id = str(item.get('gid', '')) or str(item.get('url', ''))
            if not update_id:
                continue
            # Extraire image
            contents = item.get('contents', '') or ''
            image_url = ''
            img_m = re.search(r'\[img\](https?://[^\[]+)\[/img\]', contents)
            if img_m:
                image_url = img_m.group(1)
            else:
                img_m2 = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', contents)
                if img_m2:
                    image_url = img_m2.group(1)
            # Clean summary (retire BBCode + HTML)
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


async def _fetch_rss(session: aiohttp.ClientSession, url: str, max_count: int = 10) -> list[dict]:
    """Parse un flux RSS générique. Retourne items bruts."""
    items = []
    try:
        # User-Agent réaliste pour éviter les blocs Cloudflare
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml',
        }
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                print(f"[game_updates _fetch_rss {url}] HTTP {resp.status}")
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
            image = ''
            enc = item.find('enclosure')
            if enc is not None and enc.get('url'):
                image = enc.get('url')
            if not image and desc:
                img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc)
                if img_m:
                    image = img_m.group(1)
            summary = re.sub(r'<[^>]+>', '', desc)[:300].strip()
            items.append({
                'title': title, 'link': link, 'guid': guid,
                'summary': summary, 'image': image, 'pub_date': pub_date,
            })
        # Atom (fallback)
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


async def _fetch_discourse(session: aiohttp.ClientSession, url: str, max_count: int = 15, filter_kw: Optional[list[str]] = None) -> list[dict]:
    """Parse une catégorie Discourse (devforum Roblox)."""
    items = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                print(f"[game_updates _fetch_discourse {url}] HTTP {resp.status}")
                return items
            data = await resp.json()
        topics = data.get('topic_list', {}).get('topics', [])
        for t in topics[:max_count]:
            title = t.get('title', '').strip()
            if not title:
                continue
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
    """Récupère les dernières mises à jour pour un game_key donné."""
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
            max_count=max_count * 2,  # plus large pour le filtre
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
            for r in raw[:max_count]
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

    elif source_type == 'rss_filtered':
        # Comme rss mais filtre par keywords sur title (utile pour blizzardwatch
        # qui mélange WoW/Diablo/Hearthstone/Overwatch)
        filter_kw = spec.get('filter_keywords') or []
        raw = await _fetch_rss(session, spec['source_url'], max_count=max_count * 4)
        out = []
        for r in raw:
            tl = (r['title'] + ' ' + r['summary']).lower()
            if filter_kw and not any(kw.lower() in tl for kw in filter_kw):
                continue
            out.append(GameUpdate(
                game_key=game_key,
                update_id=r['guid'],
                title=r['title'][:200],
                url=r['link'],
                summary=r['summary'],
                image_url=r['image'],
                update_type="update",
            ))
            if len(out) >= max_count:
                break
        return out

    return []


def get_game_meta(game_key: str) -> dict:
    """Retourne les métadonnées d'un game_key."""
    spec = GAME_SOURCES.get(game_key, {})
    return {
        'name': spec.get('name', game_key.title()),
        'emoji': spec.get('emoji', '🎮'),
        'color': spec.get('color', 0x5865F2),
    }


def list_available_games() -> list[tuple[str, str, str]]:
    """Retourne liste (key, emoji, name) triés : plateformes, puis jeux alpha."""
    platform_keys = ['roblox', 'steam_client']
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
