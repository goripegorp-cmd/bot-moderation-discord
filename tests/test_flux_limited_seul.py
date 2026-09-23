"""Nouveautés Roblox + passages en Limited, dans un salon — jamais un hors-vente.

═══════════════════════════════════════════════════════════════════════════════
LA CONSIGNE (23/09/2026, « la plus importante »)
═══════════════════════════════════════════════════════════════════════════════
    « Je veux que tu m'affiches les nouveaux accessoires créés par Roblox […]
      et, dans la même catégorie, les accessoires qui viennent de passer
      Limited — en vente, retirés de la vente, et d'un seul coup ils passent
      Limited. […] Cela m'arrive très souvent que tu m'affiches des
      accessoires enlevés de la vente comme potentiellement limited. Je ne
      veux pas de ça. »

CE QUE LA MESURE A MONTRÉ (API réelle, 23/09)
  · 107 des 118 dernières créations de Roblox sont HORS VENTE et NON Limited,
    dont 105 à 0-1 R$ : des récompenses d'événement (« Crown of Petals »,
    « Team Create Workstation »…). C'étaient elles, les fiches « nouvel
    accessoire · 🔴 retiré de la vente ».
  · Le tri « récents » est l'ordre de CRÉATION : un vieil article qui passe
    Limited ne remonte jamais en tête. Seule une SURVEILLANCE ciblée le voit.
  · Sur 238 articles Roblox hors vente, 28 seulement ont un vrai prix
    (« Sakura Antlers » 9 000 R$, « Arcane Fedora » 20 000 R$…) : une requête
    suffit à tous les surveiller.
"""
from __future__ import annotations

import ast
import contextlib
from pathlib import Path

import aiosqlite
import pytest

import roblox_panneau as rp
import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_VEILLE = (RACINE / "roblox_veille.py").read_text(encoding="utf-8")
SRC_PANNEAU = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
SRC_PINGS = (RACINE / "roblox_pings.py").read_text(encoding="utf-8")


def _fn(src: str, nom: str) -> str:
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  F — les flux
# ═══════════════════════════════════════════════════════════════════════════════

def test_F1_nouveautes_ET_passages_Limited_publient_par_defaut():
    """« les nouveaux accessoires créés par Roblox […] et, dans la même
    catégorie, les accessoires qui viennent de passer Limited »."""
    c = dict(veille.CLES_DEFAUT)
    assert veille.flux_allume(c, "nouveautes") is True
    assert veille.flux_allume(c, "bascules") is True


def test_F1b_le_flux_a_surveiller_n_EXISTE_plus():
    """⚠️ « je ne veux pas de ça ». Les « indices » sur des articles retirés
    de la vente ne peuvent plus sortir par aucun chemin."""
    assert veille.FLUX_OFFICIELS == ("nouveautes", "bascules")
    c = dict(veille.CLES_DEFAUT, roblox_salon_bascules=111)
    assert veille.flux_allume(c, "surveiller") is False
    assert veille.salon_du_flux(c, "surveiller") == 0
    assert "roblox_salon_surveiller" not in veille.CLES_DEFAUT
    assert "roblox_flux_surveiller" not in veille.CLES_DEFAUT


def test_F2_un_flux_ETEINT_n_a_pas_de_salon_REPLI_COMPRIS():
    c = dict(veille.CLES_DEFAUT, roblox_flux_nouveautes=False,
             roblox_salon_bascules=111)
    assert veille.salon_du_flux(c, "bascules") == 111
    assert veille.salon_du_flux(c, "nouveautes") == 0


def test_F3_un_flux_ALLUME_sans_salon_propre_garde_son_repli():
    c = dict(veille.CLES_DEFAUT, roblox_salon_bascules=111)
    assert veille.salon_du_flux(c, "nouveautes") == 111


@pytest.mark.asyncio
async def test_F4_eteindre_les_nouveautes_n_arrete_PAS_la_veille(monkeypatch):
    """L'ancien `actif()` exigeait le salon des nouveautés : les éteindre
    aurait arrêté toute la veille, Limited compris."""
    async def _cfg(_g):
        return {"roblox_veille_enabled": True, "roblox_flux_nouveautes": False,
                "roblox_salon_bascules": 111}
    monkeypatch.setattr(veille, "_cfg", _cfg)
    assert await veille.actif(1) is True


