"""26/10/2026 — le ticket de recrutement PROPRE et configurable (questionnaire.py, bot.py), vérifié sur le VRAI chemin
du bot : `tests/banc_ticket_recrutement.py` exécute les fonctions de bot.py (ouverture, équipe qui entre dans le fil,
décision, fermeture) sur le faux Discord, avec questionnaire.py branché comme au démarrage.

Le fondateur : « Ça envoie énormément de messages dans le ticket de ceux qui créent un ticket pour le recrutement…
je veux vraiment que tout soit configurable et que tout soit hyper propre. »

AVANT (mesuré sur le code du 26/10 avant ce chantier, même banc, `git archive 4f33fe0`) :
  · demande refusée à l'étape 1 : 4 messages du bot dès l'ouverture (le dossier « Ticket n°1 », l'accueil, la carte de
    l'étape 1, « L'équipe suit ce ticket »), 6 en tout, tous visibles à la fois ;
  · refusé après le questionnaire : 4 à l'ouverture, 7 en tout (+ le questionnaire, le refus, « Ticket fermé ») ;
  · accepté : 4 à l'ouverture, 7 en tout.
APRÈS (exigé ici) : AU PLUS DEUX messages du bot visibles à chaque instant — l'AFFICHE (réécrite, jamais renvoyée) et
le message de l'étape en cours ; jamais « L'équipe suit ce ticket » (l'équipe entre sans notification par une citation
sur l'affiche) ; ni numéro de ticket ni « Ticket fermé ». Postés en tout : 2 (demande refusée), 3 (refusé après le
questionnaire, accepté), 4 (accepté, questionnaire en deux étapes).

R01-R05 le compte des messages · R06 l'affiche · R07 « Direction » et la tête revérifiée à chaque clic · R08 la demande
approuvée avec des étapes et des questions écrites pour lui · R09 le contrat « passage d'étape » · R10 automatique ·
R11 sans questionnaire · R12 « Es-tu sûr », la fiche, l'élimination d'office · R13 la liste noire · R14 l'aperçu de
l'équipe (jamais un formulaire) · R15 la page web du candidat (module simulé) · R16 les chefs d'équipe · R17 la purge
exceptionnelle · R18 le nettoyage · R19 le parcours réglé sur le site (validation, version, avertissements, messages) ·
R20 les décidées · R21 un ticket d'avant l'affiche garde sa fermeture annoncée · R22 la carte RGPD · R23 les
avertissements stables · R24 le chef validé badgé et proposé en premier dans l'éditeur d'une équipe · R25-R27 le recrutement léger dans le
chargement du site (le suivi en une connexion, les décidées par morceaux, le résumé dans les données) · R28 un
numéro venu du client : des chiffres 0-9, sinon 400 (jamais 500)."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import discord
import pytest

import questionnaire as Q
import recrutements
import transcript_store
from banc_ticket_recrutement import (AUTRE, BancTicket, CANDIDAT, DIRECTION, FONDATEUR, Inter, RECRUTEUR)
from conftest_discord import Obj, laisser_finir
from faux_serveur import compter, ids, run, textes
import test_site_v2_port as _port

local = _port.local   # le vrai site local (R27 : les données de la page et la fiche d'un membre)

RESERVE = "Réservé au fondateur et à la direction."


@pytest.fixture(autouse=True)
def _sans_attente(monkeypatch):
    """Les délais du module à zéro (fermeture, mots qui s'effacent) : les tests ne dorment pas."""
    monkeypatch.setattr(Q, "DELAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "AVIS_S", 0)
    monkeypatch.setattr(Q, "PAGE_S", 0)
    monkeypatch.setattr(Q, "REESSAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "REPRISE_MIN", 0.0)
    monkeypatch.setattr(Q, "_delai", lambda p: 0.0)


def banc(tmp_path, **extra) -> BancTicket:
    b = BancTicket(tmp_path)
    b.logs_q = []
    b.monter(log=b.logs_q.append, **extra)
    return b


def sans_echec(b):
    """Aucun bouton ni formulaire en échec caché (le filet `_sans_echec` répondrait « souci » en silence)."""
    assert not [x for x in b.logs_q if "[RECRUTEMENT][E7]" in str(x)], b.logs_q
    assert not b.erreurs, b.erreurs


def vue_de(fil, m):
    return fil.vue(m)


def texte_message(fil, m) -> str:
    v = fil.vue(m)
    return (m.content or "") + " " + (textes(v) if v is not None else "")


def tout_le_fil(fil) -> str:
    return " ".join(texte_message(fil, m) for m in fil.messages)


async def parcours_regle(b, **reglage):
    """Le parcours du panneau p1, réglé comme sur le site."""
    corps = {"panneau": "p1", "version": 0, "mode": "approbation", "gabarit": [], "exigence": 100, "delai": 5,
             "liste_noire": True, "metier": True}
    corps.update(reglage)
    st, rep = await Q.enregistrer_parcours(b.g, b.fondateur, corps)
    assert st == 200, rep
    return rep


async def repondre_etape(b, fil, eid, membre=None):
    """Le candidat répond à l'étape OUVERTE, page par page (formulaires de Discord), avec les réponses attendues."""
    e = await Q._envoi(eid)
    attendues = {int(q["rang"]): q["reponse"] for q in e["questions"]}
    derniers = None
    for _ in range(20):
        i = Inter(b, membre or b.candidat, fil)
        await Q.BoutonRepondre(eid).callback(i)
        if not i.modals:
            return derniers or i
        modal = i.modals[0]
        for rang, champ in modal.champs:
            champ._value = attendues[rang]
        derniers = Inter(b, membre or b.candidat, fil)
        await modal.on_submit(derniers)
    raise AssertionError("trop de pages")


async def tout_corriger(b, eid, juste=True):
    for q in (await Q._envoi(eid))["questions"]:
        st, rep = await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": q["id"], "juste": juste})
        assert st == 200, rep


async def jusqu_aux_reponses(b, tid, fil):
    """La demande approuvée (le questionnaire prévu), puis chaque étape répondue et la suivante ouverte."""
    st, corps = await Q._r_etape_suivante(b.g, b.fondateur, {}, {"ticket": tid})
    assert st == 200, corps
    eid = (await Q._suivi(b.g.id, tid))["envoi_id"]
    for _ in range(Q.ETAPES_MAX + 1):
        await repondre_etape(b, fil, eid)
        if (await Q._envoi(eid))["statut"] == "repondu":
            return eid
        ok, message = await Q.etape_suivante(b.g, eid, b.fondateur)
        assert ok, message
    raise AssertionError("le questionnaire ne se termine pas")


DEUX_ETAPES = [{"titre": "Le studio", "consigne": "Ce que tu sais du studio.", "source": "tirage", "nombre": 2,
                "theme": "studio"},
               {"titre": "Le jeu", "consigne": "", "source": "tirage", "nombre": 3, "theme": "jeu"}]


# ═══ R01-R05 : le compte des messages — au plus deux à la fois, jamais « L'équipe suit ce ticket » ═══════════════════

def _sans_bruit(fil):
    t = tout_le_fil(fil)
    assert "L'équipe suit ce ticket" not in t, "la carte de l'équipe ne reste jamais"
    assert "Ticket fermé" not in t and "Ticket n°" not in t, "ni annonce de fermeture, ni numéro de ticket"


def test_R01_demande_refusee_deux_messages_en_tout(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        ouverture = list(fil.visibles())
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "refuser"})
        await laisser_finir()
        return tid, fil, ouverture, st, corps, await b.statut(tid)
    tid, fil, ouverture, st, corps, statut = run(sc())
    assert len(ouverture) == 1, "à l'ouverture : l'affiche seule (AVANT : 4 messages)"
    assert st == 200 and statut == "closed" and fil.supprime
    assert len(fil.messages) == 2 and fil.max_visibles <= 2, "AVANT : 6 messages, tous visibles"
    _sans_bruit(fil)
    assert {FONDATEUR, DIRECTION, RECRUTEUR} <= fil.dedans, "l'équipe est dans le fil (sans notification)"
    assert corps["mp"] is True and len(b.candidat.mp) == 1, "le refus part aussi en message privé"
    assert "n'est pas retenue" in textes(b.candidat.mp[0][1]["view"])
    sans_echec(b)


def test_R02_refuse_apres_le_questionnaire_trois_messages(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        await jusqu_aux_reponses(b, tid, fil)
        st, corps = await Q._r_decision(b.g, b.direction, {}, {"ticket": tid, "decision": "refuser",
                                                               "motif": "deux réponses fausses"})
        await laisser_finir()
        return tid, fil, st, corps, await b.statut(tid), await Q._suivi(b.g.id, tid)
    tid, fil, st, corps, statut, s = run(sc())
    assert st == 200 and statut == "closed" and s["etape"] == "refuse"
    assert len(fil.messages) == 3 and fil.max_visibles <= 2, "AVANT : 7 messages"
    _sans_bruit(fil)
    assert "deux réponses fausses" not in tout_le_fil(fil), "le motif reste à l'équipe"
    assert len(b.candidat.mp) == 2, "la demande acceptée, puis le refus"
    assert Q.sur_liste_noire is not None and run(Q.sur_liste_noire(b.g.id, CANDIDAT)), "liste noire (réglée)"
    sans_echec(b)


def test_R03_accepte_trois_messages_role_metier_et_message_prive(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        eid = await jusqu_aux_reponses(b, tid, fil)
        trop_tot = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        await tout_corriger(b, eid)
        st, corps = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        await laisser_finir()
        return tid, fil, trop_tot, st, corps, await b.statut(tid)
    tid, fil, trop_tot, st, corps, statut = run(sc())
    assert trop_tot[0] == 409 and trop_tot[1]["forcer_possible"], "100 % exigés : la correction d'abord"
    assert st == 200 and statut == "closed" and b.clan_r in b.candidat.roles, "le rôle du clan est donné"
    assert len(fil.messages) == 3 and fil.max_visibles <= 2, "AVANT : 7 messages"
    _sans_bruit(fil)
    decision = fil.vue(fil.messages[-1])
    assert "Bienvenue dans le clan" in textes(decision) and "choisis ton métier" in textes(decision)
    assert "https://discord.com/channels/1/2/3" in json.dumps(decision.to_components()), "le choix du métier"
    mp = textes(b.candidat.mp[-1][1]["view"])
    assert "Tu es accepté dans le clan" in mp and "Reste actif" in mp
    sans_echec(b)


def test_R04_deux_etapes_quatre_messages_jamais_plus_de_deux_a_la_fois(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, gabarit=DEUX_ETAPES)
        tid, fil = await b.ouvrir_ticket()
        eid = await jusqu_aux_reponses(b, tid, fil)
        await tout_corriger(b, eid)
        st, _corps = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        await laisser_finir()
        return fil, st, eid
    fil, st, eid = run(sc())
    assert st == 200
    assert len(fil.messages) == 4 and fil.max_visibles <= 2, "affiche, étape 2, étape 3, décision — deux à la fois"
    supprimes = [m for m in fil.messages if m.id in fil.monde.effaces]
    assert len(supprimes) >= 2, "chaque message d'étape s'efface quand la suite arrive"
    _sans_bruit(fil)
    sans_echec(b)


def test_R05_avec_la_page_web_les_memes_comptes(tmp_path):
    appels = []

    async def lien_candidat(i, ticket):
        appels.append(("lien", ticket))
        return f"https://bot.exemple/candidature/{ticket}"

    async def inviter(g, e):
        appels.append(("inviter", e["id"]))
        return True
    b = banc(tmp_path, web=Obj(lien_candidat=lien_candidat, inviter=inviter))

    async def sc():
        await b.preparer()
        await parcours_regle(b, gabarit=DEUX_ETAPES)
        tid, fil = await b.ouvrir_ticket()
        st, corps = await Q._r_etape_suivante(b.g, b.fondateur, {}, {"ticket": tid})
        assert st == 200, corps
        eid = (await Q._suivi(b.g.id, tid))["envoi_id"]
        message_etape = texte_message(fil, fil.messages[-1])
        clic = Inter(b, b.candidat, fil)
        await Q.BoutonRepondre(eid).callback(clic)
        #  La page web répond : ses fonctions (le contrat « passage d'étape »).
        e = await Q._envoi(eid)
        for k in (1, 2):
            async with b.get_db() as db:
                for q in [q for q in e["questions"] if int(q["etape"]) == k]:
                    await db.execute("INSERT OR REPLACE INTO recrutement_reponses (envoi_id, rang, guild_id, candidat_id,"
                                     " texte, recu_le) VALUES (?,?,?,?,?,1)", (eid, q["rang"], b.g.id, CANDIDAT,
                                                                               q["reponse"]))
                await db.execute("UPDATE recrutement_envois SET etape_envoyee=? WHERE id=?", (k, eid))
                await db.commit()
            if k == 1:
                await Q.etape_recue(b.g, await Q._envoi(eid), 1)
                ok, msg = await Q.etape_suivante(b.g, eid, b.fondateur)
                assert ok, msg
            else:
                e2 = await Q._envoi(eid)
                assert await Q.clore_envoi(e2, 2) is True and await Q.clore_envoi(e2, 3) is False, "une seule fin"
                await Q.annoncer_reponses(b.g, e2, 2)
        await tout_corriger(b, eid)
        st, _ = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        await laisser_finir()
        return tid, fil, clic, message_etape, st
    tid, fil, clic, message_etape, st = run(sc())
    assert st == 200 and len(fil.messages) == 4 and fil.max_visibles <= 2
    assert ("lien", tid) in appels and not clic.modals, "le candidat reçoit son lien, jamais un formulaire de Discord"
    assert any(f"https://bot.exemple/candidature/{tid}" in json.dumps(v.to_components()) for v in clic.vues())
    assert "**1.**" not in message_etape, "avec la page web, les questions ne sont pas recopiées dans le ticket"
    sans_echec(b)


# ═══ R06 : l'affiche ═══════════════════════════════════════════════════════════════════════════════════════════

def test_R06_l_affiche_cite_sans_prevenir_sans_numero_un_seul_bouton(tmp_path, monkeypatch):
    b = banc(tmp_path)
    monkeypatch.setattr(Q, "_banniere", lambda: "https://bot.exemple/v/recrutement_affiche.png?v=1")

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        return tid, fil, await Q._suivi(b.g.id, tid)
    tid, fil, s = run(sc())
    m = fil.messages[0]
    am = m.kw["allowed_mentions"]
    assert am.users is False and am.roles is False and am.everyone is False, "cité, jamais prévenu"
    vue = fil.vue(m)
    t = textes(vue)
    brut = json.dumps(vue.to_components(), ensure_ascii=False)
    assert '"type": 12' in brut and "recrutement_affiche.png" in brut, "la bannière (une galerie d'image)"
    assert f"<@{CANDIDAT}>" in t and "Bienvenue à bord !" in t, "le candidat cité, le mot du panneau"
    assert "Pour rejoindre le clan" in t, "les conditions"
    assert r"Kolax\_RS" in t and "16 – 17 ans" in t, "sa fiche : ce qu'il a répondu en ouvrant"
    assert "Étape 1 — ta fiche : reçue." in t, "où il en est"
    assert f"#{tid}" not in t and "Ticket n°" not in t, "aucun numéro de ticket"
    assert ids(vue) == [f"rq:e1:d:{tid}"], "un seul bouton, discret : « Direction »"
    assert compter(vue) <= 40 and len(t) <= 4000
    assert (s["carte"], s["carte_id"], s["mode"]) == ("affiche", m.id, "approbation")
    #  Les consignes suivent le registre (Textes & noms) et ses variables : sans fiche, « la demande attend ».
    attente = textes(Q.carte_affiche({"gid": b.g.id, "ticket": tid, "candidat": CANDIDAT, "etat": "demande",
                                      "nb_etapes": 2, "nb_questions": 12, "reponses": {}}))
    assert "ton questionnaire arrive ici même : 2 étapes, 12 questions." in attente and "2 steps, 12 questions" in attente


# ═══ R07 : « Direction » — la tête seule, revérifiée à chaque clic ═══════════════════════════════════════════════

def test_R07_direction_pour_la_tete_un_avis_court_pour_les_autres(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        out = {}
        for nom, qui in (("candidat", b.candidat), ("recruteur", b.recruteur), ("autre", b.autre),
                         ("fondateur", b.fondateur), ("direction", b.direction)):
            i = Inter(b, qui, fil)
            await Q.BoutonEtape1("d", tid).callback(i)
            out[nom] = i
        decisions = {}
        for code in ("n", "r", "a", "o", "s"):
            i = Inter(b, b.recruteur, fil)
            await Q.BoutonEtape1(code, tid).callback(i)
            decisions[code] = i
        refus = Inter(b, b.fondateur, fil)
        await Q.BoutonEtape1("r", tid).callback(refus)
        return tid, fil, out, decisions, refus, await Q._suivi(b.g.id, tid)
    tid, fil, out, decisions, refus, s = run(sc())
    for nom in ("candidat", "recruteur", "autre"):
        i = out[nom]
        assert " ".join(textes(v) for v in i.vues()) .strip().startswith(RESERVE), nom
        assert not any(ids(v) for v in i.vues()), f"{nom} : aucun bouton de décision"
    for nom in ("fondateur", "direction"):
        panneau = out[nom].vues()[-1]
        assert ids(panneau) == [f"rq:e1:n:{tid}", f"rq:e1:s:{tid}", f"rq:e1:r:{tid}", "ticket_ctrl_close"], nom
        assert "Direction" in textes(panneau) and panneau.is_finished(), "éphémère : une vue arrêtée"
    for code, i in decisions.items():
        assert not i.modals and RESERVE in " ".join(textes(v) for v in i.vues()), code
    assert isinstance(refus.modals[0], Q.FormulaireRefus), "la tête : le formulaire du refus"
    assert len(fil.messages) == 1 and s["etape"] == "etape1", "aucun clic n'a posté de message dans le ticket"
    sans_echec(b)


# ═══ R08 : la demande approuvée — les étapes de CE candidat, des questions écrites pour lui ═══════════════════════

def test_R08_approbation_etapes_choisies_question_ecrite_pour_lui(tmp_path):
    b = banc(tmp_path)
    etapes = [{"titre": "Le jeu", "consigne": "Ce que tu sais du jeu.", "questions": ["ex-jeu-01", "ex-jeu-02"],
               "nouvelles": [{"question": "Quel est le nom du navire amiral de l'équipage ?", "reponse": "La Sirène"}]},
              {"titre": "Le clan", "consigne": "", "questions": ["ex-clan-01"],
               "nouvelles": [{"question": "Qui a fondé l'équipage ?", "reponse": "GoRipe", "theme": "clan",
                              "banque": True}]}]

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        st_p, prop = await Q._r_proposition(b.g, b.fondateur, {"ticket": str(tid)}, None)
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "approuver", "etapes": etapes})
        e = await Q._envoi(corps["envoi"])
        banque = await Q.questions(b.g.id)
        return tid, fil, st_p, prop, st, corps, e, banque, await Q._suivi(b.g.id, tid)
    tid, fil, st_p, prop, st, corps, e, banque, s = run(sc())
    assert st_p == 200 and prop["fiche"] == 1 and prop["etapes"][0]["numero_candidat"] == 2, \
        "la proposition préremplie (sa fiche est l'étape 1)"
    assert all("reponse" not in q for x in prop["etapes"] for q in x["questions"]), "jamais une réponse attendue"
    assert st == 200 and corps["etapes"] == 2 and corps["questions"] == 5, corps
    assert [(x["numero"], x["titre"], x["consigne"]) for x in e["etapes"]] == \
        [(1, "Le jeu", "Ce que tu sais du jeu."), (2, "Le clan", "")]
    par_etape = {}
    for q in e["questions"]:
        par_etape.setdefault(q["etape"], []).append(q)
    assert [q["id"] for q in par_etape[1]][:2] == ["ex-jeu-01", "ex-jeu-02"]
    perso = par_etape[1][2]
    assert perso["id"].startswith("p-") and perso.get("perso") and perso["reponse"] == "La Sirène", \
        "la question écrite pour lui : dans son instantané seulement"
    assert perso["id"] not in {q["id"] for q in banque}, "pas dans la banque"
    ajoutee = par_etape[2][1]
    assert ajoutee["id"] in {q["id"] for q in banque} and ajoutee["question"] == "Qui a fondé l'équipage ?", \
        "« ajouter à la banque » : elle y entre aussi"
    assert [q["rang"] for q in e["questions"]] == [1, 2, 3, 4, 5], "un rang global"
    assert (e["etape_ouverte"], e["etape_envoyee"], e["etape_fiche"]) == (1, 0, 1), "le contrat « passage d'étape »"
    assert s["etape"] == "etape2" and len(fil.visibles()) == 2
    etape_msg = fil.messages[-1]
    assert [u.id for u in etape_msg.kw["allowed_mentions"].users] == [CANDIDAT], "le message de l'étape le PRÉVIENT"
    te = texte_message(fil, etape_msg)
    assert "**Étape 2 sur 3**" in te and "**Le jeu**" in te and "Ce que tu sais du jeu." in te
    assert "Quel est le nom du navire amiral" in te and "Qui a fondé" not in te, "seulement l'étape ouverte"
    assert "La Sirène" not in tout_le_fil(fil), "jamais une réponse attendue dans le ticket"
    assert "Étape 2 sur 3 : à toi." in texte_message(fil, fil.messages[0]), "l'affiche suit, réécrite"
    mp = textes(b.candidat.mp[-1][1]["view"])
    assert "Ta demande de recrutement est acceptée" in mp and f"<#{fil.id}>" in mp
    sans_echec(b)


def test_R08b_une_question_ecrite_qui_dit_sa_reponse_est_refusee(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, _fil = await b.ouvrir_ticket()
        return await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "approuver", "etapes": [
            {"titre": "", "questions": [], "nouvelles": [{"question": "Le navire s'appelle-t-il La Sirène ?",
                                                          "reponse": "La Sirène"}]}]}), \
            await Q._suivi(b.g.id, tid)
    (st, corps), s = run(sc())
    assert st == 400 and "apparaît dans la question" in corps["erreur"] and s["etape"] == "etape1"


# ═══ R09 : le contrat « passage d'étape » ══════════════════════════════════════════════════════════════════════

def test_R09_passage_d_etape_une_porte_a_la_fois(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, gabarit=DEUX_ETAPES)
        tid, fil = await b.ouvrir_ticket()
        st, corps = await Q._r_etape_suivante(b.g, b.fondateur, {}, {"ticket": tid})
        assert st == 200, corps
        eid = corps["envoi"]
        e = await Q._envoi(eid)
        premier_message = (await Q._envoi(eid))["message_etape"]
        trop_tot = await Q.etape_suivante(b.g, eid, b.fondateur)
        pages = Q.pages_envoi(e["questions"])
        page_2 = next(p for p, lot in enumerate(pages, 1) if lot[0]["etape"] == 2)
        triche = Inter(b, b.candidat, fil)
        await Q.soumettre_page(triche, eid, page_2, {int(q["rang"]): "x" for q in pages[page_2 - 1]})
        fin1 = await repondre_etape(b, fil, eid)
        apres1 = await Q._envoi(eid)
        encore = Inter(b, b.candidat, fil)
        await Q.BoutonRepondre(eid).callback(encore)
        hors_tete = await Q.etape_suivante(b.g, eid, b.recruteur)
        site_hors_tete = await Q._r_etape_suivante(b.g, b.recruteur, {}, {"envoi": eid})
        ok = await Q.etape_suivante(b.g, eid, b.fondateur)
        double = await Q.etape_suivante(b.g, eid, b.fondateur)
        apres2 = await Q._envoi(eid)
        await repondre_etape(b, fil, eid)
        fin = await Q._envoi(eid)
        derniere = await Q.etape_suivante(b.g, eid, b.fondateur)
        return (tid, fil, eid, premier_message, trop_tot, triche, fin1, apres1, encore, hors_tete, site_hors_tete, ok,
                double, apres2, fin, derniere, await Q._reponses(eid), await Q._suivi(b.g.id, tid))
    (tid, fil, eid, premier_message, trop_tot, triche, fin1, apres1, encore, hors_tete, site_hors_tete, ok, double,
     apres2, fin, derniere, reponses, s) = run(sc())
    assert trop_tot[0] is False and "pas encore envoyée" in trop_tot[1], "refus si l'étape n'est pas envoyée"
    assert "Cette étape n'est pas encore ouverte" in " ".join(textes(v) for v in triche.vues()), \
        "un formulaire de l'étape suivante, envoyé trop tôt : rien n'est gardé"
    assert apres1["etape_envoyee"] == 1 and apres1["statut"] in Q.EN_ATTENTE, "l'étape 1 envoyée, pas la fin"
    assert "Étape 2 envoyée" in " ".join(textes(v) for v in fin1.vues()), "il attend la décision de la direction"
    assert not encore.modals and "Étape 2 envoyée" in " ".join(textes(v) for v in encore.vues())
    m1 = next(m for m in fil.messages if m.id == premier_message)
    assert "réponses reçues" in texte_message(fil, m1) and m1.id in fil.monde.effaces, \
        "le message de l'étape est RÉÉCRIT (« réponses reçues »), puis supprimé quand la suivante s'ouvre"
    assert hors_tete == (False, RESERVE) and site_hors_tete[0] == 409, "la tête seule ouvre l'étape suivante"
    assert ok[0] is True and "Étape 3 ouverte" in ok[1]
    assert double[0] is False, "deux clics : une seule étape ouverte"
    assert apres2["etape_ouverte"] == 2 and apres2["message_etape"] != premier_message
    nouveau = next(m for m in fil.messages if m.id == apres2["message_etape"])
    assert [u.id for u in nouveau.kw["allowed_mentions"].users] == [CANDIDAT], "la nouvelle étape le prévient"
    assert fil.max_visibles <= 2
    assert fin["statut"] == "repondu" and fin["etape_envoyee"] == 2 and s["etape"] == "reponses"
    assert derniere[0] is False
    assert len(reponses) == len(fin["questions"]) and "x" not in reponses.values(), "rien n'a été volé à l'étape 2"
    assert any(j[0] == "recrutement.etape_recue" for j in b.journal) and \
        any(j[0] == "recrutement.etape_suivante" for j in b.journal)
    sans_echec(b)


def test_R09b_un_ancien_envoi_garde_son_fonctionnement(tmp_path):
    """Un questionnaire d'avant (`etape_ouverte = 0`) : tout est ouvert, il répond en une fois ; pas d'étape suivante."""
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "approuver"})
        eid = corps["envoi"]
        async with b.get_db() as db:
            await db.execute("UPDATE recrutement_envois SET etape_ouverte=0, etape_fiche=0 WHERE id=?", (eid,))
            await db.commit()
        refus = await Q.etape_suivante(b.g, eid, b.fondateur)
        await repondre_etape(b, fil, eid)
        return refus, await Q._envoi(eid)
    refus, e = run(sc())
    assert refus[0] is False and "pas d'étapes" in refus[1]
    assert e["statut"] == "repondu" and e["etape_ouverte"] == 0


