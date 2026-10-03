"""Le démontage du système d'activité (03/10/2026).

« Enlève-moi complètement ce système et ce calcul inutile […] tu t'assures juste
que tout le monde voit bien tous les salons. Toutes les catégories aussi. »
Ce que le système avait posé sur Discord — rôles retirés, étiquettes AFK et leur
masquage sur chaque salon, salons de retour — est défait au démarrage. Ces tests
n'appellent jamais Discord : faux serveur, vraie base SQLite.
"""
from __future__ import annotations

import asyncio
import contextlib
import json

import aiosqlite
import discord
import pytest

import activite_demontage as dem

#  ─── Faux Discord : il porte tout ce que le vrai porte et qu'on lit ─────────


class _Perms:
    def __init__(self, value=0):
        self.value = value


class _Role:
    def __init__(self, rid, nom, rang, perms=0, managed=False):
        self.id, self.name, self.rang, self.managed = rid, nom, rang, managed
        self.permissions = _Perms(perms)
        self.members = []
        self.supprime = False
        self.guild = None

    def is_default(self):
        return self.rang == 0

    def __lt__(self, autre):
        return self.rang < autre.rang

    async def delete(self, reason=None):
        self.supprime = True
        self.guild.journal.append(("delete_role", self.id))
        self.guild.roles.remove(self)
        for m in self.members:
            m.roles.remove(self)
        for s in self.guild.channels:
            s.surcharges.pop(self.id, None)


class _Surcharge:
    def __init__(self, vide=False):
        self._vide = vide

    def is_empty(self):
        return self._vide


class _Salon:
    def __init__(self, sid, nom, type_=discord.ChannelType.text):
        self.id, self.name, self.type = sid, nom, type_
        self.surcharges = {}
        self.guild = None

    def overwrites_for(self, role):
        return _Surcharge(vide=role.id not in self.surcharges)

    async def set_permissions(self, role, overwrite=None, reason=None):
        self.guild.journal.append(("set_permissions", self.id, role.id))
        if overwrite is None:
            self.surcharges.pop(role.id, None)

    async def delete(self, reason=None):
        self.guild.journal.append(("delete_channel", self.id))
        self.guild.channels.remove(self)


class _Membre:
    def __init__(self, uid, roles=()):
        self.id = uid
        self.roles = list(roles)
        self.guild = None

    async def add_roles(self, *roles, atomic=True, reason=None):
        self.guild.journal.append(("add_roles", self.id, tuple(r.id for r in roles), atomic))
        for r in roles:
            if r not in self.roles:
                self.roles.append(r)
                r.members.append(self)

    async def remove_roles(self, *roles, reason=None):
        self.guild.journal.append(("remove_roles", self.id, tuple(r.id for r in roles)))
        for r in roles:
            if r in self.roles:
                self.roles.remove(r)
                r.members.remove(self)


class _Guild:
    def __init__(self, roles, salons, membres, bot_rang=50, manage_roles=True):
        self.id, self.name, self.chunked = 1, "GoRP SEA", True
        self.journal = []
        self.everyone = _Role(1, "@everyone", 0)
        self.roles = [self.everyone] + list(roles)
        self.channels = list(salons)
        self.membres = {m.id: m for m in membres}
        top = _Role(999, "bot", bot_rang)
        self.me = type("Me", (), {
            "top_role": top,
            "guild_permissions": type("P", (), {"manage_roles": manage_roles})()})()
        for x in self.roles + self.channels + membres:
            x.guild = self
        for m in membres:
            for r in m.roles:
                r.members.append(m)

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_member(self, uid):
        return self.membres.get(uid)

    def get_channel(self, cid):
        return next((s for s in self.channels if s.id == cid), None)

    def ecritures(self, quoi):
        return [j for j in self.journal if j[0] == quoi]


