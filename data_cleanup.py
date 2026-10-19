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
| activite_jours              | 90j       | Présence : 7 j par défaut |
| health_check_log            | 30j       | Rapport horaire           |

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

import casier
import publications
import questions
import registre
import tableau
import vigilance

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# ─── Configuration : (table_name, column_for_date, retention_days) ───────
# Si column_for_date est None, on utilise simplement "created_at" si elle existe.
CLEANUP_RULES = [
    ("anomaly_log",               "detected_at", 180),
    ("daily_join_log",            "joined_day",  730),
    ("daily_stats_snapshot",      "captured_at", 730),
    #  14/10/2026 : une ligne par membre actif et par jour, sans fin. La
    #  présence ne regarde que quelques jours (7 par défaut) : 90 suffisent.
    ("activite_jours",            "jour",        90),
    #  Un rapport par heure, jamais relu au-delà de quelques jours.
    ("health_check_log",          "check_at",    30),
    #  Les transcripts sur disque vivent 120 jours (transcript_store) : leur index aussi.
    ("ticket_transcripts",        "closed_at",   120),
    ("sondages",                  "cree_le",     90),
]

#  19/10/2026 : « que ça s'auto-nettoie automatiquement et que ça puisse durer dans le temps ».
#  (nom, requête, jours, format de l'horodatage) — la borne est calculée ici, dans le format
#  de la colonne : jamais une comparaison texte/entier (un entier est toujours « plus petit »
#  qu'un texte pour SQLite, tout partirait). Les tickets ouverts ne sont jamais touchés ; le
#  casier garde les sanctions du staff deux ans, les détections automatiques un an.
PURGES_CIBLEES = [
    ("tickets fermés", "DELETE FROM tickets WHERE status='closed' AND created_at < ?", 365, "sqlite"),
    ("ticket_log_events", "DELETE FROM ticket_log_events WHERE created_unix < ?", 365, "unix"),
    ("ticket_audit", "DELETE FROM ticket_audit WHERE at < ?", 365, "sqlite"),
    ("ticket_log_msgs", "DELETE FROM ticket_log_msgs WHERE ticket_id NOT IN (SELECT id FROM tickets)", None, None),
    ("casier : détections", "DELETE FROM infractions WHERE created_at < ?"
                            " AND type NOT IN ('warn', 'mute', 'kick', 'ban')", 365, "sqlite"),
    ("casier : sanctions", "DELETE FROM infractions WHERE created_at < ?", 730, "sqlite"),
    *registre.PURGES,
    *questions.PURGES,
    *publications.PURGES,
    *vigilance.PURGES,
    *tableau.PURGES,
    *casier.PURGES,
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


def _borne(jours: int, fmt: str):
    t = datetime.now(timezone.utc) - timedelta(days=jours)
    return int(t.timestamp()) if fmt == "unix" else t.strftime("%Y-%m-%d %H:%M:%S")


async def _purges_ciblees() -> dict[str, int]:
    out: dict[str, int] = {}
    for nom, sql, jours, fmt in PURGES_CIBLEES:
        try:
            async with _get_db() as db:
                cur = await db.execute(sql, (_borne(jours, fmt),) if jours else ())
                out[nom] = int(cur.rowcount or 0)
                await db.commit()
        except Exception as ex:  # table absente sur une base ancienne : rien à purger
            print(f"[data_cleanup purge {nom}] {type(ex).__name__} {ex}")
            out[nom] = 0
    return out


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
    results.update(await _purges_ciblees())
    return results


async def part_libre() -> float:
    """La part du fichier faite de pages libres (freelist / page_count)."""
    if _get_db is None:
        return 0.0
    try:
        async with _get_db() as db:
            async with db.execute("PRAGMA page_count") as c:
                pages = (await c.fetchone())[0] or 0
            async with db.execute("PRAGMA freelist_count") as c:
                libres = (await c.fetchone())[0] or 0
        return libres / pages if pages else 0.0
    except Exception as ex:
        print(f"[data_cleanup part_libre] {ex}")
        return 0.0


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

        # VACUUM si on a supprimé beaucoup, OU si les pages libres dépassent 20 % du fichier
        # (19/10/2026 : tables des accessoires supprimées — SQLite ne rend la place qu'ici).
        if total > 1000 or await part_libre() > 0.20:
            ok = await vacuum_db()
            if not ok:
                print("🚨 [data_cleanup] VACUUM échoué")
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