# ═══ R10 / R11 : automatique, sans questionnaire ═══════════════════════════════════════════════════════════════

def test_R10_automatique_le_questionnaire_part_a_l_ouverture(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, mode="automatique")
        tid, fil = await b.ouvrir_ticket()
        s = await Q._suivi(b.g.id, tid)
        return tid, fil, s, await Q._envoi(s["envoi_id"])
    tid, fil, s, e = run(sc())
    assert s["mode"] == "automatique" and s["etape"] == "etape2" and e["origine"].startswith("ouverture")
    assert len(fil.messages) == 2 and fil.max_visibles <= 2, "l'affiche et le message de l'étape"
    assert "Étape 2 sur 2 : à toi." in texte_message(fil, fil.messages[0])
    assert not b.candidat.mp, "rien en privé : il est prévenu par le message de l'étape"
    sans_echec(b)


def test_R11_sans_questionnaire_la_decision_sur_la_fiche(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, mode="direct")
        tid, fil = await b.ouvrir_ticket()
        panneau = Inter(b, b.fondateur, fil)
        await Q.BoutonEtape1("d", tid).callback(panneau)
        envoi = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "approuver"})
        st, corps = await Q._r_decision(b.g, b.fondateur, {}, {"ticket": tid, "decision": "accepter"})
        await laisser_finir()
        return tid, fil, panneau, envoi, st, corps, await b.statut(tid)
    tid, fil, panneau, envoi, st, corps, statut = run(sc())
    assert "La direction lit ta fiche et te répond ici même." in texte_message(fil, fil.messages[0])
    assert ids(panneau.vues()[-1])[:3] == [f"rq:e1:a:{tid}", f"rq:e1:r:{tid}", f"rq:e1:s:{tid}"]
    assert envoi[0] == 409, "aucun questionnaire à envoyer"
    assert st == 200 and statut == "closed" and b.clan_r in b.candidat.roles
    assert len(fil.messages) == 2 and fil.max_visibles <= 2, "l'affiche et la décision"
    sans_echec(b)


