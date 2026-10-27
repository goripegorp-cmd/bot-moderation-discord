"""Revue du 24/10/2026 — tickets, recrutements, transcripts. Un test (ou plus) par constat corrigé :
le motif d'un refus reste à l'équipe, la note interne ne va plus dans le ticket, jamais de salon supprimé
sans transcript, seuls la direction et les comptes de tête voient tout, le recours a son panneau et se ferme,
l'équipe d'un type a ses boutons, plus de 40 composants, la décision ne se devine plus dans le texte, les
fils hors cache, la prise en charge acquittée et unique, les textes vrais, tout l'historique, « Ce salon »
après redémarrage, la confidentialité des pages de transcript, l'index d'abord."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord
import pytest

import health_server
import owner_ids
import recrutements
import registre
import rellseas_panneau
import tickets_enhance
import tickets_fils
import transcript_store
import visuels
from conftest_discord import Obj
from faux_serveur import Texte, compter, textes
from ui_v2 import LayoutView, Palette, carte_embed

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
TETE = frozenset({781205382923288593, 827633340797681714})
FONDATEUR = 781205382923288593


def _source(nom):
    for n in ARBRE.body:
        cible = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else
                                              getattr(getattr(n, "target", None), "id", None))
        if cible == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


def _ns(*noms, **plus):
    import textes as module_textes   # le registre des textes (bot.py : `import textes`) ; `textes` ici lit les vues
    ns = {"discord": discord, "asyncio": asyncio, "json": json, "re": re, "io": io, "datetime": datetime,
          "textes": module_textes, "tickets_interdits": __import__("tickets_interdits"),
          "timezone": timezone, "time": __import__("time"), "LayoutView": LayoutView, "Palette": Palette,
          "visuels": visuels, "tickets_fils": tickets_fils, "transcript_store": transcript_store,
          "rellseas_ui": rellseas_panneau, "carte_embed": carte_embed, "Button": discord.ui.Button,
          "Select": discord.ui.Select, "View": discord.ui.View, "Modal": discord.ui.Modal,
          "TextInput": discord.ui.TextInput, "TETE_IDS": TETE, "owner_ids_module": owner_ids,
          "_logerr": lambda *a, **k: None, "ZoneInfo": None,
          "now": lambda: datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)}
    ns.update(plus)
    for nom in noms:
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def _base(tmp_path, *tables):
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
            for t in tables:
                await db.execute(t)
            await db.commit()
    asyncio.run(preparer())
    return get_db


TICKETS = ("CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id, channel_id, user_id, panel_id,"
           " claimed_by, status, answers, created_at)")
EVENEMENTS = ("CREATE TABLE ticket_log_events (id INTEGER PRIMARY KEY, guild_id, ticket_id, kind, actor_id, detail,"
              " created_unix)")
MESSAGES_LOG = "CREATE TABLE ticket_log_msgs (guild_id, ticket_id, message_id, PRIMARY KEY (guild_id, ticket_id))"
TRANSCRIPTS = ("CREATE TABLE ticket_transcripts (guild_id, ticket_id, user_id, user_name, panel, url, closed_at,"
               " jeton TEXT, PRIMARY KEY (guild_id, ticket_id))")


def _lire(get_db, sql, args=()):
    async def lire():
        async with get_db() as db:
            async with db.execute(sql, args) as cur:
                return await cur.fetchall()
    return asyncio.run(lire())


class _Role:
    def __init__(self, rid, nom, position, managed=False, membres=()):
        self.id, self.name, self.position, self.managed = rid, nom, position, managed
        self.mention, self.members = f"<@&{rid}>", list(membres)

    def is_default(self):
        return False


class _Guilde:
    def __init__(self, roles=(), membres=(), salons=(), fils=(), owner_id=99):
        self.id, self.owner_id, self.name = 1, owner_id, "GoRP SEA"
        self.roles = list(roles)
        self._roles = {r.id: r for r in roles}
        self._membres = {m.id: m for m in membres}
        self.salons = {s.id: s for s in salons}
        self.fils_hors_cache = {f.id: f for f in fils}
        self.default_role, self.me, self.owner = Obj(id=1), Obj(id=999), None

    def get_role(self, rid):
        return self._roles.get(int(rid or 0))

    def get_member(self, uid):
        return self._membres.get(int(uid or 0))

    def get_channel(self, cid):
        return self.salons.get(int(cid or 0))

    def get_channel_or_thread(self, cid):
        return self.salons.get(int(cid or 0))

    async def fetch_channel(self, cid):
        x = self.salons.get(int(cid)) or self.fils_hors_cache.get(int(cid))
        if x is None:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return x


def _membre(uid, *roles, admin=False):
    return Obj(id=uid, roles=list(roles), guild_permissions=Obj(administrator=admin), bot=False,
               display_name=f"Membre{uid}", name=f"m{uid}", mention=f"<@{uid}>",
               display_avatar=Obj(url=f"https://cdn.discordapp.com/avatars/{uid}.png"))


class _Fil(discord.Thread):
    """Un fil de ticket : un vrai `discord.Thread` pour les `isinstance` du bot."""
    parent = None

    def __init__(self, tid, nom="ticket-kolax", messages=()):
        self.id, self.name, self._messages = tid, nom, list(messages)
        self.envois, self.edits, self.ajoutes, self.supprime = [], [], [], False
        self._membres_cache = []

    members = property(lambda self: self._membres_cache)

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))
        return Obj(id=1)

    async def edit(self, **kw):
        self.edits.append(kw)

    async def delete(self, **_kw):
        self.supprime = True

    async def add_user(self, m):
        self.ajoutes.append(m)

    def history(self, limit=None, oldest_first=False, **_k):
        async def gen():
            for m in (self._messages if oldest_first else self._messages[::-1])[:limit]:
                yield m
        return gen()


async def _rien(*_a, **_k):
    return None


# ═══ 1. Le motif d'un refus reste à l'équipe ══════════════════════════════════════════════════════════════

def test_1_un_refus_ferme_avec_une_raison_neutre_le_motif_reste_au_staff():
    fermetures, journal = [], []
    ch, tk = Obj(id=77), {"id": 5, "user": 7, "claimed": 2, "answers": {}, "panel_id": "p1"}

    async def ouvert(_g, _tid):
        return ch, tk

    async def fermer(*a, **k):
        fermetures.append((a, k))

    async def journaliser(_g, texte, **_k):
        journal.append(texte)
    ns = _ns("_TACHES_FERMETURE", "_fermer_en_fond", "_decision_recrutement", _ticket_ouvert=ouvert,
             _fermer_ticket=fermer, _journal_rellseas=journaliser, log_staff_action=_rien, cfg=_rien)
    g, auteur = Obj(id=1, get_member=lambda _u: None), _membre(2)

    async def scenario():
        ok, message = await ns["_decision_recrutement"](g, 5, auteur, False, "niveau trop bas")
        await asyncio.sleep(0)
        return ok, message
    ok, message = asyncio.run(scenario())
    assert ok and message == "Candidature refusée : ticket fermé."
    (args, kw), = fermetures
    assert args[4] == "Refusé : niveau trop bas", "le motif reste dans l'historique et le suivi (staff)"
    assert kw["public"] == "Candidature refusée", "le candidat lit une raison neutre"
    assert args[2]["decision"] == "refuses", "la décision suit le ticket jusqu'au suivi des recrutements"
    assert "niveau trop bas" in journal[-1], "le journal du site garde le motif"


def test_1b_le_mp_et_l_annonce_disent_la_raison_publique(tmp_path):
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(id, guild_id, channel_id, user_id, status) "
                                      "VALUES (5, 1, 77, 7, 'open')"))
    vus, mp = {}, []

    async def log(*_a, **k):
        vus["extra"] = k.get("extra")
        return True

    async def audit(*a):
        vus["audit"] = a[4]

    class Createur:
        async def send(self, **kw):
            mp.append(kw["content"])
    salon = Texte(None, 77, "ticket-kolax", {})
    salon.monde = Obj(nouvel_id=lambda: 1)
    supprimes = []

    async def supprimer(**_k):
        supprimes.append(True)
    salon.delete = supprimer
    ns = _ns("_fermer_ticket_corps", send_ticket_log=log, _recent_transcript_urls={"5": "https://bot.exemple/t/tok"},
             _ticket_transcript_html=_rien, _ticket_transcript_file=_rien, _ticket_feedback_view=lambda *a: None,
             get_db=get_db, tix_module=Obj(log_action=audit), asyncio=Obj(sleep=_rien))
    g = Obj(id=1, name="GoRP", get_member=lambda _u: Createur())
    tk = {"id": 5, "user": 7, "decision": "refuses"}
    asyncio.run(ns["_fermer_ticket_corps"](g, salon, tk, _membre(2), "Refusé : niveau trop bas",
                                           public="Candidature refusée"))
    assert "**Raison :** Candidature refusée" in mp[0] and "niveau" not in mp[0], "le MP ne dit pas le motif"
    annonce = salon.envois[-1][1]
    assert "Candidature refusée" in annonce and "niveau" not in annonce, "l'annonce dans le fil non plus"
    assert vus["extra"] == "Refusé : niveau trop bas" and "niveau" in vus["audit"], "le staff garde le motif"
    assert supprimes, "transcript enregistré : le salon part"
    assert "le motif reste à l'équipe" in textes(recrutements.carte_decision(5)), "la carte de décision le dit"


async def _executer_sql(get_db, sql, args=()):
    async with get_db() as db:
        await db.execute(sql, args)
        await db.commit()


# ═══ 2. La note interne ne va plus dans le ticket ═════════════════════════════════════════════════════════

def test_2_la_note_interne_va_au_suivi_jamais_dans_le_ticket():
    journal, audit, suivis = [], [], []

    async def log(g, lt, user, ti, extra=None, **_k):
        journal.append((lt, extra))
        return True

    async def action(*a):
        audit.append(a)

    async def poster(*_a, **_k):
        raise AssertionError("la note ne doit jamais être postée dans le ticket")

    async def suivre(*a, **k):
        suivis.append((a, k))
    ns = _ns("NOTE_MAX", "_vue_ticket_message", "TicketNoteModal", send_ticket_log=log,
             tix_module=Obj(log_action=action), webhook_send=poster)
    modal = ns["TicketNoteModal"]({"id": 5, "user": 7, "panel_id": "p1"})
    etiquette = modal.note._underlying.label  # (`.label` est déprécié dans discord.py 2.7)
    assert len(modal.title) <= 45 and len(etiquette) <= 45 and "ne la voit pas" in etiquette
    assert modal.note.max_length == ns["NOTE_MAX"] == 300, "rien de tronqué en silence (suivi : 300 caractères)"
    modal.note._value = "Le membre ment : en attente d'une preuve"
    i = Obj(guild=Obj(id=1), channel=Obj(id=77, send=poster), user=_membre(2),
            response=Obj(defer=_rien), followup=Obj(send=suivre))
    asyncio.run(modal.on_submit(i))
    assert journal == [("note", (2, "Le membre ment : en attente d'une preuve"))], "le suivi du ticket (site)"
    assert audit == [(1, 77, 2, "note", "Le membre ment : en attente d'une preuve")], "l'historique « Gérer »"
    (_a, kw), = suivis
    assert kw["ephemeral"] and "ne la voit pas" in textes(kw["view"]), "une confirmation au seul staff"


# ═══ 3. Jamais de salon supprimé sans transcript ══════════════════════════════════════════════════════════

def test_3_sans_transcript_le_fil_est_garde_renomme_et_le_staff_prevenu(tmp_path):
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(id, guild_id, channel_id, user_id, status) "
                                      "VALUES (5, 1, 9001, 7, 'open')"))
    journal, prevenu = [], []

    async def log(*_a, **_k):
        return False  # le transcript n'a pas pu être enregistré

    async def au_journal(_g, cat, type_, texte, **_k):
        journal.append((type_, texte))

    async def prevenir(texte):
        prevenu.append(texte)
    ns = _ns("_fermer_ticket_corps", "_garder_ticket_sans_transcript", send_ticket_log=log,
             _recent_transcript_urls={}, _ticket_transcript_html=_rien, _ticket_transcript_file=_rien,
             _ticket_feedback_view=lambda *a: None, get_db=get_db, tix_module=Obj(log_action=_rien),
             asyncio=Obj(sleep=_rien), _au_journal=au_journal)
    fil = _Fil(9001)
    g = Obj(id=1, name="GoRP", get_member=lambda _u: None)
    asyncio.run(ns["_fermer_ticket_corps"](g, fil, {"id": 5, "user": 7}, _membre(2), "Résolu", prevenir=prevenir))
    assert not fil.supprime, "la conversation n'est pas perdue"
    assert fil.edits == [{"name": "⚠️・sans-transcript-ticket-kolax", "archived": True, "locked": True}]
    assert not any("Suppression dans 5 s" in str(c) for c, _k in fil.envois), "aucune annonce qui mentirait"
    assert prevenu and "n'a pas pu être enregistré" in prevenu[0] and "gardé" in prevenu[0]
    assert journal and journal[0][0] == "ticket.sans_transcript"
    assert _lire(get_db, "SELECT status FROM tickets") == [("closed",)], "le ticket est fermé, son fil gardé"
    corps = _source("TicketCloseModal")
    assert "prevenir=_prevenir" in corps and "ephemeral=True" in corps, "le staff qui ferme est prévenu à lui seul"


def _banc_log(tmp_path, conf, rendu, dossier=None, logerr=None):
    """`send_ticket_log` exécuté pour de vrai (base réelle, transcript_store doublé)."""
    get_db = _base(tmp_path, EVENEMENTS, MESSAGES_LOG, TRANSCRIPTS)
    enregistres, erreurs = [], []

    async def cfg(_g):
        return conf

    async def enregistrer(*a, **k):
        enregistres.append((a, k))

    class Journal:
        propre = staticmethod(registre.propre)

        async def noter(self, *a, **k):
            return True
    ns = _ns("_ticket_event_parts", "_ticket_timeline_line", "_EVENEMENTS_TICKET", "send_ticket_log",
             cfg=cfg, get_db=get_db, db_set=_rien, _render_ticket_transcript_html=rendu, _ticket_transcript_file=_rien,
             _recent_transcript_urls={}, C=Obj(GREEN=1, BLUE=2, RED=3, BLURPLE=4), registre=Journal(),
             recrutements=Obj(enregistrer=enregistrer), RECOURS_PID="recours",
             _salon_transcripts_rellseas=_rien, _vue_recrutement=lambda *a: LayoutView(),
             _logerr=logerr or (lambda *a, **k: erreurs.append(a)),
             transcript_store=Obj(public_base_url=lambda: "https://bot.exemple", new_token=lambda: "tok",
                                  save_html=lambda t, h: True, transcript_url=lambda t: f"https://bot.exemple/t/{t}"))
    if dossier is not None:
        ns["_dossier_recrutement"] = dossier
    return ns, get_db, enregistres, erreurs


def test_3b_send_ticket_log_dit_si_la_conversation_est_conservee(tmp_path):
    conf = {"logs_sur_site_v1": "oui", "ticket_panels": {"p2": {"name": "Support"}}}
    membre = Obj(id=7, display_name="Kolax", name="kolax")
    g = Obj(id=1, get_channel=lambda _i: None, get_member=lambda _u: membre)

    async def echec(*_a, **_k):
        return None  # l'historique illisible : pas de transcript
    ns, get_db, _e, _err = _banc_log(tmp_path, conf, echec)
    tk = {"id": 6, "panel_id": "p2"}
    assert asyncio.run(ns["send_ticket_log"](g, "create", membre, tk)) is True
    assert asyncio.run(ns["send_ticket_log"](g, "close", membre, tk, extra="Résolu", closer=Obj(id=2),
                                             ch=Obj(id=77))) is False
    assert _lire(get_db, "SELECT * FROM ticket_transcripts") == [], "rien d'indexé : rien n'existe"

    async def rendu(*_a, **_k):
        return "<html>conversation</html>"
    autre = tmp_path / "b"
    autre.mkdir()
    ns, get_db, _e, _err = _banc_log(autre, conf, rendu)
    assert asyncio.run(ns["send_ticket_log"](g, "close", membre, {"id": 7, "panel_id": "p2"}, extra="Résolu",
                                             closer=Obj(id=2), ch=Obj(id=78))) is True
    assert _lire(get_db, "SELECT ticket_id, jeton FROM ticket_transcripts") == [(7, "tok")]


# ═══ 4. Seuls le rôle direction et les comptes de tête voient tout ═══════════════════════════════════════

def _roles_direction():
    staff, direction = _Role(7, "Staff", 2), _Role(20, "Direction", 10)
    deco, robot, rell = _Role(40, "✨ VIP décoratif", 12), _Role(41, "Bot", 13, managed=True), _Role(8, "Recrue", 14)
    return staff, direction, deco, robot, rell


def test_4_la_direction_c_est_le_role_direction_et_les_comptes_de_tete():
    staff, direction, deco, robot, rell = _roles_direction()
    fondateur = _membre(FONDATEUR)
    g = _Guilde([staff, direction, deco, robot, rell], [fondateur])
    c = {"direction_allowed_role": 20, "ticket_staff": 7, "rellseas_roles_autorises": [8],
         "ticket_panels": {"p1": {"name": "Support", "staff_role": 7}}}
    ns = _ns("_equipe_direction", "_au_dessus_de_la_direction")
    assert ns["_equipe_direction"](g, c) == [direction, fondateur], "plus aucun rôle rangé au-dessus"
    assert ns["_au_dessus_de_la_direction"](g, c) == [deco], \
        "à nettoyer : le rôle décoratif — pas le bot (géré), pas le staff, pas le clan"


def test_4b_retirer_n_enleve_que_ce_que_le_bot_a_pose():
    staff, direction, deco, robot, rell = _roles_direction()
    autre, main = _Role(42, "Autre", 15), _Role(43, "Réglé à la main", 16)
    melange = discord.PermissionOverwrite(**tickets_fils.DROITS_EQUIPE)
    melange.send_messages = False
    salon = Texte(None, 77, "🎫・tickets-staff", {"overwrites": {
        deco: discord.PermissionOverwrite(**tickets_fils.DROITS_EQUIPE), autre: melange,
        main: discord.PermissionOverwrite(view_channel=True, manage_threads=True)}})
    n = asyncio.run(tickets_fils.retirer(salon, [deco, autre, main]))
    assert n == 2
    assert salon.kw["overwrites"][deco] is None, "posé par le bot : la permission disparaît"
    reste = salon.overwrites_for(autre)
    assert reste.send_messages is False and reste.manage_threads is None, "le réglage à la main reste, sans « Gérer les fils »"
    assert salon.overwrites_for(main).manage_threads is True, "un réglage qui n'est pas celui du bot : intact"


def test_4c_le_nettoyage_une_fois_retire_les_roles_decoratifs(tmp_path):
    staff, direction, deco, robot, rell = _roles_direction()
    fondateur = _membre(FONDATEUR)
    porteur = Texte(None, 77, "🎫・tickets-staff", {"overwrites": {
        staff: discord.PermissionOverwrite(**tickets_fils.DROITS_EQUIPE),
        direction: discord.PermissionOverwrite(**tickets_fils.DROITS_EQUIPE),
        deco: discord.PermissionOverwrite(**tickets_fils.DROITS_EQUIPE)}})
    classique = Texte(None, 78, "ticket-kolax", {"overwrites": {
        deco: discord.PermissionOverwrite(**tickets_fils.DROITS_SALON)}})
    g = _Guilde([staff, direction, deco, robot, rell], [fondateur], [porteur, classique])
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, status) "
                                      "VALUES (1, 78, 3, 'p1', 'open')"))
    conf = {"direction_allowed_role": 20, "ticket_staff": 7, tickets_fils.CLE_PARENTS: {"40:7": 77},
            "ticket_panels": {"p1": {"name": "Support", "staff_role": 7}}}
    journal = []

    async def cfg(_g):
        return conf

    async def au_journal(*a, **_k):
        journal.append(a[3])
    ns = _ns("_equipe_direction", "_au_dessus_de_la_direction", "_equipe_du_type", "_tickets_visibilite",
             cfg=cfg, get_db=get_db, _au_journal=au_journal)
    asyncio.run(ns["_tickets_visibilite"](g))
    assert porteur.kw["overwrites"][deco] is None and classique.kw["overwrites"][deco] is None, \
        "le rôle décoratif ne lit plus les tickets privés"
    assert porteur.overwrites_for(direction).manage_threads and porteur.overwrites_for(fondateur).manage_threads
    assert classique.overwrites_for(staff).view_channel, "l'équipe du type garde son ticket"
    assert "2 accès retiré(s)" in journal[-1]
    tache = _source("entraide_task")
    debut = tache.index("if not c.get('tickets_visibilite_v2'):")
    bloc = tache[debut:tache.index("if ", debut + 10)]
    assert bloc.index("db_set(g.id, 'tickets_visibilite_v2'") < bloc.index("_tickets_visibilite(g)"), \
        "une fois, marqué avant (jamais deux nettoyages en parallèle)"
    assert "await _rafraichir_hub_tickets(g)" in bloc, "le panneau unifié déjà posé perd sa promesse fausse"


# ═══ 5. Le hub ne promet plus de prévenir ; la recherche et le départ trouvent les fils ═══════════════════

def test_5_le_hub_ne_promet_plus_l_equipe_prevenue():
    hub = _source("_build_ticket_hub_view")
    assert "prévenue" not in hub and "seuls toi et l'équipe concernée le voyez" in hub
    assert "PLUS de ping à la création" in SRC, "la décision du fondateur (20/07), à l'origine de ce choix"
    assert "allowed_mentions=discord.AllowedMentions.none()" in _source("_create_ticket_corps")


def test_5b_ticket_search_donne_un_lien_vers_le_fil(tmp_path):
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(guild_id, channel_id, user_id, claimed_by, status,"
                                      " created_at) VALUES (1, 9001, 7, 0, 'open', '2026-10-24 10:00:00')"))
    reponses = []

    async def oui(_i):
        return True

    async def suivre(texte, **kw):
        reponses.append((texte, kw))
    sans_effet = Obj(command=lambda **k: (lambda f: f), describe=lambda **k: (lambda f: f))
    ns = _ns("ticket_search_cmd", get_db=get_db, _tix_staff=oui, ticket_group=sans_effet, app_commands=sans_effet)
    i = Obj(guild=Obj(id=1, get_channel=lambda _c: None), response=Obj(defer=_rien), followup=Obj(send=suivre))
    asyncio.run(ns["ticket_search_cmd"](i))
    texte, kw = reponses[0]
    assert "<#9001>" in texte and "`#9001`" not in texte, "un fil (même hors cache) est un lien, pas un identifiant"
    assert kw["allowed_mentions"].users is False


def test_5c_le_depart_du_membre_s_ecrit_dans_son_fil(tmp_path):
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(guild_id, channel_id, user_id, claimed_by, status,"
                                      " answers, panel_id) VALUES (1, 9001, 7, 0, 'open', '{}', 'p1')"))
    fil, envois, logs = _Fil(9001), [], []
    g = _Guilde(fils=[fil])

    async def webhook_send(ch, plateforme, **kw):
        envois.append((ch, kw))

    async def log(g_, lt, user, ti, **_k):
        logs.append((lt, ti.get("panel_id")))
    ns = _ns("on_member_remove", bot=Obj(event=lambda f: f), get_db=get_db, send_ticket_log=log,
             webhook_send=webhook_send, C=Obj(ORANGE=1), print=lambda *a, **k: None)
    m = _membre(7)
    m.guild = g
    asyncio.run(ns["on_member_remove"](m))
    assert logs == [("leave", "p1")]
    assert envois and envois[0][0] is fil, "le fil archivé (hors cache) est retrouvé et reçoit la carte"
    assert "Utilisateur parti" in str(envois[0][1]["view"].to_components())


# ═══ 6. Le recours a son panneau et se ferme à la décision ════════════════════════════════════════════════

def test_6_le_recours_ne_compte_pas_dans_le_maximum_du_type_serveur(tmp_path):
    get_db = _base(tmp_path, TICKETS)

    async def remplir():
        async with get_db() as db:
            await db.executemany("INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, status, answers)"
                                 " VALUES (?,?,?,?,?,?)",
                                 [(1, 501, 7, "p1", "open", json.dumps({"recours": True})),  # recours d'avant
                                  (1, 502, 7, "recours", "open", json.dumps({"recours": True}))])
            await db.commit()
    asyncio.run(remplir())

    async def existe(_g, _c):
        return True
    ns = _ns("count_user_tickets", get_db=get_db, tickets_fils=Obj(existe=existe), RECOURS_MARQUE='"recours": true')
    g = Obj(id=1)
    assert asyncio.run(ns["count_user_tickets"](g, 7, "p1")) == 0, "« Lever la radiation » : le ticket Serveur s'ouvre"
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, status, answers)"
                                      " VALUES (1, 503, 7, 'p1', 'open', ?)", (json.dumps({"Sujet": "recours"}),)))
    assert asyncio.run(ns["count_user_tickets"](g, 7, "p1")) == 1, "un vrai ticket Serveur compte toujours"
    assert "(guild.id, ch.id, membre.id, RECOURS_PID," in _source("_ouvrir_ticket_recours")


def test_6b_la_decision_ferme_le_ticket_de_recours_sans_mp():
    lances = []

    async def fermer(*a, **k):
        lances.append((a, k))

    async def get_ticket(_cid):
        return {"id": 9, "user": 42, "panel_id": "recours"}
    ns = _ns("_TACHES_FERMETURE", "_fermer_en_fond", "_fermer_recours", get_ticket=get_ticket, _fermer_ticket=fermer)
    i = Obj(guild=Obj(id=1), channel=Obj(id=77), user=_membre(50))

    async def scenario():
        ok = await ns["_fermer_recours"](i, "Recours accepté : radiation levée")
        await asyncio.sleep(0)
        return ok
    assert asyncio.run(scenario()) is True
    (args, kw), = lances
    assert args[4] == "Recours accepté : radiation levée" and kw == {"mp": False}, "la décision est déjà partie en MP"
    assert asyncio.run(ns["_fermer_recours"](Obj(guild=Obj(id=1), user=i.user), "x")) is False

    fermes = []

    async def noter(i_, raison):
        fermes.append(raison)

    async def carte(*_a):
        return None
    ns2 = _ns("RadieDecisionButton", _autorise_radiation=_rien, _lever_radiation=_rien, _prevenir_radie=_rien,
              _carte_recours_decidee=carte, _fermer_recours=noter, _fiche_sanction=_rien)   # aucune restriction
    i2 = Obj(response=Obj(defer=_rien), followup=Obj(send=_rien), user=Obj(mention="<@50>"), message=Obj(),
             guild=Obj(id=1, get_member=lambda _u: Obj(mention="<@42>")))
    asyncio.run(ns2["RadieDecisionButton"]("lever", 42).callback(i2))
    assert fermes == ["Recours accepté : radiation levée"], "fermé à la décision"


# ═══ 7 et 14. L'équipe d'un type a ses boutons ; la direction aussi ══════════════════════════════════════

def _monde_equipes():
    globale, equipe, rell, direction = _Role(7, "Staff", 5), _Role(8, "Équipe Support", 3), _Role(9, "Recruteur", 2), \
        _Role(20, "Direction", 10)
    a, b, robot = _membre(11, equipe), _membre(12, rell), _membre(13, equipe)
    robot.bot = True
    equipe.members, rell.members = [a, robot], [b]
    chef, personne = _membre(21, direction), _membre(30)
    g = _Guilde([globale, equipe, rell, direction], [a, b, chef, personne])
    conf = {"ticket_staff": 7, "direction_allowed_role": 20, "rellseas_roles_autorises": [9],
            "ticket_panels": {"p1": {"name": "Support", "staff_role": 8}, "p2": {"name": "Rell Seas"}}}
    return g, conf, a, b, chef, personne


def _ns_droits(conf, **plus):
    async def cfg(_g):
        return conf

    async def jamais(_m):
        return False
    return _ns("_direction_ou_plus", "_equipe_du_type", "_droit_ticket", "_equipe_disponible", cfg=cfg,
               is_fully_immune=jamais, **plus)


def test_7_un_seul_calcul_des_droits_l_equipe_du_type_et_la_direction():
    g, conf, a, b, chef, personne = _monde_equipes()
    ns = _ns_droits(conf)
    droit = lambda m, pid: asyncio.run(ns["_droit_ticket"](Obj(guild=g, user=m), {"panel_id": pid}, conf))
    assert droit(a, "p1") == "equipe", "le rôle qui gère ce panneau (sous le staff global)"
    assert droit(b, "p2") == "equipe", "l'équipe Rell Seas pour ses tickets"
    assert droit(b, "p1") == "" and droit(a, "p2") == "", "chaque équipe ses tickets"
    assert droit(chef, "p1") == "chef" and droit(chef, "p2") == "chef", "la direction partout"
    assert droit(personne, "p1") == "" and droit(_membre(99), "p1") == "chef", "le propriétaire aussi"
    dispo = ns["_equipe_disponible"](g, conf, {"panel_id": "p1", "claimed": 0, "user": 3})
    assert dispo == [a], "Ajouter / Transférer : l'équipe du type, sans les bots"


def test_7b_les_boutons_reconnaissent_l_equipe_du_type():
    g, conf, a, b, chef, personne = _monde_equipes()
    envois = []

    async def get_ticket(_c):
        return {"id": 1, "user": 3, "claimed": 0, "panel_id": "p1", "answers": {}}

    async def envoyer(*args, **kw):
        envois.append(kw.get("view") or args[0])

    async def enregistre(*_a):
        return True
    ns = _ns_droits(conf, get_ticket=get_ticket, TicketPriorityView=lambda _c: "menu des priorités",
                    TicketCloseReasonView=lambda _t: "motifs", db_set=enregistre, send_ticket_log=_rien,
                    _vue_blacklist=lambda *a: "carte d'interdiction")
    exec(_source("TicketControlView"), ns)  # noqa: S102 — code du dépôt
    vue = ns["TicketControlView"]()

    def cliquer(bouton, m):
        envois.clear()
        i = Obj(guild=g, user=m, channel=Obj(id=77), response=Obj(send_message=envoyer, is_done=lambda: False))
        asyncio.run(getattr(vue, bouton).callback(i))
        return envois[-1]
    assert cliquer("priority", a) == "menu des priorités" and cliquer("close", a) == "motifs"
    assert "Réservé à l'équipe" in cliquer("priority", personne)
    assert cliquer("blacklist_user", chef) == "carte d'interdiction", "la direction peut interdire (elle était refusée)"
    assert "permission de blacklister" in cliquer("blacklist_user", personne)


def test_14_le_menu_des_etiquettes_revérifie_avec_la_meme_regle():
    vus = []

    async def oui(_i):
        return "equipe"

    async def non(_i):
        return ""

    async def repondre(*a, **k):
        vus.append(("refus", a))

    async def editer(**k):
        vus.append(("vue", k))

    def interaction():
        etat = {"fait": False}

        async def defer(**_k):
            etat["fait"] = True
        return Obj(user=Obj(id=5, roles=[], guild_permissions=Obj(administrator=False)), guild=Obj(owner_id=1),
                   response=Obj(is_done=lambda: etat["fait"], defer=defer, send_message=repondre),
                   edit_original_response=editer, followup=Obj(send=repondre))
    for autorise, attendu in ((oui, "vue"), (non, "refus")):
        vus.clear()
        vue = asyncio.run(tickets_enhance.build_ticket_manage_panel(77, 1, 0, autorise=autorise))
        menu = next(c for c in vue.walk_children() if isinstance(c, discord.ui.Select))
        asyncio.run(menu.callback(interaction()))
        assert vus and vus[0][0] == attendu, autorise


# ═══ 8. Plus de 40 composants : un menu déroulant ═════════════════════════════════════════════════════════

@pytest.mark.parametrize("n", [1, 10, 11, 12, 25, 30])
def test_8_le_menu_direction_tient_dans_les_limites_de_discord(n):
    conf = {"ticket_panels": {f"p{k}": {"name": f"Type de ticket très long numéro {k} " + "x" * 60,
                                        "disabled": k % 3 == 0} for k in range(n)}}
    rafraichis = []

    async def cfg(_g):
        return conf

    async def rafraichir(_g, **k):
        rafraichis.append(k.get("types"))
    ns = _ns("VueTypesTickets", cfg=cfg, db_set=_db_set(conf), _au_journal=_rien, _rafraichir_hub_tickets=rafraichir,
             _direction_ou_plus=lambda g, m, c: True)
    vue = ns["VueTypesTickets"](5, conf)
    assert compter(vue) <= 40 and len(textes(vue)) <= 4000, (n, compter(vue))
    menus = [c for c in vue.walk_children() if isinstance(c, discord.ui.Select)]
    if n <= 10:
        assert not menus
        return
    (menu,) = menus
    assert len(menu.options) == min(n, 25) and len({o.value for o in menu.options}) == len(menu.options)
    edits = []

    async def editer(**k):
        edits.append(k)
    i = Obj(guild=Obj(id=1), user=_membre(5), data={"values": ["p1"]}, response=Obj(edit_message=editer))
    asyncio.run(menu.callback(i))
    assert conf["ticket_panels"]["p1"]["disabled"] is True and rafraichis == [{"p1"}], "le type choisi bascule"
    assert compter(edits[-1]["view"]) <= 40


def _db_set(conf):
    async def db_set(_g, k, v):
        conf[k] = v
    return db_set


# ═══ 9. La décision ne se devine plus dans le texte libre ═════════════════════════════════════════════════

def test_9_lecture_prudente_des_anciens_motifs():
    d = recrutements.decision
    assert d(False, "Non admis") == "refuses"
    assert d(False, "Candidature pas acceptée") == "refuses"
    assert d(False, "pas encore accepté") == "refuses"
    assert d(False, "Recrutements fermés pour le moment") is None, "pas une décision"
    assert d(False, "On recrute à nouveau en novembre") is None
    assert d(False, "Accepté, bienvenue dans l'équipage") == "acceptes"
    assert d(False, "Recruté !") == "acceptes" and d(False, "Refusé : trop jeune") == "refuses"
    assert d(True, "") == "acceptes" and d(False, "Résolu") is None
    assert d(False, "Non admis", "acceptes") == "acceptes", "la décision enregistrée fait foi"


def test_9b_la_decision_des_boutons_est_enregistree_et_fait_foi(tmp_path):
    get_db = _base(tmp_path, "CREATE TABLE recrutements (guild_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL,"
                             " candidat_id INTEGER NOT NULL, candidat_nom TEXT, ouvert_le INTEGER, ferme_le INTEGER"
                             " NOT NULL, ferme_par INTEGER, pris_par INTEGER, reponses TEXT, msg_candidat INTEGER"
                             " DEFAULT 0, msg_staff INTEGER DEFAULT 0, transcript TEXT, raison TEXT DEFAULT '',"
                             " PRIMARY KEY (guild_id, ticket_id))")
    conf = {"ticket_panels": {"p1": {"name": "Rellseas"}}}

    async def cfg(_g):
        return conf
    role = Obj(id=50)
    recrutements.setup(get_db=get_db, cfg=cfg, db_set=_db_set(conf), salon=_rien, role=lambda g, c: role,
                       panneaux=rellseas_panneau.panneaux_tickets, log=lambda *a: None)
    asyncio.run(recrutements.init_db())
    assert "decision" in [r[1] for r in _lire(get_db, "PRAGMA table_info(recrutements)")], "base ancienne : migrée"
    t0 = int(datetime(2026, 10, 3, 12, tzinfo=timezone.utc).timestamp())

    def ev(motif, j):
        return [("create", 7, "", t0 + j * 86400), ("close", 2, motif, t0 + j * 86400 + 60)]
    part = [{"id": 0, "nom": "c", "bot": False, "n": 3}]

    async def remplir():
        for tid, uid, motif, dec in ((1, 101, "Refusé : Recrutements fermés pour le moment", "refuses"),
                                     (2, 102, "Recrutements fermés pour le moment", ""),
                                     (3, 103, "Non admis", ""), (4, 104, "Candidature pas acceptée", ""),
                                     (5, 105, "Accepté", "acceptes")):
            await recrutements.enregistrer(1, tid, uid, f"C{uid}", ev(motif, tid),
                                           {}, [dict(part[0], id=uid)], "", decision=dec)
        await recrutements.enregistrer(1, 6, 106, "C106", ev("x", 6), {}, None, "")
    asyncio.run(remplir())
    g = Obj(id=1, get_member=lambda _u: None)
    donnees = asyncio.run(recrutements.candidatures(g, "2026-10"))
    statuts = {f["candidat_id"]: f["statut"] for f in donnees["fiches"]}
    assert statuts == {101: "refuses", 103: "refuses", 104: "refuses", 105: "acceptes"}, \
        "« Recrutements fermés » n'est plus un Accepté ; « Non admis », « pas acceptée » sont des refus"
    assert _lire(get_db, "SELECT msg_candidat FROM recrutements WHERE ticket_id=6") == [(None,)], \
        "conversation illisible : compteurs inconnus, pas « ticket vide »"
    assert [x["statut"] for x in asyncio.run(recrutements.du_candidat(1, 105))] == ["acceptes"]


# ═══ 10. Les fils hors cache sont retrouvés ; le menu « Ajouter » répond toujours ═══════════════════════

def test_10_un_fil_archive_est_un_ticket_ouvert(tmp_path):
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(id, guild_id, channel_id, user_id, claimed_by, status,"
                                      " answers, panel_id) VALUES (5, 1, 9001, 7, 0, 'open', '{}', 'p1')"))
    fil = _Fil(9001)
    ns = _ns("get_ticket", "_ticket_ouvert", get_db=get_db)
    ch, tk = asyncio.run(ns["_ticket_ouvert"](_Guilde(fils=[fil]), 5))
    assert ch is fil and tk["id"] == 5, "archivé (hors cache) : toujours ouvert"
    assert asyncio.run(ns["_ticket_ouvert"](_Guilde(), 5)) == (None, None), "disparu : plus ouvert"


def test_10b_ajouter_un_staff_hors_cache_et_toujours_une_reponse():
    fil, suivis, cartes = _Fil(9001), [], []
    staff = _membre(5)

    async def suivre(*a, **k):
        suivis.append((a, k))

    async def poster(ch, plateforme, **kw):
        cartes.append(ch)

    async def get_ticket(_c):
        return {"id": 1, "user": 3, "claimed": 2, "panel_id": "p1"}

    class G(_Guilde):
        async def fetch_member(self, uid):
            if uid != 5:
                raise discord.NotFound(Obj(status=404, reason="x"), "absent")
            return staff
    ns = _ns("_repondre_ticket", "_vue_ticket_message", "_carte_ticket", "AddStaffSelect", webhook_send=poster,
             get_ticket=get_ticket, send_ticket_log=_rien)

    def choisir(uid, g):
        suivis.clear()
        sel = ns["AddStaffSelect"]([discord.SelectOption(label="x", value=str(uid))], 9001)
        sel._values = [str(uid)]
        i = Obj(guild=g, user=_membre(2), response=Obj(defer=_rien, is_done=lambda: True), followup=Obj(send=suivre))
        asyncio.run(sel.callback(i))
        return suivis
    r = choisir(5, G(fils=[fil]))
    assert fil.ajoutes == [staff] and cartes == [fil] and "ajouté au ticket" in textes(r[0][1]["view"])
    r = choisir(6, G(fils=[fil]))
    assert r and "n'existe plus" in r[0][0][0], "un membre parti : on le dit (avant : aucune réponse)"


# ═══ 11. La prise en charge : acquittée d'abord, une seule à la fois ════════════════════════════════════

def _banc_claim(tmp_path, droit="equipe"):
    get_db = _base(tmp_path, TICKETS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(id, guild_id, channel_id, user_id, claimed_by, status,"
                                      " answers, panel_id) VALUES (1, 1, 9001, 3, 0, 'open', '{}', 'p1')"))
    ordre, annonces = [], []
    fil = _Fil(9001)

    async def envoyer(content=None, **kw):
        annonces.append(textes(kw["view"]))
    fil.send = envoyer

    async def droit_ticket(*_a, **_k):
        return droit

    async def cfg(_g):
        return {}

    async def dossier(*_a, **_k):
        return "dossier"
    ns = _ns("get_ticket", "_repondre_ticket", "_carte_ticket", "TicketControlView", get_db=get_db, cfg=cfg,
             _droit_ticket=droit_ticket, _equipe_du_type=lambda *_a: (None, [], ""), _equipe_direction=lambda *_a: [],
             _claims_en_cours=set(), _vue_dossier_ticket_de=dossier, send_ticket_log=_rien,
             tix_module=Obj(log_action=_rien))
    vrai_get_ticket = ns["get_ticket"]

    async def get_ticket(cid):
        ordre.append("base")
        await asyncio.sleep(0.01)
        return await vrai_get_ticket(cid)
    ns["get_ticket"] = get_ticket
    g = Obj(id=1, default_role=Obj(id=1), me=Obj(id=999), owner=None, owner_id=99, get_role=lambda _r: None,
            get_member=lambda _u: None)

    def interaction(m):
        repondu = []

        async def defer(**_k):
            ordre.append("acquitté")

        async def editer(**k):
            repondu.append(("carte", k))

        async def suivre(texte, **k):
            repondu.append(("éphémère", texte))
        i = Obj(guild=g, user=m, channel=fil, message=Obj(flags=Obj(components_v2=True)),
                response=Obj(defer=defer), edit_original_response=editer, followup=Obj(send=suivre))
        return i, repondu
    return ns, get_db, ordre, annonces, interaction


def test_11_acquitte_d_abord_et_une_seule_prise_en_charge(tmp_path):
    ns, get_db, ordre, annonces, interaction = _banc_claim(tmp_path)
    vue = ns["TicketControlView"]()
    (i1, r1), (i2, r2) = interaction(_membre(11)), interaction(_membre(12))

    async def deux_clics():
        await asyncio.gather(vue.claim.callback(i1), vue.claim.callback(i2))
    asyncio.run(deux_clics())
    assert ordre[0] == "acquitté", "on répond avant la base et le réseau"
    assert _lire(get_db, "SELECT claimed_by FROM tickets") == [(11,)]
    assert len(annonces) == 1 and "prend ce ticket en charge" in annonces[0], "une seule prise en charge"
    assert r1 and r1[0] == ("carte", {"view": "dossier"}), "le dossier est réécrit après l'acquittement"
    assert r2 == [("éphémère", "⏳ Ce ticket est déjà en train d'être pris en charge.")]
    i3, r3 = interaction(_membre(12))
    asyncio.run(vue.claim.callback(i3))
    assert "déjà pris par <@11>" in r3[0][1] and _lire(get_db, "SELECT claimed_by FROM tickets") == [(11,)]


# ═══ 12. Des textes vrais : fermeture auto, transfert, interrupteurs ═════════════════════════════════════

def test_12_la_fermeture_automatique_ne_promet_plus_de_mp():
    assert "MP au créateur" not in _source("ticket_auto_close_cmd")
    assert "le créateur n'est pas prévenu" in _source("ticket_auto_close_cmd")
    assert "MP au créateur." not in ast.get_docstring(next(n for n in ARBRE.body if getattr(n, "name", "") ==
                                                            "tickets_inactifs_task"))


def _message_dossier(v2=True, webhook=None):
    edits = []

    async def edit(**k):
        edits.append(k)
    m = Obj(id=500, components=[Obj(children=[Obj(custom_id="ticket_ctrl_claim")])], flags=Obj(components_v2=v2),
            webhook_id=webhook, edit=edit)
    return m, edits


def test_12b_le_transfert_reecrit_le_dossier():
    async def dossier(_g, tk, pris_par=0):
        return f"dossier pris par {pris_par}"
    wh_edits = []

    async def wh_edit(mid, **k):
        wh_edits.append((mid, k))

    async def get_webhook(_ch, plateforme):
        return Obj(id=55, edit_message=wh_edit)
    ns = _ns("_custom_ids_du_message", "_rafraichir_dossier", _vue_dossier_ticket_de=dossier, get_webhook=get_webhook)
    for v2, webhook in ((True, None), (True, 55), (False, None)):
        msg, edits = _message_dossier(v2, webhook)
        salon = _Fil(9001, messages=[Obj(components=[]), msg])
        ok = asyncio.run(ns["_rafraichir_dossier"](Obj(id=1), salon, {"id": 1}, 12))
        if not v2:
            assert not ok and not edits, "un ancien dossier (encadré) reste tel quel"
        elif webhook:
            assert ok and wh_edits == [(500, {"view": "dossier pris par 12"})], "posté par le webhook : réécrit par lui"
        else:
            assert ok and edits == [{"view": "dossier pris par 12"}]
    assert "await _rafraichir_dossier(i.guild, ch, tk, new_staff.id)" in _source("TransferTicketSelect")


def test_12c_l_interrupteur_et_le_menu_direction_se_suivent():
    class Salon(discord.TextChannel):
        def __init__(self, messages):
            self.id, self._m = 40, messages

        def history(self, limit=None):
            async def gen():
                for m in self._m[:limit]:
                    yield m
            return gen()
    edits = []

    def message(mid, *ids, v2=True):
        async def edit(**k):
            edits.append((mid, k))
        return Obj(id=mid, author=Obj(id=999), flags=Obj(components_v2=v2), edit=edit,
                   components=[Obj(children=[Obj(custom_id=x) for x in ids])])

    async def hub(_g):
        return "hub"

    async def panneau(_g, pid):
        return f"panneau {pid}"
    salon = Salon([message(1, "tickethub:open", "tickethub:gerer"), message(2, "ticket_create_p1", "ticket_toggle_p1"),
                   message(3, "ticket_create_p2", "ticket_toggle_p2"), message(4, "ticket_toggle_p1"),
                   message(5, "ticket_toggle_p1", v2=False)])
    ns = _ns("_custom_ids_du_message", "_rafraichir_hub_tickets", _salon_des_tickets=lambda _g: salon,
             bot=Obj(user=Obj(id=999)), _build_ticket_hub_view=hub, _build_ticket_panel_view=panneau)
    assert asyncio.run(ns["_rafraichir_hub_tickets"](Obj(id=1), types={"p1"}, sauf=4)) is True
    assert edits == [(1, {"view": "hub"}), (2, {"view": "panneau p1"}),
                     (5, {"content": None, "embed": None, "attachments": [], "view": "panneau p1"})], \
        "le hub, les panneaux du type changé ; pas l'autre type ni le message déjà réécrit"
    assert "await _rafraichir_hub_tickets(i.guild, types={str(pid)}, sauf=" in _source("_ticket_toggle_click")


# ═══ 13. Tout l'historique, les plus récents gardés, et on le dit ═══════════════════════════════════════

def _messages(n):
    t = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    return [Obj(author=Obj(display_name=f"M{k % 2}", bot=False,
                           display_avatar=Obj(url="https://cdn.discordapp.com/avatars/a.png")),
                created_at=t + timedelta(minutes=k), content=f"message {k}", attachments=[], embeds=[], stickers=[])
            for k in range(n)]


def test_13_au_dela_du_plafond_les_plus_recents_et_une_ligne_qui_le_dit(tmp_path):
    ns = _ns("_historique_ticket", "_note_tronque", "_image_sure", "_HOTES_IMAGES", "_resolve_transcript_text",
             "_cartes_v2", "_html_lignes_v2", "_html_carte_v2", "_message_en_donnees", "_render_ticket_transcript_html",
             "_conversation_seule", _TRANSCRIPT_CSS="", CONVERSATION_MAX=3)
    salon = _Fil(9001, messages=_messages(5))
    lus, tronque = asyncio.run(ns["_historique_ticket"](salon, 3))
    assert [m.content for m in lus] == ["message 2", "message 3", "message 4"] and tronque, \
        "les DERNIERS messages, dans l'ordre (avant : les premiers, la fin manquait sans le dire)"
    assert asyncio.run(ns["_historique_ticket"](_Fil(1, messages=_messages(3)), 3))[1] is False
    html = asyncio.run(ns["_render_ticket_transcript_html"](salon, 5))
    assert "message 4" in html and "message 1" not in html and "(les plus récents)" in html
    relus = transcript_store._Lecteur().lire(html)
    assert relus[0]["auteur"] == "Transcript" and "seuls les 3 derniers messages" in relus[0]["texte"]
    get_db = _base(tmp_path, TICKETS, TRANSCRIPTS)
    asyncio.run(_executer_sql(get_db, "INSERT INTO tickets(id, guild_id, channel_id, status) VALUES (5, 1, 9001, 'open')"))

    async def trouver(_g, _c):
        return salon
    ns.update(get_db=get_db, tickets_fils=Obj(salon=trouver))
    direct = asyncio.run(ns["_conversation_seule"](Obj(id=1, get_member=lambda _u: None, get_role=lambda _r: None,
                                                        get_channel=lambda _c: None), 5))
    assert direct["messages"] == relus, "en direct comme relu : la même ligne en tête, les mêmes messages"
    assert "tronque" not in direct, "« les N premiers » (site) serait faux : les plus récents sont gardés"
    assert "limit=1000" not in _source("_render_ticket_transcript_html") + _source("_conversation_seule")


# ═══ 15. « Ce salon » après un redémarrage ════════════════════════════════════════════════════════════════

def test_15_les_membres_d_un_fil_au_cache_vide_sont_demandes(monkeypatch):
    class Fil(_Fil):
        def __init__(self, reponse):
            super().__init__(9001)
            self.reponse, self.demandes = reponse, 0

        async def fetch_members(self):
            self.demandes += 1
            if isinstance(self.reponse, Exception):
                raise self.reponse
            if self.reponse == "lent":
                await asyncio.sleep(1)
            return [Obj(id=4), Obj(id=5)]
    g = Obj(get_member=lambda uid: Obj(id=uid, display_name=f"M{uid}", bot=False))

    def membres(salon):
        return asyncio.run(rellseas_panneau._membres_du_salon_frais(Obj(guild=g, channel=salon)))
    fil = Fil("ok")
    assert [m.id for m in membres(fil)] == [4, 5] and fil.demandes == 1, "après un redémarrage : demandé à Discord"
    fil._membres_cache = [Obj(id=6)]
    assert [m.id for m in membres(fil)] == [6] and fil.demandes == 1, "cache rempli : pas d'appel"
    panne = discord.HTTPException(Obj(status=500, reason="x"), "panne")
    assert membres(Fil(panne)) == [], "une panne : pas de raccourci, pas d'erreur"
    monkeypatch.setattr(rellseas_panneau, "DELAI_MEMBRES_FIL", 0.05)
    assert membres(Fil("lent")) == [], "borné dans le temps (le clic a 3 s)"
    assert "SALONS TEXTE avec permissions\n    (`create_text_channel" not in Path(rellseas_panneau.__file__).read_text(
        encoding="utf-8"), "la docstring dit vrai : des fils privés"


# ═══ 16. Les pages de transcript ne montrent pas l'adresse IP du lecteur ══════════════════════════════════

def test_16_les_images_passent_par_le_relais_de_discord():
    ns = _ns("_image_sure", "_HOTES_IMAGES")
    sure = ns["_image_sure"]
    assert sure(Obj(url="https://pirate.exemple/x.gif", proxy_url="https://images-ext-1.discordapp.net/external/a")) \
        == "https://images-ext-1.discordapp.net/external/a"
    assert sure(Obj(url="https://pirate.exemple/x.gif", proxy_url=None)) == "", "sans relais : jamais affichée"
    assert sure(Obj(url="https://cdn.discordapp.com/attachments/1/2/a.png")) == "https://cdn.discordapp.com/attachments/1/2/a.png"
    assert sure(Obj(url="http://media.discordapp.net/a.png")) == "" and sure(None) == ""
    image = discord.Embed.from_dict({"title": "Lien", "image": {"url": "https://pirate.exemple/espion.gif",
                                                                 "proxy_url": "https://images-ext-2.discordapp.net/e/x"}})
    m = _messages(1)[0]
    m.embeds = [image]
    ns2 = _ns("_historique_ticket", "_note_tronque", "_image_sure", "_HOTES_IMAGES", "_resolve_transcript_text",
              "_cartes_v2", "_html_lignes_v2", "_html_carte_v2", "_message_en_donnees", "_render_ticket_transcript_html",
              _TRANSCRIPT_CSS="", CONVERSATION_MAX=50)
    html = asyncio.run(ns2["_render_ticket_transcript_html"](_Fil(1, messages=[m]), 5))
    assert "pirate.exemple" not in html and "images-ext-2.discordapp.net" in html
    assert ns2["_message_en_donnees"](m, None)["images"] == ["https://images-ext-2.discordapp.net/e/x"]


def test_16b_entetes_des_pages_de_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_store, "_BASE_DIR", str(tmp_path / "transcripts"))
    jeton = transcript_store.new_token()
    assert transcript_store.save_html(jeton, "<html>ok</html>")
    assert transcript_store.save_asset(jeton, 0, b"\x89PNG....", "png")

    class Requete:
        def __init__(self, **infos):
            self.match_info = infos
    page = asyncio.run(health_server._transcript_handler(Requete(token=jeton)))
    csp = page.headers["Content-Security-Policy"]
    assert "img-src *" not in csp and "img-src 'self' https://cdn.discordapp.com https://*.discordapp.net" in csp
    assert "media-src 'self' https://cdn.discordapp.com https://*.discordapp.net" in csp, "les vidéos s'affichent"
    assert "script-src" not in csp and "default-src 'none'" in csp, "toujours aucun script"
    assert "noindex" in page.headers["X-Robots-Tag"]
    absente = asyncio.run(health_server._transcript_handler(Requete(token="x" * 22)))
    assert absente.status == 404 and "noindex" in absente.headers["X-Robots-Tag"]
    image = asyncio.run(health_server._asset_handler(Requete(token=jeton, idx="0")))
    assert "noindex" in image.headers["X-Robots-Tag"] and "sandbox" in image.headers["Content-Security-Policy"]


# ═══ 17. L'index du transcript d'abord ═════════════════════════════════════════════════════════════════════

def test_17_le_transcript_est_indexe_meme_si_le_dossier_echoue(tmp_path):
    conf = {"ticket_log": 55, "ticket_panels": {"p1": {"name": "Recrutement Rell Seas"}}}
    envois = []

    class Salon(discord.TextChannel):
        def __init__(self):
            self.id = 55

        async def send(self, content=None, **kw):
            envois.append(kw)
            return Obj(id=900)

        async def fetch_message(self, _i):
            raise discord.NotFound(Obj(status=404, reason="x"), "x")
    lch = Salon()
    membre = Obj(id=7, display_name="Kolax", name="kolax")
    g = Obj(id=1, get_channel=lambda i: lch if i == 55 else None, get_member=lambda _u: membre)

    async def rendu(*_a, **_k):
        return "<html>conversation</html>"

    async def dossier(*_a, **_k):
        raise RuntimeError("history limit=5000 en panne")
    ns, get_db, enregistres, erreurs = _banc_log(tmp_path, conf, rendu, dossier=dossier)
    ok = asyncio.run(ns["send_ticket_log"](g, "close", membre, {"id": 5, "panel_id": "p1", "decision": "acceptes"},
                                           extra="Accepté", closer=Obj(id=2), ch=Obj(id=77)))
    assert ok is True, "la page est écrite et indexée : la conversation est conservée"
    assert _lire(get_db, "SELECT ticket_id, url, jeton FROM ticket_transcripts") == [(5, "https://bot.exemple/t/tok", "tok")]
    assert [e[0] for e in erreurs] == ["ticket.dossier_recrutement"], "l'erreur est journalisée, pas avalée"
    (args, kw), = enregistres
    assert args[6] is None and kw == {"decision": "acceptes"}, "le suivi des recrutements est quand même écrit"
