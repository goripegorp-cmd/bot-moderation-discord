"""
weekly_council.py — Conseil des Anciens hebdomadaire (Phase 170.4).

🎯 OBJECTIF : 1 vote collectif par semaine où le serveur entier choisit
une voie narrative. Le résultat est appliqué et affecte :
- L'humeur des NPCs alignés (option A plaît à Aria, option B à Drazek…)
- Les branches narratives dans chronicle_state (changement de chapitre 2.x)
- La progression du chapitre 3.2 (kind: council_votes)
- Un log dans le Codex (mémoire collective)

PHILOSOPHIE :
- Pas de "bon" choix : chaque option a ses conséquences distinctes.
- 1 vote par utilisateur par session (immuable).
- Le vainqueur est l'option avec le plus de voix ; égalité → option avec
  l'id le plus petit (déterministe, pas de doublon).
- Sessions ouvertes lundi 20h FR, closes mercredi 23h59 FR.
- Si pas de vote = pas de blocage narratif (le serveur "abstient").

PLANNING HEBDOMADAIRE :
- Lundi 20h FR : open council (si current chapitre a un council disponible)
- Mercredi 23h59 FR : close council, count votes, apply result
- Annonce dans le salon Chronique

API publique :
- setup(bot, get_db, db_get, v2, story_module, npc_module)
- init_db()
- COUNCIL_CATALOG, get_council_def(council_id)
- get_active_council(guild_id) → dict | None
- record_vote(guild_id, session_id, user_id, option_idx)
- build_council_panel(guild_id, user_id) → LayoutView
- council_task (loop hourly, opens/closes)
- CouncilVoteButton (DynamicItem)
- register_persistent_views(bot)
- open_council_from_codex(interaction)

DB :
- council_sessions (id PK, guild_id, council_id, chapter_id_at_open,
                    opens_at, closes_at, result_option_idx, status,
                    total_votes, message_id, channel_id)
- council_votes (session_id, user_id, option_idx, voted_at)
                 PRIMARY KEY (session_id, user_id)
"""
from __future__ import annotations

import json
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

# Cooldowns / timing
COUNCIL_OPEN_WEEKDAY = 0   # lundi = 0
COUNCIL_OPEN_HOUR = 20     # 20h FR
COUNCIL_CLOSE_WEEKDAY = 2  # mercredi = 2
COUNCIL_CLOSE_HOUR = 23    # 23h59 FR


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE — Questions hebdomadaires
# ═══════════════════════════════════════════════════════════════════════════
# Structure d'un conseil :
# - id : identifiant unique
# - chapter_id : si lié à un chapitre spécifique (ou "any" pour générique)
# - title : titre du conseil
# - context : contexte narratif (2-3 phrases)
# - question : la question posée
# - options : liste de 3 options
#   - id : "A", "B", "C"
#   - label : libellé court (button)
#   - description : description longue (panel)
#   - branch_key : clé d'embranchement narratif (stocké dans chronicle_state)
#   - npc_impacts : dict {npc_id: mood_delta} appliqué à TOUS les votants
#                   pour cette option (ex: +10 à Aria, -5 à Drazek)

