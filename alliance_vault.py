"""
alliance_vault.py — Coffre d'alliance + statistiques de gestion (Phase 135).

Complète le système d'alliance existant (Phase 67) avec :

1. **COFFRE D'ITEMS PARTAGÉ** : table alliance_vault_items
   • Les membres déposent des items dans le coffre
   • Le chef + les officiers (rank='leader') peuvent retirer
   • Quantités multiples (qty) supportées

2. **STATS DE CONTRIBUTION** : aggrégation depuis alliance_audit_log
   • Total coins déposés par membre (lifetime)
   • Total items déposés
   • Activité récente (7j / 30j)
   • Top contributeurs

3. **PANELS V2 magnifiques** :
   • build_vault_panel(alliance) — overview treasury + items + activité
   • build_audit_panel(alliance, limit) — historique complet du log
   • build_contribs_panel(alliance) — leaderboard des contributeurs

⚠️ Conforme à RULES.md : aucune interaction romantique/copain-copain.
Système purement de gestion / compétition entre alliances.

API publique :
- setup(get_db_fn, v2_helpers)
- deposit_item(alliance_id, user_id, item) -> ok
- withdraw_item(alliance_id, user_id, item_row_id) -> ok
- list_vault_items(alliance_id, limit) -> list[dict]
- get_contribs(alliance_id) -> list[dict]
- get_audit_lines(alliance_id, limit) -> list[dict]
- build_vault_panel / build_audit_panel / build_contribs_panel

Usage dans bot.py :
    import alliance_vault as av_module
    av_module.setup(get_db, v2_helpers)

    @bot.tree.command(name="vault")
    async def vault_cmd(i):
        # ... récupère alliance du user, appelle build_vault_panel ...
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord


# ─── Limites ───────────────────────────────────────────────────────────
VAULT_MAX_ITEMS = 50           # max items dans le coffre par alliance
CONTRIB_TOP_LIMIT = 10         # top 10 contributeurs affichés
AUDIT_DEFAULT_LIMIT = 15
ACTIVITY_WINDOW_DAYS = 7       # fenêtre pour "activité récente"


# Mapping des actions d'audit → emoji + label lisible
ACTION_LABELS = {
    "deposit_coins":      ("💰", "Dépôt de coins"),
    "withdraw_coins":     ("💸", "Retrait de coins"),
    "deposit_item":       ("📦", "Dépôt d'item"),
    "withdraw_item":      ("📤", "Retrait d'item"),
    "expel_member":       ("👋", "Expulsion membre"),
    "transfer_leader":    ("👑", "Transfert leadership"),
    "create_alliance":    ("✨", "Création alliance"),
    "dissolve_alliance":  ("💥", "Dissolution"),
    "invite_member":      ("📨", "Invitation envoyée"),
    "join_member":        ("➕", "Rejoint l'alliance"),
    "leave_member":       ("➖", "Quitte l'alliance"),
}


# Références injectées
_get_db = None
_v2_helpers = None
_tables_initialized = False


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Table alliance_vault_items
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS alliance_vault_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alliance_id INTEGER,
                item_name TEXT,
                item_emoji TEXT,
                rarity TEXT,
                stats_json TEXT,
                qty INTEGER DEFAULT 1,
                deposited_by INTEGER,
                deposited_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vault_items_alliance "
                "ON alliance_vault_items(alliance_id, deposited_at DESC)"
            )
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[alliance_vault _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# COFFRE D'ITEMS
# ═══════════════════════════════════════════════════════════════════════════════

async def vault_item_count(alliance_id: int) -> int:
    """Nombre total d'items dans le coffre."""
    if _get_db is None:
        return 0
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM alliance_vault_items "
                "WHERE alliance_id=?",
                (alliance_id,),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[alliance_vault vault_item_count] {ex}")
        return 0


