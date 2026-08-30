"""Les notes de version ne sortaient jamais — trois semaines d'affilée.

DEMANDE DU PROPRIÉTAIRE, 30/08/2026
    « Assure-toi qu'en termes de publication sur les forums, tu aies absolument
     toutes les dernières actualités de tous types d'événements qui existent,
     MÊME DES MISES À JOUR et tout, vraiment tout. »
Et, dans la même phrase, la contrainte opposée :
    « Assure-toi de ne pas spammer en boucle une recherche qui sert à rien.
     Comme ça, ça évite de spammer la plateforme, de spammer l'API et qu'elle
     ne marche plus. »

CE QUE L'AUDIT A MESURÉ — la même source, trois semaines de suite :
    11/08  « Release Notes for 734 »  corps de   70 car. → JETÉ comme pointeur
    20/08  « Release Notes for 735 »  corps de  320 car. → fiche VIDE publiée
    27/08  « Release Notes for 736 »  corps de  424 car. → fiche VIDE publiée
Zéro note de version utile. Le billet du forum ne contient qu'une phrase et un
lien : tout le contenu vit sur `create.roblox.com/docs`.

LE CORRECTIF N'AJOUTE AUCUNE SOURCE PÉRIODIQUE. La requête ne part que lorsque
le billet pointe réellement vers la documentation — environ une fois par
semaine. C'est la seule façon de satisfaire les DEUX moitiés de la demande.

⚠️ DEUX PIÈGES MESURÉS LE 30/08, ET ILS COÛTENT CHER :
  · les DEUX schémas d'URL coexistent. `/docs/updates/2026-08-24.md` répond ;
    `/docs/release-notes/release-notes-735.md` rend 404. Suivre le seul lien du
    billet aurait échoué DEUX semaines sur trois. Le lundi de la date du billet
    a fonctionné pour les trois.
  · un 404 rend du HTML, et sa taille varie (2 599 octets ce jour-là, 15 792
    lors d'une autre mesure). On teste le code ET le type de contenu, JAMAIS la
    taille.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import roblox_news_contenu as contenu


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le chemin est EXTRAIT et VALIDÉ, jamais suivi les yeux fermés
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_lien_de_documentation_est_reconnu():
    html = ('<p>Howdy! Here are the release notes for 736: '
            '<a href="https://create.roblox.com/docs/updates/2026-08-24">here</a></p>')
    assert contenu.lien_documentation(html) == "/docs/updates/2026-08-24"


def test_les_deux_schemas_connus_sont_acceptes():
    """Ils coexistent réellement — mesuré sur trois semaines consécutives."""
    for chemin in ("/docs/updates/2026-08-24",
                   "/docs/release-notes/release-notes-735"):
        html = f'<a href="https://create.roblox.com{chemin}">x</a>'
        assert contenu.lien_documentation(html) == chemin


def test_on_ne_suit_pas_n_importe_quel_lien():
    """⚠️ RÈGLE DE SÉCURITÉ DU DÉPÔT : une URL suivie par le bot est
    reconstruite à partir d'une constante et d'un chemin VALIDÉ. Ce bot lutte
    contre le phishing — il ne peut pas suivre un lien approximatif."""
    for mauvais in (
        '<a href="https://create.roblox.com/marketplace/truc">x</a>',
        '<a href="https://create-roblox.com.evil.tld/docs/updates/x">x</a>',
        '<a href="https://evil.tld/docs/updates/2026-08-24">x</a>',
        '<a href="https://devforum.roblox.com/t/1234">x</a>',
    ):
        assert contenu.lien_documentation(mauvais) is None, mauvais


def test_le_domaine_est_une_constante_en_dur():
    src = inspect.getsource(contenu.corps_documentation)
    ast.parse(src.lstrip())
    assert "DOMAINE_DOCS" in src
    assert contenu.DOMAINE_DOCS == "https://create.roblox.com"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le repli par le lundi — sans lui, deux semaines sur trois échouaient
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_lundi_de_la_semaine_est_calcule_juste():
    #  Le 20/08/2026 est un jeudi ; son lundi est le 17.
    assert contenu._chemin_du_lundi(
        "2026-08-20T18:00:00Z") == "/docs/updates/2026-08-17"
    #  Un lundi reste lui-même.
    assert contenu._chemin_du_lundi(
        "2026-08-24T09:00:00Z") == "/docs/updates/2026-08-24"


def test_une_date_illisible_ne_fabrique_pas_de_chemin():
    for mauvais in (None, "", "bientôt", 12345):
        assert contenu._chemin_du_lundi(mauvais) is None


@pytest.mark.asyncio
async def test_le_repli_est_essaye_quand_le_lien_direct_echoue(monkeypatch):
    """⚠️ MESURÉ : `/docs/release-notes/release-notes-735.md` rend 404, mais
    `/docs/updates/2026-08-17.md` répond. Sans ce repli, la note du 20/08
    n'aurait toujours pas de corps."""
    vus = []

    class _Rep:
        def __init__(self, statut, corps=""):
            self.status = statut
            self.headers = {"Content-Type": "text/markdown; charset=utf-8"}
            self._corps = corps

        async def text(self):
            return self._corps

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Sess:
        def get(self, url):
            vus.append(url)
            if "release-notes-735" in url:
                return _Rep(404)
            return _Rep(200, "---\nlast_updated: x\n---\n## Fixes\n- Une correction.")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(contenu, "_ouvrir_contenu", lambda: _Sess())
    html = ('<a href="https://create.roblox.com/docs/release-notes/'
            'release-notes-735">here</a>')
    corps = await contenu.corps_documentation(html, date_iso="2026-08-20T18:00:00Z")

    assert corps and "correction" in corps
    assert len(vus) == 2, "le repli n'a pas été essayé"
    assert vus[1].endswith("/docs/updates/2026-08-17.md")


