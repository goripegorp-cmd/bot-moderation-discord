"""
alliance_war.py — Tournoi PvP Alliance vs Alliance (Phase 254).

Deux alliances s'affrontent dans un duel à barres de PV. Le panneau live (Components
V2) affiche les 2 barres + une ZONE ATTAQUE (⚔️) et une ZONE DÉFENSE (🛡️) :
  • Attaquer = inflige des dégâts (selon l'ATK d'équipement du joueur) à l'alliance ADVERSE.
  • Défendre = rend des PV à SON alliance (selon la DEF d'équipement).
La 1ʳᵉ alliance tombée à 0 PV PERD ; l'autre gagne (récompense modeste à ses membres).

Combat 100 % TEXTE. Garde-fous Discord (cf. mémoire projet) :
  • cooldown PAR JOUEUR vérifié AVANT tout réseau (anti-429) ;
  • refresh du panneau THROTTLÉ via get_partial_message (PATCH seul, pas de GET) ;
  • boutons PERSISTANTS (DynamicItem) → survivent aux reboots ;
  • bouton NU dans le panneau + DynamicItem enregistré à part (un DynamicItem ne peut PAS
    être dans un ActionRow d'une LayoutView) ;
  • fin de tournoi ATOMIQUE (UPDATE ... WHERE status='active' + rowcount) → pas de double
    récompense ;
  • TOUT fail-open : une erreur n'interrompt jamais le combat.

Lancement : /owner tournoi alliance1 alliance2 (owner/admin).

API : setup(...), init_db(), start_war(guild, a_id, b_id, channel), record_action via
les boutons, register_persistent_views(bot), boot_cleanup().
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ui import Button

# ─── Dépendances injectées (toutes via setup, fail-open si None) ─────────────
_bot = None
_get_db = None
_v2 = None
_add_coins = None
_get_alliance_by_id = None     # async (guild_id, alliance_id) -> {id, name, emoji} | None
_get_user_alliance_id = None   # async (guild_id, user_id) -> alliance_id | None
_inventory_fn = None           # async (guild_id, user_id) -> inv dict
_gear_stats = None             # callable(inv) -> {atk, def, ...}

# ─── Réglages ────────────────────────────────────────────────────────────────
_WAR_MAX_HP = 5000
_ACTION_CD = 3.0               # cooldown par joueur (s) — anti-spam / anti-429
_REFRESH_MIN = 4.0             # throttle du refresh de panneau (s)
_WIN_REWARD = 500              # pièces par PARTICIPANT de l'alliance gagnante (modeste)
_WAR_COOLDOWN_HOURS = 6.0      # Phase 255 (audit) : délai mini entre 2 tournois pour
                               # une même alliance — anti-farm (start→end→start en boucle).

_last_action: dict = {}        # {(war_id, user_id): epoch}
_last_refresh: dict = {}       # {war_id: epoch}


def setup(bot_instance, get_db_fn, v2_helpers: dict, add_coins_fn=None,
          alliance_by_id_fn=None, user_alliance_id_fn=None,
          inventory_fn=None, gear_stats_fn=None):
    global _bot, _get_db, _v2, _add_coins, _get_alliance_by_id
    global _get_user_alliance_id, _inventory_fn, _gear_stats
    _bot = bot_instance
    _get_db = get_db_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _get_alliance_by_id = alliance_by_id_fn
    _get_user_alliance_id = user_alliance_id_fn
    _inventory_fn = inventory_fn
    _gear_stats = gear_stats_fn
    try:
        bot_instance.add_dynamic_items(AllianceWarButton)
    except Exception:
        pass


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS alliance_wars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    a_id INTEGER, a_name TEXT, a_emoji TEXT,
                    b_id INTEGER, b_name TEXT, b_emoji TEXT,
                    hp_a INTEGER, hp_b INTEGER, max_hp INTEGER,
                    channel_id INTEGER, message_id INTEGER,
                    status TEXT DEFAULT 'active',
                    winner_id INTEGER,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP
                )
            """)
            # Phase 255 (audit) : qui a RÉELLEMENT participé (cliqué ⚔️/🛡️) à chaque
            # tournoi → seuls eux sont payés (avant : toute l'alliance, même les AFK).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS alliance_war_participants (
                    war_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    alliance_id INTEGER,
                    PRIMARY KEY (war_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[alliance_war init_db] {ex}")


def _hp_bar(cur: int, mx: int, width: int = 12) -> str:
    cur = max(0, int(cur or 0))
    mx = max(1, int(mx or 1))
    filled = max(0, min(width, int(round(width * cur / mx))))
    return "█" * filled + "░" * (width - filled)


_WAR_KEYS = ["id", "guild_id", "a_id", "a_name", "a_emoji", "b_id", "b_name",
             "b_emoji", "hp_a", "hp_b", "max_hp", "channel_id", "message_id",
             "status", "winner_id"]


async def _get_war(war_id: int) -> Optional[dict]:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, a_id, a_name, a_emoji, b_id, b_name, b_emoji, "
                "hp_a, hp_b, max_hp, channel_id, message_id, status, winner_id "
                "FROM alliance_wars WHERE id=?", (war_id,)) as c:
                row = await c.fetchone()
        return dict(zip(_WAR_KEYS, row)) if row else None
    except Exception:
        return None


