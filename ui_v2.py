"""
ui_v2.py — Design system Components V2 (discord.py 2.7+).

Helpers pour construire des LayoutView modernes avec un look cohérent.

Exemple minimal :

    from ui_v2 import BasePanel, Palette, title, subtitle, divider, container, kv_block

    class MyPanel(BasePanel):
        def __init__(self, owner, guild):
            super().__init__(owner)
            self.add_item(container(
                title(f"Configuration — {guild.name}"),
                subtitle("Choisis un module ci-dessous"),
                divider(),
                kv_block([
                    ("Membres", f"{guild.member_count}"),
                    ("Salons", f"{len(guild.text_channels)}"),
                ]),
                color=Palette.PRIMARY,
            ))
"""
from __future__ import annotations
from typing import Optional, Sequence, Union
import discord
from discord import ui


# ═══════════════════════════════════════════════════════════════════════════════
#  🎨 PALETTE — couleurs accent cohérentes pour les Containers
# ═══════════════════════════════════════════════════════════════════════════════

class Palette:
    """Couleurs d'accent (utilisées dans Container.accent_color)."""
    PRIMARY = discord.Color(0x5865F2)  # Blurple Discord
    SUCCESS = discord.Color(0x57F287)  # Vert
    WARNING = discord.Color(0xFEE75C)  # Jaune
    DANGER  = discord.Color(0xED4245)  # Rouge
    INFO    = discord.Color(0x3498DB)  # Bleu clair
    NEUTRAL = discord.Color(0x2F3136)  # Gris foncé
    ACCENT  = discord.Color(0xEB459E)  # Fuchsia
    PREMIUM = discord.Color(0xF1C40F)  # Or
    DARK    = discord.Color(0x1E1F22)  # Quasi-noir


# ═══════════════════════════════════════════════════════════════════════════════
#  🧱 BUILDERS DE TEXTE
# ═══════════════════════════════════════════════════════════════════════════════

def title(text: str, level: int = 1) -> ui.TextDisplay:
    """Titre H1/H2/H3 (`#`, `##`, `###`)."""
    prefix = "#" * max(1, min(level, 3))
    return ui.TextDisplay(f"{prefix} {text}")


def subtitle(text: str) -> ui.TextDisplay:
    """Sous-titre discret (markdown `-#`)."""
    return ui.TextDisplay(f"-# {text}")


def body(text: str) -> ui.TextDisplay:
    """Paragraphe de corps de texte."""
    return ui.TextDisplay(text)


def kv_block(rows: Sequence[tuple[str, str]], *, separator: str = " — ") -> ui.TextDisplay:
    """Bloc clé/valeur en markdown.

    >>> kv_block([("Membres", "1234"), ("Bots", "8")])
    """
    lines = [f"**{k}**{separator}{v}" for k, v in rows]
    return ui.TextDisplay("\n".join(lines))


def bullets(items: Sequence[str]) -> ui.TextDisplay:
    """Liste à puces."""
    return ui.TextDisplay("\n".join(f"• {item}" for item in items))


def stat_line(icon: str, label: str, value: str) -> str:
    """Ligne de stat formatée (renvoie une str — à composer dans un TextDisplay)."""
    return f"{icon} **{label}** · `{value}`"


def stats_grid(stats: Sequence[tuple[str, str, str]]) -> ui.TextDisplay:
    """Grille de stats (icône, label, valeur), une par ligne."""
    return ui.TextDisplay("\n".join(stat_line(i, l, v) for i, l, v in stats))


# ═══════════════════════════════════════════════════════════════════════════════
#  🖼️ BUILDERS VISUELS
# ═══════════════════════════════════════════════════════════════════════════════

def divider() -> ui.Separator:
    """Séparateur visuel horizontal."""
    return ui.Separator()


def thumb(url: str) -> ui.Thumbnail:
    """Vignette (accessoire de Section)."""
    return ui.Thumbnail(media=url)


