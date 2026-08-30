"""activite.py — Système d'activité : suivi, escalade, récompenses.

DÉSACTIVÉ PAR DÉFAUT. Rien ne tourne tant que le propriétaire n'a pas activé le
système ET désigné au moins un rôle surveillé (ou « tout le monde »).

═══════════════════════════════════════════════════════════════════════════════
LE PRINCIPE
═══════════════════════════════════════════════════════════════════════════════
Un membre est ACTIF sur une journée s'il pose AU MOINS UN geste volontaire :
  · envoyer un message                   (source « m »)
  · parler en vocal — voir plus bas      (source « v »)
  · réagir à un message                  (source « r »)
  · utiliser une commande ou un bouton   (source « i »)
  · ouvrir un fil de discussion          (source « f »)
  · voter à un sondage                   (source « s »)

⚠️ LE STATUT « EN LIGNE » N'EST PAS UNE SOURCE, et ne le sera pas. Être connecté
ne prouve rien : un téléphone oublié allumé, un compte secondaire en veille
affichent « en ligne » sans qu'aucun humain soit là. Idem pour le fait de RESTER
assis dans un salon vocal : seule l'entrée, le changement de salon, la reprise du
micro ou le partage d'écran comptent — des gestes, pas une présence.
Une seule suffit. La journée va de minuit à minuit **heure de Paris**, et la
semaine du lundi 00h00 au lundi 00h00 — voir `activite_calendrier.py`.

═══════════════════════════════════════════════════════════════════════════════
DEUX MESURES, PAS UNE — C'EST TOUTE L'ASTUCE DU SYSTÈME
═══════════════════════════════════════════════════════════════════════════════
Compter « depuis quand il n'a rien fait » ne suffit pas, et se contourne en une
soirée : il suffit de poster UN message la veille du rappel pour remettre le
compteur à zéro et disparaître des listes toute l'année. C'est exactement le
scénario décrit par le propriétaire (« le ping est le vendredi, alors je poste
tous les vendredis »). On mesure donc DEUX choses indépendantes :

  1. LE SILENCE — jours consécutifs sans le moindre geste.
     Il déclenche les paliers : rôle AFK, retrait des rôles, départ.
     Il compte AUJOURD'HUI : quelqu'un qui poste maintenant est à 0 tout de
     suite, et récupère tout dans la foulée.

  2. LA PRÉSENCE — nombre de jours vus sur les 7 derniers jours COMPLETS.
     Elle déclenche le rappel doux. Le posteur du vendredi a un silence
     minuscule mais une présence de 1/7 : il est nommé chaque semaine.
     Elle ne compte QUE des journées terminées — juger la journée en cours
     punirait un membre parce qu'il n'a pas encore parlé ce matin.

  Et parce qu'un rappel doux sans suite se transforme en habitude, les rappels
  doux CONSÉCUTIFS s'accumulent : au bout de `doux_max` (défaut 3), le membre
  bascule au premier palier comme un absent. Le contournement se referme.

⚠️ La fenêtre est BORNÉE par l'ancienneté : arrivé il y a deux jours, on juge
sur deux jours, pas sur sept. Sans ça, tout nouveau venu est « 1 jour sur 7 »
dès son inscription et reçoit un rappel avant d'avoir dit bonjour.

L'ESCALADE, par rôle surveillé, avec des seuils propres à chaque rôle :
  · palier 1 (défaut 7 j)  → rappel public + RÔLE AFK, qui masque tout le serveur
                             sauf le salon des absents et le salon de retour
  · palier 2 (défaut 14 j) → 2e rappel + RETRAIT DE TOUS SES RÔLES ; pour tout
                             récupérer, le membre écrit dans le salon de retour
  · palier 3 (défaut 21 j) → proposé à l'expulsion — JAMAIS automatique, un humain
                             valide dans un panneau dédié

═══════════════════════════════════════════════════════════════════════════════
DEUX RÈGLES DU PROPRIÉTAIRE LEVÉES ICI, EN CONNAISSANCE DE CAUSE (11/08/2026)
═══════════════════════════════════════════════════════════════════════════════
1. « Aucun ping automatique de membres » → le rappel hebdomadaire MENTIONNE les
   inactifs. Choix explicite : sans ping, personne ne revient.
2. « Le bot ne retire jamais un rôle de lui-même » → il le retire au palier 2.
   Sans ça le système n'a aucun effet.
L'EXPULSION, elle, reste MANUELLE. Le bot propose, un humain clique.

═══════════════════════════════════════════════════════════════════════════════
CE QUI N'EST JAMAIS TOUCHÉ, À AUCUN PALIER
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire du serveur, le super-owner, les administrateurs, les membres
immunisés et les bots. Vérifié AVANT chaque action, pas seulement à l'entrée.

FAIL-SAFE : tout est enveloppé. Une panne du système d'activité ne doit jamais
empêcher un message de passer ni une sanction de s'appliquer.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import activite_calendrier as cal

#  Les bornes de temps vivent dans `activite_calendrier` : semaine du lundi 00h00
#  au lundi 00h00, mois du 1er au 1er, heure de Paris. Ne pas recalculer de dates
#  ici — c'est là que se cachent les décalages d'une ou deux heures.
JOUR_FMT = cal.JOUR_FMT

#  Les sources d'activité. La valeur est la lettre stockée en base.
#
#  ⚠️ CE QUI N'EST PAS UNE SOURCE, ET NE LE SERA PAS : le STATUT EN LIGNE.
#  Être « connecté » ne prouve rien — un téléphone oublié allumé, un client
#  ouvert en permanence, un compte secondaire en veille affichent tous « en
#  ligne » sans qu'aucun humain soit là. C'est justement ce que ce système doit
#  attraper. Chaque source ci-dessous demande un GESTE VOLONTAIRE.
SOURCE_MESSAGE = "m"
SOURCE_VOCAL = "v"
SOURCE_REACTION = "r"
SOURCE_INTERACTION = "i"      # commande, bouton, menu déroulant
SOURCE_FIL = "f"              # a ouvert un fil de discussion
SOURCE_SONDAGE = "s"          # a voté à un sondage
SOURCES = {
    SOURCE_MESSAGE: "message",
    SOURCE_VOCAL: "vocal",
    SOURCE_REACTION: "réaction",
    SOURCE_INTERACTION: "commande ou bouton",
    SOURCE_FIL: "fil ouvert",
    SOURCE_SONDAGE: "vote à un sondage",
}

#  Seuils par défaut, en JOURS d'inactivité. Chaque rôle surveillé peut avoir les
#  siens ; ceux-ci ne servent que de point de départ dans le panneau.
#
#  ⚠️ DÉCALÉS D'UNE SEMAINE LE 30/08/2026, sur description explicite du
#  propriétaire, et le changement ne peut qu'ADOUCIR le système.
#  Ses mots : « Si y a aucun message dans la semaine, on leur dira d'être
#  actif ; au bout de la 2e semaine, pas de messages, et ben on les met AFK
#  avec le système de rôle. »
#  Autrement dit : la PREMIÈRE semaine de silence n'est qu'un avertissement,
#  et le rôle AFK — celui qui MASQUE tout le serveur — n'arrive qu'à la
#  deuxième. L'ancienne échelle posait ce rôle dès 7 jours.
#      avertissement  → le rappel doux, qui ne masque rien (voir ci-dessous)
#      14 j de silence → rôle AFK (masque)
#      21 j            → retrait de tous les rôles
#      28 j            → proposé à l'expulsion, jamais automatique
#  Un membre silencieux entre 7 et 13 jours n'est pas oublié pour autant : sa
#  présence tombe à 0 sur 7, il passe donc par le rappel doux — l'avertissement
#  que le propriétaire décrit, sans le masquage.
#
#  ⚠️ CES VALEURS SONT DES DÉFAUTS. Un serveur qui a déjà réglé ses seuils dans
#  le panneau garde les siens : les changer ici ne le touche PAS. Il faut le
#  vérifier dans « Seuils », et c'est dit au propriétaire.
SEUIL_RAPPEL_DEFAUT = 14
SEUIL_RETRAIT_DEFAUT = 21
SEUIL_EXPULSION_DEFAUT = 28

#  La fenêtre de présence : sur combien de jours COMPLETS on regarde si le membre
#  s'est montré. Sept jours = une semaine pleine, quel que soit le jour du rappel.
#  Volontairement GLISSANTE et non calée sur le lundi : une fenêtre calée serait
#  contournable en postant toujours le même jour de la semaine.
FENETRE_PRESENCE_DEFAUT = 7

#  En dessous de ce nombre de jours vus sur la fenêtre, le membre reçoit le
#  rappel doux — il est venu, mais trop peu pour qu'on parle de présence.
SEUIL_PRESENCE_DEFAUT = 3

#  Combien de rappels doux CONSÉCUTIFS avant de basculer au premier palier.
#  C'est ce qui referme le contournement : poster une fois par semaine évite le
#  silence, mais pas ça.
DOUX_MAX_DEFAUT = 3

#  Sous cette ancienneté (en jours complets observables), on ne juge PERSONNE sur
#  sa présence. Un membre arrivé avant-hier n'a pas de semaine à montrer.
ANCIENNETE_MINIMALE = 3

#  Garde-fou : un passage ne peut jamais toucher plus de membres que ça. Si le
#  compte dépasse, on n'agit sur PERSONNE et on alerte le staff — c'est le signe
#  d'un bug de suivi (base vidée, horloge décalée), pas d'un serveur qui dort.
PLAFOND_ACTIONS_PAR_PASSAGE = 25

#  ⚠️ LES ÉTIQUETTES ONT LEUR PROPRE BUDGET, ET IL EST EN SECONDES.
#  Le plafond ci-dessus borne les actions DESTRUCTRICES (retirer tous les rôles
#  d'un membre) : 25 par passage, exprès, pour qu'un réglage malheureux ne
#  dépouille pas un serveur entier avant qu'on s'en aperçoive.
#
#  Poser une étiquette est l'inverse : réversible, sans effet sur les
#  permissions, et il faut la poser sur BEAUCOUP de monde d'un coup (959 chez
#  le propriétaire). À 25 par passage de 6 h, il aurait fallu dix jours.
#
#  Discord n'a AUCUNE API d'attribution de rôle en masse : c'est un appel par
#  membre. On cadence donc SOUS le seau plutôt que de le saturer, et on borne
#  en TEMPS et non en nombre — le débit réel de Discord n'est pas prouvable,
#  mais un budget de 240 s garantit par construction que le corps de la tâche
#  reste très loin des 6 h, quel que soit ce débit.
#
#  ⚠️ SEUL LE PREMIER BALAYAGE COÛTE. Un membre qui porte déjà l'étiquette ne
#  consomme ni appel ni pause : en régime établi, ce budget n'est jamais entamé.
PAUSE_ENTRE_ETIQUETTES = 1.0          # secondes entre deux écritures de rôle
BUDGET_ETIQUETTES_PAR_PASSAGE = 240.0  # secondes, partagé pose ET retrait

#  Injectés par bot.py au démarrage (setup) : on ne l'importe pas, sinon boucle.
_get_db = None
_cfg = None
_db_set = None
_est_immunise = None
_log = print


# ═══════════════════════════════════════════════════════════════════════════════
#  Câblage
# ═══════════════════════════════════════════════════════════════════════════════

def setup(*, get_db, cfg, db_set, est_immunise, log=None):
    """Branche le module sur les fonctions de bot.py.

    `est_immunise(member) -> bool` doit renvoyer True pour tout membre qui ne doit
    JAMAIS être touché : propriétaire, super-owner, administrateur, immunisé, bot.
    """
    global _get_db, _cfg, _db_set, _est_immunise, _log
    _get_db, _cfg, _db_set, _est_immunise = get_db, cfg, db_set, est_immunise
    if log is not None:
        _log = log


async def init_db():
    """Crée les tables. Idempotent."""
    async with _get_db() as db:
        # Un jour d'activité par membre. La clé primaire garantit qu'un même jour
        # ne peut pas être compté deux fois, quelle que soit la rafale de messages.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS activite_jours("
            " guild_id INTEGER NOT NULL,"
            " user_id INTEGER NOT NULL,"
            " jour TEXT NOT NULL,"
            " sources TEXT NOT NULL DEFAULT '',"
            " PRIMARY KEY(guild_id, user_id, jour))"
        )
        # Index pour « qui n'a rien fait depuis X » : c'est LA requête chaude.
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_activite_jours_guild_jour"
            " ON activite_jours(guild_id, jour)"
        )
        # Où en est chaque membre dans l'escalade.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS activite_etat("
            " guild_id INTEGER NOT NULL,"
            " user_id INTEGER NOT NULL,"
            " dernier_actif TEXT,"
            " palier INTEGER NOT NULL DEFAULT 0,"
            " roles_retires TEXT NOT NULL DEFAULT '[]',"
            " derniere_alerte TEXT,"
            " PRIMARY KEY(guild_id, user_id))"
        )
        #  Compteur de rappels doux consécutifs (voir l'en-tête : c'est lui qui
        #  attrape le posteur du vendredi). Ajouté après coup : `ALTER` toléré en
        #  échec, la colonne existe déjà sur les serveurs à jour.
        for colonne, definition in (
            ("doux", "INTEGER NOT NULL DEFAULT 0"),
            ("derniere_semaine_doux", "TEXT"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE activite_etat ADD COLUMN {colonne} {definition}")
            except Exception:
                pass          # colonne déjà présente

        #  Qui est parti pour inactivité, et quand. Sert à accueillir autrement
        #  quelqu'un qui revient après une expulsion : il ne redécouvre pas la
        #  règle au moment où elle le frappe une deuxième fois.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS activite_expulses("
            " guild_id INTEGER NOT NULL,"
            " user_id INTEGER NOT NULL,"
            " jour TEXT NOT NULL,"
            " silence INTEGER NOT NULL DEFAULT 0,"
            " prevenu INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY(guild_id, user_id))"
        )
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration — tout vit dans `guild_config`, donc dans le cache existant
# ═══════════════════════════════════════════════════════════════════════════════

CLES_DEFAUT = {
    "activite_enabled": False,          # interrupteur général — OFF par défaut
    #  ⚠️ TOUT LE MONDE PAR DÉFAUT. Sur un serveur Discord, tous les membres
    #  portent @everyone et beaucoup n'ont aucun autre rôle : exiger de désigner
    #  un rôle laissait le système allumé mais aveugle, sans que ça se voie.
    #  Allumer le système suffit donc à couvrir tout le monde ; les rôles servent
    #  à AFFINER (seuils, salons, jours différents), pas à activer.
    "activite_tout_le_monde": True,
    "activite_roles": {},               # {role_id(str): {rappel, retrait, expulsion}}
    "activite_salon_annonce": 0,        # où poster le rappel hebdomadaire
    "activite_salon_retour": 0,         # où un membre écrit pour récupérer son rôle
    "activite_salon_staff": 0,          # où poster la liste des expulsables
    #  ⚠️ LE SALON AFK — demandé le 30/08/2026, et il ne fait PAS ce qu'on
    #  croit. Écrire n'importe où marque déjà l'activité ET rend ses rôles à
    #  un membre étiqueté (voir `on_message` dans bot.py, et
    #  `retour_immediat`). Ce salon n'ajoute donc AUCUN pouvoir de retour : il
    #  ajoute un ENDROIT PRÉVU pour le faire, qui ne se remplit jamais.
    #  Le propriétaire : « le message s'auto supprime automatiquement comme ça,
    #  ça évite de laisser des pavés de messages. Ça permet à l'utilisateur
    #  d'envoyer un message. Le message supprime, OK, il est redevenu actif. »
    #  ⚠️ ET IL NE DONNE AUCUNE IMMUNITÉ. Un message aujourd'hui ne dispense
    #  pas de la semaine prochaine : « s'il devient inactif parce qu'il a été
    #  juste actif un jour, mais qu'il est inactif sur 34 jours, forcément on
    #  va le redétecter comme inactif ». La présence exigée reste
    #  `activite_seuil_presence` jours par fenêtre, quel que soit le salon.
    "activite_salon_afk": 0,            # salon « je suis là », auto-nettoyé
    #  Combien de secondes le message reste visible avant d'être effacé. Zéro
    #  n'est PAS un bon réglage : le membre doit voir que c'est parti, sinon il
    #  réécrit — et on obtient l'inverse du salon propre recherché.
    "activite_afk_secondes": 8,
    "activite_jour_rappel": 6,          # 0 = lundi … 6 = DIMANCHE (fin de semaine)
    "activite_derniere_semaine": "",    # semaine ISO du dernier rappel envoyé
    #  Immunité PROPRE au système d'activité : dispenser quelqu'un de présence
    #  n'a rien à voir avec le dispenser de modération. Un ami du serveur, un
    #  ancien, un bot partenaire n'ont pas à être surveillés — sans pour autant
    #  devenir intouchables face aux insultes ou au spam.
    "activite_roles_immunises": [],     # rôles dispensés d'activité
    "activite_membres_immunises": [],   # membres dispensés, un par un

    #  ── Les rôles d'inactivité, portés PAR le membre absent ──────────────────
    #  Le système ne se contente plus de compter : il ÉTIQUETTE. Le rôle rend
    #  l'absence visible de tous, y compris de l'intéressé, et c'est lui qui
    #  porte le masquage des salons (voir `activite_niveaux.py`).
    #  ⚠️ AJOUTÉ LE 20/08/2026 — L'ÉTIQUETTE QUI REMPLACE 959 MENTIONS.
    #  Le palier « doux » n'avait AUCUN rôle : le message listait donc les
    #  membres un par un. Le code supposait « ils sont peu nombreux par
    #  construction » ; chez le propriétaire ils étaient 959, affichés en
    #  30 mentions suivies d'un « +929 ». Sa demande : « au lieu de mentionner
    #  900 ou 1000 personnes, tu mentionnes un rôle ».
    #  ⚠️ CE RÔLE NE MASQUE RIEN. Il ne sert qu'à être porté et mentionné —
    #  voir `roles_afk` vs `roles_etiquettes` dans activite_niveaux.py.
    "activite_role_doux": 0,            # posé au palier « doux » — aucune sanction
    "activite_role_niveau1": 0,         # posé au 1er palier — le membre garde tout
    "activite_role_niveau2": 0,         # posé au 2e — tous ses autres rôles partent
    #  ⚠️ LA PHASE 3, AJOUTÉE LE 20/08/2026 — « comptes abandonnés ».
    #  Elle n'avait aucun rôle, donc elle ne pouvait pas être mentionnée : le
    #  propriétaire demandait que « tout le monde ait bien un rôle spécifique
    #  qui puisse être mentionné quand ils sont inactifs ». Elle MASQUE comme
    #  les paliers 1 et 2 — voir `roles_afk`. L'expulsion, elle, reste une
    #  proposition au staff et n'est JAMAIS automatique.
    "activite_role_abandon": 0,         # posé au 3e — plus aucune activité
    #  Masquer TOUT le serveur aux porteurs de ces rôles, sauf les deux salons
    #  d'activité. Réglable, parce que c'est l'action la plus visible du système.
    "activite_masquer_salons": True,

    #  ── La mesure de présence (voir l'en-tête du module) ─────────────────────
    "activite_fenetre": FENETRE_PRESENCE_DEFAUT,
    "activite_seuil_presence": SEUIL_PRESENCE_DEFAUT,
    "activite_doux_max": DOUX_MAX_DEFAUT,

    #  ── Accueil de ceux qui reviennent après une expulsion pour inactivité ───
    "activite_message_retour": True,

    #  ── L'ANCRE D'OBSERVATION — la date à partir de laquelle on a le droit de
    #  reprocher une absence. Voir `observation_jours()` : sans elle, allumer le
    #  système sur un serveur existant classait TOUT LE MONDE en expulsion le
    #  premier soir, puisque le silence d'un membre jamais vu vaut son ancienneté
    #  sur le serveur. Écrite une seule fois, jamais réécrite par un OFF/ON.
    "activite_observe_depuis": "",
    #  Dernier jour où une alerte d'ÉTAT a été postée au staff (quota, suivi
    #  muet, expulsions en attente). Sert à ne pas la répéter toutes les 6 h.
    "activite_jour_alerte": "",
}


async def config(guild_id: int) -> dict:
    """Config du système pour une guilde, défauts compris."""
    try:
        c = await _cfg(guild_id)
    except Exception as ex:
        _log(f"[activite config] {ex}")
        c = {}
    out = dict(CLES_DEFAUT)
    for k in out:
        if k in c:
            out[k] = c[k]
    #  `activite_roles` peut revenir en JSON si un vieux code l'a écrit en texte.
    if isinstance(out["activite_roles"], str):
        try:
            out["activite_roles"] = json.loads(out["activite_roles"])
        except Exception:
            out["activite_roles"] = {}
    return out


#  Pseudo-identifiant du mode « tout le serveur ». Il se configure exactement
#  comme un rôle — même écran, mêmes réglages — pour qu'il n'y ait qu'UNE façon
#  de raisonner dans tout le code.
ROLE_TOUS = "*"

#  Ce que chaque rôle surveillé peut définir POUR LUI SEUL. Une valeur laissée à
#  `None` (ou 0 pour un salon) veut dire « prends le réglage global du serveur ».
#  C'est ce qui permet à un rôle d'être totalement indépendant d'un autre sans
#  obliger à tout ressaisir quand on ne veut changer qu'un seuil.
CLES_ROLE = {
    "actif": True,           # ce rôle est-il suivi ? (on peut le suspendre seul)
    "rappel": None,          # jours avant le rappel public
    "retrait": None,         # jours avant le retrait du rôle
    "expulsion": None,       # jours avant la proposition d'expulsion
    #  Exigence de présence PROPRE au rôle : un rôle de clan peut demander d'être
    #  vu 5 jours sur 7 là où le reste du serveur se contente de 2.
    "presence": None,        # jours vus mini sur la fenêtre, sinon rappel doux
    "doux_max": None,        # rappels doux consécutifs tolérés avant le palier 1
    "retirer_role": True,    # retirer effectivement le rôle au palier 2 ?
    #  Comment le rôle revient quand le membre repointe.
    #  True  = rendu automatiquement, dès la première activité.
    #  False = le staff est prévenu et décide. À préférer pour un rôle qui a de
    #          la VALEUR — un rôle de clan ou de faction ne se récupère pas tout
    #          seul, sinon il ne veut plus rien dire.
    "restitution_auto": True,
    "salon_annonce": 0,      # SON salon d'annonce (0 = celui du serveur)
    "salon_retour": 0,       # SON salon de retour   (0 = celui du serveur)
    "jour_rappel": None,     # SON jour de rappel    (None = celui du serveur)
    "derniere_semaine": "",  # marqueur d'envoi PROPRE à ce rôle
    #  Identifiants des messages de rappel de la semaine passée, pour les
    #  supprimer avant d'en poster de nouveaux : un seul rappel vivant à la fois.
    "dernier_message_rappel": [],
}


def ids_roles_surveilles(cfg_act: dict) -> set[int]:
    """Les identifiants NUMÉRIQUES des rôles surveillés, et rien d'autre.

    ⚠️ BUG CORRIGÉ LE 12/08/2026 — ne pas revenir à `{int(r) for r in ...}`.

    `activite_roles` est indexé par identifiant de rôle EN TEXTE, mais il contient
    aussi la clé `"*"` (ROLE_TOUS), le pseudo-rôle « tout le serveur ». Et cette
    clé n'est pas hypothétique : le passage hebdomadaire l'écrit lui-même en
    mémorisant `derniere_semaine` pour ce groupe.

    Résultat mesuré : dès que le propriétaire décochait « Tout le serveur »,
    `int("*")` levait un ValueError pour CHAQUE membre. `classer` attrapait
    l'erreur membre par membre, personne n'était classé, et le panneau continuait
    d'afficher « allumé ». Le système était mort en se disant vivant.
    """
    out: set[int] = set()
    for cle in (cfg_act.get("activite_roles") or {}):
        try:
            out.add(int(cle))
        except (TypeError, ValueError):
            continue          # ROLE_TOUS, ou une clé abîmée : ce n'est pas un rôle
    return out


def config_du_role(cfg_act: dict, role_id) -> dict:
    """Configuration COMPLÈTE d'un rôle surveillé, réglages globaux en repli.

    Chaque rôle a son propre suivi : ses seuils, son salon d'annonce, son salon
    de retour, son jour de rappel, et son propre marqueur de semaine. Deux rôles
    peuvent donc vivre sur des rythmes totalement différents — l'un relancé le
    lundi dans le salon général au bout de 3 jours, l'autre le vendredi dans un
    salon privé au bout de 30.

    Un champ non renseigné retombe sur le réglage du serveur : on ne force pas à
    tout ressaisir pour changer un seul seuil.
    """
    brut = (cfg_act.get("activite_roles") or {}).get(str(role_id)) or {}

    def _n(cle, defaut_global):
        v = brut.get(cle)
        return int(v) if v not in (None, "", 0) else int(defaut_global)

    jour = brut.get("jour_rappel")
    return {
        "actif": bool(brut.get("actif", True)),
        "rappel": _n("rappel", SEUIL_RAPPEL_DEFAUT),
        "retrait": _n("retrait", SEUIL_RETRAIT_DEFAUT),
        "expulsion": _n("expulsion", SEUIL_EXPULSION_DEFAUT),
        "presence": _n("presence", cfg_act.get("activite_seuil_presence")
                       or SEUIL_PRESENCE_DEFAUT),
        "doux_max": _n("doux_max", cfg_act.get("activite_doux_max")
                       or DOUX_MAX_DEFAUT),
        "retirer_role": bool(brut.get("retirer_role", True)),
        "restitution_auto": bool(brut.get("restitution_auto", True)),
        "salon_annonce": int(brut.get("salon_annonce") or
                             cfg_act.get("activite_salon_annonce") or 0),
        "salon_retour": int(brut.get("salon_retour") or
                            cfg_act.get("activite_salon_retour") or 0),
        "jour_rappel": (int(jour) if jour not in (None, "")
                        else int(cfg_act.get("activite_jour_rappel") or 0)),
        "derniere_semaine": str(brut.get("derniere_semaine") or ""),
        "dernier_message_rappel": list(brut.get("dernier_message_rappel") or []),
        #  Vrai si le champ a été réglé sur ce rôle : le panneau affiche alors
        #  « propre au rôle » plutôt que « hérité du serveur ».
        "_propres": {k for k in ("rappel", "retrait", "expulsion", "presence",
                                 "doux_max", "salon_annonce", "salon_retour",
                                 "jour_rappel")
                     if brut.get(k) not in (None, "", 0)},
    }


def seuils_du_role(cfg_act: dict, role_id) -> dict:
    """Alias historique — la configuration complète contient les seuils."""
    return config_du_role(cfg_act, role_id)


async def ecrire_config_role(guild_id: int, role_id, **champs) -> None:
    """Écrit un ou plusieurs champs de la config d'UN rôle, sans toucher aux autres.

    Lecture-modification-écriture sur le dict complet : `db_set` ne sait écrire
    qu'une clé de premier niveau, et deux rôles ne doivent jamais s'écraser.
    """
    try:
        c = await config(guild_id)
        roles = dict(c.get("activite_roles") or {})
        conf = dict(roles.get(str(role_id)) or {})
        conf.update(champs)
        roles[str(role_id)] = conf
        await _db_set(guild_id, "activite_roles", roles)
    except Exception as ex:
        _log(f"[activite ecrire_config_role] {ex}")


async def actif(guild_id: int) -> bool:
    """Le système tourne-t-il vraiment sur cette guilde ?

    Il faut l'interrupteur ET une cible : sans rôle surveillé ni « tout le monde »,
    le système n'a personne à suivre et reste inerte.
    """
    c = await config(guild_id)
    if not c["activite_enabled"]:
        return False
    return bool(c["activite_tout_le_monde"] or c["activite_roles"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Suivi — appelé depuis on_message / on_voice_state_update / on_raw_reaction_add
# ═══════════════════════════════════════════════════════════════════════════════

def _aujourdhui() -> str:
    return cal.jour()


#  ⚠️ CACHE INDISPENSABLE — `marquer_actif` tourne sur CHAQUE message du serveur.
#  Sans lui, un membre bavard déclenche une écriture SQLite par message alors que
#  la ligne du jour existe déjà : des milliers d'écritures pour rien, sur le
#  chemin le plus chaud du bot. Le cache retient (guilde, membre, source) déjà
#  enregistrés aujourd'hui et coupe l'écriture avant même d'ouvrir la base.
#  Il est vidé au changement de jour : sa taille est donc bornée par le nombre de
#  membres actifs dans la journée, pas par le nombre de messages.
_marques_du_jour: set[tuple[int, int, str]] = set()
_jour_du_cache: str = ""


async def marquer_actif(guild_id: int, user_id: int, source: str) -> None:
    """Marque le membre actif pour AUJOURD'HUI.

    Appelé sur chaque message / arrivée en vocal / réaction. Une seule écriture,
    idempotente grâce à la clé primaire. `sources` accumule les lettres pour qu'on
    sache PAR QUOI le membre a été actif — utile pour distinguer un vrai membre
    d'un compte qui ne fait que réagir.
    """
    if source not in SOURCES:
        return
    jour = _aujourdhui()

    global _jour_du_cache
    if jour != _jour_du_cache:
        _marques_du_jour.clear()
        _jour_du_cache = jour
    cle = (guild_id, user_id, source)
    if cle in _marques_du_jour:
        return                      # déjà enregistré aujourd'hui : rien à faire
    _marques_du_jour.add(cle)
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activite_jours(guild_id, user_id, jour, sources)"
                " VALUES(?,?,?,?)"
                " ON CONFLICT(guild_id, user_id, jour) DO UPDATE SET"
                "  sources = CASE WHEN instr(sources, ?) > 0"
                "                 THEN sources ELSE sources || ? END",
                (guild_id, user_id, jour, source, source, source),
            )
            await db.execute(
                "INSERT INTO activite_etat(guild_id, user_id, dernier_actif, palier)"
                " VALUES(?,?,?,0)"
                " ON CONFLICT(guild_id, user_id) DO UPDATE SET dernier_actif=?",
                (guild_id, user_id, jour, jour),
            )
            await db.commit()
    except Exception as ex:
        _log(f"[activite marquer_actif] {ex}")


async def dernier_jour_actif(guild_id: int, user_id: int) -> str | None:
    """Dernier jour où le membre a été actif ('YYYY-MM-DD'), ou None."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT MAX(jour) FROM activite_jours WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row and row[0] else None
    except Exception as ex:
        _log(f"[activite dernier_jour_actif] {ex}")
        return None


