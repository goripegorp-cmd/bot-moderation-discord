"""config_salons.py — la configuration des salons voulue par le propriétaire (19/10/2026).

« @everyone voit tous les salons, sauf ceux où il y a déjà des rôles spécifiques. Dans
communautaire, ils peuvent tout voir, rejoindre, parler — sauf s'ils sont sanctionnés. Seul
celui qui fait des bêtises de partout ne voit plus rien. »

Jamais touchés : un salon réservé à des rôles (@everyone refusé, un rôle autorisé), un salon
que le bot utilise pour une fonction (logs, staff, salon piège…), un nom de staff ou de logs.
Sanctions : l'exclusion temporaire de Discord coupe déjà la parole ; le rôle « 🚫 Radié »
reçoit le refus total partout. Chaque modification est mémorisée et s'annule d'un clic.
"""
from __future__ import annotations

import asyncio
import json
import unicodedata

import discord

MOTS_PRIVES = ("log", "staff", "modo", "moder", "admin", "direction", "fondateur", "sanction",
               "ticket", "transcript", "audit", "rapport", "alerte", "securite", "prive", "equipe")
MOTS_LECTURE = ("regle", "rule", "annonce", "announce", "news", "actu", "sneak", "info",
                "bienvenue", "welcome", "sondage", "suggestion", "boost", "partenaire", "role")
PAROLE_TEXTE = ("view_channel", "read_message_history", "send_messages", "send_messages_in_threads",
                "add_reactions", "attach_files", "embed_links", "use_application_commands")
PAROLE_VOCAL = ("view_channel", "connect", "speak", "stream", "use_voice_activation", "send_messages")
TEXTE = (discord.ChannelType.text, discord.ChannelType.forum)
VOCAL = (discord.ChannelType.voice, discord.ChannelType.stage_voice)
_log = print


def setup(*, log=None):
    global _log
    _log = log or print


def normaliser(nom: str) -> str:
    t = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().lower()
    return "".join(c if c.isalnum() else " " for c in t)


def contient(nom: str, mots) -> bool:
    n = normaliser(nom)
    return any(m in n for m in mots)


def reserve_a_des_roles(salon, tous, exclus: set) -> bool:
    """@everyone refusé et au moins un rôle (ou membre) autorisé à voir."""
    ows = getattr(salon, "overwrites", {}) or {}
    ev = ows.get(tous)
    if ev is None or ev.view_channel is not False:
        return False
    return any(cible != tous and getattr(cible, "id", 0) not in exclus and o.view_channel is True
               for cible, o in ows.items())


def prive(salon, tous, ids_prives: set, exclus: set) -> bool:
    if salon is None:
        return False
    if salon.id in ids_prives or contient(salon.name, MOTS_PRIVES) or reserve_a_des_roles(salon, tous, exclus):
        return True
    cat = getattr(salon, "category", None)
    return cat is not None and prive(cat, tous, ids_prives, exclus)


def communautaire(salon) -> bool:
    cat = salon if getattr(salon, "type", None) == discord.ChannelType.category else getattr(salon, "category", None)
    return cat is not None and "communaut" in normaliser(cat.name)


def lecture_seule(salon, ids_lecture: set) -> bool:
    return (salon.id in ids_lecture or getattr(salon, "type", None) == discord.ChannelType.news
            or contient(salon.name, MOTS_LECTURE))


def plan(guild, ids_prives: set, ids_lecture: set, radie=None) -> list:
    """[(salon, cible, nouvel overwrite, raison)] — rien n'est appliqué ici."""
    tous = guild.default_role
    exclus = {getattr(guild.me, "id", 0), getattr(radie, "id", 0)}
    exclus |= {r.id for r in getattr(guild.me, "roles", []) or []}
    actions = []
    for salon in guild.channels:
        if radie is not None:
            o = salon.overwrites_for(radie)
            if o.view_channel is not False:
                actions.append((salon, radie, _radie(o), "radié : ne voit plus rien"))
        if prive(salon, tous, ids_prives, exclus):
            continue
        o = salon.overwrites_for(tous)
        neuf = discord.PermissionOverwrite(**dict(o))
        raisons = []
        if o.view_channel is False:
            neuf.view_channel = None
            raisons.append("visible")
        if communautaire(salon):
            if salon.type == discord.ChannelType.category:
                perms = set(PAROLE_TEXTE) | set(PAROLE_VOCAL)
            elif salon.type in VOCAL:
                perms = set(PAROLE_VOCAL)
            elif salon.type in TEXTE and not lecture_seule(salon, ids_lecture):
                perms = set(PAROLE_TEXTE)
            else:
                perms = {"view_channel", "read_message_history"}
            for p in sorted(perms):
                if getattr(neuf, p) is False:
                    setattr(neuf, p, None)
                    raisons.append(p)
        if raisons and neuf != o:
            actions.append((salon, tous, neuf, ", ".join(dict.fromkeys(raisons))))
    return actions


