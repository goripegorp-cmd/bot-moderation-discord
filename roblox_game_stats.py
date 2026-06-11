"""
roblox_game_stats.py — Stats hebdo des jeux Roblox du créateur (Phase 155 — E1).

🎯 OBJECTIF : auto-fetch les stats des jeux Roblox du serveur via l'API
publique Roblox + post hebdo dans un salon dédié, sans intervention.

Mécanique :
- Catalogue de jeux : table `roblox_tracked_games` (universe_id, name).
- Owner peut ajouter/retirer un jeu via `/owner game_add` (existant).
- Task hebdo dimanche 19h FR :
  • Pour chaque jeu, fetch stats (visites, playing, favorites, rating)
  • Compare aux stats de la semaine dernière
  • Post un récap dans le salon configuré

API publique Roblox utilisée :
- GET https://games.roblox.com/v1/games?universeIds=<id>
- GET https://games.roblox.com/v1/games/votes?universeIds=<id>

DB tables :
- roblox_game_stats_snapshots (id PK, guild_id, universe_id, captured_at,
                                visits, playing, favorites, up_votes,
                                down_votes)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- fetch_game_stats(universe_id) -> dict | None
- post_weekly_recap(guild) -> bool
- weekly_stats_task (loop weekly)
- get_growth(guild_id, universe_id, days=7) -> dict
"""
from __future__ import annotations

import asyncio
import aiohttp
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

ROBLOX_API_BASE = "https://games.roblox.com/v1"
HTTP_TIMEOUT = 10


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
                CREATE TABLE IF NOT EXISTS roblox_game_stats_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    universe_id INTEGER NOT NULL,
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    visits INTEGER DEFAULT 0,
                    playing INTEGER DEFAULT 0,
                    favorites INTEGER DEFAULT 0,
                    up_votes INTEGER DEFAULT 0,
                    down_votes INTEGER DEFAULT 0,
                    name TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_roblox_stats_recent "
                "ON roblox_game_stats_snapshots(guild_id, universe_id, captured_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[roblox_game_stats init_db] {ex}")


import re as _re
import time as _time

# Phase 165.3 : auto-preview Roblox URLs
ROBLOX_URL_RE = _re.compile(
    r"(?:https?://)?(?:www\.)?roblox\.com/games/(\d+)",
    _re.IGNORECASE,
)
_PREVIEW_COOLDOWN: dict[tuple[int, int], float] = {}  # (guild, channel) → ts
PREVIEW_COOLDOWN_SEC = 300  # 5 min


def extract_place_id_from_text(text: str) -> Optional[int]:
    """Extrait le 1er place_id Roblox d'un texte. None sinon."""
    if not text:
        return None
    m = ROBLOX_URL_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


async def fetch_universe_from_place(place_id: int) -> Optional[int]:
    """Convertit un place_id en universe_id via l'API publique Roblox."""
    if not place_id:
        return None
    try:
        url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=HTTP_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        uid = data.get("universeId")
        return int(uid) if uid else None
    except Exception as ex:
        print(f"[roblox_game_stats fetch_universe] {ex}")
        return None


