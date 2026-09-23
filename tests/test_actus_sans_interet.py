"""Les actualités : les vraies nouvelles, pas les récaps — et des fiches qui marchent.

═══════════════════════════════════════════════════════════════════════════════
LA DEMANDE (23/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « Qu'on n'ait pas des news qui servent à rien. Par exemple, un récap de la
      semaine. Alors là, on a eu telle news, telle news, telle news. On s'en
      fout. Ce qu'on veut, c'est les news sur l'instant T. Ce qui va arriver à
      l'avenir, ce qui arrive maintenant, ce qui a été corrigé, les
      événements. » — et « je veux que tu t'assures que chaque news
      fonctionne ».

LE CORPUS CI-DESSOUS EST RÉEL : les titres des cinq catégories suivies, relevés
le 23/09. Sur 150 sujets, le filtre en écarte 26 — tous des récaps ou des
tutoriels — et garde les 124 autres, dont les 30 alertes et les 30 notes de
version. Il est figé ici dans LES DEUX SENS : un filtre qui laisserait passer
un récap échoue, un filtre qui mangerait une vraie nouvelle aussi.

EN PASSANT LES VRAIES ANNONCES DANS LE PIPELINE, deux défauts sont apparus, et
sont verrouillés ici :
  · « image11374×342 52,3 Ko » en tête d'une fiche — la légende technique d'une
    image du forum ;
  · 4 notes de version sur 5 montraient l'introduction du forum (« Steve Jobs
    a démissionné en 1985… ») au lieu des correctifs, faute de suivre un lien
    `/docs/en-us/updates/…`. Après correction : 5 sur 5.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

import roblox_news as rn
import roblox_news_contenu as contenu

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_NEWS = (RACINE / "roblox_news.py").read_text(encoding="utf-8")


def _fn(src: str, nom: str) -> str:
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le corpus réel du 23/09
# ═══════════════════════════════════════════════════════════════════════════════

ECARTES = [
    "Weekly Recap: September 14–20, 2026",
    "RDC26: What We Announced",
    "Weekly Recap: August 31 - September 4, 2026 | Emissive Items and Enhanced Freecam",
    "Weekly Recap: August 24–28, 2026 | Persistent Leaderboards & OpenCloud APIs",
    "April 2026: Roblox Creator Monthly Webinar",
    "New Webinar Series: Roblox Creator Monthly",
    "2025 Year in Review!",
    "Submit to Our 2025 Year in Review!",
    "Creator Spotlight: The Story Behind 99 Nights in the Forest",
    "Collections: How to group instances with query patterns",
    "Server Authority - Tech Deep Dive + Engineering Insights",
    "Instance streaming best practices and techniques",
    "Creator Monthly March 2026",
    "Running Successful Experiments: Insights from Top Creators",
    "Optimizing Your Experience for Age-based Chat: A Guide to Custom Matchmaking",
    "Designing UI - Tips and Best Practices",
    "Roblox Creator Interviews: Getting Started with UGC (feat. PolarCub)",
    "Learn how to build immersive 3D worlds!",
    "How To: React + Roblox",
    "Modeling 101 in Blender (Box Modeling)",
]

GARDES = [
    #  L'avenir, le présent, ce qui change
    "Players Can Now Find In-Game Items Outside Your Game",
    "Creator Roadmap 2026: Fall Update",
    "YouTube Videos Will Be Removed from Game Detail Pages",
    "[Early Access] Player Support",
    "Making Publishing Easier: Our Vision and What's Coming",
    "Introducing Roblox Wallet and Card: Get Paid Faster",
    "[Studio Beta] New Device Simulator Toolbar and Network Simulator",
    "[Full Release] Create and Sell Animation Packs on Marketplace",
    "[Opt-in by Oct 5] Unified Roles & Permissions for Communities and Creator Hub",
    "Heads Up: Upcoming Rollout of Improved Physics Replication!",
    #  Ce qui a été corrigé
    "Release Notes for 740",
    "Release notes for 733",
    #  Les alertes
    "Upcoming Friends List API Access Changes for Australian Users Under 16",
    "Actioning Against Bot Accounts On Roblox",
    "Reports of a “Security Alert” Phishing Scam",
    "PSA: Verifying the authenticity of third-party tools",
    "Updates to the Roblox Terms of Use [April 2026]",
    "DevEx Processing - Holiday 2025",
    #  Les événements
    "Join The Hunt: Roblox 20",
    "Roblox Innovation Awards 2026: Voting is Now Open!",
    "Roblox Inspire 2026 Challenge",
    "EuroJam 2025: Spooktober Fest",
    "Save the Date: RDC26",
    "Ask Builderman: Submit Your Questions for RDC 2026",
]


@pytest.mark.parametrize("titre", ECARTES)
def test_R1_chaque_recap_ou_tutoriel_REEL_est_ecarte(titre):
    assert rn.sans_interet(titre), f"laissé passer : {titre}"


@pytest.mark.parametrize("titre", GARDES)
def test_R2_chaque_VRAIE_nouvelle_passe(titre):
    """Le sens qui compte le plus : un filtre qui mange une vraie nouvelle est
    pire qu'un récap de trop."""
    assert rn.sans_interet(titre) is None, f"vraie nouvelle écartée : {titre}"


