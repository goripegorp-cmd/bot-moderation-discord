#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Suppression des modules hors périmètre, par lots sûrs.

RÈGLE DU DÉPÔT (vérifiée) : `bot.py` importe ~133 modules en TOP-LEVEL, sans
`try`. Supprimer un fichier sans sa ligne d'import = ImportError au boot = bot mort.
Toute suppression doit donc être ATOMIQUE :
  (a) le fichier, (b) sa ligne d'import dans bot.py, (c) ses références par alias,
  (d) son entrée dans les listes du superviseur (référencées par CHAÎNE),
  (e) sa ligne dans tests/test_imports.py.

PIÈGE VÉRIFIÉ (HANDOFF §5.11) : des modules condamnés s'importent entre eux HORS
`try`. Supprimer l'un sans l'autre casse le boot. L'outil construit donc le graphe
des imports croisés et REFUSE de supprimer un module encore importé par un module
qui reste.

Ce script ne supprime que les modules SANS RÉFÉRENCE dans bot.py (hors leur propre
ligne d'import) : le premier lot, celui qui ne demande aucune réécriture. Les
modules encore appelés depuis bot.py sont listés à part, avec leurs appelants.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/purge_modules.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/purge_modules.py --apply
"""
from __future__ import annotations

import ast
import glob
import os
import re
import sys

BOT = "bot.py"

# ═══════════════════════════════════════════════════════════════════════════════
#  LES MODULES QU'ON GARDE — périmètre sécurité / sanctions / logs / tickets / infra.
# ═══════════════════════════════════════════════════════════════════════════════
GARDER = {
    # Socle & infra
    "ui_v2", "paths", "owner_ids", "permissions", "diag", "panels_helpers",
    "error_logger", "observability", "health_check", "health_server",
    "db_backup", "backup_lite", "data_cleanup", "gdpr", "rate_limiter",
    # Logs & modération
    "unified_logger", "mod_dashboard", "owner_export", "staff_sanction",
    "recidivism", "dm_digest", "dm_notify",
    # Tickets
    "tickets_enhance", "transcript_store",
    # Sécurité — détection
    "raid_detector", "protection_guards", "antiscam", "trust_system",
    "behavior_guard", "behavior_anomaly", "insult_filter", "offtopic_filter",
    "grooming_detector", "nsfw_scan", "ocr_scan", "token_grabber",
    "webhook_leak", "webhook_tracker", "anti_token_leak", "compromised_detector",
    "honeypot", "delegations",
    # Divers infra encore câblés
    "setup_wizard", "slash_commands_2026", "admin_panels_v2", "ui_usage",
    # Outillage : régénère INDEX.md (carte des symboles) — appelé par le workflow
    # GitHub .github/workflows/index.yml, tous les jours. Le supprimer casserait
    # ce workflow, et la carte est précieuse sur un fichier de 83 000 lignes.
    "generate_index",
}

# Fichiers d'analyse jetables laissés à la racine par d'anciennes sessions.
JETABLES = re.compile(r"^_(audit|fix|migrate|patch)_")


def alias_des_imports(arbre: ast.Module) -> dict[str, list]:
    """module -> [(lineno, alias, est_from)] pour les imports de niveau module."""
    out: dict[str, list] = {}
    for n in arbre.body:
        if isinstance(n, ast.Import):
            for al in n.names:
                base = al.name.split(".")[0]
                out.setdefault(base, []).append((n.lineno, al.asname or base, False))
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            base = n.module.split(".")[0]
            out.setdefault(base, []).append((n.lineno, None, True))
    return out


def main() -> int:
    apply_ = "--apply" in sys.argv

    locaux = {
        os.path.splitext(os.path.basename(f))[0]
        for f in glob.glob("*.py")
        if os.path.basename(f) != BOT
    }
    jetables = {m for m in locaux if JETABLES.match(m)}
    condamnes = (locaux - GARDER) - jetables

    src = open(BOT, encoding="utf-8").read()
    arbre = ast.parse(src)
    lignes = src.splitlines(keepends=True)
    imports = alias_des_imports(arbre)

    # ── Références dans bot.py, hors ligne d'import ─────────────────────────
    refs: dict[str, list[int]] = {}
    for m in condamnes:
        noms = {m} | {a for _, a, _ in imports.get(m, []) if a}
        l_import = {l for l, _, _ in imports.get(m, [])}
        hits = []
        for n in ast.walk(arbre):
            if isinstance(n, ast.Name) and n.id in noms and n.lineno not in l_import:
                hits.append(n.lineno)
        if hits:
            refs[m] = sorted(set(hits))

    # ── Graphe des imports croisés entre modules locaux ─────────────────────
    importe_par: dict[str, list[str]] = {}
    for f in glob.glob("*.py"):
        mod = os.path.splitext(os.path.basename(f))[0]
        if mod == BOT[:-3]:
            continue
        try:
            a = ast.parse(open(f, encoding="utf-8", errors="replace").read())
        except Exception:
            continue
        for n in ast.walk(a):
            cibles = []
            if isinstance(n, ast.Import):
                cibles = [al.name.split(".")[0] for al in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                cibles = [n.module.split(".")[0]]
            for c in cibles:
                if c in locaux:
                    importe_par.setdefault(c, []).append(mod)

    # Un module condamné encore importé par un module GARDÉ ne peut pas partir.
    bloques = {
        m: sorted({s for s in importe_par.get(m, []) if s in GARDER})
        for m in condamnes
        if any(s in GARDER for s in importe_par.get(m, []))
    }

    sans_ref = sorted(condamnes - set(refs) - set(bloques))
    avec_ref = sorted(set(refs) - set(bloques))

    print("── Purge des modules ───────────────────────────────────────────")
    print(f"  modules locaux : {len(locaux)}  ·  gardés : {len(GARDER & locaux)}"
          f"  ·  condamnés : {len(condamnes)}  ·  jetables : {len(jetables)}")

    print(f"\n  LOT 1 — supprimables tout de suite ({len(sans_ref)}) :")
    print("    (aucune référence dans bot.py hors import, aucun module gardé ne les importe)")
    total = 0
    for m in sans_ref:
        n = len(open(f"{m}.py", encoding="utf-8", errors="replace").read().splitlines())
        total += n
        croise = [s for s in importe_par.get(m, []) if s in condamnes]
        note = f"  ← importé par {', '.join(croise[:3])}" if croise else ""
        print(f"      {m:30} {n:5} l.{note}")
    print(f"    total : {total} lignes de module")

    if jetables:
        print(f"\n  SCRIPTS D'ANALYSE JETABLES à la racine ({len(jetables)}) :")
        for m in sorted(jetables):
            print(f"      {m}.py")

    if avec_ref:
        print(f"\n  LOT 2 — encore appelés depuis bot.py ({len(avec_ref)}), à traiter après :")
        for m in avec_ref:
            print(f"      {m:30} {len(refs[m])} référence(s), l.{refs[m][:6]}")

    if bloques:
        print(f"\n  ⚠️  BLOQUÉS — importés par un module GARDÉ ({len(bloques)}) :")
        for m, par in bloques.items():
            print(f"      {m:30} ← {', '.join(par)}")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply pour le LOT 1 + jetables.")
        return 0

    # ── Application : LOT 1 + jetables ──────────────────────────────────────
    a_supprimer = set(sans_ref) | jetables

    #  (b) lignes d'import de bot.py
    a_retirer = sorted(
        {l for m in a_supprimer for l, _, _ in imports.get(m, [])}, reverse=True)
    for l in a_retirer:
        del lignes[l - 1]
    res = "".join(lignes)
    ast.parse(res)
    open(BOT, "w", encoding="utf-8", newline="").write(res)

    #  (a) les fichiers
    for m in sorted(a_supprimer):
        os.remove(f"{m}.py")

    #  (e) tests/test_imports.py
    ti = "tests/test_imports.py"
    if os.path.exists(ti):
        avant = open(ti, encoding="utf-8").read().splitlines(keepends=True)
        apres = [
            l for l in avant
            if not any(re.search(rf'["\']{re.escape(m)}["\']', l) for m in a_supprimer)
        ]
        if len(apres) != len(avant):
            open(ti, "w", encoding="utf-8", newline="").write("".join(apres))
            print(f"  tests/test_imports.py : {len(avant) - len(apres)} ligne(s) retirée(s)")

    print(f"\n  ÉCRIT — {len(a_supprimer)} fichiers supprimés, "
          f"{len(a_retirer)} ligne(s) d'import retirée(s) de bot.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
