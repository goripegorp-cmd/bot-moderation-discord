"""
dungeon_instances.py — Donjons instanciés (Phase 184).

🎯 IDÉE OWNER : faire vivre les solos + petits groupes via des DONJONS
instanciés. Un lobby se forme (jusqu'à 4 joueurs), le bot crée une CATÉGORIE
dédiée avec un salon TEXTE + PLUSIEURS salles VOCALES réservées au groupe (1
salle par vague, NOMMÉE D'APRÈS son mob/boss), lance un cooldown, puis :
  Phase 189 — VAGUES SÉQUENTIELLES (vision owner) : le groupe enchaîne des
  vagues de mobs salle par salle (vague 1 → vague 2 → …), bonus de dégâts s'il
  est dans le vocal de la vague active. Tuer la vague en cours débloque la
  suivante ; la DERNIÈRE salle abrite le BOSS. (Étape 2 à venir : déplacement
  automatique des joueurs de vocal en vocal à chaque vague nettoyée.)
Récompenses à la clé, puis NETTOYAGE STRICT des salons.

(Legacy : _fight_dispersion/_build_dispersion_view — ancien mode « dispersion
parallèle » — ne sont plus appelés ; conservés le temps de la refonte par étapes.)

🛡️ SÉCURITÉ SALONS (limite ~500/guild Discord) :
- 1 seul run actif par guild à la fois.
- Tout est enregistré en DB (dungeon_runs) → un run orphelin (reboot pendant
  un donjon) est nettoyé au prochain boot (boot_cleanup).
- Timeout dur (RUN_TIMEOUT_SEC) → un run qui traîne est fermé + salons supprimés.
- Le groupe = overwrites @everyone view_channel=False (instancié, privé).

⚔️ COMBAT : réutilise l'équipement réel (inventory_fn → ATK + DEF + procs
élémentaires de events_engine) + bonus vocal +20%. Cohérent avec les boss/mobs.
Les mobs/boss RIPOSTENT : chaque joueur a des PV et peut tomber au combat
(réapparition après un court délai). La DEF d'équipement réduit les dégâts subis.

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
import ui_v2  # design-system V2 partagé (encadrés cohérents)

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
WAVE_TIMEOUT_SEC = 300        # phase boss non finie en 5 min → échec → cleanup
DISPERSION_TIMEOUT_SEC = 420  # phase d'exploration (salles) non finie en 7 min → échec
WAVES = 3                     # (legacy) conservé pour compat ; remplacé par les salles
ATTACK_CD_SEC = 4             # anti-spam clic par joueur
VOICE_BONUS = 0.20            # +20% dégâts si dans le vocal du donjon

# Phase 184.4 : DISPERSION — plusieurs salles vocales, chacune avec un mob ;
# le groupe se disperse, on n'attaque le mob d'une salle QUE si on est connecté
# à son vocal (détection vocale). Plafond strict (1 run/guild déjà garanti).
DUNGEON_ROOMS_MAX = 3         # nb max de salles vocales (≤ taille du groupe)
ROOM_NUMERALS = ["I", "II", "III", "IV"]

# Phase 184.1 : on peut MOURIR dans le donjon (riposte des mobs/boss)
DUNGEON_PLAYER_HP = 100       # PV par joueur, rechargés à chaque nouvelle vague
DGN_RETAL_CHANCE = 0.30       # proba que le mob riposte quand on le frappe
DGN_BOSS_RETAL_CHANCE = 0.42  # le boss riposte plus souvent/plus fort
DGN_RESPAWN_SEC = 30          # à terre : temps avant de pouvoir réattaquer

# Mobs de donjon (HP scalé selon la taille du groupe au lancement). Phase 257.6 :
# catalogue ÉLARGI (5 → 24) → chaque run pioche des mobs au hasard (random.sample),
# donc les donjons se renouvellent énormément (« beaucoup plus de donjons »).
DUNGEON_MOBS = [
    {"emoji": "🐀", "name": "Rat des cavernes", "hp": 200},
    {"emoji": "🦇", "name": "Nuée de chauves-souris", "hp": 300},
    {"emoji": "🕷️", "name": "Araignée géante", "hp": 420},
    {"emoji": "💀", "name": "Garde squelette", "hp": 480},
    {"emoji": "👹", "name": "Ogre des profondeurs", "hp": 600},
    {"emoji": "🪲", "name": "Scarabée carapace", "hp": 260},
    {"emoji": "🐍", "name": "Serpent des tunnels", "hp": 340},
    {"emoji": "🧟", "name": "Goule affamée", "hp": 460},
    {"emoji": "🦂", "name": "Scorpion venimeux", "hp": 380},
    {"emoji": "🐺", "name": "Loup des abysses", "hp": 410},
    {"emoji": "👻", "name": "Spectre errant", "hp": 350},
    {"emoji": "🏹", "name": "Archer squelette", "hp": 440},
    {"emoji": "🧌", "name": "Troll des grottes", "hp": 660},
    {"emoji": "🔥", "name": "Élémentaire de braise", "hp": 520},
    {"emoji": "❄️", "name": "Élémentaire de givre", "hp": 520},
    {"emoji": "🗿", "name": "Gargouille foudroyante", "hp": 560},
    {"emoji": "🪨", "name": "Golem de pierre", "hp": 700},
    {"emoji": "🍄", "name": "Myconide toxique", "hp": 300},
    {"emoji": "🦟", "name": "Essaim parasite", "hp": 280},
    {"emoji": "🐙", "name": "Tentacule des profondeurs", "hp": 580},
    {"emoji": "🥷", "name": "Assassin de l'ombre", "hp": 470},
    {"emoji": "🧊", "name": "Liche mineure", "hp": 540},
    {"emoji": "🧛", "name": "Vampire de crypte", "hp": 500},
    {"emoji": "🐗", "name": "Sanglier enragé", "hp": 360},
]
# Boss de donjon : pioché au hasard par run → vraie variété (Phase 257.6).
DUNGEON_BOSSES = [
    {"emoji": "🐲", "name": "Gardien du Donjon", "hp": 1400},
    {"emoji": "☠️", "name": "Seigneur des Ossements", "hp": 1600},
    {"emoji": "🔥", "name": "Drake de Lave", "hp": 1800},
    {"emoji": "❄️", "name": "Tyran de Glace", "hp": 1700},
    {"emoji": "👁️", "name": "Œil du Néant", "hp": 1500},
    {"emoji": "🕸️", "name": "Matriarche Arachnide", "hp": 1550},
    {"emoji": "🧟", "name": "Colosse Putride", "hp": 2000},
    {"emoji": "⚡", "name": "Avatar de l'Orage", "hp": 1750},
]
# Rétro-compat (export + défaut) : 1er boss du pool.
DUNGEON_BOSS = DUNGEON_BOSSES[0]

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
            # Anti « Échec de l'interaction » : un lobby est posté AVANT qu'un run
            # n'existe en DB. Si le bot reboote pendant la fenêtre du lobby, le
            # message resterait avec des boutons morts. On persiste donc le message
            # du lobby pour pouvoir le supprimer au boot (boot_cleanup).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS dungeon_lobbies (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


async def _save_lobby_row(guild_id: int, channel_id: int, message_id: int):
    """Persiste le message du lobby pour pouvoir le nettoyer au boot (le lobby
    existe AVANT tout run en DB → sinon boutons morts si reboot pendant le lobby)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO dungeon_lobbies(guild_id, channel_id, message_id) "
                "VALUES(?,?,?)", (guild_id, channel_id, message_id))
            await db.commit()
    except Exception:
        pass


