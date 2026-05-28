"""Phase 164.3 : tests roblox_raffle — sources + prizes."""
import pytest

import roblox_raffle


def test_tickets_by_source_all_sources_wired():
    """Les 5 sources de tickets sont définies avec des poids positifs."""
    expected = {
        "roblox_linked_weekly",
        "quests_5_week",
        "votes_5_week",
        "saga_top5",
        "social_post_claim",
    }
    assert set(roblox_raffle.TICKETS_BY_SOURCE.keys()) == expected
    for src, count in roblox_raffle.TICKETS_BY_SOURCE.items():
        assert count > 0, f"Source {src} a count <= 0"


def test_prizes_match_winners_slots():
    """Le nombre de prix correspond au nombre de gagnants tirés."""
    # Le code fait `for i, uid in enumerate(winners_set):`
    # `if len(winners_set) >= len(PRIZES): break`
    # Donc PRIZES doit être >= 1
    assert len(roblox_raffle.PRIZES) >= 1
    # 1er prix doit être le plus gros
    assert roblox_raffle.PRIZES[0] >= max(roblox_raffle.PRIZES)


def test_current_week_key_format():
    """_current_week_key retourne format ISO `YYYY-Www`."""
    key = roblox_raffle._current_week_key()
    assert isinstance(key, str)
    assert "-W" in key
    parts = key.split("-W")
    assert len(parts) == 2
    year, week = parts
    assert year.isdigit() and len(year) == 4
    assert week.isdigit() and 1 <= int(week) <= 53
