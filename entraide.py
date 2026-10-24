"""entraide.py — l'entraide des jeux : Rell Seas (22/10/2026), Clover RPG (24/10/2026).

Demandé par le fondateur : « demander de l'aide, faire du trading (s'échanger des fruits), des demandes
de farm, de boss, de chill… ultra compact… des joueurs qualifiés avec des rôles, plusieurs sous-rôles
en fonction des zones : ils pourront certifier que l'aide a bien été faite et clôturer la demande…
un nettoyage automatique. » Puis : « trop de salons… que ça ne se chevauche pas » et « le serveur est
international, mais aussi français… une fois que le trading est bon des deux côtés, les gens peuvent
clôturer leur propre ticket… quand les demandes sont clôturées, le fil se ferme aussi… un vrai
système de nettoyage ultra propre… nous, on a toutes les informations au propre ».

Deux forums, dans la zone Rell Seas (`zones.py`), quel que soit le nombre de demandes :
  🛟 help  — aide, boss, farm, chill (une étiquette par type, une par statut) ;
  🤝 trade — les échanges, avec middleman.
Tout ce qui est public est en français · anglais ; formulaires et réponses parlent la langue du
membre (sa préférence, sinon celle de son Discord). Une demande = un fil, jamais un salon. Le post
épinglé ouvre le formulaire du type ; la carte montre l'auteur, sa demande, qui vient aider.
L'auteur clôt lui-même (« c'est réglé », « échange conclu », ou il annule) ; un guide du type (son
rôle) certifie l'aide — le middleman pour un échange ; le staff peut tout. À la clôture, le fil
se verrouille, son historique est enregistré pour le site, puis il disparaît au passage suivant
(moins de 5 minutes). Une demande sans activité se ferme d'elle-même.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import discord
from discord.ui import Button, RoleSelect, Select, UserSelect

import config_salons
import visuels
from ui_v2 import LayoutView, Palette


# ═══════════════════════════════════════════════════════════════════════════════
#  Textes (français, anglais)
# ═══════════════════════════════════════════════════════════════════════════════

TEXTES = {
    "form.titre": {"fr": "{emoji} {nom} · nouvelle demande", "en": "{emoji} {nom} · new request"},
    "facultatif": {"fr": "Facultatif", "en": "Optional"},
    "sur_serveur": {"fr": "L'entraide se fait sur le serveur.", "en": "Help requests happen on the server."},
    "zone_fermee": {"fr": "Cette zone est fermée pour le moment.", "en": "This area is closed for now."},
    "exclu": {"fr": "Pas de demande pendant une exclusion temporaire.", "en": "No requests while you are timed out."},
    "attendre": {"fr": "Attends deux minutes entre deux demandes.", "en": "Wait two minutes between two requests."},
    "deja_ici": {"fr": "Tu as déjà une demande ouverte ici. Clôture-la avant d'en publier une autre.{lien}",
                 "en": "You already have an open request here. Close it before posting another one.{lien}"},
    "trop": {"fr": "Tu as déjà {n} demandes ouvertes. Clôtures-en une d'abord.",
             "en": "You already have {n} open requests. Close one first."},
    "obligatoire": {"fr": "« {champ} » est obligatoire.", "en": "“{champ}” is required."},
    "trop_long": {"fr": "« {champ} » est trop long.", "en": "“{champ}” is too long."},
    "corriger": {"fr": "Corriger", "en": "Edit"},
    "publiee": {"fr": "Demande publiée : {lien}", "en": "Request posted: {lien}"},
    "impossible": {"fr": "Impossible de publier ta demande pour le moment.", "en": "Can't post your request right now."},
    "plus_de_zone": {"fr": "Cette zone n'existe plus.", "en": "This area no longer exists."},
    "introuvable": {"fr": "Demande introuvable.", "en": "Request not found."},
    "close": {"fr": "Cette demande est close.", "en": "This request is closed."},
    "deja_close": {"fr": "Cette demande est déjà close.", "en": "This request is already closed."},
    "ta_demande": {"fr": "C'est ta demande : attends qu'un joueur se manifeste.",
                   "en": "It's your request: wait for a player to step in."},
    "deja_dessus": {"fr": "Tu es déjà dessus.{lien}", "en": "You're already on it.{lien}"},
    "complet": {"fr": "Il y a déjà assez de monde sur cette demande.", "en": "There are already enough people on it."},
    "note": {"fr": "C'est noté, rendez-vous dans le fil.{lien}", "en": "Got it, see you in the thread.{lien}"},
    "mm_qui": {"fr": "Seuls l'auteur et les intéressés appellent un middleman.",
               "en": "Only the author and interested players can call a middleman."},
    "mm_deja": {"fr": "Un middleman a déjà été appelé il y a peu.", "en": "A middleman was called a moment ago."},
    "mm_aucun": {"fr": "Aucun middleman n'est désigné pour le moment.", "en": "No middleman is assigned yet."},
    "mm_fil": {"fr": "Le fil de cet échange est introuvable pour le moment.",
               "en": "This trade's thread can't be found right now."},
    "mm_echec": {"fr": "Impossible de prévenir les middlemen pour le moment.",
                 "en": "Can't notify the middlemen right now."},
    "mm_ok": {"fr": "Middlemen prévenus : attends-en un avant d'échanger.",
              "en": "Middlemen notified: wait for one before trading."},
    "certif_type": {"fr": "Ce type ne se certifie pas : l'auteur clôture sa demande.",
                    "en": "This type isn't certified: the author closes the request."},
    "certif_reserve_mm": {"fr": "Réservé aux middlemen{role}.", "en": "Only for middlemen{role}."},
    "certif_reserve": {"fr": "Réservé aux guides {nom}{role}.", "en": "Only for {nom} guides{role}."},
    "certif_soi": {"fr": "Tu ne peux pas certifier ta propre demande.", "en": "You can't certify your own request."},
    "certif_titre": {"fr": "Certifier · n°{id}", "en": "Certify · #{id}"},
    "certif_texte": {"fr": "Certifier que l'aide a été faite ? La demande se clôt ; les joueurs cochés sont remerciés.",
                     "en": "Certify the help was given? The request closes; the selected players are thanked."},
    "certif_texte_trade": {"fr": "Certifier cet échange ? La demande se clôt et compte pour la confiance des deux joueurs.",
                           "en": "Certify this trade? The request closes and counts toward both players' trust."},
    "certif_qui": {"fr": "Qui a aidé ?", "en": "Who helped?"},
    "certif_qui_trade": {"fr": "Avec qui l'échange s'est fait ?", "en": "Who was the trade with?"},
    "certif_ok": {"fr": "Certifier l'aide", "en": "Certify the help"},
    "certif_ok_trade": {"fr": "Certifier l'échange", "en": "Certify the trade"},
    "certifie": {"fr": "Certifié ✅", "en": "Certified ✅"},
    "annuler": {"fr": "Annuler", "en": "Cancel"},
    "rien": {"fr": "Rien n'a changé.", "en": "Nothing changed."},
    "clore_reserve": {"fr": "Seuls l'auteur, les guides du type et le staff clôturent une demande.",
                      "en": "Only the author, this type's guides and the staff can close a request."},
    "clore_titre": {"fr": "Clôturer ta demande", "en": "Close your request"},
    "clore_texte": {"fr": "C'est réglé ? Le fil se ferme et disparaît ; l'historique reste au staff.",
                    "en": "All done? The thread closes and disappears; the staff keeps the history."},
    "clore_titre_trade": {"fr": "Clôturer ton échange", "en": "Close your trade"},
    "clore_texte_trade": {"fr": "L'échange s'est bien passé des deux côtés ? Dis avec qui, puis clôture.",
                          "en": "Did the trade go well on both sides? Say who with, then close."},
    "clore_regle": {"fr": "C'est réglé", "en": "Solved"},
    "clore_conclu": {"fr": "Échange conclu", "en": "Trade done"},
    "clore_annuler": {"fr": "Annuler ma demande", "en": "Cancel my request"},
    "clore_avec": {"fr": "Avec qui ? (facultatif)", "en": "Who with? (optional)"},
    "clore_titre_autre": {"fr": "Clôturer cette demande", "en": "Close this request"},
    "clore_texte_autre": {"fr": "Clôturer sans certifier ? Le fil se ferme et disparaît ; l'historique reste au staff.",
                          "en": "Close without certifying? The thread closes and disappears; the staff keeps the history."},
    "clore_sans": {"fr": "Clôturer sans certifier", "en": "Close without certifying"},
    "cloturee": {"fr": "Demande clôturée ✅ Le fil se ferme.", "en": "Request closed ✅ The thread is closing."},
}


def tr(cle: str, langue: str = "fr", **kw) -> str:
    e = TEXTES.get(cle) or {}
    texte = e.get(langue) or e.get("fr") or cle
    try:
        return texte.format(**kw) if kw else texte
    except (KeyError, IndexError, ValueError):
        return texte


# ═══════════════════════════════════════════════════════════════════════════════
#  Types et forums
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Champ:
    cle: str
    fr: str               # le titre du champ (≤ 45), en français
    en: str               # … et en anglais
    aide_fr: str = ""     # l'exemple (≤ 100)
    aide_en: str = ""
    carte: str = ""       # le libellé sur la carte publique, français · anglais
    long: bool = False
    max: int = 100
    requis: bool = True

    def libelle(self, langue: str) -> str:
        return self.en if langue == "en" else self.fr

    def exemple(self, langue: str) -> str:
        return self.aide_en if langue == "en" else self.aide_fr


@dataclass(frozen=True)
class Zone:
    cle: str
    nom: str              # français · anglais : l'étiquette du forum, le titre de la carte
    emoji: str
    salon: str            # le forum qui la porte : « entraide » (🛟 help) ou « trade »
    couleur: int
    expire_h: int         # fermée après autant d'heures sans activité
    champs: tuple
    titre: str            # le nom du fil, à partir des champs
    certif: str = ""      # « guide », « middleman » ou rien
    role: str = ""        # le rôle créé à l'installation
    bouton: str = ""      # son bouton dans le post épinglé
    rejoindre: str = "J'aide · I'll help"
    icone_rejoindre: str = "accueil"
    annonce: str = "🙋 {qui} vient t'aider · is coming to help — {auteur}"
    jeu: str = "rell"     # « rell » (Rell Seas) ou « clover » (Clover RPG)
    echange: bool = False  # un échange : middleman, confiance, « intéressé »

    @property
    def libelle(self) -> str:
        """Le type, et son jeu s'il n'est pas Rell Seas (le site, les réglages)."""
        return self.nom if self.jeu == "rell" else f"{self.nom} · {JEUX_NOMS.get(self.jeu, self.jeu)}"


JEUX_NOMS = {"rell": "Rell Seas", "clover": "Clover RPG"}


PSEUDO = Champ("pseudo", "Ton pseudo Roblox", "Your Roblox username", "Pour qu'on te trouve en jeu",
               "So players can find you in game", "Pseudo Roblox", max=40)
NIVEAU = Champ("niveau", "Ton niveau", "Your level", "Ex. 1 250", "E.g. 1250", "Niveau · Level", max=20, requis=False)


def _details(fr_ex: str, en_ex: str, mx: int = 500) -> Champ:
    return Champ("details", "Précisions", "Details", fr_ex, en_ex, "Précisions · Details", long=True, max=mx,
                 requis=False)


ZONES = {z.cle: z for z in (
    Zone("aide", "Aide · Help", "🛟", "entraide", 0x22C55E, 24,
         (Champ("titre", "Ta question ou ton problème", "Your question or problem", "En une phrase",
                "In one sentence", "Question", max=90),
          _details("Où tu es, ce que tu as déjà essayé…", "Where you are, what you already tried…", 800),
          PSEUDO, NIVEAU),
         "{titre}", certif="guide", role="🛟 Guide Aide", bouton="Aide · Help"),
    Zone("boss", "Boss", "⚔️", "entraide", 0xEF4444, 6,
         (Champ("titre", "Quel boss ?", "Which boss?", "Son nom", "Its name", "Boss", max=60), PSEUDO, NIVEAU,
          Champ("joueurs", "Joueurs voulus", "Players needed", "Combien en plus de toi ? Ex. 2",
                "How many besides you? E.g. 2", "Joueurs · Players", max=10, requis=False),
          _details("Île, heure, conditions…", "Island, time, conditions…")),
         "Boss {titre}", certif="guide", role="⚔️ Guide Boss", bouton="Boss"),
    Zone("farm", "Farm", "🌾", "entraide", 0x84CC16, 12,
         (Champ("titre", "Quoi farmer ?", "What to farm?", "Niveaux, argent, un objet…", "Levels, money, an item…",
                "Farm", max=80), PSEUDO, NIVEAU,
          Champ("duree", "Combien de temps ?", "How long?", "Ex. 1 h", "E.g. 1 h", "Durée · Duration", max=30,
                requis=False),
          _details("Où, comment…", "Where, how…")),
         "Farm {titre}", certif="guide", role="🌾 Guide Farm", bouton="Farm"),
    Zone("chill", "Chill", "🌴", "entraide", 0x38BDF8, 6,
         (Champ("titre", "Ce que tu veux faire", "What you want to do", "Naviguer, discuter, explorer…",
                "Sail, chat, explore…", "Activité · Activity", max=90), PSEUDO,
          Champ("quand", "Quand ?", "When?", "Maintenant, ce soir 21 h…", "Now, tonight 9 pm…", "Quand · When",
                max=40, requis=False),
          _details("Ce que tu aimes, ton style…", "What you like, your style…", 400)),
         "{titre}", bouton="Chill", rejoindre="Je viens · I'm in",
         annonce="🌴 {qui} te rejoint · is joining you — {auteur}"),
    Zone("trade", "Trade", "🤝", "trade", 0xF59E0B, 48,
         (Champ("donne", "Je donne", "I give", "Fruits, objets…", "Fruits, items…", "Je donne · I give", max=120),
          Champ("cherche", "Je cherche", "I want", "Ce que tu veux en échange", "What you want in return",
                "Je cherche · I want", max=120), PSEUDO,
          _details("Valeur, conditions…", "Value, conditions…", 400)),
         "{donne} ⇄ {cherche}", certif="middleman", role="🛡️ Middleman", bouton="Proposer · Post a trade",
         rejoindre="Intéressé · Interested", icone_rejoindre="pour",
         annonce="💬 {qui} est intéressé · is interested — {auteur}", echange=True),
    #  Clover RPG (24/10/2026) : les mêmes types, ses posts, ses rôles.
    Zone("cl_aide", "Aide · Help", "🛟", "cl_entraide", 0x22C55E, 24,
         (Champ("titre", "Ta question ou ton problème", "Your question or problem", "En une phrase",
                "In one sentence", "Question", max=90),
          _details("Où tu es, ce que tu as déjà essayé…", "Where you are, what you already tried…", 800),
          PSEUDO, NIVEAU),
         "{titre}", certif="guide", role="🛟 Guide Aide · Clover", bouton="Aide · Help", jeu="clover"),
    Zone("cl_boss", "Boss", "⚔️", "cl_entraide", 0xEF4444, 6,
         (Champ("titre", "Quel boss ?", "Which boss?", "Son nom", "Its name", "Boss", max=60), PSEUDO, NIVEAU,
          Champ("joueurs", "Joueurs voulus", "Players needed", "Combien en plus de toi ? Ex. 2",
                "How many besides you? E.g. 2", "Joueurs · Players", max=10, requis=False),
          _details("Zone, heure, conditions…", "Area, time, conditions…")),
         "Boss {titre}", certif="guide", role="⚔️ Guide Boss · Clover", bouton="Boss", jeu="clover"),
    Zone("cl_farm", "Farm", "🌾", "cl_entraide", 0x84CC16, 12,
         (Champ("titre", "Quoi farmer ?", "What to farm?", "Niveaux, argent, un objet…", "Levels, money, an item…",
                "Farm", max=80), PSEUDO, NIVEAU,
          Champ("duree", "Combien de temps ?", "How long?", "Ex. 1 h", "E.g. 1 h", "Durée · Duration", max=30,
                requis=False),
          _details("Où, comment…", "Where, how…")),
         "Farm {titre}", certif="guide", role="🌾 Guide Farm · Clover", bouton="Farm", jeu="clover"),
    Zone("cl_chill", "Chill", "🌴", "cl_entraide", 0x38BDF8, 6,
         (Champ("titre", "Ce que tu veux faire", "What you want to do", "Explorer, discuter, s'entraîner…",
                "Explore, chat, train…", "Activité · Activity", max=90), PSEUDO,
          Champ("quand", "Quand ?", "When?", "Maintenant, ce soir 21 h…", "Now, tonight 9 pm…", "Quand · When",
                max=40, requis=False),
          _details("Ce que tu aimes, ton style…", "What you like, your style…", 400)),
         "{titre}", bouton="Chill", rejoindre="Je viens · I'm in",
         annonce="🌴 {qui} te rejoint · is joining you — {auteur}", jeu="clover"),
    Zone("cl_trade", "Trade", "🤝", "cl_trade", 0xF59E0B, 48,
         (Champ("donne", "Je donne", "I give", "Objets, ressources…", "Items, resources…", "Je donne · I give",
                max=120),
          Champ("cherche", "Je cherche", "I want", "Ce que tu veux en échange", "What you want in return",
                "Je cherche · I want", max=120), PSEUDO,
          _details("Valeur, conditions…", "Value, conditions…", 400)),
         "{donne} ⇄ {cherche}", certif="middleman", role="🛡️ Middleman · Clover", bouton="Proposer · Post a trade",
         rejoindre="Intéressé · Interested", icone_rejoindre="pour",
         annonce="💬 {qui} est intéressé · is interested — {auteur}", jeu="clover", echange=True),
)}
#  Les deux forums : (nom, texte du post épinglé, bandeau, titre du bandeau, couleur)
SALONS = {
    "entraide": ("🛟help",
                 "🇫🇷 Une question, un boss, du farm, ou juste jouer ensemble ? Choisis, remplis : ta demande "
                 "s'affiche ici et des joueurs viennent t'aider.\n"
                 "🇬🇧 A question, a boss, farming, or just playing together? Pick, fill in: your request shows "
                 "up here and players come to help.",
                 "rs_entraide", "Entraide · Help", 0x22C55E),
    "trade": ("🤝trade",
              "🇫🇷 Propose un échange : ta carte s'affiche ici. Avec un inconnu, ne donne jamais en premier : "
              "appelle un middleman.\n"
              "🇬🇧 Post a trade: your card shows up here. With a stranger, never give first: call a middleman.",
              "rs_trade", "Trade", 0xF59E0B),
    "cl_entraide": ("🛟help-clover",
                    "🇫🇷 Une question, un boss, du farm, ou juste jouer ensemble sur Clover RPG ? Choisis, remplis : "
                    "ta demande s'affiche ici et des joueurs viennent t'aider.\n"
                    "🇬🇧 A question, a boss, farming, or just playing together on Clover RPG? Pick, fill in: your "
                    "request shows up here and players come to help.",
                    "cl_entraide", "Entraide · Help", 0x22C55E),
    "cl_trade": ("🤝trade-clover",
                 "🇫🇷 Propose un échange Clover RPG : ta carte s'affiche ici. Avec un inconnu, ne donne jamais en "
                 "premier : appelle un middleman.\n"
                 "🇬🇧 Post a Clover RPG trade: your card shows up here. With a stranger, never give first: call a "
                 "middleman.",
                 "cl_trade", "Trade", 0xF59E0B),
}

STATUTS = {
    "ouverte": ("Ouverte · Open", "🟢"),
    "prise": ("En cours · Ongoing", "🟡"),
    "terminee": ("Terminée · Done", "✅"),
    "fermee": ("Fermée · Closed", "🔒"),
    "expiree": ("Fermée · Closed", "⌛"),
    "retiree": ("Retirée · Removed", "🗑️"),
}
OUVERTS = ("ouverte", "prise")
#  Étiquettes des forums, réservées au bot et au staff (« modérées ») : le type, puis le statut.
TAGS = (("Ouverte · Open", "🟢"), ("En cours · Ongoing", "🟡"), ("Terminée · Done", "✅"), ("Fermée · Closed", "🔒"))
ETIQUETTE = {"ouverte": "Ouverte · Open", "prise": "En cours · Ongoing", "terminee": "Terminée · Done"}
#  Les noms d'avant (22/10, première version), pour renommer sans perdre les étiquettes posées.
ANCIENS_TAGS = {"Aide": "Aide · Help", "Ouverte": "Ouverte · Open", "En cours": "En cours · Ongoing",
                "Terminée": "Terminée · Done", "Fermée": "Fermée · Closed"}

MAX_OUVERTES = 3          # par membre, tous types
ATTENTE_S = 120           # entre deux demandes d'un même membre
MAX_AIDANTS = 10
GARDER_H = 0              # une demande close disparaît au passage suivant (l'historique reste au site)
APPEL_MM_S = 900          # un appel au middleman par quart d'heure et par échange
ARCHIVE_MIN = 10080       # Discord n'archive jamais avant nous
DELAIS = (2, 6, 12, 24, 48, 72)
GARDES = (0, 1, 24)
PAR_PASSAGE = 15          # fermetures ou suppressions par passage de la boucle


def types_du_salon(cle: str) -> list:
    return [z for z in ZONES.values() if z.salon == cle]


def tags_du_salon(cle: str) -> list:
    types = types_du_salon(cle) if len(types_du_salon(cle)) > 1 else []
    return ([discord.ForumTag(name=z.nom, emoji=z.emoji, moderated=True) for z in types]
            + [discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in TAGS])


_get_db = _cfg = _db_set = None
_texte_refuse = _controle = _est_staff = _journal = _retour = _archiver = None
_langue = None
_log = print
_verrous: dict = {}
_creations: dict = {}
_verifies: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, est_staff, journal, langue=None, archiver=None,
          salon_ticket=None, log=None):
    """`texte_refuse(g, texte)` → raison ou "" ; `controle(membre, cfg)` → raison ou "" ;
    `est_staff(g, membre)` (async) ; `journal(g, type_, texte, membre_id=, auteur_id=)` ;
    `langue(interaction)` (async) → « fr » ou « en » ; `archiver(fil, titre)` (async) → le jeton du
    transcript enregistré, ou ""."""
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _est_staff, _journal, _log, _langue, _archiver
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle, _est_staff, _journal = texte_refuse, controle, est_staff, journal
    _langue, _archiver = langue, archiver
    _log = log or print


def set_retour(fn):
    global _retour
    _retour = fn


_installateur = None


def set_installateur(fn):
    """Le bouton « Installer / Réparer » de /configure installe toute la structure (`zones.installer`)."""
    global _installateur
    _installateur = fn


def _verrou(cle):
    return _verrous.setdefault(cle, asyncio.Lock())


async def langue_de(i) -> str:
    """La langue du membre : sa préférence, sinon celle de son Discord ; français ou anglais."""
    try:
        if _langue is not None:
            return "en" if await _langue(i) == "en" else "fr"
        loc = str(getattr(getattr(i, "locale", None), "value", getattr(i, "locale", "")) or "")
        return "fr" if loc.lower().startswith("fr") else "en"
    except Exception as ex:
        _log(f"[ENTRAIDE:DETAIL] langue {type(ex).__name__} {ex}")
        return "fr"


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "zone", "auteur_id", "titre", "champs", "statut", "salon_id", "fil_id",
             "aidants", "cree", "maj", "ferme", "ferme_par", "certifie_par", "credites", "partenaire_id",
             "appel_mm", "supprime", "jeton", "mode")
#  `mode` « carte » : la demande est une carte dans son post (`salon_id` = le post, `fil_id` = la carte).
#  Vide : l'ancienne installation, un post de forum par demande (`fil_id` = ce post).
_SQL_UNE = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants, cree,"
            " maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime, jeton, mode"
            " FROM entraide_demandes WHERE id=?")
_SQL_OUVERTES = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                 " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime, jeton,"
                 " mode FROM entraide_demandes WHERE guild_id=? AND statut IN ('ouverte', 'prise')"
                 " AND fil_id>0 ORDER BY id LIMIT 300")
_SQL_DE_L_AUTEUR = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                    " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime, jeton,"
                    " mode FROM entraide_demandes WHERE guild_id=? AND auteur_id=? AND statut IN ('ouverte', 'prise')"
                    " AND fil_id>0")
_SQL_OUVERTES_DU_SALON = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id,"
                          " aidants, cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm,"
                          " supprime, jeton, mode FROM entraide_demandes WHERE guild_id=? AND salon_id=?"
                          " AND statut IN ('ouverte', 'prise')")
_SQL_A_EFFACER = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                  " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime, jeton,"
                  " mode FROM entraide_demandes WHERE guild_id=? AND statut NOT IN ('ouverte', 'prise')"
                  " AND supprime=0 AND ferme>0 AND ferme<=? ORDER BY ferme LIMIT ?")
_SQL_RECENTES = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                 " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime, jeton,"
                 " mode FROM entraide_demandes WHERE guild_id=? AND fil_id>0 ORDER BY id DESC LIMIT ?")


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS entraide_demandes ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, zone TEXT NOT NULL,"
            " auteur_id INTEGER NOT NULL, titre TEXT NOT NULL, champs TEXT NOT NULL DEFAULT '[]',"
            " statut TEXT NOT NULL DEFAULT 'ouverte', salon_id INTEGER NOT NULL DEFAULT 0,"
            " fil_id INTEGER NOT NULL DEFAULT 0, aidants TEXT NOT NULL DEFAULT '[]',"
            " cree INTEGER NOT NULL, maj INTEGER NOT NULL, ferme INTEGER NOT NULL DEFAULT 0,"
            " ferme_par INTEGER NOT NULL DEFAULT 0, certifie_par INTEGER NOT NULL DEFAULT 0,"
            " credites TEXT NOT NULL DEFAULT '[]', partenaire_id INTEGER NOT NULL DEFAULT 0,"
            " appel_mm INTEGER NOT NULL DEFAULT 0, supprime INTEGER NOT NULL DEFAULT 0, jeton TEXT NOT NULL DEFAULT '')")
        async with db.execute("PRAGMA table_info(entraide_demandes)") as cur:
            colonnes = {r[1] for r in await cur.fetchall()}
        if "jeton" not in colonnes:
            await db.execute("ALTER TABLE entraide_demandes ADD COLUMN jeton TEXT NOT NULL DEFAULT ''")
        if "mode" not in colonnes:
            await db.execute("ALTER TABLE entraide_demandes ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
        #  Les mots du bot sous une carte (qui vient aider, un middleman appelé) : effacés avec elle.
        await db.execute("CREATE TABLE IF NOT EXISTS entraide_notes (demande_id INTEGER NOT NULL,"
                         " message_id INTEGER NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entraide_statut ON entraide_demandes(guild_id, statut)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entraide_auteur ON entraide_demandes(guild_id, auteur_id, statut)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entraide_fil ON entraide_demandes(fil_id)")
        await db.commit()


def _ligne(r) -> dict:
    d = dict(zip(_COLONNES, r))
    for k in ("champs", "aidants", "credites"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except (TypeError, ValueError):
            d[k] = []
    d["jeton"] = d.get("jeton") or ""
    d["mode"] = d.get("mode") or ""
    return d


async def charger(did: int):
    async with _get_db() as db:
        async with db.execute(_SQL_UNE, (int(did),)) as cur:
            r = await cur.fetchone()
    return _ligne(r) if r else None


async def _lignes(sql: str, args: tuple) -> list:
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            return [_ligne(r) for r in await cur.fetchall()]


async def _ecrire(sql: str, args: tuple) -> None:
    async with _get_db() as db:
        await db.execute(sql, args)
        await db.commit()


async def recentes(guild_id: int, limite: int = 300) -> list:
    """Les dernières demandes, ouvertes ou closes — pour le site du staff."""
    return await _lignes(_SQL_RECENTES, (int(guild_id), int(limite)))


async def reputation(guild_id: int, membre_id: int, zone: str = "trade") -> int:
    """Échanges certifiés par un middleman dans ce trade (chaque jeu le sien), comme vendeur ou acheteur."""
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM entraide_demandes WHERE guild_id=? AND zone=?"
                              " AND statut='terminee' AND certifie_par!=0 AND (auteur_id=? OR partenaire_id=?)",
                              (int(guild_id), str(zone), int(membre_id), int(membre_id))) as cur:
            return int((await cur.fetchone())[0])


async def compter_ouvertes(guild_id: int) -> dict:
    async with _get_db() as db:
        async with db.execute("SELECT zone, COUNT(*) FROM entraide_demandes WHERE guild_id=?"
                              " AND statut IN ('ouverte', 'prise') AND fil_id>0 GROUP BY zone",
                              (int(guild_id),)) as cur:
            return {z: int(n) for z, n in await cur.fetchall()}


# ═══════════════════════════════════════════════════════════════════════════════
#  Réglages
# ═══════════════════════════════════════════════════════════════════════════════

async def conf(g) -> dict:
    c = await _cfg(g.id)
    return {"actif": bool(c.get("rs_actif")), "categorie": int(c.get("rs_categorie", 0) or 0),
            "salons": dict(c.get("rs_salons") or {}), "roles": dict(c.get("rs_roles") or {}),
            "panneaux": dict(c.get("rs_panneaux") or {}), "reglages": dict(c.get("rs_reglages") or {}),
            "ouvertures": dict(c.get("rs_ouvertures") or {})}


def ids_salons(c: dict) -> set:
    """Les salons de l'entraide, pour qu'aucun réglage de masse ne touche à leurs droits."""
    ids = {int(v) for v in (c.get("rs_salons") or {}).values() if str(v).isdigit()}
    return ids | ({int(c["rs_categorie"])} if str(c.get("rs_categorie", "")).isdigit() else set())


def salon(g, cf: dict, cle: str):
    """Le post (ou le salon) d'un type, s'il est en mémoire — un post endormi n'y est pas : voir
    `conteneur`."""
    return g.get_channel_or_thread(int(cf["salons"].get(cle, 0) or 0))


async def _resoudre(g, cid):
    """Un salon ou un post, même endormi (hors mémoire) ; None s'il n'existe plus. Une panne lève."""
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


async def conteneur(g, cf: dict, cle: str):
    """Là où vivent les demandes d'un type — le post, réveillé s'il dormait. None s'il n'existe plus
    (ou si Discord ne répond pas : c'est noté)."""
    try:
        ch = await _resoudre(g, cf["salons"].get(cle, 0))
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] lecture du salon {cle} {type(ex).__name__} {ex}")
        return None
    if isinstance(ch, discord.Thread) and ch.archived:
        try:
            await ch.edit(archived=False)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] réveil du post {cle} {ex}")
    return ch


