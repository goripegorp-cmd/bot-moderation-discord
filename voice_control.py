"""voice_control.py — Panneau de contrôle des vocaux temporaires « Voc Build » (owner 2026-06-15).

Quand un membre crée son vocal temporaire (join-to-create, table `temp_voice_rooms` côté
bot.py), le bot poste DANS le salon (chat texte intégré du vocal) un panneau V2 donnant au
PROPRIÉTAIRE, en 1 clic : 🔤 renommer · 👥 limite de places · 🔒 verrouiller/déverrouiller ·
👢 expulser · 👑 transférer. Fini les menus Discord natifs introuvables (demande #1 owner).

Conception (conforme aux directives) :
- Boutons PERSISTANTS (DynamicItem `vctl:<action>:<chid>`) → re-captés au reboot, jamais de
  « Échec de l'interaction » (le propriétaire est relu en DB au clic).
- NOMINATIF : seul le propriétaire (`temp_voice_rooms.owner_id`) agit ; le staff
  (`manage_channels`) peut dépanner (override). Sinon refus poli en éphémère.
- VERROU = deny `connect` à @everyone (overwrite de SALON, l'emporte sur la catégorie) +
  AUTO-DÉVERROUILLAGE anti-oubli (`locked_until`, tâche supervisée). Par défaut le vocal
  reste PUBLIC (cohérent avec l'entraide : on veut que les gens se rejoignent).
- Outil STAFF : lister les vocaux temp actifs (occupants/âge/proprio) + GELER/DÉGELER
  (utile en raid). Lecture depuis `temp_voice_rooms` (source de vérité, anti-orphelin).
- Anti-429 : aucune rafale ; `get_partial_message`/edits ponctuels ; sleeps si boucle.
- FAIL-OPEN / FAIL-SAFE : aucune action ne casse le bot ni on_voice_state_update.

API : setup(bot, get_db, v2) · init_db() · register_persistent(bot) · post_control_panel(
channel, owner_id) · unlock_expired_task (loop) · build_staff_voice_panel(guild).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

# ─── Deps injectées au boot ──────────────────────────────────────────────────
_bot = None
_get_db = None
_v2 = None

# Durée par défaut d'un verrou avant auto-déverrouillage (anti-oubli).
LOCK_AUTO_RELEASE_HOURS = 2
# Cap de la liste staff (anti-message géant / anti-429).
STAFF_LIST_MAX = 40


def setup(bot_instance, get_db_fn, v2_helpers: dict):
    global _bot, _get_db, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _v2 = v2_helpers or {}


async def init_db():
    """Table d'état (verrou) des vocaux temp. La table temp_voice_rooms appartient à
    bot.py (owner_id) ; on n'y touche pas. FAIL-OPEN."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            # prev_connect = état @everyone.connect AVANT verrou (1=True/0=False/NULL=hérite)
            # → restauré tel quel au déverrouillage (ne RENDS PAS public un vocal restreint).
            await db.execute(
                "CREATE TABLE IF NOT EXISTS temp_voice_state ("
                "channel_id INTEGER PRIMARY KEY, guild_id INTEGER, "
                "locked_until TIMESTAMP, prev_connect INTEGER)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[voice_control init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  État DB (propriétaire + verrou)
# ═══════════════════════════════════════════════════════════════════════════

async def _owner_of(channel_id: int) -> int:
    """Propriétaire du vocal temp (temp_voice_rooms). 0 si inconnu/non-temp. FAIL-OPEN."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT owner_id FROM temp_voice_rooms WHERE channel_id=?",
                (int(channel_id),),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


async def _set_owner(channel_id: int, new_owner_id: int) -> bool:
    """Transfère la propriété (UPDATE conditionnel : ne crée pas une ligne fantôme).
    Renvoie True si une ligne a bien été mise à jour. FAIL-SAFE."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE temp_voice_rooms SET owner_id=? WHERE channel_id=?",
                (int(new_owner_id), int(channel_id)),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[voice_control _set_owner] {ex}")
        return False


async def _is_locked(channel_id: int) -> bool:
    """True si le vocal est verrouillé ET le verrou pas encore expiré. FAIL-OPEN→False."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT locked_until FROM temp_voice_state WHERE channel_id=?",
                (int(channel_id),),
            ) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            return False
        until = _parse_ts(row[0])
        if until is None:
            return True  # date illisible → considéré verrouillé (fail-safe : l'UI dégèle)
        return datetime.now(timezone.utc) < until
    except Exception:
        return False


async def _record_lock(channel_id: int, guild_id: int, locked: bool, prev_connect=None):
    """Persiste l'état de verrou (locked_until = now+Xh + état connect mémorisé, ou supprime
    la ligne si déverrouillé). prev_connect : True/False/None. FAIL-SAFE."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            if locked:
                until = (datetime.now(timezone.utc)
                         + timedelta(hours=LOCK_AUTO_RELEASE_HOURS)).isoformat()
                pc = None if prev_connect is None else (1 if prev_connect else 0)
                await db.execute(
                    "INSERT OR REPLACE INTO temp_voice_state "
                    "(channel_id, guild_id, locked_until, prev_connect) VALUES (?,?,?,?)",
                    (int(channel_id), int(guild_id), until, pc))
            else:
                await db.execute(
                    "DELETE FROM temp_voice_state WHERE channel_id=?", (int(channel_id),))
            await db.commit()
    except Exception as ex:
        print(f"[voice_control _record_lock] {ex}")


