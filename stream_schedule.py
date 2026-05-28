"""
stream_schedule.py — Planning streams + countdown auto (Phase 165.1).

🎯 OBJECTIF : owner schedule "Stream samedi 21h Twitch" via bouton, le bot
poste les countdowns automatiques (J-1, H-2, H-30, LIVE) dans le salon
créateur configuré. Stocke l'historique pour suggérer les meilleurs créneaux.

Pourquoi : un créateur qui annonce ses streams 2 jours avant + rappels
réguliers a 3× plus d'audience qu'un live spontané. Mais c'est chiant à
faire manuellement. Le bot s'en occupe.

API publique :
- setup(bot, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- schedule_stream(guild_id, user_id, platform, starts_at_iso,
                  url, title) -> int (stream_id)
- cancel_stream(stream_id) -> bool
- get_upcoming(guild_id, limit=5) -> list[dict]
- get_habits(guild_id) -> dict (stats jour/heure préférés)
- build_schedule_panel(member) -> LayoutView
- countdown_task (loop 5min)

DB tables :
- stream_schedule (id PK, guild_id, scheduled_by, platform, starts_at,
                   url, title, role_ping_id, j1/h2/h30/live_announced,
                   cancelled, created_at)

⚠️ Heures stockées en UTC, affichées en Europe/Paris.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button, Modal, TextInput

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

PLATFORMS = {
    "twitch": ("🟣", "Twitch"),
    "youtube": ("🔴", "YouTube"),
    "tiktok": ("⚫", "TikTok"),
    "kick": ("🟢", "Kick"),
}


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
                CREATE TABLE IF NOT EXISTS stream_schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    scheduled_by_user_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    starts_at TIMESTAMP NOT NULL,
                    stream_url TEXT,
                    title TEXT,
                    role_ping_id INTEGER DEFAULT 0,
                    j1_announced INTEGER DEFAULT 0,
                    h2_announced INTEGER DEFAULT 0,
                    h30_announced INTEGER DEFAULT 0,
                    live_announced INTEGER DEFAULT 0,
                    cancelled INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_stream_schedule_upcoming "
                "ON stream_schedule(guild_id, starts_at, cancelled)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[stream_schedule init_db] {ex}")


# ─── Core API ──────────────────────────────────────────────────────────────

async def schedule_stream(
    guild_id: int, user_id: int, platform: str,
    starts_at_iso: str, url: str = "", title: str = "",
    role_ping_id: int = 0,
) -> Optional[int]:
    """Programme un stream. starts_at_iso = ISO format UTC.
    Retourne stream_id ou None."""
    if _get_db is None:
        return None
    if platform not in PLATFORMS:
        return None
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO stream_schedule "
                "(guild_id, scheduled_by_user_id, platform, starts_at, "
                "stream_url, title, role_ping_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id, user_id, platform, starts_at_iso,
                    url[:500], title[:200], int(role_ping_id),
                ),
            )
            sid = cur.lastrowid
            await db.commit()
        return sid
    except Exception as ex:
        print(f"[stream_schedule schedule_stream] {ex}")
        return None


async def cancel_stream(stream_id: int) -> bool:
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE stream_schedule SET cancelled=1 WHERE id=?",
                (stream_id,),
            )
            await db.commit()
        return True
    except Exception:
        return False


async def get_upcoming(guild_id: int, limit: int = 5) -> list[dict]:
    """Renvoie les N prochains streams non annulés."""
    out: list[dict] = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, platform, starts_at, stream_url, title, "
                "scheduled_by_user_id, role_ping_id "
                "FROM stream_schedule "
                "WHERE guild_id=? AND cancelled=0 "
                "AND datetime(starts_at) >= datetime('now', '-15 minutes') "
                "ORDER BY starts_at ASC LIMIT ?",
                (guild_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "id": int(r[0]),
                "platform": r[1],
                "starts_at": r[2],
                "url": r[3] or "",
                "title": r[4] or "",
                "scheduled_by": int(r[5]),
                "role_ping_id": int(r[6] or 0),
            })
    except Exception:
        pass
    return out


async def get_habits(guild_id: int) -> dict:
    """Stats : sur quels jours/heures l'owner stream le plus.
    Retourne {best_weekday: 0-6, best_hour: 0-23, total_streams: N}."""
    out = {
        "best_weekday": None, "best_hour": None,
        "total_streams": 0, "weekday_counts": {},
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT starts_at FROM stream_schedule "
                "WHERE guild_id=? AND cancelled=0 "
                "AND datetime(starts_at) <= datetime('now')",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        weekday_counts: dict[int, int] = {}
        hour_counts: dict[int, int] = {}
        for (iso,) in rows:
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if _PARIS_TZ:
                    dt = dt.astimezone(_PARIS_TZ)
                wd = dt.weekday()
                h = dt.hour
                weekday_counts[wd] = weekday_counts.get(wd, 0) + 1
                hour_counts[h] = hour_counts.get(h, 0) + 1
            except Exception:
                continue
        out["total_streams"] = len(rows)
        out["weekday_counts"] = weekday_counts
        if weekday_counts:
            out["best_weekday"] = max(weekday_counts, key=weekday_counts.get)
        if hour_counts:
            out["best_hour"] = max(hour_counts, key=hour_counts.get)
    except Exception:
        pass
    return out


# ─── Countdown task ───────────────────────────────────────────────────────

async def _post_announcement(
    guild: discord.Guild, stream: dict, kind: str,
) -> bool:
    """Post une annonce de countdown dans le salon créateur configuré."""
    if not guild or _db_get is None:
        return False
    try:
        cfg_data = await _db_get(guild.id)
        ch_id = int(cfg_data.get("creator_channel", 0) or 0)
        if ch_id == 0:
            return False
        ch = guild.get_channel(ch_id)
        if not ch:
            return False

        plat_emoji, plat_label = PLATFORMS.get(
            stream["platform"], ("🎬", stream["platform"].title()),
        )

        starts_at = stream["starts_at"]
        try:
            dt = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
        except Exception:
            ts = None

        title = stream.get("title") or "Stream"
        url = stream.get("url") or ""
        role_ping = stream.get("role_ping_id", 0)
        ping_str = f"<@&{role_ping}> " if role_ping else ""

        if kind == "j1":
            content = (
                f"📅 **Demain — {plat_emoji} {plat_label}**\n\n"
                f"**{title}**\n"
                f"⏰ <t:{ts}:F> · <t:{ts}:R>\n"
                f"{url}".strip()
            )
        elif kind == "h2":
            content = (
                f"{ping_str}⏱️ **Dans 2h — {plat_emoji} {plat_label}**\n\n"
                f"**{title}**\n"
                f"⏰ <t:{ts}:t>\n"
                f"{url}".strip()
            )
        elif kind == "h30":
            content = (
                f"{ping_str}🚨 **Dans 30 min — {plat_emoji} {plat_label}**\n\n"
                f"**{title}**\n"
                f"{url}".strip()
            )
        elif kind == "live":
            content = (
                f"{ping_str}🔴 **LIVE MAINTENANT — {plat_emoji} {plat_label}**\n\n"
                f"**{title}**\n"
                f"👉 {url}".strip()
            )
        else:
            return False

        # Cap mentions (TOS Discord : max 3)
        allowed = discord.AllowedMentions(
            roles=True if role_ping else False,
            everyone=False, users=False,
        )
        await ch.send(content=content, allowed_mentions=allowed)
        return True
    except Exception as ex:
        print(f"[stream_schedule _post_announcement] {ex}")
        return False


async def _mark_announced(stream_id: int, kind: str):
    """Marque un type d'annonce comme envoyé."""
    if _get_db is None:
        return
    col = {"j1": "j1_announced", "h2": "h2_announced",
           "h30": "h30_announced", "live": "live_announced"}.get(kind)
    if not col:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                f"UPDATE stream_schedule SET {col}=1 WHERE id=?",
                (stream_id,),
            )
            await db.commit()
    except Exception:
        pass


