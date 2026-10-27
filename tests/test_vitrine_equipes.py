"""La vitrine PUBLIQUE de l'équipage (`/equipage`) et les ÉQUIPES du clan (27/10/2026).

Sur le VRAI site local (`outils/site_local.py`), comme `test_site_equipage.py` :
V1 la page : sans session, en-têtes (noindex, CSP stricte), balises Open Graph remplies, aucun cookie.
V2 les données : des champs publics SEULEMENT — aucun nom ni avatar Discord, aucun identifiant, aucune note, aucune
   actualité automatique, aucun bloc privé ; les images par jetons opaques.
V3 la direction retire une affiche de la vitrine : elle disparaît aussitôt (et son portrait) ; puis revient.
V4 les blocs publics : au départ le bandeau et le code ; un bloc rendu public paraît, masqué il disparaît ; la migration.
V5 les images : seulement celles que les données citent.
V6 refus par défaut : aucune écriture, aucune autre adresse ; une session ne change rien à ce que la vitrine montre.
V7 la cadence par adresse IP (la première de X-Forwarded-For) ; V8 le cache (une écriture le renouvelle).
V9 la bannière de l'aperçu (PNG 1200 × 630) ; V10 les textes (registre) ; V11 le bouton « Copier le lien ».
E1 les équipes : écrites par la tête seule (portée « equipage » : 403 partout) ; E2 une équipe par membre, un chef
   unique, refus et conflits (409), verrous (423), journal ; E3 ce que l'équipage lit (hiérarchie, « Mon équipe ») ;
E4 la hiérarchie existante (grades du catalogue, puis rang de prime) ; E5 les équipes sur la vitrine ; E6 les badges du
   sélecteur de chef (fournisseur branchable) ; E7 RGPD.
"""
from __future__ import annotations

import asyncio
import io
import json
import re

import pytest

import test_site_equipage as _socle
from test_site_equipage import ANNE, BARBE, ISHMAEL, KOLAX, MIRA, ORIGINE, RACINE, TORTUGA

local = _socle.local   # le même site local que test_site_equipage.py (un à part pour ce fichier : portée « module »)

MIEN_JETON = re.compile(r"^/equipage/image/[A-Za-z0-9_-]{22}$")


def _vitrine(local, chemin="/equipage/donnees", h=None):
    st, corps, entetes = local.requete("GET", chemin, h)
    return st, corps, entetes


def _donnees(local, h=None) -> dict:
    st, corps, _e = _vitrine(local, h=h)
    assert st == 200, corps
    return json.loads(corps)


