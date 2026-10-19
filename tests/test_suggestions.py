"""19/10/2026 : « on mettra que les nouvelles suggestions, de vraies suggestions » ; « un rôle
ping, personne n'est ping au début » ; « logs suggestions… qui a créé la suggestion… au
propre, un vrai suivi » ; puis « l'affichage dans suggestion, il est moche… que tous les salons
soient beaux » et « ils ne peuvent que cocher la suggestion, ni messages ni réactions »."""
from __future__ import annotations

import asyncio

import discord
import pytest

import notifs
import suggestions as G
from conftest_discord import Guilde, Membre, Obj, Salon, base, interaction, laisser_finir


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    salon, logs = Salon(51, "💡suggestions"), Salon(61, "💡logs-suggestions")
    g = Guilde(salon, logs)

    async def texte_refuse(_g, t):
        return "Mot interdit." if "interdit" in t else ""

    async def controle(_m, _c):
        return ""

    async def salon_logs(_g, cle, nom):
        assert (cle, nom) == ("suggestions", "💡logs-suggestions")
        return logs
    G._verrous.clear()
    G._rappels.clear()
    G.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse, controle=controle,
            salon_logs=salon_logs, log=lambda *a: None)
    notifs.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    asyncio.run(G.init_db())
    conf["suggestions_salon"] = salon.id
    return Obj(g=g, salon=salon, logs=logs, conf=conf, get_db=get_db)


def run(coro):
    async def _avec_taches():
        r = await coro
        await laisser_finir()
        return r
    return asyncio.run(_avec_taches())


def _textes(vue):
    def tout(c):
        yield c.get("content", "")
        for x in c.get("components", []) or []:
            yield from tout(x)
    return " ".join(t for t in tout(vue.to_components()[0]) if t)


def _ids(vue):
    return [b["custom_id"] for r in vue.to_components()[0]["components"] if r.get("type") == 1
            for b in r["components"]]


def test_G1_une_idee_devient_une_carte_propre_et_sa_trace(env):
    i = interaction(env.g, Membre())
    run(G.publier(i, "Un salon musique", "Pour partager des sons."))
    vue = env.salon.envois[0][1]["view"]
    texte = _textes(vue)
    assert "### Un salon musique" in texte and "Pour partager des sons." in texte
    assert "🟡 En attente · idée n°1 · proposée par <@7>" in texte and "Pas encore de vote" in texte
    assert "-# <@&" in texte, "le rôle prévenu en bas, discrètement"
    assert "▰" not in texte and "▱" not in texte, "plus de barre en caractères"
    assert _ids(vue) == ["sug:p:1", "sug:c:1", "sug:g:1"]
    assert not env.salon.fils, "plus de fil : on ne discute pas dans le salon"
    assert i.suivis[0].startswith("Idée publiée")


def test_G2_un_vote_par_membre_modifiable(env):
    run(G.publier(interaction(env.g, Membre()), "Idée", ""))

    async def scenario():
        for uid, sens in ((10, 1), (11, 1), (12, -1), (12, 1), (11, 1)):
            await G.voter(interaction(env.g, Membre(uid), env.salon), 1, sens)
        await asyncio.sleep(3.2)
        return await G.charger(1)
    s, pour, contre = asyncio.run(scenario())
    assert (pour, contre) == (2, 0), "12 change d'avis, 11 retire son vote"
    carte = env.salon.edites[-1][1]["view"]
    assert "100 % d'accord · 2 votes" in _textes(carte)
    libelles = [b.get("label") for r in carte.to_components()[0]["components"] if r.get("type") == 1 for b in r["components"]]
    assert libelles[:2] == ["Pour · 2", "Contre · 0"]


def test_G3_le_staff_tranche_l_auteur_est_prevenu_les_logs_suivent(env):
    auteur, recus = Membre(), []

    async def send(view=None, **kw):
        recus.append(view)
    auteur.send = send
    env.g.get_member = {7: auteur}.get
    run(G.publier(interaction(env.g, Membre()), "Idée", "Détails"))
    assert "Idée n°1 · 🟡 En attente" in _textes(env.logs.envois[0][1]["view"])
    refus = interaction(env.g, Membre(8))
    asyncio.run(G.BoutonGerer(1).callback(refus))
    assert refus.response.messages[0][0] == "Réservé au staff."
    staff = interaction(env.g, Membre(9, staff=True), env.salon)
    run(G.decider(staff, 1, "acceptee", "Prévu pour samedi."))
    carte = env.salon.edites[-1][1]["view"]
    assert "🟢 Acceptée" in _textes(carte) and "Prévu pour samedi." in _textes(carte)
    assert _ids(carte) == ["sug:g:1"], "votes clos après la décision"
    assert "Réponse du staff · Acceptée" in _textes(carte) and "Votes clos" in _textes(carte)
    prive = _textes(recus[-1])
    assert "Ton idée a une réponse" in prive and "🟢 **Acceptée**" in prive and "Prévu pour samedi." in prive
    journal = _textes(env.logs.edites[-1][1]["view"])
    assert "Idée n°1 · 🟢 Acceptée" in journal and "Décision : <@9>" in journal and "`7`" in journal


def test_G4_limites_et_filtres(env):
    async def scenario():
        refus = []
        for _ in range(4):
            i = interaction(env.g, Membre())
            await G.publier(i, "Idée", "")
            refus.append(i.response.messages)
        i = interaction(env.g, Membre(20))
        await G.publier(i, "Idée interdit", "")
        refus.append(i.response.messages)
        await laisser_finir()
        return refus
    refus = asyncio.run(scenario())
    assert refus[:3] == [[], [], []] and "3 idées par jour" in refus[3][0][0]
    assert "Mot interdit." in _textes(refus[4][0][1]["view"])


def test_G5_salon_cree_une_fois_sans_messages(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    G.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None,
            salon_logs=None, log=lambda *a: None)
    asyncio.run(G.init_db())
    g = Guilde()
    asyncio.run(G.installer(g))
    nom, kw = g.crees[0]
    tous = kw["overwrites"][g.default_role]
    assert nom == "💡suggestions" and tous.send_messages is False and tous.send_messages_in_threads is False
    salon = g.salons[conf["suggestions_salon"]]

    class Msg:
        def __init__(self, canal):
            self.guild, self.channel, self.author = g, canal, Membre()
            self.webhook_id, self.supprime = None, False

        async def delete(self):
            self.supprime = True
    dans_salon, dans_fil = Msg(salon), Msg(Obj(id=999))
    asyncio.run(G.sur_message(dans_salon))
    asyncio.run(G.sur_message(dans_fil))
    assert dans_salon.supprime and not dans_fil.supprime


def test_G6_les_anciennes_cartes_sont_refaites_une_fois(env):
    for k in range(2):
        run(G.publier(interaction(env.g, Membre(30 + k)), f"Idée {k}", ""))
    env.conf.pop("suggestions_v3", None)
    avant = len(env.salon.edites)
    run(G.installer(env.g))
    refaites = env.salon.edites[avant:]
    assert len(refaites) == 2 and env.conf["suggestions_v3"] == 1
    assert all("Pas encore de vote" in _textes(kw["view"]) for _mid, kw in refaites)
    run(G.installer(env.g))
    assert len(env.salon.edites) == avant + 2, "une seule fois"
