"""outils/bandeaux_studio.py — les bannières des annonces sur les VRAIES illustrations du studio (29/10/2026).

Le fondateur : « au lieu de bannières générées où tu galères, de vraies bannières avec un vrai bateau en fond, qu'on
trouve du studio ». Chaque bannière : une illustration officielle de RELL Seas (vignettes des vidéos RELLGames, copiées
par outils/wiki_images.py), un voile sombre à gauche, le titre dans les polices du site, un filet de
laiton, et le crédit « Illustration © RELL Games ». Sortie : `visuels/<cle>.gif` (960 × 240), servie par le bot.

Usage : python outils/bandeaux_studio.py [cle …]   (sans argument : toutes)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RACINE = Path(__file__).resolve().parent.parent
FONDS = RACINE / "site" / "wiki" / "fonds"
POLICES = RACINE / "site" / "polices"
SORTIE = Path(os.environ.get("BANDEAUX_SORTIE") or RACINE / "visuels")
L, H = 960, 240
#  clé : (illustration, cadrage vertical 0-1, surtitre, titre, sous-titre)
BANNIERES = {
    "an_annonce": ("ji-L9CdSvN8", .45, "GORP SEA", "Annonce", "Les nouvelles du serveur · Server news"),
    "an_clan": ("fkCXpll1jRI", .35, "CLAN GORP", "Annonce du clan", "Clan announcement"),
    "an_rellseas": ("q09y0z5Vyxw", .40, "RELL SEAS", "Rell Seas", "Le studio · The studio"),
    "an_evenement": ("P2MhP3FeF2k", .35, "GORP SEA", "Événement", "Rendez-vous · Event"),
    "an_cadeau": ("JWpwr6hjdRo", .40, "GORP SEA", "Cadeau", "À gagner · Giveaway"),
    "an_discord": ("9BkXvWPlGLc", .45, "GORP SEA", "Le serveur", "Discord · Server news"),
    "an_maj": ("QuClr80Pmc0", .70, "RELL SEAS", "Mise à jour du jeu", "Patch · Game update"),
}


def police(nom: str, taille: int):
    return ImageFont.truetype(str(POLICES / nom), taille)


def banniere(cle: str) -> Path:
    vid, cadre_y, surtitre, titre, sous = BANNIERES[cle]
    with Image.open(FONDS / f"{vid}.webp") as brut:
        art = brut.convert("RGB")
    #  29/10/2026 : une bannière FIXE (un GIF animé d'illustration pesait 5 à 6 Mo : trop lourd dans Discord)
    art = art.resize((L, round(art.height * L / art.width)), Image.LANCZOS)
    haut = int(max(0, art.height - H) * cadre_y)
    voile = Image.new("RGBA", (L, H))
    dv = ImageDraw.Draw(voile)
    for x in range(L):                                        # sombre derrière le texte, l'image vit à droite
        a = int(248 * max(0.0, 1 - x / (L * .74)) ** 1.1)
        dv.line([(x, 0), (x, H)], fill=(20, 12, 6, a))
    for y in range(H):                                        # un léger fondu en bas
        a = int(110 * max(0.0, (y - H * .55) / (H * .45)))
        dv.line([(0, y), (L, y)], fill=(20, 12, 6, a))
    texte = Image.new("RGBA", (L, H))
    dt = ImageDraw.Draw(texte)
    laiton, pale, clair = (201, 163, 90, 255), (220, 192, 138, 255), (246, 236, 214, 255)
    dt.rectangle([7, 7, L - 8, H - 8], outline=(201, 163, 90, 150), width=2)
    dt.text((41, 48), surtitre, font=police("alegreya-sc-700-latin.woff2", 22), fill=(10, 6, 3, 230))
    dt.text((40, 46), surtitre, font=police("alegreya-sc-700-latin.woff2", 22), fill=pale)
    f_titre = police("rye-latin.woff2", 64)
    while dt.textlength(titre, font=f_titre) > L * .6 and f_titre.size > 36:
        f_titre = police("rye-latin.woff2", f_titre.size - 4)
    dt.text((38, 76), titre, font=f_titre, fill=clair, stroke_width=2, stroke_fill=(43, 29, 18, 255))
    f_sous = police("alegreya-italique-latin.woff2", 26)
    dt.text((41, 84 + f_titre.size + 6), sous, font=f_sous, fill=(10, 6, 3, 230))          # l'ombre portée
    dt.text((40, 82 + f_titre.size + 6), sous, font=f_sous, fill=pale)
    credit = "Illustration © RELL Games"
    fc = police("alegreya-latin.woff2", 14)
    dt.text((L - 22 - dt.textlength(credit, font=fc), H - 30), credit, font=fc, fill=(246, 236, 214, 170))
    cadre = art.crop((0, haut, L, haut + H)).convert("RGBA")
    cadre.alpha_composite(voile)
    cadre.alpha_composite(texte)
    SORTIE.mkdir(exist_ok=True)
    chemin = SORTIE / f"{cle}.gif"
    cadre.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(
        chemin, optimize=True)
    return chemin


if __name__ == "__main__":
    for cle in sys.argv[1:] or list(BANNIERES):
        c = banniere(cle)
        print(c.name, f"{c.stat().st_size // 1024} Ko")
