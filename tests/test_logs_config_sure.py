"""20/10/2026 (audit 3 #22) : la configuration des logs etait relue jusqu'a 4 fois par evenement et
ecrite sans precaution : un fichier abime etait lu « vide » (mode site perdu) puis ecrase."""
from __future__ import annotations

import asyncio

import pytest

import stockage
import unified_logger as U


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "DATA_DIR", tmp_path)
    U._CFG.clear()
    yield tmp_path
    U._CFG.clear()


def test_C1_relue_seulement_si_elle_change(dossier, monkeypatch):
    asyncio.run(U.activer_site(1, 55))
    lectures = []
    vrai = stockage.lire_json_sur
    monkeypatch.setattr(stockage, "lire_json_sur", lambda p: lectures.append(p) or vrai(p))
    for _ in range(4):
        assert asyncio.run(U.mode_site(1)) is True
    assert len(lectures) == 1, "une lecture, puis la copie en memoire"
    copie = U._lire(1)
    copie["site"] = False
    assert asyncio.run(U.mode_site(1)) is True, "une copie : la modifier ne touche pas la configuration"


def test_C2_un_fichier_abime_ne_fait_plus_perdre_le_mode_site(dossier):
    asyncio.run(U.activer_site(1, 55))
    asyncio.run(U.set_log_channel(1, 0))  # 2e ecriture : la 1re part en .bak
    (dossier / "1.json").write_text("{tronqué", encoding="utf-8")
    U._CFG.clear()
    assert asyncio.run(U.mode_site(1)) is True and asyncio.run(U.salon_alertes(1)) == 55


def test_C3_un_reglage_n_ecrase_jamais_une_configuration_illisible(dossier):
    asyncio.run(U.activer_site(1, 55))
    (dossier / "1.json").write_text("{tronqué", encoding="utf-8")
    U._CFG.clear()
    with pytest.raises(stockage.Illisible):
        asyncio.run(U.set_enabled_categories(1, {"Moderation"}))
    assert (dossier / "1.json").read_text(encoding="utf-8") == "{tronqué", "rien n'a ete ecrase"
