"""
daily_bosses.py — Boss du jour, 4× par jour, avec gating de niveau (Phase 173.2).

🎯 OBJECTIF : combat collectif fort PLUSIEURS fois par jour (pas par semaine).
4 boss spawnent à heures fixes FR (midi, après-midi, soir, nuit). Difficulté
ALTERNÉE : niveau minimum requis qui tourne (boss faciles → boss costauds).

Différences clés vs les mobs (mob_hunts) :
- HP ÉLEVÉ (3000-18000) → IMPOSSIBLE en solo, collaboration OBLIGATOIRE
  (cap 30 attaques/membre × ~200 dmg = 6000 max → il faut plusieurs joueurs)
- Gating de NIVEAU : il faut economy.level >= min_level pour attaquer
- Timer : si pas tué dans le temps imparti → le boss se retire, retour normal
- Public dans l'arène (message live avec barre de HP + bouton Attaquer)

PHILOSOPHIE :
- Les gens doivent être AIDÉS (le boss a beaucoup de vie, fait des dégâts)
- Récompenses proportionnelles aux dégâts + bonus top 3
- Si raté → aucune pénalité, ça revient juste à la normale

API :
- setup(bot, get_db, db_get, v2, add_coins_fn)
- init_db()
- DAILY_BOSS_CATALOG, get_boss_def, list_boss_ids
- get_active_boss(guild_id) -> dict | None
- trigger_daily_boss(guild_id, boss_id=None) -> event_id | None
- record_boss_attack(guild_id, user_id) -> dict (gating niveau inclus)
- resolve_daily_boss(event_id) -> dict
- daily_boss_task (loop 15 min, check heures 12/17/21/1 FR)
- DailyBossAttackButton (DynamicItem persistent)
- register_persistent_views(bot)

DB :
- daily_boss_events (id PK, guild_id, boss_id, slot_key, message_id,
                     channel_id, hp_max, hp_current, damage_total,
                     started_at, expires_at, ended_at, status)
- daily_boss_attackers (event_id, user_id, damage_dealt, attack_count,
                        last_attack_at, PK(event_id, user_id))
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncio
import discord
from discord.ext import tasks
from discord.ui import Button
import ui_v2  # design-system V2 partagé (encadrés cohérents)
import events_engine as _ev  # guide « comment jouer » + stats combat

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None
_inventory_fn = None  # Phase 184 : getter d'inventaire (gear-scaling du combat)
# Phase 196 : helpers injectés depuis bot.py pour fiabiliser le spawn + le ping.
_events_channel_fn = None  # async (guild) -> salon visible garanti (catégorie Événements)
_notif_check_fn = None     # async (guild_id, user_id, category) -> bool (opt-out)
_cleanup_register_fn = None  # async (message, delay_seconds, reason) -> nettoyage différé
_arena_create_fn = None  # Phase 210 : async (guild, kind, title) -> salon texte dédié
_report_fn = None  # Phase 223 : async (guild, title, body) -> rapport dans « chroniques-combat »
_arena_delete_fn = None  # Phase 210 : async (guild, text_channel_id) -> supprime l'arène
_event_busy_fn = None  # Phase 230 : async (guild_id) -> True si un AUTRE event de combat tourne (injecté)
_claim_lock_fn = None  # Phase 262 : async (guild_id, type) -> True si claim de spawn acquis (injecté)
_event_mention_fn = None  # Phase 235.24 : async (guild, type) -> mention rôles opt-in (/notify + 🔔)
_echo_fn = None  # Phase 257.1 : async (guild, channel, kind) -> écho silencieux salons actifs
_alliance_points_fn = None  # Phase 253 : async (guild_id, user_id, damage) -> crédite l'alliance
_pet_strike_fn = None  # Phase 261 : async (guild_id, user_id) -> dict assist familier (injecté)
_last_pet_click = {}  # Phase 261 : (guild_id, user_id) -> ts (anti-429 du bouton 🐾)

# Phase 235.16 : WARM-UP — léger sas de préparation au spawn (« le combat commence
# dans X s » demandé par l'owner : recevoir le ping, lire le butin, s'équiper,
# rejoindre un vocal). { event_id: epoch_fin_warmup }. Fail-open (vide au reboot →
# attaquable normalement).
_DBOSS_WARMUP_SECONDS = 20
_warmup_until: dict[int, float] = {}

# Phase 251.3 — ANTI-429 : avant, CHAQUE clic d'attaque re-fetchait (GET) + ré-éditait
# (PATCH) le panneau → sous le feu (beaucoup d'attaquants rapprochés) = TEMPÊTE de
# 429 (rate limit Discord) sur ce message. On THROTTLE le refresh : au plus 1 fois
# toutes les N s (les attaques rapprochées sont coalescées ; l'attaquant voit ses
# HP exacts dans sa réponse privée de toute façon). + édition via PartialMessage
# (PATCH seul, ZÉRO GET). { event_id: epoch_dernier_refresh }.
_last_panel_refresh: dict[int, float] = {}
_PANEL_REFRESH_MIN_INTERVAL = 4.0
# Phase 251.24 — ANTI-429 : cooldown d'attaque PAR JOUEUR. Un boss à gros HP invite au
# MATRAQUAGE du bouton ; chaque clic = defer + followup (2 requêtes) que discord.py
# re-essaie en boucle sur 429 → tempête globale. On coalesce les clics rapprochés d'un
# même joueur AVANT toute requête réseau (un clic noyé coûte ZÉRO requête).
_last_user_attack: dict[tuple, float] = {}
_ATTACK_COOLDOWN = 2.0

# ─── Tâche B.1 — PHASES DE BOSS + ENRAGE (additif, fail-open) ──────────────────
# À mesure que le boss perd ses HP, il franchit des PHASES (66 % / 33 %) : message
# d'ambiance + LÉGER buff de dégâts (du boss → exprimé ici comme un buff de dégâts
# SORTANTS des joueurs, car le boss du jour ne riposte pas : on rend le combat plus
# "épique" sans pénaliser, c.-à-d. les coups portent plus fort en phase haute). En
# FIN DE TIMER, le boss ENRAGE : s'il est tué pendant l'enrage → bonus de pièces.
#
# TOUT est BORNÉ et FAIL-OPEN : l'état vit en mémoire ; un reboot le remet à zéro
# (le boss redevient "phase 0", aucun crash). Une erreur de calcul → phase 0 / pas
# d'enrage / multiplicateur 1.0 (comportement ACTUEL inchangé).
_PHASE_THRESHOLDS = (
    # (seuil_pct_HP, clé, multiplicateur_dégâts_sortants, message_d'ambiance)
    (33, "p33", 1.15, "🔥 **{name} entre en FUREUR !** Ses HP fondent — frappez plus fort, le combat s'intensifie !"),
    (66, "p66", 1.07, "⚡ **{name} se réveille pour de bon.** L'arène gronde — vos coups portent davantage !"),
)
_PHASE_MAX_MULT = 1.15        # plafond ABSOLU du buff de phase
_ENRAGE_LAST_MINUTES = 5      # le boss enrage dans les N dernières minutes du timer
_ENRAGE_REWARD_BONUS = 250    # pièces MODESTES de bonus si tué pendant l'enrage (par top-3 / fatal)
# État en mémoire : { event_id: set(clés_de_phase_déjà_franchies) } (anti-spam des
# annonces) et { event_id: bool } pour l'enrage déjà annoncé.
_phase_reached: dict[int, set] = {}
_enrage_announced: dict[int, bool] = {}
# Tâche B.2 — COUP FATAL : { event_id: (user_id, enraged) }. Posé par
# record_boss_attack au moment du kill, LU UNE seule fois par resolve_daily_boss
# (anti-doublon : un seul coup fatal récompensé). Vidé après lecture.
_fatal_blow: dict[int, tuple] = {}


def _phase_for_pct(pct: int) -> Optional[tuple]:
    """Phase courante (la plus basse franchie) pour un % de HP, ou None. Fail-safe."""
    try:
        for seuil, key, mult, msg in _PHASE_THRESHOLDS:  # ordre croissant de sévérité (33 d'abord)
            if pct <= seuil:
                return (seuil, key, mult, msg)
    except Exception:
        pass
    return None


def _phase_damage_mult(event_id: int, hp_cur: int, hp_max: int) -> float:
    """Multiplicateur de dégâts SORTANTS lié à la phase actuelle (>= 1.0, borné).
    FAIL-OPEN STRICT → 1.0 (aucun changement de dégâts)."""
    try:
        if hp_max <= 0:
            return 1.0
        pct = int(hp_cur * 100 / hp_max)
        ph = _phase_for_pct(pct)
        if ph:
            return min(_PHASE_MAX_MULT, float(ph[2]))
    except Exception:
        pass
    return 1.0


def _is_enraged(expires_ts: Optional[int]) -> bool:
    """True si on est dans la fenêtre d'enrage (N dernières minutes avant la fin).
    FAIL-SAFE → False (pas d'enrage = comportement actuel)."""
    try:
        if not expires_ts:
            return False
        remaining = int(expires_ts) - int(datetime.now(timezone.utc).timestamp())
        return 0 < remaining <= _ENRAGE_LAST_MINUTES * 60
    except Exception:
        return False


# Phase 196 : mention intelligente rotative — paramètres anti-spam.
PING_MAX_USERS = 8          # cap dur de mentions par spawn (TOS Discord)
PING_COOLDOWN_HOURS = 8     # un même membre n'est ping qu'une fois / ~8h
PING_LOOKBACK_DAYS = 14     # « participe au combat » = a attaqué un boss < 14j
ACTIVE_PING_LOOKBACK_HOURS = 72  # Phase 205 : fallback = membres ACTIFS < 72h
PING_CLEANUP_SECONDS = 30 * 60  # la ligne de ping s'auto-supprime après 30 min
RESOLUTION_CLEANUP_SECONDS = 15 * 60  # Phase 205 : le récap de fin disparaît après 15 min

# Phase 193 : 5 créneaux fixes FR — MATIN (9h), midi, après-midi, soir, NUIT.
# Le créneau matin garantit un combat dès le réveil (vision owner : faire vivre
# la journée matin / midi / soir, pas juste le soir). _pick_boss_for_slot()
# utilise len(BOSS_HOURS) + .index(now.hour) → ajouter un créneau est sûr.
BOSS_HOURS = [9, 12, 17, 21, 1]
# Cap anti-spam : nb max d'attaques par membre par boss
MAX_ATTACKS_PER_USER = 30
# Dégâts par clic (avant bonus)
ATTACK_DAMAGE_MIN = 60
ATTACK_DAMAGE_MAX = 220
# Récompenses
COIN_PER_DAMAGE = 0.04
TOP3_BONUS_COINS = 1200
PARTICIPATION_BONUS_COINS = 150
# Bonus alliance : si 3+ membres d'une alliance participent (info — le détail
# alliance est géré côté serveur ; ici on garde la mécanique simple)
ALLIANCE_BONUS_MIN = 3
ALLIANCE_BONUS_MULT = 1.20


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE — 6 boss, difficulté CROISSANTE / alternée
# ═══════════════════════════════════════════════════════════════════════════
# - min_level : niveau requis (economy.level) pour pouvoir attaquer
# - hp_base   : élevé → collaboration obligatoire
# - lifetime_min : temps imparti avant retrait du boss
# - tier : étiquette de difficulté affichée

DAILY_BOSS_CATALOG = [
    {
        "id": "gobelin_roi",
        "name": "Gobelin Roi",
        "emoji": "👺",
        "tier": "Facile",
        "description": (
            "Un gobelin bouffi qui a volé le trésor du village. Accessible à "
            "tous — un bon entraînement pour débuter le combat collectif."
        ),
        "min_level": 0,
        "hp_base": 3000,
        "lifetime_min": 45,
        "color": 0x27AE60,
    },
    {
        "id": "golem_pierre",
        "name": "Golem de Pierre",
        "emoji": "🪨",
        "tier": "Facile+",
        "description": (
            "Un colosse de roche lent mais résistant. Frappez ensemble pour "
            "le fissurer. Niveau 3 minimum recommandé."
        ),
        "min_level": 3,
        "hp_base": 5000,
        "lifetime_min": 50,
        "color": 0x7F8C8D,
    },
    {
        "id": "hydre_marais",
        "name": "Hydre des Marais",
        "emoji": "🐉",
        "tier": "Moyen",
        "description": (
            "Une hydre à plusieurs têtes qui régénère si on la laisse "
            "respirer. Il faut frapper vite et nombreux. Niveau 5 requis."
        ),
        "min_level": 5,
        "hp_base": 8000,
        "lifetime_min": 60,
        "color": 0x16A085,
    },
    {
        "id": "chevalier_noir",
        "name": "Chevalier Noir",
        "emoji": "⚔️",
        "tier": "Difficile",
        "description": (
            "Un chevalier maudit en armure impénétrable. Seuls les "
            "aventuriers aguerris peuvent l'entamer. Niveau 8 requis."
        ),
        "min_level": 8,
        "hp_base": 12000,
        "lifetime_min": 70,
        "color": 0x2C3E50,
    },
    {
        "id": "dragon_cendres",
        "name": "Dragon de Cendres",
        "emoji": "🔥",
        "tier": "Très difficile",
        "description": (
            "Un dragon ancien crachant des cendres ardentes. Toute l'alliance "
            "doit converger pour l'abattre. Niveau 12 requis."
        ),
        "min_level": 12,
        "hp_base": 15000,
        "lifetime_min": 75,
        "color": 0xC0392B,
    },
    {
        "id": "titan_oublie",
        "name": "Titan Oublié",
        "emoji": "🗿",
        "tier": "Légendaire",
        "description": (
            "Une entité colossale des temps anciens. Le serveur ENTIER doit "
            "se coordonner. Niveau 15 requis. Récompenses légendaires."
        ),
        "min_level": 15,
        "hp_base": 18000,
        "lifetime_min": 90,
        "color": 0x8E44AD,
    },
]

# Phase 252.B — +10 boss du jour. La sélection `_pick_boss_for_slot` fait une rotation
# déterministe `% len(DAILY_BOSS_CATALOG)` → en allongeant le catalogue, le cycle est
# bien plus long ⇒ BIEN moins de répétitions (plainte owner). Schéma EXACT (9 champs).
# Les 2 premiers (min_level<=3) alimentent aussi le créneau « accessible » du matin (9h).
DAILY_BOSS_CATALOG.extend([
    {"id": "sanglier_geant", "name": "Sanglier Géant", "emoji": "🐗", "tier": "Facile",
     "description": "Une bête furieuse qui ravage les champs. Idéal pour démarrer la journée à plusieurs.",
     "min_level": 1, "hp_base": 3500, "lifetime_min": 45, "color": 0x9C640C},
    {"id": "essaim_frelons", "name": "Essaim de Frelons", "emoji": "🐝", "tier": "Facile+",
     "description": "Un nuage de frelons géants. Frappez vite et souvent pour le disperser.",
     "min_level": 2, "hp_base": 4200, "lifetime_min": 45, "color": 0xF39C12},
    {"id": "ent_ancien", "name": "Ent Ancien", "emoji": "🌳", "tier": "Moyen",
     "description": "Un arbre éveillé, lent mais à l'écorce coriace. La coordination paie.",
     "min_level": 4, "hp_base": 6500, "lifetime_min": 55, "color": 0x196F3D},
    {"id": "liche_glacee", "name": "Liche Glacée", "emoji": "❄️", "tier": "Moyen+",
     "description": "Une liche qui gèle ses assaillants. Brisez sa carapace de givre ensemble.",
     "min_level": 6, "hp_base": 9000, "lifetime_min": 60, "color": 0x5DADE2},
    {"id": "minotaure", "name": "Minotaure du Labyrinthe", "emoji": "🐂", "tier": "Difficile",
     "description": "Un minotaure enragé qui charge tout ce qui bouge. Tenez bon en groupe.",
     "min_level": 7, "hp_base": 10500, "lifetime_min": 65, "color": 0x873600},
    {"id": "kraken_abyssal", "name": "Kraken Abyssal", "emoji": "🦑", "tier": "Difficile+",
     "description": "Le kraken remonte des abysses, ses tentacules balayant l'arène. Visez les points faibles.",
     "min_level": 9, "hp_base": 13000, "lifetime_min": 70, "color": 0x1A5276},
    {"id": "golem_lave", "name": "Golem de Lave", "emoji": "🌋", "tier": "Très difficile",
     "description": "Un colosse de roche en fusion. Sa chaleur brûle — il faut toute l'alliance.",
     "min_level": 11, "hp_base": 14500, "lifetime_min": 75, "color": 0xD35400},
    {"id": "archonte_dechu", "name": "Archonte Déchu", "emoji": "😈", "tier": "Très difficile+",
     "description": "Un ange déchu assoiffé de vengeance. Seuls les plus actifs en viennent à bout.",
     "min_level": 13, "hp_base": 16000, "lifetime_min": 80, "color": 0x7D3C98},
    {"id": "colosse_celeste", "name": "Colosse Céleste", "emoji": "🌠", "tier": "Légendaire",
     "description": "Un gardien tombé des cieux. Le serveur entier doit converger — récompenses célestes.",
     "min_level": 15, "hp_base": 19000, "lifetime_min": 90, "color": 0x48DBFB},
    {"id": "devoreur_mondes", "name": "Dévoreur de Mondes", "emoji": "🪐", "tier": "Mythique",
     "description": "Une entité primordiale qui consume les étoiles. L'ultime défi collectif du serveur.",
     "min_level": 18, "hp_base": 22000, "lifetime_min": 95, "color": 0xBE2EDD},
])
# Phase 256 — EXPANSION BOSS DU JOUR (+12). Schéma EXACT (9 champs). min_level UNIQUES
# et inutilisés (10,14,16,17,19→26) + hp_base STRICTEMENT croissant avec min_level →
# l'invariant test_phase_173 (levels ET hps triés croissants) reste vrai après le sort.
# Ids uniques. Allonge fortement la rotation `% len` ⇒ bien moins de répétitions.
DAILY_BOSS_CATALOG.extend([
    {"id": "loup_alpha", "name": "Loup Alpha de la Meute", "emoji": "🐺", "tier": "Difficile",
     "description": "Le chef d'une meute affamée mène la charge. Encerclez-le tous ensemble.",
     "min_level": 10, "hp_base": 13700, "lifetime_min": 65, "color": 0x839192},
    {"id": "golem_argile", "name": "Golem d'Argile Runique", "emoji": "🧱", "tier": "Difficile+",
     "description": "Un golem gravé de runes instables. Brisez son noyau avant qu'il ne durcisse.",
     "min_level": 14, "hp_base": 17000, "lifetime_min": 72, "color": 0xA04000},
    {"id": "spectre_brume", "name": "Spectre de Brume", "emoji": "👻", "tier": "Très difficile",
     "description": "Une ombre tapie dans le brouillard, qui se dissipe si on la laisse respirer. Frappez ensemble.",
     "min_level": 16, "hp_base": 20000, "lifetime_min": 78, "color": 0x5D6D7E},
    {"id": "araignee_matriarche", "name": "Matriarche Arachnéenne", "emoji": "🕷️", "tier": "Très difficile",
     "description": "La reine des cavernes crache un venin corrosif. Frappez vite et nombreux.",
     "min_level": 17, "hp_base": 21000, "lifetime_min": 80, "color": 0x4A235A},
    {"id": "golem_foudre", "name": "Golem de Foudre", "emoji": "⚡", "tier": "Très difficile+",
     "description": "Un titan d'acier chargé d'orage. Visez entre deux décharges, tous ensemble.",
     "min_level": 19, "hp_base": 23000, "lifetime_min": 82, "color": 0xF1C40F},
    {"id": "vampire_ancien", "name": "Vampire Ancien", "emoji": "🧛", "tier": "Légendaire",
     "description": "Un seigneur de la nuit qui draine la vie de ses assaillants. Submergez-le en masse.",
     "min_level": 20, "hp_base": 24000, "lifetime_min": 85, "color": 0x7B241C},
    {"id": "behemoth_glace", "name": "Béhémoth de Glace", "emoji": "🧊", "tier": "Légendaire",
     "description": "Une montagne vivante de givre. Sa carapace ne cède que sous les coups répétés du serveur.",
     "min_level": 21, "hp_base": 25500, "lifetime_min": 88, "color": 0x5DADE2},
    {"id": "demon_braises", "name": "Démon des Braises", "emoji": "😈", "tier": "Légendaire+",
     "description": "Un démon ardent surgi des forges infernales. Toute l'alliance doit converger.",
     "min_level": 22, "hp_base": 27000, "lifetime_min": 90, "color": 0xE74C3C},
    {"id": "seraphin_dechu", "name": "Séraphin Déchu", "emoji": "😇", "tier": "Légendaire+",
     "description": "Un ange tombé, ses ailes brisées rayonnant encore. Un défi pour les plus actifs.",
     "min_level": 23, "hp_base": 28500, "lifetime_min": 95, "color": 0xF4D03F},
    {"id": "roi_liche", "name": "Roi-Liche", "emoji": "💀", "tier": "Mythique",
     "description": "Le monarque mort-vivant lève une armée d'ombres. Le serveur entier doit s'unir.",
     "min_level": 24, "hp_base": 30000, "lifetime_min": 100, "color": 0x1C2833},
    {"id": "wyrm_tempete", "name": "Wyrm de Tempête", "emoji": "🐲", "tier": "Mythique",
     "description": "Un dragon-serpent chevauchant l'ouragan. Coordonnez vos frappes entre les éclairs.",
     "min_level": 25, "hp_base": 31500, "lifetime_min": 105, "color": 0x2980B9},
    {"id": "avatar_neant", "name": "Avatar du Néant", "emoji": "🪐", "tier": "Mythique+",
     "description": "L'incarnation du vide qui consume toute lumière. L'ultime épreuve collective du serveur.",
     "min_level": 26, "hp_base": 33000, "lifetime_min": 110, "color": 0x6C3483},
])
# Phase 252.B : on RE-TRIE le catalogue par min_level croissant après l'extend.
# Invariant attendu (test_phase_173 test_boss_difficulty_progression) + créneau matin
# « accessible » cohérent + rotation _pick_boss_for_slot saine. sort() stable.
DAILY_BOSS_CATALOG.sort(key=lambda _b: int(_b.get("min_level", 0) or 0))


def get_boss_def(boss_id: str) -> Optional[dict]:
    for b in DAILY_BOSS_CATALOG:
        if b["id"] == boss_id:
            return b
    return None


def list_boss_ids() -> list[str]:
    return [b["id"] for b in DAILY_BOSS_CATALOG]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
          inventory_fn=None, events_channel_fn=None, notif_check_fn=None,
          cleanup_register_fn=None, arena_create_fn=None, arena_delete_fn=None,
          report_fn=None, event_busy_fn=None, event_mention_fn=None,
          alliance_points_fn=None, echo_fn=None, pet_strike_fn=None,
          claim_lock_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _inventory_fn
    global _events_channel_fn, _notif_check_fn, _cleanup_register_fn
    global _arena_create_fn, _arena_delete_fn, _report_fn, _event_busy_fn, _event_mention_fn
    global _alliance_points_fn, _echo_fn, _pet_strike_fn, _claim_lock_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _inventory_fn = inventory_fn
    # Phase 196 : injections optionnelles (toutes fail-open si None)
    _events_channel_fn = events_channel_fn
    _notif_check_fn = notif_check_fn
    _cleanup_register_fn = cleanup_register_fn
    # Phase 210 : arène de combat dédiée (créée au spawn, supprimée à la fin)
    _arena_create_fn = arena_create_fn
    _arena_delete_fn = arena_delete_fn
    # Phase 223 : rapport de fin → salon « 📜 chroniques-combat »
    _report_fn = report_fn
    # Phase 230 : verrou global « un seul event de combat à la fois »
    _event_busy_fn = event_busy_fn
    # Phase 235.24 : mention des rôles opt-in (/notify + 🔔 par-type) au spawn
    _event_mention_fn = event_mention_fn
    # Phase 253 : crédit des points d'alliance au combat (injecté depuis bot.py)
    _alliance_points_fn = alliance_points_fn
    _echo_fn = echo_fn
    _pet_strike_fn = pet_strike_fn  # Phase 261 : assist familier (cœur partagé bot.py)
    _claim_lock_fn = claim_lock_fn  # Phase 262 : claim atomique de spawn (anti-course TOCTOU)


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_boss_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    boss_id TEXT NOT NULL,
                    slot_key TEXT NOT NULL,
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0,
                    hp_max INTEGER NOT NULL,
                    hp_current INTEGER NOT NULL,
                    damage_total INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    ended_at TIMESTAMP,
                    status TEXT DEFAULT 'alive'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_boss_attackers (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage_dealt INTEGER DEFAULT 0,
                    attack_count INTEGER DEFAULT 0,
                    last_attack_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (event_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_boss_active "
                "ON daily_boss_events(guild_id, status)"
            )
            # Phase 196 : journal de cooldown du ping intelligent (anti-spam +
            # rotation). last_pinged = ISO UTC du dernier ping reçu par ce membre.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS boss_ping_log (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    last_pinged TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[daily_bosses init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _now_paris() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc)


def _current_slot_key() -> Optional[str]:
    """Si on est dans un créneau de spawn (heure pile), retourne une clé
    unique 'YYYY-MM-DD-HH'. Sinon None."""
    now = _now_paris()
    if now.hour in BOSS_HOURS:
        return now.strftime("%Y-%m-%d-%H")
    return None


async def get_user_level(guild_id: int, user_id: int) -> int:
    """Lit le niveau du joueur depuis la table economy. Default 1."""
    if _get_db is None:
        return 1
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT level FROM economy WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return 1
    except Exception:
        return 1


async def _find_arena_channel(guild: discord.Guild):
    """Réutilise le finder robuste de mob_hunts (7 niveaux de fallback).
    Fallback local minimal si mob_hunts indisponible."""
    try:
        import mob_hunts as _mh
        ch = await _mh._find_arena_channel(guild)
        if ch:
            return ch
    except Exception:
        pass
    # Fallback minimal : premier salon écrivable
    try:
        me = guild.me
        for ch in guild.text_channels:
            try:
                if me and ch.permissions_for(me).send_messages:
                    return ch
            except Exception:
                continue
    except Exception:
        pass
    # Phase 196 : DERNIER recours — un boss ne doit JAMAIS échouer faute de salon.
    # On route vers un salon de la catégorie « 🎪 Événements » (créée si besoin)
    # via le getter injecté par bot.py. Fail-open : toute erreur → None.
    if _events_channel_fn is not None:
        try:
            ch = await _events_channel_fn(guild)
            if ch:
                return ch
        except Exception as ex:
            print(f"[daily_bosses _find_arena_channel events fallback] {ex}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Phase 196 — Mention intelligente rotative (ping participants combat)
# ═══════════════════════════════════════════════════════════════════════════

async def _smart_combat_ping(guild: discord.Guild, exclude_opt_out: bool = True) -> str:
    """Construit une ligne de mention CIBLÉE pour le spawn d'un boss du jour.

    Vision owner : prévenir ceux qui AIMENT le combat (ils ont déjà attaqué un
    boss récemment) ET, à défaut, les MEMBRES ACTIFS récents (Phase 205 : sinon
    le boss spawnait dans le vide, personne ne venait) — mais SANS spammer : cap
    PING_MAX_USERS et on TOURNE (un même membre au plus une fois / ~8h, via
    boss_ping_log). Respecte l'opt-out `boss_raid` via le check injecté de bot.py.

    Retourne une courte ligne `🔔 <@id> … — venez tenter votre chance !` ou
    une chaîne vide si personne n'est éligible. FAIL-OPEN : toute erreur → "".
    """
    # Phase 257 : DÉSACTIVÉ — plus AUCUNE mention individuelle de membre (directive
    # owner : « les mentions sont très relou »). Le boss du jour reste visible dans
    # le salon ; seuls les volontaires abonnés au 🔔 par-type sont notifiés.
    return ""
    if _get_db is None or guild is None:
        return ""
    try:
        now = datetime.now(timezone.utc)
        lookback_iso = (now - timedelta(days=PING_LOOKBACK_DAYS)).isoformat()
        cooldown_iso = (now - timedelta(hours=PING_COOLDOWN_HOURS)).isoformat()

        chosen_ids = []

        async def _consider(uid: int) -> None:
            """Filtre commun : anti-doublon, présence, non-bot, opt-out.
            Fail-CLOSED sur l'opt-out (on saute en cas d'erreur du check)."""
            if uid in chosen_ids or len(chosen_ids) >= PING_MAX_USERS:
                return
            member = guild.get_member(uid)
            if member is None or member.bot:
                return
            if exclude_opt_out and _notif_check_fn is not None:
                try:
                    if not await _notif_check_fn(guild.id, uid, 'boss_raid'):
                        return
                except Exception as ex:
                    print(f"[_smart_combat_ping opt-out fail-closed user={uid}] {ex}")
                    return
            chosen_ids.append(uid)

        # 1) PRIORITÉ : participants récents au combat (ils adorent ça), triés
        #    par « pas ping récemment » d'abord (rotation), via boss_ping_log.
        async with _get_db() as db:
            async with db.execute(
                "SELECT a.user_id, MAX(a.last_attack_at) AS last_seen, p.last_pinged "
                "FROM daily_boss_attackers a "
                "JOIN daily_boss_events e ON e.id = a.event_id "
                "LEFT JOIN boss_ping_log p "
                "  ON p.guild_id = e.guild_id AND p.user_id = a.user_id "
                "WHERE e.guild_id = ? AND a.last_attack_at >= ? "
                "  AND (p.last_pinged IS NULL OR p.last_pinged < ?) "
                "GROUP BY a.user_id "
                "ORDER BY (p.last_pinged IS NOT NULL), p.last_pinged ASC, last_seen DESC "
                "LIMIT 50",
                (guild.id, lookback_iso, cooldown_iso),
            ) as cur:
                rows = await cur.fetchall()
        for row in rows:
            await _consider(int(row[0]))

        # 2) FALLBACK CRITIQUE (Phase 205) : s'il n'y a pas (assez) d'attaquants
        #    récents — cas du serveur où le combat démarre — on prévient les
        #    MEMBRES ACTIFS récents (ont parlé < ACTIVE_PING_LOOKBACK_HOURS).
        #    SANS ça, le boss spawnait dans le vide → personne ne venait →
        #    « boss non combattus ». On tourne aussi via boss_ping_log.
        if len(chosen_ids) < PING_MAX_USERS:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT t.user_id "
                        "FROM activity_tracking t "
                        "LEFT JOIN boss_ping_log p "
                        "  ON p.guild_id = t.guild_id AND p.user_id = t.user_id "
                        "WHERE t.guild_id = ? AND t.last_message IS NOT NULL "
                        "  AND datetime(t.last_message) >= datetime('now', ?) "
                        "  AND (p.last_pinged IS NULL OR datetime(p.last_pinged) < datetime('now', ?)) "
                        "ORDER BY (p.last_pinged IS NOT NULL), datetime(t.last_message) DESC "
                        "LIMIT 50",
                        (guild.id, f"-{ACTIVE_PING_LOOKBACK_HOURS} hours",
                         f"-{PING_COOLDOWN_HOURS} hours"),
                    ) as cur:
                        arows = await cur.fetchall()
                for row in arows:
                    if len(chosen_ids) >= PING_MAX_USERS:
                        break
                    await _consider(int(row[0]))
            except Exception as ex:
                print(f"[_smart_combat_ping active-fallback] {ex}")

        if not chosen_ids:
            return ""

        # 3) Marque ces membres comme « ping maintenant » (rotation future).
        now_iso = now.isoformat()
        try:
            async with _get_db() as db:
                for uid in chosen_ids:
                    await db.execute(
                        "INSERT INTO boss_ping_log (guild_id, user_id, last_pinged) "
                        "VALUES (?, ?, ?) "
                        "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                        "last_pinged = excluded.last_pinged",
                        (guild.id, uid, now_iso),
                    )
                await db.commit()
        except Exception as ex:
            print(f"[_smart_combat_ping log] {ex}")

        mentions = " ".join(f"<@{uid}>" for uid in chosen_ids)
        return (
            f"🔔 {mentions} — un boss vient d'apparaître, si ça vous tente venez "
            f"tenter votre chance ! _(ouvert à tout le monde · `/notifs` pour gérer "
            f"vos pings)_"
        )
    except Exception as ex:
        print(f"[_smart_combat_ping] {ex}")
        return ""


# ═══════════════════════════════════════════════════════════════════════════
#  Active boss
# ═══════════════════════════════════════════════════════════════════════════

async def get_active_boss(guild_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, boss_id, hp_max, hp_current, damage_total, "
                "started_at, expires_at, message_id, channel_id "
                "FROM daily_boss_events "
                "WHERE guild_id=? AND status='alive' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "event_id": int(row[0]),
            "boss_id": row[1],
            "hp_max": int(row[2] or 0),
            "hp_current": int(row[3] or 0),
            "damage_total": int(row[4] or 0),
            "started_at": row[5],
            "expires_at": row[6],
            "message_id": int(row[7] or 0),
            "channel_id": int(row[8] or 0),
        }
    except Exception:
        return None


async def _live_participant_count(event_id: int) -> int:
    """Tâche B.5 : nombre de COMBATTANTS distincts ayant déjà frappé ce boss
    (compteur de présence live affiché sur le panneau). LECTURE SEULE.
    FAIL-SAFE → 0 (aucune ligne affichée), jamais bloquant."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM daily_boss_attackers "
                "WHERE event_id=? AND damage_dealt > 0",
                (event_id,),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


async def _user_attack_count(event_id: int, user_id: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT attack_count FROM daily_boss_attackers "
                "WHERE event_id=? AND user_id=?",
                (event_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
#  Trigger
# ═══════════════════════════════════════════════════════════════════════════

# Phase 193c : créneaux « accessibles » — un boss BAS NIVEAU pour que tout le
# monde (même les nouveaux) puisse lancer la journée. Le matin (9h) en fait
# partie : faire vivre la matinée sans exclure les petits niveaux.
MORNING_ACCESSIBLE_HOURS = {9}


def _pick_boss_for_slot() -> dict:
    """Choisit le boss du créneau : rotation déterministe basée sur le jour +
    l'index d'heure → difficulté qui alterne. Exception : sur un créneau
    accessible (matin), on garantit un boss bas niveau (min_level <= 3) pour
    n'exclure personne au réveil."""
    now = _now_paris()
    day_of_year = now.timetuple().tm_yday
    if now.hour in MORNING_ACCESSIBLE_HOURS:
        easy = [b for b in DAILY_BOSS_CATALOG if b.get("min_level", 0) <= 3]
        if easy:
            return easy[day_of_year % len(easy)]
    try:
        slot_idx = BOSS_HOURS.index(now.hour)
    except ValueError:
        slot_idx = 0
    idx = (day_of_year * len(BOSS_HOURS) + slot_idx) % len(DAILY_BOSS_CATALOG)
    return DAILY_BOSS_CATALOG[idx]


async def trigger_daily_boss(
    guild: discord.Guild, boss_id: Optional[str] = None,
) -> Optional[int]:
    """Déclenche un boss du jour pour cette guild."""
    if _get_db is None or _bot is None or not guild:
        return None

    # Phase 191 : interrupteur Hub Événements — Boss quotidien
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('daily_boss_enabled', True)):
            return None
    except Exception:
        pass

    # Anti-doublon : déjà un boss actif ?
    if await get_active_boss(guild.id):
        return None

    # Phase 177 : pas de boss du jour pendant un GROS event masquant (Boss Raid /
    # Chasse au trésor / Quiz) — l'arène est dédiée à cet event, serveur masqué.
    # Évite que deux events de combat se superposent dans le même salon.
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM events WHERE guild_id=? AND ended=0 "
                "AND (ends_at IS NULL OR datetime(ends_at) > datetime('now')) LIMIT 1",
                (guild.id,),
            ) as cur:
                if await cur.fetchone():
                    return None
    except Exception:
        pass

    slot_key = _current_slot_key()
    if slot_key is None and boss_id is None:
        return None  # pas dans un créneau (sauf déclenchement forcé)
    if slot_key is None:
        slot_key = _now_paris().strftime("%Y-%m-%d-%H") + "-forced"

    # Anti-doublon : déjà eu un boss sur ce créneau ?
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM daily_boss_events "
                "WHERE guild_id=? AND slot_key=? LIMIT 1",
                (guild.id, slot_key),
            ) as cur:
                if await cur.fetchone():
                    return None
    except Exception:
        pass

    # Phase 230 : VERROU GLOBAL — si un AUTRE event de combat est en cours (boss
    # raid / quiz / trésor / world boss / climax), on NE lance PAS le boss du jour
    # par-dessus (sinon il masque/double l'event en cours). On réessaiera au
    # prochain passage de daily_boss_task (toutes les 15 min). Le verrou n'inclut
    # PAS les mobs : un simple mob ne doit pas repousser une ancre comme le boss
    # du jour. Fail-open si l'injection manque.
    if _event_busy_fn is not None:
        try:
            if await _event_busy_fn(guild.id):
                return None
        except Exception:
            pass
    # Phase 262 : CLAIM ATOMIQUE — kill la course TOCTOU (2 spawns simultanés qui
    # passent tous deux le verrou avant que l'un ait inséré). Si un autre spawn a
    # déjà claim dans cette fenêtre → on N'EMPILE PAS (bail). Fail-closed côté helper.
    if _claim_lock_fn is not None:
        try:
            if not await _claim_lock_fn(guild.id, 'daily_boss'):
                return None  # CONFLIT : un autre event tient déjà le verrou → on n'empile pas
        except Exception:
            pass  # erreur infra du claim → fail-OPEN (le verrou-grâce a déjà filtré)

    boss = get_boss_def(boss_id) if boss_id else _pick_boss_for_slot()
    if not boss:
        return None

    # Phase 210 : salon DÉDIÉ par boss (catégorie ⚔️ + texte + 2 vocaux), créé
    # puis supprimé à la fin. Fallback sur l'arène partagée si pas la perm/échec.
    ch = None
    if _arena_create_fn is not None:
        try:
            ch = await _arena_create_fn(guild, 'daily_boss', boss['name'])
        except Exception as ex:
            print(f"[trigger_daily_boss arena create] {ex}")
    if ch is None:
        ch = await _find_arena_channel(guild)
    if not ch:
        print(f"[daily_boss] pas de salon dispo, spawn annulé guild={guild.id}")
        return None

    # Difficulté dynamique (FAIL-OPEN strict, additif) : HP adaptés à la foule.
    # facteur BORNÉ [0.7..2.0] selon le nb d'actifs du jour, plancher/plafond
    # ABSOLUS relatifs au boss. La moindre erreur → facteur 1.0 (HP de base actuel).
    hp_base = int(boss["hp_base"])
    hp = hp_base
    try:
        import activity_system as _act
        _f = await _act.crowd_hp_factor(guild)
        hp = _act.apply_crowd_hp(
            hp_base, _f,
            floor=int(hp_base * _act.CROWD_HP_FACTOR_MIN),
            cap=int(hp_base * _act.CROWD_HP_FACTOR_MAX),
        )
    except Exception as ex:
        print(f"[trigger_daily_boss crowd_hp] {ex}")
        hp = hp_base  # FAIL-OPEN : HP de base
    expires = datetime.now(timezone.utc) + timedelta(minutes=int(boss["lifetime_min"]))

    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO daily_boss_events "
                "(guild_id, boss_id, slot_key, channel_id, hp_max, hp_current, "
                "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild.id, boss["id"], slot_key, ch.id, hp, hp,
                 expires.isoformat()),
            )
            event_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[trigger_daily_boss INSERT] {ex}")
        return None

    # Phase 235.16 : warm-up — le boss est invulnérable les premières secondes
    # (sas de préparation). Le panneau affiche « commence <t:..:R> ».
    _warm = datetime.now(timezone.utc).timestamp() + _DBOSS_WARMUP_SECONDS
    _warmup_until[event_id] = _warm
    # Poste le panel public + bouton
    msg = await _post_boss_panel(ch, event_id, boss, hp, hp, int(boss["lifetime_min"]),
                                 warmup_ts=_warm)
    # FIX salons (anti-salon-vide) : si le panneau n'a pas pu être posté, ne PAS
    # laisser un boss « fantôme » (status='alive', expires futur) bloquer
    # _has_any_major_event_running ET un salon « 👹-boss-du-jour » VIDE traîner jusqu'à
    # l'expiration. On clôt l'event (status='expired') et on supprime son salon dédié.
    # Symétrique du flux mob / boss raid. Fail-open.
    if not msg:
        print(f"[daily_bosses] panneau non posté → annulation guild={guild.id} "
              f"boss={boss['id']} (salon nettoyé)")
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE daily_boss_events SET status='expired', "
                    "ended_at=CURRENT_TIMESTAMP WHERE id=? AND status='alive'",
                    (event_id,),
                )
                await db.commit()
        except Exception:
            pass
        if _arena_delete_fn is not None:
            try:
                await _arena_delete_fn(guild, ch.id, grace_seconds=0)
            except Exception:
                pass
        return None
    if msg:
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE daily_boss_events SET message_id=? WHERE id=?",
                    (msg.id, event_id),
                )
                await db.commit()
        except Exception:
            pass
        # Phase 205 : filet de sécurité — le panneau s'auto-nettoie même si la
        # résolution ne tourne jamais (redémarrage). En temps normal il est
        # supprimé dès la résolution (resolve_daily_boss).
        if _cleanup_register_fn is not None:
            try:
                await _cleanup_register_fn(
                    msg, int(boss["lifetime_min"]) * 60 + 3600, 'boss_panel')
            except Exception:
                pass

    # Phase 257.1 : ÉCHO SILENCIEUX (sans ping) dans les salons actifs → le Boss
    # du Jour est VISIBLE pour les présents sans déranger personne. Fail-open.
    if _echo_fn is not None:
        try:
            await _echo_fn(guild, ch, 'daily_boss')
        except Exception:
            pass

    # Phase 196 : ping intelligent rotatif APRÈS le panneau (un LayoutView V2 ne
    # peut PAS porter de content/mention → message séparé). Cap 5, opt-out
    # respecté, aucun @everyone/@here. Auto-supprimé pour ne pas encombrer.
    # Tout est fail-open : une erreur ici ne doit JAMAIS empêcher le spawn.
    try:
        ping_line = await _smart_combat_ping(guild)
        # Phase 235.24 : préfixe les rôles opt-in (/notify + 🔔 Boss) → s'abonner sert
        # vraiment. Envoyé même sans actif (les abonnés sont prévenus). roles=True.
        role_mention = ""
        if _event_mention_fn is not None:
            try:
                role_mention = await _event_mention_fn(guild, 'daily_boss')
            except Exception:
                role_mention = ""
        ping_full = "\n".join([p for p in (role_mention, ping_line) if p])
        if ping_full:
            ping_msg = await ch.send(
                ping_full,
                allowed_mentions=discord.AllowedMentions(
                    users=True, everyone=False, roles=True),
            )
            if ping_msg and _cleanup_register_fn is not None:
                try:
                    await _cleanup_register_fn(
                        ping_msg, PING_CLEANUP_SECONDS, 'boss_ping')
                except Exception:
                    pass
    except Exception as ex:
        print(f"[trigger_daily_boss smart_ping] {ex}")

    print(
        f"[daily_bosses] trigger guild={guild.id} boss={boss['id']} "
        f"hp={hp} lvl={boss['min_level']} event={event_id}"
    )
    return event_id


