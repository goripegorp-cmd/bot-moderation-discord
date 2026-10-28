"""metiers.py — les rôles de métier du clan GoRP (RELL Seas), donnés et retirés tout seuls (25/10/2026).

Demandé par le fondateur : « en fonction des rôles et des attributs de chacun, par exemple, quand il crée un ticket
Rell Seas et qu'ils sont acceptés dans le clan, dès qu'il choisit un métier, j'aimerais que le métier soit créé sous
forme de rôle et que ça leur soit attribué. Une fois qu'ils ne font plus [partie du clan], soit ils n'ont plus le
rôle, soit ils ont été expulsés du clan par quelconque manière, ils perdent tout leur rôle qui font partie du clan. »

LE PARCOURS
  1. Acceptation au clan (`_decision_recrutement`, bot.py) : une carte dans le ticket dit au nouveau membre de choisir
     son métier dans le guide du clan (un bouton vers le post) — aucune mention de masse ; le lien part aussi dans le
     message privé de fermeture (le ticket disparaît quelques secondes plus tard).
  2. Le guide du clan (`zones.vue_guide_clan`) porte « Choisis ton métier · Pick your job » : la liste des métiers
     ACTIFS du catalogue (leur émoji d'application officiel s'il existe, jamais d'émoji Unicode), N au plus (réglage).
     Réservée aux membres qui ont le rôle du clan. Le choix va sur l'AFFICHE du membre (créée au minimum : le membre,
     son nom) ; la direction peut aussi le changer sur le site (Capitainerie → Affiches).
  3. Attribution automatique (OUI par défaut) : un métier choisi sans rôle lié → le bot CRÉE le rôle (le nom de la
     profession : Cuisinier, Artisan, Médecin… ; pour un métier ajouté plus tard sur le site, son nom du catalogue),
     SANS AUCUNE permission, d'une couleur sobre selon sa catégorie, juste sous le rôle du clan (jamais au-dessus du
     bot), avec l'icône officielle si le serveur a les icônes de rôle ; il le lie (`rell_roles`) et le donne. Un
     métier qu'il n'a plus → son rôle part. Jamais un autre rôle.
  4. Quitter le clan (le rôle du clan disparaît, peu importe comment) → TOUS les rôles du clan partent : ceux des
     métiers et les rôles rattachés au clan (réglage `clan_roles_rattaches`, ex. les grades). Revenir (le rôle du clan
     rendu) → ses métiers (son affiche) reviennent. Une sanction en cours (radiation, isolement, restriction) : RIEN ne
     bouge — la modération a retiré et gardé les rôles, et sa levée les rend (`_lever_radiation`,
     `_rendre_roles_isolement`, `/mod undirection`).
  5. Toutes les 30 minutes (`metiers_task`, bot.py) : la réconciliation rattrape ce qu'un redémarrage a manqué.

LES RÉGLAGES (site, Capitainerie → Rôles & métiers ; dans la configuration du serveur) : `metiers_auto` (OUI par
défaut), `metiers_max` (2 par défaut, 1 à 5), `clan_roles_rattaches` (des rôles). Rien ne bouge sans le rôle du clan
réglé (/configure → Rell Seas) : sans lui, aucun rôle n'est créé, donné ni retiré.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import io
import json
import re
import sys
import time
import unicodedata

import discord

import affiches
import tableau
import textes as textes_du_site
import visuels
from ui_v2 import LayoutView, Palette

TYPE = affiches.TYPE_METIER
MAX_DEFAUT, MAX_MIN, MAX_MAX = 2, 1, 5
RATTACHES_MAX = 20
OPTIONS_MAX = 24                # une liste Discord : 25 choix, dont « Aucun métier »
AUCUN = "_aucun"                # jamais une clé du catalogue (elles commencent par une lettre ou un chiffre)
CLE_AUTO, CLE_MAX, CLE_RATTACHES = "metiers_auto", "metiers_max", "clan_roles_rattaches"
#  26/10/2026 : le nom choisi sur le site pour le rôle d'un métier (Rôles & métiers → « Renommer ») — {clé: nom} ; il
#  sert aussi quand il faut recréer le rôle, et dans la liste du guide.
CLE_NOMS = "metiers_noms"
#  28/10/2026, le fondateur : « on choisit les places disponibles et la limite des places… ils ne peuvent pas choisir sur
#  le serveur… ils le décident dans le ticket… ça leur dit les places disponibles lors de la création du ticket. »
#  `metiers_places` {clé: places} (absent = sans limite) ; `metiers_au_ticket` (OUI par défaut) : le métier se choisit
#  dans la fiche du ticket de recrutement (un champ « Métier »), il est donné à l'acceptation s'il reste une place ; la
#  liste du guide du clan disparaît.
CLE_PLACES, CLE_TICKET = "metiers_places", "metiers_au_ticket"
PLACES_MAX = 500
CLE_BILAN = "metiers_derniere_reconciliation"
AVIS_S = 120.0                  # un mot pour soi s'efface au bout de 2 minutes
DEMARRE_S = 30.0
PAUSE_CHOIX_S = 3.0             # deux choix d'un même membre : au moins 3 s entre les deux
PAUSE_RECONCILIATION = 0.25     # entre deux membres corrigés : Discord n'est pas bousculé
GUIDE_APRES_S = 5.0             # une rafale de changements du catalogue : un seul guide réécrit
REESSAI_CREATION_S = 300.0      # Discord a refusé de créer un rôle : pas de nouvel essai avant 5 minutes
ICONE_COTE, ICONE_MAX = 128, 256 * 1024     # l'icône d'un rôle : Discord en accepte 256 Ko au plus
COULEUR_CARTE = 0x14B8A6        # la couleur du guide du clan
DETAILS_MAX = 50

#  Le nom de la profession (« un nom clair du métier en français ») : par la clé du catalogue, puis par son nom.
_PROFESSIONS = {
    "cooking": "Cuisinier", "cuisine": "Cuisinier",
    "thieving": "Voleur", "vol": "Voleur",
    "navigation": "Navigateur",
    "fishing": "Pêcheur", "peche": "Pêcheur",
    "crafting": "Artisan", "artisanat": "Artisan",
    "woodcutting": "Bûcheron", "bucheronnage": "Bûcheron",
    "doctor": "Médecin", "medecin": "Médecin",
    "mining": "Mineur", "minage": "Mineur",
    "shipwright": "Charpentier naval", "charpentier-naval": "Charpentier naval",
}
#  Des couleurs sobres (aucune teinte criarde), lisibles sur les deux thèmes de Discord, par catégorie du catalogue :
#  le premier mot connu de la catégorie décide (« Production · soutien » → production).
_COULEURS = (
    ({"recolte", "peche", "minage"}, 0x6F9A5D),            # vert sauge
    ({"production", "artisanat", "forge"}, 0xB08D57),       # laiton
    ({"soutien", "sante", "soin", "soins"}, 0xC0665E),      # cire claire
    ({"exploration", "navigation"}, 0x4F8A96),              # mer
    ({"navire", "construction"}, 0x9C7552),                 # bois
    ({"illegal", "furtivite"}, 0x857596),                   # prune grise
    ({"combat", "guerre"}, 0xB8742C),                       # ambre
)
COULEUR_DEFAUT = 0x9A8A74                                   # taupe

TEXTES = {
    "demarre": "Le bot démarre : réessaie dans quelques secondes.\n-# The bot is starting: try again in a few seconds.",
    "ferme": ("Le choix du métier n'est pas encore ouvert : la direction doit d'abord régler le rôle du clan.\n"
              "-# Job picking isn't open yet: the staff must set the clan role first."),
    "reserve": ("Réservé aux membres du clan GoRP : pour nous rejoindre, postule par ticket.\n"
                "-# GoRP clan members only: to join us, apply with a ticket."),
    "indisponible": "Indisponible pour le moment.\n-# Unavailable right now.",
    "retire": ("Ce métier n'est plus proposé : rouvre la liste du guide.\n"
               "-# This job isn't offered anymore: open the guide's list again."),
    "trop": "{n} métier(s) au plus : choisis de nouveau.\n-# Up to {n} job(s): pick again.",
    "rien": "Rien n'a été choisi.\n-# Nothing was picked.",
    "doucement": ("Doucement : ton choix précédent vient d'être enregistré, réessaie dans quelques secondes.\n"
                  "-# Easy: your previous choice was just saved, try again in a few seconds."),
    "souci": "Un souci est survenu : réessaie dans quelques secondes.\n-# Something went wrong: try again in a few seconds.",
    "au_ticket": ("Le métier se choisit dans le ticket de recrutement, selon les places libres : la direction l'attribue.\n"
                  "-# Your job is picked in the recruitment ticket, by open spots: the staff assigns it."),
}

#  Les textes que la direction réécrit (26/10/2026 : Capitainerie → Textes & noms, registre `textes.py`) : la section
#  « Ton métier » du guide du clan, la carte de l'acceptation, la ligne du message privé de fermeture.
_GUIDE, _ACCEPTATION = "Le choix du métier (guide du clan)", "L'acceptation au clan"
_declarer = functools.partial(textes_du_site.declarer, groupe="metiers")
_declarer("metiers.guide.titre", "Ton métier · Your job", titre="Le titre de la section", partie=_GUIDE, ordre=1,
          max_=100, lignes=False, aide="Dans le guide du clan, au-dessus de la liste des métiers (l'icône du navire "
                                       "se pose devant).")
_declarer("metiers.guide.texte_auto",
          "Choisis {combien} dans la liste : ton affiche du clan et tes rôles de métier suivent ton choix. Tu peux en "
          "changer quand tu veux.\n-# Pick {combien_en}: your clan poster and your job roles follow your choice. "
          "Change anytime.", titre="Le texte (rôles donnés tout seuls)", partie=_GUIDE, ordre=2, max_=800,
          variables=(("combien", "« ton métier » ou « jusqu'à 2 métiers »"),
                     ("combien_en", "le même, en anglais")),
          aide="Sous le titre, quand l'attribution automatique des rôles de métier est active.")
_declarer("metiers.guide.texte_manuel",
          "Choisis {combien} dans la liste : ton affiche du clan suit ton choix ; la direction attribue les rôles des "
          "métiers.\n-# Pick {combien_en}: your clan poster follows your choice; the staff hands out job roles.",
          titre="Le texte (rôles donnés par la direction)", partie=_GUIDE, ordre=3, max_=800,
          variables=(("combien", "« ton métier » ou « jusqu'à 2 métiers »"),
                     ("combien_en", "le même, en anglais")),
          aide="Sous le titre, quand l'attribution automatique est coupée.")
_declarer("metiers.guide.liste", "Choisis ton métier · Pick your job", titre="La liste « Choisis ton métier »",
          partie=_GUIDE, ordre=4, max_=150, lignes=False, aide="Le texte gris de la liste, avant le choix.")
_declarer("metiers.guide.aucun", "Aucun métier · No job", titre="Le choix « Aucun métier »", partie=_GUIDE, ordre=5,
          max_=100, lignes=False, aide="Le dernier choix de la liste : retirer ses métiers.")
_declarer("metiers.carte.auto",
          "### Bienvenue dans l'équipage · Welcome aboard\n{membre}, dernière étape : choisis ton métier dans le **guide "
          "du clan** — ton rôle de métier t'est donné tout de suite.\n-# Last step: pick your job in the clan guide — "
          "your job role is given right away.", titre="La carte (rôles donnés tout seuls)", partie=_ACCEPTATION,
          ordre=10, max_=1200, variables=(("membre", "la mention du nouveau membre"),),
          aide="Postée dans le ticket quand une candidature est acceptée, juste avant la fermeture.")
_declarer("metiers.carte.manuel",
          "### Bienvenue dans l'équipage · Welcome aboard\n{membre}, dernière étape : choisis ton métier dans le **guide "
          "du clan**.\n-# Last step: pick your job in the clan guide.", titre="La carte (rôles donnés par la direction)",
          partie=_ACCEPTATION, ordre=11, max_=1200, variables=(("membre", "la mention du nouveau membre"),),
          aide="La même carte, quand l'attribution automatique est coupée.")
_declarer("metiers.carte.bouton", "Choisir mon métier · Pick my job", titre="Le bouton de la carte",
          partie=_ACCEPTATION, ordre=12, max_=80, lignes=False, aide="Il mène au guide du clan.")
_declarer("metiers.carte.attribue",
          "### Bienvenue dans l'équipage · Welcome aboard\n{membre}, ton métier : **{metier}**. Ton rôle de métier t'est donné."
          "\n-# Your job: {metier}. Your job role is given.", titre="La carte (métier choisi au ticket, attribué)",
          partie=_ACCEPTATION, ordre=14, max_=1200, variables=(("membre", "la mention du nouveau membre"), ("metier", "le métier")),
          aide="Le métier choisi dans la fiche avait encore une place : il est attribué à l'acceptation.")
_declarer("metiers.carte.complet",
          "### Bienvenue dans l'équipage · Welcome aboard\n{membre}, la dernière place en **{metier}** vient d'être prise : la "
          "direction t'attribue un métier.\n-# The last {metier} spot was just taken: the staff will assign your job.",
          titre="La carte (plus de place dans le métier choisi)", partie=_ACCEPTATION, ordre=15, max_=1200,
          variables=(("membre", "la mention du nouveau membre"), ("metier", "le métier")),
          aide="Entre la fiche et l'acceptation, le métier choisi s'est rempli.")
_declarer("metiers.carte.sans",
          "### Bienvenue dans l'équipage · Welcome aboard\n{membre}, la direction t'attribue ton métier selon les places libres."
          "\n-# The staff assigns your job by open spots.", titre="La carte (aucun métier choisi dans la fiche)",
          partie=_ACCEPTATION, ordre=16, max_=1200, variables=(("membre", "la mention du nouveau membre"),),
          aide="La fiche n'avait pas de champ « Métier », ou aucune place n'était libre.")
_declarer("metiers.fiche.places", "{n} place(s) libre(s)", titre="Sous chaque métier de la fiche", partie=_ACCEPTATION,
          ordre=17, max_=100, lignes=False, variables=(("n", "le nombre de places libres"),),
          aide="Dans la liste « Métier » de la fiche du ticket, sous le nom du métier.")
_declarer("metiers.fiche.libre", "Places libres", titre="Sous un métier sans limite", partie=_ACCEPTATION, ordre=18,
          max_=100, lignes=False, aide="Un métier sans nombre de places réglé.")
_declarer("metiers.fiche.recap", "**Métiers ouverts** : {liste}", titre="La ligne des places (avant la fiche)",
          partie=_ACCEPTATION, ordre=19, max_=600, lignes=False, variables=(("liste", "« Cuisinier 2 · Artisan 1 … »"),),
          aide="Ajoutée à « Es-tu sûr ? » : les métiers et leurs places libres.")
_declarer("metiers.fiche.complet", "**Métiers** : aucune place libre pour le moment, la direction t'en attribuera un.",
          titre="La ligne des places (tout est pris)", partie=_ACCEPTATION, ordre=20, max_=300, lignes=False,
          aide="Ajoutée à « Es-tu sûr ? » quand aucun métier n'a de place libre.")
_declarer("metiers.mp_lien", "choisis ton métier dans le guide du clan (pick your job) : {lien}",
          titre="La ligne du message privé", partie=_ACCEPTATION, ordre=13, max_=300, lignes=False,
          variables=(("lien", "le lien du guide du clan"),),
          aide="Ajoutée à la raison de fermeture (« Candidature acceptée · … ») dans le message privé du nouveau membre.")


#  Les réponses au choix du métier, pour la personne seule (elles s'effacent) : chacune réécrite à part.
_REPONSES = "Les réponses au choix (pour la personne seule)"
_AVIS = {"reserve": ("Réservé au clan", "Quelqu'un hors du clan choisit un métier dans le guide."),
         "ferme": ("Choix pas encore ouvert", "Le rôle du clan n'est pas encore réglé sur le site."),
         "indisponible": ("Indisponible", "Le serveur n'est pas lisible, ou le membre est sanctionné."),
         "retire": ("Métier retiré", "Il choisit un métier qui n'est plus au catalogue."),
         "trop": ("Trop de métiers", "Il en choisit plus que le nombre permis."),
         "rien": ("Rien de choisi", "La liste refermée sans choix."),
         "doucement": ("Doucement", "Deux choix coup sur coup."),
         "demarre": ("Le bot démarre", "Un choix pendant le démarrage du bot."),
         "souci": ("Un souci", "Une erreur imprévue (elle est aussi notée au journal du bot)."),
         "au_ticket": ("Choix au ticket", "Quelqu'un touche l'ancienne liste du guide alors que le métier se choisit au ticket.")}
for _k, (_titre, _aide) in _AVIS.items():
    _declarer(f"metiers.avis.{_k}", TEXTES[_k], titre=_titre, partie=_REPONSES, ordre=40 + list(_AVIS).index(_k),
              max_=600, aide=_aide, variables=(("n", "le nombre de métiers permis"),) if _k == "trop" else ())
_METIERS_VARS = (("metiers", "les métiers choisis, en gras (« **Cuisinier**, **Pêcheur** »)"),
                 ("metiers_en", "les mêmes, en anglais"))
for _k, (_defaut, _titre, _aide, _vars) in enumerate((
        ("C'est noté : {metiers}. Ton affiche du clan est à jour et tes rôles de métier suivent.\n-# Noted: "
         "{metiers_en}. Your clan poster is up to date and your job roles follow.", "Choix noté (rôles donnés tout seuls)",
         "Après un choix, quand l'attribution automatique des rôles de métier est active.", _METIERS_VARS),
        ("C'est noté : {metiers}. Ton affiche du clan est à jour ; la direction attribue les rôles des métiers.\n-# "
         "Noted: {metiers_en}. Your clan poster is up to date; the staff hands out job roles.",
         "Choix noté (rôles donnés par la direction)", "Après un choix, quand l'attribution automatique est coupée.",
         _METIERS_VARS),
        ("C'est déjà ton choix : {metiers}. Ton affiche du clan est à jour et tes rôles de métier suivent.\n-# Already "
         "your choice: {metiers_en}. Your clan poster is up to date and your job roles follow.",
         "Déjà son choix (rôles donnés tout seuls)", "Il choisit de nouveau les mêmes métiers.", _METIERS_VARS),
        ("C'est déjà ton choix : {metiers}. Ton affiche du clan est à jour ; la direction attribue les rôles des "
         "métiers.\n-# Already your choice: {metiers_en}. Your clan poster is up to date; the staff hands out job roles.",
         "Déjà son choix (rôles donnés par la direction)", "Les mêmes métiers, attribution automatique coupée.",
         _METIERS_VARS),
        ("C'est noté : tu n'as plus de métier. Tes rôles de métier sont retirés.\n-# Noted: no job anymore. Your job "
         "roles are removed.", "Plus de métier (rôles retirés tout seuls)", "Il choisit « Aucun métier ».", ()),
        ("C'est noté : tu n'as plus de métier.\n-# Noted: no job anymore.", "Plus de métier (rôles gérés par la "
         "direction)", "« Aucun métier », attribution automatique coupée.", ()),
        ("Ton choix est bien noté, mais un rôle n'a pas pu être posé (permission ou hiérarchie) : la direction le voit "
         "sur le site.\n-# Your choice is saved, but a role couldn't be given (permission or hierarchy): the staff sees "
         "it.", "Un rôle n'a pas pu être posé", "Ajouté sous la réponse quand Discord refuse un rôle de métier.", ()))):
    _cle = ("note_auto", "note_manuel", "deja_auto", "deja_manuel", "aucun_auto", "aucun_manuel", "role_manquant")[_k]
    _declarer(f"metiers.choix.{_cle}", _defaut, titre=_titre, partie=_REPONSES, ordre=30 + _k, max_=800, aide=_aide,
              variables=_vars)


def _t(guild_id, cle: str, **valeurs) -> str:
    """Un texte que la direction peut réécrire (Textes & noms) : celui du serveur, sinon celui d'origine."""
    return textes_du_site.texte_cache(guild_id, cle, **valeurs)


