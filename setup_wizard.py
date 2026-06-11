"""
setup_wizard.py - Wizard d'installation guide pour nouveaux serveurs (Phase 1.8).

Quand l'owner ajoute le bot pour la premiere fois, /setup ouvre ce wizard
qui le guide a travers les etapes essentielles :

    Step 1 : Bienvenue + choix template (Gaming / Communaute / Esport / Roleplay / Custom)
    Step 2 : Mapping des salons (regles / accueil / aide / annonces)
    Step 3 : Roles staff (qui peut moderer / configurer)
    Step 4 : Niveau de protection (Souple / Equilibre / Strict)
    Step 5 : Features communautaires a activer
    Step 6 : Recap

Chaque etape :
    - Resume ce qui a ete decide jusqu'ici
    - Permet de revenir en arriere
    - Sauvegarde l'etat dans data/setup/{guild_id}.json (reprise possible)

Quand le wizard se termine, il :
    - Applique toutes les configs (permissions, protection, community)
    - Cree une sauvegarde initiale
    - Envoie un message de confirmation a l'owner
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

import discord
from discord import ui

from paths import module_dir
from ui_v2 import Palette
from vocabulary import Action as A, Status as S, Message as Msg

import permissions as perms_mod
import protection_guards as guards_mod
import community_features as comm_mod


DATA_DIR = module_dir("setup")


# =============================================================================
# TEMPLATES PRE-DEFINIS
# =============================================================================

class Template(str, Enum):
    GAMING = "gaming"
    COMMUNITY = "community"
    ESPORT = "esport"
    ROLEPLAY = "roleplay"
    CUSTOM = "custom"


TEMPLATE_LABELS: dict[Template, str] = {
    Template.GAMING:    "🎮 Gaming",
    Template.COMMUNITY: "💬 Communauté générale",
    Template.ESPORT:    "🏆 Esport / Compétitif",
    Template.ROLEPLAY:  "🎭 Roleplay",
    Template.CUSTOM:    "⚙️ Personnalisé",
}


TEMPLATE_DESCRIPTIONS: dict[Template, str] = {
    Template.GAMING: (
        "Optimisé pour les serveurs de jeux : LFG, tournois, guides, événements.\n"
        "Active : daily question, member spotlight, theme days (Music Monday, etc.)"
    ),
    Template.COMMUNITY: (
        "Polyvalent pour communautés généralistes : discussions, partage, entraide.\n"
        "Active : welcome quickstart, daily question, weekly digest."
    ),
    Template.ESPORT: (
        "Pour les structures compétitives : staff, joueurs, sponsors.\n"
        "Active : permissions strictes, audit log, weekly digest pro."
    ),
    Template.ROLEPLAY: (
        "Pour serveurs RP : factions, événements narratifs, salons thématiques.\n"
        "Active : theme days, member spotlight (pour roleplayers actifs)."
    ),
    Template.CUSTOM: (
        "Aucun preset : tu configures tout toi-même."
    ),
}


# =============================================================================
# NIVEAUX DE PROTECTION
# =============================================================================

class ProtectionLevel(str, Enum):
    SOFT = "soft"
    BALANCED = "balanced"
    STRICT = "strict"


PROTECTION_LEVEL_LABELS: dict[ProtectionLevel, str] = {
    ProtectionLevel.SOFT:     "🌱 Souple — log uniquement, idéal pour démarrer",
    ProtectionLevel.BALANCED: "⚖️ Équilibré — recommandé (warn / mute auto, ban très prudent)",
    ProtectionLevel.STRICT:   "🛡️ Strict — actions auto plus rapides, à utiliser si raids fréquents",
}


# =============================================================================
# ETAT DU WIZARD (persistant)
# =============================================================================

@dataclass
class WizardState:
    """Etat sauvegarde du wizard pour reprise."""

    guild_id: int
    step: int = 1
    template: Optional[str] = None
    rules_channel_id: Optional[int] = None
    welcome_channel_id: Optional[int] = None
    help_channel_id: Optional[int] = None
    announcements_channel_id: Optional[int] = None
    staff_role_ids: list[int] = field(default_factory=list)
    protection_level: Optional[str] = None
    enabled_features: list[str] = field(default_factory=list)
    completed: bool = False


def _state_path(guild_id: int):
    return DATA_DIR / f"{guild_id}.json"


def load_state(guild_id: int) -> WizardState:
    path = _state_path(guild_id)
    if path.exists():
        try:
            return WizardState(**json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            pass
    return WizardState(guild_id=guild_id)


def save_state(state: WizardState) -> None:
    _state_path(state.guild_id).write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def clear_state(guild_id: int) -> None:
    p = _state_path(guild_id)
    if p.exists():
        p.unlink()


# =============================================================================
# APPLICATION DE LA CONFIG (final step)
# =============================================================================

async def apply_wizard_config(state: WizardState, guild: discord.Guild) -> dict:
    """Applique la configuration choisie dans le wizard.

    Retourne un dict de rapport (modules configures, erreurs, etc.).
    """
    report = {"applied": [], "errors": []}

    # 1. Permissions : staff_role_ids -> trusted + can_use moderation
    try:
        config = await perms_mod.load_permissions(guild.id)
        if state.staff_role_ids:
            mod_rule = config.categories.setdefault(
                "moderation", perms_mod.PermissionRule()
            )
            for rid in state.staff_role_ids:
                if rid not in mod_rule.allow_roles:
                    mod_rule.allow_roles.append(rid)
            mod_rule.default = "deny"  # tout le monde refuse sauf allow_roles
        await perms_mod.save_permissions(guild.id, config)
        report["applied"].append("permissions")
    except Exception as ex:
        report["errors"].append(f"permissions: {ex}")

    # 2. Protection : niveau
    try:
        policy = await guards_mod.load_policy(guild.id)
        if state.protection_level == ProtectionLevel.SOFT.value:
            policy.soft_mode = True
            policy.review_mode = False
        elif state.protection_level == ProtectionLevel.BALANCED.value:
            policy.soft_mode = False
            policy.review_mode = False
            policy.trust_boost_enabled = True
        elif state.protection_level == ProtectionLevel.STRICT.value:
            policy.soft_mode = False
            policy.review_mode = False
            policy.trust_boost_enabled = True
            # En strict, on baisse les seuils ban
            for evt in policy.confidence_thresholds.values():
                if "ban" in evt:
                    evt["ban"] = max(0.85, evt["ban"] - 0.05)
        await guards_mod.save_policy(guild.id, policy)
        report["applied"].append("protection")
    except Exception as ex:
        report["errors"].append(f"protection: {ex}")

    # 3. Community features
    try:
        cfg = await comm_mod.load_config(guild.id)
        if state.welcome_channel_id:
            cfg.welcome_quickstart_channel_id = state.welcome_channel_id
            cfg.welcome_quickstart_enabled = True
        if state.rules_channel_id:
            cfg.welcome_quickstart_rules_channel_id = state.rules_channel_id
        if state.help_channel_id:
            cfg.welcome_quickstart_help_channel_id = state.help_channel_id

        feature_to_attr = {
            "daily": "daily_conversation_enabled",
            "spotlight": "member_spotlight_enabled",
            "welcome": "welcome_quickstart_enabled",
            "activity": "activity_recognition_enabled",
            "nudge": "inactivity_nudge_enabled",
            "themes": "theme_days_enabled",
            "digest": "weekly_digest_enabled",
        }
        for f in state.enabled_features:
            attr = feature_to_attr.get(f)
            if attr:
                setattr(cfg, attr, True)

        # Salons par defaut pour features qui ont besoin d'un salon
        if state.announcements_channel_id:
            if cfg.daily_conversation_enabled and not cfg.daily_conversation_channel_id:
                cfg.daily_conversation_channel_id = state.announcements_channel_id
            if cfg.member_spotlight_enabled and not cfg.member_spotlight_channel_id:
                cfg.member_spotlight_channel_id = state.announcements_channel_id
            if cfg.weekly_digest_enabled and not cfg.weekly_digest_channel_id:
                cfg.weekly_digest_channel_id = state.announcements_channel_id

        await comm_mod.save_config(guild.id, cfg)
        report["applied"].append("community")
    except Exception as ex:
        report["errors"].append(f"community: {ex}")

    state.completed = True
    save_state(state)
    return report


# =============================================================================
# UI HELPERS
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


def _progress_bar(current: int, total: int) -> str:
    filled = "█" * current
    empty = "░" * (total - current)
    return f"`[{filled}{empty}]` Étape {current}/{total}"


# =============================================================================
# PANNEAUX DU WIZARD
# =============================================================================

class _WizardView(ui.LayoutView):
    """Base : owner-only, charge l'état."""

    TOTAL_STEPS = 6

    def __init__(self, owner, guild):
        super().__init__(timeout=900)
        self.owner = owner
        self.guild = guild
        self.state = load_state(guild.id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner.id:
            await interaction.response.send_message(Msg.OWNER_ONLY_PANEL, ephemeral=True)
            return False
        return True


class WizardStep1(_WizardView):
    """Etape 1 : Bienvenue + choix template."""

    async def render_to(self, interaction, edit=True):
        self.state.step = 1
        save_state(self.state)
        self.clear_items()

        options = []
        for t in Template:
            options.append(discord.SelectOption(
                label=TEMPLATE_LABELS[t][:100],
                value=t.value,
                description=TEMPLATE_DESCRIPTIONS[t][:100],
                default=(self.state.template == t.value),
            ))
        sel = ui.Select(placeholder="Choisis un template (sera personnalisable)", options=options)
        async def _on_sel(i):
            self.state.template = sel.values[0]
            save_state(self.state)
            await WizardStep2(self.owner, self.guild).render_to(i)
        sel.callback = _on_sel

        b_skip = ui.Button(label="⏭️ Sauter (custom)", style=discord.ButtonStyle.secondary, custom_id="wiz1_skip")
        async def _skip(i):
            self.state.template = Template.CUSTOM.value
            save_state(self.state)
            await WizardStep2(self.owner, self.guild).render_to(i)
        b_skip.callback = _skip

        b_cancel = ui.Button(label=A.CANCEL_ICON, style=discord.ButtonStyle.danger, custom_id="wiz1_cancel")
        async def _cancel(i):
            clear_state(self.guild.id)
            await i.response.send_message(Msg.CANCELLED, ephemeral=True)
        b_cancel.callback = _cancel

        items = [
            _title(f"🎉 Bienvenue dans la config — {self.guild.name}"),
            _subtitle(_progress_bar(1, self.TOTAL_STEPS)),
            _divider(),
            _body(
                "Ce wizard te guide en **6 étapes** pour configurer le bot — chaque étape se sauvegarde automatiquement.\n"
                "Choisis un template : il applique des réglages par défaut sensés, modifiables ensuite via `/admin`."
            ),
            _divider(),
            ui.ActionRow(sel),
            ui.ActionRow(b_skip, b_cancel),
        ]
        self.add_item(_container(*items, color=Palette.PREMIUM))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class WizardStep2(_WizardView):
    """Etape 2 : Mapping des salons (rules, welcome, help, announcements)."""

    async def render_to(self, interaction, edit=True):
        self.state.step = 2
        save_state(self.state)
        self.clear_items()

        c_types = [discord.ChannelType.text, discord.ChannelType.news]

        sel_rules = ui.ChannelSelect(channel_types=c_types, placeholder="Salon des règles", min_values=0, max_values=1)
        async def _rules(i):
            self.state.rules_channel_id = sel_rules.values[0].id if sel_rules.values else None
            save_state(self.state)
            await self.render_to(i)
        sel_rules.callback = _rules

        sel_welcome = ui.ChannelSelect(channel_types=c_types, placeholder="Salon d'accueil", min_values=0, max_values=1)
        async def _welcome(i):
            self.state.welcome_channel_id = sel_welcome.values[0].id if sel_welcome.values else None
            save_state(self.state)
            await self.render_to(i)
        sel_welcome.callback = _welcome

        sel_help = ui.ChannelSelect(channel_types=c_types, placeholder="Salon d'aide", min_values=0, max_values=1)
        async def _help(i):
            self.state.help_channel_id = sel_help.values[0].id if sel_help.values else None
            save_state(self.state)
            await self.render_to(i)
        sel_help.callback = _help

        sel_ann = ui.ChannelSelect(channel_types=c_types, placeholder="Salon d'annonces", min_values=0, max_values=1)
        async def _ann(i):
            self.state.announcements_channel_id = sel_ann.values[0].id if sel_ann.values else None
            save_state(self.state)
            await self.render_to(i)
        sel_ann.callback = _ann

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="wiz2_back")
        async def _back(i):
            await WizardStep1(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        b_next = ui.Button(label=A.NEXT_ICON, style=discord.ButtonStyle.success, custom_id="wiz2_next")
        async def _next(i):
            await WizardStep3(self.owner, self.guild).render_to(i)
        b_next.callback = _next

        # Recap
        rules = self.guild.get_channel(self.state.rules_channel_id) if self.state.rules_channel_id else None
        welcome = self.guild.get_channel(self.state.welcome_channel_id) if self.state.welcome_channel_id else None
        help_c = self.guild.get_channel(self.state.help_channel_id) if self.state.help_channel_id else None
        ann = self.guild.get_channel(self.state.announcements_channel_id) if self.state.announcements_channel_id else None

        items = [
            _title("📍 Mapping des salons"),
            _subtitle(_progress_bar(2, self.TOTAL_STEPS)),
            _divider(),
            _body("Sélectionne tes salons pour chaque rôle. **Tu peux laisser vide** si non applicable."),
            _divider(),
            _kv([
                ("Règles", rules.mention if rules else "—"),
                ("Accueil", welcome.mention if welcome else "—"),
                ("Aide", help_c.mention if help_c else "—"),
                ("Annonces", ann.mention if ann else "—"),
            ]),
            _divider(),
            ui.ActionRow(sel_rules),
            ui.ActionRow(sel_welcome),
            ui.ActionRow(sel_help),
            ui.ActionRow(sel_ann),
            ui.ActionRow(b_back, b_next),
        ]
        self.add_item(_container(*items, color=Palette.PREMIUM))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class WizardStep3(_WizardView):
    """Etape 3 : Roles staff."""

    async def render_to(self, interaction, edit=True):
        self.state.step = 3
        save_state(self.state)
        self.clear_items()

        sel = ui.RoleSelect(placeholder="Rôles staff (peuvent modérer)", min_values=0, max_values=10)
        async def _sel(i):
            self.state.staff_role_ids = [r.id for r in sel.values]
            save_state(self.state)
            await self.render_to(i)
        sel.callback = _sel

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="wiz3_back")
        async def _back(i):
            await WizardStep2(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        b_next = ui.Button(label=A.NEXT_ICON, style=discord.ButtonStyle.success, custom_id="wiz3_next")
        async def _next(i):
            await WizardStep4(self.owner, self.guild).render_to(i)
        b_next.callback = _next

        roles = [self.guild.get_role(rid) for rid in self.state.staff_role_ids]
        roles_str = ", ".join(r.mention for r in roles if r) or "_aucun_"

        items = [
            _title("👥 Rôles staff"),
            _subtitle(_progress_bar(3, self.TOTAL_STEPS)),
            _divider(),
            _body(
                "Choisis les rôles qui auront accès aux commandes de modération.\n"
                "Tu peux en sélectionner plusieurs (ex: Admin + Modérateur + Helper)."
            ),
            _divider(),
            _kv([("Rôles staff sélectionnés", roles_str)]),
            _divider(),
            ui.ActionRow(sel),
            ui.ActionRow(b_back, b_next),
        ]
        self.add_item(_container(*items, color=Palette.PREMIUM))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class WizardStep4(_WizardView):
    """Etape 4 : Niveau de protection."""

    async def render_to(self, interaction, edit=True):
        self.state.step = 4
        save_state(self.state)
        self.clear_items()

        options = []
        for lvl in ProtectionLevel:
            options.append(discord.SelectOption(
                label=PROTECTION_LEVEL_LABELS[lvl][:100],
                value=lvl.value,
                default=(self.state.protection_level == lvl.value),
            ))
        sel = ui.Select(placeholder="Niveau de protection", options=options)
        async def _sel(i):
            self.state.protection_level = sel.values[0]
            save_state(self.state)
            await self.render_to(i)
        sel.callback = _sel

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="wiz4_back")
        async def _back(i):
            await WizardStep3(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        b_next = ui.Button(label=A.NEXT_ICON, style=discord.ButtonStyle.success, custom_id="wiz4_next")
        async def _next(i):
            await WizardStep5(self.owner, self.guild).render_to(i)
        b_next.callback = _next

        current_lbl = PROTECTION_LEVEL_LABELS.get(
            ProtectionLevel(self.state.protection_level)
        ) if self.state.protection_level else "_non choisi_"

        items = [
            _title("🛡️ Niveau de protection"),
            _subtitle(_progress_bar(4, self.TOTAL_STEPS)),
            _divider(),
            _body(
                "**🌱 Souple** — recommandé au démarrage. Aucune sanction auto, tout passe en log.\n"
                "**⚖️ Équilibré** — recommandé pour la plupart. Warn/mute auto, ban très prudent.\n"
                "**🛡️ Strict** — pour les serveurs visés par des raids. Actions auto plus rapides.\n"
                "-# Seuils affinables ensuite via `/admin → Protection`."
            ),
            _divider(),
            _kv([("Niveau choisi", current_lbl)]),
            _divider(),
            ui.ActionRow(sel),
            ui.ActionRow(b_back, b_next),
        ]
        self.add_item(_container(*items, color=Palette.WARNING))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


class WizardStep5(_WizardView):
    """Etape 5 : Features communautaires."""

    FEATURES = [
        ("daily",    "📅 Daily question",     "Une question/jour pour faire parler les gens"),
        ("spotlight","⭐ Member spotlight",   "Mise en avant hebdo d'un membre actif"),
        ("welcome",  "👋 Welcome quickstart","Accueil personnalisé pour les nouveaux"),
        ("activity", "🔥 Réactions activité","Le bot ajoute 🔥 sur les threads dynamiques"),
        ("nudge",    "💭 Inactivity nudge",  "Relance subtile sur un salon silencieux"),
        ("themes",   "🎯 Theme days",        "Jour à thème (Music Monday, etc.)"),
        ("digest",   "📊 Weekly digest",     "Bilan hebdo des stats serveur"),
    ]

    async def render_to(self, interaction, edit=True):
        self.state.step = 5
        save_state(self.state)
        # Apply template defaults if first time on this step
        if not self.state.enabled_features and self.state.template:
            self.state.enabled_features = self._template_defaults(self.state.template)
            save_state(self.state)

        self.clear_items()

        # Buttons : un par feature, toggle on/off
        rows = []
        current_row: list = []
        for key, label, desc in self.FEATURES:
            on = key in self.state.enabled_features
            btn = ui.Button(
                label=f"{'✅' if on else '⬜'} {label}",
                style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary,
                custom_id=f"wiz5_{key}",
            )
            async def _toggle(i, k=key):
                if k in self.state.enabled_features:
                    self.state.enabled_features.remove(k)
                else:
                    self.state.enabled_features.append(k)
                save_state(self.state)
                await self.render_to(i)
            btn.callback = _toggle
            current_row.append(btn)
            if len(current_row) == 3:
                rows.append(ui.ActionRow(*current_row))
                current_row = []
        if current_row:
            rows.append(ui.ActionRow(*current_row))

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="wiz5_back")
        async def _back(i):
            await WizardStep4(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        b_next = ui.Button(label="✔️ Terminer", style=discord.ButtonStyle.primary, custom_id="wiz5_next")
        async def _next(i):
            await WizardStep6(self.owner, self.guild).render_to(i)
        b_next.callback = _next

        feature_kv = [(label, "✅ Activée" if key in self.state.enabled_features else "❌ Désactivée")
                      for key, label, _ in self.FEATURES]

        items = [
            _title("💬 Features communautaires"),
            _subtitle(_progress_bar(5, self.TOTAL_STEPS)),
            _divider(),
            _body(
                "Active les features qui font vivre ton serveur.\n"
                "Toutes respectent un budget d'attention : **impossible de spammer les membres**."
            ),
            _divider(),
            _kv(feature_kv),
            _divider(),
            *rows,
            ui.ActionRow(b_back, b_next),
        ]
        self.add_item(_container(*items, color=Palette.ACCENT))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    @staticmethod
    def _template_defaults(template: str) -> list[str]:
        defaults = {
            Template.GAMING.value:    ["welcome", "daily", "spotlight", "activity", "themes"],
            Template.COMMUNITY.value: ["welcome", "daily", "activity", "digest"],
            Template.ESPORT.value:    ["welcome", "spotlight", "digest"],
            Template.ROLEPLAY.value:  ["welcome", "spotlight", "themes"],
            Template.CUSTOM.value:    ["welcome"],
        }
        return defaults.get(template, ["welcome"])


class WizardStep6(_WizardView):
    """Etape 6 : Recap + apply."""

    async def render_to(self, interaction, edit=True):
        self.state.step = 6
        save_state(self.state)
        self.clear_items()

        # Recap
        rules = self.guild.get_channel(self.state.rules_channel_id) if self.state.rules_channel_id else None
        welcome = self.guild.get_channel(self.state.welcome_channel_id) if self.state.welcome_channel_id else None
        help_c = self.guild.get_channel(self.state.help_channel_id) if self.state.help_channel_id else None
        ann = self.guild.get_channel(self.state.announcements_channel_id) if self.state.announcements_channel_id else None
        roles = [self.guild.get_role(rid) for rid in self.state.staff_role_ids]
        roles_str = ", ".join(r.mention for r in roles if r) or "_aucun_"
        feats_str = ", ".join(self.state.enabled_features) or "_aucune_"
        tpl_label = TEMPLATE_LABELS.get(Template(self.state.template), "—") if self.state.template else "—"
        prot_label = PROTECTION_LEVEL_LABELS.get(
            ProtectionLevel(self.state.protection_level)
        ) if self.state.protection_level else "—"

        b_back = ui.Button(label=A.BACK_ICON, style=discord.ButtonStyle.secondary, custom_id="wiz6_back")
        async def _back(i):
            await WizardStep5(self.owner, self.guild).render_to(i)
        b_back.callback = _back

        b_apply = ui.Button(label="🚀 Appliquer la configuration", style=discord.ButtonStyle.success, custom_id="wiz6_apply")
        async def _apply(i):
            await i.response.defer(ephemeral=True)
            report = await apply_wizard_config(self.state, self.guild)
            applied = ", ".join(report["applied"]) or "—"
            errs = "\n".join(f"- {e}" for e in report["errors"]) or "_aucune_"
            msg = (
                f"{S.DONE_ICON} **Configuration appliquée !**\n\n"
                f"**Modules configurés** : {applied}\n"
                f"**Erreurs** :\n{errs}\n\n"
                f"_Tu peux affiner toutes les options via_ `/configure`."
            )
            await i.followup.send(msg, ephemeral=True)
            clear_state(self.guild.id)

        b_apply.callback = _apply

        items = [
            _title("✔️ Récapitulatif"),
            _subtitle(_progress_bar(6, self.TOTAL_STEPS)),
            _divider(),
            _kv([
                ("📋 Template", tpl_label),
                ("📜 Salon règles", rules.mention if rules else "—"),
                ("👋 Salon accueil", welcome.mention if welcome else "—"),
                ("💬 Salon aide", help_c.mention if help_c else "—"),
                ("📣 Salon annonces", ann.mention if ann else "—"),
                ("👥 Rôles staff", roles_str),
                ("🛡️ Niveau protection", prot_label),
                ("💬 Features actives", feats_str),
            ]),
            _divider(),
            _subtitle("Une sauvegarde automatique est créée avant l'application (restaurable via `/admin → Sauvegardes`)."),
            _divider(),
            ui.ActionRow(b_back, b_apply),
        ]
        self.add_item(_container(*items, color=Palette.SUCCESS))

        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)


# =============================================================================
# COMMAND SETUP
# =============================================================================

def setup_setup_command(bot: discord.Client) -> None:
    """Enregistre le slash command /setup sur le bot."""
    tree = getattr(bot, "tree", None)
    if tree is None:
        return

    @tree.command(
        name="setup",
        description="Wizard de configuration initiale (owner only)",
    )
    async def _setup_cmd(interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Cette commande est réservée aux serveurs.", ephemeral=True,
            )
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(Msg.NOT_OWNER, ephemeral=True)
        view = WizardStep1(interaction.user, interaction.guild)
        await view.render_to(interaction, edit=False)


__all__ = [
    "Template",
    "TEMPLATE_LABELS",
    "ProtectionLevel",
    "WizardState",
    "load_state",
    "save_state",
    "clear_state",
    "apply_wizard_config",
    "WizardStep1",
    "WizardStep2",
    "WizardStep3",
    "WizardStep4",
    "WizardStep5",
    "WizardStep6",
    "setup_setup_command",
]