@pytest.fixture
def base(tmp_path, monkeypatch):
    chemin = tmp_path / "act.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def creer():
        async with get_db() as db:
            await db.execute(
                "CREATE TABLE activite_etat(guild_id INTEGER NOT NULL, user_id INTEGER"
                " NOT NULL, dernier_actif TEXT, palier INTEGER NOT NULL DEFAULT 0,"
                " roles_retires TEXT NOT NULL DEFAULT '[]', derniere_alerte TEXT,"
                " PRIMARY KEY(guild_id, user_id))")
            await db.commit()

    asyncio.run(creer())

    async def depouiller(uid, ids, palier=2):
        async with get_db() as db:
            await db.execute(
                "INSERT INTO activite_etat(guild_id, user_id, palier, roles_retires)"
                " VALUES(1,?,?,?)", (uid, palier, json.dumps(ids)))
            await db.commit()

    async def restants(uid):
        async with get_db() as db:
            async with db.execute("SELECT roles_retires, palier FROM activite_etat"
                                  " WHERE guild_id=1 AND user_id=?", (uid,)) as cur:
                return await cur.fetchone()

    async def _dodo(_s):
        return None

    monkeypatch.setattr(dem.asyncio, "sleep", _dodo)
    ecrit = {}

    async def db_set(_gid, k, v):
        ecrit[k] = v
        return True

    return {"get_db": get_db, "depouiller": depouiller, "restants": restants,
            "db_set": db_set, "ecrit": ecrit}


def _demonter(guild, cfg, base):
    return asyncio.run(dem.demonter(guild, cfg=cfg, get_db=base["get_db"],
                                    db_set=base["db_set"]))


#  Le serveur type : un membre dépouillé, les étiquettes du bot, leurs salons.
def _serveur(**kw):
    membre_r = _Role(10, "Membre", 5, perms=104324673)
    vip = _Role(11, "VIP", 6, perms=0x400)
    haut = _Role(12, "Fondateur", 90, perms=8)
    afk1 = _Role(21, "💤 AFK", 4)
    afk2 = _Role(22, "💤 AFK · rôles retirés", 4)
    doux = _Role(23, "👀 Peu actif", 3)
    porte = _Salon(31, "🔙・retour")
    afk_salon = _Salon(32, "💤-afk")
    general = _Salon(33, "💬・général")
    cat = _Salon(34, "📁 COMMUNAUTÉ", discord.ChannelType.category)
    for s in (porte, afk_salon, general, cat):
        s.surcharges.update({21: True, 22: True})
    depouille = _Membre(100, roles=[afk2])
    afk = _Membre(101, roles=[membre_r, afk1])
    actif = _Membre(102, roles=[membre_r, doux])
    g = _Guild([membre_r, vip, haut, afk1, afk2, doux],
               [porte, afk_salon, general, cat], [depouille, afk, actif], **kw)
    cfg = {"activite_enabled": True, "activite_role_niveau1": 21,
           "activite_role_niveau2": 22, "activite_role_doux": 23,
           "activite_salon_retour": 31, "activite_salon_afk": 32,
           "activite_salon_annonce": 33, "welcome_autorole": 10}
    return g, cfg


def test_T1_les_roles_pris_au_palier_2_sont_rendus_en_un_appel(base):
    g, cfg = _serveur()
    asyncio.run(base["depouiller"](100, [10, 11, 77]))     # 77 : supprimé depuis
    res = _demonter(g, cfg, base)
    (appel,) = [j for j in g.ecritures("add_roles") if j[1] == 100]
    assert set(appel[2]) == {10, 11} and appel[3] is False, "UN appel, non atomique"
    assert res["membres"] == 1 and res["rendus"] == 2
    assert asyncio.run(base["restants"](100)) == ("[]", 0)


def test_T1bis_un_role_au_dessus_du_bot_reste_note_et_rien_n_est_marque(base):
    g, cfg = _serveur()
    asyncio.run(base["depouiller"](100, [10, 12]))         # 12 : au-dessus du bot
    res = _demonter(g, cfg, base)
    assert json.loads(asyncio.run(base["restants"](100))[0]) == [12]
    assert res["impossibles"] == ["Fondateur"] and res["fait"] is False
    assert dem.MARQUE not in base["ecrit"], "le démontage doit reprendre au démarrage suivant"