async def try_inline_preview(message: discord.Message) -> bool:
    """Hook on_message — si le message contient une URL Roblox, post un
    preview stats (avec cooldown 5min/canal pour anti-spam).
    Retourne True si un preview a été posté."""
    if not message.guild or message.author.bot:
        return False
    place_id = extract_place_id_from_text(message.content or "")
    if not place_id:
        return False
    # Cooldown par canal
    key = (message.guild.id, message.channel.id)
    last = _PREVIEW_COOLDOWN.get(key, 0)
    if _time.time() - last < PREVIEW_COOLDOWN_SEC:
        return False
    try:
        universe_id = await fetch_universe_from_place(place_id)
        if not universe_id:
            return False
        stats = await fetch_game_stats(universe_id)
        if not stats:
            return False
        _PREVIEW_COOLDOWN[key] = _time.time()
        # Reply discret en réponse au message (pas de ping)
        total_votes = stats["up_votes"] + stats["down_votes"]
        approval = (
            int((stats["up_votes"] / total_votes) * 100)
            if total_votes > 0 else 0
        )
        reply = (
            f"🎮 **{stats['name']}**\n"
            f"👥 `{stats['playing']:,}` joueurs en ligne · "
            f"🚀 `{stats['visits']:,}` visites · "
            f"⭐ `{stats['favorites']:,}` favoris · "
            f"👍 `{approval}%` approval"
        )
        await message.reply(
            reply,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except Exception as ex:
        print(f"[roblox_game_stats try_inline_preview] {ex}")
        return False


async def fetch_game_stats(universe_id: int) -> Optional[dict]:
    """Fetch stats publiques d'un jeu Roblox via API officielle."""
    if not universe_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            # Stats principales
            url = f"{ROBLOX_API_BASE}/games?universeIds={universe_id}"
            async with session.get(url, timeout=HTTP_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            if not data.get("data"):
                return None
            game = data["data"][0]

            # Votes
            votes_up, votes_down = 0, 0
            try:
                url_v = f"{ROBLOX_API_BASE}/games/votes?universeIds={universe_id}"
                async with session.get(url_v, timeout=HTTP_TIMEOUT) as resp:
                    if resp.status == 200:
                        vdata = await resp.json()
                        if vdata.get("data"):
                            v = vdata["data"][0]
                            votes_up = int(v.get("upVotes", 0))
                            votes_down = int(v.get("downVotes", 0))
            except Exception:
                pass

            return {
                "universe_id": universe_id,
                "name": game.get("name", "?"),
                "visits": int(game.get("visits", 0)),
                "playing": int(game.get("playing", 0)),
                "favorites": int(game.get("favoritedCount", 0)),
                "up_votes": votes_up,
                "down_votes": votes_down,
                "created": game.get("created"),
                "max_players": int(game.get("maxPlayers", 0)),
            }
    except asyncio.TimeoutError:
        print(f"[roblox_game_stats] timeout universe={universe_id}")
        return None
    except Exception as ex:
        print(f"[roblox_game_stats fetch] {ex}")
        return None


async def _save_snapshot(
    guild_id: int, stats: dict,
):
    """Persist le snapshot pour calculer la croissance."""
    if _get_db is None or not stats:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO roblox_game_stats_snapshots "
                "(guild_id, universe_id, visits, playing, favorites, "
                "up_votes, down_votes, name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id, stats["universe_id"],
                    stats["visits"], stats["playing"], stats["favorites"],
                    stats["up_votes"], stats["down_votes"], stats["name"],
                ),
            )
            await db.commit()
    except Exception as ex:
        print(f"[roblox_game_stats save_snapshot] {ex}")


async def get_growth(
    guild_id: int, universe_id: int, days: int = 7,
) -> dict:
    """Compare aux stats d'il y a N jours."""
    out = {
        "delta_visits": 0, "delta_favorites": 0,
        "delta_up_votes": 0, "delta_down_votes": 0,
        "previous_visits": 0,
    }
    if _get_db is None:
        return out
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")
        async with _get_db() as db:
            async with db.execute(
                "SELECT visits, favorites, up_votes, down_votes "
                "FROM roblox_game_stats_snapshots "
                "WHERE guild_id=? AND universe_id=? AND captured_at <= ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (guild_id, universe_id, cutoff),
            ) as cur:
                row = await cur.fetchone()
            async with db.execute(
                "SELECT visits, favorites, up_votes, down_votes "
                "FROM roblox_game_stats_snapshots "
                "WHERE guild_id=? AND universe_id=? "
                "ORDER BY captured_at DESC LIMIT 1",
                (guild_id, universe_id),
            ) as cur:
                latest = await cur.fetchone()
        if row and latest:
            out["delta_visits"] = int(latest[0]) - int(row[0])
            out["delta_favorites"] = int(latest[1]) - int(row[1])
            out["delta_up_votes"] = int(latest[2]) - int(row[2])
            out["delta_down_votes"] = int(latest[3]) - int(row[3])
            out["previous_visits"] = int(row[0])
    except Exception as ex:
        print(f"[roblox_game_stats get_growth] {ex}")
    return out


