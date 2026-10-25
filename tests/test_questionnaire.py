"""25/10/2026 : le recrutement du clan en deux étapes (questionnaire.py).

Le fondateur : « …un questionnaire automatique et ultra bien fait qui ne leur expliquera pas où ils ont eu faux, mais
nous on le verra sur le site… Pas au Discord de décider ou au site de décider. » Puis : « tu dois créer de vraies
questions sans mettre de réponse dans la question… Tu t'assures du bon fonctionnement de tout ça. »

Le parcours entier (ouverture → étape 1 refusée → message et fermeture ; ouverture → étape 2 → formulaires page par page
→ reprise après un redémarrage → réponses → corrections → acceptation), aucune réponse attendue vers Discord, aucune
réponse dans une question, l'indication de proximité, les droits, le double clic, les limites de Discord, le site
(banque, liens, réglages, modèles, dernière sélection, dossier) et le branchement dans bot.py."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import re
from pathlib import Path

import aiosqlite
import discord
import pytest

import questionnaire as Q
import recrutements
import rellseas_panneau
from conftest_discord import Obj, laisser_finir
from faux_serveur import Monde, Texte, compter, ids, run, textes

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
EXEMPLE, LIENS = ICI / "questionnaire_exemple.json", ICI / "questionnaire_liens_exemple.json"
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION, CANDIDAT, AUTRE, RECRUTEUR = 781205382923288593, 827633340797681714, 50, 60, 70
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")
#  Les dix questions confirmées de l'exemple, dans l'ordre où la sélection automatique les range (les thèmes dans
#  l'ordre de `THEMES` : le studio, les actualités du Movie 3, le jeu, le clan).
ORDRE = ["ex-studio-01", "ex-studio-02", "ex-movie3-01", "ex-movie3-02", "ex-movie3-03", "ex-jeu-01", "ex-jeu-02",
         "ex-jeu-03", "ex-clan-01", "ex-clan-02"]
#  Ce que le candidat écrit (des fautes, des variantes, une phrase, une réponse fausse), question par question.
ECRIT = {"ex-studio-01": "brisants studio", "ex-studio-02": "Roblox", "ex-jeu-01": "The Leviathan",
         "ex-jeu-02": "sept", "ex-jeu-03": "Charpentié", "ex-movie3-01": "en 2026",
         "ex-movie3-02": "C'est Morvane qui trahit", "ex-movie3-03": "Mist Island", "ex-clan-01": "GoRp",
         "ex-clan-02": "Annonces"}


@pytest.fixture(autouse=True)
def _sans_attente(monkeypatch):
    """Les délais du module (fermeture, mots qui s'effacent) à zéro : les tests ne dorment pas."""
    monkeypatch.setattr(Q, "DELAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "AVIS_S", 0)
    monkeypatch.setattr(Q, "PAGE_S", 0)
    monkeypatch.setattr(Q, "REESSAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "REPRISE_MIN", 0.0)


class Banc:
    """Un serveur, une base, des tickets du clan ; le bot vu par `questionnaire.setup` (ses doublures)."""

    def __init__(self, tmp_path, fichier=EXEMPLE, liens=LIENS):
        self.chemin = tmp_path / "q.db"
        self.fichier, self.liens = fichier, liens
        self.conf = {"ticket_panels": {"p1": {"name": "Rell Seas", "welcome_message": "Bienvenue à bord !"},
                                       "p2": {"name": "Support"}}}
        self.g = Monde()
        self.porteur = self.g._salon(Texte, "tickets-rell-seas", {})
        self.fondateur, self.direction = self.g.membre(FONDATEUR), self.g.membre(DIRECTION)
        self.candidat, self.autre, self.recruteur = (self.g.membre(CANDIDAT), self.g.membre(AUTRE),
                                                     self.g.membre(RECRUTEUR))
        self.decisions, self.journal, self.panne, self.echecs = [], [], False, 0
        self.monter()

    @contextlib.asynccontextmanager
    async def get_db(self):
        db = await aiosqlite.connect(self.chemin)
        try:
            yield db
        finally:
            await db.close()

    async def cfg(self, _gid):
        return self.conf

    def monter(self):
        """Le démarrage du bot : tout ce que le module garde en mémoire repart de zéro (la base reste)."""
        Q.setup(get_db=self.get_db, cfg=self.cfg, panneaux=rellseas_panneau.panneaux_tickets,
                ticket_ouvert=self.ticket_ouvert, decider=self.decider, autorise=self.autorise, lien=self.lien,
                journal=self.noter, fichier_banque=self.fichier, fichier_liens=self.liens, log=lambda *a: None)

    async def preparer(self):
        async with self.get_db() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                             " guild_id INTEGER, channel_id INTEGER, user_id INTEGER, panel_id TEXT, claimed_by INTEGER,"
                             " status TEXT, answers TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS recrutements (guild_id INTEGER, ticket_id INTEGER,"
                             " decision TEXT, raison TEXT)")
            await db.commit()
        await Q.init_db()

    async def ouvrir(self, uid=CANDIDAT, pid="p1"):
        fil = self.g.nouveau_fil(self.porteur, f"ticket-{uid}")
        async with self.get_db() as db:
            cur = await db.execute("INSERT INTO tickets (guild_id, channel_id, user_id, panel_id, claimed_by, status,"
                                   " answers) VALUES (?,?,?,?,0,'open',?)",
                                   (self.g.id, fil.id, uid, pid, json.dumps({"Pseudo Roblox": "Kolax_RS", "Âge": "17"})))
            await db.commit()
            return cur.lastrowid, fil

    async def ticket_ouvert(self, g, tid):
        if self.panne:
            raise discord.HTTPException(Obj(status=503, reason="x"), "panne")
        async with self.get_db() as db:
            async with db.execute("SELECT channel_id, user_id, claimed_by, answers, panel_id FROM tickets WHERE id=?"
                                  " AND guild_id=? AND status='open'", (int(tid), g.id)) as cur:
                r = await cur.fetchone()
        if r is None:
            return None, None
        return self.g.fils.get(r[0]), {"id": int(tid), "user": r[1], "claimed": r[2] or 0,
                                       "answers": json.loads(r[3] or "{}"), "panel_id": r[4]}

    async def decider(self, g, tid, auteur, accepte, motif):
        """`_decision_recrutement` : rôle (si accepté), fermeture, suivi des candidatures."""
        self.decisions.append((int(tid), getattr(auteur, "id", 0), accepte, motif))
        if self.echecs > 0:          # Discord ne répond pas (les N premières fois)
            self.echecs -= 1
            return False, Q.DISCORD_HS
        async with self.get_db() as db:
            cur = await db.execute("UPDATE tickets SET status='closed' WHERE id=? AND status='open'", (int(tid),))
            if not cur.rowcount:
                return False, "Ce ticket n'est plus ouvert."
            await db.execute("INSERT INTO recrutements VALUES (?,?,?,?)",
                             (g.id, int(tid), "acceptes" if accepte else "refuses",
                              "Accepté" if accepte else f"Refusé : {motif}"))
            await db.commit()
        return True, ("Candidature acceptée : rôle donné, ticket fermé." if accepte
                      else "Candidature refusée : ticket fermé.")

    async def autorise(self, i):
        return i.user.id in (FONDATEUR, DIRECTION, RECRUTEUR)

    async def lien(self, i):
        if i.user.id in (FONDATEUR, DIRECTION):
            return "https://bot.exemple/tableau/JETON", ""
        return None, "Réservé au fondateur et à la direction."

    async def noter(self, g, type_, texte, membre_id=0, auteur_id=0):
        self.journal.append((type_, texte, membre_id, auteur_id))

    async def statut_ticket(self, tid):
        async with self.get_db() as db:
            async with db.execute("SELECT status FROM tickets WHERE id=?", (int(tid),)) as cur:
                return (await cur.fetchone())[0]


class Reponse:
    def __init__(self):
        self.messages, self.modals, self.defers, self.fait = [], [], [], False

    def is_done(self):
        return self.fait

    async def send_message(self, content=None, **kw):
        self.fait = True
        self.messages.append(kw.get("view", content))

    async def send_modal(self, modal):
        self.fait = True
        self.modals.append(modal)

    async def defer(self, **kw):
        self.fait = True
        self.defers.append(kw)


class Inter:
    """Une interaction : la réponse, les suivis (éphémères), l'effacement du mot pour soi."""

    def __init__(self, banc, membre, salon=None):
        self.guild, self.user, self.channel = banc.g, membre, salon
        self.response, self.suivis, self.effaces = Reponse(), [], 0
        self.followup = Obj(send=self._suivre)

    async def _suivre(self, content=None, **kw):
        assert kw.get("ephemeral") is True, "tout mot du questionnaire vers une personne est éphémère"
        self.suivis.append(kw.get("view", content))

    async def delete_original_response(self):
        self.effaces += 1

    def vues(self):
        return [v for v in self.response.messages + self.suivis if hasattr(v, "to_components")]

    def texte(self):
        return " ".join(textes(v) for v in self.vues())


def _vues_du_fil(fil):
    return [kw["view"] for _c, kw in fil.envois if "view" in kw]


def _modal_textes(modal) -> str:
    out = []

    def tout(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("title", "label", "description", "placeholder", "content") and isinstance(v, str):
                    out.append(v)
                else:
                    tout(v)
        elif isinstance(x, list):
            for y in x:
                tout(y)
    tout(modal.to_dict())
    return " ".join(out)


def _remplir(modal, valeurs: dict):
    for rang, champ in modal.champs:
        champ._value = valeurs.get(rang, f"réponse {rang}")


async def _cliquer(banc, bouton, membre, salon=None):
    i = Inter(banc, membre, salon)
    await bouton.callback(i)
    return i


async def _soumettre(banc, modal, membre, valeurs, salon=None):
    _remplir(modal, valeurs)
    i = Inter(banc, membre, salon)
    await modal.on_submit(i)
    return i


async def _ouvrir_avec_carte(b):
    tid, fil = await b.ouvrir()
    _vue, n = await Q.vue_accueil(b.g, b.conf["ticket_panels"]["p1"]["welcome_message"], "Rell Seas")
    await Q.poser_etape1(b.g, fil, tid, CANDIDAT, nombre=n)
    return tid, fil


# ═══ 1. L'ouverture : l'accueil (deux étapes, N questions, les liens) et la carte de l'étape 1 ═══════════════════════

def test_Q01_ouverture_accueil_deux_etapes_nombre_liens_et_carte_de_l_etape_1(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        tid, fil = await b.ouvrir()
        accueil, n = await Q.vue_accueil(b.g, "Bienvenue à bord !", "Rell Seas")
        await Q.poser_etape1(b.g, fil, tid, CANDIDAT, nombre=n)
        return tid, fil, accueil, n, await Q._suivi(b.g.id, tid)
    tid, fil, accueil, n, s = run(scenario())
    t = textes(accueil)
    assert n == 10, "le nombre réglé sur le site (10 par défaut), toutes les questions confirmées de l'exemple"
    assert "deux étapes" in t and "two steps" in t and "**10 questions**" in t and "10-question" in t
    assert "Bienvenue à bord !" in t, "le mot du panneau est repris"
    assert "Toutes les réponses se trouvent sur le wiki : dans les pages ci-dessous, ou à un clic depuis elles." in t and "Every answer is on the wiki: in the pages below, or one click away from them." in t
    assert "[Wiki du jeu](https://exemple.fandom.com/wiki/Accueil)" in t and "[Guide du clan](https://discord.com/" in t
    assert "Lien refusé" not in t and "sans-titre" not in t, "un lien http ou sans titre n'entre pas"
    carte = _vues_du_fil(fil)[-1]
    assert ids(carte) == [f"rq:e1:e:{tid}", f"rq:e1:s:{tid}", f"rq:e1:r:{tid}"]
    tc = textes(carte)
    assert "Envoyer le questionnaire" in tc and "Choisir sur le site" in tc and "Refuser l'étape 1" in tc
    assert "10 questions, la sélection par défaut" in tc
    am = fil.envois[-1][1]["allowed_mentions"]
    assert am.users is False and am.roles is False and am.everyone is False, "la carte de l'équipe ne prévient personne"
    assert (s["etape"], s["annonce"], s["candidat_id"], s["salon_id"]) == ("etape1", 10, CANDIDAT, fil.id)
    assert s["carte_id"] == fil.messages[-1].id
    assert not EMOJI.search(t + tc), "aucun émoji Unicode dans les cartes du recrutement"


def test_Q01b_accueil_sans_liens_ne_promet_pas_de_liens(tmp_path):
    vue = Q.carte_accueil("", "", 0, [])
    t = textes(vue)
    assert "liens" not in t and "links" not in t and "question" in t, "pas de liens réglés : aucune promesse de liens"
    assert "**0 question" not in t


# ═══ 2. Étape 1 refusée : le message automatique, puis la fermeture par le circuit normal ═════════════════════════

def test_Q02_etape1_refusee_message_automatique_puis_fermeture(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        bouton = Q.BoutonEtape1("r", tid)
        refuse = await _cliquer(b, bouton, b.candidat, fil)
        ouvre = await _cliquer(b, bouton, b.fondateur, fil)
        modal = ouvre.response.modals[0]
        modal.note._value = "pseudo Roblox introuvable"
        fin = Inter(b, b.fondateur, fil)
        await modal.on_submit(fin)
        await laisser_finir()
        return tid, fil, refuse, ouvre, fin, await Q._suivi(b.g.id, tid), await b.statut_ticket(tid)
    tid, fil, refuse, ouvre, fin, s, statut = run(scenario())
    assert not refuse.response.modals and Q.RESERVE in refuse.texte(), "le candidat ne refuse pas sa candidature"
    assert isinstance(ouvre.response.modals[0], Q.FormulaireRefus), "le formulaire est la confirmation"
    message = _vues_du_fil(fil)[-1]
    t = textes(message)
    assert f"<@{CANDIDAT}>" in t and Q.REFUS_ETAPE1.split("\n")[0] in t and "this ticket will be closed" in t
    assert "Tes réponses ne correspondent pas à ce que nous attendons : ce ticket va être clôturé." in t
    assert "Merci d'avoir créé un ticket." in t
    am = fil.envois[-1][1]["allowed_mentions"]
    assert [u.id for u in am.users] == [CANDIDAT] and am.roles is False and am.everyone is False
    assert b.decisions == [(tid, FONDATEUR, False, "étape 1 — pseudo Roblox introuvable")], \
        "le circuit normal : décision « refusé », motif interne « étape 1 » (la note reste à l'équipe)"
    assert statut == "closed" and s["etape"] == "refus_etape1" and s["fermeture_le"] == 0
    assert "pseudo Roblox" not in t, "la note interne ne part jamais dans le ticket"
    carte = [kw["view"] for mid, kw in fil.cartes if mid == s["carte_id"]][-1]
    assert "Étape 1 refusée" in textes(carte) and not ids(carte), "la carte de l'équipe le dit, sans boutons"
    assert "Message envoyé au candidat" in fin.texte()
    assert any(x[0] == "recrutement.etape1_refusee" and "pseudo Roblox introuvable" in x[1] for x in b.journal)


# ═══ 3. Le parcours complet : étape 2, pages, reprise après redémarrage, réponses, corrections, acceptation ═══════

async def _valeurs(eid) -> dict:
    """Ce que le candidat écrit, rangé comme le questionnaire envoyé (rang → texte)."""
    return {int(q["rang"]): ECRIT.get(q["id"], "je ne sais pas") for q in (await Q._envoi(eid))["questions"]}


async def _parcours_jusqu_aux_reponses(b, collecte):
    await b.preparer()
    tid, fil = await _ouvrir_avec_carte(b)
    envoi_clic = await _cliquer(b, Q.BoutonEtape1("e", tid), b.fondateur, fil)
    collecte.append(envoi_clic)
    s = await Q._suivi(b.g.id, tid)
    eid = s["envoi_id"]
    ecrit = await _valeurs(eid)
    intrus = await _cliquer(b, Q.BoutonRepondre(eid), b.autre, fil)
    collecte.append(intrus)
    page1 = await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)
    modal1 = page1.response.modals[0]
    collecte.append(modal1)
    apres1 = await _soumettre(b, modal1, b.candidat, ecrit, fil)
    collecte.append(apres1)
    b.monter()   # ⟳ le bot redémarre entre deux pages
    reprise = await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)
    modal2 = reprise.response.modals[0]
    collecte.append(modal2)
    fin = await _soumettre(b, modal2, b.candidat, ecrit, fil)
    collecte.append(fin)
    return tid, fil, eid, envoi_clic, intrus, page1, modal1, apres1, reprise, modal2, fin


def test_Q03_parcours_complet_etape2_pages_reprise_corrections_acceptation(tmp_path):
    b = Banc(tmp_path)
    collecte = []

    async def scenario():
        r = await _parcours_jusqu_aux_reponses(b, collecte)
        tid, fil, eid = r[:3]
        encore = await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)
        vieux_formulaire = await _soumettre(b, r[9], b.candidat, await _valeurs(eid), fil)
        dossier = await Q.dossier(b.g, tid)
        refus = []
        for qid in ORDRE:
            st, corps = await Q._r_corriger(b.g, b.direction, {}, {"envoi": eid, "question": qid,
                                                                  "juste": qid != "ex-clan-02"})
            refus.append(st)
        trop_tot = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        st_c, c10 = await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": "ex-clan-02", "juste": True,
                                                                "version": 1})
        accepte = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        fige = await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": "ex-clan-02", "juste": False})
        return r, encore, vieux_formulaire, dossier, refus, trop_tot, (st_c, c10), accepte, fige, \
            await Q._suivi(b.g.id, tid), await Q.dossier(b.g, tid)
    r, encore, vieux, dossier, statuts, trop_tot, c10, accepte, fige, s, dossier_final = run(scenario())
    tid, fil, eid, envoi_clic, intrus, page1, modal1, apres1, reprise, modal2, fin = r
    #  L'envoi depuis la carte de l'équipe : la sélection par défaut (10 questions), en deux formulaires.
    assert "Questionnaire envoyé : 10 questions." in envoi_clic.texte()
    cartes = [v for v in _vues_du_fil(fil) if "Étape 2" in textes(v)]
    assert len(cartes) == 1 and f"rq:rep:{eid}" in ids(cartes[0])
    t = textes(cartes[0])
    assert "## Étape 2 — 10 questions" in t and "Step 2 — 10 questions" in t
    assert "Toutes les réponses se trouvent sur le wiki : dans les pages ci-dessous, ou à un clic depuis elles." in t and "[Wiki du jeu](" in t
    assert "**1.** Quel studio développe le jeu dont parle ce clan ?" in t and "**Formulaire 2/2**" in t
    assert "**3.** En quelle année le Movie 3 est-il sorti ?" in t, "le studio, puis les actualités"
    assert "**10.** Quel salon Discord du clan donne les annonces officielles ?" in t
    envoi = next(kw for _c, kw in fil.envois if kw.get("view") is cartes[0])
    assert [u.id for u in envoi["allowed_mentions"].users] == [CANDIDAT], "le candidat seul est prévenu"
    #  Le candidat seul répond ; les formulaires : 5 questions, « Question N » et un extrait.
    assert not intrus.response.modals and Q.SEUL_CANDIDAT.split("\n")[0] in intrus.texte()
    assert isinstance(modal1, Q.FormulairePage) and [rang for rang, _c in modal1.champs] == [1, 2, 3, 4, 5]
    assert "page 1/2" in modal1.title and "Question 1" in _modal_textes(modal1)
    assert "Page 1/2 enregistrée" in apres1.texte() and ids(apres1.vues()[-1]) == [f"rq:pg:{eid}:2"]
    assert all(v.is_finished() for v in apres1.vues()), "le mot pour soi n'est pas gardé par discord.py"
    #  Après le redémarrage : la reprise à la page 2, pas une question perdue, pas une de trop.
    assert [rang for rang, _c in modal2.champs] == [6, 7, 8, 9, 10] and "page 2/2" in modal2.title
    assert Q.MERCI.split("\n")[0] in fin.texte() and "Thank you, your answers have been sent" in fin.texte()
    for mot in ("juste", "faux", "correct", "wrong", "%"):
        assert mot not in fin.texte().casefold().replace("ajuste", ""), "jamais juste ou faux pour le candidat"
    #  Une seule fois : « Répondre » le dit, un vieux formulaire renvoyé n'écrase rien.
    assert not encore.response.modals and "déjà transmises" in encore.texte()
    assert "déjà transmises" in vieux.texte()
    #  La carte dit « Réponses envoyées » (sans les réponses) ; celle de l'équipe « Réponses reçues ».
    derniere = [kw["view"] for mid, kw in fil.cartes if mid == fil.messages[-1].id or "Réponses" in textes(kw["view"])]
    assert any("Réponses envoyées" in textes(v) and not ids(v) for v in derniere)
    assert not any(ECRIT["ex-movie3-02"] in textes(kw["view"]) for _m, kw in fil.cartes), \
        "jamais les réponses dans le ticket"
    assert any("Réponses reçues" in textes(kw["view"]) and f"rq:e1:s:{tid}" in ids(kw["view"]) for _m, kw in fil.cartes)
    #  Le dossier du site : les réponses, les attendues, les indications — une aide, la personne décide.
    q = {x["id"]: x for x in dossier["envois"][0]["questions"]}
    assert dossier["etape"] == "reponses" and dossier["envois"][0]["statut"] == "repondu"
    assert q["ex-studio-01"]["reponse_candidat"] == "brisants studio" and q["ex-studio-01"]["attendue"] == "Brisants Studio"
    assert q["ex-studio-01"]["indication"]["niveau"] == "identique"
    assert q["ex-jeu-01"]["indication"]["niveau"] == "identique", "« The Leviathan » : l'article et l'accent tombent"
    assert q["ex-movie3-03"]["indication"]["avec"] == "variante" and q["ex-movie3-03"]["indication"]["variante"] == \
        "Mist Island", "la variante anglaise"
    assert q["ex-jeu-02"]["indication"]["niveau"] == "identique", "« sept » = 7"
    assert q["ex-jeu-03"]["indication"]["niveau"] == "proche", "Charpentié : une faute"
    assert q["ex-movie3-02"]["indication"]["detail"] == "contient la réponse attendue"
    assert q["ex-clan-02"]["indication"]["niveau"] == "different" and q["ex-clan-02"]["correction"] is None
    assert dossier["etape1"]["reponses"] == {"Pseudo Roblox": "Kolax_RS", "Âge": "17"}
    assert dossier["liens_discord"]["ticket"] == f"https://discord.com/channels/1/{fil.id}"
    assert dossier["peut"]["accepter"] and dossier["peut"]["renvoyer"] and dossier["peut"]["corriger"]
    #  L'exigence affichée (100 %) : sans « forcer », 9/10 ne suffit pas ; corrigée, l'acceptation passe.
    assert statuts == [200] * 10
    assert trop_tot[0] == 409 and trop_tot[1]["forcer_possible"] and trop_tot[1]["bilan"]["justes"] == 9
    assert c10[0] == 200 and c10[1]["correction"]["juste"] is True and c10[1]["correction"]["par"]["id"] == str(FONDATEUR)
    assert c10[1]["bilan"]["reussite"] and c10[1]["bilan"]["taux"] == 100
    assert accepte[0] == 200 and b.decisions == [(tid, FONDATEUR, True, "")], "le circuit actuel : rôle, fermeture"
    assert fige[0] == 409 and "figée" in fige[1]["erreur"]
    assert s["etape"] == "accepte" and dossier_final["statut_ticket"] == "ferme"
    assert [d["quoi"] for d in dossier_final["decisions"]] == ["questionnaire", "reponses", "accepte"]


