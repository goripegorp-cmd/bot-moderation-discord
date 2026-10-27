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

        async def edit(self, *, name=None, reason=None, **_kw):
            """Renommer le rôle (Capitainerie → Rôles & métiers → « Renommer »), comme `discord.Role.edit`."""
            if name is not None:
                self.name = str(name)
            return self

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


async def construire(dossier: Path | None = None, port: int = PORT, qui: int = FONDATEUR, lourd: bool = False):
    """(application aiohttp, contexte) : le site complet sur une base neuve, prêt à servir. `lourd` : des volumes de vrai
    serveur en plus (pour le contrôle visuel du rangement ; les tests gardent les données légères)."""
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
    import textes
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
    #  26/10/2026 : « Expulser » et « Bannir » — la rubrique Sécurité (qui a une permission dangereuse) a de quoi montrer.
    g.role("Staff", 40, couleur=0xA8823F, permissions=discord.Permissions(manage_messages=True, kick_members=True,
                                                                         ban_members=True))
    clan_r = g.role("Rell Seas", 30, couleur=0x1F4E5A)
    g.role("Notifications", 5)
    g.role("Bot musique", 20, managed=True)
    g.me = X.Obj(id=999, top_role=g.role("GoRP Bot", 80), guild_permissions=discord.Permissions(
        manage_roles=True, manage_channels=True, ban_members=True, mention_everyone=True, manage_events=True,
        view_audit_log=True))
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

    #  Les modules, comme dans `_activite_boot`. Les textes réécrits sur le site (Textes & noms) d'abord : les cartes de
    #  démonstration les emploient, comme celles du bot.
    silence = print
    textes.setup(get_db=get_db, log=silence)
    await textes.init_db()
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
            async with db.execute("SELECT user_id, claimed_by, answers, panel_id, channel_id FROM tickets WHERE id=? AND"
                                  " guild_id=? AND status='open'", (int(tid), SERVEUR_ID)) as cur:
                r = await cur.fetchone()
        if r is None:
            return None, None
        if int(tid) not in fils_tickets and g.fils.get(int(r[4] or 0)) is not None:
            fils_tickets[int(tid)] = g.fils[int(r[4])]      # ouvert par le vrai chemin du bot : son fil
        if int(tid) not in fils_tickets:
            fils_tickets[int(tid)] = await salon_annonces.create_thread(name=f"ticket-{int(tid)}")
        try:
            reponses = json.loads(r[2]) if r[2] else {}
        except ValueError:
            reponses = {}
        return fils_tickets[int(tid)], {"id": int(tid), "user": r[0], "claimed": r[1] or 0, "answers": reponses,
                                        "panel_id": r[3] or ""}

    async def decider(_g, tid, auteur, accepte, motif="", *, annonce=None, mp=True):
        if annonce is not None:   # comme `_decision_recrutement` : le message de la décision avant la fermeture
            await annonce()
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
    tableau.setup(bot=X.Obj(get_guild=lambda gid: g if gid == SERVEUR_ID else None, user=X.Obj(id=999), guilds=[g]),
                  cle="site-local", base_url=f"http://localhost:{port}", cfg=cfg, get_db=get_db,
                  mesurer_groupe=site_local_port.mesurer_groupe(), autorise_membre=a_la_tete, direction=a_la_tete,
                  tete=TETE, alerte_securite=alerte, conversation=site_local_port.conversation(g=g, get_db=get_db),
                  actions=site_local_port.actions_du_bot(g=g, X=X, get_db=get_db, cfg=cfg, tete=TETE,
                                                         fondateur=FONDATEUR, carnet=carnet), log=print)
    for module in (registre, recrutements, questions, vigilance, clan, casier, sondages, suggestions, entraide,
                   annonces, tableau, questionnaire):
        await module.init_db()
    await _tables_du_bot(get_db)
    tableau.monter(textes)
    tableau.monter(questionnaire.ROUTES_SITE)
    for regle in questionnaire.REGLES_RECRUTEMENT:   # comme `_activite_boot` (26/10/2026)
        tableau.ajouter_regle(**regle)

    affiches.setup(get_db=get_db, log=print)
    await affiches.init_db()
    depart = affiches.DEPART if affiches.DEPART.is_file() else CATALOGUE_EXEMPLE
    await affiches.charger_depart(depart)
    tableau.monter(affiches)
    #  Les rôles de métier du clan (Capitainerie → Rôles & métiers), comme l'étape « metiers » du bot.
    import metiers

    async def aucune_sanction(_g):
        return set()
    #  Le guide du clan (zones.py), dans son post de démonstration : un de ses textes réécrit sur le site (Textes &
    #  noms) le fait réécrire, comme sur le vrai serveur ; le choix du métier y est posé.
    zones.setup(cfg=cfg, db_set=db_set, log=silence)
    metiers.setup(get_db=get_db, cfg=cfg, db_set=db_set, role_clan=lambda _g, _c: clan_r, sanctionnes=aucune_sanction,
                  journal=journal, epargnes=a_la_tete, guide=zones.assurer_guide_clan, log=print)
    zones.brancher_metiers(metiers.section_guide)
    #  26/10/2026 : le VRAI chemin d'un ticket de recrutement (bot.py : « Es-tu sûr ? », la fiche, l'affiche, l'équipe
    #  qui entre) et le questionnaire branché comme dans `_activite_boot`.
    import site_local_recrutement
    #  Ce serveur sert /v/ : la bannière de l'affiche y est (le vrai bot la sert sur son adresse publique). Les autres
    #  bandeaux des menus gardent leur titre en texte, comme avant.
    questionnaire._banniere = lambda: f"http://localhost:{port}/v/{questionnaire.BANNIERE}"
    porteur_tickets = g._salon(X.F.Texte, "🎫・tickets-rell-seas", {"category": g.commu})
    chemin = site_local_recrutement.CheminDuBot(g=g, get_db=get_db, cfg=cfg, db_set=db_set, porteur=porteur_tickets,
                                                categorie=g.commu, metiers=metiers, tete=TETE, carnet=carnet)
    conf["ticket_panels"]["p1"].update({"welcome_message": "Bienvenue à bord, futur matelot !",
                                        "questions": [{"title": "Pseudo Roblox", "question": "Ton pseudo exact"},
                                                      {"title": "Niveau", "question": "Ton niveau dans le jeu"}]})
    #  La VRAIE page du candidat (`candidature_site`, branchée plus bas), comme `_activite_boot` : « Répondre au
    #  questionnaire » donne le lien personnel, un chef est invité par message privé. Les formulaires de Discord (le
    #  repli) restent éprouvés par `/tableau/demo/recrutement/repondre`.
    import candidature_site
    questionnaire.setup(get_db=get_db, cfg=cfg, panneaux=rellseas_panneau.panneaux_tickets, ticket_ouvert=ticket_ouvert,
                        decider=decider, autorise=lambda _i: True, journal=journal, log=silence,
                        web=candidature_site, metier=metiers.invitation, metiers_membre=metiers.metiers_du_membre,
                        **chemin.hooks())
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

    #  Le site de l'équipage (26/10/2026), comme l'étape « site_equipage » du bot.
    import site_equipage
    site_equipage.setup(get_db=get_db, cfg=cfg, log=print)
    site_equipage.brancher_badges_chef(questionnaire.badges_chefs)   # comme l'étape « questionnaire » du bot
    await site_equipage.init_db()
    tableau.monter(site_equipage)
    if evenements is not None:   # modifier une annonce publiée, en place, depuis l'accueil (comme le bot)
        import annonces_modifiables
        tableau.monter(annonces_modifiables)
    tableau.monter_equipage(site_equipage.LECTURES, medias=site_equipage.medias_permis)
    zones.brancher_site_equipage(site_equipage.section_guide)   # sa ligne dans le guide du clan de démonstration
    #  Le site sur plusieurs années (26/10/2026), comme l'étape « longevite » du bot : la suite des listes, les règles
    #  de nettoyage de chaque famille, les orphelins, l'état du stockage.
    import longevite
    longevite.setup(get_db=get_db, chemin_base=dossier / "site_local.db", log=print)
    tableau.monter(longevite)
    #  Le questionnaire en ligne du candidat (26/10/2026), comme l'étape « candidature_site » du bot.
    candidature_site.setup(get_db=get_db, cfg=cfg, log=print)
    await candidature_site.init_db()
    tableau.monter(candidature_site)

    await _remplir(get_db, g, clan_r, salon_annonces, X)
    await _affiches_demo(g, X)
    if evenements is not None and evenements.pret():
        await _evenements_demo(evenements, g, clan_r, get_db)
    await site_local_port.remplir(get_db=get_db, g=g, salon=salon_annonces, tete=TETE, fondateur=FONDATEUR,
                                  direction=DIRECTION)
    await _candidature_demo(get_db, g, ticket_ouvert)
    await _equipage_demo(g)
    if not await zones.assurer_guide_clan(g):   # le guide du clan posé une première fois (son message d'ouverture)
        print("[SITE LOCAL] guide du clan non posé")
    if lourd:
        await _remplir_lourd(get_db, g, clan_r, salon_annonces)
        await _equipes_demo(g, lourd=True)   # douze équipes sur les 80 membres du clan
    #  Après les autres tickets de démonstration (leurs numéros sont fixés) : ceux-ci prennent les numéros suivants. Les
    #  mots « pour soi » de la démonstration ne s'effacent pas plus tard (aucune tâche laissée en attente).
    avis = (questionnaire.AVIS_S, questionnaire.PAGE_S)
    questionnaire.AVIS_S = questionnaire.PAGE_S = 0
    try:
        await _recrutement_demo(get_db, g, ticket_ouvert, chemin, lourd=lourd)
    finally:
        questionnaire.AVIS_S, questionnaire.PAGE_S = avis

    app = health_server.construire_app()

    async def demo(request):
        """L'entrée de démonstration : une session SANS lien — ce script seulement. `?qui=direction` : la direction ;
        `?qui=equipage` : un membre du clan (Kolax, qui a son affiche ; `&id=` en choisit un autre du clan), portée
        « equipage » ; `?vers=equipage` : la tête, sur le site de l'équipage (mode édition)."""
        from aiohttp import web
        portee, vers = "tout", tableau.ESPACE
        if request.query.get("qui") == "candidat":   # 26/10/2026 : le candidat d'un ticket, sur SON questionnaire
            return await _demo_candidat(request)
        if request.query.get("qui") == "equipage":
            brut = request.query.get("id", "1000")
            uid = int(brut) if brut.isdigit() and len(brut) <= 20 else 0
            m = g.get_member(uid)
            if m is None or clan_r not in m.roles:
                return web.Response(status=403, text="Pas un membre du clan.")
            portee, vers = "equipage", tableau.EQUIPAGE
        else:
            uid = DIRECTION if request.query.get("qui") == "direction" else qui
            if request.query.get("vers") == "equipage":
                vers = tableau.EQUIPAGE
        expire = int(time.time()) + tableau.DUREE
        sid = await tableau._ouvrir_session(SERVEUR_ID, uid, expire, portee=portee, appareil=tableau._appareil(request),
                                            adresse=tableau.securite_site.adresse_approx(tableau._ip(request)))
        r = web.Response(status=303, headers=dict(tableau.ENTETES, Location=vers))
        r.set_cookie(tableau.COOKIE, sid, max_age=tableau.DUREE, path="/", secure=True, httponly=True, samesite="Lax")
        return r
    app.router.add_get("/tableau/demo", demo)

    async def _envoi_demande(request) -> int:
        """L'envoi d'une adresse de démonstration : `?envoi=<n>`, le questionnaire en cours de `?ticket=<n>`, ou le dernier
        questionnaire de chef d'équipe d'un membre (`?chef=<id>`)."""
        brut_e, brut_t, brut_c = request.query.get("envoi", ""), request.query.get("ticket", ""), request.query.get("chef", "")
        if brut_e.isdigit() and len(brut_e) <= 12:
            return int(brut_e)
        if brut_c.isdigit() and len(brut_c) <= 20:
            async with get_db() as db:
                async with db.execute("SELECT MAX(id) FROM recrutement_envois WHERE guild_id=? AND candidat_id=? AND"
                                      " nature='chef'", (SERVEUR_ID, int(brut_c))) as cur:
                    r = await cur.fetchone()
            return int(r[0] or 0) if r else 0
        if brut_t.isdigit() and len(brut_t) <= 12:
            s = await questionnaire._suivi(SERVEUR_ID, int(brut_t))
            return int(s["envoi_id"]) if s and s["envoi_id"] else 0
        return 0

    async def _demo_candidat(request):
        """`?qui=candidat&ticket=<n>` (ou `&envoi=<n>` : un chef d'équipe, sans ticket) : le candidat de ce questionnaire,
        une session « candidat » liée à lui, comme son lien personnel — puis SA page (`/tableau/candidature/`). Ce script
        seulement."""
        from aiohttp import web
        import candidature_site
        eid = await _envoi_demande(request)
        e = await candidature_site.envoi_complet(eid) if eid else None
        if e is None:
            return web.Response(status=404, text="Aucun questionnaire ici.")
        m = g.get_member(int(e["candidat_id"]))
        ctx = await candidature_site.contexte(g, eid, int(e["candidat_id"]))
        if m is None or ctx["etat"] not in ("ouvert", "attente", "envoye"):
            return web.Response(status=403, text="Ce questionnaire n'est plus ouvert.")
        expire = int(time.time()) + tableau.DUREE
        sid = await candidature_site.ouvrir_session(SERVEUR_ID, m.id, int(e["ticket_id"] or 0), eid, expire)
        await candidature_site.noter_ouverture(g, m, ctx["envoi"])
        r = web.Response(status=303, headers=dict(tableau.ENTETES, Location=tableau.CANDIDATURE))
        r.set_cookie(tableau.COOKIE_CANDIDAT, sid, max_age=tableau.DUREE, path=tableau.CANDIDATURE, secure=True,
                     httponly=True, samesite="Lax")
        return r

    async def discord_lu(request):
        """Ce que le FAUX Discord a reçu (ce script seulement, jamais le bot) : `?salon=<id>` (ou `?ticket=<n>`) → les
        messages d'un salon ou d'un fil tels qu'ils sont maintenant (leur dernière réécriture), leur texte et leurs
        boutons ; `?post=<clé>` → un post du forum du clan (`guide`, `infos`…) ; `?roles=1` → les rôles du serveur.
        Les parcours y prouvent l'EFFET d'un geste du site (un texte réécrit, un rôle renommé)."""
        from aiohttp import web
        if request.query.get("roles"):
            return web.json_response({"roles": [{"id": str(r.id), "nom": r.name, "position": r.position}
                                                for r in g.roles]}, headers={"Cache-Control": "no-store"})
        if request.query.get("mp", "").isdigit():   # les messages privés reçus par ce membre (le recrutement)
            return web.json_response({"mp": chemin.messages_prives(int(request.query["mp"]))},
                                     headers={"Cache-Control": "no-store"})
        brut = request.query.get("salon", "")
        salon = g.get_channel_or_thread(int(brut)) if brut.isdigit() else None
        ticket = request.query.get("ticket", "")
        if salon is None and ticket.isdigit():   # `?ticket=<n>` : le fil où le bot a posté pour ce ticket
            salon = fils_tickets.get(int(ticket))
            if salon is None:                    # ouvert par le vrai chemin du bot : son fil (même fermé)
                async with get_db() as db:
                    async with db.execute("SELECT channel_id FROM tickets WHERE id=?", (int(ticket),)) as cur:
                        r = await cur.fetchone()
                salon = g.fils.get(int(r[0] or 0)) if r else None
            brut = str(getattr(salon, "id", ""))
        post = request.query.get("post", "")
        if salon is None and post:               # `?post=guide` : un post du forum du clan
            brut = str(((conf.get("clan_posts") or {}).get(post) or {}).get("id", ""))
            salon = g.get_channel_or_thread(int(brut)) if brut.isdigit() else None
        if salon is None:
            return web.json_response({"erreur": "salon ou fil inconnu"}, status=404)
        return web.json_response({"salon": brut, "nom": salon.name, "messages": _messages_du_faux(salon)},
                                 headers={"Cache-Control": "no-store"})
    app.router.add_get("/tableau/demo/discord", discord_lu)

    async def ouvrir_etape(request):
        """`/tableau/demo/etape_suivante?ticket=<n>` (ou `?envoi=<n>`) : la direction (le fondateur) ouvre l'étape suivante
        du questionnaire — la VRAIE fonction (`questionnaire.etape_suivante` : l'ancien message d'étape retiré, le nouveau
        posté, le message privé d'un chef). Ce script seulement (les parcours)."""
        from aiohttp import web
        eid = await _envoi_demande(request)
        ok, message = await questionnaire.etape_suivante(g, eid, g.get_member(FONDATEUR)) if eid else (False, "envoi ?")
        return web.json_response({"ok": bool(ok), "message": message, "envoi": eid}, headers={"Cache-Control": "no-store"})
    app.router.add_get("/tableau/demo/etape_suivante", ouvrir_etape)

    def _liens_de(vues) -> list:
        """Les adresses des boutons-liens de ces vues (Components V2)."""
        out = []

        def tout(c):
            if isinstance(c, dict):
                if c.get("type") == 2 and c.get("url"):
                    out.append(str(c["url"]))
                for x in c.get("components", []) or []:
                    tout(x)
                if c.get("accessory"):
                    tout(c["accessory"])
        for vue in vues:
            for comp in vue.to_components():
                tout(comp)
        return out

    async def lien_du_ticket(request):
        """`/tableau/demo/recrutement/lien?ticket=<n>` : le candidat touche « Répondre au questionnaire » dans son ticket
        (le VRAI bouton, `questionnaire.BoutonRepondre`, puis la page du candidat) — ce qu'il lit pour lui seul et
        l'adresse de sa page. Ce script seulement (les parcours)."""
        from aiohttp import web
        import banc_ticket_recrutement as B
        import faux_serveur as F
        brut = request.query.get("ticket", "")
        s = await questionnaire._suivi(SERVEUR_ID, int(brut)) if brut.isdigit() and len(brut) <= 12 else None
        if s is None or not s["envoi_id"]:
            return web.json_response({"erreur": "pas de questionnaire pour ce ticket"}, status=404)
        e = await questionnaire._envoi(int(s["envoi_id"]))
        i = B.Inter(chemin, g.get_member(int(e["candidat_id"])), fils_tickets.get(int(brut)))
        await questionnaire.BoutonRepondre(int(e["id"])).callback(i)
        liens = _liens_de(i.vues())
        return web.json_response({"envoi": int(e["id"]), "url": liens[0] if liens else "", "formulaire": bool(i.modals),
                                  "lu": " ".join(F.textes(v) for v in i.vues())}, headers={"Cache-Control": "no-store"})
    app.router.add_get("/tableau/demo/recrutement/lien", lien_du_ticket)

    async def mp_cliquer(request):
        """`/tableau/demo/mp/cliquer?membre=<id>&custom_id=cq:rep:<envoi>` : ce membre touche le bouton PERSISTANT de son
        message privé (le gabarit enregistré au démarrage du bot, rebâti depuis le custom_id comme après un
        redémarrage) — ce qu'il lit pour lui seul et l'adresse de sa page. Ce script seulement (les parcours)."""
        from aiohttp import web
        import banc_ticket_recrutement as B
        import faux_serveur as F
        brut, cid = request.query.get("membre", ""), request.query.get("custom_id", "")
        m = g.get_member(int(brut)) if brut.isdigit() and len(brut) <= 20 else None
        gabarit = candidature_site.BoutonQuestionnaire.__discord_ui_compiled_template__.fullmatch(cid)
        if m is None or gabarit is None:
            return web.json_response({"erreur": "membre ou bouton inconnu"}, status=404)
        bouton = await candidature_site.BoutonQuestionnaire.from_custom_id(None, None, gabarit)
        i = B.Inter(chemin, m)
        i.guild = None   # un message privé : aucun serveur
        await bouton.callback(i)
        liens = _liens_de(i.vues())
        return web.json_response({"url": liens[0] if liens else "", "lu": " ".join(F.textes(v) for v in i.vues())},
                                 headers={"Cache-Control": "no-store"})
    app.router.add_get("/tableau/demo/mp/cliquer", mp_cliquer)

    async def mp_lus(request):
        """`/tableau/demo/mp?membre=<id>` : les messages privés que le FAUX Discord a reçus pour ce membre (leur texte et
        leurs boutons, custom_id compris) — l'invitation d'un chef d'équipe. Ce script seulement."""
        from aiohttp import web
        brut = request.query.get("membre", "")
        out = []
        for uid, contenu, kw in carnet["mp"]:
            if str(uid) != brut:
                continue
            vue = kw.get("view")
            ids_ = []

            def tout(c):
                if isinstance(c, dict):
                    if c.get("custom_id"):
                        ids_.append(str(c["custom_id"]))
                    for x in c.get("components", []) or []:
                        tout(x)
            for comp in (vue.to_components() if vue is not None else []):
                tout(comp)
            import faux_serveur as F
            out.append({"texte": " ".join(x for x in (str(contenu or ""), F.textes(vue) if vue is not None else "") if x),
                        "boutons": _boutons_de(vue), "custom_ids": ids_})
        return web.json_response({"membre": brut, "messages": out}, headers={"Cache-Control": "no-store"})
    app.router.add_get("/tableau/demo/mp", mp_lus)
    site_local_recrutement.brancher_demo(app, chemin, questionnaire, g)
    return app, X.Obj(dossier=dossier, guild=g, get_db=get_db, conf=conf, chemin=chemin, carnet=carnet)


