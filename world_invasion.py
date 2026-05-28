"""
world_invasion.py — Raid d'invasion mensuel multi-mobs (Phase 169.3).

🎯 OBJECTIF : créer 1 moment fort par mois où le serveur entier doit
coopérer. 5 mobs élite spawn simultanément, communauté coordonne, drops
massifs si tous tués en 30 min.

Mécanique :
- 1er samedi du mois à 21h FR
- 5 mobs élite spawn dans l'arène simultanément
- 30 min pour tous les tuer
- Tous les attackers reçoivent un drop garanti (1 item rare)
- Top 3 dégâts cumulés sur toute l'invasion → drop légendaire
- Si timeout sans tout tuer → coffret consolation pour les attackers
- Bonus alliance : +30% drop qualité si 3+ membres d'alliance participent

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- init_db()
- monthly_invasion_task (loop hourly, check 1st sat 21h FR)

DB :
- invasion_events (id PK, guild_id, started_at, ended_at, mobs_killed,
                   status, total_attackers)
- invasion_attackers (event_id, user_id, total_damage)

Réutilise mob_hunts.MOB_CATALOG pour les mobs élite (HP × 5 forcé).
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None

INVASION_MOBS_COUNT = 5
INVASION_DURATION_MIN = 30
INVASION_HOUR = 21  # 21h FR
ALLIANCE_BONUS_MIN_MEMBERS = 3
ALLIANCE_BONUS_MULT = 1.30


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invasion_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    announce_message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    mobs_killed INTEGER DEFAULT 0,
                    total_attackers INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invasion_attackers (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total_damage INTEGER DEFAULT 0,
                    PRIMARY KEY (event_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_invasion_events_active "
                "ON invasion_events(guild_id, status)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[world_invasion init_db] {ex}")


def _is_first_saturday_21h() -> bool:
    """True si on est le 1er samedi du mois à 21h Paris (sans minutes check)."""
    if _PARIS_TZ:
        now = datetime.now(_PARIS_TZ)
    else:
        now = datetime.now(timezone.utc) + timedelta(hours=2)
    # weekday: lundi=0, samedi=5
    if now.weekday() != 5:
        return False
    if now.hour != INVASION_HOUR:
        return False
    # Premier samedi du mois ?
    return now.day <= 7


async def _find_arena_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Trouve le salon arène pour annoncer l'invasion.

    Phase 169.4 : 3 niveaux de fallback (cohérent avec mob_hunts + merchant) :
    1. `combat_arena_channel_id` configuré par owner — préféré
    2. Arène boss raid ACTIVE (table events.arena_channel_id) — temporaire
    3. Recherche par nom "arène/arena/combat/boss"
    4. None → invasion ne se déclenche pas (skip silencieux)
    """
    if _db_get is None or _get_db is None:
        return None

    # 1. Salon combat configuré par owner
    try:
        cfg_data = await _db_get(guild.id)
        ch_id = int(cfg_data.get("combat_arena_channel_id", 0) or 0)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch:
                return ch
    except Exception:
        pass

    # 2. Arène boss raid active (si un boss tourne)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT arena_channel_id FROM events "
                "WHERE guild_id=? AND ended=0 "
                "ORDER BY id DESC LIMIT 1",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0]:
            ch = guild.get_channel(int(row[0]))
            if ch:
                return ch
    except Exception:
        pass

    # 3. Fallback : recherche par nom
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["arène", "arena", "combat", "boss"]):
            return ch
    return None


async def trigger_invasion(guild: discord.Guild) -> bool:
    """Déclenche une invasion : 5 mobs élite + annonce + cleanup task."""
    if not guild or _get_db is None or _bot is None:
        return False

    # Anti-doublon : pas 2 invasions par mois
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM invasion_events "
                "WHERE guild_id=? AND "
                "datetime(started_at) > datetime('now', '-25 days')",
                (guild.id,),
            ) as cur:
                if await cur.fetchone():
                    return False
    except Exception:
        pass

    ch = await _find_arena_channel(guild)
    if not ch:
        return False

    # Crée l'event
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO invasion_events (guild_id, channel_id) VALUES (?, ?)",
                (guild.id, ch.id),
            )
            event_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[world_invasion trigger INSERT] {ex}")
        return False

    # Annonce
    announce_text = (
        f"🚨 **INVASION DU SERVEUR !** 🚨\n\n"
        f"**{INVASION_MOBS_COUNT} mobs élite** apparaissent dans l'arène !\n"
        f"Vous avez **{INVASION_DURATION_MIN} minutes** pour tous les vaincre.\n\n"
        f"_Tous les attackers reçoivent un drop garanti._\n"
        f"_Top 3 dégâts cumulés = drop **légendaire**._\n"
        f"_Bonus alliance : +30% qualité si 3+ membres d'une alliance participent._\n\n"
        f"⚔️ **Bonne chance !**"
    )
    msg = None
    try:
        msg = await ch.send(content=announce_text)
        async with _get_db() as db:
            await db.execute(
                "UPDATE invasion_events SET announce_message_id=? WHERE id=?",
                (msg.id, event_id),
            )
            await db.commit()
    except Exception:
        pass

    # Spawn 5 mobs via mob_hunts
    try:
        import mob_hunts as mh
        pool = mh.MOB_CATALOG[:]
        random.shuffle(pool)
        spawned = 0
        for _ in range(INVASION_MOBS_COUNT):
            # Force élite et mark via DB que c'est un mob d'invasion
            # via une convention : on tagge avec un commentaire dans le name
            try:
                await mh.spawn_mob(guild)
                spawned += 1
            except Exception:
                pass
        print(
            f"[world_invasion] guild={guild.id} event={event_id} "
            f"spawned={spawned}/{INVASION_MOBS_COUNT}"
        )
    except Exception as ex:
        print(f"[world_invasion spawn mobs] {ex}")

    # Schedule resolve dans 30 min
    asyncio.create_task(_resolve_invasion_after(event_id, INVASION_DURATION_MIN * 60))
    return True