# ═══ 4. Rien de ce qui part vers Discord ne contient une réponse attendue ═══════════════════════════════════════════

def test_Q04_aucune_reponse_attendue_ne_part_vers_discord(tmp_path):
    b = Banc(tmp_path)
    collecte = []

    async def scenario():
        r = await _parcours_jusqu_aux_reponses(b, collecte)
        envoi = await Q._envoi(r[2])
        lien = await _cliquer(b, Q.BoutonEtape1("s", r[0]), b.fondateur, r[1])
        collecte.append(lien)
        return r, envoi
    r, envoi = run(scenario())
    fil = r[1]
    morceaux = [json.dumps(v.to_components(), ensure_ascii=False) for v in _vues_du_fil(fil)]
    morceaux += [json.dumps(kw["view"].to_components(), ensure_ascii=False) for _m, kw in fil.cartes]
    for x in collecte:
        if isinstance(x, discord.ui.Modal):
            morceaux.append(_modal_textes(x))
        else:
            morceaux += [json.dumps(v.to_components(), ensure_ascii=False) for v in x.vues()]
    tout = " ".join(morceaux)
    assert len(envoi["questions"]) == 10
    for q in envoi["questions"]:
        assert not Q.fuite(tout, q["reponse"], q["variantes"]), f"la réponse de {q['id']} est partie vers Discord"
    for cle in ('"attendue"', '"variantes"', '"extrait"', '"indication"', '"correction"',
                "exemple.fandom.com/wiki/Fosse_Noire", "Une créature"):
        assert cle not in tout, cle


