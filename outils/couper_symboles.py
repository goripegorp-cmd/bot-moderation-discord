"""Supprime des symboles de premier niveau de bot.py — et TOUT ce qui les câble.

`detacher_module.py` fait ce travail pour un module entier. Il ne sait rien
faire d'un système qui vit à l'intérieur de `bot.py` : les cadeaux, les boss et
les salons d'événements sont dans ce cas, pour plusieurs milliers de lignes.

⚠️ LES DEUX SUR-COUPES QUE CET OUTIL EXISTE POUR NE PAS REFAIRE
  · Borner une coupe sur « la prochaine ligne `async def` » a emporté 500 lignes
    une fois, et le décorateur `@tasks.loop` de la fonction suivante l'autre —
    le bot ne démarrait plus. Ici, les bornes viennent d'`ast` : `lineno` du
    PREMIER décorateur → `end_lineno` du corps. Jamais d'une expression
    régulière, jamais d'une devinette.
  · Retirer un `.start()` sans l'entrée de `_SUPERVISED_LOOP_NAMES` ne débranche
    rien : le superviseur relance la boucle par son NOM en chaîne.

ET UN TROISIÈME, PLUS LARGE QUE CE QUI ÉTAIT ÉCRIT
`_iter_supervised_loops` a un BALAYAGE AUTO qui ramasse tout objet `tasks.Loop`
déjà démarré, même absent de la liste. Retirer le nom de la liste ne suffit donc
PAS : il faut supprimer la boucle elle-même. C'est ce que fait cet outil.

Ce qu'il retire, pour chaque symbole demandé :
  1. le symbole entier (décorateurs compris) ;
  2. ses `X.start()` / `X.cancel()` / `X.restart()`, et la garde
     `if not X.is_running():` qui les précède — un `if` sans corps est une
     SyntaxError ;
  3. son entrée dans `_SUPERVISED_LOOP_NAMES` ;
  4. les `@X.before_loop` / `@X.after_loop` et la fonction qu'ils décorent.

Il REFUSE d'écrire si, après coup, `ast.parse` échoue ou s'il reste une
référence en code (hors chaînes et commentaires) à un symbole supprimé.

Usage :
    PYTHONIOENCODING=utf-8 python outils/couper_symboles.py nom1 nom2 …
    PYTHONIOENCODING=utf-8 python outils/couper_symboles.py nom1 nom2 … --apply
"""
from __future__ import annotations

import ast
import re
import sys

FICHIER = "bot.py"


def _symboles(arbre: ast.Module) -> dict:
    """nom -> (première ligne décorateur comprise, dernière ligne)."""
    out = {}
    for n in arbre.body:
        nom = getattr(n, "name", None)
        if not nom:
            continue
        debut = n.lineno
        for d in getattr(n, "decorator_list", []):
            debut = min(debut, d.lineno)
        out[nom] = (debut, n.end_lineno)
    return out


def _hooks_de_boucle(arbre: ast.Module, cibles: set) -> set:
    """Les `@X.before_loop` / `@X.after_loop` des boucles supprimées.

    Sans eux, le décorateur reste accroché à un nom qui n'existe plus →
    NameError à l'import, c'est-à-dire un bot qui ne démarre pas.
    """
    out = set()
    for n in arbre.body:
        for d in getattr(n, "decorator_list", []):
            base = d.func if isinstance(d, ast.Call) else d
            if (isinstance(base, ast.Attribute)
                    and isinstance(base.value, ast.Name)
                    and base.value.id in cibles
                    and base.attr in ("before_loop", "after_loop")):
                out.add(n.name)
    return out


