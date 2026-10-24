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


def test_O4_publication_rapide_des_reseaux_et_des_actualites():
    """19/10/2026 : « dès qu'ils sortent un truc, on est directement au courant »."""
    import roblox_news
    assert "@tasks.loop(minutes=1)\nasync def check_social_feeds():" in SRC
    assert "@tasks.loop(minutes=5)\nasync def veille_roblox_task():" in SRC
    assert 'os.getenv("SOCIAL_POLL_SECONDS", "60")' in SRC
    assert all(s["minutes"] <= 10 for s in roblox_news.SOURCES
               if s["cle"] in ("ressources", "newsroom", "newsroom_fr"))
    horloge = [0.0]
    ns = {"time": Obj(monotonic=lambda: horloge[0])}
    exec("_PAGES_LIVE = {}", ns)  # noqa: S102
    exec(_source("_page_live_due"), ns)  # noqa: S102 — code du dépôt
    f = ns["_page_live_due"]
    assert f("yt_1") is True and f("yt_1") is False and f("tk_1") is True
    horloge[0] += 181
    assert f("yt_1") is True, "une page live lourde : au plus une lecture par 3 minutes"
