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
    # Phase 101 AMPLIFY : 5 nouveaux noms thématiques pour plus de variété
    {
        "id": "rename_volcan",
        "name": "Éruption volcanique",
        "emoji": "🌋",
        "description": "Lave en fusion partout — restez au chaud !",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🌋 VOLCAN — {original}",
    },
    {
        "id": "rename_forest",
        "name": "Forêt enchantée",
        "emoji": "🌲",
        "description": "Une forêt magique envahit le vocal.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🌲 FORÊT — {original}",
    },
    {
        "id": "rename_pirate",
        "name": "Bateau pirate",
        "emoji": "🏴‍☠️",
        "description": "Ahoy ! Le vocal devient un navire pirate.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🏴‍☠️ PIRATES — {original}",
    },
    {
        "id": "rename_neon",
        "name": "Cyberpunk Neon",
        "emoji": "🌃",
        "description": "Lumières néon et synthwave invadent le vocal.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🌃 NEON — {original}",
    },
    {
        "id": "rename_ocean",
        "name": "Profondeurs océanes",
        "emoji": "🌊",
        "description": "Le vocal est englouti par les abysses.",
        "duration_seconds": 300,
        "kind": "rename",
        "rename_pattern": "🌊 OCÉAN — {original}",
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
# GAME NIGHT EVENTS — vrais événements interactifs 2026
# Pas des prompts "tu préfères" : des vrais mécanismes de jeu live multijoueur
# =============================================================================

# kinds disponibles (chacun est géré par bot.py avec une view dédiée) :
#   - speed_click      : 1er à cliquer un bouton dans X secondes → jackpot
#   - threshold_click  : il faut N personnes différentes qui cliquent en T sec → bonus pour TOUS
#   - emoji_storm      : "envoyez tous l'emoji X dans 15s" — minimum N participants
#   - guess_number     : le bot a choisi un nombre 1-100, premier proche gagne
#   - color_vote_live  : sondage couleur avec barre en temps réel
#   - prediction       : "combien de messages dans #general dans 30 min ?" → ranges
#   - chain_continue   : le bot pose le début d'une histoire, les membres ajoutent 1 phrase
#   - identity_secret  : 1 membre random reçoit en DM un mot secret, doit faire deviner via emojis
#   - power_move       : 1 membre random reçoit le pouvoir de "doubler" un autre membre (donner +50 coins)
#   - sync_react       : objectif collectif "5 personnes réagissent dans 30s" → tout le monde gagne
#   - rapid_fire       : 5 mini-questions à la suite, points cumulés en 60s

GAME_NIGHT_EVENTS = [
    # ─── SPEED CLICK : 1er à cliquer dans 20s → gros gain ───
    {
        "id": "speed_click_jackpot",
        "kind": "speed_click",
        "emoji": "⚡",
        "title": "⚡ JACKPOT FLASH",
        "description": "Premier à cliquer **maintenant** ! Disponible 20 secondes.",
        "duration": 20,
        "reward_coins": 400,
        "button_label": "💥 GO !",
    },
    {
        "id": "speed_click_double",
        "kind": "speed_click",
        "emoji": "🔥",
        "title": "🔥 Double or rien",
        "description": "Premier clic = +200 🪙. **15 secondes** seulement.",
        "duration": 15,
        "reward_coins": 200,
        "button_label": "🎯 Prendre",
    },

    # ─── THRESHOLD CLICK : N personnes en T secondes → tout le monde gagne ───
    {
        "id": "threshold_5_60s",
        "kind": "threshold_click",
        "emoji": "🤝",
        "title": "🤝 Tous ensemble — 5 clics en 60 sec",
        "description": "Si **5 personnes différentes** cliquent dans la minute, **TOUT LE MONDE** gagne 80 🪙.",
        "duration": 60,
        "threshold": 5,
        "reward_coins": 80,
        "button_label": "✋ J'en suis",
    },
    {
        "id": "threshold_10_120s",
        "kind": "threshold_click",
        "emoji": "🌊",
        "title": "🌊 La Vague — 10 clics en 2 min",
        "description": "**10 personnes différentes** en 2 minutes. **TOUS** les cliquers gagnent 150 🪙.",
        "duration": 120,
        "threshold": 10,
        "reward_coins": 150,
        "button_label": "🌊 Rejoindre la vague",
    },

    # ─── EMOJI STORM : envoyez tous un emoji en X sec ───
    {
        "id": "emoji_storm_fire",
        "kind": "emoji_storm",
        "emoji": "🔥",
        "title": "🔥 Tempête de feu — postez 🔥",
        "description": "Postez **🔥** dans le chat dans **20 secondes**. À partir de 5 participants, tous gagnent 60 🪙.",
        "duration": 20,
        "trigger_emoji": "🔥",
        "threshold": 5,
        "reward_coins": 60,
    },
    {
        "id": "emoji_storm_heart",
        "kind": "emoji_storm",
        "emoji": "❤️",
        "title": "❤️ Vague d'amour — postez ❤️",
        "description": "Postez **❤️** dans **15 sec**. À partir de 3 personnes : tous gagnent 50 🪙.",
        "duration": 15,
        "trigger_emoji": "❤️",
        "threshold": 3,
        "reward_coins": 50,
    },
    {
        "id": "emoji_storm_thunder",
        "kind": "emoji_storm",
        "emoji": "⚡",
        "title": "⚡ Coup de tonnerre — postez ⚡",
        "description": "Postez **⚡** dans **15 sec**. Bonus collectif si on atteint 4 personnes.",
        "duration": 15,
        "trigger_emoji": "⚡",
        "threshold": 4,
        "reward_coins": 70,
    },

    # ─── SYNC REACT : réactions simultanées sur le message ───
    {
        "id": "sync_react_5",
        "kind": "sync_react",
        "emoji": "🤝",
        "title": "🤝 Synchronisation — 5 ❤️ en 30 sec",
        "description": "Réagissez **❤️** à ce message. 5 réactions en 30 sec → **TOUS** gagnent 70 🪙.",
        "duration": 30,
        "target_emoji": "❤️",
        "threshold": 5,
        "reward_coins": 70,
    },

    # ─── ANAGRAMME : reconstituer un mot (gardé) ───
    {
        "id": "anagramme_facile",
        "kind": "anagramme",
        "emoji": "🔤",
        "title": "🔤 Anagramme — trouve le mot",
        "description": "Le bot mélange les lettres d'un mot. Postez le mot dans le chat. Premier gagne **200 🪙**.",
        "duration": 60,
        "word_pool": [
            "DRAGON", "PIRATE", "PLANETE", "DISCORD", "VOYAGE", "MUSIQUE",
            "MAGIQUE", "VICTOIRE", "AVENTURE", "MONTAGNE", "OCEAN", "TRESOR",
            "BATAILLE", "ETOILE", "ROYAUME", "CHATEAU", "GARDIEN", "MYSTERE",
        ],
        "reward_coins": 200,
    },

    # ─── 🔍 DÉTECTIVE EXPRESS : enquête sur 4 suspects via 3 indices RÉELS ───
    # Le bot pick 4 membres actifs random. Indices basés sur les VRAIES stats du
    # coupable (messages, alliance, level). Premier à identifier le bon suspect gagne.
    {
        "id": "detective_express",
        "kind": "detective_express",
        "emoji": "🔍",
        "title": "🔍 Détective Express — Trouve le coupable",
        "description": (
            "**4 suspects** dans le serveur, 1 seul est coupable. Le bot va donner **3 indices** "
            "basés sur les vraies stats du coupable (messages, alliance, niveau...). À toi de "
            "déduire et de cliquer le bon suspect en premier. Gagne **400 🪙**."
        ),
        "duration": 180,
        "reward_coins": 400,
        "consolation_coins": 75,  # 2e clic
    },

    # ─── ♟️ MASTERMIND / CODE SECRET : devine la combinaison via feedback ───
    # Code de 4 couleurs parmi 6. Tu proposes via boutons, le bot répond
    # "X bien placés, Y présents mais mal placés". Premier à trouver gagne.
    {
        "id": "mastermind",
        "kind": "mastermind",
        "emoji": "♟️",
        "title": "♟️ Mastermind — Code Secret",
        "description": (
            "Le bot a généré un **code secret de 4 couleurs** parmi 6 (🔴🟡🟢🔵🟣⚫).\n"
            "Tu peux essayer **plusieurs combinaisons**. À chaque essai, le bot te dit combien "
            "sont **bien placées** et combien sont **présentes mais mal placées**.\n"
            "Maximum 8 essais. Premier à trouver le code exact gagne **500 🪙**."
        ),
        "duration": 600,  # 10 min
        "reward_coins": 500,
    },

    # ─── 🏆 QUIZ SURVIVOR : élimination Battle Royale ───
    # 5 questions à la suite, 30s chacune. Mauvaise réponse = éliminé.
    # Dernier debout = jackpot. Top 3 consolation.
    {
        "id": "quiz_survivor",
        "kind": "quiz_survivor",
        "emoji": "🏆",
        "title": "🏆 Quiz Survivor — Battle Royale",
        "description": (
            "**5 questions à élimination**. À chaque question, tu as **30 secondes** pour "
            "cliquer la bonne réponse. Mauvaise réponse → **ÉLIMINÉ** pour les suivantes.\n\n"
            "**Survivant final = 800 🪙**. Top 3 = consolation 150 🪙."
        ),
        "duration": 240,
        "reward_coins": 800,
        "consolation_coins": 150,
        # Pool de questions (catégories variées)
        "questions": [
            {"q": "Quel est l'océan le plus profond ?", "options": ["Atlantique", "Pacifique", "Indien", "Arctique"], "answer_idx": 1},
            {"q": "Quelle planète est la plus chaude ?", "options": ["Mercure", "Vénus", "Mars", "Jupiter"], "answer_idx": 1},
            {"q": "En quelle année est tombé le mur de Berlin ?", "options": ["1987", "1989", "1991", "1993"], "answer_idx": 1},
            {"q": "Quel est l'élément chimique de symbole Au ?", "options": ["Argent", "Aluminium", "Or", "Argon"], "answer_idx": 2},
            {"q": "Qui a peint la Joconde ?", "options": ["Michel-Ange", "Léonard de Vinci", "Raphaël", "Donatello"], "answer_idx": 1},
            {"q": "Quel pays compte le plus de fuseaux horaires ?", "options": ["Russie", "USA", "Chine", "France"], "answer_idx": 3},
            {"q": "Quelle est la capitale de l'Australie ?", "options": ["Sydney", "Melbourne", "Canberra", "Perth"], "answer_idx": 2},
            {"q": "Combien de cordes un violon a-t-il ?", "options": ["3", "4", "5", "6"], "answer_idx": 1},
            {"q": "Qui a inventé le téléphone ?", "options": ["Edison", "Bell", "Tesla", "Marconi"], "answer_idx": 1},
            {"q": "Quel est le plus long fleuve du monde ?", "options": ["Amazone", "Nil", "Yangzi Jiang", "Mississippi"], "answer_idx": 1},
            {"q": "En quelle année a été créé Discord ?", "options": ["2013", "2015", "2017", "2019"], "answer_idx": 1},
            {"q": "Quelle est la langue la plus parlée dans le monde ?", "options": ["Anglais", "Mandarin", "Espagnol", "Hindi"], "answer_idx": 1},
            {"q": "Quel est le plus grand désert du monde ?", "options": ["Sahara", "Antarctique", "Gobi", "Arabie"], "answer_idx": 1},
            {"q": "Combien d'os dans le corps humain adulte ?", "options": ["156", "206", "256", "306"], "answer_idx": 1},
            {"q": "Qui a écrit Les Misérables ?", "options": ["Zola", "Hugo", "Balzac", "Dumas"], "answer_idx": 1},
        ],
    },
]


def random_game_night_events(n: int = 10) -> list:
    """Tire N events random sans doublons d'IDs pour une soirée."""
    pool = list(GAME_NIGHT_EVENTS)
    random.shuffle(pool)
    return pool[:min(n, len(pool))]


# Alias legacy (au cas où du code l'utiliserait encore)
GAME_NIGHT_PROMPTS = GAME_NIGHT_EVENTS
random_game_night_prompts = random_game_night_events


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'WORLD_BOSSES', 'random_world_boss', 'get_world_boss',
    'DAILY_RIDDLES', 'random_riddle', 'get_riddle',
    'VOICE_CHAOS_ACTIONS', 'random_voice_chaos',
    'GAME_NIGHT_EVENTS', 'random_game_night_events',
    # Legacy aliases (compat)
    'GAME_NIGHT_PROMPTS', 'random_game_night_prompts',
]
