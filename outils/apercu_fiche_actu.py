"""Aperçu d'une fiche d'actualité RÉELLE, telle que Discord la recevra.

Sert à juger l'œil avant de publier : on relève une source en direct, on
construit la fiche, et on imprime le contenu texte, la galerie, les boutons,
le nombre de composants et le budget de texte.

    PYTHONIOENCODING=utf-8 python outils/apercu_fiche_actu.py annonces
    PYTHONIOENCODING=utf-8 python outils/apercu_fiche_actu.py newsroom_fr
    PYTHONIOENCODING=utf-8 python outils/apercu_fiche_actu.py forum 4779420
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiosqlite  # noqa: E402

import roblox_news as news  # noqa: E402
import roblox_news_contenu as contenu  # noqa: E402
import roblox_panneau as panneau  # noqa: E402


def _compter(p):
    n = 0
    for x in p:
        n += 1
        n += _compter(x.get("components", []) or [])
    return n


def _texte(p):
    n = 0
    for x in p:
        if x.get("type") == 10:
            n += len(x.get("content", ""))
        n += _texte(x.get("components", []) or [])
    return n


def _afficher(p, ind=""):
    for x in p:
        ty = x.get("type")
        if ty == 10:
            print(ind + x["content"])
        elif ty == 14:
            print(ind + "─" * 60)
        elif ty == 12:
            print(ind + f"[GALERIE — {len(x.get('items', []))} média(s)]")
            for it in x.get("items", []):
                print(ind + "   " + it["media"]["url"])
        elif ty == 1:
            print(ind + "[BOUTONS] " + " | ".join(
                f"{b.get('label')} → {b.get('url', '')}" for b in x.get("components", [])))
        elif ty == 17:
            _afficher(x.get("components", []), ind)


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    chemin = os.path.join(tempfile.mkdtemp(), "apercu.db")

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def cfg(gid):
        return {}

    async def db_set(gid, k, v):
        return None

    news.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=print)
    contenu.setup(log=print)
    panneau.setup(db_set=None, webhook_send=None, log=print)
    await news.init_db()

    if sys.argv[1] == "forum" and len(sys.argv) > 2:
        import aiohttp
        tid = int(sys.argv[2])
        async with aiohttp.ClientSession(
                headers={"User-Agent": "BotModerationDiscord/1.0", "Accept": "application/json"}) as s:
            async with s.get(f"{news.DOMAINE_FORUM}/t/{tid}.json") as r:
                tj = await r.json()
        cooked = tj["post_stream"]["posts"][0]["cooked"]
        b = {"topic_id": tid, "titre": tj.get("title"), "domaine": "Annonces",
             "cree_le": tj.get("created_at"), "extrait": None, "tags": []}
        b = await contenu.enrichir_billet(b, cooked, "en")
    else:
        src = next((s for s in news.SOURCES if s["cle"] == sys.argv[1]), None)
        if not src:
            print("source inconnue :", [s["cle"] for s in news.SOURCES])
            return 1
        rel = await news.relever(src, forcer=True)
        print(f"HTTP {rel['code']} · {len(rel['billets'])} billet(s) complets · "
              f"{rel.get('pointeurs', 0)} pointeur(s) écarté(s)\n")
        if not rel["billets"]:
            return 0
        b = rel["billets"][0]

    p = panneau.construire_actu(b).to_components()
    print("═" * 60)
    _afficher(p)
    print("═" * 60)
    print(f"{_compter(p)} composants (max 40) · {_texte(p)} caractères (max 4000) · "
          f"images {len(b.get('images') or [])} · vidéos {len(b.get('videos') or [])} · "
          f"langue {b.get('langue')} · traduit par {b.get('traduit_par')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
