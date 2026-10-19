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
