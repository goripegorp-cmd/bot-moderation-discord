"""
Phase 235.19 — 🧭 LE PARCOURS DE L'AVENTURIER
═══════════════════════════════════════════════════════════════════════════════
Quête d'intégration SOLO, séquentielle et gatée par NIVEAU (crescendo) : 8 paliers
qui font découvrir TOUS les piliers du serveur dans l'ordre. Chaque palier débloque
le suivant et exige un niveau minimum → le nouveau « farme un peu » entre deux étapes
au lieu de tout enchaîner d'un coup.

DESIGN (volontairement découplé + robuste) :
  • Per-player, PERSISTANT (table hero_journey, survit au reboot).
  • Évaluation À LA DEMANDE : à l'ouverture du panneau (bouton hub) on (re)vérifie
    l'étape courante et on avance à travers TOUTES les étapes déjà satisfaites d'un
    coup (idéal pour un joueur existant qui a déjà tout fait).
  • + tâche périodique (auto-progression silencieuse) qui avance les joueurs en cours
    et NOTIFIE en DM les paliers franchis — SANS hook éparpillé dans les autres
    systèmes (zéro couplage aux handlers d'events).
  • Conditions vérifiées via UN seul callback `check_fn(kind, guild_id, user_id)`
    injecté par bot.py (qui connaît les schémas) → le module reste générique.
  • Fail-open partout : une erreur ne bloque jamais le joueur ni le bot.
"""
import asyncio
import discord
from discord.ui import Button
from discord.ext import tasks
from typing import Optional

# ─── Dépendances injectées par bot.py (setup) ───
_bot = None
_get_db = None
_v2 = None
_add_coins = None        # async (guild_id, user_id, n)
_get_level = None        # async (guild_id, user_id) -> int
_grant_item = None       # async (guild_id, user_id, item_dict) -> bool  (rangé au coffre)
_check_fn = None         # async (kind, guild_id, user_id) -> bool
_notify_check = None     # async (guild_id, user_id, category) -> bool | None  (opt-out DM)

# ═══════════════════════════════════════════════════════════════════════════════
#  CATALOGUE — 8 paliers crescendo (niveau croissant)
# ═══════════════════════════════════════════════════════════════════════════════
# Chaque palier : key (titre court), level (niveau requis), check (clé de condition
# vérifiée par check_fn ; 'none' = aucune condition au-delà du niveau), desc, hint,
# coins, item (optionnel → coffre), badge (optionnel, sur le dernier).
STEPS = [
    {"key": "🗨️ Premiers pas", "level": 1, "check": "none",
     "desc": "Bienvenue, aventurier ! Ouvre ton Parcours — ta légende commence ici.",
     "hint": "Discuter sur le serveur rapporte de l'XP et des 🪙.",
     "coins": 100},
    {"key": "📈 Monte en puissance", "level": 2, "check": "none",
     "desc": "Atteins le **niveau 2** en étant actif (messages, jeux, quêtes).",
     "hint": "Reste actif : 💬 messages **OU** 🔊 vocal débloquent l'accès aux events (l'un OU l'autre suffit).",
     "coins": 150},
    {"key": "📅 La routine du héros", "level": 2, "check": "daily",
     "desc": "Complète **1 quête quotidienne** (`/daily` ou le bouton du hub).",
     "hint": "Reviens chaque jour : la série (streak) booste les gains.",
     "coins": 200},
    {"key": "⚔️ Premier sang", "level": 3, "check": "mob",
     "desc": "Participe à **1 chasse au mob** (clique ⚔️ Attaquer dans le salon de combat).",
     "hint": "Les mobs apparaissent régulièrement — ouverts à tous.",
     "coins": 250,
     "item": {"name": "Épée d'apprenti", "rarity": "commune", "emoji": "🗡️",
              "atk": 6, "def": 0, "crit": 0, "slot": "weapon"}},
    {"key": "🛠️ L'armurier", "level": 5, "check": "equip",
     "desc": "**Équipe une pièce** d'équipement (`/inventory` → Équiper). Forge-la pour la booster (`/craft`).",
     "hint": "Ton stuff compte en combat : ATK, éléments, set bonus.",
     "coins": 300},
    {"key": "🐲 Le boss du jour", "level": 5, "check": "daily_boss",
     "desc": "Participe à **1 Boss du jour** dans le salon ⚔️-combat (accessible en étant **actif** — pas besoin de niveau).",
     "hint": "4 boss/jour, difficulté croissante. Frappez ensemble !",
     "coins": 400},
    {"key": "🤝 La meute", "level": 8, "check": "alliance",
     "desc": "Rejoins ou crée une **alliance** (hub → Alliance).",
     "hint": "Être dans le même vocal qu'un allié = bonus de dégâts.",
     "coins": 400},
    {"key": "🌍 Le grand frisson", "level": 10, "check": "world_boss",
     "desc": "Participe à **1 World Boss** — le plus gros défi collectif du serveur.",
     "hint": "Le butin le plus rare t'attend. Coordonnez-vous !",
     "coins": 600,
     "item": {"name": "Lame du Vétéran", "rarity": "rare", "emoji": "⚔️",
              "atk": 13, "def": 0, "crit": 0, "slot": "weapon"},
     "badge": "🧭 Aventurier accompli"},
]

