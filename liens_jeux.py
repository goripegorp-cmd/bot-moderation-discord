"""liens_jeux.py — le salon 🎮game-link (24/10/2026).

Le fondateur : « rajoute un nouveau salon avec un emoji de manette qui s'appelle Game Link… quelqu'un qui dit
« Ils sont où les liens pour rejoindre le jeu ? » — le salon Game Link, il est là ».

Le salon est créé une fois, dans la catégorie Information (sinon en haut), en lecture seule. Sa carte montre
chaque jeu (`zones.JEUX` : un nouveau jeu y entre tout seul) avec un bouton « Jouer » quand son lien est réglé ;
sinon « le lien arrive bientôt » — jamais un bouton qui ment. Les liens se règlent dans 📋logs (« 🎮 Liens des
jeux », le fondateur et la direction), un champ par jeu ; la carte suit. Les réponses toutes faites (`faq.py`),
le panneau ❓ aide et le guide de chaque jeu s'en servent.
"""
from __future__ import annotations

import re

import discord
from discord.ui import Button

import config_salons
import visuels
from ui_v2 import LayoutView, Palette

NOM_SALON = "🎮game-link"
SUJET = ("🇫🇷 Les liens officiels pour rejoindre nos jeux.\n🇬🇧 The official links to join our games.")
COULEUR = 0x8B5CF6
VERSION = 1
URL = re.compile(r"^https://[^\s<>]+$", re.I)

_cfg = _db_set = _autorise = _journal = None
_jeux = ()
_log = print


def setup(*, cfg, db_set, autorise, journal, jeux, log=None):
    """`autorise(g, membre)` (async) → le fondateur ou la direction ; `journal(g, type_, texte, **kw)` (async) ;
    `jeux` : `zones.JEUX`."""
    global _cfg, _db_set, _autorise, _journal, _jeux, _log
    _cfg, _db_set, _autorise, _journal, _jeux = cfg, db_set, autorise, journal, tuple(jeux)
    _log = log or print


def liens(c: dict) -> dict:
    """{clé du jeu : son lien} — seulement les liens valides."""
    return {k: v for k, v in dict(c.get("jeux_liens") or {}).items() if isinstance(v, str) and URL.match(v)}


def categorie_info(g):
    """La catégorie Information (là où vivent les annonces et les nouveautés), si elle existe."""
    return next((cat for cat in getattr(g, "categories", []) or []
                 if "information" in config_salons.normaliser(cat.name).split()), None)


async def salon(g, *, creer: bool = False):
    """Le salon 🎮game-link, suivi par son identifiant (on peut le ranger ailleurs). `creer` : s'il n'existe
    pas, il est créé — dans Information, en lecture seule."""
    c = await _cfg(g.id)
    ch = g.get_channel(int(c.get("game_link_salon", 0) or 0))
    if isinstance(ch, discord.TextChannel) or not creer:
        return ch if isinstance(ch, discord.TextChannel) else None
    ows = {g.default_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                                                        send_messages=False, add_reactions=False,
                                                        create_public_threads=False, create_private_threads=False,
                                                        send_messages_in_threads=False),
           g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                             read_message_history=True, manage_messages=True)}
    cat = categorie_info(g)
    ch = await g.create_text_channel(NOM_SALON, category=cat, topic=SUJET, overwrites=ows,
                                     **({} if cat is not None else {"position": 0}),
                                     reason="Game Link : les liens pour rejoindre nos jeux")
    await _db_set(g.id, "game_link_salon", ch.id)
    await _db_set(g.id, "game_link_message", 0)
    return ch


def vue_carte(c: dict) -> tuple:
    """La carte du salon et sa signature (elle n'est réécrite que si un lien change)."""
    l = liens(c)
    items = [visuels.bandeau("game_link", "Game Link"),
             discord.ui.TextDisplay("🇫🇷 **Nos jeux, en un clic.** Les liens d'ici sont les seuls officiels.\n"
                                    "🇬🇧 **Our games, in one click.** The links here are the only official ones."),
             discord.ui.Separator()]
    for j in _jeux:
        if l.get(j.cle):
            items.append(discord.ui.Section(discord.ui.TextDisplay(f"### {j.emoji} {j.nom}"),
                                            accessory=Button(label="Jouer · Play", emoji="🎮", url=l[j.cle])))
        else:
            items.append(discord.ui.TextDisplay(f"### {j.emoji} {j.nom}\n-# Le lien arrive bientôt · Link coming soon"))
    items.append(discord.ui.TextDisplay("-# 🛡️ Ne clique jamais un lien de jeu reçu en privé · Never click a game "
                                        "link sent to you in DMs"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(COULEUR)))
    signature = "|".join([str(VERSION)] + [f"{j.cle}={l.get(j.cle, '')}" for j in _jeux])
    return v, signature


