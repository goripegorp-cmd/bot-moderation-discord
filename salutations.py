"""salutations.py — un 👋 sous chaque « bonjour » (19/10/2026).

« Quand quelqu'un dit bonjour, on a un emoji qui apparaît en dessous de lui, avec une main. Dans les
salons où l'everyone peut écrire, sauf les salons d'annonces ou autres, où il ne peut pas écrire. »

Une salutation = le message COMMENCE par un mot de salut (« Bonjour tout le monde ! », « salut
@Kolax ») et reste court. Une fois par membre et par salon toutes les 10 minutes : pas d'avalanche
de réactions quand on se dit bonjour en boucle.
"""
from __future__ import annotations

import re
import time
import unicodedata

import discord

EMOJI = "👋"
MOTS = frozenset({"bonjour", "bonjours", "bonsoir", "bjr", "bsr", "salut", "salu", "slt", "coucou", "cc", "hello",
                  "helo", "hey", "hi", "yo", "hola", "wesh", "bonjoir", "re", "rebonjour", "resalut", "kikou"})
AMBIGUS = frozenset({"re", "cc", "yo", "hi"})  # seulement dans un message très court
LONGUEUR_MAX = 80
ATTENTE = 600
_derniers: dict = {}
_log = print


def setup(*, log=None):
    global _log
    _log = log or print


def _mots(texte: str) -> list:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"<[@#][!&]?\d+>|<a?:\w+:\d+>", " ", t)
    return re.findall(r"[a-z]+", t)


def est_salutation(texte: str) -> bool:
    """« Bonjour à tous », « slt », « Hello !! », « salut @x » — pas « je voulais dire salut »."""
    if not texte or len(texte) > LONGUEUR_MAX:
        return False
    mots = _mots(texte)
    if not mots:
        return False
    premier = re.sub(r"(.)\1{2,}", r"\1", mots[0])  # « saluuuut » → « salut », « coucouuu » → « coucou »
    if premier not in MOTS:
        premier = re.sub(r"(.)\1+", r"\1", mots[0])
    if premier in AMBIGUS and len(mots) > 4:
        return False
    return premier in MOTS


def salon_ouvert(salon, guild) -> bool:
    """Un salon où @everyone peut écrire (les fils suivent leur salon)."""
    parent = getattr(salon, "parent", None) if isinstance(salon, discord.Thread) else salon
    if parent is None or guild is None:
        return False
    p = parent.permissions_for(guild.default_role)
    return bool(p.view_channel and p.send_messages)


async def sur_message(msg) -> bool:
    try:
        g = msg.guild
        if g is None or msg.author.bot or msg.webhook_id or not est_salutation(msg.content):
            return False
        if not salon_ouvert(msg.channel, g):
            return False
        me = g.me
        if me is None or not msg.channel.permissions_for(me).add_reactions:
            return False
        cle, t = (g.id, msg.channel.id, msg.author.id), time.monotonic()
        if t - _derniers.get(cle, -1e9) < ATTENTE:
            return False
        _derniers[cle] = t
        if len(_derniers) > 5000:
            for k in [k for k, v in _derniers.items() if t - v > ATTENTE]:
                _derniers.pop(k, None)
        await msg.add_reaction(EMOJI)
        return True
    except discord.NotFound:
        return False  # message retiré entre-temps (modération) : rien à faire
    except discord.HTTPException as ex:
        _log("[SALUT] réaction impossible")
        _log(f"[SALUT:DETAIL] {type(ex).__name__} {ex}")
        return False