# ═══ R12 : « Es-tu sûr ? », la fiche, l'élimination d'office ═══════════════════════════════════════════════════

FICHE = [{"titre": "Tranche d'âge", "aide": "Pour vérifier les conditions du clan.", "type": "choix",
          "options": ["Moins de 13 ans", "13 – 15 ans", "16 – 17 ans", "18 ans ou plus"],
          "eliminatoires": ["Moins de 13 ans"]},
         {"titre": "Pseudo Roblox", "type": "court", "max": 40, "exemple": "Kolax_RS"}]


async def _ouvrir_par_le_panneau(b, membre, choix: int, pseudo="Kolax_RS"):
    """Le panneau touché → « Es-tu sûr ? » → « Oui » → la fiche → envoyée."""
    i = Inter(b, membre)
    await b.ns["_ticket_ouvrir"](i, "p1")
    vue = i.messages[0]
    oui = next(x for x in vue.walk_children() if isinstance(x, discord.ui.Button) and x.label.startswith("Oui"))
    i2 = Inter(b, membre)
    await oui.callback(i2)
    fiche = i2.modals[0]
    for ch, comp in fiche.champs:
        if isinstance(comp, discord.ui.Select):
            comp._values = [str(choix)]
        else:
            comp._value = pseudo
    i3 = Inter(b, membre)
    await fiche.on_submit(i3)
    await laisser_finir()
    return i, vue, fiche, i3


def test_R12_confirmation_fiche_et_ticket(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, fiche=FICHE)
        i, vue, fiche, i3 = await _ouvrir_par_le_panneau(b, b.candidat, 2)
        async with b.get_db() as db:
            async with db.execute("SELECT id, answers FROM tickets") as cur:
                tickets = await cur.fetchall()
        return vue, fiche, i3, tickets
    vue, fiche, i3, tickets = run(sc())
    t = textes(vue)
    assert "Es-tu sûr de vouloir ouvrir une demande de recrutement ?" in t and "effacées sur simple demande" in t
    assert fiche.title == "Ta fiche · Your form" and len(fiche.champs) == 2
    d = fiche.to_dict()
    assert d["components"][0]["component"]["type"] == 3, "la tranche d'âge : un choix dans une liste"
    assert len(tickets) == 1 and json.loads(tickets[0][1]) == {"Tranche d'âge": "16 – 17 ans", "Pseudo Roblox": "Kolax_RS"}
    assert "Ticket créé" in " ".join(textes(v) for v in i3.vues())
    sans_echec(b)


def test_R12b_reponse_eliminatoire_aucun_ticket_message_prive_et_trace(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, fiche=FICHE)
        _i, _vue, _fiche, i3 = await _ouvrir_par_le_panneau(b, b.candidat, 0)
        async with b.get_db() as db:
            async with db.execute("SELECT COUNT(*) FROM tickets") as cur:
                n = (await cur.fetchone())[0]
        apres = Inter(b, b.candidat)
        await b.ns["_ticket_ouvrir"](apres, "p1")
        return i3, n, apres, await Q.suivi(b.g), (await Q.decidees(b.g, {}))[1], await Q.liste_noire_site(b.g)
    i3, n, apres, suivi, decidees, noire = run(sc())
    assert n == 0, "aucun ticket"
    assert "ne correspondent pas aux conditions" in " ".join(textes(v) for v in i3.vues())
    assert "n'est pas retenue" in textes(b.candidat.mp[-1][1]["view"]), "le message privé du refus"
    assert suivi["elimines"][0]["champ"] == "Tranche d'âge"
    assert decidees["lignes"][0]["motif"] == "Éliminé d'office · Tranche d'âge" and decidees["comptes"]["elimine"] == 1
    assert noire["actifs"][0]["membre"]["id"] == str(CANDIDAT), "la liste noire (réglée sur le panneau)"
    assert "Tu ne peux pas ouvrir ce type de ticket" in textes(apres.messages[0]), "le refus poli, sans ticket"
    sans_echec(b)


