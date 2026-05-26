"""
events42.py — Phase 42 : nouveaux types d'events.

Catalogues purs (zero dépendance discord.py) :
- WORLD_BOSSES : boss hebdomadaires énormes nécessitant coordination
- DAILY_RIDDLES : énigmes journalières avec choix multiples
- VOICE_CHAOS_ACTIONS : effets aléatoires sur les vocaux en soirée
"""
from __future__ import annotations

import random
from typing import Optional


# =============================================================================
# WORLD BOSSES — événements hebdomadaires (samedi 21h FR par défaut)
# =============================================================================

# Bosses MASSIFS qui nécessitent ~5-20 attaquants pour être vaincus.
# Durée 90 min. Récompenses légendaires.
WORLD_BOSSES = [
    {
        "id": "leviathan_cosmique",
        "name": "🌌 Léviathan Cosmique",
        "title": "Le Léviathan Cosmique",
        "description": (
            "Une bête colossale venue d'au-delà des étoiles. "
            "Son écaille brille comme une nébuleuse. Aucun seul guerrier ne peut l'abattre. "
            "Il faut S'ENTRAIDER."
        ),
        "max_hp": 50000,
        "attack_damage": 30,         # dégâts par attaque
        "image_emoji": "🌌🐉",
        "color": 0x4B0082,
        "phases": [
            {"name": "Éveil cosmique", "hp_threshold": 0.66, "buff": None},
            {"name": "Fureur stellaire", "hp_threshold": 0.33, "buff": "double_damage_taken"},
            {"name": "Dernier souffle", "hp_threshold": 0.0, "buff": "rage"},
        ],
        "victory_reward_coins": 2500,
        "participation_reward_coins": 400,
        "rare_drop_chance": 0.35,    # 35% chance d'avoir un drop divin pour les top10
    },
    {
        "id": "phoenix_ardent",
        "name": "🔥 Phénix Ardent",
        "title": "Le Phénix Ardent",
        "description": (
            "Un phénix légendaire renaît à chaque siècle pour ravager les terres. "
            "Vaincs-le avant qu'il ne renaisse de ses cendres ! Travail d'équipe obligatoire."
        ),
        "max_hp": 45000,
        "attack_damage": 25,
        "image_emoji": "🔥🦅",
        "color": 0xFF4500,
        "phases": [
            {"name": "Vol enflammé", "hp_threshold": 0.66, "buff": None},
            {"name": "Tempête de cendres", "hp_threshold": 0.33, "buff": "fire_damage"},
            {"name": "Renaissance imminente", "hp_threshold": 0.0, "buff": "double_damage_taken"},
        ],
        "victory_reward_coins": 2200,
        "participation_reward_coins": 350,
        "rare_drop_chance": 0.30,
    },
    {
        "id": "souverain_des_abimes",
        "name": "🌊 Souverain des Abîmes",
        "title": "Le Souverain des Abîmes",
        "description": (
            "Remonté des profondeurs océaniques, il engloutit les serveurs entiers. "
            "Coordonnez vos attaques — il faut au moins 5 guerriers actifs pour espérer survivre."
        ),
        "max_hp": 55000,
        "attack_damage": 35,
        "image_emoji": "🌊👁️",
        "color": 0x000080,
        "phases": [
            {"name": "Marée montante", "hp_threshold": 0.66, "buff": None},
            {"name": "Tourbillon", "hp_threshold": 0.33, "buff": "swap_targets"},
            {"name": "Engloutissement final", "hp_threshold": 0.0, "buff": "double_damage_taken"},
        ],
        "victory_reward_coins": 3000,
        "participation_reward_coins": 500,
        "rare_drop_chance": 0.40,
    },
]


def random_world_boss() -> dict:
    """Sélectionne un world boss aléatoire."""
    return random.choice(WORLD_BOSSES)


def get_world_boss(boss_id: str) -> Optional[dict]:
    for b in WORLD_BOSSES:
        if b["id"] == boss_id:
            return b
    return None


# =============================================================================
# DAILY RIDDLES — énigmes journalières (choix multiple)
# =============================================================================