def main() -> int:
    noms = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply_ = "--apply" in sys.argv
    if not noms:
        print("Usage : couper_symboles.py nom1 nom2 … [--apply]")
        return 1

    src = open(FICHIER, encoding="utf-8").read()
    arbre = ast.parse(src)
    connus = _symboles(arbre)

    absents = [n for n in noms if n not in connus]
    if absents:
        print(f"❌ symbole(s) introuvable(s) : {absents}")
        return 1

    cibles = set(noms)
    #  Fermeture : les hooks de boucle partent avec leur boucle.
    hooks = _hooks_de_boucle(arbre, cibles)
    cibles |= hooks
    if hooks:
        print(f"  + {len(hooks)} hook(s) de boucle emporté(s) : {sorted(hooks)}")

    a_couper = sorted((connus[n][0], connus[n][1], n) for n in cibles)
    lignes = src.splitlines(keepends=True)
    supprimees = set()
    for debut, fin, nom in a_couper:
        supprimees.update(range(debut, fin + 1))
        print(f"      {nom:<38} l.{debut}-{fin} ({fin - debut + 1} l.)")

    #  ── Le câblage ──────────────────────────────────────────────────────────
    cable = []
    motif_start = re.compile(
        r"^\s*(" + "|".join(map(re.escape, sorted(cibles)))
        + r")\.(start|cancel|restart|stop)\(\s*\)\s*$")
    motif_garde = re.compile(
        r"^\s*if\s+not\s+(" + "|".join(map(re.escape, sorted(cibles)))
        + r")\.is_running\(\)\s*:\s*$")

    for i, ligne in enumerate(lignes, start=1):
        if i in supprimees:
            continue
        if motif_start.match(ligne):
            cable.append(i)
            #  La garde qui précède immédiatement part avec : un `if` dont le
            #  corps disparaît est une SyntaxError.
            j = i - 1
            while j >= 1 and lignes[j - 1].strip() == "":
                j -= 1
            if j >= 1 and motif_garde.match(lignes[j - 1]):
                cable.append(j)

    #  ── Les entrées du superviseur, référencées par CHAÎNE ───────────────────
    superviseur = []
    for i, ligne in enumerate(lignes, start=1):
        if i in supprimees:
            continue
        neuve = ligne
        for nom in cibles:
            neuve = re.sub(rf'"{re.escape(nom)}"\s*,?\s*', "", neuve)
        if neuve != ligne:
            #  Une ligne devenue vide (ou réduite à des espaces) disparaît ;
            #  sinon on garde la ligne allégée.
            superviseur.append((i, neuve if neuve.strip() else None))

    print(f"\n  câblage retiré      : {len(cable)} ligne(s)")
    print(f"  entrées superviseur : {len(superviseur)}")

    #  ── Reconstruction ──────────────────────────────────────────────────────
    remplacements = {i: t for i, t in superviseur}
    sortie = []
    for i, ligne in enumerate(lignes, start=1):
        if i in supprimees or i in cable:
            continue
        if i in remplacements:
            if remplacements[i] is None:
                continue
            sortie.append(remplacements[i])
            continue
        sortie.append(ligne)
    nouveau = "".join(sortie)

    #  ── Les refus ───────────────────────────────────────────────────────────
    try:
        arbre2 = ast.parse(nouveau)
    except SyntaxError as ex:
        print(f"\n❌ ABANDON — ast.parse échoue : ligne {ex.lineno} : {ex.msg}")
        return 1

    residus = []
    for n in ast.walk(arbre2):
        if isinstance(n, ast.Name) and n.id in cibles:
            residus.append((n.lineno, n.id))
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.value.id in cibles:
            residus.append((n.lineno, n.value.id))
    if residus:
        print("\n❌ ABANDON — références résiduelles EN CODE :")
        for l, nom in sorted(set(residus))[:20]:
            print(f"    l.{l} [{nom}]")
        return 1

    avant, apres = len(lignes), nouveau.count("\n") + 1
    print(f"\n  {FICHIER} {avant} → {apres} lignes ({apres - avant})")
    print("  ast.parse OK · aucune référence résiduelle en code")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(nouveau)
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
