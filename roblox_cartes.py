"""roblox_cartes.py — Les articles offerts avec les cartes cadeaux Roblox.

DEMANDE DU PROPRIÉTAIRE (29/09/2026)
    « il y a eu des nouveaux accessoires obtenibles par les cartes cadeaux […]
      On achète des cartes cadeaux à chaque fois, ça change les items.
      J'aimerais aussi que tu affiches les items disponibles dans les cartes
      cadeaux. Que ce soit optimisé. »

═══════════════════════════════════════════════════════════════════════════════
LA SOURCE — LA PAGE OFFICIELLE, ET RIEN D'AUTRE (mesuré le 29/09)
═══════════════════════════════════════════════════════════════════════════════
  · https://www.roblox.com/giftcards-fr est une coquille : la liste vit dans son
    script `https://js.rbxcdn.com/<empreinte>-GiftCards.js`, en dur, pays par
    pays : `{countries:[…,"fr",…],config:{bonus_items:z,cashstar_items:N,
    items:y}}`, et plus haut `y=[0x7f0a82b787c3,…]` — des identifiants
    d'articles écrits en hexadécimal. Les noms de variables changent à chaque
    version du script : on suit la configuration, jamais un nom.
  · Pour la France ce jour-là : Icarus Wings (carte en magasin, septembre
    2026 ; aussi en carte numérique), Cap of Hermes, Helm of Ares, Minotaur Head
    (codes numériques Amazon), Medusa Snakes (code bonus des cartes achetées sur
    roblox.com/giftcards).
  · Les articles du mois suivant sont DÉJÀ au catalogue (Sparkling Robux
    Shades : « … from select retailers in October 2026 »), hors vente, mais pas
    encore sur la page : seule la page dit ce qu'une carte donne AUJOURD'HUI.
    C'est aussi pourquoi le flux « nouveautés » ne les publie pas à leur
    création (règle d'or : hors vente et pas Limited) — ils sortent ICI, le
    jour où une carte les donne.

═══════════════════════════════════════════════════════════════════════════════
OPTIMISÉ
═══════════════════════════════════════════════════════════════════════════════
La page (~60 Ko) au plus toutes les HEURES_ENTRE_LECTURES ; le script (~170 Ko)
seulement quand son empreinte change ; une fiche Discord seulement quand la
liste change — une par mois, en pratique. Pages publiques, identité du bot
affichée telle quelle ; un refus (pare-feu, 403, 429) attend la lecture
suivante, sans rien contourner.
"""
from __future__ import annotations

import asyncio
import re

import roblox_veille as veille

PAGE = "https://www.roblox.com/giftcards-fr"
#  La page où l'on échange une carte, pour le bouton de la fiche.
PAGE_ECHANGE = "https://www.roblox.com/redeem"
PAYS = "fr"
HEURES_ENTRE_LECTURES = 3.0
#  Au-delà, la fiche Discord déborderait (40 composants par message).
MAX_ARTICLES = 10

MOTIF_SCRIPT = re.compile(r"https://js\.rbxcdn\.com/[0-9a-f]{16,}-GiftCards\.js")
MOTIF_GROUPE = re.compile(r"\{countries:\[([^\]]*)\],config:\{([^{}]*)\}\}")
MOTIF_ENTREE = re.compile(r"([a-z_]+):(\[[^\]]*\]|[A-Za-z_$][\w$]*)")
MOTIF_NOMBRE = re.compile(r"0x[0-9a-fA-F]+|\d+")
CLES = ("items", "bonus_items", "cashstar_items")

_MOIS = {"january": "janvier", "february": "février", "march": "mars",
         "april": "avril", "may": "mai", "june": "juin", "july": "juillet",
         "august": "août", "september": "septembre", "october": "octobre",
         "november": "novembre", "december": "décembre"}
_MOIS_FR = tuple(_MOIS.values())


def _nombres(texte: str) -> list[int]:
    out = []
    for x in MOTIF_NOMBRE.findall(texte or ""):
        v = int(x, 16) if x.lower().startswith("0x") else int(x)
        if v > 0:
            out.append(v)
    return out


def offre_du_script(js: str, pays: str = PAYS) -> dict | None:
    """{items, bonus_items, cashstar_items} pour `pays`, lus dans le script.

    `None` si la structure n'est plus celle qu'on a mesurée — on ne devine
    jamais : une liste inventée afficherait des articles qu'aucune carte ne
    donne.
    """
    for m in MOTIF_GROUPE.finditer(js or ""):
        if pays not in re.findall(r"[\"']([a-z]{2})[\"']", m.group(1)):
            continue
        conf = dict(MOTIF_ENTREE.findall(m.group(2)))
        #  Les variables sont déclarées juste avant la configuration.
        avant = js[max(0, m.start() - 6000): m.start()]
        out = {}
        for cle in CLES:
            valeur = conf.get(cle)
            if valeur is None:
                out[cle] = []
            elif valeur.startswith("["):
                out[cle] = _nombres(valeur)
            else:
                defs = list(re.finditer(
                    r"(?<![\w$.])" + re.escape(valeur) + r"=\[([^\]]*)\]", avant))
                if not defs:
                    return None
                out[cle] = _nombres(defs[-1].group(1))
        if not (out["items"] or out["bonus_items"]):
            return None
        return out
    return None


def ids_de(offre: dict) -> list[int]:
    """Les articles de l'offre, sans doublon, dans l'ordre de la page."""
    vus, out = set(), []
    for cle in ("items", "cashstar_items", "bonus_items"):
        for i in (offre or {}).get(cle) or []:
            if i not in vus:
                vus.add(i)
                out.append(i)
    return out[:MAX_ARTICLES]


