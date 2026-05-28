"""
stream_watch_party.py — Watch party live (Phase 155 + 163.4 config-based).

🎯 OBJECTIF : quand le créateur du serveur lance un live (Twitch/YouTube),
poster un panel "🔴 LIVE EN COURS" dans le salon que l'owner a désigné,
avec XP/coins ×2 actif pendant toute la durée du live.

Mécanique (Phase 163.4) :
- Plus de salon auto-créé. Owner configure `stream_watch_channel_id`
  via /configure (par défaut 0 = désactivé : le buff XP×2 marche quand
  même, juste pas de panel posté).
- Au start_live :
  • Post un panel V2 épinglé dans le salon configuré
  • Active le flag in-memory pour XP/coins ×2
- À l'end_live :
  • Edit le panel pour marquer "Live terminé"
  • Désactive le buff
  • Le message est unpin 30 min plus tard via cleanup_task

Le buff XP×2 est lu par les autres modules (boss, treasure, etc.) via
`is_stream_buff_active(guild_id) -> bool`.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- on_creator_live_start(guild, platform, stream_url, streamer_name)
- on_creator_live_end(guild)
- is_stream_buff_active(guild_id) -> bool
- get_buff_multiplier(guild_id) -> float

DB tables :
- stream_watch_parties (id PK, guild_id, channel_id, message_id,
                        started_at, ended_at, platform, stream_url)

Config (lu via _db_get) :
- guild_config.stream_watch_channel_id (INTEGER, 0 = désactivé)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Map en mémoire : guild_id → channel_id du watch party actif
_active_parties: dict[int, dict] = {}

PARTY_CHANNEL_PREFIX = "🔴-watching"
AUTO_DELETE_AFTER_MIN = 30


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
                CREATE TABLE IF NOT EXISTS stream_watch_parties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    message_id INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    platform TEXT,
                    stream_url TEXT,
                    streamer_name TEXT,
                    message_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'live'
                )
            """)
            # Phase 163.4 : migration backward-compat — add message_id if missing
            try:
                await db.execute(
                    "ALTER TABLE stream_watch_parties "
                    "ADD COLUMN message_id INTEGER DEFAULT 0"
                )
            except Exception:
                pass  # column déjà là
            # Phase 163.7 : index pour le orphan-scan filter (status, ended_at)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_stream_parties_orphan "
                "ON stream_watch_parties(status, ended_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[stream_watch_party init_db] {ex}")


# ─── Live start ─────────────────────────────────────────────────────────────

async def _get_watch_channel_id(guild_id: int) -> int:
    """Phase 163.4 : lit le salon configuré par l'owner. 0 = désactivé."""
    if _db_get is None:
        return 0
    try:
        data = await _db_get(guild_id)
        return int(data.get("stream_watch_channel_id", 0) or 0)
    except Exception:
        return 0


async def on_creator_live_start(
    guild: discord.Guild, platform: str,
    stream_url: str, streamer_name: str = "Stream",
) -> bool:
    """Appelé par le détecteur de live. Active le buff + poste un panel
    dans le salon configuré (Phase 163.4 : plus d'auto-create de salon)."""
    if not guild or _get_db is None:
        return False
    # Anti-double : si déjà actif
    if guild.id in _active_parties:
        return False
    try:
        # Phase 163.4 : active TOUJOURS le buff in-memory (XP×2 fonctionne
        # même sans salon configuré). Le panel n'est posté que si l'owner
        # a configuré stream_watch_channel_id.
        configured_id = await _get_watch_channel_id(guild.id)
        ch = guild.get_channel(configured_id) if configured_id else None

        msg = None
        if ch and _v2 is not None:
            try:
                LayoutView = _v2['LayoutView']
                v2_title = _v2['v2_title']
                v2_subtitle = _v2['v2_subtitle']
                v2_body = _v2['v2_body']
                v2_divider = _v2['v2_divider']
                v2_container = _v2['v2_container']

                items = [
                    v2_title(f"🔴  LIVE EN COURS — {streamer_name}"),
                    v2_subtitle(
                        f"_Plateforme : **{platform.title()}** · "
                        f"Buff XP×2 actif pendant tout le live_"
                    ),
                    v2_divider(),
                    v2_body(
                        f"**🎮 Regarder le live :**\n"
                        f"{stream_url}"
                    ),
                    v2_divider(),
                    v2_body(
                        "**⚡  BUFF ACTIF pendant le live**\n"
                        "• Tous les coins gagnés sont **× 2**\n"
                        "• XP gagnés sont **× 2**\n"
                        "• Drops saisonniers : **+5%** chance bonus"
                    ),
                    v2_divider(),
                    v2_body(
                        "_Discute du live ici. Le panel sera mis à jour "
                        "à la fin du stream._"
                    ),
                ]

                class _PartyPanel(LayoutView):
                    def __init__(self):
                        super().__init__(timeout=None)
                        self.add_item(v2_container(*items, color=0xFF0000))

                msg = await ch.send(view=_PartyPanel())
                try:
                    await msg.pin()
                except Exception:
                    pass
            except Exception as ex:
                print(f"[stream_watch_party post_panel] {ex}")

        # Log DB (même sans salon configuré, on garde une trace)
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO stream_watch_parties "
                "(guild_id, channel_id, message_id, platform, "
                "stream_url, streamer_name) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild.id, ch.id if ch else 0,
                    msg.id if msg else 0,
                    platform, stream_url, streamer_name,
                ),
            )
            party_id = cur.lastrowid
            await db.commit()

        _active_parties[guild.id] = {
            "party_id": party_id,
            "channel_id": ch.id if ch else 0,
            "message_id": msg.id if msg else 0,
            "started_at": datetime.now(timezone.utc),
            "platform": platform,
            "streamer_name": streamer_name,
        }
        print(
            f"[stream_watch_party] watch party started "
            f"guild={guild.id} ch={ch.id if ch else 'NONE'} "
            f"platform={platform} configured={'yes' if configured_id else 'no'}"
        )
        return True
    except Exception as ex:
        print(f"[stream_watch_party on_creator_live_start] {ex}")
        return False