# ═══ 5. La réponse n'est jamais dans la question ═══════════════════════════════════════════════════════════════════

def test_Q05_la_reponse_n_est_jamais_dans_la_question(tmp_path):
    brut = json.loads(EXEMPLE.read_text(encoding="utf-8"))["questions"]
    propres = [q for k, x in enumerate(brut) if (q := Q.depuis_fichier(x, k)) is not None]
    assert {q["id"] for q in propres} == set(ORDRE) | {"ex-fuite-01", "ex-verif-01"}, \
        "écartées : la question rejetée par la recherche, l'incomplète, celle sans identifiant"
    for q in propres:
        if q["actif"]:
            assert not Q.fuite(q["question"], q["reponse"], q["variantes"]), q["id"]
    fuyante = next(q for q in propres if q["id"] == "ex-fuite-01")
    assert fuyante["statut"] == "a_verifier" and not fuyante["actif"], "dévoile sa réponse : jamais posée"
    assert Q.fuite("Combien de mers dans le Movie 3 ?", "3") == "", "un seul chiffre n'est pas une fuite"
    assert Q.fuite("En quelle année, 2026, sort le film ?", "2026") == "2026"
    assert Q.fuite("Qui garde la fosse ?", "Léviathan", ["The Leviathan"]) == ""
    assert Q.fuite("Le Léviathan garde quelle fosse ?", "le leviathan") == "le leviathan", "casse, accents, articles"
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        refus = await Q._r_question(b.g, b.fondateur, {}, {"theme": "jeu", "question": "Quel navire, le Vent Noir, coule ?",
                                                           "reponse": "Autre", "variantes": ["Vent Noir"]})
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {})
        return refus, (st, corps), await Q.questions(b.g.id)
    refus, _e, banque = run(scenario())
    assert refus[0] == 400 and refus[1]["fuite"] == "Vent Noir", "le site refuse une question qui dévoile sa réponse"
    assert not any(Q.posable(q) and Q.fuite(q["question"], q["reponse"], q["variantes"]) for q in banque)


def test_Q06_la_banque_reelle_si_elle_est_la_ne_pose_aucune_question_qui_devoile_sa_reponse(tmp_path):
    """La banque de la recherche (le wiki), une fois copiée dans `donnees_jeu/` : lue, et trente sélections
    automatiques dont aucune réponse ne se lit dans les questions posées avec elle, ni dans les liens."""
    reelle, liens = RACINE / "donnees_jeu" / "questionnaire_base.json", RACINE / "donnees_jeu" / "questionnaire_liens.json"
    if not reelle.is_file():
        pytest.skip("la banque réelle (donnees_jeu/questionnaire_base.json) n'est pas encore dans le dépôt")
    brut = Q._lire_fichier(reelle)
    propres = [q for k, x in enumerate(brut) if (q := Q.depuis_fichier(x, k)) is not None]
    assert propres, "la banque réelle est lisible et contient des questions"
    for q in propres:
        assert not (q["actif"] and Q.fuite(q["question"], q["reponse"], q["variantes"])), q["id"]
        assert q["source"] == "" or q["source"].startswith("https://"), q["id"]
    b = Banc(tmp_path, fichier=reelle, liens=liens)

    async def scenario():
        await b.preparer()
        lns = await Q.liens(b.g.id)
        return lns, [await Q.selection(b.g.id, None) for _ in range(30)]
    lns, selections = run(scenario())
    texte_liens = Q.texte_des_liens(lns)
    for st, sel in selections:
        assert st == 200 and len(sel["questions"]) == min(10, len(propres))
        for q in sel["questions"]:
            autres = " ".join([texte_liens] + [x["question"] for x in sel["questions"]])
            assert not Q.fuite(autres, q["reponse"], q["variantes"]), q["id"]


# ═══ 6. L'indication de proximité : une aide, jamais une décision ═══════════════════════════════════════════════════

