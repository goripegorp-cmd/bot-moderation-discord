"""
roblox_raffle.py — Loterie hebdo pour fans Roblox (Phase 155 — E2).

🎯 OBJECTIF : récompenser les joueurs qui sont à la fois sur le Discord
ET qui ont lié leur compte Roblox (engagement croisé).

Mécanique (sans game-side verification car impossible côté Discord) :
- Tickets gagnés via :
  • Avoir lié son compte Roblox : 1 ticket/semaine
  • Daily quest complétée 5×/semaine : +1 ticket
  • Vote daily prompt 5×/semaine : +1 ticket
  • Saga participation (top 5) : +2 tickets
  • Tweet/Post sur le jeu du créateur : +3 tickets (claim manuel)

- Tirage : dimanche 20h FR
  • 1er : 10 000 coins
  • 2e-3e : 5 000 coins
  • 4e-10e : 1 000 coins

- Auto-reset des tickets chaque dimanche après le tirage.

DB tables :
- raffle_tickets (guild_id, user_id, week_key, tickets_count,
                  last_earned_at, PRIMARY KEY (guild_id, user_id, week_key))
- raffle_draws (id PK, guild_id, week_key, drawn_at,
                winners_jsonb)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- add_tickets(guild_id, user_id, source, count=1)
- get_my_tickets(guild_id, user_id) -> dict
- run_weekly_draw(guild) -> dict
- weekly_draw_task (loop)
- build_raffle_panel(member) -> LayoutView
"""
from __future__ import annotations

import asyncio
import json
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

# Prix par rang (idx 0 = 1er, etc.)
PRIZES = [10000, 5000, 5000, 1000, 1000, 1000, 1000, 1000, 1000, 1000]

# Source → tickets gagnés
TICKETS_BY_SOURCE = {
    "roblox_linked_weekly": 1,   # 1× par semaine si lié
    "quests_5_week":        1,   # 5 quêtes / semaine
    "votes_5_week":         1,   # 5 votes daily prompt / semaine
    "saga_top5":            2,   # top 5 contributeur saga
    "social_post_claim":    3,   # claim manuel "j'ai posté"
}


def _current_week_key() -> str:
    """Semaine ISO courante (ex: '2026-W22')."""
    if _PARIS_TZ is not None:
        d = datetime.now(_PARIS_TZ)
    else:
        d = datetime.now(timezone.utc)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    add_coins_fn=None,
):
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
                CREATE TABLE IF NOT EXISTS raffle_tickets (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    week_key TEXT NOT NULL,
                    tickets_count INTEGER DEFAULT 0,
                    last_earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id, week_key)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS raffle_draws (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    week_key TEXT NOT NULL,
                    drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    winners_jsonb TEXT
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[roblox_raffle init_db] {ex}")


async def add_tickets(
    guild_id: int, user_id: int, source: str,
    count: Optional[int] = None,
) -> int:
    """Ajoute des tickets à un user. Retourne le nouveau total semaine."""
    if _get_db is None:
        return 0
    n = count if count is not None else TICKETS_BY_SOURCE.get(source, 0)
    if n <= 0:
        return 0
    week = _current_week_key()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO raffle_tickets "
                "(guild_id, user_id, week_key, tickets_count, last_earned_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id, week_key) DO UPDATE SET "
                "tickets_count = tickets_count + ?, "
                "last_earned_at = CURRENT_TIMESTAMP",
                (guild_id, user_id, week, n, n),
            )
            await db.commit()
            async with db.execute(
                "SELECT tickets_count FROM raffle_tickets "
                "WHERE guild_id=? AND user_id=? AND week_key=?",
                (guild_id, user_id, week),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as ex:
        print(f"[roblox_raffle add_tickets] {ex}")
        return 0


async def get_my_tickets(guild_id: int, user_id: int) -> dict:
    """Renvoie le state des tickets du user pour cette semaine."""
    out = {"week": _current_week_key(), "tickets": 0,
           "last_earned_at": None, "rank_estimate": None}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT tickets_count, last_earned_at FROM raffle_tickets "
                "WHERE guild_id=? AND user_id=? AND week_key=?",
                (guild_id, user_id, out["week"]),
            ) as cur:
                row = await cur.fetchone()
            if row:
                out["tickets"] = int(row[0] or 0)
                out["last_earned_at"] = row[1]
            # Rank estimate
            async with db.execute(
                "SELECT COUNT(*) FROM raffle_tickets "
                "WHERE guild_id=? AND week_key=? AND tickets_count > ?",
                (guild_id, out["week"], out["tickets"]),
            ) as cur:
                r = await cur.fetchone()
            if r and out["tickets"] > 0:
                out["rank_estimate"] = int(r[0] or 0) + 1
    except Exception:
        pass
    return out


