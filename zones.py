"""zones.py — les compartiments du serveur (22/10/2026).

Le fondateur, dans la nuit : « je veux une catégorie… tu enlèves tout ce qui est dans Communautaire et
dans Rell Seas… tu crées uniquement un fil qui s'appelle communautaire et un fil qui s'appelle Rell
Seas. Dans le fil communautaire… le chat, médias, tout ce qui est lié au serveur… c'est les salons
dans un fil… dans le fil Rell Seas… trade, crew… et à l'intérieur, dans chacun des fils, tout va être
super bien fait… il n'y a que deux fils… le vocal, tu le laisses tel qu'il est… toutes les
fonctionnalités qui sont liées à ça fonctionnent, et ça cible bien les salons. »

· Communautaire : 💬communautaire et 🌊rell-seas (deux forums), puis 🔊Join, inchangé.
  💬communautaire : ❓ Aide · 💬 Chat · 📸 Médias · 💡 Suggestions · 🚀 Boosts · 🤖 Commandes.
  🌊rell-seas : 🌊 Chat Rell Seas · 🛟 Help · 🤝 Trade · ⚓ Crews.
On écrit dans les posts, on n'en crée pas. Chaque fonction du bot vise son post : l'orientation, les
suggestions, les boosts, l'entraide et le trade (une carte par demande), les équipages (une carte par
équipage). Les anciens salons partent dans « 📦 Archives », cachée aux membres : rien n'est perdu, le
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
import equipages
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
SUJET_RELL = ("🇫🇷 Tout Rell Seas : le chat du jeu, l'entraide, le trade, les équipages. On écrit dans les posts.\n"
              "🇬🇧 All of Rell Seas: the game chat, help, trade, crews. Write in the posts.")
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
    ("crews", "⚓ Crews · Équipages", True, ""),
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

#  La zone du clan GoRP (sa catégorie existe : 📢 info, ✍ chat, 🔊 Join réservé au clan).
CLAN_ANNONCES = "📣▷・annonces-gorp"
CLAN_FORUM = "🧵▷・discussions-gorp"
CLAN_FILS = (
    ("economie", "💰 Économie · Economy",
     "🇫🇷 L'économie du clan : objectifs, dons, dépenses.\n🇬🇧 The clan's economy: goals, donations, spending."),
    ("trade", "🤝 Trade du clan · Clan trade",
     "🇫🇷 Les échanges entre membres du clan : propose, demande.\n🇬🇧 Trades between clan members: offer, ask."),
    ("taverne", "🍺 Taverne · Tavern",
     "🇫🇷 On se pose, on raconte ses aventures en mer.\n🇬🇧 Sit down and tell your adventures at sea."),
)
SUJET_CLAN_ANNONCES = ("🇫🇷 Les annonces du clan GoRP : lis-les, clique « ✅ Vu ».\n"
                       "🇬🇧 GoRP clan announcements: read them, click “✅ Seen”.")
SUJET_CLAN_FORUM = ("🇫🇷 Économie, trade, taverne… et tes propres sujets (bouton « Nouveau post »).\n"
                    "🇬🇧 Economy, trade, tavern… and your own topics (« New post » button).")

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
            "zones_rell", "zones_chat", "zones_vocal", "zones_forum")
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
    if cle == "crews":
        return equipages.vue_panneau()
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
    if int(c.get("eq_forum", 0) or 0) != p["crews"]["id"]:
        await _db_set(g.id, "eq_forum", p["crews"]["id"])
        await _db_set(g.id, "eq_panneau", p["crews"]["ouverture"])
        await _db_set(g.id, "eq_ouverture", p["crews"]["ouverture"])


async def installer(g, *, forum: bool | None = None) -> list:
    """Crée ce qui manque — les deux forums, leurs posts, les rôles de guide —, branche chaque
    fonction sur son post, range ; la première fois, ferme proprement l'ancienne installation (les
    demandes à republier, les équipages devenus cartes) et met ses salons aux archives. Ne supprime
    rien. Rend la liste de ce qui a été fait."""
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
        await equipages.assurer_panneau(g, forcer=True)
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
                         ("zones_forum", "medias"), ("zones_chat", "rell_chat"), ("eq_forum", "crews")):
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


async def _reporter(g, paires: dict) -> list:
    """Les réglages qui visaient un ancien salon le suivent dans son post : liens et images permis,
    l'accueil et l'au revoir. (L'immunité, gardée en base, suit avec `bot._reporter_immunites`.)"""
    await _db_set(g.id, "zones_correspondances", {str(k): v for k, v in paires.items()})
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
    ferment en disant où republier, les équipages deviennent des cartes du post ⚓ Crews, les idées
    encore en vote passent dans le post 💡 Suggestions avec leurs votes."""
    faits = []
    n = await entraide.fermer_anciennes(g, "🔒 L'entraide déménage : republie ta demande dans 🌊rell-seas › 🛟 Help."
                                           " · Moved: post again in 🌊rell-seas › 🛟 Help.")
    if n:
        faits.append(f"{n} ancienne(s) demande(s) fermée(s)")
    n = await equipages.demenager(g)
    if n:
        faits.append(f"{n} équipage(s) passé(s) en cartes")
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
    """Toutes les 30 minutes : les posts (et les fils du clan) restent ouverts ; un post qui doit
    rester verrouillé l'est. Jamais l'inverse : un post que le staff a verrouillé le reste. Le guide
    de Rell Seas suit les posts et les rôles."""
    try:
        await assurer_guide(g)
    except discord.HTTPException as ex:
        _log(f"[ZONES:DETAIL] guide {type(ex).__name__} {ex}")
    cfz, c = await conf(g), await _cfg(g.id)
    verrous = {cle for cle, _t, v, _x in POSTS_COMMU + POSTS_RELL if v}
    a_suivre = [(cle, info.get("id", 0)) for cle, info in cfz["posts"].items()]
    a_suivre += list(dict(c.get("clan_fils") or {}).items())
    for cle, fid in a_suivre:
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
        if cle in verrous and cle in cfz["posts"] and not getattr(fil, "locked", False):
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
        (post(g, cfz, "crews"), "### ⚓ Équipages · Crews\nPirates ou Marine : publie ton équipage, recrute, ou clique "
         "« Rejoindre » sur une carte — le capitaine est prévenu.\n-# Post your crew or join one: the captain is "
         "notified.", "Équipages · Crews"),
    ]
    items = [visuels.bandeau("rs_guide", "Guide Rell Seas"),
             discord.ui.TextDisplay("🇫🇷 **Bienvenue à bord.** Ici, tout se passe dans les posts de ce forum : on "
                                    "discute, on s'entraide, on échange, on monte son équipage — en français ou en "
                                    "anglais.\n🇬🇧 **Welcome aboard.** Everything happens in this forum's posts: chat, "
                                    "help each other, trade, build your crew — in French or English.")]
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
            (post(g, cfz, "crews"), "⚓ **Crews** — Pirates ou Marine : publie ou rejoins · post or join",
             "Équipages · Crews"),
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  La zone du clan GoRP
# ═══════════════════════════════════════════════════════════════════════════════

async def _fils_prets(g, ch, existants: dict, definitions) -> tuple:
    """Les fils déjà ouverts d'un forum (ou, hors forum, d'un salon) : créés s'ils manquent,
    réveillés s'ils dorment. Rend (les fils, ce qui a été créé)."""
    fils, faits = dict(existants or {}), []
    for cle, titre, texte in definitions:
        fil = g.get_channel_or_thread(int(fils.get(cle, 0) or 0))
        if fil is None and fils.get(cle):
            try:
                fil = await g.fetch_channel(int(fils[cle]))
            except discord.NotFound:
                fil = None
        if fil is not None:
            if getattr(fil, "archived", False):
                try:
                    await fil.edit(archived=False)
                except discord.HTTPException as ex:
                    _log(f"[ZONES:DETAIL] réveil du fil {cle} {ex}")
            continue
        if isinstance(ch, discord.ForumChannel):
            fil = (await ch.create_thread(name=titre, content=texte, reason="Fil prêt à l'emploi")).thread
        else:
            msg = await ch.send(f"**{titre}**\n{texte}")
            fil = await msg.create_thread(name=titre, auto_archive_duration=10080, reason="Fil prêt à l'emploi")
        fils[cle] = fil.id
        faits.append(f"fil {titre}")
    return fils, faits


