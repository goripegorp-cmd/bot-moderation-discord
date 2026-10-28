"""reponses_auto.py — le bot répond lui-même aux demandes des membres (27/10/2026).

Le fondateur, devant l'accueil du site où s'alignaient les « Question de X sans réponse » : « c'est le bot qui doit leur
répondre automatiquement en fonction des demandes des gens. Genre quand ils demandent de l'aide, le bot, il peut
l'aiguiller… s'ils redemandent de l'aide au même endroit, ne le respamme pas… Si ça dure un moment et qu'il redemande de
l'aide, tu lui dis « tu peux te servir de ça » s'il n'a toujours pas créé d'affiche… c'est pas là pour ça le site. C'est
à toi de répondre aux besoins des gens en fonction de ce qui existe sur le serveur… correct et juste aussi. »

CE QUE LE BOT FAIT D'UN MESSAGE (`classer`, puis `sur_message`) — d'un membre (jamais le staff), dans un salon public
(jamais un ticket, un salon du staff, ni l'entraide 🛟/🤝 où l'on répond aux cartes), qui ne répond ni ne mentionne
personne, en français ou en anglais (`LANGUES`) :
  · « aide » — une demande d'aide (« quelqu'un pour m'aider ? », « j'ai besoin d'aide », « comment on fait pour… » dans
    un jeu) : une réponse courte vers la demande d'aide du BON jeu (nommé, sinon celui du salon, sinon chacun, et un
    ticket pour le staff) — un bouton ouvre le formulaire (`entraide.BoutonNouvelle`), un autre mène à son 🛟 Help ;
  · « faq » — une question à laquelle la FAQ répond (`faq.py` : le clan, les tickets, les liens, le trade…) : sa carte ;
  · « bavardage » — « Ma pp est bien ? », « ça va ? » : rien, et ce n'est pas une tâche pour la direction ;
  · « inconnu » — une vraie question qu'il ne sait pas classer : rien sur Discord ; le site la montre (« Pas su classer »).
Jamais un salon inventé : les boutons viennent de la configuration (le post 🛟 Help, la zone d'aide installée) ; sans
endroit réel, pas de réponse.

NE JAMAIS EMBÊTER (`decider`, puis `_cadence`), chiffré :
  · une réponse par personne et par sujet ; puis plus rien pendant le cycle (`CYCLE_S`, 24 h), où qu'elle redemande ;
  · si elle redemande au moins `RAPPEL_APRES_S` (1 h) après, sans avoir créé de demande d'aide depuis : UN rappel court ;
  · une demande d'aide créée depuis (ou encore ouverte) : plus rien ;
  · une réponse par membre toutes les 10 minutes (`MEMBRE_S`), le même sujet une fois par salon toutes les 5 minutes
    (`SUJET_SALON_S`), 3 réponses au plus par salon en 10 minutes (`SALON_MAX`) : une rafale ne fait pas une rafale ;
  · le bot attend `ATTENTE_S` secondes : quelqu'un a répondu entre-temps, ou la modération a retiré le message → rien ;
  · la réponse cite le message sans notifier personne et s'efface seule (`EFFACER_S`, même après un redémarrage).
Tout est noté (`reponses_bot`, 30 jours) : le site (Le Port › Salons & questions › Réponses du bot) montre ce que le bot
a répondu, à qui, où, ce qu'il a retenu, ce qu'il n'a pas su classer — et règle les réponses par salon ou par jeu (la tête
seule écrit). Les textes sont dans le registre (« Textes & noms », famille « Réponses du bot »).
"""
from __future__ import annotations

import asyncio
import re
import time

import discord
from discord.ui import Button

import entraide
import faq
import questions
import textes
import zones
from ui_v2 import LayoutView, Palette

LANGUES = ("fr", "en")      # « Il répond seulement aux messages en français ou en anglais. »
ATTENTE_S = 4               # le temps de laisser la modération agir, ou quelqu'un répondre
CYCLE_S = 24 * 3600         # une personne, un sujet : une réponse, au plus un rappel, puis rien jusqu'au lendemain
RAPPEL_APRES_S = 3600       # le rappel : seulement si elle redemande au moins une heure après
MEMBRE_S = 600              # une réponse par membre toutes les 10 minutes
SUJET_SALON_S = 300         # le même sujet, une fois par salon toutes les 5 minutes
SALON_MAX, SALON_FENETRE_S = 3, 600   # le plafond d'un salon : 3 réponses en 10 minutes
EFFACER_S = 1800            # la réponse s'efface d'elle-même au bout de 30 minutes
JOURS = 30
LISTE_MAX = 500
CLE_CONF = "reponses_auto"
GENRES = {"reponse": "Répondu", "rappel": "Rappel", "retenue": "Retenue", "inconnu": "Pas su classer"}
RAISONS = {"deja": "déjà répondu, il y a peu", "demande": "sa demande d'aide existe déjà",
           "membre": "une réponse à lui il y a moins de 10 min", "sujet_salon": "le même sujet ici il y a moins de 5 min",
           "plafond": "le salon a eu ses 3 réponses en 10 min", "sans_salon": "aucune aide installée pour ce jeu"}
