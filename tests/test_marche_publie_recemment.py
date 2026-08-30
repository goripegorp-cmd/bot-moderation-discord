"""Le classement officiel « Publié récemment » — les dix contrôles exigés.

═══════════════════════════════════════════════════════════════════════════════
LE BESOIN AVAIT ÉTÉ MAL INTERPRÉTÉ, ET C'ÉTAIT MA FAUTE
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire, le 30/08/2026 :

    « Je ne demande pas l'asset Roblox possédant la date technique Created la
     plus récente. Je demande le dernier accessoire placé en tête du filtre
     officiel "Publié récemment" du Marketplace Roblox. »

MESURÉ LE JOUR MÊME — les deux classements n'ont AUCUN rapport :

    RANG « PUBLIÉ RÉCEMMENT »       DATE TECHNIQUE DE CRÉATION
    1. Icarus Wings    (92,7 j)     1. Sakura Antlers  (18,4 j)
    2. Medusa Snakes   (92,7 j)     2. Gold Crown      (19,5 j)
    3. Cap of Hermes   (68,6 j)     …
    6. Sakura Antlers  (18,4 j)

`roblox_veille._normaliser` retrie par `cree_le` décroissant. Appliqué à ce
classement, il met Sakura Antlers en tête — soit exactement la mauvaise
réponse. D'où un module séparé, `roblox_marche`, qui NE TRIE JAMAIS.

═══════════════════════════════════════════════════════════════════════════════
LE FIXTURE — bâti sur la réponse observée, PAS un résultat permanent
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire l'a demandé explicitement : « ce résultat changera
naturellement, ne code pas ce nom ou cet identifiant en dur ». Les noms
ci-dessous ne servent donc qu'à éprouver l'ALGORITHME — aucun test n'affirme
que « Icarus Wings » sera toujours premier. Ce qui est verrouillé, c'est que
l'ordre de l'API survit, que les cheveux passent, et que la date ne reprend
jamais la main.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import roblox_marche as marche


#  Réponse RÉELLE du 30/08, réduite aux champs que le module lit.
#  Les âges de création sont volontairement DÉSORDONNÉS par rapport au rang :
#  c'est ce désordre qui fait la valeur du fixture.
REPONSE = {
    "data": [
        {"id": 139683119466435, "name": "Icarus Wings", "itemType": "Asset",
         "assetType": 46, "creatorType": "User", "creatorTargetId": 1,
         "itemCreatedUtc": "2026-05-29T10:00:00Z", "isOffSale": True,
         "itemRestrictions": []},
        {"id": 122550426347379, "name": "Medusa Snakes", "itemType": "Asset",
         "assetType": 41, "creatorType": "User", "creatorTargetId": 1,
         "itemCreatedUtc": "2026-05-29T10:00:00Z", "isOffSale": True,
         "itemRestrictions": []},
        {"id": 124297952377057, "name": "Cap of Hermes", "itemType": "Asset",
         "assetType": 8, "creatorType": "User", "creatorTargetId": 1,
         "itemCreatedUtc": "2026-06-22T10:00:00Z", "isOffSale": True,
         "itemRestrictions": []},
        {"id": 82762961686618, "name": "Sakura Antlers", "itemType": "Asset",
         "assetType": 8, "creatorType": "User", "creatorTargetId": 1,
         #  LE PLUS RÉCEMMENT CRÉÉ, et pourtant seulement 4e au classement.
         "itemCreatedUtc": "2026-08-12T01:18:52Z", "isOffSale": True,
         "itemRestrictions": []},
        {"id": 900000000000001, "name": "Armorsaurs King Chrome",
         "itemType": "Bundle", "assetType": None, "creatorType": "User",
         "creatorTargetId": 1, "itemCreatedUtc": "2026-08-20T10:00:00Z",
         "isOffSale": False, "itemRestrictions": []},
        {"id": 900000000000002, "name": "Moonlight Meadow", "itemType": "Asset",
         "assetType": 92, "creatorType": "User", "creatorTargetId": 1,
         "itemCreatedUtc": "2026-08-25T10:00:00Z", "isOffSale": False,
         "itemRestrictions": []},
        {"id": 900000000000003, "name": "UGC d'un tiers", "itemType": "Asset",
         "assetType": 8, "creatorType": "User", "creatorTargetId": 55555,
         "itemCreatedUtc": "2026-08-28T10:00:00Z", "isOffSale": False,
         "itemRestrictions": []},
    ],
    "nextPageCursor": None,
}


class _Rep:
    def __init__(self, data, statut=200):
        self.status = statut
        self._d = data

    async def json(self):
        return self._d

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Sess:
    def __init__(self, pages, statut=200):
        self.pages, self.appels, self.statut = pages, [], statut

    def get(self, url, params=None):
        self.appels.append(dict(params or {}))
        i = min(len(self.appels) - 1, len(self.pages) - 1)
        return _Rep(self.pages[i], self.statut)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def api(monkeypatch):
    def _poser(pages, statut=200):
        s = _Sess(pages, statut)
        monkeypatch.setattr(marche, "_ouvrir", lambda: s)
        return s
    return _poser


@pytest.fixture
def banc_marche(tmp_path):
    """Branche le suivi sur une base SQLite jetable.

    ⚠️ FIXTURE SYNCHRONE, ET LA CRÉATION DES TABLES SE FAIT DANS LE TEST.
    Une première version fabriquait sa propre boucle d'événements pour appeler
    `init_db` : deux boucles dans le même test, c'est un blocage qui n'attend
    qu'une occasion.
    """
    import contextlib

    import aiosqlite

    chemin = tmp_path / "marche.db"

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    marche.brancher_base(_get_db)
    marche.setup(log=lambda *a, **k: None)
    return _get_db


# ═══════════════════════════════════════════════════════════════════════════════
#  1 · 7 — l'ordre du Marketplace survit, la date ne reprend jamais la main
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_1_le_premier_du_marketplace_passe_avant_le_plus_recemment_cree(api):
    """⚠️ LE CŒUR DE LA CORRECTION. Dans le fixture, « Sakura Antlers » est de
    loin le plus récemment CRÉÉ — et il est 4e au classement. Un tri par date
    le mettrait premier, ce qui est la mauvaise réponse."""
    api([REPONSE])
    tete = await marche.dernier_accessoire_publie()
    assert tete["nom"] == "Icarus Wings"
    assert tete["rang_marche"] == 1

    recent = await marche.dernier_cree_techniquement()
    assert recent["nom"] == "Sakura Antlers", (
        "le second indicateur doit bien rendre le plus récemment créé")
    assert recent["rang_marche"] == 4, (
        "et il conserve son rang Marketplace, il ne devient pas premier")


@pytest.mark.asyncio
async def test_7_l_ordre_de_l_api_nest_jamais_remplace_par_un_tri(api):
    api([REPONSE])
    rep = await marche.relever_page()
    rangs = [it["rang_marche"] for it in rep["items"]]
    assert rangs == list(range(1, len(rangs) + 1)), (
        "les rangs doivent suivre l'ordre RENDU, sans trou ni permutation")
    noms = [it["nom"] for it in rep["items"][:4]]
    assert noms == ["Icarus Wings", "Medusa Snakes", "Cap of Hermes",
                    "Sakura Antlers"]


def test_7bis_aucun_tri_par_date_dans_le_chemin_de_lecture():
    """⚠️ INTERDIT PAR ÉCRIT : « il est interdit de refaire
    results.sort((a, b) => b.createdAt - a.createdAt) ». On le vérifie dans le
    code, pas seulement dans l'intention."""
    for fn in (marche.relever_page, marche._normaliser,
               marche.dernier_accessoire_publie):
        src = inspect.getsource(fn)
        ast.parse(src.lstrip())
        assert ".sort(" not in src, f"{fn.__name__} retrie le classement"
        assert "sorted(" not in src, f"{fn.__name__} retrie le classement"


