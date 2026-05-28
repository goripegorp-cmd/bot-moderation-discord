"""
activity_heatmap.py — Heatmap d'activité par (jour, heure) (Phase 165.2).

🎯 OBJECTIF : owner sait QUAND son serveur est actif. Pas par anecdote
("ça avait l'air calme hier"), mais par DATA agrégée sur 14 jours :
qui parle quand, dans quelles plages.

Mécanique :
- Sur chaque message, on incrémente activity_heatmap_buckets
  (guild_id, weekday 0-6, hour 0-23) → count.
- Une fois par semaine (dimanche 18h FR), on DM l'owner avec un
  rendu texte de la heatmap (matrice ASCII colorée par densité)
  + l'analyse "tes plages fortes / faibles".

⚠️ Pourquoi pas de PNG render : ajouter Pillow comme dépendance pour
un seul cas usage est lourd. Une matrice texte ANSI/Unicode dans un
DM Discord rend très bien et reste légère.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- track_message(message) -> None
- build_heatmap_panel(guild) -> LayoutView (visualisation)
- get_best_hours(guild_id, top_n=3) -> list[dict]
- weekly_owner_dispatch_task (loop hourly check)

DB :
- activity_heatmap_buckets (guild_id, weekday, hour, msg_count,
                            last_updated, PRIMARY KEY (gid, wd, h))
- activity_heatmap_dispatch (guild_id PK, last_sent_at)
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
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

WEEKDAYS_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

# Caractères Unicode pour la densité (du moins dense au plus dense)
DENSITY_CHARS = [
    "⬛",  # 0 = vide
    "🟦",  # 1-25%
    "🟩",  # 25-50%
    "🟨",  # 50-75%
    "🟧",  # 75-90%
    "🟥",  # 90-100% (peak)
]


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_heatmap_buckets (
                    guild_id INTEGER NOT NULL,
                    weekday INTEGER NOT NULL,
                    hour INTEGER NOT NULL,
                    msg_count INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, weekday, hour)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_heatmap_dispatch (
                    guild_id INTEGER PRIMARY KEY,
                    last_sent_at TIMESTAMP
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[activity_heatmap init_db] {ex}")


async def track_message(message: discord.Message):
    """Incrémente le bucket (guild, weekday, hour) pour ce message."""
    if not message.guild or message.author.bot or _get_db is None:
        return
    try:
        # Heure locale Paris pour qu'un "20h" = peak prime time
        if _PARIS_TZ:
            now = datetime.now(_PARIS_TZ)
        else:
            now = datetime.now(timezone.utc)
        wd = now.weekday()
        h = now.hour
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activity_heatmap_buckets "
                "(guild_id, weekday, hour, msg_count, last_updated) "
                "VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, weekday, hour) DO UPDATE SET "
                "msg_count = msg_count + 1, "
                "last_updated = CURRENT_TIMESTAMP",
                (message.guild.id, wd, h),
            )
            await db.commit()
    except Exception:
        pass


async def get_heatmap_matrix(guild_id: int) -> list[list[int]]:
    """Renvoie une matrice [weekday][hour] = msg_count."""
    matrix = [[0] * 24 for _ in range(7)]
    if _get_db is None:
        return matrix
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT weekday, hour, msg_count "
                "FROM activity_heatmap_buckets WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        for wd, h, cnt in rows:
            if 0 <= wd <= 6 and 0 <= h <= 23:
                matrix[wd][h] = int(cnt or 0)
    except Exception:
        pass
    return matrix


def _render_matrix_ascii(matrix: list[list[int]]) -> str:
    """Rend la matrice 7×24 en bloc Unicode coloré."""
    # Max global pour normaliser
    flat_max = max((max(row) if row else 0) for row in matrix) or 1

    # Header avec les heures (groupé par 4 pour éviter overflow)
    lines = []
    lines.append("```")
    lines.append("       00 02 04 06 08 10 12 14 16 18 20 22")
    for wd in range(7):
        row_chars = []
        # On échantillonne 1 sur 2 (12 colonnes au lieu de 24) pour rester
        # lisible dans un DM (max ~80 char par ligne)
        for h in range(0, 24, 2):
            val = matrix[wd][h]
            if val == 0:
                row_chars.append("⬛")
            else:
                ratio = val / flat_max
                if ratio < 0.25:
                    row_chars.append("🟦")
                elif ratio < 0.5:
                    row_chars.append("🟩")
                elif ratio < 0.75:
                    row_chars.append("🟨")
                elif ratio < 0.9:
                    row_chars.append("🟧")
                else:
                    row_chars.append("🟥")
        lines.append(f"  {WEEKDAYS_FR[wd]}  {' '.join(row_chars)}")
    lines.append("```")
    return "\n".join(lines)


async def get_best_hours(guild_id: int, top_n: int = 3) -> list[dict]:
    """Renvoie les top_n créneaux les plus actifs (weekday, hour, count)."""
    matrix = await get_heatmap_matrix(guild_id)
    all_slots: list[tuple[int, int, int]] = []
    for wd in range(7):
        for h in range(24):
            all_slots.append((wd, h, matrix[wd][h]))
    # Trier par count décroissant
    all_slots.sort(key=lambda x: -x[2])
    out = []
    for wd, h, cnt in all_slots[:top_n]:
        if cnt == 0:
            break
        out.append({
            "weekday": wd,
            "weekday_label": WEEKDAYS_FR[wd],
            "hour": h,
            "count": cnt,
        })
    return out


def build_heatmap_panel(guild: discord.Guild):
    """Panel V2 affichant la heatmap + analyse."""
    if _v2 is None or guild is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _HeatmapPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            matrix = await get_heatmap_matrix(guild.id)
            best = await get_best_hours(guild.id, top_n=3)

            total_msgs = sum(sum(row) for row in matrix)

            items = []
            items.append(v2_title("🗺️  Heatmap d'activité"))
            items.append(v2_subtitle(
                f"_Quand ton serveur est actif (heures Paris) · "
                f"{total_msgs:,} messages comptés_"
            ))
            items.append(v2_divider())

            if total_msgs == 0:
                items.append(v2_body(
                    "_Pas encore assez de données. Reviens demain._"
                ))
            else:
                items.append(v2_body(_render_matrix_ascii(matrix)))
                items.append(v2_divider())

                # Légende
                items.append(v2_body(
                    "**Légende :** ⬛ vide · 🟦 faible · 🟩 moyen · "
                    "🟨 élevé · 🟧 fort · 🟥 peak"
                ))
                items.append(v2_divider())

                # Top 3 créneaux
                if best:
                    items.append(v2_body("**🎯 Top 3 créneaux :**"))
                    for i, b in enumerate(best, start=1):
                        items.append(v2_body(
                            f"`{i}.` {b['weekday_label']} **{b['hour']:02d}h** "
                            f"— `{b['count']:,}` messages"
                        ))
                    items.append(v2_divider())
                    items.append(v2_body(
                        "_💡 **Programme tes events** sur ces créneaux "
                        "pour maximiser la participation._"
                    ))

            self.add_item(v2_container(*items, color=0x3498DB))

    return _HeatmapPanel()


# ─── Weekly owner dispatch ─────────────────────────────────────────────────

@tasks.loop(hours=1)
async def weekly_owner_dispatch_task():
    """Toutes les heures, check si on est dimanche 18h FR. Si oui, DM
    l'owner avec sa heatmap + analyse — sauf si déjà envoyé cette semaine."""
    if _bot is None or _get_db is None:
        return
    try:
        if _PARIS_TZ:
            now = datetime.now(_PARIS_TZ)
        else:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
        # Dimanche = 6, heure cible = 18
        if now.weekday() != 6 or now.hour != 18:
            return

        for guild in _bot.guilds:
            try:
                # Anti-doublon : check dernière envoi
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT last_sent_at FROM activity_heatmap_dispatch "
                        "WHERE guild_id=?",
                        (guild.id,),
                    ) as cur:
                        row = await cur.fetchone()
                if row and row[0]:
                    try:
                        last = datetime.fromisoformat(
                            str(row[0]).replace("Z", "+00:00")
                        )
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        if (datetime.now(timezone.utc) - last).days < 6:
                            continue  # déjà envoyé cette semaine
                    except Exception:
                        pass

                # Build content
                matrix = await get_heatmap_matrix(guild.id)
                total = sum(sum(r) for r in matrix)
                if total < 50:
                    continue  # pas assez de data, attend la semaine suivante

                best = await get_best_hours(guild.id, top_n=3)
                heat_str = _render_matrix_ascii(matrix)

                content_lines = [
                    f"🗺️ **Heatmap hebdo — {guild.name}**",
                    "",
                    f"_{total:,} messages analysés (heures Paris)_",
                    "",
                    heat_str,
                    "",
                    "**🎯 Top 3 créneaux les plus actifs :**",
                ]
                for i, b in enumerate(best, start=1):
                    content_lines.append(
                        f"`{i}.` {b['weekday_label']} **{b['hour']:02d}h** "
                        f"— `{b['count']:,}` msgs"
                    )
                content_lines.extend([
                    "",
                    "_💡 Programme tes events sur ces créneaux pour "
                    "maximiser la participation._",
                ])

                # Envoie au owner
                owner = (
                    guild.owner or
                    await guild.fetch_member(guild.owner_id)
                )
                if owner:
                    sent_ok = False
                    try:
                        import dm_digest as _dm_dig
                        if _dm_dig and hasattr(_dm_dig, "send_urgent_now"):
                            sent_ok = await _dm_dig.send_urgent_now(
                                owner, "\n".join(content_lines)
                            )
                    except Exception:
                        sent_ok = False
                    if not sent_ok:
                        try:
                            await owner.send("\n".join(content_lines))
                            sent_ok = True
                        except Exception:
                            pass

                # Mark dispatched
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO activity_heatmap_dispatch "
                        "(guild_id, last_sent_at) "
                        "VALUES (?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(guild_id) DO UPDATE SET "
                        "last_sent_at = CURRENT_TIMESTAMP",
                        (guild.id,),
                    )
                    await db.commit()
            except Exception as ex:
                print(f"[activity_heatmap dispatch g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[activity_heatmap weekly_owner_dispatch_task] {ex}")


@weekly_owner_dispatch_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "track_message",
    "get_heatmap_matrix",
    "get_best_hours",
    "build_heatmap_panel",
    "weekly_owner_dispatch_task",
]
