"""activite_niveaux.py — Les rôles d'inactivité, et le masquage du serveur.

Le système ne se contente pas de compter les absents : il leur POSE UN RÔLE.
Ce rôle rend l'absence visible, et surtout il porte le masquage — un membre au
premier palier ne voit plus rien du serveur, sauf deux salons : celui où la liste
des absents est publiée, et celui où il écrit pour revenir.

═══════════════════════════════════════════════════════════════════════════════
POURQUOI LE MASQUAGE PASSE PAR UN RÔLE, ET PAS PAR DES DROITS PAR MEMBRE
═══════════════════════════════════════════════════════════════════════════════
Un droit posé membre par membre laisse une trace par membre dans CHAQUE salon.
Cent absents sur cinquante salons, c'est cinq mille surcharges de permissions —
Discord en limite le nombre et l'API met des minutes à les poser. Un rôle, lui,
se pose une fois par salon et couvre tout le monde, pour toujours.

═══════════════════════════════════════════════════════════════════════════════
LE PIÈGE DES PERMISSIONS DISCORD — À LIRE AVANT DE TOUCHER À CE FICHIER
═══════════════════════════════════════════════════════════════════════════════
Discord résout les droits d'un salon dans cet ordre : @everyone, puis TOUS les
rôles du membre fusionnés (les refus d'abord, les autorisations ENSUITE), puis
les droits du membre. Conséquence : si un AUTRE rôle du membre porte une
autorisation EXPLICITE de voir un salon, elle écrase notre refus.

  · Au palier 2, aucun problème : tous ses rôles lui sont retirés.
  · Au palier 1, il les garde — le masquage peut donc être mis en échec.

On ne le cache pas et on ne le contourne pas en douce : `conflits(guild)` liste
exactement les salons concernés, et le panneau les affiche. Le propriétaire
décide — retirer l'autorisation explicite, ou accepter que ces salons restent
visibles au premier palier.

═══════════════════════════════════════════════════════════════════════════════
IDEMPOTENCE ET DÉBIT
═══════════════════════════════════════════════════════════════════════════════
`appliquer_masquage` compare AVANT d'écrire et ne touche que les salons dont le
droit diffère. Un deuxième passage ne fait donc aucun appel réseau. C'est ce qui
rend l'opération relançable sans crainte sur un serveur de deux cents salons.
"""
from __future__ import annotations

import asyncio
import json

import discord

import activite

#  Discord limite les modifications de salon. Une petite pause entre deux
#  écritures évite de manger le quota du bot entier pour une tâche de fond —
#  et une tâche de fond ne doit JAMAIS ralentir la modération.
PAUSE_ENTRE_SALONS = 0.35

#  Au-delà, on s'arrête et on le dit. Un serveur qui a plus de salons que ça
#  demande un traitement étalé, pas un passage en force qui bloque le bot.
MAX_SALONS_PAR_PASSAGE = 250

NOM_DOUX = "👀 Peu actif"
NOM_NIVEAU1 = "💤 AFK"
NOM_NIVEAU2 = "💤 AFK · rôles retirés"
NOM_ABANDON = "🚪 Compte abandonné"

#  ⚠️ LA CLÉ SE LIT DANS UNE TABLE, JAMAIS PAR f-STRING.
#  L'ancien code faisait `cfg_act.get(f"activite_role_niveau{niveau}")` : pour
#  un niveau hors {1, 2} il rendait None sans le dire, donc `cible is None`,
#  donc un refus silencieux. Une table lève l'ambiguïté et rend le palier 0
#  possible.
_CLE_PAR_NIVEAU = {
    0: "activite_role_doux",
    1: "activite_role_niveau1",
    2: "activite_role_niveau2",
    3: "activite_role_abandon",
}

