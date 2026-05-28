"""
member_risk.py — Score risque sur les nouveaux joins (Phase 167.3).

🎯 OBJECTIF : owner voit dans son weekly_digest "5 joins à risque cette
semaine, à reviewer". Pas d'action auto. Juste de la visibility pour
décider à froid si ban/kick.

Critères de scoring (0-100, plus haut = plus risqué) :
- Account age < 7j        : +30
- Account age < 30j       : +15
- Avatar default          : +20
- Username pattern suspect (digits consécutifs ≥5) : +15
- Username < 5 chars      : +10
- Join velocity (3+ joins dans 60s autour) : +25

Threshold "risk" : score >= 40 → flag

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- init_db()
- on_member_join(member) -> int (score)
- get_risky_members_this_week(guild_id) -> list[dict]
- build_risk_panel(guild) -> LayoutView

DB :
- member_risk_scores (guild_id, user_id PK, score, reasons_jsonb,
                       joined_at, reviewed INTEGER DEFAULT 0)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

RISK_THRESHOLD = 40

# Pattern : 5+ digits consécutifs dans le username
DIGITS_RE = re.compile(r"\d{5,}")


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
                CREATE TABLE IF NOT EXISTS member_risk_scores (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    score INTEGER DEFAULT 0,
                    reasons_jsonb TEXT DEFAULT '[]',
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_member_risk_recent "
                "ON member_risk_scores(guild_id, joined_at DESC, reviewed)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[member_risk init_db] {ex}")


def _score_member(member: discord.Member, recent_joins_count: int = 0) -> tuple[int, list[str]]:
    """Calcule le score risque + raisons. Retourne (score, reasons[])."""
    score = 0
    reasons: list[str] = []

    # 1. Account age
    try:
        now = datetime.now(timezone.utc)
        created = member.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days
        if age_days < 7:
            score += 30
            reasons.append(f"Compte < 7j ({age_days}j)")
        elif age_days < 30:
            score += 15
            reasons.append(f"Compte < 30j ({age_days}j)")
    except Exception:
        pass

    # 2. Default avatar
    try:
        if member.avatar is None:
            score += 20
            reasons.append("Avatar par défaut")
    except Exception:
        pass

    # 3. Username pattern suspect
    name = member.name or ""
    if DIGITS_RE.search(name):
        score += 15
        reasons.append("5+ chiffres consécutifs dans le nom")
    if len(name) < 5:
        score += 10
        reasons.append(f"Nom très court ({len(name)} chars)")

    # 4. Join velocity
    if recent_joins_count >= 3:
        score += 25
        reasons.append(f"{recent_joins_count} joins dans 60s autour")

    return score, reasons


async def on_member_join(member: discord.Member) -> int:
    """Hook on_member_join. Calcule le score + INSERT en DB.
    Retourne le score (0 si erreur)."""
    if not member or not member.guild or member.bot or _get_db is None:
        return 0
    try:
        # Count joins récents pour velocity
        recent_count = 0
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM member_risk_scores "
                    "WHERE guild_id=? AND "
                    "datetime(joined_at) > datetime('now', '-60 seconds')",
                    (member.guild.id,),
                ) as cur:
                    row = await cur.fetchone()
            if row:
                recent_count = int(row[0] or 0)
        except Exception:
            pass

        score, reasons = _score_member(member, recent_count)

        # INSERT (idempotent via PK)
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT OR REPLACE INTO member_risk_scores "
                    "(guild_id, user_id, score, reasons_jsonb, "
                    "joined_at, reviewed) "
                    "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 0)",
                    (
                        member.guild.id, member.id, score,
                        json.dumps(reasons, ensure_ascii=False),
                    ),
                )
                await db.commit()
        except Exception:
            pass

        return score
    except Exception as ex:
        print(f"[member_risk on_member_join] {ex}")
        return 0


async def get_risky_members_this_week(guild_id: int) -> list[dict]:
    """Renvoie les membres avec score >= RISK_THRESHOLD joints
    dans les 7 derniers jours et non review."""
    out: list[dict] = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, score, reasons_jsonb, joined_at "
                "FROM member_risk_scores "
                "WHERE guild_id=? AND score >= ? AND reviewed=0 "
                "AND datetime(joined_at) > datetime('now', '-7 days') "
                "ORDER BY score DESC, joined_at DESC LIMIT 20",
                (guild_id, RISK_THRESHOLD),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            try:
                reasons = json.loads(r[2] or "[]")
            except Exception:
                reasons = []
            out.append({
                "user_id": int(r[0]),
                "score": int(r[1]),
                "reasons": reasons,
                "joined_at": r[3],
            })
    except Exception:
        pass
    return out


async def mark_reviewed(guild_id: int, user_id: int) -> bool:
    """Marque un user comme reviewé par l'owner."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE member_risk_scores SET reviewed=1 "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.commit()
        return True
    except Exception:
        return False


def build_risk_panel(guild: discord.Guild):
    """Panel V2 listant les joins à risque pour review owner."""
    if _v2 is None or guild is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _RiskPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            risky = await get_risky_members_this_week(guild.id)

            items = []
            items.append(v2_title("🤖  Joins à risque (7j)"))
            items.append(v2_subtitle(
                f"_{len(risky)} membre(s) avec score ≥ {RISK_THRESHOLD} "
                f"non encore reviewé(s)_"
            ))
            items.append(v2_divider())

            if not risky:
                items.append(v2_body(
                    "✅ **Aucun join à risque cette semaine.**\n"
                    "_Le serveur attire des comptes établis. Continue comme ça._"
                ))
            else:
                items.append(v2_body(
                    "_Score basé sur : âge compte, avatar, pattern nom, "
                    "velocity joins. **Aucune action auto** — c'est juste "
                    "pour ta visibilité._"
                ))
                items.append(v2_divider())

                for r in risky[:10]:
                    member = guild.get_member(r["user_id"])
                    name = (
                        member.mention if member
                        else f"User#{r['user_id']} _(parti)_"
                    )
                    score = r["score"]
                    score_badge = (
                        "🔴" if score >= 70
                        else "🟠" if score >= 55
                        else "🟡"
                    )
                    reasons_str = " · ".join(r["reasons"][:3])
                    items.append(v2_body(
                        f"{score_badge} **{score}/100** — {name}\n"
                        f"_{reasons_str}_"
                    ))

                if len(risky) > 10:
                    items.append(v2_body(
                        f"_+ {len(risky) - 10} autre(s) non affichés._"
                    ))

            self.add_item(v2_container(*items, color=0xE67E22))

    return _RiskPanel()


__all__ = [
    "setup",
    "init_db",
    "on_member_join",
    "get_risky_members_this_week",
    "mark_reviewed",
    "build_risk_panel",
    "RISK_THRESHOLD",
]