def jours_ecoules(depuis: str | None) -> int | None:
    """Nombre de jours entre `depuis` ('YYYY-MM-DD') et aujourd'hui.

    None si la date est inconnue ou illisible : l'appelant décide quoi en faire.
    On ne renvoie JAMAIS 0 par défaut — un « 0 » silencieux ferait passer un
    membre jamais vu pour un membre actif du jour.
    """
    if not depuis:
        return None
    return cal.jours_entre(depuis)


async def jours_inactif(guild_id: int, member) -> int | None:
    """Depuis combien de jours ce membre est-il inactif ?

    None = jamais vu actif depuis l'activation du système. Dans ce cas on compte
    à partir de son ARRIVÉE sur le serveur : un membre entré hier ne doit pas être
    traité comme inactif depuis toujours.
    """
    dernier = await dernier_jour_actif(guild_id, member.id)
    if dernier:
        return jours_ecoules(dernier)
    arrivee = getattr(member, "joined_at", None)
    if arrivee is None:
        return None
    #  Passe par le calendrier pour que l'arrivée soit ramenée au même fuseau
    #  que les journées d'activité : sinon un membre arrivé à 23h30 heure de
    #  Paris compterait un jour d'écart de plus.
    return cal.jours_entre(cal.jour(arrivee))


