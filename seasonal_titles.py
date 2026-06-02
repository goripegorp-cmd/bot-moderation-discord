"""seasonal_titles.py — Phase 242 : Champion d'activité du mois (titre persistant).

Chaque mois, les **3 meilleurs en ACTIVITÉ** (messages + vocal, table
`activity_score`) gagnent un titre 💎/🥈/🥉 affiché dans `/profile` — un titre
GAGNÉ qui reste, créant des pics de compétition mensuels (rétention).

Conception VOLONTAIREMENT simple et SANS RISQUE :
- Réutilise `activity_score` (donnée que le bot maîtrise déjà) → aucune nouvelle
  collecte, ne touche NI le combat NI le gate d'accès aux events.
- **Snapshot LAZY** : le classement du mois écoulé est figé au 1er `/profile`
  ouvert dans le nouveau mois (idempotent) → AUCUNE tâche planifiée à câbler.
- Reset mensuel NATUREL (nouveau mois = nouveau classement).
- Tout FAIL-OPEN : la moindre erreur → pas de titre, jamais de crash.

Module autonome : `setup(get_db)` au boot (même patron que activity_system).
"""

from datetime import datetime, timezone

_get_db = None

RANK_BADGE = {1: "💎", 2: "🥈", 3: "🥉"}

_FR_MONTHS = {
    "01": "janvier", "02": "février", "03": "mars", "04": "avril",
    "05": "mai", "06": "juin", "07": "juillet", "08": "août",
    "09": "septembre", "10": "octobre", "11": "novembre", "12": "décembre",
}


def setup(get_db_fn):
    global _get_db
    _get_db = get_db_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS monthly_champions ("
                "guild_id INTEGER, month TEXT, user_id INTEGER, rank INTEGER, "
                "points INTEGER, PRIMARY KEY (guild_id, month, rank))"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_monthly_champions_user "
                "ON monthly_champions(guild_id, user_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[seasonal_titles init_db] {ex}")


def _prev_month_key(dt) -> str:
    y, m = dt.year, dt.month
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def _pretty_month(mk: str) -> str:
    try:
        y, m = mk.split("-")
        return f"{_FR_MONTHS.get(m, m)} {y}"
    except Exception:
        return mk


async def ensure_snapshot(guild_id):
    """Fige (idempotent) le top 3 d'activité du MOIS PRÉCÉDENT. Appelé en LAZY
    depuis /profile. FAIL-OPEN."""
    if _get_db is None:
        return
    try:
        prev = _prev_month_key(datetime.now(timezone.utc))
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM monthly_champions WHERE guild_id=? AND month=? LIMIT 1",
                (int(guild_id), prev),
            ) as cur:
                if await cur.fetchone():
                    return  # déjà figé ce mois-ci
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(points), 0) AS pts FROM activity_score "
                "WHERE guild_id=? AND day LIKE ? GROUP BY user_id "
                "HAVING pts > 0 ORDER BY pts DESC LIMIT 3",
                (int(guild_id), prev + "-%"),
            ) as cur:
                rows = await cur.fetchall()
            for idx, (uid, pts) in enumerate(rows, start=1):
                await db.execute(
                    "INSERT OR REPLACE INTO monthly_champions"
                    "(guild_id, month, user_id, rank, points) VALUES (?,?,?,?,?)",
                    (int(guild_id), prev, int(uid), idx, int(pts or 0)),
                )
            await db.commit()
    except Exception as ex:
        print(f"[seasonal_titles ensure_snapshot] {ex}")


async def get_user_badge(guild_id, user_id) -> str:
    """Ligne titre la plus récente pour /profile (ou '' si aucun titre). FAIL-OPEN."""
    if _get_db is None:
        return ""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT month, rank FROM monthly_champions "
                "WHERE guild_id=? AND user_id=? ORDER BY month DESC LIMIT 1",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return ""
        badge = RANK_BADGE.get(int(row[1]), "🏅")
        return f"{badge} **Champion d'activité — {_pretty_month(row[0])}** (#{int(row[1])} du serveur)"
    except Exception:
        return ""


async def current_podium(guild_id, n=3):
    """Top N d'activité du MOIS EN COURS → [(user_id, points), …]. Pour affichage
    live « course au titre ». FAIL-OPEN."""
    if _get_db is None:
        return []
    try:
        cur_month = datetime.now(timezone.utc).strftime("%Y-%m")
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(points), 0) AS pts FROM activity_score "
                "WHERE guild_id=? AND day LIKE ? GROUP BY user_id "
                "HAVING pts > 0 ORDER BY pts DESC LIMIT ?",
                (int(guild_id), cur_month + "-%", int(n)),
            ) as cur:
                return [(int(r[0]), int(r[1] or 0)) for r in await cur.fetchall()]
    except Exception as ex:
        print(f"[seasonal_titles current_podium] {ex}")
        return []
