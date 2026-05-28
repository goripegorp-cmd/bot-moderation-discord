"""Phase 166 : tests pour anti_token_leak, birthday_panel, welcome_ack,
spotlight_quality."""
import pytest

import anti_token_leak
import birthday_panel
import welcome_ack
import spotlight_quality


# ─── anti_token_leak ──────────────────────────────────────────────────────

def test_token_patterns_detect_mfa():
    """MFA token format détecté."""
    text = "Hey check ça : mfa.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP"
    preview = anti_token_leak._scan_for_tokens(text)
    assert preview is not None
    assert "..." in preview


def test_token_patterns_detect_bot():
    """Bot token format (24.6.27 chars) détecté.

    On utilise des chaînes synthétiques générées à la volée pour éviter
    les heuristiques de secret-scanning de GitHub (qui flag les "vrais"
    formats même s'ils sont fake).
    """
    # 25 + "." + 6 + "." + 30 chars, chaîne synthétique
    fake_token = (
        "A" * 25 + "." + "B" * 6 + "." + "C" * 30
    )
    preview = anti_token_leak._scan_for_tokens(fake_token)
    assert preview is not None


def test_token_patterns_ignore_normal_text():
    """Texte normal pas un faux positif."""
    text = "Salut comment ça va aujourd'hui ?"
    assert anti_token_leak._scan_for_tokens(text) is None


def test_token_patterns_ignore_url():
    """Une URL discord normale ne match pas."""
    text = "Discord URL : https://discord.com/channels/123/456/789"
    assert anti_token_leak._scan_for_tokens(text) is None


def test_anti_token_leak_api():
    assert hasattr(anti_token_leak, "setup")
    assert hasattr(anti_token_leak, "init_db")
    assert hasattr(anti_token_leak, "on_message_hook")


# ─── birthday_panel ───────────────────────────────────────────────────────

def test_birthday_panel_api():
    assert hasattr(birthday_panel, "setup")
    assert hasattr(birthday_panel, "get_upcoming_birthdays")
    assert hasattr(birthday_panel, "build_birthday_panel")


# ─── welcome_ack ──────────────────────────────────────────────────────────

def test_welcome_ack_api():
    assert hasattr(welcome_ack, "setup")
    assert hasattr(welcome_ack, "init_db")
    assert hasattr(welcome_ack, "on_message_hook")


# ─── spotlight_quality ────────────────────────────────────────────────────

def test_spotlight_constants():
    assert spotlight_quality.STAR_EMOJI == "⭐"
    assert spotlight_quality.DEFAULT_STAR_THRESHOLD >= 3


def test_spotlight_api():
    assert hasattr(spotlight_quality, "setup")
    assert hasattr(spotlight_quality, "init_db")
    assert hasattr(spotlight_quality, "on_reaction_hook")
