"""Fait passer TOUS les panneaux de `bot.py` par `_afficher_panneau()`.

LE SYMPTÔME, RAPPORTÉ EN DIRECT PAR LE PROPRIÉTAIRE
« Le panel est HS, quand je tape ça met échec de l'interaction. »

LA CAUSE
Discord donne **3 secondes** pour acquitter une interaction. Passé ce délai, il
affiche « L'interaction a échoué » et refuse toute réponse ultérieure.

Or aucun panneau de `bot.py` ne faisait `defer` : chacun ouvrait la base,
lisait sa configuration, parfois plusieurs fois, PUIS répondait. L'onglet
🎮 Veille Roblox est le plus lourd — quatre lectures (`veille.config`,
`news.config`, `veille.diagnostic`, `veille.actif`) avant le moindre mot à
Discord. Sur un démarrage à froid Railway, les 3 secondes tombent.

LE CORRECTIF, EN DEUX TEMPS
  1. `_module_select` fait `defer()` AVANT de construire le panneau : Discord
     est acquitté immédiatement, et le travail peut prendre son temps.
  2. Mais `defer()` consomme la réponse — les 34 blocs d'affichage qui
     appelaient `response.edit_message()` lèveraient alors `InteractionResponded`,
     transformant une panne en une autre. Ils passent donc tous par
     `_afficher_panneau()`, qui bascule sur `edit_original_response` quand la
     réponse est déjà consommée.

Sans le point 2, le point 1 casse les onze onglets. C'est pour ça que les deux
sont dans le même patch.

⚠️ Le remplacement est strictement une AMÉLIORATION : quand l'interaction n'est
pas encore répondue — le cas courant — le comportement est identique à l'octet
près. On ne change pas le chemin nominal, on ajoute le chemin manquant.

Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "bot.py"

ANCIEN = """        if edit:
            await interaction.response.edit_message(content=None, view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)
"""

NOUVEAU = """        await _afficher_panneau(self, interaction, edit)
"""

#  Le helper, posé juste avant le premier panneau qui s'en sert.
ANCRE_HELPER = "class RgpdPanelV2(LayoutView):"

HELPER = '''async def _afficher_panneau(vue, interaction, edit: bool) -> None:
    """Affiche un panneau — et supporte une interaction DÉJÀ acquittée.

    ⚠️ PIÈGE À NE PAS DÉFAIRE — « L'INTERACTION A ÉCHOUÉ », SIGNALÉ EN PROD.
    Discord laisse 3 secondes pour acquitter. Les panneaux lisent la base avant
    de répondre ; l'onglet Veille Roblox fait quatre lectures. Au-delà des 3 s,
    Discord affiche « L'interaction a échoué » et refuse tout.

    `_module_select` fait donc `defer()` d'abord. Mais `defer()` consomme la
    réponse : `response.edit_message()` lève ensuite `InteractionResponded`.
    D'où ce point de passage unique, qui choisit le bon appel selon l'état.

    Ne PAS revenir à `interaction.response.edit_message()` en direct : le
    chemin nominal est identique, seul le cas « déjà acquitté » change.
    """
    if edit:
        if interaction.response.is_done():
            await interaction.edit_original_response(
                content=None, view=vue, embed=None, attachments=[])
        else:
            await interaction.response.edit_message(
                content=None, view=vue, embed=None, attachments=[])
    else:
        if interaction.response.is_done():
            await interaction.followup.send(view=vue, ephemeral=True)
        else:
            await interaction.response.send_message(view=vue, ephemeral=True)


'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant_symboles = {getattr(n, "name", None) for n in ast.parse(src).body}
    avant_lignes = src.count("\n")

    n = src.count(ANCIEN)
    if n == 0:
        print("❌ bloc d'affichage introuvable — le fichier a changé.")
        return 1
    print(f"  {n} bloc(s) d'affichage à faire passer par _afficher_panneau()")

    neuf = src.replace(ANCIEN, NOUVEAU)

    if ANCRE_HELPER not in neuf:
        print(f"❌ ancre « {ANCRE_HELPER} » introuvable — abandon.")
        return 1
    if "_afficher_panneau" in src:
        print("❌ le helper existe déjà — patch déjà appliqué ?")
        return 1
    neuf = neuf.replace(ANCRE_HELPER, HELPER + ANCRE_HELPER, 1)
    print("  helper posé avant RgpdPanelV2")

    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"\n❌ ABANDON — ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1

    apres_symboles = {getattr(n_, "name", None) for n_ in arbre.body}
    perdus = avant_symboles - apres_symboles
    if perdus:
        print(f"\n❌ ABANDON — symboles perdus : {perdus}")
        return 1
    if "_afficher_panneau" not in apres_symboles:
        print("\n❌ ABANDON — le helper n'est pas au niveau module.")
        return 1

    print(f"\n  bot.py {avant_lignes} → {neuf.count(chr(10))} lignes")
    print(f"  ast.parse OK · {len(apres_symboles)} symboles, aucun perdu")

    if "--apply" not in sys.argv:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
