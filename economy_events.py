"""
economy_events.py — Événements économiques cycliques (Phase 131).

Cycle hebdomadaire **déterministe** : chaque jour de la semaine = un bonus
économique différent qui s'applique à tout le serveur. Pas de RNG : les
joueurs anticipent leurs activités selon le jour.

Cycle :
- 🚀 Lundi    : "MOTIVATION MONDAY"  — +20% coins sur toutes les activités
- 🛠️ Mardi    : "REPAIR TUESDAY"     — repair items gratuit à la banque
- 💎 Mercredi : "WEALTHY WEDNESDAY"  — daily / bank interest 2x
- ⚔️ Jeudi    : "THUNDER THURSDAY"   — récompenses duels/boss 1.5x
- 🎁 Vendredi : "FREEBIE FRIDAY"     — wheel spin gratuit 1x/jour
- 🏆 Samedi   : "CHAMPIONS SATURDAY" — loot world boss 1.5x
- 🌟 Dimanche : "SUNDAY FUNDAY"      — 0% taxe sur /gift (au lieu de 5%)

Une annonce auto est postée chaque jour à 9h00-9h30 Europe/Paris dans le
hub channel (anti-doublon via cfg key "econ_event_last_day").

Helpers exposés (sync, lockless — lus partout dans bot.py) :
- current_event() -> dict
- coin_multiplier() -> float
- daily_multiplier() / combat_multiplier() / loot_multiplier()
- repair_free() / wheel_free() -> bool
- gift_tax_rate() -> float
- apply_coin_mult(amount) -> int

Gift system (P2P transfer) :
- can_send_gift(guild_id, sender_id, amount) -> (ok, reason)
- log_gift(guild_id, sender_id, receiver_id, amount, tax)
- GIFT_MIN = 100 / GIFT_MAX_PER_DAY = 50000

Usage dans bot.py :
    import economy_events as econ_events_module

    econ_events_module.setup(bot, get_db, db_get, db_set, v2_helpers)
    if not econ_events_module.daily_announce_task.is_running():
        econ_events_module.daily_announce_task.start()
"""
from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord.ext import tasks

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = timezone.utc


# ═══════════════════════════════════════════════════════════════════════════════
# CATALOGUE DES BONUS HEBDOMADAIRES (weekday 0=lundi … 6=dimanche)
# ═══════════════════════════════════════════════════════════════════════════════

EVENTS = {
    0: {  # lundi
        "key": "motivation_monday",
        "emoji": "🚀",
        "label": "MOTIVATION MONDAY",
        "tagline": "+20% de coins sur toutes les activités du jour",
        "color": 0xE74C3C,
        "coin_mult": 1.20,
    },
    1: {  # mardi
        "key": "repair_tuesday",
        "emoji": "🛠️",
        "label": "REPAIR TUESDAY",
        "tagline": "Réparations gratuites à la banque toute la journée",
        "color": 0x3498DB,
        "repair_free": True,
    },
    2: {  # mercredi
        "key": "wealthy_wednesday",
        "emoji": "💎",
        "label": "WEALTHY WEDNESDAY",
        "tagline": "Daily reward et intérêts bancaires doublés",
        "color": 0x9B59B6,
        "daily_mult": 2.0,
    },
    3: {  # jeudi
        "key": "thunder_thursday",
        "emoji": "⚔️",
        "label": "THUNDER THURSDAY",
        "tagline": "Récompenses de duels et boss raids x1.5",
        "color": 0xF39C12,
        "combat_mult": 1.5,
    },
    4: {  # vendredi
        "key": "freebie_friday",
        "emoji": "🎁",
        "label": "FREEBIE FRIDAY",
        "tagline": "Un spin de roue gratuit par jour pour tous",
        "color": 0x1ABC9C,
        "wheel_free": True,
    },
    5: {  # samedi
        "key": "champions_saturday",
        "emoji": "🏆",
        "label": "CHAMPIONS SATURDAY",
        "tagline": "Loot des world boss et événements rares x1.5",
        "color": 0xFFD700,
        "loot_mult": 1.5,
    },
    6: {  # dimanche
        "key": "sunday_funday",
        "emoji": "🌟",
        "label": "SUNDAY FUNDAY",
        "tagline": "0% de taxe sur les gifts entre joueurs",
        "color": 0xE91E63,
        "gift_tax_zero": True,
    },
}

