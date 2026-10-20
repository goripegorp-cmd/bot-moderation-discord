"""
admin_panels_v2.py - Panneaux V2 owner pour les nouveaux modules (Phase 1.5).

Tous les panneaux sont owner-only (interaction_check) et utilisent les helpers
de ui_v2 pour rester coherents avec le design existant.

Panneaux fournis :
    - SocialMediaPanelV2     - Abonnements reseaux sociaux (onglet /configure)

Integration dans bot.py :
    import admin_panels_v2 as panels2026
    panels2026.set_social_manager(mgr)          # le vrai manager, au boot
    panels2026.set_retour(_retour_vers_configure)

⚠️ IL N'Y A PLUS DE `/admin`. La commande a ete retiree, et avec elle
`AdminMasterPanelV2` et `setup_admin_command` (purge du 16/08/2026).
`CommunityPanelV2` est parti au meme moment avec le systeme d'animation.
Les panneaux restants s'ouvrent depuis `/configure`, et leur bouton « Retour »
passe par `_revenir()` — jamais par une classe supprimee.
"""
from __future__ import annotations

import discord
from discord import ui

# Modules metier
from social_media import (
    Platform,
    SocialMediaManager,
    ManualAdapter,
    PLATFORM_LABELS,
    PLATFORM_ICONS,
)
# Design system
from ui_v2 import Palette
from vocabulary import Action as A, Status as S, Module as Mod, Message as Msg
import visuels


# =============================================================================
# HELPERS V2
# =============================================================================

def _container(*items, color=Palette.PRIMARY) -> ui.Container:
    return ui.Container(*items, accent_color=color)


def _title(text: str, level: int = 1) -> ui.TextDisplay:
    prefix = "#" * max(1, min(level, 3))
    return ui.TextDisplay(f"{prefix} {text}")


def _subtitle(text: str) -> ui.TextDisplay:
    return ui.TextDisplay(f"-# {text}")


def _body(text: str) -> ui.TextDisplay:
    return ui.TextDisplay(text)


def _divider() -> ui.Separator:
    return ui.Separator()


def _kv(rows: list[tuple[str, str]]) -> ui.TextDisplay:
    lines = [f"**{k}** — {v}" for k, v in rows]
    return ui.TextDisplay("\n".join(lines))


# =============================================================================
# BASE OWNER-ONLY VIEW
# =============================================================================

class _OwnerView(ui.LayoutView):
    """LayoutView restreinte a l'owner du serveur."""

    def __init__(self, owner: discord.abc.User, guild: discord.Guild, *, timeout: float = 600.0):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            try:
                await interaction.response.send_message(Msg.OWNER_ONLY_PANEL, ephemeral=True)
            except discord.InteractionResponded:
                await interaction.followup.send(Msg.OWNER_ONLY_PANEL, ephemeral=True)
            return False
        return True


# =============================================================================
# MASTER PANEL
# =============================================================================





# =============================================================================
# PERMISSIONS PANEL
# =============================================================================

_global_manager: SocialMediaManager | None = None


def _get_or_create_manager() -> SocialMediaManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = SocialMediaManager()
        # Adapters par defaut : un manuel pour chaque plateforme
        # (les adapters reels Twitch/YouTube se branchent depuis bot.py au demarrage)
        for p in Platform:
            _global_manager.register_adapter(ManualAdapter(p))
    return _global_manager


def set_social_manager(mgr: SocialMediaManager) -> None:
    """Permet a bot.py d'injecter un manager pre-configure (avec Twitch/YT)."""
    global _global_manager
    _global_manager = mgr


