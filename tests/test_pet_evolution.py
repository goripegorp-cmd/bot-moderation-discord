"""Phase 164.3 : tests pet_evolution — skins + level math."""
import pytest

import pet_evolution


def test_evolved_skins_all_legacy_pets():
    """Tous les pets legacy (engagement41.PETS) ont des skins."""
    expected_slugs = {"cat", "dog", "dragon", "wolf", "fox", "robot"}
    assert set(pet_evolution.EVOLVED_SKINS.keys()) == expected_slugs


def test_each_pet_has_4_skins():
    """Chaque pet a 4 skins (level 0, 10, 25, 50)."""
    for slug, skins in pet_evolution.EVOLVED_SKINS.items():
        assert len(skins) == 4, f"{slug} n'a pas 4 skins"
        levels = [s["min_lvl"] for s in skins]
        assert levels == [0, 10, 25, 50], f"{slug} levels = {levels}"


def test_get_evolved_skin_returns_correct_tier():
    """get_evolved_skin renvoie le bon skin selon le level."""
    s0 = pet_evolution.get_evolved_skin("dragon", 0)
    s10 = pet_evolution.get_evolved_skin("dragon", 10)
    s25 = pet_evolution.get_evolved_skin("dragon", 25)
    s50 = pet_evolution.get_evolved_skin("dragon", 50)
    s99 = pet_evolution.get_evolved_skin("dragon", 99)  # max reste lvl 50

    assert s0["name"] == "Dragon"
    assert s10["name"] == "Dragon Ardent"
    assert s25["name"] == "Dragon Tempête"
    assert s50["name"] == "Dragon Légendaire"
    assert s99["name"] == "Dragon Légendaire"  # cap


def test_get_evolved_skin_unknown_pet_safe():
    """Un pet inconnu renvoie un dict (fallback fox) sans crash."""
    result = pet_evolution.get_evolved_skin("alien_unknown", 5)
    assert isinstance(result, dict)
    assert "name" in result and "emoji" in result
