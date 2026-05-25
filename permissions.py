"""
permissions.py - Systeme de permissions granulaires (Phase 0 du redesign 2026).

Permet a l'owner de definir precisement, via le panneau de configuration,
qui peut utiliser quelle commande, quels roles sont sanctionnables, et quels
roles beneficient d'un bypass specifique.

Hierarchie d'evaluation (premier match gagne) :
    1. Owner du serveur (toujours allow)
    2. Deny utilisateur
    3. Allow utilisateur
    4. Deny role (role le plus haut d'abord)
    5. Allow role (role le plus haut d'abord)
    6. Default de la commande (si != inherit)
    7. Default de la categorie
    8. Permission Discord native (mod_only fallback)
    9. Default final = allow

API publique :
    - await load_permissions(guild_id) -> PermissionsConfig
    - await save_permissions(guild_id, config) -> None
    - await can_use(member, command_id) -> bool
    - await is_sanctionable(member) -> bool
    - await is_bypassed(member, system) -> bool
    - get_command_categories() -> dict[str, str]
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import discord


# =============================================================================
# CATALOGUE DES COMMANDES
# =============================================================================
# Chaque commande appartient a une categorie. L'owner peut configurer les
# permissions au niveau commande OU au niveau categorie (la commande herite
# si la regle commande a default="inherit").

COMMAND_CATEGORIES: dict[str, str] = {
    # --- Moderation ---
    "ban":          "moderation",
    "kick":         "moderation",
    "mute":         "moderation",
    "tempmute":     "moderation",
    "unmute":       "moderation",
    "warn":         "moderation",
    "unwarn":       "moderation",
    "purge":        "moderation",
    "lock":         "moderation",
    "unlock":       "moderation",
    "slowmode":     "moderation",

    # --- Configuration (owner) ---
    "config":       "configuration",
    "setup":        "configuration",
    "permissions":  "configuration",

    # --- Tickets ---
    "ticket_open":  "tickets",
    "ticket_close": "tickets",
    "ticket_claim": "tickets_staff",
    "ticket_panel": "tickets_staff",

    # --- Niveaux & Economie ---
    "level":        "leveling",
    "leaderboard":  "leveling",
    "shop":         "leveling",
    "buy":          "leveling",
    "give_xp":      "leveling_staff",
    "remove_xp":    "leveling_staff",

    # --- Utilitaires ---
    "help":         "utility",
    "ping":         "utility",
    "info":         "utility",
    "avatar":       "utility",
    "userinfo":     "utility",
    "serverinfo":   "utility",

    # --- Communaute ---
    "suggest":      "community",
    "trade":        "community",
    "afk":          "community",

    # --- Voix temporaire ---
    "tempvoice":    "tempvoice",
}

CATEGORY_LABELS: dict[str, str] = {
    "moderation":      "Moderation",
    "configuration":   "Configuration (owner)",
    "tickets":         "Tickets (membres)",
    "tickets_staff":   "Tickets (staff)",
    "leveling":        "Niveaux & Economie (membres)",
    "leveling_staff":  "Niveaux & Economie (staff)",
    "utility":         "Utilitaires",
    "community":       "Communaute",
    "tempvoice":       "Voix temporaire",
}


# =============================================================================
# MODELE DE DONNEES
# =============================================================================

@dataclass
class PermissionRule:
    """Regle de permission pour une commande ou categorie.

    `default` est applique si aucune regle utilisateur/role ne matche :
    - "allow"    : autorise par defaut
    - "deny"     : refuse par defaut
    - "mod_only" : autorise si l'utilisateur a la permission Discord kick_members
    - "inherit"  : herite de la categorie (commande seulement)
    """

    default: str = "inherit"
    allow_users: list[int] = field(default_factory=list)
    deny_users: list[int] = field(default_factory=list)
    allow_roles: list[int] = field(default_factory=list)
    deny_roles: list[int] = field(default_factory=list)


@dataclass
class SanctionableConfig:
    """Configuration de qui est sanctionnable.

    Par defaut, tout le monde est sanctionnable. Les roles/utilisateurs ajoutes
    a `non_sanctionable_*` deviennent immunises contre ban/kick/mute/warn.
    """

    default_sanctionable: bool = True
    non_sanctionable_roles: list[int] = field(default_factory=list)
    non_sanctionable_users: list[int] = field(default_factory=list)


@dataclass
class BypassConfig:
    """Bypass par systeme (antiraid, automod, anti-spam, etc.)."""

    roles: list[int] = field(default_factory=list)
    users: list[int] = field(default_factory=list)


@dataclass
class PermissionsConfig:
    """Configuration complete des permissions d'un serveur."""

    version: int = 1
    commands: dict[str, PermissionRule] = field(default_factory=dict)
    categories: dict[str, PermissionRule] = field(default_factory=dict)
    sanctionable: SanctionableConfig = field(default_factory=SanctionableConfig)
    bypass: dict[str, BypassConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "PermissionsConfig":
        return cls(
            version=data.get("version", 1),
            commands={
                k: PermissionRule(**v)
                for k, v in data.get("commands", {}).items()
            },
            categories={
                k: PermissionRule(**v)
                for k, v in data.get("categories", {}).items()
            },
            sanctionable=SanctionableConfig(**data.get("sanctionable", {})),
            bypass={
                k: BypassConfig(**v)
                for k, v in data.get("bypass", {}).items()
            },
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "commands": {k: asdict(v) for k, v in self.commands.items()},
            "categories": {k: asdict(v) for k, v in self.categories.items()},
            "sanctionable": asdict(self.sanctionable),
            "bypass": {k: asdict(v) for k, v in self.bypass.items()},
        }


# =============================================================================
# STOCKAGE (cache + JSON sur disque)
# =============================================================================

from paths import module_dir
DATA_DIR = module_dir("permissions")

_cache: dict[int, PermissionsConfig] = {}
_cache_lock = asyncio.Lock()


def _path_for(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}.json"


async def load_permissions(guild_id: int) -> PermissionsConfig:
    """Charge la config (cache + disque). Cree une config vide si absente."""
    async with _cache_lock:
        if guild_id in _cache:
            return _cache[guild_id]
        path = _path_for(guild_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                config = PermissionsConfig.from_dict(data)
            except (json.JSONDecodeError, TypeError, KeyError):
                config = PermissionsConfig()
        else:
            config = PermissionsConfig()
        _cache[guild_id] = config
        return config


async def save_permissions(guild_id: int, config: PermissionsConfig) -> None:
    """Sauvegarde la config (cache + disque)."""
    async with _cache_lock:
        _cache[guild_id] = config
        path = _path_for(guild_id)
        path.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


async def reload_permissions(guild_id: int) -> PermissionsConfig:
    """Force un rechargement depuis le disque (vide le cache)."""
    async with _cache_lock:
        _cache.pop(guild_id, None)
    return await load_permissions(guild_id)


# =============================================================================
# EVALUATION DES REGLES
# =============================================================================

def _evaluate_rule(
    member: discord.Member, rule: PermissionRule
) -> Optional[bool]:
    """Applique une regle. Retourne True/False si matchee, None si inherit."""
    if member.id in rule.deny_users:
        return False
    if member.id in rule.allow_users:
        return True

    deny_set = set(rule.deny_roles)
    allow_set = set(rule.allow_roles)

    # Parcourt les roles du plus haut au plus bas (poids hierarchique)
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.id in deny_set:
            return False
        if role.id in allow_set:
            return True

    # Aucun match : on applique le default
    if rule.default == "allow":
        return True
    if rule.default == "deny":
        return False
    if rule.default == "mod_only":
        return member.guild_permissions.kick_members
    # "inherit" => None (laisser hériter de la categorie)
    return None


async def can_use(member: discord.Member, command_id: str) -> bool:
    """Verifie si un membre peut utiliser une commande.

    Hierarchie : Owner > Commande > Categorie > Default sensible.
    """
    if member.guild.owner_id == member.id:
        return True

    config = await load_permissions(member.guild.id)

    # 1. Regle de la commande
    cmd_rule = config.commands.get(command_id)
    if cmd_rule:
        result = _evaluate_rule(member, cmd_rule)
        if result is not None:
            return result

    # 2. Regle de la categorie
    category = COMMAND_CATEGORIES.get(command_id)
    if category:
        cat_rule = config.categories.get(category)
        if cat_rule:
            result = _evaluate_rule(member, cat_rule)
            if result is not None:
                return result

    # 3. Default sensible : staff-only pour les categories sensibles
    staff_categories = {
        "moderation",
        "configuration",
        "tickets_staff",
        "leveling_staff",
    }
    if category in staff_categories:
        return member.guild_permissions.kick_members
    return True


async def is_sanctionable(member: discord.Member) -> bool:
    """Indique si un membre peut recevoir une sanction (ban/kick/mute/warn)."""
    if member.guild.owner_id == member.id:
        return False  # owner jamais sanctionnable
    if member == member.guild.me:
        return False  # bot jamais sanctionnable

    config = await load_permissions(member.guild.id)
    sc = config.sanctionable

    if member.id in sc.non_sanctionable_users:
        return False

    member_role_ids = {r.id for r in member.roles}
    if member_role_ids & set(sc.non_sanctionable_roles):
        return False

    return sc.default_sanctionable


async def is_bypassed(member: discord.Member, system: str) -> bool:
    """Indique si un membre est en bypass d'un systeme (antiraid, automod, etc.)."""
    config = await load_permissions(member.guild.id)
    bp = config.bypass.get(system)
    if not bp:
        return False
    if member.id in bp.users:
        return True
    member_role_ids = {r.id for r in member.roles}
    return bool(member_role_ids & set(bp.roles))


# =============================================================================
# UTILITAIRES POUR L'UI
# =============================================================================

def get_command_categories() -> dict[str, str]:
    """Retourne le mapping commande -> categorie."""
    return dict(COMMAND_CATEGORIES)


def get_category_labels() -> dict[str, str]:
    """Retourne le mapping categorie -> label affichable."""
    return dict(CATEGORY_LABELS)


def list_commands_in_category(category: str) -> list[str]:
    """Liste toutes les commandes d'une categorie."""
    return [cmd for cmd, cat in COMMAND_CATEGORIES.items() if cat == category]


def list_categories() -> list[str]:
    """Liste toutes les categories disponibles."""
    return list(CATEGORY_LABELS.keys())


__all__ = [
    "COMMAND_CATEGORIES",
    "CATEGORY_LABELS",
    "PermissionRule",
    "SanctionableConfig",
    "BypassConfig",
    "PermissionsConfig",
    "load_permissions",
    "save_permissions",
    "reload_permissions",
    "can_use",
    "is_sanctionable",
    "is_bypassed",
    "get_command_categories",
    "get_category_labels",
    "list_commands_in_category",
    "list_categories",
]
