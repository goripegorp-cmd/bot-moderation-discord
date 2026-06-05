"""
community_goals.py — Objectifs collectifs hebdomadaires (Phase 157).

🎯 OBJECTIF : créer un sentiment de communauté en posant des objectifs
qui requièrent la participation de tout le serveur.

Mécanique :
- 1 objectif/semaine posté lundi 10h FR dans le hub.
- Types d'objectifs (rotation) :
  • "Cumuler 100 boss kills"
  • "Ouvrir 50 treasures"
  • "Jouer 30 duels"
  • "Compléter 200 quêtes daily"
  • "Spin la wheel 100 fois"
  • "Solve 20 riddles"
  • "Gagner 1 saga ensemble"
- À la fin de la semaine (dimanche 22h) :
  • Si objectif atteint → tous les contributeurs reçoivent **+500c**
  • Top 3 contributeurs : +2000c chacun
  • Si non atteint → mini-reward consolation (+100c)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- record_action(guild_id, user_id, action_kind) — appelé depuis hooks
- get_current_goal(guild_id) -> dict | None
- create_weekly_goal(guild) -> bool
- close_weekly_goal(guild) -> dict
- build_goal_panel(guild) -> LayoutView
- weekly_goal_task (loop)

DB tables :
- community_goals (id PK, guild_id, week_key, goal_kind, target, progress,
                    status, started_at, closed_at, contributors_jsonb)
"""
from __future__ import annotations

import asyncio
import json
import random
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
_add_coins = None

GOAL_TEMPLATES = [
    {"kind": "boss_kill", "target": 100, "emoji": "⚔️",
     "label": "Vaincre **100** boss ensemble"},
    {"kind": "treasure_open", "target": 50, "emoji": "💎",
     "label": "Récupérer **50** trésors"},
    {"kind": "duel", "target": 30, "emoji": "🤜",
     "label": "Jouer **30** duels"},
    {"kind": "quest_complete", "target": 200, "emoji": "🎯",
     "label": "Compléter **200** quêtes daily"},
    {"kind": "wheel_spin", "target": 100, "emoji": "🎰",
     "label": "Spin la Daily Wheel **100** fois"},
    {"kind": "riddle_solve", "target": 20, "emoji": "🧠",
     "label": "Résoudre **20** énigmes"},
    {"kind": "mystery_open", "target": 40, "emoji": "📦",
     "label": "Ouvrir **40** Mystery Box"},
    # Phase 254-extra : objectif de MESSAGES collectif (demande owner #1 : "des events
    # où il faut un certain nombre de messages, c'est ça qui lance l'activité").
    {"kind": "messages", "target": 300, "emoji": "💬",
     "label": "Envoyer **300** messages dans le chat ensemble"},
    {"kind": "voice_minutes", "target": 1000, "emoji": "🎙️",
     "label": "Cumuler **1000 minutes** en vocal"},
]

REWARD_CONTRIBUTOR = 500
REWARD_TOP3 = 2000
REWARD_CONSOLATION = 100


def _current_week_key() -> str:
    d = datetime.now(_PARIS_TZ) if _PARIS_TZ else datetime.now(timezone.utc)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    add_coins_fn=None,
):
    global _bot, _get_db, _db_get, _v2, _add_coins
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS community_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    week_key TEXT NOT NULL,
                    goal_kind TEXT,
                    target INTEGER,
                    progress INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    contributors_jsonb TEXT DEFAULT '{}',
                    emoji TEXT,
                    label TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_goals_active "
                "ON community_goals(guild_id, status, week_key)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[community_goals init_db] {ex}")


