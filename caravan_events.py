"""
caravan_events.py — Phase 256 Lot 3 : « La Caravane des Trois Sceaux » (collaboratif).

Une caravane de reliques traverse Abylumis. Pour avancer d'une étape, ses **3 sceaux**
— 🎒 Porteur / 🛡️ Gardien / 🔭 Éclaireur — doivent être tenus EN MÊME TEMPS par
**3 joueurs DIFFÉRENTS**. Un joueur ne peut tenir qu'UN seul sceau. Chaque sceau se
relâche après 90 s → il faut une vraie coordination simultanée (impossible en solo).

Verrou d'ACTIVITÉ : tenir un sceau demande le palier 🟢 (3 pts / 14 j, messages OU
vocal) — fail-open. 100 % TEXTE, aucun vocal créé, aucun salon masqué. Garde-fous
Discord (cooldown/joueur avant defer ; refresh throttlé get_partial_message ; boutons
persistants DynamicItem ; écritures DB atomiques ; récompenses claim-once fail-closed ;
salon ⚔️-combat partagé déclaré dans _has_any_major_event_running ; boot cleanup).
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

import discord
from discord.ui import Button
from discord.ext import tasks

import activity_system as _act

# ─── Dépendances injectées ────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None
_active_ping_fn = None
_arena_create_fn = None
_arena_delete_fn = None
_report_fn = None
_event_busy_fn = None

# ─── Réglages (modestes) ──────────────────────────────────────────────────────
_EVENT_TYPE = "caravan"
_STAGES_TARGET = 5
_HOLD_SECONDS = 90            # durée de tenue d'un sceau (epoch)
_DURATION_MIN = 20
_CLICK_CD = 3.0
_REFRESH_MIN = 4.0
_SPAWN_COOLDOWN_H = 2.0
_SPAWN_CHANCE = 0.22
_BASE_REWARD = 80
_PER_STAGE = 25
_COLOR = 0xE67E22

_ROLES = ["porteur", "gardien", "eclaireur"]
_ROLE_META = {"porteur": ("🎒", "Porteur"), "gardien": ("🛡️", "Gardien"),
              "eclaireur": ("🔭", "Éclaireur")}

_last_click: dict = {}        # {(carav_id, user_id): epoch}
_last_refresh: dict = {}      # {carav_id: epoch}


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
          active_ping_fn=None, arena_create_fn=None, arena_delete_fn=None,
          report_fn=None, event_busy_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _active_ping_fn
    global _arena_create_fn, _arena_delete_fn, _report_fn, _event_busy_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _active_ping_fn = active_ping_fn
    _arena_create_fn = arena_create_fn
    _arena_delete_fn = arena_delete_fn
    _report_fn = report_fn
    _event_busy_fn = event_busy_fn
    try:
        bot_instance.add_dynamic_items(CaravanRoleButton)
    except Exception:
        pass


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS caravan_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER, message_id INTEGER,
                    stage INTEGER DEFAULT 0, stages_target INTEGER NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP,
                    ended INTEGER DEFAULT 0, victory INTEGER DEFAULT 0
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_caravan_active "
                "ON caravan_events(guild_id, ended)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS caravan_roles (
                    carav_id INTEGER, role TEXT,
                    holder_id INTEGER, hold_until INTEGER DEFAULT 0,
                    PRIMARY KEY (carav_id, role)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS caravan_contributors (
                    carav_id INTEGER, user_id INTEGER,
                    stages_helped INTEGER DEFAULT 0, rewarded INTEGER DEFAULT 0,
                    PRIMARY KEY (carav_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[caravan init_db] {ex}")


def _bar(cur: int, mx: int, width: int = 12) -> str:
    cur = max(0, int(cur or 0))
    mx = max(1, int(mx or 1))
    filled = max(0, min(width, int(round(width * cur / mx))))
    return "🟧" * filled + "⬜" * (width - filled)


_CARAV_KEYS = ["id", "guild_id", "channel_id", "message_id", "stage",
               "stages_target", "started_at", "ends_at", "ended", "victory"]


async def _get_carav(carav_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, channel_id, message_id, stage, stages_target, "
                "started_at, ends_at, ended, victory FROM caravan_events WHERE id=?",
                (carav_id,)) as c:
                row = await c.fetchone()
        return dict(zip(_CARAV_KEYS, row)) if row else None
    except Exception:
        return None


async def _get_roles(carav_id: int) -> dict:
    """role -> (holder_id|None, hold_until)."""
    out = {}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT role, holder_id, hold_until FROM caravan_roles WHERE carav_id=?",
                (carav_id,)) as c:
                for r in await c.fetchall():
                    out[r[0]] = (r[1], int(r[2] or 0))
    except Exception:
        pass
    return out


def _build_panel(carav: dict, roles: dict):
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    stage = int(carav["stage"] or 0)
    target = int(carav["stages_target"] or _STAGES_TARGET)
    ended = bool(carav["ended"])
    victory = bool(carav["victory"])
    now = int(time.time())

    ends_epoch = 0
    try:
        ed = carav.get("ends_at")
        if ed:
            dt = datetime.fromisoformat(str(ed).replace(" ", "T").split(".")[0])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ends_epoch = int(dt.timestamp())
    except Exception:
        ends_epoch = 0

    items = [
        v2_title("🐫  LA CARAVANE DES TROIS SCEAUX"),
        v2_subtitle("👥 **3 joueurs** tiennent les 3 sceaux EN MÊME TEMPS "
                    "(1 sceau/pers · ~90 s)"),
        v2_divider(),
    ]
    if ended:
        if victory:
            items.append(v2_body(f"✅ **La caravane est arrivée à destination !** "
                                 f"{target}/{target} étapes. Récompenses aux porteurs. 🎉"))
        else:
            items.append(v2_body(f"🌅 **La caravane s'est arrêtée en chemin...** "
                                 f"Étape {stage}/{target}. Il a manqué de la coordination "
                                 f"— petite récompense aux participants."))
    else:
        lines = [f"`{_bar(stage, target)}`  **Étape {stage} / {target}**", ""]
        for r in _ROLES:
            emoji, label = _ROLE_META[r]
            holder, hu = roles.get(r, (None, 0))
            if holder and hu > now:
                lines.append(f"{emoji} **{label}** : <@{int(holder)}> _(tenu <t:{hu}:R>)_")
            else:
                lines.append(f"{emoji} **{label}** : — _libre_ —")
        items.append(v2_body("\n".join(lines)))
        items.append(v2_divider())
        items.append(v2_body(f"⏳ La caravane repart bientôt sans vous — fin <t:{ends_epoch}:R>. "
                             f"Appelez du monde : il faut **3 joueurs en même temps** !"
                             if ends_epoch else
                             "Il faut 3 joueurs en même temps sur les 3 sceaux !"))

    cid = int(carav["id"])

    class _CaravPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=(0x2ECC71 if victory else _COLOR)))
            if not ended:
                btns = []
                for r in _ROLES:
                    emoji, label = _ROLE_META[r]
                    btns.append(Button(label=f"{emoji} {label}",
                                       style=discord.ButtonStyle.secondary,
                                       custom_id=f"carav_role:{cid}:{r}"))
                self.add_item(discord.ui.ActionRow(*btns))

    return _CaravPanel()


async def _refresh_panel(guild, carav_id: int, force: bool = False):
    try:
        if not force:
            now = datetime.now(timezone.utc).timestamp()
            if now - _last_refresh.get(carav_id, 0.0) < _REFRESH_MIN:
                return
            _last_refresh[carav_id] = now
        carav = await _get_carav(carav_id)
        if not carav or not carav.get("channel_id") or not carav.get("message_id"):
            return
        ch = guild.get_channel(int(carav["channel_id"]))
        if not ch:
            return
        roles = await _get_roles(carav_id)
        await ch.get_partial_message(int(carav["message_id"])).edit(
            view=_build_panel(carav, roles))
    except Exception:
        pass


# ─── Spawn ─────────────────────────────────────────────────────────────────────
async def _active_carav_id(guild_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM caravan_events WHERE guild_id=? AND ended=0 LIMIT 1",
                (guild_id,)) as c:
                r = await c.fetchone()
        return int(r[0]) if r else None
    except Exception:
        return None


async def _too_soon(guild_id: int) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM caravan_events WHERE guild_id=? "
                "AND julianday('now') - julianday(started_at) < ? LIMIT 1",
                (guild_id, _SPAWN_COOLDOWN_H / 24.0)) as c:
                return await c.fetchone() is not None
    except Exception:
        return False


async def spawn_caravan(guild: discord.Guild) -> bool:
    if not guild or _get_db is None or _bot is None or _v2 is None:
        return False
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('caravan_enabled', True)):
            return False
    except Exception:
        pass
    if await _active_carav_id(guild.id) is not None:
        return False
    if await _too_soon(guild.id):
        return False
    if _event_busy_fn is not None:
        try:
            if await _event_busy_fn(guild.id):
                return False
        except Exception:
            pass
    ch = None
    if _arena_create_fn is not None:
        try:
            ch = await _arena_create_fn(guild, 'caravan',
                                        "🐫 La Caravane des Trois Sceaux", voice_count=0)
        except Exception as ex:
            print(f"[caravan spawn arena] {ex}")
    if ch is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO caravan_events (guild_id, channel_id, stage, stages_target, "
                "ends_at) VALUES (?,?,0,?, datetime('now', ?))",
                (guild.id, ch.id, _STAGES_TARGET, f"+{_DURATION_MIN} minutes"))
            cid = cur.lastrowid
            for r in _ROLES:
                await db.execute(
                    "INSERT INTO caravan_roles (carav_id, role, holder_id, hold_until) "
                    "VALUES (?,?,NULL,0)", (cid, r))
            await db.commit()
        carav = await _get_carav(cid)
        roles = await _get_roles(cid)
        msg = await ch.send(view=_build_panel(carav, roles))
        async with _get_db() as db:
            await db.execute("UPDATE caravan_events SET message_id=? WHERE id=?",
                             (msg.id, cid))
            await db.commit()
        if _active_ping_fn is not None:
            try:
                await _active_ping_fn(guild, ch, notif_key=_EVENT_TYPE,
                                      intro="🐫 La **Caravane des Trois Sceaux** passe — "
                                            "tenez les 3 sceaux ensemble pour l'escorter !")
            except Exception:
                pass
        return True
    except Exception as ex:
        print(f"[caravan spawn] {ex}")
        return False


# ─── Claim d'un sceau (le bouton) ──────────────────────────────────────────────
async def _handle_role(i: discord.Interaction, carav_id: int, role: str):
    # Phase 257.3 : ACK D'ABORD (defer) — acquitter le clic AVANT toute garde/cooldown,
    # sinon un clic noyé affiche « Échec de l'interaction ». Defer = requête légère ;
    # l'anti-429 reste assuré (un clic noyé ne fait aucun followup).
    try:
        await i.response.defer(ephemeral=True)
    except Exception:
        pass
    if role not in _ROLE_META:
        return
    # Cooldown PAR JOUEUR APRÈS l'ack → clic noyé = AUCUNE erreur + AUCUN followup.
    try:
        key = (carav_id, i.user.id)
        nowf = datetime.now(timezone.utc).timestamp()
        if nowf - _last_click.get(key, 0.0) < _CLICK_CD:
            return
        _last_click[key] = nowf
    except Exception:
        pass
    try:
        if i.guild is None:
            return
        carav = await _get_carav(carav_id)
        if not carav or carav["ended"]:
            return await i.followup.send("🔒 Cette caravane est déjà partie.", ephemeral=True)
        # Verrou d'activité (fail-open).
        try:
            ok, score, needed = await _act.check_gate(i.guild.id, i.user.id, _EVENT_TYPE)
            if not ok:
                return await i.followup.send(_act.block_message(_EVENT_TYPE, score, needed),
                                             ephemeral=True)
        except Exception:
            pass
        uid = i.user.id
        now = int(time.time())
        # Claim ATOMIQUE (interdit 2 sceaux + prise seulement si libre/expiré/déjà à moi).
        async with _get_db() as db:
            async with db.execute(
                "SELECT role FROM caravan_roles WHERE carav_id=? AND holder_id=? AND hold_until>?",
                (carav_id, uid, now)) as c:
                other = await c.fetchone()
            if other and other[0] != role:
                await db.commit()
                return await i.followup.send(
                    f"🤝 Tu tiens déjà le sceau **{_ROLE_META[other[0]][1]}** — "
                    f"laisse les autres à d'autres joueurs !", ephemeral=True)
            cur = await db.execute(
                "UPDATE caravan_roles SET holder_id=?, hold_until=? "
                "WHERE carav_id=? AND role=? AND (holder_id IS NULL OR hold_until<=? OR holder_id=?)",
                (uid, now + _HOLD_SECONDS, carav_id, role, now, uid))
            await db.commit()
            if getattr(cur, "rowcount", 0) != 1:
                return await i.followup.send(
                    "🔒 Ce sceau est déjà tenu par un autre — prends-en un autre !",
                    ephemeral=True)
        # État + roles après le claim.
        roles = await _get_roles(carav_id)
        held = {r: int(h) for r, (h, hu) in roles.items() if h and hu > now}
        stage = int(carav["stage"] or 0)
        target = int(carav["stages_target"] or _STAGES_TARGET)
        advanced = False
        if len(held) == 3 and len(set(held.values())) == 3:
            async with _get_db() as db:
                fc = await db.execute(
                    "UPDATE caravan_events SET stage=stage+1 WHERE id=? AND stage=? AND ended=0",
                    (carav_id, stage))
                await db.commit()
                if getattr(fc, "rowcount", 0) == 1:
                    advanced = True
                    for u in set(held.values()):
                        await db.execute(
                            "INSERT INTO caravan_contributors(carav_id,user_id,stages_helped) "
                            "VALUES(?,?,1) ON CONFLICT(carav_id,user_id) DO UPDATE SET "
                            "stages_helped=stages_helped+1", (carav_id, int(u)))
                    # Reset des sceaux → chaque étape exige un NOUVEAU trio (anti-AFK).
                    await db.execute(
                        "UPDATE caravan_roles SET holder_id=NULL, hold_until=0 WHERE carav_id=?",
                        (carav_id,))
                    await db.commit()
            if advanced:
                stage += 1
        emoji, label = _ROLE_META[role]
        if advanced and stage >= target:
            await _end_caravan(i.guild, carav_id, victory=True)
            return await i.followup.send(
                f"{emoji} Sceau **{label}** tenu — et la caravane atteint sa **destination** ! 🎉",
                ephemeral=True)
        await _refresh_panel(i.guild, carav_id, force=advanced)
        if advanced:
            await i.followup.send(
                f"{emoji} Sceau **{label}** — **étape {stage}/{target}** franchie ENSEMBLE ! 🎉",
                ephemeral=True)
        else:
            free = [_ROLE_META[r][1] for r in _ROLES if r not in held]
            need = (f" Il manque : **{', '.join(free)}**." if free
                    else " Les 3 sceaux sont tenus — gardez la position !")
            await i.followup.send(
                f"{emoji} Tu tiens le sceau **{label}** (90 s).{need}", ephemeral=True)
    except Exception as ex:
        print(f"[caravan role] {ex}")


# ─── Fin (atomique, claim-once, fail-closed) ───────────────────────────────────
async def _end_caravan(guild, carav_id: int, victory: bool):
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE caravan_events SET ended=1, victory=? WHERE id=? AND ended=0",
                (1 if victory else 0, carav_id))
            await db.commit()
            if not getattr(cur, "rowcount", 0):
                return
        if _add_coins is not None and guild is not None:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT user_id, stages_helped FROM caravan_contributors "
                        "WHERE carav_id=?", (carav_id,)) as c:
                        rows = await c.fetchall()
                target = _STAGES_TARGET
                try:
                    cv = await _get_carav(carav_id)
                    if cv:
                        target = int(cv.get("stages_target") or _STAGES_TARGET)
                except Exception:
                    pass
                for (uid, helped) in rows:
                    uid = int(uid)
                    try:
                        async with _get_db() as db:
                            cc = await db.execute(
                                "UPDATE caravan_contributors SET rewarded=1 "
                                "WHERE carav_id=? AND user_id=? AND rewarded=0",
                                (carav_id, uid))
                            await db.commit()
                            if not getattr(cc, "rowcount", 0):
                                continue
                    except Exception:
                        continue
                    helped = max(0, min(int(helped or 0), target))
                    amount = _BASE_REWARD + _PER_STAGE * helped
                    if not victory:
                        amount = max(40, amount // 2)  # consolation : moitié, plancher 40
                    try:
                        await _add_coins(guild.id, uid, amount)
                    except Exception:
                        pass
            except Exception:
                pass
        # Récap + refresh final + teardown du salon partagé (si idle).
        try:
            carav = await _get_carav(carav_id)
            roles = await _get_roles(carav_id)
            if carav:
                ch = guild.get_channel(int(carav.get("channel_id") or 0))
                if ch and carav.get("message_id"):
                    try:
                        await ch.get_partial_message(int(carav["message_id"])).edit(
                            view=_build_panel(carav, roles))
                    except Exception:
                        pass
                if _report_fn is not None:
                    try:
                        verb = "arrivée à destination 🎉" if victory else "arrêtée en chemin 🌅"
                        await _report_fn(
                            guild, "🐫 La Caravane des Trois Sceaux",
                            f"La caravane s'est **{verb}** — étape "
                            f"{int(carav.get('stage') or 0)}/{int(carav.get('stages_target') or _STAGES_TARGET)}.")
                    except Exception:
                        pass
        except Exception:
            pass
        if _arena_delete_fn is not None:
            try:
                _cid = int((await _get_carav(carav_id) or {}).get("channel_id") or 0)
                if _cid:
                    await _arena_delete_fn(guild, _cid)
            except Exception:
                pass
    except Exception as ex:
        print(f"[caravan end] {ex}")


# ─── DynamicItem persistant ────────────────────────────────────────────────────
class CaravanRoleButton(discord.ui.DynamicItem[Button],
                        template=r"carav_role:(?P<cid>\d+):(?P<role>porteur|gardien|eclaireur)"):
    def __init__(self, carav_id: int, role: str):
        self.carav_id = int(carav_id)
        self.role = role if role in _ROLE_META else "porteur"
        emoji, label = _ROLE_META[self.role]
        super().__init__(Button(label=f"{emoji} {label}",
                                style=discord.ButtonStyle.secondary,
                                custom_id=f"carav_role:{int(carav_id)}:{self.role}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]), match["role"])

    async def callback(self, i: discord.Interaction):
        await _handle_role(i, self.carav_id, self.role)


def register_persistent_views(bot_instance):
    try:
        bot_instance.add_dynamic_items(CaravanRoleButton)
    except Exception:
        pass


# ─── Boucles supervisées ───────────────────────────────────────────────────────
@tasks.loop(minutes=19)
async def caravan_spawn_task():
    if _bot is None:
        return
    try:
        for g in list(_bot.guilds):
            try:
                if random.random() < _SPAWN_CHANCE:
                    await spawn_caravan(g)
            except Exception:
                pass
    except Exception as ex:
        print(f"[caravan spawn_task] {ex}")


@tasks.loop(seconds=30)
async def caravan_watchdog():
    """Rafraîchit les panneaux (les sceaux expirent) + termine les caravanes expirées."""
    if _bot is None or _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, ends_at FROM caravan_events WHERE ended=0") as c:
                rows = await c.fetchall()
        for (cid, gid, ends_at) in rows:
            try:
                g = _bot.get_guild(int(gid))
                if g is None:
                    continue
                expired = False
                try:
                    if ends_at:
                        dt = datetime.fromisoformat(str(ends_at).replace(" ", "T").split(".")[0])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        expired = datetime.now(timezone.utc) >= dt
                except Exception:
                    expired = False
                if expired:
                    await _end_caravan(g, int(cid), victory=False)
                else:
                    await _refresh_panel(g, int(cid), force=True)
            except Exception:
                pass
    except Exception as ex:
        print(f"[caravan watchdog] {ex}")


async def boot_cleanup():
    if _get_db is None or _bot is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, ends_at FROM caravan_events WHERE ended=0") as c:
                rows = await c.fetchall()
        for (cid, gid, ends_at) in rows:
            try:
                g = _bot.get_guild(int(gid))
                if g is None:
                    continue
                expired = True
                try:
                    if ends_at:
                        dt = datetime.fromisoformat(str(ends_at).replace(" ", "T").split(".")[0])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        expired = datetime.now(timezone.utc) >= dt
                except Exception:
                    expired = True
                if expired:
                    await _end_caravan(g, int(cid), victory=False)
            except Exception:
                pass
    except Exception as ex:
        print(f"[caravan boot_cleanup] {ex}")


__all__ = [
    "setup", "init_db", "register_persistent_views", "boot_cleanup",
    "spawn_caravan", "caravan_spawn_task", "caravan_watchdog", "CaravanRoleButton",
]