# ═══════════════════════════════════════════════════════════════════════════════
#  2 · 3 — les cheveux ne sont plus exclus
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_2_medusa_snakes_nest_pas_exclu(api):
    """⚠️ L'ANCIEN FILTRE `Category=11 + Subcategory=19` L'EXCLUAIT, alors
    qu'il est DEUXIÈME du classement officiel."""
    api([REPONSE])
    rep = await marche.relever_page()
    medusa = next(x for x in rep["items"] if x["nom"] == "Medusa Snakes")
    assert medusa["accepte"] is True
    assert medusa["rang_marche"] == 2


def test_3_le_type_cheveux_est_reconnu():
    assert 41 in marche.TYPES_ACCESSOIRE
    ok, motif = marche.est_accessoire(
        {"itemType": "Asset", "creatorType": "User", "creatorTargetId": 1,
         "assetType": 41})
    assert ok is True and "heveux" in motif


def test_3bis_les_huit_types_nommes_sont_tous_la():
    """Le propriétaire les nomme un par un. En oublier un ferait disparaître
    une famille entière, en silence."""
    for at in (8, 41, 42, 43, 44, 45, 46, 47):
        assert at in marche.TYPES_ACCESSOIRE, f"type {at} manquant"


def test_3ter_la_requete_utilise_Category_1_et_pas_11():
    """« Le filtre visible sur la capture est "Tous". Il doit donc être traduit
    par Category=1. »"""
    p = marche.parametres()
    assert p["Category"] == 1
    assert "Subcategory" not in p