def en_cartes(ch) -> bool:
    """« Plutôt que des milliers de fils » : une demande est une carte dans son post (ou son salon).
    Seule l'ancienne installation — un forum par type — ouvrait un post par demande."""
    return ch is not None and not isinstance(ch, discord.ForumChannel)


def lien(g, d: dict) -> str:
    """Le lien d'une demande : sa carte (ou, ancienne installation, son post)."""
    if d.get("mode") == "carte":
        return f"https://discord.com/channels/{g.id}/{int(d['salon_id'])}/{int(d['fil_id'])}"
    return f"https://discord.com/channels/{g.id}/{int(d['fil_id'])}"


def role_zone(g, cf: dict, cle: str):
    return g.get_role(int(cf["roles"].get(cle, 0) or 0))


def expire_h(cf: dict, z: Zone) -> int:
    v = (cf["reglages"].get("expire") or {}).get(z.cle)
    return int(v) if str(v).isdigit() and int(v) > 0 else z.expire_h


def garder_h(cf: dict) -> int:
    v = cf["reglages"].get("garder_h")
    return int(v) if str(v).isdigit() and int(v) in GARDES else GARDER_H


def prevenir(cf: dict, z: Zone) -> bool:
    return z.certif == "guide" and bool((cf["reglages"].get("ping") or {}).get(z.cle, True))


