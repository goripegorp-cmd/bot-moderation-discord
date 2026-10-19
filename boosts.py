"""boosts.py — le salon 🚀boosts (19/10/2026).

« Tu crées un salon à part qui s'appelle Boost, et à l'intérieur, tu mets toutes celles et ceux qui
ont boosté le serveur, pour les remercier. Si quelqu'un ne booste plus, son remerciement s'enlève. »
En haut, où en est le serveur ; dessous, une carte par booster, retirée dès qu'il arrête.
"""
from __future__ import annotations

import asyncio

import discord

import config_salons
import visuels
from ui_v2 import LayoutView

NOM_SALON = "🚀boosts"
ROSE = 0xF47FFF
PALIERS = ((2, 1), (7, 2), (14, 3))  # boosts nécessaires → niveau
_get_db = _cfg = _db_set = None
_log = print
_verrous: dict = {}


def setup(*, get_db, cfg, db_set, log=None):
    global _get_db, _cfg, _db_set, _log
    _get_db, _cfg, _db_set, _log = get_db, cfg, db_set, log or print


async def init_db():
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS boost_cartes (guild_id INTEGER, user_id INTEGER, "
                         "message_id INTEGER, avatar TEXT, PRIMARY KEY (guild_id, user_id))")
        await db.commit()


def _verrou(gid: int) -> asyncio.Lock:
    return _verrous.setdefault(gid, asyncio.Lock())


def _avatar(m) -> str:
    return str(m.display_avatar.url)


def boosters(g) -> list:
    return sorted((m for m in g.members if m.premium_since and not m.bot), key=lambda m: m.premium_since)


def _signature(g) -> str:
    return f"{g.premium_subscription_count or 0}|{g.premium_tier or 0}|{visuels.url('boost') or ''}"


def vue_entete(g) -> LayoutView:
    nb, niv = g.premium_subscription_count or 0, g.premium_tier or 0
    ligne = f"**{nb}** boost{'s' if nb > 1 else ''} · niveau **{niv}**"
    suivant = next(((seuil - nb, n) for seuil, n in PALIERS if n > niv), None)
    if suivant and suivant[0] > 0:
        ligne += f" · encore **{suivant[0]}** pour le niveau {suivant[1]}"
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau("boost", "Boosts"),
        discord.ui.TextDisplay(ligne + "\n-# Pour booster : clique sur le nom du serveur, puis « Booster le serveur »."),
        accent_color=ROSE))
    return v


def vue_carte(m) -> LayoutView:
    texte = f"### Merci {m.mention} 💜"
    if m.premium_since:
        texte += f"\n-# Booste le serveur depuis le <t:{int(m.premium_since.timestamp())}:D>"
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.Section(discord.ui.TextDisplay(texte), accessory=discord.ui.Thumbnail(_avatar(m))),
        accent_color=ROSE))
    return v


async def _lignes(gid: int) -> dict:
    async with _get_db() as db:
        async with db.execute("SELECT user_id, message_id, avatar FROM boost_cartes WHERE guild_id=?", (gid,)) as cur:
            return {r[0]: (r[1], r[2]) for r in await cur.fetchall()}


async def _noter(gid: int, uid: int, mid: int, avatar: str) -> None:
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO boost_cartes VALUES (?,?,?,?)", (gid, uid, mid, avatar))
        await db.commit()


async def _oublier(gid: int, uid: int) -> None:
    async with _get_db() as db:
        await db.execute("DELETE FROM boost_cartes WHERE guild_id=? AND user_id=?", (gid, uid))
        await db.commit()


async def salon_de(g):
    sid = int((await _cfg(g.id)).get("boosts_salon", 0) or 0)
    return g.get_channel(sid) if sid else None


def _categorie(g):
    """La catégorie Communauté : celle dont le nom le dit, sinon celle du chat."""
    cat = next((c for c in g.categories if "communaut" in config_salons.normaliser(c.name)), None)
    if cat is None:
        chat = next((ch for ch in g.text_channels if config_salons._mots(ch.name) == ["chat"]), None)
        cat = getattr(chat, "category", None)
    return cat


async def creer_salon(g, equipe: list):
    """Lecture seule pour tous ; le staff et au-dessus peuvent y écrire, le bot y publie."""
    ows = {g.default_role: discord.PermissionOverwrite(**config_salons.LECTURE)}
    for r in equipe:
        ows[r] = discord.PermissionOverwrite(**config_salons.EQUIPE_TEXTE)
    ows[g.me] = discord.PermissionOverwrite(**config_salons.BOT_TEXTE)
    return await g.create_text_channel(NOM_SALON, category=_categorie(g), overwrites=ows,
                                       topic="Merci à celles et ceux qui boostent le serveur 💜",
                                       reason="Boosts : remercier chaque booster")


async def installer(g, equipe: list) -> None:
    """Une fois : le salon (repris s'il existe déjà sous ce nom). Ensuite il est tenu à jour ; s'il
    est supprimé à la main, le bot ne le recrée pas."""
    try:
        if not (await _cfg(g.id)).get("boosts_installe"):
            if not (g.me and g.me.guild_permissions.manage_channels):
                return
            salon = await salon_de(g) or next(
                (ch for ch in g.text_channels if config_salons._mots(ch.name) in (["boost"], ["boosts"])), None)
            if salon is None:
                salon = await creer_salon(g, equipe)
            await _db_set(g.id, "boosts_salon", salon.id)
            await _db_set(g.id, "boosts_installe", 1)
        await synchroniser(g)
    except discord.HTTPException as ex:
        _log(f"[BOOSTS] installation : {type(ex).__name__} {ex}")


