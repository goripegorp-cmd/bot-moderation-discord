"""
pet_evolution.py — Évolution dynamique des pets (Phase 153).

🎯 OBJECTIF : transformer les pets statiques en compagnons qui grandissent.
Nourrir 1×/jour → XP → level pet → débloque nouveaux buffs + skin évolué.

Mécanique :
- Pet level 0-50
- XP requis : level² × 100 (ex: lvl 10 = 10 000 XP cumulés)
- Sources d'XP :
  • Feed 1×/jour : +50 XP
  • Pet actif pendant event (boss, treasure, etc.) : +10 XP par event
  • Boss kill final avec pet actif : +50 XP
- Skins évolués débloqués à level 10 / 25 / 50

Anti-cheese :
- 1 feed/24h max (cooldown strict)
- XP n'augmente que si le pet est ÉQUIPÉ pendant l'event

API publique :
- setup(get_db_fn, db_get_fn, v2_helpers)
- get_pet_evolution(guild_id, user_id, pet_slug) -> dict
- feed_pet(guild_id, user_id, pet_slug) -> dict (success, xp_gained, cooldown)
- gain_xp_from_event(guild_id, user_id, event_kind) -> dict
- get_evolved_skin(pet_slug, level) -> dict (emoji, name, suffix)
- build_pet_evolution_panel(member, pet_slug) -> LayoutView

DB tables :
- pet_evolution (guild_id, user_id, pet_slug, level, xp_total,
                 last_fed_at, evolved_skin_idx,
                 PRIMARY KEY (guild_id, user_id, pet_slug))
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ui import Button

# ─── Config ────────────────────────────────────────────────────────────────
_get_db = None
_db_get = None
_v2 = None

# Skins évolués par pet (suffix + emoji change à level 10/25/50).
# Phase 163.6 : aligné sur engagement41.PETS — clés = pet `id` legacy
# (cat/dog/dragon/wolf/fox/robot) pour que le wiring marche directement
# avec _get_active_pet du bot.py.
EVOLVED_SKINS = {
    "cat": [
        {"name": "Chat",           "emoji": "🐱", "min_lvl": 0},
        {"name": "Chat Agile",     "emoji": "🐈", "min_lvl": 10},
        {"name": "Chat Tigré",     "emoji": "🐅", "min_lvl": 25},
        {"name": "Lion Cosmique",  "emoji": "🦁", "min_lvl": 50},
    ],
    "dog": [
        {"name": "Chien",          "emoji": "🐶", "min_lvl": 0},
        {"name": "Loup",           "emoji": "🐺", "min_lvl": 10},
        {"name": "Loup Alpha",     "emoji": "⚔️🐺", "min_lvl": 25},
        {"name": "Fenrir",         "emoji": "🌑🐺", "min_lvl": 50},
    ],
    "dragon": [
        {"name": "Dragon",         "emoji": "🐲", "min_lvl": 0},
        {"name": "Dragon Ardent",  "emoji": "🔥🐲", "min_lvl": 10},
        {"name": "Dragon Tempête", "emoji": "⚡🐲", "min_lvl": 25},
        {"name": "Dragon Légendaire","emoji": "✨🐉", "min_lvl": 50},
    ],
    "wolf": [
        {"name": "Loup",           "emoji": "🐺", "min_lvl": 0},
        {"name": "Loup Garou",     "emoji": "🌙🐺", "min_lvl": 10},
        {"name": "Loup Lunaire",   "emoji": "🌕🐺", "min_lvl": 25},
        {"name": "Fenrir Mythique","emoji": "⚔️🌑", "min_lvl": 50},
    ],
    "fox": [
        {"name": "Renard",         "emoji": "🦊", "min_lvl": 0},
        {"name": "Renard Rusé",    "emoji": "🍃🦊", "min_lvl": 10},
        {"name": "Kitsune",        "emoji": "🌸🦊", "min_lvl": 25},
        {"name": "Esprit Renard",  "emoji": "✨🦊", "min_lvl": 50},
    ],
    "robot": [
        {"name": "Bot v1",         "emoji": "🤖", "min_lvl": 0},
        {"name": "Drone",          "emoji": "🛸", "min_lvl": 10},
        {"name": "Mecha",          "emoji": "⚙️🤖", "min_lvl": 25},
        {"name": "Conscience IA",  "emoji": "👁️🤖", "min_lvl": 50},
    ],
}

FEED_COOLDOWN_HOURS = 24
FEED_XP = 50
EVENT_XP = 10
BOSS_FINAL_XP = 50


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
                CREATE TABLE IF NOT EXISTS pet_evolution (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    pet_slug TEXT NOT NULL,
                    level INTEGER DEFAULT 0,
                    xp_total INTEGER DEFAULT 0,
                    last_fed_at TIMESTAMP,
                    evolved_skin_idx INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, pet_slug)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[pet_evolution init_db] {ex}")


def _xp_for_level(level: int) -> int:
    """XP cumulé requis pour atteindre ce level."""
    return level * level * 100


def _level_for_xp(xp: int) -> int:
    """Level atteint avec ce nombre d'XP cumulé."""
    if xp <= 0:
        return 0
    # level = floor(sqrt(xp / 100))
    level = 0
    while _xp_for_level(level + 1) <= xp and level < 50:
        level += 1
    return level


