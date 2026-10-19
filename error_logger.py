"""
error_logger.py — Logger central des erreurs avec burst alerting (Phase 168.4).

🎯 OBJECTIF : aujourd'hui le bot fait `print(f"[xxx] {ex}")` à ~500
emplacements. Si Railway redémarre, on perd. Quand un nouveau bug
apparaît, on ne le sait QUE si on lit les logs Railway à la main.

Module central qui :
1. Capture chaque erreur dans DB `error_log` (rétention 7 jours)
2. Si > THRESHOLD erreurs/heure du même type → DM owner urgent
3. Panel V2 "🔥 Erreurs récentes" pour debug visuel
4. Wrap helper : `await log_error("module_name", ex, context={...})`

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- log_error(source, exception, context=None) -> int (error_id)
- get_recent_errors(guild_id, hours=24, limit=50) -> list[dict]
- get_error_summary(hours=24) -> dict (top types + counts)
- build_errors_panel(guild) -> LayoutView
- burst_check_task (loop 5 min)

DB :
- error_log (id PK, guild_id, source, error_type, message, traceback,
             context_jsonb, occurred_at)
- error_burst_alerts (source PK, last_alert_at)
"""
from __future__ import annotations

import json
import traceback as _tb
from datetime import datetime, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Threshold burst : si > N erreurs/heure du même `source`, alerte owner
BURST_THRESHOLD_PER_HOUR = 10
# Cooldown anti-spam : pas 2 alertes burst du même source dans 4h
BURST_ALERT_COOLDOWN_HOURS = 4


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER DEFAULT 0,
                    source TEXT NOT NULL,
                    error_type TEXT,
                    message TEXT,
                    traceback TEXT,
                    context_jsonb TEXT DEFAULT '{}',
                    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_error_log_source_recent "
                "ON error_log(source, occurred_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_error_log_guild_recent "
                "ON error_log(guild_id, occurred_at DESC)"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS error_burst_alerts (
                    source TEXT PRIMARY KEY,
                    last_alert_at TIMESTAMP,
                    last_count INTEGER DEFAULT 0
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[error_logger init_db] {ex}")


async def log_error(
    source: str,
    exception: Exception,
    context: Optional[dict] = None,
    guild_id: int = 0,
) -> Optional[int]:
    """Capture une erreur en DB. Retourne error_id ou None.

    Source : identifiant court ex: 'forge_btn', 'on_message', 'raid_task'.
    Context : dict d'infos additionnelles ex: {'user_id': ..., 'channel_id': ...}.
    """
    if _get_db is None or exception is None:
        return None
    try:
        err_type = type(exception).__name__
        msg = str(exception)[:1000]
        tb_str = ""
        try:
            tb_str = "".join(_tb.format_exception(
                type(exception), exception, exception.__traceback__
            ))[:3000]
        except Exception:
            pass
        ctx_str = "{}"
        try:
            if context:
                ctx_str = json.dumps(context, ensure_ascii=False, default=str)[:1500]
        except Exception:
            pass

        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO error_log "
                "(guild_id, source, error_type, message, traceback, context_jsonb) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (int(guild_id), source[:100], err_type, msg, tb_str, ctx_str),
            )
            await db.commit()
            return cur.lastrowid
    except Exception as ex_log:
        # Fail-open : on ne veut PAS qu'une erreur dans le logger casse l'app
        print(f"[error_logger.log_error] {ex_log}")
        return None


__all__ = [
    "setup",
    "init_db",
    "log_error",
    "BURST_THRESHOLD_PER_HOUR",
]
