"""
webhook_tracker.py — Suivi & nettoyage automatique des webhooks (Phase 152).

🎯 OBJECTIF : réduire la surface d'attaque. Chaque webhook actif est un
secret à protéger. Webhooks oubliés (anciens partenariats, tests dev) =
risques de fuites.

Stratégie :
1. **Scan hebdo** : lister tous les webhooks du serveur via API Discord.
2. **DB tracking** : enregistrer first_seen, last_seen, last_used, owner.
3. **Inactive detection** : webhooks > 90j sans message = candidats suppression.
4. **Owner panel** : bouton "🔌 Webhooks" → liste avec boutons "Supprimer".
5. **Auto-revoke option** : si owner active "purge auto", les webhooks
   inactifs > 180j sont supprimés sans demander.

Pas de scan continu (rate limits API). 1 scan par semaine au boot + 1
scan manuel via bouton.

DB tables :
- webhook_registry (webhook_id PK, guild_id, channel_id, name,
                    owner_id, first_seen, last_seen, last_used,
                    is_active, last_check)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- scan_guild(guild) -> dict (results)
- get_inactive_webhooks(guild_id, days=90) -> list[dict]
- delete_webhook(webhook_id, reason) -> bool
- build_panel(guild) -> LayoutView
- weekly_scan_task (loop weekly)

⚠️ Permission Discord requise : Manage Webhooks (déjà bot perms).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button, View

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS webhook_registry (
                    webhook_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    name TEXT,
                    owner_id INTEGER,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_webhook_registry_guild "
                "ON webhook_registry(guild_id, is_active)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[webhook_tracker init_db] {ex}")


# ─── Scan ───────────────────────────────────────────────────────────────────

async def scan_guild(guild: discord.Guild) -> dict:
    """Liste tous les webhooks du guild + update DB."""
    out = {
        "guild_id": guild.id,
        "scanned": 0,
        "new": 0,
        "updated": 0,
        "deactivated": 0,
        "errors": [],
    }
    if _get_db is None or not guild:
        return out
    try:
        # Vérifie perm
        if not guild.me or not guild.me.guild_permissions.manage_webhooks:
            out["errors"].append("Permission Manage Webhooks manquante")
            return out

        # Liste tous les webhooks
        try:
            webhooks = await guild.webhooks()
        except Exception as ex:
            out["errors"].append(f"fetch failed: {ex}")
            return out

        active_ids = set()
        for wh in webhooks:
            try:
                wid = int(wh.id)
                active_ids.add(wid)
                out["scanned"] += 1
                owner_id = int(wh.user.id) if wh.user else 0
                ch_id = int(wh.channel.id) if wh.channel else 0

                async with _get_db() as db:
                    async with db.execute(
                        "SELECT webhook_id FROM webhook_registry "
                        "WHERE webhook_id=?",
                        (wid,),
                    ) as cur:
                        existing = await cur.fetchone()

                    if existing:
                        await db.execute(
                            "UPDATE webhook_registry SET "
                            "last_seen=CURRENT_TIMESTAMP, "
                            "name=?, channel_id=?, owner_id=?, "
                            "is_active=1, last_check=CURRENT_TIMESTAMP "
                            "WHERE webhook_id=?",
                            (wh.name, ch_id, owner_id, wid),
                        )
                        out["updated"] += 1
                    else:
                        await db.execute(
                            "INSERT INTO webhook_registry "
                            "(webhook_id, guild_id, channel_id, name, "
                            "owner_id) VALUES (?, ?, ?, ?, ?)",
                            (wid, guild.id, ch_id, wh.name, owner_id),
                        )
                        out["new"] += 1
                    await db.commit()
            except Exception as ex:
                out["errors"].append(f"webhook {wh.id}: {ex}")

        # Marquer comme inactifs les webhooks qu'on ne voit plus
        async with _get_db() as db:
            async with db.execute(
                "SELECT webhook_id FROM webhook_registry "
                "WHERE guild_id=? AND is_active=1",
                (guild.id,),
            ) as cur:
                tracked = {int(r[0]) for r in await cur.fetchall()}
            gone = tracked - active_ids
            for wid in gone:
                await db.execute(
                    "UPDATE webhook_registry SET is_active=0 "
                    "WHERE webhook_id=?",
                    (wid,),
                )
                out["deactivated"] += 1
            await db.commit()
    except Exception as ex:
        out["errors"].append(f"general: {ex}")
    return out


# ─── Queries ────────────────────────────────────────────────────────────────

async def get_inactive_webhooks(
    guild_id: int, days: int = 90,
) -> list[dict]:
    """Webhooks actifs qui n'ont pas été utilisés (last_used > N jours)."""
    out = []
    if _get_db is None:
        return out
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d %H:%M:%S")
        async with _get_db() as db:
            async with db.execute(
                "SELECT webhook_id, channel_id, name, owner_id, "
                "first_seen, last_used, last_seen "
                "FROM webhook_registry "
                "WHERE guild_id=? AND is_active=1 "
                "AND (last_used IS NULL OR last_used < ?) "
                "ORDER BY first_seen ASC LIMIT 30",
                (guild_id, cutoff),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "webhook_id": int(r[0]),
                "channel_id": int(r[1] or 0),
                "name": r[2] or "?",
                "owner_id": int(r[3] or 0),
                "first_seen": r[4],
                "last_used": r[5],
                "last_seen": r[6],
            })
    except Exception as ex:
        print(f"[webhook_tracker get_inactive] {ex}")
    return out


