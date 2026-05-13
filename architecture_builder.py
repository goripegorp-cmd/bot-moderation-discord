"""
architecture_builder.py - V2 panel interactif pour construire le blueprint
                          serveur (Phase 3.5).

Commande : /architecture builder

Le panel permet a l'owner de :
1. Charger un preset comme base
2. Ajouter / renommer / supprimer / reordonner des categories
3. Ajouter / renommer / supprimer des salons par categorie
4. Ajouter / renommer / supprimer des roles
5. Sauvegarder le blueprint
6. Appliquer (WIPE + REBUILD) avec confirmation

Structure :
    BuilderMainV2          - panel principal (stats + actions)
    BuilderCategoriesV2    - liste + actions sur categories
    BuilderCategoryDetailV2 - edition d'une categorie + ses channels
    BuilderRolesV2         - liste + actions sur roles
    BuilderApplyConfirmV2  - confirmation avant wipe+build

Modals :
    _CreateCategoryModal, _RenameCategoryModal
    _CreateChannelModal, _RenameChannelModal
    _CreateRoleModal, _RenameRoleModal, _RoleColorModal
"""
from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import ui

import custom_blueprint as cblueprint
from ui_v2 import Palette


# =============================================================================
# HELPERS UI V2
# =============================================================================

def _container(*items, color=Palette.PRIMARY):
    return ui.Container(*items, accent_color=color)


def _title(text, level=1):
    return ui.TextDisplay(f"{'#' * max(1, min(level, 3))} {text}")


def _subtitle(text):
    return ui.TextDisplay(f"-# {text}")


def _body(text):
    return ui.TextDisplay(text)


def _divider():
    return ui.Separator()


def _kv(rows):
    return ui.TextDisplay("\n".join(f"**{k}** — {v}" for k, v in rows))


# =============================================================================
# BASE OWNER-ONLY
# =============================================================================

class _OwnerView(ui.LayoutView):
    def __init__(self, owner, guild, *, timeout=600):
        super().__init__(timeout=timeout)
        self.owner = owner
        self.guild = guild

    async def interaction_check(self, i):
        if i.user.id != self.owner.id:
            try:
                await i.response.send_message(
                    "❌ Seul l'owner du panneau peut interagir.", ephemeral=True,
                )
            except Exception:
                pass
            return False
        return True


# =============================================================================
# MAIN PANEL
# =============================================================================

