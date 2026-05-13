"""
slash_commands_architecture.py - Slash commands pour la refonte de l'architecture
serveur + roles panels (Phase 3.1).

Groups :
    /architecture analyze   - propose un blueprint sans appliquer
    /architecture apply     - applique le blueprint (avec backup auto)
    /architecture backup    - cree un snapshot manuel
    /architecture backups   - liste les backups
    /architecture restore   - restaure depuis un backup

    /rolespanel create      - cree un nouveau panel (modal pour titre)
    /rolespanel addrole     - ajoute un role au panel
    /rolespanel removerole  - retire un role du panel
    /rolespanel post        - poste/edite le panel dans le salon courant
    /rolespanel list        - liste les panels du serveur
    /rolespanel delete      - supprime un panel
"""
from __future__ import annotations

import discord
from discord import app_commands

import server_architect as architect
import roles_panel as rpanel


def _is_owner_or_admin():
    """Owner du serveur OU admin."""
    async def predicate(i: discord.Interaction) -> bool:
        if i.guild is None:
            await i.response.send_message("Réservé aux serveurs.", ephemeral=True)
            return False
        if i.user.id == i.guild.owner_id or (
            isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator
        ):
            return True
        await i.response.send_message("🚫 Owner ou Admin uniquement.", ephemeral=True)
        return False
    return app_commands.check(predicate)


# =============================================================================
# /architecture
# =============================================================================

architecture_group = app_commands.Group(
    name="architecture",
    description="Refonte automatique de l'architecture du serveur (owner/admin)",
)


