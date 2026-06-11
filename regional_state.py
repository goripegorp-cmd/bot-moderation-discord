"""
regional_state.py — 5 régions du monde + patrouilles défensives (Phase 170.5).

🎯 OBJECTIF : ancrer la Chronique dans une géographie vivante. Le monde
est divisé en 5 régions, chacune avec sa santé (0-100) et son niveau de
menace. Si une région tombe (santé = 0), le serveur entier subit un
debuff jusqu'à reconquête.

MÉCANIQUES :
- Menace passive : +2 points/jour sur chaque région non protégée
- Patrouille hebdo : mercredi 19h FR, région la plus menacée → événement
  collectif où les joueurs défendent en cliquant un bouton
- Défense : chaque clic = +1 point, max 5 par joueur par patrouille
  (anti-spam), chaque clic = +1 chapitre 2.3 progress
- Si défense atteint target (200 pts pour 24h) → région +20 santé, -50 menace
- Si pas atteint → région perd 30 santé
- Si santé = 0 → région tombe → debuff -10% loot serveur jusqu'à reconquête

PHILOSOPHIE :
- Pression douce : pas de FOMO, juste un événement par semaine
- Effort collectif : 1 joueur ne peut PAS sauver une région seul (cap 5 pts)
- Punition modérée : un debuff -10% loot pousse à reconquérir mais pas
  punitif au point de frustrer
- Reconquête : pendant 7j après chute, patrouille spéciale "Reconquête"
  avec target halved (100 pts)

API :
- setup(bot, get_db, db_get, v2, story_module, npc_module)
- init_db()
- REGION_CATALOG (5 régions)
- ensure_regions_initialized(guild_id)
- get_region_state(guild_id, region_id) → dict
- get_all_regions_state(guild_id) → list
- apply_passive_threat(guild_id) — daily decay
- defend_region(guild_id, region_id, user_id, points=1) → dict
- start_patrol(guild_id) → patrol_id | None
- close_patrol(patrol_id) → dict
- get_active_patrol(guild_id) → dict | None
- get_server_debuff(guild_id) → dict (loot_mult, defense_mult, etc.)
- build_regions_panel(guild_id, user_id) → LayoutView (status 5 régions)
- build_patrol_panel(guild_id, user_id) → LayoutView (défense active)
- PatrolDefendButton (DynamicItem)
- regional_task (loop hourly)
- register_persistent_views(bot)

DB :
- regional_state (guild_id, region_id, health, threat, last_attack_at,
                  fallen_at, fallen_count)
                  PRIMARY KEY (guild_id, region_id)
- patrol_sessions (id PK, guild_id, region_id, opens_at, closes_at,
                   defense_total, target, status, message_id, channel_id)
- patrol_contributions (patrol_id, user_id, points, contributed_at)
                       PRIMARY KEY (patrol_id, user_id)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button
import ui_v2  # design-system V2 partagé (encadrés cohérents)

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
_story = None
_npc = None

# Bornes
HEALTH_MAX = 100
THREAT_MAX = 100
HEALTH_INITIAL = 80
THREAT_INITIAL = 10

# Menace passive
PASSIVE_THREAT_PER_DAY = 2

# Patrouille
PATROL_WEEKDAY = 2          # mercredi
PATROL_HOUR = 19            # 19h FR
PATROL_DURATION_HOURS = 24  # 24h pour défendre
PATROL_TARGET_POINTS = 200
PATROL_RECLAIM_TARGET = 100  # target halved si patrouille de reconquête
MAX_POINTS_PER_USER = 5      # cap anti-spam

# Effets
REGION_FALL_THRESHOLD = 0   # health = 0 → tombe
SERVER_DEBUFF_PER_FALLEN = 10  # -10% loot par région tombée


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE RÉGIONS
# ═══════════════════════════════════════════════════════════════════════════

REGION_CATALOG = [
    {
        "id": "cendregris",
        "name": "Cendregris",
        "subtitle": "La Forêt des Cendres",
        "emoji": "🌲",
        "description": (
            "Forêt ancienne où la cendre tombe en permanence. C'est ici "
            "que tout a commencé. Zone neutre où les nouveaux aventuriers "
            "font leurs premiers pas."
        ),
        "ambiance": "Calme, mystérieuse, vaguement inquiétante",
        "lore_unlock_act": 1,
        "linked_npc": "aria",
        "bonus_when_healthy": "Tous les drops +5% lorsque la santé est ≥80",
    },
    {
        "id": "profondes",
        "name": "Les Profondes",
        "subtitle": "Le Réseau Souterrain",
        "emoji": "🕳️",
        "description": (
            "Vaste réseau de cavernes qui s'étend sous tout le royaume. "
            "Source des cendres. Riche en minerais rares, mais dangereuse. "
            "Korr y descend pour son artisanat."
        ),
        "ambiance": "Sombre, écho lointain, danger constant",
        "lore_unlock_act": 1,
        "linked_npc": "korr",
        "bonus_when_healthy": "Mob hunts dans cette zone +10% drops élite",
    },
    {
        "id": "cathedrale",
        "name": "Cathédrale Brisée",
        "subtitle": "Le Sanctuaire Oublié",
        "emoji": "⛪",
        "description": (
            "Ruines d'une cathédrale immense, à demi engloutie par les "
            "racines. Lyra l'Érudite y mène ses recherches interdites. "
            "Les murs murmurent des secrets aux oreilles patientes."
        ),
        "ambiance": "Solennel, érudit, traces du passé",
        "lore_unlock_act": 2,
        "linked_npc": "lyra",
        "bonus_when_healthy": "Indices de mystère +1 par jour lorsque ≥70",
    },
    {
        "id": "marais",
        "name": "Marais Murmurants",
        "subtitle": "Les Eaux Sombres",
        "emoji": "🪷",
        "description": (
            "Vastes marais où l'eau reflète des étoiles qui n'existent pas. "
            "Sienna y commerce avec des entités étranges. Les voyageurs s'y "
            "perdent souvent. Une voix appelle ceux qui écoutent trop."
        ),
        "ambiance": "Humide, étrange, presque hypnotique",
        "lore_unlock_act": 2,
        "linked_npc": "sienna",
        "bonus_when_healthy": "Encounters NPCs +1 coin si ≥60",
    },
    {
        "id": "sanctuaire",
        "name": "Sanctuaire",
        "subtitle": "Le Pic Final",
        "emoji": "🏔️",
        "description": (
            "Montagne sacrée au sommet inaccessible. Personne n'y est monté "
            "depuis des générations. Drazek le Guerrier la protège des "
            "intrus. C'est là que se joue la fin de la Chronique."
        ),
        "ambiance": "Majestueux, glacial, intouchable",
        "lore_unlock_act": 3,
        "linked_npc": "drazek",
        "bonus_when_healthy": "Boss final débloqué seulement si santé ≥60",
    },
]


def get_region_def(region_id: str) -> Optional[dict]:
    for r in REGION_CATALOG:
        if r["id"] == region_id:
            return r
    return None


def list_region_ids() -> list[str]:
    return [r["id"] for r in REGION_CATALOG]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    story_module=None, npc_module=None,
):
    global _bot, _get_db, _db_get, _v2, _story, _npc
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _story = story_module
    _npc = npc_module


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS regional_state (
                    guild_id INTEGER NOT NULL,
                    region_id TEXT NOT NULL,
                    health INTEGER DEFAULT 80,
                    threat INTEGER DEFAULT 10,
                    last_threat_tick TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_attack_at TIMESTAMP,
                    fallen_at TIMESTAMP,
                    fallen_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, region_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS patrol_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    region_id TEXT NOT NULL,
                    is_reclaim INTEGER DEFAULT 0,
                    opens_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closes_at TIMESTAMP NOT NULL,
                    defense_total INTEGER DEFAULT 0,
                    target INTEGER NOT NULL,
                    status TEXT DEFAULT 'open',
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS patrol_contributions (
                    patrol_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    points INTEGER DEFAULT 0,
                    contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (patrol_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_patrol_active "
                "ON patrol_sessions(guild_id, status)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[regional_state init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Initial state & getters
# ═══════════════════════════════════════════════════════════════════════════

async def ensure_regions_initialized(guild_id: int) -> None:
    """Crée les 5 régions pour cette guild si elles n'existent pas."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT region_id FROM regional_state WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                existing = {r[0] for r in await cur.fetchall()}
            for region in REGION_CATALOG:
                if region["id"] in existing:
                    continue
                await db.execute(
                    "INSERT OR IGNORE INTO regional_state "
                    "(guild_id, region_id, health, threat) "
                    "VALUES (?, ?, ?, ?)",
                    (guild_id, region["id"], HEALTH_INITIAL, THREAT_INITIAL),
                )
            await db.commit()
    except Exception as ex:
        print(f"[ensure_regions_initialized] {ex}")


