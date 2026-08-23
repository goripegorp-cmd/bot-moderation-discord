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

def construire(fiches: list, *, palier: str, salon_retour=None,
               role_ping=None, muet: bool = False) -> LayoutView | None:
    """Le message d'un palier, en Components V2. None s'il n'y a personne.

    `palier` vaut "doux", "rappel" ou "retrait". Trois messages distincts et
    jamais fusionnés : mélanger « tu es un peu juste » et « tu as perdu tes
    rôles » dans un même bloc ferait lire le mauvais des deux à tout le monde.
    """
    if not fiches:
        return None

    if palier == "doux":
        titre, couleur = txt.T_PRESQUE, Palette.INFO
        if role_ping is not None:
            #  ⚠️ AVEC UN RÔLE, ON ANNONCE LA RÈGLE, PAS LE CHIFFRE D'UN SEUL.
            #  Le palier doux couvre 0/3, 1/3 et 2/3. Afficher les chiffres du
            #  premier de la liste ferait lire « Vu 0 jour sur 3 » à des
            #  centaines de membres pour qui c'est faux — et il n'y a plus de
            #  ligne par personne pour rétablir la vérité.
            #  ⚠️ LE SEUIL VIENT DE `activite.presence_exigee`, PAS DE LA CONF
            #  BRUTE. La fenêtre réelle est plafonnée par l'ancienneté du
            #  suivi : afficher le seuil de la conf annoncerait « au moins
            #  3 jours sur 3 » alors que le code n'en exige qu'un. Une seule
            #  source pour ce chiffre, sinon le message ment.
            action = txt.presence_demandee(
                activite.presence_exigee(fiches[0], fiches[0]["seuils"]),
                fiches[0]["fenetre"])
        else:
            #  Un seul chiffre pour l'en-tête, celui du premier de la liste : le
            #  détail par personne est déjà sur chaque ligne, et répéter la
            #  fenêtre autant de fois qu'il y a de membres rallongerait pour rien.
            action = txt.vu_trop_peu(fiches[0]["presents"], fiches[0]["fenetre"])
    elif palier == "retrait":
        titre, couleur = txt.T_ROLES_RETIRES, Palette.WARNING
        action = txt.revenir(salon_retour.mention if salon_retour is not None else None)
    elif palier == "abandon":
        #  ⚠️ SANS CETTE BRANCHE, la phase 3 tombait dans le repli et
        #  s'affichait sous « 💤 Absents » — le titre d'une autre phase.
        titre, couleur = txt.T_ABANDON, Palette.DANGER
        action = txt.revenir(salon_retour.mention if salon_retour is not None else None)
    else:
        titre, couleur = txt.T_ABSENTS, Palette.INFO
        action = txt.revenir()

    #  ⚠️ ON MENTIONNE LE RÔLE, PAS LES GENS — demandé le 15/08.
    #
    #  L'ancienne version listait chaque membre. Mesuré chez le propriétaire :
    #  950 mentions dans un seul message, suivies d'un « +923 ». Illisible,
    #  et Discord plafonne de toute façon les mentions d'un message.
    #
    #  Le rôle d'absence est DÉJÀ posé sur chacun d'eux par le palier (voir
    #  `activite_niveaux.poser_niveau`). Le mentionner touche donc exactement les
    #  mêmes personnes, en une ligne, sans mur de pseudos. Le compte reste
    #  affiché : c'est lui qui donne la mesure du problème.
    if muet:
        #  ⚠️ LE MODE MUET EXISTE POUR NE PAS PINGUER DEUX FOIS LES MÊMES GENS.
        #  Les étiquettes sont GLOBALES au serveur, mais la boucle d'envoi
        #  tourne PAR RÔLE SURVEILLÉ : avec deux rôles surveillés, le même
        #  rôle « peu actif » serait mentionné deux fois le même dimanche, et
        #  les deux marqueurs anti-doublon resteraient verts — ils sont par
        #  groupe, la mention ne l'est pas.
        #
        #  ⚠️ IL NE SUFFIT PAS DE PASSER `role_ping=None` : on retomberait sur
        #  la liste, qui mentionne jusqu'à 30 membres NOMMÉMENT, avec
        #  `users=True` à l'envoi. On remplacerait un ping de rôle par trente
        #  pings de personnes.
        corps = f"-# `{len(fiches)}` membre(s) concerné(s)"
    elif role_ping is not None:
        #  ⚠️ ON ANNONCE CE QUE LE RÔLE TOUCHE, PAS CE QU'ON A CLASSÉ.
        #  L'étiquette se pose par tranches (budget de débit) : au premier
        #  passage, le rôle peut porter 240 membres alors que 959 sont classés.
        #  Afficher `len(fiches)` annoncerait plus de monde que la mention n'en
        #  notifie — le message mentirait sur sa propre portée.
        _touches = len(getattr(role_ping, "members", None) or []) or len(fiches)
        corps = (f"{role_ping.mention}\n"
                 f"-# `{_touches}` membre(s) concerné(s)")
    else:
        #  Repli quand aucun rôle n'est configuré : on liste, mais borné.
        corps = "\n".join(_liste(fiches, palier))

    items = [
        v2_title(titre),
        v2_body(corps),
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

async def remplacer(guild, salon, cle_role, vues: list, cfg_act: dict, *,
                    purger_si_vide: bool = True) -> dict:
    """Supprime les rappels de la semaine passée, puis poste les nouveaux.

    Rend `{"envoyes": [ids], "echecs": [str], "raison": str}`.

    L'ordre compte : on supprime D'ABORD. Si l'on postait avant, une panne entre
    les deux laisserait deux listes contradictoires dans le salon — et c'est
    justement le mur de messages périmés qu'on veut éviter.
    La suppression est fail-safe : un message déjà effacé à la main, ou trop
    ancien pour l'API, ne doit pas empêcher le nouveau de partir.

    ⚠️ ON NE DÉTRUIT JAMAIS CE QU'ON NE PEUT PAS REMPLACER — ajouté le 20/08.
    Tant que cette fonction ne tournait qu'une fois par semaine derrière les
    deux gardes du passage, supprimer d'abord était de l'hygiène. Le bouton de
    renvoi manuel court-circuite ces gardes : deux cas ORDINAIRES vidaient
    alors le salon en rapportant « 0 envoyé » —
      · aucun absent classé : `construire` rend `None` pour les trois vues, on
        supprimait quand même et on ne postait rien ;
      · salon interdit au bot : la suppression passe (elle est fail-safe),
        l'envoi échoue, et l'échec était avalé.
    D'où le pré-test des permissions et `purger_si_vide=False` pour le bouton.

    ⚠️ ET ELLE NE REND PLUS UN ENTIER. Elle avalait ses exceptions et rendait
    `len(envoyes)` : un envoi refusé à 100 % était indiscernable de « personne
    à relancer ». L'appelant a besoin de la différence pour ne pas marquer la
    semaine comme faite.
    """
    res = {"envoyes": [], "echecs": [], "raison": ""}
    a_poster = [v for v in vues if v is not None]

    #  Le bot peut-il seulement poster ici ? On le demande AVANT de supprimer.
    try:
        perms = salon.permissions_for(guild.me)
        if not (perms.view_channel and perms.send_messages):
            res["echecs"].append("salon interdit au bot")
            res["raison"] = ("le bot ne peut pas écrire dans ce salon — "
                             "RIEN n'a été supprimé")
            return res
    except Exception as ex:
        _log(f"[activite_message permissions] {ex}")

    if not a_poster and not purger_si_vide:
        res["raison"] = "personne à relancer — les messages en place sont gardés"
        return res

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
            #  ⚠️ LES RÔLES SONT MAINTENANT AUTORISÉS, ET C'EST INDISPENSABLE.
            #
            #  Le rappel mentionne désormais le RÔLE d'absence au lieu des
            #  membres un par un. Avec `roles=False`, la mention s'afficherait
            #  sans notifier personne : un rappel que personne ne reçoit ne sert
            #  à rien. On autorise donc les rôles.
            #
            #  @everyone reste INTERDIT : le rôle ne touche que les absents,
            #  jamais le serveur entier. C'est toute la différence entre relancer
            #  ceux qui sont concernés et réveiller tout le monde.
            msg = await salon.send(view=v, allowed_mentions=discord.AllowedMentions(
                users=True, roles=True, everyone=False))
            envoyes.append(msg.id)
        except Exception as ex:
            _log(f"[activite_message envoi] {ex}")
            #  ⚠️ L'ÉCHEC REMONTE. Avalé, il rendait un envoi 100 % refusé
            #  indiscernable de « personne à relancer » — et l'appelant
            #  marquait la semaine comme faite.
            res["echecs"].append(str(ex)[:120])

    #  On ne réécrit la mémoire que s'il y a quelque chose à mémoriser ou à
    #  oublier : l'écraser avec une liste vide après un envoi refusé ferait
    #  perdre la trace des messages encore en place.
    if envoyes or anciens:
        try:
            await activite.ecrire_config_role(
                guild.id, cle_role, dernier_message_rappel=envoyes)
        except Exception as ex:
            _log(f"[activite_message mémorisation] {ex}")
    res["envoyes"] = envoyes
    if not envoyes and not res["echecs"]:
        res["raison"] = "aucun palier à annoncer"
    return res


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
