"""24/10/2026 : le recours d'un radié passe en Components V2 (le ticket et le message privé) et la direction
voit ce ticket ; la décision du staff prend la place des boutons. Et les transcripts (HTML, .txt), le dossier
de recrutement et la conversation sur le site lisent les cartes V2 — avant, le dossier d'un ticket et les
traces du staff y sortaient vides (« [média] »)."""
from __future__ import annotations

import ast
import asyncio
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import components as C

import tickets_fils
import transcript_store
import visuels
from conftest_discord import Obj
from faux_serveur import ids, textes
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
LECTURE = ("_resolve_transcript_text", "_cartes_v2", "_texte_v2", "_html_lignes_v2", "_html_carte_v2",
           "_historique_ticket", "_note_tronque", "_image_sure")


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)


def _ns(*noms, **plus):
    ns = {"discord": discord, "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels, "re": re, "io": io,
          "json": json, "time": __import__("time"), "datetime": datetime, "timezone": timezone,
          "Button": discord.ui.Button, "tickets_fils": tickets_fils, "transcript_store": transcript_store,
          "ZoneInfo": None, "_TRANSCRIPT_CSS": "", "_TICKET_TZ": "Europe/Paris", "_EVENEMENTS_TICKET": {},
          "now": lambda: datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc), "_logerr": lambda *a, **k: None,
          "CONVERSATION_MAX": 5000, "TRANSCRIPT_TXT_MAX": 2000,
          "_HOTES_IMAGES": ("cdn.discordapp.com", "media.discordapp.net"), "RECOURS_PID": "recours"}
    ns.update(plus)
    for nom in noms:
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def _composants(vue) -> list:
    """Ce que Discord rend dans `message.components` pour une vue envoyée."""
    return [C._component_factory(d) for d in vue.to_components()]


class _G:
    id, name = 1, "Serveur"

    def get_member(self, uid):
        return {3: Obj(display_name="Bob"), 50: Obj(display_name="Modo")}.get(uid)

    def get_role(self, _rid):
        return None

    def get_channel(self, _cid):
        return None


def _carte_dossier() -> list:
    v = discord.ui.LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.Section(discord.ui.TextDisplay("### 🎫 Ticket n°12 · Support"),
                           discord.ui.TextDisplay("<@3> · ouvert <t:1761300000:R>"),
                           accessory=discord.ui.Thumbnail("https://cdn.discordapp.com/avatars/3/a.png")),
        discord.ui.TextDisplay("-# premier ticket · casier vide"), discord.ui.Separator(),
        discord.ui.TextDisplay("**Ton pseudo en jeu ?**\nBobLeBricoleur <script>"), discord.ui.Separator(),
        discord.ui.TextDisplay("🟢 **Pris en charge** par <@50>"),
        discord.ui.ActionRow(discord.ui.Button(label="Fermer", custom_id="ticket_ctrl_close"),
                             discord.ui.Button(label="Le guide", url="https://exemple.fr/guide")),
        accent_color=0x22C55E))
    return _composants(v)


def _message(composants):
    return Obj(created_at=datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc), content="", embeds=[], attachments=[],
               stickers=[], components=composants,
               author=Obj(id=999, display_name="Vitrine", bot=True, display_avatar=Obj(url="https://cdn.discordapp.com/b.png")))


class _Salon:
    def __init__(self, messages):
        self.messages, self.guild = messages, _G()

    async def history(self, limit=100, oldest_first=False):
        for m in self.messages:
            yield m


def test_R1_le_transcript_html_lit_les_cartes_v2_et_le_site_le_relit():
    ns = _ns(*LECTURE, "_render_ticket_transcript_html")
    html = asyncio.run(ns["_render_ticket_transcript_html"](_Salon([_message(_carte_dossier())]), 12))
    assert "[média]" not in html and "###" not in html and "**" not in html
    assert '<div class="etitle">🎫 Ticket n°12 · Support</div>' in html
    assert "@Bob" in html and "<b>Pris en charge</b> par @Modo" in html
    assert "&lt;script&gt;" in html and "<script>" not in html, "le texte reste échappé"
    assert 'href="https://exemple.fr/guide"' in html and "Fermer" not in html, "les liens oui, les boutons non"
    lu = transcript_store._Lecteur().lire(html)[0]
    assert lu["embeds"][0]["titre"] == "🎫 Ticket n°12 · Support"
    assert "premier ticket · casier vide" in lu["embeds"][0]["texte"]
    assert "Pris en charge par @Modo" in lu["embeds"][0]["texte"]
    assert lu["fichiers"] == [{"nom": "Le guide", "url": "https://exemple.fr/guide"}]


