"""Phase 173.2 : tests pour daily_bosses (2 créneaux/jour MIDI+SOIR, gating niveau)."""
import pytest

import daily_bosses


def test_boss_catalog_size():
    """Au moins 6 boss (difficulté croissante)."""
    assert len(daily_bosses.DAILY_BOSS_CATALOG) >= 6


def test_boss_required_fields():
    required = {"id", "name", "emoji", "tier", "description",
                "min_level", "hp_base", "lifetime_min", "color"}
    for b in daily_bosses.DAILY_BOSS_CATALOG:
        missing = required - set(b.keys())
        assert not missing, f"Boss {b.get('id')} manque : {missing}"


def test_boss_ids_unique():
    ids = [b["id"] for b in daily_bosses.DAILY_BOSS_CATALOG]
    assert len(ids) == len(set(ids))


def test_boss_difficulty_progression():
    """min_level et hp_base croissent (difficulté alternée/croissante)."""
    levels = [b["min_level"] for b in daily_bosses.DAILY_BOSS_CATALOG]
    hps = [b["hp_base"] for b in daily_bosses.DAILY_BOSS_CATALOG]
    # Le premier est accessible à tous (niveau 0)
    assert levels[0] == 0
    # Globalement croissant
    assert levels == sorted(levels)
    assert hps == sorted(hps)


def test_boss_hp_forces_collaboration():
    """HP élevé : impossible en solo (cap 30 attaques × 220 dmg = 6600 max).
    Les boss de tier moyen+ doivent dépasser ce plafond solo."""
    solo_max = daily_bosses.MAX_ATTACKS_PER_USER * daily_bosses.ATTACK_DAMAGE_MAX
    # Au moins la moitié des boss exigent > 1 joueur
    need_team = [b for b in daily_bosses.DAILY_BOSS_CATALOG
                 if b["hp_base"] > solo_max]
    assert len(need_team) >= 3


def test_boss_slots():
    """owner 2026-06-30 (ANTI-LASSITUDE) : 2 rendez-vous lisibles — MIDI + SOIR.
    Les anciens créneaux matin (9h) et nuit (1h) ont été SUPPRIMÉS à dessein
    (ils banalisaient le combat et spawnaient « dans le vide »). MAJ du test
    Phase 193 (qui exigeait ≥4 créneaux + matin + nuit) → design 5→2."""
    assert len(daily_bosses.BOSS_HOURS) >= 2
    for h in daily_bosses.BOSS_HOURS:
        assert 0 <= h <= 23
    # Un créneau de journée (midi, accessible à tous)
    assert any(11 <= h <= 14 for h in daily_bosses.BOSS_HOURS)
    # Un temps fort en soirée (« le Boss du Soir »)
    assert any(18 <= h <= 23 for h in daily_bosses.BOSS_HOURS)


def test_boss_lifetime_reasonable():
    """Temps imparti entre 30 et 120 min."""
    for b in daily_bosses.DAILY_BOSS_CATALOG:
        assert 30 <= b["lifetime_min"] <= 120


def test_boss_reward_constants():
    assert daily_bosses.COIN_PER_DAMAGE > 0
    assert daily_bosses.TOP3_BONUS_COINS > 0
    assert daily_bosses.PARTICIPATION_BONUS_COINS > 0
    assert daily_bosses.MAX_ATTACKS_PER_USER >= 10
    assert daily_bosses.ATTACK_DAMAGE_MIN <= daily_bosses.ATTACK_DAMAGE_MAX


def test_boss_get_def():
    first = daily_bosses.DAILY_BOSS_CATALOG[0]
    assert daily_bosses.get_boss_def(first["id"]) is not None
    assert daily_bosses.get_boss_def("inconnu_xyz") is None


def test_boss_button_is_dynamic():
    import discord
    assert issubclass(
        daily_bosses.DailyBossAttackButton, discord.ui.DynamicItem,
    )


def test_boss_api():
    for name in [
        "setup", "init_db", "DAILY_BOSS_CATALOG",
        "get_boss_def", "list_boss_ids", "get_user_level",
        "get_active_boss", "trigger_daily_boss", "record_boss_attack",
        "resolve_daily_boss", "DailyBossAttackButton",
        "daily_boss_task", "register_persistent_views",
    ]:
        assert hasattr(daily_bosses, name), f"manque : {name}"
