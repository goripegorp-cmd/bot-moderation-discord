"""19/10/2026 : le salon des actualités passe en salon d'annonces. Un message n'y atteint
les serveurs abonnés que publié — Discord en accepte 10 par heure et par salon."""
from __future__ import annotations

import asyncio

import roblox_panneau as rp


class Salon:
    def __init__(self, annonces=True):
        self.id, self._annonces, self.publies = 5, annonces, []

    def is_news(self):
        return self._annonces

    def get_partial_message(self, mid):
        salon = self

        class Msg:
            async def publish(self):
                salon.publies.append(mid)
        return Msg()


def test_D1_un_salon_ordinaire_ne_publie_rien():
    s = Salon(annonces=False)
    assert asyncio.run(rp._diffuser(s, 1)) is False and s.publies == []


def test_D2_dix_par_heure_puis_on_attend(monkeypatch):
    rp._publications.clear()
    horloge = [1000.0]
    monkeypatch.setattr(rp.time, "monotonic", lambda: horloge[0])
    s = Salon()
    res = [asyncio.run(rp._diffuser(s, i)) for i in range(1, 13)]
    assert res == [True] * 10 + [False] * 2 and s.publies == list(range(1, 11))
    horloge[0] += 3601
    assert asyncio.run(rp._diffuser(s, 99)) is True and s.publies[-1] == 99


def test_D3_chaque_envoi_reussi_est_diffuse():
    import inspect
    src = inspect.getsource(rp._envoyer)
    assert src.count("await _diffuser(salon,") == 3
