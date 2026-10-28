"""27/10/2026 — interdire des tickets depuis la fiche d'une personne (tickets_interdits.py), en SILENCE.

Le fondateur : « qu'on puisse le blacklist des tickets et qu'on décide de quel type de ticket il n'a pas le droit de
créer… des tickets serveurs ou des tickets du clan » ; puis « ils ne doivent pas recevoir de messages en privé ou quoi
que ce soit… Ils l'apprennent quand ils veulent recréer un ticket. Mais ils ne savent pas de qui, de quoi, comment. »

Sur le VRAI chemin du bot (`banc_ticket_recrutement` : les fonctions de bot.py sur le faux Discord, questionnaire.py
branché comme au démarrage) :
I1 deux familles, celles du site ; un nouveau panneau se range seul · I2 serveur seul, clan seul, les deux, la levée —
les MÊMES listes que lit le bot, le clan par la liste noire du recrutement · I3 la version lue (409), rien d'écrit ·
I4 la tête seule écrit ; le fondateur, la direction, le bot : jamais interdits · I5 `/mod ticketblacklist` voit et
modifie les mêmes données (un panneau du clan rouvert lève l'entrée du recrutement) · I6 la liste noire du recrutement :
posée ici, lue là-bas ; levée là-bas, lue ici · I7 au clic : un refus ÉPHÉMÈRE et générique, l'autre famille ouverte ·
I8 le refus ne dit ni qui, ni pourquoi, ni quand — même réécrit avec {motif} ou {par} · I9 les messages privés de
refus ne parlent jamais de liste noire · I10 aucun envoi à la personne, sur chaque chemin d'interdiction ou de levée.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import discord
import pytest

import questionnaire as Q
import rellseas_panneau
import textes
import tickets_interdits as TI
from banc_ticket_recrutement import AUTRE, BOT, CANDIDAT, DIRECTION, FONDATEUR, BancTicket, Inter
from conftest_discord import Obj, laisser_finir
from faux_serveur import run, textes as texte_vue
from ui_v2 import Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
MOTS_INTERDITS = ("liste noire", "blacklist", "pourras", "plus ouvrir", "postuler", "candidater", "interdit")


@pytest.fixture(autouse=True)
def _sans_attente(monkeypatch):
    monkeypatch.setattr(Q, "DELAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "AVIS_S", 0)
    monkeypatch.setattr(Q, "PAGE_S", 0)
    monkeypatch.setattr(Q, "REESSAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "REPRISE_MIN", 0.0)
    monkeypatch.setattr(Q, "_delai", lambda p: 0.0)


class InterK(Inter):
    """Une interaction qui garde aussi les options de chaque réponse (éphémère, mentions permises)."""

    def __init__(self, *a, **k):
        self.kw = []
        super().__init__(*a, **k)

    async def _repondre(self, content=None, **kw):
        self.kw.append(kw)
        await super()._repondre(content, **kw)


def banc(tmp_path) -> BancTicket:
    b = BancTicket(tmp_path)
    b.logs_q, b.logs_ti = [], []
    b.monter(log=b.logs_q.append)
    TI.setup(get_db=b.get_db, cfg=b.cfg, db_set=b.db_set, tete={FONDATEUR, DIRECTION},
             exempte=b.ns["_ticket_sans_limite"], robot=lambda: BOT, log=b.logs_ti.append)
    return b


async def preparer(b):
    await b.preparer()
    await TI.init_db()


def listes(b) -> dict:
    return {pid: list(p.get("blacklist") or []) for pid, p in b.conf["ticket_panels"].items()}


async def ecrire(b, route, auteur=None, **corps):
    """Une écriture du site, avec la version lue juste avant (comme la page)."""
    e = await TI.etat(b.g, int(corps.get("membre", CANDIDAT)))
    c = dict({"membre": str(CANDIDAT), "version": e["version"]}, **corps)
    fn = TI._r_interdire if route == "interdire" else TI._r_lever
    return await fn(b.g, auteur or b.fondateur, {}, c)


def silence(b):
    """Rien n'est parti vers la personne : aucun message privé, rien de posté dans un salon ou un fil."""
    assert b.candidat.mp == [], b.candidat.mp
    assert not b.porteur.envois and not [m for f in b.g.fils.values() for m in getattr(f, "messages", [])]


