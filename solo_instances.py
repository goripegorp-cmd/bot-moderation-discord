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


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
          add_coins_fn=None, player_power_fn=None, grant_egg_fn=None):
    global _bot, _get_db, _db_get, _v2, _add_coins, _player_power_fn, _grant_egg_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _player_power_fn = player_power_fn
    _grant_egg_fn = grant_egg_fn


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


async def _close_run(run_id: int) -> bool:
    """Ferme un run de facon IDEMPOTENTE (claim atomique) + supprime le salon.
    Sans danger si appele plusieurs fois (watchdog + fin + boot).

    Retourne True UNIQUEMENT si CE call a remporte le claim (rowcount==1) → l'appelant
    ne paie la recompense QUE dans ce cas (exactly-once, anti double-pay sous double-clic
    / chemins concurrents). False si deja ferme par un autre chemin, ou erreur."""
    try:
        async with _get_db() as db:
            # Claim atomique : un seul appelant « gagne » la fermeture.
            cur = await db.execute(
                "UPDATE solo_runs SET status='ended' WHERE id=? AND status='active'",
                (run_id,))
            await db.commit()
            if getattr(cur, "rowcount", 0) != 1:
                return False  # deja ferme par un autre chemin → NE PAS re-payer
            async with db.execute(
                "SELECT guild_id, channel_id FROM solo_runs WHERE id=?", (run_id,)) as c:
                row = await c.fetchone()
        if row:
            gid, ch_id = int(row[0]), int(row[1] or 0)
            g = _bot.get_guild(gid) if _bot else None
            if g and ch_id:
                ch = g.get_channel(ch_id)
                if ch is not None:
                    try:
                        await ch.delete(reason="Aventure solo terminée")
                    except Exception:
                        pass
        return True
    except Exception as ex:
        print(f"[solo _close_run] {ex}")
        return False


async def boot_cleanup():
    """Au boot : ferme tous les runs solo 'active' (salons orphelins potentiels)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM solo_runs WHERE status='active'") as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
        for rid in ids:
            await _close_run(rid)
        if ids:
            print(f"[solo boot_cleanup] {len(ids)} run(s) solo orphelin(s) nettoye(s)")
    except Exception as ex:
        print(f"[solo boot_cleanup] {ex}")


@tasks.loop(minutes=5)
async def solo_watchdog():
    """Ferme tout run actif depuis > _RUN_TTL_SEC (abandon). 1 seul watchdog pour
    TOUS les types d'events solo."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM solo_runs WHERE status='active' AND "
                "datetime(started_at) < datetime('now', ?)",
                (f'-{_RUN_TTL_SEC} seconds',)) as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
        for rid in ids:
            await _close_run(rid)
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
    items = [
        v2_title("🌑  Aventures Solo"),
        v2_subtitle("Des défis RIEN QUE pour toi — ton propre salon, à ton rythme, "
                    "sans attendre personne. Plusieurs joueurs en parallèle."),
        v2_divider(),
        v2_body(
            "**🗝️ Donjon de l'Ombre**\n"
            "_Descente à étages : **descends** (+risque, +butin) ou **extrais** ton butin "
            "et repars sain. Tombe avant d'extraire = moitié perdue. Pousse ta chance !_"
            + (f"\n⏳ _dispo dans {cd_dg} min_" if cd_dg > 0 else "")
        ),
        v2_body(
            "**💎 Chasse au Trésor**\n"
            "_3 énigmes de plus en plus payantes. Bonne réponse = tu avances et empoches ; "
            "une erreur et tu repars avec la moitié de tes gains. Réfléchis bien !_"
            + (f"\n⏳ _dispo dans {cd_ts} min_" if cd_ts > 0 else "")
        ),
    ]

    class _SoloHub(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0x6C3483))
            b1 = discord.ui.Button(
                label=("⏳ Donjon" if cd_dg > 0 else "🗝️ Donjon de l'Ombre"),
                style=(discord.ButtonStyle.secondary if cd_dg > 0 else discord.ButtonStyle.success),
                custom_id="solo_start:shadow_dungeon", disabled=cd_dg > 0)
            b1.callback = _on_start_dungeon_click
            b2 = discord.ui.Button(
                label=("⏳ Trésor" if cd_ts > 0 else "💎 Chasse au Trésor"),
                style=(discord.ButtonStyle.secondary if cd_ts > 0 else discord.ButtonStyle.primary),
                custom_id="solo_start:treasure_solo", disabled=cd_ts > 0)
            b2.callback = _on_start_treasure_click
            self.add_item(discord.ui.ActionRow(b1, b2))

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
        v2_body("⚔️ **Attaque** pour vaincre le monstre · 🎒 **Extrais** pour repartir "
                "avec ton butin (sain et sauf) · plus tu descends, meilleur est le loot."),
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
        v2_body("_Choisis la bonne réponse ci-dessous._"),
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
    "SoloOpenButton",
]