def _reponse(i, cle: str, **valeurs) -> str:
    """Une réponse au choix du métier (Textes & noms) : celle du serveur de l'interaction, sinon celle d'origine."""
    return _t(getattr(getattr(i, "guild", None), "id", 0), f"metiers.avis.{cle}", **valeurs)

_get_db = _cfg = _db_set = _role_clan = _sanctionnes = _journal = _guide = _epargnes = None
_log = print
_verrous: dict = {}
_derniers_choix: dict = {}
_guides_prevus: dict = {}
_echecs_creation: dict = {}     # (serveur, métier) → quand Discord a refusé la création
_erreurs_vues: dict = {}        # (serveur, membre) → la dernière erreur notée (jamais la même ligne toutes les 30 min)
_taches: set = set()


def setup(*, get_db, cfg, db_set, role_clan, sanctionnes=None, journal=None, guide=None, epargnes=None, log=None):
    """`role_clan(g, c)` → le rôle du clan (ou None) ; `sanctionnes(g)` (async) → les identifiants des membres sous
    sanction (leurs rôles ne bougent pas) ; `journal(g, type_, texte, **kw)` (async) → le journal du site, catégorie
    « Clan » ; `guide(g)` (async) → réécrit le guide du clan (le choix du métier suit le catalogue et les réglages) ;
    `epargnes(g, membre)` → les comptes de tête, à qui aucun rôle n'est jamais retiré automatiquement."""
    global _get_db, _cfg, _db_set, _role_clan, _sanctionnes, _journal, _guide, _epargnes, _log
    _get_db, _cfg, _db_set, _role_clan = get_db, cfg, db_set, role_clan
    _sanctionnes, _journal, _guide, _epargnes, _log = sanctionnes, journal, guide, epargnes, log or print
    for memoire in (_verrous, _derniers_choix, _guides_prevus, _echecs_creation, _erreurs_vues):
        memoire.clear()
    affiches.brancher_metiers(sys.modules[__name__])


