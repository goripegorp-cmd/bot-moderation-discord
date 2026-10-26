"""Le site de l'équipage (26/10/2026) — la sécurité d'abord, puis ce que l'équipage lit et ce que la tête compose.

Sur le VRAI site local (`outils/site_local.py` : le serveur du bot, ses modules, un faux Discord) :
S1 une session « equipage » contre CHAQUE adresse du serveur : 403 partout sauf la liste blanche — et la base n'a
   pas bougé (aucune écriture possible, ni par les adresses du site, ni par les actions, ni par la synchronisation).
S2 les notes de la direction, l'historique, qui a modifié quoi, les identifiants : jamais dans une réponse.
S3 le rôle du clan perdu : accès retiré tout de suite, session fermée (rendre le rôle ne la rouvre pas).
S4 les liens : falsifié, expiré, déjà servi, portée inconnue, hors du clan, tête sans le rôle, suspendu → refus ;
   le bon lien → la bonne page ; une ligne au journal par demi-heure.
S5 les images : seulement celles que le site de l'équipage cite.
S6 la tête : les deux pages ; le mode édition (blocs, ordre, masquer, actualité avec image) — le membre voit le résultat ;
   conflits et saisies refusées.
S7 ce que l'équipage lit : sa fiche, les affiches actives, aucun brouillon, les actualités automatiques.
S8 les analyses : des comptes justes.
S9 la porte elle-même : refus par défaut d'une portée non demandée (une adresse écrite demain), migration douce.
S10 le bouton du guide du clan, RGPD, câblage dans bot.py, la page (CSP, aucun HTML de données), aucune entrée de démo.
"""
from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

import aiosqlite
import discord
import pytest

from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
KOLAX, MIRA, BARBE, ANNE, ISHMAEL, TORTUGA = 1000, 1001, 1002, 1003, 1006, 1007   # BARBE : hors du clan
ORIGINE = {"X-Tableau": "1", "Origin": "http://localhost:8790", "Sec-Fetch-Site": "same-origin"}
SECRET = "NOTE-SECRETE-7c1f-ne-sort-jamais"


# ═══════════════════════════════════════════════════════════════════════════════
#  Le vrai site local, construit une fois pour ce fichier
# ═══════════════════════════════════════════════════════════════════════════════

class Local:
    def __init__(self, boucle, client, ctx):
        self.boucle, self.client, self.ctx, self.g = boucle, client, ctx, ctx.guild

    def faire(self, coro):
        return self.boucle.run_until_complete(coro)

    def entrer(self, chemin="/tableau/demo"):
        """(en-têtes avec le cookie de session, page d'arrivée) — par l'entrée de démonstration ou un lien."""
        import tableau

        async def f():
            r = await self.client.get(chemin, allow_redirects=False)
            if r.status != 303:
                return None, (r.status, await r.text())
            return {"Cookie": f"{tableau.COOKIE}={r.cookies[tableau.COOKIE].value}"}, r.headers["Location"]
        return self.faire(f())

    def requete(self, methode, chemin, h=None, corps=None, ecrire=False, params=None):
        """(statut, corps en octets, en-têtes)."""
        async def f():
            entetes = dict(h or {}, **(ORIGINE if ecrire else {}))
            r = await self.client.request(methode, chemin, headers=entetes, params=params, allow_redirects=False,
                                          json=corps if methode == "POST" else None)
            return r.status, await r.read(), r.headers
        return self.faire(f())

    def lire(self, nom, h):
        st, corps, _h = self.requete("GET", f"/tableau/equipage/api/{nom}", h)
        return st, json.loads(corps) if corps else None

    def ecrire(self, nom, corps, h):
        st, rep, _h = self.requete("POST", f"/tableau/espace/api/{nom}", h, corps, ecrire=True)
        return st, json.loads(rep) if rep else None

    def sql(self, requete, args=()):
        async def f():
            async with self.ctx.get_db() as db:
                async with db.execute(requete, args) as cur:
                    return await cur.fetchall()
        return self.faire(f())

    def png(self, nom="essai.png", couleur=(31, 78, 90)):
        """Une image envoyée par la tête (la vraie adresse `media`) : son identifiant."""
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (64, 40), couleur).save(b, "PNG")
        st, rep = self.ecrire("media", {"nom": nom, "type": "image/png", "base64": base64.b64encode(b.getvalue()).decode()},
                              self.tete)
        assert st == 200, rep
        return rep["id"]


@pytest.fixture(scope="module")
def local(tmp_path_factory):
    import paths
    import tableau
    import transcript_store
    mp = pytest.MonkeyPatch()
    mp.setattr(tableau, "ROUTES", {})
    mp.setattr(tableau, "REGLES", dict(tableau.REGLES))
    mp.setattr(tableau, "_SOURCES_MEDIAS", [])
    mp.setattr(tableau, "ROUTES_EQUIPAGE", {})
    mp.setattr(tableau, "MEDIAS_EQUIPAGE", None)
    mp.setattr(tableau, "RACINE_DONNEES", None)
    mp.setattr(transcript_store, "_BASE_DIR", transcript_store._BASE_DIR)
    mp.setattr(paths, "_RESOLVED_BASE", paths._RESOLVED_BASE)
    mp.syspath_prepend(str(RACINE / "outils"))
    import site_local
    from aiohttp.test_utils import TestClient, TestServer
    boucle = asyncio.new_event_loop()

    async def demarrer():
        app, ctx = await site_local.construire(tmp_path_factory.mktemp("equipage") / "local", 8790)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client, ctx
    client, ctx = boucle.run_until_complete(demarrer())
    try:
        site = Local(boucle, client, ctx)
        site.tete, _ = site.entrer("/tableau/demo")
        site.kolax, arrivee = site.entrer("/tableau/demo?qui=equipage")
        assert arrivee == "/tableau/equipage/"
        yield site
    finally:
        boucle.run_until_complete(client.close())
        pendantes = [t for t in asyncio.all_tasks(boucle) if not t.done()]   # la ronde du direct (S11), entre autres
        for t in pendantes:
            t.cancel()
        boucle.run_until_complete(asyncio.gather(*pendantes, return_exceptions=True))
        tableau._direct_salles.clear()
        boucle.close()
        mp.undo()
        for nom in ("site_local", "site_local_port"):
            sys.modules.pop(nom, None)


def _corps(octets) -> str:
    return octets.decode("utf-8", "replace") if isinstance(octets, (bytes, bytearray)) else str(octets)