def _chaines(x):
    """Toutes les chaînes d'un JSON (valeurs ET clés)."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v)
    elif isinstance(x, str):
        yield x


@pytest.fixture(autouse=True)
def _cadence_libre():
    """Chaque test part d'une cadence et d'un cache vides (la cadence a son propre test)."""
    import site_vitrine
    site_vitrine._passages.clear()
    site_vitrine.oublier()
    yield
    site_vitrine._passages.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  V — la vitrine publique
# ═══════════════════════════════════════════════════════════════════════════════

def test_V1_la_page_publique_ses_entetes_et_son_apercu(local):
    st, corps, e = _vitrine(local, "/equipage")
    html = corps.decode("utf-8")
    assert st == 200 and e["Content-Type"].startswith("text/html")
    assert e["X-Robots-Tag"] == "noindex, nofollow" and "Set-Cookie" not in e
    csp = e["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe" not in csp and "img-src 'self' data:;" in csp
    assert "discord" not in csp, "aucune image de Discord sur la vitrine"
    og = dict(re.findall(r'<meta property="og:([a-z:_]+)" content="([^"]*)"', html))
    assert og["title"] == "L&#x27;Équipage · Clan Rell Seas" and og["url"] == "http://localhost:8790/equipage"
    assert re.fullmatch(r"http://localhost:8790/equipage/banniere\.png\?v=[0-9a-f]{16}", og["image"]), og["image"]
    assert og["image:width"] == "1200" and og["image:height"] == "630"
    assert re.search(r'<meta name="twitter:card" content="summary_large_image">', html)
    assert "{{" not in html, "toutes les cases remplies"
    #  `/equipage/` : une seule adresse à partager.
    st, _c, e = _vitrine(local, "/equipage/")
    assert st == 301 and e["Location"] == "/equipage"


def test_V2_seulement_des_champs_publics(local):
    import site_equipage
    d = _donnees(local)
    assert set(d) == {"serveur", "clan", "textes", "libelles", "affiches", "catalogue", "accueil", "equipes", "maintenant",
                      "version"}
    assert d["affiches"], "le mur n'est pas vide"
    for a in d["affiches"]:
        assert set(a) == {"id", "roblox", "surnom", "prime", "niveau", "grade", "statut", "attributs"}, a
        assert set(a["roblox"]) == {"nom", "avatar"} and (not a["roblox"]["avatar"] or MIEN_JETON.match(a["roblox"]["avatar"]))
        assert re.fullmatch(r"[A-Za-z0-9_-]{12}", a["id"]), "un jeton, jamais l'identifiant de l'affiche"
    tout = "\n".join(_chaines(d))
    lignes = local.faire(site_equipage._affiches_actives(local.g))
    for a in lignes:   # aucun identifiant réel : affiche, membre, Roblox
        assert a["id"] not in tout and (not a["membre_id"] or str(a["membre_id"]) not in tout)
        assert not a["roblox_id"] or f"avatar/{a['roblox_id']}" not in tout
    for interdit in ("discordapp", "cdn.discord", "notes", "cree_par", "maj_par", "GoRipe", "Capitaine Direction",
                     "Anne Bonny", "Ishmael", "Avis placardé", "Nouvelle affiche", "rejoint l'équipage", "membre_id",
                     "Grande chasse au trésor", "Prochaines sorties", "Équipiers à l'honneur", "L'équipage en chiffres"):
        assert interdit not in tout, interdit
    #  Les images : des jetons opaques, ou les icônes publiques du site.
    for s in _chaines(d):
        if s.startswith("/equipage/image/"):
            assert MIEN_JETON.match(s), s
        assert not s.startswith(("media/", "/tableau/espace/media")), s
    #  Les blocs : au départ, le bandeau et le code de l'équipage (b1, b2) — rien d'autre.
    assert [(b["id"], b["type"]) for b in d["accueil"]["blocs"]] == [("b1", "bandeau"), ("b2", "texte")]
    assert d["accueil"]["donnees"] == {}


def test_V3_la_direction_retire_une_affiche_de_la_vitrine(local):
    import site_equipage
    av = _donnees(local)
    kolax = next(a for a in local.faire(site_equipage._affiches_actives(local.g)) if a["membre_id"] == KOLAX)
    jeton_kolax = next(a for a in av["affiches"] if a["roblox"]["nom"] == kolax["roblox_nom"])
    portrait = jeton_kolax["roblox"]["avatar"]
    #  L'équipage ne peut pas : 403 (une écriture), et la vitrine n'a bougé en rien.
    assert local.ecrire("equipage/vitrine/affiche", {"id": kolax["id"], "visible": False}, local.kolax)[0] == 403
    st, rep = local.ecrire("equipage/vitrine/affiche", {"id": kolax["id"], "visible": False}, local.tete)
    assert st == 200 and rep["masquees"] == [kolax["id"]], rep
    ap = _donnees(local)
    assert len(ap["affiches"]) == len(av["affiches"]) - 1 and jeton_kolax["id"] not in "\n".join(_chaines(ap))
    if portrait:
        assert _vitrine(local, portrait)[0] == 404, "son portrait non plus"
    #  L'équipage la voit toujours ; la direction voit qu'elle est retirée.
    assert any(a["id"] == kolax["id"] for a in local.lire("equipage", local.kolax)[1]["affiches"])
    assert "vitrine" not in local.lire("equipage", local.kolax)[1]
    assert local.lire("equipage", local.tete)[1]["vitrine"]["masquees"] == [kolax["id"]]
    journal = local.sql("SELECT texte FROM registre WHERE texte LIKE '%vitrine publique%' ORDER BY rowid DESC LIMIT 1")
    assert journal and "retirée de la vitrine publique" in journal[0][0]
    #  Remise : elle revient.
    assert local.ecrire("equipage/vitrine/affiche", {"id": kolax["id"], "visible": True}, local.tete)[0] == 200
    assert len(_donnees(local)["affiches"]) == len(av["affiches"])
    #  Saisies refusées.
    assert local.ecrire("equipage/vitrine/affiche", {"id": "../x", "visible": True}, local.tete)[0] == 400
    assert local.ecrire("equipage/vitrine/affiche", {"id": "nexistepas", "visible": True}, local.tete)[0] == 404


def test_V4_les_blocs_publics_et_la_migration(local, tmp_path):
    import aiosqlite
    import site_equipage
    acc = local.lire("accueil", local.tete)[1]
    assert {b["type"]: b["public"] for b in acc["blocs"]} == {"bandeau": True, "texte": True, "actualites": False,
                                                              "evenements": False, "honneur": False, "analyses": False}
    honneur = next(b for b in acc["blocs"] if b["type"] == "honneur")
    assert local.ecrire("equipage/bloc/public", {"id": honneur["id"], "public": True}, local.kolax)[0] == 403
    st, rep = local.ecrire("equipage/bloc/public", {"id": honneur["id"], "public": True}, local.tete)
    assert st == 200
    d = _donnees(local)
    b = next(x for x in d["accueil"]["blocs"] if x["type"] == "honneur")
    ids = {a["id"] for a in d["affiches"]}
    assert d["accueil"]["donnees"]["honneur"][b["id"]] and set(d["accueil"]["donnees"]["honneur"][b["id"]]) <= ids
    #  Public mais masqué : il ne paraît pas.
    assert local.ecrire("equipage/bloc/visible", {"id": honneur["id"], "visible": False}, local.tete)[0] == 200
    assert "honneur" not in {x["type"] for x in _donnees(local)["accueil"]["blocs"]}
    assert local.ecrire("equipage/bloc/visible", {"id": honneur["id"], "visible": True}, local.tete)[0] == 200
    #  Les analyses publiques : seulement les parties du bloc, les noms Roblox (jamais Discord).
    analyses = next(x for x in acc["blocs"] if x["type"] == "analyses")
    st, _r = local.ecrire("equipage/bloc", {"id": analyses["id"], "version": analyses["version"],
                                            "contenu": {"titre": "En chiffres", "parties": ["metiers", "primes"]}}, local.tete)
    assert st == 200
    assert local.ecrire("equipage/bloc/public", {"id": analyses["id"], "public": True}, local.tete)[0] == 200
    an = _donnees(local)["accueil"]["donnees"]["analyses"]
    assert set(an) == {"metiers", "primes"} and all(x["affiche"] in ids for x in an["primes"]["top"])
    for cle in (honneur["id"], analyses["id"]):
        assert local.ecrire("equipage/bloc/public", {"id": cle, "public": False}, local.tete)[0] == 200
    assert [x["type"] for x in _donnees(local)["accueil"]["blocs"]] == ["bandeau", "texte"]

    #  Une base d'avant (sans la colonne) : le bandeau et le PREMIER texte deviennent publics, le reste privé.
    async def migrer():
        chemin = tmp_path / "ancienne.db"
        async with aiosqlite.connect(chemin) as db:
            await db.execute("CREATE TABLE equipage_blocs (guild_id INTEGER NOT NULL, id TEXT NOT NULL, type TEXT NOT NULL,"
                             " ordre INTEGER NOT NULL DEFAULT 0, visible INTEGER NOT NULL DEFAULT 1, contenu TEXT NOT NULL "
                             "DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1, cree_le INTEGER NOT NULL, cree_par INTEGER NOT "
                             "NULL DEFAULT 0, maj_le INTEGER NOT NULL, maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY "
                             "(guild_id, id))")
            for n, (ident, type_) in enumerate((("a", "bandeau"), ("b", "texte"), ("c", "texte"), ("d", "honneur")), 1):
                await db.execute("INSERT INTO equipage_blocs (guild_id, id, type, ordre, cree_le, maj_le) VALUES (7,?,?,?,1,1)",
                                 (ident, type_, n))
            await db.commit()

        def ouvrir():
            return aiosqlite.connect(chemin)
        ancien = site_equipage._get_db
        site_equipage._get_db = ouvrir
        try:
            await site_equipage.init_db()
            await site_equipage.init_db()   # deux fois : rien ne bouge
        finally:
            site_equipage._get_db = ancien
        async with aiosqlite.connect(chemin) as db:
            async with db.execute("SELECT id, public FROM equipage_blocs ORDER BY ordre") as cur:
                return await cur.fetchall()
    assert local.faire(migrer()) == [("a", 1), ("b", 1), ("c", 0), ("d", 0)]


def test_V5_les_images_seulement_celles_citees(local):
    d = _donnees(local)
    jetons = [s for s in _chaines(d) if s.startswith("/equipage/image/")]
    assert jetons, "des portraits sur la vitrine"
    st, corps, e = _vitrine(local, jetons[0])
    assert st == 200 and e["Content-Type"].startswith("image/") and e["X-Robots-Tag"] == "noindex, nofollow"
    assert e["Content-Security-Policy"] == "default-src 'none'; sandbox" and "Set-Cookie" not in e
    for faux in ("/equipage/image/" + "A" * 22, "/equipage/image/court", "/equipage/image/..%2F..%2Fsecret",
                 "/equipage/image/" + "a" * 23):
        assert _vitrine(local, faux)[0] == 404, faux
    #  Une image envoyée sur le site mais posée dans un bloc PRIVÉ : jamais servie à la vitrine.
    media = local.png("privee.png")
    st, _r = local.ecrire("equipage/bloc", {"type": "image", "contenu": {"image": media, "legende": "Privée"}}, local.tete)
    assert st == 200
    import site_vitrine
    assert media not in json.dumps(site_vitrine._cache[local.g.id]["images"] if local.g.id in site_vitrine._cache else {})
    d = _donnees(local)
    assert "Privée" not in "\n".join(_chaines(d))
    import site_equipage
    assert not any(media in str(v) for v in site_vitrine._cache[local.g.id]["images"].values())
    bloc = next(b for b in local.faire(site_equipage._blocs(local.g.id)) if b["type"] == "image")
    assert local.ecrire("equipage/bloc/supprimer", {"id": bloc["id"]}, local.tete)[0] == 200


def test_V6_refus_par_defaut_et_les_sessions_ne_changent_rien(local):
    #  Aucune écriture, aucune autre adresse sous /equipage.
    for methode in ("POST", "PUT", "DELETE", "PATCH"):
        for chemin in ("/equipage", "/equipage/donnees", "/equipage/banniere.png", "/equipage/image/" + "A" * 22):
            assert local.requete(methode, chemin)[0] == 405, (methode, chemin)
    for chemin in ("/equipage/api/equipage", "/equipage/admin", "/equipage/donnees/x", "/equipage/../tableau/espace/donnees"):
        assert local.requete("GET", chemin)[0] in (404, 403), chemin
    #  Sans session : aucune donnée du site (la vitrine est la seule porte publique).
    for chemin in ("/tableau/espace/donnees", "/tableau/espace/api/equipage/equipes", "/tableau/espace/membre?id=1000",
                   "/tableau/equipage/api/equipage", "/tableau/equipage/api/accueil", "/tableau/espace/api/rell/affiches",
                   "/tableau/espace/media/" + "A" * 16, "/tableau/espace/recherche?q=a", "/tableau/espace/export?quoi=journal"):
        st, corps, _e = local.requete("GET", chemin)
        assert st in (401, 403), (chemin, st)
    #  Une session (de l'équipage, de la direction) ne change RIEN à la vitrine : mêmes données, aucun cookie.
    nue = _donnees(local)
    for h in (local.kolax, local.tete):
        st, corps, e = _vitrine(local, h=h)
        assert st == 200 and json.loads(corps) == nue and "Set-Cookie" not in e
    st, corps, e = _vitrine(local, "/equipage", h=local.tete)
    assert st == 200 and "Set-Cookie" not in e and "Copier" not in corps.decode()[:0]


def test_V7_la_cadence_par_adresse_ip(local, monkeypatch):
    import site_vitrine
    monkeypatch.setitem(site_vitrine.LIMITES, "donnees", 3)
    ip1 = {"X-Forwarded-For": "203.0.113.5, 10.1.1.1"}
    assert [_vitrine(local, h=ip1)[0] for _ in range(3)] == [200, 200, 200]
    st, _c, e = _vitrine(local, h=ip1)
    assert st == 429 and e["Retry-After"] == "60" and e["X-Robots-Tag"] == "noindex, nofollow"
    #  La PREMIÈRE adresse compte (la dernière est celle du relais, partagée) : changer la dernière n'aide pas…
    assert _vitrine(local, h={"X-Forwarded-For": "203.0.113.5, 10.9.9.9"})[0] == 429
    #  … une autre personne passe.
    assert _vitrine(local, h={"X-Forwarded-For": "198.51.100.7, 10.1.1.1"})[0] == 200


def test_V8_le_cache_et_son_renouvellement(local, monkeypatch):
    import site_vitrine
    appels = []
    vrai = site_vitrine._construire

    async def compte(g):
        appels.append(1)
        return await vrai(g)
    monkeypatch.setattr(site_vitrine, "_construire", compte)
    for _ in range(4):
        assert _vitrine(local)[0] == 200
    assert _vitrine(local, "/equipage")[0] == 200
    assert len(appels) == 1, "une réponse gardée côté serveur"
    st, _c, e = _vitrine(local)
    assert local.requete("GET", "/equipage/donnees", {"If-None-Match": e["ETag"]})[0] == 304
    #  Une écriture de la direction renouvelle aussitôt.
    acc = local.lire("accueil", local.tete)[1]
    texte = next(b for b in acc["blocs"] if b["type"] == "texte")
    st, _r = local.ecrire("equipage/bloc", {"id": texte["id"], "version": texte["version"],
                                            "contenu": dict(texte["contenu"], texte="Le butin se partage, toujours.")}, local.tete)
    assert st == 200
    assert "Le butin se partage, toujours." in "\n".join(_chaines(_donnees(local))) and len(appels) == 2


def test_V9_la_banniere_de_l_apercu(local):
    from PIL import Image
    st, corps, e = _vitrine(local, "/equipage/banniere.png")
    assert st == 200 and e["Content-Type"] == "image/png" and e["X-Robots-Tag"] == "noindex, nofollow"
    assert e["Cross-Origin-Resource-Policy"] == "cross-origin" and "Set-Cookie" not in e
    im = Image.open(io.BytesIO(corps))
    assert im.size == (1200, 630) and im.format == "PNG"
    assert local.requete("GET", "/equipage/banniere.png", {"If-None-Match": e["ETag"]})[0] == 304
    #  Ce qu'elle dessine : des données publiques seulement (le nom du site, le clan, les noms Roblox des primes).
    import site_vitrine
    b = site_vitrine._cache[local.g.id]["apercu"]["banniere"]
    assert set(b) == {"titre", "haut", "ligne", "phrase", "mention", "affiches"}
    for a in b["affiches"]:
        assert set(a) == {"nom", "surnom", "prime", "grade", "portrait"}
        assert not a["portrait"] or a["portrait"].endswith((".webp", ".png"))


def test_V10_les_textes_de_la_vitrine_au_registre(local):
    import site_equipage
    import site_vitrine
    import textes
    for cle in ("equipage_site.vitrine.og.titre", "equipage_site.vitrine.og.description", "equipage_site.vitrine.banniere",
                "equipage_site.vitrine.phrase", "site.equipage.lien", "site.equipage.lien.copie", "guide.vitrine.bouton",
                "site.equipes.chef", "site.equipes.mon"):
        assert textes.declare(cle), cle
    def ecrire_texte(cle, valeur):
        st, rep = local.ecrire("texte", {"cle": cle, "valeur": valeur, "version": textes.item(local.g, cle)["version"]},
                               local.tete)
        assert st == 200, rep
    ecrire_texte("equipage_site.vitrine.og.titre", "{titre} · l'équipage de {clan}")
    ecrire_texte("site.equipage.lien", "Partager l'équipage")
    try:
        site_vitrine.oublier()
        html = _vitrine(local, "/equipage")[1].decode()
        assert '<meta property="og:title" content="L&#x27;Équipage · l&#x27;équipage de Clan Rell Seas">' in html
        assert _donnees(local)["libelles"]["site.equipage.lien"] == "Partager l'équipage"
        assert local.lire("depart", local.kolax)[1]["libelles"]["site.equipage.lien"] == "Partager l'équipage"
    finally:
        for cle in ("equipage_site.vitrine.og.titre", "site.equipage.lien"):
            assert local.ecrire("texte/defaut", {"cle": cle}, local.tete)[0] == 200
    assert site_equipage.libelles_page(local.g) == {}


def test_V11_le_bouton_copier_le_lien_et_les_pages(local):
    js = {f: (RACINE / "site" / f).read_text(encoding="utf-8") for f in (
        "vitrine.js", "lien_equipage.js", "equipage_mur.js", "equipage_equipes.js", "equipes_admin.js")}
    for nom, src in js.items():
        assert "innerHTML" not in src and "eval(" not in src and ".style." not in src, nom
    assert 'location.origin + ADRESSE_VITRINE' in js["lien_equipage.js"] and 'ADRESSE_VITRINE = "/equipage"' in js["lien_equipage.js"]
    assert "navigator.clipboard.writeText" in js["lien_equipage.js"] and 'execCommand("copy")' in js["lien_equipage.js"]
    app = (RACINE / "site" / "app.js").read_text(encoding="utf-8")
    assert "boutonLienEquipage({ iconeSeule: true })" in app, "en haut à droite du site de la direction"
    assert "boutonLienEquipage()" in (RACINE / "site" / "equipage.js").read_text(encoding="utf-8")
    html = (RACINE / "site" / "vitrine.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "style=" not in html and "<style" not in html
    #  Les images de la vitrine passent `srcSure` (dom.js) : ses jetons, rien d'autre de nouveau.
    assert r"/^\/equipage\/image\/[A-Za-z0-9_-]{22}$/" in (RACINE / "site" / "dom.js").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  E — les équipes du clan
# ═══════════════════════════════════════════════════════════════════════════════

def _equipes(local) -> dict:
    st, corps, _e = local.requete("GET", "/tableau/espace/api/equipage/equipes", local.tete)
    assert st == 200, corps
    return json.loads(corps)


def test_E1_les_equipes_s_ecrivent_par_la_tete_seule(local):
    base = _equipes(local)
    assert [e["nom"] for e in base["equipes"]] == ["Les Cuistots du Requin", "La Garde du Navire"]
    une = base["equipes"][0]
    corps = {"id": une["id"], "version": une["version"], "nom": "Pris", "type": None, "chef": str(KOLAX), "membres": []}
    for nom, c in (("equipage/equipe", corps), ("equipage/equipe", {"nom": "Neuve"}), ("equipage/equipe/supprimer", {"id": une["id"]}),
                   ("equipage/equipe/deplacer", {"id": une["id"], "sens": "bas"})):
        assert local.ecrire(nom, c, local.kolax)[0] == 403, nom
    assert local.requete("GET", "/tableau/espace/api/equipage/equipes", local.kolax)[0] == 403
    assert _equipes(local) == base, "rien n'a bougé"


def test_E2_une_equipe_par_membre_un_chef_unique_conflits_et_verrous(local):
    base = _equipes(local)
    cuistots, garde = base["equipes"]
    #  Créer : Mira (membre des Cuistots) passe dans la nouvelle équipe ; le chef n'est pas listé parmi les membres.
    st, rep = local.ecrire("equipage/equipe", {"nom": "Les Corsaires", "type": {"genre": "libre", "texte": "Course"},
                                               "chef": str(TORTUGA), "membres": [str(MIRA), str(TORTUGA)]}, local.tete)
    assert st == 200, rep
    eq = {e["nom"]: e for e in rep["equipes"]}
    assert eq["Les Corsaires"]["chef"]["id"] == str(TORTUGA) and [m["id"] for m in eq["Les Corsaires"]["membres"]] == [str(MIRA)]
    assert str(MIRA) not in [m["id"] for m in eq["Les Cuistots du Requin"]["membres"]], "une seule équipe à la fois"
    assert str(TORTUGA) not in [m["id"] for m in eq["La Garde du Navire"]["membres"]], "le chef quitte son ancienne équipe"
    assert eq["Les Cuistots du Requin"]["version"] > cuistots["version"], "l'équipe qui perd un membre change de version"
    assert local.sql("SELECT COUNT(*) FROM equipes_membres WHERE membre_id=?", (MIRA,))[0][0] == 1
    journal = local.sql("SELECT texte FROM registre WHERE texte LIKE 'Équipes : %' ORDER BY rowid DESC LIMIT 1")[0][0]
    assert journal.startswith("Équipes : « Les Corsaires » créée (chef : Tortuga, 1 membre)"), journal
    corsaires = eq["Les Corsaires"]
    #  Refus : un chef déjà chef ailleurs, un membre qui est chef ailleurs, un nom pris, hors du clan, un métier inconnu.
    refus = [({"nom": "X1", "chef": str(KOLAX)}, "chef"), ({"nom": "X2", "membres": [str(ISHMAEL)]}, "membres"),
             ({"nom": "les corsaires"}, "nom"), ({"nom": "X3", "chef": str(BARBE)}, "chef"),
             ({"nom": "X4", "membres": [str(BARBE)]}, "membres"), ({"nom": "X5", "type": {"genre": "metier", "cle": "astronaute"}}, "type"),
             ({"nom": "X6", "type": {"genre": "libre", "texte": ""}}, "type"), ({"nom": "", "chef": None}, "nom"),
             ({"nom": "X7", "membres": ["abc"]}, "membres"), ({"nom": "X8", "type": "cuisine"}, "type")]
    for corps, champ in refus:
        st, r = local.ecrire("equipage/equipe", corps, local.tete)
        assert st == 400 and r.get("champ") == champ, (corps, st, r)
    #  Conflit : une version dépassée → 409, avec la version enregistrée.
    st, r = local.ecrire("equipage/equipe", {"id": corsaires["id"], "version": corsaires["version"] - 1, "nom": "Les Corsaires",
                                             "chef": str(TORTUGA), "membres": []}, local.tete)
    assert st == 409 and r["actuelle"]["version"] == corsaires["version"]
    #  La clé du verrou de chaque écriture (le direct) : `equipe:<id>` ; une création ne verrouille rien (E2b : de bout en bout).
    import site_equipage
    objet = "equipe:" + corsaires["id"]
    assert site_equipage.ROUTES_SITE["equipage/equipe"]["verrou"]({"id": corsaires["id"]}) == objet
    assert site_equipage.ROUTES_SITE["equipage/equipe"]["verrou"]({"nom": "neuve"}) is None
    assert site_equipage.ROUTES_SITE["equipage/equipe/supprimer"]["verrou"]({"id": corsaires["id"]}) == objet
    #  Déplacer, puis supprimer : ses membres deviennent « sans équipe ».
    st, r = local.ecrire("equipage/equipe/deplacer", {"id": corsaires["id"], "sens": "haut"}, local.tete)
    assert st == 200 and [e["nom"] for e in r["equipes"]][1] == "Les Corsaires"
    st, r = local.ecrire("equipage/equipe/supprimer", {"id": corsaires["id"]}, local.tete)
    assert st == 200 and "Les Corsaires" not in [e["nom"] for e in r["equipes"]]
    assert local.sql("SELECT COUNT(*) FROM equipes_membres WHERE membre_id=?", (MIRA,))[0][0] == 0
    #  Remettre la base de démonstration (les autres tests la lisent).
    frais = {e["nom"]: e for e in _equipes(local)["equipes"]}
    c = frais["Les Cuistots du Requin"]
    st, r = local.ecrire("equipage/equipe", {"id": c["id"], "version": c["version"], "nom": c["nom"],
                                             "type": c["saisie_type"], "chef": str(KOLAX), "membres": [str(MIRA), str(ANNE)]},
                         local.tete)
    assert st == 200, r
    g = frais["La Garde du Navire"]
    st, r = local.ecrire("equipage/equipe", {"id": g["id"], "version": g["version"], "nom": g["nom"], "type": g["saisie_type"],
                                             "chef": str(ISHMAEL), "membres": [str(TORTUGA), "1009"]}, local.tete)
    assert st == 200, r


def test_E2b_le_verrou_d_une_equipe_de_bout_en_bout(local):
    """La direction tient l'éditeur d'une équipe (le direct) : le fondateur ne peut pas l'écrire (423), puis si."""
    import aiohttp
    e = _equipes(local)["equipes"][0]
    hd, _a = local.entrer("/tableau/demo?qui=direction")
    origine = {"Origin": "http://localhost:8790"}

    async def tenir_puis_ecrire():
        ws = await local.client.ws_connect("/tableau/espace/direct", headers=dict(hd, **origine))
        await ws.send_json({"t": "bonjour", "page": "equipage/membres"})
        await ws.send_json({"t": "prendre", "o": "equipe:" + e["id"], "ti": "l'équipe « " + e["nom"] + " »"})
        for _ in range(20):
            m = await ws.receive_json(timeout=3)
            if m.get("t") == "pris":
                break
        corps = {"id": e["id"], "version": e["version"], "nom": e["nom"], "type": e["saisie_type"],
                 "chef": e["chef"]["id"], "membres": [m["id"] for m in e["membres"]]}
        r = await local.client.post("/tableau/espace/api/equipage/equipe", json=corps, headers=dict(local.tete, **ORIGINE))
        refuse = (r.status, await r.json())
        await ws.send_json({"t": "lacher", "o": "equipe:" + e["id"]})
        await asyncio.sleep(0.3)
        await ws.close()
        r = await local.client.post("/tableau/espace/api/equipage/equipe", json=corps, headers=dict(local.tete, **ORIGINE))
        return refuse, r.status
    del aiohttp
    refuse, apres = local.faire(tenir_puis_ecrire())
    assert refuse[0] == 423 and "Capitaine Direction" in refuse[1]["erreur"], refuse
    assert apres == 200


