"""
solo_instances.py — Phase 264 : SOCLE EVENTS SOLO PARALLELES + 1er event « Donjon de l'Ombre ».

POURQUOI (demande owner) : les gros combats PUBLICS sont serialises (1 a la fois via
active_combat_lock). Les events SOLO/perso, eux, vivent CHACUN dans le salon prive du
joueur et peuvent tourner EN PARALLELE (plusieurs joueurs en meme temps), SANS jamais
toucher le verrou global — donc zero file d'attente, du contenu H24.

GARANTIES (modelees sur dungeon_instances, eprouve) :
  - 1 salon prive par run (joueur + bot uniquement) sous la categorie « 🌑 Aventures Solo ».
  - Nettoyage TRIPLE COUCHE : (a) a la fin du run (_close_run, idempotent via claim atomique),
    (b) watchdog 5 min (ferme tout run actif > TTL), (c) boot_cleanup (ferme les orphelins au
    demarrage). => aucun salon fantome.
  - Cap de securite : nombre de runs solo actifs borne par guilde (limite salons Discord).
  - HP du run = LOCAL (colonne solo_runs.hp), independant des PV du combat principal : mourir
    dans un donjon solo n'affecte PAS le systeme de mort/respawn global.
  - Anti-429 : chaque clic edite le panneau IN-PLACE via i.response.edit_message (zero fetch) +
    cooldown PAR JOUEUR avant action.

Le module est AUTONOME : il n'ajoute AUCUNE commande slash (entree par bouton de hub).
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

import discord
from discord.ext import tasks

# ─── Dependances injectees (setup) ─────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None
_player_power_fn = None      # async (gid, uid) -> {"atk": int, "deff": int}  (optionnel)
_grant_egg_fn = None         # async (gid, uid, rarity=None) -> bool            (optionnel)
_active_pet_fn = None         # async (gid, uid) -> dict|None (familier actif)   (optionnel)
_give_pet_xp_fn = None        # async (gid, uid, amount) -> None                 (optionnel)
_list_eggs_fn = None          # async (gid, uid) -> [ {id,rarity,ready,...}, … ] (optionnel)
_hatch_now_fn = None          # async (gid, uid, egg_id) -> dict résultat        (optionnel)

# ─── Reglages (volontairement modestes — retention long terme) ─────────────────
_CATEGORY_NAME = "🌑 Aventures Solo"
_RUN_TTL_SEC = 1800          # 30 min : un run abandonne est ferme par le watchdog
_MAX_ACTIVE_RUNS = 40        # plafond de securite par guilde (limite salons Discord)
_CLICK_CD = 1.5              # anti-spam par joueur (s)
_COOLDOWN_MIN = 60           # cooldown perso entre 2 donjons (min)

_DUNGEON_KIND = "shadow_dungeon"
_DG_MAX_DEPTH = 6            # 6 salles max (push-your-luck)
_DG_BASE_PLAYER_HP = 150
_DG_MOB_BASE_HP = 60
_DG_MOB_BASE_ATK = 14
_DG_COINS_PER_ROOM = 18      # x profondeur

# Ambiance : noms de salles par paliers (de plus en plus menacant)
_DG_ROOMS = [
    ("🕯️", "Antichambre poussiéreuse"),
    ("🕸️", "Galerie des Murmures"),
    ("💀", "Ossuaire effondré"),
    ("🩸", "Salle du Pacte"),
    ("🌑", "Abysse sans fond"),
    ("👁️", "Sanctuaire de l'Œil"),
]
_DG_MOBS = ["Rôdeur d'ombre", "Goule affamée", "Spectre rancunier",
            "Liche mineure", "Effroi rampant", "Gardien des abysses"]

# ─── Chasse au Trésor Solo (énigmes) ───────────────────────────────────────────
_TREASURE_KIND = "treasure_solo"
_TS_STEPS = 3                 # 3 énigmes progressives
_TS_COINS_PER_STEP = 28       # x (étape+1)
# Énigmes : question + 4 options + index de la bonne réponse. Le pool est tiré
# DÉTERMINISTE par run_id (Random(run_id)) → pas besoin de stocker la séquence, et
# le custom_id du bouton porte l'INDEX de l'option (pas « correct/faux ») → zéro fuite.
_RIDDLES = [
    {"q": "Je grandis quand on me nourrit, mais je meurs si on me donne à boire. Qui suis-je ?",
     "opts": ["Le feu", "L'eau", "Le vent", "La terre"], "correct": 0},
    {"q": "Plus j'ai de gardiens, moins je suis en sécurité. Que suis-je ?",
     "opts": ["Un secret", "Un trésor", "Un roi", "Une forteresse"], "correct": 0},
    {"q": "Quel est le seul trésor qui grandit quand on le partage ?",
     "opts": ["L'or", "Le savoir", "Les gemmes", "Le pouvoir"], "correct": 1},
    {"q": "Je parle sans bouche et j'entends sans oreilles. Qui suis-je ?",
     "opts": ["L'écho", "Le miroir", "L'ombre", "Le rêve"], "correct": 0},
    {"q": "Je passe sans jamais revenir, je guéris et je détruis. Qui suis-je ?",
     "opts": ["Le temps", "Le vent", "La rivière", "La nuit"], "correct": 0},
    {"q": "Combien de fois peut-on soustraire 5 du nombre 25 ?",
     "opts": ["Une seule fois", "Cinq fois", "Vingt-cinq fois", "Zéro"], "correct": 0},
    {"q": "Qu'attrape-t-on sans jamais pouvoir le lancer ?",
     "opts": ["Un rhume", "Une balle", "Un poisson", "Un papillon"], "correct": 0},
    {"q": "Elle te suit le jour, disparaît la nuit, et s'allonge au couchant. Qui ?",
     "opts": ["Ton ombre", "La lune", "Le temps", "Ton reflet"], "correct": 0},
    {"q": "Plus on en prend, plus on en laisse derrière soi. Quoi ?",
     "opts": ["Des pas", "Des miettes", "Des souvenirs", "Des pièces"], "correct": 0},
    {"q": "Quelle clé n'ouvre pourtant aucune porte ?",
     "opts": ["Une clé de sol", "Une clé en or", "Une clé rouillée", "Un trousseau"], "correct": 0},
    {"q": "Plus je sèche, plus je suis mouillée. Que suis-je ?",
     "opts": ["Une serviette", "Une éponge", "Une rivière", "La pluie"], "correct": 0},
    {"q": "On me casse toujours avant de m'utiliser. Que suis-je ?",
     "opts": ["Un œuf", "Une promesse", "Un record", "Une noix"], "correct": 0},
]

# ─── Défi du Familier (TON familier combat, toi tu le déchaînes) ────────────────
_PETTRIAL_KIND = "pet_trial"
_PT_PLAYER_HP = 120          # PV LOCAUX du run (≠ PV combat global)
_PT_ENEMY_BASE_HP = 200
_PT_ENEMY_BASE_ATK = 14
_PT_MAX_TURNS = 14
_PT_WIN_COINS = 80           # récompense modeste à la victoire
_PT_WIN_PET_XP = 6
_PT_ENEMIES = [
    ("🎯", "Mannequin runique"), ("🗿", "Golem d'entraînement"),
    ("👻", "Spectre du dojo"), ("🐲", "Drakeling captif"),
]

# ─── Sanctuaire d'Épreuves (survie à vagues, push-your-luck) ────────────────────
_SANCTUARY_KIND = "sanctuary"
_SANC_MAX_WAVES = 6
_SANC_PLAYER_HP = 150
_SANC_MOB_BASE_HP = 70
_SANC_MOB_BASE_ATK = 15
_SANC_COINS_PER_WAVE = 22       # x (vague+1)
_SANC_HEAL_FRAC = 0.30          # soin après chaque vague nettoyée
_SANC_MOBS = ["Gargouille mineure", "Spectre des catacombes", "Golem érodé",
              "Bête ancestrale", "Champion déchu", "Gardien du Seuil"]

# ─── Arène Miroir (combat contre un clone EXACT de tes stats) ───────────────────
_MIRROR_KIND = "mirror"
_MIRROR_MAX_TURNS = 14
_MIRROR_BASE_HP = 110           # + def*2 → la def compte
_MIRROR_WIN_COINS = 90
_MIRROR_COOLDOWN_MIN = 90       # long : prestige rare

# ─── Enquête Perso (déduction + gamble : accuser tôt = plus de gain, +risque) ───
_INVESTIGATE_KIND = "investigate"
_INV_WIN_COINS = 45             # base modeste
_INV_RISK_BONUS = 18            # par indice NON utilisé (accuser tôt = +risque/+gain)
_INV_CASES = [
    {"scene": "Le trésor scellé du marchand elfe a disparu de sa réserve.",
     "suspects": [("🏹", "Rôdeur des Bois"), ("🗿", "Golem Gardien"),
                  ("🧙", "Mage Noir"), ("🩸", "Acolyte Maudit")]},
    {"scene": "Les archives interdites de la guilde ont été dérobées dans la nuit.",
     "suspects": [("📜", "Scribe Ambitieux"), ("🛡️", "Garde Soudoyé"),
                  ("🕯️", "Mage de Cour"), ("🎭", "Espion Masqué")]},
    {"scene": "Le reliquaire du temple a été vidé sans briser le sceau sacré.",
     "suspects": [("⛪", "Prêtre Déchu"), ("🐀", "Voleur des Égouts"),
                  ("👑", "Noble Endetté"), ("🔮", "Oracle Corrompu")]},
    {"scene": "La gemme de la couronne a été remplacée par une copie.",
     "suspects": [("💎", "Joaillier Royal"), ("🗝️", "Chambellan"),
                  ("🎨", "Faussaire de Génie"), ("🍷", "Échanson Jaloux")]},
]

# ─── Forge du Défi (trempe push-your-luck : tu mises tes GAINS non encaissés) ───
# Aucune mise du portefeuille : tu ne risques QUE le butin accumulé non encaissé
# (le lingot se brise = tu perds ce butin, jamais tes pièces réelles). FAIL-CLOSED.
_FORGE_KIND = "forge"
_FORGE_MAX = 6
_FORGE_RATES = [1.00, 0.85, 0.72, 0.58, 0.45, 0.33]  # proba de réussite par palier
_FORGE_GAIN = 16            # × (palier+1) ajouté au butin à chaque trempe réussie
_FORGE_COOLDOWN_MIN = 30
_FORGE_TIERS = ["Lingot brut", "Lame affûtée", "Acier trempé", "Arme runique",
                "Relique mythique", "Éclat stellaire"]

# ─── Incubation Active (couver un œuf EXISTANT par l'activité, pas l'attente) ───
# Complète /pet (incubation par le TEMPS) : ici les CLICS remplacent l'attente.
_INCUBATION_KIND = "incubation"
_INCUB_CLICKS = 20         # clics pour faire éclore l'œuf (activité = vitesse)
_INCUB_COOLDOWN_MIN = 0    # pas de cooldown : limité par l'œuf consommé + 1 run/joueur


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
          add_coins_fn=None, player_power_fn=None, grant_egg_fn=None,
          active_pet_fn=None, give_pet_xp_fn=None,
          list_eggs_fn=None, hatch_now_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _player_power_fn, _grant_egg_fn
    global _active_pet_fn, _give_pet_xp_fn, _list_eggs_fn, _hatch_now_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _player_power_fn = player_power_fn
    _grant_egg_fn = grant_egg_fn
    _active_pet_fn = active_pet_fn
    _give_pet_xp_fn = give_pet_xp_fn
    _list_eggs_fn = list_eggs_fn
    _hatch_now_fn = hatch_now_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS solo_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    channel_id INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    depth INTEGER DEFAULT 0,
                    hp INTEGER DEFAULT 0,
                    hp_max INTEGER DEFAULT 0,
                    mob_hp INTEGER DEFAULT 0,
                    mob_hp_max INTEGER DEFAULT 0,
                    coins_pending INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_solo_active "
                "ON solo_runs(guild_id, status)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS solo_cooldowns (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    last_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id, kind)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[solo init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  SOCLE GENERIQUE : salon prive, cleanup, cooldown, cap
# ═══════════════════════════════════════════════════════════════════════════════
_last_click: dict = {}  # {(run_id|uid, uid): epoch} anti-429


async def _active_run_count(guild_id: int) -> int:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM solo_runs WHERE guild_id=? AND status='active'",
                (guild_id,)) as cur:
                r = await cur.fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


async def _user_active_run(guild_id: int, user_id: int, kind: str):
    """Retourne l'id du run actif de ce joueur pour ce type, ou None."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM solo_runs WHERE guild_id=? AND user_id=? AND kind=? "
                "AND status='active' LIMIT 1",
                (guild_id, user_id, kind)) as cur:
                r = await cur.fetchone()
        return int(r[0]) if r else None
    except Exception:
        return None


