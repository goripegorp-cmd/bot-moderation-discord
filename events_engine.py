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


# Rangs de progression — donnent un rôle Discord auto si configuré
# Chaque tier a un seuil de kills + un nom de rôle + couleur
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
    "BOSS_CATALOG", "WEAPONS", "ARMOR", "TREASURE_CATALOG",
    "BADGE_CATALOG", "RANK_TIERS", "COMBO_THRESHOLDS",
    "RARITY_COLORS", "RARITY_EMOJIS",
    # Generators
    "random_weapon", "random_armor", "random_boss", "random_treasure",
    "generate_shop_rotation",
    # Helpers
    "hp_bar", "calc_damage", "serialize_overwrites", "compute_rewards",
    "check_badge_unlocks", "get_badge_by_id",
    "rank_for_kills",
    "check_combo",
    "adjust_difficulty",
]
