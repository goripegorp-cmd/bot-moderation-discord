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
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Threshold burst : si > N erreurs/heure du même `source`, alerte owner
BURST_THRESHOLD_PER_HOUR = 10
# Cooldown anti-spam : pas 2 alertes burst du même source dans 4h
BURST_ALERT_COOLDOWN_HOURS = 4
# Rétention DB
RETENTION_DAYS = 7


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


async def get_recent_errors(
    guild_id: int = 0, hours: int = 24, limit: int = 50,
) -> list[dict]:
    """Renvoie les N erreurs les plus récentes (toutes guilds si guild_id=0)."""
    out: list[dict] = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            if guild_id:
                async with db.execute(
                    "SELECT id, source, error_type, message, occurred_at "
                    "FROM error_log "
                    "WHERE guild_id=? AND "
                    f"datetime(occurred_at) > datetime('now', '-{int(hours)} hours') "
                    "ORDER BY occurred_at DESC LIMIT ?",
                    (guild_id, limit),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT id, source, error_type, message, occurred_at "
                    "FROM error_log "
                    f"WHERE datetime(occurred_at) > datetime('now', '-{int(hours)} hours') "
                    "ORDER BY occurred_at DESC LIMIT ?",
                    (limit,),
                ) as cur:
                    rows = await cur.fetchall()
        for r in rows:
            out.append({
                "id": int(r[0]),
                "source": r[1],
                "error_type": r[2],
                "message": r[3],
                "occurred_at": r[4],
            })
    except Exception:
        pass
    return out


async def get_error_summary(hours: int = 24) -> dict:
    """Top sources d'erreurs sur les N dernières heures."""
    out = {"total": 0, "by_source": [], "by_type": []}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT source, COUNT(*) AS c FROM error_log "
                f"WHERE datetime(occurred_at) > datetime('now', '-{int(hours)} hours') "
                "GROUP BY source ORDER BY c DESC LIMIT 10"
            ) as cur:
                src_rows = await cur.fetchall()
            async with db.execute(
                "SELECT error_type, COUNT(*) AS c FROM error_log "
                f"WHERE datetime(occurred_at) > datetime('now', '-{int(hours)} hours') "
                "GROUP BY error_type ORDER BY c DESC LIMIT 10"
            ) as cur:
                typ_rows = await cur.fetchall()
            async with db.execute(
                "SELECT COUNT(*) FROM error_log "
                f"WHERE datetime(occurred_at) > datetime('now', '-{int(hours)} hours')"
            ) as cur:
                row = await cur.fetchone()
        out["total"] = int(row[0] or 0) if row else 0
        out["by_source"] = [
            {"source": r[0], "count": int(r[1])} for r in src_rows
        ]
        out["by_type"] = [
            {"error_type": r[0], "count": int(r[1])} for r in typ_rows
        ]
    except Exception:
        pass
    return out


# ─── Burst check ───────────────────────────────────────────────────────────

