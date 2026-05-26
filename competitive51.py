"""
Phase 51 — COMPÉTITIF
─────────────────────────────────────────────────────────
• BINGO_CHALLENGES : 40+ défis pour la carte 5x5 mensuelle.
• PREDICTION_TEMPLATES : exemples de prédictions binaires.
• FACTION_WAR_OBJECTIVES : objectifs compétitifs saisonniers.
"""
from __future__ import annotations

import random
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  BINGO — Défis pour la carte 5x5 mensuelle (25 cellules)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Chaque défi a un goal_kind compatible avec les stats existantes du bot.
# Le bot auto-track quand le joueur l'atteint et débloque la cellule.
#
# Goal kinds supportés :
# - messages : N messages envoyés ce mois
# - quests_done : N quêtes journalières complétées
# - events_won : N events gagnés (boss/treasure/quiz/world_boss/daily_riddle)
# - reactions_given : N réactions données
# - achievements_unlocked : N achievements débloqués
# - level_reached : atteindre level N
# - pet_level : pet level >= N
# - prestige : avoir prestige >= N
# - alliance_joined : être dans une alliance
# - confession_sent : N confessions envoyées
# - wheel_spins : N spins de la Daily Wheel
# - mission_steps : N étapes de mission complétées
# - days_active : N jours d'activité ce mois

BINGO_CHALLENGES = [
    {"id": "msg_50",         "title": "💬 50 messages",         "goal_kind": "messages",          "goal_count": 50},
    {"id": "msg_200",        "title": "💬 200 messages",        "goal_kind": "messages",          "goal_count": 200},
    {"id": "msg_500",        "title": "💬 500 messages",        "goal_kind": "messages",          "goal_count": 500},
    {"id": "quests_10",      "title": "📜 10 quêtes",           "goal_kind": "quests_done",       "goal_count": 10},
    {"id": "quests_30",      "title": "📜 30 quêtes",           "goal_kind": "quests_done",       "goal_count": 30},
    {"id": "events_3",       "title": "🏆 3 events gagnés",     "goal_kind": "events_won",        "goal_count": 3},
    {"id": "events_10",      "title": "🏆 10 events gagnés",    "goal_kind": "events_won",        "goal_count": 10},
    {"id": "reactions_50",   "title": "👀 50 réactions",        "goal_kind": "reactions_given",   "goal_count": 50},
    {"id": "reactions_200",  "title": "👀 200 réactions",       "goal_kind": "reactions_given",   "goal_count": 200},
    {"id": "ach_3",          "title": "🏅 3 hauts faits",       "goal_kind": "achievements_unlocked", "goal_count": 3},
    {"id": "ach_10",         "title": "🏅 10 hauts faits",      "goal_kind": "achievements_unlocked", "goal_count": 10},
    {"id": "level_5",        "title": "🎚️ Level 5",            "goal_kind": "level_reached",     "goal_count": 5},
    {"id": "level_15",       "title": "🎚️ Level 15",           "goal_kind": "level_reached",     "goal_count": 15},
    {"id": "level_30",       "title": "🎚️ Level 30",           "goal_kind": "level_reached",     "goal_count": 30},
    {"id": "pet_5",          "title": "🐾 Pet level 5",         "goal_kind": "pet_level",         "goal_count": 5},
    {"id": "pet_10",         "title": "🐾 Pet level 10",        "goal_kind": "pet_level",         "goal_count": 10},
    {"id": "prestige_1",     "title": "✨ Prestige 1",          "goal_kind": "prestige",          "goal_count": 1},
    {"id": "alliance_in",    "title": "🤝 Dans une Alliance",   "goal_kind": "alliance_joined",   "goal_count": 1},
    {"id": "confess_3",      "title": "🤫 3 confessions",       "goal_kind": "confession_sent",   "goal_count": 3},
    {"id": "wheel_10",       "title": "🎰 10 spins Wheel",      "goal_kind": "wheel_spins",       "goal_count": 10},
    {"id": "wheel_30",       "title": "🎰 30 spins Wheel",      "goal_kind": "wheel_spins",       "goal_count": 30},
    {"id": "mission_steps_3","title": "🎯 3 étapes mission",    "goal_kind": "mission_steps",     "goal_count": 3},
    {"id": "mission_steps_8","title": "🎯 8 étapes mission",    "goal_kind": "mission_steps",     "goal_count": 8},
    {"id": "days_10",        "title": "📅 10 jours actifs",     "goal_kind": "days_active",       "goal_count": 10},
    {"id": "days_20",        "title": "📅 20 jours actifs",     "goal_kind": "days_active",       "goal_count": 20},
    {"id": "msg_100",        "title": "💬 100 messages",        "goal_kind": "messages",          "goal_count": 100},
    {"id": "quests_20",      "title": "📜 20 quêtes",           "goal_kind": "quests_done",       "goal_count": 20},
    {"id": "events_5",       "title": "🏆 5 events gagnés",     "goal_kind": "events_won",        "goal_count": 5},
    {"id": "reactions_100",  "title": "👀 100 réactions",       "goal_kind": "reactions_given",   "goal_count": 100},
    {"id": "ach_5",          "title": "🏅 5 hauts faits",       "goal_kind": "achievements_unlocked", "goal_count": 5},
    {"id": "level_10",       "title": "🎚️ Level 10",           "goal_kind": "level_reached",     "goal_count": 10},
    {"id": "level_20",       "title": "🎚️ Level 20",           "goal_kind": "level_reached",     "goal_count": 20},
    {"id": "wheel_20",       "title": "🎰 20 spins Wheel",      "goal_kind": "wheel_spins",       "goal_count": 20},
    {"id": "confess_1",      "title": "🤫 1 confession",        "goal_kind": "confession_sent",   "goal_count": 1},
    {"id": "days_5",         "title": "📅 5 jours actifs",      "goal_kind": "days_active",       "goal_count": 5},
    {"id": "msg_1000",       "title": "💬 1000 messages",       "goal_kind": "messages",          "goal_count": 1000},
    {"id": "events_20",      "title": "🏆 20 events gagnés",    "goal_kind": "events_won",        "goal_count": 20},
    {"id": "pet_15",         "title": "🐾 Pet level 15",        "goal_kind": "pet_level",         "goal_count": 15},
    {"id": "prestige_2",     "title": "✨ Prestige 2",          "goal_kind": "prestige",          "goal_count": 2},
    {"id": "mission_steps_5","title": "🎯 5 étapes mission",    "goal_kind": "mission_steps",     "goal_count": 5},
]


