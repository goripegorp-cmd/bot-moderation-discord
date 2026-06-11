"""
reputation.py — Système de Réputation lent à long terme (Phase 153).

🎯 OBJECTIF : récompenser l'engagement cumulé sur le long terme avec
des badges permanents visibles dans /profile.

Pas un grind PvP — c'est juste l'historique du joueur sur le serveur.

Sources de gain :
- Saga win (top 5 contributors) : +5
- Boss kill final (last hit) : +3
- Duel won : +2
- Tournament won (1ère place) : +20
- Drop exclusif saison : +1
- World boss top 3 damager : +5
- Quête journalière complétée : +1
- Riddle 1st place : +2
- Treasure flash claim : +1

Tiers (palier permanent — jamais redescend) :
- 0-99    : 🌱 Nouveau
- 100-499 : 🎯 Apprenti
- 500-1999: ⚔️ Vétéran
- 2000-4999: 🏆 Légende
- 5000+   : 🔮 Mythique

API publique :
- setup(get_db_fn, db_get_fn, v2_helpers)
- add_points(guild_id, user_id, source, points)
- get_reputation(guild_id, user_id) -> dict
- get_tier(points) -> dict
- get_top_n(guild_id, n=10) -> list[dict]
- build_reputation_panel(member) -> LayoutView

DB tables :
- reputation (guild_id, user_id, total_points, last_gain_at,
              tier_reached, PRIMARY KEY (guild_id, user_id))
- reputation_history (id PK, guild_id, user_id, source, points,
                      created_at) — pour audit
"""
from __future__ import annotations

from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_get_db = None
_db_get = None
_v2 = None

# Tiers de réputation
TIERS = [
    {"name": "Nouveau", "emoji": "🌱", "min": 0,    "color": 0x95A5A6},
    {"name": "Apprenti","emoji": "🎯", "min": 100,  "color": 0x3498DB},
    {"name": "Vétéran", "emoji": "⚔️", "min": 500,  "color": 0xE67E22},
    {"name": "Légende", "emoji": "🏆", "min": 2000, "color": 0xF1C40F},
    {"name": "Mythique","emoji": "🔮", "min": 5000, "color": 0x9B59B6},
]

# Source → points map
SOURCE_POINTS = {
    "saga_top_contributor": 5,
    "boss_kill_final":      3,
    "duel_win":             2,
    "tournament_win":       20,
    "season_drop":          1,
    "world_boss_top3":      5,
    "quest_complete":       1,
    "riddle_first":         2,
    "treasure_claim":       1,
    "achievement_unlock":   2,
    "alliance_milestone":   3,
}


def setup(get_db_fn, db_get_fn, v2_helpers: dict):
    global _get_db, _db_get, _v2
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reputation (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total_points INTEGER DEFAULT 0,
                    last_gain_at TIMESTAMP,
                    tier_reached TEXT DEFAULT 'Nouveau',
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reputation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    source TEXT,
                    points INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_reputation_top "
                "ON reputation(guild_id, total_points DESC)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[reputation init_db] {ex}")


def get_tier(points: int) -> dict:
    """Renvoie le tier pour un nombre de points."""
    tier = TIERS[0]
    for t in TIERS:
        if points >= t["min"]:
            tier = t
        else:
            break
    return tier


def get_next_tier(points: int) -> Optional[dict]:
    """Tier suivant (None si déjà mythique)."""
    for t in TIERS:
        if points < t["min"]:
            return t
    return None


