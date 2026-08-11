"""activite_passage.py — Le passage quotidien : ce qui déclenche réellement les paliers.

Un seul point d'entrée : `passage(guild, bot, dry_run=False)`. Le panneau
l'appelle en `dry_run=True` pour l'aperçu, la boucle quotidienne en réel. Le
calcul est le MÊME dans les deux cas — ce que le staff voit est ce qui arrivera.

═══════════════════════════════════════════════════════════════════════════════
L'ORDRE, ET POURQUOI IL EST AINSI
═══════════════════════════════════════════════════════════════════════════════
1. Récompenses D'ABORD. Un membre actif doit voir son niveau monter avant qu'on
   parle des inactifs : sinon quelqu'un qui revient le jour du passage se fait
   compter parmi les absents avant d'être crédité de son retour.
2. Restitution des rôles ensuite : ceux qui sont revenus récupèrent leur rôle.
3. Classement, puis PLAFOND. Si le nombre d'actions dépasse le plafond, on
   n'agit sur PERSONNE — voir le commentaire du garde-fou plus bas.
4. Rappel hebdomadaire : seulement le jour choisi, pas tous les jours.
5. Retrait des rôles (palier 2).
6. Expulsions : JAMAIS appliquées ici. On poste une proposition au staff.
"""
from __future__ import annotations

import activite
import activite_calendrier as cal
import activite_escalade as esc
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
        if cfg_rec["activite_recompenses_enabled"]:
            for m in guild.members:
                if m.bot:
                    continue
                if dry_run:
                    continue
                r = await rec.mettre_a_jour(guild, m)
                if r["monte"] and r["niveau"] > 0:
                    montees.append((m, r["niveau"]))
    except Exception as ex:
        _log(f"[activite passage recompenses] {ex}")
    rap["actions"]["montees"] = len(montees)

    # ── 2. Ceux qui sont revenus récupèrent leur rôle ──
    rendus = 0
    if not dry_run:
        for m in guild.members:
            try:
                jours = await activite.jours_inactif(guild.id, m)
                if jours is not None and jours == 0:
                    if await esc.rendre_roles(guild, m):
                        rendus += 1
            except Exception as ex:
                _log(f"[activite passage restitution] {ex}")
    rap["actions"]["roles_rendus"] = rendus

    # ── 3. Classement + PLAFOND ──
    cl = await esc.classer(guild)
    rap["classement"] = {
        "suivis": cl["suivis"], "actifs": cl["actifs"],
        "rappel": len(cl["rappel"]), "retrait": len(cl["retrait"]),
        "expulsion": len(cl["expulsion"]), "roles": len(cl.get("groupes") or {}),
    }
    rap["fiches"] = cl

    total_actions = len(cl["retrait"]) + len(cl["expulsion"])
    if total_actions > activite.PLAFOND_ACTIONS_PAR_PASSAGE:
        # ⚠️ NE PAS ASSOUPLIR. Ce plafond n'est pas une limite de débit, c'est un
        # détecteur de panne. Si des dizaines de membres basculent d'un coup, la
        # cause la plus probable n'est pas que le serveur s'est vidé cette nuit :
        # c'est que le suivi est cassé (base réinitialisée, horloge décalée,
        # système activé sur un serveur sans historique). Dans ce cas, agir
        # ferait des dégâts irréversibles. On alerte et on ne touche à rien.
        rap["plafond_declenche"] = True
        rap["raison"] = (
            f"{total_actions} actions demandées, plafond à "
            f"{activite.PLAFOND_ACTIONS_PAR_PASSAGE} — RIEN n'a été appliqué. "
            f"Vérifiez que le suivi tourne depuis assez longtemps.")
        return rap

    # ── 4. Rappel hebdomadaire — PAR RÔLE, chacun sur son rythme ──
    #  Chaque rôle a SON salon, SON jour et SON marqueur de semaine. Deux rôles
    #  peuvent donc être relancés à des jours différents, dans des salons
    #  différents, sans jamais se mélanger.
    #
    #  ⚠️ Le marqueur par rôle n'est pas un luxe : la boucle passe toutes les 6 h.
    #  Sans lui, le rappel partirait QUATRE fois le jour choisi. Et un marqueur
    #  global ferait qu'un rôle relancé le lundi empêcherait celui du vendredi.
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
                f"{nom} : {len(g['rappel'])} + {len(g['retrait'])} à relancer")
            continue

        for fiches, avec_retrait in ((g["rappel"], False), (g["retrait"], True)):
            txt = esc.texte_rappel(fiches, salon_retour, avec_retrait=avec_retrait)
            if not txt:
                continue
            try:
                await salon.send(txt)
                envoyes += 1
            except Exception as ex:
                _log(f"[activite passage rappel {nom}] {ex}")

        #  Marquer la semaine MÊME si aucun message n'est parti (personne
        #  d'inactif) : sinon on retenterait à chaque passage de la journée.
        try:
            await activite.ecrire_config_role(
                guild.id, cle, derniere_semaine=semaine_courante)
        except Exception as ex:
            _log(f"[activite passage marque semaine {nom}] {ex}")

    rap["actions"]["messages_envoyes"] = envoyes
    rap["actions"]["semaine"] = semaine_courante
    rap["actions"]["rappels_par_role"] = detail_rappels

    # ── 5. Retrait des rôles ──
    if dry_run:
        rap["actions"]["retraits"] = {"faits": 0, "echecs": 0,
                                      "ignores": len(cl["retrait"]), "simule": True}
    else:
        rap["actions"]["retraits"] = await esc.appliquer_retraits(guild, cl["retrait"])

    # ── 6. Expulsions : PROPOSITION seulement ──
    # Le propriétaire a explicitement refusé l'expulsion automatique. Le bot ne
    # fait que signaler ; le panneau staff porte le bouton qui, lui, agit.
    rap["actions"]["a_expulser"] = len(cl["expulsion"])
    return rap


def resume_texte(rap: dict) -> str:
    """Rapport lisible, pour le salon staff ou le panneau."""
    if not rap.get("actif"):
        return f"⚪ Système inactif — {rap.get('raison', '')}"
    if rap.get("plafond_declenche"):
        return f"🛑 **Passage interrompu par le garde-fou**\n{rap['raison']}"

    c = rap.get("classement", {})
    a = rap.get("actions", {})
    tete = "🔎 **Aperçu** (rien appliqué)" if rap.get("dry_run") else "✅ **Passage quotidien**"
    return (
        f"{tete}\n"
        f"👥 `{c.get('suivis', 0)}` membre(s) suivi(s) · `{c.get('actifs', 0)}` à jour\n"
        f"👋 `{c.get('rappel', 0)}` à relancer · "
        f"🔻 `{c.get('retrait', 0)}` au retrait de rôle · "
        f"🚪 `{c.get('expulsion', 0)}` proposé(s) à l'expulsion\n"
        f"-# {a.get('montees', 0)} montée(s) de niveau · "
        f"{a.get('roles_rendus', 0)} rôle(s) rendu(s) · "
        f"{a.get('messages_envoyes', 0)} message(s) envoyé(s)"
    )