# ─── CAP GLOBAL ANTI-INFLATION (Tâche C.1) ──────────────────────────────────
# Toutes les sources de multiplicateur de pièces (saison × daily × weekend du
# seasonal_engine, bonus du jour ici, config event par-guilde, prestige) se
# cumulaient SANS plafond → empilement explosif possible (~×10 théorique).
# On agrège tout dans effective_coin_multiplier() puis on PLAFONNE à ce cap.
# Conservateur : on ne BAISSE pas les gains normaux, on coupe juste l'extrême.
COIN_MULT_GLOBAL_CAP = 3.0
COIN_MULT_FLOOR = 0.5  # garde-fou bas (une config owner < 0.5 ne casse rien)

# Taux de taxe par défaut (anti-laundering sur /gift)
DEFAULT_GIFT_TAX = 0.05  # 5%

# Limites anti-abus pour /gift
GIFT_MIN = 100
GIFT_MAX_PER_DAY = 50_000


# Références injectées
_bot = None
_get_db = None
_db_get = None
_db_set = None
_v2_helpers = None


def setup(bot_instance, get_db_fn, db_get_fn, db_set_fn, v2_helpers: dict):
    """Configure le module avec les références nécessaires du bot principal.

    Args:
        bot_instance : le bot discord.py
        get_db_fn    : helper async with get_db() pour requêtes
        db_get_fn    : async (guild_id) -> dict config
        db_set_fn    : async (guild_id, key, value) -> bool
        v2_helpers   : dict {'v2_title', 'v2_subtitle', 'v2_body',
                             'v2_divider', 'v2_container', 'LayoutView'}
    """
    global _bot, _get_db, _db_get, _db_set, _v2_helpers
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _db_set = db_set_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS — lus en sync partout dans le bot (pas d'I/O)
# ═══════════════════════════════════════════════════════════════════════════════

def current_event() -> dict:
    """Retourne le bonus actif aujourd'hui (Europe/Paris)."""
    now = datetime.now(_PARIS_TZ)
    return EVENTS.get(now.weekday(), EVENTS[0])


def coin_multiplier() -> float:
    """Multiplicateur de coins applicable aujourd'hui (1.0 si rien)."""
    return float(current_event().get("coin_mult", 1.0))


def daily_multiplier() -> float:
    """Multiplicateur sur /daily et intérêts banque."""
    return float(current_event().get("daily_mult", 1.0))


def combat_multiplier() -> float:
    """Multiplicateur sur duels et combats PvP/PvE."""
    return float(current_event().get("combat_mult", 1.0))


def loot_multiplier() -> float:
    """Multiplicateur sur loot world boss & events rares."""
    return float(current_event().get("loot_mult", 1.0))


def repair_free() -> bool:
    """True si réparation gratuite aujourd'hui."""
    return bool(current_event().get("repair_free", False))


def wheel_free() -> bool:
    """True si wheel spin gratuit aujourd'hui."""
    return bool(current_event().get("wheel_free", False))


def gift_tax_rate() -> float:
    """Taux de taxe sur /gift (0.0 le dimanche, 0.05 le reste)."""
    ev = current_event()
    if ev.get("gift_tax_zero"):
        return 0.0
    return DEFAULT_GIFT_TAX


def apply_coin_mult(amount: int) -> int:
    """Applique le multiplicateur coin du jour à un montant donné."""
    try:
        return int(round(int(amount) * coin_multiplier()))
    except (TypeError, ValueError):
        return int(amount or 0)


# ═══════════════════════════════════════════════════════════════════════════════
# MULTIPLICATEUR EFFECTIF CENTRAL + CAP GLOBAL (Tâche C.1)
# ═══════════════════════════════════════════════════════════════════════════════

def effective_coin_multiplier(
    guild_id: int | None = None,
    user_id: int | None = None,
    *,
    event_coin_mult: float = 1.0,
    prestige_rank: int = 0,
    detail: bool = False,
):
    """Agrège TOUTES les sources de multiplicateur de pièces et PLAFONNE.

    Sources empilées (multiplicatif) :
      • seasonal_engine.get_modifier("coin_mult")  — saison × daily × weekend
      • coin_multiplier()                          — bonus hebdo du jour (ce module)
      • event_coin_mult                            — config owner par-guilde (0.5..3.0)
      • prestige : 1 + coins_bonus(rank)           — bonus permanent (additif → facteur)

    Le produit est borné dans [COIN_MULT_FLOOR, COIN_MULT_GLOBAL_CAP].
    FAIL-SAFE : toute source qui lève renvoie 1.0 pour cette couche.

    Retourne float (le multiplicateur effectif borné), ou un dict si detail=True
    pour l'affichage (Ma Fortune) : {raw, effective, capped, sources}.
    """
    sources: dict[str, float] = {}

    # Couche 1 : seasonal_engine (saison × daily × weekend) — import paresseux
    try:
        import seasonal_engine as _season
        s = float(_season.get_modifier("coin_mult", 1.0))
        if s > 0:
            sources["saison/daily/weekend"] = s
    except Exception:
        pass

    # Couche 2 : bonus hebdo du jour (ce module)
    try:
        d = float(coin_multiplier())
        if d != 1.0 and d > 0:
            sources["bonus du jour"] = d
    except Exception:
        pass

    # Couche 3 : config event par-guilde (déjà bornée 0.5..3.0 à la saisie)
    try:
        e = float(event_coin_mult or 1.0)
        if e != 1.0 and e > 0:
            sources["réglage serveur"] = e
    except Exception:
        pass

    # Couche 4 : prestige (bonus permanent additif → on le convertit en facteur)
    try:
        if prestige_rank and prestige_rank > 0:
            import engagement47 as _eng47
            pb = float(_eng47.prestige_bonus_coins(int(prestige_rank)))
            if pb > 0:
                sources["prestige"] = 1.0 + pb
    except Exception:
        pass

    raw = 1.0
    for v in sources.values():
        raw *= v

    effective = max(COIN_MULT_FLOOR, min(COIN_MULT_GLOBAL_CAP, raw))
    capped = raw > COIN_MULT_GLOBAL_CAP

    if detail:
        return {
            "raw": round(raw, 3),
            "effective": round(effective, 3),
            "capped": capped,
            "cap": COIN_MULT_GLOBAL_CAP,
            "sources": sources,
        }
    return effective


def cap_coin_multiplier(raw_mult: float) -> float:
    """Plafonne un multiplicateur déjà combiné ailleurs (point d'application minimal).

    À utiliser là où plusieurs multiplicateurs sont DÉJÀ combinés dans le code
    existant : on borne juste le produit final dans [FLOOR, CAP], sans rien
    recalculer. FAIL-SAFE : une valeur invalide retombe sur 1.0.
    """
    try:
        m = float(raw_mult)
    except (TypeError, ValueError):
        return 1.0
    if m <= 0:
        return 1.0
    return max(COIN_MULT_FLOOR, min(COIN_MULT_GLOBAL_CAP, m))


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panel V2 du bonus actuel
# ═══════════════════════════════════════════════════════════════════════════════

def build_layout(guild=None):
    """Construit un LayoutView V2 montrant le bonus actif aujourd'hui."""
    if _v2_helpers is None:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    ev = current_event()

    # Bonus de demain pour teasing
    now = datetime.now(_PARIS_TZ)
    tomorrow_idx = (now.weekday() + 1) % 7
    tomorrow_ev = EVENTS.get(tomorrow_idx, EVENTS[0])

    class _BonusLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"{ev['emoji']} {ev['label']}"))
            items.append(v2_subtitle(f"-# {ev['tagline']}"))
            items.append(v2_divider())

            # Détails actifs aujourd'hui
            items.append(v2_body("### ✨ Aujourd'hui"))
            bullets = []
            if ev.get("coin_mult") and ev["coin_mult"] != 1.0:
                bullets.append(f"💰 Coins gagnés : **×{ev['coin_mult']}**")
            if ev.get("daily_mult") and ev["daily_mult"] != 1.0:
                bullets.append(f"🎁 Daily / banque : **×{ev['daily_mult']}**")
            if ev.get("combat_mult") and ev["combat_mult"] != 1.0:
                bullets.append(f"⚔️ Combats / duels : **×{ev['combat_mult']}**")
            if ev.get("loot_mult") and ev["loot_mult"] != 1.0:
                bullets.append(f"🏆 Loot boss : **×{ev['loot_mult']}**")
            if ev.get("repair_free"):
                bullets.append("🛠️ Réparations **gratuites** à la banque")
            if ev.get("wheel_free"):
                bullets.append("🎰 1 spin de wheel **offert** aujourd'hui")
            if ev.get("gift_tax_zero"):
                bullets.append("🎁 `/gift` **sans taxe** (0% au lieu de 5%)")
            if not bullets:
                bullets.append("_Aucun bonus actif aujourd'hui — repos pour la guilde._")
            items.append(v2_body("\n".join(f"• {b}" for b in bullets)))

            # Teasing du lendemain
            items.append(v2_divider())
            items.append(v2_body(
                f"### ⏭️ Demain\n"
                f"{tomorrow_ev['emoji']} **{tomorrow_ev['label']}**\n"
                f"-# {tomorrow_ev['tagline']}"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "-# 💡 Les bonus s'enchaînent sur 7 jours, en boucle."
            ))

            self.add_item(v2_container(*items, color=ev["color"]))

    return _BonusLayout()


