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

LE TICKET PROPRE ET LE PARCOURS RÉGLABLE (26/10/2026). Le fondateur : « Ça envoie énormément de messages dans le
ticket… je veux vraiment que tout soit configurable… on peut mettre le nombre d'étapes que l'on souhaite… Tu fais une
vraie affiche dans le ticket… Il est complètement automatique. »
  · UN message à l'ouverture : l'AFFICHE (bannière, le candidat mentionné sans le prévenir, aucun numéro de ticket, les
    conditions, sa fiche, les consignes, « Répondre au questionnaire ») et, dans le même message, le panneau « Pour
    l'équipe » (sa décision, la prise en charge). Tout changement d'état RÉÉCRIT ce message ; le questionnaire (page web
    de l'équipe « candidature », sinon les formulaires Discord) et la décision en ajoutent un chacun, puis la fermeture.
  · Le PARCOURS de chaque panneau (`recrutement_parcours`, réglé sur le site — La Capitainerie › Demande de recrutement) :
    le mode (« approbation » : la direction approuve la demande et choisit les étapes de CE candidat ; « automatique » :
    le questionnaire part à l'ouverture ; « direct » : pas de questionnaire, décision sur la fiche), la FICHE (le
    formulaire d'ouverture, 5 champs au plus), le GABARIT des étapes du questionnaire (titre, consigne, questions : un
    modèle, des questions cochées, un tirage), l'exigence, le délai de fermeture, la liste noire au refus, la carte du
    métier. Sans réglage : le comportement d'avant (approbation, la sélection par défaut du serveur).
  · L'instantané d'un envoi porte ses étapes (`etapes` : [{numero, titre, consigne}]) et chaque question son `etape`
    (et `rang`, global et continu) ; un envoi sans `etapes` (les anciens) = une seule étape.
  · La décision : un message dans le ticket, un message PRIVÉ (accepté : rester actif ; refusé : il manque des
    connaissances), la liste noire des tickets de recrutement au refus (réglable), puis la fermeture — sans le MP de
    fermeture (la décision l'a déjà dit).
  · La LISTE NOIRE (`recrutement_liste_noire`) : qui, depuis quand, pourquoi, par qui ; levée une à une ou toutes ;
    écrite aussi dans la liste noire des panneaux (le contrôle d'ouverture du bot la lit).
  · Le NETTOYAGE : des règles réglables (rubrique « Nettoyage ») et la purge exceptionnelle des candidatures refusées
    (aperçu, puis confirmation forte).

CE QUI NE PART JAMAIS VERS DISCORD : la réponse attendue, les variantes, les sources, les extraits, les indications,
les corrections. Une question dont le texte contient sa réponse (ou une variante) n'est jamais posée — l'aperçu en
lecture seule de l'équipe (« Répondre » touché par la direction) ne les montre pas davantage.

LA BANQUE vient de `donnees_jeu/questionnaire_base.json` (la recherche sur le wiki) : on insère ce qui manque ; une
question jamais touchée sur le site suit le fichier ; une question modifiée ou retirée sur le site ne bouge plus.
Les liens (`donnees_jeu/questionnaire_liens.json`) : insérés tant que le site n'a pas réglé sa liste.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import importlib
import json
import os
import math
import random
import re
import secrets
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import discord

import diag
import recrutements
import textes as textes_du_site
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

#  Le parcours d'un panneau de recrutement (26/10/2026) : réglé sur le site, vérifié ici quoi que dise la page.
MODES = ("approbation", "automatique", "direct")
MODE_DEFAUT = "approbation"
ETAPES_MAX = 8                       # les étapes d'un questionnaire
ETAPE_TITRE_MAX, ETAPE_CONSIGNE_MAX = 80, 200
FICHE_MAX = 5                        # la fiche d'ouverture : une fenêtre Discord, 5 champs au plus
CHAMP_TITRE_MAX, CHAMP_AIDE_MAX, CHAMP_EXEMPLE_MAX = 45, 100, 100
CHAMP_LONGUEUR_MAX, CHAMP_LONGUEUR_DEFAUT = 1000, 300
OPTIONS_MAX, OPTION_MAX = 25, 100
TYPES_CHAMP = ("court", "long", "choix")
SOURCES_ETAPE = ("defaut", "modele", "questions", "tirage")
DELAI_MIN, DELAI_MAX = 5, 3600       # s : la fermeture après une décision
NOUVELLES_MAX = 10                   # questions écrites pour un seul candidat, par envoi
MOTIF_MAX = 150
CONFIRMATION_PURGE, CONFIRMATION_LEVER_TOUT = "PURGER", "LEVER"
TEXTE_AFFICHE = 3700                 # le texte d'une affiche (Discord : 4 000 par message, boutons compris)
BANNIERE = "recrutement_affiche.png"   # la bannière de l'affiche (`outils/affiche_recrutement.py`, servie par /v/)
#  Ce qu'un champ de la fiche ne demande pas (le site prévient) : une donnée sensible, ou inutile à la candidature.
#  « race » n'y est pas : les races de RELL Seas sont du jeu.
MOTS_SENSIBLES = (
    (r"sante|maladie|handicap|medic|traitement|allergi", "une donnée de santé"),
    (r"religion|croyance|politique|opinion|syndic", "une opinion ou une croyance"),
    (r"orientation|sexualit|genre_sex", "la vie intime"),
    (r"adresse|domicile|telephone|portable|numero_de_tel|e_?mail|courriel", "des coordonnées personnelles"),
    (r"mot_de_passe|password|mdp", "un mot de passe"),
    (r"naissance|anniversaire|ne_le|nee_le", "une date de naissance : demande plutôt une tranche d'âge"),
    (r"nom_de_famille|nom_complet|vrai_nom|identite|papier", "son identité civile"),
    (r"ecole|college|lycee|etablissement", "son établissement scolaire"),
    (r"photo|selfie|visage", "une photo de lui"),
    (r"bancaire|iban|paypal|carte_de_credit", "des données bancaires"),
    (r"pseudo_discord|nom_discord|tag_discord|identifiant_discord", "son pseudo Discord : le bot le connaît déjà"),
)

#  Les textes envoyés au candidat (FR · EN). Aucun ne dit juste ou faux. 26/10/2026 : chacun est DÉCLARÉ au registre
#  des textes (`textes.py`) — la direction le réécrit sur le site (Capitainerie → Textes & noms, ou là où on règle le
#  recrutement) et le bot emploie le sien dès l'enregistrement ; la constante garde le texte d'origine.
_declarer = functools.partial(textes_du_site.declarer, groupe="recrutement")
_AU_CANDIDAT, _AFFICHE, _ETAPE2, _BOUTONS = ("Les messages au candidat", "L'affiche du ticket",
                                             "Le questionnaire", "Les boutons et les formulaires")
_OUVERTURE, _DECISIONS, _APERCU = ("L'ouverture d'une demande", "Les décisions (ticket et message privé)",
                                   "L'aperçu de l'équipe (pour soi)")
REFUS_ETAPE1 = _declarer(
    "recrutement.refus_etape1",
    "Tes réponses ne correspondent pas à ce que nous attendons : ce ticket va être clôturé. Merci d'avoir créé un "
    "ticket.\n-# Your answers don't match what we are looking for: this ticket will be closed. Thank you for opening "
    "a ticket.", titre="Demande refusée (dans le ticket)", partie=_AU_CANDIDAT, ordre=1, max_=1500,
    aide="Posté dans le ticket quand la demande est refusée (sa fiche ne convient pas), juste avant la fermeture. Le "
         "candidat est mentionné au-dessus.")
REFUS_FINAL = _declarer(
    "recrutement.refus_final",
    "La direction a étudié ta candidature : elle n'est pas retenue. Ce ticket va être clôturé. Merci d'avoir créé un "
    "ticket.\n-# The leadership has reviewed your application: it was not accepted. This ticket will be closed. Thank "
    "you for opening a ticket.", titre="Candidature refusée (dans le ticket)", partie=_AU_CANDIDAT, ordre=2,
    max_=1500, aide="Posté dans le ticket quand la candidature est refusée, juste avant la fermeture.")
MERCI = _declarer(
    "recrutement.merci", "Merci, tes réponses sont transmises à la direction.\n-# Thank you, your answers have been "
    "sent to the leadership.", titre="Merci, après ses réponses", partie=_AU_CANDIDAT, ordre=3, max_=800,
    aide="Pour le candidat seul, quand il vient d'envoyer toutes ses réponses.")
DEJA = _declarer(
    "recrutement.deja", "Tes réponses sont déjà transmises à la direction.\n-# Your answers have already been sent to "
    "the leadership.", titre="Réponses déjà envoyées", partie=_AU_CANDIDAT, ordre=4, max_=800,
    aide="Pour le candidat seul, s'il rouvre un questionnaire auquel il a déjà répondu.")
SEUL_CANDIDAT = _declarer(
    "recrutement.seul_candidat", "Seul le candidat peut répondre à ce questionnaire.\n-# Only the applicant can answer "
    "this questionnaire.", titre="Un autre clique « Répondre »", partie=_AU_CANDIDAT, ordre=5, max_=800,
    aide="Pour la personne seule, quand quelqu'un d'autre que le candidat (et hors de l'équipe) touche « Répondre ».")
REMPLACE = _declarer(
    "recrutement.remplace", "Ce questionnaire n'est plus ouvert : réponds au plus récent, plus bas dans le ticket.\n-# "
    "This questionnaire is no longer open: answer the latest one, further down in the ticket.",
    titre="Un ancien questionnaire", partie=_AU_CANDIDAT, ordre=6, max_=800,
    aide="Pour le candidat seul, s'il répond à un questionnaire remplacé par un plus récent.")
INTROUVABLE = _declarer(
    "recrutement.introuvable", "Ce questionnaire n'existe plus.\n-# This questionnaire no longer exists.",
    titre="Questionnaire disparu", partie=_AU_CANDIDAT, ordre=7, max_=800,
    aide="Pour la personne seule, quand le questionnaire a été effacé.")
_declarer("recrutement.fermeture.acceptee", "Candidature acceptée", titre="Raison de fermeture : acceptée",
          partie=_AU_CANDIDAT, ordre=8, max_=200, lignes=False,
          aide="La raison lue dans l'annonce de fermeture du ticket.")
_declarer("recrutement.fermeture.refusee", "Candidature refusée", titre="Raison de fermeture : refusée",
          partie=_AU_CANDIDAT, ordre=9, max_=200, lignes=False,
          aide="La raison lue dans l'annonce de fermeture (le motif interne reste à l'équipe).")
_declarer("recrutement.wiki",
          "Toutes les réponses se trouvent sur le wiki : dans les pages ci-dessous, ou à un clic depuis elles.\n-# "
          "Every answer is on the wiki: in the pages below, or one click away from them.",
          titre="Où sont les réponses", partie=_AFFICHE, ordre=28, max_=500, requis=False,
          aide="Au-dessus des liens, sur l'affiche et dans le questionnaire. Vide : la phrase disparaît.")
_declarer("recrutement.liens.titre", "**Où trouver les réponses** · *Where to find the answers*",
          titre="Le titre des liens", partie=_AFFICHE, ordre=29, max_=150, lignes=False,
          aide="Au-dessus de la liste des liens donnés au candidat.")
#  L'affiche : le message unique du ticket (26/10/2026). Les nombres suivent le questionnaire réglé.
_ETAPES_V = (("etapes", "le nombre d'étapes (« 2 étapes »)"), ("questions", "le nombre de questions (« 12 questions »)"),
             ("etapes_en", "les étapes, en anglais (« 2 steps »)"), ("questions_en", "les questions, en anglais"))
_declarer("recrutement.affiche.titre", "## Avis de recrutement\n-# Clan GoRP · RELL Seas",
          titre="Le titre (sans la bannière)", partie=_AFFICHE, ordre=20, max_=200,
          aide="En tête de l'affiche quand la bannière ne peut pas s'afficher.")
_declarer("recrutement.affiche.intro",
          "{candidat}, bienvenue à bord : voici ta candidature, pas à pas.\n-# Welcome aboard: here is your "
          "application, step by step.", titre="Le mot d'accueil", partie=_AFFICHE, ordre=21, max_=600,
          variables=(("candidat", "le candidat (mentionné, sans notification)"),),
          aide="Sous la bannière. Le candidat est cité sans être prévenu.")
_declarer("recrutement.affiche.conditions",
          "**Pour rejoindre le clan**\n- Avoir l'âge requis par Discord (13 ans ou plus).\n- Jouer à RELL Seas et bien "
          "connaître le jeu.\n- Être actif et respectueux avec l'équipage.\n-# To join: be 13 or older, play and know "
          "RELL Seas, be active and respectful.", titre="Les conditions", partie=_AFFICHE, ordre=22, max_=900,
          requis=False, aide="Les conditions pour candidater, sur l'affiche. Vide : le bloc disparaît.")
_declarer("recrutement.affiche.fiche", "**Ta fiche** · *Your form*", titre="Le titre de sa fiche", partie=_AFFICHE,
          ordre=23, max_=120, lignes=False, aide="Au-dessus de ce qu'il a répondu en ouvrant le ticket.")
_declarer("recrutement.affiche.attente",
          "**La suite** · La direction lit ta fiche. Si elle convient, ton questionnaire arrive ici même : {etapes}, "
          "{questions}.\n-# Next: the leadership reads your form. If it fits, your quiz appears right here: "
          "{etapes_en}, {questions_en}.", titre="Consignes : la demande attend", partie=_AFFICHE, ordre=24,
          max_=900, variables=_ETAPES_V, aide="Tant que la direction n'a pas approuvé la demande.")
_declarer("recrutement.affiche.questionnaire",
          "**Ta demande est acceptée : réponds au questionnaire.** {etapes}, {questions}. Touche « Répondre au "
          "questionnaire » ; tu peux faire une pause, rien n'est perdu.\n-# Your request is accepted: answer the quiz "
          "({etapes_en}, {questions_en}). You can take a break, nothing is lost.",
          titre="Consignes : demande acceptée", partie=_AFFICHE, ordre=25, max_=900, variables=_ETAPES_V,
          aide="Quand la direction a approuvé la demande : le bouton « Répondre au questionnaire » est dessous.")
_declarer("recrutement.affiche.automatique",
          "**Ton questionnaire t'attend.** {etapes}, {questions}. Touche « Répondre au questionnaire » ; tu peux faire "
          "une pause, rien n'est perdu.\n-# Your quiz is waiting ({etapes_en}, {questions_en}). You can take a "
          "break, nothing is lost.", titre="Consignes : questionnaire dès l'ouverture", partie=_AFFICHE, ordre=26,
          max_=900, variables=_ETAPES_V, aide="Quand le questionnaire part tout seul à l'ouverture du ticket.")
_declarer("recrutement.affiche.reponses",
          "**Réponses envoyées** — {quand}. Merci : la direction les lit et te répond ici.\n-# Answers sent. Thank "
          "you: the leadership reads them and replies here.", titre="Consignes : réponses envoyées",
          partie=_AFFICHE, ordre=27, max_=600, variables=(("quand", "la date d'envoi"),),
          aide="Quand le candidat a répondu à tout.")
_declarer("recrutement.affiche.direct",
          "**La suite** · La direction lit ta fiche et te répond ici même.\n-# Next: the leadership reads your form "
          "and replies right here.", titre="Consignes : sans questionnaire", partie=_AFFICHE, ordre=30, max_=600,
          aide="Pour un panneau réglé sans questionnaire : la décision se prend sur la fiche.")
_declarer("recrutement.etape.entete", "**Étape {numero}** · *Step {numero}*", titre="Le titre d'une étape",
          partie=_ETAPE2, ordre=29, max_=120, lignes=False, variables=(("numero", "le numéro de l'étape"),),
          aide="Devant le titre de chaque étape du questionnaire (le titre choisi suit).")
_declarer("recrutement.etape2.titre", "## Le questionnaire — {nombre}\n-# The quiz — {nombre}",
          titre="Le titre du questionnaire", partie=_ETAPE2, ordre=30, max_=300,
          variables=(("nombre", "le nombre de questions (« 10 questions »)"),),
          aide="En tête du questionnaire posté dans le ticket (quand le candidat répond dans Discord).")
_declarer("recrutement.etape2.titre_renvoi",
          "## Nouveau questionnaire — {nombre}\n-# New quiz — {nombre}",
          titre="Le titre d'un nouveau questionnaire", partie=_ETAPE2, ordre=31, max_=300,
          variables=(("nombre", "le nombre de questions (« 10 questions »)"),),
          aide="Quand la direction renvoie d'autres questions à la place des premières.")
_declarer("recrutement.etape2.intro",
          "Réponds à chaque question avec tes propres mots.\n-# Answer each question in your own words.",
          titre="La consigne", partie=_ETAPE2, ordre=32, max_=600,
          aide="Sous le titre du questionnaire ; le candidat est mentionné juste devant.")
_declarer("recrutement.etape2.formulaires",
          "Tu réponds en {pages} formulaires de {par_page} questions au plus : chacun est gardé dès que tu l'envoies, "
          "tu peux faire une pause et reprendre avec « Répondre ».\n-# You answer in {pages} forms of up to {par_page} "
          "questions: each one is saved as soon as you send it; you can take a break and resume with \"Answer\".",
          titre="Plusieurs formulaires", partie=_ETAPE2, ordre=33, max_=600,
          variables=(("pages", "le nombre de formulaires"), ("par_page", "le nombre de questions par formulaire")),
          aide="Quand les questions tiennent en plusieurs formulaires (5 questions chacun).")
_declarer("recrutement.etape2.un_formulaire", "Tu réponds dans un seul formulaire.\n-# You answer in a single form.",
          titre="Un seul formulaire", partie=_ETAPE2, ordre=34, max_=400,
          aide="Quand toutes les questions tiennent dans un seul formulaire.")
_declarer("recrutement.formulaire.groupe", "**Formulaire {page}/{pages}** · *Form {page}/{pages}*",
          titre="Le titre de chaque formulaire", partie=_ETAPE2, ordre=35, max_=100, lignes=False,
          variables=(("page", "le numéro du formulaire"), ("pages", "le nombre de formulaires")),
          aide="Au-dessus de chaque groupe de questions, quand il y a plusieurs formulaires.")
_declarer("recrutement.etape2.pied",
          "-# La direction lit tes réponses : le résultat ne s'affiche pas ici. · The leadership reads your answers: "
          "the result isn't shown here.", titre="Le bas du questionnaire", partie=_ETAPE2, ordre=36, max_=400,
          aide="Sous les questions, juste au-dessus du bouton « Répondre ».")
_declarer("recrutement.etape2.suite", "## Le questionnaire — suite · The quiz — continued",
          titre="La suite du questionnaire", partie=_ETAPE2, ordre=37, max_=150,
          aide="En tête du message suivant, quand les questions ne tiennent pas dans un seul.")
_declarer("recrutement.etape2.envoyees",
          "**Réponses envoyées** · *Answers sent* — {quand}\n-# Merci : la direction les lit. · Thank you: the "
          "leadership reads them.", titre="Réponses envoyées (la carte)", partie=_ETAPE2, ordre=38, max_=400,
          variables=(("quand", "la date d'envoi"),),
          aide="Remplace le bouton « Répondre » quand le candidat a tout envoyé.")
_declarer("recrutement.etape2.remplace",
          "**Questionnaire remplacé** · *Questionnaire replaced*\n-# Les nouvelles questions sont plus bas dans le "
          "ticket. · The new questions are further down in the ticket.", titre="Questionnaire remplacé (la carte)",
          partie=_ETAPE2, ordre=39, max_=400, aide="Remplace le bouton quand un nouveau questionnaire est envoyé.")
_declarer("recrutement.etape2.clos", "**Questionnaire clos** · *Questionnaire closed*",
          titre="Questionnaire clos (la carte)", partie=_ETAPE2, ordre=40, max_=300,
          aide="Remplace le bouton quand la candidature est décidée avant ses réponses.")
_declarer("recrutement.etape2.invitation",
          "{candidat} **Ton questionnaire est prêt** : {etapes}, {questions}. Touche « Répondre au questionnaire ».\n-# "
          "Your quiz is ready: {etapes_en}, {questions_en}.", titre="L'invitation (un ancien ticket)",
          partie=_ETAPE2, ordre=41, max_=600,
          variables=(("candidat", "le candidat (mention, il est prévenu)"),) + _ETAPES_V,
          aide="Dans un ticket ouvert avant l'affiche, quand le questionnaire se remplit sur la page web.")
_declarer("recrutement.bouton.repondre", "Répondre · Answer", titre="Le bouton « Répondre »", partie=_BOUTONS,
          ordre=50, max_=80, lignes=False, aide="Sous le questionnaire posté dans le ticket : il ouvre le formulaire.")
_declarer("recrutement.bouton.questionnaire", "Répondre au questionnaire · Answer the quiz",
          titre="Le bouton « Répondre au questionnaire »", partie=_BOUTONS, ordre=49, max_=80, lignes=False,
          aide="Sur l'affiche : le candidat y répond (son lien personnel, ou les formulaires de Discord).")
_declarer("recrutement.bouton.continuer", "Continuer · page {page}/{pages}", titre="Le bouton « Continuer »",
          partie=_BOUTONS, ordre=51, max_=70, lignes=False,
          variables=(("page", "le formulaire suivant"), ("pages", "le nombre de formulaires")),
          aide="Après un formulaire envoyé, pour passer au suivant.")
_declarer("recrutement.formulaire.titre", "Étape {etape} · page {page}/{pages}", titre="Le titre du formulaire",
          partie=_BOUTONS, ordre=52, max_=40, lignes=False,
          variables=(("page", "le numéro du formulaire"), ("pages", "le nombre de formulaires"),
                     ("etape", "le numéro de l'étape")),
          aide="En haut de la fenêtre où le candidat écrit (45 caractères au plus sur Discord, variables comprises).")
_declarer("recrutement.formulaire.reponse", "Ta réponse · Your answer", titre="L'exemple dans chaque champ",
          partie=_BOUTONS, ordre=53, max_=100, lignes=False, aide="Le texte gris dans chaque champ de réponse.")
_declarer("recrutement.page_enregistree",
          "Page {page}/{pages} enregistrée. Continue avec la page {suivante}/{pages} — ou plus tard, avec « Répondre » "
          "sous les questions.\n-# Page {page}/{pages} saved. Continue with page {suivante}/{pages} — or later, with "
          "\"Answer\" under the questions.", titre="Un formulaire enregistré", partie=_BOUTONS, ordre=54, max_=800,
          variables=(("page", "le formulaire envoyé"), ("pages", "le nombre de formulaires"),
                     ("suivante", "le formulaire suivant")),
          aide="Pour le candidat seul, après chaque formulaire (sauf le dernier).")
_declarer("recrutement.reponse_manquante",
          "Chaque question demande une réponse : rouvre le formulaire avec « Répondre ».\n-# Every question needs an "
          "answer: open the form again with \"Answer\".", titre="Une réponse manque", partie=_BOUTONS, ordre=55,
          max_=600, aide="Pour le candidat seul, quand un champ est resté vide.")
_declarer("recrutement.lien_candidat",
          "Ton lien personnel pour répondre : il est à toi seul, ne le partage pas.\n-# Your personal link to answer: "
          "it's yours only, don't share it.", titre="Son lien personnel (pour lui)", partie=_BOUTONS, ordre=56,
          max_=600, aide="Pour le candidat seul, quand il touche « Répondre au questionnaire » (la page web).")
#  L'ouverture d'une demande : la confirmation (Oui / Non), l'information sur ses données, le refus d'un candidat sur
#  liste noire.
_declarer("recrutement.confirmation",
          "**Es-tu sûr de vouloir ouvrir une demande de recrutement ?**\nTu remplis ta fiche (quelques questions), puis la "
          "direction te répond dans ton ticket.\n-# Are you sure you want to open a recruitment request? Fill in your "
          "form, then the leadership replies in your ticket.", titre="La confirmation", partie=_OUVERTURE, ordre=60,
          max_=900,
          aide="Pour la personne seule, quand elle touche le panneau de recrutement : « Oui » ouvre sa fiche.")
_declarer("recrutement.confirmation.info",
          "-# Tes réponses servent seulement à ta candidature : elles sont gardées un an au plus et effacées sur simple "
          "demande à la direction. · Your answers are only used for your application: kept one year at most, deleted "
          "on request.", titre="L'information sur ses données", partie=_OUVERTURE, ordre=61, max_=600, requis=False,
          aide="Sous la confirmation : à quoi servent ses réponses, combien de temps elles sont gardées, comment les "
               "faire effacer.")
_declarer("recrutement.confirmation.oui", "Oui, ouvrir ma demande", titre="Le bouton « Oui »", partie=_OUVERTURE,
          ordre=62, max_=80, lignes=False, aide="Il ouvre la fiche (la fenêtre des premières questions).")
_declarer("recrutement.confirmation.non", "Non, annuler", titre="Le bouton « Non »", partie=_OUVERTURE, ordre=63,
          max_=80, lignes=False, aide="Rien n'est créé.")
_declarer("recrutement.confirmation.annule", "Annulé : aucun ticket n'est créé.\n-# Cancelled: no ticket was created.",
          titre="Après « Non »", partie=_OUVERTURE, ordre=64, max_=300, aide="Pour la personne seule.")
_declarer("recrutement.fiche.titre", "Ta fiche · Your form", titre="Le titre de la fiche", partie=_OUVERTURE,
          ordre=65, max_=45, lignes=False, aide="En haut de la fenêtre des premières questions (45 caractères au plus).")
LISTE_NOIRE_REFUS = _declarer(
    "recrutement.liste_noire.refus",
    "Tu ne peux plus ouvrir de demande de recrutement : ta candidature a déjà été étudiée. Si tu penses que c'est une "
    "erreur, écris à la direction.\n-# You can no longer open a recruitment request: your application was already "
    "reviewed.", titre="Un candidat sur liste noire", partie=_OUVERTURE, ordre=66, max_=900,
    aide="Pour la personne seule, si elle est sur la liste noire des tickets de recrutement : aucun ticket n'est créé.")
#  Les décisions : le message dans le ticket et le message privé.
_CANDIDAT_V = (("candidat", "le candidat (mention)"),)
_declarer("recrutement.decision.acceptee",
          "{candidat} **Bienvenue dans le clan !** Ta candidature est acceptée : le rôle du clan t'est donné. Ce ticket "
          "va se fermer.\n-# Welcome to the clan! Your application is accepted. This ticket will close.",
          titre="Acceptée (dans le ticket)", partie=_DECISIONS, ordre=100, max_=1200, variables=_CANDIDAT_V,
          aide="Posté dans le ticket à l'acceptation, juste avant la fermeture (avec le choix du métier, s'il est réglé).")
_declarer("recrutement.mp.acceptee",
          "**Tu es accepté dans le clan GoRP !** Bienvenue à bord.\nReste actif : le clan suit l'activité de chacun, et un "
          "membre absent trop longtemps est prévenu, puis retiré.\n-# You are accepted into the GoRP clan! Stay "
          "active: the clan follows everyone's activity.", titre="Acceptée (message privé)", partie=_DECISIONS,
          ordre=101, max_=1500, requis=False, aide="Envoyé en privé au candidat accepté. Vide : pas de message privé.")
_declarer("recrutement.mp.refusee",
          "Ta candidature au clan GoRP n'est pas retenue : il manque encore des connaissances sur le jeu et son univers. "
          "Merci d'avoir tenté ta chance.\n-# Your application to the GoRP clan was not accepted: some knowledge of the "
          "game is still missing. Thank you for trying.", titre="Refusée (message privé)", partie=_DECISIONS,
          ordre=102, max_=1500, requis=False, aide="Envoyé en privé au candidat refusé. Vide : pas de message privé.")
_declarer("recrutement.mp.demande_refusee",
          "Ta demande pour rejoindre le clan GoRP n'est pas retenue. Merci de l'intérêt que tu portes à l'équipage.\n-# "
          "Your request to join the GoRP clan was not accepted. Thank you for your interest.",
          titre="Demande refusée (message privé)", partie=_DECISIONS, ordre=103, max_=1500, requis=False,
          aide="Envoyé en privé quand la demande est refusée avant le questionnaire. Vide : pas de message privé.")
_declarer("recrutement.mp.liste_noire",
          "-# Tu ne pourras pas ouvrir de nouvelle demande de recrutement. · You won't be able to open a new "
          "recruitment request.", titre="La liste noire (ajouté au message privé)", partie=_DECISIONS, ordre=104,
          max_=400, requis=False, aide="Ajouté au message privé d'un refus quand le refus met sur liste noire.")
_declarer("recrutement.mp.questionnaire",
          "Ta demande de recrutement est acceptée : ton questionnaire t'attend dans ton ticket {ticket}.\n-# Your "
          "recruitment request is accepted: your quiz is waiting in your ticket.",
          titre="Demande acceptée (message privé)", partie=_DECISIONS, ordre=105, max_=800, requis=False,
          variables=(("ticket", "le lien de son ticket"),),
          aide="Envoyé en privé quand la direction approuve la demande (l'affiche du ticket, elle, est réécrite sans "
               "le prévenir). Vide : pas de message privé.")
#  La carte de l'équipe : le panneau « Pour l'équipe » de l'affiche (ou l'ancienne carte d'un ticket d'avant), ses
#  boutons, le formulaire du refus et le lien du site.
_EQUIPE = "Le panneau de l'équipe (dans le ticket)"
_PAR, _QUAND = ("par", "qui l'a fait (mention)"), ("quand", "il y a combien de temps (minuteur de Discord)")
_QUESTIONS = ("questions", "« **10 questions** », ou « le questionnaire » si le nombre n'est pas connu")
_declarer("recrutement.equipe.titre", "**Pour l'équipe** · fondateur, direction et recruteurs",
          titre="Le titre du panneau", partie=_EQUIPE, ordre=69, max_=200, lignes=False,
          aide="En tête du panneau de l'équipe, sous l'affiche (dans le même message).")
_declarer("recrutement.equipe.decision",
          "### La demande\nLis sa fiche, puis :\n- **Étape suivante** : l'étape 2 s'ouvre ({questionnaire}).\n- **Choisir "
          "sur le site** : ses étapes et ses questions, pour lui seul.\n- **Refuser la demande** : il reçoit un message "
          "privé, puis le ticket se ferme.\n-# Le candidat ne voit jamais les réponses attendues.",
          titre="La demande à décider", partie=_EQUIPE, ordre=70, max_=1500,
          variables=(("combien", "le nombre de questions et une virgule (« 10 questions, »), vide s'il n'est pas "
                                 "connu"),
                     ("questionnaire", "le questionnaire prévu (« 2 étapes, 12 questions »)")),
          aide="Tant que la demande attend : ses boutons sont réservés à l'équipe.")
_declarer("recrutement.equipe.envoye",
          "### Demande approuvée\nQuestionnaire envoyé par {par} {quand} : {questions}.\n-# Les réponses arrivent sur le "
          "site (Demande de recrutement) : c'est là qu'on les corrige.", titre="Demande approuvée",
          partie=_EQUIPE, ordre=71, max_=800, variables=(_PAR, _QUAND, _QUESTIONS),
          aide="Une fois le questionnaire envoyé par l'équipe.")
_declarer("recrutement.equipe.envoye_auto",
          "### Questionnaire envoyé à l'ouverture\n{questions}, parti tout seul {quand}.\n-# Les réponses arrivent sur le "
          "site (Demande de recrutement) : c'est là qu'on les corrige.", titre="Questionnaire parti tout seul",
          partie=_EQUIPE, ordre=72, max_=800, variables=(_QUESTIONS, _QUAND),
          aide="Pour un panneau réglé « automatique » : le questionnaire part à l'ouverture.")
_declarer("recrutement.equipe.reponses",
          "### Réponses reçues\n{candidat} a répondu à {questions} {quand}.\n-# À corriger sur le site : rien n'est jugé "
          "ici.", titre="Réponses reçues", partie=_EQUIPE, ordre=73, max_=800,
          variables=(("candidat", "le candidat (mention)"), _QUESTIONS, _QUAND),
          aide="Quand le candidat a répondu à tout.")
_declarer("recrutement.equipe.direct",
          "### La décision\nLis sa fiche ci-dessus, puis accepte ou refuse.\n-# Accepter donne le rôle du clan ; "
          "refuser lui envoie un message privé. Le ticket se ferme ensuite.", titre="Sans questionnaire : décider",
          partie=_EQUIPE, ordre=74, max_=1000, aide="Pour un panneau réglé sans questionnaire.")
_declarer("recrutement.equipe.accepte",
          "### Candidature acceptée\nPar {par} {quand} : rôle du clan donné, le ticket se ferme.",
          titre="Candidature acceptée", partie=_EQUIPE, ordre=75, max_=600, variables=(_PAR, _QUAND),
          aide="La candidature acceptée.")
_declarer("recrutement.equipe.refus_etape1",
          "### Demande refusée\nPar {par} {quand} : le message est posté, le ticket se ferme dans un instant.",
          titre="Demande refusée", partie=_EQUIPE, ordre=76, max_=600, variables=(_PAR, _QUAND),
          aide="La demande refusée avant le questionnaire.")
_declarer("recrutement.equipe.refuse",
          "### Candidature refusée\nPar {par} {quand} : le message est posté, le ticket se ferme dans un instant.",
          titre="Candidature refusée", partie=_EQUIPE, ordre=77, max_=600, variables=(_PAR, _QUAND),
          aide="La candidature refusée.")
for _k, (_cle, _defaut, _titre, _aide) in enumerate((
        ("envoyer", "Approuver la demande", "Le bouton « Approuver la demande »",
         "Le questionnaire prévu pour ce panneau part tout de suite."),
        ("site", "Choisir sur le site", "Le bouton « Choisir sur le site »",
         "Le lien personnel du site : ses étapes et ses questions, pour lui seul."),
        ("refuser", "Refuser la demande", "Le bouton « Refuser la demande »", "Il ouvre le formulaire du refus."),
        ("ouvrir", "Ouvrir sur le site", "Le bouton « Ouvrir sur le site »", "Une fois le questionnaire envoyé."),
        ("corriger", "Corriger sur le site", "Le bouton « Corriger sur le site »", "Une fois les réponses reçues."),
        ("fiche", "Ouvrir sa fiche sur le site", "Le bouton du lien personnel", "Sous le lien personnel du site."),
        ("accepter", "Accepter", "Le bouton « Accepter »", "Sans questionnaire : accepter sur sa fiche."),
        ("refuser_candidature", "Refuser la candidature", "Le bouton « Refuser la candidature »",
         "Sans questionnaire : refuser sur sa fiche."),
        ("confirmer", "Oui, accepter", "Le bouton « Oui, accepter »", "La confirmation de l'acceptation."))):
    _declarer(f"recrutement.equipe.bouton.{_cle}", _defaut, titre=_titre, partie=_EQUIPE, ordre=78 + _k, max_=80,
              lignes=False, aide=_aide)
_declarer("recrutement.equipe.refus.titre", "Refuser la demande", titre="Le formulaire du refus : son titre",
          partie=_EQUIPE, ordre=90, max_=45, lignes=False, aide="La fenêtre ouverte par « Refuser la demande ».")
_declarer("recrutement.equipe.refus.titre_candidature", "Refuser la candidature",
          titre="Le formulaire du refus (sans questionnaire)", partie=_EQUIPE, ordre=91, max_=45, lignes=False,
          aide="La fenêtre ouverte par « Refuser la candidature ».")
_declarer("recrutement.equipe.refus.note", "Note pour l'équipe (facultative)", titre="Le formulaire du refus : le champ",
          partie=_EQUIPE, ordre=92, max_=45, lignes=False, aide="Le nom du champ de la note.")
_declarer("recrutement.equipe.refus.note_aide", "Le candidat ne la voit pas : il lit le message automatique.",
          titre="Le formulaire du refus : sous le champ", partie=_EQUIPE, ordre=93, max_=100, lignes=False,
          requis=False, aide="La petite ligne sous le nom du champ. Vide : rien ne s'affiche.")
_declarer("recrutement.equipe.refus.exemple", "Pseudo Roblox invalide, réponses vides…",
          titre="Le formulaire du refus : l'exemple", partie=_EQUIPE, ordre=94, max_=100, lignes=False, requis=False,
          aide="Le texte gris dans le champ.")
_declarer("recrutement.equipe.lien",
          "Ton lien personnel : il ne s'ouvre qu'une fois, valable 24 h. Ne le partage pas.\n-# Sur le site : choisis "
          "ses étapes et ses questions (un modèle, la banque, ou des questions écrites pour lui), puis envoie.",
          titre="Le lien personnel (pour soi)", partie=_EQUIPE, ordre=95, max_=800,
          aide="Pour la personne seule, après « Choisir sur le site ».")
_declarer("recrutement.equipe.reserve", "Réservé au fondateur et à la direction.",
          titre="Réservé à la direction (pour soi)", partie=_EQUIPE, ordre=96, max_=400,
          aide="Quelqu'un d'autre touche « Direction » ou un bouton de décision (le candidat, par exemple) : un court "
               "avis pour lui seul.")
_declarer("recrutement.equipe.en_cours", "L'envoi du questionnaire est déjà en cours.",
          titre="Envoi déjà en cours (pour soi)", partie=_EQUIPE, ordre=97, max_=400,
          aide="Un second clic sur « Approuver la demande » pendant l'envoi.")
_declarer("recrutement.equipe.accepter.confirmation",
          "Accepter {candidat} ? Il reçoit le rôle du clan et un message privé, puis le ticket se ferme.",
          titre="La confirmation de l'acceptation (pour soi)", partie=_EQUIPE, ordre=98, max_=600,
          variables=(("candidat", "le candidat (mention)"),), aide="Après « Accepter » (sans questionnaire).")
_declarer("recrutement.equipe.pas_ici",
          "Cette décision se prend sur le site, après la correction des réponses (Demande de recrutement).",
          titre="Décision sur le site (pour soi)", partie=_EQUIPE, ordre=99, max_=400,
          aide="Quand quelqu'un veut accepter depuis Discord alors que le panneau a un questionnaire.")
_declarer("recrutement.equipe.automatique",
          "Ce panneau envoie le questionnaire tout seul, à l'ouverture.", titre="Panneau automatique (pour soi)",
          partie=_EQUIPE, ordre=100, max_=400, aide="« Approuver la demande » touché sur un panneau automatique.")
#  L'aperçu en lecture seule : la direction (ou un recruteur) touche « Répondre au questionnaire ».
_declarer("recrutement.apercu.titre",
          "### Aperçu · ce que voit {candidat}\n-# Lecture seule : seul le candidat répond. Les réponses attendues ne "
          "sont jamais ici.", titre="Le titre de l'aperçu", partie=_APERCU, ordre=110, max_=400,
          variables=(("candidat", "le candidat (mention)"),), aide="En tête de l'aperçu, pour soi seul.")
_declarer("recrutement.apercu.attente", "**En attente de ses réponses.**", titre="État : en attente",
          partie=_APERCU, ordre=111, max_=200, lignes=False, aide="Aucune réponse encore.")
_declarer("recrutement.apercu.en_cours", "**{repondues} réponse(s) sur {total} enregistrée(s)** — il continue.",
          titre="État : en cours", partie=_APERCU, ordre=112, max_=200, lignes=False,
          variables=(("repondues", "le nombre de réponses gardées"), ("total", "le nombre de questions")),
          aide="Une partie des pages est enregistrée.")
_declarer("recrutement.apercu.repondu", "**Réponses envoyées** {quand}.", titre="État : répondu", partie=_APERCU,
          ordre=113, max_=200, lignes=False, variables=(("quand", "la date d'envoi"),), aide="Tout est envoyé.")
_declarer("recrutement.apercu.clos", "**Questionnaire clos.**", titre="État : clos", partie=_APERCU, ordre=114,
          max_=200, lignes=False, aide="Remplacé, ou la candidature est décidée.")
_declarer("recrutement.apercu.sans_reponse", "-# pas encore de réponse", titre="Une question sans réponse",
          partie=_APERCU, ordre=115, max_=100, lignes=False, aide="Sous une question à laquelle il n'a pas répondu.")
_declarer("recrutement.bouton.apercu.precedente", "Étape précédente", titre="Le bouton « Étape précédente »",
          partie=_APERCU, ordre=116, max_=80, lignes=False, aide="Dans l'aperçu.")
_declarer("recrutement.bouton.apercu.suivante", "Étape suivante", titre="Le bouton « Étape suivante »",
          partie=_APERCU, ordre=117, max_=80, lignes=False, aide="Dans l'aperçu.")
#  Le passage d'étape (26/10/2026) : une étape à la fois — la direction ouvre la suivante ; sa fiche est l'étape 1.
_ETAPE_V = (("numero", "le numéro de l'étape, pour le candidat (sa fiche est l'étape 1)"),
            ("total", "le nombre d'étapes en tout"))
_PASSAGE = "Le passage d'étape"
_declarer("recrutement.affiche.fiche_recue",
          "**Étape 1 — ta fiche : reçue.** La direction la regarde ; si elle convient, l'étape suivante s'ouvre ici même.\n"
          "-# Step 1 — your form: received. The leadership is reviewing it; if it fits, the next step opens right here.",
          titre="L'affiche : sa fiche est reçue", partie=_PASSAGE, ordre=120, max_=900,
          aide="Sur l'affiche, tant que la direction n'a pas ouvert l'étape suivante.")
_declarer("recrutement.affiche.etape_ouverte",
          "**Étape {numero} sur {total} : à toi.** Réponds avec « Répondre au questionnaire », juste en dessous ; tu peux "
          "faire une pause, rien n'est perdu.\n-# Step {numero} of {total}: your turn. Answer with \"Answer the quiz\" "
          "just below; you can take a break, nothing is lost.", titre="L'affiche : une étape ouverte",
          partie=_PASSAGE, ordre=121, max_=900, variables=_ETAPE_V,
          aide="Sur l'affiche, quand une étape du questionnaire l'attend (le message de l'étape est juste dessous).")
_declarer("recrutement.affiche.etape_recue",
          "**Étape {numero} sur {total} : réponses reçues.** La direction les regarde ; la suite arrive ici même.\n-# Step "
          "{numero} of {total}: answers received. The leadership is reviewing them; what comes next appears right here.",
          titre="L'affiche : une étape reçue", partie=_PASSAGE, ordre=122, max_=900, variables=_ETAPE_V,
          aide="Sur l'affiche, quand il a envoyé une étape et attend la décision de la direction.")
_declarer("recrutement.etape.message",
          "{candidat} **Étape {numero} sur {total}** — {questions}. Touche « Répondre au questionnaire ».\n-# Step {numero} "
          "of {total} — {questions_en}. Tap \"Answer the quiz\".", titre="Le message de l'étape",
          partie=_PASSAGE, ordre=123, max_=900,
          variables=(("candidat", "le candidat (mention : il est prévenu)"),) + _ETAPE_V + (
              ("questions", "le nombre de questions de l'étape"), ("questions_en", "le même, en anglais")),
          aide="Posté quand une étape s'ouvre (il est prévenu) ; l'ancien message d'étape est supprimé : le ticket "
               "garde au plus deux messages du bot.")
_declarer("recrutement.etape.recue",
          "**Étape {numero} sur {total} — réponses reçues** · la direction les regarde.\n-# Step {numero} of {total} — "
          "answers received: the leadership is reviewing them.", titre="Le message de l'étape, une fois reçue",
          partie=_PASSAGE, ordre=124, max_=600, variables=_ETAPE_V,
          aide="Le message de l'étape réécrit (jamais doublé) quand il a envoyé ses réponses.")
_declarer("recrutement.etape.avis",
          "Étape {numero} envoyée : la direction regarde tes réponses. La suite arrive dans ton ticket.\n-# Step {numero} "
          "sent: the leadership is reviewing your answers. What comes next appears in your ticket.",
          titre="Une étape envoyée (pour lui)", partie=_PASSAGE, ordre=125, max_=600,
          variables=(("numero", "le numéro de l'étape envoyée"),),
          aide="Pour le candidat seul, quand il vient d'envoyer une étape (dans Discord).")
_declarer("recrutement.etape.fermee",
          "Cette étape n'est pas encore ouverte : la direction l'ouvre dans ton ticket quand elle a lu tes réponses.\n-# "
          "This step isn't open yet: the leadership opens it in your ticket once it has read your answers.",
          titre="Une étape pas encore ouverte (pour lui)", partie=_PASSAGE, ordre=126, max_=600,
          aide="Pour le candidat seul, s'il envoie un ancien formulaire d'une étape qui n'est pas encore ouverte.")
_declarer("recrutement.elimine",
          "Merci pour ta demande. Tes réponses ne correspondent pas aux conditions pour rejoindre le clan : aucune demande "
          "n'est ouverte.\n-# Thank you. Your answers don't meet the conditions to join the clan: no request was opened.",
          titre="Éliminé d'office (pour lui)", partie=_OUVERTURE, ordre=67, max_=900,
          aide="Pour la personne seule, quand une réponse de sa fiche est éliminatoire (une tranche d'âge, par exemple) : "
               "aucun ticket n'est créé, il reçoit aussi le message privé du refus de la demande.")
_declarer("recrutement.equipe.bouton.direction", "Direction", titre="Le bouton « Direction » (sur l'affiche)",
          partie=_EQUIPE, ordre=101, max_=80, lignes=False,
          aide="Le seul bouton de l'équipe sur l'affiche : il ouvre, pour la tête seule, le panneau de décision.")
_declarer("recrutement.equipe.bouton.suivante", "Étape suivante", titre="Le bouton « Étape suivante »",
          partie=_EQUIPE, ordre=102, max_=80, lignes=False,
          aide="Ouvre l'étape suivante du questionnaire (la première : la demande est approuvée).")
_declarer("recrutement.direction.titre",
          "### Direction · {candidat}\n-# Pour toi seul. Tout se fait aussi sur le site (Demande de recrutement).",
          titre="Le panneau de la direction : son titre", partie=_EQUIPE, ordre=103, max_=400,
          variables=(("candidat", "le candidat (mention)"),), aide="En tête du panneau ouvert par « Direction ».")
_declarer("recrutement.direction.etape_ouverte",
          "**Étape {numero} sur {total} : il répond.** Ouverte {quand}. La suite se décide quand il a envoyé ses réponses.",
          titre="Panneau : une étape ouverte", partie=_EQUIPE, ordre=104, max_=600,
          variables=_ETAPE_V + (_QUAND,), aide="Le candidat n'a pas encore envoyé l'étape ouverte.")
_declarer("recrutement.direction.etape_recue",
          "**Étape {numero} sur {total} : réponses reçues** {quand}. Regarde-les sur le site, puis ouvre l'étape suivante, "
          "ou refuse.", titre="Panneau : une étape reçue", partie=_EQUIPE, ordre=105, max_=600,
          variables=_ETAPE_V + (_QUAND,), aide="Il a envoyé l'étape ouverte : à toi de décider de la suite.")
_declarer("recrutement.direction.derniere",
          "**Toutes ses réponses sont là** {quand}. Corrige-les sur le site, puis accepte ou refuse.",
          titre="Panneau : tout est reçu", partie=_EQUIPE, ordre=106, max_=600, variables=(_QUAND,),
          aide="La dernière étape est envoyée : la correction, puis la décision.")
_declarer("recrutement.direction.pas_envoyee",
          "L'étape {numero} n'est pas encore envoyée par le candidat : attends ses réponses.",
          titre="Étape suivante trop tôt (pour soi)", partie=_EQUIPE, ordre=107, max_=400,
          variables=(("numero", "le numéro de l'étape ouverte"),),
          aide="« Étape suivante » touché alors que le candidat n'a pas encore répondu.")
_CHEFS = "Les chefs d'équipe (messages privés)"
_declarer("recrutement.chef.mp.accepte",
          "**Tu es nommé chef d'équipe · {metier} !** Toutes tes réponses étaient justes. Tu diriges maintenant ton "
          "équipe : la direction te contacte pour la suite.\n-# You are now a team leader · {metier}.",
          titre="Chef accepté (message privé)", partie=_CHEFS, ordre=130, max_=1500, requis=False,
          variables=(("metier", "son métier"),), aide="Envoyé en privé au membre accepté chef d'équipe. Vide : rien.")
_declarer("recrutement.chef.mp.refuse",
          "Ta candidature de chef d'équipe · {metier} n'est pas retenue pour le moment. Merci d'avoir répondu : continue "
          "à progresser avec l'équipage.\n-# Your team leader application was not accepted for now.",
          titre="Chef refusé (message privé)", partie=_CHEFS, ordre=131, max_=1500, requis=False,
          variables=(("metier", "son métier"),), aide="Envoyé en privé au membre refusé (il reste du clan). Vide : rien.")
_declarer("recrutement.chef.mp.attente",
          "Ta candidature de chef d'équipe · {metier} est en attente : la direction y revient bientôt.\n-# Your team "
          "leader application is on hold.", titre="Chef en attente (message privé)", partie=_CHEFS, ordre=132,
          max_=1500, requis=False, variables=(("metier", "son métier"),),
          aide="Envoyé en privé quand la direction met sa candidature en attente. Vide : pas de message privé.")


def _t(guild_id, cle: str, **valeurs) -> str:
    """Un texte que la direction peut réécrire (Capitainerie → Textes & noms) : le sien, sinon celui d'origine."""
    return textes_du_site.texte_cache(guild_id, cle, **valeurs)


def _questions_txt(n: int) -> tuple:
    """(« 10 questions », « 10-question ») : le nombre annoncé au candidat, en français et en anglais."""
    n = int(n or 0)
    return (f"{n} question{'s' if n > 1 else ''}", f"{n}-question") if n > 0 else ("quelques questions", "short")
_COINCE = "Quand quelque chose coince (pour la personne seule)"
DEMARRE = _declarer("recrutement.demarre", "Le bot démarre : réessaie dans un instant.\n-# The bot is starting: try "
                    "again in a moment.", titre="Le bot démarre", partie=_COINCE, ordre=90, max_=400,
                    aide="Un clic pendant le démarrage du bot.")
SOUCI = _declarer("recrutement.souci", "Un souci est survenu : réessaie dans quelques secondes.\n-# Something went "
                  "wrong: try again in a few seconds.", titre="Un souci", partie=_COINCE, ordre=91, max_=400,
                  aide="Une erreur imprévue (elle est aussi notée au journal du bot).")


def _gid(i) -> int:
    """Le serveur d'une interaction (0 hors serveur : les textes d'origine)."""
    return int(getattr(getattr(i, "guild", None), "id", 0) or 0)
RESERVE = textes_du_site.defaut("recrutement.equipe.reserve")
DISCORD_HS = "Discord ne répond pas : réessaie dans un instant."
FERME = "Ce ticket n'est plus ouvert."

_get_db = _cfg = _panneaux = _ticket_ouvert = _decider = _autorise = _lien = _journal = None
_extras = _liste_noire_cfg = _web_module = _metier = _est_tete = None
_clan = _metiers_liste = _metiers_membre = None
_web_absent = 0.0      # le module de la page web manque : on ne le recherche pas avant cette heure
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
          fichier_banque=None, fichier_liens=None, log=None, extras=None, liste_noire=None, web=None,
          metier=None, est_tete=None, clan=None, metiers=None, metiers_membre=None):
    """`panneaux(c)` → les panneaux de tickets du clan ; `ticket_ouvert(g, ticket)` → (salon, ticket) ou (None, None) ;
    `decider(g, ticket, auteur, accepte, motif, annonce=, mp=)` → (ok, message) — le circuit de décision du bot (rôle,
    `annonce()` juste avant la fermeture, fermeture sans le message privé de fermeture si `mp` est faux, transcript,
    suivi) ; `autorise(i)` → peut trancher l'étape 1 ; `lien(i)` → (lien personnel du site, refus) ;
    `journal(g, type_, texte, membre_id=, auteur_id=)` → le journal du site.
    26/10/2026 — facultatifs : `extras(g, ticket, pris_par)` → {contexte: [lignes], pris_par, boutons: [boutons du
    ticket]} (le bas du panneau de l'équipe, sur l'affiche) ; `liste_noire(g, membre_id | None, ajouter)` → bool (la
    liste noire des panneaux de recrutement, celle que lit le contrôle d'ouverture du bot ; None + False : la vider) ;
    `web` : le module de la page web du candidat (`candidature_site` : `lien_candidat(i, ticket)`, `inviter(g, e)`) —
    sinon il est cherché parmi les modules (un test peut l'injecter dans `sys.modules`) ; `metier(g, membre)` → (texte, lien) de l'invitation à choisir son
    métier, ou None ; `est_tete(membre)` → le fondateur ou la direction ; les chefs d'équipe : `clan(g)` → le rôle
    du clan, `metiers(g)` → [{cle, nom}] du catalogue, `metiers_membre(g, membre)` → les clés de ses métiers."""
    global _get_db, _cfg, _panneaux, _ticket_ouvert, _decider, _autorise, _lien, _journal, _log
    global _fichier_banque, _fichier_liens, _verrou_semis, _extras, _liste_noire_cfg, _web_module, _metier, _est_tete
    global _web_absent, _clan, _metiers_liste, _metiers_membre
    _get_db, _cfg, _panneaux, _ticket_ouvert = get_db, cfg, panneaux, ticket_ouvert
    _decider, _autorise, _lien, _journal = decider, autorise, lien, journal
    _extras, _liste_noire_cfg, _web_module, _metier, _est_tete = extras, liste_noire, web, metier, est_tete
    _web_absent = 0.0
    _clan, _metiers_liste, _metiers_membre = clan, metiers, metiers_membre
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
    " panneau TEXT NOT NULL DEFAULT '', carte TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT '',"
    " etapes_annonce INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, ticket_id))",
    "CREATE TABLE IF NOT EXISTS recrutement_envois (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
    " ticket_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL, questions TEXT NOT NULL, liens TEXT NOT NULL DEFAULT '[]',"
    " statut TEXT NOT NULL DEFAULT 'prepare', origine TEXT NOT NULL DEFAULT '', renvoi INTEGER NOT NULL DEFAULT 0, envoye_par INTEGER NOT NULL DEFAULT 0,"
    " cree_le INTEGER NOT NULL DEFAULT 0, envoye_le INTEGER NOT NULL DEFAULT 0, repondu_le INTEGER NOT NULL DEFAULT 0,"
    " salon_id INTEGER NOT NULL DEFAULT 0, messages TEXT NOT NULL DEFAULT '[]', etapes TEXT NOT NULL DEFAULT '[]',"
    " etape_ouverte INTEGER NOT NULL DEFAULT 0, etape_envoyee INTEGER NOT NULL DEFAULT 0,"
    " etape_fiche INTEGER NOT NULL DEFAULT 0, message_etape INTEGER NOT NULL DEFAULT 0,"
    " nature TEXT NOT NULL DEFAULT 'recrutement', metier TEXT NOT NULL DEFAULT '')",
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
    #  26/10/2026 : le parcours de chaque panneau de recrutement (réglé sur le site) et la liste noire des tickets de
    #  recrutement (qui, depuis quand, pourquoi, par qui ; une levée garde la ligne : l'historique de la décision).
    "CREATE TABLE IF NOT EXISTS recrutement_parcours (guild_id INTEGER NOT NULL, panneau TEXT NOT NULL,"
    " mode TEXT NOT NULL DEFAULT 'approbation', fiche TEXT NOT NULL DEFAULT '', gabarit TEXT NOT NULL DEFAULT '[]',"
    " exigence INTEGER NOT NULL DEFAULT 100, delai INTEGER NOT NULL DEFAULT 20, liste_noire INTEGER NOT NULL DEFAULT 1,"
    " metier INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1, maj_le INTEGER NOT NULL DEFAULT 0,"
    " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, panneau))",
    "CREATE TABLE IF NOT EXISTS recrutement_liste_noire (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL, nom TEXT NOT NULL DEFAULT '',"
    " depuis INTEGER NOT NULL DEFAULT 0, motif TEXT NOT NULL DEFAULT '', par INTEGER NOT NULL DEFAULT 0,"
    " ticket_id INTEGER NOT NULL DEFAULT 0, leve_le INTEGER NOT NULL DEFAULT 0, leve_par INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS idx_recrutement_liste_noire ON recrutement_liste_noire(guild_id, membre_id)",
    #  Une réponse éliminatoire dans la fiche : AUCUN ticket n'est créé — la décision « Éliminé d'office » est gardée ici.
    "CREATE TABLE IF NOT EXISTS recrutement_eliminations (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL, nom TEXT NOT NULL DEFAULT '', panneau TEXT NOT NULL DEFAULT '',"
    " champ TEXT NOT NULL DEFAULT '', reponse TEXT NOT NULL DEFAULT '', quand INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS idx_recrutement_eliminations ON recrutement_eliminations(guild_id, quand)",
    #  Les chefs d'équipe : leur banque À PART (jamais mêlée au recrutement), les gabarits par métier, les candidatures
    #  (sans ticket : l'envoi), les chefs validés, le rôle des chefs de chaque métier.
    "CREATE TABLE IF NOT EXISTS recrutement_chef_questions (guild_id INTEGER NOT NULL, id TEXT NOT NULL,"
    " metiers TEXT NOT NULL DEFAULT '[\"tous\"]', question TEXT NOT NULL, reponse TEXT NOT NULL,"
    " variantes TEXT NOT NULL DEFAULT '[]', actif INTEGER NOT NULL DEFAULT 1, retiree INTEGER NOT NULL DEFAULT 0,"
    " ordre INTEGER NOT NULL DEFAULT 0, cree_le INTEGER NOT NULL DEFAULT 0, cree_par INTEGER NOT NULL DEFAULT 0,"
    " maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1,"
    " PRIMARY KEY (guild_id, id))",
    "CREATE TABLE IF NOT EXISTS recrutement_chef_gabarits (guild_id INTEGER NOT NULL, metier TEXT NOT NULL,"
    " etapes TEXT NOT NULL DEFAULT '[]', version INTEGER NOT NULL DEFAULT 1, maj_le INTEGER NOT NULL DEFAULT 0,"
    " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, metier))",
    "CREATE TABLE IF NOT EXISTS recrutement_chef_candidatures (envoi_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,"
    " membre_id INTEGER NOT NULL, metier TEXT NOT NULL DEFAULT '', decision TEXT NOT NULL DEFAULT '',"
    " decide_par INTEGER NOT NULL DEFAULT 0, decide_le INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',"
    " cree_le INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS idx_recrutement_chef_candidatures ON recrutement_chef_candidatures(guild_id, membre_id)",
    "CREATE TABLE IF NOT EXISTS recrutement_chefs (guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
    " metier TEXT NOT NULL DEFAULT '', role_id INTEGER NOT NULL DEFAULT 0, accepte_le INTEGER NOT NULL DEFAULT 0,"
    " accepte_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, membre_id))",
    "CREATE TABLE IF NOT EXISTS recrutement_chef_roles (guild_id INTEGER NOT NULL, metier TEXT NOT NULL,"
    " role_id INTEGER NOT NULL, maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0,"
    " PRIMARY KEY (guild_id, metier))",
)
#  Les colonnes ajoutées le 26/10/2026 à des tables qui existaient déjà en production (une base d'avant les reçoit au
#  démarrage ; une base neuve les a dans son CREATE).
_COLONNES = {
    "recrutement_suivi": (("panneau", "TEXT NOT NULL DEFAULT ''"), ("carte", "TEXT NOT NULL DEFAULT ''"),
                          ("mode", "TEXT NOT NULL DEFAULT ''"), ("etapes_annonce", "INTEGER NOT NULL DEFAULT 0")),
    #  Le contrat « passage d'étape » (26/10/2026, commun avec l'équipe de la page du candidat) : une étape = une porte.
    #  `etape_ouverte` : la plus haute étape du questionnaire (1…N) que le candidat voit — 0 : un envoi d'avant, tout est
    #  ouvert et il répond en une fois ; `etape_envoyee` : la plus haute qu'il a envoyée ; `etape_fiche` : 1 si le
    #  panneau a une fiche (elle est l'« Étape 1 » du candidat, le questionnaire va de 2 à N+1) ; `message_etape` : le
    #  message de l'étape en cours dans le ticket.
    "recrutement_envois": (("etapes", "TEXT NOT NULL DEFAULT '[]'"), ("etape_ouverte", "INTEGER NOT NULL DEFAULT 0"),
                           ("etape_envoyee", "INTEGER NOT NULL DEFAULT 0"), ("etape_fiche", "INTEGER NOT NULL DEFAULT 0"),
                           ("message_etape", "INTEGER NOT NULL DEFAULT 0"),
                           #  Le contrat « chef d'équipe » : un envoi de chef (`nature` « chef », son `metier`, aucun ticket).
                           ("nature", "TEXT NOT NULL DEFAULT 'recrutement'"), ("metier", "TEXT NOT NULL DEFAULT ''")),
}


async def init_db():
    async with _get_db() as db:
        for sql in _SCHEMA:
            await db.execute(sql)
        for table, colonnes in _COLONNES.items():
            async with db.execute(f"PRAGMA table_info({table})") as cur:
                presentes = {r[1] for r in await cur.fetchall()}
            for nom, definition in colonnes:
                if nom not in presentes:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")
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
    """La sélection du dernier questionnaire envoyé sur ce serveur (« Reprendre la sélection précédente ») : ses
    questions de la banque (une question écrite pour un seul candidat n'en fait pas partie) et ses étapes."""
    r = await _un("SELECT id, ticket_id, candidat_id, questions, envoye_le, etapes FROM recrutement_envois"
                  " WHERE guild_id=? AND statut NOT IN ('prepare', 'annule') ORDER BY envoye_le DESC, id DESC LIMIT 1",
                  (int(guild_id),))
    if r is None:
        return None
    qs = [q for q in _json_liste(r[3]) if isinstance(q, dict) and not q.get("perso")]
    return {"envoi_id": int(r[0]), "ticket": int(r[1]), "candidat_id": str(r[2]),
            "questions": [str(q.get("id")) for q in qs], "envoye_le": int(r[4] or 0),
            "etape_de": [int(q.get("etape") or 1) for q in qs], "etapes": etapes_de({"etapes": r[5], "questions": qs})}


# ═══════════════════════════════════════════════════════════════════════════════
#  Le parcours d'un panneau de recrutement : le mode, la fiche, le gabarit des étapes, les décisions (26/10/2026)
# ═══════════════════════════════════════════════════════════════════════════════

_COLS_P = ("mode", "fiche", "gabarit", "exigence", "delai", "liste_noire", "metier", "version", "maj_le", "maj_par")


def _defauts(panneau) -> dict:
    """Le parcours d'un panneau jamais réglé : le comportement d'avant (la direction approuve la demande, la sélection
    par défaut du serveur, 100 % exigés, la carte du métier) ; nouveau : la liste noire au refus (le fondateur)."""
    return {"panneau": str(panneau or ""), "mode": MODE_DEFAUT, "fiche": None, "gabarit": [], "exigence": EXIGENCE,
            "delai": int(DELAI_FERMETURE), "liste_noire": True, "metier": True, "version": 0, "maj_le": 0,
            "maj_par": 0, "regle": False}


async def parcours(guild_id: int, panneau) -> dict:
    """Le parcours en vigueur pour ce panneau (ses réglages, sinon ceux par défaut)."""
    p = _defauts(panneau)
    if not panneau or _get_db is None:
        return p
    r = await _un(f"SELECT {', '.join(_COLS_P)} FROM recrutement_parcours WHERE guild_id=? AND panneau=?",
                  (int(guild_id), str(panneau)))
    if r is None:
        return p
    d = dict(zip(_COLS_P, tuple(r)))
    fiche = None
    if d["fiche"]:
        fiche = [x for x in _json_liste(d["fiche"]) if isinstance(x, dict)]
    p.update(mode=d["mode"] if d["mode"] in MODES else MODE_DEFAUT, fiche=fiche,
             gabarit=[x for x in _json_liste(d["gabarit"]) if isinstance(x, dict)],
             exigence=max(0, min(100, int(d["exigence"]))), delai=max(DELAI_MIN, min(DELAI_MAX, int(d["delai"]))),
             liste_noire=bool(d["liste_noire"]), metier=bool(d["metier"]), version=int(d["version"]),
             maj_le=int(d["maj_le"] or 0), maj_par=int(d["maj_par"] or 0), regle=True)
    return p


def _delai(p: dict) -> float:
    """Le délai avant la fermeture qui suit une décision : celui du panneau s'il est réglé, sinon `DELAI_FERMETURE`."""
    return float(p["delai"]) if p.get("regle") else float(DELAI_FERMETURE)


def fiche_du_panneau(pnl) -> list:
    """Les premières questions réglées dans /configure (le format d'avant : titre, exemple), dans celui de la fiche."""
    out = []
    for q in (pnl or {}).get("questions") or [] if isinstance(pnl, dict) else []:
        if not isinstance(q, dict):
            continue
        titre = _net(q.get("title") or q.get("titre") or "")[:CHAMP_TITRE_MAX]
        if not titre:
            continue
        exemple = _net(q.get("question") or "")
        out.append({"titre": titre, "aide": "", "exemple": exemple[:CHAMP_EXEMPLE_MAX],
                    "type": "long" if len(exemple) > 50 else "court", "requis": True, "max": 500, "options": [],
                    "eliminatoires": []})
    return out[:FICHE_MAX]


def fiche_effective(p: dict, pnl) -> list:
    """La fiche que le bot demande à l'ouverture : celle réglée sur le site, sinon celle du panneau (/configure)."""
    return p["fiche"] if p.get("fiche") is not None else fiche_du_panneau(pnl)


def avertissements_fiche(champs) -> list:
    """Les champs qui ressemblent à une donnée sensible ou inutile (santé, opinions, coordonnées, date de naissance,
    pseudo Discord…) : le site prévient — la fiche reste minimale, utile à la candidature, et légale."""
    out = []
    for k, ch in enumerate(champs or []):
        texte = _cle(" ".join(str(ch.get(x) or "") for x in ("titre", "aide", "exemple")))
        for motif, raison in MOTS_SENSIBLES:
            if re.search(motif, texte):
                out.append({"champ": k, "titre": str(ch.get("titre") or ""), "raison": raison})
                break
    return out


def _champ_fiche(x) -> dict:
    if not isinstance(x, dict):
        raise _Invalide("Chaque champ de la fiche est un objet.")
    titre = _texte(x, "titre", mini=1, maxi=CHAMP_TITRE_MAX)
    aide = _texte(x, "aide", maxi=CHAMP_AIDE_MAX, requis=False)
    exemple = _texte(x, "exemple", maxi=CHAMP_EXEMPLE_MAX, requis=False)
    type_ = x.get("type", "court")
    if type_ not in TYPES_CHAMP:
        raise _Invalide("« type » : court, long ou choix.")
    requis = _booleen(x, "requis", True)
    options, longueur, eliminatoires = [], CHAMP_LONGUEUR_DEFAUT, []
    if type_ == "choix":
        brut = x.get("options")
        if not isinstance(brut, list) or not 2 <= len(brut) <= OPTIONS_MAX:
            raise _Invalide(f"« {titre} » : de 2 à {OPTIONS_MAX} choix.")
        vus = set()
        for o in brut:
            t = _net(o) if isinstance(o, str) else ""
            if not t or len(t) > OPTION_MAX:
                raise _Invalide(f"« {titre} » : chaque choix fait de 1 à {OPTION_MAX} caractères.")
            if t.casefold() in vus:
                raise _Invalide(f"« {titre} » : le choix « {t} » est en double.")
            vus.add(t.casefold())
            options.append(t)
        longueur = OPTION_MAX
        elim = x.get("eliminatoires") or []
        if not isinstance(elim, list):
            raise _Invalide(f"« {titre} » : « eliminatoires » est une liste de choix.")
        par_cle = {o.casefold(): o for o in options}
        for e in elim:
            o = par_cle.get(_net(e).casefold()) if isinstance(e, str) else None
            if o is None:
                raise _Invalide(f"« {titre} » : un choix éliminatoire n'est pas dans la liste.")
            if o not in eliminatoires:
                eliminatoires.append(o)
        if len(eliminatoires) >= len(options):
            raise _Invalide(f"« {titre} » : au moins un choix doit laisser candidater.")
    else:
        longueur = _entier(x, "max", requis=False, mini=1, maxi=CHAMP_LONGUEUR_MAX) or CHAMP_LONGUEUR_DEFAUT
    return {"titre": titre, "aide": aide, "exemple": exemple, "type": type_, "requis": bool(requis),
            "max": int(longueur), "options": options, "eliminatoires": eliminatoires}


def _etape_gabarit(x) -> dict:
    if not isinstance(x, dict):
        raise _Invalide("Chaque étape du gabarit est un objet.")
    titre = _texte(x, "titre", maxi=ETAPE_TITRE_MAX, requis=False)
    consigne = _texte(x, "consigne", maxi=ETAPE_CONSIGNE_MAX, requis=False)
    source = x.get("source", "defaut")
    if source not in SOURCES_ETAPE:
        raise _Invalide("« source » : defaut, modele, questions ou tirage.")
    out = {"titre": titre, "consigne": consigne, "source": source}
    if source == "modele":
        out["modele"] = _ident_question(x, "modele", requis=True)
    elif source == "questions":
        ids = list(dict.fromkeys(_ids(x.get("questions"))))
        if not 1 <= len(ids) <= PAR_ENVOI:
            raise _Invalide(f"Une étape a de 1 à {PAR_ENVOI} questions.")
        out["questions"] = ids
    elif source == "tirage":
        out["nombre"] = _entier(x, "nombre", mini=1, maxi=PAR_ENVOI)
        theme = x.get("theme") or ""
        if not isinstance(theme, str) or len(theme) > THEME_MAX:
            raise _Invalide("« theme » : un thème de la banque, ou rien (tous les thèmes).")
        out["theme"] = _theme(theme) if theme.strip() else ""
    return out


async def enregistrer_parcours(g, auteur, corps) -> tuple[int, dict]:
    """Le parcours ENTIER d'un panneau (la page envoie tout), avec la `version` lue : changé entre-temps → conflit."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        pid = corps.get("panneau")
        if not isinstance(pid, str) or not FORMAT_ID.fullmatch(pid):
            raise _Invalide("« panneau » : identifiant invalide.")
        version = _entier(corps, "version", mini=0)
        mode = corps.get("mode", MODE_DEFAUT)
        if mode not in MODES:
            raise _Invalide("« mode » : approbation, automatique ou direct.")
        fiche = corps.get("fiche")
        if fiche is not None:
            if not isinstance(fiche, list) or not 1 <= len(fiche) <= FICHE_MAX:
                raise _Invalide(f"La fiche a de 1 à {FICHE_MAX} champs (une fenêtre Discord).")
            fiche = [_champ_fiche(x) for x in fiche]
            titres = [c["titre"].casefold() for c in fiche]
            if len(set(titres)) != len(titres):
                raise _Invalide("Deux champs de la fiche portent le même titre.")
        gabarit = corps.get("gabarit", [])
        if not isinstance(gabarit, list) or len(gabarit) > ETAPES_MAX:
            raise _Invalide(f"Le questionnaire a {ETAPES_MAX} étapes au plus.")
        gabarit = [_etape_gabarit(x) for x in gabarit]
        exigence = _entier(corps, "exigence", mini=0, maxi=100)
        delai = _entier(corps, "delai", mini=DELAI_MIN, maxi=DELAI_MAX)
        liste_noire = _booleen(corps, "liste_noire", True)
        metier = _booleen(corps, "metier", True)
    except _Invalide as ex:
        return _erreur(str(ex))
    if pid not in _panneaux(await _cfg(g.id)):
        return _erreur("Ce panneau n'est pas un panneau de recrutement.", 404)
    connus = {m["id"] for m in await modeles(g.id)}
    if any(e["source"] == "modele" and e["modele"] not in connus for e in gabarit):
        return _erreur("Un modèle choisi pour une étape n'existe plus : choisis-en un autre.")
    t = _maintenant()
    valeurs = (mode, "" if fiche is None else json.dumps(fiche, ensure_ascii=False),
               json.dumps(gabarit, ensure_ascii=False), int(exigence), int(delai), int(bool(liste_noire)),
               int(bool(metier)))
    async with _get_db() as db:
        async with db.execute("SELECT version FROM recrutement_parcours WHERE guild_id=? AND panneau=?",
                              (g.id, pid)) as cur:
            r = await cur.fetchone()
        actuelle = int(r[0]) if r else 0
        if int(version) != actuelle:
            await db.commit()
            return 409, {"conflit": True, "erreur": "Ce parcours a changé entre-temps.",
                         "actuelle": await parcours_site(g, pid)}
        if r is None:
            await db.execute("INSERT INTO recrutement_parcours (guild_id, panneau, mode, fiche, gabarit, exigence, delai,"
                             " liste_noire, metier, version, maj_le, maj_par) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
                             (g.id, pid, *valeurs, t, auteur.id))
        else:
            await db.execute("UPDATE recrutement_parcours SET mode=?, fiche=?, gabarit=?, exigence=?, delai=?,"
                             " liste_noire=?, metier=?, version=version+1, maj_le=?, maj_par=? WHERE guild_id=?"
                             " AND panneau=?", (*valeurs, t, auteur.id, g.id, pid))
        await db.commit()
    return 200, {"ok": True, "parcours": await parcours_site(g, pid),
                 "avertissements": avertissements_fiche(fiche or [])}


# ═══════════════════════════════════════════════════════════════════════════════
#  La sélection d'un envoi : des identifiants, un modèle, la dernière, des étapes, ou le gabarit du panneau
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
    Fosse ? »). Dans l'ordre : la première gardée l'emporte. Les étapes d'un questionnaire comptent ensemble : le
    candidat les lit toutes."""
    dans_liens, accueil = texte_des_liens(liens_), str(contexte or "")
    gardees, ecartees = [], []
    for q in qs:
        refus = _conflit(q, gardees, dans_liens, accueil)
        if refus is None:
            gardees.append(q)
        else:
            ecartees.append((q["id"], *refus))
    return gardees, ecartees


def _automatique(banque: list, nombre: int, liens_: list, contexte: str = "", *, deja=(), theme: str = "") -> list:
    """Sans modèle par défaut : `nombre` questions confirmées, actives, prises à tour de rôle dans chaque thème (au
    hasard dans le thème : deux candidats n'ont pas forcément les mêmes), sans qu'aucune ne dévoile une autre — ni une
    de celles `deja` choisies pour les étapes d'avant —, puis rangées par thème. `theme` : ce thème seulement."""
    hasard = random.SystemRandom()
    pris = {q["id"] for q in deja}
    par_theme: dict = {}
    for q in banque:
        if posable(q) and q["statut"] == "confirme" and q["id"] not in pris and (not theme or q["theme"] == theme):
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
        if _conflit(q, list(deja) + choisies, dans_liens, accueil) is None:
            choisies.append(q)
    rang = {t: k for k, t in enumerate(themes)}
    return sorted(choisies, key=lambda q: (rang[q["theme"]], q["ordre"], q["id"]))


def etapes_de(e: dict) -> list:
    """Les étapes d'un envoi : [{numero, titre, consigne}] — celles de son instantané, sinon (un envoi d'avant les
    étapes) une seule, qui contient toutes ses questions."""
    brut = e.get("etapes")
    if isinstance(brut, str):
        brut = _json_liste(brut)
    out = []
    for k, x in enumerate(brut or []):
        if isinstance(x, dict):
            out.append({"numero": int(x.get("numero") or k + 1), "titre": str(x.get("titre") or ""),
                        "consigne": str(x.get("consigne") or "")})
    if out:
        return out
    return [{"numero": 1, "titre": "", "consigne": ""}]


def _filtrer(ids, par_id: dict, motifs: dict, vus: set) -> list:
    """Les questions posables de `ids` (dans l'ordre, sans doublon) ; les autres nommées dans `motifs`."""
    retenues = []
    for qid in ids:
        if qid in vus:      # en double (ou déjà dans une étape d'avant) : ignorée sans rien dire, comme avant
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
    return retenues


def _assembler(lots: list, liens_: list, contexte: str, motifs: dict, origine: str, ids_demandes: list) -> tuple:
    """`lots` : [(titre, consigne, [questions])] dans l'ordre → (200, la sélection) ou une erreur. Les réponses ne se
    lisent nulle part (toutes étapes confondues) ; une étape vidée disparaît (les suivantes sont renumérotées)."""
    tout = [q for _t, _c, qs in lots for q in qs]
    if len(tout) > PAR_ENVOI:
        return _erreur(f"{PAR_ENVOI} questions au plus par envoi ({len(tout)} choisies).")
    gardees, ecartees = _sans_devoiler(tout, liens_, contexte)
    explications = {qid: _EXPLICATIONS.get(m, m) for qid, m in motifs.items()}
    for qid, motif, texte in ecartees:
        motifs[qid], explications[qid] = motif, texte
    garde = {id(q) for q in gardees}
    etapes, questions_ = [], []
    for titre, consigne, qs in lots:
        retenues = [q for q in qs if id(q) in garde]
        if not retenues:
            continue
        n = len(etapes) + 1
        etapes.append({"numero": n, "titre": titre, "consigne": consigne})
        questions_ += [dict(q, etape=n) for q in retenues]
    ignorees = list(dict.fromkeys(x for x in ids_demandes if x in motifs))
    if not questions_:
        return _erreur("Aucune question posable dans cette sélection (retirées, désactivées ou à reformuler).", 409,
                       ignorees=ignorees, motifs=motifs, explications=explications)
    return 200, {"questions": questions_, "etapes": etapes, "ignorees": ignorees, "motifs": motifs,
                 "explications": explications, "origine": origine}


async def _par_defaut(guild_id: int, banque: list, liens_: list, contexte: str, deja=()) -> tuple:
    """La sélection par défaut du serveur : le modèle par défaut, sinon le tirage automatique (`reglages.nombre`)."""
    defaut = next((m for m in await modeles(guild_id) if m["par_defaut"]), None)
    if defaut is not None:
        return defaut["questions"], f"modele:{defaut['id']}", None
    auto = _automatique(banque, (await reglages(guild_id))["nombre"], liens_, contexte, deja=deja)
    return [q["id"] for q in auto], "automatique", auto


async def selection(guild_id: int, corps: dict | None, contexte: str = "", panneau=None,
                    personnelles=None) -> tuple[int, dict]:
    """(200, {questions, etapes, ignorees, motifs, explications, origine}) ou (statut, {erreur}). `corps` :
    `questions` (identifiants : une étape), `modele` (une étape), `derniere: true` (la dernière sélection, ses étapes
    comprises) ou `etapes` ([{titre, consigne, questions: [identifiants]}] : ce candidat-là) — un seul ; rien : le
    gabarit du `panneau` s'il est réglé, sinon le modèle par défaut, sinon la sélection automatique. Chaque question
    rendue porte son `etape` (1…N). Une question inconnue, retirée, désactivée, qui dévoile sa réponse, dont la réponse
    se lirait ailleurs (liens, mot d'accueil `contexte`, autre question, quelle que soit l'étape) est ignorée : nommée
    dans `ignorees`, avec son motif (`motifs`) et une phrase pour la page (`explications`). `personnelles` : des
    questions écrites pour ce seul candidat (leurs identifiants « p-… » valent comme ceux de la banque)."""
    corps = corps if isinstance(corps, dict) else {}
    choix = [k for k in ("questions", "modele", "derniere", "etapes")
             if corps.get(k) is not None and corps.get(k) is not False]
    if len(choix) > 1:
        return _erreur("Choisis les questions, un modèle, la dernière sélection ou des étapes : un seul des quatre.")
    banque = await questions(guild_id)
    liens_ = await liens(guild_id)
    par_id = {q["id"]: q for q in banque}
    for q in personnelles or []:
        par_id[q["id"]] = q
    motifs: dict = {}
    if not choix:
        gabarit = (await parcours(guild_id, panneau))["gabarit"] if panneau else []
        if gabarit:
            return await _selon_gabarit(guild_id, gabarit, banque, par_id, liens_, contexte)
        ids, origine, auto = await _par_defaut(guild_id, banque, liens_, contexte)
        if auto is not None:
            if not auto:
                return _erreur("La banque n'a aucune question confirmée et active : ajoute-en sur le site.", 409)
            return 200, {"questions": [dict(q, etape=1) for q in auto], "etapes": [{"numero": 1, "titre": "",
                                                                                   "consigne": ""}],
                         "ignorees": [], "motifs": {}, "explications": {}, "origine": origine}
        lots = [("", "", _filtrer(ids, par_id, motifs, set()))]
        return _assembler(lots, liens_, contexte, motifs, origine, ids)
    if choix[0] == "etapes":
        brut = corps["etapes"]
        if not isinstance(brut, list) or not 1 <= len(brut) <= ETAPES_MAX:
            return _erreur(f"De 1 à {ETAPES_MAX} étapes.")
        lots, vus, demandes = [], set(), []
        try:
            for x in brut:
                if not isinstance(x, dict):
                    raise _Invalide("Chaque étape est un objet {titre, consigne, questions}.")
                titre = _texte(x, "titre", maxi=ETAPE_TITRE_MAX, requis=False)
                consigne = _texte(x, "consigne", maxi=ETAPE_CONSIGNE_MAX, requis=False)
                ids = _ids(x.get("questions") or [])
                demandes += ids
                lots.append((titre, consigne, _filtrer(ids, par_id, motifs, vus)))
        except _Invalide as ex:
            return _erreur(str(ex))
        if not demandes:
            return _erreur("Coche au moins une question.")
        return _assembler(lots, liens_, contexte, motifs, "etapes", demandes)
    if choix[0] == "questions":
        try:
            ids = _ids(corps["questions"])
        except _Invalide as ex:
            return _erreur(str(ex))
        if not ids:
            return _erreur("Coche au moins une question.")
        return _assembler([("", "", _filtrer(ids, par_id, motifs, set()))], liens_, contexte, motifs, "questions", ids)
    if choix[0] == "modele":
        mid = corps["modele"]
        if not isinstance(mid, str) or not FORMAT_ID.fullmatch(mid):
            return _erreur("« modele » : identifiant invalide.")
        m = next((x for x in await modeles(guild_id) if x["id"] == mid), None)
        if m is None:
            return _erreur("Ce modèle n'existe plus.", 404)
        lots = [("", "", _filtrer(m["questions"], par_id, motifs, set()))]
        return _assembler(lots, liens_, contexte, motifs, f"modele:{mid}", m["questions"])
    if corps["derniere"] is not True:
        return _erreur("« derniere » doit valoir true.")
    d = await derniere_selection(guild_id)
    if d is None:
        return _erreur("Aucun questionnaire n'a encore été envoyé.", 404)
    vus, lots = set(), []
    for e in d["etapes"]:
        ids = [qid for qid, n in zip(d["questions"], d["etape_de"]) if n == e["numero"]]
        lots.append((e["titre"], e["consigne"], _filtrer(ids, par_id, motifs, vus)))
    return _assembler(lots, liens_, contexte, motifs, "derniere", d["questions"])


async def _selon_gabarit(guild_id: int, gabarit: list, banque: list, par_id: dict, liens_: list,
                         contexte: str) -> tuple:
    """Le gabarit d'un panneau, étape par étape : un modèle, des questions cochées, un tirage (d'un thème), ou la
    sélection par défaut du serveur — une question déjà prise par une étape d'avant n'est jamais reprise."""
    lots, motifs, vus, demandes, deja = [], {}, set(), [], []
    modeles_ = {m["id"]: m for m in await modeles(guild_id)}
    for e in gabarit:
        source = e.get("source", "defaut")
        if source == "tirage":
            qs = _automatique(banque, int(e.get("nombre") or 1), liens_, contexte, deja=deja,
                              theme=str(e.get("theme") or ""))
            for q in qs:
                vus.add(q["id"])
        else:
            if source == "modele":
                m = modeles_.get(str(e.get("modele") or ""))
                ids = m["questions"] if m else []
            elif source == "questions":
                ids = [str(x) for x in e.get("questions") or []]
            else:
                ids, _origine, auto = await _par_defaut(guild_id, banque, liens_, contexte, deja=deja)
                if auto is not None:
                    ids = [q["id"] for q in auto]
            demandes += ids
            qs = _filtrer(ids, par_id, motifs, vus)
        deja += qs
        lots.append((str(e.get("titre") or ""), str(e.get("consigne") or ""), qs))
    if not any(qs for _t, _c, qs in lots):
        return _erreur("Le questionnaire de ce panneau n'a aucune question posable : règle ses étapes sur le site.",
                       409)
    return _assembler(lots, liens_, contexte, motifs, "gabarit", demandes)


_EXPLICATIONS = {"inconnue": "elle n'existe pas (ou plus) dans la banque",
                 "retiree": "elle a été retirée de la banque",
                 "inactive": "elle est désactivée",
                 "devoile_sa_reponse": "son texte contient sa propre réponse : à reformuler",
                 "deja_choisie": "elle est déjà dans une autre étape"}


async def annonce(guild_id: int, contexte: str = "", panneau=None) -> int:
    """Le nombre de questions que la sélection par défaut (ou le gabarit du panneau) poserait : celui que l'affiche
    annonce au candidat."""
    return (await annonce_detail(guild_id, contexte, panneau))[1]


async def annonce_detail(guild_id: int, contexte: str = "", panneau=None) -> tuple:
    """(étapes, questions) que le questionnaire prévu pour ce panneau poserait (0, 0 : aucune question posable)."""
    status, sel = await selection(guild_id, None, contexte, panneau=panneau)
    if status != 200:
        return 0, 0
    return len(sel["etapes"]), len(sel["questions"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Les cartes Discord (Components V2, FR · EN, aucun émoji Unicode)
# ═══════════════════════════════════════════════════════════════════════════════

def nb_pages(n: int) -> int:
    return max(1, math.ceil(int(n) / PAR_PAGE))


def questions_de_la_page(qs: list, page: int) -> list:
    return qs[(page - 1) * PAR_PAGE: page * PAR_PAGE]


def pages_envoi(qs: list) -> list:
    """Les pages des formulaires d'un envoi : 5 questions au plus, jamais deux étapes dans la même page (un envoi sans
    étapes : des pages de 5, dans l'ordre, comme avant)."""
    pages, courante, etape = [], [], None
    for q in qs:
        n = int(q.get("etape") or 1)
        if courante and (n != etape or len(courante) >= PAR_PAGE):
            pages.append(courante)
            courante = []
        etape = n
        courante.append(q)
    if courante:
        pages.append(courante)
    return pages or [[]]


def premiere_incomplete(qs: list, reponses: dict) -> int | None:
    """La première page dont une question n'a pas de réponse ; None : tout est répondu."""
    for p, page in enumerate(pages_envoi(qs), 1):
        if any(int(q["rang"]) not in reponses for q in page):
            return p
    return None


def _couper(texte, n: int) -> str:
    """Un texte raccourci à `n` caractères au plus : à la fin d'une ligne, sinon d'un mot, avec « … »."""
    t = str(texte or "")
    if len(t) <= n:
        return t
    if n <= 1:
        return ""
    coupe = t[:n - 1]
    for sep in ("\n", " "):
        if sep in coupe[n // 2:]:
            coupe = coupe[:coupe.rindex(sep)]
            break
    return coupe.rstrip(" ,;:.\n") + "…"


def _ajuster(parts: dict, budget: int, ordre) -> dict:
    """Les textes d'une carte tenus dans `budget` caractères (Discord : 4 000 par message) : on raccourcit d'abord les
    premiers de `ordre` ([(nom, minimum)]), chacun jusqu'à son minimum au plus."""
    total = sum(len(t) for t in parts.values())
    for nom, minimum in ordre:
        if total <= budget:
            break
        t = parts.get(nom) or ""
        if len(t) <= minimum:
            continue
        nouveau = _couper(t, max(minimum, len(t) - (total - budget)))
        total -= len(t) - len(nouveau)
        parts[nom] = nouveau
    return parts


def _bloc_liens(liens_: list, guild_id: int = 0, budget: int = LIENS_BUDGET) -> str:
    """« Où trouver les réponses » : les liens, dans la place d'une carte (les descriptions tombent d'abord)."""
    if not liens_:
        return ""
    tete = _t(guild_id, "recrutement.liens.titre")

    def ligne(lien, avec_desc):
        titre = _md(lien["titre"]).replace("[", "(").replace("]", ")")
        url = str(lien["url"]).replace(")", "%29").replace(" ", "%20")
        desc = f" — {_md(lien['description'])}" if avec_desc and lien.get("description") else ""
        return f"- [{titre}]({url}){desc}"
    for avec_desc in (True, False):
        lignes = [ligne(x, avec_desc) for x in liens_]
        if len(tete) + sum(len(x) + 1 for x in lignes) <= budget:
            return "\n".join([tete, *lignes])
    garde, place = [], budget - len(tete) - 80
    for x in lignes:
        if place - len(x) - 1 < 0:
            break
        garde.append(x)
        place -= len(x) + 1
    reste = len(lignes) - len(garde)
    return "\n".join([tete, *garde, f"-# + {reste} lien(s) : demande-les à la direction · ask the leadership"])


def _wiki_et_liens(liens_: list, guild_id: int = 0, budget: int = LIENS_BUDGET) -> str:
    bloc = _bloc_liens(liens_, guild_id, budget)
    return "\n".join(x for x in (_t(guild_id, "recrutement.wiki"), bloc) if x) if bloc else ""


def _etapes_txt(n: int) -> tuple:
    """(« 2 étapes », « 2 steps »)."""
    n = int(n or 0)
    return ("une étape", "one step") if n <= 1 else (f"{n} étapes", f"{n} steps")


def _questions_en(n: int) -> str:
    n = int(n or 0)
    return f"{n} question{'s' if n > 1 else ''}" if n > 0 else "a few questions"


def _variables_nombres(nb_etapes: int, nb_questions: int) -> dict:
    e_fr, e_en = _etapes_txt(nb_etapes)
    return {"etapes": e_fr, "questions": _questions_txt(nb_questions)[0], "etapes_en": e_en,
            "questions_en": _questions_en(nb_questions)}


def _texte_fiche(guild_id: int, reponses: dict) -> str:
    """Sa fiche, sur l'affiche : ce qu'il a répondu en ouvrant le ticket (sans mise en forme ni mention venues de lui)."""
    lignes = []
    for q, a in list((reponses or {}).items())[:FICHE_MAX]:
        a = _net(a)
        if a:
            lignes.append(f"**{_md(_net(q))[:CHAMP_TITRE_MAX + 15]}** · {_md(a)[:300]}")
    return "\n".join([_t(guild_id, "recrutement.affiche.fiche"), *lignes]) if lignes else ""


def _entete_etape(guild_id: int, etape: dict) -> str:
    """« **Étape 2** · *Step 2* — Le jeu » et sa consigne en petit."""
    t = _t(guild_id, "recrutement.etape.entete", numero=int(etape.get("numero") or 1))
    if etape.get("titre"):
        t += f" — {_md(etape['titre'])}"
    if etape.get("consigne"):
        t += f"\n-# {_md(etape['consigne'])}"
    return t


def _bouton(gid: int, tid: int, code: str, cle: str):
    return BoutonEtape1(code, tid, _t(gid, f"recrutement.equipe.bouton.{cle}"))


def _etat_equipe(d: dict) -> tuple:
    """(texte, boutons, couleur) du panneau de la direction selon l'état de la candidature."""
    gid, tid, etat = int(d.get("gid") or 0), int(d["ticket"]), d["etat"]
    nb_q = int(d.get("nb_questions") or 0)
    v = _variables_nombres(d.get("nb_etapes") or 1, nb_q)
    q = f"**{v['questions']}**" if nb_q else "le questionnaire"
    qui, depuis_ = f"<@{int(d.get('par') or 0)}>", f"<t:{int(d.get('quand') or _maintenant())}:R>"
    if etat == "demande":
        prevu = f"{v['etapes']}, {v['questions']}" if nb_q else "la sélection par défaut"
        texte = _t(gid, "recrutement.equipe.decision", combien=f"{v['questions']}, " if nb_q else "",
                   questionnaire=prevu)
        return texte, [_bouton(gid, tid, "n", "suivante"), _bouton(gid, tid, "s", "site"),
                       _bouton(gid, tid, "r", "refuser")], COULEUR_LAITON
    if etat == "direct":
        return _t(gid, "recrutement.equipe.direct"), [_bouton(gid, tid, "a", "accepter"),
                                                       _bouton(gid, tid, "r", "refuser_candidature"),
                                                       _bouton(gid, tid, "s", "ouvrir")], COULEUR_LAITON
    if etat == "questionnaire":
        ouverte, envoyee, total = d.get("numeros") or (0, 0, 0)
        if d.get("porte") and envoyee and envoyee >= ouverte:
            texte = _t(gid, "recrutement.direction.etape_recue", numero=envoyee, total=total, quand=depuis_)
            return texte, [_bouton(gid, tid, "n", "suivante"), _bouton(gid, tid, "r", "refuser_candidature"),
                           _bouton(gid, tid, "s", "ouvrir")], COULEUR_MER
        if d.get("porte"):
            texte = _t(gid, "recrutement.direction.etape_ouverte", numero=ouverte, total=total, quand=depuis_)
        else:
            texte = (_t(gid, "recrutement.equipe.envoye_auto", questions=q, quand=depuis_) if d.get("auto")
                     else _t(gid, "recrutement.equipe.envoye", par=qui, quand=depuis_, questions=q))
        return texte, [_bouton(gid, tid, "s", "ouvrir"), _bouton(gid, tid, "r", "refuser_candidature")], COULEUR_VERT
    if etat == "reponses":
        texte = (_t(gid, "recrutement.direction.derniere", quand=depuis_) if d.get("porte")
                 else _t(gid, "recrutement.equipe.reponses", candidat=f"<@{int(d['candidat'])}>", questions=q,
                         quand=depuis_))
        return texte, [_bouton(gid, tid, "a", "accepter"), _bouton(gid, tid, "r", "refuser_candidature"),
                       _bouton(gid, tid, "s", "corriger")], COULEUR_MER
    if etat == "accepte":
        return _t(gid, "recrutement.equipe.accepte", par=qui, quand=depuis_), [], COULEUR_VERT
    cle = "recrutement.equipe.refus_etape1" if etat == "refus_etape1" else "recrutement.equipe.refuse"
    return _t(gid, cle, par=qui, quand=depuis_), [], COULEUR_CIRE


def carte_affiche(d: dict) -> LayoutView:
    """L'AFFICHE d'un ticket de recrutement — le message unique de l'ouverture, réécrit (jamais renvoyé) à chaque
    étape. Pour le candidat seulement : la bannière (sinon un titre), le mot d'accueil qui le cite SANS le prévenir, le
    mot du panneau, les conditions, sa fiche (son « Étape 1 »), puis où il en est (« Étape 2 sur 4 : à toi », « réponses
    reçues »…). Aucun numéro de ticket, aucun bouton de décision sous ses yeux : un seul bouton discret « Direction »,
    qui ouvre pour la tête seule son panneau (éphémère). `d` : gid, ticket, candidat, mode, etat (demande · direct ·
    questionnaire · reponses · accepte · refus_etape1 · refuse), nb_etapes, nb_questions, porte, numeros, auto,
    texte_panneau, reponses, repondu_le, banniere."""
    gid, cid, etat = int(d.get("gid") or 0), int(d["candidat"]), d.get("etat") or "demande"
    v = _variables_nombres(d.get("nb_etapes") or 1, d.get("nb_questions") or 0)
    ouverte, envoyee, total = d.get("numeros") or (0, 0, 0)
    fiche = _texte_fiche(gid, d.get("reponses") or {})
    if etat == "direct" or (etat in ("accepte", "refuse", "refus_etape1") and d.get("mode") == "direct"):
        consignes = _t(gid, "recrutement.affiche.direct")
    elif etat == "questionnaire" and d.get("porte"):
        consignes = (_t(gid, "recrutement.affiche.etape_recue", numero=envoyee, total=total)
                     if envoyee and envoyee >= ouverte else
                     _t(gid, "recrutement.affiche.etape_ouverte", numero=ouverte, total=total))
    elif etat == "questionnaire":
        consignes = _t(gid, "recrutement.affiche.automatique" if d.get("auto") else "recrutement.affiche.questionnaire",
                       **v)
    elif etat == "reponses" or d.get("repondu_le"):
        consignes = _t(gid, "recrutement.affiche.reponses", quand=f"<t:{int(d.get('repondu_le') or _maintenant())}:f>")
    elif fiche:
        consignes = _t(gid, "recrutement.affiche.fiche_recue")
    else:
        consignes = _t(gid, "recrutement.affiche.attente", **v)
    parts = _ajuster({
        "intro": _t(gid, "recrutement.affiche.intro", candidat=f"<@{cid}>"),
        "panneau": str(d.get("texte_panneau") or "").strip()[:1500],
        "conditions": _t(gid, "recrutement.affiche.conditions").strip(),
        "fiche": fiche, "consignes": consignes}, TEXTE_AFFICHE,
        (("panneau", 0), ("conditions", 120), ("fiche", 200), ("consignes", 200), ("intro", 60)))
    url = d.get("banniere")
    haut = [discord.ui.MediaGallery(discord.MediaGalleryItem(url, description="Avis de recrutement")) if url
            else discord.ui.TextDisplay(_t(gid, "recrutement.affiche.titre"))]
    haut.append(discord.ui.TextDisplay("\n".join(x for x in (parts["intro"], parts["panneau"]) if x)))
    for nom in ("conditions", "fiche", "consignes"):
        if parts[nom]:
            haut += [discord.ui.Separator(), discord.ui.TextDisplay(parts[nom])]
    if etat not in FINALES:
        haut.append(discord.ui.ActionRow(_bouton(gid, int(d["ticket"]), "d", "direction")))
    vue = LayoutView(timeout=None)
    vue.add_item(discord.ui.Container(*haut, accent_color=COULEUR_LAITON))
    return vue


def carte_etape1(tid: int, etat: str = "attente", *, nombre: int = 0, par: int = 0, candidat: int = 0,
                 quand: int = 0, guild_id: int = 0) -> LayoutView:
    """La carte de l'équipe d'un ticket ouvert AVANT l'affiche (26/10/2026) : la décision, puis où en est la
    candidature. Ses textes et ses boutons sont ceux du serveur (Textes & noms), sinon ceux d'origine."""
    s = "s" if nombre > 1 else ""
    q = f"**{nombre} question{s}**" if nombre else "le questionnaire"
    qui, depuis_ = f"<@{int(par)}>", f"<t:{int(quand)}:R>"
    gid = int(guild_id or 0)
    rangee = None
    if etat == "attente":
        texte = _t(gid, "recrutement.equipe.decision", combien=f"{nombre} question{s}, " if nombre else "",
                   questionnaire=f"{nombre} question{s}" if nombre else "la sélection par défaut")
        rangee = discord.ui.ActionRow(_bouton(gid, tid, "n", "suivante"), _bouton(gid, tid, "s", "site"),
                                      _bouton(gid, tid, "r", "refuser"))
        couleur = COULEUR_LAITON
    elif etat == "envoye":
        texte = _t(gid, "recrutement.equipe.envoye", par=qui, quand=depuis_, questions=q)
        rangee = discord.ui.ActionRow(_bouton(gid, tid, "s", "ouvrir"))
        couleur = COULEUR_VERT
    elif etat == "reponses":
        texte = _t(gid, "recrutement.equipe.reponses", candidat=f"<@{int(candidat)}>", questions=q, quand=depuis_)
        rangee = discord.ui.ActionRow(_bouton(gid, tid, "s", "corriger"))
        couleur = COULEUR_MER
    elif etat == "accepte":
        texte = _t(gid, "recrutement.equipe.accepte", par=qui, quand=depuis_)
        couleur = COULEUR_VERT
    else:
        texte = _t(gid, "recrutement.equipe.refus_etape1" if etat == "refus_etape1" else "recrutement.equipe.refuse",
                   par=qui, quand=depuis_)
        couleur = COULEUR_CIRE
    items = [discord.ui.TextDisplay(texte)] + ([rangee] if rangee is not None else [])
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    return v


def _groupes(qs: list, guild_id: int = 0, etapes=None) -> list:
    """Les questions, en entier, par formulaire (« Formulaire 1/2 ») et par étape (son titre et sa consigne, quand le
    questionnaire en a plusieurs ou qu'elles ont un titre) : ce que le candidat lit avant de répondre."""
    pages = pages_envoi(qs)
    etapes = etapes or [{"numero": 1, "titre": "", "consigne": ""}]
    titrees = len(etapes) > 1 or any(x.get("titre") or x.get("consigne") for x in etapes)
    par_num = {int(x["numero"]): x for x in etapes}
    out, vues = [], set()
    for p, page in enumerate(pages, 1):
        lignes = []
        n = int(page[0].get("etape") or 1) if page else 1
        if titrees and n not in vues:
            vues.add(n)
            lignes.append(_entete_etape(guild_id, par_num.get(n) or {"numero": n}))
        if len(pages) > 1:
            lignes.append(_t(guild_id, "recrutement.formulaire.groupe", page=p, pages=len(pages)))
        lignes += [f"**{int(q['rang'])}.** {_md(q['question'])}" for q in page]
        out.append("\n".join(lignes))
    return out


def cartes_etape2(envoi: dict, etat: str = "ouvert", *, quand: int = 0) -> list:
    """Le questionnaire posté dans le ticket, quand le candidat répond dans Discord (sans la page web) — en plusieurs
    messages si les questions ne tiennent pas dans un seul (4 000 caractères) ; le bouton « Répondre » est sur le
    dernier. `etat` : ouvert · repondu · remplace · clos. Ni réponse attendue, ni variante, ni source : seulement les
    questions (rangées par étape) et les liens. Un nouveau questionnaire (`renvoi`) le dit."""
    qs = envoi["questions"]
    gid = int(envoi.get("guild_id") or 0)
    n, pages = len(qs), len(pages_envoi(qs))
    renvoi = bool(envoi.get("renvoi"))
    titre = _t(gid, "recrutement.etape2.titre_renvoi" if renvoi else "recrutement.etape2.titre",
               nombre=_questions_txt(n)[0])
    forme = (_t(gid, "recrutement.etape2.formulaires", pages=pages, par_page=PAR_PAGE) if pages > 1
             else _t(gid, "recrutement.etape2.un_formulaire"))
    intro = f"<@{int(envoi['candidat_id'])}> " + _t(gid, "recrutement.etape2.intro") + "\n" + forme
    pied = _t(gid, "recrutement.etape2.pied")
    if etat == "repondu":
        fin = discord.ui.TextDisplay(_t(gid, "recrutement.etape2.envoyees", quand=f"<t:{int(quand or _maintenant())}:f>"))
    elif etat == "remplace":
        fin = discord.ui.TextDisplay(_t(gid, "recrutement.etape2.remplace"))
    elif etat == "clos":
        fin = discord.ui.TextDisplay(_t(gid, "recrutement.etape2.clos"))
    else:
        fin = discord.ui.ActionRow(BoutonRepondre(int(envoi["id"]), _t(gid, "recrutement.bouton.repondre")))
    bloc = _wiki_et_liens(envoi.get("liens") or [], gid)
    messages = [[discord.ui.TextDisplay(titre), discord.ui.TextDisplay(intro)]
                + ([discord.ui.Separator(), discord.ui.TextDisplay(bloc)] if bloc else []) + [discord.ui.Separator()]]
    taille = len(titre) + len(intro) + len(bloc)
    reserve = len(pied) + 260
    for texte in _groupes(qs, gid, etapes_de(envoi)):
        if taille + len(texte) > TEXTE_MESSAGE - reserve:
            suite = _t(gid, "recrutement.etape2.suite")
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


def carte_invitation(envoi: dict) -> LayoutView:
    """Dans un ticket ouvert avant l'affiche, quand le candidat répond sur la page web : une invitation courte (il est
    prévenu), le bouton « Répondre au questionnaire » et les liens des réponses — sans les questions."""
    gid = int(envoi.get("guild_id") or 0)
    v = _variables_nombres(len(etapes_de(envoi)), len(envoi["questions"]))
    items = [discord.ui.TextDisplay(_t(gid, "recrutement.etape2.invitation", candidat=f"<@{int(envoi['candidat_id'])}>",
                                       **v))]
    bloc = _wiki_et_liens(envoi.get("liens") or [], gid)
    if bloc:
        items += [discord.ui.Separator(), discord.ui.TextDisplay(bloc)]
    items.append(discord.ui.ActionRow(BoutonRepondre(int(envoi["id"]), _t(gid, "recrutement.bouton.questionnaire"))))
    vue = LayoutView(timeout=None)
    vue.add_item(discord.ui.Container(*items, accent_color=COULEUR_MER))
    return vue


def carte_apercu(envoi: dict, page: int, reponses: dict, *, corriger: bool = False) -> LayoutView:
    """L'APERÇU en lecture seule, pour la direction (éphémère, à soi seul) : le questionnaire tel que le candidat le
    voit — les étapes OUVERTES seulement, page par page (les pages de ses formulaires) —, avec les réponses qu'il a déjà
    données et l'état. JAMAIS les réponses attendues, ni les variantes. `corriger` : « Corriger sur le site »."""
    gid, eid = int(envoi.get("guild_id") or 0), int(envoi["id"])
    ouverte_q = int(envoi.get("etape_ouverte") or 0)
    visibles = [q for q in envoi["questions"] if not ouverte_q or int(q.get("etape") or 1) <= ouverte_q]
    pages = pages_envoi(visibles)
    k = max(0, min(len(pages) - 1, int(page)))
    etapes = {int(x["numero"]): x for x in etapes_de(envoi)}
    fiche = int(envoi.get("etape_fiche") or 0)
    _ouv, _env, total = _numeros(envoi)
    nombre, repondues = len(visibles), sum(1 for q in visibles if int(q["rang"]) in reponses)
    if envoi["statut"] == "repondu":
        etat = _t(gid, "recrutement.apercu.repondu", quand=f"<t:{int(envoi.get('repondu_le') or _maintenant())}:f>")
    elif envoi["statut"] not in EN_ATTENTE:
        etat = _t(gid, "recrutement.apercu.clos")
    elif repondues:
        etat = _t(gid, "recrutement.apercu.en_cours", repondues=repondues, total=nombre)
    else:
        etat = _t(gid, "recrutement.apercu.attente")
    n = int(pages[k][0].get("etape") or 1) if pages[k] else 1
    etape = dict(etapes.get(n) or {"numero": n, "titre": "", "consigne": ""}, numero=n + fiche)
    lignes = [_entete_etape(gid, etape) + (f" · sur {total}" if total > 1 else "")
              + (f"\n-# page {k + 1}/{len(pages)}" if len(pages) > 1 else "")]
    for q in pages[k]:
        r = reponses.get(int(q["rang"]))
        texte = f"**{int(q['rang'])}.** {_md(q['question'])}"
        if r and r.get("texte"):
            texte += "\n" + "\n".join("> " + x for x in _md(_couper(r["texte"], 420)).split("\n"))
        else:
            texte += "\n" + _t(gid, "recrutement.apercu.sans_reponse")
        lignes.append(texte)
    entete = _t(gid, "recrutement.apercu.titre", candidat=f"<@{int(envoi['candidat_id'])}>") + "\n" + etat
    liens_ = _wiki_et_liens(envoi.get("liens") or [], gid, 900) if k == 0 else ""
    parts = _ajuster({"entete": entete, "corps": "\n\n".join(lignes), "liens": liens_}, TEXTE_MESSAGE - 300,
                     (("liens", 0), ("corps", 400)))
    items = [discord.ui.TextDisplay(parts["entete"]), discord.ui.Separator(), discord.ui.TextDisplay(parts["corps"])]
    if parts["liens"]:
        items += [discord.ui.Separator(), discord.ui.TextDisplay(parts["liens"])]
    boutons = []
    if len(pages) > 1:
        boutons += [BoutonApercu(eid, max(0, k - 1), _t(gid, "recrutement.bouton.apercu.precedente"), k == 0, "p"),
                    BoutonApercu(eid, min(len(pages) - 1, k + 1), _t(gid, "recrutement.bouton.apercu.suivante"),
                                 k >= len(pages) - 1, "s")]
    if corriger and int(envoi.get("ticket_id") or 0):
        boutons.append(_bouton(gid, int(envoi["ticket_id"]), "s", "corriger"))
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    vue = LayoutView(timeout=None)
    vue.add_item(discord.ui.Container(*items, accent_color=COULEUR_MER))
    vue.stop()   # un mot pour soi : ses boutons répondent par leur gabarit (voir `_vue_texte`)
    return vue


def _vue_decision(texte: str, couleur, boutons=()) -> LayoutView:
    """Le message de la décision, dans le ticket (le candidat est cité en tête par le texte)."""
    items = [discord.ui.TextDisplay(str(texte)[:3900])]
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    return v


def _numeros(e: dict | None, fiche: int = 0) -> tuple:
    """(étape ouverte, étape envoyée, total) TELS QUE LE CANDIDAT LES LIT : sa fiche est l'étape 1 quand le panneau en
    a une (`etape_fiche`), le questionnaire va donc de 2 à N+1 ; un envoi d'avant (`etape_ouverte` 0) : tout ouvert."""
    if e is None:
        return 0, 0, 0
    n = len(etapes_de(e))
    f = int(e.get("etape_fiche") or fiche or 0)
    ouverte = int(e.get("etape_ouverte") or 0) or n
    envoyee = int(e.get("etape_envoyee") or 0)
    return ouverte + f, (envoyee + f) if envoyee else 0, n + f


def panneau_direction(d: dict) -> LayoutView:
    """Le panneau de la direction (éphémère, pour la tête seule — ouvert par « Direction » sur l'affiche) : où en est
    la candidature, ce qu'il faut décider, les boutons de la décision, le bas du dossier (son compte, son casier, la
    prise en charge) et « Fermer le ticket ». Tout se fait aussi sur le site."""
    gid = int(d.get("gid") or 0)
    texte, boutons, couleur = _etat_equipe(d)
    extras = d.get("extras") or {}
    pris = int(extras.get("pris_par") or 0)
    bas = " · ".join([*(str(x) for x in extras.get("contexte") or []),
                      f"pris en charge par <@{pris}>" if pris else "pas encore pris en charge"])
    items = [discord.ui.TextDisplay(_t(gid, "recrutement.direction.titre", candidat=f"<@{int(d['candidat'])}>")),
             discord.ui.TextDisplay(_couper(texte, 2500))]
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    items.append(discord.ui.TextDisplay("-# " + _couper(bas, 600)))
    if extras.get("boutons"):
        items.append(discord.ui.ActionRow(*list(extras["boutons"])[:5]))
    vue = LayoutView(timeout=None)
    vue.add_item(discord.ui.Container(*items, accent_color=couleur))
    vue.stop()   # un mot pour soi : ses boutons répondent par leur gabarit (voir `_vue_texte`)
    return vue


def carte_etape(e: dict, etat: str = "ouverte", *, quand: int = 0) -> LayoutView:
    """Le MESSAGE DE L'ÉTAPE en cours, dans le ticket (le second et dernier message du bot, avec l'affiche) : posté à
    l'ouverture d'une étape — il PRÉVIENT le candidat — puis réécrit, jamais doublé : « réponses reçues », « réponses
    envoyées », remplacé, clos. Ouvert : le titre et la consigne de l'étape, ses questions (quand le candidat répond
    dans Discord, sans la page web), les liens des réponses et « Répondre au questionnaire »."""
    gid = int(e.get("guild_id") or 0)
    ouverte, envoyee, total = _numeros(e)
    if etat == "recue":
        texte = _t(gid, "recrutement.etape.recue", numero=envoyee or ouverte, total=total)
        return _vue_decision(texte, COULEUR_MER)
    if etat == "repondu":
        return _vue_decision(_t(gid, "recrutement.etape2.envoyees", quand=f"<t:{int(quand or _maintenant())}:f>"),
                             COULEUR_VERT)
    if etat in ("remplace", "clos"):
        return _vue_decision(_t(gid, f"recrutement.etape2.{etat}"), COULEUR_MER)
    k = int(e.get("etape_ouverte") or 1)
    etape = next((x for x in etapes_de(e) if int(x["numero"]) == k), {"numero": k, "titre": "", "consigne": ""})
    qs = [q for q in e["questions"] if int(q.get("etape") or 1) == k]
    tete = _t(gid, "recrutement.etape.message", candidat=f"<@{int(e['candidat_id'])}>", numero=ouverte, total=total,
              questions=_questions_txt(len(qs))[0], questions_en=_questions_en(len(qs)))
    if etape.get("titre"):
        tete += f"\n**{_md(etape['titre'])}**"
    if etape.get("consigne"):
        tete += f"\n-# {_md(etape['consigne'])}"
    liste = ""
    if _page_candidat() is None:   # sans la page web, le candidat lit les questions ici et répond dans Discord
        pages = [p for p in pages_envoi(e["questions"]) if p and int(p[0].get("etape") or 1) == k]
        blocs = []
        for n, page in enumerate(pages, 1):
            lignes = [_t(gid, "recrutement.formulaire.groupe", page=n, pages=len(pages))] if len(pages) > 1 else []
            lignes += [f"**{int(q['rang'])}.** {_md(q['question'])}" for q in page]
            blocs.append("\n".join(lignes))
        liste = "\n".join(blocs)
    parts = _ajuster({"tete": tete, "liste": liste, "liens": _wiki_et_liens(e.get("liens") or [], gid, 900)},
                     TEXTE_MESSAGE - 400, (("liens", 0), ("liste", 300)))
    items = [discord.ui.TextDisplay(parts["tete"])]
    for nom in ("liste", "liens"):
        if parts[nom]:
            items += [discord.ui.Separator(), discord.ui.TextDisplay(parts[nom])]
    items.append(discord.ui.ActionRow(BoutonRepondre(int(e["id"]), _t(gid, "recrutement.bouton.questionnaire"))))
    vue = LayoutView(timeout=None)
    vue.add_item(discord.ui.Container(*items, accent_color=COULEUR_MER))
    return vue


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
            await _avis(i, _t(_gid(i), "recrutement.souci"), couleur=COULEUR_CIRE)
        except discord.HTTPException as ex2:
            _log(f"[RECRUTEMENT][E7:DETAIL] réponse impossible {type(ex2).__name__}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Les boutons persistants (ils marchent après un redémarrage)
# ═══════════════════════════════════════════════════════════════════════════════

class BoutonEtape1(discord.ui.DynamicItem[discord.ui.Button], template=r"rq:e1:(?P<d>[ersaond]):(?P<tid>\d+)"):
    """Les boutons de la direction : d = « Direction » (sur l'affiche : le panneau, éphémère, pour la tête seule),
    n = « Étape suivante » (la demande approuvée, puis chaque étape du questionnaire), s = le site, r = refuser (la
    demande, ou la candidature), a = accepter (une confirmation pour soi), o = « Oui, accepter » ; e = « Approuver la
    demande » (l'ancienne carte de l'étape 1, des tickets d'avant l'affiche)."""
    LIBELLES = {"e": ("Approuver la demande", discord.ButtonStyle.success, "envoyer"),
                "n": ("Étape suivante", discord.ButtonStyle.success, "suivant"),
                "d": ("Direction", discord.ButtonStyle.secondary, "cle"),
                "s": ("Choisir sur le site", discord.ButtonStyle.secondary, "lien"),
                "r": ("Refuser la demande", discord.ButtonStyle.danger, "interdit"),
                "a": ("Accepter", discord.ButtonStyle.success, "valider"),
                "o": ("Oui, accepter", discord.ButtonStyle.success, "valider")}

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
    """« Répondre au questionnaire » (sur l'affiche, ou sous le questionnaire posté) : le candidat y répond (son lien
    personnel vers la page web, sinon les formulaires de Discord, repris à la première page sans réponse) ; l'équipe y
    voit un APERÇU en lecture seule ; un autre est poliment refusé."""

    def __init__(self, envoi: int, libelle: str = ""):
        self.envoi = int(envoi)
        super().__init__(discord.ui.Button(label=(libelle or "Répondre · Answer")[:80], style=discord.ButtonStyle.primary,
                                           emoji=_icone("modifier"), custom_id=f"rq:rep:{int(envoi)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, ouvrir_formulaire(i, self.envoi))


class BoutonPage(discord.ui.DynamicItem[discord.ui.Button], template=r"rq:pg:(?P<eid>\d+):(?P<p>\d+)"):
    """« Continuer · page 2/3 », dans le mot pour soi qui suit un formulaire."""

    def __init__(self, envoi: int, page: int, pages: int = 0, libelle: str = ""):
        self.envoi, self.page = int(envoi), int(page)
        libelle = libelle or (f"Continuer · page {int(page)}/{int(pages)}" if pages else f"Continuer · page {int(page)}")
        super().__init__(discord.ui.Button(label=libelle[:80], style=discord.ButtonStyle.primary,
                                           emoji=_icone("suivant"), custom_id=f"rq:pg:{int(envoi)}:{int(page)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]), int(match["p"]))

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, ouvrir_formulaire(i, self.envoi, self.page))


class BoutonApercu(discord.ui.DynamicItem[discord.ui.Button], template=r"rq:vu:(?P<eid>\d+):(?P<p>\d+):(?P<c>[ps])"):
    """« Étape précédente / suivante » dans l'aperçu de l'équipe (pour soi) : la page change sur place."""

    def __init__(self, envoi: int, page: int, libelle: str = "", desactive: bool = False, cote: str = "s"):
        self.envoi, self.page = int(envoi), int(page)
        super().__init__(discord.ui.Button(label=(libelle or ("Étape suivante" if cote == "s" else "Étape précédente"))[:80],
                                           style=discord.ButtonStyle.secondary, disabled=bool(desactive),
                                           emoji=_icone("suivant" if cote == "s" else "retour"),
                                           custom_id=f"rq:vu:{int(envoi)}:{int(page)}:{cote}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]), int(match["p"]), cote=match["c"])

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, apercu_page(i, self.envoi, self.page))


BOUTONS_PERSISTANTS = (BoutonEtape1, BoutonRepondre, BoutonPage, BoutonApercu)


async def _formulaire_en_echec(i, ou: str, error: Exception) -> None:
    """Le filet des formulaires (hors `on_submit`, déjà couvert) : compté, dit, et une réponse pour soi."""
    diag.compter("questionnaire", ou, error)
    _log("[RECRUTEMENT][E7] formulaire en échec")
    _log(f"[RECRUTEMENT][E7:DETAIL] {ou} {type(error).__name__} {error}")
    try:
        await _avis(i, _t(_gid(i), "recrutement.souci"), couleur=COULEUR_CIRE)
    except discord.HTTPException as ex:
        _log(f"[RECRUTEMENT][E7:DETAIL] réponse impossible {type(ex).__name__}")


class FormulaireRefus(discord.ui.Modal):
    """« Refuser la demande » (ou « Refuser la candidature », sans questionnaire) : le formulaire est la confirmation
    (un clic de travers ne ferme rien)."""

    def __init__(self, ticket: int, guild_id: int = 0, candidature: bool = False):
        gid = int(guild_id or 0)
        cle = "recrutement.equipe.refus.titre_candidature" if candidature else "recrutement.equipe.refus.titre"
        super().__init__(title=_t(gid, cle)[:45], timeout=600)
        self.ticket = int(ticket)
        self.note = discord.ui.TextInput(style=discord.TextStyle.short, required=False, max_length=NOTE_MAX,
                                         placeholder=_t(gid, "recrutement.equipe.refus.exemple")[:100] or None)
        self.add_item(discord.ui.Label(text=_t(gid, "recrutement.equipe.refus.note")[:45],
                                       description=_t(gid, "recrutement.equipe.refus.note_aide")[:100] or None,
                                       component=self.note))

    async def on_submit(self, i: discord.Interaction):
        await _sans_echec(i, _refuser_depuis_discord(i, self.ticket, _net(self.note.value)[:NOTE_MAX]))

    async def on_error(self, i: discord.Interaction, error: Exception) -> None:
        await _formulaire_en_echec(i, "formulaire_refus", error)


class FormulairePage(discord.ui.Modal):
    """Un formulaire du questionnaire : 5 questions au plus, d'une seule étape. Le titre dit l'étape et la page ;
    chaque champ rappelle « Question 3 » et le début de la question (elle est en entier dans la carte, au-dessus)."""

    def __init__(self, envoi: dict, page: int):
        pages = pages_envoi(envoi["questions"])
        page = max(1, min(len(pages), int(page)))
        gid = int(envoi.get("guild_id") or 0)
        lot = pages[page - 1]
        etape = int(lot[0].get("etape") or 1) if lot else 1
        super().__init__(title=_t(gid, "recrutement.formulaire.titre", page=page, pages=len(pages), etape=etape)[:45],
                         timeout=FORMULAIRE_S)
        self.envoi, self.page, self.champs = int(envoi["id"]), int(page), []
        exemple = _t(gid, "recrutement.formulaire.reponse")[:100]
        for q in lot:
            champ = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=True, min_length=1,
                                         max_length=REPONSE_CANDIDAT_MAX, placeholder=exemple)
            self.add_item(discord.ui.Label(text=f"Question {int(q['rang'])}"[:45],
                                           description=extrait(q["question"], 100), component=champ))
            self.champs.append((int(q["rang"]), champ))

    async def on_submit(self, i: discord.Interaction):
        valeurs = {rang: champ.value for rang, champ in self.champs}
        await _sans_echec(i, soumettre_page(i, self.envoi, self.page, valeurs))

    async def on_error(self, i: discord.Interaction, error: Exception) -> None:
        await _formulaire_en_echec(i, "formulaire_page", error)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'ouverture du ticket : l'affiche (26/10/2026) — et la carte de l'étape 1 des tickets d'avant
# ═══════════════════════════════════════════════════════════════════════════════

def _banniere():
    """L'adresse publique de la bannière de l'affiche — None tant qu'elle n'est pas servie (un titre la remplace)."""
    url_image = getattr(visuels, "url_image", None)
    return url_image(BANNIERE) if url_image is not None else None


async def _charger_textes(guild_id: int) -> None:
    """Le cache des textes (Textes & noms) est chargé : les cartes se construisent ensuite sans attendre."""
    await textes_du_site.texte(guild_id, "recrutement.affiche.intro")


def _web():
    """Le module de la page web du candidat (`candidature_site`, l'équipe « candidature ») s'il est branché — sinon
    None : le candidat répond dans les formulaires de Discord. Ce qu'il offre : `lien_candidat(i, ticket)` (le lien
    personnel, sur le bouton du ticket) et `inviter(g, e)` (le message privé d'un chef d'équipe). Un test le donne à
    `setup(web=…)` ou l'injecte dans `sys.modules`."""
    global _web_absent
    if _web_module is not None:
        return _web_module
    m = sys.modules.get("candidature_site")
    if m is not None:
        return m
    if time.monotonic() < _web_absent:
        return None
    try:
        return importlib.import_module("candidature_site")
    except ModuleNotFoundError:
        _web_absent = time.monotonic() + 60.0
        return None
    except Exception as ex:  # le module est là mais ne se charge pas : les formulaires de Discord prennent le relais
        _web_absent = time.monotonic() + 60.0
        _log("[RECRUTEMENT][E24] page du candidat illisible")
        _log(f"[RECRUTEMENT][E24:DETAIL] {type(ex).__name__} {ex}")
        return None


def _page_candidat():
    """`lien_candidat` de la page web du candidat, si elle est branchée — sinon None (les formulaires de Discord)."""
    return getattr(_web(), "lien_candidat", None)


async def _donnees_affiche(g, tid: int, s: dict, pris_par=None) -> dict:
    """Tout ce que l'affiche et le panneau de la direction montrent, lu dans la base (jamais dans un message)."""
    rows = await _lire_tolerant("SELECT user_id, panel_id, answers FROM tickets WHERE id=? AND guild_id=?",
                                (int(tid), g.id))
    reponses: dict = {}
    if rows:
        try:
            reponses = json.loads(rows[0][2] or "{}")
        except (TypeError, ValueError):
            reponses = {}
    pid = s["panneau"] or (str(rows[0][1] or "") if rows else "")
    c = await _cfg(g.id)
    pnl = ((c.get("ticket_panels") or {}).get(pid) or {}) if isinstance(c, dict) else {}
    mode = _mode(s)
    e = await _envoi(s["envoi_id"]) if s["envoi_id"] else None
    etat = {"etape1": "direct" if mode == "direct" else "demande", "etape2": "questionnaire",
            "reponses": "reponses"}.get(s["etape"], s["etape"])
    d = {"gid": g.id, "ticket": int(tid), "candidat": int(s["candidat_id"]), "mode": mode, "etat": etat,
         "texte_panneau": str(pnl.get("welcome_message") or "") if isinstance(pnl, dict) else "",
         "reponses": reponses if isinstance(reponses, dict) else {}, "banniere": _banniere()}
    if e is not None:
        d.update(nb_etapes=len(etapes_de(e)), nb_questions=len(e["questions"]), liens=e["liens"],
                 envoi=e["id"] if e["statut"] in EN_ATTENTE else 0, auto=str(e["origine"]).startswith("ouverture"),
                 repondu_le=e["repondu_le"] if e["statut"] == "repondu" else 0,
                 porte=int(e["etape_ouverte"] or 0) > 0, numeros=_numeros(e))
        if etat == "questionnaire":
            d.update(par=e["envoye_par"], quand=e["envoye_le"])
        elif etat == "reponses":
            d.update(quand=e["repondu_le"])
    else:
        d.update(nb_etapes=int(s["etapes_annonce"] or 1), nb_questions=int(s["annonce"] or 0))
    if etat in FINALES:
        d.update(par=s["decide_par"], quand=s["decide_le"])
    if _extras is not None:
        try:
            d["extras"] = await _extras(g, int(tid), pris_par)
        except Exception as ex:  # le bas du panneau (prise en charge, boutons du ticket) manque : le reste suit
            _log("[RECRUTEMENT][E13] panneau de l'équipe incomplet")
            _log(f"[RECRUTEMENT][E13:DETAIL] ticket={tid} {type(ex).__name__} {ex}")
    await _charger_textes(g.id)
    return d


async def vue_direction(g, tid: int):
    """Le panneau de la direction (éphémère) pour ce ticket — None sans suivi de recrutement."""
    s = await _suivi(g.id, tid)
    if s is None:
        return None
    return panneau_direction(await _donnees_affiche(g, tid, s))


async def citer_sur_affiche(g, ch, tid: int, mentions: str, autorises) -> bool:
    """L'AFFICHE cite l'équipe le temps d'une modification — une modification ne prévient personne, et Discord fait
    entrer qui y est cité dans un fil privé : l'équipe voit le ticket sans qu'aucun message de plus n'y soit posé.
    `reprendre_affiche` retire ensuite la ligne. Rend False si le ticket n'a pas d'affiche (le bot pose alors sa carte
    d'équipe, puis la supprime)."""
    s = await _suivi(g.id, tid)
    if s is None or s.get("carte") != "affiche" or not s.get("carte_id") or ch is None or not str(mentions or "").strip():
        return False
    vue = await vue_affiche(g, int(tid), s=s)
    vue.add_item(discord.ui.Container(discord.ui.TextDisplay("-# " + str(mentions)[:1900]), accent_color=COULEUR_MER))
    await ch.get_partial_message(int(s["carte_id"])).edit(view=vue, allowed_mentions=autorises)
    return True


async def reprendre_affiche(g, ch, tid: int) -> bool:
    """L'affiche reprend sa forme (sans la ligne de l'équipe)."""
    s = await _suivi(g.id, tid)
    if s is None or s.get("carte") != "affiche" or not s.get("carte_id"):
        return False
    return await _editer(ch, s["carte_id"], await vue_affiche(g, int(tid), s=s))


async def vue_affiche(g, tid: int, *, pris_par=None, s=None):
    """L'affiche du ticket telle qu'elle doit être MAINTENANT — None si le ticket n'a pas de suivi de recrutement."""
    s = s or await _suivi(g.id, tid)
    if s is None:
        return None
    return carte_affiche(await _donnees_affiche(g, tid, s, pris_par))


async def est_affiche(guild_id: int, tid: int) -> bool:
    """Ce ticket a-t-il une affiche (ouvert depuis le 26/10/2026) ? Sinon : l'ancienne carte de l'étape 1."""
    s = await _suivi(guild_id, tid) if _get_db is not None else None
    return bool(s and s["carte"] == "affiche" and s["carte_id"])


async def poser_affiche(g, ch, tid: int, candidat_id: int, pnl: dict | None = None, panneau: str = "") -> int:
    """L'ouverture d'un ticket de recrutement : le suivi commence (le mode du panneau figé pour ce ticket), puis
    l'AFFICHE est posée — le message unique du ticket, qui cite le candidat sans le prévenir. Mode « automatique » : le
    questionnaire part aussitôt et l'affiche est réécrite. Rend l'identifiant de l'affiche. Une panne de Discord
    remonte (le bot pose alors l'ancienne carte de décision)."""
    pnl = pnl if isinstance(pnl, dict) else {}
    p = await parcours(g.id, panneau)
    accueil = str(pnl.get("welcome_message") or "")
    nb_e, nb_q = (0, 0) if p["mode"] == "direct" else await annonce_detail(g.id, accueil, panneau or None)
    t = _maintenant()
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO recrutement_suivi (guild_id, ticket_id, candidat_id, salon_id, etape,"
                         " annonce, etapes_annonce, panneau, carte, mode, cree_le, maj_le)"
                         " VALUES (?,?,?,?,'etape1',?,?,?,'affiche',?,?,?)",
                         (g.id, int(tid), int(candidat_id), int(getattr(ch, "id", 0) or 0), int(nb_q), int(nb_e),
                          str(panneau or ""), p["mode"], t, t))
        await db.commit()
    m = await ch.send(view=await vue_affiche(g, tid), allowed_mentions=discord.AllowedMentions.none())
    mid = int(getattr(m, "id", 0) or 0)
    try:
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_suivi SET carte_id=? WHERE guild_id=? AND ticket_id=?",
                             (mid, g.id, int(tid)))
            await db.commit()
    except (sqlite3.Error, asyncio.TimeoutError, OSError) as ex:  # l'affiche est posée : on ne la reposera pas
        _log("[RECRUTEMENT][E10] affiche non retenue")
        _log(f"[RECRUTEMENT][E10:DETAIL] ticket={tid} {type(ex).__name__} {ex}")
    if p["mode"] == "automatique":
        st, rep = await envoyer(g, tid, getattr(g, "me", None), None, depuis="ouverture")
        if st != 200:   # l'équipe garde « Approuver la demande » sur l'affiche ; le site le dit
            _log("[RECRUTEMENT][E12] questionnaire automatique non parti")
            _log(f"[RECRUTEMENT][E12:DETAIL] ticket={tid} {st} {rep.get('erreur', '')}")
            await _noter(g.id, tid, "automatique_echec", 0, str(rep.get("erreur") or "")[:200])
    return mid


async def poser_etape1(g, ch, tid: int, candidat_id: int, *, nombre: int = 0) -> None:
    """La carte de l'étape 1 d'AVANT l'affiche (les tickets ouverts avant le 26/10/2026, les démonstrations) : le suivi
    commence (étape 1, `nombre` : les questions annoncées) et la carte de l'équipe est posée. Une panne de Discord
    remonte."""
    t = _maintenant()
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO recrutement_suivi (guild_id, ticket_id, candidat_id, salon_id, etape,"
                         " annonce, cree_le, maj_le) VALUES (?,?,?,?,'etape1',?,?,?)",
                         (g.id, int(tid), int(candidat_id), int(getattr(ch, "id", 0) or 0), int(nombre), t, t))
        await db.commit()
    await textes_du_site.texte(g.id, "recrutement.equipe.decision")   # le cache des textes est chargé
    m = await ch.send(view=carte_etape1(tid, nombre=nombre, guild_id=g.id),
                      allowed_mentions=discord.AllowedMentions.none())
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
           "fermeture_par", "fermeture_motif", "decide_par", "decide_le", "cree_le", "maj_le", "panneau", "carte",
           "mode", "etapes_annonce")
_COLS_E = ("id", "guild_id", "ticket_id", "candidat_id", "questions", "liens", "statut", "origine", "renvoi", "envoye_par",
           "cree_le", "envoye_le", "repondu_le", "salon_id", "messages", "etapes", "etape_ouverte", "etape_envoyee",
           "etape_fiche", "message_etape", "nature", "metier")


async def _suivi(guild_id: int, tid: int) -> dict | None:
    r = await _un(f"SELECT {', '.join(_COLS_S)} FROM recrutement_suivi WHERE guild_id=? AND ticket_id=?",
                  (int(guild_id), int(tid)))
    return dict(zip(_COLS_S, tuple(r))) if r is not None else None


async def _suivi_ou_creer(g, tid: int, tk: dict, ch) -> dict:
    """Le suivi d'un ticket ouvert ; un ticket d'avant le recrutement en deux étapes y entre à l'étape 1."""
    t = _maintenant()
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO recrutement_suivi (guild_id, ticket_id, candidat_id, salon_id, etape,"
                         " panneau, cree_le, maj_le) VALUES (?,?,?,?,'etape1',?,?,?)",
                         (g.id, int(tid), int(tk["user"]), int(getattr(ch, "id", 0) or 0),
                          str(tk.get("panel_id") or ""), t, t))
        await db.commit()
    return await _suivi(g.id, tid)


def _envoi_dict(r) -> dict:
    d = dict(zip(_COLS_E, tuple(r)))
    d["questions"] = [q for q in _json_liste(d["questions"]) if isinstance(q, dict)]
    d["liens"] = [x for x in _json_liste(d["liens"]) if isinstance(x, dict)]
    d["messages"] = [int(x) for x in _json_liste(d["messages"]) if str(x).isdigit()]
    d["renvoi"] = bool(d["renvoi"])
    d["etapes"] = [x for x in _json_liste(d.get("etapes")) if isinstance(x, dict)]
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


def bilan(questions_: list, reponses_: dict, corrections_: dict, exigence: int = EXIGENCE) -> dict:
    """Où en est la correction. `reussite` : tout est corrigé et le taux de réponses justes atteint l'exigence du
    panneau (100 % par défaut) — une aide affichée : la décision reste celle de la personne."""
    total = len(questions_)
    rangs = [int(q["rang"]) for q in questions_]
    repondues = sum(1 for r in rangs if r in reponses_)
    corrigees = sum(1 for r in rangs if (corrections_.get(r) or {}).get("juste") is not None)
    justes = sum(1 for r in rangs if (corrections_.get(r) or {}).get("juste") is True)
    complet = total > 0 and corrigees == total
    taux = round(100 * justes / total) if total else 0
    return {"total": total, "repondues": repondues, "corrigees": corrigees, "justes": justes,
            "fausses": corrigees - justes, "complet": complet, "reussite": complet and taux >= int(exigence),
            "taux": taux, "exigence": int(exigence)}


async def _bilan_courant(s: dict, exigence: int = EXIGENCE) -> dict | None:
    """Le bilan du questionnaire EN COURS du ticket (le dernier envoyé) s'il est répondu — None sinon : un
    questionnaire renvoyé et pas encore répondu ne laisse pas l'ancien décider à sa place."""
    e = await _envoi(s["envoi_id"]) if s and s.get("envoi_id") else None
    if e is None or e["statut"] != "repondu":
        return None
    return dict(bilan(e["questions"], await _reponses(e["id"]), await _corrections(e["id"]), exigence), envoi=e["id"])


async def _editer(ch, mid: int, vue) -> bool:
    """Une carte réécrite (best effort : le ticket peut avoir été supprimé entre-temps)."""
    if ch is None or not mid or vue is None:
        return False
    try:
        await ch.get_partial_message(int(mid)).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.HTTPException as ex:
        _log("[RECRUTEMENT][E4] carte non réécrite")
        _log(f"[RECRUTEMENT][E4:DETAIL] message={mid} {type(ex).__name__} {getattr(ex, 'status', '')}")
        return False


async def _editer_carte_staff(g, ch, s: dict | None, etat: str, **kw) -> None:
    """La carte de l'équipe dit le nouvel état : l'AFFICHE (relue en entier dans la base) d'un ticket ouvert depuis le
    26/10/2026 ; sinon l'ancienne carte de l'étape 1."""
    if s is None or not s.get("carte_id"):
        return
    if s.get("carte") == "affiche":
        await _editer(ch, s["carte_id"], await vue_affiche(g, int(s["ticket_id"])))
        return
    await _editer(ch, s["carte_id"], carte_etape1(int(s["ticket_id"]), etat, candidat=int(s["candidat_id"]),
                                                  guild_id=getattr(g, "id", 0), **kw))


async def _editer_cartes(ch, e: dict, etat: str, quand: int = 0) -> None:
    """Le message de l'étape (le nouveau parcours) ou le dernier message du questionnaire posté (celui du bouton) dit
    maintenant où en est l'envoi."""
    if e.get("message_etape"):
        await _editer(ch, e["message_etape"], carte_etape(e, etat, quand=quand))
        return
    if not e.get("messages"):
        return
    if _invitation(e):
        vue = _vue_decision(_t(int(e.get("guild_id") or 0), {"repondu": "recrutement.etape2.envoyees",
                                                             "remplace": "recrutement.etape2.remplace"}.get(
            etat, "recrutement.etape2.clos"), quand=f"<t:{int(quand or _maintenant())}:f>"), COULEUR_MER)
        await _editer(ch, e["messages"][-1], vue)
        return
    vues = cartes_etape2(e, etat, quand=quand)
    if len(vues) == len(e["messages"]):
        await _editer(ch, e["messages"][-1], vues[-1])


def _invitation(e: dict) -> bool:
    """L'envoi a été posté en invitation courte (la page web), pas en questionnaire complet."""
    return str(e.get("origine") or "").endswith("+web")


async def _poster_cartes(ch, e: dict) -> list:
    """Les messages du questionnaire, dans l'ordre ; le candidat est prévenu par le premier. Un échec retire ce qui
    était déjà posé et remonte."""
    ids = []
    try:
        vues = [carte_invitation(e)] if _invitation(e) else cartes_etape2(e, "ouvert")
        for k, vue in enumerate(vues):
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
    return {"etape1": "La demande attend la décision de l'équipe.",
            "etape2": "Le questionnaire est déjà envoyé : le candidat y répond.",
            "reponses": "Les réponses sont arrivées : à corriger sur le site.",
            "refus_etape1": "La demande est refusée : le ticket se ferme.",
            "refuse": "La candidature est refusée : le ticket se ferme.",
            "accepte": "La candidature est acceptée."}.get(etape, "Cette candidature n'est plus à cette étape.")


def _mode(s: dict | None) -> str:
    """Le mode figé pour ce ticket à son ouverture (un ticket d'avant le 26/10/2026 : l'approbation)."""
    m = str((s or {}).get("mode") or "")
    return m if m in MODES else MODE_DEFAUT


async def _personnelles(g, auteur, corps: dict) -> tuple:
    """Les questions ÉCRITES pour ce seul candidat (`etapes[k].nouvelles` : {question, reponse, variantes, theme,
    banque}) : vérifiées comme celles de la banque (jamais une question qui dit sa réponse), gardées dans l'instantané
    de son envoi seulement — ou ajoutées aussi à la banque (`banque: true`). Rend (corps où elles sont devenues des
    identifiants, [questions personnelles]) ou lève `_Invalide`."""
    etapes = corps.get("etapes")
    if not isinstance(etapes, list) or not any(isinstance(x, dict) and x.get("nouvelles") for x in etapes):
        return corps, []
    persos, sortie, total = [], [], 0
    for x in etapes:
        if not isinstance(x, dict):
            raise _Invalide("Chaque étape est un objet {titre, consigne, questions}.")
        nouvelles = x.get("nouvelles") or []
        if not isinstance(nouvelles, list):
            raise _Invalide("« nouvelles » : une liste de questions.")
        total += len(nouvelles)
        if total > NOUVELLES_MAX:
            raise _Invalide(f"{NOUVELLES_MAX} questions écrites pour lui au plus.")
        ids = list(x.get("questions") or []) if isinstance(x.get("questions") or [], list) else []
        for n in nouvelles:
            if not isinstance(n, dict):
                raise _Invalide("Chaque question écrite est un objet {question, reponse}.")
            question = _texte(n, "question", mini=QUESTION_MIN, maxi=QUESTION_MAX)
            reponse = _texte(n, "reponse", mini=1, maxi=REPONSE_MAX)
            variantes = _variantes(n.get("variantes", []), reponse)
            vu = fuite(question, reponse, variantes)
            if vu:
                raise _Invalide(f"« {extrait(question, 60)} » : la réponse attendue apparaît dans la question.")
            theme = _theme(n.get("theme") or "jeu")
            if _booleen(n, "banque", False):
                st, rep = await enregistrer_question(g, auteur, {"theme": theme, "question": question, "reponse": reponse,
                                                                 "variantes": variantes, "statut": "confirme"})
                if st != 200:
                    raise _Invalide(rep.get("erreur") or "La question n'a pas pu entrer dans la banque.")
                ids.append(rep["question"]["id"])
                continue
            q = {"id": f"p-{secrets.token_hex(5)}", "theme": theme, "question": question, "reponse": reponse,
                 "variantes": variantes, "type": "texte", "difficulte": "moyenne", "source": "", "section": "",
                 "extrait": "", "statut": "confirme", "actif": True, "retiree": False, "ordre": 0, "fuite": "",
                 "perso": True}
            persos.append(q)
            ids.append(q["id"])
        sortie.append(dict({k: v for k, v in x.items() if k != "nouvelles"}, questions=ids))
    return dict(corps, etapes=sortie), persos


async def _mp(g, uid: int, texte: str, boutons=()) -> bool:
    """Un message privé au candidat (une carte). Ses messages privés fermés, ou parti du serveur : rien ne bloque —
    c'est dit (journal du bot, historique de la candidature), et le message est aussi dans le ticket."""
    texte = str(texte or "").strip()
    if not texte:
        return True
    m = g.get_member(int(uid)) if g is not None else None
    if m is None or getattr(m, "send", None) is None:
        return False
    items = [discord.ui.TextDisplay(texte[:3900])]
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=COULEUR_LAITON))
    try:
        await m.send(view=v)
        return True
    except discord.HTTPException as ex:
        _log("[RECRUTEMENT][E14] message privé impossible")
        _log(f"[RECRUTEMENT][E14:DETAIL] {type(ex).__name__} {getattr(ex, 'status', '')} {getattr(ex, 'code', '')}")
        return False


async def _publier(g, ch, s: dict, e: dict) -> tuple:
    """Le questionnaire part dans le ticket → (messages du questionnaire d'avant, message de l'étape). Le nouveau
    parcours (un ticket à affiche) : le MESSAGE DE L'ÉTAPE ouverte, qui prévient le candidat. Un ticket d'avant : le
    questionnaire en entier (formulaires de Discord), ou une invitation courte vers la page web."""
    if s.get("carte") == "affiche":
        m = await ch.send(view=carte_etape(e, "ouverte"), allowed_mentions=_ping(e["candidat_id"]))
        return [], int(getattr(m, "id", 0) or 0)
    return await _poster_cartes(ch, e), 0


async def _retirer_message_etape(ch, e: dict | None) -> None:
    """Le message de l'étape s'efface (une étape suivante, une décision) : le ticket garde au plus deux messages du
    bot. Ce qui y était (questions, réponses) reste dans la base : le site et le transcript n'en dépendent pas."""
    if not e or not e.get("message_etape"):
        return
    if ch is not None:
        try:
            await ch.get_partial_message(int(e["message_etape"])).delete()
        except discord.NotFound:
            pass  # déjà effacé (à la main, ou le ticket se ferme) : rien à faire
        except discord.HTTPException as ex:
            _log("[RECRUTEMENT][E17] message d'étape non retiré")
            _log(f"[RECRUTEMENT][E17:DETAIL] message={e['message_etape']} {type(ex).__name__} {getattr(ex, 'status', '')}")
    async with _get_db() as db:
        await db.execute("UPDATE recrutement_envois SET message_etape=0 WHERE id=?", (int(e["id"]),))
        await db.commit()
    e["message_etape"] = 0


async def _salon_ticket(g, e: dict):
    """Le fil (ou le salon) du ticket d'un envoi, s'il est encore ouvert — None sinon (un chef d'équipe n'en a pas)."""
    if not int(e.get("ticket_id") or 0):
        return None
    try:
        ch, _tk = await _ticket_ouvert(g, int(e["ticket_id"]))
    except discord.HTTPException as ex:
        _log("[RECRUTEMENT][E1] ticket illisible")
        _log(f"[RECRUTEMENT][E1:DETAIL] ticket={e['ticket_id']} {type(ex).__name__} {getattr(ex, 'status', '')}")
        return None
    return ch


async def clore_envoi(e: dict, t: int) -> bool:
    """Toutes les réponses sont là : l'envoi se ferme UNE fois (le premier qui y arrive) — « repondu », sa dernière étape
    envoyée — et la candidature passe à « réponses ». Rend True pour ce premier. Appelée par les formulaires de Discord
    et par la page web (`envoyer_etape`, à la dernière étape), puis `annoncer_reponses`."""
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_envois SET statut='repondu', repondu_le=?, etape_envoyee=CASE WHEN"
                               " etape_ouverte > 0 THEN etape_ouverte ELSE etape_envoyee END WHERE id=? AND statut IN"
                               " (?, ?)", (int(t), int(e["id"]), *EN_ATTENTE))
        premier = (cur.rowcount or 0) > 0
        if premier and int(e.get("ticket_id") or 0):
            await db.execute("UPDATE recrutement_suivi SET etape='reponses', maj_le=? WHERE guild_id=? AND ticket_id=?"
                             " AND envoi_id=? AND etape='etape2'", (int(t), e["guild_id"], e["ticket_id"], e["id"]))
        await db.commit()
    return premier


async def annoncer_reponses(g, e: dict, t: int) -> None:
    """Après `clore_envoi` (le premier seulement) : le message de l'étape (ou l'ancienne carte) dit « Réponses
    envoyées », l'affiche et la carte de l'équipe suivent, l'historique et le journal le notent. Un chef d'équipe (sans
    ticket) : le journal seulement."""
    e = await _envoi(e["id"]) or e
    n, cand = len(e["questions"]), int(e["candidat_id"])
    if int(e.get("ticket_id") or 0):
        ch = await _salon_ticket(g, e)
        await _editer_cartes(ch, e, "repondu", t)
        await _editer_carte_staff(g, ch, await _suivi(g.id, e["ticket_id"]), "reponses", nombre=n, quand=t)
        await _noter(g.id, e["ticket_id"], "reponses", cand, f"{n} réponse(s)")
        await _au_journal(g, "recrutement.reponses", f"Recrutement : réponses reçues de <@{cand}> ({n} question(s)) —"
                          " à corriger sur le site", membre_id=cand)
    else:
        await _au_journal(g, "recrutement.chef_reponses", f"Chef d'équipe : réponses reçues de <@{cand}> ({n} "
                          "question(s)) — à corriger sur le site", membre_id=cand)


async def etape_recue(g, e: dict, etape: int) -> None:
    """Une étape envoyée, pas la dernière (contrat « passage d'étape ») : le message de l'étape devient « Réponses
    reçues — la direction les regarde » — RÉÉCRIT, jamais doublé —, l'affiche suit, l'historique et le journal le
    notent. `etape` : son numéro dans le questionnaire (1…N). Appelée par `envoyer_etape` (la page web) et par les
    formulaires de Discord."""
    e = await _envoi(e["id"]) or e
    cand, fiche = int(e["candidat_id"]), int(e.get("etape_fiche") or 0)
    if int(e.get("ticket_id") or 0):
        ch = await _salon_ticket(g, e)
        if e.get("message_etape"):
            await _editer(ch, e["message_etape"], carte_etape(e, "recue"))
        await _editer_carte_staff(g, ch, await _suivi(g.id, e["ticket_id"]), "envoye")
        await _noter(g.id, e["ticket_id"], "etape_recue", cand, f"étape {int(etape) + fiche}")
        texte = f"Recrutement : étape {int(etape) + fiche} reçue de <@{cand}> — à regarder sur le site"
    else:
        texte = f"Chef d'équipe : étape {int(etape)} reçue de <@{cand}> — à regarder sur le site"
    await _au_journal(g, "recrutement.etape_recue", texte, membre_id=cand)


async def etape_suivante(g, envoi_id: int, auteur) -> tuple:
    """La direction ouvre l'étape suivante (contrat « passage d'étape ») → (fait, message). Réservée à la tête. Refusée
    tant que l'étape ouverte n'est pas envoyée. Sinon : `etape_ouverte + 1`, l'ancien message d'étape SUPPRIMÉ, le
    nouveau posté avec une mention qui PRÉVIENT le candidat (un chef d'équipe : son message privé, par la page web),
    l'affiche suit, le journal le note."""
    if _est_tete is not None and not _est_tete(auteur):
        return False, _t(g.id, "recrutement.equipe.reserve")
    e = await _envoi(envoi_id)
    if e is None or e["guild_id"] != g.id:
        return False, "Questionnaire introuvable."
    if e["statut"] not in EN_ATTENTE:
        return False, "Ce questionnaire n'est plus ouvert."
    k, n, fiche = int(e["etape_ouverte"] or 0), len(etapes_de(e)), int(e["etape_fiche"] or 0)
    if not k:
        return False, "Ce questionnaire n'a pas d'étapes à ouvrir une à une."
    if int(e["etape_envoyee"] or 0) < k:
        return False, _t(g.id, "recrutement.direction.pas_envoyee", numero=k + fiche)
    if k >= n:
        return False, "C'est la dernière étape : accepte ou refuse."
    ch = None
    if int(e["ticket_id"] or 0):
        ch = await _salon_ticket(g, e)
        if ch is None:
            return False, FERME
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_envois SET etape_ouverte=? WHERE id=? AND etape_ouverte=? AND statut"
                               " IN (?, ?)", (k + 1, int(e["id"]), k, *EN_ATTENTE))
        await db.commit()
    if (cur.rowcount or 0) < 1:
        return False, "L'étape suivante est déjà ouverte."
    cand = int(e["candidat_id"])
    if ch is not None:
        await _retirer_message_etape(ch, e)
        e = await _envoi(e["id"])
        try:
            m = await ch.send(view=carte_etape(e, "ouverte"), allowed_mentions=_ping(cand))
        except discord.HTTPException as ex:
            async with _get_db() as db:
                await db.execute("UPDATE recrutement_envois SET etape_ouverte=? WHERE id=?", (k, int(e["id"])))
                await db.commit()
            _log("[RECRUTEMENT][E2] étape suivante non posée")
            _log(f"[RECRUTEMENT][E2:DETAIL] envoi={e['id']} {type(ex).__name__} {getattr(ex, 'status', '')}")
            return False, DISCORD_HS
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_envois SET message_etape=? WHERE id=?",
                             (int(getattr(m, "id", 0) or 0), int(e["id"])))
            await db.commit()
        await _editer_carte_staff(g, ch, await _suivi(g.id, e["ticket_id"]), "envoye")
        await _noter(g.id, e["ticket_id"], "etape_suivante", getattr(auteur, "id", 0), f"étape {k + 1 + fiche}")
    else:
        inviter = getattr(_web(), "inviter", None)
        if inviter is not None:
            try:
                await inviter(g, await _envoi(e["id"]))
            except Exception as ex:  # l'étape est ouverte ; le message privé manque : c'est dit
                _log("[RECRUTEMENT][E18] invitation du chef impossible")
                _log(f"[RECRUTEMENT][E18:DETAIL] envoi={e['id']} {type(ex).__name__} {ex}")
    await _au_journal(g, "recrutement.etape_suivante", f"Recrutement : étape {k + 1 + fiche} ouverte pour <@{cand}> par "
                      f"<@{getattr(auteur, 'id', 0)}>", membre_id=cand, auteur_id=getattr(auteur, "id", 0))
    return True, f"Étape {k + 1 + fiche} ouverte : le candidat est prévenu."


async def _etape_complete(i, e: dict) -> None:
    """Toutes les réponses de l'étape OUVERTE sont là (formulaires de Discord) : la dernière ferme l'envoi
    (`_terminer`) ; une autre devient « envoyée » — il attend la décision de la direction (`etape_recue`)."""
    k, n = int(e["etape_ouverte"] or 0), len(etapes_de(e))
    if not k or k >= n:
        return await _terminer(i, e)
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_envois SET etape_envoyee=? WHERE id=? AND etape_envoyee < ? AND statut"
                               " IN (?, ?)", (k, int(e["id"]), k, *EN_ATTENTE))
        premier = (cur.rowcount or 0) > 0
        await db.commit()
    await _avis(i, _t(i.guild.id, "recrutement.etape.avis", numero=k + int(e.get("etape_fiche") or 0)), efface=False,
                couleur=COULEUR_VERT)
    if premier:
        await etape_recue(i.guild, e, k)


