"""
webhook_leak.py — Détecteur de fuite de webhooks Discord (Phase 147).

🎯 OBJECTIF : intercepter et neutraliser les fuites de webhooks Discord.

Un webhook Discord c'est un secret : qui que ce soit qui a l'URL peut
envoyer des messages au nom du serveur (spam, phishing, harcèlement,
nuke). Quand un dev colle par erreur sa config dans le chat, ou qu'un
screenshot mal cropped contient l'URL, c'est game over.

Stratégie :
1. **Scan inline** : hook on_message early. Pattern strict
   `discord(?:app)?\.com/api/webhooks/\d+/[\w-]+`.
2. **Action immédiate** : delete message en < 1s, DM author warning.
3. **Auto-revoke** : si le bot a le scope `WEBHOOKS`, tente DELETE
   sur l'URL leaked → invalide le webhook (les attaquants ne peuvent
   plus l'utiliser).
4. **Alerte staff** : panel staff_sanction avec contexte complet.

Le scan inclut aussi les embeds (description, footer, author.name)
parce que c'est un endroit où un attaquant pourrait planquer une URL.

DB tables :
- webhook_leak_log (id PK, guild_id, user_id, leaked_url_redacted,
                    detected_at, auto_revoked, channel_id)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, staff_sanction=None)
- scan_message(message) -> list[matched_urls]
- on_message_hook(message) -> bool (action taken?)

⚠️ RULES.md : pas de sanction auto sur l'user (peut être victime d'un
collage par erreur). DM warning + alerte staff.
"""
from __future__ import annotations

import re
import aiohttp
from datetime import datetime
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_staff_sanction = None

# Pattern Discord webhooks (strict)
_RX_WEBHOOK = re.compile(
    r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com"
    r"/api/(?:v\d+/)?webhooks/(\d+)/([\w-]+)",
    re.IGNORECASE,
)


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
                CREATE TABLE IF NOT EXISTS webhook_leak_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    leaked_url_redacted TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    auto_revoked INTEGER DEFAULT 0,
                    revoke_status TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_webhook_leak_recent "
                "ON webhook_leak_log(guild_id, detected_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[webhook_leak init_db] {ex}")


# ─── Scan ──────────────────────────────────────────────────────────────────

def scan_message(message: discord.Message) -> list[tuple[str, int, str]]:
    """Renvoie liste de (url_full, webhook_id, token)."""
    out = []
    if not message:
        return out

    texts = []
    if message.content:
        texts.append(message.content)
    if message.embeds:
        for e in message.embeds:
            if e.description:
                texts.append(e.description)
            if e.title:
                texts.append(e.title)
            if e.footer and e.footer.text:
                texts.append(e.footer.text)
            if e.author and e.author.name:
                texts.append(e.author.name)
            for field in e.fields or []:
                if field.value:
                    texts.append(field.value)

    combined = "\n".join(texts)
    for m in _RX_WEBHOOK.finditer(combined):
        url = m.group(0)
        wid = int(m.group(1))
        token = m.group(2)
        out.append((url, wid, token))
    return out


def _redact_url(url: str) -> str:
    """Garde le webhook_id mais masque le token (pour les logs)."""
    m = _RX_WEBHOOK.search(url)
    if not m:
        return "***redacted***"
    wid = m.group(1)
    return f"discord.com/api/webhooks/{wid}/***"


async def _try_revoke_webhook(webhook_id: int, token: str) -> tuple[bool, str]:
    """Tente de révoquer le webhook via DELETE sur son URL.
    Discord permet à n'importe qui ayant le token de delete le webhook.
    Renvoie (success, status_text)."""
    try:
        url = (
            f"https://discord.com/api/v10/webhooks/{webhook_id}/{token}"
        )
        async with aiohttp.ClientSession() as session:
            async with session.delete(url, timeout=10) as resp:
                if resp.status in (200, 204):
                    return (True, "revoked_204")
                elif resp.status == 404:
                    return (True, "already_invalid_404")
                else:
                    return (False, f"http_{resp.status}")
    except Exception as ex:
        return (False, f"error: {ex}")


# ─── Action handler ─────────────────────────────────────────────────────────

