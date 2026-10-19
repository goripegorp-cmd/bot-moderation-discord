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

import permissions as perms_mod
import protection_guards as guards_mod
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


# =============================================================================
# /protection
# =============================================================================

protection_group = app_commands.Group(
    name="protection",
    description="Configurer la protection / antimode (owner only)",
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


# =============================================================================
# /community
# =============================================================================


# =============================================================================
# REGISTRATION
# =============================================================================

def setup_all_commands(bot: discord.Client) -> None:
    """Enregistre tous les groups de commandes 2026 sur le bot."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return
    for grp in (permissions_group, social_group, protection_group):
        try:
            tree.add_command(grp)
        except discord.app_commands.CommandAlreadyRegistered:
            pass


__all__ = [
    "permissions_group",
    "social_group",
    "protection_group",
    "setup_all_commands",
]