def section(
    *items: Union[ui.TextDisplay, str],
    accessory: ui.Item,
) -> ui.Section:
    """Section avec jusqu'à 3 TextDisplays + 1 accessoire OBLIGATOIRE.

    `accessory` est requis par discord.py 2.7 (Thumbnail ou Button).
    Pour un bloc texte SANS accessoire, ajoute directement les TextDisplays
    dans le Container — pas besoin de Section.

    Les `str` passées sont automatiquement enveloppées en TextDisplay.
    """
    text_items = [
        i if isinstance(i, ui.TextDisplay) else ui.TextDisplay(str(i))
        for i in items
    ]
    return ui.Section(*text_items, accessory=accessory)


def container(*items: ui.Item, color: discord.Color = Palette.PRIMARY) -> ui.Container:
    """Container (équivalent moderne d'un Embed) avec couleur d'accent."""
    return ui.Container(*items, accent_color=color)


# ═══════════════════════════════════════════════════════════════════════════════
#  🏗️ VIEW DE BASE — owner-check + timeout standard
# ═══════════════════════════════════════════════════════════════════════════════

class BasePanel(ui.LayoutView):
    """LayoutView avec restriction owner + timeout 10 minutes par défaut.

    Usage :
        class MonPanel(BasePanel):
            def __init__(self, owner, guild):
                super().__init__(owner)
                self.guild = guild
                self.add_item(container(title("Mon Panel"), color=Palette.PRIMARY))
    """

    def __init__(self, owner: discord.abc.User, *, timeout: float = 600.0):
        super().__init__(timeout=timeout)
        self.owner = owner

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            try:
                await interaction.response.send_message(
                    "❌ Seul l'utilisateur ayant ouvert ce panneau peut l'utiliser.",
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                await interaction.followup.send(
                    "❌ Seul l'utilisateur ayant ouvert ce panneau peut l'utiliser.",
                    ephemeral=True,
                )
            return False
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  📐 PATTERNS PRÊTS À L'EMPLOI
# ═══════════════════════════════════════════════════════════════════════════════

def header(
    title_text: str,
    subtitle_text: Optional[str] = None,
    *,
    icon_url: str,
) -> ui.Section:
    """En-tête de panel : titre H1 + sous-titre + icône à droite (Thumbnail).

    `icon_url` est obligatoire (Section requiert un accessoire).
    Pour un en-tête sans icône, utilise `title()` + `subtitle()` directement
    dans le Container.
    """
    parts: list[ui.TextDisplay] = [ui.TextDisplay(f"# {title_text}")]
    if subtitle_text:
        parts.append(ui.TextDisplay(f"-# {subtitle_text}"))
    return ui.Section(*parts, accessory=ui.Thumbnail(media=icon_url))


def info_card(
    title_text: str,
    description: str,
    *,
    icon_url: Optional[str] = None,
    color: discord.Color = Palette.PRIMARY,
    footer: Optional[str] = None,
) -> ui.Container:
    """Carte d'information complète : header + description + footer optionnel.

    Si `icon_url` est fourni, utilise une Section avec Thumbnail.
    Sinon, ajoute le titre/description en TextDisplays directs.
    """
    items: list[ui.Item] = []
    if icon_url:
        items.append(header(title_text, description, icon_url=icon_url))
    else:
        items.append(ui.TextDisplay(f"# {title_text}"))
        items.append(ui.TextDisplay(description))
    if footer:
        items.append(ui.Separator())
        items.append(ui.TextDisplay(f"-# {footer}"))
    return ui.Container(*items, accent_color=color)


__all__ = [
    "Palette",
    "title",
    "subtitle",
    "body",
    "kv_block",
    "bullets",
    "stat_line",
    "stats_grid",
    "divider",
    "thumb",
    "section",
    "container",
    "BasePanel",
    "header",
    "info_card",
]
