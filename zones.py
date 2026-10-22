"""zones.py — les compartiments du serveur (22/10/2026).

Le fondateur, dans la nuit : « je veux une catégorie… tu enlèves tout ce qui est dans Communautaire et
dans Rell Seas… tu crées uniquement un fil qui s'appelle communautaire et un fil qui s'appelle Rell
Seas. Dans le fil communautaire… le chat, médias, tout ce qui est lié au serveur… c'est les salons
dans un fil… dans le fil Rell Seas… trade, crew… et à l'intérieur, dans chacun des fils, tout va être
super bien fait… il n'y a que deux fils… le vocal, tu le laisses tel qu'il est… toutes les
fonctionnalités qui sont liées à ça fonctionnent, et ça cible bien les salons. »

· Communautaire : 💬communautaire et 🌊rell-seas (deux forums), puis 🔊Join, inchangé.
  💬communautaire : ❓ Aide · 💬 Chat · 📸 Médias · 💡 Suggestions · 🚀 Boosts · 🤖 Commandes.
  🌊rell-seas : 🧭 Guide · 🌊 Chat Rell Seas · 🛟 Help · 🤝 Trade.
On écrit dans les posts, on n'en crée pas. Chaque fonction du bot vise son post : l'orientation, les
suggestions, les boosts, l'entraide et le trade (une carte par demande). Les anciens salons partent dans « 📦 Archives », cachée aux membres : rien n'est perdu, le
fondateur choisit ce qu'il supprime, d'un clic, dans 📋logs.

La zone du clan GoRP (sa catégorie existe) : 📣 annonces et 🧵 discussions, voir `installer_clan`.
"""
from __future__ import annotations

import asyncio
from collections import namedtuple

import discord

import boosts
import config_salons
import entraide
import suggestions
import visuels
from ui_v2 import LayoutView

FORUM_COMMU = "💬communautaire"
FORUM_RELL = "🌊rell-seas"
CATEGORIE = "· Communautaire"
ARCHIVES = "📦 Archives"
SUJET_COMMU = ("🇫🇷 Le serveur au même endroit : aide, chat, médias, suggestions, boosts, commandes. On écrit dans "
               "les posts.\n🇬🇧 The server in one place: help, chat, media, suggestions, boosts, commands. Write in "
               "the posts.")
SUJET_RELL = ("🇫🇷 Tout Rell Seas : le guide, le chat du jeu, l'entraide, le trade. On écrit dans les posts.\n"
              "🇬🇧 All of Rell Seas: the guide, the game chat, help, trade. Write in the posts.")
#  Les posts, dans l'ordre d'affichage : (clé, titre, verrouillé, texte d'ouverture — vide : la
#  fonction qui l'habite donne le sien). Verrouillé : on y clique, on n'y écrit pas.
POSTS_COMMU = (
    ("aide", "❓ Aide · Help", True, ""),
    ("chat", "💬 Chat", False,
     "🇫🇷 Discute de tout, en français ou en anglais. Bienvenue !\n🇬🇧 Talk about anything, in French or English. "
     "Welcome!"),
    ("medias", "📸 Médias · Media", False,
     "🇫🇷 Partage ici tes captures, clips et vidéos.\n🇬🇧 Share your screenshots, clips and videos here."),
    ("suggestions", "💡 Suggestions", True, ""),
    ("boosts", "🚀 Boosts", True, ""),
    ("commandes", "🤖 Commandes · Commands", False,
     "🇫🇷 Les commandes des bots, c'est ici : le chat reste lisible.\n🇬🇧 Use the bots' commands here: the chat "
     "stays readable."),
)
POSTS_RELL = (
    ("guide", "🧭 Guide · Rell Seas", True, ""),
    ("rell_chat", "🌊 Chat Rell Seas", False,
     "🇫🇷 Le chat de Rell Seas : îles, fruits, mises à jour, astuces.\n🇬🇧 The Rell Seas chat: islands, fruits, "
     "updates, tips."),
    ("help", "🛟 Help · Entraide", False, ""),
    ("trade", "🤝 Trade · Échanges", False, ""),
)
#  Dans les deux forums : on lit, on écrit dans les posts, on montre (images, liens), on réagit, on
#  utilise les commandes — mais on n'ouvre pas de nouveau post (« il n'y a que deux fils »).
OUVERT = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False,
                                     send_messages_in_threads=True, create_public_threads=False,
                                     create_private_threads=False, attach_files=True, embed_links=True,
                                     add_reactions=True, use_application_commands=True)
PAROLE = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True,
                                     send_messages_in_threads=True, attach_files=True, embed_links=True,
                                     add_reactions=True, use_application_commands=True)
BOT = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True,
                                  send_messages_in_threads=True, create_public_threads=True, manage_threads=True,
                                  manage_messages=True, embed_links=True, attach_files=True)
LECTURE_CLAN = discord.PermissionOverwrite(**config_salons.LECTURE)
EQUIPE_CLAN = discord.PermissionOverwrite(**config_salons.EQUIPE_TEXTE, send_messages_in_threads=True)

#  La zone du clan GoRP (22/10/2026, nuit) : le fondateur a choisi « Un seul forum » — comme
#  Communautaire, un forum du clan et ses posts ; le 🔊 Join reste ; les anciens salons partent.
CLAN_FORUM = "🦜▷・clan-gorp"
SUJET_CLAN = ("🇫🇷 Le clan GoRP : guide, infos, annonces, chat, économie, trade, taverne. On écrit dans les posts.\n"
              "🇬🇧 The GoRP clan: guide, info, announcements, chat, economy, trade, tavern. Write in the posts.")
