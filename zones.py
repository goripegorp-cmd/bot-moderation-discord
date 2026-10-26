"""zones.py — les compartiments du serveur (22/10/2026, refaits le 24/10/2026).

Le 24/10, le fondateur : « refais tout l'onglet communautaire… avec des salons simples… un salon
discussion, média, et après, tous les autres salons… Boost, Suggestion… en dehors… tu as créé un forum
pour Rell Seas, avec le système d'entraide, échange, discussion, un guide… tu vas faire la même chose
pour un nouveau jeu qui va s'appeler Clover RPG. »

· Communautaire :
  ❓aide · 💬discussion · 📸médias · 💡suggestions · 🚀boosts · 🤖commandes — des salons simples ;
  🌊rell-seas (forum) : 🧭 Guide · 🌊 Chat Rell Seas · 🛟 Help · 🤝 Trade ;
  🍀clover-rpg (forum) : 🧭 Guide · 🍀 Chat Clover RPG · 🛟 Help · 🤝 Trade ;
  🔊Join, inchangé.
Dans les forums des jeux, on écrit dans les posts, on n'en crée pas ; l'entraide et le trade de chaque
jeu y vivent en cartes. Chaque fonction du bot vise son salon ou son post. Un nouveau jeu = une entrée
de `JEUX` (et ses types dans `entraide.ZONES`). Jamais d'archives : l'ancien forum 💬communautaire est
supprimé (choix du fondateur, 24/10) ; ses idées en vote passent dans 💡suggestions avec leurs votes.

La zone du clan GoRP (sa catégorie existe) : un forum, voir `installer_clan`.
"""
from __future__ import annotations

import asyncio
from collections import namedtuple
from dataclasses import dataclass

import discord

import zlib

import boosts
import config_salons
import entraide
import suggestions
import textes as textes_du_site
import visuels
from ui_v2 import LayoutView

FORUM_COMMU = "💬communautaire"   # le forum du 22/10, supprimé au passage en salons simples (24/10)
FORUM_RELL = "🌊rell-seas"
FORUM_CLOVER = "🍀clover-rpg"
CATEGORIE = "· Communautaire"
ARCHIVES = "📦 Archives"
SUJET_RELL = ("🇫🇷 Tout Rell Seas : le guide, le chat du jeu, l'entraide, le trade. On écrit dans les posts.\n"
              "🇬🇧 All of Rell Seas: the guide, the game chat, help, trade. Write in the posts.")
SUJET_CLOVER = ("🇫🇷 Tout Clover RPG : le guide, le chat du jeu, l'entraide, le trade. On écrit dans les posts.\n"
                "🇬🇧 All of Clover RPG: the guide, the game chat, help, trade. Write in the posts.")
#  Communautaire, en salons simples : (clé, nom, les membres y écrivent, sujet).
SALONS_COMMU = (
    ("aide", "❓aide", False,
     "🇫🇷 Par où commencer : le serveur, Rell Seas, Clover RPG, les tickets.\n"
     "🇬🇧 Where to start: the server, Rell Seas, Clover RPG, tickets."),
    ("discussion", "💬discussion", True,
     "🇫🇷 Discute de tout, en français ou en anglais. Bienvenue !\n🇬🇧 Talk about anything, in French or English. "
     "Welcome!"),
    ("medias", "📸médias", True,
     "🇫🇷 Partage ici tes captures, clips et vidéos.\n🇬🇧 Share your screenshots, clips and videos here."),
    ("suggestions", "💡suggestions", False,
     "🇫🇷 Une idée pour le serveur ? Le bouton en bas : tout le monde vote, le staff répond.\n"
     "🇬🇧 An idea for the server? The button below: everyone votes, the staff answers."),
    ("boosts", "🚀boosts", False,
     "🇫🇷 Merci à celles et ceux qui boostent le serveur 💜\n🇬🇧 Thanks to everyone who boosts the server 💜"),
    ("commandes", "🤖commandes", True,
     "🇫🇷 Les commandes des bots, c'est ici : la discussion reste lisible.\n"
     "🇬🇧 Use the bots' commands here: the chat stays readable."),
)
#  L'ancien forum 💬communautaire : chaque post → son salon (ce qui visait l'un vise l'autre).
POSTS_VERS_SALONS = {"aide": "aide", "chat": "discussion", "medias": "medias", "suggestions": "suggestions",
                     "boosts": "boosts", "commandes": "commandes"}
#  Les posts des forums des jeux, dans l'ordre d'affichage : (clé, titre, verrouillé, texte d'ouverture —
#  vide : la fonction qui l'habite donne le sien). Verrouillé : on y clique, on n'y écrit pas.
POSTS_RELL = (
    ("guide", "🧭 Guide · Rell Seas", True, ""),
    ("rell_chat", "🌊 Chat Rell Seas", False,
     "🇫🇷 Le chat de Rell Seas : îles, fruits, mises à jour, astuces.\n🇬🇧 The Rell Seas chat: islands, fruits, "
     "updates, tips."),
    ("help", "🛟 Help · Entraide", False, ""),
    ("trade", "🤝 Trade · Échanges", False, ""),
)
POSTS_CLOVER = (
    ("cl_guide", "🧭 Guide · Clover RPG", True, ""),
    ("cl_chat", "🍀 Chat Clover RPG", False,
     "🇫🇷 Le chat de Clover RPG : quêtes, objets, mises à jour, astuces.\n🇬🇧 The Clover RPG chat: quests, items, "
     "updates, tips."),
    ("cl_help", "🛟 Help · Entraide", False, ""),
    ("cl_trade", "🤝 Trade · Échanges", False, ""),
)
#  Dans les forums des jeux : on lit, on écrit dans les posts, on montre (images, liens), on réagit, on
#  utilise les commandes — mais on n'ouvre pas de nouveau post.
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
#  Les salons simples où l'on n'écrit pas (❓aide, 💡suggestions, 🚀boosts) : on lit, on clique.
LECTURE_COMMU = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False,
                                            add_reactions=False, create_public_threads=False,
                                            create_private_threads=False, send_messages_in_threads=False,
                                            use_application_commands=True)
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
GUIDE_TEXTE_APRES_S = 5.0   # un texte du guide changé sur le site : le guide réécrit après une rafale de changements

