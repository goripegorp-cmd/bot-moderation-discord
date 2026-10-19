"""19/10/2026 : « que ça s'auto-nettoie automatiquement et que ça puisse durer dans le temps » ;
« absent pendant un certain temps, c'est minimum un mois l'inactivité. Pas 12 jours »."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

import aiosqlite

import activite
import activite_calendrier as cal
import data_cleanup
import rellseas_panneau as R
from conftest_discord import Obj


def _il_y_a(j, fmt="%Y-%m-%d %H:%M:%S"):
    return (datetime.now(timezone.utc) - timedelta(days=j)).strftime(fmt)


def test_D1_un_membre_inactif_depuis_quatre_mois_reste_inactif_pas_jamais_vu(tmp_path, monkeypatch):
    base = tmp_path / "a.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()
    conf = {"activite_observe_depuis": cal.jour(cal.maintenant() - timedelta(days=200)), "activite_fenetre": 7}

    async def cfg(_g):
        return conf
    monkeypatch.setattr(activite, "_get_db", get_db)
    monkeypatch.setattr(activite, "_cfg", cfg)
    membre = Obj(id=7, joined_at=cal.maintenant() - timedelta(days=300))
    recent = Obj(id=8, joined_at=cal.maintenant() - timedelta(days=300))

    async def scenario():
        await activite.init_db()
        async with get_db() as db:
            await db.execute("INSERT INTO activite_jours VALUES (1, 99, ?, 'm')", (cal.jour(),))
            await db.execute("INSERT INTO activite_etat(guild_id, user_id, dernier_actif) VALUES (1, 7, ?)",
                             (cal.jour(cal.maintenant() - timedelta(days=120)),))
            await db.execute("INSERT INTO activite_jours VALUES (1, 8, ?, 'm')",
                             (cal.jour(cal.maintenant() - timedelta(days=12)),))
            await db.commit()
        return (await activite.presences(1, [membre, recent], conf),
                await activite.presence(1, membre, conf))
    groupe, seul = asyncio.run(scenario())
    assert groupe[7]["dernier"] and seul["dernier"] == groupe[7]["dernier"]
    assert R.STATUTS[R.statut_activite(groupe[7])][0] == "Inactif"
    assert R.STATUTS[R.statut_activite(groupe[8])][0] == "Peu présent", "12 jours : pas inactif"


def test_D2_purges_ciblees_jamais_un_ticket_ouvert(tmp_path, monkeypatch):
    base = tmp_path / "c.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()
    monkeypatch.setattr(data_cleanup, "_get_db", get_db)
    vieux, recent = _il_y_a(400), _il_y_a(10)

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, status TEXT, created_at DATETIME)")
            await db.execute("CREATE TABLE ticket_log_events(id INTEGER PRIMARY KEY, ticket_id INTEGER, created_unix INTEGER)")
            await db.execute("CREATE TABLE ticket_audit(id INTEGER PRIMARY KEY, at DATETIME)")
            await db.execute("CREATE TABLE ticket_log_msgs(guild_id INTEGER, ticket_id INTEGER, message_id INTEGER)")
            await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY, type TEXT, created_at DATETIME)")
            await db.executemany("INSERT INTO tickets VALUES (?,?,?)",
                                 [(1, "closed", vieux), (2, "open", vieux), (3, "closed", recent)])
            await db.executemany("INSERT INTO ticket_log_events(ticket_id, created_unix) VALUES (?,?)", [
                (1, int((datetime.now(timezone.utc) - timedelta(days=400)).timestamp())),
                (3, int(datetime.now(timezone.utc).timestamp()))])
            await db.executemany("INSERT INTO ticket_audit(at) VALUES (?)", [(vieux,), (recent,)])
            await db.executemany("INSERT INTO ticket_log_msgs VALUES (1, ?, 5)", [(1,), (2,), (3,)])
            await db.executemany("INSERT INTO infractions(type, created_at) VALUES (?,?)", [
                ("insulte", vieux), ("warn", vieux), ("ban", _il_y_a(800)), ("insulte", recent)])
            await db.commit()
        res = await data_cleanup._purges_ciblees()
        async with get_db() as db:
            lire = lambda sql: db.execute(sql)
            async with await lire("SELECT id FROM tickets ORDER BY id") as cur:
                tickets = [r[0] for r in await cur.fetchall()]
            async with await lire("SELECT ticket_id FROM ticket_log_events") as cur:
                evts = [r[0] for r in await cur.fetchall()]
            async with await lire("SELECT COUNT(*) FROM ticket_audit") as cur:
                audit = (await cur.fetchone())[0]
            async with await lire("SELECT ticket_id FROM ticket_log_msgs ORDER BY ticket_id") as cur:
                msgs = [r[0] for r in await cur.fetchall()]
            async with await lire("SELECT type FROM infractions ORDER BY id") as cur:
                casier = [r[0] for r in await cur.fetchall()]
        return res, tickets, evts, audit, msgs, casier
    res, tickets, evts, audit, msgs, casier = asyncio.run(scenario())
    assert tickets == [2, 3], "le ticket ouvert reste, même ancien"
    assert evts == [3] and audit == 1 and msgs == [2, 3]
    assert casier == ["warn", "insulte"], "sanction du staff gardée deux ans, détection un an"
    assert res["tickets fermés"] == 1
