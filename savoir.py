"""savoir.py — ce qu'on sait de RELL Seas, et les trois familles de questions : Jeu, Site, Studio (29/10/2026).

Le fondateur : « trois catégories à part pour le système de questions : un système lié au jeu, un lié au site, un lié
au studio (le Discord, les FAQ, les questions…). Tout ce qui est lié au jeu : tous les termes, même avec Movie 3…
savoir s'il y a des informations qui sont vraies ou non. »

LE SAVOIR DU JEU (lu une fois, jamais de réseau ici)
  · `donnees_jeu/rell_catalogue.json` : ce qu'un joueur peut détenir, en français (les noms du jeu en `nom_en`) ;
  · `donnees_jeu/rell_wiki.json` : toutes les pages du wiki des fans (outils/wiki_rellseas.py) ;
  · `donnees_jeu/rell_videos.json` : où chaque terme est DIT dans une vidéo officielle de RELL (outils/videos_rellseas.py).
  Une fiche dit toujours d'où vient ce qu'elle affirme : « ✅ vu dans une vidéo officielle » (lien à la minute),
  « 🔎 à vérifier » (le wiki des fans seulement), « ⛔ retiré ». Rien n'est inventé.

LA RÉPONSE : une vraie question sur un terme du jeu (« c'est quoi Yahu ? », « comment avoir Flash Dash ? », « what is
the Sloop? ») reçoit sa fiche ; un mot courant seul (« light », « fire »…) n'en déclenche jamais une.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import textes

DONNEES = Path(__file__).resolve().parent / "donnees_jeu"
DOMAINES = {"jeu": "Jeu", "site": "Site", "studio": "Studio"}
STATUTS = {"confirme": ("**Confirmé** · source officielle", "**Confirmed** · official source"),
           "a_verifier": ("**À vérifier** · wiki des fans", "**Unverified** · fans' wiki"),
           "retire": ("**Retiré du jeu**", "**Removed from the game**")}
#  Des mots de tous les jours : jamais une fiche à eux seuls (« t'as vu la light ? »).
COMMUNS = {"light", "medium", "heavy", "ranged", "fire", "ice", "poison", "lightning", "love", "dark", "soul", "luck",
           "health", "defense", "chop", "bomb", "doctor", "spiritual", "pirates", "material", "equipment", "randomize",
           "tickets", "revive", "flame", "sand", "string", "rubber", "venom", "giant", "wolf", "endurance",
           "navigation", "compass", "katana", "dagger", "cannon", "cannons", "sails", "mammoth", "cat", "fox", "owl",
           "crab", "deer", "frog", "shark", "whale", "spider", "dragon", "rooster", "octopus", "lion", "hippo", "demon",
           "golem", "monster", "jumper", "class", "stats", "weather", "settings", "chests", "armor", "oars", "missions",
           "leveling", "parkour", "ranked", "tutorial", "items", "ships", "fishes", "islands", "npcs", "materials",
           "accessories", "enemies", "locations", "bosses", "factions", "fruits", "comparison", "camp", "cooking",
           "fishing", "mining", "crafting", "sailing", "weapons", "mounts", "races", "posters", "haki", "talents",
           "currencies", "wildlife", "reputation", "submarine", "submarines", "electro", "gravity"}
#  … sauf avec leur nom de famille : « le fruit Magma », « le poster Jumper », « Kraken boss ».
FAMILLES = r"(?:fruit|god fruit|devil fruit|poster|boss|monture|mount|navire|ship|arme|weapon|race|style|haki|carte|card)"
FORME = re.compile(
    r"\b(?:c ?est quoi|c ?est qui|qu ?est ?ce que?|qui est|quel(?:le)?s? (?:est|sont)|ca sert a quoi|sert a quoi|"
    r"comment (?:avoir|obtenir|trouver|debloquer|recuperer|battre|tuer|vaincre|on a|on obtient|marche)|"
    r"ou (?:trouver|est|sont|on trouve|se trouve)|(?:il|elle) (?:existe|est sorti)|existe|est (?:sorti|dispo)|"
    r"what (?:is|are|does)|whats|who is|how (?:to|do i|do you|can i) (?:get|find|unlock|obtain|beat|defeat|use)|"
    r"where (?:is|are|to|can i|do i)|is there|does .{1,30} exist|infos? sur|info on)\b")
SITE = re.compile(r"\b(?:site|capitainerie|affiches?|tableau de bord|connexion|me connecter|se connecter|mot de passe|"
                  r"questionnaire|fiche|page web|website|dashboard|log ?in)\b")
STUDIO = re.compile(r"\b(?:discord|serveur|server|ticket|clan|gorp|staff|modos?|r[oô]les?|salons?|channel|giveaway|"
                    r"cadeaux?|trade|annonces?|rell (?:games|brothers|world)|studio|trello|wiki|sortie|release)\b")


def plier(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _lire(nom: str) -> dict:
    try:
        return json.loads((DONNEES / nom).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def fiches() -> dict:
    """terme plié → fiche {cle, nom, nom_en, type, description, resume_en, statut, image, wiki, preuves}."""
    cat, wiki, vid = _lire("rell_catalogue.json"), _lire("rell_wiki.json"), _lire("rell_videos.json")
    #  29/10/2026 : les textes RELUS du wiki public (français et anglais, sans supposition) passent avant tout le reste
    relus = _lire("wiki_public.json")
    textes = relus.get("textes", {})
    types = {t["cle"]: t["nom"] for t in cat.get("types", [])}
    titres = {v["id"]: v["titre"] for v in vid.get("videos", [])}
    preuves = vid.get("termes", {})
    out: dict = {}

    def poser(cle_terme: str, f: dict) -> None:
        k = plier(cle_terme)
        if len(k) >= 3 and k not in out:
            out[k] = f
    brouillon = re.compile(r"(?i)lorem ipsum|placeholder|no(?:ting|thing) is true")
    for p in wiki.get("pages", []):          # un brouillon du wiki des fans ne dit rien de vrai
        if brouillon.search(p.get("resume", "")):
            p["resume"] = ""
    pages = {plier(p["titre"]): p for p in wiki.get("pages", [])}
    for e in cat.get("elements", []):
        if not e.get("actif", True):
            continue
        p = pages.get(plier(e["nom_en"]))
        relu = textes.get(f"{e['type']}.{e['cle']}") or {}
        f = {"cle": f"{e['type']}.{e['cle']}", "nom": e["nom"], "nom_en": e["nom_en"], "type": types.get(e["type"], ""),
             "description": relu.get("fr") or e.get("description", ""), "texte_en": relu.get("en", ""),
             "resume_en": (p or {}).get("resume", ""),
             "statut": e.get("statut", "a_verifier"), "image": (p or {}).get("image", ""),
             "wiki": e["source"] if "fandom.com" in e.get("source", "") else (p or {}).get("adresse", ""),
             "preuves": [(v, t, titres.get(v, "")) for v, t in preuves.get(e["nom_en"], [])[:3]]}
        poser(e["nom_en"], f)
        poser(e["nom"], f)
    for cle, x in relus.get("hors_catalogue", {}).items():
        vus = preuves.get(x.get("preuve") or x["nom"], [])
        if vus:
            f = {"cle": cle, "nom": x.get("nom_fr") or x["nom"], "nom_en": x["nom"], "type": "", "description": x["fr"],
                 "texte_en": x["en"], "resume_en": "", "statut": "confirme", "image": "",
                 "wiki": pages.get(plier(x.get("preuve") or x["nom"]), {}).get("adresse", ""),
                 "preuves": [(v, t, titres.get(v, "")) for v, t in vus[:3]]}
            poser(x["nom"], f)
            if x.get("nom_fr"):
                poser(x["nom_fr"], f)
    for p in wiki.get("pages", []):
        nom = re.sub(r"(?i)\s*boss fight (?:guide|page)$", "", p["titre"].split("/")[-1]).strip()
        if not (p.get("resume") or p.get("image")) or plier(nom) in out:
            continue
        vus = preuves.get(nom, [])
        statut = p["statut"] if p["statut"] == "retire" else ("confirme" if vus else "a_verifier")
        f = {"cle": "wiki." + plier(nom).replace(" ", "_")[:40], "nom": nom, "nom_en": nom, "type": "",
             "description": "", "resume_en": p["resume"], "statut": statut, "image": p.get("image", ""),
             "wiki": p["adresse"], "preuves": [(v, t, titres.get(v, "")) for v, t in vus[:3]]}
        poser(nom, f)
        for aka in re.split(r"[,/;]| or ", p.get("champs", {}).get("aka", "")):
            poser(aka.strip(), f)
    return out


def par_cle(cle: str) -> dict | None:
    return next((f for f in fiches().values() if f["cle"] == cle), None)


def trouver_terme(texte: str) -> dict | None:
    """Le terme du jeu nommé dans le texte (le plus long d'abord) ; un mot courant seul ne compte pas."""
    p = f" {plier(texte)} "
    for k in sorted(fiches(), key=len, reverse=True):
        if f" {k} " not in p:
            continue
        if k in COMMUNS and not re.search(rf"\b{FAMILLES} (?:de |du |d |des |la |le )?{re.escape(k)}\b|"
                                          rf"\b{re.escape(k)} {FAMILLES}\b", p):
            continue
        return fiches()[k]
    return None


def trouver(texte: str) -> dict | None:
    """Une vraie question de savoir sur un terme du jeu → sa fiche ; sinon None."""
    p = plier(texte)
    if not FORME.search(p):
        return None
    return trouver_terme(texte)


def _minute(t: int) -> str:
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def reponse(cle: str, langue: str = "fr") -> tuple | None:
    """(titre, corps, [(bouton, lien)]) pour la carte du bot ; None si la fiche n'existe plus."""
    f = par_cle(cle)
    if f is None:
        return None
    en = langue == "en"
    nom = f["nom_en"] if en or f["nom"] == f["nom_en"] else f"{f['nom']} ({f['nom_en']})"
    titre = nom + (f" · {f['type']}" if f["type"] else "")
    lignes = []
    texte = (f.get("texte_en") or f["resume_en"] or f["description"]) if en else (f["description"] or f["resume_en"])
    if texte:
        texte = re.sub(r"\s*Dit dans « [^»]+ » \([^)]*\)\.?", "", texte)       # la preuve a sa propre ligne
        lignes.append(texte[:500] + (" *(wiki des fans, en anglais)*" if not en and not f["description"] else ""))
    lignes.append(STATUTS.get(f["statut"], STATUTS["a_verifier"])[1 if en else 0])
    if f["preuves"]:
        v, t, titre_v = f["preuves"][0]
        lignes.append(("Shown in" if en else "Vu dans") + f" « {titre_v or 'RELL'} » ({_minute(t)}).")
    elif f["statut"] != "retire":
        lignes.append("Fans' wiki only: not shown officially yet." if en else
                      "Seulement le wiki des fans : pas encore montré officiellement.")
    boutons = [(("Video" if en else "La vidéo") + f" · {_minute(t)}", f"https://youtu.be/{v}?t={t}")
               for v, t, _x in f["preuves"][:2]]
    if f["wiki"]:
        boutons.append(("Wiki", f["wiki"]))
    return titre, "\n".join(lignes), boutons[:5]


def domaine(sujet: str = "", texte: str = "") -> str:
    """« jeu », « site », « studio » ou "" : la famille d'une question (sujet du bot, sinon son texte)."""
    if sujet.startswith("jeu:") or sujet == "aide":
        return "jeu"
    if sujet.startswith("site:"):
        return "site"
    if sujet:
        return "studio"         # les sujets de la FAQ : le clan, les tickets, le trade, les annonces… (le Discord)
    p = plier(texte)
    if trouver_terme(texte) is not None:
        return "jeu"
    if SITE.search(p):
        return "site"
    if STUDIO.search(p):
        return "studio"
    return ""


# ════════════════════════════════════════════════════════════════
#  La famille « Site » : les questions sur nos pages (29/10/2026)
# ════════════════════════════════════════════════════════════════
SUJETS_SITE = {
    #  le wiki : « y a un wiki ? », « le lien du wiki », « où trouver des infos sur RELL Seas ? », « is there a wiki? »
    "wiki": re.compile(r"\b(?:wiki|grimoire)\b|\b(?:infos?|informations?|tout savoir|guide)\b.{0,30}\brell ?seas\b|"
                       r"\brell ?seas\b.{0,30}\b(?:infos?|informations?|guide)\b"),
    #  la vitrine du clan : « le site du clan », « la vitrine », « le lien de l'équipage », « clan website »
    "vitrine": re.compile(r"\b(?:site|vitrine|page)\b.{0,25}\b(?:clan|gorp|equipage|crew)\b|\bvitrine\b|"
                          r"\b(?:clan|crew)\b.{0,15}\bwebsite\b"),
}
ADRESSES_SITE = {"wiki": "/wiki", "vitrine": "/equipage"}
TEXTES_SITE = {
    "wiki": ("Le wiki RELL Seas", "The RELL Seas wiki",
             "Le grimoire du clan : tout ce que RELL a vraiment montré, vérifié fiche par fiche — le jeu, le monde, le lore, "
             "les vidéos officielles. En français et en anglais.",
             "The clan's grimoire: everything RELL has really shown, verified entry by entry — the game, the world, the lore, "
             "the official videos. In French and English.", "Ouvrir le wiki", "Open the wiki"),
    "vitrine": ("La vitrine du clan", "The clan's showcase",
                "La vitrine de l'équipage GoRP : ses membres, ses affiches, ses nouvelles.",
                "The GoRP crew's showcase: its members, posters and news.", "Voir la vitrine", "See the showcase"),
}


#  Les textes des réponses « Site » : réécrits sur le site (« Textes & noms », famille « Réponses du bot »), comme la FAQ.
for _c, _t in TEXTES_SITE.items():
    for _i, _l in ((2, "fr"), (3, "en")):
        textes.declarer(f"faq.site_{_c}.{_l}", _t[_i], groupe="reponses", partie="Les questions fréquentes",
                        ordre=300 + _i, titre=f"Réponse « {_t[0]} » ({_l})", max_=500)


def sujet_site(texte: str) -> str:
    """« wiki », « vitrine » ou "" : une question sur nos pages."""
    p = plier(texte)
    if not re.search(r"\b(?:ou|lien|adresse|existe|y a|ya|il y a|c est quoi|comment|where|link|is there|any|what)\b|\?", p + (
            " ?" if "?" in str(texte) else "")):
        return ""
    return next((k for k, r in SUJETS_SITE.items() if r.search(p)), "")


def reponse_site(cle: str, langue: str, base: str, gid=None) -> tuple | None:
    if cle not in TEXTES_SITE or not base:
        return None
    t = TEXTES_SITE[cle]
    en = langue == "en"
    corps = textes.texte_cache(gid, f"faq.site_{cle}.{'en' if en else 'fr'}") if gid else t[3 if en else 2]
    return t[1 if en else 0], corps, [(t[5 if en else 4], base.rstrip("/") + ADRESSES_SITE[cle])]
