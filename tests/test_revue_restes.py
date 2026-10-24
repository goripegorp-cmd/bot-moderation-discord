"""Revue complète du 24/10/2026 — les restes signalés par la revue des panneaux : les publications des abonnements
en carte V2, le tableau de bord de modération qui répond proprement après un acquittement."""
from __future__ import annotations

import asyncio
from pathlib import Path

import discord

import mod_dashboard
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def test_X1_les_publications_des_abonnements_sont_des_cartes():
    assert "chan.send(content, view=vue" not in SRC, "plus de message texte classique"
    assert "msg = await chan.send(view=carte_embed(e, boutons, haut=\" \".join(haut))," in SRC
    assert "e.set_image(url=str(post.thumbnail_url))" in SRC, "la vignette du post"


def test_X2_le_tableau_de_bord_repond_apres_un_acquittement(monkeypatch):
    envoyes = []

    async def suivi(**kw):
        envoyes.append(kw)

    async def interdit(**kw):
        raise AssertionError("send_message après un defer : Discord refuse")
    i = Obj(guild=Obj(id=1), response=Obj(is_done=lambda: True, send_message=interdit), followup=Obj(send=suivi))

    async def stats(_gid, days=30):
        return {}

    async def audit(_gid):
        return []
    monkeypatch.setattr(mod_dashboard, "_collect_stats", stats)
    monkeypatch.setattr(mod_dashboard, "_collect_staff_audit", audit)
    monkeypatch.setattr(mod_dashboard, "_build_layout", lambda *a, **k: None)
    assert asyncio.run(mod_dashboard.show(i)) is False
    assert envoyes == [{"ephemeral": True, "content": "❌ Tableau de bord indisponible pour le moment."}]

    def casse(*a, **k):
        raise RuntimeError("secret interne")
    monkeypatch.setattr(mod_dashboard, "_build_layout", casse)
    assert asyncio.run(mod_dashboard.show(i)) is False
    assert "secret interne" not in envoyes[-1]["content"], "aucun détail technique au membre"
    _ = discord