def get_evolved_skin(pet_slug: str, level: int) -> dict:
    """Renvoie le skin actuel selon le level."""
    skins = EVOLVED_SKINS.get(pet_slug, EVOLVED_SKINS["fox"])
    current = skins[0]
    for s in skins:
        if level >= s["min_lvl"]:
            current = s
        else:
            break
    return current


async def get_pet_evolution(
    guild_id: int, user_id: int, pet_slug: str,
) -> dict:
    """Récupère l'évolution d'un pet."""
    out = {
        "level": 0,
        "xp_total": 0,
        "last_fed_at": None,
        "can_feed_in_min": 0,
        "skin": get_evolved_skin(pet_slug, 0),
        "xp_to_next": _xp_for_level(1),
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT level, xp_total, last_fed_at FROM pet_evolution "
                "WHERE guild_id=? AND user_id=? AND pet_slug=?",
                (guild_id, user_id, pet_slug),
            ) as cur:
                row = await cur.fetchone()
        if row:
            out["level"] = int(row[0] or 0)
            out["xp_total"] = int(row[1] or 0)
            out["last_fed_at"] = row[2]
        out["skin"] = get_evolved_skin(pet_slug, out["level"])
        # XP to next level
        if out["level"] < 50:
            out["xp_to_next"] = _xp_for_level(out["level"] + 1) - out["xp_total"]
        else:
            out["xp_to_next"] = 0

        # Feed cooldown
        if out["last_fed_at"]:
            try:
                last = (
                    datetime.fromisoformat(str(out["last_fed_at"]).replace("Z", "+00:00"))
                    if "T" in str(out["last_fed_at"]) else
                    datetime.strptime(
                        str(out["last_fed_at"]), "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                )
                elapsed = (datetime.now(timezone.utc) - last).total_seconds()
                remaining = FEED_COOLDOWN_HOURS * 3600 - elapsed
                if remaining > 0:
                    out["can_feed_in_min"] = int(remaining // 60)
            except Exception:
                pass
    except Exception as ex:
        print(f"[pet_evolution get_pet] {ex}")
    return out


async def feed_pet(
    guild_id: int, user_id: int, pet_slug: str,
) -> dict:
    """Nourrit le pet. Retourne {success, xp_gained, new_level, skin_upgrade}."""
    out = {"success": False, "xp_gained": 0, "new_level": 0,
           "skin_upgrade": None, "cooldown_min": 0}
    if _get_db is None:
        return out
    current = await get_pet_evolution(guild_id, user_id, pet_slug)
    if current.get("can_feed_in_min", 0) > 0:
        out["cooldown_min"] = current["can_feed_in_min"]
        return out
    try:
        new_xp = current["xp_total"] + FEED_XP
        new_level = _level_for_xp(new_xp)
        old_skin = get_evolved_skin(pet_slug, current["level"])
        new_skin = get_evolved_skin(pet_slug, new_level)

        async with _get_db() as db:
            await db.execute(
                "INSERT INTO pet_evolution "
                "(guild_id, user_id, pet_slug, level, xp_total, last_fed_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id, pet_slug) DO UPDATE SET "
                "level = ?, xp_total = ?, last_fed_at = CURRENT_TIMESTAMP",
                (
                    guild_id, user_id, pet_slug, new_level, new_xp,
                    new_level, new_xp,
                ),
            )
            await db.commit()

        out["success"] = True
        out["xp_gained"] = FEED_XP
        out["new_level"] = new_level
        if new_skin["name"] != old_skin["name"]:
            out["skin_upgrade"] = new_skin
        return out
    except Exception as ex:
        print(f"[pet_evolution feed_pet] {ex}")
        return out


async def gain_xp_from_event(
    guild_id: int, user_id: int, pet_slug: str, event_kind: str,
) -> Optional[dict]:
    """Le pet équipé gagne de l'XP lors d'un event. Renvoie {level_up} si upgrade."""
    if _get_db is None or not pet_slug:
        return None
    xp = BOSS_FINAL_XP if event_kind == "boss_kill_final" else EVENT_XP
    try:
        current = await get_pet_evolution(guild_id, user_id, pet_slug)
        new_xp = current["xp_total"] + xp
        new_level = _level_for_xp(new_xp)
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO pet_evolution "
                "(guild_id, user_id, pet_slug, level, xp_total) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, pet_slug) DO UPDATE SET "
                "level = ?, xp_total = ?",
                (guild_id, user_id, pet_slug, new_level, new_xp,
                 new_level, new_xp),
            )
            await db.commit()
        if new_level > current["level"]:
            new_skin = get_evolved_skin(pet_slug, new_level)
            old_skin = get_evolved_skin(pet_slug, current["level"])
            return {
                "level_up": True,
                "new_level": new_level,
                "old_level": current["level"],
                "skin_upgrade": (
                    new_skin if new_skin["name"] != old_skin["name"]
                    else None
                ),
            }
        return None
    except Exception as ex:
        print(f"[pet_evolution gain_xp] {ex}")
        return None


def build_pet_evolution_panel(member: discord.Member, pet_slug: str):
    """Panel V2 affichant l'évolution + bouton 'Nourrir'."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _PetPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            data = await get_pet_evolution(
                member.guild.id, member.id, pet_slug,
            )
            skin = data["skin"]
            items = []
            items.append(v2_title(f"{skin['emoji']}  {skin['name']}"))
            items.append(v2_subtitle(
                f"_Niveau {data['level']} · "
                f"{data['xp_total']:,} XP cumulés_"
            ))
            items.append(v2_divider())

            # Progress bar
            if data["level"] < 50:
                xp_current_level = _xp_for_level(data["level"])
                xp_next_level = _xp_for_level(data["level"] + 1)
                in_level = data["xp_total"] - xp_current_level
                needed = xp_next_level - xp_current_level
                pct = int(in_level * 100 / max(1, needed))
                bar_filled = int((in_level / max(1, needed)) * 20)
                bar = "█" * bar_filled + "░" * (20 - bar_filled)
                items.append(v2_body(
                    f"**Progression :** `{bar}` {pct}%\n"
                    f"`{in_level}/{needed}` XP vers level **{data['level'] + 1}**"
                ))
            else:
                items.append(v2_body(
                    "🌟 **Niveau maximum atteint !** "
                    "Ton compagnon est désormais légendaire."
                ))

            # Skin upgrades à venir
            next_evol = None
            for s in EVOLVED_SKINS.get(pet_slug, []):
                if s["min_lvl"] > data["level"]:
                    next_evol = s
                    break
            if next_evol:
                items.append(v2_body(
                    f"_Prochaine évolution : {next_evol['emoji']} "
                    f"**{next_evol['name']}** au niveau **{next_evol['min_lvl']}**_"
                ))

            # Cooldown
            items.append(v2_divider())
            if data["can_feed_in_min"] > 0:
                h = data["can_feed_in_min"] // 60
                m = data["can_feed_in_min"] % 60
                items.append(v2_body(
                    f"⏳ Prochain repas dans **{h}h {m}min**"
                ))
            else:
                items.append(v2_body(
                    f"✅ **Prêt à manger !** Clique sur 🍖 Nourrir pour "
                    f"gagner `+{FEED_XP}` XP."
                ))
            self.add_item(v2_container(*items, color=0xE67E22))

            # Bouton Feed
            if data["can_feed_in_min"] <= 0:
                btn = Button(
                    label=f"🍖 Nourrir (+{FEED_XP} XP)",
                    style=discord.ButtonStyle.success,
                )

                async def _cb(i: discord.Interaction):
                    if i.user.id != member.id:
                        return await i.response.send_message(
                            "🔒 Pas pour toi.", ephemeral=True
                        )
                    result = await feed_pet(
                        member.guild.id, member.id, pet_slug,
                    )
                    if result["success"]:
                        msg = (
                            f"🍖 **{skin['name']}** a mangé ! "
                            f"+`{result['xp_gained']}` XP."
                        )
                        if result.get("skin_upgrade"):
                            up = result["skin_upgrade"]
                            msg += (
                                f"\n\n✨ **ÉVOLUTION !** Ton compagnon "
                                f"devient **{up['name']}** {up['emoji']} !"
                            )
                        await i.response.send_message(msg, ephemeral=True)
                    else:
                        cd = result.get("cooldown_min", 0)
                        await i.response.send_message(
                            f"⏳ Pas encore l'heure du repas — "
                            f"reviens dans **{cd // 60}h {cd % 60}min**.",
                            ephemeral=True,
                        )

                btn.callback = _cb
                # Phase 235.5 : bouton nu → ActionRow (top-level LayoutView).
                self.add_item(discord.ui.ActionRow(btn))

    return _PetPanel()


__all__ = [
    "setup",
    "init_db",
    "get_pet_evolution",
    "feed_pet",
    "gain_xp_from_event",
    "get_evolved_skin",
    "build_pet_evolution_panel",
    "EVOLVED_SKINS",
]
