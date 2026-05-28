"""Phase 164.3 : smoke tests — chaque module Phase 152-163 doit s'importer
sans planter. Si quelqu'un casse un import (typo, dépendance manquante),
ce test échoue avant de toucher la prod.
"""
import importlib

import pytest


PHASE_163_MODULES = [
    "dm_digest",
    "webhook_tracker",
    "owner_digest",
    "reputation",
    "pet_evolution",
    "daily_prompt",
    "onboarding_journey",
    "mentor_bonus",
    "honeypot",
    "behavior_anomaly",
    "roblox_game_stats",
    "roblox_raffle",
    "stream_watch_party",
    "community_goals",
    "coin_economy",
    "weekly_stats",
    "server_pulse",
    # Phase 165 — nouveaux modules
    "stream_schedule",
    "activity_heatmap",
    # Phase 166 — anti-token-leak, birthday, welcome, spotlight
    "anti_token_leak",
    "birthday_panel",
    "welcome_ack",
    "spotlight_quality",
    # Phase 167 — status rotator, voice autoclean, member risk
    "status_rotator",
    "voice_autoclean",
    "member_risk",
    # Phase 168 — error logger
    "error_logger",
    # Phase 169 — mob hunts, marchand, invasion
    "mob_hunts",
    "wandering_merchant",
    "world_invasion",
    # Phase 170 — Chronique d'Abylumis (récit collectif persistant)
    "story_engine",
    "codex_chronicle",
    # Phase 170.2-3 : NPCs vivants + rencontres quotidiennes
    "npc_personalities",
    "daily_encounters",
    # Phase 170.4 : Conseil des Anciens hebdomadaire
    "weekly_council",
]


@pytest.mark.parametrize("mod_name", PHASE_163_MODULES)
def test_module_imports(mod_name):
    """Chaque module se charge sans erreur."""
    mod = importlib.import_module(mod_name)
    assert mod is not None


@pytest.mark.parametrize("mod_name", PHASE_163_MODULES)
def test_module_has_setup(mod_name):
    """Chaque module expose un `setup(...)` callable."""
    mod = importlib.import_module(mod_name)
    assert hasattr(mod, "setup"), f"{mod_name} sans fonction setup()"
    assert callable(mod.setup)


# Modules qui ont un init_db (pas tous, weekly_stats/server_pulse n'en ont
# pas car ils lisent des tables d'autres modules).
INIT_DB_MODULES = [
    "dm_digest",
    "webhook_tracker",
    "owner_digest",
    "reputation",
    "pet_evolution",
    "daily_prompt",
    "onboarding_journey",
    "mentor_bonus",
    "honeypot",
    "behavior_anomaly",
    "roblox_game_stats",
    "roblox_raffle",
    "stream_watch_party",
    "community_goals",
    "coin_economy",
    # Phase 165
    "stream_schedule",
    "activity_heatmap",
    # Phase 166 (birthday_panel n'a pas d'init_db, lit cfg directement)
    "anti_token_leak",
    "welcome_ack",
    "spotlight_quality",
    # Phase 167 (status_rotator n'a pas d'init_db, pas de table)
    "voice_autoclean",
    "member_risk",
    # Phase 168 — error_logger
    "error_logger",
    # Phase 169 — mob_hunts, merchant, invasion
    "mob_hunts",
    "wandering_merchant",
    "world_invasion",
    # Phase 170 — story_engine (codex_chronicle n'a pas d'init_db, lit DB
    # de story_engine)
    "story_engine",
    # Phase 170.2-3 : NPCs mood + encounters log
    "npc_personalities",
    "daily_encounters",
    # Phase 170.4 : council sessions + votes
    "weekly_council",
]


@pytest.mark.parametrize("mod_name", INIT_DB_MODULES)
def test_module_has_init_db(mod_name):
    """Chaque module avec table a un `init_db()` async."""
    mod = importlib.import_module(mod_name)
    assert hasattr(mod, "init_db"), f"{mod_name} sans init_db()"