def test_F5_un_flux_INCONNU_ne_publie_jamais_par_repli():
    c = dict(veille.CLES_DEFAUT, roblox_salon_bascules=111)
    for inconnu in ("ugc", "surveiller", "n_importe_quoi"):
        assert veille.salon_du_flux(c, inconnu) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  G — l'entrée de la file : les règles d'or
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "flux.db"
    cfg = {}

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return cfg

    async def _db_set(_g, k, v):
        cfg[k] = v
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                 log=lambda *a, **k: None)
    return {"cfg": cfg, "db": _get_db}


def _article(aid, **kw):
    a = {"asset_id": aid, "nom": f"art{aid}", "type_article": "Chapeau",
         "item_type": "Asset", "prix": 400, "collectionnable": 0,
         "hors_vente": 0, "favoris": 0, "cree_le": "2026-09-23T08:00:00Z",
         "createur_id": 1}
    a.update(kw)
    return a


async def _file(base):
    async with base["db"]() as db:
        async with db.execute("SELECT asset_id, flux FROM roblox_transitions"
                              " ORDER BY id") as cur:
            return await cur.fetchall()


@pytest.mark.asyncio
async def test_G1_une_nouveaute_EN_VENTE_entre_en_file(base):
    await veille.init_db()
    assert await veille.enfiler(1, _article(10), "nouveautes") is True


@pytest.mark.asyncio
async def test_G2_un_passage_en_Limited_entre_meme_HORS_VENTE(base):
    """Un Limited se revend entre joueurs : être hors vente est son état
    normal. C'est précisément l'événement attendu."""
    await veille.init_db()
    b = _article(11, hors_vente=1, collectionnable=1, bascule_detectee=True,
                 classe=veille.CLASSE_LIMITED)
    assert await veille.enfiler(1, b, "bascules") is True


@pytest.mark.asyncio
async def test_G3_hors_vente_et_NON_Limited_ne_sort_JAMAIS(base):
    """⚠️ LA RÈGLE D'OR DU 23/09. Mesuré : 105 des 118 dernières créations de
    Roblox sont des récompenses d'événement à 0-1 R$, hors vente — c'étaient
    elles, les fiches « 🔴 retiré de la vente » lues comme « peut-être
    Limited ». Aucun flux ne les laisse passer."""
    await veille.init_db()
    evenement = _article(12, prix=1, hors_vente=1, collectionnable=0)
    retire = _article(13, prix=9000, hors_vente=1, collectionnable=0)
    for a in (evenement, retire):
        for flux in ("nouveautes", "bascules"):
            assert await veille.enfiler(1, a, flux) is False, (a["asset_id"], flux)
    assert await _file(base) == []


@pytest.mark.asyncio
async def test_G4_ce_que_cree_un_AUTRE_joueur_n_entre_JAMAIS(base):
    await veille.init_db()
    assert await veille.enfiler(1, _article(14, createur_id=98765),
                                "nouveautes") is False


@pytest.mark.asyncio
async def test_G5_un_flux_eteint_n_enfile_rien_et_repart_rallume(base):
    await veille.init_db()
    base["cfg"]["roblox_flux_nouveautes"] = False
    assert await veille.enfiler(1, _article(15), "nouveautes") is False
    base["cfg"]["roblox_flux_nouveautes"] = True
    assert await veille.enfiler(1, _article(15), "nouveautes") is True


@pytest.mark.asyncio
async def test_G6_eteindre_un_flux_RETIRE_son_arriere_et_rien_d_autre(base):
    await veille.init_db()
    async with base["db"]() as db:
        for aid, flux, envoye in ((1, "bascules", None), (2, "nouveautes", None),
                                  (3, "surveiller", None), (4, "nouveautes", "2026-09-20")):
            await db.execute(
                "INSERT INTO roblox_transitions(guild_id, asset_id, flux, de, vers,"
                " detecte_le, charge, envoye_le) VALUES(?,?,?,?,?,?,?,?)",
                (1, aid, flux, "a", "b", "2026-09-23", "{}", envoye))
        await db.commit()
    assert await veille.oublier_flux_eteints(1, ["bascules"]) == 2
    async with base["db"]() as db:
        async with db.execute("SELECT asset_id FROM roblox_transitions"
                              " ORDER BY asset_id") as cur:
            assert [r[0] for r in await cur.fetchall()] == [1, 4]


