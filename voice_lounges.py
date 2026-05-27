"""
voice_milestones.py — Paliers de récompenses sur minutes vocales (Phase 137).

⚠️ Le système de VC créables à la volée existe déjà (Phase 25 — temp_voice_config
multi-hubs avec rôles requis, default_limit, etc.). On ne le re-fait PAS.

Ce module se concentre uniquement sur ce qui manquait :
**paliers de récompenses** basés sur les minutes vocales cumulées (lues depuis
user_stats41.voice_min).

Paliers :
- 60 min   (1h)    →   500 coins  · 🎙️ Première Heure
- 600 min  (10h)   → 3 000 coins  · 🎧 Habitué Vocal
- 3 000 min (50h)  → 12 000 coins · 🔊 Voix d'Argent
- 10 000 min (166h)→ 35 000 coins · 🥈 Voix d'Or
- 30 000 min (500h)→ 80 000 coins · 🏆 Voix de Platine
- 60 000 min (1000h)→ 200 000 coins · 👑 Voix Légendaire

Chaque palier est claim 1× (table voice_milestone_claims).

DB tables (créées à la volée) :
- voice_milestone_claims (guild_id, user_id, threshold_min, claimed_at)

API publique :
- setup(get_db_fn, v2_helpers)
- get_voice_minutes(guild_id, user_id) -> int
- get_claimed_thresholds(guild_id, user_id) -> set[int]
- check_and_award(guild, member, add_coins_fn) -> list[awarded]
- build_levels_panel() — Catalogue des paliers
- build_stats_panel(guild, member, awarded_now=None) — Mes stats vocales

⚠️ Conforme RULES.md : aucun système relationnel.
Pur outil de progression personnelle.

Note : le module garde son nom de fichier `voice_lounges.py` pour ne pas
casser les imports — mais c'est en réalité un module "voice_milestones".
"""
from __future__ import annotations

from typing import Optional

import discord


# ─── Catalogue de paliers vocaux (minutes cumulées) ──────────────────────
VOICE_MILESTONES = [
    {"minutes":    60, "emoji": "🎙️", "title": "Première Heure",    "coins":    500},
    {"minutes":   600, "emoji": "🎧", "title": "Habitué Vocal",      "coins":   3000},
    {"minutes":  3000, "emoji": "🔊", "title": "Voix d'Argent",      "coins":  12000},
    {"minutes": 10000, "emoji": "🥈", "title": "Voix d'Or",          "coins":  35000},
    {"minutes": 30000, "emoji": "🏆", "title": "Voix de Platine",    "coins":  80000},
    {"minutes": 60000, "emoji": "👑", "title": "Voix Légendaire",    "coins": 200000},
]


