#!/usr/bin/env python3
"""verif_evenements.py — Chaque gestionnaire d'événement Discord est-il branché ?

═══════════════════════════════════════════════════════════════════════════════
POURQUOI CET OUTIL EXISTE
═══════════════════════════════════════════════════════════════════════════════
Le 12/08/2026, on a découvert que `on_member_join` n'avait AUCUN décorateur et
qu'aucun `bot.add_listener` ne la visait. C'était une fonction ordinaire que
personne n'appelait. Résultat : depuis des mois, rien ne se passait quand
quelqu'un rejoignait un serveur — anti-raid muet, anti-alt muet, gate +18 muet,
rôle d'arrivée jamais posé.

Aucun contrôle existant ne pouvait l'attraper :
  · `ast.parse` valide la SYNTAXE — un fichier sans décorateur est valide ;
  · `import bot` exécute le module — une fonction non branchée s'importe très
    bien, elle ne sert simplement à rien ;
  · `verif_noms.py` cherche les NameError — il n'y en a pas ;
  · les tests ne simulent pas de vraie arrivée Discord.

La panne était donc invisible à tout l'outillage. D'où ce script.

═══════════════════════════════════════════════════════════════════════════════
CE QU'IL VÉRIFIE
═══════════════════════════════════════════════════════════════════════════════
Toute fonction de premier niveau nommée `on_<evenement Discord connu>` doit être
enregistrée, par l'une de ces trois voies :
  · @bot.event
  · @bot.listen() / @bot.listen("on_x")
  · bot.add_listener(la_fonction, "on_x")   n'importe où dans le fichier

Les méthodes `on_submit`, `on_timeout`, `on_error` d'une classe (Modal, View)
sont IGNORÉES : discord.py les appelle par leur nom sur l'instance, elles n'ont
pas à être enregistrées. On ne regarde que le premier niveau du module.

Usage :  python outils/verif_evenements.py [fichier.py]
Sortie :  code 0 si tout est branché, 1 sinon.
"""
from __future__ import annotations

import ast
import sys

#  Les événements que discord.py appelle lui-même. Une fonction de premier
#  niveau portant l'un de ces noms EST forcément un gestionnaire : il n'y a
#  aucune raison légitime d'en écrire un et de ne pas le brancher.
EVENEMENTS = {
    "on_ready", "on_connect", "on_disconnect", "on_resumed", "on_error",
    "on_shard_ready", "on_shard_connect", "on_shard_disconnect",
    "on_message", "on_message_edit", "on_message_delete",
    "on_bulk_message_delete", "on_raw_message_edit", "on_raw_message_delete",
    "on_raw_bulk_message_delete",
    "on_reaction_add", "on_reaction_remove", "on_reaction_clear",
    "on_raw_reaction_add", "on_raw_reaction_remove", "on_raw_reaction_clear",
    "on_member_join", "on_member_remove", "on_member_update",
    "on_member_ban", "on_member_unban", "on_user_update",
    "on_raw_member_remove",
    "on_guild_join", "on_guild_remove", "on_guild_update",
    "on_guild_available", "on_guild_unavailable",
    "on_guild_channel_create", "on_guild_channel_delete",
    "on_guild_channel_update", "on_guild_channel_pins_update",
    "on_guild_role_create", "on_guild_role_delete", "on_guild_role_update",
    "on_guild_emojis_update", "on_guild_stickers_update",
    "on_invite_create", "on_invite_delete",
    "on_webhooks_update", "on_integration_create", "on_integration_update",
    "on_voice_state_update", "on_presence_update", "on_typing",
    "on_interaction", "on_app_command_completion",
    "on_thread_create", "on_thread_join", "on_thread_remove",
    "on_thread_delete", "on_thread_update", "on_thread_member_join",
    "on_raw_poll_vote_add", "on_raw_poll_vote_remove",
    "on_audit_log_entry_create", "on_automod_rule_create",
    "on_automod_action", "on_scheduled_event_create",
    "on_entitlement_create", "on_entitlement_update",
}


def _nom_decorateur(d: ast.expr) -> str:
    """Le décorateur, rendu en texte, quelle que soit sa forme."""
    try:
        return ast.unparse(d)
    except Exception:
        return ""


def analyser(chemin: str) -> list[str]:
    """Rend la liste des gestionnaires NON branchés. Vide = tout va bien."""
    with open(chemin, encoding="utf-8") as f:
        arbre = ast.parse(f.read())

    #  Tout ce que `bot.add_listener(fn, "on_x")` enregistre à la main.
    enregistres_a_la_main: set[str] = set()
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        cible = _nom_decorateur(n.func)
        if not cible.endswith("add_listener"):
            continue
        if n.args and isinstance(n.args[0], ast.Name):
            enregistres_a_la_main.add(n.args[0].id)

    orphelins = []
    #  ⚠️ Premier niveau SEULEMENT : `arbre.body`, pas `ast.walk`. Les méthodes
    #  `on_submit` d'un Modal sont appelées par nom sur l'instance et n'ont rien
    #  à enregistrer — les inclure produirait des dizaines de faux positifs, et
    #  un outil qui crie tout le temps finit par ne plus être lancé.
    for n in arbre.body:
        if not isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if n.name not in EVENEMENTS:
            continue
        decs = [_nom_decorateur(d) for d in n.decorator_list]
        branche = any(
            d.endswith(".event") or ".listen" in d or ".error" in d
            for d in decs
        ) or n.name in enregistres_a_la_main
        if not branche:
            orphelins.append(
                f"{n.name} (ligne {n.lineno}) — "
                f"décorateurs : {decs or 'AUCUN'}")
    return orphelins


def main() -> int:
    fichier = sys.argv[1] if len(sys.argv) > 1 else "bot.py"
    try:
        orphelins = analyser(fichier)
    except FileNotFoundError:
        print(f"  {fichier} : introuvable.")
        return 1
    except SyntaxError as ex:
        print(f"  {fichier} : ne se parse pas — {ex}")
        return 1

    if not orphelins:
        print(f"  {fichier} : tous les gestionnaires d'événements sont branchés.")
        return 0

    print(f"  {fichier} : {len(orphelins)} GESTIONNAIRE(S) JAMAIS APPELÉ(S) !")
    for o in orphelins:
        print(f"    - {o}")
    print("  Une fonction on_* non enregistrée ne s'exécute JAMAIS : tout ce")
    print("  qu'elle contient (protections comprises) est inerte.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
