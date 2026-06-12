"""
mod_dashboard.py — Dashboard staff modération (Phase 130).

Affiche un panneau V2 magnifique avec :
- 📊 Stats globales modération (warn/mute/direction count sur 30j)
- 🛡️ Top staff par nb de sanctions (qui modère le plus)
- 📝 Types d'infractions les plus fréquents
- 👥 Top membres sanctionnés (récidivistes)
- ⏱️ Activité récente (dernières 24h)

Aussi exporté : REASON_TEMPLATES (liste de raisons préformatées pour
/mod warn et /mod mute — usage futur).

Usage dans bot.py :
    import mod_dashboard

    mod_dashboard.setup(get_db, v2_helpers)

    @owner_group.command(name="mod_stats")
    async def owner_mod_stats(i):
        await mod_dashboard.show(i)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Configuration ───────────────────────────────────────────────────────
WINDOW_DAYS = 30           # Période de stats (par défaut 30 jours)
TOP_STAFF_LIMIT = 5        # Top 5 staff
TOP_OFFENDERS_LIMIT = 5    # Top 5 membres sanctionnés
RECENT_ACTIVITY_HOURS = 24 # Activité dernière journée
RECENT_ACTIONS_LIMIT = 8   # Journal "actions récentes" : N dernières sanctions du serveur


# Raison templates — usables comme app_commands.Choice futurement
REASON_TEMPLATES = [
    ("spam",          "📨 Spam / flood"),
    ("toxic",         "🤬 Toxicité / insultes"),
    ("off_topic",     "🎯 Off-topic / hors-sujet"),
    ("nsfw",          "🔞 NSFW / contenu inapproprié"),
    ("ad",            "📢 Publicité non autorisée"),
    ("harassment",    "😡 Harcèlement"),
    ("rule_break",    "📜 Non-respect des règles"),
    ("provocation",   "🔥 Provocation"),
    ("inappropriate", "❌ Comportement inapproprié"),
    ("other",         "❓ Autre (voir notes)"),
]


# Références injectées
_get_db = None
_v2_helpers = None


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module avec get_db + helpers V2."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# QUERIES
# ═══════════════════════════════════════════════════════════════════════════════

async def _collect_stats(guild_id: int, days: int = WINDOW_DAYS) -> dict:
    """Agrège les stats de modération sur N derniers jours.

    Retourne :
        {
            "total": int,
            "by_type": dict[str, int],
            "top_staff": list[{"mod_id", "count"}],
            "top_offenders": list[{"user_id", "count"}],
            "recent_24h": int,
            "active_warns": int,  # warns sans unwarn
            "recent_actions": list[{"type", "user_id", "mod_id", "reason", "created_at"}],
            "window_days": int,
        }
    """
    out = {
        "total": 0,
        "by_type": {},
        "top_staff": [],
        "top_offenders": [],
        "recent_24h": 0,
        "active_warns": 0,
        "recent_actions": [],
        "window_days": days,
    }
    if _get_db is None:
        return out

    # Format ALIGNÉ sur CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS', espace, sans fuseau) —
    # comme tickets_enhance. .isoformat() (séparateur 'T' + offset) faussait la comparaison
    # lexicographique au jour-frontière : recent_24h sous-comptait tout le jour du cutoff.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=RECENT_ACTIVITY_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        async with _get_db() as db:
            # Total + breakdown par type
            async with db.execute(
                "SELECT type, COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ? "
                "GROUP BY type ORDER BY COUNT(*) DESC",
                (guild_id, cutoff),
            ) as cur:
                rows = await cur.fetchall()
            for typ, cnt in rows:
                out["by_type"][typ or "unknown"] = int(cnt)
                out["total"] += int(cnt)

            # Top staff
            async with db.execute(
                "SELECT mod_id, COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ? AND mod_id IS NOT NULL "
                "GROUP BY mod_id ORDER BY COUNT(*) DESC LIMIT ?",
                (guild_id, cutoff, TOP_STAFF_LIMIT),
            ) as cur:
                out["top_staff"] = [
                    {"mod_id": int(r[0]), "count": int(r[1])}
                    for r in await cur.fetchall()
                    if r[0]
                ]

            # Top membres sanctionnés
            async with db.execute(
                "SELECT user_id, COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ? "
                "GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT ?",
                (guild_id, cutoff, TOP_OFFENDERS_LIMIT),
            ) as cur:
                out["top_offenders"] = [
                    {"user_id": int(r[0]), "count": int(r[1])}
                    for r in await cur.fetchall()
                ]

            # Activité 24h
            async with db.execute(
                "SELECT COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ?",
                (guild_id, cutoff_24h),
            ) as cur:
                row = await cur.fetchone()
            out["recent_24h"] = int(row[0] or 0) if row else 0

            # Warns "actifs" (toutes infractions de type 'warn' sur la période)
            async with db.execute(
                "SELECT COUNT(*) FROM infractions "
                "WHERE guild_id=? AND type='warn' AND created_at >= ?",
                (guild_id, cutoff),
            ) as cur:
                row = await cur.fetchone()
            out["active_warns"] = int(row[0] or 0) if row else 0

            # Journal "actions récentes" : les N dernières sanctions du serveur, tous
            # types confondus, pour que le staff voie l'activité de modé d'un coup d'œil.
            # Tri par id DESC (PK autoincrement) → ordre d'insertion fiable, même si deux
            # sanctions partagent la même seconde dans created_at. Pas de fenêtre temporelle
            # ici : on veut TOUJOURS les dernières, même si le serveur est calme.
            async with db.execute(
                "SELECT type, user_id, mod_id, reason, created_at FROM infractions "
                "WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, RECENT_ACTIONS_LIMIT),
            ) as cur:
                out["recent_actions"] = [
                    {
                        "type": r[0] or "unknown",
                        "user_id": int(r[1]) if r[1] is not None else None,
                        "mod_id": int(r[2]) if r[2] is not None else None,
                        "reason": r[3] or "",
                        "created_at": r[4] or "",
                    }
                    for r in await cur.fetchall()
                ]
    except Exception as ex:
        print(f"[mod_dashboard _collect_stats guild={guild_id}] {ex}")

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING
# ═══════════════════════════════════════════════════════════════════════════════

def _build_layout(stats: dict, guild, tickets: dict | None = None) -> discord.ui.LayoutView | None:
    """Construit le LayoutView V2 du dashboard. `tickets` = stats tickets optionnelles."""
    if _v2_helpers is None:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    type_emojis = {
        "warn":      "⚠️",
        "mute":      "🔇",
        "direction": "🔒",
        "ban":       "🔨",
        "kick":      "👢",
        "unwarn":    "✅",
        "unmute":    "🔊",
    }

    class _ModDashboardLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []

            items.append(v2_title("🛡️ Modération"))
            items.append(v2_subtitle(
                f"{stats['window_days']} derniers jours · {guild.name}"
            ))
            items.append(v2_divider())

            # Stats globales
            items.append(v2_body("### 📊 Activité globale"))
            items.append(v2_body(
                f"📋 **Total** `{stats['total']}` · "
                f"⏱️ **24h** `{stats['recent_24h']}` · "
                f"⚠️ **Warns** `{stats['active_warns']}`"
            ))

            # Breakdown par type
            if stats["by_type"]:
                items.append(v2_divider())
                items.append(v2_body("### 📝 Par type"))
                lines = []
                for typ, cnt in sorted(
                    stats["by_type"].items(), key=lambda x: -x[1]
                ):
                    emo = type_emojis.get(typ, "▫️")
                    lines.append(f"{emo} **{typ}** : `{cnt}`")
                items.append(v2_body("\n".join(lines)))

            # Top staff
            if stats["top_staff"]:
                items.append(v2_divider())
                items.append(v2_body("### 🛡️ TOP STAFF"))
                medals = ["🥇", "🥈", "🥉", "▪️", "▪️"]
                lines = []
                for idx, s in enumerate(stats["top_staff"][:TOP_STAFF_LIMIT]):
                    medal = medals[idx] if idx < 5 else "▪️"
                    lines.append(
                        f"{medal} <@{s['mod_id']}> · `{s['count']}` sanction(s)"
                    )
                items.append(v2_body("\n".join(lines)))

            # Top offenders (récidivistes)
            if stats["top_offenders"]:
                items.append(v2_divider())
                items.append(v2_body(
                    "### 👥 TOP RÉCIDIVISTES"
                ))
                lines = []
                for o in stats["top_offenders"][:TOP_OFFENDERS_LIMIT]:
                    warning = " ⚠️" if o["count"] >= 5 else ""
                    lines.append(
                        f"• <@{o['user_id']}> · `{o['count']}` sanction(s){warning}"
                    )
                items.append(v2_body("\n".join(lines)))

            # 🕑 Actions récentes — journal chronologique des dernières sanctions.
            # Complète les stats agrégées : le staff voit QUI a sanctionné QUI et POURQUOI,
            # pas juste des compteurs. Lecture seule (aucun bouton/action ici).
            if stats.get("recent_actions"):
                items.append(v2_divider())
                items.append(v2_body("### 🕑 Actions récentes"))
                lines = []
                for a in stats["recent_actions"]:
                    emo = type_emojis.get(a.get("type"), "▫️")
                    typ = a.get("type") or "?"
                    cible = f"<@{a['user_id']}>" if a.get("user_id") else "?"
                    par = f" · par <@{a['mod_id']}>" if a.get("mod_id") else ""
                    # created_at = 'YYYY-MM-DD HH:MM:SS' (UTC, comme CURRENT_TIMESTAMP).
                    # On le rend en timestamp Discord relatif (<t:…:R>) → localisé par client,
                    # zéro calcul de fuseau côté bot. Parse défensif : si ça échoue, on omet.
                    when = ""
                    raw = a.get("created_at") or ""
                    if raw:
                        try:
                            dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(
                                tzinfo=timezone.utc
                            )
                            when = f" · <t:{int(dt.timestamp())}:R>"
                        except Exception:
                            when = ""
                    # Raison tronquée + nettoyée (évite de casser le markdown V2).
                    reason = (a.get("reason") or "").replace("\n", " ").strip()
                    if len(reason) > 60:
                        reason = reason[:57] + "…"
                    reason_txt = f"\n  ↳ _{reason}_" if reason else ""
                    lines.append(f"{emo} **{typ}** {cible}{par}{when}{reason_txt}")
                items.append(v2_body("\n".join(lines)))

            # 🎫 Tickets (Lot 4 — "dashboard staff = tickets + sanctions")
            if tickets:
                items.append(v2_divider())
                items.append(v2_body("### 🎫 TICKETS"))
                unclaimed = int(tickets.get("unclaimed", 0) or 0)
                unclaimed_txt = f" · 🙋 `{unclaimed}` non pris en charge" if unclaimed else ""
                items.append(v2_body(
                    f"🟢 **Ouverts :** `{tickets.get('open', 0)}`{unclaimed_txt}\n"
                    f"✅ **Fermés :** `{tickets.get('closed', 0)}`\n"
                    f"🆕 **7 derniers jours :** `{tickets.get('recent_7d', 0)}`"
                ))
                t_staff = tickets.get("top_staff") or []
                if t_staff:
                    medals = ["🥇", "🥈", "🥉", "▪️", "▪️"]
                    lines = []
                    for idx, s in enumerate(t_staff[:5]):
                        medal = medals[idx] if idx < 5 else "▪️"
                        lines.append(f"{medal} <@{s['user_id']}> · `{s['count']}` ticket(s)")
                    items.append(v2_body("**🛡️ Top support :**\n" + "\n".join(lines)))

            # Cas où aucune activité
            if stats["total"] == 0:
                items.append(v2_divider())
                items.append(v2_body(
                    "✨ **Période calme !**\n\n"
                    "_Aucune sanction sur cette période. Le serveur est propre._"
                ))

            items.append(v2_divider())
            items.append(v2_body(
                "-# Exporte un instantané du serveur via les boutons"
            ))

            self.add_item(v2_container(*items, color=0x9B59B6))

            # Lot 4 — Export owner (lecture seule). Boutons NUS → ActionRow obligatoire
            # (un bouton ne peut pas être un enfant top-level d'une LayoutView). La vue
            # est éphémère (timeout=300), donc un callback lié suffit (pas de DynamicItem).
            # Lazy import d'owner_export → zéro couplage d'ordre d'import.
            try:
                btn_json = discord.ui.Button(
                    label="Export JSON", emoji="📤",
                    style=discord.ButtonStyle.secondary,
                    custom_id="modash_export_json",
                )
                btn_csv = discord.ui.Button(
                    label="Export CSV", emoji="📊",
                    style=discord.ButtonStyle.secondary,
                    custom_id="modash_export_csv",
                )

                async def _cb_json(inter: discord.Interaction):
                    try:
                        import owner_export as _oe
                        await _oe.send_export(inter, fmt="json")
                    except Exception as _ex:
                        print(f"[mod_dashboard export json] {_ex}")

                async def _cb_csv(inter: discord.Interaction):
                    try:
                        import owner_export as _oe
                        await _oe.send_export(inter, fmt="csv")
                    except Exception as _ex:
                        print(f"[mod_dashboard export csv] {_ex}")

                btn_json.callback = _cb_json
                btn_csv.callback = _cb_csv
                self.add_item(discord.ui.ActionRow(btn_json, btn_csv))
            except Exception as _ex:
                print(f"[mod_dashboard export buttons] {_ex}")

    return _ModDashboardLayout()


async def show(interaction: discord.Interaction, days: int = WINDOW_DAYS) -> bool:
    """Affiche le dashboard à l'utilisateur (ephemeral).

    Returns True si envoyé avec succès.
    """
    if not interaction.guild:
        try:
            await interaction.response.send_message(
                "❌ Serveur uniquement.", ephemeral=True
            )
        except Exception:
            pass
        return False

    try:
        stats = await _collect_stats(interaction.guild.id, days=days)
        # Lot 4 : agrège AUSSI les tickets (réutilise tickets_enhance, déjà setup au boot).
        # Défensif : si le module/table manque, le dashboard s'affiche sans la section.
        tickets = None
        try:
            import tickets_enhance as _tix
            tickets = await _tix.collect_ticket_stats(interaction.guild.id)
        except Exception as _tex:
            print(f"[mod_dashboard tickets] {_tex}")
        view = _build_layout(stats, interaction.guild, tickets=tickets)
        if view is None:
            await interaction.response.send_message(
                "❌ Dashboard indisponible (module non initialisé).",
                ephemeral=True,
            )
            return False

        if not interaction.response.is_done():
            await interaction.response.send_message(view=view, ephemeral=True)
        else:
            await interaction.followup.send(view=view, ephemeral=True)
        return True
    except Exception as ex:
        print(f"[mod_dashboard show] {ex}")
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
    "show",
    "REASON_TEMPLATES",
    "WINDOW_DAYS",
]