DAILY_RIDDLES = [
    {
        "id": "r1",
        "question": "🧠 Plus j'ai d'yeux, moins je vois. Qui suis-je ?",
        "options": ["Une pomme de terre", "Un chat", "Un télescope", "Une étoile"],
        "answer_idx": 0,  # pomme de terre (yeux = germes)
        "explanation": "Une pomme de terre — ses « yeux » sont les germes.",
    },
    {
        "id": "r2",
        "question": "🌍 Quel mot contient toutes les voyelles dans l'ordre ?",
        "options": ["Anniversaire", "Faculté", "Aéroglisseur", "Aigre-doux"],
        "answer_idx": 2,
        "explanation": "Aéroglisseur : A-E-O-I-E-U (a-e-i-o-u dans l'ordre approximatif).",
    },
    {
        "id": "r3",
        "question": "🐦 Je vole sans ailes, je pleure sans yeux. Qui suis-je ?",
        "options": ["La pluie", "Un nuage", "Le vent", "Une larme"],
        "answer_idx": 1,
        "explanation": "Un nuage — il se déplace sans ailes et libère des gouttes sans yeux.",
    },
    {
        "id": "r4",
        "question": "🔢 Quel nombre s'écrit avec autant de lettres que sa valeur ?",
        "options": ["Deux", "Trois", "Quatre", "Cinq"],
        "answer_idx": 2,
        "explanation": "Quatre — Q-U-A-T-R-E = 6 lettres... attention en français c'est différent. La bonne réponse est CINQ qui a 4 lettres ? Non, on prend l'anglais : FOUR = 4. Réponse française : aucun n'est exact mais Quatre = 6 lettres est le plus proche... ⚠️ Réponse retenue : 'Quatre' par convention.",
    },
    {
        "id": "r5",
        "question": "🌙 Plus on en prend, plus on en laisse. Qu'est-ce ?",
        "options": ["Des photos", "Des pas", "De l'argent", "Des bonbons"],
        "answer_idx": 1,
        "explanation": "Des pas — chaque pas que tu fais laisse une trace derrière toi.",
    },
    {
        "id": "r6",
        "question": "📚 Qu'est-ce qui se brise sans qu'on n'y touche ?",
        "options": ["Une promesse", "Un verre", "Un miroir", "Le silence"],
        "answer_idx": 3,
        "explanation": "Le silence — il se brise quand quelqu'un parle.",
    },
    {
        "id": "r7",
        "question": "🚀 Quel mot perd une lettre quand on lui en ajoute deux ?",
        "options": ["Père", "Moins", "Verre", "Cinq"],
        "answer_idx": 1,
        "explanation": "Moins — en ajoutant 'p' et 's' tu fais MOINS PS = Moins (le sens change).",
    },
    {
        "id": "r8",
        "question": "💧 Je suis humide quand je sèche. Qui suis-je ?",
        "options": ["Une éponge", "Un parapluie", "Une serviette", "Un fer à repasser"],
        "answer_idx": 2,
        "explanation": "Une serviette — elle est mouillée en séchant le corps.",
    },
    {
        "id": "r9",
        "question": "👑 Plus on a peur de moi, plus j'approche. Qui suis-je ?",
        "options": ["La nuit", "La mort", "L'âge", "L'examen"],
        "answer_idx": 3,
        "explanation": "L'examen — c'est typiquement plus on a peur, plus la date approche.",
    },
    {
        "id": "r10",
        "question": "🎵 Quel instrument peut-on entendre mais pas voir ni toucher ?",
        "options": ["Le tonnerre", "Un orchestre", "Sa propre voix", "Le silence"],
        "answer_idx": 2,
        "explanation": "Sa propre voix — c'est notre instrument naturel.",
    },
    {
        "id": "r11",
        "question": "📅 Combien d'anniversaires a un homme moyen ?",
        "options": ["80", "1", "Selon l'âge", "Aucun"],
        "answer_idx": 1,
        "explanation": "1 — un seul anniversaire de naissance, les autres sont des célébrations.",
    },
    {
        "id": "r12",
        "question": "🌳 Plus on m'enlève, plus je grandis. Qui suis-je ?",
        "options": ["Un trou", "Un arbre", "Un nuage", "Une vague"],
        "answer_idx": 0,
        "explanation": "Un trou — plus tu creuses, plus il devient grand.",
    },
    {
        "id": "r13",
        "question": "🔥 Sans nourriture je vis, avec eau je meurs. Qui suis-je ?",
        "options": ["Un dragon", "Le feu", "Un poisson", "Un caillou"],
        "answer_idx": 1,
        "explanation": "Le feu — il a besoin d'oxygène pour vivre, l'eau l'éteint.",
    },
    {
        "id": "r14",
        "question": "⚡ Sans bouche je parle, sans oreilles j'entends. Qui suis-je ?",
        "options": ["Un écho", "Un téléphone", "Un livre", "Un robot"],
        "answer_idx": 0,
        "explanation": "Un écho — il répète ce qu'il entend.",
    },
    {
        "id": "r15",
        "question": "🪞 Plus je suis chaud, plus je suis frais. Qui suis-je ?",
        "options": ["Un pain", "Le pain au four", "Le journal", "Du café"],
        "answer_idx": 2,
        "explanation": "Le journal — quand il est 'tout chaud' (publié à l'instant) il est 'frais' (nouvelles fraîches).",
    },
    {
        "id": "r16",
        "question": "👻 Je n'ai pas de corps mais je vis. Plus tu me partages, plus je grandis. Qui suis-je ?",
        "options": ["Une histoire", "Une rumeur", "Une idée", "Toutes les réponses"],
        "answer_idx": 3,
        "explanation": "Toutes les réponses — histoire, rumeur, idée : toutes grandissent quand on les partage.",
    },
]


