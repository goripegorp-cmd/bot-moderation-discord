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
    """L'interrupteur est OFF ; mais une fois allume, il couvre tout le monde.

    `activite_tout_le_monde` vaut True par defaut DEPUIS 08/2026 : tous les
    membres portent @everyone, exiger de designer un role laissait le systeme
    allume mais aveugle.
    """
    assert activite.CLES_DEFAUT["activite_enabled"] is False
    assert activite.CLES_DEFAUT["activite_tout_le_monde"] is True
    assert activite.CLES_DEFAUT["activite_roles"] == {}


def test_les_sources_historiques_existent_toujours():
    """Message, vocal et reaction sont les trois d'origine : elles ne doivent
    jamais disparaitre au fil des ajouts."""
    for s in (activite.SOURCE_MESSAGE, activite.SOURCE_VOCAL,
              activite.SOURCE_REACTION):
        assert s in activite.SOURCES


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


# ─── calendrier : les bornes de temps ───────────────────────────────────────

import activite_calendrier as cal


def _le(s):
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=cal.FUSEAU)


def test_semaine_commence_le_lundi():
    """Toute date de la semaine doit renvoyer le MÊME lundi 00h00."""
    lundi = _le("2026-08-10")
    for j in range(7):
        d = lundi + timedelta(days=j)
        deb = cal.debut_de_semaine(d)
        assert deb.weekday() == 0, "le début de semaine doit être un lundi"
        assert (deb.hour, deb.minute, deb.second) == (0, 0, 0)
        assert deb.date() == lundi.date()


def test_semaine_change_bien_le_lundi():
    """Dimanche 23h59 et lundi 00h01 ne sont PAS la même semaine."""
    dim = _le("2026-08-16").replace(hour=23, minute=59)
    lun = _le("2026-08-17").replace(hour=0, minute=1)
    assert cal.semaine(dim) != cal.semaine(lun)


def test_semaine_iso_ne_saute_pas_au_nouvel_an():
    """Le piège : du 29/12/2025 au 04/01/2026 = UNE seule semaine.

    Avec %Y au lieu de %G, ces jours porteraient deux identifiants differents
    et le rappel hebdomadaire sauterait une semaine une annee sur deux.
    """
    ids = {cal.semaine(_le(d)) for d in
           ("2025-12-29", "2025-12-31", "2026-01-01", "2026-01-04")}
    assert len(ids) == 1, f"devrait etre une seule semaine, obtenu {ids}"
    assert cal.semaine(_le("2026-01-05")) not in ids


def test_fin_de_semaine_est_le_lundi_suivant():
    d = _le("2026-08-12")
    assert (cal.fin_de_semaine(d) - cal.debut_de_semaine(d)).days == 7
    assert cal.fin_de_semaine(d).weekday() == 0


def test_mois_borne_au_premier():
    for d, n in (("2026-01-15", 31), ("2026-02-10", 28), ("2026-04-30", 30)):
        dt = _le(d)
        assert cal.debut_de_mois(dt).day == 1
        assert cal.fin_de_mois(dt).day == 1
        assert cal.jours_du_mois(dt) == n


def test_mois_passe_bien_a_l_annee_suivante():
    fin = cal.fin_de_mois(_le("2026-12-05"))
    assert (fin.year, fin.month, fin.day) == (2027, 1, 1)


def test_annee_bissextile():
    assert cal.jours_du_mois(_le("2028-02-10")) == 29


def test_prochain_jour_de_semaine_saute_aujourdhui():
    """Demander « prochain lundi » un lundi doit donner le lundi SUIVANT."""
    lundi = _le("2026-08-10")
    suivant = cal.prochain_jour_de_semaine(0, lundi)
    assert suivant.weekday() == 0
    assert (suivant - lundi).days == 7


def test_jours_entre_inconnu_renvoie_none():
    assert cal.jours_entre("pas-une-date") is None


