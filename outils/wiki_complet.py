"""Relevé complet du wiki RELL Seas (fandom) : HTML rendu, wikitext, images, catégories.
Écrit dans _fandom/ (non suivi). Lecture seule, une requête à la fois."""
import json, os, sys, time, urllib.parse, urllib.request
API = "https://rellseas.fandom.com/api.php"
UA = {"User-Agent": "GoRP-bot-catalogue/1.0 (bot Discord du serveur GoRP ; lecture seule)"}
SORTIE = "_fandom"

def get(p):
    p = dict(p, format="json", formatversion=2)
    for essai in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(API + "?" + urllib.parse.urlencode(p), headers=UA), timeout=40)
            return json.load(r)
        except Exception as e:
            time.sleep(2 + essai * 3); err = e
    raise err

def tous():
    t, suite = [], {}
    while True:
        r = get(dict(action="query", list="allpages", aplimit=500, apnamespace=0, apfilterredir="nonredirects", **suite))
        t += [x["title"] for x in r["query"]["allpages"]]
        if "continue" not in r: return t
        suite = {"apcontinue": r["continue"]["apcontinue"]}

def main():
    os.makedirs(SORTIE, exist_ok=True)
    titres = tous(); print(len(titres), "pages")
    for i, ti in enumerate(titres):
        f = os.path.join(SORTIE, urllib.parse.quote(ti, safe="") + ".json")
        if os.path.exists(f) and "--frais" not in sys.argv: continue
        r = get(dict(action="parse", page=ti, prop="text|wikitext|images|categories|sections", redirects=1))
        json.dump(r.get("parse", r), open(f, "w", encoding="utf8"), ensure_ascii=False)
        time.sleep(0.3)
    print("ok")
if __name__ == "__main__": main()
