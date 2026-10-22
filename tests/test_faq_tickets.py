"""22/10/2026 : « les gens qui posent des questions — comment on fait pour rejoindre le clan, pour créer
un ticket staff, pour venir dans l'équipage… ça les renvoie dans le système de tickets… comment on peut
faire du trading, des suggestions… vers des salons, avec des réponses ultra bien faites » ; et « un
bouton, nous, la direction, et le fondateur… bloquer la création des tickets… cibler ce qu'on bloque :
les tickets serveur, les tickets du clan »."""
from __future__ import annotations

import ast
import time
from pathlib import Path

import discord
import pytest

import faq
from conftest_discord import Obj
from faux_serveur import Fil, Monde, interaction, run, textes
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)


# ─── Les réponses toutes faites ──────────────────────────────────────────────

QUESTIONS = {
    "Comment on fait pour rejoindre le clan ?": ("clan", "fr"),
    "how can I join the clan?": ("clan", "en"),
    "comment créer un ticket staff ?": ("ticket", "fr"),
    "Comment je fais pour venir dans un équipage ?": ("equipage", "fr"),
    "comment on peut faire du trading ?": ("trade", "fr"),
    "comment faire une suggestion ?": ("suggestion", "fr"),
    "quelqu'un peut m'aider pour le boss ?": ("aide_jeu", "fr"),
    "comment on peut demander de l'aide pour le clan ?": ("aide_clan", "fr"),
    "where is the crew list?": ("equipage", "en"),
    "ça va ?": (None, ""),
    "tu as farm combien aujourd'hui ?": (None, ""),
    "quel est le meilleur fruit du jeu ?": (None, ""),
}


def test_F1_chaque_question_trouve_son_sujet_dans_sa_langue():
    for q, (cle, langue) in QUESTIONS.items():
        s, l = faq.reconnaitre(q)
        assert (getattr(s, "cle", None), l) == (cle, langue), q
    assert faq.reconnaitre("rejoindre le clan")[0] is None, "pas une question : rien"


def test_F2_la_carte_mene_au_bon_endroit_dans_la_bonne_langue():
    s, _ = faq.reconnaitre("comment rejoindre le clan ?")
    v = faq.vue(s, "fr", "https://discord.com/channels/1/50", "Rell Seas")
    t = textes(v)
    assert "Rejoindre le clan" in t and "(type « Rell Seas »)" in t and "Ouvrir un ticket" in t
    bouton = next(c for c in v.walk_children() if isinstance(c, discord.ui.Button))
    assert bouton.url == "https://discord.com/channels/1/50"
    t = textes(faq.vue(s, "en", "https://x.y/1"))
    assert "Join the clan" in t and "Open a ticket" in t and "(type" not in t
    assert all(len(x.titre_fr) <= 40 for x in faq.SUJETS)


class Message:
    def __init__(self, salon, auteur, texte):
        self.guild, self.channel, self.author, self.content, self.webhook_id = salon.monde, salon, auteur, texte, None
        self.reponses = []

    async def reply(self, **kw):
        self.reponses.append(kw)


@pytest.fixture
def faq_env():
    conf = {"zones_posts": {}}
    staff, langues = set(), {}

    async def cfg(_gid):
        return conf

    def destinations(g, _c):
        return {"ticket": "https://discord.com/channels/1/40", "crews": "https://discord.com/channels/1/41",
                "trade": "https://discord.com/channels/1/42", "suggestions": "https://discord.com/channels/1/43",
                "help": "", "type_clan": "Rell Seas"}

    async def langue(m):
        return langues.get(m.id, "fr")
    faq._membres.clear()
    faq._salons.clear()
    faq.setup(cfg=cfg, destinations=destinations, est_staff=lambda g, m, c: m.id in staff, langue=langue,
              log=lambda *a: None)
    g = Monde()

    class Public:
        def permissions_for(self, _r):
            return discord.Permissions(view_channel=True, send_messages=False, send_messages_in_threads=True)
    chat = Fil(g, 900, Public(), "💬 Chat")
    chat.is_private = lambda: False
    chat.guild = g
    return Obj(g=g, chat=chat, staff=staff, langues=langues)


def test_F3_une_carte_en_reponse_qui_s_efface_et_ne_se_repete_pas(faq_env):
    g, chat = faq_env.g, faq_env.chat
    m = Message(chat, g.membre(7), "Comment on fait pour rejoindre le clan ?")
    assert run(faq.sur_message(m, maintenant=1000.0))
    kw = m.reponses[0]
    assert kw["delete_after"] == faq.EFFACER_S and kw["mention_author"] is False, "le chat reste propre"
    assert "(type « Rell Seas »)" in textes(kw["view"])
    m2 = Message(chat, g.membre(8), "comment rejoindre le clan svp ?")
    assert not run(faq.sur_message(m2, maintenant=1100.0)), "même sujet, même salon, 5 minutes : une seule carte"
    assert run(faq.sur_message(m2, maintenant=1000.0 + faq.SALON_S + 1))
    m3 = Message(chat, g.membre(7), "comment on rejoint le clan ?")
    assert not run(faq.sur_message(m3, maintenant=1000.0 + 2 * faq.SALON_S + 2)), "le même membre : une demi-heure"


