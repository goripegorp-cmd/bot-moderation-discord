"""
daily_bosses.py — Boss du jour, 4× par jour, avec gating de niveau (Phase 173.2).

🎯 OBJECTIF : combat collectif fort PLUSIEURS fois par jour (pas par semaine).
4 boss spawnent à heures fixes FR (midi, après-midi, soir, nuit). Difficulté
ALTERNÉE : niveau minimum requis qui tourne (boss faciles → boss costauds).

Différences clés vs les mobs (mob_hunts) :
- HP ÉLEVÉ (3000-18000) → IMPOSSIBLE en solo, collaboration OBLIGATOIRE
  (cap 30 attaques/membre × ~200 dmg = 6000 max → il faut plusieurs joueurs)
- Gating de NIVEAU : il faut economy.level >= min_level pour attaquer
- Timer : si pas tué dans le temps imparti → le boss se retire, retour normal
- Public dans l'arène (message live avec barre de HP + bouton Attaquer)

PHILOSOPHIE :
- Les gens doivent être AIDÉS (le boss a beaucoup de vie, fait des dégâts)
- Récompenses proportionnelles aux dégâts + bonus top 3
- Si raté → aucune pénalité, ça revient juste à la normale

API :
- setup(bot, get_db, db_get, v2, add_coins_fn)
- init_db()
- DAILY_BOSS_CATALOG, get_boss_def, list_boss_ids
- get_active_boss(guild_id) -> dict | None
- trigger_daily_boss(guild_id, boss_id=None) -> event_id | None
- record_boss_attack(guild_id, user_id) -> dict (gating niveau inclus)
- resolve_daily_boss(event_id) -> dict
- daily_boss_task (loop 15 min, check heures 12/17/21/1 FR)
- DailyBossAttackButton (DynamicItem persistent)
- register_persistent_views(bot)

DB :
- daily_boss_events (id PK, guild_id, boss_id, slot_key, message_id,
                     channel_id, hp_max, hp_current, damage_total,
                     started_at, expires_at, ended_at, status)
- daily_boss_attackers (event_id, user_id, damage_dealt, attack_count,
                        last_attack_at, PK(event_id, user_id))
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button
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

# Phase 193 : 5 créneaux fixes FR — MATIN (9h), midi, après-midi, soir, NUIT.
# Le créneau matin garantit un combat dès le réveil (vision owner : faire vivre
# la journée matin / midi / soir, pas juste le soir). _pick_boss_for_slot()
# utilise len(BOSS_HOURS) + .index(now.hour) → ajouter un créneau est sûr.
BOSS_HOURS = [9, 12, 17, 21, 1]
# Cap anti-spam : nb max d'attaques par membre par boss
MAX_ATTACKS_PER_USER = 30
# Dégâts par clic (avant bonus)
ATTACK_DAMAGE_MIN = 60
ATTACK_DAMAGE_MAX = 220
# Récompenses
COIN_PER_DAMAGE = 0.04
TOP3_BONUS_COINS = 1200
PARTICIPATION_BONUS_COINS = 150
# Bonus alliance : si 3+ membres d'une alliance participent (info — le détail
# alliance est géré côté serveur ; ici on garde la mécanique simple)
ALLIANCE_BONUS_MIN = 3
ALLIANCE_BONUS_MULT = 1.20


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE — 6 boss, difficulté CROISSANTE / alternée
# ═══════════════════════════════════════════════════════════════════════════
# - min_level : niveau requis (economy.level) pour pouvoir attaquer
# - hp_base   : élevé → collaboration obligatoire
# - lifetime_min : temps imparti avant retrait du boss
# - tier : étiquette de difficulté affichée

DAILY_BOSS_CATALOG = [
    {
        "id": "gobelin_roi",
        "name": "Gobelin Roi",
        "emoji": "👺",
        "tier": "Facile",
        "description": (
            "Un gobelin bouffi qui a volé le trésor du village. Accessible à "
            "tous — un bon entraînement pour débuter le combat collectif."
        ),
        "min_level": 0,
        "hp_base": 3000,
        "lifetime_min": 45,
        "color": 0x27AE60,
    },
    {
        "id": "golem_pierre",
        "name": "Golem de Pierre",
        "emoji": "🪨",
        "tier": "Facile+",
        "description": (
            "Un colosse de roche lent mais résistant. Frappez ensemble pour "
            "le fissurer. Niveau 3 minimum recommandé."
        ),
        "min_level": 3,
        "hp_base": 5000,
        "lifetime_min": 50,
        "color": 0x7F8C8D,
    },
    {
        "id": "hydre_marais",
        "name": "Hydre des Marais",
        "emoji": "🐉",
        "tier": "Moyen",
        "description": (
            "Une hydre à plusieurs têtes qui régénère si on la laisse "
            "respirer. Il faut frapper vite et nombreux. Niveau 5 requis."
        ),
        "min_level": 5,
        "hp_base": 8000,
        "lifetime_min": 60,
        "color": 0x16A085,
    },
    {
        "id": "chevalier_noir",
        "name": "Chevalier Noir",
        "emoji": "⚔️",
        "tier": "Difficile",
        "description": (
            "Un chevalier maudit en armure impénétrable. Seuls les "
            "aventuriers aguerris peuvent l'entamer. Niveau 8 requis."
        ),
        "min_level": 8,
        "hp_base": 12000,
        "lifetime_min": 70,
        "color": 0x2C3E50,
    },
    {
        "id": "dragon_cendres",
        "name": "Dragon de Cendres",
        "emoji": "🔥",
        "tier": "Très difficile",
        "description": (
            "Un dragon ancien crachant des cendres ardentes. Toute l'alliance "
            "doit converger pour l'abattre. Niveau 12 requis."
        ),
        "min_level": 12,
        "hp_base": 15000,
        "lifetime_min": 75,
        "color": 0xC0392B,
    },
    {
        "id": "titan_oublie",
        "name": "Titan Oublié",
        "emoji": "🗿",
        "tier": "Légendaire",
        "description": (
            "Une entité colossale des temps anciens. Le serveur ENTIER doit "
            "se coordonner. Niveau 15 requis. Récompenses légendaires."
        ),
        "min_level": 15,
        "hp_base": 18000,
        "lifetime_min": 90,
        "color": 0x8E44AD,
    },
]


def get_boss_def(boss_id: str) -> Optional[dict]:
    for b in DAILY_BOSS_CATALOG:
        if b["id"] == boss_id:
            return b
    return None


def list_boss_ids() -> list[str]:
    return [b["id"] for b in DAILY_BOSS_CATALOG]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
          inventory_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _inventory_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _inventory_fn = inventory_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_boss_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    boss_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0,
                    hp_max INTEGER NOT NULL,
                    hp_current INTEGER NOT NULL,
                    damage_total INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    ended_at TIMESTAMP,
                    status TEXT DEFAULT 'alive'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_boss_attackers (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage_dealt INTEGER DEFAULT 0,
                    attack_count INTEGER DEFAULT 0,
                    last_attack_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (event_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_boss_active "
                "ON daily_boss_events(guild_id, status)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[daily_bosses init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _now_paris() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc)


def _current_slot_key() -> Optional[str]:
    """Si on est dans un créneau de spawn (heure pile), retourne une clé
    unique 'YYYY-MM-DD-HH'. Sinon None."""
    now = _now_paris()
    if now.hour in BOSS_HOURS:
        return now.strftime("%Y-%m-%d-%H")
    return None


async def get_user_level(guild_id: int, user_id: int) -> int:
    """Lit le niveau du joueur depuis la table economy. Default 1."""
    if _get_db is None:
        return 1
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT level FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return 1
    except Exception:
        return 1


async def _find_arena_channel(guild: discord.Guild):
    """Réutilise le finder robuste de mob_hunts (7 niveaux de fallback).
    Fallback local minimal si mob_hunts indisponible."""
    try:
        import mob_hunts as _mh
        ch = await _mh._find_arena_channel(guild)
        if ch:
            return ch
    except Exception:
        pass
    # Fallback minimal : premier salon écrivable
    try:
        me = guild.me
        for ch in guild.text_channels:
            try:
                if me and ch.permissions_for(me).send_messages:
                    return ch
            except Exception:
                continue
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Active boss
# ═══════════════════════════════════════════════════════════════════════════

async def get_active_boss(guild_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, boss_id, hp_max, hp_current, damage_total, "
                "started_at, expires_at, message_id, channel_id "
                "FROM daily_boss_events "
                "WHERE guild_id=? AND status='alive' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "event_id": int(row[0]),
            "boss_id": row[1],
            "hp_max": int(row[2] or 0),
            "hp_current": int(row[3] or 0),
            "damage_total": int(row[4] or 0),
            "started_at": row[5],
            "expires_at": row[6],
            "message_id": int(row[7] or 0),
            "channel_id": int(row[8] or 0),
        }
    except Exception:
        return None


async def _user_attack_count(event_id: int, user_id: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT attack_count FROM daily_boss_attackers "
                "WHERE event_id=? AND user_id=?",
                (event_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
#  Trigger
# ═══════════════════════════════════════════════════════════════════════════

def _pick_boss_for_slot() -> dict:
    """Choisit le boss du créneau : rotation déterministe basée sur le jour +
    l'index d'heure → difficulté qui alterne."""
    now = _now_paris()
    day_of_year = now.timetuple().tm_yday
    try:
        slot_idx = BOSS_HOURS.index(now.hour)
    except ValueError:
        slot_idx = 0
    idx = (day_of_year * len(BOSS_HOURS) + slot_idx) % len(DAILY_BOSS_CATALOG)
    return DAILY_BOSS_CATALOG[idx]


async def trigger_daily_boss(
    guild: discord.Guild, boss_id: Optional[str] = None,
) -> Optional[int]:
    """Déclenche un boss du jour pour cette guild."""
    if _get_db is None or _bot is None or not guild:
        return None

    # Phase 191 : interrupteur Hub Événements — Boss quotidien
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('daily_boss_enabled', True)):
            return None
    except Exception:
        pass

    # Anti-doublon : déjà un boss actif ?
    if await get_active_boss(guild.id):
        return None

    # Phase 177 : pas de boss du jour pendant un GROS event masquant (Boss Raid /
    # Chasse au trésor / Quiz) — l'arène est dédiée à cet event, serveur masqué.
    # Évite que deux events de combat se superposent dans le même salon.
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM events WHERE guild_id=? AND ended=0 LIMIT 1",
                (guild.id,),
            ) as cur:
                if await cur.fetchone():
                    return None
    except Exception:
        pass

    slot_key = _current_slot_key()
    if slot_key is None and boss_id is None:
        return None  # pas dans un créneau (sauf déclenchement forcé)
    if slot_key is None:
        slot_key = _now_paris().strftime("%Y-%m-%d-%H") + "-forced"

    # Anti-doublon : déjà eu un boss sur ce créneau ?
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM daily_boss_events "
                "WHERE guild_id=? AND slot_key=? LIMIT 1",
                (guild.id, slot_key),
            ) as cur:
                if await cur.fetchone():
                    return None
    except Exception:
        pass

    boss = get_boss_def(boss_id) if boss_id else _pick_boss_for_slot()
    if not boss:
        return None

    ch = await _find_arena_channel(guild)
    if not ch:
        return None

    hp = int(boss["hp_base"])
    expires = datetime.now(timezone.utc) + timedelta(minutes=int(boss["lifetime_min"]))

    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO daily_boss_events "
                "(guild_id, boss_id, slot_key, channel_id, hp_max, hp_current, "
                "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild.id, boss["id"], slot_key, ch.id, hp, hp,
                 expires.isoformat()),
            )
            event_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[trigger_daily_boss INSERT] {ex}")
        return None

    # Poste le panel public + bouton
    msg = await _post_boss_panel(ch, event_id, boss, hp, hp, int(boss["lifetime_min"]))
    if msg:
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE daily_boss_events SET message_id=? WHERE id=?",
                    (msg.id, event_id),
                )
                await db.commit()
        except Exception:
            pass

    print(
        f"[daily_bosses] trigger guild={guild.id} boss={boss['id']} "
        f"hp={hp} lvl={boss['min_level']} event={event_id}"
    )
    return event_id


# ═══════════════════════════════════════════════════════════════════════════
#  Panel + live update
# ═══════════════════════════════════════════════════════════════════════════

def _hp_bar(cur_hp: int, max_hp: int, width: int = 18) -> str:
    if max_hp <= 0:
        return "░" * width
    pct = max(0, min(100, int(cur_hp * 100 / max_hp)))
    fill = int(width * pct / 100)
    return "█" * fill + "░" * (width - fill)


async def _post_boss_panel(
    ch, event_id: int, boss: dict, hp_cur: int, hp_max: int, lifetime_min: int,
) -> Optional[discord.Message]:
    """Poste le panel V2 du boss avec bouton Attaquer."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    pct = int(hp_cur * 100 / max(1, hp_max))
    lvl_txt = ("Accessible à tous" if boss["min_level"] <= 0
               else f"Niveau **{boss['min_level']}** requis")

    items = [
        v2_title(f"{boss['emoji']}  BOSS DU JOUR : {boss['name']}"),
        v2_subtitle(f"_Difficulté : {boss['tier']} · {lvl_txt}_"),
        v2_divider(),
        v2_body(f"_{boss['description']}_"),
        v2_divider(),
        v2_body(
            f"**❤️ HP**\n`{_hp_bar(hp_cur, hp_max)}`\n"
            f"`{hp_cur:,} / {hp_max:,}` ({pct}%)"
        ),
        v2_body(
            f"⏱️ Temps imparti : **{lifetime_min} min**\n"
            f"🤝 HP élevé → **impossible en solo**, combattez ensemble !\n"
            f"🏅 Top 3 dégâts = bonus `{TOP3_BONUS_COINS}` 🪙"
        ),
        v2_divider(),
        v2_body(_ev.how_to_play('daily_boss')),
    ]

    class _BossLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=boss.get("color", 0xC0392B)))

    layout = _BossLayout()
    layout.add_item(DailyBossAttackButton(event_id))

    try:
        return await ch.send(view=layout)
    except Exception as ex:
        print(f"[daily_bosses post_panel] {ex}")
        return None


