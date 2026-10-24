"""Tickets en fils privés (19/10/2026) : « optimiser ce système de tickets plutôt que d'avoir
des milliers de salons ». Un fil privé par ticket, un salon par équipe staff ; repli sur le
salon classique si le bot n'a pas les droits."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import functools
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import discord
import pytest

import recrutements
import rellseas_panneau
import tickets_fils as tf

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
TOUS = discord.Permissions.all()


class Obj:
    """Comme les vrais objets Discord : hachable (clé d'un dict de permissions)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class FauxFil(discord.Thread):
    def __init__(self, fid, nom, parent, refuse_ajout=False):
        self.id, self.name, self.parent_id = fid, nom, parent.id
        self._p, self.membres, self.envois = parent, [], []
        self.supprime, self.refuse_ajout, self.modifs = False, refuse_ajout, {}

    async def add_user(self, m):
        if self.refuse_ajout:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="x"), "refus")
        self.membres.append(m)

    async def delete(self):
        self.supprime = True

    async def send(self, **kw):
        self.envois.append(kw)


class FauxSalon(discord.TextChannel):
    def __init__(self, cid, nom, droits=TOUS, refuse_ajout=False):
        self.id, self.name, self.droits = cid, nom, droits
        self.fils, self.envois, self.perms = [], [], []
        self.refuse_ajout = refuse_ajout

    def permissions_for(self, _m):
        return self.droits

    async def create_thread(self, **kw):
        fil = FauxFil(9000 + len(self.fils), kw["name"], self, self.refuse_ajout)
        fil.kw = kw
        self.fils.append(fil)
        return fil

    async def send(self, *a, **kw):
        self.envois.append(a or kw)

    async def set_permissions(self, cible, overwrite=None, **kw):
        self.perms.append((cible, kw))
        if overwrite is not None:
            self.ows[cible] = overwrite

    def overwrites_for(self, cible):
        o = self.ows.get(cible) or (getattr(self, "kw", {}).get("overwrites") or {}).get(cible)
        return discord.PermissionOverwrite(**dict(iter(o))) if o is not None else discord.PermissionOverwrite()

    @property
    def ows(self):
        return self.__dict__.setdefault("_ows", {})


class FausseGuilde:
    def __init__(self, droits=TOUS, fetch=None):
        self.id, self.icon, self.owner, self.owner_id = 1, None, None, 99
        self.default_role = Obj(id=1, name="@everyone")
        self.me = Obj(id=2, guild_permissions=droits)
        self.salons, self.crees, self.fetch = {}, [], fetch or {}
        self.roles, self.membres = [], {}

    def get_member(self, uid):
        return self.membres.get(uid)

    def get_channel(self, cid):
        return self.salons.get(cid)

    def get_channel_or_thread(self, cid):
        return self.salons.get(cid)

    async def fetch_channel(self, cid):
        r = self.fetch.get(cid, discord.NotFound(SimpleNamespace(status=404, reason="x"), "x"))
        if isinstance(r, Exception):
            raise r
        return r

    async def create_text_channel(self, nom, **kw):
        ch = FauxSalon(500 + len(self.crees), nom)
        ch.kw = kw
        self.crees.append(ch)
        self.salons[ch.id] = ch
        return ch

    def get_role(self, rid):
        return Obj(id=rid, name="Staff Rell", mention="@staff") if rid else None


def _sans(*noms):
    p = discord.Permissions.all()
    for n in noms:
        setattr(p, n, False)
    return p


# ═══ Le module ════════════════════════════════════════════════════════════════

def test_F1_droits_du_bot():
    assert tf.possible(FausseGuilde())
    for d in ("manage_threads", "create_private_threads", "send_messages_in_threads"):
        assert not tf.possible(FausseGuilde(_sans(d))), d


