"""26/10/2026 — modifier une annonce DÉJÀ PUBLIÉE depuis le site de l'équipage ; la bannière aux dimensions exactes.

Le fondateur : « que uniquement nous […] la direction, la fondation, on puisse modifier les annonces qu'on a déjà
postées, que ça se modifie bien, que ça riposte pas une annonce, mais que ça fasse un truc au propre. Que l'affichage
soit nickel, qu'on peut même mettre une bannière au propre avec des dimensions exactes ».

B la bannière (`bannieres.py`) : 1600 × 640 exacts, réduite jamais étirée ; au mauvais rapport, recadrée AU CENTRE ;
  trop petite : refusée avec la taille reçue et la taille demandée ; type interdit ; trop de pixels ; l'orientation de
  l'appareil photo ; les nombres de la page (`site/banniere.js`) sont ceux du serveur.
M la modification (`evenements.modifier`, sur un faux Discord) : le message est ÉDITÉ, jamais envoyé ; le message
  disparu est dit, rien ne se republie ; la version périmée (409) ; jamais un message de plus (texte trop long, liste
  qui grandit) ; les liens ; l'aperçu n'écrit rien.
S le VRAI site local (`outils/site_local.py`) : la portée « equipage » refusée partout ; la tête modifie l'annonce depuis
  l'accueil — même message Discord, l'administration voit la même version, l'équipage aussi, journal ; le verrou de
  l'administration (`evenement:<id>`, 423) ; l'aperçu n'écrit rien ; la bannière par l'adresse `media` ; le câblage.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import struct
import zlib
from pathlib import Path

import pytest

import bannieres
import evenements as EV
import test_site_equipage as _socle
from test_evenements import T0, api, brouillon, courir, derniere_carte, env, publier  # noqa: F401  (env : la fixture)
from test_site_equipage import DIRECTION, FONDATEUR, KOLAX, ORIGINE  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
local = _socle.local   # le même site local que test_site_equipage.py (un à part pour ce fichier : portée « module »)


# ═══════════════════════════════════════════════════════════════════════════════
#  B — la bannière aux dimensions exactes
# ═══════════════════════════════════════════════════════════════════════════════

def _image(l, h, fmt="PNG", dessin=None, mode="RGB", exif=None) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new(mode, (l, h), (200, 30, 30) if mode == "RGB" else (200, 30, 30, 120))
    if dessin:
        dessin(ImageDraw.Draw(im), l, h)
    tampon = io.BytesIO()
    im.save(tampon, fmt, **({"exif": exif} if exif is not None else {}))
    return tampon.getvalue()


def _lue(r):
    from PIL import Image
    return Image.open(io.BytesIO(r["octets"])).convert("RGBA")


def _rond(px, l, h, couleur) -> tuple:
    """(largeur, hauteur) de la tache de `couleur` (à 60 près) : un cercle reste un cercle (jamais étiré)."""
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, l, 2):
            r, v, b, _a = px[x, y]
            if abs(r - couleur[0]) < 60 and abs(v - couleur[1]) < 60 and abs(b - couleur[2]) < 60:
                xs.append(x)
                ys.append(y)
    return max(xs) - min(xs), max(ys) - min(ys)


def test_B1_la_taille_exacte_reduite_jamais_etiree():
    def cercle(d, l, h):
        d.ellipse((l // 2 - 200, h // 2 - 200, l // 2 + 200, h // 2 + 200), fill=(0, 0, 0))
    r = bannieres.recadrer(_image(3200, 1280, "PNG", cercle))
    im = _lue(r)
    assert im.size == (r["largeur"], r["hauteur"]) == (1600, 640) and r["type"] in ("image/webp", "image/png")
    assert r["source"] == [3200, 1280] and r["coupe"] == [0, 0, 3200, 1280] and r["recadree"] is False
    lw, lh = _rond(im.load(), 1600, 640, (0, 0, 0))
    assert abs(lw - 200) <= 4 and abs(lh - 200) <= 4, f"le cercle est resté un cercle : {lw} × {lh}"
    assert bannieres.recadrer(_image(1600, 640))["recadree"] is False, "déjà à la taille : gardée telle quelle"
    #  Les métadonnées partent (une image neuve, pixel par pixel).
    assert b"Exif" not in r["octets"][:200]


def test_B2_au_mauvais_rapport_recadree_au_centre():
    def bandes_h(d, l, h):   # 16:9 : le haut et le bas tombent, le milieu (vert) reste
        d.rectangle((0, 0, l, 155), fill=(255, 0, 0))
        d.rectangle((0, 156, l, 923), fill=(0, 200, 0))
        d.rectangle((0, 924, l, h), fill=(0, 0, 255))
        d.ellipse((l // 2 - 150, h // 2 - 150, l // 2 + 150, h // 2 + 150), fill=(0, 0, 0))
    r = bannieres.recadrer(_image(1920, 1080, "PNG", bandes_h))
    px = _lue(r).load()
    assert r["coupe"] == [0, 156, 1920, 924] and r["recadree"] is True and r["source"] == [1920, 1080]
    for x, y in ((5, 5), (1594, 5), (5, 634), (1594, 634), (800, 20)):
        rr, v, b, _a = px[x, y]
        assert v > 150 and rr < 90 and b < 90, f"({x},{y}) : seul le centre est gardé {px[x, y]}"
    lw, lh = _rond(px, 1600, 640, (0, 0, 0))
    assert abs(lw - lh) <= 4, f"jamais étirée : {lw} × {lh}"

    def bandes_v(d, l, h):   # 4:1 : les côtés tombent
        d.rectangle((0, 0, 749, h), fill=(255, 0, 0))
        d.rectangle((750, 0, 3249, h), fill=(0, 200, 0))
        d.rectangle((3250, 0, l, h), fill=(0, 0, 255))
    r = bannieres.recadrer(_image(4000, 1000, "PNG", bandes_v))
    px = _lue(r).load()
    assert r["coupe"] == [750, 0, 3250, 1000]
    assert all(px[x, 320][1] > 150 and px[x, 320][0] < 90 for x in (2, 800, 1597))
    #  Portrait : la bande du milieu, recadrée (l'éditeur la montre avant d'enregistrer).
    r = bannieres.recadrer(_image(2000, 3000, "WEBP"))
    assert _lue(r).size == (1600, 640) and r["coupe"] == [0, 1100, 2000, 1900]


def test_B3_trop_petite_refusee_avec_la_taille_recue_et_demandee():
    for l, h in ((1200, 480), (1600, 639), (1599, 640), (800, 300)):
        with pytest.raises(bannieres.Refus) as ex:
            bannieres.recadrer(_image(l, h))
        e = ex.value
        assert e.code == "petite" and e.statut == 400
        assert f"{l} × {h} px reçue" in e.message and "1600 × 640 px" in e.message and "5:2" in e.message, e.message
        assert e.corps()["recue"] == [l, h] and e.corps()["demandee"] == [1600, 640] and e.corps()["champ"] == "image"
    assert bannieres.recadrer(_image(1600, 640))["largeur"] == 1600, "exactement la taille : acceptée"


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF", "ICO"])
def test_B4_un_type_interdit(fmt):
    with pytest.raises(bannieres.Refus) as ex:
        bannieres.recadrer(_image(1600 if fmt != "ICO" else 64, 640 if fmt != "ICO" else 64, fmt))
    assert ex.value.code == "format" and ex.value.statut == 415 and ex.value.message == bannieres.REFUS_FORMAT
    for brut in (b'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="640"/>', b"%PDF-1.4", b"ceci n'est pas une image", b""):
        with pytest.raises(bannieres.Refus):
            bannieres.recadrer(brut)


def _png_entete(l, h) -> bytes:
    """Un PNG qui ANNONCE l'image (l × h) sans la porter : la taille est refusée avant tout décodage."""
    ihdr = struct.pack(">IIBBBBB", l, h, 8, 2, 0, 0, 0)
    morceau = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + morceau(b"IHDR", ihdr) + morceau(b"IDAT", zlib.compress(b"\x00" * 10)) + morceau(b"IEND", b"")


