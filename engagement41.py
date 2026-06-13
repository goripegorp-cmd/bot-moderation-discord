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
    QuestTemplate('react_easy', 'Reactif', "Donne {target} reactions a d'autres messages", 'reactions_given', (8, 15), 40, 20, '👍', 'easy'),
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
    QuestTemplate('react_medium', 'Soutien', 'Donne {target} reactions au cours de la journee', 'reactions_given', (20, 35), 110, 70, '🌟', 'medium'),
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


def next_streak_milestone(current_streak: int) -> Optional[dict]:
    """Prochain palier de streak au-dessus du streak actuel (None si max atteint)."""
    for s in sorted(STREAK_REWARDS.keys()):
        if current_streak < s:
            return {**STREAK_REWARDS[s], 'days': s}
    return None


def streak_progress_line(current_streak: int) -> str:
    """Ligne MOTIVANTE : prochain palier + barre de progression + récompense.

    Phase 237 — rend le streak « vivant » (on voit l'objectif et le gain, pas
    juste un nombre). FAIL-OPEN : renvoie '' en cas d'erreur."""
    try:
        cur = max(0, int(current_streak or 0))
        nxt = next_streak_milestone(cur)
        if not nxt:
            return "🌟 **Palier max atteint (IMMORTEL) — légende vivante !**"
        prevs = [s for s in STREAK_REWARDS if s <= cur]
        base = max(prevs) if prevs else 0
        target = int(nxt['days'])
        span = max(1, target - base)
        done = max(0, cur - base)
        frac = max(0.0, min(1.0, done / span))
        seg = 10
        filled = max(0, min(seg, int(round(frac * seg))))
        bar = "▰" * filled + "▱" * (seg - filled)
        remaining = max(0, target - cur)
        item = nxt.get('item')
        reward = f"+{int(nxt['coins']):,} 🪙" + (f" + loot {item}" if item else "")
        return (
            f"⏭️ Prochain palier : **{nxt['label']}** dans `{remaining} j`\n"
            f"{bar}  ({reward})"
        )
    except Exception:
        return ""


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
    Achievement('reactions_500',  'Soutien',             '500 reactions donnees',                      'social', '🌟', 'rare',     'reactions_given', 500,  reward_coins=150),
    Achievement('reactions_5000', 'Bienveillant',        '5000 reactions donnees',                     'social', '💯', 'epic',      'reactions_given', 5000, reward_coins=600),

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


# =============================================================================
# Phase 235.26 — FAMILIERS PAR ŒUFS (~50 au total). Obtenables UNIQUEMENT via
# œufs à faire éclore (egg_only=True → exclus de /pet buy). Raretés TRÈS dures :
# les meilleurs (légendaires/mythiques) sortent d'œufs rarissimes, sur le long
# terme. Bonus volontairement MODESTES (rétention long terme = valeur #1).
# perk_type : 'passive' (auto pendant le combat) ou 'active' (bouton 🐾). Le
# câblage fin des perks mixtes vient en 235.26c — ici tout réutilise déjà le
# bonus passif existant (_apply_pet_bonus) + le bouton 🐾 (_handle_pet_assist).
# =============================================================================
def _ep(pid, name, emoji, rarity, kind, val, desc, perk='passive'):
    return {
        'id': pid, 'name': name, 'emoji': emoji, 'rarity': rarity,
        'bonus_kind': kind, 'bonus_value': val, 'description': desc,
        'egg_only': True, 'perk_type': perk,
    }