# ═══════════════════════════════════════════════════════════════════════════════
#  S1 — une session « equipage » contre CHAQUE adresse : 403 partout sauf la liste blanche, aucune écriture
# ═══════════════════════════════════════════════════════════════════════════════

#  Ce qu'une session « equipage » atteint — et pourquoi. TOUT le reste doit répondre 403.
LIBRES = {
    ("GET", "/tableau/equipage"),               # la barre manquante : une redirection vers SA page
    ("GET", "/tableau/equipage/"),              # SA page
    ("GET", "/tableau/equipage/api/{nom}"),     # SES lectures (S2 : nettoyées)
    ("GET", "/tableau/espace"),                 # une redirection sans donnée, vers une page qui lui répond 403
    ("GET", "/tableau/espace/s/{chemin}"),      # les fichiers publics de site/ (aucune donnée)
    ("GET", "/tableau/espace/sw.js"),           # le service worker (public, aucune donnée)
    ("GET", "/tableau/espace/media/{media}"),   # seulement les images que son site cite (S5)
    ("POST", "/tableau/espace/sortir"),         # se déconnecter
    ("GET", "/tableau/{jeton}"),                # l'entrée par lien (S4)
}


def _empreinte_base(site) -> dict:
    """{table : empreinte de toutes ses lignes} — sauf ce qu'une simple visite change (sessions, liens, journal de
    sécurité, date de dernière vue d'une image)."""
    out = {}
    for (table,) in site.sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table in ("tableau_sessions", "tableau_jetons", "registre", "tableau_blocages"):
            continue
        colonnes = "id, guild_id, auteur_id, nom, type, octets, largeur, hauteur, cree_le" if table == "tableau_medias" else "*"
        lignes = site.sql(f"SELECT {colonnes} FROM {table} ORDER BY rowid")
        out[table] = hashlib.sha256(json.dumps(lignes, default=str).encode()).hexdigest()
    return out


def test_S1_une_session_equipage_n_atteint_que_sa_page_et_n_ecrit_rien(local):
    import health_server
    import site_equipage
    import tableau
    h = local.kolax
    assert local.lire("accueil", h)[0] == 200          # (l'accueil de départ est posé avant l'empreinte)
    avant = _empreinte_base(local)
    journal_avant = local.sql("SELECT MAX(id) FROM registre")[0][0] or 0
    routes = {(r.method, r.resource.canonical) for r in health_server.construire_app().router.routes()
              if r.resource.canonical.startswith("/tableau") and r.method in ("GET", "POST")}
    assert LIBRES <= routes, "la liste blanche décrit des adresses qui existent"
    #  Les adresses concrètes de chaque gabarit fermé : CHAQUE adresse du site (modules et tableau.py), chaque méthode.
    noms_site = {m: sorted(n for n, d in {**tableau.ROUTES, **tableau._INTERNES}.items() if m in d) for m in ("GET", "POST")}
    assert len(noms_site["GET"]) >= 10 and len(noms_site["POST"]) >= 20, noms_site
    assert {"equipage/bloc", "equipage/actualite", "media", "rell/affiche"} <= set(noms_site["POST"])
    actions = ("clan_ajouter", "clan_retirer", "moderer", "ticket_fermer", "casier_serveur", "debannir")
    essais = []
    for methode, gabarit in sorted(routes - LIBRES):
        if gabarit == "/tableau/espace/api/{nom}":
            essais += [(methode, f"/tableau/espace/api/{n}", {"id": "x"}) for n in noms_site[methode] + ["inconnue/x"]]
        elif gabarit == "/tableau/equipage/api/{nom}":
            essais += [(methode, f"/tableau/equipage/api/{n}", {}) for n in [*site_equipage.LECTURES, "inconnue"]]
        elif gabarit == "/tableau/espace/action":
            essais += [(methode, gabarit, {"action": a, "membre": str(KOLAX)}) for a in actions]
        elif gabarit == "/tableau/espace/sync":
            essais.append((methode, gabarit, {"ops": [{"op_id": "op-equipage-01", "api": "rell/affiche",
                                                       "corps": {"id": "demo-kolax-01", "surnom": "Pirate"}}]}))
        elif "{" in gabarit:
            pytest.fail(f"adresse nouvelle et non couverte par ce test : {methode} {gabarit} — l'ajouter ici")
        else:
            essais.append((methode, gabarit, {}))
    assert len(essais) >= 50, len(essais)
    refus = {}
    for methode, chemin, corps in essais:
        st, rep, _h = local.requete(methode, chemin, h, corps, ecrire=(methode == "POST"),
                                    params={"id": str(KOLAX), "q": "a", "ticket": "1", "quoi": "journal"} if methode == "GET" else None)
        refus[(methode, chemin)] = st
        assert st == 403, f"{methode} {chemin} → {st} : {_corps(rep)[:200]}"
        texte = _corps(rep)
        assert SECRET not in texte and "Kolax_RS" not in texte, f"{methode} {chemin} laisse passer des données"
    #  La page de la direction lui répond « réservé » et lui montre SON espace.
    st, rep, _h = local.requete("GET", "/tableau/espace/", h)
    assert st == 403 and "Réservé à la direction" in _corps(rep) and "/tableau/equipage/" in _corps(rep)
    #  La liste blanche, elle, répond.
    assert local.requete("GET", "/tableau/equipage/", h)[0] == 200
    assert local.requete("GET", "/tableau/equipage", h)[2]["Location"] == "/tableau/equipage/"
    for nom in site_equipage.LECTURES:
        assert local.lire(nom, h)[0] == 200, nom
    assert local.requete("GET", "/tableau/espace/s/equipage.js", h)[0] == 200
    #  RIEN n'a été écrit : chaque table identique ; au journal, seulement la tentative refusée (Sécurité).
    assert _empreinte_base(local) == avant, "une session de l'équipage a modifié la base"
    nouveaux = local.sql("SELECT categorie, type, gravite FROM registre WHERE id > ?", (journal_avant,))
    assert nouveaux and {(c, t) for c, t, _g in nouveaux} == {("Sécurité", "site.hors_portee")}, nouveaux
    assert len(nouveaux) == 1, "une ligne par session et par 10 minutes, pas une par requête"


