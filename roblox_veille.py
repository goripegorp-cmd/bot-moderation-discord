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

import asyncio
import json
from datetime import datetime, timedelta, timezone

#  ⚠️ DOMAINES EN DUR. Une URL n'est JAMAIS recopiée depuis une réponse d'API :
#  elle est reconstruite à partir de ces constantes et d'un identifiant validé
#  comme entier. C'est l'exigence « liens certifiés » de ROBLOX.md, et c'est une
#  règle de sécurité : ce bot lutte contre le phishing, il ne peut pas publier
#  un lien approximatif.
DOMAINE_ARTICLE = "https://www.roblox.com/catalog/"
#  Les Bundles ont leur PROPRE chemin — mesure : /catalog/ leur rend un 404.
DOMAINE_BUNDLE = "https://www.roblox.com/bundles/"
API_CATALOGUE = "https://catalog.roblox.com/v2/search/items/details"
API_ECONOMIE = "https://economy.roblox.com/v2/assets/{}/details"
API_FICHE = "https://catalog.roblox.com/v1/catalog/items/{}/details"
API_VIGNETTE = "https://thumbnails.roblox.com/v1/assets"
#  ⚠️ Les BUNDLES ont leur propre point de vignette. `/v1/assets` leur répond
#  HTTP 200 avec `state: "Error"` — un échec déguisé en succès. Mesuré le 16/08.
API_VIGNETTE_BUNDLE = "https://thumbnails.roblox.com/v1/bundles/thumbnails"
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

#  ⚠️ « À PARTIR DE MAINTENANT » — LA RÈGLE DU 18/08, ET COMMENT ELLE SE CODE.
#  Le propriétaire : « tu dis bien qu'il VIENT de passer Limited, pas il y a un
#  jour, deux jours. Pareil pour les nouveaux accessoires : que ceux créés à
#  partir de maintenant. »
#  Deux garanties, une seule fenêtre :
#    · une bascule n'est « vient de passer » que si on avait VU l'article non
#      collectionnable il y a moins de FENETRE_DIRECTE_HEURES. Sinon — bot
#      redémarré, base ancienne, premier passage après déploiement — la
#      bascule a pu se produire il y a des jours : on l'ENREGISTRE (la base se
#      met à jour) et on ne la publie PAS ;
#    · une nouveauté n'est publiée que si Roblox l'a CRÉÉE il y a moins de
#      FENETRE_DIRECTE_HEURES. Les 850 articles que la pagination a découverts
#      d'un coup ne sont pas « nouveaux » : ils sont absorbés.
#  Six heures : la boucle passe toutes les 30 min, un redémarrage Railway en
#  prend quelques-unes ; au-delà, on ne peut plus dire « vient de ».
FENETRE_DIRECTE_HEURES = 6


def _heures_depuis(quand) -> float | None:
    """Heures écoulées depuis un instant ISO. `None` si illisible."""
    try:
        d = datetime.fromisoformat(str(quand).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - d).total_seconds() / 3600)
    except Exception:
        return None

#  ⚠️ FENÊTRE DU FLUX « BASCULES », ET D'OÙ VIENT CE CHIFFRE.
#  Demande du propriétaire : « uniquement les items RÉCEMMENT devenus limited,
#  pas des items qui datent d'il y a des années ».
#  Roblox crée ses Limiteds modernes DÉJÀ collectionnables (écart création →
#  modification mesuré : 0 à 9 jours), donc leur date de création vaut date de
#  bascule. Relevé réel du 16/08 : le plus récent avait 152 jours, le plus
#  ancien du flux 411 jours, et l'historique Valkyrie Helm remonte à 2008.
#  400 jours laissent passer toute la vague récente (2025-2026) et coupent net
#  les historiques. Ne pas descendre sous ~180 : le flux se viderait, Roblox
#  ne sortant que quelques Limiteds par an.
FRAICHEUR_BASCULE_JOURS = 400

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

#  ⚠️ LA PAGINATION — SANS ELLE, LE BOT NE VOYAIT QUE 6 % DU CATALOGUE.
#  Le relevé s'arrêtait à une seule requête de 60 articles. Mesuré le 16/08 :
#  le catalogue complet des accessoires créés par Roblox fait **964 articles,
#  en 9 pages de 120**. Le bot en voyait donc 60 sur 964.
#  12 pages laissent de la marge si Roblox en publie davantage, sans ouvrir la
#  porte à une boucle infinie si l'API rendait un curseur qui ne s'épuise pas.
#  ⚠️ Le débit est RÉEL : un HTTP 429 est tombé à la 13ᵉ requête pendant la
#  mesure. `PAUSE_ENTRE_APPELS` sépare chaque page, et un 429 en cours de
#  route conserve les pages déjà obtenues au lieu de tout jeter.
MAX_PAGES_PAR_RELEVE = 12

#  ⚠️ LA PAUSE ENTRE LES DEUX RELEVÉS, ET POURQUOI ELLE EST SI LONGUE.
#  Le catalogue complet fait 9 pages, le flux des Limiteds 7 : enchaînés avec
#  seulement 2 s d'écart, cela fait 16 requêtes en une demi-minute et l'API
#  répond HTTP 429 — mesuré le 16/08, le second relevé s'arrêtait à la page 7.
#  15 secondes laissent la fenêtre de débit se vider. La boucle tourne toutes
#  les 30 minutes : ce délai ne coûte rien, et il évite un relevé tronqué.
PAUSE_ENTRE_RELEVES = 15.0