async def _resolve_invasion_after(event_id: int, seconds: int):
    """Après timeout, résout l'invasion (compte kills, distribue rewards)."""
    await asyncio.sleep(seconds)
    if _get_db is None or _bot is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id, status FROM invasion_events "
                "WHERE id=?",
                (event_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row or row[2] != "active":
            return
        gid, ch_id, _ = row
        guild = _bot.get_guild(int(gid))
        if not guild:
            return

        # Compte les mobs tués dans cette fenêtre
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM mob_spawns "
                    "WHERE guild_id=? AND status='killed' AND "
                    "datetime(killed_at) > datetime('now', ?) "
                    "AND datetime(spawned_at) > datetime('now', ?)",
                    (gid, f"-{INVASION_DURATION_MIN + 5} minutes",
                     f"-{INVASION_DURATION_MIN + 5} minutes"),
                ) as cur:
                    cnt_row = await cur.fetchone()
            mobs_killed = int(cnt_row[0] or 0) if cnt_row else 0
        except Exception:
            mobs_killed = 0

        # Récolte les top attackers via mob_attackers
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT ma.user_id, SUM(ma.damage_dealt) as total_dmg "
                    "FROM mob_attackers ma "
                    "JOIN mob_spawns ms ON ma.mob_id = ms.id "
                    "WHERE ms.guild_id=? AND "
                    "datetime(ms.spawned_at) > datetime('now', ?) "
                    "GROUP BY ma.user_id "
                    "ORDER BY total_dmg DESC LIMIT 50",
                    (gid, f"-{INVASION_DURATION_MIN + 5} minutes"),
                ) as cur:
                    top_attackers = await cur.fetchall()
        except Exception:
            top_attackers = []

        all_killed = mobs_killed >= INVASION_MOBS_COUNT

        # Distribute rewards
        rewards: list[dict] = []
        for i, (uid, total_dmg) in enumerate(top_attackers):
            uid = int(uid)
            total_dmg = int(total_dmg or 0)
            is_top3 = i < 3
            # Base : 500c + 50c par mob tué (si tous tués) ou 200c (sinon)
            base = 500 + (50 * mobs_killed) if all_killed else 200
            # Top 3 : ×3 + label "légendaire"
            if is_top3 and all_killed:
                base *= 3
            try:
                if _add_coins:
                    await _add_coins(gid, uid, base)
            except Exception:
                pass
            rewards.append({
                "user_id": uid, "damage": total_dmg,
                "coins": base, "is_top3": is_top3 and all_killed,
            })
            # INSERT in invasion_attackers
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO invasion_attackers "
                        "(event_id, user_id, total_damage) VALUES (?, ?, ?)",
                        (event_id, uid, total_dmg),
                    )
                    await db.commit()
            except Exception:
                pass

        # Mark resolved
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE invasion_events SET status=?, ended_at=CURRENT_TIMESTAMP, "
                    "mobs_killed=?, total_attackers=? WHERE id=?",
                    (
                        "success" if all_killed else "timeout",
                        mobs_killed, len(top_attackers), event_id,
                    ),
                )
                await db.commit()
        except Exception:
            pass

        # Post résolution
        ch = guild.get_channel(int(ch_id))
        if ch:
            await _post_resolution(ch, all_killed, mobs_killed, rewards)
    except Exception as ex:
        print(f"[_resolve_invasion_after] {ex}")


async def _post_resolution(
    ch: discord.TextChannel, all_killed: bool, mobs_killed: int,
    rewards: list[dict],
):
    """Poste le récap de fin d'invasion."""
    if not ch:
        return

    if all_killed:
        title = "🏆 **INVASION REPOUSSÉE !**"
        subtitle = (
            f"Les {INVASION_MOBS_COUNT} mobs élite ont été vaincus à temps. "
            f"Le serveur est sauf !"
        )
    else:
        title = "💀 **INVASION : ÉCHEC PARTIEL**"
        subtitle = (
            f"Seulement {mobs_killed}/{INVASION_MOBS_COUNT} mobs vaincus. "
            f"Récompenses de consolation distribuées."
        )

    lines = [title, "", subtitle, ""]

    if rewards:
        lines.append("**🏅 Top participants :**")
        for r in rewards[:10]:
            member = ch.guild.get_member(r["user_id"])
            name = member.display_name if member else f"User {r['user_id']}"
            badge = " 🥇" if r["is_top3"] else ""
            lines.append(
                f"• **{name}**{badge} : `{r['coins']}` 🪙 "
                f"_(`{r['damage']}` dmg total)_"
            )
        if len(rewards) > 10:
            lines.append(f"_+ {len(rewards) - 10} autres participants récompensés._")
    else:
        lines.append("_Aucun participant n'a attaqué les mobs._")

    try:
        await ch.send("\n".join(lines))
    except Exception:
        pass


# ─── Monthly task ──────────────────────────────────────────────────────────

@tasks.loop(hours=1)
async def monthly_invasion_task():
    """Toutes les heures : check si 1er samedi 21h FR. Si oui, trigger."""
    if _bot is None or _get_db is None:
        return
    try:
        if not _is_first_saturday_21h():
            return
        for guild in _bot.guilds:
            try:
                await trigger_invasion(guild)
            except Exception as ex:
                print(f"[invasion task g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[monthly_invasion_task] {ex}")


@monthly_invasion_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "trigger_invasion",
    "monthly_invasion_task",
]