CLAN_POSTS = (
    ("guide", "🧭 Guide du clan · Clan guide", True, ""),
    ("infos", "📢 Infos · Info", True,
     "🇫🇷 Ce qu'il faut savoir sur le clan.\n🇬🇧 What to know about the clan."),
    ("annonces", "📣 Annonces · Announcements", True,
     "🇫🇷 Les annonces du clan : lis-les, clique « ✅ Vu ».\n🇬🇧 Clan announcements: read them, click “✅ Seen”."),
    ("chat", "💬 Chat", False,
     "🇫🇷 Le chat du clan : on parle de tout, entre nous.\n🇬🇧 The clan chat: talk about anything, among us."),
    ("economie", "💰 Économie · Economy", False,
     "🇫🇷 L'économie du clan : objectifs, dons, dépenses.\n🇬🇧 The clan's economy: goals, donations, spending."),
    ("trade", "🤝 Trade du clan · Clan trade", False,
     "🇫🇷 Les échanges entre membres du clan : propose, demande.\n🇬🇧 Trades between clan members: offer, ask."),
    ("taverne", "🍺 Taverne · Tavern", False,
     "🇫🇷 On se pose, on raconte ses aventures en mer.\n🇬🇧 Sit down and tell your adventures at sea."),
)
#  Le staff du clan écrit aussi dans les posts verrouillés (infos, annonces) : « Gérer les fils ».
EQUIPE_FORUM_CLAN = discord.PermissionOverwrite(**config_salons.EQUIPE_TEXTE, send_messages_in_threads=True,
                                                manage_threads=True)
GUIDE_CLAN_VERSION = 1
INFOS_MAX = 100       # messages d'info-gorp recopiés au plus

#  Un post, même endormi (hors mémoire) : son identifiant et son lien suffisent au panneau ❓ aide.
Post = namedtuple("Post", "id jump_url")
GUIDE_VERSION = 1

_cfg = _db_set = _lecteurs = _ticket = _boutons_langue = None
_log = print
_verrous: dict = {}


def setup(*, cfg, db_set, lecteurs=None, ticket=None, boutons_langue=None, log=None):
    """`lecteurs(g, c)` → les rôles qui voient « 📦 Archives » (la direction et au-dessus) ;
    `ticket(g)` → le salon des tickets ; `boutons_langue()` → les boutons 🇫🇷 / 🇬🇧 du bot."""
    global _cfg, _db_set, _lecteurs, _ticket, _boutons_langue, _log
    _cfg, _db_set, _lecteurs, _ticket, _boutons_langue = cfg, db_set, lecteurs, ticket, boutons_langue
    _log = log or print


def _verrou(gid):
    return _verrous.setdefault(gid, asyncio.Lock())


def communautaire(g):
    return entraide.categorie_communautaire(g)


async def conf(g) -> dict:
    c = await _cfg(g.id)
    return {"forums": {"commu": int(c.get("zones_forum_commu", 0) or 0),
                       "rell": int(c.get("zones_forum_rell", 0) or 0)},
            "posts": {k: dict(v) for k, v in (c.get("zones_posts") or {}).items()},
            "archives": [int(x) for x in c.get("zones_archives") or []],
            "categorie_archives": int(c.get("zones_categorie_archives", 0) or 0),
            "actif": bool(c.get("zones_v2"))}


def ids_salons(c: dict) -> set:
    """Les salons des zones (et ce qui a été rangé aux archives) : aucun réglage de masse n'y touche."""
    cles = ("zones_forum_commu", "zones_forum_rell", "zones_categorie_archives", "clan_annonces", "clan_forum",
            "clan_forum_v2", "zones_rell", "zones_chat", "zones_vocal", "zones_forum")
    ids = {int(c.get(k, 0) or 0) for k in cles} | {int(x) for x in c.get("zones_archives") or []}
    return {i for i in ids if i} | entraide.ids_salons(c) | ({int(c["eq_forum"])} if c.get("eq_forum") else set())


def post(g, cfz: dict, cle: str):
    pid = int((cfz["posts"].get(cle) or {}).get("id", 0) or 0)
    return Post(pid, f"https://discord.com/channels/{g.id}/{pid}") if pid else None


async def _resoudre(g, cid):
    """Un salon ou un post, même endormi ; None s'il n'existe plus. Une panne lève."""
    cid = int(cid or 0)
    if not cid:
        return None
    ch = g.get_channel_or_thread(cid)
    if ch is not None:
        return ch
    try:
        return await g.fetch_channel(cid)
    except discord.NotFound:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Les deux forums et leurs posts
# ═══════════════════════════════════════════════════════════════════════════════

def _vue_texte(titre: str, texte: str) -> LayoutView:
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(f"### {titre}\n{texte}" if texte else f"### {titre}"),
                                    accent_color=discord.Color(0x5865F2)))
    return v


async def _ouverture(g, cle: str, titre: str, texte: str) -> LayoutView:
    """Le message d'ouverture d'un post : son texte, ou ce que la fonction qui l'habite affiche."""
    if texte:
        return _vue_texte(titre, texte)
    if cle in ("aide", "guide"):
        return _vue_texte(titre, "🇫🇷 Le guide arrive…\n🇬🇧 The guide is on its way…")
    if cle == "suggestions":
        return suggestions.vue_panneau(await suggestions.ouvertes(g))
    if cle == "boosts":
        return boosts.vue_entete(g)
    if cle in ("help", "trade"):
        return entraide.vue_panneau("entraide" if cle == "help" else "trade", await entraide.conf(g), g)
    return _vue_texte(titre, "")


async def _forum(g, cat, nom: str, sujet: str, cle_cfg: str, forum: bool, faits: list):
    c = await _cfg(g.id)
    ch = await _resoudre(g, c.get(cle_cfg, 0))
    if ch is not None:
        return ch
    droits = {g.default_role: OUVERT, g.me: BOT}
    if forum:
        ch = await g.create_forum(nom, category=cat, topic=sujet, overwrites=droits,
                                  default_auto_archive_duration=10080,
                                  default_layout=discord.ForumLayoutType.list_view,
                                  default_sort_order=discord.ForumOrderType.creation_date,
                                  reason="Deux forums : tout le serveur dedans")
    else:
        ch = await g.create_text_channel(nom, category=cat, topic=sujet[:1024], overwrites=droits,
                                         reason="Deux salons : tout le serveur dedans, en fils")
    await _db_set(g.id, cle_cfg, ch.id)
    faits.append(f"salon {ch.name}")
    return ch