def manager_injecte() -> bool:
    """Le manager en place est-il celui du bot, ou une coquille de secours ?

    ⚠️ PIÈGE À NE PAS DÉFAIRE — UN PANNEAU QUI MENT SANS EN AVOIR L'AIR.
    `_get_or_create_manager()` fabrique, si personne n'a injecté, un manager
    garni de `ManualAdapter` seulement. Il liste alors des abonnements que rien
    ne relève : l'écran a l'air normal, et il est faux. Ça n'arrive que si
    `on_ready_addon` a échoué (bot.py journalise « Erreur init
    SocialMediaManager »), mais ce jour-là l'écran doit le DIRE.
    """
    mgr = _get_or_create_manager()
    return any(not isinstance(mgr.get_adapter(p), ManualAdapter)
               for p in Platform if mgr.get_adapter(p) is not None)


#  Le « ◀️ Retour » de ces panneaux ramenait vers `AdminMasterPanelV2`, ouvert
#  par `/admin` — commande RETIRÉE. Le bouton menait donc à un panneau que plus
#  rien n'atteint. bot.py injecte ici le retour vers `/configure`, exactement
#  comme il le fait pour l'activité et la veille Roblox.
_retour_configure = None


def set_retour(fn) -> None:
    global _retour_configure
    _retour_configure = fn


async def _revenir(owner, guild, interaction) -> None:
    """Retour au panneau parent — `/configure`, injecté par bot.py.

    ⚠️ IL N'Y A PLUS DE REPLI. Le repli était `AdminMasterPanelV2`, ouvert par
    `/admin` — commande retirée, panneau supprimé avec la purge d'animation du
    16/08. Sans injection, on le DIT plutôt que d'ouvrir un écran mort ou de
    laisser l'interaction en échec.
    """
    if _retour_configure is not None:
        return await _retour_configure(owner, guild, interaction)
    try:
        await interaction.response.send_message(
            "⚠️ Retour indisponible — rouvrez `/configure`.", ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(
            "⚠️ Retour indisponible — rouvrez `/configure`.", ephemeral=True)


async def _rendre(vue, interaction: discord.Interaction, edit: bool) -> None:
    """Affiche une vue — et supporte une interaction DÉJÀ répondue.

    ⚠️ PIÈGE À NE PAS DÉFAIRE — « L'INTERACTION A ÉCHOUÉ », EN PUBLIC.
    `response.edit_message` et `response.send_message` ne peuvent servir
    qu'UNE fois par interaction. Deux chemins de ces panneaux envoyaient une
    confirmation PUIS réaffichaient l'écran sur la même interaction : le second
    appel levait `InteractionResponded`, et l'écran ne revenait jamais après un
    ajout ou une suppression d'abonnement. Passé la première réponse, la suite
    doit passer par `edit_original_response` / `followup`.
    """
    if edit:
        if interaction.response.is_done():
            await interaction.edit_original_response(
                content=None, view=vue, embed=None, attachments=[])
        else:
            await interaction.response.edit_message(
                view=vue, embed=None, attachments=[])
    else:
        if interaction.response.is_done():
            await interaction.followup.send(view=vue, ephemeral=True)
        else:
            await interaction.response.send_message(view=vue, ephemeral=True)


class SocialMediaPanelV2(_OwnerView):
    """L'onglet « Réseaux sociaux » de `/configure`.

    Ouvert par le propriétaire du serveur depuis le select de sections. Le
    système lui-même (YouTube RSS, RSSHub pour X/TikTok/Instagram) tourne
    indépendamment : ce panneau règle QUI est suivi et OÙ ça tombe.
    """

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        mgr = _get_or_create_manager()
        subs = await mgr.list_subscriptions(self.guild.id)

        # Statut adapters
        configured = mgr.configured_platforms()
        configured_names = ", ".join(PLATFORM_LABELS[p] for p in configured) or "_aucun adapter avec API_"

        self.clear_items()

        # Liste des subs (max 10)
        subs_lines = []
        for s in subs[:10]:
            chan = self.guild.get_channel(s.target_channel_id)
            chan_str = chan.mention if chan else f"<#{s.target_channel_id}>"
            icon = PLATFORM_ICONS.get(s.platform, "")
            on_off = "✅" if s.enabled else "❌"
            subs_lines.append(f"{on_off} {icon} **{s.display_name}** ({s.handle}) → {chan_str}")
        subs_block = "\n".join(subs_lines) if subs_lines else "_Aucun abonnement configuré_"

        b_add = ui.Button(emoji=visuels.icone("ajouter"), label="Ajouter un abonnement", style=discord.ButtonStyle.success, custom_id="soc_add")
        b_add.callback = self._cb_add
        #  `disabled` plutôt qu'absent : sans abonnement, « Gérer » n'a rien à
        #  gérer, et l'utilisateur doit voir POURQUOI il ne peut pas cliquer.
        b_manage = ui.Button(emoji=visuels.icone("journal"), label="Gérer", style=discord.ButtonStyle.primary, custom_id="soc_manage", disabled=(not subs))
        b_manage.callback = self._cb_manage
        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="soc_back")
        b_back.callback = self._cb_back

        actifs = sum(1 for s in subs if s.enabled)
        items = [
            _title("📡 Réseaux sociaux"),
            _subtitle("Annonce les lives / vidéos / posts dans des salons Discord."),
            _divider(),
            _kv([
                ("Adapters API actifs", configured_names),
                ("Abonnements", f"{len(subs)} · {actifs} actif(s)"),
            ]),
        ]

        #  Le seul cas où l'écran serait faux : on le dit, en rouge, au lieu de
        #  laisser croire que la liste ci-dessous est surveillée.
        if not manager_injecte():
            items.append(_body(
                "🔴 **Le relevé n'est pas branché.** Les abonnements listés ici "
                "ne sont interrogés par personne.\n"
                "-# `on_ready_addon` a échoué au démarrage — voir « Erreur init "
                "SocialMediaManager » dans les journaux. Un redémarrage du bot "
                "rebranche le relevé."))

        items += [
            _divider(),
            _title("Abonnements (10 premiers)", level=3),
            _body(subs_block),
            _divider(),
            _subtitle("Anti-doublons (ID unique par post) et auto-clean si la source supprime."),
            _divider(),
            ui.ActionRow(b_add, b_manage, b_back),
        ]
        self.add_item(_container(*items, color=Palette.ACCENT))

        await _rendre(self, interaction, edit)

    async def _cb_add(self, i: discord.Interaction):
        await SocialAddPanel(self.owner, self.guild).render_to(i)

    async def _cb_manage(self, i: discord.Interaction):
        await SocialManagePanel(self.owner, self.guild).render_to(i)

    async def _cb_back(self, i: discord.Interaction):
        await _revenir(self.owner, self.guild, i)


