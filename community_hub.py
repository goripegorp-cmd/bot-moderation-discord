"""
community_hub.py — Wiki + Roadmap + Highlights (Phase 134).

Trois features communauté regroupées en un module :

1. **WIKI / FAQ** — base de connaissances persistante
   • Staff ajoute des entrées (Q&A, règles, tutos)
   • Tous les membres peuvent chercher / lire
   • Compteur de vues pour identifier les FAQ utiles

2. **ROADMAP / SUGGESTIONS** — vote communautaire sur features
   • Tous les membres peuvent proposer
   • Tous votent (👍 / 👎)
   • Owner change le status (planned / done / rejected)
   • Top items affichés par score net

3. **WEEKLY HIGHLIGHTS** — post auto chaque dimanche 22h FR
   • Top 3 chatters (messages cumulés)
   • Top 3 vocaux (voice min cumulés)
   • Top 3 events winners
   • Posté dans hub_channel avec anti-doublon

DB tables (créées à la volée) :
- wiki_entries     (id, guild_id, slug, title, content, author_id, views, …)
- roadmap_items    (id, guild_id, user_id, title, description, status, …)
- roadmap_votes    (item_id, user_id, vote_value)  # +1 ou -1
- highlights_log   (guild_id, week_id, posted_at)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers)
- Wiki   : add_wiki_entry / get_wiki_entry / search_wiki /
           list_wiki_entries / delete_wiki_entry
- Roadmap: create_roadmap_item / vote_roadmap_item /
           get_roadmap_items / set_roadmap_status / delete_roadmap_item
- Panels : build_wiki_entry_panel / build_wiki_list_panel / build_roadmap_panel
- Task   : weekly_highlights_task (Sunday 22h FR)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# Configuration
HIGHLIGHTS_POST_HOUR = 22       # 22h Europe/Paris
HIGHLIGHTS_POST_WEEKDAY = 6     # dimanche
ROADMAP_TOP_LIMIT = 10
WIKI_SEARCH_LIMIT = 10
HIGHLIGHTS_TOP_PER_CATEGORY = 3


# Statuts roadmap valides
ROADMAP_STATUSES = {
    "open":        ("⏳", "Ouvert"),
    "planned":     ("📌", "Planifié"),
    "in_progress": ("🔨", "En cours"),
    "done":        ("✅", "Terminé"),
    "rejected":    ("❌", "Rejeté"),
}


# Références injectées
_bot = None
_get_db = None
_db_get = None
_db_set = None
_v2_helpers = None


def setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers: dict):
    """Configure le module."""
    global _bot, _get_db, _db_get, _db_set, _v2_helpers
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _db_set = db_set_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Création des tables
# ═══════════════════════════════════════════════════════════════════════════════

_tables_initialized = False


async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS wiki_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                slug TEXT,
                title TEXT,
                content TEXT,
                author_id INTEGER,
                views INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_wiki_guild_slug "
                "ON wiki_entries(guild_id, slug)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS roadmap_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                title TEXT,
                description TEXT,
                status TEXT DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_roadmap_guild_status "
                "ON roadmap_items(guild_id, status, created_at DESC)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS roadmap_votes (
                item_id INTEGER,
                user_id INTEGER,
                vote_value INTEGER,           -- +1 (up) ou -1 (down)
                voted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (item_id, user_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS highlights_log (
                guild_id INTEGER,
                week_id TEXT,
                posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, week_id)
            )''')
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[community_hub _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# WIKI / FAQ
# ═══════════════════════════════════════════════════════════════════════════════

def _slugify(title: str) -> str:
    """Convertit un titre en slug url-friendly."""
    s = (title or "").lower().strip()
    keep = []
    for c in s:
        if c.isalnum():
            keep.append(c)
        elif c in (" ", "-", "_"):
            keep.append("-")
    out = "".join(keep).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:50] or "entry"


async def add_wiki_entry(
    guild_id: int, author_id: int, title: str, content: str
) -> tuple[bool, str]:
    """Crée ou met à jour une entrée wiki. Retourne (ok, message)."""
    if _get_db is None:
        return False, "Module non initialisé."
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        return False, "Titre et contenu requis."
    if len(title) > 100:
        return False, "Titre trop long (max 100 chars)."
    if len(content) > 1800:
        return False, "Contenu trop long (max 1800 chars)."

    await _ensure_tables()
    slug = _slugify(title)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM wiki_entries WHERE guild_id=? AND slug=?",
                (guild_id, slug),
            ) as cur:
                row = await cur.fetchone()
            if row:
                await db.execute(
                    "UPDATE wiki_entries SET title=?, content=?, author_id=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (title, content, author_id, int(row[0])),
                )
                msg = f"Entrée `{slug}` mise à jour."
            else:
                await db.execute(
                    "INSERT INTO wiki_entries(guild_id, slug, title, content, author_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (guild_id, slug, title, content, author_id),
                )
                msg = f"Entrée `{slug}` créée."
            await db.commit()
        return True, msg
    except Exception as ex:
        print(f"[community_hub add_wiki_entry] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def get_wiki_entry(guild_id: int, slug_or_title: str) -> Optional[dict]:
    """Récupère une entrée par slug ou par titre exact. Incrémente views."""
    if _get_db is None:
        return None
    await _ensure_tables()
    slug = _slugify(slug_or_title)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, slug, title, content, author_id, views, created_at, updated_at "
                "FROM wiki_entries WHERE guild_id=? AND "
                "(slug=? OR LOWER(title)=LOWER(?))",
                (guild_id, slug, slug_or_title),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return None
            await db.execute(
                "UPDATE wiki_entries SET views=views+1 WHERE id=?", (int(row[0]),)
            )
            await db.commit()
        return {
            "id": int(row[0]),
            "slug": row[1],
            "title": row[2],
            "content": row[3],
            "author_id": int(row[4] or 0),
            "views": int(row[5] or 0) + 1,
            "created_at": row[6],
            "updated_at": row[7],
        }
    except Exception as ex:
        print(f"[community_hub get_wiki_entry] {ex}")
        return None


async def search_wiki(
    guild_id: int, query: str, limit: int = WIKI_SEARCH_LIMIT
) -> list[dict]:
    """Recherche dans titre + contenu (LIKE)."""
    if _get_db is None:
        return []
    await _ensure_tables()
    q = f"%{(query or '').lower()}%"
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, slug, title, views FROM wiki_entries "
                "WHERE guild_id=? AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ?) "
                "ORDER BY views DESC, updated_at DESC LIMIT ?",
                (guild_id, q, q, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"id": int(r[0]), "slug": r[1], "title": r[2], "views": int(r[3] or 0)}
            for r in rows
        ]
    except Exception as ex:
        print(f"[community_hub search_wiki] {ex}")
        return []


async def list_wiki_entries(guild_id: int, limit: int = 20) -> list[dict]:
    """Liste les entrées wiki triées par vues."""
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, slug, title, views FROM wiki_entries "
                "WHERE guild_id=? ORDER BY views DESC, updated_at DESC LIMIT ?",
                (guild_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"id": int(r[0]), "slug": r[1], "title": r[2], "views": int(r[3] or 0)}
            for r in rows
        ]
    except Exception as ex:
        print(f"[community_hub list_wiki_entries] {ex}")
        return []


async def delete_wiki_entry(guild_id: int, slug_or_title: str) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    slug = _slugify(slug_or_title)
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM wiki_entries WHERE guild_id=? AND "
                "(slug=? OR LOWER(title)=LOWER(?))",
                (guild_id, slug, slug_or_title),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[community_hub delete_wiki_entry] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# ROADMAP / SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════════

async def create_roadmap_item(
    guild_id: int, user_id: int, title: str, description: str
) -> tuple[bool, int | str]:
    """Crée un item roadmap. Retourne (ok, item_id_ou_erreur)."""
    if _get_db is None:
        return False, "Module non initialisé."
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        return False, "Titre requis."
    if len(title) > 120:
        return False, "Titre trop long (max 120 chars)."
    if len(description) > 1000:
        return False, "Description trop longue (max 1000 chars)."

    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO roadmap_items(guild_id, user_id, title, description) "
                "VALUES (?, ?, ?, ?)",
                (guild_id, user_id, title, description),
            )
            item_id = cur.lastrowid
            await db.commit()
        return True, int(item_id or 0)
    except Exception as ex:
        print(f"[community_hub create_roadmap_item] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def vote_roadmap_item(
    item_id: int, user_id: int, vote_value: int
) -> tuple[bool, str]:
    """Vote +1/-1/0 sur un item."""
    if _get_db is None:
        return False, "Module non initialisé."
    if vote_value not in (-1, 0, 1):
        return False, "Vote invalide."

    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM roadmap_items WHERE id=?", (item_id,)
            ) as cur:
                if not await cur.fetchone():
                    return False, "Item introuvable."

            if vote_value == 0:
                await db.execute(
                    "DELETE FROM roadmap_votes WHERE item_id=? AND user_id=?",
                    (item_id, user_id),
                )
                msg = "Vote retiré."
            else:
                await db.execute(
                    "INSERT INTO roadmap_votes (item_id, user_id, vote_value) "
                    "VALUES (?, ?, ?) ON CONFLICT(item_id, user_id) DO UPDATE SET "
                    "vote_value=excluded.vote_value, voted_at=CURRENT_TIMESTAMP",
                    (item_id, user_id, vote_value),
                )
                msg = "Vote enregistré."
            await db.commit()
        return True, msg
    except Exception as ex:
        print(f"[community_hub vote_roadmap_item] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def get_roadmap_items(
    guild_id: int,
    status_filter: Optional[str] = None,
    limit: int = ROADMAP_TOP_LIMIT,
) -> list[dict]:
    """Top items par score net."""
    if _get_db is None:
        return []
    await _ensure_tables()
    where = ["guild_id=?"]
    params: list = [guild_id]
    if status_filter and status_filter in ROADMAP_STATUSES:
        where.append("status=?")
        params.append(status_filter)
    sql = (
        "SELECT i.id, i.user_id, i.title, i.description, i.status, i.created_at, "
        "COALESCE(SUM(CASE WHEN v.vote_value > 0 THEN 1 ELSE 0 END), 0) AS up_count, "
        "COALESCE(SUM(CASE WHEN v.vote_value < 0 THEN 1 ELSE 0 END), 0) AS dn_count "
        "FROM roadmap_items i "
        "LEFT JOIN roadmap_votes v ON v.item_id = i.id "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY i.id "
        "ORDER BY (up_count - dn_count) DESC, i.created_at DESC LIMIT ?"
    )
    params.append(limit)
    try:
        async with _get_db() as db:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": int(r[0]),
                "user_id": int(r[1] or 0),
                "title": r[2],
                "description": r[3] or "",
                "status": r[4] or "open",
                "created_at": r[5],
                "up": int(r[6] or 0),
                "down": int(r[7] or 0),
                "score": int(r[6] or 0) - int(r[7] or 0),
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[community_hub get_roadmap_items] {ex}")
        return []


async def set_roadmap_status(item_id: int, status: str) -> bool:
    if _get_db is None or status not in ROADMAP_STATUSES:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE roadmap_items SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, item_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[community_hub set_roadmap_status] {ex}")
        return False


async def delete_roadmap_item(item_id: int) -> bool:
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute("DELETE FROM roadmap_votes WHERE item_id=?", (item_id,))
            cur = await db.execute(
                "DELETE FROM roadmap_items WHERE id=?", (item_id,)
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[community_hub delete_roadmap_item] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# WEEKLY HIGHLIGHTS
# ═══════════════════════════════════════════════════════════════════════════════

async def _collect_highlights(guild_id: int) -> dict:
    """Top messages / voice / events sur stats cumulatives."""
    out = {
        "top_chatters": [],
        "top_voice": [],
        "top_event_winners": [],
        "week_id": "",
    }
    if _get_db is None:
        return out

    now_local = datetime.now(_PARIS_TZ)
    out["week_id"] = now_local.strftime("%G-W%V")

    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, messages FROM user_stats41 "
                "WHERE guild_id=? AND messages > 0 "
                "ORDER BY messages DESC LIMIT ?",
                (guild_id, HIGHLIGHTS_TOP_PER_CATEGORY),
            ) as cur:
                out["top_chatters"] = [
                    {"user_id": int(r[0]), "value": int(r[1] or 0)}
                    for r in await cur.fetchall()
                ]

            async with db.execute(
                "SELECT user_id, voice_min FROM user_stats41 "
                "WHERE guild_id=? AND voice_min > 0 "
                "ORDER BY voice_min DESC LIMIT ?",
                (guild_id, HIGHLIGHTS_TOP_PER_CATEGORY),
            ) as cur:
                out["top_voice"] = [
                    {"user_id": int(r[0]), "value": int(r[1] or 0)}
                    for r in await cur.fetchall()
                ]

            async with db.execute(
                "SELECT user_id, events_won FROM user_stats41 "
                "WHERE guild_id=? AND events_won > 0 "
                "ORDER BY events_won DESC LIMIT ?",
                (guild_id, HIGHLIGHTS_TOP_PER_CATEGORY),
            ) as cur:
                out["top_event_winners"] = [
                    {"user_id": int(r[0]), "value": int(r[1] or 0)}
                    for r in await cur.fetchall()
                ]
    except Exception as ex:
        print(f"[community_hub _collect_highlights] {ex}")
    return out


def _build_highlights_layout(stats: dict, guild):
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    medals = ["🥇", "🥈", "🥉"]

    class _HighlightsLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            items = []
            items.append(v2_title("✨  HIGHLIGHTS DE LA SEMAINE"))
            items.append(v2_subtitle(
                f"_Les MVPs de {guild.name} cette semaine_"
            ))
            items.append(v2_divider())

            sections = [
                ("💬  TOP CHATTERS", stats["top_chatters"], "messages"),
                ("🎤  TOP VOCAUX", stats["top_voice"], "min vocaux"),
                ("🏆  TOP CHAMPIONS", stats["top_event_winners"], "victoires"),
            ]
            empty_all = True
            for header, rows, unit in sections:
                items.append(v2_body(f"**╔═══ {header}  ═══╗**"))
                if not rows:
                    items.append(v2_body("_Personne n'a marqué cette semaine._"))
                else:
                    empty_all = False
                    lines = []
                    for idx, r in enumerate(rows[:3]):
                        medal = medals[idx] if idx < 3 else "▫️"
                        lines.append(
                            f"{medal} <@{r['user_id']}> · `{r['value']:,}` {unit}"
                        )
                    items.append(v2_body("\n".join(lines)))
                items.append(v2_divider())

            if empty_all:
                items.append(v2_body(
                    "_Aucune activité notable cette semaine — semaine tranquille._"
                ))
            else:
                items.append(v2_body(
                    "_💡 Continue à participer pour figurer dans le top de la "
                    "semaine prochaine !_"
                ))

            self.add_item(v2_container(*items, color=0xFFD700))

    return _HighlightsLayout()


async def post_highlights_for_guild(guild) -> bool:
    """Poste les highlights dans le hub channel."""
    if _bot is None or _db_get is None:
        return False
    try:
        stats = await _collect_highlights(guild.id)
        cfg_data = await _db_get(guild.id)
        hub_ch_id = int(cfg_data.get("hub_channel", 0) or 0)
        if not hub_ch_id:
            return False
        ch = guild.get_channel(hub_ch_id)
        if not ch:
            return False
        view = _build_highlights_layout(stats, guild)
        if view is None:
            return False
        try:
            msg = await ch.send(view=view)
            print(f"✅ [community_hub highlights] posted guild={guild.id} msg={msg.id}")
            return True
        except (discord.Forbidden, discord.HTTPException) as ex:
            print(f"[community_hub highlights send guild={guild.id}] {ex}")
            return False
    except Exception as ex:
        print(f"[community_hub post_highlights guild={guild.id}] {ex}")
        return False


@tasks.loop(minutes=30)
async def weekly_highlights_task():
    """Post auto chaque dimanche 22h00-22h30 FR."""
    try:
        if _bot is None or _db_get is None or _db_set is None:
            return
        now_local = datetime.now(_PARIS_TZ)
        if now_local.weekday() != HIGHLIGHTS_POST_WEEKDAY:
            return
        if now_local.hour != HIGHLIGHTS_POST_HOUR:
            return

        await _ensure_tables()
        week_id = now_local.strftime("%G-W%V")
        for guild in list(_bot.guilds):
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT 1 FROM highlights_log WHERE guild_id=? AND week_id=?",
                        (guild.id, week_id),
                    ) as cur:
                        already = await cur.fetchone()
                if already:
                    continue

                ok = await post_highlights_for_guild(guild)
                if ok:
                    async with _get_db() as db:
                        await db.execute(
                            "INSERT OR IGNORE INTO highlights_log(guild_id, week_id) "
                            "VALUES (?, ?)",
                            (guild.id, week_id),
                        )
                        await db.commit()
            except Exception as ex:
                print(f"[community_hub highlights loop guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[community_hub weekly_highlights_task] {ex}")


@weekly_highlights_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════════
# PANELS V2 — wiki + roadmap
# ═══════════════════════════════════════════════════════════════════════════════

def build_wiki_entry_panel(entry: dict, author_user=None):
    """Panel V2 d'une entrée wiki."""
    if _v2_helpers is None or entry is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _WikiEntryLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"📖  {entry['title']}"))
            author_label = (
                author_user.display_name if author_user
                else f"<@{entry['author_id']}>"
            )
            items.append(v2_subtitle(
                f"_Slug `{entry['slug']}` · {entry['views']} vues · par {author_label}_"
            ))
            items.append(v2_divider())
            items.append(v2_body(entry["content"]))
            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/community wiki_list` pour voir toutes les entrées._"
            ))
            self.add_item(v2_container(*items, color=0x3498DB))

    return _WikiEntryLayout()


def build_wiki_list_panel(entries: list, query: str = ""):
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _WikiListLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            if query:
                items.append(v2_title("🔍  RÉSULTATS DE RECHERCHE"))
                items.append(v2_subtitle(f"_Pour : `{query}`_"))
            else:
                items.append(v2_title("📚  WIKI DU SERVEUR"))
                items.append(v2_subtitle("_Les entrées les plus consultées_"))
            items.append(v2_divider())

            if entries:
                lines = []
                for e in entries:
                    lines.append(
                        f"• **{e['title']}** _(slug `{e['slug']}` · {e['views']} vues)_"
                    )
                items.append(v2_body("\n".join(lines)))
            else:
                items.append(v2_body(
                    "_Aucune entrée pour l'instant. Demande au staff d'en créer._"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/community wiki <slug>` pour ouvrir une entrée précise._"
            ))
            self.add_item(v2_container(*items, color=0x3498DB))

    return _WikiListLayout()


