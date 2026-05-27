"""
observability.py — Rapport quotidien + anomalies + rétention (Phase 139).

Trois features d'observabilité pour le staff owner :

1. **SNAPSHOT QUOTIDIEN** — capture chaque jour à 00:30 FR
   • member_count, joined, left, infractions (24h), tickets_opened,
     tickets_closed, events_won (24h), msgs cumul, voice_min cumul
   • Stocké dans daily_stats_snapshot pour historique
   • Posté dans hub_channel sous forme de rapport V2

2. **DÉTECTION D'ANOMALIES** — task toutes les 6h
   • Compare aujourd'hui vs moyenne 7 jours précédents
   • Spike détecté si valeur > 2× la moyenne (ou drop < 50%)
   • Stocké dans anomaly_log + alerté dans hub_channel si severity élevée

3. **RÉTENTION MEMBRES** — calcul depuis daily_join_log
   • % de nouveaux membres restés 7j / 30j / 90j
   • Courbe affichée dans panel V2

DB tables (créées à la volée) :
- daily_stats_snapshot   (guild_id, day TEXT PK, member_count, joined, left, ...)
- daily_join_log         (guild_id, user_id PK, joined_day, left_day)
- anomaly_log            (id, guild_id, kind, severity, detail, detected_at)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers)
- record_join(guild_id, user_id)        — hook on_member_join
- record_leave(guild_id, user_id)       — hook on_member_remove
- capture_snapshot(guild) -> dict       — snapshot manuel
- get_recent_snapshots(guild_id, days)  — liste pour graphe
- detect_anomalies(guild_id)            — retourne anomalies courantes
- compute_retention(guild_id)           — calcul retention 7/30/90
- build_daily_report_panel / build_retention_panel / build_anomalies_panel
- Tasks : daily_snapshot_task + anomaly_check_task

⚠️ Conforme RULES.md : pur outil owner/staff. Zéro relationnel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# ─── Configuration ───────────────────────────────────────────────────────
DAILY_POST_HOUR = 0          # 00:30 Europe/Paris
ANOMALY_CHECK_HOURS = 6      # check toutes les 6h
ANOMALY_SPIKE_FACTOR = 2.0   # > 2× la moyenne = spike
ANOMALY_DROP_FACTOR = 0.5    # < 50% de la moyenne = drop
RECENT_SNAPSHOTS_LIMIT = 7
RETENTION_WINDOWS = [7, 30, 90]  # jours après join


# Références injectées
_bot = None
_get_db = None
_db_get = None
_db_set = None
_v2_helpers = None
_tables_initialized = False


def setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers: dict):
    """Configure le module."""
    global _bot, _get_db, _db_get, _db_set, _v2_helpers
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _db_set = db_set_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Tables
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS daily_stats_snapshot (
                guild_id INTEGER,
                day TEXT,
                member_count INTEGER DEFAULT 0,
                joined INTEGER DEFAULT 0,
                left_count INTEGER DEFAULT 0,
                infractions INTEGER DEFAULT 0,
                tickets_opened INTEGER DEFAULT 0,
                tickets_closed INTEGER DEFAULT 0,
                events_finished INTEGER DEFAULT 0,
                captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, day)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS daily_join_log (
                guild_id INTEGER,
                user_id INTEGER,
                joined_day TEXT,
                left_day TEXT,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_join_log_day "
                "ON daily_join_log(guild_id, joined_day)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS anomaly_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                kind TEXT,
                severity TEXT,
                detail TEXT,
                detected_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_anomaly_recent "
                "ON anomaly_log(guild_id, detected_at DESC)"
            )
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[observability _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# RECORD — hooks à brancher dans bot.py
# ═══════════════════════════════════════════════════════════════════════════════

def _today_paris() -> str:
    return datetime.now(_PARIS_TZ).strftime("%Y-%m-%d")


async def record_join(guild_id: int, user_id: int):
    """Hook on_member_join : enregistre arrival."""
    if _get_db is None:
        return
    await _ensure_tables()
    day = _today_paris()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO daily_join_log(guild_id, user_id, joined_day, left_day) "
                "VALUES(?, ?, ?, NULL) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "joined_day=excluded.joined_day, left_day=NULL",
                (guild_id, user_id, day),
            )
            await db.commit()
    except Exception as ex:
        print(f"[observability record_join] {ex}")


async def record_leave(guild_id: int, user_id: int):
    """Hook on_member_remove : enregistre départ."""
    if _get_db is None:
        return
    await _ensure_tables()
    day = _today_paris()
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE daily_join_log SET left_day=? "
                "WHERE guild_id=? AND user_id=? AND left_day IS NULL",
                (day, guild_id, user_id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[observability record_leave] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT QUOTIDIEN
# ═══════════════════════════════════════════════════════════════════════════════

async def capture_snapshot(guild) -> dict:
    """Capture un snapshot des stats du jour pour ce guild.

    Le snapshot couvre la journée Paris courante (en cours), donc à 23h59
    juste avant minuit, les valeurs sont quasi-finales.
    """
    out = {
        "guild_id": guild.id,
        "day": _today_paris(),
        "member_count": 0,
        "joined": 0,
        "left_count": 0,
        "infractions": 0,
        "tickets_opened": 0,
        "tickets_closed": 0,
        "events_finished": 0,
    }
    if _get_db is None:
        return out

    await _ensure_tables()
    day = out["day"]
    try:
        # member_count : direct depuis l'objet guild
        out["member_count"] = guild.member_count or 0

        # joined / left aujourd'hui
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM daily_join_log "
                "WHERE guild_id=? AND joined_day=?",
                (guild.id, day),
            ) as cur:
                row = await cur.fetchone()
            out["joined"] = int(row[0] or 0) if row else 0

            async with db.execute(
                "SELECT COUNT(*) FROM daily_join_log "
                "WHERE guild_id=? AND left_day=?",
                (guild.id, day),
            ) as cur:
                row = await cur.fetchone()
            out["left_count"] = int(row[0] or 0) if row else 0

            # infractions aujourd'hui
            cutoff_iso = (
                datetime.now(_PARIS_TZ).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            ).isoformat()
            async with db.execute(
                "SELECT COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ?",
                (guild.id, cutoff_iso),
            ) as cur:
                row = await cur.fetchone()
            out["infractions"] = int(row[0] or 0) if row else 0

            # tickets opened/closed today (par created_at)
            async with db.execute(
                "SELECT COUNT(*) FROM tickets "
                "WHERE guild_id=? AND created_at >= ?",
                (guild.id, cutoff_iso),
            ) as cur:
                row = await cur.fetchone()
            out["tickets_opened"] = int(row[0] or 0) if row else 0

            async with db.execute(
                "SELECT COUNT(*) FROM tickets "
                "WHERE guild_id=? AND status='closed' AND created_at >= ?",
                (guild.id, cutoff_iso),
            ) as cur:
                row = await cur.fetchone()
            out["tickets_closed"] = int(row[0] or 0) if row else 0

            # events finished today
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE guild_id=? AND ended=1 AND started_at >= ?",
                    (guild.id, cutoff_iso),
                ) as cur:
                    row = await cur.fetchone()
                out["events_finished"] = int(row[0] or 0) if row else 0
            except Exception:
                pass

            # Upsert snapshot
            await db.execute(
                "INSERT INTO daily_stats_snapshot"
                "(guild_id, day, member_count, joined, left_count, "
                "infractions, tickets_opened, tickets_closed, events_finished) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, day) DO UPDATE SET "
                "member_count=excluded.member_count, "
                "joined=excluded.joined, left_count=excluded.left_count, "
                "infractions=excluded.infractions, "
                "tickets_opened=excluded.tickets_opened, "
                "tickets_closed=excluded.tickets_closed, "
                "events_finished=excluded.events_finished, "
                "captured_at=CURRENT_TIMESTAMP",
                (
                    guild.id, day, out["member_count"],
                    out["joined"], out["left_count"],
                    out["infractions"], out["tickets_opened"],
                    out["tickets_closed"], out["events_finished"],
                ),
            )
            await db.commit()
    except Exception as ex:
        print(f"[observability capture_snapshot guild={guild.id}] {ex}")

    return out


async def get_recent_snapshots(
    guild_id: int, days: int = RECENT_SNAPSHOTS_LIMIT
) -> list[dict]:
    """Retourne les N derniers snapshots du plus récent au plus ancien."""
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT day, member_count, joined, left_count, infractions, "
                "tickets_opened, tickets_closed, events_finished "
                "FROM daily_stats_snapshot WHERE guild_id=? "
                "ORDER BY day DESC LIMIT ?",
                (guild_id, max(1, min(90, int(days or 7)))),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "day": r[0],
                "member_count": int(r[1] or 0),
                "joined": int(r[2] or 0),
                "left_count": int(r[3] or 0),
                "infractions": int(r[4] or 0),
                "tickets_opened": int(r[5] or 0),
                "tickets_closed": int(r[6] or 0),
                "events_finished": int(r[7] or 0),
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[observability get_recent_snapshots] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# DÉTECTION D'ANOMALIES
# ═══════════════════════════════════════════════════════════════════════════════

async def detect_anomalies(guild_id: int) -> list[dict]:
    """Compare aujourd'hui vs moyenne 7j et détecte spikes/drops.

    Retourne liste d'anomalies [{kind, severity, detail, today, baseline}].
    """
    out = []
    snapshots = await get_recent_snapshots(guild_id, days=8)
    if len(snapshots) < 4:  # pas assez de data pour comparer
        return out

    today_snap = snapshots[0]
    baseline = snapshots[1:8]  # 7 jours précédents

    metrics = [
        ("joined", "📈 Arrivées de nouveaux membres"),
        ("left_count", "📉 Départs de membres"),
        ("infractions", "⚠️ Modérations / infractions"),
        ("tickets_opened", "🎫 Tickets ouverts"),
    ]

    for key, label in metrics:
        today_val = int(today_snap.get(key, 0))
        avg = sum(int(s.get(key, 0)) for s in baseline) / max(1, len(baseline))
        if avg < 1:
            continue
        ratio = today_val / avg

        if ratio >= ANOMALY_SPIKE_FACTOR:
            severity = "high" if ratio >= 3.0 else "medium"
            out.append({
                "kind": f"spike_{key}",
                "label": label,
                "severity": severity,
                "today": today_val,
                "baseline": round(avg, 1),
                "ratio": round(ratio, 2),
                "detail": (
                    f"Spike détecté : `{today_val}` aujourd'hui vs "
                    f"moyenne `{avg:.1f}` ({ratio:.1f}×)"
                ),
            })
        elif ratio <= ANOMALY_DROP_FACTOR and avg > 3:
            # Drop seulement si la baseline était significative
            out.append({
                "kind": f"drop_{key}",
                "label": label,
                "severity": "low",
                "today": today_val,
                "baseline": round(avg, 1),
                "ratio": round(ratio, 2),
                "detail": (
                    f"Drop détecté : `{today_val}` aujourd'hui vs "
                    f"moyenne `{avg:.1f}` ({ratio:.1f}×)"
                ),
            })

    return out


async def log_anomaly(
    guild_id: int, kind: str, severity: str, detail: str
):
    """Enregistre une anomalie dans le log."""
    if _get_db is None:
        return
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO anomaly_log(guild_id, kind, severity, detail) "
                "VALUES(?, ?, ?, ?)",
                (guild_id, kind, severity, detail),
            )
            await db.commit()
    except Exception as ex:
        print(f"[observability log_anomaly] {ex}")


async def get_recent_anomalies(
    guild_id: int, limit: int = 10
) -> list[dict]:
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT kind, severity, detail, detected_at FROM anomaly_log "
                "WHERE guild_id=? ORDER BY detected_at DESC LIMIT ?",
                (guild_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "kind": r[0] or "",
                "severity": r[1] or "low",
                "detail": r[2] or "",
                "detected_at": r[3],
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[observability get_recent_anomalies] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# RÉTENTION
# ═══════════════════════════════════════════════════════════════════════════════

async def compute_retention(guild_id: int) -> dict:
    """Calcule % de rétention à 7/30/90 jours.

    Pour chaque fenêtre : sur les membres qui ont rejoint il y a >= N jours,
    quel % est encore là (left_day IS NULL ou left_day > joined_day + N).
    """
    out = {"windows": {}, "total_tracked": 0}
    if _get_db is None:
        return out

    await _ensure_tables()
    today_dt = datetime.now(_PARIS_TZ)

    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT joined_day, left_day FROM daily_join_log "
                "WHERE guild_id=? AND joined_day IS NOT NULL",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        out["total_tracked"] = len(rows)
        if not rows:
            return out

        for window_days in RETENTION_WINDOWS:
            kept = 0
            eligible = 0
            for joined_day, left_day in rows:
                try:
                    jd = datetime.strptime(joined_day, "%Y-%m-%d")
                    if jd.tzinfo is None:
                        jd = jd.replace(tzinfo=_PARIS_TZ)
                except Exception:
                    continue
                days_since_join = (today_dt - jd).days
                if days_since_join < window_days:
                    continue  # pas encore eligible pour cette fenêtre
                eligible += 1
                if not left_day:
                    kept += 1
                else:
                    try:
                        ld = datetime.strptime(left_day, "%Y-%m-%d")
                        if ld.tzinfo is None:
                            ld = ld.replace(tzinfo=_PARIS_TZ)
                        if (ld - jd).days >= window_days:
                            kept += 1
                    except Exception:
                        pass
            pct = (kept / eligible * 100) if eligible else 0
            out["windows"][window_days] = {
                "kept": kept,
                "eligible": eligible,
                "pct": round(pct, 1),
            }
    except Exception as ex:
        print(f"[observability compute_retention] {ex}")

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# PANELS V2
# ═══════════════════════════════════════════════════════════════════════════════

def _diff_str(today: int, prev: int) -> str:
    """Format '↑ +5' ou '↓ -3' ou '='."""
    if prev == 0 and today == 0:
        return "_=_"
    delta = today - prev
    if delta == 0:
        return "_=_"
    if delta > 0:
        return f"_↑ +{delta}_"
    return f"_↓ {delta}_"


def build_daily_report_panel(snapshot: dict, prev_snapshot: Optional[dict],
                              guild_name: str = ""):
    """Panel V2 du rapport quotidien."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    prev = prev_snapshot or {}

    class _DailyReport(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"📊  RAPPORT QUOTIDIEN — {snapshot['day']}"))
            items.append(v2_subtitle(
                f"_État du serveur {guild_name} sur les dernières 24h_"
            ))
            items.append(v2_divider())

            # Members
            items.append(v2_body("**╔═══ 👥  MEMBRES  ═══╗**"))
            items.append(v2_body(
                f"📊 Total membres : `{snapshot['member_count']}` "
                f"{_diff_str(snapshot['member_count'], prev.get('member_count', 0))}\n"
                f"➕ Arrivées : `{snapshot['joined']}` "
                f"{_diff_str(snapshot['joined'], prev.get('joined', 0))}\n"
                f"➖ Départs : `{snapshot['left_count']}` "
                f"{_diff_str(snapshot['left_count'], prev.get('left_count', 0))}\n"
                f"📈 Net : `{snapshot['joined'] - snapshot['left_count']:+}`"
            ))

            # Mod
            items.append(v2_divider())
            items.append(v2_body("**╔═══ 🛡️  MODÉRATION  ═══╗**"))
            items.append(v2_body(
                f"⚠️ Infractions : `{snapshot['infractions']}` "
                f"{_diff_str(snapshot['infractions'], prev.get('infractions', 0))}"
            ))

            # Tickets
            items.append(v2_divider())
            items.append(v2_body("**╔═══ 🎫  TICKETS  ═══╗**"))
            items.append(v2_body(
                f"🟢 Ouverts : `{snapshot['tickets_opened']}` "
                f"{_diff_str(snapshot['tickets_opened'], prev.get('tickets_opened', 0))}\n"
                f"🔒 Fermés : `{snapshot['tickets_closed']}` "
                f"{_diff_str(snapshot['tickets_closed'], prev.get('tickets_closed', 0))}"
            ))

            # Events
            items.append(v2_divider())
            items.append(v2_body("**╔═══ 🎯  EVENTS  ═══╗**"))
            items.append(v2_body(
                f"🏆 Events terminés : `{snapshot['events_finished']}` "
                f"{_diff_str(snapshot['events_finished'], prev.get('events_finished', 0))}"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/server retention` pour les courbes de rétention._\n"
                "_💡 `/server anomalies` pour les alertes détectées._"
            ))

            self.add_item(v2_container(*items, color=0x2ECC71))

    return _DailyReport()


def build_history_panel(snapshots: list[dict], guild_name: str = ""):
    """Panel V2 de l'historique des N derniers jours."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _HistoryPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("📈  HISTORIQUE DES SNAPSHOTS"))
            items.append(v2_subtitle(
                f"_Les {len(snapshots)} derniers jours de {guild_name}_"
            ))
            items.append(v2_divider())

            if not snapshots:
                items.append(v2_body(
                    "_Aucun snapshot enregistré pour l'instant._"
                ))
            else:
                lines = []
                for s in snapshots:
                    lines.append(
                        f"📅 **`{s['day']}`** — "
                        f"👥 `{s['member_count']}` membres · "
                        f"➕`{s['joined']}` / ➖`{s['left_count']}` · "
                        f"⚠️ `{s['infractions']}` mod · "
                        f"🎫 `{s['tickets_opened']}` tickets · "
                        f"🎯 `{s['events_finished']}` events"
                    )
                items.append(v2_body("\n\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/server report` pour le dernier rapport détaillé._"
            ))

            self.add_item(v2_container(*items, color=0x2ECC71))

    return _HistoryPanel()