class SocialAddPanel(_OwnerView):
    """Panneau d'ajout : choix plateforme -> handle (modal) -> channel."""

    def __init__(self, owner, guild, platform: Platform | None = None):
        super().__init__(owner, guild)
        self.platform = platform
        self._handle: str | None = None
        self._display_name: str | None = None

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        self.clear_items()

        if self.platform is None:
            # Seules les plateformes qui RELÈVENT vraiment (20/10/2026 : Kick et Twitch sans clés
            # étaient proposés — un abonnement qui ne publierait jamais rien, sans le dire).
            mgr = _get_or_create_manager()
            actives = [p for p in Platform if mgr.get_adapter(p) is not None
                       and not isinstance(mgr.get_adapter(p), ManualAdapter)]
            absentes = [PLATFORM_LABELS[p] for p in Platform if p not in actives]
            options = [
                discord.SelectOption(
                    label=PLATFORM_LABELS[p], value=p.value,
                    emoji=PLATFORM_ICONS[p],
                ) for p in actives
            ] or [discord.SelectOption(label="Aucune plateforme disponible", value="aucune")]
            sel = ui.Select(placeholder="Choisis la plateforme", options=options, disabled=not actives)
            async def _on_platform(i: discord.Interaction):
                self.platform = Platform(sel.values[0])
                # Ouvre directement le modal pour saisir le handle
                modal = _SocialHandleModal(self)
                await i.response.send_modal(modal)
            sel.callback = _on_platform

            b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="socadd_back")
            async def _back(i: discord.Interaction):
                await SocialMediaPanelV2(self.owner, self.guild).render_to(i)
            b_back.callback = _back

            items = [
                _title("➕ Nouvel abonnement"),
                _subtitle("Étape 1/3 : choisis la plateforme"),
                _divider(),
                ui.ActionRow(sel),
            ]
            if absentes:
                items.append(ui.TextDisplay(
                    "-# Non proposées : " + ", ".join(absentes)
                    + " — pas de flux à relever (Twitch : il faut ses clés dans Railway)."))
            items.append(ui.ActionRow(b_back))
            self.add_item(_container(*items, color=Palette.ACCENT))
        elif self._handle is None:
            # Pas encore de handle, on attend le modal (ne devrait pas arriver normalement)
            modal = _SocialHandleModal(self)
            return await interaction.response.send_modal(modal)
        else:
            # Etape 3 : channel select
            chan_select = ui.ChannelSelect(
                channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                placeholder="Salon où poster les annonces",
            )
            async def _on_chan(i: discord.Interaction):
                chan = chan_select.values[0]
                mgr = _get_or_create_manager()
                await mgr.add_subscription(
                    guild_id=self.guild.id,
                    platform=self.platform,
                    handle=self._handle,
                    target_channel_id=chan.id,
                    display_name=self._display_name or self._handle,
                )
                #  ⚠️ L'ÉCRAN D'ABORD, LA CONFIRMATION ENSUITE. L'inverse
                #  consommait la réponse de l'interaction, et le réaffichage
                #  levait `InteractionResponded` : l'abonnement était bien créé,
                #  mais le panneau ne revenait jamais.
                await SocialMediaPanelV2(self.owner, self.guild).render_to(i)
                await i.followup.send(
                    Msg.SAVED_DETAIL.format(item=f"abonnement {self.platform.value} {self._handle}"),
                    ephemeral=True,
                )
            chan_select.callback = _on_chan

            items = [
                _title("➕ Nouvel abonnement"),
                _subtitle(f"Étape 3/3 : salon de destination"),
                _divider(),
                _kv([
                    ("Plateforme", PLATFORM_LABELS[self.platform]),
                    ("Compte", self._handle),
                    ("Nom affiché", self._display_name or self._handle),
                ]),
                _divider(),
                ui.ActionRow(chan_select),
            ]
            self.add_item(_container(*items, color=Palette.ACCENT))

        await _rendre(self, interaction, edit)


