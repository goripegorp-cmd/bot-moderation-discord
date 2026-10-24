"""22/10/2026 : « les tickets, que tu compactes… tous les salons de tickets correctement à un endroit
nickel, qu'on ait un vrai suivi parfait de chaque ticket, de chaque création, qu'on sache exactement
à quoi on a affaire ». Une catégorie « 🎫 TICKETS » qui range tout ; un dossier en tête de chaque
ticket (qui, compte, ancienneté, tickets d'avant, casier, réponses, qui s'en occupe)."""
from __future__ import annotations

import ast
import asyncio
import contextlib
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import discord

import config_salons
import tickets_fils
import visuels
from conftest_discord import Obj
from ui_v2 import LayoutView, Palette, View

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
NOMS = ("TicketControlView", "_BOUTONS_TICKET", "_CASIER_MOTS", "_contexte_ticket", "_vue_dossier_ticket",
        "TICKETS_CATEGORIE", "_verrous_tickets_cat", "_salon_panneau_tickets", "_ranger_tickets",
        "_categorie_tickets", "_salon_des_tickets", "_salon_par_nom", "_custom_ids_du_message")


def _source(nom):
    for n in ARBRE.body:
        cible = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else
                                              getattr(getattr(n, "target", None), "id", None))
        if cible == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


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
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id, channel_id,"
                             " user_id, panel_id, claimed_by, status, answers, created_at)")
            await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id, user_id,"
                             " mod_id, type, reason)")
            await db.executemany("INSERT INTO tickets(guild_id, channel_id, user_id, status) VALUES(?,?,?,?)",
                                 [(1, 501, 7, "closed"), (1, 502, 7, "closed"), (1, 503, 7, "open"),
                                  (1, 504, 9, "open"), (2, 505, 7, "closed")])
            await db.executemany("INSERT INTO infractions(guild_id, user_id, type) VALUES(?,?,?)",
                                 [(1, 7, "warn"), (1, 7, "warn"), (1, 7, "mute"), (2, 7, "ban")])
            await db.commit()
    asyncio.run(preparer())
    return get_db


def _ns(get_db, conf, journal):
    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v

    async def au_journal(_g, cat, type_, texte, **kw):
        journal.append((cat, type_, texte))
    ns = {"discord": discord, "asyncio": asyncio, "get_db": get_db, "cfg": cfg, "db_set": db_set,
          "View": View, "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels,
          "config_salons": config_salons, "tickets_fils": tickets_fils, "bot": Obj(user=Obj(id=999)),
          "_au_journal": au_journal, "_logerr": lambda *a, **k: journal.append(("erreur", a))}
    for nom in NOMS:
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def _membre(uid, nom):
    return Obj(id=uid, display_name=nom, display_avatar=Obj(url=f"https://cdn.discordapp.com/avatars/{uid}.png"),
               created_at=datetime(2024, 1, 2, tzinfo=timezone.utc), joined_at=datetime(2026, 3, 4, tzinfo=timezone.utc))


def _textes(vue) -> str:
    out = []

    def tout(c):
        if isinstance(c, dict):
            for k in ("content", "label"):
                if c.get(k):
                    out.append(str(c[k]))
            for x in c.get("components", []) or []:
                tout(x)
            if c.get("accessory"):
                tout(c["accessory"])
    for comp in vue.to_components():
        tout(comp)
    return " ".join(out)


def _boutons(vue):
    return [b for r in vue.children[0].children if isinstance(r, discord.ui.ActionRow) for b in r.children]


def test_D1_le_dossier_dit_a_quoi_on_a_affaire(tmp_path):
    ns = _ns(_base(tmp_path), {}, [])
    membres = {7: _membre(7, "Kolax"), 8: _membre(8, "Mira")}
    g = Obj(id=1, get_member=lambda uid: membres.get(int(uid)))
    reponses = {"Sujet": "Un joueur m'a arnaqué <@123456789012345678>", "Pseudo Roblox": "Kolax_RS"}
    vue = asyncio.run(ns["_vue_dossier_ticket"](g, 3, 7, "Support", reponses, 1_800_000_000))
    t = _textes(vue)
    assert "Ticket n°3 · Support" in t and "<@7> · ouvert <t:1800000000:R>" in t
    assert "Compte créé <t:1704153600:R> · sur le serveur depuis <t:1772582400:R>" in t
    assert "2 ticket(s) avant · casier : 2 avertissements, 1 mute" in t, "son passé, et pas celui d'un autre serveur"
    assert "**Sujet**" in t and "<@123456789012345678>" not in t, "les réponses, sans mention qui sonne"
    assert "En attente du staff" in t
    boutons = _boutons(vue)
    assert [b.custom_id for b in boutons] == list(ns["_BOUTONS_TICKET"]), "les huit boutons du staff, en deux rangées"
    assert all(type(b.callback.parent).__name__ == "TicketControlView" for b in boutons), \
        "chaque bouton garde son gestionnaire de ticket"
    pris = asyncio.run(ns["_vue_dossier_ticket"](g, 3, 7, "Support", reponses, 1_800_000_000, pris_par=8))
    claim = _boutons(pris)[0]
    assert (claim.label, claim.disabled) == ("Pris par Mira", True)
    assert "Pris en charge** par <@8>" in _textes(pris)
    seul = asyncio.run(ns["_vue_dossier_ticket"](g, 1, 9, "Rell Seas", {}, 1_800_000_000))
    assert "premier ticket · casier vide" in _textes(seul)