# ═══════════════════════════════════════════════════════════════════════════════
#  4 · 5 · 6 — hors vente inclus, créateur vérifié, bundle ignoré
# ═══════════════════════════════════════════════════════════════════════════════

def test_4_les_objets_hors_vente_sont_demandes():
    """C'est « Afficher les items indisponibles » sur le site — et sans ce
    paramètre, les deux premiers du classement n'existent pas."""
    assert marche.parametres()["IncludeNotForSale"] == "true"


@pytest.mark.asyncio
async def test_4bis_un_article_hors_vente_reste_accepte(api):
    api([REPONSE])
    tete = await marche.dernier_accessoire_publie()
    assert tete["en_vente"] is False, (
        "le premier du classement est hors vente : l'exclure viderait le "
        "classement de sa tête")


@pytest.mark.asyncio
async def test_5_un_ugc_de_tiers_est_rejete(api):
    api([REPONSE])
    rep = await marche.relever_page()
    tiers = next(x for x in rep["items"] if x["createur_id"] == 55555)
    assert tiers["accepte"] is False
    assert "≠ 1" in tiers["motif"]


def test_5bis_le_createur_est_impose_dans_la_requete():
    p = marche.parametres()
    assert p["CreatorTargetId"] == 1 and p["CreatorType"] == "User"


@pytest.mark.asyncio
async def test_6_un_bundle_est_ignore(api):
    api([REPONSE])
    rep = await marche.relever_page()
    b = next(x for x in rep["items"] if x["item_type"] == "Bundle")
    assert b["accepte"] is False
    assert "Asset" in b["motif"]


def test_6bis_les_non_portables_sont_rejetes_avec_leur_nom():
    """« Sans confondre : accessoires, bundles, animations, parties du corps,
    vêtements classiques, objets qui ne sont pas portables. » Chaque refus doit
    porter un motif lisible, sinon le filtre est indébogable."""
    for at, attendu in ((92, "arrière-plan"), (11, "classique"),
                        (88, "aquillage")):
        ok, motif = marche.est_accessoire(
            {"itemType": "Asset", "creatorType": "User",
             "creatorTargetId": 1, "assetType": at})
        assert ok is False and attendu in motif, (at, motif)


def test_6ter_un_type_inconnu_le_DIT():
    """Roblox ajoute des types régulièrement. Les taire ferait disparaître une
    famille entière sans un mot — c'est exactement ce qui est arrivé."""
    ok, motif = marche.est_accessoire(
        {"itemType": "Asset", "creatorType": "User", "creatorTargetId": 1,
         "assetType": 9999})
    assert ok is False and "inconnu" in motif


# ═══════════════════════════════════════════════════════════════════════════════
#  8 — la pagination continue quand la page 1 n'a aucun accessoire
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_8_on_pagine_quand_la_page_1_na_aucun_accessoire(api):
    page1 = {"data": [
        {"id": 1, "name": "Fond", "itemType": "Asset", "assetType": 92,
         "creatorType": "User", "creatorTargetId": 1, "isOffSale": False,
         "itemCreatedUtc": "2026-08-01T00:00:00Z", "itemRestrictions": []}],
        "nextPageCursor": "page2"}
    page2 = {"data": [
        {"id": 2, "name": "Un vrai chapeau", "itemType": "Asset",
         "assetType": 8, "creatorType": "User", "creatorTargetId": 1,
         "isOffSale": False, "itemCreatedUtc": "2026-07-01T00:00:00Z",
         "itemRestrictions": []}], "nextPageCursor": None}
    s = api([page1, page2])
    tete = await marche.dernier_accessoire_publie()
    assert tete is not None and tete["nom"] == "Un vrai chapeau"
    assert len(s.appels) == 2, "la seconde page n'a pas été demandée"
    assert s.appels[1].get("Cursor") == "page2"