@tasks.loop(minutes=5)
async def countdown_task():
    """Toutes les 5 min : pour chaque stream à venir dans 30h, check si
    on doit poster J-1, H-2, H-30 ou LIVE."""
    if _bot is None or _get_db is None:
        return
    try:
        now = datetime.now(timezone.utc)
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, platform, starts_at, stream_url, "
                "title, role_ping_id, j1_announced, h2_announced, "
                "h30_announced, live_announced "
                "FROM stream_schedule "
                "WHERE cancelled=0 "
                "AND datetime(starts_at) > datetime('now', '-1 hour') "
                "AND datetime(starts_at) < datetime('now', '+30 hours')"
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            sid = int(r[0])
            gid = int(r[1])
            stream = {
                "id": sid, "platform": r[2], "starts_at": r[3],
                "url": r[4] or "", "title": r[5] or "",
                "role_ping_id": int(r[6] or 0),
            }
            j1_done = bool(r[7])
            h2_done = bool(r[8])
            h30_done = bool(r[9])
            live_done = bool(r[10])
            try:
                dt = datetime.fromisoformat(str(r[3]).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                delta = (dt - now).total_seconds()
            except Exception:
                continue

            guild = _bot.get_guild(gid)
            if not guild:
                continue

            # J-1 : entre 22.5h et 25.5h avant
            if not j1_done and 81000 <= delta <= 91800:
                if await _post_announcement(guild, stream, "j1"):
                    await _mark_announced(sid, "j1")
            # H-2 : entre 1.5h et 2.5h avant
            elif not h2_done and 5400 <= delta <= 9000:
                if await _post_announcement(guild, stream, "h2"):
                    await _mark_announced(sid, "h2")
            # H-30 : entre 25min et 35min avant
            elif not h30_done and 1500 <= delta <= 2100:
                if await _post_announcement(guild, stream, "h30"):
                    await _mark_announced(sid, "h30")
            # LIVE : entre -10min et +10min de start
            elif not live_done and -600 <= delta <= 600:
                if await _post_announcement(guild, stream, "live"):
                    await _mark_announced(sid, "live")
    except Exception as ex:
        print(f"[stream_schedule countdown_task] {ex}")


@countdown_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ─── Panel V2 ──────────────────────────────────────────────────────────────

WEEKDAY_NAMES_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi",
                    "Vendredi", "Samedi", "Dimanche"]


