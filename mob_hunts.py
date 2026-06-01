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
import ui_v2  # design-system V2 partagé (encadrés cohérents)
import events_engine as _ev  # guide « comment jouer » + stats combat

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
_inventory_fn = None  # Phase 184 : getter d'inventaire (gear-scaling du combat)
_active_ping_fn = None  # Phase 206 : ping « membres actifs » (injecté par bot.py)
_arena_ensure_fn = None  # Phase 211 : arène de combat partagée dédiée (injecté)
_report_fn = None  # Phase 223 : rapports de fin → salon « 📜 chroniques-combat » (injecté)
_arena_create_fn = None  # Phase 228 : crée une arène ÉPHÉMÈRE dédiée par mob (injecté)
_arena_delete_fn = None  # Phase 228 : supprime l'arène éphémère du mob à la fin (injecté)
_event_busy_fn = None  # Phase 230 : async (guild_id) -> True si un AUTRE event de combat tourne (injecté)

# Spawn interval (random entre min et max minutes)
# Phase 173.1 : plus fréquent (18-30 min au lieu de 30-45) → bien plus de
# combat dans la journée.
SPAWN_MIN_MIN = 18
SPAWN_MAX_MIN = 30
# Durée avant despawn si pas tué (un peu plus de temps pour réagir)
MOB_LIFETIME_MIN = 20
# Phase 173.1 : spawn 24h/24. Le jour (9h-23h FR) → mobs normaux ; la nuit
# (23h-9h FR) → mobs NOCTURNES + coffres nocturnes. Plus de "trou" la nuit.
DAY_HOUR_START = 9
DAY_HOUR_END = 23
# Anti-spam : max N mobs simultanés / guild
MAX_CONCURRENT_MOBS = 2
# Bonus alliance : multiplicateur si 2+ membres alliance ont attacké
ALLIANCE_BONUS_MULT = 1.20
ALLIANCE_BONUS_MIN_MEMBERS = 2
# Probabilité d'apparition élite
ELITE_CHANCE = 0.10

# ─── Phase 214 : COMBAT SOLO vs COLLECTIF ──────────────────────────────────
# Certains mobs sont des DÉFIS SOLO (on ne ping qu'1 seul actif, PV modestes,
# faisable à une personne) ; d'autres sont des COMBATS COLLECTIFS (on ping
# PLUSIEURS actifs, PV très élevés → il faut se coordonner, « plus à faire »).
# Le ping reste la priorité : sans lui, personne ne vient frapper.
GROUP_COMBAT_CHANCE = 0.40   # 40% des mobs = combat COLLECTIF
SOLO_PING_CHANCE = 0.70      # parmi les solos, 70% défient 1 actif (sinon mob ambiant)
# Multiplicateurs de PV selon le mode (× hp_base) :
SOLO_HP_MULT = 1             # solo normal
SOLO_HP_MULT_ELITE = 2       # solo élite
GROUP_HP_MULT = 6            # collectif normal
GROUP_HP_MULT_ELITE = 10     # collectif élite
# Seuil d'affichage : hp_max >= hp_base * 4 → considéré COLLECTIF (déduit du
# ratio, donc aucune colonne DB à ajouter ; solo ≤ ×2, collectif ≥ ×6).
GROUP_HP_THRESHOLD = 4


