"""
world_invasion.py — Raid d'invasion mensuel multi-mobs (Phase 169.3).

🎯 OBJECTIF : créer 1 moment fort par mois où le serveur entier doit
coopérer. 5 mobs élite spawn simultanément, communauté coordonne, drops
massifs si tous tués en 30 min.

Mécanique :
- 1er samedi du mois à 21h FR
- 5 mobs élite spawn dans l'arène simultanément
- 30 min pour tous les tuer
- Tous les attackers reçoivent un drop garanti (1 item rare)
- Top 3 dégâts cumulés sur toute l'invasion → drop légendaire
- Si timeout sans tout tuer → coffret consolation pour les attackers
- Bonus alliance : +30% drop qualité si 3+ membres d'alliance participent

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- init_db()
- monthly_invasion_task (loop hourly, check 1st sat 21h FR)

DB :
- invasion_events (id PK, guild_id, started_at, ended_at, mobs_killed,
                   status, total_attackers)
- invasion_attackers (event_id, user_id, total_damage)

Réutilise mob_hunts.MOB_CATALOG pour les mobs élite (HP × 5 forcé).
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
import ui_v2  # design-system V2 partagé (encadrés cohérents)

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
_active_ping_fn = None  # Phase 207 : ping « membres actifs » (injecté par bot.py)
_arena_ensure_fn = None  # Phase 213 : arène de combat PARTAGÉE (mêmes mobs que mob_hunts)
_arena_delete_fn = None  # Phase 233 : async (guild, text_channel_id) -> supprime l'arène à la fin (injecté)
_event_busy_fn = None  # Phase 230 : async (guild_id) -> True si un AUTRE event de combat tourne (injecté)
_report_fn = None  # Phase 235.15 : async (guild, title, body) -> récap consolidé dans « 📜 chroniques-combat »

INVASION_MOBS_COUNT = 5
INVASION_DURATION_MIN = 30
INVASION_HOUR = 21  # 21h FR
ALLIANCE_BONUS_MIN_MEMBERS = 3
ALLIANCE_BONUS_MULT = 1.30

# A.2 — OBJECTIF COLLECTIF : jauge de progression visible (mobs tués / total) +
# prime de GROUPE MODESTE (rétention #1) versée UNE SEULE FOIS si l'objectif est
# atteint (tous les mobs tués). Anti-doublon par colonne group_reward_claimed +
# claim atomique (UPDATE … WHERE group_reward_claimed=0). Éclats jamais mêlés.
GROUP_OBJECTIVE_BONUS_COINS = 250  # prime PAR participant si objectif atteint
_GAUGE_SEGMENTS = 10               # largeur de la barre de progression collective


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
          active_ping_fn=None, arena_ensure_fn=None, event_busy_fn=None,
          arena_delete_fn=None, report_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _active_ping_fn
    global _arena_ensure_fn, _event_busy_fn, _arena_delete_fn, _report_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _active_ping_fn = active_ping_fn
    # Phase 213 : arène de combat PARTAGÉE — l'annonce d'invasion atterrit dans le
    # MÊME salon que ses 5 mobs (mob_hunts spawne dans cette arène partagée).
    _arena_ensure_fn = arena_ensure_fn
    # Phase 230 : verrou global « un seul event de combat à la fois »
    _event_busy_fn = event_busy_fn
    # Phase 233 : suppression de l'arène à la fin de l'invasion (fix fuite C1)
    _arena_delete_fn = arena_delete_fn
    # Phase 235.15 : rapport de fin consolidé → « 📜 chroniques-combat »
    _report_fn = report_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invasion_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    announce_message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    mobs_killed INTEGER DEFAULT 0,
                    total_attackers INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invasion_attackers (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total_damage INTEGER DEFAULT 0,
                    PRIMARY KEY (event_id, user_id)
                )
            """)
            # A.2 : jauge collective + récompense de groupe. Migration fail-open
            # (ALTER ignoré si la colonne existe déjà — vieux schémas).
            for _col, _ddl in (
                ("progress_message_id",
                 "ALTER TABLE invasion_events ADD COLUMN progress_message_id INTEGER DEFAULT 0"),
                ("group_reward_claimed",
                 "ALTER TABLE invasion_events ADD COLUMN group_reward_claimed INTEGER DEFAULT 0"),
            ):
                try:
                    await db.execute(_ddl)
                except Exception:
                    pass  # colonne déjà présente → no-op
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_invasion_events_active "
                "ON invasion_events(guild_id, status)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[world_invasion init_db] {ex}")