def _boutons_de(vue) -> list:
    """Les libellés des boutons d'une vue (Components V2), dans l'ordre."""
    out = []

    def tout(c):
        if isinstance(c, dict):
            if c.get("type") == 2 and c.get("label"):
                out.append(str(c["label"]))
            for x in c.get("components", []) or []:
                tout(x)
            if c.get("accessory"):
                tout(c["accessory"])
    for comp in (vue.to_components() if vue is not None else []):
        tout(comp)
    return out


def _messages_du_faux(salon) -> list:
    """Les messages d'un faux salon ou fil : `{id, texte, boutons, reecrit}`, chacun dans sa dernière version."""
    import faux_serveur as F
    reecrits = {int(mid): kw for mid, kw in getattr(salon, "cartes", []) or []}
    if hasattr(salon, "messages"):   # un fil, un post de forum
        bruts = [(m.id, m.content, m.kw) for m in salon.messages]
    else:
        bruts = list(getattr(salon, "envois", []) or [])
    out = []
    #  Le message d'ouverture d'un post (son identifiant est celui du post) n'est connu que par ses réécritures.
    connus = {int(mid) for mid, _c, _k in bruts}
    bruts = [(mid, "", {}) for mid in reecrits if mid not in connus] + bruts
    for mid, contenu, kw in bruts:
        if mid in salon.monde.effaces:
            continue
        kw = reecrits.get(int(mid), kw or {})
        vue = kw.get("view")
        texte = " ".join(x for x in (str(contenu or ""), F.textes(vue) if vue is not None else "") if x)
        out.append({"id": str(mid), "texte": texte, "boutons": _boutons_de(vue), "reecrit": int(mid) in reecrits})
    return out


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
                #  Comme bot.py (26/10/2026) : la personne, le type et le jeton du fichier (le nettoyage des tickets
                #  fermés efface aussi leur conversation, retrouvée par son jeton).
                "CREATE TABLE IF NOT EXISTS ticket_transcripts (guild_id INTEGER, ticket_id INTEGER, user_id INTEGER,"
                " user_name TEXT, panel TEXT, url TEXT, closed_at TEXT, jeton TEXT, PRIMARY KEY (guild_id, ticket_id))",
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


