"""Audit approfondi : pour chaque API cassee, trouver le nouveau pattern."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import asyncio
import re
import json

import aiohttp


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


async def deep_twitch(session):
    """Trouver le nouveau marker 'live' dans la page Twitch."""
    print("\n=== TWITCH (shroud) ===")
    url = "https://www.twitch.tv/shroud"
    async with session.get(url, headers=HEADERS, timeout=10) as r:
        html = await r.text()
    print(f"HTTP {r.status}, taille HTML: {len(html)} bytes")

    markers = [
        '"isLiveBroadcast"',
        '"isLive":',
        '"liveBroadcast"',
        '"live":true',
        'data-live="true"',
        '"streamType":"live"',
        '"VideoPlayer__live"',
        'is_live',
        'streaming-now',
    ]
    for m in markers:
        present = m in html
        if present:
            idx = html.find(m)
            ctx = html[max(0,idx-30):idx+80]
            print(f"  TROUVE '{m}' ctx: {ctx[:100]}")
        else:
            print(f"  pas trouve: '{m}'")

    print(f"  URL probablement redirect ? {r.url}")
    print(f"  Snippet HTML[:500] : {html[:500]}")


async def deep_tiktok(session):
    """Trouver les video IDs dans une page TikTok."""
    print("\n=== TIKTOK (@tiktok) ===")
    url = "https://www.tiktok.com/@tiktok"
    async with session.get(url, headers=HEADERS, timeout=15) as r:
        html = await r.text()
    print(f"HTTP {r.status}, taille: {len(html)} bytes")

    patterns = {
        '"id":"\\d{15,25}"': r'"id":"(\d{15,25})"',
        'video/\\d{15,25}':  r'/video/(\d{15,25})',
        'aweme_id':          r'"aweme_id":"(\d+)"',
        'item_id':           r'"itemId":"(\d+)"',
        'data-id':           r'data-id="(\d+)"',
    }
    for desc, pat in patterns.items():
        matches = re.findall(pat, html)
        unique = set(matches)
        print(f"  pattern {desc!r}: {len(matches)} matches ({len(unique)} uniques)")

    # Cherche le SIGI_STATE, qui contient les vrai donnees
    sigi_match = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.DOTALL)
    if sigi_match:
        try:
            sigi = json.loads(sigi_match.group(1))
            print(f"  SIGI_STATE trouve, top keys: {list(sigi.keys())[:10]}")
        except Exception as e:
            print(f"  SIGI_STATE present mais parse error: {e}")
    else:
        print("  pas de SIGI_STATE (TikTok a peut-etre change)")

    # Universal data
    udi = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if udi:
        try:
            data = json.loads(udi.group(1))
            print(f"  __UNIVERSAL_DATA__ trouve, top keys: {list(data.keys())[:10]}")
            scope = data.get("__DEFAULT_SCOPE__", {})
            print(f"     __DEFAULT_SCOPE__ keys: {list(scope.keys())[:10]}")
        except Exception as e:
            print(f"  __UNIVERSAL_DATA__ parse error: {e}")
    else:
        print("  pas de __UNIVERSAL_DATA_FOR_REHYDRATION__")

    print(f"  HTML[:300]: {html[:300]}")


async def deep_rosocial(session):
    """Verifier l'URL RoSocial."""
    print("\n=== ROSOCIAL ===")
    for url in [
        "https://rosocial.net/",
        "https://rosocial.net/Roblox",
        "https://rosocial.com/",
    ]:
        try:
            async with session.get(url, headers=HEADERS, timeout=10, allow_redirects=True) as r:
                html = await r.text()
            print(f"  {url} -> HTTP {r.status} (final URL: {r.url}), taille: {len(html)}")
            if r.status == 200 and len(html) > 200:
                print(f"    HTML[:300]: {html[:300]}")
        except Exception as ex:
            print(f"  {url} -> erreur: {ex}")


async def deep_twitter(session):
    """Tenter Twitter avec backoff + alternatives."""
    print("\n=== TWITTER/X ===")
    user = "elonmusk"

    # 1. Syndication direct
    url1 = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{user}"
    async with session.get(url1, headers=HEADERS, timeout=15) as r:
        html = await r.text()
    print(f"  Syndication: HTTP {r.status}, taille: {len(html)}")
    if "Rate limit" in html:
        print(f"    -> rate limited explicitement")
    if "__NEXT_DATA__" in html:
        print(f"    -> __NEXT_DATA__ present")

    # 2. Nitter instances (alternative)
    nitter_instances = [
        "nitter.net",
        "nitter.privacydev.net",
        "nitter.cz",
    ]
    for inst in nitter_instances:
        try:
            url2 = f"https://{inst}/{user}/rss"
            async with session.get(url2, headers=HEADERS, timeout=8) as r:
                txt = await r.text()
            has_item = "<item>" in txt or "<entry>" in txt
            print(f"  Nitter {inst}: HTTP {r.status}, has_items={has_item}")
        except Exception as ex:
            print(f"  Nitter {inst}: ERREUR {type(ex).__name__}: {ex}")


async def deep_deals(session):
    """Tenter plusieurs APIs deals/promos jeux."""
    print("\n=== DEALS / REDUCTIONS ===")
    apis = [
        ("ITAD v2",     "https://api.isthereanydeal.com/games/info/v2"),
        ("CheapShark",  "https://www.cheapshark.com/api/1.0/deals?storeID=1&upperPrice=15&pageSize=5"),
        ("Steam search","https://store.steampowered.com/api/featuredcategories"),
    ]
    for name, url in apis:
        try:
            async with session.get(url, headers=HEADERS, timeout=10) as r:
                txt = await r.text()
            content = txt[:200]
            print(f"  {name}: HTTP {r.status}, body[:200]: {content}")
        except Exception as ex:
            print(f"  {name}: ERREUR {ex}")


async def main():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        await deep_twitch(session)
        await deep_tiktok(session)
        await deep_rosocial(session)
        await deep_twitter(session)
        await deep_deals(session)


if __name__ == "__main__":
    asyncio.run(main())