# ═══════════════════════════════════════════════════════════════════════════════
#  La PRÉSENCE — la mesure qui referme le contournement
# ═══════════════════════════════════════════════════════════════════════════════

def _jour_decale(n: int) -> str:
    """La journée d'il y a `n` jours, au format base. n=0 → aujourd'hui."""
    return (cal.debut_du_jour() - timedelta(days=max(0, int(n)))).strftime(JOUR_FMT)


async def jours_vus(guild_id: int, user_id: int, depuis: str, jusqu: str) -> list[str]:
    """Les journées où ce membre a laissé une trace, bornes incluses.

    Comparaison de chaînes `YYYY-MM-DD` : l'ordre lexicographique de ce format
    est exactement l'ordre chronologique, donc `BETWEEN` fait le bon travail sans
    conversion — et l'index sur (guild_id, jour) est utilisé tel quel.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT jour FROM activite_jours"
                " WHERE guild_id=? AND user_id=? AND jour BETWEEN ? AND ?"
                " ORDER BY jour",
                (guild_id, user_id, depuis, jusqu),
            ) as cur:
                return [r[0] for r in await cur.fetchall()]
    except Exception as ex:
        _log(f"[activite jours_vus] {ex}")
        return []


async def anciennete_du_suivi(guild_id: int) -> int | None:
    """Depuis combien de jours cette guilde enregistre-t-elle quelque chose ?

    Sert de plafond à la fenêtre de présence. Un système allumé avant-hier n'a
    que deux jours d'historique : juger « 1 jour sur 7 » reviendrait à compter
    comme absences cinq journées que le bot n'a jamais observées.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT MIN(jour) FROM activite_jours WHERE guild_id=?", (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return cal.jours_entre(row[0]) if row and row[0] else None
    except Exception as ex:
        _log(f"[activite anciennete_du_suivi] {ex}")
        return None


