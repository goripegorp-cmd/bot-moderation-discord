"""
honeypot.py — Salon piège anti-bot (Phase 154 — C1).

🎯 OBJECTIF : détecter les self-bots, scrapers et comptes piratés qui
auto-explorent le serveur. Les humains ne voient jamais ce salon, mais
les bots qui crawl la liste des salons y atterrissent.

Mécanique :
1. Crée un salon `🎁-claim-free-nitro` avec perms restrictives :
   - @everyone : view_channel=False
   - Bot lui-même : view_channel=True (pour modérer)
   - Aucun rôle ne peut le voir
2. Le salon a un nom appétissant pour les scrapers
3. Si quelqu'un poste DANS ce salon → compte 99% piraté ou self-bot
4. Auto-action : quarantine instantanée + alerte staff via
   staff_sanction module

Aucun humain légitime ne devrait jamais voir ce salon.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers,
        staff_sanction_module=None)
- ensure_honeypot(guild) -> TextChannel | None
- on_message_hook(message) -> bool (action taken?)

DB tables :
- honeypot_hits (id PK, guild_id, user_id, content, detected_at,
                 action_taken)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_staff_sanction = None

HONEYPOT_NAME = "🎁-claim-free-nitro"
HONEYPOT_TOPIC = "EXCLUSIVE — claim your free Nitro here"


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    staff_sanction_module=None,
):
    global _bot, _get_db, _db_get, _v2, _staff_sanction
    _bot = bot_instance
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
                CREATE TABLE IF NOT EXISTS honeypot_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    content TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    action_taken TEXT
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[honeypot init_db] {ex}")


async def ensure_honeypot(
    guild: discord.Guild,
) -> Optional[discord.TextChannel]:
    """Crée ou récupère le salon honeypot. Visible seulement par le bot."""
    if not guild:
        return None
    try:
        # Recherche existant
        for ch in guild.text_channels:
            if ch.name == HONEYPOT_NAME:
                return ch

        # Crée
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, read_messages=False,
                send_messages=False,
            ),
        }
        try:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, read_messages=True,
                send_messages=False, manage_messages=True,
            )
        except Exception:
            pass

        # Bloque chaque role explicitement
        for role in guild.roles:
            if role == guild.default_role:
                continue
            try:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=False, read_messages=False,
                )
            except Exception:
                pass

        ch = await guild.create_text_channel(
            HONEYPOT_NAME,
            overwrites=overwrites,
            topic=HONEYPOT_TOPIC,
            reason="Anti-bot honeypot (Phase 154)",
        )
        return ch
    except Exception as ex:
        print(f"[honeypot ensure_honeypot] {ex}")
        return None


async def on_message_hook(message: discord.Message) -> bool:
    """Hook depuis bot.py on_message. Si message dans honeypot → action."""
    if not message.guild or message.author.bot:
        return False
    if message.channel.name != HONEYPOT_NAME:
        return False
    try:
        # 100% certain : compte piraté ou self-bot
        await _handle_hit(message)
        return True
    except Exception as ex:
        print(f"[honeypot on_message_hook] {ex}")
        return False


async def _handle_hit(message: discord.Message):
    """Traite un hit honeypot : log + quarantaine + alerte staff."""
    try:
        # Delete message
        try:
            await message.delete()
        except Exception:
            pass

        # Log DB
        if _get_db is not None:
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO honeypot_hits "
                        "(guild_id, user_id, channel_id, content, "
                        "action_taken) VALUES (?, ?, ?, ?, ?)",
                        (
                            message.guild.id, message.author.id,
                            message.channel.id,
                            (message.content or "")[:500],
                            "auto_mute_24h_staff_alert",
                        ),
                    )
                    await db.commit()
            except Exception:
                pass

        # Auto-mute 24h
        try:
            until = datetime.now(timezone.utc) + timedelta(hours=24)
            await message.author.timeout(
                until,
                reason="Honeypot hit — bot/compte piraté détecté",
            )
        except Exception:
            pass

        # DM author (peut être compte piraté légitime)
        try:
            await message.author.send(
                f"🚨 **{message.guild.name}** — Détection automatique "
                f"de comportement suspect.\n\n"
                f"Tu as posté dans un salon qui ne devrait être visible "
                f"par AUCUN utilisateur humain. C'est un piège que nous "
                f"plaçons pour détecter les self-bots et comptes piratés.\n\n"
                f"**Action prise :** Mute 24h.\n\n"
                f"Si ce n'était pas toi :\n"
                f"1. Change ton mot de passe Discord IMMÉDIATEMENT\n"
                f"2. Active la 2FA (Settings → My Account)\n"
                f"3. Déconnecte toutes les sessions inconnues\n\n"
                f"Le staff a été alerté."
            )
        except Exception:
            pass

        # Alerte staff via staff_sanction
        if _staff_sanction is not None:
            try:
                await _staff_sanction.create_sanction_panel(
                    guild=message.guild,
                    target=message.author,
                    reason="🍯 Honeypot — compte 99% piraté ou self-bot",
                    evidence_text=(
                        f"Le user a posté dans le salon piège "
                        f"#{HONEYPOT_NAME} qui est invisible aux humains."
                    ),
                    evidence_channel_id=message.channel.id,
                    auto_action_taken="Mute auto 24h",
                    source="honeypot",
                )
            except Exception as ex:
                print(f"[honeypot notify staff] {ex}")

        # DM owner aussi (critique)
        try:
            owner = (
                message.guild.owner or
                await message.guild.fetch_member(message.guild.owner_id)
            )
            if owner:
                await owner.send(
                    f"🍯 **HONEYPOT HIT — {message.guild.name}**\n\n"
                    f"User : {message.author.mention} "
                    f"(`{message.author.name}` · ID `{message.author.id}`)\n"
                    f"A posté dans le salon piège **#{HONEYPOT_NAME}**.\n\n"
                    f"Probablement un **self-bot** ou un **compte piraté**. "
                    f"Action auto : mute 24h. Panel staff sanction créé."
                )
        except Exception:
            pass
    except Exception as ex:
        print(f"[honeypot _handle_hit] {ex}")


__all__ = [
    "setup",
    "init_db",
    "ensure_honeypot",
    "on_message_hook",
]