async def deposit_item(
    alliance_id: int, user_id: int, item: dict
) -> tuple[bool, str]:
    """Dépose un item dans le coffre d'alliance.

    item: dict {name, emoji?, rarity?, atk?, def?, crit?, qty?}

    Returns: (ok, message)
    """
    if _get_db is None:
        return False, "Module non initialisé."
    name = (item.get("name") or "").strip()
    if not name:
        return False, "Nom de l'item requis."

    await _ensure_tables()
    if await vault_item_count(alliance_id) >= VAULT_MAX_ITEMS:
        return False, f"Coffre plein ({VAULT_MAX_ITEMS} items max)."

    qty = max(1, int(item.get("qty", 1) or 1))
    stats = {k: int(item[k]) for k in ("atk", "def", "crit") if item.get(k)}
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO alliance_vault_items "
                "(alliance_id, item_name, item_emoji, rarity, stats_json, qty, deposited_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    alliance_id, name,
                    item.get("emoji") or "📦",
                    (item.get("rarity") or "commune").lower(),
                    json.dumps(stats) if stats else None,
                    qty, user_id,
                ),
            )
            await db.commit()
        return True, f"`{name}` ×{qty} déposé."
    except Exception as ex:
        print(f"[alliance_vault deposit_item] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def withdraw_item(
    alliance_id: int, item_row_id: int
) -> tuple[bool, Optional[dict]]:
    """Retire un item du coffre (par row_id). Retourne (ok, item_dict_ou_None)."""
    if _get_db is None:
        return False, None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, item_name, item_emoji, rarity, stats_json, qty, deposited_by "
                "FROM alliance_vault_items WHERE id=? AND alliance_id=?",
                (item_row_id, alliance_id),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return False, None
            item = {
                "id": int(row[0]),
                "name": row[1],
                "emoji": row[2] or "📦",
                "rarity": row[3] or "commune",
                "stats": json.loads(row[4]) if row[4] else {},
                "qty": int(row[5] or 1),
                "deposited_by": int(row[6] or 0),
            }
            await db.execute(
                "DELETE FROM alliance_vault_items WHERE id=?", (item_row_id,)
            )
            await db.commit()
        return True, item
    except Exception as ex:
        print(f"[alliance_vault withdraw_item] {ex}")
        return False, None


async def list_vault_items(alliance_id: int, limit: int = 20) -> list[dict]:
    """Liste les items du coffre (les plus récents d'abord)."""
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, item_name, item_emoji, rarity, stats_json, qty, "
                "deposited_by, deposited_at "
                "FROM alliance_vault_items WHERE alliance_id=? "
                "ORDER BY deposited_at DESC LIMIT ?",
                (alliance_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": int(r[0]),
                "name": r[1],
                "emoji": r[2] or "📦",
                "rarity": r[3] or "commune",
                "stats": json.loads(r[4]) if r[4] else {},
                "qty": int(r[5] or 1),
                "deposited_by": int(r[6] or 0),
                "deposited_at": r[7],
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[alliance_vault list_vault_items] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# STATS DE CONTRIBUTION — aggrégation depuis alliance_audit_log
# ═══════════════════════════════════════════════════════════════════════════════

async def get_treasury(alliance_id: int) -> int:
    """Lit la trésorerie courante (table existante alliance_treasury)."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT coins FROM alliance_treasury WHERE alliance_id=?",
                (alliance_id,),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[alliance_vault get_treasury] {ex}")
        return 0


async def get_contribs(alliance_id: int, limit: int = CONTRIB_TOP_LIMIT) -> list[dict]:
    """Top contributeurs (coins déposés total, lifetime).

    Aggrège depuis alliance_audit_log (action='deposit_coins').
    """
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT actor_id, COALESCE(SUM(amount), 0) AS total_deposit, "
                "COUNT(*) AS deposit_count "
                "FROM alliance_audit_log "
                "WHERE alliance_id=? AND action='deposit_coins' "
                "GROUP BY actor_id ORDER BY total_deposit DESC LIMIT ?",
                (alliance_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "user_id": int(r[0] or 0),
                "total_deposit": int(r[1] or 0),
                "deposit_count": int(r[2] or 0),
            }
            for r in rows
            if r[0]
        ]
    except Exception as ex:
        print(f"[alliance_vault get_contribs] {ex}")
        return []


async def get_recent_activity(
    alliance_id: int, days: int = ACTIVITY_WINDOW_DAYS
) -> dict:
    """Stats d'activité récente (dépôts/retraits sur N jours)."""
    out = {
        "deposit_coins_total": 0,
        "withdraw_coins_total": 0,
        "items_deposited": 0,
        "items_withdrawn": 0,
        "unique_active_members": 0,
        "window_days": days,
    }
    if _get_db is None:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT action, COALESCE(SUM(amount), 0), COUNT(*) "
                "FROM alliance_audit_log "
                "WHERE alliance_id=? AND created_at >= ? "
                "GROUP BY action",
                (alliance_id, cutoff),
            ) as cur:
                for action, total, count in await cur.fetchall():
                    if action == "deposit_coins":
                        out["deposit_coins_total"] = int(total or 0)
                    elif action == "withdraw_coins":
                        out["withdraw_coins_total"] = int(total or 0)
                    elif action == "deposit_item":
                        out["items_deposited"] = int(count or 0)
                    elif action == "withdraw_item":
                        out["items_withdrawn"] = int(count or 0)

            async with db.execute(
                "SELECT COUNT(DISTINCT actor_id) FROM alliance_audit_log "
                "WHERE alliance_id=? AND created_at >= ?",
                (alliance_id, cutoff),
            ) as cur:
                row = await cur.fetchone()
            out["unique_active_members"] = int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[alliance_vault get_recent_activity] {ex}")
    return out


