"""Le questionnaire en ligne du candidat et son direct (26/10/2026) — la sécurité d'abord.

Sur le VRAI site local (`outils/site_local.py` : le serveur du bot, ses modules, un faux Discord) :
C1 une session « candidat » contre CHAQUE adresse du serveur : 403 partout sauf sa liste blanche — avec son cookie, puis
   le même identifiant glissé dans le cookie de la direction — et la base n'a pas bougé.
C2 rien ne sort vers le candidat : ni réponse attendue, ni variante, ni source, ni extrait, ni section, ni étape pas encore
   ouverte, ni nom de l'équipe — dans AUCUNE réponse (lectures, écritures, refus, pages, pages d'erreur).
C3 la liaison : SON envoi seulement — un autre candidat, un lien forgé, un ticket fermé, un envoi remplacé, deux envois, un
   lien déjà servi, un lien de la direction, un lien expiré, un suspendu.
C4 l'envoi : les MÊMES tables et états que le formulaire Discord (réponses, statut, suivi, cartes du ticket, historique,
   journal, dossier, correction) ; un brouillon n'est jamais une réponse.
C5 le passage d'étape : seulement l'étape ouverte, une seule fois ; étape forgée, pas ouverte, déjà envoyée, double envoi
   → refusés ; la dernière clôt l'envoi ; un envoi d'avant (`etape_ouverte` = 0) ne change pas ; les cadences et bornes.
C6 le chef d'équipe : le message privé (fermés → False), son bouton PERSISTANT (après un redémarrage), le membre visé seul,
   le rôle du clan revérifié à chaque requête, l'envoi clos.
C7 le direct : diffusé aux seules sessions « tout » branchées par WebSocket, au débit borné ; la lecture sans WebSocket.
C8 le journal : une ligne par ouverture et par envoi, jamais par frappe.
C9 les textes : déclarés au registre, la page les lit dans SA lecture (jamais `textes/site`).
C10 le câblage (bot.py, health_server, RGPD), la page (CSP, aucun HTML de données).
C11 la porte elle-même (`tableau._verifier`) : refus par défaut, sans branchement, en panne.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import aiohttp
import aiosqlite
import discord
import pytest

from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
KOLAX, MIRA, ANNE, TOBIAS = 1000, 1001, 1003, 1020
ORIGINE = {"X-Tableau": "1", "Origin": "http://localhost:8790", "Sec-Fetch-Site": "same-origin"}
SECRETS = ("REPONSE-SECRETE-7f3c", "VARIANTE-SECRETE-2b9d", "source-secrete.exemple", "EXTRAIT-SECRET-55e1",
           "SECTION-SECRETE-91a")
EQUIPE = ("GoRipe", "Capitaine Direction")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le vrai site local, construit une fois pour ce fichier
# ═══════════════════════════════════════════════════════════════════════════════

class Local:
    def __init__(self, boucle, client, ctx):
        self.boucle, self.client, self.ctx, self.g = boucle, client, ctx, ctx.guild
        self.reponses_vues: list = []      # tout ce que le serveur a répondu au candidat (C2)

    def faire(self, coro):
        return self.boucle.run_until_complete(coro)

    def entrer(self, chemin, h=None):
        """(en-têtes avec le cookie posé, page d'arrivée) — ou (None, (statut, texte)). Le compteur des faux liens est
        remis à zéro : chaque test en essaie quelques-uns depuis la même adresse."""
        import tableau
        tableau._essais.clear()

        async def f():
            r = await self.client.get(chemin, headers=h or {}, allow_redirects=False)
            if r.status != 303:
                return None, (r.status, await r.text())
            nom = tableau.COOKIE_CANDIDAT if tableau.COOKIE_CANDIDAT in r.cookies else tableau.COOKIE
            if nom not in r.cookies:
                return dict(h or {}), r.headers["Location"]
            return {"Cookie": f"{nom}={r.cookies[nom].value}"}, r.headers["Location"]
        return self.faire(f())

    def candidat(self, q):
        h, arrivee = self.entrer("/tableau/demo?qui=candidat&" + q)
        assert h is not None and arrivee == "/tableau/candidature/", arrivee
        return h

    def requete(self, methode, chemin, h=None, corps=None, ecrire=False, params=None):
        """(statut, corps en octets, en-têtes)."""
        async def f():
            entetes = dict(h or {}, **(ORIGINE if ecrire else {}))
            r = await self.client.request(methode, chemin, headers=entetes, params=params, allow_redirects=False,
                                          json=corps if methode == "POST" else None)
            return r.status, await r.read(), r.headers
        return self.faire(f())

    def lire(self, nom, h, params=None):
        st, corps, _h = self.requete("GET", f"/tableau/candidature/api/{nom}", h, params=params)
        self.reponses_vues.append(corps)
        return st, json.loads(corps) if corps else None

    def ecrire(self, nom, corps, h):
        st, rep, _h = self.requete("POST", f"/tableau/candidature/api/{nom}", h, corps, ecrire=True)
        self.reponses_vues.append(rep)
        return st, json.loads(rep) if rep else None

    def api(self, nom, h, params=None):
        st, corps, _h = self.requete("GET", f"/tableau/espace/api/{nom}", h, params=params)
        return st, json.loads(corps) if corps else None

    def sql(self, requete, args=()):
        async def f():
            async with self.ctx.get_db() as db:
                cur = await db.execute(requete, args)
                lignes = await cur.fetchall()
                await db.commit()
                return lignes
        return self.faire(f())

    def ticket(self, uid, etapes=None, ouverte=0, fiche=0, questions=None):
        """Un ticket du clan neuf et son questionnaire envoyé (le VRAI `questionnaire.envoyer`) : (ticket, envoi). `etapes`
        : le nombre d'étapes (les questions réparties en parts qui se suivent, le format de l'équipe du recrutement) ;
        `ouverte` : la porte (0 : un envoi d'avant) ; `questions` : des identifiants de la banque."""
        import questionnaire

        async def f():
            async with self.ctx.get_db() as db:
                async with db.execute("SELECT COALESCE(MAX(id), 0) FROM tickets") as cur:
                    tid = max(int((await cur.fetchone())[0]) + 1, 500)
                await db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
                                 (tid, 1, 9000 + tid, uid, "p1", FONDATEUR, "open", "{}", "2026-10-26 10:00:00"))
                await db.commit()
            ch, _tk = await questionnaire._ticket_ouvert(self.g, tid)
            await questionnaire.poser_etape1(self.g, ch, tid, uid, nombre=10)
            st, rep = await questionnaire.envoyer(self.g, tid, self.g.get_member(FONDATEUR),
                                                  {"questions": questions} if questions else {}, depuis="etape1")
            assert st == 200, rep
            e = await questionnaire._envoi(rep["envoi"])
            if etapes:
                n = len(e["questions"])
                qs = [dict(q, etape=1 + k * etapes // n) for k, q in enumerate(e["questions"])]
                decl = [{"numero": k, "titre": f"Partie {k}", "consigne": f"Consigne {k}."} for k in range(1, etapes + 1)]
                async with self.ctx.get_db() as db:
                    await db.execute("UPDATE recrutement_envois SET questions=?, etapes=?, etape_ouverte=?, etape_fiche=?"
                                     " WHERE id=?", (json.dumps(qs, ensure_ascii=False), json.dumps(decl), ouverte, fiche,
                                                     e["id"]))
                    await db.commit()
            return tid, int(e["id"])
        return self.faire(f())

    def ouvrir_etape(self, envoi):
        """La direction ouvre l'étape suivante (ce que fait `questionnaire.etape_suivante`, chez l'équipe du recrutement)."""
        self.sql("UPDATE recrutement_envois SET etape_ouverte=etape_ouverte+1 WHERE id=?", (envoi,))

    def annonces(self):
        """Le temps aux tâches de fond (cartes, journal) de finir."""
        async def f():
            for _ in range(3):
                await asyncio.sleep(0.05)
        self.faire(f())


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
    mp.setattr(tableau, "AUTORISE_CANDIDAT", None)
    mp.setattr(transcript_store, "_BASE_DIR", transcript_store._BASE_DIR)
    mp.setattr(paths, "_RESOLVED_BASE", paths._RESOLVED_BASE)
    mp.syspath_prepend(str(RACINE / "outils"))
    import site_local
    from aiohttp.test_utils import TestClient, TestServer
    boucle = asyncio.new_event_loop()

    async def demarrer():
        app, ctx = await site_local.construire(tmp_path_factory.mktemp("candidature") / "local", 8790)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client, ctx
    client, ctx = boucle.run_until_complete(demarrer())
    try:
        site = Local(boucle, client, ctx)
        site.tete, _ = site.entrer("/tableau/demo")
        site.direction, _ = site.entrer("/tableau/demo?qui=direction")
        site.kolax_equipage, _ = site.entrer("/tableau/demo?qui=equipage")
        yield site
    finally:
        #  Les réglages du module rendus QUOI QU'IL ARRIVE (sinon les modules suivants héritent du site local) ; `gather()`
        #  sans tâche chercherait une boucle courante, qu'aucune n'est plus après un `asyncio.run` (C11).
        try:
            boucle.run_until_complete(client.close())
            pendantes = [t for t in asyncio.all_tasks(boucle) if not t.done()]
            for t in pendantes:
                t.cancel()
            if pendantes:
                boucle.run_until_complete(asyncio.gather(*pendantes, return_exceptions=True))
            tableau._direct_salles.clear()
            boucle.close()
        finally:
            mp.undo()
            for nom in ("site_local", "site_local_port"):
                sys.modules.pop(nom, None)


@pytest.fixture
def sans_cadence(monkeypatch):
    """Les cadences du questionnaire (deux envois par seconde…) levées : le test prouve le refus SUR LE FOND (étape,
    double envoi), pas la cadence (C5f la prouve à part)."""
    import candidature_site
    monkeypatch.setattr(candidature_site, "_cadence", lambda *a, **k: True)


def _texte(octets) -> str:
    return octets.decode("utf-8", "replace") if isinstance(octets, (bytes, bytearray)) else str(octets)


def _composants(vue) -> list:
    """Tous les composants d'une vue (Components V2), à plat : {type, custom_id, url, label, content…}."""
    out = []

    def tout(c):
        if isinstance(c, dict):
            out.append(c)
            for x in c.get("components", []) or []:
                tout(x)
            if c.get("accessory"):
                tout(c["accessory"])
    for comp in vue.to_components():
        tout(comp)
    return out


def _journal(local, avant: int, type_: str, membre: int) -> list:
    """Les textes du journal de ce genre pour ce membre, écrits depuis `avant` (dans l'ordre)."""
    return [t for (t,) in local.sql("SELECT texte FROM registre WHERE id > ? AND type=? AND membre_id=? ORDER BY id",
                                    (avant, type_, membre))]


def _dernier_id(local) -> int:
    return local.sql("SELECT MAX(id) FROM registre")[0][0] or 0


async def _texte_registre(cle):
    import textes
    return await textes.texte(1, cle)


def _questions_secretes(local) -> list:
    """Six questions de la banque dont la réponse, les variantes, la source, l'extrait et la section sont des témoins
    uniques (le VRAI `questionnaire.enregistrer_question`)."""
    import questionnaire
    chef = local.g.get_member(FONDATEUR)
    ids = []
    for k in range(6):
        st, rep = local.faire(questionnaire.enregistrer_question(local.g, chef, {
            "theme": "jeu", "question": f"Question témoin numéro {k} : quel est le mot gravé sur le coffre {k} ?",
            "reponse": f"REPONSE-SECRETE-7f3c-{k}", "variantes": [f"VARIANTE-SECRETE-2b9d-{k}"], "type": "texte",
            "difficulte": "facile", "source": f"https://source-secrete.exemple/coffre{k}", "section": f"SECTION-SECRETE-91a {k}",
            "extrait": f"EXTRAIT-SECRET-55e1 {k}", "statut": "confirme"}))
        assert st == 200, rep
        ids.append(rep["question"]["id"])
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
#  C1 — une session « candidat » contre CHAQUE adresse : 403 partout sauf sa liste blanche, aucune écriture
# ═══════════════════════════════════════════════════════════════════════════════

#  Ce qu'une session « candidat » atteint — et pourquoi. TOUT le reste répond 403.
LIBRES = {
    ("GET", "/tableau/candidature"),              # la barre manquante : une redirection vers SA page
    ("GET", "/tableau/candidature/"),             # SA page
    ("GET", "/tableau/candidature/api/{nom}"),    # SES lectures (C2 : rien de secret)
    ("POST", "/tableau/candidature/api/{nom}"),   # SES écritures dédiées (C3 à C5 : son envoi, ses étapes ouvertes)
    ("GET", "/tableau/candidature/{jeton}"),      # l'entrée par son lien (C3)
    ("GET", "/tableau/espace"),                   # une redirection sans donnée, vers une page qui lui répond 403
    ("GET", "/tableau/equipage"),                 # idem, vers le site de l'équipage (403 aussi)
    ("GET", "/tableau/espace/s/{chemin}"),        # les fichiers publics de site/ (aucune donnée)
    ("GET", "/tableau/espace/sw.js"),             # le service worker (public, aucune donnée)
    ("POST", "/tableau/espace/sortir"),           # se déconnecter (toute portée)
}


def _empreinte_base(site) -> dict:
    """{table : empreinte de toutes ses lignes} — sauf ce qu'une simple visite change (sessions, liens, journal, blocages,
    date de dernière vue d'une image)."""
    out = {}
    for (table,) in site.sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if table in ("tableau_sessions", "tableau_jetons", "registre", "tableau_blocages"):
            continue
        colonnes = "id, guild_id, auteur_id, nom, type, octets, largeur, hauteur, cree_le" if table == "tableau_medias" else "*"
        out[table] = hashlib.sha256(json.dumps(site.sql(f"SELECT {colonnes} FROM {table} ORDER BY rowid"),
                                               default=str).encode()).hexdigest()
    return out


@pytest.mark.parametrize("mode", ["son_cookie", "cookie_de_la_direction"])
def test_C1_une_session_candidat_n_atteint_que_sa_page(local, mode):
    import health_server
    import site_equipage
    import tableau
    h = local.candidat("ticket=60")
    sid = h["Cookie"].split("=", 1)[1]
    if mode == "cookie_de_la_direction":   # le même identifiant, recopié à la main dans le cookie de la direction
        h = {"Cookie": f"{tableau.COOKIE}={sid}"}
    avant = _empreinte_base(local)
    journal_avant = local.sql("SELECT MAX(id) FROM registre")[0][0] or 0
    routes = {(r.method, r.resource.canonical) for r in health_server.construire_app().router.routes()
              if r.resource.canonical.startswith("/tableau") and r.method in ("GET", "POST")}
    assert LIBRES <= routes, "la liste blanche décrit des adresses qui existent"
    noms_site = {m: sorted(n for n, d in {**tableau.ROUTES, **tableau._INTERNES}.items() if m in d) for m in ("GET", "POST")}
    assert "direct/candidat" in noms_site["GET"], "la lecture du direct est une adresse du site de la direction"
    actions = ("clan_ajouter", "clan_retirer", "moderer", "ticket_fermer", "candidature", "debannir")
    essais = []
    for methode, gabarit in sorted(routes - LIBRES):
        if gabarit == "/tableau/espace/api/{nom}":
            essais += [(methode, f"/tableau/espace/api/{n}", {"ticket": "60", "id": "x"}) for n in noms_site[methode] + ["inconnue/x"]]
        elif gabarit == "/tableau/equipage/api/{nom}":
            essais += [(methode, f"/tableau/equipage/api/{n}", {}) for n in [*site_equipage.LECTURES, "inconnue"]]
        elif gabarit == "/tableau/espace/action":
            essais += [(methode, gabarit, {"action": a, "membre": str(TOBIAS), "ticket": 60}) for a in actions]
        elif gabarit == "/tableau/espace/sync":
            essais.append((methode, gabarit, {"ops": [{"op_id": "op-candidat-0001", "api": "recrutement/corriger",
                                                       "corps": {"envoi": 1, "question": "x", "juste": True}}]}))
        elif gabarit == "/tableau/{jeton}":
            essais.append((methode, "/tableau/" + tableau.jeton(1, TOBIAS, "candidat"), {}))
        elif gabarit == "/tableau/espace/media/{media}":
            essais.append((methode, "/tableau/espace/media/avatar/1000001", {}))
        elif "{" in gabarit:
            pytest.fail(f"adresse nouvelle et non couverte par ce test : {methode} {gabarit} — l'ajouter ici")
        else:
            essais.append((methode, gabarit, {}))
    assert len(essais) >= 50, len(essais)
    for methode, chemin, corps in essais:
        st, rep, _h = local.requete(methode, chemin, h, corps, ecrire=(methode == "POST"),
                                    params={"id": str(TOBIAS), "q": "a", "ticket": "60", "envoi": "1", "quoi": "journal",
                                            "onglet": "onglet-candidat-1"} if methode == "GET" else None)
        assert st == 403, f"{methode} {chemin} → {st} : {_texte(rep)[:200]}"
        texte = _texte(rep)
        assert "Tobias" not in texte and not any(s in texte for s in SECRETS), f"{methode} {chemin} laisse passer des données"
    #  La page de la direction : « réservé » (cookie recopié : on lui montre SON questionnaire), ou le lien expiré.
    st, rep, _h = local.requete("GET", "/tableau/espace/", h)
    assert st == 403
    assert ("/tableau/candidature/" in _texte(rep)) if mode != "son_cookie" else ("Ce lien n'est plus valable" in _texte(rep))
    #  Le site de l'équipage : refusé aussi (le rôle du clan ne suffit jamais à une session « candidat »).
    assert local.requete("GET", "/tableau/equipage/", h)[0] == 403
    #  Sa liste blanche, elle, répond — avec SON cookie seulement.
    if mode == "son_cookie":
        assert local.requete("GET", "/tableau/candidature/", h)[0] == 200
        assert local.lire("questionnaire", h)[0] == 200
    else:
        assert local.requete("GET", "/tableau/candidature/", h)[0] == 403, "le cookie de la direction n'ouvre pas sa page"
        assert local.lire("questionnaire", h)[0] == 403
    assert local.requete("GET", "/tableau/candidature", h)[2]["Location"] == "/tableau/candidature/"
    assert local.requete("GET", "/tableau/espace/s/candidature.js", h)[0] == 200
    #  RIEN n'a été écrit (sa propre lecture garde au plus sa dernière visite) ; au journal, au plus la tentative refusée
    #  (Sécurité), une seule fois.
    apres = _empreinte_base(local)
    changes = sorted(t for t in apres if apres[t] != avant.get(t))
    assert changes in ([], ["candidature_etat"]), f"une session « candidat » a modifié la base : {changes}"
    nouveaux = local.sql("SELECT categorie, type FROM registre WHERE id > ?", (journal_avant,))
    if mode == "son_cookie":
        assert not [x for x in nouveaux if x[0] == "Sécurité"], nouveaux
    else:
        assert nouveaux.count(("Sécurité", "site.hors_portee")) == 1, nouveaux
        texte = local.sql("SELECT texte FROM registre WHERE type='site.hors_portee' ORDER BY id DESC LIMIT 1")[0][0]
        assert texte.startswith("Questionnaire en ligne : Tobias a demandé une page qui ne lui est pas ouverte"), texte


def test_C1b_la_websocket_et_le_direct_refusent_le_candidat(local):
    import tableau
    h = local.candidat("ticket=60")
    sid = h["Cookie"].split("=", 1)[1]

    async def socket(cookie):
        try:
            ws = await local.client.ws_connect("/tableau/espace/direct",
                                               headers={"Cookie": cookie, "Origin": "http://localhost:8790"})
        except aiohttp.WSServerHandshakeError as ex:
            return ex.status
        await ws.close()
        return 101
    assert local.faire(socket(h["Cookie"])) == 403
    assert local.faire(socket(f"{tableau.COOKIE}={sid}")) == 403
    for cookie in (h["Cookie"], f"{tableau.COOKIE}={sid}", local.kolax_equipage["Cookie"]):
        st, _d = local.api("direct/candidat", {"Cookie": cookie}, {"ticket": "60"})
        assert st == 403, cookie
    #  La tête, elle, lit le direct (par ticket, et par envoi).
    st, d = local.api("direct/candidat", local.tete, {"ticket": "60"})
    assert st == 200 and d["ticket"] == 60
    st2, d2 = local.api("direct/candidat", local.tete, {"envoi": str(d["envoi"])})
    assert st2 == 200 and d2["envoi"] == d["envoi"]
    assert local.api("direct/candidat", local.tete, {"ticket": "abc"})[0] == 400
    assert local.api("direct/candidat", local.tete, {"envoi": "999999"})[0] == 404


# ═══════════════════════════════════════════════════════════════════════════════
#  C2 — rien de secret ne sort vers le candidat
# ═══════════════════════════════════════════════════════════════════════════════

def test_C2_aucune_reponse_attendue_aucune_etape_fermee_aucun_nom_de_l_equipe(local, sans_cadence):
    import questionnaire
    ids = _questions_secretes(local)
    tid, eid = local.ticket(1022, etapes=3, ouverte=1, fiche=1, questions=ids)
    e = local.faire(questionnaire._envoi(eid))
    assert len(e["questions"]) == 6
    fermees = [q["question"] for q in e["questions"] if questionnaire.etape_de_question(q) > 1]
    assert len(fermees) == 4
    local.reponses_vues.clear()
    h = local.candidat(f"ticket={tid}")
    #  Toutes ses lectures et écritures, réussies ou refusées.
    st, d = local.lire("questionnaire", h)
    assert st == 200 and d["portes"] == {"mode": "etapes", "ouverte": 1, "envoyee": 0, "fiche": 1, "total": 3, "courante": 1}
    assert [x["numero"] for x in d["etapes"]] == [1], "les étapes suivantes sont comptées, jamais montrées"
    une = d["etapes"][0]["questions"]
    assert len(une) == 2 and all(set(q) == {"rang", "question"} for q in une)
    assert local.ecrire("saisie", {"rang": une[0]["rang"], "texte": "je tape", "etape": 1}, h)[0] == 200
    assert local.ecrire("brouillon", {"reponses": {str(une[0]["rang"]): "je tape encore"}}, h)[0] == 200
    assert local.ecrire("brouillon", {"reponses": {str(e["questions"][-1]["rang"]): "étape fermée"}}, h)[0] == 400
    assert local.ecrire("envoyer_etape", {"etape": 2, "reponses": {}}, h)[0] == 409
    assert local.ecrire("envoyer", {"reponses": {}}, h)[0] == 409
    assert local.ecrire("presence", {"vue": "ouverte", "etape": 1}, h)[0] == 200
    assert local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(une[0]["rang"]): "x"}}, h)[0] == 400
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(q["rang"]): f"Réponse {q['rang']}" for q in une}}, h)
    assert st == 200 and rep["etat"] == "attente", rep
    local.lire("questionnaire", h)
    for chemin in ("/tableau/candidature/", "/tableau/candidature/api/inconnue"):
        local.reponses_vues.append(local.requete("GET", chemin, h)[1])
    tout = "\n".join(_texte(x) for x in local.reponses_vues)
    assert len(local.reponses_vues) >= 12 and "Question témoin numéro 0" in tout
    for s in SECRETS:
        assert s not in tout, f"« {s} » sort vers le candidat"
    for q in fermees:
        assert q not in tout, "une question d'une étape pas encore ouverte sort vers le candidat"
    for nom in EQUIPE:
        assert nom not in tout, f"le nom de l'équipe « {nom} » sort vers le candidat"
    for cle in ('"envoye_par"', '"attendue"', '"variantes"', '"indication"', '"correction"', '"reponse":'):
        assert cle not in tout, cle
    #  Les pages d'erreur du lien (inconnu, sans session) : rien non plus.
    for chemin in ("/tableau/candidature/" + "x" * 40, "/tableau/candidature/"):
        corps = _texte(local.requete("GET", chemin)[1])
        assert not any(s in corps for s in SECRETS) and "Question témoin" not in corps
    #  La direction, elle, voit tout ce qu'il écrit (le direct) — jamais la réponse attendue là non plus.
    st, dd = local.api("direct/candidat", local.tete, {"ticket": str(tid)})
    assert st == 200 and len(dd["etapes"]) == 3 and not any(s in json.dumps(dd) for s in SECRETS)