def test_E3_ce_que_l_equipage_lit_hierarchie_et_mon_equipe(local):
    st, d = local.lire("equipage", local.kolax)
    assert st == 200
    eq = {e["nom"]: e for e in d["equipes"]}
    cuistots = eq["Les Cuistots du Requin"]
    assert cuistots["chef"]["nom"] == "Kolax" and cuistots["chef"]["affiche"], "le chef à part, avec son affiche"
    assert cuistots["type"]["genre"] == "metier" and cuistots["type"]["nom"] == "Cuisine"
    #  La hiérarchie : ceux qui ont une affiche d'abord (grade, puis prime), puis les autres.
    noms = [m["nom"] for m in cuistots["membres"]]
    assert noms == ["Mira", "Anne Bonny"], noms
    assert d["mon_equipe"] == {"id": cuistots["id"], "role": "chef"}
    assert local.lire("equipage", local.entrer("/tableau/demo?qui=equipage&id=1001")[0])[1]["mon_equipe"] == \
        {"id": cuistots["id"], "role": "membre"}
    sans = local.entrer("/tableau/demo?qui=equipage&id=1004")[0]
    assert local.lire("equipage", sans)[1]["mon_equipe"] is None
    assert any(p["nom"] for p in d["sans_equipe"]) and all(set(p) == {"nom", "avatar", "affiche", "h"} for p in d["sans_equipe"])
    #  Aucun identifiant de membre dans ce que lit l'équipage.
    for e in d["equipes"]:
        for p in [e["chef"], *e["membres"]]:
            if p:
                assert set(p) == {"nom", "avatar", "affiche", "h"}, p


