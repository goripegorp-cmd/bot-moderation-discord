"""19/10/2026 : « si quelqu'un n'a pas commis d'infraction depuis plus de 3 mois non-stop, tu enlèves
toutes les infractions… sauf s'il a vraiment été très agressif… les warns des joueurs partis depuis
plus de 3 mois… que ça s'enlève bien aussi sur le serveur Discord » — « enlever tous les
avertissements de quelqu'un d'un seul coup… nettoyer tous les avertissements du serveur d'un seul
coup… repartir de zéro… nettoyer une zone »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord

import casier
import registre
import tableau
from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
BOT = 999
JOUR = 86400


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise KeyError(nom)


def _date(jours):
    return (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%d %H:%M:%S")


class Base:
    def __init__(self, tmp_path):
        chemin = tmp_path / "c.db"

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(chemin)
            try:
                yield db
            finally:
                await db.close()
        self.get_db = get_db
        casier.setup(get_db=get_db, log=lambda *a: None)
        registre.setup(get_db=get_db, log=lambda *a: None)
        registre._derniers.clear()

        async def creer():
            async with get_db() as db:
                await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,"
                                 " mod_id INTEGER, type TEXT, reason TEXT, duration TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
                await db.execute("CREATE TABLE badword_strikes(guild_id INTEGER, user_id INTEGER, count INTEGER)")
                await db.execute("CREATE TABLE user_toxicity_scores(guild_id INTEGER, user_id INTEGER, score INTEGER)")
                await db.commit()
            await casier.init_db()
            await registre.init_db()
        asyncio.run(creer())

    def ajouter(self, uid, type_, jours, raison="", mod=2):
        async def f():
            async with self.get_db() as db:
                await db.execute("INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, created_at) VALUES (1,?,?,?,?,?)",
                                 (uid, mod, type_, raison, _date(jours)))
                await db.commit()
        asyncio.run(f())

    def casier_de(self, uid):
        async def f():
            async with self.get_db() as db:
                async with db.execute("SELECT type FROM infractions WHERE guild_id=1 AND user_id=? ORDER BY id", (uid,)) as cur:
                    return [r[0] for r in await cur.fetchall()]
        return asyncio.run(f())


def test_C1_tres_agressif():
    assert casier.tres_agressif([("warn", "spam"), ("mute", "flood")]) == ""
    assert casier.tres_agressif([("warn", "x"), ("ban", "raid")]) == "ban au casier"
    assert casier.tres_agressif([("menace", "")]) == "menace au casier"
    assert casier.tres_agressif([("warn", "Menace de mort en MP")]) == "fait grave au casier"
    assert casier.tres_agressif([("insulte", "")] * 2) == "" and casier.tres_agressif([("insulte", "")] * 3) == "insultes répétées"


def test_C2_amnistie_trois_mois(tmp_path):
    b = Base(tmp_path)
    b.ajouter(10, "warn", 120); b.ajouter(10, "mute", 100)            # calme depuis 100 j : effacé
    b.ajouter(11, "warn", 120); b.ajouter(11, "warn", 10)             # récent : gardé
    b.ajouter(12, "warn", 200); b.ajouter(12, "menace", 150)          # très agressif : gardé
    b.ajouter(13, "warn", 200); b.ajouter(13, "ban", 150)             # parti il y a 120 j, agressif : warns partent
    b.ajouter(14, "warn", 40)                                         # parti il y a 100 j, warn récent : part
    b.ajouter(15, "warn", 30)                                         # parti il y a 10 j : gardé
    maintenant = time.time()
    bilan = asyncio.run(casier.amnistie(1, {10, 11, 12}, {13: maintenant - 120 * JOUR, 14: maintenant - 100 * JOUR,
                                                         15: maintenant - 10 * JOUR}))
    assert b.casier_de(10) == [] and b.casier_de(11) == ["warn", "warn"] and b.casier_de(12) == ["warn", "menace"]
    assert b.casier_de(13) == ["ban"], "parti depuis 3 mois : ses avertissements partent, le bannissement reste"
    assert b.casier_de(14) == [] and b.casier_de(15) == ["warn"]
    assert bilan["membres"] == [10, 13, 14] and bilan["n"] == 4 and bilan["gardes"] == [(12, "menace au casier")]
    lots = asyncio.run(casier.lots(1))
    assert len(lots) == 1 and lots[0]["n"] == 4 and lots[0]["personnes"] == 3 and lots[0]["par"] == 0
    asyncio.run(casier.restaurer(1, bilan["lot"], 3))
    assert b.casier_de(10) == ["warn", "mute"], "l'amnistie se défait aussi"


def test_C3_nettoyer_une_zone_les_bans_restent(tmp_path):
    b = Base(tmp_path)
    b.ajouter(20, "warn", 5); b.ajouter(20, "warn", 50); b.ajouter(20, "ban", 50)
    b.ajouter(21, "insulte", 100, mod=BOT); b.ajouter(21, "mute", 2)
    c = asyncio.run(casier.comptes(1, BOT))
    assert c["warns"] == {"0": 2, "30": 1, "90": 0} and c["auto"]["0"] == 1 and c["tout"]["0"] == 4, c
    r = asyncio.run(casier.nettoyer(1, "warns", 30, 3, BOT))
    assert r["n"] == 1 and b.casier_de(20) == ["warn", "ban"], "seulement les avertissements de plus de 30 jours"
    r = asyncio.run(casier.nettoyer(1, "tout", 0, 3, BOT))
    assert r["n"] == 3 and r["membres"] == [20, 21] and b.casier_de(20) == ["ban"] and b.casier_de(21) == []
    assert asyncio.run(casier.nettoyer(1, "tout", 0, 3, BOT))["n"] == 0
    assert [x["quoi"] for x in asyncio.run(casier.lots(1))] == ["Tout le casier (sauf bannissements)",
                                                                  "Avertissements, plus de 30 jours"]


def test_C4_defaire_remet_chaque_entree_une_seule_fois(tmp_path):
    b = Base(tmp_path)
    b.ajouter(30, "warn", 1); b.ajouter(30, "mute", 1)
    avant = b.casier_de(30)
    r = asyncio.run(casier.effacer_membre(1, 30, "tout", 3))
    assert r["n"] == 2 and b.casier_de(30) == []
    assert asyncio.run(casier.restaurer(1, r["lot"], 3)) == {"n": 2, "membres": [30]} and b.casier_de(30) == avant
    assert asyncio.run(casier.restaurer(1, r["lot"], 3))["n"] == 0, "jamais deux fois"
    r = asyncio.run(casier.effacer_membre(1, 30, "warns", 3))
    assert r["n"] == 1 and b.casier_de(30) == ["mute"], "ses avertissements seulement"


class Membre:
    def __init__(self, uid, mute=False):
        self.id, self._mute, self.faits = uid, mute, []

    def is_timed_out(self):
        return self._mute

    async def timeout(self, duree, reason=None):
        self.faits.append(("timeout", duree))


def _ns(b, membres):
    recalculs = []

    async def recompute(g, m):
        recalculs.append(m.id)

    async def dormir(_s):
        return None

    async def journal(g, *a, **k):
        return await registre.noter(g.id, *a[:3], **k)

    async def rien(*a, **k):
        return None
    ns = {"get_db": b.get_db, "casier": casier, "discord": discord, "aiosqlite": aiosqlite, "recidivism_module": Obj(recompute=recompute),
          "asyncio": Obj(sleep=dormir, create_task=lambda c: asyncio.ensure_future(c)), "_logerr": lambda *a, **k: None,
          "_au_journal": journal, "log_staff_action": rien, "bot": Obj(user=Obj(id=BOT))}
    for nom in ("_apres_casier", "_action_casier_effacer", "_action_casier_serveur", "_action_casier_restaurer"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1, owner_id=99, get_member=membres.get)
    return ns, g, recalculs


def test_C5_effacer_se_voit_sur_discord(tmp_path):
    b = Base(tmp_path)
    b.ajouter(40, "warn", 1); b.ajouter(40, "mute", 1)

    async def strikes():
        async with b.get_db() as db:
            await db.execute("INSERT INTO badword_strikes VALUES (1, 40, 4)")
            await db.execute("INSERT INTO user_toxicity_scores VALUES (1, 40, 7)")
            await db.commit()
    asyncio.run(strikes())
    m = Membre(40, mute=True)
    ns, g, recalculs = _ns(b, {40: m})
    chef = Obj(id=3, display_name="Chef")
    ok, msg = asyncio.run(ns["_action_casier_effacer"](g, chef, {"membre": 40, "quoi": "tout"}))
    assert ok and "2 entrée(s) du casier effacé(s)" in msg
    assert recalculs == [40] and m.faits == [("timeout", None)], "rôle de récidive recalculé, mute levé"

    async def lire():
        async with b.get_db() as db:
            async with db.execute("SELECT (SELECT COUNT(*) FROM badword_strikes) + (SELECT COUNT(*) FROM user_toxicity_scores)") as cur:
                return (await cur.fetchone())[0]
    assert asyncio.run(lire()) == 0, "compteurs du filtre remis à zéro"
    assert asyncio.run(ns["_action_casier_effacer"](g, chef, {"membre": 40, "quoi": "tout"})) == (False, "Rien à effacer.")
    assert asyncio.run(ns["_action_casier_effacer"](g, chef, {"membre": 99, "quoi": "tout"}))[0] is False


def test_C6_le_casier_du_serveur_demande_effacer(tmp_path):
    b = Base(tmp_path)
    b.ajouter(50, "warn", 1); b.ajouter(51, "warn", 1); b.ajouter(51, "ban", 1)
    ns, g, recalculs = _ns(b, {})
    chef = Obj(id=3, display_name="Chef")

    async def faire(corps):
        r = await ns["_action_casier_serveur"](g, chef, corps)
        await asyncio.sleep(0.05)
        return r
    assert asyncio.run(faire({"portee": "warns", "jours": 0})) == (False, "Écris EFFACER pour confirmer.")
    assert asyncio.run(faire({"portee": "tout; DROP", "jours": 0, "confirmation": "EFFACER"}))[0] is False
    assert asyncio.run(faire({"portee": "warns", "jours": 7, "confirmation": "EFFACER"}))[0] is False, "âges permis : 0, 30, 90"
    ok, msg = asyncio.run(faire({"portee": "warns", "jours": 0, "confirmation": "effacer"}))
    assert ok and msg.startswith("2 entrée(s) effacée(s) pour 2 personne(s)") and b.casier_de(51) == ["ban"]
    lot = asyncio.run(casier.lots(1))[0]["lot"]
    ok, msg = asyncio.run(ns["_action_casier_restaurer"](g, chef, {"lot": lot}))
    assert ok and b.casier_de(50) == ["warn"]


def test_C7_retirer_le_dernier_mute_leve_le_mute(tmp_path):
    b = Base(tmp_path)
    b.ajouter(60, "mute", 3); b.ajouter(60, "mute", 1)
    m = Membre(60, mute=True)
    ns, g, recalculs = _ns(b, {60: m})
    ns.update(tableau=tableau, cfg=lambda *_a: _vide(), _au_journal=ns["_au_journal"])
    exec(_source("_action_sanction_retirer"), ns)  # noqa: S102 — code du dépôt
    chef = Obj(id=3, display_name="Chef", mention="<@3>")
    asyncio.run(ns["_action_sanction_retirer"](g, chef, {"sanction": 1}))
    assert m.faits == [], "un ancien mute retiré ne lève pas le mute en cours"
    asyncio.run(ns["_action_sanction_retirer"](g, chef, {"sanction": 2}))
    assert m.faits == [("timeout", None)] and recalculs == [60, 60]


async def _vide():
    return {"logs_sur_site_v1": "oui"}


def test_C8_branchements():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert '"casier_serveur": _action_casier_serveur' in src and '"debannir": _action_debannir' in src
    assert "if not g.chunked" in _source("amnistie_task"), "jamais d'amnistie sur une liste de membres incomplète"
    assert '"amnistie_task",' in src and "amnistie_task.start()" in src
    assert tableau._genre_grave("casier_serveur", {}) == ("casier", 5) and tableau._genre_grave("debannir", {}) == ("exclusion", 1)
    page = (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert 'action: "casier_serveur"' in page or "casier_serveur" in page
    assert "EFFACER" in page and 'action: "casier_effacer"' in page and 'action: "debannir"' in page
    import data_cleanup
    assert any(p[0] == "archive du casier" for p in data_cleanup.PURGES_CIBLEES)
