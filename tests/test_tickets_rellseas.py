"""19/10/2026 : « un salon transcript pour les tickets de type Rell Seas, avec un vrai transcript
de recrutement par personne et de vrais logs complets… quand ça se clôture on sait exactement
qui a dit quoi »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosqlite
import discord

import registre
import rellseas_panneau
import visuels
from ui_v2 import LayoutView, Palette, carte_embed

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign))
                and (getattr(n, "name", "") == nom
                     or any(getattr(t, "id", "") == nom for t in getattr(n, "targets", []))))


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Salon(discord.TextChannel):
    def __init__(self, sid, nom, categorie=None):
        self.id, self.name, self._categorie = sid, nom, categorie
        self.envois = []

    @property
    def category(self):
        return self._categorie

    @property
    def overwrites(self):
        return {"staff": "voit"}

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))
        return Obj(id=900 + len(self.envois))

    async def fetch_message(self, _i):
        raise discord.NotFound(Obj(status=404, reason="x"), "x")


def _message(auteur, texte, minutes):
    return Obj(author=auteur, content=texte, embeds=[], attachments=[],
               created_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes))


class Journal:
    """Le registre du site, tel que le ticket l'appelle."""
    propre = staticmethod(registre.propre)

    def __init__(self):
        self.lignes = []

    async def noter(self, gid, categorie, type_, texte, **kw):
        self.lignes.append((categorie, type_, texte, kw))
        return True


