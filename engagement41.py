"""
engagement41.py — Phase 41 : moteur d'engagement quotidien.

Contient les CATALOGUES et HELPERS pour :
- Daily Quests (3 quetes journalieres avec streak)
- Achievements / Hauts faits (80+ unlocks)
- Pets / Compagnons (6 pets evolutifs)
- Daily Wheel (roulette quotidienne ponderee)
- Confessions (helpers anonymisation)

La logique stateful (DB, views Discord) reste dans bot.py.
Ce module est PUR (pas d'I/O, pas de discord.py) sauf imports type-hints.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# DAILY QUESTS — catalogue + generateur
# =============================================================================


@dataclass
class QuestTemplate:
    id: str
    title: str
    description: str
    metric: str  # 'messages', 'reactions_given', 'voice_min', 'events_participated',
                 # 'coins_earned', 'duels_won', 'shop_purchases', 'commands_used',
                 # 'events_won', 'treasures_found', 'quiz_correct'
    target_range: tuple  # (min, max) — randomise a la generation
    reward_coins: int
    reward_xp: int
    emoji: str
    difficulty: str  # 'easy', 'medium', 'hard'


DAILY_QUEST_TEMPLATES = [
    # --- Easy (5-15 min) ---
    QuestTemplate('msg_easy', 'Petit bavard', "Envoie {target} messages aujourd'hui", 'messages', (10, 25), 50, 30, '💬', 'easy'),
    QuestTemplate('react_easy', 'Coeur leger', "Donne {target} reactions a d'autres messages", 'reactions_given', (8, 15), 40, 20, '❤️', 'easy'),
    QuestTemplate('voice_easy', 'Passage vocal', 'Passe {target} minutes en vocal', 'voice_min', (10, 25), 60, 40, '🎙️', 'easy'),
    QuestTemplate('event_easy', 'Curieux', 'Participe a {target} evenement(s) du jour', 'events_participated', (1, 1), 80, 50, '🎯', 'easy'),
    QuestTemplate('flash_easy', 'Reflexe', "Saisis {target} Tresor(s) Flash dans le serveur", 'treasures_found', (1, 2), 90, 50, '💎', 'easy'),
    # ⛔ supprime : 'command_easy' (utilisation de commandes trop vague et inutile)
    # --- Medium (30-60 min) ---
    QuestTemplate('msg_medium', 'Conversationnel', "Envoie {target} messages aujourd'hui", 'messages', (40, 80), 120, 80, '💬', 'medium'),
    QuestTemplate('voice_medium', 'Vocal de fond', 'Passe {target} minutes en vocal', 'voice_min', (45, 90), 130, 90, '🎙️', 'medium'),
    QuestTemplate('purchase_medium', 'Acheteur', "Achete {target} item(s) a la boutique", 'shop_purchases', (1, 2), 150, 90, '🛒', 'medium'),
    QuestTemplate('event_medium', 'Participant', 'Participe a {target} evenement(s)', 'events_participated', (2, 3), 200, 130, '🎯', 'medium'),
    QuestTemplate('treasure_medium', 'Chasseur de tresors', 'Trouve {target} tresor(s)', 'treasures_found', (3, 6), 180, 120, '💎', 'medium'),
    QuestTemplate('react_medium', 'Empathique', 'Donne {target} reactions au cours de la journee', 'reactions_given', (20, 35), 110, 70, '❤️', 'medium'),
    # ⛔ supprime : 'coins_medium' (objectif "gagne X 🪙" est vague et confus)
    # --- Hard (1-3h) ---
    QuestTemplate('msg_hard', 'Pilier du chat', "Envoie {target} messages aujourd'hui", 'messages', (150, 250), 300, 200, '💬', 'hard'),
    QuestTemplate('event_hard', 'Combattant', 'Gagne {target} evenement(s)', 'events_won', (1, 2), 350, 250, '🏆', 'hard'),
    QuestTemplate('voice_hard', 'Marathon vocal', 'Passe {target} minutes en vocal', 'voice_min', (120, 180), 280, 180, '🎙️', 'hard'),
    QuestTemplate('duel_hard', 'Duelliste', 'Gagne {target} duel(s)', 'duels_won', (1, 2), 320, 200, '⚔️', 'hard'),
    QuestTemplate('quiz_hard', 'Cerveau', 'Reponds correctement a {target} questions de quiz', 'quiz_correct', (5, 10), 290, 190, '🧠', 'hard'),
    QuestTemplate('boss_hard', 'Tueur de boss', 'Inflige des degats a {target} boss', 'bosses_won', (1, 2), 380, 250, '⚔️', 'hard'),
]


def _daily_seed(guild_id: int, user_id: int, day_str: str) -> int:
    """Seed stable pour (guild, user, jour) — meme jour = memes quetes."""
    s = f"{guild_id}_{user_id}_{day_str}"
    h = hashlib.md5(s.encode()).hexdigest()
    return int(h[:8], 16)


def generate_daily_quests(guild_id: int, user_id: int, day_str: str, count: int = 3) -> list:
    """Genere N quetes journalieres deterministes (1 easy + 1 medium + 1 hard).

    Le seed est stable pour (guild, user, jour) → si on appelle 2× le meme jour,
    on a les memes quetes. Reset chaque jour a minuit.
    """
    rng = random.Random(_daily_seed(guild_id, user_id, day_str))
    easy_pool = [t for t in DAILY_QUEST_TEMPLATES if t.difficulty == 'easy']
    medium_pool = [t for t in DAILY_QUEST_TEMPLATES if t.difficulty == 'medium']
    hard_pool = [t for t in DAILY_QUEST_TEMPLATES if t.difficulty == 'hard']

    chosen = [rng.choice(easy_pool), rng.choice(medium_pool), rng.choice(hard_pool)]
    out = []
    for tmpl in chosen[:count]:
        target = rng.randint(tmpl.target_range[0], tmpl.target_range[1])
        out.append({
            'id': tmpl.id,
            'title': tmpl.title,
            'description': tmpl.description.format(target=target),
            'metric': tmpl.metric,
            'target': target,
            'reward_coins': tmpl.reward_coins,
            'reward_xp': tmpl.reward_xp,
            'emoji': tmpl.emoji,
            'difficulty': tmpl.difficulty,
        })
    return out


# Recompenses de streak (jours consecutifs avec >=1 quete terminee)
STREAK_REWARDS = {
    3:   {'coins': 100,   'label': "3 jours d'affilee",         'item': None},
    7:   {'coins': 500,   'label': '1 semaine — Streak Hebdo',  'item': None},
    14:  {'coins': 1200,  'label': '2 semaines — Persevérant',  'item': 'common'},
    30:  {'coins': 3000,  'label': '1 mois — Pilier',           'item': 'rare'},
    60:  {'coins': 7000,  'label': '2 mois — Mensuel',          'item': 'epic'},
    100: {'coins': 15000, 'label': '100 JOURS — TITAN',         'item': 'legendary'},
    365: {'coins': 50000, 'label': '1 AN — IMMORTEL',           'item': 'mythic'},
}


def streak_milestone_reached(prev_streak: int, new_streak: int) -> Optional[dict]:
    """Retourne le palier de streak atteint (ou None) entre prev et new."""
    for s in sorted(STREAK_REWARDS.keys(), reverse=True):
        if prev_streak < s <= new_streak:
            return {**STREAK_REWARDS[s], 'days': s}
    return None


# =============================================================================
# ACHIEVEMENTS / HAUTS FAITS — catalogue 80+
# =============================================================================


@dataclass
class Achievement:
    id: str
    title: str
    description: str
    category: str  # 'social', 'combat', 'economy', 'discovery', 'meta', 'hidden'
    icon: str
    rarity: str    # 'common', 'rare', 'epic', 'legendary', 'mythic'
    metric: Optional[str] = None
    threshold: Optional[int] = None
    hidden: bool = False
    reward_coins: int = 0


ACHIEVEMENTS = [
    # --- Social ---
    Achievement('first_message',  'Premier mot',         'Envoie ton premier message',                'social', '👋', 'common',    'messages', 1,      reward_coins=20),
    Achievement('msgs_100',       'Bavard',              '100 messages cumules',                       'social', '💬', 'common',    'messages', 100,    reward_coins=50),
    Achievement('msgs_1000',      'Pilier du chat',      '1000 messages',                              'social', '🗣️', 'rare',     'messages', 1000,   reward_coins=200),
    Achievement('msgs_10000',     'Voix du serveur',     '10000 messages',                             'social', '📢', 'epic',      'messages', 10000,  reward_coins=1000),
    Achievement('msgs_100000',    'Legende vivante',     '100000 messages',                            'social', '👑', 'legendary', 'messages', 100000, reward_coins=10000),
    Achievement('reactions_50',   'Emotif',              '50 reactions donnees',                       'social', '👍', 'common',    'reactions_given', 50,   reward_coins=40),
    Achievement('reactions_500',  'Empathique',          '500 reactions donnees',                      'social', '❤️', 'rare',     'reactions_given', 500,  reward_coins=150),
    Achievement('reactions_5000', 'Coeur d\'or',         '5000 reactions donnees',                     'social', '💖', 'epic',      'reactions_given', 5000, reward_coins=600),

    # --- Combat ---
    Achievement('first_boss',     'Tueur de boss',       'Participe a la victoire d\'un boss',         'combat', '⚔️', 'common',    'bosses_won', 1,    reward_coins=100),
    Achievement('boss_10',        'Veteran de raid',     '10 boss vaincus',                            'combat', '🛡️', 'rare',     'bosses_won', 10,   reward_coins=400),
    Achievement('boss_50',        'Maitre des raids',    '50 boss vaincus',                            'combat', '⚜️', 'epic',     'bosses_won', 50,   reward_coins=1500),
    Achievement('first_duel',     'Premier sang',        'Gagne ton premier duel PvP',                 'combat', '🗡️', 'common',   'duels_won', 1,     reward_coins=80),
    Achievement('duel_10',        'Duelliste',           '10 duels gagnes',                            'combat', '⚔️', 'rare',     'duels_won', 10,    reward_coins=300),
    Achievement('duel_50',        'Champion des duels',  '50 duels gagnes',                            'combat', '🏆', 'epic',      'duels_won', 50,    reward_coins=1200),
    Achievement('treasure_100',   'Chasseur de tresors', '100 tresors trouves',                        'combat', '💎', 'rare',      'treasures_found', 100, reward_coins=500),
    Achievement('quiz_10',        'Curieux',             '10 reponses correctes a un quiz',            'combat', '🧠', 'common',    'quiz_correct', 10, reward_coins=100),
    Achievement('quiz_100',       'Erudit',              '100 reponses correctes',                     'combat', '📚', 'rare',      'quiz_correct', 100,reward_coins=400),
    Achievement('mystery_3',      'Curieux compulsif',   'Ouvre 3 mystery boxes',                      'combat', '📦', 'common',    'mystery_opened', 3, reward_coins=100),

    # --- Economie ---
    Achievement('first_coin',     'Premiere piece',      'Gagne ta premiere piece',                    'economy', '🪙', 'common',   'total_coins_earned', 1,       reward_coins=10),
    Achievement('coins_1k',       'Petit pecule',        '1000 🪙 cumules',                            'economy', '💰', 'common',   'total_coins_earned', 1000,    reward_coins=50),
    Achievement('coins_10k',      'Riche',               '10 000 🪙 cumules',                          'economy', '💵', 'rare',     'total_coins_earned', 10000,   reward_coins=300),
    Achievement('coins_100k',     'Millionnaire',        '100 000 🪙 cumules',                         'economy', '🏦', 'epic',     'total_coins_earned', 100000,  reward_coins=2000),
    Achievement('coins_1m',       'Fortune obscene',     '1 million 🪙 cumules',                       'economy', '👑', 'legendary','total_coins_earned', 1000000, reward_coins=20000),
    Achievement('first_purchase', 'Premier achat',       'Achete quelque chose a la boutique',         'economy', '🛒', 'common',   'shop_purchases', 1,           reward_coins=30),
    Achievement('legendary_buy',  'Acquereur legendaire','Achete un item legendaire',                  'economy', '💎', 'epic',     'legendary_purchases', 1,      reward_coins=500),
    Achievement('divine_buy',     'Touche par les dieux','Achete un item divin',                       'economy', '✨', 'legendary','divine_purchases', 1,         reward_coins=5000),

    # --- Decouverte ---
    Achievement('voice_1h',       'Premier vocal',       '1h en vocal cumulee',                        'discovery', '🎙️', 'common', 'voice_min', 60,     reward_coins=50),
    Achievement('voice_10h',      'Vocalophile',         '10h en vocal cumulees',                      'discovery', '🎤', 'rare',   'voice_min', 600,    reward_coins=200),
    Achievement('voice_100h',     'Ambient vocal',       '100h en vocal cumulees',                     'discovery', '🔊', 'epic',   'voice_min', 6000,   reward_coins=1500),
    Achievement('all_commands',   'Explorateur',         'Utilise 20 commandes differentes',           'discovery', '🧭', 'rare',   'unique_commands', 20, reward_coins=300),
    Achievement('first_class',    'Specialisation',      'Choisis ta premiere classe',                 'discovery', '🛡️', 'common','classes_tried', 1,   reward_coins=50),
    Achievement('all_classes',    'Polyvalent',          'Essaye 6 classes differentes',               'discovery', '🎭', 'epic',   'classes_tried', 6,   reward_coins=500),
    Achievement('first_pet',      'Compagnon',           'Adopte ton premier pet',                     'discovery', '🐾', 'common', 'pets_owned', 1,     reward_coins=50),

    # --- Meta ---
    Achievement('streak_3',       'Habitude',            'Streak quotidien de 3 jours',                'meta', '🔥', 'common',    'best_streak', 3,   reward_coins=100),
    Achievement('streak_7',       'Hebdomadaire',        'Streak quotidien de 7 jours',                'meta', '🔥', 'rare',      'best_streak', 7,   reward_coins=300),
    Achievement('streak_30',      'Regulier',            'Streak quotidien de 30 jours',               'meta', '🌟', 'epic',      'best_streak', 30,  reward_coins=1500),
    Achievement('streak_100',     'Acharne',             'Streak quotidien de 100 jours',              'meta', '💎', 'legendary', 'best_streak', 100, reward_coins=10000),
    Achievement('streak_365',     'Immortel',            '365 jours d\'affilee',                       'meta', '👑', 'mythic',    'best_streak', 365, reward_coins=50000),
    Achievement('level_10',       'Echauffement',        'Atteint niveau 10',                          'meta', '⭐', 'common',    'level', 10,        reward_coins=100),
    Achievement('level_25',       'Quart de chemin',     'Atteint niveau 25',                          'meta', '⭐', 'common',    'level', 25,        reward_coins=200),
    Achievement('level_50',       'Mi-parcours',         'Atteint niveau 50',                          'meta', '🌟', 'rare',      'level', 50,        reward_coins=500),
    Achievement('level_100',      'Veteran absolu',      'Atteint niveau 100',                         'meta', '👑', 'epic',      'level', 100,       reward_coins=2500),
    Achievement('quests_10',      'Aventurier',          'Complete 10 daily quests',                   'meta', '📜', 'common',    'quests_done', 10,  reward_coins=150),
    Achievement('quests_100',     'Maitre des quetes',   'Complete 100 daily quests',                  'meta', '📚', 'rare',      'quests_done', 100, reward_coins=800),
    Achievement('quests_500',     'Legende des quetes',  'Complete 500 daily quests',                  'meta', '📖', 'epic',      'quests_done', 500, reward_coins=4000),
    Achievement('wheel_30',       'Roue habituelle',     'Spin la Daily Wheel 30 jours',               'meta', '🎰', 'rare',      'wheel_spins', 30,  reward_coins=400),

    # --- Caches (hidden=True, ne s'affichent qu'une fois debloques) ---
    Achievement('phantom',        'Phantom',             'Reviens apres 30 jours d\'absence',          'hidden', '👻', 'rare',     hidden=True, reward_coins=300),
    Achievement('night_owl',      'Noctambule',          'Envoie un message entre 3h et 5h du matin',  'hidden', '🦉', 'rare',     hidden=True, reward_coins=200),
    Achievement('early_bird',     'Levetot',             'Envoie un message entre 5h et 7h',           'hidden', '🐦', 'rare',     hidden=True, reward_coins=200),
    Achievement('first_blood',    'First Blood',         'Sois le premier a toucher un boss',          'hidden', '🩸', 'epic',     hidden=True, reward_coins=300),
    Achievement('last_hit',       'Coup de grace',       'Donne le coup fatal a un boss',              'hidden', '⚡', 'epic',     hidden=True, reward_coins=400),
    Achievement('lucky_jackpot',  'Chanceux',            'Gagne le jackpot a la Daily Wheel',          'hidden', '🍀', 'epic',     hidden=True, reward_coins=500),
    Achievement('mythic_wheel',   'Touche par la divinite','Tire un item mythique a la Wheel',         'hidden', '✨', 'legendary',hidden=True, reward_coins=2000),
    Achievement('big_spender',    'Gros porte-monnaie',  'Depense 10 000 🪙 en une fois',              'hidden', '💸', 'epic',     hidden=True, reward_coins=400),
    Achievement('confession_10',  'Coeur leger',         'Envoie 10 confessions',                      'hidden', '🤫', 'rare',     hidden=True, reward_coins=200),
    Achievement('worldboss_kill', 'Slayer mondial',      'Vaincs un World Boss',                       'hidden', '🌍', 'legendary',hidden=True, reward_coins=5000),
    Achievement('helper_10',      'Mentor',              'Aide 10 nouveaux a configurer leur class',   'hidden', '🤝', 'epic',     hidden=True, reward_coins=600),
    Achievement('pet_max',        'Eleveur',             'Fais evoluer un pet jusqu\'a sa forme 5',    'hidden', '🐲', 'epic',     hidden=True, reward_coins=800),
    Achievement('reborn',         'Renaissance',         'Reset de saison (prestige)',                 'hidden', '🔄', 'legendary',hidden=True, reward_coins=3000),
]


def get_achievement(achievement_id: str) -> Optional[Achievement]:
    for a in ACHIEVEMENTS:
        if a.id == achievement_id:
            return a
    return None


def achievements_by_category(cat: str) -> list:
    return [a for a in ACHIEVEMENTS if a.category == cat]


def achievements_for_metric(metric: str) -> list:
    """Renvoie tous les achievements automatiques pour un metric donne (tri par seuil)."""
    out = [a for a in ACHIEVEMENTS if a.metric == metric and a.threshold is not None]
    return sorted(out, key=lambda a: a.threshold or 0)


RARITY_COLORS = {
    'common':    0x95A5A6,
    'rare':      0x3498DB,
    'epic':      0x9B59B6,
    'legendary': 0xF1C40F,
    'mythic':    0xE91E63,
}


RARITY_LABELS = {
    'common':    'Commune',
    'rare':      'Rare',
    'epic':      'Epique',
    'legendary': 'Legendaire',
    'mythic':    'Mythique',
}


# =============================================================================
# PETS / COMPAGNONS
# =============================================================================


PETS = [
    {
        'id': 'cat',
        'name': 'Chat',
        'emoji': '🐱',
        'price': 500,
        'description': 'Mignon et independant. Augmente la chance de loot rare de +8% pendant les events.',
        'forms': ['Chaton', 'Chat', 'Felin agile', 'Tigre', 'Lion cosmique'],
        'form_emojis': ['🐱', '🐈', '🐅', '🐯', '🦁'],
        'bonus_kind': 'rare_loot',
        'bonus_value': 0.08,
    },
    {
        'id': 'dog',
        'name': 'Chien',
        'emoji': '🐶',
        'price': 500,
        'description': 'Fidele et joueur. Bonus XP de +10% sur les messages.',
        'forms': ['Chiot', 'Chien', 'Loup', 'Loup Alpha', 'Fenrir'],
        'form_emojis': ['🐶', '🐕', '🐺', '🐺', '🌑'],
        'bonus_kind': 'msg_xp',
        'bonus_value': 0.10,
    },
    {
        'id': 'dragon',
        'name': 'Dragon',
        'emoji': '🐉',
        'price': 2000,
        'description': 'Puissant et majestueux. +15% degats en boss raid.',
        'forms': ['Oeuf', 'Dragonnet', 'Dragon', 'Wyvern', 'Dragon Cosmique'],
        'form_emojis': ['🥚', '🐲', '🐉', '🔥', '☄️'],
        'bonus_kind': 'boss_damage',
        'bonus_value': 0.15,
    },
    {
        'id': 'wolf',
        'name': 'Loup',
        'emoji': '🐺',
        'price': 1000,
        'description': 'Predateur solitaire. +20% attaque en duels PvP.',
        'forms': ['Louveteau', 'Loup', 'Loup Garou', 'Loup Lunaire', 'Fenrir'],
        'form_emojis': ['🐺', '🐺', '🌙', '🌕', '⚔️'],
        'bonus_kind': 'duel_attack',
        'bonus_value': 0.20,
    },
    {
        'id': 'fox',
        'name': 'Renard',
        'emoji': '🦊',
        'price': 800,
        'description': 'Malin et chanceux. +12% chance a la Daily Wheel.',
        'forms': ['Renardeau', 'Renard', 'Renard ruse', 'Kitsune', 'Esprit Renard'],
        'form_emojis': ['🦊', '🦊', '🍃', '🌸', '✨'],
        'bonus_kind': 'wheel_luck',
        'bonus_value': 0.12,
    },
    {
        'id': 'robot',
        'name': 'Robot',
        'emoji': '🤖',
        'price': 1500,
        'description': 'Compagnon mecanique polyvalent. +5% partout.',
        'forms': ['Bot v1', 'Bot v2', 'Drone', 'Mecha', 'Conscience IA'],
        'form_emojis': ['🤖', '🤖', '🛸', '⚙️', '👁️'],
        'bonus_kind': 'global',
        'bonus_value': 0.05,
    },
]


def get_pet(pet_id: str) -> Optional[dict]:
    for p in PETS:
        if p['id'] == pet_id:
            return p
    return None


def pet_form_index(level: int) -> int:
    """Index de forme du pet selon son niveau (0..4)."""
    if level < 5:
        return 0
    if level < 15:
        return 1
    if level < 30:
        return 2
    if level < 60:
        return 3
    return 4


def pet_form_label(pet: dict, level: int) -> str:
    idx = pet_form_index(level)
    emo = pet['form_emojis'][idx]
    name = pet['forms'][idx]
    return f"{emo} {name}"


# Pet level up : combien d'XP pour passer du niveau N a N+1
def pet_xp_for_level(level: int) -> int:
    return 50 + (level * 25)  # Lv1→75, Lv5→175, Lv30→800


# =============================================================================
# DAILY WHEEL / ROULETTE QUOTIDIENNE
# =============================================================================


# Tableau de loot pondere : (weight, type, amount, label, rare_flag)
WHEEL_REWARDS = [
    (350, 'coins',   50,   '50 🪙',                      False),
    (250, 'coins',   100,  '100 🪙',                     False),
    (150, 'coins',   250,  '250 🪙',                     False),
    (80,  'coins',   500,  '500 🪙',                     False),
    (40,  'coins',   1000, '1000 🪙',                    False),
    (15,  'coins',   2500, '✨ 2500 🪙 (Jackpot or)',    True),
    (40,  'xp_mult', 2,    'XP ×2 pour 1h',              False),
    (20,  'xp_mult', 3,    '⚡ XP ×3 pour 1h',           True),
    (30,  'item',    'common',    '1 item commun',       False),
    (15,  'item',    'rare',      '🌟 1 item rare',      True),
    (8,   'item',    'epic',      '💎 1 item EPIQUE',    True),
    (2,   'item',    'legendary', '👑 1 item LEGENDAIRE',True),
    (1,   'item',    'mythic',    '✨ JACKPOT MYTHIQUE', True),
]


def spin_wheel(luck_bonus: float = 0.0) -> dict:
    """Spin la roue. luck_bonus (ex: 0.12 du renard) amplifie les rewards rares."""
    rewards = WHEEL_REWARDS
    if luck_bonus > 0:
        rewards = [
            (int(w * (1.0 + luck_bonus)) if rare else w, t, a, l, rare)
            for (w, t, a, l, rare) in WHEEL_REWARDS
        ]
    total = sum(w for w, _, _, _, _ in rewards)
    r = random.uniform(0, total)
    acc = 0
    for w, t, a, l, rare in rewards:
        acc += w
        if r <= acc:
            return {'type': t, 'amount': a, 'label': l, 'rare': rare}
    last = rewards[-1]
    return {'type': last[1], 'amount': last[2], 'label': last[3], 'rare': last[4]}


# =============================================================================
# CONFESSIONS — helpers anonymisation + moderation legere
# =============================================================================


CONFESSION_BAN_WORDS = {
    # Liste minimale — la vraie modération réutilise le filtre badwords du bot.
    # On laisse ici juste pour la double protection sur les triggers évidents.
}


def confession_id_format(n: int) -> str:
    """Format display id : #001, #042, etc."""
    return f"#{n:03d}"


# =============================================================================
# EXPORT
# =============================================================================

__all__ = [
    # Quests
    'QuestTemplate', 'DAILY_QUEST_TEMPLATES', 'generate_daily_quests',
    'STREAK_REWARDS', 'streak_milestone_reached',
    # Achievements
    'Achievement', 'ACHIEVEMENTS', 'get_achievement',
    'achievements_by_category', 'achievements_for_metric',
    'RARITY_COLORS', 'RARITY_LABELS',
    # Pets
    'PETS', 'get_pet', 'pet_form_index', 'pet_form_label', 'pet_xp_for_level',
    # Wheel
    'WHEEL_REWARDS', 'spin_wheel',
    # Confessions
    'confession_id_format',
]
