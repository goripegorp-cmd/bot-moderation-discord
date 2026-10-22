"""zones.py — les compartiments du serveur (22/10/2026).

« Le serveur est international, mais aussi français… une zone communautaire… un espèce de fil où
les gens puissent discuter un peu comme dans le chat, médias pour les photos, commandes pour les
bots… boost et suggestions… regroupe à l'intérieur ; puis une zone Rell Seas, avec un chat dédié au
jeu et leur propre système vocal — quelqu'un qui fait du Rell Seas peut aussi rejoindre l'autre
vocal… limiter les salons, mais un plus gros système de fil… des salons déjà pré-créés et utilisés…
séparer les deux compartiments au propre. »

· Communautaire : ❓aide (l'orientation), 💬chat, 🧵discussions (forum : 📸 Médias · Media et
🤖 Commandes · Commands déjà ouverts ; chacun peut ouvrir un sujet), 💡suggestions, 🚀boosts,
puis 🔊Join.
· Rell Seas (juste après) : 🌊chat-rellseas (le jeu), 🛟help, 🤝trade, ⚓crews, puis 🔊Join (son propre
vocal ; tout le monde entre partout). Noms au style du serveur : « · Nom » pour une catégorie, l'émoji
collé au nom pour un salon. Rien de ce que les membres ont créé n'est supprimé.
"""
from __future__ import annotations

import discord

import config_salons
import entraide
import equipages

RELL_CATEGORIE = "· Rell Seas"
RELL_CHAT = "🌊chat-rellseas"
RELL_VOCAL = "🔊Join"
FORUM = "🧵discussions"
#  On parle, on montre (images, liens), on réagit, on utilise les commandes : comme au 💬chat.
PAROLE = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True,
                                     send_messages_in_threads=True, attach_files=True, embed_links=True,
                                     add_reactions=True, use_application_commands=True)
VOCAL = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
BOT = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True,
                                  send_messages_in_threads=True, create_public_threads=True, manage_threads=True,
                                  embed_links=True, attach_files=True)
LECTURE_CLAN = discord.PermissionOverwrite(**config_salons.LECTURE)
EQUIPE_CLAN = discord.PermissionOverwrite(**config_salons.EQUIPE_TEXTE, send_messages_in_threads=True)
#  Les fils déjà ouverts du forum des discussions : (clé, titre, premier message)
FILS = (
    ("medias", "📸 Médias · Media",
     "🇫🇷 Partage ici tes captures, clips et vidéos.\n🇬🇧 Share your screenshots, clips and videos here."),
    ("commandes", "🤖 Commandes · Commands",
     "🇫🇷 Les commandes des bots, c'est ici : le chat reste lisible.\n"
     "🇬🇧 Use the bots' commands here: the chat stays readable."),
)
SUJET_FORUM = ("🇫🇷 Des fils pour tout : médias, commandes, et tes propres sujets (bouton « Nouveau post »).\n"
               "🇬🇧 Threads for everything: media, commands, and your own topics (« New post » button).")
SUJET_CHAT = ("🇫🇷 Le chat de Rell Seas : îles, fruits, mises à jour, astuces. Français ou anglais.\n"
              "🇬🇧 The Rell Seas chat: islands, fruits, updates, tips. French or English.")
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

_cfg = _db_set = None
_log = print


def setup(*, cfg, db_set, log=None):
    global _cfg, _db_set, _log
    _cfg, _db_set = cfg, db_set
    _log = log or print


def communautaire(g):
    return entraide.categorie_communautaire(g)


async def conf(g) -> dict:
    c = await _cfg(g.id)
    return {"rell": int(c.get("zones_rell", 0) or 0), "chat": int(c.get("zones_chat", 0) or 0),
            "vocal": int(c.get("zones_vocal", 0) or 0), "forum": int(c.get("zones_forum", 0) or 0),
            "fils": dict(c.get("zones_fils") or {}), "actif": bool(c.get("zones_v1"))}


def ids_salons(c: dict) -> set:
    """Les salons des zones, pour qu'aucun réglage de masse ne touche à leurs droits."""
    ids = {int(c.get(k, 0) or 0) for k in ("zones_rell", "zones_chat", "zones_vocal", "zones_forum", "clan_annonces",
                                           "clan_forum")}
    return {i for i in ids if i} | entraide.ids_salons(c) | ({int(c["eq_forum"])} if c.get("eq_forum") else set())