def _is_group_combat(mob_def: dict, hp_max: int) -> bool:
    """Phase 214 : True si ce mob est un COMBAT COLLECTIF (PV gonflés), déduit du
    ratio hp_max/hp_base — pas de colonne DB. Solo ≤ ×2, collectif ≥ ×6."""
    try:
        base = int(mob_def.get("hp_base", 0) or 0)
        return base > 0 and hp_max >= base * GROUP_HP_THRESHOLD
    except Exception:
        return False

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
    # ─── Phase 173.1 : MOBS NOCTURNES (spawn 23h-9h FR uniquement) ───
    {
        "id": "shadow_wolf",
        "name": "Loup d'Ombre",
        "emoji": "🐺",
        "hp_base": 130,
        "damage_per_click": (16, 34),
        "drop_coins": (160, 380),
        "drop_item_chance": 0.16,
        "item_pool": ["night_fang", "shadow_pelt"],
        "color": 0x2C3E50,
        "nocturnal": True,
    },
    {
        "id": "night_wraith",
        "name": "Spectre Nocturne",
        "emoji": "👻",
        "hp_base": 170,
        "damage_per_click": (20, 42),
        "drop_coins": (200, 480),
        "drop_item_chance": 0.20,
        "item_pool": ["ectoplasm", "soul_ember"],
        "color": 0x9B59B6,
        "nocturnal": True,
    },
    {
        "id": "moon_moth",
        "name": "Phalène Lunaire",
        "emoji": "🦋",
        "hp_base": 90,
        "damage_per_click": (12, 26),
        "drop_coins": (130, 300),
        "drop_item_chance": 0.22,
        "item_pool": ["moon_dust", "silver_scale"],
        "color": 0x5DADE2,
        "nocturnal": True,
    },
    {
        "id": "vampire_bat",
        "name": "Chauve-souris Vampire",
        "emoji": "🦇",
        "hp_base": 110,
        "damage_per_click": (14, 30),
        "drop_coins": (150, 340),
        "drop_item_chance": 0.17,
        "item_pool": ["blood_vial", "leather_wing"],
        "color": 0x7B241C,
        "nocturnal": True,
    },
    # Coffre nocturne : très peu de HP (s'ouvre en 1-2 clics), gros coins
    {
        "id": "night_chest",
        "name": "Coffre Nocturne",
        "emoji": "🎁",
        "hp_base": 60,
        "damage_per_click": (20, 50),
        "drop_coins": (350, 800),
        "drop_item_chance": 0.35,
        "item_pool": ["moon_dust", "soul_ember", "silver_scale", "blood_vial"],
        "color": 0xF1C40F,
        "nocturnal": True,
    },
]


def _is_nocturnal(mob: dict) -> bool:
    return bool(mob.get("nocturnal", False))


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
          inventory_fn=None, active_ping_fn=None, arena_ensure_fn=None, report_fn=None,
          arena_create_fn=None, arena_delete_fn=None, event_busy_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _inventory_fn, _active_ping_fn
    global _arena_ensure_fn, _report_fn, _arena_create_fn, _arena_delete_fn
    global _event_busy_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _inventory_fn = inventory_fn
    _active_ping_fn = active_ping_fn
    _arena_ensure_fn = arena_ensure_fn
    _report_fn = report_fn
    _arena_create_fn = arena_create_fn
    _arena_delete_fn = arena_delete_fn
    _event_busy_fn = event_busy_fn


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


def _now_paris() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc)


def _is_night() -> bool:
    """True si on est dans la fenêtre nocturne (23h-9h FR)."""
    h = _now_paris().hour
    # Nuit = NON (9h <= h < 23h)
    return not (DAY_HOUR_START <= h < DAY_HOUR_END)


def _is_active_hour() -> bool:
    """Phase 173.1 : les mobs spawnent désormais 24h/24 (jour ET nuit).
    Conservé pour compat — toujours True."""
    return True


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

def _bot_can_send(guild: discord.Guild, ch: discord.TextChannel) -> bool:
    """True si le bot peut écrire dans ce salon."""
    try:
        me = guild.me
        if me is None:
            return False
        perms = ch.permissions_for(me)
        return bool(perms.send_messages and perms.view_channel)
    except Exception:
        return False


_ARENA_AVOID_KEYWORDS = (
    "ticket", "annonce", "announce", "log", "règl", "regl", "rule",
    "bienvenue", "welcome", "lecture", "read-only", "readonly", "info",
    "staff", "admin", "mod-", "vocal", "voice",
)


