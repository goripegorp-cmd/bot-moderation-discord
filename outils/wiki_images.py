"""outils/wiki_images.py — les fonds du wiki : les vignettes OFFICIELLES des vidéos de RELL Seas (29/10/2026).

Le fondateur : « que le wiki soit vivant, qu'on ait des fonds du studio ». Les vignettes des vidéos de la chaîne
RELLGames (relevé `donnees_jeu/rell_videos.json`) sont copiées UNE fois et servies par le site (la page n'appelle jamais
YouTube : CSP stricte) : `site/wiki/fonds/<id>.webp` (1280 px) et `<id>_p.webp` (480 px). Images © RELL Games, créditées
sur la page. Rejouable : ce qui existe déjà n'est pas retéléchargé.

Usage : python outils/wiki_images.py
"""
from __future__ import annotations

import io
import json
import time
import urllib.request
from pathlib import Path

from PIL import Image

RACINE = Path(__file__).resolve().parent.parent
VIDEOS = RACINE / "donnees_jeu" / "rell_videos.json"
DOSSIER = RACINE / "site" / "wiki" / "fonds"
UA = {"User-Agent": "GoRP-bot-wiki/1.0 (bot Discord du clan GoRP)"}


def telecharger(vid: str) -> Image.Image | None:
    for nom in ("maxresdefault", "sddefault", "hqdefault"):
        try:
            brut = urllib.request.urlopen(urllib.request.Request(f"https://i.ytimg.com/vi/{vid}/{nom}.jpg", headers=UA),
                                          timeout=30).read()
            im = Image.open(io.BytesIO(brut))
            im.load()
            if im.width >= 480:
                return im.convert("RGB")
        except Exception:
            continue
    return None


def recadrer_16_9(im: Image.Image) -> Image.Image:
    """Les vignettes « sd/hq » ont des bandes noires : on garde le 16:9 central."""
    l, h = im.size
    voulu = round(l * 9 / 16)
    if h > voulu:
        haut = (h - voulu) // 2
        im = im.crop((0, haut, l, haut + voulu))
    return im


def main() -> None:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    vids = json.loads(VIDEOS.read_text(encoding="utf-8"))["videos"]
    officiel = RACINE / "donnees_jeu" / "rell_officiel.json"     # + les vidéos de CaribBros (outils/officiel_rellseas.py)
    if officiel.exists():
        vus = {v["id"] for v in vids}
        vids += [v for v in json.loads(officiel.read_text(encoding="utf-8"))["videos"] if v["id"] not in vus]
    faits = 0
    for v in vids:
        grand, petit = DOSSIER / f"{v['id']}.webp", DOSSIER / f"{v['id']}_p.webp"
        if grand.exists() and petit.exists():
            continue
        im = telecharger(v["id"])
        if im is None:
            print("absente :", v["titre"])
            continue
        im = recadrer_16_9(im)
        im.resize((1280, 720), Image.LANCZOS).save(grand, "WEBP", quality=78, method=6)
        im.resize((480, 270), Image.LANCZOS).save(petit, "WEBP", quality=74, method=6)
        faits += 1
        time.sleep(1)
    print(faits, "vignettes ajoutées ;", len(list(DOSSIER.glob("*_p.webp"))), "en tout")


if __name__ == "__main__":
    main()
