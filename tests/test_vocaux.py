"""24/10/2026, le fondateur : « plusieurs sous-salons automatiques… un vocal communautaire… un vocal concernant
les deux jeux… décider si c'est pour de l'aide, du chill, du farm… » ; et pour le clan : « un vocal join pour le
clan et après un vocal de demande… aide, farm et tout… pour bien cibler les demandes »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
from datetime import datetime, timezone
from pathlib import Path

import discord

import vocaux as V
import zones
from conftest_discord import Obj
from faux_serveur import Monde, Vocal, ids, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    return next(ast.unparse(n) for n in ast.parse(SRC).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def _select(v):
    return next(getattr(x, "item", x) for x in v.walk_children()
                if isinstance(getattr(x, "item", x), discord.ui.Select))


def test_V1_un_contexte_par_join_les_buts_et_les_noms():
    assert set(V.CONTEXTES) >= {"commu", "rell", "clover", "clan", "clan_demande"}, "un Join par jeu de zones.JEUX"
    assert [V.contexte(k).hub for k in ("commu", "rell", "clover", "clan", "clan_demande")] == [
        "🔊 Join · Communauté", "🌊 Join · Rell Seas", "🍀 Join · Clover RPG", "🔊 Join · Clan", "🙋 Demande · Clan"]
    assert V.nom_salon(V.contexte("rell"), V.BUTS["farm"], "Kolax") == "🌊 Farm · Kolax"
    assert V.nom_salon(V.contexte("commu"), V.BUTS["chill"], "Kolax") == "🌴 Chill · Kolax"
    assert V.nom_salon(V.contexte("clan_demande"), V.BUTS["boss"], "Kolax") == "🙋 Boss · Kolax"
    assert V.nom_salon(V.contexte("clover"), None, "Kolax") == "🍀 Clover RPG · Kolax"
    assert {"aide", "farm", "chill"} <= set(V.contexte("rell").buts) and "farm" not in V.contexte("commu").buts
    assert V.contexte("inconnu").cle == "commu"


def test_V2_le_panneau_du_vocal():
    v = V.vue_panneau(77, "rell", 7)
    t = textes(v)
    assert "<@7>" in t and "Rell Seas" in t and ids(v) == ["tv:but:77"]
    assert [o.value for o in _select(v).options] == list(V.contexte("rell").buts)
    t = textes(V.vue_panneau(77, "clan_demande", 7, "farm"))
    assert "que demandes-tu" in t and "🌾 Farm" in t


def test_V3_le_proprietaire_choisit_le_but_le_nom_suit_discord_limite_a_deux():
    V._renommages.clear()
    g = Monde()
    salon = run(g.create_voice_channel("🌊 Rell Seas · Pirate7"))
    g.membre(7)

    async def proprio(s):
        return (7, "rell") if s.id == salon.id else None

    async def staff(_g, m):
        return m.id == 99
    V.setup(proprio=proprio, est_staff=staff, log=lambda *a: None)
    i = interaction(g, g.membre(7))
    run(V.choisir(i, salon.id, "farm"))
    assert salon.name == "🌊 Farm · Pirate7" and "🌾 Farm" in textes(i.suivis[-1][1]["view"])
    i = interaction(g, g.membre(8))
    run(V.choisir(i, salon.id, "chill"))
    assert "Seul <@7>" in textes(i.response.messages[-1][1]["view"]) and salon.name == "🌊 Farm · Pirate7"
    run(V.choisir(interaction(g, g.membre(99)), salon.id, "boss"))
    assert salon.name == "🌊 Boss · Pirate7", "le staff aussi"
    i = interaction(g, g.membre(7))
    run(V.choisir(i, salon.id, "aide"))
    assert "2 changements de nom" in textes(i.response.messages[-1][1]["view"]) and salon.name == "🌊 Boss · Pirate7"
    V._renommages.clear()
    i = interaction(g, g.membre(7))
    run(V.choisir(i, salon.id, "musique"))
    assert "n'existe pas ici" in textes(i.response.messages[-1][1]["view"]), "la musique n'est pas un but de jeu"


def test_V4_un_join_par_jeu_et_une_demande_pour_le_clan_avec_les_droits_du_voisin():
    g = Monde()
    join = g.nom("🔊Join")
    clan_cat = g.categorie("🦜 · GoRp_SEA")
    join_clan = g._salon(Vocal, "Join", {"category": clan_cat})
    for ch in (join, join_clan):
        ch._overwrites = []
    conf = {"temp_voice_config": {"enabled": True, "hubs": {
        str(join.id): {"category": join.category_id, "default_name": "🔊 Vocal de {user}"},
        str(join_clan.id): {"category": clan_cat.id, "required_role": 5, "default_name": "🔊 Vocal de {user}"}}}}
    journal = []

    async def cfg(_gid):
        return conf

    async def db_set(_gid, cle, val):
        conf[cle] = val

    async def au_journal(*a, **_k):
        journal.append(a)
    ns = {"discord": discord, "zones": zones, "vocaux": V, "cfg": cfg, "db_set": db_set, "_au_journal": au_journal,
          "now": lambda: datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)}
    exec(_source("_vocaux_par_contexte"), ns)  # noqa: S102 — code du dépôt
    run(ns["_vocaux_par_contexte"](g))
    rell, clover, demande = g.nom("🌊 Join · Rell Seas"), g.nom("🍀 Join · Clover RPG"), g.nom("🙋 Demande · Clan")
    assert join.name == "🔊 Join · Communauté" and join_clan.name == "🔊 Join · Clan"
    assert rell.category_id == join.category_id and demande.category_id == clan_cat.id
    assert g.ordre.index(rell.id) == g.ordre.index(join.id) + 1 and g.ordre.index(clover.id) == g.ordre.index(rell.id) + 1
    assert g.ordre.index(demande.id) == g.ordre.index(join_clan.id) + 1, "chacun à côté de son voisin"
    hubs = conf["temp_voice_config"]["hubs"]
    assert {k: v["contexte"] for k, v in hubs.items()} == {
        str(join.id): "commu", str(rell.id): "rell", str(clover.id): "clover", str(join_clan.id): "clan",
        str(demande.id): "clan_demande"}
    assert hubs[str(demande.id)]["required_role"] == 5, "la Demande du clan, réservée au clan comme son Join"
    assert hubs[str(rell.id)]["default_name"] == "🌊 Rell Seas · {user}"
    assert conf["vocaux_v2"]["crees"] == ["🌊 Join · Rell Seas", "🍀 Join · Clover RPG", "🙋 Demande · Clan"]
    assert journal
    run(ns["_vocaux_par_contexte"](g))
    assert len([s for s in g.salons.values() if isinstance(s, Vocal)]) == 5, "une fois"
    assert zones._vocal_commu(g, conf, "rell") is rell and zones._vocal_commu(g, conf) is join
    assert zones._vocal_clan(g, conf) is join_clan and zones._vocal_clan(g, conf, "clan_demande") is demande


def test_V5_branche_dans_le_bot():
    assert "await vocaux.poser_panneau(new_channel, str(hub_data.get('contexte') or 'commu')" in SRC
    assert "bot.add_dynamic_items(vocaux.ChoixBut)" in SRC and "vocaux.setup(proprio=_vocal_info" in SRC
    assert '"_vocaux_par_contexte"' in SRC.split("_TRAVAUX = (", 1)[1].split(")", 1)[0]
    assert '"vocaux_hubs"' in SRC


def test_V6_le_proprietaire_et_le_contexte_d_un_vocal_meme_apres_un_redemarrage():
    conf = {"temp_voice_config": {"hubs": {"50": {"contexte": "rell"}}}}
    ligne = [None]

    class Db:
        def execute(self, *_a):
            @contextlib.asynccontextmanager
            async def cur():
                yield Obj(fetchone=lambda: _fini(ligne[0]))
            return cur()

    async def _fini(x):
        return x

    @contextlib.asynccontextmanager
    async def get_db():
        yield Db()

    async def cfg(_gid):
        return conf
    memoire = {}
    ns = {"temp_voice_channels": memoire, "get_db": get_db, "cfg": cfg}
    exec(_source("_vocal_info"), ns)  # noqa: S102 — code du dépôt
    salon = Obj(id=77, guild=Obj(id=1))
    memoire[77] = {"owner": 7, "hub_id": 50}
    assert asyncio.run(ns["_vocal_info"](salon)) == (7, "rell")
    memoire.clear()
    assert asyncio.run(ns["_vocal_info"](salon)) is None, "inconnu"
    ligne[0] = (8, 50)
    assert asyncio.run(ns["_vocal_info"](salon)) == (8, "rell"), "après un redémarrage : la base"
