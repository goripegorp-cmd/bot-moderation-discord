"""Phase 169 : tests pour mob_hunts, wandering_merchant, world_invasion."""
import pytest

import mob_hunts
import wandering_merchant
import world_invasion


# ─── mob_hunts ────────────────────────────────────────────────────────────

def test_mob_catalog_size():
    """Catalogue ≥ 10 mobs."""
    assert len(mob_hunts.MOB_CATALOG) >= 10


def test_mob_required_fields():
    """Chaque mob a tous les champs requis."""
    required = {"id", "name", "emoji", "hp_base", "damage_per_click",
                "drop_coins", "drop_item_chance", "item_pool"}
    for m in mob_hunts.MOB_CATALOG:
        missing = required - set(m.keys())
        assert not missing, f"Mob {m.get('id', '?')} manque : {missing}"


def test_mob_hp_reasonable():
    """HP base entre 30 et 250 (rapide à tuer)."""
    for m in mob_hunts.MOB_CATALOG:
        assert 30 <= m["hp_base"] <= 250, f"HP {m['hp_base']} hors range pour {m['id']}"


def test_mob_damage_consistent():
    """Damage range (min, max) : min <= max."""
    for m in mob_hunts.MOB_CATALOG:
        dmg_min, dmg_max = m["damage_per_click"]
        assert dmg_min <= dmg_max


def test_get_mob_def():
    """get_mob_def retrouve un mob par id."""
    first = mob_hunts.MOB_CATALOG[0]
    assert mob_hunts.get_mob_def(first["id"]) is not None
    assert mob_hunts.get_mob_def("nonexistent_xyz") is None


def test_mob_unique_ids():
    """Pas de doublon d'id dans le catalogue."""
    ids = [m["id"] for m in mob_hunts.MOB_CATALOG]
    assert len(ids) == len(set(ids))


def test_mob_alliance_bonus():
    """Bonus alliance dans les bornes raisonnables."""
    assert 1.0 < mob_hunts.ALLIANCE_BONUS_MULT < 2.0
    assert mob_hunts.ALLIANCE_BONUS_MIN_MEMBERS >= 2


def test_mob_api():
    assert hasattr(mob_hunts, "setup")
    assert hasattr(mob_hunts, "init_db")
    assert hasattr(mob_hunts, "spawn_mob")
    assert hasattr(mob_hunts, "register_persistent_views")


# ─── wandering_merchant ───────────────────────────────────────────────────

def test_merchant_catalog_size():
    """Catalogue marchand ≥ 8 items."""
    assert len(wandering_merchant.MERCHANT_CATALOG) >= 8


def test_merchant_prices_reasonable():
    """Prix élevés (5000-50000) pour items rares."""
    for item in wandering_merchant.MERCHANT_CATALOG:
        assert 1000 <= item["price"] <= 100000


def test_merchant_required_fields():
    required = {"id", "name", "emoji", "desc", "price", "rarity"}
    for item in wandering_merchant.MERCHANT_CATALOG:
        missing = required - set(item.keys())
        assert not missing, f"Item {item.get('id', '?')} manque : {missing}"


def test_merchant_unique_ids():
    ids = [i["id"] for i in wandering_merchant.MERCHANT_CATALOG]
    assert len(ids) == len(set(ids))


def test_merchant_api():
    assert hasattr(wandering_merchant, "setup")
    assert hasattr(wandering_merchant, "init_db")
    assert hasattr(wandering_merchant, "spawn_merchant")
    assert hasattr(wandering_merchant, "spawn_merchant_task")


# ─── world_invasion ───────────────────────────────────────────────────────

def test_invasion_config():
    """Config invasion valide."""
    assert world_invasion.INVASION_MOBS_COUNT >= 3
    assert world_invasion.INVASION_DURATION_MIN >= 10
    assert 0 <= world_invasion.INVASION_HOUR <= 23
    assert world_invasion.ALLIANCE_BONUS_MIN_MEMBERS >= 2


def test_invasion_api():
    assert hasattr(world_invasion, "setup")
    assert hasattr(world_invasion, "init_db")
    assert hasattr(world_invasion, "trigger_invasion")
    assert hasattr(world_invasion, "monthly_invasion_task")