def pret() -> bool:
    return _get_db is not None and _cfg is not None


def _verrou(cle) -> asyncio.Lock:
    """Un verrou par clé et par boucle d'évènements (un verrou né dans une autre boucle y lèverait une erreur)."""
    boucle = asyncio.get_running_loop()
    deja = _verrous.get(cle)
    if deja is None or deja[0] is not boucle:
        deja = _verrous[cle] = (boucle, asyncio.Lock())
    return deja[1]


def _verrou_membre(guild_id: int, membre_id: int) -> asyncio.Lock:
    """Les rôles d'un membre : une seule main à la fois (son choix, le départ du clan, la réconciliation)."""
    return _verrou(("membre", int(guild_id), int(membre_id)))


def _signaler(code: str, message: str, detail: str = "") -> None:
    _log(f"[METIERS][{code}] {message}")
    if detail:
        _log(f"[METIERS][{code}:DETAIL] {detail}")


async def _noter(g, type_: str, texte: str, **kw) -> None:
    """Le journal du site (catégorie « Clan ») : une phrase lisible ; il ne fait jamais échouer ce qui est fait."""
    if _journal is None:
        return
    try:
        await _journal(g, type_, texte, **kw)
    except Exception as ex:
        _signaler("E11", "journal du site non écrit", f"{type_} {type(ex).__name__} {ex}")