async def add_points(
    guild_id: int, user_id: int, source: str,
    points: Optional[int] = None,
) -> Optional[dict]:
    """Ajoute des points de réputation. Retourne dict {old_tier, new_tier,
    new_total} si tier upgrade, sinon None.
    """
    if _get_db is None:
        return None
    pts = points if points is not None else SOURCE_POINTS.get(source, 0)
    if pts <= 0:
        return None
    try:
        async with _get_db() as db:
            # Get current
            async with db.execute(
                "SELECT total_points FROM reputation "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
            old_total = int(row[0] if row else 0)
            new_total = old_total + pts

            old_tier = get_tier(old_total)
            new_tier = get_tier(new_total)

            # Upsert
            await db.execute(
                "INSERT INTO reputation "
                "(guild_id, user_id, total_points, last_gain_at, "
                "tier_reached) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "total_points = total_points + ?, "
                "last_gain_at = CURRENT_TIMESTAMP, "
                "tier_reached = ?",
                (
                    guild_id, user_id, pts, new_tier["name"],
                    pts, new_tier["name"],
                ),
            )
            # History
            await db.execute(
                "INSERT INTO reputation_history "
                "(guild_id, user_id, source, points) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, source, pts),
            )
            await db.commit()

        # Tier upgrade ?
        if new_tier["name"] != old_tier["name"]:
            return {
                "old_tier": old_tier,
                "new_tier": new_tier,
                "new_total": new_total,
                "points_added": pts,
            }
        return None
    except Exception as ex:
        print(f"[reputation add_points {source}] {ex}")
        return None


async def get_reputation(guild_id: int, user_id: int) -> dict:
    """Renvoie le profil de réputation complet d'un user."""
    out = {
        "total_points": 0,
        "tier": TIERS[0],
        "next_tier": TIERS[1],
        "progress_to_next": 0,
        "last_gain_at": None,
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT total_points, last_gain_at FROM reputation "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            out["total_points"] = int(row[0] or 0)
            out["last_gain_at"] = row[1]
        out["tier"] = get_tier(out["total_points"])
        next_t = get_next_tier(out["total_points"])
        out["next_tier"] = next_t
        if next_t:
            tier_start = out["tier"]["min"]
            tier_end = next_t["min"]
            if tier_end > tier_start:
                progress = (
                    (out["total_points"] - tier_start) /
                    (tier_end - tier_start)
                )
                out["progress_to_next"] = max(0.0, min(1.0, progress))
    except Exception:
        pass
    return out


async def get_top_n(guild_id: int, n: int = 10) -> list[dict]:
    """Top N joueurs par réputation cumulée."""
    out = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, total_points, tier_reached "
                "FROM reputation WHERE guild_id=? AND total_points > 0 "
                "ORDER BY total_points DESC LIMIT ?",
                (guild_id, n),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "user_id": int(r[0]),
                "total_points": int(r[1] or 0),
                "tier_reached": r[2] or "Nouveau",
            })
    except Exception:
        pass
    return out


def build_reputation_panel(member: discord.Member):
    """Panel V2 affichant la réputation + top + history."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _ReputationPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.member = member

        async def populate(self):
            rep = await get_reputation(member.guild.id, member.id)
            top = await get_top_n(member.guild.id, 5)
            items = []
            items.append(v2_title(f"{rep['tier']['emoji']} Réputation"))
            items.append(v2_subtitle(
                f"-# {member.display_name} · `{rep['total_points']:,}` points cumulés"
            ))
            items.append(v2_divider())

            # Tier actuel + progression
            items.append(v2_body(
                f"Tier · {rep['tier']['emoji']} **{rep['tier']['name']}**"
            ))
            if rep.get("next_tier"):
                nt = rep["next_tier"]
                pct = int(rep["progress_to_next"] * 100)
                bar_len = 20
                filled = int(rep["progress_to_next"] * bar_len)
                bar = "█" * filled + "░" * (bar_len - filled)
                items.append(v2_body(
                    f"Prochain · {nt['emoji']} **{nt['name']}** à `{nt['min']:,}` pts\n"
                    f"`{bar}` {pct}%"
                ))
            else:
                items.append(v2_body(
                    "🌟 **Tier maximum atteint** — légende du serveur !"
                ))

            # Top 5
            if top:
                items.append(v2_divider())
                items.append(v2_body("### 🏅 Top 5 réputation du serveur"))
                lines = []
                for i, u in enumerate(top, 1):
                    m = member.guild.get_member(u["user_id"])
                    name = m.display_name if m else f"User-{u['user_id']}"
                    tier = get_tier(u["total_points"])
                    medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"`{i}.`"
                    lines.append(
                        f"{medal} **{name}** {tier['emoji']} — `{u['total_points']:,}` pts"
                    )
                items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "-# 💡 La réputation se gagne en participant : events, boss, duels, sagas."
            ))
            self.add_item(v2_container(*items, color=rep["tier"]["color"]))

    return _ReputationPanel()


__all__ = [
    "setup",
    "init_db",
    "add_points",
    "get_reputation",
    "get_tier",
    "get_next_tier",
    "get_top_n",
    "build_reputation_panel",
    "TIERS",
    "SOURCE_POINTS",
]