FINAL_BADGE = "🧭 Aventurier accompli"


def setup(bot_instance, get_db_fn, v2_helpers: dict, *, add_coins_fn, get_level_fn,
          grant_item_fn, check_fn, notify_check_fn=None):
    global _bot, _get_db, _v2, _add_coins, _get_level, _grant_item, _check_fn, _notify_check
    _bot = bot_instance
    _get_db = get_db_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _get_level = get_level_fn
    _grant_item = grant_item_fn
    _check_fn = check_fn
    _notify_check = notify_check_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS hero_journey (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    step INTEGER DEFAULT 0,
                    done INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[hero_journey init_db] {ex}")


async def _load(guild_id: int, user_id: int) -> tuple[int, int]:
    """Retourne (step, done). Crée la ligne au 1er accès."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT step, done FROM hero_journey WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)) as cur:
                row = await cur.fetchone()
            if row is None:
                await db.execute(
                    "INSERT OR IGNORE INTO hero_journey(guild_id, user_id) VALUES(?,?)",
                    (guild_id, user_id))
                await db.commit()
                return 0, 0
            return int(row[0] or 0), int(row[1] or 0)
    except Exception as ex:
        print(f"[hero_journey _load] {ex}")
        return 0, 0


async def _save(guild_id: int, user_id: int, step: int, done: int):
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO hero_journey(guild_id, user_id, step, done, updated_at) "
                "VALUES(?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "step=excluded.step, done=excluded.done, updated_at=CURRENT_TIMESTAMP",
                (guild_id, user_id, int(step), int(done)))
            await db.commit()
    except Exception as ex:
        print(f"[hero_journey _save] {ex}")


async def _grant(guild_id: int, user_id: int, step: dict):
    """Distribue les récompenses d'un palier. Fail-open (jamais bloquant)."""
    try:
        if step.get("coins") and _add_coins:
            await _add_coins(guild_id, user_id, int(step["coins"]))
    except Exception as ex:
        print(f"[hero_journey grant coins] {ex}")
    try:
        if step.get("item") and _grant_item:
            await _grant_item(guild_id, user_id, dict(step["item"]))
    except Exception as ex:
        print(f"[hero_journey grant item] {ex}")


async def evaluate(guild_id: int, user_id: int) -> list[dict]:
    """(Re)vérifie l'étape courante et avance à travers TOUTES celles déjà satisfaites.
    Retourne la liste des paliers NOUVELLEMENT complétés (pour notifier). Fail-open."""
    if _get_db is None or _check_fn is None:
        return []
    step, done = await _load(guild_id, user_id)
    if done:
        return []
    try:
        lvl = int(await _get_level(guild_id, user_id)) if _get_level else 1
    except Exception:
        lvl = 1
    completed: list[dict] = []
    guard = 0
    while step < len(STEPS) and guard < len(STEPS) + 1:
        guard += 1
        s = STEPS[step]
        if lvl < int(s.get("level", 1)):
            break  # palier verrouillé par le niveau → on s'arrête là
        try:
            ok = await _check_fn(s.get("check", "none"), guild_id, user_id)
        except Exception:
            ok = False
        if not ok:
            break
        await _grant(guild_id, user_id, s)
        completed.append(s)
        step += 1
    done = 1 if step >= len(STEPS) else 0
    if completed or done:
        await _save(guild_id, user_id, step, done)
    return completed


# ═══════════════════════════════════════════════════════════════════════════════
#  Panneau V2
# ═══════════════════════════════════════════════════════════════════════════════
def _progress_bar(done_count: int, total: int) -> str:
    filled = "▰" * done_count
    empty = "▱" * max(0, total - done_count)
    return filled + empty


async def _build_panel(guild_id: int, user_id: int):
    """Construit le panneau V2 du Parcours (étape courante + progression)."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    step, done = await _load(guild_id, user_id)
    try:
        lvl = int(await _get_level(guild_id, user_id)) if _get_level else 1
    except Exception:
        lvl = 1
    total = len(STEPS)

    items = [
        v2_title("🧭  LE PARCOURS DE L'AVENTURIER"),
        v2_subtitle(f"Progression : **{min(step, total)} / {total}**  "
                    f"`{_progress_bar(min(step, total), total)}`"),
        v2_divider(),
    ]

    if done:
        items.append(v2_body(
            f"🎉 **Parcours TERMINÉ !** Tu as débloqué le titre **{FINAL_BADGE}**.\n"
            f"_Tu maîtrises désormais tous les piliers du serveur. À toi de jouer, "
            f"héros — grimpe les classements et défie les World Boss !_"))
        class _DonePanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(v2_container(*items, color=0xF1C40F))
        return _DonePanel()

    s = STEPS[step]
    locked = lvl < int(s.get("level", 1))
    # Étape courante (mise en avant)
    status = (f"🔒 **Niveau {s['level']} requis** — tu es niveau **{lvl}**. "
              f"Farme un peu (mobs, `/daily`) et reviens !"
              if locked else "🟢 **En cours** — fais l'action puis reviens vérifier !")
    items.append(v2_body(
        f"### {s['key']}\n{s['desc']}\n\n{status}\n"
        f"-# 💡 {s.get('hint', '')}\n"
        f"🎁 Récompense : `{s.get('coins', 0)}` 🪙"
        + (f" + {s['item'].get('emoji','')} **{s['item'].get('name','')}** "
           f"({s['item'].get('rarity','')})" if s.get("item") else "")
    ))
    items.append(v2_divider())
    # Aperçu des paliers (✅ faits / ➡️ courant / 🔒 à venir)
    lines = []
    for i, st in enumerate(STEPS):
        if i < step:
            mark = "✅"
        elif i == step:
            mark = "➡️"
        else:
            mark = "🔒"
        lines.append(f"{mark} {st['key']} _(niv {st['level']})_")
    items.append(v2_body("\n".join(lines)))

    items.append(discord.ui.ActionRow(Button(
        label="🔄 Vérifier ma progression", style=discord.ButtonStyle.success,
        custom_id="hero_journey:open")))

    class _Panel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=0x3498DB))
    return _Panel()


async def open_panel(interaction: discord.Interaction):
    """Ouvre (et auto-évalue) le Parcours en éphémère. Branché sur /parcours + hub."""
    if interaction.guild is None:
        try:
            await interaction.response.send_message(
                "Le Parcours se joue sur le serveur, pas en MP.", ephemeral=True)
        except Exception:
            pass
        return
    g, u = interaction.guild.id, interaction.user.id
    # Évalue d'abord (peut compléter plusieurs paliers d'un coup), puis affiche.
    completed = []
    try:
        completed = await evaluate(g, u)
    except Exception:
        completed = []
    panel = await _build_panel(g, u)
    note = ""
    if completed:
        gained = sum(int(s.get("coins", 0)) for s in completed)
        note = (f"✅ **{len(completed)} palier(s) validé(s)** (+`{gained}` 🪙) !\n"
                if gained else f"✅ **{len(completed)} palier(s) validé(s)** !\n")
    try:
        if panel is not None:
            await interaction.response.send_message(content=(note or None), view=panel, ephemeral=True)
        else:
            await interaction.response.send_message(
                content=(note or "🧭 Parcours indisponible pour le moment."), ephemeral=True)
    except (discord.InteractionResponded, discord.HTTPException):
        try:
            if panel is not None:
                await interaction.followup.send(content=(note or None), view=panel, ephemeral=True)
        except Exception:
            pass
    except Exception as ex:
        print(f"[hero_journey open_panel] {ex}")


class HeroJourneyButton(discord.ui.DynamicItem[Button], template=r"hero_journey:open"):
    """Bouton persistant « 🧭 Mon Parcours » (hub / onboarding)."""
    def __init__(self):
        super().__init__(Button(
            label="🧭 Mon Parcours", style=discord.ButtonStyle.primary,
            custom_id="hero_journey:open"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await open_panel(interaction)


class _JourneyEntryView(discord.ui.View):
    """Mini-view (DM nudge) : un bouton « 🧭 Voir mon Parcours ». Le clic est capté
    par le DynamicItem HeroJourneyButton enregistré (match du custom_id)."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(
            label="🧭 Voir mon Parcours", style=discord.ButtonStyle.primary,
            custom_id="hero_journey:open"))


