"""
voice_autoclean.py — Auto-delete des vocaux temporaires vides (Phase 167.2).

🎯 OBJECTIF : éviter que le serveur accumule des vocaux fantômes créés
par des stages/events qui ne sont jamais cleanup. Si un vocal est vide
depuis 5 min consécutives ET match un pattern "temporaire", on le delete.

⚠️ SÉCURITÉ : par défaut, le bot ne touche RIEN. Il faut explicitement
configurer des catégories à scanner via `voice_autoclean_category_ids`
dans guild_config. Et même là, il ne supprime QUE les vocaux dont le
nom matche un pattern temp explicite :
- "🔴-watching-*" (Phase 163.4 watch parties)
- "temp-*"
- "🎤-*"
- "stage-*"

Pas de fausse manipulation possible avec ce filtre strict.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- check_task (loop 1 min)

DB :
- voice_empty_since (channel_id PK, guild_id, empty_since)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Délai avant suppression d'un vocal vide
EMPTY_DELETE_AFTER_MIN = 5

# Patterns de noms de vocaux qu'on accepte de supprimer auto
TEMP_VOICE_PATTERNS = [
    re.compile(r"^🔴-watching"),         # Phase 163.4 watch party
    re.compile(r"^temp-", re.IGNORECASE),
    re.compile(r"^🎤-"),
    re.compile(r"^stage-", re.IGNORECASE),
    re.compile(r"^game-night-", re.IGNORECASE),  # Phase 46.2
]


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
                CREATE TABLE IF NOT EXISTS voice_empty_since (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    empty_since TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_empty_guild "
                "ON voice_empty_since(guild_id, empty_since)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[voice_autoclean init_db] {ex}")


def _is_temp_voice_name(name: str) -> bool:
    """True si le nom du vocal match un pattern temp."""
    if not name:
        return False
    for pat in TEMP_VOICE_PATTERNS:
        if pat.search(name):
            return True
    return False


async def _get_watched_categories(guild_id: int) -> list[int]:
    """Lit les catégories où le auto-clean est activé."""
    if _db_get is None:
        return []
    try:
        cfg_data = await _db_get(guild_id)
        cats = cfg_data.get("voice_autoclean_category_ids", []) or []
        if isinstance(cats, list):
            return [int(c) for c in cats if c]
        return []
    except Exception:
        return []


@tasks.loop(minutes=1)
async def check_task():
    """Toutes les minutes :
    - Marque les vocaux temp + vides + dans catégorie surveillée
    - Si déjà marqué depuis > EMPTY_DELETE_AFTER_MIN min → delete
    - Si plus vide → unmarke
    """
    if _bot is None or _get_db is None:
        return
    try:
        now = datetime.now(timezone.utc)
        for guild in _bot.guilds:
            try:
                watched_cats = await _get_watched_categories(guild.id)
                if not watched_cats:
                    continue

                # Collect tous les vocaux des catégories surveillées
                candidates: list[discord.VoiceChannel] = []
                for vc in guild.voice_channels:
                    if vc.category_id not in watched_cats:
                        continue
                    if not _is_temp_voice_name(vc.name):
                        continue
                    candidates.append(vc)

                for vc in candidates:
                    is_empty = len(vc.members) == 0
                    if is_empty:
                        # Marque ou check si timeout dépassé
                        async with _get_db() as db:
                            async with db.execute(
                                "SELECT empty_since FROM voice_empty_since "
                                "WHERE channel_id=?",
                                (vc.id,),
                            ) as cur:
                                row = await cur.fetchone()
                        if row and row[0]:
                            # Déjà marqué → check si timeout
                            try:
                                since = datetime.fromisoformat(
                                    str(row[0]).replace("Z", "+00:00")
                                )
                                if since.tzinfo is None:
                                    since = since.replace(tzinfo=timezone.utc)
                                if (now - since).total_seconds() >= EMPTY_DELETE_AFTER_MIN * 60:
                                    # DELETE
                                    try:
                                        await vc.delete(
                                            reason="Voice autoclean : vide > "
                                            f"{EMPTY_DELETE_AFTER_MIN}min"
                                        )
                                    except (discord.Forbidden, discord.NotFound):
                                        pass
                                    except Exception as ex_del:
                                        print(
                                            f"[voice_autoclean delete ch={vc.id}] {ex_del}"
                                        )
                                    # Cleanup DB
                                    try:
                                        async with _get_db() as db:
                                            await db.execute(
                                                "DELETE FROM voice_empty_since "
                                                "WHERE channel_id=?",
                                                (vc.id,),
                                            )
                                            await db.commit()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        else:
                            # Première fois vide → INSERT
                            try:
                                async with _get_db() as db:
                                    await db.execute(
                                        "INSERT OR REPLACE INTO voice_empty_since "
                                        "(channel_id, guild_id, empty_since) "
                                        "VALUES (?, ?, CURRENT_TIMESTAMP)",
                                        (vc.id, guild.id),
                                    )
                                    await db.commit()
                            except Exception:
                                pass
                    else:
                        # Plus vide → unmarke (réinitialise le compteur)
                        try:
                            async with _get_db() as db:
                                await db.execute(
                                    "DELETE FROM voice_empty_since "
                                    "WHERE channel_id=?",
                                    (vc.id,),
                                )
                                await db.commit()
                        except Exception:
                            pass
            except Exception as ex_g:
                print(f"[voice_autoclean guild={guild.id}] {ex_g}")
    except Exception as ex:
        print(f"[voice_autoclean check_task] {ex}")


@check_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "check_task",
    "TEMP_VOICE_PATTERNS",
    "EMPTY_DELETE_AFTER_MIN",
]
