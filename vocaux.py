"""vocaux.py — Les vocaux à la demande (24/10/2026, le fondateur).

« Plusieurs sous-salons automatiques… un vocal communautaire… un vocal concernant les deux jeux… décider si
c'est pour de l'aide, du chill, du farm… comme ça, ils pourront se rejoindre » ; et pour le clan : « un vocal
join pour le clan et après un vocal de demande… aide, farm et tout… pour bien cibler les demandes ».

Chaque « Join » (un hub des vocaux temporaires) a un CONTEXTE : la communauté, un jeu (`zones.JEUX`, les
futurs jeux compris), le clan, ou les demandes du clan. Le vocal créé porte un panneau : son propriétaire y
choisit le but, et le nom du salon le montre à tous (« 🌊 Farm · Kolax »), pour que ceux qui ont le même
besoin le rejoignent. Discord n'autorise que deux changements de nom par salon toutes les dix minutes : au-
delà, le panneau le dit au lieu de rester bloqué.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import discord

from ui_v2 import LayoutView, Palette

RENOMMAGES_MAX = 2          # par salon…
RENOMMAGES_FENETRE = 600.0  # …toutes les 10 minutes (la limite de Discord)


@dataclass(frozen=True)
class But:
    cle: str
    nom: str
    emoji: str


BUTS = {b.cle: b for b in (
    But("aide", "Aide", "🛟"), But("farm", "Farm", "🌾"), But("boss", "Boss", "⚔️"), But("raid", "Raid", "🏴‍☠️"),
    But("trade", "Trade", "🤝"), But("chill", "Chill", "🌴"), But("discussion", "Discussion", "💬"),
    But("jeux", "Jeux", "🎮"), But("musique", "Musique", "🎵"))}


@dataclass(frozen=True)
class Contexte:
    cle: str
    titre: str           # « Communauté », « Rell Seas », « Clan GoRP »…
    emoji: str           # devant le nom du salon (vide : l'emoji du but)
    hub: str             # le nom du salon « Join »
    buts: tuple
    defaut: str          # le nom d'un vocal neuf, avant le choix ({user} : son créateur)
    demande: bool = False


def _contextes() -> dict:
    import zones  # les jeux du serveur : un nouveau jeu dans zones.JEUX a son Join et ses buts
    out = {"commu": Contexte("commu", "Communauté", "", "🔊 Join · Communauté",
                             ("discussion", "chill", "jeux", "aide", "musique"), "🔊 {user}")}
    for j in zones.JEUX:
        out[j.cle] = Contexte(j.cle, j.nom, j.emoji, f"{j.emoji} Join · {j.nom}",
                              ("aide", "farm", "boss", "trade", "chill", "discussion"), f"{j.emoji} {j.nom} · {{user}}")
    out["clan"] = Contexte("clan", "Clan GoRP", "🦜", "🔊 Join · Clan",
                           ("discussion", "chill", "aide", "farm", "boss", "raid"), "🦜 Clan · {user}")
    out["clan_demande"] = Contexte("clan_demande", "Demandes du clan", "🙋", "🙋 Demande · Clan",
                                   ("aide", "farm", "boss", "raid", "trade"), "🙋 Demande · {user}", demande=True)
    return out


CONTEXTES = _contextes()

_proprio = _est_staff = None
_log = print
_renommages: dict = {}      # salon → [heures des derniers changements de nom]


def setup(*, proprio, est_staff, log=None):
    """`proprio(salon)` (async) → (id du propriétaire, contexte) d'un vocal créé par un Join, ou None ;
    `est_staff(g, membre)` (async)."""
    global _proprio, _est_staff, _log
    _proprio, _est_staff, _log = proprio, est_staff, log or print


def contexte(cle: str) -> Contexte:
    return CONTEXTES.get(cle) or CONTEXTES["commu"]


def nom_salon(ctx: Contexte, but: But | None, pseudo: str) -> str:
    """« 🌊 Farm · Kolax » (un jeu, le clan), « 🌴 Chill · Kolax » (la communauté) ; sans but : le nom
    d'un vocal neuf."""
    if but is None:
        return ctx.defaut.replace("{user}", pseudo)[:100]
    return f"{ctx.emoji or but.emoji} {but.nom} · {pseudo}"[:100]


def attente(salon_id: int, maintenant: float | None = None) -> int:
    """Secondes à attendre avant un nouveau nom (0 : tout de suite)."""
    t = time.monotonic() if maintenant is None else maintenant
    faits = [x for x in _renommages.get(int(salon_id), []) if t - x < RENOMMAGES_FENETRE]
    _renommages[int(salon_id)] = faits
    if len(faits) < RENOMMAGES_MAX:
        return 0
    return int(RENOMMAGES_FENETRE - (t - faits[0])) + 1


def _noter(salon_id: int) -> None:
    _renommages.setdefault(int(salon_id), []).append(time.monotonic())
    if len(_renommages) > 2000:
        _renommages.pop(next(iter(_renommages)))