def _is_first_saturday_21h() -> bool:
    """True si on est le 1er samedi du mois à 21h Paris (sans minutes check)."""
    if _PARIS_TZ:
        now = datetime.now(_PARIS_TZ)
    else:
        now = datetime.now(timezone.utc) + timedelta(hours=2)
    # weekday: lundi=0, samedi=5
    if now.weekday() != 5:
        return False
    if now.hour != INVASION_HOUR:
        return False
    # Premier samedi du mois ?
    return now.day <= 7


async def _find_arena_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Trouve le salon arène pour annoncer l'invasion.

    Phase 174.1 : fallback robuste (cohérent avec mob_hunts) — garantit que
    l'invasion mensuelle APPARAÎT même sans salon nommé "arène" :
    1. `combat_arena_channel_id` configuré par owner — préféré
    2. Arène boss raid ACTIVE (table events.arena_channel_id) — temporaire
    3. Recherche par nom "arène/arena/combat/boss/jeu/game/chasse/donjon"
    4-7. Délégation à mob_hunts._find_arena_channel (hub → salon sain →
         system_channel), puis repli inline si mob_hunts indispo.
    8. None seulement si AUCUN salon écrivable (cas extrême).
    """
    if _db_get is None or _get_db is None:
        return None

    # 1. Salon combat configuré par owner
    try:
        cfg_data = await _db_get(guild.id)
        ch_id = int(cfg_data.get("combat_arena_channel_id", 0) or 0)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch:
                return ch
    except Exception:
        pass

    # 2. Arène boss raid active (si un boss tourne)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT arena_channel_id FROM events "
                "WHERE guild_id=? AND ended=0 "
                "ORDER BY id DESC LIMIT 1",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0]:
            ch = guild.get_channel(int(row[0]))
            if ch:
                return ch
    except Exception:
        pass

    # 3. Fallback : recherche par nom
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["arène", "arena", "combat", "boss",
                                 "jeu", "game", "chasse", "donjon"]):
            try:
                if guild.me and ch.permissions_for(guild.me).send_messages:
                    return ch
            except Exception:
                return ch

    # 4-7. Fallback robuste partagé avec mob_hunts (hub → salon sain →
    # system_channel). Garantit que l'invasion mensuelle APPARAÎT toujours.
    try:
        import mob_hunts as _mh
        ch = await _mh._find_arena_channel(guild)
        if ch:
            return ch
    except Exception:
        pass

    # Dernier recours inline (si mob_hunts indispo) : hub puis 1er salon sain
    try:
        cfg_data = await _db_get(guild.id)
        hub_id = int(cfg_data.get("hub_channel", 0) or 0)
        if hub_id:
            ch = guild.get_channel(hub_id)
            if ch and guild.me and ch.permissions_for(guild.me).send_messages:
                return ch
    except Exception:
        pass
    _avoid = ("ticket", "log", "annonce", "règl", "regl", "rule",
              "staff", "admin", "lecture", "read-only")
    try:
        for ch in guild.text_channels:
            n = (ch.name or "").lower()
            if any(a in n for a in _avoid):
                continue
            if guild.me and ch.permissions_for(guild.me).send_messages:
                return ch
    except Exception:
        pass
    try:
        if guild.system_channel and guild.me and \
                guild.system_channel.permissions_for(guild.me).send_messages:
            return guild.system_channel
    except Exception:
        pass
    return None


async def trigger_invasion(guild: discord.Guild) -> bool:
    """Déclenche une invasion : 5 mobs élite + annonce + cleanup task."""
    if not guild or _get_db is None or _bot is None:
        return False

    # Phase 191 : interrupteur Hub Événements — Invasion mondiale
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('world_invasion_enabled', True)):
            return False
    except Exception:
        pass

    # Anti-doublon : pas 2 invasions par mois
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM invasion_events "
                "WHERE guild_id=? AND "
                "datetime(started_at) > datetime('now', '-25 days')",
                (guild.id,),
            ) as cur:
                if await cur.fetchone():
                    return False
    except Exception:
        pass

    # Phase 230 : VERROU GLOBAL — pas d'invasion par-dessus un autre event de
    # combat en cours (boss raid / quiz / world boss / boss du jour / climax).
    # Un seul à la fois. Fail-open si l'injection manque.
    if _event_busy_fn is not None:
        try:
            if await _event_busy_fn(guild.id):
                return False
        except Exception:
            pass

    # Phase 213 : on annonce dans l'arène de combat PARTAGÉE (où mob_hunts fait
    # spawner les 5 mobs élite) → annonce + mobs regroupés. Fail-open : si l'arène
    # partagée est indispo (perm/échec), on retombe sur la résolution habituelle.
    ch = None
    if _arena_ensure_fn is not None:
        try:
            ch = await _arena_ensure_fn(guild)
        except Exception as ex:
            print(f"[world_invasion arena ensure] {ex}")
    if ch is None:
        ch = await _find_arena_channel(guild)
    if not ch:
        return False

    # Crée l'event
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO invasion_events (guild_id, channel_id) VALUES (?, ?)",
                (guild.id, ch.id),
            )
            event_id = cur.lastrowid
            await db.commit()
    except Exception as ex:
        print(f"[world_invasion trigger INSERT] {ex}")
        return False

    # Annonce
    announce_text = (
        f"🚨 **Invasion du serveur !**\n"
        f"**{INVASION_MOBS_COUNT} mobs élite** dans l'arène · "
        f"**{INVASION_DURATION_MIN} min** pour tous les vaincre.\n"
        f"-# Drop garanti pour tous · top 3 dégâts = légendaire · +30% qualité à 3+ alliés."
    )
    msg = None
    try:
        msg = await ch.send(content=announce_text)
        async with _get_db() as db:
            await db.execute(
                "UPDATE invasion_events SET announce_message_id=? WHERE id=?",
                (msg.id, event_id),
            )
            await db.commit()
    except Exception:
        pass

    # Phase 207 : ping des MEMBRES ACTIFS — une invasion (mensuelle) DOIT être
    # vue, sinon les 5 mobs élite spawnent dans le vide. Rotation + opt-out +
    # auto-suppression gérés par le helper. Cap large : c'est un rassemblement.
    if _active_ping_fn is not None:
        try:
            await _active_ping_fn(
                guild, ch, cap=10, cleanup_seconds=INVASION_DURATION_MIN * 60,
                intro="🚨 **INVASION DU SERVEUR** — tous à l'arène,", notif_key='invasion')
        except Exception as ex:
            print(f"[world_invasion active_ping] {ex}")

    # Difficulté dynamique (FAIL-OPEN strict, additif) : les mobs élite de
    # l'invasion voient leurs PV adaptés à la foule (facteur BORNÉ [0.7..2.0]).
    # La moindre erreur → facteur 1.0 (PV de base actuels, mobs inchangés).
    _crowd_factor = 1.0
    try:
        import activity_system as _act
        _crowd_factor = await _act.crowd_hp_factor(guild)
    except Exception as ex:
        print(f"[world_invasion crowd_hp] {ex}")
        _crowd_factor = 1.0

    # Spawn 5 mobs via mob_hunts
    try:
        import mob_hunts as mh
        pool = mh.MOB_CATALOG[:]
        random.shuffle(pool)
        spawned = 0
        for _ in range(INVASION_MOBS_COUNT):
            # Force élite et mark via DB que c'est un mob d'invasion
            # via une convention : on tagge avec un commentaire dans le name
            # FIX salons : on REGROUPE les mobs dans le salon dédié de l'invasion
            # (« 🚨-invasion ») au lieu de laisser chaque mob créer son « 🐗-mob ».
            try:
                await mh.spawn_mob(guild, hp_factor=_crowd_factor, channel=ch)
                spawned += 1
            except Exception:
                pass
        print(
            f"[world_invasion] guild={guild.id} event={event_id} "
            f"spawned={spawned}/{INVASION_MOBS_COUNT}"
        )
    except Exception as ex:
        print(f"[world_invasion spawn mobs] {ex}")

    # A.2 — JAUGE COLLECTIVE : panneau de progression LIVE (LayoutView) dans
    # l'arène, juste après l'annonce. Affiche « X / N mobs vaincus » + barre +
    # objectif de groupe. Mis à jour à chaque kill via note_mob_killed(). Fail-safe :
    # une erreur ici n'empêche JAMAIS l'invasion (le combat tourne sans la jauge).
    try:
        gauge_view = _build_invasion_progress_view(0, INVASION_MOBS_COUNT)
        if gauge_view is not None:
            pmsg = await ch.send(view=gauge_view)
            if pmsg:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE invasion_events SET progress_message_id=? WHERE id=?",
                        (pmsg.id, event_id),
                    )
                    await db.commit()
    except Exception as ex:
        print(f"[world_invasion gauge post] {ex}")

    # Schedule resolve dans 30 min
    asyncio.create_task(_resolve_invasion_after(event_id, INVASION_DURATION_MIN * 60))
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  A.2 — Objectif collectif : jauge de progression + prime de groupe
# ═══════════════════════════════════════════════════════════════════════════

def _progress_bar(done: int, total: int, *, segments: int = _GAUGE_SEGMENTS) -> str:
    """Barre de progression collective (█/░). FAIL-SAFE : borne tout."""
    try:
        total = max(1, int(total))
        done = max(0, min(int(done), total))
        fill = int(round(segments * done / total))
        fill = max(0, min(segments, fill))
        return "█" * fill + "░" * (segments - fill)
    except Exception:
        return "░" * segments


def _build_invasion_progress_view(killed: int, total: int):
    """Construit le panneau LayoutView de progression collective de l'invasion.

    Renvoie une StaticPanel (sans bouton → zéro « Échec interaction ») ou None
    si la construction échoue (fail-safe : l'invasion tourne sans la jauge)."""
    try:
        killed = max(0, min(int(killed), int(total)))
        total = max(1, int(total))
        done = killed >= total
        bar = _progress_bar(killed, total)
        pct = int(round(100 * killed / total))
        if done:
            head = "🏆 Objectif collectif ATTEINT !"
            tail = (
                f"Les **{total} mobs élite** sont vaincus — le serveur tient bon.\n"
                f"🎁 Prime de groupe : **+{GROUP_OBJECTIVE_BONUS_COINS}** 🪙 "
                f"pour chaque participant."
            )
            color = ui_v2.Palette.SUCCESS
        else:
            head = "🛡️ Objectif collectif — repoussez l'invasion"
            tail = (
                f"Vainquez **les {total} mobs élite** ensemble avant la fin du "
                f"chrono pour débloquer la prime de groupe "
                f"(**+{GROUP_OBJECTIVE_BONUS_COINS}** 🪙 / participant)."
            )
            color = ui_v2.Palette.PRIMARY
        body = (
            f"### {head}\n"
            f"`{bar}`  **{killed} / {total}** mobs vaincus · {pct} %\n\n"
            f"{tail}"
        )
        return ui_v2.recap_view("👹 Invasion du serveur", body, color=color)
    except Exception as ex:
        print(f"[world_invasion build gauge] {ex}")
        return None


async def _count_invasion_kills(gid: int) -> int:
    """Nombre de mobs tués dans la fenêtre d'invasion courante. FAIL-SAFE → 0."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM mob_spawns "
                "WHERE guild_id=? AND status='killed' AND "
                "datetime(killed_at) > datetime('now', ?) "
                "AND datetime(spawned_at) > datetime('now', ?)",
                (gid, f"-{INVASION_DURATION_MIN + 5} minutes",
                 f"-{INVASION_DURATION_MIN + 5} minutes"),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


async def note_mob_killed(guild) -> None:
    """Hook LIVE (fail-open) appelé par mob_hunts quand UN mob tombe : si une
    invasion est active dans cette guild, rafraîchit la jauge collective.

    Contrainte combat : ne JAMAIS lever — une erreur ici ne doit pas perturber la
    résolution d'un kill de mob normal. Silencieux si pas d'invasion active."""
    if guild is None or _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, channel_id, progress_message_id FROM invasion_events "
                "WHERE guild_id=? AND status='active' "
                "ORDER BY id DESC LIMIT 1",
                (int(guild.id),),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return  # pas d'invasion active → rien à faire
        _eid, ch_id, pmsg_id = int(row[0]), int(row[1] or 0), int(row[2] or 0)
        if not ch_id or not pmsg_id:
            return
        killed = await _count_invasion_kills(int(guild.id))
        view = _build_invasion_progress_view(killed, INVASION_MOBS_COUNT)
        if view is None:
            return
        ch = guild.get_channel(ch_id)
        if ch is None:
            return
        # Édition via PartialMessage (PATCH seul, zéro GET) — anti-429.
        try:
            pm = ch.get_partial_message(pmsg_id)
            await pm.edit(view=view)
        except Exception:
            pass
    except Exception as ex:
        print(f"[world_invasion note_mob_killed] {ex}")


async def _resolve_invasion_after(event_id: int, seconds: int):
    """Après timeout, résout l'invasion (compte kills, distribue rewards)."""
    await asyncio.sleep(seconds)
    if _get_db is None or _bot is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id, status, announce_message_id, "
                "progress_message_id FROM invasion_events WHERE id=?",
                (event_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row or row[2] != "active":
            return
        gid, ch_id, _, _announce_msg_id, _progress_msg_id = row
        guild = _bot.get_guild(int(gid))
        if not guild:
            return

        # Compte les mobs tués dans cette fenêtre
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM mob_spawns "
                    "WHERE guild_id=? AND status='killed' AND "
                    "datetime(killed_at) > datetime('now', ?) "
                    "AND datetime(spawned_at) > datetime('now', ?)",
                    (gid, f"-{INVASION_DURATION_MIN + 5} minutes",
                     f"-{INVASION_DURATION_MIN + 5} minutes"),
                ) as cur:
                    cnt_row = await cur.fetchone()
            mobs_killed = int(cnt_row[0] or 0) if cnt_row else 0
        except Exception:
            mobs_killed = 0

        # Récolte les top attackers via mob_attackers
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT ma.user_id, SUM(ma.damage_dealt) as total_dmg "
                    "FROM mob_attackers ma "
                    "JOIN mob_spawns ms ON ma.mob_id = ms.id "
                    "WHERE ms.guild_id=? AND "
                    "datetime(ms.spawned_at) > datetime('now', ?) "
                    "GROUP BY ma.user_id "
                    "ORDER BY total_dmg DESC LIMIT 50",
                    (gid, f"-{INVASION_DURATION_MIN + 5} minutes"),
                ) as cur:
                    top_attackers = await cur.fetchall()
        except Exception:
            top_attackers = []

        all_killed = mobs_killed >= INVASION_MOBS_COUNT

        # Distribute rewards
        rewards: list[dict] = []
        for i, (uid, total_dmg) in enumerate(top_attackers):
            uid = int(uid)
            total_dmg = int(total_dmg or 0)
            is_top3 = i < 3
            # Base : 500c + 50c par mob tué (si tous tués) ou 200c (sinon)
            base = 500 + (50 * mobs_killed) if all_killed else 200
            # Top 3 : ×3 + label "légendaire"
            if is_top3 and all_killed:
                base *= 3
            try:
                if _add_coins:
                    await _add_coins(gid, uid, base)
            except Exception:
                pass
            rewards.append({
                "user_id": uid, "damage": total_dmg,
                "coins": base, "is_top3": is_top3 and all_killed,
            })
            # INSERT in invasion_attackers
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT OR REPLACE INTO invasion_attackers "
                        "(event_id, user_id, total_damage) VALUES (?, ?, ?)",
                        (event_id, uid, total_dmg),
                    )
                    await db.commit()
            except Exception:
                pass

        # Mark resolved
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE invasion_events SET status=?, ended_at=CURRENT_TIMESTAMP, "
                    "mobs_killed=?, total_attackers=? WHERE id=?",
                    (
                        "success" if all_killed else "timeout",
                        mobs_killed, len(top_attackers), event_id,
                    ),
                )
                await db.commit()
        except Exception:
            pass

        # A.2 — PRIME DE GROUPE (objectif collectif atteint) : versée UNE SEULE
        # FOIS, à CHAQUE participant, si tous les mobs sont tombés. Récompense
        # MODESTE (rétention #1). Anti-doublon : CLAIM ATOMIQUE via la colonne
        # group_reward_claimed (UPDATE … WHERE …=0 + rowcount==1) AVANT tout crédit
        # → impossible de re-payer (résolution rejouée / reboot). Crédits via le
        # helper existant add_coins uniquement (atomique). FAIL-SAFE.
        group_bonus_paid = False
        if all_killed and _add_coins is not None:
            _claimed = False
            try:
                async with _get_db() as db:
                    _gc = await db.execute(
                        "UPDATE invasion_events SET group_reward_claimed=1 "
                        "WHERE id=? AND group_reward_claimed=0",
                        (event_id,),
                    )
                    await db.commit()
                _claimed = getattr(_gc, "rowcount", 0) == 1
            except Exception:
                _claimed = False  # claim plante → on NE paie PAS (anti double-paie)
            if _claimed:
                for r in rewards:
                    try:
                        await _add_coins(gid, int(r["user_id"]), GROUP_OBJECTIVE_BONUS_COINS)
                        r["coins"] = int(r.get("coins", 0) or 0) + GROUP_OBJECTIVE_BONUS_COINS
                    except Exception:
                        pass
                group_bonus_paid = True

        # Post résolution
        ch = guild.get_channel(int(ch_id))
        if ch:
            await _post_resolution(ch, all_killed, mobs_killed, rewards,
                                   group_bonus_paid=group_bonus_paid)
            # Phase 235.15 : effacer le PANNEAU d'annonce live → le salon de combat
            # permanent se vide entre deux events (demande owner). Le récap persiste
            # dans « 📜 chroniques-combat » (via _post_resolution).
            if _announce_msg_id:
                try:
                    _amsg = await ch.fetch_message(int(_announce_msg_id))
                    await _amsg.delete()
                except Exception:
                    pass
            # A.2 : effacer aussi le panneau de jauge collective (le récap consolidé
            # le remplace dans « 📜 chroniques-combat »). Fail-safe.
            if _progress_msg_id:
                try:
                    await ch.get_partial_message(int(_progress_msg_id)).delete()
                except Exception:
                    pass
        # Phase 233 (fix fuite C1) : supprimer l'arène d'invasion (catégorie + salons)
        # — avant, elle traînait jusqu'au prochain boot. Délai pour lire le récap.
        if _arena_delete_fn is not None and ch_id:
            try:
                asyncio.create_task(_arena_delete_fn(guild, int(ch_id), grace_seconds=120))
            except Exception:
                pass
    except Exception as ex:
        print(f"[_resolve_invasion_after] {ex}")


