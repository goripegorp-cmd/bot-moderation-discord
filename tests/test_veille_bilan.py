"""« 0 publication » doit dire POURQUOI — défaut signalé le 19/08.

LE SYMPTÔME, LOGS RAILWAY DU PROPRIÉTAIRE
    [veille_roblox_task] passage terminé — … · 0 publication(s) réelle(s)
onze heures durant, toutes les 30 minutes, sans autre indication. Et son
constat : « on a toutes les infos mais rien n'est posté ».

⚠️ LE DÉFAUT N'ÉTAIT PAS DANS LA PUBLICATION, IL ÉTAIT DANS LE BILAN.
« 0 publication » recouvrait six situations dont une seule est une panne :
sources injoignables · billets tous déjà publiés · tous jugés « pointeurs » ·
cadence qui saute les sources · flux allumé sans salon · rien de neuf. Le
propriétaire ne pouvait pas trancher, donc il a supposé la panne — la
supposition la plus coûteuse.

MESURE DU JOUR (outils/sonde_pourquoi_zero.py, appels réseau réels)
    7/7 sources joignables · 19 billets publiables · 3 pointeurs écartés
    catalogue : HTTP 200, 964 articles — le PLUS RÉCENT a 670 h (28 jours)
Donc : côté accessoires, zéro est la BONNE réponse (Roblox n'en crée pas) ;
côté actualités, la matière existe et la cause est en aval du relevé.

CE QUI EST VERROUILLÉ ICI
Les compteurs par étage, la ligne par serveur quand rien n'est publié, et le
décorateur de la boucle — que j'ai moi-même décollé en posant ce correctif.
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _fonction(nom: str):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable au niveau module de bot.py")


BOUCLE = ast.unparse(_fonction("veille_roblox_task"))


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le bilan décompose au lieu de totaliser
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_bilan_compte_les_accessoires_etage_par_etage():
    """Sans ces compteurs, « 0 publication » ne distingue pas « rien de neuf »
    de « tout écarté par la fenêtre » ni de « salon interdit »."""
    for etage in ("lus", "candidats", "hors_fenetre", "deja", "echecs"):
        assert f"'{etage}'" in BOUCLE or f'"{etage}"' in BOUCLE, (
            f"l'étage « {etage} » n'est plus compté")


def test_le_bilan_compte_les_actualites_etage_par_etage():
    for etage in ("sautees", "pannes"):
        assert f"'{etage}'" in BOUCLE or f'"{etage}"' in BOUCLE, (
            f"l'étage « {etage} » n'est plus compté")


def test_un_envoi_rate_est_compte_et_pas_confondu_avec_rien_a_publier():
    """⚠️ `publier` et `publier_actu` AVALENT leurs erreurs et rendent None.
    Sans un `else` qui compte, un salon devenu interdit est indiscernable de
    « il n'y avait rien à publier » — c'est-à-dire d'un bot en bonne santé."""
    assert BOUCLE.count("echecs'] += 1") + BOUCLE.count('echecs"] += 1') >= 2, (
        "les échecs d'envoi doivent être comptés des DEUX côtés")


def test_le_quota_par_source_est_compte_pas_tu():
    """⚠️ LE BILAN DOIT S'ADDITIONNER. `ordonner_publication` ne garde que les
    N plus récents de chaque source ; les autres ne passent devant AUCUNE des
    portes comptées, donc ils n'apparaissaient nulle part. Mesuré sur Railway
    le 19/08 : « 11 lus · 6 déjà publiés · 0 publication » — cinq billets
    semblaient s'évaporer. Ils ne s'évaporent pas (ils repassent au tour
    suivant), mais un bilan qui ne se boucle pas fait chercher une panne là où
    il n'y en a pas."""
    assert BOUCLE.count("plafonnes'] += ") + BOUCLE.count('plafonnes"] += ') >= 2, (
        "le quota doit être compté des DEUX côtés (accessoires et actualités)")
    bilan = BOUCLE.split("passage terminé")[-1]
    assert "quota" in bilan, "le quota doit apparaître dans le bilan imprimé"


def test_le_lot_est_calcule_une_seule_fois():
    """Rappeler `ordonner_publication` pour compter donnerait deux listes
    potentiellement différentes — et un compteur faux."""
    for cle in ("_lot_a", "_lot_b"):
        assert BOUCLE.count(f"{cle} = ") == 1, f"{cle} doit être calculé une fois"


def test_le_bilan_sort_le_detail_meme_quand_rien_ne_deborde():
    """Le détail ne doit pas être conditionné à un débordement : c'est quand
    RIEN ne sort qu'on en a besoin."""
    bilan = BOUCLE.split("passage terminé")[-1]
    assert "accessoires :" in bilan
    assert "actualités :" in bilan


# ═══════════════════════════════════════════════════════════════════════════════
#  2. L'état des serveurs sort quand le passage est vide
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_diagnostic_par_serveur_est_une_fonction_reutilisable():
    """Il était ENFERMÉ dans le cas « personne n'a rien allumé ». Or le cas qui
    fait mal est l'autre : un flux allumé, l'autre éteint, zéro publication."""
    corps = ast.unparse(_fonction("_diag_veille_serveurs"))
    assert "roblox_veille_enabled" in corps
    assert "roblox_news_enabled" in corps
    assert "AUCUN salon" in corps, (
        "il doit distinguer « éteint » de « allumé mais sans salon »")


def test_zero_publication_declenche_le_diagnostic_par_serveur():
    """⚠️ LA LIGNE QUI A COÛTÉ ONZE HEURES. Sans elle, le propriétaire lit
    « 0 publication » et ne peut pas savoir qu'un flux est simplement éteint."""
    assert "_publies == 0" in BOUCLE
    apres = BOUCLE.split("_publies == 0")[-1][:200]
    assert "_diag_veille_serveurs" in apres


def test_le_diagnostic_sort_aussi_quand_personne_na_rien_allume():
    avant = BOUCLE.split("_publies = 0")[0]
    assert "_diag_veille_serveurs" in avant


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le piège n°1 — je l'ai reposé en écrivant ce correctif
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_boucle_a_toujours_son_decorateur():
    """⚠️ EN POSANT CE CORRECTIF LE 19/08, j'ai ancré l'insertion du helper sur
    « async def veille_roblox_task(): » — donc APRÈS `@tasks.loop`. Le
    décorateur s'est recollé au helper et la boucle ne tournait plus. Le piège
    n°1 du dépôt, reposé par le correctif censé aider. Ce test l'avait déjà
    attrapé une fois ; il reste ici parce qu'il l'attrapera encore."""
    n = _fonction("veille_roblox_task")
    deco = [ast.unparse(d) for d in n.decorator_list]
    assert any("tasks.loop" in d for d in deco), (
        "la boucle a perdu son @tasks.loop : elle ne tournera jamais")


def test_le_helper_na_pas_vole_le_decorateur():
    """L'autre moitié du même piège : le helper ne doit RIEN porter."""
    assert not _fonction("_diag_veille_serveurs").decorator_list, (
        "le helper porte un décorateur — il a probablement volé celui de la boucle")


def test_le_helper_est_declare_avant_la_boucle():
    """Pas une exigence de Python, mais la preuve que l'insertion s'est faite
    au bon endroit : le helper AVANT le décorateur, jamais entre les deux."""
    assert SRC.index("async def _diag_veille_serveurs") < SRC.index(
        "async def veille_roblox_task")
