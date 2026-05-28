"""
staff_sanction.py — Salon staff dédié aux actions de modération (Phase 147).

🎯 OBJECTIF : ne plus se réveiller un matin pour découvrir que le
serveur a été attaqué et que personne n'a rien fait.

Quand un module de sécurité détecte une infraction (token grabber,
webhook leak, impersonation, badwords, spam, etc.), il :
1. Prend une action immédiate (delete message, mute soft, etc.)
2. Crée un PANEL dans un salon dédié `🚨-actions-staff`
3. Le staff voit le panel avec 4 boutons : Mute / Warn / Kick / Ban
4. Clic sur un bouton → sanction appliquée + panel auto-delete

Le salon staff est :
- Auto-créé au premier setup (catégorie 🛡️ Modération)
- Privé : visible uniquement par les rôles ayant `manage_messages`
- Persistant : les panels survivent au reboot (custom_id encodé)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- ensure_channel(guild) -> TextChannel (idempotent)
- create_sanction_panel(guild, target, reason, evidence_text,
                        evidence_channel_id, auto_action_taken,
                        source) -> Message | None
- register_persistent_views(bot) — à appeler après setup pour re-attacher
  les views au boot.

DB tables :
- staff_sanction_log (id PK, guild_id, target_user_id, source,
                      reason, evidence, auto_action, created_at,
                      final_action, decided_by, decided_at,
                      panel_message_id)

⚠️ RULES.md :
- Owner et super-owner (ID 1027544786068783194) ne peuvent JAMAIS être
  kick/ban via ce panel (sécurité absolue).
- Les boutons vérifient `manage_messages` pour autoriser le click.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ui import View, Button

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

SUPER_OWNER_ID = 1027544786068783194
STAFF_CHANNEL_NAME = "🚨-actions-staff"
STAFF_CATEGORY_HINT = "🛡️ Modération"


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS staff_sanction_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_user_id INTEGER NOT NULL,
                    source TEXT,
                    reason TEXT,
                    evidence TEXT,
                    auto_action TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    final_action TEXT,
                    decided_by INTEGER,
                    decided_at TIMESTAMP,
                    panel_message_id INTEGER,
                    panel_channel_id INTEGER
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sanction_panel_msg "
                "ON staff_sanction_log(panel_message_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[staff_sanction init_db] {ex}")


# ─── Channel management ─────────────────────────────────────────────────────

async def ensure_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Renvoie le salon staff dédié. Le crée si absent."""
    if not guild:
        return None
    try:
        # Recherche existant
        for ch in guild.text_channels:
            if ch.name == STAFF_CHANNEL_NAME:
                return ch

        # Crée la catégorie si absente
        category = None
        for cat in guild.categories:
            if STAFF_CATEGORY_HINT.lower() in cat.name.lower() \
               or "modération" in cat.name.lower() \
               or "staff" in cat.name.lower():
                category = cat
                break
        if category is None:
            try:
                category = await guild.create_category(
                    STAFF_CATEGORY_HINT,
                    reason="Anti-raid : catégorie staff",
                )
            except Exception:
                pass

        # Overwrites : @everyone DENY, manage_messages roles ALLOW
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, read_messages=False,
            ),
        }
        for role in guild.roles:
            try:
                if role.permissions.manage_messages or \
                   role.permissions.kick_members or \
                   role.permissions.ban_members:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, read_messages=True,
                        send_messages=True, embed_links=True,
                    )
            except Exception:
                pass
        # Bot lui-même
        try:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, read_messages=True,
                send_messages=True, manage_messages=True,
                embed_links=True,
            )
        except Exception:
            pass

        ch = await guild.create_text_channel(
            STAFF_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            topic=(
                "Actions de modération pré-mâchées par les détecteurs auto. "
                "Cliquez sur un bouton pour valider la sanction."
            ),
            reason="Anti-raid : salon actions staff",
        )
        return ch
    except Exception as ex:
        print(f"[staff_sanction ensure_channel] {ex}")
        return None


# ─── Panel builder ──────────────────────────────────────────────────────────

# ─── DynamicItem pour persistance des boutons sanction (Phase 150) ────────
# Le pattern: sanction_<action>_<sanction_id>
# Discord.py va matcher tous les custom_ids correspondants et appeler le
# callback même après reboot du bot.
_ACTION_LABELS = {
    "mute_1h": ("⏰ Mute 1h", discord.ButtonStyle.secondary),
    "warn":    ("⚠️ Warn", discord.ButtonStyle.primary),
    "kick":    ("👢 Kick", discord.ButtonStyle.danger),
    "ban":     ("🔨 Ban", discord.ButtonStyle.danger),
    "ignore":  ("✅ Faux positif", discord.ButtonStyle.success),
}


class SanctionDynamicButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"sanction_(?P<action>mute_1h|warn|kick|ban|ignore)_(?P<sid>\d+)",
):
    """Bouton dynamique persistant — survit aux reboots du bot.

    Le custom_id encode l'action + le sanction_id. Au reboot, Discord
    re-route l'interaction vers from_custom_id() qui reconstruit
    l'instance, puis appelle callback().
    """

    def __init__(self, action: str, sanction_id: int):
        label, style = _ACTION_LABELS.get(
            action, ("?", discord.ButtonStyle.secondary)
        )
        super().__init__(
            Button(
                label=label,
                style=style,
                custom_id=f"sanction_{action}_{sanction_id}",
            )
        )
        self.action = action
        self.sanction_id = sanction_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction,
        item: discord.ui.Button, match: re.Match,
    ):
        return cls(match["action"], int(match["sid"]))

    async def callback(self, interaction: discord.Interaction):
        await _handle_sanction_click(
            interaction, self.sanction_id, self.action
        )


class SanctionView(View):
    """View standard utilisée à la création du panel (avant persistance)."""

    def __init__(self, sanction_id: int):
        super().__init__(timeout=None)
        self.sanction_id = sanction_id
        for action in ("mute_1h", "warn", "kick", "ban", "ignore"):
            self.add_item(SanctionDynamicButton(action, sanction_id))


