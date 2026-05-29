"""Phase 181 : amélioration +1 → +10 (forge pro)."""
import pytest

import events_engine as ev


def test_enhance_constants():
    assert ev.ENHANCE_MAX == 10
    assert 0 < ev.ENHANCE_STAT_PER_LEVEL < 1


def test_success_pct_decreasing():
    """Le taux de succès décroît avec le niveau."""
    pcts = [ev.enhance_success_pct(l) for l in range(0, 10)]
    assert pcts[0] >= pcts[5] >= pcts[9]
    assert all(0 <= p <= 100 for p in pcts)


def test_cost_scales_with_rarity_and_level():
    cheap = ev.enhance_cost({"rarity": "commune"}, 0)
    pricey = ev.enhance_cost({"rarity": "mythique"}, 0)
    assert pricey > cheap
    # même item, niveau plus haut = plus cher
    assert ev.enhance_cost({"rarity": "rare"}, 5) > ev.enhance_cost({"rarity": "rare"}, 0)


def test_attempt_enhance_success():
    it = {"name": "Épée", "atk": 12, "rarity": "rare", "slot": "weapon"}
    res = ev.attempt_enhance(it, roll=0.0)  # 0 < pct → succès garanti
    assert res["result"] == "success"
    assert res["new_level"] == 1
    assert it["upgrade_level"] == 1


def test_attempt_enhance_empty_and_maxed():
    assert ev.attempt_enhance({}, roll=0.0)["result"] == "empty"
    maxed = {"name": "x", "atk": 10, "rarity": "rare", "upgrade_level": 10}
    assert ev.attempt_enhance(maxed, roll=0.0)["result"] == "maxed"


def test_fail_safe_below_6():
    it = {"name": "x", "atk": 10, "rarity": "rare", "upgrade_level": 3}
    res = ev.attempt_enhance(it, roll=0.999)  # 99.9 > pct(3)=85 → échec
    assert res["result"] == "fail_safe"
    assert it["upgrade_level"] == 3  # inchangé


def test_fail_downgrade_at_6_plus():
    it = {"name": "x", "atk": 10, "rarity": "rare", "upgrade_level": 7}
    res = ev.attempt_enhance(it, roll=0.999)  # échec à +7
    assert res["result"] == "fail_downgrade"
    assert it["upgrade_level"] == 6  # perd 1 niveau


def test_gear_stats_apply_upgrade_multiplier():
    base = ev.gear_total_stats({"atk": 100, "rarity": "épique"})
    up10 = ev.gear_total_stats({"atk": 100, "rarity": "épique", "upgrade_level": 10})
    # +10 → +80 % sur la base
    assert base["atk"] == 100
    assert up10["atk"] == 180
    up5 = ev.gear_total_stats({"atk": 50, "rarity": "épique", "upgrade_level": 5})
    assert up5["atk"] == 70  # 50 * 1.4
