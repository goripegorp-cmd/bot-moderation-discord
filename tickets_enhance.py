"""
tickets_enhance.py — Améliorations du système tickets (Phase 138).

Complète le système ticket existant (table `tickets` schema : id, guild_id,
channel_id, user_id, panel_id, claimed_by, status, answers, created_at) avec :

1. **PRIORITÉS** : urgent / high / normal / low — set via slash, badge dans
   le nom du salon ticket (préfixe emoji)

2. **TEMPLATES DE RÉPONSES** : staff définit des réponses pré-rédigées
   ("Règle 5", "Ban Appeal", "Voir vidéo"), peut les invoquer en 1 commande

3. **AUTO-CLOSE INACTIVITÉ** : task quotidienne qui ferme les tickets sans
   activité (configurable par guild, défaut 7 jours sans message)

4. **STATS DASHBOARD** : staff voit avg temps de résolution, top staff,
   distribution open/closed, tickets actifs sans claim, etc.

DB tables (créées à la volée) :
- ticket_extras            (channel_id PK, priority, last_activity_at, closed_at, claimed_at)
- ticket_response_templates (id, guild_id, name, content, added_by, created_at)
- ticket_auto_close_config  (guild_id PK, inactivity_days)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers)
- set_priority(channel_id, priority) -> bool
- get_priority(channel_id) -> str
- touch_activity(channel_id) — update last_activity_at (hook on_message)
- add_template / get_template / list_templates / delete_template
- set_inactivity_days(guild_id, days) / get_inactivity_days(guild_id)
- collect_ticket_stats(guild_id) -> dict
- build_stats_panel / build_templates_panel
- auto_close_inactive_task (tasks.loop quotidienne)

⚠️ Conforme RULES.md : zéro feature relationnelle. Pur outil staff/gestion.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks


# ─── Configuration ───────────────────────────────────────────────────────
PRIORITY_LEVELS = {
    "urgent": ("🔴", "URGENT"),
    "high":   ("🟠", "HAUTE"),
    "normal": ("🟡", "NORMALE"),
    "low":    ("🔵", "BASSE"),
}
DEFAULT_INACTIVITY_DAYS = 7
AUTO_CLOSE_CHECK_HOURS = 24
# Phase 245 : rappel SLA — un ticket OUVERT et NON PRIS EN CHARGE depuis ce délai
# déclenche UN rappel staff (un seul, jamais de spam). Vérification toutes les 2 h.
SLA_UNCLAIMED_HOURS = 24


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
            await db.execute('''CREATE TABLE IF NOT EXISTS ticket_extras (
                channel_id INTEGER PRIMARY KEY,
                priority TEXT DEFAULT 'normal',
                last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME,
                claimed_at DATETIME
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_extras_activity "
                "ON ticket_extras(last_activity_at)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS ticket_response_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                name TEXT,
                content TEXT,
                added_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_ticket_templates_uniq "
                "ON ticket_response_templates(guild_id, name)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS ticket_auto_close_config (
                guild_id INTEGER PRIMARY KEY,
                inactivity_days INTEGER DEFAULT 7
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS ticket_sla_reminded (
                channel_id INTEGER PRIMARY KEY,
                reminded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[tickets_enhance _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# PRIORITÉS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_priority(channel_id: int) -> str:
    if _get_db is None:
        return "normal"
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT priority FROM ticket_extras WHERE channel_id=?",
                (channel_id,),
            ) as cur:
                row = await cur.fetchone()
        return (row[0] if row and row[0] else "normal")
    except Exception:
        return "normal"


async def set_priority(channel_id: int, priority: str) -> bool:
    """Set la priorité d'un ticket (one of: urgent/high/normal/low)."""
    if _get_db is None or priority not in PRIORITY_LEVELS:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO ticket_extras(channel_id, priority) VALUES(?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET priority=excluded.priority",
                (channel_id, priority),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[tickets_enhance set_priority] {ex}")
        return False


async def update_channel_name_for_priority(
    channel: discord.TextChannel, priority: str
) -> bool:
    """Modifie le nom du channel pour refléter la priorité (préfixe emoji)."""
    if not channel or priority not in PRIORITY_LEVELS:
        return False
    emoji, _ = PRIORITY_LEVELS[priority]
    try:
        name = channel.name
        # Strip ancien préfixe priorité (s'il y en a un)
        for em, _ in PRIORITY_LEVELS.values():
            if name.startswith(em):
                name = name[len(em):].lstrip("-_ ")
                break
        new_name = f"{emoji}-{name}"[:100]
        if new_name == channel.name:
            return True
        await channel.edit(name=new_name, reason="Ticket priority change")
        return True
    except (discord.Forbidden, discord.HTTPException) as ex:
        print(f"[tickets_enhance update_channel_name] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVITÉ — pour auto-close
# ═══════════════════════════════════════════════════════════════════════════════

async def touch_activity(channel_id: int):
    """Met à jour last_activity_at d'un ticket. À call depuis on_message."""
    if _get_db is None:
        return
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO ticket_extras(channel_id, last_activity_at) "
                "VALUES(?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "last_activity_at=CURRENT_TIMESTAMP",
                (channel_id,),
            )
            await db.commit()
    except Exception:
        pass


async def mark_claimed(channel_id: int):
    """Marque le ticket comme claim (au moment du claim staff)."""
    if _get_db is None:
        return
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO ticket_extras(channel_id, claimed_at) "
                "VALUES(?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "claimed_at=COALESCE(claimed_at, CURRENT_TIMESTAMP)",
                (channel_id,),
            )
            await db.commit()
    except Exception:
        pass