# ═══════════════════════════════════════════════════════════════════════════════
#  C3 — SON envoi seulement
# ═══════════════════════════════════════════════════════════════════════════════

def test_C3_la_liaison_a_son_envoi(local, sans_cadence):
    import candidature_site
    import questionnaire
    import tableau
    t1, e1 = local.ticket(1005)
    t2, e2 = local.ticket(1007)
    h1 = local.candidat(f"ticket={t1}")
    #  Un autre ticket, un autre envoi en paramètre : ignorés — sa lecture reste la sienne.
    st, d = local.lire("questionnaire", h1, params={"ticket": str(t2), "envoi": str(e2)})
    assert st == 200 and d["envoi"] == e1
    rang = d["etapes"][0]["questions"][0]["rang"]
    assert local.ecrire("brouillon", {"reponses": {str(rang): "à moi"}, "envoi": e2, "ticket": t2}, h1)[0] == 200
    assert local.sql("SELECT envoi_id FROM candidature_brouillons WHERE texte='à moi'") == [(e1,)], "jamais l'envoi d'un autre"

    def lien(uid, ticket):
        return local.faire(candidature_site.lien_ticket(Obj(guild=local.g, user=local.g.get_member(uid)), ticket))
    #  Le lien : l'ouvreur seulement ; un autre membre, la tête elle-même : refusés.
    url, refus = lien(1005, t1)
    assert url and url.startswith("http://localhost:8790/tableau/candidature/") and refus == ""
    j = tableau.lire_jeton(url.rsplit("/", 1)[1])
    assert j["p"] == "candidat" and j["u"] == 1005 and candidature_site.FORMAT_NONCE.fullmatch(j["n"]).group(1) == str(e1)
    seul = local.faire(_texte_registre("candidature.lien.seul"))
    for autre in (1007, FONDATEUR):
        assert lien(autre, t1) == (None, seul)
    #  Un lien FORGÉ (bien signé, mais lié à l'envoi d'un autre) : refusé à l'entrée.
    forge = tableau.jeton(1, 1007, "candidat", nonce=f"e{e1}x" + "A" * 12)
    assert local.entrer("/tableau/candidature/" + forge)[0] is None
    #  Ouvert : la session est liée à CET envoi ; le même lien rouvert ailleurs : refusé ; dans le même navigateur : passe.
    chemin = "/tableau/candidature/" + url.rsplit("/", 1)[1]
    hl, arrivee = local.entrer(chemin)
    assert arrivee == "/tableau/candidature/" and local.lire("questionnaire", hl)[1]["envoi"] == e1
    st, rep, _h = local.requete("GET", chemin)
    assert st == 403 and "déjà servi" in _texte(rep)
    st, _r, hd = local.requete("GET", chemin, hl)
    assert st == 303 and hd["Location"] == "/tableau/candidature/"
    #  Un lien de la direction ici, un lien de candidat à l'entrée de la direction, un lien expiré : refusés.
    for faux in ("/tableau/candidature/" + tableau.jeton(1, FONDATEUR, "tout"), "/tableau/" + url.rsplit("/", 1)[1],
                 "/tableau/candidature/" + tableau.jeton(1, 1005, "candidat", maintenant=time.time() - 2 * tableau.DUREE,
                                                         nonce=f"e{e1}x" + "B" * 12)):
        h_, (st, _t) = local.entrer(faux)
        assert h_ is None and st == 403, faux
    #  Un envoi REMPLACÉ (la direction renvoie d'autres questions) : l'ancienne session ne voit plus rien et n'écrit plus ;
    #  le nouveau lien mène au nouvel envoi (deux envois : le second seulement).
    st, rep = local.faire(questionnaire.envoyer(local.g, t1, local.g.get_member(FONDATEUR), {}, depuis="renvoi"))
    assert st == 200
    st, d = local.lire("questionnaire", h1)
    assert st == 200 and d["etat"] == "remplace" and "etapes" not in d and "reponses" not in d
    assert local.ecrire("brouillon", {"reponses": {str(rang): "encore"}}, h1)[0] == 409
    assert local.ecrire("saisie", {"rang": rang, "texte": "encore"}, h1)[0] == 409
    assert local.ecrire("envoyer", {"reponses": {str(rang): "encore"}}, h1)[0] == 409
    url2, _r = lien(1005, t1)
    assert url2 and candidature_site.FORMAT_NONCE.fullmatch(tableau.lire_jeton(url2.rsplit("/", 1)[1])["n"]).group(1) \
        == str(rep["envoi"])
    h1b, _a = local.entrer("/tableau/candidature/" + url2.rsplit("/", 1)[1])
    assert local.lire("questionnaire", h1b)[1]["envoi"] == rep["envoi"]
    #  Le ticket FERMÉ : plus rien — ni questionnaire, ni écriture, ni lien.
    h2 = local.candidat(f"ticket={t2}")
    local.sql("UPDATE tickets SET status='closed' WHERE id=?", (t2,))
    st, d = local.lire("questionnaire", h2)
    assert st == 200 and d["etat"] == "ferme" and "etapes" not in d
    assert local.ecrire("brouillon", {"reponses": {"1": "x"}}, h2)[0] == 409
    assert local.ecrire("envoyer", {"reponses": {"1": "x"}}, h2)[0] == 409
    assert lien(1007, t2)[0] is None
    #  Suspendu : ni lien, ni session.
    m = local.g.get_member(1005)
    local.faire(tableau.suspendre(local.g, m, "essai"))
    try:
        url3, refus3 = lien(1005, t1)
        assert url3 is None and "suspendu" in refus3
        assert local.lire("questionnaire", h1b)[0] == 403
    finally:
        local.sql("DELETE FROM tableau_blocages WHERE user_id=?", (1005,))
        tableau._blocages.pop((1, 1005), None)


