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

from typing import Optional

import discord
from discord import app_commands

import server_architect as architect
import roles_panel as rpanel
import custom_blueprint as cblueprint
import architecture_builder as builder


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
    name="move_channel",
    description="Deplace manuellement un salon vers une categorie (controle fin)",
)
@_is_owner_or_admin()
@app_commands.describe(
    channel="Salon a deplacer",
    category="Categorie cible (vide = pas de categorie)",
)
async def architecture_move_channel(
    i: discord.Interaction,
    channel: discord.abc.GuildChannel,
    category: Optional[discord.CategoryChannel] = None,
):
    await i.response.defer(ephemeral=True, thinking=False)
    try:
        await channel.edit(category=category, reason=f"Move manuel par {i.user.name}")
        cat_name = category.name if category else "_aucune_"
        await i.followup.send(
            f"✅ {channel.mention} déplacé vers **{cat_name}**", ephemeral=True,
        )
    except discord.Forbidden:
        await i.followup.send("❌ Permissions manquantes.", ephemeral=True)
    except Exception as ex:
        await i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)


@architecture_group.command(
    name="delete_empty",
    description="Supprime toutes les categories vides (utile apres une refonte)",
)
@_is_owner_or_admin()
@app_commands.describe(dry_run="True = simule sans supprimer")
async def architecture_delete_empty(i: discord.Interaction, dry_run: bool = False):
    await i.response.defer(ephemeral=True, thinking=True)
    deleted = []
    errors = []
    for cat in list(i.guild.categories):
        if len(cat.channels) > 0:
            continue
        if dry_run:
            deleted.append(f"[dry-run] {cat.name}")
            continue
        try:
            await cat.delete(reason=f"Cleanup categorie vide par {i.user.name}")
            deleted.append(cat.name)
            await __import__('asyncio').sleep(0.3)
        except Exception as ex:
            errors.append(f"{cat.name}: {ex}")
    lines = [f"**🗑️ Catégories vides** :", "",
             f"Supprimées : `{len(deleted)}`"]
    for d in deleted[:15]:
        lines.append(f"  • {d}")
    if errors:
        lines.append(f"\n⚠️ Erreurs : `{len(errors)}`")
        for e in errors[:5]:
            lines.append(f"  • {e}")
    await i.followup.send("\n".join(lines)[:1900], ephemeral=True)


@architecture_group.command(
    name="rename_category",
    description="Renomme une categorie (correction post-refonte)",
)
@_is_owner_or_admin()
@app_commands.describe(category="Categorie a renommer", new_name="Nouveau nom")
async def architecture_rename_category(
    i: discord.Interaction,
    category: discord.CategoryChannel,
    new_name: str,
):
    await i.response.defer(ephemeral=True, thinking=False)
    try:
        old_name = category.name
        await category.edit(name=new_name[:100], reason=f"Rename par {i.user.name}")
        await i.followup.send(
            f"✅ Catégorie renommée : **{old_name}** → **{new_name}**", ephemeral=True,
        )
    except Exception as ex:
        await i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)


