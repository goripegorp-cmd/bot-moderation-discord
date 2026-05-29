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
# Phase 176 — NOMS DE BOSS ÉPIQUES (uniques + thématiques par saison)
# =============================================================================
# Chaque boss reçoit un nom PROPRE unique (prénom + épithète) au lieu du simple
# type ("Dragon Ancestral"). L'épithète s'adapte à la saison en cours pour
# coller au lore → des boss différents et immersifs à chaque apparition.

BOSS_PROPER_NAMES = [
    "Vorthak", "Malphas", "Nyxara", "Drathmor", "Kael'Thuzad", "Zsharûl",
    "Morgaroth", "Velkhar", "Azgaroth", "Sythraxis", "Bal'Zoreth", "Khor'Valil",
    "Ulthrax", "Maldraxis", "Vœurnoth", "Throgar", "Xal'Atath", "Néferith",
    "Grimaldur", "Sombrelame", "Varathor", "Cindraxa", "Orgrath", "Velmyra",
    "Dûragost", "Nhalleth", "Skornveil", "Thalmgor", "Ysraël", "Karnoth",
]

# Épithètes génériques (toutes saisons confondues)
BOSS_EPITHETS_BASE = [
    "le Dévoreur", "l'Indomptable", "le Maudit", "des Abysses", "le Cataclysme",
    "l'Éternel", "le Fléau", "Briseur de Mondes", "l'Insatiable", "le Profanateur",
    "l'Effroi", "le Sans-Nom", "Mangeur d'Âmes", "le Titan Déchu", "l'Implacable",
    "la Ruine", "le Calamiteux", "Porteur de Fin",
]

# Épithètes thématiques par saison (clés = seasonal_engine.SEASONS[*]["key"])
BOSS_EPITHETS_SEASONAL = {
    "autumn":      ["de la Récolte Sanglante", "des Feuilles Mortes", "du Grand Déclin"],
    "halloween":   ["des Tombes Oubliées", "l'Âme Damnée", "du Voile Spectral", "le Revenant"],
    "fog":         ["du Brouillard Éternel", "des Brumes Maudites", "le Spectre Errant"],
    "solstice":    ["du Givre Sacré", "des Neiges Profanes", "le Gel Éternel"],
    "deep_winter": ["du Blizzard Sans Fin", "des Glaces Anciennes", "le Cœur de Givre"],
    "tournament":  ["le Champion Déchu", "Briseur d'Arènes", "le Conquérant"],
    "spring":      ["des Ronces Maudites", "du Renouveau Corrompu", "le Semeur de Fléaux"],
    "summer":      ["du Soleil Noir", "des Flammes Éternelles", "l'Embrasé"],
}


def generate_boss_title(season_key: Optional[str] = None) -> str:
    """Génère un nom de boss épique unique, ex : 'Vorthak le Dévoreur'.

    Si une saison est fournie, ~60% de chance d'utiliser une épithète
    thématique (immersion saisonnière) sinon une épithète générique.
    """
    proper = random.choice(BOSS_PROPER_NAMES).strip()
    seasonal = BOSS_EPITHETS_SEASONAL.get(season_key or "", [])
    if seasonal and random.random() < 0.60:
        epithet = random.choice(seasonal)
    else:
        epithet = random.choice(BOSS_EPITHETS_BASE)
    return f"{proper} {epithet}"


# =============================================================================
# CATALOGUE DE L'ÉQUIPEMENT
# =============================================================================
# Rareté : commune (white), rare (blue), épique (purple), légendaire (gold)

WEAPONS = [
    # Communes
    {"name": "Bâton de bois",         "atk": 5,  "rarity": "commune",    "emoji": "🪵", "weight": 30},
    {"name": "Couteau rouillé",       "atk": 7,  "rarity": "commune",    "emoji": "🔪", "weight": 30},
    {"name": "Massue grossière",      "atk": 8,  "rarity": "commune",    "emoji": "🏏", "weight": 25},
    # Rares
    {"name": "Épée d'acier",          "atk": 12, "rarity": "rare",       "emoji": "⚔️", "weight": 15},
    {"name": "Arc elfique",           "atk": 14, "rarity": "rare",       "emoji": "🏹", "weight": 15},
    {"name": "Hache de guerre",       "atk": 15, "rarity": "rare",       "emoji": "🪓", "weight": 12},
    # Épiques
    {"name": "Lame enflammée",        "atk": 22, "rarity": "épique",     "emoji": "🔥", "weight": 6},
    {"name": "Foudre de Zeus",        "atk": 24, "rarity": "épique",     "emoji": "⚡", "weight": 5},
    # Légendaires
    {"name": "Excalibur",             "atk": 40, "rarity": "légendaire", "emoji": "🗡️", "weight": 2},
    {"name": "Mjölnir",               "atk": 45, "rarity": "légendaire", "emoji": "🔨", "weight": 1},
    # Mythiques (Phase 39 — rarissimes, demandent des années de farm)
    {"name": "Aurora Stellaria",      "atk": 60, "rarity": "mythique",   "emoji": "🌌", "weight": 1},
    {"name": "Lame du Néant",         "atk": 65, "rarity": "mythique",   "emoji": "🕳️", "weight": 1},
    # Divines (Phase 39 — quasi inaccessibles, drop super rare)
    {"name": "Lame du Créateur",      "atk": 100, "rarity": "divine",    "emoji": "👁️", "weight": 1},
]

ARMOR = [
    # Communes
    {"name": "Tunique de coton",      "def": 2,  "rarity": "commune",    "emoji": "👕", "weight": 30},
    {"name": "Cuir tanné",            "def": 4,  "rarity": "commune",    "emoji": "🦺", "weight": 30},
    {"name": "Maille rouillée",       "def": 5,  "rarity": "commune",    "emoji": "⛓️", "weight": 25},
    # Rares
    {"name": "Cuirasse d'acier",      "def": 8,  "rarity": "rare",       "emoji": "🛡️", "weight": 15},
    {"name": "Robe enchantée",        "def": 9,  "rarity": "rare",       "emoji": "🧥", "weight": 15},
    {"name": "Armure de chevalier",   "def": 11, "rarity": "rare",       "emoji": "🪖", "weight": 12},
    # Épiques
    {"name": "Armure dragonique",     "def": 18, "rarity": "épique",     "emoji": "🐲", "weight": 6},
    {"name": "Cape céleste",          "def": 16, "rarity": "épique",     "emoji": "🪶", "weight": 6},
    # Légendaires
    {"name": "Armure divine",         "def": 30, "rarity": "légendaire", "emoji": "✨", "weight": 2},
    {"name": "Égide d'Athéna",        "def": 35, "rarity": "légendaire", "emoji": "🛡️", "weight": 1},
    # Mythiques
    {"name": "Cuirasse du Phénix",    "def": 50, "rarity": "mythique",   "emoji": "🔥", "weight": 1},
    {"name": "Manteau d'Éternité",    "def": 55, "rarity": "mythique",   "emoji": "♾️", "weight": 1},
    # Divines
    {"name": "Égide Cosmique",        "def": 80, "rarity": "divine",     "emoji": "🌠", "weight": 1},
]