def test_F2_le_salon_porteur_lecture_seule_le_staff_voit_tout():
    g = FausseGuilde()
    staff = g.get_role(7)
    ow = tf.permissions_parent(g, staff)
    tous = ow[g.default_role]
    assert (tous.view_channel, tous.send_messages, tous.send_messages_in_threads,
            tous.create_private_threads, tous.create_public_threads, tous.attach_files) == \
        (True, False, True, False, False, True)
    assert ow[staff].manage_threads and ow[g.me].manage_threads
    assert tf.nom_parent(staff) == "🎫・tickets-staff-rell" and tf.nom_parent(None) == "🎫・tickets"


def test_F3_un_salon_par_equipe_cree_une_fois():
    async def scenario():
        g, notes = FausseGuilde(), []

        async def garder(p):
            notes.append(p)
        cat, staff = SimpleNamespace(id=40), g.get_role(7)
        p1 = await tf.parent(g, cat, staff, {}, garder)
        assert notes == [{"40:7": p1.id}] and p1.kw["category"] is cat and p1.envois
        p2 = await tf.parent(g, cat, staff, notes[-1], garder)
        assert p2 is p1 and len(g.crees) == 1, "réutilisé, pas recréé"
        del g.salons[p1.id]
        p3 = await tf.parent(g, cat, staff, notes[-1], garder)
        assert p3 is not p1 and len(g.crees) == 2, "supprimé à la main : recréé"
        assert await tf.parent(FausseGuilde(_sans("manage_threads")), cat, staff, {}, garder) is None
    asyncio.run(scenario())


def test_F4_un_fil_prive_non_invitable_archive_a_7_jours():
    async def scenario():
        p = FauxSalon(5, "🎫・tickets")
        m = SimpleNamespace(id=3, name="kolax")
        fil = await tf.ouvrir(p, m, "ticket-kolax")
        assert fil.kw == {"name": "ticket-kolax", "type": discord.ChannelType.private_thread,
                          "invitable": False, "auto_archive_duration": 10080,
                          "reason": f"Ticket de {m}"}
        assert fil.membres == [m]
        refus = FauxSalon(6, "t", refuse_ajout=True)
        with pytest.raises(discord.HTTPException):
            await tf.ouvrir(refus, m, "ticket-x")
        assert refus.fils[0].supprime, "jamais de fil orphelin"
    asyncio.run(scenario())


def test_F5_un_fil_archive_n_est_pas_un_ticket_disparu():
    async def scenario():
        archive = FauxFil(77, "ticket-a", FauxSalon(5, "p"))
        panne = discord.HTTPException(SimpleNamespace(status=503, reason="x"), "x")
        g = FausseGuilde(fetch={77: archive, 78: panne})
        g.salons[12] = FauxSalon(12, "ticket-b")
        assert await tf.existe(g, 12) and await tf.existe(g, 77)
        assert await tf.existe(g, 78), "une panne ne ferme jamais un ticket"
        assert not await tf.existe(g, 79)
    asyncio.run(scenario())


def test_F6_ajouter_un_membre():
    async def scenario():
        fil, salon, m = FauxFil(1, "t", FauxSalon(5, "p")), FauxSalon(6, "s"), object()
        await tf.ajouter(fil, m)
        await tf.ajouter(salon, m)
        assert fil.membres == [m] and salon.perms[0][0] is m
        assert salon.perms[0][1]["attach_files"] and salon.perms[0][1]["embed_links"]
    asyncio.run(scenario())


# ═══ create_ticket, exécuté pour de vrai ═════════════════════════════════════

@functools.lru_cache(maxsize=None)
def _fonction(nom):
    for n in ast.walk(_arbre()):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


@pytest.fixture
def banc(tmp_path):
    base = tmp_path / "t.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id, "
                             "channel_id, user_id, panel_id, claimed_by, status, answers)")
            await db.commit()
    asyncio.run(preparer())
    return get_db


def _role(rid, nom, position, membres=()):
    r = Obj(id=rid, name=nom, mention=f"<@&{rid}>", position=position, managed=False, members=list(membres))
    r.is_default = lambda: False
    return r