#  26/10/2026 — le guide du clan, réécrit par la direction (Capitainerie → Textes & noms, registre `textes.py`) : chaque
#  texte et chaque bouton ; le texte d'origine reste ici. Un texte changé réécrit le guide (`quand_change("guide.")`).
_declarer = textes_du_site.declarer
_HAUT, _POSTS, _BAS = "Le haut du guide", "Les posts du clan", "Le bas du guide"
_declarer("guide.bienvenue",
          "🇫🇷 **Bienvenue dans l'équipage.** Tout le clan se retrouve ici : les infos, les annonces, le chat et nos "
          "posts — en français ou en anglais. On écrit dans les posts.\n🇬🇧 **Welcome aboard.** The whole clan meets "
          "here: info, announcements, chat and our posts — in French or English. Write in the posts.",
          groupe="guide", titre="L'accueil", partie=_HAUT, ordre=1, max_=1200,
          aide="En tête du guide du clan (le post 🧭 Guide du clan), sous l'image.")
#  (clé du post, texte d'origine, bouton d'origine, ce qu'il présente)
GUIDE_POSTS = (
    ("infos", "### 📢 Infos · Info\nCe qu'il faut savoir sur le clan : à lire en arrivant.\n-# What to know about the "
              "clan: read it first.", "Lire · Read", "Le post 📢 Infos"),
    ("annonces", "### 📣 Annonces · Announcements\nLes nouvelles du clan. Lis-les et clique « ✅ Vu ».\n-# Clan news: "
                 "read them and click “✅ Seen”.", "Lire · Read", "Le post 📣 Annonces"),
    ("chat", "### 💬 Chat\nLe chat du clan, entre nous{salons}.\n-# The clan chat, among us.", "Ouvrir · Open",
     "Le post 💬 Chat"),
    ("economie", "### 💰 Économie · Economy\nLes objectifs, les dons et les dépenses du clan.\n-# Goals, donations and "
                 "spending.", "Ouvrir · Open", "Le post 💰 Économie"),
    ("trade", "### 🤝 Trade du clan · Clan trade\nLes échanges entre membres : propose, demande.\n-# Trades between "
              "members: offer, ask.", "Échanger · Trade", "Le post 🤝 Trade du clan"),
    ("taverne", "### 🍺 Taverne · Tavern\nOn se pose, on raconte ses aventures en mer.\n-# Sit down and tell your "
                "adventures at sea.", "Entrer · Enter", "Le post 🍺 Taverne"),
)
for _k, (_post, _texte, _bouton, _nom) in enumerate(GUIDE_POSTS):
    _declarer(f"guide.{_post}.texte", _texte, groupe="guide", titre=_nom, partie=_POSTS, ordre=10 + 2 * _k, max_=800,
              aide="Sa ligne dans le guide (elle n'apparaît que si le post existe).",
              variables=(("salons", "le vocal et le salon des demandes, quand ils existent (« . Le vocal : 🔊 "
                                    "#vocal · une demande… »)"),) if _post == "chat" else ())
    _declarer(f"guide.{_post}.bouton", _bouton, groupe="guide", titre=f"{_nom} · le bouton", partie=_POSTS,
              ordre=11 + 2 * _k, max_=80, lignes=False, aide="Le bouton à droite de la ligne : il ouvre le post.")
_declarer("guide.chat.vocal", "Le vocal : 🔊 {salon}", groupe="guide", titre="Le post 💬 Chat · le vocal", partie=_POSTS,
          ordre=30, max_=200, lignes=False, variables=(("salon", "le salon vocal du clan"),),
          aide="Ajouté à la ligne du chat quand le clan a un vocal.")
_declarer("guide.chat.demande", "une demande (aide, farm, boss…) : 🙋 {salon}", groupe="guide",
          titre="Le post 💬 Chat · les demandes", partie=_POSTS, ordre=31, max_=200, lignes=False,
          variables=(("salon", "le salon des demandes"),), aide="Ajouté à la ligne du chat quand ce salon existe.")
_declarer("guide.ticket.texte", "### 🎫 Une question, un souci ? · A question?\nOuvre un ticket : le staff du clan te "
          "répond en privé.\n-# Open a ticket: the clan staff answers privately.", groupe="guide",
          titre="Les tickets", partie=_BAS, ordre=40, max_=800, aide="Vers la fin du guide, avec le bouton du salon "
                                                                        "des tickets.")
_declarer("guide.ticket.bouton", "Ticket", groupe="guide", titre="Les tickets · le bouton", partie=_BAS, ordre=41,
          max_=80, lignes=False, aide="Il ouvre le salon des tickets.")
_declarer("guide.securite", "-# 🛡️ Personne du staff ne te demandera ton mot de passe · No staff will ever ask for your "
          "password", groupe="guide", titre="La mise en garde", partie=_BAS, ordre=42, max_=300,
          aide="La dernière ligne du guide.")


