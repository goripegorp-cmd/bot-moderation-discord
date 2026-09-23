"""« Deux semaines, trois semaines » — et « il ne voit plus le serveur ».

═══════════════════════════════════════════════════════════════════════════════
LE SIGNALEMENT (22/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « Je veux m'assurer que les rôles qui sont vraiment inactifs au bout de
      deux semaines, trois semaines, et après les rôles qui leur seront donnés
      en plus — je veux que la personne ne puisse plus voir le serveur sauf
      les salons qui lui sont proposés, comme le salon où il doit écrire
      dedans pour être actif. »

Deux choses à prouver, et elles ne se recouvrent pas :

  A. L'ÉCHELLE. Les valeurs par défaut étaient déjà passées à 14/21/28 le
     30/08 — sans aucun effet, parce que le serveur garde SES seuils, écrits
     dans le panneau. L'arithmétique du 31/08 l'a démontré : 928 membres au
     palier AFK alors que l'observation ne dépassait pas 9 jours, impossible
     avec un seuil à 14. Les absents étaient donc étiquetés au bout d'UNE
     semaine. Le plancher remonte ces seuils UNE fois, sans jamais rabaisser
     une valeur choisie plus haut.

  B. LE MASQUAGE. Il est posé sur tous les salons sauf les deux salons
     d'activité — mais ⚠️ DISCORD FAIT PRIMER L'AUTORISATION EXPLICITE D'UN
     AUTRE RÔLE SUR NOTRE REFUS : @everyone d'abord, puis les rôles du membre
     (refus, PUIS autorisations), puis la surcharge nominative. Un salon
     réservé au rôle « Membre » reste donc visible à un absent du palier 1,
     qui garde ses rôles. Le bot ne peut pas l'empêcher sans une surcharge
     nominative par membre et par salon ; il le MESURE et il le DIT.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

import aiosqlite
import pytest

import activite
import activite_niveaux as niv

RACINE = Path(__file__).resolve().parent.parent
SRC_PASSAGE = (RACINE / "activite_passage.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux fidèles
# ═══════════════════════════════════════════════════════════════════════════════

class R:
    def __init__(self, rid, nom):
        self.id, self.name = rid, nom


class Ow:
    """Une surcharge de salon : on ne lit que `view_channel`, comme le code."""

    def __init__(self, view_channel=None):
        self.view_channel = view_channel


class Salon:
    def __init__(self, cid, overwrites=None):
        self.id, self.overwrites = cid, dict(overwrites or {})


class G:
    def __init__(self, salons):
        self.id = 777
        self.channels = list(salons)


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "seuils.db"
    cfg = {}

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return cfg

    async def _db_set(_g, k, v):
        cfg[k] = v

    async def _imm(_m):
        return False

    activite.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set, est_immunise=_imm,
                   log=lambda *a, **k: None)
    niv.setup(log=lambda *a, **k: None)
    return cfg


# ═══════════════════════════════════════════════════════════════════════════════
#  A. L'échelle — deux semaines, trois semaines
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_S1_les_seuils_d_une_semaine_sont_remontes(base):
    """Le cas du serveur : 7/14/21 écrits dans le panneau, donc rôle AFK au
    bout d'une semaine alors que la consigne dit deux."""
    base.update({"activite_roles": {"50": {"rappel": 7, "retrait": 14,
                                           "expulsion": 21}}})
    res = await activite.appliquer_plancher_seuils(777)
    assert res["fait"] is True
    conf = activite.config_du_role(await activite.config(777), "50")
    assert (conf["rappel"], conf["retrait"], conf["expulsion"]) == (14, 21, 28)


@pytest.mark.asyncio
async def test_S2_un_seuil_choisi_PLUS_HAUT_n_est_jamais_rabaisse(base):
    """⚠️ LE PLANCHER N'EST PAS UN RÉGLAGE. Rabaisser 60 jours à 28 masquerait
    le serveur à des gens que le propriétaire avait décidé de laisser tranquilles."""
    base.update({"activite_roles": {"50": {"rappel": 30, "retrait": 45,
                                           "expulsion": 60}}})
    res = await activite.appliquer_plancher_seuils(777)
    conf = activite.config_du_role(await activite.config(777), "50")
    assert (conf["rappel"], conf["retrait"], conf["expulsion"]) == (30, 45, 60)
    assert res["fait"] is False


@pytest.mark.asyncio
async def test_S3_les_trois_seuils_restent_dans_l_ORDRE(base):
    """Deux seuils qui se croisent rendent un palier inatteignable : le membre
    saute l'étiquette et se retrouve dépouillé sans avoir été prévenu."""
    base.update({"activite_roles": {"50": {"rappel": 30, "retrait": 14,
                                           "expulsion": 21}}})
    await activite.appliquer_plancher_seuils(777)
    conf = activite.config_du_role(await activite.config(777), "50")
    assert conf["rappel"] < conf["retrait"] < conf["expulsion"], conf


@pytest.mark.asyncio
async def test_S4_le_plancher_ne_s_applique_QU_UNE_FOIS(base):
    """Sinon un propriétaire qui redescend volontairement à 7 jours verrait sa
    valeur réécrite à chaque passage, sans comprendre pourquoi."""
    base.update({"activite_roles": {"50": {"rappel": 7, "retrait": 14,
                                           "expulsion": 21}}})
    await activite.appliquer_plancher_seuils(777)
    assert base.get("activite_seuils_migres"), "la date n'a pas été écrite"
    base["activite_roles"] = {"50": {"rappel": 7, "retrait": 14, "expulsion": 21}}
    res = await activite.appliquer_plancher_seuils(777)
    assert res["fait"] is False
    conf = activite.config_du_role(await activite.config(777), "50")
    assert conf["rappel"] == 7, "le choix du propriétaire a été écrasé"