class GuildeDirection(FausseGuilde):
    """Staff (7) < Recruteur Rell (8) < Direction (20) < Fondateur (30) ; 781205382923288593 = le fondateur."""

    def __init__(self, droits=TOUS, fetch=None):
        super().__init__(droits, fetch)
        self.recrue = Obj(id=50, bot=False)
        self.par_id = {r.id: r for r in (_role(7, "Staff", 2), _role(8, "Recruteur Rell", 3, [self.recrue]),
                                         _role(20, "Direction", 10), _role(30, "Fondateur", 11))}
        self.roles = list(self.par_id.values())
        self.fondateur = Obj(id=781205382923288593, name="goripe", mention="@goripe", roles=[self.par_id[30]],
                             display_avatar=Obj(url="u"))
        self.membres = {self.fondateur.id: self.fondateur}

    def get_role(self, rid):
        return self.par_id.get(rid)


def _ns_direction(ns):
    """Les aides du bot que `_create_ticket_corps` appelle, exécutées pour de vrai."""
    import owner_ids
    ns.update(TETE_IDS=frozenset({781205382923288593, 827633340797681714}), owner_ids_module=owner_ids)
    for nom in ("_direction_ou_plus", "_ticket_sans_limite", "_equipe_direction", "_equipe_du_type",
                "_types_tickets", "_au_dessus_de_la_direction"):
        exec(_fonction_def(nom), ns)  # noqa: S102 — code du dépôt


@functools.lru_cache(maxsize=None)
def _arbre():
    return ast.parse(SRC)  # une fois : bot.py fait 30 000 lignes


@functools.lru_cache(maxsize=None)
def _fonction_def(nom):
    for n in ast.walk(_arbre()):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


def _executer(get_db, conf, guilde, user=None, refus=False, pid="p1"):
    envois, journaux, ecrits = [], [], {}

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v
        conf[k] = v

    async def webhook_send(ch, plateforme, **kw):
        envois.append((ch, plateforme, kw))

    async def oui(*_a, **_k):
        return True, None

    async def rien(*_a, **_k):
        return None

    async def zero(*_a, **_k):
        return 0

    async def dossier(*_a, **_k):
        return "dossier"

    async def non(*_a, **_k):
        return False, "🕒 Les tickets ne peuvent être créés qu'à certaines heures"

    async def cinq(*_a, **_k):
        return 5

    async def trop_recent(*_a, **_k):
        return "🛡️ Ton compte Discord est trop récent"
    ns = {"discord": discord, "json": json, "get_db": get_db, "cfg": cfg, "db_set": db_set,
          "tickets_fils": tf, "webhook_send": webhook_send, "SUPER_OWNER_ID": 0,
          "_ticket_hours_allows": non if refus else oui, "check_rate_limit": lambda *a: not refus,
          "_access_gate_reason": trop_recent if refus else rien, "count_user_tickets_today": cinq if refus else zero,
          "count_user_tickets": cinq if refus else zero, "send_ticket_log": rien,
          "TicketControlView": lambda: "vue", "now": lambda: datetime(2026, 10, 22, tzinfo=timezone.utc),
          "rellseas_ui": rellseas_panneau, "recrutements": recrutements,
          "_logerr": lambda *a, **k: journaux.append(a), "_categorie_tickets": rien,
          "_vue_dossier_ticket": dossier, "int": int}
    ns["_tickets_en_creation"] = set()
    _ns_direction(ns)
    exec(_fonction("_create_ticket_corps"), ns)  # noqa: S102 — code du dépôt
    exec(_fonction("create_ticket"), ns)  # noqa: S102 — code du dépôt
    user = user or Obj(id=3, name="kolax_", mention="@kolax", display_avatar=Obj(url="u"), roles=[])
    guilde.salons[40] = SimpleNamespace(id=40)
    i = SimpleNamespace(user=user, guild=guilde)
    ch, err = asyncio.run(ns["create_ticket"](i, pid, {"Sujet": "Aide"}))
    return ch, err, envois, ecrits, journaux


