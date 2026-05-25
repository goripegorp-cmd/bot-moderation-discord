"""
delegations.py - Système de Distribution (Phase 18.2 — multi-rôles).

CONCEPT :
    L'owner crée des "distributions" qui définissent :
    - QUELS rôles sont gérés par cette distribution (plusieurs possibles)
    - QUI peut utiliser /manage pour cette distribution (utilisateurs ou rôles)
    - Le seuil d'activité (AFK threshold)

    Le délégué peut alors :
    - Donner ou retirer LES rôles gérés à des membres
    - Voir la liste des membres ayant l'un de ces rôles + leur activité
    - Gérer une blacklist (interdits) et une whitelist (validés)

DATA MODEL (Phase 18.2) :
    config['delegations'] = list[dict] :
    {
        "id": str,                          # ID unique (slug du nom)
        "name": str,                        # Nom affiché
        "emoji": str,                       # Emoji UI

        # OWNER-defined — quels rôles cette distribution gère
        "managed_role_ids": list[int],      # plural — multi-rôles

        # OWNER-defined — qui peut utiliser /manage
        "manager_user_ids": list[int],      # users autorisés (directement)
        "manager_role_ids": list[int],      # rôles autorisés (anyone with one of these)

        # OWNER-defined — seuil activité
        "activity_threshold_days": int,

        # MANAGER-managed (le délégué peut les modifier)
        "blacklist": list[int],
        "whitelist": list[int],

        "notes": str,
        "created_at": iso str,
    }

RÉTROCOMPAT :
    Les anciennes distributions avec `role_id` (singulier) et
    `manager_user_id` (singulier) sont auto-migrées en list lors de la
    lecture via get_delegation()/list_delegations().
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional


CONFIG_KEY = 'delegations'


def _slugify(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9]+', '_', text.lower())
    text = text.strip('_')
    return text[:40] or 'delegation'


def _normalize(d: dict) -> dict:
    """Migre une délégation au format Phase 18.2 (listes).

    Rétrocompat : si old `role_id`/`manager_user_id` (singulier) existent,
    on les convertit en listes. Garantit que les champs listes existent
    toujours (vides au pire).
    """
    if not isinstance(d, dict):
        return d

    # managed_role_ids : était role_id (single)
    if 'managed_role_ids' not in d:
        legacy_role = d.get('role_id', 0)
        d['managed_role_ids'] = [int(legacy_role)] if legacy_role else []

    # manager_user_ids : était manager_user_id (single)
    if 'manager_user_ids' not in d:
        legacy_user = d.get('manager_user_id', 0)
        d['manager_user_ids'] = [int(legacy_user)] if legacy_user else []

    # manager_role_ids : nouveau, par défaut vide
    if 'manager_role_ids' not in d:
        d['manager_role_ids'] = []

    # Listes garanties
    for key in ['managed_role_ids', 'manager_user_ids', 'manager_role_ids', 'blacklist', 'whitelist']:
        if not isinstance(d.get(key), list):
            d[key] = []

    # Defaults
    d.setdefault('activity_threshold_days', 14)
    d.setdefault('emoji', '🔑')
    d.setdefault('notes', '')

    return d


def list_delegations(guild_config: dict) -> list[dict]:
    """Retourne la liste des distributions (auto-migrées au format Phase 18.2)."""
    raw = guild_config.get(CONFIG_KEY, []) or []
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        if isinstance(d, dict) and d.get('id'):
            out.append(_normalize(d))
    return out


def get_delegation(guild_config: dict, delegation_id: str) -> Optional[dict]:
    """Retourne une distribution par son ID (auto-migrée)."""
    for d in list_delegations(guild_config):
        if d.get('id') == delegation_id:
            return d
    return None


def is_user_authorized(d: dict, user_id: int, member_role_ids: Optional[list[int]] = None) -> bool:
    """True si user_id peut utiliser /manage pour cette distribution.

    Conditions (OU) :
    - user_id ∈ manager_user_ids
    - L'un des member_role_ids ∈ manager_role_ids
    """
    if not d:
        return False
    d = _normalize(d)
    if int(user_id) in (d.get('manager_user_ids') or []):
        return True
    if member_role_ids:
        mgr_roles = set(d.get('manager_role_ids') or [])
        if mgr_roles and any(int(r) in mgr_roles for r in member_role_ids):
            return True
    return False


def get_delegations_for_user(
    guild_config: dict,
    user_id: int,
    member_role_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Retourne les distributions dont l'utilisateur est manager (user OU rôle)."""
    out = []
    for d in list_delegations(guild_config):
        if is_user_authorized(d, user_id, member_role_ids):
            out.append(d)
    return out