PETS.extend([
    # ── 🟢 COMMUN (œuf commun) — bonus 0.03–0.05 ──
    _ep('bunny', 'Lapin', '🐰', 'common', 'global', 0.03, 'Petit porte-bonheur. +3% partout.'),
    _ep('chick', 'Poussin', '🐤', 'common', 'msg_xp', 0.04, 'Piaille gaiement. +4% XP messages.'),
    _ep('mouse', 'Souris', '🐭', 'common', 'rare_loot', 0.04, 'Fouineuse. +4% chance de loot rare.'),
    _ep('frog', 'Grenouille', '🐸', 'common', 'global', 0.03, 'Saut porte-chance. +3% partout.'),
    _ep('hedgehog', 'Hérisson', '🦔', 'common', 'boss_damage', 0.04, 'Piquant. +4% dégâts sur les boss.'),
    _ep('duck', 'Canard', '🦆', 'common', 'wheel_luck', 0.05, 'Chançard. +5% à la roue.'),
    _ep('turtle', 'Tortue', '🐢', 'common', 'boss_damage', 0.03, 'Lente mais sûre. +3% dégâts boss.'),
    _ep('bee', 'Abeille', '🐝', 'common', 'msg_xp', 0.05, 'Travailleuse. +5% XP messages.'),
    _ep('snail', 'Escargot', '🐌', 'common', 'rare_loot', 0.03, 'Traîne mais trouve. +3% loot rare.'),
    _ep('piglet', 'Cochon', '🐷', 'common', 'global', 0.04, 'Gourmand chançard. +4% partout.'),
    _ep('crab', 'Crabe', '🦀', 'common', 'boss_damage', 0.04, 'Pince solide. +4% dégâts boss.'),
    _ep('sparrow', 'Moineau', '🐦', 'common', 'wheel_luck', 0.04, 'Vif. +4% à la roue.'),
    _ep('ladybug', 'Coccinelle', '🐞', 'common', 'wheel_luck', 0.05, 'Porte-bonheur. +5% à la roue.'),
    _ep('ant', 'Fourmi', '🐜', 'common', 'msg_xp', 0.04, 'Bosseuse. +4% XP messages.'),
    # ── 🔵 RARE (œuf rare) — bonus 0.06–0.08 ──
    _ep('owl', 'Hibou', '🦉', 'rare', 'msg_xp', 0.07, 'Sage nocturne. +7% XP messages.'),
    _ep('blackcat', 'Chat noir', '🐈‍⬛', 'rare', 'wheel_luck', 0.08, 'Mystérieux. +8% à la roue.'),
    _ep('panda', 'Panda', '🐼', 'rare', 'boss_damage', 0.06, 'Calme et fort. +6% dégâts boss.'),
    _ep('penguin', 'Manchot', '🐧', 'rare', 'global', 0.06, 'Glisse vers la chance. +6% partout.'),
    _ep('koala', 'Koala', '🐨', 'rare', 'rare_loot', 0.07, 'Agrippe les trésors. +7% loot rare.'),
    _ep('boar', 'Sanglier', '🐗', 'rare', 'duel_attack', 0.08, 'Charge brutale. +8% attaque en duel.'),
    _ep('ram', 'Bélier', '🐏', 'rare', 'boss_damage', 0.07, 'Coup de tête. +7% dégâts boss.'),
    _ep('octopus', 'Pieuvre', '🐙', 'rare', 'rare_loot', 0.07, 'Huit bras fouineurs. +7% loot rare.'),
    _ep('parrot', 'Perroquet', '🦜', 'rare', 'wheel_luck', 0.07, 'Répète la chance. +7% à la roue.'),
    _ep('swan', 'Cygne', '🦢', 'rare', 'global', 0.06, 'Élégant. +6% partout.'),
    _ep('bat', 'Chauve-souris', '🦇', 'rare', 'boss_damage', 0.07, 'Frappe dans le noir. +7% dégâts boss.', 'active'),
    _ep('raccoon', 'Raton laveur', '🦝', 'rare', 'rare_loot', 0.08, 'Voleur malin. +8% loot rare.'),
    # ── 🟣 ÉPIQUE (œuf épique) — bonus 0.10–0.12 ──
    _ep('tiger', 'Tigre', '🐅', 'epic', 'boss_damage', 0.11, 'Prédateur royal. +11% dégâts boss.'),
    _ep('eagle', 'Aigle', '🦅', 'epic', 'duel_attack', 0.12, 'Fond sur sa proie. +12% attaque.', 'active'),
    _ep('shark', 'Requin', '🦈', 'epic', 'boss_damage', 0.12, 'Mâchoire d\'acier. +12% dégâts boss.', 'active'),
    _ep('unicorn', 'Licorne', '🦄', 'epic', 'global', 0.10, 'Magie pure. +10% partout.'),
    _ep('peacock', 'Paon', '🦚', 'epic', 'wheel_luck', 0.12, 'Éclatant. +12% à la roue.'),
    _ep('gorilla', 'Gorille', '🦍', 'epic', 'duel_attack', 0.11, 'Force brute. +11% attaque.'),
    _ep('lion', 'Lion', '🦁', 'epic', 'boss_damage', 0.11, 'Roi de l\'arène. +11% dégâts boss.'),
    _ep('rhino', 'Rhinocéros', '🦏', 'epic', 'boss_damage', 0.12, 'Charge imparable. +12% dégâts boss.', 'active'),
    _ep('scorpion', 'Scorpion', '🦂', 'epic', 'boss_damage', 0.10, 'Dard venimeux. +10% dégâts boss.', 'active'),
    _ep('flamingo', 'Flamant', '🦩', 'epic', 'rare_loot', 0.11, 'Rose et rare. +11% loot rare.'),
    # ── 🟠 LÉGENDAIRE (œuf légendaire, rarissime) — bonus 0.15–0.18 ──
    _ep('phoenix', 'Phénix', '🔥', 'legendary', 'boss_damage', 0.16, 'Renaît des cendres. +16% dégâts boss.', 'active'),
    _ep('kraken', 'Kraken', '🦑', 'legendary', 'boss_damage', 0.17, 'Terreur des abysses. +17% dégâts boss.', 'active'),
    _ep('griffin', 'Griffon', '🦅', 'legendary', 'duel_attack', 0.16, 'Bête mythique. +16% attaque.', 'active'),
    _ep('wendigo', 'Wendigo', '🦌', 'legendary', 'global', 0.15, 'Esprit affamé. +15% partout.'),
    _ep('golem', 'Golem', '🗿', 'legendary', 'boss_damage', 0.15, 'Roche vivante. +15% dégâts boss.'),
    _ep('serpent', 'Serpent céleste', '🐍', 'legendary', 'rare_loot', 0.17, 'Gardien des trésors. +17% loot rare.'),
    # ── 🌈 MYTHIQUE (œuf mythique, ultra-rare) — bonus 0.22–0.25 ──
    _ep('celestialdragon', 'Dragon Céleste', '☄️', 'mythic', 'boss_damage', 0.25, 'Le plus rare des familiers. +25% dégâts boss.', 'active'),
    _ep('cosmicfox', 'Renard Cosmique', '🌌', 'mythic', 'global', 0.22, 'Esprit des étoiles. +22% partout.'),
])


