"""19/10/2026 : « un vrai site interactif… candidatures Rell Seas, tickets ouverts » — « des zones
par personne » — « direction et fondateur mis à part » — « renforce l'infrastructure du site :
quelqu'un qui n'a pas les accès ne l'a pas du tout » — « on va restreindre le site à 2 types de
rôles : fondateur et direction. Les staffs n'auront pas accès au site »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

import casier
import clan
import questions
import sondages
import suggestions
import recrutements
import registre
import rellseas_panneau
import tableau
import vigilance
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ORIGINE = {"X-Tableau": "1", "Origin": "https://bot.exemple", "Sec-Fetch-Site": "same-origin"}


def _source(nom):
    return next(ast.unparse(n) for n in ast.parse(SRC).body
                if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)
                or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets)))


class Role:
    def __init__(self, rid, position):
        self.id, self.position = rid, position


def _membre(uid, *roles, admin=False):
    return Obj(id=uid, roles=list(roles), guild_permissions=Obj(administrator=admin),
               display_name=f"M{uid}", name=f"m{uid}", bot=False, joined_at=None,
               display_avatar=Obj(with_size=lambda n: Obj(url=f"https://cdn.discordapp.com/a/{uid}.png")))


class Requete:
    """Une requête du navigateur, telle que le site la voit."""

    def __init__(self, jeton="", cookie=None, corps=None, entetes=None, query=None, ip="1.2.3.4"):
        self.match_info = {"jeton": jeton}
        self.cookies = {tableau.COOKIE: cookie} if cookie else {}
        self.headers = dict(entetes or {})
        self.query = dict(query or {})
        self._corps = corps
        self.content_length = len(json.dumps(corps)) if corps is not None else 0
        self.remote, self.scheme, self.host = ip, "https", "bot.exemple"

    async def json(self):
        return self._corps


def test_T1_le_lien_est_signe_personnel_expire_et_unique():
    tableau._cle = b"secret"
    j = tableau.jeton(1, 7, "tout", maintenant=1000, nonce="abc")
    assert tableau.lire_jeton(j, maintenant=1000 + 3600) == {"g": 1, "u": 7, "p": "tout", "e": 1000 + tableau.DUREE, "n": "abc"}
    assert tableau.lire_jeton(j, maintenant=1000 + tableau.DUREE + 1) is None, "expiré"
    a, b = j.split(".")
    faux = tableau._b64(b"1.8.tout.999999.abc") + "." + b
    assert tableau.lire_jeton(faux, maintenant=1000) is None, "un autre membre ne se fabrique pas"
    assert tableau.lire_jeton("n'importe quoi", maintenant=1000) is None
    ancien = tableau._b64(b"1.7.tout.99999999")
    import hashlib
    import hmac
    sig = tableau._b64(hmac.new(b"secret", b"1.7.tout.99999999", hashlib.sha256).digest()[:18])
    assert tableau.lire_jeton(ancien + "." + sig, maintenant=1000) is None, "l'ancien format (sans usage unique) ne vaut plus"
    assert tableau.jeton(1, 7, "tout") != tableau.jeton(1, 7, "tout"), "chaque lien est neuf"
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
        self.get_db = get_db

        async def cfg(_g):
            return self.conf

        async def db_set(_g, k, v):
            self.conf[k] = v

        async def mesurer(_gid, membres):
            return {}
        self.clan = Obj(id=50, name="Rell Seas", members=[], position=1)
        self.staff = Role(10, 5)
        self.membres = {2: _membre(2, self.staff), 3: _membre(3, self.staff), 7: _membre(7, self.clan), 8: _membre(8)}
        self.clan.members = [self.membres[7], self.membres[3]]
        self.g = Obj(id=1, name="GoRP SEA", icon=None, owner_id=99, get_member=self.membres.get,
                     members=list(self.membres.values()), roles=[], default_role=Obj(id=1, position=0),
                     get_role={50: self.clan, 10: self.staff}.get, get_channel=lambda i: None,
                     get_thread=lambda i: None)
        registre.setup(get_db=get_db, log=lambda *a: None)
        registre._derniers.clear()
        recrutements.setup(get_db=get_db, cfg=cfg, db_set=db_set, salon=None,
                           role=lambda g, c: self.clan, panneaux=rellseas_panneau.panneaux_tickets,
                           log=lambda *a: None)
        ns = {}
        exec(_source("_staff_ou_plus"), ns)  # noqa: S102 — code du dépôt
        self.alertes = []

        async def alerte(g, m, raison, suspendu=True):
            self.alertes.append((m.id, raison, suspendu))

        def direction(g, m, c):
            return m is not None and m.id == 3
        tableau.setup(bot=Obj(get_guild=lambda gid: self.g if gid == 1 else None, user=Obj(id=999)), cle="k",
                      base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=mesurer,
                      autorise_membre=direction, direction=direction, alerte_securite=alerte, log=lambda *a: None)
        questions.setup(get_db=get_db, est_staff=ns["_staff_ou_plus"], log=lambda *a: None)
        clan.setup(get_db=get_db, log=lambda *a: None)
        sondages.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None, log=lambda *a: None)
        suggestions.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None, salon_logs=None,
                          log=lambda *a: None)
        casier.setup(get_db=get_db, log=lambda *a: None)

        async def salon(_g):
            return None
        vigilance.setup(get_db=get_db, salon=salon, carte=lambda *a: None, log=lambda *a: None)

        async def preparer():
            await recrutements.init_db()
            await registre.init_db()
            await tableau.init_db()
            await questions.init_db()
            await vigilance.init_db()
            await clan.init_db()
            await casier.init_db()
            await sondages.init_db()
            await suggestions.init_db()
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

    def session(self, uid: int) -> str:
        r = asyncio.run(tableau.entree(Requete(tableau.jeton(1, uid, "tout"))))
        assert r.status == 303, r.status
        return r.cookies[tableau.COOKIE].value


def test_T3_tickets_tries_par_type_et_direction_a_part(tmp_path):
    env = Env(tmp_path)
    d = asyncio.run(tableau.donnees(env.g))
    types = {t["nom"]: t for t in d["tickets"]["types"]}
    assert [t["nom"] for t in d["tickets"]["types"]] == ["Rellseas", "Support"], "Rell Seas d'abord"
    assert types["Rellseas"]["rellseas"] and not types["Support"]["rellseas"]
    assert (types["Rellseas"]["ouverts"], types["Rellseas"]["fermes"]) == (1, 1)
    assert (types["Support"]["ouverts"], types["Support"]["fermes"], types["Support"]["sans_prise"]) == (1, 2, 1)
    assert [o["type"] for o in d["tickets"]["ouverts"]] == ["Rellseas", "Support"]
    assert d["tickets"]["staff"] == [{"nom": "M2", "pris": 2, "fermes": 1}]
    assert [t["ticket"] for t in d["tickets"]["fermes"]] == [4, 1, 3] and d["tickets"]["fermes"][0]["id"] == "8", "du plus récent au plus ancien"
    assert sum(sum(v.values()) for v in d["tickets"]["mois"].values()) == 5
    assert [c["nom"] for c in d["en_cours"]] == ["M8"] and list(map(list, d["en_cours"][0]["reponses"])) == [["Pseudo Roblox", "Mira_RS"]]
    assert d["clan"]["role"] == "Rell Seas" and [m["id"] for m in d["clan"]["membres"]] == ["7"]
    assert [m["id"] for m in d["clan"]["direction"]] == ["3"], "direction et fondateur : mis à part des stats"
    assert set(d["a_part"]) == {"3", "99"} and d["personnes"]["8"]["nom"] == "M8" and d["version"] == tableau.VERSION
    json.dumps(d)


def test_T4_lien_a_usage_unique_puis_session(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        j = tableau.jeton(1, 3, "tout")
        entree = await tableau.entree(Requete(j))
        sid = entree.cookies[tableau.COOKIE].value
        rejoue = await tableau.entree(Requete(j))
        rejoue_meme_navigateur = await tableau.entree(Requete(j, cookie=sid))
        page = await tableau.page(Requete(cookie=sid))
        sans = await tableau.page(Requete())
        api = await tableau.api(Requete(cookie=sid))
        api304 = await tableau.api(Requete(cookie=sid, entetes={"If-None-Match": api.headers["ETag"]}))
        hors_staff = await tableau.entree(Requete(tableau.jeton(1, 8, "tout")))
        staff = await tableau.entree(Requete(tableau.jeton(1, 2, "tout")))
        faux = await tableau.entree(Requete("faux"))
        sortie = await tableau.sortir(Requete(cookie=sid, entetes=ORIGINE))
        apres = await tableau.api(Requete(cookie=sid))
        return entree, rejoue, rejoue_meme_navigateur, page, sans, api, api304, hors_staff, staff, faux, sortie, apres
    entree, rejoue, meme, page, sans, api, api304, hors_staff, staff, faux, sortie, apres = asyncio.run(scenario())
    biscuit = entree.cookies[tableau.COOKIE]
    assert entree.status == 303 and entree.headers["Location"] == tableau.ESPACE, "l'adresse perd le jeton"
    assert biscuit["httponly"] and biscuit["secure"] and biscuit["samesite"] == "Lax" and biscuit["path"] == "/"
    assert rejoue.status == 403 and "déjà servi" in rejoue.text, "un lien copié ne sert plus à rien"
    assert meme.status == 303, "le même navigateur, déjà connecté, repasse sans erreur"
    assert page.status == 200 and "Espace direction" in page.text and "__NONCE__" not in page.text
    csp = page.headers["Content-Security-Policy"]
    assert "script-src 'nonce-" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert page.headers["Cache-Control"] == "no-store" and "noindex" in page.headers["X-Robots-Tag"]
    assert page.headers["X-Frame-Options"] == "DENY" and "max-age" in page.headers["Strict-Transport-Security"]
    assert sans.status == 403 and "plus valable" in sans.text and "script-src 'none'" in sans.headers["Content-Security-Policy"]
    corps = json.loads(api.text)
    assert api.status == 200 and corps["tickets"]["types"] and corps["expire"] > 0 and api.headers["ETag"]
    assert api304.status == 304, "rien n'a changé : rien n'est retéléchargé"
    assert hors_staff.status == 403 and faux.status == 403, "un lien d'un simple membre ne montre rien"
    assert staff.status == 403, "le staff n'entre plus sur le site, même avec un lien signé"
    assert sortie.status == 204 and apres.status == 403, "déconnecté : la session est effacée"


def test_T5_le_bouton_ne_donne_le_lien_qu_au_fondateur_et_a_la_direction(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        ok = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[3]), membre_id=7)
        non = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[8]))
        staff = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[2]))
        await tableau.suspendre(env.g, env.membres[3], "essai")
        suspendu = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[3]))
        return ok, non, staff, suspendu
    (url, refus), (url2, refus2), (url4, refus4), (url3, refus3) = asyncio.run(scenario())
    assert url.startswith("https://bot.exemple/tableau/") and url.endswith("#membre=7") and refus == ""
    assert url2 is None and "direction" in refus2
    assert url4 is None and refus4 == "Réservé au fondateur et à la direction.", "le staff n'a plus de lien"
    assert url3 is None and "suspendu" in refus3


def test_T6_la_page_n_injecte_jamais_de_donnees_en_html():
    page = tableau.PAGE
    assert page.count("innerHTML") == 0 and "insertAdjacentHTML" not in page and "eval(" not in page
    assert "textContent" in page and "createTextNode" in page and '<script nonce="__NONCE__">' in page
    assert page.count("<script") == 1 and "fetch(" in page and "/donnees" in page and "If-None-Match" in page
    assert "/tableau/espace" in page and "location.reload()" in page, "la page se relance seule"
    assert "add_roles" not in page and "role_donner" not in page, "le site ne donne aucun rôle"


def test_T7_casier_par_membre_direction_a_part(tmp_path):
    env = Env(tmp_path)
    radie_role = Obj(id=66, name="🚫 Radié", members=[env.membres[8]])
    env.g.roles = [radie_role]
    fin = datetime.now(timezone.utc) + timedelta(hours=2)
    env.membres[7].is_timed_out = lambda: True
    env.membres[7].timed_out_until = fin
    for k in (2, 3, 8):
        env.membres[k].is_timed_out = lambda: False
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
                (1, 8, 2, "ban", "Raid", "", il_y_a(40)), (1, 8, 3, "warn", "Par la direction", "", il_y_a(1)),
                (1, 3, 2, "warn", "La direction ne figure pas au casier du site", "", il_y_a(1))])
            await db.execute("INSERT INTO restricted_members VALUES (1, 8, '[]', ?, 0, 'Direction', 2)", (il_y_a(1),))
            await db.commit()
    asyncio.run(preparer())
    qui = tableau._Personnes(env.g)
    s = asyncio.run(tableau._sanctions(env.g, {3, 99}, qui))
    assert (s["total"], s["trente_jours"], s["auto"], s["manuel"]) == (7, 5, 2, 5)
    types = {t["type"]: t for t in s["types"]}
    assert types["insulte"]["detection"] and not types["warn"]["detection"] and types["ban"]["libelle"] == "Bannissement"
    assert [(x["nom"], x["total"], x["types"]) for x in s["staff"]] == \
        [("M2", 4, {"warn": 2, "mute": 1, "ban": 1})], "ni le bot ni la direction dans les stats du staff"
    par = {m["id"]: m for m in s["membres"]}
    assert set(par) == {"7", "8"}, "une case par personne ; la direction n'y figure pas"
    assert (par["7"]["total"], par["7"]["n30"], par["7"]["n90"]) == (3, 3, 3)
    assert [x["type"] for x in par["7"]["liste"]] == ["mute", "insulte", "warn"], "tout ce qu'elle a reçu, du plus récent"
    assert par["7"]["liste"][1]["auto"] and par["7"]["liste"][0]["par"] == "M2"
    assert (par["8"]["total"], par["8"]["n30"], par["8"]["n90"]) == (3, 1, 2)
    assert [m["id"] for m in s["actives"]["mutes"]] == ["7"] and s["actives"]["mutes"][0]["jusqu"]
    assert [m["id"] for m in s["actives"]["radies"]] == ["8"]
    assert s["actives"]["restreints"][0]["par"] == "M2"
    assert sum(sum(v.values()) for v in s["mois"].values()) == 6, "plus d'un an : hors du graphique"


def test_T8_un_seul_salon_de_logs_le_menu_epingle_toujours_a_jour():
    """« Il n'y aura qu'un seul salon, qui mettra le lien correctement… tout le temps opérationnel. »"""
    import annonces
    import cadeaux
    import liens_jeux
    import zones
    import discord
    import visuels
    from ui_v2 import LayoutView, Palette
    staff, direction, membre_r, robot_r = Role(10, 5), Role(11, 8), Role(12, 2), Role(13, 9)
    robot_r.managed = True
    for r in (staff, direction, membre_r):
        r.managed = False
    tous = Obj(id=1, position=0, managed=False)
    conf, crees, envois, epingles, edits = {"ticket_staff": 10, "direction_allowed_role": 11}, [], [], [], []
    etat = {"site": False, "supprime": False}

    class Message:
        id = 555

        async def pin(self, reason=None):
            epingles.append(reason)

        async def edit(self, **kw):
            edits.append(kw)

    class Salon:
        id = 77

        async def send(self, **kw):
            envois.append(kw)
            return Message()

        async def fetch_message(self, mid):
            if mid != 555 or etat["supprime"]:
                raise discord.NotFound(Obj(status=404, reason="x"), "x")
            return Message()
    salon = Salon()

    async def mode_site(_gid):
        return etat["site"]

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
          "Palette": Palette, "recrutements": recrutements, "annonces": annonces, "cadeaux": cadeaux, "liens_jeux": liens_jeux, "zones": zones,
          "_logerr": lambda *a, **k: None,
          "ulogger2026": Obj(mode_site=mode_site), "now": lambda: datetime.now(timezone.utc)}
    for nom in ("NOM_SALON_LOGS", "MENU_LOGS_VERSION", "_anciens_salons", "_menu_logs", "_salon_tableau"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    assert asyncio.run(ns["_salon_tableau"](g)) is salon
    asyncio.run(ns["_salon_tableau"](g))
    assert len(crees) == 1 and crees[0][0] == "📋logs"
    ows = crees[0][1]["overwrites"]
    assert ows[tous].view_channel is False
    assert ows[direction].view_channel and staff not in ows, "la direction et au-dessus, plus le staff"
    assert membre_r not in ows and robot_r not in ows
    assert conf.get("logs_direction_v1"), "créé déjà réservé : aucune migration à refaire"
    assert len(envois) == 1 and epingles and not edits, "un seul message, épinglé, pas réécrit pour rien"
    composants = list(envois[0]["view"].walk_children())
    assert any(getattr(c, "custom_id", "") == "recr:web" for c in composants)

    etat["site"] = True
    asyncio.run(ns["_salon_tableau"](g))
    asyncio.run(ns["_salon_tableau"](g))
    assert len(edits) == 1, "le menu change une fois, il est réécrit une fois"
    textes = " ".join(c.content for c in edits[0]["view"].walk_children() if isinstance(c, discord.ui.TextDisplay))
    assert "Plus aucun log sur Discord" in textes
    etat["supprime"] = True
    asyncio.run(ns["_salon_tableau"](g))
    assert len(envois) == 2 and len(epingles) == 2, "supprimé : le menu revient, épinglé"


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


def test_T10_actions_verifiees_origine_droits_cadence(tmp_path):
    env = Env(tmp_path)
    appels = []

    async def fermer(g, auteur, corps):
        appels.append((auteur.id, corps))
        return True, "Ticket fermé."

    async def question(g, auteur, corps):
        return True, "Question traitée."
    tableau._actions = {"ticket_fermer": fermer, "question": question}
    dir_sid = env.session(3)
    staff_sid = asyncio.run(tableau._ouvrir_session(1, 2, 4102444800))

    def act(sid, corps, entetes=ORIGINE):
        return tableau.action(Requete(cookie=sid, corps=corps, entetes=entetes))

    async def scenario():
        sans_entete = await act(dir_sid, {"action": "ticket_fermer", "ticket": 5}, {})
        autre_site = await act(dir_sid, {"action": "ticket_fermer", "ticket": 5}, dict(ORIGINE, Origin="https://pirate.exemple"))
        croise = await act(dir_sid, {"action": "ticket_fermer", "ticket": 5}, dict(ORIGINE, **{"Sec-Fetch-Site": "cross-site"}))
        sans_session = await tableau.action(Requete(corps={"action": "ticket_fermer"}, entetes=ORIGINE))
        refuse = await act(staff_sid, {"action": "ticket_fermer", "ticket": 5})
        geste_staff = await act(staff_sid, {"action": "question", "question": 1, "statut": "traitee"})
        inconnue = await act(dir_sid, {"action": "tout_supprimer"})
        ok = await act(dir_sid, {"action": "ticket_fermer", "ticket": 5})
        for _ in range(25):
            dernier = await act(dir_sid, {"action": "ticket_fermer", "ticket": 5})
        return sans_entete, autre_site, croise, sans_session, refuse, geste_staff, inconnue, ok, dernier
    sans_entete, autre_site, croise, sans_session, refuse, geste_staff, inconnue, ok, dernier = asyncio.run(scenario())
    assert sans_entete.status == autre_site.status == croise.status == 400, "une requête venue d'ailleurs que la page est refusée"
    assert sans_session.status == 403
    assert refuse.status == 403 and geste_staff.status == 403, "même une session forgée pour le staff n'agit pas"
    assert inconnue.status == 400
    assert ok.status == 200 and json.loads(ok.text) == {"ok": True, "message": "Ticket fermé."}
    assert appels[0] == (3, {"action": "ticket_fermer", "ticket": 5})
    assert dernier.status == 429, "pas plus de 20 actions par minute"


def test_T11_trop_d_actions_graves_suspend_l_acces(tmp_path):
    """« Si quelqu'un se fait voler son compte » : 6 bannissements en 10 minutes, c'est stop."""
    env = Env(tmp_path)
    faits = []

    async def moderer(g, auteur, corps):
        faits.append(corps["membre"])
        return True, "Banni."
    tableau._actions = {"moderer": moderer}
    sid = env.session(3)

    async def scenario():
        reps = [await tableau.action(Requete(cookie=sid, corps={"action": "moderer", "sanction": "ban", "membre": k},
                                             entetes=ORIGINE)) for k in range(6)]
        apres = await tableau.api(Requete(cookie=sid))
        lien = await tableau.lien_pour(Obj(guild=env.g, user=env.membres[3]))
        return reps, apres, lien
    reps, apres, lien = asyncio.run(scenario())
    assert [r.status for r in reps] == [200] * 5 + [403] and len(faits) == 5, "le 6ᵉ n'est jamais exécuté"
    assert "suspendu" in json.loads(reps[-1].text)["message"]
    assert apres.status == 403, "sessions fermées sur-le-champ"
    assert lien[0] is None and "suspendu" in lien[1]
    assert env.alertes and env.alertes[0][0] == 3, "le fondateur est prévenu dans le salon des logs"


def test_T14_la_tete_n_est_jamais_suspendue(tmp_path):
    """« Si tu es suspendu alors que je suis le fondateur, bon, il y a un petit problème… c'est ceux-là et
    uniquement eux qui sont à la tête. »"""
    env = Env(tmp_path)
    tableau._tete = frozenset({3})

    async def deja_suspendu():
        async with env.get_db() as db:
            await db.execute("INSERT INTO tableau_blocages VALUES (1, 3, ?, 'ancienne')",
                             (int(datetime.now(timezone.utc).timestamp()) + 3600,))
            await db.commit()
        tableau._blocages.clear()
        await tableau.init_db()
        return await tableau.suspendu(1, 3)
    assert asyncio.run(deja_suspendu()) == 0, "une suspension en cours est levée au démarrage"
    faits = []

    async def moderer(g, auteur, corps):
        faits.append(corps["membre"])
        return True, "Banni."
    tableau._actions = {"moderer": moderer}
    sid = env.session(3)

    async def scenario():
        return [await tableau.action(Requete(cookie=sid, corps={"action": "moderer", "sanction": "ban", "membre": k},
                                             entetes=ORIGINE)) for k in range(8)]
    reps = asyncio.run(scenario())
    assert [r.status for r in reps] == [200] * 8 and len(faits) == 8, "jamais suspendu"
    assert env.alertes == [(3, "6 actions graves (exclusion) en moins de 10 minutes", False)], "signalé une fois, pas suspendu"


def test_T15_la_fiche_montre_les_sondages_du_membre(tmp_path):
    """« Ajouter un onglet Sondages dans la fiche de chaque membre. »"""
    env = Env(tmp_path)
    salon = Obj(id=50, name="📊sondages")
    env.g.get_channel = lambda cid: salon if cid == 50 else None

    async def scenario():
        async with env.get_db() as db:
            await db.executemany(
                "INSERT INTO sondages(message_id, guild_id, channel_id, auteur_id, question, choix, comptes, total, cree_le,"
                " fin_le) VALUES (?,1,50,?,?,'[\"Oui\", \"Non\"]','[3, 1]',4,'2026-10-19 10:00:00','2026-10-20 10:00:00')",
                [(901, 7, "On fait un event ?"), (902, 8, "Autre membre ?")])
            await db.commit()
        return await tableau.fiche(env.g, 7, env.membres[3])
    f = asyncio.run(scenario())
    assert [x["question"] for x in f["sondages"]] == ["On fait un event ?"], "seulement les siens"
    assert f["sondages"][0]["salon"] == "#📊sondages" and f["sondages"][0]["comptes"] == [3, 1]
    page = tableau.PAGE
    assert '["sondages", "Sondages et idées"]' in page and "function entreeSondage" in page and "function entreeIdee" in page


def test_T12_export_propre_et_reserve(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        await registre.noter(1, "Modération", "mod.warn", "=HYPERLINK(\"http://x\") avertissement", membre_id=7, auteur_id=2)
        csv_ = await tableau.exporter(env.g, "journal", env.membres[2], 7)
        json_ = await tableau.exporter(env.g, "journal", env.membres[2], 7, format_="json")
        erreurs_staff = await tableau.exporter(env.g, "erreurs", env.membres[2])
        inconnu = await tableau.exporter(env.g, "tout", env.membres[3])
        return csv_, json_, erreurs_staff, inconnu
    (contenu, type_, nom), (jcontenu, jtype, jnom), erreurs_staff, inconnu = asyncio.run(scenario())
    texte = contenu.decode("utf-8")
    assert texte.startswith("﻿Date;Catégorie;Type;Gravité;Membre") and type_ == "text/csv" and nom.endswith(".csv")
    assert "'=HYPERLINK" in texte, "une formule n'est jamais exécutée à l'ouverture dans Excel"
    assert "M7 (7)" in texte and "M2 (2)" in texte
    assert jtype == "application/json" and json.loads(jcontenu)[0]["type"] == "mod.warn"
    assert erreurs_staff is None and inconnu is None, "les erreurs du bot : fondateur et direction seulement"


def test_T13_les_adresses_du_site_par_http(tmp_path):
    """Le vrai serveur HTTP, de bout en bout : le lien, la session, chaque adresse."""
    from aiohttp.test_utils import TestClient, TestServer

    import health_server
    env = Env(tmp_path)

    async def raison(g, auteur, corps):
        return True, "Fait."
    tableau._actions = {"essai": raison}

    async def scenario():
        out = {}
        async with TestClient(TestServer(health_server.construire_app())) as client:
            r = await client.get("/tableau/" + tableau.jeton(1, 3, "tout"), allow_redirects=False)
            out["entree"] = (r.status, r.headers.get("Location"))
            sid = r.cookies[tableau.COOKIE].value
            biscuit = {"Cookie": f"{tableau.COOKIE}={sid}"}
            for nom, chemin in (("page", "/tableau/espace"), ("donnees", "/tableau/espace/donnees"),
                                ("membre", "/tableau/espace/membre?id=7"), ("export", "/tableau/espace/export?quoi=journal"),
                                ("sans", "/tableau/espace"), ("inconnue", "/tableau/espace/rien")):
                r = await client.get(chemin, headers=biscuit if nom != "sans" else {})
                out[nom] = (r.status, r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", ""))
            origine = dict(biscuit, **{"X-Tableau": "1", "Origin": "https://bot.exemple"})
            r = await client.post("/tableau/espace/action", json={"action": "essai"}, headers=origine)
            out["action"] = (r.status, await r.json())
            r = await client.post("/tableau/espace/sortir", headers=origine)
            out["sortir"] = r.status
            r = await client.get("/tableau/espace/donnees", headers=biscuit)
            out["apres"] = r.status
        return out
    out = asyncio.run(scenario())
    assert out["entree"] == (303, "/tableau/espace")
    assert out["page"][0] == 200 and out["page"][1].startswith("text/html")
    assert out["donnees"][0] == 200 and out["membre"][0] == 200
    assert out["export"][0] == 200 and out["export"][1].startswith("text/csv") and "attachment" in out["export"][2]
    assert out["sans"][0] == 403 and out["inconnue"][0] == 404
    assert out["action"] == (200, {"ok": True, "message": "Fait."})
    assert out["sortir"] == 204 and out["apres"] == 403
