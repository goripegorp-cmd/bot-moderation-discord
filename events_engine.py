"""
events_engine.py — Phase 30 : Système d'événements communautaires.

CONCEPT :
    L'owner active un système d'événements automatiques (ou manuels) qui
    "réveillent" la communauté. L'événement principal : un BOSS RAID où
    tous les salons deviennent invisibles sauf un seul "arène", et tous
    les membres doivent collaborer pour vaincre un boss en temps réel.

SÉCURITÉ :
    - Les salons sont MASQUÉS (overwrite view_channel=False) pas supprimés
    - L'état complet est SAUVEGARDÉ en DB avant toute modification
    - Restauration garantie même après crash/restart du bot
    - Les rôles avec view_channel=True explicite gardent leur accès
    - Owner et admins voient toujours tout
    - Les filtres existants (badwords, anti-spam, @everyone) restent actifs
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# =============================================================================
# CATALOGUE DES BOSS
# =============================================================================

BOSS_CATALOG = [
    {
        "name": "🐉 Dragon Ancestral",
        "emoji": "🐉",
        "color": 0xE74C3C,
        "hp_scale": 1.0,
        "abilities": ["Souffle de feu", "Coup de queue", "Rugissement"],
        "lore": "Un dragon millénaire surgit des profondeurs ! Sa peau d'écailles brille de mille feux.",
        "image": None,
    },
    {
        "name": "💀 Roi Squelette",
        "emoji": "💀",
        "color": 0x95A5A6,
        "hp_scale": 0.8,
        "abilities": ["Charge osseuse", "Cri funeste", "Invocation de morts"],
        "lore": "Le Roi Squelette se relève de sa tombe oubliée, sa couronne rouillée brillant dans l'obscurité.",
        "image": None,
    },
    {
        "name": "🦑 Léviathan",
        "emoji": "🦑",
        "color": 0x3498DB,
        "hp_scale": 1.2,
        "abilities": ["Tentacules géants", "Vague titanesque", "Encre venimeuse"],
        "lore": "Un Léviathan abyssal émerge des profondeurs marines, ses tentacules brisant l'horizon.",
        "image": None,
    },
    {
        "name": "👹 Démon des Enfers",
        "emoji": "👹",
        "color": 0x8E44AD,
        "hp_scale": 1.5,
        "abilities": ["Lacération démoniaque", "Flammes infernales", "Pacte maudit"],
        "lore": "Une déchirure dans la réalité s'ouvre — un démon majeur traverse le voile !",
        "image": None,
    },
    {
        "name": "🧊 Géant des Glaces",
        "emoji": "🧊",
        "color": 0x5DADE2,
        "hp_scale": 0.9,
        "abilities": ["Tempête de glace", "Marteau de givre", "Souffle polaire"],
        "lore": "Le Géant des Glaces descend de sa montagne, gelant tout sur son passage.",
        "image": None,
    },
    {
        "name": "🔥 Phénix Corrompu",
        "emoji": "🔥",
        "color": 0xE67E22,
        "hp_scale": 1.3,
        "abilities": ["Renaissance ardente", "Plumes de feu", "Cri solaire"],
        "lore": "Un phénix corrompu par les ombres revient à la vie, ses plumes noircies par la malédiction.",
        "image": None,
    },
    {
        "name": "🌪️ Élémentaire du Chaos",
        "emoji": "🌪️",
        "color": 0xF39C12,
        "hp_scale": 1.1,
        "abilities": ["Vortex destructeur", "Foudre orientée", "Rafale chaotique"],
        "lore": "Un être de pure énergie chaotique se manifeste, sa forme changeant à chaque seconde.",
        "image": None,
    },
    {
        "name": "🕷️ Reine des Ombres",
        "emoji": "🕷️",
        "color": 0x2C3E50,
        "hp_scale": 0.85,
        "abilities": ["Toile maudite", "Morsure venimeuse", "Multiplication"],
        "lore": "La Reine des Ombres tisse sa toile entre les serveurs, ses huit yeux fixant les courageux.",
        "image": None,
    },
]


# =============================================================================
# CATALOGUE DE L'ÉQUIPEMENT
# =============================================================================
# Rareté : commune (white), rare (blue), épique (purple), légendaire (gold)

WEAPONS = [
    # Communes
    {"name": "Bâton de bois",      "atk": 5,  "rarity": "commune",    "emoji": "🪵", "weight": 30},
    {"name": "Couteau rouillé",    "atk": 7,  "rarity": "commune",    "emoji": "🔪", "weight": 30},
    {"name": "Massue grossière",   "atk": 8,  "rarity": "commune",    "emoji": "🏏", "weight": 25},
    # Rares
    {"name": "Épée d'acier",       "atk": 12, "rarity": "rare",       "emoji": "⚔️", "weight": 15},
    {"name": "Arc elfique",        "atk": 14, "rarity": "rare",       "emoji": "🏹", "weight": 15},
    {"name": "Hache de guerre",    "atk": 15, "rarity": "rare",       "emoji": "🪓", "weight": 12},
    # Épiques
    {"name": "Lame enflammée",     "atk": 22, "rarity": "épique",     "emoji": "🔥", "weight": 6},
    {"name": "Foudre de Zeus",     "atk": 24, "rarity": "épique",     "emoji": "⚡", "weight": 5},
    # Légendaires
    {"name": "Excalibur",          "atk": 40, "rarity": "légendaire", "emoji": "🗡️", "weight": 2},
    {"name": "Mjölnir",            "atk": 45, "rarity": "légendaire", "emoji": "🔨", "weight": 1},
]

ARMOR = [
    # Communes
    {"name": "Tunique de coton",   "def": 2,  "rarity": "commune",    "emoji": "👕", "weight": 30},
    {"name": "Cuir tanné",         "def": 4,  "rarity": "commune",    "emoji": "🦺", "weight": 30},
    {"name": "Maille rouillée",    "def": 5,  "rarity": "commune",    "emoji": "⛓️", "weight": 25},
    # Rares
    {"name": "Cuirasse d'acier",   "def": 8,  "rarity": "rare",       "emoji": "🛡️", "weight": 15},
    {"name": "Robe enchantée",     "def": 9,  "rarity": "rare",       "emoji": "🧥", "weight": 15},
    {"name": "Armure de chevalier","def": 11, "rarity": "rare",       "emoji": "🪖", "weight": 12},
    # Épiques
    {"name": "Armure dragonique",  "def": 18, "rarity": "épique",     "emoji": "🐲", "weight": 6},
    {"name": "Cape céleste",       "def": 16, "rarity": "épique",     "emoji": "🪶", "weight": 6},
    # Légendaires
    {"name": "Armure divine",      "def": 30, "rarity": "légendaire", "emoji": "✨", "weight": 2},
    {"name": "Égide d'Athéna",     "def": 35, "rarity": "légendaire", "emoji": "🛡️", "weight": 1},
]

RARITY_COLORS = {
    "commune":    0x95A5A6,
    "rare":       0x3498DB,
    "épique":     0x9B59B6,
    "légendaire": 0xF1C40F,
}

RARITY_EMOJIS = {
    "commune":    "⚪",
    "rare":       "🔵",
    "épique":     "🟣",
    "légendaire": "🟡",
}


# =============================================================================
# RNG / HELPERS
# =============================================================================

def _weighted_choice(items: list[dict]) -> dict:
    """Choisit un item aléatoire pondéré par sa 'weight'."""
    total = sum(item.get("weight", 1) for item in items)
    if total <= 0:
        return random.choice(items)
    r = random.uniform(0, total)
    acc = 0.0
    for item in items:
        acc += item.get("weight", 1)
        if r <= acc:
            return item
    return items[-1]


def random_weapon(rarity_bias: float = 1.0) -> dict:
    """Génère une arme aléatoire (rarity_bias > 1 = plus rare)."""
    # Bias : ajuster les weights pour favoriser les rares
    if rarity_bias != 1.0:
        adjusted = []
        for w in WEAPONS:
            new_w = dict(w)
            if w["rarity"] in ("épique", "légendaire"):
                new_w["weight"] = max(1, int(w["weight"] * rarity_bias))
            adjusted.append(new_w)
        return dict(_weighted_choice(adjusted))
    return dict(_weighted_choice(WEAPONS))


def random_armor(rarity_bias: float = 1.0) -> dict:
    if rarity_bias != 1.0:
        adjusted = []
        for w in ARMOR:
            new_w = dict(w)
            if w["rarity"] in ("épique", "légendaire"):
                new_w["weight"] = max(1, int(w["weight"] * rarity_bias))
            adjusted.append(new_w)
        return dict(_weighted_choice(adjusted))
    return dict(_weighted_choice(ARMOR))


def random_boss(difficulty: int = 100) -> dict:
    """Boss aléatoire. `difficulty` = facteur 50-500 (100 = normal)."""
    template = dict(random.choice(BOSS_CATALOG))
    base_hp = int(800 * template["hp_scale"])
    final_hp = int(base_hp * (difficulty / 100.0))
    template["max_hp"] = max(100, final_hp)
    template["current_hp"] = template["max_hp"]
    return template


def hp_bar(current: int, maximum: int, length: int = 20) -> str:
    """Génère une barre de HP visuelle.

    █████░░░░░░░░░░░░░░░ 250/1000
    """
    if maximum <= 0:
        return "░" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * length)
    empty = length - filled
    return "█" * filled + "░" * empty


def calc_damage(weapon: Optional[dict], player_hp: int = 100) -> tuple[int, bool]:
    """Calcule les dégâts d'un coup.

    Retourne (damage, is_critical).
    - Damage de base : 10-25
    - Bonus arme : weapon.atk (5-45)
    - Critique : 10% → 2x damage
    """
    base = random.randint(10, 25)
    weapon_atk = (weapon or {}).get("atk", 0) if weapon else 0
    total = base + weapon_atk
    is_crit = random.random() < 0.10
    if is_crit:
        total *= 2
    return total, is_crit


# =============================================================================
# CHANNEL STATE MANAGER
# =============================================================================

def serialize_overwrites(overwrites: dict) -> dict:
    """Sérialise les overwrites @everyone d'un channel pour DB.

    On stocke uniquement view_channel pour @everyone car c'est ce qu'on modifie.
    Format : {"view_channel": True/False/None}
    """
    out = {}
    for target, perms in overwrites.items():
        try:
            # On ne sauve que les overwrites @everyone
            if hasattr(target, 'is_default') and target.is_default():
                pair = perms.pair()
                allow, deny = pair[0].value, pair[1].value
                out["everyone_allow"] = allow
                out["everyone_deny"] = deny
        except Exception:
            continue
    return out


# =============================================================================
# REWARDS
# =============================================================================

def compute_rewards(participants: list[dict], boss_max_hp: int, victory: bool, coin_multiplier: float = 1.0) -> list[dict]:
    """Calcule les récompenses pour chaque participant.

    participants : [{"user_id": int, "damage": int, "attacks": int}, ...]
    Retourne : [{"user_id": int, "coins": int, "gear": Optional[dict]}, ...]
    """
    if not participants:
        return []

    rewards = []
    # Trier par dégâts décroissants
    sorted_parts = sorted(participants, key=lambda p: p.get("damage", 0), reverse=True)
    top_3_ids = {p["user_id"] for p in sorted_parts[:3]}

    for p in participants:
        dmg = p.get("damage", 0)
        atks = p.get("attacks", 0)
        # Base coins : proportionnels aux dégâts
        if victory:
            base_coins = int(50 + (dmg / boss_max_hp) * 500)
        else:
            base_coins = int(10 + (dmg / boss_max_hp) * 100)
        coins = int(base_coins * coin_multiplier)

        gear = None
        # Drop gear (top 3 ont une chance accrue)
        if victory:
            drop_chance = 0.5 if p["user_id"] in top_3_ids else 0.2
            if random.random() < drop_chance:
                # 50/50 weapon ou armor
                if random.random() < 0.5:
                    gear = random_weapon(rarity_bias=2.0 if p["user_id"] in top_3_ids else 1.0)
                    gear["slot"] = "weapon"
                else:
                    gear = random_armor(rarity_bias=2.0 if p["user_id"] in top_3_ids else 1.0)
                    gear["slot"] = "armor"

        rewards.append({
            "user_id": p["user_id"],
            "damage": dmg,
            "attacks": atks,
            "coins": coins,
            "gear": gear,
            "rank": sorted_parts.index(p) + 1,
        })
    return rewards


# =============================================================================
# PHASE 31 : BADGES & RANGS
# =============================================================================

# Badges débloqués selon des conditions sur les stats du joueur
# (kills, total_damage, etc.) ou des événements spéciaux pendant les combats.
BADGE_CATALOG = [
    # Kills milestones
    {"id": "first_blood", "name": "Premier Sang",         "emoji": "🩸", "desc": "Vaincre ton premier boss"},
    {"id": "veteran",     "name": "Vétéran",              "emoji": "🎖️", "desc": "Vaincre 5 boss"},
    {"id": "slayer",      "name": "Tueur de Légendes",    "emoji": "🏆", "desc": "Vaincre 25 boss"},
    {"id": "myth",        "name": "Mythique",             "emoji": "👑", "desc": "Vaincre 100 boss"},
    # Damage milestones
    {"id": "puncher",     "name": "Frappeur",             "emoji": "👊", "desc": "Infliger 10 000 dégâts cumulés"},
    {"id": "warrior",     "name": "Guerrier",             "emoji": "⚔️", "desc": "Infliger 100 000 dégâts cumulés"},
    {"id": "destroyer",   "name": "Destructeur",          "emoji": "💥", "desc": "Infliger 1 000 000 dégâts cumulés"},
    # Combat exploits
    {"id": "critical",    "name": "Maître du Critique",   "emoji": "🌟", "desc": "Réussir 3 critiques d'affilée"},
    {"id": "final_blow",  "name": "Coup de Grâce",        "emoji": "💀", "desc": "Porter le coup fatal sur 5 boss"},
    {"id": "top_damager", "name": "Champion",             "emoji": "🥇", "desc": "Finir #1 en dégâts sur 10 raids"},
    {"id": "team_player", "name": "Esprit d'Équipe",      "emoji": "🤝", "desc": "Participer à 20 raids"},
    # Equipment
    {"id": "collector",   "name": "Collectionneur",       "emoji": "🎁", "desc": "Posséder un équipement légendaire"},
    {"id": "shopper",     "name": "Magnat",               "emoji": "💰", "desc": "Dépenser 10 000 pièces en boutique d'événement"},
    # Special / Rare
    {"id": "combo_master","name": "Maître des Combos",    "emoji": "🔥", "desc": "Déclencher 5 combos en une bataille"},
    {"id": "lucky",       "name": "Chanceux",             "emoji": "🍀", "desc": "Obtenir un loot épique avec moins de 100 dégâts"},
]


def get_badge_by_id(badge_id: str) -> Optional[dict]:
    for b in BADGE_CATALOG:
        if b["id"] == badge_id:
            return b
    return None


def check_badge_unlocks(stats: dict, already_unlocked: set, event_context: dict = None) -> list[str]:
    """Retourne les ids de badges à débloquer pour ce joueur.

    stats : {"kills": int, "total_damage": int, "raids_participated": int,
             "top1_count": int, "final_blows": int, "crits_streak": int,
             "has_legendary": bool, "shop_spent": int, "combos_in_battle": int,
             "lucky_drop_under_100": bool}
    already_unlocked : set de badge_ids déjà acquis
    event_context : optionnel, infos de l'event courant

    Le check est défensif : si une stat manque, on ignore le badge correspondant.
    """
    out = []
    s = stats or {}

    def _unlock(badge_id: str, condition: bool):
        if condition and badge_id not in already_unlocked:
            out.append(badge_id)

    _unlock("first_blood",  int(s.get("kills", 0)) >= 1)
    _unlock("veteran",      int(s.get("kills", 0)) >= 5)
    _unlock("slayer",       int(s.get("kills", 0)) >= 25)
    _unlock("myth",         int(s.get("kills", 0)) >= 100)

    _unlock("puncher",      int(s.get("total_damage", 0)) >= 10_000)
    _unlock("warrior",      int(s.get("total_damage", 0)) >= 100_000)
    _unlock("destroyer",    int(s.get("total_damage", 0)) >= 1_000_000)

    _unlock("critical",     int(s.get("crits_streak", 0)) >= 3)
    _unlock("final_blow",   int(s.get("final_blows", 0)) >= 5)
    _unlock("top_damager",  int(s.get("top1_count", 0)) >= 10)
    _unlock("team_player",  int(s.get("raids_participated", 0)) >= 20)
    _unlock("collector",    bool(s.get("has_legendary", False)))
    _unlock("shopper",      int(s.get("shop_spent", 0)) >= 10_000)
    _unlock("combo_master", int(s.get("combos_in_battle", 0)) >= 5)
    _unlock("lucky",        bool(s.get("lucky_drop_under_100", False)))

    return out


# Rangs de progression — uniquement pour AFFICHAGE des badges/jalons (PAS de rôle Discord)
# Le système ROLE est désormais event-based (cf EVENT_RANK_ROLES) pour donner à
# chaque membre une chance de top 1 à chaque nouvel événement.
RANK_TIERS = [
    {"min_kills": 1,   "name": "🥉 Chasseur Bronze",   "color": 0xCD7F32, "key": "bronze"},
    {"min_kills": 10,  "name": "🥈 Chasseur Argent",   "color": 0xC0C0C0, "key": "silver"},
    {"min_kills": 30,  "name": "🥇 Chasseur Or",       "color": 0xFFD700, "key": "gold"},
    {"min_kills": 75,  "name": "💎 Chasseur Platine",  "color": 0x9B59B6, "key": "platinum"},
    {"min_kills": 150, "name": "🌟 Chasseur Diamant",  "color": 0x5DADE2, "key": "diamond"},
    {"min_kills": 300, "name": "👑 Chasseur Mythique", "color": 0xE74C3C, "key": "mythic"},
]


def rank_for_kills(kills: int) -> Optional[dict]:
    """Retourne le tier le plus élevé atteint pour `kills` (None si <1)."""
    result = None
    for tier in RANK_TIERS:
        if kills >= tier["min_kills"]:
            result = tier
        else:
            break
    return result


# ─── RANGS DE L'ÉVÉNEMENT (TEMPORAIRES — reset à chaque nouvel event) ───
# Chaque participant reçoit potentiellement UN rôle, perdu au prochain event.
# Cela donne à chaque membre une chance d'être au sommet à chaque nouveau raid.
EVENT_RANK_ROLES = [
    {"key": "champion",   "name": "🥇 Champion du Raid",      "color": 0xFFD700, "min_rank": 1, "max_rank": 1},
    {"key": "vice",       "name": "🥈 Vice-Champion du Raid", "color": 0xC0C0C0, "min_rank": 2, "max_rank": 2},
    {"key": "third",      "name": "🥉 Troisième du Raid",     "color": 0xCD7F32, "min_rank": 3, "max_rank": 3},
    {"key": "combatant",  "name": "🎖️ Combattant Valeureux",   "color": 0x95A5A6, "min_rank": 4, "max_rank": 10},
]


def event_role_for_rank(rank: int) -> Optional[dict]:
    """Retourne le role event correspondant au classement (1=top)."""
    for er in EVENT_RANK_ROLES:
        if er["min_rank"] <= rank <= er["max_rank"]:
            return er
    return None


# =============================================================================
# PHASE 31 : COMBOS COMMUNAUTAIRES
# =============================================================================

# Si N joueurs attaquent dans la même fenêtre de T secondes → COMBO bonus
COMBO_THRESHOLDS = [
    {"players": 3, "window_sec": 2.0, "name": "TRIPLE FRAPPE",  "emoji": "💥", "multiplier": 1.5},
    {"players": 5, "window_sec": 3.0, "name": "BARRAGE",        "emoji": "⚡", "multiplier": 2.0},
    {"players": 10, "window_sec": 5.0, "name": "FUREUR COLLECTIVE", "emoji": "🌪️", "multiplier": 3.0},
]


def check_combo(recent_attacks: list[tuple], now_ts: float) -> Optional[dict]:
    """Vérifie si un combo est déclenché.

    recent_attacks : list de (timestamp, user_id) des attaques récentes
    now_ts : timestamp actuel
    Retourne le combo déclenché (le plus haut) ou None.
    """
    if not recent_attacks:
        return None

    # Test du plus impressionnant au plus simple
    for combo in reversed(COMBO_THRESHOLDS):
        cutoff = now_ts - combo["window_sec"]
        recent = [(t, u) for (t, u) in recent_attacks if t >= cutoff]
        unique_users = {u for (_, u) in recent}
        if len(unique_users) >= combo["players"]:
            return dict(combo)
    return None


# =============================================================================
# PHASE 31 : NOUVEAUX TYPES D'ÉVÉNEMENTS
# =============================================================================

# Trésors (chasse au trésor)
TREASURE_CATALOG = [
    {"name": "Coffre en bois",      "emoji": "📦", "coins_min": 30,  "coins_max": 80,  "gear_chance": 0.10, "weight": 30},
    {"name": "Coffre en fer",       "emoji": "🗃️", "coins_min": 80,  "coins_max": 200, "gear_chance": 0.20, "weight": 20},
    {"name": "Coffre doré",         "emoji": "📜", "coins_min": 200, "coins_max": 500, "gear_chance": 0.35, "weight": 10},
    {"name": "Gemme rare",          "emoji": "💎", "coins_min": 500, "coins_max": 1000,"gear_chance": 0.50, "weight": 5},
    {"name": "Relique légendaire",  "emoji": "🏺", "coins_min": 1000,"coins_max": 2500,"gear_chance": 0.80, "weight": 2},
]


def random_treasure() -> dict:
    """Génère un trésor aléatoire pondéré + sa loot."""
    template = dict(_weighted_choice(TREASURE_CATALOG))
    template["coins"] = random.randint(template["coins_min"], template["coins_max"])
    template["gear"] = None
    if random.random() < template["gear_chance"]:
        if random.random() < 0.5:
            template["gear"] = random_weapon(rarity_bias=1.5)
            template["gear"]["slot"] = "weapon"
        else:
            template["gear"] = random_armor(rarity_bias=1.5)
            template["gear"]["slot"] = "armor"
    return template


# Questions de quiz (FR) — variées en thèmes et difficulté
QUIZ_QUESTIONS = [
    # Géographie
    {"q": "Quelle est la capitale de l'Australie ?", "a": ["Sydney", "Canberra", "Melbourne", "Perth"], "c": 1},
    {"q": "Quel est le plus long fleuve du monde ?", "a": ["Amazone", "Nil", "Yangtsé", "Mississippi"], "c": 1},
    {"q": "Combien y a-t-il de continents ?", "a": ["5", "6", "7", "8"], "c": 2},
    {"q": "Quel pays a la forme d'une botte ?", "a": ["Espagne", "Italie", "Grèce", "Portugal"], "c": 1},
    {"q": "Quelle est la monnaie du Japon ?", "a": ["Yen", "Won", "Yuan", "Bath"], "c": 0},
    # Sciences
    {"q": "Quel est le plus grand organe du corps humain ?", "a": ["Foie", "Cerveau", "Peau", "Cœur"], "c": 2},
    {"q": "Combien de planètes dans le système solaire ?", "a": ["7", "8", "9", "10"], "c": 1},
    {"q": "Quelle est la formule chimique de l'eau ?", "a": ["O2", "H2O", "CO2", "H2O2"], "c": 1},
    {"q": "Qui a inventé l'ampoule électrique ?", "a": ["Edison", "Tesla", "Newton", "Einstein"], "c": 0},
    {"q": "Quel est l'animal le plus rapide ?", "a": ["Lion", "Guépard", "Faucon", "Gazelle"], "c": 2},  # faucon pèlerin
    # Culture générale
    {"q": "Qui a peint La Joconde ?", "a": ["Picasso", "Van Gogh", "Léonard de Vinci", "Monet"], "c": 2},
    {"q": "En quelle année a commencé la WW1 ?", "a": ["1912", "1914", "1916", "1918"], "c": 1},
    {"q": "Quel est le sommet le plus haut du monde ?", "a": ["K2", "Mont Blanc", "Everest", "Kilimandjaro"], "c": 2},
    {"q": "Qui a écrit 'Les Misérables' ?", "a": ["Hugo", "Zola", "Balzac", "Dumas"], "c": 0},
    {"q": "Combien d'os dans le corps humain adulte ?", "a": ["186", "206", "226", "246"], "c": 1},
    # Gaming / Pop culture
    {"q": "Quelle entreprise a créé Minecraft à l'origine ?", "a": ["Microsoft", "Mojang", "Notch Studios", "Sony"], "c": 1},
    {"q": "Combien de Pokémon dans la 1ère génération ?", "a": ["100", "150", "151", "152"], "c": 2},
    {"q": "Quel est le jeu le plus vendu de l'histoire ?", "a": ["Tetris", "Minecraft", "GTA V", "Wii Sports"], "c": 1},
    {"q": "Dans Mario, quel est le frère de Mario ?", "a": ["Wario", "Luigi", "Yoshi", "Toad"], "c": 1},
    {"q": "Quel studio développe les Zelda ?", "a": ["Nintendo EAD", "Game Freak", "Square Enix", "Capcom"], "c": 0},
    # Math / Logique
    {"q": "Combien font 7 × 8 ?", "a": ["54", "56", "58", "64"], "c": 1},
    {"q": "Quel est le résultat de 15² ?", "a": ["205", "215", "225", "235"], "c": 2},
    {"q": "Combien y a-t-il de minutes dans 3 heures ?", "a": ["120", "150", "180", "210"], "c": 2},
    {"q": "Quel chiffre romain représente 50 ?", "a": ["X", "L", "C", "D"], "c": 1},
    # Discord / Tech
    {"q": "En quelle année Discord a-t-il été créé ?", "a": ["2012", "2015", "2017", "2019"], "c": 1},
    {"q": "Quel langage utilise discord.py ?", "a": ["JavaScript", "Python", "C++", "Java"], "c": 1},
    {"q": "Quelle entreprise possède YouTube ?", "a": ["Meta", "Google", "Microsoft", "Amazon"], "c": 1},
    {"q": "Quel est le bouton vert dans une UI Discord ?", "a": ["Success", "Primary", "Danger", "Link"], "c": 0},
    # Sport
    {"q": "Combien de joueurs dans une équipe de football ?", "a": ["10", "11", "12", "13"], "c": 1},
    {"q": "Combien de pays organisent les JO ?", "a": ["1 par édition", "2", "3", "Tous"], "c": 0},
    {"q": "Quel sport pratique-t-on à Wimbledon ?", "a": ["Golf", "Tennis", "Cricket", "Polo"], "c": 1},
    # FR / Langue
    {"q": "Combien de lettres dans l'alphabet français ?", "a": ["24", "25", "26", "27"], "c": 2},
    {"q": "Quel est le pluriel de 'cheval' ?", "a": ["chevals", "chevaux", "chevaies", "chevalles"], "c": 1},
    # Cuisine / Vie quotidienne
    {"q": "Quel ingrédient principal dans le pesto ?", "a": ["Persil", "Basilic", "Menthe", "Coriandre"], "c": 1},
    {"q": "Combien de degrés bout l'eau (au niveau de la mer) ?", "a": ["90°C", "95°C", "100°C", "105°C"], "c": 2},
]


def get_quiz_set(n: int = 10) -> list[dict]:
    """Retourne N questions aléatoires uniques pour un quiz."""
    n = max(1, min(n, len(QUIZ_QUESTIONS)))
    return random.sample(QUIZ_QUESTIONS, n)


# =============================================================================
# PHASE 33 : ÉVÉNEMENTS PERSONNELS (un seul membre concerné)
# =============================================================================

# Conseils que le bot peut donner aux joueurs (rotation)
HELP_TIPS = [
    "Sais-tu que tu peux taper `/badges` pour voir tes badges et ton rang ?",
    "Pense à `/inventory` pour voir ton équipement actuel — il booste tes dégâts !",
    "La boutique d'événement (`/event_shop`) change toutes les semaines. Va y jeter un œil !",
    "Tu peux déclencher un duel contre un autre membre avec `/duel @membre` — combat 1v1.",
    "Pour voir l'événement en cours, utilise `/event` à tout moment.",
    "Plus tu participes aux Boss Raids, plus tu débloques de badges et de rangs.",
    "Astuce : équipe-toi avant un raid pour faire plus de dégâts !",
    "Le classement du serveur est visible avec `/leaderboard` (pièces · messages · vocal).",
    "Tu peux configurer ton anniversaire avec `/birthday set JJ-MM` pour être souhaité le jour J.",
    "En vocal, tu gagnes des pièces et de l'XP — pense à passer du temps avec la commu !",
]


# Devinettes simples (FR)
PERSONAL_RIDDLES = [
    {"q": "Je grandis sans me nourrir, et je meurs si je bois. Qui suis-je ?",
     "a": ["Le feu", "L'eau", "Le vent", "La glace"], "c": 0},
    {"q": "Plus on en prend, plus on en laisse. Qu'est-ce que c'est ?",
     "a": ["Des photos", "Des empreintes", "Des souvenirs", "Des mots"], "c": 1},
    {"q": "Je n'ai pas de bouche mais je parle. Qu'est-ce que c'est ?",
     "a": ["Un écho", "Un livre", "Le vent", "Un téléphone"], "c": 0},
    {"q": "Plus je sèche, plus je deviens humide. Qu'est-ce que c'est ?",
     "a": ["Une éponge", "Une serviette", "Un mouchoir", "Une plante"], "c": 1},
    {"q": "Je tombe mais ne me casse jamais. Quand je me casse, je ne tombe plus.",
     "a": ["Un cheveu", "La nuit", "Une feuille", "Une étoile"], "c": 1},
    {"q": "Quel mot de 4 lettres contient 7 jours ?",
     "a": ["Sept", "Lune", "Année", "Hier"], "c": 0},  # "Sept" — astuce
    {"q": "Je commence par la lettre E mais ne contient qu'une lettre.",
     "a": ["Enveloppe", "Email", "Étoile", "Encre"], "c": 0},
]


def random_personal_event() -> dict:
    """Génère un événement personnel aléatoire pondéré."""
    types = [
        {"id": "gift",   "weight": 30},
        {"id": "math",   "weight": 25},
        {"id": "riddle", "weight": 25},
        {"id": "tip",    "weight": 20},
    ]
    chosen = _weighted_choice(types)["id"]

    if chosen == "gift":
        coins = random.choice([50, 75, 100, 125, 150, 200, 250, 300, 500])
        return {
            "type": "gift",
            "title": "🎁 Cadeau Surprise !",
            "description": f"Le bot t'offre **{coins}** 🪙 ! Clique sur le bouton pour l'accepter.",
            "coins": coins,
        }

    if chosen == "math":
        a = random.randint(5, 50)
        b = random.randint(5, 50)
        op = random.choice(['+', '-', '×'])
        if op == '+':
            correct = a + b
        elif op == '-':
            correct = a - b
        else:
            correct = a * b
        # 3 mauvaises réponses
        bad = set()
        while len(bad) < 3:
            offset = random.choice([-10, -5, -2, -1, 1, 2, 5, 10])
            v = correct + offset
            if v != correct:
                bad.add(v)
        all_answers = list(bad) + [correct]
        random.shuffle(all_answers)
        correct_idx = all_answers.index(correct)
        return {
            "type": "math",
            "title": "🧮 Énigme Mathématique",
            "description": f"Combien font **{a} {op} {b}** ?",
            "answers": [str(x) for x in all_answers],
            "correct_idx": correct_idx,
            "reward": random.choice([100, 150, 200, 250]),
        }

    if chosen == "riddle":
        r = dict(random.choice(PERSONAL_RIDDLES))
        return {
            "type": "riddle",
            "title": "❓ Devinette",
            "description": r["q"],
            "answers": r["a"],
            "correct_idx": r["c"],
            "reward": random.choice([150, 200, 250, 300]),
        }

    if chosen == "tip":
        return {
            "type": "tip",
            "title": "💡 Conseil du Bot",
            "description": random.choice(HELP_TIPS),
            "coins": random.choice([25, 50, 75]),
        }

    # fallback
    return {"type": "gift", "title": "🎁 Cadeau", "description": "Cadeau !", "coins": 50}


# =============================================================================
# PHASE 33 : SYSTÈME DE DUEL PvP
# =============================================================================

def simulate_duel(challenger_inv: dict, opponent_inv: dict) -> dict:
    """Simule un duel 1v1 entre deux joueurs avec leurs inventaires.

    Retourne :
    {
        "winner": "challenger" | "opponent" | "draw",
        "challenger_hp": int (HP final),
        "opponent_hp": int,
        "rounds": [ {round, c_dmg, o_dmg, c_crit, o_crit}, ... ],
    }
    """
    c_max_hp = 100 + (challenger_inv.get('armor', {}).get('def', 0) or 0) * 5
    o_max_hp = 100 + (opponent_inv.get('armor', {}).get('def', 0) or 0) * 5
    c_hp = c_max_hp
    o_hp = o_max_hp

    rounds = []
    for round_idx in range(1, 8):  # max 7 rounds
        if c_hp <= 0 or o_hp <= 0:
            break
        # Challenger attaque
        c_dmg, c_crit = calc_damage(challenger_inv.get('weapon'))
        c_dmg -= (opponent_inv.get('armor', {}).get('def', 0) or 0) // 2
        c_dmg = max(1, c_dmg)
        o_hp = max(0, o_hp - c_dmg)
        # Opponent attaque (si encore vivant)
        if o_hp > 0:
            o_dmg, o_crit = calc_damage(opponent_inv.get('weapon'))
            o_dmg -= (challenger_inv.get('armor', {}).get('def', 0) or 0) // 2
            o_dmg = max(1, o_dmg)
            c_hp = max(0, c_hp - o_dmg)
        else:
            o_dmg, o_crit = 0, False

        rounds.append({
            "round": round_idx,
            "c_dmg": c_dmg, "o_dmg": o_dmg,
            "c_crit": c_crit, "o_crit": o_crit,
            "c_hp": c_hp, "o_hp": o_hp,
        })

    if c_hp > o_hp:
        winner = "challenger"
    elif o_hp > c_hp:
        winner = "opponent"
    else:
        winner = "draw"

    return {
        "winner": winner,
        "challenger_hp": c_hp,
        "opponent_hp": o_hp,
        "challenger_max_hp": c_max_hp,
        "opponent_max_hp": o_max_hp,
        "rounds": rounds,
    }


def get_help_footer(context: str = "general") -> str:
    """Retourne un message d'aide pertinent selon le contexte.

    context : "general", "event_end", "duel_end", "inventory", "shop"
    """
    base = "💡 **Commandes utiles** : "
    if context == "event_end":
        return base + "`/badges` (tes exploits) · `/inventory` (équipement) · `/event_shop` (boutique) · `/duel @membre` (combat 1v1)"
    if context == "duel_end":
        return base + "`/duel @membre [mise]` à nouveau · `/inventory` (équipement) · `/event_shop` (s'équiper)"
    if context == "inventory":
        return base + "`/event_shop` pour acheter du gear · `/event` pour rejoindre l'event · `/duel @membre` pour défier"
    if context == "shop":
        return base + "`/inventory` (voir ton stuff) · `/event` (rejoindre l'arène) · `/badges` (ton profil)"
    return base + "`/event` · `/inventory` · `/badges` · `/event_shop` · `/duel @membre` · `/leaderboard`"


# =============================================================================
# PHASE 36 — ÉVÉNEMENTS LÉGERS (sans masquage de salons)
# Ces events s'ajoutent au flow normal — ils sont rapides, fréquents, et
# n'interrompent personne. Ils visent à RÉVEILLER les inactifs et créer des
# micro-moments d'interaction sans pollution.
# =============================================================================

# Pool d'emojis pour Speed React
SPEED_REACT_EMOJIS = ['🔥', '⚡', '💎', '🎯', '🌟', '🎁', '🏆', '⭐']

# Pool de "mystery boxes" thématiques
MYSTERY_BOX_TYPES = [
    {"name": "Boîte Mystère",         "emoji": "📦", "color": 0x95A5A6, "coins_min": 50,  "coins_max": 200, "gear_chance": 0.10, "weight": 40},
    {"name": "Boîte Étincelante",     "emoji": "✨", "color": 0xF1C40F, "coins_min": 150, "coins_max": 400, "gear_chance": 0.25, "weight": 25},
    {"name": "Coffre Doré",           "emoji": "💰", "color": 0xE67E22, "coins_min": 300, "coins_max": 700, "gear_chance": 0.40, "weight": 15},
    {"name": "Relique Mystique",      "emoji": "🔮", "color": 0x9B59B6, "coins_min": 500, "coins_max": 1200,"gear_chance": 0.65, "weight": 5},
]


def random_mystery_box() -> dict:
    """Génère une mystery box aléatoire pondérée."""
    box = dict(_weighted_choice(MYSTERY_BOX_TYPES))
    box["coins"] = random.randint(box["coins_min"], box["coins_max"])
    box["gear"] = None
    if random.random() < box["gear_chance"]:
        if random.random() < 0.5:
            box["gear"] = random_weapon(rarity_bias=1.2)
            box["gear"]["slot"] = "weapon"
        else:
            box["gear"] = random_armor(rarity_bias=1.2)
            box["gear"]["slot"] = "armor"
    return box


# Pool de citations / questions pour Daily Spark (un événement texte tout simple)
DAILY_SPARKS = [
    {"q": "Quel jeu vidéo a marqué ton enfance ?", "emoji": "🎮"},
    {"q": "Ton film préféré de tous les temps ?", "emoji": "🎬"},
    {"q": "Une chose que tu adores que personne d'autre n'aime ?", "emoji": "🤔"},
    {"q": "Plage ou montagne ? Et pourquoi ?", "emoji": "🏖️"},
    {"q": "Si tu pouvais maîtriser une langue instantanément ?", "emoji": "🌍"},
    {"q": "Ton plat ultime quand t'as la flemme de cuisiner ?", "emoji": "🍕"},
    {"q": "Animal de compagnie idéal : chat, chien, ou autre ?", "emoji": "🐱"},
    {"q": "Pile ou face : tu pars en vacances DEMAIN ?", "emoji": "✈️"},
    {"q": "Dernière série que tu as binge-watch ?", "emoji": "📺"},
    {"q": "Un super-pouvoir au choix : voler ou être invisible ?", "emoji": "🦸"},
    {"q": "Café, thé, ou rien le matin ?", "emoji": "☕"},
    {"q": "Quel est le meilleur emoji selon toi ?", "emoji": "😄"},
    {"q": "Si tu pouvais voyager dans le temps, quelle époque ?", "emoji": "⏳"},
    {"q": "Une chose à apprendre absolument avant de mourir ?", "emoji": "📚"},
    {"q": "Ton son préféré (pluie, feu, vagues, café qui passe...) ?", "emoji": "🎧"},
]


def random_daily_spark() -> dict:
    """Choisit une question random pour daily spark."""
    return dict(random.choice(DAILY_SPARKS))


# =============================================================================
# PHASE 36 : Catégorisation activité des membres
# =============================================================================

def categorize_member_activity(last_message_iso: Optional[str]) -> str:
    """Catégorise un membre selon sa dernière activité.

    Returns: 'very_active' (msg < 24h) · 'active' (< 7j) · 'dormant' (< 30j) · 'asleep' (> 30j ou jamais)
    """
    if not last_message_iso:
        return 'asleep'
    try:
        from datetime import datetime as _dt, timezone as _tz
        last_dt = _dt.fromisoformat(last_message_iso.replace('Z', '+00:00')) if 'T' in last_message_iso \
            else _dt.strptime(last_message_iso, '%Y-%m-%d %H:%M:%S').replace(tzinfo=_tz.utc)
        delta = _dt.now(_tz.utc) - last_dt
        days = delta.total_seconds() / 86400
        if days < 1:
            return 'very_active'
        if days < 7:
            return 'active'
        if days < 30:
            return 'dormant'
        return 'asleep'
    except Exception:
        return 'asleep'


def targeting_weight(category: str) -> int:
    """Poids pour le système de targeting intelligent.

    Plus élevé = plus de chances d'être ciblé par un event personnel.
    Les dormant/asleep ont plus de poids → on essaie de les réveiller.
    """
    return {
        'very_active': 5,   # actifs : on les arrose modérément (pas spammer)
        'active': 10,       # actifs récents : cibles principales
        'dormant': 25,      # endormis : on essaie de réveiller (× 2.5)
        'asleep': 15,       # très endormis : essai modéré (DMs souvent fermés)
    }.get(category, 10)


def random_event_intent(category: str) -> str:
    """Choisit un type d'event personnel selon le profil du membre.

    Pour les dormants/asleep : on privilégie les CADEAUX (motivation positive).
    Pour les actifs : on varie plus (math/riddle/tip pour l'engager activement).
    """
    if category in ('dormant', 'asleep'):
        # 60% cadeau, 20% tip motivant, 20% devinette facile
        types = [('gift', 60), ('tip', 20), ('riddle', 20)]
    elif category == 'active':
        # Mix équilibré
        types = [('gift', 30), ('math', 25), ('riddle', 25), ('tip', 20)]
    else:  # very_active
        # Plus de défis pour les actifs
        types = [('math', 30), ('riddle', 30), ('gift', 25), ('tip', 15)]

    # Tirage pondéré
    weighted = [(t, w) for t, w in types]
    total_w = sum(w for _, w in weighted)
    r = random.uniform(0, total_w)
    acc = 0
    for t, w in weighted:
        acc += w
        if r <= acc:
            return t
    return 'gift'


# =============================================================================
# PHASE 31 : DIFFICULTÉ PROGRESSIVE
# =============================================================================

def adjust_difficulty(current_diff: int, last_event_was_fast_kill: bool, last_event_was_failure: bool) -> int:
    """Ajuste la difficulté pour le prochain boss.

    - Kill en moins de moitié du temps → +20% difficulté (max 500)
    - Boss enfui → -15% difficulté (min 50)
    - Sinon → pas de changement
    """
    new_diff = current_diff
    if last_event_was_fast_kill:
        new_diff = int(current_diff * 1.20)
    elif last_event_was_failure:
        new_diff = int(current_diff * 0.85)
    return max(50, min(500, new_diff))


# =============================================================================
# PHASE 31 : SHOP D'ÉVÉNEMENT (rotation)
# =============================================================================

def generate_shop_rotation(seed: int = None) -> list[dict]:
    """Génère une sélection de 6 items pour le shop (3 armes + 3 armures).

    Utilise un seed pour stabilité par semaine. À appeler avec le numéro de semaine
    pour que tous les membres voient le même shop pendant 7 jours.
    """
    rng = random.Random(seed) if seed is not None else random

    def pick(catalog, n):
        # Plus la rareté est haute, plus le prix monte
        picked = []
        seen = set()
        attempts = 0
        while len(picked) < n and attempts < 50:
            attempts += 1
            it = dict(_weighted_choice(catalog))
            if it["name"] in seen:
                continue
            seen.add(it["name"])
            rarity_mult = {"commune": 1, "rare": 3, "épique": 8, "légendaire": 25}.get(it.get("rarity", "commune"), 1)
            stat_value = it.get("atk", 0) + it.get("def", 0)
            it["price"] = max(50, stat_value * 50 * rarity_mult)
            picked.append(it)
        return picked

    weapons = pick(WEAPONS, 3)
    armors = pick(ARMOR, 3)
    for w in weapons:
        w["slot"] = "weapon"
    for a in armors:
        a["slot"] = "armor"
    return weapons + armors


__all__ = [
    # Catalogues
    "BOSS_CATALOG", "WEAPONS", "ARMOR", "TREASURE_CATALOG", "QUIZ_QUESTIONS",
    "BADGE_CATALOG", "RANK_TIERS", "EVENT_RANK_ROLES", "COMBO_THRESHOLDS",
    "RARITY_COLORS", "RARITY_EMOJIS",
    "HELP_TIPS", "PERSONAL_RIDDLES",
    "SPEED_REACT_EMOJIS", "MYSTERY_BOX_TYPES", "DAILY_SPARKS",
    # Generators
    "random_weapon", "random_armor", "random_boss", "random_treasure",
    "generate_shop_rotation", "get_quiz_set", "random_personal_event",
    "random_mystery_box", "random_daily_spark",
    # Targeting
    "categorize_member_activity", "targeting_weight", "random_event_intent",
    # Helpers
    "hp_bar", "calc_damage", "serialize_overwrites", "compute_rewards",
    "check_badge_unlocks", "get_badge_by_id",
    "rank_for_kills", "event_role_for_rank",
    "check_combo",
    "adjust_difficulty",
    "simulate_duel",
    "get_help_footer",
]
