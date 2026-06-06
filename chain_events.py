"""
chain_events.py — Phase 256 Lot 3 : « La Chaîne d'Invocation » (event collaboratif).

Un rituel de chaîne : chaque maillon ne peut être posé que par un joueur DIFFÉRENT
des 2 derniers (relais de personnes distinctes). Atteignez la cible de maillons avant
que le délai ne s'écoule — chaque maillon repousse le délai. Si la chaîne se brise
(plus de maillon à temps), elle s'éteint (petite consolation).

La règle d'alternance vit ENTIÈREMENT dans le WHERE d'un seul UPDATE atomique
(`last_linker_id <> moi AND prev_linker_id <> moi`) → race-proof : un joueur ne peut
JAMAIS poser 2 maillons d'affilée. Verrou d'activité 🟡 (10 pts / 14 j). 100 % texte,
aucun vocal, aucun salon masqué ; salon ⚔️-combat partagé déclaré dans le verrou
d'events ; boutons persistants ; récompenses claim-once fail-closed ; boot cleanup.
"""
from __future__ import annotations

import random
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
_EVENT_TYPE = "chain"
_TARGET = 12
_LINK_TIMEOUT = 150           # secondes ; chaque maillon repousse le délai
_CLICK_CD = 4.0
_REFRESH_MIN = 4.0
_SPAWN_COOLDOWN_H = 2.5
_SPAWN_CHANCE = 0.22
_BASE_REWARD = 50
_PER_LINK = 20
_PER_LINK_CAP = 10
_COLOR = 0x16A085


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
        bot_instance.add_dynamic_items(ChainLinkButton)
    except Exception:
        pass


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chain_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER, message_id INTEGER,
                    links INTEGER DEFAULT 0, target INTEGER NOT NULL,
                    last_linker_id INTEGER, prev_linker_id INTEGER,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP,
                    ended INTEGER DEFAULT 0, victory INTEGER DEFAULT 0
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chain_active "
                "ON chain_events(guild_id, ended)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chain_contributors (
                    chain_id INTEGER, user_id INTEGER,
                    links_added INTEGER DEFAULT 0, rewarded INTEGER DEFAULT 0,
                    PRIMARY KEY (chain_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[chain init_db] {ex}")


def _bar(cur: int, mx: int, width: int = 14) -> str:
    cur = max(0, int(cur or 0))
    mx = max(1, int(mx or 1))
    filled = max(0, min(width, int(round(width * cur / mx))))
    return "🟩" * filled + "⬜" * (width - filled)


_CHAIN_KEYS = ["id", "guild_id", "channel_id", "message_id", "links", "target",
               "last_linker_id", "prev_linker_id", "started_at", "ends_at",
               "ended", "victory"]


async def _get_chain(chain_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, channel_id, message_id, links, target, "
                "last_linker_id, prev_linker_id, started_at, ends_at, ended, victory "
                "FROM chain_events WHERE id=?", (chain_id,)) as c:
                row = await c.fetchone()
        return dict(zip(_CHAIN_KEYS, row)) if row else None
    except Exception:
        return None


def _epoch_of(ends_at) -> int:
    try:
        if ends_at:
            dt = datetime.fromisoformat(str(ends_at).replace(" ", "T").split(".")[0])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
    except Exception:
        pass
    return 0


def _build_panel(chain: dict):
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    links = int(chain["links"] or 0)
    target = int(chain["target"] or _TARGET)
    ended = bool(chain["ended"])
    victory = bool(chain["victory"])
    last = chain.get("last_linker_id")
    ends_epoch = _epoch_of(chain.get("ends_at"))

    items = [
        v2_title("🔗  LA CHAÎNE D'INVOCATION"),
        v2_subtitle("👥 Relais : chaque maillon = un joueur **≠ des 2 derniers** "
                    "· 12 maillons = gagné · ne casse pas la chaîne !"),
        v2_divider(),
    ]
    if ended:
        if victory:
            items.append(v2_body(f"✅ **La Chaîne d'Invocation est COMPLÈTE !** "
                                 f"{target}/{target} maillons. Récompenses aux relayeurs. 🎉"))
        else:
            items.append(v2_body(f"⛓️ **La chaîne s'est brisée...** {links}/{target} maillons. "
                                 f"Il a manqué un relais — petite récompense aux participants."))
    else:
        last_txt = f"<@{int(last)}>" if last else "_(personne encore)_"
        items.append(v2_body(
            f"`{_bar(links, target)}`  **{links} / {target} maillons**\n"
            f"🔗 Dernier maillon : {last_txt}\n"
            + (f"⏳ Prochain maillon avant <t:{ends_epoch}:R> ou la chaîne casse !"
               if ends_epoch else "⏳ Posez vite le prochain maillon !")))
        items.append(v2_divider())
        items.append(v2_body("🔗 **Ajouter un maillon** — mais pas si tu as posé l'un "
                             "des 2 derniers ! Appelle d'autres joueurs pour le relais."))

    cid = int(chain["id"])

    class _ChainPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=(0x2ECC71 if victory else _COLOR)))
            if not ended:
                self.add_item(discord.ui.ActionRow(
                    Button(label="🔗 Ajouter un maillon", style=discord.ButtonStyle.success,
                           custom_id=f"chain_link:{cid}"),
                    # Phase 258.8 : toggle 🔔 (catégorie collab) — capté par EventNotifyButton.
                    Button(label="🔔", style=discord.ButtonStyle.secondary,
                           custom_id="evtnotif:collab")))

    return _ChainPanel()


