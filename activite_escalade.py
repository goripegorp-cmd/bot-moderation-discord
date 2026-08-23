"""activite_escalade.py — Les paliers : rôle AFK, retrait de tous les rôles, départ.

Séparé de `activite.py` volontairement : le suivi doit rester minuscule et rapide
(il tourne sur CHAQUE message), l'escalade est un traitement lourd qui passe une
fois par jour. Mélanger les deux ferait payer à chaque message le coût du calcul.

═══════════════════════════════════════════════════════════════════════════════
LES CINQ ÉTATS POSSIBLES D'UN MEMBRE
═══════════════════════════════════════════════════════════════════════════════
  actif      · vu assez souvent — rien ne se passe, et on efface son ardoise
  doux       · vu, mais trop rarement. Un rappel léger, aucun rôle touché.
               Trois semaines de suite dans cet état et il bascule en « rappel ».
  rappel     · silencieux depuis le 1er seuil → RÔLE AFK, qui masque le serveur
  retrait    · silencieux depuis le 2e seuil → il perd TOUS ses rôles
  expulsion  · silencieux depuis le 3e → proposé au staff. JAMAIS automatique.

Le classement est GROUPÉ PAR RÔLE surveillé : chaque rôle a ses seuils, son
salon, son jour. Deux rôles peuvent donc vivre sur des rythmes indépendants.

RÉVERSIBILITÉ. Les rôles retirés sont mémorisés (`activite_etat.roles_retires`)
et rendus dès le retour. Le retrait n'est pas une punition, c'est une veille.
"""
from __future__ import annotations

import asyncio
import json

import activite
import activite_calendrier as cal
import activite_niveaux as niv

PLAFOND_ACTIONS_PAR_PASSAGE = activite.PLAFOND_ACTIONS_PAR_PASSAGE

#  L'ordre du plus grave au moins grave. Sert au classement ET à l'affichage :
#  une seule source de vérité évite qu'un écran range les paliers autrement.
PALIERS = ("expulsion", "retrait", "rappel", "doux")

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Classement
# ═══════════════════════════════════════════════════════════════════════════════

