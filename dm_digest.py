"""
dm_digest.py — Hub central de notifications DM (Phase 152).

🎯 OBJECTIF : éviter le spam DM des 6+ modules qui envoient des DMs
séparés (dormant, comeback, daily quest push, achievements, raid alert,
owner alert, 2FA). Centralise en :

1. **DMs URGENTS** (envoi immédiat) :
   - 2FA confirm (60s timeout)
   - Raid alert (sécurité owner)
   - Webhook leak (critique)
   - Sanction prononcée (mute/kick/ban)

2. **DMs DIGEST** (1× par jour à 18h FR, regroupés) :
   - Quêtes terminées à claim
   - Drops saisonniers obtenus
   - Achievements débloqués
   - Hauts faits franchis
   - Comeback rewards
   - Saga update (nouvelle phase débloquée)
   - Personal events (gift, tip, etc.)

Chaque user a un budget : 1 DM digest/jour MAX (sauf urgences).
Opt-in granulaire via /profile → bouton "Mes DMs".

DB tables :
- dm_digest_queue (id PK, guild_id, user_id, category, content_md,
                   created_at, sent_at, status)
- dm_digest_prefs (guild_id, user_id, urgent_enabled, digest_enabled,
                   digest_hour, last_digest_at)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- enqueue(guild_id, user_id, category, content_md, urgent=False)
- send_urgent_now(member, content_md, view=None) -> bool
- send_digest_for_user(member) -> int (nb items envoyés)
- digest_dispatch_task (daily 18h FR)
- get_prefs(user_id) -> dict
- toggle_category(user_id, category) -> dict
- build_prefs_panel(member) -> LayoutView

⚠️ RULES.md : aucun contenu romantique. Si un user a opt-out d'une
catégorie, on respecte. Si un user a DMs fermés, fail-open silencieux.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button, View

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

# Catégories du digest (toutes opt-out possibles sauf urgent_security)
CATEGORIES = {
    "quest_ready":      ("🎯", "Quêtes à réclamer"),
    "drop_collected":   ("🌸", "Drops saisonniers"),
    "achievement":      ("🏆", "Hauts faits débloqués"),
    "comeback":         ("🎉", "Reward retour"),
    "saga_update":      ("📜", "Saga active"),
    "personal_event":   ("🎁", "Events personnels"),
    "level_up":         ("⭐", "Level up"),
    "alliance":         ("🤝", "Activité alliance"),
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
                CREATE TABLE IF NOT EXISTS dm_digest_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    content_md TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dm_digest_prefs (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    digest_enabled INTEGER DEFAULT 0,
                    digest_hour INTEGER DEFAULT 18,
                    last_digest_at TIMESTAMP,
                    opt_out_categories TEXT DEFAULT '[]',
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_digest_queue_user "
                "ON dm_digest_queue(user_id, status, created_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[dm_digest init_db] {ex}")


# ─── Prefs ──────────────────────────────────────────────────────────────────

async def get_prefs(guild_id: int, user_id: int) -> dict:
    """Récupère les prefs DM (avec defaults si absent)."""
    out = {
        # Phase 251.9 : OPT-IN STRICT — aucun DM digest tant que l'user ne l'a pas
        # activé explicitement (bouton « Activer le récap »). Conforme à la règle
        # « tous les DM en opt-in ». (Avant : True = opt-out = DM par défaut.)
        "digest_enabled": False,
        "digest_hour": 18,
        "last_digest_at": None,
        "opt_out_categories": [],
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT digest_enabled, digest_hour, last_digest_at, "
                "opt_out_categories FROM dm_digest_prefs "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            out["digest_enabled"] = bool(row[0])
            out["digest_hour"] = int(row[1] or 18)
            out["last_digest_at"] = row[2]
            try:
                out["opt_out_categories"] = json.loads(row[3] or "[]")
            except Exception:
                out["opt_out_categories"] = []
    except Exception:
        pass
    return out


async def toggle_category(
    guild_id: int, user_id: int, category: str
) -> dict:
    """Toggle on/off une catégorie pour ce user. Renvoie les nouvelles prefs."""
    if _get_db is None or category not in CATEGORIES:
        return await get_prefs(guild_id, user_id)
    try:
        prefs = await get_prefs(guild_id, user_id)
        opt_out = set(prefs.get("opt_out_categories", []))
        if category in opt_out:
            opt_out.discard(category)
        else:
            opt_out.add(category)
        opt_out_list = sorted(opt_out)

        async with _get_db() as db:
            await db.execute(
                "INSERT INTO dm_digest_prefs "
                "(guild_id, user_id, opt_out_categories) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "opt_out_categories = ?",
                (
                    guild_id, user_id,
                    json.dumps(opt_out_list),
                    json.dumps(opt_out_list),
                ),
            )
            await db.commit()
        prefs["opt_out_categories"] = opt_out_list
        return prefs
    except Exception as ex:
        print(f"[dm_digest toggle_category] {ex}")
        return await get_prefs(guild_id, user_id)


async def set_digest_enabled(guild_id: int, user_id: int, enabled: bool) -> bool:
    """Active / coupe le récap DM quotidien (interrupteur MAÎTRE opt-in, Phase 251.9).
    Tant que ce n'est pas True, `send_digest_for_user` ne DM rien. Renvoie l'état posé."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO dm_digest_prefs (guild_id, user_id, digest_enabled) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET digest_enabled = ?",
                (guild_id, user_id, 1 if enabled else 0, 1 if enabled else 0),
            )
            await db.commit()
        return bool(enabled)
    except Exception as ex:
        print(f"[dm_digest set_digest_enabled] {ex}")
        return False