def _t(guild_id, cle: str, **valeurs) -> str:
    """Un texte du guide du clan (Textes & noms) : celui du serveur, sinon celui d'origine."""
    return textes_du_site.texte_cache(guild_id, cle, **valeurs)

#  Un post, même endormi (hors mémoire) : son identifiant et son lien suffisent au panneau ❓ aide.
Post = namedtuple("Post", "id jump_url")
GUIDE_VERSION = 1


@dataclass(frozen=True)
class Jeu:
    """Un jeu du serveur : son forum, ses posts, ses types d'entraide, son guide — et les mots qui le
    désignent (les réponses toutes faites). Un nouveau jeu = une entrée ici (+ ses types d'entraide)."""
    cle: str
    nom: str
    emoji: str
    forum: str
    cle_forum: str
    sujet: str
    posts: tuple
    guide: str              # les clés de ses posts
    chat: str
    help: str
    trade: str
    entraide: str           # ses conteneurs dans l'entraide (`rs_salons`)
    echange: str
    zones: tuple            # ses types dont les rôles certifient : aide, boss, farm, puis le trade
    bandeau: str
    couleur: int
    cle_guide_v: str
    chat_fr: str
    chat_en: str
    accueil_fr: str
    accueil_en: str
    mots: tuple = ()        # comment les membres l'écrivent
    clan: bool = False      # son guide présente le clan GoRP


JEUX = (
    Jeu("rell", "Rell Seas", "🌊", FORUM_RELL, "zones_forum_rell", SUJET_RELL, POSTS_RELL, "guide", "rell_chat",
        "help", "trade", "entraide", "trade", ("aide", "boss", "farm", "trade"), "rs_guide", 0x06B6D4,
        "zones_guide_v", "Le chat du jeu : îles, fruits, mises à jour, astuces",
        "The game chat: islands, fruits, updates, tips.", "**Bienvenue à bord.**", "**Welcome aboard.**",
        mots=("rell", "rellseas", "reelsy", "realsy", "rilsi", "rils"), clan=True),
    Jeu("clover", "Clover RPG", "🍀", FORUM_CLOVER, "zones_forum_clover", SUJET_CLOVER, POSTS_CLOVER, "cl_guide",
        "cl_chat", "cl_help", "cl_trade", "cl_entraide", "cl_trade", ("cl_aide", "cl_boss", "cl_farm", "cl_trade"),
        "cl_guide", 0x22C55E, "zones_guide_v_clover", "Le chat du jeu : quêtes, objets, mises à jour, astuces",
        "The game chat: quests, items, updates, tips.", "**Bienvenue sur Clover RPG.**",
        "**Welcome to Clover RPG.**", mots=("clover", "cloverrpg")),
)

_cfg = _db_set = _lecteurs = _ticket = _boutons_langue = None
_log = print
_verrous: dict = {}
#  25/10/2026 : « Choisis ton métier · Pick your job » dans le guide du clan (`metiers.section_guide`, branché par
#  `brancher_metiers`) — async (g, c) → (composants, signature) ou None.
_section_metiers = None
#  26/10/2026 : « Le site de l'équipage » dans le guide du clan (`site_equipage.section_guide`, branché par
#  `brancher_site_equipage`) — async (g, c) → (composants, signature) ou None.
_section_site = None


def setup(*, cfg, db_set, lecteurs=None, ticket=None, boutons_langue=None, log=None):
    """`lecteurs(g, c)` → les rôles qui voient « 📦 Archives » (la direction et au-dessus) ;
    `ticket(g)` → le salon des tickets ; `boutons_langue()` → les boutons 🇫🇷 / 🇬🇧 du bot."""
    global _cfg, _db_set, _lecteurs, _ticket, _boutons_langue, _log, _section_metiers, _section_site
    _cfg, _db_set, _lecteurs, _ticket, _boutons_langue = cfg, db_set, lecteurs, ticket, boutons_langue
    _log = log or print
    _section_metiers = None         # rebranché par l'étape des métiers (après celle-ci au démarrage)
    _section_site = None            # rebranché par l'étape du site de l'équipage (après celle-ci au démarrage)


def brancher_metiers(fn) -> None:
    """Le choix du métier dans le guide du clan (`metiers.section_guide`) ; None le retire."""
    global _section_metiers
    _section_metiers = fn


def brancher_site_equipage(fn) -> None:
    """« Le site de l'équipage » dans le guide du clan (`site_equipage.section_guide`) ; None le retire."""
    global _section_site
    _section_site = fn


def _verrou(gid):
    return _verrous.setdefault(gid, asyncio.Lock())


def communautaire(g):
    return entraide.categorie_communautaire(g)


async def conf(g) -> dict:
    c = await _cfg(g.id)
    return {"forums": {"commu": int(c.get("zones_forum_commu", 0) or 0),
                       **{j.cle: int(c.get(j.cle_forum, 0) or 0) for j in JEUX}},
            "posts": {k: dict(v) for k, v in (c.get("zones_posts") or {}).items()},
            "salons": {k: int(v) for k, v in (c.get("zones_salons") or {}).items() if str(v).isdigit()},
            "archives": [int(x) for x in c.get("zones_archives") or []],
            "categorie_archives": int(c.get("zones_categorie_archives", 0) or 0),
            "actif": bool(c.get("zones_v2"))}