async def _cooldown_remaining(guild_id: int, user_id: int, kind: str, minutes: int) -> int:
    """Minutes restantes de cooldown (0 si dispo). Fail-open (0)."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT CAST((julianday('now') - julianday(last_at)) * 1440 AS INTEGER) "
                "FROM solo_cooldowns WHERE guild_id=? AND user_id=? AND kind=?",
                (guild_id, user_id, kind)) as cur:
                r = await cur.fetchone()
        if not r or r[0] is None:
            return 0
        elapsed = int(r[0])
        return max(0, minutes - elapsed)
    except Exception:
        return 0


async def _stamp_cooldown(guild_id: int, user_id: int, kind: str):
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO solo_cooldowns(guild_id, user_id, kind, last_at) "
                "VALUES(?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id, kind) DO UPDATE SET last_at=CURRENT_TIMESTAMP",
                (guild_id, user_id, kind))
            await db.commit()
    except Exception:
        pass


async def _get_solo_category(guild: discord.Guild):
    """Categorie « 🌑 Aventures Solo » (creee/reutilisee). Salons prives par joueur."""
    for c in guild.categories:
        if c.name == _CATEGORY_NAME:
            return c
    me = guild.me
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                        manage_channels=True),
    }
    try:
        return await guild.create_category(name=_CATEGORY_NAME, overwrites=ow,
                                           reason="Aventures solo")
    except Exception as ex:
        print(f"[solo category] {ex}")
        return None


async def _create_solo_channel(guild: discord.Guild, member: discord.Member, slug: str):
    """Cree le salon prive (joueur + bot). Retourne le salon ou None."""
    cat = await _get_solo_category(guild)
    me = guild.me
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                            read_message_history=True),
    }
    name = f"{slug}-{member.display_name}"[:95]
    try:
        return await guild.create_text_channel(
            name=name, category=cat, overwrites=ow, reason="Aventure solo")
    except Exception as ex:
        print(f"[solo create channel] {ex}")
        return None


_RESULT_LINGER_SEC = 7          # le panneau de résultat reste visible avant fermeture
_pending_closes: set = set()    # garde une réf aux tâches de fermeture différée (anti-GC)


async def _claim_run(run_id: int) -> bool:
    """Claim ATOMIQUE de fin de run (exactly-once). UPDATE status='ended' WHERE
    status='active' → True SSI ce call a gagné (rowcount==1). NE supprime PAS le
    salon (le `channel_id` reste pour la suppression ultérieure)."""
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE solo_runs SET status='ended' WHERE id=? AND status='active'",
                (run_id,))
            await db.commit()
            return getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[solo _claim_run] {ex}")
        return False


async def _delete_run_channel(run_id: int):
    """Supprime le salon du run (idempotent) + met channel_id=0 pour ne plus le
    re-traiter. Sans danger si déjà supprimé (get_channel→None = no-op)."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id FROM solo_runs WHERE id=?", (run_id,)) as c:
                row = await c.fetchone()
            if not row:
                return
            gid, ch_id = int(row[0]), int(row[1] or 0)
            if ch_id == 0:
                return  # déjà nettoyé
            await db.execute("UPDATE solo_runs SET channel_id=0 WHERE id=?", (run_id,))
            await db.commit()
        g = _bot.get_guild(gid) if _bot else None
        if g:
            ch = g.get_channel(ch_id)
            if ch is not None:
                try:
                    await ch.delete(reason="Aventure solo terminée")
                except Exception:
                    pass
    except Exception as ex:
        print(f"[solo _delete_run_channel] {ex}")


async def _delayed_close(run_id: int):
    """Attend _RESULT_LINGER_SEC (le joueur savoure son résultat) puis supprime le
    salon. Filet de sécurité si la tâche est perdue (reboot) : le watchdog +
    boot_cleanup balaient aussi les runs 'ended' dont le salon traîne encore."""
    try:
        await asyncio.sleep(_RESULT_LINGER_SEC)
    except Exception:
        pass
    await _delete_run_channel(run_id)


async def _close_run(run_id: int) -> bool:
    """Termine un run (claim atomique exactly-once) en LAISSANT le panneau de
    résultat visible ~_RESULT_LINGER_SEC s, puis supprime le salon. Retourne True
    SSI ce call a gagné le claim → l'appelant ne paie la récompense QUE dans ce cas
    (anti double-pay). Utilisé par TOUS les chemins de fin d'event (victoire/défaite/
    extraction/abandon)."""
    won = await _claim_run(run_id)
    if won:
        try:
            t = asyncio.create_task(_delayed_close(run_id))
            _pending_closes.add(t)
            t.add_done_callback(_pending_closes.discard)
        except Exception:
            await _delete_run_channel(run_id)  # fallback : suppression immédiate
    return won


async def _close_run_now(run_id: int) -> bool:
    """Comme _close_run mais supprime le salon IMMÉDIATEMENT (watchdog / boot_cleanup
    — aucun panneau de résultat à montrer pour un run abandonné/orphelin). Idempotent."""
    won = await _claim_run(run_id)
    await _delete_run_channel(run_id)  # supprime même si claim perdu (idempotent)
    return won


async def boot_cleanup():
    """Au boot : ferme tous les runs solo 'active' (salons orphelins potentiels)
    + balaie les runs 'ended' dont le salon traîne encore (tâche de fermeture
    différée perdue lors d'un reboot pendant le délai de résultat)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM solo_runs WHERE status='active'") as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
            async with db.execute(
                "SELECT id FROM solo_runs WHERE status='ended' AND channel_id != 0") as cur:
                stale = [int(r[0]) for r in await cur.fetchall()]
        for rid in ids:
            await _close_run_now(rid)
        for rid in stale:
            await _delete_run_channel(rid)
        if ids or stale:
            print(f"[solo boot_cleanup] {len(ids)} actif(s) + {len(stale)} salon(s) résiduel(s) nettoyé(s)")
    except Exception as ex:
        print(f"[solo boot_cleanup] {ex}")


@tasks.loop(minutes=5)
async def solo_watchdog():
    """Ferme tout run actif depuis > _RUN_TTL_SEC (abandon) + filet de sécurité :
    supprime les salons des runs 'ended' restés ouverts (tâche différée perdue).
    1 seul watchdog pour TOUS les types d'events solo."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM solo_runs WHERE status='active' AND "
                "datetime(started_at) < datetime('now', ?)",
                (f'-{_RUN_TTL_SEC} seconds',)) as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
            # Filet : runs terminés dont le salon n'a pas encore été supprimé et
            # dont le délai de résultat est largement écoulé (évite de couper un
            # linger en cours ; started_at ancien ⇒ le run est fini depuis longtemps).
            async with db.execute(
                "SELECT id FROM solo_runs WHERE status='ended' AND channel_id != 0 AND "
                "datetime(started_at) < datetime('now', '-60 seconds')") as cur:
                stale = [int(r[0]) for r in await cur.fetchall()]
        for rid in ids:
            await _close_run_now(rid)
        for rid in stale:
            await _delete_run_channel(rid)
    except Exception as ex:
        print(f"[solo_watchdog] {ex}")


@solo_watchdog.before_loop
async def _solo_wait():
    if _bot is not None:
        await _bot.wait_until_ready()


