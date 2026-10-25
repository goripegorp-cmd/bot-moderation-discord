"""outils/site_local.py — le VRAI site en local, sur http://localhost:8790 (25/10/2026).

Le même serveur que le bot (`health_server.construire_app()` : tableau, affiches, événements s'il est là),
branché sur un FAUX serveur Discord et une base TEMPORAIRE remplie de données de démonstration
(membres, sanctions, tickets, candidatures, clan, journal, questions, sondages, idées, annonces, catalogue,
affiches, rôles des métiers). Rien ne part chez Discord ; seul « portrait Roblox » interroge Roblox.
Les actions du tableau (`/tableau/espace/action`) sont les VRAIES, celles de bot.py : `outils/site_local_port.py`.

⚠️ L'ENTRÉE DE DÉMONSTRATION (`/tableau/demo` : une session SANS lien signé) n'existe QUE dans ce
script. Le bot ne l'expose jamais (`tests/test_site_v2_serveur.py` le vérifie) : ne jamais la copier
ailleurs.

Usage :
    python outils/site_local.py                 → http://localhost:8790/tableau/demo
    python outils/site_local.py --port 8791 --qui direction --garder C:\\chemin\\dossier
Ouvrir par « localhost » (pas 127.0.0.1) : les écritures vérifient l'origine de la page.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import json
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
for _chemin in (RACINE, RACINE / "tests"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import aiosqlite  # noqa: E402
import discord  # noqa: E402

import paths  # noqa: E402

FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
TETE = frozenset({FONDATEUR, DIRECTION})
SERVEUR_ID = 1
PORT = 8790
CATALOGUE_EXEMPLE = RACINE / "tests" / "donnees" / "rell_catalogue_exemple.json"
PRENOMS = ("Kolax", "Mira", "Barbe-Grise", "Anne Bonny", "Calico", "Morgane", "Ishmael", "Tortuga", "Rackham",
           "Salazar", "Hector", "Jade", "Corsaire", "Nemo", "Lysandre", "Océane", "Bastien", "Elio", "Zéphyr", "Ylva",
           "Tobias", "Maëlle", "Rosalind", "Silas")
CATEGORIES_JOURNAL = (("Modération", "mod.warn", 1), ("Modération", "mod.mute", 2), ("Membres", "member.join", 0),
                      ("Membres", "member.leave", 0), ("Messages", "message.delete", 0), ("Vocal", "voice.join", 0),
                      ("Tickets", "ticket.open", 0), ("Tickets", "ticket.close", 0), ("Sécurité", "sec.spam", 1),
                      ("Clan", "clan.journal", 0), ("Site", "site.ouvert", 0))


# ═══════════════════════════════════════════════════════════════════════════════
#  Le faux serveur Discord (assez pour tout ce que le site lit et fait)
# ═══════════════════════════════════════════════════════════════════════════════

def _faux():
    """Les classes du faux serveur, bâties sur `tests/faux_serveur.py` (importé à la demande)."""
    import faux_serveur as F
    from conftest_discord import Obj

    class Role(F.Role):
        def __init__(self, rid, name, position, couleur=0, permissions=None, managed=False):
            super().__init__(rid, name)
            self.position, self.managed = position, managed
            self.colour = self.color = discord.Colour(couleur)
            self.permissions = permissions or discord.Permissions.none()

        def is_default(self):
            return self.position == 0

    class Membre(F.Membre):
        def __init__(self, uid, nom, *roles, arrivee_jours=30, bot=False):
            super().__init__(uid, *roles)
            self.display_name, self.name, self.bot = nom, nom.lower().replace(" ", "_"), bot
            url = f"https://cdn.discordapp.com/embed/avatars/{uid % 6}.png"
            self.display_avatar = Obj(url=url, with_size=lambda _n: Obj(url=url))
            self.joined_at = datetime.now(timezone.utc) - timedelta(days=arrivee_jours)
            self.created_at = self.joined_at - timedelta(days=400)
            self.timed_out_until = None

        @property
        def top_role(self):
            return max(self.roles, key=lambda r: r.position) if self.roles else self.guild.default_role

        def is_timed_out(self):
            return bool(self.timed_out_until and self.timed_out_until > datetime.now(timezone.utc))

        async def add_roles(self, *roles, reason=None):
            for r in roles:
                if r not in self.roles:
                    self.roles.append(r)
                    r.members.append(self)

        async def remove_roles(self, *roles, reason=None):
            for r in roles:
                if r in self.roles:
                    self.roles.remove(r)
                    r.members.remove(self)

    class Serveur(F.Monde):
        def __init__(self):
            super().__init__(forum=False, communautaire=True)
            self.id, self.name, self.icon, self.chunked = SERVEUR_ID, "GoRP SEA", None, True
            for s in self.salons.values():
                if isinstance(s, F.Vocal):  # le vrai `VoiceChannel.permissions_for` lirait `guild`
                    s.permissions_for = lambda _cible: F.Droits()
            self._roles = {}
            self.default_role = Role(SERVEUR_ID, "@everyone", 0)
            self._roles[SERVEUR_ID] = self.default_role
            self.owner_id = FONDATEUR
            self.natifs = {}

        roles = property(lambda self: sorted(self._roles.values(), key=lambda r: r.position),
                         lambda self, v: None)  # Monde y range un dict : sans effet ici

        def get_role(self, rid):
            return self._roles.get(int(rid or 0))

        def role(self, name, position, **kw):
            r = Role(self.nouvel_id(), name, position, **kw)
            self._roles[r.id] = r
            return r

        async def create_role(self, *, name, colour=None, permissions=None, **kw):
            haut = max((r.position for r in self._roles.values() if r.position < 90), default=0)
            r = Role(self.nouvel_id(), name, 1, couleur=getattr(colour, "value", 0) or 0, permissions=permissions)
            for autre in self._roles.values():
                if 0 < autre.position <= haut:
                    autre.position += 1
            self._roles[r.id] = r
            return r

        async def edit_role_positions(self, positions, reason=None):
            """Le rangement des rôles (un rôle de métier se pose juste sous le rôle du clan)."""
            for objet, position in positions.items():
                if int(objet.id) in self._roles:
                    self._roles[int(objet.id)].position = position
            return list(self._roles.values())

        def membre(self, uid, nom, *roles, **kw):
            m = Membre(uid, nom, *roles, **kw)
            m.guild = self
            self.membres[uid] = m
            self.members.append(m)
            return m

        def get_thread(self, tid):
            return self.fils.get(int(tid or 0))

        def by_category(self):
            sortie = []
            for cat in self.categories_:
                salons = sorted((s for s in self.salons.values() if getattr(s, "category_id", None) == cat.id),
                                key=lambda s: s.position)
                sortie.append((cat, salons))
            sans = [s for s in self.salons.values() if getattr(s, "category_id", None) is None]
            return ([(None, sans)] if sans else []) + sortie

        async def fetch_ban(self, objet):
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")

        #  Les évènements programmés de Discord (les événements du clan les créent quand on le demande).
        async def create_scheduled_event(self, **kw):
            ev = EvenementNatif(self.nouvel_id(), kw)
            self.natifs[ev.id] = ev
            return ev

        def get_scheduled_event(self, ident):
            return self.natifs.get(int(ident or 0))

        async def fetch_scheduled_event(self, ident):
            ev = self.natifs.get(int(ident or 0))
            if ev is None:
                raise discord.NotFound(Obj(status=404, reason="x"), "absent")
            return ev

    class EvenementNatif:
        """Un évènement programmé : créé, modifié, démarré, terminé ou annulé avec l'événement du clan."""
        def __init__(self, ident, kw):
            self.id, self.kw, self.status = ident, dict(kw), discord.EventStatus.scheduled

        async def edit(self, **kw):
            self.kw.update(kw)

        async def cancel(self, **_kw):
            self.status = discord.EventStatus.canceled

        async def start(self, **_kw):
            self.status = discord.EventStatus.active

        async def end(self, **_kw):
            self.status = discord.EventStatus.completed

    return Obj(Role=Role, Membre=Membre, Serveur=Serveur, Obj=Obj, F=F)


