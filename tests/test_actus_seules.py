"""19/10/2026 : « tu m'enlèves cette mécanique [des accessoires] […] tu ne me gardes que les
news ». La veille ne relève plus que l'actualité Roblox."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

import roblox_news
import roblox_panneau as rp
import roblox_pings

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fonction(nom):
    return next(ast.unparse(n) for n in ast.walk(ast.parse(SRC))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def test_N1_plus_rien_des_accessoires():
    for m in ("roblox_veille", "roblox_cartes", "roblox_marche", "roblox_commandes"):
        assert not (RACINE / f"{m}.py").exists(), m
        assert f"import {m}" not in SRC, m
    for nom in ("eclaireur_task", "veille_marche_task", "_publier_file_accessoires",
                "_cartes_cadeaux", "_surveiller_retires"):
        assert f"def {nom}(" not in SRC, nom
    assert not {"limited", "nouveaux"} & set(roblox_pings.CATEGORIES)
    assert "_retirer_tables_mortes" in _fonction("_travaux_de_demarrage")
    assert "roblox_marche_tete" in SRC.split("_TABLES_MORTES = frozenset(")[1].split("})")[0]


def test_N2_un_passage_releve_enfile_publie_et_dit_les_pannes():
    appels = []
    sources = [{"cle": "a"}, {"cle": "b"}, {"cle": "c"}]
    reponses = {"a": {"code": 200, "billets": [1, 2, 3]}, "b": {"code": 503},
                "c": {"sautee": True, "code": None}}

    async def actif(gid):
        return gid == 1

    async def relever(src, forcer=False):
        appels.append(("relever", src["cle"], forcer))
        return reponses[src["cle"]]

    async def enfiler(guildes, rel):
        appels.append(("enfiler", [g.id for g in guildes]))
        return {"enfiles": 2}

    async def publier(guildes):
        appels.append(("publier",))
        return {"publies": 2}

    async def rien(*_a, **_k):
        appels.append(("purge",))

    async def dormir(_s):
        return None

    ns = {"bot": Obj(guilds=[Obj(id=1), Obj(id=2)]), "asyncio": Obj(sleep=dormir),
          "roblox_news_module": Obj(actif=actif, SOURCES=sources, relever=relever,
                                    purger=rien, purger_file_actu=rien),
          "_enfiler_billets": enfiler, "_publier_file_actualites": publier,
          "_logerr": lambda *a, **k: appels.append(("ERREUR", a))}
    exec(_fonction("_relever_actus"), ns)  # noqa: S102 — code du dépôt
    res = asyncio.run(ns["_relever_actus"]())
    assert res == {"lus": 3, "enfiles": 2, "publies": 2, "pannes": 1}
    assert all(a[2] is False for a in appels if a[0] == "relever"), "la boucle respecte la cadence"
    appels.clear()
    asyncio.run(ns["_relever_actus"](forcer=True))
    assert all(a[2] is True for a in appels if a[0] == "relever"), "« Relever maintenant » relève tout"
    assert "roblox_ui.set_relever(lambda: _relever_actus(forcer=True))" in SRC
    assert ("enfiler", [1]) in appels and ("publier",) in appels
    assert appels.count(("purge",)) == 2


def test_N3_la_boucle_garde_la_sentinelle_puis_les_actus():
    corps = _fonction("veille_roblox_task")
    assert corps.index("_battre_sentinelle()") < corps.index("_relever_actus()")
    assert "roblox_module" not in corps


def test_N4_l_ordre_de_publication_vient_des_actus():
    b = [{"cree_le": "2026-10-0%d" % k} for k in (3, 1, 2)]
    assert [x["cree_le"] for x in roblox_news.ordonner_publication(b, 2)] == \
        ["2026-10-02", "2026-10-03"]
    assert "roblox_news_module.ordonner_publication(" in _fonction("_enfiler_billets")


@pytest.mark.asyncio
async def test_N5_le_bouton_relever_passe_par_la_vraie_veille(monkeypatch):
    rendus = []

    async def releve():
        return {"lus": 12, "enfiles": 3, "publies": 3, "pannes": 1}

    async def rendre(self, i, *, edit=True):
        rendus.append(self._dernier)

    async def defer():
        return None

    monkeypatch.setattr(rp.RobloxPanelV2, "render_to", rendre)
    rp.set_relever(releve)
    try:
        vue = rp.RobloxPanelV2(Obj(id=1), Obj(id=1))
        await vue._cb_relever(Obj(response=Obj(defer=defer)))
    finally:
        rp.set_relever(None)
    assert rendus == ["🔄 Relevé en cours…",
                      "✅ `12` billet(s) lu(s) · `3` nouveau(x) · `3` publié(s) · "
                      "⚠️ `1` source(s) en panne"]
    assert "roblox_ui.set_relever(lambda: _relever_actus(forcer=True))" in SRC
