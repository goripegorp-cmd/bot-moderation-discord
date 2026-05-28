"""
mob_hunts.py — Combat fréquent multi-user contre des mobs (Phase 169.1).

🎯 OBJECTIF : donner du combat ACTIF dans le serveur sans attendre 6h
un boss. Mobs faciles (HP 50-200), spawn toutes les 30-45 min, TOUT
LE MONDE peut attaquer, drops proportionnels aux dégâts.

Différences vs Boss Raid :
- HP très bas (50-200 vs 5000+) → mort en 1-3 clics
- Pas de ping → message discret dans l'arène, delete-after 15min
- Plus fréquent (30-45 min vs 6h)
- Drops distribués à TOUS les attackers (pas seulement le finisher)
- Bonus alliance : 2+ membres alliance = +20% qualité drops

Mécanique :
- 12 types de mobs, stats + drop_table variés
- 1 mob "élite" sur 10 (HP × 5, drop garanti rare)
- Bouton "⚔️ Attaquer" : dégâts = base + random + pet bonus
- HP affiché en temps réel via edit_message
- Distribution loot quand HP <= 0

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- spawn_task (loop 30-45 min)
- MobAttackView : persistent View enregistrée au boot

DB :
- mob_spawns (id PK, guild_id, mob_kind, message_id, channel_id,
              is_elite, hp_max, hp_current, spawned_at, expires_at,
              killed_at, status)
- mob_attackers (mob_id, user_id, damage_dealt, attacks_count,
                  PRIMARY KEY (mob_id, user_id))
"""
from __future__ import annotations

import asyncio
import json
import random
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button, View

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

# Spawn interval (random entre min et max minutes)
SPAWN_MIN_MIN = 30
SPAWN_MAX_MIN = 45
# Durée avant despawn si pas tué
MOB_LIFETIME_MIN = 15
# Heures actives (FR) — pas de spawn la nuit
ACTIVE_HOUR_START = 10
ACTIVE_HOUR_END = 23
# Anti-spam : max N mobs simultanés / guild
MAX_CONCURRENT_MOBS = 2
# Bonus alliance : multiplicateur si 2+ membres alliance ont attacké
ALLIANCE_BONUS_MULT = 1.20
ALLIANCE_BONUS_MIN_MEMBERS = 2
# Probabilité d'apparition élite
ELITE_CHANCE = 0.10