class _SocialHandleModal(ui.Modal, title="Compte à tracker"):
    handle = ui.TextInput(label="Handle / username", placeholder="ex: asmongold (Twitch), MrBeast (YouTube)", max_length=64)
    display = ui.TextInput(label="Nom affiché (facultatif)", required=False, max_length=64)

    def __init__(self, parent: SocialAddPanel):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        self.parent._handle = str(self.handle.value).strip()
        self.parent._display_name = (str(self.display.value).strip() or self.parent._handle)
        await self.parent.render_to(interaction)


class SocialManagePanel(_OwnerView):
    """Liste les subs avec un select pour les editer / supprimer."""

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        mgr = _get_or_create_manager()
        subs = await mgr.list_subscriptions(self.guild.id)

        self.clear_items()

        if not subs:
            items = [
                _title("📋 Gestion des abonnements"),
                _body("_Aucun abonnement actif._"),
            ]
        else:
            options = []
            for s in subs[:25]:
                chan = self.guild.get_channel(s.target_channel_id)
                chan_name = chan.name if chan else "salon supprimé"
                options.append(discord.SelectOption(
                    label=f"{s.display_name} ({s.platform.value})"[:100],
                    value=s.sub_id,
                    description=f"#{chan_name} · {'on' if s.enabled else 'off'}",
                    emoji=PLATFORM_ICONS.get(s.platform),
                ))
            sel = ui.Select(placeholder="Sélectionne un abonnement", options=options)
            async def _on_sel(i: discord.Interaction):
                sub = next((x for x in subs if x.sub_id == sel.values[0]), None)
                if not sub:
                    return await i.response.send_message(Msg.NOT_FOUND, ephemeral=True)
                await SocialEditPanel(self.owner, self.guild, sub).render_to(i)
            sel.callback = _on_sel

            items = [
                _title("📋 Gestion des abonnements"),
                _subtitle(f"{len(subs)} abonnement(s) configuré(s)"),
                _divider(),
                ui.ActionRow(sel),
            ]

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="socmgr_back")
        async def _back(i: discord.Interaction):
            await SocialMediaPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back
        items.append(_divider())
        items.append(ui.ActionRow(b_back))
        self.add_item(_container(*items, color=Palette.ACCENT))

        await _rendre(self, interaction, edit)