async def _tete(i) -> bool:
    """La tête (le fondateur, la direction) — revérifiée côté bot à CHAQUE clic. Sans ce réglage (les tests d'avant) :
    l'équipe autorisée par `autorise`."""
    if _est_tete is not None:
        return bool(_est_tete(i.user))
    return await _peut(i)


async def _apercu(i, e: dict, page: int = 0) -> None:
    """L'aperçu en lecture seule, pour soi (la direction a touché « Répondre au questionnaire »)."""
    vue = carte_apercu(e, page, await _reponses(e["id"]), corriger=_lien is not None)
    if i.response.is_done():
        await i.followup.send(view=vue, ephemeral=True)
    else:
        await i.response.send_message(view=vue, ephemeral=True)


async def apercu_page(i, eid: int, page: int) -> None:
    """« Étape précédente / suivante » dans l'aperçu : la page change sur place (la tête seulement)."""
    if not pret() or i.guild is None:
        return await _avis(i, _t(_gid(i), "recrutement.demarre"))
    if not await _tete(i):
        return await _avis(i, _t(i.guild.id, "recrutement.equipe.reserve"))
    e = await _envoi(eid)
    if e is None or e["guild_id"] != i.guild.id:
        return await _avis(i, _t(i.guild.id, "recrutement.introuvable"))
    await i.response.edit_message(view=carte_apercu(e, page, await _reponses(eid), corriger=_lien is not None))