def test_G7_le_publieur_VIDE_REELLEMENT_la_file_avant_de_tirer():
    """EXÉCUTÉ, PAS LU : un test de source survit à `0 and await …`."""
    import asyncio as _aio
    journal = []

    class _Cat:
        MAX_PUBLICATIONS_PAR_PASSAGE = 12
        FLUX_OFFICIELS = veille.FLUX_OFFICIELS

        async def config(self, _gid):
            return {"roblox_flux_bascules": True, "roblox_flux_nouveautes": False}

        def flux_allume(self, c, f):
            return veille.flux_allume(c, f)

        async def oublier_flux_eteints(self, gid, allumes):
            journal.append(("oubli", gid, tuple(allumes)))
            return 0

        async def a_envoyer(self, gid, limite=12):
            journal.append(("tirage", gid))
            return []

        def __getattr__(self, nom):
            async def _rien(*a, **k):
                return {} if nom in ("etat_file",) else []
            return _rien

    class _G:
        id = 42

    ns = {"roblox_module": _Cat(), "asyncio": _aio, "_veille_tour": 0,
          "print": lambda *a, **k: None}
    exec(_fn(SRC_BOT, "_publier_file_accessoires"), ns)   # noqa: S102 — code du dépôt
    _aio.run(ns["_publier_file_accessoires"]([_G()], 12, pause_fiches=0))
    assert journal[:2] == [("oubli", 42, ("bascules",)), ("tirage", 42)], journal


# ═══════════════════════════════════════════════════════════════════════════════
#  W — la liste de surveillance des retirés de la vente
# ═══════════════════════════════════════════════════════════════════════════════

async def _poser(base, lignes):
    await veille.init_db()
    async with base["db"]() as db:
        for (aid, prix, coll, hv, it, cree) in lignes:
            await db.execute(
                "INSERT INTO roblox_articles(asset_id, nom, type_article, prix,"
                " collectionnable, hors_vente, favoris, cree_le, vu_le, signature,"
                " item_type) VALUES(?,?,?,?,?,?,0,?,?,?,?)",
                (aid, f"a{aid}", "Chapeau", prix, coll, hv, cree,
                 "2026-09-23T09:00:00", "s", it))
        await db.commit()


@pytest.mark.asyncio
async def test_W1_on_surveille_les_RETIRES_avec_un_vrai_prix_et_rien_d_autre(base):
    """« en vente, retirés de la vente, et d'un seul coup ils passent
    Limited ». Les récompenses à 0-1 R$ n'ont jamais été en vente."""
    await _poser(base, [
        (1, 9000, 0, 1, "Asset", "2026-08-12"),   # Sakura Antlers : surveillé
        (2, 20000, 0, 1, "Asset", "2026-06-24"),  # Arcane Fedora : surveillé
        (3, 1, 0, 1, "Asset", "2026-09-21"),      # récompense d'événement
        (4, 0, 0, 1, "Asset", "2026-09-21"),      # récompense gratuite
        (5, 400, 1, 1, "Asset", "2026-09-01"),    # déjà Limited
        (6, 400, 0, 0, "Asset", "2026-09-01"),    # encore en vente
        (7, 400, 0, 1, "Bundle", "2026-09-01"),   # un pack : autre espace d'ids
        (8, 400, 0, 1, None, "2026-09-01"),       # type inconnu : prudence
    ])
    assert await veille.liste_de_surveillance() == [1, 2], "le plus récent d'abord"


@pytest.mark.asyncio
async def test_W2_la_liste_tient_en_UNE_requete(base):
    await _poser(base, [(i, 500, 0, 1, "Asset", f"2026-01-{(i % 28) + 1:02d}")
                        for i in range(1, 200)])
    assert len(await veille.liste_de_surveillance()) == veille.LIMITE_SURVEILLANCE == 120


@pytest.mark.asyncio
async def test_W3_le_type_technique_est_ENREGISTRE_et_jamais_efface(base):
    """Sans lui, la liste resterait vide pour toujours — et un fiche sans
    type ne doit pas effacer celui qu'on connaît déjà."""
    await veille.init_db()
    await veille.comparer_et_enregistrer([_article(30, hors_vente=1)])
    sans_type = _article(30, hors_vente=1)
    sans_type.pop("item_type")
    await veille.comparer_et_enregistrer([sans_type])
    async with base["db"]() as db:
        async with db.execute("SELECT item_type FROM roblox_articles"
                              " WHERE asset_id=30") as cur:
            assert (await cur.fetchone())[0] == "Asset"
    assert await veille.liste_de_surveillance() == [30]


