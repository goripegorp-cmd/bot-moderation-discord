"""24/10/2026, le fondateur : « le truc des créateurs de contenu, les bons plans, tout ce que tu me dis à retirer,
fais-le ». L'aide automatique, les bons plans, le relais entre serveurs et la mise en avant des créateurs sont
partis : plus une ligne de code, plus de tâche, plus de table ; le dernier message de l'aide automatique
(« se repositionne automatiquement »), qui mentirait, est effacé une fois."""
from __future__ import annotations

import ast
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import discord

from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
RETIRES = ("handle_auto_help", "auto_help_messages", "_auto_help_locks", "relay_discord_message",
           "check_game_deals", "create_deal_embed", "cleanup_deals_task", "before_cleanup_deals",
           "cleanup_expired_deals_db", "is_deal_already_posted", "save_posted_deal", "_deals_last_check",
           "CHEAPSHARK_STORES", "GAME_PLATFORMS", "check_creator_spotlight_feeds", "set_creator_links",
           "list_creator_links", "_valid_embed_image_url")


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def test_F1_plus_une_ligne_des_fonctions_retirees():
    noms = {getattr(n, "name", None) for n in ARBRE.body}
    noms |= {getattr(t, "id", None) for n in ARBRE.body if isinstance(n, ast.Assign) for t in n.targets}
    assert not noms & set(RETIRES)
    for reste in ("cleanup_deals_task", "CREATE TABLE IF NOT EXISTS posted_deals",
                  "CREATE TABLE IF NOT EXISTS creator_links", "'creator_role'", "'creator_channel'",
                  "ads_deals", "ads_discord_feeds", "'deals': {'name'", "'auto_help': {'name'",
                  "'discord_relay': {'name'"):
        assert reste not in SRC, reste
    mortes = next(n for n in ARBRE.body if isinstance(n, ast.Assign)
                  and getattr(n.targets[0], "id", "") == "_TABLES_MORTES")
    assert {"posted_deals", "creator_links"} <= set(ast.literal_eval(mortes.value.args[0])), \
        "leurs tables partent au démarrage"
    assert "creator_links" not in (RACINE / "gdpr.py").read_text(encoding="utf-8")
    assert "AUTOHELP" not in (RACINE / "vocabulary.py").read_text(encoding="utf-8")
    assert "_retirer_fonctions_mortes" in SRC.split("_TRAVAUX = (", 1)[1].split(")", 1)[0]


class _Salon(discord.TextChannel):
    def __init__(self, messages):
        self.id, self.messages = 32, messages

    async def history(self, limit=100):
        for m in list(self.messages):
            yield m


def _message(salon, pied=None, webhook=None, auteur=7):
    m = Obj(webhook_id=webhook, author=Obj(id=auteur),
            embeds=[Obj(footer=Obj(text=pied))] if pied is not None else [])

    async def delete():
        salon.messages.remove(m)
    m.delete = delete
    return m


def test_F2_le_dernier_message_de_l_aide_automatique_est_efface_une_fois():
    salon = _Salon([])
    aide = _message(salon, "Ce message se repositionne automatiquement", webhook=55, auteur=55)
    autre_bot = _message(salon, "Autre chose", auteur=999)
    membre = _message(salon)
    salon.messages += [membre, aide, autre_bot]
    conf = {"auto_help_channels": json.dumps({"32": {"title": "Aide"}})}
    ecrits, journal = [], []

    async def cfg(_gid):
        return conf

    async def db_set(_gid, cle, val):
        ecrits.append((cle, val))
        conf[cle] = val

    async def au_journal(*a, **_k):
        journal.append(a)
    ns = {"discord": discord, "json": json, "cfg": cfg, "db_set": db_set, "_au_journal": au_journal,
          "bot": Obj(user=Obj(id=999)), "_logerr": lambda *a, **k: None,
          "now": lambda: datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)}
    exec(_source("_retirer_fonctions_mortes"), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1, get_channel=lambda cid: salon if cid == 32 else None)
    asyncio.run(ns["_retirer_fonctions_mortes"](g))
    assert salon.messages == [membre, autre_bot], "seul le message de l'aide automatique part"
    assert ecrits[-1][0] == "fonctions_mortes_v1" and ecrits[-1][1]["aide_effaces"] == 1
    assert journal and "1 message(s) effacé(s)" in journal[-1][3]
    asyncio.run(ns["_retirer_fonctions_mortes"](g))
    assert len(ecrits) == 1, "une seule fois"