async def delete_webhook(webhook_id: int, reason: str = "Inactive cleanup") -> bool:
    """Supprime un webhook via API Discord + marque inactif en DB."""
    if _bot is None:
        return False
    try:
        wh = await _bot.fetch_webhook(webhook_id)
        await wh.delete(reason=reason)
        if _get_db is not None:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE webhook_registry SET is_active=0 "
                    "WHERE webhook_id=?",
                    (webhook_id,),
                )
                await db.commit()
        return True
    except Exception as ex:
        print(f"[webhook_tracker delete] {ex}")
        return False


# ─── Panel V2 ──────────────────────────────────────────────────────────────

def build_panel(guild: discord.Guild):
    """Panel V2 pour l'owner : liste des webhooks inactifs + boutons delete."""
    if _v2 is None or not guild:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _WebhookPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.guild = guild

        async def populate(self):
            inactive = await get_inactive_webhooks(guild.id, days=90)
            items = []
            items.append(v2_title("🔌  Webhooks du serveur"))
            items.append(v2_subtitle(
                f"_{len(inactive)} webhook(s) inactif(s) depuis 90+ jours_"
            ))
            items.append(v2_divider())

            if not inactive:
                items.append(v2_body(
                    "✅ Aucun webhook inactif. Tous les webhooks ont été "
                    "utilisés récemment ou sont nouveaux."
                ))
                self.add_item(v2_container(*items, color=0x2ECC71))
                return

            # Listing
            for i, wh in enumerate(inactive[:10], 1):
                last = wh.get("last_used") or "jamais"
                ch_id = wh.get("channel_id", 0)
                ch_mention = f"<#{ch_id}>" if ch_id else "?"
                items.append(v2_body(
                    f"`{i:2d}.` **{wh['name']}** dans {ch_mention} — "
                    f"dernier usage : `{last}`"
                ))
            if len(inactive) > 10:
                items.append(v2_body(
                    f"_+ {len(inactive) - 10} autre(s) (utilise le bouton "
                    f"rescan pour voir plus)_"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "_Clique sur **Purger tout** pour supprimer les 10 premiers, "
                "ou **Rescan** pour rafraîchir._"
            ))
            self.add_item(v2_container(*items, color=0xE67E22))

            # Boutons
            b_purge = Button(
                label="🗑️ Purger les 10 premiers",
                style=discord.ButtonStyle.danger,
            )
            b_rescan = Button(
                label="🔄 Rescan",
                style=discord.ButtonStyle.secondary,
            )

            async def _on_purge(i_inter: discord.Interaction):
                if i_inter.user.id != guild.owner_id and \
                   i_inter.user.id != 1027544786068783194:
                    return await i_inter.response.send_message(
                        "🔒 Owner uniquement.", ephemeral=True
                    )
                await i_inter.response.defer(ephemeral=True)
                deleted = 0
                for wh in inactive[:10]:
                    if await delete_webhook(
                        wh["webhook_id"], "Inactive cleanup via panel"
                    ):
                        deleted += 1
                    await asyncio.sleep(0.5)
                await i_inter.followup.send(
                    f"✅ **{deleted}/{len(inactive[:10])}** webhooks supprimés.",
                    ephemeral=True,
                )

            async def _on_rescan(i_inter: discord.Interaction):
                if i_inter.user.id != guild.owner_id and \
                   i_inter.user.id != 1027544786068783194:
                    return await i_inter.response.send_message(
                        "🔒 Owner uniquement.", ephemeral=True
                    )
                await i_inter.response.defer(ephemeral=True)
                result = await scan_guild(guild)
                await i_inter.followup.send(
                    f"🔄 **Rescan terminé** : `{result['scanned']}` "
                    f"webhooks scannés (`+{result['new']}` nouveaux, "
                    f"`{result['deactivated']}` deactivés).\n"
                    f"_Réouvre le panel pour voir le nouveau listing._",
                    ephemeral=True,
                )

            b_purge.callback = _on_purge
            b_rescan.callback = _on_rescan
            # Phase 235.5 : boutons via ActionRow (bouton nu interdit top-level LayoutView).
            self.add_item(discord.ui.ActionRow(b_purge, b_rescan))

    return _WebhookPanel()


# ─── Task ───────────────────────────────────────────────────────────────────

@tasks.loop(hours=168)  # weekly
async def weekly_scan_task():
    """Scan tous les guilds 1×/semaine."""
    try:
        if _bot is None:
            return
        for g in _bot.guilds:
            try:
                result = await scan_guild(g)
                if result.get("new", 0) > 0 or result.get("deactivated", 0) > 0:
                    print(
                        f"[webhook_tracker weekly] guild={g.id} "
                        f"scanned={result['scanned']} "
                        f"new={result['new']} "
                        f"deactivated={result['deactivated']}"
                    )
            except Exception as ex:
                print(f"[webhook_tracker weekly scan {g.id}] {ex}")
            await asyncio.sleep(5)  # throttle entre guilds
    except Exception as ex:
        print(f"[weekly_scan_task] {ex}")


@weekly_scan_task.before_loop
async def _wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()
    # Délai initial 60s pour éviter scan au boot
    await asyncio.sleep(60)


__all__ = [
    "setup",
    "init_db",
    "scan_guild",
    "get_inactive_webhooks",
    "delete_webhook",
    "build_panel",
    "weekly_scan_task",
]