# ═══════════════════════════════════════════════════════════════════════════
#  Panel + live update
# ═══════════════════════════════════════════════════════════════════════════

def _hp_bar(cur_hp: int, max_hp: int, width: int = 18) -> str:
    if max_hp <= 0:
        return "░" * width
    pct = max(0, min(100, int(cur_hp * 100 / max_hp)))
    fill = int(width * pct / 100)
    return "█" * fill + "░" * (width - fill)


def _parse_ts(val) -> Optional[int]:
    """Parse un timestamp SQLite (naïf OU aware) → epoch UTC (int) ou None.
    (CURRENT_TIMESTAMP est NAÏF → on le normalise en UTC, cf. piège datetime.)"""
    if not val:
        return None
    try:
        s = str(val)
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _build_boss_layout(
    boss: dict, hp_cur: int, hp_max: int, damage_total: int, event_id: int,
    *, expires_ts: Optional[int] = None, warmup_ts: Optional[float] = None,
    alive: bool = True, guild_id: Optional[int] = None,
    live_count: Optional[int] = None,
):
    """Phase 235.16 : construit le panneau V2 COMPLET du boss du jour (lore + HP +
    infos/butin + how-to-play + bouton). UTILISÉ par le post initial ET le refresh
    → le refresh ne « décape » plus le descriptif/butin (bug « le message
    disparaît, on n'a pas le temps de lire »). Compte à rebours LIVE via expires_ts."""
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    pct = int(hp_cur * 100 / max(1, hp_max))
    lvl_txt = ("Accessible à tous" if boss["min_level"] <= 0
               else f"Niveau **{boss['min_level']}** requis")
    when_line = (f"⏱️ Se termine <t:{int(expires_ts)}:R>" if expires_ts
                 else f"⏱️ Temps imparti : **{boss.get('lifetime_min', 45)} min**")
    hp_block = (
        f"**❤️ HP**\n`{_hp_bar(hp_cur, hp_max)}`\n"
        f"`{hp_cur:,} / {hp_max:,}` ({pct}%)"
    )
    if damage_total:
        hp_block += f"\n⚔️ Dégâts totaux infligés : `{int(damage_total):,}`"
    # Tâche B.5 : COMPTEUR DE PRÉSENCE LIVE — nb de combattants distincts. FAIL-SAFE :
    # aucune ligne si la valeur n'a pas pu être lue (None) ou est nulle.
    try:
        if live_count and int(live_count) > 0:
            _lc = int(live_count)
            hp_block += f"\n👥 **{_lc} combattant{'s' if _lc != 1 else ''}** en lice"
    except Exception:
        pass

    # Tâche B.1 : ÉTAT DE PHASE / ENRAGE affiché (lecture seule, in-memory, fail-safe).
    _phase_line = ""
    try:
        if alive:
            if _is_enraged(expires_ts):
                _phase_line = ("\n💢 **BOSS ENRAGÉ !** Achevez-le avant la fin du "
                               "timer pour un **bonus de pièces** !")
            else:
                _ph = _phase_for_pct(pct)
                if _ph:
                    _bonus_pct = int((float(_ph[2]) - 1.0) * 100)
                    _phase_line = (f"\n🔥 **Phase de fureur** — vos coups infligent "
                                   f"**+{_bonus_pct} %** de dégâts !")
    except Exception:
        _phase_line = ""

    # Tâche B.3 : JAUGE DU BUFF « 📣 Crier » (lecture seule via combat_actions). FAIL-SAFE.
    _shout_line = ""
    try:
        import combat_actions as _ca
        _shout_line = "\n" + _ca.shout_line(guild_id or 0, event_id)
    except Exception:
        _shout_line = ""

    # A.3 — FAIBLESSE ÉLÉMENTAIRE affichée : déduite du nom du boss. Frapper avec
    # une arme de cet élément donne +25 % (mécanique déjà appliquée à l'attaque,
    # cf. elemental_advantage). FAIL-SAFE : pas de faiblesse lisible → aucune ligne.
    _weak_line = ""
    try:
        _wl = _ev.boss_weakness_label(boss.get('name'))
        if _wl:
            _weak_line = f"\n🎯 **Faiblesse** : {_wl} — une arme de cet élément inflige **+25 %** !"
    except Exception:
        _weak_line = ""

    items = [
        v2_title(f"{boss['emoji']} Boss du jour — {boss['name']}"),
        v2_subtitle(f"Difficulté : {boss['tier']} · {lvl_txt}"),
        v2_divider(),
        v2_body(f"_{boss['description']}_"),
        v2_divider(),
        v2_body(hp_block),
        v2_body(
            f"{when_line}\n"
            f"🤝 HP élevé → **impossible en solo**, combattez ensemble !\n"
            f"🏅 Top 3 dégâts = bonus `{TOP3_BONUS_COINS}` 🪙"
            f"{_weak_line}{_phase_line}{_shout_line}"
        ),
        v2_divider(),
        v2_body(_ev.how_to_play('daily_boss')),
    ]

    # Phase 235.16 : si le warm-up est actif, bandeau « commence <t:..:R> » en haut
    # (le compte à rebours est rendu LIVE côté client, sans re-edit du message).
    try:
        if warmup_ts and warmup_ts > datetime.now(timezone.utc).timestamp():
            items.insert(3, v2_body(
                f"⏰ **Le combat commence <t:{int(warmup_ts)}:R>** — équipe ton meilleur "
                f"stuff (`/inventory`) et **rejoins un vocal** : 🔊 **+25-60 % de dégâts** !"))
    except Exception:
        pass

    # Phase 208 FIX : le bouton DOIT être dans un ActionRow DANS le conteneur
    # (bouton brut top-level d'un LayoutView = 400). Le clic est capté par le
    # DynamicItem DailyBossAttackButton (match du custom_id), comme le World Boss.
    if alive:
        # Phase 235.22 : bouton « 🔔 Me notifier » (type boss) DANS le panneau — toggle
        # le rôle de notif en 1 clic. custom_id capté par EventNotifyButton (bot.py).
        # Phase 269 : ⚡ Charger (+dégâts ta prochaine attaque) & 📣 Crier (buff
        # d'équipe) — clics captés par les DynamicItem CombatChargeButton /
        # CombatShoutButton (combat_actions). 5 boutons max/row → OK.
        items.append(discord.ui.ActionRow(
            Button(label="⚔️ Attaquer", style=discord.ButtonStyle.danger,
                   custom_id=f"dboss_atk:{event_id}"),
            Button(label="🐾 Familier", style=discord.ButtonStyle.success,
                   custom_id=f"dboss_pet:{event_id}"),
            Button(label="⚡ Charger", style=discord.ButtonStyle.primary,
                   custom_id=f"cba_charge:{event_id}"),
            Button(label="📣 Crier", style=discord.ButtonStyle.secondary,
                   custom_id=f"cba_shout:{event_id}"),
            Button(label="🔔 Me notifier", style=discord.ButtonStyle.secondary,
                   custom_id="evtnotif:boss"),
        ))

    class _BossLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=boss.get("color", 0xC0392B)))

    return _BossLayout()