# ═══ R13 : la liste noire ═════════════════════════════════════════════════════════════════════════════════════

def test_R13_liste_noire_infos_lever_et_tout_lever(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, _fil = await b.ouvrir_ticket()
        await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "refuser", "note": "pseudo introuvable"})
        await laisser_finir()
        await Q.mettre_sur_liste_noire(b.g, AUTRE, motif="ancien refus", par=DIRECTION)
        avant = await Q.liste_noire_site(b.g)
        bloque = Inter(b, b.candidat)
        await b.ns["_ticket_ouvrir"](bloque, "p1")
        un = await Q._r_liste_noire_lever(b.g, b.fondateur, {}, {"membre": str(CANDIDAT)})
        apres_un = await Q.liste_noire_site(b.g)
        libre = Inter(b, b.candidat)
        await b.ns["_ticket_ouvrir"](libre, "p1")
        sans_mot = await Q._r_liste_noire_lever(b.g, b.fondateur, {}, {"tout": True, "confirmation": "oui"})
        tout = await Q._r_liste_noire_lever(b.g, b.fondateur, {}, {"tout": True, "confirmation": "LEVER"})
        return tid, avant, bloque, un, apres_un, libre, sans_mot, tout, await Q.liste_noire_site(b.g)
    tid, avant, bloque, un, apres_un, libre, sans_mot, tout, fin = run(sc())
    entree = next(x for x in avant["actifs"] if x["membre"]["id"] == str(CANDIDAT))
    assert entree["motif"] == "étape 1 — pseudo introuvable" and entree["par"]["id"] == str(FONDATEUR)
    assert entree["ticket"] == tid and entree["depuis"] > 0 and entree["candidatures"] == 1
    assert avant["total"] == 2
    assert "Tu ne peux pas ouvrir ce type de ticket" in textes(bloque.messages[0])
    assert un[0] == 200 and un[1]["leves"] == 1 and [x["membre"]["id"] for x in apres_un["actifs"]] == [str(AUTRE)]
    assert apres_un["leves"][0]["leve_par"]["id"] == str(FONDATEUR), "la levée garde la trace"
    assert "Es-tu sûr" in textes(libre.messages[0]), "levé : il peut recandidater"
    assert sans_mot[0] == 400, "« Tout lever » demande le mot tapé"
    assert tout[0] == 200 and tout[1]["leves"] == 1 and fin["actifs"] == []
    assert b.conf["ticket_panels"]["p1"].get("blacklist") in ([], None), "la liste noire des panneaux suit"
    assert any(j[0] == "recrutement.liste_noire_levee" and "toute la liste noire" in j[1] for j in b.journal)


# ═══ R14 : l'aperçu de l'équipe — on voit, on ne répond jamais ═══════════════════════════════════════════════════

def test_R14_la_tete_voit_l_apercu_ne_repond_jamais(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        await parcours_regle(b, gabarit=DEUX_ETAPES)
        tid, fil = await b.ouvrir_ticket()
        st, corps = await Q._r_etape_suivante(b.g, b.fondateur, {}, {"ticket": tid})
        eid = corps["envoi"]
        tete = Inter(b, b.fondateur, fil)
        await Q.BoutonRepondre(eid).callback(tete)
        autre = Inter(b, b.autre, fil)
        await Q.BoutonRepondre(eid).callback(autre)
        e = await Q._envoi(eid)
        force = Q.FormulairePage(e, 1)
        for _rang, champ in force.champs:
            champ._value = "je réponds à sa place"
        forcee = Inter(b, b.fondateur, fil)
        await force.on_submit(forcee)
        site = await Q._r_apercu(b.g, b.fondateur, {"ticket": str(tid)}, None)
        await repondre_etape(b, fil, eid)
        return eid, e, tete, autre, forcee, site, await Q._reponses(eid)
    eid, e, tete, autre, forcee, site, reponses = run(sc())
    t = " ".join(textes(v) for v in tete.vues())
    assert not tete.modals and "Aperçu" in t and "Lecture seule" in t, "jamais un formulaire pour l'équipe"
    for q in e["questions"]:
        assert q["reponse"] not in t, "jamais une réponse attendue"
    etape1 = [q for q in e["questions"] if q["etape"] == 1]
    etape2 = [q for q in e["questions"] if q["etape"] == 2]
    assert etape1[0]["question"] in t and etape2[0]["question"] not in t, "seulement les étapes ouvertes"
    assert not autre.modals and "Seul le candidat" in " ".join(textes(v) for v in autre.vues())
    assert "Seul le candidat" in " ".join(textes(v) for v in forcee.vues()), "un envoi forcé est refusé"
    assert "je réponds à sa place" not in reponses.values() and len(reponses) == len(etape1), \
        "rien n'est écrit par l'équipe ; le candidat, lui, répond normalement"
    assert site[0] == 200 and site[1]["pages"], "« Voir comme le candidat »"

    def cles(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from cles(v)
        elif isinstance(x, list):
            for v in x:
                yield from cles(v)
    assert not {"attendue", "variantes", "reponse_attendue"} & set(cles(site[1])), "jamais les attendues"
    for page in site[1]["pages"]:
        for q in page["questions"]:
            assert set(q) == {"rang", "question", "reponse"} and q["reponse"] is None, "sa réponse (aucune encore)"
    sans_echec(b)


# ═══ R15 : la page web du candidat (module simulé dans sys.modules) ════════════════════════════════════════════

def test_R15_le_module_de_la_page_web_trouve_par_sys_modules(tmp_path, monkeypatch):
    vus = []

    async def lien_candidat(i, ticket):
        vus.append(ticket)
        await i.response.send_message("ton lien", ephemeral=True)   # la fonction peut répondre elle-même
        return None
    faux = Obj(lien_candidat=lien_candidat, inviter=None)
    monkeypatch.setitem(sys.modules, "candidature_site", faux)
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "approuver"})
        clic = Inter(b, b.candidat, fil)
        await Q.BoutonRepondre(corps["envoi"]).callback(clic)
        return tid, clic
    tid, clic = run(sc())
    assert Q._web() is faux and vus == [tid] and clic.messages == ["ton lien"] and not clic.modals


def test_R15b_sans_page_web_les_formulaires_de_discord(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "candidature_site", raising=False)
    monkeypatch.setattr(Q, "_web_absent", time.monotonic() + 60)
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket()
        st, corps = await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "approuver"})
        clic = Inter(b, b.candidat, fil)
        await Q.BoutonRepondre(corps["envoi"]).callback(clic)
        return fil, clic
    fil, clic = run(sc())
    #  27/10/2026 : `candidature_site` existe désormais ; trouvé par son nom sans être branché au recrutement, il n'offre
    #  aucune page (`lien_candidat` absent) — ce qui compte ici : pas de page, les formulaires de Discord.
    assert Q._page_candidat() is None and isinstance(clic.modals[0], Q.FormulairePage)
    assert "**1.**" in texte_message(fil, fil.messages[-1]), "sans la page web, les questions sont dans le ticket"


# ═══ R16 : les chefs d'équipe ══════════════════════════════════════════════════════════════════════════════════

def test_R16_chef_d_equipe_proposer_corriger_nommer_retirer(tmp_path):
    invitations = []

    async def inviter(g, e):
        invitations.append((e["id"], e["nature"], e["metier"], e["etape_ouverte"]))
        return True
    b = banc(tmp_path, web=Obj(inviter=inviter, lien_candidat=None))

    async def sc():
        await b.preparer()
        await b.candidat.add_roles(b.clan_r)
        qs = []
        for question, reponse, metiers in (("Combien de voiles a un galion de guerre ?", "Trois", ["navigation"]),
                                           ("Quel vent est le plus sûr pour accoster ?", "Le vent arrière", ["tous"]),
                                           ("Quel outil répare une coque ?", "Le maillet", ["navigation"]),
                                           ("Quel poisson rapporte le plus ?", "Le thon doré", ["cuisine"])):
            st, rep = await Q._r_chef_question(b.g, b.fondateur, {}, {"question": question, "reponse": reponse,
                                                                     "metiers": metiers})
            assert st == 200, rep
            qs.append(rep["question"]["id"])
        st_role, role = await Q._r_chef_role(b.g, b.fondateur, {}, {"metier": "navigation", "creer": True})
        haut = b.g.role("Amiral", 95)
        trop_haut = await Q._r_chef_role(b.g, b.fondateur, {}, {"metier": "cuisine", "role": str(haut.id)})
        st_prop, prop = await Q._r_chef_proposition(b.g, b.fondateur, {"membre": str(CANDIDAT), "metier": "navigation"},
                                                    None)
        non_membre = await Q._r_chef_proposer(b.g, b.fondateur, {}, {"membre": AUTRE, "metier": "navigation",
                                                                     "etapes": prop["etapes"]})
        st, envoi = await Q._r_chef_proposer(b.g, b.fondateur, {}, {
            "membre": CANDIDAT, "metier": "navigation",
            "etapes": [{"titre": "La mer", "questions": [qs[0], qs[1]]}, {"titre": "Le navire", "questions": [qs[2]]}]})
        assert st == 200, envoi
        eid = envoi["envoi"]
        double = await Q._r_chef_proposer(b.g, b.fondateur, {}, {"membre": CANDIDAT, "metier": "navigation",
                                                                 "etapes": prop["etapes"]})
        e = await Q._envoi(eid)
        #  Le chef répond sur la page web (simulée ici par la base, comme `envoyer_etape`).
        for k in (1, 2):
            async with b.get_db() as db:
                for q in [q for q in e["questions"] if int(q["etape"]) == k]:
                    await db.execute("INSERT OR REPLACE INTO recrutement_reponses (envoi_id, rang, guild_id, candidat_id,"
                                     " texte, recu_le) VALUES (?,?,?,?,?,1)", (eid, q["rang"], b.g.id, CANDIDAT,
                                                                               q["reponse"]))
                await db.execute("UPDATE recrutement_envois SET etape_envoyee=? WHERE id=?", (k, eid))
                await db.commit()
            if k == 1:
                await Q.etape_recue(b.g, await Q._envoi(eid), 1)
                assert (await Q.etape_suivante(b.g, eid, b.fondateur))[0]
            else:
                e2 = await Q._envoi(eid)
                assert await Q.clore_envoi(e2, 5)
                await Q.annoncer_reponses(b.g, e2, 5)
        trop_tot = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": eid, "decision": "accepter"})
        e = await Q._envoi(eid)
        for k, q in enumerate(e["questions"]):
            await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": q["id"], "juste": k != 0})
        a_99 = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": eid, "decision": "accepter"})
        force = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": eid, "decision": "accepter", "forcer": True})
        dossier = await Q._r_chef_dossier(b.g, b.fondateur, {"envoi": str(eid)}, None)
        await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": e["questions"][0]["id"], "juste": True})
        ok = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": eid, "decision": "accepter"})
        nommes = await Q.chefs(b.g.id)
        fiche = await Q._r_chef(b.g, b.fondateur, {"membre": str(CANDIDAT)}, None)
        fige = await Q._r_corriger(b.g, b.fondateur, {}, {"envoi": eid, "question": e["questions"][0]["id"],
                                                          "juste": False})
        role_chef = b.g.get_role(int(role["role"]["id"]))
        avec_role = role_chef in b.candidat.roles
        retire = await Q._r_chef_retirer(b.g, b.fondateur, {}, {"membre": CANDIDAT})
        return (st_role, role, trop_haut, st_prop, prop, non_membre, envoi, double, trop_tot, a_99, force, dossier, ok,
                nommes, fiche, fige, avec_role, retire, role_chef, await Q.chefs(b.g.id), e)
    (st_role, role, trop_haut, st_prop, prop, non_membre, envoi, double, trop_tot, a_99, force, dossier, ok, nommes, fiche,
     fige, avec_role, retire, role_chef, apres, e) = run(sc())
    assert st_role == 200 and role["role"]["nom"] == "Chef · Navigateur", "« Créer le rôle »"
    assert trop_haut[0] == 409 and "au-dessus du mien" in trop_haut[1]["erreur"], "la hiérarchie du bot"
    assert st_prop == 200 and prop["metiers_membre"] == ["navigation"], "son métier, prérempli"
    assert len(prop["etapes"][0]["questions"]) == 3, "les questions du métier et celles de « tous »"
    assert non_membre[0] == 409 and "membre du clan" in non_membre[1]["erreur"]
    assert envoi["invite"] is True and invitations[0] == (envoi["envoi"], "chef", "navigation", 1)
    assert (e["ticket_id"], e["nature"], e["metier"]) == (0, "chef", "navigation"), "aucun ticket"
    assert len(invitations) == 2, "l'étape suivante d'un chef : son invitation (la page web)"
    assert double[0] == 409, "une candidature de chef à la fois"
    assert trop_tot[0] == 409 and trop_tot[1]["raison"] == "correction"
    assert a_99[0] == 409 and a_99[1]["raison"] == "exigence" and "100 %" in a_99[1]["erreur"]
    assert force[0] == 400 and "jamais en forçant" in force[1]["erreur"], "100 % FIXE : jamais forcé"
    assert dossier[1]["peut"]["accepter"] is False and "100 %" in dossier[1]["raison_accepter"]
    assert ok[0] == 200 and ok[1]["role"]["nom"] == "Chef · Navigateur" and avec_role
    assert nommes[CANDIDAT]["metier"] == "navigation" and nommes[CANDIDAT]["role_id"] == role_chef.id
    assert fiche[1]["chef"]["titre"] == "Chef d'équipe · Navigateur", "la pastille de sa fiche"
    assert fige[0] == 409, "décidée : la correction est figée"
    assert "Tu es nommé chef d'équipe · Navigateur" in textes(b.candidat.mp[-1][1]["view"])
    assert retire[0] == 200 and retire[1]["role_retire"] and role_chef not in b.candidat.roles and apres == {}
    assert b.clan_r in b.candidat.roles, "jamais un autre rôle touché"