async def _posts(g, porteur, definitions, posts: dict, faits: list) -> None:
    """Les posts d'un forum : créés s'ils manquent — du dernier au premier, le forum les montre du plus
    récent au plus ancien —, réveillés s'ils dorment, verrouillés s'il le faut."""
    for cle, titre, verrou, texte in reversed(definitions):
        fil = await _resoudre(g, (posts.get(cle) or {}).get("id", 0))
        if fil is None:
            vue = await _ouverture(g, cle, titre, texte)
            if isinstance(porteur, discord.ForumChannel):
                fil = (await porteur.create_thread(name=titre, view=vue, auto_archive_duration=10080,
                                                   allowed_mentions=discord.AllowedMentions.none(),
                                                   reason="Un post du forum")).thread
                ouverture = fil.id
            else:
                fil = await porteur.create_thread(name=titre, type=discord.ChannelType.public_thread,
                                                  auto_archive_duration=10080, reason="Un fil du salon")
                ouverture = (await fil.send(view=vue, allowed_mentions=discord.AllowedMentions.none())).id
            posts[cle] = {"id": fil.id, "ouverture": ouverture}
            faits.append(f"post {titre}")
        reglage = {}
        if getattr(fil, "archived", False):
            reglage["archived"] = False
        if verrou and not getattr(fil, "locked", False):
            reglage["locked"] = True
        if reglage:
            try:
                await fil.edit(**reglage)
            except discord.HTTPException as ex:
                _log(f"[ZONES:DETAIL] post {cle} {type(ex).__name__} {ex}")


async def _brancher(g, posts: dict) -> None:
    """« Ça cible bien les salons » : chaque fonction du bot vise son post."""
    c = await _cfg(g.id)
    p = posts
    if int(c.get("aide_salon", 0) or 0) != p["aide"]["id"]:
        await _db_set(g.id, "aide_salon", p["aide"]["id"])
        await _db_set(g.id, "aide_message", p["aide"]["ouverture"])
        await _db_set(g.id, "aide_message_v", "")
    if int(c.get("suggestions_salon", 0) or 0) != p["suggestions"]["id"]:
        await _db_set(g.id, "suggestions_salon", p["suggestions"]["id"])
        await _db_set(g.id, "suggestions_panneau", p["suggestions"]["ouverture"])
    if int(c.get("boosts_salon", 0) or 0) != p["boosts"]["id"]:
        await _db_set(g.id, "boosts_salon", p["boosts"]["id"])
        await _db_set(g.id, "boosts_entete", p["boosts"]["ouverture"])
        await _db_set(g.id, "boosts_entete_v", boosts._signature(g))
    salons = {"entraide": p["help"]["id"], "trade": p["trade"]["id"]}
    if {k: int(v) for k, v in dict(c.get("rs_salons") or {}).items()} != salons:
        ouvertures = {"entraide": p["help"]["ouverture"], "trade": p["trade"]["ouverture"]}
        await _db_set(g.id, "rs_salons", salons)
        await _db_set(g.id, "rs_panneaux", dict(ouvertures))
        await _db_set(g.id, "rs_ouvertures", ouvertures)


async def installer(g, *, forum: bool | None = None) -> list:
    """Crée ce qui manque — les deux forums, leurs posts, les rôles de guide —, branche chaque
    fonction sur son post, range ; la première fois, ferme proprement l'ancienne installation (les
    demandes à republier) et range ses salons. Ne supprime rien. Rend la liste de ce qui a été fait."""
    p = getattr(g.me, "guild_permissions", None)
    if not (p and p.manage_channels and p.manage_roles):
        raise PermissionError("Il me faut « Gérer les salons » et « Gérer les rôles ».")
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    faits = []
    async with _verrou(g.id):
        cat = communautaire(g) or await entraide.categorie_cible(g)
        if cat is None:
            cat = await g.create_category(CATEGORIE, reason="Le serveur en deux forums")
            faits.append(f"catégorie {cat.name}")
        faits += await entraide.installer(g, forum=forum, creer_salons=False)
        f_commu = await _forum(g, cat, FORUM_COMMU, SUJET_COMMU, "zones_forum_commu", forum, faits)
        f_rell = await _forum(g, cat, FORUM_RELL, SUJET_RELL, "zones_forum_rell", forum, faits)
        posts = (await conf(g))["posts"]
        await _posts(g, f_commu, POSTS_COMMU, posts, faits)
        await _posts(g, f_rell, POSTS_RELL, posts, faits)
        await _db_set(g.id, "zones_posts", posts)
        avant = dict(await _cfg(g.id))
        await _brancher(g, posts)
        if not avant.get("zones_demenage"):
            await _db_set(g.id, "zones_demenage", 1)
            faits += await _reporter(g, _correspondances(avant, posts, cat))
            faits += await _demenager(g, avant)
            faits += await _archiver(g, cat, {f_commu.id, f_rell.id})
        await entraide.assurer_panneaux(g, forcer=True)
        await _db_set(g.id, "zones_v2", 1)
    try:
        await assurer_guide(g)
    except discord.HTTPException as ex:
        _log("[ZONES][E5] guide non posé")
        _log(f"[ZONES][E5:DETAIL] {type(ex).__name__} {ex}")
    try:
        await ordonner(g)
    except discord.HTTPException as ex:
        _log("[ZONES][E1] compartiments non rangés")
        _log(f"[ZONES][E1:DETAIL] {type(ex).__name__} {ex}")
    try:
        await boosts.synchroniser(g)
    except discord.HTTPException as ex:
        _log(f"[ZONES:DETAIL] boosts {type(ex).__name__} {ex}")
    return faits


def _correspondances(avant: dict, posts: dict, commu) -> dict:
    """Ancien salon → son post (💬chat → 💬 Chat, 🛟help → 🛟 Help…) : ce qui visait l'un suivra l'autre."""
    paires = {}

    def lier(ancien, cle):
        ancien = int(ancien or 0)
        if ancien and cle in posts and ancien != int(posts[cle]["id"]):
            paires[ancien] = int(posts[cle]["id"])
    for cle_cfg, cle in (("aide_salon", "aide"), ("suggestions_salon", "suggestions"), ("boosts_salon", "boosts"),
                         ("zones_forum", "medias"), ("zones_chat", "rell_chat")):
        lier(avant.get(cle_cfg), cle)
    rs = dict(avant.get("rs_salons") or {})
    lier(rs.get("entraide"), "help")
    lier(rs.get("trade"), "trade")
    if commu is not None:
        chat = next((ch for ch in commu.channels if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel))
                     and "chat" in config_salons.normaliser(ch.name).split()), None)
        if chat is not None:
            lier(chat.id, "chat")
    return paires