#  ⚠️ LE PIÈGE LE PLUS COÛTEUX DE CE MODULE, TROUVÉ LE 16/08 EN VÉRIFIANT.
#  Les deux relevés paginés consomment ~18 requêtes. Les appels QUI SUIVENT —
#  stock, prix de revente, vignettes — tombaient donc en plein HTTP 429, et
#  `enrichir`/`vignettes` échouent SANS BRUIT : les fiches partaient sans
#  chiffres et sans image, et rien ne le disait.
#  Mesuré : à froid, 3 articles sur 3 enrichis ; juste après deux relevés
#  complets, 0 sur 3.
#  Deux réponses, et il faut les deux : une pause avant la phase « fiches »,
#  et une reprise sur 429 (`_appel_avec_reprise`).
#  ⚠️ 60 SECONDES, ET PAS MOINS — LA FENÊTRE EST GLISSANTE.
#  Le débit mesuré est de ~12 requêtes par 60 secondes. Les deux relevés
#  paginés en consomment bien plus : attendre 20 s ne vidait qu'un tiers de la
#  fenêtre, et les appels suivants tombaient encore en 429 (essayé, mesuré,
#  0 article enrichi sur 3). Une minute pleine garantit une fenêtre vide.
#  La boucle tourne toutes les 30 minutes : cette minute ne coûte rien, et
#  c'est elle qui fait la différence entre une fiche complète et une fiche
#  muette.
PAUSE_AVANT_FICHES = 60.0

#  Attente après un 429 avant de retenter. Une seule reprise : si la fenêtre
#  est encore fermée après ça, insister ne ferait qu'aggraver le blocage.
ATTENTE_APRES_429 = 25.0

#  ⚠️ PLAFOND DUR DE PUBLICATIONS PAR PASSAGE — NE PAS LE RELEVER.
#
#  Sans lui, un cas parfaitement banal noie le salon : une base restauree, un
#  serveur qui active le systeme sans amorce, un flux qui rattrape plusieurs
#  jours d'un coup. Le classement peut alors presenter des centaines d'articles
#  d'un seul tenant.
#
#  Discord limite un webhook a environ 30 messages par minute, et un salon a 5
#  messages par 5 secondes. Depasser, c'est se faire etrangler : les envois
#  suivants echouent en cascade, et on ne sait plus ce qui est sorti.
#
#  Douze par passage, toutes les 30 minutes, c'est 576 par jour au maximum —
#  tres au-dessus du rythme reel de Roblox (36 bascules sur toute l'annee 2025).
#  Le reste n'est pas perdu : il sort au passage suivant. Un flux qui s'ecoule
#  vaut mieux qu'un salon qui explose.
MAX_PUBLICATIONS_PAR_PASSAGE = 12

#  Deux secondes entre deux envois : 12 messages prennent 24 s, tres en dessous
#  des limites de Discord. Une seconde suffisait en theorie ; deux laissent de
#  la marge quand plusieurs guildes publient dans le meme passage.
PAUSE_ENTRE_PUBLICATIONS = 2.0

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


def lien_article(asset_id, item_type: str | None = None) -> str | None:
    """L'URL d'un article, RECONSTRUITE. Jamais recopiée d'une réponse.

    ⚠️ EXIGENCE DE SÉCURITÉ, voir ROBLOX.md §1. Le domaine est une constante du
    module ; l'identifiant est validé comme entier. Sans entier lisible, on rend
    None et la fiche part SANS lien — jamais avec un lien approximatif.

    ⚠️ DEUX CHEMINS, ET C'EST MESURÉ. Un « Bundle » n'habite PAS sous /catalog/ :
    testé en direct sur le FIFA Football Animation Pack (id 5626295) —
        /catalog/5626295/  → HTTP 404
        /bundles/5626295/  → HTTP 302 (redirection vers la vraie page)
    Or le relevé complet compte 410 Bundles sur 964 articles créés par Roblox.
    La première version envoyait tout sur /catalog/ : environ QUATRE LIENS SUR
    DIX menaient à une page d'erreur, sur un bot dont la règle affichée est que
    l'on clique « sans se poser de questions ».

    Type inconnu → on retombe sur /catalog/, qui couvre la majorité, plutôt que
    de supprimer le lien : un lien juste six fois sur dix vaut mieux qu'aucun.
    """
    try:
        n = int(asset_id)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    base = DOMAINE_BUNDLE if str(item_type or "").lower() == "bundle" \
        else DOMAINE_ARTICLE
    return f"{base}{n}/"


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
    "multiplicateur": 15,   # revente / prix d'origine — bonus SI ≥2, MALUS si <1
    "prix_bas": 10,         # un prix d'entrée bas élargit le nombre de détenteurs
    "recent": 10,           # une sortie récente reste dans l'actualité
}