async def _get_prev_connect(channel_id: int):
    """État @everyone.connect mémorisé avant le verrou (True/False/None=hérite). FAIL-OPEN→None."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT prev_connect FROM temp_voice_state WHERE channel_id=?",
                (int(channel_id),),
            ) as cur:
                row = await cur.fetchone()
        if not row or row[0] is None:
            return None
        return bool(row[0])
    except Exception:
        return None


def _parse_ts(val):
    """Parse souple d'un timestamp SQLite → datetime aware UTC, ou None."""
    try:
        s = str(val).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  Permissions (nominatif + override staff)
# ═══════════════════════════════════════════════════════════════════════════

async def _can_manage(interaction: discord.Interaction, channel_id: int):
    """(autorisé, owner_id). Autorisé si le cliqueur est le PROPRIÉTAIRE ou staff
    (manage_channels). FAIL-OPEN côté lecture (owner_id=0 si inconnu)."""
    owner_id = await _owner_of(channel_id)
    try:
        is_owner = interaction.user.id == owner_id and owner_id > 0
        is_staff = bool(getattr(interaction.user.guild_permissions, 'manage_channels', False))
        return (is_owner or is_staff), owner_id
    except Exception:
        return False, owner_id


# ═══════════════════════════════════════════════════════════════════════════
#  Panneau in-room
# ═══════════════════════════════════════════════════════════════════════════

def _b(label, action, chid, style=discord.ButtonStyle.secondary, emoji=None):
    return discord.ui.Button(label=label, style=style, emoji=emoji,
                             custom_id=f"vctl:{action}:{int(chid)}")


