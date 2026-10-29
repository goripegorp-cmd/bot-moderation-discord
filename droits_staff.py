"""droits_staff.py — qui écrit, qui modère, qui déplace, salon par salon (29/10/2026).

Le fondateur, mot pour mot ou presque :
  · « Annonce, Target Roblox, Ambrebois, Sneakfix, Giveaway, Gamerlink, Boost, Goripay, Sneak News, Roblox, Sneak
    Rellseas, Aide… tous les salons que le everyone peut voir [sans écrire] : il n'y a que le fondateur qui peut
    écrire dedans », ni écrire ni modérer pour le staff ;
  · les salons où @everyone voit ET écrit : le staff « peut supprimer les messages s'il faut modérer quelqu'un » ;
  · « le mute avec le clic droit, exclure temporairement » : sur le serveur, pour chaque rôle du staff ;
  · le clan GoRP : « les staffs ont la permission de modérer à l'intérieur, mais ne peuvent pas voir tant qu'ils
    n'ont pas le rôle » — le droit de modérer est posé, la vue vient seulement du rôle du clan ;
  · 29/10/2026, les FORUMS (clan GoRP, Rell Seas, Clover RPG…) : leurs posts verrouillés (guide, infos, annonces),
    « les staffs peuvent écrire dedans… je ne veux pas qu'ils puissent supprimer des messages dedans. Les seuls qui
    peuvent, fondateurs et direction ». Discord règle ces droits pour tout le forum, pas post par post : le staff
    écrit dans les posts ouverts, sans « Gérer les fils » (écrire dans un post verrouillé), sans « Gérer les
    messages », sans ouvrir de post ; la Direction a tout ça. Le staff garde « exclure temporairement » ;
  · 29/10/2026, les salons AUTOMATIQUES (le panneau des tickets) : « personne n'a à répondre à l'intérieur… juste
    cliquer sur les boutons » — personne n'y écrit, @everyone compris ; les fils des tickets restent ouverts ;
  · vocaux : le staff « peut bouger ou mute » dans les vocaux publics (et ceux créés à la demande) et dans la
    Taverne, « mais pas plus » (pas dans Live, Vidéo, 3 frères, GoRPC) ; la Direction déplace partout.

À chaque démarrage, `plan` décrit l'écart (rien n'est appliqué), `appliquer` le corrige. Seuls les rôles du staff et
au-dessus sont touchés — jamais un administrateur (il a tout), jamais un rôle du bot ni une intégration, jamais
@everyone ni le fondateur. Le bilan (des nombres) va dans /stats → `droits_staff`.
"""
from __future__ import annotations

import discord

import config_salons

VOCAUX = (discord.ChannelType.voice, discord.ChannelType.stage_voice)
VITRINES = config_salons.VITRINES          # live, video, 3 freres, gorpc, taverne
bilan: dict = {}


def _vitrine(salon) -> str:
    """« taverne », « autre » (live, vidéo, 3 frères, GoRPC) ou "" ."""
    n = config_salons.normaliser(salon.name)
    cat = config_salons.normaliser(getattr(getattr(salon, "category", None), "name", "") or "")
    if "taverne" in n or "taverne" in cat:
        return "taverne"
    return "autre" if " ".join(config_salons._mots(salon.name)) in VITRINES else ""


def _clan(salon) -> bool:
    cat = salon if salon.type == discord.ChannelType.category else getattr(salon, "category", None)
    return cat is not None and config_salons.est_clan(cat.name)


#  Ce qu'@everyone garde dans un salon automatique : rien à écrire, rien à ouvrir (les fils des tickets, eux, restent).
AUTOMATIQUE = dict(send_messages=False, add_reactions=False, create_public_threads=False, create_private_threads=False)