async def _del_lobby_row(guild_id: int):
    """Oublie le lobby d'une guilde (consommé : lancé ou annulé)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("DELETE FROM dungeon_lobbies WHERE guild_id=?", (guild_id,))
            await db.commit()
    except Exception:
        pass


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


async def _combat_profile(guild_id: int, user_id: int) -> tuple:
    """Profil combat du joueur en 1 lecture d'inventaire : (atk, def, proc).
    Cohérent avec mob_hunts/daily_bosses/boss : ATK + DEF d'équipement + proc
    élémentaire (events_engine). proc = {emoji,name,bonus,...} ou None."""
    atk = 0
    deff = 0
    proc = None
    if _inventory_fn is not None:
        try:
            import events_engine as _ev
            inv = await _inventory_fn(guild_id, user_id)
            st = _ev.inventory_total_stats(inv)
            atk = int(st.get("atk", 0) or 0)
            deff = int(st.get("def", 0) or 0)
            proc = _ev.roll_elemental_proc(inv.get("weapon"))
        except Exception:
            pass
    return atk, deff, proc


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
                await _del_lobby_row(self.guild_id)  # boutons retirés → plus à purger
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
        f"🏰 **Un donjon se forme !**\n"
        f"-# Groupe de {MAX_PARTY} max · lancement auto dans ~{LOBBY_WAIT_SEC // 60} min, "
        f"ou dès que le groupe le décide.\n\n"
        f"**Aventuriers ({len(lob['members'])}/{MAX_PARTY}) :**\n{roster}\n\n"
        f"-# Vagues de mobs salle par salle (vocal = +20% dégâts), puis le boss. "
        f"Ils ripostent — équipe ton meilleur stuff (🎒)."
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
    # RÉSERVATION SYNCHRONE : on pose _lobbies[gid] AVANT tout await pour fermer
    # la course (2 clics quasi simultanés dans la même guilde créeraient sinon
    # 2 lobbies, le 1er orphelin avec des boutons morts). Pas d'await entre le
    # check ci-dessus et cette ligne → atomique en async coopératif.
    host_id = host.id if host else 0
    lob = {"guild_id": gid, "host_id": host_id, "members": set(),
           "channel": channel, "message": None, "view": None}
    if host_id:
        lob["members"].add(host_id)
    _lobbies[gid] = lob
    # Vérifs async APRÈS réservation ; on libère le créneau si elles échouent.
    if await _active_run_exists(gid) or not _bot_can(channel):
        _lobbies.pop(gid, None)
        return False
    view = _LobbyView(gid, host_id)
    lob["view"] = view
    try:
        msg = await channel.send(content=_lobby_text(lob), view=view)
        lob["message"] = msg
        await _save_lobby_row(gid, channel.id, msg.id)  # pour purge au boot
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
    await _del_lobby_row(guild_id)  # lobby consommé → plus de boutons à purger
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

    # Overwrites : groupe seulement (instancié, privé). On ne grant PAS
    # manage_channels au bot ici : sa permission serveur (déjà vérifiée) couvre
    # création ET suppression — l'ajouter en overwrite est inutile et peut
    # provoquer un 403 à la création si le bot n'a pas Gérer les rôles.
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                        connect=True),
    }
    for m in members:
        ow[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                            connect=True, speak=True)

    # Phase 189 — DONJON EN VAGUES SÉQUENTIELLES (vision owner). On prépare un
    # PLAN : plusieurs vagues de mobs DISTINCTS (HP croissant) PUIS le boss en
    # dernier. Chaque vague a SA salle vocale, NOMMÉE D'APRÈS son mob/boss. Le
    # groupe avancera salle par salle (étape 2 : déplacement auto). 1 run/guild →
    # au pire 3 mobs + boss + texte + catégorie = 6 salons (sous la limite).
    n_waves = max(2, min(DUNGEON_ROOMS_MAX, len(members) + 1))   # 2 à 3 vagues de mobs
    mob_plan = random.sample(DUNGEON_MOBS, k=min(n_waves, len(DUNGEON_MOBS)))
    mob_plan.sort(key=lambda m: m["hp"])                          # difficulté croissante
    encounters = [dict(m, is_boss=False) for m in mob_plan]
    encounters.append(dict(random.choice(DUNGEON_BOSSES), is_boss=True))  # boss aléatoire = dernière salle

    # Création ATOMIQUE : si une étape échoue, on supprime TOUT ce qui a déjà été
    # créé (sinon catégorie/salons orphelins SANS enregistrement DB → jamais
    # nettoyés par boot_cleanup/timeout → fuite de salons vs la limite ~500).
    cat = txt = None
    created = []          # tous les salons créés, pour cleanup en cas d'échec
    room_plan = []        # [(vc_id, vc_name, encounter), ...] DANS L'ORDRE des vagues
    try:
        cat = await guild.create_category(name="🏰 Donjon", overwrites=ow,
                                          position=0,  # catégorie propre TOUT EN HAUT
                                          reason="Donjon instancié")
        created.append(cat)
        # FIX salons : nom SPÉCIFIQUE « 🗡️-donjon » (au lieu du générique « combat »
        # qui donnait l'impression que tout est du combat). Salon privé instancié,
        # supprimé avec sa catégorie « 🏰 Donjon » à la fin du run (_delete_run_channels).
        txt = await guild.create_text_channel(name="🗡️-donjon", category=cat, overwrites=ow,
                                              reason="Donjon instancié")
        created.append(txt)
        for enc in encounters:
            rname = f"🔊 {enc['emoji']} {enc['name']}"[:95]   # nom = mob/boss de la vague
            rvc = await guild.create_voice_channel(name=rname, category=cat, overwrites=ow,
                                                   reason="Donjon instancié")
            created.append(rvc)
            room_plan.append((rvc.id, rname, enc))
    except Exception as ex:
        print(f"[dungeon create channels] {ex}")
        await _delete_run_channels(*reversed(created))  # cleanup partiel (enfants→parent)
        return

    # Enregistre le run + ses membres (voice_channel_id = 1re salle ; le cleanup
    # balaie toute la catégorie, donc inutile de tracer chaque salle en DB).
    run_id = 0
    first_vc = room_plan[0][0] if room_plan else 0
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO dungeon_runs(guild_id, category_id, text_channel_id, "
                "voice_channel_id, status, wave) VALUES(?,?,?,?,'active',0)",
                (guild_id, cat.id, txt.id, first_vc),
            )
            run_id = cur.lastrowid
            for m in members:
                await db.execute(
                    "INSERT OR IGNORE INTO dungeon_members(run_id, user_id) VALUES(?,?)",
                    (run_id, m.id))
            await db.commit()
    except Exception as ex:
        print(f"[dungeon insert run] {ex}")
        await _delete_run_channels(*reversed(created))
        return

    # Met à jour le message public du lobby
    try:
        if lob.get("message"):
            await lob["message"].edit(
                content=f"🏰 **Donjon lancé !** Rendez-vous dans {txt.mention} "
                        f"— affrontez les vagues salle par salle jusqu'au boss !", view=None)
    except Exception:
        pass

    party_mentions = " ".join(m.mention for m in members[:MAX_PARTY])
    salles = " → ".join(name for _, name, _ in room_plan)
    try:
        await txt.send(
            f"🏰 **Bienvenue dans le donjon, aventuriers !** {party_mentions}\n"
            f"_Vous allez enchaîner des **vagues de mobs successives**, salle par "
            f"salle :\n{salles}\n"
            f"Tuez la vague en cours pour avancer à la suivante ; la **dernière "
            f"salle abrite le boss**. Rejoignez le vocal de la vague active pour le "
            f"bonus de dégâts. Ils **ripostent** — équipez votre meilleur stuff (🎒) !_",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except Exception:
        pass

    # Déroulé en tâche de fond (cooldown + dispersion + boss), garde-fou timeout
    asyncio.create_task(_run_dungeon(run_id, guild_id, room_plan, txt.id, cat.id))


async def _run_dungeon(run_id, guild_id, room_plan, txt_id, cat_id):
    """Déroulé EN VAGUES SÉQUENTIELLES (Phase 189, vision owner) :
    cooldown → vague 1 (mobs) → vague 2 → … → BOSS (dernière salle) →
    récompenses → cleanup.
    room_plan : [(vc_id, vc_name, encounter), ...] DANS L'ORDRE ; le dernier =
    boss (encounter['is_boss']). On réutilise _fight_wave pour CHAQUE vague."""
    try:
        guild = _bot.get_guild(guild_id)
        txt = guild.get_channel(txt_id) if guild else None
        if not txt or not room_plan:
            return await _close_run(run_id)

        # Cooldown de départ (chrono Discord)
        try:
            impact = int(time.time()) + COOLDOWN_SEC
            await txt.send(f"⏳ Le donjon s'éveille… la première vague arrive <t:{impact}:R>.")
        except Exception:
            pass
        await asyncio.sleep(COOLDOWN_SEC)

        party_size = await _member_count(run_id)
        hp_mult = 1.0 + 0.5 * max(0, party_size - 1)  # +50% HP par joueur au-delà du 1er

        total = len(room_plan)
        for wave_idx, (vc_id, vc_name, enc) in enumerate(room_plan, start=1):
            is_boss = bool(enc.get("is_boss"))
            mob_hp = int(enc["hp"] * hp_mult)
            await _set_wave(run_id, wave_idx)
            vc_ids = {vc_id}  # bonus vocal = la salle de CETTE vague (étape 2 : move auto)
            try:
                if is_boss:
                    await txt.send(
                        f"🐲 **Dernière salle — {enc['emoji']} {enc['name']} surgit !** "
                        f"Rejoignez **{vc_name}** et frappez ensemble ! (🎒 équipez-vous)")
                else:
                    await txt.send(
                        f"⚔️ **Vague {wave_idx}/{total} — {enc['emoji']} {enc['name']} !** "
                        f"Rejoignez le vocal **{vc_name}** (+{int(VOICE_BONUS * 100)}%) "
                        f"et nettoyez-le pour avancer à la vague suivante.")
            except Exception:
                pass
            label = (f"BOSS — {enc['emoji']} {enc['name']}" if is_boss
                     else f"Vague {wave_idx}/{total} — {enc['emoji']} {enc['name']}")
            ok = await _fight_wave(run_id, guild_id, txt_id, vc_ids, label, mob_hp, is_boss)
            if not ok:
                return await _close_run(run_id)  # timeout/échec → cleanup

        # Toutes les vagues + boss vaincus → récompenses
        await _reward_party(run_id, guild_id, txt_id)
        try:
            guild = _bot.get_guild(guild_id)
            txt = guild.get_channel(txt_id) if guild else None
            if txt:
                await txt.send("🎉 **DONJON TERMINÉ !** Toutes les vagues et le boss "
                               "sont vaincus. Récompenses distribuées. "
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


async def _fight_wave(run_id, guild_id, txt_id, vc_ids, label, mob_hp, is_boss=False) -> bool:
    """Combat partagé (phase boss) : HP partagé, panneau V2 auto-actualisé.
    vc_ids : set d'IDs de vocaux donnant le bonus +20%. True si vaincu, False si timeout."""
    guild = _bot.get_guild(guild_id)
    txt = guild.get_channel(txt_id) if guild else None
    if not txt:
        return False

    state = {"hp": mob_hp, "max": mob_hp, "done": False}
    pstate: dict = {}  # user_id -> {"hp": int, "down_until": ts} (PV joueur, reset/vague)
    view = _build_wave_view(run_id, guild_id, vc_ids, state, pstate, label, is_boss)
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