# ═══════════════════════════════════════════════════════════════════════════════
# TASK PROGRAMMÉE — Annonce quotidienne du bonus
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def daily_announce_task():
    """Tourne toutes les 30 min — annonce le bonus du jour à 9h00-9h30 FR."""
    try:
        if _bot is None or _db_get is None or _db_set is None:
            return

        now_local = datetime.now(_PARIS_TZ)
        if now_local.hour != 9:
            return

        # Anti-doublon : YYYY-DDD (jour de l'année)
        day_id = now_local.strftime("%Y-%j")

        for guild in list(_bot.guilds):
            try:
                cfg_data = await _db_get(guild.id)
                last_day = cfg_data.get("econ_event_last_day", "")
                if last_day == day_id:
                    continue

                hub_ch_id = int(cfg_data.get("hub_channel", 0) or 0)
                if not hub_ch_id:
                    continue
                ch = guild.get_channel(hub_ch_id)
                if not ch:
                    continue

                view = build_layout(guild)
                if view is None:
                    continue

                try:
                    await ch.send(view=view)
                    await _db_set(guild.id, "econ_event_last_day", day_id)
                    print(f"✅ [econ_events] day={day_id} announced for guild={guild.id}")
                except (discord.Forbidden, discord.HTTPException) as ex:
                    print(f"[econ_events send guild={guild.id}] {ex}")
            except Exception as ex:
                print(f"[econ_events loop guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[econ_events daily loop] {ex}")


