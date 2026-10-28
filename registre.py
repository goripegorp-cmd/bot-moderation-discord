"""registre.py — le journal du serveur, lu sur le tableau de bord (19/10/2026).

« Il n'y aura plus de logs sur le serveur Discord : ce sera envoyé sur le site, traduit
correctement par personne, tout ce qui s'est passé. Ça filtrera les logs inutiles… qui nettoie
bien correctement, qui soit bien optimisé. »

Une ligne par évènement : quand, quoi (catégorie, type), qui (membre visé, auteur), où, une
phrase lisible et un détail court. Écartés : le bruit (bots, vocal coupé/partagé, doublons à
quelques secondes). Purge : messages et vocal après 30 jours, le reste après 90 — toutes les 2 000 écritures et
chaque semaine (`data_cleanup.PURGES_CIBLEES`). 26/10/2026 (banc de plusieurs années) : messages et vocal (le
bruit) ont leur propre limite, 100 000 lignes (au-delà, leurs plus anciennes partent) ; le reste (sanctions,
sécurité, tickets…) garde ses 90 jours ; 200 000 lignes au plus en tout (le filet). Avant, une limite unique de
100 000 coupait TOUTES les catégories : à 5 ans, sanctions et sécurité n'avaient plus que ~26 jours au lieu de 90.

Gravité : 0 information, 1 à surveiller, 2 grave, 3 critique (`GRAVITES`). Un évènement grave
qui vise un membre prévient `vigilance` (l'alerte « cumule des évènements graves »).
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone

INUTILES = {"voice.mute", "voice.stream"}
DOUBLON_SECONDES = 5
JOURS_COURTS = 30  # messages et vocal
JOURS = 90
PLAFOND = 200_000         # en tout (le filet) : au-delà, les plus anciennes partent, quelle que soit leur catégorie
PLAFOND_BRUIT = 100_000   # au-delà, messages et vocal partent d'abord (les plus anciens)
BRUIT = ("Messages", "Vocal")
GRAVITES = {"mod.warn": 1, "mod.mute": 2, "mod.timeout": 2, "mod.kick": 3, "mod.ban": 3,
            "sec.spam": 1, "sec.badword": 1, "sec.link": 1, "sec.invite": 1, "sec.mention": 1,
            "sec.image": 1, "sec.alt": 1, "sec.profil": 1, "sec.toxicite": 1, "sec.qrcode": 2, "sec.escalation": 2,
            "sec.raid": 3, "sec.phishing": 3, "sec.scam": 3, "sec.nsfw": 3}
#  Les mêmes purges servent au grand nettoyage hebdomadaire (`data_cleanup`) et, ici, toutes
#  les PURGE_TOUTES écritures : la rétention est tenue au jour près, sans attendre dimanche.
PURGES = [
    ("registre : messages et vocal",
     "DELETE FROM registre WHERE categorie IN ('Messages', 'Vocal') AND quand < ?", JOURS_COURTS, "unix"),
    ("registre", "DELETE FROM registre WHERE quand < ?", JOURS, "unix"),
    ("registre : plafond du bruit", "DELETE FROM registre WHERE id IN (SELECT id FROM registre WHERE categorie IN"
                                    " ('Messages', 'Vocal') ORDER BY id LIMIT max(0, (SELECT COUNT(*) FROM registre"
                                    f" WHERE categorie IN ('Messages', 'Vocal')) - {PLAFOND_BRUIT}))", None, None),
    ("registre : plafond", "DELETE FROM registre WHERE id <= "
                           f"(SELECT id FROM registre ORDER BY id DESC LIMIT 1 OFFSET {PLAFOND})", None, None),
]
PURGE_TOUTES = 2000
COLONNES = ("id", "quand", "categorie", "type", "membre_id", "auteur_id", "salon_id", "texte", "detail", "gravite")
PAR_JOUR_FRAIS = 300      # s : le comptage par jour gardé en mémoire (`par_jour`)
_get_db = None
_apres_grave = None
_derniers: dict = {}
_par_jour: dict = {}      # (serveur, jours, fuseau) → (heure, comptage)
_ecritures = 0
_log = print


def setup(*, get_db, log=None, apres_grave=None):
    """`apres_grave(guild_id, membre_id)` : appelé (sans attendre) après un évènement grave."""
    global _get_db, _log, _apres_grave
    _get_db, _log, _apres_grave = get_db, log or print, apres_grave
    _par_jour.clear()


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS registre (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " guild_id INTEGER NOT NULL, quand INTEGER NOT NULL, categorie TEXT, type TEXT,"
            " membre_id INTEGER DEFAULT 0, auteur_id INTEGER DEFAULT 0, salon_id INTEGER DEFAULT 0,"
            " texte TEXT, detail TEXT DEFAULT '', gravite INTEGER DEFAULT 0)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_registre_quand ON registre(guild_id, quand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_registre_membre ON registre(guild_id, membre_id, quand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_registre_auteur ON registre(guild_id, auteur_id)")
        #  26/10/2026 (banc de plusieurs années) : par catégorie — les comptes de la rubrique Nettoyage (40 ms → 5 ms à
        #  5 ans), la purge des messages et du vocal, le journal du site filtré par catégorie (`longevite`).
        await db.execute("CREATE INDEX IF NOT EXISTS idx_registre_categorie ON registre(guild_id, categorie, quand)")
        await db.commit()


def propre(texte: str, guild=None) -> str:
    """Une phrase lisible : mentions en noms, plus de mise en forme Discord."""
    t = str(texte or "")

    def membre(m):
        x = guild.get_member(int(m.group(1))) if guild else None
        return f"@{x.display_name}" if x else "@membre"

    def salon(m):
        x = guild.get_channel(int(m.group(1))) if guild else None
        return f"#{x.name}" if x else "#salon"
    t = re.sub(r"<@!?(\d+)>", membre, t)
    t = re.sub(r"<#(\d+)>", salon, t)
    t = re.sub(r"<@&\d+>", "@rôle", t)
    t = re.sub(r"<a?:(\w+):\d+>", r":\1:", t)
    t = re.sub(r"<t:(\d+)(?::\w)?>", "", t)
    t = re.sub(r"\*\*|__|`|~~", "", t)
    t = re.sub(r"(?m)^-#\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


async def purger(maintenant: float | None = None) -> int:
    t = int(maintenant or time.time())
    n = 0
    async with _get_db() as db:
        for _nom, sql, jours, _fmt in PURGES:
            cur = await db.execute(sql, (t - jours * 86400,) if jours else ())
            n += max(cur.rowcount or 0, 0)
        await db.commit()
    return n


async def noter(guild_id: int, categorie: str, type_: str, texte: str, *, membre_id: int = 0,
                auteur_id: int = 0, salon_id: int = 0, detail: str = "", gravite: int = 0) -> bool:
    """Consigne un évènement. Rend False s'il est écarté (inutile ou doublon)."""
    global _ecritures
    if _get_db is None or type_ in INUTILES or not texte:
        return False
    maintenant = time.time()
    texte, detail = str(texte)[:300], str(detail or "")[:600]
    #  Un doublon = la même phrase ET le même détail (condensés). 24/10/2026 : la clé ignorait le
    #  détail ; deux suppressions du même auteur dans le même salon ont la même phrase mais pas le
    #  même contenu — la 2ᵉ, la 3ᵉ… disparaissaient en moins de 5 s, avec leur contenu (des preuves).
    condense = hashlib.blake2b(f"{texte}\x00{detail}".encode("utf-8", "replace"), digest_size=8).digest()
    cle = (guild_id, type_, int(membre_id or 0), condense)
    if maintenant - _derniers.get(cle, 0) < DOUBLON_SECONDES:
        return False
    _derniers[cle] = maintenant
    if len(_derniers) > 5000:
        for k in [k for k, t in _derniers.items() if maintenant - t > DOUBLON_SECONDES]:
            _derniers.pop(k, None)
    gravite = max(int(gravite or 0), GRAVITES.get(type_, 0))
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO registre (guild_id, quand, categorie, type, membre_id, auteur_id, salon_id,"
                " texte, detail, gravite) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(guild_id), int(maintenant), str(categorie or "Autre")[:40], str(type_)[:40],
                 int(membre_id or 0), int(auteur_id or 0), int(salon_id or 0), texte, detail, gravite))
            await db.commit()
        _ecritures += 1
        if _ecritures % PURGE_TOUTES == 0:
            _log(f"[REGISTRE] purge : {await purger()} ligne(s)")
    except Exception as ex:  # le journal ne doit jamais casser l'action qui l'appelle
        _log("[REGISTRE][E1] écriture impossible")
        _log(f"[REGISTRE][E1:DETAIL] {type(ex).__name__} {ex}")
        return False
    if gravite >= 1 and membre_id and _apres_grave is not None:
        try:
            _apres_grave(int(guild_id), int(membre_id))
        except Exception as ex:  # l'alerte ne doit jamais casser le journal
            _log("[REGISTRE][E2] vigilance indisponible")
            _log(f"[REGISTRE][E2:DETAIL] {type(ex).__name__} {ex}")
    return True


