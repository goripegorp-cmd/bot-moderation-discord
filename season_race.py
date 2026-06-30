"""season_race.py — Course de Saison PvE (board LIVE + « Ma position »).

owner 2026-06-30 : « jouer fait avancer » doit être VISIBLE et CONCRET. Ce module
publie UN board sticky (édité en place, anti-429) dans le hub :
- vrai classement de la saison (points de saison, désormais nourris par les events) ;
- compte à rebours réel jusqu'à la fin de saison (timestamp Discord, live côté client) ;
- bouton « 📊 Ma position » → rang RÉEL + points + prochain palier + points d'event
  encore gagnables aujourd'hui (action concrète, pas du blabla) ;
- bouton « 🔄 Actualiser » → ré-édite le board avec les données du moment.

Aucune dépendance circulaire dure : tout est injecté via setup(). FAIL-SAFE partout.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import tasks

# ─── Références injectées par bot.py ───────────────────────────────────────
_bot = None
_get_db = None
_db_get = None                 # async (guild_id) -> dict config
_season_id_fn = None           # () -> str (id de saison courant)
_season_progress_fn = None     # async (guild_id, user_id) -> {'points': int, ...}
_event_meta_cap = 150          # plafond quotidien de points d'event (miroir bot.py)

# anti-spam léger du bouton « Actualiser » (par guilde)
_refresh_cooldown: dict = {}


def setup(bot_instance, get_db_fn, db_get_fn, season_id_fn, season_progress_fn,
          event_meta_cap: int = 150):
    global _bot, _get_db, _db_get, _season_id_fn, _season_progress_fn, _event_meta_cap
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _season_id_fn = season_id_fn
    _season_progress_fn = season_progress_fn
    _event_meta_cap = int(event_meta_cap or 150)


async def _db_set(guild_id: int, key: str, value):
    try:
        from bot import db_set
        await db_set(guild_id, key, value)
    except Exception:
        pass


# ─── Helpers saison ────────────────────────────────────────────────────────
def _season_end_ts() -> int:
    """Timestamp unix de la fin de saison = fin du mois courant (Europe/Paris)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Europe/Paris')
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    else:
        nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    return int(nxt.timestamp())


def _next_boss_ts() -> int:
    """Timestamp unix du prochain Boss du jour (créneaux daily_bosses.BOSS_HOURS, Europe/Paris).
    Synchronisé avec la cadence réelle. FAIL-OPEN → 0 (la ligne est alors masquée)."""
    try:
        from datetime import timedelta
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo('Europe/Paris')
        except Exception:
            tz = timezone.utc
        try:
            import daily_bosses
            hours = sorted(int(h) for h in daily_bosses.BOSS_HOURS)
        except Exception:
            hours = [12, 21]
        if not hours:
            return 0
        now = datetime.now(tz)
        for h in hours:
            cand = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if cand > now:
                return int(cand.timestamp())
        cand = (now + timedelta(days=1)).replace(hour=hours[0], minute=0, second=0, microsecond=0)
        return int(cand.timestamp())
    except Exception:
        return 0


def _season_meta() -> tuple[str, str]:
    """(emoji, nom) de la saison courante via eng47. FAIL-OPEN."""
    try:
        import eng47
        s = eng47.current_season(datetime.now(timezone.utc).month)
        emoji = getattr(s, 'emoji', '🏆') or '🏆'
        name = getattr(s, 'name', None) or getattr(s, 'theme_role_name', None) or 'Saison'
        return emoji, str(name)
    except Exception:
        return '🏆', 'Saison'


def _next_tier(points: int):
    """Le prochain palier du Season Pass au-dessus de `points`, ou None. FAIL-OPEN."""
    try:
        import eng47
        tiers = sorted(eng47.SEASON_PASS_TIERS, key=lambda t: t.get('points', 0))
        for t in tiers:
            if int(t.get('points', 0)) > int(points):
                return t
    except Exception:
        pass
    return None