# Références injectées
_get_db = None
_v2_helpers = None
_tables_initialized = False


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
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
            await db.execute('''CREATE TABLE IF NOT EXISTS voice_milestone_claims (
                guild_id INTEGER,
                user_id INTEGER,
                threshold_min INTEGER,
                claimed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id, threshold_min)
            )''')
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[voice_milestones _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# PALIERS VOCAUX
# ═══════════════════════════════════════════════════════════════════════════════

async def get_voice_minutes(guild_id: int, user_id: int) -> int:
    """Lit les minutes vocales cumulées depuis user_stats41."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT voice_min FROM user_stats41 "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[voice_milestones get_voice_minutes] {ex}")
        return 0


async def get_claimed_thresholds(guild_id: int, user_id: int) -> set[int]:
    """Set des paliers déjà claim pour ce membre."""
    if _get_db is None:
        return set()
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT threshold_min FROM voice_milestone_claims "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                return {int(r[0]) for r in await cur.fetchall() if r[0]}
    except Exception as ex:
        print(f"[voice_milestones get_claimed_thresholds] {ex}")
        return set()


async def _mark_claimed(guild_id: int, user_id: int, threshold: int):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO voice_milestone_claims "
                "(guild_id, user_id, threshold_min) VALUES (?, ?, ?)",
                (guild_id, user_id, threshold),
            )
            await db.commit()
    except Exception as ex:
        print(f"[voice_milestones _mark_claimed] {ex}")


def _next_milestone(current_min: int) -> Optional[dict]:
    """Retourne le prochain palier non-atteint."""
    for m in VOICE_MILESTONES:
        if m["minutes"] > current_min:
            return m
    return None


async def check_and_award(
    guild: discord.Guild, member: discord.Member, add_coins_fn=None
) -> list[dict]:
    """Vérifie tous les paliers vocaux non-claim et les award.

    Idempotent — peut être appelé plusieurs fois sans double-claim.
    Returns: liste des paliers nouvellement award [{'milestone': dict}, ...]
    """
    awarded = []
    if _get_db is None or member is None or guild is None:
        return awarded

    await _ensure_tables()
    minutes = await get_voice_minutes(guild.id, member.id)
    claimed = await get_claimed_thresholds(guild.id, member.id)

    for m in VOICE_MILESTONES:
        if minutes >= m["minutes"] and m["minutes"] not in claimed:
            try:
                if add_coins_fn:
                    await add_coins_fn(guild.id, member.id, int(m["coins"]))
                await _mark_claimed(guild.id, member.id, m["minutes"])
                awarded.append({"milestone": m})
            except Exception as ex:
                print(f"[voice_milestones check_and_award] {ex}")

    return awarded


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panels V2
# ═══════════════════════════════════════════════════════════════════════════════

def _format_duration(minutes: int) -> str:
    """Format minutes → '12h 34min' ou '5j 2h'."""
    try:
        m = int(minutes)
    except Exception:
        return "0min"
    if m < 60:
        return f"{m}min"
    if m < 1440:
        h, rest = divmod(m, 60)
        return f"{h}h {rest}min" if rest else f"{h}h"
    d, rest = divmod(m, 1440)
    h = rest // 60
    return f"{d}j {h}h" if h else f"{d}j"


def _progress_bar(value: int, target: int, length: int = 14) -> str:
    if target <= 0:
        return "`" + "█" * length + "` 100%"
    pct = min(1.0, max(0.0, value / target))
    filled = round(pct * length)
    empty = length - filled
    return f"`{'█' * filled}{'░' * empty}` {int(pct * 100)}%"


def build_levels_panel():
    """Panel V2 listant tous les paliers vocaux."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _LevelsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("🎙️  PALIERS VOCAUX"))
            items.append(v2_subtitle(
                "_Tous les paliers basés sur tes minutes vocales cumulées_"
            ))
            items.append(v2_divider())

            lines = []
            for m in VOICE_MILESTONES:
                dur = _format_duration(m["minutes"])
                lines.append(
                    f"{m['emoji']} **{m['title']}** _({dur})_\n"
                    f"   → `+{m['coins']:,}` coins"
                )
            items.append(v2_body("\n\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/voice my_stats` pour voir tes minutes courantes._\n"
                "_💡 `/voice claim` pour réclamer les paliers atteints._"
            ))

            self.add_item(v2_container(*items, color=0x5865F2))

    return _LevelsPanel()


async def build_stats_panel(
    guild: discord.Guild, member: discord.Member,
    awarded_now: Optional[list] = None,
):
    """Panel V2 — mes stats vocales + prochain palier."""
    if _v2_helpers is None or member is None:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    minutes = await get_voice_minutes(guild.id, member.id)
    claimed = await get_claimed_thresholds(guild.id, member.id)
    next_m = _next_milestone(minutes)

    class _StatsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"🎧  STATS VOCALES DE {member.display_name.upper()}"))
            items.append(v2_subtitle(
                "_Tes minutes vocales cumulées sur le serveur_"
            ))
            items.append(v2_divider())

            # Awarded maintenant ?
            if awarded_now:
                items.append(v2_body("**╔═══ 🎉  NOUVEAUX PALIERS  ═══╗**"))
                lines = []
                total_coins = 0
                for entry in awarded_now:
                    m = entry["milestone"]
                    lines.append(
                        f"{m['emoji']} **{m['title']}** "
                        f"_({_format_duration(m['minutes'])})_ "
                        f"→ +`{m['coins']:,}` coins"
                    )
                    total_coins += int(m.get("coins", 0))
                items.append(v2_body("\n".join(lines)))
                if total_coins:
                    items.append(v2_body(
                        f"💰 **Total reçu maintenant : `{total_coins:,}` coins**"
                    ))
                items.append(v2_divider())

            # Stats actuelles
            items.append(v2_body("**╔═══ 📊  ACTIVITÉ ACTUELLE  ═══╗**"))
            items.append(v2_body(
                f"🎙️ **Minutes cumulées :** `{minutes:,}` min "
                f"_({_format_duration(minutes)})_"
            ))

            # Prochain palier
            if next_m:
                items.append(v2_divider())
                items.append(v2_body("**╔═══ 🎯  PROCHAIN PALIER  ═══╗**"))
                remaining = next_m["minutes"] - minutes
                items.append(v2_body(
                    f"{next_m['emoji']} **{next_m['title']}** "
                    f"_({_format_duration(next_m['minutes'])})_\n"
                    f"{_progress_bar(minutes, next_m['minutes'])}\n"
                    f"_Plus que `{_format_duration(remaining)}` à faire._\n"
                    f"🎁 Récompense : `+{next_m['coins']:,}` coins"
                ))
            else:
                items.append(v2_divider())
                items.append(v2_body(
                    "👑 **Tous les paliers atteints !** Tu es une légende vocale."
                ))

            # Total claim
            items.append(v2_divider())
            items.append(v2_body(
                f"📋 **Paliers débloqués :** "
                f"`{len(claimed)}` / `{len(VOICE_MILESTONES)}`\n"
                f"_💡 `/voice claim` pour récupérer les paliers en attente._"
            ))

            self.add_item(v2_container(*items, color=0x5865F2))

    return _StatsPanel()


__all__ = [
    "setup",
    # Lecture
    "get_voice_minutes", "get_claimed_thresholds",
    # Award
    "check_and_award",
    # Panels
    "build_levels_panel", "build_stats_panel",
    # Catalogue
    "VOICE_MILESTONES",
]