COUNCIL_CATALOG = [
    # ─── Conseil clé : choix de fin d'Acte 1 ───
    {
        "id": "council_1.3_main",
        "chapter_id": "1.3",
        "title": "Le Premier Choix",
        "context": (
            "Les Profondes révèlent leur secret : un sceau ancien se brise. "
            "Une entité enchaînée depuis des siècles tente de se libérer. "
            "Le Conseil des Anciens convoque le serveur. Trois voies s'offrent."
        ),
        "question": "Que doit faire le serveur face à l'entité ?",
        "options": [
            {
                "id": "A",
                "label": "🔒 Sceller (sécurité)",
                "description": (
                    "Renforcer le sceau ancien. L'entité reste prisonnière, "
                    "mais ses secrets aussi. Voie prudente, défendue par Aria."
                ),
                "branch_key": "act2_seal",
                "npc_impacts": {
                    "aria": 15, "korr": 5, "lyra": -10,
                    "drazek": 0, "sienna": 0, "voyageur": 5,
                },
            },
            {
                "id": "B",
                "label": "📚 Étudier (savoir)",
                "description": (
                    "Approcher l'entité sans la libérer, apprendre ses "
                    "secrets. Voie risquée mais ambitieuse, défendue par Lyra."
                ),
                "branch_key": "act2_study",
                "npc_impacts": {
                    "aria": -5, "korr": -5, "lyra": 18,
                    "drazek": -10, "sienna": 5, "voyageur": 10,
                },
            },
            {
                "id": "C",
                "label": "⚔️ Détruire (purification)",
                "description": (
                    "Briser le sceau et combattre l'entité directement. Voie "
                    "violente mais définitive, défendue par Drazek."
                ),
                "branch_key": "act2_destroy",
                "npc_impacts": {
                    "aria": -10, "korr": 10, "lyra": -15,
                    "drazek": 18, "sienna": -5, "voyageur": -5,
                },
            },
        ],
    },

    # ─── Conseil clé : fin Acte 2 ───
    {
        "id": "council_2.3_main",
        "chapter_id": "2.3",
        "title": "Le Second Choix",
        "context": (
            "Le Sanctuaire s'ouvre. Mais l'entrée demande un sacrifice "
            "symbolique du serveur. Le Conseil tranche."
        ),
        "question": "Que sacrifie le serveur pour entrer au Sanctuaire ?",
        "options": [
            {
                "id": "A",
                "label": "💰 Une part du trésor commun",
                "description": (
                    "Le serveur offre 30% du trésor accumulé. Voie matérielle, "
                    "mais préserve la vie."
                ),
                "branch_key": "act3_tribute_gold",
                "npc_impacts": {
                    "sienna": -10, "korr": 5, "drazek": 0,
                    "aria": 10, "lyra": 0, "voyageur": 5,
                },
            },
            {
                "id": "B",
                "label": "📜 Un fragment de mémoire collective",
                "description": (
                    "Le serveur oublie volontairement un événement passé. "
                    "Voie symbolique, irréversible."
                ),
                "branch_key": "act3_tribute_memory",
                "npc_impacts": {
                    "lyra": -10, "aria": 15, "voyageur": 12,
                    "korr": -5, "drazek": -5, "sienna": 5,
                },
            },
            {
                "id": "C",
                "label": "⚔️ Une bataille pour prouver sa valeur",
                "description": (
                    "Le serveur affronte un boss d'épreuve. Voie active, "
                    "mais risquée (boss difficile)."
                ),
                "branch_key": "act3_tribute_battle",
                "npc_impacts": {
                    "drazek": 18, "korr": 10, "aria": -5,
                    "lyra": -5, "sienna": -5, "voyageur": 0,
                },
            },
        ],
    },

    # ─── Conseil générique : qui contacter ? ───
    {
        "id": "council_generic_npc_focus",
        "chapter_id": "any",
        "title": "Le Conseil des Voix",
        "context": (
            "Le Conseil des Anciens convoque le serveur pour décider quel "
            "NPC accompagnera la quête de cette semaine. Le choix donnera "
            "une voix prépondérante à cette personne dans les jours suivants."
        ),
        "question": "Qui doit guider le serveur cette semaine ?",
        "options": [
            {
                "id": "A",
                "label": "🌙 Aria la Veilleuse",
                "description": (
                    "Aria propose une approche prudente, méthodique. "
                    "Les daily encounters seront orientées vers la sagesse."
                ),
                "branch_key": "weekly_lead_aria",
                "npc_impacts": {
                    "aria": 15, "korr": -2, "lyra": -2,
                    "drazek": -5, "sienna": 0, "voyageur": 2,
                },
            },
            {
                "id": "B",
                "label": "🔨 Korr le Forgeron",
                "description": (
                    "Korr veut de l'action concrète. La semaine sera "
                    "orientée vers le combat et l'artisanat."
                ),
                "branch_key": "weekly_lead_korr",
                "npc_impacts": {
                    "aria": -2, "korr": 15, "lyra": -5,
                    "drazek": 8, "sienna": 0, "voyageur": -2,
                },
            },
            {
                "id": "C",
                "label": "📚 Lyra l'Érudite",
                "description": (
                    "Lyra promet des révélations interdites. La semaine "
                    "sera orientée vers le savoir et les mystères."
                ),
                "branch_key": "weekly_lead_lyra",
                "npc_impacts": {
                    "aria": -5, "korr": -5, "lyra": 15,
                    "drazek": -5, "sienna": 5, "voyageur": 8,
                },
            },
        ],
    },

    # ─── Conseil générique : priorité de la semaine ───
    {
        "id": "council_generic_priority",
        "chapter_id": "any",
        "title": "La Priorité de la Semaine",
        "context": (
            "Le serveur a des ressources limitées. Le Conseil tranche sur "
            "où concentrer les efforts cette semaine."
        ),
        "question": "Quelle priorité pour les 7 prochains jours ?",
        "options": [
            {
                "id": "A",
                "label": "⚔️ Combats & Conquêtes",
                "description": (
                    "Boost ×1.2 sur les drops de mob_hunts cette semaine. "
                    "Les boss apparaissent plus souvent."
                ),
                "branch_key": "weekly_focus_combat",
                "npc_impacts": {
                    "drazek": 12, "korr": 8, "aria": -3,
                    "lyra": -5, "sienna": 5, "voyageur": 0,
                },
            },
            {
                "id": "B",
                "label": "📚 Savoir & Mystères",
                "description": (
                    "Plus d'indices distribués lors des encounters. Lyra "
                    "ouvre la Bibliothèque interdite."
                ),
                "branch_key": "weekly_focus_lore",
                "npc_impacts": {
                    "lyra": 12, "aria": 8, "voyageur": 10,
                    "korr": -3, "drazek": -5, "sienna": 0,
                },
            },
            {
                "id": "C",
                "label": "💰 Économie & Commerce",
                "description": (
                    "Sienna propose des items rares à prix réduit. Daily "
                    "quests rapportent +30% coins."
                ),
                "branch_key": "weekly_focus_economy",
                "npc_impacts": {
                    "sienna": 15, "korr": 5, "aria": 0,
                    "lyra": 0, "drazek": -5, "voyageur": 0,
                },
            },
        ],
    },

    # ─── Conseil générique : doctrine ───
    {
        "id": "council_generic_doctrine",
        "chapter_id": "any",
        "title": "La Doctrine du Serveur",
        "context": (
            "Le Voyageur convoque un débat philosophique au Conseil. La "
            "réponse collective définira une partie de l'identité du serveur."
        ),
        "question": "Quelle doctrine guide le serveur ?",
        "options": [
            {
                "id": "A",
                "label": "🛡️ Prudence avant tout",
                "description": (
                    "Le serveur privilégie les actions sûres. Bonus défense "
                    "passive +10% pour la semaine."
                ),
                "branch_key": "doctrine_prudence",
                "npc_impacts": {
                    "aria": 15, "korr": 5, "lyra": 0,
                    "drazek": -10, "sienna": 5, "voyageur": 5,
                },
            },
            {
                "id": "B",
                "label": "⚔️ Action décisive",
                "description": (
                    "Le serveur agit sans hésiter. Bonus offensive +10% "
                    "mais malus défense -5%."
                ),
                "branch_key": "doctrine_action",
                "npc_impacts": {
                    "drazek": 15, "korr": 8, "aria": -10,
                    "lyra": -5, "sienna": 0, "voyageur": -5,
                },
            },
            {
                "id": "C",
                "label": "🔮 Adaptabilité",
                "description": (
                    "Le serveur s'adapte selon les circonstances. Pas de "
                    "bonus fixe, mais flexibilité accrue."
                ),
                "branch_key": "doctrine_adapt",
                "npc_impacts": {
                    "voyageur": 18, "lyra": 10, "sienna": 5,
                    "aria": -2, "korr": -5, "drazek": -5,
                },
            },
        ],
    },
]


