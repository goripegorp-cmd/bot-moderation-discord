"""
panels_helpers.py — Helpers V2 communs réutilisables (Phase 127).

Centralise les patterns répétés dans bot.py :
- Formatters (items, coins, durées, dates)
- Badges de rareté visuelle
- Factories de boutons réutilisables (Fermer / Actualiser / Navigation)

Objectif : réduire la duplication dans bot.py et standardiser l'UX.
Aucune dépendance Discord côté logique pure — juste les factories de buttons
importent discord.

Usage typique dans bot.py :
    from panels_helpers import (
        format_item_line, rarity_badge, format_coins,
        make_close_button, make_refresh_button,
    )

    # Dans un LayoutView :
    items.append(v2_body(format_item_line(weapon, "weapon")))
    items.append(v2_section(
        v2_title("Réinitialiser"),
        v2_subtitle("Recharger les données"),
        accessory=make_refresh_button(i.user.id, my_refresh_callback),
    ))
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import discord


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES — Tables de rareté + couleurs
# ═══════════════════════════════════════════════════════════════════════════════

RARITY_BADGES = {
    "commune":    "⚪",
    "rare":       "🔵",
    "épique":     "🟣",
    "epique":     "🟣",   # alias sans accent
    "légendaire": "🟠",
    "legendaire": "🟠",   # alias sans accent
    "mythique":   "🔴",
    "divine":     "💎",
}

RARITY_COLORS = {
    "commune":    0x95A5A6,
    "rare":       0x3498DB,
    "épique":     0x9B59B6,
    "légendaire": 0xE67E22,
    "mythique":   0xE74C3C,
    "divine":     0xFFD700,
}


# ═══════════════════════════════════════════════════════════════════════════════
# FORMATTERS — affichage propre des données
# ═══════════════════════════════════════════════════════════════════════════════

def rarity_badge(rarity: str | None) -> str:
    """Retourne l'emoji badge pour une rareté donnée (insensible à la casse)."""
    if not rarity:
        return "⚪"
    key = rarity.lower().strip()
    return RARITY_BADGES.get(key, "⚪")


def rarity_color(rarity: str | None, default: int = 0x5865F2) -> int:
    """Retourne la couleur hex pour une rareté."""
    if not rarity:
        return default
    key = rarity.lower().strip()
    return RARITY_COLORS.get(key, default)


def format_coins(n: int, short: bool = False) -> str:
    """Format un montant de coins.

    short=True : 1.2k / 1.5M / 250
    short=False : 1,234,567
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if short:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)
    return f"{n:,}".replace(",", " ")  # séparateur français


def format_duration(seconds: int) -> str:
    """Format une durée en secondes en texte lisible.

    Exemples : 45s, 2min, 1h 30min, 3j 4h
    """
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        return "—"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m = s // 60
        return f"{m}min"
    if s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}min" if m else f"{h}h"
    d = s // 86400
    h = (s % 86400) // 3600
    return f"{d}j {h}h" if h else f"{d}j"


def format_item_line(item: dict, slot_label: str = "") -> str:
    """Génère une ligne pretty pour un item d'équipement.

    Format : 🟠 ⚔️ **Item Name** _légendaire_ `+15 ATK · +5 CRIT%`
    """
    if not item or not item.get("name"):
        return f"_{slot_label}: aucun_" if slot_label else "_(vide)_"
    emoji = item.get("emoji", "⚪")
    name = item.get("name", "?")
    rarity = (item.get("rarity") or "commune").lower()
    badge = rarity_badge(rarity)
    bits = []
    for stat, label in [("atk", "ATK"), ("def", "DEF"), ("crit", "CRIT%")]:
        v = item.get(stat)
        if v:
            sign = "+" if isinstance(v, (int, float)) and v >= 0 else ""
            bits.append(f"{sign}{v} {label}")
    stats_str = " · ".join(bits) if bits else ""
    head = f"{badge} {emoji} **{name}** _{rarity}_"
    return f"{head} `{stats_str}`" if stats_str else head


def format_hp_bar(current: int, maximum: int, length: int = 20) -> str:
    """Barre de HP visuelle ASCII : ████░░░░░ 42%."""
    try:
        c = max(0, int(current))
        m = max(1, int(maximum))
    except (TypeError, ValueError):
        return "░" * length
    pct = c / m
    filled = round(pct * length)
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return f"`{bar}` {int(pct * 100)}%"


def section_header(emoji: str, title: str) -> str:
    """Génère un header de section pretty : ### 🏆 TITRE."""
    return f"### {emoji} {title.upper()}"


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORIES DE BOUTONS — Boutons UX réutilisables
# ═══════════════════════════════════════════════════════════════════════════════

