"""
twofa_vault.py — Coffre-fort 2FA pour actions économiques critiques (Phase 148).

🎯 OBJECTIF : protéger les comptes piratés contre le drain économique.

Quand un joueur fait une action à fort impact (claim > 5000 coins,
vendre item légendaire, transfer Marketplace > 10000, etc.), le bot DM
un message de confirmation avec un bouton "✅ Je confirme" valide 60s.

Si le hacker a le PC (Discord desktop) mais pas le téléphone, il ne
verra pas le DM → action annulée.

Si l'utilisateur légitime a juste cliqué par erreur, il peut ignorer
le DM → action annulée.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- request_confirmation(member, action_summary, timeout=60) -> bool
- is_protected_threshold(amount, action_type) -> bool

DB tables :
- twofa_confirmations (id PK, guild_id, user_id, action_type,
                       requested_at, confirmed_at, status)

Seuils par défaut :
- claim_coins:     > 5000
- sell_item:       legendary/epic
- transfer:        > 10000
- bank_withdraw:   > 50000

Configurable via une table guild_twofa_config plus tard. Pour V1 c'est
en dur dans ce module.

⚠️ RULES.md : pas de blocage si le user n'a pas activé les DMs (fail
gracieux). On respecte aussi quiet_hours en cas de besoin.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ui import View, Button

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Seuils par défaut
THRESHOLDS = {
    "claim_coins": 5000,
    "transfer_coins": 10000,
    "bank_withdraw": 50000,
    "marketplace_sell": 10000,
    "marketplace_buy": 10000,
    "alliance_vault_withdraw": 5000,
}

# Items rare/legendary = toujours protégés
PROTECTED_RARITIES = {"legendary", "epic", "mythic", "exclusive"}


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
                CREATE TABLE IF NOT EXISTS twofa_confirmations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER NOT NULL,
                    action_type TEXT,
                    action_summary TEXT,
                    amount INTEGER DEFAULT 0,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confirmed_at TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_twofa_user "
                "ON twofa_confirmations(user_id, requested_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[twofa_vault init_db] {ex}")


def is_protected_threshold(amount: int, action_type: str) -> bool:
    """True si le montant dépasse le seuil → 2FA requis."""
    threshold = THRESHOLDS.get(action_type)
    if threshold is None:
        return False
    return amount >= threshold


def is_protected_rarity(rarity: str) -> bool:
    """True si l'item est trop rare pour passer sans 2FA."""
    if not rarity:
        return False
    return rarity.lower() in PROTECTED_RARITIES


class _ConfirmView(View):
    """View privée éphémère avec bouton OUI."""

    def __init__(self, confirmation_id: int, future: asyncio.Future):
        super().__init__(timeout=60)
        self._confirmation_id = confirmation_id
        self._future = future
        b_yes = Button(
            label="✅ Je confirme cette action",
            style=discord.ButtonStyle.success,
        )
        b_no = Button(
            label="❌ Ce n'est pas moi",
            style=discord.ButtonStyle.danger,
        )
        b_yes.callback = self._on_yes
        b_no.callback = self._on_no
        self.add_item(b_yes)
        self.add_item(b_no)

    async def _on_yes(self, i: discord.Interaction):
        try:
            await i.response.send_message(
                "✅ Confirmé. Tu peux fermer ce DM.",
                ephemeral=True,
            )
        except Exception:
            pass
        if not self._future.done():
            self._future.set_result(True)
        self.stop()

    async def _on_no(self, i: discord.Interaction):
        try:
            await i.response.send_message(
                "❌ Action annulée. Si ce n'était pas toi qui as cliqué, "
                "**change immédiatement ton mot de passe Discord** et "
                "active la 2FA (Settings → My Account → Two-Factor).",
                ephemeral=True,
            )
        except Exception:
            pass
        if not self._future.done():
            self._future.set_result(False)
        self.stop()

    async def on_timeout(self):
        if not self._future.done():
            self._future.set_result(False)


async def request_confirmation(
    member: discord.Member,
    action_summary: str,
    action_type: str = "generic",
    amount: int = 0,
    timeout: int = 60,
) -> bool:
    """Envoie un DM 2FA au membre. Renvoie True si confirmé dans la
    fenêtre de temps, False sinon (timeout, refus, ou pas de DM possible).

    Si le user n'accepte pas les DMs → fallback gracieux : on retourne
    True (on autorise quand même, sinon on bloque pour de bon les
    utilisateurs ayant fermé leurs DMs). On log que la 2FA n'a pas pu
    être envoyée.
    """
    if member is None or member.bot:
        return True
    if _get_db is None:
        return True
    try:
        # Insert en DB
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO twofa_confirmations "
                "(guild_id, user_id, action_type, action_summary, amount) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    member.guild.id if member.guild else 0,
                    member.id, action_type, action_summary[:300], amount,
                ),
            )
            conf_id = cur.lastrowid
            await db.commit()

        # DM avec View
        future: asyncio.Future = asyncio.Future()
        view = _ConfirmView(conf_id, future)
        dm_text = (
            f"🔐 **Confirmation requise — {member.guild.name if member.guild else 'Bot'}**\n\n"
            f"Action en cours : {action_summary}\n\n"
            f"_Si ce n'est pas toi, **clique sur ❌** : ton compte est "
            f"peut-être compromis._\n\n"
            f"Tu as **{timeout} secondes**."
        )
        try:
            await member.send(content=dm_text, view=view)
        except (discord.Forbidden, discord.HTTPException):
            # DMs fermés → fail-open (sinon on bloque les actions
            # légitimes). On log mais on continue.
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE twofa_confirmations SET status='dm_blocked' "
                        "WHERE id=?",
                        (conf_id,),
                    )
                    await db.commit()
            except Exception:
                pass
            return True

        # Wait result
        try:
            confirmed = await asyncio.wait_for(future, timeout=timeout + 2)
        except asyncio.TimeoutError:
            confirmed = False

        # Update DB
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE twofa_confirmations SET "
                    "status=?, confirmed_at=CURRENT_TIMESTAMP WHERE id=?",
                    ("confirmed" if confirmed else "denied_or_timeout", conf_id),
                )
                await db.commit()
        except Exception:
            pass

        return confirmed
    except Exception as ex:
        print(f"[twofa_vault request_confirmation] {ex}")
        # Fail-open en cas d'erreur du système 2FA
        return True


__all__ = [
    "setup",
    "init_db",
    "is_protected_threshold",
    "is_protected_rarity",
    "request_confirmation",
    "THRESHOLDS",
    "PROTECTED_RARITIES",
]