def test_R2_la_conversation_du_site_lit_les_cartes_v2():
    ns = _ns(*LECTURE, "_message_en_donnees")
    out = ns["_message_en_donnees"](_message(_carte_dossier()), _G())
    assert out["embeds"][0]["titre"] == "🎫 Ticket n°12 · Support"
    assert "Pris en charge par @Modo" in out["embeds"][0]["texte"] and "**" not in out["embeds"][0]["texte"]
    assert out["fichiers"] == [{"nom": "Le guide", "url": "https://exemple.fr/guide"}]


def test_R3_le_transcript_texte_et_le_dossier_de_recrutement_lisent_les_cartes_v2():
    ns = _ns(*LECTURE, "_ticket_transcript_file", "_heure_paris", "_nom_et_id", "_dossier_recrutement")
    f = asyncio.run(ns["_ticket_transcript_file"](_Salon([_message(_carte_dossier())]), 12))
    txt = f.fp.getvalue().decode("utf-8")
    assert "Pris en charge par @Modo" in txt and "[média]" not in txt and "**" not in txt
    texte, _qui = asyncio.run(ns["_dossier_recrutement"](_Salon([_message(_carte_dossier())]), _G(), 12, 3,
                                                          "Rell Seas", {}, []))
    assert "Ticket n°12 · Support" in texte and "Pris en charge par @Modo" in texte and "[média]" not in texte


class _Curseur:
    def __init__(self, rangee):
        self.rangee = rangee

    def __await__(self):
        if False:
            yield
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def fetchone(self):
        return self.rangee


class _Db:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def execute(self, *_a):
        return _Curseur((12,))

    async def commit(self):
        return None


class _Radie:
    id, name, mention = 42, "bob", "<@42>"
    display_avatar = Obj(url="https://cdn.discordapp.com/avatars/42/a.png")

    def __str__(self):
        return "bob"


def _ouvrir():
    staff, direction, fondateur = Obj(id=7, mention="<@&7>"), Obj(id=20), Obj(id=781205382923288593)
    salon = Obj(id=77, envois=[])

    async def send(**kw):
        salon.envois.append(kw)
    salon.send = send
    cree = {}

    async def create_text_channel(nom, category=None, overwrites=None, reason=None):
        cree.update(nom=nom, overwrites=overwrites)
        return salon
    g = Obj(id=1, default_role=Obj(id=1), me=Obj(id=999), owner=Obj(id=99), get_role=lambda rid: {7: staff}.get(rid),
            get_channel=lambda _cid: None, create_text_channel=create_text_channel)

    async def cfg(_gid):
        return {"ticket_staff": 7}

    async def panneau(_g):
        return "p1", {"category": 0}
    ns = _ns("RadieDecisionButton", "_ouvrir_ticket_recours", cfg=cfg, _panneau_ticket_serveur=panneau,
             get_db=lambda: _Db(), _equipe_direction=lambda _g, _c: [direction, fondateur])
    rep = asyncio.run(ns["_ouvrir_ticket_recours"](g, _Radie(), "Je n'ai rien fait @everyone", "Le motif est faux"))
    return rep, cree, salon, g, staff, direction, fondateur


def test_R4_le_ticket_de_recours_en_v2_la_direction_le_voit():
    rep, cree, salon, g, staff, direction, fondateur = _ouvrir()
    assert "Votre recours a été transmis" in rep
    ow = cree["overwrites"]
    assert ow[g.default_role].view_channel is False and ow[staff].view_channel
    assert ow[direction].view_channel and ow[fondateur].view_channel, "la direction et le fondateur voient le recours"
    kw = salon.envois[-1]
    assert "embed" not in kw and isinstance(kw["view"], discord.ui.LayoutView)
    t = textes(kw["view"])
    assert "Recours de radiation · ticket n°12" in t and "Le motif est faux" in t
    assert "@​everyone" in t, "le texte du radié ne mentionne personne"
    assert ids(kw["view"]) == ["radiedec:lever:42", "radiedec:bannir:42"]
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.users is False and am.roles == [staff], "seul le staff est prévenu"


