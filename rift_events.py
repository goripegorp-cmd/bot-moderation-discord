"""
rift_events.py — Phase 256 Lot 3 : « La Faille Convergente » (event COLLABORATIF).

Une faille dimensionnelle s'ouvre : pour la sceller, le serveur doit CANALISER de
l'énergie ENSEMBLE dans un salon dédié. Mécanique de collaboration RÉELLE :
  • barre d'énergie partagée qui DÉCROÎT en temps réel (urgence) ;
  • la faille ne peut PAS être scellée tant que **≥ 4 joueurs DISTINCTS** n'ont pas
    canalisé — impossible en solo, quel que soit le nombre de clics (garantie dure) ;
  • verrou d'ACTIVITÉ : canaliser demande le palier 🟡 (10 pts / 14 j, messages OU
    vocal) — fail-open, comme les boss.

100 % TEXTE, AUCUN vocal créé, AUCUN salon @everyone masqué. Garde-fous Discord
(cf. mémoire) : cooldown PAR JOUEUR avant tout réseau (anti-429) ; refresh THROTTLÉ
via get_partial_message (PATCH seul, zéro GET) ; boutons PERSISTANTS (DynamicItem) ;
écritures DB ATOMIQUES (UPDATE ... WHERE ... + rowcount) ; récompenses MODESTES,
claim-once, FAIL-CLOSED ; teardown du salon éphémère à la fin + boot cleanup.

API : setup(...), init_db(), register_persistent_views(bot), boot_cleanup(),
rift_spawn_task, rift_watchdog.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

import discord
from discord.ui import Button
from discord.ext import tasks

import activity_system as _act  # gate d'activité (leaf module, fail-open)

# ─── Dépendances injectées (toutes via setup ; fail-open si None) ─────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None
_inventory_fn = None
_active_ping_fn = None
_arena_create_fn = None
_arena_delete_fn = None
_report_fn = None
_event_busy_fn = None

# ─── Réglages (volontairement modestes — rétention) ───────────────────────────
_EVENT_TYPE = "rift"
_TARGET = 2500                 # énergie à atteindre pour sceller
_DECAY_PER_MIN = 60            # énergie perdue par minute (urgence ; secondaire)
_ENERGY_MIN, _ENERGY_MAX = 40, 70   # énergie par clic
_MIN_DISTINCT = 4              # GARANTIE COLLABORATIVE : 4 scelleurs distincts mini
_DURATION_MIN = 25            # durée de vie de la faille
_CLICK_CD = 8.0               # cooldown PAR JOUEUR (s), vérifié AVANT defer
_REFRESH_MIN = 4.0            # throttle du refresh de panneau (s)
_SPAWN_COOLDOWN_H = 3.0       # délai mini entre 2 failles d'un même serveur
_SPAWN_CHANCE = 0.22          # proba par tick éligible du dispatcher
_BASE_REWARD = 120            # pièces / scelleur (victoire)
_TOP_REWARD = 200             # bonus pour les 3 plus gros contributeurs
_CONSOLATION = 40             # pièces / scelleur si échec (faille non scellée)
_COLOR = 0x8E44AD

_last_click: dict = {}        # {(rift_id, user_id): epoch}
_last_refresh: dict = {}      # {rift_id: epoch}


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None,
          inventory_fn=None, active_ping_fn=None, arena_create_fn=None,
          arena_delete_fn=None, report_fn=None, event_busy_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _inventory_fn, _active_ping_fn
    global _arena_create_fn, _arena_delete_fn, _report_fn, _event_busy_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _inventory_fn = inventory_fn
    _active_ping_fn = active_ping_fn
    _arena_create_fn = arena_create_fn
    _arena_delete_fn = arena_delete_fn
    _report_fn = report_fn
    _event_busy_fn = event_busy_fn
    try:
        bot_instance.add_dynamic_items(RiftChannelButton, RiftTopButton)
    except Exception:
        pass


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rift_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER, message_id INTEGER,
                    energy INTEGER DEFAULT 0,
                    target INTEGER NOT NULL,
                    last_decay_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP,
                    ended INTEGER DEFAULT 0,
                    victory INTEGER DEFAULT 0
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rift_active "
                "ON rift_events(guild_id, ended)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rift_contributors (
                    rift_id INTEGER, user_id INTEGER,
                    energy_added INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0,
                    last_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rewarded INTEGER DEFAULT 0,
                    PRIMARY KEY (rift_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[rift init_db] {ex}")


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _bar(cur: int, mx: int, width: int = 14) -> str:
    cur = max(0, int(cur or 0))
    mx = max(1, int(mx or 1))
    filled = max(0, min(width, int(round(width * cur / mx))))
    return "🟪" * filled + "⬜" * (width - filled)


_RIFT_KEYS = ["id", "guild_id", "channel_id", "message_id", "energy", "target",
              "started_at", "ends_at", "ended", "victory"]


async def _get_rift(rift_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, channel_id, message_id, energy, target, "
                "started_at, ends_at, ended, victory FROM rift_events WHERE id=?",
                (rift_id,)) as c:
                row = await c.fetchone()
        return dict(zip(_RIFT_KEYS, row)) if row else None
    except Exception:
        return None


async def _distinct_count(rift_id: int) -> int:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM rift_contributors WHERE rift_id=?",
                (rift_id,)) as c:
                r = await c.fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def _build_panel(rift: dict, distinct: int):
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    energy = max(0, int(rift["energy"] or 0))
    target = max(1, int(rift["target"] or 1))
    ended = bool(rift["ended"])
    victory = bool(rift["victory"])
    pct = int(min(100, energy * 100 / target))

    # Compte à rebours CLIENT-SIDE (zéro edit serveur).
    ends_epoch = 0
    try:
        ed = rift.get("ends_at")
        if ed:
            dt = datetime.fromisoformat(str(ed).replace(" ", "T").split(".")[0])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ends_epoch = int(dt.timestamp())
    except Exception:
        ends_epoch = 0

    items = [
        v2_title("🌀  LA FAILLE CONVERGENTE"),
        v2_subtitle("_Une faille déchire le ciel d'Abylumis. Canalisez votre énergie "
                    "ENSEMBLE pour la sceller — seul, c'est impossible._"),
        v2_divider(),
    ]
    if ended:
        if victory:
            items.append(v2_body(
                f"✅ **Faille SCELLÉE !** Énergie `{energy:,}` / {target:,} · "
                f"{distinct} scelleurs. Récompenses distribuées aux participants. 🎉"))
        else:
            items.append(v2_body(
                f"💥 **La faille s'est refermée d'elle-même...** Énergie `{energy:,}` / "
                f"{target:,} · {distinct} scelleurs. Pas assez de monde cette fois — "
                f"petite consolation aux présents."))
    else:
        seal_ok = "✅" if distinct >= _MIN_DISTINCT else "🔒"
        items.append(v2_body(
            f"`{_bar(energy, target)}`\n"
            f"**Énergie : {energy:,} / {target:,}**  ({pct}%)\n"
            f"{seal_ok} **Scelleurs distincts : {distinct} / {_MIN_DISTINCT}** "
            f"_(il faut au moins {_MIN_DISTINCT} joueurs différents)_\n"
            f"⏳ L'énergie décroît (~{_DECAY_PER_MIN}/min) · "
            + (f"fin <t:{ends_epoch}:R>" if ends_epoch else "temps limité")))
        items.append(v2_divider())
        items.append(v2_body(
            "🌀 **Canaliser** = +énergie (boost si tu es en vocal). "
            "Appelle des amis : la faille ne cède qu'à plusieurs !"))

    rid = int(rift["id"])

    class _RiftPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=(0x2ECC71 if victory else _COLOR)))
            if not ended:
                _ch = Button(label="🌀 Canaliser", style=discord.ButtonStyle.primary,
                             custom_id=f"rift_channel:{rid}")
                _top = Button(label="🏆 Top scelleurs", style=discord.ButtonStyle.secondary,
                              custom_id=f"rift_top:{rid}")
                self.add_item(discord.ui.ActionRow(_ch, _top))

    return _RiftPanel()


async def _refresh_panel(guild, rift_id: int, force: bool = False):
    try:
        if not force:
            now = datetime.now(timezone.utc).timestamp()
            if now - _last_refresh.get(rift_id, 0.0) < _REFRESH_MIN:
                return
            _last_refresh[rift_id] = now
        rift = await _get_rift(rift_id)
        if not rift or not rift.get("channel_id") or not rift.get("message_id"):
            return
        ch = guild.get_channel(int(rift["channel_id"]))
        if not ch:
            return
        distinct = await _distinct_count(rift_id)
        await ch.get_partial_message(int(rift["message_id"])).edit(
            view=_build_panel(rift, distinct))
    except Exception:
        pass


# ─── Spawn ─────────────────────────────────────────────────────────────────────
async def _active_rift_id(guild_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM rift_events WHERE guild_id=? AND ended=0 LIMIT 1",
                (guild_id,)) as c:
                r = await c.fetchone()
        return int(r[0]) if r else None
    except Exception:
        return None


async def _too_soon(guild_id: int) -> bool:
    """True si une faille a démarré il y a moins de _SPAWN_COOLDOWN_H heures."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM rift_events WHERE guild_id=? "
                "AND julianday('now') - julianday(started_at) < ? LIMIT 1",
                (guild_id, _SPAWN_COOLDOWN_H / 24.0)) as c:
                return await c.fetchone() is not None
    except Exception:
        return False


