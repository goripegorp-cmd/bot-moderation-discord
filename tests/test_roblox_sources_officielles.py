"""Les sources OFFICIELLES hors forum : presse, newsroom EN, salle de presse FR.

DEMANDE DU PROPRIÉTAIRE (16/08)
    « Il y a énormément d'actualités de tous types, US, français, sur des
    sites très officiels de Roblox, mais rien n'est annoncé. »

Chaque source a été ouverte et lue le 16/08 (doctrine ROBLOX.md §4). Ces tests
n'appellent PAS le réseau : ils rejouent des extraits RÉELS relevés ce jour-là,
et tiennent les trois règles qui ont chacune été violées une fois pendant
l'écriture :

1. le lien est RECONSTRUIT et VALIDÉ, jamais recopié — et la forme réelle du
   lien de presse finit par `/default.aspx` (une regex trop stricte écartait
   tous les communiqués : « 0 frais » en pleine santé) ;
2. le cache des pages article est par LANGUE — le slug est identique en EN et
   en FR, et la salle de presse française ressortait le billet anglais ;
3. la clé de déduplication est COMMUNE aux deux langues — sinon le même
   article sortait deux fois. FR passe avant EN : le français quand Roblox l'a
   traduit, l'anglais sinon.
"""
from __future__ import annotations

import pytest

import roblox_news as news


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Les liens sont reconstruits et validés
# ═══════════════════════════════════════════════════════════════════════════════

def test_lien_presse_accepte_la_forme_reelle_avec_default_aspx():
    """Mesuré le 16/08 : c'est LA forme des liens du flux RSS."""
    brut = ("https://ir.roblox.com/news/news-details/2026/"
            "Roblox-Reports-Second-Quarter-2026-Financial-Results/default.aspx")
    lien = news.lien_presse(brut)
    assert lien == brut
    assert lien.startswith(news.DOMAINE_PRESSE)


def test_lien_presse_accepte_aussi_sans_default_aspx():
    lien = news.lien_presse("https://ir.roblox.com/news/news-details/2026/Titre-Slug/")
    assert lien == f"{news.DOMAINE_PRESSE}/news/news-details/2026/Titre-Slug/default.aspx"


@pytest.mark.parametrize("mauvais", [
    "https://evil.example/news/news-details/2026/x/default.aspx",   # mauvais domaine
    "https://ir.roblox.com/news/news-details/2026/x/../../etc",     # traversée
    "https://ir.roblox.com/news/news-details/26/x/default.aspx",    # année courte
    "https://ir.roblox.com/news/news-details/2026/x y/default.aspx", # espace
    "https://ir.roblox.com/autre/2026/x/default.aspx",              # autre chemin
    "", None, 42,
])
def test_lien_presse_refuse_tout_ce_qui_nest_pas_la_forme_exacte(mauvais):
    assert news.lien_presse(mauvais) is None


def test_lien_newsroom_reconstruit_en_et_fr():
    assert news.lien_newsroom("/newsroom/2026/08/beyond-selfie", "/newsroom/") == \
        f"{news.DOMAINE_NEWSROOM}/newsroom/2026/08/beyond-selfie"
    assert news.lien_newsroom("/fr/newsroom/2026/08/beyond-selfie", "/fr/newsroom/") == \
        f"{news.DOMAINE_NEWSROOM}/fr/newsroom/2026/08/beyond-selfie"


@pytest.mark.parametrize("chemin,prefixe", [
    ("/newsroom/2026/08/beyond-selfie", "/fr/newsroom/"),   # mauvais préfixe
    ("/fr/newsroom/2026/8/x", "/fr/newsroom/"),             # mois sur 1 chiffre
    ("/fr/newsroom/2026/08/", "/fr/newsroom/"),             # slug vide
    ("/fr/newsroom/2026/08/X-Majuscule", "/fr/newsroom/"),  # majuscule
    ("/fr/newsroom/2026/08/x/../../y", "/fr/newsroom/"),    # traversée
    ("https://about.roblox.com/fr/newsroom/2026/08/x", "/fr/newsroom/"),  # absolu
])
def test_lien_newsroom_refuse_les_formes_hors_gabarit(chemin, prefixe):
    assert news.lien_newsroom(chemin, prefixe) is None


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le flux RSS de presse — extrait RÉEL du 16/08
# ═══════════════════════════════════════════════════════════════════════════════