@pytest.mark.parametrize("ecrit,attendue,variantes,niveau,avec", [
    ("kraken", "Kraken", (), "identique", "reponse"),                     # majuscules
    ("ile de brume", "Île de Brume", (), "identique", "reponse"),         # accents
    ("L'Île-de-Brume !", "Île de Brume", (), "identique", "reponse"),     # ponctuation, articles
    ("RELLGames", "RELL Games", (), "identique", "reponse"),              # espaces
    ("Krakenn", "Kraken", (), "proche", "reponse"),                       # faute de frappe
    ("Kraekn", "Kraken", (), "proche", "reponse"),                        # deux lettres inversées
    ("Charpentié", "Charpentier", (), "proche", "reponse"),               # accord
    ("c'est le kraken je crois", "Kraken", (), "proche", "reponse"),      # une phrase qui la contient
    ("Mist Island", "Île de Brume", ("Mist Island",), "identique", "variante"),   # anglais / français
    ("mist iland", "Île de Brume", ("Mist Island",), "proche", "variante"),
    ("three", "3", (), "identique", "reponse"),                           # nombres écrits en lettres
    ("1 000", "1000", (), "identique", "reponse"),
    ("en 2026", "2026", (), "proche", "reponse"),
    ("2025", "2026", (), "different", "reponse"),                         # un nombre voisin reste différent
    ("Ice", "Ace", (), "different", "reponse"),
    ("Tortue", "Île de la Tortue Noire", (), "different", "reponse"),     # en partie seulement
    ("", "Kraken", (), "different", "reponse"),
])
def test_Q07_indication_de_proximite(ecrit, attendue, variantes, niveau, avec):
    ind = Q.indication(ecrit, attendue, variantes)
    assert (ind["niveau"], ind["avec"]) == (niveau, avec), ind
    assert 0.0 <= ind["score"] <= 1.0 and ind["detail"]
    if avec == "variante":
        assert ind["variante"] == variantes[0]


@pytest.mark.parametrize("ecrit,attendue,variantes,type_,niveau,detail", [
    ("Logia, Zoan et Paramecia", "Paramecia, Logia, Zoan", (), "liste", "identique", "mêmes éléments"),
    ("PC, Xbox, PlayStation, mobile", "PC, PlayStation/Xbox et Mobile", (), "liste", "identique", "mêmes éléments"),
    ("Logia, Zoan, Paramecia et Mythical", "Paramecia, Logia, Zoan", (), "liste", "proche",
     "contient tous les éléments attendus"),
    ("Logia et Zoan", "Paramecia, Logia, Zoan", (), "liste", "different", "en partie : 2 mot(s) sur 3"),
    ("Noire Barbe", "Barbe Noire", (), "texte", "proche", "mêmes mots, dans un autre ordre"),
    ("Movie 1", "Movie 3", (), "texte", "different", "un nombre ou une lettre diffère"),
    ("rang B", "rang A", (), "texte", "different", "un nombre ou une lettre diffère"),
    ("A", "A", ("rang A",), "texte", "identique", "même réponse"),
    ("25 octobre", "24 octobre", ("24/10",), "texte", "different", None),
    ("24/10", "24 octobre", ("24/10",), "texte", "identique", "même réponse"),
    ("24 octobr", "24 octobre", (), "texte", "proche", "faute de frappe ou d'accord"),
    ("9.99", "9,99 $", ("$9.99",), "texte", "identique", "même réponse"),
    ("un", "1", ("un", "un seul", "one"), "nombre", "identique", "même réponse"),
    ("un seul", "1", ("un", "un seul", "one"), "nombre", "identique", "même réponse"),
])
def test_Q07c_listes_ordre_libre_nombres_et_lettres_recopies_exactement(ecrit, attendue, variantes, type_, niveau,
                                                                       detail):
    ind = Q.indication(ecrit, attendue, variantes, type_)
    assert ind["niveau"] == niveau and (detail is None or ind["detail"] == detail), ind


def test_Q07b_indication_texte_long_rapide_et_partielle_dite():
    import time
    debut = time.perf_counter()
    for k in range(300):
        Q.indication("mot " * 100 + str(k), "Une réponse attendue assez longue " * 5, ("variante longue " * 10,) * 12)
    assert time.perf_counter() - debut < 5, "une page de dossier ne bloque pas le bot"
    assert Q.indication("Tortue", "Île de la Tortue Noire")["detail"] == "en partie : 1 mot(s) sur 3"
    assert Q.normaliser("L'Œuvre — 1 000 000 pièces, dix-sept îles") == "oeuvre 1000000 pieces 17 iles"
    assert Q.normaliser("qu'il n'utilise rien de l'IP") == "il utilise rien ip", "les élisions tombent"
    assert Q.normaliser("rang D") == "rang d" and Q.normaliser("un") == "1", "une lettre seule reste ; « un » seul = 1"
    assert Q.fuite("Quelle lettre désigne le rang le plus élevé ?", "A", ["rang A"]) == "", \
        "« rang » dans la question ne dévoile pas « rang A »"


# ═══ 7. Les droits ═════════════════════════════════════════════════════════════════════════════════════════════════

def test_Q08_droits_carte_etape1_site_et_formulaires(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        envoi_candidat = await _cliquer(b, Q.BoutonEtape1("e", tid), b.candidat, fil)
        site_candidat = await _cliquer(b, Q.BoutonEtape1("s", tid), b.candidat, fil)
        site_recruteur = await _cliquer(b, Q.BoutonEtape1("s", tid), b.recruteur, fil)
        site_tete = await _cliquer(b, Q.BoutonEtape1("s", tid), b.direction, fil)
        envoi_recruteur = await _cliquer(b, Q.BoutonEtape1("e", tid), b.recruteur, fil)
        eid = (await Q._suivi(b.g.id, tid))["envoi_id"]
        formulaire = await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)
        vole = await _soumettre(b, formulaire.response.modals[0], b.autre, ECRIT, fil)
        page_autre = await _cliquer(b, Q.BoutonPage(eid, 2, 2), b.fondateur, fil)
        inconnu = await _cliquer(b, Q.BoutonRepondre(eid + 99), b.candidat, fil)
        return tid, envoi_candidat, site_candidat, site_recruteur, site_tete, envoi_recruteur, vole, page_autre, \
            inconnu, await Q._reponses(eid)
    tid, envoi_c, site_c, site_r, site_t, envoi_r, vole, page_autre, inconnu, reponses = run(scenario())
    assert Q.RESERVE in envoi_c.texte() and Q.RESERVE in site_c.texte()
    assert "Réservé au fondateur et à la direction." in site_r.texte(), "le site : les deux comptes de tête seuls"
    lien = json.dumps(site_t.vues()[-1].to_components())
    assert f"https://bot.exemple/tableau/JETON#recrutement={tid}&membre={CANDIDAT}" in lien
    assert "Ouvrir sa fiche sur le site" in site_t.texte() and site_t.effaces == 0, "le lien reste (il est personnel)"
    assert "Questionnaire envoyé" in envoi_r.texte(), "l'équipe de recrutement (`_peut_decider`) envoie l'étape 2"
    assert Q.SEUL_CANDIDAT.split("\n")[0] in vole.texte() and reponses == {}, "un autre ne répond pas à sa place"
    assert Q.SEUL_CANDIDAT.split("\n")[0] in page_autre.texte()
    assert Q.INTROUVABLE.split("\n")[0] in inconnu.texte()


# ═══ 8. Le double clic ═════════════════════════════════════════════════════════════════════════════════════════════

def test_Q09_double_clic_un_seul_envoi_une_seule_fin(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        a, c = Inter(b, b.fondateur, fil), Inter(b, b.direction, fil)
        await asyncio.gather(Q.BoutonEtape1("e", tid).callback(a), Q.BoutonEtape1("e", tid).callback(c))
        async with b.get_db() as db:
            async with db.execute("SELECT COUNT(*) FROM recrutement_envois") as cur:
                n_envois = (await cur.fetchone())[0]
        eid = (await Q._suivi(b.g.id, tid))["envoi_id"]
        m1 = (await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)).response.modals[0]
        await _soumettre(b, m1, b.candidat, ECRIT, fil)
        m2a = (await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)).response.modals[0]
        m2b = (await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil)).response.modals[0]
        _remplir(m2a, ECRIT)
        _remplir(m2b, ECRIT)
        x, y = Inter(b, b.candidat, fil), Inter(b, b.candidat, fil)
        await asyncio.gather(m2a.on_submit(x), m2b.on_submit(y))
        r1 = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "etape2"})
        r2 = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "refuser"})
        return a, c, n_envois, x, y, r1, r2, fil, eid
    a, c, n_envois, x, y, r1, r2, fil, eid = run(scenario())
    textes_ = [a.texte(), c.texte()]
    assert n_envois == 1, "deux clics : un seul questionnaire"
    assert sum("Questionnaire envoyé" in t for t in textes_) == 1
    assert sum(("déjà envoyé" in t) or ("déjà en cours" in t) for t in textes_) == 1
    assert len([v for v in _vues_du_fil(fil) if "Étape 2 —" in textes(v)]) == 1
    merci, deja = Q.MERCI.split("\n")[0], Q.DEJA.split("\n")[0]
    assert {merci in x.texte() or deja in x.texte(), merci in y.texte() or deja in y.texte()} == {True}
    assert merci in x.texte() + y.texte(), "l'un des deux lit « Merci », l'autre « déjà transmises » — jamais une erreur"
    assert len([kw for _m, kw in fil.cartes if "Réponses envoyées" in textes(kw["view"])]) == 1, "une seule fin"
    assert len([j for j in b.journal if j[0] == "recrutement.reponses"]) == 1
    assert r1[0] == 409 and r1[1]["etape"] == "reponses" and r2[0] == 409, "l'étape 1 est passée : plus de décision d'étape 1"


# ═══ 9. Les limites de Discord, au maximum de ce que le site permet ═══════════════════════════════════════════════

