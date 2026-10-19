"""19/10/2026 : « un système de sondage, un salon spécifique que je peux déplacer où je veux…
de vrais sondages ultra optimisés… les gens appuient sur un bouton, ils créent leur sondage »."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from pathlib import Path

import aiosqlite
import discord
import pytest

import sondages as S

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def perms(staff=False, salons=True):
    return Obj(administrator=False, manage_messages=staff, manage_channels=salons)


class Partiel:
    def __init__(self, salon, mid):
        self.salon, self.id = salon, mid

    async def delete(self):
        self.salon.supprimes.append(self.id)

    async def edit(self, **kw):
        self.salon.edites.append((self.id, kw))


class Salon(discord.TextChannel):
    def __init__(self, sid=50):
        self.id, self.envois, self.supprimes, self.edites = sid, [], [], []
        self._n = 1000

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def send(self, content=None, **kw):
        self._n += 1
        m = Obj(id=self._n, jump_url=f"https://discord.com/channels/1/{self.id}/{self._n}")
        self.envois.append((content, kw, m.id))
        return m

    def get_partial_message(self, mid):
        return Partiel(self, mid)

    async def fetch_message(self, mid):
        if mid in self.supprimes or not any(e[2] == mid for e in self.envois):
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return Obj(id=mid)


class Guilde:
    def __init__(self, salon=None, peut=True):
        self.id, self.salon, self.crees = 1, salon, []
        self.default_role = Obj(id=1)
        self.me = Obj(guild_permissions=perms(salons=peut))

    def get_channel(self, cid):
        return self.salon if self.salon is not None and self.salon.id == cid else None

    async def create_text_channel(self, nom, **kw):
        self.salon = Salon(77)
        self.crees.append((nom, kw))
        return self.salon


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
        self.guild_permissions = perms(staff)
        self._exclu = exclu

    def is_timed_out(self):
        return self._exclu


def interaction(g, membre):
    suivis = []

    async def suivi(content=None, **kw):
        suivis.append(content)
    return Obj(guild=g, user=membre, response=Reponse(), followup=Obj(send=suivi), suivis=suivis)


@pytest.fixture
def conf(tmp_path):
    chemin = tmp_path / "s.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    c = {}

    async def cfg(_gid):
        return c

    async def db_set(_gid, k, v):
        c[k] = v

    async def texte_refuse(_g, t):
        return "mot interdit" if "interdit" in t else ""

    async def controle(_m, _c):
        return ""
    S._verrous.clear()
    S._rappels.clear()
    S.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse,
            controle=controle, log=lambda *a: None)
    asyncio.run(S.init_db())
    return c


def test_S1_reponses_une_par_ligne_puces_et_doublons_retires():
    assert S.lire_reponses("1. Oui\n- Non\n\n  oui \n• Peut-être\n2) Jamais") == [
        "Oui", "Non", "Peut-être", "Jamais"]


def test_S2_limites_de_discord():
    assert S.verifier("", ["a", "b"]) == "Écris une question."
    assert "300" in S.verifier("q" * 301, ["a", "b"])
    assert "2 réponses" in S.verifier("Q ?", ["a"])
    assert "10" in S.verifier("Q ?", [str(i) for i in range(11)])
    assert "55" in S.verifier("Q ?", ["a", "x" * 56])
    assert S.verifier("Q ?", ["a", "b"]) == ""


def test_S3_panneau_epure_et_ferme_quand_il_le_faut():
    ouvert = S.vue_panneau(True).to_components()[0]["components"][0]
    assert [t["content"] for t in ouvert["components"]] == [
        "# 📊 Sondages", "Pose ta question, la communauté vote."]
    assert ouvert["accessory"]["custom_id"] == "sdg:creer" and not ouvert["accessory"]["disabled"]
    assert S.vue_panneau(False).to_components()[0]["components"][0]["accessory"]["disabled"]


def test_S4_un_vrai_sondage_discord_publie_au_nom_du_membre(conf):
    salon = Salon()
    g = Guilde(salon)
    conf.update(sondages_salon=salon.id)

    async def scenario():
        i = interaction(g, Membre())
        await S.publier(i, "Quel mode ?", "Solo\nDuo\nÉquipe", 72, True)
        await asyncio.sleep(0.05)
        return i
    i = asyncio.run(scenario())
    contenu, kw, _ = salon.envois[0]
    sondage = kw["poll"]
    assert contenu == "Sondage de <@7>" and kw["allowed_mentions"].users is False
    assert [a.text for a in sondage.answers] == ["Solo", "Duo", "Équipe"]
    assert sondage.duration == timedelta(hours=72) and sondage.multiple is True
    assert kw["view"].children[0].custom_id == "sdg:fin:7"
    assert i.suivis and i.suivis[0].startswith("✅ Sondage publié")
    assert conf["sondages_panneau"], "le bouton revient en bas du salon"


def test_S5_un_texte_refuse_se_corrige_sans_tout_retaper(conf):
    salon = Salon()
    conf.update(sondages_salon=salon.id)
    i = interaction(Guilde(salon), Membre())
    asyncio.run(S.publier(i, "Question interdit ?", "a\nb", 24, False))
    assert salon.envois == []
    vue = i.response.messages[0][1]["view"]
    composants = vue.to_components()[0]["components"]
    assert composants[0]["content"] == "⚠️ mot interdit"
    assert composants[1]["components"][0]["label"] == "Corriger"


def test_S6_un_en_cours_et_trois_par_jour_sauf_le_staff(conf):
    salon = Salon()
    g = Guilde(salon)
    conf.update(sondages_salon=salon.id)

    async def scenario():
        refus = []
        for _ in range(2):
            i = interaction(g, Membre())
            await S.publier(i, "Q ?", "a\nb", 1, False)
            refus.append(i.response.messages)
        async with S._get_db() as db:
            await db.execute("UPDATE sondages SET termine=1")
            await db.commit()
        for _ in range(3):
            i = interaction(g, Membre())
            await S.publier(i, "Q ?", "a\nb", 1, False)
            async with S._get_db() as db:
                await db.execute("UPDATE sondages SET termine=1")
                await db.commit()
            refus.append(i.response.messages)
        staff = interaction(g, Membre(uid=9, staff=True))
        for _ in range(4):
            await S.publier(staff, "Q ?", "a\nb", 1, False)
        await asyncio.sleep(0.05)
        return refus
    refus = asyncio.run(scenario())
    assert refus[0] == [] and "déjà un sondage en cours" in refus[1][0][0]
    assert refus[2] == [] and refus[3] == [] and "3 sondages par jour" in refus[4][0][0]
    assert sum(1 for e in salon.envois if e[1].get("poll")) == 3 + 4


def test_S7_terminer_reserve_a_l_auteur_et_au_staff(conf):
    fins, edits = [], []

    class Message:
        id = 555

        async def end_poll(self):
            fins.append(1)
            if len(fins) > 1:
                raise discord.HTTPException(Obj(status=400, reason="x"), "déjà fini")

        async def edit(self, **kw):
            edits.append(kw)

    b = S.BoutonTerminer(7)

    async def clic(membre):
        i = interaction(Guilde(), membre)
        i.message = Message()
        await b.callback(i)
        return i
    autre = asyncio.run(clic(Membre(uid=8)))
    assert "Seul l'auteur" in autre.response.messages[0][0] and not fins
    auteur = asyncio.run(clic(Membre(uid=7)))
    assert fins == [1] and edits == [{"view": None}] and auteur.suivis == ["⏹️ Sondage terminé."]
    staff = asyncio.run(clic(Membre(uid=9, staff=True)))
    assert staff.suivis == ["⏹️ Sondage terminé."], "déjà fini : le bouton part quand même"


def test_S8_fin_naturelle_et_salon_reserve_aux_sondages(conf):
    salon = Salon()
    g = Guilde(salon)
    conf.update(sondages_salon=salon.id)

    class Msg:
        def __init__(self, auteur, type_=discord.MessageType.default, ref=None):
            self.guild, self.channel, self.author, self.type = g, salon, auteur, type_
            self.reference, self.webhook_id, self.supprime = ref, None, False

        async def delete(self):
            self.supprime = True

    async def scenario():
        await S.sur_message(Msg(Obj(bot=True), discord.MessageType.poll_result,
                                Obj(message_id=1234)))
        humain = Msg(Membre())
        await S.sur_message(humain)
        await S.sur_message(Msg(Membre()))
        staff = Msg(Membre(uid=9, staff=True))
        await S.sur_message(staff)
        return humain, staff
    humain, staff = asyncio.run(scenario())
    assert (1234, {"view": None}) in salon.edites
    assert conf["sondages_panneau"], "le panneau revient en bas après le résultat"
    assert humain.supprime and not staff.supprime
    rappels = [e for e in salon.envois if e[0] and "bouton en bas" in e[0]]
    assert len(rappels) == 1 and rappels[0][1]["delete_after"] == 10, "un rappel, pas un spam"


def test_S9_le_salon_est_cree_une_fois_puis_il_appartient_au_proprietaire(conf):
    g = Guilde()
    asyncio.run(S.installer(g))
    nom, kw = g.crees[0]
    tous = kw["overwrites"][g.default_role]
    assert nom == "📊・sondages" and tous.send_messages is False and tous.send_polls is False
    assert conf["sondages_salon"] == 77 and conf["sondages_panneau"]
    conf["sondages_salon"] = 0                      # le propriétaire l'a supprimé
    asyncio.run(S.installer(g))
    assert len(g.crees) == 1, "jamais recréé d'office"


def test_S10_branchements_et_ancien_systeme_parti():
    assert "bot.add_dynamic_items(sondages.BoutonCreer, sondages.BoutonTerminer)" in SRC
    assert 'bot.add_listener(sondages.sur_message, "on_message")' in SRC
    assert "await sondages.installer(g)" in SRC and "await sondages.assurer_panneau(g)" in SRC
    assert "'sondages':    lambda: sondages.SondagesPanelV2(self.u, self.g)," in SRC
    for ancien in ("PollVoteView", "poll_closer", "restore_active_polls", "_refresh_poll_message"):
        assert ancien not in SRC, ancien


def test_S11_les_filtres_du_serveur_s_appliquent_au_texte():
    import ast
    import re

    import insult_filter
    import mots_interdits
    import offtopic_filter
    insult_filter._load()
    offtopic_filter._load()
    arbre = ast.parse(SRC)
    morceaux = [ast.unparse(n) for n in arbre.body
                if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_LIEN_OU_MENTION")
                or (isinstance(n, ast.AsyncFunctionDef) and n.name == "_texte_sondage_refuse")]
    conf = {"anti_badwords": True, "badwords_list": ["ananas"]}

    async def cfg(_g):
        return conf
    ns = {"re": re, "cfg": cfg, "insult_filter": insult_filter, "offtopic_filter": offtopic_filter,
          "_normalize_for_scan": lambda t: t,
          "check_badwords": lambda t, mots, whitelist=None: mots_interdits.cherche(t, mots, whitelist)}
    for m in morceaux:
        exec(m, ns)  # noqa: S102 — code du dépôt
    f = ns["_texte_sondage_refuse"]
    g = Obj(id=1)
    assert "lien" in asyncio.run(f(g, "Rejoins discord.gg/abcd ?"))
    assert "mention" in asyncio.run(f(g, "Qui gagne <@123> ?"))
    assert "mot interdit" in asyncio.run(f(g, "Tu aimes l'ananas ?"))
    assert "insulte" in asyncio.run(f(g, "Qui est le plus connard ?"))
    assert "Politique" in asyncio.run(f(g, "Le Pen ou pas ?"))
    assert asyncio.run(f(g, "Quel mode de jeu préférez-vous ?")) == ""