def register_persistent_views(bot_instance):
    """Bouton d'ENTREE persistant (ouvre le hub des aventures solo). Les vues de RUN
    sont a timeout (salon supprime a la fin + boot_cleanup) → pas besoin de persistance."""
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(SoloOpenButton)
    except Exception as ex:
        print(f"[solo register] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  HUB SOLO (panneau d'entree, ephemeral)
# ═══════════════════════════════════════════════════════════════════════════════
def _v2get():
    # Phase 264 FIX : les clés du dict _v2h sont PRÉFIXÉES « v2_ » (cf. bot.py:42473)
    # — utiliser "title"/"body" renvoyait None → module mort (hub/panneau jamais rendus).
    return (_v2.get("LayoutView"), _v2.get("v2_title"), _v2.get("v2_subtitle"),
            _v2.get("v2_body"), _v2.get("v2_divider"), _v2.get("v2_container"))


async def open_solo_hub(i: discord.Interaction):
    """Panneau ephemere listant les aventures solo dispo + boutons Lancer."""
    if not await _safe_defer(i):
        return
    if i.guild is None:  # garde MP (defense en profondeur)
        return await _safe_followup(i, content="❌ Serveur uniquement.")
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    if not all((LayoutView, v2_title, v2_body, v2_container)):
        return await _safe_followup(i, content="❌ UI indisponible un instant, réessaie.")
    cd_dg = await _cooldown_remaining(i.guild.id, i.user.id, _DUNGEON_KIND, _COOLDOWN_MIN)
    cd_ts = await _cooldown_remaining(i.guild.id, i.user.id, _TREASURE_KIND, _COOLDOWN_MIN)
    cd_pt = await _cooldown_remaining(i.guild.id, i.user.id, _PETTRIAL_KIND, _COOLDOWN_MIN)
    cd_sn = await _cooldown_remaining(i.guild.id, i.user.id, _SANCTUARY_KIND, _COOLDOWN_MIN)
    cd_mr = await _cooldown_remaining(i.guild.id, i.user.id, _MIRROR_KIND, _MIRROR_COOLDOWN_MIN)
    cd_iv = await _cooldown_remaining(i.guild.id, i.user.id, _INVESTIGATE_KIND, _COOLDOWN_MIN)
    cd_fg = await _cooldown_remaining(i.guild.id, i.user.id, _FORGE_KIND, _FORGE_COOLDOWN_MIN)
    cd_ic = await _cooldown_remaining(i.guild.id, i.user.id, _INCUBATION_KIND, _INCUB_COOLDOWN_MIN)
    # Phase 271 : preuve sociale — compte LIVE des aventures en cours (frais, à l'ouverture,
    # zéro coût de refresh). « Tu n'es pas seul » → incite à se lancer.
    try:
        _active_now = await _active_run_count(i.guild.id)
    except Exception:
        _active_now = 0
    _live_line = (f"🌑 **{_active_now}** aventure(s) solo en cours sur le serveur — rejoins le mouvement !"
                  if _active_now > 0 else "🌑 _Sois le premier à lancer une aventure solo aujourd'hui !_")
    items = [
        v2_title("🌑 Aventures Solo"),
        v2_subtitle("Des défis rien que pour toi — ton salon, à ton rythme, "
                    "plusieurs joueurs en parallèle."),
        v2_body(_live_line),
        v2_divider(),
        v2_body(
            "**🗝️ Donjon de l'Ombre**\n"
            "_Descente à étages : **descends** (+risque, +butin) ou **extrais** ton butin "
            "et repars sain. Tombe avant d'extraire = moitié perdue._"
            + (f"\n⏳ _dispo dans {cd_dg} min_" if cd_dg > 0 else "")
        ),
        v2_body(
            "**💎 Chasse au Trésor**\n"
            "_3 énigmes de plus en plus payantes. Une erreur et tu repars avec la moitié._"
            + (f"\n⏳ _dispo dans {cd_ts} min_" if cd_ts > 0 else "")
        ),
        v2_body(
            "**🐾 Défi du Familier**\n"
            "_Ici c'est TON familier qui combat ! Actif = grosse salve, passif = soigne._"
            + (f"\n⏳ _dispo dans {cd_pt} min_" if cd_pt > 0 else "")
        ),
        v2_body(
            "**🏛️ Sanctuaire d'Épreuves**\n"
            "_Survis aux vagues qui s'accélèrent. Sécurise ton butin avant de tomber._"
            + (f"\n⏳ _dispo dans {cd_sn} min_" if cd_sn > 0 else "")
        ),
        v2_body(
            "**🪞 Arène Miroir**\n"
            "_Affronte un clone EXACT de tes stats — tu frappes en premier. Prestige rare._"
            + (f"\n⏳ _dispo dans {cd_mr} min_" if cd_mr > 0 else "")
        ),
        v2_body(
            "**🔍 Enquête Perso**\n"
            "_Trouve le coupable. Accuse tôt = prime de flair (+risque) ; cherche des indices = plus sûr._"
            + (f"\n⏳ _dispo dans {cd_iv} min_" if cd_iv > 0 else "")
        ),
        v2_body(
            "**🔨 Forge du Défi**\n"
            "_Trempe push-your-luck : tente d'améliorer, encaisse quand tu veux. Échec = tu perds "
            "le butin NON encaissé (jamais tes pièces réelles)._"
            + (f"\n⏳ _dispo dans {cd_fg} min_" if cd_fg > 0 else "")
        ),
        v2_body(
            "**🥚 Incubation Active**\n"
            "_Tu as un œuf ? Couve-le à la force du clic — ton activité éclôt le familier bien "
            "plus vite que l'attente._"
        ),
    ]

    class _SoloHub(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0x6C3483))
            b1 = discord.ui.Button(
                label=("⏳ Donjon" if cd_dg > 0 else "🗝️ Donjon"),
                style=(discord.ButtonStyle.secondary if cd_dg > 0 else discord.ButtonStyle.success),
                custom_id="solo_start:shadow_dungeon", disabled=cd_dg > 0)
            b1.callback = _on_start_dungeon_click
            b2 = discord.ui.Button(
                label=("⏳ Trésor" if cd_ts > 0 else "💎 Trésor"),
                style=(discord.ButtonStyle.secondary if cd_ts > 0 else discord.ButtonStyle.primary),
                custom_id="solo_start:treasure_solo", disabled=cd_ts > 0)
            b2.callback = _on_start_treasure_click
            b3 = discord.ui.Button(
                label=("⏳ Familier" if cd_pt > 0 else "🐾 Familier"),
                style=(discord.ButtonStyle.secondary if cd_pt > 0 else discord.ButtonStyle.success),
                custom_id="solo_start:pet_trial", disabled=cd_pt > 0)
            b3.callback = _on_start_pettrial_click
            b4 = discord.ui.Button(
                label=("⏳ Sanctuaire" if cd_sn > 0 else "🏛️ Sanctuaire"),
                style=(discord.ButtonStyle.secondary if cd_sn > 0 else discord.ButtonStyle.danger),
                custom_id="solo_start:sanctuary", disabled=cd_sn > 0)
            b4.callback = _on_start_sanctuary_click
            b5 = discord.ui.Button(
                label=("⏳ Miroir" if cd_mr > 0 else "🪞 Miroir"),
                style=(discord.ButtonStyle.secondary if cd_mr > 0 else discord.ButtonStyle.danger),
                custom_id="solo_start:mirror", disabled=cd_mr > 0)
            b5.callback = _on_start_mirror_click
            b6 = discord.ui.Button(
                label=("⏳ Enquête" if cd_iv > 0 else "🔍 Enquête"),
                style=(discord.ButtonStyle.secondary if cd_iv > 0 else discord.ButtonStyle.primary),
                custom_id="solo_start:investigate", disabled=cd_iv > 0)
            b6.callback = _on_start_investigate_click
            b7 = discord.ui.Button(
                label=("⏳ Forge" if cd_fg > 0 else "🔨 Forge"),
                style=(discord.ButtonStyle.secondary if cd_fg > 0 else discord.ButtonStyle.danger),
                custom_id="solo_start:forge", disabled=cd_fg > 0)
            b7.callback = _on_start_forge_click
            b8 = discord.ui.Button(
                label="🥚 Incubation",
                style=discord.ButtonStyle.primary,
                custom_id="solo_start:incubation")
            b8.callback = _on_start_incubation_click
            self.add_item(discord.ui.ActionRow(b1, b2, b3, b4))
            self.add_item(discord.ui.ActionRow(b5, b6, b7, b8))

    await _safe_followup(i, view=_SoloHub())


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers interaction (autonomes — pas de dependance bot.py)
# ═══════════════════════════════════════════════════════════════════════════════
async def _safe_defer(i: discord.Interaction, ephemeral: bool = True) -> bool:
    try:
        await i.response.defer(ephemeral=ephemeral)
        return True
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        return True
    except Exception:
        return False


async def _safe_followup(i: discord.Interaction, **kwargs):
    kwargs.setdefault("ephemeral", True)
    try:
        return await i.followup.send(**kwargs)
    except Exception:
        return None


def _click_too_soon(uid: int) -> bool:
    try:
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_click.get(uid, 0.0) < _CLICK_CD:
            return True
        _last_click[uid] = now
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  DONJON DE L'OMBRE
# ═══════════════════════════════════════════════════════════════════════════════
def _mob_for_depth(depth: int):
    idx = min(depth, len(_DG_MOBS) - 1)
    emoji, room = _DG_ROOMS[min(depth, len(_DG_ROOMS) - 1)]
    return {
        "name": _DG_MOBS[idx],
        "emoji": emoji,
        "room": room,
        "hp": int(_DG_MOB_BASE_HP * (1.0 + depth * 0.6)),
        "atk": int(_DG_MOB_BASE_ATK * (1.0 + depth * 0.45)),
    }


async def _player_atk_def(gid: int, uid: int):
    base_atk, deff = 26, 0
    if _player_power_fn is not None:
        try:
            p = await _player_power_fn(gid, uid)
            base_atk += int(p.get("atk", 0) or 0)
            deff += int(p.get("deff", 0) or 0)
        except Exception:
            pass
    return base_atk, deff


async def _on_start_dungeon_click(i: discord.Interaction):
    await start_shadow_dungeon(i)