# Phase 235.26 : helpers de catégorisation (réutilisés par pet_eggs.py + /pet)
def pets_by_rarity(rarity: str) -> list:
    return [p for p in PETS if p.get('rarity') == rarity and p.get('egg_only')]


def buyable_pets() -> list:
    """Pets achetables en boutique (les 6 d'origine ; les pets d'œuf en sont exclus)."""
    return [p for p in PETS if not p.get('egg_only')]


def get_pet(pet_id: str) -> Optional[dict]:
    for p in PETS:
        if p['id'] == pet_id:
            return p
    return None


# =============================================================================
# Phase 268 — PERK PASSIF DOUX (non-combat) : petit bonus de RENTE selon la
# rareté du familier équipé. Volontairement MODESTE et PLAFONNÉ (rétention #1 :
# n'écrase pas l'équilibre, ne punit personne). Le bonus est en ÉCLATS (monnaie
# cosmétique de La Cité) → équilibre SÉPARÉ des pièces de gameplay. Centralisé
# ici (1 seule source de vérité), lu par bot.py (helper _pet_rente_bonus) et
# affiché dans le panneau du familier + Revenus/Ma Fortune.
# Les pets achetables (sans clé 'rarity') sont traités comme 'common'.
# =============================================================================
PET_RENTE_BONUS_BY_RARITY = {
    'common':    1,
    'rare':      1,
    'epic':      2,
    'legendary': 3,
    'mythic':    5,
}


def pet_rente_bonus(pet: Optional[dict]) -> int:
    """Bonus de rente (en Éclats) du familier équipé, selon sa rareté.
    Fail-safe : pas de pet → 0. Pet sans rareté (achetable) → 'common'."""
    if not pet:
        return 0
    rarity = pet.get('rarity') or 'common'
    return int(PET_RENTE_BONUS_BY_RARITY.get(rarity, 1))


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
    # Phase 235.26 : DÉFENSIF — les familiers d'œuf n'ont pas les 5 formes
    # d'évolution (forms/form_emojis). On retombe alors sur nom+emoji de base.
    forms = pet.get('forms') or [pet.get('name', 'Familier')]
    emojis = pet.get('form_emojis') or [pet.get('emoji', '🐾')]
    idx = pet_form_index(level)
    name = forms[idx] if idx < len(forms) else forms[-1]
    emo = emojis[idx] if idx < len(emojis) else emojis[-1]
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
    'PET_RENTE_BONUS_BY_RARITY', 'pet_rente_bonus',
    # Wheel
    'WHEEL_REWARDS', 'spin_wheel',
    # Confessions
    'confession_id_format',
]
