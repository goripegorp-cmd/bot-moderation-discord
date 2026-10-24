"""Revue du 24/10/2026 — le site privé (tableau de bord) : chaque constat vérifié, corrigé, gardé ici.

R1 le site et ses actions : les deux comptes de la tête seulement ; l'export des erreurs ne sort
   jamais celles des autres serveurs. R2 l'alerte « accès au site suspendu » part vraiment (la
   mention dans la carte V2, seul le fondateur pingé). R3 un autre site ne déconnecte plus de force.
   R4 « Fermer toutes mes sessions » ; une session effacée en base est coupée en moins d'une minute.
   R5 « Rouvrir » une question la rend vraiment ouverte. R6 l'activité par jour suit le changement
   d'heure du 25/10. R7 un faux cookie ne touche pas la base et compte comme un essai. R8 /health et
   /stats ne disent jamais le texte d'une exception. R9 le journal garde chaque suppression."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite
import discord
from discord.ui import Button

import health_server
import questions
import registre
import tableau
import unified_logger as UL
import visuels
from conftest_discord import Obj
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION, PROPRIO = 781205382923288593, 827633340797681714, 99
ORIGINE = {"X-Tableau": "1", "Origin": "https://bot.exemple", "Sec-Fetch-Site": "same-origin"}


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom:
            return ast.unparse(n)
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets):
            return ast.unparse(n)
    raise KeyError(nom)


def _membre(uid):
    return Obj(id=uid, roles=[], display_name=f"M{uid}", name=f"m{uid}", bot=False, joined_at=None,
               mention=f"<@{uid}>",
               display_avatar=Obj(with_size=lambda n: Obj(url=f"https://cdn.discordapp.com/a/{uid}.png")))


def _base(chemin, compteur=None):
    @contextlib.asynccontextmanager
    async def get_db():
        if compteur is not None:
            compteur.append(1)
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


class Requete:
    """Une requête du navigateur, telle que le site la voit."""

    def __init__(self, jeton="", cookie=None, entetes=None, query=None, ip="1.2.3.4"):
        self.match_info = {"jeton": jeton}
        self.cookies = {tableau.COOKIE: cookie} if cookie else {}
        self.headers = dict(entetes or {})
        self.query = dict(query or {})
        self.content_length = 0
        self.remote, self.scheme, self.host = ip, "https", "bot.exemple"


class Site:
    """Le site branché comme dans bot.py : la VRAIE `_a_la_tete` décide qui entre et qui agit ; le
    propriétaire du serveur (99) n'est pas à la tête."""

    def __init__(self, tmp_path):
        self.connexions = []
        self.get_db = get_db = _base(tmp_path / "site.db", self.connexions)

        async def cfg(_g):
            return {}
        ns = {"TETE_IDS": frozenset({FONDATEUR, DIRECTION})}
        exec(_source("_a_la_tete"), ns)  # noqa: S102 — code du dépôt
        self.a_la_tete = ns["_a_la_tete"]
        self.membres = {u: _membre(u) for u in (FONDATEUR, DIRECTION, PROPRIO, 7)}
        self.g = Obj(id=1, name="GoRP SEA", owner_id=PROPRIO, get_member=self.membres.get,
                     members=list(self.membres.values()), roles=[], get_channel=lambda i: None,
                     get_thread=lambda i: None)
        registre.setup(get_db=get_db, log=lambda *a: None)
        registre._derniers.clear()
        tableau.setup(bot=Obj(get_guild=lambda gid: self.g if gid == 1 else None, user=Obj(id=999)), cle="k",
                      base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=None,
                      autorise_membre=self.a_la_tete, direction=self.a_la_tete, tete=ns["TETE_IDS"],
                      log=lambda *a: None)

        async def preparer():
            await registre.init_db()
            await tableau.init_db()
        asyncio.run(preparer())

    def session(self, uid: int) -> str:
        r = asyncio.run(tableau.entree(Requete(tableau.jeton(1, uid, "tout"))))
        assert r.status == 303, r.status
        return r.cookies[tableau.COOKIE].value


