"""
slash_commands_2026.py - Slash commands granulaires pour les modules 2026.

Complement des panneaux V2 : pour les power-users qui veulent aller vite,
chaque module expose un command group avec sous-commandes.

Groups :
    /permissions show / allow / deny / sanctionable / reset
    /social        add / list / remove / toggle / poll_now
    /protection    mode / trust / trust_user / audit
    /backup        create / list / restore / delete

Tous les checks owner-only sont integres. Les options sont fortement typees
(Role, User, Channel, Choice) pour un autocomplete propre cote Discord.

Integration dans bot.py :
    from slash_commands_2026 import setup_all_commands
    setup_all_commands(bot)
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import permissions as perms_mod
import protection_guards as guards_mod
import community_features as comm_mod
import social_media as social_mod
from vocabulary import Message as Msg, Status as S


# =============================================================================
# GUARDS
# =============================================================================

def _is_owner_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Cette commande est réservée aux serveurs.", ephemeral=True,
            )
            return False
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(Msg.NOT_OWNER, ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


# =============================================================================
# /permissions
# =============================================================================

permissions_group = app_commands.Group(
    name="permissions",
    description="Configurer les permissions granulaires (owner only)",
)


@permissions_group.command(name="show", description="Affiche la config actuelle des permissions")
@_is_owner_check()
async def perm_show(interaction: discord.Interaction):
    cfg = await perms_mod.load_permissions(interaction.guild.id)
    cmd_lines = []
    for cmd_id, rule in list(cfg.commands.items())[:15]:
        allow = ",".join(str(r) for r in rule.allow_roles) or "—"
        deny = ",".join(str(r) for r in rule.deny_roles) or "—"
        cmd_lines.append(f"`{cmd_id}` : default=`{rule.default}` allow=[{allow}] deny=[{deny}]")
    cat_lines = []
    for cat_id, rule in list(cfg.categories.items())[:15]:
        allow = ",".join(str(r) for r in rule.allow_roles) or "—"
        deny = ",".join(str(r) for r in rule.deny_roles) or "—"
        cat_lines.append(f"`{cat_id}` : default=`{rule.default}` allow=[{allow}] deny=[{deny}]")
    sanct_roles = ",".join(f"<@&{r}>" for r in cfg.sanctionable.non_sanctionable_roles) or "—"
    sanct_users = ",".join(f"<@{u}>" for u in cfg.sanctionable.non_sanctionable_users) or "—"

    parts = ["**🔐 Permissions actuelles**", ""]
    if cmd_lines:
        parts.append("**Commandes** :")
        parts.extend(cmd_lines)
        parts.append("")
    if cat_lines:
        parts.append("**Catégories** :")
        parts.extend(cat_lines)
        parts.append("")
    parts.append(f"**Rôles non-sanctionnables** : {sanct_roles}")
    parts.append(f"**Membres non-sanctionnables** : {sanct_users}")

    await interaction.response.send_message("\n".join(parts)[:1900], ephemeral=True)


@permissions_group.command(name="allow", description="Autorise un rôle pour une commande ou catégorie")
@_is_owner_check()
@app_commands.describe(
    target="Type cible (commande ou catégorie)",
    name="ID de la commande ou nom de la catégorie",
    role="Rôle à autoriser",
)
@app_commands.choices(target=[
    app_commands.Choice(name="Commande", value="command"),
    app_commands.Choice(name="Catégorie", value="category"),
])
async def perm_allow(
    interaction: discord.Interaction,
    target: app_commands.Choice[str],
    name: str,
    role: discord.Role,
):
    cfg = await perms_mod.load_permissions(interaction.guild.id)
    target_dict = cfg.commands if target.value == "command" else cfg.categories
    rule = target_dict.setdefault(name, perms_mod.PermissionRule())
    if role.id not in rule.allow_roles:
        rule.allow_roles.append(role.id)
    await perms_mod.save_permissions(interaction.guild.id, cfg)
    await interaction.response.send_message(
        f"{S.DONE_ICON} {role.mention} ALLOW pour {target.value} `{name}`.",
        ephemeral=True,
    )


@permissions_group.command(name="deny", description="Refuse un rôle pour une commande ou catégorie")
@_is_owner_check()
@app_commands.describe(
    target="Type cible (commande ou catégorie)",
    name="ID de la commande ou nom de la catégorie",
    role="Rôle à refuser",
)
@app_commands.choices(target=[
    app_commands.Choice(name="Commande", value="command"),
    app_commands.Choice(name="Catégorie", value="category"),
])
async def perm_deny(
    interaction: discord.Interaction,
    target: app_commands.Choice[str],
    name: str,
    role: discord.Role,
):
    cfg = await perms_mod.load_permissions(interaction.guild.id)
    target_dict = cfg.commands if target.value == "command" else cfg.categories
    rule = target_dict.setdefault(name, perms_mod.PermissionRule())
    if role.id not in rule.deny_roles:
        rule.deny_roles.append(role.id)
    await perms_mod.save_permissions(interaction.guild.id, cfg)
    await interaction.response.send_message(
        f"{S.DONE_ICON} {role.mention} DENY pour {target.value} `{name}`.",
        ephemeral=True,
    )


@permissions_group.command(name="sanctionable", description="Marque un rôle sanctionnable ou non")
@_is_owner_check()
@app_commands.describe(
    role="Rôle concerné",
    state="Sanctionnable ou non",
)
@app_commands.choices(state=[
    app_commands.Choice(name="Sanctionnable (autoriser)", value="on"),
    app_commands.Choice(name="Non sanctionnable (immuniser)", value="off"),
])
async def perm_sanct(
    interaction: discord.Interaction,
    role: discord.Role,
    state: app_commands.Choice[str],
):
    cfg = await perms_mod.load_permissions(interaction.guild.id)
    if state.value == "off":
        if role.id not in cfg.sanctionable.non_sanctionable_roles:
            cfg.sanctionable.non_sanctionable_roles.append(role.id)
        msg = f"{S.DONE_ICON} {role.mention} est **non-sanctionnable**."
    else:
        cfg.sanctionable.non_sanctionable_roles = [
            r for r in cfg.sanctionable.non_sanctionable_roles if r != role.id
        ]
        msg = f"{S.DONE_ICON} {role.mention} redevient sanctionnable."
    await perms_mod.save_permissions(interaction.guild.id, cfg)
    await interaction.response.send_message(msg, ephemeral=True)


# =============================================================================
# /social
# =============================================================================

social_group = app_commands.Group(
    name="social",
    description="Tracker des comptes réseaux sociaux (owner only)",
)


_PLATFORM_CHOICES = [
    app_commands.Choice(name=social_mod.PLATFORM_LABELS[p], value=p.value)
    for p in social_mod.Platform
]


def _get_social_manager() -> social_mod.SocialMediaManager:
    """Recupere le manager (instance globale gere par admin_panels_v2)."""
    from admin_panels_v2 import _get_or_create_manager
    return _get_or_create_manager()


@social_group.command(name="add", description="Ajoute un abonnement à un compte externe")
@_is_owner_check()
@app_commands.describe(
    platform="Plateforme",
    handle="Username/handle (ex: asmongold, MrBeast)",
    channel="Salon où poster les annonces",
    display_name="Nom affiché (optionnel)",
)
@app_commands.choices(platform=_PLATFORM_CHOICES)
async def social_add(
    interaction: discord.Interaction,
    platform: app_commands.Choice[str],
    handle: str,
    channel: discord.TextChannel,
    display_name: str = "",
):
    mgr = _get_social_manager()
    sub = await mgr.add_subscription(
        guild_id=interaction.guild.id,
        platform=social_mod.Platform(platform.value),
        handle=handle,
        target_channel_id=channel.id,
        display_name=display_name or handle,
    )
    await interaction.response.send_message(
        f"{S.DONE_ICON} Abonnement ajouté : `{sub.sub_id}` "
        f"({platform.name} **{handle}** → {channel.mention})",
        ephemeral=True,
    )


@social_group.command(name="list", description="Liste les abonnements actifs")
@_is_owner_check()
async def social_list(interaction: discord.Interaction):
    mgr = _get_social_manager()
    subs = await mgr.list_subscriptions(interaction.guild.id)
    if not subs:
        return await interaction.response.send_message(
            "_Aucun abonnement actif._", ephemeral=True,
        )
    lines = []
    for s in subs:
        chan = interaction.guild.get_channel(s.target_channel_id)
        chan_str = chan.mention if chan else f"<#{s.target_channel_id}>"
        icon = social_mod.PLATFORM_ICONS.get(s.platform, "")
        on_off = "✅" if s.enabled else "❌"
        lines.append(f"{on_off} {icon} `{s.sub_id}` **{s.display_name}** ({s.handle}) → {chan_str}")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@social_group.command(name="remove", description="Supprime un abonnement par son ID")
@_is_owner_check()
@app_commands.describe(sub_id="ID de l'abonnement (cf /social list)")
async def social_remove(interaction: discord.Interaction, sub_id: str):
    mgr = _get_social_manager()
    ok = await mgr.remove_subscription(interaction.guild.id, sub_id)
    if ok:
        await interaction.response.send_message(
            f"{S.DONE_ICON} Abonnement `{sub_id}` supprimé.", ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            f"{S.ERROR_ICON} Abonnement `{sub_id}` introuvable.", ephemeral=True,
        )


@social_group.command(name="toggle", description="Active/désactive un abonnement")
@_is_owner_check()
@app_commands.describe(sub_id="ID de l'abonnement")
async def social_toggle(interaction: discord.Interaction, sub_id: str):
    mgr = _get_social_manager()
    subs = await mgr.list_subscriptions(interaction.guild.id)
    sub = next((s for s in subs if s.sub_id == sub_id), None)
    if not sub:
        return await interaction.response.send_message(
            f"{S.ERROR_ICON} Abonnement introuvable.", ephemeral=True,
        )
    updated = await mgr.update_subscription(
        interaction.guild.id, sub_id, enabled=not sub.enabled,
    )
    state = "✅ activé" if updated.enabled else "❌ désactivé"
    await interaction.response.send_message(
        f"{S.DONE_ICON} Abonnement `{sub_id}` {state}.", ephemeral=True,
    )


@social_group.command(name="poll_now", description="Force un poll immédiat de toutes les souscriptions")
@_is_owner_check()
async def social_poll_now(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    mgr = _get_social_manager()
    subs = await mgr.list_subscriptions(interaction.guild.id)
    total_created = 0
    for s in subs:
        try:
            total_created += await mgr.poll_subscription(s)
        except Exception:
            pass
    await interaction.followup.send(
        f"{S.DONE_ICON} Poll terminé. {total_created} nouvelle(s) annonce(s) créée(s).",
        ephemeral=True,
    )


# =============================================================================
# /protection
# =============================================================================

protection_group = app_commands.Group(
    name="protection",
    description="Configurer la protection / antimode (owner only)",
)


@protection_group.command(name="mode", description="Change le mode de protection")
@_is_owner_check()
@app_commands.describe(mode="Mode de protection")
@app_commands.choices(mode=[
    app_commands.Choice(name="Normal (sanctions auto)", value="normal"),
    app_commands.Choice(name="Soft (log uniquement)", value="soft"),
    app_commands.Choice(name="Review (file de revue staff)", value="review"),
])
async def prot_mode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    policy = await guards_mod.load_policy(interaction.guild.id)
    if mode.value == "soft":
        policy.soft_mode = True
        policy.review_mode = False
    elif mode.value == "review":
        policy.soft_mode = False
        policy.review_mode = True
    else:
        policy.soft_mode = False
        policy.review_mode = False
    await guards_mod.save_policy(interaction.guild.id, policy)
    await interaction.response.send_message(
        f"{S.DONE_ICON} Mode de protection : **{mode.name}**.", ephemeral=True,
    )


@protection_group.command(name="trust", description="Active/désactive le trust boost (vétérans protégés)")
@_is_owner_check()
@app_commands.describe(state="Activer ou désactiver")
@app_commands.choices(state=[
    app_commands.Choice(name="Activer", value="on"),
    app_commands.Choice(name="Désactiver", value="off"),
])
async def prot_trust(interaction: discord.Interaction, state: app_commands.Choice[str]):
    policy = await guards_mod.load_policy(interaction.guild.id)
    policy.trust_boost_enabled = (state.value == "on")
    await guards_mod.save_policy(interaction.guild.id, policy)
    await interaction.response.send_message(
        f"{S.DONE_ICON} Trust boost {'activé' if policy.trust_boost_enabled else 'désactivé'}.",
        ephemeral=True,
    )


@protection_group.command(name="trust_user", description="Ajoute/retire un utilisateur de la whitelist")
@_is_owner_check()
@app_commands.describe(
    user="Utilisateur",
    action="Ajouter ou retirer",
)
@app_commands.choices(action=[
    app_commands.Choice(name="Ajouter à la whitelist", value="add"),
    app_commands.Choice(name="Retirer de la whitelist", value="remove"),
])
async def prot_trust_user(
    interaction: discord.Interaction,
    user: discord.Member,
    action: app_commands.Choice[str],
):
    policy = await guards_mod.load_policy(interaction.guild.id)
    if action.value == "add":
        if user.id not in policy.trusted_user_ids:
            policy.trusted_user_ids.append(user.id)
        msg = f"{user.mention} ajouté à la whitelist (jamais sanctionné automatiquement)."
    else:
        policy.trusted_user_ids = [u for u in policy.trusted_user_ids if u != user.id]
        msg = f"{user.mention} retiré de la whitelist."
    await guards_mod.save_policy(interaction.guild.id, policy)
    await interaction.response.send_message(f"{S.DONE_ICON} {msg}", ephemeral=True)


@protection_group.command(name="audit", description="Affiche les N dernières décisions auto")
@_is_owner_check()
@app_commands.describe(limit="Nombre d'entrées à afficher (max 30)")
async def prot_audit(interaction: discord.Interaction, limit: int = 10):
    limit = max(1, min(limit, 30))
    entries = await guards_mod.read_audit(interaction.guild.id, limit=limit)
    if not entries:
        return await interaction.response.send_message(
            "_Aucune entrée dans l'audit log._", ephemeral=True,
        )
    lines = ["**📋 Audit log — dernières décisions** :", ""]
    for e in entries[-limit:]:
        ts = e.timestamp.split("T")[1][:8] if "T" in e.timestamp else e.timestamp
        lines.append(
            f"`{ts}` {e.user_name} · {e.event_type} · "
            f"{e.proposed_action}→**{e.final_action}** · trust={e.trust_score} · {e.reason}"
        )
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


# =============================================================================
# /community
# =============================================================================

community_group = app_commands.Group(
    name="community",
    description="Configurer les features communautaires (owner only)",
)


_FEATURE_CHOICES = [
    app_commands.Choice(name="Daily question",      value="daily_conversation_enabled"),
    app_commands.Choice(name="Member spotlight",    value="member_spotlight_enabled"),
    app_commands.Choice(name="Welcome quickstart",  value="welcome_quickstart_enabled"),
    app_commands.Choice(name="Activity reactions",  value="activity_recognition_enabled"),
    app_commands.Choice(name="Inactivity nudge",    value="inactivity_nudge_enabled"),
    app_commands.Choice(name="Theme days",          value="theme_days_enabled"),
    app_commands.Choice(name="Weekly digest",       value="weekly_digest_enabled"),
]


@community_group.command(name="toggle", description="Active/désactive une feature communautaire")
@_is_owner_check()
@app_commands.describe(feature="Feature à toggle")
@app_commands.choices(feature=_FEATURE_CHOICES)
async def comm_toggle(
    interaction: discord.Interaction,
    feature: app_commands.Choice[str],
):
    cfg = await comm_mod.load_config(interaction.guild.id)
    new_state = not getattr(cfg, feature.value)
    setattr(cfg, feature.value, new_state)
    await comm_mod.save_config(interaction.guild.id, cfg)
    await interaction.response.send_message(
        f"{S.DONE_ICON} **{feature.name}** : {'✅ activée' if new_state else '❌ désactivée'}.",
        ephemeral=True,
    )


@community_group.command(name="show", description="Affiche l'état des features communautaires")
@_is_owner_check()
async def comm_show(interaction: discord.Interaction):
    cfg = await comm_mod.load_config(interaction.guild.id)
    lines = ["**💬 Features communautaires** :", ""]
    pairs = [
        ("Daily question",      cfg.daily_conversation_enabled, cfg.daily_conversation_channel_id),
        ("Member spotlight",    cfg.member_spotlight_enabled, cfg.member_spotlight_channel_id),
        ("Welcome quickstart",  cfg.welcome_quickstart_enabled, cfg.welcome_quickstart_channel_id),
        ("Activity reactions",  cfg.activity_recognition_enabled, None),
        ("Inactivity nudge",    cfg.inactivity_nudge_enabled, None),
        ("Theme days",          cfg.theme_days_enabled, cfg.theme_days_channel_id),
        ("Weekly digest",       cfg.weekly_digest_enabled, cfg.weekly_digest_channel_id),
    ]
    for name, enabled, chan_id in pairs:
        chan_str = f"<#{chan_id}>" if chan_id else "—"
        state = "✅" if enabled else "❌"
        lines.append(f"{state} **{name}** · salon : {chan_str}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# =============================================================================
# REGISTRATION
# =============================================================================

def setup_all_commands(bot: discord.Client) -> None:
    """Enregistre tous les groups de commandes 2026 sur le bot."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return
    for grp in (permissions_group, social_group, protection_group, community_group):
        try:
            tree.add_command(grp)
        except discord.app_commands.CommandAlreadyRegistered:
            pass


__all__ = [
    "permissions_group",
    "social_group",
    "protection_group",
    "community_group",
    "setup_all_commands",
]