@architecture_group.command(
    name="analyze",
    description="Propose une refonte (sans rien appliquer)",
)
@_is_owner_or_admin()
async def architecture_analyze(i: discord.Interaction):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        blueprint = architect.analyze_guild(i.guild)
        # Groupe par theme pour affichage
        by_theme = blueprint.by_theme()
        lines = ["**📐 Blueprint proposé** :", ""]
        for theme, cat_name in blueprint.target_categories:
            proposals = by_theme.get(theme, [])
            if not proposals:
                continue
            lines.append(f"**{cat_name}** · {len(proposals)} salon(s)")
            for p in proposals[:8]:
                lines.append(f"  • `{p.current_name}`")
            if len(proposals) > 8:
                lines.append(f"  _… +{len(proposals) - 8}_")
            lines.append("")
        lines.append(
            "_Utilise_ `/architecture apply` _pour appliquer (backup auto inclus)._"
        )
        text = "\n".join(lines)[:1900]
        await i.followup.send(text, ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="apply",
    description="Applique la refonte (backup auto avant)",
)
@_is_owner_or_admin()
@app_commands.describe(dry_run="True = simule sans rien modifier")
async def architecture_apply(i: discord.Interaction, dry_run: bool = False):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        blueprint = architect.analyze_guild(i.guild)
        report = await architect.apply_blueprint(
            i.guild, blueprint, create_backup=not dry_run, dry_run=dry_run,
        )
        lines = ["**⚙️ Rapport d'application** :", ""]
        if report.backup_id:
            lines.append(f"💾 **Backup avant** : `{report.backup_id}`")
        lines.append(f"📁 Catégories créées : `{len(report.categories_created)}`")
        lines.append(f"📺 Salons déplacés : `{len(report.channels_moved)}`")
        lines.append(f"⚠️ Erreurs : `{len(report.errors)}`")
        if report.errors:
            lines.append("\n**Erreurs** :")
            for e in report.errors[:10]:
                lines.append(f"  • {e}")
        if dry_run:
            lines.insert(1, "🟦 **DRY-RUN** : aucune modification réelle.\n")
        text = "\n".join(lines)[:1900]
        await i.followup.send(text, ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="backup",
    description="Snapshot manuel du serveur (pour restore ulterieur)",
)
@_is_owner_or_admin()
@app_commands.describe(label="Label optionnel pour identifier ce backup")
async def architecture_backup(i: discord.Interaction, label: str = ""):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        backup_id = await architect.backup_state(i.guild, label=label)
        await i.followup.send(
            f"✅ Backup créé : `{backup_id}`{(' — ' + label) if label else ''}",
            ephemeral=True,
        )
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(name="backups", description="Liste les backups du serveur")
@_is_owner_or_admin()
async def architecture_backups(i: discord.Interaction):
    backups = await architect.list_backups(i.guild.id)
    if not backups:
        return await i.response.send_message("_Aucun backup pour ce serveur._", ephemeral=True)
    lines = ["**💾 Backups** :", ""]
    for b in backups[:20]:
        import time
        age_h = (time.time() - b["captured_at"]) / 3600
        age_str = f"{int(age_h)}h" if age_h < 24 else f"{int(age_h/24)}j"
        lines.append(
            f"`{b['backup_id']}` · {age_str} · "
            f"{b['channel_count']} salons / {b['category_count']} cat. · "
            f"{b['size_kb']:.1f} KB"
            + ((" — " + b["label"]) if b["label"] else "")
        )
    await i.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@architecture_group.command(
    name="restore",
    description="Restaure le serveur depuis un backup",
)
@_is_owner_or_admin()
@app_commands.describe(backup_id="ID du backup (cf /architecture backups)")
async def architecture_restore(i: discord.Interaction, backup_id: str):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        report = await architect.restore_state(i.guild, backup_id, dry_run=False)
        lines = [f"**🔄 Restore `{backup_id}`** :", ""]
        lines.append(f"📺 Salons restaurés : `{len(report.channels_moved)}`")
        lines.append(f"⚠️ Erreurs : `{len(report.errors)}`")
        if report.errors:
            lines.append("\n**Erreurs** :")
            for e in report.errors[:10]:
                lines.append(f"  • {e}")
        await i.followup.send("\n".join(lines)[:1900], ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


# =============================================================================
# /rolespanel
# =============================================================================

rolespanel_group = app_commands.Group(
    name="rolespanel",
    description="Panneau self-service pour les rôles de mention (owner/admin)",
)


class _CreatePanelModal(discord.ui.Modal, title="🔔 Nouveau panneau de rôles"):
    title_input = discord.ui.TextInput(
        label="Titre", placeholder="🔔 Mes notifications", max_length=80,
        default="🔔 Mes notifications",
    )
    desc_input = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=400,
        default=("Choisis les sujets qui t'intéressent. Tu seras mentionné "
                 "uniquement sur ceux que tu actives."),
    )

    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = channel_id

    async def on_submit(self, i: discord.Interaction):
        cfg = rpanel.RolesPanelConfig(
            panel_id=rpanel.new_panel_id(),
            guild_id=i.guild.id,
            channel_id=self.channel_id,
            title=str(self.title_input.value),
            description=str(self.desc_input.value),
        )
        await rpanel.upsert_panel(cfg)
        await i.response.send_message(
            f"✅ Panneau créé : `{cfg.panel_id}`\n"
            f"Utilise `/rolespanel addrole panel_id:{cfg.panel_id} ...` pour ajouter des rôles, "
            f"puis `/rolespanel post panel_id:{cfg.panel_id}` pour le poster.",
            ephemeral=True,
        )


@rolespanel_group.command(name="create", description="Crée un nouveau panel de rôles")
@_is_owner_or_admin()
async def rolespanel_create(i: discord.Interaction):
    await i.response.send_modal(_CreatePanelModal(i.channel.id))


@rolespanel_group.command(name="addrole", description="Ajoute un rôle au panel")
@_is_owner_or_admin()
@app_commands.describe(
    panel_id="ID du panel (cf /rolespanel list)",
    role="Rôle à ajouter",
    label="Texte du bouton (max 80 chars)",
    emoji="Emoji optionnel (unicode)",
    description="Texte d'aide (optionnel)",
)
async def rolespanel_addrole(
    i: discord.Interaction,
    panel_id: str,
    role: discord.Role,
    label: str,
    emoji: str = "",
    description: str = "",
):
    cfg = await rpanel.get_panel(i.guild.id, panel_id)
    if not cfg:
        return await i.response.send_message(f"❌ Panel `{panel_id}` introuvable.", ephemeral=True)
    if any(r.role_id == role.id for r in cfg.roles):
        return await i.response.send_message(f"❌ {role.mention} est déjà dans ce panel.", ephemeral=True)
    if len(cfg.roles) >= 25:
        return await i.response.send_message("❌ Maximum 25 rôles par panel.", ephemeral=True)
    if role.managed:
        return await i.response.send_message("❌ Ce rôle est managé par une intégration.", ephemeral=True)
    cfg.roles.append(rpanel.RolesPanelRole(
        role_id=role.id, label=label[:80], emoji=emoji or None,
        description=description[:200] if description else "",
    ))
    await rpanel.upsert_panel(cfg)
    await i.response.send_message(
        f"✅ {role.mention} ajouté au panel `{panel_id}`. "
        f"Repost avec `/rolespanel post panel_id:{panel_id}` pour appliquer.",
        ephemeral=True,
    )


