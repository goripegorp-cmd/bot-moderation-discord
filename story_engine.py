"""
story_engine.py — Cœur de la Chronique d'Abylumis (Phase 170.1).

🎯 OBJECTIF : un récit narratif persistant qui dure 9 mois, divisé en 3 Actes
de 3 chapitres chacun. Chaque chapitre prend ~4 semaines à compléter et est
alimenté par les actions habituelles du serveur (mob_hunts, quêtes daily,
boss raid damage, etc.). Le serveur entier collabore pour avancer dans
l'histoire — c'est une expérience collective, pas individuelle.

PHILOSOPHIE :
- Aucune action n'est obligatoire ; les quêtes daily et le combat alimentent
  AUTOMATIQUEMENT la progression sans rien demander de plus.
- Le serveur peut "rater" un chapitre — il y a un cap temporel de 60 jours
  par chapitre. Si raté, on bascule quand même, mais sans la récompense.
- Les choix votés au Conseil (Phase 170.4) modifient les chapitres suivants.
- Tout est logué dans le Codex (Phase 170.7) pour la postérité.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- get_state(guild_id) -> dict avec chapitre actif
- record_progress(guild_id, kind, amount=1, user_id=None) -> hook progression
- log_chronicle_event(guild_id, event_kind, payload) -> log Codex
- chronicle_task (hourly check progression + rollover)
- ACTS, get_chapter_def(act, chapter)

DB :
- chronicle_state (guild_id PK, current_act, current_chapter, started_at,
                   last_advance_at, branches_taken_json, status)
- chronicle_chapter_progress (guild_id, act, chapter, kind, current,
                              target, started_at, completed_at, status)
- chronicle_events (id PK, guild_id, event_kind, timestamp, payload_json)
- chronicle_contributors (guild_id, act, chapter, user_id, contribution_count)
"""
from __future__ import annotations

import json
import random
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

# Cap temporel : un chapitre n'attend pas indéfiniment. Si pas complété en
# 60 jours, on bascule au suivant en "expired" (pas de récompense, mais
# l'histoire continue).
CHAPTER_TIMEOUT_DAYS = 60

# Bonus alliance : si au moins 3 membres d'une même alliance contribuent
# au même chapitre, leur contribution est multipliée.
ALLIANCE_BONUS_MULT = 1.20
ALLIANCE_BONUS_MIN_MEMBERS = 3


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE NARRATIF : les 3 Actes, 9 chapitres
# ═══════════════════════════════════════════════════════════════════════════
# Structure d'un chapitre :
# - id : "1.1", "1.2", etc. (act.chapter)
# - title : titre narratif
# - prologue : texte d'ouverture quand le chapitre démarre
# - epilogue : texte de fin quand le chapitre est complété
# - kind : type de progression ("mob_kills", "quest_completes",
#          "boss_damage", "encounters", "council_votes", "regional_defenses")
# - target : nombre à atteindre pour compléter
# - reward_coins : coins distribués à tous les contributeurs
# - reward_title : titre obtenu en fin de chapitre (None si juste milestone)
# - branches : liste de chapitres alternatifs si choix collectif (None par défaut)