# ═══════════════════════════════════════════════════════════════════════════════
#  C4 — l'envoi : les mêmes états que le formulaire Discord
# ═══════════════════════════════════════════════════════════════════════════════

class _Reponse:
    def __init__(self):
        self.fait, self.envois = False, []

    def is_done(self):
        return self.fait

    async def defer(self, **kw):
        self.fait = True

    async def send_message(self, *a, **kw):
        self.fait = True
        self.envois.append(kw)

    async def send_modal(self, modal):
        self.fait = True
        self.envois.append({"modal": modal})


def _inter(g, membre, salon=None):
    i = Obj(guild=g, user=membre, channel=salon, response=_Reponse(), suivis=[])

    async def suivre(*a, **kw):
        i.suivis.append(kw)
    i.followup = Obj(send=suivre)
    return i


def _etat_final(local, tid, eid) -> dict:
    import questionnaire
    e = local.faire(questionnaire._envoi(eid))
    s = local.faire(questionnaire._suivi(1, tid))
    d = local.faire(questionnaire.dossier(local.g, tid))
    envoi = next(x for x in d["envois"] if x["id"] == eid)
    vu = json.loads(_texte(local.requete("GET", f"/tableau/demo/discord?ticket={tid}")[1]))
    return {"statut": e["statut"], "repondu": bool(e["repondu_le"]), "etape": s["etape"], "dossier_etape": d["etape"],
            "reponses": local.sql("SELECT COUNT(*), MIN(guild_id) FROM recrutement_reponses WHERE envoi_id=?", (eid,))[0],
            "bilan": {k: envoi["bilan"][k] for k in ("total", "repondues", "corrigees")},
            "historique": [x["quoi"] for x in d["decisions"]],
            "carte_equipe": any("Réponses reçues" in m["texte"] and "Corriger sur le site" in m["boutons"] and m["reecrit"]
                                for m in vu["messages"]),
            "carte_candidat": any("Réponses envoyées" in m["texte"] and not m["boutons"] and m["reecrit"]
                                  for m in vu["messages"]),
            "peut_corriger": d["peut"]["corriger"]}


