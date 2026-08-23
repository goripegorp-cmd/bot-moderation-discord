"""Le HTTP 429 systématique de la veille — corrigé le 20/08/2026.

LE SYMPTÔME, LOGS RAILWAY
    [roblox_veille] HTTP 429 sur details — attente 25 s puis reprise
à CHAQUE passage, 48 fois par jour, soit 20 minutes quotidiennes passées en
pénalité. Repris à chaque fois, donc jamais fatal — mais un 429 récurrent est
exactement le motif qui fait finir par blacklister une IP d'hébergeur.

⚠️ LA CAUSE N'ÉTAIT PAS CELLE QU'ON CROYAIT, ET L'ARITHMÉTIQUE LE PROUVE.
Deux correctifs successifs (15 s puis 30 s de `PAUSE_ENTRE_RELEVES`) avaient
échoué parce qu'ils traitaient la mauvaise cause. L'intuition « 9 pages à 2 s
font 30 requêtes/minute, donc on dépasse les 12/60 s » est FAUSSE par
comptage : 9 pages en 16 s ne mettent jamais plus de 9 requêtes dans une
fenêtre de 60 s. Un débit tenu 16 secondes n'est pas un débit par minute.

Le vrai coupable : `PAUSE_ENTRE_RELEVES = 30 s` est la MOITIÉ de la fenêtre.
Les 9 pages du premier relevé (t = 0…16 s) sont donc TOUJOURS comptées quand le
second relevé tire à t = 46 s — pic de 10 puis 11 requêtes sur un budget de 12.
D'où un 429 qui tombe toujours sur le second relevé, jamais sur le premier :
c'est pour ça que le bilan affichait « 964 lu(s) » à chaque passage.

LA RÈGLE QUI GOUVERNE TOUT ÇA
Le nombre maximal de requêtes qu'une cadence de `s` secondes peut placer dans
une fenêtre de 60 s vaut `floor(60/s) + 1`. C'est elle qui dit pourquoi passer
les pages de 2 s à 5 ou 6 s n'aurait retiré AUCUNE requête du pic.
"""
from __future__ import annotations

import math

import pytest

import roblox_veille as veille


def _max_par_fenetre(s: float, fenetre: float = 60.0) -> int:
    """Combien de requêtes une cadence de `s` s met au plus dans `fenetre`."""
    return math.floor(fenetre / s) + 1


# ═══════════════════════════════════════════════════════════════════════════════
#  1. L'arithmétique qui justifie les constantes
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_pause_entre_releves_depasse_la_fenetre():
    """⚠️ LE CŒUR DU CORRECTIF. Sous 60 s, le second relevé démarre pendant que
    le premier compte encore : c'est ce qui produisait le 429, et ce que deux
    correctifs précédents (15 s puis 30 s) n'avaient pas vu."""
    assert veille.PAUSE_ENTRE_RELEVES > 60.0, (
        "sous une fenêtre pleine, les deux relevés se cumulent")


@pytest.mark.parametrize("s,attendu", [(2, 31), (5, 13), (6, 11), (7, 9), (8, 8)])
def test_la_regle_de_cadence(s, attendu):
    """La formule qui démolit l'intuition « 5 ou 6 secondes suffisent » : à ces
    cadences, les 9 pages tiennent encore dans une seule fenêtre."""
    assert _max_par_fenetre(s) == attendu


def test_la_cadence_du_catalogue_tient_sous_le_budget():
    """8 s ⇒ 8 requêtes par fenêtre au plus, sur un budget mesuré de 12. Les
    4 places restantes sont pour les autres applications de l'IP partagée."""
    n = _max_par_fenetre(veille.PAUSE_ENTRE_APPELS_CATALOGUE)
    assert n <= 8, f"cadence trop rapide : {n} requêtes possibles par fenêtre"


def test_la_cadence_du_catalogue_borne_aussi_les_pages_futures():
    """⚠️ BOMBE DÉSAMORCÉE. Le plafond par fenêtre ne dépend PAS du nombre de
    pages : quand le catalogue Roblox dépassera ~1320 accessoires, le relevé ne
    se mettra pas en 429 tout seul — ce qu'il aurait fait à 2 s/page, en
    tronquant en silence."""
    pire = veille.MAX_PAGES_PAR_RELEVE
    assert _max_par_fenetre(veille.PAUSE_ENTRE_APPELS_CATALOGUE) <= 12
    assert pire >= 9, "le plafond de pages doit rester au-dessus du catalogue réel"


