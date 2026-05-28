"""
honeypot.py — Salon piège anti-bot (Phase 154 — C1, Phase 158 config-based).

🎯 OBJECTIF : détecter les self-bots, scrapers et comptes piratés qui
auto-explorent le serveur. Si quelqu'un poste dans LE salon que l'owner
a désigné comme honeypot → compte 99% piraté ou self-bot.

Mécanique (Phase 158) :
1. Plus de salon auto-créé. L'owner CRÉE le salon avec le nom qu'il veut
   (suggéré : `🎁-claim-free-nitro`, `🍯-honeypot`, ou n'importe quel
   autre nom appétissant pour les scrapers).
2. Owner configure le salon via /configure → Logs → Salons sécurité.
3. Le salon doit être configuré pour être invisible à @everyone et tous
   les rôles non-staff.
4. Quand un user poste dedans → mute 1h + alerte staff_sanction + DM
   owner.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers,
        staff_sanction_module=None, db_get_cfg=None)
- get_honeypot_channel_id(guild_id) -> int (0 si non configuré)
- on_message_hook(message) -> bool (action taken?)

DB tables :
- honeypot_hits (id PK, guild_id, user_id, content, detected_at,
                 action_taken)

Config (lu via cfg() de bot.py) :
- guild_config.honeypot_channel_id (INTEGER, 0 = désactivé)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None  # Fonction async pour lire la config (cfg de bot.py)
_v2 = None
_staff_sanction = None


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


async def get_honeypot_channel_id(guild_id: int) -> int:
    """Lit l'ID du salon honeypot configuré par l'owner. 0 = désactivé."""
    if _db_get is None:
        return 0
    try:
        data = await _db_get(guild_id)
        return int(data.get("honeypot_channel_id", 0) or 0)
    except Exception:
        return 0


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
            # Phase 163.7 : index pour les requêtes par guild + récent
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_honeypot_hits_guild "
                "ON honeypot_hits(guild_id, detected_at DESC)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[honeypot init_db] {ex}")


async def apply_honeypot_perms(
    channel: discord.TextChannel,
) -> dict:
    """Applique les permissions honeypot sur un salon configuré.
    Owner appelle ceci via /configure pour bien verrouiller le salon
    (@everyone deny + tous rôles deny + bot allow).

    Retourne {success, errors}.
    """
    out = {"success": False, "errors": []}
    if not channel:
        out["errors"].append("Salon invalide")
        return out
    guild = channel.guild
    try:
        # @everyone deny
        await channel.set_permissions(
            guild.default_role,
            view_channel=False, read_messages=False,
            send_messages=False,
            reason="Honeypot setup",
        )
        # Bot allow
        try:
            await channel.set_permissions(
                guild.me,
                view_channel=True, read_messages=True,
                send_messages=False, manage_messages=True,
                reason="Honeypot bot perms",
            )
        except Exception:
            pass
        # Tous les rôles deny
        for role in guild.roles:
            if role == guild.default_role:
                continue
            try:
                await channel.set_permissions(
                    role,
                    view_channel=False, read_messages=False,
                    reason="Honeypot deny role",
                )
            except Exception as ex_r:
                out["errors"].append(f"role {role.name}: {ex_r}")
        out["success"] = True
        return out
    except Exception as ex:
        out["errors"].append(str(ex))
        return out


async def on_message_hook(message: discord.Message) -> bool:
    """Hook depuis bot.py on_message. Si message dans LE salon honeypot
    configuré → action immédiate."""
    if not message.guild or message.author.bot:
        return False
    try:
        configured_id = await get_honeypot_channel_id(message.guild.id)
        if configured_id == 0:
            return False  # honeypot désactivé
        if message.channel.id != configured_id:
            return False  # pas le salon honeypot
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
        # Phase 163.4 : utilise message.channel.name (Phase 158 = nom configurable
        # par l'owner, donc plus de constante HONEYPOT_NAME qui causait NameError).
        ch_name = message.channel.name if message.channel else "honeypot"
        if _staff_sanction is not None:
            try:
                await _staff_sanction.create_sanction_panel(
                    guild=message.guild,
                    target=message.author,
                    reason="🍯 Honeypot — compte 99% piraté ou self-bot",
                    evidence_text=(
                        f"Le user a posté dans le salon piège "
                        f"#{ch_name} qui est invisible aux humains."
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
                    f"A posté dans le salon piège **#{ch_name}**.\n\n"
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
    "get_honeypot_channel_id",
    "apply_honeypot_perms",
    "on_message_hook",
]
