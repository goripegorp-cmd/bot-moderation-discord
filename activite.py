"""activite.py — Le COMPTAGE des jours d'activité, pour /rellseas. Rien d'autre.

⚠️ LE SYSTÈME D'ACTIVITÉ EST RETIRÉ (03/10/2026) — demande du propriétaire :
    « Le système d'activité, quand les gens sont AFK, quand ils ne parlent pas
      et tout, enlève-moi complètement ce système et ce calcul inutile. »
Plus de paliers, de rôles AFK, de masquage des salons, de retrait des rôles, de
rappels, de porte de retour ni de récompenses : `activite_demontage.py` a défait
sur Discord ce que le système y avait posé.

CE QUI RESTE, ET POURQUOI — choix du propriétaire le 03/10 (« Garder pour
/rellseas ») : le bouton « Activité » de /rellseas montre, sur 7 jours, les
journées où un membre a posé un geste volontaire. Il lui faut deux choses :
  · `marquer_actif` — une ligne par membre et par jour (cache du jour : un
    message de plus ne coûte qu'une lecture de `set`) ;
  · `presence` — la mesure, en lecture seule. Personne n'est prévenu, rien
    n'est appliqué à personne.

⚠️ LE STATUT « EN LIGNE » N'EST PAS UNE SOURCE, et ne le sera pas. Être connecté
ne prouve rien : seuls comptent un message, la parole en vocal, une réaction,
une commande ou un bouton, un fil ouvert, un vote à un sondage.
"""
from __future__ import annotations

from datetime import timedelta

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
#  ligne » sans qu'aucun humain soit là. Chaque source ci-dessous demande un
#  GESTE VOLONTAIRE.
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

#  La fenêtre de présence : sur combien de jours COMPLETS on regarde si le membre
#  s'est montré. Sept jours = une semaine pleine, quel que soit le jour du rappel.
#  Volontairement GLISSANTE et non calée sur le lundi : une fenêtre calée serait
#  contournable en postant toujours le même jour de la semaine.
FENETRE_PRESENCE_DEFAUT = 7

#  Sous cette ancienneté (en jours complets observables), on ne juge PERSONNE sur
#  sa présence. Un membre arrivé avant-hier n'a pas de semaine à montrer.
ANCIENNETE_MINIMALE = 3

#  ⚠️ CACHE INDISPENSABLE — `marquer_actif` tourne sur CHAQUE message du serveur.
#  Sans lui, un membre bavard déclenche une écriture SQLite par message alors que
#  la ligne du jour existe déjà : des milliers d'écritures pour rien, sur le
#  chemin le plus chaud du bot. Le cache retient (guilde, membre, source) déjà
#  enregistrés aujourd'hui et coupe l'écriture avant même d'ouvrir la base.
#  Il est vidé au changement de jour : sa taille est donc bornée par le nombre de
#  membres actifs dans la journée, pas par le nombre de messages.
_marques_du_jour: set[tuple[int, int, str]] = set()
_jour_du_cache: str = ""

_get_db = None
_cfg = None
_db_set = None
_log = print


def setup(*, get_db, cfg, db_set, log=None):
    """Branche le module sur les fonctions de bot.py."""
    global _get_db, _cfg, _db_set, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    if log is not None:
        _log = log


async def init_db():
    """Crée les tables. Idempotent.

    `activite_etat` reste : `marquer_actif` y note le dernier jour actif, et
    `activite_demontage` y lit les rôles à rendre aux membres que l'ancien
    système avait dépouillés."""
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
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_activite_jours_guild_jour"
            " ON activite_jours(guild_id, jour)"
        )
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


async def config(guild_id: int) -> dict:
    """La configuration du serveur, avec la fenêtre de présence par défaut."""
    try:
        c = dict(await _cfg(guild_id) or {})
    except Exception as ex:
        _log(f"[activite config] {ex}")
        c = {}
    c.setdefault("activite_fenetre", FENETRE_PRESENCE_DEFAUT)
    return c


def _aujourdhui() -> str:
    return cal.jour()


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

