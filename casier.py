"""casier.py — effacer au propre : amnistie, casier d'une personne, casier du serveur (19/10/2026).

« Si quelqu'un n'a pas commis d'infraction depuis plus de 3 mois non-stop, tu enlèves toutes les
infractions de la personne, même les sanctions… sauf s'il a vraiment été très agressif. Tu enlèves
les avertissements des joueurs partis depuis plus de 3 mois… Que quand on enlève les infractions,
ça s'enlève bien aussi sur le serveur Discord. » — « Qu'on puisse enlever tous les avertissements de
quelqu'un d'un seul coup, et nettoyer tous les avertissements du serveur d'un seul coup aussi…
repartir de zéro. Si on a besoin de nettoyer une zone. »

Tout ce qui sort du casier passe d'abord par `infractions_archive`, gardée 30 jours : un nettoyage
se défait d'un clic pendant 30 jours — une erreur, ou un compte volé, ne détruit rien pour de bon.
Les effets sur Discord (rôle de récidive, compteurs du filtre, mute en cours) sont appliqués par
bot.py, qui reçoit la liste des personnes touchées.
"""
from __future__ import annotations

import re
import secrets
import time
from datetime import datetime, timezone

DELAI_JOURS = 90
GARDE_JOURS = 30
BANS = ("ban", "tempban", "softban")
#  « Très agressif » : jamais d'amnistie. Un bannissement, une menace, de la haine, du harcèlement…
GRAVES = frozenset(BANS + ("grooming", "menace", "discrimination", "haine", "harcelement", "incitation"))
MOTS_GRAVES = re.compile(r"menace|racis|nsfw|porn|doxx|phishing|arnaque|scam|\braid|p[ée]do|haine|harc[eè]le", re.I)
INSULTES_MAX = 3
PORTEES = {"warns": "Avertissements", "auto": "Détections automatiques", "tout": "Tout le casier (sauf bannissements)"}
AGES = (0, 30, 90)
LOTS_MAX = 200   # les nettoyages des 30 derniers jours montrés sur le site (rangés par sorte : jamais un long pavé)
PURGES = [("archive du casier", "DELETE FROM infractions_archive WHERE archive_le < ?", GARDE_JOURS, "unix"),
          ("nettoyages du casier", "DELETE FROM casier_lots WHERE quand < ?", GARDE_JOURS, "unix")]
_COLS = "id, guild_id, user_id, mod_id, type, reason, duration, created_at"
_get_db = None
_log = print


def setup(*, get_db, log=None):
    global _get_db, _log
    _get_db, _log = get_db, log or print


async def init_db():
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS infractions_archive (id INTEGER, guild_id INTEGER, user_id INTEGER,"
                         " mod_id INTEGER, type TEXT, reason TEXT, duration TEXT, created_at DATETIME, lot TEXT,"
                         " archive_le INTEGER)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_archive_lot ON infractions_archive(guild_id, lot)")
        await db.execute("CREATE TABLE IF NOT EXISTS casier_lots (lot TEXT PRIMARY KEY, guild_id INTEGER, quand INTEGER,"
                         " par INTEGER, quoi TEXT, n INTEGER, personnes INTEGER, restaure_le INTEGER DEFAULT 0,"
                         " restaure_par INTEGER DEFAULT 0)")
        #  Les entrées d'une amnistie défaite : plus jamais amnistiées (un nettoyage à la main, oui).
        await db.execute("CREATE TABLE IF NOT EXISTS casier_exemptions (guild_id INTEGER, infraction_id INTEGER,"
                         " lot TEXT, quand INTEGER, par INTEGER, PRIMARY KEY (guild_id, infraction_id))")
        await db.commit()


# ─── Règles ─────────────────────────────────────────────────────────────────

def tres_agressif(lignes) -> str:
    """La raison pour laquelle ce casier n'est jamais amnistié, ou "". `lignes` : (type, motif)."""
    types = [str(t or "").lower() for t, _ in lignes]
    grave = next((t for t in types if t in GRAVES), None)
    if grave:
        return f"{grave} au casier"
    if any(MOTS_GRAVES.search(str(r or "")) for _, r in lignes):
        return "fait grave au casier"
    if types.count("insulte") >= INSULTES_MAX:
        return "insultes répétées"
    return ""