async def start_shadow_dungeon(i: discord.Interaction):
    """Lance un Donjon de l'Ombre dans un salon prive au joueur. PARALLELE (ne touche
    PAS le verrou global). Cooldown perso + cap de securite."""
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        # 1 run a la fois par joueur
        existing = await _user_active_run(i.guild.id, i.user.id, _DUNGEON_KIND)
        if existing:
            return await _safe_followup(
                i, content="🗝️ Tu as déjà un donjon en cours — termine-le d'abord (ou attends son expiration).")
        # cooldown
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _DUNGEON_KIND, _COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochain donjon dans `{cd}` min.")
        # cap de securite (limite salons Discord)
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(
                i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        # permissions bot
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "🌑-donjon")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")

        hp_max = _DG_BASE_PLAYER_HP
        mob = _mob_for_depth(0)
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,?,?,?,?,0)",
                    (i.guild.id, i.user.id, _DUNGEON_KIND, ch.id, hp_max, hp_max,
                     mob["hp"], mob["hp"]))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo start INSERT] {ex}")
            try:
                await ch.delete(reason="échec init donjon")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")

        await _stamp_cooldown(i.guild.id, i.user.id, _DUNGEON_KIND)
        run = await _get_run(run_id)
        try:
            # LayoutView V2 = PAS de content (400 50035 sinon) → le ping se fait via le
            # followup ephemere ci-dessous, pas dans le salon.
            await ch.send(view=_build_dungeon_view(run))
        except Exception as ex:
            print(f"[solo start send] {ex}")
        await _safe_followup(i, content=f"🗝️ {member.mention} ton donjon t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_shadow_dungeon] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


async def _get_run(run_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, user_id, kind, channel_id, status, depth, hp, hp_max, "
                "mob_hp, mob_hp_max, coins_pending FROM solo_runs WHERE id=?", (run_id,)) as cur:
                r = await cur.fetchone()
        if not r:
            return None
        return {
            "id": r[0], "guild_id": r[1], "user_id": r[2], "kind": r[3], "channel_id": r[4],
            "status": r[5], "depth": r[6], "hp": r[7], "hp_max": r[8], "mob_hp": r[9],
            "mob_hp_max": r[10], "coins_pending": r[11],
        }
    except Exception:
        return None


def _bar(cur: int, mx: int, width: int = 14) -> str:
    cur = max(0, int(cur or 0)); mx = max(1, int(mx or 1))
    f = max(0, min(width, int(round(width * cur / mx))))
    return "█" * f + "░" * (width - f)


def _build_dungeon_view(run: dict):
    """LayoutView V2 live du donjon (re-rendu a chaque action)."""
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    depth = int(run["depth"])
    mob = _mob_for_depth(depth)
    items = [
        v2_title(f"🗝️ Donjon de l'Ombre — Salle {depth + 1}"),
        v2_subtitle(f"{mob['emoji']} _{mob['room']}_"),
        v2_divider(),
        v2_body(
            f"**{mob['emoji']} {mob['name']}**\n"
            f"❤️ `{_bar(run['mob_hp'], run['mob_hp_max'])}` `{max(0, run['mob_hp'])}/{run['mob_hp_max']}`"
        ),
        v2_body(
            f"**🛡️ Toi**\n"
            f"❤️ `{_bar(run['hp'], run['hp_max'])}` `{max(0, run['hp'])}/{run['hp_max']}`\n"
            f"🎒 Butin sécurisable : **{run['coins_pending']}** 🪙  ·  Profondeur : **{depth + 1}/{_DG_MAX_DEPTH}**"
        ),
        v2_divider(),
        v2_body("⚔️ Attaque pour vaincre · 🎒 Extrais pour repartir sain · plus tu descends, meilleur est le loot."),
    ]

    class _DgView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0x6C3483))
            atk = discord.ui.Button(label="⚔️ Attaquer", style=discord.ButtonStyle.danger,
                                    custom_id=f"sdg_atk:{run['id']}")
            ext = discord.ui.Button(label=f"🎒 Extraire ({run['coins_pending']} 🪙)",
                                    style=discord.ButtonStyle.success,
                                    custom_id=f"sdg_ext:{run['id']}")
            atk.callback = _on_dg_attack
            ext.callback = _on_dg_extract
            self.add_item(discord.ui.ActionRow(atk, ext))

    return _DgView()


def _owns_run(i: discord.Interaction, run: dict) -> bool:
    return run is not None and run["status"] == "active" and int(run["user_id"]) == i.user.id


async def _on_dg_attack(i: discord.Interaction):
    # ACK d'abord (edit_message acquitte), puis cooldown anti-spam.
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        atk, deff = await _player_atk_def(gid, uid)
        dmg = int(random.uniform(0.85, 1.15) * max(8, atk))
        mob = _mob_for_depth(int(run["depth"]))
        new_mob_hp = max(0, int(run["mob_hp"]) - dmg)

        if new_mob_hp > 0:
            # Le monstre riposte (mitige par la def, plancher 4).
            retal = max(4, int(mob["atk"] * random.uniform(0.8, 1.1)) - deff // 2)
            new_hp = int(run["hp"]) - retal
            if new_hp <= 0:
                # MORT avant extraction → perd la moitie du butin securisable.
                kept = int(run["coins_pending"]) // 2
                won = await _close_run(rid)
                if won and kept > 0 and _add_coins is not None:
                    try:
                        await _add_coins(gid, uid, kept)
                    except Exception:
                        pass
                return await _safe_edit(
                    i,
                    f"💀 **Tu es tombé** au fond de la salle {int(run['depth']) + 1}…\n"
                    f"Tu repars avec la moitié de ton butin : **+{kept}** 🪙.\n"
                    f"_Ce salon se ferme. Reviens plus fort !_")
            # combat continue
            async with _get_db() as db:
                await db.execute(
                    "UPDATE solo_runs SET mob_hp=?, hp=? WHERE id=? AND status='active'",
                    (new_mob_hp, new_hp, rid))
                await db.commit()
            run2 = await _get_run(rid)
            try:
                return await i.response.edit_message(view=_build_dungeon_view(run2))
            except Exception:
                return
        else:
            # Monstre vaincu → butin de salle, on avance.
            depth = int(run["depth"])
            gain = _DG_COINS_PER_ROOM * (depth + 1)
            new_depth = depth + 1
            new_coins = int(run["coins_pending"]) + gain
            if new_depth >= _DG_MAX_DEPTH:
                # FOND ATTEINT → extraction auto victorieuse + bonus + chance d'oeuf.
                bonus = gain  # bonus de fond
                total = new_coins + bonus
                won = await _close_run(rid)
                if won and _add_coins is not None:
                    try:
                        await _add_coins(gid, uid, total)
                    except Exception:
                        pass
                egg_txt = await _maybe_grant_egg(gid, uid, new_depth) if won else ""
                return await _safe_edit(
                    i,
                    f"🏆 **Tu as atteint le fond du Donjon de l'Ombre !**\n"
                    f"Butin total sécurisé : **+{total}** 🪙{egg_txt}\n"
                    f"_Légendaire descente. Ce salon se ferme._")
            # salle suivante : nouveau monstre
            nmob = _mob_for_depth(new_depth)
            async with _get_db() as db:
                await db.execute(
                    "UPDATE solo_runs SET depth=?, coins_pending=?, mob_hp=?, mob_hp_max=? "
                    "WHERE id=? AND status='active'",
                    (new_depth, new_coins, nmob["hp"], nmob["hp"], rid))
                await db.commit()
            run2 = await _get_run(rid)
            try:
                return await i.response.edit_message(view=_build_dungeon_view(run2))
            except Exception:
                return
    except Exception as ex:
        print(f"[_on_dg_attack] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


async def _on_dg_extract(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):  # Phase 264 : anti double-clic (comme l'attaque)
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        total = int(run["coins_pending"])
        await _close_run(rid)
        if total > 0 and _add_coins is not None:
            try:
                await _add_coins(gid, uid, total)
            except Exception:
                pass
        egg_txt = ""
        if int(run["depth"]) >= 3:  # extraction profonde → petite chance d'oeuf
            egg_txt = await _maybe_grant_egg(gid, uid, int(run["depth"]))
        await _safe_edit(
            i,
            f"🎒 **Extraction réussie !** Tu repars sain et sauf avec **+{total}** 🪙"
            f"{egg_txt}\n_Ce salon se ferme. À la prochaine descente !_")
    except Exception as ex:
        print(f"[_on_dg_extract] {ex}")


async def _maybe_grant_egg(gid: int, uid: int, depth: int) -> str:
    """Petite chance d'oeuf (rarete commune) selon la profondeur. Optionnel/fail-safe."""
    if _grant_egg_fn is None:
        return ""
    try:
        chance = 0.05 + depth * 0.03  # 5% +3%/salle, plafonne naturellement bas
        if random.random() < min(0.25, chance):
            res = await _grant_egg_fn(gid, uid)
            if res:
                return "\n🥚 Et un **œuf** trouvé dans les profondeurs ! (`/pet` pour l'éclore)"
    except Exception:
        pass
    return ""


def _parse_rid(i: discord.Interaction):
    try:
        cid = (i.data or {}).get("custom_id", "")
        return int(cid.split(":")[1])
    except Exception:
        return None


async def _safe_edit(i: discord.Interaction, text: str):
    """Edite le panneau du run en message final (boutons retires)."""
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    try:
        _body = v2_body(text)
        _cont = v2_container(_body, color=0x6C3483)

        class _Final(LayoutView):
            def __init__(self):
                super().__init__(timeout=1)
                self.add_item(_cont)

        await i.response.edit_message(view=_Final())
    except Exception:
        try:
            await i.response.defer()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  CHASSE AU TRESOR SOLO (énigmes déterministes par run_id)
# ═══════════════════════════════════════════════════════════════════════════════
def _ts_riddle_indices(run_id: int):
    """3 indices d'énigmes DÉTERMINISTES pour ce run (seed=run_id) → recalculables
    sans stockage. random.Random est déterministe (≠ random global interdit ici)."""
    try:
        return random.Random(int(run_id)).sample(range(len(_RIDDLES)), _TS_STEPS)
    except Exception:
        return list(range(_TS_STEPS))


def _ts_riddle_at(run_id: int, step: int):
    idxs = _ts_riddle_indices(run_id)
    return _RIDDLES[idxs[max(0, min(step, len(idxs) - 1))]]


async def _on_start_treasure_click(i: discord.Interaction):
    await start_treasure_solo(i)


async def start_treasure_solo(i: discord.Interaction):
    """Lance une Chasse au Trésor SOLO dans un salon prive. PARALLELE (zero verrou global)."""
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if await _user_active_run(i.guild.id, i.user.id, _TREASURE_KIND):
            return await _safe_followup(
                i, content="💎 Tu as déjà une chasse en cours — termine-la d'abord.")
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _TREASURE_KIND, _COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochaine chasse dans `{cd}` min.")
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(
                i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "💎-trésor")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,0,0,0,0,0)",
                    (i.guild.id, i.user.id, _TREASURE_KIND, ch.id))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo treasure INSERT] {ex}")
            try:
                await ch.delete(reason="échec init trésor")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")

        await _stamp_cooldown(i.guild.id, i.user.id, _TREASURE_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_treasure_view(run))
        except Exception as ex:
            print(f"[solo treasure send] {ex}")
        await _safe_followup(i, content=f"💎 {member.mention} ta chasse t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_treasure_solo] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_treasure_view(run: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    step = int(run["depth"])
    riddle = _ts_riddle_at(run["id"], step)
    items = [
        v2_title(f"💎 Chasse au Trésor — Énigme {step + 1}/{_TS_STEPS}"),
        v2_subtitle(f"🎒 Gains sécurisés : {run['coins_pending']} 🪙  ·  une erreur = moitié perdue"),
        v2_divider(),
        v2_body(f"**🧩 {riddle['q']}**"),
    ]

    class _TsView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0xC49A2B))
            row = []
            for idx, opt in enumerate(riddle["opts"][:5]):
                b = discord.ui.Button(label=str(opt)[:78], style=discord.ButtonStyle.secondary,
                                      custom_id=f"tsolo_ans:{run['id']}:{idx}")
                b.callback = _on_ts_answer
                row.append(b)
            self.add_item(discord.ui.ActionRow(*row))

    return _TsView()


