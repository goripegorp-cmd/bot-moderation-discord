"""
delegations.py - Système de Distribution (Phase 18 + 18.1 blacklist/whitelist).

CONCEPT :
    L'owner du serveur peut créer des "distributions" : déléguer la gestion
    d'UN rôle spécifique à UN utilisateur de confiance. Le délégué peut alors :
    - Donner ou retirer ce rôle à des membres
    - Voir la liste des membres qui ont le rôle
    - Voir leur activité (last message, AFK, etc.)
    - Gérer une blacklist (interdits du rôle) et une whitelist (validés)

USE CASE :
    - Le owner crée une distribution "Rell Seas Studio" déléguée à @StudioHead
    - Le owner définit : le rôle, l'utilisateur autorisé, le seuil d'activité
    - @StudioHead utilise /manage et accède à SON panel
    - @StudioHead peut donner/retirer le rôle, voir l'activité, blacklist/whitelist
    - @StudioHead NE PEUT PAS changer le rôle ni le seuil (owner only)

DATA MODEL :
    Stocké dans la config guild sous la clé 'delegations' = list[dict] :
    {
        "id": str,              # identifiant unique (slug)
        "name": str,            # nom affiché ("Rell Seas Studio", etc.)
        "emoji": str,           # emoji pour l'UI
        "role_id": int,         # rôle géré (défini par OWNER)
        "manager_user_id": int, # utilisateur autorisé (défini par OWNER)
        "activity_threshold_days": int,  # seuil AFK (défini par OWNER)
        "blacklist": list[int], # user_ids interdits du rôle (gérée par MANAGER)
        "whitelist": list[int], # user_ids validés/approuvés (gérée par MANAGER)
        "notes": str,           # description optionnelle
        "created_at": iso str,
    }

API :
    list_delegations(guild_config) -> list[dict]
    get_delegation(guild_config, delegation_id) -> dict | None
    get_delegations_for_user(guild_config, user_id) -> list[dict]
    add_delegation(guild_config, payload) -> dict (le nouveau)
    remove_delegation(guild_config, delegation_id) -> bool
    update_delegation(guild_config, delegation_id, **changes) -> bool
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional


CONFIG_KEY = 'delegations'


def _slugify(text: str) -> str:
    """Convertit un nom en slug ASCII safe pour ID."""
    text = re.sub(r'[^a-zA-Z0-9]+', '_', text.lower())
    text = text.strip('_')
    return text[:40] or 'delegation'


def list_delegations(guild_config: dict) -> list[dict]:
    """Retourne la liste des délégations configurées sur ce guild."""
    raw = guild_config.get(CONFIG_KEY, []) or []
    if not isinstance(raw, list):
        return []
    out = []
    for d in raw:
        if isinstance(d, dict) and d.get('id') and d.get('role_id'):
            out.append(d)
    return out


def get_delegation(guild_config: dict, delegation_id: str) -> Optional[dict]:
    """Retourne une délégation par son ID."""
    for d in list_delegations(guild_config):
        if d.get('id') == delegation_id:
            return d
    return None


def get_delegations_for_user(guild_config: dict, user_id: int) -> list[dict]:
    """Retourne les délégations dont l'utilisateur est manager."""
    out = []
    for d in list_delegations(guild_config):
        if int(d.get('manager_user_id', 0)) == int(user_id):
            out.append(d)
    return out


def add_delegation(
    guild_config: dict,
    *,
    name: str,
    role_id: int,
    manager_user_id: int,
    emoji: str = "🔑",
    activity_threshold_days: int = 14,
    notes: str = "",
) -> dict:
    """Ajoute une nouvelle délégation. Retourne le dict créé.

    L'ID est généré automatiquement comme slug du nom + suffix si collision.
    """
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
        "emoji": emoji[:4] or "🔑",
        "role_id": int(role_id),
        "manager_user_id": int(manager_user_id),
        "activity_threshold_days": max(1, min(365, int(activity_threshold_days))),
        "blacklist": [],  # user_ids interdits (gérée par manager via /manage)
        "whitelist": [],  # user_ids approuvés (gérée par manager via /manage)
        "notes": notes[:200],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    delegations.append(new_delegation)
    guild_config[CONFIG_KEY] = delegations
    return new_delegation


def remove_delegation(guild_config: dict, delegation_id: str) -> bool:
    """Supprime une délégation par ID. Retourne True si supprimée."""
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
    """Met à jour les champs d'une délégation. Retourne True si trouvée et modifiée."""
    delegations = list_delegations(guild_config)
    found = False
    for d in delegations:
        if d.get('id') == delegation_id:
            allowed_keys = {'name', 'emoji', 'role_id', 'manager_user_id',
                            'activity_threshold_days', 'notes'}
            for k, v in changes.items():
                if k in allowed_keys and v is not None:
                    if k == 'role_id' or k == 'manager_user_id':
                        d[k] = int(v)
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


def is_blacklisted(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    """True si l'utilisateur est blacklisté de cette distribution."""
    d = get_delegation(guild_config, delegation_id)
    if not d:
        return False
    return int(user_id) in (d.get('blacklist') or [])


def is_whitelisted(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    """True si l'utilisateur est whitelisté de cette distribution."""
    d = get_delegation(guild_config, delegation_id)
    if not d:
        return False
    return int(user_id) in (d.get('whitelist') or [])


def add_to_blacklist(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    """Ajoute un user à la blacklist. Le retire aussi de la whitelist si présent.
    Retourne True si ajouté, False si déjà présent."""
    delegations = list_delegations(guild_config)
    for d in delegations:
        if d.get('id') == delegation_id:
            bl = list(d.get('blacklist') or [])
            wl = list(d.get('whitelist') or [])
            uid = int(user_id)
            if uid in bl:
                return False
            bl.append(uid)
            # Si dans whitelist, on le retire (cohérence)
            if uid in wl:
                wl.remove(uid)
            d['blacklist'] = bl
            d['whitelist'] = wl
            guild_config[CONFIG_KEY] = delegations
            return True
    return False


def remove_from_blacklist(guild_config: dict, delegation_id: str, user_id: int) -> bool:
    """Retire un user de la blacklist. Retourne True si retiré."""
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
    """Ajoute un user à la whitelist. Le retire aussi de la blacklist si présent."""
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
    """Retire un user de la whitelist."""
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
