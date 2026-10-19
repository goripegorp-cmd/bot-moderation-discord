"""19/10/2026 : « si c'est moi qui ai à faire, tu m'enlèves ce que j'ai à faire » — le bot
fait lui-même ce qu'il laissait au propriétaire."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord

import config_salons

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


def test_A1_seul_un_flux_du_studio_rell_sans_salon_est_rattache():
    """19/10/2026 : la rattache aveugle avait mis @miranzaugc dans les sneaks Rell Seas."""
    conf = {"ads_youtube_feeds": [{"id": "UCa", "name": "Rell Seas", "channel_id": 10},
                                  {"id": "UCmiranza", "name": "@miranzaugc", "channel_id": 0},
                                  {"id": "UCb", "name": "@RellGames", "channel_id": 0}],
            "ads_twitter_feeds": [{"username": "RellGames", "channel_id": 10}],
            "ads_tiktok_feeds": [{"username": "rellseas", "channel_id": 0}], "ads_tiktok_live_channel": 30}
    ecrits = {}

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v
    g = Obj(id=1, get_channel=lambda cid: Obj(id=cid) if cid in (10, 30) else None)
    ns = {"cfg": cfg, "db_set": db_set, "config_salons": config_salons}
    for nom in ("_FLUX_RESEAUX", "_flux_du_studio", "_rattacher_flux_orphelins"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    assert asyncio.run(ns["_rattacher_flux_orphelins"](g)) == 1
    yt = ecrits["ads_youtube_feeds"]
    assert yt[1]["channel_id"] == 0, "un flux hors studio n'est jamais rattaché"
    assert yt[2]["channel_id"] == 10
    assert "ads_tiktok_feeds" not in ecrits, "un salon live existe : il publie déjà"


def test_A3_les_sneaks_ne_gardent_que_le_studio_rell_et_effacent_le_reste():
    """« Enlève dans la chaîne YouTube tous les autres, tout ce qui ne correspond pas au studio
    de Rell » — et les publications faites à tort disparaissent, une seule fois."""
    from datetime import datetime, timezone
    conf = {"ads_youtube_feeds": [{"id": "UCa", "name": "Rell Seas", "channel_id": 10},
                                  {"id": "UCmiranza", "name": "@miranzaugc", "channel_id": 10},
                                  {"id": "UCsansnom", "channel_id": 10},
                                  {"id": "UCsneak", "name": "Sneaks", "channel_id": 10}],
            "ads_twitter_feeds": [{"username": "RellGames", "channel_id": 10},
                                  {"username": "quelquun", "channel_id": 10},
                                  {"username": "partenaire", "channel_id": 99}]}
    ecrits, effaces, marques = {}, [], []

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v
        conf[k] = v

    def snow(h, mn):
        ms = int(datetime(2026, 10, 19, h, mn, tzinfo=timezone.utc).timestamp() * 1000)
        return (ms - 1420070400000) << 22
    posts = {("youtube", "ucmiranza"): [Obj(discord_message_id=snow(13, 34), discord_channel_id=10, post_id="v1"),
                                        Obj(discord_message_id=snow(9, 0), discord_channel_id=10, post_id="v0")]}

    async def annonces(_g, p, username=None):
        return posts.get((p, (username or "").lower()), [])

    async def marquer(_g, p, cle, pid):
        marques.append((p, cle, pid))

    class Partiel:
        def __init__(self, mid):
            self.mid = mid

        async def delete(self):
            effaces.append(self.mid)
    salon = Obj(id=10, get_partial_message=Partiel)
    titres = {"UCsansnom": None, "UCsneak": "Rell Seas Sneaks", "UCmiranza": "MiranzaUGC"}

    async def titre(uc):
        return titres.get(uc)

    async def journal_logs(_gid):
        return 0
    g = Obj(id=1, get_channel=lambda cid: salon if cid == 10 else None)
    ns = {"cfg": cfg, "db_set": db_set, "config_salons": config_salons, "discord": discord,
          "datetime": datetime, "timezone": timezone, "now": lambda: datetime(2026, 10, 19, 14, 0),
          "tracking2026": Obj(list_announcements=annonces, mark_deleted=marquer),
          "ulogger2026": Obj(get_log_channel=journal_logs), "_logerr": lambda *a, **k: None}
    for nom in ("_FLUX_RESEAUX", "_flux_du_studio", "_cle_de_suivi", "_RATTACHE_FAUTIVE", "_flux_studio_rell"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    ns["_titre_youtube"] = titre
    retires = asyncio.run(ns["_flux_studio_rell"](g))
    assert [f.get("name") or f.get("username") for _p, f in retires] == ["@miranzaugc", "quelquun"]
    assert [f["id"] for f in conf["ads_youtube_feeds"]] == ["UCa", "UCsansnom", "UCsneak"]
    assert all("titre" not in f for f in conf["ads_youtube_feeds"])
    assert [f["username"] for f in conf["ads_twitter_feeds"]] == ["RellGames", "partenaire"]
    assert effaces == [snow(13, 34)], "seule la publication postérieure à la rattache fautive"
    assert marques == [("youtube", "UCmiranza", "v1")]
    assert asyncio.run(ns["_flux_studio_rell"](g)) == [], "une seule fois"


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