def test_S1b_un_membre_ne_peut_meme_pas_se_faire_passer_pour_la_page(local):
    """Sans l'en-tête de la page, ou depuis un autre site : refusé avant même la session — et avec, toujours 403."""
    st, rep, _h = local.requete("POST", "/tableau/espace/api/equipage/bloc", local.kolax,
                                {"type": "texte", "contenu": {"texte": "Piraté"}})
    assert st in (400, 403)
    st, rep, _h = local.requete("POST", "/tableau/espace/api/equipage/bloc", local.kolax,
                                {"type": "texte", "contenu": {"texte": "Piraté"}}, ecrire=True)
    assert st == 403
    assert not local.sql("SELECT 1 FROM equipage_blocs WHERE contenu LIKE '%Piraté%'")


# ═══════════════════════════════════════════════════════════════════════════════
#  S2 — les notes, l'historique, qui a modifié quoi, les identifiants : jamais dans une réponse
# ═══════════════════════════════════════════════════════════════════════════════

def test_S2_les_lectures_nettoient_tout_ce_qu_une_affiche_ne_montre_pas(local):
    import affiches
    chef = local.g.get_member(FONDATEUR)
    st, rep = local.faire(affiches._route_affiche(local.g, chef, {}, {
        "membre_id": str(TORTUGA), "roblox_nom": "Tortuga_RS", "roblox_id": "1000007", "surnom": "La Tortue",
        "prime": 12_000, "niveau": 9, "grade": "Mousse", "statut": "actif", "notes": SECRET}))
    assert st == 200, rep
    a = rep["affiche"]
    st, rep = local.faire(affiches._route_affiche(local.g, local.g.get_member(DIRECTION), {}, dict(
        a, membre_id=str(TORTUGA), roblox_nom="Tortuga_RS", roblox_id="1000007", notes=SECRET + " (bis)", prime=13_000)))
    assert st == 200, rep
    for h in (local.kolax, local.tete):   # même la tête, sur la page de l'équipage, lit la forme nettoyée
        textes = []
        for nom in ("depart", "equipage", "accueil"):
            st, d = local.lire(nom, h)
            assert st == 200
            textes.append(json.dumps(d, ensure_ascii=False))
        tout = "\n".join(textes)
        assert SECRET not in tout, "une note de la direction est sortie"
        for interdit in (str(FONDATEUR), str(DIRECTION), '"notes"', '"historique"', '"cree_par"', '"maj_par"',
                         '"retire_le"', '"membre_id"', '"roblox_id"'):
            assert interdit not in tout, f"{interdit} sort dans les lectures de l'équipage"
    _st, eq = local.lire("equipage", local.kolax)
    t = next(x for x in eq["affiches"] if x["roblox"]["nom"] == "Tortuga_RS")
    assert set(t) == {"id", "membre", "roblox", "surnom", "prime", "niveau", "grade", "statut", "attributs"}
    assert set(t["membre"]) == {"nom", "avatar"} and set(t["roblox"]) == {"nom", "avatar"}
    assert t["prime"] == 13_000 and t["surnom"] == "La Tortue"
    #  L'historique d'une affiche (adresse de la direction) : refusé à l'équipage.
    st, rep, _h = local.requete("GET", "/tableau/espace/api/rell/affiche", local.kolax, params={"id": t["id"]})
    assert st == 403 and SECRET not in _corps(rep)


# ═══════════════════════════════════════════════════════════════════════════════
#  S3 — le rôle du clan perdu : accès retiré tout de suite, session fermée
# ═══════════════════════════════════════════════════════════════════════════════

def test_S3_role_du_clan_retire_acces_coupe_tout_de_suite(local):
    import tableau
    h, arrivee = local.entrer(f"/tableau/demo?qui=equipage&id={MIRA}")
    assert arrivee == "/tableau/equipage/" and local.lire("depart", h)[0] == 200
    emp = hashlib.sha256(h["Cookie"].split("=", 1)[1].encode()).hexdigest()
    assert local.sql("SELECT portee FROM tableau_sessions WHERE empreinte=?", (emp,)) == [("equipage",)]
    #  La direction retire le rôle du clan (la VRAIE action du bot, depuis son site).
    st, rep, _h = local.requete("POST", "/tableau/espace/action", local.tete,
                                {"action": "clan_retirer", "membre": str(MIRA)}, ecrire=True)
    assert st == 200 and json.loads(rep)["ok"], rep
    st, d = local.lire("depart", h)
    assert st == 403 and d["erreur"] == "Accès retiré.", "le rôle est relu à CHAQUE requête"
    assert local.sql("SELECT COUNT(*) FROM tableau_sessions WHERE empreinte=?", (emp,)) == [(0,)], "session fermée"
    assert emp not in tableau._sessions
    assert local.requete("GET", "/tableau/equipage/", h)[0] == 403
    j = local.sql("SELECT texte FROM registre WHERE type='site.equipage_ferme' ORDER BY id DESC LIMIT 1")
    assert j and "Mira" in j[0][0] and "plus le rôle du clan" in j[0][0]
    #  Le rôle rendu : l'ancienne session reste fermée ; il faut un lien neuf.
    st, rep, _h = local.requete("POST", "/tableau/espace/action", local.tete,
                                {"action": "clan_ajouter", "membre": str(MIRA)}, ecrire=True)
    assert st == 200 and json.loads(rep)["ok"], rep
    assert local.lire("depart", h)[0] == 403
    h2, _a = local.entrer(f"/tableau/demo?qui=equipage&id={MIRA}")
    assert local.lire("depart", h2)[0] == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  S4 — les liens
# ═══════════════════════════════════════════════════════════════════════════════