def test_jour_est_stable_dans_la_journee():
    d = _le("2026-08-12")
    assert cal.jour(d.replace(hour=0, minute=1)) == cal.jour(d.replace(hour=23, minute=59))


# ─── les sources : ce qui compte, et surtout ce qui ne compte pas ───────────

def test_six_sources_declarees():
    assert len(activite.SOURCES) == 6
    for lettre in "mvrifs":
        assert lettre in activite.SOURCES


def test_chaque_source_a_une_lettre_unique():
    """Les lettres s'accumulent dans une colonne texte : une collision
    ferait passer un vote de sondage pour un message."""
    assert len(set(activite.SOURCES)) == len(activite.SOURCES)
    for lettre in activite.SOURCES:
        assert len(lettre) == 1


def test_le_statut_en_ligne_n_est_pas_une_source():
    """Garde-fou explicite : être connecte ne doit JAMAIS compter.

    Un telephone oublie allume, un compte secondaire en veille affichent
    « en ligne » sans humain derriere — c'est exactement ce qu'on veut attraper.
    """
    interdits = ("presence", "statut", "status", "online", "en_ligne", "connecte")
    for lettre, nom in activite.SOURCES.items():
        for mot in interdits:
            assert mot not in nom.lower(), f"source suspecte : {nom}"


def test_source_inconnue_est_ignoree():
    """marquer_actif ne doit rien ecrire pour une lettre non declaree."""
    import asyncio
    appels = []

    class _FauxDB:
        async def execute(self, *a, **k): appels.append(a)
        async def commit(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    ancien = activite._get_db
    activite._get_db = lambda: _FauxDB()
    try:
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            activite.marquer_actif(1, 2, "ZZZ"))
    finally:
        activite._get_db = ancien
    assert appels == [], "une source inconnue ne doit rien ecrire"


# ─── configuration INDEPENDANTE par role ────────────────────────────────────

_GLOBAL = {
    "activite_salon_annonce": 111,
    "activite_salon_retour": 222,
    "activite_jour_rappel": 0,
}


def _cfg(roles):
    d = dict(_GLOBAL)
    d["activite_roles"] = roles
    return d


def test_role_herite_du_serveur_quand_rien_nest_defini():
    c = activite.config_du_role(_cfg({"7": {}}), 7)
    assert c["salon_annonce"] == 111
    assert c["salon_retour"] == 222
    assert c["jour_rappel"] == 0
    assert c["rappel"] == activite.SEUIL_RAPPEL_DEFAUT
    assert c["_propres"] == set(), "rien ne doit etre marque comme propre"


def test_role_totalement_independant():
    """Le coeur de la demande : deux roles, deux suivis sans rapport."""
    roles = {
        "1": {"rappel": 3, "retrait": 5, "expulsion": 7,
              "salon_annonce": 900, "jour_rappel": 0},
        "2": {"rappel": 30, "retrait": 60, "expulsion": 90,
              "salon_annonce": 901, "jour_rappel": 4},
    }
    a = activite.config_du_role(_cfg(roles), 1)
    b = activite.config_du_role(_cfg(roles), 2)
    assert (a["rappel"], a["retrait"], a["expulsion"]) == (3, 5, 7)
    assert (b["rappel"], b["retrait"], b["expulsion"]) == (30, 60, 90)
    assert a["salon_annonce"] != b["salon_annonce"]
    assert a["jour_rappel"] != b["jour_rappel"]


def test_reglage_partiel_ne_touche_pas_le_reste():
    """Regler un seul seuil ne doit pas forcer a tout ressaisir."""
    c = activite.config_du_role(_cfg({"5": {"expulsion": 60}}), 5)
    assert c["expulsion"] == 60
    assert c["rappel"] == activite.SEUIL_RAPPEL_DEFAUT
    assert c["salon_annonce"] == 111          # herite
    assert c["_propres"] == {"expulsion"}


