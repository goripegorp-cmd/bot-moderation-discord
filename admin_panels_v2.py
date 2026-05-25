"""
admin_panels_v2.py - Panneaux V2 owner pour les nouveaux modules (Phase 1.5).

Tous les panneaux sont owner-only (interaction_check) et utilisent les helpers
de ui_v2 pour rester coherents avec le design existant.

Panneaux fournis :
    - AdminMasterPanelV2     - Dashboard d'entree avec acces a chaque module
    - PermissionsPanelV2     - Permissions granulaires
    - SocialMediaPanelV2     - Abonnements reseaux sociaux
    - ProtectionPanelV2      - Politique de protection (soft/review/thresholds)
    - CommunityPanelV2       - Features communautaires (toggles)

Integration dans bot.py :
    from admin_panels_v2 import setup_admin_command, AdminMasterPanelV2
    setup_admin_command(bot)  # ajoute /admin

Le slash /admin ouvre le master panneau, qui dispatch vers les sous-panneaux.
"""
from __future__ import annotations

import asyncio
import discord
from discord import ui

# Modules metier
from permissions import (
    load_permissions, save_permissions, reload_permissions,
    PermissionsConfig, PermissionRule,
    COMMAND_CATEGORIES, CATEGORY_LABELS, list_categories,
)
import social_media
from social_media import (
    Platform, PostType, SocialMediaManager, ManualAdapter,
    PLATFORM_LABELS, PLATFORM_ICONS,
)
import protection_guards
from protection_guards import (
    load_policy, save_policy,
    ProtectionPolicy, AutoEventType,
)
import community_features
from community_features import (
    load_config as load_community_config,
    save_config as save_community_config,
    CommunityConfig,
)
# Design system
from ui_v2 import Palette
from vocabulary import Action as A, Status as S, Module as Mod, Message as Msg


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

