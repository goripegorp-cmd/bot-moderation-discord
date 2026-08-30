"""Tests de l'ANCRE D'OBSERVATION et du rationnement.

Ce fichier verrouille un incident de production reel (12/08/2026) : allumer le
systeme sur un serveur existant de 941 membres jamais observes les classait TOUS
en expulsion le premier soir, le garde-fou bloquait tout, et il ne pouvait plus
jamais retomber — les anciennetes ne decroissent pas. Interblocage definitif,
repete toutes les 6 heures.

La regle qui le referme : **on ne reproche jamais une journee anterieure a
l'allumage**. Chaque test ci-dessous est une facette de cette phrase.
"""
import asyncio
import datetime as dt

import pytest

import activite
import activite_calendrier as cal
import activite_escalade as esc
import activite_passage as passage


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
        self.config = dict(activite.CLES_DEFAUT)
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

    async def _pas_immunise(m):
        return False

    monkeypatch.setattr(activite, "_cfg", s.cfg)
    monkeypatch.setattr(activite, "_db_set", s.db_set)
    monkeypatch.setattr(activite, "_get_db", s.get_db)
    monkeypatch.setattr(activite, "_est_immunise", _pas_immunise)
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


class _Guild:
    id = 1
    owner_id = 999

    def __init__(self, membres):
        self.members = membres
        self.channels = []
        #  `membre_concerne` lit `member.guild.owner_id` : sans ce rattachement
        #  il echoue, et il est FAIL-CLOSED — il rendrait False pour tout le
        #  monde et le test passerait pour de mauvaises raisons.
        for m in membres:
            m.guild = self

    def get_role(self, rid):
        return None

    def get_channel(self, cid):
        """⚠️ Indispensable, et l'absence etait une bombe a retardement.

        Le rappel hebdomadaire n'appelle `get_channel` que le JOUR choisi. Les
        tests passaient donc les six autres jours de la semaine et tombaient le
        septieme — une CI rouge sans qu'une seule ligne de production ait bouge.
        Un faux objet doit porter TOUT ce que le vrai porte, meme ce qu'on ne
        croit pas atteindre.
        """
        return None


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


def test_impossible_d_expulser_avant_d_avoir_observe(socle):
    """Propriete structurelle : silence <= observation. Le seuil d'expulsion
    (21 j par defaut) est donc INATTEIGNABLE avant 21 jours d'observation."""
    conf = activite.config_du_role(socle.config, activite.ROLE_TOUS)
    for jours_observes in range(0, conf["expulsion"]):
        socle.config["activite_observe_depuis"] = _il_y_a(jours_observes)
        m = _Membre(10, arrive_il_y_a=900)
        mes = _run(activite.presence(1, m, socle.config))
        assert activite.verdict(mes, conf) != "expulsion", (
            f"expulsion possible apres seulement {jours_observes} j d'observation")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le cas de production, en entier
# ═══════════════════════════════════════════════════════════════════════════════

def test_941_fantomes_ne_declenchent_rien_le_premier_soir(socle):
    """L'incident exact : 941 membres inscrits depuis des mois, jamais vus,
    systeme allume a l'instant. Avant correctif : 941 actions demandees."""
    socle.config["activite_enabled"] = True
    socle.config["activite_observe_depuis"] = cal.jour()
    g = _Guild([_Membre(i, arrive_il_y_a=300 + i) for i in range(941)])

    cl = _run(esc.classer(g))
    assert cl["suivis"] == 941
    assert cl["rappel"] == [] and cl["retrait"] == [] and cl["expulsion"] == []
    assert cl["doux"] == [], "personne n'est jugeable le premier jour"
    assert cl["actifs"] == 941


