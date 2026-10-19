"""19/10/2026 (audit) : le verrouillage anti-raid supprimait TOUS les liens d'invitation (jamais
recréés, alors que « /bouclier off » annonçait « arrivées rétablies »), et sa fin supprimait tout rôle
« Vérification » — le rôle de quarantaine : chaque membre isolé était libéré d'un coup."""
from __future__ import annotations

import asyncio

import raid_detector as R
from conftest_discord import base


class Serveur:
    id = 1

    def __init__(self):
        self.edits, self.supprimes, self.crees = [], [], []
        self.me = type("Moi", (), {"guild_permissions": type("P", (), {"manage_guild": True})()})()
        self.roles = [type("Role", (), {"name": "Vérification", "delete": self._sup})()]
        self.channels = []

    async def _sup(self, **k):
        self.supprimes.append("role")

    async def edit(self, **kw):
        self.edits.append(kw.get("invites_disabled"))

    async def invites(self):
        raise AssertionError("on ne touche plus aux liens d'invitation")

    async def create_role(self, **kw):
        self.crees.append(kw)


def test_B1_les_invitations_sont_en_pause_puis_reprennent_et_la_quarantaine_reste(tmp_path):
    get_db, *_ = base(tmp_path)
    R.setup(None, get_db, None, {})

    async def scenario():
        await R.init_db()
        g = Serveur()
        out = await R.run_lockdown(g, 30)
        assert out["invites_disabled"] is True and not out["errors"]
        assert await R.end_lockdown(g)
        return g
    g = asyncio.run(scenario())
    assert g.edits == [True, False], "pause, puis reprise"
    assert not g.crees and not g.supprimes, "aucun rôle créé ni supprimé (la quarantaine reste)"
