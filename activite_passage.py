"""activite_passage.py — Le passage : ce qui déclenche réellement les paliers.

Un seul point d'entrée : `passage(guild, dry_run=False)`. Le panneau l'appelle en
`dry_run=True` pour l'aperçu, la boucle en réel. Le calcul est le MÊME dans les
deux cas — ce que le staff voit est exactement ce qui arrivera.

═══════════════════════════════════════════════════════════════════════════════
L'ORDRE, ET POURQUOI IL EST AINSI
═══════════════════════════════════════════════════════════════════════════════
1. Récompenses D'ABORD. Un membre actif doit voir son niveau monter avant qu'on
   parle des absents : sinon quelqu'un qui revient le jour du passage se fait
   compter parmi eux avant d'être crédité de son retour.
2. Classement. Il produit aussi la liste des REVENUS — ceux qui portent encore
   une étiquette d'absence alors qu'ils sont à jour.
3. PLAFOND. Si le nombre d'actions dépasse la limite, on n'agit sur PERSONNE.
4. Les retours AVANT les paliers. Un membre revenu la nuit dernière doit
   récupérer ses rôles avant qu'on examine qui en perd — l'inverse le ferait
   dépouiller puis rhabiller dans le même passage, avec deux notifications
   contradictoires à la clé.
5. Les paliers : rôle AFK, puis retrait de tous les rôles.
6. Le masquage des salons, une fois les rôles posés.
7. Le rappel public, uniquement le jour choisi.
8. Les expulsions : JAMAIS appliquées ici. Une proposition au staff, rien de plus.
"""
from __future__ import annotations

import asyncio

import activite
import activite_calendrier as cal
import activite_escalade as esc
import activite_message as msgs
import activite_niveaux as niv
import activite_recompenses as rec

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


