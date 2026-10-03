"""Tests de l'ANCRE D'OBSERVATION de la mesure de présence (/rellseas).

Né d'un incident de production réel (12/08/2026) : un membre inscrit depuis
400 jours mais jamais observé passait pour absent depuis 400 jours. La règle :
**on ne compte jamais une journée antérieure au début du comptage**. Le système
d'activité est retiré depuis le 03/10/2026 ; la mesure, lue par le bouton
« Activité » de /rellseas, garde cette règle.
"""
import asyncio
import datetime as dt

import pytest

import activite
import activite_calendrier as cal


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _il_y_a(n):
    return cal.jour(cal.maintenant() - dt.timedelta(days=n))


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux socle : configuration en memoire + journal d'activite en memoire
# ═══════════════════════════════════════════════════════════════════════════════

class _Socle:
    """Remplace la base et la config. Enregistre ce qui est ecrit."""

    def __init__(self, config=None, journal=None):
        #  Ce que la mesure lit de la configuration, et rien d'autre.
        self.config = {"activite_observe_depuis": "",
                       "activite_fenetre": activite.FENETRE_PRESENCE_DEFAUT}
        self.config.update(config or {})
        self.journal = journal or {}          # user_id -> set de jours
        self.ecrits = []

    #  --- interface attendue par activite.setup ---
    async def cfg(self, gid):
        return self.config

    async def db_set(self, gid, cle, val):
        self.ecrits.append((cle, val))
        self.config[cle] = val

    def get_db(self):
        return _FauxDB(self)


class _Curseur:
    def __init__(self, lignes, une=False):
        self._l, self._une = lignes, une

    async def fetchone(self):
        return self._l[0] if self._l else None

    async def fetchall(self):
        return self._l

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FauxDB:
    def __init__(self, socle):
        self.s = socle

    def execute(self, sql, p=()):
        haut = " ".join(sql.split()).upper()
        if haut.startswith("SELECT"):
            if "MIN(JOUR)" in haut:
                tous = set().union(*self.s.journal.values()) if self.s.journal else set()
                return _Curseur([(min(tous),)] if tous else [(None,)])
            if "MAX(JOUR)" in haut:
                j = self.s.journal.get(p[1]) or set()
                return _Curseur([(max(j),)] if j else [(None,)])
            if "BETWEEN" in haut:
                j = self.s.journal.get(p[1]) or set()
                return _Curseur([(x,) for x in sorted(j) if p[2] <= x <= p[3]])
            if "DOUX" in haut:
                return _Curseur([(0, "")])
            return _Curseur([])

        async def _rien():
            return None

        class _R:
            def __await__(self_):
                return _rien().__await__()

            async def __aenter__(self_):
                return _Curseur([])

            async def __aexit__(self_, *a):
                return False
        return _R()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def socle(monkeypatch):
    s = _Socle()

    monkeypatch.setattr(activite, "_cfg", s.cfg)
    monkeypatch.setattr(activite, "_db_set", s.db_set)
    monkeypatch.setattr(activite, "_get_db", s.get_db)
    return s


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux Discord, reduit au strict necessaire
# ═══════════════════════════════════════════════════════════════════════════════

class _Perms:
    administrator = False


class _Membre:
    bot = False

    def __init__(self, uid, arrive_il_y_a=400):
        self.id = uid
        self.mention = f"<@{uid}>"
        self.roles = []
        self.guild_permissions = _Perms()
        self.joined_at = cal.maintenant() - dt.timedelta(days=arrive_il_y_a)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'ancre elle-meme
# ═══════════════════════════════════════════════════════════════════════════════

def test_l_ancre_se_pose_toute_seule_et_rend_zero(socle):
    """Un serveur deja bloque doit se debloquer SANS que le proprietaire ait a
    eteindre puis rallumer : l'ecriture est paresseuse."""
    assert socle.config["activite_observe_depuis"] == ""
    assert _run(activite.observation_jours(1)) == 0
    assert socle.config["activite_observe_depuis"] == cal.jour()
    assert ("activite_observe_depuis", cal.jour()) in socle.ecrits


def test_l_ancre_n_est_jamais_reecrite(socle):
    """Sinon un OFF/ON deviendrait un moyen de repousser l'escalade a l'infini."""
    socle.config["activite_observe_depuis"] = _il_y_a(30)
    socle.ecrits.clear()
    assert _run(activite.observation_jours(1)) == 30
    assert socle.ecrits == [], "aucune ecriture ne doit avoir lieu"


def test_le_silence_est_plafonne_par_l_observation(socle):
    """LE CAS DE PRODUCTION. Membre inscrit il y a 400 jours, jamais vu,
    systeme allume aujourd'hui → silence 0, pas 400."""
    socle.config["activite_observe_depuis"] = cal.jour()
    m = _Membre(10, arrive_il_y_a=400)
    mes = _run(activite.presence(1, m, socle.config))
    assert mes["silence"] == 0
    assert mes["silence_brut"] == 400, "la valeur reelle reste lisible par le staff"


def test_l_arrivee_reste_opposable_quand_elle_est_posterieure(socle):
    """Le plafond ne doit pas rendre les vrais nouveaux invisibles : un membre
    arrive il y a 5 jours sur un systeme observant depuis 30 vaut bien 5."""
    socle.config["activite_observe_depuis"] = _il_y_a(30)
    socle.journal[99] = {_il_y_a(20)}          # pour que le journal ne soit pas vide
    m = _Membre(10, arrive_il_y_a=5)
    mes = _run(activite.presence(1, m, socle.config))
    assert mes["silence"] == 5


def test_journal_vide_ne_juge_personne(socle):
    """FAIL-OPEN CORRIGE : `anciennete_du_suivi` a None voulait dire « journal
    vide », pas « borne inconnue, passe ». L'ignorer faisait juger tout le
    monde sur des journees dont on n'a aucune trace."""
    socle.config["activite_observe_depuis"] = _il_y_a(60)
    m = _Membre(10, arrive_il_y_a=400)
    mes = _run(activite.presence(1, m, socle.config))
    assert mes["observables"] == 0
    assert mes["jugeable"] is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Le cas de production, en entier
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rationnement — rationner, ne plus avorter
# ═══════════════════════════════════════════════════════════════════════════════