def generate_bingo_card_seeded(seed: int) -> list:
    """Génère une carte 5x5 deterministique pour un seed donné.

    Retourne une liste de 25 défis. Le seed permet à tous les membres de la
    guilde d'avoir la même carte au même mois (équité).
    """
    rng = random.Random(seed)
    pool = list(BINGO_CHALLENGES)
    rng.shuffle(pool)
    return pool[:25]


# ═══════════════════════════════════════════════════════════════════════════════
#  BINGO — Détection de lignes complétées
# ═══════════════════════════════════════════════════════════════════════════════
#
# La carte est numérotée :
# 0  1  2  3  4
# 5  6  7  8  9
# 10 11 12 13 14
# 15 16 17 18 19
# 20 21 22 23 24
#
# Lignes : 5 horizontales + 5 verticales + 2 diagonales = 12 lignes

BINGO_LINES = [
    # Horizontales
    [0, 1, 2, 3, 4],
    [5, 6, 7, 8, 9],
    [10, 11, 12, 13, 14],
    [15, 16, 17, 18, 19],
    [20, 21, 22, 23, 24],
    # Verticales
    [0, 5, 10, 15, 20],
    [1, 6, 11, 16, 21],
    [2, 7, 12, 17, 22],
    [3, 8, 13, 18, 23],
    [4, 9, 14, 19, 24],
    # Diagonales
    [0, 6, 12, 18, 24],
    [4, 8, 12, 16, 20],
]


def get_completed_lines(checked_cells: set) -> list:
    """Retourne les indices des lignes complètement remplies."""
    completed = []
    for idx, line in enumerate(BINGO_LINES):
        if all(c in checked_cells for c in line):
            completed.append(idx)
    return completed


# ═══════════════════════════════════════════════════════════════════════════════
#  FACTION WARS — Objectifs saisonniers
# ═══════════════════════════════════════════════════════════════════════════════
#
# Une saison = un objectif global qui se mesure par faction. Vainqueur =
# faction la mieux placée à la fin de la saison.

FACTION_WAR_OBJECTIVES = [
    {
        "kind": "events_won",
        "title": "🏆 La Course aux Victoires",
        "description": "Quelle faction gagnera le plus d'events ?",
    },
    {
        "kind": "messages_total",
        "title": "💬 La Bataille de l'Activité",
        "description": "Quelle faction parle le plus dans le serveur ?",
    },
    {
        "kind": "boss_damage",
        "title": "⚔️ Champions des Boss",
        "description": "Quelle faction fait le plus de dégâts aux boss ?",
    },
    {
        "kind": "quests_done",
        "title": "📜 Diligence Collective",
        "description": "Quelle faction complète le plus de quêtes ?",
    },
]


def pick_random_faction_war_objective() -> dict:
    return random.choice(FACTION_WAR_OBJECTIVES)


__all__ = [
    "BINGO_CHALLENGES", "BINGO_LINES",
    "generate_bingo_card_seeded", "get_completed_lines",
    "FACTION_WAR_OBJECTIVES", "pick_random_faction_war_objective",
]
