"""bannieres.py — la bannière aux dimensions exactes (26/10/2026).

Le fondateur : « qu'on peut même mettre une bannière au propre avec des dimensions exactes qui nous disent les
dimensions qu'on doit mettre pour la bannière. Sur le site. »

UNE taille pour chaque emplacement de bannière — la bannière d'une annonce ou d'un événement du clan (la galerie en
tête de la carte Discord), le bandeau de l'Accueil du site de l'équipage, l'image d'une actualité : 1600 × 640 px,
soit 5:2, le même rapport partout. Mesuré le 26/10/2026 :
  · Discord, une galerie d'une seule image dans un conteneur Components V2 (rendu de Discohook, reproduction du
    client : conteneur de 520 px au plus) : 487 px de large sur ordinateur, 310 px au téléphone (375 px), hauteur
    plafonnée à 350 px. Une image de rapport ≥ 1,4 s'y montre ENTIÈRE, sur toute la largeur : la 5:2 fait
    487 × 195 et 310 × 124 (la 4:1 des bandeaux du bot : 310 × 78, un filet au téléphone ; la 16:9 : 274 px de haut
    sur ordinateur pour le même texte, le titre tombe sous le pli au téléphone).
  · Le site de l'équipage : une actualité fait 347 px (téléphone), 713 (tablette), 635 (1366 px, deux colonnes),
    489 (1920 px, trois colonnes) → la bannière 5:2 y fait 139 à 285 px de haut ; le bandeau de l'Accueil, 347 à
    1492 px de large — sa hauteur est plafonnée par sa largeur (la moitié de l'écran au plus), jamais par un rognage.
  · 1600 px : deux fois les 487 px de Discord (écrans haute densité), et le bandeau de l'Accueil (1150 px au plus).

Le serveur la REFAIT à cette taille exacte, avec Pillow, sous des limites strictes : PNG, JPEG ou WebP seulement
(reconnus à leurs octets, jamais au nom), 8 Mo, 24 millions de pixels et 12 000 px de côté au plus, première image
d'une animation, orientation de l'appareil photo appliquée, métadonnées retirées (une image neuve, pixel par pixel).
Recadrage CENTRÉ au rapport 5:2, puis réduction : jamais étirée, jamais agrandie. Une image plus petite que
1600 × 640 est refusée avec une phrase qui donne la taille reçue et la taille demandée.
"""
from __future__ import annotations

import io

LARGEUR, HAUTEUR = 1600, 640
RAPPORT = "5:2"
#  Le format reconnu par Pillow → le type de l'image.
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
TYPES = frozenset(FORMATS.values())
NOMS_FORMATS = "PNG, JPG ou WebP"
OCTETS_MAX = 8 * 1024 * 1024
PIXELS_MAX = 24_000_000            # au-delà, l'image demanderait trop de mémoire à décoder
COTE_MAX = 12_000                  # un côté plus long : une bande absurde (30 000 × 10), refusée avant d'être lue
QUALITE = 90
CONSIGNE = f"Bannière : {LARGEUR} × {HAUTEUR} px ({RAPPORT}) · {NOMS_FORMATS} · 8 Mo au plus"
REFUS_FORMAT = f"Format refusé : {NOMS_FORMATS} seulement."


class Refus(ValueError):
    """Une bannière refusée : la phrase dite telle quelle à la personne, et son statut HTTP."""

    def __init__(self, code: str, message: str, statut: int = 400, **detail):
        super().__init__(message)
        self.code, self.message, self.statut, self.detail = code, message, statut, detail

    def corps(self) -> dict:
        return {"erreur": self.message, "champ": "image", "code": self.code, **self.detail}


def taille(largeur: int, hauteur: int) -> str:
    return f"{int(largeur)} × {int(hauteur)} px"


def spec() -> dict:
    """Ce que la page affiche et vérifie avant l'envoi (les mêmes nombres que `site/banniere.js`)."""
    return {"largeur": LARGEUR, "hauteur": HAUTEUR, "rapport": RAPPORT, "formats": NOMS_FORMATS,
            "octets_max": OCTETS_MAX, "consigne": CONSIGNE}


def _orientee(im) -> tuple:
    """La taille de l'image TELLE QU'ELLE S'AFFICHE (une photo tournée par l'appareil : largeur et hauteur échangées)."""
    l, h = im.size
    try:
        orientation = int(im.getexif().get(0x0112) or 1)
    except Exception:  # EXIF illisible : l'image se lit sans lui (exif_transpose l'ignorera aussi)
        orientation = 1
    return (h, l) if orientation in (5, 6, 7, 8) else (l, h)


