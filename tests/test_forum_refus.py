"""Le DevForum refuse le serveur (HTTP 202) : moins de requêtes, ralentir, le dire.

═══════════════════════════════════════════════════════════════════════════════
LE JOURNAL RAILWAY DU 24/09/2026 (matin)
═══════════════════════════════════════════════════════════════════════════════
    [roblox_news annonces] HTTP 202
    [roblox_news alertes] HTTP 202
    … les cinq catégories à tour de rôle, 36 lignes en quelques minutes.

L'éclaireur d'actualités interrogeait 2 catégories toutes les 30 s et les 3
autres toutes les 90 s (~8 600 requêtes par jour, une seule IP de serveur).
Le bilan, lui, disait « 0 source(s) en panne » : tout 2xx passait pour un
succès. Depuis un poste résidentiel, les mêmes URL répondent 200, et la
catégorie parente `updates` rend les quatre catégories en UNE requête.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import roblox_news as news

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC_BOT)


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "news.db"
    lignes = []

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return {}

    async def _db_set(_g, k, v):
        return True

    news.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
               log=lambda *a, **k: lignes.append(" ".join(map(str, a))))
    news.FORUM.update(refus_depuis=None, code=None, refus=0)
    return {"db": _get_db, "lignes": lignes}


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux réseau fidèle
# ═══════════════════════════════════════════════════════════════════════════════

class _Rep:
    def __init__(self, status, data=None, entetes=None):
        self.status, self._d, self.headers = status, data, dict(entetes or {})

    async def json(self, content_type=None):
        return self._d

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Sess:
    def __init__(self, reponses):
        self.reponses, self.urls = list(reponses), []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.reponses.pop(0) if self.reponses else _Rep(404)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _sujet(tid, cat, jours=0):
    quand = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    return {"id": tid, "title": f"Sujet {tid}", "category_id": cat,
            "created_at": quand, "excerpt": "…", "tags": []}


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Un 202 n'est pas un succès
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F1_un_202_compte_comme_un_ECHEC(base):
    """Le bilan disait « 0 source(s) en panne » pendant des heures de 202."""
    await news.init_db()
    assert await news._noter_sante("annonces", 200) == 0
    assert await news._noter_sante("annonces", 202) == 1
    assert await news._noter_sante("annonces", 202) == 2
    async with base["db"]() as db:
        async with db.execute("SELECT dernier_code FROM roblox_news_sante"
                              " WHERE cle='annonces'") as cur:
            assert (await cur.fetchone())[0] == 202


# ═══════════════════════════════════════════════════════════════════════════════
#  2. La lecture groupée
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F2_UNE_requete_les_quatre_categories_chacune_son_domaine(base, monkeypatch):
    data = {"topic_list": {"topics": [
        _sujet(9001, 36), _sujet(9002, 62), _sujet(9003, 193),
        _sujet(9004, 90), _sujet(9005, 999)]}}
    #  Les corps sont déjà en cache : pas de lecture `/t/{id}.json` ici.
    for tid in (9001, 9002, 9003, 9004):
        news._cache_forum[tid] = {"topic_id": tid, "titre": f"Sujet {tid}"}
    sess = _Sess([_Rep(200, data)])
    monkeypatch.setattr(news, "_ouvrir", lambda: sess)
    try:
        r = await news.relever_mises_a_jour(leger=True)
    finally:
        for tid in (9001, 9002, 9003, 9004):
            news._cache_forum.pop(tid, None)
    assert r["code"] == 200 and len(sess.urls) == 1, sess.urls
    assert sess.urls[0] == f"{news.DOMAINE_FORUM}/c/updates.json?order=created&per_page=10"
    assert sorted(b["topic_id"] for b in r["billets"]) == [9001, 9002, 9003, 9004], (
        "un sujet d'une catégorie non suivie est entré")


@pytest.mark.asyncio
async def test_F2b_chaque_billet_porte_le_domaine_de_SA_categorie(base, monkeypatch):
    data = {"topic_list": {"topics": [_sujet(9101, 36), _sujet(9102, 193)]}}
    vus = {}

    async def _enrichir(b, cooked, langue):
        vus[b["topic_id"]] = b["domaine"]
        return dict(b)

    async def _pas_de_sommeil(*_a):
        return None

    monkeypatch.setattr(news.contenu, "enrichir_billet", _enrichir)
    monkeypatch.setattr(news.asyncio, "sleep", _pas_de_sommeil)
    sess = _Sess([_Rep(200, data), _Rep(200, {"post_stream": {"posts": [{"cooked": "x"}]}}),
                  _Rep(200, {"post_stream": {"posts": [{"cooked": "y"}]}})])
    monkeypatch.setattr(news, "_ouvrir", lambda: sess)
    try:
        await news.relever_mises_a_jour(leger=True)
    finally:
        news._cache_forum.pop(9101, None)
        news._cache_forum.pop(9102, None)
    domaines = {s["cle"]: s["domaine"] for s in news.SOURCES}
    assert vus == {9101: domaines["annonces"], 9102: domaines["alertes"]}, vus


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le refus : une ligne quand il commence, une quand il cesse
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F3_trois_refus_UNE_ligne_puis_UNE_ligne_a_la_reprise(base, monkeypatch):
    """⚠️ 36 lignes en quelques minutes le 24/09. La première ligne porte les
    en-têtes qui disent QUI refuse — c'est ce qui départagera pare-feu et
    forum à la prochaine lecture du journal."""
    refus = _Rep(202, None, {"x-amzn-waf-action": "challenge", "content-length": "0"})
    sess = _Sess([refus, refus, refus,
                  _Rep(200, {"topic_list": {"topics": []}})])
    monkeypatch.setattr(news, "_ouvrir", lambda: sess)
    for _ in range(3):
        r = await news.relever_mises_a_jour(leger=True)
        assert r["code"] == 202
    lignes = [l for l in base["lignes"] if "forum" in l]
    assert len(lignes) == 1 and "HTTP 202" in lignes[0] and "challenge" in lignes[0], lignes
    assert news.forum_refuse() and news.FORUM["refus"] == 3
    await news.relever_mises_a_jour(leger=True)
    lignes = [l for l in base["lignes"] if "forum" in l]
    assert len(lignes) == 2 and "répond de nouveau" in lignes[1] and "3 refus" in lignes[1]
    assert not news.forum_refuse()


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le VRAI éclaireur d'actualités : une requête, et il ralentit
# ═══════════════════════════════════════════════════════════════════════════════

def _src_sans_decorateur(nom):
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == nom:
            n = ast.copy_location(ast.AsyncFunctionDef(
                name=n.name, args=n.args, body=n.body, decorator_list=[],
                returns=None, type_comment=None, type_params=[]), n)
            return ast.unparse(ast.fix_missing_locations(n))
    raise AssertionError(nom)


def _constante(nom):
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(nom)


class _FauxNews:
    def __init__(self, codes):
        self.codes, self.appels = list(codes), 0

    async def actif(self, _gid):
        return True

    async def identifiants_connus_actus(self):
        return set()

    async def relever_mises_a_jour(self, leger=False):
        self.appels += 1
        code = self.codes.pop(0) if self.codes else 200
        return {"code": code, "billets": ([{"topic_id": 1, "titre": "t"}]
                                          if code == 200 else [])}


def _eclaireur(codes):
    faux = _FauxNews(codes)
    E = {"amorce": True, "vus": set(), "passages": 0, "erreurs": 0, "billets": 0,
         "publies": 0, "dernier_passage": None, "dernier_signal": None,
         "palier": 0, "pause_jusqu": None, "sautes": 0}
    journal = []

    async def _enfiler(_g, rel):
        return {"enfiles": len(rel["billets"])}

    async def _publier(_g, etiquette=None):
        return {"publies": 1}

    ns = {"_ECLAIREUR_ACTU": E, "roblox_news_module": faux,
          "bot": type("B", (), {"guilds": [type("G", (), {"id": 1})()]})(),
          "_enfiler_billets": _enfiler, "_publier_file_actualites": _publier,
          "_age_s": lambda _d: 10, "datetime": datetime, "timezone": timezone,
          "timedelta": timedelta,
          "print": lambda *a, **k: journal.append(" ".join(map(str, a)))}
    for nom in ("ECLAIREUR_ACTU_PAUSES", "ECLAIREUR_ACTU_BATTEMENT"):
        ns[nom] = _constante(nom)
    exec(_src_sans_decorateur("eclaireur_actu_task"), ns)   # noqa: S102
    return ns, E, faux, journal


def test_F4_UNE_requete_par_passage():
    ns, E, faux, journal = _eclaireur([200])
    asyncio.run(ns["eclaireur_actu_task"]())
    assert faux.appels == 1 and E["publies"] == 1, (faux.appels, E)


def test_F5_refuse_il_RALENTIT_puis_reprend_son_rythme():
    """Pendant la pause, pas une requête ; à la réponse, le rythme revient."""
    ns, E, faux, _j = _eclaireur([202, 200])
    asyncio.run(ns["eclaireur_actu_task"]())
    assert E["palier"] == 1 and E["pause_jusqu"] is not None
    attendu = ns["ECLAIREUR_ACTU_PAUSES"][1]
    reste = (E["pause_jusqu"] - datetime.now(timezone.utc)).total_seconds()
    assert attendu - 5 <= reste <= attendu, reste
    asyncio.run(ns["eclaireur_actu_task"]())
    assert faux.appels == 1 and E["sautes"] == 1, "il a frappé pendant la pause"
    E["pause_jusqu"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    asyncio.run(ns["eclaireur_actu_task"]())
    assert faux.appels == 2 and E["palier"] == 0 and E["pause_jusqu"] is None


def test_F6_des_refus_en_serie_allongent_la_pause_jusqu_au_plafond():
    ns, E, faux, _j = _eclaireur([202] * 10)
    for _ in range(8):
        E["pause_jusqu"] = None
        asyncio.run(ns["eclaireur_actu_task"]())
    assert E["palier"] == len(ns["ECLAIREUR_ACTU_PAUSES"]) - 1
    assert faux.appels == 8


def test_F7_le_bilan_DIT_le_refus_du_forum():
    blocs = [ast.unparse(n) for n in ast.walk(ARBRE) if isinstance(n, ast.IfExp)
             and "le forum refuse le serveur depuis" in ast.unparse(n)]
    assert blocs and "forum_refuse()" in blocs[0], "le bilan tait le refus"
