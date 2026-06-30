"""recidivism.py — Dégradation CRESCENDO des récidivistes (owner 2026-06-30).

Problème owner : l'échelle de sanction existante (`_cumulative_offense_sanction`) compte
sur 14 JOURS GLISSANTS → se réinitialise → un chronique qui fait « 3 sanctions un jour,
3 un autre, 3 un autre » n'atteint jamais le sommet et PROFITE du système. Le bot le
sanctionne mais « ça n'agit pas » sur le long terme.

Réponse : une couche PARALLÈLE et PERSISTANTE (on ne touche pas l'échelle 14j existante).
- SCORE de toxicité pondéré par la RÉCENCE sur 90 jours (chaque infraction AUTOMATIQUE vaut
  1.0 fraîche puis décroît linéairement jusqu'à 0 à 90 j) → ne se vide JAMAIS d'un coup ;
  un récidiviste qui continue reste élevé, un membre qui se reprend redescend lentement.
- 3 PALIERS de restriction → moins d'accès au fur et à mesure :
    🟡 1 Surveillé   : plus d'images/fichiers + cooldown messages léger + surveillance
    🟠 2 Restreint   : + plus de liens + cooldown moyen
    🔴 3 Sous contrôle: + cooldown lourd
- 1 RÔLE non-hoisté « 🔇 Restreint (auto) » (invisible dans la sidebar) = marqueur + dents
  (overwrites deny images/embeds/réactions au niveau catégorie). Le cooldown + la suppression
  des liens sont imposés BOT-SIDE en on_message (précédent : la restriction images des nouveaux
  via trust_system est déjà une suppression on_message, pas une perm de rôle).
- DÉ-ESCALADE automatique : le score étant recalculé depuis la table `infractions`, il décroît
  tout seul ; une tâche périodique retire le rôle quand le score repasse sous le seuil.

JAMAIS owner/super-owner/staff/immunisés (is_fully_immune + is_super_owner). FAIL-OPEN partout
(un bug ne bloque jamais un message ni le pipeline). Jamais de kick/ban auto (founder-only).
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import discord
from discord.ext import tasks

# ─── Références injectées par bot.py ───────────────────────────────────────
_bot = None
_get_db = None
_db_get = None                 # async (guild_id) -> dict config
_is_immune_fn = None           # async (member) -> bool  (is_fully_immune)
_is_super_owner_fn = None      # (user_id) -> bool
_log_escalation_fn = None      # async (guild, member, count, palier, reason) -> log owner/staff
_notice_fn = None              # async (channel, text) -> avertissement doux auto-supprimé

# ─── État mémoire (rechargé au boot depuis la DB / le rôle) ────────────────
_restricted: dict = {}         # (gid, uid) -> tier (1..3) — lookup O(1) en on_message
_last_msg: dict = {}           # (gid, uid) -> ts du dernier message autorisé (cooldown)
_notice_cd: dict = {}          # (gid, uid) -> ts du dernier avertissement (anti-spam)

_SELF_TYPES = ('mute', 'unmute', 'ban', 'kick')   # byproducts de l'escalade → jamais comptés
_ROLE_NAME = "🔇 Restreint (auto)"

# défauts (réglables via cfg recidivism_*)
_DEF = {
    'recidivism_enabled': 1,
    'recidivism_t1': 3, 'recidivism_t2': 6, 'recidivism_t3': 10,
    'recidivism_cd1': 15, 'recidivism_cd2': 30, 'recidivism_cd3': 60,
}


def setup(bot_instance, get_db_fn, db_get_fn, is_immune_fn, is_super_owner_fn,
          log_escalation_fn=None, notice_fn=None):
    global _bot, _get_db, _db_get, _is_immune_fn, _is_super_owner_fn
    global _log_escalation_fn, _notice_fn
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _is_immune_fn = is_immune_fn
    _is_super_owner_fn = is_super_owner_fn
    _log_escalation_fn = log_escalation_fn
    _notice_fn = notice_fn


async def _db_set(guild_id: int, key: str, value):
    try:
        from bot import db_set
        await db_set(guild_id, key, value)
    except Exception:
        pass


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS member_restrictions("
                " guild_id INTEGER, user_id INTEGER, tier INTEGER DEFAULT 0,"
                " score REAL DEFAULT 0, applied_at DATETIME, last_offense_at DATETIME,"
                " PRIMARY KEY(guild_id, user_id))")
            await db.commit()
    except Exception as ex:
        print(f"[recidivism init_db] {ex}")


async def load_cache():
    """Recharge le cache RAM des membres restreints depuis la DB (au boot)."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, user_id, tier FROM member_restrictions WHERE tier > 0") as cur:
                rows = await cur.fetchall()
        _restricted.clear()
        for gid, uid, tier in rows:
            _restricted[(int(gid), int(uid))] = int(tier)
        print(f"[recidivism] cache chargé : {len(_restricted)} membre(s) restreint(s)")
    except Exception as ex:
        print(f"[recidivism load_cache] {ex}")


