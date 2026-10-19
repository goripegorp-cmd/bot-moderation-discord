"""20/10/2026 (revue) : chaque image postee etait telechargee deux fois (OCR puis NSFW)."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))


def test_I1_une_image_un_telechargement_pour_les_deux_analyses():
    ns = {"asyncio": asyncio}
    exec(next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "_lecteur_partage"), ns)  # noqa: S102
    telechargements = []

    class Image:
        def __init__(self, i):
            self.id = i

        async def read(self):
            telechargements.append(self.id)
            await asyncio.sleep(0.01)
            return b"png%d" % self.id
    a, b = Image(1), Image(2)
    lire = ns["_lecteur_partage"](2)

    async def scenario():
        x, y = await asyncio.gather(lire(a), lire(a))
        z = await lire(b)
        return x, y, z, await lire(b)
    assert asyncio.run(scenario()) == (b"png1", b"png1", b"png2", b"png2")
    assert telechargements == [1, 2]
    assert ns["_lecteur_partage"](1) is None, "une seule analyse : lecture directe, rien de garde"


def test_I2_les_deux_analyses_recoivent_le_lecteur():
    src = ast.unparse(ARBRE)
    assert "_ocr_scam_check(msg, immune=user_immune, lire=_lire)" in src
    assert "_nsfw_image_check(msg, lire=_lire)" in src
    assert src.count("await (lire(a) if lire else a.read())") == 2


def test_I3_une_reaction_ordinaire_ne_touche_pas_la_base():
    """Roles-reactions : messages lus une fois ; aucun code n'ecrit la table (sinon : invalider)."""
    import contextlib
    import re
    from types import SimpleNamespace
    requetes = []

    @contextlib.asynccontextmanager
    async def get_db():
        class Curseur:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def fetchall(self):
                return [(55,)]

            async def fetchone(self):
                return None

        class Db:
            def execute(self, sql, *a):
                requetes.append(sql)
                return Curseur()
        yield Db()
    ns = {"get_db": get_db, "bot": SimpleNamespace(user=SimpleNamespace(id=0))}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in ("_rr_messages", "_rr_messages_connus", "_handle_reaction_role"):
            exec(ast.unparse(n), ns)  # noqa: S102

    async def scenario():
        for mid in (1, 2, 3, 55):
            await ns["_handle_reaction_role"](SimpleNamespace(user_id=9, guild_id=1, message_id=mid, emoji="x"),
                                              add=True)
    asyncio.run(scenario())
    assert len(requetes) == 2, requetes  # la liste, une fois ; puis le seul message concerne
    racine = Path(__file__).resolve().parent.parent
    for f in racine.glob("*.py"):
        assert not re.search(r"(INSERT|REPLACE|DELETE)[^;]{0,40}reaction_roles", f.read_text(encoding="utf-8")), f