async def _recrutement_demo(get_db, g, ticket_ouvert, chemin, lourd: bool = False) -> None:
    """Quatre candidatures du clan, OUVERTES PAR LE VRAI CHEMIN DU BOT (create_ticket : l'affiche, l'équipe dans le fil)
    et jouées par le vrai module (questionnaire.py) : une demande à lire, un questionnaire ouvert sans réponse, des
    réponses à corriger (justes, approchées, fausses), une correction commencée. Puis un ticket d'AVANT l'affiche (sa
    carte de l'étape 1) : ces tickets-là marchent toujours. Sur la base lourde : un chef d'équipe validé (le dernier du
    clan par son nom), badgé et proposé en premier dans l'éditeur d'une équipe."""
    import questionnaire
    chef = g.get_member(FONDATEUR)
    candidats = [m for m in g.members if m.id not in TETE and not m.bot][14:19]
    tids = []
    for k, m in enumerate(candidats[:4]):
        tid, _ch = await chemin.ouvrir(m, "p1", {"Pseudo Roblox": f"{m.display_name.split()[0]}_RS", "Niveau": str(24 + 11 * k)})
        tids.append(tid)
    for tid in tids[1:]:
        st, rep = await questionnaire.envoyer(g, tid, chef, {}, depuis="etape1")
        if st != 200:
            print(f"[SITE LOCAL] questionnaire de démonstration non envoyé : {rep}")
            return
    await chemin.repondre(tids[2], questionnaire)       # toutes justes, par les formulaires de Discord
    e = next(x for x in await questionnaire._envois_du_ticket(g.id, tids[3]) if x["statut"] == "envoye")
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
    if await questionnaire.clore_envoi(e, t):          # comme la dernière page reçue
        await questionnaire.annoncer_reponses(g, e, t)
    for q in e["questions"][:3]:                         # une correction commencée : les trois premières réponses cochées
        await questionnaire.corriger(g, chef, {"envoi": e["id"], "question": q["id"], "juste": True})
    #  Un ticket ouvert AVANT l'affiche (le 25/10) : sa carte de l'étape 1, l'ancien chemin.
    if len(candidats) > 4:
        m = candidats[4]
        async with get_db() as db:
            await db.execute("INSERT INTO tickets (guild_id, channel_id, user_id, panel_id, claimed_by, status, answers,"
                             " created_at) VALUES (?,?,?,?,?,?,?,?)", (SERVEUR_ID, 6099, m.id, "p1", 0, "open",
                                                                        json.dumps({"Pseudo Roblox": "Ancien_RS"}),
                                                                        _date(time.time() - 3 * 86400)))
            async with db.execute("SELECT last_insert_rowid()") as cur:
                ancien = (await cur.fetchone())[0]
            await db.commit()
        ch, _tk = await ticket_ouvert(g, ancien)
        await questionnaire.poser_etape1(g, ch, ancien, m.id, nombre=await questionnaire.annonce(g.id))
    if lourd:
        clan = [m for m in g.members if m.id not in TETE and not m.bot and await questionnaire.du_clan(g, m)]
        if clan:
            r = await chemin.nommer_chef(max(clan, key=lambda x: x.display_name.casefold()), questionnaire)
            if not r["ok"]:
                print(f"[SITE LOCAL] chef d'équipe de démonstration refusé : {r}")