async def observation_jours(guild_id: int) -> int:
    """Depuis combien de jours a-t-on le DROIT de reprocher une absence ?

    ═══════════════════════════════════════════════════════════════════════════
    LE BUG QUE CETTE FONCTION CORRIGE (production, 12/08/2026)
    ═══════════════════════════════════════════════════════════════════════════
    Le silence d'un membre jamais vu retombe sur sa date d'ARRIVÉE (voir
    `jours_inactif`). Sur un serveur existant, allumer le système donnait donc
    d'un seul coup « 941 actions demandées » : neuf cents membres inscrits
    depuis des mois, jamais observés, tous classés en expulsion le premier soir.
    Le garde-fou a bloqué — mais il ne pouvait plus jamais retomber, puisque ces
    ancienneté-là ne décroissent pas. Interblocage définitif.

    L'ancre referme ça à la racine : on ne peut pas reprocher une journée
    ANTÉRIEURE à l'allumage. Le silence est plafonné par cette valeur, donc il
    est structurellement impossible d'atteindre le seuil d'expulsion avant que
    le système ait réellement observé le serveur pendant autant de jours.

    Écriture PARESSEUSE : si l'ancre manque, on la pose à aujourd'hui et on rend
    0. C'est ce qui débloque un serveur déjà en panne sans que le propriétaire
    ait à éteindre puis rallumer — et sans jamais écraser une ancre existante,
    ce qui ferait d'un OFF/ON un moyen de repousser l'escalade indéfiniment.
    """
    try:
        c = await _cfg(guild_id)
        depuis = str((c or {}).get("activite_observe_depuis") or "")
    except Exception as ex:
        _log(f"[activite observation_jours lecture] {ex}")
        return 0          # dans le doute, on n'a rien observé : on ne juge pas

    if not depuis:
        jour = _aujourdhui()
        try:
            #  ⚠️ ON REGARDE LE RETOUR. `db_set` rend `False` sans lever quand
            #  elle refuse d'écrire (config au-delà de 100 ko, identifiant
            #  invalide, clé suspecte). Le jeter rendait « jamais écrite »
            #  indiscernable de « écrite puis effacée » — et c'est exactement
            #  la question qu'on s'est posée trois jours durant en voyant
            #  `observation=0 j` revenir à chaque démarrage.
            _ok = await _db_set(guild_id, "activite_observe_depuis", jour)
            _log(f"[activite ancre] guilde={guild_id} posée au {jour} "
                 f"(écriture {'OK' if _ok else '❌ REFUSÉE'})")
        except Exception as ex:
            _log(f"[activite observation_jours écriture] {ex}")
        return 0

    n = cal.jours_entre(depuis)
    return max(0, int(n)) if n is not None else 0


