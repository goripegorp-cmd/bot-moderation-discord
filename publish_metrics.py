"""
publish_metrics.py — Tracking d'engagement + cross-poster (Phase 140).

Trois features publications staff/owner :

1. **TRACKING DES POSTS BOT** — auto via on_message hook
   • Capture chaque post du bot dans les salons "publics" (pas tickets/RO)
   • Suit reactions_total + replies_count (mis à jour 1× par jour)
   • Enable opt-in via /publish track <on|off>

2. **CROSS-POSTER MULTI-SALONS** — groupes de salons préconfigurés
   • Staff crée un groupe (ex: "annonces") + ajoute X salons cibles
   • /publish cross_send <group> <message> → envoie à tous les targets
   • Évite de devoir copier-coller un message dans 5 salons

3. **BEST POST OF WEEK** — leaderboard auto
   • Calcule l'engagement (reactions + replies × 2) sur 7j
   • Top 3 posts présentés dans panel V2

DB tables (créées à la volée) :
- bot_post_tracking   (guild_id, message_id PK, channel_id, posted_at,
                       reactions_total, replies_count, last_metrics_at)
- cross_post_groups   (id, guild_id, name, source_channel_id)
- cross_post_targets  (group_id, target_channel_id) PK composite
- publish_config      (guild_id PK, track_enabled)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers)
- track_message(message) — hook on_message
- refresh_post_metrics(bot, days=7) — task hebdo
- get_best_posts_week(guild_id, limit=3)
- create_group / add_target / remove_target / list_groups / send_to_group
- build_best_posts_panel / build_groups_panel / build_metrics_panel
- Tasks : metrics_refresh_task (hebdo)

⚠️ Conforme RULES.md : zéro relationnel. Pur outil staff/owner.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks


# ─── Configuration ───────────────────────────────────────────────────────
METRICS_REFRESH_HOURS = 24
BEST_POSTS_WINDOW_DAYS = 7
METRICS_MAX_POSTS_REFRESH = 50    # max posts à refresh par run pour limiter API
ENGAGEMENT_REPLY_WEIGHT = 2.0     # une réponse = 2× une réaction


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
            await db.execute('''CREATE TABLE IF NOT EXISTS bot_post_tracking (
                guild_id INTEGER,
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reactions_total INTEGER DEFAULT 0,
                replies_count INTEGER DEFAULT 0,
                last_metrics_at DATETIME
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_bot_post_guild_date "
                "ON bot_post_tracking(guild_id, posted_at DESC)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS cross_post_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                name TEXT,
                source_channel_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_cross_groups_uniq "
                "ON cross_post_groups(guild_id, name)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS cross_post_targets (
                group_id INTEGER,
                target_channel_id INTEGER,
                PRIMARY KEY (group_id, target_channel_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS publish_config (
                guild_id INTEGER PRIMARY KEY,
                track_enabled INTEGER DEFAULT 0
            )''')
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[publish_metrics _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

async def is_tracking_enabled(guild_id: int) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT track_enabled FROM publish_config WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        return bool(row and row[0])
    except Exception:
        return False


async def set_tracking(guild_id: int, enabled: bool) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO publish_config(guild_id, track_enabled) VALUES(?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET track_enabled=excluded.track_enabled",
                (guild_id, 1 if enabled else 0),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[publish_metrics set_tracking] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TRACKING DES POSTS
# ═══════════════════════════════════════════════════════════════════════════════

async def track_message(message: discord.Message):
    """Hook on_message : enregistre un post bot pour tracking futur.

    À appeler depuis l'on_message existant si tracking activé sur ce guild.
    """
    if _get_db is None:
        return
    if not message or not message.author or not message.guild:
        return
    if not message.author.bot:
        return
    if not await is_tracking_enabled(message.guild.id):
        return

    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO bot_post_tracking "
                "(guild_id, message_id, channel_id, reactions_total, replies_count) "
                "VALUES(?, ?, ?, 0, 0)",
                (message.guild.id, message.id, message.channel.id),
            )
            await db.commit()
    except Exception as ex:
        print(f"[publish_metrics track_message] {ex}")


async def refresh_post_metrics(bot_instance) -> int:
    """Refresh les métriques des posts trackés <7 jours.

    Pour chaque post : refetch via fetch_message, compte reactions + threads.
    Retourne le nombre de posts mis à jour.
    """
    if _get_db is None or bot_instance is None:
        return 0
    await _ensure_tables()

    cutoff = (datetime.now(timezone.utc) - timedelta(
        days=BEST_POSTS_WINDOW_DAYS
    )).isoformat()
    updated = 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT message_id, channel_id FROM bot_post_tracking "
                "WHERE posted_at >= ? ORDER BY posted_at DESC LIMIT ?",
                (cutoff, METRICS_MAX_POSTS_REFRESH),
            ) as cur:
                rows = await cur.fetchall()

        for msg_id, ch_id in rows:
            try:
                channel = bot_instance.get_channel(int(ch_id))
                if not isinstance(channel, discord.TextChannel):
                    continue
                msg = await channel.fetch_message(int(msg_id))
                reactions_total = sum(r.count for r in msg.reactions)
                replies_count = 0
                # Compter les replies via thread + via lien direct (best effort)
                if msg.thread:
                    try:
                        replies_count = msg.thread.message_count or 0
                    except Exception:
                        pass

                async with _get_db() as db:
                    await db.execute(
                        "UPDATE bot_post_tracking SET "
                        "reactions_total=?, replies_count=?, "
                        "last_metrics_at=CURRENT_TIMESTAMP WHERE message_id=?",
                        (reactions_total, replies_count, int(msg_id)),
                    )
                    await db.commit()
                updated += 1
            except (discord.NotFound, discord.Forbidden):
                # Message supprimé / inaccessible → cleanup
                try:
                    async with _get_db() as db:
                        await db.execute(
                            "DELETE FROM bot_post_tracking WHERE message_id=?",
                            (int(msg_id),),
                        )
                        await db.commit()
                except Exception:
                    pass
            except Exception as ex:
                print(f"[publish_metrics refresh msg={msg_id}] {ex}")
    except Exception as ex:
        print(f"[publish_metrics refresh_post_metrics] {ex}")

    return updated


async def get_best_posts_week(
    guild_id: int, limit: int = 3
) -> list[dict]:
    """Top posts par score d'engagement sur 7j."""
    if _get_db is None:
        return []
    await _ensure_tables()
    cutoff = (datetime.now(timezone.utc) - timedelta(
        days=BEST_POSTS_WINDOW_DAYS
    )).isoformat()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT message_id, channel_id, posted_at, "
                "reactions_total, replies_count, "
                "(reactions_total + replies_count * ?) AS score "
                "FROM bot_post_tracking "
                "WHERE guild_id=? AND posted_at >= ? "
                "ORDER BY score DESC LIMIT ?",
                (ENGAGEMENT_REPLY_WEIGHT, guild_id, cutoff, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "message_id": int(r[0]),
                "channel_id": int(r[1]),
                "posted_at": r[2],
                "reactions": int(r[3] or 0),
                "replies": int(r[4] or 0),
                "score": float(r[5] or 0),
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[publish_metrics get_best_posts_week] {ex}")
        return []


async def get_post_metrics(message_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, message_id, channel_id, posted_at, "
                "reactions_total, replies_count, last_metrics_at "
                "FROM bot_post_tracking WHERE message_id=?",
                (message_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "guild_id": int(row[0]),
            "message_id": int(row[1]),
            "channel_id": int(row[2]),
            "posted_at": row[3],
            "reactions": int(row[4] or 0),
            "replies": int(row[5] or 0),
            "last_metrics_at": row[6],
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-POSTER
# ═══════════════════════════════════════════════════════════════════════════════

async def create_group(
    guild_id: int, name: str, source_channel_id: int = 0
) -> tuple[bool, int | str]:
    """Crée un nouveau groupe de cross-post."""
    if _get_db is None:
        return False, "Module non initialisé."
    name = (name or "").strip().lower()
    if not name or len(name) > 50:
        return False, "Nom invalide (1-50 chars, sans espaces)."

    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO cross_post_groups(guild_id, name, source_channel_id) "
                "VALUES(?, ?, ?)",
                (guild_id, name, source_channel_id),
            )
            gid = cur.lastrowid
            await db.commit()
        return True, int(gid or 0)
    except Exception as ex:
        msg = str(ex).lower()
        if "unique" in msg:
            return False, f"Un groupe `{name}` existe déjà."
        print(f"[publish_metrics create_group] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def add_target(group_id: int, target_channel_id: int) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO cross_post_targets"
                "(group_id, target_channel_id) VALUES(?, ?)",
                (group_id, target_channel_id),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[publish_metrics add_target] {ex}")
        return False


async def remove_target(group_id: int, target_channel_id: int) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM cross_post_targets "
                "WHERE group_id=? AND target_channel_id=?",
                (group_id, target_channel_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception:
        return False


async def delete_group(group_id: int) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM cross_post_targets WHERE group_id=?",
                (group_id,),
            )
            cur = await db.execute(
                "DELETE FROM cross_post_groups WHERE id=?", (group_id,)
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception:
        return False


async def list_groups(guild_id: int) -> list[dict]:
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT g.id, g.name, g.source_channel_id, "
                "(SELECT COUNT(*) FROM cross_post_targets t "
                " WHERE t.group_id = g.id) AS target_count "
                "FROM cross_post_groups g WHERE g.guild_id=? "
                "ORDER BY g.name",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": int(r[0]),
                "name": r[1] or "",
                "source_channel_id": int(r[2] or 0),
                "target_count": int(r[3] or 0),
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[publish_metrics list_groups] {ex}")
        return []


async def get_group_by_name(guild_id: int, name: str) -> Optional[dict]:
    if _get_db is None:
        return None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, name, source_channel_id FROM cross_post_groups "
                "WHERE guild_id=? AND name=?",
                (guild_id, (name or "").strip().lower()),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "name": row[1] or "",
            "source_channel_id": int(row[2] or 0),
        }
    except Exception:
        return None


async def get_group_targets(group_id: int) -> list[int]:
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT target_channel_id FROM cross_post_targets "
                "WHERE group_id=?",
                (group_id,),
            ) as cur:
                return [int(r[0]) for r in await cur.fetchall() if r[0]]
    except Exception:
        return []


async def send_to_group(
    bot_instance, guild: discord.Guild, group_id: int, content: str
) -> tuple[int, int]:
    """Envoie `content` à tous les target channels du groupe.

    Retourne (succès, total).
    """
    if not guild or not bot_instance:
        return 0, 0
    targets = await get_group_targets(group_id)
    if not targets:
        return 0, 0
    success = 0
    for ch_id in targets:
        ch = guild.get_channel(int(ch_id))
        if not isinstance(ch, discord.TextChannel):
            continue
        try:
            await ch.send(content)
            success += 1
        except (discord.Forbidden, discord.HTTPException) as ex:
            print(f"[publish_metrics send_to_group ch={ch_id}] {ex}")
    return success, len(targets)


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panels V2
# ═══════════════════════════════════════════════════════════════════════════════

def _format_short_dt(dt_str) -> str:
    """Format ISO date → 'YYYY-MM-DD'."""
    if not dt_str:
        return "?"
    try:
        return str(dt_str).split("T")[0]
    except Exception:
        return str(dt_str)


def build_best_posts_panel(
    posts: list[dict], guild_name: str = "",
    bot_instance=None,
):
    """Panel V2 — best posts of the week (top 3 par engagement)."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _BestPostsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("🏆 Best posts"))
            items.append(v2_subtitle(
                f"Plus d'engagement sur 7j · {guild_name}"
            ))
            items.append(v2_divider())

            if not posts:
                items.append(v2_body(
                    "_Aucun post tracké pour l'instant._"
                ))
            else:
                medals = ["🥇", "🥈", "🥉"]
                lines = []
                for idx, p in enumerate(posts[:3]):
                    medal = medals[idx] if idx < 3 else "▪️"
                    link = ""
                    if bot_instance:
                        try:
                            ch = bot_instance.get_channel(p["channel_id"])
                            if ch and hasattr(ch, "guild"):
                                link = (
                                    f"https://discord.com/channels/"
                                    f"{ch.guild.id}/{p['channel_id']}/"
                                    f"{p['message_id']}"
                                )
                        except Exception:
                            pass
                    line = (
                        f"{medal} **Score `{int(p['score'])}`** · "
                        f"💬 `{p['replies']}` · 👍 `{p['reactions']}` · "
                        f"📅 {_format_short_dt(p['posted_at'])} · "
                        f"<#{p['channel_id']}>"
                    )
                    if link:
                        line += f" · [lien]({link})"
                    lines.append(line)
                items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                f"-# Score = reactions + replies × {int(ENGAGEMENT_REPLY_WEIGHT)} · refresh 24h"
            ))

            self.add_item(v2_container(*items, color=0xF1C40F))

    return _BestPostsPanel()


def build_groups_panel(groups: list[dict], guild_name: str = ""):
    """Panel V2 — liste des groupes de cross-post."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _GroupsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("📢 Cross-post"))
            items.append(v2_subtitle(
                f"Groupes de salons configurés · {guild_name}"
            ))
            items.append(v2_divider())

            if not groups:
                items.append(v2_body(
                    "_Aucun groupe configuré pour l'instant._"
                ))
            else:
                lines = []
                for g in groups:
                    lines.append(
                        f"📢 **`{g['name']}`** · id `{g['id']}` · "
                        f"_{g['target_count']} salon(s)_"
                    )
                items.append(v2_body("\n".join(lines)))

            self.add_item(v2_container(*items, color=0x3498DB))

    return _GroupsPanel()


def build_metrics_panel(post: dict, guild_name: str = ""):
    """Panel V2 — métriques détaillées d'un post tracké."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    score = post["reactions"] + post["replies"] * ENGAGEMENT_REPLY_WEIGHT

    class _MetricsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("📊 Métriques post"))
            items.append(v2_subtitle(
                f"Engagement du post `{post['message_id']}`"
            ))
            items.append(v2_divider())

            items.append(v2_body(
                f"📅 **Posté** `{post['posted_at']}` · "
                f"📍 <#{post['channel_id']}> · "
                f"🔄 **Refresh** `{post.get('last_metrics_at', 'jamais')}`"
            ))
            items.append(v2_divider())

            items.append(v2_body(
                f"👍 **Reactions** `{post['reactions']}` · "
                f"💬 **Replies** `{post['replies']}` · "
                f"🏆 **Score** `{int(score)}`"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "-# Score = reactions + replies × 2 · refresh 24h"
            ))

            self.add_item(v2_container(*items, color=0xF1C40F))

    return _MetricsPanel()


# ═══════════════════════════════════════════════════════════════════════════════
# TASK PROGRAMMÉE — refresh métriques toutes les 24h
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=METRICS_REFRESH_HOURS)
async def metrics_refresh_task():
    """Tourne chaque 24h — refresh les métriques de tous les posts trackés."""
    try:
        if _bot is None:
            return
        updated = await refresh_post_metrics(_bot)
        if updated > 0:
            print(f"✅ [publish_metrics] refreshed {updated} post(s)")
    except Exception as ex:
        print(f"[publish_metrics metrics_refresh_task] {ex}")


@metrics_refresh_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    # Config
    "is_tracking_enabled", "set_tracking",
    # Tracking
    "track_message", "refresh_post_metrics",
    "get_best_posts_week", "get_post_metrics",
    # Cross-post
    "create_group", "add_target", "remove_target", "delete_group",
    "list_groups", "get_group_by_name", "get_group_targets", "send_to_group",
    # Panels
    "build_best_posts_panel", "build_groups_panel", "build_metrics_panel",
    # Task
    "metrics_refresh_task",
]
