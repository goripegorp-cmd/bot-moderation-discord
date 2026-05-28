"""
npc_personalities.py — Les 6 NPCs vivants de la Chronique (Phase 170.2).

🎯 OBJECTIF : donner une vraie personnalité aux NPCs cités dans
story_engine.py. Chaque NPC a un score d'humeur :
- Par joueur individuel (0-100) : relation perso avec ce NPC
- Par serveur (moyenne agrégée) : humeur collective

L'humeur affecte (dans les phases suivantes) :
- Les dialogues des encounters quotidiennes
- Les prix de Sienna la Marchande
- Les loots offerts par Korr
- Les indices distribués par Lyra
- L'aide de Drazek dans les boss raids
- Les conseils prophétiques d'Aria
- Les apparitions du Voyageur

PHILOSOPHIE :
- Chaque NPC a un trait dominant (sage / loyal / curieuse / impulsif /
  neutre / mystérieux).
- L'humeur initiale = 50 (neutre).
- Les actions des encounters modifient ±10 à ±20 selon le choix.
- L'humeur ne descend jamais sous 0 ni au-dessus de 100.
- Pas de "favori" auto : chaque user développe sa propre relation.

RULES.md :
- Aucun système romantique ; les NPCs sont des compagnons, pas des âmes-soeurs.
- Pas d'emoji cœur ; les icônes sont thématiques.
- Pas de friend-list explicite : la relation reste avec les NPCs, pas
  d'humain à humain.

API publique :
- setup(bot, get_db, db_get, v2)
- init_db()
- NPC_CATALOG, get_npc_def(npc_id)
- get_mood(guild_id, user_id, npc_id) -> int 0-100
- change_mood(guild_id, user_id, npc_id, delta) -> nouveau mood
- get_aggregate_mood(guild_id, npc_id) -> float (moyenne serveur)
- get_user_relationships(guild_id, user_id) -> liste triée par mood
- mood_label(mood_int) -> str ("Méfiance", "Neutre", "Confiance", "Loyauté", "Fidélité")
"""
from __future__ import annotations

from typing import Optional

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

INITIAL_MOOD = 50
MIN_MOOD = 0
MAX_MOOD = 100


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE NPCs
# ═══════════════════════════════════════════════════════════════════════════
# Champs :
# - id : identifiant court (utilisé en DB + custom_id)
# - name : nom complet
# - title : titre/rôle
# - emoji : icône thématique
# - trait : trait dominant
# - description : 2-3 phrases pour le Codex / panels
# - location : où on le trouve (lore)
# - voice : style de dialogue (info pour les encounters)

NPC_CATALOG = [
    {
        "id": "aria",
        "name": "Aria",
        "title": "La Veilleuse",
        "emoji": "🌙",
        "trait": "sage",
        "description": (
            "Sage et prudente, Aria observe les présages depuis la Tour de la "
            "Veille. Elle aime les actions réfléchies et déteste la précipitation. "
            "Sa connaissance des cendres est inégalée."
        ),
        "location": "Tour de la Veille",
        "voice": "Mesurée, énigmatique, prophétique",
    },
    {
        "id": "korr",
        "name": "Korr",
        "title": "Le Forgeron",
        "emoji": "🔨",
        "trait": "loyal",
        "description": (
            "Loyal et simple, Korr forge depuis trente ans dans la Vallée des "
            "Braises. Il préfère les gens qui agissent à ceux qui parlent. "
            "Sa hache n'a jamais menti."
        ),
        "location": "Forge des Braises",
        "voice": "Direct, chaleureux, terre-à-terre",
    },
    {
        "id": "lyra",
        "name": "Lyra",
        "title": "L'Érudite",
        "emoji": "📚",
        "trait": "curieuse",
        "description": (
            "Curieuse et ambiguë, Lyra étudie les sciences interdites dans la "
            "Bibliothèque Sous-Vide. Elle sait des choses que les autres ignorent. "
            "Ses motivations restent floues."
        ),
        "location": "Bibliothèque Sous-Vide",
        "voice": "Intellectuelle, mystérieuse, parfois condescendante",
    },
    {
        "id": "drazek",
        "name": "Drazek",
        "title": "Le Guerrier",
        "emoji": "⚔️",
        "trait": "impulsif",
        "description": (
            "Impulsif et courageux, Drazek défend le Pic Rouge depuis sa "
            "naissance. Il se méfie des étrangers mais respecte la force. "
            "Ses cicatrices racontent son histoire."
        ),
        "location": "Pic Rouge",
        "voice": "Brusque, franc, parfois vulnérable",
    },
    {
        "id": "sienna",
        "name": "Sienna",
        "title": "La Marchande",
        "emoji": "💰",
        "trait": "neutre",
        "description": (
            "Neutre et calculatrice, Sienna parcourt les routes avec sa caravane. "
            "Elle vend tout ce qui se vend, achète tout ce qui s'achète. "
            "Sa loyauté va au plus offrant — mais elle n'oublie jamais un bienfait."
        ),
        "location": "Caravane itinérante",
        "voice": "Pragmatique, charmeuse, intéressée",
    },
    {
        "id": "voyageur",
        "name": "Le Voyageur",
        "title": "L'Inconnu",
        "emoji": "🌫️",
        "trait": "mysterieux",
        "description": (
            "Mystérieux et insaisissable, le Voyageur n'apparaît qu'aux moments "
            "charnières. Personne ne sait son nom véritable. Ses paroles ont "
            "toujours plusieurs sens."
        ),
        "location": "Partout et nulle part",
        "voice": "Cryptique, calme, énigmatique",
    },
]