def test_E4_la_hierarchie_existante():
    import site_equipage
    types = {"grade": {"cle": "grade", "nom": "Grades", "champ": "grade", "ordre": 1}}
    elements = {("grade", "capitaine"): {"cle": "capitaine", "nom": "Capitaine", "ordre": 1},
                ("grade", "second"): {"cle": "second", "nom": "Second", "ordre": 2},
                ("grade", "mousse"): {"cle": "mousse", "nom": "Mousse", "ordre": 9}}
    rangs = site_equipage.rangs_grades(types, elements)
    assert rangs == {"capitaine": 0, "second": 1, "mousse": 2}

    def a(grade, prime):
        return {"grade": grade, "prime": prime}
    gens = [("Zed", a("mousse", 9_000_000)), ("Bob", a("capitaine", 10)), ("Ann", a("second", 50)), ("Cid", None),
            ("Dan", a("inconnu", 70)), ("Eve", a("", 900)), ("Al", a("second", 50))]
    ordre = [n for n, x in sorted(gens, key=lambda p: site_equipage.cle_hierarchie(p[1], p[0], rangs))]
    assert ordre == ["Bob", "Al", "Ann", "Zed", "Eve", "Dan", "Cid"], ordre
    #  Sans type « grade » au catalogue : la prime (le rang de prime existant), puis le nom.
    assert site_equipage.rangs_grades({}, {}) == {}
    ordre = [n for n, x in sorted(gens, key=lambda p: site_equipage.cle_hierarchie(p[1], p[0], {}))]
    assert ordre == ["Zed", "Eve", "Dan", "Al", "Ann", "Bob", "Cid"], ordre