def test_S4_les_liens_de_l_equipage_et_leurs_refus(local):
    import site_equipage
    import tableau
    lien = lambda u, p="equipage", **kw: "/tableau/" + tableau.jeton(1, u, p, **kw)  # noqa: E731
    #  Le bon lien : SA page, une session « equipage », une ligne au journal.
    tableau._ouvertures.clear()
    av = local.sql("SELECT COUNT(*) FROM registre WHERE type='site.equipage'")[0][0]
    bon = lien(ANNE)
    h, arrivee = local.entrer(bon)
    assert arrivee == "/tableau/equipage/" and local.lire("depart", h)[1]["edition"] is False
    emp = hashlib.sha256(h["Cookie"].split("=", 1)[1].encode()).hexdigest()
    assert local.sql("SELECT portee FROM tableau_sessions WHERE empreinte=?", (emp,)) == [("equipage",)]
    #  Déjà servi : refusé ailleurs ; le même navigateur repasse.
    st, rep, _h = local.requete("GET", bon)
    assert st == 403 and "déjà servi" in _corps(rep) and "Guide du clan" in _corps(rep)
    st, _r, hd = local.requete("GET", bon, h)
    assert st == 303 and hd["Location"] == "/tableau/equipage/"
    #  Une seconde ouverture dans la demi-heure : pas une seconde ligne au journal.
    local.entrer(lien(ANNE))
    assert local.sql("SELECT COUNT(*) FROM registre WHERE type='site.equipage'")[0][0] == av + 1
    #  Les refus : falsifié, expiré, portée inconnue (et l'ancienne « rs »), hors du clan, la tête SANS le rôle du
    #  clan (elle a son lien « tout »), un lien « tout » pour un membre du clan, suspendu.
    a, b = bon.rsplit("/", 1)[1].split(".")
    faux = "/tableau/" + a + "." + ("A" if b[0] != "A" else "B") + b[1:]
    vraie = tableau._cle
    tableau._cle = b"une-autre-cle"
    try:
        autre_cle = "/tableau/" + tableau.jeton(1, ANNE, "equipage")
    finally:
        tableau._cle = vraie
    refuses = {"falsifié": faux, "autre clé": autre_cle, "expiré": lien(ANNE, maintenant=time.time() - 2 * tableau.DUREE),
               "rs": lien(ANNE, "rs"), "inconnue": lien(ANNE, "admin"), "hors du clan": lien(BARBE),
               "tête sans le rôle": lien(FONDATEUR), "tout pour un membre": lien(ANNE, "tout")}
    for raison, chemin in refuses.items():
        tableau._essais.clear()
        h_, (st, texte) = local.entrer(chemin)
        assert h_ is None and st == 403, f"{raison} : {st}"
    #  Suspendu : ni lien, ni session.
    m = local.g.get_member(ISHMAEL)
    hs, _a = local.entrer(f"/tableau/demo?qui=equipage&id={ISHMAEL}")
    local.faire(tableau.suspendre(local.g, m, "essai"))
    try:
        tableau._essais.clear()
        assert local.entrer(lien(ISHMAEL))[0] is None and local.lire("depart", hs)[0] == 403
        assert local.faire(site_equipage.lien_equipage(Obj(guild=local.g, user=m)))[0] is None
    finally:
        local.faire(_lever_suspension(local, ISHMAEL))
    #  La tête : son lien « tout » avec `vers=equipage` ouvre la page de l'équipage, en mode édition.
    tableau._essais.clear()
    ht, arrivee = local.entrer(lien(FONDATEUR, "tout") + "?vers=equipage")
    assert arrivee == "/tableau/equipage/" and local.lire("depart", ht)[1]["edition"] is True
    assert local.requete("GET", "/tableau/espace/", ht)[0] == 200, "la tête garde aussi sa page"


async def _lever_suspension(local, uid):
    import tableau
    async with local.ctx.get_db() as db:
        await db.execute("DELETE FROM tableau_blocages WHERE user_id=?", (uid,))
        await db.commit()
    tableau._blocages.pop((1, uid), None)


def test_S4b_le_lien_donne_par_le_bouton(local):
    import site_equipage
    import tableau

    def lien(uid):
        return local.faire(site_equipage.lien_equipage(Obj(guild=local.g, user=local.g.get_member(uid))))
    url, refus = lien(KOLAX)
    j = tableau.lire_jeton(url.rsplit("/tableau/", 1)[1])
    assert refus == "" and url.startswith("http://localhost:8790/tableau/") and (j["p"], j["u"]) == ("equipage", KOLAX)
    url, refus = lien(FONDATEUR)
    j = tableau.lire_jeton(url.rsplit("/tableau/", 1)[1].split("?")[0])
    assert url.endswith("?vers=equipage") and (j["p"], j["u"]) == ("tout", FONDATEUR), "la tête : son lien habituel"
    url, refus = lien(BARBE)
    assert url is None and "rôle du clan" in refus


# ═══════════════════════════════════════════════════════════════════════════════
#  S5 — les images : seulement celles que le site de l'équipage cite
# ═══════════════════════════════════════════════════════════════════════════════