def test_T2_les_etiquettes_du_bot_sont_supprimees_et_le_masquage_part_avec(base):
    g, cfg = _serveur()
    res = _demonter(g, cfg, base)
    assert sorted(j[1] for j in g.ecritures("delete_role")) == [21, 22, 23]
    assert all(not s.surcharges for s in g.channels), "plus un seul refus « voir le salon »"
    assert [r.name for r in g.roles] == ["@everyone", "Membre", "VIP", "Fondateur"]
    assert g.ecritures("set_permissions") == [], \
        "supprimer le rôle suffit : pas d'écriture salon par salon"
    assert sorted(res["etiquettes"]["supprimes"]) == sorted(
        ["💤 AFK", "💤 AFK · rôles retirés", "👀 Peu actif"])


def test_T2bis_un_role_du_serveur_seulement_DESIGNE_n_est_pas_supprime(base):
    """Le propriétaire avait désigné SON rôle « Absent » comme étiquette : il
    reste, sans les refus que le système y avait posés, et sans porteurs."""
    absent = _Role(40, "Absent", 4, perms=0x400)
    homonyme = _Role(41, "💤 AFK", 4, perms=0x400)           # pas à nous : il a des droits
    s1, s2 = _Salon(50, "règles"), _Salon(51, "chat")
    s1.surcharges[40] = True
    m = _Membre(200, roles=[absent])
    g = _Guild([absent, homonyme], [s1, s2], [m])
    res = _demonter(g, {"activite_role_niveau1": 40}, base)
    assert g.ecritures("delete_role") == []
    assert g.ecritures("set_permissions") == [("set_permissions", 50, 40)]
    assert g.ecritures("remove_roles") == [("remove_roles", 200, (40,))]
    assert res["etiquettes"]["nettoyes"] == ["Absent"]
    assert homonyme in g.roles, "un rôle à notre nom MAIS avec des droits n'est pas le nôtre"


def test_T2quater_une_ancienne_etiquette_designee_est_retrouvee_par_l_historique(base):
    """Le propriétaire avait d'abord désigné SON rôle « Ancien absent », puis un
    autre : seul le registre `activite_etiquettes_historique` s'en souvient.
    Sans lui, ses refus resteraient posés sur les salons, pour toujours."""
    ancien = _Role(45, "Ancien absent", 4, perms=0x400)
    s1 = _Salon(50, "règles")
    s1.surcharges[45] = True
    m = _Membre(201, roles=[ancien])
    g = _Guild([ancien], [s1], [m])
    cfg = {"activite_role_niveau1": 21,
           "activite_etiquettes_historique": json.dumps(
               {"activite_role_niveau1": [45, 21]})}
    res = _demonter(g, cfg, base)
    assert res["etiquettes"]["nettoyes"] == ["Ancien absent"]
    assert not s1.surcharges and ancien not in m.roles


def test_T2ter_une_etiquette_au_dessus_du_bot_est_signalee_pas_forcee(base):
    g, cfg = _serveur(bot_rang=4)            # les étiquettes (rang 4) ne sont plus sous le bot
    res = _demonter(g, cfg, base)
    assert "💤 AFK" in res["etiquettes"]["bloques"]
    assert not any(j[1] in (21, 22) for j in g.ecritures("delete_role"))
    assert res["fait"] is False


def test_T3_seuls_les_salons_du_systeme_partent_jamais_un_salon_general(base):
    g, cfg = _serveur()
    cfg["activite_salon_retour"] = 33        # #général choisi comme porte
    res = _demonter(g, cfg, base)
    assert g.ecritures("delete_channel") == [("delete_channel", 32)]
    assert g.get_channel(33) is not None, "un salon général ne se supprime JAMAIS"
    assert ("💬・général", "nom général — à supprimer à la main si c'était bien "
                         "le sien") in res["salons"]["gardes"]
    assert g.get_channel(31) is not None, "la porte n'est plus configurée : intouchée"


def test_T3bis_un_salon_qui_sert_ailleurs_reste(base):
    g, cfg = _serveur()
    cfg["welcome_channel"] = "31"
    cfg["auto_help_channels"] = json.dumps({"32": {"texte": "aide"}})
    res = _demonter(g, cfg, base)
    assert g.ecritures("delete_channel") == []
    gardes = dict(res["salons"]["gardes"])
    assert "welcome_channel" in gardes["🔙・retour"]
    assert "auto_help_channels" in gardes["💤-afk"]


