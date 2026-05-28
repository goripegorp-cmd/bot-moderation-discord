"""
coin_economy.py — Anti-inflation + Festival mensuel (Phase 157).

🎯 OBJECTIF : maintenir la santé de l'économie sur le long terme.
Sans ça, les coins s'accumulent et perdent leur valeur.

3 mécaniques :

1. **Festival mensuel des prix** (1er dimanche du mois, 48h) :
   - Annonce dans le hub
   - Flag `economy_festival_active` lu par les modules shop/marketplace
   - Multiplier 0.5 sur les prix item shop (les bots/modules lisent
     `get_price_multiplier()`)

2. **Taxe de luxe douce** (anti-rich) :
   - Si balance > 100 000 coins → -0.1% des coins en banque/wallet/jour
   - Capé à -100 coins/jour max (sinon les gros joueurs ressentent pas)
   - Discret : task quotidienne 04h FR

3. **Owner inflation tracker** :
   - Stats hebdo dans l'owner_digest : top 5 plus riches + évolution

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- is_festival_active(guild_id) -> bool
- get_price_multiplier(guild_id) -> float (1.0 ou 0.5)
- get_top_rich(guild_id, n=5) -> list[dict]
- monthly_festival_task (loop)
- luxury_tax_task (loop daily)

DB tables :
- economy_festivals (id PK, guild_id, started_at, ends_at, status)
- luxury_tax_log (guild_id, user_id, taxed_at, amount, balance_before)
"""
from __future__ import annotations

import asyncio
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

# Flags en mémoire pour fast check
_festival_active: dict[int, datetime] = {}  # guild_id → ends_at

FESTIVAL_DURATION_HOURS = 48
FESTIVAL_PRICE_MULTIPLIER = 0.5
LUXURY_TAX_THRESHOLD = 100_000
LUXURY_TAX_RATE = 0.001  # 0.1% par jour
LUXURY_TAX_MAX_PER_DAY = 100  # cap


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
                CREATE TABLE IF NOT EXISTS economy_festivals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS luxury_tax_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    taxed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    amount INTEGER,
                    balance_before INTEGER
                )
            """)
            await db.commit()

        # Restore active festivals au boot
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, ends_at FROM economy_festivals "
                "WHERE status='active'",
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            try:
                ends = (
                    datetime.fromisoformat(str(r[1]).replace("Z", "+00:00"))
                    if "T" in str(r[1]) else
                    datetime.strptime(
                        str(r[1]), "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                )
                if ends > datetime.now(timezone.utc):
                    _festival_active[int(r[0])] = ends
            except Exception:
                pass
    except Exception as ex:
        print(f"[coin_economy init_db] {ex}")


# ─── Festival ──────────────────────────────────────────────────────────────

def is_festival_active(guild_id: int) -> bool:
    """True si un festival des prix est en cours."""
    ends = _festival_active.get(guild_id)
    if ends is None:
        return False
    if ends > datetime.now(timezone.utc):
        return True
    _festival_active.pop(guild_id, None)
    return False


def get_price_multiplier(guild_id: int) -> float:
    """Multiplicateur de prix à appliquer dans le shop/marketplace."""
    return FESTIVAL_PRICE_MULTIPLIER if is_festival_active(guild_id) else 1.0


async def start_festival(guild: discord.Guild) -> bool:
    """Démarre un festival des prix (48h)."""
    if _get_db is None or not guild:
        return False
    if guild.id in _festival_active:
        return False  # déjà actif
    try:
        ends = datetime.now(timezone.utc) + timedelta(
            hours=FESTIVAL_DURATION_HOURS,
        )
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO economy_festivals "
                "(guild_id, ends_at) VALUES (?, ?)",
                (guild.id, ends.isoformat()),
            )
            await db.commit()
        _festival_active[guild.id] = ends

        # Annonce
        if _v2 is not None:
            try:
                target_ch = None
                for ch in guild.text_channels:
                    n = ch.name.lower()
                    if "shop" in n or "hub" in n or "general" in n:
                        if ch.permissions_for(guild.me).send_messages:
                            target_ch = ch
                            break
                if target_ch:
                    LayoutView = _v2['LayoutView']
                    v2_title = _v2['v2_title']
                    v2_subtitle = _v2['v2_subtitle']
                    v2_body = _v2['v2_body']
                    v2_divider = _v2['v2_divider']
                    v2_container = _v2['v2_container']

                    items = [
                        v2_title("🎉  FESTIVAL DES PRIX"),
                        v2_subtitle(
                            f"_Tous les prix shop **× 0.5** pendant "
                            f"**{FESTIVAL_DURATION_HOURS}h**_"
                        ),
                        v2_divider(),
                        v2_body(
                            "**🛒  Profite des soldes mensuelles !**\n\n"
                            "• Tous les items shop sont **2× moins chers**\n"
                            "• Marketplace : commissions réduites\n"
                            "• Item rare/épique : enfin abordables\n\n"
                            "_Festival se termine dans 48h. Reviens "
                            "le 1er dimanche du mois prochain._"
                        ),
                    ]

                    class _FestivalPanel(LayoutView):
                        def __init__(self):
                            super().__init__(timeout=None)
                            self.add_item(v2_container(*items, color=0xE91E63))

                    await target_ch.send(view=_FestivalPanel())
            except Exception:
                pass

        return True
    except Exception as ex:
        print(f"[coin_economy start_festival] {ex}")
        return False


async def end_festival(guild_id: int) -> bool:
    """Termine le festival."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE economy_festivals SET status='ended' "
                "WHERE guild_id=? AND status='active'",
                (guild_id,),
            )
            await db.commit()
        _festival_active.pop(guild_id, None)
        return True
    except Exception:
        return False