def test_les_autres_chemins_ne_sont_pas_ralentis():
    """⚠️ Le seau est PAR CHEMIN. `enrichir` tape economy.roblox.com, mesuré à
    1000 requêtes/60 s : le ralentir aurait allongé un passage avec
    publications de plusieurs minutes pour corriger un budget consommé à 1 %."""
    assert veille.PAUSE_ENTRE_APPELS == 2.0
    assert veille.PAUSE_ENTRE_APPELS_CATALOGUE > veille.PAUSE_ENTRE_APPELS


def test_le_passage_reste_tres_loin_de_la_boucle():
    """La boucle passe toutes les 30 min. Le relevé ralenti doit rester une
    petite fraction de ce budget, sinon on remplace un défaut par un autre."""
    duree = (9 * veille.PAUSE_ENTRE_APPELS_CATALOGUE
             + veille.PAUSE_ENTRE_RELEVES
             + 2 * veille.PAUSE_ENTRE_APPELS_CATALOGUE)
    assert duree < 300, f"un passage prendrait {duree:.0f} s"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. L'attente après 429 : ce que Roblox ANNONCE, pas un pari
# ═══════════════════════════════════════════════════════════════════════════════

def test_lattente_suit_len_tete_retry_after():
    """25 s en dur était à la fois 5× trop long face à `retry-after: 5` et 2×
    trop court face à `x-ratelimit-reset: 49`. C'était un pari."""
    assert veille._attente_429({"Retry-After": "5"}) == pytest.approx(7.0)


def test_lattente_retombe_sur_le_reset_si_retry_after_manque():
    assert veille._attente_429({"x-ratelimit-reset": "49"}) == pytest.approx(51.0)


def test_lattente_est_bornee_par_la_fenetre():
    """Au-delà d'une fenêtre, attendre n'apporte plus rien."""
    assert veille._attente_429({"Retry-After": "9999"}) == veille.ATTENTE_429_MAX


def test_lattente_a_un_plancher():
    """Un en-tête à 0 ferait retenter immédiatement, donc re-429 aussitôt."""
    assert veille._attente_429({"Retry-After": "0"}) == veille.ATTENTE_APRES_429
    assert veille._attente_429({"Retry-After": "1"}) == veille.ATTENTE_429_MIN


def test_sans_en_tete_on_garde_le_repli_en_dur():
    """⚠️ LE REPLI DOIT RESTER. Rien ne prouve que ces en-têtes traversent le
    proxy de Railway ; leur absence est le cas NOMINAL, pas une anomalie."""
    assert veille._attente_429({}) == veille.ATTENTE_APRES_429
    assert veille._attente_429(None) == veille.ATTENTE_APRES_429


def test_un_en_tete_illisible_ne_fait_pas_planter():
    assert veille._attente_429({"Retry-After": "bientôt"}) == veille.ATTENTE_APRES_429


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le budget observé — la seule chose qui accuse l'IP partagée
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_reste_minimum_est_retenu():
    """⚠️ SANS CE CHIFFRE, on ne peut pas distinguer « notre cadence est trop
    rapide » de « un voisin de l'IP Railway a mangé le budget »."""
    s = {}
    veille._noter_budget(s, {"x-ratelimit-remaining": "9"})
    veille._noter_budget(s, {"x-ratelimit-remaining": "3"})
    veille._noter_budget(s, {"x-ratelimit-remaining": "7"})
    assert s["reste_min"] == 3


def test_sans_en_tete_on_ne_note_pas_un_zero_trompeur():
    """Un 0 inventé ferait croire au budget épuisé alors qu'on n'en sait rien."""
    s = {}
    veille._noter_budget(s, {})
    assert s.get("reste_min") is None


def test_le_compteur_survit_a_une_absence_de_stats():
    veille._noter_budget(None, {"x-ratelimit-remaining": "1"})   # ne lève pas
