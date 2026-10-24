"""20/10/2026 : « sur le site, on n'a pas le transcript au complet de tout ce qui a été envoyé, on n'a
que la partie questionnaire ». Le site montre désormais TOUTE la conversation d'un ticket : en direct
depuis Discord s'il est ouvert, relue dans le transcript enregistré s'il est fermé — et les deux
chemins rendent exactement les mêmes messages."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import discord

import tableau
import transcript_store
from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
NOMS = ("_resolve_transcript_text", "_TRANSCRIPT_CSS", "CONVERSATION_MAX", "_message_en_donnees",
        "_conversation_ticket", "_conversation_seule", "_suivi_ticket", "_render_ticket_transcript_html",
        "_cartes_v2", "_html_lignes_v2", "_html_carte_v2")


def _ns(**autres):
    ns = {"re": re, "datetime": datetime, "timezone": timezone, "asyncio": asyncio, "ZoneInfo": None, "discord": discord,
          "transcript_store": transcript_store, "now": lambda: datetime(2026, 10, 20, tzinfo=timezone.utc),
          "print": lambda *a, **k: None, "_logerr": lambda *a, **k: None, **autres}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in NOMS:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


class _Auteur:
    def __init__(self, nom, bot=False):
        self.display_name, self.bot = nom, bot
        self.display_avatar = Obj(url=f"https://cdn.discordapp.com/avatars/{nom}.png")


def _messages():
    membre, staff, robot = _Auteur("Kolax"), _Auteur("Mira"), _Auteur("GoRP", bot=True)
    t = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)

    def pj(nom, genre):
        return Obj(filename=nom, content_type=genre, url=f"https://cdn.discordapp.com/attachments/1/2/{nom}", size=10)
    questionnaire = Obj(title="Candidature", description="Réponses du formulaire\nfin",
                        fields=[Obj(name="Âge", value="15 ans"), Obj(name="Jeu", value="Blox <Fruits> & co")],
                        footer=Obj(text="Rell Seas"), image=Obj(url=None),
                        thumbnail=Obj(url="https://cdn.discordapp.com/embed/vignette.png"))
    return [
        Obj(author=robot, created_at=t, content="Bienvenue <@7> !", attachments=[], embeds=[questionnaire], stickers=[]),
        Obj(author=staff, created_at=t.replace(minute=35), content="Tu joues depuis quand ?\n<b>Réponds</b> & précise",
            attachments=[], embeds=[], stickers=[]),
        Obj(author=membre, created_at=t.replace(minute=40), content="  Depuis 2 ans, voici mes stats  ",
            attachments=[pj("stats.png", "image/png"), pj("partie.mp4", "video/mp4"), pj("cv.pdf", "application/pdf")],
            embeds=[], stickers=[Obj(url="https://media.discordapp.net/stickers/9.png")]),
        Obj(author=membre, created_at=t.replace(minute=41), content="", attachments=[], embeds=[], stickers=[]),
    ]


class _Salon:
    def __init__(self, messages, guild):
        self._m, self.guild = messages, guild

    def history(self, limit=None, oldest_first=False):
        async def gen():
            for m in self._m[:limit]:
                yield m
        return gen()


GUILDE = Obj(id=1, name="GoRP SEA", get_member=lambda i: Obj(display_name="Kolax") if i == 7 else None,
             get_role=lambda i: None, get_channel=lambda i: None)


def test_C1_le_transcript_relu_rend_exactement_les_messages_lus_en_direct():
    ns = _ns()
    msgs = _messages()
    html = asyncio.run(ns["_render_ticket_transcript_html"](_Salon(msgs, GUILDE), 42))
    relus = transcript_store._Lecteur().lire(html)
    directs = [ns["_message_en_donnees"](m, GUILDE) for m in msgs]
    assert relus == directs
    assert directs[0]["texte"] == "Bienvenue @Kolax !" and directs[0]["bot"] is True
    assert directs[0]["embeds"][0]["champs"] == [["Âge", "15 ans"], ["Jeu", "Blox <Fruits> & co"]], "le questionnaire"
    assert directs[1]["texte"] == "Tu joues depuis quand ?\n<b>Réponds</b> & précise", "les questions du staff, en texte"
    assert directs[2]["images"] == ["https://cdn.discordapp.com/attachments/1/2/stats.png",
                                    "https://media.discordapp.net/stickers/9.png"]
    assert directs[2]["videos"] and directs[2]["fichiers"] == [{"nom": "cv.pdf", "url": "https://cdn.discordapp.com/attachments/1/2/cv.pdf"}]
    assert directs[3]["texte"] == "" and relus[3]["quand"] == int(msgs[3].created_at.timestamp()), \
        "un message sans texte (le [média] de la page) reste vide, à la bonne heure"


def test_C2_un_ancien_transcript_sans_heure_exacte_se_relit_aussi():
    """Les transcripts d'avant le 20/10 n'ont pas `data-t` : l'heure affichée (UTC) suffit."""
    ns = _ns()
    html = asyncio.run(ns["_render_ticket_transcript_html"](_Salon(_messages()[1:2], GUILDE), 42))
    ancien = re.sub(r' data-t="\d+"', "", html)
    (m,) = transcript_store._Lecteur().lire(ancien)
    assert m["quand"] == int(datetime(2026, 10, 19, 18, 35, tzinfo=timezone.utc).timestamp())
    assert m["auteur"] == "Mira" and m["texte"].startswith("Tu joues depuis quand ?")