async def passage(guild, *, dry_run: bool = False) -> dict:
    """Un passage complet sur une guilde.

    Retourne un rapport détaillé, utilisable tel quel pour l'affichage :
    {"actif": bool, "raison": str, "classement": {...}, "actions": {...},
     "plafond_declenche": bool, "dry_run": bool}
    """
    rap = {"actif": False, "raison": "", "dry_run": dry_run,
           "suivi_muet": False, "quota_atteint": False, "anormal": False,
           "observation": 0, "reporte": {"rappel": 0, "retrait": 0},
           "actions": {}}

    if not await activite.actif(guild.id):
        rap["raison"] = "système désactivé, ou aucune cible désignée"
        return rap
    rap["actif"] = True

    cfg_act = await activite.config(guild.id)

    # ── 1. Récompenses d'abord (voir l'en-tête : l'ordre n'est pas anodin) ──
    montees = []
    try:
        cfg_rec = await rec.config(guild.id)
        if cfg_rec["activite_recompenses_enabled"] and not dry_run:
            for m in guild.members:
                if m.bot:
                    continue
                r = await rec.mettre_a_jour(guild, m)
                if r["monte"] and r["niveau"] > 0:
                    montees.append((m, r["niveau"]))
    except Exception as ex:
        _log(f"[activite passage recompenses] {ex}")
    rap["actions"]["montees"] = len(montees)

    # ── 2. Classement ──
    cl = await esc.classer(guild)
    rap["classement"] = {
        "suivis": cl["suivis"], "actifs": cl["actifs"],
        "doux": len(cl["doux"]), "rappel": len(cl["rappel"]),
        "retrait": len(cl["retrait"]), "expulsion": len(cl["expulsion"]),
        "revenus": len(cl["revenus"]), "roles": len(cl.get("groupes") or {}),
    }
    rap["fiches"] = cl

    # ── 3. DÉTECTEUR DE PANNE, puis QUOTA ──
    #
    # ⚠️ CE BLOC A ÉTÉ REFAIT LE 12/08/2026 APRÈS UN INTERBLOCAGE EN PRODUCTION.
    # L'ancienne version comptait `retrait + expulsion` et faisait un `return`
    # si le total dépassait 25. Sur un serveur de 941 membres jamais observés,
    # elle affichait « 941 actions demandées » toutes les 6 heures, pour
    # toujours : ces anciennetés ne décroissent pas, donc le compte ne pouvait
    # jamais repasser sous 25. Et le `return` sautait AUSSI les retours, le
    # masquage et le rappel hebdomadaire — le garde-fou bloquait la réparation.
    #
    # Trois corrections, chacune pour une raison distincte :
    #   · la CAUSE est traitée en amont (`activite.observation_jours`) : le
    #     silence ne peut plus dépasser le temps d'observation réel ;
    #   · on ne compte plus l'EXPULSION, qui n'est qu'une proposition au staff
    #     et n'applique rien — la compter gonflait le total de non-actions ;
    #   · on RATIONNE au lieu d'avorter : les plus anciens d'abord, le reste au
    #     passage suivant. Le retard s'écoule ; il ne bloque plus.
    rap["observation"] = cl.get("observation", 0)

    if cl.get("suivi_muet"):
        # Journal totalement vide alors qu'on observe depuis des jours : sur un
        # serveur vivant c'est impossible. Suivi cassé, pas serveur endormi.
        # C'est le SEUL cas où l'on refuse encore d'agir en bloc.
        rap["suivi_muet"] = True
        rap["raison"] = (
            "aucune activité enregistrée alors que le suivi tourne depuis "
            f"{rap['observation']} jour(s) — les sondes ne captent rien. "
            "RIEN n'a été appliqué.")
        cl["doux"], cl["rappel"] = [], []
        cl["retrait"], cl["expulsion"] = [], []

    quota = activite.PLAFOND_ACTIONS_PAR_PASSAGE
    #  Seuls les paliers qui APPLIQUENT quelque chose entrent dans le quota.
    applicables = len(cl["retrait"]) + len(cl["rappel"])
    reporte = {"rappel": 0, "retrait": 0}
    if applicables > quota:
        #  Le retrait passe avant le rappel : c'est le palier le plus avancé,
        #  et laisser quelqu'un stagner à 30 jours pendant qu'on étiquette des
        #  absents de 7 jours n'aurait aucun sens. Les listes sont déjà triées
        #  du plus ancien au plus récent par `classer`.
        garde_retrait = cl["retrait"][:quota]
        reporte["retrait"] = len(cl["retrait"]) - len(garde_retrait)
        garde_rappel = cl["rappel"][:max(0, quota - len(garde_retrait))]
        reporte["rappel"] = len(cl["rappel"]) - len(garde_rappel)
        cl["retrait"], cl["rappel"] = garde_retrait, garde_rappel

        #  ⚠️ COHÉRENCE DES GROUPES — indispensable. Le rappel hebdomadaire est
        #  construit à partir de `cl["groupes"]`, pas des listes globales. Sans
        #  ce filtre, un membre REPORTÉ serait annoncé publiquement comme ayant
        #  perdu ses rôles alors qu'on n'y a pas touché.
        gardes = {f["member"].id for f in garde_retrait + garde_rappel}
        for g in (cl.get("groupes") or {}).values():
            for k in ("rappel", "retrait"):
                g[k] = [f for f in g[k] if f["member"].id in gardes]

    rap["quota_atteint"] = bool(reporte["rappel"] or reporte["retrait"])
    rap["reporte"] = reporte
    #  Signalement, plus blocage : si la moitié du serveur bascule d'un coup,
    #  le staff doit le savoir — mais le quota a déjà borné les dégâts à 25.
    rap["anormal"] = bool(cl["suivis"] and applicables > 0.5 * cl["suivis"])
    rap["classement"]["reporte"] = reporte["rappel"] + reporte["retrait"]

    # ── 4. Les retours, avant tout le reste ──
    rendus, attentes = 0, []
    #  ⚠️ UN SEUL BUDGET EN SECONDES POUR LES DEUX SENS.
    #  Poser et retirer une étiquette tapent le MÊME seau de débit Discord
    #  (même route, même guilde). Budgéter la pose et laisser le retrait libre
    #  reviendrait à ne rien budgéter du tout. Les retraits passent EN PREMIER :
    #  libérer quelqu'un prime toujours sur étiqueter quelqu'un d'autre.
    budget = activite.BUDGET_ETIQUETTES_PAR_PASSAGE
    if not dry_run:
        for f in cl["revenus"]:
            try:
                r = await esc.traiter_retour(guild, f, cfg_act)
                if r["rendus"] or r["etiquette"]:
                    rendus += 1
                    #  Seul un retour qui a VRAIMENT écrit coûte une pause : un
                    #  membre sans rien à changer ne consomme pas de budget.
                    await asyncio.sleep(activite.PAUSE_ENTRE_ETIQUETTES)
                    budget -= activite.PAUSE_ENTRE_ETIQUETTES
                if r["a_valider"]:
                    attentes.append(f["member"])
            except Exception as ex:
                _log(f"[activite passage retour] {ex}")

        #  Les retours qui demandent un accord : on prévient le staff UNE fois.
        #  Sans ce message, des rôles « à valider » resteraient retirés sans que
        #  personne ne sache qu'une demande attend — le membre croirait le
        #  système cassé, et le staff ne verrait rien passer.
        if attentes:
            salon = guild.get_channel(int(cfg_act.get("activite_salon_staff", 0) or 0))
            if salon is not None:
                lignes = [f"• {m.mention}" for m in attentes[:20]]
                if len(attentes) > 20:
                    lignes.append(f"-# … et {len(attentes) - 20} autre(s)")
                try:
                    await salon.send("\n".join(
                        ["## 🔙 Retours à valider",
                         "Ces membres sont de nouveau actifs. Leurs rôles ne "
                         "reviennent pas tout seuls — à vous de les rendre.",
                         ""] + lignes))
                except Exception as ex:
                    _log(f"[activite passage attentes] {ex}")

    rap["actions"]["retours"] = rendus
    rap["actions"]["retours_a_valider"] = len(attentes)

    # ── 5. Les paliers ──
    if dry_run:
        rap["actions"]["rappels"] = {"faits": 0, "ignores": len(cl["rappel"]),
                                     "echecs": 0, "simule": True}
        rap["actions"]["retraits"] = {"faits": 0, "ignores": len(cl["retrait"]),
                                      "echecs": 0, "roles_retires": 0, "simule": True}
        rap["actions"]["doux"] = len(cl["doux"])
    else:
        rap["actions"]["rappels"] = await esc.appliquer_rappels(
            guild, cl["rappel"], cfg_act)
        rap["actions"]["retraits"] = await esc.appliquer_retraits(
            guild, cl["retrait"], cfg_act)
        #  ⚠️ LE COMPTEUR DOUX REÇOIT LA LISTE COMPLÈTE, TOUJOURS.
        #  C'est l'horloge de l'escalade (trois rappels doux → palier 1). La
        #  faire dépendre d'un budget d'appels réseau ferait avancer l'escalade
        #  à des vitesses différentes selon le nombre de membres.
        rap["actions"]["doux"] = await esc.noter_rappels_doux(guild, cl["doux"])
        #  ⚠️ L'ABANDON D'ABORD, ET LE BUDGET EST CHAÎNÉ.
        #  L'ordre compte : si le palier « doux » passait en premier, il
        #  brûlerait les 240 s sur des centaines de membres au premier
        #  balayage et l'étiquette d'abandon ne serait jamais posée. Et le
        #  budget doit être TRANSMIS : deux appels partant chacun de 240 s
        #  doubleraient le débit réel du passage.
        _ab = await esc.appliquer_abandon(guild, cl["expulsion"], cfg_act, budget)
        rap["actions"]["abandon"] = _ab
        #  L'étiquette « peu actif », elle, coûte un appel par membre : elle
        #  prend ce qui reste du budget, et le reste attend le passage suivant.
        _et = await esc.appliquer_doux(guild, cl["doux"], cfg_act, _ab["budget"])
        rap["actions"]["etiquettes"] = _et
        rap["reporte"]["etiquettes"] = (_et.get("reportes", 0)
                                        + _ab.get("reportes", 0))

    # ── 6. Le masquage des salons ──
    #  Relancé à chaque passage exprès : un salon créé entre-temps, une
    #  surcharge modifiée à la main, et le masquage a un trou. L'opération est
    #  idempotente — sans changement, elle ne fait aucun appel réseau.
    try:
        rap["actions"]["masquage"] = await niv.appliquer_masquage(
            guild, cfg_act, dry_run=dry_run)
    except Exception as ex:
        _log(f"[activite passage masquage] {ex}")
        rap["actions"]["masquage"] = {"raison": str(ex)}

    # ── 7. Rappel hebdomadaire — PAR RÔLE, chacun sur son rythme ──
    #  Chaque rôle a SON salon, SON jour et SON marqueur de semaine. Deux rôles
    #  peuvent donc être relancés à des jours différents, dans des salons
    #  différents, sans jamais se mélanger.
    #
    #  ⚠️ Le marqueur par rôle n'est pas un luxe : la boucle passe toutes les 6 h.
    #  Sans lui, le rappel partirait QUATRE fois le jour choisi. Et un marqueur
    #  global ferait qu'un rôle relancé le dimanche empêcherait celui du mercredi.
    _rap_env = await envoyer_rappels(guild, cfg_act, cl, dry_run=dry_run)
    rap["actions"]["messages_envoyes"] = _rap_env["envoyes"]
    rap["actions"]["semaine"] = _rap_env["semaine"]
    rap["actions"]["rappels_par_role"] = _rap_env["detail"]

    # ── 8. Expulsions : PROPOSITION seulement ──
    # Le propriétaire a explicitement refusé l'expulsion automatique. Le bot ne
    # fait que signaler ; le panneau staff porte le bouton qui, lui, agit.
    #  ⚠️ Depuis le 20/08, ces membres reçoivent tout de même l'étiquette
    #  « compte abandonné » (étape 5) : c'est une étiquette mentionnable, pas
    #  une expulsion. Le bot ne met toujours personne dehors tout seul.
    rap["actions"]["a_expulser"] = len(cl["expulsion"])
    return rap


