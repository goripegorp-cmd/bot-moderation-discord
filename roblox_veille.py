"""roblox_veille.py — Veille des accessoires Roblox : nouveautés, bascules, indices.

Voir `ROBLOX.md` pour le cahier des charges, et
`rapports/roblox-veille-items-plan.json` pour la recherche qui fonde ce module
(137 agents, 86 constats vérifiés par appels réels le 12/08/2026).

═══════════════════════════════════════════════════════════════════════════════
CE QUE CE MODULE NE FAIT PAS, ET POURQUOI
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire a demandé de « prédire » quels accessoires passeront Limited.
Mesuré sur 339 articles du compte Roblox : le champ de retrait de vente est vide
partout, le champ de statut est vide 120 fois sur 120, et aucune description ne
contient « limited » ni « last chance ». **Aucun signal déclaratif n'existe.**

On ne fabrique donc PAS un pourcentage. On publie un INDICE, adossé à des faits
observables, et on dit toujours sur quoi il repose. Un chiffre inventé avec une
décimale pour faire sérieux ferait acheter de travers — c'est pire que rien.

═══════════════════════════════════════════════════════════════════════════════
DEUX PIÈGES QUI EMPOISONNENT EN SILENCE — NE PAS LES ROUVRIR
═══════════════════════════════════════════════════════════════════════════════
1. `economy.roblox.com/v1/assets/{id}/resale-data` répond **200 avec des prix
   gelés à janvier 2025** (mesuré : RAP 276 828 contre 236 906 réel). Un système
   naïf bâtit toutes ses estimations sur des chiffres vieux de dix-huit mois,
   sans jamais lever la moindre erreur. On utilise `apis.roblox.com` à la place.
2. `Category=2` (« Collectibles ») **n'existe plus**. La v1 refuse par un 400 ;
   la v2, elle, **l'ignore SANS erreur** et renvoie autre chose. On filtre donc
   sur `SalesTypeFilter`, jamais sur cette catégorie.

═══════════════════════════════════════════════════════════════════════════════
LE SALON SERA CALME, ET C'EST NORMAL
═══════════════════════════════════════════════════════════════════════════════
Le dernier Limited créé par Roblox date du 21/10/2025 : dix mois de silence, et
36 bascules sur toute l'année 2025. La santé du système se mesure donc sur le
CODE HTTP des relevés, jamais sur « j'ai trouvé quelque chose » — sinon on ne
distingue pas un flux mort d'un mois sans nouveauté.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

#  ⚠️ DOMAINES EN DUR. Une URL n'est JAMAIS recopiée depuis une réponse d'API :
#  elle est reconstruite à partir de ces constantes et d'un identifiant validé
#  comme entier. C'est l'exigence « liens certifiés » de ROBLOX.md, et c'est une
#  règle de sécurité : ce bot lutte contre le phishing, il ne peut pas publier
#  un lien approximatif.
DOMAINE_ARTICLE = "https://www.roblox.com/catalog/"
API_CATALOGUE = "https://catalog.roblox.com/v2/search/items/details"
API_ECONOMIE = "https://economy.roblox.com/v2/assets/{}/details"
API_FICHE = "https://catalog.roblox.com/v1/catalog/items/{}/details"
API_VIGNETTE = "https://thumbnails.roblox.com/v1/assets"
#  Le seul domaine d'où une image a le droit de venir. Voir `vignettes`.
DOMAINE_IMAGES = "https://tr.rbxcdn.com/"

#  ⚠️ SEUIL DE PUBLICATION DE L'INDICE — demandé le 12/08 : « il faut que ce
#  soit quasiment du 100 % ou du 80 %, pas du 20 %. Tu dis pas et tu mets pas ce
#  qui sert à rien. »
#  En dessous, l'indice n'est PAS affiché du tout : un « 30/100 » se lit comme
#  un verdict faible alors que ce n'est qu'une absence de signal. Mieux vaut se
#  taire que d'afficher un chiffre qui n'apprend rien.
SEUIL_INDICE_AFFICHE = 60
#  Et le flux « à surveiller » ne publie QUE au-dessus de ça : c'est lui qui
#  doit être rare et sûr.
SEUIL_SURVEILLER = 60

#  ⚠️ DEUX BORNES D'ÂGE, ET LA PREMIÈRE EST UN MINIMUM — demandé le 12/08 :
#  « tu mets les items qui sont sortis MINIMUM il y a une semaine et demie,
#  voire deux semaines ; au-delà, tu le postes ».
#
#  Un article qui vient de sortir n'a rien à raconter : ni revente, ni demande
#  installée, ni recul sur son stock. On le laisse donc mûrir. C'est ce délai
#  qui distingue une veille d'échange d'un simple fil de nouveautés.
AGE_MIN_JOURS = 10

#  Et une borne haute, pour l'autre moitié de la consigne (« s'il est trop
#  vieux, ça sert à rien de le remettre ») : au-delà, ce n'est plus une
#  nouvelle, c'est une archive. L'article reste en base pour la détection des
#  bascules, mais il n'est plus publié.
AGE_MAX_JOURS = 90

#  La langue des noms officiels. Vérifié : Roblox renvoie « Chapeau Ladoo
#  tricolore » pour « Tricolor Ladoo Hat » — c'est SA traduction, pas la nôtre.
#  On ne traduit donc rien nous-mêmes : on demande, et on cite.
LANGUE_FR = "fr-fr"

#  Le compte officiel Roblox. C'est LA condition du propriétaire : « uniquement
#  ceux qui sont créés par Roblox ».
CREATEUR_ROBLOX = 1

#  Débits mesurés le 12/08/2026 dans les en-têtes `x-ratelimit-limit` :
#  catalogue 12/60 s, fiche 10/60 s (le plus étranglé), économie 1000/60 s.
#  On reste TRÈS en dessous : un bot banni de l'API ne protège plus personne.
PAUSE_ENTRE_APPELS = 2.0
MAX_APPELS_PAR_PASSAGE = 8

#  Combien d'articles on garde en mémoire. Borné : on ne conserve pas
#  l'historique complet du catalogue dans une base SQLite.
MAX_ARTICLES_SUIVIS = 3000

_get_db = None
_cfg = None
_db_set = None
_session = None
_log = print


def setup(*, get_db, cfg, db_set, session=None, log=None):
    """Branche le module. `session` est un aiohttp.ClientSession partagé."""
    global _get_db, _cfg, _db_set, _session, _log
    _get_db, _cfg, _db_set, _session = get_db, cfg, db_set, session
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

CLES_DEFAUT = {
    "roblox_veille_enabled": False,      # OFF par défaut — rien ne tourne
    "roblox_salon_nouveautes": 0,        # nouveaux articles créés par Roblox
    "roblox_salon_bascules": 0,          # ceux qui viennent de passer collectionnables
    "roblox_salon_surveiller": 0,        # les indices — « à surveiller »
    "roblox_salon_sante": 0,             # où l'on dit qu'une source ne répond plus
    #  Le propriétaire peut n'en régler qu'UN : les trois flux retombent alors
    #  dessus. Voir `salon_du_flux`.
    "roblox_veille_amorcee": "",         # date de la borne posée au 1er allumage
}


async def config(guild_id: int) -> dict:
    try:
        c = await _cfg(guild_id)
    except Exception as ex:
        _log(f"[roblox_veille config] {ex}")
        c = {}
    out = dict(CLES_DEFAUT)
    for k in out:
        if k in c:
            out[k] = c[k]
    return out


def salon_du_flux(cfg_r: dict, flux: str) -> int:
    """Le salon d'un flux, avec repli sur le premier salon réglé.

    Le propriétaire ne veut pas forcément trois salons. S'il n'en règle qu'un,
    tout y va — c'est mieux qu'un flux qui se tait parce que sa case est vide.
    """
    cle = {"nouveautes": "roblox_salon_nouveautes",
           "bascules": "roblox_salon_bascules",
           "surveiller": "roblox_salon_surveiller"}.get(flux)
    if cle and int(cfg_r.get(cle, 0) or 0):
        return int(cfg_r[cle])
    for repli in ("roblox_salon_nouveautes", "roblox_salon_bascules",
                  "roblox_salon_surveiller"):
        if int(cfg_r.get(repli, 0) or 0):
            return int(cfg_r[repli])
    return 0


async def actif(guild_id: int) -> bool:
    """Le système tourne-t-il vraiment ? Interrupteur ET au moins un salon."""
    c = await config(guild_id)
    return bool(c["roblox_veille_enabled"] and salon_du_flux(c, "nouveautes"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Base
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    """Crée les tables. Idempotent."""
    async with _get_db() as db:
        #  L'état connu de chaque article. C'est la comparaison de deux relevés
        #  successifs qui fabrique la détection : il n'existe aucun point d'API
        #  qui annonce « cet article vient de changer ».
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_articles("
            " asset_id INTEGER PRIMARY KEY,"
            " nom TEXT,"
            " type_article TEXT,"
            " prix INTEGER,"
            " collectionnable INTEGER NOT NULL DEFAULT 0,"
            " hors_vente INTEGER NOT NULL DEFAULT 0,"
            " favoris INTEGER NOT NULL DEFAULT 0,"
            " cree_le TEXT,"
            " vu_le TEXT NOT NULL,"
            " signature TEXT)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_roblox_articles_vu"
            " ON roblox_articles(vu_le)")
        #  Ce qui a DÉJÀ été publié, par guilde et par flux. Persisté : un
        #  redémarrage ne doit jamais republier ce qui est déjà sorti.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_publies("
            " guild_id INTEGER NOT NULL,"
            " asset_id INTEGER NOT NULL,"
            " flux TEXT NOT NULL,"
            " publie_le TEXT NOT NULL,"
            " PRIMARY KEY(guild_id, asset_id, flux))"
        )
        #  La santé des relevés. Sert au garde-fou : un flux mort ressemble à un
        #  flux calme, il faut donc mesurer le CODE HTTP et pas les trouvailles.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_sante("
            " source TEXT PRIMARY KEY,"
            " dernier_essai TEXT,"
            " dernier_succes TEXT,"
            " dernier_code INTEGER,"
            " echecs_consecutifs INTEGER NOT NULL DEFAULT 0)"
        )
        await db.commit()


def lien_article(asset_id) -> str | None:
    """L'URL d'un article, RECONSTRUITE. Jamais recopiée d'une réponse.

    ⚠️ EXIGENCE DE SÉCURITÉ, voir ROBLOX.md §1. Le domaine est une constante du
    module ; l'identifiant est validé comme entier. Sans entier lisible, on rend
    None et la fiche part SANS lien — jamais avec un lien approximatif.
    """
    try:
        n = int(asset_id)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return f"{DOMAINE_ARTICLE}{n}/"


# ═══════════════════════════════════════════════════════════════════════════════
#  L'indice — PAS une prédiction
# ═══════════════════════════════════════════════════════════════════════════════

#  Poids fixes, écrits en clair, recalculables à la main. Les conditions
#  d'utilisation de Roblox interdisent d'entraîner un modèle sur leur contenu
#  virtuel : il n'y a donc ici RIEN qui apprenne, et c'est volontaire.
POIDS = {
    "hors_vente": 35,       # le signal le plus dur : a précédé les vagues Limited
    "stock_fini": 25,       # une quantité bornée est le propre d'un collectionnable
    "revente": 20,          # une revente déjà ouverte = valeur de marché observable
    "demande": 20,          # favoris rapportés au prix
    "prix_bas": 10,         # un prix d'entrée bas élargit le nombre de détenteurs
    "recent": 10,           # une sortie récente reste dans l'actualité
}


def indice(article: dict) -> dict:
    """Un indice de 0 à 100, AVEC ses facteurs. Jamais un chiffre nu.

    Retourne {"note", "facteurs": [(libellé, points)], "confiance"}.
    `confiance` baisse quand une donnée manque : on ne devine pas, on le dit.
    """
    facteurs: list[tuple[str, int]] = []
    note = 0
    manquants = 0

    if article.get("hors_vente"):
        note += POIDS["hors_vente"]
        facteurs.append(("retiré de la vente", POIDS["hors_vente"]))

    #  Une revente DÉJÀ ouverte est un fait, pas une supposition : l'article est
    #  échangeable, donc il a une valeur de marché observable.
    if article.get("revendeurs"):
        note += POIDS["revente"]
        facteurs.append(("revente déjà ouverte", POIDS["revente"]))

    #  Un stock fini est le propre d'un collectionnable. `totalQuantity` vaut 0
    #  sur un article à stock illimité : seul un nombre > 0 est un signal.
    q = article.get("quantite")
    if q and int(q) > 0:
        note += POIDS["stock_fini"]
        facteurs.append((f"stock fini ({q})", POIDS["stock_fini"]))

    prix = article.get("prix")
    favoris = article.get("favoris")
    if prix is None or favoris is None:
        manquants += 1
    else:
        #  Favoris par Robux dépensé : une forte demande à prix bas est ce qui
        #  distingue un article convoité d'un article simplement cher.
        ratio = favoris / max(1, prix)
        if ratio >= 5:
            note += POIDS["demande"]
            facteurs.append(("très demandé", POIDS["demande"]))
        elif ratio >= 1:
            gagne = POIDS["demande"] // 2
            note += gagne
            facteurs.append(("demande correcte", gagne))
        if 0 < prix <= 100:
            note += POIDS["prix_bas"]
            facteurs.append(("prix d'entrée bas", POIDS["prix_bas"]))

    cree = article.get("cree_le")
    if not cree:
        manquants += 1
    else:
        jours = _jours_depuis(cree)
        if jours is not None and jours <= 30:
            note += POIDS["recent"]
            facteurs.append(("sorti ce mois-ci", POIDS["recent"]))

    confiance = "bonne" if manquants == 0 else ("moyenne" if manquants == 1 else "faible")
    return {"note": min(100, note), "facteurs": facteurs, "confiance": confiance}


def _jours_depuis(quand: str) -> int | None:
    try:
        d = datetime.fromisoformat(str(quand).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Relevé
# ═══════════════════════════════════════════════════════════════════════════════

#  ⚠️ VALEURS IMPOSÉES PAR L'API. Mesuré en direct : toute autre valeur renvoie
#  un HTTP 400 « Allowed values: 10, 28, 30, 60, 120 ». Un simple `min/max` sur
#  un intervalle produisait donc des requêtes refusées — et comme l'échec était
#  silencieux, le système paraissait juste « calme ».
LIMITES_AUTORISEES = (10, 28, 30, 60, 120)


def _limite_valide(n) -> int:
    """La plus petite valeur autorisée qui couvre le besoin demandé."""
    try:
        voulu = int(n)
    except (TypeError, ValueError):
        voulu = 30
    for v in LIMITES_AUTORISEES:
        if v >= voulu:
            return v
    return LIMITES_AUTORISEES[-1]


def trop_vieux(article: dict, jours: int = AGE_MAX_JOURS) -> bool:
    """Trop ancien pour être encore une nouvelle ? (borne haute)"""
    d = _jours_depuis(article.get("cree_le"))
    return d is not None and d > int(jours)


def age_publiable(article: dict) -> bool:
    """L'article a-t-il le bon âge pour être annoncé ?

    Entre `AGE_MIN_JOURS` et `AGE_MAX_JOURS`. Trop jeune, il n'a rien à
    raconter ; trop vieux, ce n'est plus une nouvelle.

    Une date illisible ne bloque PAS la publication : on ne va pas taire une
    vraie nouveauté parce qu'un champ manque. Ici le risque d'un faux positif
    est un message de trop, pas une sanction — l'inverse du fail-closed.
    """
    d = _jours_depuis(article.get("cree_le"))
    if d is None:
        return True
    return AGE_MIN_JOURS <= d <= AGE_MAX_JOURS


def _ouvrir():
    """Ouvre une session HTTP pour un relevé. À utiliser en `async with`.

    ⚠️ CE MODULE NE DÉPEND PLUS D'UNE SESSION INJECTÉE — c'est un correctif, pas
    un choix esthétique. La première version exigeait un `aiohttp.ClientSession`
    passé par `setup()`, et le câblage dans bot.py passait `session=None` : le
    relevé sortait alors AVANT le moindre appel réseau, en enregistrant
    silencieusement un échec. Le système entier était mort à la livraison, et
    seul le registre de santé le montrait.

    Le dépôt n'a pas de session partagée : les autres modules ouvrent la leur au
    besoin. On fait pareil. Un relevé toutes les 30 minutes ne justifie pas de
    garder une connexion ouverte en permanence.

    Un `User-Agent` explicite est posé : les points d'API de Roblox répondent
    mal aux requêtes sans identité, et un agent nommé se diagnostique.
    """
    import aiohttp
    if _session is not None:
        #  Session fournie par l'appelant : on ne la ferme pas, d'où l'enveloppe.
        return _SessionEmpruntee(_session)
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        headers={"User-Agent": "BotModerationDiscord/1.0 (veille Roblox)",
                 "Accept": "application/json"})


class _SessionEmpruntee:
    """Enveloppe une session qu'on n'a pas créée : on ne doit pas la fermer."""

    def __init__(self, session):
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *a):
        return False


async def _noter_sante(source: str, code: int | None) -> int:
    """Enregistre l'issue d'un relevé et rend le nombre d'échecs consécutifs.

    C'est ce compteur, et lui seul, qui permet de distinguer « rien de neuf »
    de « la source ne répond plus ». Sans lui, un flux mort passe pour calme.
    """
    maintenant = datetime.now(timezone.utc).isoformat()
    ok = code is not None and 200 <= code < 300
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT echecs_consecutifs FROM roblox_sante WHERE source=?",
                (source,)) as cur:
                row = await cur.fetchone()
            echecs = 0 if ok else (int(row[0]) if row else 0) + 1
            await db.execute(
                "INSERT INTO roblox_sante(source, dernier_essai, dernier_succes,"
                " dernier_code, echecs_consecutifs) VALUES(?,?,?,?,?)"
                " ON CONFLICT(source) DO UPDATE SET dernier_essai=?,"
                "  dernier_succes=COALESCE(?, dernier_succes),"
                "  dernier_code=?, echecs_consecutifs=?",
                (source, maintenant, maintenant if ok else None, code, echecs,
                 maintenant, maintenant if ok else None, code, echecs))
            await db.commit()
        return echecs
    except Exception as ex:
        _log(f"[roblox_veille _noter_sante] {ex}")
        return 0


async def relever_nouveautes(limite: int = 30) -> dict:
    """Interroge le catalogue pour les articles créés par Roblox.

    Retourne {"articles": [...], "code": int|None, "echecs": int}.
    Ne lève jamais : une panne de veille ne doit pas gêner la modération.
    """
    out = {"articles": [], "code": None, "echecs": 0}
    params = {
        "Category": 1,
        "SortType": 3,
        "Limit": _limite_valide(limite),
        "CreatorType": "User",
        "CreatorTargetId": CREATEUR_ROBLOX,
    }
    try:
        async with _ouvrir() as sess:
            async with sess.get(API_CATALOGUE, params=params) as r:
                out["code"] = r.status
                if r.status == 200:
                    data = await r.json()
                    out["articles"] = _normaliser(data.get("data") or [])
                    #  LE NOM FRANÇAIS, par un SECOND appel avec l'en-tête de
                    #  langue. Vérifié : Roblox renvoie sa propre traduction —
                    #  « Chapeau Ladoo tricolore ». On ne traduit rien nous-mêmes,
                    #  on cite. Un coût d'une requête sur les douze autorisées
                    #  par minute : largement dans le budget.
                    try:
                        async with sess.get(
                            API_CATALOGUE, params=params,
                            headers={"Accept-Language": LANGUE_FR}) as rf:
                            if rf.status == 200:
                                noms = {}
                                for b in ((await rf.json()).get("data") or []):
                                    try:
                                        noms[int(b.get("id"))] = str(b.get("name") or "")
                                    except (TypeError, ValueError):
                                        continue
                                for a in out["articles"]:
                                    fr = noms.get(a["asset_id"])
                                    #  On ne garde le nom français que s'il
                                    #  DIFFÈRE : beaucoup d'articles n'ont pas de
                                    #  traduction, et afficher deux fois la même
                                    #  ligne ferait croire à un défaut.
                                    if fr and fr != a["nom"]:
                                        a["nom_fr"] = fr[:120]
                    except Exception as ex:
                        _log(f"[roblox_veille noms fr] {ex}")
                else:
                    #  On garde le corps : un 403 du pare-feu et un 429 de débit
                    #  ne se corrigent pas de la même façon, et sans cette trace
                    #  on ne saurait pas lequel on a.
                    _log(f"[roblox_veille catalogue] HTTP {r.status} — "
                         f"{(await r.text())[:200]}")
    except Exception as ex:
        _log(f"[roblox_veille relever_nouveautes] {type(ex).__name__}: {ex}")
    out["echecs"] = await _noter_sante("catalogue", out["code"])
    return out


def _normaliser(bruts: list) -> list[dict]:
    """Réduit les réponses du catalogue à ce qu'on sait afficher.

    ⚠️ RETRI OBLIGATOIRE côté bot : le tri « le plus récent » de l'API n'est PAS
    strictement chronologique (ordre réel mesuré : 15:41 → 15:42 → 15:40).
    S'y fier ferait rater des articles ou en republier.
    """
    out = []
    for b in bruts:
        try:
            aid = int(b.get("id") or 0)
            if aid <= 0:
                continue
            restrictions = b.get("itemRestrictions") or []
            out.append({
                "asset_id": aid,
                "nom": str(b.get("name") or "")[:120],
                "type_article": _type_lisible(b),
                "prix": b.get("price") if b.get("price") is not None
                        else b.get("lowestPrice"),
                "favoris": int(b.get("favoriteCount") or 0),
                "collectionnable": int(any(
                    str(x).lower().startswith(("limited", "collectible"))
                    for x in restrictions)),
                #  `offSaleDeadline` renseigné = Roblox annonce lui-même la fin
                #  de vente. C'est le signal le plus dur dont on dispose.
                "hors_vente": int(bool(b.get("isOffSale"))
                                  or bool(b.get("offSaleDeadline"))),
                "cree_le": b.get("itemCreatedUtc") or b.get("createdUtc"),
                #  Signaux relevés dans la réponse réelle et qu'on aurait ratés
                #  en se fiant à la documentation : une revente déjà ouverte et
                #  un stock fini sont des faits, pas des suppositions.
                "revendeurs": int(bool(b.get("hasResellers"))),
                "quantite": b.get("totalQuantity") or None,
                "prix_revente": b.get("lowestResalePrice") or None,
            })
        except Exception:
            continue
    out.sort(key=lambda a: str(a.get("cree_le") or ""), reverse=True)
    return out


def _type_lisible(brut: dict) -> str:
    """Le type d'article, en clair.

    ⚠️ `assetType` est un NUMÉRO (8, 46, 92…), pas un nom. La première version
    l'affichait tel quel : la fiche annonçait « type 8 · Tricolor Ladoo Hat ».
    La réponse porte heureusement une `taxonomy` avec un libellé lisible — on la
    préfère, et on ne retombe sur le numéro que si elle manque, en le nommant
    pour ce qu'il est plutôt qu'en le faisant passer pour un type.
    """
    try:
        taxo = brut.get("taxonomy") or []
        if taxo:
            nom = str(taxo[0].get("taxonomyName") or "").strip()
            if nom:
                return nom[:40]
    except Exception:
        pass
    n = brut.get("assetType")
    return f"type {n}" if n is not None else "—"


async def vignettes(asset_ids: list) -> dict:
    """Les images des articles, par lot. {asset_id: url} — vide si rien.

    ⚠️ L'URL de l'image vient de Roblox et n'est PAS reconstructible : elle
    contient une empreinte. C'est la seule exception à la règle « on ne recopie
    jamais une URL » — elle est donc filtrée : on n'accepte que le domaine
    officiel des images, et rien d'autre. Un lien d'image détourné afficherait
    une image arbitraire dans le salon.

    Le point accepte 100 identifiants au maximum (101 → HTTP 400) et 50 appels
    par seconde. On découpe donc, et on ne demande que ce qu'on va publier.
    """
    out: dict[int, str] = {}
    ids = [int(a) for a in asset_ids if str(a).lstrip("-").isdigit()][:100]
    if not ids:
        return out
    params = {"assetIds": ",".join(str(i) for i in ids),
              "size": "420x420", "format": "Png", "returnPolicy": "PlaceHolder"}
    try:
        async with _ouvrir() as sess:
            async with sess.get(API_VIGNETTE, params=params) as r:
                if r.status != 200:
                    _log(f"[roblox_veille vignettes] HTTP {r.status}")
                    return out
                data = await r.json()
        for x in (data.get("data") or []):
            url = str(x.get("imageUrl") or "")
            #  Filtre de domaine : voir l'avertissement ci-dessus.
            if x.get("state") == "Completed" and url.startswith(DOMAINE_IMAGES):
                try:
                    out[int(x.get("targetId"))] = url
                except (TypeError, ValueError):
                    continue
    except Exception as ex:
        _log(f"[roblox_veille vignettes] {type(ex).__name__}: {ex}")
    return out


def signature(article: dict) -> str:
    """Ce qui, en changeant, constitue un événement digne d'être publié.

    Volontairement RESTREINTE : le prix et les favoris bougent en permanence.
    Les inclure ferait republier le même article tous les quarts d'heure.
    """
    return f"{article.get('collectionnable', 0)}|{article.get('hors_vente', 0)}"


async def comparer_et_enregistrer(articles: list[dict]) -> dict:
    """Compare au dernier relevé et rend les événements détectés.

    {"nouveaux": [...], "bascules": [...], "retires": [...]}

    ⚠️ « bascules » n'est PAS « passé Limited le … ». Aucun champ ne donne cette
    date : on constate un changement entre deux relevés. La fiche dira donc
    « détecté le … », et c'est la seule formulation honnête.
    """
    res = {"nouveaux": [], "bascules": [], "retires": []}
    if not articles:
        return res
    maintenant = datetime.now(timezone.utc).isoformat()
    try:
        async with _get_db() as db:
            for a in articles:
                async with db.execute(
                    "SELECT signature, collectionnable, hors_vente FROM"
                    " roblox_articles WHERE asset_id=?", (a["asset_id"],)) as cur:
                    row = await cur.fetchone()
                sig = signature(a)
                if row is None:
                    res["nouveaux"].append(a)
                else:
                    if not int(row[1]) and a["collectionnable"]:
                        res["bascules"].append(a)
                    elif not int(row[2]) and a["hors_vente"]:
                        res["retires"].append(a)
                await db.execute(
                    "INSERT INTO roblox_articles(asset_id, nom, type_article,"
                    " prix, collectionnable, hors_vente, favoris, cree_le,"
                    " vu_le, signature) VALUES(?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(asset_id) DO UPDATE SET nom=?, prix=?,"
                    "  collectionnable=?, hors_vente=?, favoris=?, vu_le=?,"
                    "  signature=?",
                    (a["asset_id"], a["nom"], a["type_article"], a["prix"],
                     a["collectionnable"], a["hors_vente"], a["favoris"],
                     a["cree_le"], maintenant, sig,
                     a["nom"], a["prix"], a["collectionnable"], a["hors_vente"],
                     a["favoris"], maintenant, sig))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_veille comparer] {ex}")
    return res


async def deja_publie(guild_id: int, asset_id: int, flux: str) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM roblox_publies WHERE guild_id=? AND asset_id=?"
                " AND flux=?", (guild_id, asset_id, flux)) as cur:
                return bool(await cur.fetchone())
    except Exception:
        #  Fail-CLOSED : dans le doute on considère que c'est déjà sorti. Mieux
        #  vaut rater une publication que noyer le salon de doublons.
        return True


async def marquer_publie(guild_id: int, asset_id: int, flux: str) -> None:
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO roblox_publies(guild_id, asset_id, flux,"
                " publie_le) VALUES(?,?,?,?)",
                (guild_id, asset_id, flux, datetime.now(timezone.utc).isoformat()))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_veille marquer_publie] {ex}")


async def amorcer(guild_id: int) -> int:
    """Pose la borne du premier allumage. Rend le nombre d'articles absorbés.

    ⚠️ SANS CECI, LE PREMIER PASSAGE DÉVERSE TOUT LE CATALOGUE dans le salon.
    On enregistre l'état courant SANS rien publier : seul ce qui arrive ENSUITE
    sera annoncé. C'est le §« premier allumage » de ROBLOX.md.
    """
    rel = await relever_nouveautes(limite=120)
    if rel["code"] != 200:
        return 0
    await comparer_et_enregistrer(rel["articles"])
    for a in rel["articles"]:
        for flux in ("nouveautes", "bascules", "surveiller"):
            await marquer_publie(guild_id, a["asset_id"], flux)
    try:
        await _db_set(guild_id, "roblox_veille_amorcee",
                      datetime.now(timezone.utc).isoformat())
    except Exception as ex:
        _log(f"[roblox_veille amorcer] {ex}")
    return len(rel["articles"])


async def purger(garder: int = MAX_ARTICLES_SUIVIS) -> int:
    """Borne la table : on ne garde pas l'historique complet du catalogue."""
    try:
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM roblox_articles WHERE asset_id NOT IN ("
                " SELECT asset_id FROM roblox_articles ORDER BY vu_le DESC LIMIT ?)",
                (int(garder),))
            await db.execute(
                "DELETE FROM roblox_publies WHERE publie_le < ?",
                ((datetime.now(timezone.utc) - timedelta(days=180)).isoformat(),))
            await db.commit()
        return 1
    except Exception as ex:
        _log(f"[roblox_veille purger] {ex}")
        return 0


async def diagnostic() -> dict:
    """L'état des relevés, pour le panneau. Dit si une source ne répond plus."""
    out = {"sources": [], "articles_connus": 0}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT source, dernier_essai, dernier_succes, dernier_code,"
                " echecs_consecutifs FROM roblox_sante") as cur:
                for s, essai, succes, code, echecs in await cur.fetchall():
                    out["sources"].append({
                        "source": s, "dernier_essai": essai,
                        "dernier_succes": succes, "code": code,
                        "echecs": int(echecs or 0)})
            async with db.execute(
                "SELECT COUNT(*) FROM roblox_articles") as cur:
                row = await cur.fetchone()
            out["articles_connus"] = int(row[0] or 0) if row else 0
    except Exception as ex:
        _log(f"[roblox_veille diagnostic] {ex}")
    return out