async def _post_resolution(
    ch: discord.TextChannel, all_killed: bool, mobs_killed: int,
    rewards: list[dict], *, group_bonus_paid: bool = False,
):
    """Poste le récap de fin d'invasion."""
    if not ch:
        return

    if all_killed:
        title = "🏆 **Invasion repoussée !**"
        subtitle = (
            f"Les {INVASION_MOBS_COUNT} mobs élite ont été vaincus à temps. "
            f"Le serveur est sauf !"
        )
        # A.2 : objectif collectif atteint → prime de groupe versée à tous.
        if group_bonus_paid:
            subtitle += (
                f"\n🎯 **Objectif collectif atteint** : prime de groupe "
                f"**+{GROUP_OBJECTIVE_BONUS_COINS}** 🪙 pour chaque participant."
            )
    else:
        title = "💀 **Invasion : échec partiel**"
        subtitle = (
            f"Seulement {mobs_killed}/{INVASION_MOBS_COUNT} mobs vaincus. "
            f"Récompenses de consolation distribuées."
        )

    lines = [title, "", subtitle, ""]

    if rewards:
        lines.append("**🏅 Top participants :**")
        for r in rewards[:10]:
            member = ch.guild.get_member(r["user_id"])
            name = member.display_name if member else f"User {r['user_id']}"
            badge = " 🥇" if r["is_top3"] else ""
            lines.append(
                f"• **{name}**{badge} : `{r['coins']}` 🪙 "
                f"_(`{r['damage']}` dmg total)_"
            )
        if len(rewards) > 10:
            lines.append(f"_+ {len(rewards) - 10} autres participants récompensés._")
    else:
        lines.append("_Aucun participant n'a attaqué les mobs._")

    _title_clean = lines[0].replace("**", "")
    _body = "\n".join(lines[1:])
    # Phase 235.15 : récap consolidé PERSISTANT → « 📜 chroniques-combat » (journal
    # commun à TOUS les events) = la source unique du récap.
    if _report_fn is not None and getattr(ch, "guild", None):
        try:
            await _report_fn(ch.guild, _title_clean, _body)
        except Exception:
            pass
    # Bref écho dans l'arène (closure pour les combattants), AUTO-supprimé pour ne
    # pas encombrer le salon de combat permanent. Récap COMPACT et BORNÉ identique à
    # tous les events de combat (helper partagé ui_v2.combat_recap_view) : ligne
    # d'état + podium (max 3) + « +N autres récompensés ». L'économie est intacte —
    # tout le monde reste payé, seul l'AFFICHAGE est borné (fail-open).
    try:
        _podium = []
        for r in rewards[:3]:
            _m = ch.guild.get_member(r["user_id"])
            _nm = _m.display_name if _m else f"User {r['user_id']}"
            _podium.append((_nm, r["coins"]))
        _others = max(0, len(rewards) - 3)
        _total_dmg = sum(int(r.get("damage", 0) or 0) for r in rewards) or None
        await ch.send(
            view=ui_v2.combat_recap_view(
                "👹", "Invasion",
                "win" if all_killed else "fail",
                _podium,
                others_count=_others,
                participants=len(rewards),
                total_damage=_total_dmg,
            ),
            delete_after=3 * 3600)
    except Exception:
        pass


# ─── Monthly task ──────────────────────────────────────────────────────────

@tasks.loop(hours=1)
async def monthly_invasion_task():
    """Toutes les heures : check si 1er samedi 21h FR. Si oui, trigger."""
    if _bot is None or _get_db is None:
        return
    try:
        if not _is_first_saturday_21h():
            return
        for guild in _bot.guilds:
            try:
                await trigger_invasion(guild)
            except Exception as ex:
                print(f"[invasion task g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[monthly_invasion_task] {ex}")


@monthly_invasion_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "trigger_invasion",
    "monthly_invasion_task",
]
