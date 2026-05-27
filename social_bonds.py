"""
social_bonds.py — Liens sociaux entre joueurs (Phase 133).

Quatre types de bonds gérés au même endroit :

1. **FRIENDSHIP** — amitié mutuelle (2-step propose/accept)
   • Aucune limite, on peut avoir N amis
   • Bonus de +20% coins sur les highfives entre amis
   • Visible dans /bond list

2. **MARRIAGE** — mariage symbolique (1 par user max, 2-step)
   • +100 coins/jour offerts par le partenaire automatiquement
   • Bague visible dans /profile (titre custom)

3. **RIVALRY** — rival déclaré (1 par user, one-way claim)
   • Sans consentement nécessaire
   • Bonus en duel contre son rival (+10% reward)

4. **INTERACTIONS** — hug / highfive / wave / etc.
   • Limites anti-spam (1× par receiver par jour)
   • Hug = câlin gratuit (juste social)
   • Highfive = +25 coins pour les deux si amis, +10 sinon

DB tables (créées à la volée) :
- friendships         (guild_id, user_a, user_b, since)  # user_a < user_b
- friend_requests     (guild_id, sender_id, receiver_id, created_at)
- marriages           (guild_id, user_a, user_b, since)  # user_a < user_b
- marriage_proposals  (guild_id, sender_id, receiver_id, created_at)
- rivalries           (guild_id, user_id, rival_id, since)
- social_interactions (id, guild_id, from_user, to_user, kind, day, created_at)

API publique :
- setup(get_db_fn, v2_helpers)
- Helpers async : propose_friend / accept_or_decline / list_friends / unfriend
                  propose_marry / divorce / get_spouse
                  declare_rival / clear_rival / get_rival
                  send_interaction / can_send_interaction
- show_panel(interaction) — /bond list V2

Toutes les commandes /bond X sont définies côté bot.py via le group app_commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord


# ─── Limites et bonus ────────────────────────────────────────────────────
HUG_COIN_BONUS_RECEIVER = 50         # /bond hug → receiver gagne
HIGHFIVE_BONUS_DEFAULT = 10          # /bond highfive → bonus standard
HIGHFIVE_BONUS_FRIENDS = 25          # /bond highfive entre amis
MARRIAGE_DAILY_GIFT = 100            # coins offerts par le conjoint (1×/jour)
RIVAL_DUEL_BONUS_PCT = 0.10          # +10% reward en duel contre son rival


# Références injectées
_get_db = None
_v2_helpers = None


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Création des tables (à la volée à la 1ère utilisation)
# ═══════════════════════════════════════════════════════════════════════════════

_tables_initialized = False


async def _ensure_tables():
    """Crée toutes les tables nécessaires si pas déjà fait."""
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS friendships (
                guild_id INTEGER,
                user_a INTEGER,
                user_b INTEGER,
                since DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_a, user_b)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS friend_requests (
                guild_id INTEGER,
                sender_id INTEGER,
                receiver_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, sender_id, receiver_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS marriages (
                guild_id INTEGER,
                user_a INTEGER,
                user_b INTEGER,
                since DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_a, user_b)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS marriage_proposals (
                guild_id INTEGER,
                sender_id INTEGER,
                receiver_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, sender_id, receiver_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS rivalries (
                guild_id INTEGER,
                user_id INTEGER,
                rival_id INTEGER,
                since DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS social_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                from_user INTEGER,
                to_user INTEGER,
                kind TEXT,
                day TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_social_interactions_day "
                "ON social_interactions(guild_id, from_user, to_user, kind, day)"
            )
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[social_bonds _ensure_tables] {ex}")


def _ordered(a: int, b: int) -> tuple[int, int]:
    """Retourne (a, b) ordonné pour clé canonique (user_a < user_b)."""
    return (a, b) if a < b else (b, a)


# ═══════════════════════════════════════════════════════════════════════════════
# FRIENDSHIP
# ═══════════════════════════════════════════════════════════════════════════════

async def is_friend(guild_id: int, user_a: int, user_b: int) -> bool:
    """Check si 2 users sont amis."""
    if _get_db is None or user_a == user_b:
        return False
    await _ensure_tables()
    a, b = _ordered(user_a, user_b)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM friendships WHERE guild_id=? AND user_a=? AND user_b=?",
                (guild_id, a, b),
            ) as cur:
                return (await cur.fetchone()) is not None
    except Exception as ex:
        print(f"[social_bonds is_friend] {ex}")
        return False


async def propose_friend(
    guild_id: int, sender_id: int, receiver_id: int
) -> tuple[str, str]:
    """Propose une amitié (ou accepte si invitation inverse existe).

    Returns: (status, message)
        status in {"accepted", "pending", "already", "self", "error"}
    """
    if sender_id == receiver_id:
        return "self", "Tu ne peux pas être ami avec toi-même."
    if _get_db is None:
        return "error", "Module non initialisé."

    await _ensure_tables()
    a, b = _ordered(sender_id, receiver_id)

    try:
        async with _get_db() as db:
            # Déjà amis ?
            async with db.execute(
                "SELECT 1 FROM friendships WHERE guild_id=? AND user_a=? AND user_b=?",
                (guild_id, a, b),
            ) as cur:
                if await cur.fetchone():
                    return "already", "Vous êtes déjà amis."

            # Demande inverse existante ? → accepter
            async with db.execute(
                "SELECT 1 FROM friend_requests "
                "WHERE guild_id=? AND sender_id=? AND receiver_id=?",
                (guild_id, receiver_id, sender_id),
            ) as cur:
                inverse_pending = await cur.fetchone() is not None

            if inverse_pending:
                # Créer l'amitié + nettoyer les requests
                await db.execute(
                    "INSERT OR IGNORE INTO friendships "
                    "(guild_id, user_a, user_b) VALUES (?, ?, ?)",
                    (guild_id, a, b),
                )
                await db.execute(
                    "DELETE FROM friend_requests "
                    "WHERE guild_id=? AND ((sender_id=? AND receiver_id=?) "
                    "OR (sender_id=? AND receiver_id=?))",
                    (guild_id, sender_id, receiver_id,
                     receiver_id, sender_id),
                )
                await db.commit()
                return "accepted", "Amitié acceptée !"

            # Sinon : créer une nouvelle request (ou ignore si existe déjà)
            await db.execute(
                "INSERT OR IGNORE INTO friend_requests "
                "(guild_id, sender_id, receiver_id) VALUES (?, ?, ?)",
                (guild_id, sender_id, receiver_id),
            )
            await db.commit()
            return "pending", "Demande envoyée. En attente d'acceptation."
    except Exception as ex:
        print(f"[social_bonds propose_friend] {ex}")
        return "error", f"Erreur DB : `{ex}`"


async def unfriend(guild_id: int, user_a: int, user_b: int) -> bool:
    """Supprime une amitié. Retourne True si supprimée."""
    if _get_db is None or user_a == user_b:
        return False
    await _ensure_tables()
    a, b = _ordered(user_a, user_b)
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM friendships WHERE guild_id=? AND user_a=? AND user_b=?",
                (guild_id, a, b),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[social_bonds unfriend] {ex}")
        return False


async def list_friends(guild_id: int, user_id: int) -> list[int]:
    """Liste des friend_ids de user_id."""
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_a, user_b FROM friendships "
                "WHERE guild_id=? AND (user_a=? OR user_b=?)",
                (guild_id, user_id, user_id),
            ) as cur:
                rows = await cur.fetchall()
        return [int(b) if int(a) == user_id else int(a) for a, b in rows]
    except Exception as ex:
        print(f"[social_bonds list_friends] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# MARRIAGE
# ═══════════════════════════════════════════════════════════════════════════════

async def get_spouse(guild_id: int, user_id: int) -> Optional[int]:
    """Retourne l'id du conjoint, ou None."""
    if _get_db is None:
        return None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_a, user_b FROM marriages "
                "WHERE guild_id=? AND (user_a=? OR user_b=?)",
                (guild_id, user_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row:
            a, b = int(row[0]), int(row[1])
            return b if a == user_id else a
    except Exception as ex:
        print(f"[social_bonds get_spouse] {ex}")
    return None


async def propose_marry(
    guild_id: int, sender_id: int, receiver_id: int
) -> tuple[str, str]:
    """Propose un mariage (ou accepte si demande inverse existe).

    Returns: (status, message)
        status in {"accepted", "pending", "already_married_self",
                   "already_married_target", "self", "error"}
    """
    if sender_id == receiver_id:
        return "self", "Tu ne peux pas t'épouser toi-même."
    if _get_db is None:
        return "error", "Module non initialisé."

    await _ensure_tables()
    a, b = _ordered(sender_id, receiver_id)

    try:
        # Vérifs : ni l'un ni l'autre marié
        if (await get_spouse(guild_id, sender_id)) is not None:
            return "already_married_self", "Tu es déjà marié(e). Divorce d'abord."
        if (await get_spouse(guild_id, receiver_id)) is not None:
            return "already_married_target", "Cette personne est déjà mariée."

        async with _get_db() as db:
            # Demande inverse existante ? → accepter
            async with db.execute(
                "SELECT 1 FROM marriage_proposals "
                "WHERE guild_id=? AND sender_id=? AND receiver_id=?",
                (guild_id, receiver_id, sender_id),
            ) as cur:
                inverse_pending = await cur.fetchone() is not None

            if inverse_pending:
                await db.execute(
                    "INSERT OR IGNORE INTO marriages "
                    "(guild_id, user_a, user_b) VALUES (?, ?, ?)",
                    (guild_id, a, b),
                )
                # Nettoie toutes les proposals impliquant les 2
                await db.execute(
                    "DELETE FROM marriage_proposals WHERE guild_id=? AND "
                    "(sender_id IN (?, ?) OR receiver_id IN (?, ?))",
                    (guild_id, sender_id, receiver_id,
                     sender_id, receiver_id),
                )
                await db.commit()
                return "accepted", "Mariage célébré ! 💍"

            await db.execute(
                "INSERT OR IGNORE INTO marriage_proposals "
                "(guild_id, sender_id, receiver_id) VALUES (?, ?, ?)",
                (guild_id, sender_id, receiver_id),
            )
            await db.commit()
            return "pending", "Demande en mariage envoyée."
    except Exception as ex:
        print(f"[social_bonds propose_marry] {ex}")
        return "error", f"Erreur DB : `{ex}`"


async def divorce(guild_id: int, user_id: int) -> Optional[int]:
    """Divorce ; retourne l'ex-conjoint id (ou None si pas marié)."""
    if _get_db is None:
        return None
    spouse = await get_spouse(guild_id, user_id)
    if spouse is None:
        return None
    a, b = _ordered(user_id, spouse)
    try:
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM marriages WHERE guild_id=? AND user_a=? AND user_b=?",
                (guild_id, a, b),
            )
            await db.commit()
        return spouse
    except Exception as ex:
        print(f"[social_bonds divorce] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# RIVALRY (one-way)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_rival(guild_id: int, user_id: int) -> Optional[int]:
    """Retourne l'id du rival, ou None."""
    if _get_db is None:
        return None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT rival_id FROM rivalries WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else None
    except Exception as ex:
        print(f"[social_bonds get_rival] {ex}")
        return None


async def declare_rival(
    guild_id: int, user_id: int, rival_id: int
) -> tuple[str, str]:
    """Déclare un rival (écrase l'ancien). One-way claim, pas de consentement.

    Returns: (status, message)
    """
    if user_id == rival_id:
        return "self", "Tu ne peux pas te rivaliser toi-même."
    if _get_db is None:
        return "error", "Module non initialisé."

    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO rivalries (guild_id, user_id, rival_id) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "rival_id=?, since=CURRENT_TIMESTAMP",
                (guild_id, user_id, rival_id, rival_id),
            )
            await db.commit()
        return "ok", "Rival déclaré."
    except Exception as ex:
        print(f"[social_bonds declare_rival] {ex}")
        return "error", f"Erreur DB : `{ex}`"


