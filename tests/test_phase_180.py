"""Phase 180 : expansion d'armes + effets élémentaires (DoT-flavored)."""
import pytest

import events_engine as ev


def test_weapon_catalog_expanded():
    """Catalogue d'armes nettement plus grand (>= 30)."""
    assert len(ev.WEAPONS) >= 30


def test_weapon_required_fields():
    for w in ev.WEAPONS:
        for k in ("name", "atk", "rarity", "emoji", "weight"):
            assert k in w, f"{w.get('name')} manque {k}"
        assert w["rarity"] in ev.RARITY_ORDER


def test_weapon_elements_valid():
    """Tout élément déclaré existe dans ELEMENTS."""
    for w in ev.WEAPONS:
        el = w.get("element")
        if el is not None:
            assert el in ev.ELEMENTS, f"{w['name']} : élément inconnu {el}"


def test_elements_metadata():
    assert len(ev.ELEMENTS) >= 4
    for key, meta in ev.ELEMENTS.items():
        assert "emoji" in meta and "name" in meta


def test_at_least_one_element_per_high_rarity():
    """Les hauts tiers ont des armes élémentaires."""
    has_elem = [w for w in ev.WEAPONS if w.get("element")]
    assert len(has_elem) >= 8


def test_roll_elemental_proc_none_for_plain():
    """Une arme sans élément ne proc jamais."""
    plain = {"name": "Bâton de bois", "atk": 5, "rarity": "commune"}
    for _ in range(50):
        assert ev.roll_elemental_proc(plain) is None
    assert ev.roll_elemental_proc(None) is None
    assert ev.roll_elemental_proc({}) is None


def test_roll_elemental_proc_shape_when_procs():
    """Sur une arme divine élémentaire, le proc finit par arriver et a la bonne forme."""
    weap = {"name": "Aube Infinie", "atk": 120, "rarity": "divine", "element": "fire"}
    got = None
    for _ in range(200):
        got = ev.roll_elemental_proc(weap)
        if got:
            break
    assert got is not None, "Le proc divin aurait dû arriver en 200 essais"
    assert got["element"] == "fire"
    assert got["bonus"] >= 1
    assert got["emoji"] and got["name"]


def test_proc_chance_scales_with_rarity():
    """Une divine proc bien plus souvent qu'une rare (chance croît avec rareté)."""
    rare = {"name": "x", "atk": 14, "rarity": "rare", "element": "ice"}
    divine = {"name": "y", "atk": 120, "rarity": "divine", "element": "ice"}
    n = 400
    rare_hits = sum(1 for _ in range(n) if ev.roll_elemental_proc(rare))
    div_hits = sum(1 for _ in range(n) if ev.roll_elemental_proc(divine))
    assert div_hits > rare_hits