def ids_salons(c: dict) -> set:
    """Les salons des zones (et ce qui a été rangé aux archives) : aucun réglage de masse n'y touche."""
    cles = ("zones_forum_commu", "zones_categorie_archives", "clan_annonces", "clan_forum", "clan_forum_v2",
            "zones_rell", "zones_chat", "zones_vocal", "zones_forum") + tuple(j.cle_forum for j in JEUX)
    ids = {int(c.get(k, 0) or 0) for k in cles} | {int(x) for x in c.get("zones_archives") or []}
    ids |= {int(v) for v in (c.get("zones_salons") or {}).values() if str(v).isdigit()}
    return {i for i in ids if i} | entraide.ids_salons(c) | ({int(c["eq_forum"])} if c.get("eq_forum") else set())


def salon_commu(g, cfz: dict, cle: str):
    """Un salon simple de Communautaire (❓aide, 💬discussion…), s'il existe encore."""
    ch = g.get_channel(int(cfz["salons"].get(cle, 0) or 0))
    return ch if isinstance(ch, discord.TextChannel) else None


def lien_salon(g, ch):
    """Un salon, pour un bouton : son identifiant et son lien (None s'il n'existe pas)."""
    return Post(ch.id, f"https://discord.com/channels/{g.id}/{ch.id}") if ch is not None else None


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
    if cle == "aide" or any(cle == j.guide for j in JEUX):
        return _vue_texte(titre, "🇫🇷 Le guide arrive…\n🇬🇧 The guide is on its way…")
    if cle == "suggestions":
        return suggestions.vue_panneau(await suggestions.ouvertes(g))
    if cle == "boosts":
        return boosts.vue_entete(g)
    for j in JEUX:
        if cle in (j.help, j.trade):
            return entraide.vue_panneau(j.entraide if cle == j.help else j.echange, await entraide.conf(g), g)
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


def _droits_commu(g, parole: bool) -> dict:
    return {g.default_role: PAROLE if parole else LECTURE_COMMU, g.me: BOT}


async def _salons_commu(g, cat, cfz: dict, faits: list) -> dict:
    """Les salons simples de Communautaire : créés s'ils manquent — repris s'ils existent déjà sous ce nom
    dans la catégorie. Rend {clé: identifiant}."""
    salons = dict(cfz["salons"])
    for cle, nom, parole, sujet in SALONS_COMMU:
        if isinstance(g.get_channel(int(salons.get(cle, 0) or 0)), discord.TextChannel):
            continue
        voulu = config_salons.normaliser(nom).split()
        ch = next((s for s in getattr(cat, "channels", []) or []
                   if isinstance(s, discord.TextChannel) and config_salons.normaliser(s.name).split() == voulu), None)
        if ch is None:
            ch = await g.create_text_channel(nom, category=cat, topic=sujet[:1024], overwrites=_droits_commu(g, parole),
                                             reason="Communautaire en salons simples")
            faits.append(f"salon {ch.name}")
        salons[cle] = ch.id
    await _db_set(g.id, "zones_salons", salons)
    return salons


async def _brancher(g, posts: dict, salons: dict) -> None:
    """« Ça cible bien les salons » : chaque fonction du bot vise son salon (Communautaire) ou son post
    (l'entraide et le trade de chaque jeu). Un panneau qui change de salon y est reposé."""
    c = await _cfg(g.id)
    if salons.get("aide") and int(c.get("aide_salon", 0) or 0) != salons["aide"]:
        await _db_set(g.id, "aide_salon", salons["aide"])
        await _db_set(g.id, "aide_message", 0)
        await _db_set(g.id, "aide_message_v", "")
    if salons.get("suggestions") and int(c.get("suggestions_salon", 0) or 0) != salons["suggestions"]:
        await _db_set(g.id, "suggestions_salon", salons["suggestions"])
        await _db_set(g.id, "suggestions_panneau", 0)
    if salons.get("boosts") and int(c.get("boosts_salon", 0) or 0) != salons["boosts"]:
        await _db_set(g.id, "boosts_salon", salons["boosts"])
        await _db_set(g.id, "boosts_entete", 0)
        await _db_set(g.id, "boosts_entete_v", "")
    voulus, ouvertures = {}, {}
    for j in JEUX:
        for cle_post, conteneur in ((j.help, j.entraide), (j.trade, j.echange)):
            if cle_post in posts:
                voulus[conteneur] = int(posts[cle_post]["id"])
                ouvertures[conteneur] = int(posts[cle_post]["ouverture"])
    avant = {k: int(v) for k, v in dict(c.get("rs_salons") or {}).items() if str(v).isdigit()}
    if avant != voulus:
        panneaux, ouv = dict(c.get("rs_panneaux") or {}), dict(c.get("rs_ouvertures") or {})
        for k, v in voulus.items():
            if avant.get(k) != v:  # seul ce qui change repart de son message d'ouverture
                panneaux[k] = ouv[k] = ouvertures[k]
        await _db_set(g.id, "rs_salons", voulus)
        await _db_set(g.id, "rs_panneaux", panneaux)
        await _db_set(g.id, "rs_ouvertures", ouv)


