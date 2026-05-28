"""
help_faq.py — FAQ navigable sans commande (Phase 149).

🎯 OBJECTIF : remplacer "tape /machin" par "clique ici". Les nouveaux
arrivants n'ont qu'à cliquer dans le hub → menu de FAQ par catégorie
→ chaque réponse explique ET propose d'ouvrir le panel concerné.

Architecture :
- Root panel : 6 catégories (boutons)
- Catégorie : 3-5 questions (boutons)
- Réponse : panel V2 avec explication + bouton "Ouvrir le panel"

Aucune DB, aucune commande. 100% navigation par boutons.

API publique :
- setup(v2_helpers, register_open_fn=None)
- build_faq_root() -> LayoutView
- register_panel_opener(key, async_callback)

Le bouton "Ouvrir le panel concerné" appelle le callback enregistré
par bot.py via register_panel_opener.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord
from discord.ui import View, Button

# ─── Config ────────────────────────────────────────────────────────────────
_v2 = None
_openers: dict[str, Callable[[discord.Interaction], Awaitable[None]]] = {}

# ─── Catalogue FAQ ──────────────────────────────────────────────────────────

FAQ_CATEGORIES = [
    {"key": "economy", "emoji": "💰", "title": "Économie"},
    {"key": "combat", "emoji": "⚔️", "title": "Combat & PvP"},
    {"key": "season", "emoji": "🏆", "title": "Saisons"},
    {"key": "drops", "emoji": "🎁", "title": "Drops & Loot"},
    {"key": "alliance", "emoji": "🤝", "title": "Alliances"},
    {"key": "events", "emoji": "🎰", "title": "Mini-jeux & Events"},
]

# Pour chaque catégorie, liste de Q/A
FAQ_QA = {
    "economy": [
        {
            "q": "Comment gagner des coins ?",
            "a": (
                "Tu gagnes des coins via :\n"
                "• **Daily Wheel** — 1 spin gratuit toutes les 24h\n"
                "• **Quêtes journalières** — 3 quêtes / jour\n"
                "• **Boss raids** — chaque coup donne des coins\n"
                "• **Treasures** — apparaissent aléatoirement\n"
                "• **Mini-jeux** — riddles, prédictions, etc."
            ),
            "opener": "open_hub_economy",
        },
        {
            "q": "C'est quoi la banque ?",
            "a": (
                "La banque te permet de **stocker tes coins** à l'abri "
                "des heists collectifs. Tu peux y déposer, retirer, et "
                "tes coins génèrent des intérêts passifs.\n\n"
                "_Les coins en banque ne peuvent pas être volés._"
            ),
            "opener": "open_hub_bank",
        },
        {
            "q": "Comment marche le Marketplace ?",
            "a": (
                "Tu peux **vendre tes items** à d'autres joueurs :\n"
                "1. Ouvre ton inventaire\n"
                "2. Sélectionne l'item à vendre\n"
                "3. Fixe ton prix\n"
                "4. Les autres l'achètent via le panel Marketplace.\n\n"
                "_Le bot prend 5% de commission pour éviter les abus._"
            ),
            "opener": "open_hub_marketplace",
        },
    ],
    "combat": [
        {
            "q": "Comment fonctionne le Boss Raid ?",
            "a": (
                "Un boss apparaît périodiquement dans l'arène :\n"
                "• Tu cliques sur **⚔️ ATTAQUER**\n"
                "• Tu inflige X dégâts (selon ton gear)\n"
                "• Le boss riposte aléatoirement (HP perdu)\n"
                "• Le **dernier coup** donne un bonus massif\n\n"
                "_Plus tu participes, plus tu gagnes._"
            ),
            "opener": "open_hub_boss",
        },
        {
            "q": "Comment défier quelqu'un en duel ?",
            "a": (
                "Va dans le hub → **PvP** → **Duel 1v1** :\n"
                "• Choisis ton adversaire\n"
                "• Fixe une mise optionnelle\n"
                "• Il accepte → combat instantané\n"
                "• Le perdant reporte via le panel duel\n\n"
                "_Ton rating Elo monte/descend selon le résultat._"
            ),
            "opener": "open_hub_pvp",
        },
        {
            "q": "C'est quoi le Ladder Elo ?",
            "a": (
                "Tu commences à `1000`. Chaque duel modifie ton score :\n"
                "• Battre plus fort que toi → gros gain\n"
                "• Battre plus faible → petit gain\n"
                "• Perdre contre plus faible → grosse perte\n\n"
                "Divisions :\n"
                "💎 Diamant `≥1800` · 🥇 Or `≥1500` · 🥈 Argent `≥1200` · "
                "🥉 Bronze `≥900`."
            ),
            "opener": "open_hub_pvp",
        },
    ],
    "season": [
        {
            "q": "C'est quoi les saisons ?",
            "a": (
                "8 saisons couvrent l'année. Chaque saison :\n"
                "• A son ambiance (Hiver, Été, Halloween, etc.)\n"
                "• Donne un multiplicateur sur les rewards d'events\n"
                "• Débloque des drops exclusifs (jamais re-disponibles)\n\n"
                "_Vérifie la saison active via le panel Saison._"
            ),
            "opener": "open_season_panel",
        },
        {
            "q": "Comment voir mes drops collectés ?",
            "a": (
                "Chaque drop saisonnier que tu obtiens est noté dans "
                "ton dossier permanent.\n\n"
                "Tu peux voir ta collection complète et savoir ceux qui "
                "te manquent encore — certains ne reviendront que dans "
                "1 an."
            ),
            "opener": "open_my_drops_panel",
        },
    ],
    "drops": [
        {
            "q": "Où trouver des drops ?",
            "a": (
                "Les drops apparaissent dans :\n"
                "• **Boss raids** — dernier coup = drop garanti\n"
                "• **Treasure Hunt** — boutons claim\n"
                "• **Mystery Box** — apparaît random\n"
                "• **World Boss** — top damager = drop rare\n"
                "• **Saison** — drops exclusifs (jamais revus)\n\n"
                "_Plus l'event est dur, plus le drop est rare._"
            ),
            "opener": "open_hub_economy",
        },
        {
            "q": "Comment marche le Crafting ?",
            "a": (
                "Combine 3 items rares de même rareté pour fabriquer "
                "1 item de rareté supérieure :\n"
                "• 3 communs → 1 rare\n"
                "• 3 rares → 1 épique\n"
                "• 3 épiques → 1 légendaire\n\n"
                "_Les recettes sont visibles dans le panel Crafting._"
            ),
            "opener": "open_hub_economy",
        },
    ],
    "alliance": [
        {
            "q": "C'est quoi une Alliance ?",
            "a": (
                "Une alliance, c'est un groupe de joueurs qui partagent :\n"
                "• Un **coffre commun** (déposer/retirer)\n"
                "• Un **inventaire d'équipement** partagé\n"
                "• Des **buffs** lors des events ensemble\n\n"
                "_Le chef gère les membres. Il peut expulser de l'alliance "
                "(jamais du serveur)._"
            ),
            "opener": "open_hub_alliance",
        },
        {
            "q": "Comment créer ou rejoindre une alliance ?",
            "a": (
                "**Créer :** Hub → Alliance → 'Créer une alliance'\n"
                "**Rejoindre :** un chef d'alliance t'envoie une "
                "invitation que tu acceptes via le panel.\n\n"
                "_Tu ne peux être que dans 1 alliance à la fois._"
            ),
            "opener": "open_hub_alliance",
        },
    ],
    "events": [
        {
            "q": "Quand y a-t-il des events ?",
            "a": (
                "Les events apparaissent **automatiquement** selon des "
                "horaires variés :\n"
                "• Boss raid : plusieurs fois par semaine\n"
                "• World Boss : samedi 21h FR\n"
                "• Riddle : matin\n"
                "• Treasure : random\n"
                "• Mystery Box : random\n\n"
                "_Le hub affiche les events en cours en temps réel._"
            ),
            "opener": "open_hub_events",
        },
        {
            "q": "C'est quoi la Daily Wheel ?",
            "a": (
                "Une roue avec 8 récompenses possibles. Tu spin 1×/24h "
                "gratuitement.\n\n"
                "Récompenses : coins, gear, multiplier, ou jackpot rare. "
                "Plus tu enchaînes les jours, plus le streak monte."
            ),
            "opener": "open_hub_economy",
        },
    ],
}


def setup(v2_helpers: dict):
    global _v2
    _v2 = v2_helpers


def register_panel_opener(
    key: str,
    callback: Callable[[discord.Interaction], Awaitable[None]],
):
    """Bot.py enregistre les callbacks qui ouvrent les panels.
    key = "open_hub_economy", "open_season_panel", etc.
    """
    _openers[key] = callback


# ─── Builders ──────────────────────────────────────────────────────────────

def _build_v2_panel(items: list, color: int = 0x3498DB):
    """Helper pour construire un container V2."""
    LayoutView = _v2['LayoutView']
    v2_container = _v2['v2_container']

    class _Panel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=color))
    return _Panel()


def build_faq_root():
    """Panel d'entrée : 6 catégories."""
    if _v2 is None:
        return None
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    LayoutView = _v2['LayoutView']
    v2_container = _v2['v2_container']

    class _FAQRoot(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            items = [
                v2_title("❓  Comment ça marche ?"),
                v2_body(
                    "_Bienvenue ! Choisis une catégorie pour découvrir "
                    "les features du serveur. Tout est cliquable._"
                ),
                v2_divider(),
                v2_body(
                    "**Catégories disponibles :**\n"
                    + "\n".join(
                        f"{c['emoji']} **{c['title']}**"
                        for c in FAQ_CATEGORIES
                    )
                ),
            ]
            self.add_item(v2_container(*items, color=0x3498DB))

            # Boutons catégories (max 5 par ActionRow)
            row1_buttons = []
            row2_buttons = []
            for i, cat in enumerate(FAQ_CATEGORIES):
                btn = Button(
                    label=cat["title"],
                    emoji=cat["emoji"],
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"faq_cat_{cat['key']}",
                )

                async def _cb(i_inter: discord.Interaction, k=cat["key"]):
                    panel = build_faq_category(k)
                    if panel:
                        await i_inter.response.send_message(
                            view=panel, ephemeral=True
                        )

                btn.callback = _cb
                if i < 5:
                    row1_buttons.append(btn)
                else:
                    row2_buttons.append(btn)

            for b in row1_buttons:
                self.add_item(b)
            for b in row2_buttons:
                self.add_item(b)

    return _FAQRoot()


def build_faq_category(cat_key: str):
    """Panel pour une catégorie : liste des questions cliquables."""
    if _v2 is None:
        return None
    cat = next((c for c in FAQ_CATEGORIES if c["key"] == cat_key), None)
    if not cat:
        return None
    qa_list = FAQ_QA.get(cat_key, [])
    if not qa_list:
        return None

    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    LayoutView = _v2['LayoutView']
    v2_container = _v2['v2_container']

    class _CatPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            items = [
                v2_title(f"{cat['emoji']}  {cat['title']}"),
                v2_body("_Choisis une question pour voir la réponse._"),
                v2_divider(),
            ]
            for i, qa in enumerate(qa_list, 1):
                items.append(v2_body(f"**`{i}.`** {qa['q']}"))
            self.add_item(v2_container(*items, color=0x3498DB))

            # Boutons (1 par question)
            for i, qa in enumerate(qa_list, 1):
                b = Button(
                    label=f"Q{i}",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"faq_qa_{cat_key}_{i}",
                )

                async def _cb(i_inter: discord.Interaction, idx=i - 1, c=cat_key):
                    panel = build_faq_answer(c, idx)
                    if panel:
                        await i_inter.response.send_message(
                            view=panel, ephemeral=True
                        )

                b.callback = _cb
                self.add_item(b)

    return _CatPanel()


def build_faq_answer(cat_key: str, qa_idx: int):
    """Panel pour une réponse + bouton 'Ouvrir le panel'."""
    if _v2 is None:
        return None
    qa_list = FAQ_QA.get(cat_key, [])
    if qa_idx < 0 or qa_idx >= len(qa_list):
        return None
    qa = qa_list[qa_idx]

    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    LayoutView = _v2['LayoutView']
    v2_container = _v2['v2_container']

    class _AnswerPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = [
                v2_title(f"💡  {qa['q']}"),
                v2_divider(),
                v2_body(qa["a"]),
            ]
            self.add_item(v2_container(*items, color=0x2ECC71))

            # Bouton "Ouvrir le panel concerné" si opener enregistré
            opener_key = qa.get("opener")
            if opener_key and opener_key in _openers:
                b = Button(
                    label="🔗 Ouvrir le panel concerné",
                    style=discord.ButtonStyle.success,
                )

                async def _cb(i_inter: discord.Interaction, k=opener_key):
                    try:
                        await _openers[k](i_inter)
                    except Exception as ex:
                        try:
                            if not i_inter.response.is_done():
                                await i_inter.response.send_message(
                                    f"❌ Erreur : `{ex}`", ephemeral=True
                                )
                        except Exception:
                            pass

                b.callback = _cb
                self.add_item(b)

    return _AnswerPanel()


__all__ = [
    "setup",
    "register_panel_opener",
    "build_faq_root",
    "build_faq_category",
    "build_faq_answer",
    "FAQ_CATEGORIES",
    "FAQ_QA",
]
