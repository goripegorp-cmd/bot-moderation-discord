"""notifs.py — rôles de notification pris et rendus d'un clic (19/10/2026).

Suggestions, et chaque salon de réseaux sociaux (les « sneaks » Rell Seas…) :
un rôle par sujet, créé à la première utilisation, que personne ne porte au départ. Le
bouton « Me prévenir » le donne ou le reprend ; les publications du sujet le mentionnent.
Les rôles sont non mentionnables : seul le bot (ou son webhook) peut les réveiller.
"""
from __future__ import annotations

import re

import discord
from discord.ui import Button

SUJETS = {
    "suggestions": ("🔔 Suggestions", 0xF59E0B, "les nouvelles suggestions"),
}
_cfg = _db_set = None
_log = print


def setup(*, cfg, db_set, log=None):
    global _cfg, _db_set, _log
    _cfg, _db_set = cfg, db_set
    _log = log or print


def cle_salon(salon_id: int) -> str:
    return f"salon{int(salon_id)}"


def nom_lisible(nom_salon: str) -> str:
    """« 🌊・rell-seas-news » → « Rell Seas News »."""
    mots = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", " ", nom_salon or "").split()
    return " ".join(m.capitalize() for m in mots)[:60] or "Annonces"


def _spec(guild, cle):
    if cle in SUJETS:
        return SUJETS[cle]
    if cle.startswith("salon"):
        salon = guild.get_channel(int(cle[5:])) if cle[5:].isdigit() else None
        nom = nom_lisible(getattr(salon, "name", ""))
        return (f"🔔 {nom}", 0x0EA5E9, f"les publications de {nom}")
    return None


async def role(guild, cle: str, creer: bool = True):
    """Le rôle du sujet, créé au besoin. None si impossible — jamais d'exception."""
    spec = _spec(guild, cle) if guild is not None else None
    if spec is None:
        return None
    try:
        c = await _cfg(guild.id)
        r = guild.get_role(int(c.get(f"notif_role_{cle}", 0) or 0))
        if r is not None or not creer:
            return r
        me = guild.me
        if not (me and me.guild_permissions.manage_roles):
            return None
        r = await guild.create_role(name=spec[0], colour=discord.Colour(spec[1]),
                                    mentionable=False, hoist=False,
                                    reason="Notifications : rôle pris d'un clic")
        await _db_set(guild.id, f"notif_role_{cle}", r.id)
        return r
    except discord.HTTPException as ex:
        _log(f"[NOTIFS] rôle {cle} : {ex}")
        return None


def mentions(r) -> discord.AllowedMentions:
    return discord.AllowedMentions(everyone=False, users=False, roles=[r] if r else False)


def ping(r) -> str:
    return f"<@&{r.id}>" if r is not None else ""


class BoutonNotif(discord.ui.DynamicItem[Button], template=r"notif:(?P<cle>[a-z0-9_]+)"):
    def __init__(self, cle: str, emoji=None):
        self.cle = cle
        super().__init__(Button(label="Me prévenir", emoji=emoji,
                                style=discord.ButtonStyle.secondary, custom_id=f"notif:{cle}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["cle"])

    async def callback(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        g, m = i.guild, i.user
        r = await role(g, self.cle)
        spec = _spec(g, self.cle) if g else None
        if r is None or spec is None:
            return await i.followup.send("Impossible pour le moment.", ephemeral=True)
        me = g.me
        if r >= me.top_role or r.managed:
            _log(f"[NOTIFS] rôle {r.name} au-dessus du bot")
            return await i.followup.send("Impossible pour le moment.", ephemeral=True)
        try:
            if r in getattr(m, "roles", []):
                await m.remove_roles(r, reason="Notifications : désabonnement")
                texte = f"Tu ne recevras plus {spec[2]}."
            else:
                await m.add_roles(r, reason="Notifications : abonnement")
                texte = f"Tu recevras {spec[2]}."
        except discord.HTTPException as ex:
            _log(f"[NOTIFS] bascule {self.cle} : {ex}")
            texte = "Impossible pour le moment."
        await i.followup.send(texte, ephemeral=True)