async def _post_boss_panel(
    ch, event_id: int, boss: dict, hp_cur: int, hp_max: int, lifetime_min: int,
    warmup_ts: Optional[float] = None,
) -> Optional[discord.Message]:
    """Poste le panel V2 COMPLET du boss (builder partagé avec le refresh)."""
    if _v2 is None:
        return None
    try:
        expires_ts = int(
            (datetime.now(timezone.utc) + timedelta(minutes=int(lifetime_min))).timestamp())
    except Exception:
        expires_ts = None
    layout = _build_boss_layout(
        boss, hp_cur, hp_max, 0, event_id, expires_ts=expires_ts,
        warmup_ts=warmup_ts, alive=True)
    try:
        return await ch.send(view=layout)
    except Exception as ex:
        print(f"[daily_bosses post_panel] {ex}")
        return None


async def _refresh_boss_panel(guild: discord.Guild, event_id: int, *,
                              force: bool = False) -> None:
    """Met à jour le panneau du boss (HP/dégâts) SANS rien retirer : Phase 235.16,
    on réutilise le builder COMPLET → le descriptif + butin + how-to-play RESTENT
    affichés (avant, le refresh les décapait → « le message disparaît »).

    Phase 251.3 — ANTI-429 : THROTTLE (au plus 1 refresh / _PANEL_REFRESH_MIN_INTERVAL s,
    sauf `force`) + édition via PartialMessage (PATCH seul, plus de GET fetch_message)."""
    # THROTTLE : coalesce les attaques rapprochées (sinon tempête de 429).
    if not force:
        try:
            _now = datetime.now(timezone.utc).timestamp()
            if _now - _last_panel_refresh.get(event_id, 0.0) < _PANEL_REFRESH_MIN_INTERVAL:
                return
            _last_panel_refresh[event_id] = _now
        except Exception:
            pass
    active = await get_active_boss(guild.id)
    if not active or active["event_id"] != event_id:
        return
    boss = get_boss_def(active["boss_id"])
    if not boss or not active["message_id"] or not active["channel_id"]:
        return
    ch = guild.get_channel(active["channel_id"])
    if not ch:
        return
    if _v2 is None:
        return
    # Tâche B.5 : compteur de présence live (lecture seule, fail-safe → None = pas
    # de ligne). Pas de requête réseau Discord supplémentaire (juste une lecture DB).
    _lc = None
    try:
        _lc = await _live_participant_count(event_id)
    except Exception:
        _lc = None
    layout = _build_boss_layout(
        boss, active["hp_current"], active["hp_max"],
        active.get("damage_total", 0), event_id,
        expires_ts=_parse_ts(active.get("expires_at")),
        warmup_ts=_warmup_until.get(event_id),
        alive=active["hp_current"] > 0,
        guild_id=guild.id, live_count=_lc)
    try:
        # PartialMessage : édite SANS fetch (PATCH seul, plus de GET = moitié des 429
        # en moins). Le panneau est un message du BOT → éditable ainsi.
        await ch.get_partial_message(int(active["message_id"])).edit(view=layout)
    except Exception:
        pass