async def _lien_web_candidat(i, e: dict, fn) -> bool:
    """Le candidat touche « Répondre au questionnaire » et la page web est là : son lien personnel (`lien_candidat`).
    La fonction répond elle-même, ou rend l'adresse (on la donne, pour lui seul). Rend False si rien n'a été répondu
    (les formulaires de Discord prennent le relais)."""
    try:
        res = await fn(i, int(e["ticket_id"]))
    except Exception as ex:  # la page web ne répond pas : les formulaires de Discord prennent le relais
        _log("[RECRUTEMENT][E18] lien du candidat indisponible")
        _log(f"[RECRUTEMENT][E18:DETAIL] envoi={e['id']} {type(ex).__name__} {ex}")
        res = None
    if isinstance(res, str) and res.startswith("https://"):
        bouton = discord.ui.Button(label=_t(i.guild.id, "recrutement.bouton.questionnaire")[:80], url=res[:512])
        await _avis(i, _t(i.guild.id, "recrutement.lien_candidat"), efface=False, boutons=[bouton])
        return True
    return bool(i.response.is_done())


async def envoyer(g, tid: int, auteur, corps: dict | None, *, depuis: str = "etape1") -> tuple[int, dict]:
    """Le questionnaire part : la demande approuvée (`depuis` « etape1 »), dès l'ouverture (« ouverture », un panneau
    automatique), ou un nouveau à la place du précédent (« renvoi »). La sélection réellement envoyée est figée dans
    l'envoi (un instantané : la question, la réponse attendue et ses variantes telles qu'elles étaient, ses étapes,
    les questions écrites pour lui), les liens aussi. Rien n'est posé en double : l'affiche est réécrite."""
    ch, tk, refus = await _ticket(g, tid)
    if refus:
        return refus
    try:
        corps, persos = await _personnelles(g, auteur, corps if isinstance(corps, dict) else {})
    except _Invalide as ex:
        return _erreur(str(ex))
    async with _verrou(g.id, tid):
        s = await _suivi_ou_creer(g, tid, tk, ch)
        if s["fermeture_le"]:
            return _erreur("La fermeture de ce ticket est déjà prévue.", 409, etape=s["etape"])
        if (depuis in ("etape1", "ouverture") and s["etape"] != "etape1") or \
                (depuis == "renvoi" and s["etape"] not in ("etape2", "reponses")):
            return _erreur(_texte_etape(s["etape"]), 409, etape=s["etape"])
        choisi = any(corps.get(k) for k in ("questions", "modele", "derniere", "etapes"))
        if _mode(s) == "direct" and depuis != "renvoi" and not choisi:
            return _erreur("Ce panneau est réglé sans questionnaire : la décision se prend sur sa fiche.", 409,
                           etape=s["etape"])
        pid = s["panneau"] or str(tk.get("panel_id") or "")
        pnl = ((await _cfg(g.id)).get("ticket_panels") or {}).get(pid) or {}
        accueil = str(pnl.get("welcome_message") or "") if isinstance(pnl, dict) else ""
        status, sel = await selection(g.id, corps, accueil, panneau=pid or None, personnelles=persos)
        if status != 200:
            return status, sel
        qs = [dict({c: q[c] for c in _SNAPSHOT}, rang=k + 1, etape=int(q.get("etape") or 1),
                   **({"perso": True} if q.get("perso") else {})) for k, q in enumerate(sel["questions"])]
        lns = await liens(g.id)
        origine = ("ouverture:" if depuis == "ouverture" else "") + sel["origine"]
        nouveau = s.get("carte") == "affiche"      # le nouveau parcours : une étape à la fois (contrat « passage d'étape »)
        if _page_candidat() is not None and not nouveau:
            origine += "+web"           # un ticket d'avant l'affiche : une invitation courte vers la page web
        fiche = int(nouveau and bool(fiche_effective(await parcours(g.id, pid or None), pnl)))
        t = _maintenant()
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO recrutement_envois (guild_id, ticket_id, candidat_id, questions, liens, statut, origine,"
                " renvoi, envoye_par, cree_le, salon_id, etapes, etape_ouverte, etape_fiche)"
                " VALUES (?,?,?,?,?,'prepare',?,?,?,?,?,?,?,?)",
                (g.id, int(tid), int(tk["user"]), json.dumps(qs, ensure_ascii=False),
                 json.dumps(lns, ensure_ascii=False), origine, int(depuis == "renvoi"),
                 int(getattr(auteur, "id", 0) or 0), t, int(ch.id), json.dumps(sel["etapes"], ensure_ascii=False),
                 int(nouveau), fiche))
            eid = int(cur.lastrowid)
            await db.commit()
        e = await _envoi(eid)
        ancien = await _envoi(s["envoi_id"]) if s["envoi_id"] else None
        if ancien is not None and ancien.get("message_etape"):
            await _retirer_message_etape(ch, ancien)   # deux messages du bot au plus : l'ancienne étape s'efface d'abord
        try:
            messages, message_etape = await _publier(g, ch, s, e)
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
            await db.execute("UPDATE recrutement_envois SET statut='envoye', envoye_le=?, messages=?, message_etape=?"
                             " WHERE id=?", (t, json.dumps(messages), int(message_etape), eid))
            if remplace:
                await db.execute("UPDATE recrutement_envois SET statut='remplace' WHERE id=? AND statut IN (?, ?)",
                                 (ancien["id"], *EN_ATTENTE))
            await db.execute("UPDATE recrutement_suivi SET etape='etape2', envoi_id=?, maj_le=? WHERE guild_id=?"
                             " AND ticket_id=?", (eid, t, g.id, int(tid)))
            await db.commit()
        if remplace and not ancien.get("message_etape"):
            await _editer_cartes(ch, ancien, "remplace")
        s = await _suivi(g.id, tid)
        await _editer_carte_staff(g, ch, s, "envoye", nombre=len(qs), par=getattr(auteur, "id", 0), quand=t)
        quoi = {"renvoi": "renvoi", "ouverture": "questionnaire_auto"}.get(depuis, "questionnaire")
        n_etapes = len(sel["etapes"])
        detail = f"{len(qs)} question(s) · {n_etapes} étape(s) · {sel['origine']}" + \
            (f" · {len(persos)} écrite(s) pour lui" if persos else "")
        await _noter(g.id, tid, quoi, getattr(auteur, "id", 0), detail)
        phrase = {"renvoi": "Recrutement : nouveau questionnaire envoyé",
                  "ouverture": "Recrutement : questionnaire envoyé tout seul à l'ouverture"}.get(
            depuis, "Recrutement : demande approuvée, questionnaire envoyé")
        await _au_journal(g, f"recrutement.{quoi}",
                          phrase + f" à <@{int(tk['user'])}> ({len(qs)} question(s), {n_etapes} étape(s))"
                          + (f" par <@{auteur.id}>" if depuis != "ouverture" and auteur is not None else ""),
                          membre_id=int(tk["user"]), auteur_id=getattr(auteur, "id", 0))
    #  La demande approuvée dans un ticket à affiche : l'affiche est réécrite (sans le prévenir) — un message privé
    #  le prévient (texte réglable ; vide : rien).
    if depuis == "etape1" and s.get("carte") == "affiche":
        mp = await textes_du_site.texte(g.id, "recrutement.mp.questionnaire", ticket=f"<#{int(ch.id)}>")
        if not await _mp(g, int(tk["user"]), mp):
            await _noter(g.id, tid, "mp_impossible", 0, "questionnaire")
    n = len(qs)
    message = f"Questionnaire envoyé : {n} question{'s' if n > 1 else ''}" + \
        (f" en {n_etapes} étapes." if n_etapes > 1 else ".")
    if sel["ignorees"]:
        message += (f" {len(sel['ignorees'])} question(s) ignorée(s) : retirée(s), désactivée(s), à reformuler, ou "
                    "dont la réponse se lirait ailleurs dans le questionnaire.")
    return 200, {"ok": True, "message": message, "envoi": eid, "questions": n, "etapes": n_etapes,
                 "ignorees": sel["ignorees"], "motifs": sel["motifs"], "explications": sel["explications"]}