# ─── Configuration v2 (19/10/2026, récapitulatif du fondateur) ─────────────
#  « Information (annonce, target-roblox, ambrebois, sneak-fix, ticket) et Sneak Peek (goripe,
#  sneak-news-roblox, sneak-rellseas) : voir et lire l'historique, ni écrire ni réagir. Le chat :
#  écrire, images, liens. Suggestions : seulement le bouton. Join : chacun crée son vocal, le staff
#  et au-dessus peuvent déplacer. Live, Vidéo, 3 frères, GoRPC, Taverne : visibles, on n'y entre pas.
#  GoRp_SEA : le clan et le staff seulement — info en lecture, chat ouvert, Join du clan. »
LECTURE = {"view_channel": True, "read_message_history": True, "send_messages": False, "add_reactions": False,
           "create_public_threads": False, "create_private_threads": False, "send_messages_in_threads": False,
           "send_polls": False}
PAROLE = {"view_channel": True, "read_message_history": True, "send_messages": True, "attach_files": True,
          "embed_links": True}
VOCAL_OUVERT = {"view_channel": True, "connect": True, "speak": True}
VITRINE = {"view_channel": True, "connect": False}
EQUIPE_TEXTE = {"view_channel": True, "read_message_history": True, "send_messages": True, "embed_links": True,
                "attach_files": True, "add_reactions": True}
BOT_TEXTE = {"view_channel": True, "read_message_history": True, "send_messages": True, "embed_links": True,
             "attach_files": True}
VITRINES = ("live", "video", "3 freres", "gorpc", "taverne")


def _mots(nom: str) -> list:
    return normaliser(nom).split()


def est_clan(nom_categorie: str) -> bool:
    n = normaliser(nom_categorie)
    return "gorp" in n and "sea" in n


def plan_v2(guild, clan_role, equipe: list, hubs: set, deplacer: bool, ids_prives: set = frozenset()) -> list:
    """[(salon, cible, nouvel overwrite, raison)] — seuls les droits nommés changent, le reste reste.
    `equipe` : les rôles du staff et au-dessus ; `hubs` : les salons « Join » ; `deplacer` : le bot
    peut accorder « Déplacer des membres » ; `ids_prives` : salons du bot jamais touchés (logs,
    sondages…), comme tout salon réservé à des rôles hors du clan."""
    tous, me = guild.default_role, guild.me
    exclus = {getattr(me, "id", 0)} | {r.id for r in getattr(me, "roles", []) or []}
    bot_admin = bool(getattr(getattr(me, "guild_permissions", None), "administrator", False))
    actions = []

    def regler(salon, cible, droits, raison):
        if cible is None:
            return
        o = salon.overwrites_for(cible)
        neuf = discord.PermissionOverwrite(**dict(o))
        for k, v in droits.items():
            setattr(neuf, k, v)
        if neuf != o:
            actions.append((salon, cible, neuf, raison))

    def equipe_vocal(salon, raison):
        for r in equipe:
            regler(salon, r, dict(VOCAL_OUVERT, **({"move_members": True} if deplacer else {})), raison)

    for salon in guild.channels:
        type_ = getattr(salon, "type", None)
        cat = salon if type_ == discord.ChannelType.category else getattr(salon, "category", None)
        mots, nc = _mots(salon.name), normaliser(cat.name) if cat is not None else ""
        if cat is not None and est_clan(cat.name):
            if clan_role is None:
                continue
            regler(salon, tous, {"view_channel": False}, "clan : invisible pour les autres")
            if type_ == discord.ChannelType.category:
                droits, raison = {"view_channel": True, "read_message_history": True, "connect": True}, "clan : voit tout"
            elif type_ in VOCAL:
                droits, raison = VOCAL_OUVERT, "clan : rejoint et parle"
            elif "info" in " ".join(mots):
                droits, raison = LECTURE, "clan : lecture seule"
            elif "chat" in " ".join(mots):
                droits, raison = PAROLE, "clan : messages, images, liens"
            else:
                droits, raison = {"view_channel": True, "read_message_history": True}, "clan : voit"
            regler(salon, clan_role, droits, raison)
            for r in equipe:
                regler(salon, r, EQUIPE_TEXTE if type_ in TEXTE else dict(VOCAL_OUVERT, **(
                    {"move_members": True} if deplacer and type_ in VOCAL else {})), "staff et au-dessus")
            if not bot_admin:
                regler(salon, me, dict(BOT_TEXTE, **({"connect": True, **({"move_members": True} if deplacer else {})}
                                                    if type_ != discord.ChannelType.text else {})),
                       "le bot y voit et y agit")
            continue
        if type_ == discord.ChannelType.category or salon.id in ids_prives:
            continue
        if salon.id not in hubs and prive(salon, tous, ids_prives, exclus):
            continue
        if type_ in VOCAL:
            if salon.id in hubs:
                regler(salon, tous, VOCAL_OUVERT, "Join : chacun crée son vocal")
                equipe_vocal(salon, "staff et au-dessus : déplacent")
            elif "taverne" in nc or " ".join(mots) in VITRINES:
                regler(salon, tous, VITRINE, "visible, on n'y entre pas")
            continue
        if type_ not in TEXTE and type_ != discord.ChannelType.news:
            continue
        if cat is not None and ("information" in nc or "sneak" in nc):
            raison = "lecture seule"
        elif any("suggestion" in m for m in mots):
            raison = "le bouton seulement"
        elif "aide" in mots:
            raison = "lecture seule (panneau d'aide)"
        elif any(m.startswith("boost") for m in mots):
            raison = "lecture seule (merci aux boosters)"
        elif "chat" in mots:
            regler(salon, tous, PAROLE, "messages, images, liens")
            continue
        else:
            continue
        regler(salon, tous, LECTURE, raison)
        for r in equipe:
            regler(salon, r, EQUIPE_TEXTE, "staff et au-dessus : écrivent")
        if not bot_admin:
            regler(salon, me, BOT_TEXTE, "le bot y publie")
    return actions