class AdminMasterPanelV2(_OwnerView):
    """Dashboard principal owner : acces a chacun des 6 modules."""

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        # Snapshot rapide pour l'apercu
        perms = await load_permissions(self.guild.id)
        cmd_count = len(perms.commands)
        cat_count = len(perms.categories)

        social_subs = []
        try:
            mgr = _get_or_create_manager()
            social_subs = await mgr.list_subscriptions(self.guild.id)
        except Exception:
            pass

        policy = await load_policy(self.guild.id)
        comm_cfg = await load_community_config(self.guild.id)

        self.clear_items()

        b_perms = ui.Button(label=f"🔐 {Mod.PERMISSIONS}", style=discord.ButtonStyle.primary, custom_id="adm_perms")
        b_perms.callback = self._cb_perms
        b_social = ui.Button(label="📡 Reseaux sociaux", style=discord.ButtonStyle.primary, custom_id="adm_social")
        b_social.callback = self._cb_social
        b_prot = ui.Button(label=f"🛡️ {Mod.PROTECTION}", style=discord.ButtonStyle.primary, custom_id="adm_prot")
        b_prot.callback = self._cb_prot
        b_comm = ui.Button(label=f"💬 {Mod.ENGAGEMENT}", style=discord.ButtonStyle.primary, custom_id="adm_comm")
        b_comm.callback = self._cb_comm
        b_close = ui.Button(label=A.CLOSE_ICON, style=discord.ButtonStyle.secondary, custom_id="adm_close")
        b_close.callback = self._cb_close

        protection_status = []
        if policy.soft_mode:
            protection_status.append("Soft mode activé")
        if policy.review_mode:
            protection_status.append("Review mode activé")
        if not protection_status:
            protection_status.append(f"{len(policy.confidence_thresholds)} types d'événements configurés")

        items = [
            _title(f"⚙️ Tableau de bord — {self.guild.name}"),
            _subtitle("Configuration centralisée des nouveaux modules 2026"),
            _divider(),
            _title("📊 Aperçu", level=3),
            _kv([
                ("🔐 Permissions", f"{cmd_count} commande(s), {cat_count} catégorie(s) personnalisées"),
                ("📡 Réseaux sociaux", f"{len(social_subs)} abonnement(s) actif(s)"),
                ("🛡️ Protection", " · ".join(protection_status)),
                ("💬 Engagement", _summary_community(comm_cfg)),
            ]),
            _divider(),
            _subtitle("Choisis un module ci-dessous pour le configurer."),
            _divider(),
            ui.ActionRow(b_perms, b_social, b_prot),
            ui.ActionRow(b_comm, b_close),
        ]
        self.add_item(_container(*items, color=Palette.PRIMARY))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    async def _cb_perms(self, i: discord.Interaction):
        await PermissionsPanelV2(self.owner, self.guild).render_to(i)

    async def _cb_social(self, i: discord.Interaction):
        await SocialMediaPanelV2(self.owner, self.guild).render_to(i)

    async def _cb_prot(self, i: discord.Interaction):
        await ProtectionPanelV2(self.owner, self.guild).render_to(i)

    async def _cb_comm(self, i: discord.Interaction):
        await CommunityPanelV2(self.owner, self.guild).render_to(i)

    async def _cb_close(self, i: discord.Interaction):
        # Phase 3.9 fix : i.message.delete() sur ephemeral échoue silencieusement
        # ET ne ack pas l'interaction → "Échec de l'interaction" en rouge.
        # Pattern bulletproof : edit_message (ack + clear UI) en premier.
        try:
            await i.response.edit_message(
                content="✅ Configuration fermée. Tu peux fermer ce message via *Dismiss*.",
                embed=None, embeds=[], view=None, attachments=[],
            )
        except discord.InteractionResponded:
            try:
                await i.edit_original_response(content="✅ Fermé", embed=None, view=None)
            except Exception:
                pass
        except Exception as ex:
            print(f"[AdminMasterPanelV2 _cb_close] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.defer()
            except Exception:
                pass


def _summary_community(cfg: CommunityConfig) -> str:
    enabled = []
    if cfg.daily_conversation_enabled:
        enabled.append("daily")
    if cfg.member_spotlight_enabled:
        enabled.append("spotlight")
    if cfg.welcome_quickstart_enabled:
        enabled.append("welcome")
    if cfg.activity_recognition_enabled:
        enabled.append("réactions")
    if cfg.inactivity_nudge_enabled:
        enabled.append("nudge")
    if cfg.theme_days_enabled:
        enabled.append("thèmes")
    if cfg.weekly_digest_enabled:
        enabled.append("digest")
    return ", ".join(enabled) if enabled else "rien d'activé"


# =============================================================================
# PERMISSIONS PANEL
# =============================================================================

class PermissionsPanelV2(_OwnerView):
    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        config = await load_permissions(self.guild.id)
        cmd_count = len(config.commands)
        cat_count = len(config.categories)
        non_sanct_count = (
            len(config.sanctionable.non_sanctionable_roles)
            + len(config.sanctionable.non_sanctionable_users)
        )
        bypass_count = sum(
            len(b.roles) + len(b.users) for b in config.bypass.values()
        )

        self.clear_items()

        b_cat = ui.Button(label="📂 Configurer une catégorie", style=discord.ButtonStyle.primary, custom_id="perm_cat")
        b_cat.callback = self._cb_categories
        b_cmd = ui.Button(label="⌨️ Configurer une commande", style=discord.ButtonStyle.primary, custom_id="perm_cmd")
        b_cmd.callback = self._cb_commands
        b_sanct = ui.Button(label="🛡️ Rôles non-sanctionnables", style=discord.ButtonStyle.secondary, custom_id="perm_sanct")
        b_sanct.callback = self._cb_sanctionable
        b_byp = ui.Button(label="🔓 Bypass systèmes", style=discord.ButtonStyle.secondary, custom_id="perm_byp")
        b_byp.callback = self._cb_bypass
        b_reset = ui.Button(label="🔄 Réinitialiser tout", style=discord.ButtonStyle.danger, custom_id="perm_reset")
        b_reset.callback = self._cb_reset
        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="perm_back")
        b_back.callback = self._cb_back

        items = [
            _title(f"🔐 {Mod.PERMISSIONS}"),
            _subtitle("Définis qui peut faire quoi sur ton serveur."),
            _divider(),
            _title("État actuel", level=3),
            _kv([
                ("Commandes personnalisées", str(cmd_count)),
                ("Catégories personnalisées", str(cat_count)),
                ("Roles non-sanctionnables", str(non_sanct_count)),
                ("Bypass actifs", str(bypass_count)),
            ]),
            _divider(),
            _body(
                "**Hiérarchie d'évaluation** :\n"
                "1. Owner du serveur (toujours autorisé)\n"
                "2. Règle de la commande (si définie)\n"
                "3. Règle de la catégorie (sinon)\n"
                "4. Permission Discord native (par défaut sur catégories sensibles)\n"
            ),
            _divider(),
            ui.ActionRow(b_cat, b_cmd),
            ui.ActionRow(b_sanct, b_byp),
            ui.ActionRow(b_reset, b_back),
        ]
        self.add_item(_container(*items, color=Palette.INFO))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    async def _cb_categories(self, i: discord.Interaction):
        await PermissionsCategoriesPanel(self.owner, self.guild).render_to(i)

    async def _cb_commands(self, i: discord.Interaction):
        await i.response.send_message(
            f"{S.INFO_ICON} Configuration par commande : utilise `/permissions cmd <command_id>` (à venir).",
            ephemeral=True,
        )

    async def _cb_sanctionable(self, i: discord.Interaction):
        await SanctionablePanel(self.owner, self.guild).render_to(i)

    async def _cb_bypass(self, i: discord.Interaction):
        await BypassPanel(self.owner, self.guild).render_to(i)

    async def _cb_reset(self, i: discord.Interaction):
        v = _ConfirmView(
            self.owner, self.guild,
            on_confirm=self._reset_action,
            warn_text=Msg.CONFIRM_RESET.format(item="toutes les permissions"),
        )
        await i.response.edit_message(view=v, embed=None, attachments=[])

    async def _reset_action(self, i: discord.Interaction):
        await save_permissions(self.guild.id, PermissionsConfig())
        await i.response.send_message(Msg.SAVED, ephemeral=True)
        await self.render_to(i, edit=False)

    async def _cb_back(self, i: discord.Interaction):
        await AdminMasterPanelV2(self.owner, self.guild).render_to(i)