# ─── Enqueue ───────────────────────────────────────────────────────────────

async def enqueue(
    guild_id: int, user_id: int, category: str, content_md: str,
    urgent: bool = False,
) -> bool:
    """Ajoute un item au digest (ou envoie urgent immédiatement)."""
    if _get_db is None:
        return False
    if category not in CATEGORIES and not urgent:
        return False

    # Check opt-out
    prefs = await get_prefs(guild_id, user_id)
    if not urgent and category in prefs.get("opt_out_categories", []):
        return False  # User a opt-out cette catégorie

    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO dm_digest_queue "
                "(guild_id, user_id, category, content_md) "
                "VALUES (?, ?, ?, ?)",
                (guild_id, user_id, category, content_md[:1000]),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[dm_digest enqueue] {ex}")
        return False


async def send_urgent_now(
    member: discord.Member, content_md: str,
    view: Optional[View] = None,
) -> bool:
    """Envoie un DM urgent immédiatement (2FA, raid alert, etc.)."""
    if member is None or member.bot:
        return False
    try:
        if view is not None:
            await member.send(content=content_md, view=view)
        else:
            await member.send(content=content_md)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
    except Exception as ex:
        print(f"[dm_digest send_urgent_now] {ex}")
        return False


# ─── Send digest ────────────────────────────────────────────────────────────

