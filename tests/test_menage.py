"""19/10/2026 : « dès qu'elles sont vieilles d'un mois, tu les enlèves » ; « qu'on évite d'avoir
des salons avec des millions de messages » ; « les rôles que tu as créés qui ne servent à rien,
tu les enlèves »."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
import pytest

import nettoyage as n

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
BOT = 1


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _il_y_a(jours):
    return datetime.now(timezone.utc) - timedelta(days=jours)


class Msg:
    def __init__(self, mid, auteur, jours, webhook=None):
        self.id, self.author, self.created_at = mid, Obj(id=auteur), _il_y_a(jours)
        self.webhook_id, self.supprime = webhook, False

    async def delete(self):
        self.supprime = True


class Fil(discord.Thread):
    def __init__(self, nom, jours):
        self.name, self.supprime = nom, False
        self._cree = _il_y_a(jours)

    @property
    def created_at(self):
        return self._cree

    async def delete(self):
        self.supprime = True


class Salon(discord.TextChannel):
    def __init__(self, sid, messages=(), fils=(), archives=(), droits=True):
        self.id, self.name, self._msgs = sid, "logs", list(messages)
        self._fils, self._archives, self.crees = list(fils), list(archives), []
        self._droits = droits

    @property
    def threads(self):
        return self._fils

    @property
    def guild(self):
        return Obj(me=Obj(id=BOT))

    def permissions_for(self, _m):
        return Obj(create_public_threads=self._droits, send_messages_in_threads=self._droits)

    async def create_thread(self, **kw):
        f = Fil(kw["name"], 0)
        self.crees.append(kw)
        self._fils.append(f)
        return f

    async def archived_threads(self, limit=None):
        for t in self._archives:
            yield t

    async def webhooks(self):
        return [Obj(id=5, user=Obj(id=BOT)), Obj(id=6, user=Obj(id=42))]

    async def history(self, limit=None, before=None, oldest_first=False):
        ms = sorted(self._msgs, key=lambda m: m.created_at, reverse=not oldest_first)
        if before is not None:
            ms = [m for m in ms if m.created_at < before]
        for m in ms[:limit]:
            yield m


@pytest.fixture(autouse=True)
def caches():
    n._fils.clear()
    n._verrous.clear()


def test_M1_un_fil_par_jour_et_par_salon():
    async def scenario():
        s = Salon(10)
        f1 = await n.fil_du_jour(s)
        f2 = await n.fil_du_jour(s)
        assert f1 is f2 and len(s.crees) == 1
        assert s.crees[0]["name"] == n.nom_du_jour() and s.crees[0]["auto_archive_duration"] == 1440
        sans = Salon(11, droits=False)
        assert await n.fil_du_jour(sans) is sans, "sans droits : le salon, rien ne se perd"
    asyncio.run(scenario())


def test_M2_les_fils_de_plus_de_30_jours_partent_d_un_coup():
    vieux, recent, autre = Fil("📋 01/09/2026", 40), Fil("📋 18/10/2026", 1), Fil("Discussion", 90)
    archive = Fil("📋 02/09/2026", 39)
    s = Salon(10, fils=[vieux, recent, autre], archives=[archive])
    assert asyncio.run(n.supprimer_vieux_fils(s)) == 2
    assert (vieux.supprime, archive.supprime, recent.supprime, autre.supprime) == \
        (True, True, False, False), "jamais un fil qui n'est pas un journal"


def test_M3_seuls_les_vieux_messages_du_bot_partent():
    a = Msg(1, BOT, 40)
    b = Msg(2, 99, 40)
    c = Msg(3, 77, 35, webhook=5)
    d = Msg(4, BOT, 3)
    e = Msg(5, 88, 36, webhook=6)  # le webhook d'un autre service (salon suivi, Discohook)
    s = Salon(10, messages=[a, b, c, d, e])

    async def dormir(_s):
        return None
    vrai = n.asyncio.sleep
    n.asyncio.sleep = dormir
    try:
        assert asyncio.run(n.purger_salon(s, BOT)) == 2
    finally:
        n.asyncio.sleep = vrai
    assert (a.supprime, b.supprime, c.supprime, d.supprime, e.supprime) == (True, False, True, False, False)


def test_M4_remise_a_neuf_seulement_d_un_salon_de_logs_pur():
    pur = Salon(10, messages=[Msg(1, BOT, 400), Msg(2, BOT, 1)])
    jeune = Salon(11, messages=[Msg(1, BOT, 5)])
    avec_humain = Salon(12, messages=[Msg(1, BOT, 400), Msg(2, 99, 1)])
    assert asyncio.run(n.a_remettre_a_neuf(pur, BOT)) is True
    assert asyncio.run(n.a_remettre_a_neuf(jeune, BOT)) is False
    assert asyncio.run(n.a_remettre_a_neuf(avec_humain, BOT)) is False


def test_M5_l_identite_d_un_salon_recree_remplacee_partout():
    conf = {"channel_id": 5, "category_channels": {"Tickets": 5, "Vocal": 6},
            "event_channels": {"x": "5"}, "actif": True, "liste": [5, 7]}
    assert n.remplacer_id(conf, 5, 9) == {
        "channel_id": 9, "category_channels": {"Tickets": 9, "Vocal": 6},
        "event_channels": {"x": "9"}, "actif": True, "liste": [9, 7]}


def test_M6_le_journal_ecrit_dans_le_fil_du_jour():
    src = (Path(__file__).resolve().parent.parent / "unified_logger.py").read_text(encoding="utf-8")
    assert "target = await nettoyage.fil_du_jour(target)" in src
    assert 'kw["thread"] = target' in src, "le mode webhook suit le fil"


def _source(nom):
    return next(ast.unparse(x) for x in ast.walk(ast.parse(SRC))
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == nom)


def test_M7_menage_unique_roles_salon_des_accessoires_et_logs():
    supprimes, ecrits, remplaces = [], {}, []

    class Role:
        def __init__(self, nom, rang, gere=False):
            self.name, self.rang, self.managed = nom, rang, gere

        def __lt__(self, autre):
            return self.rang < autre.rang

        async def delete(self, reason=None):
            supprimes.append(self.name)

    class SalonAcc(Salon):
        async def delete(self, reason=None):
            supprimes.append(f"salon {self.id}")

    haut = Role("Bot", 100)
    roles = [Role("🔔 Boss", 5), Role("💎 Passages Limited", 6), Role("👑 Fondateur", 200),
             Role("🔔 Invasions", 7, gere=True), Role("Membre", 3)]
    acc_bot = SalonAcc(20, messages=[Msg(1, BOT, 50)])
    acc_humain = SalonAcc(21, messages=[Msg(1, 99, 50)])
    salons = {20: acc_bot, 21: acc_humain, 22: Salon(22)}
    conf = {"roblox_salon_nouveautes": 20, "roblox_salon_bascules": 21, "roblox_news_salon": 22}
    g = Obj(id=1, roles=roles, me=Obj(guild_permissions=Obj(manage_roles=True), top_role=haut),
            get_channel=lambda i: salons.get(i))

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v

    async def logs(_g, _c):
        return set()

    async def dormir(_s):
        return None

    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "nettoyage": n,
          "asyncio": Obj(sleep=dormir), "_ROLES_OBSOLETES": frozenset({"🔔 Boss", "💎 Passages Limited", "🔔 Invasions"}),
          "_CLES_ACCESSOIRES": ("roblox_salon_nouveautes", "roblox_salon_bascules"),
          "_salons_de_logs": logs, "_remplacer_salon_partout": lambda *a: remplaces.append(a),
          "bot": Obj(user=Obj(id=BOT)), "now": lambda: datetime(2026, 10, 19),
          "_logerr": lambda *a, **k: supprimes.append(("ERREUR", a))}
    exec(_source("_menage_unique"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["_menage_unique"](g))
    assert supprimes == ["🔔 Boss", "💎 Passages Limited", "salon 20"], supprimes
    assert ecrits["roblox_salon_nouveautes"] == 0 and ecrits["roblox_salon_bascules"] == 0
    assert "menage_v1" in ecrits
    supprimes.clear()
    conf["menage_v1"] = "fait"
    asyncio.run(ns["_menage_unique"](g))
    assert supprimes == [], "une seule fois"


def test_M8_branchements():
    assert "await _menage_unique(g)" in _source("_travaux_de_demarrage")
    assert '"menage_salons_task",' in SRC and "menage_salons_task.start()" in SRC
    assert "_backfill_events_role(" not in SRC, "plus aucun rôle d'événement distribué"


def test_M9_la_base_rend_la_place(tmp_path):
    import contextlib
    import sqlite3

    import aiosqlite

    import data_cleanup as dc
    p = tmp_path / "b.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE a(x)")
        c.executemany("INSERT INTO a VALUES (?)", [("y" * 500,)] * 2000)
        c.commit()
        c.execute("DROP TABLE a")
        c.commit()

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(p)
        try:
            yield db
        finally:
            await db.close()

    dc.setup(None, get_db)
    try:
        assert asyncio.run(dc.part_libre()) > 0.2
        avant = p.stat().st_size
        assert asyncio.run(dc.vacuum_db()) is True
        assert p.stat().st_size < avant / 10
    finally:
        dc.setup(None, None)
    src = (Path(__file__).resolve().parent.parent / "data_cleanup.py").read_text(encoding="utf-8")
    assert "if total > 1000 or await part_libre() > 0.20:" in src
    assert 'await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")' in SRC
