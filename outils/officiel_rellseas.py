"""outils/officiel_rellseas.py — les sources OFFICIELLES de RELL Seas, relevées et datées (29/10/2026).

Le fondateur : « toutes les news concernant ce studio, mais des news certifiées… les performances du jeu… les liens vers
les chaînes officielles des créateurs, le Discord officiel ». Seulement des sources tenues par RELL :
  · Roblox : le groupe « RELL Seas » (11020595, badge vérifié) et le studio « RELL GAMES » (4939446) — membres, description,
    propriétaire ; le jeu (lieu 7089993809, univers 2738929784) — favoris (le jeu n'est pas encore public : pas de visites).
  · Discord : l'invitation officielle discord.gg/RELLSEAS (nom du serveur, membres, en ligne).
  · YouTube : chaque vidéo de la chaîne RELLGames (et celles de CaribBros sur RELL Seas) — date, durée, vues, description.
Écrit `donnees_jeu/rell_officiel.json`. Rien n'est interprété : des chiffres et des textes tels que publiés, datés.

Usage : python outils/officiel_rellseas.py   (pip install yt-dlp)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "donnees_jeu" / "rell_officiel.json"
UA = {"User-Agent": "GoRP-bot-wiki/1.0 (bot Discord du clan GoRP)"}
GROUPE_JEU, GROUPE_STUDIO, LIEU, UNIVERS = 11020595, 4939446, 7089993809, 2738929784
INVITATION = "RELLSEAS"
CHAINES = {"RELLGames": "https://www.youtube.com/@RELLGames/videos", "CaribBros": "https://www.youtube.com/@CaribBros/videos"}


def get(u: str) -> dict:
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))
    except Exception as ex:
        return {"erreur": f"{type(ex).__name__}"}


def roblox() -> dict:
    out = {"jeu": {"lieu": LIEU, "univers": UNIVERS, "adresse": f"https://www.roblox.com/games/{LIEU}/RELL-Seas",
                   "favoris": get(f"https://games.roblox.com/v1/games/{UNIVERS}/favorites/count").get("favoritesCount")}}
    for cle, gid in (("groupe_jeu", GROUPE_JEU), ("groupe_studio", GROUPE_STUDIO)):
        x = get(f"https://groups.roblox.com/v1/groups/{gid}")
        out[cle] = {"id": gid, "nom": x.get("name"), "membres": x.get("memberCount"), "verifie": x.get("hasVerifiedBadge"),
                    "description": x.get("description"), "proprietaire": (x.get("owner") or {}).get("username"),
                    "adresse": f"https://www.roblox.com/communities/{gid}"}
    return out


def discord() -> dict:
    x = get(f"https://discord.com/api/v10/invites/{INVITATION}?with_counts=true")
    return {"invitation": f"https://discord.gg/{INVITATION}", "nom": (x.get("guild") or {}).get("name"),
            "membres": x.get("approximate_member_count"), "en_ligne": x.get("approximate_presence_count")}


def youtube(nom: str, adresse: str) -> list:
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "--flat-playlist", "--print", "%(id)s|%(title)s", adresse],
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    out = []
    #  le tri sur le titre AVANT d'ouvrir chaque vidéo (une chaîne en a des centaines)
    ids = [l.split("|", 1)[0].strip() for l in r.stdout.splitlines()
           if "|" in l and "seas" in l.split("|", 1)[1].lower() and len(l.split("|", 1)[0].strip()) == 11]
    for vid in ids:
        m = subprocess.run([sys.executable, "-m", "yt_dlp", "-j", "--skip-download", "--no-warnings",
                            f"https://www.youtube.com/watch?v={vid}"], capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
        try:
            j = json.loads(m.stdout)
        except ValueError:
            continue
        if "seas" not in (j.get("title") or "").lower():
            continue
        d = j.get("upload_date") or ""
        out.append({"id": vid, "chaine": nom, "titre": j.get("title"), "date": f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else "",
                    "duree": j.get("duration"), "vues": j.get("view_count"), "jaime": j.get("like_count"),
                    "description": (j.get("description") or "")[:1500]})
        time.sleep(2)
    return out


def main() -> None:
    vids = []
    for nom, adresse in CHAINES.items():
        vids += youtube(nom, adresse)
    vids.sort(key=lambda v: v["date"])
    d = {"releve": time.strftime("%Y-%m-%d"), "roblox": roblox(), "discord": discord(), "videos": vids}
    SORTIE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(vids), "vidéos ·", d["roblox"]["jeu"]["favoris"], "favoris ·", d["discord"]["membres"], "membres Discord")


if __name__ == "__main__":
    main()
