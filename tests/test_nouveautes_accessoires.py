"""Les nouveautés : des ACCESSOIRES, hors vente compris (06/10/2026).

« Uniquement les accessoires, pas les visages moches ou les camouflages là,
que donne Roblox […] Là, ils ont créé une citrouille récemment. La citrouille,
elle n'est pas affichée dans le serveur. »

Mesuré le 05/10 : la « Duck-o-Lantern » (récompense des quêtes d'Halloween,
hors vente, créée à 21:23 UTC) était en tête du relevé hors vente du bot —
VUE, puis écartée par l'ancienne règle « hors vente et pas Limited : jamais ».
Sur 30 jours, les 126 créations de Roblox sont toutes hors vente. Ces tests
n'appellent jamais le réseau.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import roblox_panneau as rp
import roblox_veille as veille

SRC_BOT = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _il_y_a(heures):
    return (datetime.now(timezone.utc) - timedelta(hours=heures)).isoformat()


def _art(aid, heures, asset_type=8, item_type="Asset", **kw):
    a = {"asset_id": aid, "nom": f"art{aid}", "asset_type": asset_type,
         "item_type": item_type, "cree_le": _il_y_a(heures), "hors_vente": 1,
         "collectionnable": 0, "prix": 1, "createur_id": 1}
    a.update(kw)
    return a


@pytest.mark.parametrize("asset_type,item_type,attendu", [
    (8, "Asset", True), (41, "Asset", True), (42, "Asset", True),
    (43, "Asset", True), (44, "Asset", True), (45, "Asset", True),
    (46, "Asset", True), (47, "Asset", True),
    (76, "Asset", False), (77, "Asset", False), (18, "Asset", False),
    (17, "Asset", False), (79, "Asset", False), (67, "Asset", False),
    (19, "Asset", False), (None, "Asset", False), ("x", "Asset", False),
    (8, "Bundle", False),
])
def test_A1_ce_qui_est_un_accessoire(asset_type, item_type, attendu):
    assert veille.est_accessoire({"asset_type": asset_type,
                                  "item_type": item_type}) is attendu


def test_A2_le_reexamen_garde_les_accessoires_recents_seulement():
    lus = [_art(1, 0.5), _art(2, 5.9), _art(3, 7), _art(4, 2, asset_type=76),
           _art(5, 1, item_type="Bundle", asset_type=None), _art(1, 0.5),
           _art(6, 20)]
    assert [a["asset_id"] for a in veille.a_reexaminer(lus, 6)] == [1, 2]
    assert [a["asset_id"] for a in veille.a_reexaminer(lus, 24)] == [1, 2, 3, 6]
    assert veille.a_reexaminer([{"asset_id": 9, "asset_type": 8}], 6) == [], \
        "sans date, rien n'est rattrapé"


def _corps(nom):
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


def test_A3_le_releve_reexamine_et_rattrape_une_seule_fois():
    corps = _corps("veille_roblox_task")
    #  Ce que le relevé VIENT de lire, les deux listes.
    assert "roblox_module.a_reexaminer(_lus_tous, roblox_module.FENETRE_DIRECTE_HEURES)" in corps
    assert ("roblox_module.a_reexaminer(_lus_tous, "
            "roblox_module.RATTRAPAGE_UNIQUE_HEURES)") in corps
    #  La fenêtre n'est franchie QUE par le rattrapage unique.
    assert ("if not (_unique and a.get('asset_id') in _rattrapes "
            "or roblox_module.age_publiable(a, flux)):") in corps
    #  Le rattrapage unique se marque, une fois par serveur, après le passage.
    i_boucle = corps.index("for g in guildes_items:\n                    _unique")
    i_marque = corps.index("await db_set(g.id, roblox_module.MARQUE_RATTRAPAGE_ACCESSOIRES")
    assert i_boucle < i_marque
    #  Et seulement les nouveautés (jamais les passages Limited).
    assert "if flux == 'nouveautes':\n                            _deja_la" in corps


def test_A4_le_journal_dit_ce_qui_est_ecarte_et_pourquoi():
    assert "écarté(s) : pas un accessoire" in SRC_BOT
    assert "doublon(s) de nom" in SRC_BOT and "rattrapé(s)" in SRC_BOT
    corps = _corps("veille_roblox_task")
    assert "_sa['ecartes_type'] = _sa.get('ecartes_type', 0) + 1" in corps
    assert "_sa['doublons_nom'] = _sa.get('doublons_nom', 0) + 1" in corps


def test_A5_la_cle_du_rattrapage_existe_dans_la_configuration():
    """`config()` ne rend QUE les clés connues : sans elle, le rattrapage
    « unique » recommencerait à chaque passage."""
    assert veille.MARQUE_RATTRAPAGE_ACCESSOIRES in veille.CLES_DEFAUT


# ─── La fiche ───────────────────────────────────────────────────────────────

@pytest.fixture
def panneau():
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


def _texte(vue):
    return str(vue.to_components())


def test_F1_la_citrouille_sans_faux_prix_et_a_gagner_en_jeu(panneau):
    citrouille = _art(126884250250747, 1, nom="Duck-o-Lantern",
                      type_article="Head Accessories",
                      description="A duck in a jack-o'-lantern costume. Earn it "
                                  "through the Halloween quests in Duck Duck and "
                                  "Family Zone before Nov 8.")
    t = _texte(rp.construire_fiche(citrouille, "nouveautes"))
    assert "**Prix d'origine** · —" in t, "« 1 R$ » n'est pas un prix"
    assert "**Disponibilité** · hors vente · à gagner en jeu" in t
    assert "Duck-o-Lantern" in t


def test_F2_un_vrai_prix_reste_affiche(panneau):
    retire = _art(7, 1, nom="Telamon", prix=1000, description="Craft it.")
    t = _texte(rp.construire_fiche(retire, "nouveautes"))
    assert "**Prix d'origine** · 1 000 R$" in t
    assert "**Disponibilité** · hors vente" in t and "à gagner" not in t
    en_vente = _art(8, 1, hors_vente=0, prix=150)
    assert "🟢 en vente" in _texte(rp.construire_fiche(en_vente, "nouveautes"))
