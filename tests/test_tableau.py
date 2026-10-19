"""19/10/2026 : « un vrai site interactif… candidatures Rell Seas, tickets ouverts » — « seulement
le rôle staff et au-dessus » — « tu tries bien les tickets par type… de vrais stats »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from pathlib import Path

import aiosqlite

import recrutements
import rellseas_panneau
import tableau
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    return next(ast.unparse(n) for n in ast.parse(SRC).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


class Role:
    def __init__(self, rid, position):
        self.id, self.position = rid, position


def _membre(uid, *roles, admin=False):
    return Obj(id=uid, roles=list(roles), guild_permissions=Obj(administrator=admin),
               display_name=f"M{uid}", name=f"m{uid}", bot=False, joined_at=None,
               display_avatar=Obj(with_size=lambda n: Obj(url=f"https://cdn.discordapp.com/a/{uid}.png")))


def test_T1_le_lien_est_signe_personnel_et_expire():
    tableau._cle = b"secret"
    j = tableau.jeton(1, 7, "tout", maintenant=1000)
    assert tableau.lire_jeton(j, maintenant=1000 + 3600) == {"g": 1, "u": 7, "p": "tout", "e": 1000 + tableau.DUREE}
    assert tableau.lire_jeton(j, maintenant=1000 + tableau.DUREE + 1) is None, "expiré"
    a, b = j.split(".")
    faux = tableau._b64(b"1.8.tout.999999") + "." + b
    assert tableau.lire_jeton(faux, maintenant=1000) is None, "un autre membre ne se fabrique pas"
    assert tableau.lire_jeton("n'importe quoi", maintenant=1000) is None
    tableau._cle = b"autre"
    assert tableau.lire_jeton(j, maintenant=1000) is None


def test_T2_staff_et_au_dessus_seulement():
    ns = {}
    exec(_source("_staff_ou_plus"), ns)  # noqa: S102 — code du dépôt
    autorise = ns["_staff_ou_plus"]
    staff, direction, membre_r = Role(10, 5), Role(11, 8), Role(12, 2)
    g = Obj(owner_id=1, get_role={10: staff, 11: direction}.get)
    c = {"ticket_staff": 10, "direction_allowed_role": 11}
    assert autorise(g, _membre(1), c), "propriétaire"
    assert autorise(g, _membre(2, admin=True), c), "administrateur"
    assert autorise(g, _membre(3, staff), c), "staff"
    assert autorise(g, _membre(4, direction), c), "direction, au-dessus"
    assert autorise(g, _membre(5, Role(13, 9)), c), "un rôle plus haut encore"
    assert not autorise(g, _membre(6, membre_r), c), "membre simple"
    assert not autorise(g, _membre(7, membre_r), {}), "rien de réglé : administration seule"
    assert autorise(g, _membre(8, direction), {"direction_allowed_role": 11})


class Env:
    def __init__(self, tmp_path):
        self.base = tmp_path / "t.db"
        self.conf = {rellseas_panneau.CLE_ROLE_CIBLE: 50, "ticket_staff": 10,
                     "ticket_panels": {"p1": {"name": "Rellseas"}, "p2": {"name": "Support"}}}

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(self.base)
            try:
                yield db
            finally:
                await db.close()

        async def cfg(_g):
            return self.conf

        async def db_set(_g, k, v):
            self.conf[k] = v

        async def mesurer(_gid, membres):
            return {}
        self.clan = Obj(id=50, name="Rell Seas", members=[])
        self.staff = Role(10, 5)
        self.membres = {2: _membre(2, self.staff), 7: _membre(7, self.clan), 8: _membre(8)}
        self.clan.members = [self.membres[7]]
        self.g = Obj(id=1, name="GoRP SEA", icon=None, owner_id=99, get_member=self.membres.get,
                     get_role={50: self.clan, 10: self.staff}.get)
        recrutements.setup(get_db=get_db, cfg=cfg, db_set=db_set, salon=None,
                           role=lambda g, c: self.clan, panneaux=rellseas_panneau.panneaux_tickets,
                           log=lambda *a: None)
        ns = {}
        exec(_source("_staff_ou_plus"), ns)  # noqa: S102 — code du dépôt
        tableau.setup(bot=Obj(get_guild=lambda gid: self.g if gid == 1 else None), cle="k",
                      base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=mesurer,
                      autorise_membre=ns["_staff_ou_plus"], log=lambda *a: None)
        tableau._cache.clear()

        async def preparer():
            await recrutements.init_db()
            async with get_db() as db:
                await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
                                 " user_id INTEGER, panel_id TEXT, claimed_by INTEGER, status TEXT, answers TEXT,"
                                 " created_at DATETIME)")
                await db.execute("CREATE TABLE ticket_log_events(id INTEGER PRIMARY KEY, guild_id INTEGER,"
                                 " ticket_id INTEGER, kind TEXT, actor_id INTEGER, detail TEXT, created_unix INTEGER)")
                await db.executemany("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)", [
                    (1, 1, 901, 7, "p1", 2, "closed", "{}", "2026-10-01 10:00:00"),
                    (2, 1, 902, 8, "p1", 0, "open", '{"Pseudo Roblox": "Mira_RS"}', "2026-10-18 10:00:00"),
                    (3, 1, 903, 8, "p2", 2, "closed", "{}", "2026-10-02 10:00:00"),
                    (4, 1, 904, 8, "p2", 0, "closed", "{}", "2026-10-03 10:00:00"),
                    (5, 1, 905, 7, "p2", 0, "open", "{}", "2026-10-19 08:00:00")])
                base = 1790000000
                await db.executemany("INSERT INTO ticket_log_events(guild_id, ticket_id, kind, actor_id, created_unix)"
                                     " VALUES (?,?,?,?,?)", [(1, 3, "claim", 2, None), (1, 3, "close", 2, None)])
                await db.execute("UPDATE ticket_log_events SET created_unix=? WHERE kind='claim'", (base,))
                await db.execute("UPDATE ticket_log_events SET created_unix=? WHERE kind='close'", (base + 600,))
                await db.commit()
        asyncio.run(preparer())


def test_T3_tickets_tries_par_type_avec_les_vrais_chiffres(tmp_path):
    env = Env(tmp_path)
    d = asyncio.run(tableau.donnees(env.g))
    types = {t["nom"]: t for t in d["tickets"]["types"]}
    assert [t["nom"] for t in d["tickets"]["types"]] == ["Rellseas", "Support"], "Rell Seas d'abord"
    assert types["Rellseas"]["rellseas"] and not types["Support"]["rellseas"]
    assert (types["Rellseas"]["ouverts"], types["Rellseas"]["fermes"]) == (1, 1)
    assert (types["Support"]["ouverts"], types["Support"]["fermes"], types["Support"]["sans_prise"]) == (1, 2, 1)
    assert [o["type"] for o in d["tickets"]["ouverts"]] == ["Rellseas", "Support"]
    assert d["tickets"]["staff"] == [{"nom": "M2", "pris": 2, "fermes": 1}]
    assert sum(sum(v.values()) for v in d["tickets"]["mois"].values()) == 5
    assert [c["nom"] for c in d["en_cours"]] == ["M8"] and list(map(list, d["en_cours"][0]["reponses"])) == [["Pseudo Roblox", "Mira_RS"]]
    assert d["clan"]["role"] == "Rell Seas" and d["clan"]["membres"][0]["id"] == "7"
    json.dumps(d)


def test_T4_page_et_donnees_refusees_sans_lien_valide_ou_hors_staff(tmp_path):
    env = Env(tmp_path)

    def requete(j):
        return Obj(match_info={"jeton": j})

    async def scenario():
        bon = tableau.jeton(1, 2, "tout")
        hors_staff = tableau.jeton(1, 8, "tout")
        return (await tableau.page(requete(bon)), await tableau.api(requete(bon)),
                await tableau.page(requete("faux")), await tableau.api(requete(hors_staff)))
    page, api, faux, refuse = asyncio.run(scenario())
    assert page.status == 200 and "Tableau de bord" in page.text
    assert page.headers["Cache-Control"] == "no-store" and "noindex" in page.headers["X-Robots-Tag"]
    corps = json.loads(api.text)
    assert api.status == 200 and corps["tickets"]["types"] and corps["expire"] > 0
    assert faux.status == 403 and "plus valable" in faux.text
    assert refuse.status == 403, "un lien d'un membre qui n'est pas staff ne montre rien"


def test_T5_le_bouton_ne_donne_le_lien_qu_au_staff(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        ok = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[2]))
        non = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[8]))
        return ok, non
    (url, refus), (url2, refus2) = asyncio.run(scenario())
    assert url.startswith("https://bot.exemple/tableau/") and refus == ""
    assert url2 is None and "staff" in refus2


def test_T6_la_page_n_injecte_jamais_de_donnees_en_html():
    page = tableau.PAGE
    assert "innerHTML = chemin" in page and page.count("innerHTML") == 1, "seules les icônes fixes"
    assert "textContent" in page and "createTextNode" in page
    assert "fetch(" in page and "/donnees" in page
