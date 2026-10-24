"""24/10/2026 : « Components V2 partout » — les derniers messages en ancien format (messages privés de sanction,
avertissements automatiques, commandes /mod, alertes de 📋logs, carte d'accueil, annonces des réseaux, journaux,
rapports) passent en cartes V2, par un seul convertisseur (`ui_v2.carte_embed`)."""
from __future__ import annotations

import ast
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import components as C

import ui_v2
import visuels
from conftest_discord import Obj
from faux_serveur import ids, textes
from ui_v2 import LayoutView, Palette, carte_embed, carte_texte

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)


def _types(v):
    return [type(x).__name__ for x in v.walk_children()]


def test_W1_le_convertisseur_garde_tout_ce_que_l_embed_montrait():
    e = discord.Embed(title="Nouvelle vidéo", url="https://youtu.be/x", description="Le texte", color=0xFF0000,
                      timestamp=datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc))
    e.set_author(name="GoRipe", icon_url="https://cdn.discordapp.com/a.png")
    e.add_field(name="Membre", value="<@7>", inline=True)
    e.add_field(name="Motif", value="ligne 1\nligne 2", inline=False)
    e.set_image(url="https://cdn.discordapp.com/img.png")
    e.set_footer(text="Protection")
    v = carte_embed(e, [discord.ui.Button(label="Ouvrir", url="https://youtu.be/x")], haut="<@&5>")
    t = textes(v)
    assert "-# GoRipe" in t and "### [Nouvelle vidéo](https://youtu.be/x)" in t and "Le texte" in t
    assert "**Membre** : <@7>" in t and "**Motif**\nligne 1\nligne 2" in t
    assert "-# Protection · <t:1792864800:f>" in t and t.startswith("<@&5>")
    assert {"Section", "Thumbnail", "MediaGallery", "ActionRow"} <= set(_types(v))
    conteneur = [x for x in v.children if isinstance(x, discord.ui.Container)][0]
    assert conteneur.accent_colour.value == 0xFF0000


def test_W2_les_boutons_d_une_ancienne_vue_passent_dans_la_carte_et_le_texte_tient():
    vue = discord.ui.View(timeout=120)
    vue.add_item(discord.ui.Select(options=[discord.SelectOption(label="a")], custom_id="s1"))
    for k in range(6):
        vue.add_item(discord.ui.Button(label=f"b{k}", custom_id=f"b{k}"))
    v = carte_embed(discord.Embed(description="x"), vue)
    rangs = [x for x in v.walk_children() if isinstance(x, discord.ui.ActionRow)]
    assert [len(r.children) for r in rangs] == [5, 1, 1] and v.timeout == 120, "5 boutons par rangée, le menu seul"
    assert ids(v) == ["b0", "b1", "b2", "b3", "b4", "b5", "s1"] and not vue.children
    long = discord.Embed(description="d" * 3000)
    for _k in range(10):
        long.add_field(name="n", value="v" * 900, inline=False)
    assert len(textes(carte_embed(long))) <= 4000, "la limite de Discord : 4 000 caractères"
    assert textes(carte_texte("Bonjour", [discord.ui.Button(label="ok", custom_id="ok")])) == "Bonjour ok"


def test_W3_plus_un_seul_envoi_d_embed_dans_le_bot():
    envois = [l.strip() for l in SRC.splitlines()
              if re.search(r"\bembed=(?!None)", l) and not l.strip().startswith("#")]
    assert envois == ["await old.edit(embed=e)", "await msg.edit(embed=new, view=_dossier_vue(uid, eteinte=True))"], \
        "seuls les anciens messages (embeds) restent des embeds : " + repr(envois)
    for nom in ("ClearAllConfirmView", "_CasierManageView"):
        classe = next(n for n in ARBRE.body if isinstance(n, ast.ClassDef) and n.name == nom)
        assert [ast.unparse(b) for b in classe.bases] == ["LayoutView"], nom
    assert "_welcome_quick_buttons" not in SRC, "24/10 : l'accueil est une ligne de texte, sans bouton (test_accueil_court)"
    ul = (RACINE / "unified_logger.py").read_text(encoding="utf-8")
    assert "send(embed=" not in ul and '"embed": embed' not in ul
    assert "📋 **sur le site** (journal)" in SRC, "/logs status ne dit plus « non configuré » en mode site"


