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
# FILTRE STRICT : "mises à jour" uniquement, pas d'événements/promos
# =============================================================================

# Phase 17.2 — l'utilisateur veut UNIQUEMENT les mises à jour (patch notes,
# hotfixes, dev updates), PAS les events / promos / tournois.

# Mots-clés POSITIFS — au moins UN doit être présent dans title ou summary
_UPDATE_POSITIVE_KEYWORDS = [
    # Patches
    'patch', 'patch notes', 'patch note',
    'hotfix', 'hot fix',
    # Updates
    'update', 'updated', 'mise à jour', 'mise a jour',
    'version', ' v.', 'ver.', 'build',
    # Notes
    'release notes', 'changelog', 'change log',
    # Dev
    'dev update', 'developer update', 'developer notes', 'dev notes',
    'dev blog', 'devblog', 'devnotes',
    # Bug fixes
    'bug fix', 'bug fixes', 'fixes', 'bugfix',
    # Roblox specifics
    'release notes', 'weekly recap',
    # Season / content updates
    'season ', 'season 1', 'season 2', 'season 3', 'season 4', 'season 5',
    'season 6', 'season 7', 'season 8', 'season 9', 'season 10',
    'chapter ', 'expansion ', 'new content',
    # Steam-specific
    'steam beta', 'steam client',
]

# Mots-clés NÉGATIFS — si présent, on REJETTE même si match positif
# Phase 17.2 affiné : retiré "major"/"cup"/"deal"/"championship"/"finals" qui causaient
# des faux positifs sur "Major Update" / "Cup Mode" / "we dealt with" / "Championship season"
_UPDATE_NEGATIVE_KEYWORDS = [
    # Events e-sports (très spécifiques pour éviter faux positifs)
    'tournament', 'esports', 'esport', 'pro league',
    'iem ', 'esl ', 'blast premier', 'dreamhack',
    'qualifier',
    # Promos (clairs)
    'sale', 'discount', 'free weekend', 'free trial',
    '% off', ' on sale',
    # Twitch (spécifique)
    'twitch drop', 'twitch drops', 'twitch reward',
    # Contests
    'contest', 'giveaway', 'sweepstake', 'raffle',
    # Community/fan content (pas une vraie update)
    'community spotlight', 'fan art', 'fan-art', 'cosplay',
    'screenshot of the week', 'artwork of the week',
    # Marketing
    'now available on', 'coming soon to', 'pre-order', 'preorder',
    'wishlist now', 'launch trailer', 'reveal trailer',
    'announcement trailer',
    # Recap qui ne sont pas dev (Roblox "Weekly Recap" géré en exception)
    'recap of the week',
]