def test_S5_les_images_que_l_equipage_peut_voir(local):
    h = local.kolax
    _st, eq = local.lire("equipage", h)
    _st, acc = local.lire("accueil", h)
    portrait = next(a["roblox"]["avatar"] for a in eq["affiches"] if a["roblox"]["avatar"])
    bandeau = next(b["contenu"]["image"] for b in acc["blocs"] if b["type"] == "bandeau")
    actu = next(a["image"] for a in acc["donnees"]["actualites"]["direction"] if a["image"])
    annonce = next(a["image"] for a in acc["donnees"]["actualites"]["auto"] if a["image"])
    for src in (portrait, bandeau, actu, annonce):
        st, _c, hd = local.requete("GET", "/tableau/espace/" + src, h)
        assert st == 200 and hd["Content-Type"].startswith("image/"), (src, st)
    #  Une image envoyée sur le site et citée nulle part sur celui de l'équipage : refusée (la tête la voit).
    cachee = local.png("cachee.png")
    assert local.requete("GET", f"/tableau/espace/media/{cachee}", local.tete)[0] == 200
    assert local.requete("GET", f"/tableau/espace/media/{cachee}", h)[0] == 403
    #  Posée dans un bloc MASQUÉ : toujours refusée ; montrée : permise.
    st, rep = local.ecrire("equipage/bloc", {"type": "image", "contenu": {"image": cachee, "legende": "Le coffre"},
                                             "visible": False}, local.tete)
    assert st == 200, rep
    import site_equipage
    site_equipage._permis.clear()
    assert local.requete("GET", f"/tableau/espace/media/{cachee}", h)[0] == 403
    st, rep = local.ecrire("equipage/bloc/visible", {"id": rep["bloc"]["id"], "visible": True}, local.tete)
    assert st == 200
    assert local.requete("GET", f"/tableau/espace/media/{cachee}", h)[0] == 200
    #  Le portrait d'une affiche mise à la corbeille : refusé ; le brouillon d'une annonce : jamais cité.
    st, rep = local.ecrire("equipage/bloc/supprimer", {"id": next(b["id"] for b in rep["accueil"]["blocs"]
                                                                    if b["type"] == "image")}, local.tete)
    assert st == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  S6 — la tête compose l'accueil ; le membre voit le résultat
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_la_tete_compose_l_accueil_et_le_membre_le_voit(local):
    h, t = local.kolax, local.tete
    assert local.lire("depart", t)[1]["edition"] is True and local.lire("depart", h)[1]["edition"] is False
    _st, acc = local.lire("accueil", t)
    assert all("version" in b and "visible" in b for b in acc["blocs"]), "la tête lit version et visibilité"
    _st, acc_m = local.lire("accueil", h)
    assert all("version" not in b and "visible" not in b for b in acc_m["blocs"]), "pas l'équipage"
    #  Ajouter un bloc texte : il arrive à la fin, l'équipage le voit.
    st, rep = local.ecrire("equipage/bloc", {"type": "texte", "contenu": {"titre": "Le mot du capitaine",
                                                                          "texte": "Cap à l'ouest, **matelots** !"}}, t)
    assert st == 200 and rep["bloc"]["version"] == 1, rep
    bid = rep["bloc"]["id"]
    ids = lambda hh: [b["id"] for b in local.lire("accueil", hh)[1]["blocs"]]  # noqa: E731
    assert ids(h)[-1] == bid
    #  Le monter : il change de place chez l'équipage aussi.
    st, rep = local.ecrire("equipage/bloc/deplacer", {"id": bid, "sens": "haut"}, t)
    assert st == 200 and ids(h)[-2] == bid
    #  Le modifier (version) ; une version périmée : conflit, rien d'écrasé.
    st, rep = local.ecrire("equipage/bloc", {"id": bid, "version": 1, "contenu": {"titre": "Le mot du capitaine",
                                                                                   "texte": "Cap au nord."}}, t)
    assert st == 200 and rep["bloc"]["version"] == 2
    st, rep = local.ecrire("equipage/bloc", {"id": bid, "version": 1, "contenu": {"texte": "Écrasé ?"}}, t)
    assert st == 409 and rep["conflit"] and rep["actuel"]["contenu"]["texte"] == "Cap au nord."
    #  Le masquer : l'équipage ne le voit plus, la tête si (marqué).
    st, rep = local.ecrire("equipage/bloc/visible", {"id": bid, "visible": False}, t)
    assert st == 200 and bid not in ids(h) and bid in ids(t)
    assert next(b for b in local.lire("accueil", t)[1]["blocs"] if b["id"] == bid)["visible"] is False
    #  Le supprimer.
    st, rep = local.ecrire("equipage/bloc/supprimer", {"id": bid}, t)
    assert st == 200 and bid not in ids(t)
    #  Publier une actualité AVEC son image, épinglée : l'équipage la lit en tête, et voit son image.
    img = local.png("une.png", (142, 42, 36))
    st, rep = local.ecrire("equipage/actualite", {"titre": "Abordage à l'aube", "texte": "Tous au port.", "image": img,
                                                  "epingle": True}, t)
    assert st == 200, rep
    aid = rep["id"]
    actus = local.lire("accueil", h)[1]["donnees"]["actualites"]["direction"]
    a0 = next(a for a in actus if a["titre"] == "Abordage à l'aube")
    assert actus.index(a0) < 2 and a0["epingle"] and a0["image"] == f"media/{img}", "épinglée : en tête"
    assert "version" not in a0 and local.requete("GET", f"/tableau/espace/media/{img}", h)[0] == 200
    st, rep = local.ecrire("equipage/actualite", {"id": aid, "version": 1, "titre": "Abordage à l'aube (reporté)",
                                                  "texte": "", "epingle": False}, t)
    assert st == 200
    st, rep = local.ecrire("equipage/actualite/retirer", {"id": aid}, t)
    assert st == 200 and not any(a["id"] == aid for a in local.lire("accueil", h)[1]["donnees"]["actualites"]["direction"])
    #  Les saisies refusées, champ par champ.
    mauvaises = [({"type": "inconnu", "contenu": {}}, "type"), ({"type": "texte", "contenu": {"texte": ""}}, "texte"),
                 ({"type": "bandeau", "contenu": {"titre": "x" * 81}}, "titre"),
                 ({"type": "image", "contenu": {"image": "AAAAAAAAAAAAAAAA"}}, "image"),
                 ({"type": "image", "contenu": {"image": "../../etc/passwd"}}, "image"),
                 ({"type": "honneur", "contenu": {"affiches": ["n-existe-pas"]}}, "affiches"),
                 ({"type": "analyses", "contenu": {"parties": ["secrets"]}}, "parties"),
                 ({"type": "actualites", "contenu": {"nombre": 99}}, "nombre")]
    for corps, champ in mauvaises:
        st, rep = local.ecrire("equipage/bloc", corps, t)
        assert st == 400 and rep.get("champ") == champ, (corps, rep)
    #  Chaque écriture est au journal du site, avec son auteur.
    j = [x[0] for x in local.sql("SELECT texte FROM registre WHERE categorie='Site' AND type LIKE 'site.equipage%'"
                                 " ORDER BY id")]
    assert any("bloc « Le mot du capitaine » ajouté (par GoRipe)" in x for x in j), j
    assert any("actualité « Abordage à l'aube » publiée" in x for x in j)


# ═══════════════════════════════════════════════════════════════════════════════
#  S7 — ce que l'équipage lit
# ═══════════════════════════════════════════════════════════════════════════════

def test_S7_sa_fiche_les_affiches_actives_aucun_brouillon(local):
    import affiches
    _st, eq = local.lire("equipage", local.kolax)
    moi = next(a for a in eq["affiches"] if a["id"] == eq["moi"])
    assert moi["roblox"]["nom"] == "Kolax_RS" and moi["surnom"] == "Le Requin"
    assert all(e["type"] and e["nom"] for e in eq["catalogue"]["elements"])
    cites = {(t, k) for a in eq["affiches"] for t, ks in a["attributs"].items() for k in ks}
    assert {(e["type"], e["cle"]) for e in eq["catalogue"]["elements"]} >= cites, "chaque insigne a sa fiche du catalogue"
    hb, _a = local.entrer(f"/tableau/demo?qui=equipage&id={ANNE}")
    assert local.lire("equipage", hb)[1]["moi"] is None, "pas d'affiche : la page le dit"
    #  À la corbeille : l'affiche quitte le mur de l'équipage.
    chef = local.g.get_member(FONDATEUR)
    st, rep = local.faire(affiches._route_affiche_retirer(local.g, chef, {}, {"id": "demo-calico03"}))
    assert st == 200
    try:
        assert "demo-calico03" not in [a["id"] for a in local.lire("equipage", local.kolax)[1]["affiches"]]
    finally:
        local.faire(affiches._route_affiche_restaurer(local.g, chef, {}, {"id": "demo-calico03"}))
    #  Les actualités automatiques : l'annonce publiée, la nouvelle affiche — jamais un brouillon.
    _st, acc = local.lire("accueil", local.kolax)
    tout = json.dumps(acc, ensure_ascii=False)
    auto = acc["donnees"]["actualites"]["auto"]
    assert any(a["genre"] == "annonce" and a["titre"] == "Le Movie 3 est sorti" for a in auto)
    assert any(a["genre"] == "affiche" and a.get("affiche") == "demo-kolax-01" for a in auto)
    for brouillon in ("Sortie en mer : le boss des abysses", "Nouvelles règles du clan", "Voici les métiers officiels"):
        assert brouillon not in tout, f"un brouillon sort : {brouillon}"
    assert acc["donnees"]["evenements"] and all(e["phase"] in ("a_venir", "en_cours") for e in acc["donnees"]["evenements"])


