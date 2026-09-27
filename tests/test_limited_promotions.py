"""Les passages en Limited qu'on ne voyait pas (27/09/2026).

CE QUE LE PROPRIÉTAIRE A MONTRÉ (27/09) : sept « nouveaux Limited » de Roblox,
absents du serveur. MESURÉ SUR L'API OFFICIELLE DE ROBLOX — jamais ailleurs :
  · Dark Guardian Angel, Striking White Owl Shoulder Pet, Extraterrestrial
    Shades, Ice Fire Ram Skull Helm : horodatage Roblox du 22/09, 23:04:41 →
    23:06:53 UTC ; revendus depuis 2024-2025. Des « UGC Limited » de Roblox
    reclassés en Limited U : collectionnables avant ET après, la base n'y
    voyait rien. Journal du 22/09 à 23:xx : « 0 bascule(s) » sur un tour
    complet du flux qui les contenait ;
  · Molten Lava Wings, Atomic Blue Hairdo : la même chose le 28/08 — et Molten
    Lava Wings n'était dans AUCUNE page du flux Limited : la recherche de
    Roblox s'arrête à 1 000 résultats (995 d'un seul tenant, 1 997 en trois
    parties) ;
  · Shedletsekkar : créé Limited U le 24/09, 20 exemplaires, tous vendus — la
    fiche aurait dit « 🟢 en vente » ;
  · au passage, « Telamon's Other Crafting Jewel » : créé le 25/09, mis en
    vente le 27/09 à 15:13 — jeté par la règle « créé il y a moins de 6 h ».

Ces tests tournent sur une VRAIE base SQLite. Roblox est simulé ; la conftest
refuse tout vrai réseau.
"""
from __future__ import annotations

import ast
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import roblox_panneau as rp
import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
GUILDE = 777


def _iso(heures: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=heures)).isoformat()


def _brut(aid: int, *, restrictions=(), age_h: float = 24 * 700,
          hors_vente: bool = False, item_type: str = "Asset"):
    """Une fiche telle que le catalogue la rend (champs mesurés le 27/09)."""
    b = {"id": aid, "name": f"Article {aid}", "itemType": item_type,
         "itemCreatedUtc": _iso(age_h).replace("+00:00", "Z"),
         "itemRestrictions": list(restrictions), "price": 0,
         "favoriteCount": 5, "creatorTargetId": 1, "creatorType": "User"}
    if hors_vente:
        b["isOffSale"] = True
    return b


async def _voir(*bruts) -> dict:
    return await veille.comparer_et_enregistrer(veille._normaliser(list(bruts)))


async def _vieillir(aid: int, heures: float) -> None:
    """Notre dernière observation de l'article remonte à `heures`."""
    async with veille._get_db() as db:
        await db.execute("UPDATE roblox_articles SET vu_le=? WHERE asset_id=?",
                         (_iso(heures), aid))
        await db.commit()


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "limited.db"

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return {}

    async def _db_set(_g, _k, _v):
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                 log=lambda *a, **k: None)
    return _get_db


class _Reponse:
    """Une réponse aiohttp : statut, en-têtes, `json(content_type=…)`."""

    def __init__(self, status, data):
        self.status = status
        self._data = data
        self.headers = {"x-ratelimit-limit": "2, 2;w=1",
                        "x-ratelimit-remaining": "1"}

    async def json(self, content_type=None):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def roblox(monkeypatch):
    """L'économie de Roblox, simulée : `fiches[id] = (statut, corps)`."""
    etat = {"fiches": {}, "demandes": []}

    class _Session:
        def get(self, url, params=None, headers=None):
            aid = int(url.rstrip("/").split("/")[-2])
            etat["demandes"].append(aid)
            statut, corps = etat["fiches"].get(aid, (404, None))
            return _Reponse(statut, corps)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _dodo(_s):
        return None

    monkeypatch.setattr(veille, "_ouvrir", lambda: _Session())
    monkeypatch.setattr(veille.asyncio, "sleep", _dodo)
    return etat


def _economie(heures: float, *, limited_u=True, en_vente=False):
    """Le corps de `economy/v2/assets/{id}/details`, champs réels."""
    return (200, {"Updated": _iso(heures).replace("+00:00", "Z"),
                  "Created": _iso(24 * 700).replace("+00:00", "Z"),
                  "IsLimited": not limited_u, "IsLimitedUnique": limited_u,
                  "IsForSale": en_vente, "Remaining": 0})


