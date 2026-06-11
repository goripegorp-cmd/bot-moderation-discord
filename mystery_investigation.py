"""
mystery_investigation.py — Indices fragmentés (Phase 170.6).

🎯 OBJECTIF : créer une mécanique de collaboration FORCÉE par la structure
même. Chaque mystère est divisé en 3-5 fragments d'indice. Aucun joueur
seul ne peut tout avoir. Pour révéler le mystère, le serveur ENTIER doit
collectivement détenir tous les fragments.

Le coeur du système : pour avancer, les joueurs DOIVENT parler en chat.
Personne ne sait quel fragment l'autre détient. Ils doivent demander,
échanger, recouper. Le bot ne facilite pas la conversation — il la
nécessite.

PHILOSOPHIE :
- Indices distribués aléatoirement (5% par encounter, 1% par mob kill)
- Chaque user voit SES indices dans le Codex
- Bouton "🔍 Partager publiquement" : poste son indice dans la Chronique
  → permet aux autres de voir ce qui manque
- Auto-révélation : dès que la guild collectivement détient tous les
  fragments d'un mystère, il se révèle automatiquement
- Tous les détenteurs reçoivent une récompense + progression Chronique

API publique :
- setup(bot, get_db, db_get, v2, story_module, npc_module)
- init_db()
- MYSTERY_CATALOG, get_mystery_def, list_mystery_ids
- try_grant_clue(guild_id, user_id, source) -> dict | None
- get_user_clues(guild_id, user_id) -> list
- get_guild_clue_coverage(guild_id, mystery_id) -> dict (qui détient quoi)
- try_reveal_mystery(guild_id, mystery_id) -> dict
- get_revelations(guild_id) -> list
- share_clue_publicly(interaction, mystery_id, clue_idx) -> None
- build_mysteries_panel(guild_id, user_id) -> LayoutView
- open_mysteries_from_codex(interaction) -> None
- ShareClueButton (DynamicItem persistent)
- mystery_task (loop hourly)
- register_persistent_views(bot)

DB :
- mystery_clues_held (guild_id, user_id, mystery_id, clue_idx, received_at,
                     source) PK (guild_id, user_id, mystery_id, clue_idx)
- mystery_revelations (id PK, guild_id, mystery_id, revealed_at,
                       contributors_json)
- mystery_shares (id PK, guild_id, user_id, mystery_id, clue_idx,
                  shared_at, channel_id)
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button
import ui_v2  # design-system V2 partagé (encadrés cohérents)

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_story = None
_npc = None

# Distribution rates
GRANT_CHANCE_ENCOUNTER = 0.05  # 5% par encounter NPC
GRANT_CHANCE_MOB_KILL = 0.01   # 1% par mob tué
GRANT_CHANCE_COUNCIL = 0.10    # 10% par vote au conseil
GRANT_CHANCE_PATROL = 0.08     # 8% par patrouille défendue (par session)

REVEAL_COIN_REWARD = 200       # par contributeur


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE MYSTÈRES
# ═══════════════════════════════════════════════════════════════════════════
# Structure :
# - id : identifiant court
# - title : titre du mystère
# - act_unlock : Acte minimum requis pour avoir ces fragments
# - fragments : liste de fragments (cryptiques individuellement, sens combinés)
# - revelation : texte final révélé quand tous les fragments sont combinés
# - linked_npc : NPC central du mystère
# - reward_coins : par contributeur

MYSTERY_CATALOG = [
    {
        "id": "secret_cendres",
        "title": "Le Secret des Cendres",
        "act_unlock": 1,
        "linked_npc": "lyra",
        "fragments": [
            "_Une phrase trouvée gravée dans une pierre :_ "
            "« La cendre… vient d'en bas… »",
            "_Une note tachée découverte près d'une rivière :_ "
            "« …mais elle ne tombe pas… »",
            "_Un parchemin déchiré de la Bibliothèque :_ "
            "« …elle MONTE vers le ciel. »",
        ],
        "revelation": (
            "🔮 **LE SECRET RÉVÉLÉ : *Le Secret des Cendres***\n\n"
            "_Les cendres ne tombent pas du ciel. Elles s'élèvent depuis les "
            "Profondes vers le firmament. Lyra l'Érudite avait raison : "
            "tout est inversé. Le monde respire par en bas._\n\n"
            "Cette découverte change la compréhension de la Chronique. "
            "L'entité enchaînée n'est pas ce qu'on croit."
        ),
        "reward_coins": REVEAL_COIN_REWARD,
    },
    {
        "id": "identite_voyageur",
        "title": "L'Identité du Voyageur",
        "act_unlock": 1,
        "linked_npc": "voyageur",
        "fragments": [
            "_Un fragment de carnet brûlé :_ "
            "« Le Voyageur sait ton nom… »",
            "_Une inscription dans la mousse :_ "
            "« …parce qu'il a déjà vécu ta vie… »",
            "_Une voix dans les rêves :_ "
            "« …dans une autre boucle du temps. »",
            "_Un dessin trouvé dans un grimoire :_ "
            "« Il reviendra quand le sceau tombera. »",
        ],
        "revelation": (
            "🔮 **LE SECRET RÉVÉLÉ : *L'Identité du Voyageur***\n\n"
            "_Le Voyageur n'est pas un étranger. Il EST le serveur, dans une "
            "boucle temporelle antérieure. Il a déjà vécu la Chronique. Il a "
            "déjà fait les choix. Il revient pour guider — ou empêcher — la "
            "même issue._\n\n"
            "Désormais, ses paroles cryptiques prennent un sens nouveau."
        ),
        "reward_coins": REVEAL_COIN_REWARD,
    },
    {
        "id": "sceau_ancien",
        "title": "Le Sceau Ancien",
        "act_unlock": 2,
        "linked_npc": "aria",
        "fragments": [
            "_Une plaque de bronze :_ "
            "« Le sceau se nourrit de mémoire. »",
            "_Un verset gravé dans la roche :_ "
            "« Chaque souvenir oublié l'affaiblit. »",
            "_Une page de journal d'Aria :_ "
            "« Le serveur a oublié quelque chose d'essentiel. »",
            "_Une vision dans une coupe d'eau :_ "
            "« Ce souvenir doit être retrouvé avant la fin. »",
            "_Un chuchotement dans les murs :_ "
            "« Il s'agit d'un nom. »",
        ],
        "revelation": (
            "🔮 **LE SECRET RÉVÉLÉ : *Le Sceau Ancien***\n\n"
            "_Le sceau qui retient l'entité ne tient pas grâce à une magie "
            "puissante — il tient grâce à la MÉMOIRE collective. Chaque "
            "souvenir partagé par le serveur le renforce. Chaque oubli "
            "l'affaiblit._\n\n"
            "_Le serveur a oublié un nom. Un nom qui, prononcé à voix haute, "
            "reforgerait le sceau pour mille ans. Reste à le retrouver._"
        ),
        "reward_coins": REVEAL_COIN_REWARD,
    },
    {
        "id": "verite_aria",
        "title": "La Vérité d'Aria",
        "act_unlock": 2,
        "linked_npc": "aria",
        "fragments": [
            "_Une rumeur ancienne :_ "
            "« Aria n'est pas humaine. »",
            "_Un récit d'un vieux moine :_ "
            "« Elle est née du premier souffle de cendre. »",
            "_Une chronique poussiéreuse :_ "
            "« Elle veille depuis 1000 ans. »",
            "_Un secret murmuré sous le couvert de la nuit :_ "
            "« Aria est le SCEAU lui-même, incarné. »",
        ],
        "revelation": (
            "🔮 **LE SECRET RÉVÉLÉ : *La Vérité d'Aria***\n\n"
            "_Aria la Veilleuse n'est pas une femme. Elle est l'incarnation "
            "humaine du Sceau Ancien, une présence qui veille depuis mille "
            "ans pour maintenir l'équilibre._\n\n"
            "_Si le Sceau tombe, Aria tombe avec lui. Si Aria meurt, le Sceau "
            "se brise. Le serveur la protège plus qu'il ne le sait._"
        ),
        "reward_coins": REVEAL_COIN_REWARD,
    },
    {
        "id": "destin_drazek",
        "title": "Le Destin de Drazek",
        "act_unlock": 3,
        "linked_npc": "drazek",
        "fragments": [
            "_Une prophétie déchirée :_ "
            "« Un guerrier tombera face au Boss Final. »",
            "_Une carte de tarot ancien :_ "
            "« Le Pic Rouge sera son tombeau. »",
            "_Une lettre cachetée :_ "
            "« Drazek le sait. Il s'y prépare. »",
        ],
        "revelation": (
            "🔮 **LE SECRET RÉVÉLÉ : *Le Destin de Drazek***\n\n"
            "_Drazek le Guerrier sait qu'il mourra lors de l'Affrontement "
            "Final. Il s'y est préparé toute sa vie. Sa colère, son "
            "impulsivité — c'est la sienne face à un destin écrit._\n\n"
            "_Le serveur peut-il changer ce destin ? Personne ne le sait._"
        ),
        "reward_coins": REVEAL_COIN_REWARD,
    },
]


def get_mystery_def(mystery_id: str) -> Optional[dict]:
    for m in MYSTERY_CATALOG:
        if m["id"] == mystery_id:
            return m
    return None


def list_mystery_ids() -> list[str]:
    return [m["id"] for m in MYSTERY_CATALOG]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    story_module=None, npc_module=None, add_coins_fn=None,
):
    global _bot, _get_db, _db_get, _v2, _story, _npc, _add_coins
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _story = story_module
    _npc = npc_module
    _add_coins = add_coins_fn


_add_coins = None  # module global


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mystery_clues_held (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    mystery_id TEXT NOT NULL,
                    clue_idx INTEGER NOT NULL,
                    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT DEFAULT 'unknown',
                    PRIMARY KEY (guild_id, user_id, mystery_id, clue_idx)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mystery_revelations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    mystery_id TEXT NOT NULL,
                    revealed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    contributors_json TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mystery_shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    mystery_id TEXT NOT NULL,
                    clue_idx INTEGER NOT NULL,
                    shared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    channel_id INTEGER DEFAULT 0
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_clue_lookup "
                "ON mystery_clues_held(guild_id, mystery_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_revelation_lookup "
                "ON mystery_revelations(guild_id, mystery_id)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[mystery_investigation init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Clue distribution
# ═══════════════════════════════════════════════════════════════════════════

async def _available_mysteries_for_act(guild_id: int) -> list[dict]:
    """Retourne les mystères disponibles selon l'Acte actuel ET non révélés."""
    if _story is None:
        # Sans story_engine, on permet tous les act_unlock <= 1
        current_act = 1
    else:
        try:
            state = await _story.get_state(guild_id)
            current_act = state["act"] if state else 1
        except Exception:
            current_act = 1
    revealed = await get_revelations(guild_id)
    revealed_ids = {r["mystery_id"] for r in revealed}
    return [
        m for m in MYSTERY_CATALOG
        if m["act_unlock"] <= current_act and m["id"] not in revealed_ids
    ]


