"""rss_feeds.py — Abonnements RSS UNIVERSELS → Discord (owner 2026-06-24).

But : poster automatiquement les DERNIERS posts de Twitter/X, TikTok, Instagram (et de
n'importe quoi) dans un salon, SANS dépendre d'une API officielle morte. La méthode qui
MARCHE en 2026 = consommer un flux RSS généré par un service :
  • RSSHub (open-source, GRATUIT, auto-hébergeable — ex. template Railway) — routes
    /twitter/user/:id, /tiktok/user/:user, /instagram/user/:user… ;
  • RSS.app / FetchRSS (SaaS, setup 1 clic, essai gratuit) ;
  • ou TOUT flux RSS/Atom (YouTube, blog, news…).

L'owner colle l'URL du flux via /feed add ; le bot poll, dédup (par guid) et poste le lien
(que Discord prévisualise). 100% FAIL-SAFE : un flux qui tombe ne casse rien, n'empêche pas
les autres. Au 1er passage : on prend l'état actuel comme RÉFÉRENCE (zéro dump d'historique).
"""
from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET

import aiohttp
import discord

_bot = None
_get_db = None
_session: aiohttp.ClientSession | None = None

POLL_SECONDS = 600          # cadence de vérification (10 min) — anti-429
MAX_POST_PER_POLL = 3       # au plus N nouveaux posts par flux par passage (anti-flood)
MAX_SEEN = 60               # nb de guid mémorisés par flux (dédup borné)
_UA = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
    'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
}


def setup(bot_instance, get_db_fn):
    global _bot, _get_db
    _bot = bot_instance
    _get_db = get_db_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS rss_feeds("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, url TEXT, "
                "channel_id INTEGER, role_id INTEGER DEFAULT 0, label TEXT DEFAULT '', "
                "seen TEXT DEFAULT '', enabled INTEGER DEFAULT 1, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.commit()
        print("[rss_feeds] table prête")
    except Exception as ex:
        print(f"[rss_feeds init_db] {ex}")


async def _sess() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def _fetch(url: str, max_count: int = 10):
    """Parse un flux RSS 2.0 OU Atom. Renvoie (items, http_status). FAIL-SAFE."""
    items = []
    try:
        s = await _sess()
        async with s.get(url, headers=_UA, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            status = resp.status
            if status != 200:
                return items, status
            text = await resp.text()
        root = ET.fromstring(text)
        for item in root.findall('.//item')[:max_count]:
            link = (item.findtext('link') or '').strip()
            guid = (item.findtext('guid') or link or '').strip()
            title = (item.findtext('title') or '').strip()
            desc = item.findtext('description') or ''
            img = ''
            enc = item.find('enclosure')
            if enc is not None and enc.get('url'):
                img = enc.get('url')
            if not img and desc:
                m = re.search(r'<img[^>]+src=["\']([^"\']+)', desc)
                if m:
                    img = m.group(1)
            items.append({'guid': guid or title, 'link': link, 'title': title,
                          'summary': re.sub(r'<[^>]+>', '', desc)[:300].strip(), 'image': img})
        if not items:                      # Atom (fallback)
            ns = {'a': 'http://www.w3.org/2005/Atom'}
            for e in root.findall('.//a:entry', ns)[:max_count]:
                le = e.find('a:link', ns)
                link = le.get('href') if le is not None else ''
                guid = (e.findtext('a:id', namespaces=ns) or link or '').strip()
                title = (e.findtext('a:title', namespaces=ns) or '').strip()
                items.append({'guid': guid or title, 'link': link, 'title': title,
                              'summary': '', 'image': ''})
        return items, 200
    except Exception as ex:
        print(f"[rss_feeds _fetch {url}] {ex}")
        return items, 0


async def add_feed(guild_id, url, channel_id, role_id=0, label=''):
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO rss_feeds(guild_id, url, channel_id, role_id, label) VALUES(?,?,?,?,?)",
                (int(guild_id), str(url)[:500], int(channel_id), int(role_id or 0), str(label or '')[:80]))
            await db.commit()
            return cur.lastrowid
    except Exception as ex:
        print(f"[rss_feeds add_feed] {ex}")
        return None


async def list_feeds(guild_id):
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, url, channel_id, role_id, label, enabled FROM rss_feeds "
                "WHERE guild_id=? ORDER BY id", (int(guild_id),)) as cur:
                return list(await cur.fetchall())
    except Exception:
        return []


async def remove_feed(guild_id, feed_id):
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute("DELETE FROM rss_feeds WHERE id=? AND guild_id=?",
                                   (int(feed_id), int(guild_id)))
            await db.commit()
            return (getattr(cur, "rowcount", 0) or 0) > 0
    except Exception:
        return False


async def _save_seen(feed_id, guids):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("UPDATE rss_feeds SET seen=? WHERE id=?",
                             (json.dumps(list(guids)[:MAX_SEEN]), int(feed_id)))
            await db.commit()
    except Exception:
        pass


async def _poll_feed(row):
    fid, gid, url, chan_id, role_id, label, seen_json = row
    items, status = await _fetch(url)
    if status != 200 or not items:
        return
    try:
        seen = list(json.loads(seen_json or '[]'))
    except Exception:
        seen = []
    seen_set = set(seen)
    cur_guids = [it['guid'] for it in items if it.get('guid')]
    if not seen_set:                       # 1er passage = RÉFÉRENCE (pas de dump d'historique)
        await _save_seen(fid, cur_guids)
        return
    new_items = [it for it in items if it.get('guid') and it['guid'] not in seen_set]
    if not new_items:
        return
    ch = _bot.get_channel(int(chan_id)) if _bot else None
    if ch is not None:
        am = discord.AllowedMentions(everyone=False, users=False,
                                     roles=True if role_id else False)
        for it in reversed(new_items[:MAX_POST_PER_POLL]):     # du + ancien au + récent
            try:
                head = f"<@&{int(role_id)}> " if role_id else ""
                lbl = f"**{label}** — " if label else ""
                body = it.get('title') or "Nouveau post"
                link = f"\n{it['link']}" if it.get('link') else ""
                await ch.send(f"{head}{lbl}{body}{link}"[:1900], allowed_mentions=am)
                await asyncio.sleep(1)
            except Exception:
                pass
    await _save_seen(fid, cur_guids + [g for g in seen if g not in cur_guids])


async def poll_once():
    """Vérifie TOUS les flux activés et poste les nouveaux items. FAIL-SAFE par flux."""
    if _get_db is None:
        return
    rows = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, url, channel_id, role_id, label, seen FROM rss_feeds "
                "WHERE enabled=1") as cur:
                rows = list(await cur.fetchall())
    except Exception as ex:
        print(f"[rss_feeds poll_once] {ex}")
        return
    for row in rows:
        try:
            await _poll_feed(row)
        except Exception as ex:
            print(f"[rss_feeds poll {row[0] if row else '?'}] {ex}")
        await asyncio.sleep(0.5)           # throttle anti-429 entre flux