def get_council_def(council_id: str) -> Optional[dict]:
    for c in COUNCIL_CATALOG:
        if c["id"] == council_id:
            return c
    return None


def list_council_ids() -> list[str]:
    return [c["id"] for c in COUNCIL_CATALOG]


def get_councils_for_chapter(chapter_id: str) -> list[dict]:
    """Retourne les conseils éligibles pour un chapitre donné."""
    return [
        c for c in COUNCIL_CATALOG
        if c["chapter_id"] == chapter_id or c["chapter_id"] == "any"
    ]


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
                CREATE TABLE IF NOT EXISTS council_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    council_id TEXT NOT NULL,
                    chapter_id_at_open TEXT,
                    opens_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closes_at TIMESTAMP NOT NULL,
                    result_option_idx INTEGER,
                    status TEXT DEFAULT 'open',
                    total_votes INTEGER DEFAULT 0,
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS council_votes (
                    session_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    option_idx INTEGER NOT NULL,
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_council_active "
                "ON council_sessions(guild_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_council_votes_session "
                "ON council_votes(session_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[weekly_council init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Time helpers
# ═══════════════════════════════════════════════════════════════════════════

def _paris_now() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _is_open_window() -> bool:
    """True si on est dans la fenêtre d'ouverture (lundi 20h FR)."""
    now = _paris_now()
    return now.weekday() == COUNCIL_OPEN_WEEKDAY and now.hour == COUNCIL_OPEN_HOUR


def _is_close_window() -> bool:
    """True si on est mercredi 23h FR (fenêtre de fermeture)."""
    now = _paris_now()
    return now.weekday() == COUNCIL_CLOSE_WEEKDAY and now.hour == COUNCIL_CLOSE_HOUR


def _next_wednesday_2359() -> datetime:
    """Calcule la date de fermeture (mercredi 23h59 FR à partir de maintenant)."""
    now = _paris_now()
    days_until_wed = (COUNCIL_CLOSE_WEEKDAY - now.weekday()) % 7
    if days_until_wed == 0:
        days_until_wed = 7  # déjà mercredi → semaine suivante
    closing = (now + timedelta(days=days_until_wed)).replace(
        hour=23, minute=59, second=0, microsecond=0,
    )
    return closing


# ═══════════════════════════════════════════════════════════════════════════
#  Active council
# ═══════════════════════════════════════════════════════════════════════════

async def get_active_council(guild_id: int) -> Optional[dict]:
    """Retourne la session council active pour cette guild, ou None."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, council_id, chapter_id_at_open, opens_at, "
                "closes_at, total_votes, message_id, channel_id "
                "FROM council_sessions "
                "WHERE guild_id=? AND status='open' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "session_id": int(row[0]),
            "council_id": row[1],
            "chapter_at_open": row[2],
            "opens_at": row[3],
            "closes_at": row[4],
            "total_votes": int(row[5] or 0),
            "message_id": int(row[6] or 0),
            "channel_id": int(row[7] or 0),
        }
    except Exception as ex:
        print(f"[get_active_council] {ex}")
        return None


async def get_vote_counts(session_id: int) -> dict[int, int]:
    """Retourne {option_idx: count_votes}."""
    if _get_db is None:
        return {}
    try:
        out = {}
        async with _get_db() as db:
            async with db.execute(
                "SELECT option_idx, COUNT(*) FROM council_votes "
                "WHERE session_id=? GROUP BY option_idx",
                (session_id,),
            ) as cur:
                for r in await cur.fetchall():
                    out[int(r[0])] = int(r[1])
        return out
    except Exception:
        return {}


async def has_user_voted(session_id: int, user_id: int) -> Optional[int]:
    """Retourne l'option_idx déjà voté par ce user, ou None."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT option_idx FROM council_votes "
                "WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Open council
# ═══════════════════════════════════════════════════════════════════════════

async def _pick_council_for_guild(guild_id: int) -> Optional[dict]:
    """Sélectionne le conseil à ouvrir pour cette guild.

    Logique :
    1. Si chapitre actif a un conseil clé non encore tenu → ce conseil
    2. Sinon, conseil générique non tenu depuis ≥ 30 jours
    3. Sinon, conseil générique random
    """
    if _story is None:
        return None
    state = await _story.get_state(guild_id)
    if not state:
        return None

    chapter_id = state["chapter_id"]

    # Récupère les conseils déjà tenus pour cette guild
    already_done: set[str] = set()
    if _get_db is not None:
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT DISTINCT council_id FROM council_sessions "
                    "WHERE guild_id=? AND status IN ('closed', 'resolved')",
                    (guild_id,),
                ) as cur:
                    for r in await cur.fetchall():
                        already_done.add(r[0])
        except Exception:
            pass

    # 1. Conseil clé du chapitre
    for c in COUNCIL_CATALOG:
        if c["chapter_id"] == chapter_id and c["id"] not in already_done:
            return c

    # 2. Conseil générique non encore tenu
    for c in COUNCIL_CATALOG:
        if c["chapter_id"] == "any" and c["id"] not in already_done:
            return c

    # 3. Réutilise un générique (rotation)
    import random as _r
    generic_pool = [c for c in COUNCIL_CATALOG if c["chapter_id"] == "any"]
    if generic_pool:
        return _r.choice(generic_pool)
    return None