async def _on_ts_answer(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    try:
        opt_idx = int((i.data or {}).get("custom_id", "").split(":")[2])
    except Exception:
        opt_idx = -1
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        step = int(run["depth"])
        riddle = _ts_riddle_at(rid, step)
        correct = int(riddle.get("correct", 0))
        if opt_idx == correct:
            gain = _TS_COINS_PER_STEP * (step + 1)
            new_coins = int(run["coins_pending"]) + gain
            new_step = step + 1
            if new_step >= _TS_STEPS:
                bonus = _TS_COINS_PER_STEP * _TS_STEPS
                total = new_coins + bonus
                won = await _close_run(rid)
                if won and _add_coins is not None:
                    try:
                        await _add_coins(gid, uid, total)
                    except Exception:
                        pass
                egg_txt = await _maybe_grant_egg(gid, uid, _TS_STEPS) if won else ""
                return await _safe_edit(
                    i,
                    f"🏆 **Trésor découvert !** Les 3 énigmes résolues — coffre ouvert !\n"
                    f"Butin total : **+{total}** 🪙{egg_txt}\n_Ce salon se ferme. Reviens demain !_")
            async with _get_db() as db:
                await db.execute(
                    "UPDATE solo_runs SET depth=?, coins_pending=? WHERE id=? AND status='active'",
                    (new_step, new_coins, rid))
                await db.commit()
            run2 = await _get_run(rid)
            try:
                return await i.response.edit_message(view=_build_treasure_view(run2))
            except Exception:
                return
        else:
            # Mauvaise réponse → fin de la chasse, consolation = moitié des gains.
            kept = int(run["coins_pending"]) // 2
            good = riddle["opts"][correct] if 0 <= correct < len(riddle["opts"]) else "?"
            won = await _close_run(rid)
            if won and kept > 0 and _add_coins is not None:
                try:
                    await _add_coins(gid, uid, kept)
                except Exception:
                    pass
            return await _safe_edit(
                i,
                f"❌ **Mauvaise réponse !** La bonne était : **{good}**.\n"
                f"Tu repars avec la moitié de tes gains : **+{kept}** 🪙.\n_Ce salon se ferme._")
    except Exception as ex:
        print(f"[_on_ts_answer] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  DÉFI DU FAMILIER (ton familier combat — tu le déchaînes au bon moment)
# ═══════════════════════════════════════════════════════════════════════════════
def _pt_enemy_for(run_id: int):
    try:
        return random.Random(int(run_id) + 7).choice(_PT_ENEMIES)
    except Exception:
        return _PT_ENEMIES[0]


def _pt_pet_damage(pet: dict):
    """Salve du familier selon son perk : actif = grosse salve ; passif = salve douce
    + SOIGNE le run. Retourne (dmg, heal, is_active)."""
    lvl = int(pet.get("level", 1) or 1)
    try:
        bonus = float(pet.get("bonus_value", 0.0) or 0.0)
    except Exception:
        bonus = 0.0
    perk = str(pet.get("perk_type", "passive") or "passive")
    if perk == "active":
        dmg = int((30 + lvl * 8) * (1.0 + bonus * 2.0))
        heal = 0
    else:
        dmg = int((18 + lvl * 6) * (1.0 + bonus))
        heal = int(10 + lvl * 3)
    return max(6, min(dmg, 900)), heal, (perk == "active")


def _pet_label(pet: dict) -> str:
    return f"{pet.get('emoji', '🐾')} {pet.get('custom_name') or pet.get('name', 'Familier')}"


async def _on_start_pettrial_click(i: discord.Interaction):
    await start_pet_trial(i)


async def start_pet_trial(i: discord.Interaction):
    """Lance un Défi du Familier SOLO (salon prive, parallèle). Demande un familier actif."""
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if _active_pet_fn is None:
            return await _safe_followup(i, content="🐾 Système de familiers indisponible un instant.")
        pet = await _active_pet_fn(i.guild.id, i.user.id)
        if not pet:
            return await _safe_followup(
                i, content="🐾 Équipe d'abord un **familier** (menu `/pet`) — c'est LUI qui se bat ici !")
        if await _user_active_run(i.guild.id, i.user.id, _PETTRIAL_KIND):
            return await _safe_followup(
                i, content="🐾 Tu as déjà un défi en cours — termine-le d'abord.")
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _PETTRIAL_KIND, _COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochain défi dans `{cd}` min.")
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(
                i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "🐾-défi")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        lvl = int(pet.get("level", 1) or 1)
        enemy_hp = _PT_ENEMY_BASE_HP + lvl * 10  # le défi monte avec ton familier
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,?,?,?,?,0)",
                    (i.guild.id, i.user.id, _PETTRIAL_KIND, ch.id, _PT_PLAYER_HP, _PT_PLAYER_HP,
                     enemy_hp, enemy_hp))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo pettrial INSERT] {ex}")
            try:
                await ch.delete(reason="échec init défi")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")

        await _stamp_cooldown(i.guild.id, i.user.id, _PETTRIAL_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_pettrial_view(run, pet))
        except Exception as ex:
            print(f"[solo pettrial send] {ex}")
        await _safe_followup(i, content=f"🐾 {member.mention} ton défi t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_pet_trial] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_pettrial_view(run: dict, pet: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    enemy_em, enemy_name = _pt_enemy_for(run["id"])
    turn = int(run["depth"])
    perk = str((pet or {}).get("perk_type", "passive") or "passive")
    perk_txt = ("⚡ actif — grosse salve" if perk == "active"
                else "💚 passif — salve douce + te soigne")
    items = [
        v2_title(f"🐾 Défi du Familier — {_pet_label(pet)}"),
        v2_subtitle(f"Tour {turn + 1}/{_PT_MAX_TURNS} · ton familier : _{perk_txt}_"),
        v2_divider(),
        v2_body(f"**{enemy_em} {enemy_name}**\n"
                f"❤️ `{_bar(run['mob_hp'], run['mob_hp_max'])}` `{max(0, run['mob_hp'])}/{run['mob_hp_max']}`"),
        v2_body(f"**🛡️ Toi**\n"
                f"❤️ `{_bar(run['hp'], run['hp_max'])}` `{max(0, run['hp'])}/{run['hp_max']}`"),
        v2_divider(),
        v2_body("🐾 Abats l'adversaire avant que tes PV ne tombent."),
    ]

    class _PtView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0x2E8B57))
            b = discord.ui.Button(label="🐾 Déchaîner le familier",
                                  style=discord.ButtonStyle.success,
                                  custom_id=f"pttr:{run['id']}")
            b.callback = _on_pt_strike
            self.add_item(discord.ui.ActionRow(b))

    return _PtView()