async def _regler(g, cle: str, valeur) -> None:
    cf = await conf(g)
    reglages = cf["reglages"]
    reglages[cle] = valeur
    await _db_set(g.id, "rs_reglages", reglages)


# ═══════════════════════════════════════════════════════════════════════════════
#  Textes et cartes
# ═══════════════════════════════════════════════════════════════════════════════

def _echapper(t) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(t or "")))


def _mention(uid) -> str:
    return f"<@{int(uid)}>"


def _une_ligne(t: str) -> str:
    return " ".join(str(t or "").split())


def titre_de(z: Zone, valeurs: dict) -> str:
    return _une_ligne(z.titre.format(**{c.cle: valeurs.get(c.cle, "") for c in z.champs}))[:90]


def nom_du_fil(auteur, titre: str) -> str:
    return _une_ligne(f"{titre} · {getattr(auteur, 'display_name', '') or 'membre'}")[:100]


def verifier(z: Zone, valeurs: dict, langue: str = "fr") -> str:
    for c in z.champs:
        v = valeurs.get(c.cle, "")
        if c.requis and not v.strip():
            return tr("obligatoire", langue, champ=c.libelle(langue))
        if len(v) > c.max:
            return tr("trop_long", langue, champ=c.libelle(langue))
    return ""


def _ligne_statut(d: dict, z: Zone) -> str:
    lib, pastille = STATUTS.get(d["statut"], (d["statut"], "•"))
    if d["statut"] in OUVERTS:
        if not d["aidants"]:
            return f"{pastille} **{lib}** · personne pour l'instant · nobody yet"
        mot = "intéressé(s) · interested" if z.echange else "en route · on the way"
        return f"{pastille} **{lib}** · {mot} : " + ", ".join(_mention(a) for a in d["aidants"][:MAX_AIDANTS])
    fin = "\n-# Fil fermé · Thread closed" if d["ferme"] else ""
    if d["statut"] == "terminee":
        if d["certifie_par"]:
            quoi = "Échange certifié · Trade certified" if z.echange else "Aide certifiée · Help certified"
            s = f"✅ **{quoi}** — {_mention(d['certifie_par'])} · <t:{d['ferme']}:R>"
        else:
            quoi = "Échange conclu · Trade done" if z.echange else "Résolue · Solved"
            s = f"✅ **{quoi}** · <t:{d['ferme']}:R>"
        if z.echange and d["partenaire_id"]:
            s += f"\n-# Avec · With {_mention(d['partenaire_id'])}"
        elif d["credites"]:
            s += "\n-# Ont aidé · Helped : " + ", ".join(_mention(x) for x in d["credites"])
        return s + fin
    if d["statut"] == "expiree":
        return "⌛ **Fermée · Closed** — plus d'activité · no activity" + fin
    if d["statut"] == "retiree":
        return "🗑️ **Retirée · Removed**" + fin
    par = f" — {_mention(d['ferme_par'])}" if d["ferme_par"] and d["ferme_par"] != d["auteur_id"] else ""
    return f"🔒 **Fermée · Closed**{par} · <t:{d['ferme']}:R>" + fin


def vue_carte(d: dict, z: Zone, *, avatar: str = "", ping: str = "", rep: int | None = None) -> LayoutView:
    ouvert = d["statut"] in OUVERTS
    entete = [discord.ui.TextDisplay(f"### {z.emoji} {z.nom} · n°{d['id']}"),
              discord.ui.TextDisplay(f"{_mention(d['auteur_id'])} · <t:{d['cree']}:R>")]
    items = [discord.ui.Section(*entete, accessory=discord.ui.Thumbnail(avatar))] if avatar else list(entete)
    lignes = [f"**{lib}** · {_echapper(v)}" for lib, v in d["champs"] if str(v or "").strip()]
    if lignes:
        items.append(discord.ui.TextDisplay("\n".join(lignes)))
    if z.echange and ouvert:
        confiance = ("aucun échange certifié · no certified trade yet" if not rep
                     else f"{rep} échange(s) certifié(s) · certified trade(s)")
        items.append(discord.ui.TextDisplay(f"-# 🛡️ {confiance} · Avec un inconnu, ne donne jamais en premier : "
                                            "appelle un middleman. · With a stranger, never give first: call a "
                                            "middleman."))
    items.append(discord.ui.Separator())
    items.append(discord.ui.TextDisplay(_ligne_statut(d, z)))
    if ouvert:
        boutons = [BoutonRejoindre(d["id"], z)]
        if z.echange:
            boutons.append(BoutonMiddleman(d["id"]))
        if z.certif:
            boutons.append(BoutonCertifier(d["id"], z))
        boutons.append(BoutonFermer(d["id"]))
        items.append(discord.ui.ActionRow(*boutons))
        if ping:
            items.append(discord.ui.TextDisplay(f"-# Guides prévenus · Guides notified : {ping}"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(z.couleur) if ouvert else Palette.NEUTRAL))
    return v