async def run_weekly_draw(guild: discord.Guild) -> dict:
    """Effectue le tirage de la semaine. Retourne {winners, total_participants}."""
    out = {"winners": [], "total_participants": 0, "total_tickets": 0}
    if _get_db is None or not guild:
        return out
    # Semaine qui se termine (= ISO week courante, on tire dimanche soir)
    week = _current_week_key()
    try:
        # Phase 163.3 : distribute "roblox_linked_weekly" tickets juste avant
        # le tirage. Tout user avec compte Roblox lié reçoit 1 ticket bonus.
        # Le draw ne tire qu'une fois par semaine par guild (check raffle_draws
        # plus haut), donc cette boucle ne s'exécute qu'une fois par semaine
        # — pas de doublon.
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT user_id FROM roblox_account_links "
                    "WHERE guild_id=?",
                    (guild.id,),
                ) as cur:
                    linked_rows = await cur.fetchall()
            for (uid,) in linked_rows:
                try:
                    await add_tickets(
                        guild.id, int(uid), "roblox_linked_weekly", 1,
                    )
                except Exception:
                    pass
        except Exception as ex:
            print(f"[roblox_raffle linked_weekly] {ex}")

        # Récupère tous les tickets de la semaine
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, tickets_count FROM raffle_tickets "
                "WHERE guild_id=? AND week_key=? AND tickets_count > 0",
                (guild.id, week),
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            return out
        out["total_participants"] = len(rows)
        # Build pool pondéré
        pool: list[int] = []
        for uid, tickets in rows:
            for _ in range(int(tickets)):
                pool.append(int(uid))
        out["total_tickets"] = len(pool)
        if not pool:
            return out

        # Tirage : 10 winners distincts max
        random.shuffle(pool)
        winners_set: list[int] = []
        for uid in pool:
            if uid not in winners_set:
                winners_set.append(uid)
            if len(winners_set) >= len(PRIZES):
                break

        # Distribute prizes
        winners_data = []
        for i, uid in enumerate(winners_set):
            prize = PRIZES[i] if i < len(PRIZES) else 0
            if _add_coins is not None and prize > 0:
                try:
                    await _add_coins(guild.id, uid, prize)
                except Exception:
                    pass
            winners_data.append({
                "user_id": uid,
                "rank": i + 1,
                "prize": prize,
            })

        # Log draw
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO raffle_draws "
                "(guild_id, week_key, winners_jsonb) VALUES (?, ?, ?)",
                (guild.id, week, json.dumps(winners_data)),
            )
            await db.commit()

        out["winners"] = winners_data
        return out
    except Exception as ex:
        print(f"[roblox_raffle run_weekly_draw] {ex}")
        return out


