"""activite.py — Système d'activité : suivi, escalade, récompenses.

DÉSACTIVÉ PAR DÉFAUT. Rien ne tourne tant que le propriétaire n'a pas activé le
système ET désigné au moins un rôle surveillé (ou « tout le monde »).

═══════════════════════════════════════════════════════════════════════════════
LE PRINCIPE
═══════════════════════════════════════════════════════════════════════════════
Un membre est ACTIF sur une journée s'il fait AU MOINS UNE des trois choses :
  · envoyer un message      (source « m »)
  · se connecter en vocal   (source « v »)
  · réagir à un message     (source « r »)
Une seule suffit. La journée est comptée en UTC, bornée par `JOUR_FMT`.

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

JOUR_FMT = "%Y-%m-%d"

#  Les trois sources d'activité. La valeur est la lettre stockée en base.
SOURCE_MESSAGE = "m"
SOURCE_VOCAL = "v"
SOURCE_REACTION = "r"
SOURCES = {
    SOURCE_MESSAGE: "message",
    SOURCE_VOCAL: "vocal",
    SOURCE_REACTION: "réaction",
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
    "activite_tout_le_monde": False,    # surveiller tout le serveur, sans rôle
    "activite_roles": {},               # {role_id(str): {rappel, retrait, expulsion}}
    "activite_salon_annonce": 0,        # où poster le rappel hebdomadaire
    "activite_salon_retour": 0,         # où un membre écrit pour récupérer son rôle
    "activite_salon_staff": 0,          # où poster la liste des expulsables
    "activite_jour_rappel": 0,          # 0 = lundi … 6 = dimanche
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


def seuils_du_role(cfg_act: dict, role_id: int) -> dict:
    """Seuils d'un rôle surveillé, complétés par les défauts."""
    brut = (cfg_act.get("activite_roles") or {}).get(str(role_id)) or {}
    return {
        "rappel": int(brut.get("rappel", SEUIL_RAPPEL_DEFAUT) or SEUIL_RAPPEL_DEFAUT),
        "retrait": int(brut.get("retrait", SEUIL_RETRAIT_DEFAUT) or SEUIL_RETRAIT_DEFAUT),
        "expulsion": int(brut.get("expulsion", SEUIL_EXPULSION_DEFAUT) or SEUIL_EXPULSION_DEFAUT),
        "retirer_role": bool(brut.get("retirer_role", True)),
    }


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
    return datetime.now(timezone.utc).strftime(JOUR_FMT)


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
    try:
        d = datetime.strptime(depuis, JOUR_FMT).replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return max(0, (datetime.now(timezone.utc).date() - d.date()).days)


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
    return max(0, (datetime.now(timezone.utc).date() - arrivee.date()).days)


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

    if cfg_act.get("activite_tout_le_monde"):
        return True
    ids = {int(r) for r in (cfg_act.get("activite_roles") or {})}
    return any(r.id in ids for r in member.roles)


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