async def presence(guild_id: int, member, cfg_act: dict,
                   suivi_jours: int | None = None,
                   observation: int | None = None) -> dict:
    """Les DEUX mesures d'un membre, calculées ensemble.

    ┌ silence ─── jours consécutifs sans le moindre geste, AUJOURD'HUI COMPRIS.
    │             C'est lui qui fait monter les paliers. Il tombe à 0 à la
    │             seconde où le membre reparle, pour que le retour soit immédiat.
    └ presents ── journées vues sur la fenêtre de jours COMPLETS précédant
                  aujourd'hui. C'est elle qui attrape celui qui poste une fois
                  par semaine : son silence reste bas, sa présence reste à 1/7.

    La journée EN COURS est délibérément exclue de `presents` : à 9 h du matin,
    personne n'a encore parlé, et compter cette journée comme manquée ferait
    dépendre le verdict de l'heure du passage.

    `jugeable` est faux quand on n'a pas assez de recul — nouveau membre, ou
    système allumé il y a trois jours. Dans ce cas, AUCUN rappel doux : on ne
    reproche pas une absence sur des journées qu'on n'a pas observées.
    """
    fenetre_voulue = max(1, int(cfg_act.get("activite_fenetre")
                                or FENETRE_PRESENCE_DEFAUT))

    if observation is None:
        observation = await observation_jours(guild_id)

    silence_brut = await jours_inactif(guild_id, member)
    #  ⚠️ LE PLAFONNEMENT — voir `observation_jours`. On garde la valeur brute
    #  pour l'affichage staff (« absent depuis 2 ans, observé depuis 3 jours »
    #  est une information utile), mais on ne JUGE que sur ce qu'on a vu.
    silence = (None if silence_brut is None
               else min(silence_brut, observation))

    #  Combien de journées COMPLÈTES ce membre pouvait-il seulement remplir ?
    #  On prend la plus contraignante : son arrivée, l'âge du suivi, l'ancre.
    bornes = [observation]
    arrivee = getattr(member, "joined_at", None)
    if arrivee is not None:
        depuis_arrivee = cal.jours_entre(cal.jour(arrivee))
        if depuis_arrivee is not None:
            bornes.append(depuis_arrivee)
    if suivi_jours is None:
        suivi_jours = await anciennete_du_suivi(guild_id)
    #  ⚠️ FAIL-OPEN CORRIGÉ : `None` veut dire « le journal est VIDE », pas
    #  « borne inconnue, passe ». L'ignorer faisait juger tout le monde sur des
    #  journées dont on n'a strictement aucune trace.
    bornes.append(suivi_jours if suivi_jours is not None else 0)
    observables = min(bornes) if bornes else 0

    fenetre = max(1, min(fenetre_voulue, observables))
    jugeable = observables >= ANCIENNETE_MINIMALE

    vus = await jours_vus(guild_id, member.id, _jour_decale(fenetre), _jour_decale(1))
    return {
        "silence": silence,
        "silence_brut": silence_brut,
        "presents": len(set(vus)),
        "fenetre": fenetre,
        #  ⚠️ LA FENÊTRE DEMANDÉE, À CÔTÉ DE LA FENÊTRE RÉELLE.
        #  `fenetre` est plafonnée par ce qu'on a pu observer ; `verdict` a
        #  besoin des deux pour mettre le seuil à l'échelle. Sans elle, un
        #  serveur observé depuis 3 jours exige 3 présences sur 3 — la
        #  perfection — pour échapper au palier doux.
        "fenetre_voulue": fenetre_voulue,
        "jugeable": jugeable,
        "observables": observables,
        "observation": observation,
        "jours_vus": sorted(set(vus)),
    }


