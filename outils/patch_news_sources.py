"""Élargit la veille d'actualité aux sources OFFICIELLES hors forum.

Demande du propriétaire (16/08) : « il y a énormément d'actualités de tous
types, US, français, sur des sites très officiels de Roblox, mais rien n'est
annoncé ». Le lot A a rendu le flux vivant ; celui-ci l'élargit.

CE QUI EST AJOUTÉ — chaque source OUVERTE ET LUE le 16/08 (doctrine ROBLOX.md)
  · presse officielle    — https://ir.roblox.com/rss/pressrelease.aspx
                           RSS 2.0, dates RFC 2822, HTTP 200
  · newsroom EN          — https://about.roblox.com/newsroom
  · newsroom FR          — https://about.roblox.com/fr/newsroom
                           « Salle de presse | Roblox », HTTP 200 — la source
                           FRANÇAISE officielle. La liste ne porte ni date ni
                           titre exploitables ; la page ARTICLE porte
                           `article:published_time` et `og:title` (mesuré :
                           2026-08-04, titre en français). On lit donc la liste
                           pour les identifiants, et la page article — une
                           fois, en cache — pour la date et le titre.

CE QUI N'EST PAS AJOUTÉ, ET POURQUOI
  · le sitemap du newsroom (26 Mo) : son `lastmod` est une date de MODIFICATION
    — un article d'avril 2025 y est daté du 17/08/2026. L'utiliser republierait
    des archives comme des nouveautés ;
  · YouTube officiel : `/social add youtube` le couvre déjà, avec sa propre
    déduplication et son propre salon — ce serait un doublon ;
  · events.roblox.com : le JSON embarqué rend `startedAt: null` sur les
    premiers événements — pas de date fiable, pas de publication honnête.

LA CADENCE PAR SOURCE EST ENFIN APPLIQUÉE
`minutes` était documenté (« chaque source porte sa propre échéance ») et
jamais lu : la boucle interrogeait tout, toutes les 30 minutes. Une page
newsroom pèse 560 Ko ; la lire toutes les 30 min pour deux articles par mois
serait du gaspillage. `relever()` respecte désormais l'échéance, sauf quand
le bouton « Relever maintenant » force.

Écrit dans un fichier — piège n°3. `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_news.py"

# ── 1. Les sources ─────────────────────────────────────────────────────────
ANCIEN_SOURCES = '''SOURCES = [
    {"cle": "annonces", "domaine": "Annonces",
     "url": f"{DOMAINE_FORUM}/c/updates/announcements/36.json?order=created",
     "minutes": 30},
    {"cle": "notes", "domaine": "Studio & moteur",
     "url": f"{DOMAINE_FORUM}/c/updates/release-notes/62.json?order=created",
     "minutes": 30},
    {"cle": "alertes", "domaine": "Politique & sécurité",
     "url": f"{DOMAINE_FORUM}/c/updates/news-alerts/193.json?order=created",
     "minutes": 60},
    {"cle": "communaute", "domaine": "Événements",
     "url": f"{DOMAINE_FORUM}/c/updates/community/90.json?order=created",
     "minutes": 60},
    {"cle": "ressources", "domaine": "Développeurs",
     "url": f"{DOMAINE_FORUM}/c/resources/roblox-staff/278.json?order=created",
     "minutes": 120},
]
'''

NOUVEAU_SOURCES = '''#  ⚠️ DOMAINES EN DUR pour chaque famille de source. Un lien publié est
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
    {"cle": "presse", "domaine": "Communiqués officiels", "format": "rss",
     "url": f"{DOMAINE_PRESSE}/rss/pressrelease.aspx", "minutes": 120},
    {"cle": "newsroom", "domaine": "Newsroom Roblox", "format": "newsroom",
     "url": f"{DOMAINE_NEWSROOM}/newsroom", "prefixe": "/newsroom/",
     "minutes": 120},
    #  ⚠️ LA SOURCE FRANÇAISE OFFICIELLE. « Salle de presse | Roblox » — même
    #  contenu que le newsroom, traduit par Roblox. On ne traduit rien : on
    #  cite. Demande du propriétaire : « des actualités US, français ».
    {"cle": "newsroom_fr", "domaine": "Salle de presse (FR)", "format": "newsroom",
     "url": f"{DOMAINE_NEWSROOM}/fr/newsroom", "prefixe": "/fr/newsroom/",
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
'''

# ── 2. relever() : cadence + dispatch ──────────────────────────────────────
ANCIEN_RELEVER = '''async def relever(source: dict) -> dict:
    """Lit une source Discourse. Rend {"billets": [...], "code": int|None}.

    Ne lève jamais : une panne de veille ne doit pas gêner la modération.
    """
    out = {"billets": [], "code": None, "domaine": source["domaine"]}
    try:
        async with _ouvrir() as sess:
            async with sess.get(source["url"]) as r:
                out["code"] = r.status
                if r.status == 200:
                    data = await r.json()
                    out["billets"] = _normaliser(data, source["domaine"])
                else:
                    _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
    except Exception as ex:
        _log(f"[roblox_news {source['cle']}] {type(ex).__name__}: {ex}")
    await _noter_sante(source["cle"], out["code"])
    return out
'''

NOUVEAU_RELEVER = '''async def echue(source: dict) -> bool:
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
            if r.status == 200:
                data = await r.json()
                out["billets"] = _normaliser(data, source["domaine"])
            else:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")


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
    m = re.match(
        r"^https?://ir\\.roblox\\.com/news/news-details/(\\d{4})/([A-Za-z0-9\\-]+)/?$",
        str(url_brute or "").strip())
    if not m:
        return None
    return f"{DOMAINE_PRESSE}/news/news-details/{m.group(1)}/{m.group(2)}/"


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
            #  L'identifiant de dédup est le slug du lien validé — stable, et
            #  indépendant du titre (qui peut être corrigé après publication).
            slug = lien.rstrip("/").rsplit("/", 1)[-1] if lien else None
            if not slug:
                continue
            desc = (item.findtext("description") or "").strip()
            import re
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\\s+", " ", desc).strip()
            out.append({
                "topic_id": f"presse:{slug}",
                "titre": titre[:200] or "—",
                "domaine": domaine,
                "cree_le": date,
                "extrait": (desc[:300] or None),
                "tags": [],
                "lien": lien,
            })
        except Exception:
            continue
    out.sort(key=lambda b: str(b.get("cree_le") or ""), reverse=True)
    return out


async def _relever_rss(source: dict, out: dict) -> None:
    async with _ouvrir() as sess:
        async with sess.get(source["url"]) as r:
            out["code"] = r.status
            if r.status == 200:
                out["billets"] = _normaliser_rss(await r.text(), source["domaine"])
            else:
                _log(f"[roblox_news {source['cle']}] HTTP {r.status}")


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
    m = re.match(r"^(\\d{4})/(\\d{2})/([a-z0-9][a-z0-9\\-]{2,160})$", reste)
    if not m:
        return None
    return f"{DOMAINE_NEWSROOM}{prefixe}{m.group(1)}/{m.group(2)}/{m.group(3)}"


def _slugs_newsroom(html: str, prefixe: str) -> list[str]:
    """Les chemins d'article de la page de liste, dédoublonnés, dans l'ordre
    d'apparition (le plus récent est en tête sur la page)."""
    import re
    vus, out = set(), []
    motif = re.escape(prefixe) + r"\\d{4}/\\d{2}/[a-z0-9\\-]+"
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
        m = (re.search(r'property="' + prop + r'"\\s+content="([^"]*)"', html)
             or re.search(r'content="([^"]*)"\\s+property="' + prop + r'"', html))
        return _html.unescape(m.group(1)).strip() if m else None
    return {"date": meta("article:published_time"),
            "titre": meta("og:title"),
            "extrait": meta("og:description")}


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
            b = _cache_newsroom.get(slug)
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
                    "topic_id": f"{source['cle']}:{slug}",
                    "titre": (page.get("titre") or slug.rsplit("/", 1)[-1])[:200],
                    "domaine": source["domaine"],
                    "cree_le": page.get("date"),
                    "extrait": (page.get("extrait") or "")[:300] or None,
                    "tags": [],
                    "lien": lien,
                }
                if len(_cache_newsroom) >= MAX_CACHE_NEWSROOM:
                    _cache_newsroom.pop(next(iter(_cache_newsroom)))
                _cache_newsroom[slug] = b
            #  Fraîcheur : même règle que le forum, fail-closed sur une date
            #  illisible — une page sans `article:published_time` ne sort pas.
            if _trop_vieux(b.get("cree_le")):
                continue
            billets.append(b)
    billets.sort(key=lambda x: str(x.get("cree_le") or ""), reverse=True)
    out["billets"] = billets
'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    for nom, ancre in (("SOURCES", ANCIEN_SOURCES), ("relever", ANCIEN_RELEVER)):
        if src.count(ancre) != 1:
            print(f"❌ ancre « {nom} » trouvée {src.count(ancre)} fois — abandon.")
            return 1
    neuf = src.replace(ANCIEN_SOURCES, NOUVEAU_SOURCES).replace(
        ANCIEN_RELEVER, NOUVEAU_RELEVER)
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    noms = {getattr(n, "name", None) for n in arbre.body}
    for attendu in ("relever", "echue", "lien_presse", "lien_newsroom",
                    "_relever_rss", "_relever_newsroom", "_normaliser_rss"):
        if attendu not in noms:
            print(f"❌ {attendu} absent après patch — abandon.")
            return 1
    print(f"  roblox_news.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
