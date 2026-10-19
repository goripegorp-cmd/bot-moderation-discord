"""19/10/2026 (soir) : « refais-le avec le système de sondage par défaut de Discord, qui était bien
mieux. Pas le nouveau système… ça envoie trop de messages débiles… et qui s'affiche au propre, même
sur le panel. Comme ça, on peut décider si on l'enlève du salon ou non »."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
import pytest

import registre
import sondages as S
from conftest_discord import Guilde, Membre, Obj, base, laisser_finir

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


class Reponse:
    def __init__(self, texte, n=0, emoji=None):
        self.text, self.vote_count, self.emoji = texte, n, emoji


class Sondage:
    def __init__(self, question, choix, heures=24, multiple=False, fini=False):
        self.question, self.multiple, self._fini = question, multiple, fini
        self.answers = [Reponse(c) if isinstance(c, str) else Reponse(*c) for c in choix]
        self.expires_at = datetime.now(timezone.utc) + timedelta(hours=heures)
        self.duration = timedelta(hours=heures)

    def is_finalized(self):
        return self._fini


class Salon(discord.TextChannel):
    def __init__(self, sid, nom):
        self.id, self.name, self.messages, self.dits, self.supprimes, self.droits = sid, nom, {}, [], [], {}
        self.edites = []

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def send(self, content=None, **kw):
        self.dits.append((content, kw))

    async def fetch_message(self, mid):
        if mid not in self.messages:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return self.messages[mid]

    def get_partial_message(self, mid):
        salon = self

        class Partiel:
            async def delete(self):
                salon.supprimes.append(mid)
                salon.messages.pop(mid, None)

            async def edit(self, **kw):
                salon.edites.append((mid, kw))
        return Partiel()

    def overwrites_for(self, cible):
        return discord.PermissionOverwrite(**self.droits.get(cible, {"view_channel": False}))

    async def set_permissions(self, cible, overwrite=None, reason=None):
        self.droits[cible] = {k: v for k, v in overwrite if v is not None}


class Msg:
    def __init__(self, salon, mid, auteur, poll=None, texte="", type_=discord.MessageType.default, ref=None):
        self.channel, self.id, self.author, self.poll, self.content = salon, mid, auteur, poll, texte
        self.guild, self.type, self.webhook_id = salon.guild, type_, None
        self.reference = Obj(message_id=ref) if ref else None
        self.created_at = datetime.now(timezone.utc)
        salon.messages[mid] = self

    def is_system(self):
        return self.type != discord.MessageType.default

    async def delete(self):
        self.channel.supprimes.append(self.id)
        self.channel.messages.pop(self.id, None)


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    salon, chat = Salon(50, "📊sondages"), Salon(51, "chat")
    g = Guilde(salon, chat)
    salon.guild = chat.guild = g
    g.get_thread = lambda _i: None

    async def texte_refuse(_g, t):
        return "Ton sondage contient un mot interdit sur le serveur." if "interdit" in t else ""

    async def controle(_m, _c):
        return ""
    S._rappels.clear()
    S._a_rafraichir.clear()
    S.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse, controle=controle, log=lambda *a: None)
    registre.setup(get_db=get_db, log=lambda *a: None)
    registre._derniers.clear()
    asyncio.run(S.init_db())
    asyncio.run(registre.init_db())
    conf["sondages_salon"] = salon.id
    S._bot = Obj(get_guild=lambda gid: g)
    return Obj(g=g, salon=salon, chat=chat, conf=conf, get_db=get_db)


def run(coro):
    async def _avec_taches():
        r = await coro
        await laisser_finir(8)
        return r
    return asyncio.run(_avec_taches())


def journal(types=None):
    return [e for e in asyncio.run(registre.lire(1)) if types is None or e["type"] in types]


def test_S1_un_sondage_discord_se_lit_tel_quel():
    m = Obj(poll=Sondage("Quelle map ?", [("Port", 3, "⚓"), "Forêt"], heures=4, multiple=True),
            created_at=datetime.now(timezone.utc))
    s = S.lire_sondage(m)
    assert s["question"] == "Quelle map ?" and s["choix"] == ["⚓ Port", "Forêt"] and s["comptes"] == [3, 0]
    assert s["multiple"] and not s["termine"] and s["fin"] > datetime.now(timezone.utc)


def test_S2_le_sondage_d_un_membre_est_suivi_sans_un_mot_du_bot(env):
    run(S.sur_message(Msg(env.salon, 1001, Membre(7), Sondage("On fait un event ?", ["Oui", "Non"]))))
    d = asyncio.run(S.lister(1))
    assert [x["question"] for x in d["liste"]] == ["On fait un event ?"] and d["liste"][0]["statut"] == "en_cours"
    assert d["liste"][0]["choix"] == ["Oui", "Non"] and d["stats"]["en_cours"] == 1
    assert not env.salon.dits and not env.salon.supprimes, "le bot n'écrit rien dans le salon"
    assert [e["type"] for e in journal()] == ["sondage.publie"]


def test_S3_un_sondage_qui_enfreint_les_regles_est_retire_raison_dite(env):
    run(S.sur_message(Msg(env.chat, 1002, Membre(7), Sondage("Mot interdit ?", ["a", "b"]))))
    assert env.chat.supprimes == [1002] and not asyncio.run(S.lister(1))["liste"]
    texte, kw = env.chat.dits[0]
    assert "Sondage retiré : ton sondage contient un mot interdit" in texte and kw["delete_after"] == 12
    assert [e["type"] for e in journal()] == ["sondage.refuse"]


def test_S4_un_en_cours_trois_par_jour_staff_libre(env):
    run(S.sur_message(Msg(env.salon, 2001, Membre(7), Sondage("Un ?", ["a", "b"]))))
    run(S.sur_message(Msg(env.salon, 2002, Membre(7), Sondage("Deux ?", ["a", "b"]))))
    assert env.salon.supprimes == [2002] and "déjà un sondage en cours" in env.salon.dits[0][0]
    asyncio.run(S._marquer(1, termine=1))
    for k in (2003, 2004):
        run(S.sur_message(Msg(env.salon, k, Membre(7), Sondage(f"Q{k} ?", ["a", "b"]))))
        asyncio.run(S._marquer(len(asyncio.run(S.lister(1))["liste"]), termine=1))
    run(S.sur_message(Msg(env.salon, 2005, Membre(7), Sondage("Quatre ?", ["a", "b"]))))
    assert 2005 in env.salon.supprimes and "3 sondages par jour" in env.salon.dits[-1][0]
    for k in range(3000, 3005):
        run(S.sur_message(Msg(env.salon, k, Membre(8, staff=True), Sondage(f"Staff {k} ?", ["a", "b"]))))
    assert not any(k in env.salon.supprimes for k in range(3000, 3005)), "le staff est libre"


def test_S5_dans_le_salon_un_message_qui_n_est_pas_un_sondage_part_rappel_rare(env):
    run(S.sur_message(Msg(env.salon, 4001, Membre(7), texte="salut")))
    run(S.sur_message(Msg(env.salon, 4002, Membre(7), texte="re")))
    run(S.sur_message(Msg(env.salon, 4003, Membre(9, staff=True), texte="Rappel du staff")))
    run(S.sur_message(Msg(env.chat, 4004, Membre(7), texte="bonjour")))
    assert env.salon.supprimes == [4001, 4002] and not env.chat.supprimes
    assert len(env.salon.dits) == 1 and "bouton ➕" in env.salon.dits[0][0], "un seul rappel par heure"
    assert env.salon.dits[0][1]["delete_after"] == 10


def test_S6_votes_suivis_en_direct_puis_resultat_au_journal(env, monkeypatch):
    monkeypatch.setattr(S, "ATTENTE_VOTES", 0.01)
    sondage = Sondage("Quelle heure ?", ["20 h", "21 h"])
    msg = Msg(env.salon, 5001, Membre(7), sondage)
    run(S.sur_message(msg))
    sondage.answers[0].vote_count, sondage.answers[1].vote_count = 4, 1
    run(S.sur_vote(Obj(guild_id=1, message_id=5001)))
    x = asyncio.run(S.lister(1))["liste"][0]
    assert x["comptes"] == [4, 1] and x["total"] == 5 and x["statut"] == "en_cours"
    sondage._fini = True
    run(S.sur_message(Msg(env.salon, 5002, Obj(id=7, bot=False), type_=discord.MessageType.poll_result, ref=5001)))
    x = asyncio.run(S.lister(1))["liste"][0]
    assert x["statut"] == "termine" and not env.salon.dits
    fin = journal({"sondage.fin"})
    assert len(fin) == 1 and "Gagnant : 20 h" in fin[0]["texte"] and "5 vote(s)" in fin[0]["texte"]


def test_S7_la_direction_retire_un_sondage_du_salon(env):
    run(S.sur_message(Msg(env.salon, 6001, Membre(7), Sondage("À retirer ?", ["a", "b"]))))
    chef = Obj(id=3, display_name="Chef")
    ok, message = asyncio.run(S.retirer(env.g, 1, chef))
    assert ok and env.salon.supprimes == [6001] and message == "Sondage retiré du salon."
    x = asyncio.run(S.lister(1))["liste"][0]
    assert x["statut"] == "retire" and x["retire_par"] == "3" and x["comptes"] == [0, 0], "le résultat reste"
    assert asyncio.run(S.retirer(env.g, 1, chef)) == (False, "Ce sondage est déjà retiré du salon.")
    assert journal({"sondage.retire"})[0]["auteur_id"] == 3


def test_S8_supprime_sur_discord_il_est_marque_retire(env):
    run(S.sur_message(Msg(env.salon, 7001, Membre(7), Sondage("Q ?", ["a", "b"]))))
    run(S.sur_suppression(Obj(guild_id=1, message_id=7001)))
    assert asyncio.run(S.lister(1))["liste"][0]["statut"] == "retire"


def test_S9_passage_unique_aux_sondages_discord(env):
    async def preparer():
        async with env.get_db() as db:
            await db.execute("INSERT INTO sondages(message_id, guild_id, channel_id, auteur_id, question, choix, anonyme,"
                             " cree_le, fin_le) VALUES (900, 1, 50, 7, 'Ancien anonyme ?', '[\"Oui\", \"Non\"]', 1,"
                             " '2026-10-19 10:00:00', '2026-10-25 10:00:00')")
            await db.execute("CREATE TABLE sondages_votes (sondage_id INTEGER, votant TEXT, choix INTEGER)")
            await db.executemany("INSERT INTO sondages_votes VALUES (1, ?, ?)", [("a", 0), ("b", 0), ("c", 1)])
            await db.commit()
        await S.init_db()
    asyncio.run(preparer())
    role = Obj(id=950, managed=False, supprime=False)

    async def suppr(reason=None):
        role.supprime = True
    role.delete = suppr
    env.g.roles[950] = role
    env.conf.update(sondages_installes=1, sondages_panneau=880, notif_role_sondages=950)
    env.salon.droits[env.g.default_role] = {"view_channel": True, "send_messages": False, "send_polls": False}
    run(S.installer(env.g))
    assert env.salon.supprimes == [880], "l'ancien panneau du bot part"
    assert role.supprime and env.conf["notif_role_sondages"] == 0 and env.conf["sondages_natifs_v2"]
    droits = env.salon.droits[env.g.default_role]
    assert droits.get("read_messages", droits.get("view_channel")) is True, "la vue du salon ne change pas"
    assert droits["send_messages"] and droits["send_polls"] and droits["add_reactions"] is False
    (mid, kw), = env.salon.edites
    texte = " ".join(c.content for c in kw["view"].walk_children() if isinstance(c, discord.ui.TextDisplay))
    assert mid == 900 and "Ancien anonyme ?" in texte and "Gagnant : Oui" in texte, "le résultat reste visible"
    x = asyncio.run(S.lister(1))["liste"][0]
    assert x["comptes"] == [2, 1] and x["statut"] == "termine"
    edites = len(env.salon.edites)
    run(S.installer(env.g))
    assert len(env.salon.edites) == edites, "une seule fois"


def test_S10_branchements():
    assert 'bot.add_listener(sondages.sur_vote, "on_raw_poll_vote_add")' in SRC
    assert 'bot.add_listener(sondages.sur_vote, "on_raw_poll_vote_remove")' in SRC
    assert "sondages.BoutonCreer" not in SRC and "sondages.assurer_panneau" not in SRC
    assert '"sondage_retirer": _action_sondage_retirer' in SRC
    source = (RACINE / "sondages.py").read_text(encoding="utf-8")
    assert "salon.send(view=" not in source and "Poll(" not in source, "le bot ne publie plus de sondage"
    page = (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert '["sondages", "Sondages", "sondage"]' in page and 'action: "sondage_retirer"' in page
