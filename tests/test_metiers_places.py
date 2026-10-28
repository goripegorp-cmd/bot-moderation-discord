"""28/10/2026 — le fondateur : « on choisit les places disponibles et la limite des places… ils ne peuvent pas choisir
sur le serveur… ils le décident dans le ticket… ça leur dit les places disponibles lors de la création du ticket. »"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import affiches
import metiers as M
import questionnaire as Q

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


def test_P1_les_reglages_par_defaut_et_lus():
    r = M.reglages_de({})
    assert r["ticket"] is True and r["places"] == {}, "par défaut : le métier se choisit au ticket, sans limite"
    r = M.reglages_de({M.CLE_PLACES: {"cooking": 2, "fishing": -1, "mining": True, "doctor": 9999}, M.CLE_TICKET: False})
    assert r["places"] == {"cooking": 2} and r["ticket"] is False, "les places invalides sont ignorées"


def test_P2_le_metier_retrouve_dans_les_reponses_de_la_fiche():
    cat = [{"cle": "cooking", "nom": "Cuisine", "nom_en": "Cooking"}, {"cle": "fishing", "nom": "Pêche", "nom_en": "Fishing"}]
    assert M.metier_des_reponses(cat, {"Pseudo": "Kolax", "Métier": "Cuisinier"}, {})["cle"] == "cooking"
    assert M.metier_des_reponses(cat, {"Métier": "pêcheur"}, {})["cle"] == "fishing", "sans accents ni majuscules"
    assert M.metier_des_reponses(cat, {"Métier": "Chef coq"}, {"cooking": "Chef coq"})["cle"] == "cooking", "le nom renommé"
    assert M.metier_des_reponses(cat, {"Pseudo": "Kolax"}, {}) is None


def test_P3_les_places_se_valident(monkeypatch):
    async def cat(actifs=True):
        return [{"cle": "cooking"}, {"cle": "fishing"}]
    monkeypatch.setattr(M, "metiers_du_catalogue", cat)
    assert asyncio.run(M._valider_places({"cooking": 3, "fishing": None})) == {"cooking": 3}
    for mauvais in ({"inconnu": 1}, {"cooking": -1}, {"cooking": True}, {"cooking": M.PLACES_MAX + 1}, []):
        with pytest.raises(affiches.Invalide):
            asyncio.run(M._valider_places(mauvais))


def test_P4_la_fiche_accepte_le_champ_metier():
    ch = Q._champ_fiche({"titre": "Métier", "type": "metier"})
    assert ch["type"] == "metier" and ch["options"] == []
    assert "metier" in Q.TYPES_CHAMP


def test_P5_la_fiche_propose_seulement_les_places_libres(monkeypatch):
    async def places(g, c=None):
        return [{"cle": "cooking", "nom": "Cuisinier", "limite": 2, "occupes": 2, "libres": 0, "emoji": ""},
                {"cle": "fishing", "nom": "Pêcheur", "limite": 3, "occupes": 1, "libres": 2, "emoji": ""},
                {"cle": "mining", "nom": "Mineur", "limite": None, "occupes": 4, "libres": None, "emoji": ""}]

    async def cfg(_gid):
        return {}
    monkeypatch.setattr(M, "places", places)
    monkeypatch.setattr(M, "_cfg", cfg)
    monkeypatch.setattr(M, "_get_db", object())
    g = type("G", (), {"id": 1})()
    champs, ligne = asyncio.run(M.champs_avec_places(g, [{"titre": "Pseudo", "type": "court"}, {"titre": "Métier", "type": "metier"}]))
    metier = champs[1]
    assert metier["type"] == "choix" and metier["options"] == ["Pêcheur", "Mineur"], "Cuisinier est plein"
    assert metier["cles"] == ["fishing", "mining"] and len(metier["descriptions"]) == 2
    assert "Pêcheur 2" in ligne and "Mineur" in ligne and "Cuisinier" not in ligne


def test_P6_branche_dans_le_bot_et_le_guide():
    assert "metiers.champs_avec_places(i.guild, await questionnaire.fiche_ouverture(g_, pid, pnl))" in SRC
    src_m = (RACINE / "metiers.py").read_text(encoding="utf-8")
    assert 'is None or reglages_de(c)["ticket"]:' in src_m, "plus de liste du métier dans le guide du clan"
    assert 'if reg["ticket"]:' in src_m, "l'ancienne liste répond : le métier se choisit au ticket"
    src_q = (RACINE / "questionnaire.py").read_text(encoding="utf-8")
    assert 'await _metier(g, candidat, reponses=dict(tk.get("answers") or {}))' in src_q