async def get_region_state(
    guild_id: int, region_id: str,
) -> Optional[dict]:
    if _get_db is None:
        return None
    if get_region_def(region_id) is None:
        return None
    await ensure_regions_initialized(guild_id)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT health, threat, last_threat_tick, last_attack_at, "
                "fallen_at, fallen_count FROM regional_state "
                "WHERE guild_id=? AND region_id=?",
                (guild_id, region_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "region_id": region_id,
            "health": int(row[0] or 0),
            "threat": int(row[1] or 0),
            "last_threat_tick": row[2],
            "last_attack_at": row[3],
            "fallen_at": row[4],
            "fallen_count": int(row[5] or 0),
            "is_fallen": row[4] is not None and row[0] == 0,
        }
    except Exception:
        return None


async def get_all_regions_state(guild_id: int) -> list[dict]:
    """Retourne l'état des 5 régions de cette guild."""
    out = []
    for region in REGION_CATALOG:
        state = await get_region_state(guild_id, region["id"])
        if state:
            state["definition"] = region
            out.append(state)
    return out


async def get_server_debuff(guild_id: int) -> dict:
    """Calcule le debuff serveur basé sur le nombre de régions tombées."""
    regions = await get_all_regions_state(guild_id)
    fallen_count = sum(1 for r in regions if r["is_fallen"])
    loot_penalty = -SERVER_DEBUFF_PER_FALLEN * fallen_count
    return {
        "fallen_count": fallen_count,
        "loot_penalty_pct": loot_penalty,
        "loot_mult": max(0.5, 1.0 + (loot_penalty / 100.0)),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Threat management
# ═══════════════════════════════════════════════════════════════════════════

async def apply_passive_threat(guild_id: int) -> int:
    """Applique la menace passive (+2/jour) à chaque région non tombée.

    Retourne le nombre de régions affectées.
    """
    if _get_db is None:
        return 0
    await ensure_regions_initialized(guild_id)
    affected = 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT region_id, threat, last_threat_tick, health "
                "FROM regional_state "
                "WHERE guild_id=? AND (fallen_at IS NULL OR health > 0)",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                rid, threat, last_tick, health = row
                try:
                    dt_last = datetime.fromisoformat(
                        str(last_tick).replace("Z", "+00:00")
                    )
                    if dt_last.tzinfo is None:
                        dt_last = dt_last.replace(tzinfo=timezone.utc)
                    days_passed = (now - dt_last).days
                except Exception:
                    days_passed = 0
                if days_passed <= 0:
                    continue
                delta = days_passed * PASSIVE_THREAT_PER_DAY
                new_threat = min(THREAT_MAX, int(threat) + delta)
                await db.execute(
                    "UPDATE regional_state SET threat=?, last_threat_tick=? "
                    "WHERE guild_id=? AND region_id=?",
                    (new_threat, now.isoformat(), guild_id, rid),
                )
                affected += 1
            await db.commit()
    except Exception as ex:
        print(f"[apply_passive_threat] {ex}")
    return affected


# ═══════════════════════════════════════════════════════════════════════════
#  Defense
# ═══════════════════════════════════════════════════════════════════════════

async def defend_region(
    guild_id: int, region_id: str, user_id: int, points: int = 1,
) -> dict:
    """Un joueur ajoute des points de défense lors d'une patrouille active.

    Capé à MAX_POINTS_PER_USER par patrouille (anti-spam).
    Retourne {success: bool, my_total: int, patrol_total: int, target: int, error: ...}.
    """
    if _get_db is None:
        return {"error": "DB indisponible"}
    if get_region_def(region_id) is None:
        return {"error": "Région inconnue"}

    # Vérifie patrouille active pour cette région
    active = await get_active_patrol(guild_id)
    if not active:
        return {"error": "Aucune patrouille active"}
    if active["region_id"] != region_id:
        return {
            "error": f"La patrouille active concerne **{active['region_id']}**"
        }

    patrol_id = active["patrol_id"]

    try:
        async with _get_db() as db:
            # Lit contribution actuelle
            async with db.execute(
                "SELECT points FROM patrol_contributions "
                "WHERE patrol_id=? AND user_id=?",
                (patrol_id, user_id),
            ) as cur:
                row = await cur.fetchone()
            current = int(row[0]) if row else 0

            if current >= MAX_POINTS_PER_USER:
                return {
                    "error": f"Tu as atteint le max ({MAX_POINTS_PER_USER} pts) "
                             "pour cette patrouille.",
                    "my_total": current,
                }

            grant = min(int(points), MAX_POINTS_PER_USER - current)
            new_total = current + grant

            await db.execute(
                "INSERT INTO patrol_contributions "
                "(patrol_id, user_id, points) VALUES (?, ?, ?) "
                "ON CONFLICT(patrol_id, user_id) DO UPDATE SET "
                "points = excluded.points, contributed_at = CURRENT_TIMESTAMP",
                (patrol_id, user_id, new_total),
            )
            await db.execute(
                "UPDATE patrol_sessions SET defense_total = defense_total + ? "
                "WHERE id=?",
                (grant, patrol_id),
            )
            await db.commit()

            # Re-read totaux
            async with db.execute(
                "SELECT defense_total, target FROM patrol_sessions WHERE id=?",
                (patrol_id,),
            ) as cur:
                row = await cur.fetchone()
            patrol_total = int(row[0]) if row else 0
            target = int(row[1]) if row else PATROL_TARGET_POINTS
    except Exception as ex:
        print(f"[defend_region] {ex}")
        return {"error": str(ex)}

    # Alimente progression Chronique (kind: regional_defenses)
    if _story is not None:
        try:
            for _ in range(grant):
                await _story.on_regional_defense(guild_id, user_id)
        except Exception:
            pass

    return {
        "success": True,
        "granted": grant,
        "my_total": new_total,
        "max_per_user": MAX_POINTS_PER_USER,
        "patrol_total": patrol_total,
        "target": target,
        "pct": int(patrol_total * 100 / max(1, target)),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Patrol management
# ═══════════════════════════════════════════════════════════════════════════

def _paris_now() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _is_patrol_open_window() -> bool:
    now = _paris_now()
    return now.weekday() == PATROL_WEEKDAY and now.hour == PATROL_HOUR


async def get_active_patrol(guild_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, region_id, is_reclaim, opens_at, closes_at, "
                "defense_total, target, message_id, channel_id "
                "FROM patrol_sessions "
                "WHERE guild_id=? AND status='open' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "patrol_id": int(row[0]),
            "region_id": row[1],
            "is_reclaim": bool(row[2]),
            "opens_at": row[3],
            "closes_at": row[4],
            "defense_total": int(row[5] or 0),
            "target": int(row[6] or PATROL_TARGET_POINTS),
            "message_id": int(row[7] or 0),
            "channel_id": int(row[8] or 0),
        }
    except Exception:
        return None


async def _pick_region_for_patrol(guild_id: int) -> Optional[str]:
    """Sélectionne la région la plus menacée pour la patrouille.

    Priorité :
    1. Région tombée (reconquête)
    2. Région avec le plus de menace (parmi celles non tombées)
    """
    regions = await get_all_regions_state(guild_id)
    if not regions:
        return None
    # Fallen first
    fallen = [r for r in regions if r["is_fallen"]]
    if fallen:
        return fallen[0]["region_id"]
    # Most threatened
    not_fallen = [r for r in regions if not r["is_fallen"]]
    if not not_fallen:
        return None
    not_fallen.sort(key=lambda r: r["threat"], reverse=True)
    return not_fallen[0]["region_id"]


async def start_patrol(guild_id: int) -> Optional[int]:
    """Démarre une nouvelle patrouille pour cette guild si :
    - Aucune patrouille active
    - Au moins 1 région à défendre
    """
    if _get_db is None or _bot is None:
        return None
    existing = await get_active_patrol(guild_id)
    if existing:
        return None

    await ensure_regions_initialized(guild_id)
    region_id = await _pick_region_for_patrol(guild_id)
    if not region_id:
        return None

    state = await get_region_state(guild_id, region_id)
    is_reclaim = state and state["is_fallen"]
    target = PATROL_RECLAIM_TARGET if is_reclaim else PATROL_TARGET_POINTS
    closes_at = datetime.now(timezone.utc) + timedelta(hours=PATROL_DURATION_HOURS)

    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO patrol_sessions "
                "(guild_id, region_id, is_reclaim, closes_at, target) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, region_id, 1 if is_reclaim else 0,
                 closes_at.isoformat(), target),
            )
            patrol_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[start_patrol INSERT] {ex}")
        return None

    guild = _bot.get_guild(guild_id)
    if guild:
        await _announce_patrol_open(guild, region_id, target, is_reclaim, closes_at)

    if _story is not None:
        try:
            await _story.log_chronicle_event(
                guild_id, "patrol_started",
                {"region_id": region_id, "target": target,
                 "is_reclaim": is_reclaim},
            )
        except Exception:
            pass

    print(
        f"[regional_state] start_patrol guild={guild_id} region={region_id} "
        f"target={target} reclaim={is_reclaim} patrol={patrol_id}"
    )
    return patrol_id