class PermissionsCategoriesPanel(_OwnerView):
    """Selection d'une categorie a configurer."""

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        config = await load_permissions(self.guild.id)

        self.clear_items()

        # Select avec toutes les categories
        options = []
        for cat in list_categories():
            label = CATEGORY_LABELS.get(cat, cat)
            current = config.categories.get(cat)
            default_str = current.default if current else "allow"
            options.append(discord.SelectOption(
                label=label[:100], value=cat,
                description=f"Défaut : {default_str}",
            ))
        if options:
            select = ui.Select(placeholder="Choisis une catégorie", options=options[:25])
            async def _on_select(i: discord.Interaction):
                cat = select.values[0]
                await CategoryEditPanel(self.owner, self.guild, cat).render_to(i)
            select.callback = _on_select
        else:
            select = None

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="permcat_back")
        b_back.callback = self._cb_back

        items = [
            _title("📂 Configuration par catégorie"),
            _subtitle("Définis le comportement par défaut d'un groupe de commandes."),
            _divider(),
            _body(
                "Une catégorie est un groupe de commandes (ex: Modération = ban, kick, mute, ...).\n"
                "La règle de catégorie s'applique si la commande n'a pas de règle propre."
            ),
            _divider(),
        ]
        if select:
            items.append(ui.ActionRow(select))
        items.append(ui.ActionRow(b_back))
        self.add_item(_container(*items, color=Palette.INFO))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    async def _cb_back(self, i: discord.Interaction):
        await PermissionsPanelV2(self.owner, self.guild).render_to(i)


