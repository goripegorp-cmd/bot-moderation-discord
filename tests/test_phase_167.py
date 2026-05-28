"""Phase 167 : tests pour status_rotator, voice_autoclean, member_risk."""
import pytest

import status_rotator
import voice_autoclean
import member_risk


# ─── status_rotator ───────────────────────────────────────────────────────

def test_status_templates_non_empty():
    """Au moins 5 templates statiques + 3 dynamiques."""
    assert len(status_rotator.STATUS_TEMPLATES_STATIC) >= 5
    assert len(status_rotator.STATUS_TEMPLATES_DYNAMIC) >= 3


def test_status_build_text_with_data():
    """_build_status_text avec data dispo formate correctement."""
    text = status_rotator._build_status_text({"member_count": 73})
    assert isinstance(text, str)
    assert len(text) <= 128  # Discord limit


def test_status_build_text_no_data_fallback():
    """Sans data, fallback statique."""
    text = status_rotator._build_status_text({})
    assert isinstance(text, str)
    assert text in status_rotator.STATUS_TEMPLATES_STATIC


def test_status_api():
    assert hasattr(status_rotator, "setup")
    assert hasattr(status_rotator, "rotator_task")


# ─── voice_autoclean ──────────────────────────────────────────────────────

def test_voice_patterns_match():
    """Les patterns temp matchent les noms attendus."""
    assert voice_autoclean._is_temp_voice_name("🔴-watching-john") is True
    assert voice_autoclean._is_temp_voice_name("temp-game") is True
    assert voice_autoclean._is_temp_voice_name("Temp-Test") is True
    assert voice_autoclean._is_temp_voice_name("🎤-karaoke") is True
    assert voice_autoclean._is_temp_voice_name("stage-discussion") is True
    assert voice_autoclean._is_temp_voice_name("game-night-1") is True


def test_voice_patterns_no_false_positive():
    """Noms normaux NE matchent PAS (sécurité)."""
    assert voice_autoclean._is_temp_voice_name("Général") is False
    assert voice_autoclean._is_temp_voice_name("vocal-1") is False
    assert voice_autoclean._is_temp_voice_name("AFK") is False
    assert voice_autoclean._is_temp_voice_name("") is False


def test_voice_autoclean_api():
    assert hasattr(voice_autoclean, "setup")
    assert hasattr(voice_autoclean, "init_db")
    assert hasattr(voice_autoclean, "check_task")
    assert voice_autoclean.EMPTY_DELETE_AFTER_MIN >= 1


# ─── member_risk ──────────────────────────────────────────────────────────

def test_risk_threshold_reasonable():
    """Threshold entre 30 et 80 (raisonnable)."""
    assert 30 <= member_risk.RISK_THRESHOLD <= 80


def test_member_risk_api():
    assert hasattr(member_risk, "setup")
    assert hasattr(member_risk, "init_db")
    assert hasattr(member_risk, "on_member_join")
    assert hasattr(member_risk, "get_risky_members_this_week")
    assert hasattr(member_risk, "build_risk_panel")


def test_digits_regex():
    """Le regex digits attrape bien 5+ chiffres consécutifs."""
    assert member_risk.DIGITS_RE.search("user12345") is not None
    assert member_risk.DIGITS_RE.search("a99999bot") is not None
    assert member_risk.DIGITS_RE.search("user1234") is None  # < 5
    assert member_risk.DIGITS_RE.search("normal_user") is None