async def _refresh_panel(guild, chain_id: int, force: bool = False):
    try:
        if not force:
            now = datetime.now(timezone.utc).timestamp()
            if now - _last_refresh.get(chain_id, 0.0) < _REFRESH_MIN:
                return
            _last_refresh[chain_id] = now
        chain = await _get_chain(chain_id)
        if not chain or not chain.get("channel_id") or not chain.get("message_id"):
            return
        ch = guild.get_channel(int(chain["channel_id"]))
        if not ch:
            return
        await ch.get_partial_message(int(chain["message_id"])).edit(
            view=_build_panel(chain))
    except Exception:
        pass


_last_click: dict = {}
_last_refresh: dict = {}


# ─── Spawn ─────────────────────────────────────────────────────────────────────
async def _active_chain_id(guild_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM chain_events WHERE guild_id=? AND ended=0 LIMIT 1",
                (guild_id,)) as c:
                r = await c.fetchone()
        return int(r[0]) if r else None
    except Exception:
        return None


async def _too_soon(guild_id: int) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM chain_events WHERE guild_id=? "
                "AND julianday('now') - julianday(started_at) < ? LIMIT 1",
                (guild_id, _SPAWN_COOLDOWN_H / 24.0)) as c:
                return await c.fetchone() is not None
    except Exception:
        return False


async def spawn_chain(guild: discord.Guild) -> bool:
    if not guild or _get_db is None or _bot is None or _v2 is None:
        return False
    try:
        if _db_get is not None and not bool((await _db_get(guild.id)).get('chain_enabled', True)):
            return False
    except Exception:
        pass
    if await _active_chain_id(guild.id) is not None:
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
            ch = await _arena_create_fn(guild, 'chain',
                                        "🔗 La Chaîne d'Invocation", voice_count=0)
        except Exception as ex:
            print(f"[chain spawn arena] {ex}")
    if ch is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO chain_events (guild_id, channel_id, links, target, ends_at) "
                "VALUES (?,?,0,?, datetime('now', ?))",
                (guild.id, ch.id, _TARGET, f"+{_LINK_TIMEOUT} seconds"))
            chain_id = cur.lastrowid
            await db.commit()
        chain = await _get_chain(chain_id)
        msg = await ch.send(view=_build_panel(chain))
        async with _get_db() as db:
            await db.execute("UPDATE chain_events SET message_id=? WHERE id=?",
                             (msg.id, chain_id))
            await db.commit()
        if _active_ping_fn is not None:
            try:
                await _active_ping_fn(guild, ch, notif_key=_EVENT_TYPE,
                                      intro="🔗 Une **Chaîne d'Invocation** commence — "
                                            "posez les maillons en relais avant qu'elle ne casse !")
            except Exception:
                pass
        return True
    except Exception as ex:
        print(f"[chain spawn] {ex}")
        return False