def _ligne(get_db):
    async def lire():
        async with get_db() as db:
            async with db.execute("SELECT channel_id, user_id, panel_id, status FROM tickets") as c:
                return await c.fetchall()
    return asyncio.run(lire())


def _conf(**k):
    return {"ticket_panels": {"p1": {"category": 40, "staff_role": 7, "name": "Rell Seas"}},
            "ticket_staff": 0, **k}


def test_C1_le_ticket_s_ouvre_en_fil_prive(banc):
    g = FausseGuilde()
    ch, err, envois, ecrits, journaux = _executer(banc, _conf(), g)
    assert err is None and isinstance(ch, discord.Thread), (err, journaux)
    assert ch.name == "ticket-kolax_" and [m.id for m in ch.membres] == [3]
    assert len(g.crees) == 1 and g.crees[0].name == "🎫・tickets-staff-rell", \
        "UN salon pour l'équipe, aucun salon pour le ticket"
    assert ecrits[tf.CLE_PARENTS] == {"40:7": g.crees[0].id}
    assert _ligne(banc) == [(ch.id, 3, "p1", "open")]
    assert envois and envois[0][0] is ch and envois[0][2]["view"] == "dossier", "le dossier en tête du fil"


def test_C2_dix_tickets_un_seul_salon(banc):
    g = FausseGuilde()
    conf = _conf()
    for _ in range(10):
        _executer(banc, conf, g)
    assert len(g.crees) == 1 and len(g.crees[0].fils) == 10


@pytest.mark.parametrize("conf,droits", [(_conf(tickets_fils=0), TOUS),
                                         (_conf(), _sans("manage_threads"))])
def test_C3_repli_sur_le_salon_classique(banc, conf, droits):
    g = FausseGuilde(droits)
    ch, err, *_ = _executer(banc, conf, g)
    assert err is None and isinstance(ch, discord.TextChannel) and ch.name == "ticket-kolax_"
    assert ch.kw["category"] is g.salons[40] and len(g.crees) == 1


def test_C4_branchements_dans_le_bot():
    assert "if await tickets_fils.existe(g, chid):" in _fonction("count_user_tickets")
    assert "isinstance(channel, (discord.TextChannel, discord.Thread))" in _fonction("_tix_is_in_ticket")
    envoi = _fonction("webhook_send")
    assert envoi.index("isinstance(channel, discord.Thread)") < envoi.index("get_webhook(")
    assert "UPDATE tickets SET status='closed' WHERE channel_id=? AND status='open'" in \
        _fonction("on_raw_thread_delete")
    assert SRC.count("await i.channel.add_user(i.user)") == 1, "claim"
    assert SRC.count("await ch.add_user(new_staff)") == 1, "transfert"
    assert "await tickets_fils.ajouter(ch, st)" in SRC
    assert "i.guild.get_channel(self.chid)" not in SRC
    assert "'tickets_fils': 1, 'tickets_fils_parents': {}," in SRC


# ═══ 22/10/2026 : la direction et le fondateur voient tout, sans aucune restriction ═══════════

def test_D1_la_direction_et_le_fondateur_ne_sont_jamais_bloques(banc):
    """« Eux n'ont aucune restriction d'heure ou autre pour créer des tickets. »"""
    conf = _conf(direction_allowed_role=20, tickets_per_day=1)
    conf["ticket_panels"]["p1"].update(disabled=True, max=1, blacklist=[781205382923288593, 3])
    g = GuildeDirection()
    ch, err, *_ = _executer(banc, conf, g, user=g.fondateur, refus=True)
    assert err is None and isinstance(ch, discord.Thread), "hors horaires, type fermé, max, quota, blacklist : ouvert"
    chef = Obj(id=60, name="dir", mention="@dir", roles=[g.par_id[20]], display_avatar=Obj(url="u"))
    ch, err, *_ = _executer(banc, conf, g, user=chef, refus=True)
    assert err is None, "le rôle direction aussi"
    membre = Obj(id=3, name="kolax_", mention="@kolax", roles=[g.par_id[7]], display_avatar=Obj(url="u"))
    _ch, err, *_ = _executer(banc, conf, g, user=membre)
    assert err and "fermés pour le moment" in err, "un membre lit que le type est fermé"
    conf["ticket_panels"]["p1"]["disabled"] = False
    _ch, err, *_ = _executer(banc, conf, g, user=membre, refus=True)
    assert err and "certaines heures" in err, "et les horaires restent pour les membres"