async def _rell(g, cf: dict):
    cat = g.get_channel(cf["rell"])
    if isinstance(cat, discord.CategoryChannel):
        return cat, False
    cat = await g.create_category(RELL_CATEGORIE, reason="Zone Rell Seas : le jeu, à part de la communauté")
    await _db_set(g.id, "zones_rell", cat.id)
    commu = communautaire(g)
    if commu is not None:
        try:
            await cat.edit(position=commu.position + 1, reason="Juste après Communautaire")
        except discord.HTTPException as ex:
            _log(f"[ZONES:DETAIL] position de la zone {ex}")
    return cat, True


async def _vocal_rell(g, cat, cf: dict):
    """Le vocal du jeu : un « Join » comme celui de la communauté, ses salons naissent dans la zone."""
    v = g.get_channel(cf["vocal"])
    cree = False
    if v is None:
        v = await g.create_voice_channel(RELL_VOCAL, category=cat, overwrites={g.default_role: VOCAL},
                                         reason="Zone Rell Seas : son propre vocal")
        await _db_set(g.id, "zones_vocal", v.id)
        cree = True
    c = await _cfg(g.id)
    voix = dict(c.get("temp_voice_config") or {})
    hubs = dict(voix.get("hubs") or {})
    if str(v.id) not in hubs or not voix.get("enabled"):
        hubs[str(v.id)] = dict(hubs.get(str(v.id)) or {}, category=cat.id, default_name="🌊 {user}")
        voix.update(enabled=True, hubs=hubs)
        await _db_set(g.id, "temp_voice_config", voix)
    return v, cree


async def _forum_commu(g, cf: dict, commu, forum: bool):
    ch = g.get_channel(cf["forum"])
    faits = []
    if ch is None:
        droits = {g.default_role: PAROLE, g.me: BOT}
        if forum:
            ch = await g.create_forum(FORUM, category=commu, topic=SUJET_FORUM, overwrites=droits,
                                      default_auto_archive_duration=10080,
                                      default_layout=discord.ForumLayoutType.list_view,
                                      default_sort_order=discord.ForumOrderType.latest_activity,
                                      reason="Communautaire : des fils plutôt que des salons")
        else:
            ch = await g.create_text_channel(FORUM, category=commu, topic=SUJET_FORUM[:1024], overwrites=droits,
                                             reason="Communautaire : des fils plutôt que des salons")
        await _db_set(g.id, "zones_forum", ch.id)
        faits.append(f"salon {ch.name}")
    fils, f2 = await _fils_prets(g, ch, cf["fils"], FILS)
    await _db_set(g.id, "zones_fils", fils)
    return ch, faits + f2


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


async def installer(g, *, forum: bool | None = None) -> list:
    """Crée ce qui manque — zone Rell Seas (chat, vocal, entraide, équipages) et forum des discussions —
    puis range les deux compartiments. Ne supprime rien. Rend la liste de ce qui a été fait."""
    p = getattr(g.me, "guild_permissions", None)
    if not (p and p.manage_channels and p.manage_roles):
        raise PermissionError("Il me faut « Gérer les salons » et « Gérer les rôles ».")
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    cf = await conf(g)
    faits = []
    rell, cree = await _rell(g, cf)
    if cree:
        faits.append(f"catégorie {rell.name}")
    chat = g.get_channel(cf["chat"])
    if chat is None:
        chat = await g.create_text_channel(RELL_CHAT, category=rell, topic=SUJET_CHAT, slowmode_delay=2,
                                           overwrites={g.default_role: PAROLE},
                                           reason="Zone Rell Seas : le chat du jeu")
        await _db_set(g.id, "zones_chat", chat.id)
        faits.append(f"salon {chat.name}")
    _v, cree = await _vocal_rell(g, rell, cf)
    if cree:
        faits.append(f"vocal {RELL_VOCAL}")
    faits += await entraide.installer(g, forum=forum, categorie=rell)
    faits += await entraide.mettre_a_niveau(g, categorie=rell)
    faits += await equipages.installer(g, rell, forum=forum)
    commu = communautaire(g) or await entraide.categorie_cible(g)
    _f, f2 = await _forum_commu(g, cf, commu, forum)
    faits += f2
    await _db_set(g.id, "zones_v1", 1)
    try:
        await ordonner(g)
    except discord.HTTPException as ex:
        _log("[ZONES][E1] compartiments non rangés")
        _log(f"[ZONES][E1:DETAIL] {type(ex).__name__} {ex}")
    return faits


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
    """Communautaire : ❓aide, 💬chat, 🧵discussions, 💡suggestions, 🚀boosts. Rell Seas : 🌊chat-rellseas,
    🛟help, 🤝trade, ⚓crews. Les vocaux restent en bas de chaque zone."""
    c, cf = await _cfg(g.id), await conf(g)
    cfe, cfq = await entraide.conf(g), await equipages.conf(g)
    commu, rell = communautaire(g), g.get_channel(cf["rell"])
    fait = False
    if commu is not None:
        chat = next((ch for ch in commu.channels if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel))
                     and "chat" in config_salons.normaliser(ch.name).split()), None)
        fait |= await _ranger(commu, [_dans(g.get_channel(int(c.get("aide_salon", 0) or 0)), commu), chat,
                                      _dans(g.get_channel(cf["forum"]), commu),
                                      _dans(g.get_channel(int(c.get("suggestions_salon", 0) or 0)), commu),
                                      _dans(g.get_channel(int(c.get("boosts_salon", 0) or 0)), commu)])
    if isinstance(rell, discord.CategoryChannel):
        fait |= await _ranger(rell, [_dans(g.get_channel(cf["chat"]), rell),
                                     _dans(entraide.salon(g, cfe, "entraide"), rell),
                                     _dans(entraide.salon(g, cfe, "trade"), rell),
                                     _dans(equipages.forum_de(g, cfq), rell)])
    return fait


