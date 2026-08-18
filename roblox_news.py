"""roblox_news.py — Veille d'actualité Roblox : Studio, UGC, développeurs, événements.

Voir `ROBLOX.md` (cahier des charges) et `rapports/roblox-veille-actualites-plan.json`
(97 agents, 71 sources réellement ouvertes, 9 écartées comme mortes).

═══════════════════════════════════════════════════════════════════════════════
CE QUI EST COUVERT, ET CE QUI NE PEUT PAS L'ÊTRE
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire veut « absolument tout ». Honnêtement :

COUVERT — Studio (bêtas, pilotes, outils), moteur et API, UGC et Marketplace,
développeurs, politique et CGU, événements officiels, état de la plateforme.

PAS COUVERT — « tous les artistes » n'existe PAS comme flux chez Roblox. Mesuré :
la catégorie `clothing` donne 0 billet officiel sur 15 (que des petites annonces
« [FOR HIRE] designer 2D »), et le tag `ugc` ne renvoie aucun sujet. Il n'y a
aucune catégorie dédiée aux créateurs 2D, vêtements et accessoires. Le domaine
« artistes » sera donc un sous-ensemble du reste, moins fourni — ce n'est pas un
défaut du bot, c'est l'absence de la source.

═══════════════════════════════════════════════════════════════════════════════
LA CONTRAINTE QUI COMMANDE TOUTE L'ARCHITECTURE
═══════════════════════════════════════════════════════════════════════════════
Mesuré : c'est la CONCURRENCE qui déclenche le pare-feu d'AWS, pas le volume.
60 requêtes en parallèle passent ; 200 en salves rendent des réponses vides et
bloquent l'IP 21 à 41 secondes.

D'où la règle : **une source à la fois, jamais de rafale parallèle**. Chaque
source porte sa propre échéance ; un passage n'en interroge qu'une poignée.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import roblox_news_contenu as contenu

#  ⚠️ DOMAINES EN DUR — même règle que roblox_veille : un lien publié par ce bot
#  est RECONSTRUIT, jamais recopié d'une réponse. Voir ROBLOX.md §1.
DOMAINE_FORUM = "https://devforum.roblox.com"

#  Sources vérifiées le 12/08/2026 par appel réel. Le champ `domaine` sert au
#  classement et au routage ; `cle` identifie la source dans le registre de santé.
#
#  ⚠️ Les identifiants de catégorie sont ceux du forum Discourse de Roblox,
#  relevés dans les réponses. Ne pas les « corriger » de mémoire.
#  ⚠️ DOMAINES EN DUR pour chaque famille de source. Un lien publié est
#  RECONSTRUIT (domaine + identifiant validé), jamais recopié d'une réponse.
DOMAINE_PRESSE = "https://ir.roblox.com"
DOMAINE_NEWSROOM = "https://about.roblox.com"

#  `format` commande le lecteur : « discourse » (forum), « rss » (communiqués),
#  « newsroom » (liste HTML + page article). Chaque source garde son rythme.
SOURCES = [
    {"cle": "annonces", "domaine": "Annonces", "format": "discourse",
     "url": f"{DOMAINE_FORUM}/c/updates/announcements/36.json?order=created",
     "minutes": 30},
    {"cle": "notes", "domaine": "Studio & moteur", "format": "discourse",
     "url": f"{DOMAINE_FORUM}/c/updates/release-notes/62.json?order=created",
     "minutes": 30},
    {"cle": "alertes", "domaine": "Politique & sécurité", "format": "discourse",
     "url": f"{DOMAINE_FORUM}/c/updates/news-alerts/193.json?order=created",
     "minutes": 60},
    {"cle": "communaute", "domaine": "Événements", "format": "discourse",
     "url": f"{DOMAINE_FORUM}/c/updates/community/90.json?order=created",
     "minutes": 60},
    {"cle": "ressources", "domaine": "Développeurs", "format": "discourse",
     "url": f"{DOMAINE_FORUM}/c/resources/roblox-staff/278.json?order=created",
     "minutes": 120},
    #  ── Sources OFFICIELLES hors forum — ajoutées le 16/08/2026, chacune
    #     ouverte et lue ce jour-là (HTTP 200, extrait réel à l'appui).
    #
    #  ⚠️ « presse » (ir.roblox.com/rss/pressrelease.aspx) A ÉTÉ RETIRÉE le
    #  18/08 : le site est derrière Cloudflare, qui bloque les IP d'hébergeur.
    #  Mesuré : HTTP 200 depuis un poste résidentiel quel que soit le
    #  User-Agent, HTTP 403 ×3 depuis Railway (capture du propriétaire). Une
    #  source structurellement injoignable en production n'est pas une source :
    #  elle est un voyant rouge permanent qui finit par masquer les vraies
    #  pannes. Le lecteur RSS reste dans ce module (`_relever_rss`,
    #  `lien_presse`, testé) pour le jour où l'IP passerait, ou pour un autre
    #  flux RSS officiel. Les annonces produit sont couvertes par le newsroom ;
    #  les résultats financiers sont hors du périmètre créateurs.
    #  ⚠️ LA SOURCE FRANÇAISE OFFICIELLE — AVANT la version anglaise, exprès :
    #  même clé de dédup, donc la première servie gagne, et c'est le français. « Salle de presse | Roblox » — même
    #  contenu que le newsroom, traduit par Roblox. On ne traduit rien : on
    #  cite. Demande du propriétaire : « des actualités US, français ».
    {"cle": "newsroom_fr", "domaine": "Salle de presse (FR)", "format": "newsroom",
     "url": f"{DOMAINE_NEWSROOM}/fr/newsroom", "prefixe": "/fr/newsroom/",
     "minutes": 120},
    {"cle": "newsroom", "domaine": "Newsroom Roblox", "format": "newsroom",
     "url": f"{DOMAINE_NEWSROOM}/newsroom", "prefixe": "/newsroom/",
     "minutes": 120},
]

#  Combien de pages ARTICLE du newsroom on ouvre au plus par relevé et par
#  langue. En régime établi, c'est 0 à 2 (seuls les slugs jamais vus). Au
#  premier passage après un redémarrage, ce plafond borne le rattrapage.
MAX_ARTICLES_NEWSROOM_PAR_RELEVE = 6

#  Cache des pages article déjà lues : {slug: billet}. Une page ne se lit
#  qu'une fois par vie du processus. Borné pour ne pas grossir sans fin.
_cache_newsroom: dict[str, dict] = {}
MAX_CACHE_NEWSROOM = 400

#  Cache des CORPS de billets du forum : {topic_id: billet enrichi}. Même
#  logique — une page `/t/{id}.json` par billet, une fois, puis traduction une
#  fois. Sans ce cache, chaque passage retraduirait les mêmes billets.
_cache_forum: dict[int, dict] = {}
MAX_CACHE_FORUM = 400


def _memoriser(cache: dict, cle, valeur, maximum: int) -> None:
    if len(cache) >= maximum:
        cache.pop(next(iter(cache)))
    cache[cle] = valeur

MAX_BILLETS_PAR_PASSAGE = 5
MAX_PUBLIES_GARDES = 4000

#  ⚠️ FRAÎCHEUR MAXIMALE — NE PAS RETIRER CE GARDE-FOU.
#
#  Mesuré le 12/08/2026 sur les vraies réponses : les catégories lentes portent
#  en haut de liste des billets de 73, 137, 277 et jusqu'à 337 JOURS. Elles
#  publient peu, donc leur « dernier billet » peut être très ancien.
#
#  La déduplication seule ne suffit PAS à s'en protéger : elle repose sur la
#  base. Une base neuve, un serveur qui active le système pour la première fois,
#  une restauration de sauvegarde — et le salon reçoit d'un coup une alerte
#  vieille d'un an annoncée comme une nouvelle.
#
#  Le propriétaire l'a dit mot pour mot : « faut pas que les news soient
#  dépassées depuis un moment ». Ce plafond est indépendant de la base : un
#  billet trop vieux n'est JAMAIS publié, quel que soit l'état du reste.
#
#  30 jours : mesuré, ça laisse passer le billet le plus récent de CHAQUE
#  catégorie (le plus lent est à 17 jours) et bloque tous les autres.
FRAICHEUR_MAX_JOURS = 30

_get_db = None
_cfg = None
_db_set = None
_log = print


def setup(*, get_db, cfg, db_set, log=None):
    global _get_db, _cfg, _db_set, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    if log is not None:
        _log = log


CLES_DEFAUT = {
    "roblox_news_enabled": False,
    "roblox_news_salon": 0,
    "roblox_news_amorcee": "",
}


async def config(guild_id: int) -> dict:
    try:
        c = await _cfg(guild_id)
    except Exception as ex:
        _log(f"[roblox_news config] {ex}")
        c = {}
    out = dict(CLES_DEFAUT)
    for k in out:
        if k in c:
            out[k] = c[k]
    return out


async def actif(guild_id: int) -> bool:
    c = await config(guild_id)
    #  `.get` : une config partielle ne doit jamais faire tomber la garde,
    #  elle doit rendre « éteint » — fail-closed sur le doute.
    return bool(c.get("roblox_news_enabled")
                and int(c.get("roblox_news_salon") or 0))


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_news_publies("
            " guild_id INTEGER NOT NULL,"
            " topic_id INTEGER NOT NULL,"
            " publie_le TEXT NOT NULL,"
            " PRIMARY KEY(guild_id, topic_id))")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_news_sante("
            " cle TEXT PRIMARY KEY,"
            " dernier_essai TEXT, dernier_succes TEXT,"
            " dernier_code INTEGER, echecs INTEGER NOT NULL DEFAULT 0)")
        await db.commit()


def lien_billet(topic_id, slug: str | None = None) -> str | None:
    """L'URL d'un billet, RECONSTRUITE à partir d'un identifiant entier.

    Jamais recopiée d'une réponse. Le `slug` n'est qu'un confort de lecture :
    Discourse résout un billet sur son seul identifiant, donc un slug douteux
    n'est pas repris.
    """
    try:
        n = int(topic_id)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return f"{DOMAINE_FORUM}/t/{n}"


def _ouvrir():
    """Session HTTP dédiée, avec un User-Agent nommé.

    ⚠️ Ce module n'exige AUCUNE session injectée — la première version de
    `roblox_veille` le faisait, le câblage passait None, et le système sortait
    avant tout appel réseau. On n'y revient pas.
    """
    import aiohttp
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        headers={"User-Agent": "BotModerationDiscord/1.0 (veille Roblox)",
                 "Accept": "application/json"})


async def _noter_sante(cle: str, code: int | None) -> int:
    maintenant = datetime.now(timezone.utc).isoformat()
    ok = code is not None and 200 <= code < 300
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT echecs FROM roblox_news_sante WHERE cle=?", (cle,)) as cur:
                row = await cur.fetchone()
            echecs = 0 if ok else (int(row[0]) if row else 0) + 1
            await db.execute(
                "INSERT INTO roblox_news_sante(cle, dernier_essai, dernier_succes,"
                " dernier_code, echecs) VALUES(?,?,?,?,?)"
                " ON CONFLICT(cle) DO UPDATE SET dernier_essai=?,"
                "  dernier_succes=COALESCE(?, dernier_succes), dernier_code=?, echecs=?",
                (cle, maintenant, maintenant if ok else None, code, echecs,
                 maintenant, maintenant if ok else None, code, echecs))
            await db.commit()
        return echecs
    except Exception as ex:
        _log(f"[roblox_news _noter_sante] {ex}")
        return 0


async def echue(source: dict) -> bool:
    """La source est-elle à relever maintenant, selon son propre rythme ?

    ⚠️ `minutes` était documenté (« chaque source porte sa propre échéance »)
    et jamais lu : tout était interrogé toutes les 30 minutes. Une page
    newsroom pèse 560 Ko pour deux articles par mois. On lit `dernier_essai`
    dans la table de santé ; jamais essayé = échue. Fail-open : une base
    illisible ne doit pas faire taire une source.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT dernier_essai FROM roblox_news_sante WHERE cle=?",
                (source["cle"],)) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            return True
        d = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d) >= timedelta(
            minutes=int(source.get("minutes") or 30))
    except Exception as ex:
        _log(f"[roblox_news echue {source.get('cle')}] {ex}")
        return True