def filtre(portee: str, jours: int, bot_id: int) -> tuple[str, tuple]:
    """Ce qu'une « zone » du casier désigne. Les bannissements ne partent jamais en masse."""
    if portee == "warns":
        sql, args = "type='warn'", ()
    elif portee == "auto":
        sql, args = f"mod_id=? AND type NOT IN {BANS}", (int(bot_id),)
    elif portee == "tout":
        sql, args = f"type NOT IN {BANS}", ()
    else:
        raise ValueError(portee)
    if jours:
        sql += " AND created_at < datetime('now', ?)"
        args += (f"-{int(jours)} days",)
    return sql, args


def _lot(prefixe: str) -> str:
    return f"{prefixe}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"


async def _sortir(db, guild_id: int, sql: str, args: tuple, lot: str) -> dict:
    """Archive puis retire du casier. Rend {membre: nombre d'entrées retirées}."""
    where = f"guild_id=? AND ({sql})"
    compter = f"SELECT user_id, COUNT(*) FROM infractions WHERE {where} GROUP BY user_id"
    archiver = f"INSERT INTO infractions_archive ({_COLS}, lot, archive_le) SELECT {_COLS}, ?, ? FROM infractions WHERE {where}"
    retirer = f"DELETE FROM infractions WHERE {where}"
    async with db.execute(compter, (guild_id, *args)) as cur:
        touches = {int(u): int(n) for u, n in await cur.fetchall()}
    if touches:
        await db.execute(archiver, (lot, int(time.time()), guild_id, *args))
        await db.execute(retirer, (guild_id, *args))
    return touches


async def _noter_lot(db, guild_id, lot, par, quoi, touches):
    await db.execute("INSERT INTO casier_lots (lot, guild_id, quand, par, quoi, n, personnes) VALUES (?,?,?,?,?,?,?)",
                     (lot, guild_id, int(time.time()), int(par or 0), quoi[:120], sum(touches.values()), len(touches)))


# ─── Compter, effacer, défaire ──────────────────────────────────────────────

async def comptes(guild_id: int, bot_id: int) -> dict:
    """Pour le site : combien d'entrées chaque zone effacerait, selon l'âge."""
    out = {}
    async with _get_db() as db:
        for portee in PORTEES:
            out[portee] = {}
            for jours in AGES:
                sql, args = filtre(portee, jours, bot_id)
                requete = f"SELECT COUNT(*) FROM infractions WHERE guild_id=? AND ({sql})"
                async with db.execute(requete, (guild_id, *args)) as cur:
                    out[portee][str(jours)] = int((await cur.fetchone())[0])
    return out


async def nettoyer(guild_id: int, portee: str, jours: int, par: int, bot_id: int) -> dict:
    sql, args = filtre(portee, jours, bot_id)
    lot = _lot("zone")
    quoi = PORTEES[portee] + (f", plus de {jours} jours" if jours else "")
    async with _get_db() as db:
        touches = await _sortir(db, guild_id, sql, args, lot)
        if touches:
            await _noter_lot(db, guild_id, lot, par, quoi, touches)
        await db.commit()
    return {"lot": lot, "n": sum(touches.values()), "membres": sorted(touches), "quoi": quoi}


async def effacer_membre(guild_id: int, user_id: int, quoi: str, par: int) -> dict:
    """« Tous les avertissements de quelqu'un d'un seul coup » (`warns`) ou tout son casier (`tout`)."""
    if quoi not in ("warns", "tout"):
        raise ValueError(quoi)
    sql = "user_id=? AND type='warn'" if quoi == "warns" else "user_id=?"
    lot = _lot("membre")
    async with _get_db() as db:
        touches = await _sortir(db, guild_id, sql, (int(user_id),), lot)
        if touches:
            await _noter_lot(db, guild_id, lot, par, ("Avertissements" if quoi == "warns" else "Casier entier")
                             + f" de {int(user_id)}", touches)
        await db.commit()
    return {"lot": lot, "n": sum(touches.values()), "membres": sorted(touches)}