def build_retention_panel(retention: dict, guild_name: str = ""):
    """Panel V2 des courbes de rétention."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _RetentionPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("📉  RÉTENTION MEMBRES"))
            items.append(v2_subtitle(
                f"_Combien de nouveaux restent après N jours — {guild_name}_"
            ))
            items.append(v2_divider())

            items.append(v2_body(
                f"📊 **Total membres trackés :** `{retention.get('total_tracked', 0)}`\n"
                f"_(Seuls les membres ayant rejoint depuis l'activation du module "
                f"sont comptés)_"
            ))
            items.append(v2_divider())

            windows = retention.get("windows", {})
            if not windows:
                items.append(v2_body(
                    "_Pas encore assez de données. "
                    "Reviens dans 7 jours._"
                ))
            else:
                lines = []
                for w in [7, 30, 90]:
                    if w not in windows:
                        continue
                    data = windows[w]
                    pct = data["pct"]
                    bar_len = 20
                    filled = round(pct / 100 * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    lines.append(
                        f"⏱️ **Après {w} jours** : `{pct}%`\n"
                        f"   `{bar}`\n"
                        f"   _`{data['kept']}` restés sur `{data['eligible']}` éligibles_"
                    )
                items.append(v2_body("\n\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 Vise > 50% à 7j pour un bon onboarding, > 30% à 30j pour "
                "une communauté saine._"
            ))

            self.add_item(v2_container(*items, color=0x9B59B6))

    return _RetentionPanel()


def build_anomalies_panel(anomalies: list[dict], guild_name: str = ""):
    """Panel V2 des anomalies récentes."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    severity_emoji = {"high": "🔴", "medium": "🟠", "low": "🟡"}

    class _AnomaliesPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("🚨  ANOMALIES DÉTECTÉES"))
            items.append(v2_subtitle(
                f"_Les {len(anomalies)} derniers signaux faibles — {guild_name}_"
            ))
            items.append(v2_divider())

            if not anomalies:
                items.append(v2_body(
                    "✨ _Aucune anomalie détectée récemment. Tout va bien !_"
                ))
            else:
                lines = []
                for a in anomalies[:10]:
                    em = severity_emoji.get(a["severity"], "🟡")
                    lines.append(
                        f"{em} **{a['kind']}** _({a['severity']})_\n"
                        f"   {a['detail']}\n"
                        f"   _Détecté : {a['detected_at']}_"
                    )
                items.append(v2_body("\n\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 Check toutes les 6h vs moyenne des 7 jours précédents. "
                "Spike > 2× ou drop < 50% déclenche un signal._"
            ))

            self.add_item(v2_container(*items, color=0xE74C3C))

    return _AnomaliesPanel()