def test_W4_tout_supprimer_en_v2():
    ns = {"discord": discord, "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels,
          "Button": discord.ui.Button, "carte_texte": carte_texte}
    exec(_source("ClearAllConfirmView"), ns)  # noqa: S102 — code du dépôt
    v = ns["ClearAllConfirmView"](7, 77)
    assert "Supprimer TOUS les messages de <#77>" in textes(v) and "Tout supprimer" in textes(v)
    edits = []

    async def edit_message(**kw):
        edits.append(kw)

    async def rien(*_a, **_k):
        return None
    annuler = [b for b in v.walk_children() if isinstance(b, discord.ui.Button) and b.label == "Annuler"][0]
    i = Obj(user=Obj(id=7), response=Obj(edit_message=edit_message, send_message=rien))
    asyncio.run(annuler.callback(i))
    assert "Annulé" in textes(edits[-1]["view"]) and "content" not in edits[-1]


def test_W5_le_dossier_traite_en_v2_gris_boutons_eteints_la_decision_dedans():
    vue = discord.ui.View(timeout=None)
    vue.add_item(discord.ui.Button(label="Mute", custom_id="cad:mute:42"))
    carte = carte_embed(discord.Embed(title="Compte suspect détecté", description="score 9", color=0xE74C3C), vue)
    msg = Obj(embeds=[], components=[C._component_factory(d) for d in carte.to_components()])
    edits = []

    async def edit(**kw):
        edits.append(kw)
    msg.edit = edit
    ns = {"discord": discord, "LayoutView": LayoutView, "time": __import__("time"), "_logerr": lambda *a, **k: None}
    exec(_source("_dossier_traite"), ns)  # noqa: S102 — code du dépôt
    i = Obj(message=msg, user=Obj(mention="<@1>"), guild=Obj(id=1))
    asyncio.run(ns["_dossier_traite"](i, "🔇 Mute 24 h", 42))
    v = edits[-1]["view"]
    t = textes(v)
    assert "Compte suspect détecté" in t and "**Statut** : 🔇 Mute 24 h par <@1>" in t
    assert t.index("**Statut**") < t.rindex("Mute"), "la décision au-dessus des boutons"
    bouton = [b for b in v.walk_children() if isinstance(b, discord.ui.Button)][0]
    conteneur = [x for x in v.children if isinstance(x, discord.ui.Container)][0]
    assert bouton.disabled and conteneur.accent_colour.value == 0x95A5A6


def test_W6_les_annonces_des_reseaux_la_carte_le_lien_la_cloche_et_l_anti_doublon():
    envois = []

    async def webhook_send(salon, profil, **kw):
        envois.append((profil, kw))
        return Obj(id=5)

    async def ping_social(_salon):
        vue = discord.ui.View(timeout=None)
        vue.add_item(discord.ui.Button(label="🔔", custom_id="notif:x"))
        return "<@&9>", Obj(id=9), vue
    ns = {"discord": discord, "carte_embed": carte_embed, "visuels": visuels, "webhook_send": webhook_send,
          "_ping_social": ping_social, "notifs": Obj(mentions=lambda r: discord.AllowedMentions(roles=[r]))}
    exec(_source("_publier_social"), ns)  # noqa: S102 — code du dépôt
    e = discord.Embed(title="Live !", url="https://twitch.tv/goripe")
    asyncio.run(ns["_publier_social"](Obj(id=1), "twitch", e))
    profil, kw = envois[-1]
    t = textes(kw["view"])
    assert profil == "twitch" and t.startswith("<@&9>") and "[Live !](https://twitch.tv/goripe)" in t
    assert ids(kw["view"]) == ["notif:x"] and "Ouvrir · Open" in t and "content" not in kw
    #  « Le message est-il quand même arrivé ? » : il se reconnaît aussi en carte.
    msg = Obj(id=77, embeds=[], content="", components=[C._component_factory(d) for d in kw["view"].to_components()])

    class Salon:
        guild = None

        async def history(self, limit=15):
            yield msg
    ns2 = {"_texte_v2": None, "_logerr": lambda *a, **k: None, "discord": discord}
    for nom in ("_resolve_transcript_text", "_cartes_v2", "_texte_v2", "_deja_dans_le_salon"):
        exec(_source(nom), ns2)  # noqa: S102 — code du dépôt
    ns2.update(re=re, datetime=datetime, timezone=timezone)
    assert asyncio.run(ns2["_deja_dans_le_salon"](Salon(), "https://twitch.tv/goripe")) == 77