ACTS = [
    {
        "id": 1,
        "title": "L'Éveil des Cendres",
        "subtitle": "Quelque chose change dans le monde…",
        "chapters": [
            {
                "id": "1.1",
                "title": "Les Premiers Signes",
                "prologue": (
                    "Une fine cendre grise tombe sur les royaumes. Personne ne sait "
                    "d'où elle vient. Les NPCs parlent à voix basse de présages et "
                    "de réveils anciens. Le serveur doit en apprendre plus en "
                    "explorant le monde — chaque créature vaincue révèle un fragment."
                ),
                "epilogue": (
                    "Les cendres ne s'arrêtent pas. Mais en vidant les régions de "
                    "leurs monstres, le serveur a découvert que cette cendre vient "
                    "des Profondes — une vaste zone souterraine oubliée."
                ),
                "kind": "mob_kills",
                "target": 3000,
                "reward_coins": 200,
                "reward_title": "Témoin des Premiers Signes",
            },
            {
                "id": "1.2",
                "title": "La Source Trouvée",
                "prologue": (
                    "Aria la Veilleuse demande au serveur d'enquêter sur les "
                    "Profondes. Chaque quête accomplie rapproche le serveur de la "
                    "source des cendres. Le monde retient son souffle."
                ),
                "epilogue": (
                    "Les Profondes révèlent leur secret : un sceau ancien est en "
                    "train de se briser. Une entité enchaînée depuis des siècles "
                    "tente de se libérer. Que faire ?"
                ),
                "kind": "quest_completes",
                "target": 1500,
                "reward_coins": 300,
                "reward_title": "Enquêteur des Profondes",
            },
            {
                "id": "1.3",
                "title": "Le Premier Choix",
                "prologue": (
                    "Le Conseil des Anciens convoque le serveur. Trois voies "
                    "s'offrent : SCELLER l'entité plus fort (sécurité), L'ÉTUDIER "
                    "(savoir interdit), ou la DÉTRUIRE (purification). Chaque clic "
                    "sur une encounter compte comme préparation au vote."
                ),
                "epilogue": (
                    "Le vote a tranché. La voie choisie déterminera tout l'Acte 2. "
                    "Le serveur entre dans une nouvelle ère."
                ),
                "kind": "encounters",
                "target": 200,
                "reward_coins": 500,
                "reward_title": "Voix de l'Éveil",
                "branches": ["2.1A_seal", "2.1B_study", "2.1C_destroy"],
            },
        ],
    },
    {
        "id": 2,
        "title": "Le Schisme",
        "subtitle": "Le serveur a choisi. Maintenant, vivre avec.",
        "chapters": [
            {
                "id": "2.1",
                "title": "Les Disparitions",
                "prologue": (
                    "Trois NPCs principaux disparaissent dans des circonstances "
                    "étranges. Korr le Forgeron, Lyra l'Érudite, Drazek le Guerrier. "
                    "Le serveur doit affronter des boss puissants pour récupérer des "
                    "indices sur leur sort."
                ),
                "epilogue": (
                    "Les boss tombés ont parlé. Les trois NPCs ne sont pas morts — "
                    "ils ont été appelés ailleurs, vers un lieu que le serveur ne "
                    "connaît pas encore. La quête s'intensifie."
                ),
                "kind": "boss_damage",
                "target": 80000,
                "reward_coins": 400,
                "reward_title": "Chasseur de Vérités",
            },
            {
                "id": "2.2",
                "title": "Les Indices Combinés",
                "prologue": (
                    "Les indices fragmentés tombent au hasard sur les joueurs. "
                    "Aucun joueur ne peut comprendre seul — il faut PARLER aux "
                    "autres, partager ce qu'on a, recouper. Le serveur doit "
                    "combiner ses fragments pour reconstituer la carte."
                ),
                "epilogue": (
                    "La carte est reconstituée. Elle pointe vers le Sanctuaire — "
                    "une zone des montagnes que personne n'a osé explorer depuis "
                    "des générations. Les NPCs disparus y sont attendus."
                ),
                "kind": "mystery_combines",
                "target": 50,
                "reward_coins": 600,
                "reward_title": "Limier des Cendres",
            },
            {
                "id": "2.3",
                "title": "Le Second Choix",
                "prologue": (
                    "Le serveur doit DÉFENDRE les régions pendant les patrouilles "
                    "hebdomadaires pour gagner le droit d'accéder au Sanctuaire. "
                    "Si trop de régions tombent, le passage reste fermé."
                ),
                "epilogue": (
                    "Le Sanctuaire s'ouvre. Ce qui s'y trouve est plus grand que "
                    "tout ce que le serveur avait imaginé. L'Acte final approche."
                ),
                "kind": "regional_defenses",
                "target": 100,
                "reward_coins": 700,
                "reward_title": "Gardien des Régions",
            },
        ],
    },
    {
        "id": 3,
        "title": "L'Affrontement Final",
        "subtitle": "Tout converge vers le Sanctuaire.",
        "chapters": [
            {
                "id": "3.1",
                "title": "La Préparation",
                "prologue": (
                    "Le Boss Final approche. Le serveur a 1 mois pour s'armer, "
                    "se renforcer, forger l'équipement nécessaire. Chaque kill, "
                    "chaque quête compte. C'est le dernier effort cumulatif."
                ),
                "epilogue": (
                    "Le serveur est prêt. Les NPCs disparus sont retrouvés, blessés "
                    "mais vivants. Ils rejoignent les rangs pour la bataille."
                ),
                "kind": "mob_kills",
                "target": 5000,
                "reward_coins": 800,
                "reward_title": "Forgeron de la Fin",
            },
            {
                "id": "3.2",
                "title": "L'Approche",
                "prologue": (
                    "Le Conseil convoque le serveur chaque semaine pour ajuster la "
                    "stratégie. Chaque vote rapproche le serveur du Sanctuaire. "
                    "La cohésion collective est la dernière clé."
                ),
                "epilogue": (
                    "Le Sanctuaire est en vue. Le serveur entre dans la nuit la plus "
                    "longue. Une seule bataille reste."
                ),
                "kind": "council_votes",
                "target": 8,
                "reward_coins": 1000,
                "reward_title": "Stratège du Sanctuaire",
            },
            {
                "id": "3.3",
                "title": "Le Boss Final",
                "prologue": (
                    "L'entité libérée s'avère plus complexe que prévu. Un raid de "
                    "weekend en 3 phases. Le serveur entier doit attaquer simultanément. "
                    "La fin de la Chronique se joue maintenant."
                ),
                "epilogue": (
                    "La Chronique d'Abylumis se clôt. Le serveur a écrit son histoire. "
                    "Ce qui s'est passé restera gravé dans le Codex pour toujours."
                ),
                "kind": "boss_damage",
                "target": 200000,
                "reward_coins": 2000,
                "reward_title": "Héros de la Chronique",
            },
        ],
    },
]