def voulu(salon, tous, direction: bool, automatiques=frozenset()) -> tuple:
    """(droits voulus pour un rôle du staff ou de la Direction, raison) — {} : on ne touche pas ce salon."""
    vocal = salon.type in VOCAUX
    if getattr(salon, "id", None) in automatiques:
        return dict(AUTOMATIQUE, manage_messages=False), "automatique : personne n'écrit, on clique"
    if salon.type == discord.ChannelType.forum:
        if direction:
            return (dict(send_messages=True, send_messages_in_threads=True, manage_threads=True, manage_messages=True),
                    "forum : la Direction écrit partout, posts verrouillés compris, et modère")
        d = dict(send_messages=False, create_public_threads=False, manage_threads=False, manage_messages=False)
        if _clan(salon):
            d["view_channel"] = None
        elif salon.permissions_for(tous).view_channel:
            d.update(view_channel=True, read_message_history=True)
        return d, "forum : le staff écrit dans les posts ouverts, ni posts verrouillés, ni suppression"
    if _clan(salon):
        if direction:
            return {}, ""
        if salon.type == discord.ChannelType.category:
            return {"view_channel": None}, "clan : invisible sans le rôle du clan"
        return (dict(view_channel=None, connect=None, move_members=True, mute_members=True, manage_messages=True) if vocal else
                dict(view_channel=None, manage_messages=True)), "clan : modère dès qu'il a le rôle, ne voit pas sans"
    if salon.type == discord.ChannelType.category:
        return {}, ""
    ev = salon.permissions_for(tous)
    if vocal:
        v = _vitrine(salon)
        if v == "taverne" or direction:
            return dict(move_members=True, mute_members=True, manage_messages=True), "vocal : déplace et rend muet"
        if v == "autre":
            return dict(move_members=False), "vitrine : le staff n'y déplace pas"
        if ev.view_channel and ev.connect:
            return dict(move_members=True, mute_members=True, manage_messages=True), "vocal public : déplace et rend muet"
        return {}, ""
    if not ev.view_channel:
        return {}, ""
    if ev.send_messages or ev.send_messages_in_threads:
        #  29/10/2026 : « du moment que l'everyone peut écrire quelque part, Staff GoRP doit pouvoir modérer, supprimer
        #  des messages et voir » — forums des studios (Rellseas, Clover RPG…) compris : supprimer un post = gérer les fils.
        d = dict(view_channel=True, read_message_history=True, manage_messages=True)
        if salon.type == discord.ChannelType.forum or ev.create_public_threads:
            d["manage_threads"] = True
        return d, "public : voit, supprime les messages"
    return (dict(send_messages=False, send_messages_in_threads=False, create_public_threads=False,
                 manage_messages=False), "lecture seule : le fondateur seul écrit")


def plan(g, staff: list, direction: list, salons=None, automatiques=frozenset()) -> list:
    """[(salon, rôle, overwrite neuf, raison)] : seulement là où le rôle n'a pas déjà ce qui est voulu."""
    a_moi = {r.id for r in getattr(g.me, "roles", []) or []}
    actions = []
    for salon in (g.channels if salons is None else salons):
        for r, dirn in [(r, False) for r in staff] + [(r, True) for r in direction]:
            if r is None or r.managed or r.is_default() or r.id in a_moi or r.permissions.administrator:
                continue
            droits, raison = voulu(salon, g.default_role, dirn, automatiques)
            if not droits:
                continue
            o = salon.overwrites_for(r)
            p = salon.permissions_for(r)
            neuf = discord.PermissionOverwrite(**dict(o))
            for k, v in droits.items():
                if v is None:
                    if getattr(o, k) is True:      # la vue donnée au rôle du staff : retirée (le rôle du clan la donne)
                        setattr(neuf, k, None)
                elif bool(getattr(p, k)) != v:
                    setattr(neuf, k, v)
            if neuf != o:
                actions.append((salon, r, neuf, raison))
    return actions


async def nouveau_salon(salon, staff: list, direction: list) -> int:
    """Un salon qui vient d'être créé (un studio, un forum, un vocal…) : réglé tout de suite, sans attendre un
    redémarrage. Rend le nombre de rôles réglés."""
    n = 0
    for s_, r, neuf, raison in plan(salon.guild, staff, direction, salons=[salon]):
        try:
            await s_.set_permissions(r, overwrite=neuf, reason=raison)
            n += 1
        except Exception:
            pass
    return n


async def appliquer(g, staff: list, direction: list, automatiques=frozenset()) -> dict:
    b = {"salons_corriges": 0, "echecs": 0, "exclure_temp_ajoute": 0, "exclure_temp_echec": 0, "automatiques": 0}
    for sid in automatiques:
        salon = g.get_channel(sid)
        if salon is None:
            continue
        o = salon.overwrites_for(g.default_role)
        neuf = discord.PermissionOverwrite(**dict(o))
        for k, v in AUTOMATIQUE.items():
            setattr(neuf, k, v)
        if neuf != o:
            try:
                await salon.set_permissions(g.default_role, overwrite=neuf, reason="Salon automatique : on clique, on n'écrit pas")
                b["automatiques"] += 1
            except Exception:
                b["echecs"] += 1
    me = g.me
    for r in list(staff) + list(direction):
        if r is None or r.managed or r.permissions.administrator or r.permissions.moderate_members:
            continue
        try:
            if not (me.guild_permissions.moderate_members and r < me.top_role):
                raise PermissionError
            perms = discord.Permissions(r.permissions.value)
            perms.moderate_members = True
            await r.edit(permissions=perms, reason="Le staff peut exclure temporairement (mute)")
            b["exclure_temp_ajoute"] += 1
        except Exception:
            b["exclure_temp_echec"] += 1
    for salon, r, neuf, raison in plan(g, staff, direction, automatiques=frozenset(automatiques)):
        try:
            await salon.set_permissions(r, overwrite=neuf, reason=raison)
            b["salons_corriges"] += 1
        except Exception:
            b["echecs"] += 1
    bilan.update(b)
    return b
