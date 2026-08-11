"""activite_message.py — Ce que les membres voient. Court, bilingue, sans jargon.

Isolé parce que c'est le SEUL endroit du système que les membres voient. Le reste
tourne en silence ; ici, le ton et la longueur décident si quelqu'un revient ou
s'énerve.

═══════════════════════════════════════════════════════════════════════════════
COURT, PARCE QUE PERSONNE NE LIT
═══════════════════════════════════════════════════════════════════════════════
Consigne explicite du propriétaire, et elle est juste : un pavé d'explication
n'est pas lu, donc n'informe personne, et donne en prime l'impression d'une
procédure lourde alors que la règle tient en une phrase.
Chaque message tient donc en : un titre, la liste, une ligne d'action, un pied.
Les phrases elles-mêmes vivent dans `activite_textes.py`, où un garde-fou refuse
les lignes trop longues. Ici on ne fait qu'assembler.

═══════════════════════════════════════════════════════════════════════════════
UN CHIFFRE PAR PERSONNE
═══════════════════════════════════════════════════════════════════════════════
`@membre · 9 j` ou `@membre · 1/7`. Sans ce chiffre, chacun se croit visé par
erreur et vient le contester ; avec lui, la discussion est close avant d'exister.
Le format change selon le palier, parce que la mesure qui a déclenché le message
n'est pas la même : un silence en jours, une présence en jours vus sur la fenêtre.

═══════════════════════════════════════════════════════════════════════════════
UN SEUL MESSAGE VIVANT À LA FOIS
═══════════════════════════════════════════════════════════════════════════════
Chaque semaine, les rappels de la semaine passée sont SUPPRIMÉS avant d'en poster
de nouveaux. Sans ça, le salon accumule un mur de listes périmées où personne ne
sait laquelle est la bonne, et où d'anciens absents restent affichés alors qu'ils
sont revenus. Les identifiants sont mémorisés par rôle (`dernier_message_rappel`).
"""
from __future__ import annotations

import discord

import activite
import activite_calendrier as cal
import activite_textes as txt
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Les lignes de membres
# ═══════════════════════════════════════════════════════════════════════════════

def _ligne(fiche, *, palier: str) -> str:
    """Une ligne : la mention, puis LE chiffre qui a déclenché ce palier.

    Pour un absent, le nombre de jours de silence. Pour un rappel doux, le
    nombre de journées où on l'a vu sur la fenêtre — c'est ce « 1/7 » qui fait
    comprendre, sans une phrase d'explication, pourquoi il est dans la liste
    alors qu'il a posté avant-hier.
    """
    m = fiche["member"].mention
    if palier == "doux":
        return f"{m} · `{fiche['presents']}/{fiche['fenetre']}`"
    return f"{m} · `{fiche['jours']} j`"


def _liste(fiches: list, palier: str) -> list[str]:
    lignes = [_ligne(f, palier=palier) for f in fiches[:MAX_AFFICHES]]
    reste = len(fiches) - len(lignes)
    if reste > 0:
        lignes.append(f"-# +{reste}")
    return lignes


# ═══════════════════════════════════════════════════════════════════════════════
#  Les trois messages
# ═══════════════════════════════════════════════════════════════════════════════

def construire(fiches: list, *, palier: str, salon_retour=None) -> LayoutView | None:
    """Le message d'un palier, en Components V2. None s'il n'y a personne.

    `palier` vaut "doux", "rappel" ou "retrait". Trois messages distincts et
    jamais fusionnés : mélanger « tu es un peu juste » et « tu as perdu tes
    rôles » dans un même bloc ferait lire le mauvais des deux à tout le monde.
    """
    if not fiches:
        return None

    if palier == "doux":
        titre, couleur = txt.T_PRESQUE, Palette.INFO
        #  Un seul chiffre pour l'en-tête, celui du premier de la liste : le
        #  détail par personne est déjà sur chaque ligne, et répéter la fenêtre
        #  autant de fois qu'il y a de membres rallongerait pour rien.
        action = txt.vu_trop_peu(fiches[0]["presents"], fiches[0]["fenetre"])
    elif palier == "retrait":
        titre, couleur = txt.T_ROLES_RETIRES, Palette.WARNING
        action = txt.revenir(salon_retour.mention if salon_retour is not None else None)
    else:
        titre, couleur = txt.T_ABSENTS, Palette.INFO
        action = txt.revenir()

    items = [
        v2_title(titre),
        v2_body("\n".join(_liste(fiches, palier))),
        v2_divider(),
        v2_body(action),
    ]
    if palier == "retrait":
        items.append(v2_body(txt.retour_tout_revient()))
    items.append(v2_body(txt.pas_une_sanction()))
    items.append(v2_subtitle(txt.semaine_du(cal.debut_de_semaine(),
                                            cal.fin_de_semaine())))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=couleur))
    return v


def construire_regles(conf: dict, salon_retour=None) -> LayoutView:
    """La procédure, en quatre lignes numérotées. À épingler dans le salon.

    Les durées viennent de la CONFIGURATION du rôle, jamais écrites en dur : un
    serveur qui règle le retrait à 30 jours doit lire « 30 » ici. Une annonce qui
    annonce des seuils faux est pire que pas d'annonce — elle rend le système
    illégitime le jour où il agit.
    """
    lignes = txt.regles(conf["rappel"], conf["retrait"], conf["expulsion"])
    items = [v2_title(txt.T_REGLES), v2_divider()]
    for i, bloc in enumerate(lignes, start=1):
        items.append(v2_body(f"**{i}.** {bloc}"))
    items.append(v2_divider())
    items.append(v2_body(txt.revenir(
        salon_retour.mention if salon_retour is not None else None)))
    items.append(v2_body(txt.pas_une_sanction()))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=Palette.PRIMARY))
    return v


def construire_bienvenue(conf: dict, salon_retour=None) -> LayoutView:
    """Message privé au membre expulsé pour inactivité qui revient.

    Trois blocs, pas un de plus : ce qui s'est passé, la règle, la porte de
    sortie. Quelqu'un qui revient après une expulsion est déjà sur la défensive ;
    un long rappel à l'ordre le fait repartir aussitôt.
    """
    items = [
        v2_title(txt.T_BIENVENUE),
        v2_body(txt.apres_expulsion()),
        v2_divider(),
    ]
    for i, bloc in enumerate(txt.regles(conf["rappel"], conf["retrait"],
                                        conf["expulsion"]), start=1):
        items.append(v2_body(f"**{i}.** {bloc}"))
    items.append(v2_divider())
    items.append(v2_body(txt.revenir(
        salon_retour.mention if salon_retour is not None else None)))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=Palette.PRIMARY))
    return v


# ═══════════════════════════════════════════════════════════════════════════════
#  Le remplacement hebdomadaire
# ═══════════════════════════════════════════════════════════════════════════════

async def remplacer(guild, salon, cle_role, vues: list, cfg_act: dict) -> int:
    """Supprime les rappels de la semaine passée, puis poste les nouveaux.

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


async def accueillir(member, conf: dict, salon_retour=None) -> bool:
    """Envoie le message privé de re-bienvenue. Silencieux en cas d'échec.

    Un message privé fermé n'est pas une anomalie : beaucoup de membres les
    bloquent. On ne réessaie pas, on ne le publie pas ailleurs — annoncer
    publiquement que quelqu'un a été expulsé pour inactivité l'humilierait au
    moment précis où on cherche à le garder.
    """
    try:
        await member.send(view=construire_bienvenue(conf, salon_retour))
        return True
    except Exception:
        return False
