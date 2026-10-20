"""20/10/2026 (audit 3 #4) : infractions et tickets « du jour » valaient toujours 0 (borne ISO avec
fuseau comparee en texte a des horodatages SQLite UTC) ; le rapport de minuit capturait la journee
qui commence ; la journee en cours etait comparee a des journees completes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import observability as O
from conftest_discord import Obj, base


def _utc(jour, heure_paris):
    """Un horodatage SQLite (UTC) pour une heure de Paris donnee."""
    d = datetime(jour.year, jour.month, jour.day, heure_paris, tzinfo=O._PARIS_TZ)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def test_O1_les_infractions_et_tickets_de_la_journee_sont_comptes(tmp_path):
    get_db, cfg, db_set, _ = base(tmp_path)
    O.setup(None, get_db, cfg, db_set, {})
    O._tables_initialized = False  # une base neuve par test
    hier = datetime.now(O._PARIS_TZ).date() - timedelta(days=1)

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY, guild_id, user_id, created_at)")
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id, status, created_at)")
            for h in (0, 9, 23):  # minuit pile, matin, 23 h (heure de Paris) : la journee entiere
                await db.execute("INSERT INTO infractions(guild_id, user_id, created_at) VALUES(1, 2, ?)", (_utc(hier, h),))
            await db.execute("INSERT INTO infractions(guild_id, user_id, created_at) VALUES(1, 2, ?)",
                             (_utc(hier + timedelta(days=1), 0),))  # le lendemain : pas compte
            await db.execute("INSERT INTO tickets(guild_id, status, created_at) VALUES(1, 'closed', ?)", (_utc(hier, 10),))
            await db.commit()
        return await O.capture_snapshot(Obj(id=1, member_count=50), hier)
    snap = asyncio.run(scenario())
    assert snap["day"] == hier.strftime("%Y-%m-%d")
    assert (snap["infractions"], snap["tickets_opened"], snap["tickets_closed"], snap["events_finished"]) == (3, 1, 1, 0)


def test_O2_les_anomalies_ne_regardent_que_des_journees_completes(tmp_path):
    get_db, cfg, db_set, _ = base(tmp_path)
    O.setup(None, get_db, cfg, db_set, {})
    O._tables_initialized = False  # une base neuve par test
    aujourd_hui = datetime.now(O._PARIS_TZ).date()

    async def scenario():
        await O._ensure_tables()
        async with get_db() as db:
            for k in range(0, 9):
                jour = (aujourd_hui - timedelta(days=k)).strftime("%Y-%m-%d")
                await db.execute("INSERT INTO daily_stats_snapshot(guild_id, day, member_count, joined, left_count,"
                                 " infractions, tickets_opened, tickets_closed, events_finished)"
                                 " VALUES(1, ?, 100, ?, 5, 5, 5, 0, 0)", (jour, 0 if k == 0 else 10))
            await db.commit()
        return await O.detect_anomalies(1)
    assert asyncio.run(scenario()) == [], "la journee en cours (0 arrivee a l'aube) n'est pas une baisse"
