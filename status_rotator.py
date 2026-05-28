"""
status_rotator.py — Bot status dynamique rotatif (Phase 167.1).

🎯 OBJECTIF : garder le bot visible et "vivant" dans la liste membres.
Au lieu d'un status statique "🟢 En ligne", on tourne toutes les 30 min
entre 6-8 messages contextuels qui montrent que le bot bosse :
- "🎮 {member_count} membres"
- "⚔️ Boss raid hebdo samedi 21h"
- "📅 Stream programmé : {next_stream}"
- "⭐ {N} ⭐ spotlighted cette semaine"
- "🍯 Honeypot actif : N pièges déclenchés"
- "📡 /hub pour tes events"

⚠️ Discord limite à 1 status par bot global (pas par guild). Donc on
choisit la guild "primaire" (la 1ère ou la plus grande) pour les stats.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- rotator_task (loop 30 min)
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Templates avec placeholders {var} — quelques uns sont dynamiques,
# d'autres statiques de fallback
STATUS_TEMPLATES_DYNAMIC = [
    # ({template}, {required_data_keys})
    ("🎮 {member_count} membres", ["member_count"]),
    ("⭐ {star_count} ⭐ cette semaine", ["star_count"]),
    ("🎯 {active_quests} quêtes actives", ["active_quests"]),
    ("⚔️ {boss_kills_week} kills cette semaine", ["boss_kills_week"]),
    ("🎙️ {voice_min_today} min vocal aujourd'hui", ["voice_min_today"]),
    ("📅 Stream : {next_stream_str}", ["next_stream_str"]),
]

STATUS_TEMPLATES_STATIC = [
    "🍯 Honeypot anti-bot actif",
    "🎮 /hub pour tes events",
    "📰 /profile pour ton récap",
    "⭐ Réagis ⭐ pour highlight",
    "📡 Server pulse via /hub",
    "🛡️ Modération auto 2026",
    "🎯 /achievements à débloquer",
    "🎰 /hub → loterie hebdo",
]


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


def _pick_primary_guild() -> Optional[discord.Guild]:
    """Choisit la guild la plus active (plus grosse member_count)."""
    if _bot is None or not _bot.guilds:
        return None
    try:
        return max(_bot.guilds, key=lambda g: g.member_count or 0)
    except Exception:
        return _bot.guilds[0]


async def _collect_dynamic_data(guild: discord.Guild) -> dict:
    """Récolte les valeurs dynamiques pour les templates.
    Toutes les valeurs sont best-effort — on retourne None si pas dispo."""
    out: dict = {}
    if not guild:
        return out

    out["member_count"] = guild.member_count or 0

    if _get_db is None:
        return out

    try:
        async with _get_db() as db:
            # ⭐ count cette semaine
            try:
                async with db.execute(
                    "SELECT COALESCE(SUM(star_count), 0) "
                    "FROM spotlighted_messages "
                    "WHERE guild_id=? AND datetime(spotlight_at) > "
                    "datetime('now', '-7 days')",
                    (guild.id,),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    out["star_count"] = int(row[0] or 0)
            except Exception:
                pass

            # Quêtes actives (non claimed) cette semaine
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM daily_quest_progress "
                    "WHERE guild_id=? AND day >= "
                    "strftime('%Y-%m-%d', 'now', '-7 days')",
                    (guild.id,),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    out["active_quests"] = int(row[0] or 0)
            except Exception:
                pass

            # Boss kills cette semaine
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM world_bosses "
                    "WHERE guild_id=? AND ended=1 AND "
                    "datetime(started_at) > datetime('now', '-7 days')",
                    (guild.id,),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    out["boss_kills_week"] = int(row[0] or 0)
            except Exception:
                pass

            # Voice minutes aujourd'hui (heatmap)
            try:
                today_wd = (
                    datetime.now(_PARIS_TZ).weekday() if _PARIS_TZ
                    else datetime.now(timezone.utc).weekday()
                )
                async with db.execute(
                    "SELECT COALESCE(SUM(msg_count), 0) "
                    "FROM activity_heatmap_buckets "
                    "WHERE guild_id=? AND weekday=?",
                    (guild.id, today_wd),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    out["voice_min_today"] = int(row[0] or 0)
            except Exception:
                pass

            # Prochain stream
            try:
                async with db.execute(
                    "SELECT starts_at, platform FROM stream_schedule "
                    "WHERE guild_id=? AND cancelled=0 AND "
                    "datetime(starts_at) > datetime('now') "
                    "ORDER BY starts_at ASC LIMIT 1",
                    (guild.id,),
                ) as cur:
                    row = await cur.fetchone()
                if row and row[0]:
                    try:
                        dt = datetime.fromisoformat(
                            str(row[0]).replace("Z", "+00:00")
                        )
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if _PARIS_TZ:
                            dt = dt.astimezone(_PARIS_TZ)
                        # Format court : "samedi 21h"
                        days_fr = [
                            "lundi", "mardi", "mercredi", "jeudi",
                            "vendredi", "samedi", "dimanche",
                        ]
                        out["next_stream_str"] = (
                            f"{days_fr[dt.weekday()]} {dt.hour}h"
                        )
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

    return out


def _build_status_text(data: dict) -> str:
    """Choisit un template selon les données dispo et formate.
    Retourne un texte max 128 chars (limite Discord)."""
    # 50/50 : template dynamique ou statique
    if data and random.random() < 0.66:
        # Tente un template dynamique aléatoire dont les data sont dispo
        random.shuffle(STATUS_TEMPLATES_DYNAMIC)
        for tpl, required_keys in STATUS_TEMPLATES_DYNAMIC:
            if all(k in data and data[k] for k in required_keys):
                try:
                    return tpl.format(**data)[:128]
                except (KeyError, ValueError):
                    continue
    # Fallback statique
    return random.choice(STATUS_TEMPLATES_STATIC)[:128]


@tasks.loop(minutes=30)
async def rotator_task():
    """Toutes les 30 min : rotate le status du bot."""
    if _bot is None:
        return
    try:
        guild = _pick_primary_guild()
        data = await _collect_dynamic_data(guild) if guild else {}
        text = _build_status_text(data)
        # Discord activity type : Watching (game), Playing, Listening, etc.
        activity = discord.CustomActivity(name=text)
        await _bot.change_presence(activity=activity)
    except Exception as ex:
        print(f"[status_rotator] {ex}")


@rotator_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "rotator_task",
    "STATUS_TEMPLATES_STATIC",
    "STATUS_TEMPLATES_DYNAMIC",
]