async def installer(g, *, forum: bool | None = None) -> list:
    """Crée ce qui manque — les salons simples de Communautaire, un forum par jeu et ses posts, les rôles
    de guide —, branche chaque fonction sur son salon ou son post, range. La première fois après les deux
    forums (22/10), l'ancien forum 💬communautaire passe en salons (`_passer_en_salons`). Rend ce qui a
    été fait."""
    p = getattr(g.me, "guild_permissions", None)
    if not (p and p.manage_channels and p.manage_roles):
        raise PermissionError("Il me faut « Gérer les salons » et « Gérer les rôles ».")
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    faits = []
    async with _verrou(g.id):
        cat = communautaire(g) or await entraide.categorie_cible(g)
        if cat is None:
            cat = await g.create_category(CATEGORIE, reason="Communautaire")
            faits.append(f"catégorie {cat.name}")
        faits += await entraide.installer(g, forum=forum, creer_salons=False)
        cfz = await conf(g)
        salons = await _salons_commu(g, cat, cfz, faits)
        posts = cfz["posts"]
        for j in JEUX:
            porteur = await _forum(g, cat, j.forum, j.sujet, j.cle_forum, forum, faits)
            await _posts(g, porteur, j.posts, posts, faits)
        await _db_set(g.id, "zones_posts", posts)
        avant = dict(await _cfg(g.id))
        await _brancher(g, posts, salons)
        if not avant.get("zones_demenage"):
            await _db_set(g.id, "zones_demenage", 1)
            faits += await _reporter(g, _correspondances(avant, posts, cat, salons))
            faits += await _demenager(g, avant)
        if not avant.get("zones_salons_v3"):
            await _db_set(g.id, "zones_salons_v3", 1)
            faits += await _passer_en_salons(g, avant, salons)
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
        await suggestions.assurer_panneau(g)
        await boosts.synchroniser(g)
    except discord.HTTPException as ex:
        _log(f"[ZONES:DETAIL] suggestions ou boosts {type(ex).__name__} {ex}")
    return faits


def _correspondances(avant: dict, posts: dict, commu, salons: dict) -> dict:
    """Ancien salon → son nouveau salon ou post (🧵discussions → 📸médias, 🛟help → 🛟 Help…) : ce qui
    visait l'un suivra l'autre."""
    paires = {}

    def lier(ancien, nouveau):
        ancien, nouveau = int(ancien or 0), int(nouveau or 0)
        if ancien and nouveau and ancien != nouveau:
            paires[ancien] = nouveau
    lier(avant.get("zones_forum"), salons.get("medias"))
    lier(avant.get("zones_chat"), (posts.get("rell_chat") or {}).get("id"))
    rs = dict(avant.get("rs_salons") or {})
    lier(rs.get("entraide"), (posts.get("help") or {}).get("id"))
    lier(rs.get("trade"), (posts.get("trade") or {}).get("id"))
    if commu is not None:
        chat = next((ch for ch in commu.channels if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel))
                     and "chat" in config_salons.normaliser(ch.name).split()), None)
        if chat is not None:
            lier(chat.id, salons.get("discussion"))
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

async def _passer_en_salons(g, avant: dict, salons: dict) -> list:
    """24/10/2026 — l'ancien forum 💬communautaire : chaque post a désormais son salon. Les réglages qui
    visaient un post visent son salon (liens et images permis, accueil, immunités), les idées en vote
    passent dans 💡suggestions avec leurs votes, puis le forum est supprimé : « Le supprimer », choisi par
    le fondateur. Les posts des jeux ne bougent pas."""
    faits = []
    anciens = dict(avant.get("zones_posts") or {})
    paires = {}
    for cle_post, cle_salon in POSTS_VERS_SALONS.items():
        pid = int((anciens.get(cle_post) or {}).get("id", 0) or 0)
        if pid and salons.get(cle_salon):
            paires[pid] = int(salons[cle_salon])
    if paires:
        faits += await _reporter(g, paires, fusion=True)
    idees = int((anciens.get("suggestions") or {}).get("id", 0) or 0)
    if idees:
        n = await suggestions.demenager(g, idees)
        if n:
            faits.append(f"{n} idée(s) en vote passée(s) dans 💡suggestions avec leurs votes")
    c = await _cfg(g.id)
    await _db_set(g.id, "zones_posts", {k: v for k, v in (c.get("zones_posts") or {}).items()
                                        if k not in POSTS_VERS_SALONS})
    try:
        vieux = await _resoudre(g, avant.get("zones_forum_commu", 0))
        if vieux is not None:
            await vieux.delete(reason="Communautaire en salons simples (choix du fondateur)")
            faits.append(f"{vieux.name} supprimé")
    except discord.HTTPException as ex:
        _log("[ZONES][E9] ancien forum non supprimé")
        _log(f"[ZONES][E9:DETAIL] {type(ex).__name__} {ex}")
        return faits
    await _db_set(g.id, "zones_forum_commu", 0)
    return faits


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
    """Communautaire : les salons simples, puis les forums des jeux, puis le vocal."""
    cfz, commu = await conf(g), communautaire(g)
    if commu is None:
        return False
    voulu = [_dans(g.get_channel(int(cfz["salons"].get(cle, 0) or 0)), commu) for cle, *_r in SALONS_COMMU]
    voulu += [_dans(g.get_channel(int(cfz["forums"].get(j.cle, 0) or 0)), commu) for j in JEUX]
    return await _ranger(commu, voulu)