async def try_grant_clue(
    guild_id: int, user_id: int, source: str = "encounter",
    force_chance: Optional[float] = None,
) -> Optional[dict]:
    """Essaye d'octroyer un fragment d'indice random au user.

    Retourne le fragment octroyé, ou None si rien (probabilité ratée ou
    pas de mystère dispo).
    """
    if _get_db is None:
        return None

    # Chance selon source
    if force_chance is not None:
        chance = force_chance
    elif source == "encounter":
        chance = GRANT_CHANCE_ENCOUNTER
    elif source == "mob_kill":
        chance = GRANT_CHANCE_MOB_KILL
    elif source == "council":
        chance = GRANT_CHANCE_COUNCIL
    elif source == "patrol":
        chance = GRANT_CHANCE_PATROL
    else:
        chance = 0.02  # fallback

    if random.random() > chance:
        return None

    available = await _available_mysteries_for_act(guild_id)
    if not available:
        return None

    # Choisit un mystère random
    mystery = random.choice(available)

    # Récupère les fragments déjà tenus par CE user pour ce mystère
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT clue_idx FROM mystery_clues_held "
                "WHERE guild_id=? AND user_id=? AND mystery_id=?",
                (guild_id, user_id, mystery["id"]),
            ) as cur:
                already_held = {int(r[0]) for r in await cur.fetchall()}
    except Exception:
        already_held = set()

    # Fragments non encore tenus par ce user
    total = len(mystery["fragments"])
    not_held = [i for i in range(total) if i not in already_held]
    if not not_held:
        return None

    clue_idx = random.choice(not_held)
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO mystery_clues_held "
                "(guild_id, user_id, mystery_id, clue_idx, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, mystery["id"], clue_idx, source),
            )
            await db.commit()
    except Exception as ex:
        print(f"[try_grant_clue INSERT] {ex}")
        return None

    return {
        "mystery_id": mystery["id"],
        "mystery_title": mystery["title"],
        "clue_idx": clue_idx,
        "clue_text": mystery["fragments"][clue_idx],
        "total_fragments": total,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Read clues
# ═══════════════════════════════════════════════════════════════════════════

async def get_user_clues(guild_id: int, user_id: int) -> list[dict]:
    """Liste les indices tenus par un user."""
    if _get_db is None:
        return []
    try:
        out = []
        async with _get_db() as db:
            async with db.execute(
                "SELECT mystery_id, clue_idx, source, received_at "
                "FROM mystery_clues_held "
                "WHERE guild_id=? AND user_id=? "
                "ORDER BY mystery_id, clue_idx",
                (guild_id, user_id),
            ) as cur:
                rows = await cur.fetchall()
        for row in rows:
            mystery = get_mystery_def(row[0])
            if not mystery:
                continue
            idx = int(row[1])
            try:
                text = mystery["fragments"][idx]
            except (IndexError, KeyError):
                text = "_(fragment manquant)_"
            out.append({
                "mystery_id": row[0],
                "mystery_title": mystery["title"],
                "clue_idx": idx,
                "total_fragments": len(mystery["fragments"]),
                "text": text,
                "source": row[2],
                "received_at": row[3],
            })
        return out
    except Exception as ex:
        print(f"[get_user_clues] {ex}")
        return []


async def get_guild_clue_coverage(
    guild_id: int, mystery_id: str,
) -> dict:
    """Retourne quels fragments sont détenus collectivement par la guild,
    et combien d'utilisateurs distincts détiennent au moins 1 fragment.

    Format : {fragments_held: set, total_fragments: int, contributors: set,
              all_held: bool}
    """
    if _get_db is None:
        return {"fragments_held": set(), "total_fragments": 0,
                "contributors": set(), "all_held": False}
    mystery = get_mystery_def(mystery_id)
    if not mystery:
        return {"fragments_held": set(), "total_fragments": 0,
                "contributors": set(), "all_held": False}
    try:
        fragments_held = set()
        contributors = set()
        async with _get_db() as db:
            async with db.execute(
                "SELECT clue_idx, user_id FROM mystery_clues_held "
                "WHERE guild_id=? AND mystery_id=?",
                (guild_id, mystery_id),
            ) as cur:
                for r in await cur.fetchall():
                    fragments_held.add(int(r[0]))
                    contributors.add(int(r[1]))
        total = len(mystery["fragments"])
        return {
            "fragments_held": fragments_held,
            "total_fragments": total,
            "contributors": contributors,
            "all_held": len(fragments_held) >= total,
        }
    except Exception:
        return {"fragments_held": set(), "total_fragments": 0,
                "contributors": set(), "all_held": False}


# ═══════════════════════════════════════════════════════════════════════════
#  Revelation
# ═══════════════════════════════════════════════════════════════════════════

async def get_revelations(guild_id: int) -> list[dict]:
    """Liste les mystères déjà révélés sur cette guild."""
    if _get_db is None:
        return []
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT mystery_id, revealed_at, contributors_json "
                "FROM mystery_revelations "
                "WHERE guild_id=? ORDER BY revealed_at DESC",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            try:
                contribs = json.loads(r[2] or "[]")
            except Exception:
                contribs = []
            out.append({
                "mystery_id": r[0],
                "revealed_at": r[1],
                "contributors": contribs,
            })
    except Exception:
        pass
    return out


async def try_reveal_mystery(
    guild_id: int, mystery_id: str,
) -> Optional[dict]:
    """Vérifie si la guild peut révéler ce mystère. Si oui, révèle, distribue
    les récompenses, log dans la Chronique."""
    if _get_db is None or _bot is None:
        return None
    mystery = get_mystery_def(mystery_id)
    if not mystery:
        return None

    # Vérifie pas déjà révélé
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM mystery_revelations "
                "WHERE guild_id=? AND mystery_id=? LIMIT 1",
                (guild_id, mystery_id),
            ) as cur:
                if await cur.fetchone():
                    return None
    except Exception:
        pass

    coverage = await get_guild_clue_coverage(guild_id, mystery_id)
    if not coverage["all_held"]:
        return None

    contributors = list(coverage["contributors"])

    # Crée la révélation
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO mystery_revelations "
                "(guild_id, mystery_id, contributors_json) "
                "VALUES (?, ?, ?)",
                (guild_id, mystery_id, json.dumps(contributors)),
            )
            await db.commit()
    except Exception as ex:
        print(f"[try_reveal_mystery INSERT] {ex}")
        return None

    # Distribue les coins
    reward = int(mystery.get("reward_coins", REVEAL_COIN_REWARD))
    if _add_coins is not None:
        for uid in contributors:
            try:
                await _add_coins(guild_id, uid, reward)
            except Exception:
                pass

    # Alimente Chronique (mystery_combines)
    if _story is not None:
        try:
            for _ in contributors:
                await _story.on_mystery_combine(guild_id)
            await _story.log_chronicle_event(
                guild_id, "mystery_combined",
                {
                    "mystery_id": mystery_id,
                    "title": mystery["title"],
                    "contributors_count": len(contributors),
                },
            )
        except Exception:
            pass

    # Bonus mood pour NPC lié
    if _npc is not None and mystery.get("linked_npc"):
        for uid in contributors:
            try:
                await _npc.change_mood(
                    guild_id, uid, mystery["linked_npc"], 10,
                )
            except Exception:
                pass

    # Announce
    guild = _bot.get_guild(guild_id)
    if guild:
        await _announce_revelation(guild, mystery, contributors)

    print(
        f"[mystery_investigation] revealed guild={guild_id} mystery={mystery_id} "
        f"contributors={len(contributors)}"
    )

    return {
        "mystery_id": mystery_id,
        "title": mystery["title"],
        "revelation": mystery["revelation"],
        "contributors": contributors,
        "reward_each": reward,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Sharing publicly
# ═══════════════════════════════════════════════════════════════════════════

async def share_clue_publicly(
    interaction: discord.Interaction, mystery_id: str, clue_idx: int,
) -> dict:
    """Le user partage UN de SES indices publiquement dans la Chronique.
    Cela permet aux autres joueurs de voir le texte du fragment.

    Returns: {success: bool, error: str | None}
    """
    if interaction.guild is None:
        return {"success": False, "error": "Serveur uniquement"}
    if _get_db is None or _bot is None:
        return {"success": False, "error": "Modules indisponibles"}

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    # Vérifie que le user détient bien cet indice
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM mystery_clues_held "
                "WHERE guild_id=? AND user_id=? AND mystery_id=? AND clue_idx=?",
                (guild_id, user_id, mystery_id, clue_idx),
            ) as cur:
                if not await cur.fetchone():
                    return {"success": False,
                            "error": "Tu ne détiens pas cet indice"}
    except Exception:
        return {"success": False, "error": "DB indisponible"}

    mystery = get_mystery_def(mystery_id)
    if not mystery:
        return {"success": False, "error": "Mystère inconnu"}
    try:
        text = mystery["fragments"][int(clue_idx)]
    except (IndexError, KeyError):
        return {"success": False, "error": "Fragment introuvable"}

    # Find chronicle channel
    ch = await _find_chronicle_channel(interaction.guild)
    if not ch:
        return {"success": False,
                "error": "Salon Chronique introuvable"}

    msg = (
        f"📜 **Un membre partage un indice**\n\n"
        f"_Mystère : **{mystery['title']}***  · fragment "
        f"{int(clue_idx) + 1}/{len(mystery['fragments'])}\n\n"
        f"{text}\n\n"
        f"_Qui possède un autre fragment ? Parlez-en en chat !_"
    )

    try:
        _t, _, _b = msg.partition("\n\n")
        await ch.send(
            view=ui_v2.recap_view(_t.replace("**", ""), _b or msg,
                                  color=ui_v2.Palette.ACCENT),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        return {"success": False, "error": "Envoi impossible"}

    # Log share
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO mystery_shares "
                "(guild_id, user_id, mystery_id, clue_idx, channel_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, mystery_id, int(clue_idx), ch.id),
            )
            await db.commit()
    except Exception:
        pass

    # Petit bonus de Chronique pour avoir partagé (alimente encounters
    # — sert d'incitation sans en abuser)
    if _story is not None:
        try:
            await _story.log_chronicle_event(
                guild_id, "clue_shared",
                {"mystery_id": mystery_id, "clue_idx": int(clue_idx)},
            )
        except Exception:
            pass

    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════
