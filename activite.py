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

L'ESCALADE, par rôle surveillé, avec des seuils propres à chaque rôle :
  · palier 1 (défaut 7 j)  → rappel public hebdomadaire, le membre garde tout
  · palier 2 (défaut 14 j) → 2e rappel + RETRAIT DU RÔLE ; pour le récupérer, le
                             membre doit écrire dans le salon de retour
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
SEUIL_RAPPEL_DEFAUT = 7
SEUIL_RETRAIT_DEFAUT = 14
SEUIL_EXPULSION_DEFAUT = 21

#  Garde-fou : un passage ne peut jamais toucher plus de membres que ça. Si le
#  compte dépasse, on n'agit sur PERSONNE et on alerte le staff — c'est le signe
#  d'un bug de suivi (base vidée, horloge décalée), pas d'un serveur qui dort.
PLAFOND_ACTIONS_PAR_PASSAGE = 25

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
    "activite_jour_rappel": 0,          # 0 = lundi … 6 = dimanche
    "activite_derniere_semaine": "",    # semaine ISO du dernier rappel envoyé
    #  Immunité PROPRE au système d'activité : dispenser quelqu'un de présence
    #  n'a rien à voir avec le dispenser de modération. Un ami du serveur, un
    #  ancien, un bot partenaire n'ont pas à être surveillés — sans pour autant
    #  devenir intouchables face aux insultes ou au spam.
    "activite_roles_immunises": [],     # rôles dispensés d'activité
    "activite_membres_immunises": [],   # membres dispensés, un par un
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
    "retirer_role": True,    # retirer effectivement le rôle au palier 2 ?
    "salon_annonce": 0,      # SON salon d'annonce (0 = celui du serveur)
    "salon_retour": 0,       # SON salon de retour   (0 = celui du serveur)
    "jour_rappel": None,     # SON jour de rappel    (None = celui du serveur)
    "derniere_semaine": "",  # marqueur d'envoi PROPRE à ce rôle
}


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
        "retirer_role": bool(brut.get("retirer_role", True)),
        "salon_annonce": int(brut.get("salon_annonce") or
                             cfg_act.get("activite_salon_annonce") or 0),
        "salon_retour": int(brut.get("salon_retour") or
                            cfg_act.get("activite_salon_retour") or 0),
        "jour_rappel": (int(jour) if jour not in (None, "")
                        else int(cfg_act.get("activite_jour_rappel") or 0)),
        "derniere_semaine": str(brut.get("derniere_semaine") or ""),
        #  Vrai si le champ a été réglé sur ce rôle : le panneau affiche alors
        #  « propre au rôle » plutôt que « hérité du serveur ».
        "_propres": {k for k in ("rappel", "retrait", "expulsion",
                                 "salon_annonce", "salon_retour", "jour_rappel")
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
    ids = {int(r) for r in (cfg_act.get("activite_roles") or {})}
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
    ids = {int(r) for r in (cfg_act.get("activite_roles") or {})}
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