async def refuser(g, tid: int, auteur, *, depuis: str = "etape1", note: str = "") -> tuple[int, dict]:
    """Le refus : le message dans le ticket (FR · EN, réglable), un message PRIVÉ (réglable ; des messages privés
    fermés ne bloquent rien), la liste noire des tickets de recrutement (si le panneau le règle), puis la fermeture par
    le circuit normal (transcript, suivi, décision « refusé », motif interne) après le délai du panneau — le temps de
    lire. `depuis` : « etape1 » (la demande, avant le questionnaire ; sans questionnaire : la candidature) ou
    « final » (après le questionnaire)."""
    ch, tk, refus = await _ticket(g, tid)
    if refus:
        return refus
    async with _verrou(g.id, tid):
        s = await _suivi_ou_creer(g, tid, tk, ch)
        if s["fermeture_le"]:
            return _erreur("La fermeture de ce ticket est déjà prévue.", 409, etape=s["etape"])
        if (depuis == "etape1" and s["etape"] != "etape1") or (depuis == "final" and s["etape"] not in ("etape2", "reponses")):
            return _erreur(_texte_etape(s["etape"]), 409, etape=s["etape"])
        p = await parcours(g.id, s["panneau"] or str(tk.get("panel_id") or ""))
        final = depuis == "final" or _mode(s) == "direct"
        etape = "refuse" if final else "refus_etape1"
        #  Le texte enregistré sur le site (Textes & noms), sinon celui d'origine : la page le montre avant de refuser.
        texte = await textes_du_site.texte(g.id, "recrutement.refus_final" if final else "recrutement.refus_etape1")
        await _retirer_message_etape(ch, await _envoi(s["envoi_id"]) if s["envoi_id"] else None)
        try:
            await ch.send(view=_vue_candidat(int(tk["user"]), texte), allowed_mentions=_ping(tk["user"]))
        except discord.HTTPException as ex:
            _log("[RECRUTEMENT][E5] message automatique non posté")
            _log(f"[RECRUTEMENT][E5:DETAIL] ticket={tid} {type(ex).__name__} {getattr(ex, 'status', '')}")
            return _erreur(DISCORD_HS, 503)
        t = _maintenant()
        delai = _delai(p)
        motif = ("étape 1" if depuis == "etape1" and not final else "étape 2" if depuis == "final" else "candidature") \
            + (f" — {note}" if note else "")
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_suivi SET etape=?, fermeture_le=?, fermeture_par=?, fermeture_motif=?,"
                             " decide_par=?, decide_le=?, maj_le=? WHERE guild_id=? AND ticket_id=?",
                             (etape, t + int(delai), int(auteur.id), motif[:200], int(auteur.id), t, t,
                              g.id, int(tid)))
            await db.execute("UPDATE recrutement_envois SET statut='clos' WHERE guild_id=? AND ticket_id=?"
                             " AND statut IN (?, ?)", (g.id, int(tid), *EN_ATTENTE))
            await db.commit()
        await _editer_carte_staff(g, ch, await _suivi(g.id, tid), etape, par=auteur.id, quand=t)
        await _noter(g.id, tid, etape, auteur.id, motif)
        if etape == "refus_etape1":
            await _au_journal(g, "recrutement.etape1_refusee", f"Recrutement : demande refusée pour <@{int(tk['user'])}>"
                              f" par <@{auteur.id}>" + (f" — {note}" if note else ""),
                              membre_id=int(tk["user"]), auteur_id=auteur.id)
    #  Hors du verrou : le message privé, la liste noire, puis la fermeture planifiée.
    mp = await textes_du_site.texte(g.id, "recrutement.mp.refusee" if final else "recrutement.mp.demande_refusee")
    if mp.strip() and p["liste_noire"]:
        mp += "\n" + await textes_du_site.texte(g.id, "recrutement.mp.liste_noire")
    mp_ok = await _mp(g, int(tk["user"]), mp)
    if not mp_ok:
        await _noter(g.id, tid, "mp_impossible", 0, "refus")
    noire = False
    if p["liste_noire"]:
        noire = await mettre_sur_liste_noire(g, int(tk["user"]), motif=motif, par=int(auteur.id), ticket=int(tid))
    _planifier_fermeture(g, tid, delai)
    message = f"Message envoyé au candidat : le ticket se ferme dans {int(delai)} s."
    if not mp_ok:
        message += " Message privé impossible (ses messages privés sont fermés) : il lit le refus dans le ticket."
    if noire:
        message += " Il est sur la liste noire des tickets de recrutement."
    return 200, {"ok": True, "message": message, "mp": mp_ok, "liste_noire": noire}


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