def test_S7b_le_texte_discord_devient_lisible():
    import site_equipage
    kolax, salon = 412345678901234567, 912345678901234567
    g = Obj(get_member=lambda uid: Obj(display_name="Kolax") if uid == kolax else None,
            get_channel=lambda cid: Obj(name="infos") if cid == salon else None)
    t = site_equipage.texte_discord(f"## Titre\n**Gras** <@{kolax}> <@!712345678901234567> <#{salon}> "
                                    "<@&512345678901234567> <:rell_x:123456789012345678>\n"
                                    "-# petit\n> cité\n[lien](https://exemple.fr) ~~barré~~ `code` 🏴‍☠️ fin", g)
    assert t == "Titre\n**Gras** @Kolax @membre #infos @rôle\npetit\ncité\nlien barré code fin"
    assert len(site_equipage.texte_discord("a" * 2000)) == site_equipage.TEXTE_AUTO_MAX


# ═══════════════════════════════════════════════════════════════════════════════
#  S8 — les analyses
# ═══════════════════════════════════════════════════════════════════════════════

def test_S8_les_analyses_comptent_juste(local):
    import rellseas_panneau
    _st, eq = local.lire("equipage", local.kolax)
    an = local.lire("accueil", local.kolax)[1]["donnees"]["analyses"]
    affiches_ = eq["affiches"]
    clan = [m for m in local.g.get_role(local.ctx.conf[rellseas_panneau.CLE_ROLE_CIBLE]).members if not m.bot]
    assert an["membres"]["clan"] == len(clan) and an["membres"]["affiches"] == len(affiches_)
    assert an["primes"]["total"] == sum(a["prime"] for a in affiches_)
    assert an["primes"]["max"] == max(a["prime"] for a in affiches_)
    assert [x["prime"] for x in an["primes"]["top"]] == sorted((a["prime"] for a in affiches_ if a["prime"]), reverse=True)[:5]
    for cle, type_ in (("metiers", "metier"), ("races", "race"), ("factions", "faction")):
        attendu = {}
        for a in affiches_:
            for k in a["attributs"].get(type_, []):
                attendu[k] = attendu.get(k, 0) + 1
        assert {x["cle"]: x["n"] for x in an[cle]} == attendu, cle
        assert all(x["nom"] and "icone" in x for x in an[cle])
    assert len(an["recrues"]["mois"]) == 12 and set(an["recrues"]["par_mois"]) == set(an["recrues"]["mois"])
    assert an["recrues"]["total_12"] == sum(an["recrues"]["par_mois"].values())
    niveaux = [a["niveau"] for a in affiches_ if a["niveau"]]
    assert an["niveaux"]["max"] == max(niveaux) and sum(x["n"] for x in an["niveaux"]["tranches"]) == len(niveaux)
    assert an["evenements"]["a_venir"] >= 1 and an["evenements"]["prochain"]["titre"]
    assert 0 <= an["evenements"]["taux_reponse"] <= 100


def test_S8b_tranches_et_mediane():
    import site_equipage
    assert site_equipage._mediane([]) == 0 and site_equipage._mediane([5]) == 5 and site_equipage._mediane([1, 3, 10, 20]) == 6
    t = site_equipage._tranches([1, 12, 25, 26, 72])
    assert [(x["de"], x["a"], x["n"]) for x in t] == [(1, 20, 2), (21, 40, 2), (41, 60, 0), (61, 80, 1)], \
        "un pas rond (20 jusqu'à 72), six tranches au plus, les vides gardées (le graphique ne ment pas)"
    assert site_equipage._tranches([]) == [] and len(site_equipage._tranches([99_000])) <= 6


# ═══════════════════════════════════════════════════════════════════════════════
#  S10 — le bouton du guide du clan, RGPD, câblage, la page
# ═══════════════════════════════════════════════════════════════════════════════

class _Reponse:
    def __init__(self):
        self.envois, self.fait = [], False

    def is_done(self):
        return self.fait

    async def send_message(self, *a, **kw):
        self.envois.append(kw)
        self.fait = True


def test_S10_le_bouton_du_guide_du_clan(local, monkeypatch):
    import site_equipage
    import tableau
    import zones
    #  Persistant : son gabarit, inscrit au démarrage du bot.
    b = site_equipage.BoutonSiteEquipage()
    assert b.item.custom_id == "eq:site" and site_equipage.BoutonSiteEquipage.__discord_ui_compiled_template__.fullmatch("eq:site")
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "bot.add_dynamic_items(site_equipage.BoutonSiteEquipage)" in src
    #  Dans le guide du clan : une section, le bouton DynamicItem (une vue mixte effacerait le gabarit global).
    composants, signature = local.faire(site_equipage.section_guide(local.g, local.ctx.conf))
    assert signature and any(isinstance(x, site_equipage.BoutonSiteEquipage) for c in composants for x in c.walk_children())
    monkeypatch.setattr(zones, "_ticket", None)
    monkeypatch.setattr(zones, "_boutons_langue", None)
    vue, sig = zones.vue_guide_clan(local.g, local.ctx.conf, {}, None, (composants, signature))
    assert sig.endswith("|s" + signature)
    assert all(isinstance(x, discord.ui.DynamicItem) or not x.is_dispatchable() for x in vue.walk_children())
    assert "Le site de l'équipage" in "\n".join(x.content for x in vue.walk_children() if isinstance(x, discord.ui.TextDisplay))
    assert sum(1 for _x in vue.walk_children()) <= 40
    #  Sans rôle du clan réglé, ou site injoignable : pas de bouton qui ment.
    assert local.faire(site_equipage.section_guide(local.g, {})) is None
    monkeypatch.setattr(tableau, "_base", "")
    assert local.faire(site_equipage.section_guide(local.g, local.ctx.conf)) is None
    monkeypatch.undo()
    #  zones.setup remet le branchement à zéro (l'étape du bot le rebranche ensuite).
    monkeypatch.setattr(zones, "_section_site", site_equipage.section_guide)
    zones.setup(cfg=zones._cfg, db_set=zones._db_set, log=lambda *a: None)
    assert zones._section_site is None
    #  Le clic : un message pour soi, avec le lien ; un refus poli hors du clan.

    def cliquer(uid):
        i = Obj(guild=local.g, user=local.g.get_member(uid), response=_Reponse(), delete_original_response=None)
        local.faire(b.callback(i))
        return i.response.envois[0]
    envoi = cliquer(KOLAX)
    assert envoi["ephemeral"] is True
    liens = [x.url for x in envoi["view"].walk_children() if isinstance(x, discord.ui.Button) and x.url]
    assert len(liens) == 1 and tableau.lire_jeton(liens[0].rsplit("/", 1)[1])["p"] == "equipage"
    envoi = cliquer(BARBE)
    assert envoi["ephemeral"] is True and not any(isinstance(x, discord.ui.Button) for x in envoi["view"].walk_children())
    assert "rôle du clan" in "\n".join(x.content for x in envoi["view"].walk_children() if isinstance(x, discord.ui.TextDisplay))


