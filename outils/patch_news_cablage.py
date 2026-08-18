"""Câble les nouvelles sources d'actualité : boucle, bouton, fiche.

  · la boucle saute proprement une source non échue (sans dormir 2 s pour
    rien, sans la compter en panne) ;
  · « Relever maintenant » FORCE la cadence — un bouton de vérification qui
    respecterait l'échéance dirait « 0 lu » sur une source relevée il y a
    dix minutes, et le propriétaire croirait la source morte ;
  · la fiche préfère le lien reconstruit par la source (`billet["lien"]`), et
    ne retombe sur `lien_billet(topic_id)` — le forum — qu'à défaut.

Écrit dans un fichier — piège n°3. `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

PATCHS = {
    RACINE / "bot.py": [
        ('''                rel = await roblox_news_module.relever(src)
                if rel["code"] != 200:
                    await asyncio.sleep(2)
                    continue
''',
         '''                rel = await roblox_news_module.relever(src)
                #  Source non échue selon son propre rythme : on passe, sans
                #  la compter en panne et sans dormir pour rien.
                if rel.get("sautee"):
                    continue
                if rel["code"] != 200:
                    await asyncio.sleep(2)
                    continue
'''),
    ],
    RACINE / "roblox_panneau.py": [
        ('''                rel = await news.relever(src)
''',
         '''                #  ⚠️ `forcer=True` : un bouton de vérification qui respecterait
                #  la cadence dirait « 0 lu » sur une source relevée dix minutes
                #  plus tôt, et on la croirait morte.
                rel = await news.relever(src, forcer=True)
'''),
        ('''    lien = news.lien_billet(billet.get("topic_id"))
    items = [
        v2_title(f"📢 {_ou_tiret(billet.get('domaine'))}"),
''',
         '''    #  Le lien vient de la SOURCE quand elle l'a reconstruit et validé
    #  (presse, newsroom) ; le forum n'a qu'un identifiant entier, d'où le
    #  repli sur `lien_billet`. Jamais une URL recopiée telle quelle.
    lien = billet.get("lien") or news.lien_billet(billet.get("topic_id"))
    items = [
        v2_title(f"📢 {_ou_tiret(billet.get('domaine'))}"),
'''),
    ],
}


def main() -> int:
    for chemin, remplacements in PATCHS.items():
        src = chemin.read_text(encoding="utf-8")
        avant = {getattr(n, "name", None) for n in ast.parse(src).body}
        neuf = src
        for a, b in remplacements:
            if neuf.count(a) != 1:
                print(f"❌ {chemin.name} : ancre trouvée {neuf.count(a)} fois — abandon.")
                print("   " + a.strip().splitlines()[0][:80])
                return 1
            neuf = neuf.replace(a, b)
        try:
            arbre = ast.parse(neuf)
        except SyntaxError as ex:
            print(f"❌ {chemin.name} : ast.parse échoue l.{ex.lineno}")
            return 1
        if avant - {getattr(n, "name", None) for n in arbre.body}:
            print(f"❌ {chemin.name} : symboles perdus")
            return 1
        print(f"  {chemin.name} : {len(remplacements)} remplacement(s) · ast OK")
        if "--apply" in sys.argv:
            chemin.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT." if "--apply" in sys.argv else "  PREVIEW — rien écrit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