#  Le questionnaire en ligne (26/10/2026) : des candidatures de plus, à l'étape du questionnaire, et un chef d'équipe.
TICKETS_CANDIDATURE = {"etapes": 60, "ancien": 61, "envoye": 62, "attente": 63}
CONSIGNES_DEMO = ("Quelques mots suffisent : un nom, un chiffre ou une courte phrase.",
                  "Tout se trouve dans les pages données plus haut.", "Dernière ligne droite : relis-toi avant d'envoyer.")


def _par_tiers(questions: list) -> tuple:
    """(les questions, chacune avec son `etape` 1..3 — trois parts qui se suivent, les rangs restent continus ; les étapes
    déclarées : numéro, titre tiré des thèmes, consigne) — le format de l'équipe du recrutement."""
    import questionnaire
    qs = [dict(q, etape=1 + k * 3 // len(questions)) for k, q in enumerate(questions)]
    titres: dict = {}
    for q in qs:
        nom = questionnaire.THEMES.get(q.get("theme") or "", "").split(" (")[0]
        if nom and nom not in titres.setdefault(q["etape"], []):
            titres[q["etape"]].append(nom)
    etapes = [{"numero": n, "titre": " · ".join(titres.get(n, [])[:2]) or f"Partie {n}", "consigne": CONSIGNES_DEMO[n - 1]}
              for n in (1, 2, 3)]
    return qs, etapes


async def _candidature_demo(get_db, g, ticket_ouvert) -> None:
    """Le questionnaire en ligne, joué par les VRAIS modules, au format du passage d'étape (`etape` sur chaque question,
    `etapes`, `etape_ouverte`, `etape_envoyee`, `etape_fiche` sur l'envoi — `etapes` posée ici si le parcours réglable ne
    l'a pas encore) : #60 trois étapes, la première ouverte (la fiche du ticket est l'étape 1 du candidat), ouverte par
    le candidat il y a trois minutes, deux brouillons ; #61 un questionnaire d'avant, sans étapes, jamais ouvert ; #62 un
    questionnaire d'avant répondu sur le site ; #63 trois étapes, la première envoyée, la direction décide ; et un
    questionnaire de CHEF D'ÉQUIPE (sans ticket) pour Kolax, invité par message privé."""
    import candidature_site
    import questionnaire
    chef = g.get_member(FONDATEUR)
    t = int(time.time())
    #  #61 et #62 : deux membres du clan (des questionnaires d'avant) — les candidats hors du clan restent libres pour les
    #  parcours (`outils/parcours_site.mjs` en prend trois, `parcours_candidature.mjs` un).
    qui = {60: g.get_member(1020), 61: g.get_member(1004), 62: g.get_member(1022), 63: g.get_member(1008)}
    async with get_db() as db:
        for tid, m in qui.items():
            await db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
                             (tid, SERVEUR_ID, 6000 + tid, m.id, "p1", FONDATEUR, "open",
                              json.dumps({"Pseudo Roblox": f"{m.display_name.split()[0]}_RS", "Niveau": "31"}),
                              _date(t - (64 - tid) * 3600)))
        await db.commit()
    envois = {}
    for tid, m in qui.items():
        ch, _tk = await ticket_ouvert(g, tid)
        await questionnaire.poser_etape1(g, ch, tid, m.id, nombre=await questionnaire.annonce(g.id))
        st, rep = await questionnaire.envoyer(g, tid, chef, {}, depuis="etape1")
        if st != 200:
            print(f"[SITE LOCAL] questionnaire en ligne de démonstration non envoyé : {rep}")
            return
        envois[tid] = await questionnaire._envoi(rep["envoi"])
    async with get_db() as db:
        async with db.execute("PRAGMA table_info(recrutement_envois)") as cur:
            if "etapes" not in [r[1] for r in await cur.fetchall()]:
                await db.execute("ALTER TABLE recrutement_envois ADD COLUMN etapes TEXT NOT NULL DEFAULT '[]'")
        for tid in (60, 63):   # trois étapes, la première ouverte ; la fiche du ticket est l'étape 1 du candidat
            qs, etapes = _par_tiers(envois[tid]["questions"])
            await db.execute("UPDATE recrutement_envois SET questions=?, etapes=?, etape_ouverte=1, etape_fiche=1 WHERE id=?",
                             (json.dumps(qs, ensure_ascii=False), json.dumps(etapes, ensure_ascii=False), envois[tid]["id"]))
        #  #60 : ouvert il y a trois minutes, deux brouillons (jamais des réponses).
        e = envois[60]
        await db.execute("INSERT OR IGNORE INTO candidature_etat (envoi_id, guild_id, ticket_id, candidat_id, ouvert_le,"
                         " vu_le, etape, rang) VALUES (?,?,?,?,?,?,1,2)", (e["id"], SERVEUR_ID, 60, qui[60].id, t - 180, t - 90))
        for rang, texte in ((1, "Je crois que c'est le studio qui a créé le jeu."),
                            (2, "Je vérifie sur le wiki avant de répondre")):
            await db.execute("INSERT INTO candidature_brouillons (envoi_id, rang, guild_id, candidat_id, texte, maj_le)"
                             " VALUES (?,?,?,?,?,?)", (e["id"], rang, SERVEUR_ID, qui[60].id, texte, t - 100 + rang * 5))
        await db.commit()
    #  #63 : la première étape envoyée par la page (`questionnaire.envoyer_etape`) — la direction décide de la suite.
    e = await candidature_site.envoi_complet(envois[63]["id"])
    await candidature_site.noter_ouverture(g, qui[63], e)
    premiere = {int(q["rang"]): f"Ma réponse à la question {int(q['rang'])}." for q in e["questions"]
                if questionnaire.etape_de_question(q) == 1}
    if not await questionnaire.envoyer_etape(e, t - 240, 1, premiere, g=g):
        print("[SITE LOCAL] étape de démonstration refusée")
    #  #62 : un questionnaire d'avant répondu sur le site — la même fin que la page (`envoyer_tout` : `clore_envoi`, puis
    #  l'annonce).
    e = envois[62]
    await candidature_site.noter_ouverture(g, qui[62], e)
    textes = {int(q["rang"]): f"Ma réponse à la question {int(q['rang'])}, écrite sur le site." for q in e["questions"]}
    if not await questionnaire.envoyer_tout(e, t - 60, textes, g=g):
        print("[SITE LOCAL] réponses de démonstration refusées")
    await _chef_demo(get_db, g)


#  Les questions de chef de la démonstration (la banque des chefs) : (question, réponse attendue).
QUESTIONS_CHEF_DEMO = (("Quel instrument mesure la hauteur du soleil au-dessus de l'horizon ?", "Le sextant"),
                       ("Comment appelle-t-on le côté droit d'un navire, regardé vers l'avant ?", "Tribord"),
                       ("Combien de quarts compte une journée de bord ?", "Six"),
                       ("Quel nœud sert à faire une boucle qui ne glisse pas ?", "Le nœud de chaise"))


async def _chef_demo(get_db, g) -> None:
    """Un questionnaire de chef d'équipe pour Kolax, par le VRAI chemin du site (`questionnaire.proposer_chef`, la route de
    « Proposer d'être chef ») : deux étapes de la banque des chefs (écrite ici), la première ouverte, l'invitation par
    message privé (la page du candidat : `candidature_site.inviter`, son bouton persistant)."""
    import questionnaire
    tete = g.get_member(FONDATEUR)
    cles = [m["cle"] for m in await questionnaire._liste_metiers(g)]
    metier = next((k for k in ("navigation", "navigateur") if k in cles), cles[0] if cles else "")
    if not metier:
        print("[SITE LOCAL] aucun métier : pas de chef d'équipe de démonstration")
        return
    ids = []
    for question, reponse in QUESTIONS_CHEF_DEMO:
        st, rep = await questionnaire._r_chef_question(g, tete, {}, {"question": question, "reponse": reponse,
                                                                     "metiers": [metier]})
        if st != 200:
            print(f"[SITE LOCAL] question de chef de démonstration refusée : {rep}")
            return
        ids.append(rep["question"]["id"])
    st, rep = await questionnaire._r_chef_proposer(g, tete, {}, {"membre": 1000, "metier": metier, "etapes": [
        {"titre": "Le cap", "consigne": "Chaque réponse doit être juste.", "questions": ids[:2]},
        {"titre": "L'équipage", "consigne": "Pense à ceux que tu guideras.", "questions": ids[2:]}]})
    if st != 200 or not rep.get("invite"):
        print(f"[SITE LOCAL] chef d'équipe de démonstration : {rep}")


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
        im = Image.new("RGB", (1600, 640), (31, 78, 90))   # une bannière aux dimensions exactes (bannieres.py)
        d = ImageDraw.Draw(im)
        for y in range(0, 640, 6):
            d.line((0, y, 1600, y), fill=(31 + y // 22, 78 + y // 36, 90 + y // 42))
        d.ellipse((630, 150, 970, 490), outline=(239, 226, 196), width=14)
        d.line((800, 165, 800, 475), fill=(239, 226, 196), width=12)
        tampon = io.BytesIO()
        im.save(tampon, "PNG")
        statut, rep = await tableau._route_media(g, chef, {}, {"nom": "movie3.png", "type": "image/png", "format": "banniere",
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


async def _equipage_demo(g) -> None:
    """Le site de l'équipage : l'accueil de départ (posé par le VRAI module), une image de bandeau et deux actualités de
    la direction (l'une épinglée, avec son image) — par les mêmes adresses que la page."""
    import base64
    import io

    import site_equipage
    import tableau
    chef = g.get_member(FONDATEUR)
    statut, accueil = await site_equipage.lecture_accueil(g, chef, {"portee": "tout"}, {})
    if statut != 200:
        print(f"[SITE LOCAL] accueil de l'équipage illisible : {accueil}")
        return

    async def image(nom, dessiner, taille):
        try:
            from PIL import Image, ImageDraw
        except ImportError:  # outil local : sans Pillow, pas d'image de démonstration
            return ""
        im = Image.new("RGB", taille, (20, 40, 52))
        dessiner(ImageDraw.Draw(im), *taille)
        tampon = io.BytesIO()
        im.save(tampon, "PNG")
        #  Le bandeau de l'Accueil et l'image d'une actualité : des bannières aux dimensions exactes (bannieres.py).
        st, rep = await tableau._route_media(g, chef, {}, {"nom": nom, "type": "image/png", "format": "banniere",
                                                           "base64": base64.b64encode(tampon.getvalue()).decode()})
        return rep.get("id", "") if st == 200 else ""

    def mer(d, larg, haut):
        """Un horizon au crépuscule et un trois-mâts en ombre chinoise."""
        for y in range(haut):
            k = y / haut
            couleur = (int(196 - 150 * k), int(120 - 80 * k), int(64 - 10 * k)) if y < haut * .58 else \
                (int(30 - 12 * k), int(58 - 20 * k), int(72 - 18 * k))
            d.line((0, y, larg, y), fill=couleur)
        d.ellipse((larg * .62, haut * .34, larg * .74, haut * .66), fill=(236, 196, 120))
        base = haut * .64
        d.polygon([(larg * .22, base), (larg * .46, base), (larg * .43, base + haut * .07), (larg * .25, base + haut * .07)],
                  fill=(18, 12, 8))
        for x, h_ in ((.28, .40), (.34, .48), (.40, .36)):
            d.line((larg * x, base, larg * x, base - haut * h_), fill=(18, 12, 8), width=max(2, larg // 300))
            d.polygon([(larg * x, base - haut * h_ * .92), (larg * (x + .045), base - haut * h_ * .5),
                       (larg * x, base - haut * h_ * .12)], fill=(30, 22, 14))

    def carte(d, larg, haut):
        """Une carte au trésor : le parchemin, un chemin pointillé, la croix."""
        d.rectangle((0, 0, larg, haut), fill=(226, 204, 158))
        for k in range(0, larg, 24):
            d.ellipse((k, haut * .78 - (k % 72), k + 8, haut * .78 - (k % 72) + 8), fill=(122, 75, 42))
        d.line((larg * .72, haut * .25, larg * .82, haut * .45), fill=(142, 42, 36), width=10)
        d.line((larg * .82, haut * .25, larg * .72, haut * .45), fill=(142, 42, 36), width=10)
        d.ellipse((larg * .08, haut * .12, larg * .30, haut * .52), outline=(43, 29, 18), width=6)

    fond = await image("bandeau-equipage.png", mer, (1600, 640))
    bandeau = next((b for b in accueil["blocs"] if b["type"] == "bandeau"), None)
    if fond and bandeau is not None:
        st, rep = await site_equipage._route_bloc(g, chef, {}, {"id": bandeau["id"], "version": bandeau["version"],
                                                                "contenu": dict(bandeau["contenu"], image=fond)})
        if st != 200:
            print(f"[SITE LOCAL] bandeau de démonstration refusé : {rep}")
    await _equipes_demo(g)
    tresor = await image("carte-tresor.png", carte, (1600, 640))
    for corps in ({"titre": "Bienvenue aux nouvelles recrues",
                   "texte": "Trois nouveaux matelots ont rejoint le navire cette semaine.\nPassez les saluer au **chat du clan**."},
                  {"titre": "Grande chasse au trésor samedi soir", "image": tresor, "epingle": True,
                   "texte": "Rendez-vous au port à **21 h**.\nLa carte est entre les mains du capitaine : "
                            "l'équipage qui trouve le coffre partage le butin."}):
        st, rep = await site_equipage._route_actualite(g, chef, {}, corps)
        if st != 200:
            print(f"[SITE LOCAL] actualité de démonstration refusée : {rep}")


EQUIPES_DEMO = (("Les Cuistots du Requin", "metier", "cooking"), ("La Garde du Navire", "libre", "Garde du navire"),
                ("La Vigie du Grand Mât", "metier", "navigation"), ("Les Écumeurs", "metier", "thieving"),
                ("Les Charpentiers", "metier", "woodcutting"), ("Les Toubibs", "metier", "doctor"),
                ("Les Mineurs de Corail", "metier", "mining"), ("L'Atelier des Forges", "metier", "crafting"),
                ("Les Pêcheurs de Perles", "metier", "fishing"), ("Les Abordeurs", "libre", "Abordage"),
                ("Les Canonniers", "libre", "Canonniers"), ("Les Éclaireurs", "libre", "Éclaireurs"))


async def _equipes_demo(g, lourd: bool = False) -> None:
    """Les équipes du clan (27/10/2026), par la VRAIE route de la direction : deux sur la base légère (un chef qui a son
    affiche, un autre sans), douze sur la base lourde (ses 80 membres du clan, quelques-uns sans équipe)."""
    import affiches
    import site_equipage
    tete = g.get_member(FONDATEUR)
    clan = sorted(m.id for m in site_equipage._membres_clan(await site_equipage._role_clan(g)))
    deja = await site_equipage._equipes(g.id)
    places = {e["chef_id"] for e in deja} | {m for e in deja for m in e["membres"]}
    libres = [i for i in clan if i not in places]
    types, elements = await affiches._catalogue()
    tm = site_equipage._type_metier(types)
    tailles = (6, 6, 6, 5, 5, 5, 5, 5, 4, 4) if lourd else ()
    plan = [(1000, (1001, 1003)), (1006, (1007, 1009))] if not lourd else []
    for k in range(len(deja), 12 if lourd else 2):
        nom, genre, valeur = EQUIPES_DEMO[k]
        if lourd:
            if len(libres) < 2:
                break
            chef, membres = libres[0], libres[1:1 + tailles[(k - 2) % len(tailles)]]
        else:
            chef, membres = plan[k]
            if chef not in libres:
                continue
            membres = [m for m in membres if m in libres]
        libres = [i for i in libres if i != chef and i not in membres]
        type_ = {"genre": "metier", "cle": valeur} if genre == "metier" and (tm, valeur) in elements else \
            {"genre": "libre", "texte": valeur if genre == "libre" else nom}
        statut, rep = await site_equipage._route_equipe(g, tete, {}, {"nom": nom, "type": type_, "chef": str(chef),
                                                                      "membres": [str(m) for m in membres]})
        if statut != 200:
            print(f"[SITE LOCAL] équipe de démonstration refusée : {rep}")


#  --lourd : des volumes de vrai serveur, pour éprouver le rangement des pages (groupes repliables, « Voir plus »,
#  alignements) — jamais utilisés par les tests (construire(lourd=False)).
SURNOMS = ("le Rouge", "Main-de-Fer", "des Abysses", "la Brune", "Bois-Flotté", "l'Écumeur", "Sans-Peur", "du Levant", "la Vigie",
           "Grand-Mât", "Barbe-Sel", "le Taciturne", "des Sept Mers et des Récifs Oubliés", "Œil-de-Lynx", "la Tempête")
MOTIFS_SANCTION = ("Spam dans le salon", "Insulte envers un membre", "Lien interdit", "Pub pour un autre serveur", "Hors sujet répété",
                   "Flood de mentions", "Contournement d'un mute", "Langage inapproprié en vocal", "Arnaque au trade", "Image interdite")
TEXTES_JOURNAL = (("Modération", "mod.warn", 1, "Avertissement : {n}"), ("Modération", "mod.mute", 2, "Mute : {n} (1 h)"),
                  ("Membres", "member.join", 0, "Arrivée : {n}"), ("Membres", "member.leave", 0, "Départ : {n}"),
                  ("Messages", "message.delete", 0, "Message supprimé de {n} dans le salon"),
                  ("Messages", "message.edit", 0, "Message modifié par {n} : « la réunion est déplacée à demain soir, prévenez les autres »"),
                  ("Vocal", "voice.join", 0, "Vocal : {n} rejoint « Taverne »"), ("Tickets", "ticket.open", 0, "Ticket ouvert par {n}"),
                  ("Tickets", "ticket.close", 0, "Ticket de {n} fermé"), ("Sécurité", "sec.spam", 2, "Spam bloqué : {n}"),
                  ("Sécurité", "sec.scam", 3, "Lien d'arnaque supprimé : {n}"), ("Clan", "clan.journal", 0, "Rôle du clan donné à {n}"),
                  ("Questions", "question.ouverte", 0, "Question relevée : {n}"))


async def _remplir_lourd(get_db, g, clan_r, salon) -> None:
    """Un serveur chargé : ~110 membres (80 au clan), 400 sanctions, 60 nettoyages du casier (des membres partis surtout),
    300 tickets, 1 000 lignes de journal, des questions, des idées, des sondages, 60 décisions de recrutement, des
    membres restreints par la direction. Appelé APRÈS le remplissage léger (ses index de membres restent les mêmes)."""
    import site_local_port
    hasard = random.Random(26102026)
    t = time.time()
    #  Les membres : 90 de plus (64 au clan), et 40 partis (cités par le casier, les tickets, le journal).
    nouveaux = []
    for k in range(90):
        nom = PRENOMS[k % len(PRENOMS)] + " " + SURNOMS[(k * 7) % len(SURNOMS)]
        m = g.membre(1100 + k, nom, *([clan_r] if k < 64 else []), arrivee_jours=hasard.randint(2, 700))
        nouveaux.append(m)
        #  Leur présence (site_local_port.mesurer_groupe) : surtout actifs, des peu présents, des inactifs, des jamais vus.
        tirage = hasard.random()
        site_local_port.ACTIVITE[m.id] = ((hasard.randint(0, 5), hasard.randint(1, 7)) if tirage < .55 else (hasard.randint(8, 28), 0) if tirage < .75
                                          else (hasard.randint(31, 160), 0) if tirage < .92 else None if tirage < .96 else "recent")
    presents = [m.id for m in g.members if m.id not in TETE and not m.bot]
    partis = [2000 + k for k in range(40)]
    gens = presents + partis
    staff = (FONDATEUR, DIRECTION, site_local_port.STAFF_ID)
    async with get_db() as db:
        #  400 sanctions sur un an.
        for n in range(400):
            uid = hasard.choice(gens)
            typ = hasard.choice(("warn", "warn", "warn", "warn", "mute", "mute", "insulte", "protection", "kick", "ban"))
            auto = typ in ("insulte", "protection")
            await db.execute("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration, created_at) VALUES (?,?,?,?,?,?,?)",
                             (SERVEUR_ID, uid, site_local_port.BOT_ID if auto else hasard.choice(staff), typ, hasard.choice(MOTIFS_SANCTION),
                              hasard.choice(("1 heure", "6 heures", "1 jour")) if typ == "mute" else "", _date(t - hasard.uniform(0, 365) ** 1.3 * 86400 / 7)))
        #  60 nettoyages du casier sur 30 jours : des amnisties, des casiers de membres (partis surtout), des zones, des annulés.
        sortes = ([("amnistie", 0, "Amnistie : 3 mois sans infraction, ou parti depuis 3 mois", None)] * 18
                  + [("membre", DIRECTION, "Avertissements de {}", "warns")] * 16 + [("membre", FONDATEUR, "Casier entier de {}", "tout")] * 18
                  + [("zone", FONDATEUR, "Avertissements, plus de 90 jours", None), ("zone", DIRECTION, "Détections automatiques, plus de 30 jours", None),
                     ("zone", FONDATEUR, "Tout le casier (sauf bannissements), plus de 90 jours", None)] * 2 + [("membre", DIRECTION, "Avertissements de {}", "warns")] * 2)
        for n, (prefixe, par, quoi, _quoi) in enumerate(sortes):
            cible = hasard.choice(partis if n % 4 else presents)
            quand = int(t - hasard.uniform(.02, 29.5) * 86400)
            restaure = n % 11 == 5
            await db.execute("INSERT INTO casier_lots (lot, guild_id, quand, par, quoi, n, personnes, restaure_le, restaure_par) VALUES (?,?,?,?,?,?,?,?,?)",
                             (f"{prefixe}-lourd-{n:03d}", SERVEUR_ID, quand, par, quoi.format(cible), hasard.randint(1, 9) if prefixe == "membre" else hasard.randint(4, 60),
                              1 if prefixe == "membre" else hasard.randint(2, 25), quand + 3600 if restaure else 0, DIRECTION if restaure else 0))
        #  300 tickets sur un an (une vingtaine ouverts, récents), avec leur prise en charge, leur fermeture et leur motif.
        motifs = site_local_port.MOTIFS
        for n in range(300):
            tid, uid = 100 + n, hasard.choice(gens)
            ouvert = t - (hasard.uniform(.1, 4) if n < 22 else hasard.uniform(1, 365)) * 86400
            ouvert_t = n < 22
            panneau = hasard.choice(("p2", "p3")) if ouvert_t else hasard.choice(("p1", "p2", "p2", "p3"))
            pris = hasard.choice(staff) if (not ouvert_t or n % 3) else 0
            await db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
                             (tid, SERVEUR_ID, 9000 + tid, uid, panneau, pris, "open" if ouvert_t else "closed", "{}", _date(ouvert)))
            if pris:
                await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, created_unix) VALUES (?,?,?,?,?)",
                                 (SERVEUR_ID, tid, "claim", pris, int(ouvert + hasard.randint(300, 20000))))
            if not ouvert_t:
                fin, qui_ferme, motif = int(ouvert + hasard.randint(1800, 400000)), hasard.choice(staff), motifs[n % len(motifs)]
                await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, detail, created_unix) VALUES (?,?,?,?,?,?)",
                                 (SERVEUR_ID, tid, "close", qui_ferme, motif, fin))
                await db.execute("INSERT INTO ticket_audit (guild_id, channel_id, action, actor_id, at, detail) VALUES (?,?,?,?,?,?)",
                                 (SERVEUR_ID, 9000 + tid, "close", qui_ferme, _date(fin), motif))
        #  1 000 lignes de journal sur 30 jours (la page en lit les 400 plus récentes).
        noms = {m.id: m.display_name for m in g.members}
        for n in range(1000):
            cat, typ, gravite, texte = hasard.choice(TEXTES_JOURNAL)
            uid = hasard.choice(gens)
            await db.execute("INSERT INTO registre (guild_id, quand, categorie, type, membre_id, auteur_id, salon_id, texte, detail, gravite)"
                             " VALUES (?,?,?,?,?,?,?,?,?,?)", (SERVEUR_ID, int(t - hasard.uniform(0, 30) ** 1.4 * 86400 / 3.3), cat, typ, uid,
                                                               hasard.choice((0, 0, FONDATEUR, DIRECTION, site_local_port.STAFF_ID)), salon.id,
                                                               texte.format(n=noms.get(uid, "Membre parti")), "", gravite))
        #  Des questions (ouvertes, répondues, traitées), des idées, des sondages.
        for n in range(40):
            quand, statut = int(t - hasard.uniform(.05, 25) * 86400), hasard.choice(("ouverte", "ouverte", "repondue", "resolue", "traitee", "ignoree"))
            repondu = statut in ("repondue", "resolue")
            await db.execute("INSERT INTO questions (guild_id, salon_id, message_id, auteur_id, texte, quand, statut, repondu_par, repondu_le, par_staff, lien)"
                             " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (SERVEUR_ID, salon.id, 7500 + n, hasard.choice(presents),
                                                                  hasard.choice(("Comment on rejoint le clan ?", "C'est quand le prochain raid sur le boss des abysses avec tout l'équipage ?",
                                                                                 "Où trouver le marchand de fruits ?", "On peut changer de faction après le Movie 3 ?",
                                                                                 "Qui vient farmer des berrys ce soir ?")) + f" ({n})", quand, statut,
                                                                  site_local_port.STAFF_ID if repondu else 0, quand + 3600 if repondu else 0, 1 if repondu else 0,
                                                                  f"https://discord.com/channels/{SERVEUR_ID}/{salon.id}/{7600 + n}"))
        for n in range(15):
            statut = hasard.choice(("attente", "attente", "etude", "acceptee", "refusee", "realisee"))
            await db.execute("INSERT INTO suggestions_v2 (guild_id, channel_id, message_id, auteur_id, titre, details, statut, note, decide_par, cree_le, decide_le)"
                             " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (SERVEUR_ID, salon.id, 8300 + n, hasard.choice(presents),
                                                                  f"Idée n°{n + 10} : " + hasard.choice(("un tournoi de pêche", "un salon pour les cartes au trésor",
                                                                                                         "des grades pour les vétérans du clan et ceux qui aident les nouveaux",
                                                                                                         "un événement chaque samedi")),
                                                                  "Pour motiver l'équipage et accueillir les nouveaux.", statut,
                                                                  "" if statut == "attente" else "Bonne idée, on regarde.", 0 if statut == "attente" else DIRECTION,
                                                                  _date(t - hasard.uniform(1, 60) * 86400), _date(t - hasard.uniform(0, 1) * 86400)))
        for n in range(8):
            await db.execute("INSERT INTO sondages (message_id, guild_id, channel_id, auteur_id, question, choix, comptes, total, cree_le, fin_le, termine)"
                             " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (8400 + n, SERVEUR_ID, salon.id, hasard.choice(presents), f"Sondage n°{n + 3} : quel soir pour le raid ?",
                                                                  json.dumps(["Vendredi", "Samedi", "Dimanche"]), json.dumps([n + 2, 5, 3]), n + 10,
                                                                  _date(t - (n + 1) * 2 * 86400), _date(t + (1 - n) * 86400), 1 if n > 1 else 0))
        #  60 décisions de recrutement (acceptées, refusées) sur un an.
        for n in range(60):
            uid = hasard.choice(gens)
            ferme = t - hasard.uniform(1, 365) * 86400
            decision = "acceptes" if n % 3 else "refuses"
            await db.execute("INSERT OR REPLACE INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom, ouvert_le, ferme_le, ferme_par, pris_par, reponses,"
                             " msg_candidat, msg_staff, transcript, raison, decision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (SERVEUR_ID, 1000 + n, uid, noms.get(uid, f"Ancien candidat {n}"), int(ferme - 7200), int(ferme), DIRECTION, FONDATEUR,
                              json.dumps({"Pseudo Roblox": f"Candidat_{n}", "Pourquoi nous ?": "J'aime naviguer en équipage."}), 3, 2, "",
                              "" if decision == "acceptes" else hasard.choice(("Niveau insuffisant", "Réponses trop vagues", "N'a pas répondu")), decision))
        #  Des membres restreints par la direction (dates ISO, comme les écrit /mod direction) — durée en minutes, 0 : sans fin.
        for k, (duree, raison) in enumerate(((0, "Comportement à surveiller pendant l'enquête"), (1440, "Spam répété dans les salons"),
                                             (180, "Contournement d'un mute"), (0, ""))):
            cible = nouveaux[3 + 11 * k]
            await db.execute("INSERT INTO restricted_members VALUES (?,?,?,?,?,?,?)",
                             (SERVEUR_ID, cible.id, "[]", datetime.fromtimestamp(t - (k + 1) * 9000, timezone.utc).isoformat(), duree, raison,
                              DIRECTION if k % 2 else FONDATEUR))
        await db.commit()
    #  Quatorze affiches de plus (le mur rangé par métier) : des éléments du catalogue chargé, jamais inventés.
    import affiches
    par_type: dict = {}
    for e in (await affiches.catalogue())["elements"]:
        if e["actif"]:
            par_type.setdefault(e["type"], []).append(e["cle"])
    chef = g.get_member(FONDATEUR)
    for k, m in enumerate(nouveaux[:14]):
        corps = {"id": f"lourd-affiche-{k:02d}", "membre_id": str(m.id), "roblox_nom": f"Pirate_{k:02d}", "surnom": SURNOMS[k % len(SURNOMS)][:40],
                 "prime": hasard.randint(1, 400) * 10000, "niveau": hasard.randint(1, 90), "statut": "actif",
                 "attributs": {t: [hasard.choice(par_type[t])] for t in ("metier", "race", "faction") if par_type.get(t)}}
        statut, rep = await affiches._route_affiche(g, chef, {}, corps)
        if statut != 200:
            print(f"[SITE LOCAL] affiche lourde refusée : {rep}")
    print("[SITE LOCAL] volumes lourds : 110 membres, 400 sanctions, 60 nettoyages du casier, 300 tickets, 1 000 lignes de journal")


def main() -> int:
    parser = argparse.ArgumentParser(description="Le vrai site en local, avec un faux serveur Discord.")
    parser.add_argument("--port", type=int, default=PORT, help=f"le port ({PORT} par défaut)")
    parser.add_argument("--qui", choices=("fondateur", "direction"), default="fondateur",
                        help="le compte de l'entrée de démonstration")
    parser.add_argument("--garder", default="", help="dossier de travail gardé (sinon un dossier temporaire)")
    parser.add_argument("--site", default="", help="servir un autre dossier « site/ » (sinon celui du dépôt)")
    parser.add_argument("--lourd", action="store_true",
                        help="des volumes de vrai serveur (400 sanctions, 60 nettoyages du casier, 300 tickets, 1 000 lignes de journal…)")
    args = parser.parse_args()
    from aiohttp import web

    async def lancer():
        if args.site:
            import tableau
            tableau.SITE = Path(args.site).resolve()
        app, ctx = await construire(Path(args.garder) if args.garder else None, args.port,
                                    DIRECTION if args.qui == "direction" else FONDATEUR, lourd=args.lourd)
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