def categorie_clan(g):
    """La catégorie du clan (« 🦜 · GoRp_SEA »), même règle que `config_salons.est_clan`."""
    return next((cat for cat in getattr(g, "categories", []) or [] if config_salons.est_clan(cat.name)), None)


async def installer_clan(g, role, equipe=(), *, forum: bool | None = None) -> list:
    """22/10/2026 : « retape la zone GoRP… un salon des annonces du clan, automatisé, propre…
    économie, trade propre au clan, discussion, taverne… le vocal propre à eux ». Dans la catégorie
    du clan : 📣 annonces (lecture seule : l'annonce en un clic, la bienvenue des arrivées) et
    🧵 discussions (forum : économie, trade du clan, taverne déjà ouverts ; chacun ouvre ses sujets).
    Le Join du clan existe déjà. Réservé au rôle du clan et au staff ; rien n'est supprimé."""
    cat = categorie_clan(g)
    if cat is None or role is None:
        return []
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    c = await _cfg(g.id)
    faits = []

    def droits(ouvert: discord.PermissionOverwrite) -> dict:
        ows = {g.default_role: discord.PermissionOverwrite(view_channel=False), role: ouvert, g.me: BOT}
        for r in equipe or ():
            if r is not None and r != role:
                ows[r] = EQUIPE_CLAN
        return ows

    annonces = g.get_channel(int(c.get("clan_annonces", 0) or 0))
    if annonces is None:
        annonces = await g.create_text_channel(CLAN_ANNONCES, category=cat, topic=SUJET_CLAN_ANNONCES,
                                               overwrites=droits(LECTURE_CLAN), reason="Clan GoRP : ses annonces")
        await _db_set(g.id, "clan_annonces", annonces.id)
        faits.append(f"salon {annonces.name}")
    discussions = g.get_channel(int(c.get("clan_forum", 0) or 0))
    if discussions is None:
        if forum:
            discussions = await g.create_forum(CLAN_FORUM, category=cat, topic=SUJET_CLAN_FORUM,
                                               overwrites=droits(PAROLE), default_auto_archive_duration=10080,
                                               default_layout=discord.ForumLayoutType.list_view,
                                               default_sort_order=discord.ForumOrderType.latest_activity,
                                               reason="Clan GoRP : des fils plutôt que des salons")
        else:
            discussions = await g.create_text_channel(CLAN_FORUM, category=cat, topic=SUJET_CLAN_FORUM[:1024],
                                                      overwrites=droits(PAROLE),
                                                      reason="Clan GoRP : des fils plutôt que des salons")
        await _db_set(g.id, "clan_forum", discussions.id)
        faits.append(f"salon {discussions.name}")
    fils, f2 = await _fils_prets(g, discussions, c.get("clan_fils") or {}, CLAN_FILS)
    await _db_set(g.id, "clan_fils", fils)
    faits += f2
    texte = [ch for ch in cat.channels if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel))]
    info = next((ch for ch in texte if "info" in config_salons.normaliser(ch.name).split()), None)
    chat = next((ch for ch in texte if "chat" in config_salons.normaliser(ch.name).split()), None)
    try:
        await _ranger(cat, [info, _dans(annonces, cat), chat, _dans(discussions, cat)])
    except discord.HTTPException as ex:
        _log("[ZONES][E2] zone du clan non rangée")
        _log(f"[ZONES][E2:DETAIL] {type(ex).__name__} {ex}")
    await _db_set(g.id, "clan_v1", 1)
    return faits
