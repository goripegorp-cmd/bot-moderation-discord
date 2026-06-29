"""
rate_limiter.py — Limite par utilisateur + endpoint (Phase 148).

🎯 OBJECTIF : protéger le bot contre abus, comptes piratés et boutons
spam-cliqués (qui causent les "Échec interaction" de saturation).

Budget par user :
- 10 clicks de boutons / minute
- 30 commandes slash / heure
- 50 messages chat / 5 minutes (couvre déjà l'anti-spam, on garde
  ce slot pour les futures intégrations)

Si dépassé → soft-lock 5 minutes + DM amical "ralentis".

Implémentation : 100% in-memory (pas de DB pour la perf). Buckets
expirent automatiquement. Très léger.

API publique :
- setup(bot_instance)
- check(user_id, action) -> bool (True = autorisé, False = ratelimit)
- record(user_id, action) — incrémente le compteur
- check_and_record(user_id, action) -> bool — combine les deux
- is_locked(user_id) -> bool
- get_status(user_id) -> dict

⚠️ Le owner et super-owner sont exempts (peuvent toujours agir).
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

import discord

import owner_ids as _owner_ids  # FIX sécu : source UNIQUE de super-owners

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None

# (max_count, window_seconds)
LIMITS = {
    "button":   (10, 60),       # 10/min
    "slash":    (30, 3600),     # 30/h
    "message":  (50, 300),      # 50/5min (placeholder)
    "dm":       (5, 3600),      # 5 DM/h
}

LOCK_DURATION_SEC = 300  # soft-lock 5 min après dépassement

# user_id -> {action: deque[timestamps]}
_buckets: dict[int, dict[str, deque]] = {}
# user_id -> lock_until_ts
_locked: dict[int, float] = {}
# user_id -> set of actions for which we DMed recently (anti-spam DM)
_dm_sent: dict[int, set[str]] = {}


def setup(bot_instance):
    global _bot
    _bot = bot_instance


def _is_exempt(user_id: int) -> bool:
    """Owner / super-owner / bot lui-même = exempts."""
    if _owner_ids.is_super_owner(user_id):
        return True
    if _bot is not None:
        try:
            if user_id == _bot.user.id:
                return True
            # Check si user est owner d'un guild
            for g in _bot.guilds:
                if g.owner_id == user_id:
                    return True
        except Exception:
            pass
    return False


def _gc_bucket(buf: deque, window: int, now_ts: float):
    """Vire les timestamps en dehors de la fenêtre."""
    while buf and (now_ts - buf[0]) > window:
        buf.popleft()


# Borne mémoire (owner 2026-06-29, audit) : _buckets est alimenté par CHAQUE user à CHAQUE
# clic et n'était JAMAIS purgé → croissance RAM sans fin sur longue uptime / raid de comptes.
_MAX_TRACKED_USERS = 5000


def _evict_buckets():
    """Purge les entrées de users INACTIFS (tous les compteurs vides) quand _buckets dépasse
    la borne ; en dernier recours, coupe la moitié la plus ancienne. Ne touche jamais un user
    en lock. Inoffensif (au pire un très vieux user repart de zéro)."""
    if len(_buckets) <= _MAX_TRACKED_USERS:
        return
    for uid in list(_buckets.keys()):
        ub = _buckets.get(uid)
        if not ub or (all(len(b) == 0 for b in ub.values()) and uid not in _locked):
            _buckets.pop(uid, None)
    if len(_buckets) > _MAX_TRACKED_USERS:
        for uid in list(_buckets.keys())[: len(_buckets) // 2]:
            if uid not in _locked:
                _buckets.pop(uid, None)


def is_locked(user_id: int) -> bool:
    """True si le user est en soft-lock."""
    if _is_exempt(user_id):
        return False
    lock = _locked.get(user_id)
    if lock is None:
        return False
    if time.time() < lock:
        return True
    # Lock expiré
    _locked.pop(user_id, None)
    _dm_sent.pop(user_id, None)
    return False


def check(user_id: int, action: str) -> bool:
    """Renvoie True si l'action est autorisée (sans incrémenter)."""
    if _is_exempt(user_id):
        return True
    if is_locked(user_id):
        return False
    return True


def record(user_id: int, action: str) -> bool:
    """Incrémente le compteur. Renvoie True si OK, False si limite atteinte
    (et lock soft activé)."""
    if _is_exempt(user_id):
        return True
    limit = LIMITS.get(action)
    if limit is None:
        return True
    max_count, window = limit
    now_ts = time.time()

    _evict_buckets()  # borne mémoire avant d'insérer un éventuel nouvel user
    user_buckets = _buckets.setdefault(user_id, {})
    buf = user_buckets.setdefault(action, deque())
    _gc_bucket(buf, window, now_ts)

    if len(buf) >= max_count:
        # Lock soft
        _locked[user_id] = now_ts + LOCK_DURATION_SEC
        return False

    buf.append(now_ts)
    return True


async def check_and_record(
    user_id: int, action: str,
    user_member: Optional[discord.Member] = None,
) -> bool:
    """Combine check + record. Si limite atteinte, DM amical le user
    (1× par lock cycle). Renvoie True si OK, False si ratelimit."""
    if _is_exempt(user_id):
        return True
    if is_locked(user_id):
        # Déjà locké, on ne re-DM pas
        return False

    ok = record(user_id, action)
    if ok:
        return True

    # RÈGLE OWNER — ZÉRO MP MEMBRE : on NE DM PLUS le membre rate-limité (le refus
    # éphémère côté call site suffit comme feedback). On garde juste le bookkeeping
    # `_dm_sent` inoffensif pour ne pas changer la structure. `user_member` est ignoré.
    _dm_sent.setdefault(user_id, set()).add(action)
    return False


def get_status(user_id: int) -> dict:
    """Renvoie l'état des buckets pour un user (debug/owner)."""
    out = {
        "exempt": _is_exempt(user_id),
        "locked": is_locked(user_id),
        "buckets": {},
    }
    now_ts = time.time()
    user_buckets = _buckets.get(user_id, {})
    for action, buf in user_buckets.items():
        limit = LIMITS.get(action)
        if limit:
            _gc_bucket(buf, limit[1], now_ts)
            out["buckets"][action] = {
                "current": len(buf),
                "max": limit[0],
                "window_sec": limit[1],
            }
    lock = _locked.get(user_id)
    if lock:
        out["lock_remaining_sec"] = max(0, int(lock - now_ts))
    return out


__all__ = [
    "setup",
    "check",
    "record",
    "check_and_record",
    "is_locked",
    "get_status",
    "LIMITS",
]
