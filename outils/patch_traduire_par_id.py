"""`traduire()` : le nom et la description en français, PAR IDENTIFIANT.

DEUX DÉFAUTS DE L'ANCIENNE VERSION, TROUVÉS LE 18/08
  1. Elle cherchait le nom français dans « les N derniers créés » en français.
     Un Limited ANCIEN qui vient de basculer n'y est jamais : sa fiche
     partait en anglais, structurellement.
  2. Sur un HTTP non-200 (un 429 après les relevés paginés), elle rendait
     SANS UN MOT. Le nom français disparaissait en silence — mesuré : « nom_fr
     non » sur le Chapeau Ladoo tricolore, dont la traduction existe.

CE QUI REMPLACE — mesuré en direct le 18/08
  POST https://catalog.roblox.com/v1/catalog/items/details
       {"items": [{"itemType": "Asset"|"Bundle", "id": …}, …]}
       en-tête Accept-Language: fr-fr
  → nom ET description en français, Assets ET Bundles, tout âge, UN appel :
       « Chapeau Ladoo tricolore », « Seigneur de la Buxeration »,
       « Sourire de la reine des neiges » (un Bundle).
  ⚠️ Le point exige un jeton XSRF : le premier POST répond 403 en le donnant
  dans l'en-tête `x-csrf-token`, le second l'utilise. Aucune authentification.
  Le jeton est gardé en mémoire et rafraîchi sur 403.

Écrit dans un fichier — piège n°3. `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_veille.py"

DEBUT = "async def traduire(articles: list[dict]) -> None:"
FIN = "def _normaliser(bruts: list) -> list[dict]:"

NOUVEAU = '''#  Le point de détails PAR IDENTIFIANT — le seul qui rende le nom français d'un
#  article quel que soit son âge, Assets et Bundles confondus.
API_DETAILS = "https://catalog.roblox.com/v1/catalog/items/details"
#  Jeton XSRF du point ci-dessus. Obtenu par un premier POST (403 attendu),
#  gardé, rafraîchi sur 403. Jamais une authentification : c'est public.
_jeton_xsrf: str | None = None


async def _details_fr(sess, articles: list[dict]) -> dict:
    """{(itemType, id): {"name", "description"}} en français, ou {} si rien.

    Ne lève pas. Journalise chaque non-200 : un nom français qui disparaît
    en silence est exactement le défaut qu'on répare.
    """
    global _jeton_xsrf
    items = []
    for a in articles:
        try:
            genre = "Bundle" if str(a.get("item_type") or "").lower() == "bundle" else "Asset"
            items.append({"itemType": genre, "id": int(a["asset_id"])})
        except (TypeError, ValueError, KeyError):
            continue
    if not items:
        return {}
    corps = {"items": items[:120]}
    for tentative in (1, 2):
        entetes = {"Accept-Language": LANGUE_FR}
        if _jeton_xsrf:
            entetes["X-CSRF-TOKEN"] = _jeton_xsrf
        try:
            async with sess.post(API_DETAILS, json=corps, headers=entetes) as r:
                if r.status == 403 and tentative == 1:
                    #  La danse XSRF : le 403 PORTE le jeton. On le prend et
                    #  on rejoue une fois.
                    _jeton_xsrf = r.headers.get("x-csrf-token") or _jeton_xsrf
                    continue
                if r.status != 200:
                    _log(f"[roblox_veille traduire] HTTP {r.status} sur "
                         f"{API_DETAILS.rsplit('/', 1)[-1]} — fiches en anglais")
                    return {}
                data = await r.json()
        except Exception as ex:
            _log(f"[roblox_veille traduire] {type(ex).__name__}: {ex}")
            return {}
        out = {}
        for x in (data.get("data") or []):
            try:
                out[(str(x.get("itemType") or "Asset"), int(x.get("id")))] = {
                    "name": str(x.get("name") or ""),
                    "description": str(x.get("description") or "").strip()}
            except (TypeError, ValueError):
                continue
        return out
    return {}


async def traduire(articles: list[dict]) -> None:
    """Pose le nom et la description FRANÇAIS OFFICIELS de Roblox. Sur place.

    On ne traduit jamais nous-mêmes : on demande à Roblox avec l'en-tête de
    langue, et on cite. Sans traduction officielle, l'article garde son
    anglais. Un appel pour tout le lot, par identifiants — voir `_details_fr`.

    ⚠️ Deux défauts de la version précédente, corrigés le 18/08 :
      · elle cherchait dans « les N derniers créés » — un Limited ancien qui
        vient de basculer n'y était jamais, sa fiche partait en anglais ;
      · sur un non-200 elle rendait sans un mot, et le français disparaissait
        en silence.
    """
    if not articles:
        return
    try:
        async with _ouvrir() as sess:
            fr = await _details_fr(sess, articles)
        for a in articles:
            genre = "Bundle" if str(a.get("item_type") or "").lower() == "bundle" else "Asset"
            d = fr.get((genre, int(a["asset_id"])))
            if not d:
                continue
            #  On ne garde le français que s'il DIFFÈRE : beaucoup d'articles
            #  n'ont pas de traduction, et afficher deux fois la même ligne
            #  ferait croire à un défaut.
            if d["name"] and d["name"] != a.get("nom"):
                a["nom_fr"] = d["name"][:120]
            if d["description"] and d["description"] != (a.get("description") or ""):
                a["description_fr"] = d["description"][:400]
    except Exception as ex:
        _log(f"[roblox_veille traduire] {ex}")


'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    i, j = src.find(DEBUT), src.find(FIN)
    if i == -1 or j == -1 or j <= i:
        print("❌ ancres introuvables — abandon.")
        return 1
    neuf = src[:i] + NOUVEAU + src[j:]
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    noms = {getattr(n, "name", None) for n in arbre.body}
    for attendu in ("traduire", "_details_fr", "_normaliser", "enrichir",
                    "relever_nouveautes", "relever_collectionnables"):
        if attendu not in noms:
            print(f"❌ {attendu} absent — abandon.")
            return 1
    print(f"  roblox_veille.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