def test_C4_l_envoi_du_site_et_le_formulaire_discord_donnent_les_memes_etats(local, sans_cadence):
    import candidature_site
    import questionnaire
    ta, ea = local.ticket(1010)
    tb, eb = local.ticket(1013)
    #  A — le formulaire Discord, page par page (le VRAI `soumettre_page`).
    e = local.faire(questionnaire._envoi(ea))
    ch, _tk = local.faire(questionnaire._ticket_ouvert(local.g, ta))
    for page in range(1, questionnaire.nb_pages(len(e["questions"])) + 1):
        valeurs = {int(q["rang"]): f"  Réponse   {q['rang']} " for q in questionnaire.questions_de_la_page(e["questions"], page)}
        local.faire(questionnaire.soumettre_page(_inter(local.g, local.g.get_member(1010), ch), ea, page, valeurs))
    #  B — le questionnaire en ligne : des brouillons d'abord (JAMAIS des réponses), puis l'envoi.
    h = local.candidat(f"ticket={tb}")
    st, d = local.lire("questionnaire", h)
    rangs = [q["rang"] for x in d["etapes"] for q in x["questions"]]
    assert local.ecrire("brouillon", {"reponses": {str(r): f"brouillon {r}" for r in rangs}}, h)[0] == 200
    assert local.sql("SELECT COUNT(*) FROM recrutement_reponses WHERE envoi_id=?", (eb,)) == [(0,)], "un brouillon n'est pas une réponse"
    avant = local.faire(questionnaire.dossier(local.g, tb))
    assert avant["etape"] == "etape2" and next(x for x in avant["envois"] if x["id"] == eb)["bilan"]["repondues"] == 0
    assert not avant["peut"]["corriger"]
    assert any(o["ticket"] == tb and o["envoi"]["bilan"]["repondues"] == 0 for o in local.faire(questionnaire.suivi(local.g))["ouverts"])
    assert local.faire(questionnaire._bilan_courant(local.faire(questionnaire._suivi(1, tb)))) is None, "rien à corriger avant l'envoi"
    manque = local.ecrire("envoyer", {"reponses": {str(r): "x" for r in rangs[:-1]}}, h)
    assert manque[0] == 400 and manque[1]["manquent"] == [rangs[-1]]
    st, rep = local.ecrire("envoyer", {"reponses": {str(r): f"  Réponse   {r} " for r in rangs}}, h)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    assert local.sql("SELECT COUNT(*) FROM candidature_brouillons WHERE envoi_id=?", (eb,)) == [(0,)], "les brouillons partent"
    a, b = _etat_final(local, ta, ea), _etat_final(local, tb, eb)
    assert a == b, (a, b)
    assert b["statut"] == "repondu" and b["etape"] == "reponses" and b["reponses"] == (len(rangs), 1)
    assert b["carte_equipe"] and b["carte_candidat"] and b["peut_corriger"]
    assert b["historique"] == ["questionnaire", "reponses"]
    assert local.sql("SELECT DISTINCT candidat_id FROM recrutement_reponses WHERE envoi_id=?", (eb,)) == [(1013,)]
    #  Les textes : la même normalisation que le formulaire (espaces écrasés).
    assert local.sql("SELECT texte FROM recrutement_reponses WHERE envoi_id=? AND rang=1", (eb,)) == \
        local.sql("SELECT texte FROM recrutement_reponses WHERE envoi_id=? AND rang=1", (ea,)) == [("Réponse 1",)]
    #  La correction du site fonctionne sur les réponses venues du site.
    q = local.faire(questionnaire._envoi(eb))["questions"][0]
    st, c = local.faire(questionnaire.corriger(local.g, local.g.get_member(DIRECTION), {"envoi": eb, "question": q["id"], "juste": True}))
    assert st == 200 and c["bilan"]["corrigees"] == 1
    #  Rouvrir le lien : « déjà envoyé » (lecture seule), et plus aucune écriture.
    st, d = local.lire("questionnaire", h)
    assert d["etat"] == "envoye" and d["envoye_le"] and d["reponses"]["1"] == "Réponse 1"
    assert local.ecrire("envoyer", {"reponses": {str(r): "x" for r in rangs}}, h)[0] == 409
    assert local.ecrire("brouillon", {"reponses": {"1": "x"}}, h)[0] == 409
    assert local.sql("SELECT texte FROM recrutement_reponses WHERE envoi_id=? AND rang=1", (eb,)) == [("Réponse 1",)]
    url, refus = local.faire(candidature_site.lien_ticket(Obj(guild=local.g, user=local.g.get_member(1013)), tb))
    assert url is None and refus == local.faire(_texte_registre("candidature.lien.deja"))


def test_C4b_un_questionnaire_commence_sur_discord_se_finit_sur_le_site(local, sans_cadence):
    """Une page du formulaire Discord envoyée (statut « en_cours »), le reste sur le site : la page reprend ce qui est déjà
    là, l'envoi final garde les réponses de Discord — et ferme une seule fois."""
    import questionnaire
    tid, eid = local.ticket(1016)
    e = local.faire(questionnaire._envoi(eid))
    assert questionnaire.nb_pages(len(e["questions"])) >= 2
    ch, _tk = local.faire(questionnaire._ticket_ouvert(local.g, tid))
    page1 = {int(q["rang"]): f"Discord {q['rang']}" for q in questionnaire.questions_de_la_page(e["questions"], 1)}
    local.faire(questionnaire.soumettre_page(_inter(local.g, local.g.get_member(1016), ch), eid, 1, page1))
    assert local.faire(questionnaire._envoi(eid))["statut"] == "en_cours"
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    assert st == 200 and d["etat"] == "ouvert" and d["reponses"]["1"] == "Discord 1"
    tous = {str(q["rang"]): d["reponses"].get(str(q["rang"])) or f"Site {q['rang']}" for x in d["etapes"] for q in x["questions"]}
    assert local.ecrire("envoyer", {"reponses": tous}, h)[0] == 200
    local.annonces()
    assert local.sql("SELECT texte FROM recrutement_reponses WHERE envoi_id=? AND rang=1", (eid,)) == [("Discord 1",)]
    assert local.faire(questionnaire._envoi(eid))["statut"] == "repondu"
    #  Fermé une seule fois : une ligne « réponses » à l'historique du ticket (le journal, lui, écarte les doublons de
    #  texte — la démonstration du site local a déjà ses propres candidats).
    assert local.sql("SELECT COUNT(*) FROM recrutement_historique WHERE ticket_id=? AND quoi='reponses'", (tid,)) == [(1,)]


# ═══════════════════════════════════════════════════════════════════════════════
#  C5 — le passage d'étape
# ═══════════════════════════════════════════════════════════════════════════════

def test_C5_une_etape_ouverte_a_la_fois_envoyee_une_fois(local, sans_cadence):
    import questionnaire
    tid, eid = local.ticket(1019, etapes=3, ouverte=1, fiche=1)
    avant = _dernier_id(local)
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    r1 = [q["rang"] for q in d["etapes"][0]["questions"]]
    tous = [int(q["rang"]) for q in local.faire(questionnaire._envoi(eid))["questions"]]
    r_fermes = [r for r in tous if r not in r1]
    assert r1 and r_fermes
    #  Une question d'une étape pas encore ouverte : refusée partout.
    assert local.ecrire("saisie", {"rang": r_fermes[0], "texte": "triche"}, h)[0] == 400
    assert local.ecrire("brouillon", {"reponses": {str(r_fermes[0]): "triche"}}, h)[0] == 400
    #  Un numéro d'étape forgé (pas ouverte, nul, négatif, texte, booléen, absent, énorme) : refusé.
    for etape in (2, 3, 0, -1, "deux", True, None, 99, "1.0", [1]):
        st, rep = local.ecrire("envoyer_etape", {"etape": etape, "reponses": {str(r): "x" for r in r1}}, h)
        assert st == 409 and rep["erreur"] == "Cette étape n'est pas ouverte.", (etape, st, rep)
    #  L'étape 1, avec une réponse d'une autre étape glissée dedans : refusée ; une réponse vide : refusée.
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {**{str(r): "x" for r in r1}, str(r_fermes[0]): "y"}}, h)
    assert st == 400
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {**{str(r): "x" for r in r1}, str(r1[-1]): "   "}}, h)
    assert st == 400 and rep["manquent"] == [r1[-1]]
    #  Le tout-en-un d'un envoi d'avant : refusé ici.
    assert local.ecrire("envoyer", {"reponses": {str(r): "x" for r in tous}}, h)[0] == 409
    assert local.sql("SELECT COUNT(*) FROM recrutement_reponses WHERE envoi_id=?", (eid,)) == [(0,)]
    #  L'étape 1 : envoyée une fois ; la seconde fois (double clic, second onglet) : refusée, rien de réécrit.
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): f"Étape 1 · {r}" for r in r1}}, h)
    assert st == 200 and rep["etat"] == "attente" and rep["portes"]["envoyee"] == 1, rep
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): "écrasé ?" for r in r1}}, h)
    assert st == 409 and rep["etat"] == "attente"
    assert local.sql("SELECT COUNT(*) FROM recrutement_reponses WHERE envoi_id=? AND texte LIKE 'Étape 1 · %'", (eid,)) == [(len(r1),)]
    assert local.sql("SELECT COUNT(*) FROM recrutement_reponses WHERE envoi_id=? AND texte='écrasé ?'", (eid,)) == [(0,)]
    #  En attente : plus aucune écriture ; la page dit où il en est.
    assert local.ecrire("brouillon", {"reponses": {str(r1[0]): "encore"}}, h)[0] == 409
    assert local.ecrire("saisie", {"rang": r1[0], "texte": "encore"}, h)[0] == 409
    st, d = local.lire("questionnaire", h)
    assert d["etat"] == "attente" and [x["envoyee"] for x in d["etapes"]] == [True] and d["portes"]["total"] == 3
    assert d["reponses"][str(r1[0])] == f"Étape 1 · {r1[0]}"
    st, rep = local.ecrire("presence", {"vue": "ouverte"}, h)
    assert rep["etat"] == "attente" and rep["portes"]["ouverte"] == 1
    assert local.faire(questionnaire._envoi(eid))["statut"] == "en_cours" and \
        local.faire(questionnaire._suivi(1, tid))["etape"] == "etape2", "l'envoi reste ouvert : la direction décide"
    #  La direction ouvre l'étape 2 : la page la montre (l'étape 1 en lecture seule).
    local.ouvrir_etape(eid)
    st, d = local.lire("questionnaire", h)
    assert d["etat"] == "ouvert"
    assert [(x["numero"], x["envoyee"], x["courante"]) for x in d["etapes"]] == [(1, True, False), (2, False, True)]
    r2 = [q["rang"] for q in d["etapes"][1]["questions"]]
    assert local.ecrire("brouillon", {"reponses": {str(r1[0]): "réécrire l'étape 1 ?"}}, h)[0] == 400, "une étape envoyée est figée"
    assert local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): "x" for r in r1}}, h)[0] == 409
    assert local.ecrire("envoyer_etape", {"etape": 2, "reponses": {str(r): f"Étape 2 · {r}" for r in r2}}, h)[0] == 200
    local.ouvrir_etape(eid)
    st, d = local.lire("questionnaire", h)
    r3 = [q["rang"] for q in d["etapes"][2]["questions"]]
    st, rep = local.ecrire("envoyer_etape", {"etape": 3, "reponses": {str(r): f"Étape 3 · {r}" for r in r3}}, h)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    #  La dernière étape clôt l'envoi comme le formulaire Discord.
    assert local.faire(questionnaire._envoi(eid))["statut"] == "repondu"
    assert local.faire(questionnaire._suivi(1, tid))["etape"] == "reponses"
    assert local.sql("SELECT COUNT(*) FROM recrutement_reponses WHERE envoi_id=?", (eid,)) == [(len(tous),)]
    fin = _etat_final(local, tid, eid)
    #  Les étapes reçues (l'historique et le journal de l'équipe du recrutement : la fiche est l'étape 1 du candidat).
    assert fin["carte_equipe"] and fin["carte_candidat"]
    assert fin["historique"] == ["questionnaire", "etape_recue", "etape_recue", "reponses"], fin["historique"]
    journal = _journal(local, avant, "recrutement.etape_recue", 1019)
    assert len(journal) == 2 and "étape 2 reçue" in journal[0] and "étape 3 reçue" in journal[1], journal
    assert len(_journal(local, avant, "recrutement.reponses", 1019)) == 1
    st, d = local.lire("questionnaire", h)
    assert d["etat"] == "envoye" and [x["envoyee"] for x in d["etapes"]] == [True, True, True]


