"""site_wiki.py — le WIKI PUBLIC de RELL Seas, partageable (29/10/2026) : `/wiki`.

Le fondateur : « un onglet wiki qu'on peut partager aux gens… super bien protégé… uniquement des infos de RELL Seas, du
studio RELL Games… uniquement ce qui est vraiment réel, pas ce que les joueurs s'imaginent… traduit en français et en
langue internationale… mettre que le fondateur c'est moi, la direction, le lien du serveur Discord… pour protéger la
créativité de ce wiki. »

CE QUE LE WIKI MONTRE — le VÉRIFIÉ seulement
  · Les éléments du catalogue marqués « confirmé », avec un texte relu, sans supposition (`donnees_jeu/wiki_public.json`,
    français et anglais) ; un élément sans texte relu n'apparaît pas.
  · Hors catalogue (boss, lieux, systèmes) : seulement ce qu'une vidéo OFFICIELLE de RELL montre.
  · Chaque fiche porte sa preuve : la vidéo officielle et la minute (relevé `outils/videos_rellseas.py`). Jamais comment
    obtenir quoi que ce soit : le jeu n'est pas sorti, personne ne le sait encore.
  · Les crédits, lus en direct sur Discord : le fondateur (propriétaire du serveur), la direction (son rôle), le lien du
    serveur. Le jeu et ses images restent à RELL Games ; le wiki (textes, tri, mise en page) au clan.

LES ADRESSES (`health_server` ; lecture seule, sans session) : GET /wiki · GET /wiki/donnees
LES DÉFENSES : celles de la vitrine (cadence par adresse IP, CSP stricte, noindex, aucun cookie). Côté page : pas de
clic droit, de sélection, de glisser ni de raccourcis d'inspection, les images en fond et filigranées — un frein, pas un
coffre-fort : un navigateur montre toujours ce qu'il affiche.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from pathlib import Path

import acces_direction
import site_vitrine
import tableau

ADRESSE = "/wiki"
DONNEES = Path(__file__).resolve().parent / "donnees_jeu"
INVITATION = os.environ.get("WIKI_DISCORD", "https://discord.gg/HM9JpXrZqJ")   # le serveur du clan GoRP
FONDATEUR_DEFAUT = "GoRipe"
FRAIS = 600.0
FONDS = Path(__file__).resolve().parent / "site" / "wiki" / "fonds"
#  29/10/2026 (« que le wiki soit vivant, des fonds du studio ») : les illustrations OFFICIELLES (vignettes des vidéos
#  RELLGames, copiées par outils/wiki_images.py) — la bannière en fait défiler une sélection, chaque catégorie a la sienne.
HEROS = ("P2MhP3FeF2k", "JWpwr6hjdRo", "q09y0z5Vyxw", "9BkXvWPlGLc", "fkCXpll1jRI", "ji-L9CdSvN8", "O9XhIEAZ2r0")
FOND_TYPE = {"metier": "QuClr80Pmc0", "race": "Mm8Ybn-AzcE", "faction": "P2MhP3FeF2k", "mer": "9BkXvWPlGLc",
             "trait": "h_py6mPXKcI", "classe": "nbN6sXgREwA", "fruit": "JWpwr6hjdRo", "haki": "mDMlovdh4Cc",
             "carte_haki": "H2HHxKdWaoQ", "poster": "0SG9B3iJQtg", "style": "fkCXpll1jRI", "arme": "Q0eU4LDPtSE",
             "equipement": "rdFne7tJY68", "navire": "9BkXvWPlGLc", "piece_navire": "O9XhIEAZ2r0", "monture": "q09y0z5Vyxw",
             "monnaie": "ZCzdKbmQerg", "boss": "ji-L9CdSvN8", "lieu": "QuClr80Pmc0", "systeme": "q09y0z5Vyxw"}
CSP = site_vitrine.CSP.replace("form-action 'none'", "form-action 'none'; media-src 'none'")
_cache: dict = {}


def _lire(nom: str) -> dict:
    try:
        return json.loads((DONNEES / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _minute(t: int) -> str:
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def contenu() -> dict:
    """Les fiches du wiki (sans les crédits) : fonction pure sur les fichiers de `donnees_jeu/`."""
    cat, pub, vid = _lire("rell_catalogue.json"), _lire("wiki_public.json"), _lire("rell_videos.json")
    titres = {v["id"]: v["titre"] for v in vid.get("videos", [])}
    termes = vid.get("termes", {})
    ambigus = set()
    try:
        import savoir
        ambigus = {x.lower() for x in savoir.COMMUNS}
    except Exception:
        pass

    def fond(vid: str) -> str:
        return f"s/wiki/fonds/{vid}" if (FONDS / f"{vid}_p.webp").exists() else ""

    def preuves(nom_en: str) -> list:
        if nom_en.lower() in ambigus:
            return []
        return [{"titre": titres.get(v, "RELL"), "minute": _minute(t), "url": f"https://youtu.be/{v}?t={t}", "fond": fond(v)}
                for v, t in (termes.get(nom_en) or [])[:2]]
    types = [{"cle": t["cle"], "fr": t["nom"], "en": t.get("nom_en") or t["nom"]} for t in cat.get("types", [])]
    types += [{"cle": k, "fr": v[0], "en": v[1]} for k, v in pub.get("types", {}).items()]
    entrees = []
    for e in cat.get("elements", []):
        cle = f"{e['type']}.{e['cle']}"
        txt = pub.get("textes", {}).get(cle)
        if e.get("statut") != "confirme" or not e.get("actif", True) or not txt:
            continue
        entrees.append({"cle": cle, "type": e["type"], "nom": e["nom"], "nom_en": e["nom_en"], "fr": txt["fr"],
                        "en": txt["en"], "image": e.get("icone") or "", "m3": bool(e.get("nouveau_movie3")),
                        "groupe": e.get("categorie") or "", "preuves": preuves(e["nom_en"])})
    for cle, x in pub.get("hors_catalogue", {}).items():
        p = preuves(x["nom"])
        if not p:                       # hors catalogue : une preuve officielle, sinon rien
            continue
        entrees.append({"cle": cle, "type": x["type"], "nom": x["nom"], "nom_en": x["nom"], "fr": x["fr"], "en": x["en"],
                        "image": "", "m3": False, "groupe": "", "preuves": p})
    utilises = {e["type"] for e in entrees}
    for t in types:
        t["fond"] = fond(FOND_TYPE.get(t["cle"], ""))
        t["icone"] = next((e["image"] for e in entrees if e["type"] == t["cle"] and e["image"]), "")
    return {"types": [t for t in types if t["cle"] in utilises], "entrees": entrees,
            "heros": [{"fond": fond(v), "titre": titres.get(v, ""), "url": f"https://youtu.be/{v}"} for v in HEROS if fond(v)],
            "videos": [{"titre": v["titre"], "url": f"https://youtu.be/{v['id']}", "fond": fond(v["id"]),
                        "duree": _minute(int(v.get("duree") or 0)) if v.get("duree") else ""}
                       for v in vid.get("videos", [])],
            "releve": _lire("rell_wiki.json").get("releve", "")}


def credits(g) -> dict:
    """Le fondateur (propriétaire du serveur), la direction (son rôle, sans le fondateur), le lien du serveur."""
    proprio = getattr(g, "owner", None)
    fondateur = (getattr(proprio, "display_name", "") or FONDATEUR_DEFAUT) if proprio else FONDATEUR_DEFAUT
    direction = []
    for r in acces_direction.roles(g):
        if r.id not in acces_direction.DIRECTION_ROLE_IDS:
            continue
        for m in getattr(r, "members", []) or []:
            if getattr(m, "bot", False) or m.id == getattr(g, "owner_id", 0):
                continue
            n = re.sub(r"[\x00-\x1f<>]", "", str(getattr(m, "display_name", "") or ""))[:40]
            if n and n not in direction:
                direction.append(n)
    return {"clan": str(getattr(g, "name", "") or "GoRP SEA")[:60], "fondateur": fondateur[:40],
            "direction": direction[:12], "discord": INVITATION}


async def _entree(g) -> dict:
    e = _cache.get(g.id)
    if e is not None and time.monotonic() - e["t"] < FRAIS:
        return e
    d = dict(contenu(), credits=credits(g))
    corps = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    e = _cache[g.id] = {"t": time.monotonic(), "corps": corps, "etag": '"' + hashlib.sha256(corps).hexdigest()[:24] + '"',
                        "n": len(d["entrees"]), "pages": {}}
    return e


async def _ouvrir(request, genre: str):
    if site_vitrine._trop(request, genre):
        return None, site_vitrine._refus_cadence()
    g = await site_vitrine._guilde()
    if g is None:
        return None, site_vitrine._reponse(503, "Le wiki n'est pas ouvert pour le moment.")
    return (g, await _entree(g)), None


async def page(request):
    """`GET /wiki` : la page (aperçu du lien rempli)."""
    from aiohttp import web
    try:
        ouvert, refus = await _ouvrir(request, "wiki_page")
        if refus is not None:
            return refus
        g, e = ouvert
        base = site_vitrine._origine(request)
        texte = e["pages"].get(base)
        if texte is None:
            modele = tableau._lire_page_site("wiki.html")
            if modele is None:
                return site_vitrine._reponse(404, "Introuvable.")
            cr = credits(g)
            valeurs = {"OG_TITRE": f"Wiki RELL Seas · {cr['clan']}",
                       "OG_DESCRIPTION": f"Le wiki RELL Seas du clan {cr['clan']} : {e['n']} fiches vérifiées, preuves "
                                         "vidéo officielles à l'appui. FR · EN.",
                       "OG_URL": base + ADRESSE, "OG_IMAGE": f"{base}{ADRESSE}/banniere.png?v={e['etag'][1:9]}"}
            texte = re.sub(r"\{\{([A-Z_]{2,20})\}\}", lambda m: html.escape(str(valeurs.get(m.group(1), "")), quote=True),
                           modele)
            e["pages"] = {base: texte}
        etag = '"' + hashlib.sha256(texte.encode("utf-8")).hexdigest()[:24] + '"'
        entetes = dict(site_vitrine.ENTETES, **{"Content-Security-Policy": CSP, "Cache-Control": "no-cache", "ETag": etag})
        if etag in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        r = web.Response(text=texte, content_type="text/html", headers=entetes)
        r.enable_compression()
        return r
    except Exception as ex:
        site_vitrine._signaler("W1", "page du wiki en échec", ex)
        return site_vitrine._reponse(500, "Le wiki est indisponible pour le moment.")


async def donnees(request):
    """`GET /wiki/donnees` : les fiches et les crédits (JSON)."""
    from aiohttp import web
    try:
        ouvert, refus = await _ouvrir(request, "wiki_donnees")
        if refus is not None:
            return refus
        _g, e = ouvert
        entetes = dict(site_vitrine.ENTETES, **{"Content-Security-Policy": site_vitrine.CSP_IMAGE,
                                                "Cache-Control": "no-cache", "ETag": e["etag"]})
        if e["etag"] in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        r = web.Response(body=e["corps"], content_type="application/json", charset="utf-8", headers=entetes)
        r.enable_compression()
        return r
    except Exception as ex:
        site_vitrine._signaler("W2", "données du wiki en échec", ex)
        return site_vitrine._reponse(500, "Le wiki est indisponible pour le moment.")


async def vers_wiki(request):
    from aiohttp import web
    raise web.HTTPMovedPermanently(ADRESSE, headers=site_vitrine.ENTETES)


# ════════════════════════════════════════════════════════════════
#  L'aperçu du lien (1200 × 630) : l'illustration de Movie 3, le titre, les chiffres, le lien du clan
# ════════════════════════════════════════════════════════════════
_banniere: dict = {}


def dessiner_banniere(d: dict) -> bytes:
    """L'image que Discord (et toute messagerie) montre quand on colle le lien du wiki."""
    import io
    from PIL import Image, ImageDraw
    L, H = site_vitrine.LARGEUR, site_vitrine.HAUTEUR
    fond_vid = (d.get("heros") or [{}])[0].get("fond", "") or "s/wiki/fonds/q09y0z5Vyxw"
    chemin = FONDS / (fond_vid.rsplit("/", 1)[-1] + ".webp")
    try:
        with Image.open(chemin) as brut:
            im = brut.convert("RGB")
        im = site_vitrine._couvrir(im, (L, H)).convert("RGBA")
    except OSError:
        im = Image.new("RGBA", (L, H), (43, 29, 18, 255))
    voile = Image.new("RGBA", (L, H))
    dv = ImageDraw.Draw(voile)
    for x in range(L):                                   # sombre à gauche (le texte), l'image vit à droite
        a = int(225 * max(0.0, 1 - x / (L * 0.78)) + 40)
        dv.line([(x, 0), (x, H)], fill=(24, 15, 8, min(255, a)))
    im = Image.alpha_composite(im, voile)
    dr = ImageDraw.Draw(im)
    laiton, pale, clair = (201, 163, 90), (220, 192, 138), (246, 236, 214)
    dr.rectangle([18, 18, L - 18, H - 18], outline=laiton + (255,), width=3)
    dr.rectangle([28, 28, L - 28, H - 28], outline=(122, 90, 34, 255), width=1)
    dr.text((70, 70), "LE GRIMOIRE DE", font=site_vitrine._police("capitales", 34), fill=pale)
    dr.text((66, 108), "RELL Seas", font=site_vitrine._police("affiche", 104), fill=clair)
    cr = d.get("credits") or {}
    dr.text((70, 248), f"Le wiki vérifié du clan {cr.get('clan') or 'GoRP SEA'}", font=site_vitrine._police("texte", 40),
            fill=clair)
    n = len(d.get("entrees") or [])
    nb = {t: sum(1 for e in d.get("entrees") or [] if e["type"] == t) for t in ("fruit", "boss")}
    x = 70
    for txt in (f"{n} fiches", f"{nb['fruit']} fruits", f"{len(d.get('videos') or [])} vidéos officielles", "FR · EN"):
        f = site_vitrine._police("capitales", 28)
        w = dr.textlength(txt, font=f)
        dr.rounded_rectangle([x, 330, x + w + 36, 380], radius=8, fill=(74, 46, 26, 235), outline=laiton + (255,), width=2)
        dr.text((x + 18, 338), txt, font=f, fill=pale)
        x += w + 52
    dr.text((70, 430), "Seulement ce que RELL a montré : preuves vidéo à l'appui.",
            font=site_vitrine._police("italique", 30), fill=pale)
    lien = (cr.get("discord") or "").replace("https://", "")
    if lien:                                   # le code d'invitation garde sa casse : jamais en petites capitales
        debut = "Rejoins le clan : "
        dr.text((70, H - 110), debut, font=site_vitrine._police("capitales", 32), fill=laiton)
        x = 70 + dr.textlength(debut, font=site_vitrine._police("capitales", 32))
        dr.text((x, H - 112), lien, font=site_vitrine._police("texte", 34), fill=clair)
    dr.text((70, H - 66), "Wiki non officiel · RELL Seas © RELL Games", font=site_vitrine._police("texte", 22),
            fill=(185, 154, 107))
    out = io.BytesIO()
    im.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


async def banniere(request):
    """`GET /wiki/banniere.png` : l'aperçu du lien (redessiné quand le wiki change)."""
    import asyncio
    from aiohttp import web
    try:
        ouvert, refus = await _ouvrir(request, "wiki_page")
        if refus is not None:
            return refus
        g, e = ouvert
        deja = _banniere.get(g.id)
        if deja is None or deja[0] != e["etag"]:
            d = json.loads(e["corps"])
            deja = _banniere[g.id] = (e["etag"], await asyncio.to_thread(dessiner_banniere, d))
        entetes = dict(site_vitrine.ENTETES, **{"Content-Security-Policy": site_vitrine.CSP_IMAGE,
                                                "Cache-Control": "public, max-age=600", "ETag": deja[0],
                                                "Content-Type": "image/png", "Content-Disposition": "inline",
                                                "Cross-Origin-Resource-Policy": "cross-origin"})
        if deja[0] in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        return web.Response(body=deja[1], headers=entetes)
    except Exception as ex:
        site_vitrine._signaler("W3", "bannière du wiki en échec", ex)
        return site_vitrine._reponse(500, "Indisponible.")