async def _find_arena_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Trouve le salon arène pour spawn les mobs.

    Phase 173.1 : fallback ÉLARGI pour que les mobs spawnent TOUJOURS quelque
    part (avant, si aucun salon "arène" n'existait et que l'owner n'avait rien
    configuré, les mobs ne spawnaient JAMAIS — bug observé).
    1. `combat_arena_channel_id` configuré par owner — préféré
    2. Arène boss raid ACTIVE (events.arena_channel_id) — temporaire
    3. Recherche par nom "arène/arena/combat/boss/jeu/game/general"
    4. `hub_channel` configuré (le hub d'engagement)
    5. Premier salon écrivable "sain" (pas ticket/annonce/log/RO/vocal)
    6. system_channel de la guild
    7. None → skip silencieux (vraiment aucun salon dispo)
    """
    if _db_get is None or _get_db is None:
        return None

    # Phase 211 : arène de combat PARTAGÉE dédiée (priorité). Évite que les mobs
    # atterrissent dans un salon au hasard. Créée une fois, réutilisée.
    if _arena_ensure_fn is not None:
        try:
            arena = await _arena_ensure_fn(guild)
            if arena is not None and _bot_can_send(guild, arena):
                return arena
        except Exception as ex:
            print(f"[mob_hunts arena ensure] {ex}")

    cfg_data = {}
    # 1. Salon combat configuré par owner
    try:
        cfg_data = await _db_get(guild.id)
        ch_id = int(cfg_data.get("combat_arena_channel_id", 0) or 0)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch and _bot_can_send(guild, ch):
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
            if ch and _bot_can_send(guild, ch):
                return ch
    except Exception:
        pass

    # 3. Recherche par nom (élargie : jeux/game/general aussi)
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["arène", "arena", "combat", "boss",
                                 "jeu", "game", "chasse", "donjon", "dungeon"]):
            if _bot_can_send(guild, ch):
                return ch

    # 4. Hub d'engagement configuré
    try:
        hub_id = int(cfg_data.get("hub_channel", 0) or 0)
        if hub_id:
            ch = guild.get_channel(hub_id)
            if ch and _bot_can_send(guild, ch):
                return ch
    except Exception:
        pass

    # 5. Premier salon écrivable "sain" (général / discussion)
    try:
        for ch in guild.text_channels:
            n = (ch.name or "").lower()
            if any(bad in n for bad in _ARENA_AVOID_KEYWORDS):
                continue
            if _bot_can_send(guild, ch):
                return ch
    except Exception:
        pass

    # 6. system_channel en dernier recours
    try:
        if guild.system_channel and _bot_can_send(guild, guild.system_channel):
            return guild.system_channel
    except Exception:
        pass

    return None


async def _is_major_event_active(guild_id: int) -> bool:
    """Phase 177 : True si un GROS event masquant le serveur est en cours
    (Boss Raid / Chasse au trésor / Quiz — table `events`, ended=0).

    Pendant ces events, TOUS les salons @everyone sont masqués et l'arène est
    dédiée à l'event → on NE spawn PAS de mobs (ils seraient invisibles OU
    viendraient se superposer dans l'arène du boss). Les mobs reprennent dès
    que l'event est terminé.
    """
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM events WHERE guild_id=? AND ended=0 "
                "AND (ends_at IS NULL OR datetime(ends_at) > datetime('now')) LIMIT 1",
                (guild_id,),
            ) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def spawn_mob(guild: discord.Guild) -> bool:
    """Spawn un mob aléatoire dans l'arène. Retourne True si succès."""
    if not guild or _get_db is None or _bot is None:
        return False
    # Phase 191 : interrupteur Hub Événements — Chasse aux mobs
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('mob_hunts_enabled', True)):
            return False
    except Exception:
        pass
    if not _is_active_hour():
        return False
    # Phase 177 : pas de mob pendant un Boss Raid / event masquant (serveur enfoui)
    if await _is_major_event_active(guild.id):
        return False
    # Phase 230 : verrou GLOBAL — pas de mob non plus pendant un boss du jour /
    # world boss / climax (tables séparées que _is_major_event_active ne voit
    # pas). Un seul event de combat à la fois. Fail-open si l'injection manque.
    if _event_busy_fn is not None:
        try:
            if await _event_busy_fn(guild.id):
                return False
        except Exception:
            pass
    if await _count_alive_mobs(guild.id) >= MAX_CONCURRENT_MOBS:
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
    # Phase 173.1 : filtre jour/nuit. La nuit (23h-9h FR) → uniquement les
    # mobs nocturnes (loups d'ombre, spectres, coffres nocturnes...) ; le jour
    # → uniquement les mobs normaux. Garantit des événements de combat 24h/24.
    night = _is_night()
    pool = [
        m for m in MOB_CATALOG
        if m["id"] not in alive_kinds and _is_nocturnal(m) == night
    ]
    if not pool:
        return False

    mob_def = random.choice(pool)
    is_elite = random.random() < ELITE_CHANCE
    # Phase 214 : MODE de combat. solo → 1 actif pingé, PV modestes (faisable
    # seul) ; group → plusieurs actifs pingés, PV très élevés (coordination).
    combat_mode = 'group' if random.random() < GROUP_COMBAT_CHANCE else 'solo'
    if combat_mode == 'group':
        hp_mult = GROUP_HP_MULT_ELITE if is_elite else GROUP_HP_MULT
    else:
        hp_mult = SOLO_HP_MULT_ELITE if is_elite else SOLO_HP_MULT
    hp_max = mob_def["hp_base"] * hp_mult
    elite_prefix = "👑 " if is_elite else ""

    # Phase 228 : CHAQUE mob a SON salon dédié (catégorie « ⚔️ {mob} » + texte +
    # 1 vocal), créé maintenant et SUPPRIMÉ à sa mort/despawn → fini l'arène
    # partagée qui restait vide à l'infini sans panneau. Le panneau d'attaque est
    # dans CE salon. Fallback : arène partagée si la création dédiée échoue.
    ch = None
    if _arena_create_fn is not None:
        try:
            ch = await _arena_create_fn(
                guild, 'mob', f"{elite_prefix}{mob_def['name']}", voice_count=1)
        except Exception as ex:
            print(f"[spawn_mob arena create] {ex}")
    if ch is None:
        ch = await _find_arena_channel(guild)
    if not ch:
        print(f"[mob_hunts] pas de salon dispo, spawn annulé guild={guild.id}")
        return False

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

    # Phase 176 : combien de créatures rôdent actuellement (affiché sur le panel)
    try:
        alive_count = await _count_alive_mobs(guild.id)
    except Exception:
        alive_count = 1
    # Build le panel V2
    msg = await _post_mob_message(
        ch, mob_db_id, mob_def, hp_max, hp_max, is_elite, alive_count
    )
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

        # Phase 214 : LE PING EST LA PRIORITÉ (sans lui personne ne vient).
        #  • COLLECTIF → on appelle PLUSIEURS actifs (cap 5-8) car le mob a
        #    énormément de PV : ping quasi systématique, sinon il rote sans
        #    combattants (le despawn timer le nettoiera dans le pire cas).
        #  • SOLO → on DÉFIE 1 seul actif (cap 1) ~70% du temps ; sinon mob
        #    « ambiant » que les passants peuvent cliquer.
        # Rotation + opt-out + auto-suppression du ping gérés par le helper.
        if _active_ping_fn is not None:
            emoji = mob_def.get("emoji", "🗡️")
            do_ping = (combat_mode == 'group') or (random.random() < SOLO_PING_CHANCE)
            if do_ping:
                try:
                    if combat_mode == 'group':
                        # Phase 222 : cap plus DOUX (3-5 au lieu de 5-8) + cooldown 6h
                        # → moins de mentions par event collectif, on évite le spam.
                        ping_cap = random.randint(3, 5)
                        ping_cooldown = 6
                        ping_intro = (
                            f"⚔️ **COMBAT COLLECTIF !** {emoji} {elite_prefix}"
                            f"**{mob_def['name']}** débarque avec énormément de PV — "
                            f"rassemblez-vous pour l'abattre")
                    else:
                        ping_cap = 1
                        ping_cooldown = 2
                        ping_intro = (
                            f"🎯 {emoji} {elite_prefix}**{mob_def['name']}** te "
                            f"défie en combat singulier —")
                    await _active_ping_fn(
                        guild, ch, cap=ping_cap, cooldown_hours=ping_cooldown,
                        cleanup_seconds=900, intro=ping_intro)
                except Exception as ex:
                    print(f"[spawn_mob active_ping] {ex}")

        # Schedule despawn cleanup
        asyncio.create_task(_despawn_after(mob_db_id, MOB_LIFETIME_MIN * 60))

    print(
        f"[mob_hunts] spawn guild={guild.id} mob={mob_def['id']} "
        f"elite={is_elite} hp={hp_max}"
    )
    return True