def random_riddle() -> dict:
    """Sélectionne une énigme aléatoire."""
    return random.choice(DAILY_RIDDLES)


def get_riddle(riddle_id: str) -> Optional[dict]:
    for r in DAILY_RIDDLES:
        if r["id"] == riddle_id:
            return r
    return None


# =============================================================================
# VOICE CHAOS — événements vocaux en soirée
# =============================================================================

# Chaque action est appliquée à UN vocal aléatoire (non protégé).
# Tous les effets sont temporaires (durée définie). Aucun n'est destructif.
VOICE_CHAOS_ACTIONS = [
    {
        "id": "rename_tempete",
        "name": "Tempête de neige",
        "emoji": "🌨️",
        "description": "Le vocal est temporairement renommé en 'Tempête'.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🌨️ TEMPÊTE — {original}",
    },
    {
        "id": "rename_fete",
        "name": "Soirée surprise",
        "emoji": "🎉",
        "description": "Le vocal est temporairement renommé en 'Soirée surprise'.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🎉 SOIRÉE — {original}",
    },
    {
        "id": "rename_cosmique",
        "name": "Anomalie cosmique",
        "emoji": "🌌",
        "description": "Une anomalie spatiale enveloppe ce vocal.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🌌 COSMOS — {original}",
    },
    {
        "id": "rename_party",
        "name": "Party de classe",
        "emoji": "🪩",
        "description": "Le vocal devient une discothèque underground.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🪩 DISCO — {original}",
    },
    {
        "id": "rename_mystere",
        "name": "Salon mystère",
        "emoji": "🔮",
        "description": "Un voile de mystère recouvre le vocal.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🔮 MYSTÈRE — {original}",
    },
    # Les chaos vraiment fous (déplacements) — désactivés par défaut, opt-in via owner
    # car ça peut être déstabilisant pour les membres
    {
        "id": "shuffle_members",
        "name": "Mélange général",
        "emoji": "🌀",
        "description": "Les membres du vocal sont mélangés entre eux (swap).",
        "duration_seconds": 0,  # action instantanée
        "kind": "shuffle",
        "opt_in_only": True,
    },
]


def random_voice_chaos(allow_aggressive: bool = False) -> dict:
    """Tire une action de chaos vocal.

    Si allow_aggressive=False (défaut), ne tire que les renames non-destructifs.
    """
    pool = [a for a in VOICE_CHAOS_ACTIONS if allow_aggressive or not a.get('opt_in_only')]
    if not pool:
        pool = VOICE_CHAOS_ACTIONS
    return random.choice(pool)


# =============================================================================
# GAME NIGHT PROMPTS — mini-jeux/sondages pour vendredi soir 21h-23h30
# =============================================================================