async def _rangs(sql: str, args: tuple) -> list[dict]:
    try:
        async with _get_db() as db:
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
    except Exception as ex:
        _log("[REGISTRE][E3] lecture impossible")
        _log(f"[REGISTRE][E3:DETAIL] {type(ex).__name__} {ex}")
        return []
    return [dict(zip(COLONNES, r)) for r in rows]


async def lire(guild_id: int, limite: int = 400, membre_id: int | None = None, depuis: int = 0,
               categorie: str | None = None) -> list[dict]:
    """Les derniers évènements, du plus récent au plus ancien : d'une personne (visée ou auteur),
    depuis une date, d'une catégorie, si demandé."""
    #  26/10/2026 (banc de plusieurs années) : seul le serveur filtré, SQLite prenait un index par auteur, lisait TOUT
    #  le journal et le triait (40 ms à 100 000 lignes) ; « +guild_id » le fait lire à rebours, et s'arrêter à `limite`.
    seul = not (membre_id or depuis or categorie)
    where, args = ["+guild_id=?" if seul else "guild_id=?"], [int(guild_id)]
    if membre_id:
        where.append("(membre_id=? OR auteur_id=?)")
        args += [int(membre_id), int(membre_id)]
    if depuis:
        where.append("quand>=?")
        args.append(int(depuis))
    if categorie:
        where.append("categorie=?")
        args.append(str(categorie))
    return await _rangs(f"SELECT {', '.join(COLONNES)} FROM registre WHERE {' AND '.join(where)}"
                        " ORDER BY id DESC LIMIT ?", (*args, int(limite)))