# ─── Ajout d'un maillon (le bouton) ────────────────────────────────────────────
async def _handle_link(i: discord.Interaction, chain_id: int):
    # Phase 257.3 : ACK D'ABORD (defer) — acquitter le clic AVANT le cooldown, sinon
    # un clic noyé affiche « Échec de l'interaction ». Defer = requête légère ;
    # l'anti-429 reste assuré (un clic noyé ne fait aucun followup).
    try:
        await i.response.defer(ephemeral=True)
    except Exception:
        pass
    # Cooldown PAR JOUEUR APRÈS l'ack → clic noyé = AUCUNE erreur + AUCUN followup.
    try:
        key = (chain_id, i.user.id)
        nowf = datetime.now(timezone.utc).timestamp()
        if nowf - _last_click.get(key, 0.0) < _CLICK_CD:
            return
        _last_click[key] = nowf
    except Exception:
        pass
    try:
        if i.guild is None:
            return
        chain = await _get_chain(chain_id)
        if not chain or chain["ended"]:
            return await i.followup.send("🔒 Cette chaîne est déjà terminée.", ephemeral=True)
        try:
            ok, score, needed = await _act.check_gate(i.guild.id, i.user.id, _EVENT_TYPE)
            if not ok:
                return await i.followup.send(_act.block_message(_EVENT_TYPE, score, needed),
                                             ephemeral=True)
        except Exception:
            pass
        uid = i.user.id
        # MAILLON ATOMIQUE : ajoute UNIQUEMENT si chaîne vivante (deadline non passée)
        # ET si je ne suis PAS l'un des 2 derniers maillons. Toute la règle est ici.
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE chain_events SET links=links+1, prev_linker_id=last_linker_id, "
                "last_linker_id=?, ends_at=datetime('now', ?) "
                "WHERE id=? AND ended=0 AND datetime(ends_at) > datetime('now') "
                "AND COALESCE(last_linker_id,0)<>? AND COALESCE(prev_linker_id,0)<>?",
                (uid, f"+{_LINK_TIMEOUT} seconds", chain_id, uid, uid))
            await db.commit()
            ok_link = (getattr(cur, "rowcount", 0) == 1)
            if ok_link:
                await db.execute(
                    "INSERT INTO chain_contributors(chain_id, user_id, links_added) "
                    "VALUES(?,?,1) ON CONFLICT(chain_id, user_id) DO UPDATE SET "
                    "links_added=links_added+1", (chain_id, uid))
                await db.commit()
        if not ok_link:
            # Pourquoi ? (re-lecture pour un message clair)
            ch2 = await _get_chain(chain_id)
            if not ch2 or ch2["ended"]:
                return await i.followup.send("🔒 La chaîne vient de se terminer.", ephemeral=True)
            if _epoch_of(ch2.get("ends_at")) <= int(nowf):
                return await i.followup.send(
                    "⛓️ La chaîne s'est **brisée** (trop long) — attends la prochaine.",
                    ephemeral=True)
            return await i.followup.send(
                "🔗 **Pas toi !** Tu as posé l'un des 2 derniers maillons — laisse un "
                "AUTRE joueur poser le suivant. C'est un relais !", ephemeral=True)
        chain2 = await _get_chain(chain_id)
        links = int(chain2["links"] or 0) if chain2 else 0
        target = int(chain2["target"] or _TARGET) if chain2 else _TARGET
        if chain2 and not chain2["ended"] and links >= target:
            await _end_chain(i.guild, chain_id, victory=True)
            return await i.followup.send(
                f"🔗 Maillon posé — et la **Chaîne est COMPLÈTE** ! 🎉", ephemeral=True)
        await _refresh_panel(i.guild, chain_id)
        await i.followup.send(
            f"🔗 **Maillon {links}/{target}** posé ! Vite, un autre joueur pour le suivant.",
            ephemeral=True)
    except Exception as ex:
        print(f"[chain link] {ex}")


