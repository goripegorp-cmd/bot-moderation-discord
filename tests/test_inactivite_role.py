"""19/10/2026 : « un système d'inactivité en fonction d'un rôle que j'aurai moi-même prédéfini »
— seuls les membres du « Rôle attribué » (menu Rell Seas) sont suivis."""
from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path

import aiosqlite

import activite

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_R1_hors_du_role_rien_n_est_ecrit(tmp_path):
    chemin = tmp_path / "a.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def cfg(_g):
        return {}

    async def db_set(*_a):
        return True

    async def suivi(_g, uid):
        return uid == 7

    async def scenario():
        activite.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None, suivi=suivi)
        await activite.init_db()
        activite._marques_du_jour.clear()
        await activite.marquer_actif(1, 7, activite.SOURCE_MESSAGE)
        await activite.marquer_actif(1, 8, activite.SOURCE_MESSAGE)
        async with get_db() as db:
            async with db.execute("SELECT user_id FROM activite_jours") as c:
                return [r[0] for r in await c.fetchall()]
    try:
        assert asyncio.run(scenario()) == [7]
    finally:
        activite.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=print)


def test_R2_le_role_vient_du_menu_rell_seas():
    corps = next(ast.unparse(n) for n in ast.walk(ast.parse(SRC))
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "_activite_suivi")
    role = Obj(id=55)
    membre = Obj(roles=[role])
    g = Obj(get_member=lambda uid: membre if uid == 7 else None)
    conf = {"rellseas_role": 55}

    async def cfg(_g):
        return conf

    ns = {"cfg": cfg, "bot": Obj(get_guild=lambda _g: g)}
    exec(corps, ns)  # noqa: S102 — code du dépôt
    assert asyncio.run(ns["_activite_suivi"](1, 7)) is True
    assert asyncio.run(ns["_activite_suivi"](1, 8)) is False
    conf["rellseas_role"] = 0
    assert asyncio.run(ns["_activite_suivi"](1, 7)) is False, "sans rôle choisi : personne"
    assert "suivi=_activite_suivi" in SRC
    assert "afk_role_config" not in SRC
