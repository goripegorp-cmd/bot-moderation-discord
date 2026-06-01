"""combat_recall.py — Phase 235.25c : RAPPEL des participants aux combats.

Directive owner #1 (rétention) : RETENIR qui participe aux events de combat
(boss raid, world boss, mob/spectre, boss du jour, climax) et les RE-PINGER au
prochain event du même genre. Participer = intéressé = à rappeler pour le garder
actif.

L'opt-out (bouton 🔔 / `/notify`) reste la SEULE échappatoire — il est appliqué
par le moteur de ping `_ping_active_members` (qui filtre via `_member_wants_notif`
sur le type ET l'interrupteur maître `events`). Ce module ne fait QUE mémoriser
les participants ; il ne contourne jamais l'opt-out.

Table PERSISTANTE (survit aux reboots — contrairement aux tables per-event qui se
vident à la fin de chaque combat). Tout est FAIL-OPEN : un bug ici renvoie une
liste vide / ne fait rien, et ne casse JAMAIS un spawn ni un combat.
"""

from datetime import datetime, timezone, timedelta

_get_db = None
_RECALL_DAYS = 21  # on rappelle les participants des ~3 dernières semaines


def setup(get_db_fn):
    global _get_db
    _get_db = get_db_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS combat_recall ("
                "guild_id INTEGER, user_id INTEGER, "
                "last_at TEXT, hits INTEGER DEFAULT 1, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_combat_recall_lookup "
                "ON combat_recall(guild_id, last_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[combat_recall init_db] {ex}")


async def record(guild_id, user_id):
    """Mémorise qu'un membre vient de participer à un combat. Idempotent (upsert).
    Appelé depuis les callbacks d'attaque (additif, fail-open)."""
    if _get_db is None:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO combat_recall (guild_id, user_id, last_at, hits) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "last_at = excluded.last_at, hits = hits + 1",
                (int(guild_id), int(user_id), now),
            )
            await db.commit()
    except Exception as ex:
        print(f"[combat_recall record] {ex}")


async def recent_user_ids(guild_id, limit=50):
    """IDs des membres ayant participé à un combat dans les _RECALL_DAYS derniers
    jours, du plus récent au plus ancien. Le moteur de ping applique ENSUITE
    l'opt-out + le cooldown + le filtre en-ligne. Fail-open → []."""
    if _get_db is None:
        return []
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=_RECALL_DAYS)).isoformat()
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM combat_recall "
                "WHERE guild_id=? AND last_at >= ? "
                "ORDER BY last_at DESC LIMIT ?",
                (int(guild_id), cutoff, int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        return [int(r[0]) for r in rows]
    except Exception as ex:
        print(f"[combat_recall recent_user_ids] {ex}")
        return []


async def cleanup_old():
    """Purge les participants inactifs depuis > 2× la fenêtre (table minuscule)."""
    if _get_db is None:
        return
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=_RECALL_DAYS * 2)).isoformat()
        async with _get_db() as db:
            await db.execute("DELETE FROM combat_recall WHERE last_at < ?", (cutoff,))
            await db.commit()
    except Exception as ex:
        print(f"[combat_recall cleanup_old] {ex}")