async def relever(source: dict, forcer: bool = False) -> dict:
    """Lit une source. Rend {"billets": [...], "code": int|None, "sautee": bool}.

    `forcer=True` ignore la cadence — c'est ce que fait « Relever maintenant ».
    Ne lève jamais : une panne de veille ne doit pas gêner la modération.
    """
    out = {"billets": [], "code": None, "domaine": source["domaine"],
           "sautee": False}
    if not forcer and not await echue(source):
        out["sautee"] = True
        return out
    fmt = source.get("format", "discourse")
    try:
        if fmt == "discourse":
            await _relever_discourse(source, out)
        elif fmt == "rss":
            await _relever_rss(source, out)
        elif fmt == "newsroom":
            await _relever_newsroom(source, out)
        else:
            _log(f"[roblox_news {source['cle']}] format inconnu : {fmt}")
    except Exception as ex:
        _log(f"[roblox_news {source['cle']}] {type(ex).__name__}: {ex}")
    await _noter_sante(source["cle"], out["code"])
    return out


async def _relever_discourse(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status != 200:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
                return
            data = await r.json()
            frais = _normaliser(data, source["domaine"])
            #  Tous les titres frais — corps ou pas — servent à relier les
            #  accessoires à leur annonce (voir `billets_lies`).
            for b in frais:
                _memoriser_recent(b)

        #  ⚠️ LE CORPS, BILLET PAR BILLET — c'est ce qui rend la fiche complète.
        #  `/t/{id}.json` porte le premier post en HTML (`cooked`) : texte,
        #  images pleine taille, vidéos. On ne lit que les plus récents, dans
        #  la limite du plafond par passage, avec cache et pause. Un billet
        #  dont le corps n'est pas encore lu ATTEND le passage suivant : mieux
        #  vaut une fiche complète dans 30 min qu'une fiche vide maintenant.
        billets, pointeurs, lus = [], 0, 0
        for b in frais:
            enrichi = _cache_forum.get(b["topic_id"])
            if enrichi is None:
                if lus >= MAX_BILLETS_PAR_PASSAGE:
                    break
                lus += 1
                try:
                    async with sess.get(
                            f"{DOMAINE_FORUM}/t/{int(b['topic_id'])}.json") as rt:
                        if rt.status != 200:
                            _log(f"[roblox_news {source['cle']} corps "
                                 f"{b['topic_id']}] HTTP {rt.status}")
                            continue
                        tj = await rt.json()
                    posts = ((tj.get("post_stream") or {}).get("posts") or [])
                    cooked = str((posts[0] if posts else {}).get("cooked") or "")
                except Exception as ex:
                    _log(f"[roblox_news {source['cle']} corps {b['topic_id']}] {ex}")
                    continue
                finally:
                    await asyncio.sleep(1.5)
                enrichi = await contenu.enrichir_billet(dict(b), cooked, "en")
                _memoriser(_cache_forum, b["topic_id"], enrichi, MAX_CACHE_FORUM)
                #  Avec le corps, la mise en relation devient bien plus sûre.
                _memoriser_recent(enrichi)
            if enrichi.get("pointeur"):
                #  « Allez voir ce lien » : écarté, et compté pour le dire.
                pointeurs += 1
                continue
            billets.append(enrichi)
        out["billets"] = billets
        out["pointeurs"] = pointeurs


# ═══════════════════════════════════════════════════════════════════════════════
#  Communiqués officiels — RSS 2.0 (ir.roblox.com)
# ═══════════════════════════════════════════════════════════════════════════════

def _date_rfc2822(txt) -> str | None:
    """« Thu, 30 Jul 2026 16:05:00 -0400 » → ISO. `None` si illisible."""
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(str(txt))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def lien_presse(url_brute) -> str | None:
    """Reconstruit le lien d'un communiqué : domaine en dur + chemin VALIDÉ.

    Le chemin réel est `/news/news-details/AAAA/Slug/`. On n'accepte que cette
    forme, année sur 4 chiffres et slug alphanumérique — tout le reste rend
    `None`, et le billet part sans lien. C'est la règle ROBLOX.md §1 : le
    domaine ne vient jamais d'une réponse.
    """
    import re
    #  ⚠️ La forme RÉELLE se termine par `/default.aspx` — mesuré le 16/08 :
    #  `…/2026/Roblox-Reports-Second-Quarter-2026-Financial-Results/default.aspx`.
    #  La première regex l'ignorait : chaque communiqué partait sans slug, donc
    #  était écarté, et la source affichait « 0 frais » en pleine santé.
    m = re.match(
        r"^https?://ir\.roblox\.com/news/news-details/(\d{4})/([A-Za-z0-9\-]+)"
        r"/(?:default\.aspx)?$",
        str(url_brute or "").strip())
    if not m:
        return None
    return f"{DOMAINE_PRESSE}/news/news-details/{m.group(1)}/{m.group(2)}/default.aspx"


def _normaliser_rss(texte: str, domaine: str) -> list[dict]:
    """Un flux RSS 2.0 → billets. Sans dépendance : `xml.etree` suffit."""
    import xml.etree.ElementTree as ET
    out = []
    try:
        racine = ET.fromstring(texte)
    except Exception as ex:
        _log(f"[roblox_news rss] XML illisible : {ex}")
        return out
    for item in racine.iter("item"):
        try:
            titre = (item.findtext("title") or "").strip()
            lien_brut = (item.findtext("link") or "").strip()
            date = _date_rfc2822(item.findtext("pubDate"))
            if _trop_vieux(date):
                continue
            lien = lien_presse(lien_brut)
            if not lien:
                continue
            #  L'identifiant de dédup est le SLUG du lien validé — stable, et
            #  indépendant du titre (qui peut être corrigé après publication).
            #  ⚠️ Pris dans le chemin AVANT `/default.aspx` : la première
            #  version prenait le dernier segment du lien, c'est-à-dire
            #  « default.aspx » pour TOUS les communiqués — même clé partout,
            #  un seul aurait jamais été publié. Attrapé par un test.
            import re as _re
            m_slug = _re.search(r"/news-details/\d{4}/([A-Za-z0-9\-]+)/", lien)
            slug = m_slug.group(1) if m_slug else None
            if not slug:
                continue
            desc_html = (item.findtext("description") or "").strip()
            import re
            desc = re.sub(r"<[^>]+>", " ", desc_html)
            desc = re.sub(r"\s+", " ", desc).strip()
            out.append({
                "topic_id": f"presse:{slug}",
                "titre": titre[:200] or "—",
                "domaine": domaine,
                "cree_le": date,
                "extrait": (desc[:300] or None),
                "tags": [],
                "lien": lien,
                #  Le communiqué ENTIER : `enrichir_billet` en tirera
                #  l'essentiel et la traduction. Gardé ici, consommé par
                #  `_relever_rss`, jamais publié tel quel.
                "_html": desc_html,
            })
        except Exception:
            continue
    out.sort(key=lambda b: str(b.get("cree_le") or ""), reverse=True)
    return out


async def _relever_rss(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status != 200:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
                return
            bruts = _normaliser_rss(await r.text(), source["domaine"])
    billets, pointeurs = [], 0
    for b in bruts[:MAX_BILLETS_PAR_PASSAGE]:
        enrichi = _cache_forum.get(b["topic_id"])
        if enrichi is None:
            enrichi = await contenu.enrichir_billet(dict(b), b.pop("_html", ""), "en")
            enrichi.pop("_html", None)
            _memoriser(_cache_forum, b["topic_id"], enrichi, MAX_CACHE_FORUM)
        _memoriser_recent(enrichi)
        if enrichi.get("pointeur"):
            pointeurs += 1
            continue
        billets.append(enrichi)
    out["billets"] = billets
    out["pointeurs"] = pointeurs


# ═══════════════════════════════════════════════════════════════════════════════
#  Newsroom — liste HTML pour les identifiants, page article pour la date
# ═══════════════════════════════════════════════════════════════════════════════

def lien_newsroom(chemin, prefixe: str) -> str | None:
    """Reconstruit le lien d'un article du newsroom : domaine + chemin VALIDÉ.

    Forme acceptée : `{prefixe}AAAA/MM/slug`, où `prefixe` vaut `/newsroom/`
    ou `/fr/newsroom/`. Année 4 chiffres, mois 2 chiffres, slug minuscules /
    chiffres / tirets. Le reste rend `None`.
    """
    import re
    p = str(chemin or "").strip()
    if not p.startswith(prefixe):
        return None
    reste = p[len(prefixe):]
    m = re.match(r"^(\d{4})/(\d{2})/([a-z0-9][a-z0-9\-]{2,160})$", reste)
    if not m:
        return None
    return f"{DOMAINE_NEWSROOM}{prefixe}{m.group(1)}/{m.group(2)}/{m.group(3)}"


def _slugs_newsroom(html: str, prefixe: str) -> list[str]:
    """Les chemins d'article de la page de liste, dédoublonnés, dans l'ordre
    d'apparition (le plus récent est en tête sur la page)."""
    import re
    vus, out = set(), []
    motif = re.escape(prefixe) + r"\d{4}/\d{2}/[a-z0-9\-]+"
    for m in re.finditer(r'href="(' + motif + r')"', html):
        p = m.group(1)
        if p not in vus:
            vus.add(p)
            out.append(p)
    return out


def _lire_page_article(html: str) -> dict:
    """Date, titre et résumé d'une page article, depuis ses balises `meta`.

    Mesuré le 16/08 sur un article FR : `article:published_time` =
    2026-08-04T12:00:00.000Z, `og:title` en français. Aucune balise
    `datePublished` ni `<time>` : ce sont les seules qu'on ait, et elles
    suffisent. Un titre HTML-échappé est déséchappé (« l&#x27;âge »).
    """
    import html as _html
    import re
    def meta(prop):
        m = (re.search(r'property="' + prop + r'"\s+content="([^"]*)"', html)
             or re.search(r'content="([^"]*)"\s+property="' + prop + r'"', html))
        return _html.unescape(m.group(1)).strip() if m else None
    titre = meta("og:title") or ""
    #  ⚠️ « … | Roblox » : le suffixe du site, pas le titre. Il s'affichait
    #  sur chaque fiche — vu sur la capture du propriétaire.
    titre = re.sub(r"\s*\|\s*Roblox\s*$", "", titre).strip()
    art = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
    return {"date": meta("article:published_time"),
            "titre": titre or None,
            "extrait": meta("og:description"),
            "image": meta("og:image"),
            #  Le corps de l'article : c'est lui qui donne l'essentiel et les
            #  images du texte. Sans balise <article>, on ne devine rien.
            "corps_html": art.group(1) if art else ""}


async def _relever_newsroom(source: dict, out: dict) -> None:
    prefixe = source["prefixe"]
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status != 200:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
                return
            chemins = _slugs_newsroom(await r.text(), prefixe)

        billets, ouverts = [], 0
        for chemin in chemins:
            lien = lien_newsroom(chemin, prefixe)
            if not lien:
                continue
            slug = chemin[len(prefixe):]
            #  ⚠️ CLÉ PAR SOURCE, PAS PAR SLUG. Le slug est IDENTIQUE en EN et
            #  en FR (`2026/08/beyond-selfie-…`) : avec un cache par slug seul,
            #  la salle de presse FR ressortait le billet ANGLAIS déjà lu par
            #  le newsroom EN — titre anglais, lien anglais. Mesuré le 16/08.
            cle_cache = f"{source['cle']}:{slug}"
            b = _cache_newsroom.get(cle_cache)
            if b is None:
                #  Une page article, UNE fois, avec pause : c'est la
                #  concurrence que le pare-feu punit.
                if ouverts >= MAX_ARTICLES_NEWSROOM_PAR_RELEVE:
                    continue
                ouverts += 1
                try:
                    async with sess.get(lien) as ra:
                        if ra.status != 200:
                            continue
                        page = _lire_page_article(await ra.text())
                except Exception as ex:
                    _log(f"[roblox_news {source['cle']} {slug[:40]}] {ex}")
                    continue
                finally:
                    await asyncio.sleep(1.5)
                b = {
                    #  ⚠️ CLÉ DE DÉDUP COMMUNE AUX DEUX LANGUES. Le newsroom EN
                    #  et la salle de presse FR publient le MÊME article sous le
                    #  même slug. Avec une clé par source, il sortait deux fois
                    #  dans le salon. Une seule clé, et la source FR passe AVANT
                    #  la source EN dans `SOURCES` : le français quand Roblox
                    #  l'a traduit, l'anglais sinon — jamais les deux.
                    "topic_id": f"newsroom:{slug}",
                    "titre": (page.get("titre") or slug.rsplit("/", 1)[-1])[:200],
                    "domaine": source["domaine"],
                    "cree_le": page.get("date"),
                    "extrait": (page.get("extrait") or "")[:300] or None,
                    "tags": [],
                    "lien": lien,
                }
                #  L'essentiel, les images (og:image en tête, puis celles du
                #  texte), la langue. La salle de presse FR est en français
                #  PAR ROBLOX : elle n'est jamais traduite, on cite.
                langue = "fr" if prefixe.startswith("/fr/") else "en"
                b = await contenu.enrichir_billet(b, page.get("corps_html") or "", langue)
                if page.get("image") and contenu._domaine_autorise(page["image"]):
                    b["images"] = ([page["image"]]
                                   + [i for i in b.get("images", []) if i != page["image"]]
                                   )[:contenu.MAX_IMAGES]
                if len(_cache_newsroom) >= MAX_CACHE_NEWSROOM:
                    _cache_newsroom.pop(next(iter(_cache_newsroom)))
                _cache_newsroom[cle_cache] = b
            #  Fraîcheur : même règle que le forum, fail-closed sur une date
            #  illisible — une page sans `article:published_time` ne sort pas.
            if _trop_vieux(b.get("cree_le")):
                continue
            _memoriser_recent(b)
            billets.append(b)
    billets.sort(key=lambda x: str(x.get("cree_le") or ""), reverse=True)
    out["billets"] = billets


def _trop_vieux(quand, jours: int = FRAICHEUR_MAX_JOURS) -> bool:
    """Ce billet est-il trop ancien pour être annoncé comme une nouvelle ?

    Une date ILLISIBLE est traitée comme trop vieille — fail-closed. C'est
    l'inverse du choix fait pour les articles du catalogue, et c'est délibéré :
    ici le risque n'est pas de rater une nouveauté, c'est d'annoncer une alerte
    de sécurité vieille d'un an. Dans le doute, on se tait.
    """
    try:
        d = datetime.fromisoformat(str(quand).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days > int(jours)
    except Exception:
        return True


def _normaliser(data: dict, domaine: str) -> list[dict]:
    """Réduit une réponse Discourse aux champs qu'on sait afficher.

    Les billets ÉPINGLÉS sont écartés : ils remontent en tête indéfiniment et
    seraient republiés comme des nouveautés à chaque changement de catégorie.
    """
    out = []
    try:
        sujets = ((data.get("topic_list") or {}).get("topics") or [])
    except Exception:
        return out
    for t in sujets:
        try:
            if t.get("pinned") or t.get("pinned_globally"):
                continue
            tid = int(t.get("id") or 0)
            if tid <= 0:
                continue
            #  ⚠️ Filtre de fraîcheur appliqué DÈS LA NORMALISATION, donc avant
            #  la déduplication et avant l'amorce. Un billet trop vieux n'entre
            #  même pas dans le circuit : c'est la seule garantie qui tienne si
            #  la base est neuve ou restaurée. Voir FRAICHEUR_MAX_JOURS.
            if _trop_vieux(t.get("created_at")):
                continue
            out.append({
                "topic_id": tid,
                "titre": str(t.get("title") or "")[:200],
                "domaine": domaine,
                "cree_le": t.get("created_at"),
                "extrait": (str(t.get("excerpt") or "")[:300] or None),
                "tags": [str(x) for x in (t.get("tags") or [])][:5],
            })
        except Exception:
            continue
    out.sort(key=lambda b: str(b.get("cree_le") or ""), reverse=True)
    return out


async def deja_publie(guild_id: int, topic_id: int) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM roblox_news_publies WHERE guild_id=? AND topic_id=?",
                (guild_id, topic_id)) as cur:
                return bool(await cur.fetchone())
    except Exception:
        #  Fail-CLOSED : dans le doute on considère que c'est sorti. Mieux vaut
        #  rater un billet que noyer le salon de doublons.
        return True


async def marquer_publie(guild_id: int, topic_id: int) -> None:
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO roblox_news_publies(guild_id, topic_id,"
                " publie_le) VALUES(?,?,?)",
                (guild_id, topic_id, datetime.now(timezone.utc).isoformat()))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_news marquer_publie] {ex}")


#  ⚠️ CE QUE L'AMORCE LAISSE PASSER, ET POURQUOI.
#  La première version absorbait TOUT ce que la fenêtre de 30 jours laissait
#  entrer : le propriétaire allumait, et devait attendre le PROCHAIN billet du
#  forum pour voir une seule fiche — c'est exactement le défaut qui avait été
#  corrigé côté articles le 15/08 (« 30 articles lus, 0 fiche publiée »).
#  Demande du 16/08 : « je veux les dernières news partout ». La dernière
#  semaine sort donc au premier passage, bornée par le plafond de publications ;
#  ce qui est plus vieux est absorbé sans bruit. Sept jours = « les dernières »
#  sans déverser un mois d'archives — c'est le §« premier allumage » de
#  ROBLOX.md : une borne, jamais un mur.
AMORCE_GARDE_JOURS = 7


async def amorcer(guild_id: int) -> int:
    """Pose la borne du premier allumage. Rend le nombre de billets ABSORBÉS.

    Absorbe (marque comme déjà sortis) les billets plus vieux que
    `AMORCE_GARDE_JOURS` ; laisse les autres sortir au premier passage.
    Sans amorce du tout, le premier passage déverserait un mois d'archives.
    """
    n = 0
    for src in SOURCES:
        rel = await relever(src)
        for b in rel["billets"]:
            if _trop_vieux(b.get("cree_le"), AMORCE_GARDE_JOURS):
                await marquer_publie(guild_id, b["topic_id"])
                n += 1
        #  Une source à la fois, jamais de rafale — voir l'en-tête du module.
        await asyncio.sleep(1.5)
    try:
        await _db_set(guild_id, "roblox_news_amorcee",
                      datetime.now(timezone.utc).isoformat())
    except Exception as ex:
        _log(f"[roblox_news amorcer] {ex}")
    return n


async def oublier_publies(guild_id: int) -> int:
    """Efface les marques « déjà publié » des actualités d'une guilde.

    Le pendant du bouton ♻️ des articles : un correctif de code ne répare pas
    des données déjà écrites. Rend le nombre de marques effacées.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM roblox_news_publies WHERE guild_id=?",
                (guild_id,)) as cur:
                n = int((await cur.fetchone())[0])
            await db.execute(
                "DELETE FROM roblox_news_publies WHERE guild_id=?", (guild_id,))
            await db.commit()
        return n
    except Exception as ex:
        _log(f"[roblox_news oublier_publies] {ex}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Le lien entre un ACCESSOIRE et l'actualité qui en parle
# ═══════════════════════════════════════════════════════════════════════════════
#  Demande du propriétaire (18/08) : « pour les accessoires aussi, un affichage
#  concernant les infos de presse et les news ». Roblox annonce souvent ses
#  Limiteds et ses sorties sur le forum ou dans le newsroom. On ne CHERCHE pas
#  sur le réseau à chaque accessoire (douze requêtes par passage, pour rien la
#  plupart du temps) : on regarde ce que la veille d'actualité a DÉJÀ lu — les
#  titres de tous les billets frais, et le corps de ceux qu'elle a ouverts.
#  Rien trouvé = rien affiché. On ne fabrique pas un lien.

#  {cle: {"titre", "lien", "cree_le", "domaine", "texte"}} — alimenté à chaque
#  relevé, borné.
_recents: dict = {}
MAX_RECENTS = 300

_MOTS_VIDES = {"the", "and", "for", "with", "hat", "cap", "of", "les", "des",
               "une", "un", "le", "la", "et", "roblox", "limited", "ugc"}


def _memoriser_recent(b: dict) -> None:
    """Retient un billet pour la mise en relation avec les accessoires."""
    try:
        cle = b.get("topic_id")
        lien = b.get("lien") or lien_billet(cle)
        if not lien:
            return
        texte = " ".join(str(b.get(k) or "") for k in
                         ("titre", "titre_fr", "corps", "corps_fr", "extrait"))
        if len(_recents) >= MAX_RECENTS:
            _recents.pop(next(iter(_recents)))
        _recents[cle] = {"titre": b.get("titre_fr") or b.get("titre") or "",
                         "lien": lien, "cree_le": b.get("cree_le"),
                         "domaine": b.get("domaine"), "texte": texte.lower()}
    except Exception:
        pass


def _mots_cles(nom: str) -> list[str]:
    import re
    mots = [m for m in re.findall(r"[a-zà-ÿ0-9']{3,}", (nom or "").lower())
            if m not in _MOTS_VIDES]
    #  Les mots courts et génériques ne discriminent rien : « Red Hat » ne doit
    #  pas coller à toute annonce qui contient « red ».
    return [m for m in mots if len(m) >= 4] or mots


def billets_lies(nom: str, maximum: int = 2) -> list[dict]:
    """Les billets d'actualité récents qui parlent de cet accessoire.

    Un billet est retenu si TOUS les mots significatifs du nom (≥ 4 lettres,
    hors mots vides) apparaissent dans son titre ou son corps. Deux mots au
    moins pour éviter les faux amis — OU un seul mot s'il est long (≥ 6
    lettres, « requiem », « buxeration ») : « The Requiem » est un vrai
    Limited, et « the » ne compte pas. Un nom sans mot distinctif ne relie
    rien : on préfère se taire qu'annoncer un rapport qui n'existe pas.
    Rend [{"titre", "lien", "domaine"}], du plus récent au plus ancien.
    """
    mots = _mots_cles(nom)
    if not mots or (len(mots) < 2 and len(mots[0]) < 6):
        return []
    trouves = []
    for r in _recents.values():
        if all(m in r["texte"] for m in mots):
            trouves.append(r)
    trouves.sort(key=lambda r: str(r.get("cree_le") or ""), reverse=True)
    return [{"titre": r["titre"], "lien": r["lien"], "domaine": r["domaine"]}
            for r in trouves[:maximum]]


async def purger() -> None:
    try:
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM roblox_news_publies WHERE publie_le < ?",
                ((datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_news purger] {ex}")


async def diagnostic() -> list[dict]:
    """L'état de chaque source. Une source muette doit se voir."""
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT cle, dernier_succes, dernier_code, echecs"
                " FROM roblox_news_sante") as cur:
                for cle, succes, code, echecs in await cur.fetchall():
                    out.append({"cle": cle, "dernier_succes": succes,
                                "code": code, "echecs": int(echecs or 0)})
    except Exception as ex:
        _log(f"[roblox_news diagnostic] {ex}")
    return out
