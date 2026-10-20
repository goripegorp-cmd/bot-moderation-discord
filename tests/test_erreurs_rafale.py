"""20/10/2026 (audit 3 #9) : une rafale d'erreurs prenait une connexion du pool par erreur."""
from __future__ import annotations

import asyncio

import error_logger as E
from conftest_discord import base


def test_E1_une_meme_erreur_s_ecrit_une_fois_par_minute(tmp_path, monkeypatch):
    get_db, *_ = base(tmp_path)
    E.setup(None, get_db, None, {})
    E._ECRITES.clear()
    E._TUES.clear()
    horloge = [100.0]
    monkeypatch.setattr(E.time, "monotonic", lambda: horloge[0])

    async def scenario():
        await E.init_db()
        ids = [await E.log_error("feeds", TimeoutError("lent"), guild_id=1) for _ in range(50)]
        autre = await E.log_error("feeds", ValueError("autre"), guild_id=1)
        horloge[0] += 61
        suivante = await E.log_error("feeds", TimeoutError("lent"), guild_id=1)
        async with get_db() as db:
            async with db.execute("SELECT context_jsonb FROM error_log WHERE id=?", (suivante,)) as cur:
                ctx = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM error_log") as cur:
                total = (await cur.fetchone())[0]
        return ids, autre, ctx, total
    ids, autre, ctx, total = asyncio.run(scenario())
    assert ids[0] and not any(ids[1:]) and autre
    assert '"repetitions_non_ecrites": 49' in ctx and total == 3