def test_R1_le_site_n_est_qu_aux_deux_comptes_de_la_tete(tmp_path):
    site = Site(tmp_path)
    tete = site.a_la_tete
    assert tete(site.g, site.membres[FONDATEUR]) and tete(site.g, site.membres[DIRECTION])
    assert not tete(site.g, site.membres[PROPRIO]), "le propriétaire d'un serveur n'est pas « à la tête »"
    assert not tete(None, site.membres[FONDATEUR]) and not tete(site.g, None)
    assert tableau.a_la_tete(site.g, DIRECTION) and not tableau.a_la_tete(site.g, PROPRIO)

    async def scenario():
        refus = await tableau.lien_pour(Obj(guild=site.g, user=site.membres[PROPRIO]))
        entree = await tableau.entree(Requete(tableau.jeton(1, PROPRIO, "tout")))
        ok = await tableau.lien_pour(Obj(guild=site.g, user=site.membres[DIRECTION]))
        return refus, entree, ok
    (url, raison), entree, (url_tete, _r) = asyncio.run(scenario())
    assert url is None and raison == "Réservé au fondateur et à la direction."
    assert entree.status == 403, "même avec un lien signé, le propriétaire d'un serveur n'entre pas"
    assert url_tete and url_tete.startswith("https://bot.exemple/tableau/")
    #  Le vrai câblage : la même fonction pour entrer et pour agir.
    assert "autorise_membre=_a_la_tete," in SRC and "direction=_a_la_tete, tete=TETE_IDS," in SRC


def test_R1b_l_export_des_erreurs_ne_sort_jamais_celles_des_autres_serveurs(tmp_path):
    site = Site(tmp_path)

    async def scenario():
        async with site.get_db() as db:
            await db.execute("CREATE TABLE error_log (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER DEFAULT 0,"
                             " source TEXT NOT NULL, error_type TEXT, message TEXT, traceback TEXT,"
                             " context_jsonb TEXT DEFAULT '{}', occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            await db.executemany("INSERT INTO error_log (guild_id, source, error_type, message) VALUES (?,?,?,?)",
                                 [(1, "ici", "E", "erreur de ce serveur"), (0, "boucle", "E", "erreur du bot entier"),
                                  (2, "ailleurs", "E", "erreur d'un autre serveur")])
            await db.commit()
        return [await tableau.exporter(site.g, "erreurs", site.membres[u], format_="json")
                for u in (DIRECTION, FONDATEUR, PROPRIO)]
    direction, fondateur, proprio = asyncio.run(scenario())

    def sources(res):
        return sorted(x["Source"] for x in json.loads(res[0]))
    assert sources(direction) == ["ici"], "la direction : les erreurs de ce serveur seulement"
    assert sources(fondateur) == ["boucle", "ici"], "le fondateur : celles du bot entier en plus"
    assert proprio is None, "le propriétaire d'un serveur n'exporte rien"


def _textes(composants) -> str:
    out = []
    for c in composants or []:
        if isinstance(c.get("content"), str):
            out.append(c["content"])
        out.append(_textes(c.get("components")))
    return "\n".join(x for x in out if x)


def _ids(composants) -> list:
    out = []
    for c in composants or []:
        out += ([c["custom_id"]] if c.get("custom_id") else []) + _ids(c.get("components"))
    return out