@architecture_group.command(
    name="preview_preset",
    description="Apercu detaille d'un preset (sans rien appliquer)",
)
@_is_owner_or_admin()
@app_commands.describe(preset="Type de preset")
@app_commands.choices(preset=[
    app_commands.Choice(name="Game Development Studio", value="gamedev"),
    app_commands.Choice(name="Communauté de Créateur", value="streamer"),
    app_commands.Choice(name="Communauté Gaming", value="gaming"),
    app_commands.Choice(name="Communauté Généraliste", value="community"),
])
async def architecture_preview_preset(
    i: discord.Interaction, preset: app_commands.Choice[str],
):
    bp = cblueprint.PRESETS.get(preset.value)
    if not bp:
        return await i.response.send_message("❌ Preset inconnu.", ephemeral=True)
    lines = [
        f"**📐 Preset `{preset.name}`**",
        f"_{bp.description}_",
        "",
        f"**{len(bp.categories)} catégories · "
        f"{sum(len(c.channels) for c in bp.categories)} salons · "
        f"{len(bp.roles)} rôles · "
        f"{len(bp.mention_roles)} rôles de mention**",
        "",
    ]
    for cat in bp.categories[:15]:
        lines.append(f"**{cat.name}** ({len(cat.channels)} salons)")
        for ch in cat.channels[:6]:
            icon = "🔊" if ch.ctype == "voice" else "📰" if ch.ctype == "announcement" else "💬"
            lines.append(f"  {icon} {ch.name}")
        if len(cat.channels) > 6:
            lines.append(f"  _… +{len(cat.channels) - 6} salons_")
    if len(bp.categories) > 15:
        lines.append(f"_… +{len(bp.categories) - 15} catégories_")
    lines.append("")
    lines.append("**Rôles à créer** :")
    for r in bp.roles:
        flags = []
        if r.hoist: flags.append("hoist")
        if "administrator" in r.permissions: flags.append("admin")
        elif r.permissions: flags.append(f"{len(r.permissions)} perms")
        flags_str = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"  • **{r.name}**{flags_str}")
    lines.append("")
    lines.append(
        f"_Pour l'appliquer :_ `/architecture build_preset preset:{preset.value}`"
    )
    await i.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@architecture_group.command(
    name="build_preset",
    description="WIPE + reconstruit le serveur depuis un preset (avec backup auto)",
)
@_is_owner_or_admin()
@app_commands.describe(
    preset="Type de preset a appliquer",
    confirmation="Tape exactement : RECONSTRUIRE pour confirmer",
    wipe_first="True (par defaut) = detruit tout avant de reconstruire",
    dry_run="True = simule sans rien faire",
)
@app_commands.choices(preset=[
    app_commands.Choice(name="Game Development Studio", value="gamedev"),
    app_commands.Choice(name="Communauté de Créateur", value="streamer"),
    app_commands.Choice(name="Communauté Gaming", value="gaming"),
    app_commands.Choice(name="Communauté Généraliste", value="community"),
])
async def architecture_build_preset(
    i: discord.Interaction,
    preset: app_commands.Choice[str],
    confirmation: str = "",
    wipe_first: bool = True,
    dry_run: bool = True,
):
    # Owner uniquement (pas admin) si on wipe
    if wipe_first and not dry_run and i.user.id != i.guild.owner_id:
        return await i.response.send_message(
            "❌ Seul le **propriétaire du serveur** peut faire un wipe+rebuild.",
            ephemeral=True,
        )
    if wipe_first and not dry_run and confirmation != "RECONSTRUIRE":
        return await i.response.send_message(
            "❌ Pour confirmer le WIPE + REBUILD, tape exactement `RECONSTRUIRE` "
            "dans le champ confirmation.\n"
            "Sinon utilise `dry_run:True` pour simuler.",
            ephemeral=True,
        )

    bp = cblueprint.PRESETS.get(preset.value)
    if not bp:
        return await i.response.send_message("❌ Preset inconnu.", ephemeral=True)

    await i.response.defer(ephemeral=True, thinking=True)
    try:
        report = await cblueprint.apply_blueprint(
            i.guild, bp, wipe_first=wipe_first, dry_run=dry_run,
        )
        lines = [
            f"**🏗️ Build preset `{preset.name}`** :", "",
        ]
        if dry_run:
            lines.append("🟦 **DRY-RUN** : rien n'a ete fait.\n")
        if report.backup_id:
            lines.append(f"💾 Backup avant : `{report.backup_id}` (pour rollback)")
        lines.append(f"📁 Catégories créées : `{len(report.categories_created)}`")
        lines.append(f"📺 Salons créés : `{len(report.channels_created)}`")
        lines.append(f"🎭 Rôles créés : `{len(report.roles_created)}`")
        lines.append(f"⚠️ Erreurs : `{len(report.errors)}`")
        if report.errors:
            lines.append("\n**Erreurs** :")
            for e in report.errors[:10]:
                lines.append(f"  • {e}")
        if not dry_run and not report.errors:
            lines.append(
                "\n✅ **Reconstruction réussie**. "
                f"Si tu veux annuler : `/architecture restore <backup_id={report.backup_id}>`"
            )
            lines.append(
                f"\nSuggestion : `/architecture create_roles` pour ajouter le panneau "
                f"self-service avec les {len(bp.mention_roles)} rôles de mention."
            )
        await i.followup.send("\n".join(lines)[:1900], ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="builder",
    description="Ouvre le BUILDER interactif - customise tout puis applique",
)
@_is_owner_or_admin()
async def architecture_builder_cmd(i: discord.Interaction):
    """Ouvre le panel builder V2 ou tout est customisable visuellement."""
    try:
        view = builder.BuilderMainV2(i.user, i.guild)
        await view.render_to(i, edit=False)
    except Exception as ex:
        import traceback; traceback.print_exc()
        try:
            await i.response.send_message(
                f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True,
            )
        except discord.InteractionResponded:
            await i.followup.send(
                f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True,
            )