def tier_of(guild_id: int, user_id: int) -> int:
    """Palier de restriction d'un membre (0 = libre). Lookup mémoire O(1)."""
    return _restricted.get((int(guild_id), int(user_id)), 0)


# ─── Calcul du score & des seuils ──────────────────────────────────────────
async def _conf(guild_id: int) -> dict:
    out = dict(_DEF)
    try:
        if _db_get is not None:
            c = await _db_get(guild_id)
            for k in _DEF:
                if k in c:
                    out[k] = c[k]
    except Exception:
        pass
    return out


async def _score(guild_id: int, user_id: int) -> float:
    """Score de toxicité = somme pondérée par la récence des infractions AUTOMATIQUES
    (mod_id = bot) sur 90 jours, hors byproducts (mute/ban/kick). FAIL-OPEN → 0."""
    if _get_db is None or _bot is None or _bot.user is None:
        return 0.0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(MAX(0.0, 1.0 - (julianday('now')-julianday(created_at))/90.0)), 0) "
                "FROM infractions WHERE guild_id=? AND user_id=? AND mod_id=? "
                "AND type NOT IN ('mute','unmute','ban','kick')",
                (guild_id, user_id, _bot.user.id),
            ) as cur:
                row = await cur.fetchone()
        return float(row[0]) if row and row[0] else 0.0
    except Exception:
        return 0.0


def _tier_for(score: float, conf: dict) -> int:
    try:
        if score >= float(conf['recidivism_t3']):
            return 3
        if score >= float(conf['recidivism_t2']):
            return 2
        if score >= float(conf['recidivism_t1']):
            return 1
    except Exception:
        pass
    return 0


def _cooldown_for(tier: int, conf: dict) -> int:
    try:
        return int(conf.get(f'recidivism_cd{tier}', _DEF.get(f'recidivism_cd{tier}', 0)) or 0)
    except Exception:
        return 0