async def _on_pt_strike(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        pet = await _active_pet_fn(gid, uid) if _active_pet_fn is not None else None
        if not pet:
            await _close_run(rid)
            return await _safe_edit(
                i, "🐾 Tu n'as plus de familier équipé — défi annulé. _Ce salon se ferme._")
        dmg, heal, _is_active = _pt_pet_damage(pet)
        new_enemy_hp = max(0, int(run["mob_hp"]) - dmg)
        if new_enemy_hp <= 0:
            won = await _close_run(rid)
            if won:
                if _add_coins is not None:
                    try:
                        await _add_coins(gid, uid, _PT_WIN_COINS)
                    except Exception:
                        pass
                if _give_pet_xp_fn is not None:
                    try:
                        await _give_pet_xp_fn(gid, uid, _PT_WIN_PET_XP)
                    except Exception:
                        pass
            return await _safe_edit(
                i,
                f"🏆 **{_pet_label(pet)}** triomphe ! Salve finale de `{dmg}` dégâts.\n"
                f"Récompense : **+{_PT_WIN_COINS}** 🪙 + XP pour ton familier.\n_Ce salon se ferme._")
        # L'adversaire riposte (le soin passif s'applique avant la riposte).
        enemy_atk = _PT_ENEMY_BASE_ATK + max(0, (int(run["mob_hp_max"]) - _PT_ENEMY_BASE_HP)) // 15
        new_hp = min(int(run["hp_max"]), int(run["hp"]) + heal) - enemy_atk
        turn = int(run["depth"]) + 1
        if new_hp <= 0 or turn >= _PT_MAX_TURNS:
            await _close_run(rid)
            reason = ("💀 Tes PV sont tombés" if new_hp <= 0
                      else "⏳ L'adversaire a tenu trop longtemps")
            return await _safe_edit(
                i,
                f"{reason} — **{_pet_label(pet)}** se replie cette fois.\n"
                f"_Entraîne ton familier (combats, événements) et reviens plus fort. Ce salon se ferme._")
        async with _get_db() as db:
            await db.execute(
                "UPDATE solo_runs SET mob_hp=?, hp=?, depth=? WHERE id=? AND status='active'",
                (new_enemy_hp, new_hp, turn, rid))
            await db.commit()
        run2 = await _get_run(rid)
        try:
            return await i.response.edit_message(view=_build_pettrial_view(run2, pet))
        except Exception:
            return
    except Exception as ex:
        print(f"[_on_pt_strike] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  SANCTUAIRE D'ÉPREUVES (survie à vagues — push-your-luck collectif solo)
# ═══════════════════════════════════════════════════════════════════════════════
def _sanctuary_mob_for_wave(wave: int):
    idx = min(wave, len(_SANC_MOBS) - 1)
    return {
        "name": _SANC_MOBS[idx],
        "hp": int(_SANC_MOB_BASE_HP * (1.0 + wave * 0.7)),
        "atk": int(_SANC_MOB_BASE_ATK * (1.0 + wave * 0.5)),
    }


async def _on_start_sanctuary_click(i: discord.Interaction):
    await start_sanctuary(i)


async def start_sanctuary(i: discord.Interaction):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if await _user_active_run(i.guild.id, i.user.id, _SANCTUARY_KIND):
            return await _safe_followup(i, content="🏛️ Tu as déjà une épreuve en cours — termine-la d'abord.")
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _SANCTUARY_KIND, _COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochaine épreuve dans `{cd}` min.")
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "🏛️-sanctuaire")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        mob = _sanctuary_mob_for_wave(0)
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,?,?,?,?,0)",
                    (i.guild.id, i.user.id, _SANCTUARY_KIND, ch.id, _SANC_PLAYER_HP, _SANC_PLAYER_HP,
                     mob["hp"], mob["hp"]))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo sanctuary INSERT] {ex}")
            try:
                await ch.delete(reason="échec init sanctuaire")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")
        await _stamp_cooldown(i.guild.id, i.user.id, _SANCTUARY_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_sanctuary_view(run))
        except Exception as ex:
            print(f"[solo sanctuary send] {ex}")
        await _safe_followup(i, content=f"🏛️ {member.mention} ton épreuve t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_sanctuary] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_sanctuary_view(run: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    wave = int(run["depth"])
    mob = _sanctuary_mob_for_wave(wave)
    items = [
        v2_title(f"🏛️ Sanctuaire d'Épreuves — Vague {wave + 1}/{_SANC_MAX_WAVES}"),
        v2_subtitle("Survis aux vagues ou sécurise ton butin avant de tomber."),
        v2_divider(),
        v2_body(f"**⚔️ {mob['name']}**\n"
                f"❤️ `{_bar(run['mob_hp'], run['mob_hp_max'])}` `{max(0, run['mob_hp'])}/{run['mob_hp_max']}`"),
        v2_body(f"**🛡️ Toi**\n"
                f"❤️ `{_bar(run['hp'], run['hp_max'])}` `{max(0, run['hp'])}/{run['hp_max']}`\n"
                f"🎒 Butin sécurisable : **{run['coins_pending']}** 🪙"),
        v2_divider(),
        v2_body("⚔️ Combattre (chaque victoire soigne + augmente le butin) · 🎒 Sécuriser pour repartir · tomber = moitié perdue."),
    ]

    class _SancView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0x8E44AD))
            fight = discord.ui.Button(label="⚔️ Combattre", style=discord.ButtonStyle.danger,
                                      custom_id=f"sanc_fight:{run['id']}")
            save = discord.ui.Button(label=f"🎒 Sécuriser ({run['coins_pending']} 🪙)",
                                     style=discord.ButtonStyle.success,
                                     custom_id=f"sanc_save:{run['id']}")
            fight.callback = _on_sanc_fight
            save.callback = _on_sanc_save
            self.add_item(discord.ui.ActionRow(fight, save))

    return _SancView()


