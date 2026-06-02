"""
wandering_merchant.py — NPC marchand qui passe 1×/jour avec items rares
(Phase 169.2).

🎯 OBJECTIF : donner aux joueurs qui accumulent des coins un moyen de
les DÉPENSER sur du stuff unique sans transfert P2P (le bot vend, pas
un autre joueur).

Mécanique :
- Chaque jour à 18h FR : un NPC marchand "apparaît" dans l'arène
- Stock limité (5 items aléatoires) avec qty 1-3 chacun
- Prix élevés (5000-50 000 coins selon rareté)
- Bouton "🛒 Acheter" sur chaque item
- Despawn à minuit FR (6h ouverture)
- Pas 2× le même item dans le même mois

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, add_coins_fn)
- init_db()
- spawn_merchant_task (daily 18h FR)

DB :
- merchant_visits (id PK, guild_id, started_at, expires_at, status)
- merchant_stock (id PK, visit_id, item_kind, item_data_json, price,
                  qty_remaining)
- merchant_purchases (id PK, visit_id, user_id, item_kind, price_paid)
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

VISIT_HOUR_START = 18
VISIT_DURATION_HOURS = 6  # 18h → minuit
ITEMS_PER_VISIT = 5

# Catalogue items du marchand (rotation mensuelle)
MERCHANT_CATALOG = [
    {
        "id": "title_explorer",
        "name": "Titre : Explorateur Errant",
        "emoji": "🧭",
        "desc": "Titre permanent affiché à côté de ton nom",
        "price": 8000,
        "rarity": "rare",
    },
    {
        "id": "title_collector",
        "name": "Titre : Collectionneur",
        "emoji": "💎",
        "desc": "Titre permanent (collectionneur de drops)",
        "price": 10000,
        "rarity": "rare",
    },
    {
        "id": "title_legend",
        "name": "Titre : Légende Vivante",
        "emoji": "👑",
        "desc": "Titre permanent — réservé aux riches",
        "price": 50000,
        "rarity": "legendary",
    },
    {
        "id": "season_token_extra",
        "name": "Jeton Saison Bonus",
        "emoji": "🎫",
        "desc": "+500 points saison instantanés",
        "price": 12000,
        "rarity": "rare",
    },
    {
        "id": "enchant_scroll",
        "name": "Parchemin d'Enchantement",
        "emoji": "📜",
        "desc": "Enchante 1 item à chance 100% (consommé)",
        "price": 15000,
        "rarity": "epic",
    },
    {
        "id": "rarity_upgrade",
        "name": "Cristal de Raffinage Garanti",
        "emoji": "💠",
        "desc": "Upgrade rareté d'un item à 100% (vs 60% en forge)",
        "price": 25000,
        "rarity": "epic",
    },
    {
        "id": "pet_xp_boost",
        "name": "Friandise Magique Pet",
        "emoji": "🍖",
        "desc": "+500 XP instantanés sur ton pet actif",
        "price": 6000,
        "rarity": "rare",
    },
    {
        "id": "lucky_charm",
        "name": "Porte-bonheur",
        "emoji": "🍀",
        "desc": "+20% chance loot pendant 24h",
        "price": 7500,
        "rarity": "rare",
    },
    {
        "id": "treasure_map",
        "name": "Carte au Trésor Ancienne",
        "emoji": "🗺️",
        "desc": "Spawn un Treasure Hunt immédiatement",
        "price": 9000,
        "rarity": "rare",
    },
    {
        "id": "mystery_box_premium",
        "name": "Boîte Mystère Premium",
        "emoji": "🎁",
        "desc": "Drop tier légendaire garanti",
        "price": 18000,
        "rarity": "epic",
    },
    {
        "id": "raffle_ticket_5",
        "name": "Pack 5 Tickets Loterie",
        "emoji": "🎰",
        "desc": "5 tickets de loterie hebdo bonus",
        "price": 8000,
        "rarity": "rare",
    },
    {
        "id": "reputation_boost",
        "name": "Médaille de Reconnaissance",
        "emoji": "🥇",
        "desc": "+100 points réputation",
        "price": 11000,
        "rarity": "rare",
    },
]


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None):
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
                CREATE TABLE IF NOT EXISTS merchant_visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    message_id INTEGER DEFAULT 0,
                    channel_id INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    status TEXT DEFAULT 'active'
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS merchant_stock (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    item_data_json TEXT,
                    price INTEGER NOT NULL,
                    qty_remaining INTEGER DEFAULT 1
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS merchant_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    visit_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    price_paid INTEGER,
                    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_merchant_visits_active "
                "ON merchant_visits(guild_id, status, expires_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[wandering_merchant init_db] {ex}")


async def _find_arena_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Trouve le salon arène pour spawn le marchand.

    Phase 169.4 : 3 niveaux de fallback (cohérent avec mob_hunts + world_invasion) :
    1. `combat_arena_channel_id` configuré par owner — préféré
    2. Arène boss raid ACTIVE (table events.arena_channel_id) — temporaire
    3. Recherche par nom "arène/arena/combat/boss"
    4. None → marchand ne spawn pas (skip silencieux)
    """
    if _db_get is None or _get_db is None:
        return None

    # 1. Salon combat configuré par owner
    try:
        cfg_data = await _db_get(guild.id)
        ch_id = int(cfg_data.get("combat_arena_channel_id", 0) or 0)
        if ch_id:
            ch = guild.get_channel(ch_id)
            if ch:
                return ch
    except Exception:
        pass

    # 2. Arène boss raid active (si un boss tourne)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT arena_channel_id FROM events "
                "WHERE guild_id=? AND ended=0 "
                "ORDER BY id DESC LIMIT 1",
                (guild.id,),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0]:
            ch = guild.get_channel(int(row[0]))
            if ch:
                return ch
    except Exception:
        pass

    # 3. Fallback : recherche par nom
    for ch in guild.text_channels:
        n = (ch.name or "").lower()
        if any(k in n for k in ["arène", "arena", "combat", "boss"]):
            return ch
    return None