PURGES = [("réponses du bot", "DELETE FROM reponses_bot WHERE quand < ?", JOURS, "unix")]
#  Les sujets de la FAQ précis passent avant une demande d'aide (« j'ai besoin d'aide pour rejoindre le clan » : le clan) ;
#  les larges (annonces, vidéos) après tout le reste.
PRECIS = ("clan", "aide_clan", "ticket", "lien_jeu", "trade", "suggestion")
LARGES = ("annonces", "videos")

# ═══════════════════════════════════════════════════════════════════════════════
#  Classer un message (fonctions pures, sur le texte sans accents : `questions.plat`)
# ═══════════════════════════════════════════════════════════════════════════════

_QUI = (r"(?:quelqu'?un|quelqu un|qqn|qq1|qlqn|qlq|quelqun|kelkun|des gens|du monde|une personne|personne|vous|qui"
        r"|des joueurs|un joueur|un mec|un gars)")
_M_AIDER = (r"(?:m'?aider|m aider|maider|aider moi|m'?expliquer|mexpliquer|me depanner|me donner un coup de main"
            r"|me filer un coup de main|me montrer)")
AIDE = re.compile(
    r"\bbesoin d'?(?:un peu d'?|d'?un )?(?:aide|coup de main|help)\b"
    r"|\b(?:aide|aidez)[- ]?(?:moi|nous)\b"
    r"|\b" + _QUI + r"\b.{0,40}\b" + _M_AIDER + r"\b"
    r"|\b(?:dispo|disponibles?|chaud)\b.{0,25}\b(?:m'?aider|aider)\b"
    r"|\bje (?:suis|me sens) (?:bloquee?|coincee?|perdue?)\b|\bj'?(?:e )?galere\b"
    r"|\b(?:quelqu'?un|qqn|qui) (?:sait|saurait|connait) (?:comment|ou|pourquoi|quand|quel|si|faire)\b"
    r"|\bun (?:petit )?coup de main\b"
    r"|\bneed(?:s|ing)? (?:some |a little |a )?help\b|\bhelp (?:me|pls|plz|please)\b|\b(?:pls|plz|please) help\b"
    r"|\b(?:can|could|would|will) (?:someone|anyone|somebody|anybody|u|you guys|smb|sb) (?:pls |please )?help\b"
    r"|\b(?:anyone|someone|somebody|anybody) (?:free |available |online |here |around )?(?:to )?help\b"
    r"|\bwho (?:can|could|wants to) help\b|\bi'?m (?:stuck|lost)\b|\bi am (?:stuck|lost)\b|^help\b")
#  Ce qui ressemble à une demande d'aide sans en être une : l'aide refusée, l'aide offerte.
PAS_AIDE = re.compile(
    r"\b(?:pas|plus|jamais|aucun) besoin\b|\bn'?ai (?:pas|plus) besoin\b"
    r"|\b(?:je|j'?) ?(?:peux|pourrais|veux bien|vais) (?:t'?|vous |l'?|les )?(?:aider|help)\b|\bj'?peux (?:t'?|vous )?aider\b"
    r"|\bqui (?:a|aurait) besoin d'?(?:aide|un coup de main)\b"
    r"|\b(?:i|we) (?:can|could|will) help\b|\bi'?ll help\b|\b(?:anyone|who|someone) needs? (?:some )?help\b"
    r"|\bdon'?t need help\b|\bno need\b")
#  Une phrase adressée à une personne (« tu peux… », « t'as vu… ») : une conversation, pas une demande au serveur.
A_QUELQU_UN = re.compile(r"^(?:(?:salut|slt|yo|wsh|hey|cc|coucou|bonjour|bjr|re|hello|hi|eh|dis|oe|ouais)\b[\s,!.]*)?"
                         r"(?:tu|t'?es|t'?as|toi|te|ta|ton|tes|t'?aurais|tu as|t'?sais)\b")
#  « Comment on fait pour… » : une aide, quand elle concerne un jeu (son salon, son nom, ses mots).
COMMENT = re.compile(
    r"\bcomment (?:on (?:fait|fais|peut|doit|a|obtient|bat|tue|trouve|monte|gagne|debloque|recupere|farm)|je (?:fais|fait"
    r"|peux|dois|obtiens|bats|tue|trouve|monte|gagne|debloque|recupere|farm)|j'?(?:peux|dois|obtiens)|faire|faut[- ]il"
    r"|il faut|faut|ca marche|ca fonctionne|avoir|obtenir|trouver|battre|tuer|monter|gagner|debloquer|recuperer|farm(?:er)?)\b"
    r"|\b(?:ou|o) (?:on|je|j'?) (?:trouve|peux trouver|peut trouver|achete|recupere|obtiens|farm)\b"
    r"|\bhow (?:do|can|should) (?:i|we|you|u|one)\b|\bhow to\b|\bwhere (?:do|can) (?:i|we|you) (?:find|get|buy|farm)\b")
VOCAB_JEU = re.compile(
    r"\b(?:boss|farm\w*|qu[eê]tes?|quests?|niveaux?|lvl|level|xp|fruits?|iles?|islands?|armes?|weapons?|epees?|swords?"
    r"|items?|objets?|coffres?|chests?|donjons?|dungeons?|raids?|stats?|build|races?|factions?|metiers?|bateaux?|navires?"
    r"|ships?|berrys?|beli|mobs?|pnj|npc|codes?|gamepass|craft\w*|spawn|skills?|competences?|sorts?|spells?|pets?|map"
    r"|carte|zones?|grimoires?|mana|clover)\b")
