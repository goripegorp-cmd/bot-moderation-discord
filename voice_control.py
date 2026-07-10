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
    head = (f"### 🎛️ Personnalise ton salon vocal\n"
            f"Bienvenue <@{int(owner_id)}> — **c'est TON salon !** Configure-le à distance, d'ici, "
            f"en 1 clic :\n"
            f"🔤 **Renommer**  ·  👥 **Nombre de places**  ·  🔒 **Verrouiller**  ·  "
            f"👢 **Expulser**  ·  👑 **Transférer**"
            + ("\n🔒 **Salon verrouillé** — personne de nouveau ne peut entrer." if locked else "")
            + "\n-# Seul toi (ou le staff) peux utiliser ces boutons. Le salon se **supprime tout "
            f"seul** quand il se vide.")
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


async def _lock_text_chat(channel, owner_id: int):
    """owner 2026-06-30 : verrouille le CHAT TEXTE du vocal créé.
    - Le PROPRIÉTAIRE est le SEUL à VOIR le chat (le panneau), mais NE PEUT PAS écrire — il
      interagit UNIQUEMENT avec les boutons du bot (les clics marchent sans `send_messages`).
    - @everyone : aucune écriture ; et si on a pu donner l'accès lecture au proprio, le chat est
      MASQUÉ aux autres (lecture seule pour le proprio uniquement).
    On NE touche PAS `connect`/`speak`/`view_channel` de @everyone → le vocal reste JOIGNABLE pour
    parler. FAIL-SAFE (best-effort, perm manquante → on n'empêche rien). 2 appels API max (anti-429)."""
    try:
        guild = getattr(channel, 'guild', None)
        if guild is None:
            return
        me = getattr(guild, 'me', None)
        if not (me and channel.permissions_for(me).manage_permissions):
            return  # pas la perm → on laisse tel quel (fail-open)
        owner = guild.get_member(int(owner_id or 0)) if owner_id else None
        # ⚠️ MERGE obligatoire (owner 2026-07-10) : set_permissions(**kwargs) REMPLACE l'overwrite
        # entier → il EFFACERAIT le connect/speak posé à la création (les gens ne pourraient plus
        # PARLER). On part donc de l'overwrite EXISTANT (overwrites_for) et on ne modifie QUE les
        # champs de CHAT, en laissant connect/speak/view_channel intacts.
        # 1) Le proprio EN PREMIER (ne JAMAIS le verrouiller hors de son propre panneau) :
        #    voit le chat (read), mais n'écrit pas (boutons only).
        if owner is not None:
            try:
                ow = channel.overwrites_for(owner)
                ow.view_channel = True
                ow.read_message_history = True
                ow.send_messages = False
                ow.send_messages_in_threads = False
                ow.create_public_threads = False
                ow.create_private_threads = False
                await channel.set_permissions(
                    owner, overwrite=ow,
                    reason="Vocal créé : le proprio voit le panneau mais n'écrit pas")
            except Exception:
                pass
        # 2) @everyone : pas d'écriture (toujours) ; lecture du chat masquée SEULEMENT si le proprio
        #    a bien reçu l'accès lecture ci-dessus (sinon on ne masque pas → on ne verrouille personne).
        #    On NE TOUCHE PAS connect/speak/view_channel → le vocal reste JOIGNABLE et on PARLE.
        try:
            ow = channel.overwrites_for(guild.default_role)
            ow.send_messages = False
            ow.send_messages_in_threads = False
            ow.create_public_threads = False
            ow.create_private_threads = False
            if owner is not None:
                ow.read_message_history = False
            await channel.set_permissions(
                guild.default_role, overwrite=ow,
                reason="Vocal créé : chat texte verrouillé (privé au proprio, lecture seule)")
        except Exception:
            pass
    except Exception as ex:
        print(f"[voice_control _lock_text_chat] {ex}")


