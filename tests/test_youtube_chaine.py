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
    assert "refuse ses deux flux" in avert[0][1] and "rien n'est perdu" in avert[0][1]


def test_F5_l_ancien_avertissement_a_chaque_refus_n_est_plus_emis_pour_YouTube():
    """Le parent avertissait à chaque non-200 ; YouTube lui demande le silence
    et décide lui-même (second flux, un avertissement par jour)."""
    src = (RACINE / "social_media.py").read_text(encoding="utf-8")
    i = src.index("class YouTubeRSSAdapter")
    assert "super()._fetch_items(handle, avertir=False)" in src[i:]