async def _effacer(m) -> None:
    try:
        await m.delete()
    except discord.NotFound:
        pass


async def _message(salon, presents: dict, mid: int):
    if mid in presents:
        return presents[mid]
    try:
        presents[mid] = await salon.fetch_message(mid)
        return presents[mid]
    except discord.NotFound:
        return None


async def synchroniser(g) -> dict:
    """Le salon dit la vérité : l'en-tête à jour, une carte par booster, aucune pour qui a arrêté.
    Sans la liste complète des membres, personne n'est retiré (on ne retire que ce qu'on sait)."""
    salon = await salon_de(g)
    bilan = {"ajoutees": 0, "retirees": 0}
    if salon is None:
        return bilan
    async with _verrou(g.id):
        moi = getattr(g.me, "id", 0)
        c = await _cfg(g.id)
        presents = {m.id: m async for m in salon.history(limit=200)}
        lignes = await _lignes(g.id)
        eid = int(c.get("boosts_entete", 0) or 0)
        entete = await _message(salon, presents, eid) if eid else None
        if entete is None:
            # Plus d'en-tête en haut : on repart de zéro, l'en-tête puis les cartes dans l'ordre des boosts.
            for m in list(presents.values()):
                if getattr(m.author, "id", 0) == moi:
                    await _effacer(m)
            for uid in lignes:
                await _oublier(g.id, uid)
            lignes, presents = {}, {}
            msg = await salon.send(view=vue_entete(g), allowed_mentions=discord.AllowedMentions.none())
            eid = msg.id
            await _db_set(g.id, "boosts_entete", eid)
            await _db_set(g.id, "boosts_entete_v", _signature(g))
        elif c.get("boosts_entete_v") != _signature(g):
            await entete.edit(view=vue_entete(g))
            await _db_set(g.id, "boosts_entete_v", _signature(g))
        actuels = {m.id: m for m in boosters(g)}
        for uid, (mid, _a) in list(lignes.items()):
            carte = await _message(salon, presents, mid)
            if uid not in actuels and g.chunked:
                if carte is not None:
                    await _effacer(carte)
                    presents.pop(mid, None)
                    bilan["retirees"] += 1
            elif carte is not None:
                continue
            await _oublier(g.id, uid)
            lignes.pop(uid)
        for m in actuels.values():
            if m.id in lignes:
                mid, avatar = lignes[m.id]
                if avatar != _avatar(m):
                    await presents[mid].edit(view=vue_carte(m))
                    await _noter(g.id, m.id, mid, _avatar(m))
                continue
            msg = await salon.send(view=vue_carte(m), allowed_mentions=discord.AllowedMentions.none())
            await _noter(g.id, m.id, msg.id, _avatar(m))
            lignes[m.id] = (msg.id, _avatar(m))
            bilan["ajoutees"] += 1
        gardes = {eid} | {mid for mid, _a in lignes.values()}
        for m in list(presents.values()):
            if getattr(m.author, "id", 0) == moi and m.id not in gardes:
                await _effacer(m)
    return bilan


async def ajouter(m, *, mentionner: bool = False) -> None:
    """Sa carte de remerciement ; mentionné une seule fois, le jour où il booste."""
    g = m.guild
    salon = await salon_de(g)
    if salon is None or m.bot or not m.premium_since:
        return
    async with _verrou(g.id):
        ligne = (await _lignes(g.id)).get(m.id)
        if ligne:
            try:
                await salon.get_partial_message(ligne[0]).edit(view=vue_carte(m))
                return
            except discord.NotFound:
                pass
        mentions = (discord.AllowedMentions(users=[m], roles=False, everyone=False) if mentionner
                    else discord.AllowedMentions.none())
        msg = await salon.send(view=vue_carte(m), allowed_mentions=mentions)
        await _noter(g.id, m.id, msg.id, _avatar(m))


async def retirer(g, uid: int) -> bool:
    """Il ne booste plus (ou il est parti) : sa carte s'enlève, sans un mot."""
    salon = await salon_de(g)
    async with _verrou(g.id):
        ligne = (await _lignes(g.id)).get(uid)
        if not ligne:
            return False
        if salon is not None:
            try:
                await salon.get_partial_message(ligne[0]).delete()
            except discord.NotFound:
                pass
        await _oublier(g.id, uid)
        return True


async def rafraichir_entete(g) -> None:
    try:
        salon = await salon_de(g)
        c = await _cfg(g.id)
        eid = int(c.get("boosts_entete", 0) or 0)
        if salon is None or not eid or c.get("boosts_entete_v") == _signature(g):
            return
        try:
            await salon.get_partial_message(eid).edit(view=vue_entete(g))
            await _db_set(g.id, "boosts_entete_v", _signature(g))
        except discord.NotFound:
            await synchroniser(g)
    except discord.HTTPException as ex:
        _log(f"[BOOSTS] en-tête : {type(ex).__name__} {ex}")


async def sur_maj_serveur(avant, apres) -> None:
    """Le nombre de boosts ou le niveau change : l'en-tête suit."""
    if (avant.premium_subscription_count, avant.premium_tier) != (apres.premium_subscription_count, apres.premium_tier):
        await rafraichir_entete(apres)
