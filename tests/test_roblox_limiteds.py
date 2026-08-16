"""Les passages en Limited — le flux que le bot ne pouvait PAS voir.

LE SYMPTÔME, RAPPORTÉ LE 16/08
    « Récemment il y a eu des items qui deviennent limited mais qui sont pas
    affichés. Même s'ils sont passés, j'aimerais que tu les affiches car ils
    sont encore d'actualité. »

LA CAUSE — DEUX DÉFAUTS QUI SE CUMULAIENT
1. `relever_nouveautes` trie par date de CRÉATION (`SortType=3`) : elle rend
   les N derniers articles créés par Roblox. Or `comparer_et_enregistrer` ne
   détecte une bascule que pour un article PRÉSENT dans le relevé. Un
   accessoire créé il y a six mois qui passe Limited aujourd'hui n'y est pas —
   sa bascule n'était donc jamais vue.
2. Même une fois détecté, `age_publiable` le bloquait : la borne haute de
   90 jours mesure l'âge de la CRÉATION, alors qu'une bascule est un événement
   d'aujourd'hui.

MESURÉ EN DIRECT CONTRE L'API (16/08, `outils/sonde_limiteds.py`) :
  · 30 articles les plus récemment créés  → **0** collectionnable ;
  · 30 articles avec `SalesTypeFilter=2`  → **30** collectionnables,
    dont 30 invisibles pour l'ancien relevé ;
  · leur âge : 152 à 341 jours — soit **0 sur 8 publiable** avant le correctif.

Ces tests n'appellent PAS le réseau : la CI doit rester hermétique et rapide.
Ils vérifient les paramètres envoyés, la règle d'âge, et le câblage.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PAN = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le relevé interroge le BON endroit
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def params_captures(monkeypatch):
    """Capture les paramètres, sans toucher au réseau."""
    vus = {}

    async def _faux(params, source, arret_hors_fenetre=False):
        vus["params"] = dict(params)
        vus["source"] = source
        vus["arret_hors_fenetre"] = arret_hors_fenetre
        return {"articles": [], "code": 200, "echecs": 0}

    monkeypatch.setattr(veille, "_relever_catalogue", _faux)
    return vus


@pytest.mark.asyncio
async def test_le_releve_des_collectionnables_filtre_sur_les_limiteds(params_captures):
    await veille.relever_collectionnables(limite=30)
    p = params_captures["params"]

    assert p.get("SalesTypeFilter") == 2, (
        "SalesTypeFilter=2 est le SEUL paramètre qui rend les Limiteds. "
        "Mesuré : sans lui, 0 sur 10 ; avec lui, 10 sur 10.")
    assert p.get("CreatorTargetId") == veille.CREATEUR_ROBLOX, (
        "sans le filtre de créateur, le flux se remplit d'UGC tiers — hors du "
        "périmètre demandé (« uniquement ceux créés par Roblox »)")
    assert p.get("SortType") == 3, "les plus récents d'abord"
    #  ⚠️ L'arrêt anticipé n'est pas un détail de performance : sans lui, ce
    #  relevé ramenait 998 articles pour en écarter 892, et ces 7 pages de
    #  requêtes inutiles épuisaient le débit — si bien que les appels SUIVANTS
    #  (stock, revente, vignettes) tombaient en 429 et que les fiches
    #  partaient sans chiffres ni image.
    assert params_captures["arret_hors_fenetre"] is True


@pytest.mark.asyncio
async def test_le_catalogue_general_ne_sarrete_PAS_a_la_fenetre(params_captures):
    """Le tri « bascules » n'a pas de sens pour les créations : une nouveauté
    du jour et un article de deux ans se suivent dans ce flux."""
    await veille.relever_nouveautes(limite=30)
    assert params_captures["arret_hors_fenetre"] is False


@pytest.mark.asyncio
async def test_les_deux_releves_ont_une_sante_distincte(params_captures):
    """Un flux mort ressemble à un flux calme : il doit se voir SÉPARÉMENT."""
    await veille.relever_collectionnables(limite=30)
    assert params_captures["source"] == "collectionnables"

    await veille.relever_nouveautes(limite=30)
    assert params_captures["source"] == "catalogue"


@pytest.mark.asyncio
async def test_le_releve_des_nouveautes_ne_filtre_PAS_sur_les_limiteds(params_captures):
    """Les deux relevés doivent rester distincts : l'un voit les créations,
    l'autre les collectionnables. Les confondre reperdrait l'un des deux."""
    await veille.relever_nouveautes(limite=30)
    assert "SalesTypeFilter" not in params_captures["params"]


# ═══════════════════════════════════════════════════════════════════════════════
#  2. La règle d'âge — un Limited reste d'actualité
# ═══════════════════════════════════════════════════════════════════════════════

def _article(jours: int) -> dict:
    from datetime import datetime, timedelta, timezone
    quand = datetime.now(timezone.utc) - timedelta(days=jours)
    return {"asset_id": 1, "nom": "X", "cree_le": quand.isoformat(),
            "collectionnable": 1, "hors_vente": 0, "favoris": 10}


@pytest.mark.parametrize("jours", [0, 91, 152, 211, 298, 341, 399])
def test_un_limited_recent_est_publiable(jours):
    """La borne des 90 jours ne s'applique PAS ici.

    Chiffres réels du 16/08 : le Limited officiel le plus récent avait
    152 jours, le plus ancien retenu 341. Avec la borne de 90 jours, pas un
    seul n'aurait pu sortir — même le relevé réparé.
    """
    assert veille.age_publiable(_article(jours), "bascules") is True


@pytest.mark.parametrize("jours", [401, 411, 415, 3000, 6800])
def test_un_limited_ANCIEN_est_ecarte(jours):
    """« Pas des items qui datent d'il y a des années » — demande du 16/08.

    Mesuré sur le flux réel : 58 Limiteds relevés, 11 retenus (2025-09 à
    2026-03) et 47 écartés, dont toute la vague de 2025-06 (411 j) et les
    historiques jusqu'à 2008.
    """
    assert veille.age_publiable(_article(jours), "bascules") is False


def test_la_coupure_tombe_a_la_fenetre_annoncee():
    limite = veille.FRAICHEUR_BASCULE_JOURS
    assert veille.age_publiable(_article(limite - 1), "bascules") is True
    assert veille.age_publiable(_article(limite + 1), "bascules") is False


def test_une_bascule_VUE_EN_DIRECT_passe_quel_que_soit_lage():
    """Un article connu non collectionnable qui le devient est un événement
    d'AUJOURD'HUI, même si l'article a quinze ans. C'est la seule exception,
    et elle est portée par `bascule_detectee`."""
    vieux = _article(6800)
    assert veille.age_publiable(vieux, "bascules") is False
    vieux["bascule_detectee"] = True
    assert veille.age_publiable(vieux, "bascules") is True


def test_une_date_illisible_ne_fait_pas_taire_une_bascule():
    """Rater une vraie bascule coûte plus cher qu'une fiche de trop."""
    assert veille.age_publiable(
        {"asset_id": 1, "cree_le": None}, "bascules") is True