# ═══════════════════════════════════════════════════════════════════════════════
#  A — la classe exacte, et la promotion d'un UGC Limited
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A1_un_UGC_Limited_devenu_Limited_U_est_une_bascule(base, roblox):
    """La fournée du 22/09, rejouée : connu UGC Limited, revu Limited U."""
    await veille.init_db()
    await _voir(_brut(76292007466829, restrictions=["Collectible"]))
    res = await _voir(_brut(76292007466829, restrictions=["LimitedUnique"]))
    assert [a["asset_id"] for a in res["bascules"]] == [76292007466829]
    a = res["bascules"][0]
    assert a["bascule_detectee"] and a["classe_avant"] == veille.CLASSE_COLLECTIBLE
    assert veille.age_publiable(a, "bascules")
    assert await veille.enfiler(GUILDE, a, "bascules")
    async with veille._get_db() as db:
        async with db.execute("SELECT de, vers FROM roblox_transitions") as cur:
            assert await cur.fetchall() == [("Collectible", "LimitedUnique")]
    assert roblox["demandes"] == [], "vue de près : aucune datation à demander"


@pytest.mark.parametrize("avant,apres", [
    (["Collectible"], ["Collectible"]),
    (["LimitedUnique"], ["LimitedUnique"]),
    (["Limited"], ["LimitedUnique"]),
    (["LimitedUnique"], ["Limited"]),
    (["Limited"], ["Collectible"]),
])
@pytest.mark.asyncio
async def test_A2_rien_d_autre_n_est_une_promotion(base, roblox, avant, apres):
    await veille.init_db()
    await _voir(_brut(5, restrictions=avant))
    res = await _voir(_brut(5, restrictions=apres))
    assert res["bascules"] == [] and not res.get("bascules_anciennes")


@pytest.mark.asyncio
async def test_A3_une_classe_INCONNUE_ne_promeut_rien_mais_se_remplit(base, roblox):
    """Un article connu avant la colonne : on ne sait pas d'où il part."""
    await veille.init_db()
    async with veille._get_db() as db:
        await db.execute(
            "INSERT INTO roblox_articles(asset_id, nom, collectionnable,"
            " hors_vente, vu_le, classe) VALUES(9, 'x', 1, 0, ?, NULL)", (_iso(1),))
        await db.commit()
    res = await _voir(_brut(9, restrictions=["LimitedUnique"]))
    assert res["bascules"] == []
    async with veille._get_db() as db:
        async with db.execute("SELECT classe FROM roblox_articles WHERE asset_id=9") as cur:
            assert (await cur.fetchone())[0] == veille.CLASSE_LIMITED_U


@pytest.mark.asyncio
async def test_A4_une_promotion_sort_MEME_si_l_UGC_Limited_etait_deja_sorti(base, roblox):
    """Annoncé jadis « UGC Limited », il devient VRAI Limited : autre nouvelle.
    L'unicité de la transition garde du doublon."""
    await veille.init_db()
    await veille.marquer_publie(GUILDE, 11, "bascules")
    a = {"asset_id": 11, "bascule_detectee": True, "classe": "LimitedUnique",
         "classe_avant": veille.CLASSE_COLLECTIBLE, "createur_id": 1,
         "collectionnable": 1, "hors_vente": 1}
    assert await veille.publiable_dans(GUILDE, 11, "bascules") is False
    assert await veille.publiable_dans(GUILDE, 11, "bascules", article=a) is True
    assert await veille.enfiler(GUILDE, a, "bascules") is True
    assert await veille.enfiler(GUILDE, dict(a), "bascules") is False
    b = dict(a, classe_avant=None)
    assert await veille.publiable_dans(GUILDE, 11, "bascules", article=b) is False