async def open_council(guild_id: int) -> Optional[int]:
    """Ouvre un nouveau conseil pour cette guild si :
    - Aucun conseil n'est déjà actif
    - Un conseil approprié peut être sélectionné

    Retourne le session_id ou None.
    """
    if _get_db is None or _bot is None:
        return None
    # Anti-doublon : si conseil actif → skip
    existing = await get_active_council(guild_id)
    if existing:
        return None

    council = await _pick_council_for_guild(guild_id)
    if not council:
        return None

    state = await _story.get_state(guild_id) if _story else {}
    chapter_id = (state or {}).get("chapter_id", "—")

    closing = _next_wednesday_2359()

    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO council_sessions "
                "(guild_id, council_id, chapter_id_at_open, closes_at) "
                "VALUES (?, ?, ?, ?)",
                (guild_id, council["id"], chapter_id, closing.isoformat()),
            )
            session_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[open_council INSERT] {ex}")
        return None

    # Announce
    guild = _bot.get_guild(guild_id)
    if guild:
        await _announce_council_open(guild, council, session_id, closing)

    # Log dans Codex
    if _story is not None:
        try:
            await _story.log_chronicle_event(guild_id, "council_opened", {
                "council_id": council["id"],
                "title": council["title"],
                "chapter_at_open": chapter_id,
            })
        except Exception:
            pass

    print(
        f"[weekly_council] open guild={guild_id} council={council['id']} "
        f"session={session_id}"
    )
    return session_id


