"""faq.py — les réponses toutes faites (22/10/2026).

Demandé par le fondateur : « les gens qui posent des questions — comment on fait pour rejoindre le
clan, pour créer un ticket staff, pour venir dans l'équipage — ça les renvoie dans le système de
tickets… comment on peut demander de l'aide pour le clan, faire du trading, faire des suggestions…
ça les renvoie au propre vers des salons, avec des réponses ultra bien faites ».

Dans un salon public (jamais un ticket ni un salon du staff), une vraie question
(`questions.est_question`) sur un de ces sujets reçoit en réponse une carte courte, dans la langue
de la question, avec un bouton qui mène au bon endroit. Une fois par membre et par sujet par
demi-heure ; une fois par salon et par sujet toutes les 5 minutes (deux membres qui demandent la
même chose : une carte). La carte s'efface d'elle-même au bout de 30 minutes : le chat reste propre.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import discord
from discord.ui import Button

import questions
from ui_v2 import LayoutView, Palette

MEMBRE_S = 1800          # le même sujet pour le même membre : une fois par demi-heure
SALON_S = 300            # le même sujet dans le même salon : une fois toutes les 5 minutes
EFFACER_S = 1800         # la carte part d'elle-même


@dataclass(frozen=True)
class Sujet:
    cle: str
    emoji: str
    titre_fr: str
    titre_en: str
    texte_fr: str
    texte_en: str
    vers: str            # la destination : « ticket », « crews », « trade », « suggestions », « help »
    motifs: tuple        # une question qui en parle (français ou anglais)


#  Du plus précis au plus général : le premier sujet reconnu répond.
SUJETS = (
    Sujet("clan", "🏴‍☠️", "Rejoindre le clan", "Join the clan",
          "Pour entrer dans le clan GoRP, ouvre un ticket de candidature{type} : le staff du clan te répond en "
          "privé.",
          "To join the GoRP clan, open an application ticket{type}: the clan staff answers privately.",
          "ticket",
          (r"\b(rejoindre|int[ée]grer|entrer dans|faire partie d[ue]|candidat\w*|postuler|recrut\w*)\b.{0,40}"
           r"\b(clan|gorp\w*|team|guilde)\b",
           r"\b(clan|gorp\w*)\b.{0,40}\b(rejoindre|recrut\w*|candidat\w*|postuler)\b",
           r"\b(join|apply|get into|be part of)\b.{0,40}\b(clan|gorp\w*|team|guild)\b")),
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
          (r"\b(cr[ée]er|ouvrir|faire|mettre|open|create|make)\b.{0,20}\btickets?\b",
           r"\b(contacter|parler (au|à|a)|joindre|[ée]crire (au|à|a))\b.{0,20}\b(staff|modo\w*|mod[ée]rat\w*|admin\w*)\b",
           r"\b(contact|reach|talk to)\b.{0,20}\b(staff|mods?|admins?)\b")),
    Sujet("equipage", "⚓", "Les équipages", "Crews",
          "Dans ⚓ Crews : publie ton équipage (Pirates ou Marine) ou clique « Rejoindre » sur une carte — le "
          "capitaine est prévenu.",
          "In ⚓ Crews: post your crew (Pirates or Marine) or click “Join” on a card — the captain is notified.",
          "crews",
          (r"\b[ée]quipages?\b", r"\bcrews?\b")),
    Sujet("trade", "🤝", "Échanger", "Trading",
          "Dans 🤝 Trade : « Proposer » ta carte. Avec un inconnu, ne donne jamais en premier : appelle un "
          "middleman.",
          "In 🤝 Trade: “Post a trade”. With a stranger, never give first: call a middleman.",
          "trade",
          (r"\b(trad(e|er|es|ing)|[ée]chang(er|e|es|ent)|middleman|swap)\b",)),
    Sujet("suggestion", "💡", "Proposer une idée", "Suggest an idea",
          "Dans 💡 Suggestions : bouton « Proposer », tout le monde vote, le staff répond.",
          "In 💡 Suggestions: “Suggest” button, everyone votes, the staff answers.",
          "suggestions",
          (r"\b(suggestions?|suggest|propos(er|e) (une |des )?(id[ée]es?|am[ée]liorations?))\b",)),
    Sujet("aide_jeu", "🛟", "De l'aide en jeu", "Help in game",
          "Dans 🛟 Help : choisis Aide, Boss, Farm ou Chill, remplis — des joueurs viennent t'aider.",
          "In 🛟 Help: pick Help, Boss, Farm or Chill, fill in — players come to help you.",
          "help",
          (r"\b(besoin d'aide|aide[rz]? (moi|pour|sur)|qui (peut|veut) m'aider)\b",
           r"\b(need help|help me|can someone help|who can help)\b",
           r"\b(aide|aider|help|besoin)\b.{0,30}\b(boss|farm\w*|qu[eê]tes?|quests?)\b",
           r"\b(boss|farm\w*|qu[eê]tes?|quests?)\b.{0,30}\b(aide|aider|help)\b")),
)
BOUTONS = {"ticket": ("Ouvrir un ticket", "Open a ticket"), "crews": ("Équipages", "Crews"),
           "trade": ("Trade", "Trade"), "suggestions": ("Suggestions", "Suggestions"), "help": ("Help", "Help")}
#  La langue de la question : ses petits mots (« comment », « je »… ou « how », « the »…).
MOTS_FR = re.compile(r"\b(comment|je|j|tu|on|le|la|les|des|pour|est|un|une|du|faire|quoi|o[uù]|qui|peut)\b")
MOTS_EN = re.compile(r"\b(how|what|where|can|could|the|is|do|does|i|you|to|an|who|which)\b")

_cfg = _langue = _est_staff = _destinations = None
_log = print
_membres: dict = {}
_salons: dict = {}


def setup(*, cfg, destinations, est_staff, langue=None, log=None):
    """`destinations(g, c)` → {« ticket » | « crews » | … : lien, « type_clan » : nom du type de ticket
    du clan} ; `est_staff(g, membre, c)` → bool ; `langue(membre)` (async) → « fr » ou « en »."""
    global _cfg, _destinations, _est_staff, _langue, _log
    _cfg, _destinations, _est_staff, _langue = cfg, destinations, est_staff, langue
    _log = log or print


def langue_du_texte(t: str) -> str:
    """« fr », « en », ou "" si rien ne le dit."""
    fr, en = len(MOTS_FR.findall(t)), len(MOTS_EN.findall(t))
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


def vue(s: Sujet, langue: str, lien: str, type_clan: str = "") -> LayoutView:
    en = langue == "en"
    precision = f" (type « {type_clan} »)" if type_clan and s.cle in ("clan", "aide_clan") else ""
    texte = (s.texte_en if en else s.texte_fr).format(type=precision)
    libelle = BOUTONS.get(s.vers, ("Ouvrir", "Open"))[1 if en else 0]
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay(f"### {s.emoji} {s.titre_en if en else s.titre_fr}\n{texte}"),
        discord.ui.ActionRow(Button(label=libelle, url=lien)),
        discord.ui.TextDisplay("-# Réponse automatique · Automatic answer"), accent_color=Palette.INFO))
    return v


def _libre(cle: tuple, delai: float, registre: dict, t: float) -> bool:
    if t - registre.get(cle, -1e9) < delai:
        return False
    registre[cle] = t
    if len(registre) > 2000:
        for k in [k for k, v in registre.items() if t - v > delai]:
            registre.pop(k, None)
    return True


async def sur_message(msg, maintenant: float | None = None) -> bool:
    """Rend True si une carte a été posée."""
    g, m = getattr(msg, "guild", None), getattr(msg, "author", None)
    if g is None or m is None or getattr(m, "bot", False) or getattr(msg, "webhook_id", None) or _cfg is None:
        return False
    s, langue_q = reconnaitre(getattr(msg, "content", "") or "")
    if s is None or not questions.salon_public(msg.channel):
        return False
    c = await _cfg(g.id)
    if _est_staff(g, m, c):
        return False
    t = maintenant or time.monotonic()
    if not _libre((g.id, msg.channel.id, s.cle), SALON_S, _salons, t):
        return False
    if not _libre((g.id, m.id, s.cle), MEMBRE_S, _membres, t):
        return False
    liens = _destinations(g, c) or {}
    lien = liens.get(s.vers)
    if not lien:
        return False
    langue = langue_q or "fr"
    if not langue_q and _langue is not None:  # rien dans la question : sa langue à lui
        try:
            langue = "en" if await _langue(m) == "en" else "fr"
        except Exception as ex:
            _log(f"[FAQ:DETAIL] langue {type(ex).__name__} {ex}")
    try:
        await msg.reply(view=vue(s, langue, lien, liens.get("type_clan", "")), mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(), delete_after=EFFACER_S)
    except discord.HTTPException as ex:
        _log("[FAQ][E1] réponse non posée")
        _log(f"[FAQ][E1:DETAIL] sujet={s.cle} {type(ex).__name__} {ex}")
        return False
    return True
