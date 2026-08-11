#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Purge des commandes slash hors périmètre.

PIÈGE CENTRAL (HANDOFF.md §5.2) : une liste blanche par NOM SIMPLE (`set`, `add`,
`remove`, `list`, `reply`, `close`, `claim`) matche les sous-commandes de TOUS les
groupes. Cet outil ne raisonne donc QUE sur des identifiants QUALIFIÉS :
  · commande racine      -> "/nom"
  · sous-commande        -> "/groupe nom"
Un nom nu dans la liste blanche est REFUSÉ, pas interprété.

Ce qu'il fait :
  1. Recense les groupes (`x = app_commands.Group(name=…)`) et toutes les commandes.
  2. Supprime les commandes hors liste blanche (def + tous ses décorateurs).
  3. Supprime les groupes dont plus AUCUNE sous-commande n'est gardée, ainsi que
     leur `bot.tree.add_command(...)`.
  4. `ast.parse()` avant écriture, preview par défaut, liste affichée pour relecture.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/purge_commandes.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/purge_commandes.py --apply
"""
from __future__ import annotations

import ast
import sys

FICHIER = "bot.py"

# ═══════════════════════════════════════════════════════════════════════════════
#  LISTE BLANCHE — identifiants QUALIFIÉS uniquement.
#  Périmètre gardé : sécurité, sanctions, casier, logs de modération, tickets, infra.
# ═══════════════════════════════════════════════════════════════════════════════
GARDER = {
    # ── Racine ──
    "/signaler",         # signalement discret par un membre
    "/signaler-vocal",
    "/help",
    "/configure",
    "/afk",              # l'AFK reste : c'est de la présence, pas du jeu
    # ── /off : radiation totale d'un membre (sanction lourde) ──
    "/off on", "/off off", "/off list",
    # ── /bouclier : verrouillage du serveur (anti-raid manuel) ──
    "/bouclier on", "/bouclier off", "/bouclier secours",
    # ── /mod : sanctions + casier ──
    "/mod clear", "/mod warn", "/mod unwarn", "/mod mute", "/mod unmute",
    "/mod direction", "/mod undirection", "/mod active", "/mod infractions",
    "/mod note", "/mod ticketblacklist",
    # ── /ticket ──
    "/ticket search", "/ticket queue", "/ticket priority", "/ticket templates",
    "/ticket reply", "/ticket template_add", "/ticket template_remove",
    "/ticket stats", "/ticket auto_close_config",
    # ── /logs : salon de logs unifié ──
    "/logs setchannel", "/logs status", "/logs categories",
    # ── /owner : exploitation ──
    "/owner sync", "/owner mod_stats",
    # ── /server : observabilité = infra gardée (module `observability`) ──
    "/server anomalies", "/server history", "/server report", "/server retention",
}

# Groupes à conserver même si l'outil ne leur trouve aucune sous-commande gardée
# (aucun aujourd'hui, mais le garde-fou existe pour éviter une coupe surprise).
GROUPES_INTOUCHABLES: set[str] = set()


def isinstance_module(cle, arbre) -> bool:
    """Le bloc désigné par `cle` est-il le corps du module lui-même ?
    (Un module vidé n'a pas besoin de `pass` : il reste du code autour.)"""
    return cle[0] == id(arbre)


def deb_decorateurs(node) -> int:
    """Première ligne du bloc (décorateurs compris)."""
    return min([node.lineno] + [d.lineno for d in node.decorator_list])


def nom_groupe_de_decorateur(dec) -> str | None:
    """`@xxx_group.command(...)` -> 'xxx_group' ; sinon None."""
    f = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(f, ast.Attribute) and f.attr == "command" and isinstance(f.value, ast.Name):
        return f.value.id
    return None


def est_racine(dec) -> bool:
    """`@bot.tree.command(...)`."""
    f = dec.func if isinstance(dec, ast.Call) else dec
    return (isinstance(f, ast.Attribute) and f.attr == "command"
            and isinstance(f.value, ast.Attribute) and f.value.attr == "tree")


def kwarg(dec, cle) -> str | None:
    if not isinstance(dec, ast.Call):
        return None
    for kw in dec.keywords:
        if kw.arg == cle and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


def main() -> int:
    apply_ = "--apply" in sys.argv

    for q in GARDER:
        if not q.startswith("/"):
            raise SystemExit(f"ABANDON : « {q} » n'est pas un identifiant qualifié.")

    src = open(FICHIER, encoding="utf-8").read()
    lignes = src.splitlines(keepends=True)
    arbre = ast.parse(src)

    # ── 1. Les groupes déclarés au niveau module ────────────────────────────
    groupes: dict[str, dict] = {}
    for n in arbre.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            f = n.value.func
            nom_attr = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if nom_attr == "Group" and isinstance(n.targets[0], ast.Name):
                var = n.targets[0].id
                groupes[var] = {
                    "slash": kwarg(n.value, "name") or var,
                    "lineno": n.lineno, "end": n.end_lineno,
                    "cmds": [],
                }

    # ── 2. Toutes les commandes ─────────────────────────────────────────────
    #  Certaines sont IMBRIQUÉES (dans un `try:`, un `if`…). Les supprimer laisse
    #  un bloc vide → SyntaxError. On repère donc, pour chacune, le bloc parent et
    #  le nombre de frères, pour savoir s'il faudra laisser un `pass`.
    #  Un bloc peut contenir PLUSIEURS commandes, toutes condamnées : il se vide
    #  alors entièrement. On mémorise donc, pour chaque instruction, le bloc qui la
    #  porte, afin de savoir après coup si ce bloc perd la totalité de son contenu.
    bloc_de: dict[int, tuple] = {}      # id(stmt) -> (cle_bloc, est_module)
    contenu_bloc: dict[tuple, list] = {}
    for p in ast.walk(arbre):
        for champ in ("body", "orelse", "finalbody"):
            bloc = getattr(p, champ, None)
            if not isinstance(bloc, list) or not bloc:
                continue
            cle = (id(p), champ)
            contenu_bloc[cle] = [id(e) for e in bloc]
            for enfant in bloc:
                bloc_de[id(enfant)] = (cle, isinstance(p, ast.Module))
    parent_de = {k: (v[1], len(contenu_bloc[v[0]])) for k, v in bloc_de.items()}

    cmds = []
    for n in ast.walk(arbre):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in n.decorator_list:
            var = nom_groupe_de_decorateur(dec)
            if var and var in groupes:
                q = f"/{groupes[var]['slash']} {kwarg(dec, 'name') or n.name}"
                cmds.append({"q": q, "grp": var, "node": n,
                             "deb": deb_decorateurs(n), "fin": n.end_lineno,
                             "seul": parent_de.get(id(n), (True, 2))[1] == 1,
                             "module": parent_de.get(id(n), (True, 2))[0]})
                groupes[var]["cmds"].append(q)
                break
            if est_racine(dec):
                q = f"/{kwarg(dec, 'name') or n.name}"
                cmds.append({"q": q, "grp": None, "node": n,
                             "deb": deb_decorateurs(n), "fin": n.end_lineno,
                             "seul": parent_de.get(id(n), (True, 2))[1] == 1,
                             "module": parent_de.get(id(n), (True, 2))[0]})
                break

    connus = {c["q"] for c in cmds}
    fantomes = GARDER - connus
    if fantomes:
        print("⚠️  Dans la liste blanche mais INTROUVABLES (vérifier l'orthographe) :")
        for q in sorted(fantomes):
            print(f"      {q}")
        print()

    a_couper = [c for c in cmds if c["q"] not in GARDER]
    gardees = [c for c in cmds if c["q"] in GARDER]

    # ── 3. Groupes entièrement vidés ────────────────────────────────────────
    grp_vides = [
        var for var, g in groupes.items()
        if var not in GROUPES_INTOUCHABLES
        and not any(q in GARDER for q in g["cmds"])
    ]

    # `bot.tree.add_command(<var>)` des groupes vidés.
    #  Plusieurs sont enveloppés dans un `try:` dont ils sont l'UNIQUE contenu :
    #  retirer la seule ligne laisserait un `try:` vide. On remonte donc au bloc
    #  englobant et on supprime le try/except entier.
    add_cmds = []          # (deb, fin, var)
    for p in ast.walk(arbre):
        for champ in ("body", "orelse", "finalbody"):
            bloc = getattr(p, champ, None)
            if not isinstance(bloc, list):
                continue
            for stmt in bloc:
                cibles = [
                    n for n in ast.walk(stmt)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "add_command" and n.args
                    and isinstance(n.args[0], ast.Name) and n.args[0].id in grp_vides
                ]
                if not cibles:
                    continue
                var = cibles[0].args[0].id
                if (isinstance(stmt, ast.Try) and len(stmt.body) == 1
                        and any(isinstance(n, ast.Call) for n in ast.walk(stmt.body[0]))):
                    add_cmds.append((stmt.lineno, stmt.end_lineno, var))
                elif isinstance(stmt, ast.Expr):
                    add_cmds.append((stmt.lineno, stmt.end_lineno, var))
    # dédoublonne (un try peut être vu par plusieurs chemins de walk)
    add_cmds = sorted(set(add_cmds))

    # ── Rapport ─────────────────────────────────────────────────────────────
    print(f"── Purge des commandes ─────────────────────────────────────────")
    print(f"  recensées : {len(cmds)}  ·  gardées : {len(gardees)}  ·  coupées : {len(a_couper)}")
    print(f"  groupes : {len(groupes)}  ·  entièrement vidés : {len(grp_vides)}")

    print("\n  GARDÉES :")
    for c in sorted(gardees, key=lambda x: x["q"]):
        print(f"      {c['q']}")

    print("\n  COUPÉES :")
    par_grp: dict[str, list] = {}
    for c in a_couper:
        par_grp.setdefault(c["grp"] or "(racine)", []).append(c)
    for grp in sorted(par_grp):
        total = sum(c["fin"] - c["deb"] + 1 for c in par_grp[grp])
        print(f"    · {grp} — {len(par_grp[grp])} commande(s), {total} lignes")
        for c in sorted(par_grp[grp], key=lambda x: x["q"]):
            print(f"        {c['q']:38} l.{c['deb']}-{c['fin']}")

    if grp_vides:
        print("\n  GROUPES SUPPRIMÉS (plus aucune sous-commande gardée) :")
        for var in sorted(grp_vides):
            print(f"      {var:24} /{groupes[var]['slash']}")

    # ── Découpe, de la fin vers le début ────────────────────────────────────
    #  Une commande imbriquée SEULE dans son bloc laisse un `try:` vide si on la
    #  retire : on met un `pass` à sa place, à l'indentation de sa définition.
    supprimes = {id(c["node"]) for c in a_couper}
    blocs_vides = {
        cle for cle, membres in contenu_bloc.items()
        if membres and all(m in supprimes for m in membres)
        and not isinstance_module(cle, arbre)
    }
    # La première commande (dans l'ordre du fichier) de chaque bloc vidé porte le `pass`.
    porte_pass: set[int] = set()
    for cle in blocs_vides:
        membres = [c for c in a_couper if bloc_de.get(id(c["node"]), (None,))[0] == cle]
        if membres:
            porte_pass.add(id(min(membres, key=lambda c: c["deb"])["node"]))
    for c in a_couper:
        c["seul"] = id(c["node"]) in porte_pass

    imbriquees = [c for c in a_couper if not c["module"]]
    if imbriquees:
        print(f"\n  ⚠️  {len(imbriquees)} commande(s) imbriquée(s) (dans un try/if) :")
        for c in imbriquees:
            print(f"      {c['q']:38} l.{c['deb']}  {'bloc vidé → pass' if c['seul'] else ''}")

    plages = [(c["deb"], c["fin"], c) for c in a_couper]
    plages += [(groupes[v]["lineno"], groupes[v]["end"], None) for v in grp_vides]
    plages += [(a, b, None) for a, b, _ in add_cmds]

    # Fusionne les plages qui se chevauchent (un groupe peut être défini dans la
    # même plage qu'une commande, selon la mise en forme).
    plages.sort(key=lambda p: -p[0])
    nouvelles = list(lignes)
    dernier_deb = None
    for a, b, c in plages:
        if dernier_deb is not None and b >= dernier_deb:
            b = dernier_deb - 1
            if b < a:
                continue
        if c is not None and c["seul"] and not c["module"]:
            # Bloc parent vidé : on laisse un `pass` à la place, même indentation.
            ligne = lignes[c["deb"] - 1]
            indent = ligne[:len(ligne) - len(ligne.lstrip())]
            nouvelles[a - 1:b] = [f"{indent}pass  # commande retirée (purge du périmètre)\n"]
        else:
            del nouvelles[a - 1:b]
        dernier_deb = a

    res = "".join(nouvelles)
    try:
        ast.parse(res)
    except SyntaxError as ex:
        raise SystemExit(f"ABANDON : le résultat ne se parse pas — {ex}")

    avant, apres = len(lignes), len(res.splitlines())
    print(f"\n  bot.py {avant} → {apres} lignes ({apres - avant:+d})")
    print("  ast.parse OK")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relire la liste, puis --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(res)
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
