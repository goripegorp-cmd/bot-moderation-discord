"""sticky_messages.py — « Dernier message » (sticky) : un message qui reste TOUJOURS en
bas d'un salon (owner 2026-06-16).

Quand un membre poste dans un salon configuré, le bot SUPPRIME son message sticky du dessus
et le REPOSTE en bas → il reste visible (idéal pour des consignes que les nouveaux doivent
voir). DISTINCT du « Message automatique » récurrent (table scheduled_messages) : c'est une
case À PART qui cohabite avec lui.

⚠️ ANTI-429 (préoccupation explicite de l'owner — « s'il y a trop de messages ») : on NE
reposte PAS à chaque message. Garde-fous :
- cache MÉMOIRE des salons sticky → AUCUNE requête DB sur le chemin chaud (1 set-check O(1)),
- COOLDOWN par salon (`STICKY_COOLDOWN_SEC`) : au plus ~1 delete+send par cooldown et par salon,
- repost DIFFÉRÉ unique après une rafale (le sticky re-descend en bas une fois le calme revenu),
- verrou par salon (`_repost_lock`) → jamais 2 reposts concurrents.

API : setup(bot, get_db) · init_db() · set_sticky/get_sticky/remove_sticky/list_stickies ·
is_sticky_channel(channel_id) (sync, O(1)) · on_message_hook(msg). FAIL-SAFE / FAIL-OPEN.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

_bot = None
_get_db = None

# Délai mini entre 2 reposts d'un même salon (secondes). Borne la charge API.
STICKY_COOLDOWN_SEC = 6

# Cache mémoire des salons ayant un sticky ACTIF → évite une requête DB à chaque message.
_sticky_channels: set = set()
# Throttle + anti-concurrence (par salon).
_last_repost: dict = {}     # channel_id -> epoch du dernier repost
_repost_lock: set = set()   # channel_id avec un repost en cours/planifié


def setup(bot_instance, get_db_fn):
    global _bot, _get_db
    _bot = bot_instance
    _get_db = get_db_fn


async def init_db():
    """Crée la table + charge le cache des salons sticky. FAIL-OPEN."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS sticky_messages ("
                "guild_id INTEGER, channel_id INTEGER PRIMARY KEY, "
                "content TEXT, message_id INTEGER DEFAULT 0, "
                "enabled INTEGER DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            await db.commit()
            async with db.execute(
                "SELECT channel_id FROM sticky_messages WHERE enabled=1") as cur:
                rows = await cur.fetchall()
        _sticky_channels.clear()
        for (ch_id,) in rows:
            _sticky_channels.add(int(ch_id))
        print(f"[sticky_messages] {len(_sticky_channels)} salon(s) sticky chargé(s)")
    except Exception as ex:
        print(f"[sticky_messages init_db] {ex}")


def is_sticky_channel(channel_id) -> bool:
    """O(1) mémoire : ce salon a-t-il un sticky actif ? (chemin chaud on_message)."""
    try:
        return int(channel_id) in _sticky_channels
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  CRUD
# ═══════════════════════════════════════════════════════════════════════════