def test_E5_les_equipes_sur_la_vitrine(local):
    d = _donnees(local)
    ids = {a["id"] for a in d["affiches"]}
    assert [e["nom"] for e in d["equipes"]] == ["Les Cuistots du Requin"], "la Garde n'a aucune affiche montrée"
    e = d["equipes"][0]
    assert set(e) == {"id", "nom", "type", "chef", "membres"} and e["id"] == "q1"
    assert e["chef"]["affiche"] in ids and all(m["affiche"] in ids for m in e["membres"])
    assert set(e["type"]) == {"genre", "nom", "icone"}
    tout = "\n".join(_chaines(d["equipes"]))
    assert "Anne Bonny" not in tout and "Kolax" not in tout.replace("Kolax_RS", ""), "seulement par les affiches"
    #  Le chef retiré de la vitrine : l'équipe y reste (ses membres), sans chef montré.
    import site_equipage
    kolax = next(a for a in local.faire(site_equipage._affiches_actives(local.g)) if a["membre_id"] == KOLAX)
    assert local.ecrire("equipage/vitrine/affiche", {"id": kolax["id"], "visible": False}, local.tete)[0] == 200
    try:
        e = _donnees(local)["equipes"][0]
        assert e["chef"] is None and e["membres"]
    finally:
        assert local.ecrire("equipage/vitrine/affiche", {"id": kolax["id"], "visible": True}, local.tete)[0] == 200