def test_R5_la_decision_prend_la_place_des_boutons():
    _rep, _cree, salon, *_ = _ouvrir()
    edits = []

    async def edit(**kw):
        edits.append(kw)
    ns = _ns("_carte_recours_decidee")
    msg = Obj(embeds=[], components=_composants(salon.envois[-1]["view"]), edit=edit)
    asyncio.run(ns["_carte_recours_decidee"](msg, "✅ **Radiation levée** par <@50>"))
    v = edits[-1]["view"]
    assert ids(v) == [], "plus de boutons : on ne tranche pas deux fois"
    t = textes(v)
    assert "Radiation levée" in t and "Recours de radiation · ticket n°12" in t and "Le motif est faux" in t
    assert "<@&7> · un recours à trancher" in t
    vieux = Obj(embeds=[object()], edit=edit)
    asyncio.run(ns["_carte_recours_decidee"](vieux, "x"))
    assert edits[-1] == {"view": None}, "un ancien recours (embed) garde son embed"


def test_R6_le_bouton_de_decision_inscrit_la_decision():
    inscrit, suivis = [], []

    async def rien(*_a, **_k):
        return None

    async def carte(message, ligne):
        inscrit.append((message, ligne))

    async def send(*a, **k):
        suivis.append(a or k)
    ns = _ns("RadieDecisionButton", _autorise_radiation=rien, _lever_radiation=rien, _prevenir_radie=rien,
             _carte_recours_decidee=carte, _fermer_recours=rien, _fiche_sanction=rien)   # aucune restriction en cours
    msg = Obj()
    i = Obj(response=Obj(defer=rien), followup=Obj(send=send), user=Obj(mention="<@50>"), message=msg,
            guild=Obj(id=1, get_member=lambda _uid: Obj(mention="<@42>")))
    asyncio.run(ns["RadieDecisionButton"]("lever", 42).callback(i))
    assert inscrit and inscrit[-1][0] is msg and "Radiation levée** par <@50>" in inscrit[-1][1]
    assert "i.message.edit(view=None)" not in _source("RadieDecisionButton")


def test_R7_le_message_prive_du_recours_en_v2():
    envois = []

    async def send(**kw):
        envois.append(kw)
    u = Obj(send=send)
    ns = _ns("RadieAppelButton", "_envoyer_recours_radie", bot=Obj(get_user=lambda _uid: u))
    ok = asyncio.run(ns["_envoyer_recours_radie"](Obj(id=5, name="Serveur", icon=None), Obj(id=42), "Spam"))
    assert ok and "embed" not in envois[-1]
    v = envois[-1]["view"]
    assert ids(v) == ["radieappel:5"]
    assert "Vous avez été radié de Serveur" in textes(v) and "UN recours" in textes(v) and "Spam" in textes(v)
    assert "RECOURS DE RADIATION · ticket #" not in SRC


def test_R8_stats_les_roles_de_zone_manquants_par_jeu():
    async def conf(_g):
        return {"roles": {"aide": 11, "cl_aide": 0}}
    zones = {"aide": Obj(cle="aide", role="🛟 Guide Aide", jeu="rell"), "cl_aide": Obj(cle="cl_aide", role="🛟 Guide Aide · Clover", jeu="clover"),
             "commu": Obj(cle="commu", role="", jeu="commu")}
    entraide = Obj(conf=conf, ZONES=zones, role_zone=lambda g, cf, cle: g.get_role(int(cf["roles"].get(cle, 0) or 0)))
    tete = Obj(owner_id=781205382923288593, get_role=lambda rid: {11: Obj(id=11)}.get(rid))
    autre = Obj(owner_id=5, get_role=lambda _rid: None)
    ns = _ns("_roles_zones_manquants", bot=Obj(guilds=[tete, autre]), TETE_IDS={781205382923288593}, entraide=entraide)
    assert asyncio.run(ns["_roles_zones_manquants"]()) == {"rell": 0, "clover": 1}
