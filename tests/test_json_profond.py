"""28/10/2026 — la CI (Python 3.13, comme la production) lisait un corps JSON piège très imbriqué que Python 3.11
refusait : le site refuse lui-même toute imbrication au-delà de `PROFONDEUR_MAX`, partout (administration, candidat)."""
from __future__ import annotations

import asyncio
import json

import pytest

import tableau


def _imbrique(n):
    x = {}
    for _ in range(n):
        x = {"a": x}
    return x


def test_J1_la_profondeur():
    assert not tableau._trop_profond(_imbrique(tableau.PROFONDEUR_MAX - 1))
    assert tableau._trop_profond(_imbrique(tableau.PROFONDEUR_MAX + 1))
    assert tableau._trop_profond({"l": [_imbrique(40)]}), "dans une liste aussi"
    assert not tableau._trop_profond({"titre": "x", "liens": [{"nom": "a", "url": "b"}]})


def test_J2_le_corps_trop_imbrique_est_illisible():
    class Req:
        async def read(self):
            return json.dumps(_imbrique(60)).encode()
    with pytest.raises(tableau._Refus) as e:
        asyncio.run(tableau._lire_json(Req(), 100_000))
    assert "illisible" in str(e.value.args) or getattr(e.value, "message", "") == "Corps illisible."