async def _decider_avec(g, tid: int, auteur, accepte: bool, motif: str, **kw):
    """Le circuit de décision du bot : ses options nouvelles (`annonce`, `mp`) si sa signature les connaît."""
    try:
        return await _decider(g, tid, auteur, accepte, motif, **kw)
    except TypeError as ex:
        if "unexpected keyword" not in str(ex):
            raise
        _log("[RECRUTEMENT][E15] circuit de décision sans options")
        return await _decider(g, tid, auteur, accepte, motif)


async def _fermer_plus_tard(g, tid: int, delai: float, essai: int = 1) -> None:
    """La fermeture prévue : le circuit normal du bot (`decider`, refus — sans le message privé de fermeture : la
    décision l'a déjà dit). Discord en panne : on réessaie un peu plus tard (5 fois) ; la fermeture prévue survit à un
    redémarrage (`reprendre_fermetures`)."""
    await asyncio.sleep(max(0.0, float(delai)))
    s = await _suivi(g.id, tid)
    if s is None or not s["fermeture_le"]:
        return
    auteur = g.get_member(int(s["fermeture_par"] or 0)) or getattr(g, "me", None)
    try:
        ok, message = await _decider_avec(g, tid, auteur, False, s["fermeture_motif"] or "étape 1", mp=False)
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
    """L'acceptation : le rôle du clan, PUIS (juste avant la fermeture) le message dans le ticket — avec le choix du
    métier si le panneau le règle —, le message PRIVÉ (« accepté dans le clan… reste actif », réglable), et la
    fermeture sans le message privé de fermeture. Sans `forcer`, il faut un questionnaire répondu, entièrement corrigé,
    au taux exigé par le panneau (100 % par défaut) — la décision reste celle de la personne. Un panneau sans
    questionnaire décide sur la fiche."""
    ch, tk, refus = await _ticket(g, tid)
    if refus:
        return refus
    async with _verrou(g.id, tid):
        s = await _suivi_ou_creer(g, tid, tk, ch)
        if s["fermeture_le"]:
            return _erreur("La fermeture de ce ticket est déjà prévue.", 409, etape=s["etape"])
        if s["etape"] not in OUVERTES:
            return _erreur(_texte_etape(s["etape"]), 409, etape=s["etape"])
        p = await parcours(g.id, s["panneau"] or str(tk.get("panel_id") or ""))
        b = await _bilan_courant(s, p["exigence"])
        sans_questionnaire = _mode(s) == "direct" and s["etape"] == "etape1"
        if not forcer and not sans_questionnaire and not (b and b["reussite"]):
            if b is None:
                texte = ("Le questionnaire en cours n'a pas encore de réponses : accepter quand même demande "
                         "« forcer ».")
            elif not b["complet"]:
                texte = f"Correction incomplète ({b['corrigees']}/{b['total']}) : termine-la, ou accepte en forçant."
            else:
                texte = (f"Exigence : {p['exigence']} % de réponses justes ({b['justes']}/{b['total']}). Accepter "
                         "quand même demande « forcer ».")
            return _erreur(texte, 409, bilan=b, forcer_possible=True)
        candidat = g.get_member(int(tk["user"]))
        trace = {"mp": None}

        async def annonce():
            """Après le rôle donné, avant la fermeture : le message dans le ticket, puis le message privé."""
            t = _maintenant()
            async with _get_db() as db:
                await db.execute("UPDATE recrutement_suivi SET etape='accepte', decide_par=?, decide_le=?, maj_le=?"
                                 " WHERE guild_id=? AND ticket_id=?", (int(auteur.id), t, t, g.id, int(tid)))
                await db.commit()
            invitation = None
            if p["metier"] and _metier is not None and candidat is not None:
                try:
                    invitation = await _metier(g, candidat)
                except Exception as ex:  # le choix du métier manque : l'acceptation reste
                    _log("[RECRUTEMENT][E16] choix du métier indisponible")
                    _log(f"[RECRUTEMENT][E16:DETAIL] {type(ex).__name__} {ex}")
            texte = await textes_du_site.texte(g.id, "recrutement.decision.acceptee", candidat=f"<@{int(tk['user'])}>")
            await _retirer_message_etape(ch, await _envoi(s["envoi_id"]) if s["envoi_id"] else None)
            boutons = []
            libelle = str(invitation[2]) if invitation and len(invitation) > 2 else "Choisir mon métier"
            if invitation:
                texte += "\n\n" + str(invitation[0])
                boutons = [discord.ui.Button(label=libelle[:80], url=str(invitation[1]))]
            try:
                await ch.send(view=_vue_decision(texte, COULEUR_VERT, boutons), allowed_mentions=_ping(tk["user"]))
            except discord.HTTPException as ex:
                _log("[RECRUTEMENT][E5] message automatique non posté")
                _log(f"[RECRUTEMENT][E5:DETAIL] ticket={tid} {type(ex).__name__} {getattr(ex, 'status', '')}")
            await _editer_carte_staff(g, ch, await _suivi(g.id, tid), "accepte", par=auteur.id, quand=t)
            mp = await textes_du_site.texte(g.id, "recrutement.mp.acceptee")
            trace["mp"] = await _mp(g, int(tk["user"]), mp, [discord.ui.Button(
                label=libelle[:80], url=str(invitation[1]))] if invitation else ())
        ok, message = await _decider_avec(g, tid, auteur, True, "", annonce=annonce, mp=False)
        if not ok:
            return _erreur(message, 503 if message == DISCORD_HS else 409)
        t = _maintenant()
        async with _get_db() as db:
            await db.execute("UPDATE recrutement_suivi SET etape='accepte', decide_par=?, decide_le=?, maj_le=?"
                             " WHERE guild_id=? AND ticket_id=?", (int(auteur.id), t, t, g.id, int(tid)))
            await db.execute("UPDATE recrutement_envois SET statut='clos' WHERE guild_id=? AND ticket_id=?"
                             " AND statut IN (?, ?)", (g.id, int(tid), *EN_ATTENTE))
            await db.commit()
        await _noter(g.id, tid, "accepte", auteur.id, "forcé" if forcer and not sans_questionnaire
                     and not (b and b["reussite"]) else "")
        if trace["mp"] is False:
            await _noter(g.id, tid, "mp_impossible", 0, "acceptation")
            message += " Message privé impossible (ses messages privés sont fermés)."
    return 200, {"ok": True, "message": message, "mp": trace["mp"]}


async def sur_liste_noire(guild_id: int, membre_id: int) -> bool:
    """Ce membre est-il sur la liste noire des tickets de recrutement (une entrée active) ?"""
    if _get_db is None:
        return False
    r = await _un("SELECT 1 FROM recrutement_liste_noire WHERE guild_id=? AND membre_id=? AND leve_le=0 LIMIT 1",
                  (int(guild_id), int(membre_id)))
    return r is not None


async def _ecrire_liste_noire_cfg(g, membre_id, ajouter: bool) -> bool:
    """La liste noire des panneaux de recrutement — celle que lit le contrôle d'ouverture du bot (`liste_noire`,
    branché par bot.py). Un échec est dit : la liste du site reste juste, le bot la relit aussi à l'ouverture."""
    if _liste_noire_cfg is None:
        return True
    try:
        return bool(await _liste_noire_cfg(g, None if membre_id is None else int(membre_id), bool(ajouter)))
    except Exception as ex:
        _log("[RECRUTEMENT][E19] liste noire des panneaux non écrite")
        _log(f"[RECRUTEMENT][E19:DETAIL] {type(ex).__name__} {ex}")
        return False


async def mettre_sur_liste_noire(g, membre_id: int, *, motif: str = "", par: int = 0, ticket: int = 0) -> bool:
    """Sur la liste noire des tickets de recrutement : il ne pourra plus en ouvrir (un refus poli, sans ticket). Une
    seule entrée active par personne ; écrite aussi dans la liste noire des panneaux de recrutement."""
    if not await sur_liste_noire(g.id, membre_id):
        m = g.get_member(int(membre_id))
        async with _get_db() as db:
            await db.execute("INSERT INTO recrutement_liste_noire (guild_id, membre_id, nom, depuis, motif, par, ticket_id)"
                             " VALUES (?,?,?,?,?,?,?)", (g.id, int(membre_id), getattr(m, "display_name", "") or "",
                                                         _maintenant(), _net(motif)[:MOTIF_MAX], int(par or 0),
                                                         int(ticket or 0)))
            await db.commit()
        await _au_journal(g, "recrutement.liste_noire", f"Recrutement : <@{int(membre_id)}> mis sur la liste noire des "
                          "tickets de recrutement", membre_id=int(membre_id), auteur_id=int(par or 0))
    await _ecrire_liste_noire_cfg(g, membre_id, True)
    return True


async def liste_noire_site(g) -> dict:
    """La liste noire pour le site : chaque personne, depuis quand, pourquoi, par qui, sa candidature refusée (le
    dossier, le transcript s'ils existent encore), le nombre de ses candidatures passées ; puis les interdictions
    posées avant le site (le bouton « Blacklist » d'un ticket), sans date ni motif ; et les levées récentes."""
    rows = await _lire("SELECT id, membre_id, nom, depuis, motif, par, ticket_id, leve_le, leve_par FROM"
                       " recrutement_liste_noire WHERE guild_id=? ORDER BY depuis DESC, id DESC", (g.id,))
    c = await _cfg(g.id)
    panneaux_ = _panneaux(c) if isinstance(c, dict) else set()
    anciens = set()
    for pid in panneaux_:
        pnl = ((c.get("ticket_panels") or {}).get(pid) or {}) if isinstance(c, dict) else {}
        for x in (pnl.get("blacklist") or []) if isinstance(pnl, dict) else []:
            if str(x).isdigit():
                anciens.add(int(x))
    comptes = {}
    if panneaux_:
        marques = ",".join("?" * len(panneaux_))
        for uid, n in await _lire_tolerant(f"SELECT user_id, COUNT(*) FROM tickets WHERE guild_id=? AND panel_id IN"
                                           f" ({marques}) GROUP BY user_id", (g.id, *sorted(panneaux_))):
            comptes[int(uid)] = int(n)
    transcripts = {int(t): str(u or "") for t, u in await _lire_tolerant(
        "SELECT ticket_id, url FROM ticket_transcripts WHERE guild_id=?", (g.id,)) if str(t or "").isdigit()}
    actifs, leves, vus = [], [], set()
    for rid, uid, nom, depuis, motif, par, tid, leve_le, leve_par in rows:
        ident = _ident(g, int(uid))
        if not ident["present"] and nom:
            ident["nom"] = nom
        x = {"id": int(rid), "membre": ident, "depuis": int(depuis or 0), "motif": motif or "", "par": _qui(g, par),
             "ticket": int(tid or 0), "transcript": transcripts.get(int(tid or 0), ""),
             "candidatures": comptes.get(int(uid), 0), "ancien": False}
        if leve_le:
            leves.append(dict(x, leve_le=int(leve_le), leve_par=_qui(g, leve_par)))
        else:
            actifs.append(x)
            vus.add(int(uid))
    for uid in sorted(anciens - vus):
        actifs.append({"id": 0, "membre": _ident(g, uid), "depuis": 0, "motif": "", "par": None, "ticket": 0,
                       "transcript": "", "candidatures": comptes.get(uid, 0), "ancien": True})
    return {"actifs": actifs, "leves": leves[:100], "total": len(actifs), "confirmation": CONFIRMATION_LEVER_TOUT}


