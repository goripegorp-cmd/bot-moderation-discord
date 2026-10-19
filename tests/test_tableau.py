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


def test_T7_sanctions_en_chiffres_et_en_cours(tmp_path):
    from datetime import datetime, timedelta, timezone
    env = Env(tmp_path)
    radie_role = Obj(id=66, name="🚫 Radié", members=[env.membres[8]])
    env.g.roles = [radie_role]
    fin = datetime.now(timezone.utc) + timedelta(hours=2)
    env.membres[7].is_timed_out = lambda: True
    env.membres[7].timed_out_until = fin
    env.membres[8].is_timed_out = lambda: False
    env.membres[2].is_timed_out = lambda: False
    env.g.members = list(env.membres.values())
    tableau._bot.user = Obj(id=999)
    il_y_a = lambda j: (datetime.now(timezone.utc) - timedelta(days=j)).strftime("%Y-%m-%d %H:%M:%S")

    async def preparer():
        async with aiosqlite.connect(env.base) as db:
            await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY, guild_id INTEGER, user_id INTEGER,"
                             " mod_id INTEGER, type TEXT, reason TEXT, duration TEXT, created_at DATETIME)")
            await db.execute("CREATE TABLE restricted_members(guild_id INTEGER, user_id INTEGER, roles_backup TEXT,"
                             " restricted_at DATETIME, duration INTEGER, reason TEXT, restricted_by INTEGER)")
            await db.executemany("INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration, created_at)"
                                 " VALUES (?,?,?,?,?,?,?)", [
                (1, 7, 2, "warn", "Spam", "", il_y_a(2)), (1, 7, 999, "insulte", "Insulte détectée", "", il_y_a(3)),
                (1, 7, 2, "mute", "Récidive", "1h", il_y_a(4)), (1, 8, 999, "protection", "Lien", "", il_y_a(400)),
                (1, 8, 2, "ban", "Raid", "", il_y_a(40))])
            await db.execute("INSERT INTO restricted_members VALUES (1, 8, '[]', ?, 0, 'Direction', 2)", (il_y_a(1),))
            await db.commit()
    asyncio.run(preparer())
    s = asyncio.run(tableau._sanctions(env.g))
    assert (s["total"], s["trente_jours"], s["auto"], s["manuel"]) == (5, 3, 2, 3)
    types = {t["type"]: t for t in s["types"]}
    assert types["insulte"]["detection"] and not types["warn"]["detection"] and types["ban"]["libelle"] == "Bannissement"
    assert [(x["nom"], x["total"], x["types"]) for x in s["staff"]] == \
        [("M2", 3, {"warn": 1, "mute": 1, "ban": 1})], "le bot n'est pas un modérateur"
    assert [y["type"] for y in s["staff"][0]["dernieres"]] == ["ban", "mute", "warn"], "tout ce qu'il a attribué"
    assert s["surveiller"][0]["total_tout"] == 3
    assert s["surveiller"][0]["id"] == "7" and s["surveiller"][0]["total"] == 3, "90 jours seulement"
    assert s["recentes"][0]["libelle"] == "Bannissement" and s["recentes"][-1]["auto"] is False
    assert [m["id"] for m in s["actives"]["mutes"]] == ["7"] and s["actives"]["mutes"][0]["jusqu"]
    assert [m["id"] for m in s["actives"]["radies"]] == ["8"]
    assert s["actives"]["restreints"][0]["par"] == "M2"
    assert sum(sum(v.values()) for v in s["mois"].values()) == 4, "plus d'un an : hors du graphique"


