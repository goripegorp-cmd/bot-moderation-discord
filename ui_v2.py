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


class StaticPanel(LayoutView):
    """LayoutView statique pour une ANNONCE / un RÉCAP public (sans boutons).

    Pas d'interaction → pas de risque d'« Échec de l'interaction », pas besoin
    de persistance. À envoyer en `view=` UNIQUEMENT (jamais avec `content=` :
    content + Components V2 = erreur 400).
    """

    def __init__(self, *items: ui.Item, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        for it in items:
            self.add_item(it)


# custom_id stable du bouton « Mon hub » apposé sous les récaps/annonces publics.
# Re-enregistré au boot via bot.add_view(MyHubButtonView()) côté bot.py → le clic
# est dispatché même sur de vieux messages survivant à un reboot. NE PAS renommer.
MY_HUB_BUTTON_CUSTOM_ID = "open_my_hub"


def _my_hub_action_row() -> ui.ActionRow:
    """ActionRow contenant le seul bouton « 🎮 Mon hub » (custom_id stable).

    Le bouton n'a volontairement PAS de callback ici : le dispatch est assuré par
    la vue persistante MyHubButtonView (même custom_id) enregistrée au boot dans
    bot.py. Apposé sous un récap/annonce public, il ouvre le hub en éphémère pour
    le cliqueur (découvrabilité passive)."""
    btn = ui.Button(
        label="Mon hub",
        emoji="🎮",
        style=discord.ButtonStyle.secondary,
        custom_id=MY_HUB_BUTTON_CUSTOM_ID,
    )
    return ui.ActionRow(btn)


def recap_view(
    title_text: str,
    description: str,
    *,
    color: discord.Color = Palette.PRIMARY,
    footer: Optional[str] = None,
    icon_url: Optional[str] = None,
    hub_button: bool = False,
) -> "StaticPanel":
    """Récap/annonce d'événement dans un bel ENCADRÉ Components V2 (au lieu de
    texte brut). Renvoie une LayoutView prête à envoyer :

        await channel.send(view=ui_v2.recap_view("🏆 Fin du Boss", body, color=...))

    Look identique partout (même design-system que tous les panels du bot).
    `description` accepte du markdown multi-ligne (≤ ~4000 caractères).

    Garde-fou : un TextDisplay VIDE est rejeté par Discord (400) → ferait
    échouer le récap. On garantit donc un titre + un corps non vides.

    `hub_button=True` ajoute SOUS l'encadré un bouton « 🎮 Mon hub » persistant
    (custom_id stable, dispatché par MyHubButtonView au boot) qui ouvre le hub en
    éphémère pour le cliqueur — découvrabilité passive sur les annonces publiques.
    """
    safe_title = (title_text or "").strip() or "📢 Événement"
    safe_desc = (description or "").strip()[:4000] or "_—_"
    items = [info_card(
        safe_title, safe_desc, icon_url=icon_url, color=color, footer=footer)]
    if hub_button:
        items.append(_my_hub_action_row())
    return StaticPanel(*items)


def combat_recap_view(
    emoji: str,
    name: str,
    outcome: str,
    podium: Sequence = (),
    *,
    others_count: int = 0,
    participants: Optional[int] = None,
    total_damage: Optional[int] = None,
    hub_button: bool = False,
) -> "StaticPanel":
    """Récap de fin d'événement de COMBAT — format UNIQUE, compact et BORNÉ,
    identique pour TOUS les events (boss raid, world boss, boss du jour, mob,
    climax, invasion, donjon). Toujours ~5-6 lignes quel que soit le nombre de
    participants : ligne d'état + podium (max 3) + « +N autres récompensés ».

    Tout le monde reste RÉCOMPENSÉ (la ligne « +N autres » le rappelle) — seul
    l'AFFICHAGE est borné. Ce helper ne touche AUCUNE logique d'économie.

        view = combat_recap_view("🐲", "Dragon des Cendres", "win",
                                 [("Aria", 1200), ("Korr", 900)],
                                 others_count=12, total_damage=45000)

    Args:
        outcome: "win" (vaincu) · "fail" (non vaincu) · "done" (terminé).
        podium:  séquence de (nom_affiché, pièces) déjà triée du 1er au 3e.
        others_count: nombre de participants au-delà du podium affiché.
        participants: total de participants (sinon déduit de podium+others_count).
        total_damage: dégâts cumulés (optionnel).
    """
    title = f"{(emoji or '').strip()} {(name or 'Événement').strip()}".strip()
    out = (outcome or "done").lower()
    if out == "win":
        head, color = "✅ Vaincu", Palette.SUCCESS
    elif out == "fail":
        head, color = "⏳ Non vaincu", Palette.NEUTRAL
    else:
        head, color = "🏁 Terminé", Palette.PRIMARY
    # Récap volontairement MINIMAL (demande owner : « beaucoup plus simple, juste
    # les infos essentielles ») : état + nombre de participants + qui a gagné +
    # récompense. `total_damage` reste accepté pour compat d'appel mais n'est PLUS
    # affiché (stat technique, non essentielle au joueur).
    n = participants if participants is not None else (len(podium) + max(0, others_count))
    head_line = head
    if n:
        head_line += f" · {n} participant" + ("s" if n > 1 else "")
    lines = [head_line]
    medals = ("🥇", "🥈", "🥉")
    if podium:
        lines.append("")
        for i, entry in enumerate(list(podium)[:3]):
            try:
                nm, coins = entry
                lines.append(f"{medals[i]} **{nm}** · `{int(coins):,}` 🪙")
            except Exception:
                continue
        if others_count and others_count > 0:
            lines.append(f"🔸 _+{int(others_count)} autres récompensés_")
    return recap_view(title, "\n".join(lines), color=color, hub_button=hub_button)


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
    "StaticPanel",
    "recap_view",
    "combat_recap_view",
    "MY_HUB_BUTTON_CUSTOM_ID",
]