def test_T3ter_la_porte_propre_a_un_role_part_aussi(base):
    g, cfg = _serveur()
    g.channels.append(_Salon(35, "🚪-revenir"))
    g.channels[-1].guild = g
    cfg["activite_roles"] = json.dumps({"10": {"salon_retour": 35}})
    _demonter(g, cfg, base)
    assert ("delete_channel", 35) in g.journal


def test_T4_une_fois_fait_plus_rien_ne_bouge(base):
    g, cfg = _serveur()
    res = _demonter(g, cfg, base)
    assert res["fait"] is True and dem.MARQUE in base["ecrit"]
    assert base["ecrit"]["activite_enabled"] is False
    cfg[dem.MARQUE] = base["ecrit"][dem.MARQUE]
    #  Après coup, quelqu'un crée À LA MAIN un rôle « 💤 AFK » sans droits, et
    #  une vieille ligne traîne en base : ce n'est plus l'affaire du démontage.
    recree = _Role(60, "💤 AFK", 2)
    recree.guild = g
    g.roles.append(recree)
    asyncio.run(base["depouiller"](102, [11]))
    avant = list(g.journal)
    res = _demonter(g, cfg, base)
    assert res["deja"] is True and g.journal == avant
    assert recree in g.roles


def test_T5_un_membre_parti_recupere_ses_roles_a_son_retour(base):
    g, cfg = _serveur()
    asyncio.run(base["depouiller"](300, [10, 11]))      # parti du serveur
    res = _demonter(g, cfg, base)
    assert res["absents"] == 1 and res["fait"] is True
    revenant = _Membre(300)
    revenant.guild = g
    g.membres[300] = revenant
    r = asyncio.run(dem.rendre_au_retour(g, revenant, get_db=base["get_db"]))
    assert sorted(r["rendus"]) == ["Membre", "VIP"]
    assert asyncio.run(base["restants"](300)) == ("[]", 0)
    assert asyncio.run(dem.rendre_au_retour(g, revenant, get_db=base["get_db"])) is None


def test_T6_un_serveur_sans_table_ni_reglage_ne_casse_rien(tmp_path, monkeypatch):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(tmp_path / "vide.db")
        try:
            yield db
        finally:
            await db.close()

    async def db_set(*_a):
        return True

    monkeypatch.setattr(dem.asyncio, "sleep", lambda _s: asyncio.sleep(0))
    g = _Guild([], [_Salon(1, "chat")], [])
    res = asyncio.run(dem.demonter(g, cfg={}, get_db=get_db, db_set=db_set))
    assert res["fait"] is True and not dem.a_agi(res) and g.journal == []


@pytest.mark.parametrize("nom,systeme", [
    ("🔙・retour", True), ("💤-afk", True), ("📥 Absents", True),
    ("inactivité", True), ("🚪-porte", True), ("💬・général", False),
    ("chat", False), ("annonces", False),
])
def test_T7_le_nom_dit_si_c_est_un_salon_du_systeme(nom, systeme):
    assert dem.nom_de_salon_systeme(nom) is systeme


def test_T8_le_bilan_dit_ce_qui_a_ete_fait(base):
    g, cfg = _serveur()
    asyncio.run(base["depouiller"](100, [10]))
    cfg["activite_salon_retour"] = 33
    res = _demonter(g, cfg, base)
    t = dem.bilan_texte(res)
    assert "1 membre(s) ont récupéré 1 rôle(s)" in t
    assert "masquage levé sur tous les salons et catégories" in t
    assert "#💤-afk" in t and "#💬・général gardé" in t
    assert dem.a_agi(res)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le branchement dans bot.py
# ═══════════════════════════════════════════════════════════════════════════════

import ast as _ast
from pathlib import Path as _Path