async def get_audit_lines(
    alliance_id: int, limit: int = AUDIT_DEFAULT_LIMIT
) -> list[dict]:
    """Lignes les plus récentes du log d'audit."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT action, actor_id, target_id, amount, detail, created_at "
                "FROM alliance_audit_log "
                "WHERE alliance_id=? ORDER BY created_at DESC LIMIT ?",
                (alliance_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "action": r[0] or "unknown",
                "actor_id": int(r[1] or 0),
                "target_id": int(r[2] or 0),
                "amount": int(r[3] or 0),
                "detail": r[4] or "",
                "created_at": r[5],
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[alliance_vault get_audit_lines] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# PANELS V2 — vault overview / audit / leaderboard
# ═══════════════════════════════════════════════════════════════════════════════

def _format_relative(dt_str) -> str:
    """Formate une date ISO en relatif (il y a Xh, Xj)."""
    if not dt_str:
        return "—"
    try:
        if isinstance(dt_str, str):
            # SQLite default format
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        else:
            dt = dt_str
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:
            return "à l'instant"
        if s < 3600:
            return f"il y a {s // 60}min"
        if s < 86400:
            return f"il y a {s // 3600}h"
        return f"il y a {s // 86400}j"
    except Exception:
        return "—"


async def build_vault_panel(alliance: dict):
    """Panel V2 — overview complet du coffre d'alliance.

    alliance: dict avec au moins {'id', 'name', 'emoji'}
    """
    if _v2_helpers is None or not alliance:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    alliance_id = int(alliance["id"])
    treasury = await get_treasury(alliance_id)
    items = await list_vault_items(alliance_id, limit=10)
    item_total = await vault_item_count(alliance_id)
    contribs = await get_contribs(alliance_id, limit=5)
    activity = await get_recent_activity(alliance_id)

    class _VaultPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            block = []
            emoji = alliance.get("emoji") or "🏰"
            block.append(v2_title(f"{emoji}  COFFRE — {alliance['name'].upper()}"))
            block.append(v2_subtitle(
                "_Gestion du trésor et du stockage partagés_"
            ))
            block.append(v2_divider())

            # Trésorerie
            block.append(v2_body("**╔═══ 💰  TRÉSORERIE  ═══╗**"))
            block.append(v2_body(
                f"🪙 **Coins en réserve :** `{treasury:,}`\n"
                f"📦 **Items stockés :** `{item_total}` / `{VAULT_MAX_ITEMS}`"
            ))

            # Activité récente
            block.append(v2_divider())
            block.append(v2_body(
                f"**╔═══ 📊  ACTIVITÉ ({activity['window_days']}j)  ═══╗**"
            ))
            block.append(v2_body(
                f"📥 Coins déposés : `+{activity['deposit_coins_total']:,}`\n"
                f"📤 Coins retirés : `-{activity['withdraw_coins_total']:,}`\n"
                f"📦 Items déposés : `{activity['items_deposited']}`\n"
                f"📤 Items retirés : `{activity['items_withdrawn']}`\n"
                f"👥 Membres actifs : `{activity['unique_active_members']}`"
            ))

            # Items du coffre
            if items:
                block.append(v2_divider())
                block.append(v2_body(
                    f"**╔═══ 📦  ITEMS RÉCENTS ({len(items)})  ═══╗**"
                ))
                lines = []
                rarity_emoji = {
                    "commune": "⚪", "rare": "🔵", "épique": "🟣",
                    "epique": "🟣", "légendaire": "🟠", "legendaire": "🟠",
                    "mythique": "🔴", "divine": "💎",
                }
                for it in items[:10]:
                    rb = rarity_emoji.get(it["rarity"].lower(), "⚪")
                    stats_str = ""
                    if it["stats"]:
                        parts = []
                        for k, v in it["stats"].items():
                            label = {"atk": "ATK", "def": "DEF", "crit": "CRIT%"}.get(k, k)
                            parts.append(f"+{v} {label}")
                        stats_str = f" `{' · '.join(parts)}`"
                    qty_str = f" ×{it['qty']}" if it["qty"] > 1 else ""
                    lines.append(
                        f"{rb} {it['emoji']} **{it['name']}**{qty_str}{stats_str} "
                        f"_(par <@{it['deposited_by']}>, {_format_relative(it['deposited_at'])})_"
                    )
                block.append(v2_body("\n".join(lines)))

            # Top contributeurs
            if contribs:
                block.append(v2_divider())
                block.append(v2_body("**╔═══ 🏆  TOP CONTRIBUTEURS  ═══╗**"))
                medals = ["🥇", "🥈", "🥉", "▪️", "▪️"]
                lines = []
                for idx, c in enumerate(contribs[:5]):
                    medal = medals[idx] if idx < 5 else "▪️"
                    lines.append(
                        f"{medal} <@{c['user_id']}> · `{c['total_deposit']:,}` coins "
                        f"sur `{c['deposit_count']}` dépôt(s)"
                    )
                block.append(v2_body("\n".join(lines)))

            block.append(v2_divider())
            block.append(v2_body(
                "_💡 Utilise les boutons d'alliance dans le hub pour déposer/retirer._"
            ))

            self.add_item(v2_container(*block, color=0xF39C12))

    return _VaultPanel()


async def build_audit_panel(alliance: dict, limit: int = AUDIT_DEFAULT_LIMIT):
    """Panel V2 — historique d'audit log de l'alliance."""
    if _v2_helpers is None or not alliance:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    lines = await get_audit_lines(int(alliance["id"]), limit=limit)

    class _AuditPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            block = []
            emoji = alliance.get("emoji") or "🏰"
            block.append(v2_title(f"{emoji}  HISTORIQUE — {alliance['name'].upper()}"))
            block.append(v2_subtitle(
                f"_Les {limit} dernières actions de l'alliance_"
            ))
            block.append(v2_divider())

            if not lines:
                block.append(v2_body(
                    "_Aucune activité enregistrée pour cette alliance._"
                ))
            else:
                formatted = []
                for ln in lines:
                    emoji_a, label = ACTION_LABELS.get(
                        ln["action"], ("▫️", ln["action"])
                    )
                    when = _format_relative(ln["created_at"])
                    amount_str = ""
                    if ln["amount"]:
                        amount_str = f" · `{ln['amount']:+,}` coins"
                    target_str = ""
                    if ln["target_id"]:
                        target_str = f" → <@{ln['target_id']}>"
                    detail_str = (
                        f" — _{ln['detail']}_" if ln["detail"] else ""
                    )
                    formatted.append(
                        f"{emoji_a} **{label}**{amount_str}\n"
                        f"  _par <@{ln['actor_id']}>{target_str}, {when}{detail_str}_"
                    )
                block.append(v2_body("\n\n".join(formatted)))

            block.append(v2_divider())
            block.append(v2_body(
                f"_Affichage des {len(lines)} dernières lignes._"
            ))

            self.add_item(v2_container(*block, color=0x7F8C8D))

    return _AuditPanel()


async def build_contribs_panel(alliance: dict):
    """Panel V2 — leaderboard complet des contributeurs."""
    if _v2_helpers is None or not alliance:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    contribs = await get_contribs(int(alliance["id"]), limit=CONTRIB_TOP_LIMIT)
    treasury = await get_treasury(int(alliance["id"]))

    class _ContribsPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            block = []
            emoji = alliance.get("emoji") or "🏰"
            block.append(v2_title(f"{emoji}  CONTRIBUTEURS — {alliance['name'].upper()}"))
            block.append(v2_subtitle(
                f"_Top {CONTRIB_TOP_LIMIT} membres ayant le plus contribué (lifetime)_"
            ))
            block.append(v2_divider())

            block.append(v2_body(
                f"🪙 **Trésorerie actuelle :** `{treasury:,}` coins\n"
                f"🏆 **Contributeurs lifetime :** `{len(contribs)}`"
            ))
            block.append(v2_divider())

            if not contribs:
                block.append(v2_body(
                    "_Aucun dépôt enregistré pour cette alliance._"
                ))
            else:
                medals = ["🥇", "🥈", "🥉"] + ["▪️"] * (CONTRIB_TOP_LIMIT - 3)
                lines = []
                for idx, c in enumerate(contribs):
                    medal = medals[idx] if idx < len(medals) else "▪️"
                    avg = c["total_deposit"] // max(1, c["deposit_count"])
                    lines.append(
                        f"{medal} <@{c['user_id']}>\n"
                        f"  _Total : `{c['total_deposit']:,}` coins · "
                        f"{c['deposit_count']} dépôt(s) · "
                        f"moy `{avg:,}`/dépôt_"
                    )
                block.append(v2_body("\n\n".join(lines)))

            block.append(v2_divider())
            block.append(v2_body(
                "_💡 Plus tu contribues, plus tu montes dans le classement. "
                "Le top 3 reçoit des bonus de saison._"
            ))

            self.add_item(v2_container(*block, color=0xFFD700))

    return _ContribsPanel()


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES — récupérer l'alliance d'un user
# ═══════════════════════════════════════════════════════════════════════════════

async def get_user_alliance(guild_id: int, user_id: int) -> Optional[dict]:
    """Retourne l'alliance du user (s'il en a une, non-dissoute), ou None."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT a.id, a.name, a.emoji, a.role_id, a.channel_id, "
                "a.leader_id, am.role "
                "FROM alliances a "
                "JOIN alliance_members am ON am.alliance_id = a.id "
                "WHERE a.guild_id=? AND a.dissolved=0 AND am.user_id=? LIMIT 1",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "name": row[1],
            "emoji": row[2] or "🏰",
            "role_id": int(row[3] or 0),
            "channel_id": int(row[4] or 0),
            "leader_id": int(row[5] or 0),
            "member_role": row[6] or "member",
        }
    except Exception as ex:
        print(f"[alliance_vault get_user_alliance] {ex}")
        return None


__all__ = [
    "setup",
    # Coffre items
    "deposit_item", "withdraw_item", "list_vault_items", "vault_item_count",
    # Stats
    "get_treasury", "get_contribs", "get_recent_activity", "get_audit_lines",
    # Panels V2
    "build_vault_panel", "build_audit_panel", "build_contribs_panel",
    # Utils
    "get_user_alliance",
    # Constants
    "VAULT_MAX_ITEMS", "ACTION_LABELS",
]
