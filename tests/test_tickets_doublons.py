"""20/10/2026 (revue) : deux clics rapprochés ouvraient deux tickets ; deux fermetures simultanées
(double envoi, deux membres du staff, fermeture pour inactivité) envoyaient deux logs et deux MP."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == nom)


def test_D1_deux_clics_rapproches_un_seul_ticket():
    ouverts = []

    async def corps(i, pid, ans=None):
        await asyncio.sleep(0.05)            # création du salon, écriture en base…
        ouverts.append(pid)
        return "salon", None
    ns = {"_tickets_en_creation": set(), "_create_ticket_corps": corps}
    exec(_source("create_ticket"), ns)  # noqa: S102 — code du dépôt
    i = SimpleNamespace(guild=SimpleNamespace(id=1), user=SimpleNamespace(id=2))

    async def scenario():
        return await asyncio.gather(ns["create_ticket"](i, "p"), ns["create_ticket"](i, "p"))
    a, b = asyncio.run(scenario())
    assert ouverts == ["p"] and a == ("salon", None) and b[0] is None and "cours" in b[1]
    assert not ns["_tickets_en_creation"], "le verrou se libère (un ticket plus tard reste possible)"


def test_D2_deux_fermetures_simultanees_une_seule_passe():
    fermes, ouverts = [], {101}

    async def corps(guild, ch, tk, closer, reason, inactif_jours=0):
        await asyncio.sleep(0.05)
        fermes.append(reason)
        ouverts.discard(ch.id)

    async def get_ticket(cid):
        return {"id": 1} if cid in ouverts else None
    ns = {"_tickets_en_fermeture": set(), "_fermer_ticket_corps": corps, "get_ticket": get_ticket}
    exec(_source("_fermer_ticket"), ns)  # noqa: S102 — code du dépôt
    ch = SimpleNamespace(id=101)

    async def scenario():
        r = await asyncio.gather(ns["_fermer_ticket"](None, ch, {}, None, "Résolu"),
                                 ns["_fermer_ticket"](None, ch, {}, None, "7 jours sans message", 7))
        return r, await ns["_fermer_ticket"](None, ch, {}, None, "encore")
    (a, b), c = asyncio.run(scenario())
    assert fermes == ["Résolu"] and (a, b, c) == (True, False, False)
