"""
data_cleanup.py — Purge hebdomadaire des tables qui grossissent (Phase 143).

Comble la limitation #6 identifiée dans l'audit final : les tables ajoutées
par les modules récents (Phase 130-141) n'ont pas de mécanisme de cleanup.
Sans purge, elles grossissent indéfiniment et risquent de saturer la DB en
3-6 mois sur un serveur actif.

Stratégie : task hebdomadaire (dimanche 04h00 FR — heure morte) qui DELETE
toutes les rows older than N jours pour chaque table. Rétention configurable
par table.

Tables purgées + rétention :

| Table                       | Rétention | Justification             |
|-----------------------------|-----------|---------------------------|
| gift_log                    | 90j       | Plus utilisé pour analyse |
| social_interactions         | 60j       | Anti-spam window dépassée |
| voice_milestone_claims      | 365j      | Garde 1 an pour stats     |
| milestone_claims            | 365j      | Idem                      |
| highlights_log              | 90j       | Anti-doublon hebdo suffit |
| bot_post_tracking           | 90j       | Best-week ne lit que 7j   |
| anomaly_log                 | 180j      | Garde 6 mois pour audit   |
| daily_join_log              | 730j      | Garde 2 ans (retention)   |
| daily_stats_snapshot        | 730j      | Idem (history command)    |

Note : pas de purge sur friendships / rivalries / marriages (n/a, supprimées)
ou wiki_entries / roadmap_items (perso staff, garde tout).

API publique :
- setup(bot_instance, get_db_fn)
- run_cleanup() — exécution manuelle (returns dict {table: rows_deleted})
- weekly_cleanup_task — task @ dimanche 04h FR

Conforme RULES.md : pur outil maintenance DB.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# ─── Configuration : (table_name, column_for_date, retention_days) ───────
# Si column_for_date est None, on utilise simplement "created_at" si elle existe.
CLEANUP_RULES = [
    ("gift_log",                  "created_at",  90),
    ("social_interactions",       "created_at",  60),
    ("voice_milestone_claims",    "claimed_at",  365),
    ("milestone_claims",          "claimed_at",  365),
    ("highlights_log",            "posted_at",   90),
    ("bot_post_tracking",         "posted_at",   90),
    ("anomaly_log",               "detected_at", 180),
    ("daily_join_log",            "joined_day",  730),
    ("daily_stats_snapshot",      "captured_at", 730),
]

# Day-of-week for the task (6 = Sunday) + hour (FR)
CLEANUP_WEEKDAY = 6
CLEANUP_HOUR_FR = 4


# Refs injectés
_bot = None
_get_db = None


def setup(bot_instance, get_db_fn):
    """Configure le module."""
    global _bot, _get_db
    _bot = bot_instance
    _get_db = get_db_fn


# ═══════════════════════════════════════════════════════════════════════════════
# CLEANUP CORE
# ═══════════════════════════════════════════════════════════════════════════════

async def _purge_table(
    table: str, date_col: str, retention_days: int
) -> int:
    """Purge une table. Retourne nb de rows supprimées.

    Gère les colonnes DATETIME et TEXT (YYYY-MM-DD) de manière compatible.
    """
    if _get_db is None:
        return 0
    try:
        # On utilise une comparaison ISO string qui marche pour DATETIME ET TEXT
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        # Pour les colonnes "joined_day" / "left_day" qui sont au format
        # YYYY-MM-DD, on tronque le cutoff à la même précision.
        cutoff_day = cutoff_iso.split("T")[0]

        async with _get_db() as db:
            # Detect si la table existe (sinon skip silencieux)
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ) as cur:
                if not await cur.fetchone():
                    return 0

            # On essaie d'abord avec ISO format, fallback day format
            try:
                cur = await db.execute(
                    f"DELETE FROM {table} WHERE {date_col} < ?",
                    (cutoff_iso,),
                )
                rows = cur.rowcount or 0
            except Exception:
                # Si l'ISO format échoue (column type incompatible), retry avec day
                cur = await db.execute(
                    f"DELETE FROM {table} WHERE {date_col} < ?",
                    (cutoff_day,),
                )
                rows = cur.rowcount or 0

            await db.commit()
            return int(rows)
    except Exception as ex:
        print(f"[data_cleanup _purge_table {table}] {ex}")
        return 0


async def run_cleanup() -> dict[str, int]:
    """Exécute le cleanup complet. Retourne {table: rows_deleted}.

    Safe : try/except englobant à chaque table, ne crash jamais.
    """
    results: dict[str, int] = {}
    if _get_db is None:
        return results
    for table, col, retention in CLEANUP_RULES:
        try:
            deleted = await _purge_table(table, col, retention)
            results[table] = deleted
        except Exception as ex:
            print(f"[data_cleanup run_cleanup {table}] {ex}")
            results[table] = 0
    return results


async def vacuum_db() -> bool:
    """Compacte la DB après cleanup (récupère l'espace libre).

    À ne lancer qu'après un gros purge — coûteux mais réduit la taille du fichier.
    """
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute("VACUUM")
            await db.commit()
        return True
    except Exception as ex:
        print(f"[data_cleanup vacuum_db] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TASK HEBDOMADAIRE — Dimanche 04h FR
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def weekly_cleanup_task():
    """Tourne toutes les 30 min — exécute le cleanup DIMANCHE 04h-04h30 FR."""
    try:
        if _bot is None:
            return
        now_local = datetime.now(_PARIS_TZ)
        if now_local.weekday() != CLEANUP_WEEKDAY:
            return
        if now_local.hour != CLEANUP_HOUR_FR:
            return

        # Anti-doublon : on stocke la date du dernier run dans un fichier
        # ou on utilise un test simple sur les minutes
        if now_local.minute >= 30:
            return  # On a déjà tourné (probablement) dans la 1ère moitié de l'heure

        results = await run_cleanup()
        total = sum(results.values())
        print(
            f"🧹 [data_cleanup] purge hebdo terminée — "
            f"{total} rows supprimées au total : {results}"
        )

        # VACUUM seulement si on a supprimé beaucoup
        if total > 1000:
            ok = await vacuum_db()
            print(f"🧹 [data_cleanup] VACUUM {'OK' if ok else 'échoué'}")
    except Exception as ex:
        print(f"[data_cleanup weekly_cleanup_task] {ex}")


@weekly_cleanup_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "run_cleanup",
    "vacuum_db",
    "weekly_cleanup_task",
    "CLEANUP_RULES",
]