# ═══════════════════════════════════════════════════════════════════════════════
#  C — « dans la même catégorie »
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_C1_les_deux_flux_vont_dans_LE_salon_des_Limited(base):
    base["cfg"].update({"roblox_salon_bascules": 111, "roblox_salon_nouveautes": 222})
    r = await veille.unifier_salons(1)
    assert r["fait"] and r["salon"] == 111
    assert base["cfg"]["roblox_salon_nouveautes"] == 111
    assert base["cfg"]["roblox_salons_unifies"]


@pytest.mark.asyncio
async def test_C2_un_seul_salon_regle_devient_celui_des_deux(base):
    base["cfg"].update({"roblox_salon_nouveautes": 222})
    await veille.unifier_salons(1)
    assert base["cfg"]["roblox_salon_bascules"] == 222


@pytest.mark.asyncio
async def test_C3_l_unification_n_a_lieu_QU_UNE_fois(base):
    """Un choix fait ensuite dans le panneau ne doit plus être écrasé."""
    base["cfg"].update({"roblox_salon_bascules": 111, "roblox_salons_unifies": "x",
                        "roblox_salon_nouveautes": 333})
    r = await veille.unifier_salons(1)
    assert not r["fait"] and base["cfg"]["roblox_salon_nouveautes"] == 333


def test_C4_l_unification_est_APPELEE_au_demarrage():
    assert "unifier_salons(g.id)" in _fn(SRC_BOT, "_travaux_de_demarrage")


# ═══════════════════════════════════════════════════════════════════════════════
#  P — le panneau et la fiche disent vrai
# ═══════════════════════════════════════════════════════════════════════════════

def test_P1_UN_seul_reglage_de_salon_ecrit_les_DEUX_cles():
    assert rp.CLES_DU_CHAMP[rp.CHAMP_ACCESSOIRES] == (
        "roblox_salon_nouveautes", "roblox_salon_bascules")
    assert any(c[0] == rp.CHAMP_ACCESSOIRES for c in rp.RobloxPanelV2.CHAMPS)
    assert not any(c[0] in ("roblox_salon_nouveautes", "roblox_salon_bascules")
                   for c in rp.RobloxPanelV2.CHAMPS), "deux réglages pour un salon"
    assert "for _k in CLES_DU_CHAMP.get(cle, (cle,))" in _fn(SRC_PANNEAU, "_faire_salon")


def test_P2_plus_aucune_trace_des_indices():
    """Le texte d'aide promettait encore des « indices » sur le retrait de la
    vente : un texte qui ment."""
    assert "surveiller" not in rp.PLATEFORME and "surveiller" not in rp.NOMS_FLUX
    assert "**indice**" not in SRC_PANNEAU
    assert "🔴 **retiré de la vente**" not in SRC_PANNEAU


def _texte(vue) -> str:
    return str(vue.to_components())


@pytest.fixture
def panneau():
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


def test_P3_une_creation_qui_sort_DEJA_Limited_se_dit_NOUVEAU_LIMITED(panneau):
    a = _article(40, collectionnable=1, classe=veille.CLASSE_LIMITED, prix=50000)
    assert "NOUVEAU LIMITED ROBLOX" in _texte(rp.construire_fiche(a, "nouveautes"))


def test_P4_un_Limited_hors_vente_se_REVEND_il_n_est_pas_retire(panneau):
    """⚠️ « 🔴 retiré de la vente » faisait lire « peut-être Limited »."""
    b = _article(41, collectionnable=1, hors_vente=1, bascule_detectee=True,
                 classe=veille.CLASSE_LIMITED)
    t = _texte(rp.construire_fiche(b, "bascules"))
    assert "revente entre joueurs" in t and "retiré de la vente" not in t


def test_P5_une_nouveaute_en_vente_le_dit(panneau):
    t = _texte(rp.construire_fiche(_article(42), "nouveautes"))
    assert "NOUVEL ACCESSOIRE ROBLOX" in t and "en vente" in t


# ═══════════════════════════════════════════════════════════════════════════════
#  U — le flux UGC reste retiré
# ═══════════════════════════════════════════════════════════════════════════════