# ═══════════════════════════════════════════════════════════════════════════════
# TASKS PROGRAMMÉES
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def daily_snapshot_task():
    """Tourne toutes les 30 min — capture + post à 00h00-00h30 FR (chaque jour)."""
    try:
        if _bot is None or _db_get is None or _db_set is None:
            return
        now_local = datetime.now(_PARIS_TZ)
        if now_local.hour != DAILY_POST_HOUR:
            return

        await _ensure_tables()
        day_id = now_local.strftime("%Y-%m-%d")

        for guild in list(_bot.guilds):
            try:
                # Anti-doublon via cfg
                cfg_data = await _db_get(guild.id)
                last_day = cfg_data.get("obs_report_last_day", "")
                if last_day == day_id:
                    continue

                # Capture snapshot (de hier en fait, donc on regarde la
                # journée Paris qui vient de se terminer)
                yesterday_dt = now_local - timedelta(days=1)
                snapshot = await capture_snapshot(guild)

                # Récupère snapshot de l'avant-veille pour les diffs
                prev_list = await get_recent_snapshots(guild.id, days=3)
                prev = prev_list[1] if len(prev_list) >= 2 else None

                # Post dans hub
                hub_ch_id = int(cfg_data.get("hub_channel", 0) or 0)
                if hub_ch_id:
                    ch = guild.get_channel(hub_ch_id)
                    if ch:
                        view = build_daily_report_panel(snapshot, prev, guild.name)
                        if view is not None:
                            try:
                                await ch.send(view=view)
                            except (discord.Forbidden, discord.HTTPException) as ex:
                                print(f"[observability daily send guild={guild.id}] {ex}")

                await _db_set(guild.id, "obs_report_last_day", day_id)
            except Exception as ex:
                print(f"[observability daily_snapshot guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[observability daily_snapshot_task] {ex}")