#  V2 panel
# ═══════════════════════════════════════════════════════════════════════════

async def build_mysteries_panel(
    guild_id: int, user_id: int,
) -> Optional[discord.ui.LayoutView]:
    """Panel des mystères : mes indices + état global + révélations."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    my_clues = await get_user_clues(guild_id, user_id)
    revelations = await get_revelations(guild_id)
    revealed_ids = {r["mystery_id"] for r in revelations}
    available = await _available_mysteries_for_act(guild_id)

    items = [v2_title("🔮 Mystères & indices")]
    items.append(v2_subtitle(
        f"_Mystères révélés {len(revelations)}/{len(MYSTERY_CATALOG)}_"
    ))
    items.append(v2_divider())

    # ─── Mes indices ───
    items.append(v2_body("**📜 Mes indices détenus**"))
    if not my_clues:
        items.append(v2_body(
            "_Tu n'as encore aucun indice. Les fragments tombent au hasard lors "
            "des rencontres NPC, du combat, du conseil, ou des patrouilles._"
        ))
    else:
        for c in my_clues:
            already_revealed = c["mystery_id"] in revealed_ids
            tag = " · _révélé_" if already_revealed else ""
            items.append(v2_body(
                f"**{c['mystery_title']}** · fragment "
                f"{c['clue_idx'] + 1}/{c['total_fragments']}{tag}\n"
                f"{c['text']}"
            ))

    items.append(v2_divider())

    # ─── État des mystères ouverts ───
    items.append(v2_body("**🌐 État du serveur**"))
    for mystery in available:
        coverage = await get_guild_clue_coverage(guild_id, mystery["id"])
        held = len(coverage["fragments_held"])
        total = coverage["total_fragments"]
        contribs = len(coverage["contributors"])
        bar_pct = int((held * 100) / max(1, total))
        icon = "🟦" if coverage["all_held"] else "🟨" if held > 0 else "⚪"
        items.append(v2_body(
            f"{icon} **{mystery['title']}**\n"
            f"Fragments collectifs : `{held}/{total}` ({bar_pct}%) · "
            f"`{contribs}` membre(s) détenteur(s)"
        ))

    if revelations:
        items.append(v2_divider())
        items.append(v2_body("**✨ Mystères déjà révélés**"))
        for r in revelations[:5]:
            mystery = get_mystery_def(r["mystery_id"])
            if mystery:
                items.append(v2_body(
                    f"🔮 **{mystery['title']}** · "
                    f"{len(r['contributors'])} contributeur(s)"
                ))

    items.append(v2_divider())
    items.append(v2_body(
        "-# Partage un indice pour inviter les autres à compléter le mystère."
    ))

    class _MysteriesLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0x4527A0))

    layout = _MysteriesLayout()

    # Phase 208 FIX : boutons "Partager" dans un ActionRow (max 5). Un Button/
    # DynamicItem brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body".
    # On crée des Button BRUTS avec le MÊME label/style/custom_id que
    # ShareClueButton (DynamicItem) ; le clic reste capté par le DynamicItem.
    share_buttons = []
    for c in my_clues[:5]:
        if c["mystery_id"] in revealed_ids:
            continue  # déjà révélé : pas la peine
        share_buttons.append(Button(
            label=f"📜 Partager fragment {c['clue_idx'] + 1}",
            style=discord.ButtonStyle.primary,
            custom_id=f"mystery_share:{c['mystery_id']}:{c['clue_idx']}:{user_id}",
        ))
    if share_buttons:
        layout.add_item(discord.ui.ActionRow(*share_buttons))

    return layout


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent button
# ═══════════════════════════════════════════════════════════════════════════

class ShareClueButton(
    discord.ui.DynamicItem[Button],
    template=r"mystery_share:(?P<mystery_id>[\w]+):(?P<clue_idx>\d+):(?P<user_id>\d+)",
):
    """Bouton pour partager UN indice dans la Chronique (persistent)."""

    def __init__(self, mystery_id: str, clue_idx: int, user_id: int):
        super().__init__(
            Button(
                label=f"📜 Partager fragment {clue_idx + 1}",
                style=discord.ButtonStyle.primary,
                custom_id=f"mystery_share:{mystery_id}:{clue_idx}:{user_id}",
            )
        )
        self.mystery_id = mystery_id
        self.clue_idx = clue_idx
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(
            match["mystery_id"], int(match["clue_idx"]), int(match["user_id"]),
        )

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre tes propres mystères depuis le Codex.",
                    ephemeral=True,
                )
            except Exception:
                return

        try:
            await btn_i.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
            pass

        if btn_i.guild is None:
            try:
                await btn_i.followup.send("❌ Serveur uniquement.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            result = await share_clue_publicly(
                btn_i, self.mystery_id, self.clue_idx,
            )
            if result.get("success"):
                await btn_i.followup.send(
                    "✅ Ton indice est publié dans la Chronique. "
                    "_Maintenant, parle avec les autres en chat pour "
                    "compléter le mystère._",
                    ephemeral=True,
                )
            else:
                await btn_i.followup.send(
                    f"❌ {result.get('error', 'Erreur inconnue')}",
                    ephemeral=True,
                )
        except Exception as ex:
            print(f"[mystery_share callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(ShareClueButton)
    except Exception as ex:
        print(f"[mystery_investigation register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Announcements
# ═══════════════════════════════════════════════════════════════════════════

async def _find_chronicle_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    if _db_get is None:
        return None
    try:
        cfg = await _db_get(guild.id)
        for key in ("chronicle_channel_id", "hub_channel"):
            ch_id = int(cfg.get(key, 0) or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch:
                    return ch
    except Exception:
        pass
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["chronique", "lore", "saga", "histoire"]):
            return ch
    return None


async def _announce_revelation(
    guild: discord.Guild, mystery: dict, contributors: list[int],
) -> None:
    ch = await _find_chronicle_channel(guild)
    if not ch:
        return
    contribs_names = []
    for uid in contributors[:10]:
        m = guild.get_member(int(uid))
        if m:
            contribs_names.append(m.display_name)
    if len(contributors) > 10:
        contribs_names.append(f"+{len(contributors) - 10} autres")

    msg = (
        f"{mystery['revelation']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**🏆 Contributeurs** ({len(contributors)}) :\n"
        f"{', '.join(contribs_names) if contribs_names else '_anonyme_'}\n\n"
        f"💰 `{mystery.get('reward_coins', REVEAL_COIN_REWARD)}` 🪙 distribués à "
        f"chacun.\n"
        f"📖 Gravé dans le Codex pour toujours."
    )
    try:
        _t, _, _b = msg.partition("\n\n")
        await ch.send(
            view=ui_v2.recap_view(_t.replace("**", ""), _b or msg,
                                  color=ui_v2.Palette.ACCENT),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=20)
async def mystery_task():
    """Toutes les 20 min : check si un mystère peut être révélé automatiquement."""
    if _bot is None or _get_db is None:
        return
    try:
        for guild in _bot.guilds:
            try:
                available = await _available_mysteries_for_act(guild.id)
                for mystery in available:
                    coverage = await get_guild_clue_coverage(guild.id, mystery["id"])
                    if coverage["all_held"]:
                        await try_reveal_mystery(guild.id, mystery["id"])
            except Exception as ex:
                print(f"[mystery_task g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[mystery_task] {ex}")


@mystery_task.before_loop
async def _mystery_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point depuis le Codex
# ═══════════════════════════════════════════════════════════════════════════

async def open_mysteries_from_codex(interaction: discord.Interaction) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_mysteries_from_codex defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        view = await build_mysteries_panel(interaction.guild.id, interaction.user.id)
        if view is None:
            await interaction.followup.send(
                "❌ Mystères indisponibles.", ephemeral=True
            )
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_mysteries_from_codex] {ex}")
        try:
            await interaction.followup.send(
                f"❌ Erreur : `{ex}`", ephemeral=True,
            )
        except Exception:
            pass


__all__ = [
    "MYSTERY_CATALOG",
    "GRANT_CHANCE_ENCOUNTER",
    "GRANT_CHANCE_MOB_KILL",
    "GRANT_CHANCE_COUNCIL",
    "GRANT_CHANCE_PATROL",
    "REVEAL_COIN_REWARD",
    "setup",
    "init_db",
    "get_mystery_def",
    "list_mystery_ids",
    "try_grant_clue",
    "get_user_clues",
    "get_guild_clue_coverage",
    "get_revelations",
    "try_reveal_mystery",
    "share_clue_publicly",
    "build_mysteries_panel",
    "open_mysteries_from_codex",
    "ShareClueButton",
    "mystery_task",
    "register_persistent_views",
]