#  ⚠️ UN NIVEAU ABSENT DE CES DEUX TABLES CRÉE UN DOUBLON EN SILENCE.
#  `creer_role` retombait sur `NOM_NIVEAU2` : ajouter le palier 3 sans son nom
#  aurait fabriqué un second rôle appelé « 💤 AFK · rôles retirés », impossible
#  à distinguer du vrai dans la liste du serveur.
_NOM_PAR_NIVEAU = {0: NOM_DOUX, 1: NOM_NIVEAU1, 2: NOM_NIVEAU2, 3: NOM_ABANDON}
_COULEUR_PAR_NIVEAU = {0: 0x5865F2, 1: 0x4E5058, 2: 0x4E5058, 3: 0x992D22}

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Les rôles eux-mêmes
# ═══════════════════════════════════════════════════════════════════════════════

def roles_afk(guild, cfg_act: dict) -> list:
    """Les rôles d'inactivité MASQUANTS qui existent réellement, par palier.

    ⚠️ TROIS SUR QUATRE. C'est cette liste que lit `appliquer_masquage` : seul
    ce qui y figure reçoit `view_channel=False`. L'étiquette « peu actif » en
    est volontairement absente — ces membres-là VIENNENT d'écrire, leur
    masquer le serveur serait absurde. L'abandon, lui, y est : sinon poser le
    palier 3 (qui retire l'étiquette du palier 2) rendrait l'accès au serveur
    au membre le plus inactif.
    """
    out = []
    for cle in ("activite_role_niveau1", "activite_role_niveau2",
                "activite_role_abandon"):
        rid = int(cfg_act.get(cle) or 0)
        if rid:
            r = guild.get_role(rid)
            if r is not None:
                out.append(r)
    return out


#  ⚠️ CACHE INDISPENSABLE — lu sur CHAQUE message du serveur.
#  Le retour d'un membre doit être IMMÉDIAT : quelqu'un qui écrit dans le salon
#  de retour et qui reste masqué six heures de plus conclut que le système est
#  cassé. Mais vérifier ça proprement demanderait de lire la configuration à
#  chaque message. On garde donc en mémoire les identifiants des rôles
#  d'inactivité de toutes les guildes : la vérification devient une comparaison
#  d'entiers, sans le moindre `await`, et ne coûte rien aux 99,99 % de messages
#  écrits par des membres qui n'ont aucune étiquette.
_IDS_CONNUS: set[int] = set()


def memoriser_ids(cfg_act: dict) -> None:
    """Enregistre les rôles d'inactivité d'une guilde dans le cache mémoire.

    Appelé au démarrage, à chaque passage, et dès qu'un rôle est désigné dans le
    panneau. On n'enlève jamais rien : un identifiant périmé ne provoque au pire
    qu'une vérification inutile, alors qu'un identifiant manquant laisserait un
    membre masqué sans qu'il puisse revenir.
    """
    _IDS_CONNUS.update(ids_afk(cfg_act))


def porte_une_etiquette(member) -> bool:
    """Ce membre porte-t-il un rôle d'inactivité ? Sans base, sans réseau."""
    if not _IDS_CONNUS:
        return False
    try:
        return any(r.id in _IDS_CONNUS for r in member.roles)
    except Exception:
        return False


def ids_afk(cfg_act: dict) -> set[int]:
    """Les identifiants des rôles d'inactivité MASQUANTS, même s'ils ont disparu.

    Version « sans guilde » : sert à exclure ces rôles d'une liste à mémoriser
    sans avoir à les résoudre. Un rôle supprimé côté Discord doit tout de même
    être exclu, sinon on le mémoriserait comme un rôle du membre à restituer.

    ⚠️ DEUX RÔLES, ET PAS TROIS — NE PAS Y AJOUTER L'ÉTIQUETTE DOUCE.
    Cette fonction et `roles_afk` pilotent le MASQUAGE des salons et le cache
    du retour immédiat. Y verser le rôle « peu actif » ferait deux dégâts :
      · `appliquer_masquage` poserait `view_channel=False` sur tous les salons
        pour des centaines de membres qui viennent justement d'écrire ;
      · `_IDS_CONNUS` déclencherait `retour_immediat` à leur premier message,
        donc `remettre_doux()`, donc le compteur de rappels doux retomberait à
        zéro — et le contournement « je poste une fois par semaine » que
        `doux_max` referme se rouvrirait entièrement.
    Pour la liste des ÉTIQUETTES (les trois), voir `ids_etiquettes`.
    """
    #  ⚠️ L'ABANDON EST ICI, LE DOUX NON — ET LA DIFFÉRENCE EST DÉLIBÉRÉE.
    #  `poser_niveau` n'autorise QU'UNE étiquette à la fois : passer un membre
    #  au palier 3 lui RETIRE celle du palier 2. Si l'abandon n'était pas dans
    #  cette liste, le membre le plus inactif du serveur — déjà dépouillé de
    #  tous ses rôles — serait le seul à retrouver l'accès complet.
    #  Second motif : `_IDS_CONNUS` est alimenté par cette même liste, et c'est
    #  lui qui déclenche le retour immédiat. Hors d'ici, un abandonné qui
    #  revient resterait bloqué jusqu'à six heures.
    return {int(cfg_act.get(c) or 0) for c in
            ("activite_role_niveau1", "activite_role_niveau2",
             "activite_role_abandon")} - {0}