async def send_digest_for_user(member: discord.Member) -> int:
    """Envoie le digest accumulé pour un user. Renvoie le nb d'items envoyés.
    Mark items as sent."""
    # Phase 257 : DIGEST MP DÉSACTIVÉ (directive owner — zéro MP membre).
    return 0
    if member is None or member.bot or _get_db is None or _v2 is None:
        return 0
    try:
        prefs = await get_prefs(member.guild.id, member.id)
        if not prefs.get("digest_enabled", True):
            return 0

        # Récupère les items pending
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, category, content_md FROM dm_digest_queue "
                "WHERE guild_id=? AND user_id=? AND status='pending' "
                "ORDER BY created_at ASC LIMIT 20",
                (member.guild.id, member.id),
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return 0

        # Group par catégorie
        by_cat: dict[str, list[str]] = {}
        ids = []
        for r in rows:
            ids.append(int(r[0]))
            cat = r[1] or "personal_event"
            by_cat.setdefault(cat, []).append(r[2] or "")

        # Build panel V2
        LayoutView = _v2['LayoutView']
        v2_title = _v2['v2_title']
        v2_subtitle = _v2['v2_subtitle']
        v2_body = _v2['v2_body']
        v2_divider = _v2['v2_divider']
        v2_container = _v2['v2_container']

        items = []
        items.append(v2_title("🌟  Ton récap du jour"))
        items.append(v2_subtitle(
            f"_Serveur **{member.guild.name}** · "
            f"{len(rows)} notification(s)_"
        ))
        items.append(v2_divider())

        for cat in CATEGORIES.keys():
            entries = by_cat.get(cat)
            if not entries:
                continue
            emoji, label = CATEGORIES[cat]
            items.append(v2_body(f"{emoji} **{label}** ({len(entries)})"))
            # Cap à 3 entries par catégorie pour pas spammer
            for entry in entries[:3]:
                items.append(v2_body(f"• {entry[:200]}"))
            if len(entries) > 3:
                items.append(v2_body(f"_+ {len(entries) - 3} autre(s)…_"))

        items.append(v2_divider())
        items.append(v2_body(
            "_💡 Configure tes notifs via le bouton ❓ dans /hub._"
        ))

        class _DigestPanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(v2_container(*items, color=0xF1C40F))

        # Envoie
        try:
            await member.send(view=_DigestPanel())
        except (discord.Forbidden, discord.HTTPException):
            return 0

        # Mark sent
        async with _get_db() as db:
            placeholders = ",".join("?" * len(ids))
            await db.execute(
                f"UPDATE dm_digest_queue SET status='sent', "
                f"sent_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                ids,
            )
            await db.execute(
                "INSERT INTO dm_digest_prefs (guild_id, user_id, "
                "last_digest_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "last_digest_at = CURRENT_TIMESTAMP",
                (member.guild.id, member.id),
            )
            await db.commit()
        return len(rows)
    except Exception as ex:
        print(f"[dm_digest send_digest_for_user] {ex}")
        return 0


# ─── Task ───────────────────────────────────────────────────────────────────

@tasks.loop(minutes=15)
async def digest_dispatch_task():
    """Task qui tourne toutes les 15min et vérifie si on est à l'heure
    prévue (18h FR par défaut, configurable par user)."""
    try:
        if _bot is None or _get_db is None:
            return
        # Heure courante Paris
        if _PARIS_TZ is not None:
            now_paris = datetime.now(_PARIS_TZ)
        else:
            now_paris = datetime.now(timezone.utc) + timedelta(hours=2)
        hour = now_paris.hour
        # On dispatch dans la fenêtre 18h00-18h59 (1×/jour grace au cooldown)
        if hour != 18:
            return

        # Pour chaque user qui a des items pending et n'a pas eu son digest
        # aujourd'hui
        async with _get_db() as db:
            async with db.execute(
                "SELECT DISTINCT q.guild_id, q.user_id FROM dm_digest_queue q "
                "LEFT JOIN dm_digest_prefs p "
                "ON p.guild_id=q.guild_id AND p.user_id=q.user_id "
                "WHERE q.status='pending' AND "
                "(p.last_digest_at IS NULL OR "
                " p.last_digest_at < date('now', 'start of day'))",
                (),
            ) as cur:
                pending = await cur.fetchall()

        sent_total = 0
        for guild_id, user_id in pending[:50]:  # max 50/run pour pas spammer
            guild = _bot.get_guild(int(guild_id))
            if not guild:
                continue
            member = guild.get_member(int(user_id))
            if not member:
                continue
            n = await send_digest_for_user(member)
            sent_total += 1 if n > 0 else 0
            await asyncio.sleep(2)  # throttle 2s entre DMs

        if sent_total > 0:
            print(f"[dm_digest] dispatch OK : {sent_total} digest(s) envoye(s)")
    except Exception as ex:
        print(f"[digest_dispatch_task] {ex}")