def test_R2_l_alerte_du_site_part_vraiment_et_ne_pingue_que_le_fondateur():
    envois, refus = [], []
    v2 = discord.MessageFlags(components_v2=True).value

    class Salon:
        async def send(self, content=None, **kw):
            if content is not None:
                kw["content"] = content
            p = discord.http.handle_message_parameters(**kw).payload  # la requête que discord.py enverrait
            if p.get("flags", 0) & v2 and (p.get("content") or p.get("embeds")):
                refus.append(p)  # ce que Discord répond : 400, « content » interdit avec IS_COMPONENTS_V2
                raise discord.HTTPException(Obj(status=400, reason="Bad Request"),
                                            {"code": 50035, "message": "Invalid Form Body"})
            envois.append(p)
    salon = Salon()

    async def salon_alertes(_g):
        return salon
    ns = {"discord": discord, "Button": Button, "visuels": visuels, "LayoutView": LayoutView, "Palette": Palette,
          "_salon_alertes_site": salon_alertes, "owner_ids_module": Obj(is_super_owner=lambda u: u == FONDATEUR)}
    for nom in ("BoutonGere", "_alerte_securite_site"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1, owner_id=FONDATEUR)

    async def scenario():
        await ns["_alerte_securite_site"](g, _membre(DIRECTION), "6 actions graves (exclusion) en moins de 10 minutes",
                                          suspendu=False)
        await ns["_alerte_securite_site"](g, _membre(7), "6 actions graves (exclusion) en moins de 10 minutes")
        await ns["_alerte_securite_site"](g, _membre(FONDATEUR), "ses propres actions")
    asyncio.run(scenario())
    assert not refus, "plus de content= à côté d'une carte V2 : Discord ne refuse plus l'alerte"
    assert len(envois) == 2, "deux alertes parties ; le fondateur n'est pas alerté de ses propres actions"
    for p in envois:
        assert "content" not in p and p["flags"] & v2
        assert f"<@{FONDATEUR}>" in _textes(p["components"]), "la mention est dans la carte"
        assert p["allowed_mentions"]["parse"] == [] and p["allowed_mentions"]["users"] == [FONDATEUR], \
            "seul le fondateur est pingé — pas la personne signalée"
    assert "Beaucoup d'actions graves" in _textes(envois[0]["components"]) and f"<@{DIRECTION}>" in _textes(envois[0]["components"])
    assert "Accès au site suspendu une heure" in _textes(envois[1]["components"])
    assert all(_ids(p["components"]) == ["alerte:gere:0"] for p in envois), "le bouton « Géré » reste sous l'alerte"


def test_R3_un_autre_site_ne_deconnecte_plus_de_force(tmp_path):
    site = Site(tmp_path)
    sid = site.session(DIRECTION)

    async def scenario():
        croise = await tableau.sortir(Requete(cookie=sid, entetes={"Sec-Fetch-Site": "cross-site",
                                                                   "Origin": "https://pirate.exemple"}))
        formulaire = await tableau.sortir(Requete(cookie=sid))  # un <form> ailleurs : pas d'en-tête maison
        toujours = await tableau.page(Requete(cookie=sid))
        vrai = await tableau.sortir(Requete(cookie=sid, entetes=ORIGINE))
        apres = await tableau.page(Requete(cookie=sid))
        return croise, formulaire, toujours, vrai, apres
    croise, formulaire, toujours, vrai, apres = asyncio.run(scenario())
    for r in (croise, formulaire):
        assert r.status == 400 and tableau.COOKIE not in r.cookies, "ni session effacée, ni cookie touché"
    assert toujours.status == 200
    assert vrai.status == 204 and vrai.cookies[tableau.COOKIE].value == "", "depuis la page : déconnecté"
    assert apres.status == 403


