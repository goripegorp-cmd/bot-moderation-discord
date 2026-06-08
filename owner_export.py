"""owner_export.py — export des données serveur en fichier (JSON / CSV) pour l'owner.

GAP comblé (Lot 4) : l'owner recevait un digest quotidien en DM (embed) mais ne pouvait
RIEN exporter en fichier téléchargeable. Ce module produit un instantané AGRÉGÉ
(lecture seule, aucune mutation) et l'envoie en pièce jointe ÉPHÉMÈRE à l'owner depuis
un bouton du dashboard modération — donc AUCUNE nouvelle commande slash.

Contenu (agrégats que l'owner voit déjà ; pas de DM/notes privées/PII au-delà des IDs+
pseudos déjà visibles) :
  • résumé serveur (membres, totaux économie)
  • TOP 25 joueurs par niveau et par pièces
  • TOP 25 activité (score glissant 14 j)
  • modération : total + par type sur 30 j

Robustesse : CHAQUE section est dans son propre try/except → une table manquante n'empêche
jamais l'export (instantané partiel = acceptable). FAIL-SOFT de bout en bout.

Wiring (bot.py on_ready) :
    import owner_export as owner_export_module
    owner_export_module.setup(get_db, SUPER_OWNER_ID)
Le bouton est ajouté par mod_dashboard.py (lazy import → send_export).
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
_ACTIVITY_WINDOW_DAYS = 14
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
        },
        "economy": {},
        "top_by_level": [],
        "top_by_coins": [],
        "activity_14d": [],
        "moderation_30d": {"total": 0, "by_type": {}},
    }
    if _get_db is None:
        snap["error"] = "module non initialisé"
        return snap

    gid = guild.id

    # ── Économie : agrégat global ────────────────────────────────────────
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(coins),0), COALESCE(SUM(bank),0), "
                "COALESCE(MAX(level),0), COALESCE(AVG(level),0) "
                "FROM economy WHERE guild_id=?",
                (gid,),
            ) as cur:
                r = await cur.fetchone()
        if r:
            snap["economy"] = {
                "players_tracked": int(r[0] or 0),
                "total_coins": int(r[1] or 0),
                "total_bank": int(r[2] or 0),
                "max_level": int(r[3] or 0),
                "avg_level": round(float(r[4] or 0), 2),
            }
    except Exception as ex:
        snap["economy"] = {"error": str(ex)}

    # ── TOP par niveau ───────────────────────────────────────────────────
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, level, coins, bank, xp FROM economy "
                "WHERE guild_id=? ORDER BY level DESC, xp DESC LIMIT ?",
                (gid, _TOP_N),
            ) as cur:
                rows = await cur.fetchall()
        snap["top_by_level"] = [
            {"user_id": int(r[0]), "name": _name_of(guild, r[0]),
             "level": int(r[1] or 0), "coins": int(r[2] or 0),
             "bank": int(r[3] or 0), "xp": int(r[4] or 0)}
            for r in rows
        ]
    except Exception as ex:
        snap["top_by_level"] = [{"error": str(ex)}]

    # ── TOP par pièces ───────────────────────────────────────────────────
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, coins, bank, level FROM economy "
                "WHERE guild_id=? ORDER BY coins DESC LIMIT ?",
                (gid, _TOP_N),
            ) as cur:
                rows = await cur.fetchall()
        snap["top_by_coins"] = [
            {"user_id": int(r[0]), "name": _name_of(guild, r[0]),
             "coins": int(r[1] or 0), "bank": int(r[2] or 0),
             "level": int(r[3] or 0)}
            for r in rows
        ]
    except Exception as ex:
        snap["top_by_coins"] = [{"error": str(ex)}]

    # ── Activité (score glissant 14 j) ───────────────────────────────────
    try:
        cutoff_day = (datetime.now(timezone.utc) - timedelta(days=_ACTIVITY_WINDOW_DAYS)).strftime("%Y-%m-%d")
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, SUM(points) AS p FROM activity_score "
                "WHERE guild_id=? AND day >= ? GROUP BY user_id "
                "ORDER BY p DESC LIMIT ?",
                (gid, cutoff_day, _TOP_N),
            ) as cur:
                rows = await cur.fetchall()
        snap["activity_14d"] = [
            {"user_id": int(r[0]), "name": _name_of(guild, r[0]), "points": int(r[1] or 0)}
            for r in rows
        ]
    except Exception as ex:
        snap["activity_14d"] = [{"error": str(ex)}]

    # ── Modération (30 j) ────────────────────────────────────────────────
    try:
        # Format ALIGNÉ sur CURRENT_TIMESTAMP de SQLite ('YYYY-MM-DD HH:MM:SS', espace,
        # sans fuseau). .isoformat() mettrait un 'T' + offset → comparaison lexicographique
        # faussée au jour-frontière (piège datetime naïf, cf. MEMORY Phase 250).
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_MOD_WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        async with _get_db() as db:
            async with db.execute(
                "SELECT type, COUNT(*) FROM infractions "
                "WHERE guild_id=? AND created_at >= ? GROUP BY type",
                (gid, cutoff),
            ) as cur:
                rows = await cur.fetchall()
        by_type = {}
        total = 0
        for typ, cnt in rows:
            by_type[typ or "unknown"] = int(cnt)
            total += int(cnt)
        snap["moderation_30d"] = {"total": total, "by_type": by_type}
    except Exception as ex:
        snap["moderation_30d"] = {"error": str(ex)}

    return snap


def _json_file(snap: dict, guild) -> discord.File:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    data = json.dumps(snap, ensure_ascii=False, indent=2)
    buf = io.BytesIO(data.encode("utf-8"))
    return discord.File(buf, filename=f"abylumis_{guild.id}_{ts}.json")


def _csv_file(snap: dict, guild) -> discord.File:
    """CSV plat des TOP joueurs (tableur-friendly)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(["section", "rank", "user_id", "name", "level", "coins", "bank", "xp", "points"])
    for idx, p in enumerate(snap.get("top_by_level", []), 1):
        if "error" in p:
            continue
        w.writerow(["top_by_level", idx, p.get("user_id"), p.get("name"),
                    p.get("level"), p.get("coins"), p.get("bank"), p.get("xp"), ""])
    for idx, p in enumerate(snap.get("top_by_coins", []), 1):
        if "error" in p:
            continue
        w.writerow(["top_by_coins", idx, p.get("user_id"), p.get("name"),
                    p.get("level"), p.get("coins"), p.get("bank"), "", ""])
    for idx, p in enumerate(snap.get("activity_14d", []), 1):
        if "error" in p:
            continue
        w.writerow(["activity_14d", idx, p.get("user_id"), p.get("name"),
                    "", "", "", "", p.get("points")])
    buf = io.BytesIO(sio.getvalue().encode("utf-8-sig"))  # BOM → Excel ouvre l'UTF-8 proprement
    return discord.File(buf, filename=f"abylumis_{guild.id}_{ts}.csv")


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
            f = _csv_file(snap, guild)
            label = "CSV (tableur)"
        else:
            f = _json_file(snap, guild)
            label = "JSON (complet)"

        eco = snap.get("economy", {})
        summary = (
            f"📤 **Export {label}** — `{guild.name}`\n"
            f"• Joueurs suivis : `{eco.get('players_tracked', '?')}`\n"
            f"• Pièces totales : `{eco.get('total_coins', '?')}` · Banque : `{eco.get('total_bank', '?')}`\n"
            f"• Sanctions 30 j : `{snap.get('moderation_30d', {}).get('total', '?')}`\n"
            f"_Instantané lecture seule. Fichier joint ci-dessous._"
        )
        await interaction.followup.send(content=summary, file=f, ephemeral=True)
    except Exception as ex:
        print(f"[owner_export send_export] {ex}")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Export impossible : `{ex}`", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Export impossible : `{ex}`", ephemeral=True)
        except Exception:
            pass


__all__ = ["setup", "send_export"]