def test_a_j21_l_escalade_reprend_vraiment(socle):
    """Le plafonnement retarde, il n'annule pas. Sinon le systeme ne servirait
    a rien sur un serveur reellement endormi."""
    socle.config["activite_enabled"] = True
    #  ⚠️ ON LIT LA CONSTANTE, ON NE CODE PLUS 21 EN DUR. Les seuils par
    #  defaut ont ete decales d une semaine le 30/08 (7/14/21 → 14/21/28)
    #  sur description du proprietaire : le role AFK, qui MASQUE tout le
    #  serveur, ne doit arriver qu a la DEUXIEME semaine de silence. Un
    #  test qui fige la valeur casse a chaque reglage et n eprouve rien
    #  de plus — ce qui compte est la PROPRIETE, pas le chiffre.
    _EXP = activite.SEUIL_EXPULSION_DEFAUT
    socle.config["activite_observe_depuis"] = _il_y_a(_EXP)
    socle.journal[5000] = {_il_y_a(1)}          # un membre actif : journal non vide
    g = _Guild([_Membre(i, arrive_il_y_a=300) for i in range(30)])

    cl = _run(esc.classer(g))
    assert len(cl["expulsion"]) == 30
    assert all(f["jours"] == _EXP for f in cl["expulsion"])
    assert all(f["jours_reels"] == 300 for f in cl["expulsion"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rationnement — rationner, ne plus avorter
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_quota_rationne_au_lieu_de_tout_bloquer(socle, monkeypatch):
    """Avant : `return` anticipe, donc retours / masquage / rappel sautes, et
    plus rien ne se debloquait jamais. Apres : 25 par passage, le reste suit."""
    socle.config["activite_enabled"] = True
    socle.config["activite_observe_depuis"] = _il_y_a(
        activite.SEUIL_EXPULSION_DEFAUT)
    socle.journal[5000] = {_il_y_a(1)}
    g = _Guild([_Membre(i, arrive_il_y_a=300) for i in range(100)])

    appels = {"masquage": 0}

    async def _faux_masquage(guild, cfg_act, dry_run=False):
        appels["masquage"] += 1
        return {"modifies": 0, "deja_bons": 0, "echecs": 0, "ignores": 0,
                "roles": 0, "raison": ""}

    import activite_niveaux as niv
    monkeypatch.setattr(niv, "appliquer_masquage", _faux_masquage)

    rap = _run(passage.passage(g, dry_run=True))
    assert rap["actif"] is True
    assert rap["suivi_muet"] is False
    #  100 membres au seuil d expulsion → tous en expulsion, qui n'est PAS soumise au quota :
    #  c'est une proposition, elle n'applique rien.
    assert rap["actions"]["a_expulser"] == 100
    assert rap["quota_atteint"] is False
    assert appels["masquage"] == 1, "le masquage ne doit plus etre saute"


def test_le_quota_sert_les_plus_anciens_d_abord(socle):
    """Laisser quelqu'un stagner a 30 jours pendant qu'on etiquette des absents
    de 7 jours n'aurait aucun sens."""
    socle.config["activite_enabled"] = True
    socle.config["activite_observe_depuis"] = _il_y_a(200)
    socle.journal[5000] = {_il_y_a(1)}
    #  ⚠️ LES JOURS VIENNENT DES CONSTANTES, PAS DE CHIFFRES EN DUR. Les
    #  seuils ont ete decales d une semaine le 30/08 (7/14/21 → 14/21/28) : un
    #  test qui ecrit « 14 a 20 j » eprouve le chiffre d hier, pas la propriete
    #  « le quota sert les plus anciens d abord ».
    _RET = activite.SEUIL_RETRAIT_DEFAUT
    _EXP = activite.SEUIL_EXPULSION_DEFAUT
    _LARGEUR = max(1, _EXP - _RET)
    #  60 membres au palier « retrait », silences distincts dans sa plage.
    membres = []
    for i in range(60):
        m = _Membre(i, arrive_il_y_a=300)
        socle.journal[i] = {_il_y_a(_RET + (i % _LARGEUR))}
        membres.append(m)
    g = _Guild(membres)

    rap = _run(passage.passage(g, dry_run=True))
    cl = rap["fiches"]
    assert rap["quota_atteint"] is True
    assert len(cl["retrait"]) == activite.PLAFOND_ACTIONS_PAR_PASSAGE
    assert rap["reporte"]["retrait"] == 60 - activite.PLAFOND_ACTIONS_PAR_PASSAGE
    #  Les plus anciens d'abord : le silence minimal des retenus est >= le
    #  silence maximal de ceux qu'on reporte.
    retenus = [f["jours"] for f in cl["retrait"]]
    assert min(retenus) >= _RET


def test_un_membre_reporte_n_est_jamais_annonce_publiquement(socle):
    """Le rappel hebdomadaire se construit sur `cl["groupes"]`, pas sur les
    listes globales. Sans filtrage apres troncature, un membre REPORTE serait
    annonce comme ayant perdu ses roles alors qu'on n'y a pas touche."""
    socle.config["activite_enabled"] = True
    socle.config["activite_observe_depuis"] = _il_y_a(200)
    socle.journal[5000] = {_il_y_a(1)}
    #  ⚠️ SILENCE DERIVE DU SEUIL, pas ecrit en dur : le palier « retrait »
    #  est passe de 14 a 21 jours le 30/08, et « 15 » ne le visait plus.
    membres = []
    for i in range(60):
        m = _Membre(i, arrive_il_y_a=300)
        socle.journal[i] = {_il_y_a(activite.SEUIL_RETRAIT_DEFAUT + 1)}
        membres.append(m)
    g = _Guild(membres)

    rap = _run(passage.passage(g, dry_run=True))
    cl = rap["fiches"]
    assert cl["retrait"], "le banc ne construit plus de palier « retrait »"
    retenus = {f["member"].id for f in cl["retrait"]}
    dans_les_groupes = set()
    for gr in cl["groupes"].values():
        for k in ("rappel", "retrait"):
            dans_les_groupes |= {f["member"].id for f in gr[k]}
    assert dans_les_groupes == retenus


def test_suivi_muet_bloque_encore_tout(socle):
    """Le seul cas ou l'on refuse encore d'agir en bloc : le journal est
    totalement vide alors qu'on observe depuis des jours. Sur un serveur
    vivant c'est impossible — les sondes sont cassees."""
    socle.config["activite_enabled"] = True
    socle.config["activite_observe_depuis"] = _il_y_a(40)
    g = _Guild([_Membre(i, arrive_il_y_a=300) for i in range(50)])

    rap = _run(passage.passage(g, dry_run=True))
    assert rap["suivi_muet"] is True
    assert rap["actions"]["a_expulser"] == 0
    assert "RIEN n'a été appliqué" in rap["raison"]
    assert "Suivi muet" in passage.resume_texte(rap)


def test_l_expulsion_ne_compte_pas_dans_le_quota(socle):
    """Elle n'APPLIQUE rien — le bot ne l'execute jamais seul. La compter
    gonflait le total avec des non-actions, et c'est ce qui a produit
    « 941 actions demandees »."""
    socle.config["activite_enabled"] = True
    socle.config["activite_observe_depuis"] = _il_y_a(200)
    socle.journal[5000] = {_il_y_a(1)}
    membres = []
    for i in range(200):
        m = _Membre(i, arrive_il_y_a=300)
        socle.journal[i] = {_il_y_a(60)}          # tres au-dela du seuil
        membres.append(m)
    g = _Guild(membres)

    rap = _run(passage.passage(g, dry_run=True))
    assert rap["actions"]["a_expulser"] == 200
    assert rap["quota_atteint"] is False, "aucun rationnement sur des propositions"