async def get_current_goal(guild_id: int) -> Optional[dict]:
    """Renvoie l'objectif actif (None si aucun)."""
    if _get_db is None:
        return None
    week = _current_week_key()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, goal_kind, target, progress, emoji, label, "
                "contributors_jsonb FROM community_goals "
                "WHERE guild_id=? AND week_key=? AND status='active' "
                "ORDER BY id DESC LIMIT 1",
                (guild_id, week),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        try:
            contributors = json.loads(row[6] or "{}")
        except Exception:
            contributors = {}
        return {
            "id": int(row[0]),
            "kind": row[1],
            "target": int(row[2] or 0),
            "progress": int(row[3] or 0),
            "emoji": row[4] or "🎯",
            "label": row[5] or "",
            "contributors": contributors,
        }
    except Exception as ex:
        print(f"[community_goals get_current_goal] {ex}")
        return None


# Phase 255 (audit) : record_action est désormais appelé pour CHAQUE message
# (objectif "messages") → la lecture-modification-écriture n'était PAS atomique
# (pool sans row-lock) : 2 messages quasi simultanés perdaient un incrément et la
# liste de contributeurs JSON pouvait s'écraser. Un verrou PAR GUILD sérialise
# l'opération (le bot = 1 seul process) → zéro perte, zéro écrasement.
_record_locks: dict = {}


def _get_record_lock(guild_id: int) -> asyncio.Lock:
    lock = _record_locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        _record_locks[guild_id] = lock
    return lock


async def record_action(
    guild_id: int, user_id: int, action_kind: str, count: int = 1,
):
    """À hooker depuis les events. Si un objectif actif matche, incrémente.
    Sérialisé par guild (verrou) → pas de lost-update sous le flux de messages."""
    async with _get_record_lock(guild_id):
        goal = await get_current_goal(guild_id)
        if not goal or goal["kind"] != action_kind:
            return
        try:
            contributors = goal["contributors"]
            uid_str = str(user_id)
            contributors[uid_str] = int(contributors.get(uid_str, 0)) + count
            new_progress = goal["progress"] + count

            async with _get_db() as db:
                await db.execute(
                    "UPDATE community_goals SET progress=?, "
                    "contributors_jsonb=? WHERE id=?",
                    (new_progress, json.dumps(contributors), goal["id"]),
                )
                await db.commit()
        except Exception as ex:
            print(f"[community_goals record_action {action_kind}] {ex}")


async def create_weekly_goal(guild: discord.Guild) -> bool:
    """Crée l'objectif de la semaine + annonce."""
    if _get_db is None or _v2 is None or not guild:
        return False
    week = _current_week_key()
    try:
        # Anti-double
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM community_goals "
                "WHERE guild_id=? AND week_key=?",
                (guild.id, week),
            ) as cur:
                if await cur.fetchone():
                    return False

        # Rotation : évite les 4 derniers
        async with _get_db() as db:
            async with db.execute(
                "SELECT goal_kind FROM community_goals "
                "WHERE guild_id=? ORDER BY started_at DESC LIMIT 4",
                (guild.id,),
            ) as cur:
                recent = {r[0] for r in await cur.fetchall()}
        available = [t for t in GOAL_TEMPLATES if t["kind"] not in recent]
        if not available:
            available = GOAL_TEMPLATES
        tpl = random.choice(available)

        async with _get_db() as db:
            await db.execute(
                "INSERT INTO community_goals "
                "(guild_id, week_key, goal_kind, target, emoji, label) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild.id, week, tpl["kind"], tpl["target"],
                    tpl["emoji"], tpl["label"],
                ),
            )
            await db.commit()

        # Annonce dans le hub/general
        target_ch = None
        for ch in guild.text_channels:
            n = ch.name.lower()
            if "hub" in n or "general" in n or "💫" in n:
                if ch.permissions_for(guild.me).send_messages:
                    target_ch = ch
                    break
        if target_ch is None:
            return True  # objectif créé mais pas annoncé

        LayoutView = _v2['LayoutView']
        v2_title = _v2['v2_title']
        v2_subtitle = _v2['v2_subtitle']
        v2_body = _v2['v2_body']
        v2_divider = _v2['v2_divider']
        v2_container = _v2['v2_container']

        items = [
            v2_title(f"{tpl['emoji']}  Objectif collectif de la semaine"),
            v2_subtitle(
                f"_Tout le serveur ensemble — fin dimanche 22h FR_"
            ),
            v2_divider(),
            v2_body(f"### {tpl['label']}"),
            v2_body(
                f"**Progression actuelle :** `0 / {tpl['target']}`"
            ),
            v2_divider(),
            v2_body(
                f"**🎁  Récompenses si atteint :**\n"
                f"• Tous les contributeurs : `+{REWARD_CONTRIBUTOR}` 🪙\n"
                f"• Top 3 contributeurs : `+{REWARD_TOP3}` 🪙 chacun\n\n"
                f"_Si pas atteint, consolation de `+{REWARD_CONSOLATION}` 🪙 "
                f"pour tous les participants._"
            ),
        ]

        class _GoalPanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(v2_container(*items, color=0x3498DB))

        await target_ch.send(view=_GoalPanel())
        return True
    except Exception as ex:
        print(f"[community_goals create_weekly_goal] {ex}")
        return False