def ids_etiquettes(cfg_act: dict) -> set[int]:
    """Les identifiants des TROIS étiquettes, masquantes ou non.

    C'est la liste qu'il faut partout où l'on demande « ce membre porte-t-il
    une étiquette du système ? » — retrait d'étiquette, sauvegarde des rôles
    avant dépouillement, détection de conflit. Jamais pour le masquage.
    """
    return {int(cfg_act.get(c) or 0) for c in _CLE_PAR_NIVEAU.values()} - {0}


def roles_etiquettes(guild, cfg_act: dict) -> list:
    """Les objets rôle des trois étiquettes, DANS L'ORDRE des paliers (0, 1, 2).

    L'ordre compte : `poser_niveau` s'en sert pour savoir quelles étiquettes
    retirer quand il en pose une autre.
    """
    out = []
    for cle in _CLE_PAR_NIVEAU.values():
        rid = int(cfg_act.get(cle) or 0)
        if rid:
            r = guild.get_role(rid)
            if r is not None:
                out.append(r)
    return out


async def creer_role(guild, niveau: int) -> discord.Role | None:
    """Crée un rôle d'inactivité, SANS AUCUNE PERMISSION.

    `permissions=none` est délibéré : ce rôle ne doit rien donner. Il ne sert
    qu'à porter des REFUS dans les salons. Un rôle créé avec les permissions par
    défaut du serveur accorderait au contraire des droits à des absents.
    """
    #  Table plutôt que ternaire : avec trois paliers, `NOM_NIVEAU1 if
    #  niveau == 1 else NOM_NIVEAU2` donnait au palier 0 le nom du palier 2.
    nom = _NOM_PAR_NIVEAU.get(niveau, NOM_NIVEAU2)
    try:
        return await guild.create_role(
            name=nom,
            permissions=discord.Permissions.none(),
            colour=discord.Colour(_COULEUR_PAR_NIVEAU.get(niveau, 0x4E5058)),
            #  ⚠️ `hoist=False` : ce rôle touche des centaines de membres, les
            #  afficher séparément dans la barre latérale la rendrait illisible.
            #  ⚠️ `mentionable=False` : personne d'autre que le bot ne doit
            #  pouvoir réveiller des centaines de gens. Le bot, lui, ping en
            #  passant `allowed_mentions(roles=True)` explicitement.
            hoist=False, mentionable=False,
            reason="Système d'activité : rôle d'inactivité",
        )
    except Exception as ex:
        _log(f"[activite_niveaux creer_role] {ex}")
        return None


def utilisable(guild, role) -> bool:
    """Le bot peut-il réellement poser et retirer ce rôle ?

    Vérifié explicitement plutôt que découvert par une exception : un rôle
    au-dessus du bot produit un échec silencieux à chaque membre, et le système
    paraîtrait cassé sans qu'on sache pourquoi.
    """
    try:
        return (role is not None
                and guild.me.guild_permissions.manage_roles
                and role < guild.me.top_role
                and not role.managed)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Le masquage des salons
# ═══════════════════════════════════════════════════════════════════════════════