async def _on_sanc_fight(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        atk, deff = await _player_atk_def(gid, uid)
        dmg = int(random.uniform(0.85, 1.15) * max(8, atk))
        mob = _sanctuary_mob_for_wave(int(run["depth"]))
        new_mob_hp = max(0, int(run["mob_hp"]) - dmg)
        if new_mob_hp > 0:
            retal = max(4, int(mob["atk"] * random.uniform(0.8, 1.1)) - deff // 2)
            new_hp = int(run["hp"]) - retal
            if new_hp <= 0:
                kept = int(run["coins_pending"]) // 2
                won = await _close_run(rid)
                if won and kept > 0 and _add_coins is not None:
                    try:
                        await _add_coins(gid, uid, kept)
                    except Exception:
                        pass
                return await _safe_edit(
                    i, f"💀 **Tu es tombé** à la vague {int(run['depth']) + 1}…\n"
                       f"Tu repars avec la moitié du butin : **+{kept}** 🪙.\n_Ce salon se ferme._")
            async with _get_db() as db:
                await db.execute("UPDATE solo_runs SET mob_hp=?, hp=? WHERE id=? AND status='active'",
                                 (new_mob_hp, new_hp, rid))
                await db.commit()
            run2 = await _get_run(rid)
            try:
                return await i.response.edit_message(view=_build_sanctuary_view(run2))
            except Exception:
                return
        # vague nettoyée (le mob meurt → pas de riposte ce tour)
        wave = int(run["depth"])
        gain = _SANC_COINS_PER_WAVE * (wave + 1)
        new_wave = wave + 1
        new_coins = int(run["coins_pending"]) + gain
        if new_wave >= _SANC_MAX_WAVES:
            total = new_coins + gain  # bonus de fin
            won = await _close_run(rid)
            if won and _add_coins is not None:
                try:
                    await _add_coins(gid, uid, total)
                except Exception:
                    pass
            egg_txt = await _maybe_grant_egg(gid, uid, new_wave) if won else ""
            return await _safe_edit(
                i, f"🏆 **Tu as conquis le Sanctuaire !** Toutes les vagues vaincues.\n"
                   f"Butin total : **+{total}** 🪙{egg_txt}\n_Honneur à toi. Ce salon se ferme._")
        healed = min(int(run["hp_max"]), int(run["hp"]) + int(int(run["hp_max"]) * _SANC_HEAL_FRAC))
        nmob = _sanctuary_mob_for_wave(new_wave)
        async with _get_db() as db:
            await db.execute(
                "UPDATE solo_runs SET depth=?, coins_pending=?, hp=?, mob_hp=?, mob_hp_max=? "
                "WHERE id=? AND status='active'",
                (new_wave, new_coins, healed, nmob["hp"], nmob["hp"], rid))
            await db.commit()
        run2 = await _get_run(rid)
        try:
            return await i.response.edit_message(view=_build_sanctuary_view(run2))
        except Exception:
            return
    except Exception as ex:
        print(f"[_on_sanc_fight] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


async def _on_sanc_save(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        total = int(run["coins_pending"])
        won = await _close_run(rid)
        if won and total > 0 and _add_coins is not None:
            try:
                await _add_coins(gid, uid, total)
            except Exception:
                pass
        egg_txt = await _maybe_grant_egg(gid, uid, int(run["depth"])) if (won and int(run["depth"]) >= 2) else ""
        await _safe_edit(
            i, f"🎒 **Butin sécurisé !** Tu quittes le Sanctuaire avec **+{total}** 🪙"
               f"{egg_txt}\n_Sage décision. Ce salon se ferme._")
    except Exception as ex:
        print(f"[_on_sanc_save] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  ARÈNE MIROIR (affronte un clone EXACT de tes stats — tu frappes en premier)
# ═══════════════════════════════════════════════════════════════════════════════
def _mirror_dmg(atk: int, deff: int) -> int:
    return max(4, int(random.uniform(0.85, 1.15) * max(8, atk)) - deff // 3)


async def _on_start_mirror_click(i: discord.Interaction):
    await start_mirror(i)


async def start_mirror(i: discord.Interaction):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if await _user_active_run(i.guild.id, i.user.id, _MIRROR_KIND):
            return await _safe_followup(i, content="🪞 Ton reflet t'attend déjà — termine ce duel d'abord.")
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _MIRROR_KIND, _MIRROR_COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochain duel miroir dans `{cd}` min.")
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        atk, deff = await _player_atk_def(i.guild.id, i.user.id)
        hp = _MIRROR_BASE_HP + deff * 2  # clone identique → même HP
        ch = await _create_solo_channel(i.guild, member, "🪞-arène-miroir")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,?,?,?,?,0)",
                    (i.guild.id, i.user.id, _MIRROR_KIND, ch.id, hp, hp, hp, hp))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo mirror INSERT] {ex}")
            try:
                await ch.delete(reason="échec init miroir")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")
        await _stamp_cooldown(i.guild.id, i.user.id, _MIRROR_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_mirror_view(run))
        except Exception as ex:
            print(f"[solo mirror send] {ex}")
        await _safe_followup(i, content=f"🪞 {member.mention} ton reflet t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_mirror] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_mirror_view(run: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    turn = int(run["depth"])
    items = [
        v2_title("🪞 Arène Miroir — ton reflet"),
        v2_subtitle(f"Échange {turn + 1}/{_MIRROR_MAX_TURNS} · stats identiques, mais tu frappes en premier."),
        v2_divider(),
        v2_body(f"**🪞 Ton Reflet**\n"
                f"❤️ `{_bar(run['mob_hp'], run['mob_hp_max'])}` `{max(0, run['mob_hp'])}/{run['mob_hp_max']}`"),
        v2_body(f"**🛡️ Toi**\n"
                f"❤️ `{_bar(run['hp'], run['hp_max'])}` `{max(0, run['hp'])}/{run['hp_max']}`"),
        v2_divider(),
        v2_body("⚔️ Frappe ton reflet. Il riposte avec tes armes — le premier à tomber perd."),
    ]

    class _MirrorView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0x34495E))
            b = discord.ui.Button(label="⚔️ Frapper", style=discord.ButtonStyle.danger,
                                  custom_id=f"mirror_strike:{run['id']}")
            b.callback = _on_mirror_strike
            self.add_item(discord.ui.ActionRow(b))

    return _MirrorView()


async def _on_mirror_strike(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        atk, deff = await _player_atk_def(gid, uid)  # le clone partage TES stats à jour
        # Toi → reflet (avantage : tu frappes en premier)
        new_clone_hp = max(0, int(run["mob_hp"]) - _mirror_dmg(atk, deff))
        if new_clone_hp <= 0:
            won = await _close_run(rid)
            if won and _add_coins is not None:
                try:
                    await _add_coins(gid, uid, _MIRROR_WIN_COINS)
                except Exception:
                    pass
            return await _safe_edit(
                i, f"🏆 **Tu as vaincu ton reflet !** Preuve de ta supériorité.\n"
                   f"Récompense : **+{_MIRROR_WIN_COINS}** 🪙\n_Honneur rare. Ce salon se ferme._")
        # Le reflet riposte avec les mêmes stats
        new_hp = int(run["hp"]) - _mirror_dmg(atk, deff)
        turn = int(run["depth"]) + 1
        if new_hp <= 0:
            await _close_run(rid)
            return await _safe_edit(
                i, "💀 **Ton reflet t'a vaincu.** Cette fois, il était toi en mieux…\n"
                   "_Reviens plus fort (meilleur équipement). Ce salon se ferme._")
        if turn >= _MIRROR_MAX_TURNS:
            await _close_run(rid)
            return await _safe_edit(
                i, "⏳ **Épuisement** : aucun des deux ne cède. Le duel s'achève sans vainqueur.\n"
                   "_Affûte ton équipement et reviens. Ce salon se ferme._")
        async with _get_db() as db:
            await db.execute("UPDATE solo_runs SET mob_hp=?, hp=?, depth=? WHERE id=? AND status='active'",
                             (new_clone_hp, new_hp, turn, rid))
            await db.commit()
        run2 = await _get_run(rid)
        try:
            return await i.response.edit_message(view=_build_mirror_view(run2))
        except Exception:
            return
    except Exception as ex:
        print(f"[_on_mirror_strike] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  ENQUÊTE PERSO (déduction : indices éliminent les innocents ; accuser tôt = gamble)
# ═══════════════════════════════════════════════════════════════════════════════
def _inv_setup(run_id: int):
    """Déterministe par run_id : (case, culprit_idx, innocents_order). Le culpable
    et l'ordre d'élimination des innocents NE sont JAMAIS dans le custom_id."""
    rng = random.Random(int(run_id) * 2654435761 & 0xFFFFFFFF)
    case = _INV_CASES[rng.randrange(len(_INV_CASES))]
    n = len(case["suspects"])
    culprit = rng.randrange(n)
    innocents = [j for j in range(n) if j != culprit]
    rng.shuffle(innocents)
    return case, culprit, innocents


async def _on_start_investigate_click(i: discord.Interaction):
    await start_investigate(i)


async def start_investigate(i: discord.Interaction):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if await _user_active_run(i.guild.id, i.user.id, _INVESTIGATE_KIND):
            return await _safe_followup(i, content="🔍 Tu as déjà une enquête en cours — résous-la d'abord.")
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _INVESTIGATE_KIND, _COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochaine enquête dans `{cd}` min.")
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "🔍-enquête")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,0,0,0,0,0)",
                    (i.guild.id, i.user.id, _INVESTIGATE_KIND, ch.id))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo investigate INSERT] {ex}")
            try:
                await ch.delete(reason="échec init enquête")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")
        await _stamp_cooldown(i.guild.id, i.user.id, _INVESTIGATE_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_investigate_view(run))
        except Exception as ex:
            print(f"[solo investigate send] {ex}")
        await _safe_followup(i, content=f"🔍 {member.mention} ton enquête t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_investigate] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_investigate_view(run: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    case, culprit, innocents = _inv_setup(run["id"])
    clues_found = int(run["depth"])
    max_clues = len(innocents)  # = n-1 ; après tout, seul le coupable reste
    eliminated = set(innocents[:clues_found])
    remaining = [j for j in range(len(case["suspects"])) if j not in eliminated]
    potential_bonus = (max_clues - clues_found) * _INV_RISK_BONUS

    susp_lines = []
    for j, (em, nm) in enumerate(case["suspects"]):
        if j in eliminated:
            susp_lines.append(f"~~{em} {nm}~~ ✅ disculpé")
        else:
            susp_lines.append(f"{em} **{nm}**")

    items = [
        v2_title("🔍 Enquête Perso"),
        v2_subtitle(f"Indices recueillis : {clues_found}/{max_clues}"),
        v2_divider(),
        v2_body(f"📜 _{case['scene']}_"),
        v2_body("**Suspects :**\n" + "\n".join(susp_lines)),
        v2_divider(),
        v2_body(f"🔎 **Cherche un indice** (disculpe un innocent) — sûr mais moins payant.\n"
                f"⚖️ **Accuse** un suspect maintenant : +**{potential_bonus}** 🪙 de prime de flair "
                f"(plus tu accuses tôt, plus c'est risqué… et payant)."),
    ]

    class _InvView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0x16A085))
            rows = []
            if clues_found < max_clues:
                clue_btn = discord.ui.Button(label="🔎 Chercher un indice",
                                             style=discord.ButtonStyle.primary,
                                             custom_id=f"inv_clue:{run['id']}")
                clue_btn.callback = _on_inv_clue
                rows.append(discord.ui.ActionRow(clue_btn))
            # Boutons d'accusation (uniquement les suspects encore en lice ; max 4)
            accuse_btns = []
            for j in remaining:
                em, nm = case["suspects"][j]
                b = discord.ui.Button(label=f"⚖️ {nm}", emoji=em,
                                      style=discord.ButtonStyle.danger,
                                      custom_id=f"inv_accuse:{run['id']}:{j}")
                b.callback = _on_inv_accuse
                accuse_btns.append(b)
            # <=5 boutons/row ; 4 suspects → 1 row suffit
            rows.append(discord.ui.ActionRow(*accuse_btns[:5]))
            for r in rows:
                self.add_item(r)

    return _InvView()


async def _on_inv_clue(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        case, culprit, innocents = _inv_setup(rid)
        clues_found = int(run["depth"])
        if clues_found >= len(innocents):
            run2 = await _get_run(rid)
            try:
                return await i.response.edit_message(view=_build_investigate_view(run2))
            except Exception:
                return
        new_depth = clues_found + 1
        async with _get_db() as db:
            await db.execute("UPDATE solo_runs SET depth=? WHERE id=? AND status='active'",
                             (new_depth, rid))
            await db.commit()
        run2 = await _get_run(rid)
        try:
            return await i.response.edit_message(view=_build_investigate_view(run2))
        except Exception:
            return
    except Exception as ex:
        print(f"[_on_inv_clue] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


async def _on_inv_accuse(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        # index accusé = 3e segment du custom_id
        try:
            accused = int((i.data or {}).get("custom_id", "").split(":")[2])
        except Exception:
            accused = -1
        gid, uid = run["guild_id"], run["user_id"]
        case, culprit, innocents = _inv_setup(rid)
        clues_found = int(run["depth"])
        max_clues = len(innocents)
        em, nm = case["suspects"][culprit] if 0 <= culprit < len(case["suspects"]) else ("❓", "?")
        if accused == culprit:
            bonus = (max_clues - clues_found) * _INV_RISK_BONUS
            total = _INV_WIN_COINS + max(0, bonus)
            won = await _close_run(rid)
            if won and _add_coins is not None:
                try:
                    await _add_coins(gid, uid, total)
                except Exception:
                    pass
            egg_txt = await _maybe_grant_egg(gid, uid, 3) if won else ""
            return await _safe_edit(
                i, f"🎉 **Élémentaire !** Le coupable était bien {em} **{nm}**.\n"
                   f"Récompense : **+{total}** 🪙{egg_txt}\n_Affaire classée. Ce salon se ferme._")
        await _close_run(rid)
        return await _safe_edit(
            i, f"❌ **Mauvaise déduction…** Le vrai coupable était {em} **{nm}**.\n"
               f"Tu repars bredouille. _Ce salon se ferme — la prochaine sera la bonne !_")
    except Exception as ex:
        print(f"[_on_inv_accuse] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  FORGE DU DÉFI (trempe push-your-luck — tu ne risques QUE tes gains non encaissés)
# ═══════════════════════════════════════════════════════════════════════════════
def _forge_rate(tier: int) -> float:
    return _FORGE_RATES[min(tier, len(_FORGE_RATES) - 1)]


def _forge_tier_name(tier: int) -> str:
    return _FORGE_TIERS[min(tier, len(_FORGE_TIERS) - 1)]


async def _on_start_forge_click(i: discord.Interaction):
    await start_forge(i)


async def start_forge(i: discord.Interaction):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if await _user_active_run(i.guild.id, i.user.id, _FORGE_KIND):
            return await _safe_followup(i, content="🔨 Tu as déjà une trempe en cours — termine-la d'abord.")
        cd = await _cooldown_remaining(i.guild.id, i.user.id, _FORGE_KIND, _FORGE_COOLDOWN_MIN)
        if cd > 0:
            return await _safe_followup(i, content=f"⏳ Prochaine forge dans `{cd}` min.")
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "🔨-forge")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,0,0,0,0,0)",
                    (i.guild.id, i.user.id, _FORGE_KIND, ch.id))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo forge INSERT] {ex}")
            try:
                await ch.delete(reason="échec init forge")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")
        await _stamp_cooldown(i.guild.id, i.user.id, _FORGE_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_forge_view(run))
        except Exception as ex:
            print(f"[solo forge send] {ex}")
        await _safe_followup(i, content=f"🔨 {member.mention} ta forge t'attend : {ch.mention}")
    except Exception as ex:
        print(f"[start_forge] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_forge_view(run: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    tier = int(run["depth"])
    pending = int(run["coins_pending"])
    rate = _forge_rate(tier)
    next_gain = _FORGE_GAIN * (tier + 1)
    items = [
        v2_title(f"🔨 Forge du Défi — {_forge_tier_name(tier)}"),
        v2_subtitle(f"Palier {tier + 1}/{_FORGE_MAX} · butin non encaissé : {pending} 🪙"),
        v2_divider(),
        v2_body(f"Tu chauffes le métal… **Tenter** = {int(rate * 100)}% de réussite "
                f"(+{next_gain} 🪙).\n"
                f"⚠️ Échec = le lingot se brise, tu perds le butin non encaissé "
                f"(jamais tes pièces réelles)."),
    ]

    class _ForgeView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0xCA6F1E))
            t = discord.ui.Button(label=f"🔨 Tenter ({int(rate * 100)}%)",
                                  style=discord.ButtonStyle.danger,
                                  custom_id=f"forge_temper:{run['id']}")
            c = discord.ui.Button(label=f"💰 Encaisser ({pending} 🪙)",
                                  style=discord.ButtonStyle.success,
                                  custom_id=f"forge_collect:{run['id']}")
            t.callback = _on_forge_temper
            c.callback = _on_forge_collect
            self.add_item(discord.ui.ActionRow(t, c))

    return _ForgeView()


