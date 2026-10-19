"""19/10/2026 : « si c'est moi qui ai à faire, tu m'enlèves ce que j'ai à faire » — le bot
fait lui-même ce qu'il laissait au propriétaire."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign))
                and (getattr(n, "name", "") == nom
                     or any(getattr(t, "id", "") == nom for t in getattr(n, "targets", []))))


def test_A1_un_flux_sans_salon_prend_le_salon_des_autres():
    conf = {"ads_youtube_feeds": [{"id": "UCa", "channel_id": 10}, {"id": "UCmiranza", "channel_id": 0}],
            "ads_twitter_feeds": [{"username": "RellGames", "channel_id": 10}],
            "ads_tiktok_feeds": [{"username": "x", "channel_id": 0}], "ads_tiktok_live_channel": 30}
    ecrits = {}

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v
    g = Obj(id=1, get_channel=lambda cid: Obj(id=cid) if cid in (10, 30) else None)
    ns = {"cfg": cfg, "db_set": db_set}
    exec(_source("_FLUX_RESEAUX"), ns)  # noqa: S102 — code du dépôt
    exec(_source("_rattacher_flux_orphelins"), ns)  # noqa: S102
    assert asyncio.run(ns["_rattacher_flux_orphelins"](g)) == 1
    assert ecrits["ads_youtube_feeds"][1]["channel_id"] == 10
    assert "ads_tiktok_feeds" not in ecrits, "un salon live existe : il publie déjà"


def test_A2_le_salon_des_actualites_devient_un_salon_d_annonces_une_fois():
    for communautaire, attendu in ((True, [discord.ChannelType.news]), (False, [])):
        conf, types = {}, []

        class Salon(discord.TextChannel):
            def __init__(self):
                self.id = 5

            def is_news(self):
                return False

            async def edit(self, **kw):
                types.append(kw["type"])

        async def cfg(_g):
            return conf

        async def db_set(_g, k, v):
            conf[k] = v

        async def config(_g):
            return {"roblox_news_salon": 5}
        salon = Salon()
        g = Obj(id=1, features=["COMMUNITY"] if communautaire else [],
                me=Obj(guild_permissions=Obj(manage_channels=True)),
                get_channel=lambda cid: salon if cid == 5 else None)
        ns = {"cfg": cfg, "db_set": db_set, "discord": discord,
              "roblox_news_module": Obj(config=config), "_logerr": lambda *a, **k: None}
        exec(_source("_actus_en_annonces"), ns)  # noqa: S102 — code du dépôt
        asyncio.run(ns["_actus_en_annonces"](g))
        asyncio.run(ns["_actus_en_annonces"](g))
        assert types == attendu and conf["actus_annonces_v1"] == 1