RSS_REEL = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Roblox Press Releases</title>
<item>
<title>Roblox Reports Second Quarter 2026 Financial Results</title>
<link>https://ir.roblox.com/news/news-details/2026/Roblox-Reports-Second-Quarter-2026-Financial-Results/default.aspx</link>
<pubDate>{date_recente}</pubDate>
<description>&lt;p&gt;Roblox Corporation today reported&lt;/p&gt;</description>
</item>
<item>
<title>Vieux communiqué</title>
<link>https://ir.roblox.com/news/news-details/2024/Vieux/default.aspx</link>
<pubDate>Tue, 16 Jan 2024 08:00:00 -0400</pubDate>
</item>
<item>
<title>Lien douteux</title>
<link>https://evil.example/x</link>
<pubDate>{date_recente}</pubDate>
</item>
</channel></rss>"""


def _rss():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    recent = format_datetime(datetime.now(timezone.utc) - timedelta(days=3))
    return RSS_REEL.format(date_recente=recent)


def test_le_rss_de_presse_donne_un_billet_date_avec_lien_valide():
    billets = news._normaliser_rss(_rss(), "Communiqués officiels")
    assert len(billets) == 1, "le vieux est trop ancien, le douteux n'a pas de lien valide"
    b = billets[0]
    assert b["titre"] == "Roblox Reports Second Quarter 2026 Financial Results"
    assert b["lien"].endswith("/default.aspx")
    assert b["topic_id"] == "presse:Roblox-Reports-Second-Quarter-2026-Financial-Results"
    assert b["cree_le"] and b["cree_le"].startswith("20")
    assert "<p>" not in (b["extrait"] or ""), "le HTML de la description est retiré"


def test_la_date_rfc2822_est_lue():
    assert news._date_rfc2822("Thu, 30 Jul 2026 16:05:00 -0400") == "2026-07-30T20:05:00+00:00"
    assert news._date_rfc2822("n'importe quoi") is None
    assert news._date_rfc2822(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le newsroom — liste et page article, extraits RÉELS
# ═══════════════════════════════════════════════════════════════════════════════

LISTE_FR = '''<a href="/fr/newsroom/2026/08/beyond-selfie-how-roblox-age-assurance-system">x</a>
<a href="/fr/newsroom/2026/07/moments-new-homepage-unlocks-gaming-for-all">y</a>
<a href="/fr/newsroom/2026/07/moments-new-homepage-unlocks-gaming-for-all">doublon</a>
<a href="/newsroom/2026/07/en-only">mauvais préfixe</a>
<a href="/fr/newsroom/tag/securite">pas un article</a>'''

PAGE_FR = '''<html><head>
<meta property="og:title" content="Au-delà du selfie : comment le système de vérification de l&#x27;âge de Roblox" />
<meta property="og:description" content="Un résumé." />
<meta property="article:published_time" content="2026-08-04T12:00:00.000Z" />
</head></html>'''


def test_la_liste_donne_les_chemins_dedoublonnes_dans_lordre():
    chemins = news._slugs_newsroom(LISTE_FR, "/fr/newsroom/")
    assert chemins == [
        "/fr/newsroom/2026/08/beyond-selfie-how-roblox-age-assurance-system",
        "/fr/newsroom/2026/07/moments-new-homepage-unlocks-gaming-for-all",
    ]


def test_la_page_article_donne_date_titre_et_resume_desechappes():
    """`og:title` porte « l&#x27;âge » : il doit ressortir « l'âge »."""
    p = news._lire_page_article(PAGE_FR)
    assert p["date"] == "2026-08-04T12:00:00.000Z"
    assert p["titre"].startswith("Au-delà du selfie : comment le système de vérification de l'âge")
    assert p["extrait"] == "Un résumé."


def test_une_page_sans_date_ne_sort_pas():
    """Fail-closed : une page sans `article:published_time` est trop vieille
    par défaut — même règle que le forum, on ne devine pas une date."""
    p = news._lire_page_article("<html><head></head></html>")
    assert p["date"] is None
    assert news._trop_vieux(p["date"]) is True


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Les règles de dédup et d'ordre entre langues
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_salle_de_presse_fr_passe_avant_le_newsroom_en():
    """Même clé de dédup ⇒ la première servie gagne ⇒ ce doit être le français."""
    cles = [s["cle"] for s in news.SOURCES]
    assert "newsroom_fr" in cles and "newsroom" in cles
    assert cles.index("newsroom_fr") < cles.index("newsroom")


