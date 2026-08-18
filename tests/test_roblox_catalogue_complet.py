"""Le catalogue COMPLET, et la séparation des flux.

DEMANDE DU PROPRIÉTAIRE (16/08)
    « Tu relèves qu'une petite partie des accessoires créés par Roblox, je veux
    vraiment que tu aies absolument tout. […] Sépare bien les uns des autres. »

CE QUI CLOCHAIT
Le relevé faisait UNE requête de 60 articles et s'arrêtait là. Mesuré ce
jour-là : le catalogue des accessoires créés par Roblox fait **964 articles,
en 9 pages**. Le bot en voyait 60 — soit **6 %**.

MESURES DU 16/08, toutes contre l'API réelle :
  · catalogue complet, paginé  → 964 articles, 9 pages, `complet=True` ;
  · flux Limiteds, paginé      → 718 articles en 6 pages avant un HTTP 429 ;
  · Limiteds absents du catalogue général → **543**. Les deux relevés sont
    donc bien complémentaires, et aucun ne remplace l'autre.
  · un 429 arrive vers la 13ᵉ requête : les deux relevés enchaînés sans pause
    suffisante tronquaient le second.

Ces tests n'appellent pas le réseau : ils simulent la pagination.
"""
from __future__ import annotations

import pytest

import roblox_veille as veille


# ═══════════════════════════════════════════════════════════════════════════════
#  1. La pagination va au bout
# ═══════════════════════════════════════════════════════════════════════════════

class FausseAPI:
    """Un catalogue paginé, avec curseur — comme le vrai."""

    def __init__(self, total: int, par_page: int = 120, echoue_a: int = None):
        self.total = total
        self.par_page = par_page
        self.echoue_a = echoue_a      # numéro de page qui rend 429
        self.appels = 0

    def page(self, curseur):
        self.appels += 1
        if self.echoue_a and self.appels >= self.echoue_a:
            return 429, {}
        debut = int(curseur or 0)
        fin = min(debut + self.par_page, self.total)
        #  ⚠️ LES IDENTIFIANTS COMMENCENT À 1. `_normaliser` écarte `id <= 0`,
        #  et il a raison — un article d'identifiant 0 n'existe pas. Une
        #  première version de cette doublure numérotait à partir de 0 : le
        #  test comptait un article de moins et accusait le code à tort. Un
        #  faux objet doit porter TOUT ce que le vrai porte, y compris ses
        #  contraintes.
        data = [{"id": i + 1, "name": f"article {i + 1}", "itemType": "Asset",
                 "itemCreatedUtc": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
                 "itemRestrictions": [], "price": 100, "favoriteCount": 5}
                for i in range(debut, fin)]
        suivant = str(fin) if fin < self.total else None
        return 200, {"data": data, "nextPageCursor": suivant}


@pytest.fixture
def api_simulee(monkeypatch):
    """Remplace la couche HTTP, garde toute la logique de pagination."""
    etat = {}

    def _installer(faux: FausseAPI):
        etat["api"] = faux

        class _Reponse:
            def __init__(self, code, data):
                self.status = code
                self._data = data

            async def json(self):
                return self._data

            async def text(self):
                return "{}"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Session:
            def get(self, url, params=None, headers=None):
                code, data = faux.page((params or {}).get("Cursor"))
                return _Reponse(code, data)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(veille, "_ouvrir", lambda: _Session())

        async def _sante(source, code):
            return 0

        monkeypatch.setattr(veille, "_noter_sante", _sante)

        async def _dodo(_):
            return None

        monkeypatch.setattr(veille.asyncio, "sleep", _dodo)

    return _installer


@pytest.mark.asyncio
async def test_le_releve_parcourt_TOUTES_les_pages(api_simulee):
    """964 articles = le catalogue réel mesuré le 16/08."""
    api_simulee(FausseAPI(total=964))
    out = await veille.relever_nouveautes(limite=120)

    assert len(out["articles"]) == 964, (
        "le relevé doit aller au bout — 60 articles, c'était 6 % du catalogue")
    assert out["pages"] == 9
    assert out["complet"] is True


@pytest.mark.asyncio
async def test_un_429_en_cours_de_route_garde_ce_qui_est_deja_releve(api_simulee):
    """Un 429 n'est pas une panne : c'est notre propre débit.

    Jeter les six pages déjà obtenues ferait perdre un relevé presque complet.
    """
    api_simulee(FausseAPI(total=964, echoue_a=7))
    out = await veille.relever_nouveautes(limite=120)

    assert len(out["articles"]) == 720, "les 6 premières pages doivent rester"
    assert out["complet"] is False, "et le relevé doit se déclarer incomplet"
    assert out["code"] == 200, (
        "un 429 avec des pages déjà obtenues ne doit pas passer pour une panne")