async def _handle_sanction_click(
    i: discord.Interaction, sanction_id: int, action: str
):
    """Traite le clic sur un bouton de sanction."""
    try:
        # Permission check
        try:
            perms = i.channel.permissions_for(i.user)
            is_super = i.user.id == SUPER_OWNER_ID or \
                       i.user.id == (i.guild.owner_id if i.guild else 0)
            if not (is_super or perms.manage_messages or
                    perms.kick_members or perms.ban_members):
                return await i.response.send_message(
                    "🔒 Permission staff requise.", ephemeral=True
                )
        except Exception:
            pass

        # Charge la sanction
        if _get_db is None:
            return await i.response.send_message(
                "❌ DB indisponible.", ephemeral=True
            )
        async with _get_db() as db:
            async with db.execute(
                "SELECT target_user_id, reason, final_action "
                "FROM staff_sanction_log WHERE id=?",
                (sanction_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return await i.response.send_message(
                "❌ Sanction introuvable.", ephemeral=True
            )
        target_id, reason, already_done = int(row[0]), row[1], row[2]
        if already_done:
            return await i.response.send_message(
                f"ℹ️ Déjà traité : `{already_done}`.", ephemeral=True
            )

        # Protection owner/super-owner
        if target_id in (SUPER_OWNER_ID, i.guild.owner_id) \
           and action in ("kick", "ban"):
            return await i.response.send_message(
                "🔒 Impossible de kick/ban l'owner ou super-owner.",
                ephemeral=True,
            )

        await i.response.defer(ephemeral=True)
        target = i.guild.get_member(target_id)

        applied = "unknown"
        details = ""

        if action == "ignore":
            applied = "ignored"
            details = "Faux positif — aucune sanction"

        elif action == "warn":
            applied = "warned"
            details = "Avertissement noté"
            if target:
                try:
                    await target.send(
                        f"⚠️ **{i.guild.name}** — Tu as reçu un "
                        f"**avertissement** du staff.\n"
                        f"Raison : {reason}\n"
                        f"_Reste cool, c'est juste un rappel._"
                    )
                except Exception:
                    pass

        elif action == "mute_1h":
            applied = "muted_1h"
            details = "Mute 1 heure"
            if target:
                try:
                    until = datetime.now(timezone.utc) + timedelta(hours=1)
                    await target.timeout(until, reason=f"Staff: {reason}")
                except Exception as ex:
                    details += f" (échec : {ex})"

        elif action == "kick":
            applied = "kicked"
            details = "Kické du serveur"
            if target:
                try:
                    await target.kick(reason=f"Staff: {reason}")
                except Exception as ex:
                    details += f" (échec : {ex})"

        elif action == "ban":
            applied = "banned"
            details = "Banni du serveur"
            if target:
                try:
                    await target.ban(
                        reason=f"Staff: {reason}",
                        delete_message_seconds=86400,  # 24h
                    )
                except Exception as ex:
                    details += f" (échec : {ex})"

        # Update DB
        async with _get_db() as db:
            await db.execute(
                "UPDATE staff_sanction_log SET final_action=?, "
                "decided_by=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
                (applied, i.user.id, sanction_id),
            )
            await db.commit()

        # Confirme à l'user staff
        await i.followup.send(
            f"✅ Action `{applied}` appliquée à <@{target_id}>.\n"
            f"_{details}_",
            ephemeral=True,
        )

        # Supprime le panel (auto-cleanup)
        try:
            if i.message:
                await i.message.delete()
        except Exception:
            pass

    except Exception as ex:
        print(f"[_handle_sanction_click] {ex}")
        try:
            if not i.response.is_done():
                await i.response.send_message(
                    f"❌ Erreur : `{ex}`", ephemeral=True
                )
            else:
                await i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
        except Exception:
            pass


def _build_panel_view(_v2_helpers: dict, sanction_id: int, target: discord.Member,
                     reason: str, evidence_text: str,
                     evidence_channel_id: int, auto_action: str,
                     source: str):
    """LayoutView V2 avec contexte + boutons d'action."""
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _SanctionPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            items = []
            items.append(v2_title("🚨  ACTION STAFF REQUISE"))
            items.append(v2_subtitle(
                f"**Source :** `{source}` · **Sanction ID :** `{sanction_id}`"
            ))
            items.append(v2_divider())

            target_line = (
                f"**Cible :** {target.mention} (`{target.name}` · "
                f"ID `{target.id}`)" if target else
                f"**Cible :** User ID inconnu"
            )
            items.append(v2_body(target_line))
            items.append(v2_body(f"**Raison :** {reason}"))

            if evidence_channel_id:
                items.append(v2_body(
                    f"**Salon :** <#{evidence_channel_id}>"
                ))
            if evidence_text:
                ev = evidence_text[:600].replace("`", "'")
                items.append(v2_body(f"**Contenu :**\n```\n{ev}\n```"))
            if auto_action:
                items.append(v2_body(
                    f"**Action auto déjà prise :** _{auto_action}_"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "_Choisis l'action finale. Le panel se supprime ensuite._"
            ))
            self.add_item(v2_container(*items, color=0xE74C3C))

            sv = SanctionView(sanction_id)
            for child in sv.children:
                try:
                    self.add_item(child)
                except Exception:
                    pass

    return _SanctionPanel()


# ─── API publique : create_sanction_panel ───────────────────────────────────

async def create_sanction_panel(
    guild: discord.Guild,
    target: discord.Member,
    reason: str,
    evidence_text: str = "",
    evidence_channel_id: Optional[int] = None,
    auto_action_taken: str = "",
    source: str = "auto",
) -> Optional[discord.Message]:
    """Crée et poste un panel sanction dans le salon staff dédié.
    Renvoie le message créé (ou None)."""
    if not guild or target is None:
        return None
    if _get_db is None or _v2 is None:
        return None
    try:
        # 1) Trouve/crée le salon
        ch = await ensure_channel(guild)
        if ch is None:
            return None

        # 2) Insère la sanction en DB pour avoir l'ID
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO staff_sanction_log "
                "(guild_id, target_user_id, source, reason, evidence, "
                "auto_action) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild.id, target.id, source, reason,
                    evidence_text[:1000], auto_action_taken,
                ),
            )
            sanction_id = cur.lastrowid
            await db.commit()

        # 3) Build view + post
        view = _build_panel_view(
            _v2, sanction_id, target, reason, evidence_text,
            evidence_channel_id or 0, auto_action_taken, source,
        )
        msg = await ch.send(view=view)

        # 4) Stocke le message_id pour retrouver le panel
        async with _get_db() as db:
            await db.execute(
                "UPDATE staff_sanction_log SET panel_message_id=?, "
                "panel_channel_id=? WHERE id=?",
                (msg.id, ch.id, sanction_id),
            )
            await db.commit()

        return msg
    except Exception as ex:
        print(f"[staff_sanction create_sanction_panel] {ex}")
        return None


def register_persistent_views(bot_instance):
    """À appeler dans on_ready après init_db. Enregistre le DynamicItem
    qui matche TOUS les custom_ids sanction_*_*. Marche pour les sanctions
    créées AVANT et APRÈS le reboot."""
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(SanctionDynamicButton)
    except Exception as ex:
        print(f"[staff_sanction register_persistent_views] {ex}")


__all__ = [
    "setup",
    "init_db",
    "ensure_channel",
    "create_sanction_panel",
    "register_persistent_views",
    "SanctionView",
]