def vue_panneau(cle: str, cf: dict, g=None) -> LayoutView:
    """Le post épinglé d'un forum : un bouton par type, le délai de chacun, qui certifie."""
    _nom, texte, bandeau, titre, couleur = SALONS[cle]
    types = types_du_salon(cle)
    roles = [r for r in (role_zone(g, cf, z.cle) for z in types if z.role) if r is not None] if g is not None else []
    delais = " · ".join(f"{z.nom.split(' · ')[0].lower()} {expire_h(cf, z)} h" for z in types)
    pied = ["Une demande à la fois · One request at a time",
            "réponds sous une carte pour en parler · reply under a card to talk",
            f"fermée sans activité · closes when inactive : {delais}"]
    if roles:
        pied.append(("middlemen" if any(z.echange for z in types) else "guides") + " : "
                    + " ".join(r.mention for r in roles))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau(bandeau, titre), discord.ui.TextDisplay(texte),
        discord.ui.ActionRow(*[BoutonNouvelle(z.cle, z) for z in types]),
        discord.ui.TextDisplay("-# " + " · ".join(pied)), accent_color=discord.Color(couleur)))
    return v


# ═══════════════════════════════════════════════════════════════════════════════
#  Fils
# ═══════════════════════════════════════════════════════════════════════════════

def _horodatage(snowflake) -> float:
    return discord.utils.snowflake_time(int(snowflake)).timestamp() if snowflake else 0.0


async def _fil(g, d: dict):
    """Le fil d'une demande (archivé compris), ou None s'il n'existe plus. Une panne réseau n'est
    pas une disparition : elle lève."""
    fid = int(d.get("fil_id") or 0)
    if not fid:
        return None
    fil = g.get_channel_or_thread(fid)
    if fil is not None:
        return fil
    try:
        return await g.fetch_channel(fid)
    except discord.NotFound:
        return None


async def _fil_ou_rien(g, d: dict):
    """Pour les interactions : une panne réseau ne doit pas laisser le membre sans réponse."""
    try:
        return await _fil(g, d)
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] lecture du fil demande={d['id']} {type(ex).__name__} {ex}")
        return None


def _porteur(fil):
    """Le salon qui porte la carte : le post lui-même (forum) ou le salon sous lequel pend le fil."""
    parent = getattr(fil, "parent", None)
    return fil if isinstance(parent, discord.ForumChannel) or parent is None else parent


def _tags(forum, statut: str, z: Zone | None = None) -> list:
    """Le type (forum à plusieurs types) puis le statut — seulement les étiquettes qui existent."""
    dispo = {t.name: t for t in getattr(forum, "available_tags", []) or []}
    noms = ([z.nom] if z is not None and len(types_du_salon(z.salon)) > 1 else []) + [
        ETIQUETTE.get(statut, "Fermée · Closed")]
    return [dispo[n] for n in noms if n in dispo]


async def _maj_carte(g, d: dict, fil=None) -> None:
    z = ZONES.get(d["zone"])
    if z is None:
        return
    if d.get("mode") == "carte":
        try:
            porteur = await _resoudre(g, d["salon_id"])
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] lecture du post demande={d['id']} {ex}")
            return
        mid = int(d["fil_id"])
    else:
        fil = fil or await _fil_ou_rien(g, d)
        porteur, mid = (_porteur(fil), fil.id) if fil is not None else (None, 0)
    if porteur is None:
        return
    auteur = g.get_member(int(d["auteur_id"]))
    rep = await reputation(g.id, d["auteur_id"], z.cle) if z.echange else None
    vue = vue_carte(d, z, avatar=auteur.display_avatar.url if auteur else "", rep=rep)
    try:
        await porteur.get_partial_message(mid).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
    except discord.NotFound:
        pass
    except discord.HTTPException as ex:
        _log("[ENTRAIDE][E2] carte non mise à jour")
        _log(f"[ENTRAIDE][E2:DETAIL] demande={d['id']} {type(ex).__name__} {ex}")


async def _clore_sur_discord(g, d: dict, note: str = "") -> None:
    """Une carte : elle passe au statut final, sans bouton, puis disparaît au passage suivant avec les
    mots du bot et les réponses qu'on lui a faites. L'ancienne installation (un post par demande) :
    la carte d'abord (un message d'un fil archivé ne s'édite plus), le mot de fin, l'historique
    enregistré pour le site, puis le post verrouillé et archivé."""
    if d.get("mode") == "carte":
        await _maj_carte(g, d)
        return
    fil = await _fil_ou_rien(g, d)
    if fil is None:
        return
    await _maj_carte(g, d, fil)
    if note:
        try:
            await fil.send(note, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] mot de fin demande={d['id']} {ex}")
    if _archiver is not None and not d.get("jeton"):
        z = ZONES.get(d["zone"])
        try:
            jeton = await _archiver(fil, f"Entraide n°{d['id']} · {getattr(z, 'nom', d['zone'])} · {d['titre']}")
        except Exception as ex:
            _log("[ENTRAIDE][E11] historique non enregistré")
            _log(f"[ENTRAIDE][E11:DETAIL] demande={d['id']} {type(ex).__name__} {ex}")
            jeton = ""
        if jeton:
            d["jeton"] = jeton
            await _ecrire("UPDATE entraide_demandes SET jeton=? WHERE id=?", (jeton, d["id"]))
    reglage = {"locked": True, "archived": True}
    if isinstance(fil.parent, discord.ForumChannel):
        reglage["applied_tags"] = _tags(fil.parent, d["statut"], ZONES.get(d["zone"]))
    try:
        await fil.edit(**reglage)
    except discord.HTTPException as ex:
        _log("[ENTRAIDE][E3] fil non archivé")
        _log(f"[ENTRAIDE][E3:DETAIL] demande={d['id']} {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Publier
# ═══════════════════════════════════════════════════════════════════════════════

async def peut_publier(i, z: Zone, langue: str = "fr") -> str:
    g, m = i.guild, i.user
    if g is None or getattr(m, "guild_permissions", None) is None:
        return tr("sur_serveur", langue)
    cf = await conf(g)
    if not cf["actif"] or not cf["salons"].get(z.salon):
        return tr("zone_fermee", langue)
    if m.is_timed_out():
        return tr("exclu", langue)
    return await _controle(m, await _cfg(g.id)) or await limite(g, m, z, langue)


async def limite(g, m, z: Zone, langue: str = "fr") -> str:
    if await _est_staff(g, m):
        return ""
    t0 = _creations.get((g.id, m.id))
    if t0 is not None and time.monotonic() - t0 < ATTENTE_S:
        return tr("attendre", langue)
    ouvertes = await _lignes(_SQL_DE_L_AUTEUR, (g.id, m.id))
    ici = next((d for d in ouvertes if d["zone"] == z.cle), None)
    if ici is not None:
        return tr("deja_ici", langue, lien=f"\n{lien(g, ici)}")
    if len(ouvertes) >= MAX_OUVERTES:
        return tr("trop", langue, n=MAX_OUVERTES)
    return ""


class Formulaire(discord.ui.Modal):
    def __init__(self, z: Zone, langue: str = "fr", valeurs: dict | None = None):
        super().__init__(title=tr("form.titre", langue, emoji=z.emoji, nom=z.nom)[:45], timeout=900)
        self.zone, self.langue, self.entrees = z, langue, {}
        valeurs = valeurs or {}
        for c in z.champs[:5]:
            t = discord.ui.TextInput(style=discord.TextStyle.paragraph if c.long else discord.TextStyle.short,
                                     max_length=c.max, required=c.requis,
                                     placeholder=c.exemple(langue)[:100] or None, default=valeurs.get(c.cle) or None)
            self.entrees[c.cle] = t
            self.add_item(discord.ui.Label(text=c.libelle(langue)[:45], component=t,
                                           description=None if c.requis else tr("facultatif", langue)))

    async def on_submit(self, i: discord.Interaction):
        await publier(i, self.zone, {k: (t.value or "").strip() for k, t in self.entrees.items()}, self.langue)


def vue_corriger(auteur_id: int, z: Zone, erreur: str, valeurs: dict, langue: str = "fr") -> LayoutView:
    v = LayoutView(timeout=900)
    b = Button(label=tr("corriger", langue), style=discord.ButtonStyle.primary, emoji=visuels.icone("modifier"))

    async def _cb(i: discord.Interaction):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.send_modal(Formulaire(z, langue, valeurs))
    b.callback = _cb
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(erreur), discord.ui.ActionRow(b),
                                    accent_color=Palette.WARNING))
    return v


async def publier(i, z: Zone, valeurs: dict, langue: str = "fr"):
    g, m = i.guild, i.user
    valeurs = {c.cle: (valeurs.get(c.cle, "") if c.long else _une_ligne(valeurs.get(c.cle, ""))) for c in z.champs}
    erreur = verifier(z, valeurs, langue) or await _texte_refuse(g, "\n".join(v for v in valeurs.values() if v))
    if erreur:
        return await i.response.send_message(view=vue_corriger(m.id, z, erreur, valeurs, langue), ephemeral=True)
    refus = await peut_publier(i, z, langue)
    if refus:
        return await i.response.send_message(refus, ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    titre = titre_de(z, valeurs)
    async with _verrou(("publier", g.id)):
        refus = await limite(g, m, z, langue)
        if refus:
            return await i.followup.send(refus, ephemeral=True)
        t = int(time.time())
        champs = [[c.carte or c.fr, valeurs.get(c.cle, "")] for c in z.champs]
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO entraide_demandes(guild_id, zone, auteur_id, titre, champs, cree, maj)"
                " VALUES(?,?,?,?,?,?,?)", (g.id, z.cle, m.id, titre, json.dumps(champs, ensure_ascii=False), t, t))
            did = cur.lastrowid
            await db.commit()
        _creations[(g.id, m.id)] = time.monotonic()
    cf = await conf(g)
    ch = await conteneur(g, cf, z.salon)
    d = await charger(did)
    role = role_zone(g, cf, z.cle) if prevenir(cf, z) else None
    if role is not None and not (role.mentionable or g.me.guild_permissions.mention_everyone):
        role = None
    rep = await reputation(g.id, m.id, z.cle) if z.echange else None
    vue = vue_carte(d, z, avatar=m.display_avatar.url, ping=role.mention if role else "", rep=rep)
    mentions = discord.AllowedMentions(everyone=False, users=False, roles=[role] if role else False)
    mode, fil = ("carte" if en_cartes(ch) else ""), None
    try:
        if ch is None:
            raise discord.ClientException("zone sans salon")
        if mode == "carte":
            carte_id = (await ch.send(view=vue, allowed_mentions=mentions)).id
        else:
            fil = (await ch.create_thread(name=nom_du_fil(m, titre), view=vue, allowed_mentions=mentions,
                                          applied_tags=_tags(ch, "ouverte", z),
                                          reason=f"Entraide : demande n°{did}")).thread
            carte_id = fil.id
    except (discord.HTTPException, discord.ClientException) as ex:
        _log("[ENTRAIDE][E1] demande non publiée")
        _log(f"[ENTRAIDE][E1:DETAIL] zone={z.cle} {type(ex).__name__} {ex}")
        await _ecrire("DELETE FROM entraide_demandes WHERE id=?", (did,))
        _creations.pop((g.id, m.id), None)
        return await i.followup.send(tr("impossible", langue), ephemeral=True)
    await _ecrire("UPDATE entraide_demandes SET salon_id=?, fil_id=?, mode=? WHERE id=?", (ch.id, carte_id, mode, did))
    d.update(salon_id=ch.id, fil_id=carte_id, mode=mode)
    if fil is not None:
        try:
            await fil.add_user(m)  # l'auteur suit son post : il est prévenu de chaque réponse
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] auteur non ajouté au fil demande={did} {ex}")
    await i.followup.send(tr("publiee", langue, lien=lien(g, d)), ephemeral=True)
    if mode == "carte":
        asyncio.create_task(reposer_panneau(g, z.salon))
    await _journal(g, "entraide.demande", f"{m.mention} a publié une demande · {z.nom} : {titre}",
                   membre_id=m.id)


