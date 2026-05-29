"""Phase 176 : noms de boss épiques + thématiques par saison."""
import pytest

import events_engine as ev


def test_proper_names_and_epithets_nonempty():
    assert len(ev.BOSS_PROPER_NAMES) >= 10
    assert len(ev.BOSS_EPITHETS_BASE) >= 5
    assert len(ev.BOSS_EPITHETS_SEASONAL) >= 4


def test_generate_boss_title_format():
    """Un titre = prénom + épithète (au moins 2 mots, non vide)."""
    for _ in range(50):
        title = ev.generate_boss_title()
        assert isinstance(title, str) and title.strip()
        assert " " in title  # prénom + épithète


def test_generate_boss_title_seasonal_keys():
    """Chaque clé de saison connue produit un titre valide."""
    for key in ev.BOSS_EPITHETS_SEASONAL:
        title = ev.generate_boss_title(key)
        assert isinstance(title, str) and title.strip()


def test_generate_boss_title_unknown_season_fallback():
    """Une saison inconnue ne crashe pas (épithète générique)."""
    title = ev.generate_boss_title("saison_inexistante")
    assert isinstance(title, str) and title.strip()


def test_random_boss_has_epic_name_and_archetype():
    boss = ev.random_boss(100, season_key="halloween")
    # Nom épique = emoji + titre
    assert boss["name"]
    assert "title" in boss and boss["title"]
    # L'archétype d'origine est conservé pour le lore
    assert "archetype" in boss and boss["archetype"]
    # Le titre épique est différent du simple type d'origine
    assert boss["title"] != boss["archetype"]
    # HP cohérents
    assert boss["max_hp"] >= 100
    assert boss["current_hp"] == boss["max_hp"]


def test_random_boss_no_season_still_works():
    boss = ev.random_boss(100)
    assert boss["name"] and boss["title"] and boss["archetype"]


def test_random_boss_names_vary():
    """Sur plusieurs tirages, on obtient des noms différents (uniques/variés)."""
    names = {ev.random_boss(100, season_key="summer")["name"] for _ in range(30)}
    assert len(names) >= 5  # bonne variété
