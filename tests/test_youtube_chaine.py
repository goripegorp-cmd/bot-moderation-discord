"""YouTube : la bonne chaîne, un second flux, jamais une vieille vidéo, peu de bruit.

═══════════════════════════════════════════════════════════════════════════════
LE JOURNAL RAILWAY DU 24/09/2026 (nuit)
═══════════════════════════════════════════════════════════════════════════════
    social/youtube_resolve :: @RellGames → UCubHXSqlv_oChR-HsRqlH9A
    social/youtube_resolve :: @CaribBros → UCubHXSqlv_oChR-HsRqlH9A
    … puis deux « flux HTTP 404 » toutes les 5 minutes, plus de 3 heures.

MESURÉ LE MÊME JOUR, vraies pages, mêmes en-têtes que le bot :
  · la page de @RellGames porte UN « "channelId" » — celui de CaribBros, mis
    en avant dans un bouton. Le code prenait le premier. Canonique,
    `externalId`, meta et lien RSS disent tous UCLaduTRRWdzU8kq9AoqTRlw ;
  · le flux de CaribBros répond 200 ailleurs : le 404 est celui que YouTube
    sert par intermittence aux IP de serveurs ;
  · la playlist des mises en ligne (UU…) rend les mêmes vidéos ;
  · les 3 dernières vidéos de RellGames : 18/07/2026, 07/02/2026, 08/07/2025.
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pytest

import diag
import social_media as sm

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")

RELL = "UCLaduTRRWdzU8kq9AoqTRlw"
CARIB = "UCubHXSqlv_oChR-HsRqlH9A"

#  Extraits FIDÈLES des pages mesurées le 24/09 : sur celle de RellGames, le
#  seul « "channelId" » est celui de CaribBros, dans un bouton ; sur celle de
#  CaribBros, il n'y en a aucun.
PAGE_RELL = (
    '<html><script>var ytInitialData = {"onTap":{"innertubeCommand":'
    '{"commandMetadata":{"webCommandMetadata":{"url":"/channel/' + CARIB + '"}},'
    '"browseEndpoint":{"browseId":"' + CARIB + '"},"channelId":"' + CARIB + '"}},'
    '"header":{"x":1},"metadata":{"channelMetadataRenderer":{"title":"RELLGames",'
    '"externalId":"' + RELL + '","rssUrl":"https://www.youtube.com/feeds/videos.xml?'
    'channel_id=' + RELL + '"}}};</script>'
    '<link rel="canonical" href="https://www.youtube.com/channel/' + RELL + '">'
    '<meta itemprop="identifier" content="' + RELL + '"></html>')
PAGE_CARIB = (
    '<html><script>(function(){})();</script>'
    '<link rel="canonical" href="https://www.youtube.com/channel/' + CARIB + '">'
    '<script>var ytInitialData = {"metadata":{"channelMetadataRenderer":'
    '{"externalId":"' + CARIB + '"}}};</script></html>')


# ═══════════════════════════════════════════════════════════════════════════════
#  H — l'identifiant de LA chaîne, jamais celui d'une autre
# ═══════════════════════════════════════════════════════════════════════════════

def test_H1_la_page_de_RellGames_donne_RellGames_pas_CaribBros():
    assert sm.extraire_channel_id(PAGE_RELL) == RELL


def test_H2_la_page_de_CaribBros_donne_CaribBros():
    assert sm.extraire_channel_id(PAGE_CARIB) == CARIB


@pytest.mark.parametrize("html", [
    '<link rel="canonical" href="https://www.youtube.com/channel/' + RELL + '">',
    '"externalId":"' + RELL + '"',
    '<meta itemprop="identifier" content="' + RELL + '">',
    '<meta itemprop="channelId" content="' + RELL + '">',
    'href="https://www.youtube.com/feeds/videos.xml?channel_id=' + RELL + '"',
])
def test_H3_chaque_source_sure_suffit_seule(html):
    assert sm.extraire_channel_id(html) == RELL


def test_H4_un_channelId_ou_un_lien_d_une_AUTRE_chaine_ne_suffit_JAMAIS():
    """⚠️ Plutôt « non résolu » qu'une mauvaise chaîne : la seconde publierait
    les vidéos d'un autre sous son nom, et l'ancien chemin la PERSISTE."""
    autre = ('{"channelId":"' + CARIB + '"} <a href="/channel/' + CARIB + '">'
             '<form action="https://consent.youtube.com/save">')
    assert sm.extraire_channel_id(autre) is None
    assert sm.extraire_channel_id("") is None and sm.extraire_channel_id(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux réseau fidèle : `session.get(...)` en contexte asynchrone
# ═══════════════════════════════════════════════════════════════════════════════

class _Rep:
    def __init__(self, status, texte=""):
        self.status, self._t = status, texte

    async def text(self):
        return self._t

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    """Rend, par motif d'URL, (code, corps). Note chaque URL demandée."""

    def __init__(self, reponses):
        self.reponses, self.urls = reponses, []

    def get(self, url, **kw):
        self.urls.append(url)
        for motif, (st, corps) in self.reponses.items():
            if motif in url:
                return _Rep(st, corps)
        return _Rep(404, "")


