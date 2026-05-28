"""
spotlight_quality.py — Quand un message reçoit 5+ ⭐, repost dans #highlights
(Phase 166.4).

🎯 OBJECTIF : récompenser le contenu de qualité (drôle, utile, beau) sans
système d'amitié. Si 5+ membres réagissent ⭐ à un message, le bot le
republie dans le salon highlights configuré.

Respecte RULES.md : aucun système romantique / friend list / hug.
C'est juste de la reconnaissance qualitative de contenu.

Mécanique :
- on_raw_reaction_add : si emoji == ⭐
- Fetch message + compte total ⭐
- Si >= STAR_THRESHOLD ET pas déjà spotlighted :
  - Repost dans `spotlight_channel_id` (configurable)
  - INSERT spotlighted_messages pour anti-doublon
- Anti-self : l'auteur ne compte pas dans ses propres ⭐

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- on_reaction_hook(payload) -> bool

DB :
- spotlighted_messages (guild_id, channel_id, message_id PRIMARY KEY,
                        spotlight_msg_id, spotlight_at)

Config :
- guild_config.spotlight_channel_id (INTEGER, 0 = désactivé)
- guild_config.spotlight_threshold (INTEGER, default 5)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

STAR_EMOJI = "⭐"
DEFAULT_STAR_THRESHOLD = 5


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
                CREATE TABLE IF NOT EXISTS spotlighted_messages (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    author_id INTEGER,
                    star_count INTEGER DEFAULT 0,
                    spotlight_msg_id INTEGER,
                    spotlight_channel_id INTEGER,
                    spotlight_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, message_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[spotlight_quality init_db] {ex}")


async def _get_spotlight_config(guild_id: int) -> dict:
    """Lit la config spotlight pour cette guild."""
    out = {"channel_id": 0, "threshold": DEFAULT_STAR_THRESHOLD}
    if _db_get is None:
        return out
    try:
        cfg_data = await _db_get(guild_id)
        out["channel_id"] = int(cfg_data.get("spotlight_channel_id", 0) or 0)
        out["threshold"] = int(
            cfg_data.get("spotlight_threshold", DEFAULT_STAR_THRESHOLD)
            or DEFAULT_STAR_THRESHOLD
        )
    except Exception:
        pass
    return out


async def _already_spotlighted(guild_id: int, message_id: int) -> bool:
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM spotlighted_messages "
                "WHERE guild_id=? AND message_id=?",
                (guild_id, message_id),
            ) as cur:
                return (await cur.fetchone()) is not None
    except Exception:
        return False


async def on_reaction_hook(payload: discord.RawReactionActionEvent) -> bool:
    """Hook on_raw_reaction_add. Si star threshold atteint, repost dans
    le salon spotlight configuré."""
    if _bot is None or _get_db is None:
        return False
    # Filtre emoji
    if str(payload.emoji) != STAR_EMOJI:
        return False
    if not payload.guild_id:
        return False

    cfg = await _get_spotlight_config(payload.guild_id)
    if cfg["channel_id"] == 0:
        return False  # spotlight désactivé

    # Anti-doublon early-out
    if await _already_spotlighted(payload.guild_id, payload.message_id):
        return False

    guild = _bot.get_guild(payload.guild_id)
    if not guild:
        return False
    spotlight_ch = guild.get_channel(cfg["channel_id"])
    if not spotlight_ch:
        return False

    # Fetch message original
    try:
        src_ch = guild.get_channel(payload.channel_id)
        if not src_ch:
            return False
        msg = await src_ch.fetch_message(payload.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False

    if msg.author.bot:
        return False

    # Compte les ⭐ (en excluant l'auteur lui-même + bots)
    star_count = 0
    for reaction in msg.reactions:
        if str(reaction.emoji) != STAR_EMOJI:
            continue
        try:
            async for user in reaction.users():
                if user.bot:
                    continue
                if user.id == msg.author.id:
                    continue  # anti-self-star
                star_count += 1
        except Exception:
            star_count = reaction.count  # fallback approximatif
        break

    if star_count < cfg["threshold"]:
        return False

    # SPOTLIGHT — repost dans le salon configuré
    try:
        # Insert AVANT le repost pour éviter race condition si plusieurs
        # réactions arrivent en parallèle
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO spotlighted_messages "
                "(guild_id, channel_id, message_id, author_id, "
                "star_count, spotlight_channel_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    payload.guild_id, payload.channel_id, payload.message_id,
                    msg.author.id, star_count, cfg["channel_id"],
                ),
            )
            inserted = cur.rowcount > 0
            await db.commit()
        if not inserted:
            return False  # déjà fait par une autre task en parallèle

        # Build le message highlight
        content_preview = (msg.content or "")[:800]
        attach_str = ""
        if msg.attachments:
            attach_str = f"\n📎 {len(msg.attachments)} pièce(s) jointe(s)"

        jump_url = msg.jump_url
        highlight_content = (
            f"⭐ **{star_count} ⭐** dans {msg.channel.mention}\n\n"
            f"_{msg.author.mention} a écrit :_\n"
            f">>> {content_preview}{attach_str}\n\n"
            f"[Voir le message original]({jump_url})"
        )

        # Cap: max 1 mention (l'auteur)
        sent = await spotlight_ch.send(
            content=highlight_content,
            allowed_mentions=discord.AllowedMentions(
                users=[msg.author], everyone=False, roles=False,
            ),
        )

        # Update le spotlight_msg_id
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE spotlighted_messages SET spotlight_msg_id=? "
                    "WHERE guild_id=? AND message_id=?",
                    (sent.id, payload.guild_id, payload.message_id),
                )
                await db.commit()
        except Exception:
            pass

        return True
    except Exception as ex:
        print(f"[spotlight_quality post] {ex}")
        return False


__all__ = [
    "setup",
    "init_db",
    "on_reaction_hook",
    "STAR_EMOJI",
    "DEFAULT_STAR_THRESHOLD",
]
