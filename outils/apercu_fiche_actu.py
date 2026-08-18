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
        if ty == 9:
            #  Section : ses textes, puis son accessoire (vignette ou bouton).
            _afficher(x.get("components", []) or [], ind)
            acc = x.get("accessory") or {}
            if acc.get("type") == 11:
                print(ind + f"   [VIGNETTE à droite] {acc.get('media', {}).get('url', '')[:70]}")
        elif ty == 10:
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

    if sys.argv[1] in ("accessoire", "limited"):
        #  La fiche d'ACCESSOIRE, sur un article réel du catalogue : le plus
        #  récent créé (mode « accessoire ») ou le Limited le plus récent en
        #  simulant sa bascule (mode « limited »). Même chaîne que la boucle :
        #  enrichir → traduire → vignettes → annonces liées → fiche.
        import roblox_veille as veille
        veille.setup(get_db=get_db, cfg=cfg, db_set=db_set, session=None, log=print)
        await veille.init_db()
        if sys.argv[1] == "limited":
            rel = await veille.relever_collectionnables(limite=30)
            flux = "bascules"
        else:
            rel = await veille.relever_nouveautes(limite=30)
            flux = "nouveautes"
        if not rel["articles"]:
            print("relevé vide, HTTP", rel["code"])
            return 1
        a = rel["articles"][0]
        if flux == "bascules":
            a["bascule_detectee"] = True     # on SIMULE la bascule pour l'aperçu
        await asyncio.sleep(2)
        await veille.enrichir([a])
        await veille.traduire([a])
        imgs = await veille.vignettes([a])
        #  Les annonces liées : on lit d'abord une source d'actualité pour
        #  remplir le registre, comme le ferait un vrai passage.
        src = next(s for s in news.SOURCES if s["cle"] == "annonces")
        await news.relever(src, forcer=True)
        lies = news.billets_lies(a.get("nom") or "")
        p = panneau.construire_fiche(a, flux, image=imgs.get(a["asset_id"]),
                                     lies=lies).to_components()
        print("═" * 60)
        _afficher(p)
        print("═" * 60)
        print(f"{_compter(p)} composants · {_texte(p)} caractères · image "
              f"{'oui' if imgs.get(a['asset_id']) else 'non'} · annonces liées {len(lies)} · "
              f"nom_fr {'oui' if a.get('nom_fr') else 'non'} · description "
              f"{'fr' if a.get('description_fr') else ('en' if a.get('description') else 'non')}")
        return 0

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
