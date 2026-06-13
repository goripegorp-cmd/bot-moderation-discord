"""
owner_digest.py — DM quotidien automatique au owner (Phase 152).

🎯 OBJECTIF : l'owner sait TOUT sans avoir à explorer le serveur.
Chaque matin à 9h FR, il reçoit un DM récap :

- Nouveaux membres (avec leur style détecté si > 10 actions)
- Top 3 actifs (24h)
- Events à venir aujourd'hui
- Alertes sécurité de la nuit (raids, phishing, impersonation)
- Webhooks inactifs détectés
- Stats serveur (membres / messages / vocaux)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers,
        profile_module=None, raid_module=None, webhook_tracker=None)
- send_now(guild) -> bool (manual trigger)
- owner_digest_task (loop check 15min)

DB tables :
- owner_digest_log (guild_id PK, last_sent_at, last_summary_jsonb)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_profile_module = None
_raid_module = None
_webhook_tracker_module = None
_seasonal_module = None
_coin_economy_module = None
_super_owner_id = 0


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    profile_module=None, raid_module=None,
    webhook_tracker_module=None, seasonal_module=None,
    coin_economy_module=None, super_owner_id: int = 0,
):
    global _bot, _get_db, _db_get, _v2
    global _profile_module, _raid_module, _webhook_tracker_module
    global _seasonal_module, _coin_economy_module, _super_owner_id
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _profile_module = profile_module
    _raid_module = raid_module
    _webhook_tracker_module = webhook_tracker_module
    _seasonal_module = seasonal_module
    _coin_economy_module = coin_economy_module
    try:
        _super_owner_id = int(super_owner_id or 0)
    except Exception:
        _super_owner_id = 0


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS owner_digest_log (
                    guild_id INTEGER PRIMARY KEY,
                    last_sent_at TIMESTAMP,
                    last_summary_jsonb TEXT
                )
            """)
            # TASK C.2 : rétro MENSUELLE — anti-doublon par mois ISO (YYYY-MM).
            # PK (guild_id, month_id) → 1 seul envoi par mois et par guilde.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS owner_monthly_log (
                    guild_id INTEGER,
                    month_id TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, month_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[owner_digest init_db] {ex}")


# ─── Data collection ───────────────────────────────────────────────────────