# ─── Rôle de restriction (marqueur non-hoisté + dents au niveau catégorie) ──
async def _ensure_role(guild) -> Optional[discord.Role]:
    """Get-or-create le rôle « 🔇 Restreint (auto) » NON-HOISTÉ + pose des overwrites deny
    (images/embeds/réactions/emojis externes) au niveau des CATÉGORIES (peu d'appels, anti-429).
    Idempotent : si le rôle existe déjà (cfg), on ne repose pas les overwrites. FAIL-OPEN → None."""
    try:
        me = guild.me
        if not (me and me.guild_permissions.manage_roles):
            return None
        c = await _db_get(guild.id) if _db_get else {}
        rid = int(c.get('recidivism_role', 0) or 0)
        role = guild.get_role(rid) if rid else None
        if role is not None:
            return role
        role = discord.utils.get(guild.roles, name=_ROLE_NAME)
        if role is None:
            try:
                role = await guild.create_role(
                    name=_ROLE_NAME, colour=discord.Colour.dark_grey(),
                    hoist=False, mentionable=False,
                    reason="Dégradation crescendo : restriction des récidivistes")
            except Exception:
                return None
        await _db_set(guild.id, 'recidivism_role', role.id)
        # Poser les dents au niveau des catégories (cascade) + salons texte sans catégorie.
        deny = {
            'attach_files': False, 'embed_links': False,
            'add_reactions': False, 'use_external_emojis': False,
        }
        targets = list(getattr(guild, 'categories', []))
        try:
            targets += [ch for ch in guild.text_channels if ch.category is None]
        except Exception:
            pass
        for t in targets:
            try:
                await t.set_permissions(role, reason="Restriction récidiviste", **deny)
            except Exception:
                pass
            await asyncio.sleep(0.5)   # throttle anti-429
        return role
    except Exception as ex:
        print(f"[recidivism _ensure_role] {ex}")
        return None


# ─── Recalcul + application du palier ──────────────────────────────────────
async def recompute(guild, member):
    """Recalcule le palier d'un membre et applique/retire la restriction. FAIL-SAFE."""
    if guild is None or member is None or getattr(member, 'bot', False):
        return
    try:
        gid, uid = guild.id, member.id
        conf = await _conf(gid)
        if not conf.get('recidivism_enabled', 1):
            return
        # IMMUNITÉ : jamais owner/super-owner/staff/immunisés → on s'assure qu'ils sont LIBRES.
        immune = False
        try:
            if _is_super_owner_fn and _is_super_owner_fn(uid):
                immune = True
            elif _is_immune_fn and await _is_immune_fn(member):
                immune = True
        except Exception:
            immune = True   # doute → on NE restreint PAS (fail-safe)
        new_tier = 0
        if not immune:
            new_tier = _tier_for(await _score(gid, uid), conf)
        old_tier = _restricted.get((gid, uid), 0)
        if new_tier == old_tier:
            return
        role = await _ensure_role(guild)
        if new_tier > 0:
            if role is not None and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Récidive — palier {new_tier}")
                except Exception:
                    pass
            _restricted[(gid, uid)] = new_tier
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO member_restrictions(guild_id,user_id,tier,applied_at,last_offense_at) "
                        "VALUES(?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) "
                        "ON CONFLICT(guild_id,user_id) DO UPDATE SET tier=?, applied_at=CURRENT_TIMESTAMP",
                        (gid, uid, new_tier, new_tier))
                    await db.commit()
            except Exception:
                pass
            # Log owner/staff UNIQUEMENT quand ça MONTE (anti-flood géré par le logger).
            if new_tier > old_tier and _log_escalation_fn:
                _labels = {1: "🟡 Surveillé", 2: "🟠 Restreint", 3: "🔴 Sous contrôle"}
                try:
                    await _log_escalation_fn(
                        guild, member, new_tier, _labels.get(new_tier, str(new_tier)),
                        f"Récidive chronique → accès réduits (palier {new_tier}).")
                except Exception:
                    pass
        else:
            # Palier 0 : libération (score décru / devenu immunisé).
            _restricted.pop((gid, uid), None)
            if role is not None and role in getattr(member, 'roles', []):
                try:
                    await member.remove_roles(role, reason="Récidive : palier retombé à 0")
                except Exception:
                    pass
            try:
                async with _get_db() as db:
                    await db.execute(
                        "DELETE FROM member_restrictions WHERE guild_id=? AND user_id=?", (gid, uid))
                    await db.commit()
            except Exception:
                pass
    except Exception as ex:
        print(f"[recidivism recompute] {ex}")