#  ⚠️ CE QUE CET INDICE N'EST PAS, ET NE SERA PAS.
#  Le propriétaire a demandé le 16/08 « savoir si un item deviendra limited, et
#  être sûr de toi ». La réponse honnête est : c'est impossible, et le dépôt le
#  documente depuis le 12/08 — mesuré sur 964 articles, `offSaleDeadline` était
#  renseigné 0 fois et `itemStatus` vide 962 fois. La sonde du 16/08 a rouvert
#  tous les points d'API accessibles (catalogue, économie, reventes,
#  revendeurs) : aucun ne porte d'annonce de passage en collectionnable.
#  Roblox ne publie pas cette information AVANT de la faire.
#
#  Ce que ces poids produisent est donc un INDICE DE FAITS OBSERVÉS — retiré de
#  la vente, stock fini, revente ouverte, multiplicateur constaté — jamais une
#  prédiction. Il se tait sous 60/100 parce qu'en dessous il n'y a pas de
#  signal, et non un signal faible. Aucun modèle entraîné (CGU Roblox), et
#  Rolimons reste interdit (ses CGU proscrivent l'accès automatisé).


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
    #  `revente` vient de `enrichir()` (economy), `revendeurs` du catalogue :
    #  l'un ou l'autre suffit, et le premier est le plus fiable.
    if (article.get("revente") or article.get("prix_revente")
            or article.get("revendeurs")):
        note += POIDS["revente"]
        prix_rev = article.get("revente") or article.get("prix_revente")
        facteurs.append((f"revente ouverte ({prix_rev} R$)" if prix_rev
                         else "revente déjà ouverte", POIDS["revente"]))

    #  Un stock fini est le propre d'un collectionnable. `totalQuantity` vaut 0
    #  sur un article à stock illimité : seul un nombre > 0 est un signal.
    #  `stock` vient d'`enrichir()`, `quantite` du catalogue.
    q = article.get("stock") or article.get("quantite")
    if q and int(q) > 0:
        note += POIDS["stock_fini"]
        facteurs.append((f"stock fini ({int(q):,}".replace(",", " ") + ")",
                         POIDS["stock_fini"]))

    #  ⚠️ LE MULTIPLICATEUR EST UN FAIT, PAS UNE PROMESSE.
    #  Mesuré le 16/08 : The Requiem ×4,5 · Bandana From Beyond ×1,0 ·
    #  Specter Time Fedora ×0,6 — ce dernier fait PERDRE de l'argent à qui l'a
    #  payé plein tarif. C'est précisément pour ne pas se faire avoir que le
    #  chiffre est affiché tel quel, y compris quand il est mauvais.
    mult = article.get("multiplicateur")
    if mult is not None:
        if mult >= 2:
            note += POIDS["multiplicateur"]
            facteurs.append((f"revente à ×{mult} du prix d'origine",
                             POIDS["multiplicateur"]))
        elif mult < 1:
            #  Un malus, et il est dit : une revente SOUS le prix d'origine est
            #  un signal négatif franc, pas une absence de signal.
            note -= POIDS["multiplicateur"]
            facteurs.append((f"⚠️ revente SOUS le prix d'origine (×{mult})",
                             -POIDS["multiplicateur"]))

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