def build_schedule_panel(member: discord.Member):
    """Panel V2 affichant les streams à venir + bouton 'Programmer'."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _SchedulePanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)

        async def populate(self):
            upcoming = await get_upcoming(member.guild.id, limit=5)
            habits = await get_habits(member.guild.id)

            items = []
            items.append(v2_title("📅  Calendrier des streams"))
            items.append(v2_subtitle(
                "_Programme tes lives, le bot poste les countdowns auto._"
            ))
            items.append(v2_divider())

            if upcoming:
                items.append(v2_body("**📺  Prochains streams :**"))
                for s in upcoming:
                    plat_em, plat_lab = PLATFORMS.get(
                        s["platform"], ("🎬", s["platform"].title()),
                    )
                    try:
                        dt = datetime.fromisoformat(
                            str(s["starts_at"]).replace("Z", "+00:00")
                        )
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        ts = int(dt.timestamp())
                        line = (
                            f"{plat_em} **{s['title'] or plat_lab}** · "
                            f"<t:{ts}:R> (<t:{ts}:f>)"
                        )
                    except Exception:
                        line = f"{plat_em} **{s['title'] or plat_lab}**"
                    items.append(v2_body(f"• {line}"))
            else:
                items.append(v2_body(
                    "_Aucun stream programmé. Clique sur "
                    "**➕ Programmer** pour en ajouter un._"
                ))

            items.append(v2_divider())

            # Habitudes
            if habits["total_streams"] >= 3:
                wd = habits["best_weekday"]
                h = habits["best_hour"]
                wd_name = WEEKDAY_NAMES_FR[wd] if wd is not None else "?"
                items.append(v2_body(
                    f"**📊  Tes habitudes** ({habits['total_streams']} streams) :\n"
                    f"• Jour préféré : **{wd_name}**\n"
                    f"• Heure préférée : **{h}h00**" if h is not None else
                    f"_Pas assez de données._"
                ))

            self.add_item(v2_container(*items, color=0x9146FF))

            # Bouton programmer
            b_add = Button(
                label="➕ Programmer un stream",
                style=discord.ButtonStyle.primary,
            )

            async def _on_add(i: discord.Interaction):
                if i.user.id != member.id:
                    return await i.response.send_message(
                        "🔒 Pas pour toi.", ephemeral=True
                    )
                await i.response.send_modal(_ScheduleModal())

            b_add.callback = _on_add
            self.add_item(b_add)

            # Bouton annuler le prochain
            if upcoming:
                b_cancel = Button(
                    label=f"❌ Annuler le prochain",
                    style=discord.ButtonStyle.danger,
                )

                async def _on_cancel(i: discord.Interaction):
                    if i.user.id != member.id:
                        return await i.response.send_message(
                            "🔒 Pas pour toi.", ephemeral=True
                        )
                    ok = await cancel_stream(upcoming[0]["id"])
                    msg = (
                        "✅ Stream annulé." if ok
                        else "❌ Échec de l'annulation."
                    )
                    await i.response.send_message(msg, ephemeral=True)

                b_cancel.callback = _on_cancel
                self.add_item(b_cancel)

    class _ScheduleModal(Modal):
        def __init__(self):
            super().__init__(title="📅 Programmer un stream")
            self.dt_in = TextInput(
                label="Date et heure (Paris)",
                placeholder="2026-06-15 21:00",
                required=True, max_length=20,
            )
            self.plat_in = TextInput(
                label="Plateforme",
                placeholder="twitch / youtube / tiktok / kick",
                required=True, max_length=20,
            )
            self.url_in = TextInput(
                label="URL du live (optionnel)",
                placeholder="https://twitch.tv/...",
                required=False, max_length=500,
            )
            self.title_in = TextInput(
                label="Titre / sujet (optionnel)",
                placeholder="Stream Roblox dev — chill",
                required=False, max_length=200,
            )
            self.add_item(self.dt_in)
            self.add_item(self.plat_in)
            self.add_item(self.url_in)
            self.add_item(self.title_in)

        async def on_submit(self, i: discord.Interaction):
            try:
                raw_dt = self.dt_in.value.strip()
                # Parse "YYYY-MM-DD HH:MM" en Paris time
                try:
                    naive = datetime.strptime(raw_dt, "%Y-%m-%d %H:%M")
                except ValueError:
                    return await i.response.send_message(
                        "❌ Format de date invalide. "
                        "Utilise `YYYY-MM-DD HH:MM` (ex: `2026-06-15 21:00`).",
                        ephemeral=True,
                    )
                if _PARIS_TZ:
                    dt_aware = naive.replace(tzinfo=_PARIS_TZ)
                else:
                    dt_aware = naive.replace(tzinfo=timezone.utc)
                dt_utc = dt_aware.astimezone(timezone.utc)
                if dt_utc < datetime.now(timezone.utc):
                    return await i.response.send_message(
                        "❌ Cette date est dans le passé.",
                        ephemeral=True,
                    )

                plat = self.plat_in.value.strip().lower()
                if plat not in PLATFORMS:
                    return await i.response.send_message(
                        f"❌ Plateforme inconnue. Choix : "
                        f"{', '.join(PLATFORMS.keys())}.",
                        ephemeral=True,
                    )

                sid = await schedule_stream(
                    i.guild.id, i.user.id, plat,
                    dt_utc.isoformat(),
                    url=self.url_in.value.strip(),
                    title=self.title_in.value.strip(),
                )
                if sid is None:
                    return await i.response.send_message(
                        "❌ Erreur lors de l'enregistrement.",
                        ephemeral=True,
                    )
                ts = int(dt_utc.timestamp())
                await i.response.send_message(
                    f"✅ Stream programmé pour <t:{ts}:F> (<t:{ts}:R>).\n"
                    f"Countdowns auto J-1 / H-2 / H-30 / LIVE.",
                    ephemeral=True,
                )
            except Exception as ex:
                print(f"[stream_schedule modal] {ex}")
                try:
                    await i.response.send_message(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
                except Exception:
                    pass

    return _SchedulePanel()


__all__ = [
    "setup",
    "init_db",
    "schedule_stream",
    "cancel_stream",
    "get_upcoming",
    "get_habits",
    "build_schedule_panel",
    "countdown_task",
    "PLATFORMS",
]
