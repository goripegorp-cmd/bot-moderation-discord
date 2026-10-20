"""20/10/2026 (audit 3 #10) : la duree moyenne de resolution lisait une colonne que rien n'ecrit."""
from __future__ import annotations

import asyncio

import tickets_enhance as T
from conftest_discord import base


def test_S1_la_duree_moyenne_vient_du_journal_des_tickets(tmp_path):
    get_db, cfg, db_set, _ = base(tmp_path)
    T.setup(None, get_db, cfg, db_set, {})
    T._tables_initialized = False  # une base neuve par test

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id, channel_id, user_id, panel_id,"
                             " claimed_by, status, answers, created_at)")
            await db.execute("INSERT INTO tickets(guild_id, channel_id, status, created_at, claimed_by)"
                             " VALUES(1, 10, 'closed', '2026-10-19 08:00:00', 0)")
            await db.execute("INSERT INTO tickets(guild_id, channel_id, status, created_at, claimed_by)"
                             " VALUES(1, 11, 'closed', '2026-10-19 08:00:00', 0)")
            await db.commit()
        await T.log_action(1, 10, 5, "close", "Résolu")
        await T.log_action(1, 11, 5, "close", "Résolu")
        async with get_db() as db:
            await db.execute("UPDATE ticket_audit SET at='2026-10-19 10:00:00' WHERE channel_id=10")
            await db.execute("UPDATE ticket_audit SET at='2026-10-19 12:00:00' WHERE channel_id=11")
            await db.commit()
        return await T.collect_ticket_stats(1)
    assert asyncio.run(scenario())["avg_resolution_hours"] == 3.0