class SocialEditPanel(_OwnerView):
    """Toggle on/off + supprimer une subscription."""

    def __init__(self, owner, guild, subscription):
        super().__init__(owner, guild)
        self.sub = subscription

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        self.clear_items()

        b_toggle = ui.Button(
            emoji=('🔴' if self.sub.enabled else '🟢'), label=("Désactiver" if self.sub.enabled else "Activer"),
            style=(discord.ButtonStyle.secondary if self.sub.enabled else discord.ButtonStyle.success),
            custom_id="socedit_toggle",
        )
        async def _toggle(i: discord.Interaction):
            mgr = _get_or_create_manager()
            updated = await mgr.update_subscription(
                self.guild.id, self.sub.sub_id, enabled=not self.sub.enabled,
            )
            if updated:
                self.sub = updated
            await self.render_to(i)
        b_toggle.callback = _toggle

        b_del = ui.Button(label=A.DELETE_ICON, style=discord.ButtonStyle.danger, custom_id="socedit_del")
        async def _del(i: discord.Interaction):
            mgr = _get_or_create_manager()
            await mgr.remove_subscription(self.guild.id, self.sub.sub_id)
            #  Même ordre que pour l'ajout, et pour la même raison.
            await SocialMediaPanelV2(self.owner, self.guild).render_to(i)
            await i.followup.send(Msg.DELETED.format(item="abonnement"), ephemeral=True)
        b_del.callback = _del

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="socedit_back")
        async def _back(i: discord.Interaction):
            await SocialManagePanel(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        chan = self.guild.get_channel(self.sub.target_channel_id)
        chan_str = chan.mention if chan else f"<#{self.sub.target_channel_id}>"

        items = [
            _title(f"{PLATFORM_ICONS.get(self.sub.platform, '')} {self.sub.display_name}"),
            _subtitle(f"Plateforme : {PLATFORM_LABELS[self.sub.platform]}"),
            _divider(),
            _kv([
                ("Handle", self.sub.handle),
                ("Salon cible", chan_str),
                ("État", "✅ Activé" if self.sub.enabled else "❌ Désactivé"),
                ("Track lives", "✅" if self.sub.track_lives else "❌"),
                ("Track vidéos", "✅" if self.sub.track_videos else "❌"),
                ("Track shorts", "✅" if self.sub.track_shorts else "❌"),
                ("Track posts", "✅" if self.sub.track_posts else "❌"),
            ]),
            _divider(),
            ui.ActionRow(b_toggle, b_del, b_back),
        ]
        self.add_item(_container(*items, color=Palette.ACCENT))

        await _rendre(self, interaction, edit)


# =============================================================================
# PROTECTION PANEL
# =============================================================================

# =============================================================================
# COMMAND SETUP (a appeler depuis bot.py)
# =============================================================================



__all__ = [
    "SocialMediaPanelV2",
    "set_social_manager",
]
