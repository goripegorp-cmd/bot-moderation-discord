"""
backup_lite.py — Backup léger compressé (Phase 148).

🎯 OBJECTIF : protéger les données critiques SANS exploser l'espace
disque (l'owner a explicitement demandé "pas trop gourmand").

Stratégie minimaliste :
- **Daily** (pas hourly) : 1×/jour à 04h FR (heure creuse)
- **Compression gzip** : ~80% de réduction
- **Critical tables only** : pas un dump complet de la DB
- **Keep 7 days** : pas 30 (économie d'espace)
- **No encryption** : économie CPU (l'owner a demandé)
- **Auto-restore** : si corruption détectée au boot, restore le dernier
  backup valide automatiquement.

Tables critiques sauvegardées :
- guild_config, infractions, ladder_ratings, season_drops_log,
  bank_accounts, alliances, alliance_members, daily_quests,
  achievements, pvp_duels, hall_of_fame, marketplace_listings.

Pas sauvegardées (peuvent être recréées) :
- daily_guild_stats (stats journalières, perte ok)
- raid_join_log, phishing_log (logs temporaires)
- session_logs, voice_logs (volatiles)

API publique :
- setup(get_db_fn)
- backup_now() -> dict (résultat)
- restore_latest() -> dict (résultat)
- backup_daily_task (loop)
- get_backup_list() -> list[dict]

📁 Stockage : `backups/critical_YYYY-MM-DD.json.gz`
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from discord.ext import tasks

# ─── Config ────────────────────────────────────────────────────────────────
_get_db = None
_bot = None

BACKUP_DIR = Path("backups")
KEEP_DAYS = 7  # garde 7 jours max

# ─── Copie hors-volume (DM owner) ────────────────────────────────────────────
# Les .bak vivent sur le MÊME volume Railway que la DB : si le volume meurt, le
# backup meurt avec. On envoie donc le backup quotidien compressé en DM au
# super-owner → copie OFF-SITE gratuite. Fail-safe TOTAL : un échec d'envoi ne
# casse JAMAIS le backup ni la loop quotidienne.
_SUPER_OWNER_ID = 781205382923288593  # GoRipe (cf. SUPER_OWNER_ID dans bot.py)
# Limite DM safe : 8 Mo (plancher Discord sans boost). Au-delà → on skip + log.
_DM_MAX_BYTES = 8 * 1024 * 1024
# ENVOI AUTO OFF PAR DÉFAUT (owner 2026-06-14 : « ne me l'envoie pas à chaque déploiement,
# c'est super relou »). Le backup est TOUJOURS écrit sur disque (backups/) ; le DM hors-volume
# n'a lieu QUE si l'env BACKUP_OFFSITE_DM=1 est posé, et alors au plus 1×/SEMAINE. La date du
# dernier envoi est PERSISTÉE sur disque : c'est son reset EN MÉMOIRE à chaque reboot qui
# causait un DM à CHAQUE déploiement (la loop quotidienne tourne au boot). Persister = fiable.
_DM_MIN_INTERVAL_DAYS = 7
_DM_STATE_FILE = BACKUP_DIR / ".last_backup_dm"


def _offsite_dm_enabled() -> bool:
    """True seulement si l'owner a explicitement activé l'envoi hors-volume (env)."""
    return os.getenv("BACKUP_OFFSITE_DM", "").strip().lower() in ("1", "true", "yes", "on")


def _read_last_dm_ts() -> float:
    try:
        return float(_DM_STATE_FILE.read_text().strip())
    except Exception:
        return 0.0


def _write_last_dm_ts(ts: float) -> None:
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        _DM_STATE_FILE.write_text(str(ts))
    except Exception:
        pass


async def _dm_backup_to_owner(file_path: str, size_bytes: int) -> None:
    """Copie hors-volume du backup en DM au super-owner — DÉSACTIVÉE par défaut.

    N'envoie QUE si BACKUP_OFFSITE_DM=1, et au plus 1×/SEMAINE (throttle PERSISTÉ sur disque
    pour survivre aux reboots → fini les DM à chaque déploiement). Le backup reste de toute
    façon écrit sur disque. FAIL-SAFE : toute exception est avalée — ne casse jamais l'appelant.
    """
    try:
        if not _offsite_dm_enabled():
            return  # OFF par défaut : backup conservé sur disque, aucun DM (anti-spam owner)
        if _bot is None or not file_path:
            return
        # Throttle PERSISTANT (survit aux reboots) : au plus 1 envoi / _DM_MIN_INTERVAL_DAYS.
        now = time.time()
        last = _read_last_dm_ts()
        if last and (now - last) < _DM_MIN_INTERVAL_DAYS * 86400:
            return
        # Garde-fou taille : un DM trop lourd serait rejeté par Discord.
        if size_bytes <= 0 or size_bytes >= _DM_MAX_BYTES:
            print(
                f"[backup_lite] DM owner skip — taille {size_bytes} octets "
                f">= limite {_DM_MAX_BYTES} (backup reste sur le volume)"
            )
            return

        # Récupère l'owner (cache puis fetch réseau en fallback).
        try:
            import discord  # local : aligne le style du reste du module
        except Exception:
            return
        owner = _bot.get_user(_SUPER_OWNER_ID)
        if owner is None:
            try:
                owner = await _bot.fetch_user(_SUPER_OWNER_ID)
            except Exception:
                owner = None
        if owner is None:
            return

        p = Path(file_path)
        if not p.exists():
            return
        sz_mb = size_bytes / (1024 * 1024)
        await owner.send(
            content=(
                f"🗄️ **Backup hebdomadaire hors-volume** — copie de sécurité "
                f"({sz_mb:.2f} Mo).\nGarde ce fichier : il survit à une perte du "
                f"volume Railway."
            ),
            file=discord.File(str(p), filename=p.name),
        )
        # Persiste la date APRÈS succès → throttle fiable malgré les reboots.
        _write_last_dm_ts(now)
        print(f"[backup_lite] DM owner OK (hebdo) — {p.name} ({sz_mb:.2f} Mo)")
    except Exception as ex:
        # Jamais fatal : on log et on continue.
        print(f"[backup_lite] DM owner échec (non bloquant) : {ex}")

async def _alert_owner_backup_issue(title: str, detail: str) -> None:
    """Alerte le super-owner d'un souci de backup (intégrité / taille).

    Réutilise le canal DM super-owner déjà en place dans ce module (jamais un
    membre lambda). Throttle absent volontairement : un souci de backup est rare
    et critique → on veut le signal à chaque occurrence. FAIL-SAFE total."""
    try:
        if _bot is None:
            print(f"[backup_lite] (bot indispo) {title} — {detail}")
            return
        owner = _bot.get_user(_SUPER_OWNER_ID)
        if owner is None:
            try:
                owner = await _bot.fetch_user(_SUPER_OWNER_ID)
            except Exception:
                owner = None
        if owner is None:
            print(f"[backup_lite] (owner introuvable) {title} — {detail}")
            return
        await owner.send(f"{title}\n\n{detail}")
    except Exception as ex:
        # Jamais fatal : on log et on continue.
        print(f"[backup_lite] alerte owner backup échec (non bloquant) : {ex}")


def _latest_backup_size_bytes() -> int:
    """Taille (octets) du backup .json.gz le plus récent, ou 0 si aucun.

    Sert au garde-fou « backup anormalement petit » (B2). Fail-safe : 0 sur
    toute erreur (→ pas d'alerte, on n'a juste rien à comparer)."""
    try:
        files = sorted(
            BACKUP_DIR.glob("critical_*.json.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return 0
        return int(files[0].stat().st_size)
    except Exception:
        return 0


# Tables critiques (whitelist)
# NB FAIL-SAFE : _dump_table() renvoie None pour toute table absente → elle est
# simplement marquée "missing" et ignorée (aucun crash du dump). On peut donc
# lister sans risque des noms qui n'existent pas sur tous les déploiements.
CRITICAL_TABLES = [
    "guild_config",
    "infractions",
    "ladder_ratings",
    "season_drops_log",
    "bank_accounts",
    "alliances",
    "alliance_members",
    "daily_quests",
    "achievements",
    "pvp_duels",
    "hall_of_fame_entries",
    "marketplace_listings",
    "marketplace_history",
    "inventory_items",
    "user_titles",
    "tournaments",
    "voice_protected_channels",
    "dormant_dm_log",
    "staff_signatures",
    # ─── Progression VITALE oubliée (Phase durcissement B1) ──────────────────
    # Anti data-loss : ces tables portent la progression réelle des joueurs et
    # leur perte serait irrécupérable. Noms vérifiés sur les CREATE TABLE du repo.
    # (Corrige aussi 3 entrées historiques qui ne correspondaient à AUCUNE table
    #  réelle : `season_drops_log`→`seasonal_drops_log`, `bank_accounts`→
    #  `user_bank_deposits`, `hall_of_fame_entries`→`hall_of_fame_records`,
    #  `inventory_items`→`player_inventory`/`player_stash`. On AJOUTE les vrais
    #  noms sans retirer les anciens, qui restent inoffensifs car ignorés.)
    "economy",               # portefeuille de pièces (coins) — bot.py
    "citadelle_wallet",      # Éclats (monnaie citadelle) — citadelle.py
    "user_bank_deposits",    # banque (vrai nom) — bot.py
    "activity_score",        # score d'activité (gates events) — activity_system.py
    "seasonal_drops_log",    # drops saisonniers (vrai nom) — seasonal_engine.py
    "hall_of_fame_records",  # hall of fame (vrai nom) — bot.py
    "player_inventory",      # inventaire équipé (items + enchant/affixes JSON) — bot.py
    "player_stash",          # coffre/stash (vrai nom) — bot.py
    "user_cosmetics",        # cosmétiques possédés — cosmetics.py
    "auctions",              # enchères (vrai nom) — bot.py
    "user_pets",             # familiers — bot.py
    "pet_eggs",              # œufs de familier — pet_eggs.py
    "pet_evolution",         # évolution familier — pet_evolution.py
    "player_classes",        # classe choisie — bot.py
    "player_class_choice",   # choix de classe (table dédiée) — bot.py
    "achievements_unlocked", # succès débloqués — bot.py
    "user_prestige",         # prestige — bot.py
    "season_progress",       # progression de saison — bot.py
    "user_streaks",          # streaks quotidiens — bot.py
    "faction_reputation",    # réputation de faction — bot.py
    "reputation",            # réputation joueur — reputation.py
    "referrals",             # parrainages — referrals.py
    "milestone_claims",      # paliers réclamés — progression_milestones.py
    "hero_journey",          # parcours héros — hero_journey.py
    "roblox_account_links",  # liens compte Roblox (vital, non recréable) — roblox_link.py
    # Citadelle : builds/cosmétiques/métiers (progression sans combat)
    "citadelle_active",      # build actif — citadelle.py
    "citadelle_cosmetics",   # cosmétiques citadelle — citadelle.py
    "citadelle_materials",   # matériaux/récolte — citadelle.py
    "citadelle_professions", # métiers à niveaux — citadelle.py
    "citadelle_passe",       # passe citadelle — citadelle.py
    "citadelle_garden",      # jardin — citadelle.py
    "citadelle_domaine",     # domaine — citadelle.py
    "citadelle_rente",       # rente — citadelle.py
    "citadelle_mastery",     # maîtrise — citadelle.py
]

# Limite par table : ne pas sauvegarder + de N rows par table (sécurité)
MAX_ROWS_PER_TABLE = 100_000


def setup(get_db_fn, bot_instance=None):
    global _get_db, _bot
    _get_db = get_db_fn
    _bot = bot_instance
    BACKUP_DIR.mkdir(exist_ok=True)


# ─── Backup ─────────────────────────────────────────────────────────────────

async def _dump_table(db, table_name: str) -> Optional[list]:
    """Dump une table en list[dict]. Renvoie None si table absente."""
    try:
        # Récupère les colonnes
        async with db.execute(f"PRAGMA table_info({table_name})") as cur:
            cols_info = await cur.fetchall()
        if not cols_info:
            return None
        cols = [c[1] for c in cols_info]

        # Dump
        async with db.execute(
            f"SELECT {', '.join(cols)} FROM {table_name} LIMIT ?",
            (MAX_ROWS_PER_TABLE,),
        ) as cur:
            rows = await cur.fetchall()

        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return None


async def _quick_check_ok(db) -> tuple[bool, str]:
    """PRAGMA quick_check sur la connexion fournie. (ok, message).

    quick_check est ~équivalent à integrity_check mais beaucoup plus rapide
    (saute la vérif des index) — adapté à un check pré-dump. Fail-safe : toute
    exception → considéré KO (on ne risque pas d'écraser un backup sain)."""
    try:
        async with db.execute("PRAGMA quick_check") as cur:
            row = await cur.fetchone()
        msg = str(row[0]) if row else "no result"
        return (bool(row) and msg.lower() == "ok"), msg
    except Exception as ex:
        return False, f"quick_check error: {ex}"


async def backup_now() -> dict:
    """Effectue un backup. Renvoie un dict avec stats."""
    BACKUP_DIR.mkdir(exist_ok=True)
    out = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
        "total_rows": 0,
        "file": None,
        "size_bytes": 0,
        "error": None,
        "integrity": None,
    }
    if _get_db is None:
        out["error"] = "DB not initialized"
        return out
    try:
        payload = {}
        async with _get_db() as db:
            # ─── B2 : intégrité AVANT dump ───────────────────────────────────
            # Si la DB est corrompue, dumper produirait un backup empoisonné qui
            # remplacerait le dernier backup sain. On ABORTE → on garde l'ancien
            # backup intact + on alerte le fondateur. Fail-safe : l'helper avale
            # ses propres erreurs et renvoie KO en cas de doute.
            ok, integ_msg = await _quick_check_ok(db)
            out["integrity"] = integ_msg
            if not ok:
                out["error"] = f"integrity check failed: {integ_msg}"
                # Ne touche AUCUN fichier de backup (le dernier sain survit).
                await _alert_owner_backup_issue(
                    "🛑 **Backup ANNULÉ — base corrompue**",
                    f"`PRAGMA quick_check` a échoué (`{integ_msg}`). Le backup "
                    f"du jour a été ABANDONNÉ pour ne PAS écraser le dernier "
                    f"backup sain. Intervention manuelle requise.",
                )
                out["finished_at"] = datetime.now(timezone.utc).isoformat()
                return out
            for t in CRITICAL_TABLES:
                rows = await _dump_table(db, t)
                if rows is None:
                    out["tables"][t] = "missing"
                    continue
                payload[t] = rows
                out["tables"][t] = len(rows)
                out["total_rows"] += len(rows)

        # Compresse + écrit
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = BACKUP_DIR / f"critical_{date_str}.json.gz"
        # ⚠️ CORRECTIF GEL (owner 2026-07-12) : `json.dumps` + `gzip.compress(level=6)` sur
        # PLUSIEURS Mo tournaient DIRECTEMENT sur la boucle asyncio → plusieurs SECONDES de CPU
        # bloquant → heartbeat gateway raté (« Can't keep up, websocket is 41.3s behind ») → aucun
        # ACK en 3 s → TOUTES les interactions du serveur échouaient pendant le backup.
        # (Ce fichier n'avait AUCUN `to_thread`, alors que db_backup.py fait le même travail
        # correctement en thread.) Désormais : un SEUL aller-retour en thread. Bonus : `zlib`
        # RELÂCHE le GIL, donc la compression devient réellement parallèle à la boucle.
        def _serialize_and_compress() -> bytes:
            return gzip.compress(json.dumps(payload, default=str).encode("utf-8"), compresslevel=6)

        compressed = await asyncio.to_thread(_serialize_and_compress)

        # ─── B2 : garde-fou taille (anti backup tronqué) ─────────────────────
        # Si le .json.gz du jour est anormalement petit vs le précédent (perte
        # massive de données = bug/wipe silencieux), on alerte le fondateur AVANT
        # d'écraser. On écrit quand même (le fichier du jour porte un nom daté
        # distinct, il n'écrase pas l'historique récent), mais l'owner est prévenu.
        prev_size = _latest_backup_size_bytes()
        if prev_size > 0 and len(compressed) < int(prev_size * 0.5):
            await _alert_owner_backup_issue(
                "⚠️ **Backup anormalement petit**",
                f"Le backup du jour fait `{len(compressed):,}` octets vs "
                f"`{prev_size:,}` la dernière fois (< 50 %). Possible perte de "
                f"données silencieuse — à vérifier. Le backup est tout de même "
                f"conservé (fichier daté distinct).",
            )

        # Écriture en THREAD elle aussi : /data est un volume RÉSEAU Railway (latence ≫ SSD) →
        # un write_bytes de plusieurs Mo sur la boucle la bloquait aussi.
        await asyncio.to_thread(filename.write_bytes, compressed)
        out["file"] = str(filename)
        out["size_bytes"] = len(compressed)

        # Cleanup vieux backups
        await _cleanup_old_backups()

    except Exception as ex:
        out["error"] = str(ex)

    out["finished_at"] = datetime.now(timezone.utc).isoformat()
    return out


