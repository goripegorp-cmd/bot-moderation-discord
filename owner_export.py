"""owner_export.py — export de la modération en fichier (JSON / CSV) pour l'owner.

Instantané LECTURE SEULE envoyé en pièce jointe ÉPHÉMÈRE depuis les boutons du tableau de
modération (mod_dashboard.py, import paresseux → send_export). Aucune commande slash.

Contenu (30 derniers jours) :
  • total des sanctions et répartition par type ;
  • les 25 membres les plus sanctionnés (IDs + pseudos déjà visibles du staff).
(19/10/2026 : l'économie, les niveaux et le score d'activité ont disparu du serveur ; l'export
ne parle plus que de ce qui existe.)

Wiring (bot.py on_ready) :
    owner_export_module.setup(get_db, SUPER_OWNER_ID)
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import discord

_get_db = None
_super_owner_id = 0

_TOP_N = 25
_MOD_WINDOW_DAYS = 30


def setup(get_db_fn, super_owner_id: int = 0):
    global _get_db, _super_owner_id
    _get_db = get_db_fn
    _super_owner_id = int(super_owner_id or 0)


def _is_owner(interaction: discord.Interaction) -> bool:
    g = interaction.guild
    if g is None:
        return False
    return interaction.user.id == g.owner_id or interaction.user.id == _super_owner_id


def _name_of(guild, user_id: int) -> str:
    m = guild.get_member(int(user_id)) if guild else None
    return m.display_name if m else f"user_{user_id}"


async def _build_snapshot(guild) -> dict:
    """Agrège un instantané LECTURE SEULE. Chaque section est défensive."""
    snap: dict = {
        "meta": {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "member_count": getattr(guild, "member_count", None),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window_days": _MOD_WINDOW_DAYS,
        },
        "moderation_30d": {"total": 0, "by_type": {}},
        "top_members_30d": [],
    }
    if _get_db is None:
        snap["error"] = "module non initialisé"
        return snap

    gid = guild.id
    # Format ALIGNÉ sur CURRENT_TIMESTAMP de SQLite ('YYYY-MM-DD HH:MM:SS', espace, sans
    # fuseau) : .isoformat() fausserait la comparaison lexicographique au jour-frontière.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_MOD_WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT type, COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ? GROUP BY type",
                (gid, cutoff),
            ) as cur:
                rows = await cur.fetchall()
        by_type = {(typ or "unknown"): int(cnt) for typ, cnt in rows}
        snap["moderation_30d"] = {"total": sum(by_type.values()), "by_type": by_type}
    except Exception as ex:
        print(f"[owner_export moderation] {ex}")
        snap["moderation_30d"] = {"error": str(ex)}

    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, COUNT(*) AS n FROM infractions "
                "WHERE guild_id=? AND created_at >= ? GROUP BY user_id "
                "ORDER BY n DESC LIMIT ?",
                (gid, cutoff, _TOP_N),
            ) as cur:
                rows = await cur.fetchall()
        snap["top_members_30d"] = [
            {"user_id": int(r[0]), "name": _name_of(guild, r[0]), "infractions": int(r[1] or 0)}
            for r in rows
        ]
    except Exception as ex:
        print(f"[owner_export top] {ex}")
        snap["top_members_30d"] = [{"error": str(ex)}]

    return snap


def _json_file(snap: dict, guild) -> discord.File:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    data = json.dumps(snap, ensure_ascii=False, indent=2)
    return discord.File(io.BytesIO(data.encode("utf-8")), filename=f"moderation_{guild.id}_{ts}.json")


def _csv_file(snap: dict, guild) -> discord.File:
    """CSV plat des membres les plus sanctionnés (tableur-friendly)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(["rank", "user_id", "name", "infractions_30d"])
    for idx, p in enumerate(snap.get("top_members_30d", []), 1):
        if "error" in p:
            continue
        w.writerow([idx, p.get("user_id"), p.get("name"), p.get("infractions")])
    buf = io.BytesIO(sio.getvalue().encode("utf-8-sig"))  # BOM → Excel ouvre l'UTF-8 proprement
    return discord.File(buf, filename=f"moderation_{guild.id}_{ts}.csv")


async def send_export(interaction: discord.Interaction, fmt: str = "json") -> None:
    """Génère et envoie l'export en pièce jointe éphémère. Owner-only, FAIL-SOFT."""
    try:
        if not _is_owner(interaction):
            msg = "❌ Réservé à l'owner du serveur."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        # ACK d'abord (la collecte peut prendre > 3 s sur un gros serveur).
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        snap = await _build_snapshot(guild)
        if fmt == "csv":
            f, label = _csv_file(snap, guild), "CSV (tableur)"
        else:
            f, label = _json_file(snap, guild), "JSON (complet)"

        mod = snap.get("moderation_30d", {})
        membres = [p for p in snap.get("top_members_30d", []) if "error" not in p]
        summary = (
            f"📤 **Export {label}** — `{guild.name}`\n"
            f"• Sanctions sur 30 j : `{mod.get('total', '?')}`\n"
            f"• Membres concernés (25 max) : `{len(membres)}`\n"
            f"_Instantané lecture seule. Fichier joint ci-dessous._"
        )
        await interaction.followup.send(content=summary, file=f, ephemeral=True)
    except Exception as ex:
        print(f"[owner_export send_export] {ex}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Export impossible pour le moment.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Export impossible pour le moment.", ephemeral=True)
        except Exception as ex2:
            print(f"[owner_export reply] {ex2}")


__all__ = ["setup", "send_export"]
