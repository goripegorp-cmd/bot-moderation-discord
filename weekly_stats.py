"""
weekly_stats.py — Récap perso + Leaderboards publics (Phase 161).

🎯 OBJECTIF : exploiter toutes les data collectées (reputation, voice
minutes, saga contributions, drops, etc.) pour montrer aux utilisateurs
leur progression sur 7 jours et leur position dans le serveur.

2 features :

1. **Récap perso** (button /profile + hub) :
   - Boss kills, treasures, duels, quests, voice minutes (7 jours)
   - Coins gagnés
   - Réputation gagnée
   - Position dans le top serveur
   - Style de jeu détecté

2. **Leaderboards publics** (auto-postés lundi 9h FR + button hub) :
   - 🏆 Top 5 Réputation cette semaine
   - ⚔️ Top 5 Boss kills
   - 🎙️ Top 5 Voice time
   - 🎯 Top 5 Quêtes complétées
   - 💎 Top 5 Drops collectés

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- get_user_weekly_stats(guild_id, user_id) -> dict
- build_recap_panel(member) -> LayoutView
- build_leaderboard_panel(guild) -> LayoutView
- weekly_post_task (loop : lundi 9h FR)
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


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


# ─── Queries hebdo ────────────────────────────────────────────────────────

def _week_cutoff_iso() -> str:
    """ISO timestamp d'il y a 7 jours."""
    return (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).strftime("%Y-%m-%d %H:%M:%S")


async def _count_safe(db, query: str, params: tuple) -> int:
    """COUNT/SUM avec fallback 0 si table absente."""
    try:
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


async def get_user_weekly_stats(guild_id: int, user_id: int) -> dict:
    """Renvoie un dict avec toutes les stats des 7 derniers jours."""
    out = {
        "boss_kills_final": 0,
        "treasures": 0,
        "duels_won": 0,
        "quests_done": 0,
        "voice_minutes": 0,
        "voice_coins_earned": 0,
        "reputation_gained": 0,
        "drops_collected": 0,
        "saga_contribution": 0,
        "riddles_solved": 0,
        "rank_reputation": 0,
        "style": "balanced",
    }
    if _get_db is None:
        return out
    cutoff = _week_cutoff_iso()
    try:
        async with _get_db() as db:
            # Reputation gained
            out["reputation_gained"] = await _count_safe(
                db,
                "SELECT COALESCE(SUM(points), 0) FROM reputation_history "
                "WHERE guild_id=? AND user_id=? AND created_at >= ?",
                (guild_id, user_id, cutoff),
            )

            # Boss kills (via reputation_history sources)
            out["boss_kills_final"] = await _count_safe(
                db,
                "SELECT COUNT(*) FROM reputation_history "
                "WHERE guild_id=? AND user_id=? AND source='boss_kill_final' "
                "AND created_at >= ?",
                (guild_id, user_id, cutoff),
            )
            out["treasures"] = await _count_safe(
                db,
                "SELECT COUNT(*) FROM reputation_history "
                "WHERE guild_id=? AND user_id=? AND source='treasure_claim' "
                "AND created_at >= ?",
                (guild_id, user_id, cutoff),
            )
            out["duels_won"] = await _count_safe(
                db,
                "SELECT COUNT(*) FROM reputation_history "
                "WHERE guild_id=? AND user_id=? AND source='duel_win' "
                "AND created_at >= ?",
                (guild_id, user_id, cutoff),
            )
            out["quests_done"] = await _count_safe(
                db,
                "SELECT COUNT(*) FROM reputation_history "
                "WHERE guild_id=? AND user_id=? AND source='quest_complete' "
                "AND created_at >= ?",
                (guild_id, user_id, cutoff),
            )
            out["riddles_solved"] = await _count_safe(
                db,
                "SELECT COUNT(*) FROM reputation_history "
                "WHERE guild_id=? AND user_id=? AND source='riddle_first' "
                "AND created_at >= ?",
                (guild_id, user_id, cutoff),
            )

            # Voice minutes (via voice_activity_log)
            out["voice_minutes"] = await _count_safe(
                db,
                "SELECT COALESCE(SUM(duration_seconds), 0) / 60 "
                "FROM voice_activity_log "
                "WHERE guild_id=? AND user_id=? AND joined_at >= ?",
                (guild_id, user_id, cutoff),
            )

            # Voice coins (via voice_daily_rewards)
            cutoff_day = (
                datetime.now(timezone.utc) - timedelta(days=7)
            ).strftime("%Y-%m-%d")
            out["voice_coins_earned"] = await _count_safe(
                db,
                "SELECT COALESCE(SUM(coins_today), 0) "
                "FROM voice_daily_rewards "
                "WHERE guild_id=? AND user_id=? AND day >= ?",
                (guild_id, user_id, cutoff_day),
            )

            # Drops collected (saisonnier)
            out["drops_collected"] = await _count_safe(
                db,
                "SELECT COUNT(*) FROM seasonal_drops_log "
                "WHERE guild_id=? AND user_id=? AND claimed_at >= ?",
                (guild_id, user_id, cutoff),
            )

            # Rank reputation (combien de joueurs ont plus que moi cette semaine)
            try:
                async with db.execute(
                    "SELECT user_id, SUM(points) AS pts "
                    "FROM reputation_history "
                    "WHERE guild_id=? AND created_at >= ? "
                    "GROUP BY user_id ORDER BY pts DESC",
                    (guild_id, cutoff),
                ) as cur:
                    rows = await cur.fetchall()
                for i, r in enumerate(rows, 1):
                    if int(r[0]) == user_id:
                        out["rank_reputation"] = i
                        break
            except Exception:
                pass

        # Style (via player_styles)
        try:
            import player_profile as pp
            out["style"] = await pp.get_primary_style(guild_id, user_id)
        except Exception:
            pass

    except Exception as ex:
        print(f"[weekly_stats get_user_weekly_stats] {ex}")
    return out