async def clear_rival(guild_id: int, user_id: int) -> bool:
    """Supprime le rival. Retourne True si retiré."""
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM rivalries WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[social_bonds clear_rival] {ex}")
        return False


def is_rival_pair(guild_id: int, a_rival: Optional[int], b_id: int) -> bool:
    """Sync check (depuis valeur déjà fetched) — utile dans combat module."""
    return a_rival is not None and a_rival == b_id


# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIONS (hug / highfive / wave)
# ═══════════════════════════════════════════════════════════════════════════════

async def can_send_interaction(
    guild_id: int, from_user: int, to_user: int, kind: str
) -> bool:
    """Anti-spam : 1× par receiver par jour pour ce kind d'interaction."""
    if _get_db is None or from_user == to_user:
        return False
    await _ensure_tables()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM social_interactions "
                "WHERE guild_id=? AND from_user=? AND to_user=? "
                "AND kind=? AND day=?",
                (guild_id, from_user, to_user, kind, today),
            ) as cur:
                return (await cur.fetchone()) is None
    except Exception as ex:
        print(f"[social_bonds can_send_interaction] {ex}")
        return False


async def record_interaction(
    guild_id: int, from_user: int, to_user: int, kind: str
):
    """Enregistre une interaction."""
    if _get_db is None:
        return
    await _ensure_tables()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO social_interactions "
                "(guild_id, from_user, to_user, kind, day) VALUES (?, ?, ?, ?, ?)",
                (guild_id, from_user, to_user, kind, today),
            )
            await db.commit()
    except Exception as ex:
        print(f"[social_bonds record_interaction] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panel V2 /bond list
# ═══════════════════════════════════════════════════════════════════════════════

async def build_panel(guild: discord.Guild, member: discord.Member):
    """Construit le panel V2 de tous les bonds du joueur."""
    if _v2_helpers is None:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    friends = await list_friends(guild.id, member.id)
    spouse = await get_spouse(guild.id, member.id)
    rival = await get_rival(guild.id, member.id)

    class _BondPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"💞  LIENS DE {member.display_name.upper()}"))
            items.append(v2_subtitle("_Ton réseau social sur le serveur_"))
            items.append(v2_divider())

            # Mariage
            items.append(v2_body("**╔═══ 💍  MARIAGE  ═══╗**"))
            if spouse:
                items.append(v2_body(
                    f"💑 Marié(e) à <@{spouse}>\n"
                    f"_Vous touchez `{MARRIAGE_DAILY_GIFT}` coins l'un de l'autre chaque jour._"
                ))
            else:
                items.append(v2_body(
                    "_Pas (encore) marié(e). `/bond marry @user` pour proposer._"
                ))

            # Amis
            items.append(v2_divider())
            items.append(v2_body(
                f"**╔═══ 👥  AMIS ({len(friends)})  ═══╗**"
            ))
            if friends:
                # Affiche max 15
                shown = friends[:15]
                lines = [f"• <@{fid}>" for fid in shown]
                if len(friends) > 15:
                    lines.append(f"_… et {len(friends) - 15} autre(s)_")
                items.append(v2_body("\n".join(lines)))
            else:
                items.append(v2_body(
                    "_Aucun ami pour l'instant. `/bond friend @user` pour en ajouter._"
                ))

            # Rival
            items.append(v2_divider())
            items.append(v2_body("**╔═══ ⚔️  RIVAL  ═══╗**"))
            if rival:
                items.append(v2_body(
                    f"💢 Rival déclaré : <@{rival}>\n"
                    f"_+{int(RIVAL_DUEL_BONUS_PCT * 100)}% de récompenses "
                    f"sur les duels contre cette personne._"
                ))
            else:
                items.append(v2_body(
                    "_Aucun rival. `/bond rival @user` pour en déclarer un._"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/bond hug @user` ou `/bond highfive @user` "
                "pour interagir (1× par jour par personne)._"
            ))

            self.add_item(v2_container(*items, color=0xE91E63))

    return _BondPanel()


__all__ = [
    "setup",
    # Friend
    "propose_friend", "unfriend", "list_friends", "is_friend",
    # Marriage
    "propose_marry", "divorce", "get_spouse",
    # Rival
    "declare_rival", "clear_rival", "get_rival", "is_rival_pair",
    # Interactions
    "can_send_interaction", "record_interaction",
    # Constants
    "HUG_COIN_BONUS_RECEIVER",
    "HIGHFIVE_BONUS_DEFAULT",
    "HIGHFIVE_BONUS_FRIENDS",
    "MARRIAGE_DAILY_GIFT",
    "RIVAL_DUEL_BONUS_PCT",
    # Rendering
    "build_panel",
]