async def _reporter(g, paires: dict, *, fusion: bool = False) -> list:
    """Les réglages qui visaient un ancien salon le suivent dans son post : liens et images permis,
    l'accueil et l'au revoir. (L'immunité, gardée en base, suit avec `bot._reporter_immunites`.)
    `fusion` : les correspondances déjà notées restent (la zone du clan s'ajoute à celle des forums)."""
    toutes = dict((await _cfg(g.id)).get("zones_correspondances") or {}) if fusion else {}
    toutes.update({str(k): v for k, v in paires.items()})
    await _db_set(g.id, "zones_correspondances", toutes)
    if not paires:
        return []
    c = await _cfg(g.id)
    faits = []
    for cle in ("link_allowed_channels", "image_allowed_channels"):
        liste = [int(x) for x in c.get(cle) or [] if str(x).isdigit()]
        neufs = [paires[x] for x in liste if x in paires and paires[x] not in liste]
        if neufs:
            await _db_set(g.id, cle, liste + neufs)
            faits.append(f"{cle} suit ({len(neufs)})")
    for cle in ("welcome_channel", "goodbye_channel"):
        ancien = int(c.get(cle, 0) or 0)
        if ancien in paires:
            await _db_set(g.id, cle, paires[ancien])
            faits.append(f"{cle} suit")
    return faits


async def _demenager(g, avant: dict) -> list:
    """L'ancienne installation se ferme proprement : les demandes ouvertes (un post par demande) se
    ferment en disant où republier, les idées encore en vote passent dans le post 💡 Suggestions avec
    leurs votes."""
    faits = []
    n = await entraide.fermer_anciennes(g, "🔒 L'entraide déménage : republie ta demande dans 🌊rell-seas › 🛟 Help."
                                           " · Moved: post again in 🌊rell-seas › 🛟 Help.")
    if n:
        faits.append(f"{n} ancienne(s) demande(s) fermée(s)")
    ancien = int(avant.get("suggestions_salon", 0) or 0)
    if ancien:
        n = await suggestions.demenager(g, ancien)
        if n:
            faits.append(f"{n} idée(s) en vote republiée(s)")
    return faits


# ═══════════════════════════════════════════════════════════════════════════════
#  Les archives : l'ancienne installation, cachée, supprimée quand le fondateur le décide
# ═══════════════════════════════════════════════════════════════════════════════

async def _categorie_archives(g):
    c = await _cfg(g.id)
    cat = g.get_channel(int(c.get("zones_categorie_archives", 0) or 0))
    if isinstance(cat, discord.CategoryChannel):
        return cat
    ows = {g.default_role: discord.PermissionOverwrite(view_channel=False),
           g.me: discord.PermissionOverwrite(view_channel=True, read_message_history=True, manage_channels=True)}
    for r in (_lecteurs(g, c) if _lecteurs else []) or []:
        ows[r] = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False,
                                             connect=False)
    cat = await g.create_category(ARCHIVES, overwrites=ows, reason="L'ancienne installation, cachée aux membres")
    await _db_set(g.id, "zones_categorie_archives", cat.id)
    return cat


async def _archiver(g, commu, garder: set) -> list:
    """« Tu enlèves tout ce qui est dans Communautaire et dans Rell Seas… le vocal, tu le laisses. »
    Les salons partent aux archives (cachés aux membres, leur historique intact) ; le vocal de
    Communautaire ne bouge pas ; celui de l'ancienne zone Rell Seas, vide, part ; la zone aussi."""
    c = await _cfg(g.id)
    vocaux = (discord.VoiceChannel, discord.StageChannel)
    a_ranger = [ch for ch in (commu.channels if commu is not None else [])
                if ch.id not in garder and not isinstance(ch, vocaux)]
    rell = g.get_channel(int(c.get("zones_rell", 0) or 0))
    vocal_rell = None
    if isinstance(rell, discord.CategoryChannel):
        for ch in rell.channels:
            if not isinstance(ch, vocaux):
                a_ranger.append(ch)
            elif ch.id == int(c.get("zones_vocal", 0) or 0):
                vocal_rell = ch
    faits = []
    if a_ranger:
        archives = await _categorie_archives(g)
        ranges = [int(x) for x in c.get("zones_archives") or []]
        for ch in a_ranger:
            try:
                await ch.edit(category=archives, sync_permissions=True,
                              reason="Aux archives : tout passe par les deux forums")
            except discord.HTTPException as ex:
                _log("[ZONES][E3] salon non rangé aux archives")
                _log(f"[ZONES][E3:DETAIL] {ch.id} {type(ex).__name__} {ex}")
                continue
            ranges.append(ch.id)
            faits.append(f"{ch.name} aux archives")
        await _db_set(g.id, "zones_archives", list(dict.fromkeys(ranges)))
    if vocal_rell is not None and not getattr(vocal_rell, "members", []):
        voix = dict(c.get("temp_voice_config") or {})
        hubs = dict(voix.get("hubs") or {})
        if hubs.pop(str(vocal_rell.id), None) is not None:
            voix["hubs"] = hubs
            await _db_set(g.id, "temp_voice_config", voix)
        await vocal_rell.delete(reason="Un seul vocal : celui de Communautaire")
        await _db_set(g.id, "zones_vocal", 0)
        faits.append("vocal de l'ancienne zone Rell Seas retiré")
    if isinstance(rell, discord.CategoryChannel) and not rell.channels:
        await rell.delete(reason="Rell Seas vit maintenant dans le forum 🌊rell-seas")
        await _db_set(g.id, "zones_rell", 0)
        faits.append(f"catégorie {rell.name} retirée")
    return faits


def archives(g, c: dict) -> list:
    """Les salons encore aux archives (ceux qu'on en a sortis à la main n'y sont plus). `c` : la
    configuration du serveur."""
    cat = g.get_channel(int(c.get("zones_categorie_archives", 0) or 0))
    out = []
    for cid in [int(x) for x in c.get("zones_archives") or []]:
        ch = g.get_channel(cid)
        if ch is not None and cat is not None and getattr(ch, "category_id", None) == cat.id:
            out.append(ch)
    return out