@architecture_group.command(
    name="presets",
    description="Liste les presets disponibles avec leur description",
)
@_is_owner_or_admin()
async def architecture_presets(i: discord.Interaction):
    lines = ["**📐 Presets disponibles** :", ""]
    for key, bp in cblueprint.PRESETS.items():
        cats = len(bp.categories)
        chans = sum(len(c.channels) for c in bp.categories)
        roles = len(bp.roles)
        lines.append(f"**`{key}`** — {bp.name}")
        lines.append(f"   _{bp.description}_")
        lines.append(f"   📁 {cats} catégories · 📺 {chans} salons · 🎭 {roles} rôles")
        lines.append("")
    lines.append("`/architecture preview_preset preset:<key>` pour voir le détail")
    lines.append("`/architecture build_preset preset:<key>` pour appliquer")
    await i.response.send_message("\n".join(lines)[:1900], ephemeral=True)


@architecture_group.command(
    name="suggest_roles",
    description="Liste les rôles de mention suggérés pour votre serveur",
)
@_is_owner_or_admin()
async def architecture_suggest_roles(i: discord.Interaction):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        blueprint = architect.analyze_guild(i.guild)
        suggestions = architect.suggest_roles_for_guild(blueprint)
        template = architect.detect_template(blueprint)
        tpl_meta = architect.TEMPLATE_META[template]
        lines = [
            f"**🤖 Type de serveur détecté** : {tpl_meta['name']}",
            f"_{tpl_meta['desc']}_",
            "",
            f"**🔔 Rôles de mention suggérés** ({len(suggestions)}) :",
            "",
        ]
        for s in suggestions:
            emoji = s.emoji + " " if s.emoji else ""
            lines.append(f"{emoji}**{s.label}** — {s.description}")
        lines.append("")
        lines.append("_Pour créer ces rôles + un panneau self-service :_")
        lines.append("`/architecture create_roles`")
        await i.followup.send("\n".join(lines)[:1900], ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="create_roles",
    description="Crée les rôles suggérés + un panneau self-service dans ce salon",
)
@_is_owner_or_admin()
async def architecture_create_roles(i: discord.Interaction):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        blueprint = architect.analyze_guild(i.guild)
        suggestions = architect.suggest_roles_for_guild(blueprint)
        if not suggestions:
            return await i.followup.send(
                "❌ Aucune suggestion (serveur trop petit ou themes non detectes).",
                ephemeral=True,
            )

        created_roles: list[discord.Role] = []
        existing_roles_by_name = {r.name.lower(): r for r in i.guild.roles}
        for s in suggestions:
            role_name = s.label
            existing = existing_roles_by_name.get(role_name.lower())
            if existing:
                created_roles.append(existing)
                continue
            try:
                new_role = await i.guild.create_role(
                    name=role_name,
                    color=discord.Color(s.color),
                    mentionable=True,
                    reason="Architecture Phase 3.2 - role de mention suggere",
                )
                created_roles.append(new_role)
            except discord.Forbidden:
                continue
            except Exception:
                continue

        if not created_roles:
            return await i.followup.send(
                "❌ Aucun role n'a pu etre cree (permissions manquantes ?)",
                ephemeral=True,
            )

        # Cree un roles_panel avec ces roles
        cfg = rpanel.RolesPanelConfig(
            panel_id=rpanel.new_panel_id(),
            guild_id=i.guild.id,
            channel_id=i.channel.id,
            title="🔔 Mes notifications",
            description=(
                "Choisis les sujets qui t'intéressent. Tu seras mentionné "
                "uniquement sur ceux que tu actives."
            ),
        )
        # Map suggestions -> roles crees
        suggestions_by_name = {s.label.lower(): s for s in suggestions}
        for role in created_roles:
            s = suggestions_by_name.get(role.name.lower())
            if not s:
                continue
            cfg.roles.append(rpanel.RolesPanelRole(
                role_id=role.id,
                label=s.label[:80],
                emoji=s.emoji or None,
                description=s.description[:200],
            ))
        await rpanel.upsert_panel(cfg)
        msg_id = await rpanel.post_or_update_panel(i.client, cfg)

        lines = [
            f"✅ **{len(created_roles)} rôles** créés (ou réutilisés s'ils existaient)",
            f"📋 **Panneau self-service** posté dans {i.channel.mention} (ID `{cfg.panel_id}`)",
            "",
            "Les membres peuvent maintenant cliquer pour s'abonner à chaque type de notification.",
            "",
            "**Rôles créés** :",
        ]
        for r in created_roles[:15]:
            lines.append(f"  • {r.mention}")
        await i.followup.send("\n".join(lines)[:1900], ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="restore",
    description="Restaure le serveur depuis un backup (supprime cat vides crees apres)",
)
@_is_owner_or_admin()
@app_commands.describe(
    backup_id="ID du backup (cf /architecture backups)",
    delete_new_categories="Aussi supprimer les categories crees apres le backup et vides (par defaut: oui)",
)
async def architecture_restore(
    i: discord.Interaction, backup_id: str,
    delete_new_categories: bool = True,
):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        report = await architect.restore_state(
            i.guild, backup_id, dry_run=False,
            delete_new_categories=delete_new_categories,
        )
        lines = [f"**🔄 Restore `{backup_id}`** :", ""]
        lines.append(f"📺 Salons restaurés : `{len(report.channels_moved)}`")
        deleted = [c for c in report.categories_created if c.startswith("DELETED")]
        if deleted:
            lines.append(f"🗑️ Catégories vides supprimées : `{len(deleted)}`")
        lines.append(f"⚠️ Erreurs : `{len(report.errors)}`")
        if report.errors:
            lines.append("\n**Erreurs** :")
            for e in report.errors[:10]:
                lines.append(f"  • {e}")
        await i.followup.send("\n".join(lines)[:1900], ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="restore_latest",
    description="URGENT: Restaure le backup le plus recent (annule la derniere refonte)",
)
@_is_owner_or_admin()
async def architecture_restore_latest(i: discord.Interaction):
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        backup_id = await architect.latest_backup_id(i.guild.id)
        if not backup_id:
            return await i.followup.send(
                "❌ Aucun backup disponible pour ce serveur.", ephemeral=True,
            )
        report = await architect.restore_state(
            i.guild, backup_id, dry_run=False, delete_new_categories=True,
        )
        lines = [
            f"**🚑 Recovery rapide** depuis backup `{backup_id}`",
            "",
            f"📺 Salons restaurés : `{len(report.channels_moved)}`",
        ]
        deleted = [c for c in report.categories_created if c.startswith("DELETED")]
        if deleted:
            lines.append(f"🗑️ Catégories vides supprimées : `{len(deleted)}`")
        lines.append(f"⚠️ Erreurs : `{len(report.errors)}`")
        if report.errors:
            lines.append("\n**Erreurs** :")
            for e in report.errors[:10]:
                lines.append(f"  • {e}")
        await i.followup.send("\n".join(lines)[:1900], ephemeral=True)
    except Exception as ex:
        import traceback; traceback.print_exc()
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}: {ex}`", ephemeral=True)


@architecture_group.command(
    name="wipe",
    description="DANGEREUX : supprime TOUS les salons (avec backup auto)",
)
@_is_owner_or_admin()
@app_commands.describe(
    confirmation="Tape exactement : SUPPRIMER TOUT pour confirmer",
    dry_run="True = simule sans rien supprimer",
)
async def architecture_wipe(
    i: discord.Interaction, confirmation: str = "", dry_run: bool = True,
):
    if confirmation != "SUPPRIMER TOUT" and not dry_run:
        return await i.response.send_message(
            "❌ Pour vraiment supprimer, tape exactement `SUPPRIMER TOUT` dans le champ confirmation.\n"
            "Sinon utilise `dry_run:True` pour simuler.",
            ephemeral=True,
        )
    if i.user.id != i.guild.owner_id:
        return await i.response.send_message(
            "❌ Seul le **propriétaire du serveur** peut utiliser /architecture wipe.",
            ephemeral=True,
        )
    await i.response.defer(ephemeral=True, thinking=True)
    try:
        report = await architect.wipe_guild(i.guild, dry_run=dry_run)
        lines = [
            "**🧨 WIPE serveur** :", "",
            f"💾 Backup avant : `{report.backup_id}`" if report.backup_id else "_(dry_run, pas de backup)_",
            f"🗑️ Salons supprimés : `{len(report.channels_moved)}`",
            f"🗑️ Catégories supprimées : `{len(report.categories_created)}`",
            f"⚠️ Erreurs : `{len(report.errors)}`",
        ]
        if dry_run:
            lines.insert(1, "🟦 **DRY-RUN** : rien n'a été supprimé.\n")
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