def test_R16b_chef_refuse_sans_liste_noire_attente_et_sans_page_web(tmp_path):
    async def inviter(g, e):
        return True
    b = banc(tmp_path, web=Obj(inviter=inviter, lien_candidat=None))

    async def sc():
        await b.preparer()
        await b.autre.add_roles(b.clan_r)
        st, rep = await Q._r_chef_question(b.g, b.fondateur, {}, {"question": "Quel cap pour rentrer au port ?",
                                                                 "reponse": "Le nord", "metiers": ["tous"]})
        corps = {"membre": AUTRE, "metier": "cuisine", "etapes": [{"questions": [rep["question"]["id"]]}]}
        st, envoi = await Q._r_chef_proposer(b.g, b.fondateur, {}, corps)
        attente = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": envoi["envoi"], "decision": "attente"})
        refus = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": envoi["envoi"], "decision": "refuser"})
        encore = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": envoi["envoi"], "decision": "accepter"})
        Q._web_module = None
        sans_page = None
        try:
            import sys as _sys
            _sys.modules.pop("candidature_site", None)
            Q._web_absent = time.monotonic() + 60
            sans_page = await Q._r_chef_proposer(b.g, b.fondateur, {}, corps)
        finally:
            Q._web_module = Obj(inviter=inviter, lien_candidat=None)
        return attente, refus, encore, sans_page, await Q.sur_liste_noire(b.g.id, AUTRE)
    attente, refus, encore, sans_page, noire = run(sc())
    assert attente[0] == 200 and attente[1]["decision"] == "attente"
    assert refus[0] == 200 and refus[1]["decision"] == "refuse" and not noire, "un chef refusé reste du clan"
    assert [("en attente" in textes(kw["view"])) for _c, kw in b.autre.mp][:1] == [True]
    assert "n'est pas retenue pour le moment" in textes(b.autre.mp[-1][1]["view"])
    assert encore[0] == 409, "décidée : rien ne bouge"
    assert sans_page[0] == 409 and "page de réponse" in sans_page[1]["erreur"], "sans la page web, pas d'impasse"


# ═══ R17 : la purge exceptionnelle ════════════════════════════════════════════════════════════════════════════

A, B_, C, D, E_, F = 201, 202, 203, 204, 205, 206    # refusé seul · refusé puis accepté · refusé + ouvert · accepté ·
JETON_A, JETON_S = "A" * 22, "S" * 22                # éliminé seul · refusé mais du clan aujourd'hui


async def _base_purge(b, monkeypatch, tmp_path):
    monkeypatch.setattr(recrutements, "_get_db", b.get_db)
    async with b.get_db() as db:
        await db.execute("DROP TABLE IF EXISTS recrutements")
        await db.commit()
    await recrutements.init_db()
    await b.preparer()
    dossier = tmp_path / "transcripts"
    (dossier / f"a_{JETON_A}").mkdir(parents=True)
    (dossier / f"{JETON_A}.html").write_text("<p>ticket refusé</p>", encoding="utf-8")
    (dossier / f"a_{JETON_A}" / "0.png").write_bytes(b"x" * 10)
    (dossier / f"{JETON_S}.html").write_text("<p>support</p>", encoding="utf-8")
    monkeypatch.setattr(transcript_store, "_BASE_DIR", str(dossier))
    for uid in (A, B_, C, D, E_, F):
        b.g.membre(uid, f"Membre{uid}", *((b.clan_r,) if uid in (B_, D, F) else ()))
    g = b.g.id
    tickets = [(11, A, "p1", "closed"), (17, A, "p2", "closed"), (12, B_, "p1", "closed"), (13, B_, "p1", "closed"),
               (14, C, "p1", "closed"), (15, C, "p1", "open"), (16, D, "p1", "closed"), (18, F, "p1", "closed")]
    async with b.get_db() as db:
        for tid, uid, pid, st in tickets:
            await db.execute("INSERT INTO tickets (id, guild_id, channel_id, user_id, panel_id, status, answers)"
                             " VALUES (?,?,?,?,?,?,'{}')", (tid, g, 1000 + tid, uid, pid, st))
        for tid, uid, dec, url in ((11, A, "refuses", f"https://bot.exemple/t/{JETON_A}"), (12, B_, "refuses", ""),
                                   (13, B_, "acceptes", ""), (14, C, "refuses", ""), (16, D, "acceptes", ""),
                                   (18, F, "refuses", "")):
            await db.execute("INSERT INTO recrutements (guild_id, ticket_id, candidat_id, ferme_le, decision, transcript)"
                             " VALUES (?,?,?,?,?,?)", (g, tid, uid, 1000, dec, url))
        for sql in ("CREATE TABLE ticket_transcripts (guild_id INTEGER, ticket_id INTEGER, user_id INTEGER, url TEXT)",
                    "CREATE TABLE ticket_log_events (guild_id INTEGER, ticket_id INTEGER, actor_id INTEGER, kind TEXT)",
                    "CREATE TABLE ticket_audit (guild_id INTEGER, channel_id INTEGER, actor_id INTEGER, action TEXT)",
                    "CREATE TABLE registre (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, quand INTEGER,"
                    " categorie TEXT, type TEXT, membre_id INTEGER, auteur_id INTEGER, salon_id INTEGER, texte TEXT,"
                    " detail TEXT, gravite INTEGER)"):
            await db.execute(sql)
        await db.execute("INSERT INTO ticket_transcripts VALUES (?,?,?,?)", (g, 11, A, f"https://bot.exemple/t/{JETON_A}"))
        await db.execute("INSERT INTO ticket_transcripts VALUES (?,?,?,?)", (g, 17, A, f"https://bot.exemple/t/{JETON_S}"))
        for tid in (11, 17, 12):
            await db.execute("INSERT INTO ticket_log_events VALUES (?,?,?,?)", (g, tid, 1, "close"))
        for chid in (1011, 1017):
            await db.execute("INSERT INTO ticket_audit VALUES (?,?,?,?)", (g, chid, 1, "close"))
        for cat, typ, membre, salon, texte in (("Tickets", "ticket", A, 1011, "Ticket #11 (Recrutement) — fermé"),
                                               ("Clan", "recrutement.etape1_refusee", A, 0, "Recrutement : refusée"),
                                               ("Modération", "mute", A, 1011, "Mute de A"),
                                               ("Tickets", "ticket", A, 1017, "Ticket #17 (Support) — fermé"),
                                               ("Clan", "recrutement.questionnaire", B_, 0, "Recrutement : envoyé")):
            await db.execute("INSERT INTO registre (guild_id, quand, categorie, type, membre_id, salon_id, texte)"
                             " VALUES (?,?,?,?,?,?,?)", (g, 1, cat, typ, membre, salon, texte))
        await db.execute("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?,?,?,?,?)",
                         (g, A, 1, "warn", "insulte"))
        await db.execute("INSERT INTO recrutement_suivi (guild_id, ticket_id, candidat_id, etape, maj_le) VALUES"
                         " (?,?,?,?,?)", (g, 11, A, "refus_etape1", 1))
        cur = await db.execute("INSERT INTO recrutement_envois (guild_id, ticket_id, candidat_id, questions, statut)"
                               " VALUES (?,?,?,?,?)", (g, 11, A, "[]", "clos"))
        eid = cur.lastrowid
        await db.execute("INSERT INTO recrutement_reponses (envoi_id, rang, guild_id, candidat_id, texte, recu_le)"
                         " VALUES (?,?,?,?,?,1)", (eid, 1, g, A, "réponse"))
        await db.execute("INSERT INTO recrutement_corrections (envoi_id, rang, juste) VALUES (?,?,1)", (eid, 1))
        await db.execute("INSERT INTO recrutement_historique (guild_id, ticket_id, quand, quoi) VALUES (?,?,1,'refus')",
                         (g, 11))
        await db.execute("INSERT INTO recrutement_historique (guild_id, ticket_id, quand, quoi) VALUES (?,?,1,'refus')",
                         (g, 12))
        for uid in (A, C):
            await db.execute("INSERT INTO recrutement_liste_noire (guild_id, membre_id, depuis) VALUES (?,?,1)", (g, uid))
        await db.execute("INSERT INTO recrutement_eliminations (guild_id, membre_id, champ, quand) VALUES (?,?,?,1)",
                         (g, E_, "Tranche d'âge"))
        await db.commit()
    return dossier