async def post_control_panel(channel, owner_id: int):
    """Poste le panneau de contrôle DANS le chat texte du vocal temp. Appelé à la
    création (depuis bot.py, après move_to). FAIL-SAFE : aucun crash si l'envoi échoue."""
    try:
        if channel is None:
            return
        # owner 2026-06-30 : verrouille le chat texte AVANT de poster (privé au proprio + lecture
        # seule + écriture interdite à tous ; le vocal reste joignable). Best-effort, fail-safe.
        await _lock_text_chat(channel, owner_id)
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
    """Réaffiche le panneau à jour APRÈS un defer() de mise à jour (component) : édite le
    message du panneau EN PLACE via edit_original_response. FAIL-SAFE (followup en repli)."""
    locked = await _is_locked(channel_id)
    view = _build_panel(channel_id, owner_id, locked)
    try:
        await interaction.edit_original_response(view=view)
    except Exception:
        try:
            await interaction.followup.send("✅ C'est fait.", ephemeral=True)
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
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)  # defer-first (ch.edit = API)
            ch = interaction.guild.get_channel(self.channel_id) if interaction.guild else None
            new = (self.name.value or "").strip()[:95]
            if ch is not None and new:
                try:
                    await ch.edit(name=new, reason=f"Renommage par {interaction.user}")
                except Exception:
                    pass
            try:
                await interaction.followup.send(f"✅ Vocal renommé en **{new}**.", ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[voice_control rename submit] {ex}")
            try:
                await interaction.followup.send("✅ Pris en compte.", ephemeral=True)
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
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)  # defer-first (ch.edit = API)
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
            try:
                await interaction.followup.send(
                    f"✅ Limite réglée sur **{'illimitée' if n == 0 else n}**.", ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[voice_control limit submit] {ex}")
            try:
                await interaction.followup.send("✅ Pris en compte.", ephemeral=True)
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
        # Defer-first : move_to / set_permissions sont des appels API → on défère AVANT.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        target_id = int(values[0]) if values else 0
        guild = interaction.guild
        ch = guild.get_channel(int(channel_id)) if guild else None
        target = guild.get_member(target_id) if guild else None
        if ch is None or target is None:
            await interaction.followup.send("❌ Membre/salon introuvable.", ephemeral=True)
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
            await interaction.followup.send(
                msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        else:  # xfer
            ok = await _set_owner(channel_id, target_id)
            if ok:
                # Bascule les overwrites élevés vers le nouveau proprio (best-effort).
                await _swap_owner_overwrites(ch, owner_id, target_id, interaction.user)
                await interaction.followup.send(
                    f"👑 Propriété transférée à {target.mention}.", ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none())
                # Met à jour le panneau in-room (nouveau proprio affiché).
                await _repost_or_log(ch, target_id)
            else:
                await interaction.followup.send(
                    "❌ Transfert impossible (vocal non temporaire ?).", ephemeral=True)
    except Exception as ex:
        print(f"[voice_control _on_member_select] {ex}")
        try:
            await interaction.followup.send("✅ Pris en compte.", ephemeral=True)
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
#  Menus de CHOIX (owner 2026-06-29) : places + noms rapides = « menu pro ultra-simple »
#  (remplace la saisie de nombre/texte par un vrai Select ; « ✏️ Personnalisé » garde le modal)
# ═══════════════════════════════════════════════════════════════════════════

# 0 = illimité. Choix volontairement courts et lisibles.
_LIMIT_CHOICES = [
    ("2 personnes", 2), ("3 personnes", 3), ("4 personnes", 4), ("5 personnes", 5),
    ("6 personnes", 6), ("8 personnes", 8), ("10 personnes", 10), ("12 personnes", 12),
    ("15 personnes", 15), ("20 personnes", 20), ("Illimité", 0),
]

# (label de choix, nom réellement appliqué au salon)
_NAME_PRESETS = [
    ("🎮 Gaming", "🎮 Gaming"), ("💬 Discussion", "💬 Discussion"),
    ("😎 Chill", "😎 Chill"), ("🎵 Musique", "🎵 Musique"),
    ("🏆 Compétition", "🏆 Compétition"), ("🎲 Soirée Jeux", "🎲 Soirée Jeux"),
    ("🗣️ Papote", "🗣️ Papote"), ("🔒 Privé", "🔒 Privé"),
]


def _wrap_select_view(body_txt: str, *rows, timeout: int = 180):
    """Petite vue éphémère V2 (titre + lignes de composants). Repli non-V2 si helpers absents."""
    LayoutView = _v2.get('LayoutView') or getattr(discord.ui, 'LayoutView', None)
    v2_container = _v2.get('v2_container')
    v2_body = _v2.get('v2_body')
    if v2_container and v2_body:
        class _V(LayoutView):
            def __init__(self):
                super().__init__(timeout=timeout)
                self.add_item(v2_container(v2_body(body_txt), *rows, color=0x5865F2))
        return _V()

    class _Vfb(LayoutView):
        def __init__(self):
            super().__init__(timeout=timeout)
            self.add_item(discord.ui.TextDisplay(body_txt))
            for r in rows:
                self.add_item(r)
    return _Vfb()


def _build_limit_select_view(channel_id: int, owner_id: int):
    """Vue éphémère : un Select pour choisir le nombre de places (au lieu de taper un nombre)."""
    options = [discord.SelectOption(label=lbl, value=str(n),
                                    emoji=("♾️" if n == 0 else "👥")) for lbl, n in _LIMIT_CHOICES]
    sel = discord.ui.Select(placeholder="👥 Combien de places dans ton salon ?",
                            min_values=1, max_values=1, options=options)

    async def _cb(i: discord.Interaction):
        await _on_limit_select(i, channel_id, owner_id, sel.values)

    sel.callback = _cb
    return _wrap_select_view(
        "### 👥 Nombre de places\nChoisis combien de personnes peuvent rejoindre ton salon :",
        discord.ui.ActionRow(sel))


def _build_rename_select_view(channel_id: int, owner_id: int):
    """Vue éphémère : Select de noms rapides + bouton « ✏️ Nom personnalisé » (modal)."""
    options = [discord.SelectOption(label=lbl[:100], value=str(idx))
               for idx, (lbl, _nm) in enumerate(_NAME_PRESETS)]
    sel = discord.ui.Select(placeholder="🔤 Choisis un nom rapide…",
                            min_values=1, max_values=1, options=options)

    async def _cb(i: discord.Interaction):
        await _on_rename_select(i, channel_id, owner_id, sel.values)

    sel.callback = _cb
    b_custom = discord.ui.Button(label="✏️ Nom personnalisé", style=discord.ButtonStyle.primary)

    async def _custom(i: discord.Interaction):
        try:
            if not i.response.is_done():
                await i.response.send_modal(_RenameModal(channel_id, owner_id))
        except Exception as ex:
            print(f"[voice_control rename custom] {ex}")

    b_custom.callback = _custom
    return _wrap_select_view(
        "### 🔤 Renommer ton salon\nChoisis un nom rapide, ou clique **✏️ Nom personnalisé** :",
        discord.ui.ActionRow(sel), discord.ui.ActionRow(b_custom))


async def _on_limit_select(interaction, channel_id, owner_id, values):
    """Applique la limite de places choisie. NOMINATIF (re-check). FAIL-SAFE."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)  # defer-first (ch.edit = API)
        ok, _own = await _can_manage(interaction, channel_id)
        if not ok:
            await interaction.followup.send(
                "ℹ️ Réservé au **propriétaire** (ou au staff).", ephemeral=True)
            return
        try:
            n = int(values[0]) if values else 0
        except Exception:
            n = 0
        n = max(0, min(99, n))
        ch = interaction.guild.get_channel(int(channel_id)) if interaction.guild else None
        if ch is not None:
            try:
                await ch.edit(user_limit=n, reason=f"Limite par {interaction.user}")
            except Exception:
                pass
        await interaction.followup.send(
            f"✅ Limite réglée sur **{'illimitée ♾️' if n == 0 else f'{n} places'}**.", ephemeral=True)
    except Exception as ex:
        print(f"[voice_control _on_limit_select] {ex}")
        try:
            await interaction.followup.send("✅ Pris en compte.", ephemeral=True)
        except Exception:
            pass


async def _on_rename_select(interaction, channel_id, owner_id, values):
    """Applique un nom rapide choisi. NOMINATIF (re-check). FAIL-SAFE."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)  # defer-first (ch.edit = API)
        ok, _own = await _can_manage(interaction, channel_id)
        if not ok:
            await interaction.followup.send(
                "ℹ️ Réservé au **propriétaire** (ou au staff).", ephemeral=True)
            return
        try:
            idx = int(values[0]) if values else -1
        except Exception:
            idx = -1
        name = _NAME_PRESETS[idx][1] if 0 <= idx < len(_NAME_PRESETS) else ""
        ch = interaction.guild.get_channel(int(channel_id)) if interaction.guild else None
        if ch is not None and name:
            try:
                await ch.edit(name=name[:95], reason=f"Renommage par {interaction.user}")
            except Exception:
                pass
        await interaction.followup.send(f"✅ Salon renommé en **{name}**.", ephemeral=True)
    except Exception as ex:
        print(f"[voice_control _on_rename_select] {ex}")
        try:
            await interaction.followup.send("✅ Pris en compte.", ephemeral=True)
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


# Anti-429 (owner 2026-06-18) : cooldown par salon sur le bouton verrou → un clic répété
# ne déclenche pas un set_permissions à chaque fois. Sous le cooldown, on rafraîchit juste
# le panneau (zéro appel API). Mémoire (horloge de la loop), fail-open. {channel_id: ts}.
_lock_toggle_cd: dict = {}
_LOCK_TOGGLE_CD = 4.0


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
            # Menu de CHOIX (noms rapides) + « ✏️ Personnalisé » → modal. Ephemère.
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    view=_build_rename_select_view(channel_id, owner_id), ephemeral=True)
        elif action == "limit":
            # Menu de CHOIX des places (au lieu de taper un nombre). Ephemère.
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    view=_build_limit_select_view(channel_id, owner_id), ephemeral=True)
        elif action == "lock":
            # Defer-first : _apply_lock fait un set_permissions (API) → on défère la mise à
            # jour du panneau AVANT, pour ne jamais dépasser la fenêtre 3 s (Échec d'interaction).
            if not interaction.response.is_done():
                await interaction.response.defer()  # DEFERRED_UPDATE_MESSAGE (component)
            # Anti-429 : sous le cooldown, on ne refait PAS le set_permissions (juste le panneau).
            try:
                _now = asyncio.get_running_loop().time()
            except Exception:
                _now = 0.0
            if _now and _now - _lock_toggle_cd.get(int(channel_id), 0) < _LOCK_TOGGLE_CD:
                await _refresh_panel(interaction, channel_id, owner_id)
                return
            if _now:
                _lock_toggle_cd[int(channel_id)] = _now
                if len(_lock_toggle_cd) > 2000:  # borne mémoire
                    for _k in [k for k, v in list(_lock_toggle_cd.items()) if _now - v > 60]:
                        _lock_toggle_cd.pop(_k, None)
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
        print("[voice_control] VoiceControlButton enregistré (boutons in-room persistants)")
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