# ═══════════════════════════════════════════════════════════════════════════
#  Close council & apply result
# ═══════════════════════════════════════════════════════════════════════════

async def close_council(session_id: int) -> Optional[dict]:
    """Close une session, compte les votes, applique le résultat."""
    if _get_db is None or _bot is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, council_id, status FROM council_sessions "
                "WHERE id=?",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        guild_id, council_id, status = row
        if status != "open":
            return None
    except Exception:
        return None

    council = get_council_def(council_id)
    if not council:
        return None

    counts = await get_vote_counts(session_id)
    total = sum(counts.values())

    # Détermine option gagnante (max votes ; égalité → id le plus petit)
    if total == 0:
        winner_idx = 0  # Default
        winner_label = "(abstention)"
    else:
        sorted_opts = sorted(
            counts.items(),
            key=lambda x: (-x[1], x[0]),
        )
        winner_idx = sorted_opts[0][0]
        winner_label = council["options"][winner_idx]["label"]

    winner_option = council["options"][winner_idx]

    # Update session
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE council_sessions SET status='resolved', "
                "result_option_idx=?, total_votes=? WHERE id=?",
                (winner_idx, total, session_id),
            )
            await db.commit()
    except Exception:
        pass

    # Applique impacts NPC mood à chaque votant pour l'option gagnante
    if _npc is not None and _get_db is not None:
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT user_id FROM council_votes "
                    "WHERE session_id=? AND option_idx=?",
                    (session_id, winner_idx),
                ) as cur:
                    voters = [int(r[0]) for r in await cur.fetchall()]
            for uid in voters:
                for npc_id, delta in winner_option.get("npc_impacts", {}).items():
                    try:
                        await _npc.change_mood(guild_id, uid, npc_id, int(delta))
                    except Exception:
                        pass
        except Exception as ex:
            print(f"[close_council apply NPC] {ex}")

    # Branche narrative dans chronicle_state
    if _story is not None and winner_option.get("branch_key"):
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT branches_taken_json FROM chronicle_state "
                    "WHERE guild_id=?",
                    (guild_id,),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    try:
                        branches = json.loads(row[0] or "[]")
                    except Exception:
                        branches = []
                    branches.append({
                        "council_id": council["id"],
                        "branch_key": winner_option["branch_key"],
                        "session_id": session_id,
                    })
                    await db.execute(
                        "UPDATE chronicle_state SET branches_taken_json=? "
                        "WHERE guild_id=?",
                        (json.dumps(branches), guild_id),
                    )
                    await db.commit()
        except Exception as ex:
            print(f"[close_council branch] {ex}")

    # Alimente la progression Chronique (kind: council_votes)
    if _story is not None:
        try:
            await _story.on_council_vote(guild_id)
        except Exception:
            pass

        try:
            await _story.log_chronicle_event(
                guild_id, "council_decided",
                {
                    "council_id": council["id"],
                    "title": council["title"],
                    "decided_option": winner_option["id"],
                    "decided_label": winner_label,
                    "total_votes": total,
                    "branch_key": winner_option.get("branch_key", ""),
                },
            )
        except Exception:
            pass

    # Announce dans le salon Chronique
    guild = _bot.get_guild(guild_id)
    if guild:
        await _announce_council_closed(guild, council, winner_option, total, counts)

    print(
        f"[weekly_council] close session={session_id} winner={winner_idx} "
        f"total={total}"
    )

    return {
        "session_id": session_id,
        "council_id": council["id"],
        "winner_idx": winner_idx,
        "winner_label": winner_label,
        "total_votes": total,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Vote handling
# ═══════════════════════════════════════════════════════════════════════════

async def record_vote(
    guild_id: int, session_id: int, user_id: int, option_idx: int,
) -> dict:
    """Enregistre un vote. 1 par user, immuable."""
    if _get_db is None:
        return {"error": "DB indisponible"}

    # Vérifie session ouverte
    active = await get_active_council(guild_id)
    if not active or active["session_id"] != session_id:
        return {"error": "Conseil clos ou inactif"}

    # Vérifie pas déjà voté
    existing = await has_user_voted(session_id, user_id)
    if existing is not None:
        return {"error": "Tu as déjà voté", "previous_option": existing}

    # Vérifie option valide
    council = get_council_def(active["council_id"])
    if not council:
        return {"error": "Conseil introuvable"}
    if not (0 <= option_idx < len(council["options"])):
        return {"error": "Option invalide"}

    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO council_votes "
                "(session_id, user_id, option_idx) VALUES (?, ?, ?)",
                (session_id, user_id, option_idx),
            )
            await db.execute(
                "UPDATE council_sessions SET total_votes = "
                "(SELECT COUNT(*) FROM council_votes WHERE session_id=?) "
                "WHERE id=?",
                (session_id, session_id),
            )
            await db.commit()
        return {
            "success": True,
            "option_label": council["options"][option_idx]["label"],
            "option_description": council["options"][option_idx]["description"],
        }
    except Exception as ex:
        print(f"[record_vote] {ex}")
        return {"error": str(ex)}


