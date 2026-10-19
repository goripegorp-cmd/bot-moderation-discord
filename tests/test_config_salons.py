"""19/10/2026 : « everyone peut voir tous les salons sauf les salons où il y a déjà des rôles
spécifiques. Si c'est dans communautaire, ils peuvent tout voir dedans, rejoindre, parler,
sauf s'ils sont sanctionnés… juste celui qui fait des bêtises de partout ne voit plus rien »."""
from __future__ import annotations

import asyncio
import json

import discord

import config_salons as C

O = discord.PermissionOverwrite


class Role:
    def __init__(self, rid, nom="r"):
        self.id, self.name = rid, nom
        self.permissions = discord.Permissions.general()

    def __hash__(self):
        return self.id

    def __eq__(self, autre):
        return getattr(autre, "id", None) == self.id


class Salon:
    def __init__(self, sid, nom, type_=discord.ChannelType.text, categorie=None, ows=None):
        self.id, self.name, self.type, self.category = sid, nom, type_, categorie
        self.overwrites = dict(ows or {})
        self.poses = []

    def overwrites_for(self, cible):
        return self.overwrites.get(cible, O())

    async def set_permissions(self, cible, overwrite=None, reason=None):
        self.poses.append((cible, overwrite))
        if overwrite is None:
            self.overwrites.pop(cible, None)
        else:
            self.overwrites[cible] = overwrite


def serveur():
    tous, staff, radie, bot = Role(1, "@everyone"), Role(2, "Staff"), Role(3, "🚫 Radié"), Role(4, "Bot")
    commu = Salon(10, "🌍 COMMUNAUTAIRE", discord.ChannelType.category)
    salons = [
        commu,
        Salon(11, "💬général", categorie=commu, ows={tous: O(view_channel=False, send_messages=False)}),
        Salon(12, "📜règles", categorie=commu, ows={tous: O(send_messages=False)}),
        Salon(13, "🔊Vocal 1", discord.ChannelType.voice, commu, ows={tous: O(connect=False, speak=False)}),
        Salon(20, "🛡️equipe-staff", ows={tous: O(view_channel=False), staff: O(view_channel=True)}),
        Salon(21, "📋logs-mod", ows={tous: O(view_channel=False)}),
        Salon(22, "🎁-claim-free-nitro", ows={tous: O(view_channel=False)}),
        Salon(23, "🎮jeux", ows={tous: O(view_channel=False)}),
    ]
    g = type("G", (), {})()
    g.default_role, g.channels = tous, salons
    g.me = type("M", (), {"id": 4, "roles": [bot]})()
    return g, {s.id: s for s in salons}, tous, staff, radie


def test_K1_visible_sauf_reserve_logs_et_salon_piege():
    g, s, tous, staff, radie = serveur()
    actions = C.plan(g, ids_prives={22}, ids_lecture=set(), radie=None)
    touches = {a[0].id: a[3] for a in actions}
    assert set(touches) == {11, 13, 23}, touches
    assert "visible" in touches[23], "un salon caché sans raison redevient visible"
    for sid in (20, 21, 22):
        assert sid not in touches, "réservé à un rôle, logs ou salon piège : jamais touché"


def test_K2_communautaire_on_parle_sauf_dans_les_salons_a_lire():
    g, s, tous, staff, radie = serveur()
    actions = C.plan(g, ids_prives=set(), ids_lecture=set(), radie=None)
    neuf = {a[0].id: a[2] for a in actions}
    assert neuf[11].view_channel is None and neuf[11].send_messages is None
    assert neuf[13].connect is None and neuf[13].speak is None
    assert 12 not in neuf, "les règles restent en lecture"


def test_K3_le_radie_ne_voit_plus_rien_partout():
    g, s, tous, staff, radie = serveur()
    actions = C.plan(g, ids_prives=set(), ids_lecture=set(), radie=radie)
    sur_radie = {a[0].id for a in actions if a[1] == radie}
    assert sur_radie == set(s), "y compris les salons réservés"
    assert all(a[2].view_channel is False and a[2].send_messages is False
               for a in actions if a[1] == radie)


def test_K4_tout_s_annule_a_l_identique():
    g, s, tous, staff, radie = serveur()
    actions = C.plan(g, ids_prives=set(), ids_lecture=set(), radie=radie)
    avant = {sid: dict(x.overwrites) for sid, x in s.items()}
    instant = C.instantane(actions)
    asyncio.run(C.appliquer(actions))
    assert s[11].overwrites.get(tous) is None or s[11].overwrites[tous].view_channel is None
    g.get_channel = lambda cid: s.get(cid)
    g.get_role = lambda rid: {1: tous, 2: staff, 3: radie}.get(rid)
    g.get_member = lambda mid: None
    asyncio.run(C.restaurer(g, instant))
    for sid, x in s.items():
        assert {k.id: v.pair() for k, v in x.overwrites.items()} == \
            {k.id: v.pair() for k, v in avant[sid].items()}, sid
    assert json.loads(instant)
