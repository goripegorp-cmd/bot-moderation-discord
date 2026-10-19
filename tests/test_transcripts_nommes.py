"""19/10/2026 : « qu'on ait vraiment le nom de la personne qui a créé le ticket pour le
transcript […] qu'on sache quel transcript appartient à qui, que si on a besoin de filtrer,
on sache exactement »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import discord

import rellseas_panneau
import visuels

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    return next(ast.unparse(n) for n in ast.walk(ast.parse(SRC))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == nom)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_T1_le_transcript_porte_le_nom_et_se_retrouve_par_membre(tmp_path):
    base = tmp_path / "t.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE ticket_log_events (id INTEGER PRIMARY KEY, guild_id, "
                             "ticket_id, kind, actor_id, detail, created_unix)")
            await db.execute("CREATE TABLE ticket_log_msgs (guild_id, ticket_id, message_id, "
                             "PRIMARY KEY (guild_id, ticket_id))")
            await db.execute("CREATE TABLE ticket_transcripts (guild_id, ticket_id, user_id, "
                             "user_name, panel, url, closed_at, PRIMARY KEY (guild_id, ticket_id))")
            await db.commit()
    asyncio.run(preparer())

    envois = []

    class Salon:
        async def send(self, content=None, **kw):
            envois.append((content, kw))
            return Obj(id=900 + len(envois))

        async def fetch_message(self, _i):
            raise discord.NotFound(Obj(status=404, reason="x"), "x")

    lch = Salon()
    membre = Obj(id=7, display_name="Kolax", name="kolax_")
    g = Obj(id=1, get_channel=lambda i: lch if i == 55 else None,
            get_member=lambda i: membre if i == 7 else None)

    async def cfg(_g):
        return {"ticket_log": 55, "ticket_panels": {"p1": {"name": "Support"}}}

    async def rendu(*_a, **_k):
        return "<html>conversation</html>"

    ns = {"cfg": cfg, "get_db": get_db, "now": lambda: datetime(2026, 10, 19, tzinfo=timezone.utc),
          "discord": discord, "io": io, "re": re, "asyncio": asyncio, "rellseas_ui": rellseas_panneau, "visuels": visuels,
          "_ticket_event_parts": lambda *a: (7, ""), "_ticket_timeline_line": lambda *a: "ligne",
          "C": Obj(GREEN=1, BLUE=2, RED=3, BLURPLE=4), "_recent_transcript_urls": {},
          "_render_ticket_transcript_html": rendu, "_ticket_transcript_file": rendu,
          "transcript_store": Obj(public_base_url=lambda: "https://bot.exemple",
                                  new_token=lambda: "tok", save_html=lambda t, h: True,
                                  transcript_url=lambda t: f"https://bot.exemple/t/{t}"),
          "_logerr": lambda *a, **k: envois.append(("ERREUR", a))}
    exec(_source("send_ticket_log"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["send_ticket_log"](g, "close", membre, {"id": 5, "panel_id": "p1"},
                                      closer=Obj(id=2), ch=Obj(id=77)))
    transcripts = [c for c, _kw in envois if c and str(c).startswith("📄")]
    assert transcripts == ["📄 Transcript #5 · Kolax (7) · Support"], envois

    async def lire():
        async with get_db() as db:
            async with db.execute("SELECT ticket_id, user_id, user_name, panel, url "
                                  "FROM ticket_transcripts") as cur:
                return await cur.fetchall()
    assert asyncio.run(lire()) == [(5, 7, "Kolax", "Support", "https://bot.exemple/t/tok")]

    reponses = []

    async def suivre(texte, **kw):
        reponses.append(texte)

    async def defer(**kw):
        return None

    async def _oui(_i):
        return True

    sans_effet = Obj(command=lambda **k: (lambda f: f), describe=lambda **k: (lambda f: f))
    ns2 = {"get_db": get_db, "discord": discord, "datetime": datetime,
           "_tix_direction": _oui, "ticket_group": sans_effet,
           "app_commands": sans_effet}
    exec(_source("ticket_transcripts_cmd"), ns2)  # noqa: S102 — code du dépôt
    inter = Obj(user=Obj(), guild=Obj(id=1), response=Obj(defer=defer, send_message=suivre),
                followup=Obj(send=suivre))
    asyncio.run(ns2["ticket_transcripts_cmd"](inter, Obj(id=7, mention="@Kolax")))
    assert "🎫 #5 · **Kolax** (`7`) · Support" in reponses[0]
    assert "[ouvrir](https://bot.exemple/t/tok)" in reponses[0]
    reponses.clear()
    asyncio.run(ns2["ticket_transcripts_cmd"](inter, Obj(id=8, mention="@Autre")))
    assert reponses == ["📄 Aucun transcript pour @Autre."]
