"""Phase 167 — member_risk.

Les tests de status_rotator et voice_autoclean ont été retirés avec leurs modules
(purge du périmètre, 08/2026). member_risk reste : il évalue le risque d'un
arrivant, c'est de la sécurité.
"""
import pytest

import member_risk


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
