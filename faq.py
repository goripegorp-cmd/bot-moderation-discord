"""faq.py — les réponses toutes faites (22/10/2026, refaites le 24/10/2026).

Le 22/10, le fondateur : « les gens qui posent des questions — comment on fait pour rejoindre le clan, pour
créer un ticket staff… — ça les renvoie… au propre vers des salons, avec des réponses ultra bien faites ».
Le 24/10 : « Ils sont où les liens pour rejoindre le jeu ? Le salon Game Link… les annonces de Rell Seas,
Sneak Rell Seas… les annonces de Roblox, Sneak News Roblox… les vidéos, les lives que GoRipe poste… les salons
pour échanger : si c'est général, tous ; s'il cible un jeu, le salon du jeu… pour de futurs jeux… comment je
demande de l'aide, en fonction du jeu… il y a plusieurs types de langues… l'international. »

Dans un salon public (jamais un ticket ni un salon du staff), une vraie question (`questions.est_question`)
sur un de ces sujets — en français, anglais, espagnol, portugais, allemand ou italien — reçoit une carte
courte avec un bouton par bon endroit : celui du jeu nommé (ou du forum où l'on écrit), sinon ceux de tous
les jeux (`zones.JEUX` : un nouveau jeu y entre tout seul). Réponse en français à une question en français,
sinon en anglais. Une fois par membre et par sujet par demi-heure ; une fois par salon et par sujet toutes
les 5 minutes. La carte s'efface au bout de 30 minutes : le chat reste propre. Jamais un bouton qui ment :
un endroit inconnu n'a pas de bouton, et sans aucun bouton, pas de carte.

27/10/2026 : « c'est le bot qui doit leur répondre » — ce fichier ne garde que le savoir (les sujets, les endroits, la
carte) ; QUAND et À QUI répondre (l'aide de chaque jeu, l'anti-spam, la surveillance sur le site) est dans
`reponses_auto.py`. Les textes des sujets sont dans le registre (« Textes & noms », famille « Réponses du bot »).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import discord
from discord.ui import Button

import config_salons
import questions
import textes
from ui_v2 import LayoutView, Palette


@dataclass(frozen=True)
class Sujet:
    cle: str
    emoji: str
    titre_fr: str
    titre_en: str
    texte_fr: str
    texte_en: str
    vers: str            # « ticket », « suggestions », « goripe »… ou, par jeu, « jeu:trade », « jeu:help »…
    motifs: tuple        # une question qui en parle (français, anglais, espagnol, portugais, allemand, italien)


#  Du plus précis au plus général : le premier sujet reconnu répond.
SUJETS = (
    Sujet("clan", "🏴‍☠️", "Rejoindre le clan", "Join the clan",
          "Pour entrer dans le clan GoRP, ouvre un ticket de candidature{type} : le staff du clan te répond en "
          "privé.",
          "To join the GoRP clan, open an application ticket{type}: the clan staff answers privately.",
          "ticket",
          (r"\b(rejoindre|int[ée]grer|entrer dans|faire partie d[ue]|candidat\w*|postuler|recrut\w*)\b.{0,40}"
           r"\b(clan|gorp\w*|team|guilde)\b",
           #  « Comment je fais pour venir dans l'équipage » : l'équipage, c'est le clan.
           r"\b(rejoindre|venir dans|entrer dans|int[ée]grer|faire partie d[ue])\b.{0,30}\b([ée]quipage|crew)\b",
           r"\b(join|get into|be part of)\b.{0,30}\bcrew\b",
           r"\b(clan|gorp\w*)\b.{0,40}\b(rejoindre|recrut\w*|candidat\w*|postuler)\b",
           r"\b(join|apply|get into|be part of)\b.{0,40}\b(clan|gorp\w*|team|guild)\b",
           r"\b(unirme|unirse|entrar|ingresar|participar|beitreten|entrare|unirmi)\b.{0,30}\b(clan|cl[aã]|gorp\w*)\b",
           r"\b(clan|gorp\w*)\b.{0,30}\b(beitreten)\b")),
    Sujet("aide_clan", "🏴‍☠️", "Une question sur le clan", "A question about the clan",
          "Pour une question ou un souci avec le clan, ouvre un ticket{type} : le staff du clan te répond.",
          "For a question or an issue with the clan, open a ticket{type}: the clan staff answers you.",
          "ticket",
          (r"\b(aide|aider|question|probl[eè]me|souci)\b.{0,30}\b(clan|gorp\w*)\b",
           r"\b(help|question|problem|issue)\b.{0,30}\b(clan|gorp\w*)\b")),
    Sujet("ticket", "🎫", "Ouvrir un ticket", "Open a ticket",
          "Dans 🏷ticket : bouton « Créer un ticket », puis choisis le type. Seuls toi et le staff le voyez.",
          "In 🏷ticket: “Create a ticket” button, then pick the type. Only you and the staff can see it.",
          "ticket",
          (r"\b(cr[ée]er|ouvrir|faire|mettre|open|create|make|abrir|crear|criar|aprire|creare)\b.{0,20}\btickets?\b",
           r"\btickets?\b.{0,20}\b(erstellen|[öo]ffnen|er[öo]ffnen)\b",
           r"\b(contacter|parler (au|à|a)|joindre|[ée]crire (au|à|a))\b.{0,20}\b(staff|modo\w*|mod[ée]rat\w*|admin\w*)\b",
           r"\b(contact|reach|talk to)\b.{0,20}\b(staff|mods?|admins?)\b")),
    Sujet("lien_jeu", "🎮", "Rejoindre le jeu", "Join the game",
          "Les liens pour rejoindre nos jeux sont dans 🎮 game-link.",
          "The links to join our games are in 🎮 game-link.",
          "jeu:lien",
          (r"\b(liens?|links?)\b.{0,40}\b(jeux?|jouer|rejoindre|serveurs? priv[ée]s?|game|play|join|private server)\b",
           r"\b(jeux?|game|games)\b.{0,20}\b(liens?|links?)\b",
           r"\bgame ?link\b",
           r"\b(comment|o[uù])\b.{0,30}\b(rejoindre|jouer [aà]|trouver)\b.{0,20}\b(jeux?|rell\w*|clover\w*)\b",
           r"\bhow (do i|can i|to|do you) (join|play|get to)\b.{0,25}\b(game|rell\w*|clover\w*)\b",
           r"\b(enlaces?|links?)\b.{0,40}\b(juegos?|jugar|unirme)\b",
           r"\bc[oó]mo (entro|juego|me uno|puedo jugar)\b",
           r"\b(links?)\b.{0,40}\b(jogos?|jogar|entrar)\b",
           r"\bcomo (entro|jogo|posso jogar)\b",
           r"\b(links?)\b.{0,40}\b(spiel\w*|beitreten)\b",
           r"\bwie (komme|trete|spiele) ich\b",
           r"\b(link)\b.{0,40}\b(gioco|giocare)\b",
           r"\bcome (entro|gioco)\b")),
    Sujet("trade", "🤝", "Échanger", "Trading",
          "Chaque jeu a son 🤝 Trade : « Proposer » ta carte. Avec un inconnu, ne donne jamais en premier : "
          "appelle un middleman.",
          "Each game has its 🤝 Trade: “Post a trade”. With a stranger, never give first: call a middleman.",
          "jeu:trade",
          (r"\b(trad(e|er|es|ing)|[ée]chang(er|e|es|ent)|middleman|swap)\b",
           r"\b(intercambi(ar|o|os)|tradear|trocar|trocas?|tauschen|tausch|handeln|scambi(are|o)?)\b")),
    Sujet("suggestion", "💡", "Proposer une idée", "Suggest an idea",
          "Dans 💡 Suggestions : bouton « Proposer », tout le monde vote, le staff répond.",
          "In 💡 Suggestions: “Suggest” button, everyone votes, the staff answers.",
          "suggestions",
          #  « suggest » seul répondait à « can you suggest a build? » : il faut une idée à proposer.
          (r"\b(suggestions?|propos(er|e) (une |des )?(id[ée]es?|am[ée]liorations?))\b",
           r"\b(suggest (an? )?(ideas?|features?|improvements?)|make a suggestion)\b",
           r"\b(sugerencias?|sugerir|sugest[aã]o|sugest[oõ]es|vorschl[aä]ge?|vorschlagen|suggeriment[oi]|"
           r"suggerire)\b")),
    Sujet("aide_jeu", "🛟", "De l'aide en jeu", "Help in game",
          "Chaque jeu a son 🛟 Help : choisis Aide, Boss, Farm ou Chill, remplis — des joueurs viennent t'aider. "
          "Pour le staff : un ticket.",
          "Each game has its 🛟 Help: pick Help, Boss, Farm or Chill, fill in — players come to help you. For the "
          "staff: a ticket.",
          "jeu:help",
          (r"\b(besoin d'aide|aide[rz]? (moi|pour|sur)|qui (peut|veut) m'aider)\b",
           r"\b(need help|help me|can someone help|who can help)\b",
           r"\b(aide|aider|help|besoin)\b.{0,30}\b(boss|farm\w*|qu[eê]tes?|quests?)\b",
           r"\b(boss|farm\w*|qu[eê]tes?|quests?)\b.{0,30}\b(aide|aider|help)\b",
           r"\b(comment|o[uù])\b.{0,25}\b(demand\w*|avoir|trouv\w*|obten\w*)\b.{0,15}\baide\b",
           r"\bhow (do i|can i|to) (ask|get|find)\b.{0,10}\bhelp\b",
           r"\b(necesito ayuda|ay[uú]dame|ayuda (con|para|en))\b",
           r"\b(preciso de ajuda|me ajuda|ajuda (com|para|no))\b",
           r"\b(ich brauche hilfe|hilfe (bei|mit|im))\b",
           r"\b(ho bisogno di aiuto|aiutami|aiuto (con|per))\b")),
    Sujet("annonces", "📢", "Les annonces", "Announcements",
          "Les annonces du serveur, et celles de chaque jeu dans son salon.",
          "Server announcements, and each game's in its own channel.",
          "jeu:annonces",
          (r"\b(annonces?|news|nouveaut[ée]s?|actus?|actualit[ée]s?|mises? [aà] jour|maj|patch(es)?|sneak|leaks?)\b",
           r"\b(announcements?|updates?|patch notes?|sneak peeks?)\b",
           r"\b(anuncios?|noticias|novedades|actualizaci[oó]n(es)?|an[uú]ncios?|not[ií]cias|novidades|"
           r"atualiza[cç](ão|ões)|ank[uü]ndigungen?|neuigkeiten|annunci|notizie|novit[aà]|aggiornamenti)\b")),
    Sujet("videos", "🎥", "Les vidéos et les lives", "Videos and lives",
          "Les vidéos et les lives de GoRipe sont publiés dans le salon GoRipe.",
          "GoRipe's videos and lives are posted in the GoRipe channel.",
          "goripe",
          #  24/10/2026 (revue) : « live » / « stream » seuls attrapaient « combien de lives ai-je ? » (les vies
          #  d'un jeu) — il faut un déterminant (« le live », « en stream », « the live »…).
          (r"\b(vid[ée]os?|twitch|youtube|tiktok|goripe|livestreams?)\b",
           r"\b(le|les|en|un|ses|ton|tes|son|prochain|prochains|the|a|your|his|next)\s+(lives?|streams?)\b",
           r"\b(directos?|transmisi[oó]n|transmiss[aã]o|dirette?)\b")),
)
#  Les textes quand le jeu est connu (« {jeu} ») et les actus Roblox.
TEXTES_JEU = {
    "trade": ("Dans 🤝 Trade de {jeu} : « Proposer » ta carte. Avec un inconnu, ne donne jamais en premier : "
              "appelle un middleman.",
              "In {jeu}'s 🤝 Trade: “Post a trade”. With a stranger, never give first: call a middleman."),
    "help": ("Dans 🛟 Help de {jeu} : choisis Aide, Boss, Farm ou Chill, remplis — des joueurs viennent t'aider.",
             "In {jeu}'s 🛟 Help: pick Help, Boss, Farm or Chill, fill in — players come to help you."),
    "annonces": ("Les annonces de {jeu} sont dans son salon.", "{jeu} announcements are in its channel."),
    "lien": ("Le lien officiel de {jeu} : un clic sur « Jouer ».", "{jeu}'s official link: click “Play”."),
    "roblox": ("Les actus Roblox arrivent toutes seules dans leur salon.",
               "Roblox news arrive on their own in their channel."),
}
BOUTONS = {"ticket": ("Ouvrir un ticket", "Open a ticket"), "trade": ("Trade", "Trade"),
           "suggestions": ("Suggestions", "Suggestions"), "help": ("Help", "Help"), "goripe": ("🎥 GoRipe", "🎥 GoRipe"),
           "game_link": ("🎮 Game Link", "🎮 Game Link")}
EMOJI_JEU = {"trade": "🤝", "help": "🛟", "annonces": "📢", "lien": "🎮"}
#  La langue de la question : ses petits mots (« comment », « je »… ou « how », « the »…) ; une autre langue
#  (espagnol, portugais, allemand, italien) reçoit l'anglais, la langue de l'international.
MOTS_FR = re.compile(r"\b(comment|je|j|tu|on|le|la|les|des|pour|est|un|une|du|faire|quoi|o[uù]|qui|peut)\b")
MOTS_EN = re.compile(r"\b(how|what|where|can|could|the|is|do|does|i|you|to|an|who|which)\b")
MOTS_AUTRES = re.compile(r"[¿¡]|\b(d[oó]nde|c[oó]mo|cu[aá]ndo|est[aá]n?|hay|los|las|para|onde|voc[eê]|est[aã]o|tem"
                         r"|wo|wie|ist|sind|gibt|kann|ich|dove|sono|posso|qual)\b")
ROBLOX = re.compile(r"\broblox\b")

#  27/10/2026 : les textes des sujets, réécrits par la direction (« Textes & noms ») — la clé, son texte d'origine.
GROUPE_TEXTES = "reponses"
textes.nommer_groupe(GROUPE_TEXTES, "Réponses du bot", 35)
_PARTIE = "Les questions fréquentes"
for _n, _s in enumerate(SUJETS):
    for _l, _defaut in (("fr", _s.texte_fr), ("en", _s.texte_en)):
        textes.declarer(f"faq.{_s.cle}.{_l}", _defaut, groupe=GROUPE_TEXTES, partie=_PARTIE, ordre=100 + 2 * _n
                        + (_l == "en"), titre=f"{_s.titre_fr} · {'anglais' if _l == 'en' else 'français'}", max_=600,
                        variables=(("type", "le type de ticket du clan, entre parenthèses"),) if "{type}" in _defaut
                        else (), aide="La réponse à une question sur ce sujet ; les boutons mènent aux bons salons.")
for _n, (_cle, (_fr, _en)) in enumerate(TEXTES_JEU.items()):
    for _l, _defaut in (("fr", _fr), ("en", _en)):
        textes.declarer(f"faq.jeu.{_cle}.{_l}", _defaut, groupe=GROUPE_TEXTES, partie=_PARTIE, ordre=200 + 2 * _n
                        + (_l == "en"), titre=f"Un jeu nommé · {_cle} · {'anglais' if _l == 'en' else 'français'}",
                        max_=600, variables=(("jeu", "le nom du jeu"),) if "{jeu}" in _defaut else (),
                        aide="La même réponse quand la question nomme un jeu (ou vient de son salon).")


def _t(gid, cle: str, **valeurs) -> str:
    """Le texte de ce serveur (Textes & noms), sinon celui d'origine ; `gid` None : celui d'origine."""
    return textes.texte_cache(int(gid or 0), cle, **valeurs)


def langue_du_texte(t: str) -> str:
    """« fr », « en » (l'anglais aussi pour l'espagnol, le portugais, l'allemand, l'italien), ou "" si rien
    ne le dit."""
    fr, en, autres = len(MOTS_FR.findall(t)), len(MOTS_EN.findall(t)), len(MOTS_AUTRES.findall(t))
    if autres > max(fr, en):
        return "en"
    return "" if fr == en else ("en" if en > fr else "fr")


def reconnaitre(texte: str) -> tuple:
    """FONCTION PURE : (le sujet, la langue de la question — "" si rien ne le dit), ou (None, "") si ce
    n'est pas une question sur l'un d'eux."""
    if not questions.est_question(texte):
        return None, ""
    t = questions.nettoyer(texte).lower()
    for s in SUJETS:
        if any(re.search(m, t) for m in s.motifs):
            return s, langue_du_texte(t)
    return None, ""


