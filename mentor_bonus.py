"""
mentor_bonus.py — Renforcement Mentorat actif (Phase 153 — B3).

🎯 OBJECTIF : transformer le système mentor/apprenti (Phase 52) d'une
relation passive en duo actif qui se nourrit mutuellement.

Mécanique :
- Quand l'apprenti gagne un event (boss kill, duel win, quest, etc.) :
  → mentor reçoit +10 coins + +5 XP
- Après 7 jours de mentorat actif (≥ 3 events apprentis/semaine) :
  → badge "🤝 Duo des sages" pour les deux
- Après 30 jours :
  → badge "✨ Duo légendaire" + +1000 coins bonus chacun

API publique :
- setup(get_db_fn, db_get_fn, v2_helpers, add_coins_fn,
        reputation_module=None)
- on_apprenti_event(guild_id, apprenti_id, event_kind)
- check_milestones(guild_id, mentor_id, apprenti_id) -> dict
- get_duo_status(guild_id, user_id) -> dict
- build_duo_panel(member) -> LayoutView

DB tables :
- mentor_bonus_track (guild_id, mentor_id, apprenti_id, started_at,
                       events_count, week_streak, last_event_at,
                       milestone_7d_reached, milestone_30d_reached,
                       PRIMARY KEY (guild_id, mentor_id, apprenti_id))

⚠️ Pour identifier la relation mentor/apprenti, on lit la table
existante de Phase 52 si dispo. Sinon on track via API directe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_get_db = None
_db_get = None
_v2 = None
_add_coins = None
_reputation = None

MENTOR_REWARD_COINS = 10
MENTOR_REWARD_XP = 5
DUO_7D_BONUS = 200
DUO_30D_BONUS = 1000
DUO_7D_BADGE = "🤝 Duo des sages"
DUO_30D_BADGE = "✨ Duo légendaire"


def setup(
    get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
    reputation_module=None,
):
    global _get_db, _db_get, _v2, _add_coins, _reputation
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _reputation = reputation_module


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mentor_bonus_track (
                    guild_id INTEGER NOT NULL,
                    mentor_id INTEGER NOT NULL,
                    apprenti_id INTEGER NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    events_count INTEGER DEFAULT 0,
                    last_event_at TIMESTAMP,
                    milestone_7d_reached INTEGER DEFAULT 0,
                    milestone_30d_reached INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, mentor_id, apprenti_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[mentor_bonus init_db] {ex}")


async def _find_mentor(guild_id: int, apprenti_id: int) -> Optional[int]:
    """Trouve le mentor d'un apprenti via la table Phase 52 (mentor_pairs)."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            # Essaie plusieurs noms de table possibles
            for table in ("mentor_pairs", "mentor_invites", "mentorat"):
                try:
                    async with db.execute(
                        f"SELECT mentor_id FROM {table} "
                        f"WHERE guild_id=? AND apprenti_id=? "
                        f"AND (status IS NULL OR status='active') LIMIT 1",
                        (guild_id, apprenti_id),
                    ) as cur:
                        row = await cur.fetchone()
                    if row and row[0]:
                        return int(row[0])
                except Exception:
                    continue
    except Exception:
        pass
    return None


async def on_apprenti_event(
    guild_id: int, apprenti_id: int, event_kind: str = "generic",
) -> Optional[dict]:
    """À hooker depuis tous les events. Si apprenti a un mentor,
    le mentor gagne sa récompense."""
    if _get_db is None:
        return None
    mentor_id = await _find_mentor(guild_id, apprenti_id)
    if mentor_id is None:
        return None
    try:
        # Update track
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO mentor_bonus_track "
                "(guild_id, mentor_id, apprenti_id, events_count, "
                "last_event_at) VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, mentor_id, apprenti_id) DO UPDATE SET "
                "events_count = events_count + 1, "
                "last_event_at = CURRENT_TIMESTAMP",
                (guild_id, mentor_id, apprenti_id),
            )
            await db.commit()

        # Reward mentor
        if _add_coins is not None:
            try:
                await _add_coins(guild_id, mentor_id, MENTOR_REWARD_COINS)
            except Exception:
                pass

        # Check milestones
        return await check_milestones(guild_id, mentor_id, apprenti_id)
    except Exception as ex:
        print(f"[mentor_bonus on_apprenti_event] {ex}")
        return None