def test_R4_fermer_toutes_mes_sessions_et_session_relue_en_base(tmp_path):
    site = Site(tmp_path)
    a, b, autre = site.session(DIRECTION), site.session(DIRECTION), site.session(FONDATEUR)

    async def scenario():
        avant = [(await tableau.page(Requete(cookie=x))).status for x in (a, b, autre)]
        sans_origine = await tableau.sortir(Requete(cookie=a, query={"partout": "1"}))
        tout = await tableau.sortir(Requete(cookie=a, entetes=ORIGINE, query={"partout": "1"}))
        apres = [(await tableau.page(Requete(cookie=x))).status for x in (a, b, autre)]
        encore = await tableau.sortir(Requete(cookie=a, entetes=ORIGINE, query={"partout": "1"}))
        return avant, sans_origine, tout, apres, encore, await registre.lire(1)
    avant, sans_origine, tout, apres, encore, journal = asyncio.run(scenario())
    assert avant == [200, 200, 200]
    assert sans_origine.status == 400, "une écriture comme les autres : X-Tableau et origine"
    assert tout.status == 200 and json.loads(tout.text)["ok"] and tout.cookies[tableau.COOKIE].value == ""
    assert apres == [403, 403, 200], "ses deux navigateurs coupés sur-le-champ, pas ceux de l'autre compte"
    assert encore.status == 403 and not json.loads(encore.text)["ok"], "plus de session : rien n'est promis"
    assert journal[0]["type"] == "site.sessions_fermees" and journal[0]["auteur_id"] == DIRECTION
    assert journal[0]["detail"] == "2 session(s) fermée(s)"

    #  Une session effacée de la base ailleurs (un autre processus, un nettoyage) : coupée en moins
    #  d'une minute, au lieu de vivre jusqu'au redémarrage dans le cache.
    t = time.time()

    async def relue():
        async with site.get_db() as db:
            await db.execute("DELETE FROM tableau_sessions WHERE user_id=?", (FONDATEUR,))
            await db.commit()
        return (await tableau._session(Requete(cookie=autre), t + 1),
                await tableau._session(Requete(cookie=autre), t + tableau.RELIRE + 1))
    tout_de_suite, plus_tard = asyncio.run(relue())
    assert tout_de_suite is not None and plus_tard is None
    page = tableau.PAGE
    assert 'fetch(BASE + "/sortir?partout=1"' in page and '"X-Tableau": "1"' in page
    assert "Fermer toutes mes sessions" in page and "onclick: fermerPartout" in page
    expire = page[page.index("function expire("):page.index("/* ── Chargement")]
    assert '$("#pied").replaceChildren();' in expire, "une session finie n'affiche plus « Session personnelle jusqu'au… »"


def test_R5_rouvrir_une_question_la_rend_vraiment_ouverte(tmp_path):
    questions.setup(get_db=_base(tmp_path / "q.db"), est_staff=lambda g, m, c: m.id in {2, 3}, log=lambda *a: None)
    asyncio.run(questions.init_db())
    g = Obj(id=1, default_role=Obj(id=1))
    salon = Obj(id=10, guild=g, is_nsfw=lambda: False,
                permissions_for=lambda r: Obj(view_channel=True, send_messages=True, send_messages_in_threads=True))
    n = [100]

    def msg(auteur, texte):
        n[0] += 1
        return Obj(id=n[0], guild=g, author=auteur, channel=salon, content=texte, reference=None, raw_mentions=[],
                   mentions=[], webhook_id=None, jump_url=f"https://discord.com/channels/1/10/{n[0]}")
    kolax, staff, autre_staff = (Obj(id=u, bot=False, roles=[]) for u in (7, 2, 3))
    t0 = 2_000_000_000

    async def scenario():
        await questions.sur_message(msg(kolax, "Comment on rejoint le clan Rell Seas ?"), {}, t0)
        await questions.sur_message(msg(staff, "Ouvre un ticket dans le salon des tickets"), {}, t0 + 60)
        repondue = (await questions.lister(1, t0 + 70))["liste"][0]
        ok = await questions.marquer(1, repondue["id"], "ouverte", 3, t0 + 100)
        rouverte = (await questions.lister(1, t0 + 110))["liste"][0]
        fait = await questions.sur_message(msg(autre_staff, "Je complète : le lien est dans l'annonce"), {}, t0 + 200)
        return repondue, ok, rouverte, fait, (await questions.lister(1, t0 + 210))["liste"][0]
    repondue, ok, rouverte, fait, fin = asyncio.run(scenario())
    assert repondue["statut"] == "repondue" and repondue["par_staff"] == 1 and repondue["lien"]
    assert ok and rouverte["statut"] == "ouverte"
    assert (rouverte["repondu_par"], rouverte["repondu_le"], rouverte["par_staff"], rouverte["lien"]) == (0, 0, 0, ""), \
        "plus de « par X » ni d'ancien lien sur une question ouverte"
    assert fait == "reponse", "la réponse suivante du staff la ferme de nouveau"
    assert (fin["statut"], fin["repondu_par"], fin["par_staff"]) == ("repondue", 3, 1)
    #  L'action du site (bot.py) : le journal dit ce qui a été fait.
    journal = []

    async def au_journal(_g, _cat, type_, texte, **kw):
        journal.append((type_, texte))
    ns = {"questions": questions, "_au_journal": au_journal}
    exec(_source("_action_question"), ns)  # noqa: S102 — code du dépôt
    chef = Obj(id=3, display_name="Chef")
    reps = [asyncio.run(ns["_action_question"](Obj(id=1), chef, {"question": fin["id"], "statut": s}))
            for s in ("ouverte", "traitee", "ignoree", "supprimee")]
    assert [ok for ok, _m in reps] == [True, True, True, False]
    assert journal == [("question.ouverte", "Question rouverte par Chef"),
                       ("question.traitee", "Question marquée traitée par Chef"),
                       ("question.ignoree", "Question retirée (pas une question) par Chef")]


