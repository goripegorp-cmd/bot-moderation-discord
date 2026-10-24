"""24/10/2026, le fondateur : « des conditions pour que les gens invitent des gens sur le serveur, et combien ils
doivent avoir d'invitations au total sur leur lien… de vrais systèmes de conditions qui valorisent le serveur »."""
from __future__ import annotations

import time

import discord
import pytest

import cadeaux as K
import invitations as I
from conftest_discord import Obj, base
from faux_serveur import Monde, interaction, run, textes

from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, _conf = base(tmp_path)
    I.setup(get_db=get_db, log=lambda *a: None)
    I._derniers.clear()
    run(I.init_db())

    async def autorise(_g, m):
        return m.id == 1

    async def noter(*_a, **_k):
        return None
    releves = []

    async def relever(g):
        releves.append(g.id)
        return await I.relever(g, forcer=True)
    K.setup(get_db=get_db, cfg=cfg, db_set=db_set, autorise=autorise, journal=noter, log=lambda *a: None,
            invitations=I.total, invitations_tous=I.totaux, relever=relever)
    for d in (K._actifs, K._tampon, K._dernier_msg, K._comptes, K._vocal, K._maj_prevues):
        d.clear()
    K._charges.clear()
    monkeypatch.setattr(K, "MAJ_CARTE_S", 0)
    run(K.init_db())
    return Obj(releves=releves)


def serveur(liens):
    g = Monde()
    g.voice_channels, g.stage_channels, g.afk_channel, g.premium_subscriber_role = [], [], None, None
    g.me.guild_permissions.manage_guild = True

    async def invites():
        return [Obj(code=code, inviter=Obj(id=uid, bot=False), uses=n) for code, uid, n in liens]
    g.invites = invites
    return g


def test_I1_le_total_de_ses_liens_meme_quand_un_lien_expire(env):
    liens = [("aaa", 7, 3), ("bbb", 7, 2), ("ccc", 8, 1)]
    g = serveur(liens)
    assert run(I.relever(g, forcer=True)) == 3
    assert run(I.total(g.id, 7)) == 5 and run(I.totaux(g.id)) == {7: 5, 8: 1}
    liens[:] = [("ccc", 8, 4)]          # « aaa » et « bbb » ont expiré, « ccc » a servi
    run(I.relever(g, forcer=True))
    assert run(I.total(g.id, 7)) == 5, "un lien expiré garde ses invitations"
    assert run(I.total(g.id, 8)) == 4
    assert run(I.relever(g)) == 0, "pas avant 5 minutes"
    g.me.guild_permissions.manage_guild = False
    assert run(I.relever(g, forcer=True)) == -1, "sans « Gérer le serveur », rien"


def test_I2_un_cadeau_a_invitations_refuse_compte_et_tire(env):
    g = serveur([("aaa", 11, 3), ("bbb", 12, 1)])
    run(I.relever(g, forcer=True))
    run(K.salon_cadeaux(g, creer=True))
    lien, erreur = run(K.lancer(g, g.membre(1), K.Brouillon(lot="Nitro", duree="2h", inv_min=2)))
    assert erreur == "" and run(K.charger(1))["inv_min"] == 2
    t = textes(run(K.salon_cadeaux(g)).envois[-1][2]["view"])
    assert "📨 **2** invitations" in t and "le total des personnes venues par tes liens" in t
    i = interaction(g, g.membre(12))
    run(K.participer(i, 1))
    t = textes(i.response.messages[-1][1]["view"])
    assert "Pas encore" in t and "Invitations : **1 / 2**" in t and run(K.inscrits(1)) == []
    i = interaction(g, g.membre(11))
    run(K.participer(i, 1))
    assert "Tu participes" in textes(i.response.messages[-1][1]["view"]) and run(K.inscrits(1)) == [11]
    v = run(K.vue_participants(g, run(K.charger(1)), 0))
    assert "✅ 1 remplit les conditions" in textes(v)
    run(K.terminer(g, 1))
    assert run(K.charger(1))["resultat"]["gagnants"] == [11] and env.releves == [g.id], "un relevé frais au tirage"


def test_I3_messages_ou_invitations(env):
    g = serveur([("aaa", 11, 1)])
    run(I.relever(g, forcer=True))
    c = {"guild_id": g.id, "msg_min": 10, "voc_min": 0, "inv_min": 1, "logique": "ou"}
    assert K.remplit(c, 0, 0, 1) and K.remplit(c, 10, 0, 0) and not K.remplit(c, 9, 0, 0)
    c["logique"] = "et"
    assert not K.remplit(c, 10, 0, 0) and K.remplit(c, 10, 0, 1)
    assert K.progres(c, 3, 0, 1) == "💬 3/10 · 📨 1/1" and K.nb_conditions(c) == 2


def test_I4_branche_dans_le_bot():
    assert "import invitations" in SRC and "invitations.setup(get_db=get_db" in SRC
    assert 'bot.add_listener(_invitations_lien, "on_invite_create")' in SRC
    assert 'bot.add_listener(_invitations_arrivee, "on_member_join")' in SRC
    assert "await invitations.relever(g)" in SRC and '"invitations_liens"' in SRC
    assert "invitations=invitations.total" in SRC
