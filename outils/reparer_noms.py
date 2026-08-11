#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Boucle de réparation : élimine les noms devenus indéfinis après une purge.

Après le détachement d'un module, il reste des symboles qui citent encore un nom
supprimé. Ce script itère : il supprime les symboles PORTEURS de noms inconnus,
ce qui en rend d'autres inconnus à leur tour, jusqu'à ce que le fichier soit sain.

GARDE-FOU ABSOLU : les points d'entrée (`PROTEGES`) ne sont JAMAIS supprimés. S'il
reste un nom inconnu à l'intérieur de l'un d'eux, le script s'ARRÊTE et le signale :
c'est une réparation manuelle, pas une coupe. Sans cette règle, la boucle
emporterait `on_ready` et `on_message` au premier tour.

Ne touche pas non plus aux entrées de superviseur ni aux chaînes : elles sont
signalées pour un passage séparé.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/reparer_noms.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/reparer_noms.py --apply
"""
from __future__ import annotations

import ast
import builtins
import sys

FICHIER = "bot.py"

PROTEGES = {
    "on_ready", "on_message", "on_member_join", "on_member_update",
    "on_user_update", "on_voice_state_update", "on_raw_reaction_add",
    "on_invite_create", "on_invite_delete", "on_message_edit", "on_message_delete",
    "help_cmd", "sanction", "is_immune", "create_ticket", "task_supervisor",
    "check_expired_restrictions", "_record_infraction", "check_badwords",
    "_ocr_scam_check", "_kick_young_account", "_handle_antiraid_join",
    "MainPanelV2", "SuspectScanPanel",   # AfkRolePanel retiré : le système AFK est supprimé "_build_casier_panel",
    "warn_cmd", "unwarn_cmd", "mute_cmd", "unmute_cmd", "clear_cmd",
}


def lies(arbre):
    """Noms que le module définit (version compacte de outils/verif_noms.py)."""
    out = set()

    def cible(n):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, (ast.Tuple, ast.List)):
            for e in n.elts:
                cible(e)
        elif isinstance(n, ast.Starred):
            cible(n.value)

    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            a = getattr(n, "args", None)
            if isinstance(a, ast.arguments):
                out.update(p.arg for p in a.posonlyargs + a.args + a.kwonlyargs)
                if a.vararg:
                    out.add(a.vararg.arg)
                if a.kwarg:
                    out.add(a.kwarg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out.update((al.asname or al.name).split(".")[0] for al in n.names)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                cible(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor)):
            cible(n.target)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                if it.optional_vars is not None:
                    cible(it.optional_vars)
        elif isinstance(n, ast.comprehension):
            cible(n.target)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, ast.Lambda):
            a = n.args
            out.update(p.arg for p in a.posonlyargs + a.args + a.kwonlyargs)
            if a.vararg:
                out.add(a.vararg.arg)
            if a.kwarg:
                out.add(a.kwarg.arg)
        elif isinstance(n, ast.NamedExpr):
            cible(n.target)
    return out


def main() -> int:
    apply_ = "--apply" in sys.argv
    src = open(FICHIER, encoding="utf-8").read()
    depart = len(src.splitlines())
    supprimes: list[str] = []

    for tour in range(1, 41):
        arbre = ast.parse(src)
        lignes = src.splitlines(keepends=True)
        connus = lies(arbre) | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}

        sym = {n.name: (min([n.lineno] + [d.lineno for d in n.decorator_list]), n.end_lineno)
               for n in arbre.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        proprio = {l: nom for nom, (a, b) in sym.items() for l in range(a, b + 1)}

        porteurs, bloques = set(), []
        for n in ast.walk(arbre):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in connus:
                p = proprio.get(n.lineno)
                if p is None:
                    bloques.append(f"    l.{n.lineno} [{n.id}] au NIVEAU MODULE")
                elif p in PROTEGES:
                    bloques.append(f"    l.{n.lineno} [{n.id}] dans le PROTÉGÉ {p}")
                else:
                    porteurs.add(p)

        if not porteurs:
            if bloques:
                print(f"  ARRÊT au tour {tour} — réparation MANUELLE requise :")
                for b in sorted(set(bloques))[:20]:
                    print(b)
            break

        for a, b in sorted((sym[n] for n in porteurs), reverse=True):
            del lignes[a - 1:b]
        nouveau = "".join(lignes)
        try:
            ast.parse(nouveau)
        except SyntaxError as ex:
            print(f"  ARRÊT au tour {tour} — le résultat ne parse plus : {ex}")
            break
        src = nouveau
        supprimes.extend(sorted(porteurs))
        print(f"  tour {tour:2} : {len(porteurs):3} symbole(s) retiré(s) → "
              f"{len(src.splitlines())} lignes")

    print(f"\n  {len(supprimes)} symboles au total · "
          f"bot.py {depart} → {len(src.splitlines())} lignes "
          f"({len(src.splitlines()) - depart:+d})")

    if not apply_:
        print("  PREVIEW — rien écrit.")
        return 0
    open(FICHIER, "w", encoding="utf-8", newline="").write(src)
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
