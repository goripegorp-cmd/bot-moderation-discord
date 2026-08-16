"""Débranche les derniers câblages d'animation dans `on_ready` / `on_message`.

`couper_symboles.py` sait retirer un symbole et son `.start()`. Il ne touche PAS
aux appels enfouis dans un handler — et il a raison de refuser : ce sont des
instructions au milieu d'un corps de fonction, pas des définitions, et les
supprimer au jugé casserait le handler.

Ce script les retire par ancres textuelles EXACTES. Chaque bloc est donné en
entier, `try` compris : retirer l'appel sans son `try` laisserait un `try:` sans
corps, c'est-à-dire une SyntaxError au boot.

⚠️ CES HANDLERS SONT VITAUX. `on_ready` et `on_message` portent la sécurité
entière du bot. Le script refuse d'écrire si un seul bloc est introuvable, si
`ast.parse` échoue, ou si les symboles de premier niveau ne sont pas exactement
les mêmes avant et après — on ne perd pas un handler par inadvertance.

Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "bot.py"

#  (libellé, texte exact à retirer). L'ordre n'a pas d'importance : chaque bloc
#  est cherché tel quel.
BLOCS = [
    ("vue persistante du rituel du soir", """    try:
        bot.add_view(EveningRitualView())
    except Exception as ex:
        print(f"[on_ready add_view EveningRitualView] {ex}")
"""),
    ("vue persistante du push de quête", """    # Phase 44 — Daily Quest Push (DM persistent view)
    try:
        bot.add_view(DailyQuestPushView())
    except Exception as ex:
        print(f"[on_ready add_view DailyQuestPushView] {ex}")
"""),
    ("réattache des étapes de mission", """    # Phase 49 : re-attacher les MissionStepClickView actifs au boot
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT id, template_id, current_step FROM missions WHERE status='active'",
            ) as cur:
                rows = await cur.fetchall()
        for mid, tid, step_idx in rows:
            try:
                if not tmpl:
                    continue
                if step_idx >= len(tmpl["steps"]):
                    continue
                step = tmpl["steps"][step_idx]
                if step.get("goal_kind") == "button_click":
                    bot.add_view(MissionStepClickView(int(mid), int(step_idx), step.get("button_label", "Participer")))
            except Exception as ex:
                print(f"[on_ready mission persist mid={mid}] {ex}")
    except Exception as ex:
        print(f"[on_ready mission_step persist] {ex}")
"""),
    ("réattache des votes narratifs", """    # Phase 57 : re-attacher les NarrativeChoiceView open
    try:
        async with get_db() as db:
            async with db.execute(
                "SELECT id, choice_id FROM narrative_votes WHERE status='open'",
            ) as cur:
                rows = await cur.fetchall()
        for nv_id, choice_id in rows:
            try:
                if choice:
                    bot.add_view(NarrativeChoiceView(int(nv_id), choice))
            except Exception:
                pass
    except Exception as ex:
        print(f"[on_ready phase57 persist] {ex}")
"""),
    ("suivi des messages pour les missions",
     "            (_track_message_for_missions, '_track_message_for_missions'),\n"),
    ("chaîne du tag royale", """    # ═══════════════ Phase 43 : Tag Royale chain progression ═══════════════
    try:
        if msg.mentions:
            await _check_tag_royale_chain(msg)
    except Exception as ex:
        print(f"[_check_tag_royale_chain] {ex}")
"""),
    ("suivi des réactions pour les missions", """    # Phase 49 : tracking missions (étapes reactions_unique)
    try:
        await _track_reaction_for_missions(payload)
    except Exception as ex:
        print(f"[_track_reaction_for_missions] {ex}")
"""),
]


def _symboles(src: str) -> set:
    return {getattr(n, "name", None) for n in ast.parse(src).body
            if getattr(n, "name", None)}


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant_symboles = _symboles(src)
    avant_lignes = src.count("\n")

    neuf = src
    for libelle, bloc in BLOCS:
        n = neuf.count(bloc)
        if n != 1:
            print(f"❌ « {libelle} » : {n} occurrence(s), 1 attendue — abandon.")
            return 1
        neuf = neuf.replace(bloc, "")
        print(f"  retiré · {libelle} ({bloc.count(chr(10))} lignes)")

    try:
        ast.parse(neuf)
    except SyntaxError as ex:
        print(f"\n❌ ABANDON — ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1

    apres_symboles = _symboles(neuf)
    perdus = avant_symboles - apres_symboles
    if perdus:
        print(f"\n❌ ABANDON — symboles de premier niveau PERDUS : {perdus}")
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
