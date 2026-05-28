"""Phase 164.3 : tests reputation — tier logic + source weights."""
import pytest

import reputation


def test_get_tier_thresholds():
    """Les tiers se déclenchent aux bons seuils."""
    assert reputation.get_tier(0)["name"] == "Nouveau"
    assert reputation.get_tier(99)["name"] == "Nouveau"
    assert reputation.get_tier(100)["name"] == "Apprenti"
    assert reputation.get_tier(499)["name"] == "Apprenti"
    assert reputation.get_tier(500)["name"] == "Vétéran"
    assert reputation.get_tier(1999)["name"] == "Vétéran"
    assert reputation.get_tier(2000)["name"] == "Légende"
    assert reputation.get_tier(4999)["name"] == "Légende"
    assert reputation.get_tier(5000)["name"] == "Mythique"
    assert reputation.get_tier(99999)["name"] == "Mythique"


def test_tiers_have_required_fields():
    """Chaque tier a name, emoji, min, color."""
    for t in reputation.TIERS:
        assert "name" in t
        assert "emoji" in t
        assert "min" in t
        assert "color" in t
        assert isinstance(t["min"], int)


def test_source_points_exhaustive():
    """Les sources critiques ont des poids définis."""
    assert reputation.SOURCE_POINTS.get("boss_kill_final", 0) > 0
    assert reputation.SOURCE_POINTS.get("treasure_claim", 0) > 0
    assert reputation.SOURCE_POINTS.get("quest_complete", 0) > 0
    assert reputation.SOURCE_POINTS.get("duel_win", 0) > 0
    assert reputation.SOURCE_POINTS.get("riddle_first", 0) > 0
    assert reputation.SOURCE_POINTS.get("saga_top_contributor", 0) > 0


def test_tier_progression_monotone():
    """Plus de points → tier supérieur ou égal."""
    last_min = -1
    for t in reputation.TIERS:
        assert t["min"] > last_min, "Les tiers doivent être strictement croissants"
        last_min = t["min"]