async def envoyer_rappels(guild, cfg_act: dict, cl: dict, *,
                          forcer: bool = False, dry_run: bool = False,
                          muet_force: bool = False) -> dict:
    """Poste les rappels d'un serveur. UN SEUL CHEMIN, boucle ET bouton.

    `forcer=True` ignore le jour de la semaine et le marqueur « déjà fait » —
    c'est le bouton de renvoi manuel. Il n'ignore JAMAIS `conf["actif"]` : un
    rôle suspendu reste suspendu, et le motif est affiché.

    `muet_force=True` poste les mêmes messages sans AUCUNE mention. C'est le
    bouton « Envoyer sans mentionner », à utiliser quand le rôle a déjà été
    mentionné cette semaine.

    ⚠️ IL REÇOIT `cl` DÉJÀ CLASSÉ, il ne reclasse pas. Le filtre de cohérence
    des groupes s'applique APRÈS le rationnement du quota : reclasser ici
    enverrait des membres qu'on a explicitement REPORTÉS, et le message
    annoncerait une action qui n'a pas eu lieu.

    Rend `{"envoyes": int, "detail": [str], "semaine": str, "pingues": int}`.
    """
    maintenant = cal.maintenant()
    semaine_courante = cal.semaine(maintenant)
    envoyes = 0
    detail_rappels = []
    _mention_muette = False

    #  ⚠️ LES DEUX VERROUS ANTI-DOUBLE-PING. Voir l'en-tête du correctif :
    #  l'étiquette est globale, la boucle et son marqueur sont par groupe.
    _pingues: set[int] = set()
    _deja_semaine = (str(cfg_act.get("activite_derniere_semaine") or "")
                     == semaine_courante)
    if _deja_semaine or muet_force:
        #  Déjà mentionnés cette semaine (par la boucle OU par le bouton) :
        #  on poste, on compte, on ne notifie personne.
        for _c in ("activite_role_doux", "activite_role_niveau1",
                   "activite_role_niveau2", "activite_role_abandon"):
            _id = int(cfg_act.get(_c) or 0)
            if _id:
                _pingues.add(_id)

    for cle, g in (cl.get("groupes") or {}).items():
        conf = g["conf"]
        if not conf["actif"]:
            detail_rappels.append(f"{cle} : rôle suspendu")
            continue
        if not forcer and maintenant.weekday() != conf["jour_rappel"]:
            continue
        if not forcer and conf["derniere_semaine"] == semaine_courante:
            continue          # déjà relancé cette semaine pour CE rôle

        salon = guild.get_channel(int(conf["salon_annonce"] or 0))
        salon_retour = guild.get_channel(int(conf["salon_retour"] or 0))
        nom = g["role"].name if g["role"] is not None else "tout le serveur"

        if salon is None:
            detail_rappels.append(f"{nom} : aucun salon d'annonce")
            continue
        if dry_run:
            detail_rappels.append(
                f"{nom} : {len(g['doux'])} doux + {len(g['rappel'])} absents "
                f"+ {len(g['retrait'])} retraits")
            continue

        #  Trois messages distincts, jamais fusionnés : « tu es un peu juste » et
        #  « tu as perdu tes rôles » lus dans le même bloc, et tout le monde
        #  retient le mauvais des deux.
        #  ⚠️ CHAQUE PALIER MENTIONNE SON PROPRE RÔLE.
        #  Le palier « rappel » vise les porteurs du 1er rôle d'absence, le
        #  palier « retrait » ceux du 2e. Le palier « doux » n'en a AUCUN : ces
        #  membres-là sont venus, on ne leur a rien posé, et les mentionner par
        #  un rôle qu'ils ne portent pas ne toucherait personne. Ils sont donc
        #  listés — ils sont peu nombreux par construction.
        #  ⚠️ ON CRÉE LE RÔLE MANQUANT ICI, AU LIEU D'ATTENDRE UN CLIC.
        #  Constaté sur capture du propriétaire le 30/08 : la carte « Presque »
        #  affichait « 39 membre(s) concerné(s) » SANS mentionner personne,
        #  pendant que « Absents » mentionnait bien son rôle. La cause n'était
        #  pas le rendu mais l'absence du rôle : `_muet` vaut vrai dès que le
        #  rôle est `None`, et la carte retombe alors sur le compte seul.
        #  `creer_role` n'était appelé QUE depuis un bouton du panneau — un
        #  serveur où personne ne clique n'a donc jamais ses étiquettes, et le
        #  système paraît cassé alors qu'il attend un geste que rien ne
        #  réclame. Sa demande est sans ambiguïté : « assure-toi que tout le
        #  monde ait bien un rôle ».
        _r0, _r1, _r2, _r3 = [
            await _role_ou_creer(guild, cfg_act, cle, niveau)
            for cle, niveau in (("activite_role_doux", 0),
                                ("activite_role_niveau1", 1),
                                ("activite_role_niveau2", 2),
                                ("activite_role_abandon", 3))]
        #  ⚠️ LE PALIER DOUX A DÉSORMAIS SON RÔLE — corrigé le 20/08/2026.
        #  Il était câblé à `None`, avec ce commentaire : « le palier doux n'en
        #  a AUCUN […] ils sont peu nombreux par construction ». L'hypothèse
        #  était fausse : chez le propriétaire ils étaient 959, affichés en
        #  30 mentions suivies d'un « +929 ». Sa demande, mot pour mot : « au
        #  lieu de mentionner 900 ou 1000 personnes, tu mentionnes un rôle ».
        _roles = {"doux": _r0, "rappel": _r1, "retrait": _r2,
                  "expulsion": _r3}
        #  ⚠️ UN RÔLE N'EST MENTIONNÉ QU'UNE FOIS PAR SEMAINE ET PAR SERVEUR,
        #  quel que soit le nombre de rôles surveillés et quel que soit le
        #  déclencheur. Au deuxième groupe, le même rôle repasse en MUET.
        #  ⚠️ « EST-CE QUE ÇA MENTIONNE VRAIMENT LES GENS ? » — la question du
        #  propriétaire, le 30/08, et la réponse n'est pas dans le message.
        #  Ces rôles sont créés `mentionable=False` À DESSEIN : personne d'autre
        #  que le bot ne doit pouvoir réveiller des centaines de gens. Mais
        #  alors `allowed_mentions(roles=True)` NE SUFFIT PAS — il faut que le
        #  bot porte « Mentionner @everyone, @here et tous les rôles ». Sans
        #  elle, la mention S'AFFICHE exactement pareil et NE NOTIFIE PERSONNE.
        #  Un rappel que personne ne reçoit, et rien à l'écran ne le disait.
        if not await peut_mentionner_un_role(guild):
            _log(f"[activite rappel] ⚠️ {guild.name} : il manque au bot la "
                 f"permission « Mentionner tous les rôles ». Les cartes vont "
                 f"AFFICHER la mention du rôle mais NE NOTIFIERONT PERSONNE. "
                 f"C'est la seule chose qui empêche le rappel d'atteindre les "
                 f"absents.")
            #  ⚠️ ET ON LE REMONTE AU STAFF, pas seulement dans les journaux.
            #  Une permission manquante qui ne se voit que dans Railway
            #  n'est jamais vue : le rappel a l'air parfait à l'écran.
            _mention_muette = True
            detail_rappels.append(
                "⚠️ mention MUETTE — il manque au bot « Mentionner tous les "
                "rôles » : les cartes s'affichent mais ne notifient personne")

        vues = []
        for p in ("doux", "rappel", "retrait", "expulsion"):
            _r = _roles.get(p)
            _muet = bool(_r is None or _r.id in _pingues)
            #  Le palier « expulsion » s'affiche sous le titre « comptes
            #  abandonnés » : c'est une étiquette, jamais une expulsion.
            _pal = "abandon" if p == "expulsion" else p
            vues.append(msgs.construire(
                g[p], palier=_pal, salon_retour=salon_retour,
                role_ping=(None if _muet else _r), muet=_muet))
            if _r is not None and g[p] and not _muet:
                _pingues.add(_r.id)
        #  ⚠️ ON NE BRÛLE LA SEMAINE QUE SI L'ENVOI A ABOUTI.
        #  La version précédente marquait la semaine dans TOUS les cas, y
        #  compris quand `remplacer` levait (salon interdit, message trop
        #  long, Discord en vrac) : l'exception était journalisée puis avalée,
        #  la semaine passait pour faite, et le rappel ne partait JAMAIS —
        #  chaque semaine, indéfiniment. Trouvé le 19/08 par un audit adverse.
        #
        #  ⚠️ « Aucun message envoyé » N'EST PAS un échec : quand personne
        #  n'est absent, `remplacer` rend 0 et c'est un succès — on marque,
        #  sinon on retenterait à chaque passage de la journée. C'est la
        #  distinction que l'ancien code ne faisait pas.
        abouti = False
        try:
            #  ⚠️ `purger_si_vide=False` SUR UN RENVOI MANUEL. `remplacer`
            #  supprime avant de poster : sans ce garde, cliquer « renvoyer »
            #  un jour où personne n'est absent VIDERAIT le salon en
            #  rapportant « 0 envoyé ».
            _res = await msgs.remplacer(guild, salon, cle, vues, cfg_act,
                                        purger_si_vide=not forcer)
            envoyes += len(_res["envoyes"])
            abouti = not _res["echecs"]
            if _res.get("raison"):
                detail_rappels.append(f"{nom} : {_res['raison']}")
            elif _res["echecs"]:
                detail_rappels.append(f"{nom} : envoi refusé — {_res['echecs'][0]}")
            else:
                detail_rappels.append(f"{nom} : {len(_res['envoyes'])} message(s)")
        except Exception as ex:
            _log(f"[activite passage rappel {nom}] {ex} — semaine NON marquée, "
                 f"nouvelle tentative au prochain passage du jour")

        #  ⚠️ ON NE MARQUE LA SEMAINE DU GROUPE QUE LE JOUR PRÉVU. Un renvoi
        #  manuel un mercredi ne doit pas consommer le rappel du dimanche.
        if abouti and maintenant.weekday() == conf["jour_rappel"]:
            try:
                await activite.ecrire_config_role(
                    guild.id, cle, derniere_semaine=semaine_courante)
            except Exception as ex:
                _log(f"[activite passage marque semaine {nom}] {ex}")

    #  ⚠️ LE MARQUEUR DE GUILDE — il ferme le double ping entre déclencheurs.
    #  Sans lui, un renvoi manuel le mercredi puis le rappel automatique du
    #  dimanche mentionnent deux fois les mêmes centaines de personnes.
    if _pingues and not dry_run:
        try:
            await activite._db_set(guild.id, "activite_derniere_semaine",
                                   semaine_courante)
        except Exception as ex:
            _log(f"[activite marque semaine guilde] {ex}")

    return {"envoyes": envoyes, "detail": detail_rappels,
            "mention_muette": _mention_muette,
            "semaine": semaine_courante, "pingues": len(_pingues)}