# ═══════════════════════════════════════════════════════════════════════════════
#  La base temporaire et les modules branchés comme dans bot.py
# ═══════════════════════════════════════════════════════════════════════════════

def _base(chemin: Path):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


async def _appeler_setup(module, deps: dict) -> bool:
    """Le `setup` d'un module inconnu d'avance (les événements) : seulement les dépendances qu'il demande."""
    setup = getattr(module, "setup", None)
    if setup is not None:
        noms = inspect.signature(setup).parameters
        manquants = [n for n, p in noms.items() if p.default is inspect.Parameter.empty
                     and p.kind is not inspect.Parameter.VAR_KEYWORD and n not in deps]
        if manquants:
            print(f"[SITE LOCAL] {module.__name__} : setup non appelé (dépendances inconnues : {', '.join(manquants)})")
            return False
        res = setup(**{n: deps[n] for n in noms if n in deps})
        if inspect.isawaitable(res):
            await res
    if hasattr(module, "init_db"):
        await module.init_db()
    return True


async def construire(dossier: Path | None = None, port: int = PORT, qui: int = FONDATEUR):
    """(application aiohttp, contexte) : le site complet sur une base neuve, prêt à servir."""
    dossier = Path(dossier or tempfile.mkdtemp(prefix="site_local_"))
    (dossier / "data").mkdir(parents=True, exist_ok=True)
    paths._RESOLVED_BASE = dossier / "data"

    import affiches
    import annonces
    import casier
    import clan
    import entraide
    import health_server
    import questionnaire
    import questions
    import recrutements
    import registre
    import rellseas_panneau
    import sondages
    import suggestions
    import tableau
    import transcript_store
    import vigilance

    transcript_store._BASE_DIR = str(dossier / "transcripts")
    tableau.RACINE_DONNEES = dossier / "data" / "site"
    X = _faux()
    g = X.Serveur()
    get_db = _base(dossier / "site_local.db")
    conf = {}

    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v

    def a_la_tete(_g, m, _c=None):
        return m is not None and m.id in TETE

    async def journal(_g, type_, texte, **kw):  # comme `_au_journal` de bot.py : les mentions deviennent des noms
        await registre.noter(SERVEUR_ID, "Clan", type_, registre.propre(texte, _g), **{
            k: v for k, v in kw.items() if k in ("membre_id", "auteur_id", "salon_id", "detail")})

    #  Les rôles et les membres.
    direction_r = g.role("Direction", 60, couleur=0x8E2A24)
    g.role("Staff", 40, couleur=0xA8823F, permissions=discord.Permissions(manage_messages=True))
    clan_r = g.role("Rell Seas", 30, couleur=0x1F4E5A)
    g.role("Notifications", 5)
    g.role("Bot musique", 20, managed=True)
    g.me = X.Obj(id=999, top_role=g.role("GoRP Bot", 80), guild_permissions=discord.Permissions(
        manage_roles=True, manage_channels=True, ban_members=True, mention_everyone=True, manage_events=True))
    g.membre(FONDATEUR, "GoRipe", direction_r, arrivee_jours=600)
    g.membre(DIRECTION, "Capitaine Direction", direction_r, arrivee_jours=420)
    hasard = random.Random(25102026)
    for k, nom in enumerate(PRENOMS):
        roles = [clan_r] if k % 3 != 2 else []
        g.membre(1000 + k, nom, *roles, arrivee_jours=hasard.randint(3, 500))
    g.get_member(1003).timed_out_until = datetime.now(timezone.utc) + timedelta(hours=3)
    conf.update({rellseas_panneau.CLE_ROLE_CIBLE: clan_r.id, "direction_allowed_role": direction_r.id,
                 "ticket_panels": {"p1": {"name": "Recrutement Rell Seas"}, "p2": {"name": "Support"},
                                   "p3": {"name": "Signalement"}}})
    salon_annonces = g._salon(X.F.Texte, "📢・annonces", {"category": g.commu})
    #  Le forum du clan et ses posts (📢 Infos d'abord) : là où partent les annonces et les événements du clan. Ses
    #  posts seuls sont connus du serveur (le forum n'est pas rangé parmi les salons : les autres pages ne changent pas).
    import zones
    forum_clan = X.F.Forum(g, g.nouvel_id(), "🦜▷・clan-gorp", {})
    conf["clan_posts"] = {cle: {"id": g.nouveau_fil(forum_clan, titre).id} for cle, titre, _v, _t in zones.CLAN_POSTS}

    #  Les modules, comme dans `_activite_boot`.
    silence = print
    registre.setup(get_db=get_db, log=silence)
    recrutements.setup(get_db=get_db, cfg=cfg, db_set=db_set, salon=None, role=lambda _g, _c: clan_r,
                       panneaux=rellseas_panneau.panneaux_tickets, log=silence)
    questions.setup(get_db=get_db, est_staff=lambda _g, m, _c: a_la_tete(_g, m), log=silence)

    async def salon_alertes(*_a):  # aucun salon des logs : alertes et idées restent sur le site
        return None
    vigilance.setup(get_db=get_db, salon=salon_alertes, carte=lambda *a: None, log=silence)
    clan.setup(get_db=get_db, log=silence)
    casier.setup(get_db=get_db, log=silence)
    sondages.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None, log=silence)
    suggestions.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None,
                      salon_logs=salon_alertes, log=silence)

    async def est_staff(_g, m):
        return a_la_tete(_g, m)
    entraide.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None, est_staff=est_staff,
                   journal=journal, log=silence)
    annonces.setup(get_db=get_db, cfg=cfg, db_set=db_set, est_tete=a_la_tete, journal=journal,
                   role_clan=lambda _g, _c: clan_r, log=silence)

    #  Le recrutement en deux étapes (questionnaire.py), branché comme l'étape « questionnaire » du bot. Les tickets
    #  ouverts sont des fils de démonstration (les cartes y sont « postées » sans rien envoyer à Discord) ; décider
    #  ferme le ticket de la base locale.
    fils_tickets: dict = {}

    async def ticket_ouvert(_g, tid):
        async with get_db() as db:
            async with db.execute("SELECT user_id, claimed_by, answers, panel_id FROM tickets WHERE id=? AND guild_id=?"
                                  " AND status='open'", (int(tid), SERVEUR_ID)) as cur:
                r = await cur.fetchone()
        if r is None:
            return None, None
        if int(tid) not in fils_tickets:
            fils_tickets[int(tid)] = await salon_annonces.create_thread(name=f"ticket-{int(tid)}")
        try:
            reponses = json.loads(r[2]) if r[2] else {}
        except ValueError:
            reponses = {}
        return fils_tickets[int(tid)], {"id": int(tid), "user": r[0], "claimed": r[1] or 0, "answers": reponses,
                                        "panel_id": r[3] or ""}

    async def decider(_g, tid, auteur, accepte, motif=""):
        async with get_db() as db:
            await db.execute("UPDATE tickets SET status='closed' WHERE id=? AND guild_id=?", (int(tid), SERVEUR_ID))
            await db.commit()
        return True, "Candidature acceptée : rôle donné, ticket fermé." if accepte else "Candidature refusée : ticket fermé."
    questionnaire.setup(get_db=get_db, cfg=cfg, panneaux=rellseas_panneau.panneaux_tickets, ticket_ouvert=ticket_ouvert,
                        decider=decider, autorise=lambda _i: True, journal=journal, log=silence)

    async def alerte(_g, m, raison, suspendu=True):
        print(f"[SITE LOCAL] alerte de sécurité : {m.display_name} — {raison}")

    #  Le Port et l'Équipage : les VRAIES actions de bot.py, l'activité du clan, la conversation d'un ticket.
    import site_local_port
    carnet = site_local_port.completer_faux_serveur(g, X)
    tableau.setup(bot=X.Obj(get_guild=lambda gid: g if gid == SERVEUR_ID else None, user=X.Obj(id=999)),
                  cle="site-local", base_url=f"http://localhost:{port}", cfg=cfg, get_db=get_db,
                  mesurer_groupe=site_local_port.mesurer_groupe(), autorise_membre=a_la_tete, direction=a_la_tete,
                  tete=TETE, alerte_securite=alerte, conversation=site_local_port.conversation(g=g, get_db=get_db),
                  actions=site_local_port.actions_du_bot(g=g, X=X, get_db=get_db, cfg=cfg, tete=TETE,
                                                         fondateur=FONDATEUR, carnet=carnet), log=print)
    for module in (registre, recrutements, questions, vigilance, clan, casier, sondages, suggestions, entraide,
                   annonces, tableau, questionnaire):
        await module.init_db()
    await _tables_du_bot(get_db)
    tableau.monter(questionnaire.ROUTES_SITE)
    tableau.ajouter_regle(**questionnaire.REGLE_NETTOYAGE)

    affiches.setup(get_db=get_db, log=print)
    await affiches.init_db()
    depart = affiches.DEPART if affiches.DEPART.is_file() else CATALOGUE_EXEMPLE
    await affiches.charger_depart(depart)
    tableau.monter(affiches)
    #  Les rôles de métier du clan (Capitainerie → Rôles & métiers), comme l'étape « metiers » du bot.
    import metiers

    async def aucune_sanction(_g):
        return set()
    metiers.setup(get_db=get_db, cfg=cfg, db_set=db_set, role_clan=lambda _g, _c: clan_r, sanctionnes=aucune_sanction,
                  journal=journal, epargnes=a_la_tete, log=print)
    try:
        import evenements  # le module des événements du clan : branché s'il est là
    except ModuleNotFoundError:
        evenements = None
    except Exception as ex:  # outil local : présent mais cassé — on le dit et on continue sans lui
        print(f"[SITE LOCAL] événements illisibles : {type(ex).__name__} {ex}")
        evenements = None
    if evenements is not None:
        deps = {"get_db": get_db, "cfg": cfg, "db_set": db_set, "bot": X.Obj(get_guild=lambda gid: g, user=X.Obj(id=999),
                                                                               guilds=[g]),
                "log": print, "est_tete": a_la_tete, "journal": journal, "role_clan": lambda _g, _c: clan_r,
                "fiches": affiches.fiches_clan, "catalogue": affiches.catalogue_clan, "media": tableau.lire_media}
        try:
            if await _appeler_setup(evenements, deps) and hasattr(evenements, "ROUTES_SITE"):
                affiches.brancher_evenements(evenements)  # comme l'étape « affiches » du bot
        except Exception as ex:  # outil local : on le dit et on continue sans les événements
            print(f"[SITE LOCAL] événements non branchés : {type(ex).__name__} {ex}")

    await _remplir(get_db, g, clan_r, salon_annonces, X)
    await _recrutement_demo(get_db, g, ticket_ouvert)
    await _affiches_demo(g, X)
    if evenements is not None and evenements.pret():
        await _evenements_demo(evenements, g, clan_r, get_db)
    await site_local_port.remplir(get_db=get_db, g=g, salon=salon_annonces, tete=TETE, fondateur=FONDATEUR,
                                  direction=DIRECTION)

    app = health_server.construire_app()

    async def demo(request):
        """L'entrée de démonstration : une session SANS lien — ce script seulement."""
        from aiohttp import web
        uid = DIRECTION if request.query.get("qui") == "direction" else qui
        expire = int(time.time()) + tableau.DUREE
        sid = await tableau._ouvrir_session(SERVEUR_ID, uid, expire)
        r = web.Response(status=303, headers=dict(tableau.ENTETES, Location=tableau.ESPACE))
        r.set_cookie(tableau.COOKIE, sid, max_age=tableau.DUREE, path="/", secure=True, httponly=True, samesite="Lax")
        return r
    app.router.add_get("/tableau/demo", demo)
    return app, X.Obj(dossier=dossier, guild=g, get_db=get_db, conf=conf)