#  Les autres langues, en plus des petits mots de `faq.MOTS_AUTRES`.
AUTRES = re.compile(r"[¿¡]|\b(?:hola|ayuda|ayudar|ayudame|alguien|puede|necesito|por favor|porfa|gracias|ajuda|ajudar"
                    r"|alguem|preciso|obrigad[oa]|voce|hilfe|jemand|bitte|danke|aiuto|aiutami|qualcuno|grazie|perche)\b")
_INTERROGATIF = re.compile(r"\?")


def langue_de(texte: str) -> str:
    """« fr », « en », « autre » (espagnol, portugais, allemand, italien…) ou "" si rien ne le dit."""
    bas, p = str(texte or "").lower(), questions.plat(texte)
    fr, en = len(faq.MOTS_FR.findall(bas)), len(faq.MOTS_EN.findall(bas))
    autres = len(faq.MOTS_AUTRES.findall(bas)) + len(AUTRES.findall(p))
    if autres > max(fr, en):
        return "autre"
    return "" if fr == en else ("en" if en > fr else "fr")


def _sujet(bas: str, cles) -> faq.Sujet | None:
    return next((s for s in faq.SUJETS if s.cle in cles and any(re.search(m, bas) for m in s.motifs)), None)


def _nomme_un_jeu(p: str) -> bool:
    return any(re.search(r"\b" + re.escape(m), p) for j in zones.JEUX for m in j.mots)


def classer(texte: str, jeu_connu: bool = False) -> tuple:
    """FONCTION PURE : (genre, sujet, langue) d'un message — genre « aide », « faq », « bavardage », « inconnu », ou ""
    (rien pour le bot : ni une question, ni une demande) ; sujet : « aide » ou la clé d'un sujet de la FAQ ; langue :
    « fr », « en », « autre » ou "". `jeu_connu` : le message est écrit dans le salon d'un jeu."""
    t = questions.nettoyer(texte)
    if len(t) < 4 or t[0] in "/!.$":
        return "", "", ""
    bas, p = t.lower(), questions.plat(t)
    langue = langue_de(t)
    question = len(t) >= 8 and bool(_INTERROGATIF.search(t) or questions.INTERROGATIFS.match(t))
    conversation = bool(A_QUELQU_UN.match(p))
    aide = not conversation and not PAS_AIDE.search(p) and bool(AIDE.search(p) or _sujet(bas, ("aide_jeu",)))
    if not (question or aide):
        return "", "", langue
    if langue == "autre":
        return ("inconnu" if questions.est_question(t) or aide else ""), "", langue
    if not conversation:
        s = _sujet(bas, PRECIS)
        if s is not None:
            return "faq", s.cle, langue
    if aide:
        return "aide", "aide", langue
    if conversation or questions.BAVARDAGE.search(t) or questions.SOCIAL.search(p):
        return "bavardage", "", langue
    s = _sujet(bas, LARGES)
    if s is not None:
        return "faq", s.cle, langue
    if COMMENT.search(p) and (jeu_connu or _nomme_un_jeu(p) or VOCAB_JEU.search(p)):
        return "aide", "aide", langue
    return ("inconnu" if questions.est_question(t) else ""), "", langue


def jeux_du_lieu(salon, jeux: list) -> list:
    """Les jeux du salon où l'on écrit : son forum (un post de 🌊rell-seas, de 🍀clover-rpg), sinon son nom."""
    par_forum = faq.jeux_du_salon(salon, jeux)
    if par_forum:
        return par_forum
    nom = questions.plat(getattr(salon, "name", "") or "")
    return [j for j in jeux if any(re.search(r"\b" + re.escape(m), nom) for m in j.get("mots") or ())]


def jeux_vises(texte: str, salon, jeux: list) -> list:
    """Le BON jeu d'une demande d'aide : celui qu'elle nomme, sinon celui du salon, sinon chacun."""
    return faq.jeux_nommes(questions.plat(texte), jeux) or jeux_du_lieu(salon, jeux) or list(jeux)


def decider(historique, t: float, demande=(0, 0), aide: bool = True) -> tuple:
    """FONCTION PURE — l'anti-spam d'une personne pour un sujet. `historique` : ce que le bot lui a déjà dit sur ce sujet
    pendant le cycle, [(genre, quand)] ; `demande` : (création de sa dernière demande d'aide, combien sont ouvertes).
    → (« reponse » | « rappel » | « retenue », raison)."""
    derniere, ouvertes = demande
    faites = sorted((q, g) for g, q in historique if g in ("reponse", "rappel") and t - q < CYCLE_S)
    if aide and ouvertes:
        return "retenue", "demande"
    if not faites:
        return "reponse", ""
    premiere = faites[0][0]
    if aide and derniere and derniere >= premiere:
        return "retenue", "demande"
    if any(g == "rappel" for _q, g in faites) or t - premiere < RAPPEL_APRES_S:
        return "retenue", "deja"
    return "rappel", ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Les textes (« Textes & noms », famille « Réponses du bot »)
# ═══════════════════════════════════════════════════════════════════════════════

