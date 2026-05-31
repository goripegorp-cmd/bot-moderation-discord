"""event_notif_role.py — Rôle « 🔔 Événements » auto-attribué (Phase 216).

PROBLÈME RÉSOLU : on créait des rôles d'événement que PERSONNE n'avait. Ce module
donne EN CACHETTE (sans annonce) un rôle « 🔔 Événements » aux membres ACTIFS
récents (ceux qui participent : messages / vocal). Ce rôle :

- rend VISIBLE le « pool » de joueurs qu'on peut appeler pour les events ;
- son opt-in/opt-out est piloté par la même préférence que /notifs (catégorie
  « events ») : couper les pings d'événements via /notifs RETIRE le rôle ;
- le PING individuel reste géré par bot.py (roté + capé, RULES.md : 3 pings réels
  max/message) — ce module ne ping RIEN tout seul. C'est un badge + un pool +
  un interrupteur, pas un système de spam.

Tout est FAIL-OPEN : jamais de crash, jamais de blocage d'un événement. Si le bot
n'a pas « Gérer les rôles » ou si le rôle est trop haut dans la hiérarchie, on
log et on n'empêche rien.
"""

import discord
from discord.ext import tasks

_bot = None
_get_db = None
_db_get = None
_wants_notif_fn = None  # injecté : _member_wants_notif(guild_id, user_id, cat) -> bool

ROLE_NAME = "🔔 Événements"
ROLE_COLOR = 0x5865F2          # blurple Discord
ACTIVE_DAYS = 7                # actif (message OU vocal) < 7 j → éligible au rôle
SYNC_MAX_OPS = 25              # max add/remove par guild par run (anti rate-limit)
NOTIF_CATEGORY = "events"      # catégorie d'opt-out partagée avec /notifs


def setup(bot_instance, get_db_fn, db_get_fn, wants_notif_fn=None):
    global _bot, _get_db, _db_get, _wants_notif_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _wants_notif_fn = wants_notif_fn


async def init_db():
    """Mémorise l'id du rôle par guild (évite une recherche par nom à chaque fois)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS event_notif_roles ("
                " guild_id INTEGER PRIMARY KEY, role_id INTEGER NOT NULL)")
            await db.commit()
    except Exception as ex:
        print(f"[event_notif_role init_db] {ex}")


async def _get_role_id(guild_id: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT role_id FROM event_notif_roles WHERE guild_id=?",
                (guild_id,)) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0


async def _save_role_id(guild_id: int, role_id: int):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO event_notif_roles(guild_id, role_id) VALUES(?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET role_id=excluded.role_id",
                (guild_id, int(role_id)))
            await db.commit()
    except Exception as ex:
        print(f"[event_notif_role save] {ex}")


async def ensure_role(guild):
    """Crée/retrouve le rôle « 🔔 Événements ». Retourne le Role ou None. Fail-open."""
    if guild is None:
        return None
    me = guild.me
    try:
        rid = await _get_role_id(guild.id)
        if rid:
            r = guild.get_role(rid)
            if r is not None:
                return r
        # Au cas où il existe déjà (créé à la main / avant migration)
        r = discord.utils.get(guild.roles, name=ROLE_NAME)
        if r is None:
            if not (me and me.guild_permissions.manage_roles):
                return None
            r = await guild.create_role(
                name=ROLE_NAME, colour=discord.Colour(ROLE_COLOR),
                mentionable=False, hoist=False,
                reason="Phase 216 : rôle de notification d'événements")
        await _save_role_id(guild.id, r.id)
        return r
    except Exception as ex:
        print(f"[event_notif_role ensure_role] {ex}")
        return None


def _can_manage(guild, role) -> bool:
    """Le bot peut-il attribuer/retirer ce rôle ? (perm + hiérarchie + non géré)."""
    me = guild.me
    try:
        return bool(me and role and me.guild_permissions.manage_roles
                    and role < me.top_role and not role.managed)
    except Exception:
        return False


async def _wants(guild_id: int, user_id: int) -> bool:
    """Le membre veut-il les pings d'événements ? (défaut True). Fail-open True."""
    if _wants_notif_fn is None:
        return True
    try:
        return bool(await _wants_notif_fn(guild_id, user_id, NOTIF_CATEGORY))
    except Exception:
        return True