def _build_panel(channel_id: int, owner_id: int, locked: bool):
    """LayoutView du panneau de contrôle (Button NU → DynamicItem VoiceControlButton)."""
    LayoutView = _v2.get('LayoutView') or getattr(discord.ui, 'LayoutView', None)
    v2_container = _v2.get('v2_container')
    v2_body = _v2.get('v2_body')
    v2_title = _v2.get('v2_title')
    lock_label = "🔓 Déverrouiller" if locked else "🔒 Verrouiller"
    lock_style = discord.ButtonStyle.success if locked else discord.ButtonStyle.secondary
    head = (f"### 🎛️ Contrôle de ton vocal\n"
            f"Propriétaire : <@{int(owner_id)}>"
            + ("  ·  🔒 **verrouillé** (personne de nouveau ne peut entrer)" if locked else "")
            + "\n_Seul le propriétaire (ou le staff) peut utiliser ces boutons._")
    row1 = discord.ui.ActionRow(
        _b("Renommer", "rename", channel_id, emoji="🔤"),
        _b("Limite", "limit", channel_id, emoji="👥"),
        _b(lock_label.split(" ", 1)[1], "lock", channel_id, style=lock_style,
           emoji=("🔓" if locked else "🔒")),
    )
    row2 = discord.ui.ActionRow(
        _b("Expulser", "kick", channel_id, emoji="👢"),
        _b("Transférer", "xfer", channel_id, emoji="👑"),
    )
    if v2_container and v2_body:
        items = [v2_body(head), row1, row2]
        container = v2_container(*items, color=0x5865F2)

        class _Panel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(container)
        return _Panel()

    # Repli minimal si les helpers V2 manquent (ne devrait pas arriver).
    class _PanelFallback(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(discord.ui.TextDisplay(head))
            self.add_item(row1)
            self.add_item(row2)
    return _PanelFallback()


async def post_control_panel(channel, owner_id: int):
    """Poste le panneau de contrôle DANS le chat texte du vocal temp. Appelé à la
    création (depuis bot.py, après move_to). FAIL-SAFE : aucun crash si l'envoi échoue."""
    try:
        if channel is None:
            return
        locked = await _is_locked(channel.id)
        view = _build_panel(channel.id, int(owner_id or 0), locked)
        # Le chat texte des vocaux accepte .send() ; les clics de boutons marchent même
        # si le proprio n'a pas send_messages (interaction ≠ message).
        await channel.send(view=view)
    except discord.Forbidden:
        pass  # pas de send dans ce vocal → fail-safe (le proprio garde les menus natifs)
    except Exception as ex:
        print(f"[voice_control post_control_panel] {ex}")


async def _refresh_panel(interaction: discord.Interaction, channel_id: int, owner_id: int):
    """Réaffiche le panneau à jour APRÈS une action, en éditant le message du panneau si
    le clic vient de lui ; sinon poste un éphémère de confirmation. Anti double-ack."""
    locked = await _is_locked(channel_id)
    view = _build_panel(channel_id, owner_id, locked)
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(view=view)
    except Exception:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("✅ C'est fait.", ephemeral=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#  Modals (renommer / limite)
# ═══════════════════════════════════════════════════════════════════════════

class _RenameModal(discord.ui.Modal, title="🔤 Renommer le vocal"):
    def __init__(self, channel_id: int, owner_id: int):
        super().__init__(timeout=300)
        self.channel_id = int(channel_id)
        self.owner_id = int(owner_id)
        self.name = discord.ui.TextInput(
            label="Nouveau nom", placeholder="ex. Boss Crocodile", max_length=90, required=True)
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            ch = interaction.guild.get_channel(self.channel_id) if interaction.guild else None
            new = (self.name.value or "").strip()[:95]
            if ch is not None and new:
                try:
                    await ch.edit(name=new, reason=f"Renommage par {interaction.user}")
                except Exception:
                    pass
            await _refresh_panel(interaction, self.channel_id, self.owner_id)
        except Exception as ex:
            print(f"[voice_control rename submit] {ex}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("✅ Pris en compte.", ephemeral=True)
            except Exception:
                pass


class _LimitModal(discord.ui.Modal, title="👥 Limite de places"):
    def __init__(self, channel_id: int, owner_id: int):
        super().__init__(timeout=300)
        self.channel_id = int(channel_id)
        self.owner_id = int(owner_id)
        self.limit = discord.ui.TextInput(
            label="Nombre max (0 = illimité, 1-99)", placeholder="ex. 5",
            max_length=2, required=True)
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            raw = (self.limit.value or "0").strip()
            try:
                n = int(re.sub(r"[^0-9]", "", raw) or "0")
            except Exception:
                n = 0
            n = max(0, min(99, n))
            ch = interaction.guild.get_channel(self.channel_id) if interaction.guild else None
            if ch is not None:
                try:
                    await ch.edit(user_limit=n, reason=f"Limite par {interaction.user}")
                except Exception:
                    pass
            await _refresh_panel(interaction, self.channel_id, self.owner_id)
        except Exception as ex:
            print(f"[voice_control limit submit] {ex}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("✅ Pris en compte.", ephemeral=True)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
#  Selects éphémères (expulser / transférer)
# ═══════════════════════════════════════════════════════════════════════════

def _present_members(channel, exclude_id: int):
    """Membres humains présents dans le vocal (hors le cliqueur)."""
    out = []
    try:
        for m in list(getattr(channel, 'members', []) or []):
            if not m.bot and m.id != int(exclude_id):
                out.append(m)
    except Exception:
        pass
    return out[:25]  # cap select Discord


def _build_member_select_view(channel_id: int, owner_id: int, members, action: str):
    """Vue éphémère : un select des membres présents pour 'kick' ou 'xfer'."""
    LayoutView = _v2.get('LayoutView') or getattr(discord.ui, 'LayoutView', None)
    v2_container = _v2.get('v2_container')
    v2_body = _v2.get('v2_body')
    options = [discord.SelectOption(label=(m.display_name or str(m.id))[:100], value=str(m.id))
               for m in members]
    placeholder = "Qui expulser ?" if action == "kick" else "À qui transférer ?"
    sel = discord.ui.Select(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def _cb(i: discord.Interaction):
        await _on_member_select(i, channel_id, owner_id, action, sel.values)

    sel.callback = _cb
    title = ("👢 Expulser un membre" if action == "kick" else "👑 Transférer la propriété")
    if v2_container and v2_body:
        class _SelView(LayoutView):
            def __init__(self):
                super().__init__(timeout=180)
                self.add_item(v2_container(v2_body(f"### {title}"),
                                           discord.ui.ActionRow(sel), color=0x5865F2))
        return _SelView()

    class _SelViewFb(LayoutView):
        def __init__(self):
            super().__init__(timeout=180)
            self.add_item(discord.ui.TextDisplay(f"### {title}"))
            self.add_item(discord.ui.ActionRow(sel))
    return _SelViewFb()


async def _on_member_select(interaction, channel_id, owner_id, action, values):
    try:
        target_id = int(values[0]) if values else 0
        guild = interaction.guild
        ch = guild.get_channel(int(channel_id)) if guild else None
        target = guild.get_member(target_id) if guild else None
        if ch is None or target is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Membre/salon introuvable.", ephemeral=True)
            return
        if action == "kick":
            # Expulser = déconnecter du vocal (move_to None). Pas un kick serveur.
            try:
                if getattr(target, 'voice', None) and target.voice.channel and target.voice.channel.id == ch.id:
                    await target.move_to(None, reason=f"Expulsé du vocal par {interaction.user}")
                    msg = f"👢 {target.mention} a été retiré du vocal."
                else:
                    msg = "ℹ️ Ce membre n'est plus dans le vocal."
            except discord.Forbidden:
                msg = "❌ Je n'ai pas la permission « Déplacer des membres »."
            except Exception:
                msg = "❌ Action impossible."
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:  # xfer
            ok = await _set_owner(channel_id, target_id)
            if ok:
                # Bascule les overwrites élevés vers le nouveau proprio (best-effort).
                await _swap_owner_overwrites(ch, owner_id, target_id, interaction.user)
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"👑 Propriété transférée à {target.mention}.", ephemeral=True,
                        allowed_mentions=discord.AllowedMentions.none())
                # Met à jour le panneau in-room (nouveau proprio affiché).
                await _repost_or_log(ch, target_id)
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Transfert impossible (vocal non temporaire ?).", ephemeral=True)
    except Exception as ex:
        print(f"[voice_control _on_member_select] {ex}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("✅ Pris en compte.", ephemeral=True)
        except Exception:
            pass


async def _swap_owner_overwrites(channel, old_owner_id: int, new_owner_id: int, actor):
    """Donne au nouveau proprio les perms élevées (manage/mute/move) que le bot possède,
    et les retire à l'ancien. Best-effort, fail-safe, anti-429 (2 set_permissions max)."""
    try:
        guild = getattr(channel, 'guild', None)
        if guild is None:
            return
        me_perms = guild.me.guild_permissions if guild.me else None
        ow = discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True, send_messages=False)
        if me_perms:
            if me_perms.manage_channels:
                ow.manage_channels = True
            if me_perms.mute_members:
                ow.mute_members = True
            if me_perms.move_members:
                ow.move_members = True
        new_member = guild.get_member(int(new_owner_id))
        if new_member is not None:
            try:
                await channel.set_permissions(new_member, overwrite=ow,
                                              reason=f"Transfert de vocal par {actor}")
                await asyncio.sleep(0.3)
            except Exception:
                pass
        old_member = guild.get_member(int(old_owner_id))
        if old_member is not None and int(old_owner_id) != int(new_owner_id):
            try:
                await channel.set_permissions(old_member, overwrite=None,
                                              reason="Ancien proprio (transfert)")
            except Exception:
                pass
    except Exception as ex:
        print(f"[voice_control _swap_owner_overwrites] {ex}")


async def _repost_or_log(channel, new_owner_id: int):
    """Après transfert : reposte un panneau à jour dans le vocal (best-effort)."""
    try:
        await post_control_panel(channel, new_owner_id)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Verrou (lock / unlock)
# ═══════════════════════════════════════════════════════════════════════════

async def _apply_lock(channel, locked: bool, actor=None) -> bool:
    """Pose/retire le verrou en ne touchant QUE @everyone.connect, et en RESTAURANT l'état
    d'origine au déverrouillage (ne rend JAMAIS public un vocal restreint par rôle).
    Renvoie True si appliqué. FAIL-SAFE."""
    try:
        guild = getattr(channel, 'guild', None)
        if guild is None:
            return False
        everyone = guild.default_role
        try:
            ow = channel.overwrites_for(everyone)
        except Exception:
            ow = discord.PermissionOverwrite()
        if locked:
            prev = ow.connect  # True / False / None — à restaurer au déverrouillage
            ow.connect = False
            try:
                await channel.set_permissions(
                    everyone, overwrite=ow, reason=f"Verrouillage par {actor}")
            except discord.Forbidden:
                return False
            await _record_lock(channel.id, guild.id, True, prev)
            return True
        else:
            prev = await _get_prev_connect(channel.id)  # None=hérite / True / False
            ow.connect = prev
            try:
                await channel.set_permissions(
                    everyone, overwrite=ow, reason=f"Déverrouillage par {actor}")
            except discord.Forbidden:
                return False
            await _record_lock(channel.id, guild.id, False)
            return True
    except Exception as ex:
        print(f"[voice_control _apply_lock] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  DynamicItem (boutons persistants du panneau)
# ═══════════════════════════════════════════════════════════════════════════

class VoiceControlButton(discord.ui.DynamicItem[discord.ui.Button],
                         template=r"vctl:(?P<action>[a-z]+):(?P<chid>\d+)"):
    """Boutons du panneau de contrôle vocal. Re-captés au reboot ; le propriétaire est
    relu en DB au clic (jamais d'« Échec d'interaction »)."""
    def __init__(self, action: str, chid: int):
        super().__init__(discord.ui.Button(
            label="Vocal", style=discord.ButtonStyle.secondary,
            custom_id=f"vctl:{action}:{int(chid)}"))
        self.action = action
        self.chid = int(chid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["chid"]))

    async def callback(self, interaction: discord.Interaction):
        await _on_control_click(interaction, self.action, self.chid)


async def _on_control_click(interaction: discord.Interaction, action: str, channel_id: int):
    """Dispatch des actions du panneau. NOMINATIF (proprio ou staff). FAIL-SAFE."""
    try:
        if interaction.guild is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Serveur uniquement.", ephemeral=True)
            return
        ok, owner_id = await _can_manage(interaction, channel_id)
        if not ok:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ℹ️ Seul le **propriétaire** de ce vocal (ou le staff) peut utiliser ces boutons.",
                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        ch = interaction.guild.get_channel(int(channel_id))
        if ch is None or not isinstance(ch, discord.VoiceChannel):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "ℹ️ Ce vocal n'existe plus.", ephemeral=True)
            return

        if action == "rename":
            if not interaction.response.is_done():
                await interaction.response.send_modal(_RenameModal(channel_id, owner_id))
        elif action == "limit":
            if not interaction.response.is_done():
                await interaction.response.send_modal(_LimitModal(channel_id, owner_id))
        elif action == "lock":
            currently = await _is_locked(channel_id)
            await _apply_lock(ch, not currently, actor=interaction.user)
            await _refresh_panel(interaction, channel_id, owner_id)
        elif action == "kick":
            members = _present_members(ch, interaction.user.id)
            if not members:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "ℹ️ Personne d'autre dans le vocal.", ephemeral=True)
                return
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    view=_build_member_select_view(channel_id, owner_id, members, "kick"),
                    ephemeral=True)
        elif action == "xfer":
            members = _present_members(ch, interaction.user.id)
            if not members:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "ℹ️ Personne à qui transférer (le vocal doit contenir un autre membre).",
                        ephemeral=True)
                return
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    view=_build_member_select_view(channel_id, owner_id, members, "xfer"),
                    ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("❓ Action inconnue.", ephemeral=True)
    except Exception as ex:
        print(f"[voice_control _on_control_click {action}] {ex}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("✅ Pris en compte.", ephemeral=True)
        except Exception:
            pass


def register_persistent(bot_instance):
    """Enregistre le DynamicItem au boot (à appeler dans on_ready). FAIL-SAFE."""
    try:
        bot_instance.add_dynamic_items(VoiceControlButton)
    except Exception as ex:
        print(f"[voice_control register_persistent] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Auto-déverrouillage (tâche supervisée)
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=10)
async def unlock_expired_task():
    """Déverrouille les vocaux dont le verrou a expiré (anti-oubli). Supervisée, FAIL-OPEN."""
    if _bot is None or _get_db is None:
        return
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT channel_id, guild_id FROM temp_voice_state "
                    "WHERE locked_until IS NOT NULL AND locked_until <= ?",
                    (now_iso,),
                ) as cur:
                    rows = await cur.fetchall()
        except Exception:
            rows = []
        for ch_id, g_id in rows:
            try:
                guild = _bot.get_guild(int(g_id)) if g_id else None
                ch = guild.get_channel(int(ch_id)) if guild else None
                if ch is not None and isinstance(ch, discord.VoiceChannel):
                    await _apply_lock(ch, False, actor="auto-unlock")
                else:
                    await _record_lock(int(ch_id), int(g_id or 0), False)  # salon disparu → purge
                await asyncio.sleep(0.3)  # anti-429
            except Exception as ex:
                print(f"[voice_control unlock_expired room={ch_id}] {ex}")
    except Exception as ex:
        print(f"[voice_control unlock_expired_task] {ex}")