def _is_real_update(title: str, summary: str = "") -> bool:
    """Filtre strict : retourne True UNIQUEMENT si c'est une vraie mise à jour.

    Phase 17.2 : pour respecter la demande "que ce soit bien les mises à jour
    et pas les actualités". Combine match positif + reject négatif.

    Règles :
    1. Title vide → REJET
    2. Exception Roblox "Weekly Recap" → ACCEPT (format officiel updates)
    3. Match keyword NÉGATIF (events/promos/etc.) → REJET (priorité)
    4. Match keyword POSITIF (patch/update/hotfix) → ACCEPTER
    5. Aucun match → REJET (par défaut on est strict)
    """
    text = f"{title} {summary}".lower().strip()
    if not text:
        return False

    # Exception : Roblox "Weekly Recap" = update officielle plateforme
    if 'weekly recap' in text:
        # Vérifie qu'il n'y a pas un keyword négatif fort
        for neg in ['tournament', 'esports', 'sale', 'giveaway', 'contest']:
            if neg in text:
                return False
        return True

    # 1. Reject si keyword négatif (priorité)
    for neg in _UPDATE_NEGATIVE_KEYWORDS:
        if neg in text:
            return False

    # 2. Accept si keyword positif
    for pos in _UPDATE_POSITIVE_KEYWORDS:
        if pos in text:
            return True

    # 3. Par défaut : strict, on rejette
    return False


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
    """Fetch news Steam pour un appid donné via Steam News API officielle.

    Phase 17.2 : fetch large (15 items) puis filtre _is_real_update() pour
    ne garder QUE les vraies mises à jour (patch/hotfix/update).
    """
    # On demande 15 items pour avoir de la marge après filtrage
    url = (
        f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        f"?appid={appid}&count=15&maxlength=400&format=json"
    )
    out = []
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return out
            data = await resp.json()
        news_items = data.get('appnews', {}).get('newsitems', [])
        for item in news_items:
            if len(out) >= max_count:
                break
            feedlabel = (item.get('feedlabel', '') or '').lower()
            # Première passe : feedlabel doit être officiel
            if not any(kw in feedlabel for kw in ['community', 'developer', 'announce', 'steam']):
                continue
            update_id = str(item.get('gid', '')) or str(item.get('url', ''))
            if not update_id:
                continue

            title = item.get('title', 'Sans titre')
            contents = item.get('contents', '') or ''
            # Clean summary (retire BBCode + HTML)
            summary = re.sub(r'\[/?[a-z]+(?:=[^\]]+)?\]', '', contents)[:300]
            summary = re.sub(r'<[^>]+>', '', summary).strip()

            # Phase 17.2 : filtre strict — uniquement les vraies updates
            if not _is_real_update(title, summary):
                continue

            # Extraire image
            image_url = ''
            img_m = re.search(r'\[img\](https?://[^\[]+)\[/img\]', contents)
            if img_m:
                image_url = img_m.group(1)
            else:
                img_m2 = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', contents)
                if img_m2:
                    image_url = img_m2.group(1)

            # Determiner le type d'update
            tl = title.lower()
            if 'hotfix' in tl or 'hot fix' in tl:
                update_type = "hotfix"
            elif 'patch' in tl or 'release notes' in tl:
                update_type = "patch"
            elif 'dev' in tl and ('update' in tl or 'note' in tl):
                update_type = "dev_update"
            else:
                update_type = "update"

            out.append(GameUpdate(
                game_key=f"steam:{appid}",
                update_id=update_id,
                title=title[:200],
                url=item.get('url', f'https://store.steampowered.com/news/app/{appid}'),
                summary=summary,
                image_url=image_url,
                posted_at=float(item.get('date', time.time())),
                update_type=update_type,
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
    """Parse une catégorie Discourse (devforum Roblox).

    Le devforum renvoie souvent un HTTP 202 depuis une IP datacenter (Railway) : c'est le
    CACHE ANONYME de Discourse qui se régénère en arrière-plan (« accepté, réessaie »), pas une
    vraie erreur. Le seul UA navigateur (correctif owner 2026-06-21) ne suffit plus → stratégie
    robuste vérifiée empiriquement le 2026-06-29 :
      1) requête .json (aiohttp suit le 301 → /…/36.json) ;
      2) sur 202, on RÉESSAIE quelques fois (le cache se réchauffe) ;
      3) si ça persiste (ou autre non-200), REPLI sur le flux .rss — servi en 200 même quand le
         JSON anonyme est challengé — avec le guid NORMALISÉ sur l'ID numérique du topic pour
         rester compatible avec la dédup (tracking_layer indexe sur update_id).
    FAIL-SAFE : à la fin, on loggue et on renvoie une liste vide (jamais de crash / de doublon).
    """
    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    def _parse_topics(data) -> list[dict]:
        out = []
        topics = (data.get('topic_list', {}) or {}).get('topics', []) or []
        for t in topics[:max_count]:
            title = (t.get('title') or '').strip()
            if not title:
                continue
            if filter_kw:
                tl = title.lower()
                if not any(kw.lower() in tl for kw in filter_kw):
                    continue
            topic_id = t.get('id', 0)
            out.append({
                'title': title,
                'link': f"https://devforum.roblox.com/t/{t.get('slug', '')}/{topic_id}",
                'guid': str(topic_id),
                'summary': (t.get('excerpt') or '')[:300].strip(),
                'image': t.get('image_url') or '',
                'pub_date': t.get('created_at', ''),
            })
        return out

    # 1+2) .json avec RETRY sur 202 (cache anonyme Discourse en régénération)
    last_status = None
    for attempt in range(3):
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                last_status = resp.status
                if resp.status == 200:
                    return _parse_topics(await resp.json())
                if resp.status == 202 and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))  # laisse le cache se réchauffer
                    continue
            break
        except Exception as ex:
            print(f"[game_updates _fetch_discourse {url}] {ex}")
            break

    # 3) REPLI sur le flux .rss (plus tolérant aux lecteurs automatisés)
    try:
        rss_url = re.sub(r'\.json(\?.*)?$', '.rss', url)
        if rss_url != url:
            raw = await _fetch_rss(session, rss_url, max_count=max_count)
            if raw:  # le .rss a répondu → on s'appuie dessus (succès, même si filtré à vide)
                items = []
                for r in raw:
                    if filter_kw and not any(kw.lower() in r['title'].lower() for kw in filter_kw):
                        continue
                    # guid = ID numérique du topic (= chemin JSON) pour ne PAS reposter d'anciens
                    m = re.search(r'/t/[^/]+/(\d+)', r.get('link', ''))
                    if m:
                        r['guid'] = m.group(1)
                    items.append(r)
                print(f"[game_updates _fetch_discourse {url}] HTTP {last_status} → repli .rss OK ({len(items)}/{len(raw)})")
                return items
    except Exception as ex:
        print(f"[game_updates _fetch_discourse {url} repli-rss] {ex}")

    print(f"[game_updates _fetch_discourse {url}] HTTP {last_status} — .json ET .rss indisponibles")
    return []


