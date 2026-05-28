"""
anti_token_leak.py — Détecteur de tokens Discord leakés en clair (Phase 166.1).

🎯 OBJECTIF : quand un user poste son propre token (ou celui d'un bot)
en clair dans le chat (erreur classique de dev débutant), le bot :
1. Supprime le message immédiatement.
2. DM l'auteur : "ton token vient d'être posté en clair, change-le NOW".
3. Alerte staff via dm_digest.send_urgent_now.

Patterns détectés (format token Discord 2026) :
- Bot tokens : 24+ chars . 6 chars . 27+ chars  (ex: ODE...Y.G7...x.Pf...QM)
- User tokens : 26+ chars . 6 chars . 38+ chars
- MFA tokens : "mfa." + 84 chars

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers,
        staff_sanction_module=None)
- init_db()
- on_message_hook(message) -> bool (action prise ?)

DB :
- token_leaks (id PK, guild_id, user_id, detected_at, token_preview,
               action_taken)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_staff_sanction = None

# Patterns Discord token (2026 — formats actuels)
TOKEN_PATTERNS = [
    # MFA token : mfa.XXX (84 chars suite)
    re.compile(r"\bmfa\.[A-Za-z0-9_\-]{20,}"),
    # Bot token : 3 segments base64-url séparés par "." — pattern strict
    # Format : <24+>.<6>.<27+> (sans espaces autour des points)
    re.compile(r"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,}\b"),
]


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
                CREATE TABLE IF NOT EXISTS token_leaks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    token_preview TEXT,
                    action_taken TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_leaks_guild "
                "ON token_leaks(guild_id, detected_at DESC)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[anti_token_leak init_db] {ex}")


def _scan_for_tokens(text: str) -> Optional[str]:
    """Retourne le 1er match token trouvé (preview 12 char + '...') ou None."""
    if not text:
        return None
    for pat in TOKEN_PATTERNS:
        m = pat.search(text)
        if m:
            tok = m.group(0)
            # Preview : 12 premiers chars + ... (assez pour reconnaître le format,
            # pas assez pour réutiliser)
            return tok[:12] + "..." if len(tok) > 15 else tok[:8] + "..."
    return None


async def on_message_hook(message: discord.Message) -> bool:
    """Hook on_message. Si un token est détecté, action immédiate.
    Retourne True si une action a été prise."""
    if not message.guild or message.author.bot:
        return False
    content = message.content or ""
    if len(content) < 30:
        return False  # trop court pour contenir un token valide

    preview = _scan_for_tokens(content)
    if not preview:
        return False

    # ACTION 1 : delete message immédiatement
    deleted = False
    try:
        await message.delete()
        deleted = True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        pass

    # ACTION 2 : log DB
    if _get_db is not None:
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO token_leaks "
                    "(guild_id, user_id, channel_id, token_preview, "
                    "action_taken) VALUES (?, ?, ?, ?, ?)",
                    (
                        message.guild.id, message.author.id,
                        message.channel.id, preview,
                        "message_deleted" if deleted else "delete_failed",
                    ),
                )
                await db.commit()
        except Exception:
            pass

    # ACTION 3 : DM l'auteur — éducatif, pas punitif
    dm_text = (
        f"🚨 **Token Discord détecté — {message.guild.name}**\n\n"
        f"Tu viens de poster ce qui ressemble à un **token Discord** "
        f"en clair dans le chat (preview : `{preview}`).\n\n"
        f"**Action immédiate à prendre :**\n"
        f"1. Va dans Settings → Developer Portal\n"
        f"2. Régénère le token (Reset Token)\n"
        f"3. Update partout où tu utilisais l'ancien\n\n"
        f"**Pourquoi c'est grave :** un token donne contrôle TOTAL d'un "
        f"bot ou compte. Quelqu'un qui a vu le message peut prendre ton "
        f"bot/compte en otage.\n\n"
        f"Ton message a été supprimé pour protéger ton accès. "
        f"Aucune sanction prise — c'est juste une protection."
    )
    try:
        # Route via dm_digest.send_urgent_now si dispo
        sent = False
        try:
            import dm_digest as _dm_dig
            if _dm_dig and hasattr(_dm_dig, "send_urgent_now"):
                sent = await _dm_dig.send_urgent_now(
                    message.author, dm_text
                )
        except Exception:
            sent = False
        if not sent:
            try:
                await message.author.send(dm_text)
            except Exception:
                pass
    except Exception:
        pass

    # ACTION 4 : alerte staff (informational, pas de sanction auto)
    if _staff_sanction is not None:
        try:
            await _staff_sanction.create_sanction_panel(
                guild=message.guild,
                target=message.author,
                reason="🚨 Token Discord posté en clair (auto-deleted)",
                evidence_text=(
                    f"Pattern token détecté dans #{message.channel.name}. "
                    f"Preview : `{preview}` (le full token n'est PAS stocké). "
                    f"Action auto : message supprimé + DM éducatif à "
                    f"l'auteur. Aucune sanction recommandée — c'est juste "
                    f"un accident de débutant."
                ),
                evidence_channel_id=message.channel.id,
                auto_action_taken=(
                    "Message supprimé + DM éducatif"
                ),
                source="anti_token_leak",
            )
        except Exception as ex:
            print(f"[anti_token_leak staff alert] {ex}")

    return True


__all__ = [
    "setup",
    "init_db",
    "on_message_hook",
]