def test_E6_les_badges_du_selecteur_de_chef(local):
    import site_equipage
    try:
        assert _equipes(local)["badges"] == {}, "vide par défaut"
        site_equipage.brancher_badges_chef(lambda gid: {str(MIRA): "Chef validé · Navigation", "abc": "x", ISHMAEL: ""})
        assert _equipes(local)["badges"] == {str(MIRA): "Chef validé · Navigation"}

        async def lent(gid):
            await asyncio.sleep(0)
            return {MIRA: "Chef validé · Cuisine"}
        site_equipage.brancher_badges_chef(lent)
        assert _equipes(local)["badges"] == {str(MIRA): "Chef validé · Cuisine"}

        def casse(gid):
            raise RuntimeError("questionnaire indisponible")
        site_equipage.brancher_badges_chef(casse)
        assert _equipes(local)["badges"] == {}, "le sélecteur reste utilisable"
    finally:
        site_equipage.brancher_badges_chef(None)
    #  La page les propose en premier (equipes_admin.js : le tri du sélecteur).
    js = (RACINE / "site" / "equipes_admin.js").read_text(encoding="utf-8")
    assert "(!!badges[String(b.id)] - !!badges[String(a.id)])" in js


def test_E7_rgpd_des_equipes_et_de_la_vitrine(local):
    import gdpr
    assert gdpr.DELETE_SUBJECT["equipes_membres"] == ["membre_id"]
    assert gdpr.ANONYMIZE["equipes"] == {"ids": ["chef_id", "maj_par"], "redact": []}
    assert gdpr.ANONYMIZE["equipage_vitrine"] == {"ids": ["maj_par"], "redact": []}

    async def valider():
        async with local.ctx.get_db() as db:
            return await gdpr.validate_map(db)
    rapport = local.faire(valider())
    for table in ("equipes", "equipes_membres", "equipage_vitrine"):
        assert table not in rapport["missing_tables"], rapport
        assert not [x for x in rapport["missing_columns"] if x[0] == table], rapport


