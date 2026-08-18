"""Le bouton « Relever maintenant » relève AUSSI les actualités.

Sans ça, le bouton ne prouvait rien sur ce flux : il relevait le catalogue et
les Limiteds, jamais le forum. Le propriétaire cliquait, lisait « relevé
réussi », et les actualités restaient muettes — sans que rien ne le dise.

Le compte-rendu des actualités suit la même règle que celui des articles :
nommer la cause quand rien ne sort (éteintes, pas de salon, déjà publiées,
refusées par Discord), jamais un « c'est normal » fourre-tout.

Écrit dans un fichier — piège n°3 du dépôt (heredocs). `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_panneau.py"

ANCIEN = '''            await veille.purger()
            self._dernier = self._compte_rendu(len(rel["articles"]), envoyes,
                                               motifs, salons_absents)
            await self.render_to(i, edit=True)
'''

NOUVEAU = '''            await veille.purger()
            compte_rendu = self._compte_rendu(len(rel["articles"]), envoyes,
                                              motifs, salons_absents)

            #  ── LES ACTUALITÉS, dans le même geste ───────────────────────
            #  ⚠️ Sans ce bloc, le bouton ne prouvait RIEN sur ce flux : il
            #  relevait le catalogue et les Limiteds, jamais le forum. Le
            #  propriétaire lisait « relevé réussi » et les actualités
            #  restaient muettes, sans qu'une ligne ne le dise.
            compte_rendu += "\\n" + await self._relever_actualites()
            self._dernier = compte_rendu
            await self.render_to(i, edit=True)
'''

METHODE_ANCRE = '''    @staticmethod
    def _compte_rendu(lus: int, envoyes: int, motifs: dict,
                      salons_absents: list) -> str:'''

METHODE = '''    async def _relever_actualites(self) -> str:
        """Relève les 5 sources d'actualité et publie ce qui doit sortir.

        Rend un compte-rendu qui NOMME la cause quand rien ne sort. Une source
        à la fois, avec pause — c'est la concurrence que le pare-feu punit.
        """
        try:
            c = await news.config(self.g.id)
            if not c["roblox_news_enabled"]:
                return ("📢 Actualités — ⚪ **éteintes**, rien n'a été relevé. "
                        "Allumez-les avec le bouton « Actus ».")
            salon = self.g.get_channel(int(c.get("roblox_news_salon", 0) or 0))
            if salon is None:
                return ("📢 Actualités — 🔴 **aucun salon réglé**, rien ne peut "
                        "sortir. Réglez « 📢 Actualité Roblox » ci-dessus.")

            lus, envoyes, deja, refuses, en_panne = 0, 0, 0, 0, []
            for src in news.SOURCES:
                rel = await news.relever(src)
                if rel["code"] != 200:
                    en_panne.append(f"`{src['cle']}` ({_ou_tiret(rel['code'])})")
                    await asyncio.sleep(1.5)
                    continue
                lus += len(rel["billets"])
                #  Même ordre que la boucle : du plus ancien au plus récent,
                #  et le même plafond par source.
                for b in veille.ordonner_publication(
                        rel["billets"], news.MAX_BILLETS_PAR_PASSAGE):
                    if envoyes >= veille.MAX_PUBLICATIONS_PAR_PASSAGE:
                        break
                    if await news.deja_publie(self.g.id, b["topic_id"]):
                        deja += 1
                        continue
                    if await publier_actu(self.g, salon, b):
                        await news.marquer_publie(self.g.id, b["topic_id"])
                        envoyes += 1
                    else:
                        refuses += 1
                await asyncio.sleep(1.5)
            await news.purger()

            detail = []
            if en_panne:
                detail.append(f"source(s) en panne : {', '.join(en_panne)}")
            if refuses:
                detail.append(f"`{refuses}` **refusée(s) par Discord** — permissions "
                              f"du salon (voir les journaux)")
            if deja:
                detail.append(f"`{deja}` déjà publiée(s) — « ♻️ Tout republier » "
                              f"les libère")
            panne = bool(en_panne or refuses)
            icone = "🔴" if panne else ("🟢" if envoyes else "⚪")
            txt = (f"📢 Actualités — {icone} `{lus}` billet(s) frais lus, "
                   f"`{envoyes}` **réellement publié(s)**.")
            if detail:
                txt += "\\n" + "\\n".join(f"-# • {d}." for d in detail)
            elif not envoyes:
                txt += ("\\n-# • Rien de neuf depuis le dernier passage : "
                        "c'est normal, le forum publie environ un billet par jour.")
            return txt
        except Exception as ex:
            _log(f"[roblox relever actualites] {ex}")
            return f"📢 Actualités — ❌ erreur : `{type(ex).__name__}`"

    @staticmethod
    def _compte_rendu(lus: int, envoyes: int, motifs: dict,
                      salons_absents: list) -> str:'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    for nom, ancre in (("bloc relever", ANCIEN), ("méthode", METHODE_ANCRE)):
        if src.count(ancre) != 1:
            print(f"❌ ancre « {nom} » trouvée {src.count(ancre)} fois — abandon.")
            return 1
    neuf = src.replace(ANCIEN, NOUVEAU).replace(METHODE_ANCRE, METHODE)
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    noms = {getattr(n, "name", None) for n in arbre.body}
    assert "RobloxPanelV2" in noms
    print(f"  roblox_panneau.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