def test_S5_la_cle_du_plancher_est_DECLAREE():
    """Même piège que le registre : `config()` ne rend que les clés de
    `CLES_DEFAUT`. Non déclarée, la date serait perdue et le plancher
    s'appliquerait à CHAQUE passage — ce que S4 interdit."""
    assert "activite_seuils_migres" in activite.CLES_DEFAUT


def test_S6_le_plancher_est_APPELE_avant_le_classement_et_jamais_en_simulation():
    """Une fonction non appelée n'est pas opérationnelle. Et une simulation ne
    doit rien écrire de durable."""
    assert "appliquer_plancher_seuils(guild.id)" in SRC_PASSAGE
    i_pl = SRC_PASSAGE.index("appliquer_plancher_seuils(guild.id)")
    i_cl = SRC_PASSAGE.index("esc.classer(guild")
    assert i_pl < i_cl, "le plancher s'applique APRÈS le classement : six heures perdues"
    assert ("if not dry_run:\n        try:\n"
            "            _pl = await activite.appliquer_plancher_seuils"
            in SRC_PASSAGE), "le plancher tourne aussi en simulation"


# ═══════════════════════════════════════════════════════════════════════════════
#  B. Le masquage — et ce qui le contredit
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_M1_un_salon_rouvert_par_un_AUTRE_role_est_compte(base):
    """Le cas réel : un salon réservé au rôle « Membre » par une autorisation
    explicite. Notre refus perd, et rien ne le disait."""
    membre = R(50, "Membre")
    g = G([Salon(1, {membre: Ow(view_channel=True)})])
    base.update({"activite_role_niveau1": 11, "activite_salon_retour": 99})
    fuites = niv._fuites_du_salon(g, g.channels[0], {11})
    assert fuites == ["Membre"]


@pytest.mark.asyncio
async def test_M2_une_autorisation_d_EVERYONE_ne_compte_PAS(base):
    """Elle est appliquée AVANT les rôles : notre refus la bat. La compter
    ferait croire à une fuite sur tous les salons publics du serveur."""
    every = R(777, "@everyone")           # même id que la guilde
    g = G([Salon(1, {every: Ow(view_channel=True)})])
    assert niv._fuites_du_salon(g, g.channels[0], {11}) == []


@pytest.mark.asyncio
async def test_M3_nos_propres_etiquettes_ne_comptent_pas(base):
    """Le rôle AFK porte justement le refus : le compter serait absurde."""
    afk = R(11, "💤 AFK")
    g = G([Salon(1, {afk: Ow(view_channel=True)})])
    assert niv._fuites_du_salon(g, g.channels[0], {11}) == []


@pytest.mark.asyncio
async def test_M4_une_surcharge_NOMINATIVE_compte_aussi(base):
    """Elle est appliquée en dernier et l'emporte sur tout, y compris sur nous."""
    class Membre:
        id, display_name = 4242, "Bob"
    g = G([Salon(1, {Membre(): Ow(view_channel=True)})])
    assert niv._fuites_du_salon(g, g.channels[0], {11}) == ["Bob"]


@pytest.mark.asyncio
async def test_M5_un_refus_explicite_n_est_pas_une_fuite(base):
    """`view_channel=False` va dans notre sens ; `None` ne dit rien."""
    r1, r2 = R(50, "Membre"), R(51, "Invité")
    g = G([Salon(1, {r1: Ow(view_channel=False), r2: Ow(view_channel=None)})])
    assert niv._fuites_du_salon(g, g.channels[0], {11}) == []


def test_M6_la_carte_DIT_le_masquage_refuse_et_les_fuites():
    """⚠️ LE MASQUAGE POUVAIT ÊTRE REFUSÉ EN SILENCE. Pas de salon de retour,
    trop de salons, interrupteur éteint : la carte n'en disait pas un mot et on
    croyait le serveur masqué."""
    assert "Le masquage n'a PAS eu lieu" in SRC_PASSAGE
    assert "resteront visibles" in SRC_PASSAGE
    assert "hors de ma portée" in SRC_PASSAGE


def test_M7_le_masquage_REFUSE_de_tourner_sans_salon_de_retour():
    """La porte de sortie n'est pas une option du masquage : elle en est la
    condition. Sans elle, l'absent ne pourrait plus jamais revenir.

    ⚠️ ÉLARGI LE 23/09 : c'est la PORTE qui est exigée, plus « un salon
    ouvert » — un salon qu'on lit n'est pas une sortie. Le comportement réel
    est éprouvé dans `test_absents_porte_de_retour.py` (A5) ; ici, le corps
    entier de la fonction, lu par l'AST — jamais une tranche de texte."""
    import ast
    src = (RACINE / "activite_niveaux.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "appliquer_masquage":
            corps = ast.unparse(n)
            break
    else:
        raise AssertionError("appliquer_masquage introuvable")
    assert "if not salons_de_retour(cfg_act):" in corps
    assert "masquage REFUSÉ" in corps
