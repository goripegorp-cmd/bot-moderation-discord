"""20/10/2026 (audit #10) : une lecture ratée de la base rendait {} et cfg() gardait 30 s un serveur
« vierge » : salon de logs « non défini » (un second 📋logs pouvait naître), installations rejouées."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import time
from pathlib import Path

import pytest

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
NOMS = ("ConfigCache", "_config_cache", "validate_id", "_config_secours", "ConfigIllisible",
        "_lire_config", "db_get", "cfg")


def _bot(base):
    """`base` : {gid: config} ; base["panne"] = True fait échouer toute lecture."""
    @contextlib.asynccontextmanager
    async def get_db():
        if base.get("panne"):
            raise TimeoutError("pool saturé")

        class Curseur:
            def __init__(self, gid):
                self.gid = gid

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def fetchone(self):
                return (json.dumps(base[self.gid]),) if self.gid in base else None

        class Db:
            def execute(self, _sql, params):
                return Curseur(params[0])
        yield Db()
    erreurs = []
    ns = {"asyncio": asyncio, "json": json, "time": time, "get_db": get_db,
          "_logerr": lambda ou, ex, **k: erreurs.append(ou)}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, (ast.Assign, ast.AnnAssign)) and hasattr(n, "targets") else getattr(getattr(n, "target", None), "id", None))
        if nom in NOMS:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    assert all(k in ns for k in NOMS), [k for k in NOMS if k not in ns]
    return ns, erreurs


def test_C1_base_illisible_la_derniere_copie_sert_et_n_est_pas_gardee():
    base = {1: {"log_channel": 42}}
    ns, erreurs = _bot(base)

    async def scenario():
        assert (await ns["cfg"](1))["log_channel"] == 42
        ns["_config_cache"].clear()                    # 30 s plus tard
        base["panne"] = True
        c = await ns["cfg"](1)
        assert c["log_channel"] == 42, "pas un serveur vierge"
        assert ns["_config_cache"].get(1) is None, "la copie de secours n'est pas mise en cache"
        base["panne"] = False
        base[1] = {"log_channel": 43}
        assert (await ns["cfg"](1))["log_channel"] == 43, "on relit la base dès qu'elle répond"
    asyncio.run(scenario())
    assert erreurs == ["config.lecture"]


def test_C2_sans_aucune_copie_on_s_arrete_au_lieu_d_inventer_des_defauts():
    ns, erreurs = _bot({"panne": True})

    async def scenario():
        with pytest.raises(ns["ConfigIllisible"]):
            await ns["cfg"](5)
        assert ns["_config_cache"].get(5) is None
    asyncio.run(scenario())


def test_C3_un_serveur_sans_config_reste_un_serveur_sans_config():
    ns, _ = _bot({})

    async def scenario():
        assert (await ns["cfg"](9))["anti_phishing"] == 1
        assert await ns["db_get"](9) == {}, "les défauts de cfg ne fuient pas dans la config brute"
        assert ns["_config_secours"][9] == {}
    asyncio.run(scenario())


def test_C4_une_ecriture_met_la_copie_de_secours_a_jour():
    corps = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "db_set")
    assert "_config_secours[gid] = dict(data)" in corps
    assert "DB GET ERROR" not in ast.unparse(ARBRE), "plus de {} silencieux"
