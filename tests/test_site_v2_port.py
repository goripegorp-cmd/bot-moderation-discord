"""Site v2 — « Le Port » (Discord) et « L'Équipage » (clan) contre le VRAI serveur (25/10/2026).

La page a été écrite contre une maquette ; seul le vrai serveur a montré les écarts (l'étape des candidatures en
cours, le sens des compteurs du nettoyage, le nom de qui l'a lancé, les zones d'échange de l'entraide, l'identifiant
brut d'un casier effacé…). Ici, sur le vrai site local (`outils/site_local.py` : le serveur du bot, ses modules, les
VRAIES actions de bot.py) :
P1 chaque action envoyée par la page existe dans bot.py, et chaque champ envoyé y est lu (sinon le bouton « marche »
   à l'écran et ne fait rien) ; la maquette connaît les mêmes actions.
P2 les actions, avec le corps exact de la page, et l'état relu par l'API après chacune.
P3 ce que la page lit dans les réponses du serveur (données, fiche, conversation, nettoyage, suivi du recrutement).
P4 la maquette rend les mêmes formes que le vrai serveur (sinon ses contrôles disent faux).
P5 le nettoyage nomme qui l'a lancé ; un casier effacé nomme la personne (jamais son identifiant brut).
"""
from __future__ import annotations

import ast
import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "site"
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
#  Les champs que la page AJOUTE au corps littéral : `agir()` (motif, durée, statut choisi) et la fenêtre « Prévenir ».
AJOUTES = {"moderer": {"motif", "duree"}, "ticket_fermer": {"motif"}, "suggestion_repondre": {"motif", "statut"},
           "clan_prevenir": {"mode", "salon"}}


