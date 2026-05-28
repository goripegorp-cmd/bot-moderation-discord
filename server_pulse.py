"""
server_pulse.py — Dashboard live du serveur + Tips Rotator (Phase 162).

🎯 OBJECTIF : donner une vision en temps réel de l'activité serveur,
visible par tous via un bouton hub. Plus la communauté voit l'activité,
plus elle reste engagée.

2 features dans ce module :

1. **Server Pulse** (panel live) :
   - 👥 Membres totaux + online + en vocal
   - 💬 Messages dernière heure (estimation)
   - 🎙️ Vocaux actifs maintenant
   - 🏆 Top contributeur du jour
   - 🔥 Events actifs en ce moment
   - 📊 Saison + saga active
   Auto-refresh via bouton "🔄 Actualiser".

2. **Tips Rotator** :
   - 30+ astuces sur les features du bot
   - Rotation déterministe par jour (pas random — tout le monde voit
     la même astuce le même jour, ça crée des conversations)
   - Affiché dans le hub subtitle ou en panel dédié

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers,
        season_module=None, saga_module=None)
- build_pulse_panel(guild) -> LayoutView
- get_tip_of_the_day() -> str
- build_tip_panel() -> LayoutView
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ui import Button, View

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
_season_module = None
_saga_module = None


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    season_module=None, saga_module=None,
):
    global _bot, _get_db, _db_get, _v2, _season_module, _saga_module
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _season_module = season_module
    _saga_module = saga_module


# ─── Tips catalogue ─────────────────────────────────────────────────────────

TIPS = [
    "🎯 Clique sur les boutons du hub plutôt que d'apprendre les commandes — c'est plus rapide.",
    "🐾 N'oublie pas de nourrir ton pet 1×/jour, il monte en niveau et débloque des skins évolués.",
    "🎰 La Daily Wheel a une chance de jackpot Mythique de **1/1010**. Spin chaque jour !",
    "💎 Les drops saisonniers ne reviennent qu'1× par an. Collecte-les pendant qu'ils sont actifs.",
    "🤝 Si tu as un mentor, ses gains aussi te font progresser (badge Duo après 7 jours).",
    "⭐ La réputation se cumule à jamais — chaque event final t'en donne. 5 tiers à débloquer.",
    "🎰 5 votes daily prompt + 5 quêtes/semaine = 2 tickets loterie minimum. Combo-le !",
    "🔴 Quand le créateur live, le bot crée auto un salon watching avec coins ×2 actifs.",
    "📜 Les sagas hebdo donnent 5000 coins au top 5 contributeurs. Participe aux events.",
    "🛡️ Si tu reçois un DM suspect du bot, vérifie qu'il ne demande PAS ton mot de passe.",
    "🔐 Pour les claims > 5000 coins, le bot demande confirmation par DM. C'est ta protection.",
    "🤜 Le ladder Elo récompense plus de battre plus fort. Vise des adversaires +200 que toi.",
    "🎙️ Chaque minute en vocal = +1 coin (cap 100/jour). Reste social pendant les events.",
    "📊 Bouton 'Objectif communauté' dans le hub — top 3 = +2000 coins.",
    "🧠 Les énigmes daily récompensent le 1er à 500c (+ jusqu'à 1000c bonus si streak 7j).",
    "🎁 Le festival mensuel (1er dimanche) divise les prix shop par 2 pendant 48h.",
    "📰 Bouton 'Mon récap 7j' pour voir tes stats des 7 derniers jours et ton rang.",
    "🏆 Lundi 9h FR : leaderboards publics auto-postés dans le hub. Vise le top 5.",
    "⚔️ Boss raid : le 'last hit' donne un bonus de 500c × multiplier saison + stream.",
    "🌸 Saisons : le bot change d'ambiance 8 fois/an. Chacune débloque des drops uniques.",
    "🔔 Configure tes DMs via /profile → 🔔 Mes DMs — opt-out par catégorie.",
    "📈 Ton style de jeu est détecté auto (PvP/Collector/Social/Solo) — visible dans /profile.",
    "🏰 Crée ou rejoins une alliance — coffre commun + inventaire partagé + buff events.",
    "🎯 Onboarding 5 étapes pour les nouveaux → +5000 coins bonus final.",
    "🍯 Le honeypot anti-bot est invisible — si tu vois un salon suspect, ne poste PAS dedans.",
    "💰 Banque rapporte des intérêts passifs. Mets-y tes coins pour qu'ils grossissent seuls.",
    "🛒 Marketplace P2P : vend tes items en surplus à d'autres joueurs.",
    "🔨 Crafting : 3 items rares même rareté → 1 item de rareté supérieure.",
    "🎨 Repair : tes items perdent de la durabilité au combat. Répare via /repair button.",
    "📜 Hall of Fame : exploits indélébiles — gravés à vie pour les meilleurs.",
]


def get_tip_of_the_day() -> str:
    """Retourne l'astuce du jour (déterministe par jour)."""
    if _PARIS_TZ is not None:
        day_of_year = datetime.now(_PARIS_TZ).timetuple().tm_yday
    else:
        day_of_year = datetime.now(timezone.utc).timetuple().tm_yday
    return TIPS[day_of_year % len(TIPS)]