class BoutonNouvelle(discord.ui.DynamicItem[Button], template=r"rs:n:(?P<zone>[a-z_]+)"):
    def __init__(self, zone: str, z: Zone | None = None):
        self.zone = zone
        z = z or ZONES.get(zone)
        super().__init__(Button(label=(z.bouton if z else "") or "Publier · Post",
                                style=discord.ButtonStyle.primary,
                                emoji=(z.emoji if z else None) or visuels.icone("ajouter"), custom_id=f"rs:n:{zone}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["zone"])

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        z = ZONES.get(self.zone)
        if z is None:
            return await i.response.send_message(tr("plus_de_zone", langue), ephemeral=True)
        refus = await peut_publier(i, z, langue)
        if refus:
            return await i.response.send_message(refus, ephemeral=True)
        await i.response.send_modal(Formulaire(z, langue))


# ═══════════════════════════════════════════════════════════════════════════════
#  Rejoindre, appeler un middleman
# ═══════════════════════════════════════════════════════════════════════════════

async def _demande_ouverte(i, did: int, langue: str):
    d = await charger(did)
    if d is None or i.guild is None or d["guild_id"] != i.guild.id:
        await i.followup.send(tr("introuvable", langue), ephemeral=True)
        return None
    if d["statut"] not in OUVERTS:
        await i.followup.send(tr("close", langue), ephemeral=True)
        return None
    return d


async def rejoindre(i, did: int):
    await i.response.defer(ephemeral=True)
    g, m = i.guild, i.user
    langue = await langue_de(i)
    async with _verrou(("demande", did)):
        d = await _demande_ouverte(i, did, langue)
        if d is None:
            return
        z = ZONES[d["zone"]]
        if m.id == d["auteur_id"]:
            return await i.followup.send(tr("ta_demande", langue), ephemeral=True)
        url = f" {lien(g, d)}"
        if m.id in d["aidants"]:
            return await i.followup.send(tr("deja_dessus", langue, lien=url), ephemeral=True)
        if len(d["aidants"]) >= MAX_AIDANTS:
            return await i.followup.send(tr("complet", langue), ephemeral=True)
        d["aidants"].append(m.id)
        d["statut"], d["maj"] = "prise", int(time.time())
        await _ecrire("UPDATE entraide_demandes SET aidants=?, statut=?, maj=? WHERE id=?",
                      (json.dumps(d["aidants"]), d["statut"], d["maj"], did))
    annonce = z.annonce.format(qui=m.mention, auteur=_mention(d["auteur_id"]))
    pour_l_auteur = discord.AllowedMentions(users=[discord.Object(d["auteur_id"])])
    if d["mode"] == "carte":
        await _maj_carte(g, d)
        await _annoncer(g, d, annonce, pour_l_auteur)
    else:
        fil = await _fil_ou_rien(g, d)
        if fil is not None:
            await _maj_carte(g, d, fil)
            try:
                if isinstance(fil.parent, discord.ForumChannel):
                    await fil.edit(applied_tags=_tags(fil.parent, "prise", z))
                await fil.add_user(m)
                await fil.send(annonce, allowed_mentions=pour_l_auteur)
            except discord.HTTPException as ex:
                _log(f"[ENTRAIDE:DETAIL] annonce demande={did} {ex}")
    await i.followup.send(tr("note", langue, lien=url), ephemeral=True)


async def _annoncer(g, d: dict, texte: str, mentions) -> bool:
    """Un mot en réponse à la carte (qui vient aider, un middleman appelé) : il prévient la bonne
    personne, et il disparaîtra avec la carte."""
    try:
        porteur = await _resoudre(g, d["salon_id"])
        if porteur is None:
            return False
        msg = await porteur.send(texte, reference=porteur.get_partial_message(int(d["fil_id"])),
                                 allowed_mentions=mentions, mention_author=False)
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] mot sous la carte demande={d['id']} {type(ex).__name__} {ex}")
        return False
    await _ecrire("INSERT INTO entraide_notes(demande_id, message_id) VALUES(?,?)", (int(d["id"]), msg.id))
    return True


async def _notes(did: int) -> list:
    async with _get_db() as db:
        async with db.execute("SELECT message_id FROM entraide_notes WHERE demande_id=?", (int(did),)) as cur:
            return [int(r[0]) for r in await cur.fetchall()]


class BoutonRejoindre(discord.ui.DynamicItem[Button], template=r"rs:j:(?P<did>\d+)"):
    def __init__(self, did: int, z: Zone | None = None):
        self.did = int(did)
        z = z or ZONES["aide"]
        super().__init__(Button(label=z.rejoindre, style=discord.ButtonStyle.success,
                                emoji=visuels.icone(z.icone_rejoindre), custom_id=f"rs:j:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        await rejoindre(i, self.did)


async def appeler_middleman(i, did: int):
    await i.response.defer(ephemeral=True)
    g, m = i.guild, i.user
    langue = await langue_de(i)
    async with _verrou(("demande", did)):
        d = await _demande_ouverte(i, did, langue)
        if d is None:
            return
        if m.id != d["auteur_id"] and m.id not in d["aidants"]:
            return await i.followup.send(tr("mm_qui", langue), ephemeral=True)
        t = int(time.time())
        if t - int(d["appel_mm"] or 0) < APPEL_MM_S:
            return await i.followup.send(tr("mm_deja", langue), ephemeral=True)
        role = role_zone(g, await conf(g), d["zone"])  # le middleman du trade de ce jeu
        if role is None or not role.members:
            return await i.followup.send(tr("mm_aucun", langue), ephemeral=True)
        texte = f"🛡️ {role.mention} — {m.mention} demande un middleman · needs a middleman."
        if d["mode"] == "carte":
            if not await _annoncer(g, d, texte, discord.AllowedMentions(roles=[role])):
                _log("[ENTRAIDE][E4] middleman non appelé")
                return await i.followup.send(tr("mm_echec", langue), ephemeral=True)
        else:
            fil = await _fil_ou_rien(g, d)
            if fil is None:
                return await i.followup.send(tr("mm_fil", langue), ephemeral=True)
            try:
                await fil.send(texte, allowed_mentions=discord.AllowedMentions(roles=[role]))
            except discord.HTTPException as ex:
                _log("[ENTRAIDE][E4] middleman non appelé")
                _log(f"[ENTRAIDE][E4:DETAIL] demande={did} {ex}")
                return await i.followup.send(tr("mm_echec", langue), ephemeral=True)
        await _ecrire("UPDATE entraide_demandes SET appel_mm=? WHERE id=?", (t, did))
    await i.followup.send(tr("mm_ok", langue), ephemeral=True)


class BoutonMiddleman(discord.ui.DynamicItem[Button], template=r"rs:m:(?P<did>\d+)"):
    def __init__(self, did: int):
        self.did = int(did)
        super().__init__(Button(label="Middleman", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("bouclier"), custom_id=f"rs:m:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        await appeler_middleman(i, self.did)


# ═══════════════════════════════════════════════════════════════════════════════
#  Certifier, clôturer
# ═══════════════════════════════════════════════════════════════════════════════

async def peut_certifier(g, m, d: dict, langue: str = "fr") -> str:
    z = ZONES.get(d["zone"])
    if z is None or not z.certif:
        return tr("certif_type", langue)
    staff = await _est_staff(g, m)
    role = role_zone(g, await conf(g), z.cle)
    if not staff and (role is None or role not in getattr(m, "roles", [])):
        quel = f" ({role.mention})" if role else ""
        if z.certif == "middleman":
            return tr("certif_reserve_mm", langue, role=quel)
        return tr("certif_reserve", langue, nom=z.nom, role=quel)
    if m.id == d["auteur_id"] and not staff:
        return tr("certif_soi", langue)
    return ""


async def certifier(g, did: int, par, credites: list, partenaire: int = 0, langue: str = "fr") -> str:
    async with _verrou(("demande", did)):
        d = await charger(did)
        if d is None or d["statut"] not in OUVERTS:
            return tr("deja_close", langue)
        t = int(time.time())
        credites = [int(x) for x in dict.fromkeys(credites) if int(x) != d["auteur_id"]][:MAX_AIDANTS]
        d.update(statut="terminee", ferme=t, ferme_par=par.id, certifie_par=par.id, credites=credites,
                 partenaire_id=int(partenaire or 0), maj=t)
        await _ecrire("UPDATE entraide_demandes SET statut=?, ferme=?, ferme_par=?, certifie_par=?, credites=?,"
                      " partenaire_id=?, maj=? WHERE id=?",
                      (d["statut"], t, par.id, par.id, json.dumps(credites), d["partenaire_id"], t, did))
    z = ZONES[d["zone"]]
    if z.echange:
        note = f"✅ Échange certifié par {par.mention} · Trade certified by {par.mention}" + (
            f" — avec · with {_mention(d['partenaire_id'])}" if d["partenaire_id"] else "")
    else:
        note = f"✅ Aide certifiée par {par.mention} · Help certified by {par.mention}" + (
            " — merci · thanks " + ", ".join(_mention(x) for x in credites) if credites else "")
    await _clore_sur_discord(g, d, note)
    aides = (" — aidé par " + ", ".join(_mention(x) for x in credites)) if credites and not z.echange else ""
    await _journal(g, "entraide.certifiee", f"{par.mention} a certifié la demande de {_mention(d['auteur_id'])}"
                                            f" · {z.nom} : {d['titre']}{aides}",
                   membre_id=d["auteur_id"], auteur_id=par.id)
    return ""


async def resoudre(g, did: int, par, partenaire: int = 0, langue: str = "fr") -> str:
    """L'auteur clôt sa demande : c'est réglé (les joueurs qui sont venus sont remerciés), ou
    l'échange est conclu (avec qui, s'il le dit). Ça ne compte pas dans la confiance : seul un
    middleman la certifie."""
    async with _verrou(("demande", did)):
        d = await charger(did)
        if d is None or d["statut"] not in OUVERTS:
            return tr("deja_close", langue)
        t = int(time.time())
        z = ZONES[d["zone"]]
        credites = [] if z.echange else [int(x) for x in d["aidants"]][:MAX_AIDANTS]
        d.update(statut="terminee", ferme=t, ferme_par=par.id, certifie_par=0, credites=credites,
                 partenaire_id=int(partenaire or 0), maj=t)
        await _ecrire("UPDATE entraide_demandes SET statut=?, ferme=?, ferme_par=?, certifie_par=0, credites=?,"
                      " partenaire_id=?, maj=? WHERE id=?",
                      (d["statut"], t, par.id, json.dumps(credites), d["partenaire_id"], t, did))
    if z.echange:
        note = "✅ Échange conclu · Trade done" + (
            f" — avec · with {_mention(d['partenaire_id'])}" if d["partenaire_id"] else "")
    else:
        note = "✅ Résolu par l'auteur · Solved by the author" + (
            " — merci · thanks " + ", ".join(_mention(x) for x in credites) if credites else "")
    await _clore_sur_discord(g, d, note)
    await _journal(g, "entraide.resolue", f"{par.mention} a clôturé sa demande (réglée) · {z.nom} : {d['titre']}",
                   membre_id=par.id, auteur_id=par.id)
    return ""


async def fermer(g, did: int, par_id: int, statut: str = "fermee", note: str = "",
                 maintenant: float | None = None) -> bool:
    async with _verrou(("demande", did)):
        d = await charger(did)
        if d is None or d["statut"] not in OUVERTS:
            return False
        t = int(maintenant or time.time())
        d.update(statut=statut, ferme=t, ferme_par=int(par_id or 0), maj=t)
        await _ecrire("UPDATE entraide_demandes SET statut=?, ferme=?, ferme_par=?, maj=? WHERE id=?",
                      (statut, t, d["ferme_par"], t, did))
    await _clore_sur_discord(g, d, note)
    if par_id and par_id != d["auteur_id"]:
        await _journal(g, "entraide.fermee", f"{_mention(par_id)} a clôturé la demande de "
                                             f"{_mention(d['auteur_id'])} · {ZONES[d['zone']].nom} : {d['titre']}",
                       membre_id=d["auteur_id"], auteur_id=par_id)
    return True


def _vue_message(texte: str, couleur) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=couleur))
    return v


class VueCertifier(LayoutView):
    """Qui a aidé (ou avec qui l'échange s'est fait) — la liste est déjà cochée, on corrige au besoin."""

    def __init__(self, d: dict, z: Zone, par, langue: str = "fr"):
        super().__init__(timeout=300)
        self.d, self.z, self.par, self.langue, self.choisis = d, z, par, langue, None
        echange = z.echange
        defauts = [discord.Object(id=int(x)) for x in d["aidants"][:1 if echange else MAX_AIDANTS]]
        self.qui = UserSelect(placeholder=tr("certif_qui_trade" if echange else "certif_qui", langue),
                              min_values=0, max_values=1 if echange else MAX_AIDANTS, default_values=defauts)
        self.qui.callback = self._cb_qui
        ok = Button(label=tr("certif_ok_trade" if echange else "certif_ok", langue),
                    style=discord.ButtonStyle.success, emoji=visuels.icone("valider"))
        ok.callback = self._cb_ok
        non = Button(label=tr("annuler", langue), style=discord.ButtonStyle.secondary, emoji=visuels.icone("annuler"))
        non.callback = self._cb_non
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"### {z.emoji} {tr('certif_titre', langue, id=d['id'])}\n"
                                   + tr("certif_texte_trade" if echange else "certif_texte", langue)),
            discord.ui.ActionRow(self.qui), discord.ui.ActionRow(ok, non), accent_color=Palette.SUCCESS))

    async def interaction_check(self, i):
        return i.user.id == self.par.id

    async def _cb_qui(self, i):
        self.choisis = [u.id for u in self.qui.values]
        await i.response.defer()

    async def _cb_ok(self, i):
        await i.response.defer()
        choisis = self.choisis if self.choisis is not None else [int(x) for x in self.d["aidants"]]
        if self.z.echange:
            erreur = await certifier(i.guild, self.d["id"], i.user, [], partenaire=(choisis or [0])[0],
                                     langue=self.langue)
        else:
            erreur = await certifier(i.guild, self.d["id"], i.user, choisis, langue=self.langue)
        await i.edit_original_response(view=_vue_message(erreur or tr("certifie", self.langue),
                                                         Palette.WARNING if erreur else Palette.SUCCESS))

    async def _cb_non(self, i):
        await i.response.edit_message(view=_vue_message(tr("rien", self.langue), Palette.NEUTRAL))