# ─── Catalogue des mobs ────────────────────────────────────────────────────
# Format : {id, name, emoji, hp_base, attack_damage_per_click,
#           drop_coins_min, drop_coins_max, drop_item_chance, item_pool}
MOB_CATALOG = [
    {
        "id": "slime",
        "name": "Slime visqueux",
        "emoji": "🟢",
        "hp_base": 50,
        "damage_per_click": (8, 18),
        "drop_coins": (10, 50),
        "drop_item_chance": 0.05,
        "item_pool": ["potion", "common_gem"],
        "color": 0x2ECC71,
    },
    {
        "id": "rat",
        "name": "Rat sauvage",
        "emoji": "🐀",
        "hp_base": 60,
        "damage_per_click": (10, 20),
        "drop_coins": (15, 60),
        "drop_item_chance": 0.06,
        "item_pool": ["potion", "rope"],
        "color": 0x7F8C8D,
    },
    {
        "id": "goblin",
        "name": "Gobelin pillard",
        "emoji": "👺",
        "hp_base": 90,
        "damage_per_click": (12, 25),
        "drop_coins": (40, 120),
        "drop_item_chance": 0.10,
        "item_pool": ["dagger", "small_chest"],
        "color": 0x27AE60,
    },
    {
        "id": "wolf",
        "name": "Loup affamé",
        "emoji": "🐺",
        "hp_base": 110,
        "damage_per_click": (15, 30),
        "drop_coins": (50, 150),
        "drop_item_chance": 0.10,
        "item_pool": ["fang", "fur"],
        "color": 0x95A5A6,
    },
    {
        "id": "skeleton",
        "name": "Squelette",
        "emoji": "💀",
        "hp_base": 100,
        "damage_per_click": (12, 28),
        "drop_coins": (40, 130),
        "drop_item_chance": 0.12,
        "item_pool": ["bone", "rusty_sword"],
        "color": 0xECF0F1,
    },
    {
        "id": "zombie",
        "name": "Zombie rôdeur",
        "emoji": "🧟",
        "hp_base": 140,
        "damage_per_click": (10, 25),
        "drop_coins": (60, 180),
        "drop_item_chance": 0.12,
        "item_pool": ["rotten_flesh", "tattered_cloak"],
        "color": 0x4A4A4A,
    },
    {
        "id": "spider",
        "name": "Araignée géante",
        "emoji": "🕷️",
        "hp_base": 130,
        "damage_per_click": (14, 30),
        "drop_coins": (70, 200),
        "drop_item_chance": 0.12,
        "item_pool": ["silk", "venom_sac"],
        "color": 0x2C3E50,
    },
    {
        "id": "bandit",
        "name": "Bandit masqué",
        "emoji": "🥷",
        "hp_base": 150,
        "damage_per_click": (16, 35),
        "drop_coins": (100, 250),
        "drop_item_chance": 0.13,
        "item_pool": ["lockpick", "coin_pouch"],
        "color": 0x8B4513,
    },
    {
        "id": "troll",
        "name": "Troll des cavernes",
        "emoji": "👹",
        "hp_base": 180,
        "damage_per_click": (20, 40),
        "drop_coins": (120, 320),
        "drop_item_chance": 0.15,
        "item_pool": ["troll_hide", "stone_club"],
        "color": 0x16A085,
    },
    {
        "id": "wraith",
        "name": "Spectre maudit",
        "emoji": "👻",
        "hp_base": 160,
        "damage_per_click": (18, 38),
        "drop_coins": (130, 300),
        "drop_item_chance": 0.15,
        "item_pool": ["soul_shard", "ghost_dust"],
        "color": 0x9B59B6,
    },
    {
        "id": "gargoyle",
        "name": "Gargouille",
        "emoji": "🗿",
        "hp_base": 170,
        "damage_per_click": (15, 32),
        "drop_coins": (110, 280),
        "drop_item_chance": 0.14,
        "item_pool": ["stone_eye", "wing_fragment"],
        "color": 0x636E72,
    },
    {
        "id": "wizard",
        "name": "Sorcier noir",
        "emoji": "🧙",
        "hp_base": 200,
        "damage_per_click": (22, 45),
        "drop_coins": (180, 450),
        "drop_item_chance": 0.18,
        "item_pool": ["spell_scroll", "mana_crystal"],
        "color": 0x8E44AD,
    },
]


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
                CREATE TABLE IF NOT EXISTS mob_spawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    mob_kind TEXT NOT NULL,
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0,
                    is_elite INTEGER DEFAULT 0,
                    hp_max INTEGER NOT NULL,
                    hp_current INTEGER NOT NULL,
                    spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    killed_at TIMESTAMP,
                    status TEXT DEFAULT 'alive'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mob_attackers (
                    mob_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage_dealt INTEGER DEFAULT 0,
                    attacks_count INTEGER DEFAULT 0,
                    last_attack_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (mob_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mob_spawns_alive "
                "ON mob_spawns(guild_id, status, expires_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[mob_hunts init_db] {ex}")


def get_mob_def(mob_id: str) -> Optional[dict]:
    """Retourne la def d'un mob par son id."""
    for m in MOB_CATALOG:
        if m["id"] == mob_id:
            return m
    return None


def _is_active_hour() -> bool:
    """True si l'heure courante est dans la fenêtre active (Paris)."""
    if _PARIS_TZ:
        now = datetime.now(_PARIS_TZ)
    else:
        now = datetime.now(timezone.utc)
    return ACTIVE_HOUR_START <= now.hour < ACTIVE_HOUR_END


async def _count_alive_mobs(guild_id: int) -> int:
    """Compte les mobs encore vivants pour cette guild."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM mob_spawns "
                "WHERE guild_id=? AND status='alive' AND "
                "datetime(expires_at) > datetime('now')",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


async def _get_alliance_id(guild_id: int, user_id: int) -> Optional[int]:
    """Retourne l'alliance_id de l'user, None sinon."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT alliance_id FROM alliance_members "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


# ─── Spawn ─────────────────────────────────────────────────────────────────

async def _find_arena_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Trouve le salon arène pour spawn les mobs."""
    if _db_get is None:
        return None
    try:
        cfg_data = await _db_get(guild.id)
        # Reuse event_arena_channel s'il existe (set par boss raid)
        ch_id = (
            cfg_data.get("event_arena_channel_id", 0)
            or cfg_data.get("event_arena_channel", 0)
            or 0
        )
        if ch_id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                return ch
    except Exception:
        pass
    # Fallback : recherche par nom
    for ch in guild.text_channels:
        if any(k in ch.name.lower() for k in ["arena", "arène", "combat"]):
            return ch
    return None


async def spawn_mob(guild: discord.Guild) -> bool:
    """Spawn un mob aléatoire dans l'arène. Retourne True si succès."""
    if not guild or _get_db is None or _bot is None:
        return False
    if not _is_active_hour():
        return False
    if await _count_alive_mobs(guild.id) >= MAX_CONCURRENT_MOBS:
        return False

    ch = await _find_arena_channel(guild)
    if not ch:
        return False

    # Anti-doublon : pas le même type qu'un mob déjà vivant
    alive_kinds = set()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT mob_kind FROM mob_spawns "
                "WHERE guild_id=? AND status='alive' AND "
                "datetime(expires_at) > datetime('now')",
                (guild.id,),
            ) as cur:
                for r in await cur.fetchall():
                    alive_kinds.add(r[0])
    except Exception:
        pass
    pool = [m for m in MOB_CATALOG if m["id"] not in alive_kinds]
    if not pool:
        return False

    mob_def = random.choice(pool)
    is_elite = random.random() < ELITE_CHANCE
    hp_max = mob_def["hp_base"] * 5 if is_elite else mob_def["hp_base"]
    elite_prefix = "👑 " if is_elite else ""

    # INSERT en DB
    expires = datetime.now(timezone.utc) + timedelta(minutes=MOB_LIFETIME_MIN)
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO mob_spawns "
                "(guild_id, mob_kind, channel_id, is_elite, hp_max, hp_current, "
                "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    guild.id, mob_def["id"], ch.id,
                    1 if is_elite else 0, hp_max, hp_max,
                    expires.isoformat(),
                ),
            )
            mob_db_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[mob_hunts spawn INSERT] {ex}")
        return False

    # Build le panel V2
    msg = await _post_mob_message(ch, mob_db_id, mob_def, hp_max, hp_max, is_elite)
    if msg:
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE mob_spawns SET message_id=? WHERE id=?",
                    (msg.id, mob_db_id),
                )
                await db.commit()
        except Exception:
            pass

        # Schedule despawn cleanup
        asyncio.create_task(_despawn_after(mob_db_id, MOB_LIFETIME_MIN * 60))

    print(
        f"[mob_hunts] spawn guild={guild.id} mob={mob_def['id']} "
        f"elite={is_elite} hp={hp_max}"
    )
    return True