def add_delegation(
    guild_config: dict,
    *,
    name: str,
    managed_role_ids: list[int] = None,
    manager_user_ids: list[int] = None,
    manager_role_ids: list[int] = None,
    emoji: str = "🔑",
    activity_threshold_days: int = 14,
    notes: str = "",
) -> dict:
    """Ajoute une distribution. Phase 18.2 — accepte listes."""
    base_id = _slugify(name)
    delegations = list_delegations(guild_config)
    existing_ids = {d.get('id') for d in delegations}
    delegation_id = base_id
    suffix = 1
    while delegation_id in existing_ids:
        suffix += 1
        delegation_id = f"{base_id}_{suffix}"

    new_delegation = {
        "id": delegation_id,
        "name": name[:50],
        "emoji": (emoji[:4] or "🔑"),
        "managed_role_ids": [int(r) for r in (managed_role_ids or [])],
        "manager_user_ids": [int(u) for u in (manager_user_ids or [])],
        "manager_role_ids": [int(r) for r in (manager_role_ids or [])],
        "activity_threshold_days": max(1, min(365, int(activity_threshold_days))),
        "blacklist": [],
        "whitelist": [],
        "notes": notes[:200],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    delegations.append(new_delegation)
    guild_config[CONFIG_KEY] = delegations
    return new_delegation


def remove_delegation(guild_config: dict, delegation_id: str) -> bool:
    delegations = list_delegations(guild_config)
    before = len(delegations)
    delegations = [d for d in delegations if d.get('id') != delegation_id]
    if len(delegations) == before:
        return False
    guild_config[CONFIG_KEY] = delegations
    return True


def update_delegation(
    guild_config: dict,
    delegation_id: str,
    **changes,
) -> bool:
    """Met à jour les champs d'une distribution. Accepte listes en Phase 18.2."""
    delegations = list_delegations(guild_config)
    found = False
    for d in delegations:
        if d.get('id') == delegation_id:
            allowed_keys = {
                'name', 'emoji', 'managed_role_ids',
                'manager_user_ids', 'manager_role_ids',
                'activity_threshold_days', 'notes',
            }
            for k, v in changes.items():
                if k not in allowed_keys or v is None:
                    continue
                if k in ('managed_role_ids', 'manager_user_ids', 'manager_role_ids'):
                    d[k] = [int(x) for x in (v or [])]
                elif k == 'activity_threshold_days':
                    d[k] = max(1, min(365, int(v)))
                elif k == 'name':
                    d[k] = str(v)[:50]
                elif k == 'emoji':
                    d[k] = str(v)[:4] or "🔑"
                elif k == 'notes':
                    d[k] = str(v)[:200]
            found = True
            break
    if found:
        guild_config[CONFIG_KEY] = delegations
    return found


# =============================================================================
# Blacklist / Whitelist (gérées par le manager)
# =============================================================================

def is_blacklisted(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    d = get_delegation(guild_config, delegation_id)
    if not d:
        return False
    return int(user_id) in (d.get('blacklist') or [])


def is_whitelisted(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    d = get_delegation(guild_config, delegation_id)
    if not d:
        return False
    return int(user_id) in (d.get('whitelist') or [])


def add_to_blacklist(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    delegations = list_delegations(guild_config)
    for d in delegations:
        if d.get('id') == delegation_id:
            bl = list(d.get('blacklist') or [])
            wl = list(d.get('whitelist') or [])
            uid = int(user_id)
            if uid in bl:
                return False
            bl.append(uid)
            if uid in wl:
                wl.remove(uid)
            d['blacklist'] = bl
            d['whitelist'] = wl
            guild_config[CONFIG_KEY] = delegations
            return True
    return False


def remove_from_blacklist(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    delegations = list_delegations(guild_config)
    for d in delegations:
        if d.get('id') == delegation_id:
            bl = list(d.get('blacklist') or [])
            uid = int(user_id)
            if uid not in bl:
                return False
            bl.remove(uid)
            d['blacklist'] = bl
            guild_config[CONFIG_KEY] = delegations
            return True
    return False


def add_to_whitelist(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    delegations = list_delegations(guild_config)
    for d in delegations:
        if d.get('id') == delegation_id:
            wl = list(d.get('whitelist') or [])
            bl = list(d.get('blacklist') or [])
            uid = int(user_id)
            if uid in wl:
                return False
            wl.append(uid)
            if uid in bl:
                bl.remove(uid)
            d['whitelist'] = wl
            d['blacklist'] = bl
            guild_config[CONFIG_KEY] = delegations
            return True
    return False


def remove_from_whitelist(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    delegations = list_delegations(guild_config)
    for d in delegations:
        if d.get('id') == delegation_id:
            wl = list(d.get('whitelist') or [])
            uid = int(user_id)
            if uid not in wl:
                return False
            wl.remove(uid)
            d['whitelist'] = wl
            guild_config[CONFIG_KEY] = delegations
            return True
    return False


__all__ = [
    "CONFIG_KEY",
    "list_delegations",
    "get_delegation",
    "get_delegations_for_user",
    "is_user_authorized",
    "add_delegation",
    "remove_delegation",
    "update_delegation",
    "is_blacklisted",
    "is_whitelisted",
    "add_to_blacklist",
    "remove_from_blacklist",
    "add_to_whitelist",
    "remove_from_whitelist",
]
