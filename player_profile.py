"""
player_profile.py — Tracking style de jeu + personnalisation (Phase 149).

🎯 OBJECTIF : connaître le style de jeu de chaque membre pour lui
proposer des events qui matchent. Subtil, jamais intrusif.

Profils :
- **PvP** : duels, combat boss, ladder, faction wars
- **Collecteur** : drops, mystery box, treasure, crafting
- **Social** : alliances, voice time, animateur
- **Solo** : quêtes, riddles, wheel, prediction

Chaque action ajoute des points dans la catégorie correspondante.
Le profil dominant est utilisé pour :
- Suggérer des events via DM (à coupler avec dormant_wakeup)
- Biaiser les drops favorablement (collecteur → cosmétiques)
- Personnaliser le panel `/profile`

Opt-out via bouton dans `/profile` → set `personalization_enabled=0`.

API publique :
- setup(get_db_fn, db_get_fn, v2_helpers)
- track_action(guild_id, user_id, action_kind) — appelable depuis hooks
- get_primary_style(guild_id, user_id) -> str
- get_profile(guild_id, user_id) -> dict
- toggle_personalization(guild_id, user_id) -> bool (nouvelle valeur)
- build_personalization_panel(member) -> LayoutView

DB tables :
- player_styles (guild_id, user_id, pvp, collector, social, solo,
                 personalization_enabled, last_updated)

Mapping action → bucket :
- duel_win, duel_loss, boss_attack, ladder_match → pvp
- treasure_open, mystery_open, drop_claim, craft → collector
- alliance_join, voice_join, message_event → social
- riddle_solve, quest_complete, wheel_spin, prediction → solo
"""
from __future__ import annotations

from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_get_db = None
_db_get = None
_v2 = None