async def graves(guild_id: int, membre_id: int, depuis: int) -> list[dict]:
    """Les évènements graves qui visent un membre, depuis une date, du plus ancien au plus récent."""
    return await _rangs(f"SELECT {', '.join(COLONNES)} FROM registre WHERE guild_id=? AND membre_id=?"
                        " AND gravite>=1 AND quand>=? ORDER BY quand, id", (int(guild_id), int(membre_id), int(depuis)))


async def par_jour(guild_id: int, jours: int = 30, fuseau=timezone.utc, maintenant: float | None = None) -> dict:
    """{« AAAA-MM-JJ » : {catégorie : nombre}} sur `jours` jours, journées coupées à minuit dans
    `fuseau` (l'heure de Paris pour le site), changements d'heure compris.

    24/10/2026 : on ajoutait à tout l'historique le décalage d'AUJOURD'HUI — au passage à l'heure
    d'hiver (25/10), chaque jour d'avant perdait sa première heure au profit de la veille. La base
    compte par heure UTC ; chaque heure prend la date de son propre décalage (l'heure de Paris
    change à l'heure pleine : une heure UTC tombe toujours dans un seul jour).

    26/10/2026 (banc de plusieurs années) : ce comptage parcourt un mois de journal (115 000 lignes à 5 ans, 80 ms) à
    chaque reconstruction des données du site ; il est gardé PAR_JOUR_FRAIS secondes (les jours passés ne bougent
    plus, celui d'aujourd'hui peut attendre quelques minutes)."""
    t = maintenant or time.time()
    cle = (int(guild_id), int(jours), str(fuseau))
    deja = _par_jour.get(cle)
    if maintenant is None and deja is not None and t - deja[0] < PAR_JOUR_FRAIS:
        return {k: dict(v) for k, v in deja[1].items()}
    out = await _par_jour_lu(guild_id, jours, fuseau, t)
    if maintenant is None and out:
        if len(_par_jour) > 64:
            _par_jour.clear()
        _par_jour[cle] = (t, out)
        return {k: dict(v) for k, v in out.items()}
    return out


async def _par_jour_lu(guild_id: int, jours: int, fuseau, maintenant: float) -> dict:
    debut = int(maintenant - jours * 86400)
    try:
        async with _get_db() as db:
            async with db.execute("SELECT quand / 3600 AS h, categorie, COUNT(*) FROM registre"
                                  " WHERE guild_id=? AND quand>=? GROUP BY h, categorie",
                                  (int(guild_id), debut)) as cur:
                rows = await cur.fetchall()
    except Exception as ex:
        _log("[REGISTRE][E4] comptage impossible")
        _log(f"[REGISTRE][E4:DETAIL] {type(ex).__name__} {ex}")
        return {}
    out: dict = {}
    for h, cat, n in rows:
        jour = out.setdefault(datetime.fromtimestamp(int(h) * 3600, fuseau).strftime("%Y-%m-%d"), {})
        jour[cat or "Autre"] = jour.get(cat or "Autre", 0) + int(n)
    return dict(sorted(out.items()))
