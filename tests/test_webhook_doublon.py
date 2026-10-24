"""20/10/2026 (audit 6 #11) : apres un 5xx ou un delai depasse, le webhook renvoyait par
channel.send alors que Discord avait souvent deja garde le premier message : deux annonces.

24/10/2026 (revue) : depuis le Lot 37, les annonces (reseaux, actus) et les cartes ne partent plus
qu'en `view=` (Components V2) — ni contenu ni embed : la cle valait None et la verification rendait
la main tout de suite. La cle est desormais l'URL publiee, cherchee dans le texte des cartes V2
recentes ; une carte sans cle se reconnait a son texte entier."""
from __future__ import annotations

import ast
import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import components as C

import roblox_news
import roblox_panneau as rp
import visuels
from conftest_discord import Obj
from ui_v2 import carte_embed

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
_LECTEURS = ("_resolve_transcript_text", "_cartes_v2", "_texte_v2")


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == nom)


def _espace(historique, erreur, envois):
    class Webhook:
        async def send(self, **kw):
            raise erreur

    class Salon:
        id, name, guild = 5, "videos", None

        def history(self, **k):
            async def gen():
                for m in historique:
                    yield m
            return gen()

        async def send(self, **kw):
            envois.append(kw)
            return "renvoye"

    async def get_webhook(*a):
        return Webhook()
    ns = {"discord": discord, "bot": Obj(user=Obj(id=99)), "timedelta": timedelta, "_webhook_cache": {},
          "WEBHOOK_PROFILES": {}, "_BOT_AVATAR_URL": "a", "get_webhook": get_webhook,
          "_logerr": lambda *a, **k: None, "print": lambda *a, **k: None,
          "re": re, "datetime": datetime, "timezone": timezone}
    for nom in (*_LECTEURS, "_deja_poste", "webhook_send"):
        exec(_source(nom), ns)  # noqa: S102 — code du depot
    return ns, Salon()


def _envoi(historique, erreur):
    envois = []
    ns, salon = _espace(historique, erreur, envois)
    e = discord.Embed(title="Nouvelle video", url="https://youtu.be/abc")
    return asyncio.run(ns["webhook_send"](salon, "youtube", embed=e)), envois


def _recu(url):
    return Obj(webhook_id=7, author=Obj(id=1), content="", embeds=[Obj(url=url, title="t")])


def test_W1_un_5xx_apres_reception_ne_double_pas_l_annonce():
    r, envois = _envoi([_recu("https://youtu.be/abc")], discord.HTTPException(Obj(status=503, reason="x"), "x"))
    assert envois == [] and r.embeds[0].url == "https://youtu.be/abc"


def test_W2_un_delai_depasse_sans_reception_renvoie_bien():
    r, envois = _envoi([_recu("https://youtu.be/autre")], asyncio.TimeoutError())
    assert r == "renvoye" and len(envois) == 1


def test_W3_un_refus_403_renvoie_sans_chercher():
    r, envois = _envoi([_recu("https://youtu.be/abc")], discord.Forbidden(Obj(status=403, reason="x"), "x"))
    assert r == "renvoye", "403 : le webhook n'a rien publie"


# ═══ 24/10/2026 : les cartes Components V2 ═══════════════════════════════════════════════════

URL = "https://www.youtube.com/watch?v=abc"


def _carte(url=URL, titre="▶️ Nouvelle vidéo"):
    """Une annonce comme `_publier_social` la construit : mention, titre-lien, bouton « Ouvrir »."""
    e = discord.Embed(title=titre, url=url, description="Regarde !", color=0xFF0000,
                      timestamp=datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc))
    e.set_footer(text="YouTube • GoRipe")
    return carte_embed(e, [discord.ui.Button(label="Ouvrir · Open", url=url),
                           discord.ui.Button(label="🔔", custom_id="notif:1")], haut="<@&9>")


def _recu_v2(vue, auteur=1, webhook=7):
    """Ce que Discord rend dans l'historique : une carte V2, sans contenu ni embed."""
    return Obj(id=77, webhook_id=webhook, author=Obj(id=auteur), content="", embeds=[],
               components=[C._component_factory(d) for d in vue.to_components()])


