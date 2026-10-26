"""candidature_site.py — le questionnaire en ligne du candidat, et son direct pour la direction (26/10/2026).

Le fondateur : « Ça lui dit de répondre au ticket, ça lui dit de répondre au questionnaire en cliquant sur le lien que
nous, on peut voir en direct quand il répond et tout. On peut voir même en direct quand il écrit et tout sur le site.
Avec un site ultra personnel et ultra bien fait. Il n'y a que le fondateur et la direction qui a accès à ça. » Puis :
« ça va commencer avec les premières étapes. Étape numéro 1. Et on peut mettre le nombre d'étapes que l'on souhaite.
[…] Avec un vrai questionnaire sur le site, super bien fait. Fonctionnel sur téléphone et sur PC. » — « Il faut que ce
soit simple, efficace, pas des trucs loin à comprendre. » — « C'est nous qui décidons s'il passe à l'étape suivante. »
— et, pour les chefs d'équipe : « il recevra un message en MP lui incitant à répondre à un questionnaire s'il veut être
chef. […] Mais il n'a pas le droit à l'erreur. »

LE LIEN (la sécurité d'abord)
  · `lien_envoi(i, envoi)` : un lien PERSONNEL, signé, à usage unique, valable 24 h — au candidat de CET envoi seulement,
    et seulement si le questionnaire l'attend. Deux portes y mènent : le bouton « Répondre au questionnaire » du ticket
    (`questionnaire.ouvrir_formulaire` appelle `lien_candidat(i, ticket)`, qui RÉPOND lui-même — le lien ou le refus,
    pour la personne seule — et rend None ; la page injoignable : rien, les formulaires de Discord prennent le relais ;
    `lien_ticket` rend (lien, refus)) et le bouton PERSISTANT du message privé d'un chef d'équipe (`inviter`, appelé à la
    proposition et à chaque étape ouverte ; `BoutonQuestionnaire`). Le lien porte l'envoi dans sa partie signée ; ouvert, il
    devient une session de portée « candidat » liée à CET envoi, dans un cookie à part limité à `/tableau/candidature/`.
  · La portée « candidat » est refusée partout ailleurs (`tableau._verifier`, par défaut) ; elle n'atteint que la page,
    `LECTURES` et `ECRITURES` d'ici, et seulement pour son envoi. Ticket fermé, envoi remplacé ou clos — et, pour un chef
    d'équipe (aucun ticket), le rôle du clan perdu, revérifié à chaque requête — : l'accès se ferme.
  · Ce que le candidat reçoit : les questions des étapes OUVERTES (texte, rang, étape), leurs titres et consignes, les
    liens du questionnaire, ses propres réponses, les textes de la page. JAMAIS une réponse attendue, une variante, une
    source, une correction, une indication, le nom de quelqu'un de l'équipe, ni une étape pas encore ouverte.

LA PAGE (`site/candidature.html`, `candidature.js`, `candidature.css`)
  · Étape par étape (« Étape 2 sur 4 — titre », la consigne, ses questions), la progression, l'enregistrement
    automatique, un brouillon gardé sur l'appareil si la connexion saute. Le format des étapes (fixé avec l'équipe du
    recrutement) : chaque question de l'instantané porte `etape` (1..N) en plus de `rang` ; l'envoi porte `etapes` =
    [{numero, titre, consigne}] (colonne JSON). Un envoi SANS étapes : une seule, avec toutes ses questions.
  · Le PASSAGE D'ÉTAPE (contrat commun) : chaque étape est une porte que la direction ouvre (`etape_ouverte`). Le candidat
    ne voit et ne remplit que les étapes ouvertes, envoie CETTE étape (`questionnaire.envoyer_etape`, une fois), puis
    attend (« Réponses envoyées. La direction les regarde… ») ; les suivantes sont cachées mais comptées ; la fiche du
    panneau (`etape_fiche`) est son « Étape 1 ». Un envoi d'avant (`etape_ouverte` = 0) : tout est ouvert, « Relire et
    envoyer », un seul envoi. Éliminé, refusé, ticket fermé : « Ta candidature est terminée », plus aucune écriture.
  · CHEF D'ÉQUIPE (contrat commun) : un envoi `nature` = « chef », `metier`, `ticket_id` = 0 — invité par message privé
    (`inviter`), « Questionnaire de chef d'équipe · <métier> », « chaque réponse doit être juste », les mêmes portes.
  · Les BROUILLONS (`candidature_brouillons`) ne sont jamais des réponses : l'envoi écrit les réponses dans les mêmes
    tables et états que le formulaire Discord (`questionnaire.envoyer_etape`, `clore_envoi`, `annoncer_reponses`) — la
    correction et les décisions du site ne voient aucune différence. La page ne poste RIEN dans le ticket : seules les
    fonctions de `questionnaire` y touchent.

LE DIRECT (le fondateur et la direction seulement)
  · Pendant que le candidat écrit (la page envoie au plus une frappe toutes les 0,4 s), le serveur diffuse aux sessions
    « tout » branchées sur la présence (`tableau.diffuser_candidat`, message « candidat », par ENVOI ; le ticket n'en est
    qu'un alias) : la question, le texte en cours, l'étape ouverte et les étapes envoyées, la page ouverte, cachée ou
    fermée, l'envoi. Au plus un message toutes les 0,25 s par candidat : regroupés, le dernier texte part toujours.
  · Sans WebSocket : `GET api/direct/candidat?envoi=` (ou `?ticket=`), portée « tout », jamais gardé par le service worker.
  · La vue : `site/candidature_direct.js` (`vueEnDirect`), dans le dossier d'une candidature.

LE JOURNAL : « questionnaire ouvert » (une ligne par questionnaire, à sa première ouverture), « étape reçue » et
« réponses reçues » (celles de `questionnaire`, avec « (questionnaire en ligne) ») — jamais une ligne par frappe.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import secrets
import sqlite3
import sys
import time

import discord
from discord.ui import Button

import diag
import questionnaire
import tableau
import textes
from ui_v2 import LayoutView, Palette

# ═══════════════════════════════════════════════════════════════════════════════
#  Réglages
# ═══════════════════════════════════════════════════════════════════════════════

PAS_DIRECT = 0.25               # s : au plus un message « candidat » toutes les 0,25 s par candidat
SAISIES_PAR_S = 6               # frappes reçues par seconde et par session (au-delà : laissées de côté)
BROUILLONS_PAR_S = 3            # enregistrements par seconde et par session (au-delà : 429, la page réessaie)
VU_EN_BASE_S = 60               # la dernière visite est gardée en base au plus une fois par minute
CONTEXTE_FRAIS = 4.0            # s : l'état d'un envoi relu pour une frappe (le rôle du clan, lui, l'est toujours)
LIAISON_FRAICHE = 60.0          # s : une liaison session → envoi gardée en mémoire (comme `tableau.RELIRE`)
COLONNES_FRAICHES = 60.0        # s : les colonnes de `recrutement_envois` (le parcours réglable en ajoute)
CORPS_SAISIE = 4 * 1024
CORPS_PRESENCE = 1024
CORPS_REPONSES = 64 * 1024
DIRECT_MAX = 300                # candidats suivis en mémoire (les plus anciens partent d'abord)
LIAISONS_MAX = 2000
ETAPES_MAX = 50
TITRE_ETAPE_MAX, CONSIGNE_MAX = 120, 600
AVIS_S = 180.0                  # le mot pour soi (le lien) s'efface au bout de 3 minutes
FORMAT_NONCE = re.compile(r"e(\d{1,12})x[A-Za-z0-9_-]{12}")
_CONTROLE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
VUES = ("ouverte", "cachee", "fermee")
#  Ce que l'instantané d'un envoi gagne avec le passage d'étape et les chefs d'équipe (`questionnaire.COLONNES_ENVOIS`,
#  et `etapes`, posée par le parcours réglable) : lu s'il existe, sinon la valeur d'un envoi d'avant.
EXTRAS = (("etapes", "[]"), ("etape_ouverte", 0), ("etape_envoyee", 0), ("etape_fiche", 0), ("nature", "recrutement"),
          ("metier", ""))

_get_db = None
_cfg = None
_log = print
_liaisons: dict = {}            # empreinte de session → (heure, liaison)
_direct: dict = {}              # (serveur, envoi) → l'état vivant du candidat (ce qu'il écrit, sa page)
_contextes: dict = {}           # envoi → (heure, contexte) — pour les frappes seulement
_seaux: dict = {}               # (empreinte, genre) → heures des dernières requêtes
_taches: set = set()            # les tâches de fond (un mot pour soi qui s'efface), gardées jusqu'au bout
_colonnes: dict = {}            # {"vu": heure, "noms": colonnes de `recrutement_envois`}

# ═══════════════════════════════════════════════════════════════════════════════
#  Les textes (registre `textes.py`, famille « Le questionnaire en ligne »)
# ═══════════════════════════════════════════════════════════════════════════════

GROUPE = "candidature_site"
textes.nommer_groupe(GROUPE, "Le questionnaire en ligne", 15)
_PAGE, _ETAPES, _FIN, _CHEF, _DISCORD = ("La page du candidat", "Les étapes et les boutons", "Après l'envoi, et les refus",
                                         "Le questionnaire de chef d'équipe", "Le lien sur Discord")
_NUMERO, _TOTAL, _METIER = ("numero", "le numéro de l'étape"), ("total", "le nombre d'étapes"), ("metier", "le métier")
#  (clé, texte d'origine, titre dans l'onglet, aide, longueur, sur une ligne, partie, variables, requis)
TEXTES = (
    ("entete", "Questionnaire de candidature", "La barre du haut", "Le nom de la page, à côté du médaillon du serveur.",
     60, True, _PAGE, (), True),
    ("titre", "Ta candidature", "Le titre", "En haut de la page, au-dessus de la phrase d'accueil.", 40, True, _PAGE, (),
     True),
    ("phrase", "Le questionnaire du clan, étape par étape.", "La phrase sous le titre", "Une phrase, sous le titre.", 160,
     True, _PAGE, (), True),
    ("intro", "Réponds à chaque question avec tes propres mots. Tes réponses s'enregistrent toutes seules : tu peux "
              "faire une pause et revenir avec ton lien.\n-# Answer each question in your own words. Your answers save "
              "automatically: you can take a break and come back.", "L'accueil",
     "Au début du questionnaire. Une ligne qui commence par « -# » s'écrit en petit.", 800, False, _PAGE, (), True),
    ("liens", "Où trouver les réponses", "Les liens · le titre", "Au-dessus des liens donnés au candidat.", 80, True,
     _PAGE, (), True),
    ("liens.phrase", "Toutes les réponses sont dans ces pages, ou à un clic depuis elles.", "Les liens · la phrase",
     "Sous le titre des liens. Vide : la phrase disparaît.", 300, True, _PAGE, (), False),
    ("enregistre", "Enregistré", "« Enregistré »", "Le petit mot qui dit que la saisie est gardée.", 30, True, _PAGE, (),
     True),
    ("enregistrement", "Enregistrement…", "« Enregistrement… »", "Pendant que la saisie part.", 30, True, _PAGE, (), True),
    ("hors_ligne", "Pas de connexion : tes réponses sont gardées sur cet appareil et partiront dès son retour.",
     "Sans connexion", "Quand le réseau saute pendant la saisie.", 300, True, _PAGE, (), True),
    ("etape", "Étape {numero} sur {total}", "Le numéro de l'étape", "En tête de chaque étape (la fiche est l'étape 1).",
     60, True, _ETAPES, (_NUMERO, _TOTAL), True),
    ("etape.seule", "Le questionnaire", "Le titre d'une seule étape", "Quand le questionnaire n'a qu'une étape.", 60, True,
     _ETAPES, (), True),
    ("fiche", "Ta fiche de candidature", "L'étape de la fiche", "L'étape 1, remplie à l'ouverture du ticket.", 60, True,
     _ETAPES, (), True),
    ("fermee", "Pas encore ouverte", "Une étape pas encore ouverte", "Une étape que la direction n'a pas encore ouverte.",
     60, True, _ETAPES, (), True),
    ("envoyee", "Envoyée", "Une étape envoyée", "Le tampon d'une étape déjà envoyée.", 30, True, _ETAPES, (), True),
    ("progression", "{faites} / {total} répondues", "La progression", "Sous les étapes : les questions déjà répondues.",
     60, True, _ETAPES, (("faites", "les questions répondues"), ("total", "le nombre de questions")), True),
    ("question", "Question {numero}", "Le numéro d'une question", "Au-dessus de chaque question.", 40, True, _ETAPES,
     (("numero", "le numéro de la question"),), True),
    ("exemple", "Ta réponse", "L'exemple dans chaque champ", "Le texte gris dans le champ de réponse.", 100, True,
     _ETAPES, (), True),
    ("precedent", "Étape précédente", "Le bouton « Étape précédente »", "Pour revenir en arrière.", 40, True, _ETAPES, (),
     True),
    ("suivant", "Étape suivante", "Le bouton « Étape suivante »", "Pour passer à l'étape d'après.", 40, True, _ETAPES, (),
     True),
    ("en_cours", "Étape en cours", "Le bouton « Étape en cours »", "Depuis une étape déjà envoyée, pour y revenir.", 40,
     True, _ETAPES, (), True),
    ("relire", "Relire et envoyer", "Le bouton « Relire et envoyer »", "Un questionnaire envoyé en une fois.", 40, True,
     _ETAPES, (), True),
    ("relire.titre", "Relis tes réponses", "La relecture · le titre", "Avant l'envoi.", 60, True, _ETAPES, (), True),
    ("relire.phrase", "Vérifie tout avant d'envoyer : une fois envoyées, tes réponses ne se modifient plus.",
     "La relecture · la phrase", "Sous le titre de la relecture.", 300, True, _ETAPES, (), True),
    ("manque", "Réponses manquantes : {n}. Chaque question en demande une.", "Une réponse manque",
     "Quand des questions n'ont pas encore de réponse.", 200, True, _ETAPES, (("n", "le nombre de réponses manquantes"),),
     True),
    ("vide", "Pas encore de réponse", "Une question sans réponse", "Dans la relecture.", 60, True, _ETAPES, (), True),
    ("modifier", "Modifier", "Le bouton « Modifier »", "Dans la relecture : revenir à une étape.", 30, True, _ETAPES, (),
     True),
    ("envoyer", "Envoyer mes réponses", "Le bouton « Envoyer mes réponses »", "Un questionnaire envoyé en une fois.", 40,
     True, _ETAPES, (), True),
    ("envoyer_etape", "Envoyer cette étape", "Le bouton « Envoyer cette étape »", "Quand la direction ouvre les étapes une "
     "à une.", 40, True, _ETAPES, (), True),
    ("confirmer.titre", "Envoyer tes réponses ?", "La confirmation · le titre", "Avant l'envoi.", 60, True, _ETAPES, (),
     True),
    ("confirmer.texte", "Une fois envoyées, elles ne se modifient plus. La direction les lit.",
     "La confirmation · la phrase", "Sous le titre de la confirmation.", 300, True, _ETAPES, (), True),
    ("envoi_impossible", "L'envoi n'est pas parti : vérifie ta connexion et réessaie.", "L'envoi raté",
     "Quand la connexion saute au moment d'envoyer.", 300, True, _ETAPES, (), True),
    ("attente.titre", "Réponses envoyées", "L'attente · le titre", "Après l'envoi d'une étape, avant la suite.", 60, True,
     _FIN, (), True),
    ("attente.texte", "La direction les regarde : tu seras prévenu dans ton ticket.\n-# The leadership is reviewing them: "
                      "you'll be notified in your ticket.", "L'attente · la phrase", "Il n'y a plus rien à faire.", 600,
     False, _FIN, (), True),
    ("merci.titre", "Merci", "Merci · le titre", "Après le dernier envoi.", 40, True, _FIN, (), True),
    ("merci.texte", "Tes réponses sont transmises à la direction. Tu peux fermer cette page.\n-# Thank you, your answers "
                    "have been sent to the leadership. You can close this page.", "Merci · la phrase",
     "Après le dernier envoi (et si le candidat rouvre son lien).", 600, False, _FIN, (), True),
    ("merci.reponses", "Tes réponses", "Ses réponses", "Le titre de ses réponses, en lecture seule.", 40, True, _FIN, (),
     True),
    ("remplace.titre", "Ce questionnaire a été remplacé", "Remplacé · le titre",
     "Quand la direction envoie un nouveau questionnaire.", 80, True, _FIN, (), True),
    ("remplace.texte", "Un nouveau questionnaire t'attend : dans ton ticket, touche « Répondre au questionnaire ».\n-# A "
                       "new questionnaire is waiting for you in your ticket.", "Remplacé · la phrase",
     "Sous le titre précédent.", 600, False, _FIN, (), True),
    ("ferme.titre", "Ta candidature est terminée", "Terminée · le titre",
     "Éliminé, refusé, accepté ou ticket fermé : la page ne le détaille jamais.", 80, True, _FIN, (), True),
    ("ferme.texte", "Ce questionnaire n'attend plus de réponse.\n-# Your application is over: this questionnaire no "
                    "longer takes answers.", "Terminée · la phrase", "Sous le titre précédent.", 600, False, _FIN, (),
     True),
    ("expire.titre", "Ce lien n'est plus valable", "Lien expiré · le titre", "Un lien trop vieux, ou une session finie.",
     80, True, _FIN, (), True),
    ("expire.texte", "Dans ton ticket sur Discord, touche « Répondre au questionnaire » pour en recevoir un nouveau : tes "
                     "réponses enregistrées t'y attendent.\n-# Ask for a new link in your ticket: your saved answers are "
                     "kept.", "Lien expiré · la phrase", "Sous le titre précédent.", 600, False, _FIN, (), True),
    ("servi.titre", "Ce lien a déjà servi", "Lien déjà ouvert · le titre", "Un lien ouvert une seconde fois ailleurs.", 80,
     True, _FIN, (), True),
    ("servi.texte", "Chaque lien ne s'ouvre qu'une fois : touche de nouveau « Répondre au questionnaire » sur Discord pour "
                    "en recevoir un nouveau.\n-# Each link opens once: ask for a new one on Discord.",
     "Lien déjà ouvert · la phrase", "Sous le titre précédent.", 600, False, _FIN, (), True),
    ("chef.entete", "Questionnaire de chef d'équipe", "Chef · la barre du haut", "Le nom de la page d'un chef d'équipe.",
     60, True, _CHEF, (), True),
    ("chef.titre", "Questionnaire de chef d'équipe · {metier}", "Chef · le titre", "En haut de la page.", 100, True, _CHEF,
     (_METIER,), True),
    ("chef.phrase", "Chaque réponse doit être juste : prends le temps de vérifier.", "Chef · la phrase",
     "Sous le titre : la règle, dite clairement.", 160, True, _CHEF, (), True),
    ("chef.intro", "La direction te propose de devenir chef d'équipe. Réponds avec tes propres mots : chaque réponse doit "
                   "être juste, il n'y a pas droit à l'erreur.\n-# Every answer must be right: there is no room for "
                   "mistakes.", "Chef · l'accueil", "Au début du questionnaire.", 800, False, _CHEF, (), True),
    ("chef.attente", "La direction les regarde : tu seras prévenu par message privé.\n-# The leadership is reviewing them: "
                     "you'll be notified by direct message.", "Chef · l'attente", "Après l'envoi d'une étape.", 600, False,
     _CHEF, (), True),
    ("chef.merci", "Tes réponses sont transmises à la direction : tu seras prévenu par message privé.\n-# Your answers "
                   "have been sent to the leadership.", "Chef · merci", "Après le dernier envoi.", 600, False, _CHEF, (),
     True),
    ("chef.expire", "Rouvre le message privé de la direction et touche « Répondre au questionnaire » pour en recevoir un "
                    "nouveau : tes réponses enregistrées t'y attendent.\n-# Open the leadership's direct message again "
                    "to get a new link.", "Chef · lien expiré", "Un lien trop vieux, ou une session finie.", 600, False,
     _CHEF, (), True),
    ("chef.remplace", "Un nouveau questionnaire t'attend : ouvre le dernier message privé de la direction.\n-# A new "
                      "questionnaire is waiting for you in your direct messages.", "Chef · remplacé",
     "Quand la direction envoie un nouveau questionnaire.", 600, False, _CHEF, (), True),
    ("chef.mp", "### Chef d'équipe · {metier}\nLa direction te propose de devenir chef d'équipe · {metier}. Si tu le veux, "
                "réponds à son questionnaire : chaque réponse doit être juste.\n-# The leadership offers you to become a "
                "team leader. If you want it, answer its questionnaire: every answer must be right.",
     "Chef · le message privé", "L'invitation envoyée au membre, avec le bouton.", 1500, False, _CHEF, (_METIER,), True),
    ("chef.mp.etape", "### Chef d'équipe · {metier}\nL'étape {numero} de ton questionnaire est ouverte : réponds-y avec le "
                      "bouton ci-dessous. Chaque réponse doit être juste.\n-# Step {numero} of your team leader "
                      "questionnaire is open.", "Chef · l'étape suivante (message privé)",
     "Quand la direction ouvre l'étape suivante d'un chef d'équipe.", 1500, False, _CHEF, (_METIER, _NUMERO), True),
    ("chef.bouton", "Répondre au questionnaire", "Chef · le bouton du message privé", "Il donne le lien personnel.", 80,
     True, _CHEF, (), True),
    ("lien.texte", "**Ton questionnaire** : ce lien est à toi seul et ne s'ouvre qu'une fois. Tes réponses s'enregistrent "
                   "pendant que tu écris.\n-# Your questionnaire: this link is yours only and opens once. Your answers "
                   "save as you type.", "Le lien personnel", "Le message pour le candidat seul, après le bouton.",
     800, False, _DISCORD, (), True),
    ("lien.bouton", "Ouvrir le questionnaire", "Le lien · le bouton", "Il ouvre la page du questionnaire.", 80, True,
     _DISCORD, (), True),
    ("lien.seul", "Ce questionnaire est réservé à la personne à qui il est destiné.\n-# This questionnaire is reserved for "
                  "its recipient.", "Le refus · quelqu'un d'autre", "Quand une autre personne touche le bouton.", 400,
     False, _DISCORD, (), True),
    ("lien.aucun", "Aucun questionnaire ne t'attend pour le moment.\n-# No questionnaire is waiting for you right now.",
     "Le refus · rien à remplir", "Quand aucun questionnaire n'est ouvert.", 400, False, _DISCORD, (), True),
    ("lien.deja", "Tes réponses sont déjà transmises à la direction.\n-# Your answers have already been sent to the "
                  "leadership.", "Le refus · déjà envoyé", "Quand le candidat a déjà tout envoyé.", 400, False, _DISCORD,
     (), True),
    ("lien.clan", "Ce questionnaire est réservé aux membres du clan.\n-# This questionnaire is for clan members only.",
     "Le refus · hors du clan", "Un chef d'équipe qui n'a plus le rôle du clan.", 400, False, _DISCORD, (), True),
)
for _k, (_cle, _defaut, _titre, _aide, _max, _ligne, _partie, _vars, _requis) in enumerate(TEXTES):
    textes.declarer(f"candidature.{_cle}", _defaut, groupe=GROUPE, titre=_titre, aide=_aide, max_=_max, lignes=not _ligne,
                    partie=_partie, variables=_vars, ordre=10 + _k, requis=_requis)
#  Les clés que la page lit (dans sa propre lecture : la portée « candidat » n'entre jamais dans `textes/site`).
PAGE = tuple(f"candidature.{cle}" for cle, *_r in TEXTES
             if not cle.startswith(("lien.", "servi.", "chef.mp")) and cle != "chef.bouton")


def _t(g, cle: str, **valeurs) -> str:
    """Un texte de la famille (registre `textes.py`) : celui de ce serveur, sinon celui d'origine."""
    return textes.texte_cache(getattr(g, "id", g) or 0, cle, **valeurs)