async def close_patrol(patrol_id: int) -> Optional[dict]:
    """Close une patrouille, applique le résultat (succès / échec)."""
    if _get_db is None or _bot is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, region_id, defense_total, target, "
                "is_reclaim, status FROM patrol_sessions WHERE id=?",
                (patrol_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        guild_id, region_id, defense_total, target, is_reclaim, status = row
        if status != "open":
            return None
    except Exception:
        return None

    success = int(defense_total) >= int(target)

    # Update region
    try:
        async with _get_db() as db:
            current = await get_region_state(guild_id, region_id)
            if current:
                if success:
                    new_health = min(
                        HEALTH_MAX,
                        max(1, current["health"] + 20),
                    )
                    new_threat = max(0, current["threat"] - 50)
                    new_fallen_at = None
                else:
                    new_health = max(0, current["health"] - 30)
                    new_threat = current["threat"]
                    new_fallen_at = (
                        datetime.now(timezone.utc).isoformat()
                        if new_health == 0 else None
                    )
                fallen_count_inc = 1 if (new_health == 0 and current["health"] > 0) else 0
                await db.execute(
                    "UPDATE regional_state SET "
                    "health=?, threat=?, fallen_at=?, "
                    "fallen_count = fallen_count + ?, "
                    "last_attack_at=CURRENT_TIMESTAMP "
                    "WHERE guild_id=? AND region_id=?",
                    (new_health, new_threat, new_fallen_at,
                     fallen_count_inc, guild_id, region_id),
                )

            # Si reconquête réussie, clear fallen_at
            if is_reclaim and success:
                await db.execute(
                    "UPDATE regional_state SET fallen_at=NULL "
                    "WHERE guild_id=? AND region_id=?",
                    (guild_id, region_id),
                )

            await db.execute(
                "UPDATE patrol_sessions SET status=? WHERE id=?",
                ("success" if success else "failed", patrol_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[close_patrol apply] {ex}")
        return None

    # Announce
    guild = _bot.get_guild(guild_id)
    final_state = await get_region_state(guild_id, region_id)
    if guild:
        await _announce_patrol_closed(
            guild, region_id, success, int(defense_total), int(target),
            bool(is_reclaim), final_state,
        )

    if _story is not None:
        try:
            await _story.log_chronicle_event(
                guild_id,
                "region_reclaimed" if (is_reclaim and success) else
                "region_fallen" if (final_state and final_state["is_fallen"]) else
                "patrol_resolved",
                {
                    "region_id": region_id,
                    "region": (get_region_def(region_id) or {}).get("name", region_id),
                    "success": success,
                    "defense": int(defense_total),
                    "target": int(target),
                },
            )
        except Exception:
            pass

    print(
        f"[regional_state] close_patrol patrol={patrol_id} region={region_id} "
        f"success={success} defense={defense_total}/{target}"
    )
    return {
        "patrol_id": patrol_id,
        "region_id": region_id,
        "success": success,
        "defense": int(defense_total),
        "target": int(target),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  V2 Panels
# ═══════════════════════════════════════════════════════════════════════════

def _health_bar(value: int, max_v: int = 100, width: int = 12) -> str:
    pct = max(0, min(100, int((value * 100) / max(1, max_v))))
    fill = int(width * pct / 100)
    return "█" * fill + "░" * (width - fill)


def _threat_icon(threat: int) -> str:
    if threat < 25:
        return "🟢"
    if threat < 50:
        return "🟡"
    if threat < 75:
        return "🟠"
    return "🔴"


def _health_icon(health: int, is_fallen: bool) -> str:
    if is_fallen:
        return "💀"
    if health >= 80:
        return "💚"
    if health >= 50:
        return "💛"
    if health >= 25:
        return "🧡"
    return "❤️"


async def build_regions_panel(
    guild_id: int, user_id: int,
) -> Optional[discord.ui.LayoutView]:
    """Panel d'état des 5 régions + accès à la patrouille active."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    regions = await get_all_regions_state(guild_id)
    debuff = await get_server_debuff(guild_id)
    active_patrol = await get_active_patrol(guild_id)

    items = [v2_title("🌍 Régions du monde")]
    items.append(v2_subtitle(
        f"_Debuff serveur {debuff['loot_penalty_pct']:+d}% loot · "
        f"régions tombées {debuff['fallen_count']}/5_"
    ))
    items.append(v2_divider())

    for r in regions:
        d = r["definition"]
        h = r["health"]
        t = r["threat"]
        items.append(v2_body(
            f"{d['emoji']} **{d['name']}** — *{d['subtitle']}*\n"
            f"_{d['description']}_\n"
            f"{_health_icon(h, r['is_fallen'])} Santé `{_health_bar(h)}` `{h}/100`\n"
            f"{_threat_icon(t)} Menace `{_health_bar(t)}` `{t}/100`"
        ))
        items.append(v2_divider())

    if active_patrol:
        d = get_region_def(active_patrol["region_id"]) or {}
        reclaim_tag = " (reconquête)" if active_patrol["is_reclaim"] else ""
        items.append(v2_body(
            f"🚨 **Patrouille active{reclaim_tag}** — {d.get('emoji', '?')} {d.get('name', '?')}\n"
            f"Défense `{active_patrol['defense_total']}/{active_patrol['target']}` "
            f"({int(active_patrol['defense_total'] * 100 / max(1, active_patrol['target']))}%)"
        ))
    else:
        items.append(v2_body(
            "-# Prochaine patrouille : mercredi 19h FR."
        ))

    class _RegionsLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0x2E7D32))

    layout = _RegionsLayout()

    if active_patrol:
        # Phase 208 FIX : bouton dans un ActionRow (type 1). Un Button/DynamicItem
        # brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body". On crée
        # un Button BRUT avec le MÊME label/style/custom_id que PatrolDefendButton
        # (DynamicItem) ; le clic reste capté par le DynamicItem enregistré.
        btn = Button(
            label="🛡️ Défendre (+1 pt)",
            style=discord.ButtonStyle.danger,
            custom_id=f"patrol_defend:{active_patrol['patrol_id']}:{user_id}",
        )
        layout.add_item(discord.ui.ActionRow(btn))

    return layout


async def build_patrol_panel(
    guild_id: int, user_id: int,
) -> Optional[discord.ui.LayoutView]:
    """Panel dédié de défense de la patrouille active."""
    if _v2 is None:
        return None
    active = await get_active_patrol(guild_id)
    if not active:
        return await build_regions_panel(guild_id, user_id)

    region = get_region_def(active["region_id"]) or {}
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    # Get user's contribution
    my_contribution = 0
    if _get_db is not None:
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT points FROM patrol_contributions "
                    "WHERE patrol_id=? AND user_id=?",
                    (active["patrol_id"], user_id),
                ) as cur:
                    row = await cur.fetchone()
            my_contribution = int(row[0]) if row else 0
        except Exception:
            pass

    pct = int(active["defense_total"] * 100 / max(1, active["target"]))
    reclaim_tag = " (reconquête)" if active["is_reclaim"] else ""

    items = [
        v2_title(f"🛡️ Patrouille{reclaim_tag}"),
        v2_subtitle(
            f"_{region.get('emoji', '?')} **{region.get('name', '?')}** est menacée._"
        ),
        v2_divider(),
        v2_body(f"_{region.get('description', '…')}_"),
        v2_divider(),
        v2_body(
            f"**🎯 Défense collective**\n"
            f"`{_health_bar(active['defense_total'], active['target'], 20)}`\n"
            f"`{active['defense_total']:,} / {active['target']:,}` ({pct}%)"
        ),
        v2_body(
            f"**🛡️ Ta contribution** · `{my_contribution} / {MAX_POINTS_PER_USER}` pts"
        ),
        v2_divider(),
        v2_body(
            f"-# Chaque clic = +1 point + +1 Chronique · ferme `{active['closes_at']}`"
        ),
    ]

    if my_contribution >= MAX_POINTS_PER_USER:
        items.append(v2_body(
            "_✅ Tu as donné le maximum. Reviens à la prochaine patrouille._"
        ))

    class _PatrolLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0xD32F2F))

    layout = _PatrolLayout()
    if my_contribution < MAX_POINTS_PER_USER:
        # Phase 208 FIX : bouton dans un ActionRow (type 1). Un Button/DynamicItem
        # brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body". On crée
        # un Button BRUT avec le MÊME label/style/custom_id que PatrolDefendButton
        # (DynamicItem) ; le clic reste capté par le DynamicItem enregistré.
        btn = Button(
            label="🛡️ Défendre (+1 pt)",
            style=discord.ButtonStyle.danger,
            custom_id=f"patrol_defend:{active['patrol_id']}:{user_id}",
        )
        layout.add_item(discord.ui.ActionRow(btn))

    return layout


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent button
# ═══════════════════════════════════════════════════════════════════════════

class PatrolDefendButton(
    discord.ui.DynamicItem[Button],
    template=r"patrol_defend:(?P<patrol_id>\d+):(?P<user_id>\d+)",
):
    """Bouton de défense (persistent)."""

    def __init__(self, patrol_id: int, user_id: int):
        super().__init__(
            Button(
                label="🛡️ Défendre (+1 pt)",
                style=discord.ButtonStyle.danger,
                custom_id=f"patrol_defend:{patrol_id}:{user_id}",
            )
        )
        self.patrol_id = patrol_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["patrol_id"]), int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ta propre patrouille via les Régions du Codex.",
                    ephemeral=True,
                )
            except Exception:
                return

        try:
            await btn_i.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
            pass

        if btn_i.guild is None:
            try:
                await btn_i.followup.send("❌ Serveur uniquement.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            # Récupère la patrouille active
            active = await get_active_patrol(btn_i.guild.id)
            if not active or active["patrol_id"] != self.patrol_id:
                await btn_i.followup.send(
                    "❌ Patrouille close ou inactive.", ephemeral=True
                )
                return

            result = await defend_region(
                btn_i.guild.id, active["region_id"], btn_i.user.id, points=1,
            )

            if result.get("error"):
                await btn_i.followup.send(
                    f"❌ {result['error']}", ephemeral=True
                )
                return

            view = await build_patrol_panel(btn_i.guild.id, btn_i.user.id)
            confirm = (
                f"🛡️ +1 pt défense !\n"
                f"_Ta contribution : `{result['my_total']}/{result['max_per_user']}` pts._\n"
                f"_Défense globale : `{result['patrol_total']:,}/{result['target']:,}` "
                f"({result['pct']}%)_."
            )
            if view:
                try:
                    await btn_i.edit_original_response(
                        view=view, content=None, attachments=[],
                    )
                except Exception:
                    pass
            try:
                await btn_i.followup.send(confirm, ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[patrol_defend callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(PatrolDefendButton)
    except Exception as ex:
        print(f"[regional_state register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Announcements
# ═══════════════════════════════════════════════════════════════════════════

async def _find_chronicle_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    if _db_get is None:
        return None
    try:
        cfg = await _db_get(guild.id)
        for key in ("chronicle_channel_id", "hub_channel"):
            ch_id = int(cfg.get(key, 0) or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch:
                    return ch
    except Exception:
        pass
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["chronique", "lore", "saga", "histoire"]):
            return ch
    return None


async def _announce_patrol_open(
    guild: discord.Guild, region_id: str, target: int, is_reclaim: bool,
    closes_at: datetime,
) -> None:
    ch = await _find_chronicle_channel(guild)
    if not ch:
        return
    region = get_region_def(region_id) or {}
    head = "🚨 **Reconquête** " if is_reclaim else "🚨 **Patrouille** "
    msg = (
        f"{head}— {region.get('emoji', '?')} **{region.get('name', '?')}**\n\n"
        f"_{region.get('description', '…')}_\n\n"
        f"🎯 Objectif `{target}` pts · ⏱️ ferme dans {PATROL_DURATION_HOURS}h · "
        f"🛡️ max {MAX_POINTS_PER_USER} pts/membre\n\n"
        f"_📖 Codex → 🌍 Régions pour défendre._"
    )
    try:
        _t, _, _b = msg.partition("\n\n")
        await ch.send(
            view=ui_v2.recap_view(_t.replace("**", ""), _b or msg,
                                  color=ui_v2.Palette.INFO),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


async def _announce_patrol_closed(
    guild: discord.Guild, region_id: str, success: bool,
    defense: int, target: int, is_reclaim: bool,
    final_state: Optional[dict],
) -> None:
    ch = await _find_chronicle_channel(guild)
    if not ch:
        return
    region = get_region_def(region_id) or {}
    if success:
        if is_reclaim:
            head = (
                f"🎉 **Reconquête réussie** — "
                f"{region.get('emoji', '?')} {region.get('name', '?')}"
            )
        else:
            head = (
                f"🎉 **Patrouille réussie** — "
                f"{region.get('emoji', '?')} {region.get('name', '?')}"
            )
        body = (
            f"_La région est sauvée._\n\n"
            f"Défense : `{defense}/{target}` ({int(defense * 100 / max(1, target))}%)\n"
        )
        if final_state:
            body += (
                f"\nÉtat : 💚 Santé `{final_state['health']}/100` · "
                f"Menace `{final_state['threat']}/100`"
            )
    else:
        head = (
            f"💀 **PATROUILLE ÉCHOUÉE** — "
            f"{region.get('emoji', '?')} {region.get('name', '?')}"
        )
        body = (
            f"_La défense n'a pas suffi._\n\n"
            f"Défense : `{defense}/{target}` ({int(defense * 100 / max(1, target))}%)\n"
        )
        if final_state:
            body += (
                f"\nÉtat : {_health_icon(final_state['health'], final_state['is_fallen'])} "
                f"Santé `{final_state['health']}/100`"
            )
            if final_state["is_fallen"]:
                body += "\n\n⚠️ **Région tombée.** Debuff serveur appliqué."

    try:
        await ch.send(
            view=ui_v2.recap_view(
                head.replace("**", ""), body,
                color=(ui_v2.Palette.SUCCESS if success else ui_v2.Palette.DANGER)),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=15)
async def regional_task():
    """Toutes les 15 min : menace passive + open/close patrol."""
    if _bot is None or _get_db is None:
        return
    try:
        # Open patrouille mercredi 19h FR
        if _is_patrol_open_window():
            for guild in _bot.guilds:
                try:
                    await ensure_regions_initialized(guild.id)
                    await start_patrol(guild.id)
                except Exception as ex:
                    print(f"[regional_task open g={guild.id}] {ex}")

        # Apply passive threat (max 1x/15min mais idempotent via last_threat_tick)
        for guild in _bot.guilds:
            try:
                await apply_passive_threat(guild.id)
            except Exception as ex:
                print(f"[regional_task threat g={guild.id}] {ex}")

        # Close patrols expirées
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with _get_db() as db:
                async with db.execute(
                    "SELECT id FROM patrol_sessions "
                    "WHERE status='open' AND closes_at < ?",
                    (now_iso,),
                ) as cur:
                    to_close = [int(r[0]) for r in await cur.fetchall()]
            for pid in to_close:
                try:
                    await close_patrol(pid)
                except Exception as ex:
                    print(f"[regional_task close p={pid}] {ex}")
        except Exception as ex:
            print(f"[regional_task close scan] {ex}")
    except Exception as ex:
        print(f"[regional_task] {ex}")


@regional_task.before_loop
async def _regional_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point depuis le Codex
# ═══════════════════════════════════════════════════════════════════════════

async def open_regions_from_codex(interaction: discord.Interaction) -> None:
    """Appelé depuis le bouton 🌍 Régions dans le Codex."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_regions_from_codex defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        view = await build_regions_panel(interaction.guild.id, interaction.user.id)
        if view is None:
            await interaction.followup.send(
                "❌ Régions indisponibles.", ephemeral=True
            )
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_regions_from_codex] {ex}")
        try:
            await interaction.followup.send(
                f"❌ Erreur : `{ex}`", ephemeral=True,
            )
        except Exception:
            pass


__all__ = [
    "REGION_CATALOG",
    "HEALTH_MAX",
    "THREAT_MAX",
    "HEALTH_INITIAL",
    "THREAT_INITIAL",
    "PASSIVE_THREAT_PER_DAY",
    "PATROL_WEEKDAY",
    "PATROL_HOUR",
    "PATROL_DURATION_HOURS",
    "PATROL_TARGET_POINTS",
    "PATROL_RECLAIM_TARGET",
    "MAX_POINTS_PER_USER",
    "SERVER_DEBUFF_PER_FALLEN",
    "setup",
    "init_db",
    "get_region_def",
    "list_region_ids",
    "ensure_regions_initialized",
    "get_region_state",
    "get_all_regions_state",
    "get_server_debuff",
    "apply_passive_threat",
    "defend_region",
    "start_patrol",
    "close_patrol",
    "get_active_patrol",
    "build_regions_panel",
    "build_patrol_panel",
    "open_regions_from_codex",
    "PatrolDefendButton",
    "regional_task",
    "register_persistent_views",
]