def salons_ouverts(guild, cfg_act: dict) -> set[int]:
    """Les salons qui restent VISIBLES aux absents.

    Deux seulement, par rôle surveillé : celui où la liste est publiée, et celui
    où l'on écrit pour revenir. On prend l'union de tous les rôles, parce qu'un
    rôle surveillé peut avoir ses propres salons — masquer le salon de retour
    d'un autre groupe enfermerait ses membres sans issue.
    """
    ids = {int(cfg_act.get("activite_salon_annonce") or 0),
           int(cfg_act.get("activite_salon_retour") or 0)}
    for cle in (cfg_act.get("activite_roles") or {}):
        conf = activite.config_du_role(cfg_act, cle)
        ids.add(int(conf.get("salon_annonce") or 0))
        ids.add(int(conf.get("salon_retour") or 0))
    return ids - {0}


def _droits_voulus(salon_id: int, cfg_act: dict, ouverts: set[int]):
    """Le droit exact que doit porter un rôle AFK sur ce salon.

    Le salon de RETOUR est le seul où l'absent peut écrire : c'est sa porte de
    sortie. Le salon d'ANNONCE est visible mais muet — il sert à lire la liste,
    pas à discuter, et laisser cent absents y répondre le rendrait illisible.
    """
    if salon_id not in ouverts:
        return discord.PermissionOverwrite(view_channel=False)

    retour = int(cfg_act.get("activite_salon_retour") or 0)
    for cle in (cfg_act.get("activite_roles") or {}):
        if int(activite.config_du_role(cfg_act, cle).get("salon_retour") or 0) == salon_id:
            retour = salon_id
    peut_ecrire = (salon_id == retour)
    return discord.PermissionOverwrite(
        view_channel=True, read_message_history=True,
        send_messages=peut_ecrire, add_reactions=peut_ecrire,
    )


def _identiques(actuel, voulu) -> bool:
    """Le droit en place dit-il déjà exactement ce qu'on veut ?

    Comparaison sur les seules clés qu'on pilote : un salon peut porter d'autres
    surcharges posées à la main par le staff, et les écraser serait une
    modification que personne n'a demandée.
    """
    if actuel is None:
        return False
    a, v = dict(iter(actuel)), dict(iter(voulu))
    return all(a.get(k) == val for k, val in v.items() if val is not None)


async def appliquer_masquage(guild, cfg_act: dict, *, dry_run: bool = False) -> dict:
    """Pose le refus de voir sur TOUS les salons, pour les rôles d'inactivité.

    Y compris les salons où le rôle n'a jamais été ajouté : c'est justement le
    cas courant, et un salon oublié est une fuite qui vide le système de son sens.

    Ne touche que ce qui diffère (voir l'en-tête) : relancer est gratuit.
    """
    res = {"modifies": 0, "deja_bons": 0, "echecs": 0, "ignores": 0,
           "roles": 0, "raison": ""}
    if not cfg_act.get("activite_masquer_salons", True):
        res["raison"] = "masquage désactivé dans la configuration"
        return res

    roles = [r for r in roles_afk(guild, cfg_act) if utilisable(guild, r)]
    res["roles"] = len(roles)
    if not roles:
        res["raison"] = "aucun rôle d'inactivité utilisable par le bot"
        return res

    ouverts = salons_ouverts(guild, cfg_act)
    #  ⚠️ GARDE-FOU AJOUTÉ LE 12/08/2026 — NE PAS LE RETIRER.
    #
    #  Sans lui, un serveur dont les deux salons d'activité valent 0 se masquait
    #  ENTIÈREMENT : la liste des exceptions étant vide, l'absent ne voyait plus
    #  un seul salon, ne pouvait donc plus écrire nulle part, donc ne pouvait plus
    #  déclencher son propre retour. Un bannissement de fait, réappliqué à chaque
    #  passage — et l'écran affichait bien un avertissement, mais le bouton
    #  restait cliquable et le passage automatique l'appliquait quand même.
    #
    #  La porte de sortie n'est pas une option du masquage : elle en est la
    #  condition. Pas de salon de retour, pas de masquage.
    if not ouverts:
        res["raison"] = ("aucun salon de retour défini — masquage REFUSÉ : "
                         "sans lui, un absent ne pourrait plus jamais revenir")
        return res

    salons = list(guild.channels)
    if len(salons) > MAX_SALONS_PAR_PASSAGE:
        res["raison"] = (f"{len(salons)} salons — au-delà de "
                         f"{MAX_SALONS_PAR_PASSAGE}, traitement refusé")
        return res

    for salon in salons:
        voulu = _droits_voulus(salon.id, cfg_act, ouverts)
        for role in roles:
            try:
                if _identiques(salon.overwrites_for(role), voulu):
                    res["deja_bons"] += 1
                    continue
                if dry_run:
                    res["modifies"] += 1
                    continue
                await salon.set_permissions(
                    role, overwrite=voulu,
                    reason="Système d'activité : masquage des absents")
                res["modifies"] += 1
                await asyncio.sleep(PAUSE_ENTRE_SALONS)
            except discord.Forbidden:
                #  Un salon où le bot n'a pas la main. On compte et on continue :
                #  s'arrêter laisserait les salons suivants ouverts.
                res["ignores"] += 1
            except Exception as ex:
                _log(f"[activite_niveaux masquage {salon.id}] {ex}")
                res["echecs"] += 1
    return res


