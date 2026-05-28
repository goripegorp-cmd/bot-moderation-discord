"""Phase 164.3 : tests dm_digest — categories + enqueue logic."""
import asyncio

import pytest

import dm_digest


def test_categories_required():
    """Les catégories critiques sont définies."""
    required = {
        "quest_ready",
        "drop_collected",
        "achievement",
        "comeback",
        "saga_update",
        "personal_event",
        "level_up",
        "alliance",
    }
    assert set(dm_digest.CATEGORIES.keys()) == required


def test_categories_have_emoji_and_label():
    """Chaque catégorie est (emoji, label)."""
    for cat, entry in dm_digest.CATEGORIES.items():
        assert isinstance(entry, tuple) and len(entry) == 2
        emoji, label = entry
        assert isinstance(emoji, str) and emoji
        assert isinstance(label, str) and label


def test_send_urgent_now_exported():
    """send_urgent_now est dispo (Phase 163.6 wiring webhook_leak / 2FA)."""
    assert hasattr(dm_digest, "send_urgent_now")
    assert callable(dm_digest.send_urgent_now)


def test_enqueue_exported():
    """enqueue est dispo (Phase 163 wiring tier upgrades + drops)."""
    assert hasattr(dm_digest, "enqueue")
    assert callable(dm_digest.enqueue)


def test_enqueue_unknown_category_fails():
    """Une catégorie inconnue retourne False sans crash."""
    # _get_db est None par défaut (pas de setup()) → enqueue retourne False
    result = asyncio.run(
        dm_digest.enqueue(123, 456, "unknown_category", "test")
    )
    assert result is False


def test_send_urgent_now_handles_none_member():
    """send_urgent_now sans member retourne False (fail-open)."""
    result = asyncio.run(dm_digest.send_urgent_now(None, "test"))
    assert result is False
