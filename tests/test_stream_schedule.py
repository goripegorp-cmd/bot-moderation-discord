"""Phase 165.1 : tests stream_schedule — platforms + API exposée."""
import pytest

import stream_schedule


def test_platforms_supported():
    """Les 4 plateformes principales sont supportées."""
    expected = {"twitch", "youtube", "tiktok", "kick"}
    assert set(stream_schedule.PLATFORMS.keys()) == expected
    # Chaque plateforme a (emoji, label)
    for plat, entry in stream_schedule.PLATFORMS.items():
        assert isinstance(entry, tuple) and len(entry) == 2


def test_public_api_exported():
    """L'API publique est en place."""
    assert hasattr(stream_schedule, "schedule_stream")
    assert hasattr(stream_schedule, "cancel_stream")
    assert hasattr(stream_schedule, "get_upcoming")
    assert hasattr(stream_schedule, "get_habits")
    assert hasattr(stream_schedule, "build_schedule_panel")
    assert hasattr(stream_schedule, "countdown_task")


def test_setup_callable():
    """setup() est callable avec 4 args."""
    assert callable(stream_schedule.setup)