def _build_wave_view(run_id, guild_id, vc_ids, state, pstate, label, is_boss):
    """Construit une LayoutView V2 unique (HP bar + bouton Attaquer) qui se
    réactualise elle-même à chaque coup. Définie en closure car LayoutView est
    fourni via setup() (pas importable au chargement du module).

    Phase 184.1 : le mob/boss RIPOSTE — chaque joueur a des PV (pstate) ; tomber
    à 0 met à terre pendant DGN_RESPAWN_SEC (impossible d'attaquer). PV rechargés
    à chaque nouvelle vague (pstate neuf par vague)."""
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_container = _v2['v2_container']
    color = 0xC0392B if is_boss else 0xE67E22
    retal_chance = DGN_BOSS_RETAL_CHANCE if is_boss else DGN_RETAL_CHANCE

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
                        f"dans le vocal du donjon. ⚠️ Le {'boss' if is_boss else 'mob'} "
                        f"riposte — vous pouvez tomber au combat._"),
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
            now = time.time()
            key = (run_id, i.user.id)
            # Anti-spam UNIVERSEL (Phase 251.11) : 1 action / ATTACK_CD_SEC, placé EN
            # TÊTE → protège TOUS les chemins. Clic trop rapide → SILENCE (déjà ACK via
            # defer()). Sous le feu, répondre à CHAQUE clic noyé = 1 requête webhook/clic
            # → 429 GLOBAL sur l'app (la tempête vue dans les logs). On ne répond plus
            # aux clics throttlés : le joueur reclique, c'est tout.
            if now - _dgn_click_cd.get(key, 0) < ATTACK_CD_SEC:
                return
            _dgn_click_cd[key] = now
            if state["done"]:
                return await i.followup.send("💀 Déjà vaincu !", ephemeral=True)
            if not await _is_member(run_id, i.user.id):
                return await i.followup.send("❌ Ce donjon n'est pas le tien.", ephemeral=True)
            ps = pstate.setdefault(i.user.id, {"hp": DUNGEON_PLAYER_HP, "down_until": 0.0})
            # À terre ? (mort temporaire — réapparition)
            if ps["down_until"] > now:
                return await i.followup.send(
                    f"💀 Tu es à terre ! Réapparition <t:{int(ps['down_until'])}:R>.",
                    ephemeral=True)

            atk_bonus, deff, proc = await _combat_profile(guild_id, i.user.id)
            base = random.randint(40, 90) if is_boss else random.randint(25, 55)
            dmg = base + atk_bonus + (int(proc.get("bonus", 0) or 0) if proc else 0)
            in_vc = False
            try:
                vs = i.user.voice
                in_vc = bool(vs and vs.channel and vs.channel.id in vc_ids)
            except Exception:
                in_vc = False
            if in_vc:
                dmg = int(dmg * (1.0 + VOICE_BONUS))
            dmg = max(1, dmg)
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

            # Riposte du mob/boss (DEF d'équipement réduit les dégâts subis)
            retal_note = ""
            if not state["done"] and random.random() < retal_chance:
                raw = random.randint(12, 26) if is_boss else random.randint(6, 16)
                taken = max(1, raw - deff // 2)
                ps["hp"] = max(0, ps["hp"] - taken)
                if ps["hp"] <= 0:
                    ps["down_until"] = now + DGN_RESPAWN_SEC
                    retal_note = (f"\n💀 **Tu tombes au combat !** (-{taken} PV) "
                                  f"Réapparition <t:{int(ps['down_until'])}:R>.")
                else:
                    retal_note = (f"\n🩸 Le {'boss' if is_boss else 'mob'} riposte : "
                                  f"-{taken} PV (il te reste **{ps['hp']}** PV).")

            # Réactualise le panneau — THROTTLE anti-429 (Phase 251.10) : 1 edit / 2 s
            # max, SAUF coup final (« Vaincu » montré tout de suite). Plusieurs joueurs
            # qui frappent en rafale ne floodent plus l'API (chacun voit ses dégâts
            # exacts dans sa réponse privée). self._msg est stocké → zéro fetch.
            if state["done"] or time.time() - getattr(self, "_last_edit", 0.0) >= 2.0:
                self._last_edit = time.time()
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
                    f"⚔️ Tu infliges `{dmg}` dégâts !{proc_str}{vc_str}{tail}{retal_note}",
                    ephemeral=True)
            except Exception:
                pass

    return _WaveView()