async def lever_liste_noire(g, auteur, corps) -> tuple[int, dict]:
    """« Lever » (une personne : elle peut recandidater) ou « Tout lever » (`tout: true` et la confirmation forte
    tapée : `confirmation` = « LEVER ») — l'interdiction posée par le bouton d'un ticket comprise. Journalisé."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    t = _maintenant()
    if corps.get("tout") is True:
        if str(corps.get("confirmation") or "").strip().upper() != CONFIRMATION_LEVER_TOUT:
            return _erreur(f"Pour tout lever, tape « {CONFIRMATION_LEVER_TOUT} ».")
        async with _get_db() as db:
            cur = await db.execute("UPDATE recrutement_liste_noire SET leve_le=?, leve_par=? WHERE guild_id=? AND"
                                   " leve_le=0", (t, int(auteur.id), g.id))
            n = int(cur.rowcount or 0)
            await db.commit()
        ok = await _ecrire_liste_noire_cfg(g, None, False)
        await _au_journal(g, "recrutement.liste_noire_levee", f"Recrutement : toute la liste noire levée ({n} "
                          f"personne(s)) par <@{auteur.id}>", auteur_id=auteur.id)
        return 200, {"ok": True, "leves": n, "panneaux": ok,
                     "message": f"Liste noire levée : {n} personne(s) peuvent de nouveau candidater."}
    try:
        uid = _entier(corps, "membre", mini=1, maxi=2 ** 63)
    except _Invalide as ex:
        return _erreur(str(ex))
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_liste_noire SET leve_le=?, leve_par=? WHERE guild_id=? AND"
                               " membre_id=? AND leve_le=0", (t, int(auteur.id), g.id, int(uid)))
        n = int(cur.rowcount or 0)
        await db.commit()
    ok = await _ecrire_liste_noire_cfg(g, uid, False)
    await _au_journal(g, "recrutement.liste_noire_levee", f"Recrutement : <@{int(uid)}> retiré de la liste noire par "
                      f"<@{auteur.id}>", membre_id=int(uid), auteur_id=auteur.id)
    return 200, {"ok": True, "leves": n, "panneaux": ok, "message": "Retiré de la liste noire : il peut recandidater."}


def eliminatoire(champs, reponses: dict):
    """(le titre du champ, la réponse) si une réponse de la fiche est ÉLIMINATOIRE (un choix marqué tel sur le site,
    une tranche d'âge par exemple) — sinon None."""
    for ch in champs or []:
        elim = {str(x).casefold() for x in ch.get("eliminatoires") or []}
        if ch.get("type") != "choix" or not elim:
            continue
        v = _net((reponses or {}).get(ch.get("titre")))
        if v and v.casefold() in elim:
            return str(ch["titre"]), v
    return None


async def eliminer(g, membre, panneau: str, champ: str, reponse: str) -> dict:
    """Élimination d'office : AUCUN ticket (la fiche se remplit avant sa création), le message privé du refus de la
    demande (réglable), la liste noire selon le réglage du panneau, et la trace « Éliminé d'office · <champ> » parmi
    les décisions du site. Rend {mp, liste_noire}."""
    p = await parcours(g.id, panneau)
    uid = int(membre.id)
    async with _get_db() as db:
        await db.execute("INSERT INTO recrutement_eliminations (guild_id, membre_id, nom, panneau, champ, reponse, quand)"
                         " VALUES (?,?,?,?,?,?,?)", (g.id, uid, getattr(membre, "display_name", "") or "",
                                                     str(panneau or ""), _net(champ)[:CHAMP_TITRE_MAX],
                                                     _net(reponse)[:OPTION_MAX], _maintenant()))
        await db.commit()
    mp = await textes_du_site.texte(g.id, "recrutement.mp.demande_refusee")
    if mp.strip() and p["liste_noire"]:
        mp += "\n" + await textes_du_site.texte(g.id, "recrutement.mp.liste_noire")
    mp_ok = await _mp(g, uid, mp)
    noire = False
    if p["liste_noire"]:
        noire = await mettre_sur_liste_noire(g, uid, motif=f"Éliminé d'office · {champ}", par=0, ticket=0)
    await _au_journal(g, "recrutement.elimine", f"Recrutement : <@{uid}> éliminé d'office ({_net(champ)})", membre_id=uid)
    return {"mp": mp_ok, "liste_noire": noire}


async def fiche_ouverture(guild_id: int, panneau: str, pnl) -> list:
    """La fiche que le bot demande à l'ouverture de ce panneau (réglée sur le site, sinon celle de /configure)."""
    return fiche_effective(await parcours(guild_id, panneau), pnl)


class FormulaireFiche(discord.ui.Modal):
    """La FICHE PERSONNELLE — l'étape obligatoire, avant le ticket : 5 champs au plus (texte court ou long, ou un choix
    dans une liste — une tranche d'âge plutôt qu'une date de naissance). `sur_envoi(i, reponses)` : la suite (bot.py :
    l'élimination d'office, ou le ticket)."""

    def __init__(self, champs: list, *, guild_id: int = 0, sur_envoi=None):
        gid = int(guild_id or 0)
        super().__init__(title=_t(gid, "recrutement.fiche.titre")[:45], timeout=900)
        self.sur_envoi, self.champs = sur_envoi, []
        for ch in (champs or [])[:FICHE_MAX]:
            requis = bool(ch.get("requis", True))
            if ch.get("type") == "choix" and ch.get("options"):
                comp = discord.ui.Select(options=[discord.SelectOption(label=str(o)[:100], value=str(k))
                                                  for k, o in enumerate(ch["options"][:OPTIONS_MAX])],
                                         required=requis, min_values=1 if requis else 0, max_values=1,
                                         placeholder=str(ch.get("exemple") or "")[:100] or None)
            else:
                comp = discord.ui.TextInput(style=discord.TextStyle.paragraph if ch.get("type") == "long"
                                            else discord.TextStyle.short, required=requis,
                                            max_length=max(1, min(int(ch.get("max") or CHAMP_LONGUEUR_DEFAUT), 4000)),
                                            placeholder=str(ch.get("exemple") or "")[:100] or None)
            self.add_item(discord.ui.Label(text=str(ch.get("titre") or "Question")[:45],
                                           description=str(ch.get("aide") or "")[:100] or None, component=comp))
            self.champs.append((ch, comp))

    def valeurs(self) -> dict:
        """{titre: réponse} — le choix fait (son libellé), ou le texte écrit ; les champs laissés vides n'y sont pas."""
        out = {}
        for ch, comp in self.champs:
            if isinstance(comp, discord.ui.Select):
                v = (comp.values or [""])[0]
                opts = ch.get("options") or []
                texte = opts[int(v)] if str(v).isdigit() and int(v) < len(opts) else ""
            else:
                texte = _net(comp.value or "", lignes=True)[:int(ch.get("max") or CHAMP_LONGUEUR_DEFAUT)]
            if texte:
                out[str(ch.get("titre"))] = texte
        return out

    async def on_submit(self, i: discord.Interaction):
        if self.sur_envoi is not None:
            await self.sur_envoi(i, self.valeurs())

    async def on_error(self, i: discord.Interaction, error: Exception) -> None:
        await _formulaire_en_echec(i, "formulaire_fiche", error)


METIER_TOUS = "tous"


CHEF_EXIGENCE = 100


DECISIONS_CHEF = ("attente", "accepte", "refuse")


async def _clan_role(g):
    if _clan is None or g is None:
        return None
    try:
        return await _clan(g)
    except Exception as ex:
        _log("[RECRUTEMENT][E20] rôle du clan illisible")
        _log(f"[RECRUTEMENT][E20:DETAIL] {type(ex).__name__} {ex}")
        return None


async def du_clan(g, membre) -> bool:
    """Un membre du clan (il porte le rôle du clan) : les seuls à qui l'on propose d'être chef."""
    clan = await _clan_role(g)
    return membre is not None and clan is not None and any(
        getattr(r, "id", None) == clan.id for r in getattr(membre, "roles", []) or [])


async def _liste_metiers(g) -> list:
    """[{cle, nom}] : les métiers du catalogue (`metiers`, branché par bot.py) — et « tous »."""
    out = []
    if _metiers_liste is not None:
        try:
            out = [{"cle": str(x["cle"]), "nom": str(x.get("nom") or x["cle"])} for x in await _metiers_liste(g)]
        except Exception as ex:
            _log("[RECRUTEMENT][E21] métiers illisibles")
            _log(f"[RECRUTEMENT][E21:DETAIL] {type(ex).__name__} {ex}")
    return out


async def _metiers_de(g, membre) -> list:
    if _metiers_membre is None or membre is None:
        return []
    try:
        return [str(x) for x in await _metiers_membre(g, membre)]
    except Exception as ex:
        _log("[RECRUTEMENT][E21] métiers d'un membre illisibles")
        _log(f"[RECRUTEMENT][E21:DETAIL] {type(ex).__name__} {ex}")
        return []


_COLS_QC = ("id", "metiers", "question", "reponse", "variantes", "actif", "retiree", "ordre", "cree_le", "cree_par",
            "maj_le", "maj_par", "version")


def _question_chef(row) -> dict:
    d = dict(zip(_COLS_QC, tuple(row)))
    d["metiers"] = [str(x) for x in _json_liste(d["metiers"])] or [METIER_TOUS]
    d["variantes"] = [str(v) for v in _json_liste(d["variantes"])]
    d["actif"], d["retiree"] = bool(d["actif"]), bool(d["retiree"])
    d["fuite"] = fuite(d["question"], d["reponse"], d["variantes"])
    d.update(theme="chef", type="texte", difficulte="moyenne", source="", section="", extrait="", statut="confirme")
    return d


async def questions_chef(guild_id: int) -> list:
    rows = await _lire(f"SELECT {', '.join(_COLS_QC)} FROM recrutement_chef_questions WHERE guild_id=?"
                       " ORDER BY ordre, cree_le, id", (int(guild_id),))
    return [_question_chef(r) for r in rows]


def _pour_metier(q: dict, metier: str) -> bool:
    return METIER_TOUS in q["metiers"] or str(metier) in q["metiers"]


async def enregistrer_question_chef(g, auteur, corps) -> tuple[int, dict]:
    """Une question de chef : créer (sans `id`) ou modifier (`id` + `version`). Jamais une question qui dit sa
    réponse."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        qid = _ident_question(corps)
        question = _texte(corps, "question", mini=QUESTION_MIN, maxi=QUESTION_MAX)
        reponse = _texte(corps, "reponse", mini=1, maxi=REPONSE_MAX)
        variantes = _variantes(corps.get("variantes", []), reponse)
        brut = corps.get("metiers") or [METIER_TOUS]
        if not isinstance(brut, list) or not 1 <= len(brut) <= 40:
            raise _Invalide("« metiers » : une liste de métiers, ou « tous ».")
        metiers_ = list(dict.fromkeys(str(x) for x in brut if isinstance(x, str) and FORMAT_ID.fullmatch(str(x))))
        if not metiers_:
            raise _Invalide("« metiers » : une liste de métiers, ou « tous ».")
        if METIER_TOUS in metiers_:
            metiers_ = [METIER_TOUS]
        actif = _booleen(corps, "actif", True)
        version = _entier(corps, "version", requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    devoile = fuite(question, reponse, variantes)
    if devoile:
        return _erreur("La réponse attendue apparaît dans la question : reformule-la pour ne rien dévoiler.",
                       fuite=devoile)
    t = _maintenant()
    valeurs = (json.dumps(metiers_), question, reponse, json.dumps(variantes, ensure_ascii=False), int(bool(actif)))
    async with _get_db() as db:
        async with db.execute("SELECT version FROM recrutement_chef_questions WHERE guild_id=? AND id=?",
                              (g.id, qid or "")) as cur:
            r = await cur.fetchone()
        if r is None:
            if version not in (None, 0):
                return _erreur("Cette question n'existe plus.", 404)
            async with db.execute("SELECT COUNT(*), COALESCE(MAX(ordre), -1) FROM recrutement_chef_questions"
                                  " WHERE guild_id=?", (g.id,)) as cur:
                n, ordre = (int(x or 0) for x in await cur.fetchone())
            if n >= BANQUE_MAX:
                return _erreur(f"La banque des chefs est pleine ({BANQUE_MAX} questions).", 409)
            qid = qid or f"c-{secrets.token_hex(5)}"
            await db.execute("INSERT INTO recrutement_chef_questions (guild_id, id, metiers, question, reponse, variantes,"
                             " actif, ordre, cree_le, cree_par, maj_le, maj_par, version)"
                             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)", (g.id, qid, *valeurs, ordre + 1, t, auteur.id, t,
                                                                     auteur.id))
            cree = True
        else:
            if version is None or int(version) != int(r[0]):
                await db.commit()
                actuelle = next((q for q in await questions_chef(g.id) if q["id"] == qid), None)
                return 409, {"conflit": True, "erreur": "Cette question a changé entre-temps.", "actuelle": actuelle}
            await db.execute("UPDATE recrutement_chef_questions SET metiers=?, question=?, reponse=?, variantes=?, actif=?,"
                             " maj_le=?, maj_par=?, version=version+1 WHERE guild_id=? AND id=?",
                             (*valeurs, t, auteur.id, g.id, qid))
            cree = False
        await db.commit()
    q = next(x for x in await questions_chef(g.id) if x["id"] == qid)
    return 200, {"ok": True, "cree": cree, "question": dict(q, cree_par=_qui(g, q["cree_par"]),
                                                            maj_par=_qui(g, q["maj_par"]))}


async def retirer_question_chef(g, auteur, corps) -> tuple[int, dict]:
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        qid = _ident_question(corps, requis=True)
        restaurer = _booleen(corps, "restaurer", False)
    except _Invalide as ex:
        return _erreur(str(ex))
    async with _get_db() as db:
        cur = await db.execute("UPDATE recrutement_chef_questions SET retiree=?, actif=?, maj_le=?, maj_par=?,"
                               " version=version+1 WHERE guild_id=? AND id=?",
                               (int(not restaurer), int(bool(restaurer)), _maintenant(), auteur.id, g.id, qid))
        await db.commit()
    if (cur.rowcount or 0) < 1:
        return _erreur("Question introuvable.", 404)
    return 200, {"ok": True, "question": next(q for q in await questions_chef(g.id) if q["id"] == qid)}


async def _gabarits_chef(guild_id: int) -> dict:
    rows = await _lire("SELECT metier, etapes, version, maj_le, maj_par FROM recrutement_chef_gabarits WHERE guild_id=?",
                       (int(guild_id),))
    return {str(r[0]): {"etapes": [x for x in _json_liste(r[1]) if isinstance(x, dict)], "version": int(r[2]),
                        "maj_le": int(r[3] or 0), "maj_par": int(r[4] or 0)} for r in rows}


def _etapes_ids(brut) -> list:
    """[{titre, consigne, questions: [ids]}] vérifiées (1…ETAPES_MAX étapes, des identifiants)."""
    if not isinstance(brut, list) or not 1 <= len(brut) <= ETAPES_MAX:
        raise _Invalide(f"De 1 à {ETAPES_MAX} étapes.")
    out = []
    for x in brut:
        if not isinstance(x, dict):
            raise _Invalide("Chaque étape est un objet {titre, consigne, questions}.")
        out.append({"titre": _texte(x, "titre", maxi=ETAPE_TITRE_MAX, requis=False),
                    "consigne": _texte(x, "consigne", maxi=ETAPE_CONSIGNE_MAX, requis=False),
                    "questions": list(dict.fromkeys(_ids(x.get("questions") or [])))})
    if not any(e["questions"] for e in out):
        raise _Invalide("Coche au moins une question.")
    return out


async def enregistrer_gabarit_chef(g, auteur, corps) -> tuple[int, dict]:
    """Le gabarit d'un métier (ses étapes et leurs questions de chef), avec la `version` lue."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        metier = _ident_question(corps, "metier", requis=True)
        version = _entier(corps, "version", mini=0)
        etapes = _etapes_ids(corps.get("etapes"))
    except _Invalide as ex:
        return _erreur(str(ex))
    connues = {q["id"] for q in await questions_chef(g.id)}
    if any(x not in connues for e in etapes for x in e["questions"]):
        return _erreur("Une question de ce gabarit n'existe pas dans la banque des chefs.")
    t = _maintenant()
    async with _get_db() as db:
        async with db.execute("SELECT version FROM recrutement_chef_gabarits WHERE guild_id=? AND metier=?",
                              (g.id, metier)) as cur:
            r = await cur.fetchone()
        if int(version) != (int(r[0]) if r else 0):
            await db.commit()
            return 409, {"conflit": True, "erreur": "Ce gabarit a changé entre-temps.",
                         "actuelle": (await _gabarits_chef(g.id)).get(metier)}
        if r is None:
            await db.execute("INSERT INTO recrutement_chef_gabarits (guild_id, metier, etapes, version, maj_le, maj_par)"
                             " VALUES (?,?,?,1,?,?)", (g.id, metier, json.dumps(etapes, ensure_ascii=False), t, auteur.id))
        else:
            await db.execute("UPDATE recrutement_chef_gabarits SET etapes=?, version=version+1, maj_le=?, maj_par=?"
                             " WHERE guild_id=? AND metier=?", (json.dumps(etapes, ensure_ascii=False), t, auteur.id,
                                                                g.id, metier))
        await db.commit()
    return 200, {"ok": True, "gabarit": (await _gabarits_chef(g.id)).get(metier)}


async def _roles_chef(guild_id: int) -> dict:
    return {str(m): int(r) for m, r in await _lire("SELECT metier, role_id FROM recrutement_chef_roles WHERE guild_id=?",
                                                   (int(guild_id),))}


def _refus_role_chef(g, role) -> str | None:
    """Pourquoi ce rôle ne peut pas être celui des chefs d'un métier — None s'il le peut (le bot le donne et le retire,
    il ne donne aucun droit de gestion)."""
    if role is None:
        return "Rôle introuvable."
    if getattr(role, "is_default", lambda: False)() or role.id == getattr(g, "id", None):
        return "Le rôle @everyone ne se donne pas."
    if getattr(role, "managed", False):
        return "Rôle géré par une intégration (bot, boost…) : impossible à donner."
    haut = int(getattr(getattr(getattr(g, "me", None), "top_role", None), "position", 0) or 0)
    if int(getattr(role, "position", 0) or 0) >= haut:
        return "Ce rôle est au-dessus du mien : je ne peux pas le donner. Place-le sous mon rôle."
    droits = getattr(role, "permissions", None)
    for p in ("administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members", "kick_members",
              "moderate_members", "manage_messages", "mention_everyone"):
        if droits is not None and getattr(droits, p, False) is True:
            return "Ce rôle donne des droits de gestion ou de modération : jamais pour un chef d'équipe."
    if not getattr(getattr(getattr(g, "me", None), "guild_permissions", None), "manage_roles", False):
        return "Il me manque la permission « Gérer les rôles »."
    return None


async def regler_role_chef(g, auteur, corps) -> tuple[int, dict]:
    """Le rôle des chefs d'un métier : un rôle existant (`role`), « Créer le rôle » (`creer: true`, `nom` : « Chef ·
    <métier> » par défaut), ou aucun (`role: null`). La tête seulement (le site), journalisé ; la hiérarchie du bot est
    vérifiée ; jamais un autre rôle n'est touché."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        metier = _ident_question(corps, "metier", requis=True)
        nom = _texte(corps, "nom", maxi=100, requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    noms = {m["cle"]: m["nom"] for m in await _liste_metiers(g)}
    if metier not in noms:
        return _erreur("Ce métier n'existe pas dans le catalogue.", 404)
    role = None
    if corps.get("creer") is True:
        if not getattr(getattr(getattr(g, "me", None), "guild_permissions", None), "manage_roles", False):
            return _erreur("Il me manque la permission « Gérer les rôles ».", 409)
        try:
            role = await g.create_role(name=(nom or f"Chef · {noms[metier]}")[:100],
                                       reason=f"Chefs d'équipe {noms[metier]} (site, par {auteur})")
        except discord.HTTPException as ex:
            _log("[RECRUTEMENT][E22] rôle de chef non créé")
            _log(f"[RECRUTEMENT][E22:DETAIL] {type(ex).__name__} {getattr(ex, 'status', '')}")
            return _erreur("Discord a refusé de créer le rôle.", 503)
    elif corps.get("role") is not None:
        brut = str(corps.get("role"))
        role = g.get_role(int(brut)) if brut.isdigit() else None
        refus = _refus_role_chef(g, role)
        if refus:
            return _erreur(refus, 409)
    t = _maintenant()
    async with _get_db() as db:
        if role is None:
            await db.execute("DELETE FROM recrutement_chef_roles WHERE guild_id=? AND metier=?", (g.id, metier))
        else:
            await db.execute("INSERT OR REPLACE INTO recrutement_chef_roles (guild_id, metier, role_id, maj_le, maj_par)"
                             " VALUES (?,?,?,?,?)", (g.id, metier, int(role.id), t, auteur.id))
        await db.commit()
    await _au_journal(g, "recrutement.chef_role", f"Chefs d'équipe {noms[metier]} : rôle "
                      + (f"« {getattr(role, 'name', '')} »" if role is not None else "retiré") + f" (par <@{auteur.id}>)",
                      auteur_id=auteur.id)
    return 200, {"ok": True, "metier": metier, "role": None if role is None else {"id": str(role.id), "nom": role.name}}


async def chefs(guild_id: int) -> dict:
    """Les chefs d'équipe validés : {membre_id: {"metier", "depuis", "role_id"}} (l'équipe du site de l'équipage s'en
    sert pour le chef de chaque équipe)."""
    if _get_db is None:
        return {}
    rows = await _lire("SELECT membre_id, metier, accepte_le, role_id FROM recrutement_chefs WHERE guild_id=?",
                       (int(guild_id),))
    return {int(m): {"metier": str(met), "depuis": int(le or 0), "role_id": int(r or 0)} for m, met, le, r in rows}


async def chef_de(g, membre_id: int) -> dict | None:
    """Pour la fiche d'un membre : {metier, nom, depuis} s'il est chef d'équipe, sinon None."""
    c = (await chefs(g.id)).get(int(membre_id))
    if c is None:
        return None
    noms = {m["cle"]: m["nom"] for m in await _liste_metiers(g)}
    return dict(c, nom=noms.get(c["metier"], c["metier"]), titre=f"Chef d'équipe · {noms.get(c['metier'], c['metier'])}")


async def proposition_chef(g, membre_id: int, metier: str) -> dict:
    """Le questionnaire de chef qu'on proposerait à ce membre pour ce métier : le gabarit du métier, sinon une étape avec
    toutes les questions actives de ce métier (et « tous »). Pour le site : la page le modifie avant l'envoi."""
    banque_ = [q for q in await questions_chef(g.id) if q["actif"] and not q["retiree"] and not q["fuite"]]
    par_id = {q["id"]: q for q in banque_}
    gabarit = (await _gabarits_chef(g.id)).get(str(metier))
    if gabarit:
        etapes = [{"titre": e.get("titre", ""), "consigne": e.get("consigne", ""),
                   "questions": [x for x in e.get("questions") or [] if x in par_id]} for e in gabarit["etapes"]]
    else:
        etapes = [{"titre": "", "consigne": "", "questions": [q["id"] for q in banque_ if _pour_metier(q, metier)]}]
    return {"metier": metier, "etapes": etapes, "gabarit": bool(gabarit),
            "banque": [{"id": q["id"], "question": q["question"], "metiers": q["metiers"]} for q in banque_
                       if _pour_metier(q, metier)]}


async def proposer_chef(g, auteur, corps) -> tuple[int, dict]:
    """« Proposer d'être chef » : un membre DU CLAN, un métier, des étapes et leurs questions (de la banque des chefs).
    L'envoi est créé (aucun ticket), sa première étape ouverte, puis le message privé part (`inviter`, la page du
    candidat)."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        uid = _entier(corps, "membre", mini=1, maxi=2 ** 63)
        metier = _ident_question(corps, "metier", requis=True)
        etapes = _etapes_ids(corps.get("etapes"))
    except _Invalide as ex:
        return _erreur(str(ex))
    membre = g.get_member(int(uid))
    if membre is None:
        return _erreur("Ce membre n'est plus sur le serveur.", 404)
    if not await du_clan(g, membre):
        return _erreur("Seul un membre du clan peut devenir chef d'équipe.", 409)
    if metier not in {m["cle"] for m in await _liste_metiers(g)}:
        return _erreur("Ce métier n'existe pas dans le catalogue.", 404)
    inviter = getattr(_web(), "inviter", None)
    if inviter is None:   # un chef répond sur la page du candidat : sans elle, le questionnaire serait une impasse
        return _erreur("La page de réponse des candidats n'est pas branchée : impossible de proposer le questionnaire "
                       "de chef pour l'instant.", 409)
    deja = await _un("SELECT c.envoi_id FROM recrutement_chef_candidatures c JOIN recrutement_envois e ON e.id=c.envoi_id"
                     " WHERE c.guild_id=? AND c.membre_id=? AND c.decision IN ('', 'attente') AND e.statut NOT IN"
                     " ('annule', 'remplace')", (g.id, int(uid)))
    if deja is not None:
        return _erreur("Une candidature de chef est déjà en cours pour ce membre : décide-la d'abord.", 409,
                       envoi=int(deja[0]))
    banque_ = {q["id"]: q for q in await questions_chef(g.id)}
    motifs: dict = {}
    vus: set = set()
    lots = [(e["titre"], e["consigne"], _filtrer(e["questions"], banque_, motifs, vus)) for e in etapes]
    st, sel = _assembler(lots, [], "", motifs, "chef", [x for e in etapes for x in e["questions"]])
    if st != 200:
        return st, sel
    qs = [dict({c: q[c] for c in _SNAPSHOT}, rang=k + 1, etape=int(q.get("etape") or 1))
          for k, q in enumerate(sel["questions"])]
    t = _maintenant()
    async with _get_db() as db:
        cur = await db.execute(
            "INSERT INTO recrutement_envois (guild_id, ticket_id, candidat_id, questions, liens, statut, origine, renvoi,"
            " envoye_par, cree_le, envoye_le, salon_id, etapes, etape_ouverte, etape_fiche, nature, metier)"
            " VALUES (?,0,?,?,'[]','envoye','chef',0,?,?,?,0,?,1,0,'chef',?)",
            (g.id, int(uid), json.dumps(qs, ensure_ascii=False), int(auteur.id), t, t,
             json.dumps(sel["etapes"], ensure_ascii=False), metier))
        eid = int(cur.lastrowid)
        await db.execute("INSERT INTO recrutement_chef_candidatures (envoi_id, guild_id, membre_id, metier, cree_le, maj_le)"
                         " VALUES (?,?,?,?,?,?)", (eid, g.id, int(uid), metier, t, t))
        await db.commit()
    invite = False
    try:
        invite = bool(await inviter(g, await _envoi(eid)))
    except Exception as ex:  # l'envoi existe : la direction peut relancer l'invitation
        _log("[RECRUTEMENT][E18] invitation du chef impossible")
        _log(f"[RECRUTEMENT][E18:DETAIL] envoi={eid} {type(ex).__name__} {ex}")
    await _au_journal(g, "recrutement.chef_propose", f"Chef d'équipe : questionnaire {metier} proposé à <@{int(uid)}> "
                      f"({len(qs)} question(s)) par <@{auteur.id}>", membre_id=int(uid), auteur_id=auteur.id)
    message = f"Questionnaire de chef envoyé : {len(qs)} question(s)." + (
        "" if invite else " Le message privé n'est pas parti (ses messages privés sont peut-être fermés) : "
                          "préviens-le toi-même.")
    return 200, {"ok": True, "envoi": eid, "questions": len(qs), "invite": invite, "message": message,
                 "ignorees": sel["ignorees"], "explications": sel["explications"]}


async def _chef_candidature(g, eid: int) -> dict | None:
    r = await _un("SELECT envoi_id, membre_id, metier, decision, decide_par, decide_le, note, cree_le, maj_le FROM"
                  " recrutement_chef_candidatures WHERE guild_id=? AND envoi_id=?", (g.id, int(eid)))
    if r is None:
        return None
    return dict(zip(("envoi", "membre_id", "metier", "decision", "decide_par", "decide_le", "note", "cree_le", "maj_le"),
                    tuple(r)))


async def decider_chef(g, auteur, corps) -> tuple[int, dict]:
    """La décision sur une candidature de chef — la tête seulement (le site), journalisée. « accepter » : seulement à
    100 % de réponses justes, toutes corrigées (JAMAIS forcé) — le rôle « Chef · <métier> » s'il est réglé, le message
    privé, sa fiche. « refuser » : le message privé (pas de liste noire). « attente » : la candidature garde son état,
    message privé facultatif."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        eid = _entier(corps, "envoi", mini=1)
        note = _texte(corps, "note", maxi=NOTE_MAX, requis=False)
    except _Invalide as ex:
        return _erreur(str(ex))
    decision = corps.get("decision")
    if decision not in ("accepter", "refuser", "attente"):
        return _erreur("« decision » : accepter, refuser ou attente.")
    if corps.get("forcer"):
        return _erreur("Un chef d'équipe ne s'accepte jamais en forçant : 100 % de réponses justes sont exigés.")
    c = await _chef_candidature(g, eid)
    e = await _envoi(eid)
    if c is None or e is None:
        return _erreur("Candidature de chef introuvable.", 404)
    if c["decision"] in ("accepte", "refuse"):
        return _erreur("Cette candidature est déjà décidée.", 409)
    membre = g.get_member(int(c["membre_id"]))
    noms = {m["cle"]: m["nom"] for m in await _liste_metiers(g)}
    metier_nom = noms.get(c["metier"], c["metier"])
    t = _maintenant()
    role_donne = None
    if decision == "accepter":
        if membre is None or not await du_clan(g, membre):
            return _erreur("Il n'est plus membre du clan : on ne peut pas le nommer chef.", 409)
        if e["statut"] != "repondu":
            return _erreur("Il n'a pas encore envoyé toutes ses réponses.", 409, raison="reponses")
        b = bilan(e["questions"], await _reponses(eid), await _corrections(eid), CHEF_EXIGENCE)
        if not b["complet"]:
            return _erreur(f"Correction incomplète ({b['corrigees']}/{b['total']}) : un chef se juge sur tout.", 409,
                           bilan=b, raison="correction")
        if b["justes"] != b["total"]:
            return _erreur(f"{b['justes']}/{b['total']} réponses justes : un chef d'équipe n'a pas le droit à l'erreur "
                           "(100 % exigés).", 409, bilan=b, raison="exigence")
        rid = (await _roles_chef(g.id)).get(str(c["metier"]))
        role = g.get_role(int(rid)) if rid else None
        if rid and role is not None:
            refus = _refus_role_chef(g, role)
            if refus:
                return _erreur(refus, 409, raison="role")
            try:
                await membre.add_roles(role, reason=f"Chef d'équipe {metier_nom} (site, par {auteur})")
                role_donne = role
            except discord.HTTPException as ex:
                _log("[RECRUTEMENT][E22] rôle de chef non donné")
                _log(f"[RECRUTEMENT][E22:DETAIL] {type(ex).__name__} {getattr(ex, 'status', '')}")
                return _erreur("Discord a refusé de donner le rôle de chef.", 503)
        async with _get_db() as db:
            await db.execute("INSERT OR REPLACE INTO recrutement_chefs (guild_id, membre_id, metier, role_id, accepte_le,"
                             " accepte_par) VALUES (?,?,?,?,?,?)", (g.id, int(c["membre_id"]), c["metier"],
                                                                   int(getattr(role_donne, "id", 0) or 0), t, auteur.id))
            await db.commit()
    etat = {"accepter": "accepte", "refuser": "refuse", "attente": "attente"}[decision]
    async with _get_db() as db:
        await db.execute("UPDATE recrutement_chef_candidatures SET decision=?, decide_par=?, decide_le=?, note=?, maj_le=?"
                         " WHERE envoi_id=?", (etat, auteur.id, t, note, t, eid))
        if etat in ("accepte", "refuse"):
            await db.execute("UPDATE recrutement_envois SET statut='clos' WHERE id=? AND statut IN (?, ?)",
                             (eid, *EN_ATTENTE))
        await db.commit()
    mp = await textes_du_site.texte(g.id, f"recrutement.chef.mp.{etat}", metier=metier_nom)
    mp_ok = await _mp(g, int(c["membre_id"]), mp) if mp.strip() else None
    await _au_journal(g, f"recrutement.chef_{etat}", f"Chef d'équipe {metier_nom} : <@{int(c['membre_id'])}> "
                      + {"accepte": "nommé", "refuse": "refusé", "attente": "mis en attente"}[etat]
                      + f" par <@{auteur.id}>", membre_id=int(c["membre_id"]), auteur_id=auteur.id)
    message = {"accepte": f"Nommé chef d'équipe · {metier_nom}." + (f" Rôle « {role_donne.name} » donné."
                                                                      if role_donne else ""),
               "refuse": "Candidature de chef refusée.", "attente": "Candidature mise en attente."}[etat]
    if mp_ok is False:
        message += " Message privé impossible (ses messages privés sont fermés)."
    return 200, {"ok": True, "decision": etat, "message": message, "mp": mp_ok,
                 "role": None if role_donne is None else {"id": str(role_donne.id), "nom": role_donne.name}}


async def retirer_chef(g, auteur, corps) -> tuple[int, dict]:
    """« Retirer le titre de chef » — la tête seulement : son rôle de chef (celui-là seulement) et le titre."""
    if not isinstance(corps, dict):
        return _erreur("Corps attendu : un objet JSON.")
    try:
        uid = _entier(corps, "membre", mini=1, maxi=2 ** 63)
    except _Invalide as ex:
        return _erreur(str(ex))
    r = await _un("SELECT metier, role_id FROM recrutement_chefs WHERE guild_id=? AND membre_id=?", (g.id, int(uid)))
    if r is None:
        return _erreur("Ce membre n'est pas chef d'équipe.", 404)
    membre, role = g.get_member(int(uid)), g.get_role(int(r[1] or 0)) if r[1] else None
    retire = False
    if membre is not None and role is not None and role in (getattr(membre, "roles", []) or []):
        refus = _refus_role_chef(g, role)
        if refus:
            return _erreur(refus, 409)
        try:
            await membre.remove_roles(role, reason=f"Titre de chef retiré (site, par {auteur})")
            retire = True
        except discord.HTTPException as ex:
            _log("[RECRUTEMENT][E22] rôle de chef non retiré")
            _log(f"[RECRUTEMENT][E22:DETAIL] {type(ex).__name__} {getattr(ex, 'status', '')}")
            return _erreur("Discord a refusé de retirer le rôle de chef.", 503)
    async with _get_db() as db:
        await db.execute("DELETE FROM recrutement_chefs WHERE guild_id=? AND membre_id=?", (g.id, int(uid)))
        await db.commit()
    await _au_journal(g, "recrutement.chef_retire", f"Chef d'équipe : titre retiré à <@{int(uid)}> par <@{auteur.id}>",
                      membre_id=int(uid), auteur_id=auteur.id)
    return 200, {"ok": True, "role_retire": retire, "message": "Titre de chef retiré." + (
        " Son rôle de chef aussi." if retire else "")}


async def chefs_site(g) -> dict:
    """Tout ce que la page des chefs d'équipe montre : les membres du clan (pour proposer), les candidatures (en cours,
    à corriger, en attente, décidées depuis 30 jours), les chefs nommés, la banque des chefs, ses gabarits, les rôles
    par métier."""
    metiers_ = await _liste_metiers(g)
    noms = {m["cle"]: m["nom"] for m in metiers_}
    roles = await _roles_chef(g.id)
    nommes = await chefs(g.id)
    clan = await _clan_role(g)
    membres = []
    if clan is not None:
        for m in sorted(getattr(clan, "members", []) or [], key=lambda x: str(getattr(x, "display_name", "")).casefold()):
            if getattr(m, "bot", False):
                continue
            membres.append(dict(_ident(g, m.id), metiers=await _metiers_de(g, m), chef=nommes.get(int(m.id))))
    rows = await _lire("SELECT envoi_id, membre_id, metier, decision, decide_par, decide_le, cree_le, maj_le FROM"
                       " recrutement_chef_candidatures WHERE guild_id=? ORDER BY cree_le DESC", (g.id,))
    limite = _maintenant() - 30 * 86400
    candidatures = []
    for eid, uid, met, decision, par, le, cree, maj in rows:
        e = await _envoi(eid)
        if e is None or (decision in ("accepte", "refuse") and int(le or 0) < limite):
            continue
        b = bilan(e["questions"], await _reponses(eid), await _corrections(eid), CHEF_EXIGENCE)
        if decision:
            etat = decision
        elif e["statut"] == "repondu":
            etat = "corriger"
        else:
            etat = "en_cours"
        candidatures.append({"envoi": int(eid), "membre": _ident(g, int(uid)), "metier": met,
                             "metier_nom": noms.get(met, met), "etat": etat, "decide_par": _qui(g, par),
                             "decide_le": int(le or 0), "cree_le": int(cree or 0), "statut": e["statut"],
                             "etape_ouverte": int(e["etape_ouverte"] or 0), "etape_envoyee": int(e["etape_envoyee"] or 0),
                             "etapes": len(etapes_de(e)), "bilan": b})
    banque_ = [dict(q, cree_par=_qui(g, q["cree_par"]), maj_par=_qui(g, q["maj_par"])) for q in await questions_chef(g.id)]
    return {"metiers": metiers_, "membres": membres, "candidatures": candidatures,
            "chefs": [dict(v, membre=_ident(g, k), metier_nom=noms.get(v["metier"], v["metier"])) for k, v in nommes.items()],
            "questions": banque_, "gabarits": await _gabarits_chef(g.id),
            "roles": {m: {"id": str(r), "nom": getattr(g.get_role(r), "name", ""), "existe": g.get_role(r) is not None,
                          "refus": _refus_role_chef(g, g.get_role(r))} for m, r in roles.items()},
            "exigence": CHEF_EXIGENCE, "tous": METIER_TOUS}