async def masquer_nouveau_salon(guild, salon, cfg_act: dict) -> bool:
    """Applique le masquage à UN salon qui vient d'être créé.

    Sans ça, chaque nouveau salon serait une fuite jusqu'au prochain passage
    complet — et personne ne pense à relancer un masquage après avoir créé un
    salon. C'est branché sur `on_guild_channel_create`.
    """
    if not cfg_act.get("activite_masquer_salons", True):
        return False
    ouverts = salons_ouverts(guild, cfg_act)
    voulu = _droits_voulus(salon.id, cfg_act, ouverts)
    fait = False
    for role in roles_afk(guild, cfg_act):
        if not utilisable(guild, role):
            continue
        try:
            await salon.set_permissions(
                role, overwrite=voulu,
                reason="Système d'activité : nouveau salon")
            fait = True
        except Exception as ex:
            _log(f"[activite_niveaux nouveau salon {salon.id}] {ex}")
    return fait


async def retirer_masquage(guild, cfg_act: dict) -> dict:
    """Enlève TOUTES les surcharges posées par le système. Le retour en arrière.

    Indispensable : un propriétaire qui éteint le système doit retrouver son
    serveur exactement comme avant, sans avoir à ouvrir deux cents salons à la
    main. Un système qu'on ne peut pas défaire, on ne l'allume pas.
    """
    res = {"nettoyes": 0, "echecs": 0}
    for role in roles_afk(guild, cfg_act):
        for salon in guild.channels:
            try:
                if salon.overwrites_for(role).is_empty():
                    continue
                await salon.set_permissions(
                    role, overwrite=None,
                    reason="Système d'activité : masquage retiré")
                res["nettoyes"] += 1
                await asyncio.sleep(PAUSE_ENTRE_SALONS)
            except Exception as ex:
                _log(f"[activite_niveaux retirer_masquage {salon.id}] {ex}")
                res["echecs"] += 1
    return res


def conflits(guild, cfg_act: dict) -> list[dict]:
    """Salons où une autorisation explicite écraserait notre refus.

    Voir « LE PIÈGE DES PERMISSIONS » en tête de fichier. On ne corrige rien
    tout seul : retirer une autorisation posée par le staff serait une décision
    qui ne nous appartient pas. On la SIGNALE, et le panneau l'affiche.
    """
    ouverts = salons_ouverts(guild, cfg_act)
    afk = ids_afk(cfg_act)
    out = []
    for salon in guild.channels:
        if salon.id in ouverts:
            continue
        coupables = []
        for cible, ow in salon.overwrites.items():
            if not isinstance(cible, discord.Role):
                continue
            if cible.id in afk or cible.id == guild.id:
                continue
            if ow.view_channel is True:
                coupables.append(cible.name)
        if coupables:
            out.append({"salon": salon.name, "id": salon.id, "roles": coupables})
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Poser et retirer les paliers sur un membre
# ═══════════════════════════════════════════════════════════════════════════════

