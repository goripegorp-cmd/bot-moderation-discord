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
LES DEUX PANNES DU 30/08/2026 — CAUSES DIFFÉRENTES, NE PAS LES CONFONDRE
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire : « les accessoires qui sont nouveaux et les accessoires qui
viennent de passer Limited ne marchent pas ». Deux symptômes, deux causes.

1. LES BASCULES NE SORTAIENT PAS — C'ÉTAIT UN VRAI DÉFAUT, ET IL ÉTAIT ICI.
   `amorcer()` marquait les TROIS flux « déjà publié » au premier allumage,
   `bascules` compris. Or elle n'épargne que les articles de moins de six
   heures, et Roblox n'avait rien créé depuis 38 jours : les 964 articles du
   catalogue étaient donc marqués, et `publiable_dans(..., "bascules")` les
   refusait TOUS pendant 180 jours (la purge de `roblox_publies`). La porte
   était condamnée avant que le premier Limited n'existe. Pire, la bascule
   était comptée `_sa["deja"]` — rangée sous « déjà publié », le libellé le
   plus trompeur possible.
   → `amorcer` ne marque plus que les flux d'ÉTAT ; `_migrer_amorce_bascules`
     efface les marques déjà écrites.

2. LES NOUVEAUTÉS — LA SOURCE EST MUETTE, ET CE N'EST PAS UNE PANNE.
   Mesuré ce jour-là sur les 964 articles du compte Roblox : le plus récent
   avait **38,3 jours**. Sous la fenêtre de six heures : 0 sur 964. Sous
   30 JOURS : encore 0 sur 964. Sur un an, 14 journées de création seulement,
   soit ~1,2 occasion de publier par mois — et les fournées durent quelques
   minutes (les 12 articles du 22/07 sont tombés en 6,1 min).
   ⚠️ Un défaut RÉEL se cachait quand même derrière : la tranche
   `_TRANCHE_FLUX` coupait le lot AVANT publication alors que
   `comparer_et_enregistrer` venait d'écrire l'article en base — l'écarté
   n'était plus « jamais vu » et ne revenait JAMAIS. Rejoué : 20 nouveautés
   éligibles → 5 publiées, puis 0, puis 0. → file d'attente en base.

⚠️ TROIS FAUSSES PISTES, MESURÉES ET ÉCARTÉES — NE PAS LES REPRENDRE.
  · `Category` est un paramètre MORT sur `v2/search/items/details` : 1, 3, 11,
    13, absent et même 9999 rendent les MÊMES identifiants et le même curseur.
    Passer à `Category=11` ne change rien.
  · `SortType=3` reste le bon choix : aucune valeur ne trie strictement par
    date, mais c'est la seule qui met le plus récent en tête.
  · La pagination du catalogue va bien au bout : 964/964, curseur épuisé,
    0 doublon, 0 × 429.

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
import random
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
#
#  ⚠️ NE PAS ÉLARGIR CETTE FENÊTRE. Tentative du 19/08/2026 : la porter à 24 h
#  pour survivre à une panne de nuit. Refusée — le propriétaire avait déjà
#  tranché, mot pour mot : « pas qui est passé limited d'il y a un jour, 2
#  jours, à partir d'aujourd'hui […] faut vraiment que ça passe là bientôt ».
#  Vingt-quatre heures, c'est « il y a un jour ». `test_une_nouveaute_plus_
#  ancienne_est_absorbee_pas_publiee[24]` verrouille ce refus.
#
#  LE COMPROMIS ASSUMÉ, POUR QU'ON NE LE REDÉCOUVRE PAS : si la boucle reste
#  muette plus de six heures (redéploiement + tempête de 429), une fournée
#  d'accessoires tombée dans ce trou est perdue définitivement. C'est le prix
#  de la fraîcheur, et c'est le choix du propriétaire — pas un oubli.
#
#  Mesure du 19/08 (outils/sonde_pourquoi_zero.py) : sur les 964 accessoires
#  Roblox du catalogue, le PLUS RÉCENT avait 670 h — 28 jours. Les fournées
#  sont espacées de semaines. « 0 publication » côté accessoires est donc la
#  RÉPONSE NORMALE la plupart du temps, pas une panne.
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

#  ⚠️ LE CATALOGUE A SA PROPRE CADENCE, ET C'EST LE POINT DU CORRECTIF 20/08.
#  Une seule constante servait TROIS budgets différents : la pagination du
#  catalogue (12/60 s), `enrichir` sur economy.roblox.com (1000/60 s) et les
#  vignettes. Le seau est PAR CHEMIN — seul celui du catalogue est étroit.
#  Ralentir les trois aurait allongé un passage avec publications de plusieurs
#  minutes pour un budget consommé à 1,2 %.
#
#  POURQUOI 8 SECONDES, ET PAS 5 NI 6. Le nombre maximal de requêtes qu'une
#  cadence de `s` secondes peut placer dans une fenêtre de 60 s vaut
#  floor(60/s) + 1 :
#      s = 2 → 31    s = 5 → 13    s = 6 → 11    s = 7 → 9    s = 8 → 8
#  Les 9 pages du relevé tiennent dans UNE SEULE fenêtre tant que s < 7,5 :
#  passer à 5 ou 6 s ne retire donc pas une seule requête du pic. 8 s est le
#  premier seuil qui borne réellement à 8 requêtes par fenêtre, soit 8/12 du
#  budget, et laisse 4 places aux autres applications de l'IP Railway partagée.
#
#  ⚠️ EFFET DE BORD VOULU : ce plafond de 8 ne dépend PAS du nombre de pages.
#  Il désamorce donc la bombe à retardement de `MAX_PAGES_PAR_RELEVE` — à ~1320
#  accessoires le relevé aurait atteint 11 à 12 requêtes à lui seul et se
#  serait mis en 429 tout seul, en tronquant en silence.
PAUSE_ENTRE_APPELS_CATALOGUE = 8.0

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

#  ⚠️ LA PAUSE ENTRE LES DEUX RELEVÉS — C'EST ELLE QUI CAUSAIT LE 429.
#
#  ⚠️ LE RAISONNEMENT PRÉCÉDENT ÉTAIT ARITHMÉTIQUEMENT FAUX, ET IL A COÛTÉ
#  DEUX CORRECTIFS RATÉS. Il disait « 15 secondes laissent la fenêtre de débit
#  se vider », puis 30 s. Pour une fenêtre de 60 secondes, c'est faux par
#  construction : 30 s, c'est la MOITIÉ de la fenêtre. Les 9 pages du premier
#  relevé (t = 0 à 16 s) sont donc TOUJOURS comptées quand le second relevé
#  tire à t = 46 s et t = 48 s — pic de 10 puis 11 requêtes sur un budget de
#  12. C'est exactement la capture du propriétaire du 18/08 : « 429 sur le flux
#  Limited juste après les 9 pages du catalogue », symptôme qui a survécu au
#  passage de 15 à 30 s parce qu'on traitait la mauvaise cause.
#
#  Il faut P > 60 s pour que le second relevé démarre sur une fenêtre VIDE,
#  quelle que soit la cadence des pages. 65 s donne cinq secondes de marge sur
#  la dérive d'horloge. Coût : +35 s sur une boucle de 1800 s, soit 1,9 %.
#
#  ⚠️ LE SEUL PRIX RÉEL DE CE CORRECTIF n'est pas la durée : c'est que la
#  fenêtre pendant laquelle une bascule peut être perdue s'allonge (~95 s →
#  ~160 s). `comparer_et_enregistrer` valide le nouvel état AVANT publication ;
#  un arrêt entre les deux perd la bascule. Assumé : un arrêt pile dans cette
#  fenêtre est rare, un 429 à chaque passage était certain.
PAUSE_ENTRE_RELEVES = 65.0

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
#
#  ⚠️ CE 25 EST UN PARI, PAS UNE MESURE — et il ne sert plus que de REPLI.
#  Le 429 mesuré porte `retry-after: 5` ET `x-ratelimit-reset: 49` : 25 s sont
#  à la fois cinq fois trop longues par rapport au premier et deux fois trop
#  courtes par rapport au second. C'est ce qui expliquait le « 1 échec » vu le
#  18/08, quand la reprise retombait dans une fenêtre encore fermée.
#  On lit donc désormais ce que Roblox nous DIT (voir `_attente_429`), et on ne
#  garde cette valeur que si les en-têtes manquent — rien ne prouve qu'ils
#  survivent au proxy de Railway.
ATTENTE_APRES_429 = 25.0

