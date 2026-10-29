"""29/10/2026 — « tiktok @rellbrothers : échec réseau/parse (TimeoutError) » : un échec passager est tracé ; l'alerte part
au 3e échec d'affilée (puis tous les 12) ; le compte repart à zéro dès que le flux répond."""
from __future__ import annotations

import diag
import social_media as S


def test_F1_trois_echecs_d_affilee_avant_l_alerte(monkeypatch):
    lignes = []
    monkeypatch.setattr(diag, "warn", lambda *a, **k: lignes.append(("warn", a[-1])))
    monkeypatch.setattr(diag, "trace", lambda *a, **k: lignes.append(("trace", a[-1])))
    S._ECHECS_FLUX.clear()
    cle = ("tiktok", "rellbrothers", "u")
    for _ in range(S.ECHECS_AVANT_ALERTE + S.ECHECS_RAPPEL):
        S._signaler_flux(cle, True, "tiktok @rellbrothers : échec")
    alertes = [i for i, (k, _m) in enumerate(lignes) if k == "warn"]
    assert alertes == [S.ECHECS_AVANT_ALERTE - 1, S.ECHECS_AVANT_ALERTE + S.ECHECS_RAPPEL - 1]
    assert "3 échecs d'affilée" in lignes[alertes[0]][1]
    S._ECHECS_FLUX.pop(cle)   # le flux a répondu
    lignes.clear()
    S._signaler_flux(cle, True, "échec")
    assert lignes == [("trace", "échec")], "un seul échec après une réussite : tracé"


def test_F2_jamais_averti_quand_l_appelant_demande_le_silence(monkeypatch):
    lignes = []
    monkeypatch.setattr(diag, "warn", lambda *a, **k: lignes.append("warn"))
    monkeypatch.setattr(diag, "trace", lambda *a, **k: lignes.append("trace"))
    S._ECHECS_FLUX.clear()
    for _ in range(20):
        S._signaler_flux(("youtube", "x", "u"), False, "refus")
    assert "warn" not in lignes