async def _compte(b, sql, args=()):
    async with b.get_db() as db:
        async with db.execute(sql, args) as cur:
            return (await cur.fetchone())[0]


def test_R17_purge_exceptionnelle_exhaustive_et_idempotente(tmp_path, monkeypatch):
    b = banc(tmp_path)

    async def sc():
        dossier = await _base_purge(b, monkeypatch, tmp_path)
        apercu = await Q._r_purge(b.g, b.fondateur, {}, None)
        sans_mot = await Q._r_purge_lancer(b.g, b.fondateur, {}, {"confirmation": "purger maintenant"})
        intact = await _compte(b, "SELECT COUNT(*) FROM tickets")
        st, rep = await Q._r_purge_lancer(b.g, b.fondateur, {}, {"confirmation": "PURGER"})
        deuxieme = await Q._r_purge_lancer(b.g, b.fondateur, {}, {"confirmation": "PURGER"})
        c = {}
        for nom, sql in (("tickets", "SELECT group_concat(id) FROM (SELECT id FROM tickets ORDER BY id)"),
                         ("recrutements", "SELECT group_concat(ticket_id) FROM (SELECT ticket_id FROM recrutements"
                                          " ORDER BY ticket_id)"),
                         ("transcripts", "SELECT group_concat(ticket_id) FROM ticket_transcripts"),
                         ("log", "SELECT group_concat(ticket_id) FROM (SELECT ticket_id FROM ticket_log_events"
                                 " ORDER BY ticket_id)"),
                         ("audit", "SELECT group_concat(channel_id) FROM ticket_audit"),
                         ("registre", "SELECT group_concat(texte, ' | ') FROM (SELECT texte FROM registre ORDER BY id)"),
                         ("infractions", "SELECT COUNT(*) FROM infractions"),
                         ("suivi", "SELECT COUNT(*) FROM recrutement_suivi"),
                         ("envois", "SELECT COUNT(*) FROM recrutement_envois"),
                         ("reponses", "SELECT COUNT(*) FROM recrutement_reponses"),
                         ("corrections", "SELECT COUNT(*) FROM recrutement_corrections"),
                         ("historique", "SELECT group_concat(ticket_id) FROM recrutement_historique"),
                         ("noire", "SELECT group_concat(membre_id) FROM recrutement_liste_noire"),
                         ("elimines", "SELECT COUNT(*) FROM recrutement_eliminations")):
            c[nom] = await _compte(b, sql)
        return dossier, apercu, sans_mot, intact, st, rep, deuxieme, c
    dossier, apercu, sans_mot, intact, st, rep, deuxieme, c = run(sc())
    personnes = {p["membre"]["id"]: p for p in apercu[1]["personnes"]}
    assert set(personnes) == {str(A), str(E_)}, "refusé seul, éliminé seul — jamais B (accepté ensuite), C (ouvert)," \
                                                 " D (accepté), F (du clan)"
    assert personnes[str(A)]["octets"] > 0 and apercu[1]["confirmation"] == "PURGER"
    assert sans_mot[0] == 400 and intact == 8, "sans le mot tapé : rien n'est effacé"
    assert st == 200 and rep["personnes"] == 2 and rep["candidatures"] == 2 and rep["transcripts"] == 1
    assert c["tickets"] == "12,13,14,15,16,17,18", "son ticket Support (17) reste ; les autres membres aussi"
    assert c["recrutements"] == "12,13,14,16,18" and c["transcripts"] == "17" and c["log"] == "12,17"
    assert c["audit"] == "1017"
    assert c["registre"] == "Mute de A | Ticket #17 (Support) — fermé | Recrutement : envoyé", \
        "le journal de sa candidature part ; ses sanctions et ses autres tickets restent"
    assert c["infractions"] == 1, "le casier n'est jamais touché"
    assert (c["suivi"], c["envois"], c["reponses"], c["corrections"]) == (0, 0, 0, 0)
    assert c["historique"] == "12" and c["noire"] == str(C) and c["elimines"] == 0
    assert not (dossier / f"{JETON_A}.html").exists() and not (dossier / f"a_{JETON_A}").exists()
    assert (dossier / f"{JETON_S}.html").exists(), "le transcript de son ticket Support reste"
    assert deuxieme[0] == 200 and deuxieme[1]["candidatures"] == 0, "idempotente"
    ligne = next(j for j in b.journal if j[0] == "recrutement.purge")
    assert ligne[1] == "Purge exceptionnelle : 2 candidature(s) refusée(s) effacée(s)" and "<@" not in ligne[1]


def test_R17b_la_purge_n_est_jamais_lancee_au_demarrage():
    import ast
    import inspect
    src = inspect.getsource(Q.demarrer) + inspect.getsource(Q.purger) + inspect.getsource(Q.init_db)
    assert "purge_executer" not in src, "irréversible : jamais automatique"
    racine = Path(__file__).resolve().parent.parent
    for f in ("bot.py", "health_server.py", "tableau.py"):
        arbre = ast.parse((racine / f).read_text(encoding="utf-8"))
        assert not [n for n in ast.walk(arbre) if isinstance(n, ast.Attribute) and n.attr == "purge_executer"], f


# ═══ R18 : le nettoyage ═══════════════════════════════════════════════════════════════════════════════════════

def test_R18_nettoyage_regles_et_maintenant(tmp_path):
    import tableau
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        vieux = int(time.time()) - 400 * 86400
        async with b.get_db() as db:
            await db.execute("INSERT INTO recrutement_liste_noire (guild_id, membre_id, depuis, leve_le) VALUES (?,?,?,?)",
                             (b.g.id, 1, vieux, vieux))
            await db.execute("INSERT INTO recrutement_liste_noire (guild_id, membre_id, depuis) VALUES (?,?,?)",
                             (b.g.id, 2, vieux))
            await db.execute("INSERT INTO recrutement_eliminations (guild_id, membre_id, quand) VALUES (?,?,?)",
                             (b.g.id, 3, vieux))
            await db.commit()
        avant = await Q._r_nettoyage(b.g, b.fondateur, {}, None)
        st, rep = await Q._r_nettoyage_lancer(b.g, b.fondateur, {}, {})
        return avant, st, rep, await Q.liste_noire_site(b.g)
    avant, st, rep, noire = run(sc())
    regles = {r["cle"]: r for r in avant[1]["regles"]}
    assert set(regles) == {"questionnaires", "recrutement_traces"} and regles["recrutement_traces"]["a_retirer"] == 2
    assert st == 200 and rep["bilan"]["recrutement_traces"] == 2
    assert [x["membre"]["id"] for x in noire["actifs"]] == ["2"], "une entrée active ne part jamais"
    for r in Q.REGLES_RECRUTEMENT:
        tableau._normaliser_regle(r)


# ═══ R19 : le parcours réglé sur le site ═══════════════════════════════════════════════════════════════════════

def test_R19_parcours_validation_version_avertissements_et_messages(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tout = await Q._r_parcours(b.g, b.fondateur, {}, None)
        p1 = next(x for x in tout[1]["panneaux"] if x["panneau"] == "p1")
        mauvais = []
        for corps in ({"mode": "rapide"}, {"fiche": [{"titre": f"Champ {k}"} for k in range(6)]},
                      {"fiche": [{"titre": "Âge", "type": "choix", "options": ["A", "B"], "eliminatoires": ["A", "B"]}]},
                      {"gabarit": [{"source": "modele", "modele": "inconnu"}]}, {"delai": 1}, {"panneau": "p2"}):
            mauvais.append(await Q._r_parcours_ecrire(b.g, b.fondateur, {}, dict(
                {"panneau": "p1", "version": 0, "mode": "approbation", "exigence": 100, "delai": 20}, **corps)))
        ok = await Q._r_parcours_ecrire(b.g, b.fondateur, {}, {
            "panneau": "p1", "version": 0, "mode": "approbation", "exigence": 90, "delai": 30, "liste_noire": False,
            "metier": False, "gabarit": DEUX_ETAPES,
            "fiche": [{"titre": "Ton adresse e-mail", "type": "court"}, {"titre": "Ta date de naissance", "type": "court"},
                      {"titre": "Pseudo Roblox", "type": "court"}]})
        conflit = await Q._r_parcours_ecrire(b.g, b.fondateur, {}, {"panneau": "p1", "version": 0, "mode": "direct",
                                                                   "exigence": 100, "delai": 20})
        return p1, mauvais, ok, conflit
    p1, mauvais, ok, conflit = run(sc())
    assert p1["mode"] == "approbation" and p1["version"] == 0 and p1["exigence"] == 100
    cles = [m["cle"] for m in p1["messages"]]
    assert cles[:3] == ["confirmation", "fiche", "affiche"] and "etape" in cles and "direction" in cles, cles
    assert all(m["cles"] for m in p1["messages"]), "chaque message nomme ses textes (« Modifier ce message »)"
    assert [m[0] for m in mauvais] == [400, 400, 400, 400, 400, 404], [m[1] for m in mauvais]
    st, rep = ok
    assert st == 200 and rep["parcours"]["version"] == 1 and rep["parcours"]["exigence"] == 90
    av = " ".join(x["raison"] for x in rep["avertissements"])
    assert "coordonnées" in av and [x["titre"] for x in rep["avertissements"]][:2] == ["Ton adresse e-mail",
                                                                                         "Ta date de naissance"]
    assert "tranche d'âge" in av.casefold(), "une date de naissance : demander une tranche d'âge"
    assert rep["_journal"]["texte"].startswith("Recrutement : parcours du panneau")
    assert conflit[0] == 409 and conflit[1]["actuelle"]["version"] == 1, "changé entre-temps : conflit"


# ═══ R20 : les décidées (paginées) ════════════════════════════════════════════════════════════════════════════

def test_R20_decidees_paginees_avec_transcript_et_auteur(tmp_path, monkeypatch):
    b = banc(tmp_path)

    async def sc():
        monkeypatch.setattr(recrutements, "_get_db", b.get_db)
        async with b.get_db() as db:
            await db.execute("DROP TABLE IF EXISTS recrutements")
            await db.commit()
        await recrutements.init_db()
        await b.preparer()
        async with b.get_db() as db:
            for k in range(30):
                await db.execute("INSERT INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom, ferme_le,"
                                 " ferme_par, decision, raison, transcript) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (b.g.id, 100 + k, 5000 + k, f"Matelot {k}", 1000 + k, FONDATEUR,
                                  "acceptes" if k % 3 == 0 else "refuses", "Refusé : étape 2", f"https://x/t/{k:022d}"))
            await db.commit()
        return (await Q._r_decidees(b.g, b.fondateur, {}, None))[1], \
            (await Q._r_decidees(b.g, b.fondateur, {"page": "2"}, None))[1]
    p1, p2 = run(sc())
    assert p1["total"] == 30 and p1["pages"] == 2 and len(p1["lignes"]) == 25 and len(p2["lignes"]) == 5
    assert p1["lignes"][0]["quand"] >= p1["lignes"][-1]["quand"], "du plus récent"
    x = p1["lignes"][0]
    assert x["transcript"].startswith("https://x/t/") and x["par"]["id"] == str(FONDATEUR)
    assert x["membre"]["nom"] == "Matelot 29", "un membre parti garde son nom"
    assert p1["comptes"] == {"acceptes": 10, "refuses": 20, "elimine": 0}