@daily_announce_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════════
# GIFT — Transfer P2P de coins entre joueurs
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_gift_table():
    """Crée la table gift_log si nécessaire."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS gift_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                sender_id INTEGER,
                receiver_id INTEGER,
                amount INTEGER,
                tax INTEGER,
                day TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_gift_log_sender_day "
                "ON gift_log(guild_id, sender_id, day)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[econ_events _ensure_gift_table] {ex}")


async def can_send_gift(guild_id: int, sender_id: int, amount: int) -> tuple[bool, str]:
    """Vérifie si un gift est autorisé.

    Retourne (ok, raison_si_pas_ok).
    """
    if _get_db is None:
        return False, "Module non initialisé."
    if amount < GIFT_MIN:
        return False, f"Montant minimum : `{GIFT_MIN}` coins."
    if amount > GIFT_MAX_PER_DAY:
        return False, f"Montant maximum par envoi : `{GIFT_MAX_PER_DAY:,}` coins."

    await _ensure_gift_table()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM gift_log "
                "WHERE guild_id=? AND sender_id=? AND day=?",
                (guild_id, sender_id, today),
            ) as cur:
                row = await cur.fetchone()
            sent_today = int(row[0] or 0) if row else 0
        if sent_today + amount > GIFT_MAX_PER_DAY:
            remaining = max(0, GIFT_MAX_PER_DAY - sent_today)
            return False, (
                f"Plafond journalier atteint. Déjà envoyé : `{sent_today:,}` coins. "
                f"Reste aujourd'hui : `{remaining:,}` coins."
            )
    except Exception as ex:
        print(f"[econ_events can_send_gift] {ex}")
        return False, f"Erreur DB : `{ex}`"

    return True, ""


async def log_gift(guild_id: int, sender_id: int, receiver_id: int,
                   amount: int, tax: int):
    """Enregistre un gift effectué dans le log."""
    if _get_db is None:
        return
    await _ensure_gift_table()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO gift_log "
                "(guild_id, sender_id, receiver_id, amount, tax, day) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, sender_id, receiver_id, amount, tax, today),
            )
            await db.commit()
    except Exception as ex:
        print(f"[econ_events log_gift] {ex}")


__all__ = [
    "setup",
    # Helpers sync
    "current_event",
    "coin_multiplier",
    "daily_multiplier",
    "combat_multiplier",
    "loot_multiplier",
    "repair_free",
    "wheel_free",
    "gift_tax_rate",
    "apply_coin_mult",
    "effective_coin_multiplier",
    "cap_coin_multiplier",
    "COIN_MULT_GLOBAL_CAP",
    # Rendering
    "build_layout",
    # Task
    "daily_announce_task",
    # Gift
    "can_send_gift",
    "log_gift",
    "GIFT_MIN",
    "GIFT_MAX_PER_DAY",
    # Catalogue
    "EVENTS",
]