def test_R3_des_mots_ENTIERS_guide_n_attrape_pas_guidelines():
    """Les règles de la communauté SONT une nouvelle."""
    assert rn.sans_interet("Updated Community Guidelines") is None
    assert rn.sans_interet("Roblox Guidelines for Advertising") is None


def test_R4_le_filtre_nomme_son_motif():
    """Un filtre muet est indiscernable d'une source calme."""
    assert rn.sans_interet("Weekly Recap: May 1-7") == "récap"
    assert rn.sans_interet("How to use Radial Symmetry") == "tutoriel"


# ═══════════════════════════════════════════════════════════════════════════════
#  Le filtre est BRANCHÉ, et au bon endroit
# ═══════════════════════════════════════════════════════════════════════════════

def test_B1_le_forum_ecarte_AVANT_de_lire_le_corps():
    """Chaque récap écarté économise une requête `/t/{id}.json`."""
    corps = _fn(SRC_NEWS, "_relever_discourse")
    assert corps.index("sans_interet(") < corps.index("/t/")


def test_B2_les_trois_formats_de_source_filtrent():
    for nom in ("_relever_discourse", "_relever_rss", "_relever_newsroom"):
        assert "sans_interet(" in _fn(SRC_NEWS, nom), f"{nom} ne filtre pas"


def test_B3_le_compte_rendu_DIT_combien_ont_ete_ecartes():
    assert "écarté(s) comme récap" in SRC_BOT
    assert '_sn["sans_interet"]' in SRC_BOT or "_sn['sans_interet']" in SRC_BOT


# ═══════════════════════════════════════════════════════════════════════════════
#  Des fiches qui fonctionnent
# ═══════════════════════════════════════════════════════════════════════════════

LIGHTBOX = (
    '<p><div class="lightbox-wrapper"><a class="lightbox" href="https://x/y.png">'
    '<img src="https://x/y.png"><div class="meta"><span class="filename">image</span>'
    '<span class="informations">1137×342 52.3 KB</span></div></a></div></p>'
    "<p>Hey creators! The day is almost here! RDC 26 is just a few weeks away. "
    "It's time to gather those burning questions for Builderman, our founder, "
    "who will answer them live on stage this year.</p>")


def test_C1_la_legende_technique_d_une_image_ne_fuit_plus_dans_le_texte():
    """Mesuré sur « Ask Builderman » : la fiche commençait par ce charabia."""
    texte = contenu.extraire_essentiel(LIGHTBOX, titre="Ask Builderman")
    assert "1137×342" not in texte and "52.3 KB" not in texte, texte
    assert "The day is almost here" in texte


def test_C2_un_lien_de_doc_AVEC_langue_est_suivi():
    """Les notes 737 et 738 pointaient vers `/docs/en-us/updates/…` : sans ce
    retrait, la documentation était abandonnée."""
    html = '<a href="https://create.roblox.com/docs/en-us/updates/2026-09-07">x</a>'
    assert contenu.lien_documentation(html) == "/docs/updates/2026-09-07"


def test_C3_un_lien_hors_documentation_reste_refuse():
    """On valide le chemin, on ne suit pas n'importe quoi."""
    html = '<a href="https://create.roblox.com/en-us/store/asset/123">x</a>'
    assert contenu.lien_documentation(html) is None


INTRO_LONGUE = "<p>" + ("Hey friends, fun facts about today's date. " * 12) + "</p>"


def test_C4_une_note_de_version_va_d_ABORD_a_la_documentation(monkeypatch):
    """« Ce qui a été corrigé » vit dans la documentation ; le billet du forum
    n'en est que l'introduction, souvent plus longue que le seuil — 4 notes sur
    5 affichaient l'introduction."""
    appels = []

    async def _docs(html, date_iso=None):
        appels.append(1)
        return "**Improvements** • Adds undo/redo to Input Action Manager."

    async def _pas_de_traduction(texte):
        return None, None

    monkeypatch.setattr(contenu, "corps_documentation", _docs)
    monkeypatch.setattr(contenu, "traduire", _pas_de_traduction)
    b = asyncio.run(contenu.enrichir_billet(
        {"titre": "Release Notes for 739", "cree_le": "2026-09-17"}, INTRO_LONGUE))
    assert appels, "la documentation n'a pas été consultée"
    assert b["source_corps"] == "documentation Roblox"
    assert "Improvements" in b["corps"]


def test_C5_un_billet_ORDINAIRE_long_ne_part_pas_chercher_la_doc(monkeypatch):
    """La règle ne vaut que pour les notes de version : une annonce complète
    n'a pas besoin d'une requête de plus."""
    appels = []

    async def _docs(html, date_iso=None):
        appels.append(1)
        return "ne doit pas servir"

    async def _pas_de_traduction(texte):
        return None, None

    monkeypatch.setattr(contenu, "corps_documentation", _docs)
    monkeypatch.setattr(contenu, "traduire", _pas_de_traduction)
    b = asyncio.run(contenu.enrichir_billet(
        {"titre": "Creator Roadmap 2026: Fall Update"}, INTRO_LONGUE))
    assert not appels and b.get("source_corps") is None
