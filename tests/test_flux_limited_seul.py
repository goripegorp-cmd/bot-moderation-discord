"""« Uniquement les objets qui deviennent Limited, créés par Roblox. »

═══════════════════════════════════════════════════════════════════════════════
LA DEMANDE DU PROPRIÉTAIRE (23/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « je veux que tu affiches uniquement les objets qui deviennent limited qui
      sont uniquement créés par l'utilisateur Roblox. Ce qui est créé par
      d'autres joueurs ne m'intéresse pas. » — et le flux « tous créateurs »
      « consomme des données monstrueuses pour la plateforme ». Il ne veut
      plus qu'un salon « Nouveautés UGC » soit recréé.

CE QUI N'ÉTAIT PAS POSSIBLE AVANT
    Un flux n'avait qu'un SALON, avec repli sur le premier salon réglé. Pour
    ne garder que les Limited, il fallait vider le salon des nouveautés… et
    elles retombaient alors dans celui des Limited, par repli. Aucun réglage
    ne permettait de dire « ce flux-là, non ».

⚠️ LE PIÈGE ÉVITÉ EN ROUTE
    `actif()` testait « interrupteur ET salon des NOUVEAUTÉS ». Éteindre les
    nouveautés sans le toucher aurait arrêté TOUTE la veille, Limited compris,
    sans un mot — le contraire exact de la demande. `test_F4` le verrouille.
"""
from __future__ import annotations

import ast
import contextlib
from pathlib import Path

import aiosqlite
import pytest

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
#  F — les interrupteurs par flux
# ═══════════════════════════════════════════════════════════════════════════════

def test_F1_par_defaut_SEULS_les_passages_Limited_publient():
    """La consigne, appliquée sans que le propriétaire ait à cliquer."""
    c = dict(veille.CLES_DEFAUT)
    assert veille.flux_allume(c, "bascules") is True
    assert veille.flux_allume(c, "nouveautes") is False
    assert veille.flux_allume(c, "surveiller") is False


def test_F2_un_flux_ETEINT_n_a_pas_de_salon_REPLI_COMPRIS():
    """⚠️ LE CŒUR DE LA DEMANDE. Avant, les nouveautés sans salon propre
    retombaient dans celui des Limited : l'interrupteur doit l'empêcher."""
    c = dict(veille.CLES_DEFAUT, roblox_salon_bascules=111,
             roblox_salon_nouveautes=222)
    assert veille.salon_du_flux(c, "bascules") == 111
    assert veille.salon_du_flux(c, "nouveautes") == 0, "salon propre ignoré ?"
    c2 = dict(veille.CLES_DEFAUT, roblox_salon_bascules=111)
    assert veille.salon_du_flux(c2, "nouveautes") == 0, "repli vers les Limited"


def test_F3_un_flux_ALLUME_sans_salon_propre_garde_son_repli():
    """Le repli reste utile pour qui ne règle qu'un salon : on ne le retire
    qu'aux flux éteints."""
    c = dict(veille.CLES_DEFAUT, roblox_flux_nouveautes=True,
             roblox_salon_bascules=111)
    assert veille.salon_du_flux(c, "nouveautes") == 111


def test_F4_eteindre_les_nouveautes_n_arrete_PAS_la_veille():
    """⚠️ LE PIÈGE ÉVITÉ. L'ancien `actif()` exigeait le salon des nouveautés :
    avec elles éteintes, toute la veille se serait arrêtée, Limited compris."""
    corps = _fn(SRC_VEILLE, "actif")
    assert '"nouveautes"' not in corps and "'nouveautes'" not in corps
    assert "FLUX_OFFICIELS" in corps


@pytest.mark.asyncio
async def test_F4b_actif_est_VRAI_avec_les_seuls_Limited(monkeypatch):
    async def _cfg(_g):
        return {"roblox_veille_enabled": True, "roblox_salon_bascules": 111}
    monkeypatch.setattr(veille, "_cfg", _cfg)
    assert await veille.actif(1) is True