async def _top(guild_id: int, season_id: str, limit: int = 10):
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, points FROM season_progress "
                "WHERE guild_id=? AND season_id=? AND points > 0 "
                "ORDER BY points DESC, user_id ASC LIMIT ?",
                (guild_id, season_id, limit),
            ) as cur:
                return [(int(r[0]), int(r[1])) for r in await cur.fetchall()]
    except Exception:
        return []


async def _rank(guild_id: int, season_id: str, points: int) -> int:
    """Rang = nb de joueurs strictement au-dessus + 1. FAIL-OPEN → 1."""
    if _get_db is None:
        return 1
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM season_progress "
                "WHERE guild_id=? AND season_id=? AND points > ?",
                (guild_id, season_id, points),
            ) as cur:
                row = await cur.fetchone()
        return (int(row[0]) if row else 0) + 1
    except Exception:
        return 1


async def _today_meta_used(guild_id: int, user_id: int) -> int:
    if _get_db is None:
        return 0
    try:
        day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        async with _get_db() as db:
            async with db.execute(
                "SELECT points FROM event_meta_daily WHERE guild_id=? AND user_id=? AND day=?",
                (guild_id, user_id, day),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


# ─── Boutons persistants (DynamicItem) ─────────────────────────────────────
class SeasonRaceButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r"seasonrace:(?P<act>[a-z_]+)"):
    def __init__(self, act: str):
        self.act = act
        if act == 'refresh':
            btn = discord.ui.Button(label="🔄 Actualiser",
                                    style=discord.ButtonStyle.secondary,
                                    custom_id="seasonrace:refresh")
        else:
            btn = discord.ui.Button(label="📊 Ma position",
                                    style=discord.ButtonStyle.primary,
                                    custom_id="seasonrace:me")
        super().__init__(btn)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'])

    async def callback(self, i: discord.Interaction):
        await _on_click(i, self.act)


def _board_view() -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(SeasonRaceButton('me'))
    v.add_item(SeasonRaceButton('refresh'))
    return v


# ─── Rendu du board ────────────────────────────────────────────────────────
async def _build_board_embed(guild) -> discord.Embed:
    season_id = _season_id_fn() if _season_id_fn else 'saison'
    rows = await _top(guild.id, season_id, 10)
    emoji, sname = _season_meta()
    end_ts = _season_end_ts()
    e = discord.Embed(
        title=f"{emoji} Course de Saison — {sname}",
        description=(f"🏁 **Fin de saison <t:{end_ts}:R>** · récompenses au sommet.\n"
                     "Chaque boss et chaque trésor te donne des **points de saison** + de l'XP."),
        color=0xF1C40F,
    )
    if not rows:
        e.add_field(
            name="Classement vide",
            value="Personne n'a encore marqué de points cette saison — le prochain event lance la course.",
            inline=False)
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, (uid, pts) in enumerate(rows):
            m = guild.get_member(uid)
            name = (m.display_name if m else f"Joueur {uid}")[:28]
            badge = medals[idx] if idx < 3 else f"`#{idx + 1}`"
            lines.append(f"{badge} **{name}** — `{pts:,}` pts".replace(",", " "))
        e.add_field(name="🏆 Top 10 de la saison", value="\n".join(lines), inline=False)
    nb = _next_boss_ts()
    if nb:
        e.add_field(name="⏰ Prochain rendez-vous",
                    value=f"**Boss du jour <t:{nb}:R>** (puis <t:{nb}:t>) — sois là pour marquer des points.",
                    inline=False)
    e.set_footer(text="📊 Ma position = ton rang en direct · 🔄 Actualiser pour rafraîchir")
    return e