async def _tables_du_bot(get_db) -> None:
    """Les tables que `bot.py` crée lui-même (tickets, casier, restrictions, erreurs) : ce que le site en lit."""
    async with get_db() as db:
        for sql in (
                "CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
                " user_id INTEGER, panel_id TEXT, claimed_by INTEGER, status TEXT, answers TEXT,"
                " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
                "CREATE TABLE IF NOT EXISTS ticket_log_events (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                " ticket_id INTEGER, kind TEXT, actor_id INTEGER, detail TEXT, created_unix INTEGER)",
                "CREATE TABLE IF NOT EXISTS ticket_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                " channel_id INTEGER, action TEXT, actor_id INTEGER, at DATETIME, detail TEXT)",
                "CREATE TABLE IF NOT EXISTS ticket_transcripts (guild_id INTEGER, ticket_id INTEGER, url TEXT,"
                " user_name TEXT, closed_at DATETIME)",
                #  Comme bot.py : une sanction posée depuis le site (sans date) prend l'heure de l'écriture.
                "CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                " user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, duration TEXT DEFAULT '',"
                " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
                "CREATE TABLE IF NOT EXISTS restricted_members (guild_id INTEGER, user_id INTEGER, roles_backup TEXT,"
                " restricted_at DATETIME, duration INTEGER, reason TEXT, restricted_by INTEGER)",
                "CREATE TABLE IF NOT EXISTS error_log (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER DEFAULT 0,"
                " source TEXT NOT NULL, error_type TEXT, message TEXT, traceback TEXT,"
                " context_jsonb TEXT DEFAULT '{}', occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"):
            await db.execute(sql)
        await db.commit()