async def _collect_summary(guild: discord.Guild) -> dict:
    """Récolte toutes les stats pour le digest."""
    out = {
        "guild_name": guild.name,
        "member_count": guild.member_count or 0,
        "new_members_24h": [],
        "top_active_24h": [],
        "msgs_24h": 0,
        "voice_minutes_24h": 0,
        "security_alerts": {
            "raid_alerts": 0,
            "phishing_blocked": 0,
            "impersonation": 0,
            "webhook_leaks": 0,
        },
        "inactive_webhooks": 0,
        "season_info": None,
        "saga_active": None,
        "error_summary": None,
    }
    if _get_db is None:
        return out

    try:
        yesterday = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).strftime("%Y-%m-%d %H:%M:%S")

        async with _get_db() as db:
            # Nouveaux membres 24h (depuis raid_join_log si existe)
            try:
                async with db.execute(
                    "SELECT user_id, total_score, account_age_days "
                    "FROM raid_join_log WHERE guild_id=? AND joined_at >= ? "
                    "ORDER BY joined_at DESC LIMIT 20",
                    (guild.id, yesterday),
                ) as cur:
                    rows = await cur.fetchall()
                for r in rows:
                    m = guild.get_member(int(r[0]))
                    if m:
                        out["new_members_24h"].append({
                            "user_id": int(r[0]),
                            "name": m.display_name,
                            "score": int(r[1] or 0),
                            "age_days": int(r[2] or 0),
                        })
            except Exception:
                pass

            # Messages 24h
            try:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                async with db.execute(
                    "SELECT total_messages, vocal_minutes FROM daily_guild_stats "
                    "WHERE guild_id=? AND date=?",
                    (guild.id, today),
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    out["msgs_24h"] = int(row[0] or 0)
                    out["voice_minutes_24h"] = int(row[1] or 0)
            except Exception:
                pass

            # Security alerts 24h
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM raid_alerts "
                    "WHERE guild_id=? AND created_at >= ?",
                    (guild.id, yesterday),
                ) as cur:
                    r = await cur.fetchone()
                    out["security_alerts"]["raid_alerts"] = int(r[0] or 0) if r else 0
            except Exception:
                pass
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM phishing_log "
                    "WHERE guild_id=? AND detected_at >= ?",
                    (guild.id, yesterday),
                ) as cur:
                    r = await cur.fetchone()
                    out["security_alerts"]["phishing_blocked"] = int(r[0] or 0) if r else 0
            except Exception:
                pass
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM impersonation_alerts "
                    "WHERE guild_id=? AND created_at >= ?",
                    (guild.id, yesterday),
                ) as cur:
                    r = await cur.fetchone()
                    out["security_alerts"]["impersonation"] = int(r[0] or 0) if r else 0
            except Exception:
                pass
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM webhook_leak_log "
                    "WHERE guild_id=? AND detected_at >= ?",
                    (guild.id, yesterday),
                ) as cur:
                    r = await cur.fetchone()
                    out["security_alerts"]["webhook_leaks"] = int(r[0] or 0) if r else 0
            except Exception:
                pass

        # Webhooks inactifs (via webhook_tracker si dispo)
        if _webhook_tracker_module is not None:
            try:
                inactive = await _webhook_tracker_module.get_inactive_webhooks(
                    guild.id, days=90,
                )
                out["inactive_webhooks"] = len(inactive)
            except Exception:
                pass

        # Saison active
        if _seasonal_module is not None:
            try:
                season = _seasonal_module.current_season()
                if season:
                    out["season_info"] = {
                        "emoji": season.get("emoji", ""),
                        "name": season.get("name", ""),
                    }
            except Exception:
                pass

        # Saga active
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT title, current_phase, fragments_collected, "
                    "fragments_target FROM sagas "
                    "WHERE guild_id=? AND status='active' "
                    "ORDER BY saga_id DESC LIMIT 1",
                    (guild.id,),
                ) as cur:
                    r = await cur.fetchone()
            if r:
                out["saga_active"] = {
                    "title": r[0],
                    "phase": int(r[1] or 1),
                    "fragments": int(r[2] or 0),
                    "target": int(r[3] or 50),
                }
        except Exception:
            pass

        # Stabilité (24h) — récap erreurs via error_logger (fail-safe)
        try:
            import error_logger as _err
            if _err is not None and hasattr(_err, "get_error_summary"):
                out["error_summary"] = await _err.get_error_summary(hours=24)
        except Exception:
            out["error_summary"] = None

    except Exception as ex:
        print(f"[owner_digest _collect_summary] {ex}")

    return out


# ─── Build panel ───────────────────────────────────────────────────────────