@pytest.fixture
def journal(monkeypatch):
    lignes = []
    for niveau in ("warn", "trace", "event"):
        monkeypatch.setattr(diag, niveau, (lambda n: lambda *a, **k: lignes.append(
            (n, " ".join(map(str, a)))))(niveau))
    return lignes


@pytest.mark.asyncio
async def test_H5_le_gestionnaire_social_resout_RellGames_correctement(journal):
    yt = sm.YouTubeRSSAdapter()
    yt._session = _Session({"/@RellGames": (200, PAGE_RELL)})
    assert await yt._resolve_channel_id("@RellGames") == RELL
    assert yt.feed_url("@RellGames").endswith("channel_id=" + RELL)


def _fonctions_bot(*noms):
    ns = {"re": re, "aiohttp": aiohttp, "social2026": sm,
          "_YT_RESOLVE_CONSENT": {"Cookie": "x"}}
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            exec(ast.unparse(n), ns)          # noqa: S102 — code du dépôt
    return ns


@pytest.mark.asyncio
async def test_H6_l_ANCIEN_chemin_aussi_et_c_est_lui_qui_PERSISTE():
    ns = _fonctions_bot("_yt_extract_uc", "_yt_extract_handle", "_yt_resolve_channel_id")
    sess = _Session({"/@RellGames": (200, PAGE_RELL)})
    assert await ns["_yt_resolve_channel_id"](sess, "@RellGames") == RELL
    sess = _Session({"/@X": (200, '{"channelId":"' + CARIB + '"}')})
    assert await ns["_yt_resolve_channel_id"](sess, "@X") == "", (
        "une autre chaîne aurait été persistée comme la sienne")


# ═══════════════════════════════════════════════════════════════════════════════
#  F — les flux : le second quand le premier est refusé, jamais une vieille vidéo
# ═══════════════════════════════════════════════════════════════════════════════

def _atom(*entrees):
    corps = "".join(
        f'<entry><id>yt:video:{vid}</id><title>{titre}</title>'
        f'<link rel="alternate" href="https://www.youtube.com/watch?v={vid}"/>'
        f'<published>{quand}</published></entry>' for vid, titre, quand in entrees)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">' + corps + '</feed>')