def _date(t: float) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _remplir(get_db, g, clan_r, salon_annonces, X) -> None:
    """Des données qui ressemblent au vrai serveur : de quoi voir chaque rubrique remplie."""
    import registre
    hasard = random.Random(2510)
    maintenant = time.time()
    membres = [m for m in g.members if m.id not in TETE]
    async with get_db() as db:
        #  Les tickets : ouverts et fermés, de chaque type, avec prise en charge et motif.
        for n in range(1, 41):
            m = hasard.choice(membres)
            panneau = hasard.choice(("p1", "p1", "p2", "p3"))
            ouvert = maintenant - hasard.randint(1, 80) * 86400 + hasard.randint(0, 80000)
            ouvert_ticket = n > 34
            reponses = json.dumps({"Pseudo Roblox": f"{m.display_name.split()[0]}_RS", "Niveau": str(hasard.randint(5, 80))}
                                  if panneau == "p1" else {})
            await db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
                             (n, SERVEUR_ID, 5000 + n, m.id, panneau, FONDATEUR if n % 2 else DIRECTION,
                              "open" if ouvert_ticket else "closed", reponses, _date(ouvert)))
            await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, created_unix)"
                             " VALUES (?,?,?,?,?)", (SERVEUR_ID, n, "claim", FONDATEUR if n % 2 else DIRECTION,
                                                     int(ouvert + 1800)))
            if not ouvert_ticket:
                await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, detail, created_unix)"
                                 " VALUES (?,?,?,?,?,?)", (SERVEUR_ID, n, "close", DIRECTION, "Résolu",
                                                           int(ouvert + hasard.randint(2, 40) * 3600)))
        #  Le casier : avertissements, mutes, détections automatiques, un bannissement.
        for n in range(60):
            m = hasard.choice(membres)
            typ = hasard.choice(("warn", "warn", "warn", "mute", "insulte", "protection", "kick"))
            await db.execute("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration, created_at)"
                             " VALUES (?,?,?,?,?,?,?)",
                             (SERVEUR_ID, m.id, 999 if typ in ("insulte", "protection") else hasard.choice((FONDATEUR, DIRECTION)),
                              typ, hasard.choice(("Spam dans le salon", "Insulte", "Lien interdit", "Pub", "Hors sujet")),
                              "1h" if typ == "mute" else "", _date(maintenant - hasard.randint(0, 120) * 86400)))
        await db.execute("INSERT INTO restricted_members VALUES (?,?,?,?,?,?,?)",
                         (SERVEUR_ID, membres[4].id, "[]", _date(maintenant - 86400), 0, "Raid", DIRECTION))
        #  Les candidatures fermées (acceptées, refusées).
        for n in range(1, 13):
            m = membres[n]
            decision = "acceptes" if n % 3 else "refuses"
            ferme = maintenant - hasard.randint(1, 200) * 86400
            await db.execute("INSERT OR REPLACE INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom,"
                             " ouvert_le, ferme_le, ferme_par, pris_par, reponses, msg_candidat, msg_staff, transcript,"
                             " raison, decision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (SERVEUR_ID, 900 + n, m.id, m.display_name, int(ferme - 7200), int(ferme), DIRECTION,
                              FONDATEUR, json.dumps({"Pseudo Roblox": f"{m.display_name.split()[0]}_RS",
                                                     "Pourquoi nous ?": "J'aime naviguer en équipage."}),
                              4, 3, "", "" if decision == "acceptes" else "Niveau insuffisant", decision))
        #  Les questions, sondages et idées.
        for n, texte in enumerate(("Comment on rejoint le clan Rell Seas ?", "C'est quand le prochain event ?",
                                   "Quelqu'un sait où trouver le marchand ?")):
            await db.execute("INSERT INTO questions (guild_id, salon_id, message_id, auteur_id, texte, quand, statut)"
                             " VALUES (?,?,?,?,?,?,?)", (SERVEUR_ID, salon_annonces.id, 7000 + n, membres[n].id, texte,
                                                         int(maintenant - n * 7200), "ouverte" if n else "repondue"))
        await db.execute("INSERT INTO sondages (message_id, guild_id, channel_id, auteur_id, question, choix, comptes,"
                         " total, cree_le, fin_le) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (8001, SERVEUR_ID, salon_annonces.id, FONDATEUR, "Un raid samedi soir ?",
                          json.dumps(["Oui", "Non", "Dimanche plutôt"]), json.dumps([9, 2, 4]), 15,
                          _date(maintenant - 86400), _date(maintenant + 86400)))
        await db.execute("INSERT INTO suggestions_v2 (guild_id, channel_id, message_id, auteur_id, titre, details, statut,"
                         " cree_le) VALUES (?,?,?,?,?,?,?,?)",
                         (SERVEUR_ID, salon_annonces.id, 8101, membres[2].id, "Un salon pour les cartes au trésor",
                          "Partager les cartes trouvées.", "attente", _date(maintenant - 3 * 86400)))
        await db.execute("INSERT INTO annonces (guild_id, salon_id, message_id, fil_id, auteur_id, titre, texte, cree)"
                         " VALUES (?,?,?,?,?,?,?,?)", (SERVEUR_ID, salon_annonces.id, 8201, 0, FONDATEUR,
                                                        "Bienvenue sur GoRP SEA",
                                                        "Le clan recrute : tickets ouverts.", int(maintenant - 5 * 86400)))
        await db.commit()
    #  Le journal : un mois d'évènements, de toutes les catégories.
    for n in range(220):
        cat, type_, gravite = hasard.choice(CATEGORIES_JOURNAL)
        m = hasard.choice(membres)
        quand = maintenant - hasard.randint(0, 30 * 86400)
        async with get_db() as db:
            await db.execute("INSERT INTO registre (guild_id, quand, categorie, type, membre_id, auteur_id, salon_id, texte,"
                             " detail, gravite) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (SERVEUR_ID, int(quand), cat, type_, m.id, hasard.choice((0, FONDATEUR, DIRECTION)),
                              salon_annonces.id, f"{cat} : {m.display_name}", "", gravite))
            await db.commit()
    registre._derniers.clear()