def test_C5b_envoyer_etape_directement(local):
    """`questionnaire.envoyer_etape` (le contrat commun) : l'étape ouverte seulement, une fois, toutes ses réponses."""
    import candidature_site
    import questionnaire
    tid, eid = local.ticket(1004, etapes=2, ouverte=1)
    e = local.faire(candidature_site.envoi_complet(eid))
    r1 = {int(q["rang"]) for q in e["questions"] if questionnaire.etape_de_question(q) == 1}
    r2 = {int(q["rang"]) for q in e["questions"] if questionnaire.etape_de_question(q) == 2}
    assert r1 and r2 and questionnaire.derniere_etape(e) == 2
    t = int(time.time())

    def faire(etape, reps):
        return local.faire(questionnaire.envoyer_etape(e, t, etape, reps, g=local.g))
    assert faire(2, {r: "x" for r in r2}) is False, "pas ouverte"
    assert faire(1, {r: "x" for r in list(r1)[:-1]}) is False, "une réponse manque"
    assert faire(1, {**{r: "x" for r in r1}, **{r: "y" for r in r2}}) is False, "une autre étape glissée dedans"
    assert faire(1, {r: " " for r in r1}) is False, "vide"
    assert faire("1; DROP TABLE x", {r: "x" for r in r1}) is False
    assert faire(True, {r: "x" for r in r1}) is False, "un booléen n'est pas un numéro"
    assert local.sql("SELECT COUNT(*) FROM recrutement_reponses WHERE envoi_id=?", (eid,)) == [(0,)]
    assert faire(1, {r: "ok" for r in r1}) is True
    assert faire(1, {r: "encore" for r in r1}) is False, "le premier envoi compte"
    assert {x for (x,) in local.sql("SELECT texte FROM recrutement_reponses WHERE envoi_id=?", (eid,))} == {"ok"}
    assert local.faire(questionnaire._envoi(eid))["statut"] == "en_cours"
    local.ouvrir_etape(eid)
    assert faire(2, {r: "fin" for r in r2}) is True
    assert local.faire(questionnaire._envoi(eid))["statut"] == "repondu"
    assert faire(2, {r: "fin" for r in r2}) is False
    #  Un envoi d'avant (`etape_ouverte` = 0) : jamais par cette porte.
    _t, eid0 = local.ticket(1006)
    e0 = local.faire(candidature_site.envoi_complet(eid0))
    assert e0["etape_ouverte"] == 0 and local.faire(questionnaire.envoyer_etape(
        e0, t, 1, {int(q["rang"]): "x" for q in e0["questions"]}, g=local.g)) is False
    assert local.faire(questionnaire._envoi(eid0))["statut"] == "envoye"


def test_C5c_un_envoi_d_avant_ne_change_pas(local, sans_cadence):
    """`etape_ouverte` = 0 : tout est ouvert (toutes les étapes déclarées, ou une seule), un seul envoi à la fin."""
    t1, e1 = local.ticket(1009)
    h = local.candidat(f"ticket={t1}")
    st, d = local.lire("questionnaire", h)
    assert d["portes"]["mode"] == "unique" and len(d["etapes"]) == 1 and d["etapes"][0]["envoyee"] is False
    assert local.ecrire("envoyer_etape", {"etape": 1, "reponses": {"1": "x"}}, h)[0] == 409
    #  Un envoi d'avant, mais avec des étapes déclarées : toutes visibles, toutes écrites, envoyées ensemble.
    t2, e2 = local.ticket(1012, etapes=3, ouverte=0)
    h2 = local.candidat(f"ticket={t2}")
    st, d = local.lire("questionnaire", h2)
    assert d["portes"]["mode"] == "unique" and [x["numero"] for x in d["etapes"]] == [1, 2, 3]
    derniere = d["etapes"][2]["questions"][0]["rang"]
    assert local.ecrire("brouillon", {"reponses": {str(derniere): "étape 3 tout de suite"}}, h2)[0] == 200
    tous = {str(q["rang"]): "x" for x in d["etapes"] for q in x["questions"]}
    st, rep = local.ecrire("envoyer", {"reponses": tous}, h2)
    assert st == 200 and rep["etat"] == "envoye"


def test_C5d_les_etapes_d_un_envoi():
    import candidature_site as C
    qs = [{"rang": k, "question": f"Q{k}", "reponse": "secret", "etape": e} for k, e in ((1, 1), (2, 1), (3, 2), (4, 3))]
    assert [(x["numero"], [q["rang"] for q in x["questions"]]) for x in C.etapes_de(qs, [])] == [(1, [1, 2]), (2, [3]), (3, [4])]
    assert all(set(q) == {"rang", "question"} for x in C.etapes_de(qs, []) for q in x["questions"])
    sans = [{"rang": k, "question": f"Q{k}"} for k in (1, 2, 3)]
    assert [(x["numero"], len(x["questions"])) for x in C.etapes_de(sans, "[]")] == [(1, 3)], "un envoi d'avant : une étape"
    assert C.etapes_de(sans, "pas du json")[0]["numero"] == 1
    decl = json.dumps([{"numero": 2, "titre": "Deux", "consigne": "C2"}, {"numero": 1, "titre": "Un"}, {"numero": "x"},
                       {"numero": 1, "titre": "doublon"}, {"numero": 9, "titre": "vide"}, {"numero": True}, "pas un objet"])
    out = C.etapes_de(qs, decl)
    assert [(x["numero"], x["titre"]) for x in out] == [(1, "Un"), (2, "Deux"), (3, "")], "triées, sans doublon ni étape vide"
    assert C.etapes_de([{"rang": 1, "question": "Q", "etape": 77}], [{"numero": 1, "titre": "Un"}])[0]["numero"] == 1
    p = C.portes_de({"etape_ouverte": 2, "etape_envoyee": 1, "etape_fiche": 1}, out)
    assert p == {"mode": "etapes", "ouverte": 2, "envoyee": 1, "fiche": 1, "total": 3, "derniere": 3, "courante": 2}
    assert C.portes_de({"etape_ouverte": 2, "etape_envoyee": 2}, out)["courante"] == 0
    assert C.portes_de({"etape_ouverte": 0}, out)["mode"] == "unique"
    assert C.portes_de({"etape_ouverte": 9, "etape_envoyee": -3}, out)["ouverte"] == 3


def test_C5e_la_derniere_etape_gardee_mais_pas_close_se_clot_a_la_lecture(local):
    """Une coupure entre l'écriture de la dernière étape et la clôture : la lecture suivante clôt l'envoi — une fois."""
    import questionnaire
    tid, eid = local.ticket(1015, etapes=2, ouverte=2)
    e = local.faire(questionnaire._envoi(eid))
    local.sql("UPDATE recrutement_envois SET etape_envoyee=2, statut='en_cours' WHERE id=?", (eid,))
    for q in e["questions"]:
        local.sql("INSERT INTO recrutement_reponses (envoi_id, rang, guild_id, candidat_id, texte, recu_le)"
                  " VALUES (?,?,?,?,?,?)", (eid, int(q["rang"]), 1, 1015, "gardée", int(time.time())))
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    assert st == 200 and d["etat"] == "envoye"
    assert local.faire(questionnaire._envoi(eid))["statut"] == "repondu"
    local.lire("questionnaire", h)
    local.annonces()
    assert local.sql("SELECT COUNT(*) FROM recrutement_historique WHERE ticket_id=? AND quoi='reponses'", (tid,)) == [(1,)]


def test_C5f_les_cadences_et_les_bornes(local):
    import candidature_site
    import questionnaire
    tid, eid = local.ticket(1014)
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    rang = d["etapes"][0]["questions"][0]["rang"]
    #  Deux envois par seconde au plus : le troisième attend (429), sans rien écrire.
    statuts = [local.ecrire("envoyer", {"reponses": {str(rang): "x"}}, h)[0] for _ in range(3)]
    assert statuts == [400, 400, 429], statuts
    #  Trois brouillons par seconde : le quatrième attend (la page réessaie).
    statuts = [local.ecrire("brouillon", {"reponses": {str(rang): f"b{k}"}}, h)[0] for k in range(4)]
    assert statuts == [200, 200, 200, 429], statuts
    #  Six frappes par seconde : au-delà, laissées de côté (la suivante porte le texte entier).
    laisses = [local.ecrire("saisie", {"rang": rang, "texte": "f" * (k + 1)}, h)[1].get("laisse") for k in range(8)]
    assert laisses[:6] == [None] * 6 and laisses[6:] == [True, True], laisses
    #  Les bornes : une réponse coupée à la longueur du formulaire Discord ; un corps trop gros refusé.
    time.sleep(1.05)
    assert local.ecrire("brouillon", {"reponses": {str(rang): "y" * 2000}}, h)[0] == 200
    assert local.sql("SELECT LENGTH(texte) FROM candidature_brouillons WHERE envoi_id=? AND rang=?", (eid, rang)) == \
        [(questionnaire.REPONSE_CANDIDAT_MAX,)]
    st, _r = local.ecrire("saisie", {"rang": rang, "texte": "z" * (candidature_site.CORPS_SAISIE + 10)}, h)
    assert st in (400, 413)
    assert local.ecrire("presence", {"vue": "partout"}, h)[0] == 400
    assert local.ecrire("inconnue", {}, h)[0] == 404
    #  Sans l'en-tête de la page, ou depuis un autre site : refusé avant tout.
    assert local.requete("POST", "/tableau/candidature/api/brouillon", h, {"reponses": {str(rang): "x"}})[0] == 400
    ailleurs = dict(h, **{"X-Tableau": "1", "Origin": "https://ailleurs.exemple", "Sec-Fetch-Site": "cross-site"})
    assert local.requete("POST", "/tableau/candidature/api/brouillon", ailleurs, {"reponses": {str(rang): "x"}})[0] == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  C6 — le chef d'équipe : message privé, bouton persistant, rôle du clan
# ═══════════════════════════════════════════════════════════════════════════════

def _envoi_chef(local, uid, statut="envoye") -> int:
    import questionnaire
    banque = [q for q in local.faire(questionnaire.questions(1)) if questionnaire.posable(q) and q["statut"] == "confirme"][:4]
    qs = [dict({c: q[c] for c in questionnaire._SNAPSHOT}, rang=k + 1, etape=1 if k < 2 else 2) for k, q in enumerate(banque)]
    lignes = local.sql("INSERT INTO recrutement_envois (guild_id, ticket_id, candidat_id, questions, liens, statut, origine,"
                       " envoye_par, cree_le, envoye_le, salon_id, messages, etapes, etape_ouverte, nature, metier) VALUES"
                       " (1,0,?,?,'[]',?,'chef',?,?,?,0,'[]','[]',1,'chef','navigation') RETURNING id",
                       (uid, json.dumps(qs, ensure_ascii=False), statut, FONDATEUR, int(time.time()), int(time.time())))
    return int(lignes[0][0])