_PARTIE = "L'aide et les rappels"
TEXTES = (
    ("reponses.aide.titre", "🛟 Besoin d'aide ?", "🛟 Need help?", "Le titre de la réponse à une demande d'aide", ()),
    ("reponses.aide.texte",
     "Pour de l'aide sur {jeu}, fais une demande d'aide : elle s'affiche dans 🛟 Help et des joueurs viennent t'aider. "
     "Tu peux aussi reformuler ta question ici.",
     "For help on {jeu}, post a help request: it shows up in 🛟 Help and players come to help you. You can also rephrase "
     "your question here.", "La réponse à une demande d'aide", (("jeu", "le jeu (ou les jeux)"),)),
    ("reponses.aide.ticket", "Pour le staff : un ticket.", "For the staff: a ticket.",
     "Ajouté quand le jeu n'est pas connu (un bouton mène aux tickets)", ()),
    ("reponses.rappel", "Toujours besoin d'aide sur {jeu} ? Tu peux te servir de ça : une demande d'aide, et des joueurs "
                        "viennent t'aider.",
     "Still need help on {jeu}? You can use this: a help request, and players come to help you.",
     "Le rappel, s'il redemande plus tard sans avoir fait de demande", (("jeu", "le jeu (ou les jeux)"),)),
    ("reponses.rappel_faq", "Pour rappel, c'est ici :", "As a reminder, it's here:",
     "Le rappel d'une question fréquente déjà répondue", ()),
    ("reponses.bouton", "Demander de l'aide", "Ask for help", "Le bouton qui ouvre la demande d'aide", ()),
    ("reponses.pied", "Réponse automatique · elle s'efface d'elle-même", "Automatic answer · it removes itself",
     "La petite ligne sous chaque réponse", ()),
)
for _n, (_cle, _fr, _en, _titre, _vars) in enumerate(TEXTES):
    for _l, _defaut in (("fr", _fr), ("en", _en)):
        textes.declarer(f"{_cle}.{_l}", _defaut, groupe=faq.GROUPE_TEXTES, partie=_PARTIE, ordre=10 + 2 * _n + (_l == "en"),
                        titre=f"{_titre} · {'anglais' if _l == 'en' else 'français'}", max_=400 if "bouton" not in _cle
                        else 60, lignes="bouton" not in _cle and "titre" not in _cle and "pied" not in _cle,
                        variables=_vars)


def _t(gid, cle: str, **valeurs) -> str:
    return textes.texte_cache(int(gid or 0), cle, **valeurs)


# ═══════════════════════════════════════════════════════════════════════════════
#  Branchement
# ═══════════════════════════════════════════════════════════════════════════════

_get_db = _cfg = _db_set = _destinations = _est_staff = _langue = None
_exclus = _est_ticket = _effacer_plus_tard = None
_log = print
_verrous: dict = {}
_en_vol: dict = {}       # message → (serveur, membre, salon, sujet, quand) : décidé, pas encore noté
_attente: dict = {}      # message → {serveur, salon, auteur, traite} : le bot attend avant de répondre


def setup(*, get_db, cfg, db_set, destinations, est_staff, langue=None, exclus=None, est_ticket=None,
          effacer_plus_tard=None, log=None) -> None:
    """`destinations(g, c)` → les endroits réels (`bot._faq_destinations`) ; `est_staff(g, membre, c)` → bool ;
    `langue(membre)` (async) → « fr » ou « en » ; `exclus(g, c)` → les salons de l'entraide (on y répond aux cartes) ;
    `est_ticket(salon)` (async) → bool ; `effacer_plus_tard(message, secondes)` (async) → l'effacement qui survit à un
    redémarrage."""
    global _get_db, _cfg, _db_set, _destinations, _est_staff, _langue, _exclus, _est_ticket, _effacer_plus_tard, _log
    _get_db, _cfg, _db_set, _destinations, _est_staff = get_db, cfg, db_set, destinations, est_staff
    _langue, _exclus, _est_ticket, _effacer_plus_tard = langue, exclus, est_ticket, effacer_plus_tard
    _log = log or print
    _en_vol.clear()
    _attente.clear()


def pret() -> bool:
    return _get_db is not None


async def init_db() -> None:
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS reponses_bot (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
            " salon_id INTEGER NOT NULL, message_id INTEGER NOT NULL, auteur_id INTEGER NOT NULL,"
            " texte TEXT NOT NULL DEFAULT '', quand INTEGER NOT NULL, genre TEXT NOT NULL, sujet TEXT NOT NULL DEFAULT '',"
            " jeux TEXT NOT NULL DEFAULT '', langue TEXT NOT NULL DEFAULT '', raison TEXT NOT NULL DEFAULT '',"
            " reponse_id INTEGER NOT NULL DEFAULT 0, UNIQUE(guild_id, message_id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_reponses_membre ON reponses_bot(guild_id, auteur_id, sujet, quand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_reponses_salon ON reponses_bot(guild_id, salon_id, quand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_reponses_quand ON reponses_bot(guild_id, quand)")
        await db.commit()


def _verrou(gid):
    return _verrous.setdefault(gid, asyncio.Lock())


