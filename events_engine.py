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


__all__ = [
    "BOSS_CATALOG", "WEAPONS", "ARMOR", "RARITY_COLORS", "RARITY_EMOJIS",
    "random_weapon", "random_armor", "random_boss",
    "hp_bar", "calc_damage",
    "serialize_overwrites",
    "compute_rewards",
]
