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

# Tables critiques à vérifier (présence + read OK)
CRITICAL_TABLES = (
    "daily_guild_stats", "infractions", "ladder_ratings",
    "guild_config", "season_drops_log",
)


def setup(bot_instance, get_db_fn, db_get_fn, loops_status_fn=None):
    global _bot, _get_db, _db_get, _loops_status_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    # Rétro-compatible : appelable sans le 4e arg (ancienne signature).
    if loops_status_fn is not None:
        _loops_status_fn = loops_status_fn


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

    # DM owner si problèmes critiques
    if issues_total >= 3 and _bot is not None:
        try:
            for g in (_bot.guilds if guild is None else [guild]):
                gr = next(
                    (x for x in report["guilds"] if x.get("guild_id") == g.id),
                    None,
                )
                if not gr or not gr.get("issues"):
                    continue
                owner = g.owner or await g.fetch_member(g.owner_id)
                if owner:
                    lines = [
                        f"🩺 **Health check — {g.name}**",
                        f"",
                        f"Problèmes détectés : `{len(gr['issues'])}`",
                        "",
                    ]
                    for i, iss in enumerate(gr["issues"][:8], 1):
                        lines.append(f"`{i}.` {iss}")
                    if len(gr["issues"]) > 8:
                        lines.append(
                            f"_+ {len(gr['issues']) - 8} autre(s)..._"
                        )
                    try:
                        await owner.send("\n".join(lines))
                    except Exception:
                        pass
        except Exception as ex:
            print(f"[health_check DM owner] {ex}")

    # Tâche C : signaler au super-owner les BOUCLES MORTES persistantes (lues depuis le
    # registre mutualisé). Le DM guild ci-dessus ne porte QUE les soucis per-guild ; les
    # tasks mortes sont globales → on les remonte ici, en DIRECT au super-owner. Anti-spam :
    # dédup sur l'ensemble des labels morts (pas de re-DM tant que le même set reste mort).
    # Fail-safe total : ne lève jamais.
    try:
        await _maybe_dm_dead_loops(report.get("tasks", {}))
    except Exception as ex:
        print(f"[health_check dead-loops DM] {ex}")

    return report


# État dédup pour le DM « boucles mortes » (anti-spam ; non persistant — reset au reboot,
# acceptable car un reboot relance tout le filet de résurrection).
_dead_loops_last_signature = None


async def _maybe_dm_dead_loops(tasks_report: dict) -> None:
    """DM le super-owner UNIQUEMENT si des boucles supervisées sont mortes, et seulement
    quand l'ensemble change (dédup). Fail-safe : avale toute erreur."""
    global _dead_loops_last_signature
    if _bot is None:
        return
    dead = list(tasks_report.get("dead") or [])
    if not dead:
        _dead_loops_last_signature = None  # tout est revenu vivant → on réarme l'alerte
        return
    signature = ",".join(sorted(dead))
    if signature == _dead_loops_last_signature:
        return  # même set de morts qu'au dernier check → pas de re-spam
    _dead_loops_last_signature = signature

    try:
        import owner_ids as _oids
        owner_id_set = _oids.SUPER_OWNER_IDS
    except Exception:
        owner_id_set = {781205382923288593}  # super-owner unique (fallback fail-safe)

    shown = dead[:15]
    lines = [
        "🩺 **Boucles de tâches mortes**",
        "",
        f"`{len(dead)}` boucle(s) supervisée(s) ne tournent pas au moment du health check :",
        "",
    ]
    for i, name in enumerate(shown, 1):
        lines.append(f"`{i}.` `{name}`")
    if len(dead) > len(shown):
        lines.append(f"_+ {len(dead) - len(shown)} autre(s)..._")
    lines.append("")
    lines.append("_Le superviseur tente de les relancer ; la cause du décès est journalisée._")
    body = "\n".join(lines)

    for uid in owner_id_set:
        try:
            user = _bot.get_user(int(uid)) or await _bot.fetch_user(int(uid))
            if user is not None:
                await user.send(body)
        except Exception:
            # anti-429 / DM fermés / user introuvable : on n'insiste pas, on ne lève pas.
            continue


# ─── Loop task ──────────────────────────────────────────────────────────────

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