def _staff(g, m, c) -> bool:
    try:
        return bool(_est_staff(g, m, c))
    except (AttributeError, TypeError, ValueError) as ex:
        _log("[REPONSES][E3] rôle du membre illisible")
        _log(f"[REPONSES][E3:DETAIL] {type(ex).__name__} {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Les réglages (par jeu, par salon) — la tête, sur le site
# ═══════════════════════════════════════════════════════════════════════════════

def lire_reglages(c: dict) -> dict:
    r = (c or {}).get(CLE_CONF) or {}
    return {"actif": r.get("actif", True) is not False, "jeux": dict(r.get("jeux") or {}),
            "salons": dict(r.get("salons") or {}), "versions": dict(r.get("versions") or {})}


def coupe_ici(regl: dict, salon, jeux_lieu: list) -> bool:
    """Les réponses sont-elles coupées ici : partout, pour ce salon (ou son forum), ou pour le jeu du salon ?"""
    if not regl["actif"]:
        return True
    ids = {str(getattr(salon, "id", 0)), str(getattr(salon, "parent_id", 0) or 0)}
    return any(regl["salons"].get(i) is False for i in ids) or any(regl["jeux"].get(j["cle"]) is False for j in jeux_lieu)


def _jeux_aide(c: dict, cibles: list, regl: dict) -> list:
    """Les jeux visés dont l'aide EXISTE : le formulaire (la zone d'aide installée) et/ou le post 🛟 Help — jamais un
    salon inventé. Un jeu coupé sur le site n'y est pas."""
    installes = (c.get("rs_salons") or {}) if c.get("rs_actif") else {}
    par_cle = {j.cle: j for j in zones.JEUX}
    out = []
    for j in cibles:
        if regl["jeux"].get(j["cle"]) is False:
            continue
        jeu = par_cle.get(j["cle"])
        zone = entraide.ZONES.get(jeu.zones[0]) if jeu is not None and jeu.zones else None
        formulaire = zone.cle if zone is not None and installes.get(zone.salon) else ""
        if formulaire or j.get("help"):
            out.append(dict(j, zone=formulaire))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Les réponses
# ═══════════════════════════════════════════════════════════════════════════════

def vue_aide(gid, jeux: list, langue: str, rappel: bool = False, ticket: str = "") -> LayoutView:
    """La réponse à une demande d'aide (ou son rappel) : le texte, puis par jeu le bouton qui ouvre la demande d'aide et
    celui qui mène à son 🛟 Help ; un ticket pour le staff quand le jeu n'est pas connu. Cinq boutons au plus."""
    lg = "en" if langue == "en" else "fr"
    noms = (" or " if lg == "en" else " ou ").join(j["nom"] for j in jeux)
    corps = _t(gid, f"reponses.{'rappel' if rappel else 'aide.texte'}.{lg}", jeu=noms)
    plusieurs = len(jeux) > 1
    if ticket and plusieurs and not rappel:
        corps += " " + _t(gid, f"reponses.aide.ticket.{lg}")
    libelle = _t(gid, f"reponses.bouton.{lg}")
    boutons = []
    for j in jeux:
        if j.get("zone"):
            b = entraide.BoutonNouvelle(j["zone"])
            b.item.label = (f"{libelle} · {j['nom']}" if plusieurs else libelle)[:80]
            boutons.append(b)
        if j.get("help"):
            boutons.append(Button(label=f"{j.get('emoji') or '🛟'} Help · {j['nom']}"[:80], url=j["help"]))
    if ticket and plusieurs and not rappel:
        boutons.append(Button(label="🎫 Ticket", url=ticket))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay(f"### {_t(gid, f'reponses.aide.titre.{lg}')}\n{corps}"),
        discord.ui.ActionRow(*boutons[:5]),
        discord.ui.TextDisplay("-# " + _t(gid, f"reponses.pied.{lg}")), accent_color=Palette.INFO))
    return v


def _adresse_a_quelqu_un(msg, g, c) -> bool:
    """Une réponse à une personne, ou une mention d'une personne : une conversation (« déjà traité par quelqu'un »)."""
    auteur = msg.author
    ref = getattr(msg, "reference", None)
    if ref is not None and getattr(ref, "message_id", None):
        cible = getattr(getattr(ref, "resolved", None), "author", None)
        if cible is None or (not getattr(cible, "bot", False) and cible.id != auteur.id):
            return True
    return any(not getattr(u, "bot", False) and u.id != auteur.id for u in getattr(msg, "mentions", []) or [])


def _observer(msg, staff: bool) -> None:
    """Pendant que le bot attend : une réponse au message, une mention de son auteur, un fil ouvert dessus, ou le staff
    qui parle dans le salon — quelqu'un l'a traité, le bot se taira."""
    if not _attente:
        return
    g, ch = msg.guild.id, msg.channel
    ref = getattr(getattr(msg, "reference", None), "message_id", None)
    mentions = set(getattr(msg, "raw_mentions", []) or [])
    for mid, e in _attente.items():
        if e["serveur"] != g or msg.author.id == e["auteur"]:
            continue
        if ref == mid or ch.id == mid or (e["salon"] == ch.id and (staff or e["auteur"] in mentions)):
            e["traite"] = True


async def _historique(gid: int, uid: int, sujet: str, depuis: float) -> list:
    async with _get_db() as db:
        async with db.execute("SELECT genre, quand FROM reponses_bot WHERE guild_id=? AND auteur_id=? AND sujet=?"
                              " AND quand>=? AND genre IN ('reponse', 'rappel')", (gid, uid, sujet, int(depuis))) as cur:
            return [(r[0], r[1]) for r in await cur.fetchall()]