@pytest.mark.asyncio
async def test_A5_la_migration_reprend_la_classe_des_mesures(base, roblox):
    """Sans elle, le premier tour après le déploiement serait aveugle."""
    await veille.init_db()
    async with veille._get_db() as db:
        await db.execute("DELETE FROM roblox_migrations WHERE cle=?",
                         (veille.MIGRATION_CLASSES,))
        await db.execute(
            "INSERT INTO roblox_articles(asset_id, nom, collectionnable,"
            " hors_vente, vu_le) VALUES(12, 'x', 1, 0, ?)", (_iso(1),))
        for quand, classe in ((_iso(48), ""), (_iso(2), "Collectible")):
            await db.execute(
                "INSERT INTO roblox_mesures(asset_id, mesure_le, collectionnable,"
                " classe) VALUES(12, ?, 1, ?)", (quand, classe))
        await db.commit()
    assert await veille._migrer_classes() >= 1
    async with veille._get_db() as db:
        async with db.execute("SELECT classe FROM roblox_articles WHERE asset_id=12") as cur:
            assert (await cur.fetchone())[0] == "Collectible"
    assert await veille._migrer_classes() == 0, "une fois, jamais deux"
    res = await _voir(_brut(12, restrictions=["LimitedUnique"]))
    assert [x["asset_id"] for x in res["bascules"]] == [12]


@pytest.mark.asyncio
async def test_A6_le_demarrage_joue_la_migration(base, roblox):
    """La migration ne vaut que si le démarrage la joue : une base de
    production arrive avec ses articles et ses mesures, sans colonne remplie."""
    await veille.init_db()
    async with veille._get_db() as db:
        await db.execute("DELETE FROM roblox_migrations WHERE cle=?",
                         (veille.MIGRATION_CLASSES,))
        await db.execute(
            "INSERT INTO roblox_articles(asset_id, nom, collectionnable,"
            " hors_vente, vu_le) VALUES(13, 'x', 1, 0, ?)", (_iso(1),))
        await db.execute(
            "INSERT INTO roblox_mesures(asset_id, mesure_le, collectionnable,"
            " classe) VALUES(13, ?, 1, 'Collectible')", (_iso(3),))
        await db.commit()
    await veille.init_db()
    async with veille._get_db() as db:
        async with db.execute("SELECT classe FROM roblox_articles WHERE asset_id=13") as cur:
            assert (await cur.fetchone())[0] == "Collectible"


# ═══════════════════════════════════════════════════════════════════════════════
#  B — Roblox date ce que notre mémoire ne sait pas dater
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_B1_Roblox_confirme_une_promotion_vue_trop_tard(base, roblox):
    await veille.init_db()
    await _voir(_brut(21, restrictions=["Collectible"]))
    await _vieillir(21, 30)
    roblox["fiches"][21] = _economie(1)
    res = await _voir(_brut(21, restrictions=["LimitedUnique"]))
    assert [a["asset_id"] for a in res["bascules"]] == [21]
    a = res["bascules"][0]
    assert a["date_roblox"] and a["passe_le"] and a["classe_avant"] == "Collectible"
    assert not res.get("bascules_anciennes")


@pytest.mark.asyncio
async def test_B2_Roblox_ne_blanchit_pas_un_vieux_passage(base, roblox):
    """« Pas il y a un jour, deux jours » (18/08) — prouvé par Roblox."""
    await veille.init_db()
    await _voir(_brut(22, restrictions=["Collectible"]))
    await _vieillir(22, 30)
    roblox["fiches"][22] = _economie(24 * 5)
    res = await _voir(_brut(22, restrictions=["LimitedUnique"]))
    assert res["bascules"] == [] and len(res["bascules_anciennes"]) == 1


@pytest.mark.asyncio
async def test_B3_un_Limited_jamais_vu_n_est_date_qu_apres_un_tour_complet(base, roblox):
    await veille.init_db()
    roblox["fiches"][31] = _economie(0.5)
    res = await _voir(_brut(31, restrictions=["LimitedUnique"]))
    assert res["bascules"] == [] and roblox["demandes"] == [], (
        "avant le premier tour complet, « jamais vu » veut dire « pas encore lu »")
    await veille._curseur_ecrit(veille.SOURCE_RECENSEMENT, "0|", 1)
    lu_au_premier_tour = veille._normaliser([_brut(32, restrictions=["Limited"])])
    lu_au_premier_tour[0]["premier_tour"] = True
    roblox["fiches"][32] = _economie(0.5, limited_u=False)
    res = await veille.comparer_et_enregistrer(lu_au_premier_tour)
    assert res["bascules"] == [] and roblox["demandes"] == []
    roblox["fiches"][33] = _economie(0.5)
    res = await _voir(_brut(33, restrictions=["LimitedUnique"]))
    assert [a["asset_id"] for a in res["bascules"]] == [33]
    assert roblox["demandes"] == [33]