#  Retours déjà en cours de traitement, pour ne pas les relancer à chaque
#  message d'une rafale. Un membre qui revient écrit rarement une seule ligne.
_retours_en_cours: set[tuple[int, int]] = set()


async def retour_immediat(guild, member) -> bool:
    """Un membre étiqueté vient de se manifester : on le débloque TOUT DE SUITE.

    « S'il renvoie un message ou qu'il dit oui, je suis là par rapport au salon
    en question, alors ils regagnent tous ces rôles et ça revient à 0 pour lui. »

    Attendre le passage suivant — jusqu'à six heures — laisserait quelqu'un qui
    vient d'écrire dans le salon de retour face à un serveur toujours masqué. Il
    en conclurait que le système est cassé, et il aurait raison.

    Appelé depuis `on_message` derrière un test mémoire (`porte_une_etiquette`)
    qui coupe avant tout accès réseau pour l'immense majorité des messages.
    """
    cle = (guild.id, member.id)
    if cle in _retours_en_cours:
        return False
    _retours_en_cours.add(cle)
    try:
        cfg_act = await activite.config(guild.id)
        if not cfg_act.get("activite_enabled"):
            return False
        #  `role_surveille_du_membre` rend un OBJET rôle (ou None) ; la config,
        #  elle, se lit par identifiant. Passer l'objet tel quel retomberait
        #  silencieusement sur les réglages du serveur, et un rôle de clan avec
        #  restitution validée par le staff se serait rendu tout seul.
        role = activite.role_surveille_du_membre(member, cfg_act)
        conf = activite.config_du_role(
            cfg_act, str(role.id) if role is not None else activite.ROLE_TOUS)
        doux, _ = await activite.lire_doux(guild.id, member.id)
        fiche = {"member": member, "seuils": conf, "doux_deja": doux}
        r = await esc.traiter_retour(guild, fiche, cfg_act)
        return bool(r["etiquette"] or r["rendus"])
    except Exception as ex:
        _log(f"[activite retour_immediat] {ex}")
        return False
    finally:
        _retours_en_cours.discard(cle)