def presence_exigee(mesure: dict, conf: dict) -> int:
    """Combien de journées le membre doit avoir montrées, SUR LA FENÊTRE RÉELLE.

    ⚠️ UNE SEULE SOURCE POUR CE CHIFFRE — et c'est la raison d'être de cette
    fonction. `verdict` s'en sert pour trancher, le message d'avertissement
    pour l'annoncer. La première version calculait la mise à l'échelle dans
    `verdict` seulement : le message affichait alors « au moins 3 jours sur 3 »
    pendant que le code n'en exigeait qu'un. Un message qui annonce une règle
    que le code n'applique pas est pire que pas de message du tout.

    ⚠️ POURQUOI UNE MISE À L'ÉCHELLE. `fenetre` est plafonnée par l'ancienneté
    du suivi (voir `presence`). Comparer une présence mesurée sur 3 jours à un
    seuil pensé pour 7 exige une présence PARFAITE : sur le serveur du
    propriétaire, observé depuis trois jours, il fallait être venu 3 jours sur
    3 pour échapper au palier doux. Un membre venu deux jours sur trois — très
    présent — était donc étiqueté « peu actif ». Étiqueter des gens actifs
    discrédite le système entier dès le premier ping.

    Plancher à 1 : tant qu'on n'observe qu'un jour, être venu ce jour-là suffit.
    """
    fenetre = mesure.get("fenetre", 1) or 1
    voulue = mesure.get("fenetre_voulue") or fenetre
    return max(1, round(conf["presence"] * fenetre / max(1, voulue)))


