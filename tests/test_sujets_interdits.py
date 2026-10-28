"""27/10/2026 — les filtres du chat (exigence 11 du fondateur) : aucun sujet religieux, politique ou extrémiste
(texte ET GIF), toutes religions et tous bords traités pareil ; « omg », « oh my god », « mon dieu » PERMIS ;
« wallah » et toute formule religieuse BLOQUÉS ; insultes étrangères jugées selon la langue."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import insult_filter
import offtopic_filter
import sujets_interdits as S

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


def _cat(texte, gif=False):
    v = S.juger(texte, gif=gif)
    return v and v["categorie"]


@pytest.mark.parametrize("texte", [
    "omg trop fort", "oh my god le boss", "mon dieu ce lag", "OMG", "il joue comme un dieu", "la bible du jeu",
    "le président du club", "god of war est bien", "je t'en prie", "je suis en retard", "salam les gars",
    "voilà", "le mur (wall) est cassé", "je te jure c'est vrai", "",
])
def test_permis(texte):
    assert S.juger(texte) is None, texte


@pytest.mark.parametrize("texte,categorie", [
    ("wallah c'est vrai", "religion"), ("w4ll4h", "religion"), ("wlh frère", "religion"), ("w a l l a h", "religion"),
    ("wallahi", "religion"), ("inshallah", "religion"), ("amen", "religion"), ("amennnn", "religion"),
    ("allahu akbar", "religion"), ("que dieu te bénisse", "religion"), ("god bless you", "religion"),
    ("je prie pour toi", "religion"), ("mon dieu, va à la messe", "religion"),
    ("vote pour macron", "politique"), ("trump 2024", "politique"),
    ("heil hitler", "extremisme"),
])
def test_bloque(texte, categorie):
    assert _cat(texte) == categorie, texte


def test_symetrie_religions():
    """La même fonction, quelle que soit la religion : le même verdict."""
    for g in ("musulman", "chrétien", "juif", "bouddhiste", "athée"):
        assert _cat("je suis " + g) == "religion", g


def test_gif_titre_designe_l_image():
    assert _cat("praying", gif=True) == "religion"
    assert _cat("jesus", gif=True) == "religion"
    assert S.juger("praying") is None   # un mot seul dans une phrase ne suffit pas


def test_reglages_couper_une_categorie():
    assert S.juger("vote pour macron", reglages={"categories": {"politique": False}}) is None


def test_jamais_d_exception():
    for x in (None, 12, "​" * 50, "a" * 20000):
        S.juger(x)  # ne lève jamais


def test_insulte_selon_la_langue():
    assert insult_filter.langue("you are such a retard") == "en"
    assert insult_filter.langue("je suis en retard") == "fr"
    assert insult_filter.validisme_en_contexte("you are such a retard")
    assert not insult_filter.validisme_en_contexte("je suis en retard pour le raid")
    assert insult_filter.scan("don't bite the dust")[0] < 2


# ─── Le branchement dans bot.py ──────────────────────────────────────────────
def _extraire(*noms):
    ns = {"re": re, "offtopic_filter": offtopic_filter, "sujets_interdits": sujets_interdits_mod(),
          "_normalize_for_scan": lambda t: t}
    for n in ARBRE.body:
        nom = n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else (
            getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in noms:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def sujets_interdits_mod():
    return S


def test_branchement_texte_lien_et_titre_de_gif():
    ns = _extraire("_URL_INMSG_RE", "_msg_url_slugs", "_gif_texte", "_sujet_interdit")
    f = ns["_sujet_interdit"]
    assert f({}, "wallah c'est vrai").startswith("religion")
    assert f({}, "regarde https://tenor.com/view/praying-hands-gif-123").startswith("religion")
    emb = SimpleNamespace(title="Heil Hitler", description=None)
    assert f({}, "https://tenor.com/view/x-123", SimpleNamespace(embeds=[emb])).startswith("extremisme")
    assert f({}, "omg ce boss") == ""
    assert f({"sujets_interdits": {"categories": {"religion": False}}}, "wallah") == ""


def test_tous_les_chemins_passent_par_le_nouveau_filtre():
    """Message, édition, textes des membres : plus aucun appel direct à l'ancien lexique seul."""
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name != "_sujet_interdit":
            assert "offtopic_filter.scan(" not in ast.unparse(n), n.name
    code = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert code.count("_sujet_interdit(c, ct, ") == 2
    assert "_sujet_interdit(c, texte)" in code
    assert "Texte interdit dans une image" in code   # le texte DANS l'image ou le GIF (OCR)