def register_persistent_views(bot):
    try:
        bot.add_dynamic_items(HeroJourneyButton)
    except Exception as ex:
        print(f"[hero_journey register views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Tâche périodique : auto-progression + nudge DM (zéro hook éparpillé)
# ═══════════════════════════════════════════════════════════════════════════════
@tasks.loop(minutes=20)
async def hero_journey_task():
    """Avance les joueurs en cours et les NOTIFIE en DM des paliers franchis.
    Cap de sécurité par tick. Respecte l'opt-out DM (notify_check). Fail-open."""
    if _bot is None or _get_db is None:
        return
    try:
        rows = []
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, user_id FROM hero_journey WHERE done=0 "
                "ORDER BY updated_at ASC LIMIT 120") as cur:
                rows = await cur.fetchall()
        for gid, uid in rows:
            try:
                completed = await evaluate(int(gid), int(uid))
                if not completed:
                    continue
                # Nudge DM (opt-out respecté) : on annonce le dernier palier franchi
                # + le prochain objectif, pour ramener le joueur.
                guild = _bot.get_guild(int(gid))
                member = guild.get_member(int(uid)) if guild else None
                if member is None:
                    continue
                if _notify_check is not None:
                    try:
                        allowed = await _notify_check(int(gid), int(uid), "journey")
                        if allowed is False:
                            continue
                    except Exception:
                        pass
                last = completed[-1]
                step_now, done_now = await _load(int(gid), int(uid))
                gained = sum(int(s.get("coins", 0)) for s in completed)
                if done_now:
                    msg = (f"🎉 **{guild.name}** — tu as TERMINÉ le 🧭 Parcours de "
                           f"l'Aventurier ! Titre débloqué : **{FINAL_BADGE}** (+`{gained}` 🪙).")
                else:
                    nxt = STEPS[step_now] if step_now < len(STEPS) else None
                    nxt_txt = (f"\n➡️ Prochain : **{nxt['key']}** _(niv {nxt['level']})_ — {nxt['desc']}"
                               if nxt else "")
                    msg = (f"🧭 **{guild.name}** — palier validé : **{last['key']}** "
                           f"(+`{gained}` 🪙) !{nxt_txt}")
                try:
                    pass  # Phase 257 : notification MP DÉSACTIVÉE (zéro MP membre)
                except Exception:
                    pass  # DM fermés → tant pis, le bouton onboarding reste dispo
            except Exception:
                continue
    except Exception as ex:
        print(f"[hero_journey_task] {ex}")


__all__ = [
    "setup", "init_db", "evaluate", "open_panel", "HeroJourneyButton",
    "register_persistent_views", "hero_journey_task", "STEPS",
]
