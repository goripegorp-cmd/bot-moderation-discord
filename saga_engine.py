"""
saga_engine.py — Arcs narratifs multi-jours (Phase 149).

🎯 OBJECTIF : éviter la lassitude des events one-shot. Au lieu de boss
solo de 30 min, créer des sagas de 5-7 jours où les joueurs vivent
une histoire ensemble.

Structure d'une saga hebdo (un MMO-like) :
- **Jour 1 (Lundi 18h)** : NPC mystérieux pose 3 énigmes. Le 1er à
  résoudre les 3 débloque "Phase 2" pour tout le serveur.
- **Jours 2-4** : Collecte communautaire de 50 fragments via micro-
  events (mini-boss, riddles flash, trésors planqués).
- **Jour 5 (Vendredi)** : Vote collectif via boutons "Allié" ou
  "Traître" — influence le boss final.
- **Jour 6 (Samedi)** : Boss final dont les stats changent selon le vote.
- **Jour 7 (Dimanche)** : Distribution loot exclusif top contributors.

Tout button-driven, aucune commande à mémoriser. Le panel saga est
épinglé dans le hub avec mise à jour live.

DB tables :
- sagas (saga_id PK, theme, started_at, ends_at, current_phase, status)
- saga_phases (saga_id, phase, title, description, threshold,
               completed)
- saga_participants (saga_id, user_id, contribution)
- saga_choices (saga_id, choice_key, votes_a, votes_b, voters_jsonb)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers,
        seasonal_module=None, add_coins_fn=None)
- start_saga(guild, theme) -> dict
- get_active_saga(guild_id) -> dict | None
- add_contribution(guild_id, user_id, amount)
- vote(guild_id, user_id, choice_key, choice_value)
- build_saga_panel(guild_id, owner_id) -> LayoutView
- saga_lifecycle_task (daily 18h FR)

⚠️ RULES.md : pas de relationnel/romantique dans les thèmes. Focus
gameplay + lore + mystère.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import View, Button

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_seasonal = None
_add_coins = None

# 8 thèmes de sagas (rotation hebdo)
SAGA_THEMES = [
    {
        "key": "lost_artifact",
        "title": "🗿 L'Artefact Perdu",
        "intro": (
            "Un artefact ancien a été aperçu dans les ruines. Trois "
            "énigmes gardent son emplacement. Qui le récupèrera ?"
        ),
        "color": 0xD4AC0D,
    },
    {
        "key": "shadow_invader",
        "title": "🌑 L'Envahisseur d'Ombre",
        "intro": (
            "Une entité d'ombre menace la forêt. Collectez les "
            "fragments lumineux pour la repousser."
        ),
        "color": 0x6C3483,
    },
    {
        "key": "great_storm",
        "title": "⛈️ La Grande Tempête",
        "intro": (
            "Une tempête magique approche. Les villageois ont besoin "
            "de votre aide pour fortifier le bastion."
        ),
        "color": 0x1F618D,
    },
    {
        "key": "dragon_awakening",
        "title": "🐉 L'Éveil du Dragon",
        "intro": (
            "Un ancien dragon stirre dans les profondeurs. Le serveur "
            "doit choisir : le combattre ou conclure un pacte ?"
        ),
        "color": 0xE74C3C,
    },
    {
        "key": "stolen_crown",
        "title": "👑 La Couronne Volée",
        "intro": (
            "La couronne royale a été volée. Suivez les indices, "
            "résolvez les énigmes, retrouvez le coupable."
        ),
        "color": 0xF1C40F,
    },
    {
        "key": "frozen_oracle",
        "title": "❄️ L'Oracle Gelé",
        "intro": (
            "Un oracle figé dans la glace murmure des secrets. Brisez "
            "le sortilège ensemble pour entendre sa prophétie."
        ),
        "color": 0x85C1E9,
    },
    {
        "key": "burning_forge",
        "title": "🔥 La Forge Ardente",
        "intro": (
            "La forge des dieux s'enflamme. Apportez des matériaux "
            "rares pour créer une arme légendaire commune."
        ),
        "color": 0xE67E22,
    },
    {
        "key": "void_rift",
        "title": "🌀 La Faille du Vide",
        "intro": (
            "Une faille s'est ouverte. Des créatures étranges en "
            "sortent. Combattez ou explorez ?"
        ),
        "color": 0x4A235A,
    },
]


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    seasonal_module=None, add_coins_fn=None,
):
    global _bot, _get_db, _db_get, _v2, _seasonal, _add_coins
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _seasonal = seasonal_module
    _add_coins = add_coins_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sagas (
                    saga_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    theme_key TEXT,
                    title TEXT,
                    intro TEXT,
                    color INTEGER,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ends_at TIMESTAMP,
                    current_phase INTEGER DEFAULT 1,
                    fragments_collected INTEGER DEFAULT 0,
                    fragments_target INTEGER DEFAULT 50,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS saga_participants (
                    saga_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    contribution INTEGER DEFAULT 0,
                    last_action_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (saga_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS saga_choices (
                    saga_id INTEGER NOT NULL,
                    choice_key TEXT NOT NULL,
                    votes_a INTEGER DEFAULT 0,
                    votes_b INTEGER DEFAULT 0,
                    voters_jsonb TEXT DEFAULT '{}',
                    PRIMARY KEY (saga_id, choice_key)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[saga_engine init_db] {ex}")


# ─── Lifecycle ──────────────────────────────────────────────────────────────

async def start_saga(guild: discord.Guild, theme_key: str = None) -> Optional[dict]:
    """Démarre une nouvelle saga (1×/semaine). Choisit un thème non utilisé
    récemment si pas spécifié."""
    if _get_db is None or guild is None:
        return None
    try:
        # Vérifie qu'il n'y a pas déjà une saga active
        async with _get_db() as db:
            async with db.execute(
                "SELECT saga_id FROM sagas "
                "WHERE guild_id=? AND status='active'",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return None  # déjà une saga en cours

        # Choisit un thème
        if theme_key:
            theme = next(
                (t for t in SAGA_THEMES if t["key"] == theme_key),
                random.choice(SAGA_THEMES),
            )
        else:
            # Random parmi les thèmes pas utilisés ces 4 dernières semaines
            async with _get_db() as db:
                async with db.execute(
                    "SELECT theme_key FROM sagas "
                    "WHERE guild_id=? AND started_at >= datetime('now', '-30 days')",
                    (guild.id,),
                ) as cur:
                    recent = {r[0] for r in await cur.fetchall()}
            available = [t for t in SAGA_THEMES if t["key"] not in recent]
            if not available:
                available = SAGA_THEMES
            theme = random.choice(available)

        ends = datetime.now(timezone.utc) + timedelta(days=7)
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO sagas "
                "(guild_id, theme_key, title, intro, color, ends_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    guild.id, theme["key"], theme["title"],
                    theme["intro"], theme["color"], ends.isoformat(),
                ),
            )
            saga_id = cur.lastrowid
            await db.commit()

        return {
            "saga_id": saga_id,
            "theme_key": theme["key"],
            "title": theme["title"],
            "intro": theme["intro"],
            "color": theme["color"],
        }
    except Exception as ex:
        print(f"[saga_engine start_saga] {ex}")
        return None


async def get_active_saga(guild_id: int) -> Optional[dict]:
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT saga_id, theme_key, title, intro, color, "
                "started_at, ends_at, current_phase, fragments_collected, "
                "fragments_target FROM sagas "
                "WHERE guild_id=? AND status='active' "
                "ORDER BY saga_id DESC LIMIT 1",
                (guild_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "saga_id": int(row[0]),
            "theme_key": row[1],
            "title": row[2],
            "intro": row[3],
            "color": int(row[4] or 0x5865F2),
            "started_at": row[5],
            "ends_at": row[6],
            "current_phase": int(row[7] or 1),
            "fragments_collected": int(row[8] or 0),
            "fragments_target": int(row[9] or 50),
        }
    except Exception as ex:
        print(f"[saga_engine get_active_saga] {ex}")
        return None


async def add_contribution(guild_id: int, user_id: int, amount: int = 1):
    """Ajoute une contribution à la saga active du guild."""
    saga = await get_active_saga(guild_id)
    if saga is None:
        return False
    try:
        async with _get_db() as db:
            # Add to participant
            await db.execute(
                "INSERT INTO saga_participants "
                "(saga_id, user_id, contribution) VALUES (?, ?, ?) "
                "ON CONFLICT(saga_id, user_id) DO UPDATE SET "
                "contribution = contribution + ?, "
                "last_action_at = CURRENT_TIMESTAMP",
                (saga["saga_id"], user_id, amount, amount),
            )
            # Add to global fragments
            await db.execute(
                "UPDATE sagas SET fragments_collected = "
                "fragments_collected + ? WHERE saga_id=?",
                (amount, saga["saga_id"]),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[saga_engine add_contribution] {ex}")
        return False


async def vote(
    guild_id: int, user_id: int, choice_key: str, value: str,
) -> bool:
    """Vote on a saga choice. value='a' ou 'b'."""
    saga = await get_active_saga(guild_id)
    if saga is None or value not in ("a", "b"):
        return False
    try:
        async with _get_db() as db:
            # Récupère les voters existants
            async with db.execute(
                "SELECT voters_jsonb FROM saga_choices "
                "WHERE saga_id=? AND choice_key=?",
                (saga["saga_id"], choice_key),
            ) as cur:
                row = await cur.fetchone()
            voters = json.loads(row[0]) if row and row[0] else {}
            if str(user_id) in voters:
                return False  # déjà voté
            voters[str(user_id)] = value

            if value == "a":
                await db.execute(
                    "INSERT INTO saga_choices "
                    "(saga_id, choice_key, votes_a, voters_jsonb) "
                    "VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(saga_id, choice_key) DO UPDATE SET "
                    "votes_a = votes_a + 1, voters_jsonb = ?",
                    (
                        saga["saga_id"], choice_key,
                        json.dumps(voters), json.dumps(voters),
                    ),
                )
            else:
                await db.execute(
                    "INSERT INTO saga_choices "
                    "(saga_id, choice_key, votes_b, voters_jsonb) "
                    "VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(saga_id, choice_key) DO UPDATE SET "
                    "votes_b = votes_b + 1, voters_jsonb = ?",
                    (
                        saga["saga_id"], choice_key,
                        json.dumps(voters), json.dumps(voters),
                    ),
                )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[saga_engine vote] {ex}")
        return False


async def end_saga(saga_id: int):
    """Finalise une saga + distribue le loot top contributors."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id FROM sagas WHERE saga_id=?",
                (saga_id,),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return
            guild_id = int(row[0])

            # Top 5 contributors
            async with db.execute(
                "SELECT user_id, contribution FROM saga_participants "
                "WHERE saga_id=? ORDER BY contribution DESC LIMIT 5",
                (saga_id,),
            ) as cur:
                top = await cur.fetchall()

            await db.execute(
                "UPDATE sagas SET status='finished' WHERE saga_id=?",
                (saga_id,),
            )
            await db.commit()

        # Reward top contributors
        rewards = [5000, 3000, 2000, 1000, 500]
        if _add_coins is not None:
            for i, (uid, _) in enumerate(top):
                try:
                    await _add_coins(guild_id, int(uid), rewards[i])
                except Exception:
                    pass

        # Phase 156 : Top 5 contributors saga → 2 tickets raffle chacun
        try:
            import roblox_raffle as raffle_mod
            for i, (uid, _) in enumerate(top):
                try:
                    await raffle_mod.add_tickets(
                        guild_id, int(uid), "saga_top5", 2,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        # Phase 163.3 : Top 5 contributors → 5 points réputation + DM digest
        try:
            import reputation as rep_mod
            import dm_digest as dm_mod
            for i, (uid, _) in enumerate(top):
                try:
                    rep_result = await rep_mod.add_points(
                        guild_id, int(uid), "saga_top_contributor",
                    )
                    # DM digest : saga_update si tier upgrade
                    if rep_result and rep_result.get("new_tier"):
                        nt = rep_result["new_tier"]
                        try:
                            await dm_mod.enqueue(
                                guild_id, int(uid), "level_up",
                                f"⭐ Tu as débloqué le tier **{nt['emoji']} "
                                f"{nt['name']}** ({rep_result['new_total']} pts)!",
                            )
                        except Exception:
                            pass
                    # DM digest : saga_update pour informer du top placement
                    try:
                        await dm_mod.enqueue(
                            guild_id, int(uid), "saga_update",
                            f"📜 Top #{i+1} contributeur saga ! "
                            f"+`{rewards[i]}` 🪙 + 2 tickets loterie + 5 pts rép.",
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

        return {"top_contributors": [{"user_id": int(t[0]), "contribution": int(t[1])} for t in top]}
    except Exception as ex:
        print(f"[saga_engine end_saga] {ex}")


# ─── Panel V2 ──────────────────────────────────────────────────────────────

def build_saga_panel(guild_id: int, owner_id: int = 0):
    """LayoutView V2 affichant l'état de la saga + boutons d'interaction."""
    if _v2 is None:
        return None

    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _SagaPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            # Construit le panel async dans un wrapper
            self.guild_id = guild_id
            self.owner_id = owner_id

        async def populate(self):
            saga = await get_active_saga(self.guild_id)
            items = []
            if not saga:
                items.append(v2_title("📜  AUCUNE SAGA ACTIVE"))
                items.append(v2_body(
                    "_Pas de saga en cours. La prochaine démarre lundi à 18h FR._"
                ))
                self.add_item(v2_container(*items, color=0x95A5A6))
                return

            items.append(v2_title(saga["title"]))
            items.append(v2_subtitle(
                f"_Saga #{saga['saga_id']} · Phase {saga['current_phase']}_"
            ))
            items.append(v2_divider())
            items.append(v2_body(saga["intro"]))

            # Progression fragments
            pct = min(100, int(
                saga["fragments_collected"] * 100 / max(1, saga["fragments_target"])
            ))
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            items.append(v2_divider())
            items.append(v2_body(
                f"**Fragments collectés :** "
                f"`{saga['fragments_collected']} / {saga['fragments_target']}`\n"
                f"`{bar}` {pct}%"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "_Participe via les events du serveur (boss, treasures, "
                "duels) — chaque victoire ajoute des fragments à la saga._"
            ))

            self.add_item(v2_container(*items, color=saga["color"]))

    return _SagaPanel()


# ─── Task ───────────────────────────────────────────────────────────────────

@tasks.loop(hours=24)
async def saga_lifecycle_task():
    """Lance/finalise les sagas. Hebdo : lundi 18h FR démarre, dimanche
    23h FR finalise."""
    try:
        if _bot is None:
            return
        # Pour chaque guild, vérifier les sagas
        for g in _bot.guilds:
            try:
                # Si on est lundi et qu'aucune saga active, démarre
                weekday = datetime.now(timezone.utc).weekday()  # 0=Mon
                saga = await get_active_saga(g.id)
                if weekday == 0 and saga is None:
                    new_saga = await start_saga(g)
                    if new_saga:
                        # Annoncer dans le salon hub si possible
                        for ch in g.text_channels:
                            try:
                                if "hub" in ch.name.lower() or \
                                   "events" in ch.name.lower():
                                    await ch.send(
                                        f"📜 **Nouvelle saga démarrée !**\n"
                                        f"{new_saga['title']}\n\n"
                                        f"_{new_saga['intro']}_"
                                    )
                                    break
                            except Exception:
                                pass
                # Si dimanche 23h+ et saga active >= 6 jours, finalise
                if saga and saga.get("started_at"):
                    # Phase 235.4 : normaliser en datetime *aware* (UTC). started_at
                    # stocké par SQLite (CURRENT_TIMESTAMP) vaut « 2026-05-25 18:00:00 »
                    # — SANS fuseau → datetime NAÏF → la soustraction avec
                    # datetime.now(timezone.utc) (aware) levait « can't subtract
                    # offset-naive and offset-aware datetimes ». Fix : forcer UTC.
                    started = None
                    raw = saga["started_at"]
                    try:
                        if isinstance(raw, datetime):
                            started = raw
                        elif isinstance(raw, str):
                            started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    except Exception:
                        started = None
                    if started is not None and started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    # Fallback : on finalise simplement si > 6 jours
                    if started and (datetime.now(timezone.utc) - started).days >= 6:
                        await end_saga(saga["saga_id"])
            except Exception as ex:
                print(f"[saga_lifecycle_task guild={g.id}] {ex}")
    except Exception as ex:
        print(f"[saga_lifecycle_task] {ex}")


@saga_lifecycle_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "start_saga",
    "get_active_saga",
    "add_contribution",
    "vote",
    "end_saga",
    "build_saga_panel",
    "saga_lifecycle_task",
    "SAGA_THEMES",
]