async def mark_closed(channel_id: int):
    """Marque le ticket comme fermé (au moment du close staff)."""
    if _get_db is None:
        return
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO ticket_extras(channel_id, closed_at) "
                "VALUES(?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "closed_at=CURRENT_TIMESTAMP",
                (channel_id,),
            )
            await db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPLATES — réponses pré-rédigées staff
# ═══════════════════════════════════════════════════════════════════════════════

async def add_template(
    guild_id: int, added_by: int, name: str, content: str
) -> tuple[bool, str]:
    """Crée ou remplace un template. Retourne (ok, msg)."""
    if _get_db is None:
        return False, "Module non initialisé."
    name = (name or "").strip().lower()
    content = (content or "").strip()
    if not name or not content:
        return False, "Nom et contenu requis."
    if len(name) > 50:
        return False, "Nom trop long (max 50 chars)."
    if len(content) > 1800:
        return False, "Contenu trop long (max 1800 chars)."

    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM ticket_response_templates "
                "WHERE guild_id=? AND name=?",
                (guild_id, name),
            ) as cur:
                row = await cur.fetchone()
            if row:
                await db.execute(
                    "UPDATE ticket_response_templates SET content=?, added_by=? "
                    "WHERE id=?",
                    (content, added_by, int(row[0])),
                )
                msg = f"Template `{name}` mis à jour."
            else:
                await db.execute(
                    "INSERT INTO ticket_response_templates"
                    "(guild_id, name, content, added_by) VALUES(?, ?, ?, ?)",
                    (guild_id, name, content, added_by),
                )
                msg = f"Template `{name}` créé."
            await db.commit()
        return True, msg
    except Exception as ex:
        print(f"[tickets_enhance add_template] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def get_template(guild_id: int, name: str) -> Optional[dict]:
    if _get_db is None:
        return None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, name, content, added_by FROM ticket_response_templates "
                "WHERE guild_id=? AND name=?",
                (guild_id, (name or "").strip().lower()),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "name": row[1],
            "content": row[2],
            "added_by": int(row[3] or 0),
        }
    except Exception:
        return None


async def list_templates(guild_id: int) -> list[dict]:
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, name, content, added_by FROM ticket_response_templates "
                "WHERE guild_id=? ORDER BY name",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"id": int(r[0]), "name": r[1], "content": r[2],
             "added_by": int(r[3] or 0)}
            for r in rows
        ]
    except Exception as ex:
        print(f"[tickets_enhance list_templates] {ex}")
        return []


async def delete_template(guild_id: int, name: str) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM ticket_response_templates "
                "WHERE guild_id=? AND name=?",
                (guild_id, (name or "").strip().lower()),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-CLOSE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

async def get_inactivity_days(guild_id: int) -> int:
    if _get_db is None:
        return DEFAULT_INACTIVITY_DAYS
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT inactivity_days FROM ticket_auto_close_config "
                "WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row and row[0] else DEFAULT_INACTIVITY_DAYS
    except Exception:
        return DEFAULT_INACTIVITY_DAYS