async def set_sticky(guild_id, channel_id, content) -> bool:
    """Définit/maj le sticky d'un salon (réinitialise message_id → repost propre). FAIL-SAFE."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO sticky_messages (guild_id, channel_id, content, message_id, "
                "enabled, updated_at) VALUES (?,?,?,0,1,CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET content=excluded.content, enabled=1, "
                "message_id=0, updated_at=CURRENT_TIMESTAMP",
                (int(guild_id), int(channel_id), str(content or "")[:1800]))
            await db.commit()
        _sticky_channels.add(int(channel_id))
        _last_repost.pop(int(channel_id), None)
        return True
    except Exception as ex:
        print(f"[sticky_messages set_sticky] {ex}")
        return False


async def get_sticky(channel_id):
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id, content, message_id, enabled FROM sticky_messages "
                "WHERE channel_id=?", (int(channel_id),)) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {"guild_id": int(row[0]), "channel_id": int(row[1]), "content": row[2] or "",
                "message_id": int(row[3] or 0), "enabled": bool(row[4])}
    except Exception:
        return None


async def remove_sticky(guild_id, channel_id) -> bool:
    """Retire le sticky d'un salon : supprime le message posté (best-effort) + la ligne +
    le cache. FAIL-SAFE."""
    try:
        st = await get_sticky(channel_id)
        if st and st.get("message_id") and _bot is not None:
            try:
                ch = _bot.get_channel(int(channel_id))
                if ch is not None:
                    await ch.get_partial_message(int(st["message_id"])).delete()
            except Exception:
                pass
        if _get_db is not None:
            async with _get_db() as db:
                await db.execute(
                    "DELETE FROM sticky_messages WHERE guild_id=? AND channel_id=?",
                    (int(guild_id), int(channel_id)))
                await db.commit()
        _sticky_channels.discard(int(channel_id))
        _last_repost.pop(int(channel_id), None)
        _repost_lock.discard(int(channel_id))
        return True
    except Exception as ex:
        print(f"[sticky_messages remove_sticky] {ex}")
        return False


async def list_stickies(guild_id):
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT channel_id, content, enabled FROM sticky_messages WHERE guild_id=?",
                (int(guild_id),)) as cur:
                return [(int(r[0]), r[1] or "", bool(r[2])) for r in await cur.fetchall()]
    except Exception:
        return []


async def _set_message_id(channel_id, message_id):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("UPDATE sticky_messages SET message_id=? WHERE channel_id=?",
                             (int(message_id), int(channel_id)))
            await db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Repost (throttlé)
# ═══════════════════════════════════════════════════════════════════════════

def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


async def _do_repost(channel_id):
    """Supprime l'ancien sticky (best-effort, zéro fetch) + reposte EN BAS. Pose le
    cooldown et libère le verrou. FAIL-SAFE."""
    try:
        st = await get_sticky(channel_id)
        if not st or not st.get("enabled") or not (st.get("content") or "").strip():
            return
        ch = _bot.get_channel(int(channel_id)) if _bot else None
        if ch is None or not isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return
        old_id = int(st.get("message_id") or 0)
        if old_id:
            try:
                await ch.get_partial_message(old_id).delete()
            except Exception:
                pass
        try:
            new_msg = await ch.send(
                st["content"][:1900],
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=False))
            await _set_message_id(channel_id, new_msg.id)
        except Exception as ex:
            print(f"[sticky_messages repost send] {ex}")
        _last_repost[int(channel_id)] = _now()
    except Exception as ex:
        print(f"[sticky_messages _do_repost] {ex}")
    finally:
        _repost_lock.discard(int(channel_id))


async def repost_now(channel_id):
    """Force un repost immédiat (utilisé juste après set_sticky pour afficher le message
    tout de suite). FAIL-SAFE."""
    await _do_repost(channel_id)


async def _delayed_repost(channel_id, delay):
    try:
        await asyncio.sleep(max(0.0, float(delay)))
        await _do_repost(channel_id)
    except Exception:
        _repost_lock.discard(int(channel_id))


async def on_message_hook(msg):
    """Appelé depuis on_message (l'appelant a déjà filtré : non-bot + salon sticky). Planifie
    un repost throttlé : immédiat si le cooldown est passé, sinon UN repost différé après la
    rafale. FAIL-SAFE / non bloquant."""
    try:
        if _bot is None or msg.guild is None or getattr(msg.author, 'bot', False):
            return
        ch_id = int(msg.channel.id)
        if ch_id not in _sticky_channels or ch_id in _repost_lock:
            return
        elapsed = _now() - _last_repost.get(ch_id, 0)
        _repost_lock.add(ch_id)  # verrou (libéré par _do_repost/_delayed_repost)
        if elapsed >= STICKY_COOLDOWN_SEC:
            await _do_repost(ch_id)
        else:
            asyncio.create_task(_delayed_repost(ch_id, STICKY_COOLDOWN_SEC - elapsed))
    except Exception as ex:
        print(f"[sticky_messages on_message_hook] {ex}")
        try:
            _repost_lock.discard(int(msg.channel.id))
        except Exception:
            pass


__all__ = [
    "setup", "init_db", "set_sticky", "get_sticky", "remove_sticky",
    "list_stickies", "is_sticky_channel", "on_message_hook", "repost_now",
    "STICKY_COOLDOWN_SEC",
]
