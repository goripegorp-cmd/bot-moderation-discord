"""20/10/2026 (audit 6 #12) : un envoi d'actualite rate comptait deux essais ; un billet abandonne
n'etait relance que par un clic."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import roblox_news as news
from conftest_discord import base


def test_E1_un_echec_apres_reservation_compte_une_fois(tmp_path):
    get_db, cfg, db_set, _ = base(tmp_path)
    news.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None)

    async def scenario():
        await news.init_db()
        assert await news.enfiler_actu(1, {"topic_id": "t1", "titre": "Maj"})
        for _ in range(news.MAX_ESSAIS_ACTU):
            (ligne,) = await news.actus_a_envoyer(1)
            assert await news.reserver_actu(ligne["id"], ligne["essais"])
            await news.noter_echec_actu(ligne["id"], "salon interdit", compter=False)
        assert await news.actus_a_envoyer(1) == [], "abandonne apres 5 vrais essais, pas 3"
        assert await news.relancer_actus_abandonnees(1) == 1
        return await news.actus_a_envoyer(1)
    assert len(asyncio.run(scenario())) == 1


def test_E2_relance_automatique_une_fois_par_heure():
    src = ast.unparse(ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")))
    assert "if _page_live_due(f'actus_relance:{g.id}', 3600):" in src
    assert "'publier_actu a rendu False', compter=False)" in src


def test_E3_un_billet_deja_connu_ne_fait_plus_lire_son_corps(monkeypatch):
    """Apres un redemarrage, les billets deja publies etaient relus et retraduits un par un."""
    lus = []

    class Rep:
        def __init__(self, url):
            self.url, self.status, self.headers = url, 200, {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def json(self):
            return {"post_stream": {"posts": [{"cooked": "<p>x</p>"}]}}

    class Session:
        def get(self, url):
            lus.append(url)
            return Rep(url)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def enrichir(b, cooked, langue):
        return b

    async def rien(*_a):
        return None
    monkeypatch.setattr(news, "_ouvrir", lambda: Session())
    monkeypatch.setattr(news, "_normaliser", lambda data, dom: [{"topic_id": 11, "titre": "a"},
                                                                  {"topic_id": 12, "titre": "b"}])
    monkeypatch.setattr(news.contenu, "enrichir_billet", enrichir)
    monkeypatch.setattr(news.asyncio, "sleep", rien)
    monkeypatch.setattr(news, "_cache_forum", {})
    out = {}
    asyncio.run(news._relever_discourse(news.SOURCES[0], out, connus=frozenset({"11"})))
    assert [u for u in lus if "/t/" in u] == [f"{news.DOMAINE_FORUM}/t/12.json"]
    assert [b["topic_id"] for b in out["billets"]] == [12]