def test_les_autres_flux_gardent_leurs_bornes():
    """Le correctif ne doit pas déverser d'archives dans les autres salons."""
    assert veille.age_publiable(_article(200), "nouveautes") is False
    assert veille.age_publiable(_article(5), "nouveautes") is True
    assert veille.age_publiable(_article(200), "surveiller") is False
    assert veille.age_publiable(_article(2), "surveiller") is False
    assert veille.age_publiable(_article(30), "surveiller") is True


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le câblage — un relevé que personne n'appelle ne sert à rien
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_boucle_releve_les_collectionnables():
    arbre = ast.parse(SRC_BOT)
    for n in ast.walk(arbre):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            corps = ast.unparse(n)
            assert "relever_collectionnables" in corps, (
                "la boucle ne cherche qu'au seul endroit où les Limiteds ne "
                "sont pas")
            return
    raise AssertionError("veille_roblox_task introuvable")


def test_le_bouton_releve_aussi_les_collectionnables():
    """Sinon « Relever maintenant » ne prouverait rien sur ce flux."""
    assert "relever_collectionnables" in SRC_PAN


def test_la_boucle_reste_declaree_et_supervisee():
    """⚠️ Le décorateur a été cassé une fois en insérant du code entre lui et
    sa fonction — le piège n°1 du dépôt. Ce test le verrouille."""
    arbre = ast.parse(SRC_BOT)
    for n in arbre.body:
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            deco = [ast.unparse(d) for d in n.decorator_list]
            assert any("tasks.loop" in d for d in deco), (
                "la boucle a perdu son @tasks.loop : elle ne tournera jamais")
            break
    else:
        raise AssertionError("veille_roblox_task introuvable")
    assert '"veille_roblox_task"' in SRC_BOT, "absente du superviseur"


def test_la_tranche_des_bascules_permet_le_rattrapage():
    """Cinq par passage auraient mis des semaines à rattraper le retard."""
    assert "_TRANCHE_FLUX" in SRC_BOT
    arbre = ast.parse(SRC_BOT)
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Assign) and n.targets
                and getattr(n.targets[0], "id", "") == "_TRANCHE_FLUX"):
            tranches = ast.literal_eval(n.value)
            assert tranches["bascules"] > tranches["nouveaux"], (
                "le flux de rattrapage doit regarder plus loin que les autres")
            return
    raise AssertionError("_TRANCHE_FLUX introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Ce qu'on publie reste sûr
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_lien_dun_limited_est_reconstruit_et_valide():
    """Règle de sécurité ROBLOX.md §1, elle vaut aussi pour ce flux."""
    lien = veille.lien_article(1365767, "Asset")
    #  Le domaine vient d'une CONSTANTE du module, l'identifiant est validé
    #  comme entier — c'est tout l'objet de la règle. La barre finale fait
    #  partie de la forme réelle produite ; on vérifie la construction, pas une
    #  chaîne recopiée à la main.
    assert lien.startswith(veille.DOMAINE_ARTICLE)
    assert "1365767" in lien
    assert veille.lien_article("124'><script>", "Asset") is None
    assert veille.lien_article(None, "Asset") is None


def test_un_bundle_pointe_vers_le_bon_chemin():
    """`/bundles/` et non `/catalog/` — sinon 404 sur ~42 % des articles."""
    lien = veille.lien_article(999, "Bundle")
    assert lien and lien.startswith(veille.DOMAINE_BUNDLE)