def test_les_deux_newsrooms_partagent_la_cle_de_dedup(monkeypatch):
    """Sans ça, le même article sortait deux fois dans le salon."""
    import roblox_news as n
    src_fr = next(s for s in n.SOURCES if s["cle"] == "newsroom_fr")
    src_en = next(s for s in n.SOURCES if s["cle"] == "newsroom")
    #  On rejoue `_relever_newsroom` sur des réponses figées.
    reponses = {
        src_fr["url"]: LISTE_FR.replace("/fr/newsroom/2026/07/moments-new-homepage-unlocks-gaming-for-all", "")
                               .replace("doublon", ""),
        src_en["url"]: '<a href="/newsroom/2026/08/beyond-selfie-how-roblox-age-assurance-system">x</a>',
        f"{n.DOMAINE_NEWSROOM}/fr/newsroom/2026/08/beyond-selfie-how-roblox-age-assurance-system": PAGE_FR,
        f"{n.DOMAINE_NEWSROOM}/newsroom/2026/08/beyond-selfie-how-roblox-age-assurance-system":
            PAGE_FR.replace("Au-delà du selfie", "Beyond the Selfie"),
    }

    class _R:
        def __init__(self, txt):
            self.status = 200 if txt is not None else 404
            self._t = txt or ""

        async def text(self):
            return self._t

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _S:
        def get(self, url, **kw):
            return _R(reponses.get(url))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _dodo(_):
        return None

    monkeypatch.setattr(n, "_ouvrir", lambda: _S())
    monkeypatch.setattr(n.asyncio, "sleep", _dodo)
    n._cache_newsroom.clear()

    import asyncio
    out_fr, out_en = {"billets": []}, {"billets": []}
    asyncio.run(n._relever_newsroom(src_fr, out_fr))
    asyncio.run(n._relever_newsroom(src_en, out_en))

    fr, en = out_fr["billets"][0], out_en["billets"][0]
    assert fr["topic_id"] == en["topic_id"] == \
        "newsroom:2026/08/beyond-selfie-how-roblox-age-assurance-system"
    #  ... mais chacun garde SON titre et SON lien : le cache est par langue.
    assert fr["titre"].startswith("Au-delà")
    assert en["titre"].startswith("Beyond")
    assert "/fr/newsroom/" in fr["lien"] and "/fr/" not in en["lien"]


# ═══════════════════════════════════════════════════════════════════════════════
#  5. La cadence par source est enfin appliquée
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_une_source_relevee_a_linstant_est_sautee_sauf_si_on_force(monkeypatch):
    import contextlib
    from datetime import datetime, timezone

    class _Cur:
        def __init__(self, row):
            self._row = row

        async def fetchone(self):
            return self._row

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _DB:
        def execute(self, q, p=()):
            return _Cur((datetime.now(timezone.utc).isoformat(),))

    @contextlib.asynccontextmanager
    async def _get_db():
        yield _DB()

    news.setup(get_db=_get_db, cfg=None, db_set=None, log=lambda *a: None)
    src = news.SOURCES[0]

    assert await news.echue(src) is False, "relevée à l'instant, rythme 30 min"
    rel = await news.relever(src)
    assert rel["sautee"] is True and rel["billets"] == []

    appels = []

    async def _disc(source, out):
        appels.append(source["cle"])
        out["code"] = 200

    async def _sante(cle, code):
        return 0

    monkeypatch.setattr(news, "_relever_discourse", _disc)
    monkeypatch.setattr(news, "_noter_sante", _sante)
    rel = await news.relever(src, forcer=True)
    assert rel["sautee"] is False and appels == [src["cle"]], (
        "« Relever maintenant » doit forcer, sinon il croit la source morte")


@pytest.mark.asyncio
async def test_une_source_jamais_relevee_est_echue():
    import contextlib

    class _Cur:
        async def fetchone(self):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _DB:
        def execute(self, q, p=()):
            return _Cur()

    @contextlib.asynccontextmanager
    async def _get_db():
        yield _DB()

    news.setup(get_db=_get_db, cfg=None, db_set=None, log=lambda *a: None)
    assert await news.echue(news.SOURCES[0]) is True


def test_toutes_les_sources_ont_un_format_connu_et_un_rythme():
    for s in news.SOURCES:
        assert s.get("format") in ("discourse", "rss", "newsroom"), s["cle"]
        assert int(s.get("minutes") or 0) >= 30, s["cle"]
        assert s["url"].startswith(("https://devforum.roblox.com/",
                                    news.DOMAINE_PRESSE, news.DOMAINE_NEWSROOM))
