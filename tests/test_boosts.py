"""19/10/2026 : « tu crées un salon à part qui s'appelle Boost… tu mets toutes celles et ceux qui ont
boosté le serveur, pour les remercier. Si quelqu'un ne booste plus… son remerciement s'enlève » ;
« pas de point dans le salon boost, juste l'émoji et le nom »."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
import pytest

import boosts as B
import config_salons
from conftest_discord import Obj, base

RACINE = Path(__file__).resolve().parent.parent
MOI = Obj(id=999)
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _absent():
    return discord.NotFound(Obj(status=404, reason="x"), "absent")


class Msg:
    def __init__(self, salon, mid, auteur=MOI):
        self.salon, self.id, self.author = salon, mid, auteur

    async def delete(self):
        if self.id not in self.salon.vues:
            raise _absent()
        del self.salon.vues[self.id]
        self.salon.supprimes.append(self.id)

    async def edit(self, *, view=None, **kw):
        if self.id not in self.salon.vues:
            raise _absent()
        self.salon.vues[self.id] = view
        self.salon.edites.append(self.id)


class SalonB:
    def __init__(self, sid=80, nom=B.NOM_SALON, categorie=None):
        self.id, self.name, self.category = sid, nom, categorie
        self.vues, self.auteurs, self.mentions = {}, {}, {}
        self.supprimes, self.edites = [], []
        self._n = 1000

    async def send(self, content=None, *, view=None, allowed_mentions=None):
        self._n += 1
        self.vues[self._n], self.auteurs[self._n], self.mentions[self._n] = view, MOI, allowed_mentions
        return Msg(self, self._n)

    async def history(self, limit=100):
        for mid in sorted(self.vues, reverse=True)[:limit]:
            yield Msg(self, mid, self.auteurs[mid])

    async def fetch_message(self, mid):
        if mid not in self.vues:
            raise _absent()
        return Msg(self, mid, self.auteurs[mid])

    def get_partial_message(self, mid):
        return Msg(self, mid)


class Serveur:
    def __init__(self, boosts=0, niveau=0):
        self.id, self.chunked, self.members = 1, True, []
        self.premium_subscription_count, self.premium_tier = boosts, niveau
        self.me = Obj(id=MOI.id, guild_permissions=Obj(manage_channels=True))
        self.default_role = Obj(id=1)
        self.communaute = Obj(id=300, name="💬 Communauté")
        self.categories = [Obj(id=200, name="📌 Information"), self.communaute]
        self.text_channels = [Obj(id=301, name="💬・chat", category=self.communaute)]
        self.salons, self.crees = {}, []

    def get_channel(self, cid):
        return self.salons.get(cid)

    async def create_text_channel(self, nom, **kw):
        s = SalonB(80, nom, kw.get("category"))
        self.salons[s.id] = s
        self.crees.append((nom, kw))
        return s


def membre(g, uid, jours=None, bot=False):
    m = Obj(id=uid, bot=bot, mention=f"<@{uid}>", guild=g,
            premium_since=None if jours is None else T0 + timedelta(days=jours),
            display_avatar=Obj(url=f"https://cdn.discordapp.com/avatars/{uid}/a.png"))
    g.members.append(m)
    return m


def textes(vue):
    def tout(c):
        yield c.get("content", "")
        for x in c.get("components", []) or []:
            yield from tout(x)
        if c.get("accessory"):
            yield from tout(c["accessory"])
    return " ".join(t for t in tout(vue.to_components()[0]) if t)


def cartes(salon):
    """Les cartes dans l'ordre du salon (l'en-tête en premier)."""
    return [textes(salon.vues[x]) for x in sorted(salon.vues)]


@pytest.fixture
def conf(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    B._verrous.clear()
    B.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None)
    asyncio.run(B.init_db())
    return conf


def _serveur():
    g = Serveur(boosts=3, niveau=1)
    a, b = membre(g, 11, jours=5), membre(g, 12, jours=2)
    membre(g, 13)
    membre(g, 14, jours=1, bot=True)
    return g, a, b


def test_B1_salon_sans_point_dans_communaute_en_lecture_seule(conf):
    g, a, b = _serveur()
    asyncio.run(B.installer(g, [Obj(id=50, name="Staff")]))
    nom, kw = g.crees[0]
    assert nom == "🚀boosts" and "・" not in nom and "•" not in nom
    assert kw["category"] is g.communaute
    tous = kw["overwrites"][g.default_role]
    assert tous.view_channel is True and tous.send_messages is False and tous.add_reactions is False
    salon = g.salons[80]
    entete, *reste = cartes(salon)
    assert "**3** boosts · niveau **1** · encore **4** pour le niveau 2" in entete
    assert len(reste) == 2, "ni le non-booster ni le bot"
    assert "### Merci <@12> 💜" in reste[0] and "### Merci <@11> 💜" in reste[1], "dans l'ordre des boosts"
    assert f"<t:{int(b.premium_since.timestamp())}:D>" in reste[0]
    assert all(m.users is False for m in salon.mentions.values()), "personne n'est mentionné à l'installation"
    assert conf["boosts_installe"] == 1


def test_B2_resynchroniser_ne_double_rien(conf):
    g, a, b = _serveur()

    async def scenario():
        await B.installer(g, [])
        salon = g.salons[80]
        n, edites = salon._n, list(salon.edites)
        await B.synchroniser(g)
        await B.installer(g, [])
        assert (salon._n, salon.edites, salon.supprimes) == (n, edites, [])
        assert len(g.crees) == 1, "le salon n'est créé qu'une fois"
    asyncio.run(scenario())


def test_B3_qui_arrete_perd_sa_carte_sans_message(conf):
    g, a, b = _serveur()

    async def scenario():
        await B.installer(g, [])
        salon = g.salons[80]
        n = salon._n
        a.premium_since = None
        assert await B.retirer(g, a.id)
        assert not any("<@11>" in t for t in cartes(salon)) and salon._n == n, "retirée, rien de posté"
        assert not await B.retirer(g, a.id)
        b.premium_since = None  # arrêt manqué (bot éteint) : le ménage le rattrape
        await B.synchroniser(g)
        assert len(cartes(salon)) == 1 and salon._n == n
    asyncio.run(scenario())


def test_B4_un_nouveau_boost_mentionne_une_seule_fois(conf):
    g, a, b = _serveur()

    async def scenario():
        await B.installer(g, [])
        salon = g.salons[80]
        c = membre(g, 15, jours=9)
        await B.ajouter(c, mentionner=True)
        mid = max(salon.vues)
        assert salon.mentions[mid].users == [c] and "### Merci <@15> 💜" in textes(salon.vues[mid])
        await B.ajouter(c, mentionner=True)
        assert max(salon.vues) == mid, "pas de deuxième carte"
        await B.ajouter(membre(g, 16), mentionner=True)
        assert max(salon.vues) == mid, "pas de carte sans boost"
    asyncio.run(scenario())


def test_B5_liste_incomplete_des_membres_personne_n_est_retire(conf):
    g, a, b = _serveur()

    async def scenario():
        await B.installer(g, [])
        salon = g.salons[80]
        g.chunked = False
        g.members.remove(a)
        await B.synchroniser(g)
        assert any("<@11>" in t for t in cartes(salon))
        g.chunked = True
        await B.synchroniser(g)
        assert not any("<@11>" in t for t in cartes(salon))
    asyncio.run(scenario())


def test_B6_carte_ou_en_tete_effaces_a_la_main_reviennent_dans_l_ordre(conf):
    g, a, b = _serveur()

    async def scenario():
        await B.installer(g, [])
        salon = g.salons[80]
        carte_a = next(x for x in salon.vues if "<@11>" in textes(salon.vues[x]))
        del salon.vues[carte_a]
        await B.synchroniser(g)
        assert sum("<@11>" in t for t in cartes(salon)) == 1
        del salon.vues[min(salon.vues)]
        await B.synchroniser(g)
        entete, *reste = cartes(salon)
        assert "boosts · niveau" in entete and "<@12>" in reste[0] and "<@11>" in reste[1] and len(reste) == 2
    asyncio.run(scenario())


def test_B7_l_en_tete_suit_le_nombre_de_boosts(conf):
    g, a, b = _serveur()

    async def scenario():
        await B.installer(g, [])
        salon = g.salons[80]
        g.premium_subscription_count, g.premium_tier = 7, 2
        await B.sur_maj_serveur(Obj(premium_subscription_count=3, premium_tier=1), g)
        assert "**7** boosts · niveau **2** · encore **7** pour le niveau 3" in cartes(salon)[0]
        g.premium_subscription_count, g.premium_tier = 14, 3
        await B.sur_maj_serveur(Obj(premium_subscription_count=7, premium_tier=2), g)
        assert "**14** boosts · niveau **3**" in cartes(salon)[0] and "encore" not in cartes(salon)[0]
    asyncio.run(scenario())


def test_B8_branche_dans_le_bot_et_plus_d_appel_public_a_l_arret():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "On perd un peu de soutien" not in src and "_build_boost_support_embed" not in src
    fns = {n.name: ast.unparse(n) for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "boosts.retirer(member.guild, member.id)" in fns["_handle_boost_stopped"]
    assert "boosts.ajouter(member, mentionner=True)" in fns["_handle_boost_started"]
    assert "boosts.retirer(m.guild, m.id)" in fns["on_member_remove"]
    assert "boosts.installer(" in fns["_boosts_au_demarrage"]
    assert '"_boosts_au_demarrage"' in src.split("_TRAVAUX = (")[1].split(")")[0]
    assert "boosts.synchroniser(g)" in fns["menage_salons_task"]
    assert 'bot.add_listener(boosts.sur_maj_serveur, "on_guild_update")' in src


def test_B9_le_plan_des_salons_le_garde_en_lecture_seule():
    tous = Obj(id=1)
    salon = Obj(id=80, name="🚀boosts", type=discord.ChannelType.text, category=Obj(id=300, name="💬 Communauté"),
                overwrites={})
    salon.overwrites_for = lambda cible: discord.PermissionOverwrite()
    g = Obj(default_role=tous, me=Obj(id=999, roles=[], guild_permissions=Obj(administrator=True)), channels=[salon])
    (s, cible, neuf, raison), = config_salons.plan_v2(g, None, [], set(), False)
    assert cible is tous and raison == "lecture seule (merci aux boosters)" and neuf.send_messages is False