@pytest.mark.asyncio
async def test_B4_au_plus_huit_datations_et_arret_au_premier_refus(base, roblox):
    await veille.init_db()
    ids = list(range(100, 112))
    for i in ids:
        await _voir(_brut(i, restrictions=["Collectible"]))
        await _vieillir(i, 30)
        roblox["fiches"][i] = _economie(24 * 5)
    await _voir(*[_brut(i, restrictions=["LimitedUnique"]) for i in ids])
    assert len(roblox["demandes"]) == veille.MAX_DATATIONS_ROBLOX == 8
    roblox["demandes"].clear()
    for i in ids:
        await _vieillir(i, 30)
        async with veille._get_db() as db:
            await db.execute("UPDATE roblox_articles SET classe='Collectible'"
                             " WHERE asset_id=?", (i,))
            await db.commit()
    roblox["fiches"][ids[2]] = (429, None)
    await _voir(*[_brut(i, restrictions=["LimitedUnique"]) for i in ids])
    assert roblox["demandes"] == ids[:3], "un seau qui dit non n'est pas relancé"


@pytest.mark.asyncio
async def test_B5_un_pack_n_est_jamais_date(base, roblox):
    """Les packs n'ont pas de fiche économie (HTTP 400, mesuré le 16/08)."""
    await veille.init_db()
    await _voir(_brut(41, restrictions=["Collectible"], item_type="Bundle"))
    await _vieillir(41, 30)
    await _voir(_brut(41, restrictions=["LimitedUnique"], item_type="Bundle"))
    assert roblox["demandes"] == []


# ═══════════════════════════════════════════════════════════════════════════════
#  C — une nouveauté, c'est sa SORTIE
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_C1_une_creation_mise_en_vente_plus_tard_est_une_nouveaute(base, roblox):
    """« Telamon's Other Crafting Jewel » : créé 43 h avant sa mise en vente."""
    await veille.init_db()
    roblox["fiches"][51] = _economie(1, en_vente=True)
    res = await _voir(_brut(51, age_h=43))
    a = next(x for x in res["nouveaux"] if x["asset_id"] == 51)
    assert a["sortie_le"] and a["date_roblox"]
    assert veille.age_publiable(a, "nouveautes")
    assert await veille.enfiler(GUILDE, a, "nouveautes")


@pytest.mark.parametrize("economie", [_economie(24 * 3, en_vente=True),
                                      _economie(1, en_vente=False),
                                      (404, None)])
@pytest.mark.asyncio
async def test_C2_sans_preuve_de_sortie_recente_rien_ne_sort(base, roblox, economie):
    await veille.init_db()
    roblox["fiches"][52] = economie
    res = await _voir(_brut(52, age_h=43))
    a = next(x for x in res["nouveaux"] if x["asset_id"] == 52)
    assert not a.get("sortie_le") and not veille.age_publiable(a, "nouveautes")


@pytest.mark.asyncio
async def test_C3_au_dela_de_30_jours_ce_n_est_plus_une_nouveaute(base, roblox):
    await veille.init_db()
    roblox["fiches"][53] = _economie(1, en_vente=True)
    res = await _voir(_brut(53, age_h=24 * 40))
    assert roblox["demandes"] == []
    assert not veille.age_publiable(res["nouveaux"][0], "nouveautes")


@pytest.mark.asyncio
async def test_C4_connue_hors_vente_la_voici_en_vente(base, roblox):
    """Vue hors vente au relevé précédent, en vente maintenant : sa sortie."""
    await veille.init_db()
    await _voir(_brut(54, age_h=48, hors_vente=True))
    res = await _voir(_brut(54, age_h=48))
    assert [a["asset_id"] for a in res["mises_en_vente"]] == [54]
    assert veille.age_publiable(res["mises_en_vente"][0], "nouveautes")
    #  Vue de loin (dernière observation > 6 h) : on ne sait pas QUAND.
    await _voir(_brut(55, age_h=48, hors_vente=True))
    await _vieillir(55, 30)
    res = await _voir(_brut(55, age_h=48))
    assert not res.get("mises_en_vente")
    #  Un Limited revendu entre joueurs n'est pas un nouvel accessoire.
    await _voir(_brut(56, age_h=48, hors_vente=True, restrictions=["Limited"]))
    res = await _voir(_brut(56, age_h=48, restrictions=["Limited"]))
    assert not res.get("mises_en_vente")
    #  Et au-delà de 30 jours, c'est un retour en vente.
    await _voir(_brut(57, age_h=24 * 40, hors_vente=True))
    res = await _voir(_brut(57, age_h=24 * 40))
    assert not res.get("mises_en_vente")