async def restaurer(guild_id: int, lot: str, par: int) -> dict:
    """Un nettoyage défait : chaque entrée revient au casier avec son identifiant d'origine.

    24/10/2026 (revue) : une amnistie défaite ne tenait pas 24 h — les entrées remises gardent leur
    date, et l'amnistie du lendemain les effaçait de nouveau. Défaire une amnistie les en exempte."""
    async with _get_db() as db:
        async with db.execute("SELECT restaure_le FROM casier_lots WHERE guild_id=? AND lot=?", (guild_id, lot)) as cur:
            r = await cur.fetchone()
        if r is None or r[0]:
            return {"n": 0, "membres": []}
        async with db.execute("SELECT DISTINCT user_id FROM infractions_archive WHERE guild_id=? AND lot=?",
                              (guild_id, lot)) as cur:
            membres = sorted(int(x[0]) for x in await cur.fetchall())
        remettre = f"INSERT OR IGNORE INTO infractions ({_COLS}) SELECT {_COLS} FROM infractions_archive WHERE guild_id=? AND lot=?"
        cur = await db.execute(remettre, (guild_id, lot))
        n = cur.rowcount or 0
        if lot.startswith("amnistie-"):
            await db.execute("INSERT OR IGNORE INTO casier_exemptions (guild_id, infraction_id, lot, quand, par)"
                             " SELECT guild_id, id, ?, ?, ? FROM infractions_archive WHERE guild_id=? AND lot=?",
                             (lot, int(time.time()), int(par or 0), guild_id, lot))
        await db.execute("DELETE FROM infractions_archive WHERE guild_id=? AND lot=?", (guild_id, lot))
        await db.execute("UPDATE casier_lots SET restaure_le=?, restaure_par=? WHERE guild_id=? AND lot=?",
                         (int(time.time()), int(par or 0), guild_id, lot))
        await db.commit()
    return {"n": int(n), "membres": membres}


async def lots(guild_id: int) -> list[dict]:
    async with _get_db() as db:
        async with db.execute("SELECT lot, quand, par, quoi, n, personnes, restaure_le, restaure_par FROM casier_lots"
                              " WHERE guild_id=? AND quand>=? ORDER BY quand DESC, rowid DESC LIMIT ?",
                              (guild_id, int(time.time()) - GARDE_JOURS * 86400, LOTS_MAX)) as cur:
            return [{"lot": l, "quand": q, "par": p, "quoi": quoi, "n": n, "personnes": pers, "restaure_le": rl or None,
                     "restaure_par": rp} for l, q, p, quoi, n, pers, rl, rp in await cur.fetchall()]


# ─── L'amnistie ─────────────────────────────────────────────────────────────

async def amnistie(guild_id: int, presents: set, partis: dict, maintenant: float | None = None) -> dict:
    """· 3 mois sans infraction et jamais très agressif : tout le casier s'efface.
    · Parti depuis 3 mois (date de départ connue, sinon dernière entrée de plus de 3 mois) : ses
      avertissements et sanctions légères s'effacent ; les bannissements et faits graves restent.
    `partis` : {membre: horodatage du départ ou None} pour les absents. Rend le bilan.
    Les entrées d'une amnistie défaite (`casier_exemptions`) restent, toujours."""
    t = maintenant or time.time()
    borne = t - DELAI_JOURS * 86400
    lot = _lot("amnistie")
    effaces, gardes = {}, []
    hors_exemptees = "id NOT IN (SELECT infraction_id FROM casier_exemptions WHERE guild_id=?)"
    async with _get_db() as db:
        async with db.execute("SELECT user_id, MAX(created_at) FROM infractions WHERE guild_id=? GROUP BY user_id",
                              (guild_id,)) as cur:
            derniers = [(int(u), _unix(d)) for u, d in await cur.fetchall()]
        for uid, dernier in derniers:
            parti = uid not in presents
            depart = partis.get(uid) if parti else None
            parti_longtemps = parti and ((depart or dernier) <= borne)
            if dernier > borne and not parti_longtemps:
                continue
            async with db.execute("SELECT type, reason FROM infractions WHERE guild_id=? AND user_id=?",
                                  (guild_id, uid)) as cur:
                lignes = await cur.fetchall()
            raison = tres_agressif(lignes)
            if dernier <= borne and not raison:
                touches = await _sortir(db, guild_id, f"user_id=? AND {hors_exemptees}", (uid, guild_id), lot)
            elif parti_longtemps:
                garde = tuple(sorted(GRAVES | {"kick"}))
                touches = await _sortir(db, guild_id, f"user_id=? AND type NOT IN {garde} AND {hors_exemptees}",
                                        (uid, guild_id), lot)
            else:
                touches = {}
            if touches:
                effaces[uid] = sum(touches.values())
            if raison and uid in presents:
                gardes.append((uid, raison))
        if effaces:
            await _noter_lot(db, guild_id, lot, 0, "Amnistie : 3 mois sans infraction, ou parti depuis 3 mois", effaces)
        await db.commit()
    return {"lot": lot, "membres": sorted(effaces), "n": sum(effaces.values()), "gardes": gardes}


def _unix(valeur) -> float:
    if not valeur:
        return 0.0
    try:
        return datetime.strptime(str(valeur)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0