async def _recrutement_demo(get_db, g, ticket_ouvert) -> None:
    """Quatre candidatures du clan, jouées par le VRAI module (questionnaire.py) : une à l'étape 1, un questionnaire
    envoyé sans réponse, des réponses à corriger (justes, approchées, fausses), une correction commencée."""
    import questionnaire
    chef = g.get_member(FONDATEUR)
    maintenant = time.time()
    candidats = [m for m in g.members if m.id not in TETE and not m.bot][14:18]
    async with get_db() as db:
        for k, m in enumerate(candidats):
            await db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
                             (41 + k, SERVEUR_ID, 6041 + k, m.id, "p1", FONDATEUR, "open",
                              json.dumps({"Pseudo Roblox": f"{m.display_name.split()[0]}_RS",
                                          "Niveau": str(24 + 11 * k)}),
                              _date(maintenant - (4 - k) * 5400)))
        await db.commit()
    for k, m in enumerate(candidats):
        ch, _tk = await ticket_ouvert(g, 41 + k)
        await questionnaire.poser_etape1(g, ch, 41 + k, m.id, nombre=await questionnaire.annonce(g.id))
    for tid in (42, 43, 44):
        st, rep = await questionnaire.envoyer(g, tid, chef, {}, depuis="etape1")
        if st != 200:
            print(f"[SITE LOCAL] questionnaire de démonstration non envoyé : {rep}")
            return
    for tid in (43, 44):
        e = next(x for x in await questionnaire._envois_du_ticket(g.id, tid) if x["statut"] == "envoye")
        textes = {}
        for n, q in enumerate(e["questions"]):
            juste = str(q.get("reponse") or "")
            if n % 4 == 1 and len(juste) > 4:
                textes[int(q["rang"])] = juste[:-2] + juste[-1]           # approchée : une lettre oubliée
            elif n % 5 == 3:
                textes[int(q["rang"])] = "Je ne sais pas"
            else:
                textes[int(q["rang"])] = juste or "?"
        if not await questionnaire._garder_page(e, textes):
            print("[SITE LOCAL] réponses de démonstration refusées")
            return
        t = int(time.time())
        async with get_db() as db:   # ce que fait `_terminer` quand la dernière page arrive
            await db.execute("UPDATE recrutement_envois SET statut='repondu', repondu_le=? WHERE id=?", (t, e["id"]))
            await db.execute("UPDATE recrutement_suivi SET etape='reponses', maj_le=? WHERE guild_id=? AND ticket_id=?",
                             (t, g.id, tid))
            await db.commit()
        if tid == 44:   # une correction commencée : les trois premières réponses cochées
            for q in e["questions"][:3]:
                await questionnaire.corriger(g, chef, {"envoi": e["id"], "question": q["id"], "juste": True})