def test_U1_plus_aucun_releve_du_catalogue_de_TOUS_les_createurs():
    for nom in ("relever_ugc", "qualite_ugc", "actif_ugc", "MAX_PAGES_UGC"):
        assert not hasattr(veille, nom), f"{nom} existe encore"
    for n in ast.walk(ast.parse(SRC_VEILLE)):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_relever_catalogue"
                and n.args and isinstance(n.args[0], ast.Dict)):
            cles = {k.value for k in n.args[0].keys if isinstance(k, ast.Constant)}
            assert "CreatorTargetId" in cles, sorted(cles)


def test_U2_le_role_Nouveautes_UGC_ne_peut_plus_etre_recree():
    import roblox_pings
    assert "ugc" not in roblox_pings.CATEGORIES
    assert "ugc" not in roblox_pings.CLE_PAR_FLUX


# ═══════════════════════════════════════════════════════════════════════════════
#  E — le relais par l'économie (production du 23/09 : fiches refusées, 429)
# ═══════════════════════════════════════════════════════════════════════════════

class _Rep:
    def __init__(self, status, data=None):
        self.status, self._d = status, data or {}
        self.headers = {}

    async def json(self, content_type=None):
        return self._d

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Sess:
    def __init__(self, par_id=None, post_status=200):
        self.par_id, self.post_status, self.urls = par_id or {}, post_status, []

    def get(self, url, **kw):
        self.urls.append(url)
        aid = int(url.rstrip("/").split("/")[-2])
        st, d = self.par_id.get(aid, (200, {}))
        return _Rep(st, d)

    def post(self, url, **kw):
        self.urls.append(url)
        return _Rep(self.post_status, {"data": []})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_E1_le_relais_ne_rend_QUE_les_articles_devenus_Limited(base, monkeypatch):
    """⚠️ Il complète l'article par la base : l'économie ne donne ni favoris ni
    description, et faire passer les autres par la comparaison les écraserait."""
    await _poser(base, [(1, 9000, 0, 1, "Asset", "2026-08-12"),
                        (2, 20000, 0, 1, "Asset", "2026-06-24")])
    async with base["db"]() as db:
        await db.execute("UPDATE roblox_articles SET favoris=4321 WHERE asset_id=2")
        await db.commit()
    sess = _Sess({1: (200, {"IsLimited": False, "IsForSale": False}),
                  2: (200, {"IsLimited": True, "IsForSale": False, "Name": "Arcane Fedora",
                            "Creator": {"Id": 1}})})
    monkeypatch.setattr(veille, "_ouvrir", lambda: sess)
    monkeypatch.setattr(veille.asyncio, "sleep", _pas_de_sommeil)
    devenus, vus = await veille.verifier_par_economie([1, 2])
    assert vus == 2 and [d["asset_id"] for d in devenus] == [2]
    d = devenus[0]
    assert d["collectionnable"] == 1 and d["classe"] == veille.CLASSE_LIMITED
    assert d["favoris"] == 4321 and d["prix"] == 20000, "la base n'a pas complété l'article"
    assert all(u.startswith("https://economy.roblox.com/v2/assets/") for u in sess.urls)


async def _pas_de_sommeil(_d):
    return None


@pytest.mark.asyncio
async def test_E2_le_relais_S_ARRETE_si_l_economie_refuse_aussi(base, monkeypatch):
    """Marteler un second seau saturé ne rendrait pas de quota."""
    await _poser(base, [(1, 9000, 0, 1, "Asset", "2026-08-12")])
    sess = _Sess({1: (429, {})})
    monkeypatch.setattr(veille, "_ouvrir", lambda: sess)
    monkeypatch.setattr(veille.asyncio, "sleep", _pas_de_sommeil)
    devenus, vus = await veille.verifier_par_economie([1, 2, 3])
    assert devenus == [] and vus == 0 and len(sess.urls) == 1


@pytest.mark.asyncio
async def test_E3_un_429_du_seau_des_fiches_n_ECRIT_PAS_de_ligne(base, monkeypatch):
    """Deux lignes par minute dans les journaux (mesuré le 23/09) : c'est le
    bruit d'erreurs demandé à couper. Le code reste lisible par l'appelant."""
    lignes = []
    veille.setup(get_db=base["db"], cfg=None, db_set=None,
                 log=lambda *a, **k: lignes.append(" ".join(map(str, a))))
    monkeypatch.setattr(veille, "_ouvrir", lambda: _Sess(post_status=429))
    assert await veille.fiches_par_ids([1, 2, 3]) == []
    assert veille.DERNIER_CODE_FICHES == 429
    assert not [l for l in lignes if "429" in l], lignes