async def entretenir(g) -> None:
    """Toutes les 30 minutes : les posts (des deux forums et du forum du clan) restent ouverts ; un post
    qui doit rester verrouillé l'est. Jamais l'inverse : un post que le staff a verrouillé le reste. Un post
    supprimé sort de la configuration (24/10/2026, revue : les guides gardaient un bouton vers un post disparu).
    Puis les deux guides suivent les posts et les rôles."""
    cfz, c = await conf(g), await _cfg(g.id)
    verrous = {cle for j in JEUX for cle, _t, v, _x in j.posts if v}
    verrous_clan = {cle for cle, _t, v, _x in CLAN_POSTS if v}
    a_suivre = [(cle, info.get("id", 0), cle in verrous) for cle, info in cfz["posts"].items()]
    a_suivre += [(f"clan {cle}", (info or {}).get("id", 0), cle in verrous_clan)
                 for cle, info in dict(c.get("clan_posts") or {}).items()]
    disparus = []
    for cle, fid, verrou in a_suivre:
        try:
            fil = await _resoudre(g, fid)
        except discord.HTTPException as ex:
            _log(f"[ZONES:DETAIL] lecture du fil {cle} {ex}")
            continue
        if fil is None:
            if int(fid or 0):
                disparus.append(cle)
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
    if disparus:
        await _oublier_posts(g, c, disparus)
    for guide in (assurer_guide, assurer_guide_clan):
        try:
            await guide(g)
        except discord.HTTPException as ex:
            _log(f"[ZONES:DETAIL] guide {type(ex).__name__} {ex}")


async def _oublier_posts(g, c: dict, cles: list) -> None:
    """Les posts supprimés quittent la configuration : plus aucun bouton n'y mène (les guides, ❓aide, la FAQ)."""
    posts = {k: dict(v) for k, v in (c.get("zones_posts") or {}).items()}
    clan = dict(c.get("clan_posts") or {})
    for cle in cles:
        if cle.startswith("clan "):
            clan.pop(cle[5:], None)
        else:
            posts.pop(cle, None)
    await _db_set(g.id, "zones_posts", posts)
    await _db_set(g.id, "clan_posts", clan)
    _log("[ZONES][E7] post supprimé : retiré des guides")
    _log(f"[ZONES][E7:DETAIL] serveur={g.id} posts={', '.join(cles)}")


def lien_jouer(g, c: dict, j: Jeu):
    """« Jouer » : le lien officiel du jeu s'il est réglé (🎮 Liens des jeux), sinon le salon 🎮game-link ;
    None si aucun des deux (aucun bouton qui ment)."""
    lien = str(dict(c.get("jeux_liens") or {}).get(j.cle) or "")
    if lien.startswith("https://"):
        return Post(0, lien)
    ch = g.get_channel(int(c.get("game_link_salon", 0) or 0))
    return lien_salon(g, ch) if isinstance(ch, discord.TextChannel) else None


def _hubs(g, c: dict, clan: bool) -> list:
    """Les « Join » qui existent, avec leur contexte (vocaux.py), dans la catégorie du clan ou hors d'elle."""
    hubs = (c.get("temp_voice_config") or {}).get("hubs") or {}
    out = []
    for k, v in hubs.items():
        ch = g.get_channel(int(k)) if str(k).isdigit() else None
        if ch is not None and config_salons.est_clan(getattr(getattr(ch, "category", None), "name", "")) == clan:
            out.append((ch, str((v or {}).get("contexte") or ("clan" if clan else "commu"))))
    return out


def _vocal_commu(g, c: dict, contexte: str = "commu"):
    """Le 🔊 Join de la communauté (pas celui du clan) ; pour un jeu, son Join à lui s'il existe."""
    hubs = _hubs(g, c, False)
    return (next((ch for ch, x in hubs if x == contexte), None) or next((ch for ch, x in hubs if x == "commu"), None)
            or next((ch for ch, _x in hubs), None))


def vue_guide(g, c: dict, cfz: dict, cfe: dict, j: Jeu | None = None) -> tuple:
    """« Un fil ultra professionnel » : le guide d'un jeu, en tête de son forum. Chaque post, comment il
    marche, qui certifie, le clan ou le staff ; un bouton par post (jamais un bouton qui ment : une ligne
    n'apparaît que si son post existe). Rend (la vue, sa signature)."""
    j = j or JEUX[0]
    vocal = _vocal_commu(g, c, j.cle)
    roles = {cle: entraide.role_zone(g, cfe, cle) for cle in j.zones}
    guides = " ".join(r.mention for cle, r in roles.items() if r is not None and cle != j.zones[-1])
    mm = roles.get(j.zones[-1])
    ticket = _ticket(g) if _ticket else None
    jouer = lien_jouer(g, c, j)
    lignes = [
        (jouer, f"### 🎮 Jouer · Play\nLe lien officiel de {j.nom}, en un clic.\n-# The official {j.nom} link, in one "
         "click.", "Jouer · Play"),
        (post(g, cfz, j.chat), f"### {j.emoji} Discuter · Talk\n{j.chat_fr}"
         + (f". Le vocal : 🔊 <#{vocal.id}>." if vocal is not None else ".") + f"\n-# {j.chat_en}", "Ouvrir · Open"),
        (post(g, cfz, j.help), "### 🛟 S'entraider · Get help\nChoisis Aide, Boss, Farm ou Chill et remplis : ta carte "
         "s'affiche, des joueurs cliquent « J'aide ». C'est réglé ? Tu la clôtures toi-même.\n-# Pick a type and fill "
         "in: your card shows up, players click “I'll help”. Close it yourself when done.", "Demander · Ask"),
        (post(g, cfz, j.trade), "### 🤝 Échanger · Trade\nPropose ton échange. Avec un inconnu, ne donne jamais en "
         "premier : appelle un middleman. Bon des deux côtés ? « Échange conclu ».\n-# Never give first to a stranger: "
         "call a middleman. Both happy? “Trade done”.", "Échanger · Trade"),
    ]
    items = [visuels.bandeau(j.bandeau, f"Guide {j.nom}"),
             discord.ui.TextDisplay(f"🇫🇷 {j.accueil_fr} Ici, tout se passe dans les posts de ce forum : on discute, "
                                    "on s'entraide, on échange — en français ou en anglais.\n"
                                    f"🇬🇧 {j.accueil_en} Everything happens in this forum's posts: chat, help each "
                                    "other, trade — in French or English.")]
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
    if ticket is not None and j.clan:
        items.append(discord.ui.Section(
            discord.ui.TextDisplay("### 🏴‍☠️ Le clan GoRP · The GoRP clan\nTu veux nous rejoindre ? Une candidature par "
                                   "ticket.\n-# Want to join us? Apply with a ticket."),
            accessory=discord.ui.Button(label="Postuler · Apply", url=ticket.jump_url)))
    elif ticket is not None:
        items.append(discord.ui.Section(
            discord.ui.TextDisplay("### 🎫 Une question ? · A question?\nOuvre un ticket : le staff te répond en privé."
                                   "\n-# Open a ticket: the staff answers privately."),
            accessory=discord.ui.Button(label="Ticket", url=ticket.jump_url)))
    items.append(discord.ui.TextDisplay("-# 🛡️ Personne du staff ne te demandera ton mot de passe · No staff will ever "
                                        "ask for your password · pas d'invitation vers d'autres serveurs · no invites"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(j.couleur)))
    signature = "|".join([str(GUIDE_VERSION), *(p.jump_url for p, _t, _b in presentes),
                          str(getattr(vocal, "id", 0)), *(str(getattr(r, "id", 0)) for r in roles.values()),
                          str(getattr(ticket, "id", 0)), str(int(_boutons_langue is not None))])
    return v, signature