ACTION_TO_BUCKET = {
    # PvP
    "duel_win": "pvp", "duel_loss": "pvp", "duel": "pvp",
    "boss_attack": "pvp", "boss_kill": "pvp",
    "ladder_match": "pvp", "world_boss_attack": "pvp",
    "faction_war": "pvp", "tournament": "pvp",
    # Collector
    "treasure_open": "collector", "mystery_open": "collector",
    "drop_claim": "collector", "craft": "collector",
    "auction_win": "collector", "trade": "collector",
    "inventory_browse": "collector",
    # Social
    "alliance_join": "social", "voice_join": "social",
    "voice_time_hour": "social", "message_event_join": "social",
    "shoutout_send": "social",
    # Solo
    "riddle_solve": "solo", "quest_complete": "solo",
    "wheel_spin": "solo", "prediction_vote": "solo",
    "daily_claim": "solo", "achievement_unlock": "solo",
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
                CREATE TABLE IF NOT EXISTS player_styles (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    pvp INTEGER DEFAULT 0,
                    collector INTEGER DEFAULT 0,
                    social INTEGER DEFAULT 0,
                    solo INTEGER DEFAULT 0,
                    personalization_enabled INTEGER DEFAULT 1,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[player_profile init_db] {ex}")


async def track_action(
    guild_id: int, user_id: int, action_kind: str, weight: int = 1,
):
    """Incrémente le bucket correspondant. Silent / non-bloquant."""
    if _get_db is None or not action_kind:
        return
    bucket = ACTION_TO_BUCKET.get(action_kind)
    if bucket is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                f"INSERT INTO player_styles "
                f"(guild_id, user_id, {bucket}) VALUES (?, ?, ?) "
                f"ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                f"{bucket} = {bucket} + ?, "
                f"last_updated = CURRENT_TIMESTAMP",
                (guild_id, user_id, weight, weight),
            )
            await db.commit()
    except Exception as ex:
        print(f"[player_profile track_action {action_kind}] {ex}")


async def get_profile(guild_id: int, user_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT pvp, collector, social, solo, "
                "personalization_enabled FROM player_styles "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return {
                "pvp": 0, "collector": 0, "social": 0, "solo": 0,
                "personalization_enabled": True,
            }
        return {
            "pvp": int(row[0] or 0),
            "collector": int(row[1] or 0),
            "social": int(row[2] or 0),
            "solo": int(row[3] or 0),
            "personalization_enabled": bool(row[4]),
        }
    except Exception as ex:
        print(f"[player_profile get_profile] {ex}")
        return None


async def get_primary_style(guild_id: int, user_id: int) -> str:
    """Renvoie le style dominant : 'pvp', 'collector', 'social', 'solo',
    ou 'balanced' si pas assez de data."""
    p = await get_profile(guild_id, user_id)
    if not p:
        return "balanced"
    if not p.get("personalization_enabled", True):
        return "opted_out"
    counts = {
        "pvp": p["pvp"], "collector": p["collector"],
        "social": p["social"], "solo": p["solo"],
    }
    total = sum(counts.values())
    if total < 10:
        return "balanced"
    top_kind = max(counts, key=counts.get)
    # Si le top n'est pas >= 40% du total, balanced
    if counts[top_kind] < total * 0.40:
        return "balanced"
    return top_kind


async def toggle_personalization(guild_id: int, user_id: int) -> bool:
    """Toggle on/off. Renvoie la nouvelle valeur."""
    if _get_db is None:
        return True
    try:
        async with _get_db() as db:
            # Ensure row exists
            await db.execute(
                "INSERT OR IGNORE INTO player_styles "
                "(guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            # Toggle
            await db.execute(
                "UPDATE player_styles SET "
                "personalization_enabled = 1 - personalization_enabled, "
                "last_updated = CURRENT_TIMESTAMP "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.commit()
            async with db.execute(
                "SELECT personalization_enabled FROM player_styles "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return bool(row[0]) if row else True
    except Exception as ex:
        print(f"[player_profile toggle] {ex}")
        return True


# ─── Panel V2 ──────────────────────────────────────────────────────────────

STYLE_EMOJI = {
    "pvp": "⚔️", "collector": "💎", "social": "🤝", "solo": "🎯",
    "balanced": "⚖️", "opted_out": "🔇",
}
STYLE_LABEL = {
    "pvp": "Combattant", "collector": "Collectionneur",
    "social": "Animateur", "solo": "Aventurier solo",
    "balanced": "Équilibré", "opted_out": "Personnalisation OFF",
}


def build_personalization_panel(member: discord.Member):
    """Mini-panel V2 pour le toggle. À insérer dans /profile."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    from discord.ui import Button

    class _PersoPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=180)
            items = []
            items.append(v2_title("🎯 Personnalisation"))
            items.append(v2_body(
                "Le bot peut adapter ses suggestions d'events à ton style de jeu "
                "(PvP, collecteur, social, solo).\n"
                "-# Désactivable à tout moment."
            ))
            self.add_item(v2_container(*items, color=0x3498DB))

            b = Button(
                label="🔁 Toggle personnalisation",
                style=discord.ButtonStyle.primary,
                custom_id=f"perso_toggle_{member.id}",
            )

            async def _cb(i: discord.Interaction):
                if i.user.id != member.id:
                    return await i.response.send_message(
                        "🔒 Pas pour toi.", ephemeral=True
                    )
                new_val = await toggle_personalization(
                    i.guild.id, member.id
                )
                state = "ACTIVÉE" if new_val else "DÉSACTIVÉE"
                await i.response.send_message(
                    f"✅ Personnalisation **{state}**.",
                    ephemeral=True,
                )

            b.callback = _cb
            # Phase 235 (fix 400 50035) : un bouton NU n'est pas un composant
            # top-level valide d'une LayoutView V2 — il DOIT être dans un ActionRow.
            self.add_item(discord.ui.ActionRow(b))

    return _PersoPanel()


__all__ = [
    "setup",
    "init_db",
    "track_action",
    "get_profile",
    "get_primary_style",
    "toggle_personalization",
    "build_personalization_panel",
    "STYLE_LABEL",
    "STYLE_EMOJI",
    "ACTION_TO_BUCKET",
]