def test_B5_les_limites_strictes_avant_de_decoder():
    for l, h in ((7000, 7000), (20000, 700)):
        with pytest.raises(bannieres.Refus) as ex:
            bannieres.recadrer(_png_entete(l, h))
        assert ex.value.code == "pixels" and ex.value.statut == 413, (l, h)
    with pytest.raises(bannieres.Refus) as ex:
        bannieres.recadrer(b"\x00" * (bannieres.OCTETS_MAX + 1))
    assert ex.value.statut == 413
    #  Un fichier tronqué : illisible, jamais une exception qui remonte.
    complet = _image(2000, 800, "PNG", lambda d, l, h: d.rectangle((0, 0, l, h // 2), fill=(0, 90, 0)))
    with pytest.raises(bannieres.Refus):
        bannieres.recadrer(complet[: len(complet) // 2])


def test_B6_l_orientation_de_l_appareil_photo_et_la_transparence():
    from PIL import Image
    exif = Image.Exif()
    exif[0x0112] = 6   # « tourner de 90° » : ce qui s'affiche a la largeur et la hauteur échangées
    debout = _image(640, 1600, "JPEG", exif=exif.tobytes())
    r = bannieres.recadrer(debout)
    assert r["source"] == [1600, 640] and _lue(r).size == (1600, 640)
    couche = _image(1600, 640, "JPEG", exif=exif.tobytes())
    with pytest.raises(bannieres.Refus) as ex:
        bannieres.recadrer(couche)
    assert "640 × 1600 px reçue" in ex.value.message, "la taille telle qu'elle s'affiche"
    r = bannieres.recadrer(_image(1600, 640, "PNG", mode="RGBA"))
    assert _lue(r).getpixel((10, 10))[3] < 200, "la transparence est gardée"


def test_B7_les_nombres_de_la_page_sont_ceux_du_serveur():
    js = (RACINE / "site" / "banniere.js").read_text(encoding="utf-8")
    assert f'largeur: {bannieres.LARGEUR}, hauteur: {bannieres.HAUTEUR}, rapport: "{bannieres.RAPPORT}"' in js
    assert f'export const CONSIGNE = "{bannieres.CONSIGNE}";' in js
    assert f'formats: "{bannieres.NOMS_FORMATS}"' in js and "octetsMax: 8 * 1024 * 1024" in js
    assert bannieres.LARGEUR / bannieres.HAUTEUR == 2.5 and bannieres.CONSIGNE == \
        "Bannière : 1600 × 640 px (5:2) · PNG, JPG ou WebP · 8 Mo au plus"
    css = (RACINE / "site" / "banniere.css").read_text(encoding="utf-8")
    assert css.count("aspect-ratio: 5 / 2") >= 3, "le même rapport partout où la bannière s'affiche"
    assert bannieres.spec() == {"largeur": 1600, "hauteur": 640, "rapport": "5:2", "formats": "PNG, JPG ou WebP",
                                "octets_max": 8 * 1024 * 1024, "consigne": bannieres.CONSIGNE}


# ═══════════════════════════════════════════════════════════════════════════════
#  M — la modification sur Discord : en place, jamais un message de plus
# ═══════════════════════════════════════════════════════════════════════════════

def _boutons_liens(vue) -> list:
    out = []

    def voir(c):
        if isinstance(c, dict):
            if c.get("type") == 2 and c.get("url"):
                out.append((c.get("label"), c["url"]))
            for x in c.get("components", []) or []:
                voir(x)
    for comp in vue.to_components():
        voir(comp)
    return out


def test_M1_le_message_est_edite_en_place_jamais_envoye(env):
    a = brouillon(env, type="annonce", titre="Grande nouvelle", texte="Texte avec une fote", image="img1")
    r = publier(env, a)
    mid = env.infos.messages[-1].id
    n_messages, n_envois = len(env.infos.messages), len(env.infos.envois)
    liens = [{"nom": "Le site du jeu", "url": "https://www.roblox.com/games/1"}, {"nom": "", "url": ""},
             {"nom": "Le règlement", "url": "https://exemple.org/regles"}]
    statut, rep = api(env, "clan/modifier", {"id": a["id"], "version": r["element"]["version"], "titre": "Grande nouvelle (corrigée)",
                                             "texte": "Texte corrigé.", "liens": liens})
    assert statut == 200, rep
    assert len(env.infos.messages) == n_messages and len(env.infos.envois) == n_envois, "rien n'est envoyé : jamais republié"
    assert env.infos.cartes[-1][0] == mid and rep["lien"].endswith(f"/{mid}"), "le MÊME message, réécrit"
    vue = derniere_carte(env.infos, mid)
    assert "Grande nouvelle (corrigée)" in json.dumps(vue.to_components(), ensure_ascii=False)
    assert _boutons_liens(vue) == [("Le site du jeu", "https://www.roblox.com/games/1"), ("Le règlement", "https://exemple.org/regles")]
    assert courir(EV.charger(a["id"]))["valeurs"]["liens"] == [{"nom": "Le site du jeu", "url": "https://www.roblox.com/games/1"},
                                                               {"nom": "Le règlement", "url": "https://exemple.org/regles"}]
    assert "attachments" not in env.infos.cartes[-1][1], "la bannière n'a pas changé : la pièce jointe n'est pas renvoyée"
    #  Un événement aussi : réécrit en place.
    e = brouillon(env, type="evenement", titre="Sortie", quand=T0 + 3 * 3600, lieu="Île")
    r = publier(env, e)
    mid_e = env.infos.messages[-1].id
    n_messages = len(env.infos.messages)
    statut, rep = api(env, "clan/modifier", {"id": e["id"], "version": r["element"]["version"], "texte": "Prévoyez des vivres."})
    assert statut == 200 and len(env.infos.messages) == n_messages and env.infos.cartes[-1][0] == mid_e
    assert any(t == "clan.evenement.modifie" for t, _x, _k in env.journal), "au journal"


def test_M2_le_message_disparu_est_dit_rien_ne_se_republie(env):
    a = brouillon(env, type="annonce", titre="Partie", texte="Texte")
    r = publier(env, a)
    mid = env.infos.messages[-1].id
    env.g.effaces.add(mid)   # supprimé à la main sur Discord
    n_envois = len(env.infos.envois)
    statut, rep = api(env, "clan/modifier", {"id": a["id"], "version": r["element"]["version"], "texte": "Nouveau texte"})
    assert statut == 409 and rep["disparu"] is True and "n'existe plus sur Discord" in rep["erreur"]
    assert "rien n'a été republié" in rep["erreur"] and len(env.infos.envois) == n_envois, "rien ne se republie tout seul"
    e = courir(EV.charger(a["id"]))
    assert "n'existe plus sur Discord" in e["note"] and e["valeurs"]["texte"] == "Texte" and e["messages"] == [mid]
    assert rep["actuelle"]["note"] == e["note"], "la page le lit aussitôt"


def test_M3_la_version_perimee_ne_touche_a_rien(env):
    a = brouillon(env, type="annonce", titre="Titre", texte="Texte")
    r = publier(env, a)
    v = r["element"]["version"]
    assert api(env, "clan/modifier", {"id": a["id"], "version": v, "texte": "Première"})[0] == 200
    n_cartes = len(env.infos.cartes)
    statut, rep = api(env, "clan/modifier", {"id": a["id"], "version": v, "texte": "Écrase ?"})
    assert statut == 409 and rep["conflit"] is True and rep["actuelle"]["valeurs"]["texte"] == "Première"
    assert len(env.infos.cartes) == n_cartes, "aucune réécriture sur Discord"


def test_M4_jamais_un_message_de_plus(env):
    #  Un texte qui ne tiendrait plus dans SON message : refusé, la raison dite, rien d'envoyé ni de réécrit.
    a = brouillon(env, type="annonce", titre="T" * 100, texte="Court.")
    r = publier(env, a)
    n_messages, n_cartes = len(env.infos.messages), len(env.infos.cartes)
    long_ = {"texte": "x" * 3500, "liens": [{"nom": f"{k} " + "n" * 76, "url": f"https://exemple.org/{k}"} for k in range(5)]}
    statut, rep = api(env, "clan/modifier", {"id": a["id"], "version": r["element"]["version"], **long_})
    assert statut == 400 and "Trop long pour un message Discord" in rep["erreur"] and "Raccourcis le texte" in rep["erreur"], rep
    assert (len(env.infos.messages), len(env.infos.cartes)) == (n_messages, n_cartes)
    #  Un listing qui grandit : il demanderait un message de plus — refusé (jamais posté au bout du post).
    env.catalogue["metier"] = {f"m{k}": {"nom": f"Métier numéro {k}"} for k in range(30)}
    for k in range(180):
        uid = 10_000_000_000_000_000 + k
        env.g.membre(uid, env.role)
        env.fiches.append({"membre_id": uid, "metiers": [f"m{k % 30}", f"m{(k * 7) % 30}"], "grade": "matelot", "race": "humain"})
    lst = brouillon(env, type="listing", groupement="metier", champs=["grade", "race", "metiers"], texte="L" * 1400)
    r = publier(env, lst)
    cartes = r["element"]["cartes"]
    assert cartes >= 3
    for k in range(180, 420):
        uid = 10_000_000_000_000_000 + k
        env.g.membre(uid, env.role)
        env.fiches.append({"membre_id": uid, "metiers": [f"m{k % 30}", f"m{(k * 3) % 30}"], "grade": "matelot", "race": "humain"})
    n_messages, n_envois, n_cartes = len(env.infos.messages), len(env.infos.envois), len(env.infos.cartes)
    statut, rep = api(env, "clan/modifier", {"id": lst["id"], "version": r["element"]["version"]})
    assert statut == 400 and "La liste demanderait" in rep["erreur"] and "n'en ajoute jamais" in rep["erreur"], rep
    assert rep["messages"]["publies"] == cartes and rep["messages"]["demandes"] > cartes
    assert (len(env.infos.messages), len(env.infos.envois), len(env.infos.cartes)) == (n_messages, n_envois, n_cartes)
    #  « Seules X cartes sur Y » ne promet plus qu'une modification enverra le reste.
    source = (RACINE / "evenements.py").read_text(encoding="utf-8")
    assert "enverra le reste" not in source and "salon.send(view=vue_" not in source.split("async def modifier(")[1].split("async def apercu_modification(")[0]


@pytest.mark.parametrize("liens, morceau", [
    ([{"nom": "Site", "url": "http://exemple.org"}], "https://"),
    ([{"nom": "Piège", "url": "javascript:alert(1)"}], "https://"),
    ([{"nom": "", "url": "https://exemple.org"}], "a besoin d'un nom"),
    ([{"nom": "x" * 81, "url": "https://exemple.org"}], "80 caractères"),
    ([{"nom": f"L{k}", "url": f"https://exemple.org/{k}"} for k in range(6)], "5 liens au plus"),
    ("https://exemple.org", "liste de liens"),
    ([{"nom": "Site", "url": "https://exemple.org/<script>"}], "https://"),
])
def test_M5_les_liens_sont_verifies(env, liens, morceau):
    a = brouillon(env, type="annonce", titre="Titre", texte="Texte")
    r = publier(env, a)
    statut, rep = api(env, "clan/modifier", {"id": a["id"], "version": r["element"]["version"], "liens": liens})
    assert statut == 400 and morceau in rep["champs"]["liens"], rep


def test_M6_l_apercu_d_une_modification_n_ecrit_rien(env):
    a = brouillon(env, type="annonce", titre="Titre", texte="Texte")
    r = publier(env, a)
    n_cartes = len(env.infos.cartes)
    statut, rep = courir(EV.apercu_modification(env.g, env.tete, {"id": a["id"], "titre": "Nouveau titre", "liens": [
        {"nom": "Le site", "url": "https://exemple.org"}]}))
    assert statut == 200 and rep["modifiable"] is True and rep["erreurs"] == [] and rep["messages"] == {"publies": 1, "demandes": 1}
    md = [ln["md"] for c in rep["cartes"] for b in c["blocs"] if b["type"] == "texte" for ln in b["lignes"]]
    assert "Nouveau titre" in md
    liens = [x for c in rep["cartes"] for b in c["blocs"] if b["type"] == "boutons" for x in b["boutons"] if x["url"]]
    assert liens == [{"label": "Le site", "style": "lien", "icone": "", "desactive": False, "url": "https://exemple.org"}]
    statut, rep = courir(EV.apercu_modification(env.g, env.tete, {"id": a["id"], "texte": "x" * 3500, "titre": "T" * 100,
                                                                  "liens": [{"nom": "n" * 80, "url": f"https://e.org/{k}"} for k in range(5)]}))
    assert statut == 200 and rep["modifiable"] is False and any("Trop long" in x for x in rep["erreurs"])
    e = courir(EV.charger(a["id"]))
    assert e["version"] == r["element"]["version"] and e["valeurs"]["titre"] == "Titre" and len(env.infos.cartes) == n_cartes
    assert courir(EV.apercu_modification(env.g, env.g.membre(5), {"id": a["id"]}))[0] == 403, "la tête seule"


# ═══════════════════════════════════════════════════════════════════════════════
#  S — le vrai site local
# ═══════════════════════════════════════════════════════════════════════════════

def _png64(l, h, couleur=(31, 78, 90)) -> str:
    return base64.b64encode(_image(l, h, "PNG", lambda d, ll, hh: d.rectangle((0, 0, ll, hh), fill=couleur))).decode()


def _annonce(local) -> dict:
    """L'annonce de démonstration publiée (« Le Movie 3 est sorti »), telle que l'administration la lit."""
    st, ev = local.faire(_get(local, "/tableau/espace/api/clan/evenements", local.tete))
    assert st == 200, ev
    return next(x for x in ev["publiees"] if x["titre"].startswith("Le Movie 3"))


async def _get(local, chemin, h):
    r = await local.client.get(chemin, headers=h)
    return r.status, await r.json()


def _infos(local):
    return local.g.fils[int(local.ctx.conf["clan_posts"]["infos"]["id"])]


def test_S1_la_portee_equipage_et_toute_autre_personne_sont_refusees(local):
    import annonces_modifiables as AM
    a = _annonce(local)
    k = local.kolax
    assert local.requete("GET", f"/tableau/espace/api/equipage/publication?id={a['id']}", k)[0] == 403
    for nom, corps in (("equipage/publication", {"id": a["id"], "version": a["version"], "titre": "Piraté"}),
                       ("equipage/publication/apercu", {"id": a["id"], "titre": "Piraté"}),
                       ("clan/modifier", {"id": a["id"], "version": a["version"], "titre": "Piraté"}),
                       ("media", {"nom": "b.png", "type": "image/png", "base64": _png64(1600, 640), "format": "banniere"})):
        st, rep = local.ecrire(nom, corps, k)
        assert st == 403, (nom, st, rep)
    #  Une autre personne que la tête (un membre du clan, appelé directement) : refusée par le module même.
    kolax = local.g.get_member(KOLAX)
    for fn, corps in ((AM.route_modifier, {"id": a["id"], "version": a["version"], "titre": "x"}),
                      (AM.route_apercu, {"id": a["id"]})):
        assert local.faire(fn(local.g, kolax, {}, corps))[0] == 403
    assert local.faire(AM.route_lire(local.g, kolax, {"id": str(a["id"])}, None))[0] == 403
    assert _annonce(local)["version"] == a["version"] and _annonce(local)["titre"] == a["titre"], "rien n'a bougé"


def test_S2_la_tete_modifie_depuis_l_accueil_le_meme_message_partout(local):
    a = _annonce(local)
    post = _infos(local)
    mid = int(a["lien"].rsplit("/", 1)[1])
    n_messages, n_envois = len(post.messages), len(post.envois)
    #  L'éditeur lit la publication (son texte Discord brut, sa bannière, ses liens, sa version, les limites).
    st, lu = local.faire(_get(local, f"/tableau/espace/api/equipage/publication?id={a['id']}", local.tete))
    assert st == 200 and lu["publication"]["version"] == a["version"] and lu["publication"]["modifiable"] is True
    assert lu["publication"]["texte"].startswith("**Le Movie 3 est là.**") and lu["limites"]["texte"] == 3500
    assert lu["banniere"]["consigne"] == bannieres.CONSIGNE
    #  Une nouvelle bannière (recadrée au centre, à la taille exacte), puis l'enregistrement.
    st, ban = local.ecrire("media", {"nom": "movie3.png", "type": "image/png", "base64": _png64(1920, 1080), "format": "banniere"},
                           local.tete)
    assert st == 200 and (ban["largeur"], ban["hauteur"]) == (1600, 640) and ban["banniere"]["recadree"] is True, ban
    corps = {"id": a["id"], "version": a["version"], "titre": "Le Movie 3 est sorti (corrigé)", "texte": "**Corrigé.** Tout est dans Infos.",
             "image": ban["id"], "liens": [{"nom": "Le site du jeu", "url": "https://www.roblox.com/games/1"}]}
    st, rep = local.ecrire("equipage/publication", corps, local.tete)
    assert st == 200, rep
    assert len(post.messages) == n_messages and len(post.envois) == n_envois, "aucun message envoyé : rien n'est republié"
    assert post.cartes[-1][0] == mid and rep["lien"].endswith(f"/{mid}"), "le message Discord a le MÊME identifiant"
    assert [f.filename for f in post.cartes[-1][1]["attachments"]] == [f"clan_{a['id']}.webp"], "la bannière remplacée sur place"
    #  Le site de l'équipage montre aussitôt la nouvelle version (la réponse porte l'accueil relu) ; l'équipage aussi.
    auto = rep["accueil"]["donnees"]["actualites"]["auto"]
    vue = next(x for x in auto if x["id"] == f"auto-pub-{a['id']}")
    assert vue["titre"] == "Le Movie 3 est sorti (corrigé)" and vue["image"] == f"media/{ban['id']}"
    assert vue["liens"] == [{"nom": "Le site du jeu", "url": "https://www.roblox.com/games/1"}]
    st, acc = local.lire("accueil", local.kolax)
    vue_m = next(x for x in acc["donnees"]["actualites"]["auto"] if x["id"] == f"auto-pub-{a['id']}")
    assert vue_m["titre"] == "Le Movie 3 est sorti (corrigé)" and vue_m["texte"].startswith("**Corrigé.**")
    assert local.requete("GET", f"/tableau/espace/media/{ban['id']}", local.kolax)[0] == 200, "la nouvelle bannière, tout de suite"
    #  L'administration voit la même version.
    b = _annonce(local)
    assert b["version"] == rep["element"]["version"] == a["version"] + 1 and b["titre"] == "Le Movie 3 est sorti (corrigé)"
    assert b["valeurs"]["image"] == ban["id"] and b["lien"] == a["lien"]
    #  Au journal : la ligne du site (qui, quoi) et celle du clan.
    lignes = [x[0] for x in local.sql("SELECT texte FROM registre WHERE type='site.equipage.publication' ORDER BY id")]
    assert lignes and "annonce « Le Movie 3 est sorti (corrigé) » modifiée sur Discord (même message, rien de republié)" \
        in lignes[-1] and "(par GoRipe)" in lignes[-1], lignes
    assert local.sql("SELECT 1 FROM registre WHERE type='clan.annonce.modifie'"), "et au journal du clan"
    #  Une version périmée : 409, rien de réécrit.
    n_cartes = len(post.cartes)
    st, rep = local.ecrire("equipage/publication", dict(corps, texte="Écrase ?"), local.tete)
    assert st == 409 and rep["conflit"] is True and len(post.cartes) == n_cartes
    #  Un champ que l'éditeur ne touche pas (le post, la date…) : refusé ici.
    st, rep = local.ecrire("equipage/publication", {"id": a["id"], "version": b["version"], "destination": "1"}, local.tete)
    assert st == 400 and "ne se modifie pas ici" in rep["erreur"]


def test_S3_le_verrou_est_celui_de_l_administration(local):
    """La direction tient la publication dans l'administration (`evenement:<id>`) : le site de l'équipage ne l'écrit pas
    (423) ; libérée, l'écriture passe. Une seule clé pour les deux sites."""
    import aiohttp

    import annonces_modifiables as AM
    import tableau
    a = _annonce(local)
    assert AM.ROUTES_SITE["equipage/publication"][1]["verrou"]({"id": str(a["id"])}) == f"evenement:{a['id']}" \
        == tableau.VERROUS_ROUTES["clan/modifier"]({"id": str(a["id"])})
    hd, _x = local.entrer("/tableau/demo?qui=direction&vers=equipage")

    async def tenir_puis_ecrire():
        try:
            ws = await local.client.ws_connect("/tableau/espace/direct", headers=dict(hd, Origin="http://localhost:8790"))
        except aiohttp.WSServerHandshakeError as ex:
            pytest.fail(f"direct refusé : {ex.status}")
        await ws.send_json({"t": "bonjour", "page": "equipage/annonces"})
        await ws.send_json({"t": "prendre", "o": f"evenement:{a['id']}", "ti": "la publication « Le Movie 3 »"})
        for _ in range(20):
            m = await ws.receive_json(timeout=3)
            if m.get("t") == "pris":
                break
        corps = {"id": a["id"], "version": a["version"], "texte": "Par-dessus ?"}
        r = await local.client.post("/tableau/espace/api/equipage/publication", json=corps, headers=dict(local.tete, **ORIGINE))
        refus = (r.status, await r.json())
        await ws.send_json({"t": "lacher", "o": f"evenement:{a['id']}"})
        await asyncio.sleep(0.3)
        await ws.close()
        r = await local.client.post("/tableau/espace/api/equipage/publication", json=corps, headers=dict(local.tete, **ORIGINE))
        return refus, r.status
    refus, apres = local.faire(tenir_puis_ecrire())
    assert refus[0] == 423 and "Capitaine Direction" in refus[1]["erreur"], refus
    assert apres == 200, "libérée : l'écriture passe"


def test_S4_l_apercu_n_ecrit_rien_et_dit_ce_que_le_site_montrera(local):
    a = _annonce(local)
    post = _infos(local)
    n_cartes = len(post.cartes)
    st, rep = local.ecrire("equipage/publication/apercu", {"id": a["id"], "titre": "Titre essayé", "texte": f"Bonjour <@{FONDATEUR}> **gras**"},
                           local.tete)
    assert st == 200 and rep["modifiable"] is True and rep["messages"] == {"publies": 1, "demandes": 1}
    assert rep["site"]["titre"] == "Titre essayé" and rep["site"]["texte"] == "Bonjour @GoRipe **gras**", rep["site"]
    assert any(ln["md"] == "Titre essayé" for c in rep["cartes"] for b in c["blocs"] for ln in b.get("lignes") or [])
    assert len(post.cartes) == n_cartes and _annonce(local)["version"] == a["version"], "rien n'est écrit, rien ne part"
    assert not local.sql("SELECT 1 FROM registre WHERE type='site.equipage.publication.apercu'"), "une lecture : pas au journal"


def test_S5_la_banniere_par_l_adresse_media(local):
    st, rep = local.ecrire("media", {"nom": "grande.png", "type": "image/png", "base64": _png64(3200, 1280), "format": "banniere"},
                           local.tete)
    assert st == 200 and (rep["largeur"], rep["hauteur"]) == (1600, 640) and rep["banniere"] == {
        "source": [3200, 1280], "coupe": [0, 0, 3200, 1280], "recadree": False}
    assert local.sql("SELECT largeur, hauteur FROM tableau_medias WHERE id=?", (rep["id"],)) == [(1600, 640)]
    st, octets, _h = local.requete("GET", f"/tableau/espace/media/{rep['id']}", local.tete)
    from PIL import Image
    assert st == 200 and Image.open(io.BytesIO(octets)).size == (1600, 640)
    st, rep = local.ecrire("media", {"nom": "petite.png", "type": "image/png", "base64": _png64(1200, 480), "format": "banniere"},
                           local.tete)
    assert st == 400 and rep["erreur"].startswith("Image trop petite : 1200 × 480 px reçue, il faut au moins 1600 × 640 px")
    gif = base64.b64encode(_image(1600, 640, "GIF")).decode()
    st, rep = local.ecrire("media", {"nom": "anim.gif", "type": "image/gif", "base64": gif, "format": "banniere"}, local.tete)
    assert st == 415 and rep["erreur"] == bannieres.REFUS_FORMAT
    assert local.ecrire("media", {"nom": "x.png", "base64": _png64(1600, 640), "format": "affiche"}, local.tete)[0] == 400
    #  Sans « format » : l'envoi d'une image ordinaire ne change pas (portraits, insignes, bloc « image »).
    st, rep = local.ecrire("media", {"nom": "petite.png", "type": "image/png", "base64": _png64(64, 40)}, local.tete)
    assert st == 200 and "banniere" not in rep


def test_S6_le_cablage_et_la_page():
    import tableau
    bot = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert re.search(r"^import annonces_modifiables\b", bot, re.M)
    etape = bot.split('with _Etape("site_equipage"):')[1].split("with _Etape(")[0]
    assert "tableau.monter(annonces_modifiables)" in etape
    local_ = (RACINE / "outils" / "site_local.py").read_text(encoding="utf-8")
    assert "tableau.monter(annonces_modifiables)" in local_
    for page in ("index.html", "equipage.html", "vitrine.html"):
        assert '/tableau/espace/s/banniere.css?v={{V}}' in (RACINE / "site" / page).read_text(encoding="utf-8"), page
    sw = (RACINE / "site" / "sw.js").read_text(encoding="utf-8")
    assert '"banniere.js"' in sw and '"banniere.css"' in sw, "le site de la direction hors ligne"
    acc = (RACINE / "site" / "equipage_accueil.js").read_text(encoding="utf-8")
    assert acc.count("choixBanniere(v, \"image\"") == 2, "le bandeau de l'accueil et l'image d'une actualité"
    assert "editerPublication(a, { proteger, apres: accepter" in acc and "E.peutEditer && modifiable(a)" in acc
    pub = (RACINE / "site" / "equipage_publication.js").read_text(encoding="utf-8")
    assert '"evenement:" + id' in pub and '"equipage/publication"' in pub and '"equipage/publication/apercu"' in pub
    ann = (RACINE / "site" / "annonces.js").read_text(encoding="utf-8")
    assert "export function apercuDiscord(" in ann and "envoyerBanniere()" in ann
    for nom in ("banniere.js", "equipage_publication.js"):
        js = (RACINE / "site" / nom).read_text(encoding="utf-8")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js and ".style." not in js, nom
        assert not re.search(r"[\U0001F300-\U0001FAFF]", js), "aucun émoji"
    #  La route d'écriture est une écriture (journal, cadence, tête) ; l'aperçu est une lecture (rien de tout cela).
    import annonces_modifiables as AM
    defs = {(n, d["methode"]): d for n, x in AM.ROUTES_SITE.items() for d in tableau._definitions(n, x)}
    assert defs[("equipage/publication", "POST")]["ecriture"] is True and defs[("equipage/publication", "GET")]["ecriture"] is False
    assert defs[("equipage/publication/apercu", "POST")]["ecriture"] is False


def test_S7_le_controle_des_imports_lit_le_js_comme_le_navigateur():
    """`outils/controle_imports.py` découpait chaînes et commentaires par expressions régulières : un « // » dans une
    chaîne (« https://… ») passait pour un commentaire et inventait des dizaines de fautes sur la suite du fichier
    (71 sur annonces.js le 26/10). Un seul passage, comme le navigateur : plus aucune fausse faute."""
    import sys
    sys.path.insert(0, str(RACINE / "outils"))
    try:
        import controle_imports as CI
    finally:
        sys.path.remove(str(RACINE / "outils"))
    js = (r"""const RE = /^https:\/\/[^\s"'`]{3}$/; // l'adresse d'un lien""" + "\n"
          'const a = saisie({ placeholder: "https://…", aide: "une adresse en https://." });\n'
          "/* un commentaire avec une apostrophe : l'équipage */\n"
          "const b = `gabarit ${x} // pas un commentaire`;\n"
          "function f(x) { return x / 2 / 3; }\n"
          "const c = inconnue(1);\n")
    propre = CI.sans_chaines(js)
    assert "https" not in propre and "équipage" not in propre and "gabarit" not in propre
    assert propre.count("\n") == js.count("\n"), "les numéros de ligne restent justes"
    assert "saisie(" in propre and "inconnue(" in propre and "x / 2 / 3" in propre, "le code reste : une division n'est pas une expression régulière"
    assert "class Emprise" in CI.sans_chaines("class Emprise {\n  async relire(x) {\n  }\n}\n")
    assert {"Emprise", "relire"} <= CI.declares(CI.sans_chaines("class Emprise {\n  async relire(x) {\n  }\n}\n"))


def test_S9_retirer_une_ancienne_annonce_depuis_le_site_de_l_equipage(local):
    """28/10/2026, le fondateur : « on peut aussi supprimer les anciens posts annonces » — la tête seule ; les messages
    Discord partent, l'annonce quitte l'accueil, rien ne se republie."""
    a = _annonce(local)
    st, rep = local.ecrire("equipage/publication/retirer", {"id": a["id"]}, local.kolax)
    assert st == 403, "l'équipage ne retire rien"
    st, rep = local.ecrire("equipage/publication/retirer", {"id": a["id"]}, local.tete)
    assert st == 200, rep
    assert courir(EV.charger(a["id"]))["statut"] == "retire"
    assert "Le Movie 3" not in json.dumps(rep.get("accueil") or {}, ensure_ascii=False), "elle quitte l'accueil"
    st, rep = local.ecrire("equipage/publication/retirer", {"id": a["id"]}, local.tete)
    assert st == 200 and rep.get("deja"), "deux fois : sans effet"
