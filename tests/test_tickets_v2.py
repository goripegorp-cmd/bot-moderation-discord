"""24/10/2026 : « Components V2 partout » — les derniers menus des tickets passent en V2 ; et la direction garde la
vue d'un ticket pris en charge (« la direction et le fondateur voient les tickets », 22/10)."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
import pytest

import tickets_fils
import visuels
from conftest_discord import Obj
from faux_serveur import textes
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)


def _ns(**plus):
    ns = {"discord": discord, "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels, "time": __import__("time"),
          "Button": discord.ui.Button, "Select": discord.ui.Select, "View": discord.ui.View,
          "tickets_fils": tickets_fils, "_logerr": lambda *a, **k: None}
    ns.update(plus)
    for nom in ("_vue_ticket_message", "_carte_ticket"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def test_V1_plus_aucune_vue_de_ticket_en_ancien_format():
    for nom in ("TicketConfirmCreateView", "TicketHubTypeView", "AddStaffView", "TransferTicketView",
                "TicketPriorityView", "TicketCloseReasonView"):
        classe = next(n for n in ARBRE.body if isinstance(n, ast.ClassDef) and n.name == nom)
        assert [ast.unparse(b) for b in classe.bases] == ["LayoutView"], nom
    for vieux in ('send_message("👥 Choisir un staff:"', '"🔄 Transférer la prise en charge à :"',
                  "content='Annulé — aucun ticket créé.'", "Un **salon privé** sera créé et le **staff prévenu**",
                  "Les autres staffs ne peuvent plus voir ce ticket"):
        assert vieux not in SRC, vieux


def test_V2_la_confirmation_d_ouverture_en_v2():
    appels = []

    async def create_ticket(i, pid, ans=None):
        appels.append(pid)
        return Obj(mention="<#77>"), None
    ns = _ns(create_ticket=create_ticket)
    exec(_source("TicketConfirmCreateView"), ns)  # noqa: S102 — code du dépôt
    vue = ns["TicketConfirmCreateView"]("p1", "📩 Tu vas ouvrir un ticket **« Rell Seas »**.")
    assert "Tu vas ouvrir un ticket" in textes(vue)
    oui, non = [b for b in vue.walk_children() if isinstance(b, discord.ui.Button)]
    suivis, edits = [], []

    async def defer(**_k):
        return None

    async def send(**kw):
        suivis.append(kw)

    async def edit_message(**kw):
        edits.append(kw)
    i = Obj(guild=Obj(id=1), response=Obj(defer=defer, edit_message=edit_message), followup=Obj(send=send))
    asyncio.run(oui.callback(i))
    assert appels == ["p1"] and "Ticket créé : <#77>" in textes(suivis[-1]["view"])
    asyncio.run(non.callback(i))
    assert "Annulé — aucun ticket créé." in textes(edits[-1]["view"])


class _Salon(discord.TextChannel):
    def __init__(self):
        self.id, self.envois, self.edits = 77, [], []

    async def send(self, **kw):
        self.envois.append(kw)

    async def edit(self, **kw):
        self.edits.append(kw)


def test_V3_prendre_en_charge_la_direction_garde_la_vue():
    direction, staff = Obj(id=20, name="Direction"), Obj(id=7, name="Staff")
    fondateur = Obj(id=781205382923288593)
    salon = _Salon()
    me, defaut, owner = Obj(id=999), Obj(id=1), Obj(id=99)
    auteur = Obj(id=3)
    pris = Obj(id=50, display_name="Modo", roles=[staff], guild_permissions=Obj(administrator=False))
    g = Obj(id=1, default_role=defaut, me=me, owner=owner, owner_id=99,
            get_role=lambda rid: {7: staff}.get(rid), get_member=lambda uid: {3: auteur}.get(uid))
    journal = []

    async def get_ticket(_chid):
        return {"id": 1, "user": 3, "claimed": 0, "panel_id": "p1"}

    async def cfg(_gid):
        return {"ticket_staff": 7}

    async def faux(*_a, **_k):
        return False

    async def rien(*_a, **_k):
        journal.append(a if (a := _a) else _k)

    async def dossier(*_a, **_k):
        return "dossier"

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a):
            return None

        async def commit(self):
            return None
    async def equipe(*_a, **_k):
        return "equipe"
    ns = _ns(get_ticket=get_ticket, cfg=cfg, is_fully_immune=faux, send_ticket_log=rien,
             _vue_dossier_ticket_de=dossier, tix_module=Obj(log_action=rien), get_db=lambda: Db(),
             _equipe_direction=lambda _g, _c: [direction, fondateur], _droit_ticket=equipe,
             _equipe_du_type=lambda _g, _c, _pid: (staff, [], ""), _claims_en_cours=set())
    exec(_source("_repondre_ticket"), ns)  # noqa: S102 — code du dépôt
    exec(_source("TicketControlView"), ns)  # noqa: S102 — code du dépôt
    edits = []

    async def edit_message(**kw):
        edits.append(kw)

    async def defer(**_k):
        return None
    i = Obj(channel=salon, guild=g, user=pris, message=Obj(flags=Obj(components_v2=True)),
            response=Obj(edit_message=edit_message, defer=defer, is_done=lambda: True),
            edit_original_response=edit_message, followup=Obj(send=rien))
    vue = ns["TicketControlView"]()
    asyncio.run(vue.claim.callback(i))
    ows = salon.edits[-1]["overwrites"]
    assert ows[staff].view_channel is False and ows[pris].view_channel, "le staff en charge seul…"
    assert ows[direction].view_channel and ows[fondateur].view_channel, "…et la direction et le fondateur, toujours"
    annonce = textes(salon.envois[-1]["view"])
    assert "prend ce ticket en charge" in annonce and "la direction, si" in annonce