def get_chapter_def(act_id: int, chapter_idx: int) -> Optional[dict]:
    """Retourne la def d'un chapitre par (act, idx). idx = 0, 1, 2."""
    for act in ACTS:
        if act["id"] == act_id:
            try:
                return act["chapters"][chapter_idx]
            except IndexError:
                return None
    return None


def get_act_def(act_id: int) -> Optional[dict]:
    for act in ACTS:
        if act["id"] == act_id:
            return act
    return None


def total_chapters_count() -> int:
    return sum(len(a["chapters"]) for a in ACTS)


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    """Crée les tables de la Chronique. Idempotent."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chronicle_state (
                    guild_id INTEGER PRIMARY KEY,
                    current_act INTEGER DEFAULT 1,
                    current_chapter INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_advance_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    branches_taken_json TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chronicle_chapter_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    act INTEGER NOT NULL,
                    chapter INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    current INTEGER DEFAULT 0,
                    target INTEGER NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    status TEXT DEFAULT 'in_progress'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chronicle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    event_kind TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    payload_json TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chronicle_contributors (
                    guild_id INTEGER NOT NULL,
                    act INTEGER NOT NULL,
                    chapter INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    contribution_count INTEGER DEFAULT 0,
                    last_action_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, act, chapter, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chronicle_progress_active "
                "ON chronicle_chapter_progress(guild_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chronicle_events_recent "
                "ON chronicle_events(guild_id, timestamp)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[story_engine init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  State access
# ═══════════════════════════════════════════════════════════════════════════

async def _ensure_state(guild_id: int) -> None:
    """Crée l'état initial pour une guild si absent + le chapitre 1.1."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id FROM chronicle_state WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            if row:
                return
            await db.execute(
                "INSERT INTO chronicle_state (guild_id, current_act, current_chapter) "
                "VALUES (?, 1, 0)",
                (guild_id,),
            )
            # Spawn premier chapitre
            chap = get_chapter_def(1, 0)
            if chap:
                await db.execute(
                    "INSERT INTO chronicle_chapter_progress "
                    "(guild_id, act, chapter, kind, target) "
                    "VALUES (?, 1, 0, ?, ?)",
                    (guild_id, chap["kind"], int(chap["target"])),
                )
            await db.commit()
            await _log_event_internal(
                db, guild_id, "chronicle_started",
                {"act": 1, "chapter": 0, "title": chap["title"] if chap else "—"},
            )
            await db.commit()
    except Exception as ex:
        print(f"[story_engine _ensure_state] {ex}")