async def accueillir_revenant(guild, member) -> bool:
    """Un membre rejoint : était-il parti pour inactivité ? Alors on l'explique.

    Branché sur `on_member_join`. Fail-safe de bout en bout : ce message est un
    confort, il ne doit jamais retarder ni empêcher les contrôles d'arrivée
    (anti-raid, compte compromis) qui, eux, protègent le serveur.
    """
    try:
        cfg_act = await activite.config(guild.id)
        if not cfg_act.get("activite_message_retour", True):
            return False
        trace = await activite.etait_expulse(guild.id, member.id)
        if not trace or trace["prevenu"]:
            return False

        conf = activite.config_du_role(cfg_act, activite.ROLE_TOUS)
        salon = guild.get_channel(int(conf.get("salon_retour") or 0))
        envoye = await msgs.accueillir(member, conf, salon)
        #  Marqué prévenu même si le message privé n'est pas passé : réessayer à
        #  chaque arrivée d'un membre aux MP fermés ne ferait que du bruit dans
        #  les journaux, sans jamais aboutir.
        await activite.marquer_prevenu(guild.id, member.id)
        return envoye
    except Exception as ex:
        _log(f"[activite accueillir_revenant] {ex}")
        return False


def resume_texte(rap: dict) -> str:
    """Rapport lisible, pour le salon staff ou le panneau."""
    if not rap.get("actif"):
        return f"⚪ Système inactif — {rap.get('raison', '')}"
    if rap.get("suivi_muet"):
        return (f"🛑 **Suivi muet — rien n'a été appliqué**\n{rap['raison']}\n"
                f"-# Ouvrez 🔎 Aperçu : le diagnostic dit quelle source ne "
                f"capte pas.")

    c = rap.get("classement", {})
    a = rap.get("actions", {})
    masq = a.get("masquage") or {}
    rep = rap.get("reporte") or {}
    tete = "🔎 **Aperçu** (rien appliqué)" if rap.get("dry_run") else "✅ **Passage**"

    #  ⚠️ DEUX BLOCS DISTINCTS, ET C'EST VOLONTAIRE : l'ÉTAT (combien de membres
    #  sont dans chaque situation) n'est pas l'ACTION (combien ont été touchés
    #  ce passage). Les confondre est exactement ce qui rendait l'ancien message
    #  illisible : « 941 » se lisait comme « 941 personnes viennent de perdre
    #  leurs rôles » alors que rien n'avait été fait.
    lignes = [
        tete,
        f"👥 `{c.get('suivis', 0)}` suivi(s) · `{c.get('actifs', 0)}` à jour",
        f"**Situation** — 👀 `{c.get('doux', 0)}` trop rares · "
        f"💤 `{c.get('rappel', 0)}` à étiqueter · "
        f"🔒 `{c.get('retrait', 0)}` à dépouiller · "
        f"🚪 `{c.get('expulsion', 0)}` proposé(s)",
    ]

    if not rap.get("dry_run"):
        lignes.append(
            f"**Appliqué** — 💤 `{(a.get('rappels') or {}).get('faits', 0)}` "
            f"étiquette(s) · 🔒 `{(a.get('retraits') or {}).get('faits', 0)}` "
            f"dépouillé(s) · 🔙 `{a.get('retours', 0)}` retour(s)")

    if rap.get("quota_atteint"):
        lignes.append(
            f"⏳ **{rep.get('retrait', 0) + rep.get('rappel', 0)} reporté(s)** "
            f"au prochain passage — `{activite.PLAFOND_ACTIONS_PAR_PASSAGE}` "
            f"maximum à la fois, les plus anciens d'abord. "
            f"Rien n'est perdu, tout s'écoule.")
    if rap.get("anormal"):
        lignes.append("⚠️ Plus de la moitié des membres suivis bascule d'un "
                      "coup — vérifiez vos seuils avant de laisser filer.")

    lignes.append(
        f"-# observé depuis {rap.get('observation', 0)} j · "
        f"{a.get('montees', 0)} montée(s) · "
        f"{a.get('messages_envoyes', 0)} message(s) · "
        f"{masq.get('modifies', 0)} salon(s) masqué(s)")
    return "\n".join(lignes)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le salon AFK — « je suis là », et le salon reste propre