def _il_y_a(jours):
    return (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()


def _yt(reponses):
    yt = sm.YouTubeRSSAdapter()
    yt._cid["rellgames"] = RELL
    yt._session = _Session(reponses)
    return yt


@pytest.mark.asyncio
async def test_F1_une_vieille_video_n_est_JAMAIS_une_nouveaute(journal):
    """Le cas exact : les 3 dernières de RellGames datent du 18/07/2026, du
    07/02/2026 et du 08/07/2025. Corriger sa chaîne ne doit rien publier."""
    yt = _yt({"channel_id=" + RELL: (200, _atom(
        ("VssZRRYrCoo", "[Code] Shindo Life Biggest Update (2026)", "2026-07-18T01:48:50+00:00"),
        ("BGCI9Ml-4q4", "RELL Seas: Behind The Scenes", "2026-02-07T03:16:49+00:00"),
        ("QuClr80Pmc0", "RELL Seas: Not Movie 3", "2025-07-08T06:49:01+00:00")))})
    assert await yt.fetch_posts("@RellGames") == []


@pytest.mark.asyncio
async def test_F2_une_video_RECENTE_passe_et_garde_l_identifiant_Atom(journal):
    yt = _yt({"channel_id=" + RELL: (200, _atom(
        ("NEWVIDEO001", "RELL Seas: Update", _il_y_a(1)),
        ("OLDVIDEO001", "Ancienne", _il_y_a(400))))})
    posts = await yt.fetch_posts("@RellGames")
    assert [p.post_id for p in posts] == ["yt:video:NEWVIDEO001"]
    assert posts[0].url == "https://www.youtube.com/watch?v=NEWVIDEO001"


@pytest.mark.asyncio
async def test_F3_flux_de_la_chaine_REFUSE_la_playlist_le_remplace_sans_bruit(journal):
    yt = _yt({"channel_id=" + RELL: (404, ""),
              "playlist_id=UU" + RELL[2:]: (200, _atom(("NEWVIDEO002", "Neuve", _il_y_a(0))))})
    items = await yt._fetch_items("@RellGames")
    assert [p.post_id for p in items] == ["yt:video:NEWVIDEO002"]
    assert yt._session.urls[-1].endswith("playlist_id=UU" + RELL[2:])
    assert not [l for l in journal if l[0] == "warn"], journal


@pytest.mark.asyncio
async def test_F4_deux_refus_UN_avertissement_par_jour_pas_un_par_passage(journal):
    """⚠️ LA NUIT DU 24/09 : deux lignes toutes les 5 minutes, 3 heures."""
    yt = _yt({})                                   # tout répond 404
    for _ in range(4):
        assert await yt._fetch_items("@RellGames") == []
    avert = [l for l in journal if l[0] == "warn"]
    assert len(avert) == 1, avert
    #  « rien n'est perdu » a été RETIRÉ le 26/09 : au-delà de 7 jours de
    #  refus, une vidéo manquée le serait pour de bon — une promesse fausse.
    assert "refuse ses deux flux et sa page" in avert[0][1], avert
    assert "rien n'est perdu" not in avert[0][1]


# ═══════════════════════════════════════════════════════════════════════════════
#  P — la page « Vidéos », quand YouTube refuse ses DEUX flux au serveur
# ═══════════════════════════════════════════════════════════════════════════════
#  JOURNAL DU 26/09 : « @RellGames : YouTube refuse ses deux flux à ce serveur
#  (HTTP 404 puis 404) », pendant que les pages de chaîne répondaient.

VIDEO = "LOCKUP_CONTENT_TYPE_VIDEO"


def _page(*videos):
    """Une page « Vidéos » au format mesuré le 26/09 (`lockupViewModel`)."""
    lockups = []
    for vid, titre, quand, genre in videos:
        parts = [{"text": {"content": "12K"}}] + (
            [{"text": {"content": quand}}] if quand else [])
        lockups.append({"richItemRenderer": {"content": {"lockupViewModel": {
            "contentId": vid, "contentType": genre,
            "metadata": {"lockupMetadataViewModel": {
                "title": {"content": titre},
                "metadata": {"contentMetadataViewModel": {
                    "metadataRows": [{"metadataParts": parts}]}}}}}}}})
    data = {"contents": {"tabs": [{"content": {"richGridRenderer": {"contents": lockups}}}]}}
    return "<html><script>var ytInitialData = " + json.dumps(data) + ";</script></html>"


@pytest.mark.parametrize("textes,jours", [
    (["351K", "2mo ago"], 60), (["10d ago"], 10), (["1y ago"], 365),
    (["5 days ago"], 5), (["Streamed 3h ago"], 0), (["5m ago"], 0), (["2w ago"], 14),
])
def test_P1_la_date_relative_de_YouTube_est_lue(textes, jours):
    """« 2mo » : deux MOIS, pas deux minutes — « mo » est cherché avant « m »."""
    quand = datetime.fromisoformat(sm.date_relative(textes))
    ecart = (datetime.now(timezone.utc) - quand).total_seconds() / 86400
    assert abs(ecart - jours) < 0.5, (textes, ecart)


def test_P1b_une_video_programmee_ou_sans_date_n_a_PAS_de_date():
    assert sm.date_relative(["Scheduled for 10/10/26"]) is None
    assert sm.date_relative([]) is None and sm.date_relative(None) is None


def test_P2_la_page_rend_les_videos_DATEES_avec_l_identifiant_du_flux():
    """Même identifiant que le flux Atom (`yt:video:…`) : jamais deux annonces.
    Sans date lisible : IGNORÉE, plutôt que risquer une vidéo d'il y a un an."""
    html = _page(("NEWVIDEO011", "Neuve", "2d ago", VIDEO),
                 ("OLDVIDEO011", "Vieille", "1y ago", VIDEO),
                 ("NODATE00011", "Sans date", None, VIDEO),
                 ("PLAYLIST011", "Une playlist", "1d ago", "LOCKUP_CONTENT_TYPE_PLAYLIST"))
    posts = sm.videos_de_la_page(html, "@RellGames")
    assert [p.post_id for p in posts] == ["yt:video:NEWVIDEO011", "yt:video:OLDVIDEO011"]
    assert posts[0].url == "https://www.youtube.com/watch?v=NEWVIDEO011"
    assert posts[0].title == "Neuve"
    assert [p.post_id for p in sm.YouTubeRSSAdapter()._recentes(posts)] == [
        "yt:video:NEWVIDEO011"]


def test_P3_une_page_ILLISIBLE_rend_None_pas_une_liste_vide():
    """Mur de consentement ou format changé : c'est un échec, pas « rien de neuf »."""
    assert sm.videos_de_la_page("<html>consent.youtube.com</html>", "@x") is None
    assert sm.videos_de_la_page("", "@x") is None


@pytest.mark.asyncio
async def test_P4_deux_flux_REFUSES_la_page_prend_le_relais_sans_bruit(journal):
    yt = _yt({"channel_id=" + RELL: (404, ""), "playlist_id=UU" + RELL[2:]: (404, ""),
              f"/channel/{RELL}/videos": (200, _page(
                  ("NEWVIDEO012", "RELL Seas: Update", "3h ago", VIDEO),
                  ("OLDVIDEO012", "Ancienne", "2mo ago", VIDEO)))})
    items = await yt._fetch_items("@RellGames")
    assert [p.post_id for p in items] == ["yt:video:NEWVIDEO012"]
    assert not [l for l in journal if l[0] == "warn"], journal


@pytest.mark.asyncio
async def test_P5_la_page_d_1_Mo_n_est_lue_qu_une_fois_par_demi_heure(journal):
    yt = _yt({"channel_id=" + RELL: (404, ""), "playlist_id=UU" + RELL[2:]: (404, ""),
              f"/channel/{RELL}/videos": (200, _page(("NEWVIDEO013", "N", "1h ago", VIDEO)))})
    await yt._fetch_items("@RellGames")
    await yt._fetch_items("@RellGames")
    pages = [u for u in yt._session.urls if u.endswith("/videos")]
    assert len(pages) == 1, yt._session.urls


def test_F5_l_ancien_avertissement_a_chaque_refus_n_est_plus_emis_pour_YouTube():
    """Le parent avertissait à chaque non-200 ; YouTube lui demande le silence
    et décide lui-même (second flux, un avertissement par jour)."""
    src = (RACINE / "social_media.py").read_text(encoding="utf-8")
    i = src.index("class YouTubeRSSAdapter")
    assert "super()._fetch_items(handle, avertir=False)" in src[i:]
