#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fermeture transitive INVERSE : trouve les classes de `bot.py` que plus rien de
vivant n'atteint, et les supprime.

Le principe, et pourquoi il est sûr :
  une classe n'est morte que si TOUTES les références vers elle viennent de classes
  elles-mêmes mortes. On itère jusqu'au point fixe : dès qu'une référence vient de
  code vivant (niveau module, fonction, classe vivante, AUTRE fichier du dépôt),
  la classe est ressuscitée — et avec elle, au tour suivant, tout ce qu'elle cite.

Garde-fous (HANDOFF.md §4 et §5) :
  - `NEVER_DELETE` : les points d'entrée n'ont PAS d'appelant (on_ready, on_message,
    on_member_join…). Une analyse « personne ne l'appelle » a déjà voulu supprimer
    `on_member_join`, soit 411 lignes d'anti-raid.
  - Balayage de TOUT le dépôt (`*.py`, `tests/`) et pas seulement de `bot.py`.
  - Recherche des noms cités dans des CHAÎNES de caractères (le hub V2 résout ses
    handlers par nom) : toute classe nommée dans une string est épargnée, et signalée.
  - `ast.parse()` avant écriture, preview par défaut.
  - La liste est AFFICHÉE pour relecture humaine avant tout `--apply`.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/purge_morts.py                  # preview
    PYTHONIOENCODING=utf-8 python3 outils/purge_morts.py --apply          # écrit
    PYTHONIOENCODING=utf-8 python3 outils/purge_morts.py --only A,B,C     # restreint