@pytest.mark.asyncio
async def test_la_pagination_ne_boucle_pas_indefiniment(api_simulee):
    """Garde-fou : un curseur qui ne s'épuiserait jamais doit s'arrêter."""
    api_simulee(FausseAPI(total=10**6))
    out = await veille.relever_nouveautes(limite=120)

    assert out["pages"] == veille.MAX_PAGES_PAR_RELEVE
    assert out["complet"] is False


@pytest.mark.asyncio
async def test_les_doublons_entre_pages_sont_ecartes(api_simulee):
    """Le tri de l'API n'est pas strictement chronologique : un même article
    peut apparaître à cheval sur deux pages."""
    class APIQuiRepete(FausseAPI):
        def page(self, curseur):
            code, data = super().page(curseur)
            if code == 200 and data.get("data"):
                data["data"] = data["data"] + data["data"][:5]
            return code, data

    api_simulee(APIQuiRepete(total=240))
    out = await veille.relever_nouveautes(limite=120)

    ids = [a["asset_id"] for a in out["articles"]]
    assert len(ids) == len(set(ids)), "aucun doublon ne doit subsister"


@pytest.mark.asyncio
async def test_les_deux_releves_sont_distincts_et_pagines(api_simulee):
    """Ils ne se remplacent pas : 543 Limiteds sont absents du catalogue
    général (mesuré le 16/08). Mais ils ne paginent pas pareil : le général
    va au BOUT (c'est là que se voient les bascules) ; le flux Limited, non
    trié par date et réservé à la détection, s'arrête à
    `MAX_PAGES_COLLECTIONNABLES` (18/08)."""
    api_simulee(FausseAPI(total=300))
    a = await veille.relever_nouveautes(limite=120)
    assert a["pages"] == 3 and len(a["articles"]) == 300 and a["complet"]

    api_simulee(FausseAPI(total=300))
    b = await veille.relever_collectionnables(limite=120)
    assert b["pages"] == veille.MAX_PAGES_COLLECTIONNABLES
    assert len(b["articles"]) == 120 * veille.MAX_PAGES_COLLECTIONNABLES
    assert b["complet"] is False, "il reste des pages, et le relevé le DIT"


def test_la_pause_entre_releves_est_plus_longue_que_celle_entre_pages():
    """16 requêtes enchaînées à 2 s d'écart ont produit un 429 réel."""
    assert veille.PAUSE_ENTRE_RELEVES > veille.PAUSE_ENTRE_APPELS * 3


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Les flux restent séparés
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def base_memoire(monkeypatch):
    """Une mémoire des publications, sans base de données."""
    sortis: dict[tuple, set] = {}

    async def _flux(guild_id, asset_id):
        return set(sortis.get((guild_id, asset_id), set()))

    async def _marquer(guild_id, asset_id, flux):
        sortis.setdefault((guild_id, asset_id), set()).add(flux)

    monkeypatch.setattr(veille, "flux_deja_sortis", _flux)
    return _marquer


@pytest.mark.asyncio
async def test_un_article_ne_sort_pas_deux_fois_dans_le_meme_flux(base_memoire):
    await base_memoire(1, 42, "bascules")
    assert await veille.publiable_dans(1, 42, "bascules") is False


@pytest.mark.asyncio
async def test_une_bascule_bloque_les_flux_plus_faibles(base_memoire):
    """Un Limited retiré de la vente coche « devenu » ET « à surveiller ».
    Sans priorité, il sortait dans les deux salons."""
    await base_memoire(1, 42, "bascules")

    assert await veille.publiable_dans(1, 42, "surveiller") is False
    assert await veille.publiable_dans(1, 42, "nouveautes") is False


@pytest.mark.asyncio
async def test_une_nouveaute_NEMPECHE_PAS_une_bascule_plus_tard(base_memoire):
    """Une nouveauté annoncée en janvier qui passe Limited en mars est une
    VRAIE nouvelle : elle doit pouvoir sortir."""
    await base_memoire(1, 42, "nouveautes")

    assert await veille.publiable_dans(1, 42, "bascules") is True
    assert await veille.publiable_dans(1, 42, "surveiller") is True


@pytest.mark.asyncio
async def test_un_article_jamais_sorti_passe_partout(base_memoire):
    for flux in ("bascules", "surveiller", "nouveautes"):
        assert await veille.publiable_dans(1, 99, flux) is True


@pytest.mark.asyncio
async def test_la_lecture_est_fail_closed_si_la_base_casse(monkeypatch):
    """Dans le doute, on ne publie pas : mieux vaut rater une fiche que noyer
    le salon de doublons."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _boum():
        raise RuntimeError("base indisponible")
        yield

    monkeypatch.setattr(veille, "_get_db", _boum)
    monkeypatch.setattr(veille, "_log", lambda *a: None)

    assert await veille.flux_deja_sortis(1, 42) == set(veille.PRIORITE_FLUX)
    assert await veille.publiable_dans(1, 42, "bascules") is False


def test_lordre_de_priorite_est_celui_annonce():
    p = veille.PRIORITE_FLUX
    assert p["bascules"] > p["surveiller"] > p["nouveautes"]