def signature(offre: dict) -> str:
    """Ce qui, en changeant, mérite une nouvelle fiche. L'ordre n'y entre pas."""
    return ",".join(str(i) for i in sorted(ids_de(offre)))


def source_de(article: dict, offre: dict) -> str:
    """Quelle carte donne cet article — d'après la page, puis sa description."""
    aid = article.get("asset_id")
    texte = " ".join(str(article.get(k) or "") for k in
                     ("description", "description_fr")).lower()
    if aid in (offre.get("bonus_items") or []):
        return "🎟️ Code bonus des cartes achetées sur roblox.com/giftcards"
    if "amazon" in texte:
        return "🟠 Code de carte numérique acheté sur Amazon"
    numerique = aid in (offre.get("cashstar_items") or [])
    if "retailer" in texte or "détaillant" in texte:
        return ("🛒 Carte cadeau en magasin"
                + (" ou carte numérique sur roblox.com" if numerique else ""))
    if numerique:
        return "💳 Carte numérique achetée sur roblox.com"
    return "🎁 Carte cadeau Roblox"


def mois_de(articles: list[dict]) -> str | None:
    """« septembre 2026 », lu dans la description de l'article du mois."""
    for a in articles:
        en = str(a.get("description") or "")
        m = re.search(r"\bin (" + "|".join(_MOIS) + r")\s+(\d{4})\b", en, re.I)
        if m:
            return f"{_MOIS[m.group(1).lower()]} {m.group(2)}"
        fr = str(a.get("description_fr") or "")
        m = re.search(r"\ben (" + "|".join(_MOIS_FR) + r")\s+(\d{4})\b", fr, re.I)
        if m:
            return f"{m.group(1).lower()} {m.group(2)}"
    return None


async def lire_offre(etat: dict) -> dict:
    """La page, puis le script s'il a changé. Rend {"offre", "code", "motif",
    "script_relu"}. `etat` garde le dernier script lu et son offre : tant que
    l'empreinte ne bouge pas, on ne retélécharge rien."""
    out = {"offre": None, "code": None, "motif": None, "script_relu": False}
    try:
        async with veille._ouvrir() as sess:
            async with sess.get(PAGE, headers={"Accept": "text/html"}) as r:
                out["code"] = r.status
                if r.status != 200:
                    out["motif"] = f"HTTP {r.status}"
                    return out
                page = await r.text()
            m = MOTIF_SCRIPT.search(page or "")
            if not m:
                out["motif"] = "script introuvable dans la page"
                return out
            if m.group(0) == etat.get("script") and etat.get("offre"):
                out["offre"] = etat["offre"]
                return out
            async with sess.get(m.group(0), headers={"Accept": "*/*"}) as r:
                if r.status != 200:
                    out["code"] = r.status
                    out["motif"] = f"script HTTP {r.status}"
                    return out
                js = await r.text()
            out["script_relu"] = True
            offre = offre_du_script(js)
            if offre is None:
                out["motif"] = "liste introuvable dans le script (format changé)"
                return out
            etat["script"], etat["offre"] = m.group(0), offre
            out["offre"] = offre
    except Exception as ex:
        out["motif"] = f"{type(ex).__name__}: {ex}"
    return out


async def _economie(sess, aid: int, langue: str | None = None) -> dict | None:
    entetes = {"Accept-Language": langue} if langue else None
    async with sess.get(veille.API_ECONOMIE_DETAILS.format(int(aid)),
                        headers=entetes) as r:
        if r.status != 200:
            return None
        d = await r.json(content_type=None)
    return d if isinstance(d, dict) else None


async def fiches(offre: dict) -> list[dict]:
    """Les articles de l'offre : nom et description en anglais PUIS en
    français, tous deux de Roblox.

    ⚠️ PAR L'ÉCONOMIE, PAS PAR LA REQUÊTE GROUPÉE DES FICHES. Mesuré le 29/09 :
    `economy/v2/assets/{id}/details` rend le français officiel avec l'en-tête
    `Accept-Language: fr-fr`, et son quota tient sur l'IP de Railway (2/s),
    quand la requête groupée y est à 1 par minute, déjà prise par l'éclaireur.
    Deux requêtes par article, espacées ; un article sans réponse garde son
    identifiant — il sort quand même, avec son lien.
    """
    articles = []
    try:
        async with veille._ouvrir() as sess:
            for i, aid in enumerate(ids_de(offre)):
                if i:
                    await asyncio.sleep(veille.PAUSE_ECONOMIE_MIN * 2)
                en = await _economie(sess, aid)
                await asyncio.sleep(veille.PAUSE_ECONOMIE_MIN * 2)
                fr = await _economie(sess, aid, "fr-fr")
                a = {"asset_id": aid, "item_type": "Asset",
                     "nom": str((en or {}).get("Name") or f"Article {aid}")[:120],
                     "description": str((en or {}).get("Description") or "")[:400]}
                if fr and fr.get("Name") and fr.get("Name") != a["nom"]:
                    a["nom_fr"] = str(fr["Name"])[:120]
                if fr and fr.get("Description") and fr.get("Description") != a["description"]:
                    a["description_fr"] = str(fr["Description"])[:400]
                articles.append(a)
    except Exception as ex:
        veille._log(f"[roblox_cartes fiches] {type(ex).__name__}: {ex}")
    return articles


async def deja_affichee(guild_id: int, sig: str) -> bool:
    return (await veille.config(guild_id)).get("roblox_cartes_signature") == sig


async def noter_affichee(guild_id: int, sig: str) -> None:
    await veille._db_set(guild_id, "roblox_cartes_signature", sig)
