"""19/10/2026 : « mettre des zones sociales [en fils] […] au lieu d'avoir chat, média ou
autre, on a un truc qui regroupe un peu tout ». Une zone = un fil privé dans un salon porteur
par type ; repli sur le salon classique si le bot n'a pas les droits."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord

import social_zones as sz

TOUS = discord.Permissions.all()


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Fil(discord.Thread):
    def __init__(self, fid, nom):
        self.id, self.name, self.membres, self.retires, self.supprime = fid, nom, [], [], False

    async def add_user(self, m):
        self.membres.append(m.id)

    async def remove_user(self, m):
        self.retires.append(m.id)

    async def delete(self):
        self.supprime = True


class Porteur(discord.TextChannel):
    def __init__(self, cid, nom):
        self.id, self.name, self._fils, self.envois = cid, nom, [], []

    @property
    def threads(self):
        return self._fils

    async def create_thread(self, **kw):
        f = Fil(700 + len(self._fils), kw["name"])
        f.kw = kw
        self._fils.append(f)
        return f

    async def send(self, *a, **k):
        self.envois.append(a)


class Categorie:
    def __init__(self, nom):
        self.name, self.text_channels, self.channels = nom, [], []


class Guilde:
    def __init__(self, droits=TOUS):
        self.default_role = Obj(id=1)
        self.me = Obj(id=2, guild_permissions=droits)
        self.categories, self.text_channels, self.crees = [], [], []
        self.roles = []

    def get_role(self, _r):
        return None

    async def create_category(self, name, **kw):
        c = Categorie(name)
        self.categories.append(c)
        return c

    async def create_text_channel(self, nom=None, **kw):
        nom = nom or kw.pop("name")
        ch = Porteur(500 + len(self.crees), nom)
        ch.kw = kw
        self.crees.append(ch)
        if kw.get("category") is not None:
            kw["category"].text_channels.append(ch)
        return ch


def test_Z1_une_zone_est_un_fil_prive_dans_le_salon_du_type():
    async def scenario():
        g = Guilde()
        a, b = Obj(id=10), Obj(id=11)
        f1 = await sz._create_zone_channel(g, "trade", [a, b], "kolax-et-toto")
        f2 = await sz._create_zone_channel(g, "trade", [a], "autre")
        assert isinstance(f1, discord.Thread) and f1.membres == [10, 11]
        assert f1.kw["type"] == discord.ChannelType.private_thread and f1.kw["invitable"] is False
        assert f1.name == "🤝-trade-kolax-et-toto"
        assert [c.name for c in g.crees] == ["🤝・échanges"], "UN salon pour tous les échanges"
        assert f2 in g.crees[0].threads and len(g.crees[0].threads) == 2
    asyncio.run(scenario())


def test_Z2_sans_droits_le_salon_classique():
    async def scenario():
        p = discord.Permissions.all()
        p.manage_threads = False
        g = Guilde(p)
        ch = await sz._create_zone_channel(g, "group", [Obj(id=10)], "raid")
        assert isinstance(ch, discord.TextChannel) and ch.name == "👥-groupe-raid"
        assert ch.kw["overwrites"], "salon privé d'avant, avec ses permissions"
    asyncio.run(scenario())


def test_Z3_entrer_et_sortir_d_une_zone_en_fil():
    async def scenario():
        f = Fil(1, "👥-groupe-x")
        await sz._ouvrir_a(f, Obj(id=12), "Rejoint")
        assert f.membres == [12]
        salon = Obj(perms=[])

        async def set_permissions(m, **kw):
            salon.perms.append((m.id, kw))
        salon.set_permissions = set_permissions
        await sz._ouvrir_a(salon, Obj(id=13), "Rejoint")
        assert salon.perms[0][0] == 13 and salon.perms[0][1]["overwrite"].view_channel
    asyncio.run(scenario())


def test_Z4_les_fils_orphelins_d_un_redemarrage_sont_balayes(monkeypatch):
    async def scenario():
        porteur = Porteur(50, "👥・groupes")
        vivant, orphelin, autre = Fil(1, "👥-groupe-a"), Fil(2, "👥-groupe-b"), Fil(3, "discussion")
        porteur._fils = [vivant, orphelin, autre]
        cat = Categorie("👥 Groupes")
        cat.channels = [porteur]
        g = Obj(categories=[cat], text_channels=[])

        class _Db:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def execute(self, q, *a):
                ids = [(1,)] if "channel_id FROM" in q else []

                class _C:
                    async def __aenter__(s):
                        return s

                    async def __aexit__(s, *a):
                        return False

                    async def fetchall(s):
                        return ids
                return _C()
        monkeypatch.setattr(sz, "_get_db", lambda: _Db())
        monkeypatch.setattr(sz, "_bot", Obj(guilds=[g]))
        await sz._boot_reconcile_orphans()
        assert (vivant.supprime, orphelin.supprime, autre.supprime) == (False, True, False)
    asyncio.run(scenario())


def test_Z5_le_salon_d_une_zone_se_cherche_avec_les_fils():
    src = open(sz.__file__, encoding="utf-8").read()
    assert 'get_channel(int(z["channel_id"]))' not in src
    assert src.count('get_channel_or_thread(int(z["channel_id"]))') >= 7
    assert "await channel.remove_user(discord.Object(id=int(user_id)))" in src