async def assurer_guide(g) -> bool:
    """Le message d'ouverture du post 🧭 Guide de chaque jeu suit les posts, le vocal et les rôles (réécrit
    seulement quand quelque chose a changé). Rend True si l'un d'eux a été réécrit."""
    cfz, c = await conf(g), await _cfg(g.id)
    cfe = await entraide.conf(g)
    fait = False
    for j in JEUX:
        info = cfz["posts"].get(j.guide) or {}
        if not info.get("id"):
            continue
        vue, signature = vue_guide(g, c, cfz, cfe, j)
        if c.get(j.cle_guide_v) == signature:
            continue
        fil = await _resoudre(g, info["id"])
        if fil is None:
            continue
        if getattr(fil, "archived", False):
            await fil.edit(archived=False)
        await fil.get_partial_message(int(info.get("ouverture") or info["id"])).edit(
            view=vue, allowed_mentions=discord.AllowedMentions.none())
        await _db_set(g.id, j.cle_guide_v, signature)
        fait = True
    return fait


def groupes_aide(g, c: dict, cfz: dict) -> list:
    """Le panneau ❓ aide, par compartiment : [(titre, une phrase, [(salon ou post, bouton)])]. Un bouton
    n'apparaît que si son salon existe (aucun bouton qui ment)."""
    vocal = _vocal_commu(g, c)
    cadeaux = g.get_channel(int(c.get("cadeaux_salon", 0) or 0))
    commu = [(lien_salon(g, salon_commu(g, cfz, "discussion")), "💬 Discussion"),
             (lien_salon(g, salon_commu(g, cfz, "medias")), "📸 Médias"),
             (lien_salon(g, salon_commu(g, cfz, "suggestions")), "💡 Suggestions"),
             (lien_salon(g, salon_commu(g, cfz, "commandes")), "🤖 Commandes"),
             (lien_salon(g, cadeaux) if isinstance(cadeaux, discord.TextChannel) else None, "🎁 Cadeaux")]
    groupes = [("Communautaire · Community",
                "Discuter, partager, proposer une idée · Talk, share, suggest an idea"
                + (f" · 🔊 <#{vocal.id}>" if vocal is not None else ""), commu)]
    for j in JEUX:
        groupes.append((f"{j.emoji} {j.nom}",
                        "Le guide, le chat du jeu, l'entraide (boss, farm…) et le trade avec middleman · The guide, "
                        "the game chat, help and trades",
                        [(lien_jouer(g, c, j), "🎮 Jouer"), (post(g, cfz, j.guide), "🧭 Guide"),
                         (post(g, cfz, j.chat), f"{j.emoji} Chat"), (post(g, cfz, j.help), "🛟 Help"),
                         (post(g, cfz, j.trade), "🤝 Trade")]))
    return [(t, p, [(x, b) for x, b in boutons if x is not None]) for t, p, boutons in groupes]


# ═══════════════════════════════════════════════════════════════════════════════
#  La zone du clan GoRP
# ═══════════════════════════════════════════════════════════════════════════════

def categorie_clan(g):
    """La catégorie du clan (« 🦜 · GoRp_SEA »), même règle que `config_salons.est_clan`."""
    return next((cat for cat in getattr(g, "categories", []) or [] if config_salons.est_clan(cat.name)), None)


def _vocal_clan(g, c: dict, contexte: str = "clan"):
    """Le 🔊 Join du clan (ou sa « Demande ») : un salon « créer un vocal » de la catégorie du clan."""
    hubs = _hubs(g, c, True)
    return (next((ch for ch, x in hubs if x == contexte), None)
            or (next((ch for ch, x in hubs if x != "clan_demande"), None) if contexte == "clan" else None))


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


