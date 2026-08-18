"""La fiche d'un article : propre, complète, et qui ne flatte pas.

DEMANDE DU PROPRIÉTAIRE (16/08)
    « Affiche un post propre, l'image pas trop grande sur le serveur Discord.
    Toutes les informations nécessaires à l'item, les statistiques et tout,
    pour qu'on soit sûr de ne pas se faire avoir. »

CE QUI EN DÉCOULE, ET QUE CES TESTS TIENNENT
1. l'image est une VIGNETTE, pas une bannière pleine largeur ;
2. les chiffres de trading sont là — stock émis, prix de revente,
   multiplicateur — et lisibles ;
3. **un mauvais multiplicateur s'affiche quand même**. C'est tout l'objet du
   « ne pas se faire avoir » : mesuré le 16/08, Specter Time Fedora se revend
   à ×0,6 de son prix d'origine. Qui l'a payé plein tarif a perdu. Masquer ce
   cas rendrait la fiche flatteuse et inutile.
"""
from __future__ import annotations

import discord
import pytest

import roblox_panneau as rp


@pytest.fixture(autouse=True)
def _module_propre():
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


#  Chiffres RÉELS relevés le 16/08 — pas des valeurs inventées.
REQUIEM = {
    "asset_id": 107334338147739, "nom": "The Requiem",
    "type_article": "Accessoire", "item_type": "Asset",
    "cree_le": "2025-10-21T17:59:54Z", "prix": 400, "favoris": 21000,
    "collectionnable": 1, "hors_vente": 1,
    "stock": 27110, "revente": 1800, "multiplicateur": 4.5, "en_vente": False,
}

FEDORA_PERDANT = dict(
    REQUIEM, asset_id=74029346462094, nom="Specter Time Fedora",
    prix=3000, stock=10078, revente=1800, multiplicateur=0.6)

IMAGE = "https://tr.rbxcdn.com/abc/420/420/Hat/Png"


def _compter(payload) -> int:
    n = 0
    for c in payload:
        n += 1
        n += _compter(c.get("components", []) or [])
    return n


def _texte(vue) -> str:
    return str(vue.to_components())


#  ⚠️ discord.py sérialise les Components V2 par NUMÉRO, jamais par nom. Un
#  test qui cherche « thumbnail » dans le payload échoue même quand la vignette
#  est là — c'est arrivé en écrivant ce fichier. Les numéros, une fois pour
#  toutes :
TYPE_SECTION = 9
TYPE_TEXTE = 10
TYPE_VIGNETTE = 11
TYPE_GALERIE = 12       # la bannière pleine largeur, celle qu'on ne veut plus


def _types_presents(payload, trouve=None) -> set:
    trouve = trouve if trouve is not None else set()
    for c in payload:
        trouve.add(c.get("type"))
        if c.get("accessory"):
            trouve.add(c["accessory"].get("type"))
        _types_presents(c.get("components", []) or [], trouve)
    return trouve


# ═══════════════════════════════════════════════════════════════════════════════
#  1. L'image ne mange plus l'écran
# ═══════════════════════════════════════════════════════════════════════════════

def test_limage_est_une_vignette_pas_une_banniere():
    """`MediaGallery` prenait toute la largeur : trois fiches remplissaient
    l'écran. `Section` + `Thumbnail` met la même image en petit à droite."""
    types = _types_presents(rp.construire_fiche(
        REQUIEM, "bascules", image=IMAGE).to_components())

    assert TYPE_VIGNETTE in types, "l'image doit être une vignette (Thumbnail)"
    assert TYPE_SECTION in types, "la vignette est portée par une Section"
    assert TYPE_GALERIE not in types, (
        "la galerie pleine largeur ne doit plus être utilisée")


def test_le_nom_napparait_quune_fois():
    """Le titre est porté par la section à vignette OU seul — jamais les deux.

    Le défaut a existé pendant la réécriture : le nom sortait en double.
    """
    vue = rp.construire_fiche(REQUIEM, "bascules", image=IMAGE)
    assert _texte(vue).count("The Requiem") == 1


def test_la_fiche_reste_lisible_sans_image():
    vue = rp.construire_fiche(REQUIEM, "bascules", image=None)
    assert "The Requiem" in _texte(vue)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Toutes les statistiques sont là
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_fiche_porte_les_chiffres_de_trading():
    """La fiche « légère » du 18/08 : prix d'origine, et pour un Limited la
    revente la plus basse et le stock. Plus de favoris, plus d'indice — « ce
    sera tout pour les accessoires »."""
    brut = _texte(rp.construire_fiche(REQUIEM, "bascules", image=IMAGE))

    for attendu in ("Prix d'origine", "Revente la plus basse", "Stock émis"):
        assert attendu in brut, f"champ manquant : {attendu}"
    assert "Indice" not in brut, "le bloc indice a disparu avec le flux « à surveiller »"


