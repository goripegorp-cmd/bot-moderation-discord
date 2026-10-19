"""20/10/2026 (audit 1 #13) : chaque changement de membre lisait le journal d'audit, meme fait par le
bot ; Discord pousse desormais chaque entree avec son auteur exact."""
from __future__ import annotations

import ast
import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import discord

from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
A = discord.AuditLogAction


def _handler(journal):
    async def log_event(_bot, _g, ev, **k):
        journal.append((ev, k.get("description", "")))
    ns = {"discord": discord, "bot": Obj(event=lambda f: f), "_logerr": lambda *a, **k: print(a),
          "ulogger2026": Obj(log_event=log_event, EventType=Obj(MEMBER_UPDATE="maj", MOD_TIMEOUT="excl",
                                                                MOD_UNMUTE="levee"))}
    exec(next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "on_audit_log_entry_create"),  # noqa: S102
         ns)
    return ns["on_audit_log_entry_create"]


def _entree(action, auteur, avant, apres, cible=7):
    membre = Obj(id=cible, bot=False, mention=f"<@{cible}>")
    g = Obj(id=1, me=Obj(id=99), get_member=lambda i: membre if i == cible else Obj(id=i, mention=f"<@{i}>"))
    return Obj(guild=g, user_id=auteur, user=None, action=action, target=Obj(id=cible), reason=None,
               changes=Obj(before=avant, after=apres))


def test_P1_les_actions_humaines_sont_journalisees_celles_du_bot_non():
    journal = []
    h = _handler(journal)
    role = Obj(id=5, mention="<@&5>")

    async def scenario():
        await h(_entree(A.member_role_update, 99, NS(roles=[]), NS(roles=[role])))  # le bot lui-meme
        await h(_entree(A.member_role_update, 3, NS(roles=[]), NS(roles=[role])))
        await h(_entree(A.member_update, 7, NS(nick="a"), NS(nick="b")))  # son propre pseudo
        await h(_entree(A.member_update, 3, NS(nick="a"), NS(nick="b")))
        fin = discord.utils.utcnow() + timedelta(hours=1)
        await h(_entree(A.member_update, 3, NS(timed_out_until=None), NS(timed_out_until=fin)))
        await h(_entree(A.member_update, 3, NS(timed_out_until=fin), NS(timed_out_until=None)))
    asyncio.run(scenario())
    assert [e for e, _ in journal] == ["maj", "maj", "excl", "levee"], journal
    assert "➕ <@&5>" in journal[0][1] and "`a` → `b`" in journal[1][1]


def test_P2_plus_de_lecture_du_journal_d_audit_par_changement_de_membre():
    corps = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "on_member_update")
    assert "member_role_update" not in corps and "_audit_actor" not in corps