def verdict(mesure: dict, conf: dict, doux_deja: int = 0) -> str:
    """Le palier d'un membre, à partir de ses deux mesures. FONCTION PURE.

    Pure exprès : c'est LA règle du système, et une règle qui ne se teste
    qu'avec un vrai serveur Discord derrière n'est jamais testée. Elle se vérifie
    ici avec des dictionnaires, en une milliseconde, sur tous les cas limites.

    Renvoie l'un de : "expulsion", "retrait", "rappel", "doux", "actif".
    L'ordre du plus grave au moins grave n'est pas cosmétique : un membre ne doit
    apparaître QUE dans une liste, sinon il reçoit deux messages contradictoires.
    """
    silence = mesure.get("silence")
    if silence is None:
        return "actif"          # rien de connu : on ne devine pas, on n'agit pas

    if silence >= conf["expulsion"]:
        return "expulsion"
    if silence >= conf["retrait"]:
        return "retrait"
    if silence >= conf["rappel"]:
        return "rappel"

    #  Le membre a donné signe récemment. Reste à savoir s'il l'a fait ASSEZ.
    if not mesure.get("jugeable"):
        return "actif"          # trop récent pour qu'on lui reproche quoi que ce soit

    exige = presence_exigee(mesure, conf)
    if mesure.get("presents", 0) >= exige:
        return "actif"

    #  Présence trop faible. Un rappel doux, sauf s'il en a déjà collectionné :
    #  poster une fois par semaine ne doit pas être une stratégie viable.
    if doux_deja + 1 >= conf["doux_max"]:
        return "rappel"
    return "doux"


# ═══════════════════════════════════════════════════════════════════════════════
#  Qui est concerné
# ═══════════════════════════════════════════════════════════════════════════════

async def roles_surveilles(guild, cfg_act: dict) -> list:
    """Objets rôle réellement surveillés (les ids morts sont ignorés)."""
    out = []
    for rid in (cfg_act.get("activite_roles") or {}):
        try:
            r = guild.get_role(int(rid))
        except Exception:
            r = None
        if r is not None:
            out.append(r)
    return out


async def membre_concerne(member, cfg_act: dict) -> bool:
    """Ce membre entre-t-il dans le périmètre du suivi ?

    Ordre volontaire : on écarte D'ABORD les intouchables. Un administrateur ne
    doit jamais figurer dans une liste d'inactifs, même pour information.
    """
    if member.bot:
        return False
    try:
        if member.guild.owner_id == member.id:
            return False
        if getattr(member.guild_permissions, "administrator", False):
            return False
        if _est_immunise is not None and await _est_immunise(member):
            return False
    except Exception as ex:
        #  Fail-CLOSED sur la protection : si on n'arrive pas à établir qu'un
        #  membre est touchable, on le laisse tranquille.
        _log(f"[activite membre_concerne] {ex}")
        return False

    #  Immunité propre à l'activité, définie par le propriétaire. Vérifiée AVANT
    #  toute inclusion : un membre dispensé ne doit apparaître dans aucune liste,
    #  même pour information.
    if est_dispense(member, cfg_act):
        return False

    if cfg_act.get("activite_tout_le_monde"):
        return True
    ids = ids_roles_surveilles(cfg_act)
    return any(r.id in ids for r in member.roles)


def est_dispense(member, cfg_act: dict) -> bool:
    """Ce membre est-il dispensé d'activité par un réglage du propriétaire ?

    Distinct de l'immunité de modération : on peut vouloir qu'un ancien membre
    reste sur le serveur sans rien faire, tout en le laissant soumis aux filtres
    anti-spam. Les deux listes sont donc séparées, et celle-ci n'a d'effet QUE
    sur le système d'activité.
    """
    try:
        membres = {int(x) for x in (cfg_act.get("activite_membres_immunises") or [])}
        if member.id in membres:
            return True
        roles = {int(x) for x in (cfg_act.get("activite_roles_immunises") or [])}
        return any(r.id in roles for r in member.roles)
    except Exception:
        #  Fail-CLOSED comme le reste : si la liste est illisible, on dispense
        #  plutôt que de risquer d'expulser quelqu'un qui devait être épargné.
        return True