class VueCloturer(LayoutView):
    """« Une fois que le trading est bon des deux côtés, les gens peuvent clôturer leur propre ticket. »
    L'auteur : c'est réglé / échange conclu (avec qui, s'il veut), ou il annule. Un guide ou le staff :
    clôturer sans certifier. Chaque choix est déjà la confirmation : rien sur un mauvais clic."""

    def __init__(self, d: dict, z: Zone, membre, langue: str, sienne: bool):
        super().__init__(timeout=300)
        self.d, self.z, self.m, self.langue, self.partenaire = d, z, membre, langue, None
        echange = z.echange
        items = []
        if sienne:
            items.append(discord.ui.TextDisplay(
                f"### {z.emoji} {tr('clore_titre_trade' if echange else 'clore_titre', langue)}\n"
                + tr("clore_texte_trade" if echange else "clore_texte", langue)))
            if echange:
                self.avec = UserSelect(placeholder=tr("clore_avec", langue), min_values=0, max_values=1,
                                       default_values=[discord.Object(id=int(x)) for x in d["aidants"][:1]])
                self.avec.callback = self._cb_avec
                items.append(discord.ui.ActionRow(self.avec))
            ok = Button(label=tr("clore_conclu" if echange else "clore_regle", langue),
                        style=discord.ButtonStyle.success, emoji=visuels.icone("valider"))
            ok.callback = self._cb_regle
            annule = Button(label=tr("clore_annuler", langue), style=discord.ButtonStyle.danger,
                            emoji=visuels.icone("supprimer"))
            annule.callback = self._cb_annuler
            items.append(discord.ui.ActionRow(ok, annule))
        else:
            items.append(discord.ui.TextDisplay(f"### {z.emoji} {tr('clore_titre_autre', langue)}\n"
                                                + tr("clore_texte_autre", langue)))
            b = Button(label=tr("clore_sans", langue), style=discord.ButtonStyle.danger, emoji=visuels.icone("verrou"))
            b.callback = self._cb_autre
            items.append(discord.ui.ActionRow(b))
        self.add_item(discord.ui.Container(*items, accent_color=Palette.WARNING))

    async def interaction_check(self, i):
        return i.user.id == self.m.id

    async def _fin(self, i, texte):
        await i.edit_original_response(view=_vue_message(texte, Palette.NEUTRAL))

    async def _cb_avec(self, i):
        self.partenaire = self.avec.values[0].id if self.avec.values else 0
        await i.response.defer()

    async def _cb_regle(self, i):
        await i.response.defer()
        partenaire = self.partenaire if self.partenaire is not None else int((self.d["aidants"] or [0])[0])
        erreur = await resoudre(i.guild, self.d["id"], i.user, partenaire if self.z.echange else 0,
                                self.langue)
        await self._fin(i, erreur or tr("cloturee", self.langue))

    async def _cb_annuler(self, i):
        await i.response.defer()
        ok = await fermer(i.guild, self.d["id"], i.user.id, "fermee", "🔒 Annulée par l'auteur · Cancelled by the author")
        await self._fin(i, tr("cloturee" if ok else "deja_close", self.langue))

    async def _cb_autre(self, i):
        await i.response.defer()
        ok = await fermer(i.guild, self.d["id"], i.user.id, "fermee",
                          f"🔒 Clôturée par {i.user.mention} · Closed by {i.user.mention}")
        await self._fin(i, tr("cloturee" if ok else "deja_close", self.langue))


def vue_confirmer(texte: str, libelle: str, action, auteur_id: int, *, icone: str = "verrou",
                  style=discord.ButtonStyle.danger) -> LayoutView:
    """OUI / NON, tout en bas : jamais une action finale sur un mauvais clic."""
    v = LayoutView(timeout=300)
    oui = Button(label=libelle, style=style, emoji=visuels.icone(icone))
    non = Button(label="Annuler", style=discord.ButtonStyle.secondary, emoji=visuels.icone("annuler"))

    async def _oui(i):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.defer()
        texte_fin = await action(i)
        await i.edit_original_response(view=_vue_message(texte_fin, Palette.NEUTRAL))

    async def _non(i):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.edit_message(view=_vue_message("Rien n'a changé.", Palette.NEUTRAL))
    oui.callback, non.callback = _oui, _non
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), discord.ui.ActionRow(oui, non),
                                    accent_color=Palette.WARNING))
    return v


class BoutonCertifier(discord.ui.DynamicItem[Button], template=r"rs:c:(?P<did>\d+)"):
    def __init__(self, did: int, z: Zone | None = None):
        self.did = int(did)
        super().__init__(Button(label="Certifier · Certify", style=discord.ButtonStyle.primary,
                                emoji=visuels.icone("valider"), custom_id=f"rs:c:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        d = await charger(self.did)
        if d is None or i.guild is None or d["guild_id"] != i.guild.id:
            return await i.response.send_message(tr("introuvable", langue), ephemeral=True)
        if d["statut"] not in OUVERTS:
            return await i.response.send_message(tr("close", langue), ephemeral=True)
        refus = await peut_certifier(i.guild, i.user, d, langue)
        if refus:
            return await i.response.send_message(refus, ephemeral=True,
                                                 allowed_mentions=discord.AllowedMentions.none())
        await i.response.send_message(view=VueCertifier(d, ZONES[d["zone"]], i.user, langue), ephemeral=True)


class BoutonFermer(discord.ui.DynamicItem[Button], template=r"rs:f:(?P<did>\d+)"):
    def __init__(self, did: int):
        self.did = int(did)
        super().__init__(Button(label="Clôturer · Close", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("verrou"), custom_id=f"rs:f:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        g, m = i.guild, i.user
        langue = await langue_de(i)
        d = await charger(self.did)
        if d is None or g is None or d["guild_id"] != g.id:
            return await i.response.send_message(tr("introuvable", langue), ephemeral=True)
        if d["statut"] not in OUVERTS:
            return await i.response.send_message(tr("deja_close", langue), ephemeral=True)
        z = ZONES[d["zone"]]
        role = role_zone(g, await conf(g), z.cle)
        sienne = m.id == d["auteur_id"]
        if not (sienne or await _est_staff(g, m) or (role is not None and role in m.roles)):
            return await i.response.send_message(tr("clore_reserve", langue), ephemeral=True)
        await i.response.send_message(view=VueCloturer(d, z, m, langue, sienne), ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entretien : expiration, suppression, posts épinglés
# ═══════════════════════════════════════════════════════════════════════════════

async def _effacer(g, d: dict) -> None:
    """La demande close disparaît : sa carte, les mots du bot et les réponses qu'on lui a faites (ou,
    ancienne installation, son post). Une erreur passagère : on réessaiera au passage suivant."""
    try:
        if d["mode"] == "carte":
            porteur = await _resoudre(g, d["salon_id"])
            if porteur is not None:
                await _effacer_carte(porteur, d)
        else:
            fil = await _fil(g, d)
            if fil is not None:
                parent = fil.parent
                await fil.delete()
                if parent is not None and not isinstance(parent, discord.ForumChannel):
                    try:
                        await parent.get_partial_message(int(d["fil_id"])).delete()
                    except discord.NotFound:
                        pass
    except discord.Forbidden as ex:
        _log("[ENTRAIDE][E5] fil non supprimé (droits)")
        _log(f"[ENTRAIDE][E5:DETAIL] demande={d['id']} {ex}")
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] suppression reportée demande={d['id']} {type(ex).__name__} {ex}")
        return
    await _ecrire("UPDATE entraide_demandes SET supprime=1 WHERE id=?", (d["id"],))
    await _ecrire("DELETE FROM entraide_notes WHERE demande_id=?", (d["id"],))


async def _effacer_carte(porteur, d: dict) -> None:
    """« Un vrai système de nettoyage ultra propre » : la carte, les mots du bot dessous, et les
    messages qui y répondaient (ou répondaient à ces réponses)."""
    carte = int(d["fil_id"])
    a_effacer = [carte] + await _notes(d["id"])
    try:
        async for msg in porteur.history(limit=200, after=discord.Object(id=carte)):
            ref = getattr(getattr(msg, "reference", None), "message_id", None)
            if ref in a_effacer:
                a_effacer.append(msg.id)
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] lecture des réponses demande={d['id']} {ex}")
    for mid in dict.fromkeys(a_effacer):
        try:
            await porteur.get_partial_message(mid).delete()
        except discord.NotFound:
            pass
        except discord.Forbidden as ex:
            _log(f"[ENTRAIDE:DETAIL] message non effacé demande={d['id']} {ex}")


async def _existe(g, d: dict):
    """La demande est encore sur Discord : son post (ancienne installation) ou le post qui porte sa
    carte. None si elle a disparu. Une panne réseau lève."""
    if d["mode"] != "carte":
        return await _fil(g, d)
    porteur = await _resoudre(g, d["salon_id"])
    if porteur is None:
        return None
    try:
        await porteur.fetch_message(int(d["fil_id"]))
    except discord.NotFound:
        return None
    return porteur


async def entretenir(g, maintenant: float | None = None) -> dict:
    """Toutes les 5 minutes : les demandes sans activité se ferment, les demandes closes disparaissent
    (au passage suivant, par défaut), les posts épinglés restent en place (vérifiés toutes les 30 min)."""
    cf = await conf(g)
    bilan = {"expirees": 0, "retirees": 0, "effacees": 0}
    if not cf["actif"]:
        return bilan
    t = maintenant or time.time()
    actions = 0
    for d in await _lignes(_SQL_OUVERTES, (g.id,)):
        if actions >= PAR_PASSAGE:
            break
        z = ZONES.get(d["zone"])
        if z is None:
            continue
        try:
            trouve = await _existe(g, d)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] lecture de la demande={d['id']} {ex}")
            continue
        if trouve is None:
            await _ecrire("UPDATE entraide_demandes SET statut='retiree', ferme=?, maj=?, supprime=1 WHERE id=?",
                          (int(t), int(t), d["id"]))
            bilan["retirees"] += 1
            actions += 1
            continue
        derniere = float(d["maj"])
        if d["mode"] != "carte":
            derniere = max(derniere, _horodatage(getattr(trouve, "last_message_id", None)))
        delai = expire_h(cf, z)
        if t - derniere > delai * 3600:
            note = (f"⌛ Fermée faute d'activité ({delai} h) · Closed for inactivity ({delai} h) — "
                    "republie si besoin · post again if needed")
            if await fermer(g, d["id"], 0, "expiree", note, maintenant=t):
                bilan["expirees"] += 1
                actions += 1
    #  Clos à l'instant (garder 0 h) : effacé au passage SUIVANT — le mot de fin a le temps d'être vu.
    limite_t = int(t - max(garder_h(cf) * 3600, 60))
    for d in await _lignes(_SQL_A_EFFACER, (g.id, limite_t, PAR_PASSAGE)):
        await _effacer(g, d)
        bilan["effacees"] += 1
    #  Une publication interrompue (redémarrage entre l'écriture et le fil) ne bloque personne.
    await _ecrire("DELETE FROM entraide_demandes WHERE guild_id=? AND fil_id=0 AND cree<?", (g.id, int(t) - 600))
    if t - _verifies.get(g.id, 0) > 1800:
        _verifies[g.id] = t
        await assurer_panneaux(g)
    return bilan


async def fermer_anciennes(g, note: str) -> int:
    """22/10/2026, les deux forums : les demandes de l'ancienne installation (un post par demande) se
    ferment en disant où republier."""
    n = 0
    for d in await _lignes(_SQL_OUVERTES, (g.id,)):
        if d["mode"] != "carte" and await fermer(g, d["id"], 0, "fermee", note):
            n += 1
    return n


async def sur_depart(member) -> int:
    """Un membre quitte le serveur : ses demandes ouvertes se ferment."""
    g = member.guild
    n = 0
    for d in await _lignes(_SQL_DE_L_AUTEUR, (g.id, member.id)):
        if await fermer(g, d["id"], 0, "fermee", "🔒 Fermée : l'auteur a quitté le serveur · Closed: the author left"):
            n += 1
    return n


def _nom_panneau(cle: str) -> str:
    return ("📌 Proposer un échange · Post a trade" if any(z.echange for z in types_du_salon(cle))
            else "📌 Publier une demande · Ask for help")


async def _panneau_forum(g, cf: dict, cle: str, forum, forcer: bool) -> None:
    """Le post épinglé, en tête du forum, avec un bouton par type."""
    tid = int(cf["panneaux"].get(cle, 0) or 0)
    fil = None
    if tid:
        fil = g.get_channel_or_thread(tid)
        if fil is None:
            try:
                fil = await g.fetch_channel(tid)
            except discord.NotFound:
                fil = None
    vue = vue_panneau(cle, cf, g)
    if fil is None:
        fil = (await forum.create_thread(name=_nom_panneau(cle), view=vue,
                                         allowed_mentions=discord.AllowedMentions.none(),
                                         reason="Entraide : post épinglé")).thread
        cf["panneaux"][cle] = fil.id
        try:
            await fil.edit(pinned=True, locked=True)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] post non épinglé salon={cle} {ex}")
        return
    reglage = {}
    if fil.archived:
        reglage["archived"] = False
    if not fil.locked:
        reglage["locked"] = True
    if not fil.flags.pinned:
        reglage["pinned"] = True
    if fil.name != _nom_panneau(cle):
        reglage["name"] = _nom_panneau(cle)
    if reglage:
        try:
            await fil.edit(**reglage)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] post non rétabli salon={cle} {ex}")
    if forcer:
        await fil.get_partial_message(fil.id).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())