async def _maybe_announce_phase(guild_id: int, event_id: int,
                                hp_cur: int, hp_max: int) -> None:
    """Tâche B.1 : si l'attaque vient de FAIRE FRANCHIR un seuil de phase (66 %/33 %),
    poste UNE fois le message d'ambiance correspondant dans le salon du boss. Anti-spam
    via _phase_reached. 100 % FAIL-SOFT : toute erreur est avalée (jamais bloquant pour
    le combat ; un échec d'annonce ne doit RIEN casser)."""
    try:
        if hp_max <= 0:
            return
        pct = int(hp_cur * 100 / hp_max)
        ph = _phase_for_pct(pct)
        if not ph:
            return
        _seuil, key, _mult, msg_tpl = ph
        reached = _phase_reached.setdefault(event_id, set())
        if key in reached:
            return
        reached.add(key)
        # Récupère le salon du boss (réutilise l'event actif).
        active = await get_active_boss(guild_id)
        if not active or active["event_id"] != event_id or not active.get("channel_id"):
            return
        guild = _bot.get_guild(int(guild_id)) if _bot is not None else None
        if guild is None:
            return
        ch = guild.get_channel(int(active["channel_id"]))
        if ch is None:
            return
        boss = get_boss_def(active["boss_id"])
        name = boss["name"] if boss else "Le boss"
        try:
            await ch.send(
                msg_tpl.format(name=name),
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=45)
        except Exception:
            pass
        # Rafraîchit le panneau pour refléter la phase (force = annonce ponctuelle).
        try:
            await _refresh_boss_panel(guild, event_id, force=True)
        except Exception:
            pass
    except Exception as ex:
        print(f"[_maybe_announce_phase] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Attack (avec gating de niveau)
# ═══════════════════════════════════════════════════════════════════════════

async def record_boss_attack(guild_id: int, user_id: int) -> dict:
    """Enregistre une attaque sur le boss actif, AVEC gating de niveau.

    Retourne {error} OU {success, damage, hp_current, ...}.
    """
    if _get_db is None:
        return {"error": "DB indisponible"}
    active = await get_active_boss(guild_id)
    if not active:
        return {"error": "Aucun boss actif"}
    if active["hp_current"] <= 0:
        return {"error": "Le boss est déjà vaincu"}

    boss = get_boss_def(active["boss_id"])
    if not boss:
        return {"error": "Boss introuvable"}

    # ─── WARM-UP (Phase 235.16) : sas de préparation au spawn ───
    _wu = _warmup_until.get(active["event_id"], 0)
    if _wu and datetime.now(timezone.utc).timestamp() < _wu:
        return {
            "error": (
                f"⏳ **Le boss se prépare !** Le combat commence <t:{int(_wu)}:R>.\n"
                f"Équipe ton meilleur stuff (`/inventory`) et **rejoins un vocal** "
                f"(bonus de dégâts) en attendant !"
            ),
            "warmup": True,
        }

    # ─── GATING DE NIVEAU — Phase 235.28 : RETIRÉ (directive owner, catch-22).
    # L'accès est géré par l'ACTIVITÉ (messages), pas par le niveau. Désactivé
    # via `if False` pour garder la structure intacte.
    if False and boss["min_level"] > 0:
        user_lvl = await get_user_level(guild_id, user_id)
        if user_lvl < boss["min_level"]:
            return {
                "error": (
                    f"🔒 **{boss['name']}** demande le **niveau {boss['min_level']}**. "
                    f"Tu es niveau **{user_lvl}**. Monte en niveau (messages, quêtes, "
                    f"mobs) puis reviens — ou laisse les plus forts s'en charger !"
                ),
                "level_locked": True,
            }

    # Phase 235.25 : GATE D'ACTIVITÉ (s'ajoute au niveau). Boss du jour = 🟡 (20 pts/7 j).
    try:
        import activity_system as _act
        _aok, _asc, _aneed = await _act.check_gate(guild_id, user_id, "daily_boss")
        if not _aok:
            return {"error": _act.block_message("daily_boss", _asc, _aneed),
                    "activity_locked": True}
    except Exception:
        pass

    # Phase 235.25c : mémorise la participation (rappel rétention).
    try:
        import combat_recall as _cr
        await _cr.record(guild_id, user_id)
    except Exception:
        pass

    event_id = active["event_id"]
    attacks_done = await _user_attack_count(event_id, user_id)
    if attacks_done >= MAX_ATTACKS_PER_USER:
        return {
            "error": f"Tu as atteint le max ({MAX_ATTACKS_PER_USER} attaques) "
                     "pour ce boss.",
            "maxed": True,
        }

    damage = random.randint(ATTACK_DAMAGE_MIN, ATTACK_DAMAGE_MAX)
    # Phase 184 (cohérence) : l'ÉQUIPEMENT du joueur compte (ATK total + proc
    # élémentaire de l'arme), comme sur le Boss Raid → ton stuff/forge/éléments
    # servent aussi contre les boss du jour.
    elem_proc = None
    elem_adv = False  # Phase 254-elem : avantage élémentaire appliqué ?
    if _inventory_fn is not None:
        try:
            import events_engine as _ev
            inv = await _inventory_fn(guild_id, user_id)
            damage += int(_ev.inventory_total_stats(inv).get("atk", 0) or 0)
            _p = _ev.roll_elemental_proc(inv.get("weapon"))
            if _p:
                damage += int(_p.get("bonus", 0) or 0)
                elem_proc = _p
            # Phase 254-elem : avantage élémentaire (arme contre l'élément du boss).
            # Additif/SÛR : ×1.0 si pas d'avantage, ×1.25 sinon — ne réduit JAMAIS.
            _bdef254 = get_boss_def(active.get("boss_id"))
            _adv254 = _ev.elemental_advantage(
                inv.get("weapon"),
                _ev.element_for_boss(_bdef254.get("name") if _bdef254 else None))
            if _adv254 > 1.0:
                damage = int(damage * _adv254)
                elem_adv = True
        except Exception:
            pass
    # Phase 235.10 : BOOST VOCAL — être connecté à N'IMPORTE QUEL vocal donne un
    # bonus de dégâts ALÉATOIRE (+12-30 %, plafonné). Même règle que Boss Raid /
    # World Boss. Incite à se retrouver en vocal sans créer le moindre salon.
    voice_bonus = 0
    try:
        _g = _bot.get_guild(guild_id) if _bot is not None else None
        _m = _g.get_member(user_id) if _g is not None else None
        if _m and getattr(_m, "voice", None) and _m.voice.channel is not None:
            voice_bonus = int(damage * (random.uniform(1.25, 1.60) - 1.0))
            if voice_bonus > 0:
                damage += voice_bonus
    except Exception:
        voice_bonus = 0
    # Phase 269 : actions de combat (⚡ Charger / 📣 Crier) — multiplicateurs SORTANTS
    # additifs (>= 1.0, ne réduisent jamais). FAIL-OPEN : une erreur → ×1.0.
    try:
        import combat_actions as _ca
        _amult = _ca.consume_charge_mult(guild_id, user_id) * _ca.shout_mult(guild_id, event_id)
        if _amult != 1.0:
            damage = int(damage * _amult)
    except Exception:
        pass
    # Tâche B.1 : buff de PHASE — en phase basse (66 %/33 %) les coups portent un peu
    # plus fort (combat plus épique). Multiplicateur >= 1.0, BORNÉ, fail-open.
    phase_mult = 1.0
    try:
        phase_mult = _phase_damage_mult(event_id, active["hp_current"], active["hp_max"])
        if phase_mult != 1.0:
            damage = int(damage * phase_mult)
    except Exception:
        phase_mult = 1.0
    damage = min(damage, active["hp_current"])

    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO daily_boss_attackers "
                "(event_id, user_id, damage_dealt, attack_count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(event_id, user_id) DO UPDATE SET "
                "damage_dealt = damage_dealt + ?, "
                "attack_count = attack_count + 1, "
                "last_attack_at = CURRENT_TIMESTAMP",
                (event_id, user_id, damage, damage),
            )
            await db.execute(
                "UPDATE daily_boss_events SET "
                "hp_current = MAX(0, hp_current - ?), "
                "damage_total = damage_total + ? WHERE id=?",
                (damage, damage, event_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[record_boss_attack] {ex}")
        return {"error": str(ex)}

    # Feed Chronicle (boss_damage) — fail-soft tie-in
    try:
        import story_engine as _se
        await _se.on_boss_damage(guild_id, damage, user_id)
    except Exception:
        pass

    # Phase 253 : crédite l'alliance de l'attaquant (classement de combat). Fail-open.
    if _alliance_points_fn is not None:
        try:
            await _alliance_points_fn(guild_id, user_id, damage)
        except Exception:
            pass

    updated = await get_active_boss(guild_id)
    boss_dead = (updated is None) or (updated["hp_current"] <= 0)

    # Tâche B.1 : détection de FRANCHISSEMENT DE PHASE (66 %/33 %) → message
    # d'ambiance UNE seule fois par phase (anti-spam via _phase_reached). Sépare le
    # calcul (toujours fail-open) de l'annonce (fire-and-forget). Tâche B.2 : on note
    # qui porte le COUP FATAL pour le bonus (passé à resolve via le set partagé).
    enraged = False
    try:
        enraged = _is_enraged(_parse_ts(active.get("expires_at")))
    except Exception:
        enraged = False
    if boss_dead:
        # Coup fatal : mémorise le tueur AVANT de résoudre (anti-doublon dans resolve).
        try:
            _fatal_blow[event_id] = (int(user_id), bool(enraged))
        except Exception:
            pass
        await resolve_daily_boss(event_id)
        return {"success": True, "damage": damage, "boss_dead": True,
                "attack_count": attacks_done + 1, "elem": elem_proc,
                "voice_bonus": voice_bonus, "elem_adv": elem_adv,
                "fatal_blow": True, "enraged": enraged, "phase_mult": phase_mult}
    else:
        # Annonce d'ambiance de phase (fire-and-forget, fail-soft, jamais bloquant).
        try:
            await _maybe_announce_phase(guild_id, event_id,
                                        updated["hp_current"], updated["hp_max"])
        except Exception:
            pass

    return {
        "success": True,
        "damage": damage,
        "hp_current": updated["hp_current"],
        "hp_max": updated["hp_max"],
        "attack_count": attacks_done + 1,
        "max_attacks": MAX_ATTACKS_PER_USER,
        "boss_dead": False,
        "elem": elem_proc,
        "voice_bonus": voice_bonus,
        "elem_adv": elem_adv,
        "phase_mult": phase_mult,
        "enraged": enraged,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Resolve
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_daily_boss(event_id: int) -> Optional[dict]:
    if _get_db is None or _bot is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, boss_id, hp_current, hp_max, damage_total, "
                "channel_id, status FROM daily_boss_events WHERE id=?",
                (event_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        guild_id, boss_id, hp_current, hp_max, dmg_total, channel_id, status = row
        if status != "alive":
            return None
    except Exception:
        return None

    boss = get_boss_def(boss_id)
    killed = int(hp_current) <= 0
    final_status = "killed" if killed else "expired"

    # FIX audit 2026 : claim ATOMIQUE du statut final AVANT toute distribution. Le
    # garde `status != "alive"` ci-dessus est une LECTURE non-atomique : 2 appels
    # concurrents (coup fatal + watchdog d'expiration) peuvent tous deux le
    # franchir. Ici un seul gagne le claim `AND status='alive'` ; l'autre s'arrête
    # → pas de double coins/œuf. FAIL-OPEN : si le claim plante, on continue (un
    # boss résolu doit payer) et l'UPDATE final plus bas sert de filet.
    try:
        async with _get_db() as db:
            _rc = await db.execute(
                "UPDATE daily_boss_events SET status=?, ended_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='alive'",
                (final_status, event_id),
            )
            await db.commit()
        if getattr(_rc, "rowcount", 0) != 1:
            return None
    except Exception:
        pass

    # Attackers classés
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, damage_dealt FROM daily_boss_attackers "
                "WHERE event_id=? AND damage_dealt > 0 "
                "ORDER BY damage_dealt DESC",
                (event_id,),
            ) as cur:
                attackers = [(int(r[0]), int(r[1])) for r in await cur.fetchall()]
    except Exception:
        attackers = []

    # Tâche B.2 : récupère (et CONSOMME) l'info du coup fatal — anti-doublon : un seul
    # tueur récompensé, même si resolve est appelé 2× (coup fatal + watchdog). Fail-safe.
    fatal_uid = None
    fatal_enraged = False
    try:
        _fb = _fatal_blow.pop(event_id, None)
        if _fb:
            fatal_uid = int(_fb[0])
            fatal_enraged = bool(_fb[1])
    except Exception:
        fatal_uid, fatal_enraged = None, False
    killer_info = None  # passé au récap (nom + bonus du tueur)

    rewards = []
    for i, (uid, dmg) in enumerate(attackers):
        coins = int(dmg * COIN_PER_DAMAGE)
        if killed:
            coins += PARTICIPATION_BONUS_COINS
            if i < 3:
                coins += TOP3_BONUS_COINS
        # Tâche B.4 : BONUS D'ASSIDUITÉ — petit multiplicateur BORNÉ (≤ +15 %) pour
        # les joueurs qui reviennent régulièrement aux combats. N'augmente QUE les
        # pièces, jamais les dégâts. FAIL-OPEN : ×1.0 (aucun changement) sur erreur.
        try:
            import combat_recall as _cr
            _amult = await _cr.assiduity_mult(guild_id, uid)
            if _amult and _amult > 1.0:
                coins = int(coins * _amult)
        except Exception:
            pass
        # Tâche B.2 : BONUS DU COUP FATAL (seulement si le boss est bien tué) — petit
        # extra MODESTE au porteur du coup tuant. + Tâche B.1 : si le boss était ENRAGÉ
        # au moment du kill, bonus supplémentaire (récompense d'avoir fini avant la fin).
        fatal_bonus = 0
        if killed and fatal_uid is not None and uid == fatal_uid:
            fatal_bonus = PARTICIPATION_BONUS_COINS  # MODESTE (= bonus de participation)
            if fatal_enraged:
                fatal_bonus += _ENRAGE_REWARD_BONUS
            coins += fatal_bonus
            killer_info = {"user_id": uid, "bonus": fatal_bonus,
                           "enraged": fatal_enraged}
        try:
            if _add_coins:
                await _add_coins(guild_id, uid, coins)
        except Exception:
            pass
        # Phase 248c : œuf de familier sur kill du boss du jour (top 3 = meilleur
        # tier + chance plus haute). Récompense le farm des boss. FAIL-OPEN.
        if killed:
            try:
                import random as _rnd
                import pet_eggs as _pe
                if _rnd.random() < (0.35 if i < 3 else 0.15):
                    await _pe.grant_event_egg(
                        guild_id, uid, source="daily_boss",
                        tier=("grand" if i < 3 else "boss"))
            except Exception:
                pass
        rewards.append({"user_id": uid, "damage": dmg, "coins": coins,
                        "rank": i + 1})

    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE daily_boss_events SET status=?, ended_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (final_status, event_id),
            )
            await db.commit()
    except Exception:
        pass

    # Tâche B.1/B.2 : libère l'état en mémoire de cet event (phases franchies,
    # enrage annoncé, coup fatal). Fail-safe — purge best-effort.
    try:
        _phase_reached.pop(event_id, None)
        _enrage_announced.pop(event_id, None)
        _fatal_blow.pop(event_id, None)
    except Exception:
        pass

    guild = _bot.get_guild(int(guild_id))
    if guild and channel_id:
        ch = guild.get_channel(int(channel_id))
        if ch:
            await _announce_resolution(
                ch, boss, killed, int(dmg_total), int(hp_max), rewards,
                killer_info=killer_info,
            )

    # Phase 205 : le boss est terminé → supprimer son panneau (le récap le
    # remplace) pour ne pas laisser traîner un boss mort dans le salon.
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT message_id, channel_id FROM daily_boss_events WHERE id=?",
                (event_id,),
            ) as cur:
                prow = await cur.fetchone()
        if prow and prow[0] and prow[1] and guild:
            pch = guild.get_channel(int(prow[1]))
            if pch:
                try:
                    pmsg = await pch.fetch_message(int(prow[0]))
                    await pmsg.delete()
                except Exception:
                    pass
    except Exception as ex:
        print(f"[resolve_daily_boss panel delete] {ex}")

    # Phase 210 : supprimer l'arène dédiée (catégorie + texte + vocaux) ~2 min
    # après le récap (le temps de le lire). Fire-and-forget ; le balayage des
    # orphelins (stale_event_cleanup) rattrape si perdu (reboot). No-op si le
    # boss était dans un salon partagé (aucune arène enregistrée).
    if _arena_delete_fn is not None and guild and channel_id:
        try:
            asyncio.create_task(_arena_delete_fn(guild, int(channel_id)))
        except Exception as ex:
            print(f"[resolve_daily_boss arena delete] {ex}")

    print(
        f"[daily_bosses] resolve event={event_id} killed={killed} "
        f"dmg={dmg_total}/{hp_max} attackers={len(attackers)}"
    )
    return {"killed": killed, "damage_total": int(dmg_total),
            "attackers": len(attackers), "rewards": rewards}


async def _announce_resolution(
    ch, boss: Optional[dict], killed: bool, dmg_total: int, hp_max: int,
    rewards: list, killer_info: Optional[dict] = None,
) -> None:
    name = boss["name"] if boss else "Le boss"
    emoji = boss["emoji"] if boss else "⚔️"

    # Phase 258 : récap de fin de combat UNIQUE, compact et BORNÉ via le helper
    # partagé ui_v2.combat_recap_view (même format/taille pour TOUS les events).
    # On NE touche RIEN à l'économie : tout le monde reste payé (la boucle de
    # rewards en amont a déjà crédité chacun) — seul l'AFFICHAGE est borné. La
    # ligne « +N autres récompensés » rappelle que tous les participants le sont.
    outcome = "win" if killed else "fail"
    podium = []
    for r in rewards[:3]:
        member = ch.guild.get_member(r["user_id"]) if ch.guild else None
        nm = member.display_name if member else f"User {r['user_id']}"
        podium.append((nm, r["coins"]))
    others_count = max(0, len(rewards) - 3)

    # Texte compact équivalent pour la copie persistante des chroniques (borné).
    head = f"{emoji} {name} " + ("EST VAINCU !" if killed else "s'est retiré...")
    _medals = ["🥇", "🥈", "🥉"]
    _lines = [
        ("✅ Vaincu" if killed else "⏳ Non vaincu")
        + f" · {len(rewards)} combattant" + ("s" if len(rewards) != 1 else "")
        + (f" · `{dmg_total:,}` dégâts" if dmg_total else "")
    ]
    for _i, (nm, coins) in enumerate(podium):
        _lines.append(f"{_medals[_i]} **{nm}** · `{coins:,}` 🪙")
    if others_count:
        _lines.append(f"🔸 _+{others_count} autres récompensés_")
    # Tâche B.2 : ligne « coup fatal » — le porteur du coup tuant + son petit bonus
    # (+ mention de l'enrage si le boss était enragé). FAIL-SAFE : aucune ligne si
    # killer_info manque ou est illisible.
    try:
        if killed and killer_info and killer_info.get("user_id"):
            _km = ch.guild.get_member(int(killer_info["user_id"])) if ch.guild else None
            _knm = _km.display_name if _km else f"User {killer_info['user_id']}"
            _kbonus = int(killer_info.get("bonus", 0) or 0)
            _enr = " ⚡ _(boss enragé !)_" if killer_info.get("enraged") else ""
            _lines.append(
                f"🗡️ **Coup fatal : {_knm}**"
                + (f" · +`{_kbonus:,}` 🪙 bonus" if _kbonus else "")
                + _enr)
    except Exception:
        pass
    body = "\n".join(_lines)

    try:
        msg = await ch.send(
            view=ui_v2.combat_recap_view(
                emoji, name, outcome, podium,
                others_count=others_count,
                participants=len(rewards),
                total_damage=(dmg_total or None)),
            allowed_mentions=discord.AllowedMentions.none())
        # Phase 205 : le récap de fin s'auto-supprime (évite d'encombrer le
        # Discord avec les vieux « X s'est retiré / X est vaincu »).
        if msg and _cleanup_register_fn is not None:
            try:
                await _cleanup_register_fn(msg, RESOLUTION_CLEANUP_SECONDS, 'boss_resolution')
            except Exception:
                pass
        # Phase 223 : copie PERSISTANTE du rapport dans « 📜 chroniques-combat »
        # (l'arène du boss est éphémère → le rapport reste consultable au propre).
        if _report_fn is not None and ch is not None and getattr(ch, 'guild', None):
            try:
                await _report_fn(ch.guild, head.replace("**", ""), body)
            except Exception:
                pass
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent button
# ═══════════════════════════════════════════════════════════════════════════

class DailyBossAttackButton(
    discord.ui.DynamicItem[Button],
    template=r"dboss_atk:(?P<event_id>\d+)",
):
    """Bouton public d'attaque du boss du jour (persistent, tout le monde
    peut cliquer — le gating de niveau est dans le callback)."""

    def __init__(self, event_id: int):
        super().__init__(
            Button(
                label="⚔️ Attaquer le boss",
                style=discord.ButtonStyle.danger,
                custom_id=f"dboss_atk:{event_id}",
            )
        )
        self.event_id = event_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["event_id"]))

    async def callback(self, btn_i: discord.Interaction):
        # Phase 257.3 : ACK D'ABORD (defer) — acquitter le clic AVANT le cooldown, sinon
        # un clic noyé affiche « Échec de l'interaction ». Defer = requête légère (route
        # interaction, PAS la webhook) → pas de tempête 429 ; l'anti-429 reste assuré car
        # un clic noyé ne fait AUCUN followup.
        try:
            await btn_i.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
            pass
        # Phase 251.24 — ANTI-429 : cooldown PAR JOUEUR APRÈS l'ack (clic noyé = 0 followup).
        try:
            _key = (btn_i.guild.id if btn_i.guild else 0,
                    btn_i.user.id if btn_i.user else 0)
            _now = datetime.now(timezone.utc).timestamp()
            if _now - _last_user_attack.get(_key, 0.0) < _ATTACK_COOLDOWN:
                return
            _last_user_attack[_key] = _now
        except Exception:
            pass

        if btn_i.guild is None:
            try:
                await btn_i.followup.send("❌ Serveur uniquement.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            result = await record_boss_attack(btn_i.guild.id, btn_i.user.id)
            if result.get("error"):
                await btn_i.followup.send(result["error"], ephemeral=True)
                return

            # Rafraîchit le panneau public (HP live)
            try:
                await _refresh_boss_panel(btn_i.guild, self.event_id)
            except Exception:
                pass

            # Phase 184 : note de proc élémentaire (si l'arme a déclenché)
            _ep = result.get("elem")
            _elem_note = (
                f"\n{_ep['emoji']} **{_ep['name']}** ! +`{_ep['bonus']}` dégâts élémentaires"
                if _ep else ""
            )
            # Phase 235.10 : note de BOOST VOCAL (si connecté à un vocal)
            _vb = int(result.get("voice_bonus", 0) or 0)
            _voice_note = (f"\n🔊 **Boost vocal** ! +`{_vb}` dégâts" if _vb > 0 else "")
            # Phase 254-elem : note d'avantage élémentaire
            _adv_note = ("\n🗡️ **Avantage élémentaire** ! +25 % (ton arme contre l'élément du boss)"
                         if result.get("elem_adv") else "")
            if result.get("boss_dead"):
                await btn_i.followup.send(
                    f"⚔️ **{result['damage']} dégâts** — coup final ! "
                    f"Le boss est tombé, récompenses distribuées. 🎉{_elem_note}{_voice_note}{_adv_note}",
                    ephemeral=True,
                )
            else:
                pct = int(result["hp_current"] * 100 / max(1, result["hp_max"]))
                await btn_i.followup.send(
                    f"⚔️ **{result['damage']} dégâts** infligés !{_elem_note}{_voice_note}{_adv_note}\n"
                    f"_Boss : `{result['hp_current']:,}/{result['hp_max']:,}` HP "
                    f"({pct}%) · tes attaques : "
                    f"`{result['attack_count']}/{result['max_attacks']}`_",
                    ephemeral=True,
                )
        except Exception as ex:
            print(f"[dboss_atk callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


async def record_pet_assist(guild_id: int, user_id: int) -> dict:
    """Phase 261 : le FAMILIER du joueur frappe le boss du jour (assist).
    Réutilise le cœur PARTAGÉ _pet_strike_fn (familier actif + cooldown 90 s + soin
    passif), applique les dégâts à daily_boss_events SANS consommer le quota
    d'attaques, crédite l'alliance, et résout si le boss tombe. FAIL-OPEN."""
    if _get_db is None or _pet_strike_fn is None:
        return {"ok": False, "msg": "🐾 Familier indisponible un instant."}
    active = await get_active_boss(guild_id)
    if not active:
        return {"ok": False, "msg": "❌ Aucun boss du jour actif."}
    event_id = active["event_id"]
    _wu = _warmup_until.get(event_id, 0)
    if _wu and datetime.now(timezone.utc).timestamp() < _wu:
        return {"ok": False, "msg": "⏳ Le boss se prépare — ton familier patiente un instant."}
    strike = await _pet_strike_fn(guild_id, user_id)
    if not strike.get("ok"):
        return {"ok": False, "msg": strike.get("msg", "🐾 Familier indisponible.")}
    dmg = max(0, min(int(strike.get("dmg", 0) or 0), int(active["hp_current"])))
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO daily_boss_attackers (event_id, user_id, damage_dealt, attack_count) "
                "VALUES (?, ?, ?, 0) "
                "ON CONFLICT(event_id, user_id) DO UPDATE SET "
                "damage_dealt = damage_dealt + ?, last_attack_at = CURRENT_TIMESTAMP",
                (event_id, user_id, dmg, dmg),
            )
            await db.execute(
                "UPDATE daily_boss_events SET hp_current = MAX(0, hp_current - ?), "
                "damage_total = damage_total + ? WHERE id=?",
                (dmg, dmg, event_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[record_pet_assist] {ex}")
        return {"ok": False, "msg": "❌ Erreur, réessaie."}
    if _alliance_points_fn is not None and dmg > 0:
        try:
            await _alliance_points_fn(guild_id, user_id, dmg)
        except Exception:
            pass
    updated = await get_active_boss(guild_id)
    dead = (updated is None) or (updated["hp_current"] <= 0)
    if dead:
        try:
            await resolve_daily_boss(event_id)
        except Exception:
            pass
    else:
        # Tâche B.1 : un assist de familier peut aussi faire franchir une phase.
        try:
            await _maybe_announce_phase(guild_id, event_id,
                                        updated["hp_current"], updated["hp_max"])
        except Exception:
            pass
    text = f"🐾 **{strike.get('label', 'Familier')}** bondit et inflige `{dmg}` dégâts au boss !"
    if strike.get("note"):
        text += f"\n{strike['note']}"
    if dead:
        text += "\n🎉 **Coup final — boss vaincu !**"
    return {"ok": True, "text": text}


class DailyBossPetButton(
    discord.ui.DynamicItem[Button],
    template=r"dboss_pet:(?P<event_id>\d+)",
):
    """Phase 261 : bouton 🐾 Familier sur le boss du jour (persistent, defer-first)."""

    def __init__(self, event_id: int):
        super().__init__(
            Button(label="🐾 Familier", style=discord.ButtonStyle.success,
                   custom_id=f"dboss_pet:{event_id}")
        )
        self.event_id = event_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["event_id"]))

    async def callback(self, btn_i: discord.Interaction):
        try:
            await btn_i.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
            pass
        # Anti-429 : cooldown léger PAR JOUEUR (dédié au 🐾) AVANT tout followup.
        try:
            _key = (btn_i.guild.id if btn_i.guild else 0, btn_i.user.id if btn_i.user else 0)
            _now = datetime.now(timezone.utc).timestamp()
            if _now - _last_pet_click.get(_key, 0.0) < _ATTACK_COOLDOWN:
                return
            _last_pet_click[_key] = _now
        except Exception:
            pass
        if btn_i.guild is None:
            try:
                await btn_i.followup.send("❌ Serveur uniquement.", ephemeral=True)
            except Exception:
                pass
            return
        try:
            res = await record_pet_assist(btn_i.guild.id, btn_i.user.id)
            if not res.get("ok"):
                await btn_i.followup.send(res.get("msg", "🐾 Indisponible."), ephemeral=True)
                return
            try:
                await _refresh_boss_panel(btn_i.guild, self.event_id)
            except Exception:
                pass
            await btn_i.followup.send(res["text"], ephemeral=True)
        except Exception as ex:
            print(f"[dboss_pet callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(DailyBossAttackButton)
        bot_instance.add_dynamic_items(DailyBossPetButton)  # Phase 261 : 🐾 Familier
    except Exception as ex:
        print(f"[daily_bosses register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=15)
async def daily_boss_task():
    """Toutes les 15 min : spawn aux créneaux 12/17/21/1 FR + resolve expirés."""
    if _bot is None or _get_db is None:
        return
    try:
        # Spawn si on est dans un créneau
        if _current_slot_key() is not None:
            for guild in _bot.guilds:
                try:
                    await trigger_daily_boss(guild)
                except Exception as ex:
                    print(f"[daily_boss_task trigger g={guild.id}] {ex}")

        # Resolve les boss expirés (timer dépassé)
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with _get_db() as db:
                async with db.execute(
                    "SELECT id FROM daily_boss_events "
                    "WHERE status='alive' AND (expires_at < ? OR hp_current <= 0)",
                    (now_iso,),
                ) as cur:
                    to_resolve = [int(r[0]) for r in await cur.fetchall()]
            for eid in to_resolve:
                try:
                    await resolve_daily_boss(eid)
                except Exception as ex:
                    print(f"[daily_boss_task resolve e={eid}] {ex}")
        except Exception as ex:
            print(f"[daily_boss_task resolve scan] {ex}")

        # Phase 207 : NETTOYAGE BACKLOG — supprime les panneaux des boss DÉJÀ
        # terminés qui traînent encore (events d'avant la Phase 205, ou si la
        # suppression à la résolution a échoué). On ne touche QU'À nos propres
        # panneaux (message_id stocké) puis on remet message_id=0 pour ne pas
        # réessayer. LIMIT 20/passage (anti rate-limit).
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT id, guild_id, channel_id, message_id FROM daily_boss_events "
                    "WHERE status != 'alive' AND message_id IS NOT NULL AND message_id != 0 "
                    "LIMIT 20"
                ) as cur:
                    old_panels = await cur.fetchall()
            for ev_id, g_id, ch_id, m_id in old_panels:
                try:
                    g = _bot.get_guild(int(g_id)) if g_id else None
                    pch = g.get_channel(int(ch_id)) if (g and ch_id) else None
                    if pch and m_id:
                        try:
                            pmsg = await pch.fetch_message(int(m_id))
                            await pmsg.delete()
                        except Exception:
                            pass  # déjà supprimé / introuvable
                    async with _get_db() as db:
                        await db.execute(
                            "UPDATE daily_boss_events SET message_id=0 WHERE id=?",
                            (ev_id,))
                        await db.commit()
                except Exception as ex:
                    print(f"[daily_boss_task backlog ev={ev_id}] {ex}")
        except Exception as ex:
            print(f"[daily_boss_task backlog scan] {ex}")
    except Exception as ex:
        print(f"[daily_boss_task] {ex}")


@daily_boss_task.before_loop
async def _daily_boss_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "DAILY_BOSS_CATALOG",
    "BOSS_HOURS",
    "MAX_ATTACKS_PER_USER",
    "ATTACK_DAMAGE_MIN",
    "ATTACK_DAMAGE_MAX",
    "COIN_PER_DAMAGE",
    "TOP3_BONUS_COINS",
    "PARTICIPATION_BONUS_COINS",
    "setup",
    "init_db",
    "get_boss_def",
    "list_boss_ids",
    "get_user_level",
    "get_active_boss",
    "trigger_daily_boss",
    "_smart_combat_ping",
    "record_boss_attack",
    "resolve_daily_boss",
    "DailyBossAttackButton",
    "daily_boss_task",
    "register_persistent_views",
]
