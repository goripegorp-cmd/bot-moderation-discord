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
           "plafond_declenche": False, "actions": {}}

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

    # ── 3. PLAFOND ──
    total_actions = len(cl["retrait"]) + len(cl["expulsion"])
    if total_actions > activite.PLAFOND_ACTIONS_PAR_PASSAGE:
        # ⚠️ NE PAS ASSOUPLIR. Ce plafond n'est pas une limite de débit, c'est un
        # détecteur de panne. Si des dizaines de membres basculent d'un coup, la
        # cause la plus probable n'est pas que le serveur s'est vidé cette nuit :
        # c'est que le suivi est cassé (base réinitialisée, horloge décalée,
        # système activé sur un serveur sans historique). Dans ce cas, agir
        # ferait des dégâts irréversibles — et « retirer tous les rôles » de
        # cinquante membres ne se rattrape pas à la main. On alerte, on ne
        # touche à rien.
        rap["plafond_declenche"] = True
        rap["raison"] = (
            f"{total_actions} actions demandées, plafond à "
            f"{activite.PLAFOND_ACTIONS_PAR_PASSAGE} — RIEN n'a été appliqué. "
            f"Vérifiez que le suivi tourne depuis assez longtemps.")
        return rap

    # ── 4. Les retours, avant tout le reste ──
    rendus, attentes = 0, []
    if not dry_run:
        for f in cl["revenus"]:
            try:
                r = await esc.traiter_retour(guild, f, cfg_act)
                if r["rendus"] or r["etiquette"]:
                    rendus += 1
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
        rap["actions"]["doux"] = await esc.noter_rappels_doux(guild, cl["doux"])

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
    maintenant = cal.maintenant()
    semaine_courante = cal.semaine(maintenant)
    envoyes = 0
    detail_rappels = []

    for cle, g in (cl.get("groupes") or {}).items():
        conf = g["conf"]
        if not conf["actif"]:
            continue
        if maintenant.weekday() != conf["jour_rappel"]:
            continue
        if conf["derniere_semaine"] == semaine_courante:
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
        vues = [msgs.construire(g[p], palier=p, salon_retour=salon_retour)
                for p in ("doux", "rappel", "retrait")]
        try:
            envoyes += await msgs.remplacer(guild, salon, cle, vues, cfg_act)
        except Exception as ex:
            _log(f"[activite passage rappel {nom}] {ex}")

        #  Marquer la semaine MÊME si aucun message n'est parti (personne
        #  d'absent) : sinon on retenterait à chaque passage de la journée.
        try:
            await activite.ecrire_config_role(
                guild.id, cle, derniere_semaine=semaine_courante)
        except Exception as ex:
            _log(f"[activite passage marque semaine {nom}] {ex}")

    rap["actions"]["messages_envoyes"] = envoyes
    rap["actions"]["semaine"] = semaine_courante
    rap["actions"]["rappels_par_role"] = detail_rappels

    # ── 8. Expulsions : PROPOSITION seulement ──
    # Le propriétaire a explicitement refusé l'expulsion automatique. Le bot ne
    # fait que signaler ; le panneau staff porte le bouton qui, lui, agit.
    rap["actions"]["a_expulser"] = len(cl["expulsion"])
    return rap


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
    if rap.get("plafond_declenche"):
        return f"🛑 **Passage interrompu par le garde-fou**\n{rap['raison']}"

    c = rap.get("classement", {})
    a = rap.get("actions", {})
    masq = a.get("masquage") or {}
    tete = "🔎 **Aperçu** (rien appliqué)" if rap.get("dry_run") else "✅ **Passage**"
    return (
        f"{tete}\n"
        f"👥 `{c.get('suivis', 0)}` suivi(s) · `{c.get('actifs', 0)}` à jour\n"
        f"👀 `{c.get('doux', 0)}` trop rares · "
        f"💤 `{c.get('rappel', 0)}` au rôle AFK · "
        f"🔒 `{c.get('retrait', 0)}` sans rôles · "
        f"🚪 `{c.get('expulsion', 0)}` proposé(s)\n"
        f"-# {c.get('revenus', 0)} retour(s) · "
        f"{a.get('montees', 0)} montée(s) · "
        f"{a.get('messages_envoyes', 0)} message(s) · "
        f"{masq.get('modifies', 0)} salon(s) masqué(s)"
    )