async def assurer_carte(g) -> bool:
    """La carte en place et à jour (reposée si elle a disparu). Rend True si elle a été posée ou réécrite."""
    ch = await salon(g)
    if ch is None:
        return False
    c = await _cfg(g.id)
    vue, signature = vue_carte(c)
    mid = int(c.get("game_link_message", 0) or 0)
    try:
        if mid:
            try:
                await ch.fetch_message(mid)
                if c.get("game_link_v") == signature:
                    return False
                await ch.get_partial_message(mid).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
                await _db_set(g.id, "game_link_v", signature)
                return True
            except discord.NotFound:
                pass
        msg = await ch.send(view=vue, allowed_mentions=discord.AllowedMentions.none())
        await _db_set(g.id, "game_link_message", msg.id)
        await _db_set(g.id, "game_link_v", signature)
        return True
    except discord.HTTPException as ex:
        _log("[GAMELINK][E1] carte non posée")
        _log(f"[GAMELINK][E1:DETAIL] {type(ex).__name__} {ex}")
        return False


class FormulaireLiens(discord.ui.Modal):
    """Un champ par jeu (cinq au plus) : le lien officiel ; vide = pas encore de lien."""

    def __init__(self, c: dict):
        super().__init__(title="🎮 Liens des jeux", timeout=900)
        actuels = dict(c.get("jeux_liens") or {})
        self.champs = {}
        for j in _jeux[:5]:
            t = discord.ui.TextInput(required=False, max_length=300, default=actuels.get(j.cle) or None,
                                     placeholder="https://www.roblox.com/games/…")
            self.champs[j.cle] = t
            self.add_item(discord.ui.Label(text=f"{j.nom}"[:45], component=t,
                                           description="Vide : « le lien arrive bientôt »"))

    async def on_submit(self, i: discord.Interaction):
        g = i.guild
        await i.response.defer(ephemeral=True, thinking=True)   # la base, la carte, le journal : > 3 s possible
        if g is None or not await _autorise(g, i.user):
            return await i.followup.send("Réservé au fondateur et à la direction.", ephemeral=True)
        #  24/10/2026 (revue) : une adresse mal saisie garde le lien d'avant (« Ignoré ») au lieu de l'effacer.
        actuels = dict((await _cfg(g.id)).get("jeux_liens") or {})
        nouveaux, refus = {}, []
        for cle, t in self.champs.items():
            v = str(t.value or "").strip()
            if not v:
                continue
            if URL.match(v):
                nouveaux[cle] = v
            else:
                refus.append(next((j.nom for j in _jeux if j.cle == cle), cle))
                if actuels.get(cle):
                    nouveaux[cle] = actuels[cle]
        await _db_set(g.id, "jeux_liens", nouveaux)
        await assurer_carte(g)
        noms = ", ".join(j.nom for j in _jeux if j.cle in nouveaux) or "aucun"
        await _journal(g, "gamelink.liens", f"{i.user.mention} a réglé les liens des jeux : {noms}.",
                       auteur_id=i.user.id)
        texte = f"✅ Liens enregistrés : {noms}. La carte de 🎮 game-link suit."
        if refus:
            texte += "\n⚠️ Ignoré, le lien d'avant reste (une adresse https:// est attendue) : " + ", ".join(refus)
        v = LayoutView(timeout=60)
        v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte),
                                        accent_color=Palette.WARNING if refus else Palette.SUCCESS))
        await i.followup.send(view=v, ephemeral=True)


class BoutonLiens(discord.ui.DynamicItem[Button], template=r"gl:liens"):
    """Dans le menu de 📋logs : « 🎮 Liens des jeux »."""

    def __init__(self):
        super().__init__(Button(label="Liens des jeux", emoji="🎮", style=discord.ButtonStyle.secondary,
                                custom_id="gl:liens"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        g = i.guild
        if g is None or not await _autorise(g, i.user):
            return await i.response.send_message("Réservé au fondateur et à la direction.", ephemeral=True)
        await i.response.send_modal(FormulaireLiens(await _cfg(g.id)))
