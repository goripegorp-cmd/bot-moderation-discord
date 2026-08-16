"""Que peut-on VRAIMENT savoir d'un article Roblox ? Sonde exhaustive.

Deux questions du propriétaire (16/08), et une seule façon honnête d'y répondre :
ouvrir les points d'API et regarder.

  1. « Uniquement les items RÉCEMMENT devenus limited, pas ceux d'il y a des
     années. » → existe-t-il une date de PASSAGE en collectionnable, distincte
     de la date de création ?
  2. « Savoir si un item deviendra limited, mais il faut que tu sois sûr. »
     → quels signaux chiffrés existent réellement ?

⚠️ ROBLOX.md fixe déjà le cadre, mesuré sur 964 articles : `offSaleDeadline`
renseigné 0 fois, `itemStatus` vide 962 fois. Cette sonde vérifie s'il existe
AUTRE CHOSE — stock, reventes, vitesse — et sur quels points d'API.

Rolimons reste INTERDIT (ses CGU proscrivent l'accès automatisé). Aucune URL
rolimons ici, et aucun modèle entraîné (CGU Roblox).

Usage :
    PYTHONIOENCODING=utf-8 python outils/sonde_signaux_limited.py
"""
from __future__ import annotations

import asyncio
import json

import aiohttp

UA = {"User-Agent": "bot-moderation-discord/1.0 (veille Roblox)"}
PAUSE = 2.0

#  Deux Limiteds mesurés le 16/08 : un « récent » (152 j) et un historique.
LIMITED_RECENT = 87983592197138      # Lord of the Buxeration
LIMITED_ANCIEN = 1365767             # Valkyrie Helm
NON_LIMITED = 130206680836097        # Tricolor Ladoo Hat

POINTS = {
    "catalogue_details": "https://catalog.roblox.com/v2/search/items/details",
    "fiche_catalogue": "https://catalog.roblox.com/v1/catalog/items/{}/details",
    "economie": "https://economy.roblox.com/v2/assets/{}/details",
    "revendeurs": "https://economy.roblox.com/v1/assets/{}/resellers?limit=10",
    "reventes": "https://economy.roblox.com/v1/assets/{}/resale-data",
}

#  Les champs qui pourraient porter une DATE DE BASCULE.
CANDIDATS_DATE = (
    "created", "updated", "itemCreatedUtc", "createdUtc", "offSaleDeadline",
    "saleLocationType", "collectibleItemId", "itemStatus", "itemRestrictions",
)


async def _get(sess, url, **kw):
    try:
        async with sess.get(url, **kw) as r:
            corps = await r.text()
            try:
                return r.status, json.loads(corps)
            except Exception:
                return r.status, corps[:300]
    except Exception as ex:
        return None, f"{type(ex).__name__}: {ex}"


async def main() -> int:
    async with aiohttp.ClientSession(
            headers=UA, timeout=aiohttp.ClientTimeout(total=25)) as sess:

        for libelle, aid in (("LIMITED RÉCENT", LIMITED_RECENT),
                             ("LIMITED ANCIEN", LIMITED_ANCIEN),
                             ("NON LIMITED", NON_LIMITED)):
            print(f"\n{'═' * 70}\n  {libelle} — {aid}\n{'═' * 70}")

            for nom, gabarit in POINTS.items():
                if nom == "catalogue_details":
                    continue
                url = gabarit.format(aid)
                code, data = await _get(sess, url)
                print(f"\n  ── {nom} → HTTP {code}")
                if code != 200:
                    print(f"     {str(data)[:180]}")
                    await asyncio.sleep(PAUSE)
                    continue
                if isinstance(data, dict):
                    #  On affiche TOUT ce qui ressemble à une date ou à un
                    #  compteur : c'est là que se cache un signal exploitable.
                    interessants = {
                        k: v for k, v in data.items()
                        if k in CANDIDATS_DATE
                        or any(m in k.lower() for m in
                               ("price", "sale", "quantity", "remaining",
                                "count", "serial", "collectib", "resel"))}
                    for k, v in sorted(interessants.items()):
                        print(f"     {k:<28} {str(v)[:90]}")
                    autres = [k for k in data if k not in interessants]
                    if autres:
                        print(f"     -- autres champs : {', '.join(autres)[:150]}")
                else:
                    print(f"     {str(data)[:200]}")
                await asyncio.sleep(PAUSE)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