async def on_infraction(guild_id: int, user_id: int, typ: str):
    """Appelé (fire-and-forget) depuis _record_infraction après CHAQUE infraction auto.
    Ignore les byproducts de l'escalade (anti-boucle). FAIL-SAFE."""
    try:
        if typ and str(typ).lower() in _SELF_TYPES:
            return
        if _bot is None:
            return
        guild = _bot.get_guild(int(guild_id))
        if guild is None:
            return
        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except Exception:
                member = None
        if member is None:
            return
        await recompute(guild, member)
    except Exception as ex:
        print(f"[recidivism on_infraction] {ex}")


# ─── Enforcement en on_message (cooldown + suppression images/liens) ────────
async def enforce_on_message(msg, content: str) -> bool:
    """Applique la restriction à un membre dégradé : cooldown de messages + suppression des
    images (palier ≥1) et des liens (palier ≥2). Retourne True si le message a été supprimé
    (l'appelant fait alors `return`). FAIL-OPEN : tout échec → False (on ne bloque pas)."""
    try:
        if msg.guild is None:
            return False
        gid, uid = msg.guild.id, msg.author.id
        tier = _restricted.get((gid, uid), 0)
        if not tier:
            return False
        # garde-fou immunité (ne devrait jamais arriver : un immunisé n'est pas restreint)
        if _is_super_owner_fn and _is_super_owner_fn(uid):
            return False
        conf = await _conf(gid)
        if not conf.get('recidivism_enabled', 1):
            return False
        now = time.time()
        # (1) COOLDOWN de messages imposé par le bot (Discord n'a pas de slowmode par-personne).
        cd = _cooldown_for(tier, conf)
        if cd > 0:
            last = _last_msg.get((gid, uid), 0)
            if (now - last) < cd:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await _maybe_notice(msg, gid, uid,
                                    f"⏳ {msg.author.mention}, tu es en **mode ralenti** (récidives) — "
                                    f"attends **{cd}s** entre tes messages.")
                return True
            _last_msg[(gid, uid)] = now
        # (2) Contenu interdit selon le palier (images dès le palier 1, liens dès le palier 2).
        try:
            import trust_system
            if trust_system.has_media(msg, content or ''):
                try:
                    await msg.delete()
                except Exception:
                    pass
                await _maybe_notice(msg, gid, uid,
                                    f"🚫 {msg.author.mention}, l'envoi d'**images/fichiers** t'est "
                                    f"temporairement retiré (récidives). Ça reviendra en te calmant.")
                return True
            if tier >= 2 and trust_system.has_non_media_link(content or ''):
                try:
                    await msg.delete()
                except Exception:
                    pass
                await _maybe_notice(msg, gid, uid,
                                    f"🚫 {msg.author.mention}, les **liens** te sont temporairement "
                                    f"retirés (récidives).")
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False


async def _maybe_notice(msg, gid, uid, text):
    """Avertissement doux auto-supprimé, throttlé 30 s par membre (anti-spam). FAIL-SAFE."""
    try:
        now = time.time()
        if now - _notice_cd.get((gid, uid), 0) < 30:
            return
        _notice_cd[(gid, uid)] = now
        if _notice_fn:
            await _notice_fn(msg.channel, text)
    except Exception:
        pass


# ─── Dé-escalade périodique (le score décroît → on retire le rôle) ─────────
@tasks.loop(hours=12)
async def deescalate_task():
    if _bot is None:
        return
    try:
        snapshot = list(_restricted.items())
    except Exception:
        return
    for (gid, uid), _tier in snapshot:
        try:
            guild = _bot.get_guild(gid)
            if guild is None:
                continue
            member = guild.get_member(uid)
            if member is None:
                # parti / non caché → on nettoie le cache (le rôle, s'il revient, sera réévalué)
                continue
            await recompute(guild, member)
            await asyncio.sleep(1)   # jitter anti-429
        except Exception:
            continue


@deescalate_task.before_loop
async def _before():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "setup", "init_db", "load_cache", "tier_of", "recompute", "on_infraction",
    "enforce_on_message", "deescalate_task",
]
