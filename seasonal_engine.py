"""
seasonal_engine.py — Moteur saisonnier qui fait évoluer les events (Phase 144).

🎯 OBJECTIF : empêcher la répétition / l'usure des events. Chaque saison
de l'année transforme automatiquement tous les events du bot :
- Buffs/debuffs (HP boss ×1.5 en Halloween, par exemple)
- Loot exclusif (items qui ne droppent QUE pendant cette saison)
- Thème visuel (couleur + emoji des panels)
- Fréquence ajustée (été = events plus fréquents)

6 saisons couvrent l'année entière, donc le serveur a toujours un thème actif :

| Saison              | Dates           | Thème                          |
|---------------------|-----------------|--------------------------------|
| 🍂 Récolte           | 01 sep → 14 oct | Quêtes longues + drops dorés   |
| 🎃 Voile des Esprits | 15 oct → 05 nov | Boss HP×1.5 + skins spectraux  |
| 🌫️ Brouillard        | 06 nov → 09 déc | Mystery boxes ×2 + drops rares |
| 🎄 Solstice d'Hiver  | 10 déc → 05 jan | Calendrier + cadeaux quotidiens|
| ❄️ Cœur de l'Hiver   | 06 jan → 09 fév | Tâches collectives + intérêts banque ×1.3 |
| 🏆 Festival Tournois | 10 fév → 28 fév | Duels ×2 + leaderboards (PAS St-Valentin romantique) |
| 🌸 Renaissance       | 01 mar → 31 mai | XP ×1.2 + drops végétal       |
| ☀️ Saison du Feu     | 01 juin → 31 août| Events ×1.5 fréquence + drops chaud |

⚠️ Pas de St-Valentin romantique — remplacé par "Festival des Tournois" avec
focus duels/compétitions. Conforme RULES.md (zéro relationnel).

API publique :
- setup(get_db_fn, v2_helpers)
- current_season() -> dict   # toujours retourne UNE saison (jamais None)
- get_modifier(key, default=1.0) -> float
- seasonal_drop_pool() -> list[dict]  # items exclusifs saison actuelle
- maybe_drop_seasonal(extra_chance=0.0) -> dict|None
- build_season_panel(guild_name) -> LayoutView V2
- log_drop_claim(guild_id, user_id, drop_name)  # tracking anti-double
- get_user_seasonal_drops(guild_id, user_id) -> list[dict]

Modifiers exposés (utilisables par tout module) :
- "boss_hp_mult"          (Halloween 1.5, Hiver 1.3)
- "boss_reward_mult"      (Halloween 1.4, Hiver 1.5)
- "duel_reward_mult"      (Tournament 2.0)
- "xp_mult"               (Spring 1.2)
- "event_freq_mult"       (Summer 1.5)
- "quest_reward_mult"     (Autumn 1.4)
- "bank_interest_mult"    (Winter 1.3)
- "mysterybox_drop_mult"  (Brouillard 2.0)

Les events existants peuvent opt-in sans refactor majeur :
  from seasonal_engine import get_modifier
  reward = base_reward * get_modifier("boss_reward_mult")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import random

import discord

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# ═══════════════════════════════════════════════════════════════════════════════
# CATALOGUE DES 8 SAISONS (couvrent 100% de l'année)
# ═══════════════════════════════════════════════════════════════════════════════

SEASONS = [
    {
        "key": "autumn",
        "name": "Récolte",
        "emoji": "🍂",
        "color": 0xD2691E,
        "tagline": "_Le serveur cueille les fruits de l'année — quêtes plus généreuses_",
        "start": (9, 1),   # mois, jour
        "end":   (10, 14),
        "modifiers": {
            "quest_reward_mult": 1.4,
            "xp_mult": 1.1,
        },
        "exclusive_drops": [
            {"name": "Feuille d'Or", "emoji": "🍂", "rarity": "rare",
             "atk": 8, "def": 4, "lore": "Cueillie pendant la chute des feuilles."},
            {"name": "Châtaigne Magique", "emoji": "🌰", "rarity": "épique",
             "atk": 0, "def": 0, "crit": 12, "lore": "Plus dure que le diamant."},
            {"name": "Ramure de Sage", "emoji": "🦌", "rarity": "légendaire",
             "atk": 25, "def": 18, "lore": "Symbole de sagesse ancienne."},
        ],
    },
    {
        "key": "halloween",
        "name": "Voile des Esprits",
        "emoji": "🎃",
        "color": 0xFF6B00,
        "tagline": "_Le voile entre les mondes s'amincit — les boss sont enragés_",
        "start": (10, 15),
        "end":   (11, 5),
        "modifiers": {
            "boss_hp_mult": 1.5,
            "boss_reward_mult": 1.4,
            "mysterybox_drop_mult": 1.3,
        },
        "exclusive_drops": [
            {"name": "Citrouille Hantée", "emoji": "🎃", "rarity": "rare",
             "atk": 10, "def": 6, "lore": "Brille dans le noir."},
            {"name": "Voile Spectral", "emoji": "👻", "rarity": "épique",
             "atk": 0, "def": 22, "crit": 5, "lore": "Te rend partiellement invisible."},
            {"name": "Crâne Ancien", "emoji": "💀", "rarity": "légendaire",
             "atk": 32, "def": 10, "lore": "Murmure le nom de ton prochain ennemi."},
            {"name": "Lame du Néant", "emoji": "🗡️", "rarity": "mythique",
             "atk": 50, "def": 0, "crit": 25, "lore": "Apparue d'entre les ombres."},
        ],
    },
    {
        "key": "fog",
        "name": "Brouillard d'Automne",
        "emoji": "🌫️",
        "color": 0x607D8B,
        "tagline": "_Le mystère plane — boîtes mystères doublées_",
        "start": (11, 6),
        "end":   (12, 9),
        "modifiers": {
            "mysterybox_drop_mult": 2.0,
            "loot_mult": 1.2,
        },
        "exclusive_drops": [
            {"name": "Lanterne du Brouillard", "emoji": "🏮", "rarity": "rare",
             "atk": 5, "def": 15, "lore": "Perce les ténèbres les plus épaisses."},
            {"name": "Boussole Brisée", "emoji": "🧭", "rarity": "épique",
             "atk": 12, "def": 8, "crit": 10, "lore": "Pointe toujours vers le butin."},
            {"name": "Œil du Voyant", "emoji": "👁️", "rarity": "légendaire",
             "atk": 0, "def": 0, "crit": 35, "lore": "Voit ce que les autres ratent."},
        ],
    },
    {
        "key": "solstice",
        "name": "Solstice d'Hiver",
        "emoji": "🎄",
        "color": 0x1E90FF,
        "tagline": "_Le serveur célèbre — cadeaux quotidiens et bonus banque_",
        "start": (12, 10),
        "end":   (1, 5),
        "modifiers": {
            "boss_reward_mult": 1.5,
            "bank_interest_mult": 1.3,
            "daily_mult": 1.5,
        },
        "exclusive_drops": [
            {"name": "Cristal de Glace", "emoji": "❄️", "rarity": "rare",
             "atk": 6, "def": 12, "lore": "Ne fond jamais."},
            {"name": "Cadeau Surprise", "emoji": "🎁", "rarity": "épique",
             "atk": 15, "def": 15, "lore": "Personne ne sait ce qu'il contient."},
            {"name": "Étoile du Nord", "emoji": "🌟", "rarity": "légendaire",
             "atk": 0, "def": 30, "crit": 20, "lore": "Guide les voyageurs perdus."},
            {"name": "Sceptre de Glace", "emoji": "🔱", "rarity": "mythique",
             "atk": 55, "def": 25, "lore": "Forgé au sommet du Mont Blanc."},
        ],
    },
    {
        "key": "deep_winter",
        "name": "Cœur de l'Hiver",
        "emoji": "❄️",
        "color": 0xB0E0E6,
        "tagline": "_Le serveur s'unit contre le froid — quêtes collectives_",
        "start": (1, 6),
        "end":   (2, 9),
        "modifiers": {
            "bank_interest_mult": 1.5,
            "collective_event_bonus": 1.4,
        },
        "exclusive_drops": [
            {"name": "Fourrure de Mammouth", "emoji": "🦣", "rarity": "rare",
             "atk": 4, "def": 25, "lore": "Garde au chaud même en pleine tempête."},
            {"name": "Glaçon Éternel", "emoji": "🧊", "rarity": "épique",
             "atk": 18, "def": 12, "crit": 8, "lore": "Tranchant comme une lame."},
            {"name": "Couronne du Roi-Loup", "emoji": "🐺", "rarity": "légendaire",
             "atk": 28, "def": 22, "crit": 15, "lore": "Symbole de la meute hivernale."},
        ],
    },
    {
        "key": "tournament",
        "name": "Festival des Tournois",
        "emoji": "🏆",
        "color": 0xE91E63,
        "tagline": "_3 semaines de pure compétition — duels doublés_",
        "start": (2, 10),
        "end":   (2, 28),
        "modifiers": {
            "duel_reward_mult": 2.0,
            "combat_mult": 1.5,
            "ladder_xp_mult": 1.5,
        },
        "exclusive_drops": [
            {"name": "Médaille du Champion", "emoji": "🏆", "rarity": "rare",
             "atk": 12, "def": 8, "lore": "Décernée aux duellistes acharnés."},
            {"name": "Lame Doublée", "emoji": "⚔️", "rarity": "épique",
             "atk": 24, "def": 6, "crit": 10, "lore": "Forgée pour les tournois."},
            {"name": "Insigne de Tournoi", "emoji": "🎖️", "rarity": "légendaire",
             "atk": 18, "def": 18, "crit": 20, "lore": "Le sceau des invaincus."},
            {"name": "Gantelet du Vainqueur", "emoji": "🥊", "rarity": "mythique",
             "atk": 45, "def": 15, "crit": 30, "lore": "Brillé par mille victoires."},
        ],
    },
    {
        "key": "spring",
        "name": "Renaissance",
        "emoji": "🌸",
        "color": 0xFF69B4,
        "tagline": "_La nature s'éveille — XP boostée pour tous_",
        "start": (3, 1),
        "end":   (5, 31),
        "modifiers": {
            "xp_mult": 1.2,
            "level_up_bonus": 1.3,
        },
        "exclusive_drops": [
            {"name": "Pétale Magique", "emoji": "🌸", "rarity": "rare",
             "atk": 6, "def": 6, "crit": 8, "lore": "Tombée d'un arbre sacré."},
            {"name": "Aile de Cristal", "emoji": "🦋", "rarity": "épique",
             "atk": 14, "def": 10, "crit": 12, "lore": "Battue par le vent printanier."},
            {"name": "Graine Ancienne", "emoji": "🌱", "rarity": "légendaire",
             "atk": 0, "def": 35, "lore": "Capable de faire pousser des forêts."},
            {"name": "Couronne de Floraison", "emoji": "👑", "rarity": "mythique",
             "atk": 30, "def": 30, "crit": 20, "lore": "Bénit son porteur d'éternité."},
        ],
    },
    {
        "key": "summer",
        "name": "Saison du Feu",
        "emoji": "☀️",
        "color": 0xFFD700,
        "tagline": "_L'été enflamme le serveur — events ×1.5 plus fréquents_",
        "start": (6, 1),
        "end":   (8, 31),
        "modifiers": {
            "event_freq_mult": 1.5,
            "loot_mult": 1.3,
            "coin_mult": 1.2,
        },
        "exclusive_drops": [
            {"name": "Ambre Solaire", "emoji": "☀️", "rarity": "rare",
             "atk": 10, "def": 5, "crit": 5, "lore": "Capture les rayons du soleil."},
            {"name": "Cœur de Flamme", "emoji": "🔥", "rarity": "épique",
             "atk": 22, "def": 4, "crit": 18, "lore": "Bat au rythme du brasier."},
            {"name": "Perle des Profondeurs", "emoji": "🌊", "rarity": "légendaire",
             "atk": 15, "def": 25, "crit": 15, "lore": "Repêchée des fonds marins."},
            {"name": "Lame Forgée au Soleil", "emoji": "🗡️", "rarity": "mythique",
             "atk": 60, "def": 10, "crit": 25, "lore": "Brûle au contact de l'ennemi."},
        ],
    },
]


# Modifiers défauts (utilisés si la saison n'override pas)
DEFAULT_MODIFIERS = {
    "boss_hp_mult": 1.0,
    "boss_reward_mult": 1.0,
    "duel_reward_mult": 1.0,
    "combat_mult": 1.0,
    "xp_mult": 1.0,
    "event_freq_mult": 1.0,
    "quest_reward_mult": 1.0,
    "bank_interest_mult": 1.0,
    "daily_mult": 1.0,
    "mysterybox_drop_mult": 1.0,
    "loot_mult": 1.0,
    "coin_mult": 1.0,
    "ladder_xp_mult": 1.0,
    "level_up_bonus": 1.0,
    "collective_event_bonus": 1.0,
}


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY MYSTERY MODIFIERS — varient chaque jour, déterministe par jour de l'année
# ═══════════════════════════════════════════════════════════════════════════════
# Casino-style : les joueurs ouvrent le panel chaque matin pour voir le bonus
# du jour. 12 variantes en rotation = quasi-jamais le même 2 jours d'affilée.

DAILY_MODIFIERS = [
    {"key": "lucky_morning", "emoji": "🍀", "label": "Matin Chanceux",
     "tagline": "Drop rate ×1.5 toute la journée",
     "modifiers": {"loot_mult": 1.5, "mysterybox_drop_mult": 1.3}},

    {"key": "iron_arena", "emoji": "⚔️", "label": "Arène de Fer",
     "tagline": "Combats et duels boostés",
     "modifiers": {"combat_mult": 1.3, "duel_reward_mult": 1.4}},

    {"key": "scholar", "emoji": "📚", "label": "Jour du Savant",
     "tagline": "XP doublée sur les quêtes",
     "modifiers": {"quest_reward_mult": 1.5, "xp_mult": 1.3}},

    {"key": "merchant", "emoji": "🪙", "label": "Festival du Marchand",
     "tagline": "Coins gagnés multipliés",
     "modifiers": {"coin_mult": 1.4, "bank_interest_mult": 1.2}},

    {"key": "wild_hunt", "emoji": "🐲", "label": "Chasse Sauvage",
     "tagline": "Les boss tombent en plus grand nombre",
     "modifiers": {"event_freq_mult": 1.4, "boss_reward_mult": 1.3}},

    {"key": "treasure_winds", "emoji": "🌬️", "label": "Vents de Trésor",
     "tagline": "Trésors flash et mystery boxes en abondance",
     "modifiers": {"mysterybox_drop_mult": 1.8, "loot_mult": 1.2}},

    {"key": "guild_pride", "emoji": "🏰", "label": "Fierté de Guilde",
     "tagline": "Events collectifs et alliances boostés",
     "modifiers": {"collective_event_bonus": 1.5, "bank_interest_mult": 1.3}},

    {"key": "speedrunner", "emoji": "⚡", "label": "Jour de Vitesse",
     "tagline": "Récompenses ladder et XP combat boostées",
     "modifiers": {"ladder_xp_mult": 1.5, "combat_mult": 1.2}},

    {"key": "patron_saint", "emoji": "🌟", "label": "Étoile du Jour",
     "tagline": "Level up bonus + daily reward boosté",
     "modifiers": {"level_up_bonus": 1.5, "daily_mult": 1.4}},

    {"key": "voidcaller", "emoji": "🔮", "label": "Appel du Néant",
     "tagline": "Mythiques 2× plus probables (drops)",
     "modifiers": {"loot_mult": 1.6, "boss_reward_mult": 1.2}},

    {"key": "rest_day", "emoji": "☕", "label": "Jour de Repos",
     "tagline": "Bonus banque massif — pour ceux qui économisent",
     "modifiers": {"bank_interest_mult": 1.8}},

    {"key": "wild_card", "emoji": "🎰", "label": "Joker du Jour",
     "tagline": "Tous les bonus à +20% — léger mais sur tout",
     "modifiers": {"coin_mult": 1.2, "xp_mult": 1.2, "loot_mult": 1.2,
                   "boss_reward_mult": 1.2, "duel_reward_mult": 1.2}},
]


# ═══════════════════════════════════════════════════════════════════════════════
# WEEKEND SPECIALS — vendredi 18h → dimanche 23h, 6 variantes en rotation
# ═══════════════════════════════════════════════════════════════════════════════

WEEKEND_SPECIALS = [
    {"key": "double_drop_weekend", "emoji": "💎", "label": "Weekend Double Drops",
     "tagline": "Tous les drops sont doublés ce weekend",
     "modifiers": {"loot_mult": 2.0, "mysterybox_drop_mult": 1.5}},

    {"key": "boss_rush_weekend", "emoji": "🐲", "label": "Weekend Boss Rush",
     "tagline": "Boss apparaissent 2× plus souvent + récompenses ×1.6",
     "modifiers": {"event_freq_mult": 2.0, "boss_reward_mult": 1.6}},

    {"key": "duel_fever", "emoji": "⚔️", "label": "Fièvre des Duels",
     "tagline": "Duels doublés + ladder XP ×2",
     "modifiers": {"duel_reward_mult": 2.0, "ladder_xp_mult": 2.0}},

    {"key": "treasure_storm", "emoji": "🌪️", "label": "Tempête de Trésors",
     "tagline": "Mystery boxes ×2.5 + loot ×1.5",
     "modifiers": {"mysterybox_drop_mult": 2.5, "loot_mult": 1.5}},

    {"key": "level_explosion", "emoji": "💥", "label": "Explosion d'XP",
     "tagline": "XP doublée pour tous, niveau accéléré",
     "modifiers": {"xp_mult": 2.0, "level_up_bonus": 1.5,
                   "quest_reward_mult": 1.4}},

    {"key": "coin_rain", "emoji": "🌧️", "label": "Pluie de Coins",
     "tagline": "Tous les gains de coins ×1.8",
     "modifiers": {"coin_mult": 1.8, "daily_mult": 1.5}},
]


# Références injectées
_get_db = None
_v2_helpers = None
_tables_initialized = False


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — table de tracking des drops saisonniers (pour anti-double)
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS seasonal_drops_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                season_key TEXT,
                drop_name TEXT,
                drop_emoji TEXT,
                drop_rarity TEXT,
                claimed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_seasonal_drops_user "
                "ON seasonal_drops_log(guild_id, user_id, season_key)"
            )
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[seasonal_engine _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# DETECT SEASON — toujours retourne UNE saison (fallback summer si gap)
# ═══════════════════════════════════════════════════════════════════════════════

def _is_date_in_range(now_md: tuple[int, int], start: tuple[int, int],
                      end: tuple[int, int]) -> bool:
    """True si now_md ∈ [start, end] (inclusif). Gère le wrap (déc → jan)."""
    if start <= end:
        return start <= now_md <= end
    # Wrap autour de janvier (solstice : 12-10 → 1-5)
    return now_md >= start or now_md <= end


def current_season() -> dict:
    """Retourne la saison active aujourd'hui (Europe/Paris).

    Si aucune saison n'est dans la fenêtre → retourne 'summer' par défaut
    (cas théorique impossible vu la couverture 365j).
    """
    now = datetime.now(_PARIS_TZ)
    now_md = (now.month, now.day)
    for s in SEASONS:
        if _is_date_in_range(now_md, s["start"], s["end"]):
            return s
    # Fallback (ne devrait jamais arriver — toutes les dates sont couvertes)
    return SEASONS[-1]  # summer par défaut


def current_daily_modifier() -> dict:
    """Retourne le DAILY_MODIFIER actif aujourd'hui.

    Déterministe par jour de l'année (rotation sur 12 variantes).
    Casino-style : prévisible mais varié = anticipation des joueurs.
    """
    now = datetime.now(_PARIS_TZ)
    day_of_year = now.timetuple().tm_yday
    return DAILY_MODIFIERS[day_of_year % len(DAILY_MODIFIERS)]


def current_weekend_special() -> Optional[dict]:
    """Retourne le WEEKEND_SPECIAL actif si on est vendredi 18h → dimanche 23h.

    Sinon retourne None. Déterministe par numéro de semaine de l'année.
    """
    now = datetime.now(_PARIS_TZ)
    wd = now.weekday()  # 0=lundi, 4=vendredi, 5=samedi, 6=dimanche
    is_weekend = (
        (wd == 4 and now.hour >= 18) or
        (wd == 5) or
        (wd == 6 and now.hour < 23)
    )
    if not is_weekend:
        return None
    week_of_year = now.isocalendar()[1]
    return WEEKEND_SPECIALS[week_of_year % len(WEEKEND_SPECIALS)]


def get_modifier(key: str, default: float = 1.0) -> float:
    """Retourne le multiplicateur courant pour `key`.

    EMPILE les modifiers : saison × daily × weekend (si actif).
    Donc un Halloween + Lucky Morning + Double Drop Weekend = effet cumulé.

    Ex pendant Halloween (boss_reward_mult=1.4) + Wild Hunt daily (1.3) +
    Boss Rush weekend (1.6) → get_modifier("boss_reward_mult") = 2.91
    """
    final = float(default)

    # Couche 1 : saison
    season = current_season()
    season_mult = float(season.get("modifiers", {}).get(key, default))
    if season_mult != default:
        final *= (season_mult / default) if default != 0 else season_mult

    # Couche 2 : daily mystery
    daily = current_daily_modifier()
    daily_mult = float(daily.get("modifiers", {}).get(key, default))
    if daily_mult != default:
        final *= (daily_mult / default) if default != 0 else daily_mult

    # Couche 3 : weekend special (si actif)
    weekend = current_weekend_special()
    if weekend:
        wk_mult = float(weekend.get("modifiers", {}).get(key, default))
        if wk_mult != default:
            final *= (wk_mult / default) if default != 0 else wk_mult

    return final


def get_all_active_modifiers() -> dict:
    """Retourne un snapshot de tous les modifiers actifs maintenant.

    Utile pour afficher dans le panel /season info l'effet total
    de saison + daily + weekend cumulés.
    """
    season = current_season()
    daily = current_daily_modifier()
    weekend = current_weekend_special()
    return {
        "season": season,
        "daily": daily,
        "weekend": weekend,
    }


def is_in_season(season_key: str) -> bool:
    """True si la saison actuelle a la key fournie."""
    return current_season().get("key") == season_key


# ═══════════════════════════════════════════════════════════════════════════════
# DROPS SAISONNIERS
# ═══════════════════════════════════════════════════════════════════════════════

def seasonal_drop_pool() -> list[dict]:
    """Pool d'items exclusifs à la saison actuelle."""
    return list(current_season().get("exclusive_drops", []))