def _fonction(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise KeyError(nom)


def _actions_du_bot() -> dict:
    """{action : nom de la fonction} — `_ACTIONS_TABLEAU` de bot.py."""
    for n in ARBRE.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_ACTIONS_TABLEAU" for t in n.targets):
            return {k.value: v.id for k, v in zip(n.value.keys, n.value.values)}
    raise KeyError("_ACTIONS_TABLEAU")


def _corps_de_la_page() -> dict:
    """{action : champs du corps littéral} pour chaque `{ action: "…", … }` de site/*.js."""
    out: dict = {}
    for f in sorted(SITE.glob("*.js")):
        texte = f.read_text(encoding="utf-8")
        for m in re.finditer(r'\{\s*action:\s*"(\w+)"', texte):
            prof, i = 0, m.start()
            while True:  # jusqu'à l'accolade qui ferme ce corps
                prof += {"{": 1, "}": -1}.get(texte[i], 0)
                if prof == 0:
                    break
                i += 1
            corps = texte[m.start() + 1:i]
            out.setdefault(m.group(1), set()).update(set(re.findall(r"(?:^|,)\s*(\w+)\s*:", corps)) - {"action"})
    return out


def test_P1_chaque_action_de_la_page_existe_et_chaque_champ_est_lu():
    bot = _actions_du_bot()
    page = _corps_de_la_page()
    assert len(page) >= 18, sorted(page)
    for nom, champs in page.items():
        assert nom in bot, f"action inconnue du bot : {nom}"
        source = ast.unparse(_fonction(bot[nom]))
        for champ in champs | AJOUTES.get(nom, set()):
            assert f"'{champ}'" in source, f"{nom} : le champ « {champ} » envoyé par la page n'est pas lu par {bot[nom]}"
    sys.path.insert(0, str(RACINE / "outils"))
    try:
        import site_maquette
        assert set(site_maquette.ACTIONS) == set(bot), "la maquette connaît exactement les actions du bot"
    finally:
        sys.path.remove(str(RACINE / "outils"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Le vrai site local, construit une fois pour ce fichier
# ═══════════════════════════════════════════════════════════════════════════════

class Local:
    def __init__(self, boucle, client, ctx):
        self.boucle, self.client, self.ctx = boucle, client, ctx
        self.cookies: dict = {}

    def faire(self, coro):
        return self.boucle.run_until_complete(coro)

    async def _session(self, qui):
        if qui not in self.cookies:
            r = await self.client.get("/tableau/demo" + ("?qui=direction" if qui == "direction" else ""),
                                      allow_redirects=False)
            import tableau
            self.cookies[qui] = {"Cookie": f"{tableau.COOKIE}={r.cookies[tableau.COOKIE].value}"}
        return self.cookies[qui]

    def get(self, chemin, qui="fondateur", **params):
        async def f():
            h = await self._session(qui)
            r = await self.client.get(chemin, params=params or None, headers=h)
            return r.status, await r.json()
        return self.faire(f())

    def post(self, chemin, corps, qui="fondateur"):
        async def f():
            h = dict(await self._session(qui), **{"X-Tableau": "1", "Origin": "http://localhost:8790"})
            r = await self.client.post(chemin, json=corps, headers=h)
            return r.status, await r.json()
        return self.faire(f())

    def action(self, corps, qui="fondateur"):
        return self.post("/tableau/espace/action", corps, qui)

    def donnees(self):
        return self.get("/tableau/espace/donnees")[1]

    def fiche(self, uid):
        return self.get("/tableau/espace/membre", id=str(uid))[1]


@pytest.fixture(scope="module")
def local(tmp_path_factory):
    import paths
    import tableau
    import transcript_store
    mp = pytest.MonkeyPatch()
    mp.setattr(tableau, "ROUTES", {})
    mp.setattr(tableau, "REGLES", dict(tableau.REGLES))
    mp.setattr(tableau, "_SOURCES_MEDIAS", [])
    mp.setattr(tableau, "RACINE_DONNEES", None)
    mp.setattr(transcript_store, "_BASE_DIR", transcript_store._BASE_DIR)
    mp.setattr(paths, "_RESOLVED_BASE", paths._RESOLVED_BASE)
    mp.syspath_prepend(str(RACINE / "outils"))
    import site_local
    from aiohttp.test_utils import TestClient, TestServer
    boucle = asyncio.new_event_loop()

    async def demarrer():
        app, ctx = await site_local.construire(tmp_path_factory.mktemp("port") / "local", 8790)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client, ctx
    client, ctx = boucle.run_until_complete(demarrer())
    try:
        site = Local(boucle, client, ctx)
        site.depart = site.donnees()  # les données de départ (P3, P4), avant les actions de P2
        yield site
    finally:
        boucle.run_until_complete(client.close())
        boucle.close()
        mp.undo()
        for nom in ("site_local", "site_local_port"):
            sys.modules.pop(nom, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  P2 — les actions, comme la page les envoie
# ═══════════════════════════════════════════════════════════════════════════════

def test_P2_les_actions_du_port_et_de_l_equipage_sur_le_vrai_serveur(local):
    d = local.donnees()
    ok = lambda rep: rep[0] == 200 and rep[1]["ok"] is True  # noqa: E731
    #  Aperçu, salons et questions.
    al = d["alertes"][0]["id"]
    assert ok(local.action({"action": "alerte_geree", "membre": al}))
    assert not any(a["id"] == al for a in local.donnees()["alertes"])
    q = next(x for x in d["questions"]["liste"] if x["statut"] == "ouverte")
    assert ok(local.action({"action": "question", "question": q["question"], "statut": "traitee"}))
    assert next(x for x in local.donnees()["questions"]["liste"] if x["question"] == q["question"])["statut"] == "traitee"
    idee = next(x for x in d["suggestions"]["liste"] if x["statut"] == "attente")
    assert ok(local.action({"action": "suggestion_repondre", "suggestion": idee["id"], "motif": "On regarde.", "statut": "etude"}))
    i = next(x for x in local.donnees()["suggestions"]["liste"] if x["id"] == idee["id"])
    assert (i["statut"], i["note"]) == ("etude", "On regarde."), "la carte suit et l'auteur est prévenu (aucune erreur)"
    assert ok(local.action({"action": "suggestion_retirer", "suggestion": idee["id"]}))
    sond = next(x for x in d["sondages"]["liste"] if x["statut"] == "en_cours")
    assert ok(local.action({"action": "sondage_retirer", "sondage": sond["id"]}))
    assert next(x for x in local.donnees()["sondages"]["liste"] if x["id"] == sond["id"])["statut"] == "retire"
    #  Tickets : le motif de fermeture revient dans la liste des fermés.
    t = next(x for x in d["tickets"]["ouverts"] if not x["rellseas"])
    assert ok(local.action({"action": "ticket_fermer", "ticket": t["ticket"], "motif": "Réglé depuis le site"}))
    local.faire(asyncio.sleep(0.3))  # la fermeture part en fond, comme dans le bot
    ferme = next(x for x in local.donnees()["tickets"]["fermes"] if x["ticket"] == t["ticket"])
    assert ferme["motif"] == "Réglé depuis le site" and ferme["ferme_par"] == "GoRipe"
    #  La fiche : modérer, le casier.
    rep = local.action({"action": "moderer", "membre": "1011", "sanction": "warn", "motif": " "})
    assert rep[1]["ok"] is False and "motif" in rep[1]["message"], "motif obligatoire, comme les commandes"
    assert ok(local.action({"action": "moderer", "membre": "1011", "sanction": "warn", "motif": "Spam répété"}))
    assert ok(local.action({"action": "moderer", "membre": "1011", "sanction": "mute", "motif": "Flood", "duree": 60}))
    f = local.fiche(1011)
    assert f["membre"]["mute_jusqu"] and any(s["type"] == "warn" and s["date"] for s in f["sanctions"]), "datée à l'écriture"
    assert ok(local.action({"action": "moderer", "membre": "1011", "sanction": "unmute"}))
    assert not local.fiche(1011)["membre"]["mute_jusqu"]
    mute = next(s for s in local.fiche(1011)["sanctions"] if s["type"] == "mute")
    assert ok(local.action({"action": "sanction_retirer", "sanction": mute["sanction"]}))
    assert ok(local.action({"action": "casier_effacer", "membre": "1011", "quoi": "warns"}))
    assert not any(s["type"] == "warn" for s in local.fiche(1011)["sanctions"])
    protege = local.action({"action": "moderer", "membre": str(FONDATEUR), "sanction": "ban", "motif": "Essai"})
    assert protege[1]["ok"] is False and "protégés" in protege[1]["message"]
    assert ok(local.action({"action": "moderer", "membre": "1023", "sanction": "ban", "motif": "Arnaque"}, "direction"))
    assert local.fiche(1023)["membre"].get("banni") is True
    assert ok(local.action({"action": "debannir", "membre": "1023"}, "direction"))
    assert local.fiche(1023)["membre"].get("banni") is False
    assert ok(local.action({"action": "casier_serveur", "portee": "warns", "jours": 90, "confirmation": "EFFACER"}, "direction"))
    assert local.donnees()["casier"]["compte"]["warns"]["90"] == 0
    lot = next(x for x in local.donnees()["casier"]["lots"] if not x["restaure_le"])
    assert ok(local.action({"action": "casier_restaurer", "lot": lot["lot"]}, "direction"))
    #  L'équipage.
    assert ok(local.action({"action": "clan_ajouter", "membre": "1002"}, "direction"))
    salon = local.donnees()["clan"]["salons"][0]["id"]
    assert ok(local.action({"action": "clan_prevenir", "membres": ["1012", "1022"], "mode": "salon", "salon": salon}, "direction"))
    rappels = {m["id"]: m["rappel"] for m in local.donnees()["clan"]["membres"]}
    assert all(rappels[u] and rappels[u]["statut"] == "en_attente" and rappels[u]["mode"] == "salon" for u in ("1012", "1022"))
    assert ok(local.action({"action": "clan_rappel_annuler", "membre": "1007"}, "direction")), "le délai écoulé : le garder"
    assert ok(local.action({"action": "clan_retirer", "membre": "1022"}, "direction"))
    assert ok(local.action({"action": "clan_retirer_lot", "membres": ["1012", "1021"]}, "direction"))
    ids = {m["id"] for m in local.donnees()["clan"]["membres"]}
    assert "1002" in ids and not ids & {"1012", "1021", "1022"} and rappels["1007"] is not None
    cand = local.donnees()["candidats"][0]["id"]
    assert ok(local.action({"action": "fiche_retirer", "candidat": cand}, "direction"))
    #  P5 : un casier effacé nomme la personne ; le nettoyage nomme qui l'a lancé.
    efface = next(x for x in local.donnees()["casier"]["lots"] if x.get("membre"))
    assert (efface["membre"], efface["quoi"]) == ("1011", "Avertissements"), efface
    st, n = local.post("/tableau/espace/api/nettoyage/lancer", {})
    assert st == 200 and n["par"] == str(FONDATEUR) and n["personnes"][str(FONDATEUR)]["nom"] == "GoRipe"
    assert n["bilans"][0]["par"] == str(FONDATEUR)
    st, n = local.get("/tableau/espace/api/nettoyage")
    assert st == 200 and n["personnes"][str(FONDATEUR)]["nom"] == "GoRipe"


# ═══════════════════════════════════════════════════════════════════════════════
#  P3 — ce que la page lit ; P4 — la maquette rend la même chose
# ═══════════════════════════════════════════════════════════════════════════════

#  Les champs lus par la page (discord.js, clan.js, fiche.js, app.js) : s'ils manquent, une rubrique se vide sans erreur.
LUS = {
    "tickets.ouverts": {"id", "nom", "pseudo", "avatar", "ticket", "type", "rellseas", "ouvert", "pris_par", "salon"},
    "tickets.fermes": {"id", "ticket", "type", "rellseas", "ouvert", "ferme", "ferme_par", "motif", "transcript"},
    "tickets.types": {"nom", "rellseas", "total", "sans_prise", "prise_mediane", "fermeture_mediane"},
    "clan.membres": {"id", "nom", "pseudo", "avatar", "statut", "rang", "jours", "derniere", "arrivee", "rappel"},
    "sanctions.membres": {"id", "total", "n30", "n90", "types", "derniere", "liste"},
    "questions.liste": {"question", "id", "texte", "quand", "statut", "par", "repondu_le", "salon", "message"},
    "suggestions.liste": {"id", "auteur", "titre", "details", "statut", "note", "decide_par", "decide_le", "cree", "retire_le",
                          "pour", "contre", "salon", "lien"},
    "sondages.liste": {"id", "auteur", "question", "choix", "comptes", "total", "multiple", "cree", "fin", "statut",
                       "retire_le", "retire_par", "salon", "lien"},
    "entraide.liste": {"id", "zone", "type", "auteur", "titre", "champs", "statut", "aidants", "certifie_par", "partenaire",
                       "ferme_par", "cree", "ferme", "lien", "transcript"},
    "annonces.liste": {"id", "titre", "texte", "salon", "auteur", "cree", "vues", "vus", "mention", "lien"},
    "casier.lots": {"lot", "quand", "par", "quoi", "n", "personnes", "restaure_le", "restaure_par"},
    "alertes": {"id", "incidents", "points", "evenements"},
    "en_cours": {"id", "nom", "ticket", "ouvert", "pris_par", "reponses", "salon"},
}


def _chemin(d, chemin):
    for k in chemin.split("."):
        d = d[k]
    return d


def test_P3_ce_que_la_page_lit_dans_les_reponses_du_serveur(local):
    d = local.depart
    for chemin, champs in LUS.items():
        liste = _chemin(d, chemin)
        assert liste, f"données de démonstration vides : {chemin}"
        manque = champs - set().union(*[set(x) for x in liste])
        assert not manque, f"{chemin} : champs absents {sorted(manque)}"
    assert {"ouvertes", "repondues_7", "delai_median", "salons"} <= set(d["questions"]["stats"])
    assert {e["zone"] for e in d["entraide"]["liste"]} & {"trade", "cl_trade"}, "les deux zones d'échange existent"
    f = local.fiche(1003)
    assert {"present", "a_part", "protege", "roles", "arrivee", "cree", "mute_jusqu", "clan"} <= set(f["membre"])
    assert {"agir", "sanctions", "donnees", "tickets", "candidatures", "journal", "questions", "sondages", "idees", "alerte",
            "personnes"} <= set(f)
    st, n = local.get("/tableau/espace/api/nettoyage")
    assert st == 200 and {"regles", "compteurs", "dernier", "bilan", "par", "bilans", "personnes"} <= set(n)
    r = {x["cle"]: x for x in n["regles"]}
    assert r["tickets_archives"]["auto"] is False, "un rangement : la page le dit, rien n'est effacé"
    assert r["sessions"]["garde_jours"] == 0 and not r["sessions"]["reglable"], "« jusqu'à expiration » sur la page"
    #  L'étape des candidatures en cours : donnees ne la porte pas, le suivi du recrutement oui.
    st, s = local.get("/tableau/espace/api/recrutement/suivi")
    etapes = {o["etape"] for o in s["ouverts"]}
    assert st == 200 and {"etape1", "etape2", "reponses"} <= etapes, etapes
    tickets_en_cours = {c["ticket"] for c in d["en_cours"]}
    assert tickets_en_cours <= {o["ticket"] for o in s["ouverts"]}, "chaque candidature en cours a son étape"
    #  La conversation : en direct, transcript, absent — et le suivi.
    ouvert = local.donnees()["tickets"]["ouverts"][0]["ticket"]
    st, c = local.get("/tableau/espace/conversation", ticket=str(ouvert))
    assert st == 200 and c["source"] == "discord" and c["messages"] and c["suivi"]
    st, c = local.get("/tableau/espace/conversation", ticket="999999")
    assert st == 200 and c["absent"] == "Ticket introuvable."


def forme(x):
    if isinstance(x, dict):
        return {k: forme(v) for k, v in x.items()}
    if isinstance(x, list):
        if x and all(isinstance(e, dict) for e in x):
            union: dict = {}
            for e in x:
                for k, v in e.items():
                    if union.get(k) in (None, "", [], {}):
                        union[k] = v
            return [forme(union)]
        return [forme(x[0])] if x else []
    return None if x is None else "nombre" if isinstance(x, (int, float)) and not isinstance(x, bool) else type(x).__name__


#  Des dictionnaires aux clés libres (catégories, règles branchées, identifiants) : seule la forme des valeurs compte.
CLES_LIBRES = ("journal.par_jour", "journal.par_jour.<clé>", "sanctions.libelles", "sanctions.membres[].types", "sanctions.staff[].types",
               "nettoyage.compteurs", "nettoyage.bilan", "nettoyage.partiront", "personnes", "sanctions.mois", "tickets.mois")
#  Ce que la maquette porte en plus et que la page tolère (l'étape des candidatures : le suivi du recrutement fait foi).
EN_PLUS_PERMIS = ("donnees.en_cours[].etape", "donnees.en_cours[].recrutement")


def ecarts(reel, maq, chemin="") -> list:
    out = []
    if isinstance(reel, dict) and isinstance(maq, dict):
        if any(chemin.endswith(c) for c in CLES_LIBRES) or (reel and all(str(k)[:1].isdigit() for k in reel)):
            vr, vm = list(reel.values()), list(maq.values())
            return ecarts(vr[0], vm[0], chemin + ".<clé>") if vr and vm else []
        for k in sorted(set(reel) - set(maq)):
            out.append(f"manque dans la maquette : {chemin}.{k}")
        for k in sorted(set(maq) - set(reel)):
            if f"{chemin}.{k}" not in EN_PLUS_PERMIS:
                out.append(f"en trop dans la maquette : {chemin}.{k}")
        for k in sorted(set(reel) & set(maq)):
            out += ecarts(reel[k], maq[k], f"{chemin}.{k}")
    elif isinstance(reel, list) and isinstance(maq, list):
        if reel and maq:
            out += ecarts(reel[0], maq[0], chemin + "[]")
    elif reel is not None and maq is not None and type(reel) is not type(maq):
        out.append(f"type différent : {chemin} (serveur {reel}, maquette {maq})")
    return out


def test_P4_la_maquette_rend_les_memes_formes_que_le_serveur(local):
    sys.path.insert(0, str(RACINE / "outils"))
    try:
        import site_maquette
    finally:
        sys.path.remove(str(RACINE / "outils"))
    m = site_maquette.MONDE = site_maquette.Monde(7)

    class Requete:
        def __init__(self, **q):
            self.query = q
    reel = {"donnees": local.depart}
    maq = {"donnees": json.loads(json.dumps(m.donnees("v"), default=str))}
    reel["membre"] = local.fiche(1003)
    maq["membre"] = json.loads(json.dumps(m.fiche(m.sanctions_donnees()["membres"][0]["id"]), default=str))
    ferme = next(t["ticket"] for t in reel["donnees"]["tickets"]["fermes"] if t["transcript"])
    reel["conversation"] = local.get("/tableau/espace/conversation", ticket=str(ferme))[1]
    maq["conversation"] = m.conversation(m.tickets_donnees()["fermes"][0]["ticket"])
    reel["recherche"] = local.get("/tableau/espace/recherche", q="a")[1]
    maq["recherche"] = json.loads(local.faire(site_maquette.recherche(Requete(q="a"))).body)
    reel["nettoyage"] = local.get("/tableau/espace/api/nettoyage")[1]
    maq["nettoyage"] = site_maquette.r_nettoyage(m, {}, {})[1]
    reel["suivi"] = local.get("/tableau/espace/api/recrutement/suivi")[1]
    maq["suivi"] = site_maquette.r_suivi(m, {}, {})[1]
    differences = []
    for nom in reel:
        differences += ecarts(forme(reel[nom]), forme(maq[nom]), nom)
    assert not differences, "\n".join(differences)