RARITY_COLORS = {
    "commune":    0x95A5A6,
    "rare":       0x3498DB,
    "épique":     0x9B59B6,
    "légendaire": 0xF1C40F,
    "mythique":   0xE74C3C,
    "divine":     0xFFFFFF,
}

RARITY_EMOJIS = {
    "commune":    "⚪",
    "rare":       "🔵",
    "épique":     "🟣",
    "légendaire": "🟡",
    "mythique":   "🔴",
    "divine":     "🌟",
}

# Phase 39 : ordre numérique des raretés (utilisé pour comparaisons + soft cap)
RARITY_ORDER = {
    "commune":    0,
    "rare":       1,
    "épique":     2,
    "légendaire": 3,
    "mythique":   4,
    "divine":     5,
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


# ─── Phase 102 : Nouveaux slots équipement ───────────────────────────────
# Helmet (casque), Boots (bottes), Accessory (anneau/collier), Trinket (objet magique)

HELMETS = [
    {"name": "Bandeau de toile",  "emoji": "🎀", "rarity": "commune",    "def": 2, "weight": 40},
    {"name": "Capuche d'éclaireur","emoji": "🧢", "rarity": "commune",    "def": 3, "weight": 35},
    {"name": "Casque de bronze",  "emoji": "⛑️", "rarity": "rare",       "def": 6, "weight": 18},
    {"name": "Heaume de chevalier","emoji": "🪖", "rarity": "épique",     "def": 11, "weight": 6},
    {"name": "Couronne ancienne", "emoji": "👑", "rarity": "légendaire", "def": 18, "atk": 3, "weight": 1},
]

BOOTS_LIST = [
    {"name": "Sandales de toile",  "emoji": "🥿", "rarity": "commune",    "def": 1, "weight": 40},
    {"name": "Bottes en cuir",     "emoji": "🥾", "rarity": "commune",    "def": 2, "weight": 35},
    {"name": "Bottes renforcées",  "emoji": "👢", "rarity": "rare",       "def": 5, "weight": 18},
    {"name": "Bottes de vitesse",  "emoji": "🏃", "rarity": "épique",     "def": 9, "crit": 5, "weight": 6},
    {"name": "Bottes ailées",      "emoji": "🪽", "rarity": "légendaire", "def": 14, "crit": 10, "weight": 1},
]

ACCESSORIES = [
    {"name": "Bracelet en cuir",     "emoji": "💍", "rarity": "commune",    "atk": 1, "weight": 40},
    {"name": "Anneau d'argent",      "emoji": "💎", "rarity": "commune",    "atk": 2, "weight": 35},
    {"name": "Collier de chasseur",  "emoji": "📿", "rarity": "rare",       "atk": 5, "weight": 18},
    {"name": "Anneau enchanté",      "emoji": "💠", "rarity": "épique",     "atk": 9, "crit": 5, "weight": 6},
    {"name": "Amulette divine",      "emoji": "🌟", "rarity": "légendaire", "atk": 15, "crit": 10, "weight": 1},
]

TRINKETS = [
    {"name": "Pierre porte-bonheur", "emoji": "🪨", "rarity": "commune",    "crit": 2, "weight": 40},
    {"name": "Fiole d'huile",        "emoji": "🍶", "rarity": "commune",    "crit": 3, "weight": 35},
    {"name": "Plume mystique",       "emoji": "🪶", "rarity": "rare",       "crit": 7, "weight": 18},
    {"name": "Cristal magique",      "emoji": "🔮", "rarity": "épique",     "crit": 12, "atk": 3, "weight": 6},
    {"name": "Œil de dragon",        "emoji": "🐉", "rarity": "légendaire", "crit": 20, "atk": 5, "weight": 1},
]


def _bias_pool(pool: list, rarity_bias: float) -> list:
    """Helper : applique un bias de rareté à un pool."""
    if rarity_bias == 1.0:
        return pool
    out = []
    for item in pool:
        new_item = dict(item)
        if item["rarity"] in ("épique", "légendaire"):
            new_item["weight"] = max(1, int(item["weight"] * rarity_bias))
        out.append(new_item)
    return out


def random_helmet(rarity_bias: float = 1.0) -> dict:
    """Phase 102 : génère un helmet aléatoire."""
    pool = _bias_pool(HELMETS, rarity_bias)
    item = dict(_weighted_choice(pool))
    item["slot"] = "helmet"
    return item


def random_boots(rarity_bias: float = 1.0) -> dict:
    """Phase 102 : génère des boots aléatoires."""
    pool = _bias_pool(BOOTS_LIST, rarity_bias)
    item = dict(_weighted_choice(pool))
    item["slot"] = "boots"
    return item


def random_accessory(rarity_bias: float = 1.0) -> dict:
    """Phase 102 : génère un accessoire aléatoire."""
    pool = _bias_pool(ACCESSORIES, rarity_bias)
    item = dict(_weighted_choice(pool))
    item["slot"] = "accessory"
    return item


def random_trinket(rarity_bias: float = 1.0) -> dict:
    """Phase 102 : génère un trinket aléatoire."""
    pool = _bias_pool(TRINKETS, rarity_bias)
    item = dict(_weighted_choice(pool))
    item["slot"] = "trinket"
    return item


def random_gear_any(rarity_bias: float = 1.0) -> dict:
    """Phase 102 : tire un item dans n'importe quel slot (6 types).

    Pondération équilibrée : weapon/armor 25% chacun, helmet/boots/accessory/trinket
    12.5% chacun (les nouveaux slots droppent moins souvent que weapon/armor).

    Phase 104 : applique un enchantment aléatoire (30% chance sur épique+,
    60% chance sur légendaire+).
    """
    r = random.random()
    if r < 0.25:
        item = random_weapon(rarity_bias)
        item["slot"] = "weapon"
    elif r < 0.50:
        item = random_armor(rarity_bias)
        item["slot"] = "armor"
    elif r < 0.625:
        item = random_helmet(rarity_bias)
    elif r < 0.75:
        item = random_boots(rarity_bias)
    elif r < 0.875:
        item = random_accessory(rarity_bias)
    else:
        item = random_trinket(rarity_bias)

    # Phase 104 : enchantment chance basée sur rareté
    rarity = item.get("rarity", "commune")
    enchant_chance = {
        "commune": 0.0,
        "rare": 0.10,
        "épique": 0.30,
        "légendaire": 0.60,
        "mythique": 0.85,
        "divine": 1.0,
    }.get(rarity, 0.0)
    if random.random() < enchant_chance:
        item["enchant"] = random_enchantment(rarity_bias)

    return item


# ─── Phase 104 : ENCHANTMENTS (modifiers magiques) ───────────────────────

ENCHANTMENTS = [
    # COMMON enchantments (small bonuses)
    {"id": "flamme",     "name": "Flamme",        "emoji": "🔥", "atk_bonus": 3,                            "weight": 30, "tier": "minor",  "desc": "+3 ATK"},
    {"id": "givre",      "name": "Givre",          "emoji": "❄️",  "def_bonus": 3,                            "weight": 30, "tier": "minor",  "desc": "+3 DEF"},
    {"id": "vif",        "name": "Vif",            "emoji": "💨",  "crit_bonus": 3,                           "weight": 30, "tier": "minor",  "desc": "+3% CRIT"},
    # MID enchantments
    {"id": "vampirisme", "name": "Vampirisme",     "emoji": "🩸",  "lifesteal": 0.05, "atk_bonus": 2,         "weight": 15, "tier": "mid",    "desc": "5% lifesteal · +2 ATK"},
    {"id": "fureur",     "name": "Fureur",         "emoji": "💢",  "atk_bonus": 6,                            "weight": 15, "tier": "mid",    "desc": "+6 ATK"},
    {"id": "endurant",   "name": "Endurant",       "emoji": "🛡️",  "def_bonus": 6, "hp_bonus": 10,            "weight": 15, "tier": "mid",    "desc": "+6 DEF · +10 HP"},
    # MAJOR enchantments
    {"id": "tonnerre",   "name": "Tonnerre",       "emoji": "⚡",  "atk_bonus": 8, "crit_bonus": 5,           "weight": 6,  "tier": "major",  "desc": "+8 ATK · +5% CRIT"},
    {"id": "divin",      "name": "Bénédiction divine","emoji": "🌟", "atk_bonus": 5, "def_bonus": 5, "crit_bonus": 5, "weight": 6, "tier": "major", "desc": "+5 ATK/DEF/CRIT"},
    {"id": "chaos",      "name": "Chaos",          "emoji": "🌀",  "atk_bonus": 10, "crit_bonus": -3,         "weight": 4,  "tier": "major",  "desc": "+10 ATK · −3% CRIT (chaos)"},
    # MYTHIC enchantments
    {"id": "phoenix",    "name": "Phénix",         "emoji": "🦅",  "atk_bonus": 12, "crit_bonus": 8, "lifesteal": 0.08, "weight": 2, "tier": "mythic", "desc": "+12 ATK · +8% CRIT · 8% lifesteal"},
    {"id": "dragon",     "name": "Souffle du Dragon","emoji": "🐉", "atk_bonus": 15, "crit_bonus": 10,         "weight": 1,  "tier": "mythic", "desc": "+15 ATK · +10% CRIT"},
]


def random_enchantment(rarity_bias: float = 1.0) -> dict:
    """Phase 104 : tire un enchantment aléatoire pondéré.

    Plus le rarity_bias est élevé, plus on favorise les tiers mid/major/mythic.
    """
    if rarity_bias != 1.0:
        adjusted = []
        for e in ENCHANTMENTS:
            new_e = dict(e)
            if e["tier"] in ("mid", "major", "mythic"):
                new_e["weight"] = max(1, int(e["weight"] * rarity_bias))
            adjusted.append(new_e)
        chosen = dict(_weighted_choice(adjusted))
    else:
        chosen = dict(_weighted_choice(ENCHANTMENTS))
    # Return only the keys utiles (pas weight/tier internes)
    return {
        "id": chosen["id"],
        "name": chosen["name"],
        "emoji": chosen["emoji"],
        "desc": chosen["desc"],
        "atk_bonus": chosen.get("atk_bonus", 0),
        "def_bonus": chosen.get("def_bonus", 0),
        "crit_bonus": chosen.get("crit_bonus", 0),
        "hp_bonus": chosen.get("hp_bonus", 0),
        "lifesteal": chosen.get("lifesteal", 0.0),
    }


def gear_total_stats(item: dict) -> dict:
    """Phase 104 : calcule les stats totales d'un item (base + enchant).

    Retourne {atk, def, crit, hp_bonus, lifesteal}.
    """
    base_atk = int(item.get("atk", 0) or 0)
    base_def = int(item.get("def", 0) or 0)
    base_crit = int(item.get("crit", 0) or 0)
    enchant = item.get("enchant") or {}
    return {
        "atk": base_atk + int(enchant.get("atk_bonus", 0) or 0),
        "def": base_def + int(enchant.get("def_bonus", 0) or 0),
        "crit": base_crit + int(enchant.get("crit_bonus", 0) or 0),
        "hp_bonus": int(enchant.get("hp_bonus", 0) or 0),
        "lifesteal": float(enchant.get("lifesteal", 0.0) or 0.0),
    }


# ─── Phase 106 : Set Bonuses (basés sur rareté) ──────────────────────────
#
# Plus l'inventaire contient d'items de haute rareté, plus le bonus de set
# devient puissant. Récompense la collection et l'investissement long terme.
#
# Niveaux de set (par rareté minimum + nombre d'items requis) :
# - 2+ rare        → 🌱 Apprenti     : +5 ATK
# - 2+ épique      → 💪 Vétéran      : +10 ATK +5 DEF
# - 2+ légendaire  → 🔥 Champion     : +15 ATK +5 DEF +5% CRIT
# - 4+ légendaire  → ⚡ Champion Suprême : +20 ATK +10 DEF +10% CRIT
# - 6  mythique    → 🌌 Divin (FULL)  : +30 ATK +20 DEF +15% CRIT
#
# Note : seul le PLUS HAUT set actif est compté (pas cumulatif).

EQUIPMENT_SLOTS = ["weapon", "armor", "helmet", "boots", "accessory", "trinket"]


def compute_set_bonus(inventory: dict) -> dict:
    """Phase 106 : retourne le bonus de set actif (le plus haut tier).

    Retourne {name, emoji, atk, def, crit, hp_bonus, desc, color}.
    Si aucun set actif : {name='', ...zéros}.
    """
    if not inventory:
        return {"name": "", "emoji": "", "atk": 0, "def": 0, "crit": 0,
                "hp_bonus": 0, "desc": "", "color": 0x95A5A6, "tier_count": 0}

    # Compter par rareté
    counts = {"commune": 0, "rare": 0, "épique": 0, "légendaire": 0, "mythique": 0, "divine": 0}
    for slot in EQUIPMENT_SLOTS:
        item = inventory.get(slot) or {}
        if not item or not item.get("name"):
            continue
        r = (item.get("rarity") or "commune").lower()
        # Normaliser épique/epique
        if r == "epique":
            r = "épique"
        elif r == "legendaire":
            r = "légendaire"
        if r in counts:
            counts[r] += 1

    # Détecter le plus haut set actif (du plus haut au plus bas)
    # 6 mythique → Divin
    if counts["mythique"] >= 6:
        return {
            "name": "Divin",
            "emoji": "🌌",
            "atk": 30, "def": 20, "crit": 15, "hp_bonus": 50,
            "desc": "6 items mythiques équipés — bonus FULL DIVIN",
            "color": 0xE74C3C,
            "tier_count": counts["mythique"],
        }

    # 4+ légendaire → Champion Suprême
    if counts["légendaire"] + counts["mythique"] >= 4:
        return {
            "name": "Champion Suprême",
            "emoji": "⚡",
            "atk": 20, "def": 10, "crit": 10, "hp_bonus": 25,
            "desc": "4+ items légendaires/mythiques équipés",
            "color": 0xF1C40F,
            "tier_count": counts["légendaire"] + counts["mythique"],
        }

    # 2+ légendaire → Champion
    if counts["légendaire"] + counts["mythique"] >= 2:
        return {
            "name": "Champion",
            "emoji": "🔥",
            "atk": 15, "def": 5, "crit": 5, "hp_bonus": 15,
            "desc": "2+ items légendaires/mythiques équipés",
            "color": 0xE67E22,
            "tier_count": counts["légendaire"] + counts["mythique"],
        }

    # 2+ épique → Vétéran
    if counts["épique"] + counts["légendaire"] + counts["mythique"] >= 2:
        return {
            "name": "Vétéran",
            "emoji": "💪",
            "atk": 10, "def": 5, "crit": 0, "hp_bonus": 10,
            "desc": "2+ items épiques+ équipés",
            "color": 0x9B59B6,
            "tier_count": counts["épique"] + counts["légendaire"] + counts["mythique"],
        }

    # 2+ rare → Apprenti
    if counts["rare"] + counts["épique"] + counts["légendaire"] + counts["mythique"] >= 2:
        return {
            "name": "Apprenti",
            "emoji": "🌱",
            "atk": 5, "def": 0, "crit": 0, "hp_bonus": 5,
            "desc": "2+ items rares+ équipés",
            "color": 0x3498DB,
            "tier_count": counts["rare"] + counts["épique"] + counts["légendaire"] + counts["mythique"],
        }

    return {
        "name": "", "emoji": "", "atk": 0, "def": 0, "crit": 0,
        "hp_bonus": 0, "desc": "Équipe 2+ items rares pour activer un set",
        "color": 0x95A5A6, "tier_count": 0,
    }


def inventory_total_stats(inventory: dict) -> dict:
    """Phase 106 : stats TOTALES (gear + set bonus) pour l'inventaire complet.

    Phase 107 : items à 0 durabilité n'apportent AUCUNE stat (cassés).

    Retourne {atk, def, crit, hp_bonus, lifesteal, set_name, set_emoji}.
    """
    total_atk = 0
    total_def = 0
    total_crit = 0
    total_hp_bonus = 0
    total_lifesteal = 0.0
    for slot in EQUIPMENT_SLOTS:
        item = inventory.get(slot) or {}
        if not item:
            continue
        # Phase 107 : skip items cassés (durabilité <= 0)
        if is_item_broken(item):
            continue
        s = gear_total_stats(item)
        total_atk += s["atk"]
        total_def += s["def"]
        total_crit += s["crit"]
        total_hp_bonus += s["hp_bonus"]
        total_lifesteal += s["lifesteal"]

    # Phase 106 : ajouter set bonus
    set_bonus = compute_set_bonus(inventory)
    total_atk += set_bonus["atk"]
    total_def += set_bonus["def"]
    total_crit += set_bonus["crit"]
    total_hp_bonus += set_bonus["hp_bonus"]

    return {
        "atk": total_atk,
        "def": total_def,
        "crit": total_crit,
        "hp_bonus": total_hp_bonus,
        "lifesteal": total_lifesteal,
        "set_name": set_bonus["name"],
        "set_emoji": set_bonus["emoji"],
        "set_desc": set_bonus["desc"],
    }


# ─── Phase 107 : Durability / Repair ─────────────────────────────────────
#
# Chaque item équipé possède une durabilité max (selon rareté).
# Chaque combat consomme 1 point. À 0 → item cassé : stats désactivées
# jusqu'à réparation. Coût de réparation = base * (max - current).
#
# Durabilité par rareté :
# - commune    : 30  pts
# - rare       : 50  pts
# - épique     : 80  pts
# - légendaire : 120 pts
# - mythique   : 200 pts
# - divine     : 300 pts
#
# Coût base par point manquant :
# - commune    : 2 coins/pt
# - rare       : 5 coins/pt
# - épique     : 12 coins/pt
# - légendaire : 25 coins/pt
# - mythique   : 50 coins/pt
# - divine     : 100 coins/pt

DURABILITY_MAX_BY_RARITY = {
    "commune": 30,
    "rare": 50,
    "épique": 80,
    "epique": 80,  # alias
    "légendaire": 120,
    "legendaire": 120,  # alias
    "mythique": 200,
    "divine": 300,
}

REPAIR_COST_PER_POINT = {
    "commune": 2,
    "rare": 5,
    "épique": 12,
    "epique": 12,
    "légendaire": 25,
    "legendaire": 25,
    "mythique": 50,
    "divine": 100,
}


def get_max_durability(item: dict) -> int:
    """Phase 107 : durabilité max d'un item selon sa rareté.

    Si item.max_durability déjà défini → on le respecte (override custom).
    Sinon → calcul depuis rareté.
    """
    if not item:
        return 0
    if "max_durability" in item and item["max_durability"]:
        return int(item["max_durability"])
    r = (item.get("rarity") or "commune").lower()
    return DURABILITY_MAX_BY_RARITY.get(r, 30)


def get_current_durability(item: dict) -> int:
    """Phase 107 : durabilité actuelle d'un item.

    Si non défini → on retourne le max (item neuf).
    Rétro-compatible avec items legacy (sans champ durability).
    """
    if not item:
        return 0
    if "durability" in item and item["durability"] is not None:
        return max(0, int(item["durability"]))
    return get_max_durability(item)


def is_item_broken(item: dict) -> bool:
    """Phase 107 : True si l'item est cassé (durability <= 0)."""
    if not item or not item.get("name"):
        return False
    return get_current_durability(item) <= 0


def init_item_durability(item: dict) -> dict:
    """Phase 107 : initialise durability/max_durability sur un item neuf.

    Idempotent : si déjà initialisé, ne change rien.
    Mutation in-place + return same dict pour chaînage.
    """
    if not item or not item.get("name"):
        return item
    max_dur = get_max_durability(item)
    item["max_durability"] = max_dur
    if "durability" not in item or item["durability"] is None:
        item["durability"] = max_dur
    return item


def consume_durability(inventory: dict, points: int = 1) -> list:
    """Phase 107 : retire `points` à chaque item équipé.

    Retourne la liste des items qui viennent de CASSER (passage à 0).
    Mutation in-place de l'inventaire.
    """
    just_broken = []
    if not inventory:
        return just_broken
    for slot in EQUIPMENT_SLOTS:
        item = inventory.get(slot) or {}
        if not item or not item.get("name"):
            continue
        # Initialiser si nécessaire (rétro-compat)
        if "max_durability" not in item:
            init_item_durability(item)
        cur = get_current_durability(item)
        new_dur = max(0, cur - points)
        was_alive = cur > 0
        item["durability"] = new_dur
        if was_alive and new_dur == 0:
            just_broken.append({"slot": slot, "item": dict(item)})
    return just_broken


def repair_cost(item: dict) -> int:
    """Phase 107 : coût total pour réparer un item à 100%."""
    if not item or not item.get("name"):
        return 0
    max_dur = get_max_durability(item)
    cur = get_current_durability(item)
    missing = max(0, max_dur - cur)
    if missing == 0:
        return 0
    r = (item.get("rarity") or "commune").lower()
    cost_per_pt = REPAIR_COST_PER_POINT.get(r, 2)
    return missing * cost_per_pt


def repair_inventory_cost(inventory: dict) -> int:
    """Phase 107 : coût TOTAL pour réparer tout l'inventaire."""
    if not inventory:
        return 0
    total = 0
    for slot in EQUIPMENT_SLOTS:
        item = inventory.get(slot) or {}
        total += repair_cost(item)
    return total


def repair_item(item: dict) -> int:
    """Phase 107 : restaure la durabilité d'un item à son max.

    Retourne le coût appliqué (0 si déjà au max).
    Mutation in-place.
    """
    if not item or not item.get("name"):
        return 0
    cost = repair_cost(item)
    item["durability"] = get_max_durability(item)
    return cost


def repair_all_inventory(inventory: dict) -> int:
    """Phase 107 : répare tous les items équipés. Retourne le coût total."""
    if not inventory:
        return 0
    total = 0
    for slot in EQUIPMENT_SLOTS:
        item = inventory.get(slot) or {}
        if not item or not item.get("name"):
            continue
        total += repair_item(item)
    return total


def durability_bar(item: dict, length: int = 10) -> str:
    """Phase 107 : mini-barre visuelle de durabilité.

    █████████░ 90% (108/120)
    """
    if not item or not item.get("name"):
        return ""
    cur = get_current_durability(item)
    mx = get_max_durability(item)
    if mx <= 0:
        return ""
    ratio = max(0.0, min(1.0, cur / mx))
    filled = round(ratio * length)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    pct = int(ratio * 100)
    return f"{bar} {pct}% ({cur}/{mx})"


# ─── Phase 110 : Crafting / Refinement ───────────────────────────────────
#
# Affine un item équipé pour tenter de monter sa rareté d'un cran.
# - Coût en coins selon la rareté ACTUELLE (croissant)
# - Chance de succès décroissante avec les hauts tiers
# - Échec → item perdu (retour à un état "vide")
#
# Conçu pour offrir une vraie tension/risque/reward sans système de stockage
# additionnel (les items équipés sont raffinés directement).

REFINE_RECIPES = {
    # rarity_source → {target, success_pct, cost}
    "commune":    {"target": "rare",       "success_pct": 80, "cost": 500},
    "rare":       {"target": "épique",     "success_pct": 60, "cost": 2000},
    "épique":     {"target": "légendaire", "success_pct": 40, "cost": 8000},
    "légendaire": {"target": "mythique",   "success_pct": 20, "cost": 25000},
    "mythique":   {"target": "divine",     "success_pct":  8, "cost": 75000},
    # Aliases
    "epique":     {"target": "légendaire", "success_pct": 40, "cost": 8000},
    "legendaire": {"target": "mythique",   "success_pct": 20, "cost": 25000},
}


def get_refine_recipe(item: dict) -> Optional[dict]:
    """Phase 110 : retourne la recette d'affinage pour cet item.

    Retourne None si l'item est divine (max) ou inconnu.
    """
    if not item or not item.get("name"):
        return None
    r = (item.get("rarity") or "commune").lower()
    return REFINE_RECIPES.get(r)


def attempt_refine(item: dict, roll: Optional[float] = None) -> tuple:
    """Phase 110 : tente l'affinage de l'item.

    Args:
        item: l'item à raffiner (mutation in-place)
        roll: random.random() optionnel (pour tests)

    Returns:
        (success, result_item_or_empty)
        Si succès : item modifié vers le nouveau tier (stats re-roll)
        Si échec : item vidé ({})
    """
    recipe = get_refine_recipe(item)
    if recipe is None:
        # Pas de recette (item divine ou inconnu)
        return False, item

    if roll is None:
        roll = random.random()
    success = roll * 100 < recipe["success_pct"]

    if not success:
        return False, {}

    # Re-roll de l'item vers la nouvelle rareté
    target_rarity = recipe["target"]
    slot = item.get("slot", "weapon")
    pool_map = {
        "weapon": WEAPONS,
        "armor": ARMOR,
        "helmet": HELMETS,
        "boots": BOOTS_LIST,
        "accessory": ACCESSORIES,
        "trinket": TRINKETS,
    }
    pool = pool_map.get(slot, WEAPONS)
    # Filtrer le pool par target_rarity
    candidates = [x for x in pool if (x.get("rarity") or "").lower() == target_rarity.lower()]

    if candidates:
        # Pool contient des items de cette rareté → pick directement
        new_item = dict(random.choice(candidates))
    else:
        # Phase 112 : pool vide pour cette rareté → fallback
        # On prend l'item le plus haut tier dispo + scaling des stats au target tier
        # Ordre des raretés du moins au plus rare
        order = ["commune", "rare", "épique", "légendaire", "mythique", "divine"]
        # Trouver le tier max du pool
        pool_by_rarity = {}
        for itm in pool:
            r = (itm.get("rarity") or "commune").lower()
            pool_by_rarity.setdefault(r, []).append(itm)
        # Pick l'item du plus haut tier dispo
        highest_available = None
        for r in reversed(order):
            if r in pool_by_rarity:
                highest_available = random.choice(pool_by_rarity[r])
                break
        if not highest_available:
            highest_available = random.choice(pool)
        new_item = dict(highest_available)
        # Scaling : multiplier les stats par le ratio (target_tier_index / source_tier_index)
        src_idx = order.index((new_item.get("rarity") or "commune").lower()) if (new_item.get("rarity") or "").lower() in order else 0
        tgt_idx = order.index(target_rarity) if target_rarity in order else src_idx
        if tgt_idx > src_idx:
            # Multiplier 1.5x par tier d'écart
            mult = 1.5 ** (tgt_idx - src_idx)
            for stat_key in ("atk", "def", "crit"):
                if stat_key in new_item and new_item[stat_key]:
                    new_item[stat_key] = int(new_item[stat_key] * mult)

    new_item["slot"] = slot
    new_item["rarity"] = target_rarity  # force la rareté target
    init_item_durability(new_item)
    return True, new_item


def random_boss(difficulty: int = 100, season_key: Optional[str] = None) -> dict:
    """Boss aléatoire. `difficulty` = facteur 50-500 (100 = normal).

    Phase 176 : le boss reçoit un NOM ÉPIQUE unique (prénom + épithète, thématisé
    par la saison). Le type d'origine ("Dragon Ancestral"...) est conservé dans
    `archetype` pour le lore, et l'emoji du type est gardé en tête du nom.
    """
    template = dict(random.choice(BOSS_CATALOG))
    base_hp = int(800 * template["hp_scale"])
    final_hp = int(base_hp * (difficulty / 100.0))
    template["max_hp"] = max(100, final_hp)
    template["current_hp"] = template["max_hp"]
    # Nom épique : <emoji> <Prénom> <épithète>  (ex : "🐉 Vorthak le Dévoreur")
    emoji = template.get("emoji", "👹")
    template["archetype"] = template.get("name", "Boss")  # garde le type pour le lore
    title = generate_boss_title(season_key)
    template["title"] = title
    template["name"] = f"{emoji} {title}"
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

def compute_rewards(
    participants: list[dict],
    boss_max_hp: int,
    victory: bool,
    coin_multiplier: float = 1.0,
    player_inventories: Optional[dict] = None,
) -> list[dict]:
    """Calcule les récompenses pour chaque participant.

    participants : [{"user_id": int, "damage": int, "attacks": int}, ...]
    player_inventories : Phase 39 — optionnel : {user_id: {"weapon": {...}, "armor": {...}}}
                         Permet d'appliquer le soft cap (moins de chance de drop de la même rareté).
    Retourne : [{"user_id": int, "coins": int, "gear": Optional[dict]}, ...]
    """
    if not participants:
        return []

    player_inventories = player_inventories or {}

    rewards = []
    sorted_parts = sorted(participants, key=lambda p: p.get("damage", 0), reverse=True)
    top_3_ids = {p["user_id"] for p in sorted_parts[:3]}

    for p in participants:
        dmg = p.get("damage", 0)
        atks = p.get("attacks", 0)
        if victory:
            base_coins = int(50 + (dmg / boss_max_hp) * 500)
        else:
            base_coins = int(10 + (dmg / boss_max_hp) * 100)
        coins = int(base_coins * coin_multiplier)

        gear = None
        if victory:
            drop_chance = 0.5 if p["user_id"] in top_3_ids else 0.2
            if random.random() < drop_chance:
                # 50/50 weapon ou armor
                slot = "weapon" if random.random() < 0.5 else "armor"
                rarity_bias = 2.0 if p["user_id"] in top_3_ids else 1.0

                # Phase 39 : SOFT CAP — si le joueur a déjà la même rareté ou plus,
                # on RÉDUIT massivement la chance de drop de rareté équivalente.
                # Force la diversité et la rareté des hauts tiers.
                inv = player_inventories.get(p["user_id"], {})
                current = inv.get(slot, {}) or {}
                current_rarity = current.get("rarity", "commune")
                current_order = RARITY_ORDER.get(current_rarity, 0)

                # On essaie de générer un gear plusieurs fois, en respectant le soft cap
                for attempt in range(5):
                    candidate = random_weapon(rarity_bias=rarity_bias) if slot == "weapon" else random_armor(rarity_bias=rarity_bias)
                    cand_rarity = candidate.get("rarity", "commune")
                    cand_order = RARITY_ORDER.get(cand_rarity, 0)

                    # Soft cap : si le candidat est de rareté égale ou inférieure
                    # à ce que le joueur a déjà, on a 80% de chance de re-tirer
                    # (donc on essaie de drop quelque chose de mieux)
                    if cand_order <= current_order and current_order > 0:
                        if random.random() < 0.80:
                            continue  # re-tirage
                    # Si le candidat est supérieur, on accepte mais avec soft cap
                    # sur les hauts tiers (mythique/divine ont chacun 60% de drop)
                    if cand_order >= 4:  # mythique ou divine
                        if random.random() > 0.40:  # 60% chance de rejet → reroll
                            continue
                    gear = candidate
                    gear["slot"] = slot
                    break

                if not gear:
                    # Fallback : tirage simple
                    if slot == "weapon":
                        gear = random_weapon()
                    else:
                        gear = random_armor()
                    gear["slot"] = slot

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
    # Phase 113 — Achievements pour les nouveaux systèmes (Swap/Auction/Craft)
    {"id": "first_swap",     "name": "Premier Marché",     "emoji": "🤝", "desc": "Compléter ton premier échange P2P"},
    {"id": "merchant",       "name": "Marchand",           "emoji": "💼", "desc": "Compléter 5 échanges P2P"},
    {"id": "first_auction",  "name": "Commissaire-Priseur","emoji": "🔨", "desc": "Vendre ton premier item aux enchères"},
    {"id": "tycoon",         "name": "Magnat des Enchères","emoji": "💎", "desc": "Vendre 10 items aux enchères"},
    {"id": "first_bid_won",  "name": "Premier Coup",       "emoji": "🎯", "desc": "Gagner ta première enchère"},
    {"id": "auction_baron",  "name": "Baron des Enchères", "emoji": "👑", "desc": "Gagner 5 enchères"},
    {"id": "first_refine",   "name": "Apprenti Forgeron",  "emoji": "⚒️", "desc": "Réussir ton premier affinage"},
    {"id": "master_smith",   "name": "Maître Forgeron",    "emoji": "🔥", "desc": "Réussir 10 affinages"},
    {"id": "the_divine",     "name": "Touché par le Divin","emoji": "🌌", "desc": "Affiner un item jusqu'au tier divine"},
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

    # Phase 113 — Nouveaux systèmes (Swap/Auction/Craft)
    _unlock("first_swap",     int(s.get("swaps_done", 0)) >= 1)
    _unlock("merchant",       int(s.get("swaps_done", 0)) >= 5)
    _unlock("first_auction",  int(s.get("auctions_sold", 0)) >= 1)
    _unlock("tycoon",         int(s.get("auctions_sold", 0)) >= 10)
    _unlock("first_bid_won",  int(s.get("auctions_won", 0)) >= 1)
    _unlock("auction_baron",  int(s.get("auctions_won", 0)) >= 5)
    _unlock("first_refine",   int(s.get("refines_success", 0)) >= 1)
    _unlock("master_smith",   int(s.get("refines_success", 0)) >= 10)
    _unlock("the_divine",     bool(s.get("has_divine", False)))

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
    """Génère un trésor aléatoire pondéré + sa loot.

    Phase 102 : drop possible dans les 6 slots via random_gear_any (bias 1.5
    pour favoriser épique/légendaire).
    """
    template = dict(_weighted_choice(TREASURE_CATALOG))
    template["coins"] = random.randint(template["coins_min"], template["coins_max"])
    template["gear"] = None
    if random.random() < template["gear_chance"]:
        template["gear"] = random_gear_any(rarity_bias=1.5)
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
    """Génère une mystery box aléatoire pondérée.

    Phase 102 : drop possible dans les 6 slots (weapon/armor/helmet/boots/accessory/trinket)
    via random_gear_any() qui pondère 25%/25%/12.5%/12.5%/12.5%/12.5%.
    """
    box = dict(_weighted_choice(MYSTERY_BOX_TYPES))
    box["coins"] = random.randint(box["coins_min"], box["coins_max"])
    box["gear"] = None
    if random.random() < box["gear_chance"]:
        box["gear"] = random_gear_any(rarity_bias=1.2)
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


# =============================================================================
# PHASE 37 — SYSTÈME DE CLASSES (6 classes)
# Chaque membre peut choisir une classe qui modifie son rôle pendant les events.
# =============================================================================

CLASSES = [
    {
        "id": "tank",
        "name": "🛡️ Tank",
        "emoji": "🛡️",
        "color": 0x95A5A6,
        "description": "Encaisse les coups. +50% PV, peut absorber 20% des dégâts d'un allié.",
        "hp_mult": 1.5,
        "dmg_mult": 0.85,
        "ability": "shield",
        "ability_desc": "Protège un allié pendant 1 phase",
    },
    {
        "id": "dps",
        "name": "⚔️ DPS",
        "emoji": "⚔️",
        "color": 0xE74C3C,
        "description": "Tueur de boss. +30% dégâts purs sur le boss.",
        "hp_mult": 1.0,
        "dmg_mult": 1.30,
        "ability": None,
    },
    {
        "id": "healer",
        "name": "🩹 Healer",
        "emoji": "🩹",
        "color": 0x2ECC71,
        "description": "Soigneur. Dégâts -20% mais peut soigner un allié pour +25 PV.",
        "hp_mult": 1.0,
        "dmg_mult": 0.80,
        "ability": "heal",
        "ability_desc": "Soigne +25 PV à un allié (cooldown 60s)",
    },
    {
        "id": "mage",
        "name": "🔮 Mage",
        "emoji": "🔮",
        "color": 0x9B59B6,
        "description": "Critiques massifs. Chance de critique 25% au lieu de 10%.",
        "hp_mult": 1.0,
        "dmg_mult": 1.0,
        "crit_chance": 0.25,  # vs 0.10 défaut
        "ability": None,
    },
    {
        "id": "rogue",
        "name": "🗡️ Rogue",
        "emoji": "🗡️",
        "color": 0xF39C12,
        "description": "Furtif et rapide. 30% chance d'enchaîner 2 attaques d'un coup.",
        "hp_mult": 1.0,
        "dmg_mult": 1.0,
        "double_attack_chance": 0.30,
        "ability": None,
    },
    {
        "id": "bard",
        "name": "🎤 Bard",
        "emoji": "🎤",
        "color": 0x1ABC9C,
        "description": "Soutien vocal. +15% dégâts à tous les alliés dans le MÊME vocal.",
        "hp_mult": 1.0,
        "dmg_mult": 0.90,
        "vocal_aura": 0.15,
        "ability": None,
    },
]


def get_class(class_id: Optional[str]) -> Optional[dict]:
    """Retourne la classe par id (ou None)."""
    if not class_id:
        return None
    for c in CLASSES:
        if c["id"] == class_id:
            return c
    return None


# =============================================================================
# PHASE 37 — ZONES VOCALES (lors d'un raid)
# 3 sous-vocaux créés pendant un boss raid avec des bonus/malus distincts.
# =============================================================================

VOICE_ZONES = [
    {
        "id": "offensive",
        "name": "⚔️ Zone Offensive",
        "color": 0xE74C3C,
        "dmg_mult": 1.40,        # +40% dégâts infligés
        "dmg_taken_mult": 1.20,  # +20% dégâts subis du boss
        "description": "+40% dégâts au boss, mais +20% dégâts subis lors des phases.",
    },
    {
        "id": "defense",
        "name": "🛡️ Zone Défense",
        "color": 0x3498DB,
        "dmg_mult": 0.70,        # -30% dégâts infligés
        "dmg_taken_mult": 0.60,  # -40% dégâts subis du boss
        "description": "−30% dégâts au boss, mais −40% dégâts subis lors des phases.",
    },
    {
        "id": "soin",
        "name": "🩹 Zone Soin",
        "color": 0x2ECC71,
        "dmg_mult": 0.85,
        "dmg_taken_mult": 0.80,
        "regen_per_phase": 25,   # +25 PV à chaque phase passée ici
        "description": "−15% dégâts mais régénère +25 PV à chaque phase.",
    },
]


def get_voice_zone(zone_id: Optional[str]) -> Optional[dict]:
    if not zone_id:
        return None
    for z in VOICE_ZONES:
        if z["id"] == zone_id:
            return z
    return None


# =============================================================================
# PHASE 37 — CALCUL DE DÉGÂTS AVANCÉ (avec classe + vocal + bard aura)
# =============================================================================

def calc_damage_v2(
    weapon: Optional[dict],
    player_class_id: Optional[str] = None,
    voice_zone_id: Optional[str] = None,
    allies_in_same_voice: int = 0,
    bard_in_same_voice: bool = False,
    inventory: Optional[dict] = None,
) -> tuple[int, bool, bool, dict]:
    """Calcul de dégâts avec toutes les modifications Phase 37 + 105.

    Phase 105 : `inventory` (full dict) permet d'inclure enchants de tous les
    slots (weapon/armor/helmet/boots/accessory/trinket). Si non fourni,
    fallback sur weapon seul (backward compat).

    Retourne (final_damage, is_crit, is_double_attack, details_dict).
    """
    base = random.randint(10, 25)

    # Phase 105 + 106 : calcul stats totales depuis l'inventaire complet
    # Inclut gear (base + enchant) + set bonus
    set_bonus_active = None
    if inventory:
        totals = inventory_total_stats(inventory)
        gear_atk = totals["atk"]
        gear_crit_bonus = totals["crit"]  # en pourcentage
        set_bonus_active = totals["set_name"] or None
    else:
        gear_atk = (weapon or {}).get("atk", 0) if weapon else 0
        if weapon and weapon.get("enchant"):
            gear_atk += int(weapon["enchant"].get("atk_bonus", 0) or 0)
        gear_crit_bonus = 0
        if weapon and weapon.get("enchant"):
            gear_crit_bonus += int(weapon["enchant"].get("crit_bonus", 0) or 0)

    pc = get_class(player_class_id) or {}
    zone = get_voice_zone(voice_zone_id) or {}

    # Phase 105 : crit chance = base class + bonus gear (/100)
    crit_chance = pc.get("crit_chance", 0.10) + (gear_crit_bonus / 100.0)
    crit_chance = min(0.75, max(0.0, crit_chance))  # cap 75%
    dmg_mult_class = pc.get("dmg_mult", 1.0)
    dmg_mult_zone = zone.get("dmg_mult", 1.0)

    # Bard aura : +15% par allié dans le même vocal (max 3)
    bard_bonus_mult = 1.0
    if bard_in_same_voice:
        bard_bonus_mult += 0.15 * min(3, max(0, allies_in_same_voice))

    raw = base + gear_atk
    after_class = raw * dmg_mult_class
    after_zone = after_class * dmg_mult_zone
    after_bard = after_zone * bard_bonus_mult

    is_crit = random.random() < crit_chance
    after_crit = after_bard * (2 if is_crit else 1)

    # Rogue : double attaque
    is_double = False
    if pc.get("double_attack_chance", 0) > 0 and random.random() < pc["double_attack_chance"]:
        is_double = True
        after_crit *= 1.85

    final = int(round(after_crit))

    details = {
        "base": base,
        "weapon_atk": gear_atk,
        "crit_chance": crit_chance,
        "class_mult": dmg_mult_class,
        "zone_mult": dmg_mult_zone,
        "bard_mult": bard_bonus_mult,
        "crit": is_crit,
        "double": is_double,
        "final": final,
        "set_bonus": set_bonus_active,
    }
    return final, is_crit, is_double, details


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
    "RARITY_COLORS", "RARITY_EMOJIS", "RARITY_ORDER",
    "HELP_TIPS", "PERSONAL_RIDDLES",
    "SPEED_REACT_EMOJIS", "MYSTERY_BOX_TYPES", "DAILY_SPARKS",
    "CLASSES", "VOICE_ZONES",
    # Phase 102 : nouveaux slots équipement
    "HELMETS", "BOOTS_LIST", "ACCESSORIES", "TRINKETS",
    # Phase 104 : enchantments
    "ENCHANTMENTS",
    # Generators
    "random_weapon", "random_armor", "random_boss", "random_treasure",
    "random_helmet", "random_boots", "random_accessory", "random_trinket",
    "random_gear_any", "random_enchantment", "gear_total_stats",
    "compute_set_bonus", "inventory_total_stats", "EQUIPMENT_SLOTS",
    # Phase 107 : durability / repair
    "DURABILITY_MAX_BY_RARITY", "REPAIR_COST_PER_POINT",
    "get_max_durability", "get_current_durability", "is_item_broken",
    "init_item_durability", "consume_durability",
    "repair_cost", "repair_inventory_cost", "repair_item", "repair_all_inventory",
    "durability_bar",
    # Phase 110 : crafting / refining
    "REFINE_RECIPES", "get_refine_recipe", "attempt_refine",
    "generate_shop_rotation", "get_quiz_set", "random_personal_event",
    "random_mystery_box", "random_daily_spark",
    # Targeting
    "categorize_member_activity", "targeting_weight", "random_event_intent",
    # Phase 37
    "get_class", "get_voice_zone", "calc_damage_v2",
    # Helpers
    "hp_bar", "calc_damage", "serialize_overwrites", "compute_rewards",
    "check_badge_unlocks", "get_badge_by_id",
    "rank_for_kills", "event_role_for_rank",
    "check_combo",
    "adjust_difficulty",
    "simulate_duel",
    "get_help_footer",
]
