"""
raid_recap.py — Récap hebdomadaire des Boss Raids (Phase 129).

Tâche programmée chaque dimanche 21h Europe/Paris qui aggrège les stats des
boss raids des 7 derniers jours et poste un panneau magnifique dans le hub
channel.

Stats compilées :
- 🏆 Top damager (avec son score)
- ⚔️ MVP : top final-blow + raid participation
- 💀 Total boss vaincus cette semaine
- 🎁 Total coins distribués
- 📊 Nombre d'attaquants uniques

Dépend de :
- aiosqlite (DB queries sur events + event_participants)
- discord.py (Embed/View pour le post)

Usage dans bot.py :
    import raid_recap
    if not raid_recap.weekly_recap_task.is_running():
        raid_recap.weekly_recap_task.start()

Pour tester :
    await raid_recap.post_recap_for_guild(guild)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

# ─── Configuration ───────────────────────────────────────────────────────
WINDOW_DAYS = 7   # période couverte par le recap
POST_HOUR_FR = 21  # 21h00 Europe/Paris
POST_WEEKDAY = 6   # dimanche (0=lundi)


# Référence injectée par bot.py — set au démarrage
_bot = None
_get_db = None
_db_get = None       # async (guild_id) -> dict de config
_v2_helpers = None   # dict avec les helpers V2 (v2_title, v2_subtitle, etc.)


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    """Configure le module avec les références nécessaires du bot principal.

    Args:
        bot_instance : le bot discord.py
        get_db_fn    : helper async with get_db() pour requêtes
        db_get_fn    : async (guild_id) -> dict config
        v2_helpers   : dict {'v2_title', 'v2_subtitle', 'v2_body',
                             'v2_divider', 'v2_container', 'LayoutView'}
    """
    global _bot, _get_db, _db_get, _v2_helpers
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# QUERIES — récupérer les stats brutes des 7 derniers jours
# ═══════════════════════════════════════════════════════════════════════════════

async def _collect_stats(guild_id: int) -> dict:
    """Aggrège les stats Boss Raid sur les 7 derniers jours.

    Retourne :
        {
            "events_count": int,
            "total_damage": int,
            "unique_attackers": int,
            "top_damager": {"user_id": int, "damage": int} | None,
            "top_participants": [{"user_id": int, "raids": int}, ...],  # top 3
        }
    """
    out = {
        "events_count": 0,
        "total_damage": 0,
        "unique_attackers": 0,
        "top_damager": None,
        "top_participants": [],
    }
    if _get_db is None:
        return out

    cutoff = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()

    try:
        async with _get_db() as db:
            # Events de la semaine
            async with db.execute(
                "SELECT id FROM events WHERE guild_id=? AND ended=1 "
                "AND event_type IN ('boss_raid', 'boss') AND started_at >= ?",
                (guild_id, cutoff),
            ) as cur:
                event_ids = [r[0] for r in await cur.fetchall()]
            out["events_count"] = len(event_ids)
            if not event_ids:
                return out

            placeholders = ",".join("?" * len(event_ids))

            # Total damage + unique attackers
            async with db.execute(
                f"SELECT SUM(damage_dealt), COUNT(DISTINCT user_id) "
                f"FROM event_participants WHERE event_id IN ({placeholders})",
                event_ids,
            ) as cur:
                row = await cur.fetchone()
            out["total_damage"] = int(row[0] or 0) if row else 0
            out["unique_attackers"] = int(row[1] or 0) if row else 0

            # Top damager
            async with db.execute(
                f"SELECT user_id, SUM(damage_dealt) AS total_dmg "
                f"FROM event_participants WHERE event_id IN ({placeholders}) "
                f"GROUP BY user_id ORDER BY total_dmg DESC LIMIT 1",
                event_ids,
            ) as cur:
                row = await cur.fetchone()
            if row:
                out["top_damager"] = {
                    "user_id": int(row[0]),
                    "damage": int(row[1] or 0),
                }

            # Top participants (par nb d'event_id)
            async with db.execute(
                f"SELECT user_id, COUNT(DISTINCT event_id) AS raids "
                f"FROM event_participants WHERE event_id IN ({placeholders}) "
                f"GROUP BY user_id ORDER BY raids DESC LIMIT 3",
                event_ids,
            ) as cur:
                rows = await cur.fetchall()
            out["top_participants"] = [
                {"user_id": int(r[0]), "raids": int(r[1])} for r in rows
            ]
    except Exception as ex:
        print(f"[raid_recap _collect_stats guild={guild_id}] {ex}")

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Construit le LayoutView V2 et le poste
# ═══════════════════════════════════════════════════════════════════════════════

def _build_layout(stats: dict, guild) -> discord.ui.LayoutView | None:
    """Construit le LayoutView V2 du recap. Retourne None si pas de stats."""
    if _v2_helpers is None or stats["events_count"] == 0:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _RaidRecapLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            items = []
            items.append(v2_title("🏆 Récap des Boss Raids"))
            items.append(v2_subtitle(
                f"Les 7 derniers jours sur {guild.name}"
            ))
            items.append(v2_divider())

            # Stats globales
            items.append(v2_body("### 📊 Cette semaine"))
            items.append(v2_body(
                f"💀 **Boss vaincus :** `{stats['events_count']}`\n"
                f"💥 **Dégâts cumulés :** `{stats['total_damage']:,}`\n"
                f"⚔️ **Attaquants uniques :** `{stats['unique_attackers']}`"
            ))

            # Top damager
            if stats.get("top_damager"):
                td = stats["top_damager"]
                items.append(v2_divider())
                items.append(v2_body("### 🥇 Top damager"))
                items.append(v2_body(
                    f"🏆 <@{td['user_id']}> · `{td['damage']:,}` dégâts cumulés\n"
                    f"_Le titan de la semaine. Chapeau bas._"
                ))

            # Top participants
            if stats.get("top_participants"):
                items.append(v2_divider())
                items.append(v2_body("### 🎖️ MVP de participation"))
                medals = ["🥇", "🥈", "🥉"]
                lines = []
                for idx, p in enumerate(stats["top_participants"][:3]):
                    medal = medals[idx] if idx < 3 else "▫️"
                    lines.append(
                        f"{medal} <@{p['user_id']}> · `{p['raids']}` raid(s)"
                    )
                items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "-# Attaque les boss pour figurer au prochain récap · le top damager gagne un bonus."
            ))

            self.add_item(v2_container(*items, color=0xFFD700))

    return _RaidRecapLayout()


async def post_recap_for_guild(guild) -> bool:
    """Poste le recap dans le hub channel du serveur. Retourne True si posté."""
    if _bot is None or _db_get is None:
        return False
    try:
        stats = await _collect_stats(guild.id)
        if stats["events_count"] == 0:
            print(f"[raid_recap] guild={guild.id} : 0 raids cette semaine, skip")
            return False

        cfg_data = await _db_get(guild.id)
        hub_ch_id = int(cfg_data.get("hub_channel", 0) or 0)
        if not hub_ch_id:
            print(f"[raid_recap] guild={guild.id} : pas de hub_channel configuré")
            return False
        ch = guild.get_channel(hub_ch_id)
        if not ch:
            return False

        view = _build_layout(stats, guild)
        if view is None:
            return False

        try:
            msg = await ch.send(view=view)
            print(f"✅ [raid_recap] posted in guild={guild.id} (msg={msg.id})")
            return True
        except (discord.Forbidden, discord.HTTPException) as ex:
            print(f"[raid_recap send guild={guild.id}] {ex}")
            return False
    except Exception as ex:
        print(f"[raid_recap post_recap_for_guild={guild.id}] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TASK PROGRAMMÉE — Loop hebdomadaire
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def weekly_recap_task():
    """Tourne toutes les 30 min, déclenche le recap UNIQUEMENT dimanche 21h FR."""
    try:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Europe/Paris")
        except Exception:
            tz = timezone.utc

        now_local = datetime.now(tz)
        # Dimanche 21h00-21h30 → trigger
        if now_local.weekday() != POST_WEEKDAY:
            return
        if now_local.hour != POST_HOUR_FR:
            return

        # Anti-doublon : on stocke la dernière semaine recap-ée par guild
        # via db_get/db_set (clé "raid_recap_last_week")
        if _bot is None or _db_get is None:
            return

        week_id = now_local.strftime("%G-W%V")  # YYYY-W## (ISO week)

        for guild in list(_bot.guilds):
            try:
                cfg_data = await _db_get(guild.id)
                last_week = cfg_data.get("raid_recap_last_week", "")
                if last_week == week_id:
                    continue  # déjà fait cette semaine

                ok = await post_recap_for_guild(guild)
                if ok:
                    # Marquer comme fait via db_set si disponible
                    # (on importe db_set dynamiquement pour éviter circular)
                    try:
                        from bot import db_set
                        await db_set(guild.id, "raid_recap_last_week", week_id)
                    except Exception:
                        pass
            except Exception as ex:
                print(f"[raid_recap loop guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[raid_recap loop] {ex}")


@weekly_recap_task.before_loop
async def _before():
    """Attend que le bot soit prêt avant de démarrer."""
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "post_recap_for_guild",
    "weekly_recap_task",
    "WINDOW_DAYS",
]