def test_C5_une_sortie_ne_rajeunit_jamais_une_vieille_creation():
    """Double garde : même avec une sortie datée, au-delà de 30 jours c'est un
    retour en vente."""
    vieux = {"cree_le": _iso(24 * 40), "sortie_le": _iso(0.5)}
    assert not veille.age_publiable(vieux, "nouveautes")
    assert veille.age_publiable(dict(vieux, cree_le=_iso(24 * 20)), "nouveautes")
    assert not veille.age_publiable(dict(vieux, cree_le=_iso(24 * 20),
                                         sortie_le=_iso(7)), "nouveautes")


# ═══════════════════════════════════════════════════════════════════════════════
#  D — la fiche le dit
# ═══════════════════════════════════════════════════════════════════════════════

def _texte(vue) -> str:
    return str(vue.to_components())


@pytest.fixture
def panneau():
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


def _promotion(**kw):
    a = {"asset_id": 76292007466829, "nom": "Dark Guardian Angel",
         "type_article": "Chapeau", "item_type": "Asset", "prix": 0,
         "collectionnable": 1, "hors_vente": 1, "classe": "LimitedUnique",
         "limited_u": 1, "bascule_detectee": True, "classe_avant": "Collectible",
         "cree_le": "2024-08-30T16:28:46Z", "revente": 5700, "stock": 31516}
    a.update(kw)
    return a


def test_D1_la_fiche_d_une_promotion_dit_d_ou_il_vient_et_quand(panneau):
    t = _texte(rp.construire_fiche(_promotion(passe_le=_iso(0.2)), "bascules"))
    assert "VIENT DE PASSER LIMITED U" in t
    assert "**Avant** · UGC Limited" in t
    #  Offert lors d'un événement, jamais vendu : il se revend, il n'est pas
    #  « épuisé » — même si l'économie dit `Remaining: 0`.
    t0 = _texte(rp.construire_fiche(_promotion(restant=0, en_vente=False), "bascules"))
    assert "revente entre joueurs" in t0 and "épuisé" not in t0
    assert "heure donnée par Roblox" in t and ":R>" in t
    assert "31 516" in t and "5 700 R$" in t


def test_D2_une_heure_Roblox_trop_vieille_n_est_pas_attribuee_au_passage(panneau):
    t = _texte(rp.construire_fiche(_promotion(maj_roblox=_iso(72)), "bascules"))
    assert "détecté à l'instant" in t and "heure donnée par Roblox" not in t
    t = _texte(rp.construire_fiche(_promotion(maj_roblox=_iso(1)), "bascules"))
    assert "heure donnée par Roblox" in t


def test_D3_un_Limited_EPUISE_n_est_pas_en_vente(panneau):
    """Shedletsekkar : 20 exemplaires à 2 000 000 R$, tous partis."""
    a = {"asset_id": 93762663362787, "nom": "Shedletsekkar", "prix": 2000000,
         "collectionnable": 1, "hors_vente": 0, "classe": "LimitedUnique",
         "limited_u": 1, "en_vente": True, "restant": 0, "stock": 20,
         "cree_le": "2026-09-24T19:51:04Z", "type_article": "Chapeau"}
    t = _texte(rp.construire_fiche(a, "nouveautes"))
    assert "NOUVEAU LIMITED U ROBLOX" in t
    assert "stock épuisé" in t and "🟢 en vente" not in t


def test_D4_une_sortie_dit_MIS_EN_VENTE(panneau):
    a = {"asset_id": 76668098179041, "nom": "Telamon's Other Crafting Jewel",
         "prix": 1000, "collectionnable": 0, "hors_vente": 0,
         "cree_le": "2026-09-25T20:08:49Z", "sortie_le": _iso(0.5),
         "type_article": "Chapeau"}
    t = _texte(rp.construire_fiche(a, "nouveautes"))
    assert "Mis en vente" in t and "🟢 en vente" in t