async def spawn_rift(guild: discord.Guild) -> bool:
    """Ouvre une faille dans un salon dédié éphémère. True si OK."""
    if not guild or _get_db is None or _bot is None or _v2 is None:
        return False
    # Interrupteur Hub (optionnel, défaut activé) ; fail-open.
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('rift_enabled', True)):
            return False
    except Exception:
        pass
    if await _active_rift_id(guild.id) is not None:
        return False
    if await _too_soon(guild.id):
        return False
    # Verrou GLOBAL : pas de faille par-dessus un boss raid / world boss / climax.
    if _event_busy_fn is not None:
        try:
            if await _event_busy_fn(guild.id):
                return False
        except Exception:
            pass
    # Salon éphémère dédié (TEXTE seul : voice_count=0 → aucun vocal créé).
    ch = None
    if _arena_create_fn is not None:
        try:
            ch = await _arena_create_fn(guild, 'rift', "🌀 La Faille Convergente",
                                        voice_count=0)
        except Exception as ex:
            print(f"[rift spawn arena] {ex}")
    if ch is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO rift_events (guild_id, channel_id, energy, target, "
                "ends_at) VALUES (?,?,0,?, datetime('now', ?))",
                (guild.id, ch.id, _TARGET, f"+{_DURATION_MIN} minutes"))
            rift_id = cur.lastrowid
            await db.commit()
        rift = await _get_rift(rift_id)
        msg = await ch.send(view=_build_panel(rift, 0))
        async with _get_db() as db:
            await db.execute("UPDATE rift_events SET message_id=? WHERE id=?",
                             (msg.id, rift_id))
            await db.commit()
        # Ping discret des actifs (respecte opt-out / cooldown côté bot). Fail-open.
        if _active_ping_fn is not None:
            try:
                await _active_ping_fn(guild, ch, notif_key=_EVENT_TYPE,
                                      intro="🌀 Une **Faille Convergente** s'ouvre — "
                                            "canalisez ensemble pour la sceller !")
            except Exception:
                pass
        return True
    except Exception as ex:
        print(f"[rift spawn] {ex}")
        return False


