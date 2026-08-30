"""L'ORDRE des publications — du plus ancien au plus récent.

DEMANDE DU PROPRIÉTAIRE (16/08)
    « Mets le plus ancien posté en premier jusqu'au plus récent. Comme ça, ça
    évite que quand on scroll on voie un vieil item avec un nouveau. »

LE POINT QUI SE TROMPE FACILEMENT
Discord empile les messages du plus ancien EN HAUT au plus récent EN BAS. Pour
qu'un salon se lise de haut en bas dans l'ordre, il faut donc ENVOYER le plus
ancien d'abord — l'inverse de l'intuition.

Mais le relevé, lui, doit rester trié du plus RÉCENT au plus ancien : c'est ce
tri-là qui décide QUELS articles entrent dans la tranche. Prendre les 30
premiers d'une liste croissante donnerait les 30 plus VIEUX du catalogue.

Deux tris opposés, dans un ordre non interchangeable :
  1. sélectionner sur la liste décroissante ;
  2. inverser la tranche retenue pour l'envoi.

Ces tests tiennent les deux bouts. Se tromper sur l'un donne un salon illisible,
se tromper sur l'autre fait suivre les mauvais articles.
"""
from __future__ import annotations

import ast
from pathlib import Path

import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PAN = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")


def _art(nom: str, date: str) -> dict:
    return {"asset_id": abs(hash(nom)) % 10**9, "nom": nom, "cree_le": date}


CATALOGUE = [
    _art("très vieux", "2024-01-01T00:00:00Z"),
    _art("vieux", "2025-01-01T00:00:00Z"),
    _art("moyen", "2025-06-01T00:00:00Z"),
    _art("récent", "2026-03-01T00:00:00Z"),
    _art("tout frais", "2026-08-01T00:00:00Z"),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  1. L'ordre d'envoi
# ═══════════════════════════════════════════════════════════════════════════════

def test_lenvoi_va_du_plus_ancien_au_plus_recent():
    noms = [a["nom"] for a in veille.ordonner_publication(CATALOGUE, 5)]
    assert noms == ["très vieux", "vieux", "moyen", "récent", "tout frais"], (
        "le plus ancien doit partir EN PREMIER : Discord empile vers le bas")


def test_lordre_ne_depend_pas_de_lordre_dentree():
    """La liste arrive parfois fusionnée (nouveautés + collectionnables) :
    son ordre n'est plus garanti, la fonction ne doit pas s'y fier."""
    melange = [CATALOGUE[2], CATALOGUE[0], CATALOGUE[4], CATALOGUE[1], CATALOGUE[3]]
    noms = [a["nom"] for a in veille.ordonner_publication(melange, 5)]
    assert noms == ["très vieux", "vieux", "moyen", "récent", "tout frais"]


# ═══════════════════════════════════════════════════════════════════════════════
#  2. La sélection reste sur les plus RÉCENTS — le piège de l'inversion
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_tranche_retient_les_plus_recents_pas_les_plus_vieux():
    """LE défaut qu'on aurait introduit en inversant trop tôt.

    Si l'on triait croissant AVANT de couper, une tranche de 2 rendrait
    « très vieux » et « vieux » — on suivrait les archives au lieu de
    l'actualité.
    """
    noms = [a["nom"] for a in veille.ordonner_publication(CATALOGUE, 2)]
    assert set(noms) == {"récent", "tout frais"}, (
        "la tranche doit retenir les plus RÉCENTS")
    assert noms == ["récent", "tout frais"], (
        "... et les envoyer quand même du plus ancien au plus récent")


def test_une_tranche_plus_large_que_la_liste_ne_perd_personne():
    assert len(veille.ordonner_publication(CATALOGUE, 99)) == len(CATALOGUE)


def test_les_cas_vides_ne_cassent_rien():
    assert veille.ordonner_publication([], 5) == []
    assert veille.ordonner_publication(CATALOGUE, 0) == []
    assert veille.ordonner_publication(CATALOGUE, -3) == []


def test_une_date_illisible_ne_fait_pas_disparaitre_larticle():
    """Fail-open : on préfère un ordre approximatif sur une fiche à une fiche
    tue. Elle part en tête, avec les plus anciens."""
    avec_trou = CATALOGUE + [_art("sans date", None)]
    noms = [a["nom"] for a in veille.ordonner_publication(avec_trou, 10)]
    assert "sans date" in noms
    assert noms[0] == "sans date"


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le câblage — la fonction doit être RÉELLEMENT utilisée
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_boucle_publie_dans_lordre():
    arbre = ast.parse(SRC_BOT)
    for n in ast.walk(arbre):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            corps = ast.unparse(n)
            #  ⚠️ SEUIL RAMENÉ DE 3 À 2 LE 30/08 — ET LA DOCTRINE EST PLUS
            #  FORTE, PAS PLUS FAIBLE. Le troisième appel ordonnait le lot des
            #  VIGNETTES, dont l'ordre n'a jamais rien produit de visible : ce
            #  lot ne sert qu'à demander des images en un seul appel. Depuis la
            #  file d'attente, il ne regroupe même plus que les articles qu'on
            #  va réellement envoyer, dédoublonnés — l'ordonner n'aurait aucun
            #  sens. Restent les deux appels qui décident d'un salon : les
            #  articles (à l'entrée en file) et les actualités.
            assert corps.count("ordonner_publication") >= 2, (
                "articles ET actualités doivent passer par l'ordre")
            #  Et la propriété que l'ancien seuil ne vérifiait pas : c'est
            #  l'ENTRÉE en file qui est ordonnée, donc l'ordre survit au
            #  plafond du passage et au redémarrage.
            i_ordre = corps.index("ordonner_publication")
            i_enfiler = corps.index("roblox_module.enfiler(")
            assert i_ordre < i_enfiler, (
                "on ordonne AVANT de mettre en file : la file se vide dans "
                "l'ordre d'entrée, donc l'ordonner après ne servirait à rien")
            return
    raise AssertionError("veille_roblox_task introuvable")


def test_le_bouton_publie_dans_lordre():
    assert SRC_PAN.count("ordonner_publication") >= 2, (
        "le bouton « Relever maintenant » doit suivre le même ordre que la "
        "boucle, sinon les deux chemins donnent des salons différents")


def test_plus_aucune_tranche_brute_ne_subsiste():
    """Une tranche `[:5]` oubliée quelque part rendrait l'ordre incohérent
    entre les flux."""
    for interdit in ('(evts.get(cle) or [])[:', '(evts.get(k) or [])[:',
                     'rel["billets"][:'):
        assert interdit not in SRC_BOT, f"tranche brute restante : {interdit}"
        assert interdit not in SRC_PAN, f"tranche brute restante : {interdit}"