def test_Q10_limites_components_v2_et_formulaires_au_maximum():
    question = ("Pourquoi " + "le navire " * 40)[:Q.QUESTION_MAX - 1] + "?"
    envoi = {"id": 123456, "candidat_id": CANDIDAT, "renvoi": True,
             "questions": [{"rang": k + 1, "id": f"q{k}", "question": question} for k in range(Q.PAR_ENVOI)],
             "liens": [{"titre": "T" * Q.LIEN_TITRE_MAX, "url": "https://exemple.com/" + "a" * (Q.URL_MAX - 20),
                        "description": "d" * Q.LIEN_DESC_MAX} for _ in range(Q.LIENS_MAX)]}

    async def scenario():
        vues = {etat: Q.cartes_etape2(envoi, etat, quand=1) for etat in ("ouvert", "repondu", "remplace", "clos")}
        modals = [Q.FormulairePage(envoi, p) for p in range(1, Q.nb_pages(Q.PAR_ENVOI) + 1)]
        accueil = Q.carte_accueil("m" * 3000, "N" * 200, 25, envoi["liens"])
        etape1 = [Q.carte_etape1(10 ** 11, etat, nombre=25, par=FONDATEUR, candidat=CANDIDAT, quand=1)
                  for etat in ("attente", "envoye", "reponses", "refus_etape1", "refuse", "accepte")]
        refus = Q.FormulaireRefus(10 ** 11)
        page = Q._vue_texte("x" * 5000, boutons=[Q.BoutonPage(10 ** 11, 5, 5)])
        return vues, modals, accueil, etape1, refus, page
    vues, modals, accueil, etape1, refus, page = run(scenario())
    for etat, liste in vues.items():
        assert 1 <= len(liste) <= 4, etat
        tout = " ".join(textes(v) for v in liste)
        for k in range(1, Q.PAR_ENVOI + 1):
            assert f"**{k}.**" in tout, (etat, k)
        for v in liste:
            assert compter(v) <= 40 and len(textes(v)) <= 4000, (etat, compter(v), len(textes(v)))
        assert (f"rq:rep:123456" in ids(liste[-1])) == (etat == "ouvert"), "le bouton sur le dernier message"
    for v in [accueil, page, *etape1]:
        assert compter(v) <= 40 and len(textes(v)) <= 4000
    for m in [*modals, refus]:
        d = m.to_dict()
        assert len(d["title"]) <= 45 and 1 <= len(d["components"]) <= 5
        for c in d["components"]:
            assert len(c["label"]) <= 45 and len(c.get("description") or "") <= 100
            assert len(c["component"].get("placeholder") or "") <= 100
    for v in [*vues["ouvert"], *etape1, page]:
        for item in v.walk_children():
            bouton = item.item if isinstance(item, discord.ui.DynamicItem) else item
            if isinstance(bouton, discord.ui.Button):
                assert len(bouton.label or "") <= 80 and len(bouton.custom_id or "") <= 100
                assert bouton.emoji is None, "sans icône maison installée : aucun émoji (pas de repli Unicode)"
    assert len(modals) == 5 and [len(m.champs) for m in modals] == [5] * 5


# ═══ 10. Le site : la banque, les liens, les réglages, le semis ════════════════════════════════════════════════════

def test_Q11_banque_liens_reglages_et_semis_qui_n_ecrase_jamais_le_site(tmp_path):
    b = Banc(tmp_path)
    fichier = tmp_path / "banque.json"
    donnees = json.loads(EXEMPLE.read_text(encoding="utf-8"))
    fichier.write_text(json.dumps(donnees), encoding="utf-8")
    b.fichier = fichier
    b.monter()

    async def scenario():
        await b.preparer()
        banque = await Q.banque(b.g)
        qs = {q["id"]: q for q in banque["questions"]}
        #  La question modifiée sur le site, celle retirée : le fichier ne les touche plus.
        m = await Q._r_question(b.g, b.fondateur, {}, dict(qs["ex-jeu-01"], reponse="Le Léviathan noir",
                                                           variantes=["Leviathan"], version=qs["ex-jeu-01"]["version"]))
        conflit = await Q._r_question(b.g, b.direction, {}, dict(qs["ex-jeu-01"], version=qs["ex-jeu-01"]["version"]))
        retire = await Q._r_question_retirer(b.g, b.fondateur, {}, {"id": "ex-clan-01"})
        neuve = await Q._r_question(b.g, b.fondateur, {}, {"theme": "Movie 3", "question": "Quel trésor est volé au début ?",
                                                           "reponse": "La couronne d'ambre", "source": "https://www.youtube.com/watch?v=x&t=60",
                                                           "difficulte": "difficile"})
        hors_ligne = await Q._r_question(b.g, b.fondateur, {}, {"id": "op-1234", "theme": "clan",
                                                                "question": "Qui accueille les nouveaux du clan ?",
                                                                "reponse": "La vigie"})
        mauvais = [await Q._r_question(b.g, b.fondateur, {}, x) for x in (
            None, {"theme": "jeu", "question": "court", "reponse": "x"},
            {"theme": "jeu", "question": "Une vraie question ?", "reponse": ""},
            {"theme": "jeu", "question": "Une vraie question ?", "reponse": "x", "source": "javascript:alert(1)"},
            {"theme": "jeu", "question": "Une vraie question ?", "reponse": "x", "difficulte": "impossible"},
            {"theme": "jeu", "question": "Une vraie question ?", "reponse": "x", "variantes": "a" * 300},
            {"id": "../../x", "theme": "jeu", "question": "Une vraie question ?", "reponse": "x"},
            {"id": "ex-jeu-02", "theme": "jeu", "question": "Une vraie question ?", "reponse": "x"})]
        #  Le fichier de recherche change : l'intacte suit, la modifiée et la retirée ne bougent pas.
        for q in donnees["questions"]:
            if q["id"] in ("ex-jeu-01", "ex-clan-01", "ex-jeu-03"):
                q["reponse"] = q["reponse"] + " (corrigé)"
        donnees["questions"].append({"id": "ex-nouvelle", "theme": "jeu", "question": "Quelle arme lance des harpons ?",
                                     "reponse": "Arbalète", "statut": "confirme"})
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
        b.monter()
        bilan_semis = await Q.semer(b.g.id)
        apres = {q["id"]: q for q in await Q.questions(b.g.id)}
        #  Les liens et les réglages : versions, conflits, et le fichier ne remet plus les siens.
        r0 = await Q.reglages(b.g.id)
        lns = await Q._r_liens(b.g, b.fondateur, {}, {"version": r0["liens_version"], "liens": [
            {"titre": "Wiki officiel", "url": "https://exemple.fandom.com/wiki/Accueil", "description": "Tout le jeu"},
            {"id": "l-film", "titre": "Le film", "url": "https://www.youtube.com/watch?v=exemple"}]})
        lns_conflit = await Q._r_liens(b.g, b.direction, {}, {"version": r0["liens_version"], "liens": []})
        lns_mauvais = [await Q._r_liens(b.g, b.fondateur, {}, x) for x in (
            {"version": lns[1]["version"], "liens": [{"titre": "x", "url": "http://exemple.com/abc"}]},
            {"version": lns[1]["version"], "liens": [{"titre": "a", "url": "https://a.fr/b"}] * 2},
            {"version": lns[1]["version"], "liens": [{"titre": "a", "url": "https://a.fr/" + str(k)} for k in range(11)]})]
        b.monter()
        await Q.semer(b.g.id)
        liens_apres = await Q.liens(b.g.id)
        reg = await Q._r_reglages(b.g, b.fondateur, {}, {"nombre": 4, "version": r0["version"]})
        reg_conflit = await Q._r_reglages(b.g, b.direction, {}, {"nombre": 6, "version": r0["version"]})
        reg_mauvais = await Q._r_reglages(b.g, b.fondateur, {}, {"nombre": 26, "version": reg[1]["reglages"]["version"]})
        return banque, m, conflit, retire, neuve, hors_ligne, mauvais, bilan_semis, apres, lns, lns_conflit, \
            lns_mauvais, liens_apres, reg, reg_conflit, reg_mauvais
    (banque, m, conflit, retire, neuve, hors_ligne, mauvais, bilan_semis, apres, lns, lns_conflit, lns_mauvais,
     liens_apres, reg, reg_conflit, reg_mauvais) = run(scenario())
    assert len(banque["questions"]) == 12 and banque["reglages"]["nombre"] == 10 and banque["reglages"]["annonce"] == 10
    assert banque["limites"]["par_envoi"] == 25 and banque["themes"]["movie3"] and banque["derniere_selection"] is None
    assert [x["titre"] for x in banque["liens"]] == ["Wiki du jeu", "Le dernier film (vidéo)", "Guide du clan"]
    fuyante = next(q for q in banque["questions"] if q["id"] == "ex-fuite-01")
    assert fuyante["fuite"] == "Vent Noir" and not fuyante["posable"]
    sources = {q["id"]: q["source_dans_les_liens"] for q in banque["questions"]}
    assert sources["ex-movie3-01"] is True, "la vidéo des liens, minutage ou pas : la même page"
    assert sources["ex-studio-01"] is False and sources["ex-clan-01"] is None
    assert banque["sources_sans_lien"][0] == {"url": "https://exemple.fandom.com/wiki/Studio", "questions": 2}
    assert "https://exemple.fandom.com/wiki/Navires" not in [x["url"] for x in banque["sources_sans_lien"]], \
        "une question qui ne part pas ne demande pas de lien"
    assert m[0] == 200 and m[1]["question"]["version"] == 2 and m[1]["question"]["modifiee"]
    assert m[1]["question"]["maj_par"]["id"] == str(FONDATEUR)
    assert conflit[0] == 409 and conflit[1]["conflit"] and conflit[1]["actuelle"]["reponse"] == "Le Léviathan noir"
    assert retire[0] == 200 and retire[1]["question"]["retiree"] and not retire[1]["question"]["posable"]
    assert neuve[0] == 200 and neuve[1]["cree"] and neuve[1]["question"]["theme"] == "movie3"
    assert neuve[1]["question"]["statut"] == "confirme" and neuve[1]["question"]["origine"] == "site"
    assert hors_ligne[0] == 200 and hors_ligne[1]["question"]["id"] == "op-1234", "un identifiant venu d'une page hors ligne"
    assert [x[0] for x in mauvais] == [400] * 7 + [409], [x[1] for x in mauvais]
    assert bilan_semis == {"ajoutees": 1, "mises_a_jour": 1, "liens": 0}
    assert apres["ex-jeu-03"]["reponse"] == "Charpentier (corrigé)" and apres["ex-jeu-03"]["version"] == 2
    assert apres["ex-jeu-01"]["reponse"] == "Le Léviathan noir", "modifiée sur le site : jamais remplacée"
    assert apres["ex-clan-01"]["retiree"] and apres["ex-clan-01"]["reponse"] == "GoRP", "retirée : jamais ressuscitée"
    assert "ex-nouvelle" in apres
    assert lns[0] == 200 and [x["titre"] for x in lns[1]["liens"]] == ["Wiki officiel", "Le film"]
    assert lns_conflit[0] == 409 and lns_conflit[1]["conflit"] and len(lns_conflit[1]["actuelle"]["liens"]) == 2
    assert [x[0] for x in lns_mauvais] == [400, 400, 400]
    assert [x["titre"] for x in liens_apres] == ["Wiki officiel", "Le film"], "la liste du site n'est plus complétée"
    assert reg[0] == 200 and reg[1]["reglages"]["nombre"] == 4 and reg[1]["reglages"]["annonce"] == 4
    assert reg_conflit[0] == 409 and reg_conflit[1]["actuelle"]["nombre"] == 4
    assert reg_mauvais[0] == 400