def test_C6_le_message_prive_et_son_bouton_persistant(local, monkeypatch):
    import candidature_site
    import tableau
    eid = _envoi_chef(local, MIRA)
    e = local.faire(candidature_site.envoi_complet(eid))
    assert e["nature"] == "chef" and e["metier"] == "navigation" and int(e["ticket_id"]) == 0
    nom = local.faire(candidature_site.nom_metier("navigation"))
    assert nom == "Navigation", "le métier par son nom du catalogue"
    carnet = local.ctx.carnet["mp"]
    n = len(carnet)
    assert local.faire(candidature_site.inviter(local.g, e)) is True
    uid, _c, kw = carnet[n]
    vue = kw["view"]
    comps = _composants(vue)
    assert uid == MIRA and [c["custom_id"] for c in comps if c.get("custom_id")] == [f"cq:rep:{eid}"]
    assert vue.timeout is None
    assert all(isinstance(x, discord.ui.DynamicItem) or not x.is_dispatchable() for x in vue.walk_children()), \
        "une vue mixte, en expirant, effacerait le gabarit global du bouton"
    texte = "\n".join(c["content"] for c in comps if c.get("type") == 10)
    assert f"chef d'équipe · {nom}" in texte and "Répondre au questionnaire" in [c.get("label") for c in comps]
    #  Messages privés fermés, membre parti : False (l'appelant le dit à la direction).
    m = local.g.get_member(MIRA)

    async def ferme(*a, **k):
        raise discord.Forbidden(Obj(status=403, reason="Forbidden"), "Cannot send messages to this user")
    monkeypatch.setattr(m, "send", ferme, raising=False)
    assert local.faire(candidature_site.inviter(local.g, e)) is False
    monkeypatch.undo()
    assert local.faire(candidature_site.inviter(local.g, dict(e, candidat_id=424242))) is False
    assert len(carnet) == n + 1
    #  Le bouton PERSISTANT : son gabarit, enregistré au démarrage du bot, et rebâti depuis son custom_id après un
    #  redémarrage (le module rebranché à neuf) — le clic donne le lien au membre visé seulement, en message privé.
    gabarit = candidature_site.BoutonQuestionnaire.__discord_ui_compiled_template__
    assert gabarit.fullmatch(f"cq:rep:{eid}") and not gabarit.fullmatch("cq:rep:x")
    assert "bot.add_dynamic_items(candidature_site.BoutonQuestionnaire)" in (RACINE / "bot.py").read_text(encoding="utf-8")
    candidature_site.setup(get_db=local.ctx.get_db, cfg=candidature_site._cfg, log=candidature_site._log)
    bouton = local.faire(candidature_site.BoutonQuestionnaire.from_custom_id(None, None, gabarit.fullmatch(f"cq:rep:{eid}")))
    assert bouton.envoi == eid and bouton.custom_id == f"cq:rep:{eid}"

    def cliquer(membre):
        i = Obj(guild=None, user=membre, response=_Reponse())   # un message privé : pas de serveur
        local.faire(bouton.callback(i))
        envoi = i.response.envois[0]
        assert envoi["ephemeral"] is True
        cs = _composants(envoi["view"])
        return [c["url"] for c in cs if c.get("url")], "\n".join(c["content"] for c in cs if c.get("type") == 10)
    liens, _t = cliquer(local.g.get_member(MIRA))
    assert len(liens) == 1
    lien_mira = liens[0].rsplit("/", 1)[1]
    j = tableau.lire_jeton(lien_mira)
    assert (j["p"], j["u"]) == ("candidat", MIRA) and candidature_site.FORMAT_NONCE.fullmatch(j["n"]).group(1) == str(eid)
    #  Un autre membre (du clan, lui aussi) : refusé.
    liens, t = cliquer(local.g.get_member(KOLAX))
    assert not liens and "réservé à la personne" in t
    #  Le lien ouvre la page du chef : son titre, la règle, les mêmes portes.
    hc, arrivee = local.entrer("/tableau/candidature/" + lien_mira)
    assert arrivee == "/tableau/candidature/"
    st, d = local.lire("questionnaire", hc)
    assert d["nature"] == "chef" and d["metier"] == nom and d["portes"]["mode"] == "etapes" and d["portes"]["fiche"] == 0
    assert d["textes"]["candidature.chef.phrase"].startswith("Chaque réponse doit être juste")
    assert [x["numero"] for x in d["etapes"]] == [1] and d["portes"]["total"] == 2
    #  Le direct se branche sur l'ENVOI (aucun ticket).
    st, dd = local.api("direct/candidat", local.tete, {"envoi": str(eid)})
    assert st == 200 and dd["chef"] is True and dd["ticket"] == 0 and dd["metier"] == nom and dd["page"]["vue"] == "ouverte"


def test_C6b_le_role_du_clan_reverifie_a_chaque_requete_et_l_envoi_clos(local, sans_cadence):
    import candidature_site
    import tableau
    eid = _envoi_chef(local, ANNE)
    m = local.g.get_member(ANNE)
    clan = next(r for r in local.g.roles if r.name == "Rell Seas")
    if clan not in m.roles:
        local.faire(m.add_roles(clan))
    hc, _a = local.entrer("/tableau/candidature/" + tableau.jeton(1, ANNE, "candidat", nonce=f"e{eid}x" + "D" * 12))
    assert hc is not None
    st, d = local.lire("questionnaire", hc)
    assert st == 200 and d["etat"] == "ouvert"
    rang = d["etapes"][0]["questions"][0]["rang"]
    assert local.ecrire("saisie", {"rang": rang, "texte": "avant"}, hc)[0] == 200
    #  Le rôle du clan retiré : tout de suite plus rien — ni lecture, ni frappe, ni brouillon, ni envoi, ni lien.
    local.faire(m.remove_roles(clan))
    try:
        assert local.ecrire("saisie", {"rang": rang, "texte": "après"}, hc)[0] == 409, "même dans le cache des frappes"
        st, d = local.lire("questionnaire", hc)
        assert d["etat"] == "ferme" and "etapes" not in d
        assert local.ecrire("brouillon", {"reponses": {str(rang): "après"}}, hc)[0] == 409
        assert local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(rang): "après"}}, hc)[0] == 409
        url, refus = local.faire(candidature_site.lien_envoi(Obj(guild=None, user=m), eid))
        assert url is None and "membres du clan" in refus
        assert local.entrer("/tableau/candidature/" + tableau.jeton(1, ANNE, "candidat", nonce=f"e{eid}x" + "E" * 12))[0] is None
        st, dd = local.api("direct/candidat", local.tete, {"envoi": str(eid)})
        assert dd["etat"] == "ferme"
    finally:
        local.faire(m.add_roles(clan))
    assert local.lire("questionnaire", hc)[1]["etat"] == "ouvert", "le rôle rendu : le questionnaire revient"
    #  L'envoi clos par la direction : terminé.
    local.sql("UPDATE recrutement_envois SET statut='clos' WHERE id=?", (eid,))
    assert local.lire("questionnaire", hc)[1]["etat"] == "ferme"
    assert local.faire(candidature_site.lien_envoi(Obj(guild=None, user=m), eid))[0] is None


# ═══════════════════════════════════════════════════════════════════════════════
#  C7 — le direct : aux seules sessions « tout », au débit borné
# ═══════════════════════════════════════════════════════════════════════════════

def test_C7_le_direct_aux_seules_sessions_de_la_tete_et_au_debit_borne(local, monkeypatch):
    import candidature_site
    import tableau
    tid, eid = local.ticket(1018)
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    rang = d["etapes"][0]["questions"][0]["rang"]
    monkeypatch.setattr(candidature_site, "SAISIES_PAR_S", 1000)   # l'entrée ouverte : on mesure le débit du direct

    async def scenario():
        ws = await local.client.ws_connect("/tableau/espace/direct", headers=dict(local.tete, Origin="http://localhost:8790"))
        await ws.send_json({"t": "bonjour", "page": "recrutement"})
        while (await ws.receive_json(timeout=3)).get("t") != "etat":
            pass
        #  Un onglet de la direction qui interroge (sans WebSocket) : branché, mais jamais destinataire d'une diffusion.
        r = await local.client.get("/tableau/espace/api/direct/etat", params={"onglet": "onglet-http-candidat"},
                                   headers=local.direction)
        assert r.status == 200, await r.text()
        t0 = time.monotonic()
        for k in range(40):
            r = await local.client.post("/tableau/candidature/api/saisie", json={"rang": rang, "texte": "a" * (k + 1), "etape": 1},
                                        headers=dict(h, **ORIGINE))
            assert r.status == 200
        duree = time.monotonic() - t0
        recus, fin = [], time.monotonic() + 1.5
        while time.monotonic() < fin:
            try:
                m = await ws.receive_json(timeout=max(0.05, fin - time.monotonic()))
            except (asyncio.TimeoutError, TimeoutError):
                break
            if m.get("t") == "candidat" and m.get("e") == eid:
                recus.append(m)
        await ws.close()
        return recus, duree, tableau._direct_salles[1].prises.get("h-onglet-http-candidat")
    recus, duree, http = local.faire(scenario())
    textes_ = [m["rep"][str(rang)] for m in recus if str(rang) in (m.get("rep") or {})]
    assert textes_ and textes_[-1] == "a" * 40, "le dernier texte part toujours"
    assert len(recus) <= int(duree / candidature_site.PAS_DIRECT) + 3, (len(recus), duree)
    assert all(m["k"] == tid and set(m) <= {"t", "k", "e", "s", "rep", "ec", "r", "et", "vu", "vue", "etat", "po", "envoye"}
               for m in recus)
    assert http is not None and not [x for x in http.boite if x.get("t") == "candidat"], "un onglet qui interroge lit l'état"
    #  Sans WebSocket : la lecture dédiée a le texte en cours (en mémoire), avant tout brouillon.
    st, dd = local.api("direct/candidat", local.tete, {"ticket": str(tid)})
    assert st == 200 and dd["reponses"][str(rang)] == "a" * 40 and dd["page"]["vue"] == "ouverte" and dd["rang"] == rang
    assert local.sql("SELECT COUNT(*) FROM candidature_brouillons WHERE envoi_id=?", (eid,)) == [(0,)], "une frappe n'écrit rien"
    #  La page fermée : dite tout de suite ; cachée juste après (les deux arrivent ensemble) : la fermeture compte.
    local.ecrire("presence", {"vue": "fermee"}, h)
    local.ecrire("presence", {"vue": "cachee"}, h)
    assert local.api("direct/candidat", local.tete, {"ticket": str(tid)})[1]["page"]["vue"] == "fermee"
    assert local.sql("SELECT vu_le > 0 FROM candidature_etat WHERE envoi_id=?", (eid,)) == [(1,)], "la fermeture est gardée"


def test_C7b_diffuser_candidat_sans_salle_n_atteint_personne():
    import tableau
    assert tableau.diffuser_candidat(987654321, {"k": 1, "e": 2}) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  C8 — le journal : une ligne par ouverture et par envoi, jamais par frappe
# ═══════════════════════════════════════════════════════════════════════════════

def test_C8_le_journal(local, sans_cadence):
    tid, eid = local.ticket(1021)
    avant = local.sql("SELECT MAX(id) FROM registre")[0][0] or 0
    h = local.candidat(f"ticket={tid}")
    local.candidat(f"ticket={tid}")   # rouvert : pas de seconde ligne
    st, d = local.lire("questionnaire", h)
    rang = d["etapes"][0]["questions"][0]["rang"]
    for k in range(15):
        local.ecrire("saisie", {"rang": rang, "texte": "x" * (k + 1)}, h)
    local.ecrire("brouillon", {"reponses": {str(rang): "xxx"}}, h)
    local.ecrire("presence", {"vue": "cachee"}, h)
    nouveaux = local.sql("SELECT type, texte FROM registre WHERE id > ? AND (membre_id=? OR auteur_id=?)", (avant, 1021, 1021))
    assert [t for t, _x in nouveaux] == ["recrutement.en_ligne"], nouveaux
    assert "a ouvert le questionnaire en ligne" in nouveaux[0][1]
    tous = {str(q["rang"]): "fin" for x in d["etapes"] for q in x["questions"]}
    assert local.ecrire("envoyer", {"reponses": tous}, h)[0] == 200
    local.annonces()
    lignes = local.sql("SELECT type, texte FROM registre WHERE id > ? AND membre_id=? AND type LIKE 'recrutement.%' ORDER BY id",
                       (avant, 1021))
    assert [t for t, _x in lignes] == ["recrutement.en_ligne", "recrutement.reponses"], lignes
    assert "réponses reçues" in lignes[1][1], lignes[1][1]


# ═══════════════════════════════════════════════════════════════════════════════
#  C9 — les textes du registre
# ═══════════════════════════════════════════════════════════════════════════════