def build_raffle_panel(member: discord.Member):
    """Panel V2 pour voir ses tickets + le pot."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _RafflePanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            data = await get_my_tickets(member.guild.id, member.id)
            items = []
            items.append(v2_title("🎰 Loterie Roblox hebdo"))
            items.append(v2_subtitle(
                f"-# Semaine `{data['week']}` · tirage dimanche 20h FR"
            ))
            items.append(v2_divider())

            if data["tickets"] > 0:
                line = f"🎟️ **{data['tickets']}** ticket(s)"
                if data["rank_estimate"]:
                    line += f" · classé **#{data['rank_estimate']}**"
                items.append(v2_body(line))
            else:
                items.append(v2_body(
                    "🎟️ Aucun ticket cette semaine — participe aux events pour en gagner."
                ))

            items.append(v2_divider())
            items.append(v2_body("### 🏆 Gagner des tickets"))
            items.append(v2_body(
                "🔗 Compte Roblox lié · **+1**/sem · 🎯 Quête quotidienne · **+1**\n"
                "📅 Vote daily · **+1** · 📜 Top 5 saga · **+2** · 📱 Tweet du jeu · **+3**"
            ))
            items.append(v2_divider())
            items.append(v2_body(
                "### 🎁 Prix\n"
                "🥇 `10 000` 🪙 · 🥈🥉 `5 000` 🪙 · Top 4-10 `1 000` 🪙"
            ))
            self.add_item(v2_container(*items, color=0xE91E63))

    return _RafflePanel()


@tasks.loop(hours=1)
async def weekly_draw_task():
    """Check chaque heure : si dimanche 20h FR → tirage."""
    try:
        if _bot is None:
            return
        if _PARIS_TZ is not None:
            now_paris = datetime.now(_PARIS_TZ)
        else:
            now_paris = datetime.now(timezone.utc) + timedelta(hours=2)
        # Dimanche = 6 ; heure 20
        if now_paris.weekday() != 6 or now_paris.hour != 20:
            return

        # Pour chaque guild, check si déjà fait pour cette semaine
        week = _current_week_key()
        for g in _bot.guilds:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT id FROM raffle_draws "
                        "WHERE guild_id=? AND week_key=?",
                        (g.id, week),
                    ) as cur:
                        if await cur.fetchone():
                            continue  # déjà fait
                result = await run_weekly_draw(g)
                if result["winners"]:
                    print(
                        f"[roblox_raffle] guild={g.id} "
                        f"draw OK : {len(result['winners'])} winners"
                    )
                    # Annonce dans un salon
                    await _announce_winners(g, result)
            except Exception as ex:
                print(f"[weekly_draw_task g={g.id}] {ex}")
            await asyncio.sleep(3)
    except Exception as ex:
        print(f"[weekly_draw_task] {ex}")


async def _announce_winners(guild: discord.Guild, result: dict):
    """Annonce les gagnants dans le salon roblox/general."""
    if _v2 is None:
        return
    try:
        target = None
        for ch in guild.text_channels:
            n = ch.name.lower()
            if "raffle" in n or "loterie" in n or "🎰" in n or "roblox" in n:
                if ch.permissions_for(guild.me).send_messages:
                    target = ch
                    break
        if target is None:
            for ch in guild.text_channels:
                if "general" in ch.name.lower() and \
                   ch.permissions_for(guild.me).send_messages:
                    target = ch
                    break
        if target is None:
            return

        LayoutView = _v2['LayoutView']
        v2_title = _v2['v2_title']
        v2_subtitle = _v2['v2_subtitle']
        v2_body = _v2['v2_body']
        v2_divider = _v2['v2_divider']
        v2_container = _v2['v2_container']

        items = []
        items.append(v2_title("🎰 Tirage Loterie Roblox"))
        items.append(v2_subtitle(
            f"-# Bravo aux **{result['total_participants']}** participants"
        ))
        items.append(v2_divider())
        for w in result["winners"][:5]:
            m = guild.get_member(int(w["user_id"]))
            name = m.mention if m else f"User-{w['user_id']}"
            medal = ["🥇", "🥈", "🥉"][w["rank"] - 1] if w["rank"] <= 3 else f"`{w['rank']}.`"
            items.append(v2_body(
                f"{medal} {name} — **{w['prize']:,}** 🪙"
            ))
        items.append(v2_divider())
        items.append(v2_body(
            "-# Prochain tirage dimanche 20h FR · les tickets repartent à 0."
        ))

        class _WinPanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(v2_container(*items, color=0xF1C40F))

        await target.send(view=_WinPanel())
    except Exception as ex:
        print(f"[_announce_winners] {ex}")


@weekly_draw_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "add_tickets",
    "get_my_tickets",
    "run_weekly_draw",
    "build_raffle_panel",
    "weekly_draw_task",
    "TICKETS_BY_SOURCE",
    "PRIZES",
]