def _build_digest_panel(summary: dict):
    """Panel V2 visuel pour le digest."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    items = []
    items.append(v2_title(f"📰 Récap quotidien — {summary['guild_name']}"))

    # Membres
    new_n = len(summary["new_members_24h"])
    items.append(v2_subtitle(
        f"_Membres : `{summary['member_count']:,}` total · "
        f"+`{new_n}` arrivées 24h_"
    ))
    items.append(v2_divider())

    # Sécurité (en premier — le plus important pour owner)
    sa = summary["security_alerts"]
    total_sec = sum(sa.values())
    if total_sec > 0:
        items.append(v2_body("**🚨 Alertes sécurité (24h)**"))
        if sa["raid_alerts"] > 0:
            items.append(v2_body(
                f"• 🛡️ Raid alerts : **{sa['raid_alerts']}**"
            ))
        if sa["phishing_blocked"] > 0:
            items.append(v2_body(
                f"• 🎣 Phishing bloqués : **{sa['phishing_blocked']}**"
            ))
        if sa["impersonation"] > 0:
            items.append(v2_body(
                f"• 🎭 Impersonation : **{sa['impersonation']}**"
            ))
        if sa["webhook_leaks"] > 0:
            items.append(v2_body(
                f"• 🔌 Webhook leaks : **{sa['webhook_leaks']}**"
            ))
        items.append(v2_divider())
    else:
        items.append(v2_body("✅ **Sécurité** : nuit calme, aucune alerte"))
        items.append(v2_divider())

    # Activité
    items.append(v2_body("**📊 Activité (24h)**"))
    items.append(v2_body(
        f"• 💬 Messages : **{summary['msgs_24h']:,}**\n"
        f"• 🎙️ Minutes voice : **{summary['voice_minutes_24h']:,}**"
    ))
    items.append(v2_divider())

    # Nouveaux membres
    if new_n > 0:
        items.append(v2_body(f"**🆕 Nouveaux membres ({new_n})**"))
        for nm in summary["new_members_24h"][:5]:
            age = nm.get("age_days", 0)
            age_str = f"{age}j" if age < 90 else f"{age // 30}m"
            risk = "⚠️" if nm.get("score", 0) > 6 else "✅"
            items.append(v2_body(
                f"{risk} **{nm['name']}** — compte de **{age_str}**"
            ))
        if new_n > 5:
            items.append(v2_body(f"_+ {new_n - 5} autres…_"))
        items.append(v2_divider())

    # Saison + Saga
    if summary.get("season_info"):
        s = summary["season_info"]
        items.append(v2_body(
            f"**Saison active :** {s['emoji']} {s['name']}"
        ))
    if summary.get("saga_active"):
        sg = summary["saga_active"]
        pct = int(sg["fragments"] * 100 / max(1, sg["target"]))
        items.append(v2_body(
            f"**Saga active :** {sg['title']} — phase {sg['phase']} "
            f"({sg['fragments']}/{sg['target']} fragments · {pct}%)"
        ))

    # Maintenance
    if summary.get("inactive_webhooks", 0) > 0:
        items.append(v2_divider())
        items.append(v2_body(
            f"🔧 **Maintenance :** {summary['inactive_webhooks']} webhooks "
            f"inactifs depuis 90+ jours détectés."
        ))

    # Stabilité (24h) — récap erreurs (fail-safe, n'empêche jamais le digest)
    try:
        es = summary.get("error_summary")
        items.append(v2_divider())
        if not es or int(es.get("total", 0) or 0) <= 0:
            items.append(v2_body("🩺 **Stabilité (24h)**"))
            items.append(v2_body("✅ Aucune erreur remontée (24h)"))
        else:
            total_err = int(es.get("total", 0) or 0)
            items.append(v2_body(
                f"🩺 **Stabilité (24h)** — **{total_err}** erreur(s) capturée(s)"
            ))
            top_src = (es.get("by_source") or [])[:3]
            if top_src:
                src_line = " · ".join(
                    f"`{s.get('source', '?')}` ({int(s.get('count', 0) or 0)})"
                    for s in top_src
                )
                items.append(v2_body(f"• Sources : {src_line}"))
            top_typ = (es.get("by_type") or [])[:3]
            if top_typ:
                typ_line = " · ".join(
                    f"`{t.get('error_type', '?')}` ({int(t.get('count', 0) or 0)})"
                    for t in top_typ
                )
                items.append(v2_body(f"• Types : {typ_line}"))
    except Exception:
        pass

    items.append(v2_divider())
    items.append(v2_body("-# Récap auto chaque jour à 9h FR"))

    class _DigestPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=0x9B59B6))

    return _DigestPanel()


# ─── Send ──────────────────────────────────────────────────────────────────

async def send_now(guild: discord.Guild) -> bool:
    """Envoie le digest au owner. Retourne True si envoyé."""
    if guild is None or _v2 is None:
        return False
    try:
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except Exception:
                return False
        if owner is None:
            return False

        summary = await _collect_summary(guild)
        panel = _build_digest_panel(summary)
        if panel is None:
            return False

        try:
            await owner.send(view=panel)
        except (discord.Forbidden, discord.HTTPException):
            return False

        # Log
        if _get_db is not None:
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO owner_digest_log "
                        "(guild_id, last_sent_at, last_summary_jsonb) "
                        "VALUES (?, CURRENT_TIMESTAMP, ?) "
                        "ON CONFLICT(guild_id) DO UPDATE SET "
                        "last_sent_at = CURRENT_TIMESTAMP, "
                        "last_summary_jsonb = ?",
                        (
                            guild.id, json.dumps(summary, default=str),
                            json.dumps(summary, default=str),
                        ),
                    )
                    await db.commit()
            except Exception:
                pass
        return True
    except Exception as ex:
        print(f"[owner_digest send_now] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# TASK C.2 — RÉTRO MENSUELLE OWNER (DM super-owner, 1×/mois, anti-doublon ISO)
# ═══════════════════════════════════════════════════════════════════════════
# Récap du mois écoulé envoyé au super-owner (DM autorisé — owner uniquement).
# Réutilise les agrégats EXISTANTS : daily_guild_stats (somme du mois), raid_join_log
# (arrivées + rétention), user_stats41 (top events cumulés), coin_economy.get_top_rich,
# error_logger.get_error_summary (fenêtre = mois). FAIL-OPEN, jamais bloquant.

def _prev_month_id(now_dt: datetime) -> str:
    """Renvoie l'ID ISO 'YYYY-MM' du MOIS PRÉCÉDENT (celui qu'on récapitule)."""
    y, m = now_dt.year, now_dt.month
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


async def _collect_monthly_summary(guild: discord.Guild, month_id: str) -> dict:
    """Agrège les stats du mois `month_id` ('YYYY-MM'). Tout fail-safe → 0/[]"""
    out = {
        "guild_name": guild.name,
        "month_id": month_id,
        "member_count": guild.member_count or 0,
        "new_members": 0,
        "left_members": 0,
        "retained": 0,            # arrivants du mois encore présents
        "retention_pct": 0,
        "msgs": 0,
        "voice_minutes": 0,
        "top_events": [],         # [{user_id, value}] (events_won cumulés)
        "top_rich": [],           # [{user_id, total}]
        "error_summary": None,
    }
    if _get_db is None:
        return out
    like = f"{month_id}%"
    try:
        async with _get_db() as db:
            # Activité agrégée du mois (somme daily_guild_stats).
            try:
                async with db.execute(
                    "SELECT COALESCE(SUM(new_members),0), COALESCE(SUM(left_members),0), "
                    "COALESCE(SUM(total_messages),0), COALESCE(SUM(vocal_minutes),0) "
                    "FROM daily_guild_stats WHERE guild_id=? AND date LIKE ?",
                    (guild.id, like),
                ) as cur:
                    r = await cur.fetchone()
                if r:
                    out["new_members"] = int(r[0] or 0)
                    out["left_members"] = int(r[1] or 0)
                    out["msgs"] = int(r[2] or 0)
                    out["voice_minutes"] = int(r[3] or 0)
            except Exception:
                pass

            # Rétention : arrivants du mois encore membres aujourd'hui.
            try:
                async with db.execute(
                    "SELECT user_id FROM raid_join_log "
                    "WHERE guild_id=? AND strftime('%Y-%m', joined_at)=?",
                    (guild.id, month_id),
                ) as cur:
                    joiners = [int(x[0]) for x in await cur.fetchall()]
                if joiners:
                    still = sum(1 for uid in joiners if guild.get_member(uid) is not None)
                    out["retained"] = still
                    out["retention_pct"] = int(still * 100 / max(1, len(joiners)))
                    # raid_join_log est plus fiable que daily_guild_stats pour les arrivées
                    if out["new_members"] <= 0:
                        out["new_members"] = len(joiners)
            except Exception:
                pass

            # Top events (events_won cumulés — agrégat existant, pas de tracking mensuel).
            try:
                async with db.execute(
                    "SELECT user_id, events_won FROM user_stats41 "
                    "WHERE guild_id=? AND events_won > 0 "
                    "ORDER BY events_won DESC LIMIT 5",
                    (guild.id,),
                ) as cur:
                    out["top_events"] = [
                        {"user_id": int(x[0]), "value": int(x[1] or 0)}
                        for x in await cur.fetchall()
                    ]
            except Exception:
                pass

        # Top riches (réutilise coin_economy).
        if _coin_economy_module is not None:
            try:
                out["top_rich"] = await _coin_economy_module.get_top_rich(guild.id, 5)
            except Exception:
                out["top_rich"] = []

        # Erreurs du mois (~31 jours).
        try:
            import error_logger as _err
            if _err is not None and hasattr(_err, "get_error_summary"):
                out["error_summary"] = await _err.get_error_summary(hours=31 * 24)
        except Exception:
            out["error_summary"] = None
    except Exception as ex:
        print(f"[owner_digest _collect_monthly_summary] {ex}")
    return out


def _build_monthly_panel(summary: dict):
    """Panel V2 pour la rétro mensuelle."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    items = []
    items.append(v2_title(f"📅 Rétro du mois — {summary['guild_name']}"))
    items.append(v2_subtitle(f"_Mois {summary['month_id']} · {summary['member_count']:,} membres_"))
    items.append(v2_divider())

    # Croissance + rétention
    net = summary["new_members"] - summary["left_members"]
    sign = "+" if net >= 0 else ""
    items.append(v2_body("**👥 Croissance**"))
    items.append(v2_body(
        f"• Arrivées : **{summary['new_members']}** · Départs : **{summary['left_members']}** "
        f"· Net : **{sign}{net}**\n"
        f"• Rétention des arrivants : **{summary['retention_pct']}%** "
        f"({summary['retained']} encore présents)"
    ))
    items.append(v2_divider())

    # Activité
    items.append(v2_body("**📊 Activité du mois**"))
    items.append(v2_body(
        f"• 💬 Messages : **{summary['msgs']:,}**\n"
        f"• 🎙️ Minutes voice : **{summary['voice_minutes']:,}**"
    ))
    items.append(v2_divider())

    # Top events
    if summary["top_events"]:
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        lines = []
        for idx, e in enumerate(summary["top_events"][:5]):
            lines.append(f"{medals[idx]} <@{e['user_id']}> · {e['value']} victoires")
        items.append(v2_body("**🏆 Top events (cumul)**"))
        items.append(v2_body("\n".join(lines)))
        items.append(v2_divider())

    # Économie
    if summary["top_rich"]:
        lines = []
        for idx, r in enumerate(summary["top_rich"][:5]):
            lines.append(f"{idx + 1}. <@{r['user_id']}> · `{int(r.get('total', 0)):,}` 🪙")
        items.append(v2_body("**💰 Plus riches**"))
        items.append(v2_body("\n".join(lines)))
        items.append(v2_divider())

    # Stabilité du mois
    es = summary.get("error_summary")
    if not es or int(es.get("total", 0) or 0) <= 0:
        items.append(v2_body("🩺 **Stabilité** · ✅ aucune erreur capturée ce mois"))
    else:
        total_err = int(es.get("total", 0) or 0)
        items.append(v2_body(f"🩺 **Stabilité** · **{total_err}** erreur(s) capturée(s)"))
        top_src = (es.get("by_source") or [])[:3]
        if top_src:
            src_line = " · ".join(
                f"`{s.get('source', '?')}` ({int(s.get('count', 0) or 0)})"
                for s in top_src
            )
            items.append(v2_body(f"• Sources : {src_line}"))

    items.append(v2_divider())
    items.append(v2_body("-# Rétro auto le 1er du mois — récap du mois écoulé."))

    class _MonthlyPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=0x5865F2))

    return _MonthlyPanel()


