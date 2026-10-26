"""outils/affiche_recrutement.py — la bannière de l'AFFICHE d'un ticket de recrutement (26/10/2026).

Dessinée par le code, dans le style de la maison (le site « La Capitainerie ») : un avis de recrutement de pirates au nom
du clan — parchemin bordé de bois, titre en Pirata One, petites capitales Alegreya SC, une rose des vents à l'encre, un
sceau de cire « G ». Servie par le bot (`/v/recrutement_affiche.png`) et posée en tête de l'affiche (MediaGallery) ;
sans elle, l'affiche garde son titre en texte.

Usage : python outils/affiche_recrutement.py        → visuels/recrutement_affiche.png (960 × 320, PNG)
Déterministe (graine fixe) : deux fabrications donnent le même fichier.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "site"
SORTIE = RACINE / "visuels" / "recrutement_affiche.png"
L, H, ECH = 960, 320, 2
ENCRE, ENCRE_2, CIRE, CIRE_FONCE, LAITON = (43, 29, 18), (90, 67, 48), (142, 42, 36), (106, 28, 23), (168, 130, 63)


def police(nom: str, taille: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(SITE / "polices" / nom), taille * ECH)


def texture(nom: str, taille: tuple) -> Image.Image:
    """Une texture du site, répétée pour couvrir `taille`."""
    t = Image.open(SITE / "textures" / nom).convert("RGB")
    out = Image.new("RGB", taille)
    for x in range(0, taille[0], t.width):
        for y in range(0, taille[1], t.height):
            out.paste(t, (x, y))
    return out


def bord_dechire(taille: tuple, marge: int, graine: int) -> Image.Image:
    """Le masque d'un papier aux bords un peu irréguliers (jamais une découpe nette de machine)."""
    w, h = taille
    hasard = random.Random(graine)
    pts = []
    for x in range(marge, w - marge + 1, 6 * ECH):
        pts.append((x, marge + hasard.uniform(-2.5, 2.5) * ECH))
    for y in range(marge, h - marge + 1, 6 * ECH):
        pts.append((w - marge + hasard.uniform(-2.5, 2.5) * ECH, y))
    for x in range(w - marge, marge - 1, -6 * ECH):
        pts.append((x, h - marge + hasard.uniform(-2.5, 2.5) * ECH))
    for y in range(h - marge, marge - 1, -6 * ECH):
        pts.append((marge + hasard.uniform(-2.5, 2.5) * ECH, y))
    m = Image.new("L", taille, 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m.filter(ImageFilter.GaussianBlur(0.8 * ECH))


def texte_centre(d: ImageDraw.ImageDraw, cx: float, y: float, texte: str, f, couleur, espace: float = 0.0) -> float:
    """Un texte centré sur `cx` (avec un espacement des lettres) ; rend sa largeur."""
    if not espace:
        lg = d.textlength(texte, font=f)
        d.text((cx - lg / 2, y), texte, font=f, fill=couleur)
        return lg
    largeurs = [d.textlength(c, font=f) for c in texte]
    total = sum(largeurs) + espace * (len(texte) - 1)
    x = cx - total / 2
    for c, lg in zip(texte, largeurs):
        d.text((x, y), c, font=f, fill=couleur)
        x += lg + espace
    return total


def rose_des_vents(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
    """Une rose des vents gravée : huit pointes, deux tons d'encre, un cercle."""
    d.ellipse((cx - r * 0.78, cy - r * 0.78, cx + r * 0.78, cy + r * 0.78), outline=ENCRE_2, width=int(1.6 * ECH))
    d.ellipse((cx - r * 0.66, cy - r * 0.66, cx + r * 0.66, cy + r * 0.66), outline=ENCRE_2, width=int(0.8 * ECH))
    for k in range(8):
        a = math.radians(k * 45 - 90)
        longue = k % 2 == 0
        rr = r if longue else r * 0.62
        lg = r * (0.16 if longue else 0.12)
        pointe = (cx + rr * math.cos(a), cy + rr * math.sin(a))
        g = (cx + lg * math.cos(a - math.pi / 2), cy + lg * math.sin(a - math.pi / 2))
        dr = (cx + lg * math.cos(a + math.pi / 2), cy + lg * math.sin(a + math.pi / 2))
        d.polygon([pointe, g, (cx, cy)], fill=ENCRE)
        d.polygon([pointe, dr, (cx, cy)], fill=LAITON if longue else ENCRE_2)
    d.ellipse((cx - r * 0.08, cy - r * 0.08, cx + r * 0.08, cy + r * 0.08), fill=CIRE)
    f = police("alegreya-sc-700-latin.woff2", 15)
    lg = d.textlength("N", font=f)
    d.text((cx - lg / 2, cy - r - 21 * ECH), "N", font=f, fill=ENCRE)


def sceau(base: Image.Image, cx: float, cy: float, r: float, graine: int) -> None:
    """Un sceau de cire rouge, bord irrégulier, le « G » du clan en relief."""
    hasard = random.Random(graine)
    pts = []
    for k in range(48):
        a = 2 * math.pi * k / 48
        rr = r * (1 + hasard.uniform(-0.05, 0.07))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    calque = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    ombre = Image.new("L", base.size, 0)
    ImageDraw.Draw(ombre).polygon([(x + 3 * ECH, y + 4 * ECH) for x, y in pts], fill=150)
    base.paste((40, 16, 10), (0, 0), ombre.filter(ImageFilter.GaussianBlur(4 * ECH)))
    d.polygon(pts, fill=CIRE + (255,))
    d.ellipse((cx - r * 0.74, cy - r * 0.74, cx + r * 0.74, cy + r * 0.74), fill=CIRE_FONCE + (255,))
    d.ellipse((cx - r * 0.68, cy - r * 0.68, cx + r * 0.68, cy + r * 0.68), fill=CIRE + (255,))
    f = police("pirata-one-latin.woff2", int(r / ECH * 1.05))
    boite = d.textbbox((0, 0), "G", font=f)
    x, y = cx - (boite[0] + boite[2]) / 2, cy - (boite[1] + boite[3]) / 2
    d.text((x + 1.5 * ECH, y + 1.5 * ECH), "G", font=f, fill=CIRE_FONCE + (255,))
    d.text((x, y), "G", font=f, fill=(214, 120, 104, 255))
    reflet = Image.new("L", base.size, 0)
    ImageDraw.Draw(reflet).ellipse((cx - r * 0.55, cy - r * 0.85, cx + r * 0.1, cy - r * 0.35), fill=70)
    calque.putalpha(ImageChops.multiply(calque.getchannel("A"), Image.new("L", base.size, 255)))
    base.alpha_composite(calque)
    base.paste((255, 235, 225), (0, 0), reflet.filter(ImageFilter.GaussianBlur(5 * ECH)))


def fabriquer() -> Image.Image:
    w, h = L * ECH, H * ECH
    #  Le cadre de bois, assombri.
    bois = texture("bois.webp", (w, h))
    bois = Image.blend(bois, Image.new("RGB", (w, h), (20, 11, 5)), 0.45)
    toile = bois.convert("RGBA")
    #  Le parchemin, aux bords un peu irréguliers, une ombre portée dessous.
    marge = 16 * ECH
    masque = bord_dechire((w, h), marge, 26102026)
    ombre = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ombre.putalpha(masque.filter(ImageFilter.GaussianBlur(7 * ECH)).point(lambda v: int(v * 0.7)))
    toile.alpha_composite(ombre, (0, 3 * ECH))
    papier = texture("parchemin.webp", (w, h)).convert("RGBA")
    #  Un voile plus sombre sur les bords du papier (le vieux papier jaunit par les bords).
    voile = Image.new("L", (w, h), 0)
    ImageDraw.Draw(voile).rectangle((marge + 40 * ECH, marge + 30 * ECH, w - marge - 40 * ECH, h - marge - 30 * ECH), fill=255)
    voile = voile.filter(ImageFilter.GaussianBlur(38 * ECH))
    jauni = Image.new("RGBA", (w, h), (120, 82, 40, 255))
    papier = Image.composite(papier, Image.blend(papier, jauni, 0.35), voile)
    papier.putalpha(masque)
    toile.alpha_composite(papier)
    d = ImageDraw.Draw(toile)
    #  Un double filet d'encre à l'intérieur du papier.
    m2 = marge + 12 * ECH
    d.rectangle((m2, m2, w - m2, h - m2), outline=ENCRE_2 + (255,), width=int(1.4 * ECH))
    d.rectangle((m2 + 5 * ECH, m2 + 5 * ECH, w - m2 - 5 * ECH, h - m2 - 5 * ECH), outline=ENCRE_2 + (255,),
                width=int(0.7 * ECH))
    cx = w / 2
    #  Le surtitre, le titre, le filet à losange, la ligne du bas.
    texte_centre(d, cx, 52 * ECH, "L'ÉQUIPAGE GORP RECRUTE", police("alegreya-sc-700-latin.woff2", 24), CIRE + (255,),
                 espace=3.2 * ECH)
    titre = police("pirata-one-latin.woff2", 78)
    texte_centre(d, cx + 2 * ECH, 96 * ECH + 2 * ECH, "Avis de recrutement", titre, (120, 90, 60, 120))
    lg = texte_centre(d, cx, 96 * ECH, "Avis de recrutement", titre, ENCRE + (255,))
    y = 202 * ECH
    demi = min(lg / 2, 300 * ECH)
    d.line((cx - demi, y, cx - 14 * ECH, y), fill=ENCRE_2 + (255,), width=int(1.6 * ECH))
    d.line((cx + 14 * ECH, y, cx + demi, y), fill=ENCRE_2 + (255,), width=int(1.6 * ECH))
    d.polygon([(cx, y - 7 * ECH), (cx + 8 * ECH, y), (cx, y + 7 * ECH), (cx - 8 * ECH, y)], fill=CIRE + (255,))
    texte_centre(d, cx, 218 * ECH, "RELL Seas · rejoins l'équipage, pas à pas", police("alegreya-italique-latin.woff2", 25),
                 ENCRE_2 + (255,))
    texte_centre(d, cx, 252 * ECH, "JOIN THE CREW", police("alegreya-sc-400-latin.woff2", 17), (110, 85, 63, 255),
                 espace=2.4 * ECH)
    #  La rose des vents à gauche, le sceau à droite.
    rose_des_vents(d, 112 * ECH, 168 * ECH, 58 * ECH)
    sceau(toile, w - 116 * ECH, 168 * ECH, 50 * ECH, 777)
    return toile.convert("RGB").resize((L, H), Image.LANCZOS)


def main() -> int:
    img = fabriquer()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    img.save(SORTIE, "PNG", optimize=True)
    print(f"{SORTIE.relative_to(RACINE)} : {img.width} × {img.height}, {SORTIE.stat().st_size // 1024} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
