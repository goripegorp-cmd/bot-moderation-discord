"""publications.py — une publication des réseaux sociaux = un seul message (19/10/2026).

« Le bot publie deux fois les annonces. » Trois chemins peuvent annoncer la même vidéo : le
relevé du panneau « Réseaux sociaux », le gestionnaire des abonnements, et désormais la poussée
instantanée de YouTube (WebSub). Pendant un redéploiement, deux instances du bot tournent
parfois ensemble. Chacun gardait sa propre mémoire de ce qui était publié — d'où les doublons.

Ici, une RÉSERVATION ATOMIQUE en base avant d'envoyer : `INSERT OR IGNORE` sur
(serveur, plateforme, identifiant du post). Un seul chemin, une seule instance l'emporte ; les
autres passent leur tour. Si l'envoi échoue, la réservation est rendue et le prochain passage
réessaie. Une réservation restée sans message (instance arrêtée au milieu) se reprend après
REPRISE secondes.
"""
from __future__ import annotations

import time

REPRISE = 600
JOURS = 365
PURGES = [("publications des réseaux", "DELETE FROM publications WHERE reserve_le < ?", JOURS, "unix")]
_get_db = None
_instance = "?"
_log = print


def setup(*, get_db, instance: str = "?", log=None):
    global _get_db, _instance, _log
    _get_db, _instance, _log = get_db, str(instance), log or print


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS publications (guild_id INTEGER NOT NULL, plateforme TEXT NOT NULL,"
            " post_id TEXT NOT NULL, reserve_le INTEGER NOT NULL, instance TEXT DEFAULT '', chemin TEXT DEFAULT '',"
            " message_id INTEGER DEFAULT 0, salon_id INTEGER DEFAULT 0, PRIMARY KEY (guild_id, plateforme, post_id))")
        await db.commit()


def identifiant(plateforme: str, post_id: str) -> str:
    """Le même post, quel que soit le chemin : le gestionnaire lit `yt:video:<id>` dans le flux
    Atom, le panneau et WebSub lisent `<id>`."""
    pid = str(post_id)
    if plateforme == "youtube" and pid.startswith("yt:video:"):
        pid = pid[len("yt:video:"):]
    return pid


async def reserver(guild_id: int, plateforme: str, post_id: str, chemin: str = "",
                   maintenant: float | None = None) -> bool:
    """True : à toi d'envoyer. False : déjà publié, ou en cours d'envoi ailleurs."""
    t = int(maintenant or time.time())
    cle = (int(guild_id), str(plateforme), identifiant(plateforme, post_id))
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO publications (guild_id, plateforme, post_id, reserve_le, instance,"
                               " chemin) VALUES (?,?,?,?,?,?)", (*cle, t, _instance, chemin[:40]))
        if not cur.rowcount:
            cur = await db.execute("UPDATE publications SET reserve_le=?, instance=?, chemin=? WHERE guild_id=? AND"
                                   " plateforme=? AND post_id=? AND message_id=0 AND salon_id=0 AND reserve_le<?",
                                   (t, _instance, chemin[:40], *cle, t - REPRISE))
        await db.commit()
        return bool(cur.rowcount)


async def confirmer(guild_id: int, plateforme: str, post_id: str, message_id: int, salon_id: int) -> None:
    async with _get_db() as db:
        await db.execute("UPDATE publications SET message_id=?, salon_id=? WHERE guild_id=? AND plateforme=? AND post_id=?",
                         (int(message_id or 0), int(salon_id or 0) or -1, int(guild_id), str(plateforme),
                          identifiant(plateforme, post_id)))
        await db.commit()


async def annuler(guild_id: int, plateforme: str, post_id: str) -> None:
    """L'envoi a échoué : la place est rendue, le prochain passage réessaiera."""
    async with _get_db() as db:
        await db.execute("DELETE FROM publications WHERE guild_id=? AND plateforme=? AND post_id=? AND message_id=0"
                         " AND salon_id=0",
                         (int(guild_id), str(plateforme), identifiant(plateforme, post_id)))
        await db.commit()


async def deja(guild_id: int, plateforme: str, post_id: str) -> bool:
    async with _get_db() as db:
        async with db.execute("SELECT 1 FROM publications WHERE guild_id=? AND plateforme=? AND post_id=?",
                              (int(guild_id), str(plateforme), identifiant(plateforme, post_id))) as cur:
            return await cur.fetchone() is not None
