"""outils/wiki_rellseas.py — tout le wiki RELL Seas (rellseas.fandom.com) rangé et daté (29/10/2026).

Le fondateur : « que ce soient de vrais termes… quand il y a besoin de nommer, de renommer ou de chercher des
informations officielles, on ne se trompe absolument pas ». Le wiki est fait par des fans : on garde POUR CHAQUE PAGE
de quoi juger — ses catégories (ébauche, en construction, retiré), sa date, son image, et surtout les vidéos
OFFICIELLES de RELL qu'elle cite (avec la minute), vérifiées auprès de YouTube (chaîne de l'auteur).

Usage (machine avec internet) : python outils/wiki_rellseas.py → donnees_jeu/rell_wiki.json
Rien n'est inventé : un champ inconnu reste vide, une page sans preuve reste « à vérifier ».
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://rellseas.fandom.com/api.php"
WIKI = "https://rellseas.fandom.com/wiki/"
SORTIE = Path(__file__).resolve().parent.parent / "donnees_jeu" / "rell_wiki.json"
UA = {"User-Agent": "GoRP-bot-catalogue/1.0 (bot Discord du serveur GoRP ; lecture seule)"}
CHAINES_OFFICIELLES = ("rell", )            # l'auteur YouTube doit être une chaîne RELL (RELL Games, RELL World…)
EBAUCHE = {"Article Stubs", "Article Stubs with Reason", "Under Construction", "Stubs", "Expansion"}
RETIRE = {"Removed", "Former", "Candidates for Deletion", "Candidates for deletion"}
TECHNIQUE = re.compile(r"(?i)^(test|testing|testingpage|fruit page testing|godfruitnewtesting|main page|hatnotes|"
                       r"editors guide|rules|wiki staff|staff applications|discord subscriptions|.*page guide.*|"
                       r"page guides.*|rell seas wiki.*|boss page guide|.*\(disambiguation\))$")


def _get(params: dict) -> dict:
    params = dict(params, format="json")
    for essai in range(4):
        try:
            r = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
            return json.load(urllib.request.urlopen(r, timeout=40))
        except Exception:
            time.sleep(2 * (essai + 1))
    raise RuntimeError("wiki injoignable")


def titres() -> list:
    out, suite = [], {}
    while True:
        d = _get(dict(action="query", list="allpages", aplimit="500", apnamespace="0", apfilterredir="nonredirects",
                      **suite))
        out += [p["title"] for p in d["query"]["allpages"]]
        if "continue" not in d:
            return out
        suite = d["continue"]


def pages(liste: list) -> dict:
    out = {}
    for i in range(0, len(liste), 40):
        d = _get(dict(action="query", titles="|".join(liste[i:i + 40]), prop="revisions|categories|pageimages",
                      rvprop="content|timestamp", rvslots="main", cllimit="max", piprop="original"))
        for p in d["query"]["pages"].values():
            rev = (p.get("revisions") or [{}])[0]
            out[p["title"]] = {
                "texte": rev.get("slots", {}).get("main", {}).get("*", ""),
                "date": rev.get("timestamp", "")[:10],
                "categories": sorted(c["title"].split(":", 1)[1] for c in p.get("categories", [])),
                "image": p.get("original", {}).get("source", ""),
            }
    return out


def propre(w: str) -> str:
    """Le wikitexte en phrases lisibles (sans modèles, tableaux, fichiers)."""
    w = re.sub(r"<!--.*?-->", "", w, flags=re.S)
    for _ in range(4):
        w = re.sub(r"\{\{[^{}]*\}\}", "", w)
    w = re.sub(r"(?s)\{\|.*?\|\}", "", w)
    w = re.sub(r"\[\[(?:File|Image|Fichier|Category):[^\]]*\]\]", "", w, flags=re.I)
    w = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", w)
    w = re.sub(r"\[https?://\S+ ([^\]]+)\]", r"\1", w)
    w = re.sub(r"'{2,}|<[^>]+>|^\s*[|!].*$|^\s*\|-.*$", "", w, flags=re.M)
    w = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\n## \1", w, flags=re.M)
    return re.sub(r"\n\s*\n+", "\n", w).strip()


BROUILLON = re.compile(r"(?i)lorem ipsum|placeholder|no(?:ting|thing) is true|to be (?:added|written)|\bwip\b")


def resume(w: str) -> str:
    """La première vraie phrase de la page ; rien pour un brouillon (« Lorem ipsum », « placeholder… nothing is true »)."""
    t = propre(w)
    if BROUILLON.search(t[:4000]):
        return ""
    blocs = [b.strip() for b in re.split(r"\n## [^\n]*", t) if len(b.strip()) > 40]
    return re.sub(r"\s+", " ", blocs[0])[:400] if blocs else ""


def champs(w: str) -> dict:
    """Les paramètres des modèles d'infobox (« release_date=Movie 3 », « type=Logia »…)."""
    out = {}
    for m in re.finditer(r"\|\s*([a-zA-Z_ ]{2,30}?)\s*=\s*([^|{}\n]{1,120})", w):
        k, v = m.group(1).strip().lower().replace(" ", "_"), m.group(2).strip()
        if v and not v.lower().endswith((".png", ".jpg", ".gif", ".webp")) and k not in out:
            out[k] = v
    return out


