"""
birthday_panel.py — Panel anniversaires hebdo (Phase 166.2).

🎯 OBJECTIF : combler un gap UX. Le système anniversaire existe (table
`birthdays` dans guild_config + slash `/birthday`) mais y a aucun panel
unifié pour voir d'un coup d'œil "qui a son anniv cette semaine ?".

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- get_upcoming_birthdays(guild, days_ahead=7) -> list[dict]
- build_birthday_panel(guild) -> LayoutView

Pas de DB table — lit directement guild_config.birthdays (dict).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
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


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def get_upcoming_birthdays(
    guild: discord.Guild, days_ahead: int = 7,
) -> list[dict]:
    """Renvoie les anniversaires dans les N prochains jours.

    Chaque entry : {user_id, mm_dd, days_until, label}
    """
    out: list[dict] = []
    if not guild or _db_get is None:
        return out
    try:
        cfg_data = await _db_get(guild.id)
        bdays = cfg_data.get("birthdays", {}) or {}
        if not bdays:
            return out

        now = datetime.now(_PARIS_TZ) if _PARIS_TZ else datetime.now(timezone.utc)
        for uid_str, mm_dd in bdays.items():
            try:
                uid = int(uid_str)
                if "-" not in mm_dd:
                    continue
                mm, dd = mm_dd.split("-")
                mm, dd = int(mm), int(dd)
                # Build cette année
                this_year = now.replace(month=mm, day=dd, hour=0,
                                         minute=0, second=0, microsecond=0)
                if this_year < now.replace(hour=0, minute=0, second=0,
                                            microsecond=0):
                    # déjà passé cette année → l'année prochaine
                    next_occurrence = this_year.replace(year=now.year + 1)
                else:
                    next_occurrence = this_year
                days_until = (
                    next_occurrence - now.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                ).days
                if days_until <= days_ahead:
                    out.append({
                        "user_id": uid,
                        "mm_dd": mm_dd,
                        "days_until": days_until,
                        "next_date": next_occurrence,
                    })
            except (ValueError, KeyError):
                continue
        # Sort par days_until croissant
        out.sort(key=lambda x: x["days_until"])
    except Exception as ex:
        print(f"[birthday_panel get_upcoming] {ex}")
    return out


def build_birthday_panel(guild: discord.Guild):
    """Panel V2 affichant les anniversaires de la semaine."""
    if _v2 is None or guild is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _BirthdayPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            upcoming = await get_upcoming_birthdays(guild, days_ahead=7)
            today = [b for b in upcoming if b["days_until"] == 0]
            week = [b for b in upcoming if 0 < b["days_until"] <= 7]

            items = []
            items.append(v2_title("🎂  Anniversaires"))
            items.append(v2_subtitle(
                f"_{len(upcoming)} dans les 7 prochains jours_"
            ))
            items.append(v2_divider())

            if today:
                items.append(v2_body("**🎉  AUJOURD'HUI :**"))
                for b in today:
                    member = guild.get_member(b["user_id"])
                    name = member.mention if member else f"User#{b['user_id']}"
                    items.append(v2_body(f"• {name} 🎂"))
                items.append(v2_divider())

            if week:
                items.append(v2_body("**📅  Cette semaine :**"))
                for b in week:
                    member = guild.get_member(b["user_id"])
                    name = member.display_name if member else f"User#{b['user_id']}"
                    days = b["days_until"]
                    day_label = (
                        "demain" if days == 1 else f"dans {days} jours"
                    )
                    items.append(v2_body(
                        f"• **{name}** — {day_label} "
                        f"(`{b['mm_dd']}`)"
                    ))

            if not upcoming:
                items.append(v2_body(
                    "_Personne n'a son anniv dans la semaine. "
                    "Configure le tien via `/birthday set`._"
                ))

            self.add_item(v2_container(*items, color=0xE91E63))

            # Bouton "Souhaiter à tous" si y a des birthdays today
            if today:
                b_wish = Button(
                    label=f"🎉 Souhaiter à tous ({len(today)})",
                    style=discord.ButtonStyle.success,
                )

                async def _on_wish(i: discord.Interaction):
                    if not i.guild:
                        return await i.response.send_message(
                            "❌ Serveur uniquement.", ephemeral=True
                        )
                    try:
                        cfg_data = await _db_get(i.guild.id)
                        ch_id = int(cfg_data.get("birthday_channel", 0) or 0)
                        ch = i.guild.get_channel(ch_id) if ch_id else None
                        if not ch:
                            return await i.response.send_message(
                                "❌ Salon anniv pas configuré. "
                                "Va dans `/configure` → Welcome → Anniversaires.",
                                ephemeral=True,
                            )
                        mentions = []
                        for b in today:
                            mb = i.guild.get_member(b["user_id"])
                            if mb:
                                mentions.append(mb.mention)
                        if not mentions:
                            return await i.response.send_message(
                                "❌ Aucun membre trouvé.", ephemeral=True
                            )
                        # Cap mentions à 3 (TOS Discord)
                        if len(mentions) > 3:
                            extra = len(mentions) - 3
                            line = (
                                f"🎂 **Joyeux anniversaire à "
                                f"{', '.join(mentions[:3])} et "
                                f"{extra} autre{'s' if extra > 1 else ''} !** 🎉"
                            )
                        else:
                            line = (
                                f"🎂 **Joyeux anniversaire à "
                                f"{', '.join(mentions)} !** 🎉"
                            )
                        await ch.send(
                            line,
                            allowed_mentions=discord.AllowedMentions(
                                users=True, everyone=False, roles=False,
                            ),
                        )
                        await i.response.send_message(
                            f"✅ Souhaits envoyés dans {ch.mention}.",
                            ephemeral=True,
                        )
                    except Exception as ex:
                        print(f"[birthday_panel wish_all] {ex}")
                        try:
                            await i.response.send_message(
                                f"❌ Erreur : `{ex}`", ephemeral=True
                            )
                        except Exception:
                            pass

                b_wish.callback = _on_wish
                # Phase 235.5 : bouton nu → ActionRow (top-level LayoutView).
                self.add_item(discord.ui.ActionRow(b_wish))

    return _BirthdayPanel()


__all__ = [
    "setup",
    "get_upcoming_birthdays",
    "build_birthday_panel",
]