# ─── Live end ───────────────────────────────────────────────────────────────

async def on_creator_live_end(guild: discord.Guild) -> bool:
    """Marque le live terminé. Le message panel sera unpin 30min plus tard
    via cleanup_task (Phase 163.4 : on n'écrase pas le salon de l'owner)."""
    if not guild or guild.id not in _active_parties:
        return False
    try:
        party = _active_parties[guild.id]
        # Mark end
        if _get_db is not None:
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE stream_watch_parties SET "
                        "ended_at=CURRENT_TIMESTAMP, status='ended' "
                        "WHERE id=?",
                        (party["party_id"],),
                    )
                    await db.commit()
            except Exception:
                pass

        # Phase 163.4 : on poste un récap dans le salon configuré (s'il
        # existe) et on schedule l'unpin. PAS de delete de salon.
        try:
            ch_id = party.get("channel_id", 0)
            ch = guild.get_channel(ch_id) if ch_id else None
            if ch:
                duration = (
                    datetime.now(timezone.utc) - party["started_at"]
                ).total_seconds()
                h = int(duration // 3600)
                m = int((duration % 3600) // 60)
                await ch.send(
                    f"🏁 **Live terminé.** Durée : `{h}h {m}min`. "
                    f"Buff XP×2 désactivé. _Le panel sera dépinglé dans "
                    f"**30 min**._"
                )
        except Exception:
            pass

        # Schedule unpin in 30 min
        party["end_time"] = datetime.now(timezone.utc)
        return True
    except Exception as ex:
        print(f"[stream_watch_party on_creator_live_end] {ex}")
        return False


# ─── Buff check ────────────────────────────────────────────────────────────

def is_stream_buff_active(guild_id: int) -> bool:
    """True si un live est actif → XP/coins ×2."""
    return guild_id in _active_parties


def get_buff_multiplier(guild_id: int) -> float:
    """Multiplicateur à appliquer aux récompenses pendant un live."""
    return 2.0 if is_stream_buff_active(guild_id) else 1.0


# ─── Task : cleanup auto des salons morts ───────────────────────────────────

@tasks.loop(minutes=5)
async def cleanup_task():
    """Toutes les 5min : unpin les messages panel des watch parties
    terminées depuis > 30min (Phase 163.4 : unpin au lieu de delete salon)."""
    try:
        if _bot is None:
            return
        now = datetime.now(timezone.utc)
        to_remove = []
        for gid, party in list(_active_parties.items()):
            end_t = party.get("end_time")
            if end_t and (now - end_t).total_seconds() >= AUTO_DELETE_AFTER_MIN * 60:
                try:
                    g = _bot.get_guild(gid)
                    if g:
                        ch_id = party.get("channel_id", 0)
                        msg_id = party.get("message_id", 0)
                        if ch_id and msg_id:
                            ch = g.get_channel(ch_id)
                            if ch:
                                try:
                                    msg = await ch.fetch_message(msg_id)
                                    await msg.unpin(
                                        reason="Watch party ended +30min"
                                    )
                                except Exception:
                                    pass
                except Exception:
                    pass
                to_remove.append(gid)
        for gid in to_remove:
            _active_parties.pop(gid, None)

        # Phase 163.4 : DB orphan scan — pour les parties terminées dont le
        # bot a été rebooté avant la fin du cooldown 30 min.
        if _get_db is not None:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT id, guild_id, channel_id, message_id "
                        "FROM stream_watch_parties "
                        "WHERE status='ended' AND ended_at IS NOT NULL "
                        "AND ended_at <= datetime('now', '-30 minutes') "
                        "AND (status != 'cleaned' OR status IS NULL) "
                        "LIMIT 50"
                    ) as cur:
                        orphans = await cur.fetchall()
                for orphan_id, gid, ch_id, msg_id in orphans:
                    try:
                        g = _bot.get_guild(int(gid))
                        if g and ch_id and msg_id:
                            ch = g.get_channel(int(ch_id))
                            if ch:
                                try:
                                    msg = await ch.fetch_message(int(msg_id))
                                    await msg.unpin(
                                        reason="Watch party orphan cleanup"
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    # Mark cleaned
                    try:
                        async with _get_db() as db:
                            await db.execute(
                                "UPDATE stream_watch_parties "
                                "SET status='cleaned' WHERE id=?",
                                (orphan_id,),
                            )
                            await db.commit()
                    except Exception:
                        pass
            except Exception as ex:
                print(f"[stream_watch_party orphan_cleanup] {ex}")
    except Exception as ex:
        print(f"[stream_watch_party cleanup_task] {ex}")


@cleanup_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "on_creator_live_start",
    "on_creator_live_end",
    "is_stream_buff_active",
    "get_buff_multiplier",
    "cleanup_task",
]