# ═══ R21 : un ticket d'avant l'affiche garde sa fermeture annoncée ════════════════════════════════════════════

def test_R21_un_ticket_sans_affiche_annonce_toujours_sa_fermeture(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        tid, fil = await b.ouvrir_ticket(pid="p2", reponses={})
        ok = await b.ns["_fermer_ticket"](b.g, fil, {"id": tid, "user": CANDIDAT}, b.fondateur, "Résolu")
        await laisser_finir()
        return fil, ok
    fil, ok = run(sc())
    assert "Ticket fermé" in tout_le_fil(fil), "un ticket Support : l'annonce de fermeture, comme avant"


def test_R22_les_tables_du_recrutement_sont_dans_la_carte_rgpd(tmp_path):
    import gdpr
    connues = set(gdpr.DELETE_SUBJECT) | set(gdpr.DELETE_SUBJECT_KEEP_ACTOR) | set(gdpr.ANONYMIZE)
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        async with b.get_db() as db:
            async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'recrutement_%'") as cur:
                tables = {r[0] for r in await cur.fetchall()}
            manque = await gdpr.validate_map(db)
        return tables, manque
    tables, manque = run(sc())
    personnelles = {t for t in tables if t not in ("recrutement_questions", "recrutement_liens", "recrutement_reglages",
                                                   "recrutement_modeles", "recrutement_corrections")}
    assert personnelles <= connues, personnelles - connues
    assert not [c for c in manque["missing_columns"] if c[0].startswith("recrutement_")], manque


def test_R23_rien_de_dynamique_dans_les_avertissements_du_module():
    """Les avertissements du journal : un code stable et un texte fixe (le détail part dans une ligne `:DETAIL`)."""
    import re
    src = (Path(__file__).resolve().parent.parent / "questionnaire.py").read_text(encoding="utf-8")
    for m in re.finditer(r'_log\((f?)"\[RECRUTEMENT\]\[E(\d+)\]([^"]*)"\)', src):
        assert m.group(1) == "", f"E{m.group(2)} : le message principal ne porte aucune valeur ({m.group(3)})"
    _ = os


# ═══ R24 : les chefs validés sur les équipes du clan (site_equipage, 27/10/2026) ═══════════════════════════════════

def test_R24_le_chef_valide_est_badge_et_propose_en_premier_dans_l_editeur_d_equipe(tmp_path, monkeypatch):
    """Le chef validé par le recrutement porte « Chef validé · <métier> » dans l'éditeur d'une équipe et y passe en
    premier : le fournisseur branché au démarrage (bot.py), le badge renommable, retiré avec le titre ; le tri de
    l'éditeur exécuté tel quel (equipes_admin.js)."""
    import ast
    import re
    import shutil
    import subprocess
    import site_equipage
    import textes as T
    racine = Path(__file__).resolve().parent.parent

    async def inviter(g, e):
        return True
    b = banc(tmp_path, web=Obj(inviter=inviter, lien_candidat=None))
    monkeypatch.setattr(Q, "_bot", Obj(get_guild=lambda gid: b.g if gid == b.g.id else None))
    for nom, valeur in (("_get_db", b.get_db), ("_cache", {}), ("_etat", {"charge": False, "echec": 0.0}),
                        ("_verrous", {}), ("_log", lambda *a: None)):
        monkeypatch.setattr(T, nom, valeur)   # les textes du serveur dans la base du banc (rendus après le test)

    async def sc():
        await b.preparer()
        await T.init_db()
        await b.candidat.add_roles(b.clan_r)
        st, rep = await Q._r_chef_question(b.g, b.fondateur, {}, {"question": "Combien de voiles a un galion de guerre ?",
                                                                 "reponse": "Trois", "metiers": ["navigation"]})
        assert st == 200, rep
        st, envoi = await Q._r_chef_proposer(b.g, b.fondateur, {}, {"membre": CANDIDAT, "metier": "navigation",
                                                                    "etapes": [{"titre": "",
                                                                                "questions": [rep["question"]["id"]]}]})
        assert st == 200, envoi
        e = await Q._envoi(envoi["envoi"])
        assert await Q._garder_page(e, {int(q["rang"]): q["reponse"] for q in e["questions"]})   # la page web
        assert await Q.clore_envoi(e, 5)
        await Q.annoncer_reponses(b.g, e, 5)
        en_cours = await site_equipage.badges_chef(b.g.id)
        await tout_corriger(b, e["id"])
        st, ok = await Q._r_chef_decision(b.g, b.fondateur, {}, {"envoi": e["id"], "decision": "accepter"})
        assert st == 200, ok
        nomme = await site_equipage.badges_chef(b.g.id)
        st, rep = await T.ecrire(b.g, b.fondateur, {"cle": "recrutement.chef.badge",
                                                    "valeur": "Second de confiance · {metier}", "version": 0})
        assert st == 200, rep
        renomme = await site_equipage.badges_chef(b.g.id)
        st, rep = await Q._r_chef_retirer(b.g, b.fondateur, {}, {"membre": CANDIDAT})
        assert st == 200, rep
        return en_cours, nomme, renomme, await site_equipage.badges_chef(b.g.id)

    site_equipage.brancher_badges_chef(Q.badges_chefs)   # comme au démarrage du bot (vérifié plus bas)
    try:
        en_cours, nomme, renomme, retire = run(sc())
    finally:
        site_equipage.brancher_badges_chef(None)
    assert en_cours == {}, "une candidature en cours n'est pas un chef validé"
    assert nomme == {str(CANDIDAT): "Chef validé · Navigateur"}, nomme
    assert renomme == {str(CANDIDAT): "Second de confiance · Navigateur"}, "le badge se renomme (Textes & noms)"
    assert retire == {}, "le titre retiré : plus de badge"
    sans_echec(b)

    #  Branché au démarrage : dans l'étape « questionnaire » du bot (et le site local fait de même).
    def branche(arbre) -> bool:
        return any(isinstance(n, ast.Call) and ast.unparse(n.func) == "site_equipage.brancher_badges_chef"
                   and [ast.unparse(a) for a in n.args] == ["questionnaire.badges_chefs"] for n in ast.walk(arbre))
    etapes = [n for n in ast.walk(ast.parse((racine / "bot.py").read_text(encoding="utf-8"))) if isinstance(n, ast.With)
              and any(ast.unparse(x.context_expr) == "_Etape('questionnaire')" for x in n.items)]
    assert len(etapes) == 1 and branche(etapes[0]), "le fournisseur des badges est branché au démarrage du bot"
    assert branche(ast.parse((racine / "outils" / "site_local.py").read_text(encoding="utf-8")))

    #  Proposé en premier : le tri du sélecteur de l'éditeur d'une équipe, exécuté tel quel.
    js = (racine / "site" / "equipes_admin.js").read_text(encoding="utf-8")
    tri = re.search(r"const trier = (\(l\) => l\.sort\(.+?\));\n", js)
    assert tri and "badges[id] ? pastille(badges[id]" in js, "le tri et le badge de l'éditeur"
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent : le tri de l'éditeur n'est pas exécuté")
    script = ("const badges = " + json.dumps({str(CANDIDAT): nomme[str(CANDIDAT)]}) + ";\n"
              "const nomDe = (m) => m.nom;\nconst trier = " + tri.group(1) + ";\n"
              "const clan = [{ id: '1', nom: 'Anne Bonny' }, { id: '" + str(CANDIDAT) + "', nom: 'Zoé la Vigie' },"
              " { id: '2', nom: 'Barbe Noire' }];\nconsole.log(JSON.stringify(trier(clan).map((m) => m.id)));\n")
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [str(CANDIDAT), "1", "2"], "le chef validé d'abord, puis les autres par leur nom"


# ═══ R25-R27 : le recrutement léger dans le chargement du site (27/10/2026, banc de 5 ans) ═══════════════════════════

def test_R25_le_suivi_une_connexion_et_des_lectures_groupees(tmp_path, monkeypatch):
    """`recrutement/suivi` passait de 66 à 330 ms (banc de 5 ans : une connexion et une lecture par ticket ouvert, par
    réponse, par correction, par transcript récent). Il ouvre UNE connexion et fait le même nombre de lectures pour 3
    ou 30 tickets ouverts ; les transcripts récents viennent de l'index (le plus récent), sinon du suivi des
    candidatures ; `recents=False` (les données de la page) ne lit que les ouvertes."""
    b = banc(tmp_path)
    connexions, lectures = [], []
    get_db0, lire0 = Q._get_db, Q._lire_dans

    def get_db():
        connexions.append(1)
        return get_db0()

    async def lire_dans(db, sql, args=(), tolerant=False):
        lectures.append(sql)
        return await lire0(db, sql, args, tolerant)

    async def ouvrir(n, debut):
        t = int(time.time())
        async with b.get_db() as db:
            for k in range(debut, debut + n):
                await db.execute("INSERT INTO tickets (id, guild_id, channel_id, user_id, panel_id, claimed_by, status, answers)"
                                 " VALUES (?,?,?,?,?,?,?,?)", (k, b.g.id, 9000 + k, 7000 + k, "p1", 0, "open", "{}"))
                cur = await db.execute("INSERT INTO recrutement_envois (guild_id, ticket_id, candidat_id, questions, statut)"
                                       " VALUES (?,?,?,?,?)", (b.g.id, k, 7000 + k, json.dumps(
                                           [{"id": "q1", "rang": 1, "question": "Quel cap ?", "reponse": "Nord"}]), "repondu"))
                await db.execute("INSERT INTO recrutement_reponses (envoi_id, rang, guild_id, candidat_id, texte, recu_le)"
                                 " VALUES (?,?,?,?,?,?)", (cur.lastrowid, 1, b.g.id, 7000 + k, "Nord", t))
                await db.execute("INSERT INTO recrutement_suivi (guild_id, ticket_id, candidat_id, etape, envoi_id, cree_le,"
                                 " maj_le) VALUES (?,?,?,?,?,?,?)", (b.g.id, k, 7000 + k, "reponses", cur.lastrowid, t, t))
            await db.commit()

    async def mesurer(**kw):
        connexions.clear()
        lectures.clear()
        s = await Q.suivi(b.g, **kw)
        return s, (len(connexions), len(lectures))

    async def sc():
        await b.preparer()
        t = int(time.time())
        async with b.get_db() as db:   # trois décisions récentes : deux transcripts à trouver, une étape sans
            await db.execute("CREATE TABLE IF NOT EXISTS ticket_transcripts (guild_id INTEGER, ticket_id INTEGER, url TEXT)")
            for k, etape in ((500, "accepte"), (501, "refuse"), (502, "etape2")):
                await db.execute("INSERT INTO recrutement_suivi (guild_id, ticket_id, candidat_id, etape, maj_le)"
                                 " VALUES (?,?,?,?,?)", (b.g.id, k, 7500 + k, etape, t - 60 - k))
            for url in ("https://t/ancien", "https://t/500"):
                await db.execute("INSERT INTO ticket_transcripts (guild_id, ticket_id, url) VALUES (?,?,?)", (b.g.id, 500, url))
            await db.execute("INSERT INTO recrutements (guild_id, ticket_id, candidat_id, ferme_le, transcript)"
                             " VALUES (?,?,?,?,?)", (b.g.id, 501, 8001, t, "https://t/501"))
            await db.commit()
        await ouvrir(3, 100)
        monkeypatch.setattr(Q, "_get_db", get_db)
        monkeypatch.setattr(Q, "_lire_dans", lire_dans)
        s3, n3 = await mesurer()
        await ouvrir(27, 200)
        s30, n30 = await mesurer()
        o, no = await mesurer(recents=False)
        return s3, n3, s30, n30, o, no
    s3, n3, s30, n30, o, no = run(sc())
    assert n3[0] == n30[0] == no[0] == 1, "une seule connexion"
    assert n3[1] == n30[1], f"autant de lectures pour 3 ou 30 tickets ouverts : {n3} · {n30}"
    assert len(s30["ouverts"]) == 30 and all(x["envoi"]["bilan"]["repondues"] == 1 and x["action"] == "corriger"
                                             for x in s30["ouverts"])
    assert [(x["ticket"], x["transcript"]) for x in s30["recents"]] == [(500, "https://t/500"), (501, "https://t/501"),
                                                                       (502, "")], s30["recents"]
    assert o["ouverts"] == s30["ouverts"] and o["recents"] == [] and o["elimines"] == [] and no[1] < n30[1]


def test_R26_les_decidees_par_morceaux_comme_le_journal(tmp_path):
    """L'historique des décisions se lit par morceaux (`avant` = la `suite` du morceau précédent) : tout est rendu une
    fois, du plus récent, égalités comprises ; seul le morceau demandé est lu ; l'ancienne pagination reste lue."""
    b = banc(tmp_path)

    async def sc():
        await b.preparer()
        async with b.get_db() as db:
            for k in range(60):   # deux décisions par seconde : le curseur départage
                await db.execute("INSERT INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom, ferme_le, ferme_par,"
                                 " decision, raison, transcript) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (b.g.id, 100 + k, 5000 + k, f"Matelot {k}", 1000 + k // 2, FONDATEUR,
                                  "acceptes" if k % 3 == 0 else "refuses", "", ""))
            for k in range(5):    # éliminés d'office à la même seconde que deux décisions
                await db.execute("INSERT INTO recrutement_eliminations (guild_id, membre_id, nom, champ, reponse, quand)"
                                 " VALUES (?,?,?,?,?,?)", (b.g.id, 6000 + k, f"Mousse {k}", "Tranche d'âge", "Moins de 13 ans",
                                                           1010))
            await db.commit()
        morceaux, suite = [], None
        while True:
            st, r = await Q._r_decidees(b.g, b.fondateur, {"avant": suite} if suite else {}, None)
            assert st == 200, r
            morceaux.append(r)
            suite = r["suite"]
            if not suite or len(morceaux) > 10:
                break
        page2 = (await Q._r_decidees(b.g, b.fondateur, {"page": "2"}, None))[1]
        invalide = await Q._r_decidees(b.g, b.fondateur, {"avant": "1000:abc"}, None)
        grand = (await Q._r_decidees(b.g, b.fondateur, {"n": "500"}, None))[1]
        return morceaux, page2, invalide, grand
    morceaux, page2, invalide, grand = run(sc())
    tout = [x for m in morceaux for x in m["lignes"]]
    assert [len(m["lignes"]) for m in morceaux] == [25, 25, 15] and morceaux[-1]["suite"] is None
    cles = [(x["quand"], x["ticket"], int(x["membre"]["id"])) for x in tout]
    assert len(set(cles)) == 65 and cles == sorted(cles, reverse=True), "tout, une fois, du plus récent"
    assert morceaux[0]["total"] == 65 and morceaux[0]["comptes"] == {"acceptes": 20, "refuses": 40, "elimine": 5}
    assert [x["ticket"] for x in page2["lignes"]] == [x["ticket"] for x in morceaux[1]["lignes"]], "l'ancienne pagination"
    assert invalide[0] == 400, "une suite illisible est refusée"
    assert grand["n"] == Q.DECIDEES_MAX and len(grand["lignes"]) == 65 and grand["suite"] is None, "100 au plus par morceau"