class CategoryEditPanel(_OwnerView):
    """Edition d'une categorie : default + roles allow/deny."""

    def __init__(self, owner, guild, category: str):
        super().__init__(owner, guild)
        self.category = category

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        config = await load_permissions(self.guild.id)
        rule = config.categories.get(self.category) or PermissionRule(default="inherit")

        allow_roles = [self.guild.get_role(rid) for rid in rule.allow_roles]
        deny_roles = [self.guild.get_role(rid) for rid in rule.deny_roles]
        allow_str = ", ".join(r.mention for r in allow_roles if r) or "_aucun_"
        deny_str = ", ".join(r.mention for r in deny_roles if r) or "_aucun_"

        self.clear_items()

        # Default selector
        default_options = [
            discord.SelectOption(label="✅ Allow", value="allow", description="Autorise par défaut"),
            discord.SelectOption(label="❌ Deny", value="deny", description="Refuse par défaut"),
            discord.SelectOption(label="🛡️ Mod only", value="mod_only", description="Autorise si kick_members"),
            discord.SelectOption(label="↪️ Inherit", value="inherit", description="Hérite (catégorie -> default)"),
        ]
        for opt in default_options:
            opt.default = (opt.value == rule.default)
        sel_default = ui.Select(placeholder=f"Défaut actuel : {rule.default}", options=default_options)
        async def _on_default_change(i: discord.Interaction):
            new_default = sel_default.values[0]
            cfg = await load_permissions(self.guild.id)
            r = cfg.categories.get(self.category) or PermissionRule()
            r.default = new_default
            cfg.categories[self.category] = r
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        sel_default.callback = _on_default_change

        # Role allow/deny
        role_allow = ui.RoleSelect(placeholder="Ajouter rôles ALLOW (override le défaut)", min_values=0, max_values=10)
        async def _on_allow(i: discord.Interaction):
            cfg = await load_permissions(self.guild.id)
            r = cfg.categories.get(self.category) or PermissionRule()
            for role in role_allow.values:
                if role.id not in r.allow_roles:
                    r.allow_roles.append(role.id)
            cfg.categories[self.category] = r
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        role_allow.callback = _on_allow

        role_deny = ui.RoleSelect(placeholder="Ajouter rôles DENY (override le défaut)", min_values=0, max_values=10)
        async def _on_deny(i: discord.Interaction):
            cfg = await load_permissions(self.guild.id)
            r = cfg.categories.get(self.category) or PermissionRule()
            for role in role_deny.values:
                if role.id not in r.deny_roles:
                    r.deny_roles.append(role.id)
            cfg.categories[self.category] = r
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        role_deny.callback = _on_deny

        b_clear = ui.Button(label="🧹 Vider la règle", style=discord.ButtonStyle.danger, custom_id="catedit_clear")
        async def _clear(i: discord.Interaction):
            cfg = await load_permissions(self.guild.id)
            cfg.categories.pop(self.category, None)
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        b_clear.callback = _clear

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="catedit_back")
        async def _back(i: discord.Interaction):
            await PermissionsCategoriesPanel(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        label = CATEGORY_LABELS.get(self.category, self.category)
        items = [
            _title(f"📂 {label}"),
            _subtitle(f"Catégorie `{self.category}`"),
            _divider(),
            _kv([
                ("Défaut", f"`{rule.default}`"),
                ("Rôles ALLOW", allow_str),
                ("Rôles DENY", deny_str),
            ]),
            _divider(),
            _subtitle("Modifie le défaut, ou ajoute des rôles ALLOW/DENY."),
            ui.ActionRow(sel_default),
            ui.ActionRow(role_allow),
            ui.ActionRow(role_deny),
            ui.ActionRow(b_clear, b_back),
        ]
        self.add_item(_container(*items, color=Palette.INFO))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class SanctionablePanel(_OwnerView):
    """Gestion des roles non-sanctionnables."""

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        config = await load_permissions(self.guild.id)
        sc = config.sanctionable

        non_sanct_roles = [self.guild.get_role(r) for r in sc.non_sanctionable_roles]
        non_sanct_users = [self.guild.get_member(u) for u in sc.non_sanctionable_users]
        roles_str = ", ".join(r.mention for r in non_sanct_roles if r) or "_aucun_"
        users_str = ", ".join(u.mention for u in non_sanct_users if u) or "_aucun_"

        self.clear_items()

        role_add = ui.RoleSelect(placeholder="Ajouter un rôle non-sanctionnable", min_values=0, max_values=5)
        async def _on_role(i: discord.Interaction):
            cfg = await load_permissions(self.guild.id)
            for role in role_add.values:
                if role.id not in cfg.sanctionable.non_sanctionable_roles:
                    cfg.sanctionable.non_sanctionable_roles.append(role.id)
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        role_add.callback = _on_role

        user_add = ui.UserSelect(placeholder="Ajouter un membre non-sanctionnable", min_values=0, max_values=5)
        async def _on_user(i: discord.Interaction):
            cfg = await load_permissions(self.guild.id)
            for user in user_add.values:
                if user.id not in cfg.sanctionable.non_sanctionable_users:
                    cfg.sanctionable.non_sanctionable_users.append(user.id)
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        user_add.callback = _on_user

        b_clear = ui.Button(label="🧹 Tout vider", style=discord.ButtonStyle.danger, custom_id="sanct_clear")
        async def _clear(i: discord.Interaction):
            cfg = await load_permissions(self.guild.id)
            cfg.sanctionable.non_sanctionable_roles = []
            cfg.sanctionable.non_sanctionable_users = []
            await save_permissions(self.guild.id, cfg)
            await self.render_to(i)
        b_clear.callback = _clear

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="sanct_back")
        async def _back(i: discord.Interaction):
            await PermissionsPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        items = [
            _title("🛡️ Rôles non-sanctionnables"),
            _subtitle("Personnes immunisées contre ban/kick/mute/warn automatiques."),
            _divider(),
            _kv([
                ("Rôles immunisés", roles_str),
                ("Membres immunisés", users_str),
            ]),
            _divider(),
            _subtitle("Sélectionne un rôle ou un membre à ajouter."),
            ui.ActionRow(role_add),
            ui.ActionRow(user_add),
            ui.ActionRow(b_clear, b_back),
        ]
        self.add_item(_container(*items, color=Palette.SUCCESS))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class BypassPanel(_OwnerView):
    """Bypass d'un systeme antimode."""

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        config = await load_permissions(self.guild.id)

        self.clear_items()

        systems = ["antiraid", "automod", "antispam", "antialt", "antiphishing"]
        rows = []
        for sys_name in systems:
            bp = config.bypass.get(sys_name)
            n_roles = len(bp.roles) if bp else 0
            n_users = len(bp.users) if bp else 0
            rows.append((sys_name, f"{n_roles} rôle(s), {n_users} membre(s)"))

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="byp_back")
        async def _back(i: discord.Interaction):
            await PermissionsPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        items = [
            _title("🔓 Bypass des systèmes"),
            _subtitle("Exempte certains rôles d'un système (anti-raid, automod, etc.)."),
            _divider(),
            _kv(rows),
            _divider(),
            _body(
                "_Pour ajouter un bypass : `/permissions bypass <system> <role>` (slash, à venir)._\n"
                "Les bypass sont **par-système** et **cumulatifs**."
            ),
            _divider(),
            ui.ActionRow(b_back),
        ]
        self.add_item(_container(*items, color=Palette.WARNING))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class _ConfirmView(_OwnerView):
    """View de confirmation generique."""

    def __init__(self, owner, guild, on_confirm, warn_text: str):
        super().__init__(owner, guild)
        self._on_confirm = on_confirm
        self._warn = warn_text

        self.clear_items()
        b_yes = ui.Button(label=A.CONFIRM_ICON, style=discord.ButtonStyle.danger, custom_id="cf_yes")
        b_yes.callback = self._yes
        b_no = ui.Button(label=A.CANCEL_ICON, style=discord.ButtonStyle.secondary, custom_id="cf_no")
        b_no.callback = self._no

        items = [
            _title("⚠️ Confirmation requise"),
            _divider(),
            _body(self._warn),
            _divider(),
            ui.ActionRow(b_yes, b_no),
        ]
        self.add_item(_container(*items, color=Palette.DANGER))

    async def _yes(self, i: discord.Interaction):
        await self._on_confirm(i)

    async def _no(self, i: discord.Interaction):
        await i.response.send_message(Msg.CANCELLED, ephemeral=True)