async def _refresh_boss_panel(guild: discord.Guild, event_id: int) -> None:
    """Met à jour le message du boss avec les HP actuels."""
    active = await get_active_boss(guild.id)
    if not active or active["event_id"] != event_id:
        return
    boss = get_boss_def(active["boss_id"])
    if not boss or not active["message_id"] or not active["channel_id"]:
        return
    ch = guild.get_channel(active["channel_id"])
    if not ch:
        return
    try:
        msg = await ch.fetch_message(active["message_id"])
    except Exception:
        return
    if _v2 is None:
        return
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    pct = int(active["hp_current"] * 100 / max(1, active["hp_max"]))
    lvl_txt = ("Accessible à tous" if boss["min_level"] <= 0
               else f"Niveau **{boss['min_level']}** requis")
    items = [
        v2_title(f"{boss['emoji']}  BOSS DU JOUR : {boss['name']}"),
        v2_subtitle(f"_Difficulté : {boss['tier']} · {lvl_txt}_"),
        v2_divider(),
        v2_body(
            f"**❤️ HP**\n`{_hp_bar(active['hp_current'], active['hp_max'])}`\n"
            f"`{active['hp_current']:,} / {active['hp_max']:,}` ({pct}%)"
        ),
        v2_body(f"⚔️ Dégâts totaux infligés : `{active['damage_total']:,}`"),
    ]

    class _BossLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=boss.get("color", 0xC0392B)))

    layout = _BossLayout()
    if active["hp_current"] > 0:
        layout.add_item(DailyBossAttackButton(event_id))
    try:
        await msg.edit(view=layout)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Attack (avec gating de niveau)
