#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sonde AST : pour une liste de classes de panneaux, extrait
   - la signature de __init__
   - la signature de render_to
   - les instanciations de MainPanelV2 / SecurityPanelV2 à l'intérieur (boutons « Retour »)
Lecture seule. Aucune écriture.

Usage : PYTHONIOENCODING=utf-8 python3 outils/sonde_panneaux.py [Classe ...]
"""
import ast
import sys

CIBLES_DEFAUT = [
    "MainPanelV2", "SecurityPanelV2", "ProtPanelV2", "ModerationPanelV2",
    "ImmunePanelV2", "TicketMainPanelV2", "LogsPanelV2", "AntiRaidPanelV2",
    "AfkRolePanelV2", "RgpdPanelV2",
]
# Panneaux dont on veut savoir qui les instancie (cibles des boutons « Retour »).
PARENTS = {"MainPanelV2", "SecurityPanelV2"}


def sig(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = fn.args
    parts = [p.arg for p in a.posonlyargs + a.args]
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    prefix = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {fn.name}({', '.join(parts)})"


def main() -> int:
    cibles = sys.argv[1:] or CIBLES_DEFAUT
    src = open("bot.py", encoding="utf-8").read()
    tree = ast.parse(src)

    classes = {
        n.name: n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name in cibles
    }

    for nom in cibles:
        node = classes.get(nom)
        print("=" * 78)
        if node is None:
            print(f"{nom} : INTROUVABLE au niveau module")
            continue
        print(f"{nom}  (l.{node.lineno}-{node.end_lineno}, {node.end_lineno - node.lineno + 1} lignes)")

        for m in node.body:
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in ("__init__", "render_to"):
                print(f"    l.{m.lineno:<6} {sig(m)}")

        # Qui ce panneau réinstancie-t-il parmi les parents ? (= son bouton Retour)
        retours = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in PARENTS:
                retours.append((sub.lineno, sub.func.id, len(sub.args)))
        if retours:
            for ln, cible, nargs in sorted(set(retours)):
                print(f"    RETOUR  l.{ln:<6} -> {cible}({nargs} args positionnels)")
        else:
            print("    RETOUR  (aucun vers MainPanelV2/SecurityPanelV2)")

    # Qui, dans TOUT bot.py, instancie chacune des cibles ?
    print("\n" + "=" * 78)
    print("APPELANTS (instanciation par NOM, tout bot.py)")
    lignes = src.splitlines()
    for nom in cibles:
        appels = [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == nom
        ]
        node = classes.get(nom)
        interne = range(node.lineno, node.end_lineno + 1) if node else range(0)
        externes = sorted({l for l in appels if l not in interne})
        internes = sorted({l for l in appels if l in interne})
        print(f"\n  {nom} : {len(externes)} externe(s), {len(internes)} interne(s)")
        for l in externes:
            print(f"      EXTERNE l.{l:<7} {lignes[l - 1].strip()[:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
