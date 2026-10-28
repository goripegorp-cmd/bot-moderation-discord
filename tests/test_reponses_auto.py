"""27/10/2026 — exigence 12 du fondateur : « le bot répond, pas le site ». Une demande d'aide dans un salon : le bot
oriente lui-même (demande d'aide du bon jeu, FAQ, vrais salons) UNE fois, puis rien, puis UN rappel seulement s'il n'a
pas créé sa demande ; jamais de « Question sans réponse » à traiter sur le site."""
from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path

import aiosqlite
import discord
import pytest

import entraide
import questions
import reponses_auto as R
from conftest_discord import Obj
from faux_serveur import Fil, Monde, run, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


class Message:
    n = 5000

    def __init__(self, salon, auteur, texte):
        Message.n += 1
        self.id = Message.n
        self.guild, self.channel, self.author, self.content, self.webhook_id = salon.monde, salon, auteur, texte, None
        self.reference, self.mentions, self.raw_mentions = None, [], []
        self.reponses = []

    async def reply(self, **kw):
        self.reponses.append(kw)
        return Obj(id=self.id + 100000)


@pytest.fixture
def env(tmp_path):
    chemin = tmp_path / "r.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    conf = {"zones_posts": {}}
    staff, langues, demandes = set(), {}, {}

    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v

    def destinations(g, _c):
        return {"ticket": "https://discord.com/channels/1/40", "suggestions": "https://discord.com/channels/1/43",
                "type_clan": "Rell Seas",
                "jeux": [{"cle": "rell", "nom": "Rell Seas", "emoji": "🌊", "mots": ("rell",), "forum": 0,
                          "trade": "https://discord.com/channels/1/42", "help": "https://discord.com/channels/1/44",
                          "annonces": "", "lien": ""}]}

    async def langue(m):
        return langues.get(m.id, "fr")

    async def est_ticket(_ch):
        return False
    R.setup(get_db=get_db, cfg=cfg, db_set=db_set, destinations=destinations, est_staff=lambda g, m, c: m.id in staff,
            langue=langue, exclus=lambda g, c: set(), est_ticket=est_ticket, log=lambda *a: None)
    questions.setup(get_db=get_db, est_staff=lambda g, m, c: m.id in staff, log=lambda *a: None)
    asyncio.run(R.init_db())
    asyncio.run(questions.init_db())
    vraie = entraide.demandes_aide

    async def demandes_aide(_gid, uid):
        return demandes.get(uid, (0, 0))
    entraide.demandes_aide = demandes_aide
    g = Monde()

    class Public:
        def permissions_for(self, _r):
            return discord.Permissions(view_channel=True, send_messages=True, send_messages_in_threads=True)
    chat = Fil(g, 900, Public(), "💬 Chat")
    chat.is_private = lambda: False
    chat.guild = g
    yield Obj(g=g, chat=chat, staff=staff, langues=langues, demandes=demandes, conf=conf)
    entraide.demandes_aide = vraie


def _dire(e, uid, texte, t):
    m = Message(e.chat, e.g.membre(uid), texte)
    return m, run(R.sur_message(m, maintenant=t, attente=0))


def test_R1_une_question_frequente_une_carte_qui_s_efface(env):
    m, fait = _dire(env, 7, "Comment on fait pour rejoindre le clan ?", 1000.0)
    assert fait == "reponse"
    kw = m.reponses[0]
    assert kw["delete_after"] == R.EFFACER_S and kw["mention_author"] is False, "le chat reste propre"
    assert "(type « Rell Seas »)" in textes(kw["view"])
    _m2, fait2 = _dire(env, 8, "comment rejoindre le clan svp ?", 1100.0)
    assert fait2 == "retenue", "même sujet, même salon, 5 minutes : une seule carte"


