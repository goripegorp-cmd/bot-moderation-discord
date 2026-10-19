"""19/10/2026 : « un onglet Questions : les questions posées dans le serveur, restées sans réponse »."""
from __future__ import annotations

import asyncio
import contextlib

import aiosqlite

import questions as Q
from conftest_discord import Obj

STAFF = {2}


def _base(tmp_path):
    chemin = tmp_path / "q.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    Q.setup(get_db=get_db, est_staff=lambda g, m, c: m.id in STAFF, log=lambda *a: None)
    asyncio.run(Q.init_db())
    return get_db


def _salon(sid, public=True):
    return Obj(id=sid, guild=None, is_nsfw=lambda: False,
               permissions_for=lambda r: Obj(view_channel=public, send_messages=public, send_messages_in_threads=public))


def _membre(uid):
    return Obj(id=uid, bot=False, roles=[], display_name=f"M{uid}")


class Fabrique:
    def __init__(self):
        self.g = Obj(id=1, default_role=Obj(id=1))
        self.n = 100

    def msg(self, auteur, texte, salon, reference=None, cible=None, mentions=()):
        self.n += 1
        salon.guild = self.g
        ref = Obj(message_id=reference, resolved=Obj(author=cible) if cible else None) if reference else None
        return Obj(id=self.n, guild=self.g, author=auteur, channel=salon, content=texte, reference=ref,
                   raw_mentions=[m.id for m in mentions], mentions=list(mentions), webhook_id=None,
                   jump_url=f"https://discord.com/channels/1/{salon.id}/{self.n}")


def test_Q1_une_vraie_question_pas_du_bavardage():
    oui = ["Comment on rejoint le clan Rell Seas ?", "quand est le prochain event du clan", "How do I join the crew?",
           "Quelqu'un sait pourquoi le lien d'invitation marche plus ?", "Est-ce qu'on peut changer de pseudo"]
    non = ["ça va ?", "mdr t'es où ?", "ok", "?", "/rang", "tu fais quoi ce soir ?", "salut tout le monde",
           "!help moi stp ?", "qui joue avec moi ce soir ?", "hello ?"]
    assert all(Q.est_question(t) for t in oui), [t for t in oui if not Q.est_question(t)]
    assert not any(Q.est_question(t) for t in non), [t for t in non if Q.est_question(t)]
    assert Q.nettoyer("<@123> **Comment** on fait ? https://x.y/z") == "Comment on fait ?"


def test_Q2_releve_et_fermeture_automatique(tmp_path):
    _base(tmp_path)
    f = Fabrique()
    aide, prive = _salon(10), _salon(11, public=False)
    kolax, mira, zed, staff = _membre(7), _membre(8), _membre(9), _membre(2)
    t0 = 2_000_000_000

    async def scenario():
        r = []
        q1 = f.msg(kolax, "Comment on rejoint le clan Rell Seas ?", aide)
        r.append(await Q.sur_message(q1, {}, t0))
        r.append(await Q.sur_message(f.msg(kolax, "Il faut un niveau minimum ?", aide), {}, t0 + 60))
        r.append(await Q.sur_message(f.msg(mira, "Tu ouvres un ticket dans #ticket", aide, reference=q1.id, cible=kolax), {}, t0 + 120))
        r.append(await Q.sur_message(f.msg(mira, "Pourquoi le lien d'invitation marche plus ?", aide), {}, t0 + 2000))
        r.append(await Q.sur_message(f.msg(staff, "Le lien a été changé, regarde l'annonce", aide), {}, t0 + 2300))
        r.append(await Q.sur_message(f.msg(zed, "Comment je fais pour avoir le rôle ?", aide), {}, t0 + 9000))
        r.append(await Q.sur_message(f.msg(zed, "c'est bon trouvé merci", aide), {}, t0 + 9600))
        r.append(await Q.sur_message(f.msg(zed, "ça va ?", aide), {}, t0 + 9700))
        r.append(await Q.sur_message(f.msg(zed, "Comment tu fais ça ?", aide, reference=999, cible=mira), {}, t0 + 9800))
        r.append(await Q.sur_message(f.msg(zed, "Comment tu as eu ce skin, dis moi ?", aide, mentions=[mira]), {}, t0 + 9900))
        r.append(await Q.sur_message(f.msg(zed, "Comment on rejoint le clan Rell Seas ?", prive), {}, t0 + 9950))
        r.append(await Q.sur_message(f.msg(staff, "Comment ça se passe pour vous ?", aide), {}, t0 + 9990))
        return r, await Q.lister(1, t0 + 10000)
    r, liste = asyncio.run(scenario())
    assert r == ["question", "fusion", "reponse", "question", "reponse", "question", None, None, None, None, None, None]
    q = {x["auteur_id"]: x for x in liste["liste"]}
    assert set(q) == {7, 8, 9}, "pas de bavardage, pas de salon privé, pas de question du staff"
    assert q[7]["statut"] == "repondue" and q[7]["par_staff"] == 0 and q[7]["repondu_par"] == 8, "un membre a répondu"
    assert q[7]["texte"] == "Comment on rejoint le clan Rell Seas ? · Il faut un niveau minimum ?", "deux questions d'affilée = une"
    assert q[8]["statut"] == "repondue" and q[8]["par_staff"] == 1 and q[8]["repondu_le"] - q[8]["quand"] == 300
    assert q[9]["statut"] == "resolue", "l'auteur a dit que c'était bon"
    assert q[7]["message"] == "https://discord.com/channels/1/10/101"
    st = liste["stats"]
    assert (st["ouvertes"], st["repondues_7"], st["delai_median"]) == (0, 3, 300) and st["salons"] == [(10, 3)]


def test_Q3_fil_ouvert_sur_la_question_et_gestes_du_site(tmp_path):
    _base(tmp_path)
    import discord
    f = Fabrique()
    aide = _salon(10)
    kolax, staff = _membre(7), _membre(2)
    t0 = 2_000_000_000

    class Fil(discord.Thread):
        def __init__(self, tid, parent):
            self.id, self.parent_id, self._parent, self.guild = tid, parent.id, parent, None

        @property
        def parent(self):
            return self._parent

        def is_private(self):
            return False

    async def scenario():
        q1 = f.msg(kolax, "Comment on rejoint le clan Rell Seas ?", aide)
        await Q.sur_message(q1, {}, t0)
        q2 = f.msg(kolax, "Pourquoi mon ticket est fermé ?", aide)
        await Q.sur_message(q2, {}, t0 + 4000)
        reponse = await Q.sur_message(f.msg(staff, "Je te réponds ici", Fil(q2.id, aide)), {}, t0 + 5000)
        l1 = await Q.lister(1, t0 + 6000)
        q1_id = next(x["id"] for x in l1["liste"] if x["message_id"] == q1.id)
        ok = await Q.marquer(1, q1_id, "ignoree", 2, t0 + 6100)
        faux = await Q.marquer(1, q1_id, "supprimee", 2)
        return reponse, ok, faux, await Q.du_membre(1, 7)
    reponse, ok, faux, siennes = asyncio.run(scenario())
    assert reponse == "reponse", "un fil ouvert sur la question, le staff y répond : répondue"
    assert ok and not faux
    assert sorted(x["statut"] for x in siennes) == ["ignoree", "repondue"]
    assert Q.PURGES[0][1].startswith("DELETE FROM questions WHERE quand <")