def videos(w: str) -> list:
    vus = []
    for m in re.finditer(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})(?:[^\s\]|]*?[?&]t=(\d+)s?)?", w):
        x = (m.group(1), int(m.group(2) or 0))
        if x not in vus:
            vus.append(x)
    return vus


def chaine(vid: str, cache: dict) -> dict:
    if vid not in cache:
        try:
            u = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}")
            d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20))
            cache[vid] = {"titre": d.get("title", ""), "auteur": d.get("author_name", ""), "chaine": d.get("author_url", "")}
        except Exception:
            cache[vid] = {"titre": "", "auteur": "", "chaine": ""}
    return cache[vid]


def statut(cats: set, preuves: int, texte: str) -> str:
    if cats & RETIRE or re.search(r"(?i)\b(cut content|removed from the game|no longer in the game)\b", texte[:3000]):
        return "retire"
    if preuves:
        return "confirme"
    return "a_verifier"


def main() -> None:
    liste = [t for t in titres() if not TECHNIQUE.match(t)]
    brut = pages(liste)
    cache: dict = {}
    sortie = []
    for t, p in sorted(brut.items()):
        cats = set(p["categories"])
        vids = []
        for vid, sec in videos(p["texte"]):
            c = chaine(vid, cache)
            officielle = any(x in (c["auteur"] or "").lower() for x in CHAINES_OFFICIELLES)
            vids.append({"id": vid, "t": sec, "titre": c["titre"], "auteur": c["auteur"], "officielle": officielle})
        preuves = sum(1 for v in vids if v["officielle"])
        sortie.append({
            "titre": t, "adresse": WIKI + urllib.parse.quote(t.replace(" ", "_")), "date": p["date"],
            "categories": p["categories"], "image": p["image"], "resume": resume(p["texte"]),
            "champs": champs(p["texte"]), "videos": vids, "ebauche": bool(cats & EBAUCHE),
            "statut": statut(cats, preuves, p["texte"]), "taille": len(p["texte"]),
        })
    SORTIE.write_text(json.dumps({"source": "https://rellseas.fandom.com", "releve": time.strftime("%Y-%m-%d"),
                                  "pages": sortie, "videos": cache}, ensure_ascii=False, indent=1), encoding="utf-8")
    n = {s: sum(1 for x in sortie if x["statut"] == s) for s in ("confirme", "a_verifier", "retire")}
    print(len(sortie), "pages ·", n, "·", sum(1 for v in cache.values() if any(x in v["auteur"].lower() for x in CHAINES_OFFICIELLES)),
          "vidéos officielles sur", len(cache))


if __name__ == "__main__":
    sys.exit(main())