def role_du_niveau(guild, niveau: int, cfg_act: dict):
    """L'étiquette configurée pour ce palier, ou None. Aucun accès réseau."""
    cle = _CLE_PAR_NIVEAU.get(niveau, "")
    rid = int(cfg_act.get(cle) or 0) if cle else 0
    if not rid:
        return None
    return guild.get_role(rid)


def reste_a_faire(guild, member, niveau: int, cfg_act: dict) -> bool:
    """Reste-t-il quelque chose à APPLIQUER à ce membre, à ce palier ?

    ⚠️ CE PRÉDICAT EXISTE POUR CASSER UN TAPIS ROULANT. Sans lui, les 25 plus
    anciens absents étaient « ré-appliqués » toutes les six heures — étiquette
    déjà posée, donc aucune écriture — pendant que 894 autres attendaient un
    tour qui ne venait jamais. Mesuré le 03/09 : deux passages consécutifs,
    « 919 à étiqueter » puis « 919 à étiqueter ».

    Il reproduit EXACTEMENT ce que feraient `poser_niveau` et, au palier 2,
    `retirer_tous_les_roles` — sinon on écarterait du quota un membre pour qui
    il restait du travail, ce qui est le défaut inverse et bien pire.

    En cas de doute il rend True : on préfère un passage inutile à un membre
    oublié.
    """
    try:
        cible = role_du_niveau(guild, niveau, cfg_act)
        #  Aucune étiquette posable : on laisse le palier décider et refuser
        #  lui-même (c'est lui qui journalise la cause).
        if cible is None or not utilisable(guild, cible):
            return True
        if cible not in member.roles:
            return True
        #  L'étiquette est là, mais celle d'un autre palier peut traîner :
        #  `poser_niveau` doit encore la retirer.
        for r in roles_etiquettes(guild, cfg_act):
            if r.id != cible.id and r in member.roles and utilisable(guild, r):
                return True
        #  Palier 2 : le dépouillement est le vrai travail. Il reste à faire
        #  tant qu'un rôle retirable subsiste — même critère que
        #  `retirer_tous_les_roles`, à la ligne près.
        if niveau == 2:
            afk = ids_etiquettes(cfg_act)
            for r in member.roles:
                if r.is_default() or r.managed or r.id in afk:
                    continue
                if utilisable(guild, r):
                    return True
        return False
    except Exception as ex:
        _log(f"[activite_niveaux reste_a_faire {getattr(member, 'id', '?')}] {ex}")
        return True