async def supprimer_archives(g, ids: list) -> int:
    """Le fondateur l'a confirmé : ces salons d'archives disparaissent, et la catégorie si elle est vide."""
    cfz, c = await conf(g), await _cfg(g.id)
    gardes = {ch.id: ch for ch in archives(g, c)}
    n, supprimes = 0, set()
    for cid in ids:
        ch = gardes.get(int(cid))
        if ch is None:
            continue
        try:
            await ch.delete(reason="Archives supprimées par le fondateur")
            supprimes.add(ch.id)
            n += 1
        except discord.HTTPException as ex:
            _log("[ZONES][E4] archive non supprimée")
            _log(f"[ZONES][E4:DETAIL] {cid} {type(ex).__name__} {ex}")
    #  Le cache de Discord suit l'effacement avec un temps de retard : on compte ce qu'on vient d'effacer.
    restants = [cid for cid in cfz["archives"] if cid not in supprimes and g.get_channel(cid) is not None]
    await _db_set(g.id, "zones_archives", restants)
    cat = g.get_channel(cfz["categorie_archives"])
    if isinstance(cat, discord.CategoryChannel) and not [ch for ch in cat.channels if ch.id not in supprimes]:
        try:
            await cat.delete(reason="Archives vides")
            await _db_set(g.id, "zones_categorie_archives", 0)
        except discord.HTTPException as ex:
            _log(f"[ZONES:DETAIL] catégorie d'archives {type(ex).__name__} {ex}")
    return n


# ═══════════════════════════════════════════════════════════════════════════════
#  Rangement, entretien, panneau ❓ aide
# ═══════════════════════════════════════════════════════════════════════════════

def _dans(ch, cat):
    return ch if ch is not None and cat is not None and getattr(ch, "category_id", None) == cat.id else None


async def _ranger(cat, voulu: list) -> bool:
    """Les salons de `voulu` en tête de `cat`, dans cet ordre ; les autres suivent, les vocaux en bas."""
    voulu = list(dict.fromkeys(ch for ch in voulu if ch is not None))
    texte = [ch for ch in sorted(cat.channels, key=lambda c: c.position)
             if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel))]
    if not voulu or texte[:len(voulu)] == voulu:
        return False
    for n, ch in enumerate(voulu):
        if n == 0:
            await ch.move(beginning=True, category=cat, sync_permissions=False, reason="Rangé par priorité")
        else:
            await ch.move(after=voulu[n - 1], category=cat, sync_permissions=False, reason="Rangé par priorité")
    return True


async def ordonner(g) -> bool:
    """Communautaire : 💬communautaire, 🌊rell-seas, puis le vocal."""
    cfz, commu = await conf(g), communautaire(g)
    if commu is None:
        return False
    return await _ranger(commu, [_dans(g.get_channel(cfz["forums"]["commu"]), commu),
                                 _dans(g.get_channel(cfz["forums"]["rell"]), commu)])


async def entretenir(g) -> None:
    """Toutes les 30 minutes : les posts (des deux forums et du forum du clan) restent ouverts ; un post
    qui doit rester verrouillé l'est. Jamais l'inverse : un post que le staff a verrouillé le reste. Les
    deux guides suivent les posts et les rôles."""
    for guide in (assurer_guide, assurer_guide_clan):
        try:
            await guide(g)
        except discord.HTTPException as ex:
            _log(f"[ZONES:DETAIL] guide {type(ex).__name__} {ex}")
    cfz, c = await conf(g), await _cfg(g.id)
    verrous = {cle for cle, _t, v, _x in POSTS_COMMU + POSTS_RELL if v}
    verrous_clan = {cle for cle, _t, v, _x in CLAN_POSTS if v}
    a_suivre = [(cle, info.get("id", 0), cle in verrous) for cle, info in cfz["posts"].items()]
    a_suivre += [(f"clan {cle}", (info or {}).get("id", 0), cle in verrous_clan)
                 for cle, info in dict(c.get("clan_posts") or {}).items()]
    for cle, fid, verrou in a_suivre:
        try:
            fil = await _resoudre(g, fid)
        except discord.HTTPException as ex:
            _log(f"[ZONES:DETAIL] lecture du fil {cle} {ex}")
            continue
        if fil is None:
            continue
        reglage = {}
        if getattr(fil, "archived", False):
            reglage["archived"] = False
        if verrou and not getattr(fil, "locked", False):
            reglage["locked"] = True
        if reglage:
            try:
                await fil.edit(**reglage)
            except discord.HTTPException as ex:
                _log(f"[ZONES:DETAIL] réveil du fil {cle} {ex}")


def vue_guide(g, c: dict, cfz: dict, cfe: dict) -> tuple:
    """« Un fil ultra professionnel » : le guide de Rell Seas, en tête du forum 🌊rell-seas. Chaque
    post, comment il marche, qui certifie, le clan ; un bouton par post (jamais un bouton qui ment :
    une ligne n'apparaît que si son post existe). Rend (la vue, sa signature)."""
    hubs = (c.get("temp_voice_config") or {}).get("hubs") or {}
    vocal = next((ch for ch in (g.get_channel(int(k)) for k in hubs if str(k).isdigit())
                  if ch is not None and not config_salons.est_clan(getattr(getattr(ch, "category", None), "name", ""))),
                 None)
    roles = {cle: entraide.role_zone(g, cfe, cle) for cle in ("aide", "boss", "farm", "trade")}
    guides = " ".join(r.mention for cle, r in roles.items() if r is not None and cle != "trade")
    mm = roles.get("trade")
    ticket = _ticket(g) if _ticket else None
    lignes = [
        (post(g, cfz, "rell_chat"), "### 🌊 Discuter · Talk\nLe chat du jeu : îles, fruits, mises à jour, astuces"
         + (f". Le vocal : 🔊 <#{vocal.id}>." if vocal is not None else ".")
         + "\n-# The game chat: islands, fruits, updates, tips.", "Ouvrir · Open"),
        (post(g, cfz, "help"), "### 🛟 S'entraider · Get help\nChoisis Aide, Boss, Farm ou Chill et remplis : ta carte "
         "s'affiche, des joueurs cliquent « J'aide ». C'est réglé ? Tu la clôtures toi-même.\n-# Pick a type and fill "
         "in: your card shows up, players click “I'll help”. Close it yourself when done.", "Demander · Ask"),
        (post(g, cfz, "trade"), "### 🤝 Échanger · Trade\nPropose ton échange. Avec un inconnu, ne donne jamais en "
         "premier : appelle un middleman. Bon des deux côtés ? « Échange conclu ».\n-# Never give first to a stranger: "
         "call a middleman. Both happy? “Trade done”.", "Échanger · Trade"),
    ]
    items = [visuels.bandeau("rs_guide", "Guide Rell Seas"),
             discord.ui.TextDisplay("🇫🇷 **Bienvenue à bord.** Ici, tout se passe dans les posts de ce forum : on "
                                    "discute, on s'entraide, on échange — en français ou en anglais.\n🇬🇧 **Welcome "
                                    "aboard.** Everything happens in this forum's posts: chat, help each other, trade "
                                    "— in French or English.")]
    if _boutons_langue is not None:
        items.append(discord.ui.ActionRow(*_boutons_langue()))
    presentes = [(p, t, b) for p, t, b in lignes if p is not None]
    if presentes:
        items.append(discord.ui.Separator())
        for p, texte, libelle in presentes:
            items.append(discord.ui.Section(discord.ui.TextDisplay(texte),
                                            accessory=discord.ui.Button(label=libelle, url=p.jump_url)))
    items.append(discord.ui.Separator())
    certif = ["### 🏅 Qui certifie · Who certifies"]
    if guides:
        certif.append(f"Les guides {guides} certifient l'aide · certify the help.")
    if mm is not None:
        certif.append(f"{mm.mention} sécurise les échanges · secures trades.")
    certif.append("-# Sans activité, une demande se ferme seule ; close, elle disparaît — le staff en garde la trace. "
                  "· Inactive requests close by themselves; closed ones disappear, the staff keeps a record.")
    items.append(discord.ui.TextDisplay("\n".join(certif)))
    if ticket is not None:
        items.append(discord.ui.Section(
            discord.ui.TextDisplay("### 🏴‍☠️ Le clan GoRP · The GoRP clan\nTu veux nous rejoindre ? Une candidature par "
                                   "ticket.\n-# Want to join us? Apply with a ticket."),
            accessory=discord.ui.Button(label="Postuler · Apply", url=ticket.jump_url)))
    items.append(discord.ui.TextDisplay("-# 🛡️ Personne du staff ne te demandera ton mot de passe · No staff will ever "
                                        "ask for your password · pas d'invitation vers d'autres serveurs · no invites"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(0x06B6D4)))
    signature = "|".join([str(GUIDE_VERSION), *(str(p.id) for p, _t, _b in presentes),
                          str(getattr(vocal, "id", 0)), *(str(getattr(r, "id", 0)) for r in roles.values()),
                          str(getattr(ticket, "id", 0)), str(int(_boutons_langue is not None))])
    return v, signature