def test_R6_l_activite_par_jour_suit_le_changement_d_heure(tmp_path, monkeypatch):
    registre.setup(get_db=_base(tmp_path / "r.db"), log=lambda *a: None)
    asyncio.run(registre.init_db())

    def utc(s):
        return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
    evenements = [("2026-10-23T22:30:00", "Membres"),   # 24/10 00 h 30, heure d'été
                  ("2026-10-24T21:59:00", "Membres"),   # 24/10 23 h 59
                  ("2026-10-24T22:00:00", "Tickets"),   # 25/10 00 h 00
                  ("2026-10-25T00:30:00", "Tickets"),   # 25/10 02 h 30, avant le retour à l'heure d'hiver
                  ("2026-10-25T01:30:00", "Tickets"),   # 25/10 02 h 30, après
                  ("2026-10-25T22:59:00", "Tickets"),   # 25/10 23 h 59, heure d'hiver
                  ("2026-10-25T23:00:00", "Membres"),   # 26/10 00 h 00
                  ("2026-10-25T23:30:00", "Membres")]   # 26/10 00 h 30

    async def scenario():
        async with registre._get_db() as db:
            await db.executemany("INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (1,?,?,'x','x')",
                                 [(utc(q), cat) for q, cat in evenements])
            await db.commit()
        return await registre.par_jour(1, 30, ZoneInfo("Europe/Paris"), maintenant=utc("2026-10-27T12:00:00"))
    assert asyncio.run(scenario()) == {"2026-10-24": {"Membres": 2}, "2026-10-25": {"Tickets": 4},
                                       "2026-10-26": {"Membres": 2}}, "chaque jour coupé à SON minuit, heure de Paris"
    #  Le site passe le fuseau de Paris, plus un décalage calculé le jour même.
    vus = []

    async def par_jour(gid, jours, fuseau=None, maintenant=None):
        vus.append(fuseau)
        return {}

    async def lire(*a, **k):
        return []
    monkeypatch.setattr(registre, "par_jour", par_jour)
    monkeypatch.setattr(registre, "lire", lire)
    asyncio.run(tableau._journal(Obj(id=1), tableau._Personnes(Obj(id=1))))
    assert vus == [tableau.PARIS] and str(tableau.PARIS) == "Europe/Paris"