@pytest.mark.asyncio
async def test_aucune_requete_si_le_billet_ne_pointe_pas_vers_la_doc(monkeypatch):
    """⚠️ « NE PAS SPAMMER UNE RECHERCHE QUI SERT À RIEN. » Sans cette garde,
    toute annonce courte du forum déclencherait une requête vers la
    documentation à chaque relevé, pour rien."""
    def _interdit():
        raise AssertionError("une requête est partie sans lien vers la doc")

    monkeypatch.setattr(contenu, "_ouvrir_contenu", _interdit)
    assert await contenu.corps_documentation(
        "<p>Annonce courte sans lien.</p>", date_iso="2026-08-20T18:00:00Z") is None


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le markdown est réduit à ce que la fiche sait afficher
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_front_matter_est_jete():
    """⚠️ `last_updated` EST UN HORODATAGE DE BUILD. Mesuré : les semaines du
    10, 17 et 24 août portent toutes `2026-08-28T18:00:06Z`, à la seconde près.
    Le publier ferait dater toutes les notes du même jour."""
    brut = ("---\ntitle: Week of August 24\nlast_updated: 2026-08-28T18:00:06Z\n"
            "---\n## Improvements\n- Une amélioration.\n")
    out = contenu._markdown_en_texte(brut)
    assert "last_updated" not in out and "2026-08-28" not in out
    assert "**Improvements**" in out and "• Une amélioration." in out


def test_les_titres_et_les_puces_survivent():
    """C'est la structure MÊME des notes de version : « ## Improvements »,
    « ## Fixes ». La perdre rendrait la fiche illisible."""
    out = contenu._markdown_en_texte(
        "## Improvements\n- A\n- B\n## Fixes\n- C\n")
    assert out.count("•") == 3
    assert "**Improvements**" in out and "**Fixes**" in out


def test_un_markdown_vide_ne_rend_rien():
    for vide in ("", "   ", "---\nx: y\n---\n"):
        assert contenu._markdown_en_texte(vide) is None


def test_le_corps_est_borne():
    out = contenu._markdown_en_texte("- " + ("a" * 9000))
    assert len(out) <= contenu.MAX_CORPS_DOCS


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le billet n'est plus jeté après qu'on est allé chercher son contenu
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_un_billet_repris_des_docs_nest_plus_un_pointeur(monkeypatch):
    """⚠️ LE DÉFAUT À DEUX ÉTAGES. `est_pointeur` juge sur le HTML D'ORIGINE,
    resté court. Sans cette correction, on payait la requête vers la
    documentation, on obtenait le vrai contenu… et on jetait le billet quand
    même."""
    async def _faux_docs(html, date_iso=None):
        return "**Fixes**\n• Une vraie correction."

    async def _pas_de_traduction(_bloc):
        return None, None

    monkeypatch.setattr(contenu, "corps_documentation", _faux_docs)
    monkeypatch.setattr(contenu, "traduire", _pas_de_traduction)

    html = ('<p>Howdy! Release notes for 736: '
            '<a href="https://create.roblox.com/docs/updates/2026-08-24">here</a></p>')
    b = await contenu.enrichir_billet(
        {"titre": "Release Notes for 736", "cree_le": "2026-08-27T18:00:00Z"},
        html, "en")

    assert b["pointeur"] is False, (
        "le billet est encore jeté alors qu'on a récupéré son contenu")
    assert "correction" in b["corps"]
    assert b.get("source_corps") == "documentation Roblox", (
        "l'origine du corps doit être tracée : ce texte ne vient pas du forum")


@pytest.mark.asyncio
async def test_un_vrai_pointeur_reste_ecarte(monkeypatch):
    """La contre-épreuve. Sans elle, ce correctif pourrait faire passer TOUS
    les billets creux — et le salon se remplirait de « allez voir ce lien »."""
    async def _rien(html, date_iso=None):
        return None

    monkeypatch.setattr(contenu, "corps_documentation", _rien)
    html = ('<p>Go see this: '
            '<a href="https://www.roblox.com/games/123">here</a></p>')
    b = await contenu.enrichir_billet({"titre": "Coucou"}, html, "en")
    assert b["pointeur"] is True


@pytest.mark.asyncio
async def test_une_panne_de_la_doc_ne_fait_pas_tomber_le_billet(monkeypatch):
    """Une source annexe injoignable ne doit jamais casser le traitement du
    billet : au pire il sort comme avant."""
    async def _explose(html, date_iso=None):
        raise RuntimeError("réseau coupé")

    async def _pas_de_traduction(_bloc):
        return None, None

    monkeypatch.setattr(contenu, "corps_documentation", _explose)
    monkeypatch.setattr(contenu, "traduire", _pas_de_traduction)
    b = await contenu.enrichir_billet({"titre": "T"}, "<p>court</p>", "en")
    assert isinstance(b, dict) and "pointeur" in b
