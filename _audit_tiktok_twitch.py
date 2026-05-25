"""Investigation approfondie TikTok + Twitch."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import asyncio
import json
import re

import aiohttp


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


async def tiktok_videos(session):
    """Extraire les videos d'un user TikTok via __UNIVERSAL_DATA_FOR_REHYDRATION__."""
    url = "https://www.tiktok.com/@tiktok"
    async with session.get(url, headers=HEADERS, timeout=15) as r:
        html = await r.text()

    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        print("Pas de UNIVERSAL_DATA")
        return
    data = json.loads(m.group(1))
    scope = data.get("__DEFAULT_SCOPE__", {})

    print(f"Top keys du scope: {list(scope.keys())}")
    for key in scope:
        v = scope[key]
        if isinstance(v, dict):
            sub = list(v.keys())[:8]
            print(f"  '{key}': {sub}")

    # Cherche les keys contenant "video"
    for key in scope:
        if "video" in key.lower() or "post" in key.lower() or "item" in key.lower():
            print(f"\nKey '{key}': {json.dumps(scope[key], default=str)[:500]}")

    # Cherche "ItemModule" ou similaire dans tout le scope
    raw = json.dumps(scope)
    for needle in ["ItemModule", "items", "itemList", "videoList", "userPosts", "PostsTab"]:
        if needle in raw:
            print(f"\n  '{needle}' present dans le scope")


async def twitch_gql(session):
    """Tester l'API GQL non-officielle de Twitch."""
    print("\n=== Twitch GQL (UseLive query) ===")
    # Client ID public utilise par le web Twitch (connu, pas un secret)
    client_id = "kimne78kx3ncx6brgo4mv6wki5h1ko"
    headers = dict(HEADERS)
    headers["Client-ID"] = client_id
    headers["Content-Type"] = "application/json"

    body = [{
        "operationName": "UseLive",
        "variables": {"channelLogin": "shroud"},
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": "639d5f11bfb8bf3053b424d9ef650d04c4ebb7d94711d644afb08fe9a0fad5d9"
            }
        }
    }]

    try:
        async with session.post("https://gql.twitch.tv/gql", json=body, headers=headers, timeout=10) as r:
            txt = await r.text()
        print(f"GQL status={r.status}, body[:400]: {txt[:400]}")
        if r.status == 200:
            data = json.loads(txt)
            try:
                live_data = data[0].get("data", {}).get("user", {}).get("stream")
                print(f"  Stream pour 'shroud': {live_data}")
            except Exception as ex:
                print(f"  parse err: {ex}")
    except Exception as ex:
        print(f"GQL failed: {ex}")


async def main():
    async with aiohttp.ClientSession() as session:
        await tiktok_videos(session)
        await twitch_gql(session)


asyncio.run(main())