async def classer(guild) -> dict:
    """Range les membres concernés par RÔLE, puis par palier. NE MODIFIE RIEN.

    Retourne :
      {"groupes": {role_id: {"role", "conf", "doux", "rappel", "retrait",
                             "expulsion"}},
       "suivis", "actifs", "revenus",
       "doux"/"rappel"/"retrait"/"expulsion": [...]}   ← totaux tous rôles confondus

    « revenus » = ceux qui portent encore un rôle AFK alors qu'ils sont à jour.
    On les collecte ici pour que le passage n'ait pas à re-balayer la guilde.
    """
    cfg_act = await activite.config(guild.id)
    out = {"groupes": {}, "suivis": 0, "actifs": 0, "revenus": [],
           "doux": [], "rappel": [], "retrait": [], "expulsion": [],
           "observation": 0, "suivi_muet": False}
    if not await activite.actif(guild.id):
        return out

    #  L'âge du suivi se lit UNE FOIS pour toute la guilde, pas par membre : la
    #  même requête répétée mille fois est le genre de détail qui transforme un
    #  passage d'une seconde en passage d'une minute.
    suivi_jours = await activite.anciennete_du_suivi(guild.id)
    #  L'ancre d'observation : on ne reproche pas une journée antérieure à
    #  l'allumage du système. Lue UNE fois pour la guilde — voir
    #  `activite.observation_jours`, qui explique le blocage qu'elle corrige.
    observation = await activite.observation_jours(guild.id)
    out["observation"] = observation
    #  Journal totalement vide alors qu'on observe depuis plusieurs jours : sur
    #  un serveur vivant, c'est impossible. C'est le signe d'un suivi cassé
    #  (base réinitialisée, hooks débranchés), pas d'un serveur qui dort. On le
    #  signale et on n'agira sur personne — voir `activite_passage`.
    out["suivi_muet"] = (suivi_jours is None
                         and observation > activite.ANCIENNETE_MINIMALE)
    #  ⚠️ DEUX ENSEMBLES, ET LA DIFFÉRENCE COMPTE.
    #  `afk_ids` = les deux étiquettes MASQUANTES : « ce membre est-il masqué,
    #  dépouillé ? ». `etiq_ids` = les trois étiquettes : « porte-t-il une
    #  étiquette du système qu'il faut lui retirer ? ». Confondre les deux, soit
    #  masque le serveur à des centaines de présents, soit rend l'étiquette
    #  douce indélébile.
    afk_ids = niv.ids_afk(cfg_act)
    etiq_ids = niv.ids_etiquettes(cfg_act)
    #  Alimente le cache qui rend le retour immédiat possible sur chaque message
    #  (voir `activite_niveaux._IDS_CONNUS`).
    niv.memoriser_ids(cfg_act)
    semaine = cal.semaine()

    def _groupe(cle, role_obj):
        if cle not in out["groupes"]:
            out["groupes"][cle] = {
                "role": role_obj,
                "conf": activite.config_du_role(cfg_act, cle),
                "doux": [], "rappel": [], "retrait": [], "expulsion": [],
            }
        return out["groupes"][cle]

    for member in guild.members:
        try:
            if not await activite.membre_concerne(member, cfg_act):
                continue
            out["suivis"] += 1

            mesure = await activite.presence(guild.id, member, cfg_act,
                                             suivi_jours=suivi_jours,
                                             observation=observation)
            if mesure["silence"] is None:
                continue          # ni activité connue ni arrivée : on ne devine pas

            role = activite.role_surveille_du_membre(member, cfg_act)
            cle = str(role.id) if role is not None else activite.ROLE_TOUS
            g = _groupe(cle, role)
            conf = g["conf"]

            #  Un rôle peut être suspendu seul, sans éteindre tout le système.
            if not conf["actif"]:
                out["actifs"] += 1
                continue

            etat = await activite.lire_etat(guild.id, member.id)
            doux_deja = etat["doux"]
            palier = activite.verdict(mesure, conf, doux_deja)

            fiche = {"member": member, "jours": mesure["silence"],
                     #  Le silence RÉEL, non plafonné : « absent depuis 2 ans,
                     #  observé depuis 3 jours » est une information que le
                     #  staff doit voir, même si on ne juge pas là-dessus.
                     "jours_reels": mesure.get("silence_brut"),
                     "presents": mesure["presents"], "fenetre": mesure["fenetre"],
                     #  ⚠️ INDISPENSABLE AU MESSAGE. `presence_exigee` met le
                     #  seuil à l'échelle de la fenêtre réellement observée ;
                     #  sans cette valeur, le message annoncerait le seuil brut
                     #  de la configuration — « au moins 3 jours sur 3 » — alors
                     #  que le code n'en exige qu'un. Le message mentirait.
                     "fenetre_voulue": mesure.get("fenetre_voulue"),
                     "role": role, "seuils": conf, "groupe": cle,
                     #  Le palier voyage AVEC la fiche : `traiter_retour` doit
                     #  savoir s'il traite un membre redevenu ACTIF ou un membre
                     #  encore « doux » qu'on libère seulement d'un masquage.
                     #  Effacer l'ardoise du second rouvrirait le contournement
                     #  « je poste une fois par semaine ».
                     "palier": palier,
                     "doux_deja": doux_deja, "semaine": semaine}

            if palier == "actif":
                out["actifs"] += 1
                #  À jour, mais porte-t-il encore une étiquette d'absence ou
                #  a-t-il des rôles en attente ? C'est ici qu'on le repère, sans
                #  second balayage de la guilde.
                #  ⚠️ BUG CORRIGE LE 12/08/2026 — NE PAS RETIRER LA 3e CONDITION.
                #  On ne detectait le retour QUE sur l'etiquette AFK portee. Or si
                #  aucun role AFK n'est configure (l'etat PAR DEFAUT), le palier 2
                #  retirait quand meme tous les roles du membre : il se retrouvait
                #  depouille, SANS etiquette, donc invisible ici — et ses roles ne
                #  lui etaient JAMAIS rendus. Perte definitive.
                #  `a_des_roles_retires` vient de la meme requete que le compteur
                #  doux : il ne coute aucun acces supplementaire.
                #  ⚠️ LES TROIS ÉTIQUETTES ICI. Un membre redevenu actif doit
                #  perdre AUSSI l'étiquette « peu actif », sinon elle devient un
                #  cliquet et le rôle finit par mentionner tout le serveur.
                a_des_roles_afk = any(r.id in etiq_ids for r in member.roles)
                if a_des_roles_afk or doux_deja or etat["a_des_roles_retires"]:
                    out["revenus"].append(fiche)
                continue

            #  ⚠️ UN EX-PALIER 2 QUI REVIENT UN PEU N'EST PAS « ACTIF ».
            #  S'il poste une seule fois, son verdict est « doux » — donc il ne
            #  passe pas par la branche ci-dessus, et il resterait MASQUÉ et
            #  DÉPOUILLÉ sous une étiquette « peu actif ». On le verse aussi
            #  dans `revenus` pour qu'on lui rende ce qu'on lui a pris ; son
            #  étiquette douce, elle, sera reposée par `appliquer_doux`.
            if palier == "doux" and (any(r.id in afk_ids for r in member.roles)
                                     or etat["a_des_roles_retires"]):
                out["revenus"].append(fiche)

            g[palier].append(fiche)
            out[palier].append(fiche)
        except Exception as ex:
            _log(f"[activite classer {getattr(member, 'id', '?')}] {ex}")

    for g in out["groupes"].values():
        for k in PALIERS:
            g[k].sort(key=lambda f: -f["jours"])
    for k in PALIERS:
        out[k].sort(key=lambda f: -f["jours"])
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Le retour — le pendant exact du retrait
# ═══════════════════════════════════════════════════════════════════════════════

