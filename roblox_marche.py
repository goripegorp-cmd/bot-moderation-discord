"""roblox_marche.py — « Publié récemment » sur le Marketplace, à la lettre.

═══════════════════════════════════════════════════════════════════════════════
DEUX QUESTIONS DIFFÉRENTES, ET JE M'ÉTAIS TROMPÉ DE QUESTION
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire, le 30/08/2026 :

    « Je ne demande pas l'asset Roblox possédant la date technique Created la
     plus récente. Je demande le dernier accessoire placé en tête du filtre
     officiel "Publié récemment" du Marketplace Roblox. »

Un objet peut être créé techniquement des semaines avant d'être publié, rendu
visible ou actualisé sur le Marketplace. Mesuré ce jour-là, et c'est sans appel :

    RANG « PUBLIÉ RÉCEMMENT »          DATE TECHNIQUE DE CRÉATION
    1. Icarus Wings      (92,7 j)      1. Sakura Antlers   (18,4 j)
    2. Medusa Snakes     (92,7 j)      2. Gold Crown       (19,5 j)
    3. Cap of Hermes     (68,6 j)      3. World Builder    (32,5 j)
    …                                  …
    6. Sakura Antlers    (18,4 j)      …

Le classement du Marketplace n'a AUCUN rapport avec l'ordre des dates de
création. Retrier par `cree_le` — ce que faisait `roblox_veille._normaliser` —
détruit la réponse à la question posée.

═══════════════════════════════════════════════════════════════════════════════
CE QUE J'AI MESURÉ AVANT D'ÉCRIRE CE MODULE
═══════════════════════════════════════════════════════════════════════════════
· La requête du propriétaire (v1 + `SortAggregation=5`) reproduit EXACTEMENT
  l'ordre de sa capture. Vérifié sur les six premiers noms.
· ⚠️ `SortAggregation=5` NE CHANGE RIEN ICI. v1 avec, v2 avec, v2 sans : ordre
  identique aux six premières places. Le paramètre qui manquait au bot était
  `IncludeNotForSale=true`. On garde quand même `SortAggregation` : il est dans
  la requête du site, et rien ne dit qu'il restera neutre.
· ⚠️ v1 REFUSE `Limit=120` (HTTP 400). v2 l'accepte et rend le même ordre —
  on prend donc v2 : quatre fois moins de requêtes pour la même réponse, ce
  qui est la consigne « ne pas spammer une recherche qui sert à rien ».

═══════════════════════════════════════════════════════════════════════════════
LES TYPES D'ACCESSOIRES — MESURÉS, PAS RÉCITÉS
═══════════════════════════════════════════════════════════════════════════════
Relevé du 30/08 sur 357 articles du compte Roblox, avec leur taxonomie
officielle. C'est cette table qui fonde le filtre, pas un souvenir :

    8  Head Accessories        11  Classic Shirts     88  Face Makeup
   41  Hair                    12  Classic Pants      89  Lip Makeup
   42  Face Accessories        64  T-Shirt            90  Eye Makeup
   43  Neck Accessories        65  Shirt              92  Background
   44  Shoulder Accessories    66  Pants            None  Bundle
   45  Front Accessories       67  Jacket
   46  Back Accessories        68  Sweater
   47  Waist Accessories       76  Eyebrows · 77 Eyelashes

⚠️ `HairAccessory` (41) EST DANS LA LISTE. Le propriétaire l'a explicitement
exigé : un ancien filtre l'excluait, et « Medusa Snakes » — deuxième du
classement officiel — disparaissait.
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone

#  Bornes de l'attente après un 429. Mêmes valeurs que `roblox_veille` : c'est
#  le MÊME seau, il n'y a aucune raison d'y répondre différemment.
ATTENTE_429_MIN = 5.0
ATTENTE_429_MAX = 60.0
ATTENTE_429_DEFAUT = 25.0


def _attente_429(entetes) -> float:
    """Combien attendre après un 429 — d'après ce que Roblox ANNONCE.

    ⚠️ LE PLUS GRAND DES DEUX EN-TÊTES, pas le premier trouvé : mesuré le
    30/08, `retry-after: 5` et `x-ratelimit-reset: 12` se contredisent sur la
    même réponse. Prendre le premier faisait repartir dans le mur.
    ⚠️ Et un peu d'aléa, JAMAIS À LA BAISSE : Railway sort par une IP partagée,
    deux applications qui repartent à la même seconde se refont refuser
    ensemble.
    """
    annonces = []
    for cle in ("Retry-After", "retry-after", "x-ratelimit-reset"):
        try:
            v = float(str((entetes or {}).get(cle)).strip())
            if v > 0:
                annonces.append(v)
        except Exception:
            continue
    base = (max(annonces) + 2.0) if annonces else ATTENTE_429_DEFAUT
    return max(ATTENTE_429_MIN,
               min(ATTENTE_429_MAX, base * random.uniform(1.0, 1.3)))

#  ⚠️ DOMAINE EN DUR — règle du dépôt : une URL suivie par ce bot est
#  RECONSTRUITE, jamais recopiée d'une réponse.
API_RECHERCHE = "https://catalog.roblox.com/v2/search/items/details"
CREATEUR_ROBLOX = 1

#  Les huit types que le propriétaire nomme, plus rien. Chaque nombre a été
#  relevé le 30/08 avec sa taxonomie officielle (voir l'en-tête).
#  ⚠️ CE N'EST PAS UNE LISTE « À COMPLÉTER PLUS TARD ». Tout ce qui n'y est pas
#  est REJETÉ AVEC SON MOTIF, visible dans `/roblox marche`. Si un type doit
#  entrer, il se verra dans ce tableau — pas dans un silence.
TYPES_ACCESSOIRE = {
    8: "Chapeau / accessoire de tête",
    41: "Cheveux",
    42: "Accessoire de visage",
    43: "Accessoire de cou",
    44: "Accessoire d'épaule",
    45: "Accessoire de face avant",
    46: "Accessoire de dos",
    47: "Accessoire de taille",
}

#  Ce qu'on rejette, avec le mot juste. Le propriétaire a demandé de ne pas
#  confondre accessoires, bundles, animations, parties du corps, vêtements
#  classiques et objets non portables — cette table nomme chaque refus.
TYPES_CONNUS_REJETES = {
    11: "vêtement classique (chemise)",
    12: "vêtement classique (pantalon)",
    64: "vêtement en couches (t-shirt)",
    65: "vêtement en couches (chemise)",
    66: "vêtement en couches (pantalon)",
    67: "vêtement en couches (veste)",
    68: "vêtement en couches (pull)",
    76: "trait du visage (sourcils)",
    77: "trait du visage (cils)",
    88: "maquillage (visage)",
    89: "maquillage (lèvres)",
    90: "maquillage (yeux)",
    92: "décor, non portable (arrière-plan)",
}

_log = print
_session = None


def setup(*, session=None, log=None):
    """Branche le module. `session` est un aiohttp.ClientSession partagé."""
    global _session, _log
    if session is not None:
        _session = session
    if log is not None:
        _log = log


def est_accessoire(item: dict) -> tuple[bool, str]:
    """(accepté, motif). Le motif est affiché tel quel dans le diagnostic.

    ⚠️ ON REND TOUJOURS UN MOTIF, MÊME QUAND ON ACCEPTE. Un filtre qui rejette
    en silence est indébogable : le propriétaire a passé une session entière à
    chercher pourquoi « Medusa Snakes » n'apparaissait pas.
    """
    if str(item.get("itemType") or "") != "Asset":
        return False, f"n'est pas un Asset ({item.get('itemType') or 'Bundle'})"
    if str(item.get("creatorType") or "") != "User":
        return False, f"créateur de type {item.get('creatorType')!r}"
    try:
        if int(item.get("creatorTargetId")) != CREATEUR_ROBLOX:
            return False, f"créateur {item.get('creatorTargetId')} ≠ 1"
    except (TypeError, ValueError):
        return False, "créateur illisible"
    at = item.get("assetType")
    try:
        at = int(at)
    except (TypeError, ValueError):
        return False, "type d'objet absent"
    if at in TYPES_ACCESSOIRE:
        return True, TYPES_ACCESSOIRE[at]
    if at in TYPES_CONNUS_REJETES:
        return False, TYPES_CONNUS_REJETES[at]
    #  ⚠️ UN TYPE INCONNU SE DIT. Roblox en ajoute régulièrement ; le taire
    #  ferait disparaître une famille entière d'accessoires sans un mot.
    return False, f"type {at} inconnu de la table — à vérifier"


def _ouvrir():
    """Session HTTP. Réutilise celle du bot si elle est branchée."""
    if _session is not None and not getattr(_session, "closed", False):
        return _SessionEmpruntee(_session)
    import aiohttp
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": "GoRp-Discord-Bot/1.0 (veille Marketplace)",
                 "Accept": "application/json"})


class _SessionEmpruntee:
    """Emprunte la session du bot sans la fermer en sortant."""

    def __init__(self, sess):
        self._s = sess

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *a):
        return False


def parametres(limite: int = 120, curseur: str | None = None) -> dict:
    """Les paramètres du filtre officiel. Un seul endroit, pour qu'ils ne
    divergent jamais entre le relevé, le diagnostic et les tests."""
    p = {
        "Category": 1,              # « Tous » sur le site — PAS Category=11 :
        #  mesuré, `Category=11` + `Subcategory=19` excluait « Medusa Snakes »
        #  (type Cheveux), pourtant deuxième du classement officiel.
        "CreatorType": "User",
        "CreatorTargetId": CREATEUR_ROBLOX,
        "SortType": 3,              # « Publié récemment »
        "SortAggregation": 5,       # présent dans la requête du site
        "IncludeNotForSale": "true",   # « Afficher les items indisponibles »
        "Limit": int(limite),
    }
    if curseur:
        p["Cursor"] = curseur
    return p


async def relever_page(curseur: str | None = None, limite: int = 120) -> dict:
    """Une page du filtre officiel, DANS SON ORDRE.

    Rend `{"items": [...], "curseur": str|None, "code": int|None}`.
    Chaque item porte `rang_marche`, son rang 1-based dans le classement.

    ⚠️ ON NE RETRIE RIEN, JAMAIS. C'est tout l'objet de ce module : l'ordre
    RENDU PAR L'API *EST* la réponse. Un `sort()` par date de création ici
    transformerait la question en une autre, et c'est précisément l'erreur
    signalée par le propriétaire.
    """
    out = {"items": [], "curseur": None, "code": None}
    #  ⚠️ CE MODULE TAPE LE SEAU LE PLUS ÉTROIT DU BOT, TOUTES LES 4 MINUTES.
    #  Même route que `roblox_veille` (`/v2/search/items/details`), budget
    #  mesuré `12, 12;w=60`, et la production est déjà descendue à
    #  `reste_min=2/12`. La première version n'avait AUCUNE gestion du 429 :
    #  elle repartait aveuglément quatre minutes plus tard, ce qui est la
    #  meilleure façon de rester bloqué. Trouvé en réfutation le 30/08.
    try:
        async with _ouvrir() as sess:
            for tentative in (1, 2):
                async with sess.get(
                        API_RECHERCHE,
                        params=parametres(limite, curseur)) as r:
                    out["code"] = r.status
                    if r.status == 429 and tentative == 1:
                        attente = _attente_429(r.headers)
                        _log(f"[roblox_marche] HTTP 429 — attente "
                             f"{attente:.0f} s puis une reprise")
                        await asyncio.sleep(attente)
                        continue
                    if r.status != 200:
                        _log(f"[roblox_marche] HTTP {r.status} sur le filtre "
                             f"« Publié récemment »")
                        return out
                    data = await r.json()
                    break
            else:
                return out
    except Exception as ex:
        _log(f"[roblox_marche relever_page] {type(ex).__name__}: {ex}")
        return out
    out["curseur"] = data.get("nextPageCursor") or None
    #  Le rang est posé ICI, avant que quiconque puisse toucher à la liste.
    depart = 0
    for i, brut in enumerate(data.get("data") or [], start=depart + 1):
        out["items"].append(_normaliser(brut, i))
    return out


def _normaliser(brut: dict, rang: int) -> dict:
    """Ce qu'on retient d'un article, SANS toucher à son rang."""
    try:
        aid = int(brut.get("id") or 0)
    except (TypeError, ValueError):
        aid = 0
    accepte, motif = est_accessoire(brut)
    return {
        "rang_marche": rang,
        "asset_id": aid,
        "nom": str(brut.get("name") or "")[:120],
        "item_type": str(brut.get("itemType") or ""),
        "asset_type": brut.get("assetType"),
        "createur_id": brut.get("creatorTargetId"),
        "createur_nom": str(brut.get("creatorName") or ""),
        #  ⚠️ INFORMATIONS COMPLÉMENTAIRES, JAMAIS UN CRITÈRE DE TRI.
        "cree_le": brut.get("itemCreatedUtc"),
        "maj_le": brut.get("itemUpdatedUtc"),
        "prix": brut.get("price"),
        "statut_prix": brut.get("priceStatus"),
        "en_vente": not bool(brut.get("isOffSale")),
        "restrictions": list(brut.get("itemRestrictions") or []),
        "accepte": accepte,
        "motif": motif,
    }


async def dernier_accessoire_publie(max_pages: int = 3) -> dict | None:
    """Le PREMIER accessoire valide du filtre officiel. `None` si aucun.

    ⚠️ « PREMIER » AU SENS DU MARKETPLACE, pas au sens de la date. On parcourt
    dans l'ordre rendu et on s'arrête au premier accepté — c'est littéralement
    l'algorithme demandé.

    ⚠️ ON PAGINE SI LA PAGE 1 N'EN CONTIENT AUCUN. Rare (elle en contient
    presque toujours), mais un classement qui commencerait par vingt fonds
    d'écran rendrait `None` alors que la réponse existe page 2.
    """
    curseur, page = None, 0
    while page < max(1, int(max_pages)):
        rep = await relever_page(curseur)
        if rep["code"] != 200:
            return None
        for it in rep["items"]:
            if it["accepte"]:
                return it
        curseur = rep["curseur"]
        page += 1
        if not curseur:
            break
    return None


async def dernier_cree_techniquement(max_pages: int = 3) -> dict | None:
    """L'autre indicateur : la date de création la plus récente.

    ⚠️ IL NE REMPLACE PAS LE PREMIER, il l'ÉCLAIRE. Le propriétaire veut voir
    les deux côte à côte, parce que c'est leur DIVERGENCE qui explique pourquoi
    deux systèmes donnent des réponses différentes. Ici, et seulement ici, on a
    le droit de trier par date.
    """
    meilleur, curseur, page = None, None, 0
    while page < max(1, int(max_pages)):
        rep = await relever_page(curseur)
        if rep["code"] != 200:
            break
        for it in rep["items"]:
            if not it["accepte"] or not it["cree_le"]:
                continue
            if meilleur is None or str(it["cree_le"]) > str(meilleur["cree_le"]):
                meilleur = it
        curseur = rep["curseur"]
        page += 1
        if not curseur:
            break
    return meilleur


async def tableau_diagnostic(combien: int = 20) -> list[dict]:
    """Les N premiers du classement, dans l'ordre exact, acceptés ET rejetés.

    C'est le `/debug-marketplace-recent` demandé. Sans lui, un filtre trop
    strict fait disparaître une famille entière d'articles sans un mot — c'est
    ce qui est arrivé avec les cheveux.
    """
    rep = await relever_page(limite=120)
    return rep["items"][:max(1, int(combien))]


# ═══════════════════════════════════════════════════════════════════════════════
#  Le suivi de la tête de classement
# ═══════════════════════════════════════════════════════════════════════════════

_get_db = None


def brancher_base(get_db) -> None:
    global _get_db
    _get_db = get_db


async def init_db() -> None:
    """La table du suivi. Idempotent."""
    if _get_db is None:
        return
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_marche_tete("
            " asset_id INTEGER PRIMARY KEY,"
            " nom TEXT,"
            " item_type TEXT,"
            " asset_type INTEGER,"
            " createur_id INTEGER,"
            " rang_marche INTEGER,"
            " vu_la_1re_fois TEXT NOT NULL,"
            " vu_la_derniere_fois TEXT NOT NULL,"
            " cree_le TEXT,"
            " maj_le TEXT,"
            " statut_prix TEXT,"
            " en_vente INTEGER,"
            " parametres TEXT,"
            " empreinte TEXT)"
        )
        #  ⚠️ LA TETE RETENUE, SEULE ET UNIQUE. Une ligne, id=1. Elle designe
        #  le premier ACCEPTE — pas le rang 1 brut, qui peut etre un vetement
        #  ou un Bundle. Confondre les deux faisait crier « la tete a change »
        #  toutes les quatre minutes sur une liste immobile.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_marche_retenue("
            " id INTEGER PRIMARY KEY CHECK(id = 1),"
            " asset_id INTEGER NOT NULL,"
            " nom TEXT,"
            " asset_type INTEGER,"
            " rang_marche INTEGER,"
            " cree_le TEXT,"
            " maj_le TEXT,"
            " statut_prix TEXT,"
            " en_vente INTEGER,"
            " vu_le TEXT NOT NULL)"
        )
        await db.commit()


def empreinte(items: list[dict]) -> str:
    """Une empreinte de l'ORDRE, pas seulement du contenu.

    Deux relevés qui portent les mêmes articles dans un ordre différent DOIVENT
    donner deux empreintes différentes : c'est le changement d'ordre qui nous
    intéresse.
    """
    import hashlib
    brut = "|".join(f"{it['rang_marche']}:{it['asset_id']}" for it in items)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:32]


async def noter_tete(items: list[dict]) -> dict:
    """Enregistre les N premiers et dit si la TÊTE a changé.

    Rend `{"change": bool, "avant": int|None, "maintenant": int|None}`.
    """
    res = {"change": False, "avant": None, "maintenant": None}
    if not items or _get_db is None:
        return res
    tete = next((it for it in items if it["accepte"]), None)
    if tete is None:
        return res
    res["maintenant"] = tete["asset_id"]
    maintenant = datetime.now(timezone.utc).isoformat()
    try:
        async with _get_db() as db:
            #  ⚠️ ON COMPARE LA TÊTE ACCEPTÉE, PAS LE RANG 1 BRUT — corrigé le
            #  30/08 après réfutation. `rang_marche` est écrit sur les vingt
            #  premiers, acceptés ET rejetés. Or `tete` est le premier ACCEPTÉ.
            #  Dès qu'un article rejeté (vêtement, Bundle, arrière-plan) occupe
            #  le rang 1 — et 28 des 119 items de la page 1 sont rejetés —
            #  `avant` et `tete` ne pouvaient plus jamais coïncider :
            #  « LA TÊTE DU CLASSEMENT A CHANGÉ » se serait imprimé toutes les
            #  quatre minutes sur une liste immobile. Et `tete_memorisee`, que
            #  `/roblox marche` présente comme « dernier premier confirmé »,
            #  aurait rendu un article que le filtre rejette.
            #  On garde donc une ligne dédiée, `rang_marche = 0`, qui désigne
            #  LA TÊTE RETENUE et rien d'autre.
            async with db.execute(
                "SELECT asset_id FROM roblox_marche_retenue WHERE id=1"
            ) as cur:
                row = await cur.fetchone()
            res["avant"] = int(row[0]) if row else None
            res["change"] = bool(res["avant"] is not None
                                 and res["avant"] != tete["asset_id"])
            #  On garde les vingt premiers ET leur ordre : c'est la seule façon
            #  de dire plus tard « il est monté de la 7e à la 1re place ».
            emp = empreinte(items)
            params = json.dumps(parametres(), ensure_ascii=False)
            #  La tête RETENUE porte le rang 0 : c'est elle, et elle seule, que
            #  `tete_memorisee` doit rendre. Les vingt bruts gardent leur rang
            #  réel, pour pouvoir dire plus tard « il est monté de la 7e à la
            #  1re place ».
            #  ⚠️ LA TÊTE RETENUE VIT DANS SA PROPRE TABLE, PAS DANS UN RANG 0.
            #  `asset_id` est la clé primaire de `roblox_marche_tete` : une
            #  ligne « rang 0 » serait écrasée par la ligne du même article
            #  dans le top 20, quelques itérations plus loin. Deux rôles
            #  différents, deux tables.
            await db.execute(
                "INSERT INTO roblox_marche_retenue(id, asset_id, nom,"
                " asset_type, rang_marche, cree_le, maj_le, statut_prix,"
                " en_vente, vu_le) VALUES(1,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET asset_id=?, nom=?,"
                "  asset_type=?, rang_marche=?, cree_le=?, maj_le=?,"
                "  statut_prix=?, en_vente=?, vu_le=?",
                (tete["asset_id"], tete["nom"], tete["asset_type"],
                 tete["rang_marche"], tete["cree_le"], tete["maj_le"],
                 tete["statut_prix"], int(bool(tete["en_vente"])), maintenant,
                 tete["asset_id"], tete["nom"], tete["asset_type"],
                 tete["rang_marche"], tete["cree_le"], tete["maj_le"],
                 tete["statut_prix"], int(bool(tete["en_vente"])), maintenant))
            for i, it in enumerate(items[:20], start=1):
                await db.execute(
                    "INSERT INTO roblox_marche_tete(asset_id, nom, item_type,"
                    " asset_type, createur_id, rang_marche, vu_la_1re_fois,"
                    " vu_la_derniere_fois, cree_le, maj_le, statut_prix,"
                    " en_vente, parametres, empreinte)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(asset_id) DO UPDATE SET"
                    "  rang_marche=?, vu_la_derniere_fois=?, statut_prix=?,"
                    "  en_vente=?, empreinte=?",
                    (it["asset_id"], it["nom"], it["item_type"],
                     it["asset_type"], it["createur_id"], i, maintenant,
                     maintenant, it["cree_le"], it["maj_le"],
                     it["statut_prix"], int(bool(it["en_vente"])), params, emp,
                     i, maintenant, it["statut_prix"],
                     int(bool(it["en_vente"])), emp))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_marche noter_tete] {ex}")
    return res


async def tete_memorisee() -> dict | None:
    """Le dernier premier-du-classement confirmé.

    ⚠️ SERT DE REPLI QUAND L'API TOMBE. Le propriétaire l'a demandé : « une
    erreur API conserve le dernier résultat confirmé ». Afficher « inconnu »
    parce que Roblox a hoqueté serait pire que de dire ce qu'on savait.
    """
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT asset_id, nom, asset_type, cree_le, maj_le,"
                " statut_prix, en_vente, vu_le, rang_marche"
                " FROM roblox_marche_retenue WHERE id=1") as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {"asset_id": int(row[0]), "nom": row[1], "asset_type": row[2],
                "cree_le": row[3], "maj_le": row[4], "statut_prix": row[5],
                "en_vente": bool(row[6]), "vu_le": row[7],
                #  Le rang REEL de la tete retenue, pas un « 1 » en dur : elle
                #  peut tres bien etre 3e si les deux premiers sont rejetes.
                "rang_marche": row[8]}
    except Exception as ex:
        _log(f"[roblox_marche tete_memorisee] {ex}")
        return None