async def _on_forge_temper(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        tier = int(run["depth"])
        if random.random() < _forge_rate(tier):
            gain = _FORGE_GAIN * (tier + 1)
            new_pending = int(run["coins_pending"]) + gain
            new_tier = tier + 1
            if new_tier >= _FORGE_MAX:
                total = new_pending + gain  # chef-d'œuvre : bonus de maîtrise
                won = await _close_run(rid)
                if won and _add_coins is not None:
                    try:
                        await _add_coins(gid, uid, total)
                    except Exception:
                        pass
                return await _safe_edit(
                    i, f"🏆 **Chef-d'œuvre !** Tu forges un **{_forge_tier_name(_FORGE_MAX - 1)}** parfait.\n"
                       f"Butin encaissé : **+{total}** 🪙\n_Ce salon se ferme._")
            async with _get_db() as db:
                await db.execute(
                    "UPDATE solo_runs SET depth=?, coins_pending=? WHERE id=? AND status='active'",
                    (new_tier, new_pending, rid))
                await db.commit()
            run2 = await _get_run(rid)
            try:
                return await i.response.edit_message(view=_build_forge_view(run2))
            except Exception:
                return
        # Échec → le lingot se brise, perte du butin NON encaissé (zéro pièce réelle perdue).
        lost = int(run["coins_pending"])
        await _close_run(rid)
        return await _safe_edit(
            i, f"💥 **Le lingot se brise !** Tu perds le butin non encaissé "
               f"(**{lost}** 🪙 envolés — mais zéro pièce de ta bourse).\n"
               f"_La forge est impitoyable. Ce salon se ferme._")
    except Exception as ex:
        print(f"[_on_forge_temper] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


async def _on_forge_collect(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        total = int(run["coins_pending"])
        won = await _close_run(rid)
        if won and total > 0 and _add_coins is not None:
            try:
                await _add_coins(gid, uid, total)
            except Exception:
                pass
        await _safe_edit(
            i, f"💰 **Trempe encaissée !** Tu repars avec **+{total}** 🪙 bien mérités.\n"
               f"_Sage forgeron. Ce salon se ferme._")
    except Exception as ex:
        print(f"[_on_forge_collect] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  INCUBATION ACTIVE (couver un œuf existant : l'activité remplace l'attente)
# ═══════════════════════════════════════════════════════════════════════════════
async def _on_start_incubation_click(i: discord.Interaction):
    await start_incubation(i)


async def start_incubation(i: discord.Interaction):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if _list_eggs_fn is None or _hatch_now_fn is None:
            return await _safe_followup(i, content="🥚 Système d'œufs indisponible un instant.")
        if await _user_active_run(i.guild.id, i.user.id, _INCUBATION_KIND):
            return await _safe_followup(i, content="🥚 Tu couves déjà un œuf — termine-le d'abord.")
        # Besoin d'au moins un œuf NON éclos. On couve celui le + proche d'éclore.
        try:
            eggs = await _list_eggs_fn(i.guild.id, i.user.id)
        except Exception:
            eggs = []
        if not eggs:
            return await _safe_followup(
                i, content="🥚 Tu n'as pas d'œuf à couver ! Gagne-en via les events/quêtes "
                           "(drops de combat, trésors…), puis reviens.")
        egg_id = int(eggs[0]["id"])
        if await _active_run_count(i.guild.id) >= _MAX_ACTIVE_RUNS:
            return await _safe_followup(i, content="🌑 Trop d'aventures en cours sur le serveur — réessaie dans un instant.")
        if not i.guild.me.guild_permissions.manage_channels:
            return await _safe_followup(i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")

        ch = await _create_solo_channel(i.guild, member, "🥚-incubation")
        if ch is None:
            return await _safe_followup(i, content="❌ Impossible de créer ton salon, réessaie.")
        try:
            async with _get_db() as db:
                # depth=clics faits ; hp_max=clics requis ; mob_hp=egg_id (réf. de l'œuf couvé).
                cur = await db.execute(
                    "INSERT INTO solo_runs(guild_id, user_id, kind, channel_id, status, "
                    "depth, hp, hp_max, mob_hp, mob_hp_max, coins_pending) "
                    "VALUES(?,?,?,?,'active',0,0,?,?,0,0)",
                    (i.guild.id, i.user.id, _INCUBATION_KIND, ch.id, _INCUB_CLICKS, egg_id))
                run_id = cur.lastrowid
                await db.commit()
        except Exception as ex:
            print(f"[solo incubation INSERT] {ex}")
            try:
                await ch.delete(reason="échec init incubation")
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")
        await _stamp_cooldown(i.guild.id, i.user.id, _INCUBATION_KIND)
        run = await _get_run(run_id)
        try:
            await ch.send(view=_build_incubation_view(run))
        except Exception as ex:
            print(f"[solo incubation send] {ex}")
        await _safe_followup(
            i, content=f"🥚 {member.mention} ton nid t'attend : {ch.mention} — "
                       f"_clique pour couver, le familier éclos rejoint ta collection._")
    except Exception as ex:
        print(f"[start_incubation] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _build_incubation_view(run: dict):
    LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container = _v2get()
    done = int(run["depth"])
    req = max(1, int(run["hp_max"]))
    items = [
        v2_title("🥚 Incubation Active"),
        v2_subtitle(f"Couvée : {min(done, req)}/{req}"),
        v2_divider(),
        v2_body(f"`{_bar(done, req)}`\n"
                f"Continue de **couver** : ton activité réchauffe l'œuf bien plus vite "
                f"que l'attente passive. Mystère sur ce qui éclora… 🐣"),
    ]

    class _IncubView(LayoutView):
        def __init__(self):
            super().__init__(timeout=_RUN_TTL_SEC)
            self.add_item(v2_container(*items, color=0xF1C40F))
            b = discord.ui.Button(label="🐣 Couver", style=discord.ButtonStyle.primary,
                                  custom_id=f"incub_warm:{run['id']}")
            b.callback = _on_incub_click
            self.add_item(discord.ui.ActionRow(b))

    return _IncubView()


async def _on_incub_click(i: discord.Interaction):
    rid = _parse_rid(i)
    if rid is None:
        return
    if _click_too_soon(i.user.id):
        try:
            await i.response.defer()
        except Exception:
            pass
        return
    run = await _get_run(rid)
    if not _owns_run(i, run):
        try:
            return await i.response.edit_message(view=None)
        except Exception:
            return
    try:
        gid, uid = run["guild_id"], run["user_id"]
        egg_id = int(run["mob_hp"])
        req = max(1, int(run["hp_max"]))
        new_done = int(run["depth"]) + 1
        if new_done >= req:
            won = await _close_run(rid)  # claim atomique → éclosion exactement une fois
            if not won:
                return
            res = {}
            try:
                res = await _hatch_now_fn(gid, uid, egg_id) or {}
            except Exception as ex:
                print(f"[incub hatch] {ex}")
            if res.get("error"):
                txt = f"🥚 L'œuf refuse d'éclore : {res['error']}\n_Ce salon se ferme._"
            elif res.get("duplicate"):
                txt = (f"🥚 **Éclosion !** Tu possèdes déjà ce familier → "
                       f"**+{res.get('coins', 0)}** 🪙 de compensation.\n_Ce salon se ferme._")
            elif res.get("ok") and res.get("pet"):
                p = res["pet"]
                act = " — **équipé automatiquement** !" if res.get("activated") else ""
                txt = (f"🎉 **Éclosion !** Tu obtiens **{p.get('emoji', '🐾')} "
                       f"{p.get('name', 'familier')}** ({res.get('rarity', '?')}){act}\n"
                       f"_Retrouve-le dans `/pet`. Ce salon se ferme._")
            else:
                txt = "🥚 **Éclosion terminée !** Vérifie ta collection `/pet`.\n_Ce salon se ferme._"
            return await _safe_edit(i, txt)
        async with _get_db() as db:
            await db.execute("UPDATE solo_runs SET depth=? WHERE id=? AND status='active'",
                             (new_done, rid))
            await db.commit()
        run2 = await _get_run(rid)
        try:
            return await i.response.edit_message(view=_build_incubation_view(run2))
        except Exception:
            return
    except Exception as ex:
        print(f"[_on_incub_click] {ex}")
        try:
            await i.response.defer()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Bouton d'ENTREE persistant (a placer dans un hub)
# ═══════════════════════════════════════════════════════════════════════════════
class SoloOpenButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"solo:open"):
    """Bouton persistant qui ouvre le hub des aventures solo (ephemere)."""
    def __init__(self):
        super().__init__(discord.ui.Button(
            label="🌑 Aventures Solo", style=discord.ButtonStyle.secondary,
            custom_id="solo:open"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        await open_solo_hub(i)


__all__ = [
    "setup", "init_db", "register_persistent_views", "boot_cleanup",
    "solo_watchdog", "open_solo_hub", "start_shadow_dungeon", "start_treasure_solo",
    "start_pet_trial", "start_sanctuary", "start_mirror", "start_investigate",
    "start_forge", "start_incubation", "SoloOpenButton",
]