def _radie(o):
    neuf = discord.PermissionOverwrite(**dict(o))
    for p in ("view_channel", "read_message_history", "send_messages", "add_reactions",
              "send_messages_in_threads", "connect", "speak", "use_application_commands"):
        setattr(neuf, p, False)
    return neuf


def instantane(actions) -> str:
    """L'état d'avant, pour annuler : {salon: {cible: [allow, deny] ou None}}."""
    avant = {}
    for salon, cible, _, _ in actions:
        o = salon.overwrites.get(cible)
        avant.setdefault(str(salon.id), {})[str(cible.id)] = (
            None if o is None else [o.pair()[0].value, o.pair()[1].value])
    return json.dumps(avant)


async def appliquer(actions) -> int:
    faits = 0
    for salon, cible, neuf, raison in actions:
        try:
            await salon.set_permissions(cible, overwrite=None if neuf.is_empty() else neuf,
                                        reason=f"Configuration des salons : {raison}")
            faits += 1
            await asyncio.sleep(0.4)
        except discord.HTTPException as ex:
            _log(f"[SALONS] {salon.id} : {ex}")
    return faits


async def restaurer(guild, avant_json: str) -> int:
    faits = 0
    for sid, cibles in json.loads(avant_json or "{}").items():
        salon = guild.get_channel(int(sid))
        if salon is None:
            continue
        for cid, paire in cibles.items():
            cible = guild.get_role(int(cid)) or guild.get_member(int(cid))
            if cible is None:
                continue
            o = None if paire is None else discord.PermissionOverwrite.from_pair(
                discord.Permissions(paire[0]), discord.Permissions(paire[1]))
            try:
                await salon.set_permissions(cible, overwrite=o, reason="Configuration des salons : annulée")
                faits += 1
                await asyncio.sleep(0.4)
            except discord.HTTPException as ex:
                _log(f"[SALONS] annulation {sid} : {ex}")
    return faits


def resume(actions) -> str:
    lignes = [f"<#{s.id}> · {r}" for s, c, _, r in actions if not getattr(c, "name", "").startswith("🚫")]
    radie = sum(1 for _, c, _, _ in actions if getattr(c, "name", "").startswith("🚫"))
    texte = "\n".join(lignes[:30]) + (f"\n… et {len(lignes) - 30} autre(s)" if len(lignes) > 30 else "")
    if radie:
        texte += f"\n-# Radié : refus posé sur {radie} salon(s)"
    return texte or "Rien à changer."