async def sync_member(guild, member, wants=None):
    """Ajoute/retire le rôle pour UN membre selon son opt-in. Appelé par /notifs
    (toggle instantané) avec wants=True/False, ou en lisant la préférence si None.
    Fail-open."""
    if guild is None or member is None or getattr(member, 'bot', False):
        return
    role = await ensure_role(guild)
    if role is None or not _can_manage(guild, role):
        return
    if wants is None:
        wants = await _wants(guild.id, member.id)
    try:
        has = role in getattr(member, 'roles', [])
        if wants and not has:
            await member.add_roles(role, reason="Opt-in pings d'événements")
        elif (not wants) and has:
            await member.remove_roles(
                role, reason="Opt-out pings d'événements (/notifs)")
    except Exception as ex:
        print(f"[event_notif_role sync_member] {ex}")


async def _active_user_ids(guild_id: int) -> set:
    """IDs des membres ACTIFS récents (message OU vocal < ACTIVE_DAYS)."""
    ids = set()
    if _get_db is None:
        return ids
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM activity_tracking WHERE guild_id=? AND ("
                " (last_message IS NOT NULL AND datetime(last_message) >= datetime('now', ?))"
                " OR (last_vocal IS NOT NULL AND datetime(last_vocal) >= datetime('now', ?)))",
                (guild_id, f"-{ACTIVE_DAYS} days", f"-{ACTIVE_DAYS} days")) as cur:
                for r in await cur.fetchall():
                    try:
                        ids.add(int(r[0]))
                    except Exception:
                        pass
    except Exception as ex:
        print(f"[event_notif_role active ids] {ex}")
    return ids


async def sync_guild(guild):
    """EN CACHETTE : donne le rôle aux ACTIFS récents (opt-in) et le RETIRE aux
    opt-out qui l'ont encore. Capé à SYNC_MAX_OPS opérations/run (anti rate-limit).
    Retourne (granted, removed). Fail-open."""
    if guild is None:
        return (0, 0)
    role = await ensure_role(guild)
    if role is None or not _can_manage(guild, role):
        return (0, 0)
    active = await _active_user_ids(guild.id)
    granted = removed = ops = 0
    # 1) GRANT : actifs opt-in qui n'ont pas encore le rôle
    for uid in active:
        if ops >= SYNC_MAX_OPS:
            break
        m = guild.get_member(uid)
        if m is None or m.bot or role in m.roles:
            continue
        if not await _wants(guild.id, uid):
            continue
        try:
            await m.add_roles(
                role, reason="Phase 216 : membre actif → pings d'événements")
            granted += 1
            ops += 1
        except Exception:
            pass
    # 2) REMOVE : porteurs qui ont coupé les pings d'événements
    for m in list(getattr(role, 'members', [])):
        if ops >= SYNC_MAX_OPS:
            break
        try:
            if not await _wants(guild.id, m.id):
                await m.remove_roles(role, reason="Opt-out pings d'événements")
                removed += 1
                ops += 1
        except Exception:
            pass
    if granted or removed:
        print(f"[event_notif_role] guild={guild.id} +{granted} -{removed}")
    return (granted, removed)


@tasks.loop(hours=3)
async def event_role_task():
    """Toutes les 3 h : synchronise le rôle « 🔔 Événements » sur chaque serveur."""
    if _bot is None:
        return
    for guild in list(_bot.guilds):
        try:
            await sync_guild(guild)
        except Exception as ex:
            print(f"[event_role_task] {ex}")


@event_role_task.before_loop
async def _event_role_wait_ready():
    if _bot is not None:
        try:
            await _bot.wait_until_ready()
        except Exception:
            pass
