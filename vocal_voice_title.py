"""vocal_voice_title.py — Titre mensuel « 🎙️ Voix du serveur » (owner 2026-06-15).

Met en avant celles et ceux qui ANIMENT LES VOCAUX, À ÉGALITÉ avec le titre
« Champion d'activité » (seasonal_titles.py). Chaque mois, le TOP 3 du TEMPS
EN VOCAL (table `voice_activity_log`, secondes) gagne un titre 🥇/🥈/🥉
« Voix du serveur » affiché dans `/profile` — un titre GAGNÉ qui reste.

Conception VOLONTAIREMENT identique à seasonal_titles (patron éprouvé en prod) :
- Réutilise `voice_activity_log` (donnée déjà collectée par `_track_voice_state`)
  → AUCUNE nouvelle collecte, ne touche NI le combat NI le gate d'accès aux events.
- **Snapshot LAZY** : le classement du mois écoulé est figé au 1er `/profile`
  ouvert dans le nouveau mois (idempotent) → AUCUNE tâche planifiée à câbler.
- Reset mensuel NATUREL (nouveau mois = nouveau classement).
- Tout FAIL-OPEN : la moindre erreur → pas de titre, jamais de crash.

Classé sur le VOCAL SEUL (pas le score combiné) → prestige PROPRE que les
tops messages n'ont pas en double. Seuil mini pour que le titre reste rare.

Module autonome : `setup(get_db)` au boot (même patron que seasonal_titles).
"""

from datetime import datetime, timezone

_get_db = None

RANK_BADGE = {1: "🥇", 2: "🥈", 3: "🥉"}

# Plancher : minutes cumulées en vocal sur le mois pour qualifier au titre.
# Assez bas pour être atteignable, assez haut pour que le titre reste prestigieux
# (raretés dures — directive owner). 60 min = 1h cumulée dans le mois.
MIN_MONTHLY_VOICE_MINUTES = 60

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
                "CREATE TABLE IF NOT EXISTS monthly_voice_kings ("
                "guild_id INTEGER, month TEXT, user_id INTEGER, rank INTEGER, "
                "minutes INTEGER, PRIMARY KEY (guild_id, month, rank))"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_monthly_voice_kings_user "
                "ON monthly_voice_kings(guild_id, user_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[vocal_voice_title init_db] {ex}")


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
    """Fige (idempotent) le top 3 du TEMPS VOCAL du MOIS PRÉCÉDENT. Appelé en
    LAZY depuis /profile. FAIL-OPEN.

    NB : classé sur `joined_at` (mois où la session a COMMENCÉ), même convention
    que la requête hebdo de compute_top_active (activity_rewards) — cohérent."""
    if _get_db is None:
        return
    try:
        prev = _prev_month_key(datetime.now(timezone.utc))
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM monthly_voice_kings WHERE guild_id=? AND month=? LIMIT 1",
                (int(guild_id), prev),
            ) as cur:
                if await cur.fetchone():
                    return  # déjà figé ce mois-ci
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(duration_seconds), 0)/60 AS mins "
                "FROM voice_activity_log "
                "WHERE guild_id=? AND strftime('%Y-%m', joined_at)=? "
                "GROUP BY user_id HAVING mins >= ? "
                "ORDER BY mins DESC LIMIT 3",
                (int(guild_id), prev, MIN_MONTHLY_VOICE_MINUTES),
            ) as cur:
                rows = await cur.fetchall()
            for idx, (uid, mins) in enumerate(rows, start=1):
                await db.execute(
                    "INSERT OR REPLACE INTO monthly_voice_kings"
                    "(guild_id, month, user_id, rank, minutes) VALUES (?,?,?,?,?)",
                    (int(guild_id), prev, int(uid), idx, int(mins or 0)),
                )
            await db.commit()
    except Exception as ex:
        print(f"[vocal_voice_title ensure_snapshot] {ex}")


async def get_user_badge(guild_id, user_id) -> str:
    """Ligne titre vocal la plus récente pour /profile (ou '' si aucun). FAIL-OPEN."""
    if _get_db is None:
        return ""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT month, rank FROM monthly_voice_kings "
                "WHERE guild_id=? AND user_id=? ORDER BY month DESC LIMIT 1",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return ""
        badge = RANK_BADGE.get(int(row[1]), "🏅")
        return f"{badge} **Voix du serveur — {_pretty_month(row[0])}** (#{int(row[1])} en vocal)"
    except Exception:
        return ""


async def current_podium(guild_id, n=3):
    """Top N du temps vocal du MOIS EN COURS → [(user_id, minutes), …]. Pour
    affichage live « course au titre ». FAIL-OPEN."""
    if _get_db is None:
        return []
    try:
        cur_month = datetime.now(timezone.utc).strftime("%Y-%m")
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(duration_seconds), 0)/60 AS mins "
                "FROM voice_activity_log "
                "WHERE guild_id=? AND strftime('%Y-%m', joined_at)=? "
                "GROUP BY user_id HAVING mins > 0 ORDER BY mins DESC LIMIT ?",
                (int(guild_id), cur_month, int(n)),
            ) as cur:
                return [(int(r[0]), int(r[1] or 0)) for r in await cur.fetchall()]
    except Exception as ex:
        print(f"[vocal_voice_title current_podium] {ex}")
        return []
