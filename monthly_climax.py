"""
monthly_climax.py — Boss Climax mensuel thématique (Phase 170.8).

🎯 OBJECTIF : Une fois par mois, le serveur affronte un BOSS CLIMAX
thématiquement lié au chapitre actuel de la Chronique. Le boss vivra
2-3 heures. Les attackers reçoivent des récompenses cumulées en
fonction de leurs dégâts. Le top contributeur obtient un TITRE
PERMANENT.

PHILOSOPHIE :
- 1 boss par mois (1er samedi 21h FR) — événement à ne pas rater
- Le boss change selon le chapitre actif = narratif progressif
- HP massif (5000-50000) → impossible à solo, force la coopération
- Récompenses proportionnelles aux dégâts (équitable)
- Titre permanent au top 3 → fierté durable, gravée dans Codex
- Alimente la progression Chronique (kind: boss_damage,
  chapitre 3.3 = 200000 boss_damage → ~3 climax pour finir)

API :
- setup(bot, get_db, db_get, v2, story_module, npc_module)
- init_db()
- CLIMAX_BOSSES (9 boss thématiques, 1 par chapitre)
- get_climax_boss_for_chapter(chapter_id) → dict
- trigger_climax(guild_id) → climax_id | None
- record_attack(guild_id, user_id, damage) → dict
- resolve_climax(climax_id) → dict
- get_active_climax(guild_id) → dict | None
- get_user_titles(guild_id, user_id) → list
- build_climax_panel(guild_id, user_id) → LayoutView
- ClimaxAttackButton (DynamicItem)
- climax_task (loop hourly)
- register_persistent_views(bot)
- open_climax_from_codex(interaction)

DB :
- climax_events (id PK, guild_id, chapter_id, boss_id, month_key,
                 hp_max, hp_current, damage_total, started_at,
                 ends_at, ended_at, status, message_id, channel_id)
- climax_attackers (event_id, user_id, damage_dealt, last_attack_at)
                   PRIMARY KEY (event_id, user_id)
- climax_titles (id PK, guild_id, user_id, title, chapter_id,
                 earned_at)
"""
from __future__ import annotations

import asyncio
import random
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
_add_coins = None
# Phase 213 : arène de combat DÉDIÉE (créée au spawn, supprimée à la fin), comme
# le boss du jour. Fail-open : si None, on retombe sur _find_chronicle_channel.
_arena_create_fn = None  # async (guild, kind, title) -> salon texte dédié
_arena_delete_fn = None  # async (guild, text_channel_id) -> supprime l'arène
_event_busy_fn = None  # Phase 230 : async (guild_id) -> True si un AUTRE event de combat tourne (injecté)
_claim_lock_fn = None  # Phase 262 : async (guild_id, type) -> True si claim de spawn acquis (injecté)
_report_fn = None  # Phase 235.15 : async (guild, title, body) -> récap consolidé dans « 📜 chroniques-combat »
_event_mention_fn = None  # Phase 235.24 : async (guild, type) -> mention rôles opt-in (/notify + 🔔)
_pet_strike_fn = None  # Phase 261 (4/4) : async (guild_id, user_id) -> coeur partagé _pet_strike (bot.py)
_last_pet_click: dict[tuple, float] = {}  # anti-429 par (guild,user) sur le bouton 🐾 climax
_PET_CLICK_CD = 2.0
# Phase 235.16 : warm-up climax (clé = event_id) — sas de préparation au spawn.
_CLIMAX_WARMUP_SECONDS = 25
_warmup_until: dict[int, float] = {}

CLIMAX_WEEKDAY = 5    # samedi
CLIMAX_HOUR = 21      # 21h FR
CLIMAX_DURATION_HOURS = 3

# Récompenses
COIN_PER_DAMAGE = 0.05  # 0.05 coins par damage point
TOP3_BONUS_COINS = 2000
PARTICIPATION_BONUS_COINS = 200
MAX_ATTACKS_PER_USER = 50  # anti-spam
ATTACK_DAMAGE_MIN = 50
ATTACK_DAMAGE_MAX = 200


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE BOSS CLIMAX (1 par chapitre)
# ═══════════════════════════════════════════════════════════════════════════
# Chaque boss est thématiquement lié à son chapitre :
# - chapter_id : 1.1, 1.2, ..., 3.3
# - name, emoji, description, lore, hp_base
# - winning_title : titre permanent au top 3 contributeurs
# - participation_title : titre pour tous les attackers (option, peut être None)