async def _fight_dispersion(run_id, guild_id, txt_id, room_vc, hp_mult) -> bool:
    """PHASE DISPERSION : chaque salle vocale abrite un mob. On ne peut frapper
    le mob d'une salle QUE si on est connecté à SON vocal (détection vocale).
    Toutes les salles doivent être nettoyées. True si OK, False si timeout."""
    guild = _bot.get_guild(guild_id)
    txt = guild.get_channel(txt_id) if guild else None
    if not txt or not room_vc:
        return False
    # Un mob distinct par salle (échantillon sans répétition tant que possible)
    pool = random.sample(DUNGEON_MOBS, k=min(len(room_vc), len(DUNGEON_MOBS)))
    rooms = []
    for idx, (vc_id, vc_name) in enumerate(room_vc):
        mob = pool[idx] if idx < len(pool) else random.choice(DUNGEON_MOBS)
        hp = int(mob["hp"] * hp_mult)
        rooms.append({"idx": idx, "vc_id": vc_id, "vc_name": vc_name,
                      "emoji": mob["emoji"], "mob": mob["name"],
                      "hp": hp, "max": hp, "done": False})
    pstate: dict = {}  # PV joueur partagés sur toute la phase d'exploration
    view = _build_dispersion_view(run_id, guild_id, rooms, pstate)
    try:
        view._msg = await txt.send(view=view)
    except Exception as ex:
        print(f"[fight_dispersion send] {ex}")
        return False
    waited = 0
    while not all(r["done"] for r in rooms) and waited < DISPERSION_TIMEOUT_SEC:
        await asyncio.sleep(2)
        waited += 2
    try:
        if view._msg:
            await view._msg.delete()
    except Exception:
        pass
    return all(r["done"] for r in rooms)


