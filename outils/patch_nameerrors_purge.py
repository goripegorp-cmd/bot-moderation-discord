"""Ferme les 4 derniers NameError laissés par la purge, trouvés par verif_portees.

D'OÙ ILS VIENNENT
La purge d'animation a retiré des systèmes entiers (classes RP, MP d'événement,
programme du jour, stats de jeux) mais a laissé DERRIÈRE elle les morceaux qui
les LISAIENT. Ces morceaux référencent des variables qui n'existent plus.
Python ne s'en plaint qu'à l'exécution, et un `except Exception` avale la
plainte : le défaut est invisible jusqu'à ce qu'un membre tombe dessus.

C'est la même famille que `name 'ok' is not defined`, qui tournait une dizaine
de fois par jour dans les logs Railway sans que rien ne le signale.

⚠️ `verif_noms.py` EST VERT SUR LES QUATRE. Il aplatit toutes les portées dans
un seul ensemble : un nom assigné n'importe où passe pour connu partout. Seul
`verif_portees.py` (écrit le 19/08) les voit.

CE QUE CHACUN CASSE, VRAIMENT
  1. `cls` — /admin_journey l.41492. La commande admin CRASHE à la ligne
     « Classe RP » : le propriétaire reçoit « ❌ Erreur » au lieu de la fiche.
     Le système de classes RP est parti à la purge. → on retire la ligne et le
     champ de l'embed ; le reste de la fiche revient.
  2. `sent` — `weekly_activity_recap_task`. Le corps qui envoyait les MP est
     parti avec le module `dm_notify` (12/08) ; `dm_event_optin`, dont elle
     dépendait, n'existe plus que dans sa docstring. Il ne reste qu'un marqueur
     anti-doublon écrit en base, puis le NameError. La boucle se réveille
     24 fois par jour pour ne rien envoyer. → RETIRÉE en entier (déf +
     before_loop + `.start()`). Vérifié : elle n'est pas dans
     `_SUPERVISED_LOOP_NAMES` — piège n°2 sans objet ici, mais contrôlé.
  3. `body` — `_post_daily_agenda`. Fonction JAMAIS APPELÉE (son unique
     référence est sa propre définition) et cassée : `body` n'est calculé nulle
     part. Du code mort qui ne peut que mentir à une relecture. → RETIRÉE.
  4. `games` — `game_stats_set_cmd`. Son propre commentaire dit « Phase 120 :
     retiré (debug inutilisé) » : le `@bot.tree.command` a été enlevé, laissant
     un `@app_commands.describe` orphelin sur une fonction que plus rien
     n'atteint. → RETIRÉE avec son décorateur pendant.

⚠️ COUPES BORNÉES PAR L'AST — piège n°1 du dépôt : « ne jamais borner une coupe
sur la prochaine ligne `async def` ». On coupe de la première ligne du premier
décorateur jusqu'à `end_lineno`, ce qui couvre les classes imbriquées et les
chaînes de décorateurs. Après coupe : `ast.parse`, et comparaison des symboles
de niveau module avant/après pour prouver qu'on n'a emporté que les 4 visés.

Écrit dans un fichier puis exécuté (piège n°3 : les heredocs bash). `--apply`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "bot.py"

#  Fonctions de niveau module à retirer ENTIÈREMENT.
A_RETIRER = ["weekly_activity_recap_task", "_weekly_recap_wait",
             "_post_daily_agenda", "game_stats_set_cmd"]

#  Remplacements exacts (petits morceaux à l'intérieur de fonctions gardées).
REMPLACEMENTS = [
    #  1. /admin_journey : le calcul et le champ « Classe RP ».
    (
        """        # Class
        cls_str = f"{cls['emoji']} {cls['name']}" if cls else "_Aucune_"
""",
        """        #  ⚠️ « Classe RP » retirée le 19/08/2026 : le système de classes est
        #  parti à la purge, mais la ligne qui le LISAIT était restée. Elle
        #  levait `NameError: name 'cls' is not defined` À CHAQUE APPEL — la
        #  commande entière rendait « ❌ Erreur » au lieu de la fiche membre.
""",
    ),
    (
        """                f"## ⚔️ Profil\\n"
                f"**Classe RP :** {cls_str}\\n"
""",
        """                f"## ⚔️ Profil\\n"
""",
    ),
    #  2. Le lancement au boot de la boucle retirée.
    (
        """    # Phase 238 : récap hebdo en MP (opt-in strict)
    if not weekly_activity_recap_task.is_running():
        weekly_activity_recap_task.start()
""",
        """    #  (Récap hebdo en MP retiré le 19/08/2026 : le module `dm_notify` qui
    #   envoyait les MP, et l'opt-in `dm_event_optin` dont il dépendait, sont
    #   partis à la purge. Il ne restait qu'une boucle qui se réveillait toutes
    #   les heures pour écrire un marqueur puis lever un NameError.)
""",
    ),
]


def _bornes(arbre, nom: str) -> tuple[int, int]:
    """(première ligne, dernière ligne) 1-indexées, décorateurs COMPRIS.

    ⚠️ Piège n°1 du dépôt : borner sur « la prochaine ligne async def » couperait
    au milieu d'une classe imbriquée (`_GameStatsLayout` vit DANS
    `game_stats_set_cmd`). `end_lineno` de l'AST est la seule borne juste."""
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            debut = min([n.lineno] + [d.lineno for d in n.decorator_list])
            return debut, n.end_lineno
    raise AssertionError(f"{nom} introuvable au niveau module")


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    avant = {getattr(n, "name", None) for n in arbre.body}

    #  ═══ 1. Les remplacements ciblés ═══
    neuf = src
    for vieux, nouveau in REMPLACEMENTS:
        if neuf.count(vieux) != 1:
            print(f"❌ motif trouvé {neuf.count(vieux)} fois :\n{vieux[:90]}…")
            return 1
        neuf = neuf.replace(vieux, nouveau, 1)

    #  ═══ 2. Les retraits de fonctions, du bas vers le haut ═══
    #  (du bas vers le haut : sinon chaque coupe décale les lignes suivantes)
    arbre2 = ast.parse(neuf)
    plages = sorted((_bornes(arbre2, nom) + (nom,) for nom in A_RETIRER),
                    key=lambda p: -p[0])
    lignes = neuf.splitlines(keepends=True)
    for debut, fin, nom in plages:
        print(f"    − {nom}  l.{debut}→{fin}  ({fin - debut + 1} lignes)")
        lignes[debut - 1:fin] = []
    neuf = "".join(lignes)

    #  ═══ 3. Preuves ═══
    try:
        arbre3 = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    apres = {getattr(n, "name", None) for n in arbre3.body}
    perdus = (avant - apres) - set(A_RETIRER)
    if perdus:
        print(f"❌ symboles emportés par erreur : {perdus}")
        return 1
    restants = set(A_RETIRER) & apres
    if restants:
        print(f"❌ pas retirés : {restants}")
        return 1
    for nom in A_RETIRER:
        if nom in neuf:
            print(f"❌ « {nom} » encore référencé ailleurs — un appel resterait mort.")
            return 1

    print(f"  bot.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK · "
          f"{len(avant) - len(apres)} symbole(s) de moins")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