def get_npc_def(npc_id: str) -> Optional[dict]:
    """Retourne la def d'un NPC par id."""
    for npc in NPC_CATALOG:
        if npc["id"] == npc_id:
            return npc
    return None


def list_npc_ids() -> list[str]:
    return [n["id"] for n in NPC_CATALOG]


# ═══════════════════════════════════════════════════════════════════════════
#  Mood labels
# ═══════════════════════════════════════════════════════════════════════════

def mood_label(mood: int) -> str:
    """Convertit un mood numérique en libellé narratif."""
    m = max(MIN_MOOD, min(MAX_MOOD, int(mood)))
    if m < 20:
        return "Méfiance profonde"
    if m < 40:
        return "Distance"
    if m < 60:
        return "Neutre"
    if m < 80:
        return "Confiance"
    if m < 95:
        return "Loyauté"
    return "Fidélité absolue"


def mood_icon(mood: int) -> str:
    m = max(MIN_MOOD, min(MAX_MOOD, int(mood)))
    if m < 20:
        return "🟥"
    if m < 40:
        return "🟧"
    if m < 60:
        return "🟨"
    if m < 80:
        return "🟩"
    return "🟦"


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
    """Crée la table npc_mood. Idempotent."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS npc_mood (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    npc_id TEXT NOT NULL,
                    mood INTEGER DEFAULT 50,
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    interaction_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, npc_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_npc_mood_user "
                "ON npc_mood(guild_id, user_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_npc_mood_aggregate "
                "ON npc_mood(guild_id, npc_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[npc_personalities init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Mood API
# ═══════════════════════════════════════════════════════════════════════════

async def get_mood(guild_id: int, user_id: int, npc_id: str) -> int:
    """Retourne le mood d'un user envers un NPC. Default = INITIAL_MOOD."""
    if _get_db is None:
        return INITIAL_MOOD
    if get_npc_def(npc_id) is None:
        return INITIAL_MOOD
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT mood FROM npc_mood "
                "WHERE guild_id=? AND user_id=? AND npc_id=?",
                (guild_id, user_id, npc_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return max(MIN_MOOD, min(MAX_MOOD, int(row[0])))
        return INITIAL_MOOD
    except Exception:
        return INITIAL_MOOD


async def change_mood(
    guild_id: int, user_id: int, npc_id: str, delta: int,
) -> int:
    """Modifie le mood (clamp dans [0, 100]). Retourne le nouveau mood."""
    if _get_db is None:
        return INITIAL_MOOD
    if get_npc_def(npc_id) is None:
        return INITIAL_MOOD
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT mood, interaction_count FROM npc_mood "
                "WHERE guild_id=? AND user_id=? AND npc_id=?",
                (guild_id, user_id, npc_id),
            ) as cur:
                row = await cur.fetchone()
            if row:
                old = int(row[0])
                count = int(row[1])
            else:
                old = INITIAL_MOOD
                count = 0

            new_mood = max(MIN_MOOD, min(MAX_MOOD, old + int(delta)))
            new_count = count + 1

            await db.execute(
                "INSERT INTO npc_mood "
                "(guild_id, user_id, npc_id, mood, interaction_count) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, npc_id) DO UPDATE SET "
                "mood = excluded.mood, "
                "interaction_count = npc_mood.interaction_count + 1, "
                "last_interaction = CURRENT_TIMESTAMP",
                (guild_id, user_id, npc_id, new_mood, new_count),
            )
            await db.commit()
            return new_mood
    except Exception as ex:
        print(f"[npc_personalities change_mood] {ex}")
        return INITIAL_MOOD


async def get_aggregate_mood(guild_id: int, npc_id: str) -> float:
    """Retourne l'humeur agrégée d'un NPC envers le serveur (moyenne)."""
    if _get_db is None:
        return float(INITIAL_MOOD)
    if get_npc_def(npc_id) is None:
        return float(INITIAL_MOOD)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT AVG(mood) FROM npc_mood "
                "WHERE guild_id=? AND npc_id=?",
                (guild_id, npc_id),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
        return float(INITIAL_MOOD)
    except Exception:
        return float(INITIAL_MOOD)


async def get_user_relationships(
    guild_id: int, user_id: int,
) -> list[dict]:
    """Retourne la liste des relations du user avec les 6 NPCs, triée."""
    relations = []
    for npc in NPC_CATALOG:
        mood = await get_mood(guild_id, user_id, npc["id"])
        relations.append({
            "npc_id": npc["id"],
            "name": npc["name"],
            "title": npc["title"],
            "emoji": npc["emoji"],
            "mood": mood,
            "label": mood_label(mood),
        })
    relations.sort(key=lambda r: r["mood"], reverse=True)
    return relations


async def get_interaction_count(
    guild_id: int, user_id: int, npc_id: str,
) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT interaction_count FROM npc_mood "
                "WHERE guild_id=? AND user_id=? AND npc_id=?",
                (guild_id, user_id, npc_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


__all__ = [
    "NPC_CATALOG",
    "INITIAL_MOOD",
    "MIN_MOOD",
    "MAX_MOOD",
    "setup",
    "init_db",
    "get_npc_def",
    "list_npc_ids",
    "mood_label",
    "mood_icon",
    "get_mood",
    "change_mood",
    "get_aggregate_mood",
    "get_user_relationships",
    "get_interaction_count",
]
