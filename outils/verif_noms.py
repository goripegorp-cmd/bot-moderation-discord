#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Détecteur de NameError avant le boot.

`ast.parse()` valide la SYNTAXE : il ne voit pas qu'un nom a disparu. C'est
exactement ce que la CI attrape avec son `import bot`, mais 3 minutes plus tard.
Ce script fait le même contrôle en local, en 5 secondes.

Principe : rassembler tout ce que le module DÉFINIT (imports, defs, classes,
affectations de niveau module, globals, boucles, with, compréhensions…), puis
lister les noms UTILISÉS qui n'y figurent pas et ne sont pas des builtins.

Faux positifs possibles (noms créés dynamiquement) : ils sont affichés, à trier
à l'œil. Un nom qui apparaît ici après une suppression est presque toujours réel.

Usage : PYTHONIOENCODING=utf-8 python3 outils/verif_noms.py [fichier]
"""
from __future__ import annotations

import ast
import builtins
import sys


def noms_lies(arbre: ast.Module) -> set[str]:
    """Tout ce que le module lie à un nom, à n'importe quelle profondeur."""
    lies: set[str] = set()

    def cible(n):
        if isinstance(n, ast.Name):
            lies.add(n.id)
        elif isinstance(n, (ast.Tuple, ast.List)):
            for e in n.elts:
                cible(e)
        elif isinstance(n, ast.Starred):
            cible(n.value)

    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lies.add(n.name)
            a = n.args if hasattr(n, "args") and isinstance(getattr(n, "args", None), ast.arguments) else None
            if a:
                for p in a.posonlyargs + a.args + a.kwonlyargs:
                    lies.add(p.arg)
                if a.vararg:
                    lies.add(a.vararg.arg)
                if a.kwarg:
                    lies.add(a.kwarg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                lies.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                cible(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            cible(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            cible(n.target)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                if it.optional_vars is not None:
                    cible(it.optional_vars)
        elif isinstance(n, (ast.comprehension,)):
            cible(n.target)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            lies.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            lies.update(n.names)
        elif isinstance(n, ast.Lambda):
            a = n.args
            for p in a.posonlyargs + a.args + a.kwonlyargs:
                lies.add(p.arg)
            if a.vararg:
                lies.add(a.vararg.arg)
            if a.kwarg:
                lies.add(a.kwarg.arg)
        elif isinstance(n, ast.NamedExpr):
            cible(n.target)
        elif isinstance(n, ast.MatchAs) and n.name:
            lies.add(n.name)
        elif isinstance(n, ast.MatchStar) and n.name:
            lies.add(n.name)

    return lies


def main() -> int:
    fichier = sys.argv[1] if len(sys.argv) > 1 else "bot.py"
    src = open(fichier, encoding="utf-8").read()
    arbre = ast.parse(src)
    lignes = src.splitlines()

    connus = noms_lies(arbre) | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}

    manquants: dict[str, list[int]] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in connus:
            manquants.setdefault(n.id, []).append(n.lineno)

    if not manquants:
        print(f"  {fichier} : aucun nom inconnu. (Contrôle de NameError OK.)")
        return 0

    print(f"  {fichier} : {len(manquants)} nom(s) utilisé(s) mais jamais défini(s) :\n")
    for nom, lns in sorted(manquants.items(), key=lambda kv: -len(kv[1])):
        print(f"    {nom}  —  {len(lns)} usage(s)")
        for l in sorted(lns)[:4]:
            print(f"        l.{l}: {lignes[l - 1].strip()[:92]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