CLIMAX_BOSSES = [
    {
        "id": "climax_1_1",
        "chapter_id": "1.1",
        "name": "Le Brouillard de Cendre",
        "emoji": "🌫️",
        "description": (
            "Une masse informe de cendres compactes qui flotte au-dessus de "
            "la forêt. Plus elle est attaquée, plus elle révèle des visages "
            "qui hurlent. Aria pense qu'elle est l'écho de mille morts oubliées."
        ),
        "lore": (
            "Un présage. Le premier vrai signe que les cendres ne sont pas "
            "un simple phénomène naturel."
        ),
        "hp_base": 8000,
        "winning_title": "Disperseur du Brouillard",
        "participation_title": "Témoin du Premier Boss",
    },
    {
        "id": "climax_1_2",
        "chapter_id": "1.2",
        "name": "Le Premier Gardien",
        "emoji": "🗿",
        "description": (
            "Une statue géante qui s'anime au pied de la Source des Cendres. "
            "Elle protège un secret depuis des siècles. Korr reconnaît la "
            "facture : c'est l'œuvre de forgerons disparus."
        ),
        "lore": (
            "Ce qu'il garde est plus important que lui. Le serveur devra le "
            "vaincre pour avancer."
        ),
        "hp_base": 12000,
        "winning_title": "Brise-Gardien",
        "participation_title": "Voyageur des Profondes",
    },
    {
        "id": "climax_1_3",
        "chapter_id": "1.3",
        "name": "L'Augure des Profondeurs",
        "emoji": "👁️",
        "description": (
            "Une entité oraculaire qui apparaît pour tester la résolution "
            "du serveur avant le Premier Choix. Elle parle d'une voix faite "
            "de mille voix. Personne ne sait si elle ment ou pas."
        ),
        "lore": (
            "Vaincre l'Augure prouve au Conseil que le serveur est digne de "
            "décider de son destin."
        ),
        "hp_base": 15000,
        "winning_title": "Briseur d'Augure",
        "participation_title": "Voix de l'Éveil",
    },
    {
        "id": "climax_2_1",
        "chapter_id": "2.1",
        "name": "Le Ravisseur d'Âmes",
        "emoji": "👻",
        "description": (
            "Entité spectrale qui a kidnappé Korr, Lyra, et Drazek. Pour "
            "les libérer, le serveur doit la vaincre. Elle se nourrit de la "
            "mémoire qu'on lui livre."
        ),
        "lore": (
            "Plus on lutte, plus elle s'affaiblit — mais plus elle absorbe "
            "aussi de nos souvenirs."
        ),
        "hp_base": 20000,
        "winning_title": "Libérateur des Âmes",
        "participation_title": "Veilleur des Disparus",
    },
    {
        "id": "climax_2_2",
        "chapter_id": "2.2",
        "name": "Le Tisseur d'Énigmes",
        "emoji": "🕷️",
        "description": (
            "Araignée géante qui tisse des fils de mystère. Chaque fil coupé "
            "révèle un fragment d'indice. Mais elle ne se laisse pas faire — "
            "ses pattes frappent à la vitesse de la pensée."
        ),
        "lore": (
            "Lyra dit qu'il sait des choses sur le sceau ancien. Mais il les "
            "garde pour lui."
        ),
        "hp_base": 25000,
        "winning_title": "Coupeur de Toile",
        "participation_title": "Limier des Cendres",
    },
    {
        "id": "climax_2_3",
        "chapter_id": "2.3",
        "name": "Le Gardien du Sanctuaire",
        "emoji": "⚔️",
        "description": (
            "Un colosse de pierre et de glace au pied du Sanctuaire. Il ne "
            "laisse passer que ceux qui ont prouvé leur valeur. Drazek le "
            "respecte ; il dit qu'il ne combat pas par méchanceté mais par "
            "devoir."
        ),
        "lore": (
            "Vaincu, il s'efface. Le passage vers le Sanctuaire s'ouvre."
        ),
        "hp_base": 30000,
        "winning_title": "Ouvre-Passage",
        "participation_title": "Pèlerin du Sanctuaire",
    },
    {
        "id": "climax_3_1",
        "chapter_id": "3.1",
        "name": "L'Avant-coureur",
        "emoji": "🐲",
        "description": (
            "Un dragon de cendres, héraut du Boss Final. Sa simple présence "
            "fait trembler le sol. Drazek dit qu'il connaît son nom mais "
            "refuse de le prononcer."
        ),
        "lore": (
            "Sa mort prouve au serveur qu'il est prêt pour l'Affrontement Final."
        ),
        "hp_base": 35000,
        "winning_title": "Tueur d'Avant-coureur",
        "participation_title": "Forgeron de la Fin",
    },
    {
        "id": "climax_3_2",
        "chapter_id": "3.2",
        "name": "La Sentinelle de l'Affrontement",
        "emoji": "🛡️",
        "description": (
            "Un golem antique conçu pour empêcher quiconque d'atteindre "
            "l'Entité Enchaînée. Le serveur entier doit converger pour le "
            "briser. Aria pleure en le voyant."
        ),
        "lore": (
            "Vaincre la Sentinelle, c'est franchir le dernier seuil."
        ),
        "hp_base": 40000,
        "winning_title": "Brise-Sentinelle",
        "participation_title": "Stratège du Sanctuaire",
    },
    {
        "id": "climax_3_3",
        "chapter_id": "3.3",
        "name": "L'Entité Enchaînée",
        "emoji": "👁️‍🗨️",
        "description": (
            "Ce qui a été scellé depuis des siècles, maintenant libéré. "
            "Personne ne sait à quoi il ressemble vraiment — chaque attaquant "
            "voit une forme différente. C'est le Boss Final de la Chronique."
        ),
        "lore": (
            "Sa chute clôt la Chronique. Le serveur entrera dans l'Épilogue."
        ),
        "hp_base": 50000,
        "winning_title": "Héros de la Chronique",
        "participation_title": "Témoin de la Fin",
    },
]


def get_climax_boss_for_chapter(chapter_id: str) -> Optional[dict]:
    for b in CLIMAX_BOSSES:
        if b["chapter_id"] == chapter_id:
            return b
    return None


def get_climax_boss_by_id(boss_id: str) -> Optional[dict]:
    for b in CLIMAX_BOSSES:
        if b["id"] == boss_id:
            return b
    return None