def maybe_drop_seasonal(extra_chance: float = 0.0) -> Optional[dict]:
    """Tente un drop saisonnier (chance de base 3% + extra).

    À appeler depuis un combat / event victory :
        seasonal_item = seasonal_engine.maybe_drop_seasonal(0.02)  # +2% si event rare
        if seasonal_item:
            # Award à l'utilisateur

    Retourne un dict {name, emoji, rarity, atk, def, crit, lore} ou None.
    """
    base_chance = 0.03 + max(0.0, min(0.5, extra_chance))
    if random.random() > base_chance:
        return None
    pool = seasonal_drop_pool()
    if not pool:
        return None
    # Pondération par rareté (rare > épique > légendaire > mythique)
    weights = []
    for it in pool:
        rar = (it.get("rarity") or "rare").lower()
        weights.append({
            "rare": 10, "épique": 5, "epique": 5,
            "légendaire": 2, "legendaire": 2, "mythique": 1,
        }.get(rar, 5))
    chosen = random.choices(pool, weights=weights, k=1)[0]
    return dict(chosen)  # copy défensive


async def log_drop_claim(
    guild_id: int, user_id: int, drop: dict
) -> bool:
    """Enregistre un drop dans le log (pour /season my_drops)."""
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO seasonal_drops_log "
                "(guild_id, user_id, season_key, drop_name, drop_emoji, drop_rarity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, current_season()["key"],
                 drop.get("name", "?"), drop.get("emoji", "❓"),
                 drop.get("rarity", "commune")),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[seasonal_engine log_drop_claim] {ex}")
        return False