def test_T1_ticket_rellseas_dans_son_salon_avec_le_dossier_complet(tmp_path, site=False):
    base = tmp_path / "t.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE ticket_log_events (id INTEGER PRIMARY KEY, guild_id, "
                             "ticket_id, kind, actor_id, detail, created_unix)")
            await db.execute("CREATE TABLE ticket_log_msgs (guild_id, ticket_id, message_id, "
                             "PRIMARY KEY (guild_id, ticket_id))")
            await db.execute("CREATE TABLE ticket_transcripts (guild_id, ticket_id, user_id, "
                             "user_name, panel, url, closed_at, jeton TEXT, PRIMARY KEY (guild_id, ticket_id))")
            await db.commit()
    asyncio.run(preparer())

    conf = {"ticket_log": 55, "ticket_panels": {"p1": {"name": "🏴‍☠️ Recrutement Rell Seas"},
                                                "p2": {"name": "Support"}}}
    if site:
        conf["logs_sur_site_v1"] = "2026-10-19T20:00:00"
    journal = Journal()
    logs = Salon(55, "logs-tickets", categorie="LOGS")
    salons = {55: logs}
    candidat = Obj(id=7, display_name="Kolax", name="kolax_", bot=False)
    staff = Obj(id=2, display_name="Capitaine", name="cap", bot=False)
    robot = Obj(id=3, display_name="GoRP", name="gorp", bot=True)

    async def creer(nom, **kw):
        s = Salon(56, nom, kw.get("category"))
        salons[56] = s
        return s
    g = Obj(id=1, get_channel=salons.get, me=Obj(guild_permissions=Obj(manage_channels=True)),
            get_member={7: candidat, 2: staff}.get, create_text_channel=creer)

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v

    async def rendu(*_a, **_k):
        return "<html>conversation</html>"

    class Ticket:
        def history(self, limit=None, oldest_first=False, **_k):
            """Comme Discord : du plus récent au plus ancien, sauf `oldest_first`."""
            async def gen():
                messages = [_message(robot, "Bienvenue", 0), _message(candidat, "Bonjour, je veux rejoindre", 1),
                            _message(staff, "Ton niveau ?", 2), _message(candidat, "2400\net je joue chaque soir", 3)]
                for m in (messages if oldest_first else messages[::-1])[:limit]:
                    yield m
            return gen()
    enregistres = []

    async def enregistrer(*a, **k):
        enregistres.append(a)
    ns = {"cfg": cfg, "get_db": get_db, "db_set": db_set, "discord": discord, "io": io, "re": re,
          "asyncio": asyncio, "datetime": datetime, "timezone": timezone, "ZoneInfo": ZoneInfo,
          "_TICKET_TZ": "Europe/Paris", "rellseas_ui": rellseas_panneau, "visuels": visuels,
          "LayoutView": LayoutView, "Palette": Palette, "carte_embed": carte_embed,
          "now": lambda: datetime(2026, 10, 19, 12, 30, tzinfo=timezone.utc),
          "C": Obj(GREEN=1, BLUE=2, RED=3, BLURPLE=4), "_recent_transcript_urls": {},
          "_render_ticket_transcript_html": rendu, "_ticket_transcript_file": rendu,
          "_resolve_transcript_text": lambda t, _g: t,
          "transcript_store": Obj(public_base_url=lambda: "https://bot.exemple",
                                  new_token=lambda: "tok", save_html=lambda t, h: True,
                                  transcript_url=lambda t: f"https://bot.exemple/t/{t}"),
          "_logerr": lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)),
          "recrutements": Obj(enregistrer=enregistrer), "registre": journal}
    for nom in ("_ticket_event_parts", "_ticket_timeline_line", "_salon_transcripts_rellseas",
                "_heure_paris", "_nom_et_id", "_EVENEMENTS_TICKET", "_cartes_v2", "_texte_v2", "_dossier_recrutement",
                "_vue_recrutement", "send_ticket_log", "CONVERSATION_MAX", "_historique_ticket", "_note_tronque",
                "_image_sure", "_HOTES_IMAGES"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    tk = {"id": 5, "panel_id": "p1", "answers": {"Pseudo Roblox": "Kolax_RS", "Niveau": "2400"}}
    asyncio.run(ns["send_ticket_log"](g, "create", candidat, tk))
    asyncio.run(ns["send_ticket_log"](g, "close", candidat, tk, extra="Accepté, bienvenue", closer=staff,
                                      ch=Ticket()))
    assert len(enregistres) == 1, "la candidature entre au suivi des recrutements"
    _gid, tid, cid, nom, events, reponses, participants, url = enregistres[0]
    assert (tid, cid, nom, url) == (5, 7, "Kolax", "https://bot.exemple/t/tok")
    assert events[-1][0] == "close" and events[-1][2] == "Accepté, bienvenue", "le motif de fermeture suit"
    assert reponses["Pseudo Roblox"] == "Kolax_RS" and any(p["id"] == 7 for p in participants)
    assert [(c, t) for c, t, _x, _k in journal.lignes] == [("Tickets", "ticket.create"), ("Tickets", "ticket.close")]
    texte_fin, kw_fin = journal.lignes[-1][2], journal.lignes[-1][3]
    assert texte_fin.startswith("Ticket #5 (🏴‍☠️ Recrutement Rell Seas) — Fermé par @Capitaine")
    assert "Accepté, bienvenue" in texte_fin and (kw_fin["membre_id"], kw_fin["auteur_id"]) == (7, 2)

    async def index():
        async with get_db() as db:
            async with db.execute("SELECT ticket_id, user_id, url, jeton FROM ticket_transcripts") as cur:
                return await cur.fetchall()
    assert asyncio.run(index()) == [(5, 7, "https://bot.exemple/t/tok", "tok")], "le transcript est indexé pour le site, avec son jeton (conversation)"
    if site:
        assert logs.envois == [] and 56 not in salons, "plus rien sur Discord, aucun salon créé"
        asyncio.run(ns["send_ticket_log"](g, "create", candidat, {"id": 6, "panel_id": "p2"}))
        assert logs.envois == [] and len(journal.lignes) == 3, "un ticket Support : au journal seulement"
        return

    assert logs.envois == [], "rien d'un ticket Rell Seas dans le salon des tickets"
    dedie = salons[56]
    assert dedie.name == "📜transcripts-rellseas" and dedie.category == "LOGS"
    assert conf["rellseas_transcripts_salon"] == 56
    fiche = dedie.envois[-1][1]
    texte = fiche["file"].fp.getvalue().decode("utf-8")
    assert "Candidat : Kolax (7)" in texte
    assert "Kolax (candidat) : Bonjour, je veux rejoindre" in texte
    assert "Capitaine : Ton niveau ?" in texte
    assert "GoRP [bot] : Bienvenue" in texte
    assert re.search(r"Kolax\s+7\s+2 message\(s\) · candidat", texte)
    assert "Pseudo Roblox" in texte and "Kolax_RS" in texte
    assert "Fermé par Capitaine (2)" in texte
    assert "[14:03] Kolax (candidat) : 2400\n" in texte, "heure de Paris, suite du message indentée"
    composants = list(fiche["view"].walk_children())
    assert any(isinstance(c, discord.ui.File) and c.media.url == f"attachment://{fiche['file'].filename}"
               for c in composants)
    assert any(isinstance(c, discord.ui.Button) and c.url == "https://bot.exemple/t/tok" for c in composants)

    autre = {"id": 6, "panel_id": "p2"}
    asyncio.run(ns["send_ticket_log"](g, "create", candidat, autre))
    assert len(logs.envois) == 1, "un ticket Support reste dans le salon des tickets"


def test_T1b_logs_sur_le_site_rien_sur_discord_tout_au_journal(tmp_path):
    """« Il n'y aura plus de logs sur le serveur Discord, ce sera envoyé sur le site. »"""
    test_T1_ticket_rellseas_dans_son_salon_avec_le_dossier_complet(tmp_path, site=True)


def test_T2_choix_explicite_dans_configure_prime_sur_le_nom():
    c = {"ticket_panels": {"a": {"name": "Rell Seas"}, "b": {"name": "Candidatures clan"}}}
    assert rellseas_panneau.panneaux_tickets(c) == {"a"}
    c[rellseas_panneau.CLE_TICKETS] = ["b", "fantome"]
    assert rellseas_panneau.panneaux_tickets(c) == {"b"}
    c[rellseas_panneau.CLE_TICKETS] = []
    assert rellseas_panneau.panneaux_tickets(c) == set()