async def set_inactivity_days(guild_id: int, days: int) -> bool:
    if _get_db is None:
        return False
    d = max(1, min(90, int(days or DEFAULT_INACTIVITY_DAYS)))
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO ticket_auto_close_config(guild_id, inactivity_days) "
                "VALUES(?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET inactivity_days=excluded.inactivity_days",
                (guild_id, d),
            )
            await db.commit()
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════════════

async def collect_ticket_stats(guild_id: int) -> dict:
    """Aggrège les stats des tickets du serveur."""
    out = {
        "total": 0,
        "open": 0,
        "closed": 0,
        "unclaimed": 0,
        "by_priority": {},
        "top_staff": [],
        "avg_resolution_hours": 0,
        "recent_7d": 0,
    }
    if _get_db is None:
        return out
    await _ensure_tables()
    try:
        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        async with _get_db() as db:
            # Total + status
            async with db.execute(
                "SELECT status, COUNT(*) FROM tickets WHERE guild_id=? "
                "GROUP BY status",
                (guild_id,),
            ) as cur:
                for status, cnt in await cur.fetchall():
                    out["total"] += int(cnt or 0)
                    if status == "open":
                        out["open"] = int(cnt or 0)
                    elif status == "closed":
                        out["closed"] = int(cnt or 0)

            # Unclaimed open
            async with db.execute(
                "SELECT COUNT(*) FROM tickets "
                "WHERE guild_id=? AND status='open' AND claimed_by=0",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
            out["unclaimed"] = int(row[0] or 0) if row else 0

            # 7d
            async with db.execute(
                "SELECT COUNT(*) FROM tickets "
                "WHERE guild_id=? AND created_at >= ?",
                (guild_id, cutoff_7d),
            ) as cur:
                row = await cur.fetchone()
            out["recent_7d"] = int(row[0] or 0) if row else 0

            # Top staff (claimed_by)
            async with db.execute(
                "SELECT claimed_by, COUNT(*) FROM tickets "
                "WHERE guild_id=? AND claimed_by != 0 "
                "GROUP BY claimed_by ORDER BY COUNT(*) DESC LIMIT 5",
                (guild_id,),
            ) as cur:
                out["top_staff"] = [
                    {"user_id": int(r[0]), "count": int(r[1])}
                    for r in await cur.fetchall()
                ]

            # Distribution par priorité
            async with db.execute(
                "SELECT te.priority, COUNT(*) FROM tickets t "
                "JOIN ticket_extras te ON te.channel_id = t.channel_id "
                "WHERE t.guild_id=? AND t.status='open' "
                "GROUP BY te.priority",
                (guild_id,),
            ) as cur:
                for prio, cnt in await cur.fetchall():
                    out["by_priority"][prio or "normal"] = int(cnt or 0)

            # Avg resolution time (closed_at - created_at)
            try:
                async with db.execute(
                    "SELECT AVG((julianday(te.closed_at) - julianday(t.created_at)) * 24) "
                    "FROM tickets t JOIN ticket_extras te ON te.channel_id = t.channel_id "
                    "WHERE t.guild_id=? AND t.status='closed' AND te.closed_at IS NOT NULL",
                    (guild_id,),
                ) as cur:
                    row = await cur.fetchone()
                out["avg_resolution_hours"] = round(float(row[0] or 0), 1) if row else 0
            except Exception:
                pass
    except Exception as ex:
        print(f"[tickets_enhance collect_ticket_stats] {ex}")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panels V2
# ═══════════════════════════════════════════════════════════════════════════════

def build_templates_panel(templates: list, guild_name: str = ""):
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _TemplatesPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("📋  TEMPLATES DE RÉPONSE"))
            items.append(v2_subtitle(
                f"_Réponses pré-rédigées du staff ({len(templates)})_"
            ))
            items.append(v2_divider())

            if not templates:
                items.append(v2_body(
                    "_Aucun template. Staff peut en créer avec "
                    "`/ticket template_add`._"
                ))
            else:
                lines = []
                for t in templates[:20]:
                    preview = t["content"][:80].replace("\n", " ")
                    if len(t["content"]) > 80:
                        preview += "…"
                    lines.append(
                        f"📝 **`{t['name']}`** _(par <@{t['added_by']}>)_\n"
                        f"   _{preview}_"
                    )
                items.append(v2_body("\n\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/ticket reply <name>` pour utiliser un template "
                "dans un ticket._"
            ))

            self.add_item(v2_container(*items, color=0x3498DB))

    return _TemplatesPanel()