async def _panneau_conteneur(g, cf: dict, cle: str, ch, forcer: bool) -> None:
    """Un post (ou un salon) : les boutons « publier » sont sur son message d'ouverture et sous la
    dernière carte — ce panneau-là redescend à chaque nouvelle carte."""
    vue = vue_panneau(cle, cf, g)
    ouverture = int(cf["ouvertures"].get(cle, 0) or 0)
    if forcer and ouverture:
        try:
            await ch.get_partial_message(ouverture).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            pass
    mid = int(cf["panneaux"].get(cle, 0) or 0)
    if mid and mid == ouverture:
        return
    if mid:
        try:
            if forcer:
                await ch.get_partial_message(mid).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
            else:
                await ch.fetch_message(mid)
            return
        except discord.NotFound:
            pass
    cf["panneaux"][cle] = (await ch.send(view=vue, allowed_mentions=discord.AllowedMentions.none())).id


async def reposer_panneau(g, cle: str) -> None:
    """Après une nouvelle carte, le panneau redescend dessous (le message d'ouverture reste)."""
    async with _verrou(("panneaux", g.id)):
        try:
            cf = await conf(g)
            ch = await conteneur(g, cf, cle)
            if not en_cartes(ch):
                return
            mid = int(cf["panneaux"].get(cle, 0) or 0)
            if mid and mid != int(cf["ouvertures"].get(cle, 0) or 0):
                try:
                    await ch.get_partial_message(mid).delete()
                except discord.NotFound:
                    pass
            cf["panneaux"][cle] = (await ch.send(view=vue_panneau(cle, cf, g),
                                                 allowed_mentions=discord.AllowedMentions.none())).id
            await _db_set(g.id, "rs_panneaux", cf["panneaux"])
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] panneau non reposé salon={cle} {ex}")