# ═══════════════════════════════════════════════════════════════════════════
#  Panel V2
# ═══════════════════════════════════════════════════════════════════════════

def _progress_bar_small(count: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    pct = count / total
    fill = int(width * pct)
    return "█" * fill + "░" * (width - fill)


async def build_council_panel(
    guild_id: int, user_id: int,
) -> Optional[discord.ui.LayoutView]:
    """Construit le panel du conseil actif pour ce user."""
    if _v2 is None:
        return None

    active = await get_active_council(guild_id)
    if not active:
        # Pas de conseil actif
        LayoutView = _v2['LayoutView']
        v2_title = _v2['v2_title']
        v2_body = _v2['v2_body']
        v2_container = _v2['v2_container']
        items = [
            v2_title("🗳️ Conseil des Anciens"),
            v2_body(
                "_Aucun conseil ouvert._\n\n"
                "Le prochain ouvre **lundi 20h FR**."
            ),
        ]

        class _NoCouncil(LayoutView):
            def __init__(self):
                super().__init__(timeout=120)
                self.add_item(v2_container(*items, color=0x808080))

        return _NoCouncil()

    council = get_council_def(active["council_id"])
    if not council:
        return None

    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    counts = await get_vote_counts(active["session_id"])
    total = sum(counts.values())
    user_voted = await has_user_voted(active["session_id"], user_id)

    items = [
        v2_title(f"🗳️ {council['title']}"),
        v2_subtitle(
            f"_Conseil des Anciens · {total} voix_"
        ),
        v2_divider(),
        v2_body(f"_{council['context']}_"),
        v2_divider(),
        v2_body(f"**❓ {council['question']}**"),
    ]

    # Options avec barres de progression
    for idx, opt in enumerate(council["options"]):
        c = counts.get(idx, 0)
        pct = int((c * 100) / max(1, total)) if total else 0
        bar = _progress_bar_small(c, max(1, total))
        my_vote_mark = " ✅ **(ton vote)**" if user_voted == idx else ""
        items.append(v2_body(
            f"{opt['label']}{my_vote_mark}\n"
            f"_{opt['description']}_\n"
            f"`{bar}` `{c}` voix ({pct}%)"
        ))

    items.append(v2_divider())
    if user_voted is not None:
        items.append(v2_body(
            f"-# ✅ Vote enregistré · résultat à la fermeture · ferme `{active['closes_at']}`"
        ))
    else:
        items.append(v2_body(
            f"-# 1 vote/membre, immuable · ferme `{active['closes_at']}`"
        ))

    class _CouncilLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0xD4AF37))

    layout = _CouncilLayout()

    # Boutons de vote (3 options) si pas encore voté
    # Phase 208 FIX : boutons dans des ActionRow (max 5/row). Un Button/
    # DynamicItem brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body".
    # On crée des Button BRUTS avec le MÊME label/style/custom_id que
    # CouncilVoteButton (DynamicItem) ; le clic reste capté par le DynamicItem.
    if user_voted is None:
        vote_buttons = []
        for idx, opt in enumerate(council["options"]):
            vote_buttons.append(Button(
                label=(opt["label"])[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"council_vote:{active['session_id']}:{idx}:{user_id}",
            ))
        for i in range(0, len(vote_buttons), 5):
            layout.add_item(discord.ui.ActionRow(*vote_buttons[i:i + 5]))

    return layout


# ═══════════════════════════════════════════════════════════════════════════
#  Vote button (persistent)
# ═══════════════════════════════════════════════════════════════════════════

class CouncilVoteButton(
    discord.ui.DynamicItem[Button],
    template=r"council_vote:(?P<session_id>\d+):(?P<option_idx>\d+):(?P<user_id>\d+)",
):
    def __init__(self, session_id: int, option_idx: int, user_id: int):
        super().__init__(
            Button(
                label="…",
                style=discord.ButtonStyle.primary,
                custom_id=f"council_vote:{session_id}:{option_idx}:{user_id}",
            )
        )
        self.session_id = session_id
        self.option_idx = option_idx
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(
            int(match["session_id"]),
            int(match["option_idx"]),
            int(match["user_id"]),
        )

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Conseil depuis le Codex.", ephemeral=True
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
            result = await record_vote(
                btn_i.guild.id, self.session_id, btn_i.user.id, self.option_idx,
            )

            if result.get("error"):
                await btn_i.followup.send(
                    f"❌ {result['error']}", ephemeral=True,
                )
                return

            # Rebuild panel showing the vote was registered
            view = await build_council_panel(btn_i.guild.id, btn_i.user.id)
            confirmation = (
                f"✅ **Vote enregistré** pour : {result.get('option_label', '?')}\n\n"
                f"_{result.get('option_description', '')}_\n\n"
                f"_Le résultat sera annoncé à la fermeture du Conseil._"
            )
            if view:
                try:
                    await btn_i.edit_original_response(
                        view=view, content=None, attachments=[],
                    )
                except Exception:
                    pass
            try:
                await btn_i.followup.send(confirmation, ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[council_vote callback] {ex}")
            try:
                await btn_i.followup.send(
                    f"❌ Erreur : `{ex}`", ephemeral=True,
                )
            except Exception:
                pass


class CouncilVotePublicButton(
    discord.ui.DynamicItem[Button],
    template=r"cvote_pub:(?P<session_id>\d+):(?P<option_idx>\d+)",
):
    """Phase 235.21 : bouton de vote PUBLIC, posé DIRECTEMENT sous l'annonce du Conseil
    (fini « va dans le Codex pour voter » → personne n'y arrivait). N'importe quel
    membre clique → son vote est enregistré (record_vote gère « déjà voté »/immuable).
    Pas de user_id dans le custom_id → un seul jeu de boutons pour tout le serveur."""
    def __init__(self, session_id: int, option_idx: int):
        super().__init__(Button(
            label="Voter",
            style=discord.ButtonStyle.primary,
            custom_id=f"cvote_pub:{session_id}:{option_idx}",
        ))
        self.session_id = session_id
        self.option_idx = option_idx

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["session_id"]), int(match["option_idx"]))

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
            result = await record_vote(
                btn_i.guild.id, self.session_id, btn_i.user.id, self.option_idx)
            if result.get("error"):
                await btn_i.followup.send(f"❌ {result['error']}", ephemeral=True)
                return
            await btn_i.followup.send(
                f"✅ **Vote pris en compte** : {result.get('option_label', '?')}\n"
                f"_Résultat à la fermeture du Conseil._", ephemeral=True)
        except Exception as ex:
            print(f"[cvote_pub callback] {ex}")
            try:
                await btn_i.followup.send("❌ Erreur, réessaie.", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(CouncilVoteButton, CouncilVotePublicButton)
    except Exception as ex:
        print(f"[weekly_council register_persistent_views] {ex}")


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


async def _announce_council_open(
    guild: discord.Guild, council: dict, session_id: int, closing: datetime,
) -> None:
    ch = await _find_chronicle_channel(guild)
    if not ch:
        return
    # Phase 235.21 : vote EN UN CLIC sous l'annonce (boutons publics) — fini « va dans
    # le Codex ». Texte court : contexte + question + options, vote 👇 juste en dessous.
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_container = _v2['v2_container']

    body = f"_{council['context']}_\n\n**❓ {council['question']}**\n"
    for opt in council["options"]:
        body += f"\n{opt['label']} — _{opt['description']}_"
    body += "\n\n_⏱️ Fermeture mercredi 23h59 · 1 vote/membre · vote ci-dessous 👇_"

    items = [
        v2_title(f"🗳️ Conseil des Anciens — {council['title']}"),
        v2_body(body),
    ]
    vote_buttons = [
        Button(label=(opt["label"])[:80], style=discord.ButtonStyle.primary,
               custom_id=f"cvote_pub:{session_id}:{idx}")
        for idx, opt in enumerate(council["options"])
    ]

    class _CouncilAnnounce(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=ui_v2.Palette.INFO))
            for i in range(0, len(vote_buttons), 5):
                self.add_item(discord.ui.ActionRow(*vote_buttons[i:i + 5]))

    try:
        await ch.send(view=_CouncilAnnounce(),
                      allowed_mentions=discord.AllowedMentions.none())
    except Exception as ex:
        print(f"[_announce_council_open] {ex}")