def _envoi_v2(historique, erreur, **kw):
    envois = []
    ns, salon = _espace(historique, erreur, envois)
    return asyncio.run(ns["webhook_send"](salon, "youtube", view=_carte(), **kw)), envois


def test_W4_une_carte_v2_deja_recue_apres_un_5xx_ne_repart_pas():
    recu = _recu_v2(_carte())
    r, envois = _envoi_v2([recu], discord.HTTPException(Obj(status=503, reason="x"), "x"), cle=URL)
    assert envois == [] and r is recu, "Discord avait garde la carte : pas de second exemplaire"


def test_W5_sans_cle_une_carte_se_reconnait_a_son_texte_entier():
    recu = _recu_v2(_carte())
    r, envois = _envoi_v2([recu], asyncio.TimeoutError())
    assert envois == [] and r is recu, "delai depasse : la carte etait arrivee"


def test_W6_une_autre_carte_n_empeche_pas_l_envoi():
    autre = _recu_v2(_carte(url="https://www.youtube.com/watch?v=autre", titre="Autre vidéo"))
    for kw in ({"cle": URL}, {}):
        r, envois = _envoi_v2([autre], discord.HTTPException(Obj(status=502, reason="x"), "x"), **kw)
        assert r == "renvoye" and len(envois) == 1 and "view" in envois[0], kw


def test_W7_la_carte_d_un_membre_ne_compte_pas():
    """Seuls le bot et les webhooks comptent : un membre qui recolle le lien ne bloque rien."""
    membre = _recu_v2(_carte(), auteur=5, webhook=None)
    r, envois = _envoi_v2([membre], discord.HTTPException(Obj(status=503, reason="x"), "x"), cle=URL)
    assert r == "renvoye" and len(envois) == 1


def test_W8_les_publications_passent_leur_url_et_l_url_se_lit_dans_la_carte(monkeypatch):
    """Les deux chemins des annonces : reseaux (`_publier_social`) et actus (`roblox_panneau`)."""
    lecteur = {"_logerr": lambda *a, **k: None, "discord": discord, "re": re, "datetime": datetime,
               "timezone": timezone}
    for nom in _LECTEURS:
        exec(_source(nom), lecteur)  # noqa: S102 — code du depot
    envois = []

    async def webhook_send(salon, profil, **kw):
        envois.append(kw)
        return Obj(id=5)

    async def ping_social(_salon):
        vue = discord.ui.View(timeout=None)
        vue.add_item(discord.ui.Button(label="🔔", custom_id="notif:x"))
        return "<@&9>", Obj(id=9), vue
    ns = {"discord": discord, "carte_embed": carte_embed, "visuels": visuels, "webhook_send": webhook_send,
          "_ping_social": ping_social, "notifs": Obj(mentions=lambda r: discord.AllowedMentions(roles=[r]))}
    exec(_source("_publier_social"), ns)  # noqa: S102 — code du depot
    asyncio.run(ns["_publier_social"](Obj(id=1), "youtube", discord.Embed(title="Vidéo", url=URL)))
    assert envois[-1]["cle"] == URL and URL in lecteur["_texte_v2"](envois[-1]["view"].children, None)
    asyncio.run(ns["_publier_social"](Obj(id=1), "twitter", discord.Embed(description="Tweet")))
    assert envois[-1]["cle"] is None, "sans URL : la carte se reconnait a son texte entier"

    monkeypatch.setattr(rp, "_webhook_send", webhook_send)
    billet = {"topic_id": 42, "titre": "Notes", "domaine": "?", "corps": "x", "cree_le": None}
    assert asyncio.run(rp.publier_actu(None, Obj(id=2, name="actus"), billet)) is True
    lien = roblox_news.lien_billet(42)
    assert lien and envois[-1]["cle"] == lien
    assert lien in lecteur["_texte_v2"](envois[-1]["view"].children, None), "la cle se retrouve dans la fiche"
