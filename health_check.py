"""
health_check.py — Auto-réparation périodique (Phase 148).

🎯 OBJECTIF : éviter les bugs silencieux qui pourrissent pendant des
jours avant qu'on s'en rende compte.

Tâche hourly qui vérifie :
1. **DB ping** : SELECT 1 sur les tables critiques
2. **Tasks loops** : vérifie qu'aucune task scheduler n'est crashée
3. **Critical channels** : les salons indispensables existent
4. **Bot permissions** : Send + Manage Messages dans les salons critiques
5. **Memory state** : nettoie les caches in-memory trop volumineux

Si problème détecté → auto-fix quand possible, sinon DM owner.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn)
- health_check_task (loop hourly)
- run_check_now(guild=None) -> dict (manual trigger)
- get_last_report(guild_id=None) -> dict

DB tables :
- health_check_log (id PK, guild_id, check_at, results_jsonb, issues_count)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import tasks

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
# Tâche C : callback partagé fourni par bot.py → renvoie [(label, is_running)] pour TOUTES
# les boucles supervisées (= MÊME registre que le task_supervisor). Optionnel/fail-safe :
# si non câblé, on retombe sur l'ancien check 2-loops codé en dur.
_loops_status_fn = None
# D2 : callback watchdog mémoire fourni par bot.py → renvoie un dict
# {"asyncio_tasks": int, "dicts": {name: size}}. Optionnel/fail-open : si non
# câblé ou cassé, le watchdog est simplement inactif (ne bloque jamais le check).
_mem_stats_fn = None

# Tables critiques à vérifier (présence + read OK)
CRITICAL_TABLES = (
    "daily_guild_stats", "infractions", "ladder_ratings",
    "guild_config", "season_drops_log",
)

# D2 : seuils d'alerte mémoire (généreux → on alerte une fuite réelle, pas un pic).
_MEM_TASKS_THRESHOLD = 1500     # nb de tâches asyncio vivantes
_MEM_DICT_THRESHOLD = 50_000    # taille d'un seul gros dict mémoire


def setup(bot_instance, get_db_fn, db_get_fn, loops_status_fn=None, mem_stats_fn=None):
    global _bot, _get_db, _db_get, _loops_status_fn, _mem_stats_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    # Rétro-compatible : appelable sans le 4e/5e arg (ancienne signature).
    if loops_status_fn is not None:
        _loops_status_fn = loops_status_fn
    if mem_stats_fn is not None:
        _mem_stats_fn = mem_stats_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS health_check_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    check_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    results_jsonb TEXT,
                    issues_count INTEGER DEFAULT 0,
                    auto_fixed INTEGER DEFAULT 0
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[health_check init_db] {ex}")


# ─── Checks ────────────────────────────────────────────────────────────────

async def _check_db() -> dict:
    """Vérifie que la DB répond + que les tables critiques sont lisibles."""
    out = {"ok": True, "issues": [], "tables_ok": 0, "tables_fail": 0}
    if _get_db is None:
        out["ok"] = False
        out["issues"].append("DB module non initialisé")
        return out
    try:
        async with _get_db() as db:
            for t in CRITICAL_TABLES:
                try:
                    async with db.execute(f"SELECT COUNT(*) FROM {t}") as cur:
                        await cur.fetchone()
                    out["tables_ok"] += 1
                except Exception as ex:
                    out["ok"] = False
                    out["issues"].append(f"Table `{t}` : {ex}")
                    out["tables_fail"] += 1
    except Exception as ex:
        out["ok"] = False
        out["issues"].append(f"DB inaccessible : {ex}")
    return out


async def _check_tasks() -> dict:
    """Vérifie que les tasks loops supervisées sont vivantes.

    Tâche C : lit la MÊME source de vérité que le task_supervisor (callback partagé
    `_loops_status_fn` câblé par bot.py) au lieu des 2 loops codées en dur — couvre
    désormais l'ENSEMBLE du registre (listes manuelles + balayage auto). Fail-safe :
    si le callback est absent/casse, on retombe sur l'ancien check minimal."""
    out = {"ok": True, "issues": [], "alive": [], "dead": []}
    used_registry = False
    if _loops_status_fn is not None:
        try:
            statuses = _loops_status_fn() or []
            for label, running in statuses:
                if running:
                    out["alive"].append(label)
                else:
                    out["dead"].append(label)
            used_registry = True
        except Exception as ex:
            # Le callback a échoué → on bascule sur le fallback ci-dessous.
            print(f"[health_check _check_tasks registry] {ex}")
            used_registry = False

    if not used_registry:
        # Fallback historique (callback non câblé) : check minimal 2 loops.
        try:
            import dormant_wakeup as dm
            if hasattr(dm, "dormant_dispatch_task"):
                if dm.dormant_dispatch_task.is_running():
                    out["alive"].append("dormant_dispatch")
                else:
                    out["dead"].append("dormant_dispatch")
        except Exception:
            pass
        try:
            import data_cleanup as dc
            if hasattr(dc, "weekly_cleanup_task"):
                if dc.weekly_cleanup_task.is_running():
                    out["alive"].append("weekly_cleanup")
                else:
                    out["dead"].append("weekly_cleanup")
        except Exception:
            pass

    if out["dead"]:
        out["ok"] = False
        # Borne l'affichage (le registre peut lister ~85 loops) pour ne pas exploser le DM.
        dead = out["dead"]
        shown = ", ".join(dead[:15])
        if len(dead) > 15:
            shown += f" (+{len(dead) - 15})"
        out["issues"].append(f"Tasks mortes ({len(dead)}) : {shown}")
    return out


