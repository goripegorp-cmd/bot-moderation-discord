"""Inventaire de TOUT ce qui relève des cadeaux, des boss et des événements.

Demande du propriétaire (15/08) : « Les gens peuvent gagner des cadeaux, y a des
salons qui apparaissent avec des événements comme gagner des cadeaux, combattre
des boss. Je veux que tu m'assures que tu m'enlèves bien tout ça. »

Cet outil ne supprime RIEN. Il dresse la carte, pour que la coupe qui suivra
soit bornée sur des ancres exactes et non sur « la prochaine ligne `async def` »
— la sur-coupe qui a déjà emporté 500 lignes une fois, et un `@tasks.loop`
l'autre.

Ce qu'il relève :
  · les modules du dépôt dont le NOM ou le CONTENU relève du registre ;
  · les fonctions de premier niveau de bot.py, et lesquelles sont des boucles ;
  · les `.start()` correspondants ;
  · les entrées de `_SUPERVISED_LOOP_NAMES`, y compris les MORTES (nom listé
    sans fonction) ;
  · les commandes slash et les groupes concernés ;
  · les tables SQL créées par ce code.

⚠️ LE PIÈGE QUE CET OUTIL SERT À NE PAS REFAIRE
`_iter_supervised_loops` a un BALAYAGE AUTO (source 3) qui ramasse tout objet
`tasks.Loop` déjà démarré, même absent de `_SUPERVISED_LOOP_NAMES`. Retirer le
nom de la liste ne suffit donc PAS à débrancher une boucle : il faut retirer la
boucle ET son `.start()`. Le piège n°2 du dépôt est plus large qu'écrit.

Usage :
    PYTHONIOENCODING=utf-8 python outils/inventaire_evenements.py
    PYTHONIOENCODING=utf-8 python outils/inventaire_evenements.py --json
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import sys

BOT = "bot.py"

#  Le registre visé, en trois familles. Séparées parce qu'elles ne portent pas
#  le même mandat : les deux premières sont nommées mot pour mot par le
#  propriétaire, la troisième est le décor qui les entoure.
FAMILLES = {
    "cadeaux": [
        r"giveaway", r"cadeau", r"tirage", r"raffle", r"loot", r"reward_drop",
        r"treasure", r"capsule", r"gift",
    ],
    "boss": [
        r"world_boss", r"\bboss\b", r"combat", r"alliance_war", r"encounter",
        r"tag_royale", r"saga",
    ],
    "evenements": [
        r"event_engine", r"events_engine", r"event_followup", r"_event_",
        r"event_timeout", r"event_auto", r"stale_event", r"personal_event",
        r"light_events", r"sweepable_event", r"game_night", r"riddle",
        r"herald", r"showcase", r"chaos", r"ritual", r"golden_hour",
        r"camouflage", r"spotlight", r"npc_", r"mission", r"lore", r"codex",
        r"ambient", r"seasonal_title", r"daily_encounters", r"anniversary",
        r"coup_de_coeur", r"creator_of_month", r"milestone",
    ],
}

#  Ne JAMAIS classer ceci dans le registre, quoi que dise un motif : c'est de la
#  sécurité, du RGPD ou du socle. Un faux positif ici coûterait une protection.
INTOUCHABLE = {
    "raid_detector", "protection_guards", "antiscam", "trust_system",
    "behavior_guard", "behavior_anomaly", "insult_filter", "offtopic_filter",
    "grooming_detector", "nsfw_scan", "ocr_scan", "token_grabber",
    "webhook_leak", "webhook_tracker", "anti_token_leak", "compromised_detector",
    "honeypot", "delegations", "gdpr", "unified_logger", "permissions",
    "recidivism", "staff_sanction", "member_risk", "impersonation_detector",
    "ui_v2", "paths", "owner_ids", "diag", "error_logger", "i18n",
    # Réintroductions explicitement demandées — ROBLOX.md le dit noir sur blanc.
    "roblox_veille", "roblox_news", "roblox_panneau",
    "social_media", "social_zones", "social_match", "admin_panels_v2",
    "activite", "activite_calendrier", "activite_escalade", "activite_message",
    "activite_niveaux", "activite_panneau", "activite_passage",
    "activite_recompenses", "activite_textes",
}

MOTIFS = {f: re.compile("|".join(p), re.I) for f, p in FAMILLES.items()}


def famille_de(texte: str) -> str | None:
    for nom, motif in MOTIFS.items():
        if motif.search(texte):
            return nom
    return None


def _lire(chemin: str) -> str:
    return open(chemin, encoding="utf-8", errors="replace").read()


def modules_concernes() -> dict:
    """Modules dont le nom relève du registre, ou dont le contenu en est saturé."""
    out = {}
    for f in sorted(glob.glob("*.py")):
        mod = os.path.splitext(os.path.basename(f))[0]
        if mod in INTOUCHABLE or f == BOT:
            continue
        src = _lire(f)
        lignes = src.count("\n") + 1
        par_nom = famille_de(mod)
        #  Densité : un module qui parle SANS CESSE de boss en est un. Un module
        #  qui le mentionne trois fois est juste voisin.
        compte = {n: len(m.findall(src)) for n, m in MOTIFS.items()}
        total = sum(compte.values())
        densite = total / max(lignes, 1)
        if par_nom or densite > 0.02:
            out[mod] = {
                "fichier": f, "lignes": lignes,
                "famille_par_nom": par_nom,
                "occurrences": compte,
                "densite": round(densite, 4),
            }
    return out


def analyse_bot() -> dict:
    src = _lire(BOT)
    arbre = ast.parse(src)

    fonctions, boucles = {}, {}
    for n in arbre.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fam = famille_de(n.name)
        if not fam:
            continue
        est_boucle = any(
            (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "loop")
            or getattr(d, "attr", "") == "loop"
            for d in n.decorator_list)
        fiche = {"ligne": n.lineno, "fin": getattr(n, "end_lineno", None),
                 "famille": fam, "boucle": est_boucle,
                 "decorateurs": [ast.unparse(d) for d in n.decorator_list]}
        (boucles if est_boucle else fonctions)[n.name] = fiche

    #  Les `.start()` — sans eux une boucle ne tourne pas, avec eux le balayage
    #  auto la ressuscite même retirée du superviseur.
    starts = {}
    for m in re.finditer(r"^\s*(\w+)\.start\(\)", src, re.M):
        nom = m.group(1)
        if famille_de(nom):
            starts.setdefault(nom, []).append(src[:m.start()].count("\n") + 1)

    #  Le superviseur, et ses entrées mortes.
    supervises, morts = [], []
    bloc = re.search(r"_SUPERVISED_LOOP_NAMES = \[(.*?)^\]", src, re.S | re.M)
    if bloc:
        for nom in re.findall(r'"([^"]+)"', bloc.group(1)):
            if famille_de(nom):
                supervises.append(nom)
            if f"async def {nom}" not in src and f"def {nom}" not in src:
                morts.append(nom)

    #  Les commandes slash.
    commandes = []
    for m in re.finditer(r'@(\w+)\.command\(\s*name="([^"]+)"', src):
        if famille_de(m.group(2)) or famille_de(m.group(1)):
            commandes.append({"groupe": m.group(1), "nom": m.group(2),
                              "ligne": src[:m.start()].count("\n") + 1})

    #  Les tables créées par ce code.
    tables = sorted({
        t for t in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src)
        if famille_de(t)})

    return {"fonctions": fonctions, "boucles": boucles, "starts": starts,
            "supervises": supervises, "supervises_morts": morts,
            "commandes": commandes, "tables": tables}


def main() -> int:
    if not os.path.exists(BOT):
        print(f"❌ {BOT} introuvable — lancer depuis la racine du dépôt.")
        return 1

    mods = modules_concernes()
    bot = analyse_bot()

    if "--json" in sys.argv:
        print(json.dumps({"modules": mods, "bot": bot}, indent=2,
                         ensure_ascii=False))
        return 0

    print("═══ MODULES DU REGISTRE ═══")
    total_l = 0
    for mod, d in sorted(mods.items(), key=lambda kv: -kv[1]["lignes"]):
        total_l += d["lignes"]
        fam = d["famille_par_nom"] or f"densité {d['densite']}"
        print(f"  {mod:<26} {d['lignes']:>6} l.   [{fam}]")
    print(f"  → {len(mods)} module(s), {total_l} lignes\n")

    print("═══ DANS bot.py ═══")
    print(f"  boucles          : {len(bot['boucles'])}")
    for nom, d in sorted(bot["boucles"].items(), key=lambda kv: kv[1]["ligne"]):
        s = bot["starts"].get(nom)
        print(f"      {nom:<34} l.{d['ligne']:<6} start={s or '❌ AUCUN'}")
    print(f"  fonctions        : {len(bot['fonctions'])}")
    print(f"  commandes slash  : {len(bot['commandes'])}")
    for c in bot["commandes"]:
        print(f"      /{c['groupe']} {c['nom']}  l.{c['ligne']}")
    print(f"  tables SQL       : {bot['tables']}")
    print(f"  supervisées      : {len(bot['supervises'])}")

    if bot["supervises_morts"]:
        print(f"\n  ⚠️  {len(bot['supervises_morts'])} entrée(s) du superviseur "
              f"SANS fonction correspondante — purge déjà passée, nom resté :")
        for n in bot["supervises_morts"]:
            print(f"      {n}")

    print("\n  (inventaire seul — aucune écriture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