async def close_weekly_goal(guild: discord.Guild) -> dict:
    """Ferme l'objectif + distribue les récompenses."""
    out = {"closed": False, "achieved": False, "total_contributors": 0,
           "coins_distributed": 0}
    if _get_db is None or not guild:
        return out
    week = _current_week_key()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, target, progress, contributors_jsonb, label, emoji "
                "FROM community_goals "
                "WHERE guild_id=? AND week_key=? AND status='active'",
                (guild.id, week),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return out

        goal_id = int(row[0])
        target = int(row[1])
        progress = int(row[2])
        contributors = json.loads(row[3] or "{}")
        label = row[4]
        emoji = row[5]
        achieved = progress >= target

        # Top 3 contributors
        top_sorted = sorted(
            contributors.items(), key=lambda x: -int(x[1]),
        )[:3]
        top_ids = {int(uid) for uid, _ in top_sorted}

        # Distribute rewards
        if _add_coins is not None:
            if achieved:
                for uid_str in contributors.keys():
                    try:
                        uid = int(uid_str)
                        reward = (
                            REWARD_TOP3 + REWARD_CONTRIBUTOR
                            if uid in top_ids
                            else REWARD_CONTRIBUTOR
                        )
                        await _add_coins(guild.id, uid, reward)
                        out["coins_distributed"] += reward
                    except Exception:
                        pass
            else:
                # Consolation
                for uid_str in contributors.keys():
                    try:
                        await _add_coins(
                            guild.id, int(uid_str), REWARD_CONSOLATION,
                        )
                        out["coins_distributed"] += REWARD_CONSOLATION
                    except Exception:
                        pass

        # Update DB
        async with _get_db() as db:
            await db.execute(
                "UPDATE community_goals SET status=?, "
                "closed_at=CURRENT_TIMESTAMP WHERE id=?",
                ("achieved" if achieved else "missed", goal_id),
            )
            await db.commit()

        out["closed"] = True
        out["achieved"] = achieved
        out["total_contributors"] = len(contributors)

        # Annonce résultat
        if _v2 is not None:
            try:
                target_ch = None
                for ch in guild.text_channels:
                    n = ch.name.lower()
                    if "hub" in n or "general" in n or "💫" in n:
                        if ch.permissions_for(guild.me).send_messages:
                            target_ch = ch
                            break
                if target_ch:
                    LayoutView = _v2['LayoutView']
                    v2_title = _v2['v2_title']
                    v2_body = _v2['v2_body']
                    v2_divider = _v2['v2_divider']
                    v2_container = _v2['v2_container']

                    items = []
                    if achieved:
                        items.append(v2_title(f"🎉  Objectif atteint !"))
                        items.append(v2_body(
                            f"{emoji} **{label}** — accompli !\n\n"
                            f"`{progress} / {target}` avec "
                            f"**{len(contributors)}** participants.\n\n"
                            f"💰 **{out['coins_distributed']:,}** coins "
                            f"distribués."
                        ))
                    else:
                        items.append(v2_title(f"⏰  Objectif manqué"))
                        items.append(v2_body(
                            f"{emoji} **{label}**\n\n"
                            f"`{progress} / {target}` — manqué de "
                            f"`{target - progress}`.\n\n"
                            f"Mais **{len(contributors)}** participants "
                            f"reçoivent `+{REWARD_CONSOLATION}` coins de "
                            f"consolation."
                        ))
                    items.append(v2_divider())
                    items.append(v2_body(
                        "_Nouvel objectif lundi matin 10h FR._"
                    ))

                    class _ResultPanel(LayoutView):
                        def __init__(self):
                            super().__init__(timeout=None)
                            self.add_item(v2_container(
                                *items,
                                color=0x2ECC71 if achieved else 0xE67E22,
                            ))

                    await target_ch.send(view=_ResultPanel())
            except Exception:
                pass

        return out
    except Exception as ex:
        print(f"[community_goals close_weekly_goal] {ex}")
        return out


