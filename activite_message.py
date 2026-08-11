"""activite_message.py — Le rappel hebdomadaire : sa forme, et son remplacement.

Isolé parce que c'est le SEUL endroit du système que les membres voient. Le reste
tourne en silence ; ici, le ton et la présentation décident si quelqu'un revient
ou s'énerve.

═══════════════════════════════════════════════════════════════════════════════
LE TON — CE N'EST PAS UNE PUNITION
═══════════════════════════════════════════════════════════════════════════════
Le message ne reproche rien et n'humilie personne. Il explique pourquoi le
serveur tient à une présence réelle — éviter une communauté de comptes fantômes
et de bots — et rappelle qu'un seul geste suffit à repartir de zéro.
Un message qui pique fait fuir ; un message clair fait revenir.

═══════════════════════════════════════════════════════════════════════════════
UN SEUL MESSAGE VIVANT À LA FOIS
═══════════════════════════════════════════════════════════════════════════════
Chaque semaine, l'ancien rappel est SUPPRIMÉ avant d'en poster un nouveau. Sans
ça, le salon accumule un mur de listes périmées où personne ne sait laquelle est
la bonne, et où d'anciens inactifs restent affichés alors qu'ils sont revenus.
L'identifiant du message est mémorisé par rôle (`dernier_message_rappel`).
"""
from __future__ import annotations

import discord

import activite
import activite_calendrier as cal
from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, subtitle as v2_subtitle, title as v2_title,
)

MAX_AFFICHES = activite.MAX_AFFICHES

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


def _ligne(fiche) -> str:
    """Une ligne par membre : la mention, puis depuis quand."""
    return f"{fiche['member'].mention} · `{activite.duree_lisible(fiche['jours'])}`"


def construire(fiches: list, *, salon_retour=None, avec_retrait: bool = False,
               nom_role: str | None = None) -> LayoutView | None:
    """Le rappel, en Components V2. None s'il n'y a personne à relancer."""
    if not fiches:
        return None

    lignes = [_ligne(f) for f in fiches[:MAX_AFFICHES]]
    reste = len(fiches) - len(lignes)

    items = []
    if avec_retrait:
        items.append(v2_title("🔻 Rôle mis en veille"))
        items.append(v2_subtitle(
            "Vous n'avez pas donné signe depuis un moment — votre rôle vous attend"))
    else:
        items.append(v2_title("👋 On ne vous a pas vu cette semaine"))
        items.append(v2_subtitle("Un seul geste suffit à repartir de zéro"))

    items.append(v2_divider())
    items.append(v2_body("\n".join(lignes)))
    if reste > 0:
        items.append(v2_body(f"-# … et {reste} autre(s) membre(s)"))
    items.append(v2_divider())

    #  Le « comment revenir » AVANT le « pourquoi » : quelqu'un qui ne lit qu'une
    #  ligne doit tomber sur l'action, pas sur la justification.
    items.append(v2_body(
        "**Comment repartir de zéro — une seule suffit :**\n"
        "💬 écrire un message  ·  🎤 passer en vocal  ·  👍 réagir à un message\n"
        "🎛️ utiliser une commande  ·  🧵 ouvrir un fil  ·  📊 voter à un sondage"
    ))

    if avec_retrait:
        if salon_retour is not None:
            items.append(v2_body(
                f"🔙 Votre rôle revient dès votre retour. Pour aller plus vite, "
                f"passez par {salon_retour.mention}."))
        else:
            items.append(v2_body("🔙 Votre rôle revient dès votre retour."))

    items.append(v2_divider())
    items.append(v2_body(
        "-# **Ce n'est ni une sanction, ni un reproche.** Le serveur tient "
        "simplement à rester vivant : sans ça, il se remplit de comptes "
        "fantômes et de bots, et il n'y a plus personne à qui parler. "
        "Vous ne perdez rien de façon définitive."
    ))

    ds = cal.debut_de_semaine()
    pied = f"Semaine du {ds.strftime('%d/%m')} au {cal.fin_de_semaine().strftime('%d/%m')}"
    if nom_role:
        pied += f" · {nom_role}"
    items.append(v2_subtitle(pied))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(
        *items, color=Palette.WARNING if avec_retrait else Palette.INFO))
    return v


async def remplacer(guild, salon, cle_role, vues: list, cfg_act: dict) -> int:
    """Supprime le rappel de la semaine passée, puis poste le nouveau.

    L'ordre compte : on supprime D'ABORD. Si l'on postait avant, une panne entre
    les deux laisserait deux listes contradictoires dans le salon — et c'est
    justement le mur de messages périmés qu'on veut éviter.
    La suppression est fail-safe : un message déjà effacé à la main, ou trop
    ancien pour l'API, ne doit pas empêcher le nouveau de partir.
    """
    conf = activite.config_du_role(cfg_act, cle_role)
    anciens = conf.get("dernier_message_rappel") or []
    if isinstance(anciens, (int, str)):
        anciens = [anciens]

    for mid in anciens:
        try:
            msg = await salon.fetch_message(int(mid))
            await msg.delete()
        except Exception:
            pass          # déjà supprimé, introuvable, ou hors de portée

    envoyes = []
    for v in vues:
        if v is None:
            continue
        try:
            #  Les mentions doivent NOTIFIER : c'est tout l'intérêt du rappel.
            #  On autorise explicitement les utilisateurs, et on interdit
            #  @everyone et les rôles — un rappel d'inactivité ne doit jamais
            #  réveiller tout le serveur.
            msg = await salon.send(view=v, allowed_mentions=discord.AllowedMentions(
                users=True, roles=False, everyone=False))
            envoyes.append(msg.id)
        except Exception as ex:
            _log(f"[activite_message envoi] {ex}")

    try:
        await activite.ecrire_config_role(
            guild.id, cle_role, dernier_message_rappel=envoyes)
    except Exception as ex:
        _log(f"[activite_message mémorisation] {ex}")
    return len(envoyes)