# ─── Contribution (le bouton Canaliser) ────────────────────────────────────────
async def _handle_channel(i: discord.Interaction, rift_id: int):
    # 1) Cooldown PAR JOUEUR en TÊTE, avant tout réseau (anti-429).
    try:
        key = (rift_id, i.user.id)
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_click.get(key, 0.0) < _CLICK_CD:
            return
        _last_click[key] = now
    except Exception:
        pass
    try:
        await i.response.defer(ephemeral=True)
    except Exception:
        pass
    try:
        if i.guild is None:
            return
        rift = await _get_rift(rift_id)
        if not rift or rift["ended"]:
            return await i.followup.send("🔒 Cette faille est déjà refermée.", ephemeral=True)
        # 2) Verrou d'ACTIVITÉ (fail-open).
        try:
            ok, score, needed = await _act.check_gate(i.guild.id, i.user.id, _EVENT_TYPE)
            if not ok:
                return await i.followup.send(_act.block_message(_EVENT_TYPE, score, needed),
                                             ephemeral=True)
        except Exception:
            pass
        # 3) Énergie de base + boost vocal (si connecté à n'importe quel vocal).
        energy_add = random.randint(_ENERGY_MIN, _ENERGY_MAX)
        voice_note = ""
        try:
            if i.user.voice and i.user.voice.channel:
                mult = random.uniform(1.12, 1.30)
                energy_add = int(energy_add * mult)
                voice_note = f" 🔊 _(boost vocal +{int((mult - 1) * 100)}%)_"
        except Exception:
            pass
        energy_add = max(1, int(energy_add))
        # 4) Écriture ATOMIQUE : applique la décroissance depuis last_decay_at PUIS
        #    ajoute l'énergie, borne >=0, UNIQUEMENT si la faille est encore vivante.
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE rift_events SET "
                " energy = MAX(0, energy "
                "   - CAST((julianday('now') - julianday(last_decay_at)) * 1440 * ? AS INTEGER) "
                "   + ?), "
                " last_decay_at = CURRENT_TIMESTAMP "
                "WHERE id=? AND ended=0",
                (_DECAY_PER_MIN, energy_add, rift_id))
            if getattr(cur, "rowcount", 0) != 1:
                await db.commit()
                return await i.followup.send("🔒 Cette faille est déjà refermée.", ephemeral=True)
            await db.execute(
                "INSERT INTO rift_contributors(rift_id, user_id, energy_added, clicks, last_at) "
                "VALUES(?,?,?,1,CURRENT_TIMESTAMP) "
                "ON CONFLICT(rift_id, user_id) DO UPDATE SET "
                "energy_added = energy_added + ?, clicks = clicks + 1, last_at = CURRENT_TIMESTAMP",
                (rift_id, i.user.id, energy_add, energy_add))
            await db.commit()
        # 5) État courant → complétion ?
        rift2 = await _get_rift(rift_id)
        distinct = await _distinct_count(rift_id)
        cur_energy = int(rift2["energy"] or 0) if rift2 else 0
        if rift2 and not rift2["ended"] and cur_energy >= int(rift2["target"] or _TARGET) \
                and distinct >= _MIN_DISTINCT:
            await _end_rift(i.guild, rift_id, victory=True)
            await i.followup.send(
                f"🌀 **+{energy_add} énergie**{voice_note} — et la faille est **SCELLÉE** ! 🎉",
                ephemeral=True)
            return
        # 6) Sinon refresh throttlé + retour ephemeral (HP exact dans la réponse).
        await _refresh_panel(i.guild, rift_id)
        need_more = ""
        if distinct < _MIN_DISTINCT:
            need_more = (f" Il manque **{_MIN_DISTINCT - distinct}** scelleur(s) "
                         f"distinct(s) — appelle du monde !")
        await i.followup.send(
            f"🌀 **+{energy_add} énergie** canalisée !{voice_note} "
            f"({cur_energy:,}/{int(rift2['target']) if rift2 else _TARGET:,}).{need_more}",
            ephemeral=True)
    except Exception as ex:
        print(f"[rift channel] {ex}")