def test_role_suspendable_seul():
    """On doit pouvoir mettre UN role en pause sans eteindre le systeme."""
    assert activite.config_du_role(_cfg({"9": {"actif": False}}), 9)["actif"] is False
    assert activite.config_du_role(_cfg({"9": {}}), 9)["actif"] is True


def test_marqueur_de_semaine_est_propre_au_role():
    """Sinon un role relance le lundi bloquerait celui du vendredi."""
    roles = {"1": {"derniere_semaine": "2026-S33"}, "2": {}}
    assert activite.config_du_role(_cfg(roles), 1)["derniere_semaine"] == "2026-S33"
    assert activite.config_du_role(_cfg(roles), 2)["derniere_semaine"] == ""


def test_mode_tout_le_monde_se_configure_comme_un_role():
    c = activite.config_du_role(_cfg({activite.ROLE_TOUS: {"rappel": 2}}),
                                activite.ROLE_TOUS)
    assert c["rappel"] == 2
    assert c["salon_annonce"] == 111


def test_seuils_du_role_reste_compatible():
    """L'ancien nom doit continuer de marcher : du code l'appelle encore."""
    c = activite.seuils_du_role(_cfg({"3": {"rappel": 4}}), 3)
    assert c["rappel"] == 4 and "retirer_role" in c


# ─── tout le monde par defaut + dispenses ───────────────────────────────────

class _Membre2:
    def __init__(self, mid, roles=(), bot=False):
        self.id = mid
        self.roles = [_Role(r) for r in roles]
        self.bot = bot


def test_tout_le_monde_est_le_defaut():
    """Tous les membres portent @everyone : exiger un role rendait le systeme
    allumé mais aveugle, sans que ca se voie."""
    assert activite.CLES_DEFAUT["activite_tout_le_monde"] is True


def test_systeme_reste_eteint_par_defaut():
    """Couvrir tout le monde ne veut pas dire demarrer tout seul."""
    assert activite.CLES_DEFAUT["activite_enabled"] is False


def test_dispenses_vides_par_defaut():
    assert activite.CLES_DEFAUT["activite_roles_immunises"] == []
    assert activite.CLES_DEFAUT["activite_membres_immunises"] == []


def test_role_dispense_est_ecarte():
    cfg = {"activite_roles_immunises": [42], "activite_membres_immunises": []}
    assert activite.est_dispense(_Membre2(1, roles=[42]), cfg) is True
    assert activite.est_dispense(_Membre2(2, roles=[7]), cfg) is False


def test_membre_dispense_est_ecarte():
    cfg = {"activite_roles_immunises": [], "activite_membres_immunises": [99]}
    assert activite.est_dispense(_Membre2(99), cfg) is True
    assert activite.est_dispense(_Membre2(98), cfg) is False


def test_dispense_fail_closed_si_liste_illisible():
    """Une liste corrompue doit DISPENSER, jamais exposer a l'expulsion."""
    cfg = {"activite_roles_immunises": ["pas-un-nombre"]}
    assert activite.est_dispense(_Membre2(1, roles=[1]), cfg) is True


def test_dispense_accepte_les_identifiants_en_texte():
    """Discord renvoie souvent des identifiants en chaine : ils doivent marcher."""
    cfg = {"activite_roles_immunises": ["42"], "activite_membres_immunises": ["99"]}
    assert activite.est_dispense(_Membre2(1, roles=[42]), cfg) is True
    assert activite.est_dispense(_Membre2(99), cfg) is True


def test_dispense_ne_touche_pas_la_moderation():
    """Les deux listes sont distinctes : dispenser de PRESENCE ne doit pas
    dispenser des filtres anti-spam."""
    for cle in activite.CLES_DEFAUT:
        assert not cle.startswith("immune_"), (
            "les dispenses d'activite ne doivent pas reutiliser les cles "
            "d'immunite de moderation")