def test_D2_un_ticket_rell_seas_est_vu_par_les_roles_du_clan_et_la_direction(banc):
    conf = _conf(direction_allowed_role=20, rellseas_roles_autorises=[8])
    g = GuildeDirection()
    ch, err, _envois, ecrits, _j = _executer(banc, conf, g)
    assert err is None and isinstance(ch, discord.Thread)
    porteur = g.crees[0]
    assert porteur.name == "🎫・tickets-rell-seas" and ecrits[tf.CLE_PARENTS] == {"40:7:rell": porteur.id}, \
        "les tickets Rell Seas ont leur salon : le clan ne voit pas les autres"
    ows = porteur.kw["overwrites"]
    for rid in (7, 8, 20):
        assert ows[g.par_id[rid]].manage_threads and ows[g.par_id[rid]].view_channel, rid
    assert ows[g.fondateur].manage_threads, "le compte du fondateur aussi"
    assert g.par_id[30] not in ows, "24/10 (revue) : un rôle rangé au-dessus de la direction ne voit plus tout"
    conf["ticket_panels"]["p2"] = {"category": 40, "staff_role": 7, "name": "Support"}
    ch2, err, *_ = _executer(banc, conf, g, pid="p2")
    assert err is None and ch2.parent_id != porteur.id and g.par_id[8] not in g.crees[1].kw["overwrites"], \
        "un ticket Support : le clan ne le voit pas, la direction si"
    assert g.crees[1].kw["overwrites"][g.par_id[20]].manage_threads


def test_D3_un_salon_porteur_d_avant_est_complete_jamais_retire(banc):
    conf = _conf(direction_allowed_role=20)
    conf["ticket_panels"]["p1"]["name"] = "Support"
    g = GuildeDirection()
    ancien = FauxSalon(77, "🎫・tickets-staff")
    ancien.kw = {"overwrites": {g.par_id[7]: discord.PermissionOverwrite(**tf.DROITS_EQUIPE),
                                g.par_id[30]: discord.PermissionOverwrite(view_channel=True, send_messages=False)}}
    g.salons[77] = ancien
    conf[tf.CLE_PARENTS] = {"40:7": 77}
    ch, err, *_ = _executer(banc, conf, g)
    assert err is None and ch.parent_id == 77 and not g.crees, "le salon d'avant sert toujours"
    complete = {c.id for c, _kw in ancien.perms}
    assert complete == {20, 781205382923288593} and ancien.ows[g.par_id[20]].manage_threads, \
        "ce qui manquait est ajouté : le rôle direction et le compte du fondateur (24/10 : pas les rôles au-dessus)"
    assert ancien.overwrites_for(g.par_id[30]).send_messages is False, "un réglage posé à la main reste"
    _executer(banc, conf, g)
    assert len(ancien.perms) == 2, "la fois suivante : rien à refaire"