def test_R2_une_fois_puis_rien_puis_un_seul_rappel_sans_demande(env):
    t = 10_000.0
    assert _dire(env, 9, "quelqu'un peut m'aider sur rell ?", t)[1] == "reponse"
    assert _dire(env, 9, "quelqu'un peut m'aider sur rell ?", t + 1200)[1] == "retenue", "redemande tôt : rien"
    m, fait = _dire(env, 9, "quelqu'un peut m'aider sur rell ?", t + 4000)
    assert fait == "rappel" and m.reponses, "plus d'une heure après, sans demande : UN rappel"
    assert _dire(env, 9, "quelqu'un peut m'aider sur rell ?", t + 9000)[1] == "retenue", "plus de rappel"


def test_R3_sa_demande_d_aide_existe_plus_rien(env):
    t = 50_000.0
    assert _dire(env, 10, "j'ai besoin d'aide sur rell", t)[1] == "reponse"
    env.demandes[10] = (int(t + 600), 1)
    assert _dire(env, 10, "j'ai besoin d'aide sur rell", t + 5000)[1] == "retenue"


def test_R4_le_staff_le_bavardage_et_l_aide_proposee_n_ont_rien(env):
    env.staff.add(7)
    assert _dire(env, 7, "comment créer un ticket ?", 1.0)[1] == ""
    assert _dire(env, 11, "ma pp est bien ?", 2.0)[1] == ""
    assert _dire(env, 12, "je peux t'aider si tu veux", 3.0)[1] == ""
    assert _dire(env, 13, "ça va ?", 4.0)[1] == ""


def test_R5_la_question_n_attend_plus_le_staff(env):
    """Ce que le bot a traité ne reste jamais « sans réponse » sur le site."""
    m, fait = _dire(env, 14, "comment ouvrir un ticket ?", 70_000.0)
    assert fait == "reponse"
    l = run(questions.lister(env.g.id, 70_010.0))["liste"]
    assert all(q["statut"] != "ouverte" for q in l if q.get("message", "").endswith(str(m.id)))


def test_R6_la_tete_coupe_les_reponses_ici(env):
    st, r = run(R.regler(env.g, None, {"cible": "tout", "actif": False, "version": 0}))
    assert st == 200 and r["reglages"]["actif"] is False
    assert _dire(env, 15, "comment ouvrir un ticket ?", 90_000.0)[1] == ""
    st, _r = run(R.regler(env.g, None, {"cible": "tout", "actif": True, "version": 0}))
    assert st == 409, "une version dépassée est refusée"


def test_R7_branche_dans_le_bot_et_le_site():
    arbre = ast.unparse(ast.parse(SRC))
    assert "await reponses_auto.sur_message(msg)" in arbre and "reponses_auto.setup(" in SRC
    assert "tableau.monter(reponses_auto.ROUTES_SITE)" in SRC and "await reponses_auto.init_db()" in SRC
    assert "faq.setup(" not in SRC and "faq.set_hooks(" not in SRC and "faq.sur_message(" not in SRC
    assert "*reponses_auto.PURGES," in (RACINE / "data_cleanup.py").read_text(encoding="utf-8")
    accueil = (RACINE / "site" / "accueil.js").read_text(encoding="utf-8")
    assert "sans réponse\", sous" not in accueil and "Question de \" + nomDe(p)" not in accueil
    assert "vueReponsesBot" in (RACINE / "site" / "discord.js").read_text(encoding="utf-8")


def test_R8_silence_dans_help_et_trade_et_effacement_qui_survit(env):
    effaces = []

    async def plus_tard(_m, s):
        effaces.append(s)
    R._exclus, R._effacer_plus_tard = (lambda _g, _c: {env.chat.id}), plus_tard
    assert _dire(env, 20, "comment on peut faire du trading ?", 1.0)[1] == "", "🛟 Help / 🤝 Trade : on y répond aux cartes"
    R._exclus = lambda _g, _c: set()
    assert _dire(env, 20, "comment on peut faire du trading ?", 10.0)[1] == "reponse"
    assert effaces == [R.EFFACER_S], "l'effacement survit au redémarrage"
    assert _dire(env, 21, "comment on peut faire du trading ?", 10.0 + R.SUJET_SALON_S + 1)[1] == "reponse", \
        "un autre membre, après la cadence du salon : il a sa réponse"