#  Bornes de l'attente lue dans les en-têtes. Le haut est la taille de la
#  fenêtre : au-delà, attendre n'apporte plus rien. Le bas protège d'un en-tête
#  à 0 qui ferait retenter immédiatement.
ATTENTE_429_MIN = 5.0
ATTENTE_429_MAX = 60.0

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
    #  ⚠️ MODE SIMULATION — demandé par la spécification du 30/08 : « un mode
    #  simulation permettant de tester une transition sans publier de fausse
    #  annonce publique ».
    #  Quand il est allumé, TOUT tourne — relevés, détection, mise en file —
    #  mais RIEN ne part dans un salon. Les fiches restent en file et ne sont
    #  pas marquées envoyées : éteindre l'interrupteur les fait partir pour de
    #  bon, dans l'ordre. C'est ce qui permet d'éprouver la chaîne complète sur
    #  un vrai serveur sans mentir à ses membres.
    "roblox_veille_simulation": False,
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
        #  ⚠️ LA FILE D'ATTENTE D'ENVOI — « outbox », exigée par la
        #  spécification du 30/08 et par deux défauts mesurés du dépôt.
        #
        #  CE QU'ELLE RÉPARE, ET C'EST MESURÉ.
        #  1. LA FAMINE. `_TRANCHE_FLUX["nouveaux"] = 5` tronque le lot AVANT
        #     que quoi que ce soit ne soit publié, mais `comparer_et_enregistrer`
        #     a DÉJÀ écrit l'article en base au même passage. Au passage
        #     suivant, l'article n'est plus « jamais vu » : il ne peut plus
        #     JAMAIS réapparaître. Rejoué en exécution le 30/08 : 20 nouveautés
        #     toutes dans la fenêtre → 5 publiées au passage 1, puis 0, puis 0.
        #     **15 sur 20 perdues définitivement**, pendant que le journal
        #     imprimait « Rien n'est perdu. »
        #  2. LA PERTE AU REDÉMARRAGE. Railway redéploie ; ce qui était détecté
        #     mais pas encore envoyé disparaissait avec le processus.
        #
        #  LA CONTRAINTE D'UNICITÉ EST LE CŒUR : une même transition
        #  (serveur, article, de → vers) ne peut pas être mise en file deux
        #  fois, donc ne peut pas produire deux annonces — même si la détection
        #  la revoit à chaque passage, même après un redémarrage.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_transitions("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " guild_id INTEGER NOT NULL,"
            " asset_id INTEGER NOT NULL,"
            " flux TEXT NOT NULL,"
            " de TEXT NOT NULL,"
            " vers TEXT NOT NULL,"
            " detecte_le TEXT NOT NULL,"
            #  L'article entier, en JSON : c'est ce qui permet de publier
            #  APRÈS un redémarrage, sans redemander quoi que ce soit à Roblox.
            " charge TEXT NOT NULL,"
            " message_id INTEGER,"
            " envoye_le TEXT,"
            " essais INTEGER NOT NULL DEFAULT 0,"
            " dernier_echec TEXT,"
            " UNIQUE(guild_id, asset_id, de, vers))"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_roblox_transitions_attente"
            " ON roblox_transitions(guild_id, envoye_le, detecte_le)")
        #  ⚠️ LA SÉRIE TEMPORELLE — la seule chose qui rendra un jour une
        #  prédiction POSSIBLE, et elle n'existait pas.
        #
        #  Mesuré le 30/08 : sept points d'API testés ne donnent AUCUNE date de
        #  passage en Limited. Il n'existe donc aucune vérité terrain, donc
        #  rien à calibrer, donc aucune probabilité honnête — et on refuse d'en
        #  fabriquer une (voir `tests/test_veille_transitions.py`).
        #  MAIS la spécification a raison sur un point : « le système doit
        #  construire ses propres séries temporelles à partir de snapshots ».
        #  Tant que personne ne les enregistre, l'attente est infinie. Cette
        #  table est le seul moyen que « dans six mois » devienne un jour.
        #
        #  ⚠️ CADENCE : UNE MESURE PAR ARTICLE ET PAR JOUR, pas une par passage.
        #  48 passages par jour × 964 articles = 46 000 lignes quotidiennes,
        #  ingérable sur SQLite au bout de quelques mois. Une mesure par jour
        #  suffit très largement à « croissance des favoris sur 1, 7 et 30
        #  jours ». On écrit AUSSI hors cadence quand un champ STRUCTUREL
        #  bouge (prix, mise hors vente, passage collectionnable) : ce sont
        #  précisément les instants qu'un modèle devra pouvoir dater.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_mesures("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " asset_id INTEGER NOT NULL,"
            " mesure_le TEXT NOT NULL,"
            " prix INTEGER,"
            " favoris INTEGER,"
            " hors_vente INTEGER NOT NULL DEFAULT 0,"
            " collectionnable INTEGER NOT NULL DEFAULT 0,"
            " classe TEXT,"
            " quantite INTEGER)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_roblox_mesures_article"
            " ON roblox_mesures(asset_id, mesure_le)")
        #  Où reprendre la pagination d'un relevé au passage suivant. Une seule
        #  ligne par source. Voir `relever_collectionnables`.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_curseurs("
            " source TEXT PRIMARY KEY,"
            " curseur TEXT,"
            " tours INTEGER NOT NULL DEFAULT 0,"
            " maj_le TEXT NOT NULL)"
        )
        #  Les réparations de DONNÉES déjà écrites, faites une seule fois.
        #  Un correctif de code ne répare pas une base : c'est la leçon de
        #  `oublier_publies`, et elle a coûté au propriétaire des semaines
        #  d'articles invisibles.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_migrations("
            " cle TEXT PRIMARY KEY,"
            " fait_le TEXT NOT NULL,"
            " lignes INTEGER NOT NULL DEFAULT 0)"
        )
        await db.commit()
    await _migrer_amorce_bascules()


#  ═══════════════════════════════════════════════════════════════════════════
#  Réparations de données — une fois, et jamais deux
#  ═══════════════════════════════════════════════════════════════════════════

MIGRATION_AMORCE_BASCULES = "amorce_ne_marque_plus_bascules_2026_08_30"