def textes_page(g) -> dict:
    return {cle: _t(g, cle) for cle in PAGE}


# ═══════════════════════════════════════════════════════════════════════════════
#  Branchement et base
# ═══════════════════════════════════════════════════════════════════════════════

def setup(*, get_db, cfg, log=None):
    """`cfg(guild_id)` (async) : les réglages du serveur (le rôle du clan). Branche aussi la porte de `tableau`
    (`AUTORISE_CANDIDAT`) : sans elle, aucune session « candidat » n'entre nulle part."""
    global _get_db, _cfg, _log
    _get_db, _cfg, _log = get_db, cfg, log or print
    for d in (_liaisons, _contextes, _seaux, _colonnes):
        d.clear()
    for v in _direct.values():
        if v.get("minuteur") is not None:
            v["minuteur"].cancel()
    _direct.clear()
    tableau.AUTORISE_CANDIDAT = autorise


def pret() -> bool:
    return _get_db is not None


def _signaler(code: str, message: str, ex=None, detail: str = "") -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    _log(f"[CANDIDATURE][{code}] {message}")
    _log(f"[CANDIDATURE][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    if ex is not None:
        diag.compter("candidature", code, ex)


async def init_db():
    async with _get_db() as db:
        #  La liaison d'une session « candidat » à SON questionnaire (un envoi ; le ticket 0 pour un chef d'équipe).
        await db.execute("CREATE TABLE IF NOT EXISTS candidature_sessions (empreinte TEXT PRIMARY KEY,"
                         " guild_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL,"
                         " envoi_id INTEGER NOT NULL, expire_le INTEGER NOT NULL)")
        #  Les brouillons, pendant la saisie : JAMAIS des réponses (celles-ci vont dans `recrutement_reponses` à l'envoi).
        await db.execute("CREATE TABLE IF NOT EXISTS candidature_brouillons (envoi_id INTEGER NOT NULL,"
                         " rang INTEGER NOT NULL, guild_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL,"
                         " texte TEXT NOT NULL, maj_le INTEGER NOT NULL, PRIMARY KEY (envoi_id, rang))")
        #  La page du candidat : sa première ouverture (une ligne de journal), sa dernière visite, son étape.
        await db.execute("CREATE TABLE IF NOT EXISTS candidature_etat (envoi_id INTEGER PRIMARY KEY,"
                         " guild_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL,"
                         " ouvert_le INTEGER NOT NULL DEFAULT 0, vu_le INTEGER NOT NULL DEFAULT 0,"
                         " etape INTEGER NOT NULL DEFAULT 1, rang INTEGER NOT NULL DEFAULT 0)")
        await db.commit()


async def demarrer() -> int:
    """Au démarrage : les liaisons expirées, les brouillons d'un questionnaire qui n'attend plus de réponse, l'état des
    pages d'un envoi effacé. Rend le nombre de lignes retirées."""
    t = int(time.time())
    n = 0
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM candidature_sessions WHERE expire_le < ?", (t,))
        n += max(cur.rowcount or 0, 0)
        try:
            cur = await db.execute("DELETE FROM candidature_brouillons WHERE envoi_id NOT IN (SELECT id FROM"
                                   " recrutement_envois WHERE statut IN ('envoye', 'en_cours'))")
            n += max(cur.rowcount or 0, 0)
            cur = await db.execute("DELETE FROM candidature_etat WHERE envoi_id NOT IN (SELECT id FROM recrutement_envois)")
            n += max(cur.rowcount or 0, 0)
        except sqlite3.OperationalError as ex:   # sans le recrutement (une base neuve) : rien à ranger
            if "no such table" not in str(ex):
                raise
        await db.commit()
    return n


async def _lire(sql: str, args: tuple = ()) -> list:
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            return list(await cur.fetchall())


async def _lire_tolerant(sql: str, args: tuple = ()) -> list:
    """Une table du bot (`tickets`) : absente (base neuve, tests) = rien, le reste remonte."""
    try:
        return await _lire(sql, args)
    except sqlite3.OperationalError as ex:
        if "no such table" not in str(ex):
            raise
        return []


def _garder(coro) -> asyncio.Task:
    t = asyncio.get_running_loop().create_task(coro)
    _taches.add(t)
    t.add_done_callback(_taches.discard)
    return t


def _texte_net(texte, maxi: int, lignes: bool = False) -> str:
    t = _CONTROLE.sub(" ", str(texte or ""))
    t = re.sub(r"[^\S\n]+", " ", t) if lignes else re.sub(r"\s+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()[:maxi]


def _entier(x) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.isdigit() and len(x) <= 6:
        return int(x)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Un envoi : ses colonnes, ses étapes et leurs portes, où il en est
# ═══════════════════════════════════════════════════════════════════════════════

async def _colonnes_envois() -> set:
    t = time.monotonic()
    if _colonnes.get("noms") is not None and t - _colonnes["vu"] < COLONNES_FRAICHES:
        return _colonnes["noms"]
    try:
        noms = {r[1] for r in await _lire("PRAGMA table_info(recrutement_envois)")}
    except sqlite3.Error as ex:
        _signaler("E7", "colonnes des envois illisibles", ex)
        noms = set()
    _colonnes.update(vu=t, noms=noms)
    return noms


async def envoi_complet(eid: int) -> dict | None:
    """L'envoi (`questionnaire._envoi`) et ce que lui ajoutent le passage d'étape et les chefs d'équipe (`EXTRAS`)."""
    e = await questionnaire._envoi(int(eid))
    if e is None:
        return None
    manquent = [c for c, _d in EXTRAS if c not in e]
    lisibles = [c for c in manquent if c in await _colonnes_envois()]
    if lisibles:
        r = await _lire(f"SELECT {', '.join(lisibles)} FROM recrutement_envois WHERE id=?", (int(e["id"]),))
        if r:
            e.update(zip(lisibles, r[0]))
    for c, defaut in EXTRAS:
        if e.get(c) is None:
            e[c] = defaut
    return e


def etapes_de(questions: list, brut) -> list:
    """[{numero, titre, consigne, questions: [{rang, question}]}] — les étapes NON vides, dans l'ordre de leur numéro (ceux
    déclarés et ceux que portent les questions). Sans étapes déclarées (un envoi d'avant), une seule avec toutes les
    questions. Une question sans étape valable va dans la première. Ni réponse attendue, ni variante, ni source : le texte
    de la question seulement."""
    if isinstance(brut, str):
        try:
            brut = json.loads(brut or "[]")
        except ValueError:
            brut = []
    declarees: dict = {}
    for x in brut if isinstance(brut, list) else []:
        if not isinstance(x, dict) or isinstance(x.get("numero"), bool):
            continue
        try:
            n = int(x.get("numero"))
        except (TypeError, ValueError):
            continue
        if 1 <= n <= ETAPES_MAX and n not in declarees:
            declarees[n] = {"numero": n, "titre": _texte_net(x.get("titre"), TITRE_ETAPE_MAX),
                            "consigne": _texte_net(x.get("consigne"), CONSIGNE_MAX, lignes=True)}
    qs = sorted((q for q in questions or [] if isinstance(q, dict)), key=lambda q: int(q.get("rang") or 0))
    portees = {questionnaire.etape_de_question(q) for q in qs if "etape" in q}
    numeros = sorted(set(declarees) | {n for n in portees if n <= ETAPES_MAX}) or [1]
    par = {n: [] for n in numeros}
    for q in qs:
        n = questionnaire.etape_de_question(q) if "etape" in q else numeros[0]
        par[n if n in par else numeros[0]].append({"rang": int(q["rang"]), "question": str(q.get("question") or "")})
    return [dict(declarees.get(n) or {"numero": n, "titre": "", "consigne": ""}, questions=par[n])
            for n in numeros if par[n]]


def portes_de(e: dict, etapes: list) -> dict:
    """Le passage d'étape : `mode` « etapes » (la direction ouvre chaque étape) ou « unique » (un envoi d'avant : tout
    ouvert, un seul envoi), l'étape ouverte, la dernière envoyée, la fiche (l'« Étape 1 » du candidat), le nombre d'étapes
    du questionnaire et le numéro de la dernière, l'étape à remplir (`courante`, 0 : aucune)."""
    derniere = max((x["numero"] for x in etapes), default=1)
    ouverte = max(0, min(int(e.get("etape_ouverte") or 0), derniere))
    envoyee = max(0, min(int(e.get("etape_envoyee") or 0), derniere))
    mode = "etapes" if ouverte > 0 else "unique"
    courante = ouverte if mode == "etapes" and envoyee < ouverte and any(x["numero"] == ouverte for x in etapes) else 0
    return {"mode": mode, "ouverte": ouverte, "envoyee": envoyee, "fiche": 1 if int(e.get("etape_fiche") or 0) else 0,
            "total": len(etapes), "derniere": derniere, "courante": courante}


def est_chef(e: dict | None) -> bool:
    """Un envoi de chef d'équipe : `nature` « chef », ou aucun ticket (ticket 0)."""
    return bool(e) and (str(e.get("nature") or "") == "chef" or not int(e.get("ticket_id") or 0))


async def _du_clan(g, uid: int) -> bool:
    """Le rôle du clan (réglages Rell Seas), lu à chaque appel (en mémoire : un rôle retiré coupe tout de suite)."""
    m = g.get_member(int(uid)) if g is not None else None
    return m is not None and _cfg is not None and tableau.autorise_equipage(g, m, await _cfg(g.id))


async def _ticket_ouvert(g, tid: int) -> bool:
    r = await _lire_tolerant("SELECT status FROM tickets WHERE id=? AND guild_id=?", (int(tid), g.id))
    return bool(r) and r[0][0] == "open"


async def contexte(g, envoi_id: int, candidat_id: int | None = None) -> dict:
    """L'envoi et où il en est : `etat` ∈ ouvert (quelque chose à remplir) · attente (étape envoyée, la direction décide)
    · envoye · remplace · ferme · inconnu. `candidat_id` : l'envoi doit être le sien (sinon « inconnu »). Un ticket fermé,
    une fermeture prévue, une décision prise → « ferme » ; pour un chef d'équipe (aucun ticket) : l'envoi clos, ou le rôle
    du clan perdu."""
    e = await envoi_complet(int(envoi_id))
    if e is None or int(e["guild_id"]) != int(getattr(g, "id", 0) or 0) or \
            (candidat_id is not None and int(e["candidat_id"]) != int(candidat_id)):
        return {"etat": "inconnu", "envoi": None, "suivi": None, "etapes": [], "portes": None, "chef": False}
    etapes = etapes_de(e["questions"], e["etapes"])
    portes = portes_de(e, etapes)
    chef = est_chef(e)
    s = None
    if chef:
        if not await _du_clan(g, int(e["candidat_id"])):
            etat = "ferme"
        elif e["statut"] == "remplace":
            etat = "remplace"
        elif e["statut"] == "repondu":
            etat = "envoye"
        elif e["statut"] not in questionnaire.EN_ATTENTE:
            etat = "ferme"
        else:
            etat = "ouvert"
    else:
        s = await questionnaire._suivi(g.id, int(e["ticket_id"]))
        if s is None or not await _ticket_ouvert(g, int(e["ticket_id"])):
            etat = "ferme"
        elif int(s["envoi_id"] or 0) != int(e["id"]) or e["statut"] == "remplace":
            etat = "remplace"
        elif e["statut"] == "repondu":
            etat = "envoye"
        elif e["statut"] not in questionnaire.EN_ATTENTE or s["fermeture_le"] or s["etape"] in questionnaire.FINALES:
            etat = "ferme"
        else:
            etat = "ouvert"
    if etat == "ouvert" and portes["mode"] == "etapes" and not portes["courante"]:
        etat = "attente"
    return {"etat": etat, "envoi": e, "suivi": s, "etapes": etapes, "portes": portes, "chef": chef}


async def _contexte_frais(g, lien: dict) -> dict:
    """Le contexte d'un envoi, relu en base au plus toutes les quelques secondes (les frappes : rien n'y est écrit) ; le
    rôle du clan d'un chef d'équipe, lui, est relu à chaque fois."""
    t = time.monotonic()
    deja = _contextes.get(lien["envoi"])
    if deja is not None and t - deja[0] < CONTEXTE_FRAIS:
        ctx = deja[1]
        if ctx["chef"] and ctx["etat"] in ("ouvert", "attente") and not await _du_clan(g, int(lien["candidat"])):
            ctx = dict(ctx, etat="ferme")
        return ctx
    ctx = await contexte(g, lien["envoi"], lien["candidat"])
    _contextes[lien["envoi"]] = (t, ctx)
    if len(_contextes) > 500:
        for k in sorted(_contextes, key=lambda k: _contextes[k][0])[:100]:
            _contextes.pop(k, None)
    return ctx


def _rangs_etape(ctx: dict, numero: int) -> set:
    return {q["rang"] for x in ctx["etapes"] if x["numero"] == numero for q in x["questions"]}


def rangs_modifiables(ctx: dict) -> set:
    """Les questions que le candidat peut écrire maintenant : toutes (un envoi d'avant), sinon celles de l'étape ouverte
    pas encore envoyée — aucune hors de l'état « ouvert »."""
    if ctx["etat"] != "ouvert":
        return set()
    p = ctx["portes"]
    if p["mode"] == "unique":
        return {q["rang"] for x in ctx["etapes"] for q in x["questions"]}
    return _rangs_etape(ctx, p["courante"]) if p["courante"] else set()


def _liens_publics(liens: list) -> list:
    """Les liens donnés au candidat : titre, adresse (https seulement), description."""
    out = []
    for x in liens or []:
        url = str((x or {}).get("url") or "")
        if isinstance(x, dict) and re.fullmatch(r"https://[^\s<>\"'`\\]{3,300}", url):
            out.append({"titre": _texte_net(x.get("titre"), 80) or url, "url": url,
                        "description": _texte_net(x.get("description"), 150)})
    return out


async def _brouillons(envoi_id: int) -> dict:
    rows = await _lire("SELECT rang, texte, maj_le FROM candidature_brouillons WHERE envoi_id=?", (int(envoi_id),))
    return {int(r[0]): (str(r[1]), int(r[2] or 0)) for r in rows}


async def _reponses(e: dict, avec_brouillons: bool) -> dict:
    """{rang: (texte, quand)} : les réponses gardées (envoyées étape par étape, ou par le formulaire Discord), puis — tant
    que le questionnaire attend — les brouillons du site par-dessus."""
    out = {rang: (r["texte"], r["recu_le"]) for rang, r in (await questionnaire._reponses(e["id"])).items()}
    if avec_brouillons:
        out.update(await _brouillons(e["id"]))
    return out


async def nom_metier(metier) -> str:
    """Le nom d'un métier (`metier` d'un envoi de chef : sa clé du catalogue, ou déjà son nom)."""
    m = _texte_net(metier, 80)
    if not m:
        return ""
    import affiches
    if getattr(affiches, "_get_db", None) is None:
        return m
    try:
        _types, elements = await affiches._catalogue()
    except Exception as ex:   # le catalogue ne répond pas : le métier tel qu'écrit, et le détail au journal
        _signaler("E6", "catalogue des métiers illisible", ex)
        return m
    el = elements.get(("metier", m))
    return _texte_net(el.get("nom"), 80) if el and el.get("nom") else m


# ═══════════════════════════════════════════════════════════════════════════════
#  Les sessions « candidat » : liées à UN envoi
# ═══════════════════════════════════════════════════════════════════════════════

async def ouvrir_session(guild_id: int, candidat_id: int, ticket_id: int, envoi_id: int, expire: int) -> str:
    """Une session « candidat » (`tableau_sessions`) et sa liaison à l'envoi : rend l'identifiant du cookie."""
    t = int(time.time())
    sid = await tableau._ouvrir_session(int(guild_id), int(candidat_id), int(expire), portee="candidat")
    emp = tableau._empreinte(sid)
    lien = {"guild": int(guild_id), "candidat": int(candidat_id), "ticket": int(ticket_id or 0), "envoi": int(envoi_id),
            "expire": int(expire)}
    async with _get_db() as db:
        await db.execute("DELETE FROM candidature_sessions WHERE expire_le < ?", (t,))
        await db.execute("INSERT OR REPLACE INTO candidature_sessions (empreinte, guild_id, candidat_id, ticket_id,"
                         " envoi_id, expire_le) VALUES (?,?,?,?,?,?)",
                         (emp, lien["guild"], lien["candidat"], lien["ticket"], lien["envoi"], lien["expire"]))
        await db.commit()
    _liaisons[emp] = (time.monotonic(), lien)
    return sid


async def liaison(emp: str) -> dict | None:
    """{guild, candidat, ticket, envoi, expire} d'une session « candidat », ou None (relue en base chaque minute)."""
    t = time.monotonic()
    deja = _liaisons.get(emp)
    if deja is not None and t - deja[0] < LIAISON_FRAICHE:
        lien = deja[1]
    else:
        r = await _lire("SELECT guild_id, candidat_id, ticket_id, envoi_id, expire_le FROM candidature_sessions"
                        " WHERE empreinte=?", (str(emp),))
        lien = ({"guild": int(r[0][0]), "candidat": int(r[0][1]), "ticket": int(r[0][2]), "envoi": int(r[0][3]),
                 "expire": int(r[0][4])} if r else None)
        _liaisons[emp] = (t, lien)
        if len(_liaisons) > LIAISONS_MAX:
            for k in sorted(_liaisons, key=lambda k: _liaisons[k][0])[:LIAISONS_MAX // 4]:
                _liaisons.pop(k, None)
    if lien is None or lien["expire"] < time.time():
        return None
    return lien


async def autorise(g, membre, emp: str) -> str:
    """La porte de `tableau` (`AUTORISE_CANDIDAT`) : « » si cette session « candidat » est bien celle de ce membre, sur ce
    serveur, liée à un questionnaire — sinon la raison du refus. (L'état du questionnaire, le ticket, le rôle du clan d'un
    chef d'équipe : relus par chaque lecture et chaque écriture, `contexte`.)"""
    if g is None or membre is None or getattr(membre, "bot", False) or not pret():
        return "Accès retiré."
    lien = await liaison(emp)
    if lien is None or lien["guild"] != int(g.id) or lien["candidat"] != int(membre.id):
        return "Accès retiré."
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Le direct : l'état vivant du candidat, diffusé au débit borné
# ═══════════════════════════════════════════════════════════════════════════════

def _vivant(gid: int, envoi: int, ticket: int = 0) -> dict:
    cle = (int(gid), int(envoi))
    v = _direct.get(cle)
    if v is None:
        v = _direct[cle] = {"envoi": int(envoi), "ticket": int(ticket or 0), "textes": {}, "ecrits": {}, "etape": 0,
                            "rang": 0, "vu": 0, "vue": "", "ecrit": 0, "attente": {}, "dernier": 0.0, "minuteur": None,
                            "vu_base": 0.0}
        if len(_direct) > DIRECT_MAX:
            for k in sorted(_direct, key=lambda k: _direct[k]["vu"])[:DIRECT_MAX // 5]:
                if k != cle:
                    x = _direct.pop(k)
                    if x.get("minuteur") is not None:
                        x["minuteur"].cancel()
    return v


def _pousser(gid: int, v: dict, patch: dict) -> None:
    """Le débit borné : un message « candidat » au plus toutes les PAS_DIRECT secondes par candidat ; ce qui arrive entre
    deux est regroupé — le dernier texte de chaque question, la dernière page, la dernière étape partent toujours."""
    for k, x in patch.items():
        if k in ("rep", "ec"):
            v["attente"].setdefault(k, {}).update(x)
        else:
            v["attente"][k] = x
    if v["minuteur"] is not None:
        return
    reste = PAS_DIRECT - (time.monotonic() - v["dernier"])
    if reste <= 0:
        _vider(gid, v)
        return
    try:
        v["minuteur"] = asyncio.get_running_loop().call_later(reste, _vider, gid, v)
    except RuntimeError:   # aucune boucle (un appel hors du serveur) : tout de suite
        _vider(gid, v)


def _vider(gid: int, v: dict) -> None:
    v["minuteur"] = None
    if not v["attente"]:
        return
    m = {"k": v["ticket"], "e": v["envoi"], "s": int(time.time()), **v["attente"]}
    v["attente"] = {}
    v["dernier"] = time.monotonic()
    try:
        tableau.diffuser_candidat(gid, m)
    except Exception as ex:   # le direct ne bloque jamais le candidat ; le détail part au journal
        _signaler("E2", "direct du questionnaire non diffusé", ex)


def _portes_direct(ctx: dict) -> dict:
    p = ctx.get("portes") or {}
    return {"o": p.get("ouverte", 0), "env": p.get("envoyee", 0), "f": p.get("fiche", 0)}


async def _vu(g, lien: dict, ctx: dict, *, vue: str | None = None, etape=None, rang=None, persister=False) -> dict:
    """Le candidat donne des nouvelles (toute requête) : sa dernière visite, sa page, son étape — gardées en mémoire,
    en base au plus une fois par minute (et à la fermeture de la page)."""
    e = ctx.get("envoi")
    if e is None:
        return {}
    v = _vivant(g.id, e["id"], int(e["ticket_id"] or 0))
    t = int(time.time())
    patch = {"vu": t, "etat": ctx["etat"], "po": _portes_direct(ctx)}
    v["vu"] = t
    if vue == "cachee" and v["vue"] == "fermee" and time.monotonic() - v.get("ferme_t", 0.0) < 3:
        vue = None   # la page cachée PUIS fermée : les deux arrivent ensemble, la fermeture compte
    if vue in VUES and vue != v["vue"]:
        v["vue"] = patch["vue"] = vue
        if vue == "fermee":
            v["ferme_t"] = time.monotonic()
    elif not v["vue"]:
        v["vue"] = patch["vue"] = "ouverte"
    for nom, x in (("etape", etape), ("rang", rang)):
        if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 1000 and x != v[nom]:
            v[nom] = x
            patch["et" if nom == "etape" else "r"] = x
    _pousser(g.id, v, patch)
    if persister or time.monotonic() - v["vu_base"] > VU_EN_BASE_S:
        v["vu_base"] = time.monotonic()
        try:
            async with _get_db() as db:
                await db.execute("UPDATE candidature_etat SET vu_le=?, etape=?, rang=? WHERE envoi_id=?",
                                 (t, int(v["etape"] or 1), int(v["rang"] or 0), int(e["id"])))
                await db.commit()
        except sqlite3.Error as ex:   # seulement la dernière visite : la page continue
            _signaler("E3", "dernière visite non gardée", ex)
    return v


# ═══════════════════════════════════════════════════════════════════════════════
#  Discord : le lien personnel (le bouton du ticket, le bouton du message privé d'un chef d'équipe)
# ═══════════════════════════════════════════════════════════════════════════════

async def lien_envoi(i, envoi_id) -> tuple:
    """(lien personnel, "") — ou (None, le refus, dit tel quel à la personne). Au candidat de CET envoi seulement, et
    seulement si le questionnaire l'attend (à remplir, ou une étape envoyée en attente de la suite) ; un chef d'équipe
    doit avoir TOUJOURS le rôle du clan. Le serveur vient de l'envoi (le bouton d'un message privé n'en a pas)."""
    u = getattr(i, "user", None)
    if u is None or not pret() or not questionnaire.pret() or not tableau._base or not tableau._cle:
        return None, "Le questionnaire en ligne n'est pas joignable pour le moment."
    eid = _entier(envoi_id)
    e = await envoi_complet(eid) if eid else None
    g = tableau._bot.get_guild(int(e["guild_id"])) if e is not None and tableau._bot is not None else None
    ici = getattr(i, "guild", None)
    if g is None or (ici is not None and int(ici.id) != int(g.id)):
        return None, _t(ici, "candidature.lien.aucun")
    await textes.texte(g.id, "candidature.lien.aucun")   # le cache des textes est chargé
    if int(e["candidat_id"]) != int(u.id):
        return None, _t(g, "candidature.lien.seul")
    ctx = await contexte(g, int(e["id"]), u.id)
    if ctx["chef"] and not await _du_clan(g, u.id):
        return None, _t(g, "candidature.lien.clan")
    if ctx["etat"] == "envoye":
        return None, _t(g, "candidature.lien.deja")
    if ctx["etat"] not in ("ouvert", "attente"):
        return None, _t(g, "candidature.lien.aucun")
    if await tableau.suspendu(g.id, u.id):
        return None, "Ton accès au site est suspendu pour le moment. Réessaie plus tard."
    nonce = f"e{int(e['id'])}x{secrets.token_urlsafe(9)}"
    return f"{tableau._base}{tableau.CANDIDATURE}{tableau.jeton(g.id, u.id, 'candidat', nonce=nonce)}", ""


def joignable() -> bool:
    """La page du candidat peut servir : ce module, le recrutement et le site (son adresse, sa clé) sont branchés."""
    return pret() and questionnaire.pret() and bool(tableau._base) and bool(tableau._cle)


async def lien_ticket(i, ticket: int) -> tuple:
    """(lien personnel, "") ou (None, le refus) — le questionnaire en cours de ce TICKET (`lien_envoi`), pour son
    ouvreur seulement."""
    g, m = getattr(i, "guild", None), getattr(i, "user", None)
    if g is None or m is None or not pret() or not questionnaire.pret():
        return None, "Le questionnaire en ligne n'est pas joignable pour le moment."
    await textes.texte(g.id, "candidature.lien.aucun")
    tid = _entier(ticket)
    r = await _lire_tolerant("SELECT user_id, status FROM tickets WHERE id=? AND guild_id=?", (tid, g.id)) if tid else []
    if not r or r[0][1] != "open":
        return None, _t(g, "candidature.lien.aucun")
    if int(r[0][0] or 0) != int(m.id):
        return None, _t(g, "candidature.lien.seul")
    s = await questionnaire._suivi(g.id, tid)
    if s is None or not s["envoi_id"]:
        return None, _t(g, "candidature.lien.aucun")
    return await lien_envoi(i, int(s["envoi_id"]))


def _vue_avis(texte: str, couleur=Palette.NEUTRAL, lien: str = "", bouton: str = "") -> LayoutView:
    v = LayoutView(timeout=AVIS_S)
    morceaux = [discord.ui.TextDisplay(str(texte)[:3900])]
    if lien:
        morceaux.append(discord.ui.ActionRow(Button(label=(bouton or "Ouvrir")[:80], url=lien)))
    v.add_item(discord.ui.Container(*morceaux, accent_color=couleur))
    return v


def _effacer_plus_tard(i, delai: float = AVIS_S) -> None:
    """« Un avis est pour la personne seule » : il s'efface tout seul."""
    supprimer = getattr(i, "delete_original_response", None)
    if supprimer is None or not delai:
        return

    async def _plus_tard():
        await asyncio.sleep(delai)
        try:
            await supprimer()
        except discord.HTTPException:
            pass  # déjà fermé par la personne, ou le jeton de l'interaction a expiré : rien à faire
    _garder(_plus_tard())


async def _repondre_lien(i, url, refus: str, g) -> None:
    if url:
        vue = _vue_avis(_t(g, "candidature.lien.texte"), discord.Color(0xA8823F), url, _t(g, "candidature.lien.bouton"))
    else:
        vue = _vue_avis(refus, Palette.WARNING)
    if i.response.is_done():
        await i.followup.send(view=vue, ephemeral=True)
    else:
        await i.response.send_message(view=vue, ephemeral=True)
    _effacer_plus_tard(i)


async def _lien_candidat(i, ticket: int) -> None:
    """`lien_candidat` — le point d'appel de l'équipe du recrutement (`questionnaire.ouvrir_formulaire` : « Répondre au
    questionnaire » du ticket, touché par le candidat) : son lien personnel — ou le refus — RÉPONDU ICI, pour lui seul,
    effacé après 3 minutes (une adresse http du site local passe aussi) ; rend None. La page injoignable : rien n'est
    répondu, les formulaires de Discord prennent le relais."""
    if not joignable():
        return None
    url, refus = await lien_ticket(i, ticket)
    await _repondre_lien(i, url, refus, getattr(i, "guild", None))
    return None


envoyer_lien = _lien_candidat   # le geste complet du bouton du ticket (l'ancien nom)


async def envoyer_lien_envoi(i, envoi_id: int) -> None:
    """Le geste complet du bouton du MESSAGE PRIVÉ (chef d'équipe) : le lien (ou le refus), pour la personne seule."""
    url, refus = await lien_envoi(i, envoi_id)
    e = await questionnaire._envoi(int(envoi_id)) if url else None
    g = tableau._bot.get_guild(int(e["guild_id"])) if e is not None and tableau._bot is not None else None
    await _repondre_lien(i, url, refus, g)


class BoutonQuestionnaire(discord.ui.DynamicItem[Button], template=r"cq:rep:(?P<eid>\d{1,12})"):
    """« Répondre au questionnaire » du message privé d'un chef d'équipe : PERSISTANT (`bot.add_dynamic_items` au
    démarrage ; `persistants.garder()` le protège d'une vue qui expire), l'envoi dans son custom_id."""

    def __init__(self, envoi: int, libelle: str = ""):
        self.envoi = int(envoi)
        super().__init__(Button(label=(libelle or textes.defaut("candidature.chef.bouton"))[:80],
                                style=discord.ButtonStyle.primary, custom_id=f"cq:rep:{int(envoi)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        try:
            await envoyer_lien_envoi(i, self.envoi)
        except Exception as ex:
            _signaler("E8", "bouton du questionnaire en échec", ex)
            try:
                vue = _vue_avis("Un souci est survenu : réessaie dans un instant.", Palette.WARNING)
                if i.response.is_done():
                    await i.followup.send(view=vue, ephemeral=True)
                else:
                    await i.response.send_message(view=vue, ephemeral=True)
            except discord.HTTPException as ex2:
                _signaler("E8", "réponse impossible", ex2)


def vue_invitation(g, e: dict, metier: str) -> LayoutView:
    """Le message privé d'un chef d'équipe : l'invitation (registre, « Chef · le message privé ») — ou, l'étape suivante
    ouverte par la direction, « Chef · l'étape suivante » — et le bouton persistant. Rien d'autre qui réponde : une vue
    de DynamicItem seulement, sans fin (le bouton marche après un redémarrage)."""
    v = LayoutView(timeout=None)
    ouverte = int(e.get("etape_ouverte") or 0)
    texte = (_t(g, "candidature.chef.mp.etape", metier=metier or "", numero=ouverte + int(e.get("etape_fiche") or 0))
             if ouverte > 1 else _t(g, "candidature.chef.mp", metier=metier or ""))
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay(texte[:3900]),
        discord.ui.ActionRow(BoutonQuestionnaire(int(e["id"]), _t(g, "candidature.chef.bouton"))),
        accent_color=discord.Color(0xA8823F)))
    return v


async def _inviter(g, e: dict) -> bool:
    """`inviter` — le contrat « chef d'équipe » : le message privé d'invitation au membre `e["candidat_id"]` (à la
    proposition, puis à chaque étape ouverte : « l'étape N est ouverte »), avec le bouton persistant « Répondre au
    questionnaire ». Rend False si ses messages privés sont fermés (ou s'il n'est plus là) — l'appelant le dit à la
    direction, avec une ligne au journal."""
    m = g.get_member(int(e["candidat_id"])) if g is not None else None
    if m is None or getattr(m, "bot", False):
        return False
    await textes.texte(g.id, "candidature.chef.mp")   # le cache des textes est chargé
    metier = await nom_metier(e.get("metier") if "metier" in e else (await envoi_complet(int(e["id"])) or {}).get("metier"))
    try:
        await m.send(view=vue_invitation(g, e, metier), allowed_mentions=discord.AllowedMentions.none())
    except discord.Forbidden:
        return False
    except discord.HTTPException as ex:
        _signaler("E5", "invitation de chef d'équipe non envoyée", ex, f"envoi={e.get('id')}")
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Les adresses du candidat (`/tableau/candidature/…`, health_server)
# ═══════════════════════════════════════════════════════════════════════════════

def _html_texte(texte: str) -> str:
    """Un texte du registre dans une page d'erreur (HTML) : échappé ; « -# » en petit."""
    lignes = []
    for ligne in str(texte or "").split("\n"):
        if ligne.startswith("-# "):
            lignes.append(f"<small style='font-size:13px;opacity:.8'>{html.escape(ligne[3:])}</small>")
        else:
            lignes.append(html.escape(ligne))
    return "<br>".join(lignes)


def _page_refus(g, quoi: str, status: int = 403, chef: bool = False):
    if quoi == "trop":
        return tableau._html(tableau.TROP, 429)
    quoi = quoi if quoi in ("expire", "servi", "remplace", "ferme") else "expire"
    gid = getattr(g, "id", 0) or 0
    cle = f"candidature.chef.{quoi}" if chef and quoi in ("expire", "remplace") else f"candidature.{quoi}.texte"
    return tableau._html(tableau._message(html.escape(_t(gid, f"candidature.{quoi}.titre")), _html_texte(_t(gid, cle))),
                         status)


async def vers_page(request):
    """`/tableau/candidature` sans la barre : la page est à `/tableau/candidature/`."""
    from aiohttp import web
    return web.Response(status=303, headers=dict(tableau.ENTETES, Location=tableau.CANDIDATURE))


async def entree(request):
    """`/tableau/candidature/<lien>` : le lien du candidat — vérifié (signé, portée « candidat », pas expiré), l'envoi qu'il
    porte encore à LUI (et, pour un chef d'équipe, le rôle du clan), consommé (une seule fois), changé en session liée à
    cet envoi ; puis la page."""
    from aiohttp import web
    if tableau._trop_essais(request):
        return _page_refus(None, "trop", 429)
    j = tableau.lire_jeton(request.match_info.get("jeton", ""))
    n = FORMAT_NONCE.fullmatch(j["n"]) if j and j["p"] == "candidat" else None
    g = tableau._bot.get_guild(j["g"]) if n and tableau._bot is not None else None
    membre = g.get_member(j["u"]) if g is not None else None
    ctx = {"etat": "inconnu", "chef": False}
    if membre is not None and not getattr(membre, "bot", False) and pret() and not await tableau.suspendu(g.id, membre.id):
        ctx = await contexte(g, int(n.group(1)), membre.id)
    if ctx["etat"] not in ("ouvert", "attente", "envoye"):
        tableau._trop_essais(request, compter=True)
        return _page_refus(g if ctx["etat"] != "inconnu" else None,
                           ctx["etat"] if ctx["etat"] in ("remplace", "ferme") else "expire", 403, chef=ctx["chef"])
    e = ctx["envoi"]
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO tableau_jetons (nonce, expire_le) VALUES (?,?)", (j["n"], j["e"]))
        await db.commit()
        neuf = bool(cur.rowcount)
    if not neuf:   # déjà servi : le même navigateur repasse (sa session est liée au même envoi), personne d'autre
        ses = await tableau._lire_session(request, cookie=tableau.COOKIE_CANDIDAT)
        lien = await liaison(ses[0]) if ses is not None and ses[2] == "candidat" else None
        if lien is not None and (lien["envoi"], lien["candidat"]) == (int(e["id"]), int(membre.id)):
            return web.Response(status=303, headers=dict(tableau.ENTETES, Location=tableau.CANDIDATURE))
        tableau._trop_essais(request, compter=True)
        return _page_refus(g, "servi", 403)
    sid = await ouvrir_session(g.id, membre.id, int(e["ticket_id"] or 0), int(e["id"]), j["e"])
    r = web.Response(status=303, headers=dict(tableau.ENTETES, Location=tableau.CANDIDATURE))
    r.set_cookie(tableau.COOKIE_CANDIDAT, sid, max_age=max(60, j["e"] - int(time.time())), path=tableau.CANDIDATURE,
                 secure=True, httponly=True, samesite="Lax")
    await noter_ouverture(g, membre, e)
    return r


async def noter_ouverture(g, membre, e: dict) -> bool:
    """La première ouverture d'un questionnaire : son état de page, et UNE ligne au journal (« questionnaire ouvert »)."""
    t = int(time.time())
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO candidature_etat (envoi_id, guild_id, ticket_id, candidat_id,"
                               " ouvert_le, vu_le) VALUES (?,?,?,?,?,?)",
                               (int(e["id"]), g.id, int(e["ticket_id"] or 0), int(membre.id), t, t))
        await db.commit()
        premiere = bool(cur.rowcount)
    if premiere:
        quoi = "questionnaire de chef d'équipe" if est_chef(e) else "questionnaire"
        await questionnaire._au_journal(g, "recrutement.en_ligne", f"Recrutement : <@{int(membre.id)}> a ouvert le {quoi}"
                                        " en ligne", membre_id=int(membre.id), auteur_id=int(membre.id))
    return premiere


async def page(request):
    """`/tableau/candidature/` : la page du candidat (`site/candidature.html`) — une session « candidat » seulement."""
    from aiohttp import web
    try:
        await tableau._verifier(request, portees=("candidat",), cookie=tableau.COOKIE_CANDIDAT)
    except tableau._Refus as r:
        return _page_refus(None, "trop" if r.status == 429 else "expire", r.status)
    texte = tableau._lire_page_site("candidature.html")
    if texte is None:
        return tableau._html(tableau._message("Page en maintenance", "Réessaie dans quelques minutes."), 503)
    r = web.Response(text=texte, content_type="text/html",
                     headers=dict(tableau.ENTETES, **{"Content-Security-Policy": tableau.CSP_SITE}))
    r.enable_compression()
    return r


async def api(request):
    """`GET|POST /tableau/candidature/api/<nom>` : les lectures et écritures DÉDIÉES du candidat — session « candidat »
    liée à son questionnaire, origine de la page pour toute écriture, taille du corps, cadence ; une erreur reste ici."""
    nom = str(request.match_info.get("nom", ""))
    try:
        j, g = await tableau._verifier(request, portees=("candidat",), cookie=tableau.COOKIE_CANDIDAT)
    except tableau._Refus as r:
        return tableau._json({"erreur": r.message, "etat": "expire"}, r.status)
    methode = "GET" if request.method == "HEAD" else request.method
    route = (LECTURES if methode == "GET" else ECRITURES).get(nom)
    if route is None:
        return tableau._json({"erreur": "Adresse inconnue."}, 404)
    corps = None
    if methode == "POST":
        if not tableau._origine_ok(request):
            return tableau._json({"erreur": "Requête refusée."}, 400)
        try:
            corps = await tableau._lire_json(request, route["corps_max"])
        except tableau._Refus as r:
            return tableau._json({"erreur": r.message}, r.status)
    lien = await liaison(j["emp"])
    if lien is None:
        return tableau._json({"erreur": "Accès retiré.", "etat": "expire"}, 403)
    try:
        status, rep = await route["fn"](g, g.get_member(j["u"]), dict(lien, emp=j["emp"]),
                                        corps if methode == "POST" else tableau._parametres(request))
    except Exception as ex:  # la page lit « indisponible », le détail part au journal
        _signaler("E1", "adresse du questionnaire en ligne en échec", ex, nom)
        return tableau._json({"erreur": "Indisponible pour le moment."}, 500)
    return tableau._json(rep, status)


api_post = api   # le même, pour la route POST (aiohttp : un nom par route)


def _cadence(lien: dict, genre: str, par_seconde: int) -> bool:
    """True si la requête passe : au plus `par_seconde` par seconde, par session et par genre."""
    t = time.monotonic()
    cle = (lien.get("emp", ""), genre)
    recents = [x for x in _seaux.get(cle, []) if t - x < 1.0]
    if len(recents) >= par_seconde:
        _seaux[cle] = recents
        return False
    _seaux[cle] = recents + [t]
    if len(_seaux) > 5000:
        for k in [k for k, x in _seaux.items() if not x or t - x[-1] > 5][:2500]:
            _seaux.pop(k, None)
    return True


_REFUS = {"envoye": "Tes réponses sont déjà envoyées.", "attente": "Cette étape est déjà envoyée : la direction la regarde.",
          "remplace": "Ce questionnaire a été remplacé.", "ferme": "Ta candidature est terminée.",
          "inconnu": "Ce questionnaire n'existe plus."}


def _refus_etat(ctx: dict) -> tuple:
    return 409, {"erreur": _REFUS.get(ctx["etat"], "Ta candidature est terminée."), "etat": ctx["etat"],
                 "portes": _portes_publiques(ctx)}


def _portes_publiques(ctx: dict) -> dict | None:
    p = ctx.get("portes")
    return None if not p else {k: p[k] for k in ("mode", "ouverte", "envoyee", "fiche", "total", "courante")}


def _textes_recus(corps: dict, ctx: dict, *, final: bool) -> dict:
    """{rang: texte} reçus de la page : des questions que le candidat peut écrire MAINTENANT (une étape pas encore ouverte,
    ou déjà envoyée, est refusée), des textes bornés. `final` : la normalisation des réponses (celle du formulaire
    Discord). Lève ValueError (le message part tel quel vers la page)."""
    brut = corps.get("reponses")
    if not isinstance(brut, dict) or len(brut) > questionnaire.PAR_ENVOI:
        raise ValueError("« reponses » : un objet {rang: texte}.")
    permis, out = rangs_modifiables(ctx), {}
    for k, v in brut.items():
        rang = _entier(k)
        if rang is None or rang not in permis:
            raise ValueError("Une réponse vise une question qui n'est pas ouverte.")
        if not isinstance(v, str):
            raise ValueError("Chaque réponse est un texte.")
        out[rang] = (questionnaire._net(v, lignes=True)[:questionnaire.REPONSE_CANDIDAT_MAX] if final
                     else _texte_net(v, questionnaire.REPONSE_CANDIDAT_MAX, lignes=True))
    return out


def _etapes_visibles(ctx: dict) -> list:
    """Ce que le candidat voit : toutes les étapes (un envoi d'avant), sinon les étapes OUVERTES seulement — les suivantes
    ne sont que comptées (`portes.total`). Chacune dit sa place (`position`), si elle est envoyée, si elle est à remplir."""
    p = ctx["portes"]
    out = []
    for k, x in enumerate(ctx["etapes"]):
        if p["mode"] == "etapes" and x["numero"] > p["ouverte"]:
            continue
        out.append(dict(x, position=k + 1, envoyee=p["mode"] == "etapes" and x["numero"] <= p["envoyee"],
                        courante=p["mode"] == "etapes" and x["numero"] == p["courante"]))
    return out


async def _finir_si_tout_envoye(g, ctx: dict) -> dict:
    """La dernière étape envoyée mais l'envoi pas clos (une coupure entre les deux) : il se clôt maintenant (`clore_envoi`
    et `annoncer_reponses`, une seule fois)."""
    p, e = ctx["portes"], ctx["envoi"]
    if ctx["etat"] != "attente" or p["mode"] != "etapes" or p["envoyee"] < p["derniere"]:
        return ctx
    t = int(time.time())
    if await questionnaire.clore_envoi(e, t):
        try:
            await questionnaire.annoncer_reponses(g, e, t)
        except Exception as ex:   # les réponses sont gardées ; seules les cartes ou le journal manquent — dit au journal
            _signaler("E4", "annonce des réponses du questionnaire en ligne en échec", ex, f"envoi={e['id']}")
    return await contexte(g, int(e["id"]), int(e["candidat_id"]))


async def _lecture_questionnaire(g, membre, lien: dict, requete: dict):
    """`GET questionnaire` : où en est SON questionnaire, ses étapes ouvertes et leurs questions, les liens, ses réponses
    (brouillons compris), les textes de la page. Fermé ou remplacé : l'état et les textes seulement."""
    ctx = await _finir_si_tout_envoye(g, await contexte(g, lien["envoi"], lien["candidat"]))
    _contextes[lien["envoi"]] = (time.monotonic(), ctx)
    e = ctx["envoi"]
    out = {"etat": ctx["etat"], "textes": textes_page(g), "version": tableau.version_page(), "expire": lien["expire"],
           "moi": {"nom": getattr(membre, "display_name", "") or ""},
           "serveur": {"nom": getattr(g, "name", "") or "",
                       "icone": str(g.icon.with_size(128).url) if getattr(g, "icon", None) else ""},
           "limite": questionnaire.REPONSE_CANDIDAT_MAX, "nature": "chef" if ctx["chef"] else "recrutement",
           "metier": await nom_metier(e["metier"]) if e is not None and ctx["chef"] else ""}
    if ctx["etat"] in ("ouvert", "attente", "envoye"):
        visibles = _etapes_visibles(ctx)
        rangs = {q["rang"] for x in visibles for q in x["questions"]}
        reponses = await _reponses(e, avec_brouillons=ctx["etat"] == "ouvert")
        etat_page = await _lire("SELECT etape FROM candidature_etat WHERE envoi_id=?", (int(e["id"]),))
        out.update(envoi=int(e["id"]), etapes=visibles, portes=_portes_publiques(ctx), liens=_liens_publics(e["liens"]),
                   reponses={str(r): t for r, (t, _q) in sorted(reponses.items()) if r in rangs},
                   envoye_le=int(e["repondu_le"] or 0) if ctx["etat"] == "envoye" else 0,
                   etape=int(etat_page[0][0]) if etat_page else 1)
        await _vu(g, lien, ctx)
    return 200, out


async def _ecriture_saisie(g, membre, lien: dict, corps: dict):
    """`POST saisie` {rang, texte, etape?} : ce que le candidat tape, pour le direct — rien d'écrit en base (le brouillon
    a son adresse). Au-delà de six par seconde : laissée de côté (la suivante porte le texte entier)."""
    ctx = await _contexte_frais(g, lien)
    if ctx["etat"] != "ouvert":
        return _refus_etat(ctx)
    rang = _entier(corps.get("rang"))
    if rang is None or rang not in rangs_modifiables(ctx) or not isinstance(corps.get("texte"), str):
        return 400, {"erreur": "Cette question n'est pas ouverte."}
    if not _cadence(lien, "saisie", SAISIES_PAR_S):
        return 200, {"ok": True, "laisse": True}
    texte = _texte_net(corps["texte"], questionnaire.REPONSE_CANDIDAT_MAX, lignes=True)
    v = await _vu(g, lien, ctx, etape=_entier(corps.get("etape")), rang=rang)
    t = int(time.time())
    if v["textes"].get(rang) != texte:
        v["textes"][rang], v["ecrits"][rang], v["ecrit"] = texte, t, t
        _pousser(g.id, v, {"rep": {str(rang): texte}, "ec": {str(rang): t}, "r": rang})
    return 200, {"ok": True}


async def _ecriture_brouillon(g, membre, lien: dict, corps: dict):
    """`POST brouillon` {reponses: {rang: texte}, etape?, rang?} : le brouillon gardé (un texte vide l'efface), pour les
    questions ouvertes seulement. Jamais une réponse : `recrutement_reponses` n'est écrit qu'à l'envoi."""
    if not _cadence(lien, "brouillon", BROUILLONS_PAR_S):
        return 429, {"erreur": "Trop d'enregistrements d'un coup : un instant."}
    ctx = await contexte(g, lien["envoi"], lien["candidat"])
    _contextes[lien["envoi"]] = (time.monotonic(), ctx)
    if ctx["etat"] != "ouvert":
        return _refus_etat(ctx)
    e = ctx["envoi"]
    try:
        recus = _textes_recus(corps, ctx, final=False)
    except ValueError as ex:
        return 400, {"erreur": str(ex)}
    t = int(time.time())
    async with _get_db() as db:
        for rang, texte in recus.items():
            if texte:
                await db.execute("INSERT OR REPLACE INTO candidature_brouillons (envoi_id, rang, guild_id, candidat_id,"
                                 " texte, maj_le) VALUES (?,?,?,?,?,?)",
                                 (int(e["id"]), rang, g.id, int(lien["candidat"]), texte, t))
            else:
                await db.execute("DELETE FROM candidature_brouillons WHERE envoi_id=? AND rang=?", (int(e["id"]), rang))
        await db.commit()
    v = await _vu(g, lien, ctx, etape=_entier(corps.get("etape")), rang=_entier(corps.get("rang")))
    change = {r: x for r, x in recus.items() if v["textes"].get(r) != x}
    for r, x in change.items():
        v["textes"][r], v["ecrits"][r], v["ecrit"] = x, t, t
    if change:
        _pousser(g.id, v, {"rep": {str(r): x for r, x in change.items()}, "ec": {str(r): t for r in change}})
    return 200, {"ok": True, "enregistre_le": t, "n": len(recus)}


async def _ecriture_presence(g, membre, lien: dict, corps: dict):
    """`POST presence` {vue: ouverte | cachee | fermee, etape?, rang?} : le battement de la page (toutes les 20 s), et ce
    qu'elle devient (cachée, fermée). La réponse dit où en est le questionnaire : la page relit quand la direction ouvre
    l'étape suivante, ou quand la candidature se termine. La fermeture est gardée tout de suite."""
    vue = corps.get("vue")
    if vue not in VUES:
        return 400, {"erreur": "Présence invalide."}
    if vue != "fermee" and not _cadence(lien, "presence", 2):
        return 200, {"ok": True, "laisse": True}
    ctx = await _contexte_frais(g, lien)
    if ctx["envoi"] is None:
        return _refus_etat(ctx)
    await _vu(g, lien, ctx, vue=vue, etape=_entier(corps.get("etape")), rang=_entier(corps.get("rang")),
              persister=vue == "fermee")
    return 200, {"ok": True, "etat": ctx["etat"], "portes": _portes_publiques(ctx)}


def _manquent(recus: dict, attendus: set) -> list:
    return sorted(r for r in attendus if not recus.get(r))


async def _apres_envoi(g, lien: dict, e: dict, recus: dict, t: int) -> dict:
    """Les brouillons envoyés partent ; le direct dit l'étape envoyée (ou l'envoi entier)."""
    async with _get_db() as db:
        for rang in recus:
            await db.execute("DELETE FROM candidature_brouillons WHERE envoi_id=? AND rang=?", (int(e["id"]), int(rang)))
        await db.commit()
    _contextes.pop(lien["envoi"], None)
    ctx = await contexte(g, int(e["id"]), int(e["candidat_id"]))
    v = _vivant(g.id, e["id"], int(e["ticket_id"] or 0))
    for r, x in recus.items():
        v["textes"][r], v["ecrits"][r] = x, t
    _pousser(g.id, v, {"etat": ctx["etat"], "po": _portes_direct(ctx), "envoye": t,
                       "rep": {str(r): x for r, x in recus.items()}})
    return ctx


async def _ecriture_envoyer(g, membre, lien: dict, corps: dict):
    """`POST envoyer` {reponses: {rang: texte}} — un envoi d'avant (`etape_ouverte` = 0) : TOUTES les réponses, d'un coup,
    dans les mêmes tables et états que le formulaire Discord (`questionnaire.envoyer_tout` : `clore_envoi`, une seule
    fois, puis les cartes du ticket, l'historique et le journal, `annoncer_reponses`), le direct ; les brouillons
    partent."""
    if not _cadence(lien, "envoyer", 2):
        return 429, {"erreur": "Un instant : l'envoi est déjà en route."}
    ctx = await contexte(g, lien["envoi"], lien["candidat"])
    if ctx["etat"] != "ouvert":
        return _refus_etat(ctx)
    if ctx["portes"]["mode"] != "unique":
        return 409, {"erreur": "Ce questionnaire s'envoie étape par étape.", "etat": ctx["etat"],
                     "portes": _portes_publiques(ctx)}
    e = ctx["envoi"]
    try:
        recus = _textes_recus(corps, ctx, final=True)
    except ValueError as ex:
        return 400, {"erreur": str(ex)}
    manquent = _manquent(recus, rangs_modifiables(ctx))
    if manquent:
        return 400, {"erreur": _t(g, "candidature.manque", n=len(manquent)), "manquent": manquent}
    t = int(time.time())
    try:
        premier = await questionnaire.envoyer_tout(e, t, recus, g=g)
    except Exception as ex:   # les réponses sont peut-être gardées (le ticket a échoué) : relues ci-dessous
        _signaler("E4", "envoi du questionnaire en ligne en échec", ex, f"envoi={e['id']}")
        premier = False
    if not premier:   # le formulaire Discord, ou un autre onglet, est passé avant : la page relit où elle en est
        ctx = await contexte(g, lien["envoi"], lien["candidat"])
        if ctx["etat"] == "ouvert":
            return 409, {"erreur": "Tes réponses n'ont pas pu être envoyées : recharge la page.", "etat": ctx["etat"],
                         "portes": _portes_publiques(ctx)}
        return _refus_etat(ctx)
    ctx = await _apres_envoi(g, lien, e, recus, t)
    return 200, {"ok": True, "etat": ctx["etat"], "envoye_le": t}


async def _ecriture_envoyer_etape(g, membre, lien: dict, corps: dict):
    """`POST envoyer_etape` {etape, reponses: {rang: texte}} — le passage d'étape : CETTE étape (l'étape ouverte, pas
    encore envoyée ; un autre numéro est refusé), toutes ses questions remplies, et rien d'autre. Écrite par
    `questionnaire.envoyer_etape` (une seule fois) : la dernière clôt l'envoi, une autre attend la direction."""
    if not _cadence(lien, "envoyer", 2):
        return 429, {"erreur": "Un instant : l'envoi est déjà en route."}
    ctx = await contexte(g, lien["envoi"], lien["candidat"])
    if ctx["etat"] != "ouvert":
        return _refus_etat(ctx)
    p = ctx["portes"]
    if p["mode"] != "etapes":
        return 409, {"erreur": "Ce questionnaire s'envoie en une fois.", "etat": ctx["etat"], "portes": _portes_publiques(ctx)}
    numero = _entier(corps.get("etape"))
    if numero is None or numero != p["courante"]:
        return 409, {"erreur": "Cette étape n'est pas ouverte.", "etat": ctx["etat"], "portes": _portes_publiques(ctx)}
    e = ctx["envoi"]
    try:
        recus = _textes_recus(corps, ctx, final=True)
    except ValueError as ex:
        return 400, {"erreur": str(ex)}
    manquent = _manquent(recus, _rangs_etape(ctx, numero))
    if manquent:
        return 400, {"erreur": _t(g, "candidature.manque", n=len(manquent)), "manquent": manquent}
    t = int(time.time())
    try:
        premier = await questionnaire.envoyer_etape(e, t, numero, recus, g=g)
    except Exception as ex:   # l'étape est peut-être gardée (le message du ticket a échoué) : relue ci-dessous
        _signaler("E9", "envoi d'une étape en échec", ex, f"envoi={e['id']} etape={numero}")
        premier = False
    if not premier:   # un double envoi (deux onglets, deux clics) : rien n'est réécrit, et la page relit où elle en est
        ctx = await contexte(g, lien["envoi"], lien["candidat"])
        if ctx["etat"] == "ouvert":
            return 409, {"erreur": "Cette étape n'a pas pu être envoyée : recharge la page.", "etat": ctx["etat"],
                         "portes": _portes_publiques(ctx)}
        return _refus_etat(ctx)
    ctx = await _apres_envoi(g, lien, e, recus, t)
    return 200, {"ok": True, "etat": ctx["etat"], "portes": _portes_publiques(ctx), "envoye_le": t}


LECTURES = {"questionnaire": {"fn": _lecture_questionnaire}}
ECRITURES = {"saisie": {"fn": _ecriture_saisie, "corps_max": CORPS_SAISIE},
             "brouillon": {"fn": _ecriture_brouillon, "corps_max": CORPS_REPONSES},
             "presence": {"fn": _ecriture_presence, "corps_max": CORPS_PRESENCE},
             "envoyer": {"fn": _ecriture_envoyer, "corps_max": CORPS_REPONSES},
             "envoyer_etape": {"fn": _ecriture_envoyer_etape, "corps_max": CORPS_REPONSES}}


# ═══════════════════════════════════════════════════════════════════════════════
#  La lecture de la direction (`/tableau/espace/api/direct/candidat`, portée « tout »)
# ═══════════════════════════════════════════════════════════════════════════════

async def etat_direct(g, ticket: int = 0, envoi: int = 0) -> dict | None:
    """Tout ce que le direct montre d'un questionnaire (par ENVOI ; un ticket désigne son questionnaire en cours) : toutes
    ses étapes et leurs questions (ouvertes, envoyées, à venir), ce que le candidat a écrit (réponses envoyées, brouillons
    et texte en cours), sa page (ouverte, cachée, fermée, jamais), son étape, sa question."""
    if not envoi and ticket:
        s = await questionnaire._suivi(g.id, int(ticket))
        envoi = int(s["envoi_id"]) if s and s["envoi_id"] else 0
    if not envoi:
        return None
    ctx = await contexte(g, int(envoi))
    e = ctx["envoi"]
    if e is None:
        return None
    reponses = await _reponses(e, avec_brouillons=ctx["etat"] == "ouvert")
    textes_ = {r: x for r, (x, _q) in reponses.items()}
    ecrits = {r: q for r, (_x, q) in reponses.items()}
    page_ = await _lire("SELECT ouvert_le, vu_le, etape, rang FROM candidature_etat WHERE envoi_id=?", (int(e["id"]),))
    ouvert_le, vu, etape, rang = (tuple(int(x or 0) for x in page_[0]) if page_ else (0, 0, 0, 0))
    vue, ecrit = ("fermee" if vu else ""), max(ecrits.values(), default=0)
    v = _direct.get((g.id, int(e["id"])))
    if v is not None:
        modifiables = rangs_modifiables(ctx)
        for r, x in v["textes"].items():
            if r in modifiables and v["ecrits"].get(r, 0) >= ecrits.get(r, 0):
                textes_[r], ecrits[r] = x, v["ecrits"][r]
        vu, vue = max(vu, v["vu"]), v["vue"] or vue
        etape, rang, ecrit = v["etape"] or etape, v["rang"] or rang, max(ecrit, v["ecrit"])
    p = ctx["portes"]
    etapes = [dict(x, position=k + 1, ouverte=p["mode"] == "unique" or x["numero"] <= p["ouverte"],
                   envoyee=p["mode"] == "etapes" and x["numero"] <= p["envoyee"],
                   courante=x["numero"] == p["courante"]) for k, x in enumerate(ctx["etapes"])]
    return {"ticket": int(e["ticket_id"] or 0), "envoi": int(e["id"]), "etat": ctx["etat"], "chef": ctx["chef"],
            "metier": await nom_metier(e["metier"]) if ctx["chef"] else "", "etapes": etapes,
            "portes": _portes_publiques(ctx), "reponses": {str(r): x for r, x in sorted(textes_.items()) if x},
            "ecrits": {str(r): q for r, q in sorted(ecrits.items()) if q and textes_.get(r)},
            "page": {"vue": vue or "jamais", "vu": vu, "ouvert_le": ouvert_le}, "etape": etape, "rang": rang,
            "ecrit": ecrit, "envoye_le": int(e["repondu_le"] or 0) if ctx["etat"] == "envoye" else 0,
            "pose_le": int(e["envoye_le"] or 0), "s": int(time.time())}


async def _route_direct_candidat(g, auteur, requete, corps):
    """`GET api/direct/candidat?envoi=<n>` (ou `?ticket=<n>`) : l'état complet du direct d'un questionnaire (sans
    WebSocket, la page l'interroge toutes les quelques secondes ; avec, une fois, puis les messages « candidat »)."""
    brut_e, brut_t = str((requete or {}).get("envoi", "")), str((requete or {}).get("ticket", ""))
    if not (brut_e.isdigit() and len(brut_e) <= 12) and not (brut_t.isdigit() and len(brut_t) <= 12):
        return 400, {"erreur": "Envoi ou ticket invalide."}
    d = await etat_direct(g, ticket=int(brut_t) if brut_t.isdigit() else 0, envoi=int(brut_e) if brut_e.isdigit() else 0)
    if d is None and brut_t.isdigit() and not brut_e.isdigit():
        #  Un ticket encore sans questionnaire (sa demande attend la direction) : un état, pas une erreur — la vue le dit
        #  et se branche dès que le questionnaire part.
        return 200, {"ticket": int(brut_t), "envoi": 0, "etat": "aucun", "s": int(time.time())}
    return (200, d) if d is not None else (404, {"erreur": "Aucun questionnaire ici."})


ROUTES_SITE = {"direct/candidat": {"methode": "GET", "fn": _route_direct_candidat, "corps_max": 0}}


#  Les points d'appel du recrutement, `lien_candidat` et `inviter` : présents seulement quand le recrutement a reçu
#  CETTE page (`questionnaire.setup(web=…)`, comme `_activite_boot`) et qu'elle peut servir. `questionnaire._web()`
#  trouve aussi un module par son nom (un `import`) : la page n'est pas branchée pour autant — `_page_candidat()` lit
#  None, les formulaires de Discord prennent le relais (et leurs tests restent les leurs).
_POINTS_D_APPEL = {"lien_candidat": _lien_candidat, "inviter": _inviter}


def branchee() -> bool:
    """Le recrutement a reçu cette page (`questionnaire.setup(web=candidature_site)`) et elle peut servir (`joignable`)."""
    return getattr(questionnaire, "_web_module", None) is sys.modules.get(__name__) and joignable()


def __getattr__(nom: str):
    if nom in _POINTS_D_APPEL and branchee():
        return _POINTS_D_APPEL[nom]
    raise AttributeError(f"module {__name__!r} has no attribute {nom!r}")


__all__ = ["setup", "init_db", "demarrer", "lien_envoi", "lien_ticket", "joignable", "branchee", "envoyer_lien",
           "envoyer_lien_envoi", "BoutonQuestionnaire", "LECTURES", "ECRITURES", "ROUTES_SITE", "etapes_de", "portes_de", "etat_direct",
           "ouvrir_session", "autorise", "contexte"]
