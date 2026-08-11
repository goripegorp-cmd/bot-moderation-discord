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
           "doux": [], "rappel": [], "retrait": [], "expulsion": []}
    if not await activite.actif(guild.id):
        return out

    #  L'âge du suivi se lit UNE FOIS pour toute la guilde, pas par membre : la
    #  même requête répétée mille fois est le genre de détail qui transforme un
    #  passage d'une seconde en passage d'une minute.
    suivi_jours = await activite.anciennete_du_suivi(guild.id)
    afk_ids = niv.ids_afk(cfg_act)
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
                                             suivi_jours=suivi_jours)
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

            doux_deja, _ = await activite.lire_doux(guild.id, member.id)
            palier = activite.verdict(mesure, conf, doux_deja)

            fiche = {"member": member, "jours": mesure["silence"],
                     "presents": mesure["presents"], "fenetre": mesure["fenetre"],
                     "role": role, "seuils": conf, "groupe": cle,
                     "doux_deja": doux_deja, "semaine": semaine}

            if palier == "actif":
                out["actifs"] += 1
                #  À jour, mais porte-t-il encore une étiquette d'absence ou
                #  a-t-il des rôles en attente ? C'est ici qu'on le repère, sans
                #  second balayage de la guilde.
                a_des_roles_afk = any(r.id in afk_ids for r in member.roles)
                if a_des_roles_afk or doux_deja:
                    out["revenus"].append(fiche)
                continue

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

        if fiche.get("doux_deja"):
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
            #  L'étiquette d'abord : si le retrait des rôles échoue à mi-chemin,
            #  le membre est au moins correctement signalé et masqué.
            await niv.poser_niveau(guild, member, 2, cfg_act)
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
