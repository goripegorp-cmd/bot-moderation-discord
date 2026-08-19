"""Cherche les NameError que `verif_noms.py` ne peut PAS voir : hors portée.

⚠️ LE TROU QUE CET OUTIL COMBLE, ET CE QU'IL A COÛTÉ
`verif_noms.py` met TOUS les noms liés du fichier dans un seul ensemble, sans
distinguer les portées. Un nom assigné n'importe où passe donc pour connu
partout. C'est délibéré — ça évite un déluge de faux positifs — mais ça laisse
passer exactement le cas suivant, trouvé en production le 19/08/2026 :

    async def _bg_comeback(m):
        if ok and amount > 0:        # ← ni l'un ni l'autre n'existe ICI
            await m.reply(f"… +{amount:,} coins de bienvenue.")

`ok` était assigné ligne 5210 dans une AUTRE fonction, `amount` ligne 40368
dans une classe. `verif_noms` : vert. La réalité : `NameError: name 'ok' is
not defined` à CHAQUE message de membre, une dizaine de fois par jour dans les
logs Railway, avalé par un `except` — donc invisible autrement.

C'est un résidu de purge : le calcul vivait dans le système de coins, retiré
avec l'animation ; l'annonce, elle, était restée. Le briefing du propriétaire
réclamait « l'équivalent pour les boucles sans .start() et les DynamicItem » ;
voici le troisième de la même famille.

MÉTHODE — une portée à la fois, comme Python
Pour chaque fonction (imbriquée comprise), un nom chargé est connu s'il est :
  · lié dans cette fonction (paramètre, assignation, for, with, except,
    comprehension, def/class imbriqué, import local, `global`/`nonlocal`) ;
  · lié dans une fonction ENGLOBANTE (fermeture) ;
  · un global du module, ou un builtin.
Sinon, c'est un NameError en puissance.

⚠️ CONSERVATEUR EXPRÈS. Le corps d'une classe n'est PAS une portée fermante
pour ses méthodes (Python non plus), mais on tolère ses noms pour ne pas
noyer le vrai signal. Les comprehensions sont traitées comme faisant partie de
leur fonction. Objectif : zéro faux positif sur 43 000 lignes, pour que la
sortie reste lisible et qu'on la regarde vraiment.

Usage :
    PYTHONIOENCODING=utf-8 python outils/verif_portees.py bot.py
"""
from __future__ import annotations

import ast
import builtins
import sys


def _lies_dans(noeud) -> set:
    """Les noms liés DIRECTEMENT dans cette portée, sans descendre dans les
    fonctions/classes imbriquées (elles ont la leur)."""
    lies = set()

    def cible(n):
        if isinstance(n, ast.Name):
            lies.add(n.id)
        elif isinstance(n, (ast.Tuple, ast.List)):
            for e in n.elts:
                cible(e)
        elif isinstance(n, ast.Starred):
            cible(n.value)

    args = getattr(noeud, "args", None)
    if isinstance(args, ast.arguments):
        for p in args.posonlyargs + args.args + args.kwonlyargs:
            lies.add(p.arg)
        if args.vararg:
            lies.add(args.vararg.arg)
        if args.kwarg:
            lies.add(args.kwarg.arg)

    def descendre(n, racine=False):
        #  On ne descend PAS dans une fonction/classe imbriquée : son nom est
        #  lié ici, son contenu appartient à sa propre portée.
        if not racine and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef, ast.Lambda)):
            if hasattr(n, "name"):
                lies.add(n.name)
            return
        if isinstance(n, (ast.Import, ast.ImportFrom)):
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
        elif isinstance(n, ast.comprehension):
            cible(n.target)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            lies.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            lies.update(n.names)
        elif isinstance(n, ast.NamedExpr):
            cible(n.target)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and getattr(n, "name", None):
            lies.add(n.name)
        for enfant in ast.iter_child_nodes(n):
            descendre(enfant)

    descendre(noeud, racine=True)
    return lies


def _charges_dans(noeud) -> list:
    """Les (nom, ligne) CHARGÉS directement dans cette portée."""
    out = []

    def descendre(n, racine=False):
        if not racine and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                         ast.ClassDef, ast.Lambda)):
            #  Les valeurs par défaut et décorateurs s'évaluent dans la portée
            #  PARENTE : on les regarde, pas le corps.
            for d in getattr(n, "decorator_list", []):
                descendre(d)
            a = getattr(n, "args", None)
            if isinstance(a, ast.arguments):
                for v in list(a.defaults) + [x for x in a.kw_defaults if x]:
                    descendre(v)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.append((n.id, n.lineno))
        for enfant in ast.iter_child_nodes(n):
            descendre(enfant)

    descendre(noeud, racine=True)
    return out


def main() -> int:
    fichier = sys.argv[1] if len(sys.argv) > 1 else "bot.py"
    src = open(fichier, encoding="utf-8").read()
    arbre = ast.parse(src)
    lignes = src.splitlines()

    globaux = _lies_dans(arbre) | set(dir(builtins)) | {
        "__file__", "__name__", "__doc__", "__builtins__"}

    trouves: list[tuple[str, int, str]] = []

    def visiter(noeud, englobantes: set, chemin: str):
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                nom = getattr(enfant, "name", "<lambda>")
                locaux = _lies_dans(enfant)
                visibles = globaux | englobantes | locaux
                for n, ligne in _charges_dans(enfant):
                    if n not in visibles:
                        trouves.append((n, ligne, f"{chemin}{nom}"))
                visiter(enfant, englobantes | locaux, f"{chemin}{nom}.")
            elif isinstance(enfant, ast.ClassDef):
                #  Tolérance : les noms du corps de classe restent visibles
                #  pour ses méthodes. Python ne le fait pas, mais l'inverse
                #  produirait des faux positifs sur les décorateurs et les
                #  annotations, et noierait le vrai signal.
                visiter(enfant, englobantes | _lies_dans(enfant),
                        f"{chemin}{enfant.name}.")
            else:
                visiter(enfant, englobantes, chemin)

    visiter(arbre, set(), "")

    if not trouves:
        print(f"  {fichier} : aucun nom hors portée. (NameError de fermeture OK.)")
        return 0

    par_nom: dict[str, list] = {}
    for n, ligne, ou in trouves:
        par_nom.setdefault(n, []).append((ligne, ou))

    print(f"  {fichier} : {len(par_nom)} nom(s) utilisé(s) HORS PORTÉE "
          f"— NameError à l'exécution :\n")
    for nom, usages in sorted(par_nom.items(), key=lambda kv: -len(kv[1])):
        print(f"    {nom}  —  {len(usages)} usage(s)")
        for ligne, ou in sorted(usages)[:4]:
            print(f"        l.{ligne} dans {ou}() : {lignes[ligne - 1].strip()[:80]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
