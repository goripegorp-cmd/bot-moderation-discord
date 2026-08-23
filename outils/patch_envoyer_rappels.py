"""Extrait l'envoi des rappels, et ferme le double ping structurel.

DEMANDE DU PROPRIÉTAIRE (20/08/2026)
    « Fais en sorte que […] je puisse renvoyer le message qui pique tout le
      monde […] Et que moi-même je puisse bien renvoyer les requêtes. »

⚠️ DÉFAUT BLOQUANT TROUVÉ EN CHEMIN — LE DOUBLE PING EXISTE DÉJÀ.
Les étiquettes (« peu actif », « AFK », « rôles retirés », « abandonné ») sont
GLOBALES au serveur. Mais la boucle d'envoi tourne PAR RÔLE SURVEILLÉ, et le
marqueur anti-doublon `derniere_semaine` est lui aussi PAR RÔLE SURVEILLÉ.

Conséquence : dès qu'un deuxième rôle est surveillé, le passage du dimanche
poste deux messages qui mentionnent LE MÊME rôle — et les deux marqueurs
restent verts, puisqu'ils protègent des groupes, pas une mention. Un marqueur
par groupe ne pourra jamais protéger une mention qui, elle, est commune à tous
les groupes. Sur 959 personnes, c'est le pire échec possible de la fonction.

DEUX VERROUS, ET IL FAUT LES DEUX :
  · `_pingues` — intra-passage : un rôle déjà mentionné dans ce passage repasse
    en mode MUET pour les groupes suivants (message posté, compte affiché,
    zéro notification) ;
  · `activite_derniere_semaine` — inter-passage et inter-déclencheur : marqueur
    au niveau de la GUILDE, partagé avec le bouton de renvoi manuel. Sans lui,
    un renvoi manuel le mercredi puis le rappel automatique du dimanche
    pinguent deux fois la même semaine.
    Cette clé existait déjà dans CLES_DEFAUT et n'avait AUCUN lecteur — clé
    morte, donc aucune migration.

⚠️ POURQUOI EXTRAIRE PLUTÔT QUE DUPLIQUER. Le bouton doit emprunter le MÊME
chemin que la boucle. Une seconde implémentation divergerait au premier
correctif — c'est exactement ce qui est arrivé côté Roblox, où le bouton
« Relever maintenant » et la boucle appliquaient deux ordres différents.

Écrit dans un fichier puis exécuté (piège n°3 : les heredocs). `--apply`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "activite_passage.py"

VIEUX = '''    maintenant = cal.maintenant()
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
'''

NEUF = '''    _rap_env = await envoyer_rappels(guild, cfg_act, cl, dry_run=dry_run)
    rap["actions"]["messages_envoyes"] = _rap_env["envoyes"]
    rap["actions"]["semaine"] = _rap_env["semaine"]
    rap["actions"]["rappels_par_role"] = _rap_env["detail"]
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
'''

VIEUX_ROLES = '''        _r0 = guild.get_role(int(cfg_act.get("activite_role_doux", 0) or 0))
        _r1 = guild.get_role(int(cfg_act.get("activite_role_niveau1", 0) or 0))
        _r2 = guild.get_role(int(cfg_act.get("activite_role_niveau2", 0) or 0))'''

NEUF_ROLES = '''        _r0 = guild.get_role(int(cfg_act.get("activite_role_doux", 0) or 0))
        _r1 = guild.get_role(int(cfg_act.get("activite_role_niveau1", 0) or 0))
        _r2 = guild.get_role(int(cfg_act.get("activite_role_niveau2", 0) or 0))
        _r3 = guild.get_role(int(cfg_act.get("activite_role_abandon", 0) or 0))'''

VIEUX_VUES = '''        _roles = {"doux": _r0, "rappel": _r1, "retrait": _r2}
        vues = [msgs.construire(g[p], palier=p, salon_retour=salon_retour,
                                role_ping=_roles.get(p))
                for p in ("doux", "rappel", "retrait")]'''

NEUF_VUES = '''        _roles = {"doux": _r0, "rappel": _r1, "retrait": _r2,
                  "expulsion": _r3}
        #  ⚠️ UN RÔLE N'EST MENTIONNÉ QU'UNE FOIS PAR SEMAINE ET PAR SERVEUR,
        #  quel que soit le nombre de rôles surveillés et quel que soit le
        #  déclencheur. Au deuxième groupe, le même rôle repasse en MUET.
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
                _pingues.add(_r.id)'''

VIEUX_ENVOI = '''        abouti = False
        try:
            envoyes += await msgs.remplacer(guild, salon, cle, vues, cfg_act)
            abouti = True
        except Exception as ex:
            _log(f"[activite passage rappel {nom}] {ex} — semaine NON marquée, "
                 f"nouvelle tentative au prochain passage du jour")

        if abouti:
            try:
                await activite.ecrire_config_role(
                    guild.id, cle, derniere_semaine=semaine_courante)
            except Exception as ex:
                _log(f"[activite passage marque semaine {nom}] {ex}")'''

NEUF_ENVOI = '''        abouti = False
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
                _log(f"[activite passage marque semaine {nom}] {ex}")'''

VIEUX_FIN = '''    rap["actions"]["messages_envoyes"] = envoyes
    rap["actions"]["semaine"] = semaine_courante
    rap["actions"]["rappels_par_role"] = detail_rappels'''

NEUF_FIN = '''    #  ⚠️ LE MARQUEUR DE GUILDE — il ferme le double ping entre déclencheurs.
    #  Sans lui, un renvoi manuel le mercredi puis le rappel automatique du
    #  dimanche mentionnent deux fois les mêmes centaines de personnes.
    if _pingues and not dry_run:
        try:
            await activite._db_set(guild.id, "activite_derniere_semaine",
                                   semaine_courante)
        except Exception as ex:
            _log(f"[activite marque semaine guilde] {ex}")

    return {"envoyes": envoyes, "detail": detail_rappels,
            "semaine": semaine_courante, "pingues": len(_pingues)}'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}
    if "async def envoyer_rappels" in src:
        print("❌ déjà appliqué.")
        return 1

    neuf = src
    for nom, a, b in (("tete", VIEUX, NEUF), ("roles", VIEUX_ROLES, NEUF_ROLES),
                      ("vues", VIEUX_VUES, NEUF_VUES),
                      ("envoi", VIEUX_ENVOI, NEUF_ENVOI),
                      ("fin", VIEUX_FIN, NEUF_FIN)):
        if neuf.count(a) != 1:
            print(f"❌ ancre « {nom} » trouvée {neuf.count(a)} fois — abandon.")
            return 1
        neuf = neuf.replace(a, b, 1)

    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse l.{ex.lineno} : {ex.msg}")
        return 1
    apres = {getattr(n, "name", None) for n in arbre.body}
    if avant - apres:
        print(f"❌ symboles perdus : {avant - apres}")
        return 1
    if "envoyer_rappels" not in apres:
        print("❌ envoyer_rappels n'est pas au niveau module.")
        return 1

    print(f"  activite_passage.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