class Salon(discord.TextChannel):
    def __init__(self, cid, nom, cat=None, messages=()):
        self.id, self.name, self.category_id, self._messages, self.edits = cid, nom, cat, list(messages), []

    def history(self, limit=None):
        async def gen():
            for m in self._messages[:limit]:
                yield m
        return gen()

    async def edit(self, **kw):
        self.edits.append(kw)
        self.category_id = kw["category"].id


class Categorie(discord.CategoryChannel):
    def __init__(self, cid, nom):
        self.id, self.name = cid, nom


class Guilde:
    def __init__(self, salons):
        self.id, self.salons, self.creees = 1, {s.id: s for s in salons}, []
        self.me = Obj(guild_permissions=Obj(manage_channels=True))

    text_channels = property(lambda self: [s for s in self.salons.values() if isinstance(s, Salon)])

    def get_channel(self, cid):
        return self.salons.get(int(cid or 0))

    async def create_category(self, nom, **kw):
        c = Categorie(900 + len(self.creees), nom)
        self.creees.append(c)
        self.salons[c.id] = c
        return c


def test_D2_une_categorie_qui_range_tout_sans_rien_casser(tmp_path):
    panneau_msg = Obj(author=Obj(id=999), components=[Obj(children=[Obj(custom_id="tickethub:open")])])
    ouverture = Salon(10, "🎫・ticket", cat=1, messages=[panneau_msg])
    equipe = Salon(20, "🎫・tickets-staff", cat=1)
    ancien = Salon(503, "ticket-kolax", cat=2)
    hors = Salon(30, "général", cat=1)
    g = Guilde([ouverture, equipe, ancien, hors])
    conf, journal = {tickets_fils.CLE_PARENTS: {"1:7": 20}}, []
    ns = _ns(_base(tmp_path), conf, journal)
    cat = asyncio.run(ns["_categorie_tickets"](g))
    assert cat.name == "🎫 TICKETS" and conf["tickets_categorie"] == cat.id
    assert [s.category_id for s in (ouverture, equipe, ancien, hors)] == [cat.id, cat.id, cat.id, 1], \
        "le salon d'ouverture, celui de l'équipe et l'ancien ticket encore ouvert ; rien d'autre"
    assert all(e.get("sync_permissions") is False for s in (ouverture, equipe, ancien) for e in s.edits), \
        "chaque salon garde ses droits"
    assert conf[tickets_fils.CLE_PARENTS] == {"1:7": 20, f"{cat.id}:7": 20}, "l'équipe garde son salon : pas de doublon"
    assert journal[-1][:2] == ("Tickets", "tickets.regroupes") and "3 salon(s)" in journal[-1][2]
    assert asyncio.run(ns["_categorie_tickets"](g)) is cat and len(g.creees) == 1, "une seule fois"
    g.me.guild_permissions.manage_channels = False
    del g.salons[cat.id]
    assert asyncio.run(ns["_categorie_tickets"](g)) is None, "sans le droit : la catégorie du panneau sert"


def test_D3_branche_dans_le_bot():
    corps = _source("_create_ticket_corps")
    assert "cat = await _categorie_tickets(i.guild) or i.guild.get_channel(pnl.get('category', 0))" in corps
    assert "await _vue_dossier_ticket(" in corps and "discord.Embed(" not in corps
    #  24/10/2026 : `claim` acquitte et pose la garde ; `_prendre` fait la prise en charge.
    claim = next(ast.unparse(n) for n in ast.walk(ARBRE) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_prendre")
    assert "_vue_dossier_ticket_de(i.guild, tk, pris_par=i.user.id)" in claim and "components_v2" in claim, \
        "la prise en charge réécrit le dossier au lieu de le remplacer par de simples boutons"
    assert "await _categorie_tickets(g)" in _source("salon_logs_task"), "le rangement se fait sans attendre un ticket"
    assert "res['suivi'] = await _suivi_ticket(g, ticket_id)" in _source("_conversation_ticket")
