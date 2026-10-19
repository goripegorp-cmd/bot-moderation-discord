"""19/10/2026 (soir) : « il n'y aura qu'un seul salon, qui mettra le lien correctement… il n'y aura
plus de logs sur le serveur Discord, ce sera envoyé sur le site, traduit correctement par
personne… ça filtrera les logs inutiles… qui nettoie bien correctement, qui soit bien optimisé »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import discord

import data_cleanup
import gdpr
import nettoyage
import questions
import recrutements
import registre
import rellseas_panneau
import tableau
import unified_logger as UL
import vigilance
import visuels
from conftest_discord import Obj
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom:
            return ast.unparse(n)
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets):
            return ast.unparse(n)
    raise KeyError(nom)


def _registre(tmp_path):
    chemin = tmp_path / "r.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    registre.setup(get_db=get_db, log=lambda *a: None)
    registre._derniers.clear()
    asyncio.run(registre.init_db())
    return get_db


class Salon(discord.TextChannel):
    """Un salon texte, sans passer par l'état de Discord."""

    def __init__(self, sid, nom, categorie=None, pur=True):
        self.id, self.name, self._categorie, self.pur = sid, nom, categorie, pur
        self.supprime, self.renomme = False, None

    @property
    def category(self):
        return self._categorie

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def delete(self, reason=None):
        self.supprime = True
        if self._categorie is not None:
            self._categorie.channels.remove(self)

    async def edit(self, name=None, reason=None):
        self.renomme = name


def test_L1_une_phrase_par_evenement_sans_bruit(tmp_path):
    _registre(tmp_path)
    g = Obj(get_member={7: Obj(display_name="Kolax")}.get, get_channel={5: Obj(name="général")}.get)
    assert registre.propre("**Ban** de <@7> dans <#5> · <@&9> <t:1700000000:R> `x`", g) == \
        "Ban de @Kolax dans #général · @rôle x"

    async def scenario():
        faits = (await registre.noter(1, "Modération", "mod.warn", "Avertissement de Kolax", membre_id=7, auteur_id=2),
                 await registre.noter(1, "Modération", "mod.warn", "Avertissement de Kolax", membre_id=7, auteur_id=2),
                 await registre.noter(1, "Vocal", "voice.mute", "Micro coupé", membre_id=7),
                 await registre.noter(1, "Tickets", "ticket.close", "Ticket #3 fermé", membre_id=8, auteur_id=7),
                 await registre.noter(1, "Membres", "member.join", "Arrivée de Mira", membre_id=8),
                 await registre.noter(2, "Membres", "member.join", "Autre serveur", membre_id=7))
        return faits, await registre.lire(1), await registre.lire(1, membre_id=7)
    faits, tout, kolax = asyncio.run(scenario())
    assert faits == (True, False, False, True, True, True), "doublon à 5 s et bruit écartés"
    assert [x["type"] for x in tout] == ["member.join", "ticket.close", "mod.warn"], "du plus récent, ce serveur"
    assert [x["type"] for x in kolax] == ["ticket.close", "mod.warn"], "ce qui le concerne ET ce qu'il a fait"


