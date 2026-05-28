"""
onboarding_journey.py — Parcours guidé en 5 étapes (Phase 153 — A3).

🎯 OBJECTIF : un nouveau membre ne doit JAMAIS être perdu. Au lieu d'un
mur de texte ou d'un DM cryptique, on le guide étape par étape pour
qu'il découvre les features par la pratique.

5 étapes (chacune débloque +500 coins) :
1. 🐾 Adopter un pet (5 boutons : Renard / Lapin / Chouette / Tortue / Dragon)
2. 🎰 Faire son 1er spin sur la Daily Wheel
3. 🎯 Compléter sa 1ère quête
4. ⚔️ Cliquer ATTAQUER sur le prochain boss qui apparaît
5. 🤝 Rejoindre ou créer une alliance

Après les 5 étapes → +5000 coins bonus + badge "🌟 Newcomer".

Le parcours est entièrement bouton-driven, accessible via DM ou via le
hub. Pas de pression : si l'user skippe une étape, ce n'est pas grave.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- start_for_member(member) -> bool
- mark_step_completed(guild_id, user_id, step) -> dict
- get_progress(guild_id, user_id) -> dict
- build_journey_panel(member) -> LayoutView

DB tables :
- onboarding_journey (guild_id, user_id, started_at, step_1_done,
                      step_2_done, step_3_done, step_4_done, step_5_done,
                      pet_chosen, completed_at, bonus_claimed,
                      PRIMARY KEY (guild_id, user_id))
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ui import Button, View

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_add_coins = None

STEPS = [
    {"key": "pet",       "emoji": "🐾", "label": "Adopte un pet",
     "desc": "Choisis ton compagnon de jeu — il te donnera des buffs",
     "reward": 500},
    {"key": "wheel",     "emoji": "🎰", "label": "1er spin Daily Wheel",
     "desc": "Tente ta chance : coins, items rares, ou jackpot",
     "reward": 500},
    {"key": "quest",     "emoji": "🎯", "label": "Première quête complétée",
     "desc": "Termine 1 quête du jour pour gagner XP + coins",
     "reward": 500},
    {"key": "boss",      "emoji": "⚔️", "label": "Premier coup sur un boss",
     "desc": "Attaque le prochain boss qui apparaît dans l'arène",
     "reward": 500},
    {"key": "alliance",  "emoji": "🤝", "label": "Rejoindre une alliance",
     "desc": "Crée ou rejoins une alliance pour les events groupés",
     "reward": 500},
]

PET_CHOICES = [
    {"slug": "fox",    "emoji": "🦊", "name": "Renard",
     "buff": "+12% chance Daily Wheel"},
    {"slug": "rabbit", "emoji": "🐰", "name": "Lapin",
     "buff": "+10% vitesse quêtes"},
    {"slug": "owl",    "emoji": "🦉", "name": "Chouette",
     "buff": "+15% XP riddles"},
    {"slug": "turtle", "emoji": "🐢", "name": "Tortue",
     "buff": "+20% défense boss raids"},
    {"slug": "dragon", "emoji": "🐲", "name": "Dragon",
     "buff": "+10% dégâts boss raids"},
]

FINAL_BONUS = 5000


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


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS onboarding_journey (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    step_1_done INTEGER DEFAULT 0,
                    step_2_done INTEGER DEFAULT 0,
                    step_3_done INTEGER DEFAULT 0,
                    step_4_done INTEGER DEFAULT 0,
                    step_5_done INTEGER DEFAULT 0,
                    pet_chosen TEXT,
                    completed_at TIMESTAMP,
                    bonus_claimed INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[onboarding_journey init_db] {ex}")


async def get_progress(guild_id: int, user_id: int) -> dict:
    """Renvoie l'état du parcours."""
    out = {
        "started": False,
        "steps_done": [False] * 5,
        "pet_chosen": None,
        "completed": False,
        "bonus_claimed": False,
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT started_at, step_1_done, step_2_done, step_3_done, "
                "step_4_done, step_5_done, pet_chosen, completed_at, "
                "bonus_claimed FROM onboarding_journey "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            out["started"] = True
            out["steps_done"] = [bool(row[i]) for i in range(1, 6)]
            out["pet_chosen"] = row[6]
            out["completed"] = bool(row[7])
            out["bonus_claimed"] = bool(row[8])
    except Exception:
        pass
    return out


async def start_for_member(member: discord.Member) -> bool:
    """Démarre le parcours pour un nouveau membre."""
    if _get_db is None or member is None or member.bot:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO onboarding_journey "
                "(guild_id, user_id) VALUES (?, ?)",
                (member.guild.id, member.id),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[onboarding_journey start] {ex}")
        return False


async def mark_step_completed(
    guild_id: int, user_id: int, step: int,
    extra: Optional[dict] = None,
) -> dict:
    """Marque une étape complétée + reward. Si toutes faites → bonus final.

    step : 1-5
    extra : dict optionnel (ex: pet_chosen pour step 1)
    """
    out = {"awarded": 0, "step_was_new": False, "completed_all": False,
           "final_bonus": 0}
    if _get_db is None or step < 1 or step > 5:
        return out
    try:
        # Vérifie pas déjà fait
        prog = await get_progress(guild_id, user_id)
        if not prog.get("started"):
            await _ensure_journey(guild_id, user_id)
            prog = await get_progress(guild_id, user_id)

        if prog["steps_done"][step - 1]:
            return out  # déjà fait
        out["step_was_new"] = True

        col = f"step_{step}_done"
        extra_sql = ""
        extra_args: list = []
        if extra and "pet_chosen" in extra and step == 1:
            extra_sql = ", pet_chosen = ?"
            extra_args.append(extra["pet_chosen"])

        async with _get_db() as db:
            await db.execute(
                f"UPDATE onboarding_journey SET {col} = 1 {extra_sql} "
                f"WHERE guild_id=? AND user_id=?",
                (*extra_args, guild_id, user_id),
            )
            await db.commit()

        # Reward étape
        reward = STEPS[step - 1]["reward"]
        if _add_coins is not None:
            try:
                await _add_coins(guild_id, user_id, reward)
                out["awarded"] = reward
            except Exception:
                pass

        # Check all done
        prog2 = await get_progress(guild_id, user_id)
        if all(prog2["steps_done"]) and not prog2["bonus_claimed"]:
            # Final bonus
            if _add_coins is not None:
                try:
                    await _add_coins(guild_id, user_id, FINAL_BONUS)
                    out["final_bonus"] = FINAL_BONUS
                except Exception:
                    pass
            async with _get_db() as db:
                await db.execute(
                    "UPDATE onboarding_journey SET "
                    "completed_at = CURRENT_TIMESTAMP, "
                    "bonus_claimed = 1 "
                    "WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
                await db.commit()
            out["completed_all"] = True
        return out
    except Exception as ex:
        print(f"[onboarding_journey mark_step] {ex}")
        return out


async def _ensure_journey(guild_id: int, user_id: int):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO onboarding_journey "
                "(guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await db.commit()
    except Exception:
        pass


def build_journey_panel(member: discord.Member):
    """Panel V2 du parcours d'onboarding."""
    if _v2 is None or member is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _JourneyPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.member = member

        async def populate(self):
            prog = await get_progress(member.guild.id, member.id)
            if not prog["started"]:
                await _ensure_journey(member.guild.id, member.id)
                prog = await get_progress(member.guild.id, member.id)

            done_count = sum(prog["steps_done"])
            items = []
            items.append(v2_title("🌟  Bienvenue ! Parcours de découverte"))
            items.append(v2_subtitle(
                f"_{done_count}/5 étapes complétées · "
                f"chaque étape = **+500 coins** · "
                f"toutes = **+5000 bonus**_"
            ))
            items.append(v2_divider())

            for i, step in enumerate(STEPS):
                done = prog["steps_done"][i]
                check = "✅" if done else "⬜"
                items.append(v2_body(
                    f"{check} {step['emoji']} **{step['label']}** "
                    f"_(+{step['reward']} coins)_"
                ))
                if not done:
                    items.append(v2_body(f"   _{step['desc']}_"))

            if prog["completed"]:
                items.append(v2_divider())
                items.append(v2_body(
                    "🌟 **PARCOURS COMPLÉTÉ !** Tu as gagné le badge "
                    "**Newcomer** et **+5000 coins bonus**. Bienvenue !"
                ))
            elif done_count > 0:
                items.append(v2_divider())
                remaining = 5 - done_count
                items.append(v2_body(
                    f"💪 Encore **{remaining}** étape(s) pour débloquer "
                    f"le bonus final de **5000 coins** !"
                ))

            # Phase 163.4 : fix — l'instruction "Commence par choisir ton
            # pet" doit être DANS le container, pas après. Auparavant elle
            # était ajoutée à items après self.add_item(v2_container(...)),
            # donc jamais affichée.
            if not prog["steps_done"][0]:
                items.append(v2_divider())
                items.append(v2_body("**👇 Commence par choisir ton pet :**"))

            self.add_item(v2_container(*items, color=0x9B59B6))

            # Étape 1 : pet — boutons inline si pas encore fait
            if not prog["steps_done"][0]:
                for pet in PET_CHOICES:
                    btn = Button(
                        label=pet["name"],
                        emoji=pet["emoji"],
                        style=discord.ButtonStyle.primary,
                    )

                    async def _cb(i: discord.Interaction, p=pet):
                        if i.user.id != member.id:
                            return await i.response.send_message(
                                "🔒 Pas pour toi.", ephemeral=True
                            )
                        result = await mark_step_completed(
                            member.guild.id, member.id, 1,
                            extra={"pet_chosen": p["slug"]},
                        )
                        msg = (
                            f"🎉 **Pet adopté : {p['emoji']} {p['name']}** !\n"
                            f"_Buff débloqué : {p['buff']}_\n"
                            f"_+{result['awarded']} coins_"
                        )
                        if result["completed_all"]:
                            msg += (
                                f"\n\n🌟 **PARCOURS COMPLÉTÉ !** "
                                f"+{result['final_bonus']} coins bonus final !"
                            )
                        await i.response.send_message(msg, ephemeral=True)

                    btn.callback = _cb
                    self.add_item(btn)

    return _JourneyPanel()


__all__ = [
    "setup",
    "init_db",
    "start_for_member",
    "mark_step_completed",
    "get_progress",
    "build_journey_panel",
    "STEPS",
    "PET_CHOICES",
]