# =============================================================================
# SOCIAL MEDIA PANEL
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


class SocialMediaPanelV2(_OwnerView):
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

        b_add = ui.Button(label=A.ADD_ICON + " Abonnement", style=discord.ButtonStyle.success, custom_id="soc_add")
        b_add.callback = self._cb_add
        b_manage = ui.Button(label="📋 Gérer", style=discord.ButtonStyle.primary, custom_id="soc_manage", disabled=(not subs))
        b_manage.callback = self._cb_manage
        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="soc_back")
        b_back.callback = self._cb_back

        items = [
            _title("📡 Réseaux sociaux"),
            _subtitle("Annonce les lives / vidéos / posts dans des salons Discord."),
            _divider(),
            _kv([
                ("Adapters API actifs", configured_names),
                ("Abonnements", str(len(subs))),
            ]),
            _divider(),
            _title("Abonnements (10 premiers)", level=3),
            _body(subs_block),
            _divider(),
            _subtitle(
                "🔒 **Anti-doublons** : chaque post a un ID unique, jamais re-publié.\n"
                "🧹 **Auto-clean** : si la source supprime, l'annonce Discord est supprimée."
            ),
            _divider(),
            ui.ActionRow(b_add, b_manage, b_back),
        ]
        self.add_item(_container(*items, color=Palette.ACCENT))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    async def _cb_add(self, i: discord.Interaction):
        await SocialAddPanel(self.owner, self.guild).render_to(i)

    async def _cb_manage(self, i: discord.Interaction):
        await SocialManagePanel(self.owner, self.guild).render_to(i)

    async def _cb_back(self, i: discord.Interaction):
        await AdminMasterPanelV2(self.owner, self.guild).render_to(i)


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
            options = [
                discord.SelectOption(
                    label=PLATFORM_LABELS[p], value=p.value,
                    emoji=PLATFORM_ICONS[p],
                ) for p in Platform
            ]
            sel = ui.Select(placeholder="Choisis la plateforme", options=options)
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
                ui.ActionRow(b_back),
            ]
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
                await i.response.send_message(
                    Msg.SAVED_DETAIL.format(item=f"abonnement {self.platform.value} {self._handle}"),
                    ephemeral=True,
                )
                await SocialMediaPanelV2(self.owner, self.guild).render_to(i, edit=False)
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

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


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

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class SocialEditPanel(_OwnerView):
    """Toggle on/off + supprimer une subscription."""

    def __init__(self, owner, guild, subscription):
        super().__init__(owner, guild)
        self.sub = subscription

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        self.clear_items()

        b_toggle = ui.Button(
            label=("🔴 Désactiver" if self.sub.enabled else "🟢 Activer"),
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
            await i.response.send_message(Msg.DELETED.format(item="abonnement"), ephemeral=True)
            await SocialMediaPanelV2(self.owner, self.guild).render_to(i, edit=False)
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

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


# =============================================================================
# PROTECTION PANEL
# =============================================================================

class ProtectionPanelV2(_OwnerView):
    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        policy = await load_policy(self.guild.id)

        self.clear_items()

        b_soft = ui.Button(
            label=("🔴 Soft mode : ON" if policy.soft_mode else "🟢 Soft mode : OFF"),
            style=discord.ButtonStyle.success if not policy.soft_mode else discord.ButtonStyle.secondary,
            custom_id="prot_soft",
        )
        async def _soft(i: discord.Interaction):
            policy.soft_mode = not policy.soft_mode
            await save_policy(self.guild.id, policy)
            await self.render_to(i)
        b_soft.callback = _soft

        b_review = ui.Button(
            label=("🔴 Review mode : ON" if policy.review_mode else "🟢 Review mode : OFF"),
            style=discord.ButtonStyle.success if not policy.review_mode else discord.ButtonStyle.secondary,
            custom_id="prot_review",
        )
        async def _review(i: discord.Interaction):
            policy.review_mode = not policy.review_mode
            await save_policy(self.guild.id, policy)
            await self.render_to(i)
        b_review.callback = _review

        b_trust = ui.Button(
            label=("🔴 Trust boost : ON" if policy.trust_boost_enabled else "🟢 Trust boost : OFF"),
            style=discord.ButtonStyle.success if not policy.trust_boost_enabled else discord.ButtonStyle.secondary,
            custom_id="prot_trust",
        )
        async def _trust(i: discord.Interaction):
            policy.trust_boost_enabled = not policy.trust_boost_enabled
            await save_policy(self.guild.id, policy)
            await self.render_to(i)
        b_trust.callback = _trust

        b_thr = ui.Button(label="📊 Seuils détection", style=discord.ButtonStyle.primary, custom_id="prot_thr")
        async def _thr(i: discord.Interaction):
            await ProtectionThresholdsPanel(self.owner, self.guild).render_to(i)
        b_thr.callback = _thr

        b_wl = ui.Button(label="📜 Whitelist", style=discord.ButtonStyle.primary, custom_id="prot_wl")
        async def _wl(i: discord.Interaction):
            await ProtectionWhitelistPanel(self.owner, self.guild).render_to(i)
        b_wl.callback = _wl

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="prot_back")
        async def _back(i: discord.Interaction):
            await AdminMasterPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        items = [
            _title("🛡️ Politique de protection"),
            _subtitle("Évite les bans / kicks accidentels avec des garde-fous configurables."),
            _divider(),
            _kv([
                ("Soft mode", "✅ Actif" if policy.soft_mode else "❌ Inactif"),
                ("Review mode", "✅ Actif" if policy.review_mode else "❌ Inactif"),
                ("Trust boost", "✅ Actif" if policy.trust_boost_enabled else "❌ Inactif"),
                ("Whitelist domaines", f"{len(policy.domain_whitelist)} entrée(s)"),
                ("Trusted users", f"{len(policy.trusted_user_ids)} membre(s)"),
                ("Trusted roles", f"{len(policy.trusted_role_ids)} rôle(s)"),
                ("Action storm", f"{policy.action_storm_threshold} actions / {policy.action_storm_window_minutes}min"),
            ]),
            _divider(),
            _body(
                "**Soft mode** : aucune sanction réelle, tout passe en audit.\n"
                "**Review mode** : sanctions au-delà de WARN sont mises en file de revue.\n"
                "**Trust boost** : les vétérans sont protégés des bans automatiques.\n"
            ),
            _divider(),
            ui.ActionRow(b_soft, b_review, b_trust),
            ui.ActionRow(b_thr, b_wl, b_back),
        ]
        self.add_item(_container(*items, color=Palette.WARNING))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class ProtectionThresholdsPanel(_OwnerView):
    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        policy = await load_policy(self.guild.id)

        self.clear_items()

        rows = []
        for evt in AutoEventType:
            t = policy.confidence_thresholds.get(evt.value, {})
            rows.append((
                evt.value,
                f"warn≥{t.get('warn', '?')} mute≥{t.get('mute', '?')} kick≥{t.get('kick', '?')} ban≥{t.get('ban', '?')}",
            ))

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="prot_thr_back")
        async def _back(i: discord.Interaction):
            await ProtectionPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        items = [
            _title("📊 Seuils de détection"),
            _subtitle("Confidence requise pour chaque action automatique"),
            _divider(),
            _kv(rows),
            _divider(),
            _body(
                "Seuils plus hauts = bot plus prudent (moins de bans automatiques).\n"
                "_Édition fine via `/protection threshold <event> <action> <value>` (à venir)._"
            ),
            _divider(),
            ui.ActionRow(b_back),
        ]
        self.add_item(_container(*items, color=Palette.WARNING))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class ProtectionWhitelistPanel(_OwnerView):
    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        policy = await load_policy(self.guild.id)

        self.clear_items()

        domains_preview = ", ".join(policy.domain_whitelist[:10])
        if len(policy.domain_whitelist) > 10:
            domains_preview += f" … (+{len(policy.domain_whitelist) - 10})"

        users_preview = ", ".join(f"<@{u}>" for u in policy.trusted_user_ids[:10]) or "_aucun_"
        roles_preview = ", ".join(f"<@&{r}>" for r in policy.trusted_role_ids[:10]) or "_aucun_"

        role_add = ui.RoleSelect(placeholder="+ rôle de confiance (jamais sanctionnable)", min_values=0, max_values=5)
        async def _on_role(i: discord.Interaction):
            for role in role_add.values:
                if role.id not in policy.trusted_role_ids:
                    policy.trusted_role_ids.append(role.id)
            await save_policy(self.guild.id, policy)
            await self.render_to(i)
        role_add.callback = _on_role

        user_add = ui.UserSelect(placeholder="+ utilisateur de confiance", min_values=0, max_values=5)
        async def _on_user(i: discord.Interaction):
            for user in user_add.values:
                if user.id not in policy.trusted_user_ids:
                    policy.trusted_user_ids.append(user.id)
            await save_policy(self.guild.id, policy)
            await self.render_to(i)
        user_add.callback = _on_user

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="prot_wl_back")
        async def _back(i: discord.Interaction):
            await ProtectionPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        items = [
            _title("📜 Whitelists"),
            _subtitle("Personnes et domaines qui ne déclencheront pas l'automod."),
            _divider(),
            _title("Domaines autorisés", level=3),
            _body(domains_preview),
            _divider(),
            _title("Membres de confiance", level=3),
            _body(users_preview),
            _divider(),
            _title("Rôles de confiance", level=3),
            _body(roles_preview),
            _divider(),
            ui.ActionRow(role_add),
            ui.ActionRow(user_add),
            ui.ActionRow(b_back),
        ]
        self.add_item(_container(*items, color=Palette.WARNING))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


