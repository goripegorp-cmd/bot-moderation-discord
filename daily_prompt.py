"""
daily_prompt.py — Question fun du jour avec votes (Phase 153 — F2).

🎯 OBJECTIF : faire participer la communauté en posant 1 question fun
par jour. Les votants gagnent des coins. Crée un mood passif sympa.

Mécanique :
- 1×/jour à 18h FR
- Question random parmi un catalogue (sans romance — RULES.md)
- Panel V2 avec 2-4 boutons-réponses
- Voting 24h
- Le lendemain : reset + reveal des votes + récompense
  • Tous les votants : +50 coins
  • Vote majoritaire : +200 coins bonus
- Track par jour pour éviter doublons sur 30 jours

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- daily_prompt_task (loop 15min check)
- post_now(guild) -> bool (manual)
- close_yesterday(guild) -> dict (results)

DB tables :
- daily_prompts (id PK, guild_id, day TEXT, question, options_jsonb,
                 votes_jsonb, posted_at, closed_at, status)
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None

# Catalogue de questions (FR, RULES.md = no romance/relationnel)
QUESTIONS = [
    {"q": "🍕 C'est quoi ton snack favori en session gaming ?",
     "opts": ["🍕 Pizza", "🍫 Chocolat", "🍿 Popcorn", "🥨 Salé"]},
    {"q": "🎮 Tu préfères jouer à quelle heure ?",
     "opts": ["🌅 Matin", "☀️ Après-midi", "🌆 Soir", "🌙 Nuit"]},
    {"q": "🎵 Quelle ambiance musicale tu mets en jouant ?",
     "opts": ["🎸 Rock", "🎧 Lo-fi", "🥁 EDM", "🤫 Silence"]},
    {"q": "🍔 Plat préféré pour un Saturday night gaming ?",
     "opts": ["🍔 Burger", "🍜 Ramen", "🌮 Tacos", "🍕 Pizza"]},
    {"q": "☕ Boisson de combat ?",
     "opts": ["☕ Café", "🥤 Soda", "💧 Eau", "🍵 Thé"]},
    {"q": "🎯 Tu es plutôt quel style ?",
     "opts": ["⚔️ Agro", "🛡️ Tank", "🎯 Sniper", "🤝 Support"]},
    {"q": "🐲 Combat préféré dans le bot ?",
     "opts": ["⚔️ Boss Raid", "🤜 Duel", "🎲 Quiz", "💎 Treasure"]},
    {"q": "📱 Tu joues sur quoi le plus souvent ?",
     "opts": ["💻 PC", "📱 Mobile", "🎮 Console", "🌐 Web"]},
    {"q": "🎰 Tu spin la Daily Wheel quand ?",
     "opts": ["🌅 Au réveil", "🕒 Midi", "🌆 Le soir", "❌ Jamais"]},
    {"q": "🏆 Plus belle victoire en jeu ?",
     "opts": ["🐉 Boss solo", "🏆 Tournoi", "🎯 1v1 clutch", "👥 Team win"]},
    {"q": "🎨 Style d'avatar préféré ?",
     "opts": ["🤖 Cyberpunk", "🧙 Fantasy", "🎮 Pixel art", "📸 Photo réelle"]},
    {"q": "💸 Si tu gagnais 1M de coins, tu ferais quoi en 1er ?",
     "opts": ["🏰 Banque", "🛒 Marketplace", "🎰 Wheel × 1000", "💎 Tout investir"]},
    {"q": "⏰ Tu te connectes au serveur combien de fois par jour ?",
     "opts": ["1", "2-3", "5+", "🚫 Toujours offline"]},
    {"q": "🎭 Tu aimes quelle saison du bot ?",
     "opts": ["🌸 Printemps", "☀️ Été", "🍂 Automne", "❄️ Hiver"]},
    {"q": "🐾 Ton pet préféré ?",
     "opts": ["🦊 Renard", "🦉 Chouette", "🐢 Tortue", "🐲 Dragon"]},
    {"q": "🏰 Tu joues à Roblox ?",
     "opts": ["🔥 Tous les jours", "📅 Souvent", "⏰ Parfois", "❌ Jamais"]},
    {"q": "🎬 Genre de film préféré ?",
     "opts": ["🦸 Action", "👽 SF", "🎭 Comédie", "😱 Horreur"]},
    {"q": "📚 Tu lis quoi entre 2 games ?",
     "opts": ["📖 Manga", "📚 Livre", "📱 Reddit", "❌ Jamais"]},
    {"q": "🚀 Si tu pouvais ajouter 1 feature au bot ?",
     "opts": ["🎮 Mini-jeu", "🏆 Trophée", "💰 Économie", "🤖 IA chat"]},
    {"q": "⭐ Note ta journée gaming sur 10 ?",
     "opts": ["1-3", "4-6", "7-8", "9-10"]},
    {"q": "🎉 Tu fêtes les anniversaires sur Discord ?",
     "opts": ["🎂 Toujours", "🎁 Parfois", "😶 Discret", "❌ Jamais"]},
    {"q": "📺 Tu watch des streams ?",
     "opts": ["🔥 Twitch", "🎥 YouTube", "📺 Kick", "❌ Aucun"]},
    {"q": "🍴 Dîner gamer parfait ?",
     "opts": ["🍣 Sushi", "🥙 Kebab", "🍝 Pasta", "🥗 Healthy"]},
    {"q": "💻 OS préféré ?",
     "opts": ["🪟 Windows", "🍎 macOS", "🐧 Linux", "❌ Autre"]},
    {"q": "🎙️ Mic ON ou OFF en vocal ?",
     "opts": ["🎤 Toujours ON", "🤐 Souvent OFF", "👂 Que pour écouter", "🔇 Jamais en vocal"]},
    {"q": "🌍 Hémisphère gaming ?",
     "opts": ["🇪🇺 Europe", "🇺🇸 NA", "🇯🇵 Asie", "🇧🇷 SA"]},
    {"q": "💰 Combien tu dépenses en skins/jeux par mois ?",
     "opts": ["0€", "1-20€", "20-50€", "50€+"]},
    {"q": "🎯 Toi en tant que dev de jeu, tu ferais quoi ?",
     "opts": ["🏰 MMO", "🤜 PvP", "🎨 Indé", "🧩 Puzzle"]},
    {"q": "🔥 Streak record sur le bot ?",
     "opts": ["1-3 jours", "4-7 jours", "8-30 jours", "30+ jours"]},
    {"q": "🎓 Tu apprends quoi en ce moment ?",
     "opts": ["💻 Code", "🎨 Design", "🎮 Speedrun", "📚 Études"]},
]


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    add_coins_fn=None,
):
    global _bot, _get_db, _db_get, _v2, _add_coins
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    # Phase 251.23 : enregistre le bouton de vote PERSISTANT (DynamicItem) pour que
    # les clics SURVIVENT à un reboot. Sans ça, après chaque redéploiement la vue en
    # mémoire est morte → « ❌ Échec de l'interaction » (le sondage vit 24h, bien
    # au-delà d'un restart). Le DynamicItem matche le custom_id `prompt_vote_*` au clic.
    try:
        bot_instance.add_dynamic_items(_PromptVoteButton)
    except Exception:
        pass


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    question TEXT,
                    options_jsonb TEXT,
                    votes_jsonb TEXT DEFAULT '{}',
                    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    status TEXT DEFAULT 'open',
                    channel_id INTEGER,
                    message_id INTEGER
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_prompts_guild "
                "ON daily_prompts(guild_id, day)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[daily_prompt init_db] {ex}")


def _pick_question(used_questions: set) -> dict:
    """Choisit une question pas utilisée récemment (sinon random)."""
    available = [q for q in QUESTIONS if q["q"] not in used_questions]
    if not available:
        available = QUESTIONS
    return random.choice(available)


async def post_now(guild: discord.Guild) -> bool:
    """Poste le prompt du jour dans le hub ou un salon chatty."""
    if _get_db is None or _v2 is None or not guild:
        return False
    try:
        # Récupère les 30 dernières questions utilisées
        async with _get_db() as db:
            async with db.execute(
                "SELECT question FROM daily_prompts "
                "WHERE guild_id=? "
                "ORDER BY posted_at DESC LIMIT 30",
                (guild.id,),
            ) as cur:
                used = {r[0] for r in await cur.fetchall()}

        # Check si déjà posté aujourd'hui
        today = (
            datetime.now(_PARIS_TZ) if _PARIS_TZ else datetime.now(timezone.utc)
        ).strftime("%Y-%m-%d")
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM daily_prompts "
                "WHERE guild_id=? AND day=?",
                (guild.id, today),
            ) as cur:
                if await cur.fetchone():
                    return False  # déjà posté

        # Choisit la question
        q_data = _pick_question(used)

        # Trouve un salon (hub ou chatty)
        target_channel = None
        for ch in guild.text_channels:
            n = ch.name.lower()
            if "hub" in n or "general" in n or "💫" in n or "discussion" in n:
                if ch.permissions_for(guild.me).send_messages:
                    target_channel = ch
                    break
        if target_channel is None:
            # Fallback : 1er salon écrivable MAIS « chatty » — on EXCLUT explicitement
            # tickets / logs / annonces / règlement / staff / accueil / arènes (ne JAMAIS
            # poster une question du jour dans un salon sérieux, en lecture seule ou de combat).
            _BAD = ("ticket", "log", "audit", "mod", "staff", "annonce", "announce",
                    "rule", "règl", "regl", "welcome", "bienvenue", "info", "chronique",
                    "combat", "arène", "arene", "vente", "shop", "boutique")
            for ch in guild.text_channels:
                n = ch.name.lower()
                if any(b in n for b in _BAD):
                    continue
                if ch.permissions_for(guild.me).send_messages:
                    target_channel = ch
                    break
        if target_channel is None:
            return False

        # Nettoyage : supprime le message de la question PRÉCÉDENTE (DB-backed → survit
        # aux redémarrages ; évite que les votes s'accumulent jour après jour dans le chat).
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT channel_id, message_id FROM daily_prompts "
                    "WHERE guild_id=? AND message_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (guild.id,),
                ) as _pc:
                    _prev = await _pc.fetchone()
            if _prev and _prev[0] and _prev[1]:
                _pch = guild.get_channel(int(_prev[0]))
                if _pch is not None:
                    try:
                        _pm = await _pch.fetch_message(int(_prev[1]))
                        await _pm.delete()
                    except Exception:
                        pass
        except Exception:
            pass

        # Insert + post
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO daily_prompts "
                "(guild_id, day, question, options_jsonb, channel_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    guild.id, today, q_data["q"],
                    json.dumps(q_data["opts"]),
                    target_channel.id,
                ),
            )
            prompt_id = cur.lastrowid
            await db.commit()

        # Build panel + envoie
        view = _build_vote_view(prompt_id, q_data)
        LayoutView = _v2['LayoutView']
        v2_title = _v2['v2_title']
        v2_subtitle = _v2['v2_subtitle']
        v2_body = _v2['v2_body']
        v2_divider = _v2['v2_divider']
        v2_container = _v2['v2_container']

        items = [
            v2_title("📅 Question du jour"),
            v2_subtitle("Fin demain 18h · tous les votants gagnent +50 coins."),
            v2_divider(),
            v2_body(f"## {q_data['q']}"),
        ]

        class _PromptPanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=None)
                self.add_item(v2_container(*items, color=0x5865F2))
                # Phase 235.5 : boutons nus interdits en top-level LayoutView
                # (400 50035) → on enveloppe les boutons de vote dans des ActionRow.
                _btns = list(view.children)
                for _k in range(0, len(_btns), 5):
                    try:
                        self.add_item(discord.ui.ActionRow(*_btns[_k:_k + 5]))
                    except Exception:
                        pass

        msg = await target_channel.send(view=_PromptPanel())
        async with _get_db() as db:
            await db.execute(
                "UPDATE daily_prompts SET message_id=? WHERE id=?",
                (msg.id, prompt_id),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[daily_prompt post_now] {ex}")
        return False


class _PromptVoteButton(
    discord.ui.DynamicItem[Button],
    template=r"prompt_vote_(?P<pid>[0-9]+)_(?P<idx>[0-9]+)",
):
    """Bouton de vote PERSISTANT (Phase 251.23) — capté par son custom_id même
    APRÈS un reboot (le sondage du jour vit 24h). On reconstruit prompt_id + index
    depuis le custom_id ; le libellé de l'option est relu en DB au clic."""
    def __init__(self, prompt_id: int, choice_idx: int,
                 label: str = "Vote", emoji=None):
        self.prompt_id = int(prompt_id)
        self.choice_idx = int(choice_idx)
        super().__init__(
            Button(
                label=(label or "Vote")[:80],
                emoji=emoji,
                style=discord.ButtonStyle.primary,
                custom_id=f"prompt_vote_{int(prompt_id)}_{int(choice_idx)}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["pid"]), int(match["idx"]))

    async def callback(self, i: discord.Interaction):
        await _on_vote_click(i, self.prompt_id, self.choice_idx)


def _build_vote_view(prompt_id: int, q_data: dict):
    """View avec les boutons-réponses."""
    from discord.ui import View

    class _VoteView(View):
        def __init__(self):
            super().__init__(timeout=None)
            for idx, opt in enumerate(q_data["opts"][:4]):
                # Extract emoji from opt (first char usually)
                emoji = opt[0] if opt and not opt[0].isalnum() else None
                label = opt[2:] if emoji else opt
                btn = Button(
                    label=label[:30],
                    emoji=emoji,
                    style=discord.ButtonStyle.primary,
                    custom_id=f"prompt_vote_{prompt_id}_{idx}",
                )

                async def _cb(i: discord.Interaction, choice_idx=idx):
                    await _on_vote_click(i, prompt_id, choice_idx)

                btn.callback = _cb
                self.add_item(btn)

    return _VoteView()


async def _on_vote_click(
    i: discord.Interaction, prompt_id: int, choice_idx: int,
):
    """Gère un clic de vote. Le libellé de l'option est relu en DB depuis l'index
    → robuste APRÈS un reboot (le DynamicItem ne connaît que prompt_id + index)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT votes_jsonb, status, options_jsonb FROM daily_prompts "
                "WHERE id=?",
                (prompt_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return await i.response.send_message(
                "❌ Vote introuvable.", ephemeral=True
            )
        if row[1] != "open":
            return await i.response.send_message(
                "🔒 Le vote est terminé.", ephemeral=True
            )
        try:
            opts = json.loads(row[2] or "[]")
        except Exception:
            opts = []
        if not (0 <= choice_idx < len(opts)):
            return await i.response.send_message(
                "❌ Choix invalide.", ephemeral=True
            )
        choice_text = opts[choice_idx]
        votes = json.loads(row[0] or "{}")
        uid = str(i.user.id)
        if uid in votes:
            return await i.response.send_message(
                f"ℹ️ Tu as déjà voté **{votes[uid]}**. 1 vote/jour max.",
                ephemeral=True,
            )
        votes[uid] = choice_text
        async with _get_db() as db:
            await db.execute(
                "UPDATE daily_prompts SET votes_jsonb=? WHERE id=?",
                (json.dumps(votes), prompt_id),
            )
            await db.commit()
        await i.response.send_message(
            f"✅ Vote enregistré : **{choice_text}**. "
            f"Résultats demain à 18h !",
            ephemeral=True,
        )
    except Exception as ex:
        print(f"[_on_vote_click] {ex}")


async def close_yesterday(guild: discord.Guild) -> dict:
    """Ferme le prompt d'hier + distribue les coins."""
    out = {"closed": False, "voters_count": 0, "winning_option": None,
           "coins_distributed": 0}
    if _get_db is None or not guild:
        return out
    try:
        yesterday = (
            (datetime.now(_PARIS_TZ) if _PARIS_TZ else datetime.now(timezone.utc))
            - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, votes_jsonb, options_jsonb FROM daily_prompts "
                "WHERE guild_id=? AND day=? AND status='open'",
                (guild.id, yesterday),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return out
        prompt_id = int(row[0])
        votes = json.loads(row[1] or "{}")
        if not votes:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE daily_prompts SET status='closed', "
                    "closed_at=CURRENT_TIMESTAMP WHERE id=?",
                    (prompt_id,),
                )
                await db.commit()
            return out

        # Compte votes
        tally: dict[str, int] = {}
        for choice in votes.values():
            tally[choice] = tally.get(choice, 0) + 1
        winning = max(tally, key=tally.get)
        winners = [int(uid) for uid, c in votes.items() if c == winning]

        # Distribute coins
        if _add_coins is not None:
            for uid_str, choice in votes.items():
                try:
                    bonus = 200 if choice == winning else 0
                    await _add_coins(guild.id, int(uid_str), 50 + bonus)
                    out["coins_distributed"] += 50 + bonus
                except Exception:
                    pass

        # Phase 156 : chaque vote donne 1 ticket de loterie (1 vote = 1 prompt/jour
        # donc max 1 ticket/jour de cette source — ~5/semaine si quotidien)
        try:
            import roblox_raffle as raffle_mod
            for uid_str in votes.keys():
                try:
                    await raffle_mod.add_tickets(
                        guild.id, int(uid_str), "votes_5_week", 1,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        async with _get_db() as db:
            await db.execute(
                "UPDATE daily_prompts SET status='closed', "
                "closed_at=CURRENT_TIMESTAMP WHERE id=?",
                (prompt_id,),
            )
            await db.commit()

        out["closed"] = True
        out["voters_count"] = len(votes)
        out["winning_option"] = winning
        return out
    except Exception as ex:
        print(f"[daily_prompt close_yesterday] {ex}")
        return out


@tasks.loop(minutes=15)
async def daily_prompt_task():
    """Check chaque 15min si on est à 18h FR."""
    try:
        if _bot is None:
            return
        if _PARIS_TZ is not None:
            now_paris = datetime.now(_PARIS_TZ)
        else:
            now_paris = datetime.now(timezone.utc) + timedelta(hours=2)
        if now_paris.hour != 18:
            return
        for g in _bot.guilds:
            try:
                # 1. Ferme hier
                await close_yesterday(g)
                # 2. Poste aujourd'hui
                await post_now(g)
            except Exception as ex:
                print(f"[daily_prompt_task guild={g.id}] {ex}")
    except Exception as ex:
        print(f"[daily_prompt_task] {ex}")


@daily_prompt_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup",
    "init_db",
    "post_now",
    "close_yesterday",
    "daily_prompt_task",
    "QUESTIONS",
]
