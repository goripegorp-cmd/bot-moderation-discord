"""update_ping_role.py — Bouton « 🔔 Me ping » sous chaque mise à jour (owner 2026-07-12).

DEMANDE OWNER : sous chaque publication d'update (Roblox, WoW, CS2, devblogs…), un petit bouton
pour choisir d'être pingé ou non. Le membre CLIQUE → il gagne un rôle → il sera pingé aux
prochaines updates. Re-clic → il le perd. 100 % opt-in, zéro pression.

🔒 RÈGLE ABSOLUE (owner, rappel explicite : « ne fais pas la même erreur que la dernière fois ») :
le rôle est **`mentionable=False`** — PERSONNE ne peut le mentionner, SEUL le bot le ping (il a la
permission « Mentionner tout le monde », donc `allowed_mentions(roles=[role])` marche même sur un
rôle non-mentionnable). Rappel de l'INCIDENT : un rôle d'event créé en `mentionable=True` avait
permis à un membre de ping TOUT le serveur en postant une arnaque crypto type MrBeast.
→ Ici : mentionable=False à la CRÉATION **ET** re-verrouillé à chaque `ensure_role` (si quelqu'un
  le repasse mentionnable à la main, on le re-verrouille au prochain passage). hoist=False aussi
  (n'encombre pas la sidebar).

KINDS (extensible) : 'updates' (mises à jour de jeux) · 'sneak' (sneak-peek / avant-premières).

Module PUR : aucune dépendance à bot.py. `get_db` injecté par setup(). 100 % FAIL-SAFE.
"""
from __future__ import annotations

from typing import Optional

import discord

_get_db = None
_bot = None

# kind -> (nom du rôle, couleur, libellé humain)
KINDS = {
    'updates': ("🔔 Mises à jour", 0x5865F2, "les mises à jour de jeux"),
    'sneak':   ("👀 Sneak Peek",   0xEB459E, "les avant-premières (sneak-peek)"),
}


def setup(bot_instance, get_db_fn) -> None:
    global _bot, _get_db
    _bot = bot_instance
    _get_db = get_db_fn


async def init_db() -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS update_ping_roles (
                    guild_id INTEGER NOT NULL,
                    kind     TEXT    NOT NULL,
                    role_id  INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, kind)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[update_ping_role init_db] {ex}")


async def _get_role_id(guild_id: int, kind: str) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT role_id FROM update_ping_roles WHERE guild_id=? AND kind=?",
                (int(guild_id), str(kind)),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


async def _save_role_id(guild_id: int, kind: str, role_id: int) -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO update_ping_roles(guild_id, kind, role_id) VALUES(?,?,?) "
                "ON CONFLICT(guild_id, kind) DO UPDATE SET role_id=excluded.role_id",
                (int(guild_id), str(kind), int(role_id)),
            )
            await db.commit()
    except Exception as ex:
        print(f"[update_ping_role save] {ex}")


async def ensure_role(guild: discord.Guild, kind: str) -> Optional[discord.Role]:
    """Récupère (ou crée) le rôle de ping. TOUJOURS non-mentionnable. None si impossible."""
    if guild is None or kind not in KINDS:
        return None
    name, color, _lbl = KINDS[kind]
    role = None
    try:
        rid = await _get_role_id(guild.id, kind)
        if rid:
            role = guild.get_role(rid)
        if role is None:                       # perdu / supprimé → retrouve par nom
            role = discord.utils.get(guild.roles, name=name)
        if role is None:
            me = guild.me
            if not (me and me.guild_permissions.manage_roles):
                return None                    # pas la perm → fail-soft
            role = await guild.create_role(
                name=name, colour=discord.Colour(color),
                mentionable=False,             # 🔒 JAMAIS mentionnable (incident 2026-06-27)
                hoist=False,                   # n'encombre pas la liste des membres
                reason="Rôle de ping des mises à jour (opt-in par bouton)")
        if role is not None:
            await _save_role_id(guild.id, kind, role.id)
            # 🔒 RE-VERROUILLAGE : si quelqu'un l'a repassé mentionnable à la main, on corrige.
            try:
                if role.mentionable and guild.me and guild.me.guild_permissions.manage_roles:
                    await role.edit(mentionable=False,
                                    reason="Sécurité : ce rôle ne doit JAMAIS être mentionnable")
            except Exception:
                pass
    except Exception as ex:
        print(f"[update_ping_role ensure_role {kind}] {ex}")
        return None
    return role