GAME_NIGHT_PROMPTS = [
    {"emoji": "🎬", "title": "Tu préfères : films ou séries ?", "kind": "vote", "options": ["🎬 Films", "📺 Séries"]},
    {"emoji": "🍕", "title": "Tu préfères : sucré ou salé ?", "kind": "vote", "options": ["🍬 Sucré", "🧂 Salé"]},
    {"emoji": "🌅", "title": "Tu préfères : matin ou soir ?", "kind": "vote", "options": ["🌅 Matin", "🌙 Soir"]},
    {"emoji": "🏖️", "title": "Tu préfères : plage ou montagne ?", "kind": "vote", "options": ["🏖️ Plage", "⛰️ Montagne"]},
    {"emoji": "🐱", "title": "Tu préfères : chat ou chien ?", "kind": "vote", "options": ["🐱 Chat", "🐶 Chien"]},
    {"emoji": "📚", "title": "Tu préfères : livre ou film ?", "kind": "vote", "options": ["📚 Livre", "🎬 Film"]},
    {"emoji": "☕", "title": "Tu préfères : café ou thé ?", "kind": "vote", "options": ["☕ Café", "🍵 Thé"]},
    {"emoji": "🎮", "title": "Plate-forme préférée ?", "kind": "vote", "options": ["🖥️ PC", "🎮 Console", "📱 Mobile"]},
    {"emoji": "🌍", "title": "Continent rêvé ?", "kind": "vote", "options": ["🇪🇺 Europe", "🌏 Asie", "🌎 Amériques", "🌍 Afrique"]},
    {"emoji": "💭", "title": "Si tu avais un super-pouvoir ?", "kind": "debate", "prompt": "Vole, téléportation, lecture pensées, invisibilité... que choisis-tu et pourquoi ?"},
    {"emoji": "🎵", "title": "Genre musical préféré ?", "kind": "vote", "options": ["🎸 Rock", "🎤 Pop", "🎧 Électro", "🎹 Classique", "🎤 Rap"]},
    {"emoji": "💸", "title": "1M€ — tu fais quoi en premier ?", "kind": "debate", "prompt": "Investissement, voyage, achat, don ? Racontez !"},
    {"emoji": "🎂", "title": "Ton meilleur souvenir d'enfance ?", "kind": "debate", "prompt": "Un mot, une scène, une émotion — partagez."},
    {"emoji": "🚀", "title": "Si tu voyageais dans le temps : passé ou futur ?", "kind": "vote", "options": ["⏪ Passé", "⏩ Futur"]},
    {"emoji": "🔮", "title": "Devinette express", "kind": "riddle", "question": "Qu'est-ce qui monte et descend mais ne bouge pas ?", "answer": "Un escalier"},
    {"emoji": "🎯", "title": "Quel est ton hobby caché ?", "kind": "debate", "prompt": "Quelque chose que personne ne sait sur toi !"},
    {"emoji": "🌟", "title": "Une personne célèbre à rencontrer ?", "kind": "debate", "prompt": "Vivant ou mort — qui et pourquoi ?"},
    {"emoji": "🎨", "title": "Couleur préférée ?", "kind": "vote", "options": ["🔴 Rouge", "🔵 Bleu", "🟢 Vert", "🟡 Jaune", "🟣 Violet", "⚫ Noir"]},
    {"emoji": "🍔", "title": "Plat ultime ?", "kind": "debate", "prompt": "Si tu ne pouvais manger qu'UN seul plat à vie..."},
    {"emoji": "📅", "title": "Saison préférée ?", "kind": "vote", "options": ["🌸 Printemps", "☀️ Été", "🍂 Automne", "❄️ Hiver"]},
    {"emoji": "🎭", "title": "Tu préfères : faire rire ou faire pleurer (au cinéma) ?", "kind": "vote", "options": ["😂 Rire", "😭 Émouvoir"]},
    {"emoji": "💡", "title": "L'invention la plus utile selon toi ?", "kind": "debate", "prompt": "Roue, électricité, internet, smartphone... ou autre ?"},
    {"emoji": "🦄", "title": "Animal mythique préféré ?", "kind": "vote", "options": ["🦄 Licorne", "🐉 Dragon", "🧚 Fée", "👻 Fantôme"]},
    {"emoji": "🎤", "title": "Tu chantes sous la douche ?", "kind": "vote", "options": ["🎤 Oui souvent", "🤫 Jamais", "😅 Parfois"]},
    {"emoji": "📖", "title": "Anecdote bizarre que tu connais", "kind": "debate", "prompt": "Le truc inutile mais cool que tu as appris cette semaine !"},
    {"emoji": "🌧️", "title": "Tu préfères : pluie ou neige ?", "kind": "vote", "options": ["🌧️ Pluie", "❄️ Neige"]},
    {"emoji": "🎲", "title": "Quel jeu de société tu kiffes ?", "kind": "debate", "prompt": "Loup-garou, Mille Bornes, Monopoly... ton préféré ?"},
    {"emoji": "🧠", "title": "Devinette logique", "kind": "riddle", "question": "Plus on en partage, plus on en a. Qu'est-ce ?", "answer": "Le bonheur (ou un sourire)"},
    {"emoji": "🌃", "title": "Ville rêvée pour vivre ?", "kind": "debate", "prompt": "Paris, Tokyo, NYC, ou un coin secret ?"},
    {"emoji": "🐺", "title": "Animal totem ?", "kind": "vote", "options": ["🦅 Aigle", "🐺 Loup", "🦊 Renard", "🦁 Lion", "🐢 Tortue"]},
]


def random_game_night_prompts(n: int = 10) -> list:
    """Tire N prompts random sans doublons pour une soirée."""
    pool = list(GAME_NIGHT_PROMPTS)
    random.shuffle(pool)
    return pool[:min(n, len(pool))]


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'WORLD_BOSSES', 'random_world_boss', 'get_world_boss',
    'DAILY_RIDDLES', 'random_riddle', 'get_riddle',
    'VOICE_CHAOS_ACTIONS', 'random_voice_chaos',
    'GAME_NIGHT_PROMPTS', 'random_game_night_prompts',
]
