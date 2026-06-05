"""Phase 164.3 : tests community_goals — templates + kinds."""
import pytest

import community_goals


def test_goal_templates_cover_all_event_kinds():
    """Les templates couvrent tous les types d'event hookés."""
    expected_kinds = {
        "boss_kill",
        "treasure_open",
        "duel",
        "quest_complete",
        "wheel_spin",
        "riddle_solve",
        "mystery_open",
        "messages",       # Phase 254-extra : objectif collectif de messages
        "voice_minutes",
    }
    actual_kinds = {t["kind"] for t in community_goals.GOAL_TEMPLATES}
    assert actual_kinds == expected_kinds


def test_goal_templates_have_required_fields():
    """Chaque template a kind, target, emoji + label/desc."""
    for t in community_goals.GOAL_TEMPLATES:
        assert "kind" in t
        assert "target" in t
        assert "emoji" in t
        assert t["target"] > 0, f"Target invalide pour {t['kind']}"


def test_record_action_exported():
    """record_action est la fonction publique appelée par bot.py."""
    assert hasattr(community_goals, "record_action")
    assert callable(community_goals.record_action)