def test_C9_les_textes_de_la_page_sont_declares_et_lus_par_sa_lecture(local):
    import candidature_site
    import textes
    js = (RACINE / "site" / "candidature.js").read_text(encoding="utf-8")
    assert set(re.findall(r'\bT\("([a-z0-9_.]+)"', js)) == {k.split(".", 1)[1] for k in candidature_site.PAGE}
    employes = {}
    for cle, defaut in re.findall(r'\bT\("([a-z0-9_.]+)",\s*"((?:[^"\\]|\\.)*)"', js):
        employes.setdefault("candidature." + cle, set()).add(json.loads('"' + defaut + '"'))
    assert set(employes) == set(candidature_site.PAGE), set(employes) ^ set(candidature_site.PAGE)
    for cle, defauts in employes.items():
        assert defauts == {textes.defaut(cle)}, f"le repli de la page diffère du texte d'origine : {cle}"
    for cle in [f"candidature.{c}" for c, *_r in candidature_site.TEXTES]:
        assert textes.declare(cle), cle
    h = local.candidat("ticket=61")
    st, d = local.lire("questionnaire", h)
    assert set(d["textes"]) == set(candidature_site.PAGE)
    assert local.requete("GET", "/tableau/espace/api/textes/site", h)[0] == 403
    #  Réécrit par la direction (la VRAIE adresse du registre) : la page le reçoit tout de suite.
    item = textes.item(local.g, "candidature.titre")
    st, rep, _h = local.requete("POST", "/tableau/espace/api/texte", local.tete,
                                {"cle": "candidature.titre", "valeur": "Ton embarquement", "version": item["version"]}, ecrire=True)
    assert st == 200, _texte(rep)
    try:
        assert local.lire("questionnaire", h)[1]["textes"]["candidature.titre"] == "Ton embarquement"
    finally:
        local.requete("POST", "/tableau/espace/api/texte/defaut", local.tete, {"cle": "candidature.titre"}, ecrire=True)
    assert local.lire("questionnaire", h)[1]["textes"]["candidature.titre"] == "Ta candidature"
    groupe = next(x for x in textes.groupes(local.g) if x["cle"] == "candidature_site")
    assert groupe["nom"] == "Le questionnaire en ligne" and len(groupe["textes"]) == len(candidature_site.TEXTES)


# ═══════════════════════════════════════════════════════════════════════════════
#  C10 — le câblage, la page, RGPD
# ═══════════════════════════════════════════════════════════════════════════════

def test_C10_cablage_page_et_rgpd(local):
    import gdpr
    import tableau
    arbre = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
    boot = ast.unparse(next(n for n in arbre.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_activite_boot"))
    etape = boot[boot.index("with _Etape('candidature_site'):"):]
    for morceau in ("candidature_site.setup(get_db=get_db, cfg=cfg", "await candidature_site.init_db()",
                    "tableau.monter(candidature_site)", "await candidature_site.demarrer()"):
        assert morceau in etape, morceau
    assert boot.index("with _Etape('tableau'):") < boot.index("with _Etape('candidature_site'):")
    assert boot.index("with _Etape('questionnaire'):") < boot.index("with _Etape('candidature_site'):")
    for fichier in ("candidature_site.py", "tableau.py", "health_server.py", "bot.py", "questionnaire.py"):
        texte = (RACINE / fichier).read_text(encoding="utf-8")
        assert "/tableau/demo" not in texte and "site_local" not in texte, f"{fichier} : aucune entrée sans lien"
    for table in ("candidature_brouillons", "candidature_sessions", "candidature_etat"):
        assert gdpr.DELETE_SUBJECT[table] == ["candidat_id"]
    assert gdpr.RETENTION["candidature_brouillons"] == ("maj_le", 30)

    async def valider():
        async with local.ctx.get_db() as db:
            return await gdpr.validate_map(db)
    manque = local.faire(valider())
    assert not [t for t in manque["missing_tables"] if t.startswith("candidature")]
    assert not [c for c in manque["missing_columns"] if c[0].startswith("candidature")]
    #  La page : CSP stricte, rien en ligne, aucun HTML de données, aucun émoji, rien du site de la direction.
    h = local.candidat("ticket=61")
    st, corps, hd = local.requete("GET", "/tableau/candidature/", h)
    page = _texte(corps)
    assert st == 200 and hd["Content-Security-Policy"] == tableau.CSP_SITE and hd["Cache-Control"] == "no-store"
    assert "{{V}}" not in page and 'src="/tableau/espace/s/candidature.js?v=' in page
    assert "<script>" not in page and " style=" not in page and "<style" not in page
    for nom in ("candidature.js", "candidature_direct.js"):
        js = (RACINE / "site" / nom).read_text(encoding="utf-8")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js and "outerHTML" not in js
        assert 'setAttribute("style"' not in js and "new Function" not in js
        assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", js), "aucun émoji"
    principal = (RACINE / "site" / "candidature.js").read_text(encoding="utf-8")
    for module in ("./app.js", "./hors_ligne.js", "./api.js", "./recrutement.js", "./direct.js", "./capitainerie.js"):
        assert f'from "{module}"' not in principal, module
    assert "/tableau/candidature/api/" in principal and "/tableau/espace/api/" not in principal
    for css in ("candidature.css", "candidature_direct.css"):
        assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", (RACINE / "site" / css).read_text(encoding="utf-8"))
    #  Le dossier de la direction charge le direct à la demande ; le service worker le garde, jamais ses données.
    zone = (RACINE / "site" / "recrutement_zone.js").read_text(encoding="utf-8")
    assert 'import("./candidature_direct.js")' in zone and "m.vueEnDirect(Number(D.ticket), {" in zone
    chefs = (RACINE / "site" / "recrutement_chefs.js").read_text(encoding="utf-8")
    assert 'import("./candidature_direct.js")' in chefs and "m.vueEnDirect({ envoi: Number(e.id) }, {" in chefs
    sw = (RACINE / "site" / "sw.js").read_text(encoding="utf-8")
    assert '"candidature_direct.js"' in sw and '"candidature_direct.css"' in sw and r"api\/(?!direct\/)" in sw
    assert "/tableau/espace/s/candidature_direct.css?v={{V}}" in (RACINE / "site" / "index.html").read_text(encoding="utf-8")
    direct = (RACINE / "site" / "direct.js").read_text(encoding="utf-8")
    assert 'case "candidat": signaler({ type: "candidat", m }); break;' in direct and "export const modeDirect" in direct


# ═══════════════════════════════════════════════════════════════════════════════
#  C12, C13 — le VRAI chemin, avec l'équipe du recrutement : un ticket, puis un chef d'équipe
# ═══════════════════════════════════════════════════════════════════════════════

def _poster(local, nom, corps):
    """Une écriture du site de la direction (la tête) : (statut, corps)."""
    st, rep, _h = local.requete("POST", f"/tableau/espace/api/{nom}", local.tete, corps, ecrire=True)
    return st, json.loads(rep) if rep else None


def _liens_vues(vues) -> list:
    return [c["url"] for v in vues for c in _composants(v) if c.get("url")]


def test_C12_le_vrai_chemin_d_un_ticket_et_la_page_du_candidat(local, sans_cadence):
    """Le ticket ouvert par le VRAI chemin du bot (le panneau, « Es-tu sûr ? », la fiche, l'affiche), la demande approuvée
    avec deux étapes (la fiche est l'étape 1), « Répondre au questionnaire » (le vrai bouton du ticket) → le lien de SA
    page, l'étape 2 envoyée sur la page → « réponses reçues » dans le ticket, l'étape 3 ouverte par la direction, envoyée
    → « Réponses envoyées », la correction, « Accepter » — à chaque instant, au plus deux messages du bot dans le ticket."""
    import banc_ticket_recrutement as B
    import questionnaire
    import tableau
    m = local.g.get_member(1002)
    r = local.faire(local.ctx.chemin.ouvrir_par_le_panneau(m, "p1", 2, "Parcours_C12"))
    tid = int(r["ticket"])
    assert tid, r

    def messages():
        return json.loads(_texte(local.requete("GET", f"/tableau/demo/discord?ticket={tid}")[1]))["messages"]
    assert len(messages()) == 1, "l'affiche seule"
    banque = [q["id"] for q in local.faire(questionnaire.questions(1)) if questionnaire.posable(q) and q["statut"] == "confirme"]
    st, rep = _poster(local, "recrutement/etape1", {"ticket": tid, "decision": "approuver", "etapes": [
        {"titre": "Le jeu", "consigne": "Quelques mots suffisent.", "questions": banque[:3]},
        {"titre": "Le clan", "consigne": "Relis-toi.", "questions": banque[3:6]}]})
    assert st == 200, rep
    eid = int(rep["envoi"])
    e = local.faire(questionnaire._envoi(eid))
    assert e["etape_ouverte"] == 1 and e["etape_fiche"] == 1 and len(questionnaire.etapes_de(e)) == 2
    m1 = messages()
    assert len(m1) == 2 and "Étape 2 sur 3" in m1[1]["texte"], [x["texte"][:80] for x in m1]
    assert not any(q["question"] in m1[1]["texte"] for q in e["questions"]), "les questions sont sur SA page, pas dans le ticket"
    #  « Répondre au questionnaire » : sa page (le lien, pour lui seul), jamais un formulaire de Discord.
    i = B.Inter(local.ctx.chemin, m)
    local.faire(questionnaire.BoutonRepondre(eid).callback(i))
    liens = _liens_vues(i.vues())
    assert not i.modals and len(liens) == 1 and liens[0].startswith("http://localhost:8790/tableau/candidature/"), liens
    j = tableau.lire_jeton(liens[0].rsplit("/", 1)[1])
    assert (j["p"], j["u"]) == ("candidat", 1002)
    h, arrivee = local.entrer("/tableau/candidature/" + liens[0].rsplit("/", 1)[1])
    assert arrivee == "/tableau/candidature/"
    st, d = local.lire("questionnaire", h)
    assert d["portes"] == {"mode": "etapes", "ouverte": 1, "envoyee": 0, "fiche": 1, "total": 2, "courante": 1}
    assert [x["titre"] for x in d["etapes"]] == ["Le jeu"]
    r1 = [q["rang"] for q in d["etapes"][0]["questions"]]
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): f"Réponse {r}" for r in r1}}, h)
    assert st == 200 and rep["etat"] == "attente", rep
    m2 = messages()
    assert len(m2) == 2 and m2[1]["id"] == m1[1]["id"] and "reçues" in m2[1]["texte"].lower(), [x["texte"][:80] for x in m2]
    #  « Répondre » une seconde fois : l'étape attend la direction (dit par l'équipe du recrutement, sans lien).
    i2 = B.Inter(local.ctx.chemin, m)
    local.faire(questionnaire.BoutonRepondre(eid).callback(i2))
    assert not _liens_vues(i2.vues()) and not i2.modals
    #  La direction ouvre l'étape 3 : l'ancien message s'efface, le nouveau le prévient ; sa page la montre.
    st, rep = _poster(local, "recrutement/etape_suivante", {"envoi": eid})
    assert st == 200, rep
    m3 = messages()
    assert len(m3) == 2 and m3[1]["id"] != m1[1]["id"] and "Étape 3 sur 3" in m3[1]["texte"]
    st, d = local.lire("questionnaire", h)
    assert d["etat"] == "ouvert" and [(x["numero"], x["envoyee"], x["courante"]) for x in d["etapes"]] == [(1, True, False), (2, False, True)]
    r2 = [q["rang"] for q in d["etapes"][1]["questions"]]
    st, rep = local.ecrire("envoyer_etape", {"etape": 2, "reponses": {str(r): f"Réponse {r}" for r in r2}}, h)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    m4 = messages()
    assert len(m4) <= 2 and "envoyées" in " ".join(x["texte"] for x in m4).lower(), [x["texte"][:80] for x in m4]
    d = local.api("recrutement/dossier", local.tete, {"ticket": str(tid)})[1]
    assert d["etape"] == "reponses" and d["envois"][-1]["bilan"]["repondues"] == len(r1) + len(r2)
    #  La correction, puis « Accepter » : le ticket se ferme sur la décision, au plus deux messages.
    for q in d["envois"][-1]["questions"]:
        assert _poster(local, "recrutement/corriger", {"envoi": eid, "question": q["id"], "juste": True})[0] == 200
    st, rep = _poster(local, "recrutement/decision", {"ticket": tid, "decision": "accepter"})
    assert st == 200, rep
    local.annonces()
    d = local.api("recrutement/dossier", local.tete, {"ticket": str(tid)})[1]
    assert d["etape"] == "accepte" and len(messages()) <= 2
    st, fin = local.lire("questionnaire", h)
    assert fin["etat"] in ("envoye", "ferme")