def test_L2_le_journal_se_nettoie_seul(tmp_path, monkeypatch):
    get_db = _registre(tmp_path)
    maintenant, jour = 2_000_000_000, 86400

    async def textes():
        async with get_db() as db:
            async with db.execute("SELECT texte FROM registre ORDER BY id") as cur:
                return [r[0] for r in await cur.fetchall()]

    async def scenario():
        async with get_db() as db:
            await db.executemany("INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (1,?,?,?,?)", [
                (maintenant - 31 * jour, "Messages", "message.delete", "vieux message"),
                (maintenant - 29 * jour, "Messages", "message.delete", "message récent"),
                (maintenant - 31 * jour, "Vocal", "voice.join", "vieux vocal"),
                (maintenant - 60 * jour, "Modération", "mod.warn", "avertissement de 60 j"),
                (maintenant - 91 * jour, "Modération", "mod.ban", "ban de 91 j")])
            await db.commit()
        n = await registre.purger(maintenant)
        restes = await textes()
        async with get_db() as db:
            await db.executemany("INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (1,?,?,?,?)",
                                 [(maintenant, "Membres", "member.join", f"arrivée {k}") for k in range(5)])
            await db.execute(registre.PURGES[2][1].replace(str(registre.PLAFOND), "3"))
            await db.commit()
        plafond = await textes()
        async with get_db() as db:
            await db.execute("DELETE FROM registre")
            await db.execute("INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (1, 1, 'Modération',"
                             " 'mod.warn', 'très vieux')")
            await db.commit()
        monkeypatch.setattr(registre, "PURGE_TOUTES", 2)
        monkeypatch.setattr(registre, "_ecritures", 0)
        await registre.noter(1, "Membres", "member.join", "un", membre_id=1)
        avant = await textes()
        await registre.noter(1, "Membres", "member.join", "deux", membre_id=2)
        return n, restes, plafond, avant, await textes()
    n, restes, plafond, avant, apres = asyncio.run(scenario())
    assert n == 3 and restes == ["message récent", "avertissement de 60 j"], "messages et vocal 30 j, le reste 90 j"
    assert plafond == ["arrivée 2", "arrivée 3", "arrivée 4"], "au-delà du plafond, les plus anciennes partent"
    assert "très vieux" in avant and apres == ["un", "deux"], "le journal se purge seul en écrivant"
    assert all(p in data_cleanup.PURGES_CIBLEES for p in registre.PURGES), "et chaque semaine"
    assert gdpr.DELETE_SUBJECT_KEEP_ACTOR["registre"] == {"subject": ["membre_id"], "actor": ["auteur_id"]}
    assert gdpr.RETENTION["registre"] == ("quand", 90)


def test_L3_en_mode_site_rien_sur_discord_sauf_les_alertes(tmp_path, monkeypatch):
    _registre(tmp_path)
    monkeypatch.setattr(UL, "DATA_DIR", tmp_path)
    envois = []

    class Cible:
        id = 77

        async def send(self, **kw):
            envois.append(kw)
            return Obj(id=1, channel=self)
    cible = Cible()
    bot = Obj(get_channel=lambda cid: cible if cid == 77 else None)
    membre = Obj(id=7, display_name="Kolax", mention="<@7>", bot=False, roles=[], name="kolax")
    g = Obj(id=1, get_member={7: membre}.get, get_channel=lambda i: None, icon=None, name="S")
    (tmp_path / "1.json").write_text(json.dumps({"channel_id": 55, "category_channels": {"Membres": 56},
                                                 "event_channels": {"mod.warn": 57}}), encoding="utf-8")

    async def scenario():
        anciens = await UL.activer_site(1, 77)
        await UL.log_event(bot, g, UL.EventType.MEMBER_JOIN, description="Arrivée de <@7>", user=membre)
        await UL.log_event(bot, g, UL.EventType.SEC_ESCALATION, description="Palier critique", user=membre)
        await UL.set_disabled_events(1, {"member.join"})
        registre._derniers.clear()
        await UL.log_event(bot, g, UL.EventType.MEMBER_JOIN, description="Retour de <@7>", user=membre)
        site = await UL.mode_site(1), UL.salons_de_logs(1)
        await UL.set_log_channel(1, 88)
        return anciens, site, await UL.mode_site(1), await registre.lire(1)
    anciens, (site, salons), apres, lignes = asyncio.run(scenario())
    assert anciens == {55, 56, 57} and site and salons == set(), "plus aucun salon de logs"
    assert len(envois) == 1 and envois[0]["embed"].description == "Palier critique", "seule l'alerte part"
    assert [x["type"] for x in lignes] == ["sec.escalation", "member.join"], "un évènement désactivé n'est pas noté"
    assert lignes[1]["texte"] == "Arrivée · Arrivée de @Kolax" or "Kolax" in lignes[1]["texte"]
    assert lignes[1]["membre_id"] == 7
    assert apres is True, "choisir un salon ne remet pas les logs sur Discord : le mode a son propre réglage"