@unlock_expired_task.before_loop
async def _unlock_wait():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Outil STAFF : lister + geler/dégeler les vocaux temp actifs
# ═══════════════════════════════════════════════════════════════════════════

async def _active_temp_rooms(guild):
    """[(channel, owner_id), …] des vocaux temp encore existants de la guilde."""
    out = []
    if _get_db is None or guild is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT channel_id, owner_id FROM temp_voice_rooms WHERE guild_id=?",
                (int(guild.id),),
            ) as cur:
                rows = await cur.fetchall()
        for ch_id, owner_id in rows:
            ch = guild.get_channel(int(ch_id))
            if ch is not None and isinstance(ch, discord.VoiceChannel):
                out.append((ch, int(owner_id or 0)))
    except Exception as ex:
        print(f"[voice_control _active_temp_rooms] {ex}")
    return out[:STAFF_LIST_MAX]


def build_staff_voice_panel(guild):
    """Panneau STAFF (éphémère) : liste des vocaux temp actifs + geler/dégeler tout.
    Renvoie une coroutine-builder (à await) car il lit la DB. À câbler depuis un dashboard
    staff. NOMINATIF côté appelant (vérifier manage_channels avant d'afficher)."""
    LayoutView = _v2.get('LayoutView') or getattr(discord.ui, 'LayoutView', None)
    v2_container = _v2.get('v2_container')
    v2_body = _v2.get('v2_body')
    v2_title = _v2.get('v2_title')

    async def _build():
        rooms = await _active_temp_rooms(guild)
        if not rooms:
            body = "_Aucun vocal temporaire actif pour l'instant._"
        else:
            lines = []
            for ch, owner_id in rooms:
                n = len([m for m in getattr(ch, 'members', []) if not m.bot])
                locked = await _is_locked(ch.id)
                lines.append(f"• {ch.mention} — 👥 `{n}` · 👑 <@{owner_id}>"
                             + ("  · 🔒" if locked else ""))
            body = f"**{len(rooms)} vocal(aux) temp actif(s) :**\n" + "\n".join(lines)

        async def _freeze_all(i: discord.Interaction, lock: bool):
            try:
                if not bool(getattr(i.user.guild_permissions, 'manage_channels', False)):
                    if not i.response.is_done():
                        await i.response.send_message("❌ Réservé au staff.", ephemeral=True)
                    return
                if not i.response.is_done():
                    await i.response.defer(ephemeral=True)
                done = 0
                for ch, _own in await _active_temp_rooms(guild):
                    if await _apply_lock(ch, lock, actor=f"staff {i.user}"):
                        done += 1
                    await asyncio.sleep(0.3)  # anti-429
                await i.followup.send(
                    f"{'🧊 Gelé' if lock else '☀️ Dégelé'} {done} vocal(aux).", ephemeral=True)
            except Exception as ex:
                print(f"[voice_control staff freeze] {ex}")

        b_freeze = discord.ui.Button(label="Geler tout", style=discord.ButtonStyle.danger, emoji="🧊")
        b_unfreeze = discord.ui.Button(label="Dégeler tout", style=discord.ButtonStyle.success, emoji="☀️")
        b_freeze.callback = lambda i: _freeze_all(i, True)
        b_unfreeze.callback = lambda i: _freeze_all(i, False)
        row = discord.ui.ActionRow(b_freeze, b_unfreeze)
        if v2_container and v2_body and v2_title:
            class _StaffView(LayoutView):
                def __init__(self):
                    super().__init__(timeout=300)
                    self.add_item(v2_container(
                        v2_title("🎙️ Vocaux temporaires actifs"),
                        v2_body(body), row, color=0xE67E22))
            return _StaffView()

        class _StaffViewFb(LayoutView):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(discord.ui.TextDisplay("### 🎙️ Vocaux temporaires actifs\n" + body))
                self.add_item(row)
        return _StaffViewFb()

    return _build()


__all__ = [
    "setup", "init_db", "register_persistent", "post_control_panel",
    "unlock_expired_task", "build_staff_voice_panel", "VoiceControlButton",
    "LOCK_AUTO_RELEASE_HOURS",
]