def role_surveille_du_membre(member, cfg_act: dict):
    """Le premier rôle surveillé que porte ce membre, sinon None.

    C'est lui qui donne les seuils : un membre peut cumuler plusieurs rôles
    surveillés, on applique alors le plus EXIGEANT (seuils les plus courts).
    """
    ids = ids_roles_surveilles(cfg_act)
    portes = [r for r in member.roles if r.id in ids]
    if not portes:
        return None
    return min(portes, key=lambda r: seuils_du_role(cfg_act, r.id)["expulsion"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Diagnostic — la preuve que le suivi fonctionne vraiment
# ═══════════════════════════════════════════════════════════════════════════════

async def diagnostic(guild_id: int, jours: int = 7) -> dict:
    """Ce que le suivi a RÉELLEMENT enregistré ces derniers jours.

    Sert à répondre à la seule question qui compte avant d'allumer les paliers :
    « est-ce que ça capte vraiment mes messages, mon vocal et mes réactions ? »
    Un système de présence qui se trompe expulse des innocents ; on ne l'allume
    pas sur la foi d'une intention, on l'allume sur des chiffres.

    Retourne, par source, le nombre de membres distincts captés, plus le détail
    des derniers jours.
    """
    out = {"par_source": {k: 0 for k in SOURCES}, "jours": [],
           "total_membres": 0, "premier_jour": None}
    try:
        depuis = cal.debut_du_jour() - timedelta(days=max(1, int(jours)))
        borne = depuis.strftime(JOUR_FMT)
        async with _get_db() as db:
            async with db.execute(
                "SELECT jour, COUNT(DISTINCT user_id), group_concat(sources, '')"
                " FROM activite_jours WHERE guild_id=? AND jour>=?"
                " GROUP BY jour ORDER BY jour DESC",
                (guild_id, borne),
            ) as cur:
                rows = await cur.fetchall()
            for j, n, src in rows:
                src = src or ""
                out["jours"].append({
                    "jour": j, "membres": int(n),
                    "sources": {k: src.count(k) for k in SOURCES},
                })
                for k in SOURCES:
                    out["par_source"][k] += src.count(k)

            async with db.execute(
                "SELECT COUNT(DISTINCT user_id), MIN(jour) FROM activite_jours"
                " WHERE guild_id=?", (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            if row:
                out["total_membres"] = int(row[0] or 0)
                out["premier_jour"] = row[1]
    except Exception as ex:
        _log(f"[activite diagnostic] {ex}")
    return out


def diagnostic_texte(d: dict) -> str:
    """Le diagnostic, lisible. Dit franchement ce qui ne capte pas."""
    lignes = [cal.description(), ""]

    muettes = [nom for k, nom in SOURCES.items() if d["par_source"].get(k, 0) == 0]
    for k, nom in SOURCES.items():
        n = d["par_source"].get(k, 0)
        icone = "✅" if n else "⚠️"
        lignes.append(f"{icone} **{nom.capitalize()}** · `{n}` enregistrement(s)")

    if d["premier_jour"]:
        recul = cal.jours_entre(d["premier_jour"])
        lignes.append("")
        lignes.append(f"📈 `{d['total_membres']}` membre(s) connu(s) · "
                      f"suivi depuis `{recul}` jour(s)")
        if recul is not None and recul < SEUIL_RAPPEL_DEFAUT:
            lignes.append(f"-# ⚠️ Le suivi n'a que `{recul}` jour(s) d'historique. "
                          f"Tout le monde paraît inactif avant d'avoir eu le temps "
                          f"d'être vu — n'allumez pas les paliers maintenant.")
    else:
        lignes.append("")
        lignes.append("⚠️ **Aucune activité enregistrée.** Le système est peut-être "
                      "éteint, ou vient d'être installé.")

    if muettes and d["premier_jour"]:
        lignes.append(f"-# Aucune trace pour : {', '.join(muettes)}. "
                      f"Testez-les vous-même, puis rouvrez cet écran.")
    return "\n".join(lignes)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le compteur de rappels doux — la mémoire qui referme le contournement
# ═══════════════════════════════════════════════════════════════════════════════

async def lire_etat(guild_id: int, user_id: int) -> dict:
    """Tout ce que `classer` doit savoir sur un membre, en UNE requête.

    ⚠️ `roles_retires` est lu ICI et pas ailleurs, exprès. Le classement tourne
    sur chaque membre de la guilde : une seconde requête par membre doublerait le
    coût du passage. Comme on interrogeait déjà `activite_etat` pour le compteur
    de rappels doux, on rapporte les trois informations d'un coup.

    `a_des_roles_retires` est ce qui permet de RENDRE ses rôles à quelqu'un qui
    ne porte plus d'étiquette AFK — voir le bug corrigé dans `classer`.
    """
    vide = {"doux": 0, "semaine": "", "a_des_roles_retires": False}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT doux, derniere_semaine_doux, roles_retires FROM activite_etat"
                " WHERE guild_id=? AND user_id=?", (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return vide
        gardes = False
        try:
            gardes = bool(json.loads(row[2] or "[]"))
        except Exception:
            gardes = False
        return {"doux": int(row[0] or 0), "semaine": str(row[1] or ""),
                "a_des_roles_retires": gardes}
    except Exception as ex:
        _log(f"[activite lire_etat] {ex}")
        return vide


async def lire_doux(guild_id: int, user_id: int) -> tuple[int, str]:
    """(nombre de rappels doux consécutifs, dernière semaine comptée)."""
    e = await lire_etat(guild_id, user_id)
    return (e["doux"], e["semaine"])


async def noter_doux(guild_id: int, user_id: int, semaine: str) -> int:
    """Compte un rappel doux de plus, UNE SEULE FOIS par semaine.

    Le garde-semaine n'est pas un détail : le passage tourne plusieurs fois par
    jour. Sans lui, un membre atteindrait `doux_max` en une journée et se
    retrouverait au palier 1 pour une seule semaine un peu creuse.
    """
    try:
        n, derniere = await lire_doux(guild_id, user_id)
        if derniere == semaine:
            return n            # déjà compté cette semaine
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activite_etat(guild_id, user_id, doux,"
                " derniere_semaine_doux) VALUES(?,?,?,?)"
                " ON CONFLICT(guild_id, user_id) DO UPDATE SET"
                "  doux=?, derniere_semaine_doux=?",
                (guild_id, user_id, n + 1, semaine, n + 1, semaine),
            )
            await db.commit()
        return n + 1
    except Exception as ex:
        _log(f"[activite noter_doux] {ex}")
        return 0


async def remettre_doux(guild_id: int, user_id: int) -> None:
    """Efface le compteur : le membre a repris une présence normale.

    Appelé quand la présence repasse au-dessus du seuil, PAS à la première
    activité — sinon un message suffirait à effacer trois semaines de contournement,
    et le compteur ne servirait plus à rien.
    """
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE activite_etat SET doux=0, derniere_semaine_doux=NULL"
                " WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await db.commit()
    except Exception as ex:
        _log(f"[activite remettre_doux] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Mémoire des départs pour inactivité
# ═══════════════════════════════════════════════════════════════════════════════

async def noter_expulsion(guild_id: int, user_id: int, silence: int) -> None:
    """Retient qu'un membre est parti pour inactivité.

    Sans cette trace, quelqu'un qui revient six mois plus tard redécouvre la
    règle au moment où elle le frappe une deuxième fois. Avec elle, on peut
    l'accueillir en lui rappelant calmement ce qui s'est passé.
    """
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activite_expulses(guild_id, user_id, jour, silence,"
                " prevenu) VALUES(?,?,?,?,0)"
                " ON CONFLICT(guild_id, user_id) DO UPDATE SET"
                "  jour=?, silence=?, prevenu=0",
                (guild_id, user_id, _aujourdhui(), int(silence),
                 _aujourdhui(), int(silence)),
            )
            await db.commit()
    except Exception as ex:
        _log(f"[activite noter_expulsion] {ex}")


async def etait_expulse(guild_id: int, user_id: int) -> dict | None:
    """Ce membre est-il déjà parti pour inactivité ? None sinon."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT jour, silence, prevenu FROM activite_expulses"
                " WHERE guild_id=? AND user_id=?", (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {"jour": row[0], "silence": int(row[1] or 0),
                "prevenu": bool(row[2])}
    except Exception as ex:
        _log(f"[activite etait_expulse] {ex}")
        return None


async def marquer_prevenu(guild_id: int, user_id: int) -> None:
    """Le message d'accueil est parti : ne pas le renvoyer au prochain passage."""
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE activite_expulses SET prevenu=1"
                " WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await db.commit()
    except Exception as ex:
        _log(f"[activite marquer_prevenu] {ex}")


def duree_lisible(jours: int) -> str:
    """Une durée d'absence telle qu'un humain la ressent.

    « 3 semaines » se ressent ; « 21 jours » se lit sans rien évoquer. C'est le
    genre de détail qui décide si quelqu'un se dit « ah oui, quand même » ou
    survole la ligne.
    Pure et sans dépendance : testable sans Discord.
    """
    j = max(0, int(jours))
    if j >= 14:
        return f"{j // 7} semaines"
    if j >= 7:
        return "1 semaine"
    return f"{j} jour" + ("s" if j > 1 else "")


#  Plafond d'affichage du rappel : au-delà, la liste devient illisible et le
#  message frôle la limite de taille de Discord.
MAX_AFFICHES = 30