# =============================================================================
# COMMUNITY PANEL
# =============================================================================

class CommunityPanelV2(_OwnerView):
    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        cfg = await load_community_config(self.guild.id)

        self.clear_items()

        def _toggle_btn(label: str, attr: str, custom_id: str):
            current = getattr(cfg, attr)
            btn = ui.Button(
                label=f"{'✅' if current else '⬜'} {label}",
                style=discord.ButtonStyle.success if current else discord.ButtonStyle.secondary,
                custom_id=custom_id,
            )
            async def _cb(i: discord.Interaction):
                setattr(cfg, attr, not current)
                await save_community_config(self.guild.id, cfg)
                await self.render_to(i)
            btn.callback = _cb
            return btn

        b1 = _toggle_btn("Daily question", "daily_conversation_enabled", "comm_daily")
        b2 = _toggle_btn("Member spotlight", "member_spotlight_enabled", "comm_spot")
        b3 = _toggle_btn("Welcome quickstart", "welcome_quickstart_enabled", "comm_welc")
        b4 = _toggle_btn("Reactions activité", "activity_recognition_enabled", "comm_act")
        b5 = _toggle_btn("Inactivity nudge", "inactivity_nudge_enabled", "comm_nudge")
        b6 = _toggle_btn("Theme days", "theme_days_enabled", "comm_theme")
        b7 = _toggle_btn("Weekly digest", "weekly_digest_enabled", "comm_digest")

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="comm_back")
        async def _back(i: discord.Interaction):
            await AdminMasterPanelV2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        items = [
            _title("💬 Engagement communautaire"),
            _subtitle("Active les features qui font vivre ton serveur — sans spammer de pings."),
            _divider(),
            _body(
                "Toutes les features respectent un **budget d'attention** : le bot ne peut pas dépasser "
                "5 réponses subtiles/jour, 1 ping de rôle/semaine, etc. Impossible de saouler les membres."
            ),
            _divider(),
            _title("Features", level=3),
            _kv([
                ("📅 Daily question", "Une question/jour dans un salon"),
                ("⭐ Member spotlight", "Mise en avant hebdo d'un membre actif"),
                ("👋 Welcome quickstart", "Accueil personnalisé avec liens utiles"),
                ("🔥 Reactions activité", "Le bot ajoute 🔥 sur les threads dynamiques"),
                ("💭 Inactivity nudge", "Relance subtile sur un salon silencieux"),
                ("🎯 Theme days", "Jour à thème (Music Monday, etc.)"),
                ("📊 Weekly digest", "Bilan hebdo des stats serveur"),
            ]),
            _divider(),
            ui.ActionRow(b1, b2, b3),
            ui.ActionRow(b4, b5, b6),
            ui.ActionRow(b7, b_back),
        ]
        self.add_item(_container(*items, color=Palette.ACCENT))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


# =============================================================================
# COMMAND SETUP (a appeler depuis bot.py)
# =============================================================================

def setup_admin_command(bot: discord.Client) -> None:
    """Enregistre le slash command /admin sur le bot.

    Usage dans bot.py :
        from admin_panels_v2 import setup_admin_command
        setup_admin_command(bot)
    """
    tree = getattr(bot, "tree", None)
    if tree is None:
        return

    @tree.command(
        name="admin",
        description="Tableau de bord owner (modules 2026)",
    )
    async def _admin_cmd(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Cette commande est réservée aux serveurs.", ephemeral=True,
            )
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                Msg.NOT_OWNER, ephemeral=True,
            )
        view = AdminMasterPanelV2(interaction.user, interaction.guild)
        await view.render_to(interaction, edit=False)


__all__ = [
    "AdminMasterPanelV2",
    "PermissionsPanelV2",
    "SocialMediaPanelV2",
    "ProtectionPanelV2",
    "CommunityPanelV2",
    "set_social_manager",
    "setup_admin_command",
]