@digest_dispatch_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ─── Panel preferences ─────────────────────────────────────────────────────

def build_prefs_panel(member: discord.Member):
    """LayoutView pour configurer les prefs DM. À insérer dans /profile."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _PrefsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=180)
            self.member = member

        async def populate(self):
            prefs = await get_prefs(member.guild.id, member.id)
            opt_out = set(prefs.get("opt_out_categories", []))
            digest_on = bool(prefs.get("digest_enabled", False))
            items = []
            items.append(v2_title("🔔  Mes DMs"))
            items.append(v2_body(
                "_Récap quotidien en DM (18h FR) de TON activité. **Opt-in** : tu "
                "ne reçois **rien** tant que tu ne l'as pas activé ci-dessous._"
            ))
            items.append(v2_body(
                f"**Récap quotidien : {'🔔 ACTIVÉ' if digest_on else '🔕 désactivé'}**"
            ))
            items.append(v2_divider())
            for cat_key, (emoji, label) in CATEGORIES.items():
                status = "🔇 OFF" if cat_key in opt_out else "🔔 ON"
                items.append(v2_body(f"{emoji} {label} — `{status}`"))
            self.add_item(v2_container(*items, color=0x3498DB))

            # Boutons toggle par catégorie — Phase 235.5 : groupés en ActionRow
            # (bouton nu interdit top-level LayoutView = 400 50035 ; max 5/row).
            _btns = []
            for i, (cat_key, (emoji, label)) in enumerate(CATEGORIES.items()):
                btn = Button(
                    label=label[:20],
                    emoji=emoji,
                    style=(
                        discord.ButtonStyle.secondary if cat_key in opt_out
                        else discord.ButtonStyle.primary
                    ),
                    custom_id=f"digest_toggle_{member.id}_{cat_key}",
                )

                async def _cb(i_inter: discord.Interaction, k=cat_key):
                    if i_inter.user.id != member.id:
                        return await i_inter.response.send_message(
                            "🔒 Pas pour toi.", ephemeral=True
                        )
                    await toggle_category(
                        i_inter.guild.id, member.id, k
                    )
                    await i_inter.response.send_message(
                        f"✅ Préférence mise à jour pour `{k}`. "
                        "Réouvre le panel pour voir l'état actuel.",
                        ephemeral=True,
                    )

                btn.callback = _cb
                _btns.append(btn)
            for _k in range(0, len(_btns), 5):
                self.add_item(discord.ui.ActionRow(*_btns[_k:_k + 5]))

            # Phase 251.9 : interrupteur MAÎTRE opt-in (active/coupe tout le récap DM).
            master_btn = Button(
                label=("Couper le récap quotidien" if digest_on
                       else "Activer le récap quotidien"),
                emoji="🔔",
                style=(discord.ButtonStyle.danger if digest_on
                       else discord.ButtonStyle.success),
                custom_id=f"digest_master_{member.id}",
            )

            async def _master_cb(i_inter: discord.Interaction):
                if i_inter.user.id != member.id:
                    return await i_inter.response.send_message(
                        "🔒 Pas pour toi.", ephemeral=True)
                new_state = await set_digest_enabled(
                    i_inter.guild.id, member.id, not digest_on)
                await i_inter.response.send_message(
                    ("✅ Récap quotidien **activé** — tu recevras ton récap à 18h FR. "
                     "Réouvre le panel pour gérer les catégories."
                     if new_state else
                     "🔕 Récap quotidien **coupé** — plus aucun DM de récap."),
                    ephemeral=True,
                )

            master_btn.callback = _master_cb
            self.add_item(discord.ui.ActionRow(master_btn))

    return _PrefsPanel()


__all__ = [
    "setup",
    "init_db",
    "enqueue",
    "send_urgent_now",
    "send_digest_for_user",
    "digest_dispatch_task",
    "get_prefs",
    "toggle_category",
    "build_prefs_panel",
    "CATEGORIES",
]