async def _handle_top(i: discord.Interaction, rift_id: int):
    try:
        await i.response.defer(ephemeral=True)
    except Exception:
        pass
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, energy_added FROM rift_contributors "
                "WHERE rift_id=? ORDER BY energy_added DESC LIMIT 10",
                (rift_id,)) as c:
                rows = await c.fetchall()
        if not rows:
            return await i.followup.send("Personne n'a encore canalisé.", ephemeral=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, (uid, e) in enumerate(rows):
            rank = medals[idx] if idx < 3 else f"`#{idx + 1}`"
            lines.append(f"{rank} <@{int(uid)}> — `{int(e or 0):,}` énergie")
        await i.followup.send("**🏆 Top scelleurs de la faille**\n" + "\n".join(lines),
                              ephemeral=True)
    except Exception as ex:
        print(f"[rift top] {ex}")
        try:
            await i.followup.send("Classement indisponible.", ephemeral=True)
        except Exception:
            pass


# ─── Fin de faille (atomique, claim-once, fail-closed) ─────────────────────────
async def _end_rift(guild, rift_id: int, victory: bool):
    try:
        # Claim ATOMIQUE : un seul appelant termine + récompense (pas de double).
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE rift_events SET ended=1, victory=? WHERE id=? AND ended=0",
                (1 if victory else 0, rift_id))
            await db.commit()
            if not getattr(cur, "rowcount", 0):
                return
        # Récompenses : seulement aux contributeurs réels, claim-once par joueur.
        if _add_coins is not None and guild is not None:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT user_id, energy_added FROM rift_contributors "
                        "WHERE rift_id=? ORDER BY energy_added DESC", (rift_id,)) as c:
                        rows = await c.fetchall()
                # Phase 256 (audit) : pas de consolation sur une faille ÉCHOUÉE sans
                # collaboration réelle (< 2 scelleurs distincts) — un clic solo sur une
                # faille ratée ne paie rien. La victoire (≥4 distincts) reste payée.
                if not victory and len(rows) < 2:
                    rows = []
                top3 = {int(u) for (u, _e) in rows[:3]}
                for (uid, _e) in rows:
                    uid = int(uid)
                    # claim-once
                    try:
                        async with _get_db() as db:
                            cc = await db.execute(
                                "UPDATE rift_contributors SET rewarded=1 "
                                "WHERE rift_id=? AND user_id=? AND rewarded=0",
                                (rift_id, uid))
                            await db.commit()
                            if not getattr(cc, "rowcount", 0):
                                continue
                    except Exception:
                        continue
                    if victory:
                        amount = _BASE_REWARD + (_TOP_REWARD if uid in top3 else 0)
                    else:
                        amount = _CONSOLATION
                    try:
                        await _add_coins(guild.id, uid, amount)
                    except Exception:
                        pass
            except Exception:
                pass
        # Récap consolidé (optionnel) puis suppression du salon éphémère.
        try:
            rift = await _get_rift(rift_id)
            distinct = await _distinct_count(rift_id)
            if rift:
                ch = guild.get_channel(int(rift.get("channel_id") or 0))
                if ch and rift.get("message_id"):
                    try:
                        await ch.get_partial_message(int(rift["message_id"])).edit(
                            view=_build_panel(rift, distinct))
                    except Exception:
                        pass
                if _report_fn is not None:
                    try:
                        verb = "scellée 🎉" if victory else "refermée d'elle-même 💥"
                        await _report_fn(
                            guild, "🌀 La Faille Convergente",
                            f"La faille a été **{verb}** — {distinct} scelleur(s), "
                            f"énergie finale `{int(rift.get('energy') or 0):,}`.")
                    except Exception:
                        pass
        except Exception:
            pass
        # Teardown : _delete_combat_arena ne supprime le salon ⚔️-combat PARTAGÉ que
        # s'il est devenu IDLE (aucun autre event) — sûr à appeler. Signature
        # EXACTE : (guild, text_channel_id, grace_seconds=120).
        if _arena_delete_fn is not None:
            try:
                _cid = int((await _get_rift(rift_id) or {}).get("channel_id") or 0)
                if _cid:
                    await _arena_delete_fn(guild, _cid)
            except Exception:
                pass
    except Exception as ex:
        print(f"[rift end] {ex}")