# ═══ 11. Les modèles, la dernière sélection, les questions ignorées ════════════════════════════════════════════════

def test_Q12_modeles_derniere_selection_et_questions_ignorees(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        cree = await Q._r_modele(b.g, b.fondateur, {}, {"nom": "Movie 3 d'abord", "questions": [
            "ex-movie3-01", "ex-movie3-02", "ex-movie3-03", "ex-clan-01"], "par_defaut": True})
        mid = cree[1]["modele"]["id"]
        autre = await Q._r_modele(b.g, b.direction, {}, {"id": "op-modele-1", "nom": "Studio", "questions": [
            "ex-studio-01", "ex-studio-02"], "par_defaut": True})
        liste = await Q._r_modeles(b.g, b.fondateur, {}, None)
        refaire_defaut = await Q._r_modele(b.g, b.fondateur, {}, {"id": mid, "nom": "Movie 3 d'abord", "questions": [
            "ex-movie3-01", "ex-movie3-02", "ex-movie3-03", "ex-clan-01"], "par_defaut": True, "version": 2})
        conflit = await Q._r_modele(b.g, b.fondateur, {}, {"id": mid, "nom": "x", "questions": ["ex-jeu-01"],
                                                           "version": 1})
        mauvais = [await Q._r_modele(b.g, b.fondateur, {}, x) for x in (
            {"nom": "", "questions": ["ex-jeu-01"]}, {"nom": "a", "questions": []},
            {"nom": "a", "questions": ["ex-jeu-01", "ex-jeu-01"]}, {"nom": "a", "questions": ["inconnue"]},
            {"nom": "a" * 61, "questions": ["ex-jeu-01"]}, {"nom": "a", "questions": [f"q{k}" for k in range(26)]})]
        await Q._r_question_retirer(b.g, b.fondateur, {}, {"id": "ex-clan-01"})
        annonce = await Q.annonce(b.g.id)
        #  Ticket 1 : « Envoyer le questionnaire » = le modèle par défaut (la retirée ignorée proprement).
        t1, f1 = await _ouvrir_avec_carte(b)
        clic = await _cliquer(b, Q.BoutonEtape1("e", t1), b.fondateur, f1)
        e1 = await Q._envoi((await Q._suivi(b.g.id, t1))["envoi_id"])
        banque = await Q.banque(b.g)
        #  Ticket 2 : « Reprendre la sélection précédente » en un clic.
        t2, _f2 = await _ouvrir_avec_carte(b)
        derniere = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t2, "decision": "etape2", "derniere": True})
        e2 = await Q._envoi(derniere[1]["envoi"])
        #  Ticket 3 : des questions cochées, dont une retirée et une inconnue → `ignorees` + `motifs`.
        t3, _f3 = await _ouvrir_avec_carte(b)
        coches = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t3, "decision": "etape2", "questions": [
            "ex-jeu-02", "ex-clan-01", "inconnue", "ex-fuite-01", "ex-jeu-02", "ex-verif-01"]})
        e3 = await Q._envoi(coches[1]["envoi"])
        #  Ticket 4 : un modèle choisi ; puis les refus de forme.
        t4, _f4 = await _ouvrir_avec_carte(b)
        par_modele = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t4, "decision": "etape2",
                                                              "modele": "op-modele-1"})
        t5, _f5 = await _ouvrir_avec_carte(b)
        deux_choix = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t5, "decision": "etape2", "derniere": True,
                                                             "modele": mid})
        rien = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t5, "decision": "etape2", "questions": []})
        que_des_retirees = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t5, "decision": "etape2",
                                                                   "questions": ["ex-clan-01", "ex-fuite-01"]})
        modele_parti = await Q._r_modele_retirer(b.g, b.fondateur, {}, {"id": "op-modele-1"})
        deja_parti = await Q._r_modele_retirer(b.g, b.fondateur, {}, {"id": "op-modele-1"})
        par_modele_parti = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t5, "decision": "etape2",
                                                                    "modele": "op-modele-1"})
        return (cree, autre, liste, refaire_defaut, conflit, mauvais, annonce, clic, e1, banque, derniere, e2, coches,
                e3, par_modele, deux_choix, rien, que_des_retirees, modele_parti, deja_parti, par_modele_parti)
    (cree, autre, liste, refaire, conflit, mauvais, annonce, clic, e1, banque, derniere, e2, coches, e3, par_modele,
     deux_choix, rien, que_des_retirees, modele_parti, deja_parti, par_modele_parti) = run(scenario())
    assert cree[0] == 200 and cree[1]["modele"]["par_defaut"] and cree[1]["annonce"] == 4
    assert autre[0] == 200 and autre[1]["modele"]["id"] == "op-modele-1" and autre[1]["annonce"] == 2
    defauts = [m for m in liste[1]["modeles"] if m["par_defaut"]]
    assert [m["id"] for m in defauts] == ["op-modele-1"], "un seul modèle par défaut"
    assert refaire[0] == 200 and refaire[1]["modele"]["par_defaut"] and refaire[1]["annonce"] == 4
    assert conflit[0] == 409 and conflit[1]["conflit"]
    assert [x[0] for x in mauvais] == [400] * 6, [x[1] for x in mauvais]
    assert annonce == 3, "le modèle par défaut moins la question retirée"
    assert "3 questions" in clic.texte() and "1 question(s) ignorée(s)" in clic.texte()
    assert [q["id"] for q in e1["questions"]] == ["ex-movie3-01", "ex-movie3-02", "ex-movie3-03"]
    assert e1["origine"].startswith("modele:")
    d = banque["derniere_selection"]
    assert d["questions"] == ["ex-movie3-01", "ex-movie3-02", "ex-movie3-03"] and d["candidat"] == f"Pirate{CANDIDAT}"
    assert derniere[0] == 200 and [q["id"] for q in e2["questions"]] == d["questions"] and e2["origine"] == "derniere"
    assert coches[0] == 200 and [q["id"] for q in e3["questions"]] == ["ex-jeu-02", "ex-verif-01"]
    assert coches[1]["ignorees"] == ["ex-clan-01", "inconnue", "ex-fuite-01"]
    assert coches[1]["motifs"] == {"ex-clan-01": "retiree", "inconnue": "inconnue", "ex-fuite-01": "inactive"}
    assert coches[1]["explications"] == {"ex-clan-01": "elle a été retirée de la banque",
                                         "inconnue": "elle n'existe pas (ou plus) dans la banque",
                                         "ex-fuite-01": "elle est désactivée"}
    assert par_modele[0] == 200 and par_modele[1]["questions"] == 2
    assert deux_choix[0] == 400 and rien[0] == 400
    assert que_des_retirees[0] == 409 and que_des_retirees[1]["ignorees"] == ["ex-clan-01", "ex-fuite-01"]
    assert modele_parti[0] == 200 and deja_parti[0] == 404 and par_modele_parti[0] == 404


def test_Q13_une_question_qui_en_devoile_une_autre_ou_un_lien_qui_dit_la_reponse(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        await Q._r_question(b.g, b.fondateur, {}, {"id": "q-indice", "theme": "jeu", "confirme": True,
                                                   "question": "Quel est le point faible du Léviathan ?",
                                                   "reponse": "Les yeux"})
        t1, _f1 = await _ouvrir_avec_carte(b)
        ensemble = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t1, "decision": "etape2",
                                                            "questions": ["q-indice", "ex-jeu-01", "ex-jeu-02"]})
        r0 = await Q.reglages(b.g.id)
        await Q._r_liens(b.g, b.fondateur, {}, {"version": r0["liens_version"], "liens": [
            {"titre": "Le Charpentier, métier", "url": "https://exemple.fandom.com/wiki/Metiers"}]})
        t2, _f2 = await _ouvrir_avec_carte(b)
        lien = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t2, "decision": "etape2",
                                                        "questions": ["ex-jeu-03", "ex-jeu-02"]})
        r1 = await Q.reglages(b.g.id)
        await Q._r_reglages(b.g, b.fondateur, {}, {"nombre": 8, "version": r1["version"]})
        autos = [await Q.selection(b.g.id, None) for _ in range(6)]
        return ensemble, lien, autos, await Q.banque(b.g)
    ensemble, lien, autos, banque = run(scenario())
    assert ensemble[0] == 200 and ensemble[1]["questions"] == 2
    assert ensemble[1]["motifs"] == {"ex-jeu-01": "reponse_visible"}, "« Léviathan » se lirait dans l'autre question"
    assert ensemble[1]["explications"] == {"ex-jeu-01": "« Léviathan » se lit dans la question q-indice"}
    assert lien[0] == 200 and lien[1]["motifs"] == {"ex-jeu-03": "reponse_visible"}, "un lien qui dit la réponse"
    assert lien[1]["explications"]["ex-jeu-03"] == "« Charpentier » se lit dans les liens du questionnaire"
    marquee = {q["id"]: q["dans_les_liens"] for q in banque["questions"]}
    assert marquee["ex-jeu-03"] == "Charpentier" and marquee["ex-jeu-01"] == "", "la banque le montre d'avance"
    for st, sel in autos:
        choisies = [q["id"] for q in sel["questions"]]
        assert st == 200 and len(choisies) == 8, "la sélection automatique en prend d'autres : le nombre reste"
        assert "ex-jeu-03" not in choisies, "elle évite la question dont un lien dit la réponse"
        assert not {"q-indice", "ex-jeu-01"} <= set(choisies), "et jamais une question qui en dévoile une autre"


