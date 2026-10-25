"""25/10/2026 : une vue temporaire qui contient un bouton persistant (DynamicItem) ne doit plus, en expirant, retirer
ce bouton du registre global de discord.py — sinon tous les boutons de ce type deviennent muets jusqu'au redémarrage."""
from __future__ import annotations

import asyncio
from pathlib import Path

import discord
from discord.ui.view import ViewStore

import persistants

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


class Persistant(discord.ui.DynamicItem[discord.ui.Button], template=r"essai:p:(?P<n>\d+)"):
    def __init__(self, n: int):
        super().__init__(discord.ui.Button(label="Participer", custom_id=f"essai:p:{n}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["n"]))


class Passager(discord.ui.DynamicItem[discord.ui.Button], template=r"essai:t:(?P<n>\d+)"):
    def __init__(self, n: int):
        super().__init__(discord.ui.Button(label="Temporaire", custom_id=f"essai:t:{n}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["n"]))


def test_P1_une_vue_qui_expire_ne_retire_plus_un_bouton_persistant():
    persistants.garder()

    async def essai():
        store = ViewStore(object())
        store.add_dynamic_items(Persistant)                  # inscrit au démarrage (bot.add_dynamic_items)
        motif = Persistant.__discord_ui_compiled_template__
        vue = discord.ui.View(timeout=5)
        vue.add_item(Persistant(1))
        vue.add_item(Passager(2))
        #  Le cas réel : la vue mêle des boutons persistants et un bouton ordinaire (« Annuler »…) — c'est ce
        #  mélange qui fait retirer les gabarits du registre global quand elle expire.
        vue.add_item(discord.ui.Button(label="Annuler", custom_id="essai:annuler"))
        store.add_view(vue, 123)
        assert motif in store._dynamic_items
        store.remove_view(vue)                               # ce que fait discord.py quand la vue expire
        assert store._dynamic_items.get(motif) is Persistant, "le bouton persistant répond toujours"
        assert Passager.__discord_ui_compiled_template__ not in store._dynamic_items, \
            "un bouton seulement porté par la vue temporaire part avec elle, comme avant"
        store.remove_dynamic_items(Persistant)               # un retrait volontaire reste possible
        assert motif not in store._dynamic_items and motif not in persistants.PERSISTANTS
    asyncio.run(essai())


def test_P2_garde_installee_une_fois_avant_la_creation_du_bot():
    assert persistants.garder() is False, "déjà installée : rien n'est empilé deux fois"
    assert SRC.index("persistants.garder()") < SRC.index("bot = commands.Bot(")