def test_L4_passage_au_site_une_fois_alertes_au_salon_unique(tmp_path):
    cat = Obj(name="📁 LOGS", channels=[])
    salons = {s.id: s for s in (Salon(55, "logs"), Salon(56, "logs-membres"), Salon(61, "logs-tickets", cat),
                                Salon(62, "staff-discussion", pur=False), Salon(63, "logs-spam"),
                                Salon(64, "journal-clan"), Salon(65, "logs-sondages"), Salon(66, "piege"))}
    unique = Salon(77, "📊tableau-de-bord")
    salons[77] = unique
    conf = {"tableau_salon": 77, "ticket_log": 61, "mod_log_channel": 62, "log_anti_spam": 63, "log_anti_raid": 0,
            "log_anti_alt": 0, "rellseas_log_channel": 64, "logs_salon_sondages": 65, "honeypot_channel_id": 66,
            rellseas_panneau.CLE_SALON_TRANSCRIPTS: 0, "staff_sanction_channel_id": 0}
    journal, menus = [], []

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v

    async def tableau_salon(_g):
        menus.append(1)
        return unique

    async def activer_site(gid, alertes):
        journal.append(("activer", alertes))
        return {55, 56}

    async def pur(ch):
        return ch.pur

    async def au_journal(_g, cat_, type_, texte, **kw):
        journal.append((cat_, type_, texte))
    g = Obj(id=1, get_channel=salons.get)
    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "_salon_tableau": tableau_salon,
          "ulogger2026": Obj(activer_site=activer_site), "rellseas_ui": rellseas_panneau,
          "_salon_de_logs_pur": pur, "_au_journal": au_journal, "_logerr": lambda *a, **k: None,
          "now": lambda: datetime(2026, 10, 19, 21, 0, tzinfo=timezone.utc)}
    for nom in ("NOM_SALON_LOGS", "CLES_ALERTES", "_passer_logs_sur_site"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    assert asyncio.run(ns["_passer_logs_sur_site"](g)) is True
    assert asyncio.run(ns["_passer_logs_sur_site"](g)) is False, "une seule fois"
    assert unique.renomme == "📋logs" and ("activer", 77) in journal
    for k in ns["CLES_ALERTES"]:
        assert conf[k] == 77, f"les alertes de {k} arrivent au salon unique"
    for k in ("ticket_log", "log_anti_spam", "rellseas_log_channel", "logs_salon_sondages"):
        assert conf[k] == 0, f"{k} : plus de salon"
    assert conf["honeypot_channel_id"] == 66, "le piège n'est pas un salon de logs"
    assert conf["logs_anciens_salons"] == [55, 56, 61, 63, 64, 65], "jamais un salon où un membre a écrit"
    assert conf["logs_sur_site_v1"] and len(menus) == 2
    assert not any(s.supprime for s in salons.values()), "rien n'est supprimé sans le fondateur"


def test_L5_suppression_des_anciens_salons_fondateur_et_direction_confirmee():
    cat = Obj(name="📁 LOGS", channels=[])
    a, b, c = Salon(61, "logs-tickets", cat), Salon(63, "logs-spam"), Salon(70, "general")
    cat.channels.append(a)
    salons = {61: a, 63: b, 70: c}
    conf = {"tableau_salon": 77, "logs_anciens_salons": [61, 63]}
    journal, menus, actions, categories = [], [], [], []
    cat.delete = lambda reason=None: categories.append(reason) or asyncio.sleep(0)

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v

    async def pur(ch):
        return ch.pur

    async def tableau_salon(_g):
        menus.append(1)

    async def au_journal(_g, cat_, type_, texte, **kw):
        journal.append((type_, texte, kw.get("auteur_id")))

    async def staff_action(*a, **k):
        actions.append(a)

    async def dormir(_s):
        return None
    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "Button": discord.ui.Button,
          "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels, "_salon_de_logs_pur": pur,
          "_salon_tableau": tableau_salon, "_au_journal": au_journal, "log_staff_action": staff_action,
          "_logerr": lambda *x, **k: None, "asyncio": Obj(sleep=dormir),
          "_direction_ou_plus": lambda g, m, c: m.id in (1, 2)}
    for nom in ("_anciens_salons", "BoutonAnciensSalons", "ConfirmerAnciensSalons"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1, get_channel=salons.get)
    vues, refus = [], []

    def interaction(uid):
        rep = Obj(edit_message=None, send_message=None)

        async def edit_message(**kw):
            vues.append(kw["view"])

        async def send_message(texte, **kw):
            refus.append(texte)
        rep.edit_message, rep.send_message = edit_message, send_message

        async def edit_original_response(**kw):
            vues.append(kw["view"])
        return Obj(guild=g, user=Obj(id=uid, __str__=lambda: "x"), response=rep,
                   edit_original_response=edit_original_response)

    async def scenario():
        bouton = ns["BoutonAnciensSalons"](2)
        assert bouton.item.label == "Supprimer les anciens salons de logs (2)"
        await bouton.callback(interaction(9))
        vue = ns["ConfirmerAnciensSalons"](1, [a, b])
        b.pur = False  # un membre y a écrit depuis
        vue.choix = [61, 63, 70]
        await vue._supprimer(interaction(9))
        await vue._supprimer(interaction(1))
    asyncio.run(scenario())
    assert refus == ["Réservé au fondateur et à la direction.", "Réservé au fondateur et à la direction."]
    assert a.supprime and not b.supprime and not c.supprime, "seulement les salons proposés, encore purs"
    assert categories, "la catégorie de logs vide part avec"
    fin = " ".join(x.content for x in vues[-1].walk_children() if isinstance(x, discord.ui.TextDisplay))
    assert fin.startswith("1 salon(s) supprimé(s).") and "2 non supprimé(s)" in fin
    assert conf["logs_anciens_salons"] == [] and menus, "le bouton disparaît du menu"
    assert journal == [("logs.anciens", "Anciens salons de logs supprimés (1) : #logs-tickets", 1)]
    assert actions and actions[0][3] == "logs_anciens_supprimes"


