"""Trouve les boucles qui ne tourneront jamais — et celles qui ont perdu leur décorateur.

⚠️ LE TROU QUE CET OUTIL COMBLE — RÉCLAMÉ NOIR SUR BLANC PAR LE HANDOFF
    « Reste à écrire l'équivalent pour les `@tasks.loop` sans `.start()` et
      pour les `DynamicItem` non réenregistrés — ce sont les deux mêmes trous,
      et ils ont chacun coûté une découverte tardive. »
Le second est fermé par `verif_boutons_persistants.py`. Voici le premier.

CE QUE ÇA A DÉJÀ COÛTÉ, DEUX FOIS
  · `weekly_security_report` était décorée `@tasks.loop` et n'avait AUCUN
    `.start()`. Elle n'a jamais tourné. Un rapport hebdomadaire qui ne part
    pas ne se remarque qu'une semaine plus tard — ou jamais.
  · 19/08/2026, en posant le bilan détaillé de la veille : j'ai inséré un
    helper entre `@tasks.loop(minutes=30)` et `veille_roblox_task`. Le
    décorateur s'est recollé au helper ; la boucle principale de la veille
    Roblox est devenue une fonction ordinaire que plus rien n'appelait. C'est
    le piège n°1 du dépôt, reposé par le correctif censé aider.

Aucun de ces deux cas n'est vu par `ast.parse`, par `import bot`, ni par
`verif_noms`. Le code est parfaitement valide — il ne s'exécute simplement
jamais. C'est la définition même d'une fonction non appelée.

LES DEUX CONTRÔLES, ET POURQUOI UN SEUL EST FATAL

  ❌ FATAL — DÉMARRÉE MAIS PLUS DÉCORÉE. Un `X.start()` (ou une entrée du
     superviseur) qui vise une fonction de niveau module SANS `@tasks.loop`.
     Rien ne rattrape ce cas : `.start()` sur une fonction ordinaire lève
     `AttributeError`, avalé par le `try` du boot, et le balayage automatique
     du superviseur ne la voit pas non plus — il ne collecte que les objets
     `tasks.Loop`, or ce n'en est plus un. C'est le cas du 19/08.

  ⚠️ SIGNALÉ, PAS FATAL — DÉCORÉE MAIS JAMAIS DÉMARRÉE explicitement.
     `_iter_supervised_loops` fait un BALAYAGE AUTOMATIQUE de tous les objets
     `tasks.Loop` des globals et relance ce qui ne tourne pas (`if not
     lo.is_running(): lo.start()`). Une boucle jamais démarrée n'est donc pas
     en train de tourner… jusqu'au premier passage du superviseur, qui la
     démarre. En crier serait un faux positif — c'est justement ce filet qui
     a été posé après l'affaire `weekly_security_report`.
     ⚠️ SAUF si elle est dans `_SUPERVISOR_DENY` : la deny-list exclut de
     TOUTES les sources, balayage compris. Là, jamais démarrée = jamais
     exécutée, pour de bon → fatal.

⚠️ CONSERVATEUR. Une boucle appelée via `globals()[...]` ne peut pas être
suivie statiquement — on ne la juge pas.

Usage :
    PYTHONIOENCODING=utf-8 python outils/verif_boucles.py bot.py
Sortie : code 1 dès qu'une boucle est déclarée sans démarrage, ou démarrée
sans décorateur.
"""
from __future__ import annotations

import ast
import sys


def _est_tasks_loop(deco) -> bool:
    """`@tasks.loop(...)` ou `@tasks.loop` — avec ou sans appel."""
    n = deco.func if isinstance(deco, ast.Call) else deco
    if isinstance(n, ast.Attribute):
        return n.attr == "loop"
    return isinstance(n, ast.Name) and n.id == "loop"


def _decorees(arbre) -> dict:
    """{nom: ligne} des fonctions de niveau module portant @tasks.loop."""
    out = {}
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_est_tasks_loop(d) for d in n.decorator_list):
                out[n.name] = n.lineno
    return out


def _fonctions_module(arbre) -> dict:
    return {n.name: n.lineno for n in arbre.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _demarrees(arbre) -> dict:
    """{nom: ligne} des `X.start()` où X est un simple nom."""
    out = {}
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "start"
                and isinstance(n.func.value, ast.Name)):
            out.setdefault(n.func.value.id, n.lineno)
    return out


