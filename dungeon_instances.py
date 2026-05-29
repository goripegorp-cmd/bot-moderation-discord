"""
dungeon_instances.py — Donjons instanciés (Phase 184).

🎯 IDÉE OWNER : faire vivre les solos + petits groupes via des DONJONS
instanciés. Un lobby se forme (jusqu'à 4 joueurs), le bot crée une CATÉGORIE
dédiée avec un salon TEXTE + un salon VOCAL réservés au groupe, lance un
cooldown, puis des VAGUES de mobs à combattre ensemble. Récompenses à la clé,
puis NETTOYAGE STRICT des salons.

🛡️ SÉCURITÉ SALONS (limite ~500/guild Discord) :
- 1 seul run actif par guild à la fois.
- Tout est enregistré en DB (dungeon_runs) → un run orphelin (reboot pendant
  un donjon) est nettoyé au prochain boot (boot_cleanup).
- Timeout dur (RUN_TIMEOUT_SEC) → un run qui traîne est fermé + salons supprimés.
- Le groupe = overwrites @everyone view_channel=False (instancié, privé).

⚔️ COMBAT : réutilise l'équipement réel (inventory_fn → ATK + procs
élémentaires de events_engine) + bonus vocal +20%. Cohérent avec les boss/mobs.

API :
- setup(bot, get_db, db_get, v2, add_coins_fn=None, inventory_fn=None)
- init_db()
- start_dungeon_lobby(channel, host) -> bool
- dungeon_timeout_task (loop 5 min : ferme les runs périmés)
- boot_cleanup() -> nettoie les runs orphelins au démarrage
- register_persistent_views(bot)  (no-op : vues à timeout, runs nettoyés au boot)
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button, View

# ─── Globals injectés ────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None
_inventory_fn = None

# ─── Config ──────────────────────────────────────────────────────────────
MAX_PARTY = 4
LOBBY_WAIT_SEC = 120          # délai avant lancement auto du lobby
COOLDOWN_SEC = 20             # cooldown affiché avant la 1re vague
RUN_TIMEOUT_SEC = 1800        # garde-fou : un run > 30 min est fermé
WAVE_TIMEOUT_SEC = 300        # une vague non finie en 5 min → échec → cleanup
WAVES = 3                     # nb de vagues de mobs avant le boss final
ATTACK_CD_SEC = 4             # anti-spam clic par joueur
VOICE_BONUS = 0.20            # +20% dégâts si dans le vocal du donjon

# Mobs de donjon (HP scalé selon la taille du groupe au lancement)
DUNGEON_MOBS = [
    {"emoji": "🐀", "name": "Rat des cavernes", "hp": 220},
    {"emoji": "🦇", "name": "Nuée de chauves-souris", "hp": 320},
    {"emoji": "🕷️", "name": "Araignée géante", "hp": 420},
    {"emoji": "💀", "name": "Garde squelette", "hp": 480},
    {"emoji": "👹", "name": "Ogre des profondeurs", "hp": 600},
]
DUNGEON_BOSS = {"emoji": "🐲", "name": "Gardien du Donjon", "hp": 1400}

# Lobby en mémoire : guild_id -> dict(host_id, members:set, channel, message, view)
_lobbies: dict = {}
# Cooldown clic : (run_id, user_id) -> ts
_dgn_click_cd: dict = {}


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
          add_coins_fn=None, inventory_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _inventory_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _inventory_fn = inventory_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dungeon_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    category_id INTEGER DEFAULT 0,
                    text_channel_id INTEGER DEFAULT 0,
                    voice_channel_id INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    wave INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dungeon_members (
                    run_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage_dealt INTEGER DEFAULT 0,
                    PRIMARY KEY (run_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[dungeon init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _bot_can(ch) -> bool:
    try:
        p = ch.permissions_for(ch.guild.me)
        return bool(p.send_messages and p.view_channel)
    except Exception:
        return False


async def _active_run_exists(guild_id: int) -> bool:
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM dungeon_runs WHERE guild_id=? AND status='active' LIMIT 1",
                (guild_id,),
            ) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def _member_count(run_id: int) -> int:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM dungeon_members WHERE run_id=?", (run_id,)) as cur:
                return int((await cur.fetchone())[0])
    except Exception:
        return 1


async def _is_member(run_id: int, user_id: int) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM dungeon_members WHERE run_id=? AND user_id=?",
                (run_id, user_id)) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def _weapon_damage(guild_id: int, user_id: int, base: int) -> tuple:
    """Dégâts d'un coup : base + ATK équipement + proc élémentaire.
    Retourne (damage, elem_proc_or_None). Cohérent avec mob_hunts/daily_bosses."""
    dmg = base
    proc = None
    if _inventory_fn is not None:
        try:
            import events_engine as _ev
            inv = await _inventory_fn(guild_id, user_id)
            dmg += int(_ev.inventory_total_stats(inv).get("atk", 0) or 0)
            p = _ev.roll_elemental_proc(inv.get("weapon"))
            if p:
                dmg += int(p.get("bonus", 0) or 0)
                proc = p
        except Exception:
            pass
    return max(1, dmg), proc


# ═══════════════════════════════════════════════════════════════════════════
#  LOBBY (vue classique : content + boutons → pas de souci content+V2)
# ═══════════════════════════════════════════════════════════════════════════

class _LobbyView(View):
    """Lobby public : Rejoindre (≤4) + Lancer (groupe). Auto-lancement au timeout."""

    def __init__(self, guild_id: int, host_id: int):
        super().__init__(timeout=LOBBY_WAIT_SEC)
        self.guild_id = guild_id
        self.host_id = host_id
        b_join = Button(label="⚔️ Rejoindre le donjon", style=discord.ButtonStyle.success,
                        custom_id=f"dgn_join_{guild_id}")
        b_join.callback = self._on_join
        self.add_item(b_join)
        b_start = Button(label="🏰 Lancer maintenant", style=discord.ButtonStyle.primary,
                         custom_id=f"dgn_start_{guild_id}")
        b_start.callback = self._on_start
        self.add_item(b_start)

    async def _on_join(self, i: discord.Interaction):
        lob = _lobbies.get(self.guild_id)
        if not lob:
            return await i.response.send_message("⏰ Ce lobby est clos.", ephemeral=True)
        if i.user.id in lob["members"]:
            return await i.response.send_message("✅ Tu es déjà inscrit !", ephemeral=True)
        if len(lob["members"]) >= MAX_PARTY:
            return await i.response.send_message(
                f"🚪 Le groupe est complet ({MAX_PARTY}).", ephemeral=True)
        lob["members"].add(i.user.id)
        await i.response.send_message(
            f"⚔️ Tu rejoins le donjon ! (`{len(lob['members'])}/{MAX_PARTY}`)",
            ephemeral=True)
        try:
            await _refresh_lobby_message(self.guild_id)
        except Exception:
            pass
        if len(lob["members"]) >= MAX_PARTY:
            await _launch_dungeon(self.guild_id)

    async def _on_start(self, i: discord.Interaction):
        lob = _lobbies.get(self.guild_id)
        if not lob:
            return await i.response.send_message("⏰ Ce lobby est clos.", ephemeral=True)
        if i.user.id != lob["host_id"] and i.user.id not in lob["members"]:
            return await i.response.send_message(
                "❌ Rejoins d'abord le donjon pour le lancer.", ephemeral=True)
        try:
            await i.response.defer()
        except Exception:
            pass
        await _launch_dungeon(self.guild_id)

    async def on_timeout(self):
        # Auto-lancement si au moins 1 joueur, sinon annulation propre
        try:
            lob = _lobbies.get(self.guild_id)
            if lob and lob["members"]:
                await _launch_dungeon(self.guild_id)
            else:
                if lob and lob.get("message"):
                    try:
                        await lob["message"].edit(
                            content="⏰ Lobby de donjon expiré (personne n'a rejoint).",
                            view=None)
                    except Exception:
                        pass
                _lobbies.pop(self.guild_id, None)
        except Exception:
            pass


def _lobby_text(lob: dict) -> str:
    names = []
    g = _bot.get_guild(lob["guild_id"]) if _bot else None
    for uid in lob["members"]:
        m = g.get_member(uid) if g else None
        names.append(m.mention if m else f"<@{uid}>")
    roster = "\n".join(f"• {n}" for n in names) if names else "_(personne encore)_"
    return (
        f"🏰 **UN DONJON SE FORME !**\n"
        f"_Groupe de **{MAX_PARTY} max** — cliquez pour rejoindre. Lancement auto "
        f"dans ~{LOBBY_WAIT_SEC // 60} min, ou dès que le groupe le décide._\n\n"
        f"**Aventuriers ({len(lob['members'])}/{MAX_PARTY}) :**\n{roster}\n\n"
        f"_Une fois lancé : salon + vocal privés, {WAVES} vagues de mobs + un boss, "
        f"butin partagé. Équipe ton meilleur stuff (🎒) et rejoins le vocal "
        f"(+{int(VOICE_BONUS * 100)}% dégâts) !_"
    )


async def _refresh_lobby_message(guild_id: int):
    lob = _lobbies.get(guild_id)
    if not lob or not lob.get("message"):
        return
    try:
        await lob["message"].edit(content=_lobby_text(lob), view=lob.get("view"))
    except Exception:
        pass


async def start_dungeon_lobby(channel, host) -> bool:
    """Ouvre un lobby de donjon dans `channel`. Retourne True si posté."""
    if _bot is None or channel is None or not getattr(channel, "guild", None):
        return False
    gid = channel.guild.id
    if gid in _lobbies:
        return False  # déjà un lobby en cours
    if await _active_run_exists(gid):
        return False  # déjà un donjon actif
    if not _bot_can(channel):
        return False
    host_id = host.id if host else 0
    lob = {"guild_id": gid, "host_id": host_id, "members": set(),
           "channel": channel, "message": None, "view": None}
    if host_id:
        lob["members"].add(host_id)
    _lobbies[gid] = lob
    view = _LobbyView(gid, host_id)
    lob["view"] = view
    try:
        msg = await channel.send(content=_lobby_text(lob), view=view)
        lob["message"] = msg
        return True
    except Exception as ex:
        print(f"[dungeon start_lobby] {ex}")
        _lobbies.pop(gid, None)
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  LANCEMENT + INSTANCE
# ═══════════════════════════════════════════════════════════════════════════

async def _launch_dungeon(guild_id: int):
    lob = _lobbies.pop(guild_id, None)
    if not lob:
        return
    guild = _bot.get_guild(guild_id) if _bot else None
    if not guild:
        return
    members = [m for m in (guild.get_member(uid) for uid in lob["members"]) if m]
    if not members:
        return
    if await _active_run_exists(guild_id):  # sécurité : pas 2 runs en parallèle
        return
    me = guild.me
    if not (me and me.guild_permissions.manage_channels):
        try:
            if lob.get("message"):
                await lob["message"].edit(
                    content="❌ Donjon annulé : le bot n'a pas la permission "
                            "**Gérer les salons**.", view=None)
        except Exception:
            pass
        return

    # Overwrites : groupe seulement (instancié, privé)
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                        manage_channels=True, connect=True),
    }
    for m in members:
        ow[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                            connect=True, speak=True)

    try:
        cat = await guild.create_category(name="🏰 Donjon", overwrites=ow,
                                          reason="Donjon instancié")
        txt = await guild.create_text_channel(name="combat", category=cat, overwrites=ow,
                                              reason="Donjon instancié")
        vc = await guild.create_voice_channel(name="🔊 Donjon — vocal", category=cat,
                                              overwrites=ow, reason="Donjon instancié")
    except Exception as ex:
        print(f"[dungeon create channels] {ex}")
        return

    # Enregistre le run + ses membres
    run_id = 0
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO dungeon_runs(guild_id, category_id, text_channel_id, "
                "voice_channel_id, status, wave) VALUES(?,?,?,?,'active',0)",
                (guild_id, cat.id, txt.id, vc.id),
            )
            run_id = cur.lastrowid
            for m in members:
                await db.execute(
                    "INSERT OR IGNORE INTO dungeon_members(run_id, user_id) VALUES(?,?)",
                    (run_id, m.id))
            await db.commit()
    except Exception as ex:
        print(f"[dungeon insert run] {ex}")
        await _delete_run_channels(txt, vc, cat)
        return

    # Met à jour le message public du lobby
    try:
        if lob.get("message"):
            await lob["message"].edit(
                content=f"🏰 **Donjon lancé !** Rendez-vous dans {txt.mention} "
                        f"(et {vc.mention} pour le bonus vocal).", view=None)
    except Exception:
        pass

    party_mentions = " ".join(m.mention for m in members[:MAX_PARTY])
    try:
        await txt.send(
            f"🏰 **Bienvenue dans le donjon, aventuriers !** {party_mentions}\n"
            f"_Rejoignez {vc.mention} pour **+{int(VOICE_BONUS * 100)}% de dégâts**. "
            f"{WAVES} vagues + un boss vous attendent. Préparez-vous…_",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except Exception:
        pass

    # Déroulé en tâche de fond (cooldown + vagues), garde-fou via timeout task
    asyncio.create_task(_run_dungeon(run_id, guild_id, vc.id, txt.id, cat.id))


async def _run_dungeon(run_id, guild_id, vc_id, txt_id, cat_id):
    """Déroulé : cooldown → WAVES vagues → boss → récompenses → cleanup."""
    try:
        guild = _bot.get_guild(guild_id)
        txt = guild.get_channel(txt_id) if guild else None
        if not txt:
            return await _close_run(run_id)

        # Cooldown de départ (chrono Discord)
        try:
            impact = int(time.time()) + COOLDOWN_SEC
            await txt.send(f"⏳ Le donjon s'éveille… premiers mobs <t:{impact}:R>.")
        except Exception:
            pass
        await asyncio.sleep(COOLDOWN_SEC)

        party_size = await _member_count(run_id)
        hp_mult = 1.0 + 0.5 * max(0, party_size - 1)  # +50% HP par joueur au-delà du 1er

        # Vagues de mobs
        for wave in range(1, WAVES + 1):
            mob = random.choice(DUNGEON_MOBS)
            mob_hp = int(mob["hp"] * hp_mult)
            await _set_wave(run_id, wave)
            ok = await _fight_wave(
                run_id, guild_id, txt_id, vc_id,
                f"Vague {wave}/{WAVES} — {mob['emoji']} {mob['name']}", mob_hp, False)
            if not ok:
                return await _close_run(run_id)  # timeout/échec → cleanup

        # Boss final
        boss_hp = int(DUNGEON_BOSS["hp"] * hp_mult)
        await _set_wave(run_id, WAVES + 1)
        ok = await _fight_wave(
            run_id, guild_id, txt_id, vc_id,
            f"BOSS — {DUNGEON_BOSS['emoji']} {DUNGEON_BOSS['name']}", boss_hp, True)
        if not ok:
            return await _close_run(run_id)

        # Victoire → récompenses
        await _reward_party(run_id, guild_id, txt_id)
        try:
            guild = _bot.get_guild(guild_id)
            txt = guild.get_channel(txt_id) if guild else None
            if txt:
                await txt.send("🎉 **DONJON TERMINÉ !** Récompenses distribuées. "
                               "_Ce salon se ferme dans 30 s…_")
        except Exception:
            pass
        await asyncio.sleep(30)
        await _close_run(run_id)
    except Exception as ex:
        print(f"[_run_dungeon {run_id}] {ex}")
        await _close_run(run_id)


async def _set_wave(run_id: int, wave: int):
    try:
        async with _get_db() as db:
            await db.execute("UPDATE dungeon_runs SET wave=? WHERE id=?", (wave, run_id))
            await db.commit()
    except Exception:
        pass


async def _fight_wave(run_id, guild_id, txt_id, vc_id, label, mob_hp, is_boss=False) -> bool:
    """Combat d'une vague (HP partagé, panneau V2 auto-actualisé).
    Retourne True si vaincu, False si timeout."""
    guild = _bot.get_guild(guild_id)
    txt = guild.get_channel(txt_id) if guild else None
    if not txt:
        return False

    state = {"hp": mob_hp, "max": mob_hp, "done": False}
    view = _build_wave_view(run_id, guild_id, vc_id, state, label, is_boss)
    try:
        view._msg = await txt.send(view=view)  # LayoutView : view-only (PAS de content)
    except Exception as ex:
        print(f"[fight_wave send] {ex}")
        return False

    # Attendre la mort du mob OU le timeout de la vague
    waited = 0
    while not state["done"] and waited < WAVE_TIMEOUT_SEC:
        await asyncio.sleep(2)
        waited += 2
    try:
        if view._msg:
            await view._msg.delete()
    except Exception:
        pass
    return bool(state["done"])


def _build_wave_view(run_id, guild_id, vc_id, state, label, is_boss):
    """Construit une LayoutView V2 unique (HP bar + bouton Attaquer) qui se
    réactualise elle-même à chaque coup. Définie en closure car LayoutView est
    fourni via setup() (pas importable au chargement du module)."""
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_container = _v2['v2_container']
    color = 0xC0392B if is_boss else 0xE67E22

    class _WaveView(LayoutView):
        def __init__(self):
            super().__init__(timeout=WAVE_TIMEOUT_SEC + 20)
            self._msg = None
            self._render()

        def _render(self):
            self.clear_items()
            hp, mx = max(0, state["hp"]), state["max"]
            barlen = 18
            filled = int((hp / mx) * barlen) if mx else 0
            bar = "█" * filled + "░" * (barlen - filled)
            items = [
                v2_title(("👑 " if is_boss else "⚔️ ") + label),
                v2_body(f"**❤️ HP :** `{bar}`\n`{hp:,} / {mx:,}`\n\n"
                        f"_Frappez ensemble ! +{int(VOICE_BONUS * 100)}% si vous êtes "
                        f"dans le vocal du donjon._"),
            ]
            if not state["done"]:
                b = Button(label="⚔️ Attaquer", style=discord.ButtonStyle.danger,
                           custom_id=f"dgn_atk_{run_id}")
                b.callback = self._on_attack
                items.append(discord.ui.ActionRow(b))
            else:
                items.append(v2_body("💀 **Vaincu !**"))
            self.add_item(v2_container(*items, color=color))

        async def _on_attack(self, i: discord.Interaction):
            try:
                await i.response.defer()  # ack (DeferredMessageUpdate, pas de "thinking")
            except Exception:
                pass
            if state["done"]:
                return await i.followup.send("💀 Déjà vaincu !", ephemeral=True)
            if not await _is_member(run_id, i.user.id):
                return await i.followup.send("❌ Ce donjon n'est pas le tien.", ephemeral=True)
            key = (run_id, i.user.id)
            now = time.time()
            if now - _dgn_click_cd.get(key, 0) < ATTACK_CD_SEC:
                return await i.followup.send("⏱️ Doucement ! Attends une seconde.",
                                             ephemeral=True)
            _dgn_click_cd[key] = now

            base = random.randint(40, 90) if is_boss else random.randint(25, 55)
            dmg, proc = await _weapon_damage(guild_id, i.user.id, base)
            in_vc = False
            try:
                vs = i.user.voice
                in_vc = bool(vs and vs.channel and vs.channel.id == vc_id)
            except Exception:
                in_vc = False
            if in_vc:
                dmg = int(dmg * (1.0 + VOICE_BONUS))
            state["hp"] = max(0, state["hp"] - dmg)
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE dungeon_members SET damage_dealt = damage_dealt + ? "
                        "WHERE run_id=? AND user_id=?", (dmg, run_id, i.user.id))
                    await db.commit()
            except Exception:
                pass
            if state["hp"] <= 0:
                state["done"] = True
            # Réactualise le panneau (même message)
            self._render()
            try:
                if self._msg:
                    await self._msg.edit(view=self)
            except Exception:
                pass
            proc_str = (f" {proc['emoji']} {proc['name']} +{proc['bonus']}" if proc else "")
            vc_str = f" 🔊+{int(VOICE_BONUS * 100)}%" if in_vc else ""
            tail = " — **coup final !**" if state["done"] else ""
            try:
                await i.followup.send(
                    f"⚔️ Tu infliges `{dmg}` dégâts !{proc_str}{vc_str}{tail}",
                    ephemeral=True)
            except Exception:
                pass

    return _WaveView()


# ═══════════════════════════════════════════════════════════════════════════
#  Récompenses
# ═══════════════════════════════════════════════════════════════════════════

async def _reward_party(run_id, guild_id, txt_id):
    """Récompense chaque membre selon ses dégâts (coins). Annonce le top."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, damage_dealt FROM dungeon_members WHERE run_id=? "
                "ORDER BY damage_dealt DESC", (run_id,)) as cur:
                rows = await cur.fetchall()
    except Exception:
        rows = []
    guild = _bot.get_guild(guild_id) if _bot else None
    txt = guild.get_channel(txt_id) if guild else None
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for idx, (uid, dmg) in enumerate(rows):
        reward = 400 + int(dmg)  # base + proportionnel aux dégâts
        if _add_coins is not None:
            try:
                await _add_coins(guild_id, int(uid), reward)
            except Exception:
                pass
        m = guild.get_member(int(uid)) if guild else None
        nm = m.mention if m else f"<@{uid}>"
        rank = medals[idx] if idx < 3 else f"`#{idx + 1}`"
        lines.append(f"{rank} {nm} · `{int(dmg):,}` dégâts · **+{reward}** 🪙")
    if txt and lines:
        try:
            await txt.send("🏆 **Butin du donjon :**\n" + "\n".join(lines[:10]),
                           allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
#  CLEANUP (strict)
# ═══════════════════════════════════════════════════════════════════════════

async def _delete_run_channels(*channels):
    for ch in channels:
        try:
            if ch:
                await ch.delete(reason="Donjon terminé — cleanup")
        except Exception:
            pass


async def _close_run(run_id: int):
    """Ferme un run : supprime salons + catégorie, marque 'done'. Idempotent."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, category_id, text_channel_id, voice_channel_id, status "
                "FROM dungeon_runs WHERE id=?", (run_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                return
            guild_id, cat_id, txt_id, vc_id, status = row
            if status != "active":
                return
            await db.execute("UPDATE dungeon_runs SET status='done' WHERE id=?", (run_id,))
            await db.commit()
    except Exception as ex:
        print(f"[dungeon _close_run] {ex}")
        return
    guild = _bot.get_guild(int(guild_id)) if _bot else None
    if not guild:
        return
    txt = guild.get_channel(int(txt_id)) if txt_id else None
    vc = guild.get_channel(int(vc_id)) if vc_id else None
    cat = guild.get_channel(int(cat_id)) if cat_id else None
    await _delete_run_channels(txt, vc, cat)


async def boot_cleanup():
    """Au démarrage : ferme tous les runs 'active' orphelins (salons supprimés).
    Protège contre l'accumulation de salons si le bot reboot pendant un donjon."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM dungeon_runs WHERE status='active'") as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
        for rid in ids:
            await _close_run(rid)
        if ids:
            print(f"[dungeon boot_cleanup] {len(ids)} run(s) orphelin(s) nettoyé(s)")
    except Exception as ex:
        print(f"[dungeon boot_cleanup] {ex}")


@tasks.loop(minutes=5)
async def dungeon_timeout_task():
    """Garde-fou : ferme tout run actif depuis > RUN_TIMEOUT_SEC."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM dungeon_runs WHERE status='active' AND "
                "datetime(started_at) < datetime('now', ?)",
                (f'-{RUN_TIMEOUT_SEC} seconds',)) as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
        for rid in ids:
            await _close_run(rid)
    except Exception as ex:
        print(f"[dungeon_timeout_task] {ex}")


@dungeon_timeout_task.before_loop
async def _dgn_wait():
    if _bot is not None:
        await _bot.wait_until_ready()


def register_persistent_views(bot_instance):
    """No-op : les vues de donjon ont un timeout et les runs sont nettoyés au
    boot (boot_cleanup), donc pas de persistance inter-reboot nécessaire."""
    return


__all__ = [
    "setup", "init_db", "start_dungeon_lobby", "boot_cleanup",
    "dungeon_timeout_task", "register_persistent_views",
    "MAX_PARTY", "WAVES", "DUNGEON_MOBS", "DUNGEON_BOSS",
]
