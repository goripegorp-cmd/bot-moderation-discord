"""19/10/2026 : tickets fermés après 7 jours sans message (même fermeture que le bouton 🔒) ;
« les salons de combat temporaires, tu les enlèves »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord
import pytest

import tickets_fils

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _flocon(jours):
    return discord.utils.time_snowflake(datetime.now(timezone.utc) - timedelta(days=jours))


@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "t.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id, channel_id, "
                             "user_id, claimed_by, answers, panel_id, status)")
            for tid, chid in ((1, 101), (2, 102), (3, 103)):
                await db.execute("INSERT INTO tickets VALUES (?,1,?,7,0,?,'p1','open')",
                                 (tid, chid, json.dumps({"Sujet": "x"})))
            await db.commit()
    asyncio.run(preparer())
    return get_db


async def _statuts(get_db):
    async with get_db() as db:
        async with db.execute("SELECT id, status FROM tickets ORDER BY id") as c:
            return await c.fetchall()


def test_I1_seul_le_ticket_muet_depuis_7_jours_est_ferme(base):
    vieux = Obj(id=101, last_message_id=_flocon(9))
    recent = Obj(id=102, last_message_id=_flocon(2))
    g = Obj(id=1, me=Obj(id=2))
    salons = {101: vieux, 102: recent}
    fermes, conf = [], {"tickets_inactivite_jours": 7}

    async def salon(_g, chid):
        return salons.get(chid)

    async def fermer(guild, ch, tk, closer, reason, inactif_jours=0):
        fermes.append((ch.id, tk["id"], tk["answers"], closer.id, inactif_jours))

    async def cfg(_g):
        return conf

    async def dormir(_s):
        return None

    ns = {"bot": Obj(guilds=[g]), "cfg": cfg, "get_db": base, "json": json, "discord": discord,
          "tickets_fils": Obj(salon=salon), "_fermer_ticket": fermer, "_logerr": print,
          "now": lambda: datetime.now(timezone.utc), "asyncio": Obj(sleep=dormir),
          "tasks": Obj(loop=lambda **k: (lambda f: f))}
    exec(_source("tickets_inactifs_task"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["tickets_inactifs_task"]())
    assert fermes == [(101, 1, {"Sujet": "x"}, 2, 7)]
    assert asyncio.run(_statuts(base)) == [(1, "open"), (2, "open"), (3, "closed")], \
        "le salon 103 n'existe plus : fermé en base, sans rien envoyer"
    conf["tickets_inactivite_jours"] = 0
    fermes.clear()
    asyncio.run(ns["tickets_inactifs_task"]())
    assert fermes == [], "0 = jamais"


def test_I2_la_fermeture_partagee_log_mp_base_puis_suppression(base):
    journal = []

    class Salon:
        id = 101

        async def send(self, texte):
            journal.append(("annonce", texte))

        async def delete(self):
            journal.append(("supprime",))

    class Createur:
        async def send(self, **kw):
            journal.append(("mp", kw.get("content", ""), "view" in kw))

    async def log(*a, **k):
        journal.append(("log",))

    async def transcript(*_a):
        return "fichier"

    async def audit(*a):
        journal.append(("audit", a[3]))

    async def dormir(_s):
        return None

    g = Obj(id=1, name="GoRP", get_member=lambda _u: Createur())
    ns = {"send_ticket_log": log, "_recent_transcript_urls": {}, "_ticket_transcript_html": transcript,
          "_ticket_transcript_file": transcript, "_ticket_feedback_view": lambda *a: "notes",
          "get_db": base, "tix_module": Obj(log_action=audit), "asyncio": Obj(sleep=dormir),
          "discord": discord, "_logerr": lambda *a, **k: journal.append(("ERREUR", a))}
    exec(_source("_fermer_ticket"), ns)  # noqa: S102 — code du dépôt
    tk = {"id": 1, "user": 7}
    asyncio.run(ns["_fermer_ticket"](g, Salon(), tk, Obj(id=2, mention="@bot", display_name="Bot"),
                                     "7 jours sans message", inactif_jours=7))
    #  19/10 : « ils n'ont pas à le savoir » — un nettoyage : ni MP, ni annonce.
    assert [e[0] for e in journal] == ["log", "audit", "supprime"], journal
    assert asyncio.run(_statuts(base))[0] == (1, "closed")
    journal.clear()
    asyncio.run(ns["_fermer_ticket"](g, Salon(), tk, Obj(id=2, mention="@staff", display_name="Staff"),
                                     "Résolu"))
    assert [e[0] for e in journal] == ["log", "mp", "audit", "annonce", "supprime"], journal
    assert journal[1][2] is True, "la note de satisfaction après une vraie prise en charge"


def test_I3_branchements():
    assert "await _fermer_ticket(i.guild, i.channel, self.tk, i.user, reason)" in SRC
    assert '"tickets_inactifs_task",' in SRC and "tickets_inactifs_task.start()" in SRC
    assert "'tickets_inactivite_jours': 7" in SRC


# ═══ Combat ═══════════════════════════════════════════════════════════════════

def test_K1_les_salons_de_combat_sont_retires_et_pas_le_reste():
    supprimes, ecrits = [], {}

    class Salon:
        def __init__(self, cid, nom):
            self.id, self.name = cid, nom

        async def delete(self, reason=None):
            supprimes.append(self.name)

    class Categorie(discord.CategoryChannel):
        def __init__(self, cid, enfants):
            self.id, self._enfants = cid, enfants

        @property
        def channels(self):
            return self._enfants

        async def delete(self, reason=None):
            supprimes.append("CATÉGORIE")

    cat = Categorie(900, [])
    salons = [Salon(1, "🐗-mob"), Salon(2, "⚔️-arène"), Salon(3, "🔊 Combat 2"),
              Salon(4, "anciennom"), Salon(5, "général"), Salon(6, "🎁-tresor"), cat]
    conf = {"combat_channel_id": 4, "combat_channel_id_misc": 0, "events_category": 900}

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v

    async def dormir(_s):
        return None

    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "asyncio": Obj(sleep=dormir),
          "_ALL_COMBAT_CHANNEL_NAMES": frozenset({"🐗-mob", "🎁-tresor", "⚔️-combat"}),
          "_LEGACY_COMBAT_CHANNEL_NAMES": frozenset({"📢-mob"}),
          "_logerr": lambda *a, **k: supprimes.append(("ERREUR", a))}
    exec(_source("_retirer_salons_combat"), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1, channels=salons, get_channel=lambda cid: cat if cid == 900 else None)
    asyncio.run(ns["_retirer_salons_combat"](g))
    assert supprimes == ["🐗-mob", "⚔️-arène", "🔊 Combat 2", "anciennom", "🎁-tresor", "CATÉGORIE"]
    assert ecrits == {"combat_channel_id": 0}


def test_K2_appele_au_demarrage():
    assert '"_retirer_salons_combat"' in SRC.split("_TRAVAUX = (")[1].split(")")[0]
    assert "_ensure_combat_channel(" not in SRC.replace("async def _ensure_combat_channel(", ""), \
        "plus rien ne crée de salon de combat"