# ═══════════════════════════════════════════════════════════════════════════════

async def est_salon_afk(guild_id: int, salon_id: int) -> bool:
    """Ce salon est-il LE salon AFK de ce serveur ?

    Volontairement bon marché : c'est appelé sur CHAQUE message du serveur.
    `activite.config` passe par le cache de configuration, donc pas d'accès
    base dans le cas courant.
    """
    if not salon_id:
        return False
    try:
        c = await activite.config(guild_id)
        return int(c.get("activite_salon_afk", 0) or 0) == int(salon_id)
    except Exception:
        return False


async def nettoyer_message_afk(message) -> bool:
    """Efface le message d'un membre dans le salon AFK. Rend True si effacé.

    ⚠️ CE QUE CETTE FONCTION NE FAIT PAS, ET IL FAUT LE SAVOIR.
    Elle ne marque PAS l'activité et ne rend PAS les rôles : `on_message` le
    fait déjà pour TOUS les salons, avant d'arriver ici (voir `marquer_actif`
    et `retour_immediat`). Un salon AFK qui « rendrait actif » serait donc une
    fonction en double — et deux chemins qui font la même chose finissent
    toujours par diverger. Ici, on ne fait qu'une chose : garder le salon
    propre.

    ⚠️ ON RÉPOND AVANT D'EFFACER. Effacer sans un mot donnerait l'impression
    que le message n'est pas passé, et le membre réécrirait — soit exactement
    les « pavés de messages » que ce salon existe pour éviter. La confirmation
    s'efface elle aussi.

    Ne lève jamais : un défaut de permission ne doit pas casser `on_message`,
    qui traite TOUS les messages du serveur. Mais il est JOURNALISÉ — un salon
    AFK qui ne se nettoie pas en silence se remplirait pendant des semaines
    sans que personne ne sache pourquoi.
    """
    salon = getattr(message, "channel", None)
    guild = getattr(message, "guild", None)
    if salon is None or guild is None:
        return False
    #  Un message épinglé est une consigne du staff : on n'y touche pas.
    if getattr(message, "pinned", False):
        return False
    try:
        c = await activite.config(guild.id)
        delai = max(0, int(c.get("activite_afk_secondes", 8) or 0))
    except Exception:
        delai = 8

    #  ⚠️ LA PERMISSION SE VÉRIFIE AVANT, PAS APRÈS L'ÉCHEC. Sans ce contrôle,
    #  chaque message du salon lèverait un Forbidden attrapé plus bas, et le
    #  journal se remplirait d'une erreur par message au lieu d'un diagnostic.
    try:
        moi = guild.me
        if moi is not None and not salon.permissions_for(moi).manage_messages:
            _log(f"[activite salon_afk] ⚠️ il manque « Gérer les messages » "
                 f"dans #{getattr(salon, 'name', '?')} ({salon.id}) : les "
                 f"messages AFK ne seront PAS effacés et le salon va se "
                 f"remplir.")
            return False
    except Exception:
        pass

    accuse = None
    try:
        accuse = await salon.send(
            f"✅ {message.author.mention} — noté, tu es compté comme **actif**."
            f"\n-# Ce message et le tien s'effacent dans "
            f"{delai} seconde(s), pour garder le salon propre.",
            delete_after=float(delai) if delai else None)
    except Exception as ex:
        #  Pas d'accusé de réception possible : on efface quand même, c'est le
        #  cœur de la demande. Mais on le dit.
        _log(f"[activite salon_afk] accusé impossible dans "
             f"#{getattr(salon, 'name', '?')} : {type(ex).__name__}: {ex}")

    try:
        if delai:
            await asyncio.sleep(delai)
        await message.delete()
        return True
    except Exception as ex:
        _log(f"[activite salon_afk] suppression refusée dans "
             f"#{getattr(salon, 'name', '?')} ({getattr(salon, 'id', '?')}) : "
             f"{type(ex).__name__}: {ex}")
        #  L'accusé, lui, doit partir : le laisser seul serait pire que rien.
        if accuse is not None and not delai:
            try:
                await accuse.delete()
            except Exception:
                pass
        return False