async def chef_dossier(g, eid: int) -> dict | None:
    """Le dossier d'une candidature de chef : chaque réponse à côté de l'attendue, l'indication (une aide), la correction,
    le score, ce qu'on peut décider (et pourquoi « Accepter » ne l'est pas encore)."""
    c = await _chef_candidature(g, eid)
    e = await _envoi(eid)
    if c is None or e is None or e["guild_id"] != g.id:
        return None
    noms = {m["cle"]: m["nom"] for m in await _liste_metiers(g)}
    d = await _envoi_site(g, e)
    b = bilan(e["questions"], await _reponses(eid), await _corrections(eid), CHEF_EXIGENCE)
    d["bilan"] = b
    raison = ""
    if e["statut"] != "repondu":
        raison = "Il n'a pas encore envoyé toutes ses réponses."
    elif not b["complet"]:
        raison = f"Correction incomplète ({b['corrigees']}/{b['total']})."
    elif b["justes"] != b["total"]:
        raison = f"{b['justes']}/{b['total']} justes : 100 % exigés pour un chef d'équipe."
    decidee = c["decision"] in ("accepte", "refuse")
    return {"envoi": int(eid), "membre": _ident(g, int(c["membre_id"])), "metier": c["metier"],
            "metier_nom": noms.get(c["metier"], c["metier"]), "decision": c["decision"], "decide_par": _qui(g, c["decide_par"]),
            "decide_le": int(c["decide_le"] or 0), "note": c["note"], "questionnaire": d, "exigence": CHEF_EXIGENCE,
            "peut": {"accepter": not decidee and not raison, "refuser": not decidee, "attente": not decidee,
                     "corriger": not decidee and e["statut"] == "repondu",
                     "etape_suivante": not decidee and int(e["etape_ouverte"] or 0) > 0
                     and int(e["etape_envoyee"] or 0) >= int(e["etape_ouverte"] or 0) > 0
                     and int(e["etape_ouverte"]) < len(etapes_de(e)) and e["statut"] in EN_ATTENTE},
            "raison_accepter": raison}


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


async def _tables(db) -> dict:
    """{table: {colonnes}} des tables `recrutement_*` de la base (les brouillons de la page du candidat compris)."""
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'recrutement%'") as cur:
        noms = [r[0] for r in await cur.fetchall()]
    out = {}
    for n in noms:
        if not re.fullmatch(r"[a-z_]{1,60}", n):
            continue
        async with db.execute(f"PRAGMA table_info({n})") as cur:
            out[n] = {r[1] for r in await cur.fetchall()}
    return out


async def _candidatures_par_membre(g) -> dict:
    """{membre_id: {"tickets": {tid: canal}, "acceptes", "refuses", "ouverts", "indecis", "elimines", "premier",
    "dernier", "transcripts": [jetons]}} — toutes ses candidatures de recrutement (tickets des panneaux du clan, suivi
    des candidatures, éliminations d'office)."""
    c = await _cfg(g.id)
    pids = sorted(_panneaux(c)) if isinstance(c, dict) else []
    par: dict = {}

    def membre(uid):
        return par.setdefault(int(uid), {"tickets": {}, "acceptes": 0, "refuses": 0, "ouverts": 0, "indecis": 0,
                                         "elimines": 0, "premier": 0, "dernier": 0, "transcripts": []})
    etats: dict = {}
    if pids:
        for tid, chid, uid, statut, cree in await _lire_tolerant(
                f"SELECT id, channel_id, user_id, status, created_at FROM tickets WHERE guild_id=? AND panel_id IN"
                f" ({','.join('?' * len(pids))})", (g.id, *pids)):
            m = membre(uid)
            m["tickets"][int(tid)] = int(chid or 0)
            etats[int(tid)] = "ouvert" if statut == "open" else ""
            quand = recrutements._unix(cree)
            m["premier"] = min(x for x in (m["premier"], quand) if x) if quand else m["premier"]
            m["dernier"] = max(m["dernier"], quand or 0)
    decisions = {}
    for tid, uid, decision, raison, transcript, ferme in await _lire_tolerant(
            "SELECT ticket_id, candidat_id, decision, raison, transcript, ferme_le FROM recrutements WHERE guild_id=?",
            (g.id,)):
        m = membre(uid)
        m["tickets"].setdefault(int(tid), 0)
        prise = recrutements.decision(False, str(raison or ""), str(decision or ""))
        decisions[int(tid)] = prise
        if transcript:
            m["transcripts"].append(str(transcript))
        m["dernier"] = max(m["dernier"], int(ferme or 0))
        m["premier"] = min(x for x in (m["premier"], int(ferme or 0)) if x) if ferme else m["premier"]
    for tid, etape in await _lire("SELECT ticket_id, etape FROM recrutement_suivi WHERE guild_id=?", (g.id,)):
        if etape == "accepte":
            decisions[int(tid)] = "acceptes"
        elif etape in ("refuse", "refus_etape1") and decisions.get(int(tid)) != "acceptes":
            decisions[int(tid)] = "refuses"
    for uid, m in par.items():
        for tid in m["tickets"]:
            if etats.get(tid) == "ouvert":
                m["ouverts"] += 1
            elif decisions.get(tid) == "acceptes":
                m["acceptes"] += 1
            elif decisions.get(tid) == "refuses":
                m["refuses"] += 1
            else:
                m["indecis"] += 1
    for uid, n, dernier in await _lire("SELECT membre_id, COUNT(*), MAX(quand) FROM recrutement_eliminations WHERE"
                                       " guild_id=? GROUP BY membre_id", (g.id,)):
        m = membre(uid)
        m["elimines"] = int(n)
        m["dernier"] = max(m["dernier"], int(dernier or 0))
    for tid, url in await _lire_tolerant("SELECT ticket_id, url FROM ticket_transcripts WHERE guild_id=?", (g.id,)):
        for m in par.values():
            if int(tid or 0) in m["tickets"] and url:
                m["transcripts"].append(str(url))
    return par


def _taille_transcripts(urls) -> int:
    """La place (en octets) des transcripts de ces adresses : la page et ses images."""
    import transcript_store
    total = 0
    for jeton in {transcript_store.jeton_de(u) for u in urls}:
        if not jeton:
            continue
        chemin = transcript_store.transcript_path(jeton)
        try:
            if chemin and os.path.isfile(chemin):
                total += os.path.getsize(chemin)
            dossier_ = getattr(transcript_store, "_asset_dir", None)
            d = dossier_(jeton) if dossier_ else None
            if d and os.path.isdir(d):
                total += sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
        except OSError as ex:
            _log(f"[RECRUTEMENT][E23:DETAIL] taille {type(ex).__name__}")
    return total


def _effacer_transcripts(urls) -> int:
    """Les fichiers de ces transcripts (la page et ses images), par le stockage des transcripts. Rend le nombre effacé."""
    import shutil

    import transcript_store
    n = 0
    for jeton in {transcript_store.jeton_de(u) for u in urls}:
        if not jeton:
            continue
        try:
            chemin = transcript_store.transcript_path(jeton)
            if chemin and os.path.isfile(chemin):
                os.remove(chemin)
                n += 1
            dossier_ = getattr(transcript_store, "_asset_dir", None)
            d = dossier_(jeton) if dossier_ else None
            if d and os.path.isdir(d):
                shutil.rmtree(d)
        except OSError as ex:
            _log("[RECRUTEMENT][E23] transcript non effacé")
            _log(f"[RECRUTEMENT][E23:DETAIL] {type(ex).__name__} {ex}")
    return n


async def _concernes_purge(g) -> dict:
    """La purge exceptionnelle concerne qui n'a QUE des candidatures refusées (jamais acceptée, aucune en cours, aucune
    sans décision) et n'est pas du clan aujourd'hui."""
    par = await _candidatures_par_membre(g)
    clan = await _clan_role(g)
    out = {}
    for uid, m in par.items():
        if m["acceptes"] or m["ouverts"] or m["indecis"] or not (m["refuses"] or m["elimines"]):
            continue
        membre = g.get_member(int(uid))
        if membre is not None and clan is not None and any(getattr(r, "id", None) == clan.id
                                                          for r in getattr(membre, "roles", []) or []):
            continue
        out[uid] = m
    return out


async def purge_apercu(g) -> dict:
    """L'APERÇU de la purge exceptionnelle : les personnes (nom, nombre de candidatures, dates, place des transcripts)
    et les totaux. Rien n'est effacé ici."""
    concernes = await _concernes_purge(g)
    personnes = []
    for uid, m in sorted(concernes.items(), key=lambda x: -x[1]["dernier"]):
        personnes.append({"membre": _ident(g, uid), "candidatures": len(m["tickets"]) + m["elimines"],
                          "tickets": len(m["tickets"]), "elimines": m["elimines"], "premier": m["premier"],
                          "dernier": m["dernier"], "octets": await asyncio.to_thread(_taille_transcripts,
                                                                                      m["transcripts"])})
    return {"personnes": personnes, "total_personnes": len(personnes),
            "total_candidatures": sum(p["candidatures"] for p in personnes),
            "total_octets": sum(p["octets"] for p in personnes), "confirmation": CONFIRMATION_PURGE}


async def purge_executer(g, auteur, corps) -> tuple[int, dict]:
    """La PURGE EXCEPTIONNELLE des candidatures refusées — irréversible, jamais automatique : la confirmation forte
    (taper « PURGER »). Pour chaque personne concernée : ses tickets de recrutement refusés (lignes, suivi, audit,
    transcripts : fichiers et index), le suivi des candidatures, toutes les tables du recrutement (suivi, envois,
    réponses, brouillons, corrections, historique), les lignes du journal liées à sa candidature, la liste noire et les
    éliminations — elle pourra recandidater. Jamais touché : ses sanctions, ses autres tickets, ses messages.
    Idempotente (relancée : 0). Le journal ne garde que le nombre."""
    if not isinstance(corps, dict) or str(corps.get("confirmation") or "").strip().upper() != CONFIRMATION_PURGE:
        return _erreur(f"Pour purger, tape « {CONFIRMATION_PURGE} » : c'est irréversible.")
    concernes = await _concernes_purge(g)
    n_cand, n_fichiers = 0, 0
    async with _get_db() as db:
        tables = await _tables(db)
        for uid, m in concernes.items():
            tids = sorted(m["tickets"])
            canaux = sorted({c for c in m["tickets"].values() if c})
            n_cand += len(tids) + m["elimines"]
            for k in range(0, len(tids), 400):
                lot = tids[k:k + 400]
                marques = ",".join("?" * len(lot))
                async with db.execute(f"SELECT id FROM recrutement_envois WHERE guild_id=? AND ticket_id IN ({marques})",
                                      (g.id, *lot)) as cur:
                    envois = [int(r[0]) for r in await cur.fetchall()]
                for table, cols in tables.items():
                    if table == "recrutement_envois":
                        continue
                    if "envoi_id" in cols and envois:
                        await db.execute(f"DELETE FROM {table} WHERE envoi_id IN ({','.join('?' * len(envois))})",
                                         envois)
                    if {"guild_id", "ticket_id"} <= cols:
                        await db.execute(f"DELETE FROM {table} WHERE guild_id=? AND ticket_id IN ({marques})",
                                         (g.id, *lot))
                await db.execute(f"DELETE FROM recrutement_envois WHERE guild_id=? AND ticket_id IN ({marques})",
                                 (g.id, *lot))
                for sql in (f"DELETE FROM tickets WHERE guild_id=? AND id IN ({marques})",
                            f"DELETE FROM ticket_log_events WHERE guild_id=? AND ticket_id IN ({marques})",
                            f"DELETE FROM ticket_transcripts WHERE guild_id=? AND ticket_id IN ({marques})",
                            f"DELETE FROM recrutements WHERE guild_id=? AND ticket_id IN ({marques})"):
                    try:
                        await db.execute(sql, (g.id, *lot))
                    except sqlite3.OperationalError as ex:
                        if "no such table" not in str(ex):
                            raise
                for tid in lot:   # le journal des tickets : « Ticket #N (Recrutement…) — … »
                    try:
                        await db.execute("DELETE FROM registre WHERE guild_id=? AND membre_id=? AND categorie='Tickets'"
                                         " AND texte LIKE ?", (g.id, int(uid), f"Ticket #{int(tid)} %"))
                    except sqlite3.OperationalError as ex:
                        if "no such table" not in str(ex):
                            raise
            if canaux:
                marques = ",".join("?" * len(canaux))
                #  Le journal du site : les lignes du ticket (catégories « Tickets » et « Clan ») — JAMAIS une sanction
                #  (« Modération »), ni ses messages ailleurs.
                for sql in (f"DELETE FROM ticket_audit WHERE guild_id=? AND channel_id IN ({marques})",
                            f"DELETE FROM registre WHERE guild_id=? AND salon_id IN ({marques})"
                            " AND categorie IN ('Tickets', 'Clan')"):
                    try:
                        await db.execute(sql, (g.id, *canaux))
                    except sqlite3.OperationalError as ex:
                        if "no such table" not in str(ex):
                            raise
            for table in ("recrutement_liste_noire", "recrutement_eliminations"):
                if table in tables:
                    await db.execute(f"DELETE FROM {table} WHERE guild_id=? AND membre_id=?", (g.id, int(uid)))
            try:
                await db.execute("DELETE FROM registre WHERE guild_id=? AND membre_id=? AND (type LIKE 'recrutement.%'"
                                 " OR (type='clan.journal' AND texte LIKE '%andidature%'))", (g.id, int(uid)))
            except sqlite3.OperationalError as ex:
                if "no such table" not in str(ex):
                    raise
        await db.commit()
    for uid, m in concernes.items():
        n_fichiers += await asyncio.to_thread(_effacer_transcripts, m["transcripts"])
        await _ecrire_liste_noire_cfg(g, uid, False)
    await _au_journal(g, "recrutement.purge", f"Purge exceptionnelle : {n_cand} candidature(s) refusée(s) effacée(s)",
                      auteur_id=getattr(auteur, "id", 0))
    return 200, {"ok": True, "personnes": len(concernes), "candidatures": n_cand, "transcripts": n_fichiers,
                 "message": f"Purge faite : {n_cand} candidature(s) refusée(s) effacée(s), {len(concernes)} personne(s) "
                            "peuvent recandidater."}


async def nettoyer_liste_noire(guild_id: int, jours: int, maintenant: float | None = None) -> int:
    """La règle « Liste noire levée » : les entrées LEVÉES depuis plus de `jours` jours s'effacent (une entrée active
    ne part jamais)."""
    limite = int(maintenant or time.time()) - int(jours) * 86400
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM recrutement_liste_noire WHERE guild_id=? AND leve_le > 0 AND leve_le < ?",
                               (int(guild_id), limite))
        n = int(cur.rowcount or 0)
        cur = await db.execute("DELETE FROM recrutement_eliminations WHERE guild_id=? AND quand < ?",
                               (int(guild_id), limite))
        n += int(cur.rowcount or 0)
        await db.commit()
    return n


async def compter_liste_noire(guild_id: int, jours: int, maintenant: float | None = None) -> int:
    limite = int(maintenant or time.time()) - int(jours) * 86400
    a = await _un("SELECT COUNT(*) FROM recrutement_liste_noire WHERE guild_id=? AND leve_le > 0 AND leve_le < ?",
                  (int(guild_id), limite))
    b = await _un("SELECT COUNT(*) FROM recrutement_eliminations WHERE guild_id=? AND quand < ?",
                  (int(guild_id), limite))
    return int((a or (0,))[0] or 0) + int((b or (0,))[0] or 0)


REGLE_LISTE_NOIRE = {"cle": "recrutement_traces", "nom": "Liste noire levée et éliminations",
                     "quoi": "Les entrées levées de la liste noire du recrutement et les éliminations d'office : "
                             "effacées après ce délai (une entrée active reste).",
                     "garde_jours": 180, "min": 7, "max": RETENTION_JOURS, "ordre": 32,
                     "fn": nettoyer_liste_noire, "compter": compter_liste_noire}


async def nettoyage_site(g) -> dict:
    """Le nettoyage du recrutement, pour la zone du site : chaque règle (sa durée, réglée dans « Nettoyage ») et ce
    qu'elle retirerait maintenant."""
    import tableau as _tableau   # chargé : le site appelle cette adresse
    out = []
    for r in REGLES_RECRUTEMENT:
        jours = await _tableau.jours_regle(g.id, r["cle"]) if r["cle"] in getattr(_tableau, "REGLES", {}) \
            else r["garde_jours"]
        out.append({"cle": r["cle"], "nom": r["nom"], "quoi": r["quoi"], "garde_jours": jours, "min": r["min"],
                    "max": r["max"], "a_retirer": int(await r["compter"](g.id, jours))})
    return {"regles": out}


async def nettoyer_maintenant(g, auteur) -> tuple[int, dict]:
    """« Nettoyer maintenant » (la zone du recrutement) : les règles du recrutement, avec leurs durées."""
    import tableau as _tableau
    bilan_ = {}
    for r in REGLES_RECRUTEMENT:
        jours = await _tableau.jours_regle(g.id, r["cle"]) if r["cle"] in getattr(_tableau, "REGLES", {}) \
            else r["garde_jours"]
        bilan_[r["cle"]] = int(await r["fn"](g.id, jours))
    total = sum(bilan_.values())
    await _au_journal(g, "recrutement.nettoyage", f"Recrutement : nettoyage lancé par <@{auteur.id}> — {total} "
                      "élément(s) retiré(s)", auteur_id=auteur.id)
    return 200, {"ok": True, "bilan": bilan_, "total": total,
                 "message": f"Nettoyage fait : {total} élément(s) retiré(s)." if total else "Rien à retirer."}


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
    """Les boutons de l'équipe (le panneau « Direction », l'ancienne carte de l'étape 1) — la tête seulement,
    revérifiée à chaque clic ; un autre reçoit un court avis pour lui seul."""
    if not pret() or i.guild is None:
        return await _avis(i, _t(_gid(i), "recrutement.demarre"))
    gid = i.guild.id
    if d in ("r", "a"):   # un formulaire (le refus) ou une confirmation : la réponse ne peut pas attendre
        if not await _tete(i):
            return await _avis(i, _t(gid, "recrutement.equipe.reserve"))
        s = await _suivi(gid, tid)
        if d == "r":
            candidature = s is not None and (s["etape"] in ("etape2", "reponses") or _mode(s) == "direct")
            return await i.response.send_modal(FormulaireRefus(tid, gid, candidature))
        if s is None or not ((_mode(s) == "direct" and s["etape"] == "etape1") or s["etape"] == "reponses"):
            return await _avis(i, _t(gid, "recrutement.equipe.pas_ici"))
        return await _avis(i, _t(gid, "recrutement.equipe.accepter.confirmation", candidat=f"<@{int(s['candidat_id'])}>"),
                           efface=False, boutons=[_bouton(gid, tid, "o", "confirmer")])
    await _acquitter(i)
    if not await _tete(i):
        return await _avis(i, _t(gid, "recrutement.equipe.reserve"))
    if d == "d":
        vue = await vue_direction(i.guild, tid)
        if vue is None:
            return await _avis(i, FERME)
        return await i.followup.send(view=vue, ephemeral=True)
    if d == "s":
        return await _lien_site(i, tid)
    s = await _suivi(gid, tid)
    if d == "o":
        forcer = s is not None and _mode(s) == "direct" and s["etape"] == "etape1"
        status, corps = await accepter(i.guild, tid, i.user, forcer=forcer)
        texte = corps.get("message") if status == 200 else corps.get("erreur")
        return await _avis(i, texte or _t(gid, "recrutement.souci"), couleur=COULEUR_VERT if status == 200 else COULEUR_CIRE)
    cle = ("e1", gid, int(tid))
    if cle in _en_cours:
        return await _avis(i, _t(gid, "recrutement.equipe.en_cours"))
    _en_cours.add(cle)
    try:
        if s is not None and s["etape"] == "etape2" and s["envoi_id"]:
            ok, message = await etape_suivante(i.guild, s["envoi_id"], i.user)
            status, corps = (200, {"message": message}) if ok else (409, {"erreur": message})
        else:
            status, corps = await envoyer(i.guild, tid, i.user, None, depuis="etape1")
    finally:
        _en_cours.discard(cle)
    texte = corps.get("message") if status == 200 else corps.get("erreur")
    await _avis(i, texte or _t(gid, "recrutement.souci"), couleur=COULEUR_VERT if status == 200 else COULEUR_CIRE)


async def _refuser_depuis_discord(i, tid: int, note: str) -> None:
    await _acquitter(i)
    if not pret() or i.guild is None:
        return await _avis(i, _t(_gid(i), "recrutement.demarre"))
    if not await _tete(i):
        return await _avis(i, _t(i.guild.id, "recrutement.equipe.reserve"))
    s = await _suivi(i.guild.id, tid)
    depuis = "final" if s is not None and s["etape"] in ("etape2", "reponses") else "etape1"
    status, corps = await refuser(i.guild, tid, i.user, depuis=depuis, note=note)
    await _avis(i, corps.get("message") if status == 200 else corps.get("erreur") or _t(_gid(i), "recrutement.souci"),
                couleur=COULEUR_VERT if status == 200 else COULEUR_CIRE)


async def _lien_site(i, tid: int) -> None:
    """Le lien personnel du site, ouvert sur la candidature (« Choisir sur le site »), pour soi seul."""
    url, refus = await _lien(i) if _lien is not None else (None, "Le site n'est pas branché.")
    if not url:
        return await _avis(i, refus or "Le site n'est pas joignable pour le moment.")
    s = await _suivi(i.guild.id, tid)
    cible = f"#recrutement={int(tid)}" + (f"&membre={int(s['candidat_id'])}" if s else "")
    bouton = discord.ui.Button(label=_t(i.guild.id, "recrutement.equipe.bouton.fiche")[:80], url=url + cible,
                               emoji=_icone("lien"))
    await _avis(i, _t(i.guild.id, "recrutement.equipe.lien"), efface=False, boutons=[bouton])


async def ouvrir_formulaire(i, eid: int, page: int | None = None) -> None:
    """« Répondre au questionnaire » (ou « Continuer ») : le CANDIDAT reçoit son lien personnel vers la page web (sinon
    le formulaire de la première page sans réponse de l'étape ouverte) ; la DIRECTION voit l'aperçu en lecture seule —
    jamais un formulaire ; un autre est poliment refusé. Une étape envoyée attend la décision de la direction ; un
    questionnaire répondu, remplacé ou clos le dit."""
    if not pret() or i.guild is None:
        return await _avis(i, _t(_gid(i), "recrutement.demarre"))
    e = await _envoi(eid)
    gid = i.guild.id
    await textes_du_site.texte(gid, "recrutement.introuvable")   # le cache des textes est chargé
    if e is None or e["guild_id"] != gid:
        return await _avis(i, _t(gid, "recrutement.introuvable"))
    if i.user.id != e["candidat_id"]:
        if await _tete(i):
            return await _apercu(i, e)
        return await _avis(i, _t(gid, "recrutement.seul_candidat"))
    if e["statut"] == "repondu":
        return await _avis(i, _t(gid, "recrutement.deja"))
    if e["statut"] not in EN_ATTENTE:
        return await _avis(i, _t(gid, "recrutement.remplace"))
    k = int(e["etape_ouverte"] or 0)
    if k and int(e["etape_envoyee"] or 0) >= k:
        return await _avis(i, _t(gid, "recrutement.etape.avis", numero=k + int(e["etape_fiche"] or 0)))
    lien = _page_candidat()
    if lien is not None and await _lien_web_candidat(i, e, lien):
        return
    reponses = await _reponses(eid)
    pages = pages_envoi(e["questions"])
    ouvertes = [p for p, lot in enumerate(pages, 1) if lot and (not k or int(lot[0].get("etape") or 1) == k)]
    manque = [p for p in ouvertes if any(int(q["rang"]) not in reponses for q in pages[p - 1])]
    if page is not None and int(page) in manque:
        manque.insert(0, int(page))
    if not manque:  # tout est là mais l'étape n'a pas été close (une coupure au mauvais moment) : on la clôt
        await _acquitter(i)
        return await _etape_complete(i, e)
    await i.response.send_modal(FormulairePage(e, manque[0]))


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
        return await _avis(i, _t(_gid(i), "recrutement.demarre"))
    e = await _envoi(eid)
    gid = i.guild.id
    await textes_du_site.texte(gid, "recrutement.introuvable")   # le cache des textes est chargé
    if e is None or e["guild_id"] != gid:
        return await _avis(i, _t(gid, "recrutement.introuvable"))
    if i.user.id != e["candidat_id"]:
        return await _avis(i, _t(gid, "recrutement.seul_candidat"))
    if e["statut"] == "repondu":
        return await _avis(i, _t(gid, "recrutement.deja"))
    if e["statut"] not in EN_ATTENTE:
        return await _avis(i, _t(gid, "recrutement.remplace"))
    pages = pages_envoi(e["questions"])
    k = int(e["etape_ouverte"] or 0)
    lot = pages[page - 1] if 1 <= int(page) <= len(pages) else []
    if not lot:
        return await _avis(i, _t(gid, "recrutement.remplace"))
    n_lot = int(lot[0].get("etape") or 1)
    if k and n_lot > k:            # une étape pas encore ouverte : rien n'est gardé
        return await _avis(i, _t(gid, "recrutement.etape.fermee"))
    if k and (n_lot < k or int(e["etape_envoyee"] or 0) >= k):   # une étape déjà envoyée
        return await _avis(i, _t(gid, "recrutement.etape.avis", numero=min(n_lot, k) + int(e["etape_fiche"] or 0)))
    attendus = {int(q["rang"]) for q in lot}
    textes = {int(r): _net(v, lignes=True)[:REPONSE_CANDIDAT_MAX] for r, v in valeurs.items() if int(r) in attendus}
    if set(textes) != attendus or not all(textes.values()):
        return await _avis(i, _t(gid, "recrutement.reponse_manquante"))
    if not await _garder_page(e, textes):
        e = await _envoi(eid)
        return await _avis(i, _t(gid, "recrutement.deja" if e is not None and e["statut"] == "repondu"
                                 else "recrutement.remplace"))
    reponses = await _reponses(eid)
    restantes = [p for p, l in enumerate(pages, 1) if l and (not k or int(l[0].get("etape") or 1) == k)
                 and any(int(q["rang"]) not in reponses for q in l)]
    if not restantes:
        return await _etape_complete(i, e)
    p = restantes[0]
    await _avis(i, _t(gid, "recrutement.page_enregistree", page=page, pages=len(pages), suivante=p),
                delai=PAGE_S, couleur=COULEUR_MER,
                boutons=[BoutonPage(eid, p, len(pages), _t(gid, "recrutement.bouton.continuer", page=p, pages=len(pages)))])


async def _terminer(i, e: dict) -> None:
    """Toutes les réponses sont là : l'envoi se ferme UNE fois (`clore_envoi`), le candidat lit « Merci », puis
    (le premier seulement) `annoncer_reponses`."""
    t = _maintenant()
    premier = await clore_envoi(e, t)
    await _avis(i, await textes_du_site.texte(e["guild_id"], "recrutement.merci"), efface=False, couleur=COULEUR_VERT)
    if premier:
        await annoncer_reponses(i.guild, e, t)


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


FICHE_CONSEILLEE = [
    {"titre": "Pseudo Roblox", "aide": "Ton pseudo exact dans le jeu.", "exemple": "Kolax_RS", "type": "court",
     "requis": True, "max": 40, "options": [], "eliminatoires": []},
    {"titre": "Tranche d'âge", "aide": "Discord demande d'avoir 13 ans ou plus.", "exemple": "Choisis ta tranche",
     "type": "choix", "requis": True, "max": OPTION_MAX,
     "options": ["Moins de 13 ans", "13 – 15 ans", "16 – 17 ans", "18 ans et plus"],
     "eliminatoires": ["Moins de 13 ans"]},
    {"titre": "Ton niveau en jeu", "aide": "", "exemple": "Niveau 45", "type": "court", "requis": True, "max": 40,
     "options": [], "eliminatoires": []},
    {"titre": "Pourquoi le clan ?", "aide": "En quelques phrases.", "exemple": "", "type": "long", "requis": True,
     "max": 500, "options": [], "eliminatoires": []},
]


def _blocs(vue) -> list:
    """Une carte Discord (Components V2) en blocs pour l'aperçu du site : [{couleur, blocs: [texte · separateur ·
    image · boutons · section]}] — le texte tel que Discord l'affichera (le site le met en forme)."""
    def enfant(c):
        t = c.get("type")
        if t == 10:
            return {"type": "texte", "texte": str(c.get("content") or "")}
        if t == 14:
            return {"type": "separateur"}
        if t == 12:
            items = c.get("items") or [{}]
            return {"type": "image", "description": str(items[0].get("description") or ""),
                    "src": f"/v/{BANNIERE}" if visuels.fichier(BANNIERE) is not None else ""}
        if t == 1:
            return {"type": "boutons", "boutons": [
                {"libelle": str(b.get("label") or ""), "style": int(b.get("style") or 2), "lien": bool(b.get("url")),
                 "desactive": bool(b.get("disabled"))} for b in c.get("components") or [] if b.get("type") == 2]}
        if t == 9:
            return {"type": "section", "blocs": [x for x in (enfant(y) for y in c.get("components") or []) if x]}
        return None
    out = []
    for c in vue.to_components() if vue is not None else []:
        if c.get("type") == 17:
            out.append({"couleur": f"#{int(c.get('accent_color') or 0):06x}",
                        "blocs": [b for b in (enfant(x) for x in c.get("components") or []) if b]})
        else:
            b = enfant(c)
            if b:
                out.append({"couleur": "", "blocs": [b]})
    return out


def _texte_blocs(gid: int, *textes, couleur=COULEUR_LAITON, boutons=()) -> list:
    v = LayoutView(timeout=None)
    items = [discord.ui.TextDisplay(t) for t in textes if str(t or "").strip()]
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    return _blocs(v)