async def _post_mob_message(
    ch: discord.TextChannel, mob_db_id: int, mob_def: dict,
    hp_current: int, hp_max: int, is_elite: bool, alive_count: int = 1,
) -> Optional[discord.Message]:
    """Build et poste le message du mob (Phase 176 : clairement distinct d'un boss)."""
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

    # Phase 214 : combat SOLO (défi perso, PV modestes) vs COLLECTIF (PV gonflés,
    # à plusieurs) — déduit du ratio PV (aucune colonne DB).
    is_group = _is_group_combat(mob_def, hp_max)
    crowd = (
        f"`{alive_count}` créatures rôdent — attaque celle que tu veux !"
        if (alive_count and alive_count > 1) else "seule pour l'instant"
    )
    if is_group:
        count_line = (
            f"⚔️ **COMBAT COLLECTIF** · gros PV — frappez à **plusieurs** "
            f"(bonus alliance dès 2 alliés) · {crowd}"
        )
    else:
        count_line = (
            f"🎯 **Cible solo** · défi personnel, faisable en solo · {crowd}"
        )

    items = []
    items.append(v2_title(
        f"{elite_prefix}{mob_def['emoji']} {mob_def['name']}"
    ))
    items.append(v2_subtitle(count_line))
    items.append(v2_divider())
    items.append(v2_body(
        f"**❤️ HP :** `{bar}` `{hp_current}/{hp_max}` ({pct}%)\n"
        f"**💰 Drop :** `{drop_min}-{drop_max}` 🪙 · "
        f"**🎁 Item :** `{drop_item_pct}%`\n"
        f"⏳ Disparaît dans **{MOB_LIFETIME_MIN} min** si pas vaincue"
    ))
    if is_group:
        # Phase 214 : « plus à faire » en combat collectif → on oriente les joueurs.
        items.append(v2_body(
            "🐾 **Plus à faire :** active ton **familier**, équipe ton **meilleur "
            "stuff** et regroupez-vous en vocal — ce monstre tombe en équipe."
        ))
    items.append(v2_divider())
    items.append(v2_body(_ev.how_to_play('mob')))
    items.append(v2_body(
        "_🐾 Simple créature — **ce n'est PAS un boss** : aucun salon n'est masqué, "
        "le serveur reste ouvert. Loot proportionnel aux dégâts · "
        "**bonus alliance** si 2+ alliés frappent._"
    ))

    color = 0xFFD700 if is_elite else mob_def.get("color", 0x95A5A6)

    # Phase 208 FIX : le bouton DOIT être dans un ActionRow DANS le conteneur.
    # Un bouton brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body /
    # components.1 type". Le clic est capté par le DynamicItem MobAttackButton
    # enregistré (match du custom_id), exactement comme le World Boss.
    attack_btn = Button(
        label="⚔️ Attaquer", style=discord.ButtonStyle.danger,
        custom_id=f"mob_attack:{mob_db_id}",
    )
    items.append(discord.ui.ActionRow(attack_btn))

    class _MobLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=color))

    layout = _MobLayout()

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
        # Phase 184 (cohérence) : l'arme du joueur compte (ATK partiel + proc
        # élémentaire), comme sur les boss. Sur les mobs (peu de PV), on prend
        # la moitié de l'ATK pour ne pas one-shot, + le burst élémentaire.
        elem_proc = None
        if _inventory_fn is not None:
            try:
                import events_engine as _ev
                _pinv = await _inventory_fn(btn_i.guild.id, btn_i.user.id)
                dmg += int(_ev.inventory_total_stats(_pinv).get("atk", 0) or 0) // 2
                _p = _ev.roll_elemental_proc(_pinv.get("weapon"))
                if _p:
                    dmg += int(_p.get("bonus", 0) or 0)
                    elem_proc = _p
            except Exception:
                pass

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
            _en = (
                f"  {elem_proc['emoji']} {elem_proc['name']} +{elem_proc['bonus']}"
                if elem_proc else ""
            )
            await btn_i.followup.send(
                f"⚔️ Tu infliges **{dmg}** dégâts à "
                f"{mob_def['emoji']} **{mob_def['name']}** "
                f"({new_hp}/{hp_max} HP).{_en}",
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

    # Phase 214 : sous-titre selon le mode (déduit du ratio PV).
    _sub = (
        "_⚔️ Combat collectif — continuez à frapper **ensemble** !_"
        if _is_group_combat(mob_def, hp_max)
        else "_🎯 Combat solo — frappe encore !_"
    )
    items = [
        v2_title(f"{elite_prefix}{mob_def['emoji']} {mob_def['name']}"),
        v2_subtitle(_sub),
        v2_divider(),
        v2_body(
            f"**❤️ HP :** `{bar}` `{hp_current}/{hp_max}` ({pct}%)\n"
            f"**💰 Drop estimé :** `{drop_min}-{drop_max}` 🪙"
        ),
    ]
    color = 0xFFD700 if is_elite else mob_def.get("color", 0x95A5A6)

    # Phase 208 FIX : bouton dans un ActionRow DANS le conteneur (cf. _post_mob_message).
    attack_btn = Button(
        label="⚔️ Attaquer", style=discord.ButtonStyle.danger,
        custom_id=f"mob_attack:{mob_id}",
    )
    items.append(discord.ui.ActionRow(attack_btn))

    class _MobLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=color))

    layout = _MobLayout()
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

    # Phase 214 : un COMBAT COLLECTIF (PV gonflés ×6-10) partage le pool de coins
    # entre plus de monde → sans correction chacun gagnerait MOINS pour bien plus
    # d'effort. On gonfle le pool ~ au ratio de PV (plafonné) pour que la
    # récompense PAR DÉGÂT reste constante (équitable) et que le collectif vaille
    # le coup. Les items sont déjà tirés par personne (non dilués).
    try:
        _base_hp = int(mob_def.get("hp_base", 0) or 0)
        if _base_hp > 0:
            _hp_ratio = max(1, int(hp_max) // _base_hp)
            if _hp_ratio >= GROUP_HP_THRESHOLD:
                _loot_scale = min(_hp_ratio, GROUP_HP_MULT_ELITE)
                drop_min *= _loot_scale
                drop_max *= _loot_scale
    except Exception:
        pass

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

    # Phase 170.1 : alimente la Chronique d'Abylumis (1 mob tué = +1 progress)
    # Le top_user reçoit le crédit "killer principal", les autres participent
    # via leur damage. Fail-soft : si story_engine pas wired, no-op.
    try:
        import story_engine as _se
        await _se.on_mob_kill(guild.id, top_user_id)
    except Exception:
        pass

    # Phase 170.9 : 1% chance par mob tué pour le top_user de recevoir
    # un fragment d'indice de mystère. Fail-soft.
    try:
        import mystery_investigation as _myst
        if top_user_id:
            await _myst.try_grant_clue(
                guild.id, top_user_id, source="mob_kill",
            )
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
                    # Le panneau de spawn est en Components V2 → on NE PEUT PAS y
                    # remettre du `content` (erreur 400). On édite donc avec un
                    # bel encadré V2 de récap (cohérent avec tout le bot).
                    _recap_title = (
                        f"💀 {elite_prefix}{mob_def['emoji']} {mob_def['name']} vaincu !")
                    _recap_body = "\n".join(lines[2:]) if len(lines) > 2 else "\n".join(lines)
                    # Phase 223 : le rapport PERSISTE dans « 📜 chroniques-combat »
                    # (informe au propre, hors de l'arène).
                    if _report_fn is not None:
                        try:
                            await _report_fn(guild, _recap_title, _recap_body)
                        except Exception:
                            pass
                    # Le panneau devient un mini-récap « vaincu » (visible un court
                    # instant) PUIS on l'EFFACE. Phase 235.15 (demande owner) : le salon
                    # de combat permanent « ⚔️-combat » doit se VIDER entre deux combats
                    # → on supprime le panneau après ~15 s, qu'il soit dans le salon
                    # permanent OU dans un salon dédié éphémère. Le récap reste, lui,
                    # dans « 📜 chroniques-combat » (journal persistant).
                    await msg.edit(view=ui_v2.recap_view(
                        _recap_title, _recap_body, color=ui_v2.Palette.SUCCESS))
                    try:
                        await msg.delete(delay=15)
                    except Exception:
                        pass
                    # Si le mob avait un salon DÉDIÉ éphémère (catégorie + texte +
                    # vocal), _arena_delete_fn le supprime entièrement (grace 20 s).
                    # Sur le salon permanent, il se contente d'oublier la ligne DB.
                    if _arena_delete_fn is not None:
                        try:
                            asyncio.create_task(
                                _arena_delete_fn(guild, int(row[1]), grace_seconds=20))
                        except Exception:
                            pass
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
        # Phase 228 : le mob a despawn sans être tué → supprimer SON salon dédié
        # (catégorie + texte + vocal). No-op si c'est l'arène partagée (fallback,
        # pas dans combat_arenas) → on ne touche jamais l'arène partagée.
        if guild and ch_id and _arena_delete_fn is not None:
            try:
                await _arena_delete_fn(guild, int(ch_id), grace_seconds=0)
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
