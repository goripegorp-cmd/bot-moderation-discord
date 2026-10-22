"""Tickets en fils privés (19/10/2026) : un salon par équipe staff, un fil privé par ticket.

Un fil privé n'est vu que de ses membres et de qui a « Gérer les fils » ; il ne compte pas
dans la limite des 500 salons (doc Discord, topics/threads). Si le bot n'a pas les droits,
create_ticket retombe sur le salon classique.
"""
from __future__ import annotations

import re

import discord

ARCHIVE_MIN = 10080
DROITS_BOT = ("view_channel", "manage_channels", "manage_threads", "create_private_threads",
              "create_public_threads", "send_messages", "send_messages_in_threads",
              "read_message_history", "attach_files", "embed_links", "add_reactions")
CLE_PARENTS = "tickets_fils_parents"
#  Ce que reçoit chaque équipe qui doit voir les tickets d'un salon porteur : « Gérer les fils » est
#  ce qui montre un fil privé à qui n'y a pas été ajouté (doc Discord, topics/threads).
DROITS_EQUIPE = dict(view_channel=True, read_message_history=True, send_messages_in_threads=True,
                     manage_threads=True, attach_files=True, embed_links=True, add_reactions=True)
#  Dans un ticket en salon classique (le repli), la même équipe parle comme le staff.
DROITS_SALON = dict(view_channel=True, send_messages=True, read_message_history=True, attach_files=True,
                    embed_links=True, add_reactions=True, use_external_emojis=True, use_external_stickers=True)


def possible(guild) -> bool:
    p = guild.me.guild_permissions
    return all(getattr(p, d, False) for d in DROITS_BOT)


def nom_parent(staff) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(getattr(staff, "name", "") or "").casefold()).strip("-")
    return f"🎫・tickets-{base}"[:90] if base else "🎫・tickets"


def permissions_parent(guild, staff, voient=()) -> dict:
    """Lecture seule pour tous ; on parle dans SON fil (preuves comprises) ; le staff — et `voient` :
    la direction, le fondateur, l'équipe du type — voit tous les fils (« Gérer les fils »)."""
    ow = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False,
            send_messages_in_threads=True, create_public_threads=False,
            create_private_threads=False, attach_files=True, embed_links=True,
            add_reactions=True),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, send_messages_in_threads=True,
            create_private_threads=True, manage_threads=True, read_message_history=True,
            attach_files=True, embed_links=True),
    }
    for cible in (staff, *voient):
        if cible is not None:
            ow[cible] = discord.PermissionOverwrite(**DROITS_EQUIPE)
    return ow


async def completer(ch, cibles, droits=None) -> int:
    """Ajoute à `ch` ce qui manque pour que chaque cible voie ses tickets ; ne retire jamais rien (un
    réglage posé à la main reste). Rend le nombre de cibles complétées."""
    droits = droits or DROITS_EQUIPE
    n = 0
    for cible in dict.fromkeys(c for c in cibles if c is not None):
        actuel = ch.overwrites_for(cible)
        if all(getattr(actuel, k) is v for k, v in droits.items()):
            continue
        for k, v in droits.items():
            setattr(actuel, k, v)
        await ch.set_permissions(cible, overwrite=actuel, reason="Tickets : la direction et l'équipe du type voient tout")
        n += 1
    return n


def _parent_valide(ch, me) -> bool:
    if not isinstance(ch, discord.TextChannel):
        return False
    p = ch.permissions_for(me)
    return p.view_channel and p.create_private_threads and p.manage_threads and p.send_messages_in_threads


async def parent(guild, cat, staff, parents: dict, enregistrer, *, voient=(), groupe: str = "", nom: str = ""):
    """Le salon qui porte les fils de cette équipe — créé au premier ticket. None si
    impossible. `enregistrer(parents)` garde le lien catégorie:staff[:groupe] → salon.
    `voient` (direction, fondateur, équipe du type) y voit tous les fils, complété s'il manque ;
    un `groupe` (« rell ») a son propre salon : ses rôles ne voient pas les tickets des autres."""
    if not possible(guild):
        return None
    cle = f"{getattr(cat, 'id', 0)}:{getattr(staff, 'id', 0)}" + (f":{groupe}" if groupe else "")
    ch = guild.get_channel(int((parents or {}).get(cle, 0) or 0))
    if _parent_valide(ch, guild.me):
        try:
            await completer(ch, (staff, *voient))
        except discord.HTTPException as ex:
            print(f"[tickets_fils] droits du salon {ch.id} non complétés : {ex}")
        return ch
    ch = await guild.create_text_channel(nom or nom_parent(staff), category=cat,
                                         overwrites=permissions_parent(guild, staff, voient),
                                         reason="Tickets en fils privés")
    await enregistrer({**(parents or {}), cle: ch.id})
    try:
        await ch.send("🎫 Les tickets s'ouvrent ici, en **fil privé** : seuls toi et le staff "
                      "le voient. Ouvre-le depuis la notification ou la liste des fils.")
    except discord.HTTPException as ex:
        print(f"[tickets_fils] message d'accueil non posé : {ex}")
    return ch


async def ouvrir(parent_ch, membre, nom: str):
    fil = await parent_ch.create_thread(
        name=nom[:100], type=discord.ChannelType.private_thread, invitable=False,
        auto_archive_duration=ARCHIVE_MIN, reason=f"Ticket de {membre}")
    try:
        await fil.add_user(membre)
    except discord.HTTPException:
        try:
            await fil.delete()
        except discord.HTTPException as ex:
            print(f"[tickets_fils] fil orphelin {fil.id} : {ex}")
        raise
    return fil


async def salon(guild, chid):
    """Le salon ou le fil d'un ticket — un fil archivé n'est pas en cache : on le demande."""
    ch = guild.get_channel_or_thread(int(chid or 0))
    if ch is not None:
        return ch
    try:
        return await guild.fetch_channel(int(chid))
    except discord.NotFound:
        return None


async def existe(guild, chid) -> bool:
    """Ne déclare jamais disparu un ticket sur une simple panne réseau."""
    try:
        return await salon(guild, chid) is not None
    except discord.HTTPException:
        return True


async def ajouter(ch, membre):
    if isinstance(ch, discord.Thread):
        return await ch.add_user(membre)
    return await ch.set_permissions(
        membre, view_channel=True, send_messages=True, read_message_history=True,
        attach_files=True, embed_links=True, add_reactions=True,
        use_external_emojis=True, use_external_stickers=True)