async def poser_niveau(guild, member, niveau: int, cfg_act: dict) -> bool:
    """Met le membre au palier demandé : ajoute son rôle, enlève celui de l'autre.

    Un seul rôle d'inactivité à la fois. En porter deux afficherait deux états
    contradictoires sur le même membre et fausserait tous les comptages.
    """
    #  ⚠️ LES TROIS ÉTIQUETTES, pas seulement les deux masquantes : sans ça le
    #  palier 0 ne trouverait jamais sa cible, et le passage doux → palier 1
    #  laisserait les deux étiquettes sur le même membre.
    voulus = roles_etiquettes(guild, cfg_act)
    if not voulus:
        return False
    cible = None
    for r in voulus:
        if int(cfg_act.get(_CLE_PAR_NIVEAU.get(niveau, "")) or 0) == r.id:
            cible = r
    #  ⚠️ SANS ÉTIQUETTE POSABLE, ON REFUSE — ET ON NE TOUCHE À RIEN.
    #  Le garde-fou du 12/08 (activite_escalade.py) refuse le dépouillement
    #  quand `poser_niveau` rend False. Il était CONTOURNABLE : si le rôle de
    #  CE palier n'est pas configuré (id 0), a été supprimé, ou est passé
    #  au-dessus du bot, `cible` restait None — mais `a_retirer` contenait
    #  alors le rôle de l'AUTRE palier, que le membre PORTE déjà. Le
    #  `remove_roles` réussissait, `fait` passait à True, la fonction rendait
    #  True, et le garde-fou laissait passer : le membre perdait TOUS ses
    #  rôles sans étiquette AFK ni masquage. Exactement l'accident que le
    #  commentaire du 12/08 déclare interdit — trouvé le 19/08 par un audit
    #  adverse, jamais par un test.
    #
    #  Retirer l'étiquette du palier précédent sans pouvoir poser la nouvelle
    #  laisserait de toute façon le membre non étiqueté : il n'y a aucun cas
    #  où continuer est le bon choix.
    if cible is None:
        return False
    #  ⚠️ ON VÉRIFIE QU'ELLE EST POSABLE AVANT D'ÉCRIRE QUOI QUE CE SOIT.
    #  Un rôle passé au-dessus du bot dans la hiérarchie est intouchable : sans
    #  ce contrôle, on retirerait l'étiquette précédente puis on échouerait à
    #  poser la nouvelle, laissant le membre sans étiquette du tout.
    if not utilisable(guild, cible):
        return False
    a_retirer = [r for r in voulus if r.id != cible.id]
    a_retirer = [r for r in a_retirer if r in member.roles and utilisable(guild, r)]

    #  ⚠️ LE RETOUR REFLÈTE LA POSE, JAMAIS LE RETRAIT — corrigé le 20/08/2026.
    #  L'ancien code mettait `fait = True` sur le simple `remove_roles`. Le
    #  garde-fou du 12/08 (activite_escalade) lit ce retour pour décider s'il a
    #  le droit de dépouiller un membre de tous ses rôles. Avec une étiquette
    #  douce portée par des centaines de membres, `a_retirer` est presque
    #  toujours non vide : le garde-fou aurait laissé passer le dépouillement
    #  de membres qu'on n'a pas réussi à étiqueter. On rend donc l'état de
    #  l'ÉTIQUETTE, seule chose que le garde-fou cherche à garantir.
    pose = cible in member.roles
    try:
        if not pose:
            await member.add_roles(cible, reason=f"Inactivité — palier {niveau}")
            pose = True
        if a_retirer:
            await member.remove_roles(*a_retirer,
                                      reason="Inactivité — changement de palier")
    except Exception as ex:
        _log(f"[activite_niveaux poser_niveau {member.id}] {ex}")
        #  L'ajout a pu échouer APRÈS qu'on l'ait cru posé : on ne ment pas.
        pose = cible in member.roles
    return pose


async def retirer_niveaux(guild, member, cfg_act: dict) -> bool:
    """Enlève tout rôle d'inactivité : le membre est de retour.

    ⚠️ LES TROIS ÉTIQUETTES, pas les deux masquantes. C'est l'UNIQUE sortie
    d'étiquette du système (seul appelant : `activite_escalade.traiter_retour`).
    Lire `roles_afk` ici transformerait le rôle « peu actif » en cliquet : posé
    une fois, jamais retiré, il s'accumulerait semaine après semaine sur des
    gens redevenus actifs — et le ping finirait par mentionner tout le serveur,
    exactement ce que ce rôle était censé éviter.
    """
    a_retirer = [r for r in roles_etiquettes(guild, cfg_act)
                 if r in member.roles and utilisable(guild, r)]
    if not a_retirer:
        return False
    try:
        await member.remove_roles(*a_retirer, reason="Activité : retour du membre")
        return True
    except Exception as ex:
        _log(f"[activite_niveaux retirer_niveaux {member.id}] {ex}")
        return False


