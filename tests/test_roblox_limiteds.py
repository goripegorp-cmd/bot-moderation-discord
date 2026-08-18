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

    async def _faux(params, source, max_pages=None):
        vus["params"] = dict(params)
        vus["source"] = source
        vus["max_pages"] = max_pages
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
    #  ⚠️ Ce flux N'EST PAS trié par date (mesuré le 18/08 : la page 1 va de
    #  154 à 6 955 jours) — donc pas d'arrêt anticipé « par date ». Il ne sert
    #  qu'à détecter : deux pages, pas plus, sinon les 8 pages épuisent le
    #  débit et les appels de fiche (stock, revente, vignettes) tombent en 429.
    assert params_captures["max_pages"] == veille.MAX_PAGES_COLLECTIONNABLES
    assert 1 <= veille.MAX_PAGES_COLLECTIONNABLES <= 3


@pytest.mark.asyncio
async def test_le_catalogue_general_va_au_bout(params_captures):
    """Lui est trié par création et doit être COMPLET (964 articles, 9 pages) :
    c'est là que se voient presque toutes les bascules."""
    await veille.relever_nouveautes(limite=30)
    assert params_captures["max_pages"] is None


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
#  2. La règle de publication — « VIENT de passer », « créé À PARTIR DE
#     MAINTENANT » (tranché par le propriétaire le 18/08)
#
#  ⚠️ Ces tests REMPLACENT ceux du 16/08, qui verrouillaient un rattrapage des
#  Limiteds récents (≤ 400 jours). Le propriétaire a tranché contre deux jours
#  plus tard : « uniquement les accessoires qui deviennent limited, pas ceux
#  qui le sont déjà devenus ; tu dis bien qu'il VIENT de passer, pas il y a un
#  jour, deux jours ». La consigne a changé, la garde suit.
# ═══════════════════════════════════════════════════════════════════════════════

def _article(jours: int = 0, heures: float = 0) -> dict:
    from datetime import datetime, timedelta, timezone
    quand = datetime.now(timezone.utc) - timedelta(days=jours, hours=heures)
    return {"asset_id": 1, "nom": "X", "cree_le": quand.isoformat(),
            "collectionnable": 1, "hors_vente": 0, "favoris": 10}


@pytest.mark.parametrize("jours", [0, 91, 152, 341, 399, 401, 3000, 6800])
def test_un_limited_deja_collectionnable_nest_JAMAIS_publie_par_son_age(jours):
    """Sans le marqueur `bascule_detectee`, un Limited est « déjà devenu » —
    hors périmètre, quel que soit son âge. Le 16/08 laissait passer jusqu'à
    400 jours ; c'est fini."""
    assert veille.age_publiable(_article(jours), "bascules") is False


@pytest.mark.parametrize("jours", [0, 152, 6800])
def test_une_bascule_VUE_EN_DIRECT_passe_quel_que_soit_lage(jours):
    """Un article connu non collectionnable qui le devient sous nos yeux est
    un événement d'AUJOURD'HUI, même si l'article a quinze ans. C'est le SEUL
    chemin vers le flux « bascules », porté par `bascule_detectee`."""
    a = _article(jours)
    a["bascule_detectee"] = True
    assert veille.age_publiable(a, "bascules") is True


def test_la_fenetre_de_fraicheur_ne_gouverne_plus_la_publication():
    """Elle borne la PAGINATION du relevé des Limiteds (détection), pas ce
    qui sort : sous ou au-dessus de la fenêtre, sans marqueur, rien ne sort."""
    limite = veille.FRAICHEUR_BASCULE_JOURS
    assert veille.age_publiable(_article(limite - 1), "bascules") is False
    assert veille.age_publiable(_article(limite + 1), "bascules") is False