async def _voice_stats_7d(guild_id: int) -> dict:
    """Stats vocales des 7 derniers jours (voice_activity_log) pour le récap staff (Lot 3).
    FAIL-OPEN → dict à zéros."""
    out = {"sessions": 0, "minutes": 0, "users": 0, "top": [], "peak_hours": []}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(duration_seconds),0)/60, COUNT(DISTINCT user_id) "
                "FROM voice_activity_log WHERE guild_id=? "
                "AND datetime(joined_at) > datetime('now','-7 days')",
                (int(guild_id),)) as cur:
                row = await cur.fetchone()
            if row:
                out["sessions"] = int(row[0] or 0)
                out["minutes"] = int(row[1] or 0)
                out["users"] = int(row[2] or 0)
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(duration_seconds),0)/60 AS m FROM voice_activity_log "
                "WHERE guild_id=? AND datetime(joined_at) > datetime('now','-7 days') "
                "GROUP BY user_id HAVING m > 0 ORDER BY m DESC LIMIT 10",
                (int(guild_id),)) as cur:
                out["top"] = [(int(r[0]), int(r[1] or 0)) for r in await cur.fetchall()]
            async with db.execute(
                "SELECT strftime('%H', joined_at) AS h, COUNT(*) AS c FROM voice_activity_log "
                "WHERE guild_id=? AND datetime(joined_at) > datetime('now','-7 days') "
                "GROUP BY h ORDER BY c DESC LIMIT 3",
                (int(guild_id),)) as cur:
                out["peak_hours"] = [(r[0], int(r[1])) for r in await cur.fetchall()
                                     if r and r[0] is not None]
    except Exception as ex:
        print(f"[voice_control _voice_stats_7d] {ex}")
    return out