"""
from __future__ import annotations

import ast
import glob
import os
import re
import sys

FICHIER = "bot.py"

# §5 piège 1 — les points d'entrée n'ont pas d'appelant. Ne jamais les toucher,
# ni les classes qui portent un contrat Discord (vues persistantes, DynamicItem).
NEVER_DELETE = {
    "MainPanelV2",
    # Helpers V1 dont un panneau V2 dépend encore (constaté en cartographie) :
    "SuspectScanPanel",   # helper de scan de SuspectScanPanelV2
    "AfkRolePanel",       # porte get_afk_members, utilisé par AfkRolePanelV2
}


def refs_par_nom(arbre: ast.Module) -> dict[str, list[int]]:
    """Toutes les lignes où un nom est employé comme identifiant (appel, classe de
    base, isinstance, affectation…). Les `ast.Name` couvrent tous ces cas."""
    out: dict[str, list[int]] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name):
            out.setdefault(n.id, []).append(n.lineno)
        elif isinstance(n, ast.Attribute):
            # `module.Classe` — on ne suit pas, mais on note la base si c'est un Name
            pass
    return out


def noms_dans_chaines(src: str, noms: set[str]) -> set[str]:
    """Noms de classes cités dans une chaîne de caractères (résolution dynamique)."""
    trouves = set()
    for m in re.finditer(r'["\']([A-Za-z_][A-Za-z0-9_]*)["\']', src):
        if m.group(1) in noms:
            trouves.add(m.group(1))
    return trouves


def refs_autres_fichiers(noms: set[str]) -> dict[str, list[str]]:
    """Références depuis les AUTRES fichiers .py du dépôt (modules + tests)."""
    out: dict[str, list[str]] = {}
    fichiers = [
        f for f in glob.glob("**/*.py", recursive=True)
        if os.path.normpath(f) != FICHIER and ".git" not in f and "outils" not in f
    ]
    for f in fichiers:
        try:
            texte = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for nom in noms:
            if re.search(rf"\b{re.escape(nom)}\b", texte):
                out.setdefault(nom, []).append(f)
    return out


def main() -> int:
    apply_ = "--apply" in sys.argv
    only = None
    for a in sys.argv:
        if a.startswith("--only"):
            val = a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1]
            only = {s.strip() for s in val.split(",") if s.strip()}

    src = open(FICHIER, encoding="utf-8").read()
    lignes = src.splitlines(keepends=True)
    arbre = ast.parse(src)

    classes = {
        n.name: (n.lineno, n.end_lineno)
        for n in arbre.body if isinstance(n, ast.ClassDef)
    }
    refs = refs_par_nom(arbre)

    # ── Point fixe ───────────────────────────────────────────────────────────
    candidats = set(classes) - NEVER_DELETE
    if only:
        inconnus = only - set(classes)
        if inconnus:
            raise SystemExit(f"ABANDON : classes inconnues dans --only : {sorted(inconnus)}")
        candidats &= only

    # Épargne immédiate : nom cité dans une chaîne, ou utilisé ailleurs dans le dépôt.
    dynamiques = noms_dans_chaines(src, candidats)
    externes = refs_autres_fichiers(candidats)
    epargnes_dyn = dynamiques | set(externes)
    candidats -= epargnes_dyn

    change = True
    while change:
        change = False
        for c in sorted(candidats):
            zones_mortes = [classes[n] for n in candidats]
            dehors = [
                l for l in refs.get(c, [])
                if not any(a <= l <= b for a, b in zones_mortes)
            ]
            if dehors:
                candidats.discard(c)
                change = True

    morts = sorted(candidats, key=lambda n: classes[n][0])

    # ── Rapport ──────────────────────────────────────────────────────────────
    total = sum(classes[n][1] - classes[n][0] + 1 for n in morts)
    print("── Fermeture transitive inverse ────────────────────────────────")
    print(f"  classes de niveau module : {len(classes)}")
    print(f"  épargnées (nom en chaîne / usage hors bot.py) : {len(epargnes_dyn)}")
    if epargnes_dyn:
        for n in sorted(epargnes_dyn):
            raison = []
            if n in dynamiques:
                raison.append("citée dans une chaîne")
            if n in externes:
                raison.append("utilisée dans " + ", ".join(externes[n][:3]))
            print(f"      {n:34} {' ; '.join(raison)}")
    print(f"\n  INATTEIGNABLES : {len(morts)} classes, {total} lignes")
    for n in morts:
        a, b = classes[n]
        print(f"      {n:38} l.{a}-{b}  ({b - a + 1} l.)")

    if not morts:
        print("\n  Rien à supprimer.")
        return 0

    # ── Découpe, de la fin vers le début ─────────────────────────────────────
    plages = sorted((classes[n] for n in morts), reverse=True)
    nouvelles = list(lignes)
    for a, b in plages:
        del nouvelles[a - 1:b]
    resultat = "".join(nouvelles)

    try:
        ast.parse(resultat)
    except SyntaxError as ex:
        raise SystemExit(f"ABANDON : le résultat ne se parse pas — {ex}")

    # ── Garde-fou dur : plus AUCUNE référence dans du CODE ───────────────────
    #  On distingue le code des commentaires : une mention historique du genre
    #  « l'ancien X paginait les salons 23 par 23 » explique POURQUOI le code
    #  actuel est ainsi — elle doit survivre. Un appel, lui, casse le boot.
    arbre_res = ast.parse(resultat)
    morts_set = set(morts)
    en_code = []
    for n in ast.walk(arbre_res):
        if isinstance(n, ast.Name) and n.id in morts_set:
            en_code.append(f"  l.{n.lineno} [{n.id}] (identifiant)")
        elif isinstance(n, ast.Attribute) and n.attr in morts_set:
            en_code.append(f"  l.{n.lineno} [{n.attr}] (attribut)")
    if en_code:
        raise SystemExit(
            "ABANDON : références résiduelles DANS DU CODE :\n" + "\n".join(en_code[:40])
        )

    # ── Signalement doux : mentions dans les commentaires et docstrings ──────
    #  Pas bloquant, mais à relire : un commentaire qui décrit l'état ACTUEL
    #  devient un mensonge, alors qu'un commentaire historique reste utile.
    mentions = []
    for n, l in enumerate(resultat.splitlines(), 1):
        for m in morts_set:
            if re.search(rf"\b{re.escape(m)}\b", l):
                mentions.append(f"      l.{n} [{m}] {l.strip()[:88]}")
    if mentions:
        print(f"\n  ⚠️  {len(mentions)} mention(s) en commentaire — à relire :")
        for x in mentions[:25]:
            print(x)

    avant, apres = len(lignes), len(resultat.splitlines())
    print(f"\n  bot.py  {avant} → {apres} lignes ({apres - avant:+d})")
    print("  ast.parse OK · aucune référence résiduelle")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relire la liste ci-dessus, puis --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(resultat)
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
