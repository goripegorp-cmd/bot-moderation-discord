"""
db_backup.py — Backup quotidien automatique de la DB SQLite (Phase 126).

Stratégie :
- Une fois par 24h, copie atomique du fichier .db dans un dossier `backups/`
- Format du nom : `bot.db.YYYY-MM-DD_HHMM.bak`
- Rétention : 7 derniers backups (rotation auto, suppression des plus vieux)
- Utilise sqlite3.iterdump() pour garantir une copie cohérente (vs filesystem copy
  qui peut être incohérent si transaction en cours)
- Si la DB est sur volume Railway (/data), backup dans `/data/backups/`
- Sinon backup dans `./data/backups/` (chemin paths.module_dir)

Usage dans bot.py :
    import db_backup
    # Démarrer la loop dans on_ready :
    if not db_backup.backup_task.is_running():
        db_backup.backup_task.start()

Notes de sécurité :
- Aucune dépendance externe (sqlite3 stdlib)
- Ne crash JAMAIS le bot : exceptions catchées + log
- Backup atomique : écrit dans .tmp puis rename (no half-written files)
- Skip si DB introuvable (ex: premier démarrage)
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import tasks

# ─── Configuration ───────────────────────────────────────────────────────
RETENTION_COUNT = 7   # Garde 7 derniers backups (1 semaine)
BACKUP_INTERVAL_HOURS = 24

# B2 : alerte intégrité. _do_backup_sync() tourne dans un thread (sqlite3 sync) →
# il ne peut pas await un DM. On dépose donc le message ici ; la task async le
# flushe via le canal owner déjà câblé dans backup_lite (super-owner uniquement,
# jamais un membre). Fail-safe : si rien n'est dispo, on log et on n'insiste pas.
_pending_integrity_alert: str | None = None


def _alert_owner_integrity(integ_msg: str) -> None:
    """(sync, thread) Mémorise une alerte intégrité à flusher par la task async."""
    global _pending_integrity_alert
    _pending_integrity_alert = integ_msg


def _resolve_db_path() -> Path:
    """Retourne le chemin de la DB du bot (même logique que bot.py)."""
    if os.path.exists('/data'):
        return Path('/data') / 'bot.db'
    return Path('bot.db')


def _resolve_backup_dir() -> Path:
    """Retourne le dossier de backups (créé si absent)."""
    if os.path.exists('/data') and os.path.isdir('/data'):
        d = Path('/data') / 'backups'
    else:
        # paths.module_dir si dispo, sinon ./data/backups
        try:
            from paths import module_dir
            d = module_dir('backups')
        except Exception:
            d = Path('data') / 'backups'
    try:
        d.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as ex:
        print(f"[db_backup] mkdir {d} failed: {ex}")
    return d


def _do_backup_sync() -> str | None:
    """Exécute le backup en bloquant (à appeler via asyncio.to_thread).

    Utilise sqlite3 backup API (cohérent même si write en cours).
    Retourne le chemin du backup créé, ou None si échec.
    """
    src = _resolve_db_path()
    if not src.exists():
        print(f"[db_backup] source DB not found: {src}")
        return None

    dst_dir = _resolve_backup_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    final_path = dst_dir / f"bot.db.{ts}.bak"
    tmp_path = dst_dir / f".bot.db.{ts}.tmp"

    try:
        # Connexion source (read-only safe via backup API)
        src_conn = sqlite3.connect(str(src))
        try:
            # ─── B2 : intégrité AVANT dump ───────────────────────────────────
            # quick_check sur la source : si la DB est corrompue, on N'ÉCRIT PAS
            # un .bak empoisonné — on aborte et on retourne None (l'historique de
            # .bak sains précédents reste intact). Fail-safe : toute erreur du
            # check est traitée comme corruption.
            try:
                cur = src_conn.execute("PRAGMA quick_check")
                row = cur.fetchone()
                integ = str(row[0]) if row else "no result"
            except Exception as ex:
                integ = f"quick_check error: {ex}"
            if integ.lower() != "ok":
                print(f"🛑 [db_backup] integrity KO ({integ}) — backup ABANDONNÉ")
                _alert_owner_integrity(integ)
                return None

            dst_conn = sqlite3.connect(str(tmp_path))
            try:
                # Backup API : copie cohérente même si writes en cours
                with dst_conn:
                    src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        finally:
            src_conn.close()

        # Rename atomique (no half-written)
        try:
            os.replace(tmp_path, final_path)
        except OSError as ex:
            print(f"[db_backup] rename failed: {ex}")
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None

        size_kb = final_path.stat().st_size / 1024
        print(f"✅ [db_backup] {final_path.name} ({size_kb:.1f} KB)")
        return str(final_path)
    except Exception as ex:
        print(f"[db_backup] backup failed: {ex}")
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _rotate_old_backups_sync() -> int:
    """Supprime les backups au-delà de RETENTION_COUNT (ordre temporel).

    Retourne le nombre de backups supprimés.
    """
    dst_dir = _resolve_backup_dir()
    try:
        backups = sorted(
            [p for p in dst_dir.glob("bot.db.*.bak") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,  # plus récent en premier
        )
    except Exception as ex:
        print(f"[db_backup] list backups failed: {ex}")
        return 0

    deleted = 0
    for old in backups[RETENTION_COUNT:]:
        try:
            old.unlink()
            deleted += 1
            print(f"🗑️  [db_backup] removed old backup: {old.name}")
        except Exception as ex:
            print(f"[db_backup] delete {old.name} failed: {ex}")
    return deleted


@tasks.loop(hours=BACKUP_INTERVAL_HOURS)
async def backup_task():
    """Tâche périodique : backup quotidien + rotation.

    Tourne dans un thread (sqlite3 sync) pour ne pas bloquer la loop asyncio.
    Try/except englobant : ne plante JAMAIS le bot.
    """
    try:
        # Délègue le backup au threadpool (sqlite3 = sync)
        path = await asyncio.to_thread(_do_backup_sync)
        if path:
            await asyncio.to_thread(_rotate_old_backups_sync)
        # B2 : flush une éventuelle alerte intégrité posée par le thread sync.
        # Fail-safe total : ne casse jamais la loop.
        global _pending_integrity_alert
        if _pending_integrity_alert:
            msg = _pending_integrity_alert
            _pending_integrity_alert = None
            try:
                import backup_lite
                await backup_lite._alert_owner_backup_issue(
                    "🛑 **Backup .db ANNULÉ — base corrompue**",
                    f"`PRAGMA quick_check` a échoué (`{msg}`). Aucun `.bak` n'a "
                    f"été écrit ; les backups sains précédents sont intacts.",
                )
            except Exception as ex2:
                print(f"[db_backup task] alerte intégrité non envoyée : {ex2}")
    except Exception as ex:
        print(f"[db_backup task] {ex}")


@backup_task.before_loop
async def _before_loop():
    """Attend que le bot soit prêt, puis fait un premier backup immédiat
    si aucun backup n'existe (cold start)."""
    try:
        # On délaye 60s après le boot pour ne pas concurrencer db_init
        await asyncio.sleep(60)
        dst_dir = _resolve_backup_dir()
        if not any(dst_dir.glob("bot.db.*.bak")):
            print("[db_backup] no existing backup, doing initial snapshot…")
            await asyncio.to_thread(_do_backup_sync)
    except Exception as ex:
        print(f"[db_backup before_loop] {ex}")


def list_backups() -> list[dict]:
    """API d'introspection : retourne la liste des backups (pour /owner)."""
    dst_dir = _resolve_backup_dir()
    out = []
    try:
        for p in sorted(dst_dir.glob("bot.db.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                st = p.stat()
                out.append({
                    "name": p.name,
                    "path": str(p),
                    "size_kb": round(st.st_size / 1024, 1),
                    "mtime_ts": int(st.st_mtime),
                })
            except Exception:
                continue
    except Exception as ex:
        print(f"[db_backup list_backups] {ex}")
    return out


__all__ = ["backup_task", "list_backups", "RETENTION_COUNT", "BACKUP_INTERVAL_HOURS"]