async def _active_war_for_alliance(guild_id: int, alliance_id: int) -> Optional[int]:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM alliance_wars WHERE guild_id=? AND status='active' "
                "AND (a_id=? OR b_id=?) LIMIT 1",
                (guild_id, alliance_id, alliance_id)) as c:
                r = await c.fetchone()
        return int(r[0]) if r else None
    except Exception:
        return None


async def _recent_war_for_alliance(guild_id: int, alliance_id: int) -> bool:
    """Phase 255 (audit) : True si l'alliance a un tournoi actif OU terminé dans la
    fenêtre de cooldown → bloque les boucles start→end→start (farm de pièces)."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM alliance_wars WHERE guild_id=? AND (a_id=? OR b_id=?) "
                "AND julianday('now') - julianday(COALESCE(ended_at, started_at)) < ? "
                "LIMIT 1",
                (guild_id, alliance_id, alliance_id, _WAR_COOLDOWN_HOURS / 24.0)) as c:
                r = await c.fetchone()
        return bool(r)
    except Exception:
        return False


def _build_panel(war: dict):
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    mx = max(1, int(war["max_hp"] or 1))
    a_hp = max(0, int(war["hp_a"] or 0))
    b_hp = max(0, int(war["hp_b"] or 0))
    ended = war["status"] != "active"
    color = 0xF1C40F if ended else 0xE74C3C

    items = [
        v2_title("⚔️  TOURNOI D'ALLIANCES"),
        v2_subtitle("_Attaque l'alliance adverse · Défends la tienne. La 1ʳᵉ à 0 PV perd !_"),
        v2_divider(),
        v2_body(f"{war['a_emoji']} **{war['a_name']}**\n"
                f"`{_hp_bar(a_hp, mx)}`  **{a_hp:,}** / {mx:,} PV  ({int(a_hp * 100 / mx)}%)"),
        v2_body(f"{war['b_emoji']} **{war['b_name']}**\n"
                f"`{_hp_bar(b_hp, mx)}`  **{b_hp:,}** / {mx:,} PV  ({int(b_hp * 100 / mx)}%)"),
    ]
    if ended:
        win = war.get("winner_id")
        if win == war["a_id"]:
            wn, we = war["a_name"], war["a_emoji"]
        else:
            wn, we = war["b_name"], war["b_emoji"]
        items.append(v2_divider())
        items.append(v2_body(f"🏆 **VICTOIRE : {we} {wn} !** Tournoi terminé."))
    else:
        items.append(v2_divider())
        items.append(v2_body("_⚔️ Attaquer = dégâts selon ton **ATK** · "
                             "🛡️ Défendre = PV rendus selon ta **DEF**. Équipe-toi (`/inventory`) !_"))

    war_id = int(war["id"])

    class _WarPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=None)
            self.add_item(v2_container(*items, color=color))
            if not ended:
                # Boutons NUS (custom_id) — captés par le DynamicItem AllianceWarButton.
                _atk = Button(label="⚔️ Attaquer l'adversaire",
                              style=discord.ButtonStyle.danger,
                              custom_id=f"awar:{war_id}:atk")
                _def = Button(label="🛡️ Défendre mon alliance",
                              style=discord.ButtonStyle.success,
                              custom_id=f"awar:{war_id}:def")
                self.add_item(discord.ui.ActionRow(_atk, _def))

    return _WarPanel()


async def _refresh_panel(guild, war_id: int, force: bool = False):
    try:
        if not force:
            now = datetime.now(timezone.utc).timestamp()
            if now - _last_refresh.get(war_id, 0.0) < _REFRESH_MIN:
                return
            _last_refresh[war_id] = now
        war = await _get_war(war_id)
        if not war or not war.get("channel_id") or not war.get("message_id"):
            return
        ch = guild.get_channel(int(war["channel_id"]))
        if not ch:
            return
        await ch.get_partial_message(int(war["message_id"])).edit(view=_build_panel(war))
    except Exception:
        pass


async def start_war(guild, a_id: int, b_id: int, channel) -> dict:
    """Crée + poste un tournoi entre 2 alliances. Retourne {ok, error?, war_id?}."""
    if _get_db is None or _get_alliance_by_id is None or _v2 is None:
        return {"ok": False, "error": "Système indisponible."}
    if int(a_id) == int(b_id):
        return {"ok": False, "error": "Choisis 2 alliances DIFFÉRENTES."}
    a = await _get_alliance_by_id(guild.id, a_id)
    b = await _get_alliance_by_id(guild.id, b_id)
    if not a or not b:
        return {"ok": False, "error": "Alliance introuvable."}
    if await _active_war_for_alliance(guild.id, a_id) or await _active_war_for_alliance(guild.id, b_id):
        return {"ok": False, "error": "Une de ces alliances est déjà dans un tournoi actif."}
    # Phase 255 (audit) : cooldown anti-farm — pas de relance immédiate start→end→start.
    if await _recent_war_for_alliance(guild.id, a_id) or await _recent_war_for_alliance(guild.id, b_id):
        return {"ok": False, "error": f"Une de ces alliances a déjà fait un tournoi il y a moins de {int(_WAR_COOLDOWN_HOURS)} h — réessaie plus tard."}
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO alliance_wars (guild_id, a_id, a_name, a_emoji, b_id, b_name, "
                "b_emoji, hp_a, hp_b, max_hp, channel_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (guild.id, int(a_id), a.get("name", "Alliance A"), a.get("emoji", "🤝"),
                 int(b_id), b.get("name", "Alliance B"), b.get("emoji", "🤝"),
                 _WAR_MAX_HP, _WAR_MAX_HP, _WAR_MAX_HP, channel.id))
            war_id = cur.lastrowid
            await db.commit()
        war = await _get_war(war_id)
        msg = await channel.send(view=_build_panel(war))
        async with _get_db() as db:
            await db.execute("UPDATE alliance_wars SET message_id=? WHERE id=?",
                             (msg.id, war_id))
            await db.commit()
        return {"ok": True, "war_id": war_id}
    except Exception as ex:
        print(f"[alliance_war start_war] {ex}")
        return {"ok": False, "error": f"Erreur : {ex}"}


async def _record_action(i: discord.Interaction, war_id: int, kind: str):
    # Cooldown PAR JOUEUR EN TÊTE, avant tout appel réseau (anti-429).
    try:
        key = (war_id, i.user.id)
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_action.get(key, 0.0) < _ACTION_CD:
            return
        _last_action[key] = now
    except Exception:
        pass
    try:
        await i.response.defer(ephemeral=True)
    except Exception:
        pass
    try:
        if i.guild is None:
            return
        war = await _get_war(war_id)
        if not war or war["status"] != "active":
            return await i.followup.send("🔒 Ce tournoi est terminé.", ephemeral=True)
        my_alliance = None
        if _get_user_alliance_id is not None:
            my_alliance = await _get_user_alliance_id(i.guild.id, i.user.id)
        if my_alliance not in (war["a_id"], war["b_id"]):
            return await i.followup.send(
                "🔒 Tu n'es dans **aucune** des 2 alliances de ce tournoi.", ephemeral=True)
        i_am_a = (my_alliance == war["a_id"])
        # Puissance selon l'équipement.
        try:
            inv = await _inventory_fn(i.guild.id, i.user.id) if _inventory_fn else {}
            st = _gear_stats(inv) if _gear_stats else {}
            power = (30 + int(st.get("atk", 0) or 0)) if kind == "atk" \
                else (25 + int(st.get("def", 0) or 0))
        except Exception:
            power = 30 if kind == "atk" else 25
        power = max(1, int(power))
        # Application ATOMIQUE (par statement) — pas de lost-update.
        async with _get_db() as db:
            if kind == "atk":
                col = "hp_b" if i_am_a else "hp_a"
                await db.execute(
                    f"UPDATE alliance_wars SET {col}=MAX(0,{col}-?) "
                    f"WHERE id=? AND status='active'", (power, war_id))
            else:
                col = "hp_a" if i_am_a else "hp_b"
                await db.execute(
                    f"UPDATE alliance_wars SET {col}=MIN(max_hp,{col}+?) "
                    f"WHERE id=? AND status='active'", (power, war_id))
            # Phase 255 (audit) : marque le joueur comme PARTICIPANT (seuls les
            # participants seront payés à la fin — fini la paie aux AFK).
            await db.execute(
                "INSERT OR IGNORE INTO alliance_war_participants (war_id, user_id, alliance_id) "
                "VALUES (?,?,?)", (war_id, i.user.id, int(my_alliance)))
            await db.commit()
        war2 = await _get_war(war_id)
        if war2 and war2["status"] == "active" and (war2["hp_a"] <= 0 or war2["hp_b"] <= 0):
            winner = war2["a_id"] if war2["hp_b"] <= 0 else war2["b_id"]
            await _end_war(i.guild, war_id, winner)
        else:
            await _refresh_panel(i.guild, war_id)
        if kind == "atk":
            tgt = war["b_name"] if i_am_a else war["a_name"]
            await i.followup.send(f"⚔️ **{power} dégâts** infligés à **{tgt}** !", ephemeral=True)
        else:
            await i.followup.send(f"🛡️ **+{power} PV** rendus à ton alliance !", ephemeral=True)
    except Exception as ex:
        print(f"[alliance_war action] {ex}")


async def _end_war(guild, war_id: int, winner_id: int):
    try:
        # Claim ATOMIQUE : un seul appelant termine + récompense (pas de double).
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE alliance_wars SET status='ended', winner_id=?, "
                "ended_at=CURRENT_TIMESTAMP WHERE id=? AND status='active'",
                (int(winner_id), war_id))
            await db.commit()
            if not getattr(cur, "rowcount", 0):
                return
        # Récompense modeste — Phase 255 (audit) : SEULEMENT aux PARTICIPANTS de
        # l'alliance gagnante (ceux qui ont cliqué ⚔️/🛡️ pendant CE tournoi), plus
        # à toute la liste de membres (qui payait même les AFK + aggravait le farm).
        if _add_coins is not None:
            try:
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT user_id FROM alliance_war_participants "
                        "WHERE war_id=? AND alliance_id=?",
                        (war_id, int(winner_id))) as c:
                        rows = await c.fetchall()
                for (uid,) in rows:
                    try:
                        await _add_coins(guild.id, int(uid), _WIN_REWARD)
                    except Exception:
                        pass
            except Exception:
                pass
        await _refresh_panel(guild, war_id, force=True)
    except Exception as ex:
        print(f"[alliance_war end] {ex}")


class AllianceWarButton(discord.ui.DynamicItem[Button],
                        template=r"awar:(?P<war>\d+):(?P<kind>atk|def)"):
    """Bouton de tournoi PERSISTANT — capté par custom_id même après un reboot."""
    def __init__(self, war_id: int, kind: str):
        self.war_id = int(war_id)
        self.kind = kind if kind in ("atk", "def") else "atk"
        if self.kind == "atk":
            super().__init__(Button(label="⚔️ Attaquer l'adversaire",
                                    style=discord.ButtonStyle.danger,
                                    custom_id=f"awar:{int(war_id)}:atk"))
        else:
            super().__init__(Button(label="🛡️ Défendre mon alliance",
                                    style=discord.ButtonStyle.success,
                                    custom_id=f"awar:{int(war_id)}:def"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["war"]), match["kind"])

    async def callback(self, i: discord.Interaction):
        await _record_action(i, self.war_id, self.kind)


def register_persistent_views(bot_instance):
    try:
        bot_instance.add_dynamic_items(AllianceWarButton)
    except Exception:
        pass


async def boot_cleanup():
    """Au boot : termine les tournois 'active' ABANDONNÉS (>24 h) — filet anti-orphelin.
    Les tournois récents restent actifs (les boutons DynamicItem survivent au reboot)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE alliance_wars SET status='ended', ended_at=CURRENT_TIMESTAMP "
                "WHERE status='active' AND julianday('now') - julianday(started_at) > 1.0")
            await db.commit()
    except Exception as ex:
        print(f"[alliance_war boot_cleanup] {ex}")


__all__ = [
    "setup", "init_db", "start_war", "register_persistent_views",
    "boot_cleanup", "AllianceWarButton",
]