async def _deja_note(gid: int, mid: int) -> bool:
    async with _get_db() as db:
        async with db.execute("SELECT 1 FROM reponses_bot WHERE guild_id=? AND message_id=?", (gid, mid)) as cur:
            return await cur.fetchone() is not None


async def _cadence(gid: int, uid: int, sid: int, sujet: str, t: float) -> str:
    """Les cadences : par membre, par sujet dans le salon, le plafond du salon — sur ce qui est noté ET ce qui part."""
    async with _get_db() as db:
        async with db.execute("SELECT auteur_id, salon_id, sujet, quand FROM reponses_bot WHERE guild_id=? AND"
                              " genre IN ('reponse', 'rappel') AND quand>=? AND (auteur_id=? OR salon_id=?)",
                              (gid, int(t - max(MEMBRE_S, SALON_FENETRE_S)), uid, sid)) as cur:
            faites = [tuple(r) for r in await cur.fetchall()]
    faites += [(u, s, su, q) for g_, u, s, su, q in _en_vol.values() if g_ == gid]
    if any(u == uid and t - q < MEMBRE_S for u, _s, _su, q in faites):
        return "membre"
    if any(s == sid and su == sujet and t - q < SUJET_SALON_S for _u, s, su, q in faites):
        return "sujet_salon"
    if sum(1 for _u, s, _su, q in faites if s == sid and t - q < SALON_FENETRE_S) >= SALON_MAX:
        return "plafond"
    return ""


async def _noter(g, msg, t: float, genre: str, sujet: str, jeux, langue: str, raison: str = "",
                 reponse_id: int = 0) -> None:
    texte = questions.nettoyer(getattr(msg, "content", "") or "")[:300]
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO reponses_bot (guild_id, salon_id, message_id, auteur_id, texte, quand,"
                         " genre, sujet, jeux, langue, raison, reponse_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (g.id, msg.channel.id, msg.id, msg.author.id, texte, int(t), genre, sujet,
                          ",".join(j["cle"] for j in jeux), langue, raison, int(reponse_id or 0)))
        await db.commit()
    if questions._get_db is not None:   # la question n'attend plus personne (le veilleur s'aligne)
        await questions.marquer_bot(g.id, msg.id, msg.author.id, msg.channel.id, t)