async def mention_for(guild: discord.Guild, kind: str) -> str:
    """Texte de ping à mettre AVANT l'embed ('' si le rôle n'existe pas ou n'a aucun membre).
    ⚠️ L'appelant DOIT passer `allowed_mentions=discord.AllowedMentions(roles=[role], everyone=False,
    users=False)` — jamais roles=True en aveugle (on ne ping QUE ce rôle-là)."""
    try:
        role = await ensure_role(guild, kind)
        if role is None or len(role.members) == 0:
            return ""                          # personne n'a opt-in → aucun ping (zéro bruit)
        return role.mention
    except Exception:
        return ""


async def allowed_for(guild: discord.Guild, kind: str) -> discord.AllowedMentions:
    """AllowedMentions qui autorise UNIQUEMENT ce rôle. Jamais @everyone, jamais les users."""
    try:
        role = await ensure_role(guild, kind)
        if role is not None:
            return discord.AllowedMentions(everyone=False, users=False, roles=[role])
    except Exception:
        pass
    return discord.AllowedMentions.none()


def build_view(kind: str):
    """Vue à coller SOUS chaque update : un seul bouton toggle. Persistant (DynamicItem)."""
    try:
        v = discord.ui.View(timeout=None)
        v.add_item(discord.ui.Button(
            label="Me ping pour les prochaines",
            style=discord.ButtonStyle.secondary,
            emoji="🔔",
            custom_id=f"updping:{kind}"))
        return v
    except Exception:
        return None


class UpdatePingButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r"updping:(?P<kind>[a-z]+)"):
    """Bouton PERSISTANT (re-capté après un reboot) : donne/retire le rôle de ping."""

    def __init__(self, kind: str):
        super().__init__(discord.ui.Button(
            label="Me ping pour les prochaines",
            style=discord.ButtonStyle.secondary,
            emoji="🔔",
            custom_id=f"updping:{kind}"))
        self.kind = kind

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["kind"])

    async def callback(self, interaction: discord.Interaction):
        # DEFER-FIRST : on ACQUITTE avant toute I/O (règle des 3 s de Discord).
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        try:
            guild, member = interaction.guild, interaction.user
            if guild is None or not isinstance(member, discord.Member):
                return
            role = await ensure_role(guild, self.kind)
            if role is None:
                await interaction.followup.send(
                    "❌ Je n'ai pas pu créer le rôle (il me manque « Gérer les rôles »). "
                    "Préviens un admin.", ephemeral=True)
                return
            _lbl = KINDS.get(self.kind, ("", 0, "ces publications"))[2]
            if role in member.roles:           # déjà opt-in → on retire (toggle)
                await member.remove_roles(role, reason="Opt-out des pings de mises à jour")
                await interaction.followup.send(
                    f"🔕 C'est noté — tu **ne seras plus pingé** pour {_lbl}.\n"
                    f"-# Reclique sur le bouton quand tu veux pour les réactiver.",
                    ephemeral=True)
            else:
                await member.add_roles(role, reason="Opt-in des pings de mises à jour")
                await interaction.followup.send(
                    f"🔔 C'est bon — tu seras **pingé** pour {_lbl} ! ({role.mention})\n"
                    f"-# Reclique sur le bouton pour arrêter à tout moment.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            try:
                await interaction.followup.send(
                    "❌ Je ne peux pas te donner ce rôle : mon rôle doit être **au-dessus** du sien "
                    "dans la liste. Préviens un admin.", ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            # ⚠️ NE JAMAIS répondre « ✅ Pris en compte » ici (bug corrigé le 2026-07-17) : le rôle
            # n'a PAS été basculé. Le membre croyait s'être inscrit, n'était jamais pingé, et ne
            # recliquait jamais puisqu'on lui avait confirmé le succès. Le bouton est un toggle
            # idempotent → l'inviter à recliquer est sans risque.
            import sys as _sys
            print(f"[update_ping_role callback] {ex}", file=_sys.stderr, flush=True)
            try:
                await interaction.followup.send(
                    "❌ Ça n'a pas marché — reclique dans un instant.\n"
                    "-# Si ça persiste, préviens un admin.", ephemeral=True)
            except Exception:
                pass


def register_persistent(bot_instance) -> None:
    """À appeler dans on_ready : re-capte les boutons des anciens messages après un reboot."""
    try:
        bot_instance.add_dynamic_items(UpdatePingButton)
        print("[update_ping_role] UpdatePingButton enregistré (boutons persistants)")
    except Exception as ex:
        print(f"[update_ping_role register_persistent] {ex}")