# ─── Server Pulse ──────────────────────────────────────────────────────────

async def _collect_pulse(guild: discord.Guild) -> dict:
    """Récolte toutes les stats live du serveur."""
    out = {
        "members_total": guild.member_count or 0,
        "members_online": 0,
        "members_voice": 0,
        "voice_active_channels": 0,
        "messages_last_hour": 0,
        "top_contributor_today": None,
        "events_active": [],
        "season_name": None,
        "saga_info": None,
    }
    try:
        # Online members
        try:
            out["members_online"] = sum(
                1 for m in guild.members
                if m.status != discord.Status.offline and not m.bot
            )
        except Exception:
            # Sans Intent presences, on ne peut pas compter
            pass

        # Voice activity
        try:
            voice_users = set()
            for ch in guild.voice_channels:
                if len(ch.members) > 0:
                    out["voice_active_channels"] += 1
                    for m in ch.members:
                        if not m.bot:
                            voice_users.add(m.id)
            out["members_voice"] = len(voice_users)
        except Exception:
            pass

        # Messages last hour (via daily_guild_stats — approximation)
        if _get_db is not None:
            try:
                today = (
                    datetime.now(_PARIS_TZ) if _PARIS_TZ
                    else datetime.now(timezone.utc)
                ).strftime("%Y-%m-%d")
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT total_messages FROM daily_guild_stats "
                        "WHERE guild_id=? AND date=?",
                        (guild.id, today),
                    ) as cur:
                        row = await cur.fetchone()
                if row:
                    # Estimation : msgs jour / 24 = approx msgs/h
                    out["messages_last_hour"] = int((row[0] or 0) / 24)
            except Exception:
                pass

        # Top contributor today (via reputation_history)
        if _get_db is not None:
            try:
                day_cutoff = (
                    (datetime.now(_PARIS_TZ) if _PARIS_TZ
                     else datetime.now(timezone.utc))
                    .replace(hour=0, minute=0, second=0, microsecond=0)
                ).strftime("%Y-%m-%d %H:%M:%S")
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT user_id, SUM(points) AS pts "
                        "FROM reputation_history "
                        "WHERE guild_id=? AND created_at >= ? "
                        "GROUP BY user_id ORDER BY pts DESC LIMIT 1",
                        (guild.id, day_cutoff),
                    ) as cur:
                        row = await cur.fetchone()
                if row:
                    m = guild.get_member(int(row[0]))
                    out["top_contributor_today"] = {
                        "user_id": int(row[0]),
                        "name": m.display_name if m else f"User-{row[0]}",
                        "points": int(row[1] or 0),
                    }
            except Exception:
                pass

        # Season active
        if _season_module is not None:
            try:
                s = _season_module.current_season()
                if s:
                    out["season_name"] = (
                        f"{s.get('emoji', '🌸')} {s.get('name', '?')}"
                    )
            except Exception:
                pass

        # Saga active
        if _saga_module is not None:
            try:
                saga = await _saga_module.get_active_saga(guild.id)
                if saga:
                    pct = int(
                        saga["fragments_collected"] * 100 /
                        max(1, saga["fragments_target"])
                    )
                    out["saga_info"] = {
                        "title": saga["title"],
                        "progress_pct": pct,
                    }
            except Exception:
                pass

        # Events actifs (recherche les salons d'event ouverts)
        try:
            for ch in guild.text_channels:
                n = ch.name.lower()
                if any(k in n for k in ("boss", "arena", "🔴-watching")):
                    if "boss" in n and ch.permissions_for(guild.me).view_channel:
                        out["events_active"].append("⚔️ Boss raid")
                        break
            # Watch party live (Phase 155)
            try:
                import stream_watch_party as swp
                if swp.is_stream_buff_active(guild.id):
                    out["events_active"].append("🔴 Stream live (XP ×2)")
            except Exception:
                pass
            # Festival
            try:
                import coin_economy as ce
                if ce.is_festival_active(guild.id):
                    out["events_active"].append("🎉 Festival prix ×0.5")
            except Exception:
                pass
        except Exception:
            pass

    except Exception as ex:
        print(f"[server_pulse _collect_pulse] {ex}")
    return out