def build_roadmap_panel(items_list: list, status_filter: Optional[str] = None):
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    title_label = "🗺️  ROADMAP COMMUNAUTAIRE"
    if status_filter and status_filter in ROADMAP_STATUSES:
        emoji, label = ROADMAP_STATUSES[status_filter]
        title_label = f"{emoji}  ROADMAP — {label.upper()}"

    class _RoadmapLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(title_label))
            items.append(v2_subtitle(
                "_Les suggestions de la communauté, triées par votes_"
            ))
            items.append(v2_divider())

            if items_list:
                lines = []
                for it in items_list:
                    emoji, _ = ROADMAP_STATUSES.get(it["status"], ("⏳", "Ouvert"))
                    score_str = (
                        f"`+{it['score']}`" if it['score'] >= 0
                        else f"`{it['score']}`"
                    )
                    lines.append(
                        f"{emoji} **#{it['id']}** · {it['title']}\n"
                        f"   _Score {score_str} · 👍 {it['up']} · 👎 {it['down']} · "
                        f"par <@{it['user_id']}>_"
                    )
                items.append(v2_body("\n\n".join(lines)))
            else:
                items.append(v2_body(
                    "_Aucune suggestion pour l'instant. "
                    "Sois le premier avec `/community suggest`._"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/community vote <id> <up|down>` pour voter sur un item._"
            ))
            self.add_item(v2_container(*items, color=0x9B59B6))

    return _RoadmapLayout()


__all__ = [
    "setup",
    # Wiki
    "add_wiki_entry", "get_wiki_entry", "search_wiki",
    "list_wiki_entries", "delete_wiki_entry",
    "build_wiki_entry_panel", "build_wiki_list_panel",
    # Roadmap
    "create_roadmap_item", "vote_roadmap_item", "get_roadmap_items",
    "set_roadmap_status", "delete_roadmap_item",
    "build_roadmap_panel", "ROADMAP_STATUSES",
    # Highlights
    "weekly_highlights_task", "post_highlights_for_guild",
]
