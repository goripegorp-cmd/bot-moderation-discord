"""
engagement47.py - Phase 47 : moteur d'engagement LONG TERME (annees).

Contient les catalogues + helpers pour :
- SAISONS (3 mois chacune, 20 paliers de Season Pass)
- PRESTIGE (renaissance level 100, jusqu'a rank 25 sur 4+ ans)
- FACTIONS (4 factions de reputation, 7 paliers, Legendaire = 2-3 ans)
- WEEKLY QUESTS (5 par semaine, plus difficiles que les daily)
- MONTHLY MEGA QUESTS (1 par mois, defi enorme)

Toutes les structures sont PURES (zero dependance discord.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# SAISONS - 3 mois chacune, theme + Season Pass 20 paliers
# =============================================================================

@dataclass
class SeasonDef:
    id: str            # 'spring_2026', 'summer_2026', etc.
    name: str
    emoji: str
    start_month: int   # 1, 4, 7, 10
    color: int
    theme_role_name: str  # "Eclat du Printemps 2026" etc.


# Saisons : on tourne sur 4 par an. Chaque saison a son theme + couleur + role
SEASONS = [
    SeasonDef("spring", "Printemps",    "🌸", 3, 0xFF7AC3, "Eclat du Printemps"),
    SeasonDef("summer", "Ete",          "☀️", 6, 0xFFB347, "Souffle d'Ete"),
    SeasonDef("autumn", "Automne",      "🍂", 9, 0xC0392B, "Lumiere d'Automne"),
    SeasonDef("winter", "Hiver",        "❄️", 12, 0x3498DB, "Givre d'Hiver"),
]


def current_season(month: int) -> SeasonDef:
    """Retourne la saison courante a partir du mois (1-12)."""
    if 3 <= month <= 5:
        return SEASONS[0]   # printemps
    if 6 <= month <= 8:
        return SEASONS[1]   # ete
    if 9 <= month <= 11:
        return SEASONS[2]   # automne
    return SEASONS[3]       # hiver (dec/jan/fev)


def current_season_id(year: int, month: int) -> str:
    """Identifiant unique pour la saison : 'spring_2026'."""
    s = current_season(month)
    # L'hiver enjambe deux annees ; on prend l'annee d'octobre/decembre
    yref = year if s.id != "winter" or month >= 12 else year - 1
    return f"{s.id}_{yref}"


# Season Pass : 20 paliers de points (cumules sur la saison)
# Mix : petits gains (1-10), gros gains (15, 20) qui donnent les ROLES SAISONNIERS
SEASON_PASS_TIERS = [
    {"tier": 1,  "points": 100,    "reward_coins": 50,    "label": "Bourgeon"},
    {"tier": 2,  "points": 250,    "reward_coins": 100,   "label": "Petale"},
    {"tier": 3,  "points": 500,    "reward_coins": 150,   "label": "Brindille"},
    {"tier": 4,  "points": 1000,   "reward_coins": 250,   "label": "Branche"},
    {"tier": 5,  "points": 2000,   "reward_coins": 400,   "label": "Petit Arbre", "extra": "wheel_token"},
    {"tier": 6,  "points": 3500,   "reward_coins": 600,   "label": "Arbre"},
    {"tier": 7,  "points": 5000,   "reward_coins": 800,   "label": "Forestier"},
    {"tier": 8,  "points": 7500,   "reward_coins": 1200,  "label": "Garde Forestier"},
    {"tier": 9,  "points": 10000,  "reward_coins": 1500,  "label": "Sylvain"},
    {"tier": 10, "points": 14000,  "reward_coins": 2000,  "label": "Sage", "extra": "pet_token"},
    {"tier": 11, "points": 18000,  "reward_coins": 2500,  "label": "Erudit"},
    {"tier": 12, "points": 23000,  "reward_coins": 3000,  "label": "Mentor"},
    {"tier": 13, "points": 29000,  "reward_coins": 3500,  "label": "Vénérable"},
    {"tier": 14, "points": 35000,  "reward_coins": 4000,  "label": "Ascensionne"},
    {"tier": 15, "points": 42000,  "reward_coins": 5000,  "label": "Eclat saisonnier", "extra": "season_role"},
    {"tier": 16, "points": 50000,  "reward_coins": 6000,  "label": "Astre Discret"},
    {"tier": 17, "points": 60000,  "reward_coins": 7500,  "label": "Etoile Filante"},
    {"tier": 18, "points": 72000,  "reward_coins": 9000,  "label": "Constellation"},
    {"tier": 19, "points": 86000,  "reward_coins": 12000, "label": "Galaxie"},
    {"tier": 20, "points": 100000, "reward_coins": 15000, "label": "Cosmos saisonnier", "extra": "season_role_legendary"},
]


def get_tier_by_points(points: int) -> int:
    """Retourne le palier max atteint (0-20) pour N points."""
    last = 0
    for t in SEASON_PASS_TIERS:
        if points >= t["points"]:
            last = t["tier"]
        else:
            break
    return last


def points_for_next_tier(points: int) -> tuple:
    """Retourne (palier_actuel, points_restants, palier_cible). 0 si max."""
    current = get_tier_by_points(points)
    if current >= 20:
        return (current, 0, current)
    target = SEASON_PASS_TIERS[current]  # current=0 means next is tier 1 = index 0
    if current >= 1:
        target = SEASON_PASS_TIERS[current]  # index = current means tier current+1
    return (current, target["points"] - points, target["tier"])


# =============================================================================
# PRESTIGE - renaissance au niveau 100
# =============================================================================

# Bonus permanents par rang de prestige (additif)
PRESTIGE_RANKS = [
    {"rank": 0,  "name": "Mortel",     "emoji": "",   "color": 0x95A5A6, "xp_bonus": 0.00, "coins_bonus": 0.00},
    {"rank": 1,  "name": "Argente",    "emoji": "⚪", "color": 0xC0C0C0, "xp_bonus": 0.02, "coins_bonus": 0.01},
    {"rank": 2,  "name": "Argente II", "emoji": "⚪", "color": 0xC0C0C0, "xp_bonus": 0.04, "coins_bonus": 0.02},
    {"rank": 3,  "name": "Argente III","emoji": "⚪", "color": 0xC0C0C0, "xp_bonus": 0.06, "coins_bonus": 0.03},
    {"rank": 4,  "name": "Argente IV", "emoji": "⚪", "color": 0xC0C0C0, "xp_bonus": 0.08, "coins_bonus": 0.04},
    {"rank": 5,  "name": "Or",         "emoji": "🟡", "color": 0xFFD700, "xp_bonus": 0.12, "coins_bonus": 0.06},
    {"rank": 6,  "name": "Or II",      "emoji": "🟡", "color": 0xFFD700, "xp_bonus": 0.15, "coins_bonus": 0.08},
    {"rank": 7,  "name": "Or III",     "emoji": "🟡", "color": 0xFFD700, "xp_bonus": 0.18, "coins_bonus": 0.10},
    {"rank": 8,  "name": "Or IV",      "emoji": "🟡", "color": 0xFFD700, "xp_bonus": 0.21, "coins_bonus": 0.12},
    {"rank": 9,  "name": "Or V",       "emoji": "🟡", "color": 0xFFD700, "xp_bonus": 0.25, "coins_bonus": 0.14},
    {"rank": 10, "name": "Diamant",    "emoji": "💎", "color": 0x00BFFF, "xp_bonus": 0.30, "coins_bonus": 0.18},
    {"rank": 12, "name": "Diamant II", "emoji": "💎", "color": 0x00BFFF, "xp_bonus": 0.35, "coins_bonus": 0.22},
    {"rank": 15, "name": "Diamant III","emoji": "💎", "color": 0x00BFFF, "xp_bonus": 0.42, "coins_bonus": 0.28},
    {"rank": 18, "name": "Mythique",   "emoji": "💜", "color": 0x9B59B6, "xp_bonus": 0.50, "coins_bonus": 0.35},
    {"rank": 22, "name": "Mythique II","emoji": "💜", "color": 0x9B59B6, "xp_bonus": 0.60, "coins_bonus": 0.42},
    {"rank": 25, "name": "Cosmique",   "emoji": "🌌", "color": 0xE91E63, "xp_bonus": 0.75, "coins_bonus": 0.50},
]


def get_prestige_def(rank: int) -> dict:
    """Retourne la def la plus haute atteinte pour ce rank."""
    last = PRESTIGE_RANKS[0]
    for p in PRESTIGE_RANKS:
        if p["rank"] <= rank:
            last = p
        else:
            break
    return last


def prestige_bonus_xp(rank: int) -> float:
    return get_prestige_def(rank)["xp_bonus"]


def prestige_bonus_coins(rank: int) -> float:
    return get_prestige_def(rank)["coins_bonus"]


# =============================================================================
# FACTIONS - 4 factions, 7 paliers de reputation
# =============================================================================

FACTIONS = [
    {
        "id": "garde",
        "name": "Garde",
        "emoji": "🛡️",
        "color": 0xE74C3C,
        "description": "Reputation gagnee via Boss Raids, Duels et combats",
        "actions": ["bosses_won", "duels_won", "world_boss_attacks"],
    },
    {
        "id": "sage",
        "name": "Sage",
        "emoji": "📚",
        "color": 0x3498DB,
        "description": "Reputation gagnee via Quiz, Enigmes et savoir",
        "actions": ["quiz_correct", "riddles_won", "achievements_unlocked"],
    },
    {
        "id": "marchand",
        "name": "Marchand",
        "emoji": "💰",
        "color": 0xF1C40F,
        "description": "Reputation gagnee via Boutique, Trade et economie",
        "actions": ["shop_purchases", "coins_spent", "trades_done"],
    },
    {
        "id": "legende",
        "name": "Legende",
        "emoji": "🌟",
        "color": 0x9B59B6,
        "description": "Reputation gagnee via achievements rares et events epiques",
        "actions": ["epic_achievements", "season_top3", "world_boss_kills"],
    },
]


# 7 paliers de reputation - exponentiel pour que Legendaire = long
FACTION_TIERS = [
    {"tier": 0, "points": 0,      "name": "Inconnu",    "emoji": "❓"},
    {"tier": 1, "points": 500,    "name": "Allie",      "emoji": "🤝"},
    {"tier": 2, "points": 2000,   "name": "Ami",        "emoji": "🙂"},
    {"tier": 3, "points": 5000,   "name": "Honore",     "emoji": "⭐"},
    {"tier": 4, "points": 12000,  "name": "Revere",     "emoji": "🏅"},
    {"tier": 5, "points": 25000,  "name": "Exalte",     "emoji": "👑"},
    {"tier": 6, "points": 60000,  "name": "Legendaire", "emoji": "🌟"},
]


def get_faction(faction_id: str) -> Optional[dict]:
    for f in FACTIONS:
        if f["id"] == faction_id:
            return f
    return None


def faction_tier_from_points(points: int) -> dict:
    """Retourne le tier le plus haut pour N points."""
    last = FACTION_TIERS[0]
    for t in FACTION_TIERS:
        if points >= t["points"]:
            last = t
        else:
            break
    return last


def faction_points_to_next(points: int) -> tuple:
    """Retourne (tier_actuel_dict, points_restants, tier_cible_dict). None si max."""
    cur = faction_tier_from_points(points)
    if cur["tier"] >= 6:
        return (cur, 0, None)
    nxt = FACTION_TIERS[cur["tier"] + 1]
    return (cur, nxt["points"] - points, nxt)


# =============================================================================
# WEEKLY QUESTS - 5 par semaine, plus dures, reset lundi
# =============================================================================

@dataclass
class WeeklyQuestTemplate:
    id: str
    title: str
    description: str
    metric: str
    target_range: tuple
    reward_coins: int
    season_points: int   # bonus pour le Season Pass
    icon: str


WEEKLY_QUEST_TEMPLATES = [
    WeeklyQuestTemplate("w_msg_500",  "Pilier de la semaine", "Envoie {target} messages sur la semaine", "messages",          (400, 800),   1500, 300, "💬"),
    WeeklyQuestTemplate("w_voice_5h", "Voix de la semaine",   "Passe {target} minutes en vocal",         "voice_min",         (180, 360),   1200, 250, "🎙️"),
    WeeklyQuestTemplate("w_events_7", "Aventurier hebdo",     "Participe a {target} evenements",         "events_participated",(5, 10),     1800, 400, "🎯"),
    WeeklyQuestTemplate("w_bosses_3", "Chasseur de boss",     "Vaincs {target} boss",                    "bosses_won",        (2, 4),       2000, 500, "⚔️"),
    WeeklyQuestTemplate("w_quiz_25",  "Maitre des quiz",      "Reponds correctement a {target} questions","quiz_correct",     (15, 30),     1500, 350, "🧠"),
    WeeklyQuestTemplate("w_treasures","Trouve-trésors",       "Trouve {target} tresors / flash",         "treasures_found",   (10, 20),     1700, 350, "💎"),
    WeeklyQuestTemplate("w_duels_5",  "Duelliste",            "Gagne {target} duels PvP",                "duels_won",         (3, 7),       1600, 350, "⚔️"),
    WeeklyQuestTemplate("w_quests_5", "Maitre des taches",    "Termine {target} daily quests",           "quests_done",       (10, 18),     1400, 300, "📜"),
    WeeklyQuestTemplate("w_react_50", "Cœur géant",           "Donne {target} reactions",                "reactions_given",   (50, 100),    1000, 200, "❤️"),
    WeeklyQuestTemplate("w_wheel_5",  "Tournoyer",            "Spin la Daily Wheel {target} fois",       "wheel_spins",       (5, 7),       800,  150, "🎰"),
]


def generate_weekly_quests(guild_id: int, user_id: int, week_str: str, count: int = 5) -> list:
    """Genere N quetes hebdo deterministes pour (guild, user, week)."""
    import hashlib
    s = f"{guild_id}_{user_id}_{week_str}"
    seed = int(hashlib.md5(s.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    pool = list(WEEKLY_QUEST_TEMPLATES)
    rng.shuffle(pool)
    chosen = pool[:min(count, len(pool))]
    out = []
    for tmpl in chosen:
        target = rng.randint(tmpl.target_range[0], tmpl.target_range[1])
        out.append({
            "id": tmpl.id,
            "title": tmpl.title,
            "description": tmpl.description.format(target=target),
            "metric": tmpl.metric,
            "target": target,
            "reward_coins": tmpl.reward_coins,
            "season_points": tmpl.season_points,
            "icon": tmpl.icon,
        })
    return out


# =============================================================================
# MONTHLY MEGA QUESTS - 1 par mois, defi enorme
# =============================================================================

@dataclass
class MonthlyMegaTemplate:
    id: str
    title: str
    description: str
    metric: str
    target_range: tuple
    reward_coins: int
    season_points: int
    icon: str


MONTHLY_MEGA_TEMPLATES = [
    MonthlyMegaTemplate("m_msg_2k",   "Le Bavard du Mois",   "Envoie {target} messages ce mois-ci",      "messages",         (1500, 3000), 8000, 2500, "💬"),
    MonthlyMegaTemplate("m_voice_30h","Voix du Mois",        "Passe {target} minutes en vocal",          "voice_min",        (1200, 1800), 7500, 2300, "🎙️"),
    MonthlyMegaTemplate("m_events_30","Aventurier Mensuel",  "Participe a {target} evenements",          "events_participated",(20, 35),   9000, 2800, "🎯"),
    MonthlyMegaTemplate("m_bosses_15","Slayer du Mois",      "Vaincs {target} boss",                     "bosses_won",       (10, 18),     10000,3000, "⚔️"),
    MonthlyMegaTemplate("m_quiz_100", "Erudit Mensuel",      "Reponds a {target} questions correctes",   "quiz_correct",     (60, 120),    8500, 2700, "🧠"),
]


def generate_monthly_mega(guild_id: int, user_id: int, month_str: str) -> Optional[dict]:
    """Genere 1 mega quete deterministe pour le mois."""
    import hashlib
    s = f"{guild_id}_{user_id}_{month_str}"
    seed = int(hashlib.md5(s.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    tmpl = rng.choice(MONTHLY_MEGA_TEMPLATES)
    target = rng.randint(tmpl.target_range[0], tmpl.target_range[1])
    return {
        "id": tmpl.id,
        "title": tmpl.title,
        "description": tmpl.description.format(target=target),
        "metric": tmpl.metric,
        "target": target,
        "reward_coins": tmpl.reward_coins,
        "season_points": tmpl.season_points,
        "icon": tmpl.icon,
    }


__all__ = [
    'SeasonDef', 'SEASONS', 'current_season', 'current_season_id',
    'SEASON_PASS_TIERS', 'get_tier_by_points', 'points_for_next_tier',
    'PRESTIGE_RANKS', 'get_prestige_def', 'prestige_bonus_xp', 'prestige_bonus_coins',
    'FACTIONS', 'FACTION_TIERS', 'get_faction',
    'faction_tier_from_points', 'faction_points_to_next',
    'WeeklyQuestTemplate', 'WEEKLY_QUEST_TEMPLATES', 'generate_weekly_quests',
    'MonthlyMegaTemplate', 'MONTHLY_MEGA_TEMPLATES', 'generate_monthly_mega',
]