def test_R7_un_faux_cookie_ne_touche_pas_la_base_et_compte_comme_un_essai(tmp_path):
    site = Site(tmp_path)
    sid = site.session(DIRECTION)
    tableau._essais.clear()

    async def scenario():
        assert (await tableau.page(Requete(cookie=sid))).status == 200
        avant = len(site.connexions)
        mal_formes = [await tableau.page(Requete(cookie=c)) for c in ("x", "y" * 42, "z" * 44, "é" * 43, "a b" * 15)]
        sans_base = len(site.connexions) == avant
        statuts, lectures = [], []
        for _ in range(40):
            avant = len(site.connexions)
            statuts.append((await tableau.api(Requete(cookie=secrets.token_urlsafe(32)))).status)
            lectures.append(len(site.connexions) - avant)
        ailleurs = len(site.connexions)
        autre_adresse = await tableau.page(Requete(cookie=secrets.token_urlsafe(32), ip="5.6.7.8"))
        ailleurs = len(site.connexions) - ailleurs
        legitime = await tableau.page(Requete(cookie=sid))
        return mal_formes, sans_base, statuts, lectures, autre_adresse, ailleurs, legitime
    mal_formes, sans_base, statuts, lectures, autre_adresse, ailleurs, legitime = asyncio.run(scenario())
    assert [r.status for r in mal_formes] == [403] * 5 and sans_base, "un cookie mal formé ne touche jamais la base"
    assert sum(lectures) == tableau.LIMITE_ESSAIS + 1 - 5, "les faux cookies comptent comme des essais ratés"
    assert set(statuts) == {403, 429} and statuts[-1] == 429 and lectures[-10:] == [0] * 10, \
        "adresse bloquée : plus aucune lecture en base"
    assert autre_adresse.status == 403 and ailleurs == 1, "une autre adresse n'est pas punie"
    assert legitime.status == 200, "une session ouverte, déjà en mémoire, continue de marcher"
    tableau._essais.clear()


def test_R8_health_et_stats_ne_disent_jamais_le_texte_d_une_exception(monkeypatch, capsys):
    monkeypatch.setattr(health_server, "_started_at", "pas une heure")  # time.time() - str : TypeError
    for handler in (health_server._health_handler, health_server._stats_handler):
        r = asyncio.run(handler(None))
        assert r.status == 500 and json.loads(r.text) == {"status": "error", "error": "erreur interne"}
    sortie = capsys.readouterr().out
    assert "[HEALTH][E2] /health en échec\n" in sortie and "[HEALTH][E3] /stats en échec\n" in sortie
    assert "TypeError" in sortie, "le détail part au journal du bot"


def test_R9_le_journal_garde_chaque_suppression_et_son_contenu(tmp_path, monkeypatch):
    registre.setup(get_db=_base(tmp_path / "r.db"), log=lambda *a: None)
    registre._derniers.clear()
    asyncio.run(registre.init_db())
    monkeypatch.setattr(UL, "DATA_DIR", tmp_path)
    auteur = Obj(id=7, display_name="Kolax", mention="<@7>", bot=False, roles=[], name="kolax")
    salon = Obj(id=5, name="général", mention="<#5>")
    g = Obj(id=1, get_member={7: auteur}.get, get_channel={5: salon}.get, icon=None, name="S")

    async def scenario():
        await UL.activer_site(1, 77)
        for texte in ("première preuve", "deuxième preuve", "troisième preuve", "troisième preuve"):
            await UL.log_message_delete(Obj(get_channel=lambda cid: None), g,
                                        Obj(author=auteur, channel=salon, content=texte))
        return await registre.lire(1)
    lignes = asyncio.run(scenario())
    assert [x["detail"] for x in lignes] == ["troisième preuve", "deuxième preuve", "première preuve"], \
        "chaque suppression garde son contenu ; un vrai doublon (même phrase, même contenu) reste écarté"
    assert len({x["texte"] for x in lignes}) == 1, "la même phrase pour les trois : c'est le détail qui les distingue"