async def entretenir(g) -> None:
    """Toutes les 30 minutes : les fils prêts à l'emploi (Communautaire, clan) restent ouverts et visibles."""
    cf, c = await conf(g), await _cfg(g.id)
    a_suivre = (list(cf["fils"].items()) if cf["actif"] else []) + list(dict(c.get("clan_fils") or {}).items())
    for cle, fid in a_suivre:
        fid = int(fid or 0)
        fil = g.get_channel_or_thread(fid) if fid else None
        if fil is None and fid:
            try:
                fil = await g.fetch_channel(fid)
            except discord.NotFound:
                fil = None
            except discord.HTTPException as ex:
                _log(f"[ZONES:DETAIL] lecture du fil {cle} {ex}")
                continue
        if fil is not None and getattr(fil, "archived", False):
            try:
                await fil.edit(archived=False)
            except discord.HTTPException as ex:
                _log(f"[ZONES:DETAIL] réveil du fil {cle} {ex}")


def lignes_aide(g, c: dict, cfz: dict, cfe: dict, cfq: dict) -> dict:
    """Le contenu du panneau ❓ aide, par compartiment : {titre: [(salon, texte, bouton)]}. Une ligne
    n'apparaît que si son salon existe."""
    chat_commu = None
    commu = communautaire(g)
    if commu is not None:
        chat_commu = next((ch for ch in commu.channels if not isinstance(ch, (discord.VoiceChannel,
                                                                             discord.StageChannel))
                           and "chat" in config_salons.normaliser(ch.name).split()), None)
    vocal_commu = next((g.get_channel(int(k)) for k in ((c.get("temp_voice_config") or {}).get("hubs") or {})
                        if str(k).isdigit() and int(k) != cfz["vocal"] and g.get_channel(int(k)) is not None
                        and not config_salons.est_clan(getattr(getattr(g.get_channel(int(k)), "category", None),
                                                               "name", ""))), None)
    vocal_rell = g.get_channel(cfz["vocal"])

    def voc(v):
        return f" · 🔊 <#{v.id}>" if v is not None else ""
    return {
        "Communautaire · Community": [
            (chat_commu, "💬 **Chat** — discuter de tout · talk about anything" + voc(vocal_commu), "Ouvrir · Open"),
            (g.get_channel(cfz["forum"]), "🧵 **Discussions** — médias, commandes, tes sujets · media, commands, "
                                          "your topics", "Ouvrir · Open"),
            (g.get_channel(int(c.get("suggestions_salon", 0) or 0)), "💡 **Suggestions** — propose une idée · "
                                                                    "suggest an idea", "Ouvrir · Open"),
        ],
        "Rell Seas": [
            (g.get_channel(cfz["chat"]), "🌊 **Chat Rell Seas** — le jeu · the game" + voc(vocal_rell), "Ouvrir · Open"),
            (entraide.salon(g, cfe, "entraide"), "🛟 **Help** — une question, un boss, du farm, du chill · a question, "
                                                 "a boss, farming, chilling", "Demander · Ask"),
            (entraide.salon(g, cfe, "trade"), "🤝 **Trade** — fruits et objets, avec middleman · fruits & items, "
                                              "with a middleman", "Échanger · Trade"),
            (equipages.forum_de(g, cfq), "⚓ **Crews** — Pirates ou Marine : publie ou rejoins · post or join",
             "Équipages · Crews"),
        ],
    }
