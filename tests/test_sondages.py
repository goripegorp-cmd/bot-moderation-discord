"""19/10/2026 : « un sondage, c'est soit l'un, soit l'autre, ou alors jusqu'à quatre… avec un
vrai menu » ; « si un jour tu veux un vote anonyme, il faudra un sondage maison — ouais, tu
peux » ; « quand le sondage est terminé… un salon logs… un vrai suivi »."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import discord
import pytest

import notifs
import sondages as S
from conftest_discord import Guilde, Membre, Obj, Salon, base, interaction

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    salon, logs = Salon(50, "📊sondages"), Salon(60, "📊logs-sondages")
    g = Guilde(salon, logs)

    async def texte_refuse(_g, t):
        return "Mot interdit." if "interdit" in t else ""

    async def controle(_m, _c):
        return ""

    async def salon_logs(_g, cle, nom):
        assert (cle, nom) == ("sondages", "📊logs-sondages")
        return logs
    S._verrous.clear()
    S._rappels.clear()
    S.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse, controle=controle,
            salon_logs=salon_logs, cle_secrete="secret", log=lambda *a: None)
    notifs.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    asyncio.run(S.init_db())
    conf["sondages_salon"] = salon.id
    return Obj(g=g, salon=salon, logs=logs, conf=conf, get_db=get_db)


def run(coro):
    async def _avec_taches():
        r = await coro
        await asyncio.sleep(0.05)
        return r
    return asyncio.run(_avec_taches())


def test_S1_choix_remplis_sans_doublon():
    assert S.nettoyer_choix(["Oui", " non ", "", "oui", "Peut-être"]) == ["Oui", "non", "Peut-être"]


def test_S2_deux_a_quatre_choix_et_limites_de_discord():
    assert S.verifier("", ["a", "b"]) == "Écris une question."
    assert "300" in S.verifier("q" * 301, ["a", "b"])
    assert "deux choix" in S.verifier("Q ?", ["a"])
    assert "4 choix" in S.verifier("Q ?", ["a", "b", "c", "d", "e"])
    assert "55" in S.verifier("Q ?", ["a", "x" * 56])
    assert S.verifier("Q ?", ["a", "b"]) == ""


def test_S3_formulaire_une_question_et_quatre_champs_de_choix():
    f = S.Formulaire(72, True, "Q ?", ["A", "B"])
    champs = f.to_dict()["components"]
    assert [c["label"] for c in champs] == ["Question", "Choix 1", "Choix 2", "Choix 3", "Choix 4"]
    assert [c["component"]["required"] for c in champs] == [True, True, True, False, False]
    assert champs[1]["component"]["value"] == "A" and f.heures == 72 and f.anonyme is True


def test_S4_menu_duree_et_votes_puis_formulaire():
    m = S.MenuCreation(7)
    selects = [c for c in m.walk_children() if isinstance(c, discord.ui.Select)]
    assert [o.label for o in selects[1].options] == ["Votes visibles", "Votes anonymes"]

    async def rien():
        return None
    i = Obj(data={"values": ["168"]}, response=Obj(defer=rien))
    asyncio.run(m._duree(i))
    i.data = {"values": ["1"]}
    asyncio.run(m._votes(i))
    modals = []

    async def send_modal(x):
        modals.append(x)
    asyncio.run(m._ecrire(Obj(response=Obj(send_modal=send_modal))))
    assert modals[0].heures == 168 and modals[0].anonyme is True


def test_S5_vote_visible_un_vrai_sondage_discord_annonce_et_journalise(env):
    i = interaction(env.g, Membre())
    run(S.publier(i, "Quel mode ?", ["Solo", "Duo", "", ""], 72, False))
    contenu, kw, _ = env.salon.envois[0]
    assert contenu.endswith("Sondage de <@7>") and contenu.startswith("<@&")
    assert [a.text for a in kw["poll"].answers] == ["Solo", "Duo"]
    assert kw["poll"].duration == timedelta(hours=72) and kw["poll"].multiple is False
    assert kw["allowed_mentions"].roles and kw["view"].children[0].custom_id == "sdg:fin:7"
    assert i.suivis[0].startswith("Sondage publié")
    journal = env.logs.envois[0][1]["view"].to_components()[0]["components"][0]["content"]
    assert "Sondage en cours" in journal and "Quel mode ?" in journal and "<@7>" in journal
    assert env.conf["sondages_panneau"], "le panneau redescend"


def test_S6_vote_anonyme_personne_ne_sait_qui_a_vote_quoi(env):
    i = interaction(env.g, Membre())
    run(S.publier(i, "Pizza ?", ["Oui", "Non"], 1, True))
    vue = env.salon.envois[0][1]["view"]
    ids = [b["custom_id"] for r in vue.to_components()[0]["components"] if r.get("type") == 1
           for b in r["components"]]
    assert ids == ["sdgv:1:0", "sdgv:1:1", "sdgf:1"]

    async def votes():
        for uid, k in ((10, 0), (11, 0), (12, 1), (10, 1)):
            await S.BoutonVote(1, k).callback(interaction(env.g, Membre(uid), env.salon))
        async with env.get_db() as db:
            async with db.execute("SELECT votant, choix FROM sondages_votes") as cur:
                return await cur.fetchall()
    lignes = asyncio.run(votes())
    assert sorted(k for _, k in lignes) == [0, 1, 1], "un vote par membre, modifiable"
    assert all(len(v) == 32 for v, _ in lignes), "des empreintes, pas des identifiants"
    run(S.finaliser(Obj(get_guild=lambda gid: env.g), 1))
    final = env.salon.edites[-1][1]["view"].to_components()[0]["components"]
    textes = " ".join(c.get("content", "") for c in final)
    assert "Gagnant : **Non**" in textes and "terminé" in textes
    assert not any(c.get("type") == 1 for c in final), "plus de boutons de vote"
    journal = env.logs.edites[-1][1]["view"].to_components()[0]["components"]
    assert "Sondage terminé" in journal[0]["content"] and "Gagnant : **Non**" in journal[-1]["content"]


def test_S7_un_en_cours_trois_par_jour_staff_libre(env):
    async def scenario():
        refus = []
        for _ in range(2):
            i = interaction(env.g, Membre())
            await S.publier(i, "Q ?", ["a", "b"], 1, False)
            refus.append(i.response.messages)
        for _ in range(3):
            async with env.get_db() as db:
                await db.execute("UPDATE sondages SET termine=1")
                await db.commit()
            i = interaction(env.g, Membre())
            await S.publier(i, "Q ?", ["a", "b"], 1, False)
            refus.append(i.response.messages)
        for _ in range(4):
            await S.publier(interaction(env.g, Membre(9, staff=True)), "Q ?", ["a", "b"], 1, False)
        await asyncio.sleep(0.05)
        return refus
    refus = asyncio.run(scenario())
    assert refus[0] == [] and "déjà un sondage en cours" in refus[1][0][0]
    assert refus[2] == [] and refus[3] == [] and "3 sondages par jour" in refus[4][0][0]


def test_S8_un_texte_refuse_se_corrige_sans_tout_retaper(env):
    i = interaction(env.g, Membre())
    run(S.publier(i, "Question interdit ?", ["a", "b", "", ""], 24, True))
    assert env.salon.envois == []
    vue = i.response.messages[0][1]["view"]
    corriger = next(c for c in vue.walk_children() if isinstance(c, discord.ui.Button))
    clic = interaction(env.g, Membre())
    asyncio.run(corriger.callback(clic))
    f = clic.response.modals[0]
    assert f.q.default == "Question interdit ?" and f.anonyme is True and f.heures == 24


def test_S9_fin_naturelle_resultat_aux_logs_et_salon_reserve(env):
    run(S.publier(interaction(env.g, Membre()), "Q ?", ["A", "B"], 1, False))
    mid = env.salon.envois[0][2]
    sondage = Obj(answers=[Obj(vote_count=3), Obj(vote_count=5)])

    async def edit(**k):
        return None

    async def fetch(m):
        return Obj(id=m, poll=sondage, edit=edit)
    env.salon.fetch_message = fetch

    class Msg:
        def __init__(self, auteur, type_=discord.MessageType.default, ref=None):
            self.guild, self.channel, self.author, self.type = env.g, env.salon, auteur, type_
            self.reference, self.webhook_id, self.supprime = ref, None, False

        async def delete(self):
            self.supprime = True
    run(S.sur_message(Msg(Obj(bot=True), discord.MessageType.poll_result, Obj(message_id=mid))))
    journal = env.logs.edites[-1][1]["view"].to_components()[0]["components"]
    assert "Sondage terminé" in journal[0]["content"] and "Gagnant : **B**" in journal[-1]["content"]
    humain = Msg(Membre())
    run(S.sur_message(humain))
    assert humain.supprime


def test_S10_salon_cree_une_fois_et_renomme(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    S.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None,
            salon_logs=None, cle_secrete="x", log=lambda *a: None)
    g = Guilde()
    asyncio.run(S.installer(g))
    nom, kw = g.crees[0]
    assert nom == "📊sondages" and kw["overwrites"][g.default_role].send_messages is False
    conf["sondages_salon"] = 0
    asyncio.run(S.installer(g))
    assert len(g.crees) == 1, "jamais recréé d'office"
    ancien = Salon(80, "📊・sondages")
    g.salons[80] = ancien
    conf["sondages_salon"] = 80
    asyncio.run(S.installer(g))
    assert ancien.name == "📊sondages"


def test_S11_branchements():
    for attendu in ("sondages.BoutonVote", "sondages.BoutonFinAnonyme", "suggestions.BoutonProposer",
                    "notifs.BoutonNotif", "sondages.demarrer(bot)", "('sondages', 'cloture_task')",
                    "await suggestions.installer(g)", "salon_logs=_salon_logs_dedie"):
        assert attendu in SRC, attendu
