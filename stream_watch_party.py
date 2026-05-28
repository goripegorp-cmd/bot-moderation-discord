"""
stream_watch_party.py — Salon temporaire auto pendant les lives (Phase 155 — E3).

🎯 OBJECTIF : quand le créateur du serveur lance un live (Twitch/YouTube),
créer auto un salon "🔴-watching-now" pour que la communauté discute
ensemble, avec XP/coins ×2 actif pendant le live.

Mécanique :
- Détection via le live_state existant (Phase 26.2) ou via API si dispo.
- Au start_live :
  • Crée un salon `🔴-watching-{name}` temporaire
  • Topic : lien du live + "XP ×2 actif"
  • Panel V2 épinglé avec le lien live + chat encouragé
  • Active un flag `stream_live_buff` dans guild_config
- À l'end_live :
  • Auto-delete le salon après 30 min
  • Désactive le buff
  • Post un récap auto (durée live + commentaires postés dans le salon)

Le buff XP×2 est lu par les autres modules (boss, treasure, etc.) via
`is_stream_buff_active(guild_id) -> bool`.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- on_creator_live_start(guild, platform, stream_url, streamer_name)
- on_creator_live_end(guild)
- is_stream_buff_active(guild_id) -> bool
- get_buff_multiplier(guild_id) -> float

DB tables :
- stream_watch_parties (id PK, guild_id, channel_id, started_at,
                        ended_at, platform, stream_url, message_count)
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
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    platform TEXT,
                    stream_url TEXT,
                    streamer_name TEXT,
                    message_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'live'
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[stream_watch_party init_db] {ex}")


# ─── Live start ─────────────────────────────────────────────────────────────

async def on_creator_live_start(
    guild: discord.Guild, platform: str,
    stream_url: str, streamer_name: str = "Stream",
) -> bool:
    """Appelé par le détecteur de live existant. Crée le watch party."""
    if not guild or _get_db is None:
        return False
    # Anti-double : si déjà actif
    if guild.id in _active_parties:
        return False
    try:
        # Crée le salon
        ch_name = f"{PARTY_CHANNEL_PREFIX}-{streamer_name.lower()[:15]}"
        ch_name = "".join(
            c if c.isalnum() or c in "-🔴" else "-"
            for c in ch_name
        )[:50]

        # Cherche une catégorie events / live / créateur
        category = None
        for cat in guild.categories:
            n = cat.name.lower()
            if "live" in n or "stream" in n or "créateur" in n or "📺" in n:
                category = cat
                break

        try:
            ch = await guild.create_text_channel(
                ch_name,
                category=category,
                topic=(
                    f"🔴 LIVE EN COURS — {streamer_name} sur {platform} · "
                    f"XP ×2 actif pendant le live · {stream_url}"
                ),
                reason=f"Stream watch party : {platform} live",
            )
        except Exception as ex:
            print(f"[stream_watch_party create_channel] {ex}")
            return False

        # Post panel d'accueil
        if _v2 is not None:
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
                        f"Salon temporaire — auto-delete 30min après la fin_"
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
                        "_Discute du live ici. Le salon se ferme tout seul "
                        "30 min après la fin du stream._"
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

        # Log DB
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO stream_watch_parties "
                "(guild_id, channel_id, platform, stream_url, streamer_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild.id, ch.id, platform, stream_url, streamer_name),
            )
            party_id = cur.lastrowid
            await db.commit()

        _active_parties[guild.id] = {
            "party_id": party_id,
            "channel_id": ch.id,
            "started_at": datetime.now(timezone.utc),
            "platform": platform,
            "streamer_name": streamer_name,
        }
        print(
            f"[stream_watch_party] watch party started "
            f"guild={guild.id} ch={ch.id} platform={platform}"
        )
        return True
    except Exception as ex:
        print(f"[stream_watch_party on_creator_live_start] {ex}")
        return False


# ─── Live end ───────────────────────────────────────────────────────────────

async def on_creator_live_end(guild: discord.Guild) -> bool:
    """Marque le live terminé. Le salon se delete 30min plus tard via task."""
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

        # Post message de fin + countdown delete
        try:
            ch = guild.get_channel(party["channel_id"])
            if ch:
                duration = (
                    datetime.now(timezone.utc) - party["started_at"]
                ).total_seconds()
                h = int(duration // 3600)
                m = int((duration % 3600) // 60)
                await ch.send(
                    f"🏁 **Live terminé.** Durée : `{h}h {m}min`.\n"
                    f"_Ce salon sera supprimé dans **30 minutes**._"
                )
        except Exception:
            pass

        # Schedule delete in 30 min
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
    """Toutes les 5min : delete les salons end_live > 30min."""
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
                        ch = g.get_channel(party["channel_id"])
                        if ch:
                            await ch.delete(reason="Watch party ended +30min")
                except Exception:
                    pass
                to_remove.append(gid)
        for gid in to_remove:
            _active_parties.pop(gid, None)
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
