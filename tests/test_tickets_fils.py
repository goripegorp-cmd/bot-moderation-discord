"""Tickets en fils privés (19/10/2026) : « optimiser ce système de tickets plutôt que d'avoir
des milliers de salons ». Un fil privé par ticket, un salon par équipe staff ; repli sur le
salon classique si le bot n'a pas les droits."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
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

    async def set_permissions(self, cible, **kw):
        self.perms.append((cible, kw))


class FausseGuilde:
    def __init__(self, droits=TOUS, fetch=None):
        self.id, self.icon, self.owner, self.owner_id = 1, None, None, 99
        self.default_role = Obj(id=1, name="@everyone")
        self.me = Obj(id=2, guild_permissions=droits)
        self.salons, self.crees, self.fetch = {}, [], fetch or {}

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

def _fonction(nom):
    for n in ast.walk(ast.parse(SRC)):
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


def _executer(get_db, conf, guilde):
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

    ns = {"discord": discord, "json": json, "get_db": get_db, "cfg": cfg, "db_set": db_set,
          "tickets_fils": tf, "webhook_send": webhook_send, "SUPER_OWNER_ID": 0,
          "_ticket_hours_allows": oui, "check_rate_limit": lambda *a: True,
          "_access_gate_reason": rien, "count_user_tickets_today": zero,
          "count_user_tickets": zero, "send_ticket_log": rien,
          "TicketControlView": lambda: "vue", "now": lambda: None,
          "rellseas_ui": rellseas_panneau, "recrutements": recrutements,
          "_logerr": lambda *a, **k: journaux.append(a)}
    ns["_tickets_en_creation"] = set()
    exec(_fonction("_create_ticket_corps"), ns)  # noqa: S102 — code du dépôt
    exec(_fonction("create_ticket"), ns)  # noqa: S102 — code du dépôt
    user = Obj(id=3, name="kolax_", mention="@kolax", display_avatar=Obj(url="u"))
    guilde.salons[40] = SimpleNamespace(id=40)
    i = SimpleNamespace(user=user, guild=guilde)
    ch, err = asyncio.run(ns["create_ticket"](i, "p1", {"Sujet": "Aide"}))
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
    assert envois and envois[0][0] is ch and envois[0][2]["view"] == "vue"


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