def list_climax_ids() -> list[str]:
    return [b["id"] for b in CLIMAX_BOSSES]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    story_module=None, npc_module=None, add_coins_fn=None,
    arena_create_fn=None, arena_delete_fn=None, event_busy_fn=None,
    report_fn=None, event_mention_fn=None, pet_strike_fn=None,
    claim_lock_fn=None, echo_fn=None,
):
    global _bot, _get_db, _db_get, _v2, _story, _npc, _add_coins
    global _arena_create_fn, _arena_delete_fn, _event_busy_fn, _report_fn, _event_mention_fn
    global _pet_strike_fn, _claim_lock_fn, _echo_fn
    _bot = bot_instance
    _echo_fn = echo_fn  # _post_event_echo (accroche 1-ligne chat, sans @, auto-supprimée)
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _story = story_module
    _npc = npc_module
    _add_coins = add_coins_fn
    # Phase 213 : arène de combat dédiée (créée au spawn, supprimée à la fin)
    _arena_create_fn = arena_create_fn
    _arena_delete_fn = arena_delete_fn
    # Phase 230 : verrou global « un seul event de combat à la fois »
    _event_busy_fn = event_busy_fn
    # Phase 235.15 : rapport de fin consolidé → « 📜 chroniques-combat »
    _report_fn = report_fn
    # Phase 235.24 : mention des rôles opt-in (/notify + 🔔 Climax) au spawn
    _event_mention_fn = event_mention_fn
    # Phase 261 (4/4) : cœur partagé d'appui familier (sinon record_pet_assist bail).
    _pet_strike_fn = pet_strike_fn
    # Phase 262 : claim atomique de spawn (anti-course TOCTOU).
    _claim_lock_fn = claim_lock_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS climax_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    chapter_id TEXT NOT NULL,
                    boss_id TEXT NOT NULL,
                    month_key TEXT NOT NULL,
                    hp_max INTEGER NOT NULL,
                    hp_current INTEGER NOT NULL,
                    damage_total INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP NOT NULL,
                    ended_at TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS climax_attackers (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage_dealt INTEGER DEFAULT 0,
                    attack_count INTEGER DEFAULT 0,
                    last_attack_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (event_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS climax_titles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    chapter_id TEXT,
                    boss_id TEXT,
                    earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_climax_active "
                "ON climax_events(guild_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_climax_titles_user "
                "ON climax_titles(guild_id, user_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[monthly_climax init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Time helpers
# ═══════════════════════════════════════════════════════════════════════════

def _paris_now() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _is_climax_window() -> bool:
    """True si 1er samedi du mois à 21h FR."""
    now = _paris_now()
    if now.weekday() != CLIMAX_WEEKDAY:
        return False
    if now.hour != CLIMAX_HOUR:
        return False
    # 1er samedi : jour <= 7
    return now.day <= 7


def _current_month_key() -> str:
    return _paris_now().strftime("%Y-%m")


# ═══════════════════════════════════════════════════════════════════════════
#  Active climax
# ═══════════════════════════════════════════════════════════════════════════

async def get_active_climax(guild_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, chapter_id, boss_id, hp_max, hp_current, "
                "damage_total, started_at, ends_at, message_id, channel_id "
                "FROM climax_events "
                "WHERE guild_id=? AND status='active' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "event_id": int(row[0]),
            "chapter_id": row[1],
            "boss_id": row[2],
            "hp_max": int(row[3] or 0),
            "hp_current": int(row[4] or 0),
            "damage_total": int(row[5] or 0),
            "started_at": row[6],
            "ends_at": row[7],
            "message_id": int(row[8] or 0),
            "channel_id": int(row[9] or 0),
        }
    except Exception:
        return None


async def get_user_attack_count(event_id: int, user_id: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT attack_count FROM climax_attackers "
                "WHERE event_id=? AND user_id=?",
                (event_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
#  Titles
# ═══════════════════════════════════════════════════════════════════════════

async def get_user_titles(
    guild_id: int, user_id: int, limit: int = 20,
) -> list[dict]:
    if _get_db is None:
        return []
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT title, chapter_id, boss_id, earned_at "
                "FROM climax_titles "
                "WHERE guild_id=? AND user_id=? "
                "ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "title": r[0],
                "chapter_id": r[1],
                "boss_id": r[2],
                "earned_at": r[3],
            })
    except Exception:
        pass
    return out


async def _grant_title(
    guild_id: int, user_id: int, title: str,
    chapter_id: str, boss_id: str,
) -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO climax_titles "
                "(guild_id, user_id, title, chapter_id, boss_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, title, chapter_id, boss_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[_grant_title] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Trigger climax
# ═══════════════════════════════════════════════════════════════════════════

async def trigger_climax(guild_id: int) -> Optional[int]:
    """Déclenche un Boss Climax pour cette guild si :
    - Aucun climax actif
    - Pas déjà un climax ce mois
    - Story engine donne un chapitre courant
    """
    if _get_db is None or _bot is None or _story is None:
        return None

    # Anti-doublon : déjà actif ?
    if await get_active_climax(guild_id):
        return None

    # Anti-doublon : déjà eu un climax ce mois ?
    month = _current_month_key()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM climax_events "
                "WHERE guild_id=? AND month_key=? LIMIT 1",
                (guild_id, month),
            ) as cur:
                if await cur.fetchone():
                    return None
    except Exception:
        pass

    # Phase 230 : VERROU GLOBAL — pas de boss climax par-dessus un autre event de
    # combat en cours (boss raid / quiz / world boss / boss du jour). Un seul à la
    # fois ; il se relancera plus tard. Fail-open si l'injection manque.
    if _event_busy_fn is not None:
        try:
            if await _event_busy_fn(guild_id):
                return None
        except Exception:
            pass
    # Phase 262 : CLAIM ATOMIQUE — anti-course TOCTOU (2 spawns simultanés qui passent
    # tous deux le verrou avant insertion). Si un autre event vient de claim → bail.
    if _claim_lock_fn is not None:
        try:
            if not await _claim_lock_fn(guild_id, 'climax'):
                return None  # CONFLIT : un autre event tient déjà le verrou → on n'empile pas
        except Exception:
            pass  # erreur infra du claim → fail-OPEN (le verrou-grâce a déjà filtré)

    # Get state
    state = await _story.get_state(guild_id)
    if not state:
        return None
    chapter_id = state["chapter_id"]
    boss = get_climax_boss_for_chapter(chapter_id)
    if not boss:
        return None

    # Difficulté dynamique (FAIL-OPEN strict, additif) : HP adaptés à la foule.
    # facteur BORNÉ [0.7..2.0] selon le nb d'actifs du jour, plancher/plafond
    # ABSOLUS relatifs au boss. La moindre erreur → facteur 1.0 (HP de base actuel).
    hp_base = int(boss["hp_base"])
    hp = hp_base
    try:
        import activity_system as _act
        _g = _bot.get_guild(guild_id) if _bot else None
        _f = await _act.crowd_hp_factor(_g)
        hp = _act.apply_crowd_hp(
            hp_base, _f,
            floor=int(hp_base * _act.CROWD_HP_FACTOR_MIN),
            cap=int(hp_base * _act.CROWD_HP_FACTOR_MAX),
        )
    except Exception as ex:
        print(f"[trigger_climax crowd_hp] {ex}")
        hp = hp_base  # FAIL-OPEN : HP de base
    ends_at = datetime.now(timezone.utc) + timedelta(hours=CLIMAX_DURATION_HOURS)

    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO climax_events "
                "(guild_id, chapter_id, boss_id, month_key, "
                "hp_max, hp_current, ends_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, chapter_id, boss["id"], month, hp, hp,
                 ends_at.isoformat()),
            )
            event_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[trigger_climax INSERT] {ex}")
        return None

    guild = _bot.get_guild(guild_id)
    if guild:
        # Phase 213 : salon DÉDIÉ pour ce boss climax (catégorie ⚔️ + texte +
        # vocaux), créé puis supprimé à la fin — comme le boss du jour. On stocke
        # son id dans climax_events.channel_id pour le supprimer à la résolution.
        # Fail-open : si l'arène échoue, _announce_climax_open retombe sur
        # _find_chronicle_channel (ch=None).
        ch = None
        if _arena_create_fn is not None:
            try:
                ch = await _arena_create_fn(guild, 'monthly_climax', boss['name'])
            except Exception as ex:
                print(f"[trigger_climax arena create] {ex}")
        if ch is not None:
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE climax_events SET channel_id=? WHERE id=?",
                        (ch.id, event_id),
                    )
                    await db.commit()
            except Exception as ex:
                print(f"[trigger_climax channel_id store] {ex}")
        # Phase 235.16 : warm-up — invulnérable les premières secondes (sas de prép.).
        _warm = datetime.now(timezone.utc).timestamp() + _CLIMAX_WARMUP_SECONDS
        _warmup_until[event_id] = _warm
        try:
            await _announce_climax_open(guild, boss, event_id, ends_at, channel=ch,
                                        warmup_ts=_warm)
        except Exception as _ann_ex:
            print(f"[trigger_climax announce] {_ann_ex}")
            # FIX salons (anti-salon-vide) : l'annonce n'est pas partie → ne PAS laisser
            # un climax « fantôme » (status='active', ends_at = +CLIMAX_DURATION_HOURS)
            # bloquer _has_any_major_event_running NI un salon par-type VIDE traîner des
            # heures. On clôt l'event (status='expired') + supprime le salon dédié créé.
            # Fail-open.
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE climax_events SET status='expired', "
                        "ended_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'",
                        (event_id,),
                    )
                    await db.commit()
            except Exception:
                pass
            if ch is not None and _arena_delete_fn is not None:
                try:
                    await _arena_delete_fn(guild, ch.id)
                except Exception:
                    pass
            return None
        # Accroche 1-ligne dans le chat (sans @mention, auto-supprimée) : sinon le boss
        # climax mensuel était invisible hors abonnés au rôle 🔔 Climax. _echo_fn =
        # _post_event_echo (bot.py). globals().get → zéro risque de NameError.
        _echo = globals().get('_echo_fn')
        if _echo is not None and ch is not None:
            try:
                await _echo(guild, ch, 'climax')
            except Exception:
                pass
        # Phase 235.24 : ping des rôles opt-in (/notify + 🔔 Climax). L'annonce est en
        # V2 (pas de content) → message de ping séparé, roles=True.
        if _event_mention_fn is not None and ch is not None:
            try:
                _cm = await _event_mention_fn(guild, 'climax')
                if _cm:
                    # Phase 258.3 : bouton 🔔/🔕 SOUS le ping (zéro commande). Boutons
                    # NUS → captés par les handlers globaux de bot.py : `evtnotif:climax`
                    # par le DynamicItem EventNotifyButton, `events_optout` par la vue
                    # persistante EventsOptOutView. Pas d'import croisé nécessaire.
                    _nv = discord.ui.View(timeout=None)
                    _nv.add_item(Button(
                        label="🔔 Me notifier (Climax)", style=discord.ButtonStyle.success,
                        custom_id="evtnotif:climax"))
                    _nv.add_item(Button(
                        label="🔕 Plus aucun event", style=discord.ButtonStyle.secondary,
                        custom_id="events_optout"))
                    # Phase 260.1 : delete_after = durée du climax → le message-ping
                    # ne survit JAMAIS à l'event (anti ghost ping si le salon persiste,
                    # ex. fallback chroniques). La notif a été consommée pendant l'event.
                    await ch.send(_cm, view=_nv, delete_after=CLIMAX_DURATION_HOURS * 3600,
                                  allowed_mentions=discord.AllowedMentions(
                                      roles=True, users=True, everyone=False))
            except Exception:
                pass

    if _story is not None:
        try:
            await _story.log_chronicle_event(
                guild_id, "climax_started",
                {"chapter_id": chapter_id, "boss_id": boss["id"],
                 "name": boss["name"], "hp": hp},
            )
        except Exception:
            pass

    print(
        f"[monthly_climax] trigger guild={guild_id} boss={boss['id']} "
        f"hp={hp} event={event_id}"
    )
    return event_id