# ─── Fin (atomique, claim-once, fail-closed) ───────────────────────────────────
async def _end_chain(guild, chain_id: int, victory: bool):
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE chain_events SET ended=1, victory=? WHERE id=? AND ended=0",
                (1 if victory else 0, chain_id))
            await db.commit()
            if not getattr(cur, "rowcount", 0):
                return
        if _add_coins is not None and guild is not None:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT user_id, links_added FROM chain_contributors WHERE chain_id=?",
                        (chain_id,)) as c:
                        rows = await c.fetchall()
                for (uid, added) in rows:
                    uid = int(uid)
                    try:
                        async with _get_db() as db:
                            cc = await db.execute(
                                "UPDATE chain_contributors SET rewarded=1 "
                                "WHERE chain_id=? AND user_id=? AND rewarded=0",
                                (chain_id, uid))
                            await db.commit()
                            if not getattr(cc, "rowcount", 0):
                                continue
                    except Exception:
                        continue
                    eff = max(0, min(int(added or 0), _PER_LINK_CAP))
                    amount = _BASE_REWARD + _PER_LINK * eff
                    if not victory:
                        amount = max(40, amount // 2)
                    try:
                        await _add_coins(guild.id, uid, amount)
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            chain = await _get_chain(chain_id)
            if chain:
                ch = guild.get_channel(int(chain.get("channel_id") or 0))
                if ch and chain.get("message_id"):
                    try:
                        await ch.get_partial_message(int(chain["message_id"])).edit(
                            view=_build_panel(chain))
                    except Exception:
                        pass
                if _report_fn is not None:
                    try:
                        verb = "complétée 🎉" if victory else "brisée ⛓️"
                        await _report_fn(
                            guild, "🔗 La Chaîne d'Invocation",
                            f"La chaîne a été **{verb}** — "
                            f"{int(chain.get('links') or 0)}/{int(chain.get('target') or _TARGET)} maillons.")
                    except Exception:
                        pass
        except Exception:
            pass
        if _arena_delete_fn is not None:
            try:
                _cid = int((await _get_chain(chain_id) or {}).get("channel_id") or 0)
                if _cid:
                    await _arena_delete_fn(guild, _cid)
            except Exception:
                pass
    except Exception as ex:
        print(f"[chain end] {ex}")


# ─── DynamicItem persistant ────────────────────────────────────────────────────
class ChainLinkButton(discord.ui.DynamicItem[Button],
                      template=r"chain_link:(?P<cid>\d+)"):
    def __init__(self, chain_id: int):
        self.chain_id = int(chain_id)
        super().__init__(Button(label="🔗 Ajouter un maillon",
                                style=discord.ButtonStyle.success,
                                custom_id=f"chain_link:{int(chain_id)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await _handle_link(i, self.chain_id)


def register_persistent_views(bot_instance):
    try:
        bot_instance.add_dynamic_items(ChainLinkButton)
    except Exception:
        pass


# ─── Boucles supervisées ───────────────────────────────────────────────────────
@tasks.loop(minutes=23)
async def chain_spawn_task():
    if _bot is None:
        return
    try:
        for g in list(_bot.guilds):
            try:
                if random.random() < _SPAWN_CHANCE:
                    await spawn_chain(g)
            except Exception:
                pass
    except Exception as ex:
        print(f"[chain spawn_task] {ex}")


@tasks.loop(seconds=20)
async def chain_watchdog():
    """Termine les chaînes BRISÉES (délai du prochain maillon dépassé)."""
    if _bot is None or _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id FROM chain_events WHERE ended=0 "
                "AND ends_at IS NOT NULL AND datetime(ends_at) <= datetime('now')") as c:
                broken = await c.fetchall()
        for (cid, gid) in broken:
            try:
                g = _bot.get_guild(int(gid))
                if g is not None:
                    await _end_chain(g, int(cid), victory=False)
            except Exception:
                pass
    except Exception as ex:
        print(f"[chain watchdog] {ex}")


async def boot_cleanup():
    if _get_db is None or _bot is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, ends_at FROM chain_events WHERE ended=0") as c:
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
                    await _end_chain(g, int(cid), victory=False)
            except Exception:
                pass
    except Exception as ex:
        print(f"[chain boot_cleanup] {ex}")


__all__ = [
    "setup", "init_db", "register_persistent_views", "boot_cleanup",
    "spawn_chain", "chain_spawn_task", "chain_watchdog", "ChainLinkButton",
]