async def get_user_seasonal_drops(
    guild_id: int, user_id: int, season_key: Optional[str] = None
) -> list[dict]:
    """Liste les drops saisonniers que l'user a déjà claim."""
    if _get_db is None:
        return []
    await _ensure_tables()
    sk = season_key or current_season()["key"]
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT drop_name, drop_emoji, drop_rarity, claimed_at "
                "FROM seasonal_drops_log "
                "WHERE guild_id=? AND user_id=? AND season_key=? "
                "ORDER BY claimed_at DESC",
                (guild_id, user_id, sk),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "name": r[0], "emoji": r[1] or "❓",
                "rarity": r[2] or "commune", "claimed_at": r[3],
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[seasonal_engine get_user_seasonal_drops] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# PANELS V2
# ═══════════════════════════════════════════════════════════════════════════════

def _days_until_end_of_season(season: dict) -> int:
    """Nombre de jours restants avant fin de la saison actuelle."""
    now = datetime.now(_PARIS_TZ)
    end_m, end_d = season["end"]
    try:
        # Si l'end est dans une année future (wrap), on calcule pareil
        end_year = now.year
        if (end_m, end_d) < (now.month, now.day):
            end_year += 1
        end_dt = datetime(end_year, end_m, end_d, tzinfo=_PARIS_TZ)
        return max(0, (end_dt - now).days)
    except Exception:
        return 0