def test_L6_le_site_lit_tout_ce_qui_concerne_une_personne(tmp_path):
    get_db = _registre(tmp_path)
    kolax = Obj(id=7, display_name="Kolax", name="kolax", roles=[], guild_permissions=Obj(administrator=True), bot=False,
                display_avatar=Obj(with_size=lambda n: Obj(url="https://cdn.discordapp.com/a/7.png")))
    g = Obj(id=1, owner_id=99, members=[kolax], get_member={7: kolax}.get, get_channel={5: Obj(name="général")}.get,
            get_thread=lambda i: None, get_role=lambda i: None, me=None)

    async def cfg(_g):
        return {}

    async def rien(*_a, **_k):
        return None
    tableau.setup(bot=Obj(get_guild=lambda gid: g if gid == 1 else None, user=Obj(id=999)), cle="cle",
                  base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=None,
                  autorise_membre=lambda g_, m, c: m is not None, log=lambda *a: None)
    recrutements.setup(get_db=get_db, cfg=cfg, db_set=rien, salon=None, role=lambda *a: None,
                       panneaux=rellseas_panneau.panneaux_tickets, log=lambda *a: None)
    questions.setup(get_db=get_db, est_staff=lambda *a: False, log=lambda *a: None)
    vigilance.setup(get_db=get_db, salon=rien, carte=lambda *a: None, log=lambda *a: None)

    class Requete:
        def __init__(self, jeton="", cookie=None, query=None):
            self.match_info, self.query, self.headers, self.remote = {"jeton": jeton}, dict(query or {}), {}, "1.2.3.4"
            self.cookies = {tableau.COOKIE: cookie} if cookie else {}

    async def scenario():
        for f in (tableau.init_db, recrutements.init_db, questions.init_db, vigilance.init_db):
            await f()
        await registre.noter(1, "Modération", "mod.warn", "Avertissement de Kolax", membre_id=7, auteur_id=2,
                             salon_id=5, detail="spam")
        await registre.noter(1, "Membres", "member.join", "Arrivée de Mira", membre_id=8)
        entree = await tableau.entree(Requete(tableau.jeton(1, 7, "tout")))
        sid = entree.cookies[tableau.COOKIE].value
        return (await tableau.membre(Requete(query={"id": "7"})), await tableau.membre(Requete(cookie=sid, query={"id": "7; DROP"})),
                await tableau.membre(Requete(cookie=sid, query={"id": "7"})))
    expire, invalide, ok = asyncio.run(scenario())
    assert (expire.status, invalide.status, ok.status) == (403, 400, 200)
    corps = json.loads(ok.body)
    assert corps["membre"]["nom"] == "Kolax" and [e["type"] for e in corps["journal"]] == ["site.ouvert", "mod.warn"],         "ce qui le concerne ET ce qu'il a fait (il a ouvert le site)"
    e = corps["journal"][1]
    assert (e["membre"], e["auteur"], e["salon"], e["detail"]) == ("7", "2", "#général", "spam")
    assert corps["personnes"]["2"]["nom"] == "Membre parti" and corps["personnes"]["7"]["nom"] == "Kolax"
    assert not corps["agir"], "sans rôle direction réglé, personne n'agit depuis le site"
    assert not corps["membre"]["protege"], "protégés : le fondateur et la direction, pas un simple administrateur"
    page = (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert '["journal", "Journal", "journal"]' in page and "/membre?id=" in page and "ouvrirFiche" in page
    assert "/tableau/espace/membre" in (RACINE / "health_server.py").read_text(encoding="utf-8")


def test_L7_les_anciens_envoyeurs_se_taisent_en_mode_site():
    envois, unifies = [], []
    conf = {"mod_log_channel": 77}

    async def cfg(_g):
        return conf

    async def log_event(*a, **k):
        unifies.append(a[2])

    async def webhook_send(salon, *a, **k):
        envois.append(salon)
    salon = Obj(id=77)
    cible = Obj(mention="<@7>", id=7, display_avatar=Obj(url="https://x"), __str__=lambda: "k")
    mod = Obj(mention="<@2>", id=2)
    g = Obj(id=1, icon=None, get_channel=lambda cid: salon if cid == 77 else None)
    ns = {"cfg": cfg, "discord": discord, "now": lambda: datetime.now(timezone.utc),
          "webhook_send": webhook_send, "C": Obj(ORANGE=1), "bot": None,
          "ulogger2026": Obj(log_event=log_event, EventType=UL.EventType)}
    exec(_source("send_mod_log"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["send_mod_log"](g, "warn", mod, cible, "spam"))
    assert envois == [salon], "avant le passage au site : le salon des sanctions"
    conf["logs_sur_site_v1"] = "oui"
    asyncio.run(ns["send_mod_log"](g, "warn", mod, cible, "spam"))
    assert envois == [salon] and len(unifies) == 2, "après : au site seulement"

    async def jamais(*_a, **_k):
        raise AssertionError("aucun salon ne se crée en mode site")
    ns2 = {"cfg": cfg, "discord": discord, "ulogger2026": Obj(get_log_channel=jamais), "db_set": jamais,
           "_logerr": lambda *a, **k: None}
    exec(_source("_salon_logs_dedie"), ns2)  # noqa: S102 — code du dépôt
    assert asyncio.run(ns2["_salon_logs_dedie"](Obj(id=1, get_channel=lambda i: None), "sondages", "x")) is None


def test_L8_le_menu_epingle_n_est_jamais_purge():
    vieux = datetime(2026, 8, 1, tzinfo=timezone.utc)
    supprimes = []

    def msg(auteur, epingle):
        m = Obj(author=Obj(id=auteur), webhook_id=None, pinned=epingle, created_at=vieux)

        async def delete():
            supprimes.append(m)
        m.delete = delete
        return m
    menu, alerte, membre = msg(1, True), msg(1, False), msg(5, False)

    class S:
        def history(self, **_k):
            async def gen():
                for m in (menu, alerte, membre):
                    yield m
            return gen()

    async def scenario():
        import nettoyage as N
        original = N.asyncio.sleep

        async def vite(_s):
            return None
        N.asyncio.sleep = vite
        try:
            return await nettoyage.purger_salon(S(), 1)
        finally:
            N.asyncio.sleep = original
    assert asyncio.run(scenario()) == 1 and supprimes == [alerte]


class _Role(discord.Role):
    """Un rôle du serveur, sans l'état de Discord."""

    def __init__(self, rid, nom, position, managed=False, admin=False):
        self.id, self.name, self.position, self.managed, self._admin = rid, nom, position, managed, admin

    @property
    def permissions(self):
        return Obj(administrator=self._admin)


def test_L9_logs_reserve_au_fondateur_et_a_la_direction():
    """« Le salon Logs n'apparaîtra plus pour les staffs, mais que pour la direction et le fondateur. »"""
    tous, staff, modo = _Role(1, "@everyone", 0), _Role(10, "Staff", 5, admin=True), _Role(12, "Modo", 4)
    direction, haut, robot = _Role(11, "Direction", 8), _Role(13, "Co-fondateur", 9), _Role(14, "Bot", 10, managed=True)
    me, staffeur, chef = Obj(id=500, bot=True), Obj(id=20, bot=False), Obj(id=30, bot=False)
    vue = discord.PermissionOverwrite

    class SalonLogs:
        mention = "<#77>"

        def __init__(self):
            self.overwrites = {tous: vue(view_channel=True), staff: vue(view_channel=True), modo: vue(view_channel=True),
                               direction: vue(view_channel=True), robot: vue(view_channel=True), me: vue(view_channel=True),
                               staffeur: vue(view_channel=True), chef: vue(view_channel=True)}
            self.appels = []

        def overwrites_for(self, cible):
            ow = self.overwrites.get(cible)
            return vue(**dict(ow)) if ow is not None else vue()

        async def set_permissions(self, cible, overwrite=None, reason=None):
            self.appels.append(cible)
            if overwrite is None:
                self.overwrites.pop(cible, None)
            else:
                self.overwrites[cible] = overwrite
    salon = SalonLogs()
    conf, journal = {"tableau_salon": 77, "direction_allowed_role": 11}, []

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v

    async def au_journal(_g, *a, **k):
        journal.append(a)

    async def dormir(_s):
        return None
    g = Obj(id=1, owner_id=99, default_role=tous, me=Obj(id=500, guild_permissions=Obj(manage_roles=True, manage_channels=True)),
            roles=[tous, modo, staff, direction, haut, robot], get_channel=lambda cid: salon if cid == 77 else None,
            get_role={11: direction}.get)
    g.me = me
    me.guild_permissions = Obj(manage_roles=True, manage_channels=True)
    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "asyncio": Obj(sleep=dormir), "_au_journal": au_journal,
          "_logerr": lambda *a, **k: None, "now": lambda: datetime.now(timezone.utc),
          "_direction_ou_plus": lambda _g, m, _c: m.id == 30}
    exec(_source("_logs_direction_seule"), ns)  # noqa: S102 — code du dépôt
    assert asyncio.run(ns["_logs_direction_seule"](g)) is True
    ows = salon.overwrites
    assert staff not in ows and modo not in ows and staffeur not in ows, "le staff ne voit plus 📋logs"
    assert ows[tous].view_channel is False, "@everyone ne voit pas"
    assert ows[direction].view_channel and ows[haut].view_channel, "la direction et au-dessus voient"
    assert robot in ows and me in ows and chef in ows, "le bot, son rôle et la direction gardent leurs droits"
    assert "Staff" in journal[-1][2] and "Administrateur" in journal[-1][2], "un rôle admin sous la direction est signalé"
    appels = len(salon.appels)
    assert asyncio.run(ns["_logs_direction_seule"](g)) is False and len(salon.appels) == appels, "une seule fois"
