"""Phase 170.1-7 : Chronique + NPCs + Encounters + Conseil + Régions + Mystères + Lettres."""
import pytest

import story_engine
import codex_chronicle
import npc_personalities
import daily_encounters
import weekly_council
import regional_state
import mystery_investigation
import npc_letters


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


# ─── Phase 170.4 : Weekly Council ────────────────────────────────────────

def test_council_catalog_size():
    """Au moins 5 conseils (2 clés + 3 génériques)."""
    assert len(weekly_council.COUNCIL_CATALOG) >= 5


def test_council_required_fields():
    """Chaque conseil a les champs requis."""
    required = {"id", "chapter_id", "title", "context", "question", "options"}
    for c in weekly_council.COUNCIL_CATALOG:
        missing = required - set(c.keys())
        assert not missing, f"Council {c.get('id')} manque : {missing}"


def test_council_ids_unique():
    ids = [c["id"] for c in weekly_council.COUNCIL_CATALOG]
    assert len(ids) == len(set(ids))


def test_council_three_options_each():
    """Chaque conseil a exactement 3 options."""
    for c in weekly_council.COUNCIL_CATALOG:
        assert len(c["options"]) == 3, (
            f"Conseil {c['id']} a {len(c['options'])} options au lieu de 3"
        )


def test_council_options_required_fields():
    """Chaque option a id/label/description/branch_key/npc_impacts."""
    required = {"id", "label", "description", "branch_key", "npc_impacts"}
    for c in weekly_council.COUNCIL_CATALOG:
        for opt in c["options"]:
            missing = required - set(opt.keys())
            assert not missing, (
                f"Option de {c['id']} manque : {missing}"
            )


def test_council_npc_impacts_valid_npcs():
    """Tous les NPCs impactés par les choix existent."""
    valid_ids = set(npc_personalities.list_npc_ids())
    for c in weekly_council.COUNCIL_CATALOG:
        for opt in c["options"]:
            for npc_id in opt.get("npc_impacts", {}):
                assert npc_id in valid_ids, (
                    f"Council {c['id']} option {opt['id']} ref NPC inconnu : {npc_id}"
                )


def test_council_npc_deltas_bounded():
    """Mood deltas dans [-20, +20]."""
    for c in weekly_council.COUNCIL_CATALOG:
        for opt in c["options"]:
            for npc_id, delta in opt.get("npc_impacts", {}).items():
                assert -20 <= int(delta) <= 20, (
                    f"{c['id']} {opt['id']} delta {delta} hors borne"
                )


def test_council_timing_config():
    """Lundi 20h / Mercredi 23h."""
    assert weekly_council.COUNCIL_OPEN_WEEKDAY == 0  # lundi
    assert weekly_council.COUNCIL_OPEN_HOUR == 20
    assert weekly_council.COUNCIL_CLOSE_WEEKDAY == 2  # mercredi
    assert 20 <= weekly_council.COUNCIL_CLOSE_HOUR <= 23


def test_council_key_questions_for_chapters():
    """Les chapitres 1.3 et 2.3 ont un conseil clé."""
    chapter_councils = {
        c["chapter_id"] for c in weekly_council.COUNCIL_CATALOG
        if c["chapter_id"] != "any"
    }
    assert "1.3" in chapter_councils
    assert "2.3" in chapter_councils


def test_council_generic_pool_exists():
    """Il y a au moins 2 conseils génériques pour remplir les semaines sans conseil clé."""
    generics = [
        c for c in weekly_council.COUNCIL_CATALOG if c["chapter_id"] == "any"
    ]
    assert len(generics) >= 2


def test_council_button_is_dynamic():
    """CouncilVoteButton est un DynamicItem."""
    import discord
    assert issubclass(
        weekly_council.CouncilVoteButton, discord.ui.DynamicItem,
    )


def test_council_api():
    """API publique exposée."""
    for name in [
        "setup", "init_db", "COUNCIL_CATALOG",
        "get_council_def", "list_council_ids", "get_councils_for_chapter",
        "get_active_council", "get_vote_counts", "has_user_voted",
        "open_council", "close_council", "record_vote",
        "build_council_panel", "open_council_from_codex",
        "CouncilVoteButton", "council_task", "register_persistent_views",
    ]:
        assert hasattr(weekly_council, name), f"manque : {name}"


# ─── Phase 170.5 : Regional State ────────────────────────────────────────

def test_region_catalog_size():
    """Exactement 5 régions."""
    assert len(regional_state.REGION_CATALOG) == 5


def test_region_required_fields():
    """Chaque région a les champs requis."""
    required = {"id", "name", "subtitle", "emoji", "description",
                "ambiance", "lore_unlock_act", "linked_npc",
                "bonus_when_healthy"}
    for r in regional_state.REGION_CATALOG:
        missing = required - set(r.keys())
        assert not missing, f"Region {r.get('id')} manque : {missing}"


