"""Tests du système d'activité — la logique pure, sans Discord ni base.

On teste ce qui DÉCIDE : le calcul des jours, le choix des seuils, le tri des
paliers et le texte envoyé. Le reste (écriture en base, appels API) est du
câblage, couvert par la CI d'import.
"""
from datetime import datetime, timedelta, timezone

import pytest

import activite
import activite_escalade as esc


# ─── jours_ecoules : le calcul dont tout dépend ─────────────────────────────

def _il_y_a(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime(activite.JOUR_FMT)


def test_jours_ecoules_aujourdhui():
    assert activite.jours_ecoules(_il_y_a(0)) == 0


def test_jours_ecoules_une_semaine():
    assert activite.jours_ecoules(_il_y_a(7)) == 7


def test_jours_ecoules_inconnu_renvoie_none():
    """None, jamais 0 : un 0 ferait passer un membre jamais vu pour actif du jour."""
    assert activite.jours_ecoules(None) is None
    assert activite.jours_ecoules("") is None
    assert activite.jours_ecoules("pas-une-date") is None


def test_jours_ecoules_jamais_negatif():
    futur = (datetime.now(timezone.utc) + timedelta(days=5)).strftime(activite.JOUR_FMT)
    assert activite.jours_ecoules(futur) == 0


# ─── seuils par rôle ────────────────────────────────────────────────────────

def test_seuils_defaut_si_role_inconnu():
    s = activite.seuils_du_role({"activite_roles": {}}, 123)
    assert s["rappel"] == activite.SEUIL_RAPPEL_DEFAUT
    assert s["retrait"] == activite.SEUIL_RETRAIT_DEFAUT
    assert s["expulsion"] == activite.SEUIL_EXPULSION_DEFAUT
    assert s["retirer_role"] is True


def test_seuils_personnalises_par_role():
    cfg = {"activite_roles": {"42": {"rappel": 3, "retrait": 5, "expulsion": 9}}}
    s = activite.seuils_du_role(cfg, 42)
    assert (s["rappel"], s["retrait"], s["expulsion"]) == (3, 5, 9)


def test_seuils_partiels_completes_par_defaut():
    cfg = {"activite_roles": {"42": {"rappel": 2}}}
    s = activite.seuils_du_role(cfg, 42)
    assert s["rappel"] == 2
    assert s["retrait"] == activite.SEUIL_RETRAIT_DEFAUT


def test_retrait_role_desactivable():
    cfg = {"activite_roles": {"42": {"retirer_role": False}}}
    assert activite.seuils_du_role(cfg, 42)["retirer_role"] is False


# ─── choix du rôle quand le membre en cumule plusieurs ──────────────────────

class _Role:
    def __init__(self, rid):
        self.id = rid


class _Membre:
    def __init__(self, roles):
        self.roles = roles


def test_role_surveille_prend_le_plus_exigeant():
    """Deux rôles surveillés → celui dont l'expulsion tombe le plus tôt gagne."""
    cfg = {"activite_roles": {
        "1": {"expulsion": 30},
        "2": {"expulsion": 10},
    }}
    m = _Membre([_Role(1), _Role(2)])
    assert activite.role_surveille_du_membre(m, cfg).id == 2


def test_role_surveille_none_si_aucun():
    cfg = {"activite_roles": {"1": {}}}
    assert activite.role_surveille_du_membre(_Membre([_Role(9)]), cfg) is None


# ─── le texte envoyé aux inactifs ───────────────────────────────────────────

class _MembreMention:
    def __init__(self, n):
        self.mention = f"<@{n}>"


def _fiches(n, jours=8):
    return [{"member": _MembreMention(i), "jours": jours + i} for i in range(n)]


def test_texte_rappel_vide_si_personne():
    assert esc.texte_rappel([]) == ""


def test_texte_rappel_mentionne_bien():
    """Le propriétaire a explicitement demandé le ping : il doit être là."""
    t = esc.texte_rappel(_fiches(2))
    assert "<@0>" in t and "<@1>" in t


def test_texte_rappel_tronque_au_dela_de_40():
    t = esc.texte_rappel(_fiches(45))
    assert "et 5 autre(s)" in t
    assert t.count("•") == 40


def test_texte_rappel_retrait_annonce_la_restitution():
    """Le membre doit comprendre que ce n'est pas définitif."""
    t = esc.texte_rappel(_fiches(1), avec_retrait=True)
    assert "veille" in t.lower()
    assert "rendu" in t.lower()


def test_texte_rappel_cite_les_trois_sources():
    t = esc.texte_rappel(_fiches(1))
    for mot in ("message", "vocal", "réagir"):
        assert mot in t.lower()


# ─── garde-fous ─────────────────────────────────────────────────────────────

def test_plafond_actions_est_raisonnable():
    """Trop bas, le système ne fait rien ; trop haut, un bug vide le serveur."""
    assert 5 <= activite.PLAFOND_ACTIONS_PAR_PASSAGE <= 100


def test_systeme_desactive_par_defaut():
    assert activite.CLES_DEFAUT["activite_enabled"] is False
    assert activite.CLES_DEFAUT["activite_tout_le_monde"] is False
    assert activite.CLES_DEFAUT["activite_roles"] == {}


def test_les_trois_sources_existent():
    assert set(activite.SOURCES) == {
        activite.SOURCE_MESSAGE, activite.SOURCE_VOCAL, activite.SOURCE_REACTION}


# ─── récompenses : la courbe de niveaux ─────────────────────────────────────

import activite_recompenses as rec


def test_niveau_zero_si_jamais_actif():
    """0, pas 1 : un membre jamais vu n'est pas « niveau 1 par défaut »."""
    assert rec.niveau_pour(0) == 0
    assert rec.niveau_pour(-5) == 0


def test_niveau_croit_avec_les_jours():
    precedent = -1
    for j in (1, 3, 7, 14, 21, 30, 45, 60, 90, 120, 150, 180, 240, 300, 365):
        n = rec.niveau_pour(j)
        assert n > precedent, f"{j} jours devrait dépasser le palier précédent"
        precedent = n


def test_niveau_et_jours_sont_reciproques():
    for n in range(1, 20):
        j = rec.jours_pour_niveau(n)
        assert rec.niveau_pour(j) == n, f"niveau {n} <-> {j} jours"


def test_niveau_continue_au_dela_du_dernier_palier():
    base = rec.niveau_pour(rec.PALIERS[-1])
    assert rec.niveau_pour(rec.PALIERS[-1] + rec.JOURS_PAR_NIVEAU_AU_DELA) == base + 1


def test_progression_bornee():
    for j in (0, 1, 37, 200, 1000):
        p = rec.progression(j)
        assert 0 <= p["pourcent"] <= 100
        assert p["reste"] >= 0
        assert p["prochain_a"] > j or j == 0


def test_recompenses_desactivees_par_defaut():
    assert rec.CLES_DEFAUT["activite_recompenses_enabled"] is False
    assert rec.CLES_DEFAUT["activite_vip_role"] == 0


def test_vip_par_defaut_demande_un_mois():
    """Le VIP doit se mériter : le défaut vise ~30 jours de présence."""
    assert rec.jours_pour_niveau(rec.CLES_DEFAUT["activite_vip_niveau"]) >= 30