class BuilderMainV2(_OwnerView):
    """Panel principal du builder."""

    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        total_channels = sum(len(c.channels) for c in bp.categories)

        self.clear_items()

        # Boutons d'action
        b_cats = ui.Button(label=f"📁 Catégories ({len(bp.categories)})",
                            style=discord.ButtonStyle.primary)
        b_cats.callback = self._cb_categories
        b_roles = ui.Button(label=f"🎭 Rôles ({len(bp.roles)})",
                             style=discord.ButtonStyle.primary)
        b_roles.callback = self._cb_roles
        b_preset = ui.Button(label="📦 Charger Preset",
                              style=discord.ButtonStyle.secondary)
        b_preset.callback = self._cb_load_preset
        b_save = ui.Button(label="💾 Sauvegarder",
                            style=discord.ButtonStyle.success)
        b_save.callback = self._cb_save
        b_clear = ui.Button(label="🗑️ Vider tout",
                             style=discord.ButtonStyle.danger)
        b_clear.callback = self._cb_clear
        b_apply = ui.Button(label="🚀 Appliquer (WIPE + REBUILD)",
                             style=discord.ButtonStyle.danger)
        b_apply.callback = self._cb_apply

        items = [
            _title(f"🏗️ Builder Serveur — {bp.name}"),
            _subtitle(bp.description or "Construis ton serveur à ta façon."),
            _divider(),
            _kv([
                ("📁 Catégories", str(len(bp.categories))),
                ("📺 Salons total", str(total_channels)),
                ("🎭 Rôles", str(len(bp.roles))),
                ("🔔 Rôles mentions", str(len(bp.mention_roles))),
            ]),
            _divider(),
            _subtitle("💡 Clique sur **Catégories** ou **Rôles** pour éditer. "
                      "**Charger Preset** pour partir d'une base. "
                      "**Appliquer** détruit l'existant et reconstruit selon ton blueprint."),
            _divider(),
            ui.ActionRow(b_cats, b_roles, b_preset),
            ui.ActionRow(b_save, b_clear, b_apply),
        ]
        self.add_item(_container(*items, color=Palette.PRIMARY))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except (discord.InteractionResponded, discord.NotFound):
                try:
                    await i.edit_original_response(view=self, embed=None, attachments=[])
                except Exception:
                    pass
        else:
            await i.response.send_message(view=self, ephemeral=True)

    async def _cb_categories(self, i):
        await BuilderCategoriesV2(self.owner, self.guild).render_to(i)

    async def _cb_roles(self, i):
        await BuilderRolesV2(self.owner, self.guild).render_to(i)

    async def _cb_load_preset(self, i):
        await BuilderLoadPresetV2(self.owner, self.guild).render_to(i)

    async def _cb_save(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        await cblueprint.save_blueprint(self.guild.id, bp)
        try:
            await i.response.send_message("✅ Blueprint sauvegardé.", ephemeral=True)
        except discord.InteractionResponded:
            await i.followup.send("✅ Blueprint sauvegardé.", ephemeral=True)

    async def _cb_clear(self, i):
        await _ConfirmActionV2(
            self.owner, self.guild,
            title="🗑️ Vider tout le blueprint ?",
            description="Tout sera reset (catégories, salons, rôles).",
            on_confirm=self._do_clear,
            return_factory=lambda: BuilderMainV2(self.owner, self.guild),
        ).render_to(i)

    async def _do_clear(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        cblueprint.mutate_clear(bp)
        await cblueprint.save_blueprint(self.guild.id, bp)
        await BuilderMainV2(self.owner, self.guild).render_to(i)

    async def _cb_apply(self, i):
        await BuilderApplyConfirmV2(self.owner, self.guild).render_to(i)


# =============================================================================
# LOAD PRESET
# =============================================================================

class BuilderLoadPresetV2(_OwnerView):
    """Charger un preset comme base."""

    async def render_to(self, i, *, edit=True):
        self.clear_items()

        options = []
        for key, preset in cblueprint.PRESETS.items():
            options.append(discord.SelectOption(
                label=preset.name[:100], value=key,
                description=preset.description[:100],
            ))
        sel = ui.Select(placeholder="📦 Choisir un preset...", options=options)

        async def _on_sel(inter):
            preset_key = sel.values[0]
            bp = await cblueprint.get_or_create_blueprint(self.guild.id)
            cblueprint.mutate_load_preset(bp, preset_key)
            await cblueprint.save_blueprint(self.guild.id, bp)
            try:
                await inter.followup.send(
                    f"✅ Preset **{cblueprint.PRESETS[preset_key].name}** chargé.",
                    ephemeral=True,
                )
            except Exception:
                pass
            await BuilderMainV2(self.owner, self.guild).render_to(inter)
        sel.callback = _on_sel

        b_back = ui.Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderMainV2(self.owner, self.guild).render_to(inter)
        b_back.callback = _back

        items = [
            _title("📦 Charger un preset"),
            _subtitle("Choisis un preset pour partir d'une base solide. "
                      "Tu pourras ensuite tout customiser."),
            _divider(),
            ui.ActionRow(sel),
            ui.ActionRow(b_back),
        ]
        self.add_item(_container(*items, color=Palette.PREMIUM))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


# =============================================================================
# CATEGORIES
# =============================================================================

class BuilderCategoriesV2(_OwnerView):
    """Liste + actions sur categories."""

    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        self.clear_items()

        items = [
            _title(f"📁 Catégories ({len(bp.categories)})"),
            _subtitle("Sélectionne une catégorie pour l'éditer."),
            _divider(),
        ]

        if bp.categories:
            cat_lines = []
            for idx, cat in enumerate(bp.categories[:25], start=1):
                cat_lines.append(f"`{idx:>2}.` **{cat.name}** ({len(cat.channels)} salons)")
            items.append(_body("\n".join(cat_lines)))
            items.append(_divider())

            options = []
            for idx, cat in enumerate(bp.categories[:25]):
                options.append(discord.SelectOption(
                    label=cat.name[:100], value=str(idx),
                    description=f"{len(cat.channels)} salons",
                ))
            sel = ui.Select(placeholder="📁 Éditer une catégorie...", options=options)
            async def _on_sel(inter):
                idx = int(sel.values[0])
                await BuilderCategoryDetailV2(self.owner, self.guild, idx).render_to(inter)
            sel.callback = _on_sel
            items.append(ui.ActionRow(sel))
        else:
            items.append(_body("_Aucune catégorie. Ajoute la première !_"))
            items.append(_divider())

        b_add = ui.Button(label="➕ Nouvelle catégorie",
                          style=discord.ButtonStyle.success)
        async def _add(inter):
            await inter.response.send_modal(_CreateCategoryModal(self.owner, self.guild))
        b_add.callback = _add

        b_back = ui.Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderMainV2(self.owner, self.guild).render_to(inter)
        b_back.callback = _back

        items.append(ui.ActionRow(b_add, b_back))
        self.add_item(_container(*items, color=Palette.INFO))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


class _CreateCategoryModal(ui.Modal, title="➕ Nouvelle catégorie"):
    name = ui.TextInput(label="Nom (avec emoji recommandé)",
                         placeholder="📌 Bienvenue", max_length=100)

    def __init__(self, owner, guild):
        super().__init__()
        self.owner = owner
        self.guild = guild

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if cblueprint.mutate_add_category(bp, str(self.name.value).strip()):
            await cblueprint.save_blueprint(self.guild.id, bp)
            await BuilderCategoriesV2(self.owner, self.guild).render_to(i)
        else:
            await i.response.send_message(
                "❌ Une catégorie avec ce nom existe déjà.", ephemeral=True,
            )


class BuilderCategoryDetailV2(_OwnerView):
    """Édition d'une catégorie."""

    def __init__(self, owner, guild, cat_idx: int):
        super().__init__(owner, guild)
        self.cat_idx = cat_idx

    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.cat_idx >= len(bp.categories):
            await BuilderCategoriesV2(self.owner, self.guild).render_to(i)
            return
        cat = bp.categories[self.cat_idx]
        self.clear_items()

        # Liste des channels
        ch_lines = []
        for ch in cat.channels[:15]:
            icon = "🔊" if ch.ctype == "voice" else "📰" if ch.ctype == "announcement" else "💬"
            ch_lines.append(f"{icon} {ch.name}")
        if len(cat.channels) > 15:
            ch_lines.append(f"_… +{len(cat.channels) - 15}_")
        ch_block = "\n".join(ch_lines) if ch_lines else "_Aucun salon_"

        items = [
            _title(f"📁 {cat.name}"),
            _subtitle(f"Position : {self.cat_idx + 1}/{len(bp.categories)} · "
                      f"{len(cat.channels)} salons"),
            _divider(),
            _title("Salons", level=3),
            _body(ch_block),
            _divider(),
        ]

        # Select pour edit un channel
        if cat.channels:
            options = []
            for idx, ch in enumerate(cat.channels[:25]):
                icon = "🔊" if ch.ctype == "voice" else "📰" if ch.ctype == "announcement" else "💬"
                options.append(discord.SelectOption(
                    label=f"{icon} {ch.name}"[:100], value=str(idx),
                    description=f"Type: {ch.ctype}",
                ))
            sel = ui.Select(placeholder="💬 Éditer un salon...", options=options)
            async def _on_sel(inter):
                ch_idx = int(sel.values[0])
                await BuilderChannelDetailV2(
                    self.owner, self.guild, self.cat_idx, ch_idx
                ).render_to(inter)
            sel.callback = _on_sel
            items.append(ui.ActionRow(sel))

        # Boutons
        b_add_ch = ui.Button(label="➕ Salon",
                              style=discord.ButtonStyle.success)
        async def _add_ch(inter):
            await inter.response.send_modal(
                _CreateChannelModal(self.owner, self.guild, self.cat_idx)
            )
        b_add_ch.callback = _add_ch

        b_rename = ui.Button(label="✏️ Renommer cat.",
                              style=discord.ButtonStyle.primary)
        async def _rename(inter):
            await inter.response.send_modal(
                _RenameCategoryModal(self.owner, self.guild, self.cat_idx)
            )
        b_rename.callback = _rename

        b_up = ui.Button(label="⬆️", style=discord.ButtonStyle.secondary,
                         disabled=(self.cat_idx == 0))
        async def _up(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.cat_idx < len(bp2.categories):
                cblueprint.mutate_move_category(bp2, bp2.categories[self.cat_idx].name, -1)
                await cblueprint.save_blueprint(self.guild.id, bp2)
            self.cat_idx = max(0, self.cat_idx - 1)
            await self.render_to(inter)
        b_up.callback = _up

        b_down = ui.Button(label="⬇️", style=discord.ButtonStyle.secondary,
                            disabled=(self.cat_idx >= len(bp.categories) - 1))
        async def _down(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.cat_idx < len(bp2.categories):
                cblueprint.mutate_move_category(bp2, bp2.categories[self.cat_idx].name, +1)
                await cblueprint.save_blueprint(self.guild.id, bp2)
            self.cat_idx = min(len(bp.categories) - 1, self.cat_idx + 1)
            await self.render_to(inter)
        b_down.callback = _down

        b_delete = ui.Button(label="🗑️ Supprimer cat.",
                              style=discord.ButtonStyle.danger)
        async def _del(inter):
            await _ConfirmActionV2(
                self.owner, self.guild,
                title=f"🗑️ Supprimer '{cat.name}' ?",
                description=f"Cette catégorie + ses {len(cat.channels)} salons "
                            f"seront retirés du blueprint.",
                on_confirm=self._do_delete_cat,
                return_factory=lambda: BuilderCategoriesV2(self.owner, self.guild),
            ).render_to(inter)
        b_delete.callback = _del

        b_back = ui.Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderCategoriesV2(self.owner, self.guild).render_to(inter)
        b_back.callback = _back

        items.append(ui.ActionRow(b_add_ch, b_rename, b_up, b_down, b_delete))
        items.append(ui.ActionRow(b_back))

        self.add_item(_container(*items, color=Palette.INFO))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)

    async def _do_delete_cat(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.cat_idx < len(bp.categories):
            cblueprint.mutate_delete_category(bp, bp.categories[self.cat_idx].name)
            await cblueprint.save_blueprint(self.guild.id, bp)
        await BuilderCategoriesV2(self.owner, self.guild).render_to(i)


class _RenameCategoryModal(ui.Modal, title="✏️ Renommer catégorie"):
    new_name = ui.TextInput(label="Nouveau nom", max_length=100)

    def __init__(self, owner, guild, cat_idx):
        super().__init__()
        self.owner = owner
        self.guild = guild
        self.cat_idx = cat_idx

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.cat_idx < len(bp.categories):
            old = bp.categories[self.cat_idx].name
            cblueprint.mutate_rename_category(bp, old, str(self.new_name.value).strip())
            await cblueprint.save_blueprint(self.guild.id, bp)
        await BuilderCategoryDetailV2(self.owner, self.guild, self.cat_idx).render_to(i)


class _CreateChannelModal(ui.Modal, title="➕ Nouveau salon"):
    name = ui.TextInput(label="Nom du salon (sans #)",
                         placeholder="règles", max_length=100)
    ctype = ui.TextInput(label="Type (text/voice/forum/announcement)",
                          default="text", max_length=20)
    topic = ui.TextInput(label="Topic (optionnel)",
                          style=discord.TextStyle.paragraph,
                          required=False, max_length=500)
    slowmode = ui.TextInput(label="Slowmode en secondes (0 = aucun)",
                              default="0", max_length=5, required=False)

    def __init__(self, owner, guild, cat_idx):
        super().__init__()
        self.owner = owner
        self.guild = guild
        self.cat_idx = cat_idx

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.cat_idx >= len(bp.categories):
            return await i.response.send_message("❌ Catégorie introuvable.", ephemeral=True)
        cat_name = bp.categories[self.cat_idx].name
        try:
            slow = int(str(self.slowmode.value or "0").strip())
        except ValueError:
            slow = 0
        ctype = str(self.ctype.value or "text").strip().lower()
        if ctype not in ("text", "voice", "forum", "announcement"):
            ctype = "text"
        ok = cblueprint.mutate_add_channel(
            bp, cat_name,
            str(self.name.value).strip(),
            ctype=ctype,
            topic=str(self.topic.value or "").strip(),
            slowmode=slow,
        )
        if ok:
            await cblueprint.save_blueprint(self.guild.id, bp)
            await BuilderCategoryDetailV2(self.owner, self.guild, self.cat_idx).render_to(i)
        else:
            await i.response.send_message(
                "❌ Un salon avec ce nom existe déjà dans cette catégorie.",
                ephemeral=True,
            )


# =============================================================================
# CHANNEL DETAIL
# =============================================================================

class BuilderChannelDetailV2(_OwnerView):
    def __init__(self, owner, guild, cat_idx, ch_idx):
        super().__init__(owner, guild)
        self.cat_idx = cat_idx
        self.ch_idx = ch_idx

    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if (self.cat_idx >= len(bp.categories) or
                self.ch_idx >= len(bp.categories[self.cat_idx].channels)):
            return await BuilderCategoryDetailV2(
                self.owner, self.guild, self.cat_idx
            ).render_to(i)
        cat = bp.categories[self.cat_idx]
        ch = cat.channels[self.ch_idx]
        self.clear_items()

        icon = "🔊" if ch.ctype == "voice" else "📰" if ch.ctype == "announcement" else "💬"
        items = [
            _title(f"{icon} {ch.name}"),
            _subtitle(f"Catégorie : {cat.name}"),
            _divider(),
            _kv([
                ("Type", ch.ctype),
                ("Topic", (ch.topic[:60] + "...") if ch.topic and len(ch.topic) > 60 else (ch.topic or "_aucun_")),
                ("Slowmode", f"{ch.slowmode}s" if ch.slowmode else "_aucun_"),
                ("NSFW", "oui" if ch.nsfw else "non"),
            ]),
            _divider(),
        ]

        b_rename = ui.Button(label="✏️ Renommer",
                              style=discord.ButtonStyle.primary)
        async def _rename(inter):
            await inter.response.send_modal(
                _RenameChannelModal(self.owner, self.guild, self.cat_idx, self.ch_idx)
            )
        b_rename.callback = _rename

        b_edit = ui.Button(label="📝 Topic/Slow/NSFW",
                            style=discord.ButtonStyle.primary)
        async def _edit(inter):
            await inter.response.send_modal(
                _EditChannelModal(self.owner, self.guild, self.cat_idx, self.ch_idx)
            )
        b_edit.callback = _edit

        b_delete = ui.Button(label="🗑️ Supprimer",
                              style=discord.ButtonStyle.danger)
        async def _del(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.cat_idx < len(bp2.categories):
                cat_name = bp2.categories[self.cat_idx].name
                cblueprint.mutate_delete_channel(bp2, cat_name, ch.name)
                await cblueprint.save_blueprint(self.guild.id, bp2)
            await BuilderCategoryDetailV2(
                self.owner, self.guild, self.cat_idx
            ).render_to(inter)
        b_delete.callback = _del

        b_back = ui.Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderCategoryDetailV2(
                self.owner, self.guild, self.cat_idx
            ).render_to(inter)
        b_back.callback = _back

        items.append(ui.ActionRow(b_rename, b_edit, b_delete, b_back))
        self.add_item(_container(*items, color=Palette.INFO))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


class _RenameChannelModal(ui.Modal, title="✏️ Renommer salon"):
    new_name = ui.TextInput(label="Nouveau nom", max_length=100)

    def __init__(self, owner, guild, cat_idx, ch_idx):
        super().__init__()
        self.owner = owner
        self.guild = guild
        self.cat_idx = cat_idx
        self.ch_idx = ch_idx

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if (self.cat_idx < len(bp.categories) and
                self.ch_idx < len(bp.categories[self.cat_idx].channels)):
            cat = bp.categories[self.cat_idx]
            old = cat.channels[self.ch_idx].name
            cblueprint.mutate_rename_channel(bp, cat.name, old, str(self.new_name.value).strip())
            await cblueprint.save_blueprint(self.guild.id, bp)
        await BuilderChannelDetailV2(
            self.owner, self.guild, self.cat_idx, self.ch_idx
        ).render_to(i)


class _EditChannelModal(ui.Modal, title="📝 Topic / Slowmode"):
    topic = ui.TextInput(label="Topic",
                          style=discord.TextStyle.paragraph,
                          required=False, max_length=500)
    slowmode = ui.TextInput(label="Slowmode en secondes",
                              required=False, max_length=5)
    nsfw = ui.TextInput(label="NSFW (oui/non)",
                          required=False, max_length=3, default="non")

    def __init__(self, owner, guild, cat_idx, ch_idx):
        super().__init__()
        self.owner = owner
        self.guild = guild
        self.cat_idx = cat_idx
        self.ch_idx = ch_idx

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if (self.cat_idx < len(bp.categories) and
                self.ch_idx < len(bp.categories[self.cat_idx].channels)):
            ch = bp.categories[self.cat_idx].channels[self.ch_idx]
            ch.topic = str(self.topic.value or "").strip()
            try:
                ch.slowmode = max(0, int(str(self.slowmode.value or "0").strip()))
            except ValueError:
                pass
            ch.nsfw = str(self.nsfw.value or "non").strip().lower() in ("oui", "yes", "true", "1")
            await cblueprint.save_blueprint(self.guild.id, bp)
        await BuilderChannelDetailV2(
            self.owner, self.guild, self.cat_idx, self.ch_idx
        ).render_to(i)


# =============================================================================
# ROLES
# =============================================================================

class BuilderRolesV2(_OwnerView):
    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        self.clear_items()

        items = [
            _title(f"🎭 Rôles ({len(bp.roles)})"),
            _subtitle("Définis les rôles qui seront créés."),
            _divider(),
        ]

        if bp.roles:
            role_lines = []
            for idx, r in enumerate(bp.roles[:25], start=1):
                flags = []
                if r.hoist:
                    flags.append("hoist")
                if "administrator" in r.permissions:
                    flags.append("admin")
                elif r.permissions:
                    flags.append(f"{len(r.permissions)} perms")
                flags_str = f" _({', '.join(flags)})_" if flags else ""
                role_lines.append(f"`{idx:>2}.` **{r.name}**{flags_str} #{r.color:06x}")
            items.append(_body("\n".join(role_lines)))
            items.append(_divider())

            options = []
            for idx, r in enumerate(bp.roles[:25]):
                options.append(discord.SelectOption(
                    label=r.name[:100], value=str(idx),
                ))
            sel = ui.Select(placeholder="🎭 Éditer un rôle...", options=options)
            async def _on_sel(inter):
                idx = int(sel.values[0])
                await BuilderRoleDetailV2(self.owner, self.guild, idx).render_to(inter)
            sel.callback = _on_sel
            items.append(ui.ActionRow(sel))
        else:
            items.append(_body("_Aucun rôle. Ajoute-en au moins un staff !_"))
            items.append(_divider())

        b_add = ui.Button(label="➕ Nouveau rôle",
                          style=discord.ButtonStyle.success)
        async def _add(inter):
            await inter.response.send_modal(
                _CreateRoleModal(self.owner, self.guild)
            )
        b_add.callback = _add

        b_back = ui.Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderMainV2(self.owner, self.guild).render_to(inter)
        b_back.callback = _back

        items.append(ui.ActionRow(b_add, b_back))
        self.add_item(_container(*items, color=Palette.ACCENT))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


class _CreateRoleModal(ui.Modal, title="➕ Nouveau rôle"):
    name = ui.TextInput(label="Nom du rôle",
                         placeholder="Staff", max_length=80)
    color = ui.TextInput(label="Couleur hex (ex: FF6B35)",
                          required=False, max_length=8, default="99AAB5")
    hoist = ui.TextInput(label="Afficher séparément (oui/non)",
                          required=False, default="non", max_length=3)
    admin = ui.TextInput(label="Administrateur (oui/non) - PRUDENCE",
                          required=False, default="non", max_length=3)
    mentionable = ui.TextInput(label="Mentionnable (oui/non)",
                                  required=False, default="oui", max_length=3)

    def __init__(self, owner, guild):
        super().__init__()
        self.owner = owner
        self.guild = guild

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        try:
            color = int(str(self.color.value or "99AAB5").strip().lstrip("#"), 16)
        except ValueError:
            color = 0x99AAB5
        hoist = str(self.hoist.value or "non").strip().lower() in ("oui", "yes", "true", "1")
        admin = str(self.admin.value or "non").strip().lower() in ("oui", "yes", "true", "1")
        mentionable = str(self.mentionable.value or "oui").strip().lower() in ("oui", "yes", "true", "1")
        perms = ["administrator"] if admin else []
        ok = cblueprint.mutate_add_role(
            bp, str(self.name.value).strip(),
            color=color, mentionable=mentionable, hoist=hoist, permissions=perms,
        )
        if ok:
            await cblueprint.save_blueprint(self.guild.id, bp)
            await BuilderRolesV2(self.owner, self.guild).render_to(i)
        else:
            await i.response.send_message(
                "❌ Un rôle avec ce nom existe déjà.", ephemeral=True,
            )


class BuilderRoleDetailV2(_OwnerView):
    def __init__(self, owner, guild, role_idx):
        super().__init__(owner, guild)
        self.role_idx = role_idx

    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.role_idx >= len(bp.roles):
            return await BuilderRolesV2(self.owner, self.guild).render_to(i)
        r = bp.roles[self.role_idx]
        self.clear_items()

        items = [
            _title(f"🎭 {r.name}"),
            _subtitle(f"Position : {self.role_idx + 1}/{len(bp.roles)}"),
            _divider(),
            _kv([
                ("Couleur", f"#{r.color:06x}"),
                ("Hoist", "oui" if r.hoist else "non"),
                ("Mentionnable", "oui" if r.mentionable else "non"),
                ("Administrateur", "OUI" if "administrator" in r.permissions else "non"),
                ("Autres perms", str(len([p for p in r.permissions if p != "administrator"]))),
            ]),
            _divider(),
        ]

        b_rename = ui.Button(label="✏️ Renommer",
                              style=discord.ButtonStyle.primary)
        async def _rename(inter):
            await inter.response.send_modal(
                _RenameRoleModal(self.owner, self.guild, self.role_idx)
            )
        b_rename.callback = _rename

        b_color = ui.Button(label="🎨 Couleur",
                             style=discord.ButtonStyle.primary)
        async def _color(inter):
            await inter.response.send_modal(
                _RoleColorModal(self.owner, self.guild, self.role_idx)
            )
        b_color.callback = _color

        b_hoist = ui.Button(label=f"📌 Hoist : {'on' if r.hoist else 'off'}",
                             style=discord.ButtonStyle.secondary)
        async def _hoist(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.role_idx < len(bp2.roles):
                bp2.roles[self.role_idx].hoist = not bp2.roles[self.role_idx].hoist
                await cblueprint.save_blueprint(self.guild.id, bp2)
            await self.render_to(inter)
        b_hoist.callback = _hoist

        b_mention = ui.Button(label=f"@ Mention : {'on' if r.mentionable else 'off'}",
                               style=discord.ButtonStyle.secondary)
        async def _mention(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.role_idx < len(bp2.roles):
                bp2.roles[self.role_idx].mentionable = not bp2.roles[self.role_idx].mentionable
                await cblueprint.save_blueprint(self.guild.id, bp2)
            await self.render_to(inter)
        b_mention.callback = _mention

        b_admin = ui.Button(
            label=f"🔐 Admin : {'OUI' if 'administrator' in r.permissions else 'non'}",
            style=discord.ButtonStyle.danger if "administrator" in r.permissions else discord.ButtonStyle.secondary,
        )
        async def _admin(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.role_idx < len(bp2.roles):
                role = bp2.roles[self.role_idx]
                if "administrator" in role.permissions:
                    role.permissions.remove("administrator")
                else:
                    role.permissions.append("administrator")
                await cblueprint.save_blueprint(self.guild.id, bp2)
            await self.render_to(inter)
        b_admin.callback = _admin

        b_delete = ui.Button(label="🗑️ Supprimer",
                              style=discord.ButtonStyle.danger)
        async def _del(inter):
            bp2 = await cblueprint.get_or_create_blueprint(self.guild.id)
            if self.role_idx < len(bp2.roles):
                cblueprint.mutate_delete_role(bp2, bp2.roles[self.role_idx].name)
                await cblueprint.save_blueprint(self.guild.id, bp2)
            await BuilderRolesV2(self.owner, self.guild).render_to(inter)
        b_delete.callback = _del

        b_back = ui.Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderRolesV2(self.owner, self.guild).render_to(inter)
        b_back.callback = _back

        items.append(ui.ActionRow(b_rename, b_color, b_hoist, b_mention, b_admin))
        items.append(ui.ActionRow(b_delete, b_back))
        self.add_item(_container(*items, color=Palette.ACCENT))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


class _RenameRoleModal(ui.Modal, title="✏️ Renommer rôle"):
    new_name = ui.TextInput(label="Nouveau nom", max_length=80)

    def __init__(self, owner, guild, role_idx):
        super().__init__()
        self.owner = owner
        self.guild = guild
        self.role_idx = role_idx

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.role_idx < len(bp.roles):
            old = bp.roles[self.role_idx].name
            cblueprint.mutate_rename_role(bp, old, str(self.new_name.value).strip())
            await cblueprint.save_blueprint(self.guild.id, bp)
        await BuilderRoleDetailV2(self.owner, self.guild, self.role_idx).render_to(i)


class _RoleColorModal(ui.Modal, title="🎨 Couleur rôle"):
    color_hex = ui.TextInput(label="Couleur hex (ex: FF6B35)",
                                max_length=8, default="99AAB5")

    def __init__(self, owner, guild, role_idx):
        super().__init__()
        self.owner = owner
        self.guild = guild
        self.role_idx = role_idx

    async def on_submit(self, i):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        if self.role_idx < len(bp.roles):
            try:
                color = int(str(self.color_hex.value).strip().lstrip("#"), 16)
                bp.roles[self.role_idx].color = color
                await cblueprint.save_blueprint(self.guild.id, bp)
            except ValueError:
                await i.response.send_message("❌ Couleur invalide.", ephemeral=True)
                return
        await BuilderRoleDetailV2(self.owner, self.guild, self.role_idx).render_to(i)


# =============================================================================
# APPLY / CONFIRM
# =============================================================================

class BuilderApplyConfirmV2(_OwnerView):
    """Confirmation finale avant wipe + build."""

    async def render_to(self, i, *, edit=True):
        bp = await cblueprint.get_or_create_blueprint(self.guild.id)
        total_channels = sum(len(c.channels) for c in bp.categories)
        self.clear_items()

        items = [
            _title("🚀 Appliquer le blueprint"),
            _subtitle("⚠️ Cette action **DÉTRUIT** tous les salons et catégories actuels."),
            _divider(),
            _body(
                f"📁 **{len(bp.categories)}** catégories vont être créées\n"
                f"📺 **{total_channels}** salons vont être créés\n"
                f"🎭 **{len(bp.roles)}** rôles vont être créés\n"
            ),
            _divider(),
            _body(
                "✅ Un **backup automatique** est créé avant. "
                "Si tu n'es pas satisfait, tu pourras restaurer via "
                "`/architecture restore <backup_id>`."
            ),
            _divider(),
        ]

        b_dry = ui.Button(label="🟦 Dry-run (simulation)",
                          style=discord.ButtonStyle.secondary)
        async def _dry(inter):
            await inter.response.defer(ephemeral=True, thinking=True)
            try:
                report = await cblueprint.apply_blueprint(
                    self.guild, bp, wipe_first=True, dry_run=True,
                )
                lines = ["**🟦 DRY-RUN (rien n'a été modifié)** :", ""]
                lines.append(f"📁 Catégories simulées : `{len(report.categories_created)}`")
                lines.append(f"📺 Salons simulés : `{len(report.channels_created)}`")
                lines.append(f"🎭 Rôles simulés : `{len(report.roles_created)}`")
                lines.append(f"⚠️ Erreurs simulées : `{len(report.errors)}`")
                if report.errors:
                    lines.append("\n**Erreurs** :")
                    for e in report.errors[:10]:
                        lines.append(f"  • {e}")
                await inter.followup.send("\n".join(lines)[:1900], ephemeral=True)
            except Exception as ex:
                await inter.followup.send(f"❌ Erreur : {ex}", ephemeral=True)
        b_dry.callback = _dry

        b_apply = ui.Button(label="🚀 APPLIQUER (WIPE + BUILD)",
                             style=discord.ButtonStyle.danger)
        async def _apply(inter):
            # Owner du serveur uniquement
            if inter.user.id != self.guild.owner_id:
                return await inter.response.send_message(
                    "❌ Seul le **propriétaire du serveur** peut faire un WIPE + BUILD.",
                    ephemeral=True,
                )
            await inter.response.defer(ephemeral=True, thinking=True)
            try:
                report = await cblueprint.apply_blueprint(
                    self.guild, bp, wipe_first=True, dry_run=False,
                )
                lines = ["**✅ BUILD terminé** :", ""]
                if report.backup_id:
                    lines.append(f"💾 Backup : `{report.backup_id}` (pour rollback)")
                lines.append(f"📁 Catégories créées : `{len(report.categories_created)}`")
                lines.append(f"📺 Salons créés : `{len(report.channels_created)}`")
                lines.append(f"🎭 Rôles créés : `{len(report.roles_created)}`")
                lines.append(f"⚠️ Erreurs : `{len(report.errors)}`")
                if report.errors:
                    lines.append("\n**Erreurs** :")
                    for e in report.errors[:10]:
                        lines.append(f"  • {e}")
                await inter.followup.send("\n".join(lines)[:1900], ephemeral=True)
            except Exception as ex:
                import traceback; traceback.print_exc()
                await inter.followup.send(f"❌ Erreur : {ex}", ephemeral=True)
        b_apply.callback = _apply

        b_back = ui.Button(label="◀️ Annuler", style=discord.ButtonStyle.secondary)
        async def _back(inter):
            await BuilderMainV2(self.owner, self.guild).render_to(inter)
        b_back.callback = _back

        items.append(ui.ActionRow(b_dry, b_apply, b_back))
        self.add_item(_container(*items, color=Palette.DANGER))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


# =============================================================================
# CONFIRM GENERIQUE
# =============================================================================

class _ConfirmActionV2(_OwnerView):
    def __init__(self, owner, guild, *, title, description, on_confirm, return_factory):
        super().__init__(owner, guild)
        self._title = title
        self._desc = description
        self._on_confirm = on_confirm
        self._return_factory = return_factory

    async def render_to(self, i, *, edit=True):
        self.clear_items()
        b_yes = ui.Button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
        async def _yes(inter):
            await self._on_confirm(inter)
        b_yes.callback = _yes

        b_no = ui.Button(label="✖️ Annuler", style=discord.ButtonStyle.secondary)
        async def _no(inter):
            v = self._return_factory()
            await v.render_to(inter)
        b_no.callback = _no

        items = [
            _title(self._title),
            _divider(),
            _body(self._desc),
            _divider(),
            ui.ActionRow(b_yes, b_no),
        ]
        self.add_item(_container(*items, color=Palette.WARNING))

        if edit:
            try:
                await i.response.edit_message(view=self, embed=None, attachments=[])
            except discord.InteractionResponded:
                await i.edit_original_response(view=self, embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


__all__ = [
    "BuilderMainV2",
    "BuilderCategoriesV2",
    "BuilderCategoryDetailV2",
    "BuilderChannelDetailV2",
    "BuilderRolesV2",
    "BuilderRoleDetailV2",
    "BuilderLoadPresetV2",
    "BuilderApplyConfirmV2",
]
