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
import sys as _sys
import traceback as _traceback
import discord
from discord import ui


# ═══════════════════════════════════════════════════════════════════════════════
#  🛟 FILET GLOBAL — un bouton ne doit JAMAIS rester muet
# ═══════════════════════════════════════════════════════════════════════════════
#
# PROBLÈME (revue 2026-07-17) : aucun panneau du bot ne définissait `on_error`.
# discord.py appelle `BaseView.on_error(interaction, error, item)` dès qu'un callback
# d'item lève (view.py:568, appelé view.py:600) ; son implémentation par défaut se
# contente d'un `_log.error(...)`. Résultat : le moindre hoquet transitoire (pool
# SQLite affamé, gateway en retard, 429) laissait l'interaction SANS RÉPONSE →
# le membre voyait « L'application ne répond plus » et l'owner ne voyait RIEN.
#
# On hérite `View`/`LayoutView` d'un mixin qui, sur exception :
#   1. écrit la stack sur **stderr** (obligatoire : `_QuietStdout` masque stdout) ;
#   2. répond quelque chose au membre au lieu de le laisser devant un bouton mort.
#
# Une classe qui définit son propre `on_error` garde le sien (MRO) — rien n'est écrasé.
# Le mixin est inerte vis-à-vis de `__init_subclass__` de discord.py (il n'y cherche que
# des `Item` et des `__discord_ui_model_type__`, view.py:749-759 et 855-867).
# `Modal` n'est PAS couvert : sa signature diffère (`on_error(interaction, error)`).

class _SafeErrorView:
    """Mixin : une exception dans un callback ne laisse jamais l'interaction muette."""

    async def on_error(self, interaction, error, item=None, /) -> None:
        try:
            _who = getattr(item, 'custom_id', None) or getattr(item, 'label', None) or '?'
            # DIAG : un bouton/menu qui plante apparaît dans le flux [DIAG] filtrable sur Railway.
            try:
                import diag
                diag.error("ui", f"{type(self).__name__}/{_who}",
                           "exception dans un callback d'interaction", exc=error)
            except Exception:
                pass
            print(f"[view on_error] {type(self).__name__}/{_who} : "
                  f"{type(error).__name__}: {error}", file=_sys.stderr, flush=True)
            _traceback.print_exception(type(error), error, error.__traceback__,
                                       file=_sys.stderr)
        except Exception:
            pass
        try:
            _msg = ("⚠️ Un souci est survenu pendant cette action — réessaie dans quelques "
                    "secondes.\n-# Si ça continue, préviens un admin.")
            if interaction.response.is_done():
                await interaction.followup.send(_msg, ephemeral=True)
            else:
                await interaction.response.send_message(_msg, ephemeral=True)
        except Exception:
            pass


class View(_SafeErrorView, ui.View):
    """`discord.ui.View` + filet d'erreur. À importer d'ici, pas de `discord.ui`."""


class LayoutView(_SafeErrorView, ui.LayoutView):
    """`discord.ui.LayoutView` (Components V2) + filet d'erreur."""


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

class BasePanel(LayoutView):
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


__all__ = [
    "Palette",
    "title",
    "subtitle",
    "body",
    "kv_block",
    "divider",
    "thumb",
    "section",
    "container",
    "BasePanel",
    "header",
]