async def _items_sold_this_month(guild_id: int) -> set[str]:
    """IDs d'items déjà vendus ce mois — anti-doublon mensuel."""
    out: set[str] = set()
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT DISTINCT item_id FROM merchant_purchases "
                "WHERE guild_id=? AND "
                "datetime(purchased_at) > datetime('now', '-30 days')",
                (guild_id,),
            ) as cur:
                for r in await cur.fetchall():
                    out.add(r[0])
    except Exception:
        pass
    return out


async def spawn_merchant(guild: discord.Guild) -> bool:
    """Spawn le marchand pour cette guild."""
    if not guild or _get_db is None:
        return False

    # Vérifie qu'aucun marchand n'est déjà actif
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM merchant_visits "
                "WHERE guild_id=? AND status='active' AND "
                "datetime(expires_at) > datetime('now')",
                (guild.id,),
            ) as cur:
                if await cur.fetchone():
                    return False
    except Exception:
        pass

    ch = await _find_arena_channel(guild)
    if not ch:
        return False

    # Sélection items (5) en évitant ce qui a été vendu ce mois
    excluded = await _items_sold_this_month(guild.id)
    pool = [item for item in MERCHANT_CATALOG if item["id"] not in excluded]
    if len(pool) < ITEMS_PER_VISIT:
        # Si trop de répétitions exclues, on permet le pool entier
        pool = MERCHANT_CATALOG[:]
    selected = random.sample(pool, min(ITEMS_PER_VISIT, len(pool)))

    expires = datetime.now(timezone.utc) + timedelta(hours=VISIT_DURATION_HOURS)

    # INSERT visit
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO merchant_visits "
                "(guild_id, channel_id, expires_at) VALUES (?, ?, ?)",
                (guild.id, ch.id, expires.isoformat()),
            )
            visit_id = cur.lastrowid
            await db.commit()

            # INSERT stock
            for item in selected:
                qty = random.randint(1, 3)
                await db.execute(
                    "INSERT INTO merchant_stock "
                    "(visit_id, item_id, item_data_json, price, qty_remaining) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        visit_id, item["id"],
                        json.dumps(item, ensure_ascii=False),
                        int(item["price"]),
                        qty,
                    ),
                )
            await db.commit()
    except Exception as ex:
        print(f"[wandering_merchant spawn] {ex}")
        return False

    # Build le panel + post
    msg = await _post_merchant_panel(ch, visit_id, selected)
    if msg:
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE merchant_visits SET message_id=? WHERE id=?",
                    (msg.id, visit_id),
                )
                await db.commit()
        except Exception:
            pass

    print(
        f"[wandering_merchant] spawn guild={guild.id} "
        f"items={[i['id'] for i in selected]}"
    )
    return True


