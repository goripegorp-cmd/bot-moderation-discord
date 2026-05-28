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
]


@pytest.mark.parametrize("mod_name", INIT_DB_MODULES)
def test_module_has_init_db(mod_name):
    """Chaque module avec table a un `init_db()` async."""
    mod = importlib.import_module(mod_name)
    assert hasattr(mod, "init_db"), f"{mod_name} sans init_db()"
