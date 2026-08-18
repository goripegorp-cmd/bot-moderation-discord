"""La boucle de veille Roblox dit ce qu'elle fait — une ligne par passage.

Elle était MUETTE : `return` sans un mot quand rien n'est actif, rien à la fin
d'un passage réussi. Sur Railway, impossible de savoir si elle a tourné, ce
qu'elle a vu, ce qu'elle a publié. Le propriétaire constate « rien n'est
posté » et personne — ni lui, ni moi — ne peut dire pourquoi depuis les logs.

Trois lignes, et pas plus (une boucle bavarde noie le vrai signal) :
  · quand aucun serveur n'a rien allumé : le dire, avec le nombre de serveurs ;
  · à la fin de chaque passage : combien de guildes, combien d'articles lus,
    combien de billets, combien PUBLIÉS et REPORTÉS ;
  · le compteur de publications réelles est désormais tenu — il ne l'était pas.

Écrit dans un fichier — piège n°3 (heredocs). `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "bot.py"

REMPLACEMENTS = [
    # 1. le retour muet
    ('''        if not guildes_items and not guildes_news:
            return
''',
     '''        if not guildes_items and not guildes_news:
            #  ⚠️ LE DIRE. Cette boucle était muette : elle sortait sans un mot,
            #  et depuis les logs Railway rien ne distinguait « personne n'a
            #  allumé » de « la boucle est morte ». Une ligne toutes les 30 min
            #  ne coûte rien et répond à la question avant qu'on la pose.
            print(f"[veille_roblox_task] passage sans travail — aucun des "
                  f"{len(bot.guilds)} serveur(s) n'a allumé accessoires ni "
                  f"actualités (interrupteur + salon requis)")
            return
        _publies = 0
'''),
    # 2. compter les publications réelles (articles)
    ('''                            if await roblox_ui.publier(g, salon, a, flux,
                                                      image=_imgs.get(a["asset_id"])):
                                await roblox_module.marquer_publie(g.id, a["asset_id"], flux)
                                _budget -= 1
''',
     '''                            if await roblox_ui.publier(g, salon, a, flux,
                                                      image=_imgs.get(a["asset_id"])):
                                await roblox_module.marquer_publie(g.id, a["asset_id"], flux)
                                _budget -= 1
                                _publies += 1
'''),
    # 3. compter les publications réelles (actualités)
    ('''                        if await roblox_ui.publier_actu(g, salon, b):
                            await roblox_news_module.marquer_publie(g.id, b["topic_id"])
                            _budget -= 1
''',
     '''                        if await roblox_ui.publier_actu(g, salon, b):
                            await roblox_news_module.marquer_publie(g.id, b["topic_id"])
                            _budget -= 1
                            _publies += 1
'''),
    # 4. le bilan de fin de passage
    ('''        if _reporte:
            print(f"[veille_roblox_task] plafond atteint — {_reporte} publication(s) "
                  f"reportee(s) au prochain passage (dans 30 min). Rien n'est perdu.")
''',
     '''        #  Le bilan, TOUJOURS — pas seulement quand quelque chose déborde.
        #  C'est cette ligne qu'on cherche dans Railway quand « rien ne sort ».
        print(f"[veille_roblox_task] passage terminé — accessoires sur "
              f"{len(guildes_items)} serveur(s), actualités sur "
              f"{len(guildes_news)} · {_publies} publication(s) réelle(s) · "
              f"{_reporte} reportée(s)")
        if _reporte:
            print(f"[veille_roblox_task] plafond atteint — {_reporte} publication(s) "
                  f"reportee(s) au prochain passage (dans 30 min). Rien n'est perdu.")
'''),
]


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}
    neuf = src
    for k, (a, b) in enumerate(REMPLACEMENTS, 1):
        if neuf.count(a) != 1:
            print(f"❌ ancre n°{k} trouvée {neuf.count(a)} fois — abandon.")
            print("   " + a.strip().splitlines()[0][:90])
            return 1
        neuf = neuf.replace(a, b)
        print(f"  ✅ n°{k}")
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    if avant - {getattr(n, "name", None) for n in arbre.body}:
        print("❌ symboles perdus — abandon.")
        return 1
    print(f"  bot.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