def test_R27_les_donnees_portent_le_resume_la_fiche_porte_tout(local):
    """`donnees` ne porte plus que le RÉSUMÉ des 30 dernières candidatures décidées (banc de 5 ans : 560 candidats,
    520 Ko) ; la fiche du membre a toutes les siennes : la dernière décision, qui l'a prise, ses réponses, le
    transcript (fiche.js les lit là)."""
    import site_local
    import tableau
    t = int(time.time())

    async def ecrire(sql, lignes):
        async with local.ctx.get_db() as db:
            for x in lignes:
                await db.execute(sql, x)
            await db.commit()
    local.faire(ecrire("INSERT OR REPLACE INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom, ouvert_le, ferme_le,"
                       " ferme_par, reponses, msg_candidat, transcript, raison, decision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       [(site_local.SERVEUR_ID, 80000 + k, 990000 + k, f"Ancien {k}", t - 90 * 86400 - k * 3600,
                         t - 80 * 86400 - k * 3600, FONDATEUR, json.dumps({"Pseudo Roblox": f"Ancien_{k}"}), 3,
                         f"https://exemple.invalid/t/{k}", "Bienvenue à bord", "acceptes") for k in range(45)]))
    try:
        tableau._cache.clear()
        d = local.donnees()
        f = local.fiche(990044)
    finally:
        local.faire(ecrire("DELETE FROM recrutements WHERE ticket_id >= ?", [(80000,)]))
        tableau._cache.clear()
    c = d["candidats"]
    assert len(c) == tableau.CANDIDATS_RECENTS and [x["ferme"] for x in c] == sorted((x["ferme"] for x in c), reverse=True)
    assert not {"reponses", "transcript", "candidatures", "pris_par"} & set().union(*map(set, c)), "le résumé seulement"
    assert "990044" not in {x["id"] for x in c}, "un ancien candidat n'est plus dans les données…"
    derniere = f["candidatures"][0]
    assert (derniere["statut"], derniere["ferme_par"], derniere["raison"]) == ("acceptes", "GoRipe", "Bienvenue à bord")
    assert derniere["reponses"] == [["Pseudo Roblox", "Ancien_44"]] and derniere["transcript"].endswith("/t/44"), \
        "… sa fiche a tout"
    js = (Path(__file__).resolve().parent.parent / "site" / "fiche.js").read_text(encoding="utf-8")
    assert "etat.d.candidats" not in js and '(f.candidatures || []).find((c) => c.statut === "acceptes"' in js


# ═══ R28 : un nombre venu du client = des chiffres 0-9, sinon 400 (revue de sécurité, 27/10/2026) ═══════════════════

#  « ² » : `str.isdigit()` dit oui et `int()` lève (une erreur 500) ; « ١٢ » et « ５ » : `int()` les lit en silence.
PAS_DES_NOMBRES = ("²", "١٢", "５", "1.5", "-3", " 7", "7 ", "0x10", "1e3", "")


def test_R28_un_identifiant_non_ascii_est_refuse_en_400_jamais_500(local):
    """Chaque adresse du recrutement qui lit un numéro (ticket, envoi, membre, rôle, morceau) le lit en chiffres 0-9 :
    autre chose est refusé proprement (400), jamais une erreur 500 ; le bon numéro marche toujours."""
    import questionnaire as Q_
    api = "/tableau/espace/api/recrutement/"
    lectures = [("dossier", "ticket", {}), ("proposition", "ticket", {}), ("apercu", "ticket", {}), ("apercu", "envoi", {}),
                ("chefs/proposition", "membre", {"metier": "navigation"}), ("chefs/dossier", "envoi", {}),
                ("chef", "membre", {}), ("decidees", "n", {}), ("decidees", "page", {}), ("decidees", "avant", {})]
    vus = {}
    for route, cle, autres in lectures:
        for brut in PAS_DES_NOMBRES:
            if brut == "" and (route == "decidees" or cle == "envoi"):
                continue   # vide : le défaut (le premier morceau), ou l'autre clé d'`apercu`
            valeur = brut + ":1:1" if cle == "avant" and brut else brut
            st, rep = local.get(api + route, **dict(autres, **{cle: valeur}))
            vus[(route, cle, brut)] = st
            assert st == 400, f"{route}?{cle}={brut!r} → {st} {rep}"
    #  Les écritures : le même nombre lu dans le corps (`_entier`), et le verrou d'une correction.
    for route, corps in (("etape1", {"ticket": "²"}), ("decision", {"ticket": "١٢", "accepte": True}),
                         ("corriger", {"envoi": "²", "question": "q1", "juste": True}),
                         ("liste_noire/lever", {"membre": "５"}), ("chefs/retirer", {"membre": "²"})):
        st, rep = local.post(api + route, corps)
        assert st in (400, 404, 409) and st != 500, f"{route} {corps} → {st} {rep}"
    #  Les bons numéros passent toujours (et un numéro inconnu reste un 404, pas une erreur).
    ticket = local.get(api + "suivi")[1]["ouverts"][0]["ticket"]
    assert local.get(api + "dossier", ticket=str(ticket))[0] == 200
    assert local.get(api + "dossier", ticket="999999")[0] == 404
    assert local.get(api + "decidees", n="5")[0] == 200
    #  Le lecteur lui-même.
    assert [Q_._chiffres(x) for x in ("0", "42", "007", "²", "١٢", "５", "-1", "", None, True, 12, -4)] == \
        [0, 42, 7, None, None, None, None, None, None, None, 12, None]
    assert Q_._chiffres("1" * 21) is None and Q_._chiffres("1" * 16, 15) is None
