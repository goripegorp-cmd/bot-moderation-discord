"""
Phase 53 — AMBIANCE PASSIVE
─────────────────────────────────────────────────────────
• CONVERSATION_STARTERS : 40 questions ouvertes pour relancer le chat
• GOLDEN_HOUR_DEFAULTS : dimanche 18h-20h FR par défaut
"""
from __future__ import annotations
import random


CONVERSATION_STARTERS = [
    "🎮 Quel est le **premier jeu vidéo** qui vous a marqué ?",
    "🎵 Quelle musique vous met d'une humeur **incroyable** instantanément ?",
    "🍕 Si vous deviez manger **un seul plat** le reste de votre vie, ce serait quoi ?",
    "🌍 **Quel pays** ou ville rêvez-vous de visiter, et pourquoi ?",
    "📚 Un livre, film ou série que vous **recommanderiez les yeux fermés** ?",
    "💭 Quelle **compétence inutile** est votre fierté secrète ?",
    "🌃 **Lève-tôt ou couche-tard** ? Et pourquoi ?",
    "☕ Avec quoi vous **commencez votre journée** ?",
    "🎯 Une **résolution** que vous gardez sans en parler ?",
    "🐶 **Chat ou chien** ? (ou aucun des deux ?)",
    "🏆 Le **plus grand achievement** dont vous êtes fier dans votre vie ?",
    "🎨 Si vous deviez avoir un **super-pouvoir** banal, lequel ?",
    "📱 **L'app la plus inutile** que vous gardez sur votre téléphone ?",
    "🌧️ Vous préférez la **pluie ou le soleil** pour bosser ?",
    "🍦 Votre **parfum de glace** de l'enfance ?",
    "🚀 Une **innovation technologique** qui vous fascine actuellement ?",
    "🎤 La **chanson** que vous chantez sous la douche ?",
    "📺 Une **série culte** que vous n'avez jamais vue (oui c'est honteux) ?",
    "🍔 **Burger ou pizza** ? Justifiez votre crime.",
    "🌙 **Un rêve étrange** dont vous vous souvenez encore ?",
    "📝 Le **meilleur conseil** qu'on vous ait jamais donné ?",
    "🎬 Un film qui vous a **fait pleurer** (allez, avouez) ?",
    "🎁 Le **meilleur cadeau** que vous ayez reçu ?",
    "🏖️ **Plage ou montagne** pour les vacances ?",
    "💼 Votre **premier job** ? Bonne ou mauvaise expérience ?",
    "🌟 Une **célébrité morte** que vous rencontreriez si vous pouviez ?",
    "🎮 Si vous deviez **vivre dans un jeu vidéo** une semaine, lequel ?",
    "🍰 **Pâtisserie préférée** ? Bonus si vous savez la faire.",
    "📐 Une **matière scolaire détestée** qui vous a finalement servi ?",
    "🌊 **Une peur** que vous avez vaincue avec le temps ?",
    "🚗 La **dernière fois** que vous avez ri aux larmes, c'était pour quoi ?",
    "💡 Une **invention qui n'existe pas** mais devrait ?",
    "🎲 **Pile ou face** pour les grandes décisions, oui ou non ?",
    "🍂 Votre **saison préférée** ? (sans dire 'été')",
    "🎯 Le **skill** que vous aimeriez maîtriser en 1 mois si c'était possible ?",
    "🌍 Un **lieu près de chez vous** que peu de gens connaissent et qui mérite ?",
    "🎤 Si vous deviez choisir **votre walk-in song** (entrée arène), ce serait quoi ?",
    "📚 Un **fait random** que vous ressortez à chaque dîner ?",
    "🎮 La **meilleure cinématique** de jeu vidéo selon vous ?",
    "🌈 Votre **couleur préférée** révèle quoi sur vous ?",
]


def pick_random_starter() -> str:
    return random.choice(CONVERSATION_STARTERS)


GOLDEN_HOUR_DEFAULT_DAY = 6  # Dimanche (0=lundi, 6=dimanche)
GOLDEN_HOUR_DEFAULT_START = 18
GOLDEN_HOUR_DEFAULT_END = 20
GOLDEN_HOUR_MULTIPLIER = 2  # ×2 coins/XP


__all__ = [
    "CONVERSATION_STARTERS", "pick_random_starter",
    "GOLDEN_HOUR_DEFAULT_DAY", "GOLDEN_HOUR_DEFAULT_START",
    "GOLDEN_HOUR_DEFAULT_END", "GOLDEN_HOUR_MULTIPLIER",
]
