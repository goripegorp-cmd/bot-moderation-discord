"""
roles_panel.py - Panneau de self-service pour les roles de mention (Phase 3.1).

Permet aux membres de cliquer sur des boutons pour s'attribuer/retirer eux-memes
des roles de mention (ex: "Stream Alerts", "Trade", "Gaming News"). Evite les
@everyone abusifs : seuls les membres opt-in sont mentionnes.

Architecture :
    - RolesPanelConfig : config persistante (titre, description, rôles, salon)
    - build_panel_view(config) : retourne la LayoutView a poster
    - RolesPanelView : LayoutView avec un bouton par role + label personnalise
    - Click button -> toggle role pour l'utilisateur

UX :
    - 1 message par salon par panel
    - Boutons en grille (4-5 par ligne)
    - Confirmation ephemere "✅ Role X ajouté/retiré"
    - Auto-update du compteur de membres par role

Stockage : JSON par guild, supporte plusieurs panels par guild.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import discord
from discord import ui

from paths import module_dir


DATA_DIR = module_dir("roles_panels")


# =============================================================================
# CONFIG
# =============================================================================

@dataclass
class RolesPanelRole:
    """Un role configurable dans le panel."""

    role_id: int
    label: str                   # texte du bouton, max 80 chars
    emoji: Optional[str] = None  # emoji optionnel (unicode ou custom :name:id:)
    description: str = ""        # texte d'aide affiche en sous-titre


@dataclass
class RolesPanelConfig:
    """Config d'un panel de roles."""

    panel_id: str
    guild_id: int
    channel_id: int               # ou le panel sera affiche
    message_id: Optional[int] = None  # ID du message Discord (apres post)
    title: str = "🔔 Mes notifications"
    description: str = ("Choisis les sujets qui t'interessent. Tu seras mentionne "
                        "uniquement sur ceux que tu actives.")
    color: int = 0x5865F2
    roles: list[RolesPanelRole] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "panel_id": self.panel_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "title": self.title,
            "description": self.description,
            "color": self.color,
            "roles": [asdict(r) for r in self.roles],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RolesPanelConfig":
        return cls(
            panel_id=data["panel_id"],
            guild_id=data["guild_id"],
            channel_id=data["channel_id"],
            message_id=data.get("message_id"),
            title=data.get("title", "🔔 Mes notifications"),
            description=data.get("description", ""),
            color=data.get("color", 0x5865F2),
            roles=[RolesPanelRole(**r) for r in data.get("roles", [])],
        )


# =============================================================================
# STOCKAGE
# =============================================================================

_io_lock = asyncio.Lock()


def _path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}.json"


async def load_panels(guild_id: int) -> list[RolesPanelConfig]:
    async with _io_lock:
        p = _path(guild_id)
        if not p.exists():
            return []
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            return [RolesPanelConfig.from_dict(d) for d in raw]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return []


async def save_panels(guild_id: int, panels: list[RolesPanelConfig]) -> None:
    async with _io_lock:
        payload = [p.to_dict() for p in panels]
        _path(guild_id).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


async def get_panel(guild_id: int, panel_id: str) -> Optional[RolesPanelConfig]:
    panels = await load_panels(guild_id)
    return next((p for p in panels if p.panel_id == panel_id), None)


async def upsert_panel(panel: RolesPanelConfig) -> None:
    panels = await load_panels(panel.guild_id)
    panels = [p for p in panels if p.panel_id != panel.panel_id]
    panels.append(panel)
    await save_panels(panel.guild_id, panels)


async def delete_panel(guild_id: int, panel_id: str) -> bool:
    panels = await load_panels(guild_id)
    new_panels = [p for p in panels if p.panel_id != panel_id]
    if len(new_panels) == len(panels):
        return False
    await save_panels(guild_id, new_panels)
    return True


def new_panel_id() -> str:
    return uuid.uuid4().hex[:10]


# =============================================================================
# VIEW
# =============================================================================

