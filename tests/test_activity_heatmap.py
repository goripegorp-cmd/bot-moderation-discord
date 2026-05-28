"""Phase 165.2 : tests activity_heatmap — render + API."""
import pytest

import activity_heatmap


def test_weekdays_fr_complete():
    """7 jours définis."""
    assert len(activity_heatmap.WEEKDAYS_FR) == 7


def test_density_chars_count():
    """Au moins 5 niveaux de densité."""
    assert len(activity_heatmap.DENSITY_CHARS) >= 5


def test_render_matrix_ascii_zero():
    """Matrice vide rend tout en ⬛ (pas de crash)."""
    matrix = [[0] * 24 for _ in range(7)]
    out = activity_heatmap._render_matrix_ascii(matrix)
    assert "```" in out  # code block discord
    assert "Lun" in out


def test_render_matrix_ascii_non_zero():
    """Matrice avec valeurs rend des emojis colorés."""
    matrix = [[0] * 24 for _ in range(7)]
    matrix[0][20] = 100  # Lundi 20h peak
    out = activity_heatmap._render_matrix_ascii(matrix)
    assert "🟥" in out  # peak emoji


def test_public_api_exported():
    assert hasattr(activity_heatmap, "track_message")
    assert hasattr(activity_heatmap, "get_heatmap_matrix")
    assert hasattr(activity_heatmap, "get_best_hours")
    assert hasattr(activity_heatmap, "build_heatmap_panel")
    assert hasattr(activity_heatmap, "weekly_owner_dispatch_task")