async def on_message_hook(message: discord.Message) -> bool:
    """Hook depuis bot.py on_message. Retourne True si action prise."""
    if not message.guild or message.author.bot:
        return False
    if _get_db is None:
        return False
    try:
        matches = scan_message(message)
        if not matches:
            return False

        # 1) Delete message immédiatement
        deleted = False
        try:
            await message.delete()
            deleted = True
        except Exception as ex:
            print(f"[webhook_leak delete] {ex}")

        # 2) Auto-revoke chaque webhook leaked
        revoke_results = []
        for url, wid, token in matches:
            ok, status = await _try_revoke_webhook(wid, token)
            revoke_results.append((url, wid, ok, status))

        # 3) Log DB
        async with _get_db() as db:
            for url, wid, ok, status in revoke_results:
                await db.execute(
                    "INSERT INTO webhook_leak_log "
                    "(guild_id, user_id, channel_id, leaked_url_redacted, "
                    "auto_revoked, revoke_status) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        message.guild.id, message.author.id,
                        message.channel.id, _redact_url(url),
                        1 if ok else 0, status,
                    ),
                )
            await db.commit()

        # 4) DM author (peut être un dev qui a leaké par erreur,
        #    ou un attaquant qui leak quelqu'un d'autre)
        try:
            revoked_count = sum(1 for _, _, ok, _ in revoke_results if ok)
            dm_text = (
                f"⚠️ **{message.guild.name}** — Webhook leak détecté.\n\n"
                f"Ton message contenait **{len(matches)}** URL(s) de webhook "
                f"Discord. Ces URLs sont des SECRETS — qui que ce soit qui "
                f"les voit peut envoyer des messages au nom du serveur.\n\n"
                f"**Action prise :**\n"
                f"• Message supprimé\n"
                f"• {revoked_count}/{len(matches)} webhooks révoqués "
                f"automatiquement\n\n"
                f"**Si tu n'as pas envoyé ce message** → ton compte est "
                f"peut-être compromis. Change ton mdp + active 2FA.\n\n"
                f"**Si c'était volontaire** → ne re-poste JAMAIS un webhook "
                f"en clair. Utilise des secrets manager (env vars, .env)."
            )
            await message.author.send(dm_text)
        except Exception:
            pass

        # 5) DM owner systématiquement (un leak = critique)
        try:
            owner = message.guild.owner or await message.guild.fetch_member(
                message.guild.owner_id
            )
            if owner:
                lines = [
                    f"🚨 **WEBHOOK LEAK — {message.guild.name}**",
                    f"",
                    f"**Membre :** {message.author.mention} "
                    f"({message.author.id})",
                    f"**Salon :** {message.channel.mention}",
                    f"**Nombre de webhooks leakés :** {len(matches)}",
                    f"",
                    f"**Revoke automatique :**",
                ]
                for url, wid, ok, status in revoke_results:
                    icon = "✅" if ok else "❌"
                    lines.append(f"{icon} `{wid}` — {status}")
                lines.append("")
                lines.append(
                    "_Le message a été supprimé. L'auteur a été DM. "
                    "Voir le panel staff sanction pour décider d'une "
                    "action supplémentaire._"
                )
                await owner.send("\n".join(lines))
        except Exception:
            pass

        # 6) Alerte staff via staff_sanction
        if _staff_sanction is not None:
            try:
                revoked_count = sum(
                    1 for _, _, ok, _ in revoke_results if ok
                )
                evidence = (
                    f"Message contenait {len(matches)} webhook(s) Discord. "
                    f"{revoked_count} ont été révoqués automatiquement."
                )
                await _staff_sanction.create_sanction_panel(
                    guild=message.guild,
                    target=message.author,
                    reason="Webhook Discord leaked en clair",
                    evidence_text=evidence,
                    evidence_channel_id=message.channel.id,
                    auto_action_taken=(
                        f"Message supprimé + {revoked_count} webhook(s) "
                        f"révoqués"
                    ),
                    source="webhook_leak",
                )
            except Exception as ex:
                print(f"[webhook_leak notify staff] {ex}")

        return True
    except Exception as ex:
        print(f"[webhook_leak on_message_hook] {ex}")
        return False


# ─── Helpers de stats (utilisé par le panel owner) ──────────────────────────

async def get_recent_leaks(guild_id: int, limit: int = 10) -> list[dict]:
    """Renvoie les N derniers leaks pour un guild."""
    out = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, channel_id, leaked_url_redacted, "
                "detected_at, auto_revoked, revoke_status "
                "FROM webhook_leak_log WHERE guild_id=? "
                "ORDER BY detected_at DESC LIMIT ?",
                (guild_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "user_id": int(r[0]),
                "channel_id": int(r[1] or 0),
                "url_redacted": r[2],
                "detected_at": r[3],
                "auto_revoked": bool(r[4]),
                "revoke_status": r[5],
            })
    except Exception as ex:
        print(f"[webhook_leak get_recent_leaks] {ex}")
    return out


__all__ = [
    "setup",
    "init_db",
    "scan_message",
    "on_message_hook",
    "get_recent_leaks",
]