async def _post_mob_message(
    ch: discord.TextChannel, mob_db_id: int, mob_def: dict,
    hp_current: int, hp_max: int, is_elite: bool,
) -> Optional[discord.Message]:
    """Build et poste le message du mob."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    elite_prefix = "👑 ÉLITE — " if is_elite else ""
    pct = int((hp_current / hp_max) * 100) if hp_max else 0
    bar_len = 16
    filled = int((hp_current / hp_max) * bar_len) if hp_max else 0
    bar = "█" * filled + "░" * (bar_len - filled)

    drop_min, drop_max = mob_def["drop_coins"]
    if is_elite:
        drop_min *= 3
        drop_max *= 3
    drop_item_pct = int(mob_def["drop_item_chance"] * 100)
    if is_elite:
        drop_item_pct = min(100, drop_item_pct * 3)

    items = []
    items.append(v2_title(
        f"{elite_prefix}{mob_def['emoji']} {mob_def['name']}"
    ))
    items.append(v2_subtitle(
        f"_Mob apparu — cliquez pour attaquer · "
        f"despawn dans {MOB_LIFETIME_MIN}min_"
    ))
    items.append(v2_divider())
    items.append(v2_body(
        f"**❤️ HP :** `{bar}` `{hp_current}/{hp_max}` ({pct}%)\n"
        f"**💰 Drop :** `{drop_min}-{drop_max}` 🪙 · "
        f"**🎁 Item :** `{drop_item_pct}%`"
    ))
    items.append(v2_divider())
    items.append(v2_body(
        "_⚔️ Tout le monde peut frapper · loot proportionnel "
        "aux dégâts · **bonus alliance** si 2+ membres alliance attaquent._"
    ))

    color = 0xFFD700 if is_elite else mob_def.get("color", 0x95A5A6)

    class _MobLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=color))

    layout = _MobLayout()
    layout.add_item(MobAttackButton(mob_db_id))

    try:
        msg = await ch.send(view=layout)
        return msg
    except Exception as ex:
        print(f"[mob_hunts post_message] {ex}")
        return None


# ─── Attack button ─────────────────────────────────────────────────────────

class MobAttackButton(discord.ui.DynamicItem[Button], template=r"mob_attack:(?P<mob_id>\d+)"):
    """Persistent button via DynamicItem — survit aux reboots."""

    def __init__(self, mob_id: int):
        super().__init__(
            Button(
                label="⚔️ Attaquer",
                style=discord.ButtonStyle.danger,
                custom_id=f"mob_attack:{mob_id}",
            )
        )
        self.mob_id = mob_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["mob_id"]))

    async def callback(self, btn_i: discord.Interaction):
        # Defer immédiat — multi-DB ops à suivre
        try:
            await btn_i.response.defer()
        except Exception:
            pass

        try:
            await _process_attack(btn_i, self.mob_id)
        except Exception as ex:
            print(f"[mob_attack callback] {ex}")
            try:
                await btn_i.followup.send(
                    f"❌ Erreur : `{ex}`", ephemeral=True
                )
            except Exception:
                pass


async def _process_attack(btn_i: discord.Interaction, mob_id: int):
    """Logique d'attaque : applique dégâts + update message + check kill."""
    if _get_db is None or btn_i.guild is None:
        return

    # Récupère le mob
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, mob_kind, message_id, channel_id, "
                "is_elite, hp_max, hp_current, status FROM mob_spawns "
                "WHERE id=?",
                (mob_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return await btn_i.followup.send("❌ Mob introuvable.", ephemeral=True)
        gid, mob_kind, msg_id, ch_id, is_elite, hp_max, hp_curr, status = row
        if status != "alive":
            return await btn_i.followup.send(
                "💀 Ce mob est déjà mort.", ephemeral=True
            )

        mob_def = get_mob_def(mob_kind)
        if not mob_def:
            return

        # Calcul dégâts : base + random + petit bonus pet si éligible
        dmg_min, dmg_max = mob_def["damage_per_click"]
        dmg = random.randint(dmg_min, dmg_max)

        new_hp = max(0, int(hp_curr) - dmg)

        # Update mob + attacker dans une seule transaction
        async with _get_db() as db:
            await db.execute(
                "UPDATE mob_spawns SET hp_current=? WHERE id=?",
                (new_hp, mob_id),
            )
            await db.execute(
                "INSERT INTO mob_attackers "
                "(mob_id, user_id, damage_dealt, attacks_count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(mob_id, user_id) DO UPDATE SET "
                "damage_dealt = damage_dealt + ?, "
                "attacks_count = attacks_count + 1, "
                "last_attack_at = CURRENT_TIMESTAMP",
                (mob_id, btn_i.user.id, dmg, dmg),
            )
            await db.commit()

        # Mob mort ?
        if new_hp <= 0:
            await _on_mob_killed(btn_i, mob_id, mob_def, bool(is_elite), int(hp_max))
            return

        # Edit le message pour refléter new HP
        try:
            guild = btn_i.guild
            ch = guild.get_channel(int(ch_id))
            if ch and msg_id:
                try:
                    msg = await ch.fetch_message(int(msg_id))
                    new_layout = await _build_updated_layout(
                        mob_def, new_hp, int(hp_max), bool(is_elite), mob_id
                    )
                    if new_layout:
                        await msg.edit(view=new_layout)
                except discord.NotFound:
                    pass
                except Exception as ex:
                    print(f"[mob_attack edit msg] {ex}")
        except Exception:
            pass

        # Feedback ephemeral
        try:
            await btn_i.followup.send(
                f"⚔️ Tu infliges **{dmg}** dégâts à "
                f"{mob_def['emoji']} **{mob_def['name']}** "
                f"({new_hp}/{hp_max} HP).",
                ephemeral=True,
            )
        except Exception:
            pass
    except Exception as ex:
        print(f"[_process_attack] {ex}")


async def _build_updated_layout(
    mob_def: dict, hp_current: int, hp_max: int, is_elite: bool, mob_id: int,
):
    """Re-build le layout du mob avec HP mis à jour."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    elite_prefix = "👑 ÉLITE — " if is_elite else ""
    pct = int((hp_current / hp_max) * 100) if hp_max else 0
    bar_len = 16
    filled = int((hp_current / hp_max) * bar_len) if hp_max else 0
    bar = "█" * filled + "░" * (bar_len - filled)

    drop_min, drop_max = mob_def["drop_coins"]
    if is_elite:
        drop_min *= 3
        drop_max *= 3

    items = [
        v2_title(f"{elite_prefix}{mob_def['emoji']} {mob_def['name']}"),
        v2_subtitle("_Mob en combat — frappe encore !_"),
        v2_divider(),
        v2_body(
            f"**❤️ HP :** `{bar}` `{hp_current}/{hp_max}` ({pct}%)\n"
            f"**💰 Drop estimé :** `{drop_min}-{drop_max}` 🪙"
        ),
    ]
    color = 0xFFD700 if is_elite else mob_def.get("color", 0x95A5A6)

    class _MobLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=color))

    layout = _MobLayout()
    layout.add_item(MobAttackButton(mob_id))
    return layout


# ─── Kill resolution ───────────────────────────────────────────────────────

async def _on_mob_killed(
    btn_i: discord.Interaction, mob_id: int, mob_def: dict,
    is_elite: bool, hp_max: int,
):
    """Distribue les drops à tous les attackers proportionnels."""
    if _get_db is None:
        return

    # Récupère tous les attackers
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, damage_dealt FROM mob_attackers "
                "WHERE mob_id=?",
                (mob_id,),
            ) as cur:
                attackers = await cur.fetchall()
    except Exception:
        attackers = []

    if not attackers:
        return

    total_dmg = sum(int(d) for _, d in attackers) or 1
    guild = btn_i.guild
    if not guild:
        return

    # Bonus alliance : combien d'attackers sont dans la même alliance ?
    alliance_counts: dict[int, int] = {}  # alliance_id → count
    user_alliances: dict[int, Optional[int]] = {}
    for uid, _ in attackers:
        aid = await _get_alliance_id(guild.id, int(uid))
        user_alliances[int(uid)] = aid
        if aid:
            alliance_counts[aid] = alliance_counts.get(aid, 0) + 1

    # Calcul drops
    drop_min, drop_max = mob_def["drop_coins"]
    if is_elite:
        drop_min *= 3
        drop_max *= 3
    drop_chance = mob_def["drop_item_chance"]
    if is_elite:
        drop_chance = min(1.0, drop_chance * 3)

    top_user_id = max(attackers, key=lambda x: int(x[1]))[0]
    rewards: list[dict] = []

    for uid, dmg in attackers:
        uid = int(uid)
        share = int(dmg) / total_dmg
        base_drop = int(random.randint(drop_min, drop_max) * share)
        # Min 5 coins pour avoir attaqué
        coins = max(5, base_drop)

        # Bonus alliance
        aid = user_alliances.get(uid)
        bonus_applied = False
        if aid and alliance_counts.get(aid, 0) >= ALLIANCE_BONUS_MIN_MEMBERS:
            coins = int(coins * ALLIANCE_BONUS_MULT)
            bonus_applied = True

        # Bonus top damage : +50% drop pour le top
        if uid == top_user_id:
            coins = int(coins * 1.50)

        # Item drop ?
        got_item = random.random() < drop_chance
        item_str = ""
        if got_item and mob_def.get("item_pool"):
            item_str = random.choice(mob_def["item_pool"])
            # Élite garantit toujours un item
        if is_elite and not got_item:
            got_item = True
            item_str = random.choice(mob_def["item_pool"])

        # Apply coins
        if _add_coins is not None:
            try:
                await _add_coins(guild.id, uid, coins)
            except Exception:
                pass

        rewards.append({
            "user_id": uid,
            "damage": int(dmg),
            "coins": coins,
            "item": item_str,
            "alliance_bonus": bonus_applied,
            "is_top": uid == top_user_id,
        })

    # Mark killed
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE mob_spawns SET status='killed', "
                "killed_at=CURRENT_TIMESTAMP WHERE id=?",
                (mob_id,),
            )
            await db.commit()
    except Exception:
        pass

    # Build kill message
    elite_prefix = "👑 ÉLITE " if is_elite else ""
    title_msg = (
        f"💀 **{elite_prefix}{mob_def['emoji']} {mob_def['name']}** est tombé !"
    )

    lines = [title_msg, "", "**🏆 Récompenses :**"]
    for r in rewards[:10]:
        member = guild.get_member(r["user_id"])
        name = member.display_name if member else f"User {r['user_id']}"
        badge_top = " 🥇" if r["is_top"] else ""
        badge_alli = " 🤝" if r["alliance_bonus"] else ""
        item_str = f" + 🎁 `{r['item']}`" if r["item"] else ""
        lines.append(
            f"• **{name}**{badge_top}{badge_alli} : "
            f"`{r['coins']}` 🪙{item_str} _(`{r['damage']}` dmg)_"
        )
    if len(rewards) > 10:
        lines.append(f"_+ {len(rewards) - 10} autres attackers récompensés._")

    # Edit le message original pour montrer le kill
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT message_id, channel_id FROM mob_spawns WHERE id=?",
                (mob_id,),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0] and row[1]:
            ch = guild.get_channel(int(row[1]))
            if ch:
                try:
                    msg = await ch.fetch_message(int(row[0]))
                    await msg.edit(content="\n".join(lines), view=None)
                except Exception:
                    pass
    except Exception:
        pass

    # Phase 163.6 : pet XP via le bot.py helper si dispo
    # (skip — fait via callback boss principal)


async def _despawn_after(mob_id: int, seconds: int):
    """Despawn cleanup après timeout."""
    await asyncio.sleep(seconds)
    if _get_db is None or _bot is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, message_id, channel_id, status "
                "FROM mob_spawns WHERE id=?",
                (mob_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row or row[3] != "alive":
            return
        gid, msg_id, ch_id, _ = row
        guild = _bot.get_guild(int(gid))
        if guild and ch_id and msg_id:
            ch = guild.get_channel(int(ch_id))
            if ch:
                try:
                    msg = await ch.fetch_message(int(msg_id))
                    await msg.delete()
                except Exception:
                    pass
        # Mark despawned
        async with _get_db() as db:
            await db.execute(
                "UPDATE mob_spawns SET status='despawned' WHERE id=?",
                (mob_id,),
            )
            await db.commit()
    except Exception as ex:
        print(f"[_despawn_after] {ex}")


# ─── Spawn task ────────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def spawn_task():
    """Task qui décide quand spawn un mob (random 30-45 min entre 2)."""
    if _bot is None or _get_db is None:
        return
    try:
        for guild in _bot.guilds:
            try:
                # Vérifie le dernier spawn — si > random(30-45) min, on spawn
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT spawned_at FROM mob_spawns "
                        "WHERE guild_id=? ORDER BY id DESC LIMIT 1",
                        (guild.id,),
                    ) as cur:
                        row = await cur.fetchone()
                if row and row[0]:
                    try:
                        last_dt = datetime.fromisoformat(
                            str(row[0]).replace("Z", "+00:00")
                        )
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        elapsed_min = (
                            datetime.now(timezone.utc) - last_dt
                        ).total_seconds() / 60
                        # Cooldown random 30-45 min
                        cooldown = random.randint(SPAWN_MIN_MIN, SPAWN_MAX_MIN)
                        if elapsed_min < cooldown:
                            continue
                    except Exception:
                        pass
                # Sinon ou si jamais → spawn
                await spawn_mob(guild)
            except Exception as ex:
                print(f"[mob_hunts spawn_task g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[mob_hunts spawn_task] {ex}")


@spawn_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


def register_persistent_views(bot_instance):
    """À appeler dans on_ready après init_db. Enregistre le DynamicItem
    qui matche les custom_ids mob_attack_*."""
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(MobAttackButton)
    except Exception as ex:
        print(f"[mob_hunts register_persistent_views] {ex}")


__all__ = [
    "setup",
    "init_db",
    "spawn_mob",
    "spawn_task",
    "register_persistent_views",
    "MobAttackButton",
    "MOB_CATALOG",
]
