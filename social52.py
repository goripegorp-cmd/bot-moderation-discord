"""
Phase 52 — SOCIAL
─────────────────────────────────────────────────────────
• Shoutout categories (les raisons de remercier qqun)
• Mentor / Apprenti : règles d'éligibilité
"""
from __future__ import annotations
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  SHOUTOUTS — Catégories
# ═══════════════════════════════════════════════════════════════════════════════

SHOUTOUT_CATEGORIES = [
    {"id": "helpful",     "label": "🤝 M'a aidé",          "color": 0x57F287},
    {"id": "creative",    "label": "🎨 Créatif",            "color": 0xE67E22},
    {"id": "friendly",    "label": "😊 Bienveillant",       "color": 0xFEE75C},
    {"id": "playmate",    "label": "🎮 Bon coéquipier",     "color": 0x9B59B6},
    {"id": "mentor",      "label": "🧠 M'a appris",         "color": 0x3498DB},
    {"id": "moderator",   "label": "🛡️ Bonne modération",   "color": 0xE74C3C},
]


def get_shoutout_category(cat_id: str) -> Optional[dict]:
    for c in SHOUTOUT_CATEGORIES:
        if c["id"] == cat_id:
            return c
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  MENTORAT — Règles d'éligibilité
# ═══════════════════════════════════════════════════════════════════════════════
#
# Mentor potentiel : membre depuis ≥30 jours ET level ≥5 ET pas d'apprenti actuel
# Apprenti potentiel : membre depuis ≤7 jours ET sans mentor

MENTOR_MIN_DAYS = 30
MENTOR_MIN_LEVEL = 5
APPRENTICE_MAX_DAYS = 7

# Bonus quand mentor et apprenti interagissent dans la même journée
MENTOR_INTERACTION_BONUS_COINS = 50
APPRENTICE_INTERACTION_BONUS_COINS = 30

# Durée de la relation : 30 jours par défaut (ensuite l'apprenti "diplôme")
MENTORSHIP_DURATION_DAYS = 30


__all__ = [
    "SHOUTOUT_CATEGORIES", "get_shoutout_category",
    "MENTOR_MIN_DAYS", "MENTOR_MIN_LEVEL", "APPRENTICE_MAX_DAYS",
    "MENTOR_INTERACTION_BONUS_COINS", "APPRENTICE_INTERACTION_BONUS_COINS",
    "MENTORSHIP_DURATION_DAYS",
]