def _build_dispersion_view(run_id, guild_id, rooms, pstate):
    """LayoutView V2 d'exploration : 1 section + 1 bouton par salle. Le bouton
    d'une salle n'inflige des dégâts QUE si le joueur est dans SON vocal."""
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_container = _v2['v2_container']
    color = 0x8E44AD

    def _bar(hp, mx):
        barlen = 14
        filled = int((hp / mx) * barlen) if mx else 0
        return "█" * filled + "░" * (barlen - filled)

    def _numeral(idx):
        return ROOM_NUMERALS[idx] if idx < len(ROOM_NUMERALS) else str(idx + 1)

    class _DispView(LayoutView):
        def __init__(self):
            super().__init__(timeout=DISPERSION_TIMEOUT_SEC + 20)
            self._msg = None
            self._render()

        def _render(self):
            self.clear_items()
            cleared = sum(1 for r in rooms if r["done"])
            items = [
                v2_title("🏰 Donjon — Dispersez-vous dans les salles !"),
                v2_body(f"Rejoins le **vocal** d'une salle pour frapper son mob "
                        f"(+{int(VOICE_BONUS * 100)}% inclus). Salles nettoyées : "
                        f"**{cleared}/{len(rooms)}**. Ils ripostent — tu peux tomber !"),
            ]
            buttons = []
            for r in rooms:
                if r["done"]:
                    items.append(v2_body(
                        f"**{r['vc_name']}** — {r['emoji']} {r['mob']} · 💀 _nettoyée_"))
                else:
                    items.append(v2_body(
                        f"**{r['vc_name']}** — {r['emoji']} {r['mob']}\n"
                        f"`{_bar(max(0, r['hp']), r['max'])}` "
                        f"`{max(0, r['hp']):,}/{r['max']:,}`"))
                    b = Button(label=f"⚔️ Salle {_numeral(r['idx'])}",
                               style=discord.ButtonStyle.danger,
                               custom_id=f"dgn_room_{run_id}_{r['idx']}")
                    b.callback = self._on_attack
                    buttons.append(b)
            if buttons:
                items.append(discord.ui.ActionRow(*buttons))
            self.add_item(v2_container(*items, color=color))

        async def _on_attack(self, i: discord.Interaction):
            try:
                await i.response.defer()
            except Exception:
                pass
            cid = (i.data or {}).get("custom_id", "")
            try:
                idx = int(cid.rsplit("_", 1)[-1])
            except Exception:
                return
            room = next((r for r in rooms if r["idx"] == idx), None)
            if room is None:
                return
            now = time.time()
            key = (run_id, i.user.id, idx)  # cooldown par salle
            # Anti-spam UNIVERSEL (Phase 251.11) : 1 action / ATTACK_CD_SEC, EN TÊTE →
            # protège TOUS les chemins (done / pas membre / pas dans le vocal / à terre).
            # Clic trop rapide → SILENCE (déjà ACK via defer()). Avant, un joueur HORS
            # vocal qui spammait renvoyait 1 followup/clic → 429 GLOBAL sur l'app.
            if now - _dgn_click_cd.get(key, 0) < ATTACK_CD_SEC:
                return
            _dgn_click_cd[key] = now
            if room["done"]:
                return await i.followup.send("💀 Salle déjà nettoyée !", ephemeral=True)
            if not await _is_member(run_id, i.user.id):
                return await i.followup.send("❌ Ce donjon n'est pas le tien.", ephemeral=True)
            # DÉTECTION VOCALE : il faut être dans le vocal de CETTE salle
            try:
                vs = i.user.voice
                in_room = bool(vs and vs.channel and vs.channel.id == room["vc_id"])
            except Exception:
                in_room = False
            if not in_room:
                return await i.followup.send(
                    f"🔊 Rejoins le vocal **{room['vc_name']}** pour frapper son mob !",
                    ephemeral=True)
            ps = pstate.setdefault(i.user.id, {"hp": DUNGEON_PLAYER_HP, "down_until": 0.0})
            if ps["down_until"] > now:
                return await i.followup.send(
                    f"💀 Tu es à terre ! Réapparition <t:{int(ps['down_until'])}:R>.",
                    ephemeral=True)

            atk_bonus, deff, proc = await _combat_profile(guild_id, i.user.id)
            base = random.randint(25, 55)
            dmg = base + atk_bonus + (int(proc.get("bonus", 0) or 0) if proc else 0)
            dmg = max(1, int(dmg * (1.0 + VOICE_BONUS)))  # on EST dans le vocal → +20%
            room["hp"] = max(0, room["hp"] - dmg)
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE dungeon_members SET damage_dealt = damage_dealt + ? "
                        "WHERE run_id=? AND user_id=?", (dmg, run_id, i.user.id))
                    await db.commit()
            except Exception:
                pass
            if room["hp"] <= 0:
                room["done"] = True
            # Riposte du mob (DEF d'équipement réduit les dégâts subis)
            retal_note = ""
            if not room["done"] and random.random() < DGN_RETAL_CHANCE:
                raw = random.randint(6, 16)
                taken = max(1, raw - deff // 2)
                ps["hp"] = max(0, ps["hp"] - taken)
                if ps["hp"] <= 0:
                    ps["down_until"] = now + DGN_RESPAWN_SEC
                    retal_note = (f"\n💀 **Tu tombes !** (-{taken} PV) "
                                  f"Réapparition <t:{int(ps['down_until'])}:R>.")
                else:
                    retal_note = (f"\n🩸 Le mob riposte : -{taken} PV "
                                  f"(il te reste **{ps['hp']}** PV).")
            # THROTTLE anti-429 (Phase 251.10) : 1 edit / 2 s max, sauf salle nettoyée.
            if room["done"] or time.time() - getattr(self, "_last_edit", 0.0) >= 2.0:
                self._last_edit = time.time()
                self._render()
                try:
                    if self._msg:
                        await self._msg.edit(view=self)
                except Exception:
                    pass
            proc_str = (f" {proc['emoji']} {proc['name']} +{proc['bonus']}" if proc else "")
            tail = " — **salle nettoyée !**" if room["done"] else ""
            try:
                await i.followup.send(
                    f"⚔️ `{dmg}` dégâts sur {room['emoji']} {room['mob']} "
                    f"🔊+{int(VOICE_BONUS * 100)}%{proc_str}{tail}{retal_note}",
                    ephemeral=True)
            except Exception:
                pass

    return _DispView()


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
    podium = []          # (display_name, coins) trié 1er→3e (max 3 utilisés)
    total_damage = 0
    for idx, (uid, dmg) in enumerate(rows):
        reward = 400 + int(dmg)  # base + proportionnel aux dégâts
        if _add_coins is not None:
            try:
                await _add_coins(guild_id, int(uid), reward)
            except Exception:
                pass
        total_damage += int(dmg)
        if idx < 3:
            m = guild.get_member(int(uid)) if guild else None
            nm = m.display_name if m else f"Joueur {uid}"
            podium.append((nm, reward))
    if txt and rows:
        # Récap UNIQUE, compact et borné — même format que les autres events
        # de combat. Économie inchangée : tout le monde reste payé ci-dessus,
        # seul l'affichage est borné (« +N autres récompensés »).
        try:
            await txt.send(
                view=ui_v2.combat_recap_view(
                    "🏆", "Donjon", "win", podium,
                    others_count=max(0, len(rows) - 3),
                    participants=len(rows),
                    total_damage=total_damage or None),
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
        await asyncio.sleep(0.2)  # throttle anti-429 (DELETE salons en boucle)


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
    cat = guild.get_channel(int(cat_id)) if cat_id else None
    if cat is not None:
        # Balaie TOUS les salons de la catégorie (texte + toutes les salles
        # vocales) PUIS la catégorie → aucun salon orphelin, quel que soit le
        # nombre de salles créées.
        try:
            children = list(getattr(cat, "channels", []) or [])
        except Exception:
            children = []
        await _delete_run_channels(*children, cat)
    else:
        # Catégorie déjà absente : on tente quand même les salons connus en DB.
        txt = guild.get_channel(int(txt_id)) if txt_id else None
        vc = guild.get_channel(int(vc_id)) if vc_id else None
        await _delete_run_channels(txt, vc)


async def boot_cleanup():
    """Au démarrage : ferme tous les runs 'active' orphelins (salons supprimés)
    + supprime les messages de LOBBY orphelins (boutons morts après reboot).
    Protège contre l'accumulation de salons + l'« Échec de l'interaction »."""
    if _get_db is None:
        return
    # 1) Runs orphelins → suppression des salons
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
        print(f"[dungeon boot_cleanup runs] {ex}")
    # 2) Lobbies orphelins → suppression des messages à boutons morts
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id, message_id FROM dungeon_lobbies") as cur:
                rows = await cur.fetchall()
        done = []
        for gid, cid, mid in rows:
            g = _bot.get_guild(int(gid)) if _bot else None
            if g is None:
                continue  # guilde pas en cache → on garde la ligne pour plus tard
            try:
                ch = g.get_channel(int(cid))
                if ch is not None:
                    await ch.get_partial_message(int(mid)).delete()
            except Exception:
                pass
            done.append(int(gid))
            await asyncio.sleep(0.3)  # throttle anti-429 (DELETE messages en boucle)
        if done:
            async with _get_db() as db:
                await db.executemany(
                    "DELETE FROM dungeon_lobbies WHERE guild_id=?", [(g,) for g in done])
                await db.commit()
            print(f"[dungeon boot_cleanup] {len(done)} lobby(s) orphelin(s) nettoyé(s)")
    except Exception as ex:
        print(f"[dungeon boot_cleanup lobbies] {ex}")


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