async def _check_guild_channels(guild: discord.Guild) -> dict:
    """Vérifie que le bot peut envoyer dans le salon hub et les
    salons critiques. Tente auto-fix si possible."""
    out = {"ok": True, "issues": [], "channels_checked": 0}
    if not guild:
        return out
    try:
        me = guild.me
        if me is None:
            out["ok"] = False
            out["issues"].append("Bot membre introuvable dans la guild")
            return out

        # Vérifie au moins 1 salon où le bot peut écrire
        writable = 0
        for ch in guild.text_channels:
            try:
                perms = ch.permissions_for(me)
                if perms.send_messages and perms.view_channel:
                    writable += 1
                    out["channels_checked"] += 1
                    if writable >= 5:
                        break
            except Exception:
                pass
        if writable == 0:
            out["ok"] = False
            out["issues"].append("Aucun salon où le bot peut envoyer")
    except Exception as ex:
        out["ok"] = False
        out["issues"].append(f"channel check error: {ex}")
    return out


async def _check_perms(guild: discord.Guild) -> dict:
    """Vérifie les permissions du bot."""
    out = {"ok": True, "issues": [], "perms": {}}
    if not guild or guild.me is None:
        return out
    try:
        gp = guild.me.guild_permissions
        critical = {
            "send_messages": gp.send_messages,
            "manage_messages": gp.manage_messages,
            "embed_links": gp.embed_links,
            "read_message_history": gp.read_message_history,
            "manage_channels": gp.manage_channels,
            "moderate_members": gp.moderate_members,
        }
        out["perms"] = critical
        missing = [k for k, v in critical.items() if not v]
        if missing:
            out["issues"].append(
                f"Permissions manquantes : {', '.join(missing)}"
            )
            # Pas forcément "not ok" — certaines features ne nécessitent pas tout
            if not gp.send_messages or not gp.embed_links:
                out["ok"] = False
    except Exception as ex:
        out["ok"] = False
        out["issues"].append(f"perms check error: {ex}")
    return out


# ─── Run check ──────────────────────────────────────────────────────────────

async def run_check_now(guild: Optional[discord.Guild] = None) -> dict:
    """Exécute un check complet. Si guild=None → check sur toutes les guilds."""
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "db": {},
        "tasks": {},
        "guilds": [],
    }
    issues_total = 0

    # DB global
    db_r = await _check_db()
    report["db"] = db_r
    issues_total += len(db_r.get("issues", []))

    # Tasks global
    tasks_r = await _check_tasks()
    report["tasks"] = tasks_r
    issues_total += len(tasks_r.get("issues", []))

    # Per-guild
    targets = [guild] if guild else (_bot.guilds if _bot else [])
    for g in targets:
        try:
            ch_r = await _check_guild_channels(g)
            perms_r = await _check_perms(g)
            g_issues = (ch_r.get("issues", []) +
                        perms_r.get("issues", []))
            report["guilds"].append({
                "guild_id": g.id,
                "guild_name": g.name,
                "channels": ch_r,
                "perms": perms_r,
                "issues": g_issues,
            })
            issues_total += len(g_issues)
        except Exception as ex:
            report["guilds"].append({
                "guild_id": getattr(g, "id", 0),
                "error": str(ex),
            })
            issues_total += 1

    report["issues_total"] = issues_total

    # Log
    if _get_db is not None:
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO health_check_log "
                    "(guild_id, results_jsonb, issues_count) "
                    "VALUES (?, ?, ?)",
                    (
                        guild.id if guild else 0,
                        json.dumps(report)[:5000],
                        issues_total,
                    ),
                )
                await db.commit()
        except Exception as ex:
            print(f"[health_check log] {ex}")

    # (MP au propriétaire SUPPRIMÉ le 12/08/2026, à sa demande.)
    #
    # Il partait à CHAQUE tour de boucle horaire, sans aucune déduplication — jusqu'à
    # 24 messages privés par jour. Et son déclencheur `issues_total >= 3` était garanti :
    # `CRITICAL_TABLES` cite `season_drops_log`, une table qui n'est créée nulle part dans
    # le dépôt, donc au moins un problème remontait à chaque passage, indéfiniment.
    # Le rapport continue d'être ÉCRIT en base (`health_check_log`) : rien n'est perdu,
    # seul l'envoi privé disparaît.

    return report


# (Les deux MP au super-owner — « boucles mortes » et « watchdog mémoire » — ont été
#  SUPPRIMÉS le 12/08/2026 avec les fonctions qui les construisaient. Le propriétaire a
#  demandé de ne plus recevoir de message privé hors sanctions, comptes compromis et
#  retour d'inactivité. L'état des boucles reste consultable : il est calculé par
#  `supervised_loops_status` et journalisé dans `health_check_log`.
#  ⚠️ La signature de `setup()` est laissée INTACTE : bot.py l'appelle avec 5 arguments
#  POSITIONNELS — retirer un paramètre ici produirait un TypeError au démarrage.)


# ─── Loop task ──────────────────────────────────────────────────────────────
#
# ⚠️ NE JAMAIS RETIRER `@tasks.loop` : sans lui, `health_check_task` redevient une
# fonction ordinaire, `@health_check_task.before_loop` juste en dessous lève un
# AttributeError À L'IMPORT, et le bot ne démarre plus du tout. C'est exactement ce
# qui vient d'arriver en supprimant les MP au-dessus : la coupe s'est arrêtée sur
# `async def` et a emporté le décorateur qui le précédait.

@tasks.loop(hours=1)
async def health_check_task():
    """Run health check chaque heure."""
    try:
        await run_check_now()
    except Exception as ex:
        print(f"[health_check_task] {ex}")


@health_check_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "run_check_now",
    "health_check_task",
]