async def assurer_guide(g) -> bool:
    """Le message d'ouverture du post 🧭 Guide suit les posts, le vocal et les rôles (réécrit seulement
    quand quelque chose a changé). Rend True s'il a été réécrit."""
    cfz, c = await conf(g), await _cfg(g.id)
    info = cfz["posts"].get("guide") or {}
    if not info.get("id"):
        return False
    vue, signature = vue_guide(g, c, cfz, await entraide.conf(g))
    if c.get("zones_guide_v") == signature:
        return False
    fil = await _resoudre(g, info["id"])
    if fil is None:
        return False
    if getattr(fil, "archived", False):
        await fil.edit(archived=False)
    await fil.get_partial_message(int(info.get("ouverture") or info["id"])).edit(
        view=vue, allowed_mentions=discord.AllowedMentions.none())
    await _db_set(g.id, "zones_guide_v", signature)
    return True


def lignes_aide(g, c: dict, cfz: dict) -> dict:
    """Le contenu du panneau ❓ aide, par forum : {titre: [(post, texte, bouton)]}. Une ligne n'apparaît
    que si son post existe."""
    hubs = (c.get("temp_voice_config") or {}).get("hubs") or {}
    vocal = next((ch for ch in (g.get_channel(int(k)) for k in hubs if str(k).isdigit())
                  if ch is not None and not config_salons.est_clan(getattr(getattr(ch, "category", None), "name", ""))),
                 None)
    voc = f" · 🔊 <#{vocal.id}>" if vocal is not None else ""
    return {
        "Communautaire · Community": [
            (post(g, cfz, "chat"), "💬 **Chat** — discuter de tout · talk about anything" + voc, "Ouvrir · Open"),
            (post(g, cfz, "medias"), "📸 **Médias** — captures, clips · screenshots, clips", "Ouvrir · Open"),
            (post(g, cfz, "suggestions"), "💡 **Suggestions** — propose une idée · suggest an idea", "Ouvrir · Open"),
            (post(g, cfz, "commandes"), "🤖 **Commandes** — les commandes des bots · bot commands", "Ouvrir · Open"),
        ],
        "Rell Seas": [
            (post(g, cfz, "rell_chat"), "🌊 **Chat Rell Seas** — le jeu · the game", "Ouvrir · Open"),
            (post(g, cfz, "help"), "🛟 **Help** — une question, un boss, du farm, du chill · a question, a boss, "
                                   "farming, chilling", "Demander · Ask"),
            (post(g, cfz, "trade"), "🤝 **Trade** — fruits et objets, avec middleman · fruits & items, with a "
                                    "middleman", "Échanger · Trade"),
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  La zone du clan GoRP
# ═══════════════════════════════════════════════════════════════════════════════

def categorie_clan(g):
    """La catégorie du clan (« 🦜 · GoRp_SEA »), même règle que `config_salons.est_clan`."""
    return next((cat for cat in getattr(g, "categories", []) or [] if config_salons.est_clan(cat.name)), None)


def _vocal_clan(g, c: dict):
    """Le 🔊 Join du clan : le salon « créer un vocal » rangé dans la catégorie du clan."""
    hubs = (c.get("temp_voice_config") or {}).get("hubs") or {}
    return next((ch for ch in (g.get_channel(int(k)) for k in hubs if str(k).isdigit())
                 if ch is not None and config_salons.est_clan(getattr(getattr(ch, "category", None), "name", ""))),
                None)


async def installer_clan(g, role, equipe=(), *, forum: bool | None = None) -> list:
    """22/10/2026 (nuit), le fondateur : « Un seul forum ». Dans la catégorie du clan, 🦜▷・clan-gorp et
    ses posts (guide, infos, annonces, chat, économie, trade du clan, taverne), réservés au clan et au
    staff ; les annonces du clan visent leur post. Ne supprime rien : les anciens salons partent avec
    `demenager_clan`. Le 🔊 Join ne bouge pas. Rend ce qui a été fait."""
    cat = categorie_clan(g)
    if cat is None or role is None:
        return []
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    faits = []
    async with _verrou(("clan", g.id)):
        c = await _cfg(g.id)
        ows = {g.default_role: discord.PermissionOverwrite(view_channel=False), role: OUVERT, g.me: BOT}
        for r in equipe or ():
            if r is not None and r != role:
                ows[r] = EQUIPE_FORUM_CLAN
        porteur = await _resoudre(g, c.get("clan_forum_v2", 0))
        if porteur is None:
            if forum:
                porteur = await g.create_forum(CLAN_FORUM, category=cat, topic=SUJET_CLAN, overwrites=ows,
                                               default_auto_archive_duration=10080,
                                               default_layout=discord.ForumLayoutType.list_view,
                                               default_sort_order=discord.ForumOrderType.creation_date,
                                               reason="Clan GoRP : un seul forum")
            else:
                porteur = await g.create_text_channel(CLAN_FORUM, category=cat, topic=SUJET_CLAN[:1024],
                                                      overwrites=ows, reason="Clan GoRP : un seul salon, en fils")
            await _db_set(g.id, "clan_forum_v2", porteur.id)
            faits.append(f"salon {porteur.name}")
        posts = {k: dict(v) for k, v in (c.get("clan_posts") or {}).items()}
        await _posts(g, porteur, CLAN_POSTS, posts, faits)
        await _db_set(g.id, "clan_posts", posts)
        if not c.get("clan_anciens"):
            #  Avant de rebrancher : où étaient les annonces et les discussions d'avant.
            await _db_set(g.id, "clan_anciens", {"annonces": int(c.get("clan_annonces", 0) or 0),
                                                 "forum": int(c.get("clan_forum", 0) or 0)})
        if int(c.get("clan_annonces", 0) or 0) != posts["annonces"]["id"]:
            await _db_set(g.id, "clan_annonces", posts["annonces"]["id"])
        await _db_set(g.id, "clan_v2", 1)
    try:
        await assurer_guide_clan(g)
    except discord.HTTPException as ex:
        _log("[ZONES][E6] guide du clan non posé")
        _log(f"[ZONES][E6:DETAIL] {type(ex).__name__} {ex}")
    return faits


def _morceaux(texte: str, n: int = 2000) -> list:
    """Un texte long (Nitro : 4 000 caractères) en messages de 2 000 au plus, coupés à la ligne."""
    out, reste = [], texte or ""
    while len(reste) > n:
        coupe = reste.rfind("\n", 0, n)
        if coupe <= 0:
            coupe = n
        out.append(reste[:coupe])
        reste = reste[coupe:].lstrip("\n")
    if reste:
        out.append(reste)
    return out


async def _recopier(g, source, fil) -> tuple:
    """Les messages de `source`, du plus ancien au plus récent, recopiés dans `fil` : le texte, les
    images et fichiers, les cartes. Reprend où il s'était arrêté (`clan_infos_dernier`). Un message qu'on
    ne sait pas recopier en entier (un panneau de bot, un autocollant, un fichier trop lourd) compte
    comme resté : l'ancien salon ne sera pas supprimé. Rend (recopiés, restés)."""
    c = await _cfg(g.id)
    dernier = int(c.get("clan_infos_dernier", 0) or 0)
    limite = int(getattr(g, "filesize_limit", 0) or 8 * 1024 * 1024)
    copies = restes = 0
    if getattr(fil, "archived", False):
        await fil.edit(archived=False)
    async for m in source.history(limit=INFOS_MAX, oldest_first=True,
                                  after=discord.Object(dernier) if dernier else None):
        if getattr(m, "type", discord.MessageType.default) not in (discord.MessageType.default,
                                                                   discord.MessageType.reply):
            continue  # « X a épinglé un message » : rien à recopier
        texte = (m.content or "").strip()
        embeds = [e for e in (m.embeds or []) if getattr(e, "type", "") == "rich"][:10]
        pieces = list(m.attachments or [])
        a_joindre = [p for p in pieces if int(p.size or 0) <= limite][:10]
        incomplet = bool(getattr(m, "components", None) or getattr(m, "stickers", None)
                         or getattr(m, "poll", None) or len(a_joindre) < len(pieces))
        try:
            fichiers = [await p.to_file() for p in a_joindre]
            morceaux = _morceaux(texte)
            if morceaux or embeds or fichiers:
                for n, morceau in enumerate(morceaux or [None]):
                    envoi = {"content": morceau, "allowed_mentions": discord.AllowedMentions.none()}
                    if n == len(morceaux or [None]) - 1:  # les cartes et les fichiers avec le dernier morceau
                        if embeds:
                            envoi["embeds"] = embeds
                        if fichiers:
                            envoi["files"] = fichiers
                    await fil.send(**envoi)
        except discord.HTTPException as ex:
            restes += 1
            _log("[ZONES][E8] message d'info non recopié")
            _log(f"[ZONES][E8:DETAIL] {m.id} {type(ex).__name__} {ex}")
            continue
        await _db_set(g.id, "clan_infos_dernier", m.id)
        if incomplet:
            restes += 1
        elif texte or embeds or a_joindre:
            copies += 1
    return copies, restes


async def demenager_clan(g, *, deplacer_annonces=None) -> list:
    """Une fois, après `installer_clan` — le choix du fondateur : « les 4 salons actuels sont supprimés :
    le texte d'info-gorp est recopié dans 📢 Infos, l'historique du chat est perdu ». info-gorp est
    recopié (texte, images, liens) ; les annonces déjà publiées passent dans 📣 Annonces avec leurs
    « ✅ Vu » (`deplacer_annonces`) ; les réglages suivent ; puis info, annonces, chat et discussions
    sont supprimés. Une recopie incomplète garde l'ancien salon d'info. Le 🔊 Join ne bouge pas."""
    c = await _cfg(g.id)
    cat = categorie_clan(g)
    posts = c.get("clan_posts") or {}
    if cat is None or not posts or c.get("clan_demenage_v2"):
        return []
    anciens = dict(c.get("clan_anciens") or {})
    garder = {int(c.get("clan_forum_v2", 0) or 0)}
    texte = [ch for ch in cat.channels if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel))
             and ch.id not in garder]
    info = next((ch for ch in texte if "info" in config_salons.normaliser(ch.name).split()), None)
    chat = next((ch for ch in texte if "chat" in config_salons.normaliser(ch.name).split()), None)
    v1_annonces = g.get_channel(int(anciens.get("annonces", 0) or 0))
    v1_forum = g.get_channel(int(anciens.get("forum", 0) or 0))
    faits, garder_info = [], False
    infos = await _resoudre(g, (posts.get("infos") or {}).get("id", 0))
    if isinstance(info, discord.TextChannel) and infos is not None:
        copies, restes = await _recopier(g, info, infos)
        if copies:
            faits.append(f"{copies} message(s) d'info recopié(s) dans 📢 Infos")
        if restes:
            garder_info = True
            faits.append(f"{info.name} gardé : {restes} message(s) pas entièrement recopié(s), à vérifier")
    annonces_post = await _resoudre(g, (posts.get("annonces") or {}).get("id", 0))
    if isinstance(v1_annonces, discord.TextChannel) and annonces_post is not None and deplacer_annonces is not None:
        n = await deplacer_annonces(g, v1_annonces, annonces_post)
        if n:
            faits.append(f"{n} annonce(s) passée(s) dans 📣 Annonces avec leurs « ✅ Vu »")
    paires = {}
    for ancien, cle in ((info, "infos"), (chat, "chat"), (v1_annonces, "annonces"), (v1_forum, "chat")):
        if ancien is not None and (posts.get(cle) or {}).get("id"):
            paires[ancien.id] = int(posts[cle]["id"])
    faits += await _reporter(g, paires, fusion=True)
    partants = [ch for ch in (info if not garder_info else None, v1_annonces, chat, v1_forum) if ch is not None]
    for ch in dict.fromkeys(partants):
        try:
            await ch.delete(reason="Clan GoRP : un seul forum (choix du fondateur)")
            faits.append(f"{ch.name} supprimé")
        except discord.NotFound:
            pass
        except discord.HTTPException as ex:
            _log("[ZONES][E7] ancien salon du clan non supprimé")
            _log(f"[ZONES][E7:DETAIL] {ch.id} {type(ex).__name__} {ex}")
    await _db_set(g.id, "clan_demenage_v2", 1)
    return faits


