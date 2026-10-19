"""20/10/2026 (audit 1 #12) : « Roles epargnes » ne proposait que 25 evenements sur 50."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
from discord.ui import Button, Select

import ui_v2
import unified_logger as U
import visuels
from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))


def _panneau():
    async def exclusions(_gid):
        return {"msg.delete": [1]}

    async def afficher(vue, i, edit):
        return None
    ns = {"discord": discord, "Button": Button, "Select": Select, "visuels": visuels, "LayoutView": ui_v2.LayoutView,
          "v2_container": ui_v2.container, "v2_body": ui_v2.body, "v2_subtitle": ui_v2.subtitle,
          "v2_divider": ui_v2.divider, "Palette": ui_v2.Palette, "_afficher_panneau": afficher,
          "ulogger2026": Obj(get_role_exclusions=exclusions, EVENT_META=U.EVENT_META, EventType=U.EventType),
          "_logerr": lambda *a, **k: None}
    for n in ARBRE.body:
        if getattr(n, "name", "") in ("LogsExclusionsPanelV2", "_resolve_event_type"):
            exec(ast.unparse(n), ns)  # noqa: S102
    return ns["LogsExclusionsPanelV2"](Obj(id=1), Obj(id=2, get_role=lambda r: None))


def _options(vue):
    sel = next(x for x in vue.walk_children() if isinstance(x, Select))
    return [o.value for o in sel.options]


def test_X1_les_50_evenements_sont_atteignables_par_categorie():
    vue = _panneau()
    asyncio.run(vue.render_to(None))
    cats = _options(vue)
    assert len(cats) == len({m["cat"] for m in U.EVENT_META.values()})
    atteints = set()
    for cat in cats:
        vue.selected_cat = cat
        asyncio.run(vue.render_to(None))
        atteints |= set(_options(vue))
    assert atteints == {ev.value for ev in U.EVENT_META} and "msg.delete" in atteints
