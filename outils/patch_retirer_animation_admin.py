"""Retire d'`admin_panels_v2.py` ce qui relève de l'animation.

Purge du 16/08/2026 : « toutes les animations du serveur, tu les cut ».

Ce qui part :
  · `CommunityPanelV2` — toggles des « features communautaires » ;
  · `_summary_community` — son résumé ;
  · `AdminMasterPanelV2` — le tableau de bord de `/admin`, commande retirée.
    Il n'était plus atteignable que comme repli de `_revenir`, lui-même
    remplacé par un message honnête ;
  · les imports de `community_features`, qui devient détachable.

Ce qui RESTE, et c'est délibéré : `PermissionsPanelV2`, `ProtectionPanelV2` et
toute la famille `Social*`. Les deux premiers sont de la sécurité ; le dernier
est l'onglet « Réseaux sociaux » de `/configure`, branché le 16/08.

⚠️ Les boutons « Retour » des panneaux gardés pointaient vers
`AdminMasterPanelV2`. Les laisser produirait un `NameError` au clic — un bouton
qui plante en public. Ils passent tous par `_revenir()`.

Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "admin_panels_v2.py"

#  `setup_admin_command` construisait `/admin`. bot.py ne l'appelle plus depuis
#  le retrait de la commande (voir le commentaire de son import) : la fonction
#  était devenue du code mort qui retenait `AdminMasterPanelV2` en vie.
SYMBOLES = ("AdminMasterPanelV2", "CommunityPanelV2", "_summary_community",
            "setup_admin_command")

#  Les appels de retour à réécrire, forme exacte.
RETOURS = [
    ("await AdminMasterPanelV2(self.owner, self.guild).render_to(i)",
     "await _revenir(self.owner, self.guild, i)"),
    ("await AdminMasterPanelV2(self.owner, self.guild).render_to(interaction)",
     "await _revenir(self.owner, self.guild, interaction)"),
]

#  Les lignes d'import à retirer, en bloc exact.
IMPORTS = """import community_features
from community_features import (
    load_config as load_community_config,
    save_config as save_community_config,
    CommunityConfig,
)
"""


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")

    # ── 1. Les retours, AVANT toute suppression ─────────────────────────────
    n_retours = 0
    for avant, apres in RETOURS:
        n_retours += src.count(avant)
        src = src.replace(avant, apres)
    print(f"  retours réécrits vers _revenir() : {n_retours}")

    # ── 2. Les imports ──────────────────────────────────────────────────────
    if IMPORTS not in src:
        print("❌ bloc d'imports community_features introuvable — abandon.")
        return 1
    src = src.replace(IMPORTS, "")
    print("  imports community_features retirés")

    # ── 3. Les symboles, bornés par `ast` — jamais par une devinette ────────
    arbre = ast.parse(src)
    zones = []
    for n in arbre.body:
        if getattr(n, "name", None) in SYMBOLES:
            debut = n.lineno
            for d in getattr(n, "decorator_list", []):
                debut = min(debut, d.lineno)
            zones.append((debut, n.end_lineno, n.name))
    if len(zones) != len(SYMBOLES):
        trouves = {z[2] for z in zones}
        print(f"❌ symboles introuvables : {set(SYMBOLES) - trouves} — abandon.")
        return 1

    a_jeter = set()
    for debut, fin, nom in sorted(zones):
        a_jeter.update(range(debut, fin + 1))
        print(f"      {nom:<24} l.{debut}-{fin} ({fin - debut + 1} l.)")

    lignes = src.splitlines(keepends=True)
    src = "".join(l for i, l in enumerate(lignes, 1) if i not in a_jeter)

    #  Le `__all__` du module cite les classes supprimées.
    for nom in SYMBOLES:
        src = src.replace(f'    "{nom}",\n', "")

    # ── 4. Les refus ────────────────────────────────────────────────────────
    try:
        arbre2 = ast.parse(src)
    except SyntaxError as ex:
        print(f"\n❌ ABANDON — ast.parse échoue : ligne {ex.lineno} : {ex.msg}")
        return 1

    residus = sorted({
        (n.lineno, n.id) for n in ast.walk(arbre2)
        if isinstance(n, ast.Name) and n.id in SYMBOLES})
    if residus:
        print("\n❌ ABANDON — références résiduelles EN CODE :")
        for l, nom in residus[:15]:
            print(f"    l.{l} [{nom}]")
        return 1

    print(f"\n  admin_panels_v2.py {len(lignes)} → {src.count(chr(10)) + 1} lignes")
    print("  ast.parse OK · aucune référence résiduelle en code")

    if "--apply" not in sys.argv:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    CIBLE.write_text(src, encoding="utf-8", newline="")
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