def test_une_date_illisible_ne_change_rien_pour_une_bascule():
    """Seul le marqueur compte : la date de création n'entre plus en jeu."""
    assert veille.age_publiable({"asset_id": 1, "cree_le": None}, "bascules") is False
    assert veille.age_publiable(
        {"asset_id": 1, "cree_le": None, "bascule_detectee": True}, "bascules") is True


@pytest.mark.parametrize("heures", [0, 1, 5.5])
def test_une_nouveaute_creee_il_y_a_moins_de_six_heures_est_publiee(heures):
    """« Que les nouveaux créés à partir de maintenant »."""
    assert veille.age_publiable(_article(heures=heures), "nouveautes") is True


@pytest.mark.parametrize("heures", [6.5, 24, 24 * 5, 24 * 200])
def test_une_nouveaute_plus_ancienne_est_absorbee_pas_publiee(heures):
    """Les 850 articles que la pagination découvre d'un coup — créés il y a
    des semaines — ne sont pas « nouveaux ». Et « il y a un jour, deux
    jours » non plus : c'est le mot du propriétaire."""
    assert veille.age_publiable(_article(heures=heures), "nouveautes") is False


def test_une_nouveaute_sans_date_ne_sort_pas():
    """Fail-closed : on ne peut pas prouver « récent », on se tait. C'est
    l'inverse de la règle du 15/08 — la consigne a changé."""
    assert veille.age_publiable({"asset_id": 1, "cree_le": None}, "nouveautes") is False


def test_le_flux_surveiller_garde_ses_bornes_meme_sil_ne_publie_plus():
    """La fonction existe encore (indice) ; ses bornes restent cohérentes."""
    assert veille.age_publiable(_article(200), "surveiller") is False
    assert veille.age_publiable(_article(2), "surveiller") is False
    assert veille.age_publiable(_article(30), "surveiller") is True


# ── La détection elle-même : « vient de » exige de l'avoir VU avant ──────────

@pytest.mark.asyncio
async def test_une_bascule_nest_detectee_que_si_on_a_vu_larticle_recemment(monkeypatch):
    """Si notre dernière observation date de plus de FENETRE_DIRECTE_HEURES —
    bot arrêté, premier passage après déploiement — la bascule a pu avoir lieu
    il y a deux jours : on met la base à jour, on ne publie pas."""
    import contextlib
    from datetime import datetime, timedelta, timezone

    def _faux_get_db(vu_le_iso):
        class _Cur:
            async def fetchone(self):
                return ("0|0", 0, 0, vu_le_iso)   # connu NON collectionnable

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def __await__(self):
                async def _r():
                    return self
                return _r().__await__()

        class _DB:
            def execute(self, q, p=()):
                return _Cur()

            async def commit(self):
                return None

        @contextlib.asynccontextmanager
        async def _get_db():
            yield _DB()

        return _get_db

    art = dict(_article(200), collectionnable=1)   # aujourd'hui collectionnable

    #  Vu il y a 1 h non collectionnable → il VIENT de passer.
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    monkeypatch.setattr(veille, "_get_db", _faux_get_db(recent))
    res = await veille.comparer_et_enregistrer([dict(art)])
    assert len(res["bascules"]) == 1 and res["bascules"][0].get("bascule_detectee") is True

    #  Vu il y a 3 jours → la bascule a pu se produire n'importe quand depuis :
    #  enregistrée comme ancienne, PAS publiée.
    vieux = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    monkeypatch.setattr(veille, "_get_db", _faux_get_db(vieux))
    res = await veille.comparer_et_enregistrer([dict(art)])
    assert res["bascules"] == []
    assert len(res.get("bascules_anciennes") or []) == 1


def test_la_fenetre_directe_est_courte_mais_survit_a_un_redemarrage():
    """La boucle passe toutes les 30 min ; un redémarrage Railway prend
    quelques minutes. Six heures : assez pour ça, pas assez pour « il y a un
    jour »."""
    assert 1 <= veille.FENETRE_DIRECTE_HEURES <= 12


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