def salons_du_serveur(salons, mots_jeux) -> dict:
    """FONCTION PURE : les salons d'information reconnus par leur nom, parmi `salons` (ceux que @everyone
    voit) : {« game_link », « annonces » (le serveur), « roblox » (les actus), « goripe » (vidéos et lives),
    « jeux » : [le salon des annonces de chaque jeu, dans l'ordre de `mots_jeux`]}. Absent : None."""
    def mots(ch):
        return config_salons.normaliser(getattr(ch, "name", "") or "").split()

    def premier(test):
        return next((ch for ch in salons if test(mots(ch))), None)

    def du_jeu(m, prefixes):
        return any(x.startswith(p) for x in m for p in prefixes)
    tous = [p for jm in mots_jeux for p in jm]
    return {
        "game_link": premier(lambda m: ("game" in m and "link" in m) or "gamelink" in m),
        "roblox": premier(lambda m: "roblox" in m and any(x in ("news", "actu", "actus") for x in m)),
        "goripe": premier(lambda m: "goripe" in m and "sneak" not in m),
        "annonces": premier(lambda m: any(x in ("annonce", "annonces", "announcements") for x in m)
                            and not du_jeu(m, tous) and "clan" not in m and not any(x.startswith("gorp") for x in m)),
        "jeux": [premier(lambda m, jm=jm: du_jeu(m, jm) and ("sneak" in m or "news" in m
                                                             or any(x.startswith("annonce") for x in m)))
                 for jm in mots_jeux],
    }