def test_region_ids_unique():
    ids = [r["id"] for r in regional_state.REGION_CATALOG]
    assert len(ids) == len(set(ids))


def test_region_expected_ids():
    """Les 5 régions canoniques."""
    ids = {r["id"] for r in regional_state.REGION_CATALOG}
    expected = {"cendregris", "profondes", "cathedrale", "marais", "sanctuaire"}
    assert ids == expected


def test_region_linked_npcs_valid():
    """Chaque région est liée à un NPC valide."""
    valid_npcs = set(npc_personalities.list_npc_ids())
    for r in regional_state.REGION_CATALOG:
        assert r["linked_npc"] in valid_npcs, (
            f"Region {r['id']} ref NPC inconnu : {r['linked_npc']}"
        )


def test_region_acts_distribution():
    """Régions réparties sur les 3 Actes."""
    acts = {r["lore_unlock_act"] for r in regional_state.REGION_CATALOG}
    # Au moins 2 actes représentés (1 et 2 ou 3)
    assert len(acts) >= 2


def test_region_constants():
    """Constantes saines."""
    assert regional_state.HEALTH_MAX == 100
    assert regional_state.THREAT_MAX == 100
    assert 0 < regional_state.HEALTH_INITIAL <= 100
    assert 0 <= regional_state.THREAT_INITIAL <= 100
    assert regional_state.PATROL_WEEKDAY == 2  # mercredi
    assert 0 <= regional_state.PATROL_HOUR <= 23
    assert regional_state.PATROL_DURATION_HOURS > 0
    assert regional_state.PATROL_TARGET_POINTS > 0
    assert regional_state.PATROL_RECLAIM_TARGET < regional_state.PATROL_TARGET_POINTS
    assert 1 <= regional_state.MAX_POINTS_PER_USER <= 20
    assert regional_state.SERVER_DEBUFF_PER_FALLEN > 0


def test_region_button_is_dynamic():
    """PatrolDefendButton est un DynamicItem."""
    import discord
    assert issubclass(
        regional_state.PatrolDefendButton, discord.ui.DynamicItem,
    )


def test_regional_api():
    """API publique exposée."""
    for name in [
        "setup", "init_db", "REGION_CATALOG",
        "get_region_def", "list_region_ids",
        "ensure_regions_initialized", "get_region_state",
        "get_all_regions_state", "get_server_debuff",
        "apply_passive_threat", "defend_region",
        "start_patrol", "close_patrol", "get_active_patrol",
        "build_regions_panel", "build_patrol_panel",
        "open_regions_from_codex",
        "PatrolDefendButton", "regional_task", "register_persistent_views",
    ]:
        assert hasattr(regional_state, name), f"manque : {name}"


# ─── Phase 170.6 : Mystery Investigation ─────────────────────────────────

def test_mystery_catalog_size():
    """Au moins 4 mystères."""
    assert len(mystery_investigation.MYSTERY_CATALOG) >= 4


def test_mystery_required_fields():
    required = {"id", "title", "act_unlock", "linked_npc", "fragments",
                "revelation", "reward_coins"}
    for m in mystery_investigation.MYSTERY_CATALOG:
        missing = required - set(m.keys())
        assert not missing, f"Mystery {m.get('id')} manque : {missing}"


def test_mystery_ids_unique():
    ids = [m["id"] for m in mystery_investigation.MYSTERY_CATALOG]
    assert len(ids) == len(set(ids))


def test_mystery_fragments_count():
    """Chaque mystère a 3 à 5 fragments."""
    for m in mystery_investigation.MYSTERY_CATALOG:
        n = len(m["fragments"])
        assert 3 <= n <= 5, (
            f"Mystère {m['id']} a {n} fragments (3-5 attendu)"
        )


def test_mystery_fragments_non_empty():
    """Tous les textes de fragments sont substantiels."""
    for m in mystery_investigation.MYSTERY_CATALOG:
        for frag in m["fragments"]:
            assert len(frag) > 20


def test_mystery_revelation_non_empty():
    for m in mystery_investigation.MYSTERY_CATALOG:
        assert len(m["revelation"]) > 50


def test_mystery_linked_npcs_valid():
    """Tous les NPCs liés existent."""
    valid_ids = set(npc_personalities.list_npc_ids())
    for m in mystery_investigation.MYSTERY_CATALOG:
        assert m["linked_npc"] in valid_ids, (
            f"Mystère {m['id']} ref NPC inconnu : {m['linked_npc']}"
        )


def test_mystery_acts_range():
    """act_unlock entre 1 et 3."""
    for m in mystery_investigation.MYSTERY_CATALOG:
        assert 1 <= int(m["act_unlock"]) <= 3