# ─── Luxury tax ─────────────────────────────────────────────────────────────

async def get_top_rich(guild_id: int, n: int = 5) -> list[dict]:
    """Top N joueurs les plus riches (wallet + bank si dispo)."""
    out = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            # Récupère les balances combinées
            async with db.execute(
                "SELECT user_id, coins, COALESCE(bank, 0) "
                "FROM economy WHERE guild_id=? AND coins > 0 "
                "ORDER BY (coins + COALESCE(bank, 0)) DESC LIMIT ?",
                (guild_id, n),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            wallet = int(r[1] or 0)
            bank = int(r[2] or 0)
            out.append({
                "user_id": int(r[0]),
                "wallet": wallet,
                "bank": bank,
                "total": wallet + bank,
            })
    except Exception:
        pass
    return out


async def apply_luxury_tax(guild: discord.Guild) -> dict:
    """Applique la taxe de luxe sur les balances > seuil."""
    out = {"taxed_count": 0, "total_collected": 0}
    if _get_db is None or not guild:
        return out
    try:
        rich_list = await get_top_rich(guild.id, n=100)
        for u in rich_list:
            total = u["total"]
            if total < LUXURY_TAX_THRESHOLD:
                continue
            tax = min(
                LUXURY_TAX_MAX_PER_DAY,
                int(total * LUXURY_TAX_RATE),
            )
            if tax <= 0:
                continue
            # Subtract from wallet first
            if _add_coins is not None:
                try:
                    await _add_coins(guild.id, u["user_id"], -tax)
                except Exception:
                    pass
            # Log
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO luxury_tax_log "
                        "(guild_id, user_id, amount, balance_before) "
                        "VALUES (?, ?, ?, ?)",
                        (guild.id, u["user_id"], tax, total),
                    )
                    await db.commit()
            except Exception:
                pass
            out["taxed_count"] += 1
            out["total_collected"] += tax
        return out
    except Exception as ex:
        print(f"[coin_economy apply_luxury_tax] {ex}")
        return out


# ─── Tasks ──────────────────────────────────────────────────────────────────

@tasks.loop(hours=2)
async def monthly_festival_task():
    """Check : 1er dimanche du mois à 18h FR → start festival.
    Et : fin festival si ends_at dépassé."""
    try:
        if _bot is None:
            return
        now_paris = (
            datetime.now(_PARIS_TZ) if _PARIS_TZ
            else datetime.now(timezone.utc)
        )
        # 1er dimanche du mois : weekday=6, day <= 7, hour=18
        is_first_sunday = (
            now_paris.weekday() == 6 and
            now_paris.day <= 7 and
            now_paris.hour == 18
        )

        for g in _bot.guilds:
            try:
                # End expired festivals
                if g.id in _festival_active and \
                   _festival_active[g.id] <= datetime.now(timezone.utc):
                    await end_festival(g.id)

                # Start new if 1st Sunday
                if is_first_sunday:
                    await start_festival(g)
            except Exception as ex:
                print(f"[monthly_festival_task g={g.id}] {ex}")
    except Exception as ex:
        print(f"[monthly_festival_task] {ex}")


@tasks.loop(hours=24)
async def luxury_tax_task():
    """Daily à 04h FR : applique la taxe de luxe."""
    try:
        if _bot is None:
            return
        for g in _bot.guilds:
            try:
                result = await apply_luxury_tax(g)
                if result.get("taxed_count", 0) > 0:
                    print(
                        f"[coin_economy] luxury tax g={g.id} : "
                        f"{result['taxed_count']} users, "
                        f"{result['total_collected']:,} c"
                    )
            except Exception:
                pass
            await asyncio.sleep(2)
    except Exception as ex:
        print(f"[luxury_tax_task] {ex}")


@monthly_festival_task.before_loop
async def _wait_ready_1():
    if _bot is not None:
        await _bot.wait_until_ready()


@luxury_tax_task.before_loop
async def _wait_ready_2():
    if _bot is not None:
        await _bot.wait_until_ready()
    # Initial delay : on lance à 04h
    now = datetime.now(_PARIS_TZ) if _PARIS_TZ else datetime.now(timezone.utc)
    next_4am = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if next_4am <= now:
        next_4am += timedelta(days=1)
    delay = (next_4am - now).total_seconds()
    await asyncio.sleep(max(60, min(delay, 86400)))


__all__ = [
    "setup",
    "init_db",
    "is_festival_active",
    "get_price_multiplier",
    "start_festival",
    "end_festival",
    "get_top_rich",
    "apply_luxury_tax",
    "monthly_festival_task",
    "luxury_tax_task",
]