def age_publiable(article: dict, flux: str = "surveiller") -> bool:
    """L'article a-t-il le bon âge pour être annoncé ? DÉPEND DU FLUX.

    ⚠️ DEUX RÈGLES DIFFÉRENTES, ET C'EST LE PROPRIÉTAIRE QUI A TRANCHÉ (15/08) :
    « les nouveaux accessoires sous la nouvelle création de Roblox, faut que tu
    le mettes SANS PITIÉ, sans chance, rien. Tu mets tout ce que Roblox crée. »

    · flux « nouveautes » — AUCUN âge minimum. Une nouveauté est une nouveauté
      le jour même ; la faire mûrir dix jours la transforme en vieille nouvelle.
      Seule la borne haute s'applique, pour ne pas déverser d'archives.
      C'est ce minimum, appliqué à tort ici, qui faisait afficher « 30 articles
      lus, 0 fiche publiée » alors que le catalogue en contenait des dizaines.

    · flux « surveiller » — le minimum GARDE tout son sens. Un article qui vient
      de sortir n'a ni revente, ni demande installée, ni recul sur son stock :
      il n'y a rien à surveiller, et l'indice serait du bruit.

    · flux « bascules » — UNIQUEMENT ce qui DEVIENT collectionnable sous nos
      yeux. Tranché par le propriétaire le 18/08, et c'est un revirement
      assumé par rapport au 16/08 :
        « uniquement les accessoires qui deviennent limited ou limited U, pas
         ceux qui le sont déjà devenus »
      Un article est publié ici si, et seulement si, il était connu NON
      collectionnable et l'est devenu entre deux relevés — `bascule_detectee`,
      posé par `comparer_et_enregistrer`. Un Limited vu pour la première fois
      déjà collectionnable n'est PAS une bascule : il est enregistré, jamais
      publié. Quel que soit son âge.

      ⚠️ Le relevé `relever_collectionnables` reste INDISPENSABLE, mais son
      rôle change : il n'alimente plus la publication, il alimente la
      DÉTECTION. 183 Limiteds sont absents du catalogue général (mesuré) : sans
      ce second relevé, leur passage en collectionnable ne serait jamais vu.

      La fenêtre `FRAICHEUR_BASCULE_JOURS` ne sert plus qu'à l'arrêt anticipé
      de la pagination de ce relevé (voir `_relever_catalogue`) — pas à la
      publication.
    """
    if flux == "bascules":
        #  Seule une bascule OBSERVÉE entre deux relevés sort. Le reste est
        #  « déjà devenu », donc hors périmètre.
        return bool(article.get("bascule_detectee"))
    if flux == "nouveautes":
        #  ⚠️ « CRÉÉS À PARTIR DE MAINTENANT » (18/08). Une nouveauté n'est
        #  publiée que si Roblox l'a créée il y a moins de
        #  FENETRE_DIRECTE_HEURES. Les 850 articles que la pagination découvre
        #  d'un coup — créés il y a des semaines — sont ENREGISTRÉS, pas
        #  publiés. Date illisible = on ne peut pas prouver « récent » = on
        #  se tait (fail-closed, à l'inverse de la règle du 15/08 : la
        #  consigne a changé, la garde suit).
        h = _heures_depuis(article.get("cree_le"))
        return h is not None and h <= FENETRE_DIRECTE_HEURES
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

    ⚠️ CE RELEVÉ NE VOIT QUE LES CRÉATIONS RÉCENTES — voir
    `relever_collectionnables` pour les Limiteds, qu'il ne peut PAS attraper.
    """
    return await _relever_catalogue({
        "Category": 1,
        "SortType": 3,
        "Limit": _limite_valide(limite),
        "CreatorType": "User",
        "CreatorTargetId": CREATEUR_ROBLOX,
    }, "catalogue")


async def relever_collectionnables(limite: int = 30) -> dict:
    """Les articles COLLECTIONNABLES de Roblox — le flux que le bot ne voyait pas.

    ⚠️ POURQUOI CETTE FONCTION EXISTE, ET CE QU'ELLE RÉPARE.
    Le propriétaire a signalé le 16/08 que des accessoires passés Limited ne
    sortaient jamais. La cause était structurelle : `relever_nouveautes` trie
    par date de CRÉATION (`SortType=3`) et rend les N derniers articles créés
    par Roblox. Or `comparer_et_enregistrer` ne peut détecter une bascule que
    pour un article PRÉSENT dans le relevé. Un accessoire créé il y a six mois
    qui passe Limited aujourd'hui n'est pas dans « les 60 derniers créés » : il
    n'est jamais relevé, donc sa bascule n'est jamais vue.

    MESURÉ, PAS SUPPOSÉ (sonde du 16/08, `outils/sonde_limiteds.py`) :
      · les 10 articles les plus récemment créés par Roblox → **0 Limited** ;
      · les 10 mêmes avec `SalesTypeFilter=2`               → **10 Limited**,
        dont aucun n'apparaissait dans le premier relevé.

    Le paramètre `SalesTypeFilter=2` est donc le seul moyen de les atteindre.
    `SalesTypeFilter=3` a été essayé : il ne filtre RIEN (résultats identiques
    au relevé de référence) — ne pas le réintroduire en croyant mieux faire.

    ⚠️ Garder `CreatorTargetId=1` : sans lui, le flux se remplit d'UGC de
    créateurs tiers, hors du périmètre demandé (« uniquement ceux qui sont
    créés par Roblox »).

    ⚠️ DEPUIS LE 18/08 : DEUX PAGES, PAS PLUS. Ce flux ne publie plus rien
    par lui-même (seules les bascules vues en direct sortent), il ne sert qu'à
    DÉTECTER. Or il n'est PAS trié par date — mesuré ce jour-là : la page 1
    va de 154 à 6 955 jours d'âge — donc aucun arrêt anticipé « par date »
    n'est possible, et le paginer en entier coûtait 8 requêtes par passage,
    celles qui faisaient tomber en 429 les appels de fiche. Presque toutes les
    bascules qui nous intéressent sont visibles dans le catalogue GÉNÉRAL (les
    964 plus récents, où l'article a déjà sa ligne « non collectionnable ») ;
    ces deux pages attrapent le reste au meilleur coût. Un article de plus de
    deux ans qui repasserait Limited peut nous échapper — cas rare, assumé.
    """
    return await _relever_catalogue({
        "Category": 1,
        "SortType": 3,
        "Limit": _limite_valide(limite),
        "SalesTypeFilter": 2,          # 2 = Limited. Mesuré le 16/08.
        "CreatorType": "User",
        "CreatorTargetId": CREATEUR_ROBLOX,
    }, "collectionnables", max_pages=MAX_PAGES_COLLECTIONNABLES)


#  Voir la docstring de `relever_collectionnables` : ce flux n'est pas trié par
#  date, il ne sert qu'à détecter, deux pages suffisent.
MAX_PAGES_COLLECTIONNABLES = 2


async def _relever_catalogue(params: dict, source: str,
                             max_pages: int | None = None) -> dict:
    """L'appel au catalogue, partagé par les deux relevés.

    `source` sert au suivi de santé : un flux muet doit se voir SÉPARÉMENT.
    Si les collectionnables tombent en panne pendant que les nouveautés
    marchent, un compteur commun le masquerait — et un flux mort ressemble
    exactement à un flux calme.
    """
    out = {"articles": [], "code": None, "echecs": 0, "pages": 0,
           "complet": False}
    vus: set[int] = set()
    curseur = None
    try:
        async with _ouvrir() as sess:
            for page in range(MAX_PAGES_PAR_RELEVE):
                p = dict(params)
                if curseur:
                    p["Cursor"] = curseur
                async with sess.get(API_CATALOGUE, params=p) as r:
                    out["code"] = r.status
                    if r.status != 200:
                        #  On garde le corps : un 403 du pare-feu et un 429 de
                        #  débit ne se corrigent pas de la même façon, et sans
                        #  cette trace on ne saurait pas lequel on a.
                        _log(f"[roblox_veille {source}] HTTP {r.status} à la "
                             f"page {page + 1} — {(await r.text())[:200]}")
                        #  ⚠️ UN 429 N'EST PAS UNE PANNE : c'est notre propre
                        #  débit. On garde les pages déjà obtenues et on
                        #  reprendra au prochain passage. Les jeter ferait
                        #  perdre un relevé presque complet pour rien.
                        if r.status == 429 and out["articles"]:
                            out["code"] = 200
                        break
                    data = await r.json()

                lot = _normaliser(data.get("data") or [])
                if not lot:
                    out["complet"] = True
                    break
                for a in lot:
                    #  Dédoublonnage : l'API renvoie parfois deux fois le même
                    #  article à cheval sur deux pages (son tri n'est pas
                    #  strictement chronologique — voir `_normaliser`).
                    if a["asset_id"] not in vus:
                        vus.add(a["asset_id"])
                        out["articles"].append(a)
                out["pages"] = page + 1

                #  ⚠️ IL N'Y A PLUS D'ARRÊT ANTICIPÉ « PAR DATE » — la prémisse
                #  était fausse. Une première version s'arrêtait dès qu'une page
                #  entière du flux Limited dépassait la fenêtre de fraîcheur, en
                #  supposant ce flux trié par date de création. Mesuré le 18/08 :
                #  la page 1 va de 154 à 6 955 jours d'âge — l'arrêt ne se
                #  déclenchait JAMAIS, et le flux paginait ses 8 pages à chaque
                #  passage, exactement ce qui faisait tomber en 429 les appels de
                #  fiche (stock, revente, vignettes). Le plafond est désormais un
                #  NOMBRE DE PAGES par relevé (`max_pages`), qui ne dépend
                #  d'aucun tri.
                if max_pages is not None and page + 1 >= max_pages:
                    out["complet"] = not data.get("nextPageCursor")
                    break

                curseur = data.get("nextPageCursor")
                if not curseur:
                    out["complet"] = True
                    break
                await asyncio.sleep(PAUSE_ENTRE_APPELS)
    except Exception as ex:
        _log(f"[roblox_veille {source}] {type(ex).__name__}: {ex}")
    out["echecs"] = await _noter_sante(source, out["code"])
    return out


#  Le point de détails PAR IDENTIFIANT — le seul qui rende le nom français d'un
#  article quel que soit son âge, Assets et Bundles confondus.
API_DETAILS = "https://catalog.roblox.com/v1/catalog/items/details"
#  Jeton XSRF du point ci-dessus. Obtenu par un premier POST (403 attendu),
#  gardé, rafraîchi sur 403. Jamais une authentification : c'est public.
_jeton_xsrf: str | None = None


async def _details_fr(sess, articles: list[dict]) -> dict:
    """{(itemType, id): {"name", "description"}} en français, ou {} si rien.

    Ne lève pas. Journalise chaque non-200 : un nom français qui disparaît
    en silence est exactement le défaut qu'on répare.
    """
    global _jeton_xsrf
    items = []
    for a in articles:
        try:
            genre = "Bundle" if str(a.get("item_type") or "").lower() == "bundle" else "Asset"
            items.append({"itemType": genre, "id": int(a["asset_id"])})
        except (TypeError, ValueError, KeyError):
            continue
    if not items:
        return {}
    corps = {"items": items[:120]}
    for tentative in (1, 2):
        entetes = {"Accept-Language": LANGUE_FR}
        if _jeton_xsrf:
            entetes["X-CSRF-TOKEN"] = _jeton_xsrf
        try:
            async with sess.post(API_DETAILS, json=corps, headers=entetes) as r:
                if r.status == 403 and tentative == 1:
                    #  La danse XSRF : le 403 PORTE le jeton. On le prend et
                    #  on rejoue une fois.
                    _jeton_xsrf = r.headers.get("x-csrf-token") or _jeton_xsrf
                    continue
                if r.status != 200:
                    _log(f"[roblox_veille traduire] HTTP {r.status} sur "
                         f"{API_DETAILS.rsplit('/', 1)[-1]} — fiches en anglais")
                    return {}
                data = await r.json()
        except Exception as ex:
            _log(f"[roblox_veille traduire] {type(ex).__name__}: {ex}")
            return {}
        out = {}
        for x in (data.get("data") or []):
            try:
                out[(str(x.get("itemType") or "Asset"), int(x.get("id")))] = {
                    "name": str(x.get("name") or ""),
                    "description": str(x.get("description") or "").strip()}
            except (TypeError, ValueError):
                continue
        return out
    return {}


async def traduire(articles: list[dict]) -> None:
    """Pose le nom et la description FRANÇAIS OFFICIELS de Roblox. Sur place.

    On ne traduit jamais nous-mêmes : on demande à Roblox avec l'en-tête de
    langue, et on cite. Sans traduction officielle, l'article garde son
    anglais. Un appel pour tout le lot, par identifiants — voir `_details_fr`.

    ⚠️ Deux défauts de la version précédente, corrigés le 18/08 :
      · elle cherchait dans « les N derniers créés » — un Limited ancien qui
        vient de basculer n'y était jamais, sa fiche partait en anglais ;
      · sur un non-200 elle rendait sans un mot, et le français disparaissait
        en silence.
    """
    if not articles:
        return
    try:
        async with _ouvrir() as sess:
            fr = await _details_fr(sess, articles)
        for a in articles:
            genre = "Bundle" if str(a.get("item_type") or "").lower() == "bundle" else "Asset"
            d = fr.get((genre, int(a["asset_id"])))
            if not d:
                continue
            #  On ne garde le français que s'il DIFFÈRE : beaucoup d'articles
            #  n'ont pas de traduction, et afficher deux fois la même ligne
            #  ferait croire à un défaut.
            if d["name"] and d["name"] != a.get("nom"):
                a["nom_fr"] = d["name"][:120]
            if d["description"] and d["description"] != (a.get("description") or ""):
                a["description_fr"] = d["description"][:400]
    except Exception as ex:
        _log(f"[roblox_veille traduire] {ex}")


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
                #  « Asset » ou « Bundle » : commande le CHEMIN du lien, pas
                #  l'affichage. Voir `lien_article`.
                "item_type": str(b.get("itemType") or ""),
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
                #  « Limited U » (LimitedUnique) se distingue de « Limited » :
                #  demande du 18/08 — les deux sortent, mais on dit lequel.
                "limited_u": int(any(
                    "unique" in str(x).lower() for x in restrictions)),
                #  La « légère description » demandée pour la fiche : celle de
                #  Roblox, jamais la nôtre. Bornée, elle se traduit avec le nom
                #  (voir `traduire`).
                "description": (str(b.get("description") or "").strip()[:400]
                                or None),
            })
        except Exception:
            continue
    out.sort(key=lambda a: str(a.get("cree_le") or ""), reverse=True)
    return out


async def _appel_avec_reprise(sess, url: str, params: dict | None = None):
    """Un GET qui ne se laisse pas tuer par notre propre débit.

    Rend `(code, données)` — `données` vaut `None` si la réponse n'est pas
    exploitable. Sur HTTP 429, attend puis retente UNE fois : c'est notre
    cadence qui est en cause, pas une panne, et la fenêtre se rouvre d'
    elle-même. Insister davantage ne ferait qu'allonger le blocage.

    ⚠️ Sans cette reprise, les appels de fin de passage (stock, revente,
    vignettes) échouaient en silence après les deux relevés paginés — mesuré
    le 16/08 : 0 article enrichi sur 3, alors que les mêmes appels rendaient
    3 sur 3 à froid.
    """
    for tentative in (1, 2):
        try:
            async with sess.get(url, params=params) as r:
                if r.status == 429 and tentative == 1:
                    _log(f"[roblox_veille] HTTP 429 sur {url.split('/')[-1]} — "
                         f"attente {ATTENTE_APRES_429:.0f} s puis reprise")
                    await asyncio.sleep(ATTENTE_APRES_429)
                    continue
                if r.status != 200:
                    return r.status, None
                return 200, await r.json()
        except Exception as ex:
            _log(f"[roblox_veille appel {url.split('/')[-1]}] "
                 f"{type(ex).__name__}: {ex}")
            return None, None
    return 429, None


async def enrichir(articles: list[dict]) -> None:
    """Complète les articles avec les chiffres d'ÉCONOMIE. Modifie sur place.

    ⚠️ UN APPEL PAR ARTICLE — donc réservé à ceux qu'on va VRAIMENT publier.
    Le catalogue donne le nom, le prix et les favoris ; il ne donne ni le stock
    émis, ni le prix de revente. Ces deux-là sont le cœur d'une décision de
    trading, et ils vivent sur `economy.roblox.com`.

    Ce que la sonde du 16/08 a établi sur ce point d'API :
      · `CollectiblesItemDetails.TotalQuantity`            → stock ÉMIS
      · `CollectiblesItemDetails.CollectibleLowestResalePrice` → revente la
        plus basse, c'est-à-dire le prix réel du marché secondaire
      · `PriceInRobux`                                     → prix d'origine
      · `IsForSale`                                        → encore en vente ?
    Le rapport revente / prix d'origine est le seul multiplicateur FACTUEL
    disponible. Mesuré : The Requiem ×4,5 · Bandana ×1,0 · Specter Time
    Fedora ×0,6 (donc une PERTE pour qui l'a acheté plein tarif).

    ⚠️ `economy.roblox.com/v1/assets/{id}/resale-data` n'a pas été retenu :
    HTTP 400 sur les articles récents (système « collectible » moderne), il ne
    répond que pour les Limiteds historiques. Le brancher donnerait un champ
    renseigné pour les vieux et vide pour les neufs — soit l'inverse de ce
    qu'on veut suivre. Et `/resellers` demande une authentification (401).

    Ne lève jamais, et laisse l'article intact en cas d'échec : une fiche sans
    chiffres de revente reste une fiche utile, une exception ferait taire tout
    le passage.
    """
    if not articles:
        return
    try:
        async with _ouvrir() as sess:
            for a in articles:
                #  ⚠️ LES BUNDLES N'ONT PAS DE FICHE ÉCONOMIE.
                #  `economy/v2/assets/{id}/details` leur rend HTTP 400 « No
                #  Product Info found », et `economy/v1/bundles/{id}/details`
                #  n'existe pas (404). Vérifié le 16/08 sur trois bundles du
                #  flux réel.
                #  Ce n'est pas grave : le catalogue porte DÉJÀ leur stock
                #  (`quantite`) et leur revente (`prix_revente`), et la fiche
                #  retombe dessus. Les appeler pour rien coûterait une requête
                #  par bundle et brûlerait le débit des articles qui, eux, ont
                #  une fiche.
                if str(a.get("item_type") or "").lower() == "bundle":
                    continue
                code, d = await _appel_avec_reprise(
                    sess, API_ECONOMIE.format(int(a["asset_id"])))
                #  La pause va DANS la boucle : c'est la concurrence que le
                #  pare-feu punit, pas le volume.
                await asyncio.sleep(PAUSE_ENTRE_APPELS)
                if not d:
                    _log(f"[roblox_veille enrichir {a.get('asset_id')}] "
                         f"HTTP {code} — fiche publiée sans ses chiffres")
                    continue

                det = d.get("CollectiblesItemDetails") or {}
                a["stock"] = det.get("TotalQuantity") or None
                a["revente"] = det.get("CollectibleLowestResalePrice") or None
                a["en_vente"] = bool(d.get("IsForSale"))
                prix_origine = d.get("PriceInRobux")
                if prix_origine is not None:
                    a["prix"] = prix_origine
                #  Le multiplicateur ne se calcule que s'il veut dire quelque
                #  chose : un prix d'origine nul (article offert) rendrait une
                #  division par zéro, et « ×∞ » n'informe personne.
                try:
                    if a["revente"] and prix_origine and int(prix_origine) > 0:
                        a["multiplicateur"] = round(
                            float(a["revente"]) / float(prix_origine), 2)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
    except Exception as ex:
        _log(f"[roblox_veille enrichir] {ex}")


def ordonner_publication(articles: list[dict], tranche: int) -> list[dict]:
    """Choisit les `tranche` plus RÉCENTS, puis les rend du plus ANCIEN au plus récent.

    ⚠️ DEUX TRIS OPPOSÉS, ET LES CONFONDRE CASSE L'UN OU L'AUTRE.
    Demande du propriétaire (16/08) : « mets le plus ancien posté en premier
    jusqu'au plus récent, comme ça quand on scroll on voit pas un vieil item
    avec un nouveau ».

    Discord empile les messages du plus ancien EN HAUT au plus récent EN BAS.
    Pour qu'un salon se lise de haut en bas dans l'ordre, il faut donc ENVOYER
    le plus ancien d'abord. Or le relevé, lui, doit rester trié du plus récent
    au plus ancien : c'est ce tri-là qui décide QUELS articles entrent dans la
    tranche. Prendre les 30 premiers d'une liste croissante donnerait les 30
    plus VIEUX du catalogue — l'exact contraire de ce qu'on veut suivre.

    D'où l'ordre des opérations, qui n'est pas interchangeable :
      1. sélectionner sur la liste DÉCROISSANTE (les plus récents) ;
      2. inverser la tranche retenue pour l'envoi.

    Une date illisible ne fait pas tomber l'article : il part en tête, avec les
    plus anciens. Le taire pour un champ manquant serait pire qu'un ordre
    approximatif sur une seule fiche.
    """
    if not articles:
        return []
    #  Le relevé arrive déjà décroissant (`_normaliser`), mais on ne s'appuie
    #  pas dessus : cette fonction est appelée sur des listes FUSIONNÉES
    #  (nouveautés + collectionnables), dont l'ordre n'est plus garanti.
    recents = sorted(articles, key=lambda a: str(a.get("cree_le") or ""),
                     reverse=True)[:max(0, int(tranche))]
    return list(reversed(recents))


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


async def vignettes(articles_ou_ids: list) -> dict:
    """Les images des articles, par lot. {asset_id: url} — vide si rien.

    Accepte une liste d'articles (dictionnaires) ou d'identifiants nus.

    ⚠️ DEUX POINTS D'API, PARCE QU'IL Y A DEUX SORTES D'ARTICLES.
    Défaut trouvé le 16/08 en vérifiant : les fiches sortaient sans image, et
    ce n'était PAS un problème de débit — c'est que la moitié du flux Limited
    de Roblox est faite de **Bundles** (les visages, les têtes dynamiques),
    pas d'Assets. Or `/v1/assets` leur répond HTTP 200 avec `state: "Error"`
    et une image vide : un échec qui se déguise en succès.
    Mesuré sur un lot réel : Snow Queen Smile, Bacon Face et Friendly Trusting
    Smile — trois Bundles, trois images manquantes, aucun message d'erreur.
    Le bon point est `/v1/bundles/thumbnails?bundleIds=…`, qui rend
    `state: "Completed"`.

    ⚠️ L'URL de l'image vient de Roblox et n'est PAS reconstructible : elle
    contient une empreinte. C'est la seule exception à la règle « on ne recopie
    jamais une URL » — elle est donc filtrée : on n'accepte que le domaine
    officiel des images. Un lien détourné afficherait une image arbitraire.

    Les points acceptent 100 identifiants au maximum (101 → HTTP 400).
    """
    out: dict[int, str] = {}
    if not articles_ou_ids:
        return out

    #  Séparer les deux familles. Sans `item_type` (identifiant nu), on tente
    #  la voie « asset » : c'est le cas majoritaire hors Limiteds.
    assets, bundles = [], []
    for x in articles_ou_ids:
        if isinstance(x, dict):
            aid, genre = x.get("asset_id"), str(x.get("item_type") or "")
        else:
            aid, genre = x, ""
        if not str(aid).lstrip("-").isdigit():
            continue
        (bundles if genre.lower() == "bundle" else assets).append(int(aid))

    async def _demander(sess, url, cle, ids):
        if not ids:
            return
        params = {cle: ",".join(str(i) for i in ids[:100]),
                  "size": "420x420", "format": "Png",
                  "returnPolicy": "PlaceHolder"}
        code, data = await _appel_avec_reprise(sess, url, params)
        if not data:
            _log(f"[roblox_veille vignettes {cle}] HTTP {code} — "
                 f"fiches publiées sans image")
            return
        for x in (data.get("data") or []):
            url_img = str(x.get("imageUrl") or "")
            #  ⚠️ `state` DOIT valoir « Completed ». Un « Error » vient avec
            #  une URL d'image de remplacement : la garder afficherait un
            #  visuel qui n'est pas l'article.
            if x.get("state") == "Completed" and url_img.startswith(DOMAINE_IMAGES):
                try:
                    out[int(x.get("targetId"))] = url_img
                except (TypeError, ValueError):
                    continue

    try:
        async with _ouvrir() as sess:
            await _demander(sess, API_VIGNETTE, "assetIds", assets)
            if assets and bundles:
                await asyncio.sleep(PAUSE_ENTRE_APPELS)
            await _demander(sess, API_VIGNETTE_BUNDLE, "bundleIds", bundles)
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
                    "SELECT signature, collectionnable, hors_vente, vu_le FROM"
                    " roblox_articles WHERE asset_id=?", (a["asset_id"],)) as cur:
                    row = await cur.fetchone()
                sig = signature(a)
                if row is None:
                    res["nouveaux"].append(a)
                else:
                    if not int(row[1]) and a["collectionnable"]:
                        #  ⚠️ « VIENT DE PASSER » — SEULEMENT SI ON L'A VU AVANT.
                        #  L'article était connu NON collectionnable et l'est
                        #  devenu. Mais depuis QUAND ? Si notre dernière
                        #  observation (`vu_le`) date de plus de
                        #  FENETRE_DIRECTE_HEURES — bot arrêté, premier passage
                        #  après déploiement — la bascule a pu avoir lieu il y a
                        #  deux jours, et « vient de passer » serait un
                        #  mensonge. Tranché le 18/08 : on met la base à jour,
                        #  on ne publie pas.
                        depuis = _heures_depuis(row[3])
                        if depuis is not None and depuis <= FENETRE_DIRECTE_HEURES:
                            a["bascule_detectee"] = True
                            res["bascules"].append(a)
                        else:
                            res.setdefault("bascules_anciennes", []).append(a)
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


#  ⚠️ LA SÉPARATION DES FLUX — demande du propriétaire le 16/08 :
#  « sépare bien les uns des autres ».
#  Un même article peut satisfaire plusieurs flux à la fois : un Limited retiré
#  de la vente coche « devenu collectionnable » ET « à surveiller ». Sans règle,
#  il sortait dans les deux salons — et si un seul salon est réglé, deux fois
#  dans le même, à la suite.
#
#  La priorité dit ce qu'un article est AVANT TOUT :
#    · il EST devenu collectionnable      → l'information la plus forte
#    · il POURRAIT le devenir             → une hypothèse, plus faible
#    · il vient d'être créé               → un fait neutre
#  Un article déjà sorti dans un flux ne ressort donc pas dans un flux de
#  priorité inférieure. L'inverse reste permis, et c'est voulu : une nouveauté
#  annoncée en janvier qui passe Limited en mars est une VRAIE nouvelle.
PRIORITE_FLUX = {"bascules": 3, "surveiller": 2, "nouveautes": 1}


async def flux_deja_sortis(guild_id: int, asset_id: int) -> set[str]:
    """Les flux dans lesquels cet article est déjà sorti sur ce serveur."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT flux FROM roblox_publies WHERE guild_id=? AND asset_id=?",
                (guild_id, asset_id)) as cur:
                return {str(r[0]) for r in await cur.fetchall()}
    except Exception as ex:
        _log(f"[roblox_veille flux_deja_sortis] {ex}")
        #  Fail-CLOSED comme `deja_publie` : dans le doute, on considère que
        #  tout est déjà sorti. Mieux vaut rater une publication que noyer le
        #  salon de doublons.
        return set(PRIORITE_FLUX)


async def publiable_dans(guild_id: int, asset_id: int, flux: str) -> bool:
    """Cet article a-t-il sa place dans CE flux, sur ce serveur ?

    Non s'il y est déjà sorti, et non s'il est déjà sorti dans un flux plus
    fort — voir `PRIORITE_FLUX`.
    """
    sortis = await flux_deja_sortis(guild_id, asset_id)
    if flux in sortis:
        return False
    mien = PRIORITE_FLUX.get(flux, 0)
    return not any(PRIORITE_FLUX.get(f, 0) > mien for f in sortis)


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

    #  ⚠️ ON N'ABSORBE QUE CE QUI N'ÉTAIT DE TOUTE FAÇON PAS PUBLIABLE.
    #
    #  La première version marquait TOUT le catalogue comme déjà sorti. Résultat
    #  mesuré chez le propriétaire : il allume, clique « Relever maintenant », et
    #  lit « 30 articles lus, 0 fiche publiée » — alors que 17 articles du relevé
    #  entraient parfaitement dans sa fenêtre d'âge. Il aurait fallu attendre que
    #  Roblox crée quelque chose de neuf, c'est-à-dire des semaines, pour voir
    #  une seule fiche. Le message « c'est normal, Roblox publie peu » était donc
    #  exact sur les faits et trompeur sur la cause.
    #
    #  L'amorce sert à ne pas déverser des ARCHIVES, pas à museler le système.
    #  On absorbe donc les articles hors fenêtre — trop vieux, ou trop jeunes
    #  pour avoir quoi que ce soit à raconter — et on laisse les autres sortir au
    #  premier passage, bornés par le plafond de publications.
    absorbes = 0
    for a in rel["articles"]:
        #  Le flux « nouveautes » est le plus permissif : si un article y a sa
        #  place, il ne doit surtout pas etre absorbe par l'amorce.
        if age_publiable(a, "nouveautes"):
            continue                      # celui-là a le droit de sortir
        for flux in ("nouveautes", "bascules", "surveiller"):
            await marquer_publie(guild_id, a["asset_id"], flux)
        absorbes += 1
    try:
        await _db_set(guild_id, "roblox_veille_amorcee",
                      datetime.now(timezone.utc).isoformat())
    except Exception as ex:
        _log(f"[roblox_veille amorcer] {ex}")
    #  On rend ce qui a ete ABSORBE, pas le total lu : c'est le chiffre qui a du
    #  sens pour le proprietaire — « voila ce que je ne te publierai pas ».
    return absorbes


async def oublier_publies(guild_id: int) -> int:
    """Efface les marques « déjà publié » d'une guilde. Rend le nombre effacé.

    ⚠️ POURQUOI CE BOUTON EXISTE. La première amorce marquait TOUT le catalogue
    comme déjà sorti à l'allumage. Le correctif a rendu l'amorce raisonnable —
    mais les marques posées AVANT sont toujours en base. Le système est propre,
    la base ne l'est pas : sur le serveur du propriétaire, 15 articles de moins
    de 30 jours restaient invisibles pour toujours.

    Un correctif de code ne répare pas des données déjà écrites. Il fallait donc
    un geste explicite, et il est réservé au propriétaire : effacer ces marques
    peut faire ressortir des articles déjà vus, ce qui est exactement ce qu'on
    veut ici mais qu'on ne doit jamais déclencher par accident.

    Le plafond de publications par passage limite la casse dans tous les cas :
    au pire, ça ressort par paquets de 12 toutes les 30 minutes.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM roblox_publies WHERE guild_id=?",
                (guild_id,)) as cur:
                row = await cur.fetchone()
            n = int(row[0] or 0) if row else 0
            await db.execute("DELETE FROM roblox_publies WHERE guild_id=?",
                             (guild_id,))
            await db.commit()
        return n
    except Exception as ex:
        _log(f"[roblox_veille oublier_publies] {ex}")
        return 0


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
