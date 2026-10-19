"""20/10/2026 (revue) : /signaler n'avait aucun délai (le salon d'alertes de la direction pouvait
être inondé) et les deux commandes répondaient « ✅ transmis » même quand rien n'était parti."""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

import discord

from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
NOMS = ("_signalements", "_SIGNALEMENT_CD", "_SIGNALEMENT_RATE", "_signalement_recent", "_signalement_note",
        "signaler_cmd")


def _commande(reponses):
    appels = []

    async def log_event(*a, **k):
        appels.append(k.get("description"))
        return reponses.pop(0)
    ns = {"discord": discord, "time": time, "bot": Obj(user=Obj(id=0)), "_logerr": lambda *a, **k: None,
          "ulogger2026": Obj(log_event=log_event, EventType=Obj(SEC_ESCALATION="sec.escalation"))}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else
                                           getattr(getattr(n, "target", None), "id", None))
        if nom in NOMS:
            if hasattr(n, "decorator_list"):
                n.decorator_list = []
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns, appels


def _interaction(recus):
    async def rien(*a, **k):
        return None

    async def envoyer(texte, **k):
        recus.append(texte)
    return Obj(guild=Obj(id=1), user=Obj(id=2, mention="@moi"), channel=Obj(mention="#chat"),
               response=Obj(defer=rien), followup=Obj(send=envoyer))


def test_S1_un_echec_le_dit_et_n_empeche_pas_de_reessayer():
    ns, appels = _commande([None, Obj(id=9)])
    recus = []

    async def scenario():
        await ns["signaler_cmd"](_interaction(recus), "il m'a demandé mon mot de passe")
        await ns["signaler_cmd"](_interaction(recus), "il m'a demandé mon mot de passe")
    asyncio.run(scenario())
    assert recus[0] == ns["_SIGNALEMENT_RATE"] and "ticket" in recus[0]
    assert recus[1].startswith("✅") and len(appels) == 2


def test_S2_un_second_signalement_immediat_attend():
    ns, appels = _commande([Obj(id=9), Obj(id=10)])
    recus = []

    async def scenario():
        for _ in range(3):
            await ns["signaler_cmd"](_interaction(recus), "arnaque en MP")
    asyncio.run(scenario())
    assert recus[0].startswith("✅") and all(r.startswith("⏳") for r in recus[1:])
    assert len(appels) == 1, "le salon d'alertes ne reçoit qu'un signalement"


def test_S3_le_signalement_vocal_suit_les_memes_regles():
    corps = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "signaler_vocal_cmd")
    assert "_signalement_recent(_voice_report_cd" in corps and "_signalement_note(_voice_report_cd" in corps
    assert corps.index("envoye is None") < corps.index("_signalement_note(")