def test_F5_un_flux_INCONNU_ne_publie_jamais_par_repli():
    """Des fiches de l'ancien flux « ugc » pouvaient attendre en file : un
    nom inconnu tombant dans le salon officiel les aurait publiées sous
    l'identité des créations Roblox."""
    c = dict(veille.CLES_DEFAUT, roblox_salon_bascules=111)
    assert veille.salon_du_flux(c, "ugc") == 0
    assert veille.flux_allume(c, "ugc") is False
    assert "ugc" not in veille.FLUX_OFFICIELS


# ═══════════════════════════════════════════════════════════════════════════════
#  G — la garde « créé par Roblox », et la file
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


def _bascule(aid, createur=1):
    return {"asset_id": aid, "nom": f"art{aid}", "bascule_detectee": True,
            "classe": veille.CLASSE_LIMITED, "createur_id": createur}


async def _file(base):
    async with base["db"]() as db:
        async with db.execute("SELECT asset_id, flux, envoye_le FROM "
                              "roblox_transitions ORDER BY id") as cur:
            return await cur.fetchall()


@pytest.mark.asyncio
async def test_G1_un_Limited_cree_par_ROBLOX_entre_en_file(base):
    await veille.init_db()
    assert await veille.enfiler(1, _bascule(10), "bascules") is True


@pytest.mark.asyncio
async def test_G2_ce_que_cree_un_AUTRE_joueur_n_entre_JAMAIS(base):
    """« Ce qui est créé par d'autres joueurs ne m'intéresse pas. » Les
    requêtes filtrent déjà le créateur ; la garde tient même le jour où l'une
    d'elles l'oublierait — ce qu'avait fait le flux UGC, par construction."""
    await veille.init_db()
    assert await veille.enfiler(1, _bascule(11, createur=98765), "bascules") is False
    assert await _file(base) == []


@pytest.mark.asyncio
async def test_G3_un_flux_eteint_ou_inconnu_n_enfile_RIEN(base):
    await veille.init_db()
    a = {"asset_id": 12, "nom": "neuf", "createur_id": 1}
    assert await veille.enfiler(1, a, "nouveautes") is False, "nouveautés éteintes"
    assert await veille.enfiler(1, a, "ugc") is False, "flux retiré"
    base["cfg"]["roblox_flux_nouveautes"] = True
    assert await veille.enfiler(1, a, "nouveautes") is True, "rallumé : il repart"


@pytest.mark.asyncio
async def test_G4_eteindre_un_flux_RETIRE_son_arriere_et_rien_d_autre(base):
    """Un flux éteint ne laisse rien partir. Les fiches déjà ENVOYÉES et
    celles d'un flux allumé ne sont pas touchées."""
    await veille.init_db()
    async with base["db"]() as db:
        for aid, flux, envoye in ((1, "bascules", None), (2, "nouveautes", None),
                                  (3, "ugc", None), (4, "nouveautes", "2026-09-20")):
            await db.execute(
                "INSERT INTO roblox_transitions(guild_id, asset_id, flux, de, vers,"
                " detecte_le, charge, envoye_le) VALUES(?,?,?,?,?,?,?,?)",
                (1, aid, flux, "a", "b", "2026-09-23", "{}", envoye))
        await db.commit()
    n = await veille.oublier_flux_eteints(1, ["bascules"])
    assert n == 2, f"{n} fiche(s) retirée(s) au lieu de 2"
    restes = {(r[0], r[1]) for r in await _file(base)}
    assert restes == {(1, "bascules"), (4, "nouveautes")}, restes