def build_season_panel(guild_name: str = ""):
    """Panel V2 — affiche la saison actuelle + modifiers + drops exclusifs."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    season = current_season()
    days_left = _days_until_end_of_season(season)

    class _SeasonPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(
                f"{season['emoji']}  SAISON ACTIVE — {season['name'].upper()}"
            ))
            items.append(v2_subtitle(season["tagline"]))
            items.append(v2_divider())

            # Compteur jours restants
            items.append(v2_body(
                f"⏳ **Reste : `{days_left}` jour(s)** avant changement de saison.\n"
                f"_Profite des bonus et des drops exclusifs maintenant !_"
            ))

            # Bonus de saison
            mods = season.get("modifiers", {})
            if mods:
                items.append(v2_divider())
                items.append(v2_body("### ✨ BONUS DE SAISON"))
                mod_labels = {
                    "boss_hp_mult": "🐲 Boss HP",
                    "boss_reward_mult": "🏆 Récompenses boss",
                    "duel_reward_mult": "⚔️ Récompenses duels",
                    "combat_mult": "⚔️ Combats",
                    "xp_mult": "📈 XP",
                    "event_freq_mult": "🎯 Fréquence events",
                    "quest_reward_mult": "📜 Récompenses quêtes",
                    "bank_interest_mult": "🏦 Intérêts banque",
                    "daily_mult": "🎁 Daily reward",
                    "mysterybox_drop_mult": "📦 Mystery boxes",
                    "loot_mult": "💰 Loot général",
                    "coin_mult": "🪙 Coins",
                    "ladder_xp_mult": "🪜 XP ladder",
                    "level_up_bonus": "⬆️ Bonus level up",
                    "collective_event_bonus": "🤝 Events collectifs",
                }
                lines = []
                for key, mult in mods.items():
                    label = mod_labels.get(key, key)
                    lines.append(f"• {label} : **×{mult}**")
                items.append(v2_body("\n".join(lines)))

            # Daily mystery modifier
            daily = current_daily_modifier()
            items.append(v2_divider())
            items.append(v2_body(
                f"### {daily['emoji']} AUJOURD'HUI : {daily['label'].upper()}\n"
                f"_{daily['tagline']}_"
            ))
            d_mods = daily.get("modifiers", {})
            if d_mods:
                d_lines = []
                for key, mult in d_mods.items():
                    label = {
                        "boss_hp_mult": "🐲 Boss HP",
                        "boss_reward_mult": "🏆 Récompenses boss",
                        "duel_reward_mult": "⚔️ Duels",
                        "combat_mult": "⚔️ Combats",
                        "xp_mult": "📈 XP",
                        "event_freq_mult": "🎯 Events fréquence",
                        "quest_reward_mult": "📜 Quêtes",
                        "bank_interest_mult": "🏦 Banque",
                        "daily_mult": "🎁 Daily",
                        "mysterybox_drop_mult": "📦 Mystery",
                        "loot_mult": "💰 Loot",
                        "coin_mult": "🪙 Coins",
                        "ladder_xp_mult": "🪜 Ladder",
                        "level_up_bonus": "⬆️ Level up",
                        "collective_event_bonus": "🤝 Collectifs",
                    }.get(key, key)
                    d_lines.append(f"  · {label} ×{mult}")
                items.append(v2_body("\n".join(d_lines)))
            items.append(v2_body(
                "_💡 Le bonus du jour change tous les matins — viens checker !_"
            ))

            # Weekend special (si actif)
            weekend = current_weekend_special()
            if weekend:
                items.append(v2_divider())
                items.append(v2_body(
                    f"### 🎉 WEEKEND SPECIAL : {weekend['label'].upper()}\n"
                    f"{weekend['emoji']} _{weekend['tagline']}_"
                ))
                w_mods = weekend.get("modifiers", {})
                if w_mods:
                    w_lines = []
                    for key, mult in w_mods.items():
                        label = {
                            "boss_reward_mult": "🏆 Boss",
                            "duel_reward_mult": "⚔️ Duels",
                            "xp_mult": "📈 XP",
                            "event_freq_mult": "🎯 Fréquence",
                            "mysterybox_drop_mult": "📦 Mystery",
                            "loot_mult": "💰 Loot",
                            "coin_mult": "🪙 Coins",
                            "ladder_xp_mult": "🪜 Ladder",
                            "level_up_bonus": "⬆️ Level up",
                            "quest_reward_mult": "📜 Quêtes",
                            "daily_mult": "🎁 Daily",
                        }.get(key, key)
                        w_lines.append(f"  · {label} ×{mult}")
                    items.append(v2_body("\n".join(w_lines)))
                items.append(v2_body(
                    "_⏰ Ce bonus weekend s'arrête dimanche 23h._"
                ))

            # Drops exclusifs
            drops = season.get("exclusive_drops", [])
            if drops:
                items.append(v2_divider())
                items.append(v2_body(
                    f"### 💎 DROPS EXCLUSIFS ({len(drops)})"
                ))
                rarity_emoji = {
                    "rare": "🔵", "épique": "🟣", "epique": "🟣",
                    "légendaire": "🟠", "legendaire": "🟠",
                    "mythique": "🔴", "commune": "⚪",
                }
                lines = []
                for d in drops:
                    rb = rarity_emoji.get(d.get("rarity", "rare"), "⚪")
                    stats_bits = []
                    for k, lbl in [("atk", "ATK"), ("def", "DEF"), ("crit", "CRIT%")]:
                        v = d.get(k, 0)
                        if v:
                            stats_bits.append(f"+{v} {lbl}")
                    stats_str = " · ".join(stats_bits) if stats_bits else ""
                    lines.append(
                        f"{rb} {d.get('emoji', '❓')} **{d['name']}** _({d.get('rarity', 'rare')})_\n"
                        f"   `{stats_str}`\n"
                        f"   _{d.get('lore', '')}_"
                    )
                items.append(v2_body("\n\n".join(lines)))
                items.append(v2_body(
                    "_💡 Ces items ne droppent QUE pendant cette saison. "
                    "Une fois la saison terminée, ils deviennent introuvables._"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/season my_drops` pour voir ce que tu as déjà collecté._"
            ))

            self.add_item(v2_container(*items, color=season["color"]))

    return _SeasonPanel()


def build_my_drops_panel(member, drops: list[dict], guild_name: str = ""):
    """Panel V2 — drops saisonniers que l'user a collecté."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    season = current_season()
    pool = seasonal_drop_pool()
    collected_names = {d["name"] for d in drops}

    class _MyDropsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(
                f"{season['emoji']}  COLLECTION — {member.display_name.upper()}"
            ))
            items.append(v2_subtitle(
                f"_Tes drops de la saison **{season['name']}** ({len(drops)})_"
            ))
            items.append(v2_divider())

            # Progress vs pool complet
            total_unique = len({d["name"] for d in drops})
            target = len(pool)
            items.append(v2_body(
                f"📊 **Complétion :** `{total_unique}` / `{target}` items uniques\n"
                f"📦 **Total drops claim :** `{len(drops)}` "
                f"(certains items peuvent drop plusieurs fois)"
            ))

            # Items pas encore collectés
            missing = [d for d in pool if d["name"] not in collected_names]
            if missing:
                items.append(v2_divider())
                items.append(v2_body("### ❓ ENCORE À DÉCOUVRIR"))
                lines = []
                for d in missing[:6]:
                    lines.append(
                        f"❓ **???** _({d.get('rarity', 'rare')})_  ·  {d.get('emoji', '?')}"
                    )
                if len(missing) > 6:
                    lines.append(f"_… et {len(missing) - 6} autre(s)_")
                items.append(v2_body("\n".join(lines)))

            # Items collectés
            if drops:
                items.append(v2_divider())
                items.append(v2_body("### 🏆 TES TROUVAILLES"))
                # Regrouper par nom (count occurrences)
                grouped = {}
                for d in drops:
                    key = d["name"]
                    if key not in grouped:
                        grouped[key] = {**d, "count": 0}
                    grouped[key]["count"] += 1
                lines = []
                rarity_emoji = {
                    "rare": "🔵", "épique": "🟣", "epique": "🟣",
                    "légendaire": "🟠", "legendaire": "🟠",
                    "mythique": "🔴", "commune": "⚪",
                }
                for d in grouped.values():
                    rb = rarity_emoji.get(d.get("rarity", "rare"), "⚪")
                    count_str = f" ×{d['count']}" if d["count"] > 1 else ""
                    lines.append(
                        f"{rb} {d['emoji']} **{d['name']}**{count_str}"
                    )
                items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 Continue à participer aux events pour compléter ta collection._\n"
                "_La saison se termine bientôt — fonce !_"
            ))

            self.add_item(v2_container(*items, color=season["color"]))

    return _MyDropsPanel()


__all__ = [
    "setup",
    # Catalogue
    "SEASONS", "DEFAULT_MODIFIERS",
    "DAILY_MODIFIERS", "WEEKEND_SPECIALS",
    # Detection
    "current_season", "current_daily_modifier", "current_weekend_special",
    "get_all_active_modifiers",
    "is_in_season", "get_modifier",
    # Drops
    "seasonal_drop_pool", "maybe_drop_seasonal",
    "log_drop_claim", "get_user_seasonal_drops",
    # Panels
    "build_season_panel", "build_my_drops_panel",
]