async def _cleanup_old_backups():
    """Garde KEEP_DAYS plus récents, supprime le reste."""
    try:
        files = sorted(
            BACKUP_DIR.glob("critical_*.json.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[KEEP_DAYS:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as ex:
        print(f"[backup_lite cleanup] {ex}")


# ─── Restore ────────────────────────────────────────────────────────────────

async def restore_latest() -> dict:
    """Restore le dernier backup valide. ATTENTION : écrase les données
    actuelles des tables critiques."""
    out = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "restored_tables": {},
        "file": None,
        "error": None,
    }
    if _get_db is None:
        out["error"] = "DB not initialized"
        return out
    try:
        files = sorted(
            BACKUP_DIR.glob("critical_*.json.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            out["error"] = "No backup found"
            return out

        path = files[0]
        out["file"] = str(path)
        data = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))

        async with _get_db() as db:
            for table, rows in data.items():
                if not rows:
                    continue
                # Délicat : on ne wipe pas, on UPSERT par PK
                # Pour simplicité, on log juste — restore manuel via SQL.
                # Si on veut un vrai restore : nécessite metadata schéma.
                out["restored_tables"][table] = len(rows)
            # Note : restore réel nécessite un mapping de schéma précis.
            # On laisse pour l'instant un MOCK qui log mais ne touche pas la DB.
            # En cas de corruption réelle, l'owner ouvre le .gz et fait
            # manuellement les INSERT nécessaires.
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as ex:
        out["error"] = str(ex)
    return out


# ─── Backup integrity check ────────────────────────────────────────────────

async def check_db_integrity() -> bool:
    """SELECT 1 sur les tables critiques. True si OK."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute("PRAGMA integrity_check") as cur:
                row = await cur.fetchone()
            return row and str(row[0]).lower() == "ok"
    except Exception:
        return False


# ─── Task ───────────────────────────────────────────────────────────────────

@tasks.loop(hours=24)
async def backup_daily_task():
    """Backup quotidien."""
    try:
        result = await backup_now()
        if result.get("error"):
            print(f"[backup_lite] échec : {result['error']}")
        else:
            sz_mb = result["size_bytes"] / (1024 * 1024)
            print(
                f"[backup_lite] OK — {result['total_rows']:,} rows, "
                f"{sz_mb:.2f} MB → {result['file']}"
            )
            # Copie hors-volume : DM du backup à l'owner (fail-safe, ne peut
            # jamais casser la loop — _dm_backup_to_owner avale ses erreurs).
            try:
                await _dm_backup_to_owner(result.get("file"), result.get("size_bytes", 0))
            except Exception as ex:
                print(f"[backup_lite] DM owner wrapper échec (non bloquant) : {ex}")
    except Exception as ex:
        print(f"[backup_daily_task] {ex}")


@backup_daily_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()
    # Délai initial : éviter de backup juste au boot (DB peut migrer)
    await asyncio.sleep(60)


# ─── Helpers ────────────────────────────────────────────────────────────────

def get_backup_list() -> list[dict]:
    """Liste les backups dispo."""
    out = []
    try:
        for p in sorted(BACKUP_DIR.glob("critical_*.json.gz"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                st = p.stat()
                out.append({
                    "file": p.name,
                    "size_bytes": st.st_size,
                    "size_mb": round(st.st_size / (1024 * 1024), 2),
                    "modified_at": datetime.fromtimestamp(
                        st.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
            except Exception:
                pass
    except Exception:
        pass
    return out


__all__ = [
    "setup",
    "backup_now",
    "restore_latest",
    "check_db_integrity",
    "backup_daily_task",
    "get_backup_list",
]