async def _affiches_demo(g, X) -> None:
    """Quelques affiches (et des portraits dessinés ici, à défaut de Roblox), un rôle de métier lié."""
    import affiches
    import tableau
    #  Les clés viennent du catalogue chargé (le vrai, donnees_jeu/rell_catalogue.json, ou l'exemple des tests) :
    #  une affiche de démonstration n'invente jamais un élément du jeu.
    par_type: dict = {}
    for e in (await affiches.catalogue())["elements"]:
        if e["actif"]:
            par_type.setdefault(e["type"], []).append(e["cle"])

    def cle(type_, *voulues):
        dispo = par_type.get(type_, [])
        return next((k for k in voulues if k in dispo), dispo[0] if dispo else None)

    def attributs(**voulus):
        out = {t: [k for k in (cle(t, *v) for v in listes) if k] for t, listes in voulus.items()}
        return {t: list(dict.fromkeys(ks)) for t, ks in out.items() if ks}

    corps = [
        {"id": "demo-kolax-01", "membre_id": "1000", "roblox_nom": "Kolax_RS", "roblox_id": "1000001", "surnom": "Le Requin",
         "prime": 1_500_000, "niveau": 72, "grade": "Second", "statut": "actif",
         "attributs": attributs(race=[("human", "humain")], metier=[("navigation", "navigateur"), ("shipwright", "canonnier")],
                                faction=[("pirates",)]),
         "notes": "Toujours à l'heure aux raids."},
        {"id": "demo-mira-002", "membre_id": "1001", "roblox_nom": "Mira_RS", "roblox_id": "1000002", "surnom": "L'Écume",
         "prime": 640_000, "niveau": 41, "grade": "Matelot", "statut": "actif",
         "attributs": attributs(race=[("marinian", "triton")], metier=[("fishing", "charpentier")], faction=[("pirates",)])},
        {"id": "demo-calico03", "membre_id": "1004", "roblox_nom": "Calico_Jack", "roblox_id": "1000003",
         "surnom": "Calico", "prime": 90_000, "niveau": 12, "grade": "Mousse", "statut": "nouveau",
         "attributs": attributs(metier=[("cooking", "cuisinier")], faction=[("marines", "marine")])},
    ]
    chef = g.get_member(FONDATEUR)
    for c in corps:
        status, rep = await affiches._route_affiche(g, chef, {}, c)
        if status != 200:
            print(f"[SITE LOCAL] affiche de démonstration refusée : {rep}")
    try:
        from PIL import Image, ImageDraw
        dossier = tableau.dossier_site("avatars")
        for k, (rid, teinte) in enumerate(((1000001, (31, 78, 90)), (1000002, (142, 42, 36)), (1000003, (168, 130, 63)))):
            im = Image.new("RGB", (420, 420), (239, 226, 196))
            d = ImageDraw.Draw(im)
            d.ellipse((110, 60, 310, 260), fill=teinte)
            d.rectangle((90, 270, 330, 420), fill=teinte)
            im.save(dossier / f"{rid}.webp", "WEBP", quality=85)
    except Exception as ex:  # outil local : sans Pillow, les affiches n'ont pas de portrait
        print(f"[SITE LOCAL] portraits de démonstration non dessinés : {type(ex).__name__} {ex}")
    #  Un rôle de métier lié à la main — sauf si l'attribution automatique (metiers.py) l'a déjà créé avec les affiches.
    cle_navigation = cle("metier", "navigation", "navigateur")
    if cle_navigation and not any(x["type"] == "metier" and x["cle"] == cle_navigation for x in await affiches._liens(g.id)):
        metier = g.role("Navigateur", 6, couleur=0x1F4E5A)
        await affiches._route_role(g, chef, {}, {"type": "metier", "cle": cle_navigation, "role_id": str(metier.id),
                                                 "auto": True})