async def _role_ou_creer(guild, cfg_act: dict, cle: str, niveau: int):
    """Le rôle d'un palier, CRÉÉ s'il manque. `None` si c'est impossible.

    ⚠️ POURQUOI CETTE FONCTION EXISTE — CAPTURE DU PROPRIÉTAIRE, 30/08/2026.
    Sa carte « 👀 Presque » annonçait « 39 membre(s) concerné(s) » sans
    mentionner personne, pendant que « 💤 Absents » mentionnait bien son rôle.
    Le rendu n'y était pour rien : `construire` passe en mode muet dès que le
    rôle vaut `None`, et affiche alors le compte seul. Le rôle « peu actif »
    n'existait tout simplement pas sur son serveur — parce que `creer_role`
    n'était appelé QUE depuis un bouton du panneau.
    Un système qui attend un clic que rien ne réclame paraît cassé. On crée
    donc à la demande, une seule fois, et on mémorise l'identifiant.

    ⚠️ ON N'ÉCRIT LA CONFIG QU'APRÈS UNE CRÉATION RÉUSSIE. Poser l'identifiant
    avant ferait pointer la config vers un rôle inexistant au prochain passage,
    et `get_role` rendrait `None` pour toujours sans jamais retenter.
    """
    try:
        rid = int(cfg_act.get(cle, 0) or 0)
    except (TypeError, ValueError):
        rid = 0
    if rid:
        r = guild.get_role(rid)
        if r is not None:
            return r
        #  L'identifiant est en config mais le rôle a été supprimé à la main :
        #  on repart de zéro plutôt que de rester muet indéfiniment.
        _log(f"[activite roles] le rôle {cle}={rid} n'existe plus sur "
             f"{guild.name} — recréation")

    #  ⚠️ SANS « Gérer les rôles », inutile d'essayer : l'API refusera et on
    #  écrirait une ligne d'erreur à chaque passage. On le dit UNE fois, avec
    #  la cause exacte.
    try:
        if not guild.me.guild_permissions.manage_roles:
            _log(f"[activite roles] ⚠️ il manque « Gérer les rôles » sur "
                 f"{guild.name} : l'étiquette « {cle} » ne peut pas être "
                 f"créée, et les absents concernés ne seront donc PAS "
                 f"mentionnés — seulement comptés.")
            return None
    except Exception:
        pass

    r = await niv.creer_role(guild, niveau)
    if r is None:
        return None
    try:
        await activite._db_set(guild.id, cle, r.id)
    except Exception as ex:
        #  Le rôle existe mais la config ne le sait pas : au prochain passage
        #  on en créerait un second. Mieux vaut le supprimer et retenter.
        _log(f"[activite roles] config non écrite pour {cle} : {ex} — "
             f"le rôle créé est retiré pour éviter les doublons")
        try:
            await r.delete(reason="Système d'activité : config non écrite")
        except Exception:
            pass
        return None
    _log(f"[activite roles] rôle « {r.name} » créé sur {guild.name} "
         f"({cle}={r.id})")
    return r


async def peut_mentionner_un_role(guild) -> bool:
    """Le bot peut-il RÉELLEMENT notifier un rôle non mentionnable ?

    ⚠️ LA QUESTION EXACTE DU PROPRIÉTAIRE : « est-ce que ça mentionne vraiment
    les gens ? » La réponse n'est pas dans le message, elle est dans une
    permission. Les rôles d'inactivité sont créés `mentionable=False` — à
    dessein, pour que personne d'autre que le bot ne puisse réveiller des
    centaines de gens. Dans ce cas, `allowed_mentions(roles=True)` ne suffit
    PAS : il faut que le bot porte « Mentionner @everyone, @here et tous les
    rôles ». Sans elle, la mention S'AFFICHE et NE NOTIFIE PERSONNE — un
    rappel que personne ne reçoit, et rien à l'écran ne le dit.
    """
    try:
        return bool(guild.me.guild_permissions.mention_everyone)
    except Exception:
        return False