def _fmt_hm(minutes: int) -> str:
    minutes = max(0, int(minutes or 0))
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def build_voice_stats_recap(guild):
    """Récap ÉPHÉMÈRE de l'activité vocale du serveur (7j) pour le STAFF : volume global,
    top vocal, heures de pointe. Lecture seule (voice_activity_log). Comble le seul manque
    réel du Lot 3 Logs (routage/filtres/exclusions/dashboard/export existent déjà). Renvoie
    une COROUTINE (à await). FAIL-SAFE."""
    h = _v2 or {}
    LayoutView = h.get('LayoutView') or getattr(discord.ui, 'LayoutView', None)
    v2_container = h.get('v2_container')
    v2_body = h.get('v2_body')
    v2_title = h.get('v2_title')

    async def _build():
        s = await _voice_stats_7d(guild.id)
        total = s["minutes"]
        top_lines = "\n".join(f"• <@{uid}> — **{_fmt_hm(m)}**" for uid, m in s["top"]) or "_aucune activité_"
        peak = " · ".join(f"`{hh}h` ({c})" for hh, c in s["peak_hours"]) or "—"
        body = (f"**7 derniers jours**\n"
                f"🎙️ Sessions : `{s['sessions']}`  ·  ⏱️ Total : `{total // 60}h{total % 60:02d}`  ·  "
                f"👥 Membres : `{s['users']}`\n"
                f"🔝 Heures de pointe : {peak}\n\n"
                f"### Top vocal (7j)\n{top_lines}")
        if v2_container and v2_body and v2_title:
            class _RecapView(LayoutView):
                def __init__(self):
                    super().__init__(timeout=300)
                    self.add_item(v2_container(
                        v2_title("📊 Activité vocale du serveur"),
                        v2_body(body), color=0x5865F2))
            return _RecapView()

        class _RecapViewFb(LayoutView):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(discord.ui.TextDisplay("### 📊 Activité vocale du serveur\n" + body))
        return _RecapViewFb()

    return _build()


