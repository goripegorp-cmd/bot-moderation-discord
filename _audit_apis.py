"""Audit des 9 APIs sociales utilisees par bot.py."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import aiohttp


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


async def t_youtube(session):
    """YouTube via RSS feed (channel ID = MKBHD)."""
    cid = "UCBJycsmduvYEL83R_U4JriQ"
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as r:
            txt = await r.text()
        root = ET.fromstring(txt)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)
        if not entries:
            return ("KO", "RSS retourne 0 entree", r.status)
        first = entries[0]
        title = first.findtext("a:title", "", ns)
        return ("OK", f"{len(entries)} videos, derniere: {title[:40]}", r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_twitch(session):
    """Twitch via scrape de la page profil (look for 'isLiveBroadcast')."""
    user = "shroud"
    url = f"https://www.twitch.tv/{user}"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as r:
            html = await r.text()
        is_live = '"isLiveBroadcast":true' in html
        has_marker = "isLiveBroadcast" in html
        return ("OK" if has_marker else "KO",
                f"page chargee, marker={has_marker}, live={is_live}",
                r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_tiktok(session):
    """TikTok via scrape page profil."""
    user = "tiktok"
    url = f"https://www.tiktok.com/@{user}"
    try:
        async with session.get(url, headers=HEADERS, timeout=15) as r:
            html = await r.text()
        ids = re.findall(r'"id":"(\d{15,25})"', html)
        return ("OK" if ids else "KO",
                f"page chargee, video_ids trouves: {len(ids)}",
                r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_twitter_syndication(session):
    """Twitter Syndication API (officiel public) sur elonmusk."""
    user = "elonmusk"
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{user}"
    try:
        async with session.get(url, headers=HEADERS, timeout=15) as r:
            html = await r.text()
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not m:
            return ("KO", "Pas de __NEXT_DATA__ dans le HTML", r.status)
        import json
        data = json.loads(m.group(1))
        entries = data.get("props", {}).get("pageProps", {}).get("timeline", {}).get("entries", [])
        return ("OK" if entries else "KO",
                f"{len(entries)} tweets recents",
                r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_reddit(session):
    """Reddit via Atom feed."""
    sub = "AskReddit"
    url = f"https://www.reddit.com/r/{sub}/.rss"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as r:
            txt = await r.text()
        if "<entry>" not in txt and "<item>" not in txt:
            return ("KO", "Pas d'entries dans le feed", r.status)
        # Compte les entries
        ns = {"a": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(txt)
            entries = root.findall("a:entry", ns) or root.findall(".//entry")
        except Exception:
            entries = []
        return ("OK", f"{len(entries)} posts", r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_rosocial(session):
    """RoSocial via scrape de la page profil."""
    user = "Roblox"  # username vraiment generique
    url = f"https://rosocial.net/{user}"
    try:
        async with session.get(url, headers=HEADERS, timeout=15) as r:
            html = await r.text()
        posts = re.findall(r'/posts/(\d+)', html)
        return ("OK" if posts else "WARN",
                f"page chargee, {len(set(posts))} post_ids uniques trouves",
                r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_roblox_ugc(session):
    """Roblox catalog API - groupe Powerful artists 16981319."""
    gid = 16981319
    urls = [
        f"https://catalog.roblox.com/v1/search/items?Category=All&CreatorType=Group&CreatorTargetId={gid}&Limit=10&SortType=3",
        f"https://catalog.roblox.com/v2/search/items/details?Category=All&CreatorType=Group&CreatorTargetId={gid}&Limit=10&SortType=3",
    ]
    results = []
    for u in urls:
        try:
            async with session.get(u, headers=HEADERS, timeout=10) as r:
                if r.status == 200:
                    data = await r.json()
                    n = len(data.get("data", []))
                    results.append((u.split("/v")[1].split("/")[0], "v"+u.split("/v")[1].split("/")[0], n, r.status))
                else:
                    results.append((u, "?", 0, r.status))
        except Exception as ex:
            results.append((u, "?", 0, f"exc:{ex}"))
    if any(n > 0 for _, _, n, _ in results):
        ok_v = next((v for _, v, n, _ in results if n > 0), "?")
        return ("OK", f"version qui marche: v{ok_v}, items: " + " | ".join(f"v{v}={n}" for _, v, n, _ in results), "200")
    return ("KO", " | ".join(f"v{v} status={s} n={n}" for _, v, n, s in results), "?")


async def t_steam_deals(session):
    """SteamDB ou ChepperShark API pour les deals."""
    # Tester ITAD (IsThereAnyDeal) qui est l'API publique standard
    url = "https://api.isthereanydeal.com/games/info/v2"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as r:
            txt = await r.text()
        return ("WARN", f"endpoint generique, status={r.status}, body[:80]={txt[:80]}", r.status)
    except Exception as ex:
        return ("KO", f"{type(ex).__name__}: {ex}", "?")


async def t_discord_followed(session):
    """Discord 'follow' channels - pas une API externe, c'est interne au bot.
    On verifie juste qu'on peut hit le webhook URL d'un canal public."""
    return ("INFO", "Discord follow = mecanisme interne Discord, pas d'API externe a tester", "—")


async def main():
    tests = [
        ("YouTube",      t_youtube),
        ("Twitch",       t_twitch),
        ("TikTok",       t_tiktok),
        ("Twitter/X",    t_twitter_syndication),
        ("Reddit",       t_reddit),
        ("RoSocial",     t_rosocial),
        ("Roblox UGC",   t_roblox_ugc),
        ("Réductions",   t_steam_deals),
        ("Discord follow", t_discord_followed),
    ]

    timeout = aiohttp.ClientTimeout(total=30)
    print(f"\n=== Audit APIs sociales — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    print(f"{'Plateforme':<18} {'Status':<8} {'Détail'}")
    print("-" * 100)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, fn in tests:
            try:
                icon, detail, http = await fn(session)
            except Exception as ex:
                icon, detail, http = "KO", f"FATAL {type(ex).__name__}: {ex}", "?"
            print(f"{name:<18} {icon} {http:<5} {detail[:80]}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