# ─── DynamicItems persistants (survivent au reboot) ────────────────────────────
class RiftChannelButton(discord.ui.DynamicItem[Button],
                        template=r"rift_channel:(?P<rid>\d+)"):
    def __init__(self, rift_id: int):
        self.rift_id = int(rift_id)
        super().__init__(Button(label="🌀 Canaliser", style=discord.ButtonStyle.primary,
                                custom_id=f"rift_channel:{int(rift_id)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["rid"]))

    async def callback(self, i: discord.Interaction):
        await _handle_channel(i, self.rift_id)


class RiftTopButton(discord.ui.DynamicItem[Button],
                    template=r"rift_top:(?P<rid>\d+)"):
    def __init__(self, rift_id: int):
        self.rift_id = int(rift_id)
        super().__init__(Button(label="🏆 Top scelleurs", style=discord.ButtonStyle.secondary,
                                custom_id=f"rift_top:{int(rift_id)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["rid"]))

    async def callback(self, i: discord.Interaction):
        await _handle_top(i, self.rift_id)


def register_persistent_views(bot_instance):
    try:
        bot_instance.add_dynamic_items(RiftChannelButton, RiftTopButton)
    except Exception:
        pass


# ─── Boucles supervisées (dispatcher + watchdog) ───────────────────────────────
@tasks.loop(minutes=17)
async def rift_spawn_task():
    if _bot is None:
        return
    try:
        for g in list(_bot.guilds):
            try:
                if random.random() < _SPAWN_CHANCE:
                    await spawn_rift(g)
            except Exception:
                pass
    except Exception as ex:
        print(f"[rift spawn_task] {ex}")


@tasks.loop(minutes=1)
async def rift_watchdog():
    """Applique la décroissance aux failles inactives + termine les expirées par id."""
    if _bot is None or _get_db is None:
        return
    try:
        async with _get_db() as db:
            # Décroissance lazy (même sans clic) — la faille finit par s'éteindre.
            await db.execute(
                "UPDATE rift_events SET "
                " energy = MAX(0, energy "
                "   - CAST((julianday('now') - julianday(last_decay_at)) * 1440 * ? AS INTEGER)), "
                " last_decay_at = CURRENT_TIMESTAMP "
                "WHERE ended=0", (_DECAY_PER_MIN,))
            await db.commit()
            async with db.execute(
                "SELECT id, guild_id FROM rift_events WHERE ended=0 "
                "AND ends_at IS NOT NULL AND datetime(ends_at) <= datetime('now')") as c:
                expired = await c.fetchall()
        for (rid, gid) in expired:
            try:
                g = _bot.get_guild(int(gid))
                if g is not None:
                    await _end_rift(g, int(rid), victory=False)
            except Exception:
                pass
    except Exception as ex:
        print(f"[rift watchdog] {ex}")


async def boot_cleanup():
    """Au boot : termine les failles orphelines déjà expirées + nettoie les salons."""
    if _get_db is None or _bot is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id FROM rift_events WHERE ended=0") as c:
                rows = await c.fetchall()
        for (rid, gid) in rows:
            try:
                rift = await _get_rift(int(rid))
                g = _bot.get_guild(int(gid))
                if not rift or g is None:
                    continue
                # Faille expirée → finalise (échec) ; sinon on la laisse vivre
                # (les boutons DynamicItem survivent au reboot).
                ed = rift.get("ends_at")
                expired = False
                try:
                    if ed:
                        dt = datetime.fromisoformat(str(ed).replace(" ", "T").split(".")[0])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        expired = datetime.now(timezone.utc) >= dt
                except Exception:
                    expired = True
                if expired:
                    await _end_rift(g, int(rid), victory=False)
            except Exception:
                pass
    except Exception as ex:
        print(f"[rift boot_cleanup] {ex}")


__all__ = [
    "setup", "init_db", "register_persistent_views", "boot_cleanup",
    "spawn_rift", "rift_spawn_task", "rift_watchdog",
    "RiftChannelButton", "RiftTopButton",
]
