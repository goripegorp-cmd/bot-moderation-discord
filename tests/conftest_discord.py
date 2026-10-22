"""Faux objets Discord partagés par les tests des sondages et des suggestions."""
from __future__ import annotations

import asyncio
import contextlib

import aiosqlite
import discord


async def laisser_finir(limite: float = 5.0):
    """Attend les tâches lancées en arrière-plan au lieu d'une durée fixe (sous charge,
    50 ms ne suffisaient pas toujours)."""
    boucle = asyncio.get_running_loop()
    fin = boucle.time() + limite
    while boucle.time() < fin:
        autres = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if not autres:
            return
        await asyncio.wait(autres, timeout=0.05)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def perms(staff=False, salons=True):
    return Obj(administrator=False, manage_messages=staff, manage_channels=salons, manage_roles=True)


class Partiel:
    def __init__(self, salon, mid):
        self.salon, self.id = salon, mid

    async def delete(self):
        self.salon.supprimes.append(self.id)

    async def edit(self, **kw):
        self.salon.edites.append((self.id, kw))


class Message:
    def __init__(self, salon, mid):
        self.salon, self.id = salon, mid
        self.jump_url = f"https://discord.com/channels/1/{salon.id}/{mid}"
        self.fils = []

    async def create_thread(self, **kw):
        fil = Obj(id=self.id + 50000, envois=[], **kw)

        async def send(texte, **k):
            fil.envois.append(texte)
        fil.send = send
        self.salon.fils[fil.id] = fil
        return fil


class Salon(discord.TextChannel):
    def __init__(self, sid=50, nom="salon"):
        self.id, self.name = sid, nom
        self.envois, self.supprimes, self.edites, self.fils = [], [], [], {}
        self._n = sid * 1000

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def send(self, content=None, **kw):
        self._n += 1
        self.envois.append((content, kw, self._n))
        return Message(self, self._n)

    def get_partial_message(self, mid):
        return Partiel(self, mid)

    async def fetch_message(self, mid):
        if mid in self.supprimes or not any(e[2] == mid for e in self.envois):
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return Message(self, mid)

    async def edit(self, **kw):
        self.name = kw.get("name", self.name)


class Role:
    def __init__(self, rid, nom):
        self.id, self.name, self.managed = rid, nom, False

    def __ge__(self, autre):
        return False


class Guilde:
    def __init__(self, *salons):
        self.id = 1
        self.salons = {s.id: s for s in salons}
        self.roles, self.crees = {}, []
        self.default_role = Obj(id=1)
        self.me = Obj(guild_permissions=perms(), top_role=Obj())

    def get_channel(self, cid):
        return self.salons.get(cid)

    def get_channel_or_thread(self, cid):
        return self.get_channel(cid) or self.get_thread(cid)

    def get_thread(self, tid):
        for s in self.salons.values():
            if tid in s.fils:
                return s.fils[tid]
        return None

    def get_role(self, rid):
        return self.roles.get(rid)

    async def create_role(self, name, **kw):
        r = Role(900 + len(self.roles), name)
        self.roles[r.id] = r
        return r

    async def create_text_channel(self, nom, **kw):
        s = Salon(70 + len(self.crees), nom)
        self.salons[s.id] = s
        self.crees.append((nom, kw))
        return s


class Reponse:
    def __init__(self):
        self.messages, self.modals, self.fait = [], [], False

    def is_done(self):
        return self.fait

    async def send_message(self, content=None, **kw):
        self.fait = True
        self.messages.append((content, kw))

    async def send_modal(self, modal):
        self.fait = True
        self.modals.append(modal)

    async def defer(self, **kw):
        self.fait = True


class Membre:
    def __init__(self, uid=7, staff=False, exclu=False):
        self.id, self.bot, self.mention = uid, False, f"<@{uid}>"
        self.display_name = f"Membre{uid}"
        self.guild_permissions = perms(staff)
        self._exclu = exclu
        self.roles = []

    def is_timed_out(self):
        return self._exclu


def interaction(g, membre, salon=None):
    suivis = []

    async def suivi(content=None, **kw):
        suivis.append(content)
    return Obj(guild=g, user=membre, response=Reponse(), followup=Obj(send=suivi), suivis=suivis,
               channel=salon, client=Obj(get_guild=lambda gid: g))


def base(tmp_path):
    chemin = tmp_path / "t.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    conf = {}

    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v
    return get_db, cfg, db_set, conf
