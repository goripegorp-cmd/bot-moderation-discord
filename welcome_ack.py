"""
welcome_ack.py — Reconnaissance discrète au 1er message (Phase 166.3).

🎯 OBJECTIF : quand un nouveau membre poste son TOUT PREMIER message ever
sur le serveur, le bot réagit avec 👋. Une seule fois, jamais après.

Pas de ping. Pas de spam. Juste une micro-reconnaissance qui dit
"je t'ai vu, bienvenue parmi nous".

Mécanique :
- Table `welcomed_users` (guild_id, user_id PK)
- Sur on_message : check si user_id NOT IN welcomed_users
  - Si oui → add_reaction("👋") + INSERT
  - Si non → rien

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- on_message_hook(message) -> bool (action prise ?)
"""
from __future__ import annotations

from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None


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
                CREATE TABLE IF NOT EXISTS welcomed_users (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    welcomed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[welcome_ack init_db] {ex}")


async def on_message_hook(message: discord.Message) -> bool:
    """Hook on_message. Si c'est le 1er message ever de ce user sur ce
    serveur, ajoute une réaction 👋 et marque comme welcomed."""
    if not message.guild or message.author.bot or _get_db is None:
        return False
    # Owner et super-owner ne sont jamais "nouveaux"
    if message.author.id == message.guild.owner_id:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM welcomed_users "
                "WHERE guild_id=? AND user_id=?",
                (message.guild.id, message.author.id),
            ) as cur:
                already = await cur.fetchone()
        if already:
            return False
        # Première fois : INSERT (idempotent via PK) AVANT la réaction
        # pour éviter race condition double-réaction si l'user poste 2 msgs
        # en parallèle
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO welcomed_users "
                "(guild_id, user_id) VALUES (?, ?)",
                (message.guild.id, message.author.id),
            )
            await db.commit()
        # owner 2026-06-29 : 👋 UNIQUEMENT dans un salon où @everyone peut écrire (jamais
        # annonce/ticket/staff). Garde minimale sans dépendance externe. FAIL-SAFE.
        try:
            if not message.channel.permissions_for(message.guild.default_role).send_messages:
                return False
        except Exception:
            return False
        # Réaction 👋 — silencieuse, pas de ping, fail-open
        try:
            await message.add_reaction("👋")
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            pass
        return True
    except Exception as ex:
        print(f"[welcome_ack on_message_hook] {ex}")
        return False


__all__ = [
    "setup",
    "init_db",
    "on_message_hook",
]
