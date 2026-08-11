#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Détache complètement un module condamné de bot.py, puis le supprime.

Les modules encore accrochés ne le sont plus par le câblage d'`on_ready` (déjà
propre) mais par des symboles DÉDIÉS qui survivent à la fermeture transitive parce
qu'ils sont décorés (`@tasks.loop`) ou cités dans une chaîne. Ce script fait la
coupe complète, dans le bon ordre :

  1. Recense les symboles de niveau module qui référencent l'alias du module.
  2. Étend par fermeture : un symbole qui ne sert QUE ces symboles-là part aussi.
  3. Retire tout ce qui les CÂBLE encore, et c'est là qu'est le piège :
       · les `X.start()` / `X.cancel()` ;
       · ⚠️ §5.5 — les entrées de `_SUPERVISED_LOOP_NAMES` et
         `_SUPERVISED_MODULE_LOOPS`, référencées par CHAÎNE. Retirer le `.start()`
         sans elles ne sert à rien : le superviseur RELANCE la boucle.
       · les appels simples depuis du code gardé (`await _hook(m)`).
  4. Supprime les symboles, la ligne d'import, le fichier du module et ses tests.
  5. `ast.parse` + contrôle qu'aucun nom supprimé ne subsiste EN CODE.

Tout ce qui n'est pas une instruction simple est REFUSÉ et signalé : une référence
au milieu d'une expression demande une décision humaine, pas une coupe automatique.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/detacher_module.py entraide
    PYTHONIOENCODING=utf-8 python3 outils/detacher_module.py entraide --apply