async def get_state(guild_id: int) -> Optional[dict]:
    """Retourne l'état complet : act, chapter, progress, target, % etc."""
    if _get_db is None:
        return None
    await _ensure_state(guild_id)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT current_act, current_chapter, started_at, "
                "last_advance_at, branches_taken_json, status "
                "FROM chronicle_state WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            act_id, chap_idx, started_at, last_adv, branches_json, status = row

            # Progress du chapitre en cours
            async with db.execute(
                "SELECT current, target, started_at, status, kind "
                "FROM chronicle_chapter_progress "
                "WHERE guild_id=? AND act=? AND chapter=? AND status='in_progress' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id, act_id, chap_idx),
            ) as cur:
                prog = await cur.fetchone()

        chap_def = get_chapter_def(act_id, chap_idx)
        if not chap_def:
            return None
        current, target = (int(prog[0]), int(prog[1])) if prog else (0, int(chap_def["target"]))
        chap_started = prog[2] if prog else started_at
        kind = prog[4] if prog else chap_def["kind"]
        progress_pct = min(100, int((current * 100) / max(1, target)))

        try:
            branches = json.loads(branches_json or "[]")
        except Exception:
            branches = []

        return {
            "act": act_id,
            "act_title": get_act_def(act_id)["title"] if get_act_def(act_id) else "—",
            "act_subtitle": get_act_def(act_id)["subtitle"] if get_act_def(act_id) else "",
            "chapter_idx": chap_idx,
            "chapter_id": chap_def["id"],
            "chapter_title": chap_def["title"],
            "chapter_prologue": chap_def["prologue"],
            "kind": kind,
            "current": current,
            "target": target,
            "progress_pct": progress_pct,
            "chapter_started": chap_started,
            "started_at": started_at,
            "last_advance_at": last_adv,
            "branches_taken": branches,
            "status": status,
            "reward_coins": chap_def.get("reward_coins", 0),
            "reward_title": chap_def.get("reward_title"),
        }
    except Exception as ex:
        print(f"[story_engine get_state] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Progression hooks (appelés depuis mob_hunts, quests, boss, etc.)
# ═══════════════════════════════════════════════════════════════════════════

VALID_KINDS = {
    "mob_kills", "quest_completes", "boss_damage", "encounters",
    "council_votes", "regional_defenses", "mystery_combines",
}


async def record_progress(
    guild_id: int,
    kind: str,
    amount: int = 1,
    user_id: Optional[int] = None,
) -> bool:
    """Hook universel : alimente la progression du chapitre courant si le
    kind correspond. Sinon, no-op silencieux.

    Retourne True si la progression a été enregistrée, False sinon.
    """
    if _get_db is None or amount <= 0:
        return False
    if kind not in VALID_KINDS:
        return False
    try:
        await _ensure_state(guild_id)
        async with _get_db() as db:
            # Lit le chapitre actif
            async with db.execute(
                "SELECT id, kind, current, target FROM chronicle_chapter_progress "
                "WHERE guild_id=? AND status='in_progress' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return False
            prog_id, expected_kind, current, target = row
            if expected_kind != kind:
                return False
            new_current = min(int(current) + int(amount), int(target))
            await db.execute(
                "UPDATE chronicle_chapter_progress SET current=? WHERE id=?",
                (new_current, prog_id),
            )
            # Contributors
            if user_id:
                await db.execute(
                    "INSERT INTO chronicle_contributors "
                    "(guild_id, act, chapter, user_id, contribution_count) "
                    "VALUES (?, "
                    "(SELECT current_act FROM chronicle_state WHERE guild_id=?), "
                    "(SELECT current_chapter FROM chronicle_state WHERE guild_id=?), "
                    "?, ?) "
                    "ON CONFLICT(guild_id, act, chapter, user_id) DO UPDATE SET "
                    "contribution_count = contribution_count + ?, "
                    "last_action_at = CURRENT_TIMESTAMP",
                    (guild_id, guild_id, guild_id, user_id, int(amount), int(amount)),
                )
            await db.commit()

            # Milestone notifications (25/50/75/100%)
            old_pct = int((int(current) * 100) / max(1, int(target)))
            new_pct = int((new_current * 100) / max(1, int(target)))
            for milestone in (25, 50, 75, 100):
                if old_pct < milestone <= new_pct:
                    await _log_event_internal(
                        db, guild_id, "chapter_milestone",
                        {"act": None, "chapter": None, "pct": milestone},
                    )
                    await db.commit()
                    break

            # Si target atteint, on programme l'avance (sera fait par chronicle_task)
        return True
    except Exception as ex:
        print(f"[story_engine record_progress] {ex}")
        return False


# Hooks pratiques pour les modules existants
async def on_mob_kill(guild_id: int, user_id: Optional[int] = None) -> None:
    await record_progress(guild_id, "mob_kills", 1, user_id)


async def on_quest_complete(guild_id: int, user_id: Optional[int] = None) -> None:
    await record_progress(guild_id, "quest_completes", 1, user_id)


async def on_boss_damage(
    guild_id: int, damage: int, user_id: Optional[int] = None,
) -> None:
    await record_progress(guild_id, "boss_damage", int(damage), user_id)


async def on_encounter_completed(
    guild_id: int, user_id: Optional[int] = None,
) -> None:
    await record_progress(guild_id, "encounters", 1, user_id)


async def on_council_vote(
    guild_id: int, user_id: Optional[int] = None,
) -> None:
    await record_progress(guild_id, "council_votes", 1, user_id)


async def on_regional_defense(
    guild_id: int, user_id: Optional[int] = None,
) -> None:
    await record_progress(guild_id, "regional_defenses", 1, user_id)


async def on_mystery_combine(
    guild_id: int, user_id: Optional[int] = None,
) -> None:
    await record_progress(guild_id, "mystery_combines", 1, user_id)


# ═══════════════════════════════════════════════════════════════════════════
#  Codex events log
# ═══════════════════════════════════════════════════════════════════════════

async def _log_event_internal(db, guild_id: int, event_kind: str, payload: dict):
    """Variante interne : utilise un db transaction déjà ouverte."""
    try:
        await db.execute(
            "INSERT INTO chronicle_events (guild_id, event_kind, payload_json) "
            "VALUES (?, ?, ?)",
            (guild_id, event_kind, json.dumps(payload, ensure_ascii=False)),
        )
    except Exception:
        pass


async def log_chronicle_event(
    guild_id: int, event_kind: str, payload: dict,
) -> None:
    """Logue un événement dans le Codex (public, permanent)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await _log_event_internal(db, guild_id, event_kind, payload)
            await db.commit()
    except Exception as ex:
        print(f"[story_engine log_event] {ex}")


async def get_recent_events(
    guild_id: int, limit: int = 20,
) -> list[dict]:
    """Pour le Codex : retourne les N derniers événements ordre antéchronologique."""
    if _get_db is None:
        return []
    try:
        out = []
        async with _get_db() as db:
            async with db.execute(
                "SELECT event_kind, timestamp, payload_json FROM chronicle_events "
                "WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, int(limit)),
            ) as cur:
                for r in await cur.fetchall():
                    try:
                        payload = json.loads(r[2] or "{}")
                    except Exception:
                        payload = {}
                    out.append({"kind": r[0], "timestamp": r[1], "payload": payload})
        return out
    except Exception:
        return []


async def get_top_contributors(
    guild_id: int, act: int, chapter: int, limit: int = 10,
) -> list[tuple[int, int]]:
    """Retourne [(user_id, contribution_count), ...] triés par contribution."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, contribution_count FROM chronicle_contributors "
                "WHERE guild_id=? AND act=? AND chapter=? "
                "ORDER BY contribution_count DESC LIMIT ?",
                (guild_id, act, chapter, int(limit)),
            ) as cur:
                return [(int(r[0]), int(r[1])) for r in await cur.fetchall()]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
#  Advance chapter (called by task when target reached or timeout)
# ═══════════════════════════════════════════════════════════════════════════

async def _try_advance_chapter(guild_id: int) -> Optional[dict]:
    """Si le chapitre courant est complété (ou timeout), passe au suivant.
    Retourne dict avec info du nouveau chapitre, ou None si rien à faire.
    """
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT current_act, current_chapter, status, branches_taken_json "
                "FROM chronicle_state WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                state_row = await cur.fetchone()
            if not state_row:
                return None
            act_id, chap_idx, status, branches_json = state_row
            if status != "active":
                return None

            async with db.execute(
                "SELECT id, current, target, started_at FROM chronicle_chapter_progress "
                "WHERE guild_id=? AND act=? AND chapter=? AND status='in_progress' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id, act_id, chap_idx),
            ) as cur:
                prog_row = await cur.fetchone()
            if not prog_row:
                return None
            prog_id, current, target, started_at = prog_row

            current = int(current)
            target = int(target)
            completed = current >= target

            # Check timeout (60 jours)
            timed_out = False
            try:
                dt_started = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                )
                if dt_started.tzinfo is None:
                    dt_started = dt_started.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - dt_started > timedelta(
                    days=CHAPTER_TIMEOUT_DAYS
                ):
                    timed_out = True
            except Exception:
                pass

            if not (completed or timed_out):
                return None

            # Mark current as done
            final_status = "completed" if completed else "expired"
            await db.execute(
                "UPDATE chronicle_chapter_progress "
                "SET status=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (final_status, prog_id),
            )
            await db.commit()

            # Log
            current_chap_def = get_chapter_def(act_id, chap_idx)
            await _log_event_internal(
                db, guild_id, "chapter_completed",
                {
                    "act": act_id, "chapter": chap_idx,
                    "title": current_chap_def["title"] if current_chap_def else "—",
                    "status": final_status,
                    "current": current, "target": target,
                },
            )

            # Détermine le prochain chapitre
            next_act = act_id
            next_chap = chap_idx + 1
            current_act_def = get_act_def(act_id)
            if current_act_def and next_chap >= len(current_act_def["chapters"]):
                # Fin de l'Acte → Acte suivant
                next_act = act_id + 1
                next_chap = 0

            next_chap_def = get_chapter_def(next_act, next_chap)
            if not next_chap_def:
                # Fin de la Chronique
                await db.execute(
                    "UPDATE chronicle_state SET status='completed' WHERE guild_id=?",
                    (guild_id,),
                )
                await _log_event_internal(
                    db, guild_id, "chronicle_completed",
                    {"final_act": act_id, "final_chapter": chap_idx},
                )
                await db.commit()
                return {"completed_chronicle": True}

            # Avance
            await db.execute(
                "UPDATE chronicle_state SET current_act=?, current_chapter=?, "
                "last_advance_at=CURRENT_TIMESTAMP WHERE guild_id=?",
                (next_act, next_chap, guild_id),
            )
            await db.execute(
                "INSERT INTO chronicle_chapter_progress "
                "(guild_id, act, chapter, kind, target) VALUES (?, ?, ?, ?, ?)",
                (guild_id, next_act, next_chap, next_chap_def["kind"],
                 int(next_chap_def["target"])),
            )
            await _log_event_internal(
                db, guild_id, "chapter_started",
                {"act": next_act, "chapter": next_chap,
                 "title": next_chap_def["title"]},
            )
            await db.commit()

            return {
                "advanced": True,
                "from_act": act_id,
                "from_chapter": chap_idx,
                "to_act": next_act,
                "to_chapter": next_chap,
                "new_title": next_chap_def["title"],
                "previous_completed": completed,
                "previous_status": final_status,
                "previous_reward_coins": (current_chap_def.get("reward_coins", 0)
                                         if current_chap_def else 0),
                "previous_reward_title": (current_chap_def.get("reward_title")
                                         if current_chap_def else None),
            }
    except Exception as ex:
        print(f"[story_engine advance_chapter] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=15)
async def chronicle_task():
    """Toutes les 15 min : check si un chapitre peut avancer pour chaque guild."""
    if _bot is None or _get_db is None:
        return
    try:
        for guild in _bot.guilds:
            try:
                result = await _try_advance_chapter(guild.id)
                if result and result.get("advanced"):
                    await _announce_chapter_advance(guild, result)
                elif result and result.get("completed_chronicle"):
                    await _announce_chronicle_completed(guild)
            except Exception as ex:
                print(f"[chronicle_task guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[chronicle_task] {ex}")


@chronicle_task.before_loop
async def _chronicle_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Announces (when chapter advances)
# ═══════════════════════════════════════════════════════════════════════════

async def _find_announce_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Trouve le salon d'annonce de la Chronique.

    Priorité : `chronicle_channel_id` config → `hub_channel` → premier salon
    nommé "chronique/lore/saga" → None.
    """
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


async def _announce_chapter_advance(guild: discord.Guild, result: dict) -> None:
    """Annonce dans le salon Chronique qu'un chapitre est terminé + suivant débloqué."""
    ch = await _find_announce_channel(guild)
    if not ch:
        return
    prev_status = result.get("previous_status", "completed")
    prev_act = result.get("from_act", 1)
    prev_chap = result.get("from_chapter", 0)
    prev_def = get_chapter_def(prev_act, prev_chap)
    new_def = get_chapter_def(result["to_act"], result["to_chapter"])

    if prev_status == "completed" and prev_def:
        head = f"🎉 **CHAPITRE TERMINÉ** — *{prev_def['title']}*\n\n"
        body = f"_{prev_def.get('epilogue', '…')}_\n\n"
        reward_lines = []
        if result.get("previous_reward_coins"):
            reward_lines.append(
                f"💰 **{result['previous_reward_coins']}** 🪙 à tous les contributeurs"
            )
        if result.get("previous_reward_title"):
            reward_lines.append(
                f"🏅 Titre permanent : **{result['previous_reward_title']}**"
            )
        if reward_lines:
            body += "**Récompenses :**\n" + "\n".join(reward_lines) + "\n\n"
    elif prev_def:
        head = (
            f"⏳ **CHAPITRE EXPIRÉ** — *{prev_def['title']}*\n\n"
            f"_Le temps a manqué. L'histoire continue malgré tout._\n\n"
        )
        body = ""
    else:
        head = "📖 **La Chronique avance.**\n\n"
        body = ""

    if new_def:
        body += (
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📖 **NOUVEAU CHAPITRE** — *{new_def['title']}*\n\n"
            f"_{new_def['prologue']}_\n\n"
            f"🎯 Objectif : `{new_def['target']}` — alimenté par : `{new_def['kind']}`\n"
            f"_Clique 📖 dans le hub pour voir la progression._"
        )

    try:
        await ch.send(head + body, allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


async def _announce_chronicle_completed(guild: discord.Guild) -> None:
    """Annonce que TOUTE la Chronique est terminée (9 chapitres)."""
    ch = await _find_announce_channel(guild)
    if not ch:
        return
    msg = (
        "🌟 **LA CHRONIQUE D'ABYLUMIS EST TERMINÉE** 🌟\n\n"
        "_9 chapitres, 3 Actes, 9 mois d'aventure collective._\n\n"
        "Le serveur a écrit son histoire. Ce qui s'est passé restera gravé dans le "
        "Codex pour toujours.\n\n"
        "_Un nouvel Acte commencera bientôt. Mais l'épisode qui se clôt aujourd'hui "
        "ne reviendra jamais._"
    )
    try:
        await ch.send(msg, allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


__all__ = [
    "ACTS",
    "ALLIANCE_BONUS_MULT",
    "ALLIANCE_BONUS_MIN_MEMBERS",
    "CHAPTER_TIMEOUT_DAYS",
    "VALID_KINDS",
    "setup",
    "init_db",
    "get_state",
    "get_chapter_def",
    "get_act_def",
    "total_chapters_count",
    "record_progress",
    "on_mob_kill",
    "on_quest_complete",
    "on_boss_damage",
    "on_encounter_completed",
    "on_council_vote",
    "on_regional_defense",
    "on_mystery_combine",
    "log_chronicle_event",
    "get_recent_events",
    "get_top_contributors",
    "chronicle_task",
]