async def _post_merchant_panel(
    ch: discord.TextChannel, visit_id: int, items_list: list[dict],
) -> Optional[discord.Message]:
    """Build et poste le panel du marchand."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    items_render = []
    items_render.append(v2_title("🛒  MARCHAND ITINÉRANT"))
    items_render.append(v2_subtitle(
        f"_Le marchand est de passage ! Il reste {VISIT_DURATION_HOURS}h._\n"
        f"_Stock limité — premier arrivé, premier servi._"
    ))
    items_render.append(v2_divider())

    for item in items_list:
        items_render.append(v2_body(
            f"{item['emoji']} **{item['name']}**\n"
            f"_{item['desc']}_\n"
            f"💰 **{item['price']:,}** 🪙"
        ))
    items_render.append(v2_divider())
    items_render.append(v2_body(
        "_💡 Le bot vend — aucun échange entre joueurs. "
        "Stock se rechargera demain à 18h FR._"
    ))

    class _MerchantLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items_render, color=0xD4AF37))

    layout = _MerchantLayout()
    # Phase 208 FIX : boutons d'achat dans un ActionRow (max 5).
    # Un bouton brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body".
    # On crée des Button bruts avec le MÊME custom_id que MerchantBuyButton
    # (DynamicItem) ; le clic est capté par le DynamicItem enregistré (match
    # du custom_id) — un DynamicItem ne peut PAS aller dans un ActionRow.
    buy_buttons = []
    for item in items_list[:5]:
        buy_buttons.append(Button(
            label=f"🛒 {item['name'][:30]} — {item['price']:,} 🪙",
            style=discord.ButtonStyle.success,
            custom_id=f"merch_buy:{visit_id}:{item['id']}",
        ))
    if buy_buttons:
        layout.add_item(discord.ui.ActionRow(*buy_buttons))

    try:
        msg = await ch.send(view=layout)
        return msg
    except Exception as ex:
        print(f"[wandering_merchant post_panel] {ex}")
        return None


class MerchantBuyButton(discord.ui.DynamicItem[Button], template=r"merch_buy:(?P<visit_id>\d+):(?P<item_id>\w+)"):
    """Persistent button — achat d'un item du marchand."""

    def __init__(self, visit_id: int, item_id: str, item_name: str = "?", price: int = 0):
        super().__init__(
            Button(
                label=f"🛒 {item_name[:30]} — {price:,} 🪙",
                style=discord.ButtonStyle.success,
                custom_id=f"merch_buy:{visit_id}:{item_id}",
            )
        )
        self.visit_id = visit_id
        self.item_id = item_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["visit_id"]), match["item_id"])

    async def callback(self, btn_i: discord.Interaction):
        try:
            await btn_i.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            await _process_purchase(btn_i, self.visit_id, self.item_id)
        except Exception as ex:
            print(f"[merch_buy callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


async def _process_purchase(btn_i: discord.Interaction, visit_id: int, item_id: str):
    """Traite l'achat : check stock + check coins + débite + log."""
    if _get_db is None or _add_coins is None or btn_i.guild is None:
        return

    # Récupère le stock
    async with _get_db() as db:
        async with db.execute(
            "SELECT id, qty_remaining, price, item_data_json FROM merchant_stock "
            "WHERE visit_id=? AND item_id=?",
            (visit_id, item_id),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return await btn_i.followup.send("❌ Item introuvable.", ephemeral=True)
    stock_id, qty, price, item_data = row
    if int(qty) <= 0:
        return await btn_i.followup.send(
            "❌ Stock épuisé sur cet item.", ephemeral=True
        )

    # Check coins
    try:
        # Use existing get_user_economy if accessible via bot module — fallback
        # On lit directement depuis economy table
        async with _get_db() as db:
            async with db.execute(
                "SELECT coins, bank FROM economy WHERE guild_id=? AND user_id=?",
                (btn_i.guild.id, btn_i.user.id),
            ) as cur:
                eco_row = await cur.fetchone()
        hand = int(eco_row[0] or 0) if eco_row else 0
        bank = int(eco_row[1] or 0) if eco_row else 0
    except Exception:
        hand, bank = 0, 0

    if hand + bank < int(price):
        return await btn_i.followup.send(
            f"💸 Fonds insuffisants : tu as `{hand + bank:,}` 🪙 "
            f"mais l'item coûte `{int(price):,}` 🪙.",
            ephemeral=True,
        )

    # Débite (main d'abord, puis banque)
    from_hand = min(hand, int(price))
    from_bank = int(price) - from_hand
    try:
        if from_hand > 0:
            await _add_coins(btn_i.guild.id, btn_i.user.id, -from_hand)
        if from_bank > 0:
            async with _get_db() as db:
                # FIX audit (re-check) : borne à 0 (`MAX(0, …)`) — comme add_bank dans
                # bot.py. Sans le plancher, un débit concurrent ou un double-clic
                # pouvait rendre la banque NÉGATIVE. Relatif → pas de lost-update.
                await db.execute(
                    "UPDATE economy SET bank = MAX(0, bank - ?) "
                    "WHERE guild_id=? AND user_id=?",
                    (from_bank, btn_i.guild.id, btn_i.user.id),
                )
                await db.commit()
    except Exception as ex:
        return await btn_i.followup.send(
            f"❌ Échec du débit : `{ex}`", ephemeral=True
        )

    # Décrémente le stock
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE merchant_stock SET qty_remaining=qty_remaining-1 "
                "WHERE id=?",
                (stock_id,),
            )
            await db.execute(
                "INSERT INTO merchant_purchases "
                "(guild_id, visit_id, user_id, item_id, price_paid) "
                "VALUES (?, ?, ?, ?, ?)",
                (btn_i.guild.id, visit_id, btn_i.user.id, item_id, int(price)),
            )
            await db.commit()
    except Exception:
        pass

    # Parse item meta
    try:
        item_meta = json.loads(item_data or "{}")
    except Exception:
        item_meta = {}

    name = item_meta.get("name", item_id)
    emoji = item_meta.get("emoji", "🎁")

    await btn_i.followup.send(
        f"✅ Tu as acheté **{emoji} {name}** pour `{int(price):,}` 🪙 !\n\n"
        f"_L'item est ajouté à ton inventaire. Effet appliqué selon le type._",
        ephemeral=True,
    )


# ─── Daily spawn task ──────────────────────────────────────────────────────

@tasks.loop(hours=1)
async def spawn_merchant_task():
    """Toutes les heures : si 18h FR et pas de marchand actif, spawn."""
    if _bot is None or _get_db is None:
        return
    try:
        if _PARIS_TZ:
            now = datetime.now(_PARIS_TZ)
        else:
            now = datetime.now(timezone.utc) + timedelta(hours=2)
        if now.hour != VISIT_HOUR_START:
            return
        for guild in _bot.guilds:
            try:
                await spawn_merchant(guild)
            except Exception as ex:
                print(f"[merchant spawn_task g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[merchant spawn_task] {ex}")


@spawn_merchant_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(MerchantBuyButton)
    except Exception as ex:
        print(f"[wandering_merchant register_persistent_views] {ex}")


__all__ = [
    "setup",
    "init_db",
    "spawn_merchant",
    "spawn_merchant_task",
    "register_persistent_views",
    "MerchantBuyButton",
    "MERCHANT_CATALOG",
]