async def traiter_retour(guild, fiche, cfg_act: dict) -> dict:
    """Un membre est redevenu à jour : on défait tout ce qu'on lui avait fait.

    Dans cet ordre, et il compte :
      1. l'étiquette AFK part — sinon il reste masqué alors qu'il est revenu,
         ne voit pas le serveur, et croit que rien n'a marché ;
      2. ses rôles reviennent, tous, en un appel ;
      3. son ardoise de rappels doux s'efface.

    La restitution des rôles peut demander l'accord du staff (`restitution_auto`
    à faux) : c'est le bon réglage pour un rôle de clan, qui perdrait tout sens
    s'il se récupérait en postant un emoji. L'étiquette AFK, elle, part TOUJOURS
    tout de suite — la garder ne punirait pas le membre, elle l'empêcherait
    simplement de voir le serveur.
    """
    member = fiche["member"]
    res = {"etiquette": False, "rendus": [], "a_valider": False, "doux_efface": False}
    try:
        res["etiquette"] = await niv.retirer_niveaux(guild, member, cfg_act)

        if fiche["seuils"].get("restitution_auto", True):
            r = await niv.rendre_tous_les_roles(guild, member, cfg_act)
            res["rendus"] = r["rendus"]
        else:
            #  On ne rend rien, mais seulement s'il y a quelque chose à rendre :
            #  prévenir le staff pour un membre qui n'a rien perdu ferait du bruit
            #  et finirait par faire ignorer les vraies demandes.
            res["a_valider"] = await _a_des_roles_en_attente(guild, member)

        #  ⚠️ ON N'EFFACE L'ARDOISE QUE D'UN MEMBRE REDEVENU ACTIF.
        #  `revenus` contient désormais aussi des membres encore « doux » qu'on
        #  vient seulement de démasquer. Leur remettre le compteur à zéro
        #  rouvrirait exactement le contournement que `doux_max` referme :
        #  poster une fois par semaine suffirait à ne jamais monter d'un palier.
        if fiche.get("palier", "actif") == "actif" and fiche.get("doux_deja"):
            await activite.remettre_doux(guild.id, member.id)
            res["doux_efface"] = True
    except Exception as ex:
        _log(f"[activite traiter_retour {member.id}] {ex}")
    return res


