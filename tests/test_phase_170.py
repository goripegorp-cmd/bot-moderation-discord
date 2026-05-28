"""Phase 170.1 : tests fondation Chronique d'Abylumis."""
import pytest

import story_engine
import codex_chronicle


# ─── story_engine ────────────────────────────────────────────────────────

def test_acts_count():
    """3 Actes exactement."""
    assert len(story_engine.ACTS) == 3


def test_chapters_per_act():
    """Chaque Acte a 3 chapitres."""
    for act in story_engine.ACTS:
        assert len(act["chapters"]) == 3


def test_total_chapters():
    """9 chapitres au total."""
    assert story_engine.total_chapters_count() == 9


def test_acts_required_fields():
    """Chaque Acte a id/title/subtitle/chapters."""
    required = {"id", "title", "subtitle", "chapters"}
    for act in story_engine.ACTS:
        missing = required - set(act.keys())
        assert not missing, f"Acte {act.get('id')} manque : {missing}"


def test_chapters_required_fields():
    """Chaque chapitre a id/title/prologue/epilogue/kind/target/reward_coins."""
    required = {"id", "title", "prologue", "epilogue", "kind", "target",
                "reward_coins"}
    for act in story_engine.ACTS:
        for chap in act["chapters"]:
            missing = required - set(chap.keys())
            assert not missing, (
                f"Chap {chap.get('id')} manque : {missing}"
            )


def test_chapter_ids_unique():
    """Pas de doublon d'id chapitre dans tout le catalogue."""
    ids = []
    for act in story_engine.ACTS:
        for chap in act["chapters"]:
            ids.append(chap["id"])
    assert len(ids) == len(set(ids))


def test_chapter_kinds_valid():
    """Chaque kind de chapitre est dans VALID_KINDS."""
    for act in story_engine.ACTS:
        for chap in act["chapters"]:
            assert chap["kind"] in story_engine.VALID_KINDS, (
                f"Chap {chap['id']} kind {chap['kind']} invalide"
            )


def test_chapter_targets_reasonable():
    """Targets entre 5 et 500000.

    Borne basse à 5 car certains kinds (council_votes, mystery_combines)
    sont des actions PAR SEMAINE — pas des compteurs unitaires comme
    mob_kills. 8 council_votes = 2 mois de conseils hebdo.
    """
    for act in story_engine.ACTS:
        for chap in act["chapters"]:
            assert 5 <= chap["target"] <= 500000


def test_get_chapter_def():
    """get_chapter_def retrouve un chapitre par (act, idx)."""
    chap = story_engine.get_chapter_def(1, 0)
    assert chap is not None
    assert chap["id"] == "1.1"
    assert story_engine.get_chapter_def(99, 99) is None


def test_get_act_def():
    """get_act_def retrouve un Acte par id."""
    act = story_engine.get_act_def(1)
    assert act is not None
    assert act["title"] == "L'Éveil des Cendres"
    assert story_engine.get_act_def(99) is None


def test_alliance_bonus_config():
    """Bonus alliance configuré dans les bornes raisonnables."""
    assert 1.0 < story_engine.ALLIANCE_BONUS_MULT < 2.0
    assert story_engine.ALLIANCE_BONUS_MIN_MEMBERS >= 2


def test_chapter_timeout():
    """Timeout chapitre raisonnable (entre 14 et 120 jours)."""
    assert 14 <= story_engine.CHAPTER_TIMEOUT_DAYS <= 120


def test_story_engine_api():
    """API publique exposée."""
    for name in [
        "setup", "init_db", "get_state", "record_progress",
        "log_chronicle_event", "get_recent_events", "get_top_contributors",
        "chronicle_task",
        "on_mob_kill", "on_quest_complete", "on_boss_damage",
        "on_encounter_completed", "on_council_vote",
        "on_regional_defense", "on_mystery_combine",
    ]:
        assert hasattr(story_engine, name), f"manque : {name}"


# ─── codex_chronicle ─────────────────────────────────────────────────────

def test_codex_pages():
    """4 pages valides définies."""
    assert len(codex_chronicle.VALID_PAGES) == 4
    assert "current" in codex_chronicle.VALID_PAGES
    assert "history" in codex_chronicle.VALID_PAGES
    assert "memoirs" in codex_chronicle.VALID_PAGES
    assert "acts" in codex_chronicle.VALID_PAGES


def test_codex_api():
    """API publique exposée."""
    for name in [
        "setup", "build_codex_panel", "open_codex_from_hub",
        "CodexPageButton", "register_persistent_views",
    ]:
        assert hasattr(codex_chronicle, name), f"manque : {name}"


def test_codex_button_is_dynamic():
    """CodexPageButton est un DynamicItem."""
    import discord
    assert issubclass(codex_chronicle.CodexPageButton, discord.ui.DynamicItem)


# ─── Cohérence catalogue narratif ────────────────────────────────────────

def test_act_titles_consistent():
    """Les 3 titres d'Acte connus."""
    titles = [a["title"] for a in story_engine.ACTS]
    assert "L'Éveil des Cendres" in titles
    assert "Le Schisme" in titles
    assert "L'Affrontement Final" in titles


def test_prologue_epilogue_non_empty():
    """Tous les textes narratifs sont non-vides."""
    for act in story_engine.ACTS:
        for chap in act["chapters"]:
            assert len(chap["prologue"]) > 20
            assert len(chap["epilogue"]) > 20