# ═══ 12. Renvoyer d'autres questions, refuser après l'étape 2 ═══════════════════════════════════════════════════════

def test_Q14_renvoyer_puis_refuser_message_neutre_et_fermeture(tmp_path):
    b = Banc(tmp_path)
    collecte = []

    async def scenario():
        r = await _parcours_jusqu_aux_reponses(b, collecte)
        tid, fil, eid = r[:3]
        renvoi = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "renvoyer",
                                                           "questions": ["ex-verif-01", "ex-jeu-02"]})
        e2 = renvoi[1]["envoi"]
        m = (await _cliquer(b, Q.BoutonRepondre(e2), b.candidat, fil)).response.modals[0]
        renvoi_encore = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "renvoyer", "derniere": True})
        e3 = renvoi_encore[1]["envoi"]
        vieux = await _soumettre(b, m, b.candidat, {1: "x", 2: "y"}, fil)
        sans_reponse = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        refus = await Q._r_decision(b.g, b.direction, {}, {"ticket": tid, "decision": "refuser",
                                                          "motif": "deux réponses fausses"})
        await laisser_finir()
        apres = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter", "forcer": True})
        return tid, fil, eid, renvoi, e2, renvoi_encore, e3, vieux, sans_reponse, refus, apres, \
            await Q.dossier(b.g, tid), await b.statut_ticket(tid)
    tid, fil, eid, renvoi, e2, renvoi_encore, e3, vieux, sans_reponse, refus, apres, dossier, statut = run(scenario())
    assert renvoi[0] == 200 and renvoi[1]["questions"] == 2
    nouvelles = [v for v in _vues_du_fil(fil) if "nouveau questionnaire" in textes(v)]
    assert len(nouvelles) == 2 and "Step 2 — new questionnaire · 2 questions" in textes(nouvelles[0])
    assert any(mid != 0 and "Questionnaire remplacé" in textes(kw["view"]) for mid, kw in fil.cartes), \
        "le questionnaire non répondu, remplacé, le dit"
    assert Q.REMPLACE.split("\n")[0] in vieux.texte(), "un formulaire d'un questionnaire remplacé n'écrit rien"
    assert sans_reponse[0] == 409 and sans_reponse[1]["forcer_possible"], \
        "le questionnaire en cours n'a pas de réponses : l'ancien (10/10 répondu) ne décide pas à sa place"
    assert refus[0] == 200
    message = [v for v in _vues_du_fil(fil) if Q.REFUS_FINAL.split("\n")[0] in textes(v)]
    assert len(message) == 1 and "deux réponses fausses" not in textes(message[0]), "neutre : jamais où il a eu faux"
    assert b.decisions == [(tid, DIRECTION, False, "étape 2 — deux réponses fausses")] and statut == "closed"
    assert apres[0] == 409, "le ticket est fermé"
    assert dossier["etape"] == "refuse" and [e["statut"] for e in dossier["envois"]] == ["repondu", "remplace", "clos"]
    assert [d["quoi"] for d in dossier["decisions"]] == ["questionnaire", "reponses", "renvoi", "renvoi", "refuse"]


# ═══ 13. Redémarrage pendant la fermeture prévue, pannes de Discord ════════════════════════════════════════════════

def test_Q15_fermeture_prevue_reprise_apres_redemarrage_et_reessayee(tmp_path, monkeypatch):
    b = Banc(tmp_path)
    monkeypatch.setattr(Q, "DELAI_FERMETURE", 3600.0)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "refuser"})
        prevue = (await Q._suivi(b.g.id, tid))["fermeture_le"]
        b.monter()                       # ⟳ arrêt du bot avant la fermeture (la tâche en mémoire est perdue)
        async with b.get_db() as db:     # l'heure prévue est passée pendant l'arrêt
            await db.execute("UPDATE recrutement_suivi SET fermeture_le=1 WHERE ticket_id=?", (tid,))
            await db.commit()
        b.echecs = 2                     # Discord en panne aux deux premiers essais
        await Q.demarrer(Obj(guilds=[b.g], get_guild=lambda gid: b.g))
        await laisser_finir()
        return st, corps, prevue, tid, await Q._suivi(b.g.id, tid), await b.statut_ticket(tid)
    st, corps, prevue, tid, s, statut = run(scenario())
    assert st == 200 and "se ferme dans 3600 s" in corps["message"] and prevue > 0
    assert b.decisions == [(tid, FONDATEUR, False, "étape 1")] * 3, "deux essais en panne, le troisième ferme"
    assert statut == "closed" and s["fermeture_le"] == 0, "reprise au démarrage, réessayée pendant la panne"


def test_Q16_pannes_de_discord_rien_de_faux_n_est_enregistre(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        b.panne = True
        lecture = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "etape2"})
        b.panne = False

        async def refuse(*_a, **_k):
            raise discord.HTTPException(Obj(status=500, reason="x"), "panne")
        fil.send = refuse
        envoi = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "etape2"})
        refus = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "refuser"})
        async with b.get_db() as db:
            async with db.execute("SELECT statut FROM recrutement_envois") as cur:
                statuts = [r[0] for r in await cur.fetchall()]
        inconnu = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": 999, "decision": "etape2"})
        support_tid, _f = await b.ouvrir(pid="p2")
        support = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": support_tid, "decision": "etape2"})
        mal = [await Q._r_etape1(b.g, b.fondateur, {}, x) for x in (None, {"ticket": "abc"}, {"ticket": tid},
                                                                   {"ticket": tid, "decision": "accepter"})]
        return lecture, envoi, refus, statuts, inconnu, support, mal, await Q._suivi(b.g.id, tid), \
            await Q.derniere_selection(b.g.id)
    lecture, envoi, refus, statuts, inconnu, support, mal, s, derniere = run(scenario())
    assert lecture[0] == 503 and envoi[0] == 503 and refus[0] == 503
    assert statuts == ["annule"] and s["etape"] == "etape1" and s["fermeture_le"] == 0, "rien n'a changé"
    assert derniere is None, "un envoi annulé n'est pas « la sélection précédente »"
    assert inconnu[0] == 404 and support[0] == 404, "un ticket Support n'est pas une candidature"
    assert [x[0] for x in mal] == [400, 400, 400, 400]


# ═══ 14. Le dossier d'un ticket fermé autrement, la liste du site, la rétention ═══════════════════════════════════

def test_Q17_dossier_ferme_par_l_ancienne_carte_suivi_et_retention(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        t1, _f1 = await _ouvrir_avec_carte(b)
        t2, _f2 = await _ouvrir_avec_carte(b)
        await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t2, "decision": "etape2"})
        liste = await Q._r_suivi(b.g, b.fondateur, {}, None)
        await b.decider(b.g, t1, b.fondateur, True, "")      # l'ancienne carte « Accepter » (sans ce module)
        d1 = await Q._r_dossier(b.g, b.fondateur, {"ticket": str(t1)}, None)
        mal = await Q._r_dossier(b.g, b.fondateur, {"ticket": "x"}, None)
        absent = await Q._r_dossier(b.g, b.fondateur, {"ticket": "4242"}, None)
        liste2 = await Q._r_suivi(b.g, b.fondateur, {}, None)
        async with b.get_db() as db:
            await db.execute("UPDATE recrutement_envois SET cree_le=1")
            await db.execute("UPDATE recrutement_suivi SET maj_le=1")
            await db.commit()
        n = await Q.purger()
        async with b.get_db() as db:
            async with db.execute("SELECT COUNT(*) FROM recrutement_envois") as cur:
                restants = (await cur.fetchone())[0]
        return t1, t2, liste, d1, mal, absent, liste2, n, restants
    t1, t2, liste, d1, mal, absent, liste2, n, restants = run(scenario())
    assert liste[0] == 200 and [o["ticket"] for o in liste[1]["ouverts"]] == [t1, t2]
    o2 = liste[1]["ouverts"][1]
    assert o2["etape"] == "etape2" and o2["envoi"]["nb"] == 10 and o2["envoi"]["bilan"]["repondues"] == 0
    assert o2["candidat"]["id"] == str(CANDIDAT) and o2["annonce"] == 10
    assert d1[0] == 200 and d1[1]["etape"] == "accepte" and d1[1]["statut_ticket"] == "ferme"
    assert d1[1]["peut"]["accepter"] is False and d1[1]["peut"]["etape1"] is False
    assert mal[0] == 400 and absent[0] == 404
    assert [o["ticket"] for o in liste2[1]["ouverts"]] == [t2] and liste2[1]["recents"][0]["ticket"] == t1
    assert n == 1 and restants == 0


# ═══ 15. Les mots pour soi s'effacent ; les vues éphémères ne sont pas gardées ════════════════════════════════════

def test_Q18_les_mots_pour_soi_s_effacent_et_ne_tuent_aucun_bouton(tmp_path, monkeypatch):
    b = Banc(tmp_path)
    monkeypatch.setattr(Q, "AVIS_S", 0.01)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        refuse = await _cliquer(b, Q.BoutonEtape1("e", tid), b.autre, fil)
        await laisser_finir()
        return refuse
    refuse = run(scenario())
    assert refuse.effaces == 1 and refuse.response.defers == [{"ephemeral": True, "thinking": True}], \
        "« réfléchit » pour soi : l'effacement vise ce mot, jamais la carte du bouton"
    assert all(v.is_finished() for v in refuse.vues())


# ═══ 16. Persistance et branchement dans bot.py ═══════════════════════════════════════════════════════════════════