async def get_top_n(
    guild_id: int, metric: str, n: int = 5,
) -> list[dict]:
    """Top N joueurs sur une metric précise des 7 derniers jours.

    metric : 'reputation' / 'boss_kill_final' / 'duel_win' / 'quest_complete'
             / 'voice_minutes' / 'drops_collected' / 'treasure_claim'
    """
    out = []
    if _get_db is None:
        return out
    cutoff = _week_cutoff_iso()
    try:
        async with _get_db() as db:
            if metric == "reputation":
                async with db.execute(
                    "SELECT user_id, SUM(points) AS pts "
                    "FROM reputation_history "
                    "WHERE guild_id=? AND created_at >= ? "
                    "GROUP BY user_id ORDER BY pts DESC LIMIT ?",
                    (guild_id, cutoff, n),
                ) as cur:
                    rows = await cur.fetchall()
            elif metric in (
                "boss_kill_final", "duel_win", "quest_complete",
                "treasure_claim", "riddle_first",
            ):
                async with db.execute(
                    "SELECT user_id, COUNT(*) AS cnt "
                    "FROM reputation_history "
                    "WHERE guild_id=? AND source=? AND created_at >= ? "
                    "GROUP BY user_id ORDER BY cnt DESC LIMIT ?",
                    (guild_id, metric, cutoff, n),
                ) as cur:
                    rows = await cur.fetchall()
            elif metric == "voice_minutes":
                async with db.execute(
                    "SELECT user_id, SUM(duration_seconds) / 60 AS m "
                    "FROM voice_activity_log "
                    "WHERE guild_id=? AND joined_at >= ? "
                    "GROUP BY user_id ORDER BY m DESC LIMIT ?",
                    (guild_id, cutoff, n),
                ) as cur:
                    rows = await cur.fetchall()
            elif metric == "drops_collected":
                async with db.execute(
                    "SELECT user_id, COUNT(*) AS cnt "
                    "FROM seasonal_drops_log "
                    "WHERE guild_id=? AND claimed_at >= ? "
                    "GROUP BY user_id ORDER BY cnt DESC LIMIT ?",
                    (guild_id, cutoff, n),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                rows = []

        for r in rows:
            out.append({
                "user_id": int(r[0]),
                "value": int(r[1] or 0),
            })
    except Exception as ex:
        print(f"[weekly_stats get_top_n {metric}] {ex}")
    return out


# ─── Panels V2 ──────────────────────────────────────────────────────────────

STYLE_EMOJI = {
    "pvp": "⚔️", "collector": "💎", "social": "🤝", "solo": "🎯",
    "balanced": "⚖️", "opted_out": "🔇",
}
STYLE_LABEL = {
    "pvp": "Combattant", "collector": "Collectionneur",
    "social": "Animateur", "solo": "Aventurier solo",
    "balanced": "Équilibré", "opted_out": "Tracking OFF",
}


def build_recap_panel(member: discord.Member):
    """Panel V2 du récap perso 7 jours."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _RecapPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            s = await get_user_weekly_stats(member.guild.id, member.id)
            items = []
            items.append(v2_title("📰  Ton récap des 7 derniers jours"))
            style_e = STYLE_EMOJI.get(s["style"], "⚖️")
            style_l = STYLE_LABEL.get(s["style"], "Équilibré")
            items.append(v2_subtitle(
                f"_Style détecté : {style_e} **{style_l}** · "
                f"Rang réputation : "
                f"{('**#' + str(s['rank_reputation']) + '**') if s['rank_reputation'] else '_non classé_'}_"
            ))
            items.append(v2_divider())

            # Phase 164.2 : "Prochaine étape" — réduit cognitive load.
            # Suggère 1-2 actions concrètes selon les stats faibles.
            suggestions = []
            if s.get("quests_done", 0) < 3:
                suggestions.append(
                    "🎯 **Réclame ta quête du jour** (bouton hub)"
                )
            if s.get("voice_minutes", 0) < 60:
                suggestions.append(
                    "🎙️ **Passe 1h en vocal cette semaine** "
                    "(coins ×2 si live créateur actif)"
                )
            if s.get("treasures", 0) == 0 and s.get("boss_kills_final", 0) == 0:
                suggestions.append(
                    "⚔️ **Participe à un event** "
                    "(boss raid, treasure hunt, mystery box)"
                )
            if s.get("reputation_gained", 0) == 0:
                suggestions.append(
                    "⭐ **Gagne tes premiers pts réputation** "
                    "via duel, quête ou boss"
                )
            if suggestions:
                items.append(v2_body("**👉  Prochaine étape**"))
                # Affiche les 2 premières — focus, pas surcharge
                for sug in suggestions[:2]:
                    items.append(v2_body(f"• {sug}"))
                items.append(v2_divider())

            # Combat
            items.append(v2_body("**⚔️  Combat**"))
            items.append(v2_body(
                f"• Boss kills (coup final) : `{s['boss_kills_final']}`\n"
                f"• Duels gagnés : `{s['duels_won']}`"
            ))
            items.append(v2_divider())

            # Économie / Collecte
            items.append(v2_body("**💎  Collecte**"))
            items.append(v2_body(
                f"• Trésors récupérés : `{s['treasures']}`\n"
                f"• Drops saisonniers : `{s['drops_collected']}`"
            ))
            items.append(v2_divider())

            # Solo
            items.append(v2_body("**🎯  Solo / Daily**"))
            items.append(v2_body(
                f"• Quêtes complétées : `{s['quests_done']}`\n"
                f"• Énigmes 1ère place : `{s['riddles_solved']}`"
            ))
            items.append(v2_divider())

            # Voice
            items.append(v2_body("**🎙️  Voice activity**"))
            items.append(v2_body(
                f"• Minutes en vocal : `{s['voice_minutes']:,}`\n"
                f"• Coins voice gagnés : `{s['voice_coins_earned']}` 🪙"
            ))
            items.append(v2_divider())

            # Réputation
            items.append(v2_body(
                f"**⭐ Réputation gagnée :** "
                f"`+{s['reputation_gained']}` points"
            ))

            self.add_item(v2_container(*items, color=0x9B59B6))

    return _RecapPanel()


def build_leaderboard_panel(guild: discord.Guild):
    """Panel V2 avec les top 5 publics."""
    if _v2 is None or guild is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    METRICS = [
        ("reputation",    "⭐ Top Réputation",       "pts"),
        ("boss_kill_final", "⚔️ Top Boss Killers",  "kills"),
        ("voice_minutes", "🎙️ Top Voice (min)",     "min"),
        ("quest_complete", "🎯 Top Quêtes",         "quêtes"),
        ("drops_collected", "💎 Top Drops",          "drops"),
    ]

    class _LBPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            items = []
            items.append(v2_title("🏆  Leaderboards de la semaine"))
            items.append(v2_subtitle(
                f"_Top 5 sur les 7 derniers jours · {guild.name}_"
            ))
            items.append(v2_divider())

            medals = ["🥇", "🥈", "🥉", "4.", "5."]
            for metric_key, label, unit in METRICS:
                top = await get_top_n(guild.id, metric_key, 5)
                items.append(v2_body(f"**{label}**"))
                if not top:
                    items.append(v2_body(
                        "_Aucune donnée cette semaine_"
                    ))
                else:
                    for i, u in enumerate(top):
                        m = guild.get_member(u["user_id"])
                        name = m.display_name if m else f"User-{u['user_id']}"
                        medal = (
                            medals[i] if i < 3 else f"`{i + 1}.`"
                        )
                        items.append(v2_body(
                            f"{medal} **{name}** — `{u['value']:,}` {unit}"
                        ))
                items.append(v2_divider())

            items.append(v2_body(
                "_Reset chaque lundi 9h FR. Continue à jouer pour grimper !_"
            ))
            self.add_item(v2_container(*items, color=0xF1C40F))

    return _LBPanel()


# ─── Auto-post task ─────────────────────────────────────────────────────────

@tasks.loop(hours=1)
async def weekly_post_task():
    """Check : lundi 9h FR → post les leaderboards dans le hub."""
    try:
        if _bot is None or _v2 is None:
            return
        now_paris = (
            datetime.now(_PARIS_TZ) if _PARIS_TZ
            else datetime.now(timezone.utc) + timedelta(hours=2)
        )
        # Lundi = 0, hour = 9
        if now_paris.weekday() != 0 or now_paris.hour != 9:
            return

        for g in _bot.guilds:
            try:
                # Trouve un salon hub
                target = None
                for ch in g.text_channels:
                    n = ch.name.lower()
                    if "hub" in n or "general" in n or "💫" in n:
                        if ch.permissions_for(g.me).send_messages:
                            target = ch
                            break
                if target is None:
                    continue

                panel = build_leaderboard_panel(g)
                if panel:
                    await panel.populate()
                    await target.send(view=panel)
            except Exception as ex:
                print(f"[weekly_post_task g={g.id}] {ex}")
            await asyncio.sleep(3)
    except Exception as ex:
        print(f"[weekly_post_task] {ex}")


@weekly_post_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "get_user_weekly_stats",
    "get_top_n",
    "build_recap_panel",
    "build_leaderboard_panel",
    "weekly_post_task",
]