async def _a_des_roles_en_attente(guild, member) -> bool:
    """Ce membre a-t-il des rôles retirés qui n'attendent qu'un accord ?"""
    try:
        async with activite._get_db() as db:
            async with db.execute(
                "SELECT roles_retires FROM activite_etat WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
        return bool(row and row[0] and json.loads(row[0]))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Application des paliers
# ═══════════════════════════════════════════════════════════════════════════════

async def appliquer_doux(guild, fiches: list, cfg_act: dict,
                         budget: float) -> dict:
    """Palier « doux » : pose l'étiquette « peu actif ». AUCUNE sanction.

    ⚠️ POURQUOI CETTE ÉTIQUETTE EXISTE. Le message de ce palier listait les
    membres un par un : 30 mentions puis « +929 » chez le propriétaire, pour
    959 personnes. Sa demande du 20/08 : « au lieu de mentionner 900 ou 1000
    personnes, tu mentionnes un rôle ». Un rôle porté par tout le monde se
    mentionne en un caractère et touche exactement les mêmes gens.

    ⚠️ CE RÔLE NE MASQUE RIEN et ne retire rien. Il ne change pas les
    permissions du membre — c'est une étiquette, pas une punition.

    ⚠️ LE BUDGET EST EN SECONDES, ET IL EST PARTAGÉ AVEC LES RETRAITS.
    Discord n'a aucune API d'attribution en masse : c'est un appel par membre.
    On cadence sous le seau (`PAUSE_ENTRE_ETIQUETTES`) plutôt que de le
    saturer, et on s'arrête quand le budget est épuisé — le reste attend le
    passage suivant. Rend le budget restant dans `res["budget"]`.

    ⚠️ UN MEMBRE QUI PORTE DÉJÀ L'ÉTIQUETTE NE COÛTE NI APPEL NI PAUSE. C'est
    ce qui fait que seul le premier balayage est cher : en régime établi, ce
    budget n'est jamais entamé.
    """
    res = {"faits": 0, "echecs": 0, "ignores": 0, "reportes": 0,
           "budget": float(budget)}
    deja = {int(cfg_act.get("activite_role_doux") or 0)}
    for f in fiches:
        member = f["member"]
        #  Déjà étiqueté : rien à faire, et surtout aucun appel réseau.
        if any(r.id in deja for r in getattr(member, "roles", []) if r.id):
            res["ignores"] += 1
            continue
        if res["budget"] <= 0:
            res["reportes"] += 1
            continue
        #  Re-vérification de l'immunité JUSTE AVANT d'agir, comme les autres
        #  paliers : le classement peut dater de quelques secondes.
        if not await activite.membre_concerne(member, cfg_act):
            res["ignores"] += 1
            continue
        try:
            if await niv.poser_niveau(guild, member, 0, cfg_act):
                res["faits"] += 1
            else:
                res["ignores"] += 1
        except Exception as ex:
            _log(f"[activite doux {member.id}] {ex}")
            res["echecs"] += 1
        await asyncio.sleep(activite.PAUSE_ENTRE_ETIQUETTES)
        res["budget"] -= activite.PAUSE_ENTRE_ETIQUETTES
    return res


async def appliquer_abandon(guild, fiches: list, cfg_act: dict,
                            budget: float) -> dict:
    """Palier 3 : pose l'étiquette « compte abandonné ». N'EXPULSE JAMAIS.

    Demande du propriétaire (20/08) : « le 3e, ça va être qu'ils sont
    considérés comme des comptes abandonnés […] plus aucune activité ». Cette
    phase n'avait aucun rôle, donc aucun moyen d'être mentionnée.

    ⚠️ CETTE ÉTIQUETTE MASQUE — c'est une action qui retire l'accès au serveur,
    pas une simple pastille comme « peu actif ». D'où le garde ci-dessous.

    ⚠️ ON NE MASQUE PAS QUELQU'UN QUI N'A JAMAIS ÉTÉ PRÉVENU.
    `verdict` est exclusif et teste l'expulsion EN PREMIER : un membre peut
    atterrir au palier 3 sans être jamais passé par les paliers 1 ou 2 — il
    suffit que le rationnement à 25 actions par passage l'ait fait franchir
    14 puis 21 jours sans qu'on le traite. Il n'a alors reçu aucun rappel, et
    lui retirer tout le serveur serait une sanction sans avertissement.
    On exige donc qu'il porte DÉJÀ une étiquette masquante. Les autres sont
    comptés dans `jamais_prevenus` — et ce compteur DOIT être affiché, sinon on
    remplace un masquage silencieux par un refus silencieux.

    Même budget en secondes que `appliquer_doux`, et il est CHAÎNÉ : cette
    fonction rend le reste dans `res["budget"]`, que l'appelant passe à
    `appliquer_doux`. Sans ce chaînage, chaque fonction repartirait de zéro et
    le budget réel du passage doublerait.
    """
    res = {"faits": 0, "echecs": 0, "ignores": 0, "reportes": 0,
           "jamais_prevenus": 0, "budget": float(budget)}
    cible_id = int(cfg_act.get("activite_role_abandon") or 0)
    if not cible_id:
        res["ignores"] = len(fiches)
        return res
    prealables = {int(cfg_act.get("activite_role_niveau1") or 0),
                  int(cfg_act.get("activite_role_niveau2") or 0)} - {0}
    for f in fiches:
        member = f["member"]
        roles = getattr(member, "roles", [])
        if any(r.id == cible_id for r in roles):
            res["ignores"] += 1           # déjà étiqueté : aucun appel réseau
            continue
        if prealables and not any(r.id in prealables for r in roles):
            res["jamais_prevenus"] += 1
            continue
        if res["budget"] <= 0:
            res["reportes"] += 1
            continue
        if not await activite.membre_concerne(member, cfg_act):
            res["ignores"] += 1
            continue
        try:
            if await niv.poser_niveau(guild, member, 3, cfg_act):
                res["faits"] += 1
            else:
                res["ignores"] += 1
        except Exception as ex:
            _log(f"[activite abandon {member.id}] {ex}")
            res["echecs"] += 1
        await asyncio.sleep(activite.PAUSE_ENTRE_ETIQUETTES)
        res["budget"] -= activite.PAUSE_ENTRE_ETIQUETTES
    return res


async def appliquer_rappels(guild, fiches: list, cfg_act: dict) -> dict:
    """Palier 1 : pose le rôle AFK. Le membre garde tout le reste.

    C'est ce rôle qui masque le serveur (voir `activite_niveaux`). Le membre
    n'est privé de rien d'autre : ses rôles, son historique, sa place sont
    intacts. Il ne voit plus que la liste des absents et le salon de retour.
    """
    res = {"faits": 0, "echecs": 0, "ignores": 0}
    for f in fiches:
        member = f["member"]
        #  Re-vérification de l'immunité JUSTE AVANT d'agir : le classement peut
        #  dater de quelques secondes, un membre a pu devenir admin entre-temps.
        if not await activite.membre_concerne(member, cfg_act):
            res["ignores"] += 1
            continue
        try:
            if await niv.poser_niveau(guild, member, 1, cfg_act):
                res["faits"] += 1
            else:
                res["ignores"] += 1
        except Exception as ex:
            _log(f"[activite rappel {member.id}] {ex}")
            res["echecs"] += 1
    return res


async def appliquer_retraits(guild, fiches: list, cfg_act: dict) -> dict:
    """Palier 2 : rôle AFK de second niveau, et retrait de TOUS les rôles.

    « Tous » au sens du propriétaire, avec les seules exceptions que Discord
    impose (rôles d'intégration, rôles au-dessus du bot) — voir
    `activite_niveaux.retirer_tous_les_roles`, qui les mémorise pour la suite.
    """
    res = {"faits": 0, "echecs": 0, "ignores": 0, "roles_retires": 0}
    for f in fiches:
        member, seuils = f["member"], f["seuils"]
        if not seuils.get("retirer_role", True):
            res["ignores"] += 1
            continue
        if not await activite.membre_concerne(member, cfg_act):
            res["ignores"] += 1
            continue
        try:
            #  ⚠️ GARDE-FOU AJOUTE LE 12/08/2026 — NE PAS LE RETIRER.
            #  `poser_niveau` echoue en silence quand aucun role AFK n'est
            #  configure, et le retrait de TOUS les roles s'executait quand meme.
            #  Dans la configuration PAR DEFAUT (les deux ids valent 0), allumer
            #  le systeme et attendre 14 jours depouillait donc chaque membre sans
            #  etiquette, sans masquage, et sans rien pour le signaler.
            #  On refuse : mieux vaut un palier qui n'agit pas qu'un membre
            #  depouille que personne ne peut rhabiller.
            if not await niv.poser_niveau(guild, member, 2, cfg_act):
                _log(f"[activite retrait {member.id}] aucun role AFK posable — "
                     f"retrait REFUSE (creez les roles dans le panneau Roles AFK)")
                res["ignores"] += 1
                res["sans_etiquette"] = res.get("sans_etiquette", 0) + 1
                continue
            r = await niv.retirer_tous_les_roles(guild, member, cfg_act)
            if r["ok"]:
                res["faits"] += 1
                res["roles_retires"] += len(r["retires"])
            else:
                res["echecs"] += 1
        except Exception as ex:
            _log(f"[activite retrait {member.id}] {ex}")
            res["echecs"] += 1
    return res


async def noter_rappels_doux(guild, fiches: list) -> int:
    """Compte un rappel doux de plus pour chacun — une fois par semaine au plus.

    C'est la seule écriture du palier « doux » : aucun rôle n'est touché, rien
    n'est retiré. Ce compteur est pourtant ce qui rend le système incontournable
    (voir l'en-tête d'`activite.py`).
    """
    n = 0
    for f in fiches:
        try:
            await activite.noter_doux(guild.id, f["member"].id, f["semaine"])
            n += 1
        except Exception as ex:
            _log(f"[activite doux {f['member'].id}] {ex}")
    return n
