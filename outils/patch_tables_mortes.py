"""Retire les `CREATE TABLE` des tables que plus aucun code ne touche.

Après la purge d'animation du 16/08/2026, 26 tables étaient encore créées à
chaque démarrage sans qu'une seule requête ne les lise ni ne les écrive. Ce
n'est pas une fuite, mais c'est un mensonge de schéma : la prochaine lecture du
fichier croira que ces systèmes existent.

⚠️ CE SCRIPT NE SUPPRIME AUCUNE DONNÉE. Il retire les instructions `CREATE
TABLE IF NOT EXISTS`, pas les tables déjà présentes dans la base de production.
Les anciennes données restent où elles sont, intactes — les effacer serait une
opération irréversible qui demande une décision explicite du propriétaire, pas
un effet de bord de purge.

La détection est refaite ICI, pas recopiée : une table est « morte » si aucun
`FROM`, `INTO`, `UPDATE` ni `JOIN` ne la nomme dans tout le dépôt (bot.py ET les
modules — une table peut très bien être créée par bot.py et lue par un module).

Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CIBLE = RACINE / "bot.py"


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")

    #  Tout le dépôt, pas seulement bot.py.
    tout = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in RACINE.glob("*.py"))

    creees = sorted(set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src)))
    mortes = [t for t in creees
              if not re.search(rf"(?:FROM|INTO|UPDATE|JOIN)\s+{t}\b", tout)]

    if not mortes:
        print("  Aucune table morte — rien à faire.")
        return 0

    print(f"  {len(creees)} tables créées par bot.py · {len(mortes)} mortes")

    lignes = src.splitlines(keepends=True)
    a_jeter = set()
    for i, ligne in enumerate(lignes, 1):
        m = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", ligne)
        if not m or m.group(1) not in mortes:
            continue
        #  L'instruction s'étend jusqu'à la fermeture de l'appel `execute(`.
        #  On avance tant que les parenthèses ne sont pas équilibrées : borner
        #  sur « la prochaine ligne qui ressemble à la fin » est exactement la
        #  devinette qui a coûté deux sur-coupes à ce dépôt.
        j, solde = i, 0
        while j <= len(lignes):
            solde += lignes[j - 1].count("(") - lignes[j - 1].count(")")
            a_jeter.add(j)
            if solde <= 0 and j > i - 1:
                break
            j += 1
        print(f"      {m.group(1):<26} l.{i}-{j}")

    neuf = "".join(l for i, l in enumerate(lignes, 1) if i not in a_jeter)

    try:
        ast.parse(neuf)
    except SyntaxError as ex:
        print(f"\n❌ ABANDON — ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1

    #  Aucun symbole de premier niveau ne doit disparaître : on ne retire que
    #  des instructions à l'intérieur de fonctions d'initialisation.
    av = {getattr(n, "name", None) for n in ast.parse(src).body}
    ap = {getattr(n, "name", None) for n in ast.parse(neuf).body}
    if av - ap:
        print(f"\n❌ ABANDON — symboles perdus : {av - ap}")
        return 1

    print(f"\n  bot.py {len(lignes)} → {neuf.count(chr(10)) + 1} lignes")
    print("  ast.parse OK · aucun symbole perdu · AUCUNE donnée touchée")

    if "--apply" not in sys.argv:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