# =============================================================================
# API PUBLIQUE
# =============================================================================

async def fetch_updates(session: aiohttp.ClientSession, game_key: str, max_count: int = 5) -> list[GameUpdate]:
    """Récupère les dernières mises à jour pour un game_key donné.

    Phase 17.2 : tous les fetchers passent par _is_real_update() pour
    filtrer strictement (UNIQUEMENT patches/hotfixes/updates, pas d'événements).
    """
    spec = GAME_SOURCES.get(game_key)
    if not spec:
        return []

    source_type = spec.get('source_type')

    if source_type == 'steam_news':
        # _fetch_steam_news applique déjà _is_real_update en interne
        return await _fetch_steam_news(session, spec['appid'], max_count=max_count)

    elif source_type == 'discourse':
        # Fetch large + filtre par keywords source + filtre _is_real_update
        raw = await _fetch_discourse(
            session,
            spec['source_url'],
            max_count=max_count * 4,  # large pour avoir de la marge
            filter_kw=spec.get('filter_keywords'),
        )
        out = []
        for r in raw:
            # Phase 17.2 : double filtre — keywords source + filtre update strict
            if not _is_real_update(r['title'], r['summary']):
                continue
            out.append(GameUpdate(
                game_key=game_key,
                update_id=r['guid'],
                title=r['title'][:200],
                url=r['link'],
                summary=r['summary'],
                image_url=r['image'],
                update_type="dev_update",
            ))
            if len(out) >= max_count:
                break
        return out

    elif source_type == 'rss':
        raw = await _fetch_rss(session, spec['source_url'], max_count=max_count * 4)
        out = []
        for r in raw:
            if not _is_real_update(r['title'], r['summary']):
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

    elif source_type == 'rss_filtered':
        # Filtre KW source (game keywords) + filtre _is_real_update strict
        filter_kw = spec.get('filter_keywords') or []
        raw = await _fetch_rss(session, spec['source_url'], max_count=max_count * 6)
        out = []
        for r in raw:
            text = (r['title'] + ' ' + r['summary']).lower()
            # 1. Doit matcher au moins UN keyword du jeu (ex: 'wow' pour WoW)
            if filter_kw and not any(kw.lower() in text for kw in filter_kw):
                continue
            # 2. ET doit être une vraie update (pas event/promo)
            if not _is_real_update(r['title'], r['summary']):
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