class ChoixBut(discord.ui.DynamicItem[discord.ui.Select], template=r"tv:but:(?P<salon>\d+)"):
    """Le but du vocal, dans son panneau. Persistant : il marche après un redémarrage."""

    def __init__(self, salon_id: int, options=None, placeholder: str = "Le but du vocal · Purpose"):
        self.salon_id = int(salon_id)
        super().__init__(discord.ui.Select(custom_id=f"tv:but:{int(salon_id)}", placeholder=placeholder,
                                           options=options or [discord.SelectOption(label="—", value="-")],
                                           min_values=1, max_values=1))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["salon"]))

    async def callback(self, i: discord.Interaction):
        valeurs = (getattr(i, "data", None) or {}).get("values") or []
        await choisir(i, self.salon_id, str(valeurs[0]) if valeurs else "")


def vue_panneau(salon_id: int, cle: str, proprio_id: int, but: str = "") -> LayoutView:
    """Le panneau posé dans le vocal créé : choisir le but ; le nom du salon le montre à tous."""
    ctx = contexte(cle)
    actuel = BUTS.get(but)
    if ctx.demande:
        tete = (f"### 🙋 Ta demande au clan · Your request\n<@{int(proprio_id)}>, que demandes-tu ? Le nom du "
                "salon le montre à tout le clan : ceux qui peuvent t'aider te rejoignent.\n"
                "-# What do you need? The channel name shows it to the whole clan.")
    else:
        tete = (f"### {ctx.emoji or '🔊'} Ton vocal · {ctx.titre}\n<@{int(proprio_id)}>, choisis le but de ton vocal : "
                "le nom du salon le montre à tous, ceux qui ont le même besoin te rejoignent.\n"
                "-# Pick your channel's purpose: its name shows it to everyone.")
    lignes = [tete]
    if actuel is not None:
        lignes.append(f"**Actuellement · Now : {actuel.emoji} {actuel.nom}**")
    lignes.append("-# Le salon se ferme tout seul quand il est vide · Closes by itself when empty")
    options = [discord.SelectOption(label=BUTS[b].nom, value=b, emoji=BUTS[b].emoji, default=(b == but))
               for b in ctx.buts if b in BUTS]
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lignes)),
                                    discord.ui.ActionRow(ChoixBut(salon_id, options)),
                                    accent_color=Palette.INFO))
    return v


async def poser_panneau(salon, cle: str, membre) -> None:
    """Dans le chat du vocal qui vient d'être créé : le panneau, avec son propriétaire prévenu."""
    await salon.send(view=vue_panneau(salon.id, cle, membre.id),
                     allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[membre]))


async def _dire(i, texte: str) -> None:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=Palette.WARNING))
    if i.response.is_done():
        await i.followup.send(view=v, ephemeral=True)
    else:
        await i.response.send_message(view=v, ephemeral=True)


async def choisir(i, salon_id: int, cle: str) -> None:
    """Le propriétaire (ou le staff) choisit le but : le salon est renommé, le panneau le montre."""
    g = i.guild
    salon = g.get_channel(int(salon_id)) if g is not None else None
    if salon is None:
        return await _dire(i, "Ce vocal n'existe plus · This channel is gone.")
    info = await _proprio(salon)
    if info is None:
        return await _dire(i, "Ce vocal n'est pas un vocal à la demande · Not an on-demand channel.")
    proprio_id, cle_ctx = info
    if i.user.id != int(proprio_id) and not await _est_staff(g, i.user):
        return await _dire(i, f"Seul <@{int(proprio_id)}> choisit le but de ce vocal · Only the owner can.")
    ctx, but = contexte(cle_ctx), BUTS.get(cle)
    if but is None or cle not in ctx.buts:
        return await _dire(i, "Ce choix n'existe pas ici · Not available here.")
    reste = attente(salon.id)
    if reste:
        return await _dire(i, f"Discord n'accepte que 2 changements de nom toutes les 10 minutes : réessaie dans "
                              f"{max(1, -(-reste // 60))} min · Discord allows 2 renames per 10 minutes.")
    await i.response.defer()
    membre = g.get_member(int(proprio_id))
    pseudo = getattr(membre, "display_name", None) or "vocal"
    try:
        await asyncio.wait_for(salon.edit(name=nom_salon(ctx, but, pseudo), reason=f"Vocal : {but.nom}"), timeout=10)
        _noter(salon.id)
    except (asyncio.TimeoutError, discord.HTTPException) as ex:
        _log("[VOCAUX][E1] nom du vocal non changé")
        _log(f"[VOCAUX][E1:DETAIL] salon={salon.id} {type(ex).__name__} {ex}")
        return await _dire(i, "Discord n'a pas accepté le nouveau nom pour l'instant : réessaie dans quelques "
                              "minutes · Discord refused the rename for now.")
    await i.edit_original_response(view=vue_panneau(salon.id, cle_ctx, int(proprio_id), but.cle))
