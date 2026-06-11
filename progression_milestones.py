"""
progression_milestones.py — Paliers de progression (Phase 132).

Trois catalogues de milestones gérés au même endroit :

1. **STREAK** : palier sur le streak quotidien (jours consécutifs)
   • 3 / 7 / 14 / 30 / 60 / 100 / 200 / 365 jours
   • Award 1× = badge + coin bonus (jamais re-claimable)

2. **VETERAN** : ancienneté sur le serveur (jours depuis member.joined_at)
   • 7 / 30 / 90 / 180 / 365 / 730 jours
   • Award 1× = badge + coin bonus

3. **PRESTIGE** : perks cumulatifs par rang de prestige
   • Pas de claim (toujours actif tant que le rang est >= seuil)
   • Multiplicateurs coin / XP utilisables partout dans le bot

Lit depuis :
- user_streaks (current_streak / best_streak)
- user_prestige (rank)
- member.joined_at (Discord)

Écrit dans (table créée à la volée) :
- milestone_claims (guild_id, user_id, kind, threshold, claimed_at)

API publique :
- setup(get_db_fn, v2_helpers)
- check_and_award(guild, member, add_coins_fn) -> list[awarded_dict]
- show(interaction) — /milestones panel V2 avec progress
- prestige_coin_mult(rank) -> float
- prestige_xp_mult(rank) -> float
- compute_progress(streak, days_on_server, prestige_rank) -> dict

Usage dans bot.py :
    import progression_milestones as prog_module

    prog_module.setup(get_db, v2_helpers)

    # /milestones :
    @bot.tree.command(name="milestones")
    async def milestones_cmd(i):
        await prog_module.show(i)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord


# ═══════════════════════════════════════════════════════════════════════════════
# CATALOGUES — Paliers et récompenses
# ═══════════════════════════════════════════════════════════════════════════════

STREAK_MILESTONES = [
    {"days": 3,   "emoji": "🌱", "title": "Premiers Pas",    "coins": 200},
    {"days": 7,   "emoji": "🔥", "title": "Une Semaine",     "coins": 500},
    {"days": 14,  "emoji": "⚡", "title": "Deux Semaines",   "coins": 1500},
    {"days": 30,  "emoji": "💎", "title": "Un Mois",         "coins": 5000},
    {"days": 60,  "emoji": "🏆", "title": "Deux Mois",       "coins": 12000},
    {"days": 100, "emoji": "🌟", "title": "Centenaire",      "coins": 25000},
    {"days": 200, "emoji": "👑", "title": "Bicentenaire",    "coins": 60000},
    {"days": 365, "emoji": "💍", "title": "Une Année",       "coins": 150000},
]

VETERAN_MILESTONES = [
    {"days": 7,   "emoji": "🌿", "title": "Bienvenu",         "coins": 300},
    {"days": 30,  "emoji": "🍀", "title": "Habitué",          "coins": 1000},
    {"days": 90,  "emoji": "🌾", "title": "Régulier",         "coins": 3000},
    {"days": 180, "emoji": "🌳", "title": "Ancien",           "coins": 7500},
    {"days": 365, "emoji": "🎂", "title": "Vétéran",          "coins": 20000},
    {"days": 730, "emoji": "🏛️", "title": "Pilier",           "coins": 50000},
    {"days": 1095,"emoji": "🗿", "title": "Légende Vivante",  "coins": 100000},
]

# Perks de prestige — clé = rank minimum requis
# Tous les perks dont la clé <= current_rank sont actifs (cumulatifs sur le max)
PRESTIGE_PERKS = {
    1:  {"coin_mult": 1.05, "xp_mult": 1.05, "title": "Renommé"},
    2:  {"coin_mult": 1.10, "xp_mult": 1.10, "title": "Distingué"},
    3:  {"coin_mult": 1.15, "xp_mult": 1.15, "title": "Honorable"},
    5:  {"coin_mult": 1.25, "xp_mult": 1.25, "title": "Maître"},
    10: {"coin_mult": 1.50, "xp_mult": 1.50, "title": "Grand-Maître"},
    20: {"coin_mult": 2.00, "xp_mult": 2.00, "title": "Légende"},
}


# Références injectées
_get_db = None
_v2_helpers = None


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module avec get_db + helpers V2."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Table milestone_claims
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_claims_table():
    """Crée la table milestone_claims si nécessaire."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS milestone_claims (
                guild_id INTEGER,
                user_id INTEGER,
                kind TEXT,          -- 'streak' | 'veteran'
                threshold INTEGER,
                claimed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id, kind, threshold)
            )''')
            await db.commit()
    except Exception as ex:
        print(f"[progression _ensure_claims_table] {ex}")


async def _get_claimed_thresholds(guild_id: int, user_id: int) -> dict:
    """Retourne {'streak': set[int], 'veteran': set[int]} des paliers déjà claim."""
    out = {"streak": set(), "veteran": set()}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT kind, threshold FROM milestone_claims "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                for k, t in await cur.fetchall():
                    if k in out:
                        out[k].add(int(t))
    except Exception as ex:
        print(f"[progression _get_claimed_thresholds] {ex}")
    return out


async def _mark_claimed(guild_id: int, user_id: int, kind: str, threshold: int):
    """Marque un palier comme claim (insert ignore si déjà fait)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO milestone_claims "
                "(guild_id, user_id, kind, threshold) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, kind, threshold),
            )
            await db.commit()
    except Exception as ex:
        print(f"[progression _mark_claimed] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# LECTURE — Streak + Prestige depuis DB
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_streak(guild_id: int, user_id: int) -> tuple[int, int]:
    """Retourne (current_streak, best_streak)."""
    if _get_db is None:
        return 0, 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT current_streak, best_streak FROM user_streaks "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return int(row[0] or 0), int(row[1] or 0)
    except Exception as ex:
        print(f"[progression _get_streak] {ex}")
    return 0, 0


async def _get_prestige(guild_id: int, user_id: int) -> int:
    """Retourne le rank de prestige (0 si rien)."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT rank FROM user_prestige WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception as ex:
        print(f"[progression _get_prestige] {ex}")
    return 0


def _days_on_server(member: discord.Member) -> int:
    """Calcule le nombre de jours depuis joined_at."""
    try:
        if not member.joined_at:
            return 0
        joined = member.joined_at
        if joined.tzinfo is None:
            joined = joined.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - joined
        return max(0, int(delta.days))
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS — Multiplicateurs de prestige (lus partout dans le bot)
# ═══════════════════════════════════════════════════════════════════════════════

def prestige_coin_mult(rank: int) -> float:
    """Multiplicateur coin du palier de prestige le plus élevé atteint."""
    try:
        r = int(rank or 0)
    except (TypeError, ValueError):
        return 1.0
    best = 1.0
    for threshold, perk in PRESTIGE_PERKS.items():
        if r >= threshold:
            best = max(best, float(perk.get("coin_mult", 1.0)))
    return best


def prestige_xp_mult(rank: int) -> float:
    """Multiplicateur XP du palier de prestige le plus élevé atteint."""
    try:
        r = int(rank or 0)
    except (TypeError, ValueError):
        return 1.0
    best = 1.0
    for threshold, perk in PRESTIGE_PERKS.items():
        if r >= threshold:
            best = max(best, float(perk.get("xp_mult", 1.0)))
    return best


def prestige_title(rank: int) -> str:
    """Titre courant du joueur selon son rang de prestige."""
    try:
        r = int(rank or 0)
    except (TypeError, ValueError):
        return ""
    best_threshold = 0
    best_title = ""
    for threshold, perk in PRESTIGE_PERKS.items():
        if r >= threshold and threshold > best_threshold:
            best_threshold = threshold
            best_title = perk.get("title", "")
    return best_title


def _next_milestone(value: int, catalog: list) -> Optional[dict]:
    """Retourne le prochain palier non-atteint dans un catalogue."""
    for m in catalog:
        if m["days"] > value:
            return m
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Check & award (à appeler après daily quest / sur /milestones)
# ═══════════════════════════════════════════════════════════════════════════════

async def check_and_award(
    guild: discord.Guild,
    member: discord.Member,
    add_coins_fn=None,
) -> list[dict]:
    """Vérifie tous les paliers atteignables et award les non-claim.

    Args:
        guild        : guilde Discord
        member       : membre concerné
        add_coins_fn : fonction async (guild_id, user_id, amount) → solde, pour
                       créditer les coins. Optionnelle (skip si None).

    Returns:
        liste des paliers nouvellement award : [{'kind', 'milestone', 'reward'}]
    """
    awarded = []
    if _get_db is None or member is None or guild is None:
        return awarded

    await _ensure_claims_table()
    claimed = await _get_claimed_thresholds(guild.id, member.id)

    # Récupère les valeurs courantes
    current_streak, best_streak = await _get_streak(guild.id, member.id)
    streak_high = max(current_streak, best_streak)
    days_server = _days_on_server(member)

    # 1) Streak milestones
    for m in STREAK_MILESTONES:
        if streak_high >= m["days"] and m["days"] not in claimed["streak"]:
            try:
                if add_coins_fn:
                    await add_coins_fn(guild.id, member.id, int(m["coins"]))
                await _mark_claimed(guild.id, member.id, "streak", m["days"])
                awarded.append({"kind": "streak", "milestone": m})
            except Exception as ex:
                print(f"[progression award streak] {ex}")

    # 2) Veteran milestones
    for m in VETERAN_MILESTONES:
        if days_server >= m["days"] and m["days"] not in claimed["veteran"]:
            try:
                if add_coins_fn:
                    await add_coins_fn(guild.id, member.id, int(m["coins"]))
                await _mark_claimed(guild.id, member.id, "veteran", m["days"])
                awarded.append({"kind": "veteran", "milestone": m})
            except Exception as ex:
                print(f"[progression award veteran] {ex}")

    return awarded


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panel V2 du player progress
# ═══════════════════════════════════════════════════════════════════════════════

def _progress_bar(value: int, target: int, length: int = 14) -> str:
    """Barre de progression visuelle."""
    if target <= 0:
        return "`" + "█" * length + "` 100%"
    pct = min(1.0, max(0.0, value / target))
    filled = round(pct * length)
    empty = length - filled
    return f"`{'█' * filled}{'░' * empty}` {int(pct * 100)}%"


async def _build_layout(
    guild: discord.Guild,
    member: discord.Member,
    awarded_now: list[dict] | None = None,
):
    """Construit le panel V2."""
    if _v2_helpers is None:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    cur_streak, best_streak = await _get_streak(guild.id, member.id)
    days_server = _days_on_server(member)
    prestige_rank = await _get_prestige(guild.id, member.id)
    claimed = await _get_claimed_thresholds(guild.id, member.id)
    streak_high = max(cur_streak, best_streak)

    next_streak = _next_milestone(streak_high, STREAK_MILESTONES)
    next_vet = _next_milestone(days_server, VETERAN_MILESTONES)

    class _MilestonesLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"🏅  PROGRESSION DE {member.display_name.upper()}"))
            items.append(v2_subtitle(
                f"_Tes paliers, ton ancienneté, ton prestige_"
            ))
            items.append(v2_divider())

            # Récompenses qui viennent d'être attribuées
            if awarded_now:
                items.append(v2_body("### 🎉 PALIERS DÉBLOQUÉS"))
                lines = []
                total_coin_reward = 0
                for entry in awarded_now:
                    m = entry["milestone"]
                    kind_label = "🔥 Streak" if entry["kind"] == "streak" else "🌿 Ancienneté"
                    lines.append(
                        f"{m['emoji']} **{m['title']}** _({kind_label} {m['days']}j)_ "
                        f"→ +`{m['coins']:,}` coins"
                    )
                    total_coin_reward += int(m.get("coins", 0))
                items.append(v2_body("\n".join(lines)))
                if total_coin_reward > 0:
                    items.append(v2_body(
                        f"💰 **Total reçu maintenant : `{total_coin_reward:,}` coins**"
                    ))
                items.append(v2_divider())

            # Streak
            items.append(v2_body("### 🔥 STREAK QUOTIDIEN"))
            items.append(v2_body(
                f"⚡ Streak actuel : **`{cur_streak}`** jours\n"
                f"🏆 Meilleur streak : **`{best_streak}`** jours"
            ))
            if next_streak:
                items.append(v2_body(
                    f"🎯 Prochain palier : **{next_streak['emoji']} "
                    f"{next_streak['title']}** ({next_streak['days']}j)\n"
                    f"{_progress_bar(streak_high, next_streak['days'])}\n"
                    f"Récompense : **`+{next_streak['coins']:,}` coins**"
                ))
            else:
                items.append(v2_body(
                    "👑 **Tous les paliers de streak débloqués !** Tu es une légende."
                ))

            # Veteran
            items.append(v2_divider())
            items.append(v2_body("### 🌿 ANCIENNETÉ SUR LE SERVEUR"))
            items.append(v2_body(
                f"📅 Membre depuis : **`{days_server}`** jours"
            ))
            if next_vet:
                items.append(v2_body(
                    f"🎯 Prochain palier : **{next_vet['emoji']} "
                    f"{next_vet['title']}** ({next_vet['days']}j)\n"
                    f"{_progress_bar(days_server, next_vet['days'])}\n"
                    f"Récompense : **`+{next_vet['coins']:,}` coins**"
                ))
            else:
                items.append(v2_body(
                    "🏛️ **Tous les paliers d'ancienneté atteints — pilier du serveur !**"
                ))

            # Prestige
            items.append(v2_divider())
            items.append(v2_body("### 👑 PRESTIGE"))
            title = prestige_title(prestige_rank)
            coin_mult = prestige_coin_mult(prestige_rank)
            xp_mult = prestige_xp_mult(prestige_rank)
            if prestige_rank > 0:
                items.append(v2_body(
                    f"⭐ Rang : **{prestige_rank}**"
                    f"{f' — _{title}_' if title else ''}\n"
                    f"💰 Bonus coins permanent : **×{coin_mult:.2f}**\n"
                    f"📈 Bonus XP permanent : **×{xp_mult:.2f}**"
                ))
            else:
                items.append(v2_body(
                    "🌑 Pas encore prestigé. _Atteins le niveau max pour débloquer "
                    "le prestige et ses perks permanents (jusqu'à ×2 coins / XP au rang 20)._"
                ))

            # Total paliers claim
            total_claimed = len(claimed["streak"]) + len(claimed["veteran"])
            total_avail = len(STREAK_MILESTONES) + len(VETERAN_MILESTONES)
            items.append(v2_divider())
            items.append(v2_body(
                f"📋 **Paliers débloqués :** `{total_claimed}` / `{total_avail}`\n"
                f"_💡 Reviens chaque jour pour faire monter ton streak !_"
            ))

            self.add_item(v2_container(*items, color=0xFFD700))

    return _MilestonesLayout()


async def show(interaction: discord.Interaction, add_coins_fn=None) -> bool:
    """Affiche le panel à l'utilisateur (ephemeral).

    Si add_coins_fn est fourni, check_and_award sera appelé d'abord pour
    créditer les paliers atteints depuis la dernière vérification.

    Returns True si envoyé avec succès.
    """
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        try:
            await interaction.response.send_message(
                "❌ Serveur uniquement.", ephemeral=True
            )
        except Exception:
            pass
        return False

    try:
        # Award éventuel
        awarded = []
        if add_coins_fn is not None:
            awarded = await check_and_award(
                interaction.guild, interaction.user, add_coins_fn
            )

        view = await _build_layout(
            interaction.guild, interaction.user, awarded_now=awarded
        )
        if view is None:
            await interaction.response.send_message(
                "❌ Module progression indisponible.", ephemeral=True
            )
            return False

        if not interaction.response.is_done():
            await interaction.response.send_message(view=view, ephemeral=True)
        else:
            await interaction.followup.send(view=view, ephemeral=True)
        return True
    except Exception as ex:
        print(f"[progression show] {ex}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Erreur : `{ex}`", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Erreur : `{ex}`", ephemeral=True
                )
        except Exception:
            pass
        return False


__all__ = [
    "setup",
    "check_and_award",
    "show",
    # Helpers prestige (lus partout dans le bot)
    "prestige_coin_mult",
    "prestige_xp_mult",
    "prestige_title",
    # Catalogues
    "STREAK_MILESTONES",
    "VETERAN_MILESTONES",
    "PRESTIGE_PERKS",
]