async def assurer_panneaux(g, forcer: bool = False) -> None:
    async with _verrou(("panneaux", g.id)):
        cf = await conf(g)
        for cle in SALONS:
            ch = await conteneur(g, cf, cle)
            try:
                if isinstance(ch, discord.ForumChannel):
                    await _panneau_forum(g, cf, cle, ch, forcer)
                elif ch is not None:
                    await _panneau_conteneur(g, cf, cle, ch, forcer)
            except discord.HTTPException as ex:
                _log("[ENTRAIDE][E7] post épinglé non posé")
                _log(f"[ENTRAIDE][E7:DETAIL] salon={cle} {type(ex).__name__} {ex}")
        await _db_set(g.id, "rs_panneaux", cf["panneaux"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Installation et mise à niveau des forums
# ═══════════════════════════════════════════════════════════════════════════════

def droits_zone(g) -> dict:
    """On ne publie que par le bouton ; on parle dans les fils (preuves et captures comprises)."""
    return {g.default_role: discord.PermissionOverwrite(
                send_messages=False, create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=True, read_message_history=True, attach_files=True, embed_links=True,
                add_reactions=True),
            g.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, send_messages_in_threads=True,
                create_public_threads=True, manage_threads=True, manage_messages=True,
                read_message_history=True, embed_links=True, attach_files=True)}


async def completer_droits(ch, g, droits: discord.PermissionOverwrite, raison: str) -> bool:
    """Ajoute à @everyone les droits nommés (preuves, captures…) sans toucher aux autres cibles —
    le refus posé au rôle « Radié » ou à la quarantaine reste."""
    o = ch.overwrites_for(g.default_role)
    neuf = discord.PermissionOverwrite(**dict(o))
    for k, v in droits:
        if v is not None:
            setattr(neuf, k, v)
    if neuf == o:
        return False
    await ch.set_permissions(g.default_role, overwrite=neuf, reason=raison)
    return True


def sujet(cle: str, cf: dict) -> str:
    types = types_du_salon(cle)
    delais = " · ".join(f"{z.nom.split(' · ')[0].lower()} {expire_h(cf, z)} h" for z in types)
    return (f"{SALONS[cle][1]}\nPublie avec le post épinglé · Post with the pinned post. Une demande à la fois · "
            f"One request at a time ({delais}).")


def categorie_communautaire(g):
    """La catégorie « Communautaire » (même règle que `config_salons.communautaire`)."""
    for cat in getattr(g, "categories", []) or []:
        if "communaut" in config_salons.normaliser(cat.name):
            return cat
    return None


async def categorie_cible(g):
    brut = await _cfg(g.id)
    aide = g.get_channel(int(brut.get("aide_salon", 0) or 0))
    return categorie_communautaire(g) or getattr(aide, "category", None)


async def installer(g, *, forum: bool | None = None, categorie=None, creer_salons: bool = True) -> list:
    """Crée ce qui manque — quatre rôles, les panneaux, et (seul, sans les zones) ses deux salons —
    sans jamais rien supprimer. Relancer répare. Rend la liste de ce qui a été créé. Les zones
    (`zones.py`) donnent elles-mêmes les posts 🛟 Help et 🤝 Trade : `creer_salons=False`."""
    me = g.me
    p = getattr(me, "guild_permissions", None)
    if not (p and p.manage_channels and p.manage_roles):
        raise PermissionError("Il me faut « Gérer les salons » et « Gérer les rôles ».")
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    faits = []
    async with _verrou(("installer", g.id)):
        cf = await conf(g)
        cat = categorie or await categorie_cible(g)
        roles = cf["roles"]
        for z in ZONES.values():
            if z.role and role_zone(g, cf, z.cle) is None:
                r = await g.create_role(name=z.role, colour=discord.Colour(z.couleur), mentionable=False,
                                        hoist=False, reason="Entraide : guides de la zone")
                roles[z.cle] = r.id
                await _db_set(g.id, "rs_roles", roles)
                faits.append(f"rôle {r.name}")
        salons = cf["salons"]
        for cle, (nom, *_reste) in SALONS.items():
            if not creer_salons or await _resoudre(g, salons.get(cle, 0)) is not None:
                continue
            if any(z.jeu != "rell" for z in types_du_salon(cle)):
                continue  # seul, sans les zones : l'entraide Rell Seas d'origine ; les autres jeux ont leur forum

            if forum:
                ch = await g.create_forum(
                    nom, category=cat, topic=sujet(cle, cf), overwrites=droits_zone(g),
                    default_auto_archive_duration=ARCHIVE_MIN, default_layout=discord.ForumLayoutType.list_view,
                    default_sort_order=discord.ForumOrderType.latest_activity, available_tags=tags_du_salon(cle),
                    reason="Entraide Rell Seas")
            else:
                ch = await g.create_text_channel(nom, category=cat, topic=sujet(cle, cf)[:1024],
                                                 overwrites=droits_zone(g), reason="Entraide Rell Seas")
            salons[cle] = ch.id
            await _db_set(g.id, "rs_salons", salons)
            faits.append(f"salon {ch.name}")
        await _db_set(g.id, "rs_actif", 1)
        await _db_set(g.id, "rs_v2", 1)
    await assurer_panneaux(g, forcer=True)
    return faits


def _copie_etiquette(t) -> discord.ForumTag:
    """Une copie (même identifiant) : l'étiquette du cache reste telle quelle tant que Discord n'a pas
    accepté le changement — un échec ne fait pas croire que c'est déjà fait."""
    n = discord.ForumTag(name=t.name, emoji=t.emoji, moderated=t.moderated)
    n.id = t.id
    return n


def _signature_etiquettes(tags) -> list:
    return [(t.name, str(t.emoji), bool(t.moderated), int(t.id or 0)) for t in tags]


def etiquettes_a_jour(existantes, cle: str) -> list:
    """Les étiquettes d'un forum, au propre : celles qui existent gardent leur identifiant (les posts
    étiquetés le restent) mais prennent le nom bilingue et l'émoji du type — plus de badge 🆘 ;
    l'ordre devient types puis statuts ; une étiquette ajoutée par le staff reste, à la fin."""
    gardes = [_copie_etiquette(t) for t in existantes or []]
    par_nom = {}
    for t in gardes:
        t.name = ANCIENS_TAGS.get(t.name, t.name)
        par_nom.setdefault(t.name, t)
    voulus = []
    for canon in tags_du_salon(cle):
        t = par_nom.get(canon.name)
        if t is None:
            voulus.append(canon)
            continue
        t.emoji, t.moderated = canon.emoji, True
        voulus.append(t)
    autres = [t for t in gardes if all(t is not v for v in voulus) and t.name not in {v.name for v in voulus}]
    return (voulus + autres)[:20]


async def mettre_a_niveau(g, categorie=None) -> list:
    """22/10 (nuit) : « universel, que tout le monde comprenne ». Les forums prennent leur nom et leurs
    étiquettes en français · anglais (les étiquettes déjà posées sont RENOMMÉES, pas remplacées), leur
    consigne, et rejoignent `categorie` (la zone Rell Seas). Les posts épinglés se réécrivent."""
    cf = await conf(g)
    faits = []
    for cle, (nom, *_reste) in SALONS.items():
        ch = salon(g, cf, cle)
        if ch is None:
            continue
        reglage = {}
        consigne = sujet(cle, cf)[:1024 if isinstance(ch, discord.TextChannel) else 4096]
        if (getattr(ch, "topic", None) or "") != consigne:
            reglage["topic"] = consigne
        if ch.name != nom:
            reglage["name"] = nom
        if categorie is not None and getattr(ch, "category_id", None) != categorie.id:
            reglage["category"], reglage["sync_permissions"] = categorie, False
        if isinstance(ch, discord.ForumChannel):
            tags = etiquettes_a_jour(ch.available_tags, cle)
            if _signature_etiquettes(tags) != _signature_etiquettes(ch.available_tags):
                reglage["available_tags"] = tags
        if reglage:
            await ch.edit(reason="Entraide : français · anglais, zone Rell Seas", **reglage)
        droits = await completer_droits(ch, g, droits_zone(g)[g.default_role],
                                        "Entraide : preuves et captures dans les fils")
        if reglage or droits:
            faits.append(f"{nom} mis à niveau")
    await assurer_panneaux(g, forcer=True)
    return faits


async def migrer_v2(g) -> list:
    """22/10 (soir) : la première installation (une catégorie, sept salons) devient deux forums.
    Seuls les salons créés par le bot partent ; la discussion seulement si aucun membre n'y a écrit."""
    brut = await _cfg(g.id)
    p = getattr(g.me, "guild_permissions", None)
    if brut.get("rs_v2") or not brut.get("rs_actif") or not (p and p.manage_channels):
        return []
    faits, traites = [], set()
    cf = await conf(g)
    anciens = dict(cf["salons"])
    cat = await categorie_cible(g)
    for cle in ("boss", "farm", "chill"):
        ch = g.get_channel(int(anciens.get(cle, 0) or 0))
        if ch is None:
            continue
        for d in await _lignes(_SQL_OUVERTES_DU_SALON, (g.id, ch.id)):
            await fermer(g, d["id"], 0, "fermee", "🔒 Cette zone rejoint 🛟 help : republie ta demande là-bas.")
        await ch.delete(reason="Entraide regroupée : un forum pour l'aide, le boss, le farm et le chill")
        traites.add(ch.id)
        faits.append(f"{ch.name} retiré")
    orientation = g.get_channel(int(anciens.get("orientation", 0) or 0))
    if orientation is not None:
        await orientation.delete(reason="L'orientation rejoint le panneau ❓ aide")
        traites.add(orientation.id)
        faits.append(f"{orientation.name} retiré")
    discussion = g.get_channel(int(anciens.get("discussion", 0) or 0))
    if discussion is not None:
        a_parle = False
        async for m in discussion.history(limit=200):
            if not getattr(m.author, "bot", False):
                a_parle = True
                break
        if a_parle:
            await discussion.edit(category=cat, sync_permissions=False, reason="Rangé dans Communautaire")
            faits.append(f"{discussion.name} gardé et rangé (des membres y ont écrit)")
        else:
            await discussion.delete(reason="On parle du jeu dans 💬 chat")
            faits.append(f"{discussion.name} retiré")
        traites.add(discussion.id)
    entraide_ch = g.get_channel(int(anciens.get("aide", 0) or 0))
    trade_ch = g.get_channel(int(anciens.get("trade", 0) or 0))
    for ch in (entraide_ch, trade_ch):
        if ch is not None:
            await ch.edit(category=cat, sync_permissions=False, reason="Entraide regroupée")
            traites.add(ch.id)
    await _db_set(g.id, "rs_salons", {k: ch.id for k, ch in (("entraide", entraide_ch), ("trade", trade_ch))
                                      if ch is not None})
    await _db_set(g.id, "rs_panneaux", {k: cf["panneaux"][ancien] for k, ancien in (("entraide", "aide"),
                                                                                     ("trade", "trade"))
                                        if cf["panneaux"].get(ancien)})
    ancienne = g.get_channel(cf["categorie"])
    if isinstance(ancienne, discord.CategoryChannel) and ancienne is not cat and \
            all(c.id in traites for c in ancienne.channels):
        await ancienne.delete(reason="Entraide regroupée")
        faits.append(f"catégorie {ancienne.name} retirée")
    await _db_set(g.id, "rs_categorie", 0)
    await _db_set(g.id, "rs_orientation", 0)
    await _db_set(g.id, "rs_v2", 1)
    faits += await installer(g)
    faits += await mettre_a_niveau(g)
    return faits


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration (/configure → Entraide Rell Seas)
# ═══════════════════════════════════════════════════════════════════════════════

class EntraidePanelV2(LayoutView):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g, self._note, self.zone = u, g, "", None

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            cf = await conf(self.g)
            items = [visuels.bandeau("rs_port", "Entraide Rell Seas")]
            installe = cf["actif"] and bool(cf["salons"].get("entraide"))
            if not installe:
                items.append(discord.ui.TextDisplay(
                    "Pas encore installée.\n-# Deux forums dans la zone Rell Seas — 🛟 help (aide, boss, farm, "
                    "chill) et 🤝 trade — et quatre rôles de guide."))
            else:
                ouvertes = await compter_ouvertes(self.g.id)
                lignes = [f"🟢 Installée · une carte par demande dans 🛟 Help et 🤝 Trade · "
                          f"{sum(ouvertes.values())} demande(s) en cours"]
                for z in ZONES.values():
                    r = role_zone(self.g, cf, z.cle)
                    qui = f" · {r.mention} ({len(r.members)})" if r else (" · rôle manquant" if z.role else "")
                    ping = " · 🔔" if prevenir(cf, z) else ""
                    lignes.append(f"{z.emoji} **{z.libelle}** · {expire_h(cf, z)} h{qui}{ping}")
                g_h = garder_h(cf)
                lignes.append("-# Les demandes closes disparaissent " + ("tout de suite (au passage suivant)" if not g_h
                                                                         else f"après {g_h} h")
                              + " ; leur historique reste sur le site.")
                items.append(discord.ui.TextDisplay("\n".join(lignes)))
            if self._note:
                items.append(discord.ui.TextDisplay(self._note))
            if installe:
                choix = Select(placeholder="Régler un type…", options=[
                    discord.SelectOption(label=z.libelle, value=z.cle, emoji=z.emoji, default=self.zone == z.cle)
                    for z in ZONES.values()])
                choix.callback = self._cb_zone
                items.append(discord.ui.ActionRow(choix))
                z = ZONES.get(self.zone)
                if z is not None:
                    if z.role:
                        rs = RoleSelect(placeholder=f"Rôle des {'middlemen' if z.certif == 'middleman' else 'guides'}"
                                                    f" · {z.libelle}", min_values=1, max_values=1)
                        rs.callback = self._cb_role
                        items.append(discord.ui.ActionRow(rs))
                    delai = Select(placeholder=f"Fermée après… · {z.nom}", options=[
                        discord.SelectOption(label=f"{h} h sans activité", value=str(h),
                                             default=h == expire_h(cf, z)) for h in DELAIS])
                    delai.callback = self._cb_delai
                    items.append(discord.ui.ActionRow(delai))
                    if z.certif == "guide":
                        b = Button(label="Prévenir les guides : " + ("oui" if prevenir(cf, z) else "non"),
                                   style=discord.ButtonStyle.secondary,
                                   emoji=visuels.icone("cloche" if prevenir(cf, z) else "cloche_off"))
                        b.callback = self._cb_ping
                        items.append(discord.ui.ActionRow(b))
                garder = Select(placeholder="Les demandes closes disparaissent…", options=[
                    discord.SelectOption(label="tout de suite" if h == 0 else f"après {h} h", value=str(h),
                                         default=h == garder_h(cf)) for h in GARDES])
                garder.callback = self._cb_garder
                items.append(discord.ui.ActionRow(garder))
            b_inst = Button(label="Réparer" if installe else "Installer", style=discord.ButtonStyle.primary,
                            emoji=visuels.icone("actualiser" if installe else "ajouter"))
            b_inst.callback = self._cb_installer
            boutons = [b_inst]
            if installe:
                b_rep = Button(label="Reposer les panneaux", style=discord.ButtonStyle.secondary,
                               emoji=visuels.icone("epingle"))
                b_rep.callback = self._cb_panneaux
                boutons.append(b_rep)
            r = Button(label="Retour", style=discord.ButtonStyle.secondary, emoji=visuels.icone("retour"))
            r.callback = self._cb_retour
            boutons.append(r)
            items.append(discord.ui.ActionRow(*boutons))
            self.clear_items()
            self.add_item(discord.ui.Container(*items, accent_color=discord.Color(0x0EA5E9)))
            if not edit:
                return await i.response.send_message(view=self, ephemeral=True)
            if i.response.is_done():
                await i.edit_original_response(content=None, view=self, embed=None, attachments=[])
            else:
                await i.response.edit_message(content=None, view=self, embed=None, attachments=[])
        except Exception as ex:
            _log("[ENTRAIDE][E8] panneau de configuration")
            _log(f"[ENTRAIDE][E8:DETAIL] {type(ex).__name__} {ex}")

    async def _cb_zone(self, i):
        await i.response.defer()
        self.zone, self._note = i.data["values"][0], ""
        await self.render_to(i)

    async def _cb_role(self, i):
        await i.response.defer()
        z, rid = ZONES[self.zone], int(i.data["values"][0])
        r = self.g.get_role(rid)
        if r is None or r.managed or r.is_default():
            self._note = "Ce rôle ne peut pas servir (rôle d'une application ou @everyone)."
            return await self.render_to(i)
        cf = await conf(self.g)
        cf["roles"][z.cle] = rid
        await _db_set(self.g.id, "rs_roles", cf["roles"])
        self._note = f"{z.emoji} {z.libelle} : {r.mention} certifie désormais."
        await assurer_panneaux(self.g, forcer=True)
        await self.render_to(i)

    async def _cb_delai(self, i):
        await i.response.defer()
        cf = await conf(self.g)
        expire = dict(cf["reglages"].get("expire") or {})
        expire[self.zone] = int(i.data["values"][0])
        await _regler(self.g, "expire", expire)
        self._note = ""
        await assurer_panneaux(self.g, forcer=True)
        await self.render_to(i)

    async def _cb_ping(self, i):
        await i.response.defer()
        cf = await conf(self.g)
        ping = dict(cf["reglages"].get("ping") or {})
        ping[self.zone] = not prevenir(cf, ZONES[self.zone])
        await _regler(self.g, "ping", ping)
        await self.render_to(i)

    async def _cb_garder(self, i):
        await i.response.defer()
        await _regler(self.g, "garder_h", int(i.data["values"][0]))
        await self.render_to(i)

    async def _cb_installer(self, i):
        cf = await conf(self.g)
        repare = cf["actif"]
        texte = ("Réparer l'entraide ? Ce qui manque est recréé (forums, rôles, posts épinglés) ; rien n'est "
                 "supprimé." if repare else
                 "Installer l'entraide ? Deux forums (🛟 help, 🤝 trade) dans la zone Rell Seas et quatre rôles de "
                 "guide ; rien n'est supprimé.")
        panneau = self

        async def _action(_i):
            try:
                faits = await (_installateur or installer)(panneau.g)
            except PermissionError as ex:
                return str(ex)
            except discord.HTTPException as ex:
                _log("[ENTRAIDE][E9] installation incomplète")
                _log(f"[ENTRAIDE][E9:DETAIL] {type(ex).__name__} {ex}")
                return "Installation incomplète : relance « Réparer » dans un instant."
            await _journal(panneau.g, "entraide.installation",
                           "Entraide Rell Seas " + ("réparée" if repare else "installée") +
                           (" : " + ", ".join(faits) if faits else " : rien ne manquait."), auteur_id=panneau.u.id)
            return ("Créé : " + ", ".join(faits) + ".") if faits else "Rien ne manquait : panneaux reposés."
        await i.response.send_message(view=vue_confirmer(texte, "Oui, " + ("réparer" if repare else "installer"),
                                                         _action, self.u.id, icone="valider",
                                                         style=discord.ButtonStyle.success), ephemeral=True)

    async def _cb_panneaux(self, i):
        await i.response.defer()
        await assurer_panneaux(self.g, forcer=True)
        self._note = "Panneaux reposés."
        await self.render_to(i)

    async def _cb_retour(self, i):
        if _retour is not None:
            await _retour(self.u, self.g, i)
        else:
            await i.response.defer()