def test_G5_le_menage_passe_AVANT_le_tirage_de_la_file():
    """Une fonction non appelée n'est pas opérationnelle. Dans la boucle ET
    dans « Relever maintenant » : les deux vident la file."""
    corps = _fn(SRC_BOT, "_publier_file_accessoires")
    assert corps.index("oublier_flux_eteints(") < corps.index("a_envoyer(")
    panneau = SRC_PANNEAU
    assert panneau.index("oublier_flux_eteints(") < panneau.index(
        "attente = await veille.a_envoyer(")


# ═══════════════════════════════════════════════════════════════════════════════
#  U — le flux UGC n'existe plus, nulle part
# ═══════════════════════════════════════════════════════════════════════════════

def test_U1_plus_aucun_releve_du_catalogue_de_TOUS_les_createurs():
    """C'était la consommation « monstrueuse ». Toute requête de catalogue du
    module doit poser le créateur Roblox."""
    for nom in ("relever_ugc", "qualite_ugc", "actif_ugc", "MAX_PAGES_UGC"):
        assert not hasattr(veille, nom), f"{nom} existe encore"
    arbre = ast.parse(SRC_VEILLE)
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_relever_catalogue"
                and n.args and isinstance(n.args[0], ast.Dict)):
            cles = {k.value for k in n.args[0].keys if isinstance(k, ast.Constant)}
            assert "CreatorTargetId" in cles, (
                f"un relevé de catalogue sans créateur : {sorted(cles)}")


def test_U2_le_role_Nouveautes_UGC_ne_peut_plus_etre_recree():
    """C'est la catégorie « ugc » des pings qui le créait à la première
    fiche. Sans elle, il ne revient jamais."""
    import roblox_pings
    assert "ugc" not in roblox_pings.CATEGORIES
    assert "ugc" not in roblox_pings.CLE_PAR_FLUX
    assert "Nouveautés UGC\", \"couleur\"" not in SRC_PINGS


def test_U3_le_panneau_n_offre_plus_AUCUN_reglage_UGC():
    """Un bouton pour un flux qui n'existe plus est un bouton qui ment
    (UI.md)."""
    for interdit in ("rblx_toggle_ugc", "rblx_seuils_ugc", "roblox_salon_ugc",
                     "_cb_toggle_ugc", "_cb_seuils_ugc"):
        assert interdit not in SRC_PANNEAU, f"{interdit} encore dans le panneau"


def test_U4_le_panneau_offre_UN_interrupteur_par_flux():
    """« que je puisse vraiment bien configurer le type de salon et tout
    proprement ». Un interrupteur par flux, et chaque ligne de salon dit si
    son flux publie, et où."""
    assert "rblx_flux_bascules" in SRC_PANNEAU
    assert "rblx_flux_nouveautes" in SRC_PANNEAU
    corps = _fn(SRC_PANNEAU, "_faire_flux")
    assert 'f"roblox_flux_{flux}"' in corps or "f'roblox_flux_{flux}'" in corps
    assert "(repli)" in SRC_PANNEAU and "éteint" in SRC_PANNEAU


def test_U5_publier_les_derniers_disparait_quand_les_nouveautes_sont_eteintes():
    """Il remet en file des NOUVEAUTÉS : flux éteint, il répondrait « rien à
    rattraper » — un bouton qui ment."""
    assert "([b_rattrap] if _nv else [])" in SRC_PANNEAU


def test_G6_le_publieur_VIDE_REELLEMENT_la_file_avant_de_tirer():
    """⚠️ EXÉCUTÉ, PAS LU. Le test de source (G5) survit à une mutation qui
    laisse le texte de l'appel en place mais le neutralise (`0 and await…`).
    Ici on exécute le vrai `_publier_file_accessoires` : le ménage doit être
    ATTENDU avant `a_envoyer`, avec la liste des flux ALLUMÉS du serveur."""
    import asyncio as _aio
    journal = []

    class _Cat:
        MAX_PUBLICATIONS_PAR_PASSAGE = 12
        FLUX_OFFICIELS = veille.FLUX_OFFICIELS

        async def config(self, _gid):
            return {"roblox_flux_bascules": True}

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