def test_la_fiche_dit_quil_VIENT_de_passer_limited():
    """« Tu dis bien qu'il vient de passer Limited » — mot pour mot."""
    brut = _texte(rp.construire_fiche(REQUIEM, "bascules", image=IMAGE))
    assert "VIENT DE PASSER LIMITED" in brut
    assert "détecté à l'instant" in brut


def test_la_fiche_distingue_limited_u():
    brut = _texte(rp.construire_fiche(dict(REQUIEM, limited_u=1), "bascules"))
    assert "VIENT DE PASSER LIMITED U" in brut


def test_la_fiche_dune_nouveaute_le_dit_et_date_la_creation():
    brut = _texte(rp.construire_fiche(dict(REQUIEM, collectionnable=0), "nouveautes"))
    assert "NOUVEL ACCESSOIRE ROBLOX" in brut
    assert "<t:" in brut, "horodatage natif de la création"
    assert "Revente la plus basse" not in brut, (
        "une nouveauté n'est pas un Limited : pas de chiffres de revente")


def test_la_fiche_porte_la_description_de_roblox_courte():
    a = dict(REQUIEM, description="A haunting melody carved in bone. " * 20,
             description_fr="Une mélodie obsédante gravée dans l'os. " * 20)
    brut = _texte(rp.construire_fiche(a, "bascules"))
    assert "Une mélodie obsédante" in brut, "le français de Roblox d'abord"
    assert "A haunting melody" not in brut, "pas les deux langues pour la description"
    assert " …" in brut, "coupée proprement, jamais un pavé"


def test_la_fiche_relie_lannonce_qui_parle_de_laccessoire():
    lies = [{"titre": "New Limited: The Requiem", "lien": "https://devforum.roblox.com/t/1",
             "domaine": "Annonces"}]
    p = rp.construire_fiche(REQUIEM, "bascules", lies=lies).to_components()
    brut = str(p)
    assert "devforum.roblox.com/t/1" in brut, "le bouton 📰 Annonce mène au billet"


def test_les_grands_nombres_sont_lisibles():
    """`107 687` et non `107687` : c'est le chiffre qu'on compare d'une fiche
    à l'autre, collé il se lit de travers."""
    assert rp._fmt_nombre(107687) == "107 687"
    assert rp._fmt_nombre(None) == "—"
    assert rp._fmt_nombre("bizarre") == "bizarre"


def test_gratuit_et_inconnu_ne_se_confondent_pas():
    """Un article offert et un prix inconnu ne se traitent pas pareil quand on
    décide d'acheter."""
    assert rp._fmt_robux(0) == "gratuit"
    assert rp._fmt_robux(None) == "—"
    assert rp._fmt_robux(1800) == "1 800 R$"


def test_un_champ_inconnu_affiche_un_tiret_et_ne_disparait_pas():
    """Une fiche à géométrie variable ne se lit plus en diagonale
    (ROBLOX.md §3)."""
    creux = {"asset_id": 1, "nom": "Sans chiffres", "item_type": "Asset",
             "collectionnable": 1}
    brut = _texte(rp.construire_fiche(creux, "bascules"))

    assert "Stock émis" in brut and "Revente la plus basse" in brut
    assert "—" in brut


# ═══════════════════════════════════════════════════════════════════════════════
#  3. La fiche ne flatte pas — le cœur du « ne pas se faire avoir »
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_bon_multiplicateur_est_annonce():
    brut = _texte(rp.construire_fiche(REQUIEM, "bascules", image=IMAGE))
    assert "×4.5" in brut


def test_un_multiplicateur_PERDANT_est_affiche_quand_meme():
    """LE test qui garde l'honnêteté de la fiche.

    Specter Time Fedora : acheté 3 000 R$, revendu 1 800. Le masquer ferait
    une fiche qui ment par omission — exactement ce que le propriétaire veut
    éviter.
    """
    brut = _texte(rp.construire_fiche(FEDORA_PERDANT, "bascules", image=IMAGE))

    assert "×0.6" in brut
    assert "sous le prix d'origine" in brut, "la conséquence doit être dite en clair"
    assert "🔴" in brut, "et en rouge — pas rangée dans le décor"


def test_le_statut_collectionnable_se_voit():
    assert "Limited" in _texte(rp.construire_fiche(REQUIEM, "bascules"))


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Les limites dures de l'API restent respectées
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("article", [REQUIEM, FEDORA_PERDANT])
@pytest.mark.parametrize("flux", ["nouveautes", "bascules", "surveiller"])
def test_la_fiche_reste_sous_les_limites(article, flux):
    vue = rp.construire_fiche(article, flux, image=IMAGE)
    payload = vue.to_components()

    assert payload, "une vue sans composant est refusée par Discord"
    assert _compter(payload) <= 40, "40 composants maximum — au-delà, HTTP 400"
    assert vue.has_components_v2(), "Components V2, jamais un embed hérité"
    assert isinstance(vue, discord.ui.LayoutView)