def test_D4_le_menu_du_panneau_montre_les_types_fermes_a_la_direction():
    ns = {}
    _ns_direction(ns)
    c = {"ticket_panels": {"a": {"name": "Support"}, "b": {"name": "Rell Seas", "disabled": True}}}
    assert [p for p, _x in ns["_types_tickets"](c)] == ["a"], "les membres : les types ouverts"
    tous = ns["_types_tickets"](c, tous=True)
    assert [p for p, _x in tous] == ["a", "b"] and "Fermé aux membres" in tous[1][1]["embed_description"]
    assert "disabled" in tous[1][1] and "embed_description" not in c["ticket_panels"]["b"], "la config intacte"
    assert "_types_tickets(c, tous=_ticket_sans_limite(i.guild, i.user, c))" in SRC
    ouvrir = _fonction("_ticket_ouvrir")
    for regle in ("if pnl.get('disabled') and (not libre):", "if i.user.id in blacklist and (not libre):",
                  "if not libre and await count_user_tickets(i.guild, i.user.id, pid) >= mx:"):
        assert regle in ouvrir, regle
    assert ouvrir.index("libre = _ticket_sans_limite(") < ouvrir.index("_ticket_hours_allows(")


class FilPorte(FauxFil):
    parent = property(lambda self: self._p)


def test_D5_une_fois_les_tickets_ouverts_et_les_salons_recoivent_ce_qui_manque(banc):
    conf = _conf(direction_allowed_role=20, rellseas_roles_autorises=[8])
    g = GuildeDirection()
    porteur = FauxSalon(77, "🎫・tickets-staff")
    porteur.kw = {"overwrites": {g.par_id[7]: discord.PermissionOverwrite(**tf.DROITS_EQUIPE)}}
    porteur.permissions_for = lambda cible: discord.Permissions(manage_threads=cible.id in (7, 20, 30))
    fil = FilPorte(9001, "ticket-a", porteur)
    classique = FauxSalon(78, "ticket-b")
    g.salons.update({77: porteur, 9001: fil, 78: classique})
    conf[tf.CLE_PARENTS] = {"40:7": 77}

    async def remplir():
        async with banc() as db:
            await db.execute("INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, status) "
                             "VALUES(1, 9001, 3, 'p1', 'open'), (1, 78, 4, 'p1', 'open')")
            await db.commit()
    asyncio.run(remplir())
    journal = []

    async def cfg(_g):
        return conf

    async def _au_journal(*a, **_k):
        journal.append(a)
    ns = {"discord": discord, "cfg": cfg, "get_db": banc, "tickets_fils": tf, "rellseas_ui": rellseas_panneau,
          "_au_journal": _au_journal, "_logerr": lambda *a, **k: None}
    _ns_direction(ns)
    exec(_fonction("_tickets_visibilite"), ns)  # noqa: S102 — code du dépôt
    n = asyncio.run(ns["_tickets_visibilite"](g))
    assert {c.id for c, _kw in porteur.perms} == {20, 781205382923288593}, \
        "la direction (le rôle, pas ceux au-dessus — 24/10) et le fondateur voient le salon porteur"
    assert fil.membres == [g.recrue], "le ticket Rell Seas ouvert accueille le recruteur du clan"
    assert {c.id for c, _kw in classique.perms} >= {7, 8, 20} and classique.ows[g.par_id[8]].send_messages
    assert g.par_id[30] not in classique.ows
    assert n == 2 + 1 + 4 and "la direction et le fondateur voient tous les tickets" in journal[-1][3]
    boucle = _fonction("entraide_task")
    assert boucle.index("db_set(g.id, 'tickets_visibilite_v1'") < boucle.index("_tickets_visibilite(g)"), "une fois"
    assert '"tickets_direction": any(' in SRC, "/stats le dit"


def test_D6_les_horaires_ne_bloquent_jamais_la_direction():
    corps = _fonction("_ticket_hours_allows")
    assert "user_id in TETE_IDS" in corps and "_ticket_sans_limite(guild, guild.get_member(user_id), _c)" in corps
    creer = _fonction("_create_ticket_corps")
    assert creer.index("libre = _ticket_sans_limite(") < creer.index("_ticket_hours_allows(")
    for garde in ("if not libre:", "_gate = '' if libre else await _access_gate_reason(",
                  "if not libre and await count_user_tickets(i.guild, i.user.id, pid) >= mx:"):
        assert garde in creer, garde