@tasks.loop(minutes=5)
async def burst_check_task():
    """Toutes les 5 min : check si un `source` a dépassé le threshold
    burst. Si oui, DM owner via dm_digest.send_urgent_now (avec cooldown
    anti-spam de 4h)."""
    if _bot is None or _get_db is None:
        return
    try:
        # Trouve les sources avec > THRESHOLD erreurs dans la dernière heure
        async with _get_db() as db:
            async with db.execute(
                "SELECT source, COUNT(*) AS c FROM error_log "
                "WHERE datetime(occurred_at) > datetime('now', '-1 hour') "
                "GROUP BY source HAVING c > ? ORDER BY c DESC",
                (BURST_THRESHOLD_PER_HOUR,),
            ) as cur:
                bursts = await cur.fetchall()
        if not bursts:
            return

        now = datetime.now(timezone.utc)
        for source, count in bursts:
            # Check cooldown
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT last_alert_at FROM error_burst_alerts "
                        "WHERE source=?",
                        (source,),
                    ) as cur:
                        row = await cur.fetchone()
            except Exception:
                row = None
            if row and row[0]:
                try:
                    last = datetime.fromisoformat(
                        str(row[0]).replace("Z", "+00:00")
                    )
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    age_h = (now - last).total_seconds() / 3600
                    if age_h < BURST_ALERT_COOLDOWN_HOURS:
                        continue  # cooldown actif
                except Exception:
                    pass

            # Récolte un sample d'erreur récente
            sample_msg = "?"
            sample_type = "?"
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT error_type, message FROM error_log "
                        "WHERE source=? "
                        "AND datetime(occurred_at) > datetime('now', '-1 hour') "
                        "ORDER BY occurred_at DESC LIMIT 1",
                        (source,),
                    ) as cur:
                        s_row = await cur.fetchone()
                if s_row:
                    sample_type = s_row[0] or "?"
                    sample_msg = (s_row[1] or "")[:300]
            except Exception:
                pass

            # DM owner de la 1ère guild (= owner principal)
            try:
                guild = next(iter(_bot.guilds), None)
                if guild:
                    owner = (
                        guild.owner or
                        await guild.fetch_member(guild.owner_id)
                    )
                    if owner:
                        text = (
                            f"🔥 **Burst d'erreurs détecté**\n\n"
                            f"**Source :** `{source}`\n"
                            f"**Compteur :** `{count}` erreurs dans la "
                            f"dernière heure (threshold `{BURST_THRESHOLD_PER_HOUR}`)\n"
                            f"**Type :** `{sample_type}`\n"
                            f"**Sample :** _{sample_msg}_\n\n"
                            f"_Prochaine alerte du même source dans "
                            f"{BURST_ALERT_COOLDOWN_HOURS}h max._"
                        )
                        sent = False
                        try:
                            import dm_digest as _dm
                            if _dm and hasattr(_dm, "send_urgent_now"):
                                sent = await _dm.send_urgent_now(owner, text)
                        except Exception:
                            sent = False
                        if not sent:
                            try:
                                await owner.send(text)
                            except Exception:
                                pass
            except Exception as ex:
                print(f"[error_logger burst DM] {ex}")

            # Mark alerted
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO error_burst_alerts "
                        "(source, last_alert_at, last_count) "
                        "VALUES (?, CURRENT_TIMESTAMP, ?) "
                        "ON CONFLICT(source) DO UPDATE SET "
                        "last_alert_at = CURRENT_TIMESTAMP, last_count = ?",
                        (source, int(count), int(count)),
                    )
                    await db.commit()
            except Exception:
                pass
    except Exception as ex:
        print(f"[error_logger burst_check_task] {ex}")


@burst_check_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ─── Panel V2 ──────────────────────────────────────────────────────────────

def build_errors_panel(guild: discord.Guild):
    """Panel V2 affichant le résumé erreurs récentes (owner-only)."""
    if _v2 is None or guild is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _ErrorsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            summary = await get_error_summary(hours=24)
            recent = await get_recent_errors(limit=10, hours=24)

            items = []
            items.append(v2_title("🔥  Erreurs récentes (24h)"))
            items.append(v2_subtitle(
                f"_{summary['total']} erreur(s) capturée(s) dans les "
                f"dernières 24h_"
            ))
            items.append(v2_divider())

            if summary["total"] == 0:
                items.append(v2_body(
                    "✅ **Aucune erreur capturée.**\n"
                    "_Soit tout va bien, soit l'error_logger n'est wiré "
                    "nulle part. Si tu vois des prints d'erreur dans les "
                    "logs Railway, c'est qu'un module n'utilise pas encore "
                    "`error_logger.log_error()`._"
                ))
            else:
                # Top sources
                if summary["by_source"]:
                    items.append(v2_body("**📊  Top sources :**"))
                    for s in summary["by_source"][:5]:
                        items.append(v2_body(
                            f"• `{s['source']}` : **{s['count']}**"
                        ))
                    items.append(v2_divider())

                # Top types
                if summary["by_type"]:
                    items.append(v2_body("**🔧  Top types :**"))
                    for t in summary["by_type"][:5]:
                        items.append(v2_body(
                            f"• `{t['error_type']}` : **{t['count']}**"
                        ))
                    items.append(v2_divider())

                # Recent samples
                if recent:
                    items.append(v2_body("**🕐  10 dernières :**"))
                    for e in recent[:10]:
                        msg_short = (e["message"] or "")[:120]
                        items.append(v2_body(
                            f"`{e['source']}` · **{e['error_type']}**\n"
                            f"_{msg_short}_"
                        ))

            self.add_item(v2_container(*items, color=0xE74C3C))

    return _ErrorsPanel()


__all__ = [
    "setup",
    "init_db",
    "log_error",
    "get_recent_errors",
    "get_error_summary",
    "build_errors_panel",
    "burst_check_task",
    "BURST_THRESHOLD_PER_HOUR",
]