def vue_guide_clan(g, c: dict, posts: dict, metiers: tuple | None = None, site: tuple | None = None) -> tuple:
    """Le guide du clan, en tête de 🦜▷・clan-gorp : chaque post et à quoi il sert, le vocal, à qui
    s'adresser. Une ligne n'apparaît que si son post existe (aucun bouton qui ment). `metiers` : (composants,
    signature) du choix du métier (`metiers.section_guide`), posés avant le ticket ; `site` : de même, « Le site de
    l'équipage » (`site_equipage.section_guide`). Rend (vue, signature)."""
    vocal = _vocal_clan(g, c)
    demande = _vocal_clan(g, c, "clan_demande")
    ticket = _ticket(g) if _ticket else None

    def lien(cle):
        pid = int((posts.get(cle) or {}).get("id", 0) or 0)
        return Post(pid, f"https://discord.com/channels/{g.id}/{pid}") if pid else None
    #  Les textes du serveur (Textes & noms), sinon ceux d'origine ; ils entrent dans la signature : un texte changé
    #  réécrit le guide.
    salons = ((". " + _t(g.id, "guide.chat.vocal", salon=f"<#{vocal.id}>") if vocal is not None else "")
              + (" · " + _t(g.id, "guide.chat.demande", salon=f"<#{demande.id}>") if demande is not None else ""))
    lignes = [(lien(cle), _t(g.id, f"guide.{cle}.texte", salons=salons), _t(g.id, f"guide.{cle}.bouton"))
              for cle, *_x in GUIDE_POSTS]
    bienvenue = _t(g.id, "guide.bienvenue")
    items = [visuels.bandeau("clan_guide", "Guide du clan"), discord.ui.TextDisplay(bienvenue)]
    if _boutons_langue is not None:
        items.append(discord.ui.ActionRow(*_boutons_langue()))
    presentes = [(p, t, b) for p, t, b in lignes if p is not None]
    if presentes:
        items.append(discord.ui.Separator())
        for p, texte, libelle in presentes:
            items.append(discord.ui.Section(discord.ui.TextDisplay(texte),
                                            accessory=discord.ui.Button(label=libelle, url=p.jump_url)))
    items.append(discord.ui.Separator())
    if metiers is not None:   # 25/10/2026 : « Choisis ton métier » — l'affiche et les rôles de métier suivent
        items += [*metiers[0], discord.ui.Separator()]
    if site is not None:      # 26/10/2026 : « Le site de l'équipage » — un lien personnel, en lecture seule
        items += [*site[0], discord.ui.Separator()]
    ticket_t = (_t(g.id, "guide.ticket.texte"), _t(g.id, "guide.ticket.bouton"))
    if ticket is not None:
        items.append(discord.ui.Section(discord.ui.TextDisplay(ticket_t[0]),
                                        accessory=discord.ui.Button(label=ticket_t[1][:80], url=ticket.jump_url)))
    securite = _t(g.id, "guide.securite")
    items.append(discord.ui.TextDisplay(securite))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(0x14B8A6)))
    textes_ = "\x1f".join([bienvenue, *(f"{t}\x1e{b}" for _p, t, b in lignes), *ticket_t, securite])
    signature = "|".join([str(GUIDE_CLAN_VERSION), *(str(p.id) for p, _t, _b in presentes),
                          str(getattr(vocal, "id", 0)), str(getattr(demande, "id", 0)), str(getattr(ticket, "id", 0)),
                          str(int(_boutons_langue is not None))] + ([f"m{metiers[1]}"] if metiers is not None else [])
                         + ([f"s{site[1]}"] if site is not None else [])
                         + [f"t{zlib.crc32(textes_.encode('utf-8')):08x}"])
    return v, signature


_guides_clan_prevus: dict = {}


def _texte_du_guide_change(g, cle: str) -> None:
    """Un texte du guide du clan vient de changer sur le site (Textes & noms) : le guide se réécrit, une fois pour
    toute une rafale de changements."""
    if _cfg is None or g is None:
        return
    t = _guides_clan_prevus.get(g.id)
    if t is not None and not t.done():
        return

    async def _plus_tard():
        await asyncio.sleep(GUIDE_TEXTE_APRES_S)
        try:
            await assurer_guide_clan(g)
        except Exception as ex:  # le texte est enregistré ; seul le guide attend : dit au journal
            _log("[ZONES][E11] guide du clan non réécrit après un texte changé")
            _log(f"[ZONES][E11:DETAIL] serveur={g.id} {type(ex).__name__} {ex}")
    _guides_clan_prevus[g.id] = asyncio.get_running_loop().create_task(_plus_tard())


textes_du_site.quand_change("guide.", _texte_du_guide_change)


async def assurer_guide_clan(g) -> bool:
    """Le message d'ouverture du post 🧭 Guide du clan suit les posts, le vocal, le salon des tickets et le choix du
    métier (réécrit seulement quand quelque chose a changé). Rend True s'il a été réécrit."""
    c = await _cfg(g.id)
    posts = c.get("clan_posts") or {}
    info = posts.get("guide") or {}
    if not info.get("id"):
        return False
    metiers = None
    if _section_metiers is not None:
        try:
            metiers = await _section_metiers(g, c)
        except Exception as ex:  # la base fait défaut : le guide reste tel quel (jamais réécrit sans la liste, puis avec)
            _log("[ZONES][E10] choix du métier indisponible : guide du clan inchangé")
            _log(f"[ZONES][E10:DETAIL] {type(ex).__name__} {ex}")
            return False
    site = None
    if _section_site is not None:
        try:
            site = await _section_site(g, c)
        except Exception as ex:  # jamais un guide réécrit sans le bouton, puis avec : il reste tel quel
            _log("[ZONES][E11] site de l'équipage indisponible : guide du clan inchangé")
            _log(f"[ZONES][E11:DETAIL] {type(ex).__name__} {ex}")
            return False
    vue, signature = vue_guide_clan(g, c, posts, metiers, site)
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