async def _migrer_amorce_bascules() -> int:
    """Efface les marques « déjà publié » posées à tort dans le flux bascules.

    ⚠️ POURQUOI C'EST SANS RISQUE — ET LA PREMIÈRE VERSION DE CETTE DÉFENSE
    ÉTAIT FAUSSE, corrigée après réfutation adverse le 30/08.

    Elle disait : « publier une bascule exige aussi `bascule_detectee`, donc
    effacer ces marques ne peut RIEN republier ». C'est vrai POUR LE FLUX
    `bascules`, et seulement pour lui. Ce que la phrase oubliait, c'est que la
    marque `bascules` sert AUSSI de bouclier de priorité (`publiable_dans` :
    un article sorti en `bascules` ne peut plus sortir dans un flux plus
    faible). L'effacer rouvre donc, en droit, une republication en
    `nouveautes`.

    CE QUI FERME QUAND MÊME LE RISQUE, ET C'EST MESURABLE :
      · l'article garde sa marque `nouveautes`, que cette migration ne touche
        pas — `publiable_dans(..., "nouveautes")` refuse toujours ;
      · pour redevenir « jamais vu », il faudrait qu'il soit évincé de
        `roblox_articles` par le plafond LRU. Mesuré le 30/08 :
        `MAX_ARTICLES_SUIVIS = 3000` contre 964 (catalogue général) + 998
        (flux Limited) ≈ 1 962 suivis. **Le LRU n'évince rien.**

    ⚠️ CETTE DÉFENSE A DONC UNE DATE DE PÉREMPTION : le jour où le catalogue
    Roblox dépassera 3 000 articles suivis, ou si le flux `surveiller` est
    réactivé, il faudra la reprendre. On ne la laisse pas passer pour une
    vérité éternelle.

    Rend le nombre de lignes effacées ; 0 si la migration a déjà été faite.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM roblox_migrations WHERE cle=?",
                (MIGRATION_AMORCE_BASCULES,)) as cur:
                if await cur.fetchone():
                    return 0
            async with db.execute(
                "SELECT COUNT(*) FROM roblox_publies WHERE flux='bascules'"
            ) as cur:
                row = await cur.fetchone()
            n = int(row[0] or 0) if row else 0
            await db.execute("DELETE FROM roblox_publies WHERE flux='bascules'")
            await db.execute(
                "INSERT OR REPLACE INTO roblox_migrations(cle, fait_le, lignes)"
                " VALUES(?,?,?)",
                (MIGRATION_AMORCE_BASCULES,
                 datetime.now(timezone.utc).isoformat(), n))
            await db.commit()
        #  ⚠️ LE DIRE DANS LES JOURNAUX. Une réparation muette est
        #  indiscernable d'une réparation qui n'a pas eu lieu — et c'est
        #  précisément la question que le propriétaire posera.
        _log(f"[roblox_veille migration] amorce/bascules : {n} marque(s) "
             f"posée(s) à tort effacée(s) — les passages en Limited peuvent "
             f"de nouveau sortir")
        return n
    except Exception as ex:
        _log(f"[roblox_veille _migrer_amorce_bascules] {ex}")
        return 0


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
    #  ⚠️ ROTATION DU CURSEUR — CORRECTIF DU 30/08/2026.
    #  Deux pages restent le plafond (c'est le débit qui est en jeu, mesuré :
    #  12 requêtes/60 s par chemin, `reste_min` descendu à 2). Mais on ne relit
    #  plus les deux MÊMES pages : on reprend là où le passage précédent s'est
    #  arrêté. Mesuré le 30/08 : le flux compte 998 articles en 9 pages, donc
    #  238 lus sur 998 — 24 %. Les 76 % restants n'étaient JAMAIS comparés à
    #  leur état antérieur, et leur passage en Limited ne pouvait pas être vu.
    #  Avec la rotation, les 998 sont couverts en 5 passages, soit 2 h 30 — ce
    #  qui tient dans la fenêtre de six heures de `vu_le`, la condition même de
    #  « vient de passer Limited ».
    depart, tours = await _curseur_lu("collectionnables")
    out = await _relever_catalogue({
        "Category": 1,
        "SortType": 3,
        "Limit": _limite_valide(limite),
        "SalesTypeFilter": 2,          # 2 = Limited. Mesuré le 16/08.
        "CreatorType": "User",
        "CreatorTargetId": CREATEUR_ROBLOX,
    }, "collectionnables", max_pages=MAX_PAGES_COLLECTIONNABLES,
        curseur_depart=depart)
    if out.get("curseur_refuse"):
        #  Curseur périmé : on repart du début plutôt que de rester coincé.
        _log("[roblox_veille collectionnables] curseur périmé — on repart du "
             "début du flux")
        await _curseur_ecrit("collectionnables", None, tours + 1)
    elif out["code"] == 200:
        suivant = out.get("curseur_suivant")
        #  ⚠️ UN RELEVÉ TRONQUÉ N'EST PAS UN TOUR TERMINÉ. Le 429 est
        #  requalifié en 200 plus haut (à raison : un relevé presque complet
        #  vaut mieux que rien), mais le compter comme un tour ferait croire
        #  qu'on a couvert les 998 articles alors qu'on s'est arrêté en route.
        fini = not suivant and not out.get("tronque")
        await _curseur_ecrit("collectionnables", suivant,
                             tours + (1 if fini else 0))
        out["tour"] = tours + (1 if fini else 0)
    return out


async def _curseur_lu(source: str) -> tuple[str | None, int]:
    """Le curseur mémorisé pour cette source, et le nombre de tours complets."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT curseur, tours FROM roblox_curseurs WHERE source=?",
                (source,)) as cur:
                row = await cur.fetchone()
        if row:
            return (str(row[0]) if row[0] else None), int(row[1] or 0)
    except Exception as ex:
        _log(f"[roblox_veille _curseur_lu] {ex}")
    return None, 0


async def _curseur_ecrit(source: str, curseur: str | None, tours: int) -> None:
    """Mémorise où reprendre. `None` = le prochain passage repart du début."""
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO roblox_curseurs(source, curseur, tours, maj_le)"
                " VALUES(?,?,?,?) ON CONFLICT(source) DO UPDATE SET"
                " curseur=?, tours=?, maj_le=?",
                (source, curseur, int(tours),
                 datetime.now(timezone.utc).isoformat(),
                 curseur, int(tours), datetime.now(timezone.utc).isoformat()))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_veille _curseur_ecrit] {ex}")


#  Voir la docstring de `relever_collectionnables` : ce flux n'est pas trié par
#  date, il ne sert qu'à détecter, deux pages suffisent.
MAX_PAGES_COLLECTIONNABLES = 2


