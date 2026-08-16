"""Sonde l'API catalogue : peut-on lister les articles COLLECTIONNABLES ?

POURQUOI CETTE SONDE
Le propriétaire signale que des accessoires passés Limited ne sortent pas.
Lecture du code : `relever_nouveautes()` interroge le catalogue avec
`SortType=3` (le plus récent) + `CreatorTargetId=1`. Elle rend donc les N
articles les plus récemment CRÉÉS par Roblox.

Or `comparer_et_enregistrer()` ne détecte une bascule que pour un article
PRÉSENT dans ce relevé. Un accessoire créé il y a six mois qui devient Limited
aujourd'hui n'est pas dans « les 60 derniers créés » : il n'est jamais relevé,
donc sa bascule n'est jamais vue. Le système ne peut détecter que les bascules
d'articles très récents — alors que ce sont souvent les anciens qui passent.

Cette sonde cherche un paramètre qui liste les collectionnables EUX-MÊMES,
indépendamment de leur date de création.

⚠️ DOCTRINE DU DÉPÔT : « une source n'est retenue que si elle a été ouverte et
lue, avec un extrait réel à l'appui ». On mesure, on ne suppose pas. Débit
respecté : une poignée d'appels, 2 s entre chaque.

Usage :
    PYTHONIOENCODING=utf-8 python outils/sonde_limiteds.py
"""
from __future__ import annotations

import asyncio
import json
import sys

import aiohttp

API = "https://catalog.roblox.com/v2/search/items/details"
UA = {"User-Agent": "bot-moderation-discord/1.0 (veille Roblox)"}
PAUSE = 2.0

#  Chaque essai : un libellé, et les paramètres exacts. On garde le paramétrage
#  de base connu (Category 1 = accessoires, créateur Roblox) et on fait varier
#  UNE chose à la fois — sinon on ne sait pas ce qui a marché.
ESSAIS = [
    ("référence — les plus récents créés (ce que fait le bot aujourd'hui)",
     {"Category": 1, "SortType": 3, "Limit": 10,
      "CreatorType": "User", "CreatorTargetId": 1}),
    ("SalesTypeFilter=2 (Limited) + créateur Roblox",
     {"Category": 1, "SortType": 3, "Limit": 10, "SalesTypeFilter": 2,
      "CreatorType": "User", "CreatorTargetId": 1}),
    ("SalesTypeFilter=2 SANS filtre de créateur",
     {"Category": 1, "SortType": 3, "Limit": 10, "SalesTypeFilter": 2}),
    ("SalesTypeFilter=2 + SortType=1 (plus favoris)",
     {"Category": 1, "SortType": 1, "Limit": 10, "SalesTypeFilter": 2,
      "CreatorType": "User", "CreatorTargetId": 1}),
    ("SalesTypeFilter=3 (Collectible)",
     {"Category": 1, "SortType": 3, "Limit": 10, "SalesTypeFilter": 3,
      "CreatorType": "User", "CreatorTargetId": 1}),
]


def _resume(brut: dict) -> str:
    coll = brut.get("collectibleItemId") or brut.get("itemRestrictions") or []
    return (f"{str(brut.get('name'))[:34]:<36} "
            f"id={brut.get('id')} "
            f"restrictions={coll if isinstance(coll, list) else 'oui'} "
            f"prix={brut.get('price')} "
            f"stock={brut.get('unitsAvailableForConsumption')}")


async def main() -> int:
    async with aiohttp.ClientSession(
            headers=UA, timeout=aiohttp.ClientTimeout(total=25)) as sess:
        for libelle, params in ESSAIS:
            print(f"\n═══ {libelle}")
            print(f"    {params}")
            try:
                async with sess.get(API, params=params) as r:
                    print(f"    HTTP {r.status}")
                    if r.status != 200:
                        print(f"    corps : {(await r.text())[:220]}")
                        await asyncio.sleep(PAUSE)
                        continue
                    data = await r.json()
                    items = data.get("data") or []
                    print(f"    {len(items)} article(s)")
                    #  Combien portent réellement une restriction « Limited » ?
                    limiteds = [
                        x for x in items
                        if any("Limited" in str(v)
                               for v in (x.get("itemRestrictions") or []))]
                    print(f"    dont Limited/LimitedUnique : {len(limiteds)}")
                    for x in items[:5]:
                        print(f"      {_resume(x)}")
            except Exception as ex:
                print(f"    ❌ {type(ex).__name__}: {ex}")
            await asyncio.sleep(PAUSE)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
