"""24/10/2026, le fondateur : « rajoute un nouveau salon avec un emoji de manette qui s'appelle Game Link…
quelqu'un qui dit « Ils sont où les liens pour rejoindre le jeu ? » — le salon Game Link, il est là »."""
from __future__ import annotations

import ast
from pathlib import Path

import discord
import pytest

import liens_jeux as L
import zones as ZN
from conftest_discord import Obj, base
from faux_serveur import Monde, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    _get_db, cfg, db_set, conf = base(tmp_path)
    journal = []

    async def autorise(_g, m):
        return m.id == 1

    async def noter(_g, type_, texte, **_kw):
        journal.append((type_, texte))
    L.setup(cfg=cfg, db_set=db_set, autorise=autorise, journal=noter, jeux=ZN.JEUX, log=lambda *a: None)
    return Obj(conf=conf, journal=journal)


def test_L1_le_salon_dans_information_en_lecture_seule(env):
    g = Monde()
    info = g.categorie("· Information")
    ch = run(L.salon(g, creer=True))
    assert ch.name == "🎮game-link" and ch.category_id == info.id, "avec les annonces et les nouveautés"
    assert ch.kw["overwrites"][g.default_role].send_messages is False
    assert run(L.salon(g, creer=True)) is ch, "une fois"
    assert run(L.assurer_carte(g)) and not run(L.assurer_carte(g)), "posée, puis rien à refaire"
    t = textes(ch.envois[-1][2]["view"])
    assert "### 🌊 Rell Seas" in t and "### 🍀 Clover RPG" in t and t.count("Le lien arrive bientôt") == 2, \
        "sans lien : « bientôt », jamais un bouton qui ment"


def test_L2_la_direction_regle_les_liens_la_carte_suit(env):
    g = Monde()
    g.categorie("· Information")
    ch = run(L.salon(g, creer=True))
    run(L.assurer_carte(g))
    i = interaction(g, g.membre(9))
    run(L.BoutonLiens().callback(i))
    assert i.response.messages[-1][0] == "Réservé au fondateur et à la direction."
    i = interaction(g, g.membre(1))
    run(L.BoutonLiens().callback(i))
    form = i.response.modals[-1]
    form.champs["rell"]._value = "https://www.roblox.com/games/123/Rell-Seas"
    form.champs["clover"]._value = "pas un lien"
    j = interaction(g, g.membre(1))
    run(form.on_submit(j))
    assert env.conf["jeux_liens"] == {"rell": "https://www.roblox.com/games/123/Rell-Seas"}
    retour = textes(j.suivis[-1][1]["view"])   # 24/10/2026 (revue) : acquitté d'abord, la réponse suit
    assert "Ignoré" in retour and "Clover RPG" in retour, "une adresse fausse le dit"
    vue = ch.cartes[-1][1]["view"]
    assert [b.url for b in vue.walk_children() if isinstance(b, discord.ui.Button)] == \
        ["https://www.roblox.com/games/123/Rell-Seas"] and "Le lien arrive bientôt" in textes(vue)
    assert "Rell Seas" in env.journal[-1][1]
    env.conf["jeux_liens"] = {"rell": "https://www.roblox.com/games/123/Rell-Seas",
                              "clover": "https://www.roblox.com/games/9/Clover"}
    k = interaction(g, g.membre(1))
    run(form.on_submit(k))
    assert env.conf["jeux_liens"]["clover"] == "https://www.roblox.com/games/9/Clover",         "une adresse mal saisie garde le lien d'avant"
    assert "le lien d'avant reste" in textes(k.suivis[-1][1]["view"])


def test_L3_branche_dans_le_bot():
    boucle = next(ast.unparse(n) for n in ast.parse(SRC).body if getattr(n, "name", "") == "entraide_task")
    assert boucle.index("db_set(g.id, 'game_link_v1'") < boucle.index("liens_jeux.salon(g, creer=True)"), "une fois"
    assert "liens_jeux.setup(cfg=cfg" in SRC and "bot.add_dynamic_items(liens_jeux.BoutonLiens)" in SRC
    assert "liens_jeux.BoutonLiens()]" in SRC and "await liens_jeux.assurer_carte(g)" in SRC
    assert '"game_link": sum(' in SRC and '"jeux_liens": max(' in SRC
    assert (RACINE / "visuels" / "game_link.gif").is_file()