# ═══ I1 : les familles ═════════════════════════════════════════════════════════════════════════════════════════

def test_I1_deux_familles_celles_du_site_un_nouveau_panneau_se_range_seul():
    c = {"ticket_panels": {"p1": {"name": "Recrutement Rell Seas"}, "p2": {"name": "Support"}, "p3": {"name": "Signalement"}}}
    assert {p["id"]: p["famille"] for p in TI.panneaux(c)} == {"p1": "clan", "p2": "serveur", "p3": "serveur"}
    c["ticket_panels"]["p4"] = {"name": "Chefs d'équipe · RELL Seas"}
    assert TI.famille(c, "p4") == "clan", "un nouveau panneau se range de lui-même"
    c[rellseas_panneau.CLE_TICKETS] = ["p3"]
    assert TI.famille(c, "p3") == "clan" and TI.famille(c, "p1") == "serveur", "le choix de /configure passe avant le nom"
    #  La classification de la page « Tickets » (tableau._tickets : « rellseas ») : la même fonction.
    assert "rell = rellseas_panneau.panneaux_tickets(c)" in (RACINE / "tableau.py").read_text(encoding="utf-8")


# ═══ I2 : serveur seul, clan seul, les deux, la levée ══════════════════════════════════════════════════════════

def test_I2_serveur_seul_clan_seul_les_deux_puis_la_levee(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await preparer(b)
        vus = {}
        vus["serveur"] = (await ecrire(b, "interdire", familles=["serveur"], motif="Spam de tickets"), listes(b),
                          await Q.sur_liste_noire(b.g.id, CANDIDAT))
        vus["clan"] = (await ecrire(b, "interdire", familles=["clan"], motif="Réponses copiées"), listes(b),
                       await Q.sur_liste_noire(b.g.id, CANDIDAT), await Q.liste_noire_site(b.g))
        vus["lever_serveur"] = (await ecrire(b, "lever", familles=["serveur"]), listes(b))
        vus["lever_clan"] = (await ecrire(b, "lever", familles=["clan"]), listes(b), await Q.sur_liste_noire(b.g.id, CANDIDAT),
                             await Q.liste_noire_site(b.g))
        vus["deux"] = (await ecrire(b, "interdire", familles=["serveur", "clan"]), listes(b))
        vus["lever_deux"] = (await ecrire(b, "lever", familles=["serveur", "clan"]), listes(b),
                             await Q.sur_liste_noire(b.g.id, CANDIDAT))
        return vus
    v = run(sc())
    (st, rep), l, rec = v["serveur"]
    assert st == 200 and rep["ok"] and "Il n'est pas prévenu" in rep["message"]
    assert l == {"p1": [], "p2": [CANDIDAT]} and rec is False, "le serveur seul : sa liste, rien au recrutement"
    s = rep["etat"]["familles"]["serveur"]
    assert (s["etat"], s["motif"], s["par"]["id"], s["source"]) == ("interdit", "Spam de tickets", str(FONDATEUR), "site")
    assert s["depuis"] > 0 and rep["etat"]["familles"]["clan"]["etat"] == "autorise"
    assert rep["_journal"]["membre_id"] == CANDIDAT and "interdits à Kolax" in rep["_journal"]["texte"]
    (st, rep), l, rec, noire = v["clan"]
    assert st == 200 and l == {"p1": [CANDIDAT], "p2": [CANDIDAT]} and rec is True, "le clan : la liste noire du recrutement"
    entree = next(x for x in noire["actifs"] if x["membre"]["id"] == str(CANDIDAT))
    assert entree["motif"] == "Réponses copiées" and entree["par"]["id"] == str(FONDATEUR) and not entree["ancien"]
    c = rep["etat"]["familles"]["clan"]
    assert (c["etat"], c["source"], c["motif"]) == ("interdit", "recrutement", "Réponses copiées")
    (st, rep), l = v["lever_serveur"]
    assert st == 200 and l == {"p1": [CANDIDAT], "p2": []} and rep["etat"]["familles"]["clan"]["etat"] == "interdit"
    (st, rep), l, rec, noire = v["lever_clan"]
    assert st == 200 and l == {"p1": [], "p2": []} and rec is False
    assert any(x["membre"]["id"] == str(CANDIDAT) for x in noire["leves"]), "la levée se lit dans la liste noire"
    assert {f: x["etat"] for f, x in rep["etat"]["familles"].items()} == {"serveur": "autorise", "clan": "autorise"}
    (st, rep), l = v["deux"]
    assert st == 200 and l == {"p1": [CANDIDAT], "p2": [CANDIDAT]}
    (st, rep), l, rec = v["lever_deux"]
    assert st == 200 and l == {"p1": [], "p2": []} and rec is False
    silence(b)


# ═══ I3 – I4 : la version, la tête seule, les personnes jamais interdites ═══════════════════════════════════════

def test_I3_une_version_perimee_est_refusee_et_rien_n_est_ecrit(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await preparer(b)
        vieille = (await TI.etat(b.g, CANDIDAT))["version"]
        await ecrire(b, "interdire", familles=["serveur"])
        apres = listes(b)
        refus = await TI._r_lever(b.g, b.fondateur, {}, {"membre": str(CANDIDAT), "version": vieille, "familles": ["serveur"]})
        return apres, refus, listes(b)
    apres, (st, rep), fin = run(sc())
    assert st == 409 and rep["conflit"] and rep["etat"]["familles"]["serveur"]["etat"] == "interdit"
    assert fin == apres == {"p1": [], "p2": [CANDIDAT]}


def test_I4_la_tete_seule_ecrit_et_le_fondateur_la_direction_le_bot_jamais_interdits(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await preparer(b)
        hors = await ecrire(b, "interdire", auteur=b.autre, familles=["serveur"])
        cibles = {}
        for uid in (FONDATEUR, DIRECTION, BOT):
            e = await TI.etat(b.g, uid)
            cibles[uid] = (e["protege"], await TI._r_interdire(b.g, b.fondateur, {}, {
                "membre": str(uid), "version": e["version"], "familles": ["serveur", "clan"]}))
        mauvais = [await TI._r_interdire(b.g, b.fondateur, {}, x) for x in (
            {}, {"membre": "²", "version": "0" * 12, "familles": ["serveur"]},
            {"membre": str(CANDIDAT), "version": "0" * 12, "familles": ["partout"]},
            {"membre": str(CANDIDAT), "version": "0" * 12},
            {"membre": str(CANDIDAT), "version": "0" * 12, "familles": ["serveur"], "motif": "x" * 151})]
        return hors, cibles, mauvais, listes(b), await Q.sur_liste_noire(b.g.id, FONDATEUR)
    hors, cibles, mauvais, l, rec = run(sc())
    assert hors[0] == 403, "hors de la tête : refusé"
    for uid, (protege, (st, rep)) in cibles.items():
        assert protege and st == 403 and rep["erreur"] == protege, (uid, st, rep)
    assert "jamais interdits" in cibles[FONDATEUR][0] and "robot" in cibles[BOT][0]
    assert [st for st, _r in mauvais] == [400] * 5
    assert l == {"p1": [], "p2": []} and rec is False, "rien d'écrit"
    assert TI.ROUTES_SITE["tickets/interdire"]["ecriture"] and not TI.ROUTES_SITE["tickets/interdire"].get("hors_ligne")


# ═══ I5 : /mod ticketblacklist — les mêmes données ══════════════════════════════════════════════════════════════

def _commande(b, journal):
    """`ticketblacklist_cmd` de bot.py (sans ses décorateurs de commande), sur le banc."""
    n = next(x for x in ARBRE.body if isinstance(x, ast.AsyncFunctionDef) and x.name == "ticketblacklist_cmd")
    n = ast.AsyncFunctionDef(**{k: getattr(n, k) for k in n._fields if k != "decorator_list"}, decorator_list=[])
    ast.fix_missing_locations(n)

    async def au_journal(*a, **k):
        journal.append((a, k))
    ns = {"discord": discord, "cfg": b.cfg, "db_set": b.db_set, "_au_journal": au_journal, "Palette": Palette,
          "_vue_blacklist": lambda texte, *_a: ("carte", texte), "tickets_interdits": TI}
    exec(compile(ast.Module(body=[n], type_ignores=[]), "bot.py", "exec"), ns)  # noqa: S102 — code du dépôt
    return ns["ticketblacklist_cmd"]


class Reponse:
    def __init__(self):
        self.envois = []

    async def send_message(self, *a, **kw):
        self.envois.append((a, kw))

    def is_done(self):
        return bool(self.envois)


def test_I5_la_commande_ticketblacklist_voit_et_modifie_les_memes_listes(tmp_path):
    b = banc(tmp_path)
    b.g.owner_id = FONDATEUR
    chef = Obj(id=DIRECTION, display_name="Capitaine", roles=[], guild_permissions=Obj(administrator=True))
    journal = []
    cmd = _commande(b, journal)

    async def sc():
        await preparer(b)
        i_add = Obj(guild=b.g, user=chef, response=Reponse())
        await cmd(i_add, "add", b.candidat, "Support")
        apres_add = await TI.etat(b.g, CANDIDAT)
        await ecrire(b, "interdire", familles=["clan"], motif="Réponses copiées")   # le site, par la liste noire
        i_list = Obj(guild=b.g, user=chef, response=Reponse())
        await cmd(i_list, "list")
        i_rm = Obj(guild=b.g, user=chef, response=Reponse())
        await cmd(i_rm, "remove", b.candidat, "Recrutement Rell Seas")
        await laisser_finir()
        ouvre = InterK(b, b.candidat)
        await b.ns["_ticket_ouvrir"](ouvre, "p1")
        return (i_add, apres_add, i_list, i_rm, await TI.etat(b.g, CANDIDAT), await Q.sur_liste_noire(b.g.id, CANDIDAT),
                listes(b), ouvre)
    i_add, apres_add, i_list, i_rm, fin, rec, l, ouvre = run(sc())
    s = apres_add["familles"]["serveur"]
    assert (s["etat"], s["par"]["id"], s["source"]) == ("interdit", str(DIRECTION), "commande"), "la fiche lit la commande"
    assert "Kolax" in str(i_list.response.envois[0][1]["view"]) or str(CANDIDAT) in str(i_list.response.envois[0][1]["view"])
    assert rec is False and l == {"p1": [], "p2": [CANDIDAT]}, "un panneau du clan rouvert lève aussi l'entrée du recrutement"
    assert fin["familles"]["clan"]["etat"] == "autorise" and fin["familles"]["serveur"]["etat"] == "interdit"
    assert "Es-tu sûr" in texte_vue(ouvre.messages[0]), "rouvert par la commande : il peut ouvrir le panneau du clan"
    for i in (i_add, i_rm):
        a, kw = i.response.envois[-1]
        assert kw.get("ephemeral") is True and kw.get("allowed_mentions") is not None \
            and not kw["allowed_mentions"].users, "une réponse pour soi, sans mention qui préviendrait"
    silence(b)


# ═══ I6 : la liste noire du recrutement ═════════════════════════════════════════════════════════════════════════

def test_I6_la_liste_noire_du_recrutement_et_la_fiche_disent_la_meme_chose(tmp_path):
    b = banc(tmp_path)

    async def sc():
        await preparer(b)
        await Q.mettre_sur_liste_noire(b.g, CANDIDAT, motif="Refus à l'étape 1", par=DIRECTION)   # posée là-bas
        la_bas = await TI.etat(b.g, CANDIDAT)
        lever = await Q._r_liste_noire_lever(b.g, b.fondateur, {}, {"membre": str(CANDIDAT)})       # levée là-bas
        apres = await TI.etat(b.g, CANDIDAT)
        await ecrire(b, "interdire", panneaux=["p1"])                                                # le réglage fin
        fin = await Q.liste_noire_site(b.g)
        return la_bas, lever, apres, fin
    la_bas, lever, apres, fin = run(sc())
    c = la_bas["familles"]["clan"]
    assert (c["etat"], c["motif"], c["par"]["id"]) == ("interdit", "Refus à l'étape 1", str(DIRECTION))
    assert lever[0] == 200 and apres["familles"]["clan"]["etat"] == "autorise", "une levée là-bas se lit sur la fiche"
    assert any(x["membre"]["id"] == str(CANDIDAT) for x in fin["actifs"]), "un panneau du clan interdit ici se lit là-bas"


# ═══ I7 – I8 : au clic, un refus éphémère et générique ═══════════════════════════════════════════════════════════

def test_I7_au_clic_un_refus_ephemere_et_l_autre_famille_reste_ouverte(tmp_path):
    b = banc(tmp_path)

    async def clic(pid):
        i = InterK(b, b.candidat)
        await b.ns["_ticket_ouvrir"](i, pid)
        return i, texte_vue(i.messages[0]) if i.messages and hasattr(i.messages[0], "to_components") else str(i.messages)

    async def sc():
        await preparer(b)
        await ecrire(b, "interdire", familles=["clan"], motif="Réponses copiées")
        clan_ferme, serveur_ouvert = await clic("p1"), await clic("p2")
        await ecrire(b, "lever", familles=["clan"])
        await ecrire(b, "interdire", familles=["serveur"], motif="Spam de tickets")
        serveur_ferme, clan_ouvert = await clic("p2"), await clic("p1")
        #  Le filet du bot (`_create_ticket_corps`) : la même réponse générique, même par un autre chemin.
        ch, err = await b.ns["create_ticket"](Inter(b, b.candidat), "p2", {})
        return clan_ferme, serveur_ouvert, serveur_ferme, clan_ouvert, (ch, err)
    clan_ferme, serveur_ouvert, serveur_ferme, clan_ouvert, (ch, err) = run(sc())
    for i, t in (clan_ferme, serveur_ferme):
        assert "Tu ne peux pas ouvrir ce type de ticket pour le moment." in t, t
        assert i.kw[0].get("ephemeral") is True, "un avis pour lui seul"
    assert "Confirmer l'ouverture" in " ".join(serveur_ouvert[1:]) or "Tu vas ouvrir" in serveur_ouvert[1]
    assert "Es-tu sûr" in clan_ouvert[1], "l'autre famille reste ouverte"
    assert ch is None and err == TI.REFUS
    silence(b)


def test_I8_le_refus_ne_dit_ni_qui_ni_pourquoi_ni_quand_meme_reecrit(tmp_path, monkeypatch):
    b = banc(tmp_path)
    piege = "Refus {motif} par {par} depuis {depuis} {quand} {auteur} {date}"
    cache = {b.g.id: {TI.CLE_REFUS: (piege, 1, 0, 0), "recrutement.liste_noire.refus": (piege, 1, 0, 0)}}
    monkeypatch.setattr(textes, "_cache", cache)
    monkeypatch.setitem(textes._etat, "charge", True)

    async def sc():
        await preparer(b)
        await ecrire(b, "interdire", familles=["serveur", "clan"], motif="Spam de tickets")
        lus = []
        for pid in ("p1", "p2"):
            i = InterK(b, b.candidat)
            await b.ns["_ticket_ouvrir"](i, pid)
            lus.append(texte_vue(i.messages[0]))
        return lus
    for t in run(sc()):
        assert "{motif}" in t and "Spam" not in t and "GoRipe" not in t and str(FONDATEUR) not in t
        assert not re.search(r"\d{1,2}/\d{1,2}|\d{4}", t), "aucune date"
    #  Le code ne leur passe jamais de valeur : deux arguments, aucun mot-clé ; déclarés sans variable.
    appels = [n for n in ast.walk(ARBRE) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "texte"
              and any(isinstance(a, ast.Constant) and a.value in (TI.CLE_REFUS, "recrutement.liste_noire.refus") for a in n.args)]
    assert len(appels) >= 3 and all(len(n.args) == 2 and not n.keywords for n in appels)
    for cle in (TI.CLE_REFUS, "recrutement.liste_noire.refus"):
        assert not textes._DECLARES[cle]["variables"], cle


# ═══ I9 – I10 : les messages privés, et le silence sur chaque chemin ═══════════════════════════════════════════════

def test_I9_les_messages_prives_de_refus_ne_parlent_jamais_de_liste_noire(tmp_path):
    for cle in ("recrutement.mp.refusee", "recrutement.mp.demande_refusee", "recrutement.refus_final",
                "recrutement.refus_etape1", "recrutement.elimine", TI.CLE_REFUS, "recrutement.liste_noire.refus"):
        t = textes.defaut(cle).lower()
        assert not [m for m in MOTS_INTERDITS if m in t], (cle, t)
    assert not textes.declare("recrutement.mp.liste_noire"), "plus de ligne « liste noire » ajoutée au message privé"
    assert "recrutement.mp.liste_noire" not in (RACINE / "questionnaire.py").read_text(encoding="utf-8")
    b = banc(tmp_path)

    async def sc():
        await preparer(b)
        st, rep = await Q.enregistrer_parcours(b.g, b.fondateur, {"panneau": "p1", "version": 0, "mode": "approbation",
                                                                  "gabarit": [], "exigence": 100, "delai": 5,
                                                                  "liste_noire": True, "metier": True})
        assert st == 200, rep
        tid, _fil = await b.ouvrir_ticket()
        await Q._r_etape1(b.g, b.fondateur, {}, {"ticket": tid, "decision": "refuser", "note": "pseudo introuvable"})
        await laisser_finir()
        return await TI.etat(b.g, CANDIDAT)
    e = run(sc())
    mp = " ".join(texte_vue(kw["view"]) if kw.get("view") is not None else str(c or "") for c, kw in b.candidat.mp).lower()
    assert "n'est pas retenue" in mp and not [m for m in MOTS_INTERDITS if m in mp], mp
    assert e["familles"]["clan"]["etat"] == "interdit" and e["familles"]["clan"]["source"] == "recrutement", \
        "refusé : ses tickets du clan interdits, sans le lui dire"


def test_I10_aucun_envoi_a_la_personne_sur_chaque_chemin(tmp_path):
    """Le site (interdire, lever) : prouvé par I2, I5, I7 (`silence`). Ici, les chemins de bot.py, lus dans leur source :
    jamais un envoi à la personne (ni `.send`, ni une réponse publique) — des réponses pour soi, sans mention."""
    def fonction(nom, classe=None):
        for n in ast.walk(ARBRE):
            if isinstance(n, ast.ClassDef) and classe and n.name == classe:
                return next(x for x in n.body if getattr(x, "name", "") == nom)
            if not classe and isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == nom:
                return n
        raise AssertionError(nom)
    for nom, classe in (("ticketblacklist_cmd", None), ("blacklist_user", "TicketControlView")):
        f = fonction(nom, classe)
        envois = [n for n in ast.walk(f) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in
                  ("send", "send_message", "followup")]
        for n in envois:
            src = ast.unparse(n)
            assert src.startswith("i.response.send_message("), (nom, src)
            assert "ephemeral=True" in src, (nom, src)
        assert "tickets_interdits." in ast.unparse(f), f"{nom} : la fiche lit qui et depuis quand"
    #  Le silence au refus d'une candidature et à l'élimination d'office : plus de ligne ajoutée au message privé.
    for nom in ("refuser", "eliminer"):
        src = ast.unparse(next(n for n in ast.parse((RACINE / "questionnaire.py").read_text(encoding="utf-8")).body
                               if isinstance(n, ast.AsyncFunctionDef) and n.name == nom))
        assert "mp.liste_noire" not in src and "mettre_sur_liste_noire" in src, nom
    #  tickets_interdits.py n'envoie rien à personne.
    module = (RACINE / "tickets_interdits.py").read_text(encoding="utf-8")
    assert not re.search(r"\.send\(|send_message|followup|create_dm", module)