# ═══════════════════════════════════════════════════════════════════════════
#  Attack
# ═══════════════════════════════════════════════════════════════════════════

async def record_attack(
    guild_id: int, user_id: int, damage: int = 0,
) -> dict:
    """Enregistre une attaque. Si damage=0, on tire un random dans
    [ATTACK_DAMAGE_MIN, ATTACK_DAMAGE_MAX]."""
    if _get_db is None:
        return {"error": "DB indisponible"}
    active = await get_active_climax(guild_id)
    if not active:
        return {"error": "Aucun climax actif"}
    event_id = active["event_id"]
    if active["hp_current"] <= 0:
        return {"error": "Boss déjà tombé"}

    # Phase 235.16 : WARM-UP — sas de préparation au spawn (fail-open au reboot →
    # attaquable normalement). Même principe que Boss Raid / World Boss / boss du jour.
    _wu = _warmup_until.get(event_id, 0)
    if _wu and datetime.now(timezone.utc).timestamp() < _wu:
        return {
            "error": (
                f"⏳ **Le Climax se prépare !** Le combat commence <t:{int(_wu)}:R>.\n"
                f"Équipe ton meilleur stuff (`/inventory`) et rejoins un vocal en attendant !"
            ),
            "warmup": True,
        }

    attacks_done = await get_user_attack_count(event_id, user_id)
    if attacks_done >= MAX_ATTACKS_PER_USER:
        return {
            "error": f"Max {MAX_ATTACKS_PER_USER} attaques par climax atteint",
            "attack_count": attacks_done,
        }

    # Phase 235.12 : GATING DE NIVEAU (crescendo) — le Climax (boss de fin de
    # chapitre) demande le niveau 10, comme le World Boss. On lit economy.level
    # (même DB). Fail-open : erreur → on laisse passer.
    try:
        async with _get_db() as _db:
            async with _db.execute(
                "SELECT level FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as _cur:
                _lr = await _cur.fetchone()
        _clvl = int((_lr[0] if _lr and _lr[0] else 1) or 1)
    except Exception:
        _clvl = 999
    # Phase 235.28 : niveau-pour-PARTICIPER RETIRÉ (directive owner — catch-22).
    # L'accès est géré par l'ACTIVITÉ (messages), pas par le niveau. Bloc gardé
    # désactivé (`if False`) pour préserver la structure sans rien casser.
    if False and _clvl < 10:
        return {
            "error": (f"🔒 Le **Climax** demande le **niveau 10** (tu es niveau **{_clvl}**). "
                      f"Farme les mobs, le boss du jour et fais `/daily` pour monter !"),
            "attack_count": attacks_done,
        }

    # Phase 235.25 : GATE D'ACTIVITÉ (s'ajoute au niveau 10). Climax = 🔴 (60 pts/7 j).
    try:
        import activity_system as _act
        _aok, _asc, _aneed = await _act.check_gate(guild_id, user_id, "climax")
        if not _aok:
            return {"error": _act.block_message("climax", _asc, _aneed),
                    "attack_count": attacks_done}
    except Exception:
        pass

    # Phase 235.25c : mémorise la participation (rappel rétention).
    try:
        import combat_recall as _cr
        await _cr.record(guild_id, user_id)
    except Exception:
        pass

    if damage <= 0:
        damage = random.randint(ATTACK_DAMAGE_MIN, ATTACK_DAMAGE_MAX)
    # Phase 235.10 : BOOST VOCAL — connecté à N'IMPORTE QUEL vocal → bonus de dégâts
    # aléatoire (+12-30 %, plafonné). Même règle que Boss Raid / World Boss / Boss du jour.
    voice_bonus = 0
    try:
        _g = _bot.get_guild(guild_id) if _bot is not None else None
        _m = _g.get_member(user_id) if _g is not None else None
        if _m and getattr(_m, "voice", None) and _m.voice.channel is not None:
            voice_bonus = int(damage * (random.uniform(1.25, 1.60) - 1.0))
            if voice_bonus > 0:
                damage += voice_bonus
    except Exception:
        voice_bonus = 0
    # Phase 269 : actions de combat (⚡ Charger / 📣 Crier) — multiplicateur SORTANT
    # additif (>= 1.0). FAIL-OPEN : une erreur → ×1.0. Scope du cri = event_id.
    try:
        import combat_actions as _ca
        _amult = _ca.consume_charge_mult(guild_id, user_id) * _ca.shout_mult(guild_id, event_id)
        if _amult != 1.0:
            damage = int(damage * _amult)
    except Exception:
        pass
    # A.3 — AVANTAGE ÉLÉMENTAIRE (Climax) : si l'arme équipée CONTRE l'élément du
    # boss (déduit de son nom), +25 % (borné par elemental_advantage : ×1.0..×1.25,
    # ne peut JAMAIS réduire les dégâts). Lecture autonome du weapon_json (même DB
    # que le gate). PUREMENT ADDITIF & FAIL-OPEN : la moindre erreur → aucun bonus.
    elem_bonus = 0
    try:
        import events_engine as _eng
        _bdef = get_climax_boss_by_id(active.get("boss_id"))
        _belem = _eng.element_for_boss(_bdef.get("name") if _bdef else None)
        if _belem:
            import json as _json
            _weapon = None
            async with _get_db() as _wdb:
                async with _wdb.execute(
                    "SELECT weapon_json FROM player_inventory "
                    "WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                ) as _wc:
                    _wr = await _wc.fetchone()
            if _wr and _wr[0]:
                _weapon = _json.loads(_wr[0])
            _adv = _eng.elemental_advantage(_weapon, _belem)
            if _adv > 1.0:
                _before = damage
                damage = int(damage * _adv)
                elem_bonus = max(0, damage - _before)
    except Exception:
        elem_bonus = 0  # FAIL-OPEN : combat normal
    # Capé pour ne pas overkill
    damage = min(damage, active["hp_current"])

    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO climax_attackers "
                "(event_id, user_id, damage_dealt, attack_count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(event_id, user_id) DO UPDATE SET "
                "damage_dealt = damage_dealt + ?, "
                "attack_count = attack_count + 1, "
                "last_attack_at = CURRENT_TIMESTAMP",
                (event_id, user_id, damage, damage),
            )
            await db.execute(
                "UPDATE climax_events SET "
                "hp_current = MAX(0, hp_current - ?), "
                "damage_total = damage_total + ? "
                "WHERE id=?",
                (damage, damage, event_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[record_attack] {ex}")
        return {"error": str(ex)}

    # Alimente Chronique (boss_damage)
    if _story is not None:
        try:
            await _story.on_boss_damage(guild_id, damage, user_id)
        except Exception:
            pass

    # Re-read
    updated = await get_active_climax(guild_id)
    if not updated:
        # Boss tombé exact pendant la requête → resolve
        await resolve_climax(event_id)
        return {
            "success": True,
            "damage": damage,
            "boss_dead": True,
            "attack_count": attacks_done + 1,
            "voice_bonus": voice_bonus,
            "elem_bonus": elem_bonus,
        }

    return {
        "success": True,
        "damage": damage,
        "hp_current": updated["hp_current"],
        "hp_max": updated["hp_max"],
        "damage_total": updated["damage_total"],
        "attack_count": attacks_done + 1,
        "max_attacks": MAX_ATTACKS_PER_USER,
        "boss_dead": updated["hp_current"] <= 0,
        "voice_bonus": voice_bonus,
        "elem_bonus": elem_bonus,
    }


async def record_pet_assist(guild_id: int, user_id: int) -> dict:
    """Phase 261 (4/4) : APPUI FAMILIER sur le Climax. Le familier actif (via le
    cœur partagé _pet_strike_fn injecté depuis bot.py) frappe le boss et SOIGNE le
    joueur si passif. NE consomme PAS le quota d'attaques (attack_count inchangé) :
    c'est un appui bonus, pas une attaque manuelle. Cooldown 90 s côté _pet_strike.
    FAIL-OPEN : une erreur ici ne casse jamais le combat."""
    if _get_db is None:
        return {"error": "DB indisponible"}
    if _pet_strike_fn is None:
        return {"error": "Familier indisponible un instant, réessaie."}
    active = await get_active_climax(guild_id)
    if not active:
        return {"error": "Aucun climax actif"}
    event_id = active["event_id"]
    if active["hp_current"] <= 0:
        return {"error": "Boss déjà tombé"}
    # Warm-up : le familier patiente aussi pendant le sas de préparation.
    _wu = _warmup_until.get(event_id, 0)
    if _wu and datetime.now(timezone.utc).timestamp() < _wu:
        return {
            "error": (f"⏳ **Le Climax se prépare !** Le combat commence <t:{int(_wu)}:R>.\n"
                      f"Ton familier piaffe d'impatience…"),
            "warmup": True,
        }

    # Cœur partagé : applique le cooldown 90 s, calcule la salve, soigne si passif.
    res = await _pet_strike_fn(guild_id, user_id)
    if not res.get("ok"):
        return {"error": res.get("msg", "🐾 Familier indisponible.")}
    dmg = int(res.get("dmg", 0) or 0)
    dmg = min(dmg, active["hp_current"])  # pas d'overkill (cohérent avec record_attack)

    try:
        async with _get_db() as db:
            # Crédite le classement SANS consommer le quota (attack_count inchangé).
            await db.execute(
                "INSERT INTO climax_attackers "
                "(event_id, user_id, damage_dealt, attack_count) "
                "VALUES (?, ?, ?, 0) "
                "ON CONFLICT(event_id, user_id) DO UPDATE SET "
                "damage_dealt = damage_dealt + ?, "
                "last_attack_at = CURRENT_TIMESTAMP",
                (event_id, user_id, dmg, dmg),
            )
            await db.execute(
                "UPDATE climax_events SET "
                "hp_current = MAX(0, hp_current - ?), "
                "damage_total = damage_total + ? "
                "WHERE id=?",
                (dmg, dmg, event_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[record_pet_assist] {ex}")
        return {"error": str(ex)}

    # Alimente la Chronique (boss_damage), comme une attaque normale.
    if _story is not None:
        try:
            await _story.on_boss_damage(guild_id, dmg, user_id)
        except Exception:
            pass

    updated = await get_active_climax(guild_id)
    if not updated:
        await resolve_climax(event_id)
        return {"success": True, "damage": dmg, "boss_dead": True,
                "label": res.get("label", "🐾 Familier"), "note": res.get("note", "")}
    return {"success": True, "damage": dmg, "hp_current": updated["hp_current"],
            "hp_max": updated["hp_max"], "boss_dead": updated["hp_current"] <= 0,
            "label": res.get("label", "🐾 Familier"), "note": res.get("note", "")}


# ═══════════════════════════════════════════════════════════════════════════
#  Resolve
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_climax(event_id: int) -> Optional[dict]:
    """Résout un climax : distribue coins + titre, log Codex."""
    if _get_db is None or _bot is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, chapter_id, boss_id, hp_current, hp_max, "
                "damage_total, status, channel_id, message_id "
                "FROM climax_events WHERE id=?",
                (event_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        (guild_id, chapter_id, boss_id, hp_current, hp_max, dmg_total,
         status, channel_id, _panel_msg_id) = row
        if status != "active":
            return None
    except Exception:
        return None

    boss = get_climax_boss_by_id(boss_id)
    if not boss:
        return None

    killed = hp_current <= 0
    final_status = "killed" if killed else "expired"

    # FIX audit 2026 : claim ATOMIQUE du statut final AVANT toute distribution
    # (coins + titres). Le garde `status != "active"` ci-dessus est une LECTURE
    # non-atomique : 2 appels concurrents (coup fatal + watchdog) peuvent tous deux
    # le franchir. Ici un seul gagne le claim `AND status='active'` ; l'autre
    # s'arrête → pas de double coins/titre. FAIL-OPEN ; l'UPDATE final reste un filet.
    try:
        async with _get_db() as db:
            _rc = await db.execute(
                "UPDATE climax_events SET status=?, ended_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='active'",
                (final_status, event_id),
            )
            await db.commit()
        if getattr(_rc, "rowcount", 0) != 1:
            return None
    except Exception:
        pass

    # Get attackers ranked
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, damage_dealt FROM climax_attackers "
                "WHERE event_id=? AND damage_dealt > 0 "
                "ORDER BY damage_dealt DESC",
                (event_id,),
            ) as cur:
                attackers = [(int(r[0]), int(r[1])) for r in await cur.fetchall()]
    except Exception:
        attackers = []

    # Distribute rewards
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

        # Titles
        title_given = None
        if killed:
            # Participation title for all
            if boss.get("participation_title"):
                await _grant_title(
                    guild_id, uid, boss["participation_title"],
                    chapter_id, boss_id,
                )
                title_given = boss["participation_title"]
            # Top 3 winning title
            if i < 3 and boss.get("winning_title"):
                await _grant_title(
                    guild_id, uid, boss["winning_title"],
                    chapter_id, boss_id,
                )
                title_given = boss["winning_title"]

        rewards.append({
            "user_id": uid,
            "damage": dmg,
            "coins": coins,
            "rank": i + 1,
            "title": title_given,
            "is_top3": i < 3,
        })

    # Update status
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE climax_events SET status=?, ended_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (final_status, event_id),
            )
            await db.commit()
    except Exception:
        pass

    # Log codex
    if _story is not None:
        try:
            await _story.log_chronicle_event(
                guild_id,
                "boss_defeated" if killed else "climax_expired",
                {
                    "chapter_id": chapter_id, "boss_id": boss_id,
                    "title": boss["name"], "killed": killed,
                    "damage_total": int(dmg_total),
                    "attackers": len(attackers),
                    "top3_count": min(3, len(attackers)),
                },
            )
        except Exception:
            pass

    guild = _bot.get_guild(guild_id)
    if guild:
        # Phase 213 : poster le récap dans l'arène dédiée (si elle existe encore),
        # sinon fallback _find_chronicle_channel via channel=None.
        close_ch = None
        try:
            if channel_id:
                close_ch = guild.get_channel(int(channel_id))
        except Exception:
            close_ch = None
        await _announce_climax_closed(
            guild, boss, killed, int(dmg_total), int(hp_max),
            rewards, chapter_id, channel=close_ch,
        )

        # Phase 235.15 : effacer le PANNEAU live du climax → le salon de combat
        # permanent se vide entre deux events (demande owner). Le récap reste dans
        # « 📜 chroniques-combat » (via _announce_climax_closed).
        if close_ch is not None and _panel_msg_id:
            try:
                _pm = await close_ch.fetch_message(int(_panel_msg_id))
                await _pm.delete()
            except Exception:
                pass

        # Phase 213 : supprimer l'arène dédiée (catégorie + texte + vocaux) après
        # le récap (grâce au délai interne du helper). Fire-and-forget ; le
        # balayage des orphelins rattrape si perdu. No-op si pas d'arène (channel_id=0).
        if _arena_delete_fn is not None and channel_id:
            try:
                asyncio.create_task(_arena_delete_fn(guild, int(channel_id)))
            except Exception as ex:
                print(f"[resolve_climax arena delete] {ex}")

    print(
        f"[monthly_climax] resolve event={event_id} killed={killed} "
        f"damage={dmg_total}/{hp_max} attackers={len(attackers)}"
    )
    return {
        "event_id": event_id,
        "killed": killed,
        "damage_total": int(dmg_total),
        "hp_max": int(hp_max),
        "attackers": len(attackers),
        "rewards": rewards,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  V2 panel
# ═══════════════════════════════════════════════════════════════════════════

def _hp_bar(current: int, maximum: int, width: int = 20) -> str:
    if maximum <= 0:
        return "░" * width
    pct = max(0, min(100, int((current * 100) / maximum)))
    fill = int(width * pct / 100)
    return "█" * fill + "░" * (width - fill)


async def build_climax_panel(
    guild_id: int, user_id: int,
) -> Optional[discord.ui.LayoutView]:
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    active = await get_active_climax(guild_id)
    if not active:
        items = [
            v2_title("⚔️ Boss Climax"),
            v2_body(
                "_Aucun boss n'est actif._\n\n"
                "Le prochain Boss Climax apparaîtra le **1er samedi du "
                "mois à 21h FR**. Il sera thématiquement lié au chapitre "
                "actif de la Chronique."
            ),
        ]

        # Affiche aussi les titres permanents du user
        titles = await get_user_titles(guild_id, user_id, limit=10)
        if titles:
            items.append(v2_divider())
            items.append(v2_body("**🏆 Tes titres permanents**"))
            for t in titles:
                items.append(v2_body(
                    f"🏅 **{t['title']}** _(chapitre {t['chapter_id']})_"
                ))

        class _NoClimax(LayoutView):
            def __init__(self):
                super().__init__(timeout=180)
                self.add_item(v2_container(*items, color=0x5D4037))

        return _NoClimax()

    boss = get_climax_boss_by_id(active["boss_id"]) or {}
    my_dmg = 0
    my_attacks = 0
    if _get_db is not None:
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT damage_dealt, attack_count FROM climax_attackers "
                    "WHERE event_id=? AND user_id=?",
                    (active["event_id"], user_id),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    my_dmg = int(row[0] or 0)
                    my_attacks = int(row[1] or 0)
        except Exception:
            pass

    pct = int(active["hp_current"] * 100 / max(1, active["hp_max"]))
    # A.3 — FAIBLESSE ÉLÉMENTAIRE affichée (déduite du nom du boss). Frapper avec
    # une arme de cet élément donne +25 % (appliqué dans record_attack). FAIL-SAFE :
    # pas de faiblesse lisible → aucune ligne (combat normal).
    _weak_block = []
    try:
        import events_engine as _eng
        _wl = _eng.boss_weakness_label(boss.get("name"))
        if _wl:
            _weak_block = [v2_body(
                f"🎯 **Faiblesse** : {_wl} — une arme de cet élément inflige **+25 %** !")]
    except Exception:
        _weak_block = []
    items = [
        v2_title(f"⚔️ Boss Climax — {boss.get('emoji', '?')} {boss.get('name', '?')}"),
        v2_subtitle(
            f"Chapitre {active['chapter_id']} · boss thématique du mois"
        ),
        v2_divider(),
        v2_body(f"_{boss.get('description', '…')}_"),
        v2_divider(),
        v2_body(
            f"**❤️ HP**\n"
            f"`{_hp_bar(active['hp_current'], active['hp_max'])}`\n"
            f"`{active['hp_current']:,} / {active['hp_max']:,}` ({pct}%)"
        ),
        *_weak_block,
        v2_body(
            f"**⚔️ Ma contribution**\n"
            f"Dégâts : `{my_dmg:,}` · Attaques : `{my_attacks}/{MAX_ATTACKS_PER_USER}`"
        ),
        v2_divider(),
        v2_body(
            f"_⏱️ Fin : `{active['ends_at']}`_\n"
            f"_Récompense top 3 : titre permanent **{boss.get('winning_title', '?')}**_\n"
            f"_Participation : **{boss.get('participation_title', '?')}**_"
        ),
    ]

    if my_attacks >= MAX_ATTACKS_PER_USER:
        items.append(v2_body(
            "_✅ Tu as donné le maximum. Reviens à la prochaine lune._"
        ))

    class _ClimaxLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0xD32F2F))

    layout = _ClimaxLayout()
    # Phase 208 FIX : boutons dans un ActionRow (type 1). Un Button/DynamicItem
    # brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body". On crée des
    # Buttons BRUTS avec les MÊMES label/style/custom_id que les DynamicItems
    # enregistrés ; le clic reste capté par le DynamicItem (persistance).
    _row_btns = []
    if my_attacks < MAX_ATTACKS_PER_USER and active["hp_current"] > 0:
        atk_btn = Button(
            label="⚔️ Attaquer",
            style=discord.ButtonStyle.danger,
            custom_id=f"climax_atk:{active['event_id']}:{user_id}",
        )
        _row_btns.append(atk_btn)
    # Phase 261 (4/4) : APPUI FAMILIER — disponible tant que le boss vit, MÊME si le
    # quota d'attaques manuelles est épuisé (l'appui familier ne consomme pas le quota).
    if active["hp_current"] > 0:
        pet_btn = Button(
            label="🐾 Familier",
            style=discord.ButtonStyle.success,
            custom_id=f"climax_pet:{active['event_id']}:{user_id}",
        )
        _row_btns.append(pet_btn)
        # Phase 269 : ⚡ Charger / 📣 Crier (captés par combat_actions). Scope = event_id
        # SEUL (le template cba_* n'a qu'un groupe → pas de user_id dans le custom_id).
        _row_btns.append(Button(label="⚡ Charger", style=discord.ButtonStyle.primary,
                                custom_id=f"cba_charge:{active['event_id']}"))
        _row_btns.append(Button(label="📣 Crier", style=discord.ButtonStyle.secondary,
                                custom_id=f"cba_shout:{active['event_id']}"))
    if _row_btns:
        layout.add_item(discord.ui.ActionRow(*_row_btns))

    return layout


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent button
# ═══════════════════════════════════════════════════════════════════════════

class ClimaxAttackButton(
    discord.ui.DynamicItem[Button],
    template=r"climax_atk:(?P<event_id>\d+):(?P<user_id>\d+)",
):
    """Bouton d'attaque (persistent)."""

    def __init__(self, event_id: int, user_id: int):
        super().__init__(
            Button(
                label="⚔️ Attaquer",
                style=discord.ButtonStyle.danger,
                custom_id=f"climax_atk:{event_id}:{user_id}",
            )
        )
        self.event_id = event_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["event_id"]), int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Boss depuis le Codex.",
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
            active = await get_active_climax(btn_i.guild.id)
            if not active or active["event_id"] != self.event_id:
                await btn_i.followup.send(
                    "❌ Boss inactif ou différent.", ephemeral=True
                )
                return

            result = await record_attack(btn_i.guild.id, btn_i.user.id)
            if result.get("error"):
                await btn_i.followup.send(
                    f"❌ {result['error']}", ephemeral=True
                )
                return

            view = await build_climax_panel(btn_i.guild.id, btn_i.user.id)
            _vb = int(result.get("voice_bonus", 0) or 0)
            _vn = (f" · 🔊 **Boost vocal** +`{_vb}`" if _vb > 0 else "")
            # A.3 : avantage élémentaire (arme contre l'élément du boss).
            _eb = int(result.get("elem_bonus", 0) or 0)
            _en = (f" · 🎯 **Avantage élémentaire** +`{_eb}`" if _eb > 0 else "")
            msg = (
                f"⚔️ **{result['damage']} dégâts** infligés !{_vn}{_en}\n"
                f"_Attaques : `{result['attack_count']}/{result.get('max_attacks', MAX_ATTACKS_PER_USER)}`._"
            )
            if result.get("boss_dead"):
                msg += "\n\n💀 **Le boss est tombé !** Les récompenses seront distribuées."

            if view:
                try:
                    await btn_i.edit_original_response(
                        view=view, content=None, attachments=[],
                    )
                except Exception:
                    pass
            try:
                await btn_i.followup.send(msg, ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[climax_attack callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


class ClimaxPetButton(
    discord.ui.DynamicItem[Button],
    template=r"climax_pet:(?P<event_id>\d+):(?P<user_id>\d+)",
):
    """Phase 261 (4/4) : bouton APPUI FAMILIER (persistent) du Climax. Le familier
    actif frappe le boss et soigne le joueur si passif — sans consommer le quota."""

    def __init__(self, event_id: int, user_id: int):
        super().__init__(
            Button(
                label="🐾 Familier",
                style=discord.ButtonStyle.success,
                custom_id=f"climax_pet:{event_id}:{user_id}",
            )
        )
        self.event_id = event_id
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["event_id"]), int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Boss depuis le Codex.",
                    ephemeral=True,
                )
            except Exception:
                return

        # ACK D'ABORD — acquitter le clic avant tout (anti « Échec de l'interaction »).
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

        # Anti-429 : un clic noyé (< _PET_CLICK_CD s) ne coûte AUCUN followup.
        try:
            _k = (btn_i.guild.id, btn_i.user.id)
            _now = datetime.now(timezone.utc).timestamp()
            if _now - _last_pet_click.get(_k, 0.0) < _PET_CLICK_CD:
                return
            _last_pet_click[_k] = _now
        except Exception:
            pass

        try:
            active = await get_active_climax(btn_i.guild.id)
            if not active or active["event_id"] != self.event_id:
                await btn_i.followup.send(
                    "❌ Boss inactif ou différent.", ephemeral=True
                )
                return

            result = await record_pet_assist(btn_i.guild.id, btn_i.user.id)
            if result.get("error"):
                await btn_i.followup.send(f"🐾 {result['error']}", ephemeral=True)
                return

            view = await build_climax_panel(btn_i.guild.id, btn_i.user.id)
            label = result.get("label", "🐾 Familier")
            note = result.get("note", "")
            _extra = f"\n{note}" if note else ""
            msg = f"🐾 **{label}** frappe le boss — `{result['damage']}` dégâts !{_extra}"
            if result.get("boss_dead"):
                msg += "\n\n💀 **Le boss est tombé !** Les récompenses seront distribuées."

            if view:
                try:
                    await btn_i.edit_original_response(
                        view=view, content=None, attachments=[],
                    )
                except Exception:
                    pass
            try:
                await btn_i.followup.send(msg, ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[climax_pet callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(ClimaxAttackButton)
    except Exception as ex:
        print(f"[monthly_climax register_persistent_views] {ex}")
    try:
        bot_instance.add_dynamic_items(ClimaxPetButton)
    except Exception as ex:
        print(f"[monthly_climax register_persistent_views pet] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Announces
# ═══════════════════════════════════════════════════════════════════════════

async def _find_chronicle_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    if _db_get is None:
        return None
    try:
        cfg = await _db_get(guild.id)
        for key in ("chronicle_channel_id", "combat_arena_channel_id", "hub_channel"):
            ch_id = int(cfg.get(key, 0) or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch:
                    return ch
    except Exception:
        pass
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["chronique", "arène", "combat", "boss", "lore", "saga"]):
            return ch
    return None


async def _announce_climax_open(
    guild: discord.Guild, boss: dict, event_id: int, ends_at: datetime,
    channel: Optional[discord.TextChannel] = None,
    warmup_ts: Optional[float] = None,
) -> None:
    # Phase 213 : `channel` = arène dédiée créée au spawn (préférée). Fallback sur
    # _find_chronicle_channel si l'arène n'a pas pu être créée (fail-open).
    ch = channel or await _find_chronicle_channel(guild)
    if not ch:
        return
    msg = (
        f"⚔️ **Boss Climax du mois**\n\n"
        f"{boss['emoji']} **{boss['name']}**\n"
        f"_{boss['description']}_\n\n"
        f"❤️ HP : `{boss['hp_base']:,}` · ⏱️ {CLIMAX_DURATION_HOURS}h · "
        f"⚔️ max {MAX_ATTACKS_PER_USER} attaques/membre\n\n"
        f"**Récompenses :**\n"
        f"🏅 Top 3 : titre permanent **« {boss.get('winning_title', '?')} »** + "
        f"`{TOP3_BONUS_COINS}` 🪙 bonus\n"
        f"🎖️ Participation : titre **« {boss.get('participation_title', '?')} »** + "
        f"`{PARTICIPATION_BONUS_COINS}` 🪙\n\n"
        f"_« {boss.get('lore', '')} »_"
    )
    if warmup_ts:
        msg += (f"\n\n⏰ **Le combat commence <t:{int(warmup_ts)}:R>** — "
                f"équipez-vous et **rejoignez un vocal** : 🔊 **+25-60 % de dégâts** !")
    try:
        _t, _, _b = msg.partition("\n\n")
        await ch.send(
            view=ui_v2.recap_view(_t.replace("**", ""), _b or msg,
                                  color=ui_v2.Palette.DANGER),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


async def _announce_climax_closed(
    guild: discord.Guild, boss: dict, killed: bool,
    damage_total: int, hp_max: int, rewards: list[dict],
    chapter_id: str, channel: Optional[discord.TextChannel] = None,
) -> None:
    # Phase 213 : `channel` = arène dédiée (récap dedans avant suppression).
    # Fallback _find_chronicle_channel si l'arène n'existe pas/plus (fail-open).
    ch = channel or await _find_chronicle_channel(guild)
    if not ch:
        return

    # Phase 235.33 : récap de FIN d'event en format UNIQUE, compact et BORNÉ via
    # ui_v2.combat_recap_view (même taille pour TOUS les events). On ne touche QUE
    # l'affichage : tout le monde reste récompensé (la ligne « +N autres » le rappelle).
    # `rewards` est déjà trié par rang (rank = i+1, dérivé des dégâts décroissants).
    podium: list[tuple[str, int]] = []
    for r in rewards[:3]:
        member = guild.get_member(r["user_id"])
        nm = member.display_name if member else f"User {r['user_id']}"
        podium.append((nm, int(r.get("coins", 0))))
    others_count = max(0, len(rewards) - 3)
    participants = len(rewards)
    outcome = "win" if killed else "fail"

    # Texte compact pour le journal persistant « 📜 chroniques-combat » (même bornage).
    _head_clean = (
        f"{'💀 BOSS VAINCU' if killed else '⏳ BOSS NON VAINCU'} — "
        f"{boss['emoji']} {boss['name']}"
    )
    _medals = ["🥇", "🥈", "🥉"]
    _body_lines = [
        ("✅ Vaincu" if killed else "⏳ Non vaincu")
        + f" · {participants} combattant" + ("s" if participants != 1 else "")
        + f" · `{int(damage_total):,}` dégâts"
    ]
    for _i, (nm, coins) in enumerate(podium):
        _body_lines.append(f"{_medals[_i]} **{nm}** · `{coins:,}` 🪙")
    if others_count:
        _body_lines.append(f"🔸 _+{others_count} autres récompensés_")
    body = "\n".join(_body_lines)

    # Phase 235.15 : récap consolidé PERSISTANT → « 📜 chroniques-combat » (journal
    # commun à TOUS les events) = la source unique du récap.
    if _report_fn is not None:
        try:
            await _report_fn(guild, _head_clean, body)
        except Exception:
            pass
    # Bref écho dans l'arène (closure pour les combattants), AUTO-supprimé pour ne
    # pas encombrer le salon de combat permanent.
    try:
        await ch.send(
            view=ui_v2.combat_recap_view(
                boss.get("emoji", "⚔️"), boss.get("name", "Boss Climax"),
                outcome, podium,
                others_count=others_count,
                participants=participants,
                total_damage=int(damage_total),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
            delete_after=3 * 3600,
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=15)
async def climax_task():
    """Toutes les 15 min : check trigger / resolve."""
    if _bot is None or _get_db is None:
        return
    try:
        # Trigger 1er samedi 21h FR
        if _is_climax_window():
            for guild in _bot.guilds:
                try:
                    await trigger_climax(guild.id)
                except Exception as ex:
                    print(f"[climax_task trigger g={guild.id}] {ex}")

        # Resolve expirés
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with _get_db() as db:
                async with db.execute(
                    "SELECT id FROM climax_events "
                    "WHERE status='active' AND (ends_at < ? OR hp_current <= 0)",
                    (now_iso,),
                ) as cur:
                    to_resolve = [int(r[0]) for r in await cur.fetchall()]
            for eid in to_resolve:
                try:
                    await resolve_climax(eid)
                except Exception as ex:
                    print(f"[climax_task resolve event={eid}] {ex}")
        except Exception as ex:
            print(f"[climax_task resolve scan] {ex}")
    except Exception as ex:
        print(f"[climax_task] {ex}")


@climax_task.before_loop
async def _climax_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point depuis Codex
# ═══════════════════════════════════════════════════════════════════════════

async def open_climax_from_codex(interaction: discord.Interaction) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_climax_from_codex defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        view = await build_climax_panel(interaction.guild.id, interaction.user.id)
        if view is None:
            await interaction.followup.send(
                "❌ Boss indisponible.", ephemeral=True
            )
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_climax_from_codex] {ex}")
        try:
            await interaction.followup.send(
                f"❌ Erreur : `{ex}`", ephemeral=True,
            )
        except Exception:
            pass


__all__ = [
    "CLIMAX_BOSSES",
    "CLIMAX_WEEKDAY",
    "CLIMAX_HOUR",
    "CLIMAX_DURATION_HOURS",
    "COIN_PER_DAMAGE",
    "TOP3_BONUS_COINS",
    "PARTICIPATION_BONUS_COINS",
    "MAX_ATTACKS_PER_USER",
    "ATTACK_DAMAGE_MIN",
    "ATTACK_DAMAGE_MAX",
    "setup",
    "init_db",
    "get_climax_boss_for_chapter",
    "get_climax_boss_by_id",
    "list_climax_ids",
    "get_active_climax",
    "get_user_attack_count",
    "get_user_titles",
    "trigger_climax",
    "record_attack",
    "resolve_climax",
    "build_climax_panel",
    "open_climax_from_codex",
    "ClimaxAttackButton",
    "climax_task",
    "register_persistent_views",
]