async def _relever_catalogue(params: dict, source: str,
                             max_pages: int | None = None,
                             curseur_depart: str | None = None) -> dict:
    """L'appel au catalogue, partagé par les deux relevés.

    `source` sert au suivi de santé : un flux muet doit se voir SÉPARÉMENT.
    Si les collectionnables tombent en panne pendant que les nouveautés
    marchent, un compteur commun le masquerait — et un flux mort ressemble
    exactement à un flux calme.
    """
    out = {"articles": [], "code": None, "echecs": 0, "pages": 0,
           "complet": False, "tronque": False,
           #  Compteurs de DEBIT — ils remplacent la constante morte
           #  MAX_APPELS_PAR_PASSAGE, qui annoncait 8 alors que le passage
           #  reel en fait 11. Un chiffre mesure vaut mieux qu'un plafond
           #  declare que le code ne respecte pas.
           "req": 0, "n429": 0, "reste_min": None,
           #  Où reprendre au prochain passage. `None` = recommencer du début.
           #  Voir `relever_collectionnables` : c'est ce qui transforme deux
           #  pages figées en une lecture COMPLÈTE étalée dans le temps.
           "curseur_suivant": None, "curseur_refuse": False}
    vus: set[int] = set()
    curseur = curseur_depart or None
    try:
        async with _ouvrir() as sess:
            for page in range(MAX_PAGES_PAR_RELEVE):
                p = dict(params)
                if curseur:
                    p["Cursor"] = curseur
                #  ⚠️ REPRISE SUR 429, ICI AUSSI. La sortie Railway est une IP
                #  PARTAGÉE : d'autres applications tapent les mêmes API, le
                #  budget est moins prévisible que depuis un poste. Capture du
                #  propriétaire (18/08) : « collectionnables · 429 · 1 échec »
                #  dès la première page. Une seule reprise, après attente —
                #  comme pour les fiches (`_appel_avec_reprise`).
                code, data = await _appel_avec_reprise(
                    sess, API_CATALOGUE, p,
                    etiquette=f"{source} page {page + 1}", stats=out)
                out["code"] = code
                if code != 200 or data is None:
                    _log(f"[roblox_veille {source}] HTTP {code} à la page {page + 1}")
                    #  ⚠️ UN CURSEUR MÉMORISÉ PÉRIME. Roblox le refuse alors
                    #  par un 400, et sans ce drapeau le relevé resterait
                    #  bloqué sur ce curseur mort à CHAQUE passage, muet pour
                    #  toujours. On le signale ; l'appelant repart du début.
                    if page == 0 and curseur_depart and code in (400, 404):
                        out["curseur_refuse"] = True
                    #  ⚠️ UN 429 N'EST PAS UNE PANNE : c'est notre propre
                    #  débit. On garde les pages déjà obtenues et on
                    #  reprendra au prochain passage. Les jeter ferait
                    #  perdre un relevé presque complet pour rien.
                    if code == 429 and out["articles"]:
                        out["code"] = 200
                        #  ⚠️ ET ON REJOUE LA PAGE RATÉE AU PROCHAIN PASSAGE.
                        #  Sans cette ligne, la sortie par 429 laissait
                        #  `curseur_suivant` à None, ce que l'appelant lisait
                        #  comme « tour terminé » : la rotation REMBOBINAIT au
                        #  début du flux, et les pages suivantes n'étaient
                        #  jamais atteintes tant que le 429 retombait au même
                        #  rang. Le bilan imprimait pourtant « reprise au
                        #  prochain passage » — l'inverse exact de ce qui se
                        #  produisait. Trouvé en réfutation adverse le 30/08.
                        out["curseur_suivant"] = curseur
                        #  ⚠️ ON GARDE LA TRACE DE LA TRONCATURE.
                        #  Requalifier le 429 en 200 est le bon choix — un
                        #  relevé presque complet vaut mieux que rien — mais
                        #  l'appelant ne pouvait plus savoir qu'il lisait une
                        #  liste incomplète : `complet` et `pages` étaient
                        #  calculés et lus NULLE PART. Un relevé tronqué
                        #  ressemblait trait pour trait à un relevé entier.
                        out["tronque"] = True
                    break

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
                    #  ⚠️ ON MÉMORISE OÙ ON S'ARRÊTE. Sans cette ligne, le
                    #  relevé relisait éternellement les deux MÊMES pages :
                    #  mesuré le 30/08, 238 articles sur 998, soit 24 % du flux
                    #  Limited — les 76 % restants n'étaient jamais comparés,
                    #  donc leur passage en Limited ne pouvait pas être vu.
                    out["curseur_suivant"] = data.get("nextPageCursor") or None
                    break

                curseur = data.get("nextPageCursor")
                if not curseur:
                    out["complet"] = True
                    break
                await asyncio.sleep(PAUSE_ENTRE_APPELS_CATALOGUE)
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


async def fiche_par_id(asset_id: int, item_type: str = "Asset") -> dict | None:
    """L'état ACTUEL d'un article, redemandé à Roblox. `None` si introuvable.

    ⚠️ POURQUOI ON REDEMANDE PLUTÔT QUE DE LIRE LA BASE. La spécification est
    explicite : « /item doit forcer une actualisation raisonnable de l'article
    avant de répondre ». Servir la ligne en base ferait afficher l'état du
    dernier relevé — jusqu'à trente minutes de retard, et bien plus si
    l'article est sorti du catalogue général. Sur une commande qu'on tape
    précisément pour VÉRIFIER quelque chose, ce serait le pire moment pour
    répondre de mémoire.

    ⚠️ Le point de détails par lot est le SEUL qui rende un article quel que
    soit son âge — la recherche, elle, ne voit que ce qui est dans ses pages.
    """
    global _jeton_xsrf
    try:
        aid = int(asset_id)
    except (TypeError, ValueError):
        return None
    if aid <= 0:
        return None
    lot = await fiches_par_ids([aid], item_type=item_type)
    return lot[0] if lot else None


async def fiches_par_ids(ids: list, item_type: str = "Asset") -> list[dict]:
    """Jusqu'à 120 articles en UNE requête. Liste vide si rien.

    ⚠️ UNE REQUÊTE POUR CENT, JAMAIS CENT REQUÊTES. Le propriétaire, le
    30/08 : « assure-toi de ne pas spammer en boucle une recherche qui sert à
    rien, ça évite de spammer la plateforme, de spammer l'API et qu'elle ne
    marche plus. » Ce point accepte un lot ; s'en priver serait gaspiller.
    """
    global _jeton_xsrf
    propres = []
    for x in (ids or []):
        try:
            v = int(x)
            if v > 0:
                propres.append(v)
        except (TypeError, ValueError):
            continue
    if not propres:
        return []
    genre = "Bundle" if str(item_type or "").lower() == "bundle" else "Asset"
    corps = {"items": [{"itemType": genre, "id": v} for v in propres[:120]]}
    try:
        async with _ouvrir() as sess:
            for tentative in (1, 2):
                entetes = {"Accept-Language": LANGUE_FR}
                if _jeton_xsrf:
                    entetes["X-CSRF-TOKEN"] = _jeton_xsrf
                async with sess.post(API_DETAILS, json=corps,
                                     headers=entetes) as r:
                    if r.status == 403 and tentative == 1:
                        #  La danse XSRF : le 403 PORTE le jeton.
                        _jeton_xsrf = r.headers.get("x-csrf-token") or _jeton_xsrf
                        continue
                    if r.status != 200:
                        _log(f"[roblox_veille fiches_par_ids] HTTP {r.status} "
                             f"pour {len(propres)} identifiant(s)")
                        return []
                    data = await r.json()
                return _normaliser(data.get("data") or [])
    except Exception as ex:
        _log(f"[roblox_veille fiches_par_ids] {type(ex).__name__}: {ex}")
    return []