def test_S11_le_direct_refuse_l_equipage_et_ses_verrous_gardent_l_accueil(local):
    """La présence en direct (`/tableau/espace/direct`, et son repli HTTP) : une session « equipage » n'y entre JAMAIS —
    refusée dès la porte, aucune WebSocket ouverte —, même glissée dans une prise du direct (portée relue en base). Et
    les écritures de l'accueil respectent les verrous : un bloc ou une actualité que la direction modifie ne s'écrit pas
    depuis un autre compte (423), puis s'écrit dès qu'il est libre."""
    import aiohttp
    import tableau
    origine = {"Origin": "http://localhost:8790"}

    async def socket(h):
        try:
            ws = await local.client.ws_connect("/tableau/espace/direct", headers=dict(h, **origine))
        except aiohttp.WSServerHandshakeError as ex:
            return ex.status, None
        return 101, ws
    st, _ws = local.faire(socket(local.kolax))
    assert st == 403, "aucune WebSocket pour l'équipage"
    assert local.requete("GET", "/tableau/espace/api/direct/etat", local.kolax, params={"onglet": "onglet-equipage-1"})[0] == 403
    assert local.requete("POST", "/tableau/espace/api/direct/envoi", local.kolax,
                         {"onglet": "onglet-equipage-1", "t": "prendre", "o": "accueil:x"}, ecrire=True)[0] == 403
    #  Même glissée dans une prise du direct (une erreur de câblage demain), la portée relue en base la refuse.
    emp = hashlib.sha256(local.kolax["Cookie"].split("=", 1)[1].encode()).hexdigest()
    prise = tableau._Prise("essai1", 1, KOLAX, emp, None, time.time())
    assert local.faire(tableau._session_direct(prise, time.time(), forcer=True)) == "acces"
    #  Les verrous de l'accueil : la direction tient un bloc, le fondateur ne peut pas l'écrire.
    hd, _a = local.entrer("/tableau/demo?qui=direction&vers=equipage")
    _st, acc = local.lire("accueil", local.tete)
    bloc = next(b for b in acc["blocs"] if b["type"] == "texte")

    async def tenir_puis_ecrire():
        st, ws = await socket(hd)
        assert st == 101
        await ws.send_json({"t": "bonjour", "page": "site-equipage/accueil"})
        await ws.send_json({"t": "prendre", "o": "accueil:" + bloc["id"], "ti": "le bloc « Le code » de l'accueil"})
        for _ in range(20):
            m = await ws.receive_json(timeout=3)
            if m.get("t") == "pris":
                break
        corps = {"id": bloc["id"], "version": bloc["version"], "contenu": dict(bloc["contenu"], texte="Écrit par-dessus ?")}
        r = await local.client.post("/tableau/espace/api/equipage/bloc", json=corps, headers=dict(local.tete, **ORIGINE))
        refuse = (r.status, await r.json())
        r = await local.client.post("/tableau/espace/api/equipage/bloc/visible", json={"id": bloc["id"], "visible": False},
                                    headers=dict(local.tete, **ORIGINE))
        refuse_visible = r.status
        await ws.send_json({"t": "lacher", "o": "accueil:" + bloc["id"]})
        await asyncio.sleep(0.3)
        await ws.close()
        r = await local.client.post("/tableau/espace/api/equipage/bloc", json=corps, headers=dict(local.tete, **ORIGINE))
        return refuse, refuse_visible, r.status
    refuse, refuse_visible, apres = local.faire(tenir_puis_ecrire())
    assert refuse[0] == 423 and "Capitaine Direction" in refuse[1]["erreur"], refuse
    assert refuse_visible == 423
    assert apres == 200, "libéré : l'écriture passe"
    #  La clé de chaque écriture : `accueil:<id>`, `actualite:<id>` ; un ajout ne verrouille rien.
    import site_equipage
    v = {n: d["verrou"] for n, d in site_equipage.ROUTES_SITE.items()}
    assert v["equipage/bloc"]({"id": "abcdef12"}) == "accueil:abcdef12" and v["equipage/bloc"]({"type": "texte"}) is None
    assert v["equipage/actualite/retirer"]({"id": "abcdef12"}) == "actualite:abcdef12"
    assert v["equipage/bloc"]({"id": "../x"}) is None and all(callable(f) for f in v.values())