@daily_snapshot_task.before_loop
async def _before_daily():
    if _bot is not None:
        await _bot.wait_until_ready()


@tasks.loop(hours=ANOMALY_CHECK_HOURS)
async def anomaly_check_task():
    """Tourne toutes les 6h — détecte spikes/drops vs moyenne 7j."""
    try:
        if _bot is None or _get_db is None:
            return
        await _ensure_tables()
        for guild in list(_bot.guilds):
            try:
                # On capture d'abord pour avoir des données fraîches
                await capture_snapshot(guild)
                anomalies = await detect_anomalies(guild.id)
                for a in anomalies:
                    await log_anomaly(
                        guild.id, a["kind"], a["severity"], a["detail"]
                    )
            except Exception as ex:
                print(f"[observability anomaly_check guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[observability anomaly_check_task] {ex}")


@anomaly_check_task.before_loop
async def _before_anomaly():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    # Hooks
    "record_join", "record_leave",
    # Snapshots
    "capture_snapshot", "get_recent_snapshots",
    # Anomalies
    "detect_anomalies", "log_anomaly", "get_recent_anomalies",
    # Retention
    "compute_retention",
    # Panels
    "build_daily_report_panel", "build_history_panel",
    "build_retention_panel", "build_anomalies_panel",
    # Tasks
    "daily_snapshot_task", "anomaly_check_task",
]
