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
import questions
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
    "Comment je fais pour venir dans un équipage ?": ("clan", "fr"),  # l'équipage, c'est le clan
    "comment on peut faire du trading ?": ("trade", "fr"),
    "comment faire une suggestion ?": ("suggestion", "fr"),
    "quelqu'un peut m'aider pour le boss ?": ("aide_jeu", "fr"),
    "comment on peut demander de l'aide pour le clan ?": ("aide_clan", "fr"),
    "how do I join your crew?": ("clan", "en"),
    "where is the crew list?": (None, ""),  # plus de liste d'équipages
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


#  27/10/2026 : les réponses du bot (cartes, cadence, rappel) sont testées dans tests/test_reponses_auto.py.


# ─── Ouvrir ou fermer les types de ticket ────────────────────────────────────

def _ns_tickets(conf, direction: set):
    journal, rafraichis = [], []

    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v

    async def _au_journal(*a, **k):
        journal.append((a, k))

    async def _rafraichir_hub_tickets(_g, **k):
        rafraichis.append(k.get("types"))
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
    assert rafraichis == [{"2"}] and "Rell Seas : fermé" in journal[-1][0][3], \
        "le panneau unifié et le panneau de ce type suivent (24/10/2026)"
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
    assert "bot.add_listener(_faq_hook, 'on_message')" in ast.unparse(ARBRE) and "reponses_auto.setup(" in SRC
    dest = _source("_faq_destinations")
    assert "zones_posts" in dest and "_salon_des_tickets(g)" in dest


# ─── 24/10 : le bon salon, selon le jeu et la langue ─────────────────────────

DEST = {"ticket": "https://t/40", "suggestions": "https://t/43", "game_link": "https://t/60", "annonces": "https://t/61",
        "roblox": "https://t/62", "goripe": "https://t/63",
        "jeux": [{"cle": "rell", "nom": "Rell Seas", "emoji": "🌊", "mots": ("rell", "rellseas", "reelsy"), "forum": 70,
                  "trade": "https://t/71", "help": "https://t/72", "annonces": "https://t/73",
                  "lien": "https://www.roblox.com/games/1"},
                 {"cle": "clover", "nom": "Clover RPG", "emoji": "🍀", "mots": ("clover",), "forum": 80,
                  "trade": "https://t/81", "help": "https://t/82", "annonces": "", "lien": ""}]}


def _repond(texte, salon=None, d=DEST):
    s, langue = faq.reconnaitre(texte)
    assert s is not None, texte
    return faq.reponse(s, questions.nettoyer(texte).lower(), salon, d, langue or "fr")


def _liens(r):
    return [u for _b, u in r[2]]


def test_F6_six_langues_le_bon_sujet():
    """« Fais attention, il y a plusieurs types de langues… l'international. »"""
    attendus = {
        "Ils sont où les liens pour rejoindre le jeu ?": ("lien_jeu", "fr"),
        "where are the game links?": ("lien_jeu", "en"),
        "¿Dónde están los enlaces para jugar?": ("lien_jeu", "en"),
        "Onde estão os anúncios do jogo?": ("annonces", "en"),
        "Wo sind die Ankündigungen?": ("annonces", "en"),
        "dove sono i video di goripe?": ("videos", "en"),
        "Elles sont où les annonces de Rell Seas ?": ("annonces", "fr"),
        "où sont les vidéos et les lives de goripe ?": ("videos", "fr"),
        "comment je demande de l'aide ?": ("aide_jeu", "fr"),
        "où sont les salons pour échanger ?": ("trade", "fr"),
        "¿Cómo puedo intercambiar objetos?": ("trade", "en"),
    }
    for q, (cle, langue) in attendus.items():
        s, l = faq.reconnaitre(q)
        assert (getattr(s, "cle", None), l) == (cle, langue), q
    assert faq.reconnaitre("Que c'est beau ce soir les amis")[0] is None, "une exclamation n'est pas une question"