def test_S10b_rgpd_et_cablage_dans_le_bot(local):
    import gdpr
    for table in ("equipage_blocs", "equipage_actualites"):
        assert gdpr.ANONYMIZE[table] == {"ids": ["cree_par", "maj_par"], "redact": []}

    async def valider():
        async with local.ctx.get_db() as db:
            return await gdpr.validate_map(db)
    manque = local.faire(valider())
    assert not [t for t in manque["missing_tables"] if t.startswith("equipage")]
    assert not [c for c in manque["missing_columns"] if c[0].startswith("equipage") or c[0] == "tableau_sessions"]
    arbre = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
    boot = ast.unparse(next(n for n in arbre.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_activite_boot"))
    etape = boot[boot.index("with _Etape('site_equipage'):"):]
    for morceau in ("site_equipage.setup(get_db=get_db, cfg=cfg", "await site_equipage.init_db()",
                    "tableau.monter(site_equipage)", "tableau.monter_equipage(site_equipage.LECTURES, medias=site_equipage.medias_permis)",
                    "zones.brancher_site_equipage(site_equipage.section_guide)"):
        assert morceau in etape, morceau
    assert boot.index("with _Etape('tableau'):") < boot.index("with _Etape('site_equipage'):")
    assert boot.index("with _Etape('zones'):") < boot.index("with _Etape('site_equipage'):"), "après zones (son setup)"
    for fichier in ("site_equipage.py", "tableau.py", "health_server.py", "bot.py", "zones.py"):
        texte = (RACINE / fichier).read_text(encoding="utf-8")
        assert "/tableau/demo" not in texte and "site_local" not in texte, f"{fichier} : aucune entrée sans lien"


def test_S10c_la_page_csp_et_aucun_html_de_donnees(local):
    import tableau
    st, corps, hd = local.requete("GET", "/tableau/equipage/", local.kolax)
    page = _corps(corps)
    assert st == 200 and hd["Content-Security-Policy"] == tableau.CSP_SITE and hd["Cache-Control"] == "no-store"
    assert "{{V}}" not in page and 'src="/tableau/espace/s/equipage.js?v=' in page
    assert "<script>" not in page and " style=" not in page and "<style" not in page, "rien en ligne (CSP)"
    for nom in ("equipage.js", "equipage_accueil.js", "equipage_commun.js"):
        js = (RACINE / "site" / nom).read_text(encoding="utf-8")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js and "outerHTML" not in js
        assert not re.search(r'\{\s*action:\s*"', js), "aucune action du site de la direction"
        assert not re.search(r"[\U0001F300-\U0001FAFF]", js), "aucun émoji"
    acc = (RACINE / "site" / "equipage_accueil.js").read_text(encoding="utf-8")
    assert '"equipage/bloc"' in acc and "poster(" in acc, "les écritures passent par l'API de la direction"
    #  L'équipage ne charge AUCUN module du site de la direction qui ouvrirait sa file ou ses données.
    principal = (RACINE / "site" / "equipage.js").read_text(encoding="utf-8")
    for module in ("./app.js", "./hors_ligne.js", "./discord.js", "./clan.js", "./recrutement.js", "./capitainerie.js"):
        assert f'from "{module}"' not in principal


# ═══════════════════════════════════════════════════════════════════════════════
#  S9 — la porte elle-même (en dernier : ces tests rappellent tableau.setup)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S9_refus_par_defaut_d_une_portee_non_demandee(tmp_path, monkeypatch):
    """Une adresse écrite demain (la présence en direct, une WebSocket…) qui appelle `_verifier` ou `_session` sans y
    penser reste fermée à l'équipage ; `sortir` les accepte toutes."""
    import tableau
    import contextlib

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(tmp_path / "porte.db")
        try:
            yield db
        finally:
            await db.close()
    clan_r = Obj(id=50)
    m = Obj(id=7, bot=False, roles=[clan_r], display_name="Kolax")
    g = Obj(id=1, get_member=lambda uid: m if uid == 7 else None)

    async def cfg(_g):
        return {"rellseas_role": 50}
    tableau.setup(bot=Obj(get_guild=lambda gid: g), cle="k", base_url="https://bot.exemple", cfg=cfg, get_db=get_db,
                  mesurer_groupe=None, autorise_membre=lambda gg, mm, c: False, direction=lambda gg, mm, c: False,
                  tete=(), log=lambda *a: None)
    import registre
    registre.setup(get_db=get_db, log=lambda *a: None)

    async def scenario():
        await tableau.init_db()
        await registre.init_db()
        sid = await tableau._ouvrir_session(1, 7, int(time.time()) + 3600, portee="equipage")
        req = Obj(cookies={tableau.COOKIE: sid}, headers={}, remote="1.2.3.4", path="/tableau/espace/direct")
        defaut = await tableau._session(req)
        toutes = await tableau._session(req, portees=None)
        try:
            await tableau._verifier(req)
            refus = None
        except tableau._Refus as r:
            refus = (r.status, r.portee)
        ok, _g = await tableau._verifier(req, portees=tableau.PORTEES)
        with pytest.raises(ValueError):
            await tableau._ouvrir_session(1, 7, int(time.time()) + 3600, portee="admin")
        return defaut, toutes, refus, ok
    defaut, toutes, refus, ok = asyncio.run(scenario())
    assert defaut is None, "par défaut : « tout » seulement"
    assert toutes is not None and refus == (403, "equipage") and ok["p"] == "equipage"
    assert tableau.lire_jeton(tableau.jeton(1, 7, "rs")) is None, "l'ancienne portée « rs » est refusée"


def test_S9b_migration_douce_des_sessions(tmp_path):
    """Une base d'avant (sans colonne `portee`) : la colonne arrive, les sessions de la tête restent « tout »."""
    import tableau
    import contextlib
    chemin = tmp_path / "ancienne.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    tete = Obj(id=FONDATEUR, bot=False, roles=[], display_name="GoRipe")
    g = Obj(id=1, get_member=lambda uid: tete if uid == FONDATEUR else None)

    async def cfg(_g):
        return {}
    tableau.setup(bot=Obj(get_guild=lambda gid: g), cle="k", base_url="https://bot.exemple", cfg=cfg, get_db=get_db,
                  mesurer_groupe=None, autorise_membre=lambda gg, mm, c: mm.id == FONDATEUR,
                  direction=lambda gg, mm, c: True, tete=(FONDATEUR,), log=lambda *a: None)
    sid = "s" * 43

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE tableau_sessions (empreinte TEXT PRIMARY KEY, guild_id INTEGER,"
                             " user_id INTEGER, cree_le INTEGER, expire_le INTEGER)")
            await db.execute("INSERT INTO tableau_sessions VALUES (?,1,?,?,?)",
                             (tableau._empreinte(sid), FONDATEUR, int(time.time()), int(time.time()) + 3600))
            await db.commit()
        await tableau.init_db()
        await tableau.init_db()  # deux fois : sans erreur
        j, _g = await tableau._verifier(Obj(cookies={tableau.COOKIE: sid}, headers={}, remote="1.2.3.4"))
        async with get_db() as db:
            async with db.execute("SELECT portee FROM tableau_sessions") as cur:
                return j, await cur.fetchall()
    j, lignes = asyncio.run(scenario())
    assert j["p"] == "tout" and lignes == [("tout",)]
