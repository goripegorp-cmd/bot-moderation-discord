"""Branche le CONTENU (essentiel, images, vidéos, traduction) dans les sources.

Avant : chaque billet portait un titre, une date, un extrait d'une ligne et un
lien. Le propriétaire (18/08) : « les posts sont très moches, aucune
information, les textes sont coupés ». Il montre l'ancienne fiche : bilingue
FR puis EN, image pleine largeur, date — « c'est comme ça que tu les
transformes, voire même en mieux ».

Ce patch fait lire à chaque source le CORPS du billet :
  · forum    → `/t/{id}.json`, champ `cooked` du premier post (HTML complet,
               images en `lightbox`, vidéos YouTube et mp4) ;
  · newsroom → la page article, balise `<article>` + `og:image` — et le
               titre débarrassé de son « | Roblox » ;
  · presse   → la `description` du RSS, qui est le communiqué entier.

Puis `roblox_news_contenu.enrichir_billet` pose : corps, corps_fr, titre_fr,
images, videos, videos_fichiers, langue, traduit_par, pointeur.

Bornes : au plus `MAX_BILLETS_PAR_PASSAGE` corps lus par source et par relevé,
avec cache — en régime établi, 0 à 2 pages par passage. Les billets non encore
lus attendent le passage suivant plutôt que de partir vides.

Écrit dans un fichier — piège n°3. `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_news.py"

REMPLACEMENTS = [
    # ── 0. import du module de contenu
    ('''import asyncio
from datetime import datetime, timedelta, timezone
''',
     '''import asyncio
from datetime import datetime, timedelta, timezone

import roblox_news_contenu as contenu
'''),

    # ── 1. cache des corps du forum, à côté du cache newsroom
    ('''#  Cache des pages article déjà lues : {slug: billet}. Une page ne se lit
#  qu'une fois par vie du processus. Borné pour ne pas grossir sans fin.
_cache_newsroom: dict[str, dict] = {}
MAX_CACHE_NEWSROOM = 400
''',
     '''#  Cache des pages article déjà lues : {slug: billet}. Une page ne se lit
#  qu'une fois par vie du processus. Borné pour ne pas grossir sans fin.
_cache_newsroom: dict[str, dict] = {}
MAX_CACHE_NEWSROOM = 400

#  Cache des CORPS de billets du forum : {topic_id: billet enrichi}. Même
#  logique — une page `/t/{id}.json` par billet, une fois, puis traduction une
#  fois. Sans ce cache, chaque passage retraduirait les mêmes billets.
_cache_forum: dict[int, dict] = {}
MAX_CACHE_FORUM = 400


def _memoriser(cache: dict, cle, valeur, maximum: int) -> None:
    if len(cache) >= maximum:
        cache.pop(next(iter(cache)))
    cache[cle] = valeur
'''),

    # ── 2. le forum lit le corps des billets
    ('''async def _relever_discourse(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status == 200:
                data = await r.json()
                out["billets"] = _normaliser(data, source["domaine"])
            else:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
''',
     '''async def _relever_discourse(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status != 200:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
                return
            data = await r.json()
            frais = _normaliser(data, source["domaine"])

        #  ⚠️ LE CORPS, BILLET PAR BILLET — c'est ce qui rend la fiche complète.
        #  `/t/{id}.json` porte le premier post en HTML (`cooked`) : texte,
        #  images pleine taille, vidéos. On ne lit que les plus récents, dans
        #  la limite du plafond par passage, avec cache et pause. Un billet
        #  dont le corps n'est pas encore lu ATTEND le passage suivant : mieux
        #  vaut une fiche complète dans 30 min qu'une fiche vide maintenant.
        billets, pointeurs, lus = [], 0, 0
        for b in frais:
            enrichi = _cache_forum.get(b["topic_id"])
            if enrichi is None:
                if lus >= MAX_BILLETS_PAR_PASSAGE:
                    break
                lus += 1
                try:
                    async with sess.get(
                            f"{DOMAINE_FORUM}/t/{int(b['topic_id'])}.json") as rt:
                        if rt.status != 200:
                            _log(f"[roblox_news {source['cle']} corps "
                                 f"{b['topic_id']}] HTTP {rt.status}")
                            continue
                        tj = await rt.json()
                    posts = ((tj.get("post_stream") or {}).get("posts") or [])
                    cooked = str((posts[0] if posts else {}).get("cooked") or "")
                except Exception as ex:
                    _log(f"[roblox_news {source['cle']} corps {b['topic_id']}] {ex}")
                    continue
                finally:
                    await asyncio.sleep(1.5)
                enrichi = await contenu.enrichir_billet(dict(b), cooked, "en")
                _memoriser(_cache_forum, b["topic_id"], enrichi, MAX_CACHE_FORUM)
            if enrichi.get("pointeur"):
                #  « Allez voir ce lien » : écarté, et compté pour le dire.
                pointeurs += 1
                continue
            billets.append(enrichi)
        out["billets"] = billets
        out["pointeurs"] = pointeurs
'''),

    # ── 3. la presse : le communiqué entier est dans <description>
    ('''            desc = (item.findtext("description") or "").strip()
            import re
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\\s+", " ", desc).strip()
            out.append({
                "topic_id": f"presse:{slug}",
                "titre": titre[:200] or "—",
                "domaine": domaine,
                "cree_le": date,
                "extrait": (desc[:300] or None),
                "tags": [],
                "lien": lien,
            })''',
     '''            desc_html = (item.findtext("description") or "").strip()
            import re
            desc = re.sub(r"<[^>]+>", " ", desc_html)
            desc = re.sub(r"\\s+", " ", desc).strip()
            out.append({
                "topic_id": f"presse:{slug}",
                "titre": titre[:200] or "—",
                "domaine": domaine,
                "cree_le": date,
                "extrait": (desc[:300] or None),
                "tags": [],
                "lien": lien,
                #  Le communiqué ENTIER : `enrichir_billet` en tirera
                #  l'essentiel et la traduction. Gardé ici, consommé par
                #  `_relever_rss`, jamais publié tel quel.
                "_html": desc_html,
            })'''),

    ('''async def _relever_rss(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status == 200:
                out["billets"] = _normaliser_rss(await r.text(), source["domaine"])
            else:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
''',
     '''async def _relever_rss(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status != 200:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
                return
            bruts = _normaliser_rss(await r.text(), source["domaine"])
    billets, pointeurs = [], 0
    for b in bruts[:MAX_BILLETS_PAR_PASSAGE]:
        enrichi = _cache_forum.get(b["topic_id"])
        if enrichi is None:
            enrichi = await contenu.enrichir_billet(dict(b), b.pop("_html", ""), "en")
            enrichi.pop("_html", None)
            _memoriser(_cache_forum, b["topic_id"], enrichi, MAX_CACHE_FORUM)
        if enrichi.get("pointeur"):
            pointeurs += 1
            continue
        billets.append(enrichi)
    out["billets"] = billets
    out["pointeurs"] = pointeurs
'''),

    # ── 4. newsroom : le corps <article>, l'image og:image, le titre propre
    ('''    import html as _html
    import re
    def meta(prop):
        m = (re.search(r'property="' + prop + r'"\\s+content="([^"]*)"', html)
             or re.search(r'content="([^"]*)"\\s+property="' + prop + r'"', html))
        return _html.unescape(m.group(1)).strip() if m else None
    return {"date": meta("article:published_time"),
            "titre": meta("og:title"),
            "extrait": meta("og:description")}
''',
     '''    import html as _html
    import re
    def meta(prop):
        m = (re.search(r'property="' + prop + r'"\\s+content="([^"]*)"', html)
             or re.search(r'content="([^"]*)"\\s+property="' + prop + r'"', html))
        return _html.unescape(m.group(1)).strip() if m else None
    titre = meta("og:title") or ""
    #  ⚠️ « … | Roblox » : le suffixe du site, pas le titre. Il s'affichait
    #  sur chaque fiche — vu sur la capture du propriétaire.
    titre = re.sub(r"\\s*\\|\\s*Roblox\\s*$", "", titre).strip()
    art = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
    return {"date": meta("article:published_time"),
            "titre": titre or None,
            "extrait": meta("og:description"),
            "image": meta("og:image"),
            #  Le corps de l'article : c'est lui qui donne l'essentiel et les
            #  images du texte. Sans balise <article>, on ne devine rien.
            "corps_html": art.group(1) if art else ""}
'''),

    ('''                b = {
                    #  ⚠️ CLÉ DE DÉDUP COMMUNE AUX DEUX LANGUES. Le newsroom EN
                    #  et la salle de presse FR publient le MÊME article sous le
                    #  même slug. Avec une clé par source, il sortait deux fois
                    #  dans le salon. Une seule clé, et la source FR passe AVANT
                    #  la source EN dans `SOURCES` : le français quand Roblox
                    #  l'a traduit, l'anglais sinon — jamais les deux.
                    "topic_id": f"newsroom:{slug}",
                    "titre": (page.get("titre") or slug.rsplit("/", 1)[-1])[:200],
                    "domaine": source["domaine"],
                    "cree_le": page.get("date"),
                    "extrait": (page.get("extrait") or "")[:300] or None,
                    "tags": [],
                    "lien": lien,
                }
''',
     '''                b = {
                    #  ⚠️ CLÉ DE DÉDUP COMMUNE AUX DEUX LANGUES. Le newsroom EN
                    #  et la salle de presse FR publient le MÊME article sous le
                    #  même slug. Avec une clé par source, il sortait deux fois
                    #  dans le salon. Une seule clé, et la source FR passe AVANT
                    #  la source EN dans `SOURCES` : le français quand Roblox
                    #  l'a traduit, l'anglais sinon — jamais les deux.
                    "topic_id": f"newsroom:{slug}",
                    "titre": (page.get("titre") or slug.rsplit("/", 1)[-1])[:200],
                    "domaine": source["domaine"],
                    "cree_le": page.get("date"),
                    "extrait": (page.get("extrait") or "")[:300] or None,
                    "tags": [],
                    "lien": lien,
                }
                #  L'essentiel, les images (og:image en tête, puis celles du
                #  texte), la langue. La salle de presse FR est en français
                #  PAR ROBLOX : elle n'est jamais traduite, on cite.
                langue = "fr" if prefixe.startswith("/fr/") else "en"
                b = await contenu.enrichir_billet(b, page.get("corps_html") or "", langue)
                if page.get("image") and contenu._domaine_autorise(page["image"]):
                    b["images"] = ([page["image"]]
                                   + [i for i in b.get("images", []) if i != page["image"]]
                                   )[:contenu.MAX_IMAGES]
'''),
]


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}
    neuf = src
    for k, (a, b) in enumerate(REMPLACEMENTS, 1):
        if neuf.count(a) != 1:
            print(f"❌ ancre n°{k} trouvée {neuf.count(a)} fois — abandon.")
            print("   " + a.strip().splitlines()[0][:90])
            return 1
        neuf = neuf.replace(a, b)
        print(f"  ✅ n°{k}")
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    if avant - {getattr(n, "name", None) for n in arbre.body}:
        print("❌ symboles perdus")
        return 1
    print(f"  roblox_news.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