def make_close_button(
    owner_id: int,
    custom_id_prefix: str = "panel_close",
) -> discord.ui.Button:
    """Crée un bouton "❌ Fermer" qui supprime le message ephemeral.

    Vérifie owner_id pour empêcher les clics par autrui.
    """

    class _CloseBtn(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label="❌ Fermer",
                style=discord.ButtonStyle.secondary,
                custom_id=f"{custom_id_prefix}_{owner_id}",
            )

        async def callback(self, btn_i: discord.Interaction):
            if btn_i.user.id != owner_id:
                return await btn_i.response.send_message(
                    "❌ Ce panneau n'est pas pour toi.", ephemeral=True
                )
            try:
                # Pour les ephemeral, on edit avec contenu vide + view=None
                await btn_i.response.edit_message(content="✅ Panneau fermé.", view=None)
            except Exception:
                try:
                    await btn_i.response.defer()
                except Exception:
                    pass

    return _CloseBtn()


def make_refresh_button(
    owner_id: int,
    refresh_callback: Callable[[discord.Interaction], Awaitable[None]],
    label: str = "🔄 Actualiser",
    custom_id_prefix: str = "panel_refresh",
) -> discord.ui.Button:
    """Crée un bouton "🔄 Actualiser" qui appelle refresh_callback(interaction).

    Le callback doit gérer son propre rendering (edit_message ou send_message).
    """

    class _RefreshBtn(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"{custom_id_prefix}_{owner_id}",
            )

        async def callback(self, btn_i: discord.Interaction):
            if btn_i.user.id != owner_id:
                return await btn_i.response.send_message(
                    "❌ Ce panneau n'est pas pour toi.", ephemeral=True
                )
            try:
                await refresh_callback(btn_i)
            except Exception as ex:
                print(f"[make_refresh_button cb] {ex}")
                try:
                    if not btn_i.response.is_done():
                        await btn_i.response.send_message(
                            f"❌ Erreur refresh : `{ex}`", ephemeral=True
                        )
                except Exception:
                    pass

    return _RefreshBtn()


def make_nav_button(
    owner_id: int,
    label: str,
    target_callable: Callable[[discord.Interaction], Awaitable[None]],
    style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    custom_id_prefix: str = "panel_nav",
) -> discord.ui.Button:
    """Crée un bouton de navigation qui appelle target_callable(interaction).

    Pattern : pour passer d'un panel à un autre (Inventaire ↔ Badges ↔ etc.)
    """

    class _NavBtn(discord.ui.Button):
        def __init__(self):
            super().__init__(
                label=label,
                style=style,
                custom_id=f"{custom_id_prefix}_{owner_id}_{hash(label) & 0xffff:04x}",
            )

        async def callback(self, btn_i: discord.Interaction):
            if btn_i.user.id != owner_id:
                return await btn_i.response.send_message(
                    "❌ Ce panneau n'est pas pour toi.", ephemeral=True
                )
            try:
                await target_callable(btn_i)
            except Exception as ex:
                print(f"[make_nav_button cb] {ex}")
                try:
                    if not btn_i.response.is_done():
                        await btn_i.response.send_message(
                            f"❌ Erreur : `{ex}`", ephemeral=True
                        )
                except Exception:
                    pass

    return _NavBtn()


__all__ = [
    # Constantes
    "RARITY_BADGES", "RARITY_COLORS",
    # Formatters
    "rarity_badge", "rarity_color",
    "format_coins", "format_duration",
    "format_item_line", "format_hp_bar",
    "section_header",
    # Factories de boutons
    "make_close_button", "make_refresh_button", "make_nav_button",
]
