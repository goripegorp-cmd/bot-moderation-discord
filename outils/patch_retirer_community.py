"""Détache `community_features` de `slash_commands_2026.py` et `setup_wizard.py`.

Purge d'animation du 16/08/2026. `community_features` porte les « features pour
faire vivre la communauté » — question du jour, projecteur sur un membre, jours
à thème, digest hebdomadaire, relance des inactifs. Tout cela part.

Ce sont les DEUX derniers modules gardés qui l'importaient en dur (avec
`admin_panels_v2`, déjà traité, et `activity_tracker`, qui part aussi). Tant
qu'un seul subsiste, `detacher_module.py` refuse — à juste titre : un import dur
vers un fichier absent, c'est un bot qui ne démarre plus.

Ce qui part :
  · `slash_commands_2026` — le groupe `/community` (toggle, show) et son
    enregistrement dans `setup_all_commands` ;
  · `setup_wizard` — l'écran de l'assistant qui règle ces features.

⚠️ `/social`, `/permissions` et `/protection` restent intacts : ce sont les
autres groupes du même fichier, et ils ne relèvent pas de l'animation.

Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SLASH = RACINE / "slash_commands_2026.py"
WIZARD = RACINE / "setup_wizard.py"

SYMBOLES_SLASH = ("community_group", "_FEATURE_CHOICES", "comm_toggle", "comm_show")


def _couper(src: str, symboles: tuple, fichier: str) -> str | None:
    """Supprime des symboles de premier niveau, bornés par `ast`."""
    arbre = ast.parse(src)
    zones, trouves = [], set()
    for n in arbre.body:
        nom = getattr(n, "name", None)
        if nom is None and isinstance(n, ast.Assign) and n.targets:
            cible = n.targets[0]
            nom = cible.id if isinstance(cible, ast.Name) else None
        if nom in symboles:
            debut = n.lineno
            for d in getattr(n, "decorator_list", []):
                debut = min(debut, d.lineno)
            zones.append((debut, n.end_lineno, nom))
            trouves.add(nom)
    manquants = set(symboles) - trouves
    if manquants:
        print(f"❌ {fichier} : symboles introuvables {manquants} — abandon.")
        return None

    a_jeter = set()
    for debut, fin, nom in sorted(zones):
        a_jeter.update(range(debut, fin + 1))
        print(f"      {nom:<20} l.{debut}-{fin} ({fin - debut + 1} l.)")
    lignes = src.splitlines(keepends=True)
    return "".join(l for i, l in enumerate(lignes, 1) if i not in a_jeter)


def _controler(src: str, interdits: tuple, fichier: str) -> bool:
    try:
        arbre = ast.parse(src)
    except SyntaxError as ex:
        print(f"❌ {fichier} : ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return False
    residus = sorted({
        (n.lineno, n.id) for n in ast.walk(arbre)
        if isinstance(n, ast.Name) and n.id in interdits})
    if residus:
        print(f"❌ {fichier} : références résiduelles EN CODE :")
        for l, nom in residus[:10]:
            print(f"    l.{l} [{nom}]")
        return False
    return True


def main() -> int:
    apply_ = "--apply" in sys.argv

    # ── slash_commands_2026 ─────────────────────────────────────────────────
    print("── slash_commands_2026.py")
    src = SLASH.read_text(encoding="utf-8")
    neuf = _couper(src, SYMBOLES_SLASH, "slash_commands_2026")
    if neuf is None:
        return 1
    #  L'enregistrement du groupe, et l'import du module métier.
    neuf = neuf.replace(
        "    for grp in (permissions_group, social_group, protection_group, community_group):",
        "    for grp in (permissions_group, social_group, protection_group):")
    neuf = neuf.replace("import community_features as comm_mod\n", "")
    neuf = neuf.replace('    "community_group",\n', "")
    if not _controler(neuf, ("comm_mod",) + SYMBOLES_SLASH, "slash_commands_2026"):
        return 1
    print(f"  {src.count(chr(10))} → {neuf.count(chr(10))} lignes · OK")

    # ── setup_wizard ────────────────────────────────────────────────────────
    #
    #  ⚠️ ICI, LE BLOC ENTIER — PAS LES LIGNES `comm_mod`.
    #  La première version de ce script retirait les trois lignes contenant
    #  `comm_mod`, ce qui laissait `cfg = ...` supprimé mais `cfg.` utilisé
    #  trente lignes plus bas : un `NameError` à la première exécution de
    #  l'assistant, avalé par le `try` et rangé dans `report["errors"]`. Un
    #  écran qui dit « appliqué » sans rien appliquer — exactement le défaut
    #  que ce dépôt paie depuis des mois. On borne donc sur DEUX ancres
    #  textuelles exactes, et on refuse d'écrire si l'une manque.
    print("── setup_wizard.py")
    src_w = WIZARD.read_text(encoding="utf-8")

    DEBUT = "    # 3. Community features\n"
    FIN = '        report["errors"].append(f"community: {ex}")\n'
    i = src_w.find(DEBUT)
    j = src_w.find(FIN)
    if i == -1 or j == -1 or j <= i:
        print("❌ setup_wizard : ancres du bloc community introuvables — abandon.")
        return 1
    j += len(FIN)
    bloc = src_w[i:j]
    print(f"      bloc « Community features » : {bloc.count(chr(10))} lignes")
    neuf_w = src_w[:i] + src_w[j:]
    neuf_w = neuf_w.replace("import community_features as comm_mod\n", "")

    if not _controler(neuf_w, ("comm_mod",), "setup_wizard"):
        return 1
    #  Le bloc supprimé était le dernier à écrire dans `report` avant la
    #  clôture : on vérifie que l'assistant se termine toujours proprement.
    if "state.completed = True" not in neuf_w:
        print("❌ setup_wizard : la clôture de l'assistant a disparu — abandon.")
        return 1
    print(f"  {src_w.count(chr(10))} → {neuf_w.count(chr(10))} lignes · OK")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    SLASH.write_text(neuf, encoding="utf-8", newline="")
    WIZARD.write_text(neuf_w, encoding="utf-8", newline="")
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