async def _noter_panne(g, membre, type_: str, panne: tuple, texte: str) -> None:
    """Une panne notée UNE fois (la même ne s'écrit pas toutes les 30 minutes) ; `panne` vide : tout va bien."""
    cle = (g.id, membre.id, type_)
    if not any(panne):
        _erreurs_vues.pop(cle, None)
    elif _erreurs_vues.get(cle) != panne:
        _erreurs_vues[cle] = panne
        await _noter(g, type_, texte, membre_id=membre.id, gravite=1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Les réglages, le rôle du clan, les sanctions
# ═══════════════════════════════════════════════════════════════════════════════

def reglages_de(c: dict) -> dict:
    """`{"auto", "max", "rattaches"}` lus dans la configuration du serveur (valeurs par défaut : OUI, 2, aucun)."""
    auto = c.get(CLE_AUTO)
    try:
        maxi = int(c.get(CLE_MAX) or MAX_DEFAUT)
    except (TypeError, ValueError):
        maxi = MAX_DEFAUT
    rattaches = [int(x) for x in (c.get(CLE_RATTACHES) or []) if str(x).isdigit() and int(x) > 0]
    places = {}
    for k, v in (c.get(CLE_PLACES) or {}).items() if isinstance(c.get(CLE_PLACES), dict) else ():
        if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= PLACES_MAX:
            places[k] = v
    ticket = c.get(CLE_TICKET)
    return {"auto": True if auto is None else bool(auto), "max": max(MAX_MIN, min(MAX_MAX, maxi)),
            "rattaches": list(dict.fromkeys(rattaches))[:RATTACHES_MAX], "places": places,
            "ticket": True if ticket is None else bool(ticket)}


async def reglages(g) -> dict:
    return reglages_de(await _cfg(g.id))


async def max_metiers(g) -> int:
    return (await reglages(g))["max"]


async def role_du_clan(g, c: dict | None = None):
    """Le rôle du clan (/configure → Rell Seas, « Rôle attribué »), ou None."""
    if _role_clan is None or g is None:
        return None
    try:
        return _role_clan(g, c if c is not None else await _cfg(g.id))
    except Exception as ex:
        _signaler("E10", "rôle du clan illisible", f"{type(ex).__name__} {ex}")
        return None


async def gere(g) -> bool:
    """Les rôles des métiers suivent le clan (le module est branché et le rôle du clan est réglé)."""
    return pret() and await role_du_clan(g) is not None


def _du_clan(membre, clan) -> bool:
    return clan is not None and any(getattr(r, "id", None) == clan.id for r in getattr(membre, "roles", []) or [])


async def _sanctionnes_de(g) -> set | None:
    """Les membres sous sanction — None si on ne peut pas le savoir : dans le doute, on ne touche à rien."""
    if _sanctionnes is None:
        return set()
    try:
        return {int(x) for x in await _sanctionnes(g)}
    except Exception as ex:
        _signaler("E7", "sanctions illisibles : rôles du clan laissés tels quels", f"serveur={g.id} {type(ex).__name__} {ex}")
        return None


async def sous_sanction(g, membre) -> bool:
    s = await _sanctionnes_de(g)
    return s is None or membre.id in s


async def epargne(g, membre) -> bool:
    """Le fondateur et la direction (les comptes de tête) : aucun rôle ne leur est retiré automatiquement — comme
    partout sur le site, ils sont hors d'atteinte des automatismes."""
    if _epargnes is None or membre is None:
        return False
    try:
        r = _epargnes(g, membre)
        return bool(await r) if asyncio.iscoroutine(r) else bool(r)
    except Exception as ex:  # dans le doute, on épargne : ne rien retirer n'abîme rien
        _signaler("E12", "comptes épargnés illisibles", f"{type(ex).__name__} {ex}")
        return True


def _haut_du_bot(g) -> int:
    return int(getattr(getattr(getattr(g, "me", None), "top_role", None), "position", 0) or 0)


def _amovible(g, role) -> bool:
    """Un rôle que le bot peut retirer : ni @everyone, ni géré par une intégration, sous son rôle le plus haut."""
    if role is None or getattr(role, "managed", False) or getattr(role, "id", None) == getattr(g, "id", None):
        return False
    if getattr(role, "is_default", lambda: False)():
        return False
    return int(getattr(role, "position", 0) or 0) < _haut_du_bot(g)


# ═══════════════════════════════════════════════════════════════════════════════
#  Les métiers du catalogue, le nom et la couleur de leur rôle
# ═══════════════════════════════════════════════════════════════════════════════

async def metiers_du_catalogue(actifs: bool = True) -> list[dict]:
    """Les métiers du catalogue RELL Seas (les actifs seulement, par défaut), dans l'ordre du catalogue."""
    types, elements = await affiches._catalogue()
    if TYPE not in types:
        return []
    out = [e for (t, _c), e in elements.items() if t == TYPE and (e["actif"] or not actifs)]
    return sorted(out, key=lambda e: (int(e["ordre"]), e["nom"].casefold(), e["cle"]))


def _norme(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def noms_choisis(c: dict) -> dict:
    """{clé du métier : nom de son rôle} choisis sur le site (Rôles & métiers → « Renommer »)."""
    brut = c.get(CLE_NOMS) if isinstance(c, dict) else None
    if not isinstance(brut, dict):
        return {}
    return {str(k): " ".join(str(v).split())[:100] for k, v in brut.items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()}


async def retenir_noms(g, noms: dict) -> None:
    """Le nom choisi pour le rôle de ces métiers : gardé dans la configuration du serveur (il sert à la prochaine
    création du rôle et dans la liste du guide)."""
    c = await _cfg(g.id)
    actuels = noms_choisis(c)
    actuels.update({str(k): " ".join(str(v).split())[:100] for k, v in noms.items() if str(v).strip()})
    await _db_set(g.id, CLE_NOMS, actuels)


def nom_du_role(e: dict, noms: dict | None = None) -> str:
    """« Un nom clair du métier en français — un nom de profession » : Cuisinier, Artisan, Médecin… — reconnu par la
    clé, le nom ou le nom anglais que donne le catalogue (aucune clé n'est supposée présente) ; pour un métier ajouté
    plus tard sur le site, son nom du catalogue. 26/10/2026 : le nom choisi sur le site (`noms`, « Renommer ») passe
    avant tout."""
    if noms and str(e.get("cle") or "") in noms:
        return noms[str(e.get("cle"))][:100]
    for k in (e.get("cle"), _norme(e.get("nom")), _norme(e.get("nom_en"))):
        if k in _PROFESSIONS:
            return _PROFESSIONS[k]
    return str(e.get("nom") or e.get("cle") or "Métier")[:100]


def couleur_du_role(e: dict) -> int:
    for mot in _norme(e.get("categorie")).split("-"):
        for mots, couleur in _COULEURS:
            if mot in mots:
                return couleur
    return COULEUR_DEFAUT


def _emoji(cle: str) -> str:
    """L'émoji d'application de l'icône officielle du métier (installé par `visuels`), sinon rien — jamais Unicode."""
    return affiches._emoji_jeu(TYPE, cle)


def _icone_maison(nom: str) -> str:
    """Une icône maison (émoji d'application) — vide tant qu'elle n'est pas installée (pas de repli Unicode)."""
    e = visuels.icone(nom)
    return str(e) if getattr(e, "id", None) else ""


async def options_selecteur(g=None) -> list[dict]:
    """Les choix de la liste du guide : `{"cle", "label", "description", "emoji"}` par métier actif (24 au plus)."""
    out = []
    noms = noms_choisis(await _cfg(g.id)) if g is not None and _cfg is not None else {}
    for e in (await metiers_du_catalogue())[:OPTIONS_MAX]:
        nom, en = nom_du_role(e, noms), str(e.get("nom_en") or "")
        label = f"{nom} · {en}" if en and _norme(en) != _norme(nom) else nom
        out.append({"cle": e["cle"], "label": label[:100], "description": str(e.get("categorie") or "")[:100],
                    "emoji": _emoji(e["cle"])})
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Les places (28/10/2026) : le métier se choisit dans la fiche du ticket
# ═══════════════════════════════════════════════════════════════════════════════

async def occupes(g, c: dict | None = None) -> dict:
    """{clé du métier : membres du clan dont l'affiche porte ce métier}."""
    c = c if c is not None else await _cfg(g.id)
    clan = await role_du_clan(g, c)
    dans_clan = {m.id for m in getattr(clan, "members", []) or []} if clan is not None else None
    out: dict = {}
    for a in await affiches._affiches(g.id):
        if a["retire_le"] or (dans_clan is not None and int(a["membre_id"] or 0) not in dans_clan):
            continue
        for cle in a["attributs"].get(TYPE) or []:
            out[cle] = out.get(cle, 0) + 1
    return out


async def places(g, c: dict | None = None) -> list:
    """Chaque métier actif : `{"cle", "nom", "limite" (None : sans limite), "occupes", "libres" (None : sans limite)}`."""
    c = c if c is not None else await _cfg(g.id)
    reg, noms, pris = reglages_de(c), noms_choisis(c), await occupes(g, c)
    out = []
    for e in (await metiers_du_catalogue())[:OPTIONS_MAX]:
        limite = reg["places"].get(e["cle"])
        n = pris.get(e["cle"], 0)
        out.append({"cle": e["cle"], "nom": nom_du_role(e, noms), "limite": limite, "occupes": n,
                    "libres": None if limite is None else max(0, limite - n), "emoji": _emoji(e["cle"])})
    return out


async def champs_avec_places(g, champs: list) -> tuple:
    """La fiche du ticket : chaque champ « metier » devient une liste des métiers qui ont une place libre (leur nombre de
    places sous le nom). → (les champs, la ligne des places pour « Es-tu sûr ? », "" sans champ « metier »)."""
    if not any(isinstance(ch, dict) and ch.get("type") == "metier" for ch in champs or []) or g is None or not pret():
        return [ch for ch in champs or [] if ch.get("type") != "metier"], ""
    c = await _cfg(g.id)
    ouverts = [p for p in await places(g, c) if p["libres"] is None or p["libres"] > 0]
    out = []
    for ch in champs:
        if ch.get("type") != "metier":
            out.append(ch)
        elif ouverts:
            out.append(dict(ch, type="choix", options=[p["nom"][:100] for p in ouverts], eliminatoires=[],
                            descriptions=[_t(g.id, "metiers.fiche.libre") if p["libres"] is None
                                          else _t(g.id, "metiers.fiche.places", n=p["libres"]) for p in ouverts],
                            cles=[p["cle"] for p in ouverts]))
    if not ouverts:
        return out, _t(g.id, "metiers.fiche.complet")
    liste = " · ".join(p["nom"] + ("" if p["libres"] is None else f" {p['libres']}") for p in ouverts)
    return out, _t(g.id, "metiers.fiche.recap", liste=liste)


def metier_des_reponses(metiers: list, reponses: dict, noms: dict) -> dict | None:
    """FONCTION PURE : le métier choisi dans la fiche (une réponse égale au nom d'un métier actif), ou None."""
    par_nom = {}
    for e in metiers:
        for n in (nom_du_role(e, noms), e.get("nom"), e.get("nom_en")):
            if n:
                par_nom.setdefault(_norme(n), e)
    for v in (reponses or {}).values():
        e = par_nom.get(_norme(v))
        if e is not None:
            return e
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rôle d'un métier : lié, relié par son nom, ou créé
# ═══════════════════════════════════════════════════════════════════════════════

async def _liens_metiers(guild_id: int) -> dict:
    """{clé du métier : identifiant du rôle lié}."""
    return {x["cle"]: x["role_id"] for x in await affiches._liens(guild_id) if x["type"] == TYPE}


async def _lier(guild_id: int, cle: str, role_id: int, par: int) -> None:
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO rell_roles (guild_id, type, cle, role_id, auto, maj_le, maj_par)"
                         " VALUES (?,?,?,?,1,?,?)", (int(guild_id), TYPE, cle, int(role_id), int(time.time()), int(par)))
        await db.commit()


async def ids_roles_clan(g, c: dict | None = None) -> set:
    """Les « rôles du clan » : ceux des métiers (liés) et les rôles rattachés au clan (réglage) — qui existent."""
    c = c if c is not None else await _cfg(g.id)
    ids = set((await _liens_metiers(g.id)).values()) | set(reglages_de(c)["rattaches"])
    clan = await role_du_clan(g, c)
    return {i for i in ids if g.get_role(i) is not None and (clan is None or i != clan.id)}


def _role_du_meme_nom(g, nom: str, exclus: set):
    """Un rôle qui porte déjà ce nom et que rien d'autre n'utilise : relié plutôt qu'un doublon (un lien défait sur le
    site laisse le rôle sur Discord)."""
    cible = nom.casefold()
    for r in sorted(getattr(g, "roles", []) or [], key=lambda r: -int(getattr(r, "position", 0) or 0)):
        if str(getattr(r, "name", "")).casefold() == cible and r.id not in exclus and affiches.refus_role(g, r) is None:
            return r
    return None


async def role_du_metier(g, cle: str, *, creer: bool = True, auteur=None):
    """(le rôle du métier, ce qui s'est passé) — `deja` (lié), `relie` (un rôle du même nom), `cree` ; ou (None, la
    raison : `refuse` le rôle lié ne se donne pas, `absent` sans création, `inconnu`, `droits`, `echec`)."""
    c = await _cfg(g.id)
    clan = await role_du_clan(g, c)

    def utilisable(r) -> bool:   # jamais le rôle du clan : changer de métier sortirait le membre du clan
        return affiches.refus_role(g, r) is None and (clan is None or r.id != clan.id)
    liens = await _liens_metiers(g.id)
    role = g.get_role(liens[cle]) if cle in liens else None
    if role is not None:
        return (role, "deja") if utilisable(role) else (None, "refuse")
    if not creer:
        return None, "absent"
    async with _verrou(("creation", g.id, cle)):
        liens = await _liens_metiers(g.id)          # relu sous le verrou : deux choix en même temps, un seul rôle
        role = g.get_role(liens[cle]) if cle in liens else None
        if role is not None:
            return (role, "deja") if utilisable(role) else (None, "refuse")
        _t, elements = await affiches._catalogue()
        e = elements.get((TYPE, cle))
        if e is None or not e["actif"]:
            return None, "inconnu"
        nom = nom_du_role(e, noms_choisis(c))
        exclus = set(liens.values()) | set(reglages_de(c)["rattaches"]) | ({clan.id} if clan is not None else set())
        role = _role_du_meme_nom(g, nom, exclus)
        etat = "relie"
        if role is None:
            if not affiches._peut_gerer_roles(g):
                _signaler("E1", "rôle du métier non créé : permission « Gérer les rôles » absente", f"serveur={g.id} {cle}")
                return None, "droits"
            if time.monotonic() - _echecs_creation.get((g.id, cle), -1e9) < REESSAI_CREATION_S:
                return None, "echec"
            role = await _creer_role(g, e, nom, clan)
            if role is None:
                _echecs_creation[(g.id, cle)] = time.monotonic()
                return None, "echec"
            _echecs_creation.pop((g.id, cle), None)
            etat = "cree"
        await _lier(g.id, cle, role.id, getattr(auteur, "id", 0) or 0)
    if etat == "cree":
        await _noter(g, "clan.metier_role", f"Rôle « {role.name} » créé pour le métier « {e['nom']} » (sans permission,"
                                            " sous le rôle du clan)", auteur_id=getattr(auteur, "id", 0) or 0)
    else:
        await _noter(g, "clan.metier_role", f"Rôle « {role.name} » relié au métier « {e['nom']} »",
                     auteur_id=getattr(auteur, "id", 0) or 0)
    return role, etat


async def _creer_role(g, e: dict, nom: str, clan):
    """Le rôle neuf : AUCUNE permission, couleur sobre de sa catégorie, ni affiché à part ni mentionnable, l'icône
    officielle si le serveur a les icônes de rôle ; posé juste sous le rôle du clan. None si Discord refuse."""
    raison = f"Métier « {e['nom']} » choisi dans le clan GoRP : rôle du métier"[:400]
    kw = dict(name=nom, colour=discord.Colour(couleur_du_role(e)), permissions=discord.Permissions.none(), hoist=False,
              mentionable=False, reason=raison)
    icone = await icone_du_role(e) if "ROLE_ICONS" in (getattr(g, "features", None) or []) else None
    try:
        role = await (g.create_role(**kw, display_icon=icone) if icone else g.create_role(**kw))
    except discord.HTTPException as ex:
        if icone is None:
            _signaler("E1", "rôle du métier non créé", f"serveur={g.id} {e['cle']} {type(ex).__name__} {ex}")
            return None
        _signaler("E5", "icône du rôle refusée : rôle créé sans icône", f"serveur={g.id} {e['cle']} {type(ex).__name__} {ex}")
        try:
            role = await g.create_role(**kw)
        except discord.HTTPException as ex2:
            _signaler("E1", "rôle du métier non créé", f"serveur={g.id} {e['cle']} {type(ex2).__name__} {ex2}")
            return None
    await placer_sous_le_clan(g, role, clan)
    return role


async def placer_sous_le_clan(g, role, clan) -> bool:
    """Le rôle juste sous le rôle du clan, l'ordre de tous les autres gardé : les positions sont renumérotées du bas
    jusqu'au nouveau rôle, puis au-dessus seulement tant que deux positions se touchent (Discord laisse des positions
    à égalité). Jamais le rôle du bot ni au-dessus. Le clan au-dessus du bot (il ne pourrait pas le donner) : le rôle
    reste en bas."""
    moi = getattr(getattr(g, "me", None), "top_role", None)
    if clan is None or moi is None or int(getattr(clan, "position", 0) or 0) >= _haut_du_bot(g):
        if clan is not None:
            _signaler("E4", "rôle du clan au-dessus du bot : rôle du métier laissé en bas", f"serveur={g.id}")
        return False
    try:
        roles = list(await g.fetch_roles())            # les positions à jour (le cache peut avoir un temps de retard)
    except (discord.HTTPException, AttributeError):
        roles = list(getattr(g, "roles", []) or [])
    actuelles = {r.id: int(r.position) for r in roles}
    actuelles.setdefault(role.id, int(getattr(role, "position", 1) or 1))
    ordre = sorted((r for r in roles if r.id != role.id and r.id != g.id and not r.is_default()),
                   key=lambda r: (int(r.position), -int(r.id)))   # du bas vers le haut, comme Discord les range
    ids = [r.id for r in ordre]
    if clan.id not in ids:
        return False
    k = ids.index(clan.id)
    voulu = ids[:k] + [role.id] + ids[k:]
    positions, precedente = {}, 0
    for n, rid in enumerate(voulu):
        if n > k and actuelles[rid] > precedente:
            break                                       # déjà au-dessus : tout ce qui suit l'est aussi
        if rid == moi.id:
            _signaler("E4", "rôles serrés jusqu'au rôle du bot : rôle du métier laissé en bas", f"serveur={g.id}")
            return False
        precedente += 1
        if actuelles[rid] != precedente:
            positions[rid] = precedente
    if not positions:
        return True
    try:
        await g.edit_role_positions(positions={discord.Object(id=rid): n for rid, n in positions.items()},
                                    reason="Rôle de métier : juste sous le rôle du clan")
        return True
    except discord.HTTPException as ex:
        _signaler("E4", "rôle du métier non déplacé", f"serveur={g.id} {type(ex).__name__} {ex}")
        return False


async def icone_du_role(e: dict) -> bytes | None:
    """L'icône officielle du métier en PNG carré (128 px, 256 Ko au plus) : l'émoji d'application du jeu
    (`visuels/icones/rell_…png`), sinon l'icône du catalogue (`s/icones/…` du site, ou une image envoyée)."""
    data = None
    for nom in (f"rell_{TYPE}_{e['cle']}", f"rell_{e['cle']}"):
        p = visuels.DOSSIER / "icones" / f"{nom.replace('-', '_')[:32]}.png"
        if p.is_file():
            try:
                data = await asyncio.to_thread(p.read_bytes)
            except OSError:
                data = None
            if data:
                break
    icone = str(e.get("icone") or "")
    if not data and icone.startswith("s/"):
        chemin = tableau._chemin_statique(icone[2:])
        lu = tableau._lire_statique(chemin[0]) if chemin else None
        data = lu[0] if lu else None
    elif not data and icone.startswith("media/"):
        lu = await tableau.lire_media(icone[len("media/"):])
        data = lu[0] if lu else None
    if not data:
        return None
    return await asyncio.to_thread(_png_carre, data)


def _png_carre(data: bytes) -> bytes | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP", "GIF") or im.width * im.height > 4096 * 4096:
                return None
            im.seek(0)
            source = im.convert("RGBA")
        for cote in (ICONE_COTE, 64):
            image = source.copy()
            image.thumbnail((cote, cote), Image.Resampling.LANCZOS)
            toile = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
            toile.paste(image, ((cote - image.width) // 2, (cote - image.height) // 2))
            sortie = io.BytesIO()
            toile.save(sortie, "PNG", optimize=True)
            if sortie.tell() <= ICONE_MAX:
                return sortie.getvalue()
    except Exception as ex:  # image illisible : le rôle se crée sans icône
        _signaler("E5", "icône du métier illisible", f"{type(ex).__name__} {ex}")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Donner, retirer
# ═══════════════════════════════════════════════════════════════════════════════

async def appliquer(g, membre, metiers: list, *, auteur=None, cause: str = "", creer: bool = True,
                    trace: bool = False, journaliser: bool = True) -> dict:
    """Les rôles des `metiers` (les N premiers, réglage) donnés à `membre`, ceux de ses autres métiers retirés —
    jamais un autre rôle. Un métier sans rôle : créé (`creer`). → `{"ajoutes", "retires", "ignores", "crees",
    "manquants"}` (+ `"erreur"` si Discord a refusé)."""
    voulus = list(dict.fromkeys(m for m in metiers if isinstance(m, str)))[:(await reglages(g))["max"]]
    crees, manquants = [], []
    for cle in voulus:
        role, etat = await role_du_metier(g, cle, creer=creer, auteur=auteur)
        if role is None:
            manquants.append(cle)
        elif etat == "cree":
            crees.append({"id": str(role.id), "nom": role.name})
    qui = auteur if auteur is not None else getattr(g, "me", None)
    clan = await role_du_clan(g)
    res = await affiches.appliquer_roles(g, qui, membre, {TYPE: voulus}, types=(TYPE,), trace=trace,
                                         raison=f"Rôles des métiers du clan GoRP — {cause}"[:400],
                                         sauf_roles={clan.id} if clan is not None else ())
    res = dict(res, crees=crees, manquants=manquants)
    if journaliser and (res.get("ajoutes") or res.get("retires")):
        await _noter(g, "clan.metiers_roles", f"{affiches._phrase_roles(membre.display_name, res)} ({cause})",
                     membre_id=membre.id, auteur_id=getattr(auteur, "id", 0) or 0)
    panne = (str(res.get("erreur") or ""), tuple(sorted(manquants)), tuple(sorted(x["id"] for x in res.get("ignores", []))))
    await _noter_panne(g, membre, "clan.metiers_erreur", panne, f"Rôles des métiers de {membre.display_name} : un rôle "
                                                                "n'a pas pu être posé (permission ou hiérarchie)")
    return res


async def retirer_roles_clan(g, membre, *, cause: str, journaliser: bool = True) -> dict:
    """Tous les « rôles du clan » de `membre` partent : ceux des métiers et les rôles rattachés — jamais un autre."""
    ids = await ids_roles_clan(g)
    partants = [r for r in getattr(membre, "roles", []) or [] if r.id in ids and _amovible(g, r)]
    if not partants:
        return {"retires": []}
    panne = tuple(sorted(r.id for r in partants))
    if not affiches._peut_gerer_roles(g):
        _signaler("E2", "rôles du clan non retirés : permission « Gérer les rôles » absente", f"serveur={g.id}")
        await _noter_panne(g, membre, "clan.roles_erreur", panne, f"Rôles du clan de {membre.display_name} non retirés :"
                                                                  " il me manque la permission « Gérer les rôles »")
        return {"retires": [], "erreur": "Il me manque la permission « Gérer les rôles »."}
    try:
        await membre.remove_roles(*partants, reason=f"Rôles du clan GoRP — {cause}"[:400])
    except discord.HTTPException as ex:
        _signaler("E2", "rôles du clan non retirés", f"serveur={g.id} membre={membre.id} {type(ex).__name__} {ex}")
        await _noter_panne(g, membre, "clan.roles_erreur", panne, f"Rôles du clan de {membre.display_name} non retirés :"
                                                                  " Discord a refusé (hiérarchie)")
        return {"retires": [], "erreur": "Discord a refusé (hiérarchie ou permission)."}
    await _noter_panne(g, membre, "clan.roles_erreur", (), "")
    noms = [r.name for r in partants]
    if journaliser:
        await _noter(g, "clan.roles_depart", f"{membre.display_name} n'est plus dans le clan : rôles du clan retirés "
                                             f"({', '.join(noms)})", membre_id=membre.id)
    return {"retires": [{"id": str(r.id), "nom": r.name} for r in partants]}


async def effectifs(g, membre, metiers: list) -> list | None:
    """Les métiers dont `membre` doit porter les rôles : les N premiers dans le clan, aucun hors du clan ; None pendant
    une sanction (ses rôles ne bougent pas)."""
    clan = await role_du_clan(g)
    if clan is None:
        return list(metiers)
    if await sous_sanction(g, membre):
        return None
    if not _du_clan(membre, clan):
        return None if await epargne(g, membre) else []
    return list(dict.fromkeys(metiers))[:(await reglages(g))["max"]]


async def apres_affiche(g, auteur, membre, affiche: dict) -> dict | None:
    """Une affiche enregistrée sur le site (`affiches._roles_automatiques`) : ses métiers suivent — dans le clan avec
    l'attribution automatique ; hors du clan, aucun rôle de métier. None : rien à faire ici."""
    c = await _cfg(g.id)
    clan = await role_du_clan(g, c)
    if clan is None:
        return None
    async with _verrou_membre(g.id, membre.id):
        if await sous_sanction(g, membre):
            return None
        if not _du_clan(membre, clan):
            if await epargne(g, membre):
                return None
            return await appliquer(g, membre, [], auteur=auteur, cause="hors du clan", creer=False, trace=True)
        if not reglages_de(c)["auto"]:
            return None
        return await appliquer(g, membre, list(affiche["attributs"].get(TYPE) or []), auteur=auteur,
                               cause="affiche modifiée sur le site", creer=True, trace=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rôle du clan perdu ou rendu (`on_member_update`) et la réconciliation
# ═══════════════════════════════════════════════════════════════════════════════

async def sur_maj_membre(before, after) -> None:
    """Le rôle du clan disparaît (un modérateur, le site, l'inactivité… peu importe) : tous les rôles du clan partent.
    Il revient : les métiers de son affiche sont rendus (attribution automatique). Une sanction en cours : rien."""
    g = getattr(after, "guild", None)
    if g is None or getattr(after, "bot", False) or not pret():
        return
    avant = {r.id for r in getattr(before, "roles", []) or []}
    apres = {r.id for r in getattr(after, "roles", []) or []}
    if avant == apres:
        return
    c = await _cfg(g.id)
    clan = await role_du_clan(g, c)
    if clan is None or (clan.id in avant) == (clan.id in apres):
        return
    async with _verrou_membre(g.id, after.id):
        m = g.get_member(after.id) or after
        if await sous_sanction(g, m):
            _log(f"[METIERS:DETAIL] sanction en cours : rôles du clan laissés tels quels serveur={g.id} membre={m.id}")
            return
        if clan.id in avant:
            if await epargne(g, m):
                _log(f"[METIERS:DETAIL] compte de tête : rôles du clan laissés serveur={g.id} membre={m.id}")
                return
            await retirer_roles_clan(g, m, cause="n'est plus dans le clan")
            return
        if not reglages_de(c)["auto"]:
            return
        a = await affiches._affiche_du_membre(g.id, m.id)
        metiers = list((a or {}).get("attributs", {}).get(TYPE) or [])
        await appliquer(g, m, metiers, cause="retour dans le clan", creer=True)


async def reconcilier(g, *, auteur=None) -> dict:
    """Les rôles du clan remis d'accord avec le clan : un non-membre ne garde aucun rôle du clan ; un membre du clan
    qui a son affiche porte les rôles de ses métiers (attribution automatique). Un membre sous sanction, ou sans
    affiche, n'est pas touché. Rattrape ce qu'un redémarrage a manqué. → le bilan."""
    bilan = {"actif": False, "verifies": 0, "retires": 0, "anciens": 0, "rendus": 0, "membres": 0, "crees": 0,
             "sanctions": 0, "epargnes": 0, "erreurs": 0, "details": []}
    if not pret():
        return dict(bilan, raison="Le module démarre.")
    c = await _cfg(g.id)
    clan = await role_du_clan(g, c)
    if clan is None:
        return dict(bilan, raison="Aucun rôle du clan réglé (/configure → Rell Seas) : rien n'est touché.")
    bilan["actif"] = True
    if not affiches._peut_gerer_roles(g):
        return dict(bilan, erreurs=1, raison="Il me manque la permission « Gérer les rôles » : rien n'est touché.")
    async with _verrou(("reconciliation", g.id)):
        reg = reglages_de(c)
        sanctionnes = await _sanctionnes_de(g)
        if sanctionnes is None:
            return dict(bilan, erreurs=1, raison="Sanctions illisibles : rien n'a été touché.")
        ids_clan = await ids_roles_clan(g, c)
        membres = [m for m in list(getattr(g, "members", []) or []) if not getattr(m, "bot", False)]
        bilan["verifies"] = len(membres)

        def detail(m, res):
            if len(bilan["details"]) < DETAILS_MAX:
                bilan["details"].append({"membre_id": str(m.id), "nom": m.display_name,
                                         "ajoutes": [x["nom"] for x in res.get("ajoutes", [])],
                                         "retires": [x["nom"] for x in res.get("retires", [])]})
        #  1. Les anciens membres : aucun rôle du clan.
        for m in membres:
            if _du_clan(m, clan) or not any(r.id in ids_clan for r in m.roles):
                continue
            if m.id in sanctionnes:
                bilan["sanctions"] += 1
                continue
            if await epargne(g, m):          # le fondateur, la direction : jamais retirés automatiquement
                bilan["epargnes"] += 1
                continue
            async with _verrou_membre(g.id, m.id):
                res = await retirer_roles_clan(g, m, cause="réconciliation : n'est plus dans le clan", journaliser=False)
            if res.get("erreur"):
                bilan["erreurs"] += 1
            elif res["retires"]:
                bilan["retires"] += len(res["retires"])
                bilan["anciens"] += 1
                detail(m, res)
                await asyncio.sleep(PAUSE_RECONCILIATION)
        #  2. Les membres du clan : les rôles de leurs métiers (leur affiche).
        if reg["auto"]:
            affiche_de = {int(a["membre_id"]): a for a in await affiches._affiches(g.id)
                          if not a["retire_le"] and a["membre_id"]}
            liens = await _liens_metiers(g.id)
            ids_metiers = set(liens.values())
            for m in membres:
                a = affiche_de.get(m.id)
                if a is None or not _du_clan(m, clan):
                    continue
                voulus = list(dict.fromkeys(a["attributs"].get(TYPE) or []))[:reg["max"]]
                attendus = {liens.get(k) for k in voulus}
                if None not in attendus and all(g.get_role(r) is not None for r in attendus) \
                        and {r.id for r in m.roles if r.id in ids_metiers} == attendus:
                    continue                          # déjà juste : aucun appel à Discord
                if m.id in sanctionnes:
                    bilan["sanctions"] += 1
                    continue
                async with _verrou_membre(g.id, m.id):
                    res = await appliquer(g, m, voulus, auteur=auteur, cause="réconciliation", creer=True,
                                          journaliser=False)
                bilan["crees"] += len(res.get("crees", []))
                if res.get("erreur") or res.get("manquants"):
                    bilan["erreurs"] += 1
                if res.get("ajoutes") or res.get("retires"):
                    bilan["rendus"] += len(res.get("ajoutes", []))
                    bilan["retires"] += len(res.get("retires", []))
                    bilan["membres"] += 1
                    detail(m, res)
                    await asyncio.sleep(PAUSE_RECONCILIATION)
    if bilan["retires"] or bilan["rendus"]:
        lignes = "; ".join(f"{d['nom']} " + " ".join([f"+{x}" for x in d["ajoutes"]] + [f"−{x}" for x in d["retires"]])
                           for d in bilan["details"])
        await _noter(g, "clan.roles_reconciliation", phrase_bilan(bilan), detail=lignes[:600],
                     auteur_id=getattr(auteur, "id", 0) or 0)
    if _db_set is not None:
        try:
            await _db_set(g.id, CLE_BILAN, {k: bilan[k] for k in ("verifies", "retires", "anciens", "rendus", "membres",
                                                                 "crees", "sanctions", "epargnes", "erreurs")}
                          | {"quand": int(time.time())})
        except Exception as ex:
            _signaler("E6", "bilan de la réconciliation non gardé", f"serveur={g.id} {type(ex).__name__} {ex}")
    return bilan


async def donner_aux_affiches(g, cles, *, cause: str = "installation", auteur=None) -> int:
    """Les rôles de ces métiers (déjà liés) donnés aux membres du clan dont l'affiche les porte (parmi ses N premiers
    métiers), avec l'attribution automatique — rien n'est retiré ni créé ; une sanction en cours : rien. → le nombre
    de rôles donnés. 26/10/2026 (sécurité) : `auteur`, la personne du site qui l'a déclenché — un autre compte de la tête
    n'est pas touché par elle (`affiches.protege_de`)."""
    c = await _cfg(g.id)
    reg, clan = reglages_de(c), await role_du_clan(g, c)
    cles = set(cles or ())
    if clan is None or not reg["auto"] or not cles or not affiches._peut_gerer_roles(g):
        return 0
    sanctionnes = await _sanctionnes_de(g)
    if sanctionnes is None:
        return 0
    liens = await _liens_metiers(g.id)
    donnes = 0
    for a in await affiches._affiches(g.id):
        m = g.get_member(int(a["membre_id"])) if a["membre_id"] and not a["retire_le"] else None
        if m is None or getattr(m, "bot", False) or not _du_clan(m, clan) or m.id in sanctionnes:
            continue
        if auteur is not None and affiches.protege_de(g, auteur, m):
            continue
        voulus = [k for k in list(dict.fromkeys(a["attributs"].get(TYPE) or []))[:reg["max"]] if k in cles and k in liens]
        roles = [r for r in (g.get_role(liens[k]) for k in voulus) if r is not None and r.id != clan.id
                 and r not in m.roles and affiches.refus_role(g, r) is None]
        if not roles:
            continue
        async with _verrou_membre(g.id, m.id):
            try:
                await m.add_roles(*roles, reason=f"Rôles des métiers du clan GoRP — {cause}"[:400])
            except discord.HTTPException as ex:
                _signaler("E3", "rôles des métiers non donnés", f"serveur={g.id} membre={m.id} {type(ex).__name__} {ex}")
                continue
        donnes += len(roles)
        await _noter(g, "clan.metiers_roles", f"Rôles des métiers de {m.display_name} : "
                     + ", ".join(f"+{r.name}" for r in roles) + f" ({cause})", membre_id=m.id)
        await asyncio.sleep(PAUSE_RECONCILIATION)
    return donnes


def planifier_attribution(g, cle: str, auteur=None) -> None:
    """Un métier vient d'avoir son rôle (créé ou lié sur le site) : donné tout de suite, en fond, à ceux qui l'ont."""
    if g is None or not pret():
        return

    async def _faire():
        try:
            await donner_aux_affiches(g, {cle}, cause="rôle lié sur le site", auteur=auteur)
        except Exception as ex:
            _signaler("E3", "rôles des métiers non donnés", f"serveur={g.id} {cle} {type(ex).__name__} {ex}")
    t = asyncio.create_task(_faire())
    _taches.add(t)
    t.add_done_callback(_taches.discard)


def phrase_bilan(b: dict) -> str:
    morceaux = []
    if b["retires"]:
        morceaux.append(f"{b['retires']} rôle(s) retiré(s)" + (f" à {b['anciens']} ancien(s) membre(s)" if b["anciens"] else ""))
    if b["rendus"]:
        morceaux.append(f"{b['rendus']} rôle(s) de métier donné(s)")
    if b["membres"]:
        morceaux.append(f"{b['membres']} membre(s) du clan remis à jour")
    if b["sanctions"]:
        morceaux.append(f"{b['sanctions']} membre(s) sous sanction laissé(s) tel(s) quel(s)")
    if b["erreurs"]:
        morceaux.append(f"{b['erreurs']} refus de Discord")
    return "Rôles du clan remis en ordre : " + (", ".join(morceaux) if morceaux else "rien à changer")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le choix du membre : la liste du guide du clan (persistante)
# ═══════════════════════════════════════════════════════════════════════════════

_EMOJI_APPLICATION = re.compile(r"<(a?):(\w{2,32}):(\d{13,20})>")


def _emoji_option(texte: str):
    """« <:nom:id> » → l'émoji d'application. ⚠️ `SelectOption(emoji="<:nom:id>")` ne le lit PAS : il en ferait le
    NOM d'un émoji Unicode, que Discord refuse (toute la carte du guide avec). Autre chose qu'un émoji d'application :
    rien — jamais un émoji Unicode."""
    m = _EMOJI_APPLICATION.fullmatch(texte) if isinstance(texte, str) else None
    return discord.PartialEmoji(name=m.group(2), id=int(m.group(3)), animated=bool(m.group(1))) if m else None


class ChoixMetier(discord.ui.DynamicItem[discord.ui.Select], template=r"mt:choix"):
    """« Choisis ton métier · Pick your job » dans le guide du clan : persistant, il répond après un redémarrage."""

    def __init__(self, options: list | None = None, maxi: int = MAX_DEFAUT, placeholder: str = "", aucun: str = ""):
        choix = [discord.SelectOption(label=o["label"][:100], value=o["cle"], description=(o["description"] or None),
                                      emoji=_emoji_option(o["emoji"])) for o in options or []][:OPTIONS_MAX]
        n = len(choix)
        if choix:
            choix.append(discord.SelectOption(label=(aucun or "Aucun métier · No job")[:100], value=AUCUN))
        super().__init__(discord.ui.Select(custom_id="mt:choix",
                                           placeholder=(placeholder or "Choisis ton métier · Pick your job")[:150],
                                           min_values=1, max_values=max(1, min(int(maxi), n)) if n else 1,
                                           options=choix or [discord.SelectOption(label="—", value=AUCUN)]))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        valeurs = [v for v in ((getattr(i, "data", None) or {}).get("values") or []) if isinstance(v, str)]
        await _sans_echec(i, choisir(i, valeurs))


def _vue_avis(texte: str, couleur=Palette.NEUTRAL) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=couleur))
    return v


def _effacer_plus_tard(i, delai: float | None = None) -> None:
    """« Un avis est pour la personne seule » : il s'efface tout seul."""
    supprimer = getattr(i, "delete_original_response", None)
    if supprimer is None:
        return

    async def _plus_tard():
        await asyncio.sleep(AVIS_S if delai is None else delai)
        try:
            await supprimer()
        except discord.HTTPException:
            pass  # déjà fermé par le membre, ou le jeton de l'interaction a expiré : rien à faire
    t = asyncio.create_task(_plus_tard())
    _taches.add(t)
    t.add_done_callback(_taches.discard)


async def _avis(i, texte: str, couleur=Palette.NEUTRAL, delai: float | None = None) -> None:
    vue = _vue_avis(texte, couleur)
    if i.response.is_done():
        await i.followup.send(view=vue, ephemeral=True)
    else:
        await i.response.send_message(view=vue, ephemeral=True)
    _effacer_plus_tard(i, delai)


async def _sans_echec(i, travail) -> None:
    """Le filet d'un composant persistant : une erreur répond quand même, pour soi, puis remonte (discord.py la
    journalise, /stats la compte)."""
    try:
        await travail
    except Exception as ex:
        _signaler("E9", "choix du métier en échec", f"{type(ex).__name__} {ex}")
        try:
            await _avis(i, _reponse(i, "souci"), Palette.WARNING)
        except discord.HTTPException as ex2:
            _signaler("E9", "réponse impossible", f"{type(ex2).__name__} {ex2}")
        raise


def _texte_choix(choisis: list, auto: bool, res: dict | None, deja: bool, choisis_noms: dict | None = None,
                 guild_id: int = 0) -> str:
    """La réponse au choix (Textes & noms : `metiers.choix.…`), le rôle refusé par Discord dit en dessous."""
    mode = "auto" if auto else "manuel"
    if not choisis:
        texte = _t(guild_id, f"metiers.choix.aucun_{mode}")
    else:
        noms = ", ".join(f"**{nom_du_role(e, choisis_noms)}**" for e in choisis)
        noms_en = ", ".join(str(e.get("nom_en") or nom_du_role(e, choisis_noms)) for e in choisis)
        texte = _t(guild_id, f"metiers.choix.{'deja' if deja else 'note'}_{mode}", metiers=noms, metiers_en=noms_en)
    if auto and res and (res.get("erreur") or res.get("manquants") or res.get("ignores")):
        texte += "\n" + _t(guild_id, "metiers.choix.role_manquant")
    return texte


async def choisir(i, valeurs: list) -> None:
    """Le membre choisit ses métiers dans le guide du clan : son affiche les reçoit (créée au besoin), puis ses rôles
    suivent (attribution automatique). Réservé au clan ; chaque réponse est pour lui seul et s'efface."""
    if not pret():
        return await _avis(i, _reponse(i, "demarre"), Palette.WARNING, DEMARRE_S)
    await i.response.defer(ephemeral=True, thinking=True)   # répondre d'abord : la base peut faire attendre
    g, m = getattr(i, "guild", None), getattr(i, "user", None)
    if g is None or not hasattr(m, "roles"):
        return await _avis(i, _reponse(i, "indisponible"))
    c = await _cfg(g.id)
    clan = await role_du_clan(g, c)
    if clan is None:
        return await _avis(i, _reponse(i, "ferme"), Palette.WARNING)
    if not _du_clan(m, clan):
        return await _avis(i, _reponse(i, "reserve"), Palette.WARNING)
    if await sous_sanction(g, m):
        return await _avis(i, _reponse(i, "indisponible"), Palette.WARNING)
    reg = reglages_de(c)
    if reg["ticket"]:   # une ancienne liste du guide : le métier se choisit au ticket, la direction l'attribue
        return await _avis(i, _reponse(i, "au_ticket"), Palette.WARNING)
    actifs = {e["cle"]: e for e in await metiers_du_catalogue()}
    choix = list(dict.fromkeys(valeurs))
    aucun = AUCUN in choix
    choix = [v for v in choix if v != AUCUN]
    if any(v not in actifs for v in choix):
        return await _avis(i, _reponse(i, "retire"), Palette.WARNING)
    if not choix and not aucun:
        return await _avis(i, _reponse(i, "rien"))
    if len(choix) > reg["max"]:
        return await _avis(i, _reponse(i, "trop", n=reg["max"]), Palette.WARNING)
    async with _verrou_membre(g.id, m.id):
        cle = (g.id, m.id)
        if time.monotonic() - _derniers_choix.get(cle, -1e9) < PAUSE_CHOIX_S:
            return await _avis(i, _reponse(i, "doucement"), Palette.WARNING, DEMARRE_S)
        _derniers_choix[cle] = time.monotonic()
        try:
            affiche, change = await affiches.definir_metiers(g, m, choix, m.id)
        except affiches.Invalide as ex:
            return await _avis(i, f"{ex.message}\n-# This choice can't be saved.", Palette.WARNING)
        res = await appliquer(g, m, choix, auteur=m, cause="son choix", creer=True) if reg["auto"] else None
    choisis = [actifs[k] for k in choix]
    choisis_noms = noms_choisis(c)
    if change:
        noms = ", ".join(nom_du_role(e, choisis_noms) for e in choisis)
        await _noter(g, "clan.metier_choisi", f"{m.display_name} a choisi son métier : {noms}" if choisis
                     else f"{m.display_name} n'a plus de métier", membre_id=m.id, auteur_id=m.id,
                     detail=f"affiche {affiche['id']}")
    erreur = bool(res and (res.get("erreur") or res.get("manquants") or res.get("ignores")))
    await _avis(i, _texte_choix(choisis, reg["auto"], res, not change, choisis_noms, g.id),
                Palette.WARNING if erreur else (Palette.SUCCESS if change else Palette.NEUTRAL))


async def section_guide(g, c: dict) -> tuple | None:
    """Pour le guide du clan (`zones.vue_guide_clan`) : (les composants « Choisis ton métier », leur signature) — None
    quand le choix n'est pas possible (aucun rôle du clan réglé, aucun métier actif) : aucune liste qui ment."""
    if not pret() or await role_du_clan(g, c) is None or reglages_de(c)["ticket"]:
        return None   # 28/10/2026 : le métier se choisit au ticket — aucune liste sur le serveur
    options = await options_selecteur(g)
    if not options:
        return None
    reg = reglages_de(c)
    maxi = max(1, min(reg["max"], len(options)))
    icone = _icone_maison("navire")
    combien_fr = "ton métier" if maxi == 1 else f"jusqu'à **{maxi}** métiers"
    combien_en = "your job" if maxi == 1 else f"up to {maxi} jobs"
    #  Les textes de Textes & noms (sinon ceux d'origine) ; leur changement réécrit le guide (`quand_change`).
    await textes_du_site.texte(g.id, "metiers.guide.titre")
    titre = _t(g.id, "metiers.guide.titre")
    corps = _t(g.id, "metiers.guide.texte_auto" if reg["auto"] else "metiers.guide.texte_manuel",
               combien=combien_fr, combien_en=combien_en)
    liste, aucun = _t(g.id, "metiers.guide.liste"), _t(g.id, "metiers.guide.aucun")
    texte = f"### {icone + ' ' if icone else ''}{titre}\n{corps}"
    composants = [discord.ui.TextDisplay(texte), discord.ui.ActionRow(ChoixMetier(options, maxi, liste, aucun))]
    empreinte = json.dumps([reg["auto"], maxi, icone, options, texte, liste, aucun], sort_keys=True, ensure_ascii=False)
    return composants, hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:12]


def _texte_change(g, cle: str) -> None:
    """Un texte du guide (Textes & noms) vient de changer : le guide du clan se réécrit."""
    planifier_guide(g)


textes_du_site.quand_change("metiers.guide.", _texte_change)


def planifier_guide(g) -> None:
    """Le guide du clan se réécrit (le catalogue ou les réglages ont changé) — une fois pour toute une rafale."""
    if _guide is None or g is None:
        return
    t = _guides_prevus.get(g.id)
    if t is not None and not t.done():
        return

    async def _plus_tard():
        await asyncio.sleep(GUIDE_APRES_S)
        try:
            await _guide(g)
        except Exception as ex:
            _signaler("E10", "guide du clan non réécrit", f"serveur={g.id} {type(ex).__name__} {ex}")
    t = asyncio.create_task(_plus_tard())
    _guides_prevus[g.id] = t
    _taches.add(t)
    t.add_done_callback(_taches.discard)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'acceptation au clan : la carte du ticket
# ═══════════════════════════════════════════════════════════════════════════════

def lien_guide(g, c: dict) -> str | None:
    pid = int(((c.get("clan_posts") or {}).get("guide") or {}).get("id", 0) or 0)
    return f"https://discord.com/channels/{g.id}/{pid}" if pid else None


async def invitation(g, membre, reponses: dict | None = None) -> tuple | None:
    """(le texte, le lien du guide, le libellé du bouton) de l'invitation à choisir son métier — None s'il n'y a ni guide, ni métier à choisir,
    ni rôle du clan réglé. 26/10/2026 : le recrutement la met dans SON message de décision (un message de moins dans
    le ticket) ; `inviter_au_choix` la pose en carte."""
    if not pret() or g is None or membre is None:
        return None
    c = await _cfg(g.id)
    lien = lien_guide(g, c)
    if reglages_de(c)["ticket"]:
        return await _attribuer_au_recrutement(g, c, membre, reponses or {}, lien)
    if lien is None or await role_du_clan(g, c) is None or not await options_selecteur(g):
        return None
    auto = reglages_de(c)["auto"]
    await textes_du_site.texte(g.id, "metiers.carte.bouton")   # le cache des textes (Textes & noms) est chargé
    return (_t(g.id, "metiers.carte.auto" if auto else "metiers.carte.manuel", membre=membre.mention), lien,
            _t(g.id, "metiers.carte.bouton"))


async def _attribuer_au_recrutement(g, c: dict, membre, reponses: dict, lien) -> tuple | None:
    """28/10/2026 : à l'acceptation, le métier choisi dans la fiche est donné s'il reste une place (son affiche, puis son
    rôle). → (le texte de la carte, le lien du guide ou None, le libellé du bouton)."""
    if await role_du_clan(g, c) is None:
        return None
    reg, noms = reglages_de(c), noms_choisis(c)
    await textes_du_site.texte(g.id, "metiers.carte.attribue")   # le cache des textes est chargé
    bouton = _t(g.id, "metiers.carte.bouton")
    e = metier_des_reponses(await metiers_du_catalogue(), reponses, noms)
    if e is None:
        return _t(g.id, "metiers.carte.sans", membre=membre.mention), lien, bouton
    nom = nom_du_role(e, noms)
    async with _verrou(("places", g.id)):
        limite = reg["places"].get(e["cle"])
        pris = (await occupes(g, c)).get(e["cle"], 0)
        if limite is not None and pris >= limite:
            await _noter(g, "clan.metier_complet", f"{membre.display_name} : plus de place en {nom}, à attribuer",
                         membre_id=membre.id)
            return _t(g.id, "metiers.carte.complet", membre=membre.mention, metier=nom), lien, bouton
        affiche, _change = await affiches.definir_metiers(g, membre, [e["cle"]], membre.id)
    if reg["auto"]:
        await appliquer(g, membre, [e["cle"]], auteur=None, cause="choisi au recrutement", creer=True)
    await _noter(g, "clan.metier_choisi", f"{membre.display_name} : métier {nom} (choisi au recrutement)",
                 membre_id=membre.id, detail=f"affiche {affiche['id']}")
    return _t(g.id, "metiers.carte.attribue", membre=membre.mention, metier=nom), lien, bouton


async def metiers_du_membre(g, membre) -> list:
    """Les clés des métiers dont ce membre porte le rôle (les chefs d'équipe : le métier proposé d'office)."""
    if not pret() or g is None or membre is None:
        return []
    siens = {getattr(r, "id", None) for r in getattr(membre, "roles", []) or []}
    return [cle for cle, rid in (await _liens_metiers(g.id)).items() if rid in siens]


async def inviter_au_choix(g, ch, membre) -> str | None:
    """À l'acceptation au clan, AVANT la fermeture du ticket : une carte dit au nouveau membre de choisir son métier dans
    le guide du clan (un bouton vers le post), sans mention de masse. Rend le lien du guide — None (rien posté) s'il n'y
    a ni guide, ni métier à choisir, ni rôle du clan réglé."""
    if ch is None:
        return None
    inv = await invitation(g, membre)
    if inv is None:
        return None
    texte, lien, libelle = inv
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay(texte),
        discord.ui.ActionRow(discord.ui.Button(label=libelle[:80], url=lien)),
        accent_color=discord.Color(COULEUR_CARTE)))
    try:
        await ch.send(view=v, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as ex:
        _signaler("E8", "carte du métier non posée dans le ticket", f"serveur={g.id} {type(ex).__name__} {ex}")
    return lien


# ═══════════════════════════════════════════════════════════════════════════════
#  Le site (Capitainerie → Rôles & métiers) — branché par `affiches.ROUTES_SITE`
# ═══════════════════════════════════════════════════════════════════════════════

def _role_sortie(r) -> dict | None:
    if r is None:
        return None
    return {"id": str(r.id), "nom": r.name, "couleur": affiches._couleur_role(r), "position": int(getattr(r, "position", 0))}


async def etat(g) -> dict:
    """`GET rell/metiers/reglages` : les réglages, les rôles qu'on peut rattacher, chaque métier et son rôle."""
    c = await _cfg(g.id)
    reg = reglages_de(c)
    clan = await role_du_clan(g, c)
    liens = await _liens_metiers(g.id)
    #  Tous les rôles attribuables, sauf le rôle du clan : la page s'en sert pour les rôles rattachés ET pour le rôle de
    #  chaque métier (le rôle déjà lié doit y figurer).
    disponibles = [_role_sortie(r) for r in sorted(getattr(g, "roles", []) or [], key=lambda r: -int(r.position))
                   if (clan is None or r.id != clan.id) and affiches.refus_role(g, r) is None]
    par_metier: dict = {}
    for a in await affiches._affiches(g.id):
        if not a["retire_le"]:
            for cle in a["attributs"].get(TYPE) or []:
                par_metier[cle] = par_metier.get(cle, 0) + 1
    metiers = []
    for e in await metiers_du_catalogue(actifs=False):
        role = g.get_role(liens[e["cle"]]) if e["cle"] in liens else None
        metiers.append({"cle": e["cle"], "nom": e["nom"], "nom_en": e["nom_en"], "actif": bool(e["actif"]),
                        "categorie": e["categorie"], "icone": affiches._icone_servie(e["icone"]),
                        "role_nom": nom_du_role(e, noms_choisis(c)),
                        "couleur": f"#{couleur_du_role(e):06x}", "role": _role_sortie(role),
                        "lie": e["cle"] in liens, "attribuable": role is not None and affiches.refus_role(g, role) is None,
                        "affiches": par_metier.get(e["cle"], 0)})
    hors_clan = [m for m in getattr(g, "members", []) or [] if not getattr(m, "bot", False) and not _du_clan(m, clan)]
    rattaches = []
    for rid in reg["rattaches"]:
        r = g.get_role(rid)
        refus = affiches.refus_role(g, r) if r is not None else "Ce rôle n'existe plus."
        rattaches.append({"id": str(rid), "nom": getattr(r, "name", ""), "existe": r is not None,
                          "attribuable": refus is None, "raison": refus or "",
                          "non_membres": sum(1 for m in hors_clan if any(x.id == rid for x in m.roles)) if clan else 0})
    pris = await occupes(g, c)
    for x in metiers:
        x["places"] = reg["places"].get(x["cle"])
        x["occupes"] = pris.get(x["cle"], 0)
    return {"auto": reg["auto"], "max_metiers": reg["max"], "max_bornes": [MAX_MIN, MAX_MAX],
            "au_ticket": reg["ticket"], "places_max": PLACES_MAX,
            "rattaches": [str(x) for x in reg["rattaches"]], "rattaches_details": rattaches,
            "roles_disponibles": disponibles, "icones_roles": "ROLE_ICONS" in (getattr(g, "features", None) or []),
            "gestion": affiches._peut_gerer_roles(g), "actif": clan is not None, "role_clan": _role_sortie(clan),
            "metiers": metiers, "derniere_reconciliation": c.get(CLE_BILAN) or None}


async def _valider_rattaches(g, c: dict, v) -> list:
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > RATTACHES_MAX:
        raise affiches.Invalide("rattaches", f"Une liste de {RATTACHES_MAX} rôles au plus.")
    clan = await role_du_clan(g, c)
    out = []
    for x in v:
        rid = affiches._identifiant(x, "rattaches")
        r = g.get_role(rid)
        if r is None:
            raise affiches.Invalide("rattaches", "Un de ces rôles n'existe plus.")
        if clan is not None and r.id == clan.id:
            raise affiches.Invalide("rattaches", "Le rôle du clan lui-même ne se rattache pas.")
        refus = affiches.refus_role(g, r)   # le rôle d'un métier coché aussi : accepté (il part déjà avec le clan)
        if refus is not None:
            raise affiches.Invalide("rattaches", f"« {r.name} » : {refus}")
        if r.id not in out:
            out.append(r.id)
    return out


async def _valider_places(v) -> dict:
    """`{clé: places | null}` : null (ou absent) = sans limite ; un entier de 0 à PLACES_MAX."""
    if not isinstance(v, dict) or len(v) > 200:
        raise affiches.Invalide("places", "Un objet {métier : nombre de places}.")
    connus = {e["cle"] for e in await metiers_du_catalogue(actifs=False)}
    out = {}
    for k, n in v.items():
        if k not in connus:
            raise affiches.Invalide("places", "Un de ces métiers n'existe pas.")
        if n is None:
            continue
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= PLACES_MAX:
            raise affiches.Invalide("places", f"Des places : un nombre de 0 à {PLACES_MAX}, ou vide pour sans limite.")
        out[k] = n
    return out


async def route_reglages(g, auteur, requete, corps):
    return 200, await etat(g)


async def route_regler(g, auteur, requete, corps):
    """`POST rell/metiers/reglages` `{"auto"?, "max_metiers"?, "rattaches"?: [role_id]}` : seuls les champs donnés
    changent. → l'état (comme la lecture)."""
    c = await _cfg(g.id)
    reg = reglages_de(c)
    voulu = {}
    try:
        if "auto" in corps:
            voulu[CLE_AUTO] = affiches._booleen(corps.get("auto"), "auto", reg["auto"])
        if "max_metiers" in corps:
            voulu[CLE_MAX] = affiches._entier(corps.get("max_metiers"), "max_metiers", MAX_MIN, MAX_MAX)
        if "rattaches" in corps:
            voulu[CLE_RATTACHES] = await _valider_rattaches(g, c, corps.get("rattaches"))
        if "au_ticket" in corps:
            voulu[CLE_TICKET] = affiches._booleen(corps.get("au_ticket"), "au_ticket", reg["ticket"])
        if "places" in corps:
            voulu[CLE_PLACES] = await _valider_places(corps.get("places"))
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if not voulu:
        return 400, {"erreur": "Rien à régler : « auto », « max_metiers », « rattaches », « au_ticket » ou « places »."}
    avant = {CLE_AUTO: reg["auto"], CLE_MAX: reg["max"], CLE_RATTACHES: reg["rattaches"], CLE_TICKET: reg["ticket"],
             CLE_PLACES: reg["places"]}
    changes = {k: v for k, v in voulu.items() if avant[k] != v}
    for k, v in changes.items():
        await _db_set(g.id, k, v)
    nouveau = await etat(g)
    if CLE_AUTO in changes or CLE_MAX in changes or CLE_TICKET in changes:
        planifier_guide(g)
    phrase = (f"Rôles & métiers : attribution automatique {'OUI' if nouveau['auto'] else 'NON'}, "
              f"{nouveau['max_metiers']} métier(s) au plus par membre, {len(nouveau['rattaches'])} rôle(s) rattaché(s) "
              f"au clan, métier choisi {'au ticket' if nouveau['au_ticket'] else 'dans le guide'}"
              + (", places des métiers changées" if CLE_PLACES in changes else ""))
    return 200, dict(nouveau, ok=True, _journal=phrase if changes else None)


def _sans_zeros(d: dict, toujours=()) -> dict:
    """La page (`bilanLisible`) compte chaque nombre et chaque liste d'un bilan : les zéros et les listes vides n'y vont
    pas (« Rien à changer » plutôt que « 0 rôle retiré · 0 rôle rendu »)."""
    return {k: v for k, v in d.items() if k in toujours or (v if isinstance(v, (int, list)) else True)}


async def route_installer(g, auteur, requete, corps):
    """`POST rell/metiers/installer` : d'un coup, un rôle pour chaque métier actif qui n'en a pas (créé, ou relié à un
    rôle du même nom), rangés dans l'ordre du catalogue sous le rôle du clan ; puis, avec l'attribution automatique,
    donnés aux membres du clan dont l'affiche porte ces métiers (rien n'est retiré). → `{"crees", "lies", "deja",
    "donnes", "erreurs"}` (les comptes que lit la page, sans zéro) et `message`."""
    if await role_du_clan(g) is None:
        return 409, {"erreur": "Règle d'abord le rôle du clan (/configure → Rell Seas)."}
    if not affiches._peut_gerer_roles(g):
        return 403, {"erreur": "Il me manque la permission « Gérer les rôles »."}
    sortie = {"crees": [], "lies": [], "deja": [], "erreurs": []}
    raisons = {"refuse": "Le rôle lié ne peut pas être donné (hiérarchie ou droits).", "droits": "Permission manquante.",
               "echec": "Discord a refusé de créer le rôle.", "inconnu": "Métier inconnu ou retiré."}
    #  Du dernier au premier : chacun se pose juste sous le rôle du clan, le premier métier finit le plus haut.
    for e in reversed(await metiers_du_catalogue()):
        role, quoi = await role_du_metier(g, e["cle"], creer=True, auteur=auteur)
        if role is None:
            sortie["erreurs"].append({"cle": e["cle"], "nom": e["nom"], "raison": raisons.get(quoi, quoi)})
        else:
            sortie[{"cree": "crees", "relie": "lies"}.get(quoi, "deja")].append(
                {"cle": e["cle"], "role_id": str(role.id), "nom": role.name})
    for k in sortie:
        sortie[k].reverse()
    if sortie["crees"] or sortie["lies"]:
        planifier_guide(g)
    auto = (await reglages(g))["auto"]
    donnes = await donner_aux_affiches(g, {x["cle"] for x in sortie["crees"] + sortie["lies"] + sortie["deja"]},
                                       auteur=auteur) if auto else 0
    message = "" if auto else ("Attribution automatique sur NON : les rôles sont prêts, donnés à personne (« Appliquer »"
                               " sur chaque affiche).")
    phrase = (f"Rôles des métiers installés : {len(sortie['crees'])} créé(s), {len(sortie['lies'])} relié(s), "
              f"{len(sortie['deja'])} déjà là, {donnes} donné(s)"
              + (f", {len(sortie['erreurs'])} en échec" if sortie["erreurs"] else ""))
    journal = phrase if (sortie["crees"] or sortie["lies"] or sortie["erreurs"] or donnes) else None
    return 200, dict(_sans_zeros(dict(sortie, donnes=donnes)), ok=True, message=message, _journal=journal)


async def route_reconcilier(g, auteur, requete, corps):
    """`POST rell/metiers/reconcilier` : la réconciliation tout de suite → `{"bilan": {"verifies", "retires", "rendus",
    "crees", "ignores", "erreurs"}, "detail", "message"}` (le bilan dans les mots de la page, sans zéro)."""
    if await role_du_clan(g) is not None and not affiches._peut_gerer_roles(g):
        return 403, {"erreur": "Il me manque la permission « Gérer les rôles »."}
    b = await reconcilier(g, auteur=auteur)
    if not b["actif"]:
        return 409, {"erreur": b.get("raison") or "Indisponible."}
    bilan = _sans_zeros({"verifies": b["verifies"], "retires": b["retires"], "rendus": b["rendus"], "crees": b["crees"],
                         "ignores": b["sanctions"] + b["epargnes"], "erreurs": b["erreurs"]}, toujours=("verifies",))
    detail = {k: b[k] for k in ("anciens", "membres", "sanctions", "epargnes", "details")}
    return 200, {"ok": True, "bilan": bilan, "detail": detail, "message": b.get("raison") or "",
                 "_journal": f"{phrase_bilan(b)} (lancé depuis le site)"}