# ═══════════════════════════════════════════════════════════════════════════════
#  V12 — la vitrine montre l'équipage ACTUEL (27/10/2026)
# ═══════════════════════════════════════════════════════════════════════════════

def _action(local, action, membre):
    st, rep, _h = local.requete("POST", "/tableau/espace/action", local.tete, {"action": action, "membre": str(membre)}, ecrire=True)
    assert st == 200, rep
    return json.loads(rep)


def _partir(g, uid):
    """Un membre quitte le serveur (le faux serveur du site local) : plus dans ses listes, ni dans ses rôles."""
    m = g.get_member(uid)
    for r in list(m.roles):
        if m in r.members:
            r.members.remove(m)
    g.members.remove(m)
    del g.membres[uid]
    return m


def _revenir(g, m):
    g.membres[m.id] = m
    g.members.append(m)
    for r in m.roles:
        if m not in r.members:
            r.members.append(m)


def _sur_la_vitrine(local, nom_roblox) -> bool:
    return any(a["roblox"]["nom"] == nom_roblox for a in _donnees(local)["affiches"])


def test_V12_un_depart_masque_l_affiche_un_retour_la_rend_rien_n_est_supprime(local):
    import site_equipage
    mira = next(a for a in local.faire(site_equipage._affiches_actives(local.g)) if a["membre_id"] == MIRA)
    nom = mira["roblox_nom"]
    assert _sur_la_vitrine(local, nom), "au départ, au mur"   # (la réponse est gardée en cache)
    jeton = next(a["id"] for a in _donnees(local)["affiches"] if a["roblox"]["nom"] == nom)
    #  Le rôle du clan retiré (la vraie action de la direction) : AUSSITÔT hors de la vitrine — le cache suit l'équipage.
    _action(local, "clan_retirer", MIRA)
    try:
        d = _donnees(local)
        assert not _sur_la_vitrine(local, nom) and jeton not in json.dumps(d), "ni au mur, ni dans une équipe publique"
        #  Rien n'est supprimé : la base la garde, l'atelier de la direction et le site de l'équipage la montrent encore.
        assert local.sql("SELECT retire_le FROM rell_affiches WHERE id=?", (mira["id"],)) == [(0,)]
        st, corps, _e = local.requete("GET", "/tableau/espace/api/rell/affiches", local.tete)
        assert st == 200 and any(a["id"] == mira["id"] for a in json.loads(corps)["affiches"])
        assert any(a["id"] == mira["id"] for a in local.lire("equipage", local.kolax)[1]["affiches"])
        #  La direction la voit « ancienne » (le mode édition, l'atelier : « Ancien membre · masquée de la vitrine »).
        assert mira["id"] in local.lire("equipage", local.tete)[1]["vitrine"]["anciennes"]
        assert "anciennes" not in json.dumps(local.lire("equipage", local.kolax)[1].get("vitrine", {})), "l'équipage n'a pas ce réglage"
    finally:
        _action(local, "clan_ajouter", MIRA)
    #  Le rôle rendu : elle revient toute seule, avec le même jeton.
    assert _sur_la_vitrine(local, nom) and jeton in json.dumps(_donnees(local))
    assert mira["id"] not in local.lire("equipage", local.tete)[1]["vitrine"]["anciennes"]


