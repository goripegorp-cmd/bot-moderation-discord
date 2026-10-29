"""outils/videos_rellseas.py — les vidéos OFFICIELLES de RELL Seas (chaîne RELLGames) et où chaque terme y est dit.

Les sous-titres (automatiques, anglais) des vidéos de la chaîne RELLGames sont lus ; on cherche chaque terme du wiki
(titre de page, « aka ») et du catalogue. Un terme dit dans une vidéo officielle = une PREUVE, avec le lien à la seconde
près. On ne garde que l'index (terme → vidéo, seconde), jamais le texte des vidéos.

Usage : python outils/videos_rellseas.py   (après outils/wiki_rellseas.py ; pip install yt-dlp youtube-transcript-api)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
WIKI = RACINE / "donnees_jeu" / "rell_wiki.json"
CATALOGUE = RACINE / "donnees_jeu" / "rell_catalogue.json"
SORTIE = RACINE / "donnees_jeu" / "rell_videos.json"
CHAINE = "https://www.youtube.com/@RELLGames/videos"
PAR_TERME = 6
#  Les sous-titres automatiques entendent mal certains noms : on garde ces corrections connues, rien d'autre.
ENTENDU = {"real seas": "rell seas", "rel seas": "rell seas", "hockey": "haki", "hacky": "haki", "hakki": "haki"}
TROP_COMMUNS = {"light", "medium", "heavy", "ranged", "fire", "ice", "cat", "fox", "owl", "crab", "deer", "frog",
                "shark", "whale", "spider", "dragon", "rooster", "octopus", "lion", "hippo", "monster", "demon",
                "golem", "jumper", "class", "stats", "weather", "settings", "chests", "armor", "oars", "missions",
                "leveling", "parkour", "ranked", "tutorial", "test", "items", "ships", "fishes", "islands", "npcs",
                "materials", "accessories", "enemies", "locations", "bosses", "factions", "fruits", "comparison"}


def plier(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t)
    for a, b in ENTENDU.items():
        t = re.sub(rf"\b{a}\b", b, t)
    return re.sub(r"\s+", " ", t).strip()


def liste_videos() -> list:
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "--print", "%(id)s|%(duration)s|%(title)s",
                        CHAINE], capture_output=True, text=True, encoding="utf-8", timeout=300)
    out = []
    for l in r.stdout.splitlines():
        i, d, t = (l.split("|", 2) + ["", ""])[:3]
        if "seas" in t.lower() and len(i) == 11:
            out.append({"id": i, "duree": int(float(d)) if d not in ("", "NA") else 0, "titre": t})
    return out


#  Les sous-titres reçus sont gardés sur la machine (HORS du dépôt) : YouTube bloque une adresse qui redemande trop.
CACHE = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "gorp_cache" / "sous_titres"


def sous_titres(vid: str) -> list:
    f = CACHE / f"{vid}.json"
    if f.exists():
        return [tuple(x) for x in json.loads(f.read_text(encoding="utf-8"))]
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        segs = [(int(s.start), plier(s.text)) for s in YouTubeTranscriptApi().fetch(vid, languages=["en", "en-US"])]
    except Exception:
        return []
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(segs), encoding="utf-8")
    time.sleep(3)
    return segs


def termes() -> dict:
    """terme plié → nom affiché (titres du wiki, leurs « aka », noms anglais du catalogue)."""
    out = {}
    w = json.loads(WIKI.read_text(encoding="utf-8"))
    for p in w["pages"]:
        noms = [re.sub(r"\s*\((?:.*)\)$", "", p["titre"].split("/")[-1])]
        noms += [x.strip() for x in re.split(r"[,/;]| or ", p["champs"].get("aka", "")) if x.strip()]
        for n in noms:
            n = re.sub(r"(?i)\s*boss fight (guide|page)$", "", n)
            out.setdefault(plier(n), n)
    for e in json.loads(CATALOGUE.read_text(encoding="utf-8"))["elements"]:
        out.setdefault(plier(e["nom_en"]), e["nom_en"])
    return {k: v for k, v in out.items() if len(k) >= 4 and k not in TROP_COMMUNS}


def main() -> None:
    vids = liste_videos()
    index: dict = {}
    tous = termes()
    for v in vids:
        segs = sous_titres(v["id"])
        v["sous_titres"] = bool(segs)
        #  fenêtres de 3 segments : un nom coupé entre deux lignes est retrouvé
        fen = [(segs[i][0], " ".join(s for _t, s in segs[i:i + 3])) for i in range(len(segs))]
        for k in tous:
            pat = re.compile(rf"\b{re.escape(k)}\b")
            dernier = -999
            for t, txt in fen:
                if t - dernier > 60 and pat.search(txt):
                    lst = index.setdefault(k, [])
                    if len(lst) < PAR_TERME:
                        lst.append([v["id"], t])
                    dernier = t
    SORTIE.write_text(json.dumps({"chaine": CHAINE, "videos": vids,
                                  "termes": {tous[k]: v for k, v in sorted(index.items())}},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(vids), "vidéos,", sum(v["sous_titres"] for v in vids), "avec sous-titres ;", len(index), "termes trouvés sur",
          len(tous))


if __name__ == "__main__":
    main()