def test_F7_general_tous_les_jeux_un_jeu_nomme_son_salon():
    """« Si c'est général… tous les salons pour échanger ; s'il cible un jeu, le salon du jeu. »"""
    titre, corps, boutons = _repond("où sont les salons pour échanger ?")
    assert _liens((titre, corps, boutons)) == ["https://t/71", "https://t/81"] and "Chaque jeu" in corps
    assert [b for b, _u in boutons] == ["🤝 Rell Seas", "🤝 Clover RPG"]
    r = _repond("comment on trade sur clover ?")
    assert _liens(r) == ["https://t/81"] and "Clover RPG" in r[1], "un jeu nommé : son salon"
    fil = Fil(Monde(), 901, Obj(id=70), "🌊 Chat Rell Seas")
    r = _repond("comment on fait pour échanger ?", fil)
    assert _liens(r) == ["https://t/71"], "écrit dans un post de 🌊rell-seas : Rell Seas"
    r = _repond("how do I trade?")
    assert r[0] == "🤝 Trading" and "Each game" in r[1], "en anglais"


def test_F8_les_annonces_d_un_jeu_de_roblox_du_serveur():
    assert _liens(_repond("Elles sont où les annonces de Rell Seas ?")) == ["https://t/73"], "Sneak Rell Seas"
    r = _repond("où sont les annonces de roblox ?")
    assert _liens(r) == ["https://t/62"] and "Roblox" in r[0], "Sneak News Roblox"
    assert _liens(_repond("où sont les annonces ?")) == ["https://t/61", "https://t/73"], \
        "le serveur, puis chaque jeu qui a son salon (Clover RPG n'en a pas : pas de bouton)"
    assert _repond("où sont les annonces de clover ?") is None, "aucun salon connu : pas de carte"


def test_F9_les_liens_les_videos_l_aide():
    r = _repond("Ils sont où les liens pour rejoindre le jeu ?")
    assert _liens(r) == ["https://t/60", "https://www.roblox.com/games/1"] and "game-link" in r[1], \
        "🎮 Game Link, et le lien direct de chaque jeu qui en a un"
    r = _repond("where is the link to play rell seas?")
    assert _liens(r) == ["https://t/60", "https://www.roblox.com/games/1"] and "Rell Seas's official link" in r[1]
    assert _liens(_repond("where is the link to play clover?")) == ["https://t/60"]
    assert _liens(_repond("où sont les vidéos et les lives de goripe ?")) == ["https://t/63"]
    r = _repond("comment je demande de l'aide ?")
    assert _liens(r) == ["https://t/72", "https://t/82", "https://t/40"] and "Pour le staff" in r[1]
    r = _repond("comment je demande de l'aide sur clover ?")
    assert _liens(r) == ["https://t/82"] and "Clover RPG" in r[1] and "staff" not in r[1]


def test_F10_les_salons_reconnus_par_leur_nom():
    noms = ["📜annonce", "🟢target-roblox", "📀sneak-rellseas", "sneak-news-roblox", "🎥goripe", "🎮game-link",
            "📣▷・annonces-gorp", "💬discussion"]
    salons = [Obj(id=n, name=nom) for n, nom in enumerate(noms, 1)]
    t = faq.salons_du_serveur(salons, [("rell", "rellseas"), ("clover",)])
    assert (t["game_link"].name, t["roblox"].name, t["goripe"].name, t["annonces"].name) == \
        ("🎮game-link", "sneak-news-roblox", "🎥goripe", "📜annonce")
    assert t["jeux"][0].name == "📀sneak-rellseas" and t["jeux"][1] is None


def test_F11_branche_dans_le_bot():
    dest = _source("_faq_destinations")
    for morceau in ("faq.salons_du_serveur(publics", "zones.JEUX", "liens_jeux.liens(c)",
                    "permissions_for(g.default_role).view_channel"):
        assert morceau in dest, morceau
