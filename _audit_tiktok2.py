"""TikTok deeper - extraire vidList."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import asyncio, re, json
import aiohttp


async def main():
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    async with aiohttp.ClientSession() as session:
        for user in ["tiktok", "khaby.lame", "charlidamelio"]:
            print(f"\n=== TikTok @{user} ===")
            async with session.get(f"https://www.tiktok.com/@{user}", headers=HEADERS, timeout=15) as r:
                html = await r.text()
            m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                print("  pas de DATA")
                continue
            data = json.loads(m.group(1))
            scope = data.get("__DEFAULT_SCOPE__", {})

            # 1. seo.abtest.vidList
            vidlist = scope.get("seo.abtest", {}).get("vidList", [])
            print(f"  vidList: {len(vidlist)} entries, sample: {vidlist[:3]}")

            # 2. user info
            user_info = scope.get("webapp.user-detail", {}).get("userInfo", {})
            user_data = user_info.get("user", {}) if isinstance(user_info, dict) else {}
            stats = user_info.get("stats", {}) if isinstance(user_info, dict) else {}
            print(f"  user: id={user_data.get('id')}, secUid={(user_data.get('secUid') or '')[:30]}..., uniqueId={user_data.get('uniqueId')}")
            print(f"  stats: video count = {stats.get('videoCount')}")

            # 3. scrape "Posts" feed via API (item_list)
            sec_uid = user_data.get("secUid")
            if sec_uid:
                api_url = (
                    "https://www.tiktok.com/api/post/item_list/"
                    f"?aid=1988&secUid={sec_uid}&count=10&cursor=0"
                )
                try:
                    async with session.get(api_url, headers=HEADERS, timeout=10) as r2:
                        body = await r2.text()
                    if r2.status == 200 and body:
                        try:
                            j = json.loads(body)
                            items = j.get("itemList", [])
                            print(f"  api/post/item_list: {len(items)} items, status={r2.status}")
                            for it in items[:3]:
                                vid = it.get("id")
                                desc = (it.get("desc") or "")[:50]
                                created = it.get("createTime")
                                print(f"    - id={vid}, created={created}, desc={desc}")
                        except Exception as ex:
                            print(f"  parse err: {ex}, body[:200]: {body[:200]}")
                    else:
                        print(f"  api/post/item_list status={r2.status}, body[:200]: {body[:200]}")
                except Exception as ex:
                    print(f"  api/post/item_list erreur: {ex}")


asyncio.run(main())
