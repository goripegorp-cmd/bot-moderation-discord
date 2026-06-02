"""dm_notify.py — Phase 235.31 : notifications d'événement en MP (OPT-IN STRICT).

Cahier des charges owner : certains membres veulent être prévenus EN PRIVÉ (MP)
quand un événement apparaît. MAIS le MP de masse est INTERDIT par Discord (et
dérange). Donc : **OPT-IN STRICT** — on ne DM QUE les membres qui ont
explicitement cliqué « 📩 Notifs MP ». Toujours réversible (re-clic = stop).

Garde-fous anti-abus / anti-bannissement Discord :
- Seuls les events SIGNIFICATIFS déclenchent un MP (pas chaque mob / trésor).
- Cooldown par user (un même opt-in n'est MP qu'1×/N h).
- Cap dur de MP par event + délai entre 2 MP (respect du rate-limit).
- MP fermés (Forbidden) → skip silencieux.
- Tout FAIL-OPEN : un bug n'empêche jamais l'event de tourner.
"""

import asyncio
from datetime import datetime, timezone, timedelta

_get_db = None

# Seuls les events « importants » déclenchent un MP (les mob/trésor/mystère/quiz
# sont trop fréquents → spam). Clés alignées sur les notif_key de _ping_active_members.
_DM_EVENT_TYPES = {"boss", "boss_raid", "world_boss", "climax", "invasion", "daily_boss"}
_PER_USER_COOLDOWN_H = 2    # un même opt-in n'est MP qu'1×/2 h max
_DM_CAP = 25               # max de MP envoyés par event (anti-flood Discord)
_DM_DELAY = 1.3            # secondes entre deux MP (respect rate-limit)


def setup(get_db_fn):
    global _get_db
    _get_db = get_db_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS dm_event_optin ("
                "guild_id INTEGER, user_id INTEGER, enabled INTEGER DEFAULT 1, "
                "last_dm TEXT, PRIMARY KEY (guild_id, user_id))"
            )
            await db.commit()
    except Exception as ex:
        print(f"[dm_notify init_db] {ex}")


async def is_optin(guild_id, user_id) -> bool:
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT enabled FROM dm_event_optin WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        return bool(row and row[0])
    except Exception:
        return False


async def set_optin(guild_id, user_id, enabled: bool):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO dm_event_optin (guild_id, user_id, enabled) VALUES (?,?,?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET enabled=excluded.enabled",
                (int(guild_id), int(user_id), 1 if enabled else 0),
            )
            await db.commit()
    except Exception as ex:
        print(f"[dm_notify set_optin] {ex}")


async def toggle_optin(guild_id, user_id) -> bool:
    """Inverse l'état d'abonnement MP. Retourne le NOUVEL état (True = abonné)."""
    cur = await is_optin(guild_id, user_id)
    nv = not cur
    await set_optin(guild_id, user_id, nv)
    return nv


def _dm_text(guild, title: str, ch_txt: str) -> str:
    return (
        f"🔔 **{getattr(guild, 'name', 'Le serveur')}** — {title}{ch_txt}\n"
        f"_Tu reçois ce MP car tu as activé les **notifs privées d'événement**. "
        f"Clique le bouton ci-dessous, ou re-clique « 📩 Notifs MP » sur le serveur, "
        f"pour arrêter à tout moment._"
    )


async def notify_event_dm(guild, title: str, channel, *, notif_key="boss",
                          view_factory=None) -> int:
    """DM les membres OPT-IN (events significatifs seulement). Throttlé + capé +
    fail-open. `view_factory()` → une View optionnelle (bouton stop) jointe au MP.
    Retourne le nombre de MP envoyés."""
    if _get_db is None or guild is None:
        return 0
    if (notif_key or "").lower() not in _DM_EVENT_TYPES:
        return 0  # pas de MP pour les events fréquents
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=_PER_USER_COOLDOWN_H)).isoformat()
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM dm_event_optin "
                "WHERE guild_id=? AND enabled=1 AND (last_dm IS NULL OR last_dm < ?) "
                "LIMIT ?",
                (guild.id, cutoff, _DM_CAP),
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            return 0
        sent = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        ch_txt = f"\n➡️ Ça se passe dans {channel.mention}" if channel is not None else ""
        body = _dm_text(guild, title, ch_txt)
        for r in rows:
            uid = int(r[0])
            m = guild.get_member(uid)
            if m is None or m.bot:
                continue
            try:
                kwargs = {}
                if view_factory is not None:
                    try:
                        kwargs["view"] = view_factory()
                    except Exception:
                        kwargs = {}
                await m.send(body, **kwargs)
                sent += 1
                try:
                    async with _get_db() as db:
                        await db.execute(
                            "UPDATE dm_event_optin SET last_dm=? "
                            "WHERE guild_id=? AND user_id=?",
                            (now_iso, guild.id, uid),
                        )
                        await db.commit()
                except Exception:
                    pass
                await asyncio.sleep(_DM_DELAY)  # respect rate-limit Discord
            except Exception:
                # MP fermés (Forbidden) ou autre → on saute, silencieusement
                continue
        return sent
    except Exception as ex:
        print(f"[dm_notify notify_event_dm] {ex}")
        return 0


async def send_weekly_recaps(guild, build_text, *, cap=40) -> int:
    """Phase 238 : DM un RÉCAP HEBDO aux membres OPT-IN MP (dm_event_optin
    enabled=1) — les MÊMES qui ont cliqué « 📩 Notifs MP ». Strictement opt-in,
    donc aucun MP de masse. `build_text(member)` (coroutine) renvoie le corps du
    MP (ou '' pour sauter ce membre, ex. inactif). Cappé + throttlé + fail-open.
    Retourne le nombre de MP envoyés."""
    if _get_db is None or guild is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM dm_event_optin "
                "WHERE guild_id=? AND enabled=1 LIMIT ?",
                (guild.id, int(cap)),
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            return 0
        sent = 0
        for r in rows:
            uid = int(r[0])
            m = guild.get_member(uid)
            if m is None or m.bot:
                continue
            try:
                body = await build_text(m)
            except Exception:
                body = ""
            if not body:
                continue
            try:
                await m.send(body)
                sent += 1
                await asyncio.sleep(_DM_DELAY)  # respect rate-limit Discord
            except Exception:
                continue
        return sent
    except Exception as ex:
        print(f"[dm_notify send_weekly_recaps] {ex}")
        return 0