@rolespanel_group.command(name="removerole", description="Retire un rôle du panel")
@_is_owner_or_admin()
@app_commands.describe(panel_id="ID du panel", role="Rôle à retirer")
async def rolespanel_removerole(
    i: discord.Interaction, panel_id: str, role: discord.Role,
):
    cfg = await rpanel.get_panel(i.guild.id, panel_id)
    if not cfg:
        return await i.response.send_message(f"❌ Panel `{panel_id}` introuvable.", ephemeral=True)
    before = len(cfg.roles)
    cfg.roles = [r for r in cfg.roles if r.role_id != role.id]
    if len(cfg.roles) == before:
        return await i.response.send_message(f"❌ {role.mention} pas dans ce panel.", ephemeral=True)
    await rpanel.upsert_panel(cfg)
    await i.response.send_message(
        f"✅ {role.mention} retiré du panel `{panel_id}`. "
        f"Repost avec `/rolespanel post panel_id:{panel_id}`.",
        ephemeral=True,
    )


@rolespanel_group.command(name="post", description="Poste (ou met à jour) le panel")
@_is_owner_or_admin()
@app_commands.describe(panel_id="ID du panel")
async def rolespanel_post(i: discord.Interaction, panel_id: str):
    cfg = await rpanel.get_panel(i.guild.id, panel_id)
    if not cfg:
        return await i.response.send_message(f"❌ Panel `{panel_id}` introuvable.", ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    msg_id = await rpanel.post_or_update_panel(i.client, cfg)
    if msg_id:
        chan = i.guild.get_channel(cfg.channel_id)
        await i.followup.send(
            f"✅ Panel posté/mis à jour dans {chan.mention if chan else cfg.channel_id} "
            f"(message ID `{msg_id}`)",
            ephemeral=True,
        )
    else:
        await i.followup.send("❌ Échec du post/edit. Permissions ?", ephemeral=True)


@rolespanel_group.command(name="list", description="Liste les panels du serveur")
@_is_owner_or_admin()
async def rolespanel_list(i: discord.Interaction):
    panels = await rpanel.load_panels(i.guild.id)
    if not panels:
        return await i.response.send_message("_Aucun panel configuré._", ephemeral=True)
    lines = ["**🔔 Panels de rôles** :", ""]
    for cfg in panels[:20]:
        chan = i.guild.get_channel(cfg.channel_id)
        chan_str = chan.mention if chan else f"<#{cfg.channel_id}>"
        lines.append(
            f"`{cfg.panel_id}` · **{cfg.title}** · {chan_str} · "
            f"{len(cfg.roles)} rôle(s)"
            + (f" · msg `{cfg.message_id}`" if cfg.message_id else " · _non posté_")
        )
    await i.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@rolespanel_group.command(name="delete", description="Supprime un panel (config seulement)")
@_is_owner_or_admin()
@app_commands.describe(panel_id="ID du panel à supprimer")
async def rolespanel_delete(i: discord.Interaction, panel_id: str):
    ok = await rpanel.delete_panel(i.guild.id, panel_id)
    if ok:
        await i.response.send_message(
            f"✅ Panel `{panel_id}` supprimé de la config.\n"
            f"_Le message Discord reste posté — supprime-le manuellement si voulu._",
            ephemeral=True,
        )
    else:
        await i.response.send_message(f"❌ Panel `{panel_id}` introuvable.", ephemeral=True)


# =============================================================================
# REGISTRATION
# =============================================================================

def setup_architecture_commands(bot) -> None:
    """Enregistre les groupes /architecture et /rolespanel."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return
    for grp in (architecture_group, rolespanel_group):
        try:
            tree.add_command(grp)
        except discord.app_commands.CommandAlreadyRegistered:
            pass


__all__ = [
    "architecture_group",
    "rolespanel_group",
    "setup_architecture_commands",
]