async def render_board(guild) -> bool:
    """Poste/édite le board sticky dans le hub. Édite en place (anti-429, zéro doublon).
    Retourne True si publié/édité. FAIL-SAFE."""
    if _bot is None or _db_get is None or guild is None:
        return False
    try:
        c = await _db_get(guild.id)
        if not c.get('season_race_enabled', 1):
            return False
        ch_id = int(c.get('hub_channel', 0) or 0)
        if not ch_id:
            return False
        ch = guild.get_channel(ch_id)
        if ch is None:
            return False
        embed = await _build_board_embed(guild)
        view = _board_view()
        msg_id = int(c.get('season_race_msg', 0) or 0)
        if msg_id:
            try:
                msg = await ch.fetch_message(msg_id)
                await msg.edit(embed=embed, view=view)
                return True
            except discord.NotFound:
                pass   # supprimé → on recrée
            except Exception:
                return False   # erreur transitoire (429…) → NE PAS reposter
        msg = await ch.send(embed=embed, view=view,
                            allowed_mentions=discord.AllowedMentions.none())
        await _db_set(guild.id, 'season_race_msg', msg.id)
        return True
    except Exception as ex:
        print(f"[season_race render guild={getattr(guild,'id',0)}] {ex}")
        return False


# ─── Interactions ──────────────────────────────────────────────────────────
async def _on_click(i: discord.Interaction, act: str):
    try:
        if i.guild is None:
            return await i.response.send_message("❌ Serveur uniquement.", ephemeral=True)
        if act == 'refresh':
            # anti-spam : 1 actualisation / 20 s / guilde — clic noyé = ack léger sans re-render.
            import time as _t
            now_ts = _t.time()
            last = _refresh_cooldown.get(i.guild.id, 0)
            await i.response.defer(ephemeral=True)
            if now_ts - last < 20:
                return await i.followup.send("⏳ Classement déjà à jour à l'instant.", ephemeral=True)
            _refresh_cooldown[i.guild.id] = now_ts
            await render_board(i.guild)
            return await i.followup.send("🔄 Classement actualisé.", ephemeral=True)

        # 'me' → position RÉELLE du joueur (données concrètes)
        await i.response.defer(ephemeral=True)
        season_id = _season_id_fn() if _season_id_fn else 'saison'
        prog = {}
        if _season_progress_fn:
            try:
                prog = await _season_progress_fn(i.guild.id, i.user.id) or {}
            except Exception:
                prog = {}
        pts = int(prog.get('points', 0) or 0)
        rank = await _rank(i.guild.id, season_id, pts)
        nxt = _next_tier(pts)
        used = await _today_meta_used(i.guild.id, i.user.id)
        remain = max(0, _event_meta_cap - used)
        emoji, sname = _season_meta()
        lines = [
            f"{emoji} **{sname}**",
            f"🏅 **Ton rang** : #{rank}",
            f"⭐ **Tes points de saison** : `{pts}`",
        ]
        if nxt:
            need = max(0, int(nxt.get('points', 0)) - pts)
            lines.append(f"🎯 **Prochain palier** (palier {nxt.get('tier', '?')}) : encore `{need}` pts")
        lines.append(f"⚡ **Points d'event encore gagnables aujourd'hui** : `{remain}` / {_event_meta_cap}")
        lines.append("-# Tu gagnes des points à CHAQUE event (boss, trésor…). Joue un event pour grimper.")
        await i.followup.send("\n".join(lines), ephemeral=True)
    except Exception as ex:
        print(f"[season_race _on_click {act}] {ex}")
        try:
            if not i.response.is_done():
                await i.response.send_message("✅ Pris en compte.", ephemeral=True)
            else:
                await i.followup.send("✅ Pris en compte.", ephemeral=True)
        except Exception:
            pass


# ─── Tâche programmée + persistance ────────────────────────────────────────
@tasks.loop(minutes=60)
async def season_race_task():
    """Rafraîchit le board de chaque serveur (édition en place). La 1re itération au
    boot ne fait qu'éditer le sticky existant → aucun spam de redéploiement."""
    if _bot is None:
        return
    for guild in list(_bot.guilds):
        try:
            await render_board(guild)
            await asyncio.sleep(2)   # jitter anti-429 multi-guildes
        except Exception:
            continue


@season_race_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


def register_persistent_views(bot):
    """Enregistre le DynamicItem des boutons (boutons vivants après reboot)."""
    try:
        bot.add_dynamic_items(SeasonRaceButton)
    except Exception as ex:
        print(f"[season_race register_persistent_views] {ex}")


__all__ = [
    "setup", "render_board", "season_race_task",
    "register_persistent_views", "SeasonRaceButton",
]