def test_C12b_la_page_n_est_offerte_que_branchee_au_recrutement(local, monkeypatch):
    """Les points d'appel (`lien_candidat`, `inviter`) n'existent que si le recrutement a reçu CETTE page
    (`questionnaire.setup(web=…)`) et qu'elle peut servir : trouvée par son nom (un `import`), elle n'offre rien — le
    recrutement garde ses formulaires de Discord, et un chef ne se propose pas sans page."""
    import candidature_site
    import questionnaire
    import tableau
    assert candidature_site.branchee() and questionnaire._page_candidat() is candidature_site._lien_candidat
    assert getattr(candidature_site, "inviter") is candidature_site._inviter
    monkeypatch.setattr(questionnaire, "_web_module", None)          # trouvée par son nom, pas branchée
    assert questionnaire._web() is candidature_site and not candidature_site.branchee()
    assert questionnaire._page_candidat() is None and getattr(candidature_site, "inviter", None) is None
    with pytest.raises(AttributeError):
        candidature_site.lien_candidat   # noqa: B018
    monkeypatch.undo()
    monkeypatch.setattr(tableau, "_base", "")                        # branchée, mais le site n'a pas d'adresse
    assert not candidature_site.branchee() and questionnaire._page_candidat() is None
    monkeypatch.undo()
    assert candidature_site.branchee()


def test_C13_le_vrai_chemin_d_un_chef_d_equipe(local, sans_cadence):
    """« Proposer d'être chef » (la route du site) : le message privé (la page du candidat, son bouton persistant), le lien,
    ses réponses justes étape par étape — l'étape suivante ouverte par la direction lui revient en message privé —, 100 %,
    « Nommer chef » : son rôle « Chef · <métier> », son badge « Chef validé · <métier> » pour l'éditeur des équipes."""
    import questionnaire
    import tableau
    nonce = int(time.time()) % 100000
    m = local.g.get_member(1013)
    metiers_ = {x["cle"]: x["nom"] for x in local.faire(questionnaire._liste_metiers(local.g))}
    metier = "navigation" if "navigation" in metiers_ else next(iter(metiers_))
    st, rep = _poster(local, "recrutement/chefs/role", {"metier": metier, "creer": True})
    assert st == 200, rep
    qa = [(f"Quel instrument mesure la hauteur du soleil, épreuve {nonce} ?", "Le sextant"),
          (f"Comment appelle-t-on le côté droit d'un navire, épreuve {nonce} ?", "Tribord"),
          (f"Combien de quarts compte une journée de bord, épreuve {nonce} ?", "Six"),
          (f"Quel nœud fait une boucle qui ne glisse pas, épreuve {nonce} ?", "Le nœud de chaise")]
    ids = []
    for question, reponse in qa:
        st, rep = _poster(local, "recrutement/chefs/question", {"question": question, "reponse": reponse, "metiers": [metier]})
        assert st == 200, rep
        ids.append(rep["question"]["id"])
    carnet = local.ctx.carnet["mp"]
    n = len(carnet)
    st, rep = _poster(local, "recrutement/chefs/proposer", {"membre": str(m.id), "metier": metier, "etapes": [
        {"titre": "Le cap", "consigne": "Chaque réponse doit être juste.", "questions": ids[:2]},
        {"titre": "L'équipage", "consigne": "", "questions": ids[2:]}]})
    assert st == 200 and rep["invite"] is True, rep
    eid = int(rep["envoi"])
    #  Le message privé : la page du candidat, son bouton persistant.
    mp = [x for x in carnet[n:] if x[0] == m.id]
    assert len(mp) == 1
    comps = _composants(mp[0][2]["view"])
    assert [c["custom_id"] for c in comps if c.get("custom_id")] == [f"cq:rep:{eid}"]
    assert f"chef d'équipe · {metiers_[metier]}" in "\n".join(c.get("content", "") for c in comps)

    def cliquer():
        import candidature_site
        gabarit = candidature_site.BoutonQuestionnaire.__discord_ui_compiled_template__.fullmatch(f"cq:rep:{eid}")
        bouton = local.faire(candidature_site.BoutonQuestionnaire.from_custom_id(None, None, gabarit))
        i = Obj(guild=None, user=m, response=_Reponse())
        local.faire(bouton.callback(i))
        return _liens_vues([i.response.envois[0]["view"]])
    liens = cliquer()
    assert len(liens) == 1
    h, _a = local.entrer("/tableau/candidature/" + liens[0].rsplit("/", 1)[1])
    st, d = local.lire("questionnaire", h)
    assert d["nature"] == "chef" and d["metier"] == metiers_[metier] and d["portes"]["total"] == 2 and d["portes"]["fiche"] == 0
    attendues = dict(qa)
    e = local.faire(questionnaire._envoi(eid))
    par_rang = {int(q["rang"]): attendues[q["question"]] for q in e["questions"]}
    r1 = [q["rang"] for q in d["etapes"][0]["questions"]]
    assert local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): par_rang[r] for r in r1}}, h)[0] == 200
    #  L'étape suivante : ouverte par la direction, elle lui revient en message privé (« l'étape 2 est ouverte »).
    n = len(carnet)
    st, rep = _poster(local, "recrutement/etape_suivante", {"envoi": eid})
    assert st == 200, rep
    mp = [x for x in carnet[n:] if x[0] == m.id]
    assert len(mp) == 1 and "L'étape 2 de ton questionnaire est ouverte" in "\n".join(
        c.get("content", "") for c in _composants(mp[0][2]["view"]))
    st, d = local.lire("questionnaire", h)
    r2 = [q["rang"] for q in d["etapes"][1]["questions"]]
    st, rep = local.ecrire("envoyer_etape", {"etape": 2, "reponses": {str(r): par_rang[r] for r in r2}}, h)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    #  100 % justes (cochées par la direction), « Nommer chef » : le rôle, le badge.
    for q in e["questions"]:
        assert _poster(local, "recrutement/corriger", {"envoi": eid, "question": q["id"], "juste": True})[0] == 200
    st, rep = _poster(local, "recrutement/chefs/decision", {"envoi": eid, "decision": "accepter"})
    assert st == 200, rep
    assert any(r.name == f"Chef · {metiers_[metier]}" for r in m.roles), [r.name for r in m.roles]
    badges = local.faire(questionnaire.badges_chefs(1))
    assert badges.get(str(m.id), badges.get(m.id, "")).startswith("Chef validé · "), badges
    #  Nommé : sa page ne prend plus rien.
    assert local.lire("questionnaire", h)[1]["etat"] in ("envoye", "ferme")
    assert local.ecrire("brouillon", {"reponses": {str(r1[0]): "encore"}}, h)[0] == 409


# ═══════════════════════════════════════════════════════════════════════════════
#  C11 — la porte elle-même (en dernier : ce test rappelle tableau.setup)
# ═══════════════════════════════════════════════════════════════════════════════

def test_C11_la_porte_refuse_le_candidat_partout_ou_on_ne_le_demande_pas(tmp_path, monkeypatch):
    import registre
    import tableau

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(tmp_path / "porte.db")
        try:
            yield db
        finally:
            await db.close()
    m = Obj(id=7, bot=False, roles=[], display_name="Tobias")
    g = Obj(id=1, get_member=lambda uid: m if uid == 7 else None)

    async def cfg(_g):
        return {}
    tableau.setup(bot=Obj(get_guild=lambda gid: g), cle="k", base_url="https://bot.exemple", cfg=cfg, get_db=get_db,
                  mesurer_groupe=None, autorise_membre=lambda gg, mm, c: False, direction=lambda gg, mm, c: False,
                  tete=(), log=lambda *a: None)
    registre.setup(get_db=get_db, log=lambda *a: None)
    monkeypatch.setattr(tableau, "AUTORISE_CANDIDAT", None)

    async def scenario():
        await tableau.init_db()
        await registre.init_db()
        sid = await tableau._ouvrir_session(1, 7, int(time.time()) + 3600, portee="candidat")
        sur = Obj(cookies={tableau.COOKIE_CANDIDAT: sid}, headers={}, remote="1.2.3.4", path="/tableau/candidature/")
        recopie = Obj(cookies={tableau.COOKIE: sid}, headers={}, remote="1.2.3.5", path="/tableau/espace/")
        out = {"defaut": await tableau._session(recopie), "toutes": await tableau._session(recopie, portees=None)}
        for nom, req, portees, cookie in (("direction", recopie, ("tout",), tableau.COOKIE),
                                          ("equipage", recopie, tableau.PORTEES_EQUIPAGE, tableau.COOKIE),
                                          ("sans_branchement", sur, ("candidat",), tableau.COOKIE_CANDIDAT)):
            try:
                await tableau._verifier(req, portees=portees, cookie=cookie)
                out[nom] = None
            except tableau._Refus as r:
                out[nom] = (r.status, r.message)
        tableau.AUTORISE_CANDIDAT = lambda gg, mm, emp: ""      # branché : il entre, chez lui seulement
        ok, _g = await tableau._verifier(sur, portees=("candidat",), cookie=tableau.COOKIE_CANDIDAT)
        out["branche"] = ok["p"]
        tableau.AUTORISE_CANDIDAT = lambda gg, mm, emp: "Accès retiré."
        try:
            await tableau._verifier(sur, portees=("candidat",), cookie=tableau.COOKIE_CANDIDAT)
            out["refuse"] = None
        except tableau._Refus as r:
            out["refuse"] = r.status

        async def casse(gg, mm, emp):
            raise RuntimeError("base en panne")
        tableau.AUTORISE_CANDIDAT = casse
        try:
            await tableau._verifier(sur, portees=("candidat",), cookie=tableau.COOKIE_CANDIDAT)
            out["en_panne"] = None
        except tableau._Refus as r:
            out["en_panne"] = r.status
        return out
    out = asyncio.run(scenario())
    assert out["defaut"] is None and out["toutes"] is not None
    assert out["direction"] == (403, "Réservé au fondateur et à la direction.")
    assert out["equipage"][0] == 403 and out["sans_branchement"] == (403, "Accès retiré.")
    assert out["branche"] == "candidat" and out["refuse"] == 403 and out["en_panne"] == 403
    assert tableau.lire_jeton(tableau.jeton(1, 7, "candidat"))["p"] == "candidat"
    assert "candidat" in tableau.PORTEES and "candidat" not in tableau.PORTEES_EQUIPAGE
