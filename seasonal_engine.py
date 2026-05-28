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


def get_modifier(key: str, default: float = 1.0) -> float:
    """Retourne le multiplicateur courant pour `key`.

    Si la saison ne définit pas ce key → retourne `default` (typiquement 1.0).
    Lecture sync, lockless, safe pour utilisation massive.
    """
    season = current_season()
    return float(season.get("modifiers", {}).get(key, default))


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

            # Modifiers actifs
            mods = season.get("modifiers", {})
            if mods:
                items.append(v2_divider())
                items.append(v2_body("**╔═══ ✨  BONUS ACTIFS  ═══╗**"))
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

            # Drops exclusifs
            drops = season.get("exclusive_drops", [])
            if drops:
                items.append(v2_divider())
                items.append(v2_body(
                    f"**╔═══ 💎  DROPS EXCLUSIFS ({len(drops)})  ═══╗**"
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
                items.append(v2_body("**╔═══ ❓  ENCORE À DÉCOUVRIR  ═══╗**"))
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
                items.append(v2_body("**╔═══ 🏆  TES TROUVAILLES  ═══╗**"))
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
    # Detection
    "current_season", "is_in_season", "get_modifier",
    # Drops
    "seasonal_drop_pool", "maybe_drop_seasonal",
    "log_drop_claim", "get_user_seasonal_drops",
    # Panels
    "build_season_panel", "build_my_drops_panel",
]