def build_staff_voice_panel(guild):
    """Panneau STAFF (éphémère) : liste des vocaux temp actifs + geler/dégeler tout +
    récap d'activité vocale (Lot 3). Renvoie une coroutine-builder (à await) car il lit la
    DB. À câbler depuis un dashboard staff. NOMINATIF côté appelant (manage_channels)."""
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

        async def _show_stats(i: discord.Interaction):
            try:
                if not bool(getattr(i.user.guild_permissions, 'manage_channels', False)):
                    if not i.response.is_done():
                        await i.response.send_message("❌ Réservé au staff.", ephemeral=True)
                    return
                # defer-first : le récap fait plusieurs requêtes d'agrégat (potentiellement
                # lentes sur une grosse table) → on défère AVANT pour ne jamais timeouter.
                if not i.response.is_done():
                    await i.response.defer(ephemeral=True)
                recap = await build_voice_stats_recap(guild)
                await i.followup.send(view=recap, ephemeral=True)
            except Exception as ex:
                print(f"[voice_control staff stats] {ex}")
        b_stats = discord.ui.Button(label="Activité vocale (7j)",
                                    style=discord.ButtonStyle.primary, emoji="📊")
        b_stats.callback = _show_stats
        row = discord.ui.ActionRow(b_freeze, b_unfreeze, b_stats)
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
    "unlock_expired_task", "build_staff_voice_panel", "build_voice_stats_recap",
    "VoiceControlButton", "LOCK_AUTO_RELEASE_HOURS",
]