def test_T8_le_salon_du_tableau_reserve_au_staff_et_epingle():
    import discord
    import visuels
    from ui_v2 import LayoutView, Palette
    staff, direction, membre_r, robot_r = Role(10, 5), Role(11, 8), Role(12, 2), Role(13, 9)
    robot_r.managed = True
    for r in (staff, direction, membre_r):
        r.managed = False
    tous = Obj(id=1, position=0, managed=False)
    conf, crees, envois, epingles = {"ticket_staff": 10, "direction_allowed_role": 11}, [], [], []

    class Message:
        id = 555

        async def pin(self, reason=None):
            epingles.append(reason)

    class Salon:
        id = 77

        async def send(self, **kw):
            envois.append(kw)
            return Message()

        async def fetch_message(self, mid):
            if mid != 555:
                raise discord.NotFound(Obj(status=404, reason="x"), "x")
            return Message()
    salon = Salon()

    async def creer(nom, **kw):
        crees.append((nom, kw))
        return salon
    me = Obj(guild_permissions=Obj(manage_channels=True, manage_roles=True))
    g = Obj(id=1, default_role=tous, roles=[tous, membre_r, staff, direction, robot_r], me=me,
            get_role={10: staff, 11: direction}.get, create_text_channel=creer,
            get_channel=lambda cid: salon if cid == 77 and conf.get("tableau_salon") == 77 else None)

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v
    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "visuels": visuels, "LayoutView": LayoutView,
          "Palette": Palette, "recrutements": recrutements, "_logerr": lambda *a, **k: None}
    exec(_source("_salon_tableau"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["_salon_tableau"](g))
    asyncio.run(ns["_salon_tableau"](g))
    assert len(crees) == 1 and crees[0][0] == "📊tableau-de-bord"
    ows = crees[0][1]["overwrites"]
    assert ows[tous].view_channel is False
    assert ows[staff].view_channel and ows[direction].view_channel, "staff et au-dessus"
    assert membre_r not in ows and robot_r not in ows
    assert len(envois) == 1 and epingles, "un seul message, épinglé"
    composants = list(envois[0]["view"].walk_children())
    assert any(getattr(c, "custom_id", "") == "recr:web" for c in composants)


def test_T9_seuls_le_fondateur_et_la_direction_agissent():
    ns = {"owner_ids_module": Obj(is_super_owner=lambda uid: uid == 42)}
    exec(_source("_direction_ou_plus"), ns)  # noqa: S102 — code du dépôt
    direction = ns["_direction_ou_plus"]
    staff, dir_r, haut = Role(10, 5), Role(11, 8), Role(12, 9)
    g = Obj(owner_id=1, get_role={10: staff, 11: dir_r}.get)
    c = {"ticket_staff": 10, "direction_allowed_role": 11}
    assert direction(g, _membre(1), c) and direction(g, _membre(42), c), "fondateur"
    assert direction(g, _membre(3, dir_r), c) and direction(g, _membre(4, haut), c)
    assert not direction(g, _membre(5, staff), c), "le staff voit, mais n'agit pas"
    assert not direction(g, _membre(6, admin=True), {}), "sans rôle direction : le fondateur seul"


def test_T10_actions_verifiees_tracees_et_limitees(tmp_path):
    env = Env(tmp_path)
    appels = []

    async def fermer(g, auteur, corps):
        appels.append((auteur.id, corps))
        return True, "Ticket fermé."
    tableau._actions = {"ticket_fermer": fermer}
    tableau._direction = lambda g, m, c: m is not None and m.id == 2
    tableau._cadence.clear()

    class Requete:
        def __init__(self, j, corps, entete=True):
            self.match_info = {"jeton": j}
            self.headers = {"X-Tableau": "1"} if entete else {}
            self._corps = corps
            self.content_length = len(json.dumps(corps))

        async def json(self):
            return self._corps

    async def scenario():
        bon, staff_simple = tableau.jeton(1, 2, "tout"), tableau.jeton(1, 8, "tout")
        env.membres[8].roles = [env.staff]
        sans_entete = await tableau.action(Requete(bon, {"action": "ticket_fermer", "ticket": 5}, entete=False))
        refuse = await tableau.action(Requete(staff_simple, {"action": "ticket_fermer", "ticket": 5}))
        inconnue = await tableau.action(Requete(bon, {"action": "tout_supprimer"}))
        ok = await tableau.action(Requete(bon, {"action": "ticket_fermer", "ticket": 5}))
        for _ in range(25):
            dernier = await tableau.action(Requete(bon, {"action": "ticket_fermer", "ticket": 5}))
        return sans_entete, refuse, inconnue, ok, dernier
    sans_entete, refuse, inconnue, ok, dernier = asyncio.run(scenario())
    assert sans_entete.status == 400, "une requête venue d'ailleurs que la page est refusée"
    assert refuse.status == 403 and "direction" in json.loads(refuse.text)["message"]
    assert inconnue.status == 400
    assert ok.status == 200 and json.loads(ok.text) == {"ok": True, "message": "Ticket fermé."}
    assert appels[0] == (2, {"action": "ticket_fermer", "ticket": 5})
    assert dernier.status == 429, "pas plus de 20 actions par minute"