async def sur_message(msg, c=None, maintenant: float | None = None, attente: float | None = None) -> str:
    """Rend ce que le bot a fait : « reponse », « rappel », « retenue », « traite » (quelqu'un l'a fait avant lui) ou ""."""
    g, m, ch = getattr(msg, "guild", None), getattr(msg, "author", None), getattr(msg, "channel", None)
    if g is None or m is None or ch is None or getattr(m, "bot", False) or getattr(msg, "webhook_id", None) \
            or _get_db is None:
        return ""
    c = c if c is not None else await _cfg(g.id)
    staff = _staff(g, m, c)
    _observer(msg, staff)
    if staff:
        return ""
    texte = getattr(msg, "content", "") or ""
    liens = _destinations(g, c) or {}
    jeux = list(liens.get("jeux") or [])
    lieu = jeux_du_lieu(ch, jeux)
    genre, sujet, langue = classer(texte, jeu_connu=bool(lieu))
    if genre not in ("aide", "faq") or (langue and langue not in LANGUES):
        return ""
    if not questions.salon_public(ch) or _adresse_a_quelqu_un(msg, g, c):
        return ""
    ici = {ch.id, getattr(ch, "parent_id", 0) or 0} - {0}
    if _exclus is not None and ici & set(_exclus(g, c) or ()):
        return ""
    if _est_ticket is not None and await _est_ticket(ch):
        return ""
    regl = lire_reglages(c)
    if coupe_ici(regl, ch, lieu):
        return ""
    if not langue:   # rien dans le message ne dit sa langue : celle du membre
        langue = "fr"
        if _langue is not None:
            langue = "en" if await _langue(m) == "en" else "fr"
    t = maintenant or time.time()
    vises, carte = [], None
    if genre == "aide":
        vises = _jeux_aide(c, jeux_vises(texte, ch, jeux), regl)
    else:
        s = next(x for x in faq.SUJETS if x.cle == sujet)
        carte = faq.reponse(s, questions.nettoyer(texte).lower(), ch, liens, langue, gid=g.id)
        if carte is None:   # aucun endroit connu pour ce sujet : jamais un bouton qui ment
            return ""
    async with _verrou(g.id):
        if msg.id in _en_vol or await _deja_note(g.id, msg.id):
            return ""
        if genre == "aide" and not vises:
            await _noter(g, msg, t, "retenue", sujet, [], langue, "sans_salon")
            return "retenue"
        historique = await _historique(g.id, m.id, sujet, t - CYCLE_S)
        demande = await entraide.demandes_aide(g.id, m.id) if genre == "aide" else (0, 0)
        geste, raison = decider(historique, t, demande, aide=genre == "aide")
        if geste != "retenue":
            raison = await _cadence(g.id, m.id, ch.id, sujet, t)
            geste = "retenue" if raison else geste
        if geste == "retenue":
            await _noter(g, msg, t, "retenue", sujet, vises, langue, raison)
            return "retenue"
        _en_vol[msg.id] = (g.id, m.id, ch.id, sujet, t)
    try:
        _attente[msg.id] = {"serveur": g.id, "salon": ch.id, "auteur": m.id, "traite": False}
        await asyncio.sleep(ATTENTE_S if attente is None else attente)
        if _attente[msg.id]["traite"]:
            return "traite"
        rappel = geste == "rappel"
        if genre == "aide":
            vue = vue_aide(g.id, vises, langue, rappel=rappel, ticket=liens.get("ticket") or "")
        else:
            titre, corps, boutons = carte
            if rappel:
                corps = _t(g.id, f"reponses.rappel_faq.{langue}")
            vue = faq.vue_reponse(titre, corps, boutons, pied=_t(g.id, f"reponses.pied.{langue}"))
        try:
            rep = await msg.reply(view=vue, mention_author=False, allowed_mentions=discord.AllowedMentions.none(),
                                  delete_after=EFFACER_S)
        except discord.NotFound:
            return ""   # le message a été retiré entre-temps (la modération) : rien à dire
        except discord.HTTPException as ex:
            if getattr(ex, "code", 0) in (10008, 50035):   # message retiré : la réponse ne peut plus le citer
                return ""
            _log("[REPONSES][E1] réponse non posée")
            _log(f"[REPONSES][E1:DETAIL] sujet={sujet} {type(ex).__name__} {ex}")
            return ""
        if rep is not None and _effacer_plus_tard is not None:
            try:
                await _effacer_plus_tard(rep, EFFACER_S)
            except Exception as ex:   # la réponse est posée ; seul l'effacement après un redémarrage manque : dit
                _log("[REPONSES][E2] effacement différé non noté")
                _log(f"[REPONSES][E2:DETAIL] {type(ex).__name__} {ex}")
        await _noter(g, msg, t, geste, sujet, vises, langue, "", getattr(rep, "id", 0))
        return geste
    finally:
        _en_vol.pop(msg.id, None)
        _attente.pop(msg.id, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le site : la surveillance (lecture) et les réglages (la tête)
# ═══════════════════════════════════════════════════════════════════════════════

def _personne(g, uid) -> dict:
    m = g.get_member(int(uid or 0))
    if m is None:
        return {"id": str(uid), "nom": "", "pseudo": "", "avatar": ""}
    avatar = getattr(getattr(m, "display_avatar", None), "url", "") or ""
    return {"id": str(m.id), "nom": str(m.display_name), "pseudo": str(getattr(m, "name", "") or ""), "avatar": str(avatar)}


def _nom_salon(g, sid) -> str:
    ch = g.get_channel_or_thread(int(sid or 0))
    return f"#{ch.name}" if ch is not None else "#salon supprimé"


def _libelle(sujet: str, jeux: str) -> str:
    if sujet == "aide":
        noms = {j.cle: j.nom for j in zones.JEUX}
        return "Aide · " + (" · ".join(noms.get(k, k) for k in jeux.split(",") if k) or "aucun jeu")
    s = next((x for x in faq.SUJETS if x.cle == sujet), None)
    return s.titre_fr if s is not None else sujet


def _salons_du_site(g, c: dict, regl: dict) -> list:
    """Les salons où les membres écrivent (et ceux déjà réglés) : leur réglage, leur version."""
    v, vus, out = regl["versions"], set(), []
    exclus = set(_exclus(g, c) or ()) if _exclus is not None else set()

    def ajouter(sid, nom, jeu=""):
        if not sid or sid in vus or sid in exclus:
            return
        vus.add(sid)
        out.append({"id": str(sid), "nom": nom, "jeu": jeu, "actif": regl["salons"].get(str(sid)) is not False,
                    "version": int(v.get(f"salon:{sid}", 0) or 0)})
    for ch in getattr(g, "text_channels", []) or []:
        if questions.salon_public(ch) and not str(ch.name).lower().startswith(("ticket-", "🎫")):
            ajouter(ch.id, f"#{ch.name}")
    posts = c.get("zones_posts") or {}
    for j in zones.JEUX:
        pid = int((posts.get(j.chat) or {}).get("id", 0) or 0)
        titre = next((x[1] for x in j.posts if x[0] == j.chat), j.nom)
        ajouter(pid, _nom_salon(g, pid) if g.get_channel_or_thread(pid) is not None else f"#{titre}", j.cle)
    for sid in regl["salons"]:
        if str(sid).isdigit():
            ajouter(int(sid), _nom_salon(g, sid))
    return out[:60]


def _reglages_site(g, c: dict) -> dict:
    regl = lire_reglages(c)
    v = regl["versions"]
    return {"actif": regl["actif"], "version": int(v.get("tout", 0) or 0),
            "jeux": [{"cle": j.cle, "nom": j.nom, "actif": regl["jeux"].get(j.cle) is not False,
                      "version": int(v.get(f"jeu:{j.cle}", 0) or 0)} for j in zones.JEUX],
            "salons": _salons_du_site(g, c, regl)}


async def surveillance(g, c: dict, maintenant: float | None = None) -> dict:
    """Ce que le bot a répondu, retenu, et ce qu'il n'a pas su classer (30 jours) ; ses chiffres sur 7 jours ; ses
    réglages ; ses règles."""
    t = maintenant or time.time()
    async with _get_db() as db:
        async with db.execute("SELECT id, salon_id, message_id, auteur_id, texte, quand, genre, sujet, jeux, langue,"
                              " raison, reponse_id FROM reponses_bot WHERE guild_id=? AND quand>=? ORDER BY quand DESC"
                              " LIMIT ?", (g.id, int(t - JOURS * 86400), LISTE_MAX)) as cur:
            rows = await cur.fetchall()
    liste = []
    for rid, sid, mid, uid, texte, quand, genre, sujet, jeux, langue, raison, rep in rows:
        liste.append({"id": f"r{rid}", "membre": _personne(g, uid), "salon": _nom_salon(g, sid),
                      "message": f"https://discord.com/channels/{g.id}/{sid}/{mid}", "texte": texte, "quand": quand,
                      "genre": genre, "sujet": sujet, "libelle": _libelle(sujet, jeux), "langue": langue,
                      "raison": RAISONS.get(raison, ""),
                      "reponse": f"https://discord.com/channels/{g.id}/{sid}/{rep}" if rep else ""})
    if questions._get_db is not None:
        for q in (await questions.lister(g.id, t))["liste"]:
            if q["statut"] in ("bot", "ignoree") or classer(q["texte"])[0] != "inconnu":
                continue
            liste.append({"id": f"q{q['id']}", "membre": _personne(g, q["auteur_id"]), "salon": _nom_salon(g, q["salon_id"]),
                          "message": q["message"], "texte": q["texte"], "quand": q["quand"], "genre": "inconnu",
                          "sujet": "", "libelle": "", "langue": langue_de(q["texte"]),
                          "raison": "répondue par un membre" if q["statut"] in ("repondue", "resolue") and not q["par_staff"]
                          else "répondue par le staff" if q["par_staff"] else "", "reponse": q["lien"] or ""})
    liste.sort(key=lambda x: -int(x["quand"] or 0))
    semaine = [x for x in liste if t - int(x["quand"] or 0) <= 7 * 86400]
    stats = {f"{k}_7": sum(1 for x in semaine if x["genre"] == k) for k in ("reponse", "rappel", "retenue", "inconnu")}
    return {"liste": liste[:LISTE_MAX], "stats": stats, "reglages": _reglages_site(g, c),
            "regles": {"cycle_h": CYCLE_S // 3600, "rappel_h": RAPPEL_APRES_S // 3600, "membre_min": MEMBRE_S // 60,
                       "salon_max": SALON_MAX, "salon_min": SALON_FENETRE_S // 60, "effacer_min": EFFACER_S // 60}}


async def regler(g, auteur, corps) -> tuple:
    """`{cible: "tout" | "jeu:<clé>" | "salon:<id>", actif: bool, version?}` : les réponses actives ou coupées là.
    Une version qui n'est plus celle du serveur → 409 (rejoué hors ligne après un autre changement)."""
    corps = corps if isinstance(corps, dict) else {}
    cible, actif, version = str(corps.get("cible") or ""), corps.get("actif"), corps.get("version")
    if not isinstance(actif, bool):
        return 400, {"erreur": "« actif » : vrai ou faux."}
    jeux = {j.cle: j.nom for j in zones.JEUX}
    if cible == "tout":
        nom = "partout"
    elif cible.startswith("jeu:") and cible[4:] in jeux:
        nom = f"pour {jeux[cible[4:]]}"
    elif cible.startswith("salon:") and cible[6:].isdigit() and 0 < len(cible[6:]) <= 20:
        nom = f"dans {_nom_salon(g, cible[6:])}"
    else:
        return 400, {"erreur": "Réglage inconnu."}
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        return 400, {"erreur": "« version » : un nombre."}
    c = await _cfg(g.id)
    conf = dict(c.get(CLE_CONF) or {})
    versions = dict(conf.get("versions") or {})
    cle_v = cible if cible != "tout" else "tout"
    if version is not None and version != int(versions.get(cle_v, 0) or 0):
        return 409, {"conflit": True, "erreur": "Ce réglage a changé entre-temps.", "actuelle": _reglages_site(g, c)}
    if cible == "tout":
        conf["actif"] = actif
    elif cible.startswith("jeu:"):
        conf["jeux"] = dict(conf.get("jeux") or {}, **{cible[4:]: actif})
    else:
        conf["salons"] = dict(conf.get("salons") or {}, **{cible[6:]: actif})
    versions[cle_v] = int(versions.get(cle_v, 0) or 0) + 1
    conf["versions"] = versions
    await _db_set(g.id, CLE_CONF, conf)
    c = await _cfg(g.id)
    etat = "actives" if actif else "coupées"
    return 200, {"ok": True, "reglages": _reglages_site(g, c), "message": f"Réponses du bot {etat} {nom}.",
                 "_journal": f"Réponses du bot {etat} {nom}"}


async def _r_lire(g, auteur, requete, corps):
    return 200, await surveillance(g, await _cfg(g.id))


async def _r_regler(g, auteur, requete, corps):
    return await regler(g, auteur, corps)


ROUTES_SITE = {
    "reponses": {"methode": "GET", "fn": _r_lire, "corps_max": 0},
    "reponses/reglages": {"methode": "POST", "fn": _r_regler, "ecriture": True, "hors_ligne": True, "corps_max": 1024},
}