def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def test_Q19_boutons_persistants_enregistres_et_routes_du_site(tmp_path):
    async def scenario():
        envoi = {"id": 3, "candidat_id": CANDIDAT, "questions": [{"rang": 1, "id": "a", "question": "Une question ?"}],
                 "liens": []}
        vues = [Q.carte_etape1(7), Q.carte_etape1(7, "envoye", nombre=3, par=1, quand=1),
                Q.carte_etape1(7, "reponses", nombre=3, candidat=1, quand=1), *Q.cartes_etape2(envoi),
                Q._vue_texte("x", boutons=[Q.BoutonPage(3, 2, 2)])]
        return vues
    vues = run(scenario())
    for v in vues:
        assert all(isinstance(x, discord.ui.DynamicItem) or not x.is_dispatchable() for x in v.walk_children()), \
            "une vue mixte (DynamicItem + bouton ordinaire) effacerait, en expirant, le gabarit global"
    gabarits = [c.__discord_ui_compiled_template__ for c in Q.BOUTONS_PERSISTANTS]
    tous = [cid for v in vues for cid in ids(v)]
    assert tous and all(any(g.fullmatch(cid) for g in gabarits) for cid in tous), tous
    assert ("bot.add_dynamic_items(questionnaire.BoutonEtape1, questionnaire.BoutonRepondre, "
            "questionnaire.BoutonPage)") in SRC, "les trois capteurs sont enregistrés au démarrage"
    for c in Q.BOUTONS_PERSISTANTS:
        assert f"questionnaire.{c.__name__}" in SRC
    boot = _source("_activite_boot")
    for bout in ("with _Etape('questionnaire'):", "questionnaire.setup(get_db=get_db", "ticket_ouvert=_ticket_ouvert",
                 "decider=_decision_recrutement", "autorise=_peut_decider", "lien=tableau.lien_pour",
                 "await questionnaire.init_db()", "if hasattr(tableau, 'monter'):",
                 "tableau.monter(questionnaire.ROUTES_SITE)", "if hasattr(tableau, 'ajouter_regle'):",
                 "tableau.ajouter_regle(**questionnaire.REGLE_NETTOYAGE)", "await questionnaire.demarrer(bot)"):
        assert bout in boot, bout
    corps = _source("_create_ticket_corps")
    assert "await _accueil_recrutement(i.guild, ch, tid, i.user.id, pnl)" in corps
    assert "if welcome_message and not recrutement:" in SRC, "un seul accueil pour un ticket du clan"
    format_route = re.compile(r"[a-z0-9_]{1,40}(?:/[a-z0-9_]{1,40}){0,4}")
    attendu = {"recrutement/banque": ("GET", False), "recrutement/modeles": ("GET", False),
               "recrutement/suivi": ("GET", False), "recrutement/dossier": ("GET", False),
               "recrutement/question": ("POST", True), "recrutement/question/retirer": ("POST", True),
               "recrutement/liens": ("POST", True), "recrutement/reglages": ("POST", True),
               "recrutement/modele": ("POST", True), "recrutement/modele/retirer": ("POST", True),
               "recrutement/corriger": ("POST", True), "recrutement/etape1": ("POST", False),
               "recrutement/decision": ("POST", False)}
    assert set(Q.ROUTES_SITE) == set(attendu)
    for nom, (methode, hors_ligne) in attendu.items():
        r = Q.ROUTES_SITE[nom]
        assert format_route.fullmatch(nom) and r["methode"] == methode and r["hors_ligne"] is hors_ligne, nom
        assert r["ecriture"] is (methode == "POST") and asyncio.iscoroutinefunction(r["fn"])
        assert list(__import__("inspect").signature(r["fn"]).parameters) == ["g", "auteur", "requete", "corps"]
    assert Q.ROUTES_SITE["recrutement/decision"]["grave"] == "roles", "accepter donne le rôle du clan"
    #  Les règles du registre de tableau.py (`_normaliser_route`) : une lecture n'écrit pas et ne se rejoue pas,
    #  seule une écriture se rejoue hors ligne, un corps borné, un genre grave connu.
    import tableau
    for nom, r in Q.ROUTES_SITE.items():
        if r["methode"] == "GET":
            assert not r["ecriture"] and not r["hors_ligne"] and r["corps_max"] == 0, nom
        assert not r["hors_ligne"] or r["ecriture"], nom
        assert isinstance(r["corps_max"], int) and 0 <= r["corps_max"] <= 12 * 1024 * 1024, nom
        assert r["grave"] is None or r["grave"] in tableau.LIMITES_GRAVES, nom
    regle = Q.REGLE_NETTOYAGE
    assert format_route.fullmatch(regle["cle"]) and "/" not in regle["cle"]
    assert 0 <= regle["min"] <= regle["garde_jours"] <= regle["max"] <= 3650
    assert callable(regle["fn"]) and callable(regle["compter"]) and len(regle["nom"]) <= 60


def test_Q20_l_accueil_d_un_ticket_du_clan_dans_le_bot(tmp_path):
    b = Banc(tmp_path)
    envois, erreurs = [], []

    async def webhook_send(ch, profil, **kw):
        envois.append((ch, profil, kw))

    ns = {"discord": discord, "questionnaire": Q, "recrutements": recrutements, "webhook_send": webhook_send,
          "_logerr": lambda ou, ex, **k: erreurs.append(ou)}
    exec(_source("_accueil_recrutement"), ns)  # noqa: S102 — code du dépôt

    async def panne(*_a, **_k):
        raise RuntimeError("base occupée")

    async def scenario():
        await b.preparer()
        tid, fil = await b.ouvrir()
        await ns["_accueil_recrutement"](b.g, fil, tid, CANDIDAT, b.conf["ticket_panels"]["p1"])
        t2, f2 = await b.ouvrir()
        ns["questionnaire"] = Obj(vue_accueil=panne, poser_etape1=panne)
        await ns["_accueil_recrutement"](b.g, f2, t2, CANDIDAT, b.conf["ticket_panels"]["p1"])
        return tid, fil, t2, f2
    tid, fil, t2, f2 = run(scenario())
    (ch, profil, kw), = envois
    assert ch is fil and profil == "ticket" and kw["allowed_mentions"].users is False
    t = textes(kw["view"])
    assert "**10 questions**" in t and "Bienvenue à bord !" in t and "-# Rell Seas" in t
    assert ids(_vues_du_fil(fil)[-1])[0] == f"rq:e1:e:{tid}"
    assert erreurs == ["recrutement.accueil", "recrutement.carte"], "la panne est dite, le ticket reste ouvert"
    assert ids(_vues_du_fil(f2)[-1]) == [f"recr:dec:a:{t2}", f"recr:dec:r:{t2}"], \
        "sans la nouvelle carte, l'ancienne décision (accepter, refuser) reste possible"


# ═══ 17. Le journal du site, la règle de nettoyage ═════════════════════════════════════════════════════════════════

def test_Q21_phrases_du_journal_du_site_et_regle_de_nettoyage(tmp_path):
    b = Banc(tmp_path)

    async def scenario():
        await b.preparer()
        q = await Q._r_question(b.g, b.fondateur, {}, {"theme": "jeu", "question": "Quel métier pêche les perles ?",
                                                       "reponse": "Plongeur"})
        mauvaise = await Q._r_question(b.g, b.fondateur, {}, {"theme": "jeu", "question": "x", "reponse": "y"})
        retiree = await Q._r_question_retirer(b.g, b.fondateur, {}, {"id": q[1]["question"]["id"]})
        reg = await Q._r_reglages(b.g, b.fondateur, {}, {"nombre": 5, "version": 1})
        modele = await Q._r_modele(b.g, b.fondateur, {}, {"nom": "Court", "questions": ["ex-jeu-01"], "par_defaut": True})
        t1, f1 = await _ouvrir_avec_carte(b)
        envoi = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t1, "decision": "etape2"})
        eid = envoi[1]["envoi"]
        page = (await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, f1)).response.modals[0]
        await _soumettre(b, page, b.candidat, {1: "Léviathan"}, f1)
        corr = await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": "ex-jeu-01", "juste": True})
        t2, _f2 = await _ouvrir_avec_carte(b)
        await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": t2, "decision": "etape2"})
        avant = await Q.compter_regle(b.g.id, 30, maintenant=10 ** 10)
        acceptee = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": t1, "decision": "accepter"})
        apres = await Q.compter_regle(b.g.id, 30, maintenant=10 ** 10)
        retires = await Q.nettoyer_regle(b.g.id, 30, maintenant=10 ** 10)
        async with b.get_db() as db:
            async with db.execute("SELECT ticket_id FROM recrutement_envois") as cur:
                restants = [r[0] for r in await cur.fetchall()]
            async with db.execute("SELECT COUNT(*) FROM recrutement_reponses") as cur:
                reponses = (await cur.fetchone())[0]
        return q, mauvaise, retiree, reg, modele, envoi, corr, avant, acceptee, apres, retires, restants, reponses, t2
    (q, mauvaise, retiree, reg, modele, envoi, corr, avant, acceptee, apres, retires, restants, reponses,
     t2) = run(scenario())
    assert q[1]["_journal"] == {"texte": "Recrutement : question « Quel métier pêche les perles ? » ajoutée"}
    assert "_journal" not in mauvaise[1], "une écriture refusée ne s'écrit pas au journal"
    assert retiree[1]["_journal"]["texte"].endswith("» retirée")
    assert reg[1]["_journal"]["texte"] == "Recrutement : 5 question(s) par défaut à l'étape 2"
    assert modele[1]["_journal"]["texte"] == "Recrutement : modèle « Court » créé (sélection par défaut)"
    assert envoi[0] == 200 and envoi[1]["_journal"] is None, "la décision est au journal du clan, une seule fois"
    assert any(j[0] == "recrutement.questionnaire" for j in b.journal)
    assert corr[0] == 200 and corr[1]["_journal"] is None and acceptee[1]["_journal"] is None
    assert (avant, apres, retires) == (0, 1, 1), "un ticket ouvert garde son questionnaire ; un fermé part"
    assert restants == [t2] and reponses == 0
