"""Ajoute AutoHelpPanelV2 + dispatch dans MainPanelV2."""
from pathlib import Path

p = Path("bot.py")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)


def find_line(predicate, start=0, end=None):
    end = end if end is not None else len(lines)
    for idx in range(start, end):
        if predicate(lines[idx]):
            return idx
    return None


# Insérer juste avant la classe AutoHelpChannelSelect
ahp_idx = find_line(lambda l: l.startswith("class AutoHelpPanel(View):"))
end_idx = find_line(lambda l: l.startswith("class AutoHelpChannelSelect("), start=ahp_idx)
if ahp_idx is None or end_idx is None:
    print(f"ERREUR: bornes AutoHelpPanel introuvables ({ahp_idx}, {end_idx})")
    raise SystemExit(1)

insert_at = end_idx
print(f"Insertion AutoHelpPanelV2 à la ligne {insert_at+1}")

NEW_CLASS = '''class AutoHelpPanelV2(LayoutView):
    """Panneau Aide Automatique en V2."""

    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        c = await cfg(self.g.id)
        auto_helps = c.get('auto_help_channels', {})
        count = len(auto_helps)

        # Liste des salons configurés
        list_lines = []
        if auto_helps:
            for ch_id, help_data in list(auto_helps.items())[:10]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    title = help_data.get('title', 'Aide')[:30]
                    list_lines.append(f"• {ch.mention} · **{title}**")
        list_block = "\\n".join(list_lines) if list_lines else "_Aucun salon configuré pour l\\'instant_"

        # Boutons
        self.clear_items()
        b_add = Button(label="➕ Ajouter un salon", style=discord.ButtonStyle.success, custom_id="ahpv2_add")
        b_add.callback = self._cb_add
        b_manage = Button(label="📋 Gérer les aides", style=discord.ButtonStyle.primary, custom_id="ahpv2_manage", disabled=(count == 0))
        b_manage.callback = self._cb_manage
        b_back = Button(label="◀️ Retour", style=discord.ButtonStyle.secondary, custom_id="ahpv2_back")
        b_back.callback = self._cb_back

        items: list = []
        if self.g.icon:
            items.append(v2_section(
                v2_title("💡 Aide Automatique"),
                v2_subtitle(f"{count} salon(s) configuré(s)"),
                accessory=v2_thumb(self.g.icon.url),
            ))
        else:
            items.append(v2_title("💡 Aide Automatique"))
            items.append(v2_subtitle(f"{count} salon(s) configuré(s)"))

        items.append(v2_divider())
        items.append(v2_body(
            "Le message d\\'aide reste toujours en bas du salon.\\n"
            "_Se repositionne automatiquement après chaque message._"
        ))
        items.append(v2_divider())
        items.append(v2_title("📋 Salons configurés", level=3))
        items.append(v2_body(list_block))
        items.append(v2_divider())
        items.append(discord.ui.ActionRow(b_add, b_manage, b_back))

        self.add_item(v2_container(*items, color=Palette.INFO))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    async def _cb_add(self, i):
        v = AutoHelpChannelSelect(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Choisir le salon",
                description="Sélectionne le salon où afficher l\\'aide automatique",
                color=0x3498DB,
            ),
            view=v,
            attachments=[],
        )

    async def _cb_manage(self, i):
        c = await cfg(self.g.id)
        auto_helps = c.get('auto_help_channels', {})
        if not auto_helps:
            return await i.response.send_message("❌ Aucun salon configuré", ephemeral=True)
        v = await AutoHelpManageView.create(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v, attachments=[])

    async def _cb_back(self, i):
        v = MainPanelV2(self.u, self.g)
        await i.response.edit_message(view=v, embed=None, attachments=[])


'''

sample = lines[insert_at]
if sample.endswith("\r\n"):
    NEW_CLASS = NEW_CLASS.replace("\n", "\r\n")

new_lines = lines[:insert_at] + [NEW_CLASS] + lines[insert_at:]
p.write_text("".join(new_lines), encoding="utf-8", newline="")
print("AutoHelpPanelV2 inséré.")

# ─── Update MainPanelV2 dispatch ───
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

# Trouver la dernière ligne dans v2_panels
v2_dispatch_idx = find_line(lambda l: l.rstrip() == "        v2_panels = {")
last_v2_entry = find_line(
    lambda l: "lambda: " in l and "PanelV2" in l,
    start=v2_dispatch_idx,
)
# Trouver la dernière entrée V2 (pas la première)
while True:
    next_v2 = find_line(
        lambda l: "lambda: " in l and "PanelV2" in l,
        start=last_v2_entry + 1,
    )
    if next_v2 is None or lines[next_v2].rstrip() == "        }":
        break
    # Vérifier qu'on est encore dans v2_panels
    if "v1_panels" in lines[next_v2]:
        break
    last_v2_entry = next_v2

sample = lines[last_v2_entry]
nl = "\r\n" if sample.endswith("\r\n") else "\n"
new_line = f"            'help': lambda: AutoHelpPanelV2(self.u, self.g),{nl}"

# Retirer 'help' de v1_panels
help_v1 = find_line(lambda l: "'help': lambda: AutoHelpPanel" in l, start=last_v2_entry)
if help_v1 is None:
    print("ERREUR: ligne help V1 introuvable")
    raise SystemExit(1)

new_lines = (
    lines[:last_v2_entry + 1]
    + [new_line]
    + lines[last_v2_entry + 1:help_v1]
    + lines[help_v1 + 1:]
)
p.write_text("".join(new_lines), encoding="utf-8", newline="")
print("MainPanelV2 dispatch mis à jour.")