# ═══════════════════════════════════════════════════════════════════════════════
#  9 · 10 — le changement de tête, et le repli sur le dernier confirmé
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_9_le_changement_de_tete_est_detecte(banc_marche, api):
    await marche.init_db()
    api([REPONSE])
    rep = await marche.relever_page()
    r1 = await marche.noter_tete(rep["items"])
    assert r1["change"] is False, "le tout premier relevé n'est pas un changement"

    #  Un nouvel article prend la tête.
    autre = {"data": [dict(REPONSE["data"][0], id=111222333, name="Neuf")]
             + REPONSE["data"], "nextPageCursor": None}
    api([autre])
    rep2 = await marche.relever_page()
    r2 = await marche.noter_tete(rep2["items"])
    assert r2["change"] is True
    assert r2["maintenant"] == 111222333


@pytest.mark.asyncio
async def test_9bis_l_empreinte_change_quand_l_ORDRE_change():
    """Deux relevés portant les MÊMES articles dans un ordre différent doivent
    donner deux empreintes différentes : c'est le changement d'ordre qui nous
    intéresse, pas seulement le contenu."""
    a = [{"rang_marche": 1, "asset_id": 10}, {"rang_marche": 2, "asset_id": 20}]
    b = [{"rang_marche": 1, "asset_id": 20}, {"rang_marche": 2, "asset_id": 10}]
    assert marche.empreinte(a) != marche.empreinte(b)


@pytest.mark.asyncio
async def test_10_une_erreur_api_conserve_le_dernier_confirme(banc_marche, api):
    """⚠️ EXIGENCE ÉCRITE : « une erreur API conserve le dernier résultat
    confirmé ». Afficher « inconnu » parce que Roblox a hoqueté serait pire
    que de dire ce qu'on savait."""
    await marche.init_db()
    api([REPONSE])
    rep = await marche.relever_page()
    await marche.noter_tete(rep["items"])

    api([{}], statut=503)
    casse = await marche.relever_page()
    assert casse["code"] == 503 and casse["items"] == []
    assert await marche.dernier_accessoire_publie() is None, (
        "on ne fabrique pas une réponse quand l'API tombe")

    garde = await marche.tete_memorisee()
    assert garde is not None and garde["nom"] == "Icarus Wings"


# ═══════════════════════════════════════════════════════════════════════════════
#  Le câblage — sans lui, rien de tout cela ne tourne
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_boucle_de_suivi_existe_et_est_supervisee():
    """⚠️ PIÈGE N°1 ET N°2 DU DÉPÔT RÉUNIS : une boucle sans décorateur ne
    tourne jamais, et une boucle absente du superviseur meurt à la première
    exception."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_marche_task":
            deco = " ".join(ast.unparse(d) for d in n.decorator_list)
            assert "tasks.loop" in deco
            #  Entre 2 et 5 minutes, comme demandé.
            assert "minutes=4" in deco or "minutes=3" in deco \
                or "minutes=5" in deco or "minutes=2" in deco
            break
    else:
        raise AssertionError("veille_marche_task introuvable")
    assert '"veille_marche_task"' in src, "absente du superviseur"
    assert "veille_marche_task.start()" in src, "jamais démarrée"


def test_la_commande_de_diagnostic_existe():
    """Le `/debug-marketplace-recent` demandé : les 20 premiers dans l'ordre
    exact, acceptés ET rejetés, avec le motif."""
    import roblox_commandes as cmds
    assert "marche" in {c.name for c in cmds.groupe.commands}
    src = inspect.getsource(cmds.marche_cmd.callback)
    ast.parse(src.lstrip())
    assert "tableau_diagnostic" in src
    assert "tete_memorisee" in src, (
        "sans repli, une panne de l'API afficherait « rien » au lieu du "
        "dernier résultat confirmé")