async def check_milestones(
    guild_id: int, mentor_id: int, apprenti_id: int,
) -> dict:
    """Vérifie si milestone 7d ou 30d atteint."""
    out = {
        "milestone_7d": False,
        "milestone_30d": False,
        "bonus_awarded": 0,
        "badge": None,
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT started_at, events_count, milestone_7d_reached, "
                "milestone_30d_reached FROM mentor_bonus_track "
                "WHERE guild_id=? AND mentor_id=? AND apprenti_id=?",
                (guild_id, mentor_id, apprenti_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return out

        started_at, events_count, m7, m30 = row
        events_count = int(events_count or 0)
        try:
            started = (
                datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                if "T" in str(started_at) else
                datetime.strptime(
                    str(started_at), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
            )
        except Exception:
            started = datetime.now(timezone.utc)
        days_elapsed = (datetime.now(timezone.utc) - started).days

        # Milestone 7d : 7+ jours actifs + 3+ events
        if not m7 and days_elapsed >= 7 and events_count >= 3:
            out["milestone_7d"] = True
            out["badge"] = DUO_7D_BADGE
            if _add_coins is not None:
                for uid in (mentor_id, apprenti_id):
                    try:
                        await _add_coins(guild_id, uid, DUO_7D_BONUS)
                    except Exception:
                        pass
            out["bonus_awarded"] = DUO_7D_BONUS
            async with _get_db() as db:
                await db.execute(
                    "UPDATE mentor_bonus_track SET milestone_7d_reached=1 "
                    "WHERE guild_id=? AND mentor_id=? AND apprenti_id=?",
                    (guild_id, mentor_id, apprenti_id),
                )
                await db.commit()

        # Milestone 30d : 30+ jours + 10+ events
        if not m30 and days_elapsed >= 30 and events_count >= 10:
            out["milestone_30d"] = True
            out["badge"] = DUO_30D_BADGE
            if _add_coins is not None:
                for uid in (mentor_id, apprenti_id):
                    try:
                        await _add_coins(guild_id, uid, DUO_30D_BONUS)
                    except Exception:
                        pass
            out["bonus_awarded"] = DUO_30D_BONUS
            # Reputation aussi !
            if _reputation is not None:
                for uid in (mentor_id, apprenti_id):
                    try:
                        await _reputation.add_points(
                            guild_id, uid, "alliance_milestone", 10,
                        )
                    except Exception:
                        pass
            async with _get_db() as db:
                await db.execute(
                    "UPDATE mentor_bonus_track SET milestone_30d_reached=1 "
                    "WHERE guild_id=? AND mentor_id=? AND apprenti_id=?",
                    (guild_id, mentor_id, apprenti_id),
                )
                await db.commit()

        return out
    except Exception as ex:
        print(f"[mentor_bonus check_milestones] {ex}")
        return out


async def get_duo_status(guild_id: int, user_id: int) -> dict:
    """Status duo pour un user (en tant que mentor OU apprenti)."""
    out = {"is_mentor": False, "is_apprenti": False, "duos": []}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT mentor_id, apprenti_id, events_count, "
                "milestone_7d_reached, milestone_30d_reached, started_at "
                "FROM mentor_bonus_track "
                "WHERE guild_id=? AND (mentor_id=? OR apprenti_id=?)",
                (guild_id, user_id, user_id),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            partner_id = int(r[1]) if int(r[0]) == user_id else int(r[0])
            role = "mentor" if int(r[0]) == user_id else "apprenti"
            badge = None
            if int(r[4]):
                badge = DUO_30D_BADGE
            elif int(r[3]):
                badge = DUO_7D_BADGE
            out["duos"].append({
                "partner_id": partner_id,
                "role": role,
                "events_count": int(r[2] or 0),
                "badge": badge,
                "started_at": r[5],
            })
            if role == "mentor":
                out["is_mentor"] = True
            else:
                out["is_apprenti"] = True
    except Exception:
        pass
    return out


def build_duo_panel(member: discord.Member):
    """Panel V2 affichant les duos actifs + badges."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _DuoPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            status = await get_duo_status(member.guild.id, member.id)
            items = []
            items.append(v2_title("🤝  Mentorat actif"))
            if not status["duos"]:
                items.append(v2_body(
                    "_Tu n'as pas encore de mentor ou d'apprenti. "
                    "Utilise `/mentor_invite` pour démarrer une relation._"
                ))
                self.add_item(v2_container(*items, color=0x95A5A6))
                return

            items.append(v2_body(
                f"_Tu as **{len(status['duos'])}** relation(s) active(s)_"
            ))
            items.append(v2_divider())

            for duo in status["duos"]:
                partner = member.guild.get_member(duo["partner_id"])
                pname = partner.display_name if partner else f"User-{duo['partner_id']}"
                role_emoji = "📚" if duo["role"] == "mentor" else "🎓"
                items.append(v2_body(
                    f"{role_emoji} **{pname}** _(tu es {duo['role']})_"
                ))
                items.append(v2_body(
                    f"   • Events partagés : `{duo['events_count']}`"
                ))
                if duo["badge"]:
                    items.append(v2_body(f"   • {duo['badge']} ✨"))
                else:
                    items.append(v2_body(
                        "   _Continuez d'enchainer les events ensemble pour "
                        "débloquer des badges et bonus_"
                    ))

            self.add_item(v2_container(*items, color=0x2ECC71))

    return _DuoPanel()


__all__ = [
    "setup",
    "init_db",
    "on_apprenti_event",
    "check_milestones",
    "get_duo_status",
    "build_duo_panel",
]
