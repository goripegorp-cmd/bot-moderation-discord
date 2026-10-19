"""19/10/2026 : « vérifie tous les messages qui sont envoyés en privé aux gens pour éviter
toute cause de messages privés et de spam »."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    return next(ast.unparse(n) for n in ast.walk(ast.parse(SRC))
                if isinstance(n, ast.AsyncFunctionDef) and n.name == nom)


def test_P1_un_meme_mp_au_plus_une_fois_par_6_h():
    horloge = [datetime(2026, 10, 19, 12, tzinfo=timezone.utc)]
    recus = []

    class Membre:
        id = 7

        async def send(self, texte):
            recus.append(texte)

    ns = {"_MP_ENVOYES": {}, "now": lambda: horloge[0], "discord": discord,
          "_evict_if_big": lambda d, n: None}
    exec(_source("_mp_une_fois"), ns)  # noqa: S102 — code du dépôt
    m = Membre()
    for _ in range(5):
        asyncio.run(ns["_mp_une_fois"](m, "hub_role:1", "rôle requis"))
    asyncio.run(ns["_mp_une_fois"](m, "hub_role:2", "autre hub"))
    horloge[0] += timedelta(hours=6, seconds=1)
    asyncio.run(ns["_mp_une_fois"](m, "hub_role:1", "rôle requis"))
    assert recus == ["rôle requis", "autre hub", "rôle requis"]


def test_P2_plus_de_mp_pour_un_probleme_de_staff_ni_en_double():
    assert "il me manque **« Gérer les rôles »**" not in SRC, "affaire du staff, pas du membre"
    assert "Tes statistiques d'activité sur" not in SRC, "l'avertissement le dit déjà"
    assert SRC.count('await _mp_une_fois(') == 2