async def _announce_council_closed(
    guild: discord.Guild, council: dict, winner: dict,
    total_votes: int, counts: dict,
) -> None:
    ch = await _find_chronicle_channel(guild)
    if not ch:
        return
    msg = (
        f"🎉 **Conseil clos — *{council['title']}***\n\n"
        f"_{total_votes} membres ont voté._\n\n"
        f"**🏆 Voie choisie :** {winner['label']}\n\n"
        f"_{winner['description']}_\n\n"
        f"**📊 Détail des votes :**\n"
    )
    for idx, opt in enumerate(council["options"]):
        c = counts.get(idx, 0)
        pct = int((c * 100) / max(1, total_votes)) if total_votes else 0
        msg += f"{opt['label']} : `{c}` voix ({pct}%)\n"
    msg += (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        "_Le résultat est gravé dans le Codex. La suite de l'histoire en "
        "tiendra compte._"
    )
    try:
        _t, _, _b = msg.partition("\n\n")
        await ch.send(
            view=ui_v2.recap_view(_t.replace("**", "").replace("*", ""), _b or msg,
                                  color=ui_v2.Palette.PREMIUM),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=15)
async def council_task():
    """Toutes les 15 min : check si on doit ouvrir ou fermer un conseil."""
    if _bot is None or _get_db is None:
        return
    try:
        # Ouverture lundi 20h FR (fenêtre 1h)
        if _is_open_window():
            for guild in _bot.guilds:
                try:
                    await open_council(guild.id)
                except Exception as ex:
                    print(f"[council_task open guild={guild.id}] {ex}")

        # Fermeture si closes_at dépassé
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with _get_db() as db:
                async with db.execute(
                    "SELECT id FROM council_sessions "
                    "WHERE status='open' AND closes_at < ?",
                    (now_iso,),
                ) as cur:
                    sessions_to_close = [int(r[0]) for r in await cur.fetchall()]
            for sid in sessions_to_close:
                try:
                    await close_council(sid)
                except Exception as ex:
                    print(f"[council_task close session={sid}] {ex}")
        except Exception as ex:
            print(f"[council_task close scan] {ex}")
    except Exception as ex:
        print(f"[council_task] {ex}")


