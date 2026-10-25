"""questionnaire.py — le recrutement du clan en deux étapes (25/10/2026).

Le fondateur, mot pour mot : « Quand les gens postulent pour rejoindre le clan, [ils] répondent aux premiers
questionnaires. Si cela convient, la direction et/ou le fondateur acceptent les premiers choix, ou alors renvoient un
message automatique comme quoi les réponses ne sont pas bonnes et que le ticket va être clôturé… Si c'est bon, alors ils
passeront à l'étape suivante qui enverra un questionnaire automatique et ultra bien fait qui ne leur expliquera pas où ils
ont eu faux, mais nous on le verra sur le site… Pas au Discord de décider ou au site de décider. » Puis : « tu dois créer
de vraies questions sans mettre de réponse dans la question… que les réponses soient écrites par nous… pour bien que les
réponses coïncident. » Et : « il a juste à renvoyer le questionnaire que l'autre avait juste avant ».

LE DÉROULÉ
  1. Ouverture d'un ticket du clan : l'accueil dit les deux étapes, le nombre de questions de l'étape 2 et les liens où
     se trouvent toutes les réponses ; la carte de l'étape 1 suit (réservée à l'équipe de recrutement).
  2. Étape 1 : « Refuser l'étape 1 » (le message automatique, puis la fermeture par le circuit normal après un court
     délai) · « Envoyer le questionnaire » (la sélection par défaut) · « Choisir sur le site » (lien personnel).
  3. Étape 2 : la carte « Étape 2 — N questions » (les questions en entier, les liens) et « Répondre » : des formulaires
     de 5 questions, gardés page par page, repris après un redémarrage, envoyés une seule fois. À la fin : « Merci, tes
     réponses sont transmises à la direction » — jamais juste ou faux.
  4. Le site corrige : la réponse attendue, les variantes, une INDICATION de proximité (une aide, jamais une décision) ;
     le fondateur et la direction cochent « juste » ou « faux » ; l'exigence affichée est 100 %.
  5. La décision : accepter (rôle du clan, fermeture), refuser (message neutre, fermeture), renvoyer des questions.

CE QUI NE PART JAMAIS VERS DISCORD : la réponse attendue, les variantes, les sources, les extraits, les indications,
les corrections. Une question dont le texte contient sa réponse (ou une variante) n'est jamais posée.

LA BANQUE vient de `donnees_jeu/questionnaire_base.json` (la recherche sur le wiki) : on insère ce qui manque ; une
question jamais touchée sur le site suit le fichier ; une question modifiée ou retirée sur le site ne bouge plus.
Les liens (`donnees_jeu/questionnaire_liens.json`) : insérés tant que le site n'a pas réglé sa liste.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import math
import random
import re
import secrets
import sqlite3
import time
import unicodedata
from pathlib import Path

import discord

import diag
import recrutements
import visuels
from ui_v2 import LayoutView

RACINE = Path(__file__).resolve().parent
FICHIER_BANQUE = RACINE / "donnees_jeu" / "questionnaire_base.json"
FICHIER_LIENS = RACINE / "donnees_jeu" / "questionnaire_liens.json"

#  Les bornes, vérifiées ici quoi que dise la page (le site les reçoit dans `limites`).
QUESTION_MIN, QUESTION_MAX = 8, 250
REPONSE_MAX = 200
VARIANTES_MAX, VARIANTE_MAX = 12, 200
THEME_MAX, SECTION_MAX, EXTRAIT_MAX, URL_MAX = 40, 120, 600, 300
NOTE_MAX = 150
PAR_PAGE = 5              # un formulaire Discord : 5 champs au plus
PAR_ENVOI = 25            # 5 formulaires de 5
NOMBRE_DEFAUT = 10
BANQUE_MAX = 500
LIENS_MAX, LIEN_TITRE_MAX, LIEN_DESC_MAX = 10, 80, 150
MODELES_MAX, MODELE_NOM_MAX = 50, 60
REPONSE_CANDIDAT_MAX = 400
TEXTE_MESSAGE = 3800      # Discord : 4 000 caractères de texte par message Components V2 (une marge)
LIENS_BUDGET = 1400       # la place des liens dans une carte
DELAI_FERMETURE = 20.0    # s : le candidat lit le message automatique avant la fermeture
REESSAI_FERMETURE = 60.0  # s : Discord ne répondait pas, on réessaie
ESSAIS_FERMETURE = 5
REPRISE_MIN = 5.0         # s : une fermeture reprise au démarrage attend au moins ce délai (le bot finit de démarrer)
FORMULAIRE_S = 7200       # un formulaire ouvert reste valable 2 h
AVIS_S = 90.0             # un mot pour soi (refus, rappel) s'efface tout seul
PAGE_S = 840.0            # « Page 1/3 enregistrée » s'efface avant 15 min (le bouton « Répondre » reprend toujours)
RETENTION_JOURS = 365     # comme le suivi des candidatures (`gdpr.RETENTION["recrutements"]`)
EXIGENCE = 100            # % de réponses justes demandé — affiché ; la décision reste humaine
SEUIL_PROCHE = 0.75       # ressemblance (1 − distance relative) à partir de laquelle on dit « proche »

#  Les thèmes, dans l'ordre où la sélection automatique les prend à tour de rôle : le studio et les actualités (le
#  Movie 3) d'abord, comme le fondateur le demande ; un thème inconnu passe après, sous son nom.
THEMES = {"studio": "Le studio (RELL Games)", "actualites": "Actualités (Movie 3)", "movie3": "Movie 3",
          "jeu": "Le jeu (RELL Seas)", "monde": "Le monde", "races": "Races", "factions": "Factions",
          "fruits": "God Fruits", "combat": "Combat", "navires": "Navires", "boss": "Boss",
          "personnages": "Personnages", "evenements": "Événements", "clan": "Le clan (GoRP)"}
DIFFICULTES = ("facile", "moyenne", "difficile")
STATUTS_QUESTION = ("confirme", "a_verifier")
FORMAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
FORMAT_TYPE = re.compile(r"[a-z_]{1,20}")
FORMAT_URL = re.compile(r"https://[^\s<>\"'`\\]{3,}")

#  Les étapes d'un ticket de recrutement.
OUVERTES = ("etape1", "etape2", "reponses")
FINALES = ("refus_etape1", "refuse", "accepte")
#  Les états d'un envoi de questions.
EN_ATTENTE = ("envoye", "en_cours")

COULEUR_LAITON, COULEUR_MER, COULEUR_CIRE, COULEUR_VERT = 0xA8823F, 0x1F4E5A, 0x8E2A24, 0x3F6B3A

#  Les textes envoyés au candidat (FR · EN). Aucun ne dit juste ou faux.
REFUS_ETAPE1 = ("Tes réponses ne correspondent pas à ce que nous attendons : ce ticket va être clôturé. "
                "Merci d'avoir créé un ticket.\n"
                "-# Your answers don't match what we are looking for: this ticket will be closed. "
                "Thank you for opening a ticket.")
REFUS_FINAL = ("La direction a étudié ta candidature : elle n'est pas retenue. Ce ticket va être clôturé. "
               "Merci d'avoir créé un ticket.\n"
               "-# The leadership has reviewed your application: it was not accepted. This ticket will be closed. "
               "Thank you for opening a ticket.")
MERCI = ("Merci, tes réponses sont transmises à la direction.\n"
         "-# Thank you, your answers have been sent to the leadership.")
DEJA = ("Tes réponses sont déjà transmises à la direction.\n"
        "-# Your answers have already been sent to the leadership.")
SEUL_CANDIDAT = ("Seul le candidat peut répondre à ce questionnaire.\n"
                 "-# Only the applicant can answer this questionnaire.")
REMPLACE = ("Ce questionnaire n'est plus ouvert : réponds au plus récent, plus bas dans le ticket.\n"
            "-# This questionnaire is no longer open: answer the latest one, further down in the ticket.")
INTROUVABLE = "Ce questionnaire n'existe plus.\n-# This questionnaire no longer exists."
DEMARRE = "Le bot démarre : réessaie dans un instant.\n-# The bot is starting: try again in a moment."
SOUCI = "Un souci est survenu : réessaie dans quelques secondes.\n-# Something went wrong: try again in a few seconds."
RESERVE = "Réservé au fondateur, à la direction et à l'équipe de recrutement."
DISCORD_HS = "Discord ne répond pas : réessaie dans un instant."
FERME = "Ce ticket n'est plus ouvert."

_get_db = _cfg = _panneaux = _ticket_ouvert = _decider = _autorise = _lien = _journal = None
_bot = None
_log = print
_fichier_banque, _fichier_liens = FICHIER_BANQUE, FICHIER_LIENS
_semes: set = set()        # les serveurs dont la banque a été semée par ce processus
_verrous: dict = {}        # (serveur, ticket) → asyncio.Lock : une décision à la fois par ticket
_en_cours: set = set()     # les gestes en cours (double clic) : réponse immédiate « déjà en cours »
_taches: set = set()       # les tâches de fond gardées jusqu'au bout (une tâche sans référence peut être ramassée)
_fermetures: dict = {}     # (serveur, ticket) → tâche : une fermeture planifiée à la fois
_verrou_semis = None


def setup(*, get_db, cfg, panneaux, ticket_ouvert, decider, autorise, lien=None, journal=None,
          fichier_banque=None, fichier_liens=None, log=None):
    """`panneaux(c)` → les panneaux de tickets du clan ; `ticket_ouvert(g, ticket)` → (salon, ticket) ou (None, None) ;
    `decider(g, ticket, auteur, accepte, motif)` → (ok, message) — le circuit de décision du bot (rôle, fermeture,
    transcript, suivi) ; `autorise(i)` → peut trancher l'étape 1 ; `lien(i)` → (lien personnel du site, refus) ;
    `journal(g, type_, texte, membre_id=, auteur_id=)` → le journal du site."""
    global _get_db, _cfg, _panneaux, _ticket_ouvert, _decider, _autorise, _lien, _journal, _log
    global _fichier_banque, _fichier_liens, _verrou_semis
    _get_db, _cfg, _panneaux, _ticket_ouvert = get_db, cfg, panneaux, ticket_ouvert
    _decider, _autorise, _lien, _journal = decider, autorise, lien, journal
    _fichier_banque = Path(fichier_banque) if fichier_banque else FICHIER_BANQUE
    _fichier_liens = Path(fichier_liens) if fichier_liens else FICHIER_LIENS
    _log = log or print
    for t in list(_fermetures.values()):
        if not t.done():
            t.cancel()
    for d in (_semes, _verrous, _en_cours, _fermetures):
        d.clear()
    _verrou_semis = None


def pret() -> bool:
    return _get_db is not None


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS recrutement_questions (guild_id INTEGER NOT NULL, id TEXT NOT NULL,"
    " theme TEXT NOT NULL DEFAULT '', question TEXT NOT NULL, reponse TEXT NOT NULL,"
    " variantes TEXT NOT NULL DEFAULT '[]', type TEXT NOT NULL DEFAULT 'texte',"
    " difficulte TEXT NOT NULL DEFAULT 'moyenne', source TEXT NOT NULL DEFAULT '', section TEXT NOT NULL DEFAULT '',"
    " extrait TEXT NOT NULL DEFAULT '', statut TEXT NOT NULL DEFAULT 'a_verifier', actif INTEGER NOT NULL DEFAULT 1,"
    " retiree INTEGER NOT NULL DEFAULT 0, ordre INTEGER NOT NULL DEFAULT 0, origine TEXT NOT NULL DEFAULT 'site',"
    " modifiee INTEGER NOT NULL DEFAULT 0, empreinte TEXT NOT NULL DEFAULT '', cree_le INTEGER NOT NULL DEFAULT 0,"
    " cree_par INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0,"
    " version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (guild_id, id))",
    "CREATE TABLE IF NOT EXISTS recrutement_liens (guild_id INTEGER NOT NULL, id TEXT NOT NULL, titre TEXT NOT NULL,"
    " url TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', ordre INTEGER NOT NULL DEFAULT 0,"
    " PRIMARY KEY (guild_id, id))",
    "CREATE TABLE IF NOT EXISTS recrutement_reglages (guild_id INTEGER PRIMARY KEY,"
    " nombre INTEGER NOT NULL DEFAULT 10, version INTEGER NOT NULL DEFAULT 1, liens_version INTEGER NOT NULL DEFAULT 1,"
    " liens_modifies INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS recrutement_modeles (guild_id INTEGER NOT NULL, id TEXT NOT NULL, nom TEXT NOT NULL,"
    " questions TEXT NOT NULL DEFAULT '[]', par_defaut INTEGER NOT NULL DEFAULT 0, cree_le INTEGER NOT NULL DEFAULT 0,"
    " cree_par INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0,"
    " version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (guild_id, id))",
    "CREATE TABLE IF NOT EXISTS recrutement_suivi (guild_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL,"
    " candidat_id INTEGER NOT NULL, salon_id INTEGER NOT NULL DEFAULT 0, carte_id INTEGER NOT NULL DEFAULT 0,"
    " etape TEXT NOT NULL DEFAULT 'etape1', annonce INTEGER NOT NULL DEFAULT 0, envoi_id INTEGER NOT NULL DEFAULT 0,"
    " fermeture_le INTEGER NOT NULL DEFAULT 0, fermeture_par INTEGER NOT NULL DEFAULT 0,"
    " fermeture_motif TEXT NOT NULL DEFAULT '', decide_par INTEGER NOT NULL DEFAULT 0,"
    " decide_le INTEGER NOT NULL DEFAULT 0, cree_le INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0,"
    " PRIMARY KEY (guild_id, ticket_id))",
    "CREATE TABLE IF NOT EXISTS recrutement_envois (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
    " ticket_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL, questions TEXT NOT NULL, liens TEXT NOT NULL DEFAULT '[]',"
    " statut TEXT NOT NULL DEFAULT 'prepare', origine TEXT NOT NULL DEFAULT '', renvoi INTEGER NOT NULL DEFAULT 0, envoye_par INTEGER NOT NULL DEFAULT 0,"
    " cree_le INTEGER NOT NULL DEFAULT 0, envoye_le INTEGER NOT NULL DEFAULT 0, repondu_le INTEGER NOT NULL DEFAULT 0,"
    " salon_id INTEGER NOT NULL DEFAULT 0, messages TEXT NOT NULL DEFAULT '[]')",
    "CREATE INDEX IF NOT EXISTS idx_recrutement_envois_ticket ON recrutement_envois(guild_id, ticket_id)",
    "CREATE TABLE IF NOT EXISTS recrutement_reponses (envoi_id INTEGER NOT NULL, rang INTEGER NOT NULL,"
    " guild_id INTEGER NOT NULL DEFAULT 0, candidat_id INTEGER NOT NULL DEFAULT 0, texte TEXT NOT NULL,"
    " recu_le INTEGER NOT NULL, PRIMARY KEY (envoi_id, rang))",
    "CREATE TABLE IF NOT EXISTS recrutement_corrections (envoi_id INTEGER NOT NULL, rang INTEGER NOT NULL, juste INTEGER,"
    " par INTEGER NOT NULL DEFAULT 0, le INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,"
    " PRIMARY KEY (envoi_id, rang))",
    "CREATE TABLE IF NOT EXISTS recrutement_historique (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " guild_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, quand INTEGER NOT NULL, quoi TEXT NOT NULL,"
    " par INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_recrutement_historique ON recrutement_historique(guild_id, ticket_id)",
)


async def init_db():
    async with _get_db() as db:
        for sql in _SCHEMA:
            await db.execute(sql)
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Le texte comparé : normalisation, distance, indication de proximité, fuite
# ═══════════════════════════════════════════════════════════════════════════════

_ARTICLES = frozenset({"le", "la", "les", "un", "une", "des", "du", "de", "au", "aux", "the", "an"})
_LIAISONS = frozenset({"et", "and", "ou", "or"})     # dans une liste : « A, B et C » = « C, A, B »
_NOMBRES = {"zero": "0", "deux": "2", "trois": "3", "quatre": "4", "cinq": "5", "six": "6", "sept": "7",
            "huit": "8", "neuf": "9", "dix": "10", "onze": "11", "douze": "12", "treize": "13", "quatorze": "14",
            "quinze": "15", "seize": "16", "vingt": "20", "one": "1", "two": "2", "three": "3", "four": "4",
            "five": "5", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
            "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
            "eighteen": "18", "nineteen": "19", "twenty": "20"}
_RANG_NIVEAU = {"different": 0, "proche": 1, "identique": 2}


@functools.lru_cache(maxsize=16384)
def _normaliser(texte: str) -> str:
    """Le texte comparé : sans casse ni accents ni ponctuation, espaces écrasés, sans articles (le, la, les, un,
    une, des, du, de, au, aux, the, an) ni élisions (l', d', qu'…) ; « 1 000 » = « 1000 » ; les petits nombres
    écrits en lettres (« trois », « three ») deviennent des chiffres. Une lettre seule reste (« rang D » n'est pas
    « rang ») ; une réponse faite seulement d'articles les garde (« un » = 1)."""
    t = unicodedata.normalize("NFKD", str(texte or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = t.replace("œ", "oe").replace("æ", "ae").replace("’", "'")
    t = re.sub(r"\b(?:qu|[ldjmnst])'", " ", t)
    t = re.sub(r"(?<=\d)[\s.,'’_](?=\d{3}(?!\d))", "", t)
    t = re.sub(r"dix[\s-]+(sept|huit|neuf)", lambda m: {"sept": "17", "huit": "18", "neuf": "19"}[m.group(1)], t)
    mots = [m for m in re.split(r"[\W_]+", t) if m]
    gardes = [m for m in mots if m not in _ARTICLES] or [{"un": "1", "une": "1"}.get(m, m) for m in mots]
    return " ".join(_NOMBRES.get(m, m) for m in gardes)


def normaliser(texte) -> str:
    """`_normaliser`, gardé en mémoire : les mêmes questions et réponses reviennent à chaque sélection."""
    return _normaliser(str(texte or ""))


def distance(a: str, b: str) -> int:
    """La distance d'édition (insertion, suppression, substitution, deux lettres inversées = 1)."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    avant, prec = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cour = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            v = min(prec[j] + 1, cour[j - 1] + 1, prec[j - 1] + (ca != cb))
            if avant is not None and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                v = min(v, avant[j - 2] + 1)
            cour[j] = v
        avant, prec = prec, cour
    return prec[-1]


def _ressemblance(a: str, b: str) -> float:
    """1 − la distance relative ; 0 quand les longueurs à elles seules l'empêchent d'atteindre « proche » (on ne
    calcule pas pour rien) ou quand le texte est trop long pour une comparaison lettre à lettre."""
    m = max(len(a), len(b))
    if not m:
        return 1.0
    if abs(len(a) - len(b)) > (1 - SEUIL_PROCHE) * m or m > 200:
        return 0.0
    return 1 - distance(a, b) / m


def _mot_proche(mot: str, mots: list) -> bool:
    if mot in mots:
        return True
    if len(mot) < 4:
        return False
    return any(abs(len(mot) - len(m)) <= 2 and distance(mot, m) <= (1 - SEUIL_PROCHE) * max(len(mot), len(m))
               for m in mots)


def _comparer(cand: str, att: str, nombre: bool, liste: bool = False) -> tuple:
    if cand == att or cand.replace(" ", "") == att.replace(" ", ""):
        return "identique", 1.0, "même réponse"
    mots_c, mots_a = cand.split()[:80], att.split()
    if nombre:
        if f" {att} " in f" {cand} ":
            return "proche", 0.9, "contient le nombre attendu"
        return "different", 0.0, "nombre différent"
    #  Un nombre ou une lettre seule se recopie exactement : « Movie 1 » n'est pas une faute de frappe de « Movie 3 »,
    #  ni « rang B » de « rang A », ni « 25 octobre » de « 24 octobre ».
    manquent = {m for m in mots_a if len(m) == 1 or m.isdigit()} - set(mots_c)
    if manquent:
        return "different", 0.0, "un nombre ou une lettre diffère"
    ens_c, ens_a = set(mots_c) - _LIAISONS, set(mots_a) - _LIAISONS
    if ens_a and ens_c == ens_a:
        return ("identique", 1.0, "mêmes éléments") if liste else ("proche", 0.9, "mêmes mots, dans un autre ordre")
    s = max(_ressemblance(cand, att), _ressemblance(cand.replace(" ", ""), att.replace(" ", "")))
    if s >= SEUIL_PROCHE:
        return "proche", s, "faute de frappe ou d'accord"
    utiles = [m for m in mots_a if m not in _LIAISONS] or mots_a
    trouves = sum(1 for m in utiles if _mot_proche(m, mots_c))
    if trouves == len(utiles):
        return "proche", max(s, SEUIL_PROCHE), ("contient tous les éléments attendus" if liste
                                                else "contient la réponse attendue")
    if trouves:
        return "different", max(s, round(0.7 * trouves / len(utiles), 2)), f"en partie : {trouves} mot(s) sur {len(utiles)}"
    return "different", s, "pas assez proche" if s >= 0.5 else "aucune ressemblance"


@functools.lru_cache(maxsize=4096)
def _indication(reponse: str, attendue: str, variantes: tuple, type_: str) -> tuple:
    cand = normaliser(reponse)[:300]
    if not cand:
        return ("different", 0.0, "reponse", "", "réponse vide")
    meilleur = None
    for k, cible in enumerate((attendue, *variantes)):
        att = normaliser(cible)[:200]
        if not att:
            continue
        niveau, score, detail = _comparer(cand, att, type_ == "nombre" or att.replace(" ", "").isdigit(),
                                          type_ == "liste")
        cle = (_RANG_NIVEAU[niveau], score, -k)
        if meilleur is None or cle > meilleur[0]:
            meilleur = (cle, niveau, score, detail, k, str(cible))
    if meilleur is None:
        return ("different", 0.0, "reponse", "", "aucune réponse attendue")
    _cle, niveau, score, detail, k, cible = meilleur
    return (niveau, round(float(score), 2), "reponse" if k == 0 else "variante", "" if k == 0 else cible, detail)


def indication(reponse_candidat, attendue, variantes=(), type_: str = "texte") -> dict:
    """UNE AIDE pour le correcteur, jamais une décision : « identique » (même texte une fois normalisé),
    « proche » (une faute de frappe, un accord, ou la réponse attendue contenue dans une phrase), « different ».
    Comparée à la réponse attendue ET à chaque variante ; la meilleure l'emporte (`avec`, `variante`)."""
    niveau, score, avec, variante, detail = _indication(str(reponse_candidat or ""), str(attendue or ""),
                                                        tuple(str(v) for v in variantes or ()), str(type_ or ""))
    return {"niveau": niveau, "score": score, "avec": avec, "variante": variante, "detail": detail}


def fuite(question, reponse, variantes=()) -> str:
    """La réponse (ou la variante) que le texte de la question dévoile, sinon "". Comparaison par mots entiers une
    fois normalisés ; un seul chiffre ou moins de trois lettres ne compte pas (« Movie 3 » n'est pas une fuite de
    la réponse « 3 »)."""
    q = f" {normaliser(question)} "
    for cible in (reponse, *(variantes or ())):
        c = normaliser(cible)
        compact = c.replace(" ", "")
        if not c or len(compact) < (2 if compact.isdigit() else 3):
            continue
        if f" {c} " in q:
            return str(cible)
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Petits outils : textes, validation, base
# ═══════════════════════════════════════════════════════════════════════════════

class _Invalide(Exception):
    """Un champ refusé : le message part tel quel vers la page (400)."""


def _maintenant() -> int:
    return int(time.time())


def _net(texte, lignes: bool = False) -> str:
    """Sans caractères de contrôle ; les espaces écrasés (les retours à la ligne gardés si `lignes`)."""
    t = str(texte or "")
    if lignes:
        t = re.sub(r"[^\S\n]+", " ", re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", " ", t))
        return re.sub(r"\n{3,}", "\n\n", t).strip()
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", t)).strip()


def _cle(texte) -> str:
    t = unicodedata.normalize("NFKD", str(texte or ""))
    return re.sub(r"[\W_]+", "_", "".join(c for c in t if not unicodedata.combining(c)).casefold()).strip("_")


def extrait(texte, n: int) -> str:
    t = _net(texte)
    if len(t) <= n:
        return t
    coupe = t[:n - 1]
    if " " in coupe[n // 2:]:
        coupe = coupe[:coupe.rindex(" ")]
    return coupe.rstrip(" ,;:.") + "…"


def _md(texte) -> str:
    """Un texte écrit sur le site, affiché tel quel dans Discord : ni mise en forme, ni mention."""
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(texte or "")))


def _theme(texte) -> str:
    c = _cle(texte)
    for cle, mots in (("studio", ("studio", "rell_games", "rellgames")), ("movie3", ("movie3", "movie_3", "film_3")),
                      ("jeu", ("jeu", "rell_seas", "rellseas", "game")), ("clan", ("clan", "gorp"))):
        if c == cle or c in mots:
            return cle
    return c[:THEME_MAX] or "jeu"


def _difficulte(valeur) -> str:
    c = _cle(valeur)
    if c in ("1", "facile", "easy", "simple"):
        return "facile"
    if c in ("3", "difficile", "hard", "dur", "expert"):
        return "difficile"
    return "moyenne"


def _type(valeur) -> str:
    c = _cle(valeur)
    if c in ("nombre", "number", "nombre_entier", "chiffre", "numerique", "annee", "date_annee"):
        return "nombre"
    return c if FORMAT_TYPE.fullmatch(c or "") else "texte"


def _url(valeur) -> str:
    u = str(valeur or "").strip()
    return u if len(u) <= URL_MAX and FORMAT_URL.fullmatch(u) else ""


def _variantes(brut, reponse: str) -> list:
    """Les variantes admises, telles qu'écrites : des textes, sans doublon ni la réponse elle-même (à la casse
    près). « sept » à côté de « 7 » reste : la personne qui corrige voit ce qu'elle a écrit."""
    if brut is None:
        return []
    if isinstance(brut, str):
        brut = [x for x in re.split(r"[|;\n]", brut)]
    if not isinstance(brut, list):
        raise _Invalide("« variantes » doit être une liste de textes.")
    vues, out = {_net(reponse).casefold()}, []
    for v in brut:
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            raise _Invalide("« variantes » doit être une liste de textes.")
        t = _net(v)
        if not t:
            continue
        if len(t) > VARIANTE_MAX:
            raise _Invalide(f"Une variante fait {VARIANTE_MAX} caractères au plus.")
        if t.casefold() not in vues:
            vues.add(t.casefold())
            out.append(t)
    if len(out) > VARIANTES_MAX:
        raise _Invalide(f"{VARIANTES_MAX} variantes au plus.")
    return out


def _json_liste(texte) -> list:
    try:
        x = json.loads(texte or "[]")
    except (TypeError, ValueError):
        return []
    return x if isinstance(x, list) else []


def _texte(corps: dict, cle: str, *, mini: int = 0, maxi: int, requis: bool = True, lignes: bool = False) -> str:
    v = corps.get(cle)
    if v is None:
        if requis:
            raise _Invalide(f"« {cle} » manque.")
        return ""
    if not isinstance(v, str):
        raise _Invalide(f"« {cle} » doit être un texte.")
    v = _net(v, lignes)
    if len(v) < mini:
        raise _Invalide(f"« {cle} » : {mini} caractère(s) au moins.")
    if len(v) > maxi:
        raise _Invalide(f"« {cle} » : {maxi} caractères au plus.")
    return v


def _entier(corps: dict, cle: str, *, requis: bool = True, mini: int = 0, maxi: int = 2 ** 53):
    v = corps.get(cle)
    if v is None:
        if requis:
            raise _Invalide(f"« {cle} » manque.")
        return None
    if isinstance(v, str) and v.isdigit() and len(v) <= 15:
        v = int(v)
    if not isinstance(v, int) or isinstance(v, bool) or not mini <= v <= maxi:
        raise _Invalide(f"« {cle} » doit être un nombre entre {mini} et {maxi}.")
    return v


def _booleen(corps: dict, cle: str, defaut=None):
    v = corps.get(cle, defaut)
    if v is not defaut and not isinstance(v, bool):
        raise _Invalide(f"« {cle} » doit être vrai ou faux.")
    return v


def _ident_question(corps: dict, cle: str = "id", requis: bool = False):
    v = corps.get(cle)
    if v is None:
        if requis:
            raise _Invalide(f"« {cle} » manque.")
        return None
    if not isinstance(v, str) or not FORMAT_ID.fullmatch(v):
        raise _Invalide(f"« {cle} » : identifiant invalide.")
    return v


def _ids(brut, cle: str = "questions") -> list:
    if not isinstance(brut, list) or len(brut) > 100:
        raise _Invalide(f"« {cle} » doit être une liste d'identifiants (100 au plus).")
    out = []
    for x in brut:
        if isinstance(x, bool) or not isinstance(x, (str, int)) or not FORMAT_ID.fullmatch(str(x)):
            raise _Invalide(f"« {cle} » : identifiant invalide.")
        out.append(str(x))
    return out


def _erreur(message: str, status: int = 400, **extra) -> tuple:
    return status, dict({"erreur": message}, **extra)


async def _lire(sql: str, args: tuple = ()) -> list:
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            return list(await cur.fetchall())


async def _un(sql: str, args: tuple = ()):
    rows = await _lire(sql, args)
    return rows[0] if rows else None


async def _lire_tolerant(sql: str, args: tuple = ()) -> list:
    """Une lecture d'une table du bot (`tickets`) : absente (base neuve, tests) = rien, le reste remonte."""
    try:
        return await _lire(sql, args)
    except sqlite3.OperationalError as ex:
        if "no such table" not in str(ex):
            raise
        return []


def _verrou(gid: int, tid: int) -> asyncio.Lock:
    cle = (int(gid), int(tid))
    v = _verrous.get(cle)
    if v is None:
        if len(_verrous) > 1000:
            for k in [k for k, x in _verrous.items() if not x.locked()][:500]:
                _verrous.pop(k, None)
        v = _verrous[cle] = asyncio.Lock()
    return v


def _garder(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _taches.add(t)
    t.add_done_callback(_taches.discard)
    return t


async def _au_journal(g, type_: str, texte: str, membre_id: int = 0, auteur_id: int = 0) -> None:
    if _journal is None:
        return
    try:
        await _journal(g, type_, texte, membre_id=int(membre_id or 0), auteur_id=int(auteur_id or 0))
    except Exception as ex:  # le journal ne bloque jamais une décision ; l'échec est dit
        _log("[RECRUTEMENT][E11] journal du site indisponible")
        _log(f"[RECRUTEMENT][E11:DETAIL] {type_} {type(ex).__name__} {ex}")


async def _noter(guild_id: int, tid: int, quoi: str, par: int = 0, detail: str = "") -> None:
    async with _get_db() as db:
        await db.execute("INSERT INTO recrutement_historique (guild_id, ticket_id, quand, quoi, par, detail)"
                         " VALUES (?,?,?,?,?,?)", (int(guild_id), int(tid), _maintenant(), quoi, int(par or 0),
                                                   str(detail or "")[:300]))
        await db.commit()


def _qui(g, uid) -> dict | None:
    if not uid:
        return None
    m = g.get_member(int(uid)) if g is not None else None
    return {"id": str(uid), "nom": getattr(m, "display_name", "") or "Membre parti"}


def _ident(g, uid) -> dict:
    m = g.get_member(int(uid)) if uid else None
    avatar = ""
    try:
        avatar = str(m.display_avatar.with_size(64).url) if m is not None else ""
    except AttributeError:
        avatar = ""
    return {"id": str(uid or ""), "nom": getattr(m, "display_name", "") or "Membre parti",
            "pseudo": getattr(m, "name", "") or "", "avatar": avatar, "present": m is not None}


def _ping(uid) -> discord.AllowedMentions:
    """Le candidat seul est prévenu (une mention dans une carte V2 notifie sans ce filtre)."""
    return discord.AllowedMentions(everyone=False, roles=False, replied_user=False, users=[discord.Object(id=int(uid))])


def _icone(nom: str):
    """L'icône maison si elle est installée — sinon rien (jamais un émoji Unicode dans ces cartes)."""
    pe = visuels.icone(nom)
    return pe if getattr(pe, "id", None) else None


def _lien_discord(g, salon: int, message: int = 0) -> str:
    if not salon:
        return ""
    return f"https://discord.com/channels/{g.id}/{int(salon)}" + (f"/{int(message)}" if message else "")


# ═══════════════════════════════════════════════════════════════════════════════
#  La banque : semis depuis le fichier, lecture
# ═══════════════════════════════════════════════════════════════════════════════

_COLS_Q = ("id", "theme", "question", "reponse", "variantes", "type", "difficulte", "source", "section", "extrait",
           "statut", "actif", "retiree", "ordre", "origine", "modifiee", "cree_le", "cree_par", "maj_le", "maj_par",
           "version")
_SNAPSHOT = ("id", "theme", "question", "reponse", "variantes", "type", "difficulte", "source", "section", "extrait")


def _lire_fichier(chemin, cles=("questions", "liens", "elements")) -> list:
    try:
        brut = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as ex:
        _log("[RECRUTEMENT][E9] fichier de départ illisible")
        _log(f"[RECRUTEMENT][E9:DETAIL] {Path(chemin).name} {type(ex).__name__} {ex}")
        return []
    if isinstance(brut, dict):
        brut = next((brut[k] for k in cles if isinstance(brut.get(k), list)), [])
    return [x for x in brut if isinstance(x, dict)] if isinstance(brut, list) else []


def depuis_fichier(x: dict, ordre: int = 0) -> dict | None:
    """Une question du fichier de recherche, propre — ou None (incomplète, ou écartée par la recherche). Une question
    qui dévoile sa réponse entre « à vérifier » et désactivée : on ne la pose pas, le site la montre à reformuler."""
    qid = str(x.get("id") or "").strip()
    question = _net(x.get("question"))[:QUESTION_MAX]
    reponse = _net(x.get("reponse") or x.get("réponse") or x.get("answer"))[:REPONSE_MAX]
    statut = _cle(x.get("statut"))
    if not FORMAT_ID.fullmatch(qid) or len(question) < QUESTION_MIN or not reponse or \
            statut in ("rejete", "rejetee", "ecarte", "ecartee", "refuse", "refusee", "supprime", "supprimee"):
        return None
    try:
        variantes = _variantes(x.get("variantes") or [], reponse)
    except _Invalide:
        variantes = []
    variantes = [v[:VARIANTE_MAX] for v in variantes][:VARIANTES_MAX]
    devoile = fuite(question, reponse, variantes)
    confirme = statut in ("confirme", "confirmee", "confirmed", "verifie", "verifiee", "ok")
    return {"id": qid, "theme": _theme(x.get("theme")), "question": question, "reponse": reponse,
            "variantes": variantes, "type": _type(x.get("type")), "difficulte": _difficulte(x.get("difficulte")),
            "source": _url(x.get("source")), "section": _net(x.get("section"))[:SECTION_MAX],
            "extrait": _net(x.get("extrait"), lignes=True)[:EXTRAIT_MAX],
            "statut": "confirme" if confirme and not devoile else "a_verifier", "actif": not devoile, "ordre": ordre}


def _empreinte(q: dict) -> str:
    return hashlib.sha256(json.dumps({k: q[k] for k in sorted(q) if k != "ordre"}, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _lien_depuis_fichier(x: dict) -> dict | None:
    url = _url(x.get("url") or x.get("lien") or x.get("href"))
    titre = _net(x.get("titre") or x.get("nom") or x.get("title"))[:LIEN_TITRE_MAX]
    if not url or not titre:
        return None
    lid = str(x.get("id") or "").strip()
    if not FORMAT_ID.fullmatch(lid):
        lid = "l-" + hashlib.sha256(url.encode()).hexdigest()[:10]
    return {"id": lid, "titre": titre, "url": url,
            "description": _net(x.get("description") or x.get("desc"))[:LIEN_DESC_MAX]}


async def semer(guild_id: int) -> dict:
    """Le fichier de recherche entre dans la banque de ce serveur : ce qui manque est inséré ; une question venue du
    fichier et jamais touchée sur le site suit le fichier (une correction de la recherche) ; une question modifiée ou
    retirée sur le site ne bouge plus, et n'est jamais ressuscitée. Les liens : insérés tant que le site n'a pas
    enregistré sa propre liste."""
    gid = int(guild_id)
    bilan = {"ajoutees": 0, "mises_a_jour": 0, "liens": 0}
    fichier = [q for k, x in enumerate(_lire_fichier(_fichier_banque)) if (q := depuis_fichier(x, k)) is not None]
    liens_fichier = [x for x in (_lien_depuis_fichier(y) for y in _lire_fichier(_fichier_liens)) if x is not None]
    t = _maintenant()
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO recrutement_reglages (guild_id, nombre, maj_le) VALUES (?,?,?)",
                         (gid, NOMBRE_DEFAUT, t))
        async with db.execute("SELECT id, origine, modifiee, retiree, empreinte FROM recrutement_questions"
                              " WHERE guild_id=?", (gid,)) as cur:
            existantes = {r[0]: tuple(r) for r in await cur.fetchall()}
        total, vus = len(existantes), set()
        for q in fichier:
            if q["id"] in vus:
                continue
            vus.add(q["id"])
            emp = _empreinte(q)
            r = existantes.get(q["id"])
            valeurs = (q["theme"], q["question"], q["reponse"], json.dumps(q["variantes"], ensure_ascii=False),
                       q["type"], q["difficulte"], q["source"], q["section"], q["extrait"], q["statut"],
                       int(q["actif"]))
            if r is None:
                if total >= BANQUE_MAX:
                    continue
                await db.execute(
                    "INSERT INTO recrutement_questions (guild_id, id, theme, question, reponse, variantes, type,"
                    " difficulte, source, section, extrait, statut, actif, ordre, origine, modifiee, empreinte,"
                    " cree_le, maj_le, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'fichier',0,?,?,?,1)",
                    (gid, q["id"], *valeurs, q["ordre"], emp, t, t))
                total += 1
                bilan["ajoutees"] += 1
            elif r[1] == "fichier" and not r[2] and not r[3] and r[4] != emp:
                await db.execute(
                    "UPDATE recrutement_questions SET theme=?, question=?, reponse=?, variantes=?, type=?, difficulte=?,"
                    " source=?, section=?, extrait=?, statut=?, actif=?, empreinte=?, maj_le=?, version=version+1"
                    " WHERE guild_id=? AND id=?", (*valeurs, emp, t, gid, q["id"]))
                bilan["mises_a_jour"] += 1
        async with db.execute("SELECT liens_modifies FROM recrutement_reglages WHERE guild_id=?", (gid,)) as cur:
            r = await cur.fetchone()
        if r is not None and not r[0] and liens_fichier:
            async with db.execute("SELECT id, url FROM recrutement_liens WHERE guild_id=?", (gid,)) as cur:
                deja = [tuple(x) for x in await cur.fetchall()]
            ids, urls = {x[0] for x in deja}, {x[1] for x in deja}
            for lien in liens_fichier:
                if len(urls) >= LIENS_MAX:
                    break
                if lien["url"] in urls or lien["id"] in ids:
                    continue
                await db.execute("INSERT INTO recrutement_liens (guild_id, id, titre, url, description, ordre)"
                                 " VALUES (?,?,?,?,?,?)", (gid, lien["id"], lien["titre"], lien["url"],
                                                           lien["description"], len(urls)))
                ids.add(lien["id"])
                urls.add(lien["url"])
                bilan["liens"] += 1
        await db.commit()
    _semes.add(gid)
    if any(bilan.values()):
        _log("[RECRUTEMENT] banque de départ insérée")
        _log(f"[RECRUTEMENT:DETAIL] serveur={gid} {bilan}")
    return bilan


async def _assurer(guild_id: int) -> None:
    """La banque de ce serveur est semée une fois par démarrage, avant la première lecture."""
    global _verrou_semis
    if int(guild_id) in _semes:
        return
    if _verrou_semis is None:
        _verrou_semis = asyncio.Lock()
    async with _verrou_semis:
        if int(guild_id) not in _semes:
            await semer(guild_id)


def _question(row) -> dict:
    d = dict(zip(_COLS_Q, tuple(row)))
    d["variantes"] = [str(v) for v in _json_liste(d["variantes"])]
    d["actif"], d["retiree"], d["modifiee"] = bool(d["actif"]), bool(d["retiree"]), bool(d["modifiee"])
    d["fuite"] = fuite(d["question"], d["reponse"], d["variantes"])
    return d


def posable(q: dict) -> bool:
    """Peut être posée : active, pas retirée, et sa question ne dévoile pas sa réponse."""
    return bool(q["actif"]) and not q["retiree"] and not q["fuite"]


async def questions(guild_id: int) -> list[dict]:
    await _assurer(guild_id)
    rows = await _lire(f"SELECT {', '.join(_COLS_Q)} FROM recrutement_questions WHERE guild_id=?"
                       " ORDER BY ordre, cree_le, id", (int(guild_id),))
    return [_question(r) for r in rows]


async def reglages(guild_id: int) -> dict:
    await _assurer(guild_id)
    r = await _un("SELECT nombre, version, liens_version, liens_modifies, maj_le, maj_par FROM recrutement_reglages"
                  " WHERE guild_id=?", (int(guild_id),))
    if r is None:
        return {"nombre": NOMBRE_DEFAUT, "version": 1, "liens_version": 1, "liens_modifies": False, "maj_le": 0,
                "maj_par": 0}
    return {"nombre": int(r[0]), "version": int(r[1]), "liens_version": int(r[2]), "liens_modifies": bool(r[3]),
            "maj_le": int(r[4] or 0), "maj_par": int(r[5] or 0)}


async def liens(guild_id: int) -> list[dict]:
    await _assurer(guild_id)
    rows = await _lire("SELECT id, titre, url, description FROM recrutement_liens WHERE guild_id=?"
                       " ORDER BY ordre, rowid", (int(guild_id),))
    return [{"id": r[0], "titre": r[1], "url": r[2], "description": r[3] or ""} for r in rows]


async def modeles(guild_id: int) -> list[dict]:
    rows = await _lire("SELECT id, nom, questions, par_defaut, cree_le, cree_par, maj_le, maj_par, version"
                       " FROM recrutement_modeles WHERE guild_id=? ORDER BY par_defaut DESC, nom, id", (int(guild_id),))
    return [{"id": r[0], "nom": r[1], "questions": [str(x) for x in _json_liste(r[2])], "par_defaut": bool(r[3]),
             "cree_le": int(r[4] or 0), "cree_par": int(r[5] or 0), "maj_le": int(r[6] or 0),
             "maj_par": int(r[7] or 0), "version": int(r[8])} for r in rows]


async def derniere_selection(guild_id: int) -> dict | None:
    """La sélection du dernier questionnaire envoyé sur ce serveur (« Reprendre la sélection précédente »)."""
    r = await _un("SELECT id, ticket_id, candidat_id, questions, envoye_le FROM recrutement_envois"
                  " WHERE guild_id=? AND statut NOT IN ('prepare', 'annule') ORDER BY envoye_le DESC, id DESC LIMIT 1",
                  (int(guild_id),))
    if r is None:
        return None
    return {"envoi_id": int(r[0]), "ticket": int(r[1]), "candidat_id": str(r[2]),
            "questions": [str(q.get("id")) for q in _json_liste(r[3]) if isinstance(q, dict)],
            "envoye_le": int(r[4] or 0)}


# ═══════════════════════════════════════════════════════════════════════════════
#  La sélection d'un envoi : des identifiants, un modèle, la dernière, ou la sélection par défaut
# ═══════════════════════════════════════════════════════════════════════════════

def texte_des_liens(liens_: list) -> str:
    return " ".join(f"{x.get('titre', '')} {x.get('description', '')}" for x in liens_ or [])


def _conflit(q: dict, gardees: list, dans_liens: str, accueil: str):
    """(motif, explication) si `q` ne peut pas être posée avec les questions `gardees` — sa réponse se lirait dans
    les liens, le mot d'accueil ou l'une d'elles, ou son texte dit la réponse de l'une d'elles — sinon None."""
    vu = fuite(dans_liens, q["reponse"], q["variantes"])
    if vu:
        return "reponse_visible", f"« {vu} » se lit dans les liens du questionnaire"
    vu = fuite(accueil, q["reponse"], q["variantes"])
    if vu:
        return "reponse_visible", f"« {vu} » se lit dans le mot d'accueil du ticket"
    for x in gardees:
        vu = fuite(x["question"], q["reponse"], q["variantes"])
        if vu:
            return "reponse_visible", f"« {vu} » se lit dans la question {x['id']}"
    for x in gardees:
        vu = fuite(q["question"], x["reponse"], x["variantes"])
        if vu:
            return "devoile_une_autre", f"elle contient « {vu} », la réponse de {x['id']}"
    return None


def _sans_devoiler(qs: list, liens_: list, contexte: str = "") -> tuple:
    """(gardées, [(id, motif, explication)]) : une question n'est posée que si sa réponse n'apparaît NULLE PART
    dans ce que le candidat lira — ni dans les liens, ni dans le mot d'accueil, ni dans une autre question posée
    avec elle (« Quel est le point faible du Léviathan ? » dévoilerait la réponse de « Quelle créature garde la
    Fosse ? »). Dans l'ordre : la première gardée l'emporte."""
    dans_liens, accueil = texte_des_liens(liens_), str(contexte or "")
    gardees, ecartees = [], []
    for q in qs:
        refus = _conflit(q, gardees, dans_liens, accueil)
        if refus is None:
            gardees.append(q)
        else:
            ecartees.append((q["id"], *refus))
    return gardees, ecartees


def _automatique(banque: list, nombre: int, liens_: list, contexte: str = "") -> list:
    """Sans modèle par défaut : `nombre` questions confirmées, actives, prises à tour de rôle dans chaque thème (au
    hasard dans le thème : deux candidats n'ont pas forcément les mêmes), sans qu'aucune ne dévoile une autre, puis
    rangées par thème."""
    hasard = random.SystemRandom()
    par_theme: dict = {}
    for q in banque:
        if posable(q) and q["statut"] == "confirme":
            par_theme.setdefault(q["theme"], []).append(q)
    for lot in par_theme.values():
        hasard.shuffle(lot)
    ordre = list(THEMES)
    themes = sorted(par_theme, key=lambda t: (ordre.index(t) if t in ordre else len(ordre), t))
    file_ = []
    while any(par_theme[t] for t in themes):
        for t in themes:
            if par_theme[t]:
                file_.append(par_theme[t].pop())
    choisies: list = []
    dans_liens, accueil = texte_des_liens(liens_), str(contexte or "")
    for q in file_:
        if len(choisies) >= nombre:
            break
        if _conflit(q, choisies, dans_liens, accueil) is None:
            choisies.append(q)
    rang = {t: k for k, t in enumerate(themes)}
    return sorted(choisies, key=lambda q: (rang[q["theme"]], q["ordre"], q["id"]))


async def selection(guild_id: int, corps: dict | None, contexte: str = "") -> tuple[int, dict]:
    """(200, {questions, ignorees, motifs, explications, origine}) ou (statut, {erreur}). `corps` : `questions`
    (identifiants), `modele` (identifiant) ou `derniere: true` — un seul ; rien : le modèle par défaut, sinon la
    sélection automatique. Une question inconnue, retirée, désactivée, qui dévoile sa réponse, dont la réponse se
    lirait ailleurs (liens, mot d'accueil `contexte`, autre question) est ignorée : nommée dans `ignorees`, avec son
    motif (`motifs`) et une phrase pour la page (`explications`)."""
    corps = corps if isinstance(corps, dict) else {}
    choix = [k for k in ("questions", "modele", "derniere") if corps.get(k) is not None and corps.get(k) is not False]
    if len(choix) > 1:
        return _erreur("Choisis les questions, un modèle ou la dernière sélection : un seul des trois.")
    banque = await questions(guild_id)
    liens_ = await liens(guild_id)
    par_id = {q["id"]: q for q in banque}
    if not choix:
        defaut = next((m for m in await modeles(guild_id) if m["par_defaut"]), None)
        if defaut is None:
            auto = _automatique(banque, (await reglages(guild_id))["nombre"], liens_, contexte)
            if not auto:
                return _erreur("La banque n'a aucune question confirmée et active : ajoute-en sur le site.", 409)
            return 200, {"questions": auto, "ignorees": [], "motifs": {}, "explications": {}, "origine": "automatique"}
        ids, origine = defaut["questions"], f"modele:{defaut['id']}"
    elif choix[0] == "questions":
        try:
            ids = _ids(corps["questions"])
        except _Invalide as ex:
            return _erreur(str(ex))
        if not ids:
            return _erreur("Coche au moins une question.")
        origine = "questions"
    elif choix[0] == "modele":
        mid = corps["modele"]
        if not isinstance(mid, str) or not FORMAT_ID.fullmatch(mid):
            return _erreur("« modele » : identifiant invalide.")
        m = next((x for x in await modeles(guild_id) if x["id"] == mid), None)
        if m is None:
            return _erreur("Ce modèle n'existe plus.", 404)
        ids, origine = m["questions"], f"modele:{mid}"
    else:
        if corps["derniere"] is not True:
            return _erreur("« derniere » doit valoir true.")
        d = await derniere_selection(guild_id)
        if d is None:
            return _erreur("Aucun questionnaire n'a encore été envoyé.", 404)
        ids, origine = d["questions"], "derniere"
    vus, retenues, motifs = set(), [], {}
    for qid in ids:
        if qid in vus:
            continue
        vus.add(qid)
        q = par_id.get(qid)
        if q is None:
            motifs[qid] = "inconnue"
        elif q["retiree"]:
            motifs[qid] = "retiree"
        elif not q["actif"]:
            motifs[qid] = "inactive"
        elif q["fuite"]:
            motifs[qid] = "devoile_sa_reponse"
        else:
            retenues.append(q)
    if len(retenues) > PAR_ENVOI:
        return _erreur(f"{PAR_ENVOI} questions au plus par envoi ({len(retenues)} choisies).")
    retenues, ecartees = _sans_devoiler(retenues, liens_, contexte)
    explications = {qid: _EXPLICATIONS[m] for qid, m in motifs.items()}
    for qid, motif, texte in ecartees:
        motifs[qid], explications[qid] = motif, texte
    ignorees = list(dict.fromkeys(x for x in ids if x in motifs))
    if not retenues:
        return _erreur("Aucune question posable dans cette sélection (retirées, désactivées ou à reformuler).", 409,
                       ignorees=ignorees, motifs=motifs, explications=explications)
    return 200, {"questions": retenues, "ignorees": ignorees, "motifs": motifs, "explications": explications,
                 "origine": origine}


_EXPLICATIONS = {"inconnue": "elle n'existe pas (ou plus) dans la banque",
                 "retiree": "elle a été retirée de la banque",
                 "inactive": "elle est désactivée",
                 "devoile_sa_reponse": "son texte contient sa propre réponse : à reformuler"}


async def annonce(guild_id: int, contexte: str = "") -> int:
    """Le nombre de questions que la sélection par défaut poserait : celui que l'accueil annonce au candidat."""
    status, sel = await selection(guild_id, None, contexte)
    return len(sel["questions"]) if status == 200 else 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Les cartes Discord (Components V2, FR · EN, aucun émoji Unicode)
# ═══════════════════════════════════════════════════════════════════════════════

def nb_pages(n: int) -> int:
    return max(1, math.ceil(int(n) / PAR_PAGE))


def questions_de_la_page(qs: list, page: int) -> list:
    return qs[(page - 1) * PAR_PAGE: page * PAR_PAGE]


def premiere_incomplete(qs: list, reponses: dict) -> int | None:
    """La première page dont une question n'a pas de réponse ; None : tout est répondu."""
    for p in range(1, nb_pages(len(qs)) + 1):
        if any(int(q["rang"]) not in reponses for q in questions_de_la_page(qs, p)):
            return p
    return None


def _bloc_liens(liens_: list) -> str:
    """« Où trouver les réponses » : les liens, dans la place d'une carte (les descriptions tombent d'abord)."""
    if not liens_:
        return ""
    tete = "**Où trouver les réponses** · *Where to find the answers*"

    def ligne(lien, avec_desc):
        titre = _md(lien["titre"]).replace("[", "(").replace("]", ")")
        url = str(lien["url"]).replace(")", "%29").replace(" ", "%20")
        desc = f" — {_md(lien['description'])}" if avec_desc and lien.get("description") else ""
        return f"- [{titre}]({url}){desc}"
    for avec_desc in (True, False):
        lignes = [ligne(x, avec_desc) for x in liens_]
        if len(tete) + sum(len(x) + 1 for x in lignes) <= LIENS_BUDGET:
            return "\n".join([tete, *lignes])
    garde, place = [], LIENS_BUDGET - len(tete) - 80
    for x in lignes:
        if place - len(x) - 1 < 0:
            break
        garde.append(x)
        place -= len(x) + 1
    reste = len(lignes) - len(garde)
    return "\n".join([tete, *garde, f"-# + {reste} lien(s) : demande-les à la direction · ask the leadership"])


def carte_accueil(texte_panneau: str, nom_panneau: str, nombre: int, liens_: list) -> LayoutView:
    """L'accueil d'un ticket de recrutement : les deux étapes, le nombre de questions de l'étape 2, les liens."""
    s = "s" if nombre > 1 else ""
    combien, combien_en = (f"de **{nombre} question{s}** ", f"{nombre}-question ") if nombre > 0 else ("", "")
    ou = " Toutes les réponses se trouvent sur le wiki : dans les pages ci-dessous, ou à un clic depuis elles." if liens_ else ""
    ou_en = " Every answer is on the wiki: in the pages below, or one click away from them." if liens_ else ""
    items = [discord.ui.TextDisplay("### Bienvenue · Welcome")]
    if texte_panneau:
        items.append(discord.ui.TextDisplay(str(texte_panneau)[:1500]))
    items.append(discord.ui.TextDisplay(
        "**Ta candidature se passe en deux étapes.**\n"
        "**1.** Le questionnaire que tu viens de remplir : la direction le lit.\n"
        f"**2.** S'il convient, un questionnaire {combien}sur le studio, le jeu et ses dernières actualités, ici même, "
        f"dans ce ticket.{ou}\n"
        f"-# Your application has two steps. 1. The form you just filled in: the leadership reads it. 2. If it fits, "
        f"a {combien_en}quiz about the studio, the game and its latest news, right here in this ticket.{ou_en}"))
    bloc = _bloc_liens(liens_)
    if bloc:
        items += [discord.ui.Separator(), discord.ui.TextDisplay(bloc)]
    if nom_panneau:
        items.append(discord.ui.TextDisplay(f"-# {_md(nom_panneau)[:80]}"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=COULEUR_MER))
    return v


def carte_etape1(tid: int, etat: str = "attente", *, nombre: int = 0, par: int = 0, candidat: int = 0,
                 quand: int = 0) -> LayoutView:
    """La carte de l'équipe, dans le ticket : la décision de l'étape 1, puis où en est la candidature."""
    s = "s" if nombre > 1 else ""
    q = f"**{nombre} question{s}**" if nombre else "le questionnaire"
    rangee = None
    if etat == "attente":
        combien = f"{nombre} question{s}, " if nombre else ""
        texte = ("### Étape 1 · décision\n"
                 "Lis le questionnaire d'ouverture ci-dessus, puis :\n"
                 f"- **Envoyer le questionnaire** : l'étape 2 part tout de suite ({combien}la sélection par défaut "
                 "du site).\n"
                 "- **Choisir sur le site** : coche toi-même les questions, sur sa fiche.\n"
                 "- **Refuser l'étape 1** : un message automatique est posté, puis le ticket se ferme.\n"
                 "-# Réservé au fondateur, à la direction et à l'équipe de recrutement. Le candidat ne voit jamais les "
                 "réponses attendues.")
        rangee = discord.ui.ActionRow(BoutonEtape1("e", tid), BoutonEtape1("s", tid), BoutonEtape1("r", tid))
        couleur = COULEUR_LAITON
    elif etat == "envoye":
        texte = (f"### Étape 1 validée\nQuestionnaire de l'étape 2 envoyé par <@{int(par)}> <t:{int(quand)}:R> : {q}.\n"
                 "-# Les réponses arrivent sur le site (rubrique Candidatures) : c'est là qu'on les corrige.")
        rangee = discord.ui.ActionRow(BoutonEtape1("s", tid, "Ouvrir sur le site"))
        couleur = COULEUR_VERT
    elif etat == "reponses":
        texte = (f"### Réponses reçues\n<@{int(candidat)}> a répondu à {q} <t:{int(quand)}:R>.\n"
                 "-# À corriger sur le site : rien n'est jugé ici.")
        rangee = discord.ui.ActionRow(BoutonEtape1("s", tid, "Corriger sur le site"))
        couleur = COULEUR_MER
    elif etat == "accepte":
        texte = f"### Candidature acceptée\nPar <@{int(par)}> <t:{int(quand)}:R> : rôle du clan donné, le ticket se ferme."
        couleur = COULEUR_VERT
    else:
        quoi = "Étape 1 refusée" if etat == "refus_etape1" else "Candidature refusée"
        texte = (f"### {quoi}\nPar <@{int(par)}> <t:{int(quand)}:R> : le message automatique est posté, "
                 "le ticket se ferme dans un instant.")
        couleur = COULEUR_CIRE
    items = [discord.ui.TextDisplay(texte)] + ([rangee] if rangee is not None else [])
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    return v


def _groupes(qs: list) -> list:
    """Les questions, en entier, par formulaire (« Formulaire 1/2 ») : ce que le candidat lit avant de répondre."""
    pages = nb_pages(len(qs))
    out = []
    for p in range(1, pages + 1):
        lignes = [f"**Formulaire {p}/{pages}** · *Form {p}/{pages}*"] if pages > 1 else []
        lignes += [f"**{int(q['rang'])}.** {_md(q['question'])}" for q in questions_de_la_page(qs, p)]
        out.append("\n".join(lignes))
    return out


def cartes_etape2(envoi: dict, etat: str = "ouvert", *, quand: int = 0) -> list:
    """La carte de l'étape 2 — en plusieurs messages si les questions ne tiennent pas dans un seul (4 000 caractères) ;
    le bouton « Répondre » est sur le dernier. `etat` : ouvert · repondu · remplace · clos. Ni réponse attendue, ni
    variante, ni source : seulement les questions et les liens. Un nouveau questionnaire (`renvoi`) le dit."""
    qs = envoi["questions"]
    n, pages = len(qs), nb_pages(len(qs))
    s = "s" if n > 1 else ""
    renvoi = bool(envoi.get("renvoi"))
    titre = (f"## Étape 2 — nouveau questionnaire · {n} question{s}\n-# Step 2 — new questionnaire · {n} question{s}"
             if renvoi else f"## Étape 2 — {n} question{s}\n-# Step 2 — {n} question{s}")
    liens_ = envoi.get("liens") or []
    ou = " Toutes les réponses se trouvent sur le wiki : dans les pages ci-dessous, ou à un clic depuis elles." if liens_ else ""
    ou_en = " Every answer is on the wiki: in the pages below, or one click away from them." if liens_ else ""
    if pages > 1:
        forme = (f" Tu réponds en {pages} formulaires de {PAR_PAGE} questions au plus : chacun est gardé dès que tu "
                 "l'envoies, tu peux faire une pause et reprendre avec « Répondre ».")
        forme_en = (f" You answer in {pages} forms of up to {PAR_PAGE} questions: each one is saved as soon as you "
                    "send it; you can take a break and resume with \"Answer\".")
    else:
        forme, forme_en = " Tu réponds dans un seul formulaire.", " You answer in a single form."
    intro = (f"<@{int(envoi['candidat_id'])}> Réponds à chaque question avec tes propres mots.{ou}{forme}\n"
             f"-# Answer each question in your own words.{ou_en}{forme_en}")
    pied = ("-# La direction lit tes réponses : le résultat ne s'affiche pas ici. "
            "· The leadership reads your answers: the result isn't shown here.")
    if etat == "repondu":
        fin = discord.ui.TextDisplay(f"**Réponses envoyées** · *Answers sent* — <t:{int(quand or _maintenant())}:f>\n"
                                     "-# Merci : la direction les lit. · Thank you: the leadership reads them.")
    elif etat == "remplace":
        fin = discord.ui.TextDisplay("**Questionnaire remplacé** · *Questionnaire replaced*\n"
                                     "-# Les nouvelles questions sont plus bas dans le ticket. "
                                     "· The new questions are further down in the ticket.")
    elif etat == "clos":
        fin = discord.ui.TextDisplay("**Questionnaire clos** · *Questionnaire closed*")
    else:
        fin = discord.ui.ActionRow(BoutonRepondre(int(envoi["id"])))
    bloc = _bloc_liens(liens_)
    messages = [[discord.ui.TextDisplay(titre), discord.ui.TextDisplay(intro)]
                + ([discord.ui.Separator(), discord.ui.TextDisplay(bloc)] if bloc else []) + [discord.ui.Separator()]]
    taille = len(titre) + len(intro) + len(bloc)
    reserve = len(pied) + 260
    for texte in _groupes(qs):
        if taille + len(texte) > TEXTE_MESSAGE - reserve:
            suite = "## Étape 2 — suite · Step 2 — continued"
            messages.append([discord.ui.TextDisplay(suite)])
            taille = len(suite)
        messages[-1].append(discord.ui.TextDisplay(texte))
        taille += len(texte)
    messages[-1] += [discord.ui.Separator(), discord.ui.TextDisplay(pied), fin]
    vues = []
    for items in messages:
        v = LayoutView(timeout=None)
        v.add_item(discord.ui.Container(*items, accent_color=COULEUR_MER))
        vues.append(v)
    return vues


def _vue_texte(texte: str, couleur=COULEUR_LAITON, boutons=()) -> LayoutView:
    """Un mot pour soi (éphémère). La vue est ARRÊTÉE avant l'envoi : discord.py ne la garde pas en mémoire (15 min
    pour un message éphémère), et son expiration ne touche jamais au registre global. Vérifié sur discord.py 2.7.1
    (`ViewStore.remove_view`) : une vue qui mêle un DynamicItem et un bouton ordinaire efface, en expirant, le
    gabarit de ce DynamicItem — tous ses boutons persistants mourraient jusqu'au prochain démarrage. Ces boutons-ci
    répondent par leur gabarit, enregistré au démarrage (`add_dynamic_items`), jamais par cette vue."""
    v = LayoutView(timeout=None)
    items = [discord.ui.TextDisplay(str(texte)[:3900])]
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    v.stop()
    return v


def _effacer_plus_tard(i, delai: float) -> None:
    """Un mot pour soi s'efface tout seul. Seulement après une réponse éphémère à nous (envoyée, ou « réfléchit »
    puis suivie) : `delete_original_response` viserait sinon le message du bouton."""
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


async def _acquitter(i) -> None:
    """« … réfléchit », pour soi seul : la réponse suivra (Discord n'attend que 3 s)."""
    if not i.response.is_done():
        await i.response.defer(ephemeral=True, thinking=True)


async def _avis(i, texte: str, *, efface: bool = True, delai: float | None = None, couleur=COULEUR_LAITON,
                boutons=()) -> None:
    """Un mot pour soi ; il s'efface tout seul (après `AVIS_S`, ou `delai`) sauf `efface=False`."""
    vue = _vue_texte(texte, couleur, boutons)
    if i.response.is_done():
        await i.followup.send(view=vue, ephemeral=True)
    else:
        await i.response.send_message(view=vue, ephemeral=True)
    if efface:
        _effacer_plus_tard(i, AVIS_S if delai is None else delai)


async def _sans_echec(i, travail) -> None:
    """Le filet des boutons persistants : une erreur répond quand même, pour soi, et se compte dans /stats."""
    try:
        await travail
    except Exception as ex:
        diag.compter("questionnaire", "bouton", ex)
        _log("[RECRUTEMENT][E7] bouton en échec")
        _log(f"[RECRUTEMENT][E7:DETAIL] {type(ex).__name__} {ex}")
        try:
            await _avis(i, SOUCI, couleur=COULEUR_CIRE)
        except discord.HTTPException as ex2:
            _log(f"[RECRUTEMENT][E7:DETAIL] réponse impossible {type(ex2).__name__}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Les boutons persistants (ils marchent après un redémarrage)
# ═══════════════════════════════════════════════════════════════════════════════

class BoutonEtape1(discord.ui.DynamicItem[discord.ui.Button], template=r"rq:e1:(?P<d>[ers]):(?P<tid>\d+)"):
    """La carte de l'équipe : e = envoyer le questionnaire, s = le site, r = refuser l'étape 1."""
    LIBELLES = {"e": ("Envoyer le questionnaire", discord.ButtonStyle.success, "envoyer"),
                "s": ("Choisir sur le site", discord.ButtonStyle.secondary, "lien"),
                "r": ("Refuser l'étape 1", discord.ButtonStyle.danger, "interdit")}

    def __init__(self, d: str, ticket: int, libelle: str = ""):
        self.d, self.ticket = d, int(ticket)
        texte, style, icone = self.LIBELLES[d]
        super().__init__(discord.ui.Button(label=(libelle or texte)[:80], style=style, emoji=_icone(icone),
                                           custom_id=f"rq:e1:{d}:{int(ticket)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["d"], int(match["tid"]))

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, etape1_bouton(i, self.d, self.ticket))


class BoutonRepondre(discord.ui.DynamicItem[discord.ui.Button], template=r"rq:rep:(?P<eid>\d+)"):
    """« Répondre » sous la carte de l'étape 2 : le candidat seul ; reprend à la première page sans réponse."""

    def __init__(self, envoi: int):
        self.envoi = int(envoi)
        super().__init__(discord.ui.Button(label="Répondre · Answer", style=discord.ButtonStyle.primary,
                                           emoji=_icone("modifier"), custom_id=f"rq:rep:{int(envoi)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, ouvrir_formulaire(i, self.envoi))


class BoutonPage(discord.ui.DynamicItem[discord.ui.Button], template=r"rq:pg:(?P<eid>\d+):(?P<p>\d+)"):
    """« Continuer · page 2/3 », dans le mot pour soi qui suit un formulaire."""

    def __init__(self, envoi: int, page: int, pages: int = 0):
        self.envoi, self.page = int(envoi), int(page)
        libelle = f"Continuer · page {int(page)}/{int(pages)}" if pages else f"Continuer · page {int(page)}"
        super().__init__(discord.ui.Button(label=libelle[:80], style=discord.ButtonStyle.primary,
                                           emoji=_icone("suivant"), custom_id=f"rq:pg:{int(envoi)}:{int(page)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]), int(match["p"]))

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, ouvrir_formulaire(i, self.envoi, self.page))


BOUTONS_PERSISTANTS = (BoutonEtape1, BoutonRepondre, BoutonPage)


async def _formulaire_en_echec(i, ou: str, error: Exception) -> None:
    """Le filet des formulaires (hors `on_submit`, déjà couvert) : compté, dit, et une réponse pour soi."""
    diag.compter("questionnaire", ou, error)
    _log("[RECRUTEMENT][E7] formulaire en échec")
    _log(f"[RECRUTEMENT][E7:DETAIL] {ou} {type(error).__name__} {error}")
    try:
        await _avis(i, SOUCI, couleur=COULEUR_CIRE)
    except discord.HTTPException as ex:
        _log(f"[RECRUTEMENT][E7:DETAIL] réponse impossible {type(ex).__name__}")


class FormulaireRefus(discord.ui.Modal):
    """« Refuser l'étape 1 » : le formulaire est la confirmation (un clic de travers ne ferme rien)."""

    def __init__(self, ticket: int):
        super().__init__(title="Refuser l'étape 1", timeout=600)
        self.ticket = int(ticket)
        self.note = discord.ui.TextInput(style=discord.TextStyle.short, required=False, max_length=NOTE_MAX,
                                         placeholder="Pseudo Roblox invalide, réponses vides…")
        self.add_item(discord.ui.Label(text="Note pour l'équipe (facultative)",
                                       description="Le candidat ne la voit pas : il lit le message automatique.",
                                       component=self.note))

    async def on_submit(self, i: discord.Interaction):
        await _sans_echec(i, _refuser_depuis_discord(i, self.ticket, _net(self.note.value)[:NOTE_MAX]))

    async def on_error(self, i: discord.Interaction, error: Exception) -> None:
        await _formulaire_en_echec(i, "formulaire_refus", error)


class FormulairePage(discord.ui.Modal):
    """Un formulaire de l'étape 2 : 5 questions au plus. Le titre dit la page ; chaque champ rappelle « Question 3 »
    et le début de la question (elle est en entier dans la carte, au-dessus)."""

    def __init__(self, envoi: dict, page: int):
        pages = nb_pages(len(envoi["questions"]))
        super().__init__(title=f"Étape 2 · Step 2 — page {int(page)}/{pages}"[:45], timeout=FORMULAIRE_S)
        self.envoi, self.page, self.champs = int(envoi["id"]), int(page), []
        for q in questions_de_la_page(envoi["questions"], page):
            champ = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=True, min_length=1,
                                         max_length=REPONSE_CANDIDAT_MAX, placeholder="Ta réponse · Your answer")
            self.add_item(discord.ui.Label(text=f"Question {int(q['rang'])}"[:45],
                                           description=extrait(q["question"], 100), component=champ))
            self.champs.append((int(q["rang"]), champ))

    async def on_submit(self, i: discord.Interaction):
        valeurs = {rang: champ.value for rang, champ in self.champs}
        await _sans_echec(i, soumettre_page(i, self.envoi, self.page, valeurs))

    async def on_error(self, i: discord.Interaction, error: Exception) -> None:
        await _formulaire_en_echec(i, "formulaire_page", error)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'ouverture du ticket : l'accueil et la carte de l'étape 1
# ═══════════════════════════════════════════════════════════════════════════════

async def vue_accueil(g, texte_panneau: str = "", nom_panneau: str = "") -> tuple:
    """(la carte d'accueil, le nombre de questions annoncé)."""
    n = await annonce(g.id, texte_panneau)
    return carte_accueil(texte_panneau, nom_panneau, n, await liens(g.id)), n


async def poser_etape1(g, ch, tid: int, candidat_id: int, *, nombre: int = 0) -> None:
    """Le suivi du ticket commence (étape 1, `nombre` : les questions annoncées par l'accueil) et la carte de
    l'équipe est posée. Une panne de Discord remonte."""
    t = _maintenant()
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO recrutement_suivi (guild_id, ticket_id, candidat_id, salon_id, etape,"
                         " annonce, cree_le, maj_le) VALUES (?,?,?,?,'etape1',?,?,?)",
                         (g.id, int(tid), int(candidat_id), int(getattr(ch, "id", 0) or 0), int(nombre), t, t))
        await db.commit()
    m = await ch.send(view=carte_etape1(tid, nombre=nombre), allowed_mentions=discord.AllowedMentions.none())
    try:
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_suivi SET carte_id=? WHERE guild_id=? AND ticket_id=?",
                             (int(getattr(m, "id", 0) or 0), g.id, int(tid)))
            await db.commit()
    except (sqlite3.Error, asyncio.TimeoutError, OSError) as ex:  # la carte est posée : on ne la reposera pas
        _log("[RECRUTEMENT][E10] carte de l'étape 1 non retenue")
        _log(f"[RECRUTEMENT][E10:DETAIL] ticket={tid} {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le suivi d'un ticket et les envois
# ═══════════════════════════════════════════════════════════════════════════════

_COLS_S = ("ticket_id", "candidat_id", "salon_id", "carte_id", "etape", "annonce", "envoi_id", "fermeture_le",
           "fermeture_par", "fermeture_motif", "decide_par", "decide_le", "cree_le", "maj_le")
_COLS_E = ("id", "guild_id", "ticket_id", "candidat_id", "questions", "liens", "statut", "origine", "renvoi", "envoye_par",
           "cree_le", "envoye_le", "repondu_le", "salon_id", "messages")


async def _suivi(guild_id: int, tid: int) -> dict | None:
    r = await _un(f"SELECT {', '.join(_COLS_S)} FROM recrutement_suivi WHERE guild_id=? AND ticket_id=?",
                  (int(guild_id), int(tid)))
    return dict(zip(_COLS_S, tuple(r))) if r is not None else None


async def _suivi_ou_creer(g, tid: int, tk: dict, ch) -> dict:
    """Le suivi d'un ticket ouvert ; un ticket d'avant le recrutement en deux étapes y entre à l'étape 1."""
    t = _maintenant()
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO recrutement_suivi (guild_id, ticket_id, candidat_id, salon_id, etape,"
                         " cree_le, maj_le) VALUES (?,?,?,?,'etape1',?,?)",
                         (g.id, int(tid), int(tk["user"]), int(getattr(ch, "id", 0) or 0), t, t))
        await db.commit()
    return await _suivi(g.id, tid)


def _envoi_dict(r) -> dict:
    d = dict(zip(_COLS_E, tuple(r)))
    d["questions"] = [q for q in _json_liste(d["questions"]) if isinstance(q, dict)]
    d["liens"] = [x for x in _json_liste(d["liens"]) if isinstance(x, dict)]
    d["messages"] = [int(x) for x in _json_liste(d["messages"]) if str(x).isdigit()]
    d["renvoi"] = bool(d["renvoi"])
    return d


async def _envoi(eid: int) -> dict | None:
    r = await _un(f"SELECT {', '.join(_COLS_E)} FROM recrutement_envois WHERE id=?", (int(eid),))
    return _envoi_dict(r) if r is not None else None


async def _envois_du_ticket(guild_id: int, tid: int) -> list:
    rows = await _lire(f"SELECT {', '.join(_COLS_E)} FROM recrutement_envois WHERE guild_id=? AND ticket_id=?"
                       " AND statut NOT IN ('prepare', 'annule') ORDER BY id", (int(guild_id), int(tid)))
    return [_envoi_dict(r) for r in rows]


async def _reponses(eid: int) -> dict:
    rows = await _lire("SELECT rang, texte, recu_le FROM recrutement_reponses WHERE envoi_id=?", (int(eid),))
    return {int(r[0]): {"texte": r[1], "recu_le": int(r[2] or 0)} for r in rows}


async def _corrections(eid: int) -> dict:
    rows = await _lire("SELECT rang, juste, par, le, version FROM recrutement_corrections WHERE envoi_id=?",
                       (int(eid),))
    return {int(r[0]): {"juste": None if r[1] is None else bool(r[1]), "par": int(r[2] or 0), "le": int(r[3] or 0),
                        "version": int(r[4])} for r in rows}


def bilan(questions_: list, reponses_: dict, corrections_: dict) -> dict:
    total = len(questions_)
    rangs = [int(q["rang"]) for q in questions_]
    repondues = sum(1 for r in rangs if r in reponses_)
    corrigees = sum(1 for r in rangs if (corrections_.get(r) or {}).get("juste") is not None)
    justes = sum(1 for r in rangs if (corrections_.get(r) or {}).get("juste") is True)
    complet = total > 0 and corrigees == total
    return {"total": total, "repondues": repondues, "corrigees": corrigees, "justes": justes,
            "fausses": corrigees - justes, "complet": complet, "reussite": complet and justes == total,
            "taux": round(100 * justes / total) if total else 0, "exigence": EXIGENCE}


async def _bilan_courant(s: dict) -> dict | None:
    """Le bilan du questionnaire EN COURS du ticket (le dernier envoyé) s'il est répondu — None sinon : un
    questionnaire renvoyé et pas encore répondu ne laisse pas l'ancien décider à sa place."""
    e = await _envoi(s["envoi_id"]) if s and s.get("envoi_id") else None
    if e is None or e["statut"] != "repondu":
        return None
    return dict(bilan(e["questions"], await _reponses(e["id"]), await _corrections(e["id"])), envoi=e["id"])


async def _editer(ch, mid: int, vue) -> bool:
    """Une carte réécrite (best effort : le ticket peut avoir été supprimé entre-temps)."""
    if ch is None or not mid:
        return False
    try:
        await ch.get_partial_message(int(mid)).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.HTTPException as ex:
        _log("[RECRUTEMENT][E4] carte non réécrite")
        _log(f"[RECRUTEMENT][E4:DETAIL] message={mid} {type(ex).__name__} {getattr(ex, 'status', '')}")
        return False


async def _editer_carte_staff(g, ch, s: dict | None, etat: str, **kw) -> None:
    if s is None or not s.get("carte_id"):
        return
    await _editer(ch, s["carte_id"], carte_etape1(int(s["ticket_id"]), etat, candidat=int(s["candidat_id"]), **kw))


async def _editer_cartes(ch, e: dict, etat: str, quand: int = 0) -> None:
    """Le dernier message de la carte de l'étape 2 (celui du bouton) dit maintenant où en est l'envoi."""
    if not e.get("messages"):
        return
    vues = cartes_etape2(e, etat, quand=quand)
    if len(vues) == len(e["messages"]):
        await _editer(ch, e["messages"][-1], vues[-1])


async def _poster_cartes(ch, e: dict) -> list:
    """Les messages de l'étape 2, dans l'ordre ; le candidat est prévenu par le premier. Un échec retire ce qui était
    déjà posé et remonte."""
    ids = []
    try:
        for k, vue in enumerate(cartes_etape2(e, "ouvert")):
            m = await ch.send(view=vue, allowed_mentions=_ping(e["candidat_id"]) if k == 0
                              else discord.AllowedMentions.none())
            ids.append(int(getattr(m, "id", 0) or 0))
    except discord.HTTPException:
        for mid in ids:
            try:
                await ch.get_partial_message(mid).delete()
            except discord.HTTPException as ex:
                _log(f"[RECRUTEMENT][E2:DETAIL] message {mid} non retiré {type(ex).__name__}")
        raise
    return ids


async def _ticket(g, tid: int):
    """(salon, ticket, refus) — le refus est déjà (statut, corps)."""
    try:
        ch, tk = await _ticket_ouvert(g, int(tid))
    except discord.HTTPException as ex:
        _log("[RECRUTEMENT][E1] ticket illisible")
        _log(f"[RECRUTEMENT][E1:DETAIL] ticket={tid} {type(ex).__name__} {getattr(ex, 'status', '')}")
        return None, None, _erreur(DISCORD_HS, 503)
    if ch is None:
        existe = await _lire_tolerant("SELECT 1 FROM tickets WHERE id=? AND guild_id=?", (int(tid), g.id))
        return None, None, (_erreur(FERME, 409) if existe else _erreur("Ticket introuvable.", 404))
    if str(tk.get("panel_id") or "") not in _panneaux(await _cfg(g.id)) and await _suivi(g.id, tid) is None:
        return None, None, _erreur("Ce ticket n'est pas une candidature du clan.", 404)
    return ch, tk, None


def _texte_etape(etape: str) -> str:
    return {"etape1": "La candidature attend la décision de l'étape 1.",
            "etape2": "Le questionnaire de l'étape 2 est déjà envoyé : le candidat y répond.",
            "reponses": "Les réponses de l'étape 2 sont arrivées : à corriger sur le site.",
            "refus_etape1": "L'étape 1 est refusée : le ticket se ferme.",
            "refuse": "La candidature est refusée : le ticket se ferme.",
            "accepte": "La candidature est acceptée."}.get(etape, "Cette candidature n'est plus à cette étape.")


async def envoyer(g, tid: int, auteur, corps: dict | None, *, depuis: str = "etape1") -> tuple[int, dict]:
    """Le questionnaire de l'étape 2 part dans le ticket (`depuis` « etape1 ») — ou un nouveau, à la place du
    précédent (« renvoi »). La sélection réellement envoyée est figée dans l'envoi (un instantané : la question, la
    réponse attendue et ses variantes telles qu'elles étaient), les liens aussi."""
    ch, tk, refus = await _ticket(g, tid)
    if refus:
        return refus
    async with _verrou(g.id, tid):
        s = await _suivi_ou_creer(g, tid, tk, ch)
        if s["fermeture_le"]:
            return _erreur("La fermeture de ce ticket est déjà prévue.", 409, etape=s["etape"])
        if (depuis == "etape1" and s["etape"] != "etape1") or \
                (depuis == "renvoi" and s["etape"] not in ("etape2", "reponses")):
            return _erreur(_texte_etape(s["etape"]), 409, etape=s["etape"])
        pnl = ((await _cfg(g.id)).get("ticket_panels") or {}).get(str(tk.get("panel_id") or "")) or {}
        accueil = str(pnl.get("welcome_message") or "") if isinstance(pnl, dict) else ""
        status, sel = await selection(g.id, corps, accueil)
        if status != 200:
            return status, sel
        qs = [dict({c: q[c] for c in _SNAPSHOT}, rang=k + 1) for k, q in enumerate(sel["questions"])]
        lns = await liens(g.id)
        t = _maintenant()
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO recrutement_envois (guild_id, ticket_id, candidat_id, questions, liens, statut, origine,"
                " renvoi, envoye_par, cree_le, salon_id) VALUES (?,?,?,?,?,'prepare',?,?,?,?,?)",
                (g.id, int(tid), int(tk["user"]), json.dumps(qs, ensure_ascii=False),
                 json.dumps(lns, ensure_ascii=False), sel["origine"], int(depuis == "renvoi"), int(auteur.id), t,
                 int(ch.id)))
            eid = int(cur.lastrowid)
            await db.commit()
        e = await _envoi(eid)
        ancien = await _envoi(s["envoi_id"]) if s["envoi_id"] else None
        try:
            messages = await _poster_cartes(ch, e)
        except discord.HTTPException as ex:
            async with _get_db() as db:
                await db.execute("UPDATE recrutement_envois SET statut='annule' WHERE id=?", (eid,))
                await db.commit()
            _log("[RECRUTEMENT][E2] questionnaire non posé")
            _log(f"[RECRUTEMENT][E2:DETAIL] ticket={tid} {type(ex).__name__} {getattr(ex, 'status', '')}")
            return _erreur("Discord a refusé l'envoi du questionnaire : réessaie dans un instant.", 503)
        t = _maintenant()
        remplace = ancien is not None and ancien["statut"] in EN_ATTENTE
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_envois SET statut='envoye', envoye_le=?, messages=? WHERE id=?",
                             (t, json.dumps(messages), eid))
            if remplace:
                await db.execute("UPDATE recrutement_envois SET statut='remplace' WHERE id=? AND statut IN (?, ?)",
                                 (ancien["id"], *EN_ATTENTE))
            await db.execute("UPDATE recrutement_suivi SET etape='etape2', envoi_id=?, maj_le=? WHERE guild_id=?"
                             " AND ticket_id=?", (eid, t, g.id, int(tid)))
            await db.commit()
        if remplace:
            await _editer_cartes(ch, ancien, "remplace")
        await _editer_carte_staff(g, ch, s, "envoye", nombre=len(qs), par=auteur.id, quand=t)
        quoi = "renvoi" if depuis == "renvoi" else "questionnaire"
        await _noter(g.id, tid, quoi, auteur.id, f"{len(qs)} question(s) · {sel['origine']}")
        await _au_journal(g, f"recrutement.{quoi}",
                          ("Recrutement : nouveau questionnaire" if depuis == "renvoi" else "Recrutement : questionnaire")
                          + f" de l'étape 2 envoyé à <@{int(tk['user'])}> ({len(qs)} question(s)) par <@{auteur.id}>",
                          membre_id=int(tk["user"]), auteur_id=auteur.id)
    n = len(qs)
    message = f"Questionnaire envoyé : {n} question{'s' if n > 1 else ''}."
    if sel["ignorees"]:
        message += (f" {len(sel['ignorees'])} question(s) ignorée(s) : retirée(s), désactivée(s), à reformuler, ou "
                    "dont la réponse se lirait ailleurs dans le questionnaire.")
    return 200, {"ok": True, "message": message, "envoi": eid, "questions": n, "ignorees": sel["ignorees"],
                 "motifs": sel["motifs"], "explications": sel["explications"]}


async def refuser(g, tid: int, auteur, *, depuis: str = "etape1", note: str = "") -> tuple[int, dict]:
    """Le message automatique dans le ticket (FR · EN), puis la fermeture par le circuit normal (transcript, suivi,
    décision « refusé », motif interne « étape 1 » ou « étape 2 ») après un court délai — le temps de le lire."""
    ch, tk, refus = await _ticket(g, tid)
    if refus:
        return refus
    async with _verrou(g.id, tid):
        s = await _suivi_ou_creer(g, tid, tk, ch)
        if s["fermeture_le"]:
            return _erreur("La fermeture de ce ticket est déjà prévue.", 409, etape=s["etape"])
        if (depuis == "etape1" and s["etape"] != "etape1") or (depuis == "final" and s["etape"] not in ("etape2", "reponses")):
            return _erreur(_texte_etape(s["etape"]), 409, etape=s["etape"])
        texte = REFUS_ETAPE1 if depuis == "etape1" else REFUS_FINAL
        try:
            await ch.send(view=_vue_candidat(int(tk["user"]), texte), allowed_mentions=_ping(tk["user"]))
        except discord.HTTPException as ex:
            _log("[RECRUTEMENT][E5] message automatique non posté")
            _log(f"[RECRUTEMENT][E5:DETAIL] ticket={tid} {type(ex).__name__} {getattr(ex, 'status', '')}")
            return _erreur(DISCORD_HS, 503)
        t = _maintenant()
        motif = ("étape 1" if depuis == "etape1" else "étape 2") + (f" — {note}" if note else "")
        etape = "refus_etape1" if depuis == "etape1" else "refuse"
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_suivi SET etape=?, fermeture_le=?, fermeture_par=?, fermeture_motif=?,"
                             " decide_par=?, decide_le=?, maj_le=? WHERE guild_id=? AND ticket_id=?",
                             (etape, t + int(DELAI_FERMETURE), int(auteur.id), motif[:200], int(auteur.id), t, t,
                              g.id, int(tid)))
            await db.execute("UPDATE recrutement_envois SET statut='clos' WHERE guild_id=? AND ticket_id=?"
                             " AND statut IN (?, ?)", (g.id, int(tid), *EN_ATTENTE))
            await db.commit()
        await _editer_carte_staff(g, ch, s, etape, par=auteur.id, quand=t)
        await _noter(g.id, tid, etape, auteur.id, motif)
        if depuis == "etape1":
            await _au_journal(g, "recrutement.etape1_refusee", f"Recrutement : étape 1 refusée pour <@{int(tk['user'])}>"
                              f" par <@{auteur.id}>" + (f" — {note}" if note else ""),
                              membre_id=int(tk["user"]), auteur_id=auteur.id)
    _planifier_fermeture(g, tid, DELAI_FERMETURE)
    return 200, {"ok": True, "message": f"Message envoyé au candidat : le ticket se ferme dans {int(DELAI_FERMETURE)} s."}


def _vue_candidat(uid: int, texte: str) -> LayoutView:
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(f"<@{int(uid)}>\n{texte}"), accent_color=COULEUR_CIRE))
    return v


def _planifier_fermeture(g, tid: int, delai: float, essai: int = 1) -> None:
    cle = (g.id, int(tid))
    t = _fermetures.get(cle)
    if t is not None and not t.done() and t is not asyncio.current_task():
        return
    _fermetures[cle] = _garder(_fermer_plus_tard(g, int(tid), delai, essai))


async def _fermer_plus_tard(g, tid: int, delai: float, essai: int = 1) -> None:
    """La fermeture prévue : le circuit normal du bot (`decider`, refus). Discord en panne : on réessaie un peu plus
    tard (5 fois) ; la fermeture prévue survit à un redémarrage (`reprendre_fermetures`)."""
    await asyncio.sleep(max(0.0, float(delai)))
    s = await _suivi(g.id, tid)
    if s is None or not s["fermeture_le"]:
        return
    auteur = g.get_member(int(s["fermeture_par"] or 0)) or getattr(g, "me", None)
    try:
        ok, message = await _decider(g, tid, auteur, False, s["fermeture_motif"] or "étape 1")
    except Exception as ex:  # la fermeture différée ne meurt pas en silence : dite, comptée, réessayée
        diag.compter("questionnaire", "fermeture", ex)
        ok, message = False, DISCORD_HS
        _log(f"[RECRUTEMENT][E3:DETAIL] ticket={tid} {type(ex).__name__} {ex}")
    if not ok and message == DISCORD_HS and essai < ESSAIS_FERMETURE:
        _fermetures.pop((g.id, int(tid)), None)
        _planifier_fermeture(g, tid, REESSAI_FERMETURE, essai + 1)
        return
    async with _get_db() as db:
        await db.execute("UPDATE recrutement_suivi SET fermeture_le=0, maj_le=? WHERE guild_id=? AND ticket_id=?",
                         (_maintenant(), g.id, int(tid)))
        await db.commit()
    if not ok and message != FERME:
        _log("[RECRUTEMENT][E3] fermeture différée impossible")
        _log(f"[RECRUTEMENT][E3:DETAIL] ticket={tid} {message}")


async def accepter(g, tid: int, auteur, *, forcer: bool = False) -> tuple[int, dict]:
    """Le circuit actuel : rôle du clan, fermeture. Sans `forcer`, il faut un questionnaire répondu, entièrement
    corrigé, à 100 % de réponses justes (l'exigence affichée) — la décision reste celle de la personne."""
    ch, tk, refus = await _ticket(g, tid)
    if refus:
        return refus
    async with _verrou(g.id, tid):
        s = await _suivi_ou_creer(g, tid, tk, ch)
        if s["fermeture_le"]:
            return _erreur("La fermeture de ce ticket est déjà prévue.", 409, etape=s["etape"])
        if s["etape"] not in OUVERTES:
            return _erreur(_texte_etape(s["etape"]), 409, etape=s["etape"])
        b = await _bilan_courant(s)
        if not forcer and not (b and b["reussite"]):
            if b is None:
                texte = ("Le questionnaire en cours n'a pas encore de réponses : accepter quand même demande "
                         "« forcer ».")
            elif not b["complet"]:
                texte = f"Correction incomplète ({b['corrigees']}/{b['total']}) : termine-la, ou accepte en forçant."
            else:
                texte = f"Exigence : {EXIGENCE} % de réponses justes ({b['justes']}/{b['total']}). Accepter quand même demande « forcer »."
            return _erreur(texte, 409, bilan=b, forcer_possible=True)
        ok, message = await _decider(g, tid, auteur, True, "")
        if not ok:
            return _erreur(message, 503 if message == DISCORD_HS else 409)
        t = _maintenant()
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_suivi SET etape='accepte', decide_par=?, decide_le=?, maj_le=?"
                             " WHERE guild_id=? AND ticket_id=?", (int(auteur.id), t, t, g.id, int(tid)))
            await db.execute("UPDATE recrutement_envois SET statut='clos' WHERE guild_id=? AND ticket_id=?"
                             " AND statut IN (?, ?)", (g.id, int(tid), *EN_ATTENTE))
            await db.commit()
        await _noter(g.id, tid, "accepte", auteur.id, "forcé" if forcer and not (b and b["reussite"]) else "")
    return 200, {"ok": True, "message": message}


async def reprendre_fermetures() -> int:
    """Au démarrage : les fermetures prévues avant l'arrêt sont replanifiées (sinon le ticket restait ouvert avec son
    message « ce ticket va être clôturé »)."""
    rows = await _lire("SELECT guild_id, ticket_id, fermeture_le FROM recrutement_suivi WHERE fermeture_le > 0")
    n = 0
    for gid, tid, quand in rows:
        g = _bot.get_guild(int(gid)) if _bot is not None else None
        if g is None:
            continue
        _planifier_fermeture(g, int(tid), max(REPRISE_MIN, float(quand) - time.time()))
        n += 1
    return n


async def purger(jours: int = RETENTION_JOURS) -> int:
    """La rétention : les questionnaires (et leurs réponses, corrections, historique) de plus d'un an s'effacent —
    comme le suivi des candidatures (`gdpr.RETENTION`)."""
    limite = _maintenant() - int(jours) * 86400
    async with _get_db() as db:
        await db.execute("DELETE FROM recrutement_reponses WHERE envoi_id IN (SELECT id FROM recrutement_envois"
                         " WHERE cree_le < ?)", (limite,))
        await db.execute("DELETE FROM recrutement_corrections WHERE envoi_id IN (SELECT id FROM recrutement_envois"
                         " WHERE cree_le < ?)", (limite,))
        cur = await db.execute("DELETE FROM recrutement_envois WHERE cree_le < ?", (limite,))
        n = int(cur.rowcount or 0)
        await db.execute("DELETE FROM recrutement_suivi WHERE maj_le < ? AND fermeture_le = 0", (limite,))
        await db.execute("DELETE FROM recrutement_historique WHERE quand < ?", (limite,))
        await db.commit()
    return n


async def _vieux_envois(db, guild_id: int, limite: int) -> list:
    """Les questionnaires d'avant `limite` dont la candidature est fermée (un ticket ouvert garde les siens)."""
    async with db.execute("SELECT id, ticket_id FROM recrutement_envois WHERE guild_id=? AND cree_le < ?",
                          (int(guild_id), int(limite))) as cur:
        envois = [tuple(r) for r in await cur.fetchall()]
    if not envois:
        return []
    try:
        async with db.execute("SELECT id FROM tickets WHERE guild_id=? AND status='open'", (int(guild_id),)) as cur:
            ouverts = {int(r[0]) for r in await cur.fetchall()}
    except sqlite3.OperationalError as ex:
        if "no such table" not in str(ex):
            raise
        ouverts = set()
    return [eid for eid, tid in envois if int(tid) not in ouverts]


async def nettoyer_regle(guild_id: int, jours: int, maintenant: float | None = None) -> int:
    """La règle « Questionnaires de recrutement » du nettoyage du site : les questions posées, les réponses et les
    corrections des candidatures fermées depuis plus de `jours` jours s'effacent. Rend le nombre retiré."""
    limite = int(maintenant or time.time()) - int(jours) * 86400
    async with _get_db() as db:
        ids_ = await _vieux_envois(db, guild_id, limite)
        for k in range(0, len(ids_), 400):
            lot = ids_[k:k + 400]
            marques = ",".join("?" * len(lot))
            for table in ("recrutement_reponses", "recrutement_corrections"):
                await db.execute(f"DELETE FROM {table} WHERE envoi_id IN ({marques})", lot)
            await db.execute(f"DELETE FROM recrutement_envois WHERE id IN ({marques})", lot)
        await db.execute("DELETE FROM recrutement_historique WHERE guild_id=? AND quand < ?", (int(guild_id), limite))
        await db.execute("DELETE FROM recrutement_suivi WHERE guild_id=? AND maj_le < ? AND fermeture_le = 0"
                         " AND etape IN ('refus_etape1', 'refuse', 'accepte')", (int(guild_id), limite))
        await db.commit()
    return len(ids_)


async def compter_regle(guild_id: int, jours: int, maintenant: float | None = None) -> int:
    limite = int(maintenant or time.time()) - int(jours) * 86400
    async with _get_db() as db:
        return len(await _vieux_envois(db, guild_id, limite))


#  `tableau.ajouter_regle(**REGLE_NETTOYAGE)` : la règle apparaît dans la rubrique « Nettoyage » du site, réglable de
#  30 jours à un an (au-delà, la rétention du démarrage efface de toute façon : comme le suivi des candidatures).
REGLE_NETTOYAGE = {"cle": "questionnaires", "nom": "Questionnaires de recrutement",
                   "quoi": "Les questions posées, les réponses et les corrections des candidatures fermées : "
                           "effacées après ce délai.",
                   "garde_jours": RETENTION_JOURS, "min": 30, "max": RETENTION_JOURS, "ordre": 31,
                   "fn": nettoyer_regle, "compter": compter_regle}


async def demarrer(bot) -> None:
    """Au démarrage : la rétention, la banque des serveurs qui ont des tickets du clan, les fermetures à reprendre."""
    global _bot
    _bot = bot
    await purger()
    for g in list(getattr(bot, "guilds", []) or []):
        if _panneaux(await _cfg(g.id)):
            await semer(g.id)
    n = await reprendre_fermetures()
    if n:
        _log(f"[RECRUTEMENT] {n} fermeture(s) reprise(s)")


# ═══════════════════════════════════════════════════════════════════════════════
#  Discord : la carte de l'étape 1, les formulaires de l'étape 2
# ═══════════════════════════════════════════════════════════════════════════════

async def _peut(i) -> bool:
    return _autorise is not None and bool(await _autorise(i))


async def etape1_bouton(i, d: str, tid: int) -> None:
    if not pret() or i.guild is None:
        return await _avis(i, DEMARRE)
    if d == "r":
        if not await _peut(i):
            return await _avis(i, RESERVE)
        return await i.response.send_modal(FormulaireRefus(tid))
    await _acquitter(i)
    if not await _peut(i):
        return await _avis(i, RESERVE)
    if d == "s":
        return await _lien_site(i, tid)
    cle = ("e1", i.guild.id, int(tid))
    if cle in _en_cours:
        return await _avis(i, "L'envoi du questionnaire est déjà en cours.")
    _en_cours.add(cle)
    try:
        status, corps = await envoyer(i.guild, tid, i.user, None, depuis="etape1")
    finally:
        _en_cours.discard(cle)
    texte = corps.get("message") if status == 200 else corps.get("erreur")
    await _avis(i, texte or SOUCI, couleur=COULEUR_VERT if status == 200 else COULEUR_CIRE)


async def _refuser_depuis_discord(i, tid: int, note: str) -> None:
    await _acquitter(i)
    if not pret() or i.guild is None:
        return await _avis(i, DEMARRE)
    if not await _peut(i):
        return await _avis(i, RESERVE)
    status, corps = await refuser(i.guild, tid, i.user, depuis="etape1", note=note)
    await _avis(i, corps.get("message") if status == 200 else corps.get("erreur") or SOUCI,
                couleur=COULEUR_VERT if status == 200 else COULEUR_CIRE)


async def _lien_site(i, tid: int) -> None:
    """Le lien personnel du site, ouvert sur la candidature (« Choisir sur le site »), pour soi seul."""
    url, refus = await _lien(i) if _lien is not None else (None, "Le site n'est pas branché.")
    if not url:
        return await _avis(i, refus or "Le site n'est pas joignable pour le moment.")
    s = await _suivi(i.guild.id, tid)
    cible = f"#recrutement={int(tid)}" + (f"&membre={int(s['candidat_id'])}" if s else "")
    bouton = discord.ui.Button(label="Ouvrir sa fiche sur le site", url=url + cible, emoji=_icone("lien"))
    await _avis(i, "Ton lien personnel : il ne s'ouvre qu'une fois, valable 24 h. Ne le partage pas.\n"
                   "-# Sur le site : coche les questions dans la banque, ou reprends un modèle ou la sélection "
                   "précédente, puis envoie l'étape 2.", efface=False, boutons=[bouton])


async def ouvrir_formulaire(i, eid: int, page: int | None = None) -> None:
    """« Répondre » (ou « Continuer ») : le formulaire de la première page sans réponse. Une page déjà envoyée ne se
    rouvre pas ; un questionnaire répondu, remplacé ou clos le dit."""
    if not pret() or i.guild is None:
        return await _avis(i, DEMARRE)
    e = await _envoi(eid)
    if e is None or e["guild_id"] != i.guild.id:
        return await _avis(i, INTROUVABLE)
    if i.user.id != e["candidat_id"]:
        return await _avis(i, SEUL_CANDIDAT)
    if e["statut"] == "repondu":
        return await _avis(i, DEJA)
    if e["statut"] not in EN_ATTENTE:
        return await _avis(i, REMPLACE)
    p = premiere_incomplete(e["questions"], await _reponses(eid))
    if p is None:  # tout est là mais l'envoi n'a pas été clos (coupure au mauvais moment) : on le clôt maintenant
        await _acquitter(i)
        return await _terminer(i, e)
    await i.response.send_modal(FormulairePage(e, p))


async def _garder_page(e: dict, textes: dict) -> bool:
    """Les réponses d'une page, gardées d'un coup — seulement tant que le questionnaire est ouvert. Chaque ligne
    porte le serveur et le candidat : l'effacement RGPD (`gdpr`) les trouve sans passer par l'envoi."""
    t = _maintenant()
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_envois SET statut='en_cours' WHERE id=? AND statut IN (?, ?)",
                               (int(e["id"]), *EN_ATTENTE))
        if (cur.rowcount or 0) < 1:
            await db.commit()
            return False
        for rang, texte in textes.items():
            await db.execute("INSERT OR REPLACE INTO recrutement_reponses (envoi_id, rang, guild_id, candidat_id,"
                             " texte, recu_le) VALUES (?,?,?,?,?,?)",
                             (int(e["id"]), int(rang), int(e["guild_id"]), int(e["candidat_id"]), texte, t))
        await db.commit()
    return True


async def soumettre_page(i, eid: int, page: int, valeurs: dict) -> None:
    await _acquitter(i)
    if not pret() or i.guild is None:
        return await _avis(i, DEMARRE)
    e = await _envoi(eid)
    if e is None or e["guild_id"] != i.guild.id:
        return await _avis(i, INTROUVABLE)
    if i.user.id != e["candidat_id"]:
        return await _avis(i, SEUL_CANDIDAT)
    if e["statut"] == "repondu":
        return await _avis(i, DEJA)
    if e["statut"] not in EN_ATTENTE:
        return await _avis(i, REMPLACE)
    attendus = {int(q["rang"]) for q in questions_de_la_page(e["questions"], page)}
    textes = {int(r): _net(v, lignes=True)[:REPONSE_CANDIDAT_MAX] for r, v in valeurs.items() if int(r) in attendus}
    if set(textes) != attendus or not all(textes.values()):
        return await _avis(i, "Chaque question demande une réponse : rouvre le formulaire avec « Répondre ».\n"
                              "-# Every question needs an answer: open the form again with \"Answer\".")
    if not await _garder_page(e, textes):
        e = await _envoi(eid)
        return await _avis(i, DEJA if e is not None and e["statut"] == "repondu" else REMPLACE)
    p = premiere_incomplete(e["questions"], await _reponses(eid))
    if p is None:
        return await _terminer(i, e)
    pages = nb_pages(len(e["questions"]))
    await _avis(i, f"Page {page}/{pages} enregistrée. Continue avec la page {p}/{pages} — ou plus tard, avec "
                   f"« Répondre » sous les questions.\n-# Page {page}/{pages} saved. Continue with page {p}/{pages} — "
                   "or later, with \"Answer\" under the questions.",
                delai=PAGE_S, couleur=COULEUR_MER, boutons=[BoutonPage(eid, p, pages)])


async def _terminer(i, e: dict) -> None:
    """Toutes les réponses sont là : l'envoi se ferme UNE fois (le premier qui y arrive), le candidat lit « Merci »,
    la carte dit « Réponses envoyées », celle de l'équipe « Réponses reçues »."""
    t = _maintenant()
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_envois SET statut='repondu', repondu_le=? WHERE id=?"
                               " AND statut IN (?, ?)", (t, int(e["id"]), *EN_ATTENTE))
        premier = (cur.rowcount or 0) > 0
        if premier:
            await db.execute("UPDATE recrutement_suivi SET etape='reponses', maj_le=? WHERE guild_id=? AND ticket_id=?"
                             " AND envoi_id=? AND etape='etape2'", (t, e["guild_id"], e["ticket_id"], e["id"]))
        await db.commit()
    await _avis(i, MERCI, efface=False, couleur=COULEUR_VERT)
    if not premier:
        return
    g = i.guild
    ch = getattr(i, "channel", None)
    if ch is None or getattr(ch, "id", 0) != e["salon_id"]:
        try:
            ch, _tk = await _ticket_ouvert(g, e["ticket_id"])
        except discord.HTTPException:
            ch = None
    await _editer_cartes(ch, e, "repondu", t)
    s = await _suivi(g.id, e["ticket_id"])
    await _editer_carte_staff(g, ch, s, "reponses", nombre=len(e["questions"]), quand=t)
    await _noter(g.id, e["ticket_id"], "reponses", e["candidat_id"], f"{len(e['questions'])} réponse(s)")
    await _au_journal(g, "recrutement.reponses", f"Recrutement : réponses de l'étape 2 reçues de <@{e['candidat_id']}>"
                      f" ({len(e['questions'])} question(s)) — à corriger sur le site", membre_id=e["candidat_id"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Le site : la banque, les liens, les réglages, les modèles, les dossiers, les décisions
# ═══════════════════════════════════════════════════════════════════════════════

def page_web(url) -> str:
    """La page d'une adresse (sans ancre ni minutage) : « rellseas.fandom.com/wiki/Talents », « youtube:<vidéo> »."""
    m = re.match(r"https?://(?:www\.|m\.)?([^/?#]+)(/[^?#]*)?(?:\?([^#]*))?", str(url or "").strip())
    if not m:
        return ""
    hote, chemin, requete = m.group(1).lower(), (m.group(2) or "").rstrip("/"), m.group(3) or ""
    if hote.endswith("youtube.com") or hote == "youtu.be":
        v = re.search(r"(?:^|&)v=([\w-]+)", requete)
        return "youtube:" + (v.group(1) if v else chemin.strip("/").split("/")[-1])
    return hote + chemin


def _question_site(g, q: dict, dans_liens: str | None = None, pages_liens: set | None = None) -> dict:
    """Une question pour le site. `fuite` : le texte de la question dit sa réponse ; `dans_les_liens` : un lien du
    questionnaire la dit (la question ne part pas tant qu'il est là) ; `source_dans_les_liens` : la page de sa
    source est dans les liens donnés au candidat (None : pas de source, ou liens non lus)."""
    return dict({k: q[k] for k in _COLS_Q if k not in ("cree_par", "maj_par")}, fuite=q["fuite"], posable=posable(q),
                dans_les_liens=fuite(dans_liens, q["reponse"], q["variantes"]) if dans_liens else "",
                source_dans_les_liens=(page_web(q["source"]) in pages_liens) if q["source"] and pages_liens is not None
                else None,
                cree_par=_qui(g, q["cree_par"]), maj_par=_qui(g, q["maj_par"]))


def _modele_site(g, m: dict, par_id: dict) -> dict:
    ignorees = [x for x in m["questions"] if x not in par_id or not posable(par_id[x])]
    return dict(m, cree_par=_qui(g, m["cree_par"]), maj_par=_qui(g, m["maj_par"]),
                valides=len(m["questions"]) - len(ignorees), ignorees=ignorees)


async def banque(g) -> dict:
    qs = await questions(g.id)
    par_id = {q["id"]: q for q in qs}
    r = await reglages(g.id)
    d = await derniere_selection(g.id)
    if d is not None:
        d = dict(d, candidat=_ident(g, int(d["candidat_id"]))["nom"])
    lns = await liens(g.id)
    dans_liens, pages = texte_des_liens(lns), {page_web(x["url"]) for x in lns}
    #  « Toutes les réponses se trouvent dans les liens » : les pages sources des questions posables qui ne sont pas
    #  dans les liens (à ajouter sur le site si la page d'accueil du wiki ne suffit pas).
    manquent: dict = {}
    for q in qs:
        if posable(q) and q["source"] and page_web(q["source"]) not in pages:
            manquent.setdefault(page_web(q["source"]), [q["source"].split("#")[0], 0])[1] += 1
    return {"questions": [_question_site(g, q, dans_liens, pages) for q in qs], "liens": lns,
            "sources_sans_lien": [{"url": u, "questions": n} for u, n in
                                  sorted(manquent.values(), key=lambda x: (-x[1], x[0]))][:50],
            "liens_version": r["liens_version"],
            "reglages": {"nombre": r["nombre"], "version": r["version"], "annonce": await annonce(g.id),
                         "maj_le": r["maj_le"], "maj_par": _qui(g, r["maj_par"])},
            "modeles": [_modele_site(g, m, par_id) for m in await modeles(g.id)],
            "derniere_selection": d, "themes": THEMES, "difficultes": list(DIFFICULTES),
            "statuts": list(STATUTS_QUESTION), "exigence": EXIGENCE,
            "limites": {"question": [QUESTION_MIN, QUESTION_MAX], "reponse": REPONSE_MAX, "variantes": VARIANTES_MAX,
                        "variante": VARIANTE_MAX, "theme": THEME_MAX, "section": SECTION_MAX, "extrait": EXTRAIT_MAX,
                        "url": URL_MAX, "par_envoi": PAR_ENVOI, "par_page": PAR_PAGE, "banque": BANQUE_MAX,
                        "liens": LIENS_MAX, "lien_titre": LIEN_TITRE_MAX, "lien_description": LIEN_DESC_MAX,
                        "modeles": MODELES_MAX, "modele_nom": MODELE_NOM_MAX, "note": NOTE_MAX},
            #  La dernière modification (stable d'une lecture à l'autre : l'empreinte ETag de la page reste valable).
            "maj": max([int(q["maj_le"] or 0) for q in qs] + [r["maj_le"]], default=0)}


async def _question_par_id(g, qid: str) -> dict | None:
    r = await _un(f"SELECT {', '.join(_COLS_Q)} FROM recrutement_questions WHERE guild_id=? AND id=?", (g.id, qid))
    return _question(r) if r is not None else None


async def enregistrer_question(g, auteur, corps) -> tuple[int, dict]:
    """Créer (sans `id`, ou avec un `id` neuf venu d'une page hors ligne) ou modifier (`id` + `version`)."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        qid = _ident_question(corps)
        theme = _theme(_texte(corps, "theme", mini=1, maxi=THEME_MAX))
        question = _texte(corps, "question", mini=QUESTION_MIN, maxi=QUESTION_MAX)
        reponse = _texte(corps, "reponse", mini=1, maxi=REPONSE_MAX)
        variantes = _variantes(corps.get("variantes", []), reponse)
        type_ = corps.get("type", "texte")
        if not isinstance(type_, str) or not FORMAT_TYPE.fullmatch(type_):
            raise _Invalide("« type » : quelques lettres minuscules (texte, nombre…).")
        difficulte = corps.get("difficulte", "moyenne")
        if difficulte not in DIFFICULTES:
            raise _Invalide("« difficulte » : facile, moyenne ou difficile.")
        source = _texte(corps, "source", maxi=URL_MAX, requis=False)
        if source and not FORMAT_URL.fullmatch(source):
            raise _Invalide("« source » : une adresse https://… (vidéo avec minutage, page du wiki).")
        section = _texte(corps, "section", maxi=SECTION_MAX, requis=False)
        extrait_ = _texte(corps, "extrait", maxi=EXTRAIT_MAX, requis=False, lignes=True)
        statut = corps.get("statut", "confirme")
        if statut not in STATUTS_QUESTION:
            raise _Invalide("« statut » : confirme ou a_verifier.")
        actif = _booleen(corps, "actif", True)
        version = _entier(corps, "version", requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    devoile = fuite(question, reponse, variantes)
    if devoile:
        return _erreur("La réponse attendue apparaît dans la question : reformule-la pour ne rien dévoiler.",
                       fuite=devoile)
    await _assurer(g.id)
    t = _maintenant()
    valeurs = (theme, question, reponse, json.dumps(variantes, ensure_ascii=False), type_, difficulte, source, section,
               extrait_, statut, int(bool(actif)))
    async with _get_db() as db:
        async with db.execute("SELECT version FROM recrutement_questions WHERE guild_id=? AND id=?",
                              (g.id, qid or "")) as cur:
            r = await cur.fetchone()
        if r is None:
            if version not in (None, 0):
                return _erreur("Cette question n'existe plus.", 404)
            async with db.execute("SELECT COUNT(*), COALESCE(MAX(ordre), -1) FROM recrutement_questions"
                                  " WHERE guild_id=?", (g.id,)) as cur:
                n, ordre = (int(x or 0) for x in await cur.fetchone())
            if n >= BANQUE_MAX:
                return _erreur(f"La banque est pleine ({BANQUE_MAX} questions) : retire d'anciennes questions.", 409)
            qid = qid or f"s-{secrets.token_hex(5)}"
            await db.execute(
                "INSERT INTO recrutement_questions (guild_id, id, theme, question, reponse, variantes, type, difficulte,"
                " source, section, extrait, statut, actif, ordre, origine, modifiee, cree_le, cree_par, maj_le, maj_par,"
                " version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'site',1,?,?,?,?,1)",
                (g.id, qid, *valeurs, ordre + 1, t, auteur.id, t, auteur.id))
            cree = True
        else:
            if version is None or int(version) != int(r[0]):
                await db.commit()
                actuelle = await _question_par_id(g, qid)
                return 409, {"conflit": True, "erreur": "Cette question a changé entre-temps.",
                             "actuelle": _question_site(g, actuelle)}
            await db.execute(
                "UPDATE recrutement_questions SET theme=?, question=?, reponse=?, variantes=?, type=?, difficulte=?,"
                " source=?, section=?, extrait=?, statut=?, actif=?, modifiee=1, maj_le=?, maj_par=?,"
                " version=version+1 WHERE guild_id=? AND id=?", (*valeurs, t, auteur.id, g.id, qid))
            cree = False
        await db.commit()
    return 200, {"ok": True, "cree": cree, "question": _question_site(g, await _question_par_id(g, qid))}


async def retirer_question(g, auteur, corps) -> tuple[int, dict]:
    """Retirée (jamais effacée : le fichier de départ ne la ressuscite pas) ; `restaurer: true` la remet."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        qid = _ident_question(corps, requis=True)
        restaurer = _booleen(corps, "restaurer", False)
    except _Invalide as ex:
        return _erreur(str(ex))
    await _assurer(g.id)
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_questions SET retiree=?, actif=?, modifiee=1, maj_le=?, maj_par=?,"
                               " version=version+1 WHERE guild_id=? AND id=?",
                               (int(not restaurer), int(bool(restaurer)), _maintenant(), auteur.id, g.id, qid))
        await db.commit()
    if (cur.rowcount or 0) < 1:
        return _erreur("Question introuvable.", 404)
    return 200, {"ok": True, "question": _question_site(g, await _question_par_id(g, qid))}


async def enregistrer_liens(g, auteur, corps) -> tuple[int, dict]:
    """La liste entière des liens (dans l'ordre), avec la `version` lue : une liste changée entre-temps → conflit."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    brut = corps.get("liens")
    try:
        version = _entier(corps, "version")
        if not isinstance(brut, list) or len(brut) > LIENS_MAX:
            raise _Invalide(f"« liens » : une liste de {LIENS_MAX} liens au plus.")
        propres, urls = [], set()
        for x in brut:
            if not isinstance(x, dict):
                raise _Invalide("Chaque lien est un objet {titre, url, description}.")
            titre = _texte(x, "titre", mini=1, maxi=LIEN_TITRE_MAX)
            url = _texte(x, "url", mini=10, maxi=URL_MAX)
            if not FORMAT_URL.fullmatch(url):
                raise _Invalide(f"« {titre} » : une adresse https://… est demandée.")
            if url.casefold() in urls:
                raise _Invalide(f"« {titre} » : ce lien est déjà dans la liste.")
            urls.add(url.casefold())
            lid = _ident_question(x) or f"l-{secrets.token_hex(5)}"
            propres.append({"id": lid, "titre": titre, "url": url,
                            "description": _texte(x, "description", maxi=LIEN_DESC_MAX, requis=False)})
        if len({x["id"] for x in propres}) != len(propres):
            raise _Invalide("Deux liens portent le même identifiant.")
    except _Invalide as ex:
        return _erreur(str(ex))
    await _assurer(g.id)
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_reglages SET liens_version=liens_version+1, liens_modifies=1,"
                               " maj_le=?, maj_par=? WHERE guild_id=? AND liens_version=?",
                               (_maintenant(), auteur.id, g.id, int(version)))
        if (cur.rowcount or 0) < 1:
            await db.commit()
            return 409, {"conflit": True, "erreur": "La liste des liens a changé entre-temps.",
                         "actuelle": {"liens": await liens(g.id), "version": (await reglages(g.id))["liens_version"]}}
        await db.execute("DELETE FROM recrutement_liens WHERE guild_id=?", (g.id,))
        for k, x in enumerate(propres):
            await db.execute("INSERT INTO recrutement_liens (guild_id, id, titre, url, description, ordre)"
                             " VALUES (?,?,?,?,?,?)", (g.id, x["id"], x["titre"], x["url"], x["description"], k))
        await db.commit()
    return 200, {"ok": True, "liens": await liens(g.id), "version": int(version) + 1}


async def enregistrer_reglages(g, auteur, corps) -> tuple[int, dict]:
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        nombre = _entier(corps, "nombre", mini=1, maxi=PAR_ENVOI)
        version = _entier(corps, "version")
    except _Invalide as ex:
        return _erreur(str(ex))
    await _assurer(g.id)
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_reglages SET nombre=?, version=version+1, maj_le=?, maj_par=?"
                               " WHERE guild_id=? AND version=?", (nombre, _maintenant(), auteur.id, g.id, version))
        await db.commit()
    r = await reglages(g.id)
    actuels = {"nombre": r["nombre"], "version": r["version"], "annonce": await annonce(g.id)}
    if (cur.rowcount or 0) < 1:
        return 409, {"conflit": True, "erreur": "Les réglages ont changé entre-temps.", "actuelle": actuels}
    return 200, {"ok": True, "reglages": actuels}


async def enregistrer_modele(g, auteur, corps) -> tuple[int, dict]:
    """Une sélection enregistrée (« modèle ») : créer (sans `id`, ou avec un `id` neuf) ou modifier (`id` + `version`).
    Un seul modèle par défaut : c'est la sélection de « Envoyer le questionnaire » et de l'étape 2 sans choix."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        mid = _ident_question(corps)
        nom = _texte(corps, "nom", mini=1, maxi=MODELE_NOM_MAX)
        ids = _ids(corps.get("questions"))
        if not 1 <= len(ids) <= PAR_ENVOI:
            raise _Invalide(f"Un modèle a de 1 à {PAR_ENVOI} questions.")
        if len(set(ids)) != len(ids):
            raise _Invalide("Une question est en double dans ce modèle.")
        par_defaut = _booleen(corps, "par_defaut", None)
        version = _entier(corps, "version", requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    connues = {q["id"] for q in await questions(g.id)}
    inconnues = [x for x in ids if x not in connues]
    if inconnues:
        return _erreur("Des questions de ce modèle n'existent pas dans la banque.", inconnues=inconnues)
    t = _maintenant()
    async with _get_db() as db:
        async with db.execute("SELECT version, par_defaut FROM recrutement_modeles WHERE guild_id=? AND id=?",
                              (g.id, mid or "")) as cur:
            r = await cur.fetchone()
        if r is None:
            if version not in (None, 0):
                return _erreur("Ce modèle n'existe plus.", 404)
            async with db.execute("SELECT COUNT(*) FROM recrutement_modeles WHERE guild_id=?", (g.id,)) as cur:
                n = int((await cur.fetchone())[0] or 0)
            if n >= MODELES_MAX:
                return _erreur(f"{MODELES_MAX} modèles au plus : retire-en un.", 409)
            mid, defaut = mid or f"m-{secrets.token_hex(5)}", bool(par_defaut)
            if defaut:
                await db.execute("UPDATE recrutement_modeles SET par_defaut=0, version=version+1 WHERE guild_id=?"
                                 " AND par_defaut=1", (g.id,))
            await db.execute("INSERT INTO recrutement_modeles (guild_id, id, nom, questions, par_defaut, cree_le,"
                             " cree_par, maj_le, maj_par, version) VALUES (?,?,?,?,?,?,?,?,?,1)",
                             (g.id, mid, nom, json.dumps(ids), int(defaut), t, auteur.id, t, auteur.id))
            cree = True
        else:
            if version is None or int(version) != int(r[0]):
                await db.commit()
                par_id = {q["id"]: q for q in await questions(g.id)}
                actuel = next((m for m in await modeles(g.id) if m["id"] == mid), None)
                return 409, {"conflit": True, "erreur": "Ce modèle a changé entre-temps.",
                             "actuelle": _modele_site(g, actuel, par_id) if actuel else None}
            defaut = bool(r[1]) if par_defaut is None else bool(par_defaut)
            if defaut and not r[1]:
                await db.execute("UPDATE recrutement_modeles SET par_defaut=0, version=version+1 WHERE guild_id=?"
                                 " AND par_defaut=1", (g.id,))
            await db.execute("UPDATE recrutement_modeles SET nom=?, questions=?, par_defaut=?, maj_le=?, maj_par=?,"
                             " version=version+1 WHERE guild_id=? AND id=?",
                             (nom, json.dumps(ids), int(defaut), t, auteur.id, g.id, mid))
            cree = False
        await db.commit()
    par_id = {q["id"]: q for q in await questions(g.id)}
    m = next(x for x in await modeles(g.id) if x["id"] == mid)
    return 200, {"ok": True, "cree": cree, "modele": _modele_site(g, m, par_id), "annonce": await annonce(g.id)}


async def retirer_modele(g, auteur, corps) -> tuple[int, dict]:
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        mid = _ident_question(corps, requis=True)
    except _Invalide as ex:
        return _erreur(str(ex))
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM recrutement_modeles WHERE guild_id=? AND id=?", (g.id, mid))
        await db.commit()
    if (cur.rowcount or 0) < 1:
        return _erreur("Ce modèle n'existe plus.", 404)
    return 200, {"ok": True, "annonce": await annonce(g.id)}


def _indications(qs: list, reps: dict) -> dict:
    return {int(q["rang"]): indication(reps[int(q["rang"])]["texte"], q.get("reponse", ""), q.get("variantes") or (),
                                       q.get("type") or "texte")
            for q in qs if int(q["rang"]) in reps}


async def _envoi_site(g, e: dict) -> dict:
    reps, corr = await _reponses(e["id"]), await _corrections(e["id"])
    ind = await asyncio.to_thread(_indications, e["questions"], reps)
    qs = []
    for q in e["questions"]:
        rang = int(q["rang"])
        c = corr.get(rang)
        qs.append(dict({k: v for k, v in q.items() if k != "reponse"}, attendue=q.get("reponse", ""),
                       reponse_candidat=(reps.get(rang) or {}).get("texte"),
                       recu_le=(reps.get(rang) or {}).get("recu_le", 0), indication=ind.get(rang),
                       correction=None if c is None else dict(c, par=_qui(g, c["par"]))))
    return {"id": e["id"], "statut": e["statut"], "origine": e["origine"], "renvoi": e["renvoi"],
            "envoye_par": _qui(g, e["envoye_par"]),
            "envoye_le": e["envoye_le"], "repondu_le": e["repondu_le"], "nb": len(e["questions"]),
            "pages": nb_pages(len(e["questions"])), "liens": e["liens"], "questions": qs,
            "bilan": bilan(e["questions"], reps, corr),
            "carte": _lien_discord(g, e["salon_id"], e["messages"][0] if e["messages"] else 0)}


async def dossier(g, tid: int) -> dict | None:
    """Tout ce que le site montre d'une candidature : l'étape, les réponses de l'étape 1, chaque envoi (questions,
    réponses, réponses attendues, variantes, indications, corrections), les décisions, les liens Discord."""
    rows = await _lire_tolerant("SELECT id, channel_id, user_id, panel_id, status, answers, created_at FROM tickets"
                                " WHERE id=? AND guild_id=?", (int(tid), g.id))
    s = await _suivi(g.id, tid)
    if not rows and s is None:
        return None
    tk = tuple(rows[0]) if rows else None
    if tk is not None and s is None and str(tk[3] or "") not in _panneaux(await _cfg(g.id)):
        return None
    candidat = int(tk[2]) if tk else int(s["candidat_id"])
    ouvert = bool(tk and tk[4] == "open")
    try:
        etape1 = json.loads(tk[5] or "{}") if tk else {}
    except ValueError:
        etape1 = {}
    etape = s["etape"] if s else ("etape1" if ouvert else "ferme")
    if not ouvert and etape in OUVERTES:
        #  Fermé sans passer par ce module (l'ancienne carte, la fermeture à la main, l'inactivité) : la décision
        #  enregistrée à la clôture par le suivi des candidatures fait foi.
        r = await _lire_tolerant("SELECT decision, raison FROM recrutements WHERE guild_id=? AND ticket_id=?",
                                 (g.id, int(tid)))
        prise = recrutements.decision(False, str(r[0][1] or ""), str(r[0][0] or "")) if r else None
        etape = {"acceptes": "accepte", "refuses": "refuse"}.get(prise, "ferme")
    envois = [await _envoi_site(g, e) for e in await _envois_du_ticket(g.id, tid)]
    hist = await _lire("SELECT quand, quoi, par, detail FROM recrutement_historique WHERE guild_id=? AND ticket_id=?"
                       " ORDER BY id", (g.id, int(tid)))
    salon = int(tk[1]) if tk else int(s["salon_id"] if s else 0)
    courant = int(s["envoi_id"]) if s else 0
    fermeture = bool(s and s["fermeture_le"])
    return {"ticket": int(tid), "statut_ticket": "ouvert" if ouvert else "ferme", "candidat": _ident(g, candidat),
            "etape": etape, "annonce": int(s["annonce"]) if s else 0,
            "ouvert_le": recrutements._unix(tk[6]) if tk else (s["cree_le"] if s else 0),
            "etape1": {"reponses": recrutements.garder(etape1 if isinstance(etape1, dict) else {})},
            "envois": envois, "envoi_courant": courant, "fermeture_prevue": fermeture,
            "decisions": [{"quand": int(h[0]), "quoi": h[1], "par": _qui(g, h[2]), "detail": h[3]} for h in hist],
            "liens_discord": {"ticket": _lien_discord(g, salon) if ouvert else "",
                              "carte_etape1": _lien_discord(g, salon, s["carte_id"]) if ouvert and s and s["carte_id"]
                              else ""},
            "exigence": EXIGENCE,
            "peut": {"etape1": ouvert and etape == "etape1" and not fermeture,
                     "corriger": etape not in FINALES and any(e["statut"] == "repondu" for e in envois),
                     "accepter": ouvert and etape in OUVERTES and not fermeture,
                     "refuser": ouvert and etape in ("etape2", "reponses") and not fermeture,
                     "renvoyer": ouvert and etape in ("etape2", "reponses") and not fermeture}}


async def suivi(g) -> dict:
    """Les candidatures ouvertes (et celles décidées depuis 30 jours) avec leur étape : la liste du site."""
    pids = sorted(_panneaux(await _cfg(g.id)))
    tickets = []
    if pids:
        tickets = await _lire_tolerant(f"SELECT id, user_id, channel_id, created_at FROM tickets WHERE guild_id=? AND"
                                       f" status='open' AND panel_id IN ({','.join('?' * len(pids))}) ORDER BY id",
                                       (g.id, *pids))
    suivis = {int(r[0]): dict(zip(_COLS_S, tuple(r))) for r in
              await _lire(f"SELECT {', '.join(_COLS_S)} FROM recrutement_suivi WHERE guild_id=?", (g.id,))}
    ouverts = []
    for tid, uid, salon, cree in tickets:
        s = suivis.get(int(tid))
        e = await _envoi(s["envoi_id"]) if s and s["envoi_id"] else None
        resume = None
        if e is not None:
            resume = {"id": e["id"], "nb": len(e["questions"]), "statut": e["statut"], "envoye_le": e["envoye_le"],
                      "repondu_le": e["repondu_le"],
                      "bilan": bilan(e["questions"], await _reponses(e["id"]), await _corrections(e["id"]))}
        ouverts.append({"ticket": int(tid), "candidat": _ident(g, int(uid)), "ouvert": recrutements._unix(cree),
                        "etape": s["etape"] if s else "etape1", "annonce": int(s["annonce"]) if s else 0,
                        "fermeture_prevue": bool(s and s["fermeture_le"]), "salon": _lien_discord(g, int(salon)),
                        "envoi": resume})
    ouverts_ids = {o["ticket"] for o in ouverts}
    limite = _maintenant() - 30 * 86400
    recents = sorted(({"ticket": tid, "candidat": _ident(g, s["candidat_id"]), "etape": s["etape"],
                       "maj_le": int(s["maj_le"] or 0)}
                      for tid, s in suivis.items() if tid not in ouverts_ids and int(s["maj_le"] or 0) >= limite),
                     key=lambda x: -x["maj_le"])[:50]
    return {"ouverts": ouverts, "recents": recents, "exigence": EXIGENCE}


async def corriger(g, auteur, corps) -> tuple[int, dict]:
    """« juste » / « faux » (ou null : à revoir) sur UNE réponse, avec qui et quand. Le site ne décide rien : c'est la
    personne qui coche. `version` (facultative) : celle lue — une correction changée entre-temps → conflit."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        eid = _entier(corps, "envoi", mini=1)
        qid = _ident_question(corps, "question", requis=True)
        if "juste" not in corps or corps["juste"] not in (True, False, None):
            raise _Invalide("« juste » : true, false ou null.")
        juste = corps["juste"]
        version = _entier(corps, "version", requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    e = await _envoi(eid)
    if e is None or e["guild_id"] != g.id:
        return _erreur("Questionnaire introuvable.", 404)
    rang = next((int(q["rang"]) for q in e["questions"] if str(q.get("id")) == qid), None)
    if rang is None:
        return _erreur("Cette question ne fait pas partie de ce questionnaire.", 404)
    reps = await _reponses(eid)
    if rang not in reps:
        return _erreur("Le candidat n'a pas encore répondu à cette question.", 409)
    s = await _suivi(g.id, e["ticket_id"])
    if s is not None and s["etape"] in FINALES:
        return _erreur("La décision est prise : la correction est figée.", 409, etape=s["etape"])
    t = _maintenant()
    async with _get_db() as db:
        async with db.execute("SELECT version FROM recrutement_corrections WHERE envoi_id=? AND rang=?",
                              (eid, rang)) as cur:
            r = await cur.fetchone()
        actuelle = int(r[0]) if r else 0
        if version is not None and int(version) != actuelle:
            await db.commit()
            c = (await _corrections(eid)).get(rang)
            return 409, {"conflit": True, "erreur": "Cette correction a changé entre-temps.",
                         "actuelle": None if c is None else dict(c, par=_qui(g, c["par"]))}
        valeur = None if juste is None else int(bool(juste))
        if r is None:
            await db.execute("INSERT INTO recrutement_corrections (envoi_id, rang, juste, par, le, version)"
                             " VALUES (?,?,?,?,?,1)", (eid, rang, valeur, auteur.id, t))
        else:
            await db.execute("UPDATE recrutement_corrections SET juste=?, par=?, le=?, version=version+1"
                             " WHERE envoi_id=? AND rang=?", (valeur, auteur.id, t, eid, rang))
        await db.commit()
    corr = await _corrections(eid)
    c = corr[rang]
    return 200, {"ok": True, "correction": dict(c, par=_qui(g, c["par"]), question=qid, rang=rang),
                 "bilan": bilan(e["questions"], reps, corr)}


# ─── Les adresses du site (`tableau.monter`) : fn(g, auteur, requete, corps) → (statut, corps) ─────────────────

def _ticket_requis(source: dict, cle: str = "ticket") -> int:
    return _entier(source, cle, mini=1, maxi=10 ** 12)


async def _r_banque(g, auteur, requete, corps):
    return 200, await banque(g)


async def _r_modeles(g, auteur, requete, corps):
    par_id = {q["id"]: q for q in await questions(g.id)}
    return 200, {"modeles": [_modele_site(g, m, par_id) for m in await modeles(g.id)], "annonce": await annonce(g.id)}


def _avec_journal(status: int, rep: dict, texte) -> tuple:
    """La phrase du journal du site pour une écriture réussie (`_journal`, retirée de la réponse par le registre de
    tableau.py ; None : rien à noter — la décision est déjà au journal du clan)."""
    if status < 400:
        rep["_journal"] = texte if texte is None else {"texte": texte}
    return status, rep


async def _r_question(g, auteur, requete, corps):
    st, rep = await enregistrer_question(g, auteur, corps)
    q = rep.get("question") or {}
    return _avec_journal(st, rep, f"Recrutement : question « {extrait(q.get('question'), 80)} » "
                                  + ("ajoutée" if rep.get("cree") else "modifiée"))


async def _r_question_retirer(g, auteur, requete, corps):
    st, rep = await retirer_question(g, auteur, corps)
    q = rep.get("question") or {}
    return _avec_journal(st, rep, f"Recrutement : question « {extrait(q.get('question'), 80)} » "
                                  + ("retirée" if q.get("retiree") else "remise dans la banque"))


async def _r_liens(g, auteur, requete, corps):
    st, rep = await enregistrer_liens(g, auteur, corps)
    return _avec_journal(st, rep, f"Recrutement : liens des réponses enregistrés ({len(rep.get('liens') or [])})")


async def _r_reglages(g, auteur, requete, corps):
    st, rep = await enregistrer_reglages(g, auteur, corps)
    n = (rep.get("reglages") or {}).get("nombre")
    return _avec_journal(st, rep, f"Recrutement : {n} question(s) par défaut à l'étape 2")


async def _r_modele(g, auteur, requete, corps):
    st, rep = await enregistrer_modele(g, auteur, corps)
    m = rep.get("modele") or {}
    return _avec_journal(st, rep, f"Recrutement : modèle « {m.get('nom', '')} » "
                                  + ("créé" if rep.get("cree") else "modifié")
                                  + (" (sélection par défaut)" if m.get("par_defaut") else ""))


async def _r_modele_retirer(g, auteur, requete, corps):
    st, rep = await retirer_modele(g, auteur, corps)
    return _avec_journal(st, rep, "Recrutement : un modèle de questionnaire retiré")


async def _r_dossier(g, auteur, requete, corps):
    try:
        tid = _ticket_requis(dict(requete or {}))
    except _Invalide as ex:
        return _erreur(str(ex))
    d = await dossier(g, tid)
    return (200, d) if d is not None else _erreur("Candidature introuvable.", 404)


async def _r_suivi(g, auteur, requete, corps):
    return 200, await suivi(g)


async def _r_etape1(g, auteur, requete, corps):
    corps = corps if isinstance(corps, dict) else {}
    try:
        tid = _ticket_requis(corps)
        note = _texte(corps, "note", maxi=NOTE_MAX, requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    if corps.get("decision") == "refuser":
        return _avec_journal(*await refuser(g, tid, auteur, depuis="etape1", note=note), None)
    if corps.get("decision") == "etape2":
        return _avec_journal(*await envoyer(g, tid, auteur, corps, depuis="etape1"), None)
    return _erreur("« decision » : « refuser » ou « etape2 ».")


async def _r_corriger(g, auteur, requete, corps):
    #  Qui a coché quoi, et quand, est gardé avec chaque correction (le dossier le montre) : pas une ligne de
    #  journal par réponse corrigée.
    st, rep = await corriger(g, auteur, corps)
    return _avec_journal(st, rep, None)


async def _r_decision(g, auteur, requete, corps):
    corps = corps if isinstance(corps, dict) else {}
    try:
        tid = _ticket_requis(corps)
        motif = _texte(corps, "motif", maxi=NOTE_MAX, requis=False)
        forcer = _booleen(corps, "forcer", False)
    except _Invalide as ex:
        return _erreur(str(ex))
    decision = corps.get("decision")
    if decision == "accepter":
        return _avec_journal(*await accepter(g, tid, auteur, forcer=bool(forcer)), None)
    if decision == "refuser":
        return _avec_journal(*await refuser(g, tid, auteur, depuis="final", note=motif), None)
    if decision == "renvoyer":
        return _avec_journal(*await envoyer(g, tid, auteur, corps, depuis="renvoi"), None)
    return _erreur("« decision » : « accepter », « refuser » ou « renvoyer ».")


def _route(methode: str, fn, *, hors_ligne: bool = False, corps_max: int = 16 * 1024, grave=None) -> dict:
    return {"methode": methode, "fn": fn, "ecriture": methode == "POST", "hors_ligne": hors_ligne,
            "corps_max": corps_max, "grave": grave}


ROUTES_SITE = {
    "recrutement/banque": _route("GET", _r_banque, corps_max=0),
    "recrutement/modeles": _route("GET", _r_modeles, corps_max=0),
    "recrutement/suivi": _route("GET", _r_suivi, corps_max=0),
    "recrutement/dossier": _route("GET", _r_dossier, corps_max=0),
    "recrutement/question": _route("POST", _r_question, hors_ligne=True),
    "recrutement/question/retirer": _route("POST", _r_question_retirer, hors_ligne=True, corps_max=2048),
    "recrutement/liens": _route("POST", _r_liens, hors_ligne=True),
    "recrutement/reglages": _route("POST", _r_reglages, hors_ligne=True, corps_max=2048),
    "recrutement/modele": _route("POST", _r_modele, hors_ligne=True, corps_max=8192),
    "recrutement/modele/retirer": _route("POST", _r_modele_retirer, hors_ligne=True, corps_max=2048),
    "recrutement/corriger": _route("POST", _r_corriger, hors_ligne=True, corps_max=2048),
    "recrutement/etape1": _route("POST", _r_etape1, corps_max=8192),
    #  Accepter donne le rôle du clan : compté avec les actions graves « roles » du site.
    "recrutement/decision": _route("POST", _r_decision, corps_max=8192, grave="roles"),
}