async def _evenements_demo(ev, g, clan_r, get_db) -> None:
    """Les annonces et événements du clan, joués par le VRAI module (evenements.py) : trois brouillons, un événement
    à venir avec des réponses et des places (et son évènement Discord), une annonce publiée avec son image et ses
    « Vu », un événement terminé, un annulé. Les heures sont celles de Paris."""
    import base64
    import io
    from zoneinfo import ZoneInfo

    import tableau
    chef = g.get_member(FONDATEUR)
    paris = ZoneInfo("Europe/Paris")

    def a_paris(jours, heure, minute=0, depuis=None):
        d = datetime.fromtimestamp(depuis or time.time(), paris) + timedelta(days=jours)
        return int(d.replace(hour=heure, minute=minute, second=0, microsecond=0).timestamp())

    async def brouillon(**corps):
        statut, rep = await ev.route_brouillon(g, chef, {}, corps)
        if statut != 200:
            print(f"[SITE LOCAL] brouillon de démonstration refusé : {rep}")
            return None
        return rep["element"]

    async def publier(e):
        statut, rep = await ev.publier(g, chef, e["id"])
        if statut != 200:
            print(f"[SITE LOCAL] publication de démonstration refusée : {rep}")
            return None
        return rep["element"]

    async def repondre(eid, choix):
        membres = [m for m in g.members if clan_r in m.roles]
        async with get_db() as db:
            k = 0
            for c, n in choix:
                for m in membres[k:k + n]:
                    await db.execute("INSERT OR REPLACE INTO clan_evenements_reponses(evenement_id, membre_id, choix, quand)"
                                     " VALUES (?,?,?,?)", (eid, m.id, c, int(time.time()) - 600))
                k += n
            await db.commit()
        await ev.maj_carte(g, eid)

    image = ""
    try:
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (960, 360), (31, 78, 90))
        d = ImageDraw.Draw(im)
        for y in range(0, 360, 6):
            d.line((0, y, 960, y), fill=(31 + y // 12, 78 + y // 20, 90 + y // 24))
        d.ellipse((380, 60, 580, 260), outline=(239, 226, 196), width=10)
        d.line((480, 70, 480, 250), fill=(239, 226, 196), width=8)
        tampon = io.BytesIO()
        im.save(tampon, "PNG")
        statut, rep = await tableau._route_media(g, chef, {}, {"nom": "movie3.png", "type": "image/png",
                                                              "base64": base64.b64encode(tampon.getvalue()).decode()})
        image = rep.get("id", "") if statut == 200 else ""
    except Exception as ex:  # outil local : sans Pillow, l'annonce part sans image
        print(f"[SITE LOCAL] image de démonstration non dessinée : {type(ex).__name__} {ex}")

    await brouillon(type="evenement", titre="Sortie en mer : le boss des abysses", quand=a_paris(2, 21),
                    texte="Rendez-vous au port **15 minutes avant**.\nPrévoyez des vivres et vos meilleures armes.\n\n"
                          "> Les absents non excusés passent leur tour.",
                    lieu="Fosse des abysses", duree_min=120, places=12, rappels=[1440, 60, 10], mention="inscrits",
                    discord_event=True)
    await brouillon(type="annonce", titre="Nouvelles règles du clan", mention="clan",
                    texte="Merci de lire les **nouvelles règles** épinglées dans le post Infos.")
    await brouillon(type="metiers", texte="Voici les métiers officiels de chacun, d'après les affiches.")
    e = await brouillon(type="evenement", titre="Entraînement de combat", quand=a_paris(1, 20, 30), lieu="Taverne du clan",
                        texte="Duels un contre un, puis en équipe.", duree_min=90, places=10, rappels=[60, 10],
                        mention="clan", discord_event=True)
    e = await publier(e) if e else None
    if e:
        await repondre(e["id"], (("d", 6), ("p", 2), ("n", 1)))
    a = await brouillon(type="annonce", titre="Le Movie 3 est sorti", image=image, mention="clan",
                        texte="**Le Movie 3 est là.** Toutes les nouveautés sont dans le post Infos.")
    a = await publier(a) if a else None
    if a:
        await repondre(a["id"], (("v", 9),))
    #  Un événement d'il y a cinq jours (publié à l'époque), puis un événement annulé.
    vrai, passe = ev._mur, time.time() - 5 * 86400
    ev._mur = lambda: passe
    try:
        p = await brouillon(type="evenement", titre="Guerre de factions", quand=a_paris(0, 21, depuis=passe + 86400),
                            lieu="Forteresse du centre", duree_min=120, rappels=[60])
        p = await publier(p) if p else None
    finally:
        ev._mur = vrai
    if p:
        await repondre(p["id"], (("d", 11), ("p", 3), ("n", 2)))
        await ev.traiter(g, p["id"])
    c = await brouillon(type="evenement", titre="Course de navires", quand=a_paris(4, 18), duree_min=60, rappels=[60])
    c = await publier(c) if c else None
    if c:
        await ev.annuler(g, chef, c["id"], prevenir=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Le vrai site en local, avec un faux serveur Discord.")
    parser.add_argument("--port", type=int, default=PORT, help=f"le port ({PORT} par défaut)")
    parser.add_argument("--qui", choices=("fondateur", "direction"), default="fondateur",
                        help="le compte de l'entrée de démonstration")
    parser.add_argument("--garder", default="", help="dossier de travail gardé (sinon un dossier temporaire)")
    parser.add_argument("--site", default="", help="servir un autre dossier « site/ » (sinon celui du dépôt)")
    args = parser.parse_args()
    from aiohttp import web

    async def lancer():
        if args.site:
            import tableau
            tableau.SITE = Path(args.site).resolve()
        app, ctx = await construire(Path(args.garder) if args.garder else None, args.port,
                                    DIRECTION if args.qui == "direction" else FONDATEUR)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "localhost", args.port).start()
        print(f"[SITE LOCAL] base et images : {ctx.dossier}")
        print(f"[SITE LOCAL] ouvre http://localhost:{args.port}/tableau/demo   (Ctrl+C pour arrêter)")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await runner.cleanup()
    try:
        asyncio.run(lancer())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
