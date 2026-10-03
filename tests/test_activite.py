"""Tests du COMPTAGE d'activité — la logique pure, sans Discord ni base.

Le système d'activité (paliers, rôles AFK, masquage, rappels) est retiré depuis
le 03/10/2026 ; ne reste que le comptage des jours, pour le bouton « Activité »
de /rellseas. On teste le calcul des jours, le calendrier et les sources.
"""
from datetime import datetime, timedelta, timezone

import activite


# ─── jours_ecoules : le calcul dont tout dépend ─────────────────────────────

def _il_y_a(n):
    """Date d'il y a n jours, DANS LE MÊME FUSEAU que le système.

    ⚠️ Ce helper utilisait `datetime.now(timezone.utc)` alors que le système
    compte les journées en heure de Paris. Entre 22h et minuit UTC en été, les
    deux fuseaux sont sur des jours DIFFÉRENTS : le test échouait d'un jour, et
    seulement à ces heures-là. La CI l'a attrapé en tournant à 22h10 UTC.
    Toute date de test doit passer par `activite_calendrier`.
    """
    import activite_calendrier as _cal
    return _cal.jour(_cal.maintenant() - timedelta(days=n))


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


# ─── choix du rôle quand le membre en cumule plusieurs ──────────────────────

class _Role:
    def __init__(self, rid):
        self.id = rid


class _Membre:
    def __init__(self, roles):
        self.roles = roles


# ─── le message envoye aux inactifs ─────────────────────────────────────────
#
#  On teste la fabrique de LIGNES et le contenu, pas le rendu Discord : le
#  panneau lui-meme exige discord.py, absent de l'environnement de test pur.

class _MembreMention:
    def __init__(self, n):
        self.mention = f"<@{n}>"


def _fiche(jours, n=0):
    return {"member": _MembreMention(n), "jours": jours}


# ─── garde-fous ─────────────────────────────────────────────────────────────


# ─── récompenses : la courbe de niveaux ─────────────────────────────────────


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


# ─── tout le monde par defaut + dispenses ───────────────────────────────────

class _Membre2:
    def __init__(self, mid, roles=(), bot=False):
        self.id = mid
        self.roles = [_Role(r) for r in roles]
        self.bot = bot


# ─── restitution : le role de clan ne revient pas tout seul ─────────────────