async def _get_tracked_games(guild_id: int) -> list[dict]:
    """Récupère les jeux trackés via la table existante (Phase 18+)."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            # Essaie plusieurs noms de table possibles
            for table in ("roblox_tracked_games", "tracked_roblox_games",
                          "roblox_games", "game_updates_catalog"):
                try:
                    async with db.execute(
                        f"SELECT universe_id, name FROM {table} "
                        f"WHERE guild_id=? AND universe_id IS NOT NULL "
                        f"AND universe_id > 0",
                        (guild_id,),
                    ) as cur:
                        rows = await cur.fetchall()
                    if rows:
                        return [
                            {"universe_id": int(r[0]), "name": r[1] or "?"}
                            for r in rows
                        ]
                except Exception:
                    continue
    except Exception:
        pass
    return []


async def post_weekly_recap(guild: discord.Guild) -> bool:
    """Poste le récap hebdo dans le salon configuré."""
    if _get_db is None or _v2 is None or not guild:
        return False
    try:
        games = await _get_tracked_games(guild.id)
        if not games:
            return False  # rien à poster

        # Capture stats actuelles
        all_stats = []
        for g in games[:10]:  # max 10 jeux pour pas spammer
            stats = await fetch_game_stats(g["universe_id"])
            if stats:
                await _save_snapshot(guild.id, stats)
                growth = await get_growth(
                    guild.id, g["universe_id"], days=7,
                )
                stats["growth"] = growth
                all_stats.append(stats)
            await asyncio.sleep(1)  # throttle API Roblox

        if not all_stats:
            return False

        # Trouve un salon roblox/stats
        target = None
        for ch in guild.text_channels:
            n = ch.name.lower()
            if "roblox" in n or "stats" in n or "📊" in n:
                if ch.permissions_for(guild.me).send_messages:
                    target = ch
                    break
        if target is None:
            # Fallback : hub channel
            for ch in guild.text_channels:
                if "hub" in ch.name.lower() and \
                   ch.permissions_for(guild.me).send_messages:
                    target = ch
                    break
        if target is None:
            return False

        # Build panel
        LayoutView = _v2['LayoutView']
        v2_title = _v2['v2_title']
        v2_subtitle = _v2['v2_subtitle']
        v2_body = _v2['v2_body']
        v2_divider = _v2['v2_divider']
        v2_container = _v2['v2_container']

        items = []
        items.append(v2_title("📊 Stats hebdo Roblox"))
        items.append(v2_subtitle(
            f"-# {len(all_stats)} jeu(x) trackés cette semaine"
        ))
        items.append(v2_divider())

        for s in all_stats:
            g = s["growth"]
            delta_v = g["delta_visits"]
            delta_v_str = (
                f"📈 +`{delta_v:,}`" if delta_v > 0
                else (f"📉 `{delta_v:,}`" if delta_v < 0 else "➖ `0`")
            )
            items.append(v2_body(
                f"### 🎮 {s['name']}\n"
                f"🚀 `{s['visits']:,}` visites ({delta_v_str} 7j) · 👥 `{s['playing']:,}` en ligne\n"
                f"⭐ `{s['favorites']:,}` favoris (+`{g['delta_favorites']}`) · "
                f"👍 `{s['up_votes']:,}` / 👎 `{s['down_votes']:,}`"
            ))
            items.append(v2_divider())

        items.append(v2_body(
            "-# Récap auto chaque dimanche 19h FR."
        ))

        class _RecapPanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(v2_container(*items, color=0x00A8F4))

        await target.send(view=_RecapPanel())
        return True
    except Exception as ex:
        print(f"[roblox_game_stats post_weekly_recap] {ex}")
        return False


@tasks.loop(hours=1)
async def weekly_stats_task():
    """Check chaque heure si on est dimanche 19h FR."""
    try:
        if _bot is None:
            return
        if _PARIS_TZ is not None:
            now_paris = datetime.now(_PARIS_TZ)
        else:
            now_paris = datetime.now(timezone.utc) + timedelta(hours=2)
        # Dimanche = 6 ; heure 19
        if now_paris.weekday() != 6 or now_paris.hour != 19:
            return

        for g in _bot.guilds:
            try:
                await post_weekly_recap(g)
            except Exception as ex:
                print(f"[weekly_stats_task guild={g.id}] {ex}")
            await asyncio.sleep(5)
    except Exception as ex:
        print(f"[weekly_stats_task] {ex}")


@weekly_stats_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "fetch_game_stats",
    "post_weekly_recap",
    "get_growth",
    "weekly_stats_task",
]