"""
from __future__ import annotations

import ast
import glob
import os
import re
import sys

FICHIER = "bot.py"
SUPERVISEURS = ("_SUPERVISED_LOOP_NAMES", "_SUPERVISED_MODULE_LOOPS")

#  ⚠️ SANS CETTE LISTE, L'OUTIL SUPPRIME on_ready ET on_member_join.
#  Ces handlers CITENT des modules condamnés (i18n, lore, onboarding…) tout en
#  étant vitaux : la règle « ce symbole touche le module donc il part » les
#  emporte. Constaté en vrai le 11/08 — `verif_socle.sh` l'a rattrapé avant le
#  commit. Un symbole protégé n'est JAMAIS supprimé ; seules les instructions
#  qui, à l'intérieur de lui, touchent le module condamné sont retirées.
PROTEGES = {
    "on_ready", "on_message", "on_member_join", "on_member_update",
    "on_user_update", "on_voice_state_update", "on_raw_reaction_add",
    "on_invite_create", "on_invite_delete", "on_message_edit", "on_message_delete",
    "help_cmd", "sanction", "is_immune", "create_ticket", "task_supervisor",
    "check_expired_restrictions", "_record_infraction", "check_badwords",
    "_ocr_scam_check", "_kick_young_account", "_handle_antiraid_join",
    "MainPanelV2", "SuspectScanPanel", "AfkRolePanel",
}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("Usage : detacher_module.py <module> [--apply]")
    module = args[0]
    apply_ = "--apply" in sys.argv

    src = open(FICHIER, encoding="utf-8").read()
    lignes = src.splitlines(keepends=True)
    arbre = ast.parse(src)

    # ── L'alias sous lequel bot.py connaît ce module ────────────────────────
    alias, ligne_import = set(), None
    for n in arbre.body:
        if isinstance(n, ast.Import):
            for al in n.names:
                if al.name.split(".")[0] == module:
                    alias.add(al.asname or module)
                    ligne_import = n.lineno
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == module:
            ligne_import = n.lineno
    if not alias and ligne_import is None:
        raise SystemExit(f"ABANDON : {module} n'est pas importé par {FICHIER}.")

    #  ⚠️ La plage part du PREMIER DÉCORATEUR, pas du `def` : en AST, `lineno`
    #  pointe sur le `def`, donc `@x.before_loop` tombait hors de la plage et sa
    #  référence à `x` était comptée comme « venant de l'extérieur ».
    sym = {n.name: (min([n.lineno] + [d.lineno for d in n.decorator_list]), n.end_lineno)
           for n in arbre.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

    # ── Index UNIQUE des noms utilisés (un seul ast.walk) ───────────────────
    #  Le faire par symbole était quadratique (1358 symboles × ~1 M de nœuds) et
    #  ne terminait pas sur un fichier de 75 000 lignes.
    refs: dict[str, list[int]] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name):
            refs.setdefault(n.id, []).append(n.lineno)

    #  Table ligne -> symbole propriétaire, bâtie une seule fois.
    proprio: dict[int, str] = {}
    for nom, (a, b) in sym.items():
        for l in range(a, b + 1):
            proprio[l] = nom

    # ── 1. Symboles qui touchent l'alias, SAUF les protégés ─────────────────
    #  Tout `on_*` est protégé d'office : ce sont les handlers d'événement, ils
    #  citent souvent un module condamné au milieu de code vital.
    def protege(nom: str) -> bool:
        return nom in PROTEGES or nom.startswith("on_")

    touchent = {proprio[l] for a in alias for l in refs.get(a, []) if l in proprio}
    cibles = {n for n in touchent if not protege(n)}
    gardes_touches = sorted(touchent - cibles)

    # ── 2. Fermeture : ce qui ne sert QUE les cibles ────────────────────────
    #  Décorateurs : `@<tache>.before_loop` sur une fonction que PERSONNE n'appelle.
    #  Elle n'a aucune référence entrante, donc la règle « toutes ses références
    #  viennent de condamnés » ne la prend jamais — il faut la suivre par son
    #  décorateur, sinon elle survit en citant une tâche supprimée.
    dec_vers: dict[str, set[str]] = {}
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            dec_vers[n.name] = {x.id for d in n.decorator_list
                                for x in ast.walk(d) if isinstance(x, ast.Name)}

    change = True
    while change:
        change = False
        for nom in sorted(set(sym) - cibles):
            if protege(nom):
                continue
            hits = refs.get(nom, [])
            #  Toutes ses références viennent-elles de symboles déjà condamnés ?
            if hits and all(proprio.get(l) in cibles for l in hits):
                cibles.add(nom)
                change = True
            elif dec_vers.get(nom, set()) & cibles:
                cibles.add(nom)
                change = True

    #  Instruction simple dont TOUTE la substance est une référence à une cible.
    def dans_cible(l: int) -> bool:
        return proprio.get(l) in cibles

    a_couper: set[int] = set()
    for p in ast.walk(arbre):
        for champ in ("body", "orelse", "finalbody"):
            bloc = getattr(p, champ, None)
            if not isinstance(bloc, list):
                continue
            for stmt in bloc:
                if not isinstance(stmt, (ast.Expr, ast.Assign)):
                    continue
                if dans_cible(stmt.lineno):
                    continue                      # déjà emporté avec sa cible
                if any(isinstance(x, ast.Name) and (x.id in cibles or x.id in alias)
                       for x in ast.walk(stmt)):
                    a_couper.update(
                        range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))

    #  Entrées de superviseur (référencées par CHAÎNE) — le piège §5.5.
    #  On délimite d'abord les listes par AST, puis on ne scanne que ces plages :
    #  chercher les noms sur tout le fichier était quadratique et inexploitable.
    plages_sup: list[tuple[int, int]] = []
    for n in arbre.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in SUPERVISEURS for t in n.targets):
            plages_sup.append((n.lineno, n.end_lineno))

    sup_lignes = set()
    for deb, fin in plages_sup:
        for n in range(deb, fin + 1):
            l = lignes[n - 1]
            for nom in cibles:
                if f'"{nom}"' in l or f"'{nom}'" in l:
                    sup_lignes.add(n)
                    break

    print(f"── Détachement de « {module} » ─────────────────────────────────")
    print(f"  alias : {sorted(alias) or '(from-import)'}  ·  import l.{ligne_import}")
    print(f"  symboles à supprimer : {len(cibles)}, "
          f"{sum(sym[n][1] - sym[n][0] + 1 for n in cibles)} lignes")
    if gardes_touches:
        print(f"  🛡️  PROTÉGÉS qui y touchent (jamais supprimés, coupe interne) : "
              f"{', '.join(gardes_touches)}")
    for n in sorted(cibles, key=lambda x: sym[x][0]):
        a, b = sym[n]
        print(f"      {n:40} l.{a}-{b} ({b - a + 1} l.)")
    if a_couper:
        print(f"\n  câblage retiré : {len(a_couper)} ligne(s)")
        for l in sorted(a_couper)[:15]:
            print(f"      l.{l}: {lignes[l - 1].strip()[:88]}")
    if sup_lignes:
        print(f"\n  ⚠️  entrées de SUPERVISEUR (§5.5) : {len(sup_lignes)}")
        for l in sorted(sup_lignes):
            print(f"      l.{l}: {lignes[l - 1].strip()[:88]}")

    # ── Découpe ─────────────────────────────────────────────────────────────
    a_retirer = set(a_couper) | sup_lignes | {ligne_import}
    for n in cibles:
        a_retirer.update(range(sym[n][0], sym[n][1] + 1))

    #  Un bloc dont TOUTES les instructions disparaissent laisse un `try:` /
    #  `if:` vide → SyntaxError. On y pose un `pass`, à l'indentation d'origine.
    pass_a_poser: dict[int, str] = {}
    for p in ast.walk(arbre):
        for champ in ("body", "orelse", "finalbody"):
            bloc = getattr(p, champ, None)
            if not isinstance(bloc, list) or not bloc or isinstance(p, ast.Module):
                continue
            #  Si le parent (`try:`, `if:`, la fonction…) disparaît lui aussi, son
            #  bloc n'a pas besoin de `pass` : ce serait un orphelin mal indenté.
            if getattr(p, "lineno", None) in a_retirer:
                continue
            if all(all(l in a_retirer
                       for l in range(s.lineno, (s.end_lineno or s.lineno) + 1))
                   for s in bloc):
                prem = bloc[0].lineno
                src_l = lignes[prem - 1]
                pass_a_poser[prem] = src_l[:len(src_l) - len(src_l.lstrip())]

    nouvelles = []
    for i, l in enumerate(lignes, 1):
        if i in pass_a_poser:
            nouvelles.append(f"{pass_a_poser[i]}pass  # bloc vidé (module détaché)\n")
        elif i not in a_retirer:
            nouvelles.append(l)
    res = "".join(nouvelles)

    try:
        ast.parse(res)
    except SyntaxError as ex:
        rl = res.splitlines()
        ctx = "\n".join(
            f"    {n:>6}{'>' if n == ex.lineno else ' '} {rl[n - 1][:96]}"
            for n in range(max(1, (ex.lineno or 1) - 8), min(len(rl), (ex.lineno or 1) + 3) + 1))
        raise SystemExit(f"ABANDON : le résultat ne se parse pas — {ex}\n"
                         f"  Contexte DANS LE RÉSULTAT :\n{ctx}")

    arbre_res = ast.parse(res)
    morts = cibles | alias
    restes = [f"  l.{n.lineno} [{n.id}]" for n in ast.walk(arbre_res)
              if isinstance(n, ast.Name) and n.id in morts]
    if restes:
        raise SystemExit("ABANDON : références résiduelles EN CODE :\n"
                         + "\n".join(restes[:25]))

    avant, apres = len(lignes), len(res.splitlines())
    print(f"\n  bot.py {avant} → {apres} lignes ({apres - avant:+d})")
    print("  ast.parse OK · aucune référence résiduelle en code")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(res)
    if os.path.exists(f"{module}.py"):
        os.remove(f"{module}.py")
    for t in glob.glob("tests/*.py"):
        txt = open(t, encoding="utf-8", errors="replace").read()
        if re.search(rf"^\s*(import|from)\s+{re.escape(module)}\b", txt, re.M):
            os.remove(t)
            print(f"  test supprimé : {t}")
    ti = "tests/test_imports.py"
    if os.path.exists(ti):
        av = open(ti, encoding="utf-8").read().splitlines(keepends=True)
        ap = [l for l in av if not re.search(rf'["\']{re.escape(module)}["\']', l)]
        if len(ap) != len(av):
            open(ti, "w", encoding="utf-8", newline="").write("".join(ap))
            print(f"  {ti} : {len(av) - len(ap)} ligne(s) retirée(s)")
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