def build_goal_panel(guild_id: int):
    """Panel V2 pour voir l'objectif actuel."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _GoalViewer(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.guild_id = guild_id

        async def populate(self):
            goal = await get_current_goal(guild_id)
            items = []
            if not goal:
                items.append(v2_title("🎯  Aucun objectif actif"))
                items.append(v2_body(
                    "_L'objectif de la semaine arrive lundi 10h FR._"
                ))
                self.add_item(v2_container(*items, color=0x95A5A6))
                return

            items.append(v2_title(
                f"{goal['emoji']}  Objectif collectif"
            ))
            items.append(v2_subtitle(f"_{goal['label']}_"))
            items.append(v2_divider())

            pct = int(goal["progress"] * 100 / max(1, goal["target"]))
            bar_filled = int(pct / 5)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            items.append(v2_body(
                f"**Progression :** `{goal['progress']} / "
                f"{goal['target']}` ({pct}%)\n`{bar}`"
            ))

            # Top contributors
            top = sorted(
                goal["contributors"].items(),
                key=lambda x: -int(x[1]),
            )[:5]
            if top:
                items.append(v2_divider())
                items.append(v2_body("**🏅  Top contributeurs :**"))
                for i, (uid_str, count) in enumerate(top, 1):
                    medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"`{i}.`"
                    items.append(v2_body(
                        f"{medal} <@{uid_str}> — `{count}` actions"
                    ))

            items.append(v2_divider())
            items.append(v2_body(
                f"**🎁  Récompenses si atteint :**\n"
                f"• Tous : `+{REWARD_CONTRIBUTOR}` 🪙\n"
                f"• Top 3 : `+{REWARD_TOP3}` 🪙 bonus chacun"
            ))
            self.add_item(v2_container(*items, color=0x3498DB))

    return _GoalViewer()


@tasks.loop(minutes=30)
async def weekly_goal_task():
    """Check : lundi 10h → create, dimanche 22h → close."""
    try:
        if _bot is None:
            return
        now_paris = (
            datetime.now(_PARIS_TZ) if _PARIS_TZ
            else datetime.now(timezone.utc)
        )
        weekday = now_paris.weekday()  # 0=Mon, 6=Sun
        hour = now_paris.hour

        if weekday == 0 and hour == 10:
            # Lundi 10h : create
            for g in _bot.guilds:
                try:
                    await create_weekly_goal(g)
                except Exception:
                    pass
                await asyncio.sleep(2)
        elif weekday == 6 and hour == 22:
            # Dimanche 22h : close
            for g in _bot.guilds:
                try:
                    await close_weekly_goal(g)
                except Exception:
                    pass
                await asyncio.sleep(2)
    except Exception as ex:
        print(f"[weekly_goal_task] {ex}")


@weekly_goal_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "record_action",
    "get_current_goal",
    "create_weekly_goal",
    "close_weekly_goal",
    "build_goal_panel",
    "weekly_goal_task",
    "GOAL_TEMPLATES",
]