def test_F4_le_staff_les_salons_prives_et_les_destinations_manquantes_n_ont_rien(faq_env):
    g, chat = faq_env.g, faq_env.chat
    faq_env.staff.add(7)
    assert not run(faq.sur_message(Message(chat, g.membre(7), "comment créer un ticket ?"), maintenant=1.0))
    chat.is_private = lambda: True
    assert not run(faq.sur_message(Message(chat, g.membre(8), "comment créer un ticket ?"), maintenant=2.0))
    chat.is_private = lambda: False
    assert not run(faq.sur_message(Message(chat, g.membre(9), "quelqu'un peut m'aider pour le boss ?"),
                                   maintenant=3.0)), "pas de post 🛟 Help connu : aucun bouton qui ment"


def test_F5_la_langue_du_membre_quand_la_question_ne_la_dit_pas(faq_env):
    g, chat = faq_env.g, faq_env.chat
    faq_env.langues[7] = "en"
    m = Message(chat, g.membre(7), "trade ? middleman ? svp ?")
    assert run(faq.sur_message(m, maintenant=50.0)) and "Trading" in textes(m.reponses[0]["view"])


# ─── Ouvrir ou fermer les types de ticket ────────────────────────────────────

def _ns_tickets(conf, direction: set):
    journal, rafraichis = [], []

    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v

    async def _au_journal(*a, **k):
        journal.append((a, k))

    async def _rafraichir_hub_tickets(_g):
        rafraichis.append(1)
    ns = {"discord": discord, "Button": discord.ui.Button, "LayoutView": LayoutView, "Palette": Palette,
          "cfg": cfg, "db_set": db_set, "time": time, "_au_journal": _au_journal,
          "_rafraichir_hub_tickets": _rafraichir_hub_tickets,
          "_direction_ou_plus": lambda g, m, c: m.id in direction}
    for nom in ("VueTypesTickets", "TicketHubGererDynamic"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns, journal, rafraichis


def test_T1_la_direction_ferme_un_type_le_panneau_suit(tmp_path):
    conf = {"ticket_panels": {"1": {"name": "Serveur"}, "2": {"name": "Rell Seas", "disabled": False}}}
    ns, journal, rafraichis = _ns_tickets(conf, {11})
    g = Monde()
    i = interaction(g, g.membre(5))
    run(ns["TicketHubGererDynamic"]().callback(i))
    assert i.response.messages[0][0] == "Réservé à la direction et au fondateur."
    i = interaction(g, g.membre(11))
    run(ns["TicketHubGererDynamic"]().callback(i))
    vue = i.response.messages[0][1]["view"]
    assert "Serveur" in textes(vue) and "Rell Seas" in textes(vue) and textes(vue).count("Ouvert · fermer") == 2
    boutons = [b for b in vue.walk_children() if isinstance(b, discord.ui.Button)]
    j = interaction(g, g.membre(11))
    run(boutons[1].callback(j))  # Rell Seas : fermer
    assert conf["ticket_panels"]["2"]["disabled"] is True and conf["ticket_panels"]["2"]["ferme_par"] == 11
    assert conf["ticket_panels"]["1"].get("disabled") is not True, "seul ce type"
    assert rafraichis and "Rell Seas : fermé" in journal[-1][0][3]
    assert "Fermé · rouvrir" in textes(j.response.edits[-1]["view"])
    tout = next(b for b in boutons if b.label == "Tout rouvrir")
    run(tout.callback(interaction(g, g.membre(11))))
    assert not any(p.get("disabled") for p in conf["ticket_panels"].values())


def test_T2_branche_dans_le_bot():
    assert "bot.add_dynamic_items(BoutonArchives, TicketHubGererDynamic)" in SRC
    hub = _source("_build_ticket_hub_view")
    assert "TicketHubGererDynamic().item" in hub and "Fermés pour le moment" in hub, "le panneau dit ce qui est fermé"
    ouvrir = _source("_ticket_ouvrir")
    assert "sont fermés pour le moment" in ouvrir and "tickets are closed for now" in ouvrir
    assert "{'tickethub:open', 'tickethub:gerer'}" in _source("_salon_panneau_tickets")
    assert "bot.add_listener(_faq_hook, 'on_message')" in ast.unparse(ARBRE) and "faq.setup(" in SRC
    dest = _source("_faq_destinations")
    assert "zones_posts" in dest and "_salon_des_tickets(g)" in dest