def _base(tmp_path):
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
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id, channel_id, status)")
            await db.execute("CREATE TABLE ticket_transcripts(guild_id, ticket_id, user_id, user_name, panel, url,"
                             " closed_at, jeton TEXT, PRIMARY KEY (guild_id, ticket_id))")
            await db.execute("CREATE TABLE ticket_log_events(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id,"
                             " ticket_id, kind, actor_id, detail, created_unix)")
            await db.executemany("INSERT INTO ticket_log_events(guild_id, ticket_id, kind, actor_id, detail,"
                                 " created_unix) VALUES(?,?,?,?,?,?)",
                                 [(1, 2, "create", 7, "", 1_800_000_000), (1, 2, "claim", 8, "", 1_800_000_600),
                                  (1, 2, "close", 8, "Accepté, bienvenue", 1_800_003_600),
                                  (2, 2, "close", 9, "autre serveur", 1_800_000_000)])
            await db.executemany("INSERT INTO tickets VALUES(?,?,?,?)",
                                 [(1, 1, 500, "open"), (2, 1, 501, "closed"), (3, 1, 502, "closed"), (4, 1, 503, "closed"),
                                  (5, 2, 504, "closed")])
            await db.commit()
    asyncio.run(preparer())
    return get_db


def test_C3_ouvert_en_direct_ferme_relu_absent_dit_pourquoi(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_store, "_BASE_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(transcript_store, "public_base_url", lambda: "https://bot.exemple")
    get_db = _base(tmp_path)
    msgs = _messages()

    async def salon(g, chid):
        return _Salon(msgs, GUILDE) if chid == 500 else None
    ns = _ns(get_db=get_db, tickets_fils=Obj(salon=salon))
    jeton, ancien = transcript_store.new_token(), transcript_store.new_token()
    html = asyncio.run(ns["_render_ticket_transcript_html"](_Salon(msgs, GUILDE), 2))
    html = html.replace("https://cdn.discordapp.com/attachments/1/2/stats.png", f"https://bot.exemple/ta/{jeton}/0")
    assert transcript_store.save_html(jeton, html) and transcript_store.save_html(ancien, html)

    async def scenario():
        async with get_db() as db:
            await db.execute("INSERT INTO ticket_transcripts VALUES(1, 2, 7, 'Kolax', '', ?, '', ?)",
                             (f"https://bot.exemple/t/{jeton}", jeton))
            await db.execute("INSERT INTO ticket_transcripts VALUES(1, 3, 7, 'Kolax', '', ?, '', NULL)",
                             (f"https://bot.exemple/t/{ancien}",))
            await db.commit()
        return [await ns["_conversation_ticket"](GUILDE, n) for n in (1, 2, 3, 4, 5)]
    ouvert, ferme, ferme_ancien, sans, autre_serveur = asyncio.run(scenario())
    assert ouvert["source"] == "discord" and len(ouvert["messages"]) == 4
    assert ferme["source"] == "transcript" and [m["texte"] for m in ferme["messages"]] == [m["texte"] for m in ouvert["messages"]]
    assert ferme["messages"][2]["images"][0] == f"/ta/{jeton}/0", "image ré-hébergée : adresse relative (CSP du site)"
    assert ferme_ancien["source"] == "transcript", "ancienne ligne : le jeton se lit dans l'adresse"
    assert sans["messages"] == [] and "Aucun transcript" in sans["absent"]
    assert autre_serveur["absent"] == "Ticket introuvable.", "un ticket d'un autre serveur ne se lit pas"
    assert "suivi" not in autre_serveur
    assert [(e["quoi"], e["qui"], e["detail"]) for e in ferme["suivi"]] == [
        ("create", "Kolax", ""), ("claim", "membre parti", ""), ("close", "membre parti", "Accepté, bienvenue")], \
        "22/10 : chaque étape du ticket, dans l'ordre, et pas celles d'un autre serveur"
    assert ouvert["suivi"] == [] and sans["suivi"] == []


def test_C4_la_route_est_reservee_a_la_session_de_la_tete(tmp_path):
    import registre
    get_db = _base(tmp_path)
    registre.setup(get_db=get_db, log=lambda *a: None)
    registre._derniers.clear()
    asyncio.run(registre.init_db())
    g = Obj(id=1, owner_id=99, members=[], get_member=lambda i: Obj(id=i, roles=[], display_name="Tete"),
            get_channel=lambda i: None, get_thread=lambda i: None, get_role=lambda i: None, me=None)
    vus = []

    async def conversation(g_, n):
        vus.append(n)
        return {"ticket": n, "messages": []}

    async def cfg(_g):
        return {}
    tableau.setup(bot=Obj(get_guild=lambda gid: g if gid == 1 else None, user=Obj(id=999)), cle="cle",
                  base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=None,
                  autorise_membre=lambda g_, m, c: m is not None, conversation=conversation, log=lambda *a: None)

    class Requete:
        def __init__(self, jeton="", cookie=None, query=None):
            self.match_info, self.query, self.headers, self.remote = {"jeton": jeton}, dict(query or {}), {}, "1.2.3.4"
            self.cookies = {tableau.COOKIE: cookie} if cookie else {}

    async def scenario():
        await tableau.init_db()
        entree = await tableau.entree(Requete(tableau.jeton(1, 7, "tout")))
        sid = entree.cookies[tableau.COOKIE].value
        return (await tableau.conversation(Requete(query={"ticket": "2"})),
                await tableau.conversation(Requete(cookie=sid, query={"ticket": "2; DROP"})),
                await tableau.conversation(Requete(cookie=sid, query={"ticket": "2"})))
    sans, invalide, ok = asyncio.run(scenario())
    assert (sans.status, invalide.status, ok.status) == (403, 400, 200) and vus == [2]
    assert json.loads(ok.body) == {"ticket": 2, "messages": []}
    assert "img-src 'self'" in ok.headers["Content-Security-Policy"]
    assert "tableau:conversation" in (RACINE / "health_server.py").read_text(encoding="utf-8")
    page = (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert page.count("ouvrirConversation(") >= 4, "cartes des tickets ouverts et fermés + « Agrandir »"
    assert page.count("transcriptEnLigne(") >= 5, "dans la fiche : tickets, candidature en cours, décidée, anciennes"
    assert page.count("const suivi = suiviConv(d);") == 2, "le suivi au-dessus de la conversation, dans la fenêtre et la fiche"
    assert 'transcriptEnLigne(enCours.ticket, "Candidature · ticket #" + enCours.ticket, true)' in page, \
        "« on clique sur quelqu'un » : le transcript s'affiche d'office sous le questionnaire"
    assert '"/conversation?ticket="' in page and "\\/ta\\/[A-Za-z0-9_-]{16,86}" in page
    assert "candidatures: f.candidatures.length + (enCours ? 1 : 0)" in page, \
        "une candidature EN COURS ouvre l'onglet Candidatures de la fiche : sinon un premier candidat n'a ni dossier ni conversation"