def test_D5_la_fiche_ordinaire_ne_change_pas(panneau):
    a = _promotion(classe_avant=None)
    t = _texte(rp.construire_fiche(a, "bascules"))
    assert "Avant" not in t and "détecté à l'instant" in t


# ═══════════════════════════════════════════════════════════════════════════════
#  E — le flux Limited en trois parties
# ═══════════════════════════════════════════════════════════════════════════════

def test_E1_les_parties_couvrent_le_flux_mesure():
    """Mesuré le 27/09 : chapeaux 1 000, accessoires et équipements 836 (41 à
    47, 67, 72, 19), packs 161 — le flux unique (995) y est inclus en entier."""
    types = [t for _n, f in veille.PARTITIONS_LIMITED
             for t in f.get("AssetTypeIds", ())]
    packs = [t for _n, f in veille.PARTITIONS_LIMITED
             for t in f.get("BundleTypeIds", ())]
    assert sorted(types) == sorted([8, 41, 42, 43, 44, 45, 46, 47, 67, 72, 19])
    assert sorted(packs) == [1, 2, 3, 4, 5]
    assert veille.MAX_ARTICLES_SUIVIS >= 6000, (
        "la purge garde les plus récemment vus : trop bas, elle efface la "
        "classe des Limited dont la page va revenir")


def test_E2_une_valeur_multiple_devient_une_cle_repetee():
    p = veille._parametres({"SalesTypeFilter": 2, "AssetTypeIds": (41, 42, 19)})
    assert p.getall("AssetTypeIds") == [41, 42, 19] and p["SalesTypeFilter"] == 2
    p["Cursor"] = "abc"
    p["Cursor"] = "def"
    assert p.getall("Cursor") == ["def"]


@pytest.mark.asyncio
async def test_E3_la_requete_reelle_porte_le_filtre_de_la_partie(base, monkeypatch):
    """Ce que reçoit la session HTTP — pas ce qu'on croit lui passer."""
    await veille.init_db()
    recus = []

    class _S:
        def get(self, url, params=None, headers=None):
            recus.append(params)
            return _Reponse(200, {"data": [], "nextPageCursor": None})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _dodo(_s):
        return None

    monkeypatch.setattr(veille, "_ouvrir", lambda: _S())
    monkeypatch.setattr(veille.asyncio, "sleep", _dodo)
    await veille.relever_collectionnables(limite=120, pages=3)
    assert [r.getall("AssetTypeIds", None) or r.getall("BundleTypeIds")
            for r in recus] == [[8], [41, 42, 43, 44, 45, 46, 47, 67, 72, 19],
                                [1, 2, 3, 4, 5]]
    assert all(r["SalesTypeFilter"] == 2 and r["CreatorTargetId"] == 1
               for r in recus)
    _c, tours = await veille._curseur_lu(veille.SOURCE_RECENSEMENT)
    assert tours == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  F — le câblage
# ═══════════════════════════════════════════════════════════════════════════════

SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


def _corps(src: str, nom: str) -> str:
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


@pytest.mark.parametrize("fichier", ["bot.py", "roblox_panneau.py"])
def test_F1_chaque_porte_de_la_file_laisse_passer_une_promotion(fichier):
    """Un seul oubli, et la promotion d'un UGC Limited déjà annoncé se tait :
    TOUT appel à `publiable_dans` porte l'article (27/09)."""
    arbre = ast.parse((RACINE / fichier).read_text(encoding="utf-8"))
    appels = [n for n in ast.walk(arbre) if isinstance(n, ast.Call)
              and ast.unparse(n.func).endswith("publiable_dans")]
    assert appels, fichier
    sans = [ast.unparse(a) for a in appels
            if not any(k.arg == "article" for k in a.keywords)]
    assert not sans, sans


def test_F2_le_bilan_dit_ou_en_est_le_flux_en_parties():
    c = _corps(SRC_BOT, "veille_roblox_task")
    assert "SOURCE_RECENSEMENT" in c and "PARTITIONS_LIMITED" in c
    assert "UGC Limited devenu(s)" in c