_SRC_BOT = (_Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _fonction(nom):
    for n in _ast.walk(_ast.parse(_SRC_BOT)):
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name == nom:
            return _ast.unparse(n)
    raise AssertionError(nom)


def test_W1_le_demontage_passe_au_demarrage_avant_le_bilan():
    corps = _fonction("_travaux_de_demarrage")
    i_dem = corps.index("await _demonter_activite(g)")
    i_vis = corps.index("await _verifier_visibilite(g)")
    i_bil = corps.index("await _publier_bilan_sante(g)")
    assert i_dem < i_vis < i_bil


def test_W2_un_membre_depouille_qui_revient_recupere_ses_roles():
    corps = _fonction("on_member_join")
    assert "asyncio.create_task(_rendre_roles_au_retour(m))" in corps
    assert "_TACHES_RETOUR_ROLES.add(" in corps, "une tâche non retenue peut disparaître"
    assert "activite_demontage_module.rendre_au_retour" in _fonction("_rendre_roles_au_retour")


def test_W3_plus_rien_du_systeme_et_le_comptage_reste_pour_rellseas():
    for mort in ("activite_esc", "activite_niv", "activite_msg", "activite_rec",
                 "activite_pass", "activite_ui", "activite_passage_task",
                 "ActivitePanelV2", "masquer_nouveau_salon", "porte_une_etiquette"):
        assert mort not in _SRC_BOT, mort
    for source in ("SOURCE_MESSAGE", "SOURCE_REACTION", "SOURCE_VOCAL",
                   "SOURCE_INTERACTION", "SOURCE_FIL", "SOURCE_SONDAGE"):
        assert f"activite_module.{source}" in _SRC_BOT, f"comptage /rellseas : {source}"
    assert "activite_module.presence(" in _fonction("_activite_boot")


def _banc_demonter(res, config):
    envois = []

    class _SalonLog:
        async def send(self, texte, allowed_mentions=None):
            envois.append((texte, allowed_mentions))

    guild = type("G", (), {"id": 1, "name": "GoRP SEA",
                           "get_channel": lambda self, cid: _SalonLog() if cid == 4 else None})()

    async def _demonter(g, *, cfg, get_db, db_set):
        return res

    async def _cfg(_g):
        return config

    ns = {"cfg": _cfg, "get_db": None, "db_set": None, "discord": discord,
          "_logerr": lambda *a, **k: envois.append(("ERREUR", a)),
          "print": lambda *a, **k: None,
          "activite_demontage_module": type("D", (), {
              "demonter": staticmethod(_demonter),
              "bilan_texte": staticmethod(dem.bilan_texte),
              "a_agi": staticmethod(dem.a_agi)})}
    exec(_fonction("_demonter_activite"), ns)          # noqa: S102 — code du dépôt
    asyncio.run(ns["_demonter_activite"](guild))
    return envois


def _res(**kw):
    r = {"membres": 0, "rendus": 0, "absents": 0, "impossibles": [],
         "etiquettes": {"supprimes": [], "nettoyes": [], "bloques": []},
         "salons": {"supprimes": [], "gardes": []}, "fait": True, "deja": False}
    r.update(kw)
    return r


def test_W4_le_compte_rendu_va_une_fois_au_salon_de_logs_quand_il_y_a_eu_du_travail():
    agi = _res(membres=2, rendus=5, etiquettes={"supprimes": ["💤 AFK"],
                                                "nettoyes": [], "bloques": []})
    envois = _banc_demonter(agi, {"mod_log_channel": 4})
    ((texte, mentions),) = envois
    assert texte.startswith("🧹 **Système d'activité retiré**")
    assert "2 membre(s) ont récupéré 5 rôle(s)" in texte
    assert mentions is not None and mentions.roles is False and mentions.everyone is False
    assert _banc_demonter(_res(), {"mod_log_channel": 4}) == [], "rien fait : rien dit"
    assert len(_banc_demonter(_res(membres=1, rendus=1), {"mod_log_channel": 4})) == 1, \
        "des rôles rendus, et rien d'autre : c'est déjà du travail à dire"
    assert _banc_demonter(_res(deja=True, membres=1, rendus=1),
                          {"mod_log_channel": 4}) == [], "déjà démonté : silence"