def build_stats_panel(stats: dict, guild_name: str = ""):
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _StatsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("📊  DASHBOARD TICKETS"))
            items.append(v2_subtitle(
                f"_Statistiques du système ticket — {guild_name}_"
            ))
            items.append(v2_divider())

            # Overview
            items.append(v2_body("### 📋 ÉTAT GLOBAL"))
            items.append(v2_body(
                f"📊 **Total :** `{stats['total']}`\n"
                f"🟢 **Ouverts :** `{stats['open']}`\n"
                f"🔒 **Fermés :** `{stats['closed']}`\n"
                f"⚠️ **Sans claim :** `{stats['unclaimed']}`\n"
                f"📅 **Nouveaux 7j :** `{stats['recent_7d']}`"
            ))

            # Priorité distribution
            if stats["by_priority"]:
                items.append(v2_divider())
                items.append(v2_body("### 🚨 PAR PRIORITÉ (ouverts)"))
                lines = []
                for prio, cnt in sorted(
                    stats["by_priority"].items(),
                    key=lambda x: ["urgent", "high", "normal", "low"].index(x[0])
                    if x[0] in ("urgent", "high", "normal", "low") else 99,
                ):
                    emoji, label = PRIORITY_LEVELS.get(prio, ("⚪", prio.upper()))
                    lines.append(f"{emoji} **{label}** : `{cnt}`")
                items.append(v2_body("\n".join(lines)))

            # Avg resolution
            if stats["avg_resolution_hours"] > 0:
                items.append(v2_divider())
                items.append(v2_body("### ⏱️ TEMPS DE RÉSOLUTION"))
                avg_h = stats["avg_resolution_hours"]
                if avg_h < 1:
                    avg_str = f"`{int(avg_h * 60)}` min"
                elif avg_h < 24:
                    avg_str = f"`{avg_h}` heures"
                else:
                    avg_str = f"`{avg_h / 24:.1f}` jours"
                items.append(v2_body(f"📈 **Moyenne :** {avg_str}"))

            # Top staff
            if stats["top_staff"]:
                items.append(v2_divider())
                items.append(v2_body("### 🛡️ TOP STAFF"))
                medals = ["🥇", "🥈", "🥉", "▪️", "▪️"]
                lines = []
                for idx, s in enumerate(stats["top_staff"][:5]):
                    medal = medals[idx] if idx < 5 else "▪️"
                    lines.append(
                        f"{medal} <@{s['user_id']}> · `{s['count']}` claim(s)"
                    )
                items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/ticket priority <level>` dans un ticket pour le tagger._"
            ))

            self.add_item(v2_container(*items, color=0x9B59B6))

    return _StatsPanel()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-CLOSE TASK — quotidienne
# ═══════════════════════════════════════════════════════════════════════════════

async def _try_close_channel(channel_id: int):
    """Tente de fermer un ticket inactif (DB + channel)."""
    if _bot is None or _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE tickets SET status='closed' WHERE channel_id=?",
                (channel_id,),
            )
            await db.commit()
        await mark_closed(channel_id)

        # Tente d'envoyer un message dans le ticket + archive
        ch = _bot.get_channel(channel_id)
        if isinstance(ch, discord.TextChannel):
            try:
                await ch.send(
                    "🔒 **Auto-close** : ce ticket est fermé pour cause "
                    "d'inactivité. Si tu as encore besoin d'aide, "
                    "ouvre un nouveau ticket."
                )
            except Exception:
                pass
            # Optionnel : delete après quelques min (laissé à la charge de l'admin)
        return True
    except Exception as ex:
        print(f"[tickets_enhance _try_close_channel] {ex}")
        return False


@tasks.loop(hours=AUTO_CLOSE_CHECK_HOURS)
async def auto_close_inactive_task():
    """DÉSACTIVÉ (directive owner) : le bot ne ferme JAMAIS un ticket pour inactivité.
    Les tickets peuvent rester ouverts aussi longtemps que nécessaire — c'est VOULU.
    Boucle conservée en no-op (références boot/historique préservées, zéro risque de
    NameError) ; elle n'est même plus lancée au boot. Le SEUL rappel automatique sur
    les tickets = `sla_reminder_task` (ping staff sur un ticket NON PRIS EN CHARGE).
    La fermeture reste 100 % MANUELLE (bouton 🔒 par le staff)."""
    return


@auto_close_inactive_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════════
# SLA — rappel staff sur les tickets non pris en charge (Phase 245)
# ═══════════════════════════════════════════════════════════════════════════════

async def _mark_sla_reminded(channel_id: int):
    """Marque un ticket comme « rappel SLA envoyé » (1 seule fois → jamais de spam)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO ticket_sla_reminded(channel_id, reminded_at) "
                "VALUES(?, CURRENT_TIMESTAMP) ON CONFLICT(channel_id) DO NOTHING",
                (int(channel_id),),
            )
            await db.commit()
    except Exception:
        pass


@tasks.loop(hours=2)
async def sla_reminder_task():
    """Toutes les 2 h : poste UN rappel dans les tickets OUVERTS et NON PRIS EN
    CHARGE (claimed_by vide) depuis plus de SLA_UNCLAIMED_HOURS. Ping le rôle
    staff (ticket_staff) s'il est configuré. 1 rappel max par ticket. FAIL-OPEN :
    une erreur par guild/ticket ne casse jamais le loop."""
    if _bot is None or _get_db is None:
        return
    try:
        await _ensure_tables()
        # FIX audit : format ALIGNÉ sur SQLite CURRENT_TIMESTAMP (cf. auto_close)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=SLA_UNCLAIMED_HOURS)
        ).strftime('%Y-%m-%d %H:%M:%S')
        for guild in list(_bot.guilds):
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT t.channel_id FROM tickets t "
                        "LEFT JOIN ticket_sla_reminded r ON r.channel_id = t.channel_id "
                        "WHERE t.guild_id=? AND t.status='open' "
                        "AND (t.claimed_by IS NULL OR t.claimed_by=0) "
                        "AND t.created_at < ? AND r.channel_id IS NULL "
                        "LIMIT 25",
                        (guild.id, cutoff),
                    ) as cur:
                        rows = await cur.fetchall()
                if not rows:
                    continue
                # Rôle staff à mentionner (best-effort ; sans ping si non configuré).
                staff_mention = ""
                try:
                    if _db_get is not None:
                        # FIX audit : db_get prend 1 SEUL arg et renvoie le dict de
                        # config (db_set en prend 3, pas db_get) → l'appel 3-args
                        # levait un TypeError silencieux et le staff n'était JAMAIS ping.
                        rid = (await _db_get(guild.id) or {}).get('ticket_staff', 0)
                        role = guild.get_role(int(rid)) if rid else None
                        if role:
                            staff_mention = role.mention + " "
                except Exception:
                    staff_mention = ""
                for (ch_id,) in rows:
                    ch = _bot.get_channel(int(ch_id))
                    if not isinstance(ch, discord.TextChannel):
                        # Salon disparu → on marque quand même pour ne pas reboucler.
                        await _mark_sla_reminded(int(ch_id))
                        continue
                    try:
                        await ch.send(
                            f"⏰ {staff_mention}**Ticket en attente** — ouvert depuis plus de "
                            f"`{SLA_UNCLAIMED_HOURS}h` **sans prise en charge**. Un membre du "
                            f"staff peut le **réclamer** pour s'en occuper. 🙏",
                            allowed_mentions=discord.AllowedMentions(roles=True),
                        )
                    except Exception:
                        pass
                    await _mark_sla_reminded(int(ch_id))
            except Exception as ex:
                print(f"[tickets_enhance sla guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[tickets_enhance sla_reminder_task] {ex}")


@sla_reminder_task.before_loop
async def _sla_before():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    # Priorities
    "PRIORITY_LEVELS",
    "get_priority", "set_priority", "update_channel_name_for_priority",
    # Activity
    "touch_activity", "mark_claimed", "mark_closed",
    # Templates
    "add_template", "get_template", "list_templates", "delete_template",
    # Auto-close
    "get_inactivity_days", "set_inactivity_days", "auto_close_inactive_task",
    # Stats
    "collect_ticket_stats",
    # Panels
    "build_templates_panel", "build_stats_panel",
]
