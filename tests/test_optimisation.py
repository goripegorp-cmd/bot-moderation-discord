"""19/10/2026 : « l'optimisation, il y a pas mal de choses à revoir ». Le chemin de chaque
message ne relit plus la base pour rien."""
from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path

import discord

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


class Db:
    def __init__(self, lignes):
        self.lignes, self.requetes = lignes, []

    def execute(self, sql, params=()):
        self.requetes.append(sql)
        lignes = self.lignes(sql) if callable(self.lignes) else self.lignes

        class Curseur:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def fetchone(self):
                return lignes[0] if lignes else None

            async def fetchall(self):
                return lignes

            def __aiter__(self):
                return self._it()

            async def _it(self):
                for x in lignes:
                    yield x
        return Curseur()

    async def commit(self):
        pass


def _get_db(db):
    @contextlib.asynccontextmanager
    async def get_db():
        yield db
    return get_db


def test_O1_le_relais_lit_la_configuration_en_cache():
    envois, lus = [], []
    salon_dest = Obj(id=900)
    a = Obj(id=1, name="A", icon=None)
    b = Obj(id=2, name="B", icon=None, get_channel=lambda i: salon_dest if i == 900 else None)

    async def cfg(gid):
        lus.append(gid)
        return {"ads_discord_feeds": [{"channel_id": "10"}], "ads_discord_channel": 900} if gid == 2 else {}

    async def webhook_send(ch, profil, embed=None):
        envois.append((ch.id, profil, embed.fields[2].value))

    ns = {"bot": Obj(guilds=[a]), "cfg": cfg, "webhook_send": webhook_send, "discord": discord,
          "_escape_md": lambda t, n: str(t)[:n], "_logerr": lambda *x, **k: envois.append(("ERREUR", x))}
    exec(_source("relay_discord_message"), ns)  # noqa: S102 — code du dépôt
    auteur = Obj(display_name="Zed", display_avatar=None)
    msg = Obj(guild=a, channel=Obj(id=10, name="annonces"), author=auteur, content="Salut",
              attachments=[], created_at=None)
    asyncio.run(ns["relay_discord_message"](msg))
    assert lus == [] and envois == [], "un seul serveur : rien à relayer, rien à lire"
    ns["bot"] = Obj(guilds=[a, b])
    asyncio.run(ns["relay_discord_message"](msg))
    assert lus == [2] and envois == [(900, "discord_relay", "Salut")]
    msg.channel = Obj(id=11, name="autre")
    asyncio.run(ns["relay_discord_message"](msg))
    assert len(envois) == 1, "salon non suivi : rien"
    assert "SELECT guild_id, data FROM guild_config" not in _source("relay_discord_message")


def test_O2_salon_de_ticket_une_lecture_par_salon_et_par_2_minutes():
    horloge = [100.0]
    db = Db([(1,)])
    ns = {"get_db": _get_db(db), "time": Obj(monotonic=lambda: horloge[0]),
          "_evict_if_big": lambda d, n: None, "_logerr": lambda *a, **k: None}
    exec("_SALONS_TICKET = {}", ns)  # noqa: S102
    exec(_source("is_ticket_channel"), ns)  # noqa: S102 — code du dépôt
    f = ns["is_ticket_channel"]
    fil = Obj(id=5, name="Ticket de Zed")
    assert asyncio.run(f(fil)) is True and asyncio.run(f(fil)) is True
    assert len(db.requetes) == 1
    assert asyncio.run(f(Obj(id=6, name="ticket-0042"))) is True and len(db.requetes) == 1
    horloge[0] += 121
    asyncio.run(f(fil))
    assert len(db.requetes) == 2


def test_O3_boucles_a_la_minute_muettes_quand_plus_rien_ne_peut_arriver():
    assert "check_scheduled_messages" not in SRC, "messages programmés retirés le 19/10"
    for boucle, drapeau, table in (("check_expired_roles", "_ACHATS_VIDES", "shop_purchases"),):
        db = Db(lambda sql: [(0,)] if "COUNT(*)" in sql else [])
        ns = {"get_db": _get_db(db), "tasks": Obj(loop=lambda **k: (lambda f: f)),
              "now": lambda: __import__("datetime").datetime(2026, 10, 19, 12),
              "timedelta": __import__("datetime").timedelta, drapeau: False}
        exec(_source(boucle), ns)  # noqa: S102 — code du dépôt
        asyncio.run(ns[boucle]())
        assert ns[drapeau] is True and any(table in r for r in db.requetes), boucle
        n = len(db.requetes)
        asyncio.run(ns[boucle]())
        assert len(db.requetes) == n, f"{boucle} relit la base pour rien"
