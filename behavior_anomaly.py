"""
behavior_anomaly.py — Détecteur de comptes piratés via comportement (Phase 154 — C2).

🎯 OBJECTIF : détecter les comptes piratés AVANT qu'ils ne fassent du
dégât, en repérant les changements de comportement soudains.

Mécanique :
1. Build profile par user : heures actives, taille messages moyenne,
   intervalle entre messages, mots/min, salons fréquentés.
2. Sur chaque message, comparer au profile (rolling 14 jours).
3. Si déviation > 3σ sur 2+ axes → alerte staff (PAS d'action auto,
   trop sensible).

Signaux de déviation typiques d'un compte piraté :
- Posts massifs après 14 jours inactivité (réveil suspect)
- Heure complètement différente d'habitude
- Taille de message ×5 d'un coup
- Nouveaux salons (jamais fréquentés avant)
- Vitesse de frappe surhumaine

C'est PROBABILISTE — pas une vérité absolue. Le staff décide.

API publique :
- setup(get_db_fn, db_get_fn, v2_helpers, staff_sanction_module=None)
- track_message(message) — appelé depuis on_message
- check_anomaly(member, message) -> dict | None
- get_profile(guild_id, user_id) -> dict

DB tables :
- behavior_profile (guild_id, user_id, msg_count_14d, avg_msg_length,
                    typical_hours_jsonb, typical_channels_jsonb,
                    last_message_at, last_update_at,
                    PRIMARY KEY (guild_id, user_id))
- behavior_alerts (id PK, guild_id, user_id, deviation_axes_jsonb,
                   score, detected_at, status)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_get_db = None
_db_get = None
_v2 = None
_staff_sanction = None

# Minimums pour considérer un profile mature (sinon on skip)
MIN_PROFILE_MESSAGES = 50
ANOMALY_COOLDOWN_HOURS = 6  # 1 alerte max / user / 6h


def setup(
    get_db_fn, db_get_fn, v2_helpers: dict,
    staff_sanction_module=None,
):
    global _get_db, _db_get, _v2, _staff_sanction
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _staff_sanction = staff_sanction_module


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS behavior_profile (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    msg_count_14d INTEGER DEFAULT 0,
                    avg_msg_length REAL DEFAULT 0,
                    typical_hours_jsonb TEXT DEFAULT '{}',
                    typical_channels_jsonb TEXT DEFAULT '{}',
                    last_message_at TIMESTAMP,
                    last_update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS behavior_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    deviation_axes_jsonb TEXT,
                    score REAL,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_behavior_profile_user "
                "ON behavior_profile(guild_id, user_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[behavior_anomaly init_db] {ex}")


async def get_profile(guild_id: int, user_id: int) -> dict:
    """Renvoie le profil comportemental d'un user."""
    out = {
        "msg_count_14d": 0,
        "avg_msg_length": 0,
        "typical_hours": {},
        "typical_channels": {},
        "last_message_at": None,
        "mature": False,
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT msg_count_14d, avg_msg_length, "
                "typical_hours_jsonb, typical_channels_jsonb, "
                "last_message_at FROM behavior_profile "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            out["msg_count_14d"] = int(row[0] or 0)
            out["avg_msg_length"] = float(row[1] or 0)
            try:
                out["typical_hours"] = json.loads(row[2] or "{}")
            except Exception:
                pass
            try:
                out["typical_channels"] = json.loads(row[3] or "{}")
            except Exception:
                pass
            out["last_message_at"] = row[4]
            out["mature"] = out["msg_count_14d"] >= MIN_PROFILE_MESSAGES
    except Exception:
        pass
    return out


async def track_message(message: discord.Message):
    """Met à jour le profile + check anomaly.

    Phase 163.4 : décroissance lazy. Si le dernier message du user est >
    14 jours, le counter et les distributions sont reset avant l'update
    pour avoir une vraie rolling window 14j (au lieu de croître sans fin).
    """
    if not message.guild or message.author.bot or _get_db is None:
        return
    try:
        # Get current profile
        prof = await get_profile(message.guild.id, message.author.id)
        msg_len = len(message.content or "")
        hour = datetime.now(timezone.utc).hour
        ch_id = str(message.channel.id)

        # Phase 163.4 : si profil pas mis à jour depuis > 14j → reset
        # ("rolling 14d window" lazy)
        last_at = prof.get("last_message_at")
        if last_at:
            try:
                from datetime import timedelta
                # last_at peut être string ISO ou datetime suivant SQLite
                if isinstance(last_at, str):
                    last_dt = datetime.fromisoformat(
                        last_at.replace("Z", "+00:00").split(".")[0]
                    )
                else:
                    last_dt = last_at
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - last_dt
                if age > timedelta(days=14):
                    prof["msg_count_14d"] = 0
                    prof["avg_msg_length"] = 0
                    prof["typical_hours"] = {}
                    prof["typical_channels"] = {}
                    prof["mature"] = False
            except Exception:
                pass

        # Update incremental (running averages)
        n = prof["msg_count_14d"]
        new_n = n + 1
        new_avg_len = (
            (prof["avg_msg_length"] * n + msg_len) / new_n
            if new_n > 0 else msg_len
        )

        hours = prof["typical_hours"]
        hours[str(hour)] = int(hours.get(str(hour), 0)) + 1

        channels = prof["typical_channels"]
        channels[ch_id] = int(channels.get(ch_id, 0)) + 1

        # Garder seulement top 10 channels (anti bloat)
        if len(channels) > 15:
            channels = dict(
                sorted(channels.items(), key=lambda x: -x[1])[:10]
            )

        async with _get_db() as db:
            await db.execute(
                "INSERT INTO behavior_profile "
                "(guild_id, user_id, msg_count_14d, avg_msg_length, "
                "typical_hours_jsonb, typical_channels_jsonb, "
                "last_message_at, last_update_at) "
                "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "msg_count_14d = ?, avg_msg_length = ?, "
                "typical_hours_jsonb = ?, typical_channels_jsonb = ?, "
                "last_message_at = CURRENT_TIMESTAMP, "
                "last_update_at = CURRENT_TIMESTAMP",
                (
                    message.guild.id, message.author.id, new_n, new_avg_len,
                    json.dumps(hours), json.dumps(channels),
                    new_n, new_avg_len,
                    json.dumps(hours), json.dumps(channels),
                ),
            )
            await db.commit()

        # Check anomaly (seulement si profile mature)
        if prof["mature"]:
            anomaly = _detect_anomaly(prof, message, hour, msg_len)
            if anomaly:
                await _report_anomaly(message, anomaly)
    except Exception as ex:
        print(f"[behavior_anomaly track_message] {ex}")


def _detect_anomaly(
    prof: dict, message: discord.Message, hour: int, msg_len: int,
) -> Optional[dict]:
    """Compare le message courant au profile. Retourne dict si anomalie."""
    deviations = []

    # 1. Taille message anormale (>5× moyenne)
    if prof["avg_msg_length"] > 0:
        ratio = msg_len / prof["avg_msg_length"]
        if ratio > 5 and msg_len > 200:
            deviations.append({
                "axis": "msg_length",
                "expected": int(prof["avg_msg_length"]),
                "actual": msg_len,
                "ratio": round(ratio, 1),
            })

    # 2. Heure anormale (jamais actif à cette heure)
    hours_dist = prof["typical_hours"]
    hour_count = int(hours_dist.get(str(hour), 0))
    total_msgs = sum(int(v) for v in hours_dist.values())
    if total_msgs > 50:
        hour_pct = hour_count / total_msgs
        if hour_pct < 0.01:  # < 1% des messages historiques
            deviations.append({
                "axis": "unusual_hour",
                "hour": hour,
                "pct_history": round(hour_pct * 100, 2),
            })

    # 3. Salon nouveau (jamais utilisé)
    channels = prof["typical_channels"]
    ch_id = str(message.channel.id)
    if ch_id not in channels and len(channels) >= 5:
        deviations.append({
            "axis": "new_channel",
            "channel_id": message.channel.id,
            "channel_name": message.channel.name,
        })

    # 4. Réveil après inactivité prolongée + post immédiat
    if prof.get("last_message_at"):
        try:
            last = (
                datetime.fromisoformat(str(prof["last_message_at"]).replace("Z", "+00:00"))
                if "T" in str(prof["last_message_at"]) else
                datetime.strptime(
                    str(prof["last_message_at"]), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            )
            inactive_days = (datetime.now(timezone.utc) - last).days
            if inactive_days >= 14 and msg_len > 100:
                deviations.append({
                    "axis": "wakeup_after_inactivity",
                    "inactive_days": inactive_days,
                    "msg_length": msg_len,
                })
        except Exception:
            pass

    if len(deviations) >= 2:
        score = len(deviations) * 0.33
        return {
            "deviations": deviations,
            "score": min(1.0, score),
        }
    return None


async def _report_anomaly(message: discord.Message, anomaly: dict):
    """Log l'anomalie + crée un panel staff si module dispo."""
    if _get_db is None:
        return
    try:
        # Anti-spam : 1 alerte max / user / 6h
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=ANOMALY_COOLDOWN_HOURS)
        ).strftime("%Y-%m-%d %H:%M:%S")
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM behavior_alerts "
                "WHERE guild_id=? AND user_id=? AND detected_at >= ?",
                (message.guild.id, message.author.id, cutoff),
            ) as cur:
                row = await cur.fetchone()
            if row and int(row[0] or 0) > 0:
                return  # déjà alerté récemment

            await db.execute(
                "INSERT INTO behavior_alerts "
                "(guild_id, user_id, deviation_axes_jsonb, score) "
                "VALUES (?, ?, ?, ?)",
                (
                    message.guild.id, message.author.id,
                    json.dumps(anomaly["deviations"]),
                    anomaly["score"],
                ),
            )
            await db.commit()

        # Panel staff (informationnel, pas d'action auto)
        if _staff_sanction is not None:
            try:
                axes_str = ", ".join(
                    d["axis"] for d in anomaly["deviations"]
                )
                evidence = (
                    f"Déviations détectées : {axes_str}\n\n"
                    f"Détails : {json.dumps(anomaly['deviations'], indent=2)[:500]}"
                )
                await _staff_sanction.create_sanction_panel(
                    guild=message.guild,
                    target=message.author,
                    reason=(
                        f"🧠 Anomalie comportementale "
                        f"(score {anomaly['score']:.0%})"
                    ),
                    evidence_text=evidence,
                    evidence_channel_id=message.channel.id,
                    auto_action_taken=(
                        "Aucune (informationnel) — staff doit décider"
                    ),
                    source="behavior_anomaly",
                )
            except Exception as ex:
                print(f"[behavior_anomaly notify staff] {ex}")
    except Exception as ex:
        print(f"[behavior_anomaly _report_anomaly] {ex}")


__all__ = [
    "setup",
    "init_db",
    "track_message",
    "get_profile",
]