async def retirer_tous_les_roles(guild, member, cfg_act: dict) -> dict:
    """Palier 2 : retire TOUS les rôles du membre, et les mémorise.

    « Tous » a des exceptions imposées par Discord, pas par nous :
      · les rôles gérés par une intégration (bot, boost, abonnement) — l'API
        refuse de les retirer, les demander ferait échouer tout l'appel ;
      · les rôles au-dessus du bot — même chose ;
      · les rôles d'inactivité eux-mêmes, qui portent le masquage.

    Tout part en UN SEUL appel (`edit(roles=...)`) plutôt qu'un appel par rôle :
    dix rôles retirés un par un, c'est dix modifications visibles dans le journal
    d'audit et dix fois le risque de s'arrêter au milieu, membre à moitié dépouillé.

    Les identifiants retirés sont écrits AVANT d'appeler Discord. Si l'écriture
    échoue, on n'agit pas : mieux vaut un retrait qui n'a pas eu lieu qu'un
    retrait dont on a perdu la liste — celui-là, personne ne peut le défaire.
    """
    res = {"retires": [], "gardes": [], "ok": False}
    #  ⚠️ LES TROIS ÉTIQUETTES, pas les deux masquantes. Un membre qui passe de
    #  « peu actif » au palier 2 porte encore l'étiquette douce dans le cache
    #  `member.roles` (la passerelle Discord met à jour de façon différée).
    #  Avec `ids_afk`, elle serait donc RETIRÉE avec les autres — et surtout
    #  MÉMORISÉE dans la liste des rôles à rendre. Le jour où le membre revient,
    #  on lui rendrait son étiquette « peu actif » comme si c'était un de ses
    #  rôles. C'est le seul endroit du système où une étiquette peut être
    #  confondue avec un vrai rôle du membre.
    afk = ids_etiquettes(cfg_act)
    try:
        garder, retirer = [], []
        for r in member.roles:
            if r.is_default():
                continue                    # @everyone n'est pas un rôle qu'on porte
            if r.managed or r.id in afk or not utilisable(guild, r):
                garder.append(r)
            else:
                retirer.append(r)
        res["gardes"] = [r.name for r in garder]
        if not retirer:
            res["ok"] = True
            return res

        ids = [r.id for r in retirer]
        async with activite._get_db() as db:
            async with db.execute(
                "SELECT roles_retires FROM activite_etat WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
            deja = json.loads(row[0]) if row and row[0] else []
            fusion = list(dict.fromkeys([int(x) for x in deja] + ids))
            await db.execute(
                "INSERT INTO activite_etat(guild_id, user_id, palier, roles_retires)"
                " VALUES(?,?,2,?)"
                " ON CONFLICT(guild_id, user_id) DO UPDATE SET palier=2, roles_retires=?",
                (guild.id, member.id, json.dumps(fusion), json.dumps(fusion)),
            )
            await db.commit()

        await member.edit(roles=garder, reason="Inactivité — retrait de tous les rôles")
        res["retires"] = [r.name for r in retirer]
        res["ok"] = True
    except Exception as ex:
        _log(f"[activite_niveaux retirer_tous_les_roles {member.id}] {ex}")
    return res


async def rendre_tous_les_roles(guild, member, cfg_act: dict) -> dict:
    """Le retour : le membre récupère tout ce qu'on lui avait pris.

    En un seul appel, comme le retrait. Les rôles devenus inaccessibles (rôle
    supprimé, passé au-dessus du bot) sont GARDÉS EN MÉMOIRE plutôt qu'oubliés :
    si le propriétaire redescend le rôle sous le bot, le prochain retour les rend.
    """
    res = {"rendus": [], "impossibles": [], "ok": False}
    try:
        async with activite._get_db() as db:
            async with db.execute(
                "SELECT roles_retires FROM activite_etat WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
        ids = json.loads(row[0]) if row and row[0] else []
        if not ids:
            res["ok"] = True
            return res

        a_rendre, restants = [], []
        for rid in ids:
            r = guild.get_role(int(rid))
            if r is None:
                continue                     # rôle supprimé : plus rien à rendre
            if not utilisable(guild, r):
                restants.append(int(rid))
                continue
            if r not in member.roles:
                a_rendre.append(r)

        if a_rendre:
            await member.edit(roles=list(member.roles) + a_rendre,
                              reason="Activité : retour du membre")
            res["rendus"] = [r.name for r in a_rendre]
        res["impossibles"] = restants

        async with activite._get_db() as db:
            await db.execute(
                "UPDATE activite_etat SET roles_retires=?, palier=0"
                " WHERE guild_id=? AND user_id=?",
                (json.dumps(restants), guild.id, member.id),
            )
            await db.commit()
        res["ok"] = True
    except Exception as ex:
        _log(f"[activite_niveaux rendre_tous_les_roles {member.id}] {ex}")
    return res