def _chaines_de(arbre, variable: str) -> set:
    """Les chaînes littérales affectées à `variable` au niveau module."""
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == variable:
                    return {e.value for e in ast.walk(n.value)
                            if isinstance(e, ast.Constant)
                            and isinstance(e.value, str)}
    return set()


def main() -> int:
    fichier = sys.argv[1] if len(sys.argv) > 1 else "bot.py"
    src = open(fichier, encoding="utf-8").read()
    arbre = ast.parse(src)
    lignes = src.splitlines()

    decorees = _decorees(arbre)
    fonctions = _fonctions_module(arbre)
    demarrees = _demarrees(arbre)
    supervisees = _chaines_de(arbre, "_SUPERVISED_LOOP_NAMES")
    refusees = _chaines_de(arbre, "_SUPERVISOR_DENY")

    #  ❌ FATAL — démarrée (ou surveillée) mais plus décorée.
    #     On ne juge que les noms qui SONT une fonction de niveau module :
    #     un `.start()` sur autre chose (thread, session…) ne nous regarde pas.
    orphelines = []
    for nom, ligne in demarrees.items():
        if nom in fonctions and nom not in decorees:
            orphelines.append((nom, ligne, "démarrée par .start()"))
    for nom in sorted(supervisees):
        if nom in fonctions and nom not in decorees:
            orphelines.append((nom, fonctions[nom], "inscrite au superviseur"))

    #  ❌ FATAL — décorée, jamais démarrée, ET exclue du balayage automatique
    #     par la deny-list : plus aucun filet, elle ne tournera jamais.
    condamnees = [(nom, l) for nom, l in decorees.items()
                  if nom not in demarrees and nom in refusees]

    #  ⚠️ SIGNALÉ — décorée, pas de `.start()` explicite, mais le balayage
    #     automatique du superviseur la démarrera au premier passage.
    tardives = [(nom, l) for nom, l in decorees.items()
                if nom not in demarrees and nom not in refusees]

    #  Une entrée du superviseur qui ne correspond à RIEN : la liste ment sur
    #  ce qu'elle surveille. Signalé, pas fatal (`globals().get()` rend None).
    fantomes = sorted(n for n in supervisees if n not in fonctions)

    print(f"  {fichier}")
    print(f"    boucles déclarées @tasks.loop : {len(decorees)}")
    print(f"    démarrées par .start()        : {len(demarrees)}")
    print(f"    inscrites au superviseur      : {len(supervisees)}")
    if fantomes:
        print(f"    ⚠️ inscrites au superviseur sans fonction : {', '.join(fantomes)}")
        print("       (sans effet — `globals().get()` rend None — mais la liste ment)")
    for nom, ligne in sorted(tardives, key=lambda x: x[1]):
        print(f"    ⚠️ {nom} (l.{ligne}) n'a aucun .start() explicite —")
        print("       démarrée par le balayage automatique du superviseur.")

    if not orphelines and not condamnees:
        print("    ✅ aucune boucle démarrée sans décorateur, aucune condamnée.")
        return 0

    if orphelines:
        print(f"\n  ❌ {len(orphelines)} boucle(s) DÉMARRÉE(S) MAIS SANS @tasks.loop "
              f"— `.start()` lèvera AttributeError :\n")
        for nom, ligne, comment in sorted(orphelines, key=lambda x: x[1]):
            print(f"    {nom}  —  l.{ligne}  ({comment})")
            print(f"        {lignes[ligne - 1].strip()[:88]}")
        print("\n  → le décorateur a probablement été décollé en insérant du code")
        print("    entre lui et sa fonction (piège n°1 du dépôt). Le balayage")
        print("    automatique ne rattrape PAS ce cas : ce n'est plus une Loop.")

    if condamnees:
        print(f"\n  ❌ {len(condamnees)} boucle(s) SANS .start() ET EXCLUE(S) du "
              f"balayage (deny-list) — elles ne tourneront jamais :\n")
        for nom, ligne in sorted(condamnees, key=lambda x: x[1]):
            print(f"    {nom}  —  l.{ligne}")
            print(f"        {lignes[ligne - 1].strip()[:88]}")
        print("\n  → soit un `.start()` explicite, soit retirer la boucle.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