def vue_guide_clan(g, c: dict, posts: dict) -> tuple:
    """Le guide du clan, en tête de 🦜▷・clan-gorp : chaque post et à quoi il sert, le vocal, à qui
    s'adresser. Une ligne n'apparaît que si son post existe (aucun bouton qui ment). Rend (vue, signature)."""
    vocal = _vocal_clan(g, c)
    ticket = _ticket(g) if _ticket else None

    def lien(cle):
        pid = int((posts.get(cle) or {}).get("id", 0) or 0)
        return Post(pid, f"https://discord.com/channels/{g.id}/{pid}") if pid else None
    lignes = [
        (lien("infos"), "### 📢 Infos · Info\nCe qu'il faut savoir sur le clan : à lire en arrivant.\n-# What to "
         "know about the clan: read it first.", "Lire · Read"),
        (lien("annonces"), "### 📣 Annonces · Announcements\nLes nouvelles du clan. Lis-les et clique « ✅ Vu ».\n-# "
         "Clan news: read them and click “✅ Seen”.", "Lire · Read"),
        (lien("chat"), "### 💬 Chat\nLe chat du clan, entre nous"
         + (f". Le vocal : 🔊 <#{vocal.id}>." if vocal is not None else ".") + "\n-# The clan chat, among us.",
         "Ouvrir · Open"),
        (lien("economie"), "### 💰 Économie · Economy\nLes objectifs, les dons et les dépenses du clan.\n-# Goals, "
         "donations and spending.", "Ouvrir · Open"),
        (lien("trade"), "### 🤝 Trade du clan · Clan trade\nLes échanges entre membres : propose, demande.\n-# Trades "
         "between members: offer, ask.", "Échanger · Trade"),
        (lien("taverne"), "### 🍺 Taverne · Tavern\nOn se pose, on raconte ses aventures en mer.\n-# Sit down and "
         "tell your adventures at sea.", "Entrer · Enter"),
    ]
    items = [visuels.bandeau("clan_guide", "Guide du clan"),
             discord.ui.TextDisplay("🇫🇷 **Bienvenue dans l'équipage.** Tout le clan se retrouve ici : les infos, les "
                                    "annonces, le chat et nos posts — en français ou en anglais. On écrit dans les "
                                    "posts.\n🇬🇧 **Welcome aboard.** The whole clan meets here: info, announcements, "
                                    "chat and our posts — in French or English. Write in the posts.")]
    if _boutons_langue is not None:
        items.append(discord.ui.ActionRow(*_boutons_langue()))
    presentes = [(p, t, b) for p, t, b in lignes if p is not None]
    if presentes:
        items.append(discord.ui.Separator())
        for p, texte, libelle in presentes:
            items.append(discord.ui.Section(discord.ui.TextDisplay(texte),
                                            accessory=discord.ui.Button(label=libelle, url=p.jump_url)))
    items.append(discord.ui.Separator())
    if ticket is not None:
        items.append(discord.ui.Section(
            discord.ui.TextDisplay("### 🎫 Une question, un souci ? · A question?\nOuvre un ticket : le staff du clan "
                                   "te répond en privé.\n-# Open a ticket: the clan staff answers privately."),
            accessory=discord.ui.Button(label="Ticket", url=ticket.jump_url)))
    items.append(discord.ui.TextDisplay("-# 🛡️ Personne du staff ne te demandera ton mot de passe · No staff will ever "
                                        "ask for your password"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(0x14B8A6)))
    signature = "|".join([str(GUIDE_CLAN_VERSION), *(str(p.id) for p, _t, _b in presentes),
                          str(getattr(vocal, "id", 0)), str(getattr(ticket, "id", 0)),
                          str(int(_boutons_langue is not None))])
    return v, signature


async def assurer_guide_clan(g) -> bool:
    """Le message d'ouverture du post 🧭 Guide du clan suit les posts, le vocal et le salon des tickets
    (réécrit seulement quand quelque chose a changé). Rend True s'il a été réécrit."""
    c = await _cfg(g.id)
    posts = c.get("clan_posts") or {}
    info = posts.get("guide") or {}
    if not info.get("id"):
        return False
    vue, signature = vue_guide_clan(g, c, posts)
    if c.get("clan_guide_v") == signature:
        return False
    fil = await _resoudre(g, info["id"])
    if fil is None:
        return False
    if getattr(fil, "archived", False):
        await fil.edit(archived=False)
    await fil.get_partial_message(int(info.get("ouverture") or info["id"])).edit(
        view=vue, allowed_mentions=discord.AllowedMentions.none())
    await _db_set(g.id, "clan_guide_v", signature)
    return True