def build_pulse_panel(guild: discord.Guild):
    """Panel V2 live du serveur avec bouton refresh."""
    if _v2 is None or guild is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    class _PulsePanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)

        async def populate(self):
            self.clear_items()
            p = await _collect_pulse(guild)

            items = []
            items.append(v2_title(f"📡  Pulse de {guild.name}"))
            items.append(v2_subtitle(
                f"_Live · {datetime.now().strftime('%H:%M')}_"
            ))
            items.append(v2_divider())

            # Membres
            items.append(v2_body("**👥  Membres**"))
            online_str = (
                f"online : `{p['members_online']:,}`"
                if p['members_online'] > 0
                else "_online indisponible (Intent presences off)_"
            )
            items.append(v2_body(
                f"• Total : `{p['members_total']:,}` · {online_str}\n"
                f"• En vocal : `{p['members_voice']}` "
                f"dans `{p['voice_active_channels']}` salon(s)"
            ))
            items.append(v2_divider())

            # Activité
            items.append(v2_body("**📊  Activité**"))
            items.append(v2_body(
                f"• Messages dernière heure (~) : `{p['messages_last_hour']:,}`"
            ))
            if p.get("top_contributor_today"):
                t = p["top_contributor_today"]
                items.append(v2_body(
                    f"• 🏆 Top du jour : **{t['name']}** "
                    f"(`+{t['points']}` réputation)"
                ))
            items.append(v2_divider())

            # Events
            if p.get("events_active"):
                items.append(v2_body("**🔥  En cours**"))
                for e in p["events_active"]:
                    items.append(v2_body(f"• {e}"))
                items.append(v2_divider())

            # Saison / Saga
            if p.get("season_name") or p.get("saga_info"):
                items.append(v2_body("**🌸  Contexte serveur**"))
                if p.get("season_name"):
                    items.append(v2_body(f"• Saison : {p['season_name']}"))
                if p.get("saga_info"):
                    s = p["saga_info"]
                    items.append(v2_body(
                        f"• Saga : {s['title']} ({s['progress_pct']}%)"
                    ))
                items.append(v2_divider())

            # Tip du jour
            tip = get_tip_of_the_day()
            items.append(v2_body(f"💡 **Astuce du jour**\n_{tip}_"))

            self.add_item(v2_container(*items, color=0x2ECC71))

            # Bouton refresh
            b_refresh = Button(
                label="🔄 Actualiser",
                style=discord.ButtonStyle.primary,
            )

            async def _on_refresh(i: discord.Interaction):
                await self.populate()
                try:
                    await i.response.edit_message(view=self)
                except Exception:
                    try:
                        await i.followup.edit_message(
                            i.message.id, view=self,
                        )
                    except Exception:
                        pass

            b_refresh.callback = _on_refresh
            self.add_item(b_refresh)

    return _PulsePanel()


def build_tip_panel():
    """Panel V2 pour afficher l'astuce du jour en grand."""
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    tip = get_tip_of_the_day()
    items = [
        v2_title("💡  Astuce du jour"),
        v2_subtitle("_Nouvelle astuce chaque jour à minuit Paris_"),
        v2_divider(),
        v2_body(tip),
        v2_divider(),
        v2_body(
            "_Tip rotatif — tous les joueurs voient la même astuce "
            "le même jour. Parfait pour lancer des conversations._"
        ),
    ]

    class _TipPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=180)
            self.add_item(v2_container(*items, color=0xF1C40F))

    return _TipPanel()


__all__ = [
    "setup",
    "build_pulse_panel",
    "build_tip_panel",
    "get_tip_of_the_day",
    "TIPS",
]
