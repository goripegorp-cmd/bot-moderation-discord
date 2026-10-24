"""24/10/2026, le fondateur : « des conditions pour que les gens invitent des gens… attention aux faux comptes, les
comptes doubles, il faut vraiment que ce soit sûr. Les gens qui sont invités puis qui quittent directement, il faut
que ce soit bien enlevé des statistiques. D'autres conditions… d'ancienneté »."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import cadeaux as K
import invitations as I
from conftest_discord import Obj, base
from faux_serveur import Monde, interaction, run, textes

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, _conf = base(tmp_path)
    I.setup(get_db=get_db, log=lambda *a: None)
    for d in (I._photos, I._verrous, I._menages):
        d.clear()
    run(I.init_db())

    async def autorise(_g, m):
        return m.id == 1

    async def noter(*_a, **_k):
        return None
    K.setup(get_db=get_db, cfg=cfg, db_set=db_set, autorise=autorise, journal=noter, log=lambda *a: None,
            invitations=I.total, invitations_tous=I.totaux, relever=I.reconcilier)
    for d in (K._actifs, K._tampon, K._dernier_msg, K._comptes, K._vocal, K._maj_prevues):
        d.clear()
    K._charges.clear()
    monkeypatch.setattr(K, "MAJ_CARTE_S", 0)
    run(K.init_db())
    return Obj()


def serveur(liens):
    """`liens` : [code, auteur, utilisations] — modifiable pendant le test."""
    g = Monde()
    g.voice_channels, g.stage_channels, g.afk_channel, g.premium_subscriber_role = [], [], None, None
    g.me.guild_permissions.manage_guild = True
    g.lectures = 0

    async def invites():
        g.lectures += 1
        return [Obj(code=c, inviter=Obj(id=a), uses=n, max_uses=0) for c, a, n in liens]
    g.invites = invites
    return g


def arrivant(g, uid, age_compte_j=30):
    m = g.membre(uid)
    m.created_at = datetime.now(timezone.utc) - timedelta(days=age_compte_j)
    return m


def test_I1_le_lien_qui_a_servi_seulement_quand_c_est_sur():
    avant = {"aaa": (7, 3, 0), "bbb": (8, 1, 0)}
    assert I.lien_utilise(avant, {"aaa": (7, 4, 0), "bbb": (8, 1, 0)}) == "aaa"
    assert I.lien_utilise(avant, {"aaa": (7, 4, 0), "bbb": (8, 2, 0)}) is None, "deux arrivées à la fois"
    assert I.lien_utilise(avant, {"aaa": (7, 5, 0), "bbb": (8, 1, 0)}) is None, "deux arrivées par le même lien"
    assert I.lien_utilise(avant, {"aaa": (7, 3, 0), "bbb": (8, 1, 0)}) is None, "le lien personnalisé du serveur"
    assert I.lien_utilise(avant, {"aaa": (7, 3, 0), "bbb": (8, 1, 0), "ccc": (9, 1, 0)}) == "ccc", "un lien neuf"
    assert I.lien_utilise(avant, {"bbb": (8, 1, 0)}) is None, "un lien qui disparaît : on ne devine pas"


def test_I2_seuls_les_vrais_invites_encore_la_comptent(env):
    liens = [["aaa", 7, 0], ["bbb", 8, 0]]
    g = serveur(liens)
    assert run(I.photographier(g)) == 2
    liens[0][2] = 1
    assert run(I.sur_arrivee(arrivant(g, 21))) == 7 and run(I.total(g.id, 7)) == 1
    liens[0][2] = 2
    assert run(I.sur_arrivee(arrivant(g, 22, age_compte_j=2))) == 7
    assert run(I.total(g.id, 7)) == 1, "un compte de 2 jours ne compte pas (faux compte)"
    assert run(I.sur_arrivee(arrivant(g, 23))) == 0, "le lien personnalisé : personne"
    liens[0][2], liens[1][2] = 3, 1
    assert run(I.sur_arrivee(arrivant(g, 24))) == 0, "deux arrivées à la fois : personne"
    liens[0][2] = 4
    assert run(I.sur_arrivee(arrivant(g, 7))) == 0, "on ne s'invite pas soi-même"
    run(I.sur_depart(g.membres[21]))
    assert run(I.total(g.id, 7)) == 0, "parti : enlevé tout de suite"
    liens[1][2] = 2
    assert run(I.sur_arrivee(g.membres[21])) == 8, "revenu par un autre lien"
    assert run(I.totaux(g.id)) == {8: 1}, "un membre ne compte qu'une fois, pour le dernier"
    del g.membres[21]                   # parti pendant une coupure du bot
    assert run(I.reconcilier(g)) == 1 and run(I.totaux(g.id)) == {}
    r = run(I.releve(g.id))
    assert r["comptes_neufs"] == 1 and r["comptent"] == 0 and r["photo"]


def test_I3_une_rafale_n_interroge_pas_discord(env):
    liens = [["aaa", 7, 0]]
    g = serveur(liens)
    run(I.photographier(g))
    lectures = g.lectures

    async def rafale():
        async with I._verrou(g.id):
            return await I.sur_arrivee(arrivant(g, 30))
    assert asyncio.run(rafale()) == 0 and g.lectures == lectures


def test_I4_cadeau_invitations_et_anciennete(env):
    liens = [["aaa", 11, 0]]
    g = serveur(liens)
    run(I.photographier(g))
    liens[0][2] = 1
    run(I.sur_arrivee(arrivant(g, 40)))
    run(K.salon_cadeaux(g, creer=True))
    run(K.lancer(g, g.membre(1), K.Brouillon(lot="Nitro", duree="2h", inv_min=1, anc_min=30)))
    t = textes(run(K.salon_cadeaux(g)).envois[-1][2]["view"])
    assert "📨 **1** invitation" in t and "📅 **30** jours sur le serveur" in t
    nouveau, ancien = g.membre(12), g.membre(11)
    nouveau.joined_at = datetime.now(timezone.utc) - timedelta(days=10)
    ancien.joined_at = datetime.now(timezone.utc) - timedelta(days=45)
    i = interaction(g, nouveau)
    run(K.participer(i, 1))
    t = textes(i.response.messages[-1][1]["view"])
    assert "Invitations : **0 / 1**" in t and "Ancienneté · Seniority : **10 / 30 j**" in t and run(K.inscrits(1)) == []
    i = interaction(g, ancien)
    run(K.participer(i, 1))
    assert "Tu participes" in textes(i.response.messages[-1][1]["view"]) and run(K.inscrits(1)) == [11]
    del g.membres[40]                   # son invité est parti : au tirage, il ne compte plus
    run(K.terminer(g, 1))
    assert run(K.charger(1))["resultat"]["gagnants"] == []


def test_I5_branche_dans_le_bot_et_le_bump_retire():
    assert 'bot.add_listener(_invitations_arrivee, "on_member_join")' in SRC
    assert 'bot.add_listener(_invitations_depart, "on_member_remove")' in SRC
    assert 'bot.add_listener(_invitations_lien, "on_invite_create")' in SRC
    assert "await invitations.entretenir(g)" in SRC and '"invitations": next(' in SRC
    assert "relever=invitations.reconcilier" in SRC and '"invitations_liens"' in SRC.split("_TABLES_MORTES", 1)[1]
    for mort in ("bump_reminder", "_bump_last", "_DISBOARD_ID", "_bump_detect_listener"):
        assert mort not in SRC, mort
