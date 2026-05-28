"""Phase 170.1-3 : tests fondation Chronique + NPCs + Daily Encounters."""
import pytest

import story_engine
import codex_chronicle
import npc_personalities
import daily_encounters


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


# ─── Phase 170.2 : NPCs ──────────────────────────────────────────────────

def test_npc_catalog_size():
    """Exactement 6 NPCs."""
    assert len(npc_personalities.NPC_CATALOG) == 6


def test_npc_required_fields():
    """Chaque NPC a tous les champs requis."""
    required = {"id", "name", "title", "emoji", "trait", "description",
                "location", "voice"}
    for npc in npc_personalities.NPC_CATALOG:
        missing = required - set(npc.keys())
        assert not missing, f"NPC {npc.get('id')} manque : {missing}"


def test_npc_ids_unique():
    ids = [n["id"] for n in npc_personalities.NPC_CATALOG]
    assert len(ids) == len(set(ids))


def test_npc_expected_ids():
    """Les 6 NPCs canoniques de la saga."""
    ids = {n["id"] for n in npc_personalities.NPC_CATALOG}
    assert {"aria", "korr", "lyra", "drazek", "sienna", "voyageur"} == ids


def test_npc_get_def():
    """get_npc_def fonctionne pour chaque NPC + None pour inconnu."""
    for npc_id in npc_personalities.list_npc_ids():
        assert npc_personalities.get_npc_def(npc_id) is not None
    assert npc_personalities.get_npc_def("inconnu") is None


def test_mood_bounds():
    """Constants 0-100 bien définies."""
    assert npc_personalities.MIN_MOOD == 0
    assert npc_personalities.MAX_MOOD == 100
    assert 0 <= npc_personalities.INITIAL_MOOD <= 100


def test_mood_label():
    """Labels couvrent toute l'échelle 0-100."""
    assert npc_personalities.mood_label(0)
    assert npc_personalities.mood_label(50)
    assert npc_personalities.mood_label(100)
    # Les labels diffèrent selon la zone
    assert npc_personalities.mood_label(10) != npc_personalities.mood_label(90)


def test_npc_api():
    """API publique exposée."""
    for name in [
        "setup", "init_db", "NPC_CATALOG",
        "get_npc_def", "list_npc_ids", "mood_label", "mood_icon",
        "get_mood", "change_mood", "get_aggregate_mood",
        "get_user_relationships",
    ]:
        assert hasattr(npc_personalities, name), f"manque : {name}"


# ─── Phase 170.3 : Daily Encounters ──────────────────────────────────────

def test_encounter_catalog_size():
    """30 encounters minimum (5 par NPC × 6 NPCs)."""
    assert len(daily_encounters.ENCOUNTER_CATALOG) >= 30


def test_encounter_required_fields():
    """Chaque encounter a tous les champs requis."""
    required = {"id", "npc_id", "title", "narrative", "choices"}
    for e in daily_encounters.ENCOUNTER_CATALOG:
        missing = required - set(e.keys())
        assert not missing, f"Encounter {e.get('id')} manque : {missing}"


def test_encounter_ids_unique():
    ids = [e["id"] for e in daily_encounters.ENCOUNTER_CATALOG]
    assert len(ids) == len(set(ids))


def test_encounter_three_choices_each():
    """Chaque encounter a exactement 3 choix."""
    for e in daily_encounters.ENCOUNTER_CATALOG:
        assert len(e["choices"]) == 3, (
            f"Encounter {e['id']} a {len(e['choices'])} choix au lieu de 3"
        )


def test_encounter_choices_required_fields():
    """Chaque choix a label/reply/mood_delta/coin_reward."""
    required = {"label", "reply", "mood_delta", "coin_reward"}
    for e in daily_encounters.ENCOUNTER_CATALOG:
        for choice in e["choices"]:
            missing = required - set(choice.keys())
            assert not missing, (
                f"Choix de {e['id']} manque : {missing}"
            )


def test_encounter_npc_references_valid():
    """Tous les npc_id référencés existent dans NPC_CATALOG."""
    valid_npc_ids = set(npc_personalities.list_npc_ids())
    for e in daily_encounters.ENCOUNTER_CATALOG:
        assert e["npc_id"] in valid_npc_ids, (
            f"Encounter {e['id']} référence NPC inconnu : {e['npc_id']}"
        )


def test_encounter_all_npcs_covered():
    """Chaque NPC a au moins 1 encounter (idéalement 5)."""
    npc_counts = {}
    for e in daily_encounters.ENCOUNTER_CATALOG:
        npc_counts[e["npc_id"]] = npc_counts.get(e["npc_id"], 0) + 1
    for npc_id in npc_personalities.list_npc_ids():
        assert npc_counts.get(npc_id, 0) >= 1, (
            f"NPC {npc_id} n'a aucun encounter"
        )


def test_encounter_mood_deltas_bounded():
    """Mood deltas dans la fourchette [-25, +25] (cohérent avec gameplay)."""
    for e in daily_encounters.ENCOUNTER_CATALOG:
        for choice in e["choices"]:
            assert -25 <= int(choice["mood_delta"]) <= 25, (
                f"{e['id']} mood_delta {choice['mood_delta']} hors borne"
            )


def test_encounter_coin_rewards_bounded():
    """Récompenses coins entre 0 et 100."""
    for e in daily_encounters.ENCOUNTER_CATALOG:
        for choice in e["choices"]:
            assert 0 <= int(choice["coin_reward"]) <= 100


def test_encounter_button_is_dynamic():
    """EncounterChoiceButton est un DynamicItem."""
    import discord
    assert issubclass(
        daily_encounters.EncounterChoiceButton, discord.ui.DynamicItem,
    )


def test_encounter_api():
    """API publique exposée."""
    for name in [
        "setup", "init_db", "ENCOUNTER_CATALOG",
        "get_encounter_def", "list_encounter_ids",
        "has_done_today", "pick_encounter_for_user", "record_choice",
        "build_encounter_panel", "open_encounter_from_hub",
        "EncounterChoiceButton", "register_persistent_views",
    ]:
        assert hasattr(daily_encounters, name), f"manque : {name}"
