#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fermeture transitive inverse sur les FONCTIONS ET LES CLASSES de bot.py.

`purge_morts.py` ne traite que les classes. Le gros du code condamné restant est
constitué de FONCTIONS de niveau module (runtimes de giveaway, d'événements,
d'entraide, d'économie…). Ce script étend le même point fixe aux deux.

DANGER, ET COMMENT IL EST TENU (HANDOFF §5.1) : une fonction peut être un POINT
D'ENTRÉE — `on_message`, `on_ready`, une tâche `@tasks.loop`, un callback de vue.
Personne ne l'appelle, et elle est pourtant vitale. Une analyse naïve « aucun
appelant donc morte » a déjà voulu supprimer `on_member_join`, soit 411 lignes
d'anti-raid. Sont donc traités comme VIVANTS d'office :
  · tout nom listé dans NEVER_DELETE ;
  · tout `on_*` (handler d'événement discord.py) ;
  · toute fonction portant un décorateur (tasks.loop, bot.event, app_commands…) ;
  · tout nom cité dans une CHAÎNE de caractères (résolution dynamique) ;
  · tout nom utilisé ailleurs que dans bot.py.

Un symbole n'est supprimé que si TOUTES les références vers lui viennent de
symboles eux-mêmes supprimés. On itère jusqu'au point fixe.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/purge_runtimes.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/purge_runtimes.py --apply
"""
from __future__ import annotations

import ast
import glob
import os
import re
import sys

FICHIER = "bot.py"

NEVER_DELETE = {
    "MainPanelV2", "SuspectScanPanel", "AfkRolePanel",
    "on_ready", "on_message", "on_member_join", "help_cmd",
    "sanction", "is_immune", "create_ticket", "task_supervisor",
    "check_expired_restrictions", "_record_infraction", "check_badwords",
    "_ocr_scam_check", "_kick_young_account", "_handle_antiraid_join",
}


def est_point_entree(n) -> bool:
    """Vrai si le symbole doit être considéré vivant sans appelant."""
    if n.name in NEVER_DELETE:
        return True
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # handler discord.py, ou toute fonction décorée (tasks.loop, command…)
        if n.name.startswith("on_") or n.decorator_list:
            return True
    return False


def main() -> int:
    apply_ = "--apply" in sys.argv

    src = open(FICHIER, encoding="utf-8").read()
    lignes = src.splitlines(keepends=True)
    arbre = ast.parse(src)

    #  Symboles de niveau module, et ceux qui sont vivants d'office.
    sym: dict[str, tuple[int, int]] = {}
    vivants_office: set[str] = set()
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            sym[n.name] = (n.lineno, n.end_lineno)
            if est_point_entree(n):
                vivants_office.add(n.name)

    #  Références par nom, toutes profondeurs.
    refs: dict[str, list[int]] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name):
            refs.setdefault(n.id, []).append(n.lineno)

    #  Épargnes : nom cité dans une chaîne, ou utilisé hors bot.py.
    dyn = {m.group(1) for m in re.finditer(r'["\']([A-Za-z_][A-Za-z0-9_]*)["\']', src)
           if m.group(1) in sym}
    hors = set()
    for f in glob.glob("*.py"):
        if os.path.basename(f) == FICHIER:
            continue
        txt = open(f, encoding="utf-8", errors="replace").read()
        for nom in sym:
            if nom not in hors and re.search(rf"\b{re.escape(nom)}\b", txt):
                hors.add(nom)

    candidats = set(sym) - vivants_office - dyn - hors

    #  Point fixe.
    change = True
    while change:
        change = False
        zones = [sym[n] for n in candidats]
        for c in sorted(candidats):
            dehors = [l for l in refs.get(c, [])
                      if not any(a <= l <= b for a, b in zones)]
            if dehors:
                candidats.discard(c)
                change = True

    morts = sorted(candidats, key=lambda n: sym[n][0])
    total = sum(sym[n][1] - sym[n][0] + 1 for n in morts)

    print("── Fermeture inverse (fonctions + classes) ─────────────────────")
    print(f"  symboles de niveau module : {len(sym)}")
    print(f"  vivants d'office (points d'entrée / décorés) : {len(vivants_office)}")
    print(f"  épargnés (chaîne ou usage hors bot.py) : {len(dyn | hors)}")
    print(f"\n  INATTEIGNABLES : {len(morts)} symboles, {total} lignes")
    for n in morts:
        a, b = sym[n]
        print(f"      {n:44} l.{a}-{b} ({b - a + 1} l.)")
    if False:
        print(f"      … et {len(morts) - 70} autres")

    if not morts:
        return 0

    nouvelles = list(lignes)
    for a, b in sorted((sym[n] for n in morts), reverse=True):
        del nouvelles[a - 1:b]
    res = "".join(nouvelles)

    try:
        ast.parse(res)
    except SyntaxError as ex:
        raise SystemExit(f"ABANDON : le résultat ne se parse pas — {ex}")

    arbre_res = ast.parse(res)
    morts_set = set(morts)
    en_code = [f"  l.{n.lineno} [{n.id}]" for n in ast.walk(arbre_res)
               if isinstance(n, ast.Name) and n.id in morts_set]
    if en_code:
        raise SystemExit("ABANDON : références résiduelles en CODE :\n"
                         + "\n".join(en_code[:30]))

    avant, apres = len(lignes), len(res.splitlines())
    print(f"\n  bot.py {avant} → {apres} lignes ({apres - avant:+d})")
    print("  ast.parse OK · aucune référence résiduelle en code")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relire la liste, puis --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(res)
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
