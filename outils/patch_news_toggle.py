"""Branche l'interrupteur des ACTUALITÉS dans le panneau Roblox.

LE DÉFAUT, CONSTATÉ PAR LE PROPRIÉTAIRE LE 16/08
    « Aucun de tes systèmes concernant les news et les actualités ne sont
    annoncés dans le serveur. Rien n'est annoncé, absolument rien. »

LA CAUSE
`roblox_news_enabled` n'était écrit NULLE PART — ni bouton, ni commande.
`roblox_news.actif()` rendait donc toujours faux, `guildes_news` restait vide,
et le bloc actualité de la boucle ne s'exécutait JAMAIS. Le salon se réglait,
la santé se calculait, et rien ne sortait. Vérifié : 5 sources sur 5 en
HTTP 200, 29 billets frais disponibles le jour du constat.

C'est le cas exact du briefing : « clé de config sans interface donc toujours
à 0 » — le 5ᵉ des sept cas de code présent qui ne s'exécute jamais.

CE QUE CE PATCH POSE
  · un bouton « Actus allumées / éteintes », avec amorce raisonnable au
    premier allumage (la semaine écoulée sort, le reste est absorbé) ;
  · la santé des sources d'actualité, qui était calculée mais affichée nulle
    part ;
  · la ligne « Système » montre les DEUX interrupteurs ;
  · le bouton « Relever maintenant » relève AUSSI les actualités et compte ce
    qu'il a publié, avec la cause quand rien ne sort ;
  · le bouton ♻️ efface AUSSI les marques d'actualité.

⚠️ Écrit dans un fichier et non en heredoc : piège n°3 du dépôt, les heredocs
bash mangent les `\n` — l'ancre `"\n".join(sante)` était introuvable en heredoc.
Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_panneau.py"

REMPLACEMENTS = [
    # ── 1. Diagnostic + état des news
    ('''            diag = await veille.diagnostic()
            en_marche = await veille.actif(self.g.id)
''',
     '''            diag = await veille.diagnostic()
            en_marche = await veille.actif(self.g.id)
            #  ⚠️ La santé des ACTUALITÉS était calculée (`news.diagnostic`)
            #  mais affichée NULLE PART. Une source muette ressemble à une
            #  source calme — c'est le défaut n°4 de ROBLOX.md, et il était là.
            try:
                diag_news = await news.diagnostic()
            except Exception as ex:
                _log(f"[RobloxPanelV2 diag news] {ex}")
                diag_news = []
            news_en_marche = await news.actif(self.g.id)
'''),

    # ── 2. Santé des news, après la santé des articles
    ('''                sante_txt = "\\n".join(sante)
            else:
                sante_txt = "⚪ aucun relevé effectué pour l'instant"
''',
     '''                sante_txt = "\\n".join(sante)
            else:
                sante_txt = "⚪ aucun relevé effectué pour l'instant"

            if diag_news:
                sante_news = []
                for s_ in diag_news:
                    icone = "🟢" if s_["echecs"] == 0 else "🔴"
                    sante_news.append(f"{icone} `{s_['cle']}` · code "
                                      f"`{_ou_tiret(s_['code'])}`"
                                      + (f" · {s_['echecs']} échec(s) d'affilée"
                                         if s_["echecs"] else ""))
                sante_news_txt = "\\n".join(sante_news)
            else:
                sante_news_txt = "⚪ aucun relevé d'actualité pour l'instant"
'''),

    # ── 3. Ligne « Système » : les DEUX interrupteurs
    ('''                v2_body(
                    f"{'🟢' if c['roblox_veille_enabled'] else '⚪'} **Système** · "
                    + ("allumé" if c["roblox_veille_enabled"] else "éteint")
                    + ("" if en_marche or not c["roblox_veille_enabled"]
                       else "  ⚠️ _aucun salon défini, rien ne sortira_")),
''',
     '''                v2_body(
                    f"{'🟢' if c['roblox_veille_enabled'] else '⚪'} **Accessoires** · "
                    + ("allumés" if c["roblox_veille_enabled"] else "éteints")
                    + ("" if en_marche or not c["roblox_veille_enabled"]
                       else "  ⚠️ _aucun salon défini, rien ne sortira_")
                    + "\\n"
                    #  ⚠️ CET INTERRUPTEUR N'EXISTAIT PAS. `roblox_news_enabled`
                    #  n'était écrit nulle part — ni bouton, ni commande — donc
                    #  `actif()` rendait toujours faux et le bloc actualité de
                    #  la boucle ne s'exécutait JAMAIS. Le salon se réglait, la
                    #  santé se calculait, et rien ne sortait. Constaté par le
                    #  propriétaire le 16/08 : « 0 fond sur les actus ».
                    + f"{'🟢' if c['roblox_news_enabled'] else '⚪'} **Actualités** · "
                    + ("allumées" if c["roblox_news_enabled"] else "éteintes")
                    + ("" if news_en_marche or not c["roblox_news_enabled"]
                       else "  ⚠️ _aucun salon d'actualité défini, rien ne sortira_")),
'''),

    # ── 4. État des relevés : bloc news
    ('''                v2_body(f"**État des relevés**\\n{sante_txt}\\n"
                        f"-# `{diag['articles_connus']}` article(s) connu(s)"),
''',
     '''                v2_body(f"**État des relevés — accessoires**\\n{sante_txt}\\n"
                        f"-# `{diag['articles_connus']}` article(s) connu(s)"),
                v2_body(f"**État des relevés — actualités**\\n{sante_news_txt}"),
'''),

    # ── 5. Bouton d'allumage des news
    ('''            b_on.callback = self._cb_toggle

            b_test = Button(label="Relever maintenant", emoji="🔄",''',
     '''            b_on.callback = self._cb_toggle

            b_news = Button(
                label="Actus allumées" if c["roblox_news_enabled"] else "Actus éteintes",
                emoji="🟢" if c["roblox_news_enabled"] else "⚪",
                style=(discord.ButtonStyle.success if c["roblox_news_enabled"]
                       else discord.ButtonStyle.secondary),
                custom_id="rblx_toggle_news")
            b_news.callback = self._cb_toggle_news

            b_test = Button(label="Relever maintenant", emoji="🔄",'''),

    # ── 6. Deux rangées de boutons (5 max par ligne)
    ('''            items.append(discord.ui.ActionRow(b_on, b_test, b_reset, b_back))
''',
     '''            #  Deux rangées : Discord refuse plus de 5 boutons par ligne, et
            #  regrouper les deux interrupteurs ensemble se lit mieux.
            items.append(discord.ui.ActionRow(b_on, b_news))
            items.append(discord.ui.ActionRow(b_test, b_reset, b_back))
'''),

    # ── 7. Le callback du nouvel interrupteur, juste après _cb_toggle
    ('''    async def _cb_relever(self, i):
        """Un relevé immédiat, pour vérifier que la chaîne fonctionne.