async def _resolve_super_owner_user():
    """Renvoie l'objet User du super-owner (DM autorisé). None si introuvable."""
    if _bot is None or not _super_owner_id:
        return None
    u = _bot.get_user(_super_owner_id)
    if u is not None:
        return u
    try:
        return await _bot.fetch_user(_super_owner_id)
    except Exception:
        return None


async def send_monthly_now(guild: discord.Guild, month_id: str) -> bool:
    """Envoie la rétro mensuelle du `month_id` au super-owner en DM. True si OK."""
    if guild is None or _v2 is None:
        return False
    try:
        owner_user = await _resolve_super_owner_user()
        if owner_user is None:
            return False
        summary = await _collect_monthly_summary(guild, month_id)
        panel = _build_monthly_panel(summary)
        if panel is None:
            return False
        try:
            await owner_user.send(view=panel)
        except (discord.Forbidden, discord.HTTPException):
            return False
        return True
    except Exception as ex:
        print(f"[owner_digest send_monthly_now] {ex}")
        return False


# ─── Task ───────────────────────────────────────────────────────────────────

@tasks.loop(minutes=15)
async def owner_digest_task():
    """Check chaque 15min si on est à 9h FR + pas déjà envoyé aujourd'hui."""
    try:
        if _bot is None:
            return
        if _PARIS_TZ is not None:
            now_paris = datetime.now(_PARIS_TZ)
        else:
            now_paris = datetime.now(timezone.utc) + timedelta(hours=2)

        # ── TASK C.2 : rétro MENSUELLE — le 1er du mois, fenêtre 9h-10h FR.
        # Anti-doublon par mois ISO (PK guild_id+month_id). FAIL-OPEN. On récapitule
        # le MOIS PRÉCÉDENT (complet). Ne bloque jamais le digest quotidien.
        if now_paris.day == 1 and now_paris.hour == 9 and _super_owner_id:
            month_id = _prev_month_id(now_paris)
            for g in list(_bot.guilds):
                try:
                    already = False
                    if _get_db is not None:
                        async with _get_db() as db:
                            async with db.execute(
                                "SELECT 1 FROM owner_monthly_log "
                                "WHERE guild_id=? AND month_id=?",
                                (g.id, month_id),
                            ) as cur:
                                already = (await cur.fetchone()) is not None
                    if already:
                        continue
                    ok_m = await send_monthly_now(g, month_id)
                    if ok_m and _get_db is not None:
                        async with _get_db() as db:
                            await db.execute(
                                "INSERT OR IGNORE INTO owner_monthly_log"
                                "(guild_id, month_id) VALUES (?, ?)",
                                (g.id, month_id),
                            )
                            await db.commit()
                        print(f"[owner_digest] rétro mensuelle {month_id} envoyée guild={g.id}")
                except Exception as ex:
                    print(f"[owner_digest monthly guild={g.id}] {ex}")

        if now_paris.hour != 9:
            return

        # Pour chaque guild, check si pas envoyé aujourd'hui
        for g in _bot.guilds:
            try:
                if _get_db is not None:
                    async with _get_db() as db:
                        async with db.execute(
                            "SELECT last_sent_at FROM owner_digest_log "
                            "WHERE guild_id=?",
                            (g.id,),
                        ) as cur:
                            row = await cur.fetchone()
                    if row and row[0]:
                        try:
                            last = (
                                datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                                if "T" in str(row[0]) else
                                datetime.strptime(
                                    str(row[0]), "%Y-%m-%d %H:%M:%S"
                                ).replace(tzinfo=timezone.utc)
                            )
                            if (datetime.now(timezone.utc) - last).total_seconds() < 23 * 3600:
                                continue  # déjà envoyé aujourd'hui
                        except Exception:
                            pass

                ok = await send_now(g)
                if ok:
                    print(f"[owner_digest] envoye guild={g.id}")
            except Exception as ex:
                print(f"[owner_digest_task guild={g.id}] {ex}")
    except Exception as ex:
        print(f"[owner_digest_task] {ex}")


@owner_digest_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "send_now",
    "send_monthly_now",
    "owner_digest_task",
]