@council_task.before_loop
async def _council_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point depuis le Codex
# ═══════════════════════════════════════════════════════════════════════════

async def open_council_from_codex(interaction: discord.Interaction) -> None:
    """Appelé depuis le bouton 🗳️ Conseil dans le Codex (page current)."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_council_from_codex defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        view = await build_council_panel(interaction.guild.id, interaction.user.id)
        if view is None:
            await interaction.followup.send("❌ Conseil indisponible.", ephemeral=True)
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_council_from_codex] {ex}")
        try:
            await interaction.followup.send(
                f"❌ Erreur : `{ex}`", ephemeral=True,
            )
        except Exception:
            pass


__all__ = [
    "COUNCIL_CATALOG",
    "COUNCIL_OPEN_WEEKDAY",
    "COUNCIL_OPEN_HOUR",
    "COUNCIL_CLOSE_WEEKDAY",
    "COUNCIL_CLOSE_HOUR",
    "setup",
    "init_db",
    "get_council_def",
    "list_council_ids",
    "get_councils_for_chapter",
    "get_active_council",
    "get_vote_counts",
    "has_user_voted",
    "open_council",
    "close_council",
    "record_vote",
    "build_council_panel",
    "open_council_from_codex",
    "CouncilVoteButton",
    "council_task",
    "register_persistent_views",
]