def test_V13_un_membre_parti_du_serveur_puis_revenu(local):
    import site_equipage
    kolax = next(a for a in local.faire(site_equipage._affiches_actives(local.g)) if a["membre_id"] == KOLAX)
    assert _sur_la_vitrine(local, kolax["roblox_nom"])
    m = _partir(local.g, KOLAX)
    try:
        d = _donnees(local)
        assert not _sur_la_vitrine(local, kolax["roblox_nom"])
        cuistots = next((e for e in d["equipes"] if e["nom"] == "Les Cuistots du Requin"), None)
        assert cuistots is None or cuistots["chef"] is None, "le chef parti n'est plus montré"
        assert local.sql("SELECT COUNT(*) FROM rell_affiches WHERE id=? AND retire_le=0", (kolax["id"],)) == [(1,)]
    finally:
        _revenir(local.g, m)
    assert _sur_la_vitrine(local, kolax["roblox_nom"])
    assert next(e for e in _donnees(local)["equipes"] if e["nom"] == "Les Cuistots du Requin")["chef"] is not None


def test_V14_une_affiche_sans_membre_lie_ne_change_pas(local):
    import site_equipage
    import tableau
    st, rep = local.ecrire("rell/affiche", {"id": "sans-membre-01", "roblox_nom": "Fantome_Seas", "surnom": "Le Fantôme",
                                            "prime": 1000, "niveau": 3, "statut": "actif"}, local.tete)
    assert st == 200, rep
    try:
        assert _sur_la_vitrine(local, "Fantome_Seas"), "sans membre lié : la direction la gère à la main"
        assert "sans-membre-01" not in local.lire("equipage", local.tete)[1]["vitrine"]["anciennes"]
        assert local.ecrire("equipage/vitrine/affiche", {"id": "sans-membre-01", "visible": False}, local.tete)[0] == 200
        assert not _sur_la_vitrine(local, "Fantome_Seas")
    finally:
        assert local.ecrire("equipage/vitrine/affiche", {"id": "sans-membre-01", "visible": True}, local.tete)[0] == 200
        st, _r = local.ecrire("rell/affiche/retirer", {"id": "sans-membre-01", "version": 1}, local.tete)
    del site_equipage, tableau
    #  La mention dans l'atelier de la direction : une ligne de capitainerie.js, le reste dans lien_equipage.js.
    cap = (RACINE / "site" / "capitainerie.js").read_text(encoding="utf-8")
    assert "mentionAncien(avecVerrou(affiche(a, cat," in cap
    assert 'libelle("site.equipage.ancien", "Ancien membre · masquée de la vitrine")' in (RACINE / "site" / "lien_equipage.js").read_text(encoding="utf-8")