class RolesPanelView(ui.LayoutView):
    """LayoutView persistante avec un bouton par role."""

    def __init__(self, config: RolesPanelConfig):
        super().__init__(timeout=None)
        self.config = config
        self._build()

    def _build(self):
        self.clear_items()

        items: list = []
        items.append(ui.TextDisplay(f"# {self.config.title}"))
        if self.config.description:
            items.append(ui.TextDisplay(f"-# {self.config.description}"))
        items.append(ui.Separator())

        if not self.config.roles:
            items.append(ui.TextDisplay("_Aucun rôle configuré._"))
        else:
            # Liste des roles avec description
            role_lines = []
            for r in self.config.roles:
                emoji = (r.emoji + " ") if r.emoji else ""
                desc = f" — {r.description}" if r.description else ""
                role_lines.append(f"{emoji}**{r.label}**{desc}")
            items.append(ui.TextDisplay("\n".join(role_lines)))
            items.append(ui.Separator())

            # Boutons : 5 max par ActionRow, jusqu'a 5 rows = 25 max
            current_row: list = []
            rows = []
            for r in self.config.roles[:25]:
                btn = ui.Button(
                    label=r.label[:80],
                    style=discord.ButtonStyle.primary,
                    custom_id=f"rolespanel:{self.config.panel_id}:{r.role_id}",
                    emoji=r.emoji if r.emoji and not r.emoji.startswith("<") else None,
                )
                btn.callback = self._make_toggle(r.role_id)
                current_row.append(btn)
                if len(current_row) == 5:
                    rows.append(ui.ActionRow(*current_row))
                    current_row = []
            if current_row:
                rows.append(ui.ActionRow(*current_row))

            for row in rows:
                items.append(row)

        items.append(ui.Separator())
        items.append(ui.TextDisplay("-# Tes choix sont privés."))

        self.add_item(ui.Container(*items, accent_color=discord.Color(self.config.color)))

    def _make_toggle(self, role_id: int):
        async def _toggle(i: discord.Interaction):
            try:
                if i.guild is None or not isinstance(i.user, discord.Member):
                    return await i.response.send_message(
                        "❌ Erreur : interaction hors serveur.", ephemeral=True
                    )
                role = i.guild.get_role(role_id)
                if role is None:
                    return await i.response.send_message(
                        "❌ Ce rôle n'existe plus.", ephemeral=True
                    )
                # Verifier que le bot peut gerer ce role
                if role >= i.guild.me.top_role:
                    return await i.response.send_message(
                        "❌ Le rôle est plus haut que celui du bot.", ephemeral=True
                    )
                if role.managed:
                    return await i.response.send_message(
                        "❌ Ce rôle est géré par une intégration.", ephemeral=True
                    )

                member: discord.Member = i.user
                if role in member.roles:
                    await member.remove_roles(role, reason="Roles panel self-service")
                    await i.response.send_message(
                        f"➖ Rôle {role.mention} retiré. Tu ne seras plus mentionné.",
                        ephemeral=True,
                    )
                else:
                    await member.add_roles(role, reason="Roles panel self-service")
                    await i.response.send_message(
                        f"➕ Rôle {role.mention} ajouté. Tu seras mentionné pour ce sujet.",
                        ephemeral=True,
                    )
            except discord.Forbidden:
                try:
                    await i.response.send_message(
                        "❌ Le bot n'a pas les permissions pour gérer ce rôle.",
                        ephemeral=True,
                    )
                except Exception:
                    pass
            except Exception as ex:
                import traceback; traceback.print_exc()
                try:
                    await i.response.send_message(f"❌ Erreur : {ex}", ephemeral=True)
                except Exception:
                    pass
        return _toggle


# =============================================================================
# RENDER / POST
# =============================================================================

async def post_or_update_panel(bot, config: RolesPanelConfig) -> Optional[int]:
    """Poste le panel ou edite le message existant. Retourne le message_id."""
    chan = bot.get_channel(config.channel_id)
    if chan is None:
        return None

    view = RolesPanelView(config)

    # Edit si message existe
    if config.message_id:
        try:
            msg = await chan.fetch_message(config.message_id)
            await msg.edit(view=view, embeds=[], attachments=[])
            return config.message_id
        except (discord.NotFound, discord.HTTPException):
            pass  # message supprime, on en poste un nouveau

    try:
        new_msg = await chan.send(view=view)
        config.message_id = new_msg.id
        await upsert_panel(config)
        return new_msg.id
    except Exception as ex:
        import traceback; traceback.print_exc()
        return None


async def register_persistent_views(bot) -> int:
    """Recharge les RolesPanelView persistantes (a appeler au boot).

    Retourne le nombre de panels enregistres.
    """
    count = 0
    # On scanne tous les fichiers de panels
    for path in DATA_DIR.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for d in raw:
                try:
                    cfg = RolesPanelConfig.from_dict(d)
                    view = RolesPanelView(cfg)
                    bot.add_view(view)
                    count += 1
                except Exception:
                    continue
        except (json.JSONDecodeError, OSError):
            continue
    return count


__all__ = [
    "RolesPanelRole",
    "RolesPanelConfig",
    "RolesPanelView",
    "load_panels",
    "save_panels",
    "get_panel",
    "upsert_panel",
    "delete_panel",
    "new_panel_id",
    "post_or_update_panel",
    "register_persistent_views",
]