def jeux_nommes(texte: str, jeux: list) -> list:
    """Les jeux dont la question parle (« rell », « rellseas », « clover »…)."""
    return [j for j in jeux if any(re.search(r"\b" + re.escape(m), texte) for m in j.get("mots") or ())]


def jeux_du_salon(salon, jeux: list) -> list:
    """Le jeu du forum où l'on écrit (un post de 🌊rell-seas, de 🍀clover-rpg…)."""
    parent = getattr(salon, "parent", None) if isinstance(salon, discord.Thread) else None
    pid = getattr(parent, "id", 0)
    return [j for j in jeux if pid and int(j.get("forum") or 0) == pid]


def reponse(s: Sujet, texte: str, salon, liens: dict, langue: str, gid=None) -> tuple | None:
    """(titre, texte, [(bouton, lien)]) — un bouton par bon endroit, cinq au plus ; None si aucun endroit
    n'est connu (jamais un bouton qui ment). `gid` : les textes réécrits de ce serveur (Textes & noms)."""
    en = langue == "en"
    lg = "en" if en else "fr"
    titre = f"{s.emoji} {s.titre_en if en else s.titre_fr}"
    precision = f" (type « {liens.get('type_clan')} »)" if liens.get("type_clan") and s.cle in ("clan", "aide_clan") \
        else ""
    corps = _t(gid, f"faq.{s.cle}.{lg}", type=precision)
    if not s.vers.startswith("jeu:"):
        url = liens.get(s.vers)
        return (titre, corps, [(BOUTONS.get(s.vers, ("Ouvrir", "Open"))[1 if en else 0], url)]) if url else None
    cle = s.vers[4:]
    jeux = list(liens.get("jeux") or [])
    nommes = jeux_nommes(texte, jeux) or jeux_du_salon(salon, jeux)
    if cle == "annonces" and not nommes and ROBLOX.search(texte):
        url = liens.get("roblox")
        return (f"📰 {'Roblox news' if en else 'Les actus Roblox'}", _t(gid, f"faq.jeu.roblox.{lg}"),
                [("📰 Roblox", url)]) if url else None
    choisis = nommes or jeux
    if cle == "lien":
        libelle = "Play" if en else "Jouer"
        boutons = [(f"🎮 {libelle} · {j['nom']}", j.get("lien")) for j in choisis if j.get("lien")]
    else:
        boutons = [(f"{EMOJI_JEU[cle]} {j['nom']}", j.get(cle)) for j in choisis if j.get(cle)]
    if len(nommes) == 1 and boutons:
        corps = _t(gid, f"faq.jeu.{cle}.{lg}", jeu=nommes[0]["nom"])
    if cle == "lien" and liens.get("game_link"):
        boutons.insert(0, ("🎮 Game Link", liens["game_link"]))
        if not nommes or len(boutons) == 1:
            corps = _t(gid, f"faq.{s.cle}.{lg}", type="")
    if cle == "annonces" and not nommes and liens.get("annonces"):
        boutons.insert(0, ("📜 " + ("Server" if en else "Serveur"), liens["annonces"]))
    if cle == "help" and not nommes and boutons and liens.get("ticket"):
        boutons.append(("🎫 Ticket", liens["ticket"]))
    if not boutons:
        return None
    if cle == "help" and nommes:
        corps = _t(gid, f"faq.jeu.help.{lg}", jeu=nommes[0]["nom"])
    elif cle == "help" and not liens.get("ticket"):
        corps = corps.replace(" Pour le staff : un ticket.", "").replace(" For the staff: a ticket.", "")
    return titre, corps, boutons[:5]


def vue_reponse(titre: str, corps: str, boutons: list, pied: str = "Réponse automatique · Automatic answer") \
        -> LayoutView:
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay(f"### {titre}\n{corps}"),
        discord.ui.ActionRow(*[Button(label=libelle[:80], url=url) for libelle, url in boutons[:5]]),
        discord.ui.TextDisplay(f"-# {pied}"), accent_color=Palette.INFO))
    return v


def vue(s: Sujet, langue: str, lien: str, type_clan: str = "") -> LayoutView:
    """Une réponse à un seul bouton (le clan, un ticket…)."""
    en = langue == "en"
    precision = f" (type « {type_clan} »)" if type_clan and s.cle in ("clan", "aide_clan") else ""
    texte = (s.texte_en if en else s.texte_fr).format(type=precision)
    libelle = BOUTONS.get(s.vers, ("Ouvrir", "Open"))[1 if en else 0]
    return vue_reponse(f"{s.emoji} {s.titre_en if en else s.titre_fr}", texte, [(libelle, lien)])