def test_mystery_chances_in_range():
    """Probabilités de drop entre 0 et 1."""
    for chance in [
        mystery_investigation.GRANT_CHANCE_ENCOUNTER,
        mystery_investigation.GRANT_CHANCE_MOB_KILL,
        mystery_investigation.GRANT_CHANCE_COUNCIL,
        mystery_investigation.GRANT_CHANCE_PATROL,
    ]:
        assert 0.0 < chance < 1.0


def test_mystery_reward_positive():
    assert mystery_investigation.REVEAL_COIN_REWARD > 0


def test_mystery_button_is_dynamic():
    import discord
    assert issubclass(
        mystery_investigation.ShareClueButton, discord.ui.DynamicItem,
    )


def test_mystery_api():
    for name in [
        "setup", "init_db", "MYSTERY_CATALOG",
        "get_mystery_def", "list_mystery_ids",
        "try_grant_clue", "get_user_clues", "get_guild_clue_coverage",
        "get_revelations", "try_reveal_mystery", "share_clue_publicly",
        "build_mysteries_panel", "open_mysteries_from_codex",
        "ShareClueButton", "mystery_task", "register_persistent_views",
    ]:
        assert hasattr(mystery_investigation, name), f"manque : {name}"


# ─── Phase 170.7 : NPC Letters ───────────────────────────────────────────

def test_letter_catalog_size():
    """18 lettres (3 par NPC × 6 NPCs)."""
    assert len(npc_letters.LETTER_CATALOG) >= 18


def test_letter_required_fields():
    required = {"id", "npc_id", "mood_min", "mood_max", "subject", "body"}
    for ltr in npc_letters.LETTER_CATALOG:
        missing = required - set(ltr.keys())
        assert not missing, f"Letter {ltr.get('id')} manque : {missing}"


def test_letter_ids_unique():
    ids = [ltr["id"] for ltr in npc_letters.LETTER_CATALOG]
    assert len(ids) == len(set(ids))


def test_letter_npcs_valid():
    """Tous les NPCs des lettres existent."""
    valid_ids = set(npc_personalities.list_npc_ids())
    for ltr in npc_letters.LETTER_CATALOG:
        assert ltr["npc_id"] in valid_ids, (
            f"Letter {ltr['id']} ref NPC inconnu : {ltr['npc_id']}"
        )


def test_letter_each_npc_has_3_tones():
    """Chaque NPC a au moins une lettre low/mid/high mood."""
    for npc_id in npc_personalities.list_npc_ids():
        ltrs = npc_letters.get_letters_for_npc(npc_id)
        # at least 1 for each of the 3 ranges
        has_low = any(l["mood_min"] <= 20 for l in ltrs)
        has_mid = any(l["mood_min"] <= 50 <= l["mood_max"] for l in ltrs)
        has_high = any(l["mood_max"] >= 80 for l in ltrs)
        assert has_low, f"NPC {npc_id} sans lettre low mood"
        assert has_mid, f"NPC {npc_id} sans lettre mid mood"
        assert has_high, f"NPC {npc_id} sans lettre high mood"


def test_letter_mood_ranges_valid():
    """mood_min/max dans [0, 100] et min ≤ max."""
    for ltr in npc_letters.LETTER_CATALOG:
        assert 0 <= ltr["mood_min"] <= 100
        assert 0 <= ltr["mood_max"] <= 100
        assert ltr["mood_min"] <= ltr["mood_max"]


def test_letter_body_substantial():
    """Chaque corps de lettre fait au moins 50 caractères."""
    for ltr in npc_letters.LETTER_CATALOG:
        assert len(ltr["body"]) >= 50, (
            f"Letter {ltr['id']} trop courte : {len(ltr['body'])} chars"
        )


def test_letter_npc_rotation_size():
    """Rotation NPCs = 6 (= nb NPCs)."""
    assert len(npc_letters.NPC_ROTATION) == 6
    assert set(npc_letters.NPC_ROTATION) == set(
        npc_personalities.list_npc_ids()
    )


def test_letter_timing_config():
    """Dimanche 18h FR."""
    assert npc_letters.LETTER_WEEKDAY == 6  # dimanche
    assert 0 <= npc_letters.LETTER_HOUR <= 23
    assert npc_letters.ACTIVE_WINDOW_DAYS > 0


def test_letter_button_is_dynamic():
    import discord
    assert issubclass(
        npc_letters.LetterToggleButton, discord.ui.DynamicItem,
    )


def test_letter_api():
    for name in [
        "setup", "init_db", "LETTER_CATALOG",
        "get_letter_def", "list_letter_ids", "get_letters_for_npc",
        "is_subscribed", "subscribe", "unsubscribe",
        "toggle_subscription", "get_letters_history",
        "generate_and_send_letters_for_guild",
        "build_letters_panel", "open_letters_from_codex",
        "LetterToggleButton", "weekly_letter_task",
        "register_persistent_views",
    ]:
        assert hasattr(npc_letters, name), f"manque : {name}"
