"""20/10/2026 (audit 6 #11) : apres un 5xx ou un delai depasse, le webhook renvoyait par
channel.send alors que Discord avait souvent deja garde le premier message : deux annonces."""
from __future__ import annotations

import ast
import asyncio
from datetime import timedelta
from pathlib import Path

import discord

from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))


def _envoi(historique, erreur):
    envois = []

    class Webhook:
        async def send(self, **kw):
            raise erreur

    class Salon:
        id, name, guild = 5, "videos", Obj(id=1)

        def history(self, **k):
            async def gen():
                for m in historique:
                    yield m
            return gen()

        async def send(self, **kw):
            envois.append(kw)
            return "renvoye"

    async def get_webhook(*a):
        return Webhook()
    ns = {"discord": discord, "bot": Obj(user=Obj(id=99)), "timedelta": timedelta, "_webhook_cache": {},
          "WEBHOOK_PROFILES": {}, "_BOT_AVATAR_URL": "a", "get_webhook": get_webhook,
          "_logerr": lambda *a, **k: None, "print": lambda *a, **k: None}
    for n in ARBRE.body:
        if getattr(n, "name", "") in ("_deja_poste", "webhook_send"):
            exec(ast.unparse(n), ns)  # noqa: S102 — code du depot
    e = discord.Embed(title="Nouvelle video", url="https://youtu.be/abc")
    return asyncio.run(ns["webhook_send"](Salon(), "youtube", embed=e)), envois


def _recu(url):
    return Obj(webhook_id=7, author=Obj(id=1), content="", embeds=[Obj(url=url, title="t")])


def test_W1_un_5xx_apres_reception_ne_double_pas_l_annonce():
    r, envois = _envoi([_recu("https://youtu.be/abc")], discord.HTTPException(Obj(status=503, reason="x"), "x"))
    assert envois == [] and r.embeds[0].url == "https://youtu.be/abc"


def test_W2_un_delai_depasse_sans_reception_renvoie_bien():
    r, envois = _envoi([_recu("https://youtu.be/autre")], asyncio.TimeoutError())
    assert r == "renvoye" and len(envois) == 1


def test_W3_un_refus_403_renvoie_sans_chercher():
    r, envois = _envoi([_recu("https://youtu.be/abc")], discord.Forbidden(Obj(status=403, reason="x"), "x"))
    assert r == "renvoye", "403 : le webhook n'a rien publie"