def coupe(largeur: int, hauteur: int) -> tuple:
    """La zone gardée (x0, y0, x1, y1), en flottants : le plus grand rectangle 5:2 CENTRÉ dans l'image."""
    if largeur * HAUTEUR > hauteur * LARGEUR:      # trop large : on garde toute la hauteur
        l = hauteur * LARGEUR / HAUTEUR
        x0 = (largeur - l) / 2
        return x0, 0.0, x0 + l, float(hauteur)
    h = largeur * HAUTEUR / LARGEUR                # trop haute (ou juste) : toute la largeur
    y0 = (hauteur - h) / 2
    return 0.0, y0, float(largeur), y0 + h


def recadrer(data: bytes) -> dict:
    """La bannière REFAITE à 1600 × 640 → {"octets", "largeur", "hauteur", "type", "source": [l, h], "coupe":
    [x0, y0, x1, y1] (dans l'image reçue), "recadree": bool}. Lève `Refus` (la phrase pour la personne)."""
    try:
        from PIL import Image, ImageOps, features
    except ImportError as ex:   # le bot sans Pillow : l'envoi est refusé, jamais une image non vérifiée
        raise Refus("pillow", "Les bannières ne peuvent pas être traitées pour le moment.", 503) from ex
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise Refus("vide", "Image absente.")
    if len(data) > OCTETS_MAX:
        raise Refus("lourde", "Image trop lourde : 8 Mo au plus.", 413)
    try:
        im = Image.open(io.BytesIO(data))
    except Exception as ex:   # pas une image, ou un format que Pillow ne lit pas
        raise Refus("format", REFUS_FORMAT, 415) from ex
    with im:
        if im.format not in FORMATS:
            raise Refus("format", REFUS_FORMAT, 415, recu=str(im.format or "inconnu"))
        brut = im.size
        if brut[0] < 1 or brut[1] < 1 or max(brut) > COTE_MAX or brut[0] * brut[1] > PIXELS_MAX:
            raise Refus("pixels", f"Image trop grande à traiter : {taille(*brut)} reçue "
                                  f"(24 millions de pixels et {COTE_MAX} px de côté au plus).", 413)
        source = _orientee(im)
        if source[0] < LARGEUR or source[1] < HAUTEUR:
            raise Refus("petite", f"Image trop petite : {taille(*source)} reçue, il faut au moins {taille(LARGEUR, HAUTEUR)} "
                                  f"({RAPPORT}). Elle n'est jamais agrandie : envoie-la en plus grand.",
                        recue=list(source), demandee=[LARGEUR, HAUTEUR])
        try:
            im.seek(0)
            if im.format == "JPEG":   # décodée réduite (puissance de 2), jamais sous 1600 px de côté : la mémoire tenue
                im.draft("RGB", (LARGEUR, LARGEUR))
            cadre = ImageOps.exif_transpose(im)
            l, h = cadre.size
            alpha = cadre.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in cadre.info
            cadre = cadre.convert("RGBA" if alpha else "RGB")
            boite = coupe(l, h)
            #  Le recadrage et la réduction d'un seul geste : la zone 5:2 exacte → 1600 × 640 (jamais déformée).
            sortie = cadre.resize((LARGEUR, HAUTEUR), Image.Resampling.LANCZOS, box=boite)
            neuve = Image.new(sortie.mode, sortie.size)
            neuve.paste(sortie)
            tampon = io.BytesIO()
            if features.check("webp"):
                neuve.save(tampon, "WEBP", quality=QUALITE, method=4)
                typ = "image/webp"
            else:
                neuve.save(tampon, "PNG", optimize=True)
                typ = "image/png"
        except Refus:
            raise
        except Exception as ex:   # fichier tronqué, bombe de décompression, mode exotique…
            raise Refus("illisible", "Image illisible : enregistre-la à nouveau (PNG ou JPG), puis renvoie-la.", 415) from ex
    echelle = source[0] / l
    x0, y0, x1, y1 = (round(v * echelle) for v in boite)
    return {"octets": tampon.getvalue(), "largeur": LARGEUR, "hauteur": HAUTEUR, "type": typ, "source": list(source),
            "coupe": [x0, y0, x1, y1], "recadree": (x1 - x0, y1 - y0) != tuple(source)}


__all__ = ["LARGEUR", "HAUTEUR", "RAPPORT", "FORMATS", "TYPES", "NOMS_FORMATS", "OCTETS_MAX", "PIXELS_MAX", "COTE_MAX",
           "CONSIGNE", "REFUS_FORMAT", "Refus", "recadrer", "coupe", "spec", "taille"]