async def _messages_parcours(g, pid: str, p: dict, pnl: dict, fiche: list, nb_e: int, nb_q: int) -> list:
    """LES MESSAGES du parcours de ce panneau, dans leur ordre d'apparition — rendus par les MÊMES fonctions que le bot
    (les textes de Textes & noms, les variables remplies d'exemples) : ce que le site montre est ce que Discord
    affichera. Chacun nomme ses textes (`cles`) : « Modifier ce message » ouvre leur éditeur."""
    gid, mode = g.id, p["mode"]
    await _charger_textes(gid)
    cand = 0
    exemple = {ch["titre"]: (ch["options"][-1] if ch.get("type") == "choix" and ch.get("options")
                             else ch.get("exemple") or "…") for ch in fiche}
    d = {"gid": gid, "ticket": 0, "candidat": cand, "mode": mode, "texte_panneau": str(pnl.get("welcome_message") or ""),
         "reponses": exemple, "nb_etapes": max(1, nb_e), "nb_questions": nb_q, "banniere": _banniere()}
    f = 1 if fiche else 0
    etapes_g = p["gabarit"] or [{"titre": "", "consigne": ""}]
    total_q = max(1, nb_e or len(etapes_g))
    faux = {"id": 0, "guild_id": gid, "ticket_id": 0, "candidat_id": cand, "statut": "envoye", "liens": await liens(gid),
            "questions": [{"rang": k + 1, "etape": 1, "question": f"Question {k + 1} de l'étape…"}
                          for k in range(min(5, max(1, nb_q // total_q)))],
            "etapes": [{"numero": k + 1, "titre": str(e.get("titre") or ""), "consigne": str(e.get("consigne") or "")}
                       for k, e in enumerate(etapes_g)],
            "etape_ouverte": 1, "etape_envoyee": 0, "etape_fiche": f, "message_etape": 0, "renvoi": False}
    msgs = [{"cle": "confirmation", "titre": "La confirmation", "ou": "pour lui seul", "quand": "Il touche le panneau.",
             "cles": ["recrutement.confirmation", "recrutement.confirmation.info", "recrutement.confirmation.oui",
                      "recrutement.confirmation.non"],
             "blocs": _texte_blocs(gid, _t(gid, "recrutement.confirmation"), _t(gid, "recrutement.confirmation.info"),
                                   couleur=COULEUR_MER, boutons=[
                                       discord.ui.Button(label=_t(gid, "recrutement.confirmation.oui")[:80],
                                                         style=discord.ButtonStyle.success),
                                       discord.ui.Button(label=_t(gid, "recrutement.confirmation.non")[:80],
                                                         style=discord.ButtonStyle.secondary)])}]
    if fiche:
        msgs.append({"cle": "fiche", "titre": "Étape 1 — sa fiche", "ou": "une fenêtre de Discord",
                     "quand": "Il touche « Oui ».", "cles": ["recrutement.fiche.titre"], "fiche": fiche,
                     "titre_fenetre": _t(gid, "recrutement.fiche.titre"), "blocs": []})
        if any(ch.get("eliminatoires") for ch in fiche):
            msgs.append({"cle": "elimine", "titre": "Éliminé d'office", "ou": "pour lui seul, et en message privé",
                         "quand": "Une réponse éliminatoire : aucun ticket n'est créé.",
                         "cles": ["recrutement.elimine", "recrutement.mp.demande_refusee", "recrutement.mp.liste_noire"],
                         "blocs": _texte_blocs(gid, _t(gid, "recrutement.elimine"), couleur=COULEUR_CIRE)})
    etat_ouv = "direct" if mode == "direct" else "questionnaire" if mode == "automatique" else "demande"
    vues = [("affiche", "L'affiche", "dans le ticket (le seul message à l'ouverture)", "Le ticket s'ouvre.",
             ["recrutement.affiche.titre", "recrutement.affiche.intro", "recrutement.affiche.conditions",
              "recrutement.affiche.fiche", "recrutement.affiche.fiche_recue" if etat_ouv == "demande" else
              "recrutement.affiche.direct" if etat_ouv == "direct" else "recrutement.affiche.etape_ouverte",
              "recrutement.equipe.bouton.direction"],
             carte_affiche(dict(d, etat=etat_ouv, porte=True, numeros=(1 + f, 0, total_q + f), envoi=0)))]
    if mode != "direct":
        vues.append(("etape", "Le message de l'étape", "dans le ticket — il est prévenu",
                     "Le questionnaire part (dès l'ouverture, ou quand la direction ouvre l'étape).",
                     ["recrutement.etape.message", "recrutement.bouton.questionnaire", "recrutement.wiki",
                      "recrutement.liens.titre"], carte_etape(faux, "ouverte")))
        if mode == "approbation":
            msgs_mp = _texte_blocs(gid, _t(gid, "recrutement.mp.questionnaire", ticket="#ticket"))
        vues.append(("recue", "Une étape reçue", "le message de l'étape, réécrit",
                     "Il a envoyé l'étape : la direction décide de la suite.", ["recrutement.etape.recue",
                                                                                "recrutement.affiche.etape_recue"],
                     carte_etape(dict(faux, etape_envoyee=1), "recue")))
        vues.append(("reponses", "Toutes ses réponses", "l'affiche et le message de l'étape, réécrits",
                     "Il a envoyé la dernière étape.", ["recrutement.affiche.reponses", "recrutement.etape2.envoyees"],
                     carte_affiche(dict(d, etat="reponses", repondu_le=_maintenant()))))
    for cle, titre, ou, quand, cles, vue in vues:
        msgs.append({"cle": cle, "titre": titre, "ou": ou, "quand": quand, "cles": cles, "blocs": _blocs(vue)})
        if cle == "etape" and mode == "approbation":
            msgs.append({"cle": "mp_questionnaire", "titre": "Demande acceptée", "ou": "en message privé",
                         "quand": "La direction ouvre l'étape suivante (l'affiche est réécrite sans le prévenir).",
                         "cles": ["recrutement.mp.questionnaire"], "blocs": msgs_mp})
    noire = "\n" + _t(gid, "recrutement.mp.liste_noire") if p["liste_noire"] else ""
    msgs += [
        {"cle": "acceptee", "titre": "Acceptée", "ou": "dans le ticket, puis en message privé",
         "quand": "La direction accepte : rôle du clan, puis fermeture.",
         "cles": ["recrutement.decision.acceptee", "recrutement.mp.acceptee"],
         "blocs": _texte_blocs(gid, _t(gid, "recrutement.decision.acceptee", candidat=f"<@{cand}>"), couleur=COULEUR_VERT)
         + _texte_blocs(gid, _t(gid, "recrutement.mp.acceptee"))},
        {"cle": "refusee", "titre": "Refusée", "ou": "dans le ticket, puis en message privé",
         "quand": "La direction refuse" + (" : liste noire, puis fermeture." if p["liste_noire"] else " : fermeture."),
         "cles": ["recrutement.refus_final", "recrutement.mp.refusee", "recrutement.mp.liste_noire"],
         "blocs": _texte_blocs(gid, f"<@{cand}>\n" + _t(gid, "recrutement.refus_final"), couleur=COULEUR_CIRE)
         + _texte_blocs(gid, _t(gid, "recrutement.mp.refusee") + noire)}]
    if mode == "approbation":
        msgs.append({"cle": "demande_refusee", "titre": "Demande refusée", "ou": "dans le ticket, puis en message privé",
                     "quand": "La direction refuse sa fiche (avant le questionnaire).",
                     "cles": ["recrutement.refus_etape1", "recrutement.mp.demande_refusee", "recrutement.mp.liste_noire"],
                     "blocs": _texte_blocs(gid, f"<@{cand}>\n" + _t(gid, "recrutement.refus_etape1"), couleur=COULEUR_CIRE)
                     + _texte_blocs(gid, _t(gid, "recrutement.mp.demande_refusee") + noire)})
    msgs.append({"cle": "direction", "titre": "Le panneau « Direction »", "ou": "pour la tête seule",
                 "quand": "La direction touche « Direction » sur l'affiche.",
                 "cles": ["recrutement.direction.titre", "recrutement.equipe.decision", "recrutement.equipe.bouton.suivante",
                          "recrutement.equipe.bouton.site", "recrutement.equipe.bouton.refuser"],
                 "blocs": _blocs(panneau_direction(dict(d, etat=etat_ouv if etat_ouv != "questionnaire" else "demande",
                                                        extras={"contexte": ["Compte créé il y a 2 ans",
                                                                             "premier ticket · casier vide"]})))})
    return msgs


async def parcours_site(g, pid: str) -> dict:
    """Le parcours d'un panneau de recrutement pour le site : ses réglages, sa fiche (et ses avertissements), son
    gabarit d'étapes, ce que le questionnaire prévu pose, et ses messages dans l'ordre (aperçus de Discord)."""
    c = await _cfg(g.id)
    pnl = ((c.get("ticket_panels") or {}).get(pid) or {}) if isinstance(c, dict) else {}
    p = await parcours(g.id, pid)
    fiche = fiche_effective(p, pnl)
    accueil = str(pnl.get("welcome_message") or "")
    nb_e, nb_q = (0, 0) if p["mode"] == "direct" else await annonce_detail(g.id, accueil, pid)
    return {"panneau": pid, "nom": str(pnl.get("name") or pid), "texte_panneau": accueil, "mode": p["mode"],
            "fiche": fiche, "fiche_reglee": p["fiche"] is not None, "fiche_panneau": fiche_du_panneau(pnl),
            "avertissements": avertissements_fiche(fiche), "gabarit": p["gabarit"], "exigence": p["exigence"],
            "delai": p["delai"] if p["regle"] else int(DELAI_FERMETURE) or 20, "liste_noire": p["liste_noire"],
            "metier": p["metier"], "version": p["version"], "maj_le": p["maj_le"], "maj_par": _qui(g, p["maj_par"]),
            "regle": p["regle"], "annonce": {"etapes": nb_e, "questions": nb_q},
            "messages": await _messages_parcours(g, pid, p, pnl, fiche, nb_e, nb_q)}


async def parcours_tous(g) -> dict:
    c = await _cfg(g.id)
    pids = sorted(_panneaux(c)) if isinstance(c, dict) else []
    return {"panneaux": [await parcours_site(g, pid) for pid in pids], "modes": list(MODES),
            "types_champ": list(TYPES_CHAMP), "sources": list(SOURCES_ETAPE), "themes": THEMES,
            "modeles": [{"id": m["id"], "nom": m["nom"], "questions": len(m["questions"]), "par_defaut": m["par_defaut"]}
                        for m in await modeles(g.id)],
            "fiche_conseillee": FICHE_CONSEILLEE,
            "limites": {"fiche": FICHE_MAX, "champ_titre": CHAMP_TITRE_MAX, "champ_aide": CHAMP_AIDE_MAX,
                        "champ_exemple": CHAMP_EXEMPLE_MAX, "champ_longueur": CHAMP_LONGUEUR_MAX,
                        "options": OPTIONS_MAX, "option": OPTION_MAX, "etapes": ETAPES_MAX,
                        "etape_titre": ETAPE_TITRE_MAX, "etape_consigne": ETAPE_CONSIGNE_MAX, "par_envoi": PAR_ENVOI,
                        "delai": [DELAI_MIN, DELAI_MAX], "nouvelles": NOUVELLES_MAX}}


def _q_resume(q: dict) -> dict:
    """Une question pour l'aperçu d'une proposition : jamais sa réponse attendue."""
    return {"id": q["id"], "question": q["question"], "theme": q.get("theme", ""), "difficulte": q.get("difficulte", ""),
            "statut": q.get("statut", ""), "perso": bool(q.get("perso"))}


async def proposition(g, tid: int) -> tuple[int, dict]:
    """Le questionnaire prévu pour CE candidat (le gabarit de son panneau, tirages faits maintenant) : la page de
    l'approbation le préremplit, la direction le modifie pour lui seul, puis l'envoie."""
    rows = await _lire_tolerant("SELECT panel_id FROM tickets WHERE id=? AND guild_id=?", (int(tid), g.id))
    s = await _suivi(g.id, tid)
    if not rows and s is None:
        return _erreur("Candidature introuvable.", 404)
    pid = (s or {}).get("panneau") or (str(rows[0][0] or "") if rows else "")
    c = await _cfg(g.id)
    pnl = ((c.get("ticket_panels") or {}).get(pid) or {}) if isinstance(c, dict) else {}
    st, sel = await selection(g.id, None, str(pnl.get("welcome_message") or ""), panneau=pid or None)
    if st != 200:
        return st, sel
    fiche = int(bool(fiche_effective(await parcours(g.id, pid), pnl)))
    etapes = [dict(e, numero_candidat=int(e["numero"]) + fiche,
                   questions=[_q_resume(q) for q in sel["questions"] if int(q["etape"]) == int(e["numero"])])
              for e in sel["etapes"]]
    return 200, {"ticket": int(tid), "panneau": pid, "fiche": fiche, "etapes": etapes, "ignorees": sel["ignorees"],
                 "explications": sel["explications"], "origine": sel["origine"]}


async def apercu_candidat(g, *, ticket: int = 0, envoi: int = 0) -> tuple[int, dict]:
    """« Voir comme le candidat » (le site, en lecture seule) : l'affiche et le message de l'étape tels qu'ils sont
    dans le ticket, et chaque page de ses formulaires (les étapes ouvertes) avec les réponses déjà données — JAMAIS
    les réponses attendues."""
    s = await _suivi(g.id, ticket) if ticket else None
    eid = int(envoi or (s["envoi_id"] if s else 0) or 0)
    e = await _envoi(eid) if eid else None
    if s is None and e is None:
        return _erreur("Candidature introuvable.", 404)
    if e is not None and e["guild_id"] != g.id:
        return _erreur("Questionnaire introuvable.", 404)
    out = {"ticket": int(ticket or (e or {}).get("ticket_id") or 0), "envoi": eid, "affiche": [], "etape": [],
           "pages": [], "statut": (e or {}).get("statut", ""), "nature": (e or {}).get("nature", "recrutement")}
    if s is not None and s.get("carte") == "affiche":
        out["affiche"] = _blocs(await vue_affiche(g, int(ticket), s=s))
    if e is not None:
        reps = await _reponses(eid)
        ouverte = int(e["etape_ouverte"] or 0)
        etat = "recue" if ouverte and int(e["etape_envoyee"] or 0) >= ouverte and e["statut"] in EN_ATTENTE else \
            "ouverte" if e["statut"] in EN_ATTENTE else "repondu" if e["statut"] == "repondu" else "clos"
        out["etape"] = _blocs(carte_etape(e, etat, quand=e["repondu_le"]))
        visibles = [q for q in e["questions"] if not ouverte or int(q.get("etape") or 1) <= ouverte]
        pages = pages_envoi(visibles)
        par_num = {int(x["numero"]): x for x in etapes_de(e)}
        fiche = int(e["etape_fiche"] or 0)
        _o, _e, total = _numeros(e)
        for k, lot in enumerate(pages, 1):
            n = int(lot[0].get("etape") or 1) if lot else 1
            et = par_num.get(n) or {"titre": "", "consigne": ""}
            out["pages"].append({"page": k, "pages": len(pages), "numero": n + fiche, "total": total,
                                 "titre": et.get("titre", ""), "consigne": et.get("consigne", ""),
                                 "fenetre": _t(g.id, "recrutement.formulaire.titre", page=k, pages=len(pages),
                                               etape=n + fiche)[:45],
                                 "questions": [{"rang": int(q["rang"]), "question": q["question"],
                                                "reponse": (reps.get(int(q["rang"])) or {}).get("texte")} for q in lot]})
        out["repondues"] = sum(1 for q in visibles if int(q["rang"]) in reps)
        out["total"] = len(visibles)
    return 200, out


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


async def _envoi_site(g, e: dict, exigence: int = EXIGENCE) -> dict:
    reps, corr = await _reponses(e["id"]), await _corrections(e["id"])
    ind = await asyncio.to_thread(_indications, e["questions"], reps)
    qs = []
    for q in e["questions"]:
        rang = int(q["rang"])
        c = corr.get(rang)
        indic = ind.get(rang)
        qs.append(dict({k: v for k, v in q.items() if k != "reponse"}, attendue=q.get("reponse", ""),
                       reponse_candidat=(reps.get(rang) or {}).get("texte"),
                       recu_le=(reps.get(rang) or {}).get("recu_le", 0), indication=indic,
                       #  « pré-marquée » : la réponse dit l'attendue (ou une variante) — la personne confirme.
                       pre_juste=bool(indic and indic.get("niveau") == "identique" and c is None),
                       etape=int(q.get("etape") or 1),
                       correction=None if c is None else dict(c, par=_qui(g, c["par"]))))
    fiche = int(e.get("etape_fiche") or 0)
    return {"id": e["id"], "statut": e["statut"], "origine": e["origine"], "renvoi": e["renvoi"],
            "envoye_par": _qui(g, e["envoye_par"]),
            "envoye_le": e["envoye_le"], "repondu_le": e["repondu_le"], "nb": len(e["questions"]),
            "pages": len(pages_envoi(e["questions"])), "liens": e["liens"], "questions": qs,
            "etapes": [dict(x, numero_candidat=int(x["numero"]) + fiche) for x in etapes_de(e)],
            "etape_ouverte": int(e.get("etape_ouverte") or 0), "etape_envoyee": int(e.get("etape_envoyee") or 0),
            "etape_fiche": fiche, "nature": e.get("nature") or "recrutement", "metier": e.get("metier") or "",
            "porte": int(e.get("etape_ouverte") or 0) > 0,
            "bilan": bilan(e["questions"], reps, corr, exigence),
            "carte": _lien_discord(g, e["salon_id"], e.get("message_etape") or (e["messages"][0] if e["messages"] else 0))}


_VUE_DIRECT = RACINE / "site" / "candidature_direct.js"


def _vue_direct() -> bool:
    return _VUE_DIRECT.is_file()


async def dossier(g, tid: int) -> dict | None:
    """Tout ce que le site montre d'une candidature : l'étape, sa fiche (« Étape 1 »), chaque envoi (ses étapes, ses
    questions, ses réponses, les réponses attendues, les variantes, les indications, les corrections), les décisions,
    les liens Discord, le transcript (une candidature fermée), la liste noire, ce que la direction peut faire."""
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
    pid = (s or {}).get("panneau") or (str(tk[3] or "") if tk else "")
    p = await parcours(g.id, pid or None)
    envois_bruts = await _envois_du_ticket(g.id, tid)
    envois = [await _envoi_site(g, e, p["exigence"]) for e in envois_bruts]
    hist = await _lire("SELECT quand, quoi, par, detail FROM recrutement_historique WHERE guild_id=? AND ticket_id=?"
                       " ORDER BY id", (g.id, int(tid)))
    salon = int(tk[1]) if tk else int(s["salon_id"] if s else 0)
    courant = int(s["envoi_id"]) if s else 0
    fermeture = bool(s and s["fermeture_le"])
    mode = _mode(s)
    e_cour = next((e for e in envois_bruts if e["id"] == courant), None)
    porte = bool(e_cour and int(e_cour["etape_ouverte"] or 0) > 0)
    suivante = bool(ouvert and not fermeture and etape == "etape2" and e_cour is not None and porte
                    and e_cour["statut"] in EN_ATTENTE
                    and int(e_cour["etape_envoyee"] or 0) >= int(e_cour["etape_ouverte"] or 0)
                    and int(e_cour["etape_ouverte"]) < len(etapes_de(e_cour)))
    return {"ticket": int(tid), "statut_ticket": "ouvert" if ouvert else "ferme", "candidat": _ident(g, candidat),
            "etape": etape, "annonce": int(s["annonce"]) if s else 0, "mode": mode, "panneau": pid,
            "affiche": bool(s and s["carte"] == "affiche"),
            "ouvert_le": recrutements._unix(tk[6]) if tk else (s["cree_le"] if s else 0),
            "etape1": {"reponses": recrutements.garder(etape1 if isinstance(etape1, dict) else {})},
            "envois": envois, "envoi_courant": courant, "fermeture_prevue": fermeture,
            "decisions": [{"quand": int(h[0]), "quoi": h[1], "par": _qui(g, h[2]), "detail": h[3]} for h in hist],
            "liens_discord": {"ticket": _lien_discord(g, salon) if ouvert else "",
                              "carte_etape1": _lien_discord(g, salon, s["carte_id"]) if ouvert and s and s["carte_id"]
                              else ""},
            "transcript": "" if ouvert else await _transcript_du_ticket(g, tid),
            "liste_noire": await sur_liste_noire(g.id, candidat),
            "exigence": p["exigence"], "delai": int(_delai(p)),
            #  Les textes EXACTS que le candidat lira (ceux de Textes & noms) : la page les montre avant de refuser.
            "message_refus_etape1": await textes_du_site.texte(g.id, "recrutement.refus_etape1"),
            "message_refus": await textes_du_site.texte(g.id, "recrutement.refus_final"),
            "mp_refus": await textes_du_site.texte(g.id, "recrutement.mp.refusee"),
            "mp_refus_demande": await textes_du_site.texte(g.id, "recrutement.mp.demande_refusee"),
            "mp_accepte": await textes_du_site.texte(g.id, "recrutement.mp.acceptee"),
            "message_acceptee": await textes_du_site.texte(g.id, "recrutement.decision.acceptee", candidat=f"<@{candidat}>"),
            #  La vue en direct de la page du candidat (`site/candidature_direct.js`, l'équipe « candidature ») : la page
            #  ne la charge que si le fichier est servi (jamais un 404 dans la console).
            "vue_direct": _vue_direct(),
            "liste_noire_au_refus": p["liste_noire"],
            "peut": {"etape1": ouvert and etape == "etape1" and not fermeture and mode != "direct",
                     "etape_suivante": suivante,
                     "corriger": etape not in FINALES and any(q.get("reponse_candidat") is not None
                                                              for e in envois for q in e["questions"]),
                     "accepter": ouvert and etape in OUVERTES and not fermeture,
                     "accepter_direct": ouvert and etape == "etape1" and mode == "direct" and not fermeture,
                     "refuser": ouvert and (etape in ("etape2", "reponses") or (etape == "etape1" and mode == "direct"))
                     and not fermeture,
                     "renvoyer": ouvert and etape in ("etape2", "reponses") and not fermeture}}


async def suivi(g) -> dict:
    """Les candidatures ouvertes (« À analyser », « En cours », « À corriger ») avec leur étape et leur PROCHAINE action,
    et celles décidées depuis 30 jours (l'historique complet : `decidees`, paginé)."""
    pids = sorted(_panneaux(await _cfg(g.id)))
    tickets = []
    if pids:
        tickets = await _lire_tolerant(f"SELECT id, user_id, channel_id, created_at, panel_id, claimed_by FROM tickets"
                                       f" WHERE guild_id=? AND status='open' AND panel_id IN ({','.join('?' * len(pids))})"
                                       f" ORDER BY id", (g.id, *pids))
    suivis = {int(r[0]): dict(zip(_COLS_S, tuple(r))) for r in
              await _lire(f"SELECT {', '.join(_COLS_S)} FROM recrutement_suivi WHERE guild_id=?", (g.id,))}
    ouverts = []
    for tid, uid, salon, cree, pid, pris in tickets:
        s = suivis.get(int(tid))
        e = await _envoi(s["envoi_id"]) if s and s["envoi_id"] else None
        resume = None
        etape = s["etape"] if s else "etape1"
        if e is not None:
            ouv, env, total = _numeros(e)
            resume = {"id": e["id"], "nb": len(e["questions"]), "statut": e["statut"], "envoye_le": e["envoye_le"],
                      "repondu_le": e["repondu_le"], "etapes": len(etapes_de(e)), "etape_ouverte": ouv,
                      "etape_envoyee": env, "total": total, "porte": int(e["etape_ouverte"] or 0) > 0,
                      "bilan": bilan(e["questions"], await _reponses(e["id"]), await _corrections(e["id"]))}
        ouverts.append({"ticket": int(tid), "candidat": _ident(g, int(uid)), "ouvert": recrutements._unix(cree),
                        "etape": etape, "annonce": int(s["annonce"]) if s else 0, "mode": _mode(s),
                        "affiche": bool(s and s["carte"] == "affiche"),
                        "panneau": str(pid or ""), "pris_par": _qui(g, pris) if pris else None,
                        "fermeture_prevue": bool(s and s["fermeture_le"]), "salon": _lien_discord(g, int(salon)),
                        "action": _action(etape, e), "envoi": resume})
    ouverts_ids = {o["ticket"] for o in ouverts}
    limite = _maintenant() - 30 * 86400
    recents = [{"ticket": tid, "candidat": _ident(g, s["candidat_id"]), "etape": s["etape"],
                "maj_le": int(s["maj_le"] or 0), "par": _qui(g, s["decide_par"]),
                "transcript": await _transcript_du_ticket(g, tid) if s["etape"] in FINALES else ""}
               for tid, s in suivis.items() if tid not in ouverts_ids and int(s["maj_le"] or 0) >= limite]
    recents = sorted(recents, key=lambda x: -x["maj_le"])[:50]
    elimines = [{"membre": _ident(g, int(uid)), "champ": champ, "reponse": rep, "quand": int(q or 0)} for uid, champ, rep, q
                in await _lire("SELECT membre_id, champ, reponse, quand FROM recrutement_eliminations WHERE guild_id=?"
                               " AND quand >= ? ORDER BY quand DESC LIMIT 50", (g.id, limite))]
    return {"ouverts": ouverts, "recents": recents, "elimines": elimines, "exigence": EXIGENCE}


async def corriger(g, auteur, corps) -> tuple[int, dict]:
    """« juste » / « faux » (ou null : à revoir) sur UNE réponse, avec qui et quand. Le site ne décide rien : c'est la
    personne qui coche. `version` (facultative) : celle lue — une correction changée entre-temps → conflit. Une
    candidature décidée (un recrutement, ou un chef d'équipe) est figée."""
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
    if int(e["ticket_id"] or 0):
        s = await _suivi(g.id, e["ticket_id"])
        if s is not None and s["etape"] in FINALES:
            return _erreur("La décision est prise : la correction est figée.", 409, etape=s["etape"])
        exigence = (await parcours(g.id, (s or {}).get("panneau") or None))["exigence"]
    else:
        c = await _chef_candidature(g, eid)
        if c is not None and c["decision"] in ("accepte", "refuse"):
            return _erreur("La décision est prise : la correction est figée.", 409, etape=c["decision"])
        exigence = CHEF_EXIGENCE
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
                 "bilan": bilan(e["questions"], reps, corr, exigence)}


async def _transcript_du_ticket(g, tid: int) -> str:
    """Le transcript d'un ticket fermé (son adresse) : l'index des transcripts, sinon le suivi des candidatures."""
    for sql in ("SELECT url FROM ticket_transcripts WHERE guild_id=? AND ticket_id=? ORDER BY rowid DESC LIMIT 1",
                "SELECT transcript FROM recrutements WHERE guild_id=? AND ticket_id=?"):
        try:
            r = await _lire(sql, (g.id, int(tid)))
        except sqlite3.OperationalError as ex:   # une base sans cette table (ou d'avant cette colonne) : rien
            if "no such" not in str(ex):
                raise
            continue
        if r and r[0][0]:
            return str(r[0][0])
    return ""


def _action(etape: str, e: dict | None) -> str:
    """La PROCHAINE action d'une candidature ouverte : analyser (la demande attend), attendre (il répond), etape_suivante
    (il a envoyé une étape : à toi d'ouvrir la suivante), corriger (tout est là)."""
    if etape == "etape1":
        return "analyser"
    if etape == "reponses":
        return "corriger"
    if e is not None and int(e.get("etape_ouverte") or 0) and e["statut"] in EN_ATTENTE and \
            int(e.get("etape_envoyee") or 0) >= int(e["etape_ouverte"]):
        return "etape_suivante"
    return "attendre"


DECIDEES_PAR_PAGE = 25


async def decidees(g, requete) -> tuple[int, dict]:
    """L'historique des décisions de recrutement (acceptés, refusés, éliminés d'office), du plus récent, PAGINÉ (`page`,
    25 par page) — quand, par qui, le motif interne, le transcript. Rien ne grossit sans fin : la liste du site en
    lit une page à la fois."""
    q = dict(requete or {})
    try:
        page = int(q.get("page") or 1)
    except ValueError:
        page = 1
    page = max(1, min(page, 10 ** 6))
    lignes = []
    for tid, uid, nom, ferme, par, decision, raison, transcript in await _lire_tolerant(
            "SELECT ticket_id, candidat_id, candidat_nom, ferme_le, ferme_par, decision, raison, transcript FROM"
            " recrutements WHERE guild_id=? AND decision IN ('acceptes', 'refuses')", (g.id,)):
        ident = _ident(g, int(uid or 0))
        if not ident["present"] and nom:
            ident["nom"] = nom
        lignes.append({"ticket": int(tid or 0), "membre": ident, "decision": decision, "quand": int(ferme or 0),
                       "par": _qui(g, par), "motif": str(raison or ""), "transcript": str(transcript or "")})
    for uid, nom, champ, rep, quand in await _lire("SELECT membre_id, nom, champ, reponse, quand FROM"
                                                   " recrutement_eliminations WHERE guild_id=?", (g.id,)):
        ident = _ident(g, int(uid))
        if not ident["present"] and nom:
            ident["nom"] = nom
        lignes.append({"ticket": 0, "membre": ident, "decision": "elimine", "quand": int(quand or 0), "par": None,
                       "motif": f"Éliminé d'office · {champ}", "reponse": rep, "transcript": ""})
    lignes.sort(key=lambda x: -x["quand"])
    total = len(lignes)
    debut = (page - 1) * DECIDEES_PAR_PAGE
    return 200, {"lignes": lignes[debut:debut + DECIDEES_PAR_PAGE], "page": page, "par_page": DECIDEES_PAR_PAGE,
                 "total": total, "pages": max(1, math.ceil(total / DECIDEES_PAR_PAGE)),
                 "comptes": {k: sum(1 for x in lignes if x["decision"] == k) for k in ("acceptes", "refuses", "elimine")}}


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
    if corps.get("decision") in ("etape2", "approuver"):
        return _avec_journal(*await envoyer(g, tid, auteur, corps, depuis="etape1"), None)
    return _erreur("« decision » : « refuser », « approuver » ou « etape2 ».")


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
        s = await _suivi(g.id, tid)
        depuis = "etape1" if s is not None and s["etape"] == "etape1" else "final"
        return _avec_journal(*await refuser(g, tid, auteur, depuis=depuis, note=motif), None)
    if decision == "renvoyer":
        return _avec_journal(*await envoyer(g, tid, auteur, corps, depuis="renvoi"), None)
    return _erreur("« decision » : « accepter », « refuser » ou « renvoyer ».")


REGLES_RECRUTEMENT = (REGLE_NETTOYAGE, REGLE_LISTE_NOIRE)


async def _r_parcours(g, auteur, requete, corps):
    return 200, await parcours_tous(g)


async def _r_parcours_ecrire(g, auteur, requete, corps):
    st, rep = await enregistrer_parcours(g, auteur, corps)
    p = rep.get("parcours") or {}
    return _avec_journal(st, rep, f"Recrutement : parcours du panneau « {p.get('nom', '')} » enregistré "
                                  f"({p.get('mode', '')})")


async def _r_proposition(g, auteur, requete, corps):
    try:
        tid = _ticket_requis(dict(requete or {}))
    except _Invalide as ex:
        return _erreur(str(ex))
    return await proposition(g, tid)


async def _r_apercu(g, auteur, requete, corps):
    q = dict(requete or {})
    t, e = str(q.get("ticket") or ""), str(q.get("envoi") or "")
    if not (t.isdigit() or e.isdigit()):
        return _erreur("« ticket » ou « envoi » : un numéro.")
    return await apercu_candidat(g, ticket=int(t) if t.isdigit() else 0, envoi=int(e) if e.isdigit() else 0)


async def _r_etape_suivante(g, auteur, requete, corps):
    """« Étape suivante » sur le site : la demande approuvée (une candidature à l'étape 1 : le questionnaire part, ses
    étapes choisies pour lui si `etapes` est donné), sinon l'étape suivante de son questionnaire (ou d'un chef)."""
    corps = corps if isinstance(corps, dict) else {}
    if corps.get("envoi") is not None and corps.get("ticket") is None:
        try:
            eid = _entier(corps, "envoi", mini=1)
        except _Invalide as ex:
            return _erreur(str(ex))
        ok, message = await etape_suivante(g, eid, auteur)
        return _avec_journal(*((200, {"ok": True, "message": message}) if ok else _erreur(message, 409)), None)
    try:
        tid = _ticket_requis(corps)
    except _Invalide as ex:
        return _erreur(str(ex))
    s = await _suivi(g.id, tid)
    if s is None or s["etape"] == "etape1":
        return _avec_journal(*await envoyer(g, tid, auteur, corps, depuis="etape1"), None)
    if not s["envoi_id"]:
        return _erreur(_texte_etape(s["etape"]), 409)
    ok, message = await etape_suivante(g, s["envoi_id"], auteur)
    return _avec_journal(*((200, {"ok": True, "message": message}) if ok else _erreur(message, 409)), None)


async def _r_decidees(g, auteur, requete, corps):
    return await decidees(g, requete)


async def _r_liste_noire(g, auteur, requete, corps):
    return 200, await liste_noire_site(g)


async def _r_liste_noire_lever(g, auteur, requete, corps):
    return _avec_journal(*await lever_liste_noire(g, auteur, corps), None)


async def _r_nettoyage(g, auteur, requete, corps):
    return 200, await nettoyage_site(g)


async def _r_nettoyage_lancer(g, auteur, requete, corps):
    return _avec_journal(*await nettoyer_maintenant(g, auteur), None)


async def _r_purge(g, auteur, requete, corps):
    return 200, await purge_apercu(g)


async def _r_purge_lancer(g, auteur, requete, corps):
    return _avec_journal(*await purge_executer(g, auteur, corps), None)


async def _r_chefs(g, auteur, requete, corps):
    return 200, await chefs_site(g)


async def _r_chef_question(g, auteur, requete, corps):
    st, rep = await enregistrer_question_chef(g, auteur, corps)
    q = rep.get("question") or {}
    return _avec_journal(st, rep, f"Chefs d'équipe : question « {extrait(q.get('question'), 80)} » "
                                  + ("ajoutée" if rep.get("cree") else "modifiée"))


async def _r_chef_question_retirer(g, auteur, requete, corps):
    st, rep = await retirer_question_chef(g, auteur, corps)
    q = rep.get("question") or {}
    return _avec_journal(st, rep, f"Chefs d'équipe : question « {extrait(q.get('question'), 80)} » "
                                  + ("retirée" if q.get("retiree") else "remise dans la banque"))


async def _r_chef_gabarit(g, auteur, requete, corps):
    st, rep = await enregistrer_gabarit_chef(g, auteur, corps)
    return _avec_journal(st, rep, f"Chefs d'équipe : gabarit du métier « {(corps or {}).get('metier', '')} » enregistré")


async def _r_chef_proposition(g, auteur, requete, corps):
    q = dict(requete or {})
    membre, metier = str(q.get("membre") or ""), str(q.get("metier") or "")
    if not membre.isdigit() or not FORMAT_ID.fullmatch(metier or "-"):
        return _erreur("« membre » et « metier » sont demandés.")
    m = g.get_member(int(membre))
    if m is None or not await du_clan(g, m):
        return _erreur("Seul un membre du clan peut devenir chef d'équipe.", 409)
    return 200, dict(await proposition_chef(g, int(membre), metier), metiers_membre=await _metiers_de(g, m))


async def _r_chef_proposer(g, auteur, requete, corps):
    return _avec_journal(*await proposer_chef(g, auteur, corps), None)


async def _r_chef_dossier(g, auteur, requete, corps):
    e = str(dict(requete or {}).get("envoi") or "")
    if not e.isdigit():
        return _erreur("« envoi » : un numéro.")
    d = await chef_dossier(g, int(e))
    return (200, d) if d is not None else _erreur("Candidature de chef introuvable.", 404)


async def _r_chef_decision(g, auteur, requete, corps):
    return _avec_journal(*await decider_chef(g, auteur, corps), None)


async def _r_chef_retirer(g, auteur, requete, corps):
    return _avec_journal(*await retirer_chef(g, auteur, corps), None)


async def _r_chef_role(g, auteur, requete, corps):
    return _avec_journal(*await regler_role_chef(g, auteur, corps), None)


async def _r_chef(g, auteur, requete, corps):
    m = str(dict(requete or {}).get("membre") or "")
    if not m.isdigit():
        return _erreur("« membre » : un identifiant.")
    return 200, {"chef": await chef_de(g, int(m))}


def _objet(genre: str, valeur) -> str | None:
    v = str(valeur if valeur is not None else "").strip()
    return f"{genre}:{v}" if v and FORMAT_ID.fullmatch(v) else None


async def _v_corriger(c: dict):
    """Le verrou d'une correction : le dossier de son ticket, ou la candidature du chef (sans ticket)."""
    eid = str((c or {}).get("envoi") or "")
    if not eid.isdigit():
        return None
    e = await _envoi(int(eid))
    if e is None:
        return None
    return f"dossier:{int(e['ticket_id'])}" if int(e["ticket_id"] or 0) else f"chef:{int(e['id'])}"


def _v_suivante(c: dict):
    c = c or {}
    return _objet("dossier", c.get("ticket")) if c.get("ticket") is not None else _objet("chef", c.get("envoi"))


def _route(methode: str, fn, *, hors_ligne: bool = False, corps_max: int = 16 * 1024, grave=None, verrou=None) -> dict:
    d = {"methode": methode, "fn": fn, "ecriture": methode == "POST", "hors_ligne": hors_ligne,
         "corps_max": corps_max, "grave": grave}
    if verrou is not None:
        d["verrou"] = verrou
    return d


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
    "recrutement/corriger": _route("POST", _r_corriger, hors_ligne=True, corps_max=2048, verrou=_v_corriger),
    "recrutement/etape1": _route("POST", _r_etape1, corps_max=32 * 1024),
    #  Accepter donne le rôle du clan : compté avec les actions graves « roles » du site.
    "recrutement/decision": _route("POST", _r_decision, corps_max=32 * 1024, grave="roles"),
    #  26/10/2026 : le parcours de chaque panneau, la proposition d'étapes d'un candidat, « Voir comme le candidat », le
    #  passage d'étape, l'historique des décisions, la liste noire, le nettoyage, la purge exceptionnelle.
    "recrutement/parcours": [_route("GET", _r_parcours, corps_max=0),
                             _route("POST", _r_parcours_ecrire, hors_ligne=True, corps_max=32 * 1024,
                                    verrou=lambda c: _objet("parcours", (c or {}).get("panneau")))],
    "recrutement/proposition": _route("GET", _r_proposition, corps_max=0),
    "recrutement/apercu": _route("GET", _r_apercu, corps_max=0),
    "recrutement/etape_suivante": _route("POST", _r_etape_suivante, corps_max=32 * 1024, verrou=_v_suivante),
    "recrutement/decidees": _route("GET", _r_decidees, corps_max=0),
    "recrutement/liste_noire": _route("GET", _r_liste_noire, corps_max=0),
    "recrutement/liste_noire/lever": _route("POST", _r_liste_noire_lever, corps_max=2048,
                                            verrou=lambda c: "liste_noire:tout" if (c or {}).get("tout") is True
                                            else _objet("liste_noire", (c or {}).get("membre"))),
    "recrutement/nettoyage": [_route("GET", _r_nettoyage, corps_max=0),
                              _route("POST", _r_nettoyage_lancer, corps_max=1024)],
    "recrutement/purge": [_route("GET", _r_purge, corps_max=0),
                          _route("POST", _r_purge_lancer, corps_max=1024, verrou=lambda c: "recrutement:purge")],
    #  Les chefs d'équipe : leur banque à part, les gabarits par métier, proposer, décider, le rôle de chaque métier.
    "recrutement/chefs": _route("GET", _r_chefs, corps_max=0),
    "recrutement/chefs/question": _route("POST", _r_chef_question, hors_ligne=True,
                                         verrou=lambda c: _objet("chef_question", (c or {}).get("id"))),
    "recrutement/chefs/question/retirer": _route("POST", _r_chef_question_retirer, hors_ligne=True, corps_max=2048,
                                                 verrou=lambda c: _objet("chef_question", (c or {}).get("id"))),
    "recrutement/chefs/gabarit": _route("POST", _r_chef_gabarit, hors_ligne=True, corps_max=16 * 1024,
                                        verrou=lambda c: _objet("chef_gabarit", (c or {}).get("metier"))),
    "recrutement/chefs/proposition": _route("GET", _r_chef_proposition, corps_max=0),
    "recrutement/chefs/proposer": _route("POST", _r_chef_proposer, corps_max=16 * 1024,
                                         verrou=lambda c: _objet("chef_membre", (c or {}).get("membre"))),
    "recrutement/chefs/dossier": _route("GET", _r_chef_dossier, corps_max=0),
    #  Nommer chef donne un rôle : compté avec les actions graves « roles » du site.
    "recrutement/chefs/decision": _route("POST", _r_chef_decision, corps_max=2048, grave="roles",
                                         verrou=lambda c: _objet("chef", (c or {}).get("envoi"))),
    "recrutement/chefs/retirer": _route("POST", _r_chef_retirer, corps_max=1024, grave="roles",
                                        verrou=lambda c: _objet("chef_membre", (c or {}).get("membre"))),
    "recrutement/chefs/role": _route("POST", _r_chef_role, corps_max=1024, grave="roles",
                                     verrou=lambda c: _objet("chef_role", (c or {}).get("metier"))),
    "recrutement/chef": _route("GET", _r_chef, corps_max=0),
}
