"""19/10/2026 : un live YouTube, Twitch ou TikTok n'est annoncé qu'une fois, et son annonce
part à la fin. Depuis le 11/08 (détachement de modules), l'état n'était plus jamais écrit :
chaque passage réannonçait le live."""
from __future__ import annotations

import ast
import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    return next(ast.unparse(n) for n in ast.walk(ast.parse(SRC))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def test_L1_chaque_annonce_est_memorisee_et_chaque_absence_comptee():
    for plateforme in ("youtube", "twitch", "tiktok"):
        m = re.search(rf"_live_msg = await _publier_social\(\w+, '{plateforme}_live', e\)\n"
                      rf"\s+await mark_live_announced\(", SRC)
        assert m, f"{plateforme} : l'annonce n'est pas mémorisée"
        assert f"await check_live_ended(" in SRC[m.end():m.end() + 900], plateforme
    assert SRC.count("await check_live_ended(") == 3


def test_L2_une_annonce_par_live_et_retrait_a_la_fin():
    horloge = [datetime(2026, 10, 19, 20, tzinfo=timezone.utc)]
    retires, ecrits = [], []

    class Message:
        async def delete(self):
            retires.append(1)

    class Salon:
        async def fetch_message(self, mid):
            assert mid == 555
            return Message()

    class Serveur:
        def get_channel(self, cid):
            return Salon() if cid == 9 else None

    class Bot:
        def get_guild(self, gid):
            return Serveur()

    class Db:
        async def execute(self, sql, params=()):
            ecrits.append(params[5])

        async def commit(self):
            pass

    @asynccontextmanager
    async def get_db():
        yield Db()

    ns = {"_live_state": {}, "now": lambda: horloge[0], "get_db": get_db, "bot": Bot(),
          "discord": discord, "timezone": timezone, "LIVE_END_THRESHOLD": 36,
          "LIVE_ANNOUNCE_COOLDOWN": 64800, "_logerr": lambda *a, **k: None}
    for nom in ("save_live_state", "mark_live_announced", "check_live_ended",
                "should_announce_live"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    cle = "yt_live_1_UCx"
    run = asyncio.run

    run(ns["check_live_ended"](cle, 1, "youtube", "X"))
    assert ns["_live_state"] == {}, "jamais annoncé : rien à clore"
    assert run(ns["should_announce_live"](cle)) is True
    run(ns["mark_live_announced"](cle, 1, "youtube", "X", message_id=555, live_channel_id=9))
    assert run(ns["should_announce_live"](cle)) is False, "déjà annoncé"
    for _ in range(35):
        run(ns["check_live_ended"](cle, 1, "youtube", "X"))
    assert ns["_live_state"][cle]["is_live"] and not retires, "un clignotement ne clôt pas"
    run(ns["check_live_ended"](cle, 1, "youtube", "X"))
    assert retires == [1] and ns["_live_state"][cle]["is_live"] is False
    assert run(ns["should_announce_live"](cle)) is False, "18 h de délai après une annonce"
    horloge[0] += timedelta(hours=18, seconds=1)
    assert run(ns["should_announce_live"](cle)) is True
    assert ecrits[0] == 1 and ecrits[-1] == 0, "état persistant écrit en base"