# ═══════════════════════════════════════════════════════════════════════════

async def record_boss_attack(guild_id: int, user_id: int) -> dict:
    """Enregistre une attaque sur le boss actif, AVEC gating de niveau.

    Retourne {error} OU {success, damage, hp_current, ...}.
    """
    if _get_db is None:
        return {"error": "DB indisponible"}
    active = await get_active_boss(guild_id)
    if not active:
        return {"error": "Aucun boss actif"}
    if active["hp_current"] <= 0:
        return {"error": "Le boss est déjà vaincu"}

    boss = get_boss_def(active["boss_id"])
    if not boss:
        return {"error": "Boss introuvable"}

    # ─── GATING DE NIVEAU ───
    if boss["min_level"] > 0:
        user_lvl = await get_user_level(guild_id, user_id)
        if user_lvl < boss["min_level"]:
            return {
                "error": (
                    f"🔒 **{boss['name']}** demande le **niveau {boss['min_level']}**. "
                    f"Tu es niveau **{user_lvl}**. Monte en niveau (messages, quêtes, "
                    f"mobs) puis reviens — ou laisse les plus forts s'en charger !"
                ),
                "level_locked": True,
            }

    event_id = active["event_id"]
    attacks_done = await _user_attack_count(event_id, user_id)
    if attacks_done >= MAX_ATTACKS_PER_USER:
        return {
            "error": f"Tu as atteint le max ({MAX_ATTACKS_PER_USER} attaques) "
                     "pour ce boss.",
            "maxed": True,
        }

    damage = random.randint(ATTACK_DAMAGE_MIN, ATTACK_DAMAGE_MAX)
    # Phase 184 (cohérence) : l'ÉQUIPEMENT du joueur compte (ATK total + proc
    # élémentaire de l'arme), comme sur le Boss Raid → ton stuff/forge/éléments
    # servent aussi contre les boss du jour.
    elem_proc = None
    if _inventory_fn is not None:
        try:
            import events_engine as _ev
            inv = await _inventory_fn(guild_id, user_id)
            damage += int(_ev.inventory_total_stats(inv).get("atk", 0) or 0)
            _p = _ev.roll_elemental_proc(inv.get("weapon"))
            if _p:
                damage += int(_p.get("bonus", 0) or 0)
                elem_proc = _p
        except Exception:
            pass
    damage = min(damage, active["hp_current"])

    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO daily_boss_attackers "
                "(event_id, user_id, damage_dealt, attack_count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(event_id, user_id) DO UPDATE SET "
                "damage_dealt = damage_dealt + ?, "
                "attack_count = attack_count + 1, "
                "last_attack_at = CURRENT_TIMESTAMP",
                (event_id, user_id, damage, damage),
            )
            await db.execute(
                "UPDATE daily_boss_events SET "
                "hp_current = MAX(0, hp_current - ?), "
                "damage_total = damage_total + ? WHERE id=?",
                (damage, damage, event_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[record_boss_attack] {ex}")
        return {"error": str(ex)}

    # Feed Chronicle (boss_damage) — fail-soft tie-in
    try:
        import story_engine as _se
        await _se.on_boss_damage(guild_id, damage, user_id)
    except Exception:
        pass

    updated = await get_active_boss(guild_id)
    boss_dead = (updated is None) or (updated["hp_current"] <= 0)
    if boss_dead:
        await resolve_daily_boss(event_id)
        return {"success": True, "damage": damage, "boss_dead": True,
                "attack_count": attacks_done + 1, "elem": elem_proc}

    return {
        "success": True,
        "damage": damage,
        "hp_current": updated["hp_current"],
        "hp_max": updated["hp_max"],
        "attack_count": attacks_done + 1,
        "max_attacks": MAX_ATTACKS_PER_USER,
        "boss_dead": False,
        "elem": elem_proc,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Resolve
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_daily_boss(event_id: int) -> Optional[dict]:
    if _get_db is None or _bot is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, boss_id, hp_current, hp_max, damage_total, "
                "channel_id, status FROM daily_boss_events WHERE id=?",
                (event_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        guild_id, boss_id, hp_current, hp_max, dmg_total, channel_id, status = row
        if status != "alive":
            return None
    except Exception:
        return None

    boss = get_boss_def(boss_id)
    killed = int(hp_current) <= 0
    final_status = "killed" if killed else "expired"

    # Attackers classés
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, damage_dealt FROM daily_boss_attackers "
                "WHERE event_id=? AND damage_dealt > 0 "
                "ORDER BY damage_dealt DESC",
                (event_id,),
            ) as cur:
                attackers = [(int(r[0]), int(r[1])) for r in await cur.fetchall()]
    except Exception:
        attackers = []

    rewards = []
    for i, (uid, dmg) in enumerate(attackers):
        coins = int(dmg * COIN_PER_DAMAGE)
        if killed:
            coins += PARTICIPATION_BONUS_COINS
            if i < 3:
                coins += TOP3_BONUS_COINS
        try:
            if _add_coins:
                await _add_coins(guild_id, uid, coins)
        except Exception:
            pass
        rewards.append({"user_id": uid, "damage": dmg, "coins": coins,
                        "rank": i + 1})

    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE daily_boss_events SET status=?, ended_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (final_status, event_id),
            )
            await db.commit()
    except Exception:
        pass

    guild = _bot.get_guild(int(guild_id))
    if guild and channel_id:
        ch = guild.get_channel(int(channel_id))
        if ch:
            await _announce_resolution(
                ch, boss, killed, int(dmg_total), int(hp_max), rewards,
            )

    print(
        f"[daily_bosses] resolve event={event_id} killed={killed} "
        f"dmg={dmg_total}/{hp_max} attackers={len(attackers)}"
    )
    return {"killed": killed, "damage_total": int(dmg_total),
            "attackers": len(attackers), "rewards": rewards}


async def _announce_resolution(
    ch, boss: Optional[dict], killed: bool, dmg_total: int, hp_max: int,
    rewards: list,
) -> None:
    name = boss["name"] if boss else "Le boss"
    emoji = boss["emoji"] if boss else "⚔️"
    if killed:
        head = f"🎉 **{emoji} {name} EST VAINCU !**"
        body = (
            f"_Le serveur a uni ses forces et triomphé._\n\n"
            f"Dégâts totaux : `{dmg_total:,}` · Combattants : `{len(rewards)}`\n"
        )
    else:
        head = f"⏳ **{emoji} {name} s'est retiré...**"
        body = (
            f"_Le temps a manqué. Le boss disparaît dans les ombres. Le serveur "
            f"revient à la normale — réessayez au prochain boss !_\n\n"
            f"Dégâts infligés : `{dmg_total:,} / {hp_max:,}` "
            f"({int(dmg_total * 100 / max(1, hp_max))}%)\n"
        )

    if rewards:
        lines = ["\n**🏅 Top combattants :**"]
        for r in rewards[:3]:
            member = ch.guild.get_member(r["user_id"]) if ch.guild else None
            nm = member.display_name if member else f"User {r['user_id']}"
            medal = ["🥇", "🥈", "🥉"][r["rank"] - 1]
            lines.append(f"{medal} **{nm}** : `{r['damage']:,}` dmg · `{r['coins']:,}` 🪙")
        if len(rewards) > 3:
            lines.append(f"_+ {len(rewards) - 3} autres récompensés._")
        body += "\n".join(lines)

    try:
        await ch.send(
            view=ui_v2.recap_view(
                head.replace("**", ""), body,
                color=(ui_v2.Palette.SUCCESS if killed else ui_v2.Palette.NEUTRAL)),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent button
# ═══════════════════════════════════════════════════════════════════════════

class DailyBossAttackButton(
    discord.ui.DynamicItem[Button],
    template=r"dboss_atk:(?P<event_id>\d+)",
):
    """Bouton public d'attaque du boss du jour (persistent, tout le monde
    peut cliquer — le gating de niveau est dans le callback)."""

    def __init__(self, event_id: int):
        super().__init__(
            Button(
                label="⚔️ Attaquer le boss",
                style=discord.ButtonStyle.danger,
                custom_id=f"dboss_atk:{event_id}",
            )
        )
        self.event_id = event_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["event_id"]))

    async def callback(self, btn_i: discord.Interaction):
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
            result = await record_boss_attack(btn_i.guild.id, btn_i.user.id)
            if result.get("error"):
                await btn_i.followup.send(result["error"], ephemeral=True)
                return

            # Rafraîchit le panneau public (HP live)
            try:
                await _refresh_boss_panel(btn_i.guild, self.event_id)
            except Exception:
                pass

            # Phase 184 : note de proc élémentaire (si l'arme a déclenché)
            _ep = result.get("elem")
            _elem_note = (
                f"\n{_ep['emoji']} **{_ep['name']}** ! +`{_ep['bonus']}` dégâts élémentaires"
                if _ep else ""
            )
            if result.get("boss_dead"):
                await btn_i.followup.send(
                    f"⚔️ **{result['damage']} dégâts** — coup final ! "
                    f"Le boss est tombé, récompenses distribuées. 🎉{_elem_note}",
                    ephemeral=True,
                )
            else:
                pct = int(result["hp_current"] * 100 / max(1, result["hp_max"]))
                await btn_i.followup.send(
                    f"⚔️ **{result['damage']} dégâts** infligés !{_elem_note}\n"
                    f"_Boss : `{result['hp_current']:,}/{result['hp_max']:,}` HP "
                    f"({pct}%) · tes attaques : "
                    f"`{result['attack_count']}/{result['max_attacks']}`_",
                    ephemeral=True,
                )
        except Exception as ex:
            print(f"[dboss_atk callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(DailyBossAttackButton)
    except Exception as ex:
        print(f"[daily_bosses register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=15)
async def daily_boss_task():
    """Toutes les 15 min : spawn aux créneaux 12/17/21/1 FR + resolve expirés."""
    if _bot is None or _get_db is None:
        return
    try:
        # Spawn si on est dans un créneau
        if _current_slot_key() is not None:
            for guild in _bot.guilds:
                try:
                    await trigger_daily_boss(guild)
                except Exception as ex:
                    print(f"[daily_boss_task trigger g={guild.id}] {ex}")

        # Resolve les boss expirés (timer dépassé)
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with _get_db() as db:
                async with db.execute(
                    "SELECT id FROM daily_boss_events "
                    "WHERE status='alive' AND (expires_at < ? OR hp_current <= 0)",
                    (now_iso,),
                ) as cur:
                    to_resolve = [int(r[0]) for r in await cur.fetchall()]
            for eid in to_resolve:
                try:
                    await resolve_daily_boss(eid)
                except Exception as ex:
                    print(f"[daily_boss_task resolve e={eid}] {ex}")
        except Exception as ex:
            print(f"[daily_boss_task resolve scan] {ex}")
    except Exception as ex:
        print(f"[daily_boss_task] {ex}")


@daily_boss_task.before_loop
async def _daily_boss_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "DAILY_BOSS_CATALOG",
    "BOSS_HOURS",
    "MAX_ATTACKS_PER_USER",
    "ATTACK_DAMAGE_MIN",
    "ATTACK_DAMAGE_MAX",
    "COIN_PER_DAMAGE",
    "TOP3_BONUS_COINS",
    "PARTICIPATION_BONUS_COINS",
    "setup",
    "init_db",
    "get_boss_def",
    "list_boss_ids",
    "get_user_level",
    "get_active_boss",
    "trigger_daily_boss",
    "record_boss_attack",
    "resolve_daily_boss",
    "DailyBossAttackButton",
    "daily_boss_task",
    "register_persistent_views",
]