async def _deja_reellement_envoye(guild_id: int, asset_id: int,
                                  flux: str) -> bool:
    """Une fiche est-elle DÉJÀ PARTIE dans un salon pour cet article ?

    Distinct de `deja_publie` : celui-ci lit `roblox_publies`, qui contient
    aussi tout ce que l'amorce a absorbé SANS l'envoyer. Ici on lit la file
    d'envoi, seule table qui porte la date d'envoi et l'identifiant du message.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM roblox_transitions WHERE guild_id=?"
                " AND asset_id=? AND flux=? AND envoye_le IS NOT NULL LIMIT 1",
                (int(guild_id), int(asset_id), str(flux))) as cur:
                return bool(await cur.fetchone())
    except Exception as ex:
        _log(f"[roblox_veille _deja_reellement_envoye] {ex}")
        #  Fail-CLOSED : dans le doute, on ne republie pas.
        return True


async def rattraper_nouveautes(guild_id: int, combien: int = 12) -> dict:
    """Remet en file les N accessoires Roblox les plus récents jamais annoncés.

    ⚠️ POURQUOI CE GESTE EXISTE, ET POURQUOI IL N'EST PAS AUTOMATIQUE.
    Le propriétaire, le 30/08 : « assure-toi que les derniers accessoires
    soient bien publiés sur le serveur ». Mesuré le même jour : les huit
    derniers articles créés par Roblox ont TOUS 38,4 jours, pour une fenêtre
    de publication de six heures (`FENETRE_DIRECTE_HEURES`, imposée le 18/08).
    Ils ne peuvent donc PAS sortir — et l'amorce les a en plus marqués « déjà
    publiés ». La réponse honnête à sa demande n'était pas « c'est fait », mais
    « voici le geste qui le fait ».

    ⚠️ CE GESTE NE TOUCHE PAS À LA FENÊTRE. Élargir `FENETRE_DIRECTE_HEURES`
    changerait la règle pour toujours, alors que le propriétaire l'a posée
    explicitement (« pas d'il y a un jour, deux jours »). On ne discute pas sa
    règle : on lui donne un rattrapage BORNÉ et volontaire, qu'il déclenche.

    Ce qu'on rattrape : les articles les plus récemment CRÉÉS, jamais sortis
    dans aucun flux, et pas plus vieux que `AGE_MAX_JOURS` — au-delà ce n'est
    plus une nouvelle, c'est une archive, et ROBLOX.md l'interdit.

    Rend `{"candidats", "enfiles", "plus_vieux_j"}`.
    """
    out = {"candidats": 0, "enfiles": 0, "plus_vieux_j": None}
    try:
        combien = max(1, min(int(combien), 30))
    except (TypeError, ValueError):
        combien = 12
    borne = (datetime.now(timezone.utc)
             - timedelta(days=AGE_MAX_JOURS)).isoformat()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT asset_id FROM roblox_articles"
                " WHERE cree_le IS NOT NULL AND cree_le >= ?"
                " ORDER BY cree_le DESC LIMIT ?",
                (borne, combien * 3)) as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
        if not ids:
            return out
        #  ⚠️ ON REDEMANDE LES FICHES À ROBLOX, en UNE requête. La ligne en
        #  base ne porte ni le type d'objet (Asset/Bundle, qui commande le
        #  lien et la vignette), ni la classe, ni la description : publier
        #  depuis elle donnerait des fiches amputées.
        fiches = {a["asset_id"]: a for a in await fiches_par_ids(ids)}
        retenus = []
        for aid in ids:
            if len(retenus) >= combien:
                break
            a = fiches.get(aid)
            if a is None:
                continue
            #  ⚠️ LA MARQUE « nouveautes » NE COMPTE PAS ICI — c'est ELLE qu'on
            #  vient lever. L'amorce l'a posée sur les 964 articles du
            #  catalogue sans qu'aucune fiche ne soit jamais partie : s'en
            #  servir comme filtre ferait que ce bouton ne rattrape RIEN, ce
            #  qui est précisément le défaut qu'il répare.
            #  On écarte donc sur deux critères, et deux seulement :
            if "bascules" in await flux_deja_sortis(guild_id, aid):
                #  Déjà annoncé comme passé Limited : le ressortir en
                #  « nouveauté » serait un doublon ET une régression de flux.
                continue
            if await _deja_reellement_envoye(guild_id, aid, "nouveautes"):
                #  ⚠️ LE SEUL REGISTRE FIABLE DE CE QUI EST SORTI. La file
                #  d'envoi garde la date et l'identifiant du message Discord ;
                #  `roblox_publies`, lui, contient aussi tout ce que l'amorce a
                #  absorbé sans jamais l'envoyer. Confondre les deux, c'est
                #  soit republier, soit ne rien rattraper.
                continue
            retenus.append(a)
        out["candidats"] = len(retenus)
        if not retenus:
            return out
        #  Du plus ANCIEN au plus récent : même règle de lecture que partout.
        retenus = ordonner_publication(retenus, len(retenus))
        async with _get_db() as db:
            for a in retenus:
                #  On lève la marque posée par l'amorce — sans elle, la fiche
                #  entrerait en file et serait refusée à la sortie.
                await db.execute(
                    "DELETE FROM roblox_publies WHERE guild_id=? AND asset_id=?"
                    " AND flux='nouveautes'", (int(guild_id), a["asset_id"]))
            await db.commit()
        for a in retenus:
            if await enfiler(guild_id, a, "nouveautes"):
                out["enfiles"] += 1
        vieux = [_jours_depuis(a.get("cree_le")) for a in retenus]
        vieux = [v for v in vieux if v is not None]
        out["plus_vieux_j"] = max(vieux) if vieux else None
    except Exception as ex:
        _log(f"[roblox_veille rattraper_nouveautes] {ex}")
    return out


async def derniers_evenements(guild_id: int, flux: str,
                              limite: int = 10) -> list[dict]:
    """Les dernières fiches SORTIES de ce flux, la plus récente d'abord.

    Lit la file d'envoi : c'est la seule table qui garde ce qui a réellement
    été annoncé, avec sa date et son identifiant de message.
    """
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT charge, envoye_le, message_id, de, vers"
                " FROM roblox_transitions WHERE guild_id=? AND flux=?"
                " AND envoye_le IS NOT NULL"
                " ORDER BY envoye_le DESC LIMIT ?",
                (int(guild_id), str(flux), int(limite))) as cur:
                for r in await cur.fetchall():
                    try:
                        out.append({"article": json.loads(r[0]),
                                    "envoye_le": r[1], "message_id": r[2],
                                    "de": r[3], "vers": r[4]})
                    except Exception:
                        continue
    except Exception as ex:
        _log(f"[roblox_veille derniers_evenements] {ex}")
    return out


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


#  Les trois classes de collection, de la plus forte à la plus faible. L'ordre
#  compte : un article peut porter plusieurs restrictions à la fois, et c'est
#  la plus spécifique qui le nomme.
CLASSE_LIMITED_U = "LimitedUnique"
CLASSE_LIMITED = "Limited"
CLASSE_COLLECTIBLE = "Collectible"        # « UGC Limited » côté joueur


def _classe_collection(restrictions) -> str:
    """Laquelle des trois classes, ou "" si l'article n'est pas collectionnable.

    ⚠️ L'ORDRE DES TESTS EST LA RÈGLE. `LimitedUnique` contient « limited » :
    tester « Limited » d'abord classerait tous les Limited U comme de simples
    Limited, silencieusement.
    """
    bas = [str(x).lower() for x in (restrictions or [])]
    if any("unique" in x for x in bas):
        return CLASSE_LIMITED_U
    if any(x.startswith("limited") for x in bas):
        return CLASSE_LIMITED
    if any(x.startswith("collectible") for x in bas):
        return CLASSE_COLLECTIBLE
    return ""


def libelle_classe(classe: str) -> str:
    """Ce qu'on écrit au joueur. `Collectible` n'est PAS un Limited Roblox."""
    return {
        CLASSE_LIMITED_U: "LIMITED U",
        CLASSE_LIMITED: "LIMITED",
        CLASSE_COLLECTIBLE: "UGC LIMITED",
    }.get(classe or "", "COLLECTIONNABLE")


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
                #  ⚠️ TROIS CLASSES, PAS DEUX — exigence de la spécification du
                #  30/08 : « Limited : Roblox Limited ; LimitedUnique : Roblox
                #  Limited Unique ; Collectible : UGC Limited. Le système doit
                #  distinguer ces trois catégories. »
                #  `collectionnable` ci-dessus les fond en un seul booléen, ce
                #  qui reste juste pour la détection, mais faisait annoncer un
                #  UGC Limited comme un Limited Roblox. Mesuré le 30/08 :
                #  `Collectible` existe réellement dans ce flux (2 articles en
                #  page 1, 10 sur 159 détaillés).
                #  ⚠️ NE PAS ARBITRER VIA `economy.roblox.com` : mesuré, il
                #  CONTREDIT le catalogue (`IsLimitedUnique: true` sur un
                #  article que le catalogue classe `Collectible`).
                "classe": _classe_collection(restrictions),
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


#  Combien de fois on frappe avant d'abandonner, 429 compris. Trois : la
#  première tentative, puis DEUX reprises espacées exponentiellement. Au-delà,
#  on n'aide plus personne — on garde l'IP partagée de Railway sous le mur, et
#  le passage suivant arrive de toute façon dans trente minutes.
MAX_TENTATIVES_429 = 3


def _attente_429(entetes) -> float:
    """Combien attendre après un 429 — d'après ce que Roblox ANNONCE.

    On lit `Retry-After` puis, à défaut, `x-ratelimit-reset`. La valeur est
    bornée par `ATTENTE_429_MIN`/`MAX`. Si aucun en-tête n'est exploitable, on
    retombe sur `ATTENTE_APRES_429` — le repli DOIT rester, rien ne prouve que
    ces en-têtes traversent le proxy de Railway.
    """
    #  ⚠️ LE PLUS GRAND DES DEUX, PAS LE PREMIER TROUVÉ — mesuré le 30/08 sur
    #  `catalog/v1/catalog/items/details` : `retry-after: 5` et
    #  `x-ratelimit-reset: 12` CONTREDISENT l'un l'autre sur la même réponse,
    #  et le corps du 429 est vide. Prendre le premier (5 s) ne suffisait pas :
    #  la reprise retombait dans le mur. On prend donc le plus prudent.
    annonces = []
    for cle in ("Retry-After", "retry-after", "x-ratelimit-reset"):
        try:
            brut = (entetes or {}).get(cle)
            if brut is None:
                continue
            v = float(str(brut).strip())
            if v > 0:
                annonces.append(v)
        except Exception:
            continue
    if annonces:
        return max(ATTENTE_429_MIN,
                   min(ATTENTE_429_MAX, max(annonces) + 2.0))
    return ATTENTE_APRES_429


def _attente_429_progressive(entetes, tentative: int) -> float:
    """L'attente de la n-ième reprise : exponentielle, avec une part aléatoire.

    ⚠️ POURQUOI L'ALÉA — exigence de la spécification du 30/08, et raison
    concrète : Railway sort par une IP PARTAGÉE. Si deux applications prennent
    le même 429 à la même seconde et attendent exactement la même durée, elles
    repartent ENSEMBLE et se refont refuser ensemble. Un peu de dispersion
    suffit à casser cette synchronisation.

    La base reste ce que Roblox ANNONCE (`_attente_429`) : on ne l'allonge que
    si l'annonce n'a pas suffi, ce que prouve une seconde reprise.
    """
    base = _attente_429(entetes)
    facteur = 2 ** max(0, int(tentative) - 1)
    #  ⚠️ L'ALÉA N'ALLONGE, IL NE RACCOURCIT JAMAIS. La première version tirait
    #  entre 0,75 et 1,25 : au-delà d'une annonce de 6 s, le tirage bas rendait
    #  une attente PLUS COURTE que ce que Roblox venait d'exiger — on repartait
    #  droit dans le mur, en croyant faire mieux. Le commentaire disait
    #  d'ailleurs l'inverse de ce que faisait le code.
    #  De 1,0 à 1,3 : la dispersion suffit à désynchroniser deux applications
    #  qui partagent l'IP de Railway, sans jamais désobéir à l'annonce.
    alea = random.uniform(1.0, 1.3)
    return max(ATTENTE_429_MIN, min(ATTENTE_429_MAX, base * facteur * alea))


def _noter_budget(stats, entetes) -> None:
    """Retient le plus petit `x-ratelimit-remaining` vu du passage.

    ⚠️ C'EST LA SEULE MESURE QUI DIRA SI L'IP PARTAGÉE EST LE PROBLÈME.
    Le budget de 12 requêtes n'est pas le nôtre seul : d'autres applications
    sortent par la même adresse. Tant qu'on ne voyait pas ce qu'il RESTE, on ne
    pouvait pas distinguer « notre cadence est trop rapide » de « un voisin a
    mangé le budget ». Absent des en-têtes ⇒ on ne note rien, pas de zéro
    trompeur.
    """
    if stats is None:
        return
    try:
        brut = (entetes or {}).get("x-ratelimit-remaining")
        if brut is None:
            return
        v = int(str(brut).strip())
        actuel = stats.get("reste_min")
        stats["reste_min"] = v if actuel is None else min(actuel, v)
    except Exception:
        pass


async def _appel_avec_reprise(sess, url: str, params: dict | None = None,
                              etiquette: str | None = None,
                              stats: dict | None = None):
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
    for tentative in range(1, MAX_TENTATIVES_429 + 1):
        try:
            if stats is not None:
                stats["req"] = int(stats.get("req") or 0) + 1
            async with sess.get(url, params=params) as r:
                _noter_budget(stats, r.headers)
                #  ⚠️ ON COMPTE TOUS LES 429, Y COMPRIS LE DERNIER. L'incrément
                #  vivait sous la condition de reprise : le 429 terminal — le
                #  seul qui coûte vraiment une page — n'était jamais compté, et
                #  `429=0` pouvait s'afficher sur un passage tronqué.
                if r.status == 429 and stats is not None:
                    stats["n429"] = int(stats.get("n429") or 0) + 1
                if r.status == 429 and tentative < MAX_TENTATIVES_429:
                    _attente = _attente_429_progressive(r.headers, tentative)
                    #  ⚠️ DIRE QUOI, PAS SEULEMENT « details ».
                    #  Les DEUX relevés paginés tapent la même URL, qui finit
                    #  par « details » : le journal disait donc « HTTP 429 sur
                    #  details » sans qu'on puisse savoir lequel des deux était
                    #  en cause — ni à quelle page. Constaté le 20/08 en
                    #  cherchant l'origine d'un 429 systématique.
                    _log(f"[roblox_veille] HTTP 429 sur "
                         f"{etiquette or url.split('/')[-1]} — "
                         f"attente {_attente:.0f} s puis reprise "
                         f"({tentative}/{MAX_TENTATIVES_429 - 1})")
                    await asyncio.sleep(_attente)
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
    #  ⚠️ HORS DU `try` PRÉCÉDENT, ET APRÈS SON `commit`. Une panne
    #  d'enregistrement de la série temporelle ne doit JAMAIS faire perdre une
    #  détection : la série est un bonus pour plus tard, la détection est le
    #  produit. `enregistrer_mesures` avale d'ailleurs ses propres erreurs.
    await enregistrer_mesures(articles)
    return res


#  Une mesure par article et par jour suffit — voir le commentaire de la table.
HEURES_ENTRE_MESURES = 24.0


async def enregistrer_mesures(articles: list[dict]) -> int:
    """Alimente la série temporelle. Rend le nombre de mesures écrites.

    Écrit si, et seulement si : plus de `HEURES_ENTRE_MESURES` depuis la
    dernière mesure de cet article, OU un champ STRUCTUREL a bougé depuis
    elle (prix, mise hors vente, passage collectionnable, classe). Les favoris
    seuls ne déclenchent pas — ils bougent en permanence et feraient écrire à
    chaque passage.
    """
    if not articles:
        return 0
    ecrites = 0
    try:
        async with _get_db() as db:
            #  UNE requête pour tout le lot : 964 requêtes individuelles
            #  coûteraient plus cher que la détection elle-même.
            derniers: dict[int, tuple] = {}
            async with db.execute(
                "SELECT m.asset_id, m.mesure_le, m.prix, m.hors_vente,"
                " m.collectionnable, m.classe FROM roblox_mesures m"
                " JOIN (SELECT asset_id, MAX(id) AS mid FROM roblox_mesures"
                "       GROUP BY asset_id) d ON d.mid = m.id") as cur:
                for r in await cur.fetchall():
                    derniers[int(r[0])] = tuple(r[1:])
            maintenant = datetime.now(timezone.utc).isoformat()
            for a in articles:
                try:
                    aid = int(a["asset_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                prec = derniers.get(aid)
                if prec is not None:
                    h = _heures_depuis(prec[0])
                    structure = (a.get("prix"), int(a.get("hors_vente") or 0),
                                 int(a.get("collectionnable") or 0),
                                 a.get("classe") or "")
                    inchange = structure == (prec[1], int(prec[2] or 0),
                                             int(prec[3] or 0), prec[4] or "")
                    if inchange and h is not None and h < HEURES_ENTRE_MESURES:
                        continue
                await db.execute(
                    "INSERT INTO roblox_mesures(asset_id, mesure_le, prix,"
                    " favoris, hors_vente, collectionnable, classe, quantite)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (aid, maintenant, a.get("prix"), a.get("favoris"),
                     int(a.get("hors_vente") or 0),
                     int(a.get("collectionnable") or 0),
                     a.get("classe") or "", a.get("quantite")))
                ecrites += 1
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_veille enregistrer_mesures] {ex}")
    return ecrites


async def croissance_favoris(asset_id: int, jours: int) -> int | None:
    """Favoris gagnés sur `jours`, ou None si la série ne remonte pas si loin.

    ⚠️ REND `None` PLUTÔT QU'UN ZÉRO. « Pas de croissance » et « je ne sais
    pas encore » sont deux choses différentes, et les confondre serait le
    premier pas vers un chiffre fabriqué.
    """
    try:
        borne = (datetime.now(timezone.utc) - timedelta(days=int(jours))).isoformat()
        async with _get_db() as db:
            async with db.execute(
                "SELECT favoris FROM roblox_mesures WHERE asset_id=?"
                " AND mesure_le <= ? ORDER BY mesure_le DESC LIMIT 1",
                (int(asset_id), borne)) as cur:
                avant = await cur.fetchone()
            if not avant or avant[0] is None:
                return None
            async with db.execute(
                "SELECT favoris FROM roblox_mesures WHERE asset_id=?"
                " ORDER BY mesure_le DESC LIMIT 1", (int(asset_id),)) as cur:
                apres = await cur.fetchone()
        if not apres or apres[0] is None:
            return None
        return int(apres[0]) - int(avant[0])
    except Exception as ex:
        _log(f"[roblox_veille croissance_favoris] {ex}")
        return None


async def etat_serie() -> dict:
    """De quoi la série dispose. Sert à `/roblox modele` — et à dire NON.

    ⚠️ C'EST CE DICTIONNAIRE QUI JUSTIFIE LE REFUS DE PRÉDIRE. Tant que
    `transitions_observees` reste sous le seuil, aucun modèle ne peut être
    calibré, et l'afficher noir sur blanc vaut mieux qu'un « bientôt ».
    """
    out = {"mesures": 0, "articles": 0, "depuis": None,
           "transitions_observees": 0}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT asset_id), MIN(mesure_le)"
                " FROM roblox_mesures") as cur:
                r = await cur.fetchone()
            if r:
                out["mesures"] = int(r[0] or 0)
                out["articles"] = int(r[1] or 0)
                out["depuis"] = r[2]
            #  Une transition OBSERVÉE — c'est-à-dire vue passer entre deux
            #  relevés, la seule qui vaille comme exemple d'entraînement.
            async with db.execute(
                "SELECT COUNT(*) FROM roblox_transitions WHERE de='normal'"
            ) as cur:
                r = await cur.fetchone()
            out["transitions_observees"] = int(r[0] or 0) if r else 0
    except Exception as ex:
        _log(f"[roblox_veille etat_serie] {ex}")
    return out


#  ⚠️ LE SEUIL EN DESSOUS DUQUEL ON REFUSE DE PRÉDIRE, ET IL EST ASSUMÉ.
#  Un modèle de classification déséquilibrée n'a rien à dire avec moins de
#  quelques dizaines de cas positifs : en dessous, la « probabilité » ne
#  mesurerait que le bruit de l'échantillon. Roblox a fait 36 bascules sur
#  toute l'année 2025 — atteindre ce seuil prendra des mois, et c'est
#  exactement l'information que le propriétaire doit avoir plutôt qu'un
#  pourcentage inventé.
MIN_TRANSITIONS_POUR_MODELE = 30


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


# ═══════════════════════════════════════════════════════════════════════════════
#  La file d'attente d'envoi
# ═══════════════════════════════════════════════════════════════════════════════

#  Combien d'essais avant d'abandonner une fiche. Au-delà, ce n'est plus un
#  incident réseau : c'est un salon supprimé ou une permission retirée, et
#  réessayer indéfiniment ferait grossir la file sans fin.
MAX_ESSAIS_ENVOI = 5


def etat_transition(article: dict) -> tuple[str, str]:
    """(de, vers) — ce que cette fiche annonce. Sert de clé d'unicité.

    Volontairement GROSSIER : ce couple doit rester stable d'un passage à
    l'autre, sinon la contrainte d'unicité ne protège plus de rien. Le prix ou
    les favoris n'y entrent donc pas.
    """
    if article.get("bascule_detectee"):
        return "normal", (article.get("classe") or CLASSE_LIMITED)
    return "absent", "nouveau"


async def enfiler(guild_id: int, article: dict, flux: str) -> bool:
    """Met une fiche en file. Rend True si elle y entre pour la première fois.

    ⚠️ C'EST ICI QUE SE JOUE « JAMAIS DEUX FOIS ». L'`INSERT OR IGNORE` sur la
    contrainte UNIQUE(guild_id, asset_id, de, vers) fait qu'une transition
    revue à chaque passage — ce qui arrive tout le temps, la détection étant
    rejouée — n'ajoute rien. Pas de compteur, pas de cache mémoire : la base.
    """
    de, vers = etat_transition(article)
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO roblox_transitions(guild_id, asset_id,"
                " flux, de, vers, detecte_le, charge) VALUES(?,?,?,?,?,?,?)",
                (int(guild_id), int(article["asset_id"]), str(flux), de, vers,
                 datetime.now(timezone.utc).isoformat(),
                 json.dumps(article, ensure_ascii=False)))
            await db.commit()
            return bool(cur.rowcount)
    except Exception as ex:
        _log(f"[roblox_veille enfiler] {ex}")
        return False


async def a_envoyer(guild_id: int, limite: int = 12) -> list[dict]:
    """Les fiches en attente, la plus ancienne d'abord.

    Rend des dicts `{"id", "flux", "article"}`. La charge est relue depuis la
    base : après un redémarrage, elle suffit à publier sans rappeler Roblox.
    """
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                #  ⚠️ LES BASCULES D'ABORD, quel que soit leur âge en file.
                #  `PRIORITE_FLUX` dit qu'une bascule est l'information la plus
                #  forte ; un tri purement chronologique la faisait attendre
                #  derrière un arriéré de nouveautés — mesuré en réfutation :
                #  49 fiches devant elle, soit 2 h 30 de retard sur un
                #  événement dont tout l'intérêt est d'être frais.
                "SELECT id, flux, charge, essais FROM roblox_transitions"
                " WHERE guild_id=? AND envoye_le IS NULL AND essais<?"
                " ORDER BY CASE flux WHEN 'bascules' THEN 0 ELSE 1 END,"
                "  detecte_le ASC, id ASC LIMIT ?",
                (int(guild_id), MAX_ESSAIS_ENVOI, int(limite))) as cur:
                for row in await cur.fetchall():
                    try:
                        out.append({"id": int(row[0]), "flux": str(row[1]),
                                    "article": json.loads(row[2]),
                                    #  Sert de jeton de réservation : voir
                                    #  `reserver`.
                                    "essais": int(row[3] or 0)})
                    except Exception:
                        #  Une charge illisible ne doit pas bloquer la file
                        #  entière : on la compte comme un essai raté.
                        await noter_echec_envoi(int(row[0]), "charge illisible")
    except Exception as ex:
        _log(f"[roblox_veille a_envoyer] {ex}")
    return out


async def reserver(ligne_id: int, essais_vus: int) -> bool:
    """Réserve la fiche AVANT de l'envoyer. Rend True si on l'a bien prise.

    ⚠️ POURQUOI CETTE FONCTION EXISTE — J'AVAIS ÉCRIT LE CONTRAIRE, ET C'ÉTAIT
    FAUX. Un commentaire affirmait que la contrainte UNIQUE de
    `roblox_transitions` garantissait « jamais deux annonces ». Elle ne
    garantit rien de tel : elle empêche d'ENFILER deux fois, pas d'ENVOYER deux
    fois. `a_envoyer` n'était qu'un SELECT, sans réservation — la boucle et le
    bouton « Relever maintenant » pouvaient tirer les MÊMES lignes et publier
    deux fois. Réfutation du 30/08, rejouée en exécution : 6 messages pour une
    file de 3.

    LE MÉCANISME. `essais` sert de jeton : on ne prend la ligne que si elle
    porte encore la valeur qu'on a lue. Deux tireurs concurrents lisent la même
    valeur, un seul réussit son UPDATE — l'autre voit `rowcount == 0` et passe.

    ⚠️ CE QUE ÇA NE GARANTIT PAS, ET IL FAUT LE DIRE. Le compteur monte AVANT
    l'envoi. Une coupure entre un envoi réussi et son enregistrement laisse
    donc la fiche non marquée : elle repartira, et il y aura UN doublon. C'est
    le prix d'une file « au moins une fois », et il est borné par
    `MAX_ESSAIS_ENVOI`. L'inverse — marquer avant d'envoyer — perdrait la fiche
    en silence, ce qui est pire : un doublon se voit, une perte non.
    """
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE roblox_transitions SET essais=?"
                " WHERE id=? AND envoye_le IS NULL AND essais=?",
                (int(essais_vus) + 1, int(ligne_id), int(essais_vus)))
            await db.commit()
            return bool(cur.rowcount)
    except Exception as ex:
        _log(f"[roblox_veille reserver] {ex}")
        #  Fail-CLOSED : dans le doute on n'envoie pas. Mieux vaut une fiche
        #  retardée d'un passage qu'un doublon.
        return False


async def marquer_envoye(ligne_id: int, message_id: int | None) -> bool:
    """La fiche est partie. On garde l'identifiant du message Discord.

    ⚠️ REND UN BOOLÉEN, ET L'APPELANT DOIT LE REGARDER. La version précédente
    avalait son exception et rendait `None` : une base verrouillée laissait la
    ligne non marquée pendant que le bilan comptait « 1 publication réelle » —
    et la fiche repartait au passage suivant. Un échec ici est la SEULE trace
    d'un doublon à venir, il ne doit pas être muet.
    """
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE roblox_transitions SET envoye_le=?, message_id=?"
                " WHERE id=?",
                (datetime.now(timezone.utc).isoformat(),
                 int(message_id) if message_id else None, int(ligne_id)))
            await db.commit()
        return True
    except Exception as ex:
        _log(f"[roblox_veille marquer_envoye] ⚠️ la fiche {ligne_id} est PARTIE "
             f"mais n'a pas pu être marquée — elle repartira au prochain "
             f"passage (doublon) : {ex}")
        return False


async def noter_echec_envoi(ligne_id: int, motif: str) -> None:
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE roblox_transitions SET essais=essais+1, dernier_echec=?"
                " WHERE id=?", (str(motif)[:200], int(ligne_id)))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_veille noter_echec_envoi] {ex}")


async def relancer_abandonnees(guild_id: int) -> int:
    """Remet à zéro le compteur d'essais des fiches abandonnées. Rend le nombre.

    ⚠️ POURQUOI CE GESTE EXISTE. Une fiche qui a échoué `MAX_ESSAIS_ENVOI` fois
    — salon supprimé, permission retirée, Discord indisponible deux heures —
    sort définitivement de `a_envoyer`, et RIEN dans le dépôt ne la ramenait :
    `enfiler` refuse de la réinsérer (contrainte d'unicité) et
    « ♻️ Tout republier » n'efface que `roblox_publies`. La panne réparée, la
    fiche restait morte. C'est le seul chemin de retour.
    """
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE roblox_transitions SET essais=0, dernier_echec=NULL"
                " WHERE guild_id=? AND envoye_le IS NULL AND essais>=?",
                (int(guild_id), MAX_ESSAIS_ENVOI))
            await db.commit()
            return int(cur.rowcount or 0)
    except Exception as ex:
        _log(f"[roblox_veille relancer_abandonnees] {ex}")
        return 0


async def etat_file(guild_id: int | None = None) -> dict:
    """Ce que contient la file. Sert au bilan et à la commande de santé."""
    out = {"attente": 0, "envoyees": 0, "abandonnees": 0, "plus_vieille": None}
    ou, args = "", []
    if guild_id is not None:
        ou, args = " WHERE guild_id=?", [int(guild_id)]
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT"
                "  SUM(CASE WHEN envoye_le IS NULL AND essais<? THEN 1 ELSE 0 END),"
                "  SUM(CASE WHEN envoye_le IS NOT NULL THEN 1 ELSE 0 END),"
                "  SUM(CASE WHEN envoye_le IS NULL AND essais>=? THEN 1 ELSE 0 END),"
                "  MIN(CASE WHEN envoye_le IS NULL THEN detecte_le END)"
                " FROM roblox_transitions" + ou,
                    [MAX_ESSAIS_ENVOI, MAX_ESSAIS_ENVOI] + args) as cur:
                row = await cur.fetchone()
        if row:
            out["attente"] = int(row[0] or 0)
            out["envoyees"] = int(row[1] or 0)
            out["abandonnees"] = int(row[2] or 0)
            out["plus_vieille"] = row[3]
    except Exception as ex:
        _log(f"[roblox_veille etat_file] {ex}")
    return out


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
        #  ⚠️ « bascules » EST EXCLU, ET C'EST LE CORRECTIF DU 30/08/2026.
        #
        #  LE DÉFAUT. Cette boucle marquait les TROIS flux. Or `age_publiable`
        #  ci-dessus n'épargne que ce qui a moins de six heures — mesuré le
        #  30/08 : ZÉRO article sur 964, le compte Roblox n'ayant rien créé
        #  depuis 38 jours. Donc les 964 articles du catalogue étaient marqués
        #  « déjà publié » dans `bascules` dès l'allumage, et `publiable_dans`
        #  les refusait TOUS pendant 180 jours (la purge de `roblox_publies`).
        #  Le propriétaire : « les accessoires qui viennent de passer Limited
        #  ne marchent pas ». Ils ne pouvaient pas : la porte était condamnée
        #  avant que le premier Limited n'existe.
        #
        #  POURQUOI L'EXCLUSION EST LA BONNE FORME. Une amorce sert à ne pas
        #  déverser un ÉTAT existant (« ces 964 articles existent déjà »). Une
        #  bascule n'est pas un état, c'est un ÉVÉNEMENT FUTUR : elle ne peut
        #  pas être « déjà sortie » avant de s'être produite. Et elle n'a pas
        #  besoin d'être protégée ici, parce qu'`age_publiable(a, "bascules")`
        #  n'accepte QUE `bascule_detectee`, posé uniquement quand un article
        #  connu non collectionnable le devient sous nos yeux. Un Limited
        #  présent au premier relevé n'obtient jamais ce marqueur.
        #
        #  `surveiller` reste marqué : c'est bien un état, comme `nouveautes`.
        for flux in ("nouveautes", "surveiller"):
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
            #  ⚠️ ON NE PURGE QUE CE QUI EST PARTI, JAMAIS CE QUI ATTEND.
            #  Effacer une ligne en attente la ferait remettre en file au
            #  passage suivant — donc republier. La contrainte d'unicité ne
            #  protège que tant que la ligne existe.
            _vieux = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
            await db.execute(
                "DELETE FROM roblox_transitions WHERE envoye_le IS NOT NULL"
                " AND envoye_le < ?", (_vieux,))
            #  ⚠️ ET LES ABANDONNÉES, QUI FUYAIENT POUR TOUJOURS. Une ligne à
            #  `essais >= MAX_ESSAIS_ENVOI` n'est ni partie ni en attente :
            #  aucune requête ne la touchait, aucune fonction ne remettait son
            #  compteur à zéro. Mesuré en réfutation : encore là après dix ans
            #  simulés. On les efface au même âge que le reste — la fiche est
            #  perdue de toute façon, autant que la table ne le soit pas.
            await db.execute(
                "DELETE FROM roblox_transitions WHERE envoye_le IS NULL"
                " AND essais >= ? AND detecte_le < ?",
                (MAX_ESSAIS_ENVOI, _vieux))
            #  La série temporelle : on garde plus longtemps que le reste,
            #  parce que c'est justement son ancienneté qui fait sa valeur —
            #  mais pas indéfiniment. 400 jours couvrent l'horizon de 90 jours
            #  demandé, avec la marge d'un cycle annuel complet.
            await db.execute(
                "DELETE FROM roblox_mesures WHERE mesure_le < ?",
                ((datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),))
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