''',
     '''    async def _cb_toggle_news(self, i):
        """Allume ou éteint les ACTUALITÉS. Amorce raisonnable au premier
        allumage : la semaine écoulée sort, le reste est absorbé.

        Voir `news.amorcer` — la première version de l'amorce absorbait TOUT et
        le propriétaire devait attendre le prochain billet du forum.
        """
        try:
            await i.response.defer()
            c = await news.config(self.g.id)
            allume = not c["roblox_news_enabled"]
            await _db_set(self.g.id, "roblox_news_enabled", allume)
            if allume and not c.get("roblox_news_amorcee"):
                n = await news.amorcer(self.g.id)
                self._dernier = (
                    f"✅ Actualités allumées. `{n}` billet(s) de plus de "
                    f"`{news.AMORCE_GARDE_JOURS}` jours absorbé(s) sans être publiés.\\n"
                    f"-# Ceux de la semaine écoulée sortiront au prochain "
                    f"relevé — cliquez « Relever maintenant » pour ne pas attendre.")
            else:
                self._dernier = ("✅ Actualités allumées." if allume
                                 else "⚪ Actualités éteintes.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox toggle news] {ex}")

    async def _cb_relever(self, i):
        """Un relevé immédiat, pour vérifier que la chaîne fonctionne.
'''),

    # ── 8. Le bouton ♻️ efface aussi les marques d'actualité
    ('''            n = await veille.oublier_publies(self.g.id)
            self._dernier = (
                f"♻️ `{n}` marque(s) effacée(s). Les articles déjà connus "
                f"peuvent de nouveau sortir.\\n"''',
     '''            n = await veille.oublier_publies(self.g.id)
            #  Les actualités ont leur propre table de marques : sans cette
            #  ligne, le bouton disait « tout republier » et n'effaçait que
            #  la moitié.
            n_news = await news.oublier_publies(self.g.id)
            self._dernier = (
                f"♻️ `{n}` marque(s) d'article et `{n_news}` marque(s) "
                f"d'actualité effacée(s). Ce qui est déjà connu peut de nouveau "
                f"sortir.\\n"'''),
]


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}
    neuf = src
    for k, (a, b) in enumerate(REMPLACEMENTS, 1):
        n = neuf.count(a)
        if n != 1:
            print(f"❌ ancre n°{k} trouvée {n} fois (1 attendue) — abandon.")
            print("   " + a.splitlines()[0][:90])
            return 1
        neuf = neuf.replace(a, b)
        print(f"  ✅ n°{k} · {b.strip().splitlines()[0][:70]}")

    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"\n❌ ABANDON — ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    apres = {getattr(n, "name", None) for n in arbre.body}
    if avant - apres:
        print(f"\n❌ ABANDON — symboles perdus : {avant - apres}")
        return 1
    print(f"\n  roblox_panneau.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")

    if "--apply" not in sys.argv:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
