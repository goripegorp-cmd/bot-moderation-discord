"""
backup_system.py - Sauvegarde & restauration de la configuration (Phase 1.1).

Permet a l'owner de sauvegarder l'integralite de la config d'un serveur et
de la restaurer en cas de probleme.

Strategie :
- Sauvegardes versionnees (timestamp + label optionnel)
- Stockage JSON sur disque, un dossier par guild
- Retention 30 jours par defaut (configurable)
- Auto-backup avant chaque modification majeure
- Restauration totale ou partielle (par module)

API:
    - await create_backup(guild_id, sources, label=None) -> BackupInfo
    - await list_backups(guild_id) -> list[BackupInfo]
    - await load_backup(guild_id, backup_id) -> dict
    - await restore_backup(guild_id, backup_id, modules=None) -> RestoreReport
    - await delete_backup(guild_id, backup_id) -> bool
    - await prune_old_backups(guild_id, max_age_days=30) -> int

Format de sauvegarde (JSON) :
{
  "version": 1,
  "guild_id": 123,
  "created_at": "2026-05-07T13:00:00Z",
  "label": "Avant refactor anti-raid",
  "sources": ["main_config", "permissions", "leveling"],
  "data": {
    "main_config": {...},
    "permissions": {...},
    ...
  }
}
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


# =============================================================================
# CONSTANTES
# =============================================================================

from paths import module_dir
DATA_DIR = module_dir("backups")

CURRENT_VERSION = 1
DEFAULT_RETENTION_DAYS = 30
MAX_BACKUPS_PER_GUILD = 50  # garde-fou


# =============================================================================
# MODELES
# =============================================================================

@dataclass
class BackupInfo:
    """Metadonnees d'une sauvegarde (sans les donnees lourdes)."""

    backup_id: str
    guild_id: int
    created_at: str          # ISO 8601 UTC
    label: Optional[str]
    sources: list[str]       # quels modules sont inclus
    size_bytes: int

    def created_dt(self) -> datetime:
        return datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))

    def age_days(self) -> float:
        return (datetime.now(timezone.utc) - self.created_dt()).total_seconds() / 86400


@dataclass
class RestoreReport:
    """Rapport d'une operation de restauration."""

    backup_id: str
    restored_modules: list[str] = field(default_factory=list)
    skipped_modules: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    pre_restore_backup_id: Optional[str] = None

    @property
    def success(self) -> bool:
        return not self.errors


# =============================================================================
# REGISTRE DES SOURCES (modules sauvegardables)
# =============================================================================
# Chaque module peut s'enregistrer avec un loader (export) et un saver (restore).
# Le registre permet d'ajouter de nouveaux modules sans toucher au code core.

ExporterFunc = Callable[[int], Awaitable[Any]]
ImporterFunc = Callable[[int, Any], Awaitable[None]]


@dataclass
class BackupSource:
    """Source de donnees sauvegardable."""

    key: str                # identifiant unique (ex: "permissions", "main_config")
    label: str              # nom affichable
    exporter: ExporterFunc  # fonction async qui retourne les donnees a sauvegarder
    importer: ImporterFunc  # fonction async qui restaure les donnees
    is_critical: bool = False  # si True, sauvegarde par defaut
    description: str = ""


_sources: dict[str, BackupSource] = {}


def register_source(source: BackupSource) -> None:
    """Enregistre une source sauvegardable."""
    _sources[source.key] = source


def get_source(key: str) -> Optional[BackupSource]:
    return _sources.get(key)


def list_sources() -> list[BackupSource]:
    return list(_sources.values())


def list_critical_sources() -> list[str]:
    return [s.key for s in _sources.values() if s.is_critical]


# =============================================================================
# AUTO-ENREGISTREMENT : permissions
# =============================================================================
# La source "permissions" est enregistree automatiquement car elle vient du meme
# package. Les autres sources s'enregistrent depuis bot.py au demarrage.

async def _export_permissions(guild_id: int) -> dict:
    from permissions import load_permissions
    cfg = await load_permissions(guild_id)
    return cfg.to_dict()


async def _import_permissions(guild_id: int, data: dict) -> None:
    from permissions import PermissionsConfig, save_permissions
    cfg = PermissionsConfig.from_dict(data)
    await save_permissions(guild_id, cfg)


register_source(BackupSource(
    key="permissions",
    label="Permissions granulaires",
    exporter=_export_permissions,
    importer=_import_permissions,
    is_critical=True,
    description="Roles autorises/refuses, sanctionables, bypasses",
))


# =============================================================================
# STOCKAGE
# =============================================================================

def _guild_dir(guild_id: int) -> Path:
    p = DATA_DIR / str(guild_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _backup_path(guild_id: int, backup_id: str) -> Path:
    return _guild_dir(guild_id) / f"{backup_id}.json"


_io_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_backup_id() -> str:
    """ID = timestamp court + uuid pour eviter les collisions."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{ts}-{suffix}"


# =============================================================================
# OPERATIONS PUBLIQUES
# =============================================================================

async def create_backup(
    guild_id: int,
    sources: Optional[list[str]] = None,
    label: Optional[str] = None,
) -> BackupInfo:
    """Cree une sauvegarde des sources demandees (ou toutes les critiques par defaut)."""
    if sources is None:
        sources = list_critical_sources()

    data: dict[str, Any] = {}
    for key in sources:
        source = _sources.get(key)
        if not source:
            continue
        try:
            data[key] = await source.exporter(guild_id)
        except Exception as exc:
            data[key] = {"__error__": f"{type(exc).__name__}: {exc}"}

    backup_id = _new_backup_id()
    payload = {
        "version": CURRENT_VERSION,
        "guild_id": guild_id,
        "backup_id": backup_id,
        "created_at": _now_iso(),
        "label": label,
        "sources": sources,
        "data": data,
    }

    async with _io_lock:
        path = _backup_path(guild_id, backup_id)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        size = path.stat().st_size

    info = BackupInfo(
        backup_id=backup_id,
        guild_id=guild_id,
        created_at=payload["created_at"],
        label=label,
        sources=sources,
        size_bytes=size,
    )

    # Enforce le quota
    await _enforce_quota(guild_id)
    return info


async def list_backups(guild_id: int) -> list[BackupInfo]:
    """Liste les sauvegardes disponibles, plus recentes en premier."""
    async with _io_lock:
        gdir = _guild_dir(guild_id)
        infos: list[BackupInfo] = []
        for path in gdir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                infos.append(BackupInfo(
                    backup_id=payload.get("backup_id", path.stem),
                    guild_id=payload.get("guild_id", guild_id),
                    created_at=payload.get("created_at", ""),
                    label=payload.get("label"),
                    sources=payload.get("sources", []),
                    size_bytes=path.stat().st_size,
                ))
            except (json.JSONDecodeError, KeyError):
                continue
        infos.sort(key=lambda b: b.created_at, reverse=True)
        return infos


async def load_backup(guild_id: int, backup_id: str) -> Optional[dict]:
    """Charge le contenu complet d'une sauvegarde."""
    async with _io_lock:
        path = _backup_path(guild_id, backup_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


async def delete_backup(guild_id: int, backup_id: str) -> bool:
    """Supprime une sauvegarde."""
    async with _io_lock:
        path = _backup_path(guild_id, backup_id)
        if not path.exists():
            return False
        path.unlink()
        return True


async def restore_backup(
    guild_id: int,
    backup_id: str,
    modules: Optional[list[str]] = None,
    auto_backup_before: bool = True,
) -> RestoreReport:
    """Restaure une sauvegarde.

    - `modules=None` : restaure tous les modules de la sauvegarde
    - `modules=[...]` : restaure seulement ces modules
    - `auto_backup_before` : cree une sauvegarde de l'etat actuel avant restauration
    """
    payload = await load_backup(guild_id, backup_id)
    if payload is None:
        return RestoreReport(
            backup_id=backup_id,
            errors={"_backup": "introuvable"},
        )

    backup_data = payload.get("data", {})
    target_modules = modules if modules is not None else list(backup_data.keys())

    pre_id: Optional[str] = None
    if auto_backup_before:
        pre = await create_backup(
            guild_id,
            sources=target_modules,
            label=f"Auto-backup avant restore {backup_id}",
        )
        pre_id = pre.backup_id

    report = RestoreReport(backup_id=backup_id, pre_restore_backup_id=pre_id)

    for module_key in target_modules:
        if module_key not in backup_data:
            report.skipped_modules.append(module_key)
            continue
        source = _sources.get(module_key)
        if not source:
            report.errors[module_key] = "source non enregistree"
            continue
        module_data = backup_data[module_key]
        if isinstance(module_data, dict) and "__error__" in module_data:
            report.errors[module_key] = f"sauvegarde corrompue: {module_data['__error__']}"
            continue
        try:
            await source.importer(guild_id, module_data)
            report.restored_modules.append(module_key)
        except Exception as exc:
            report.errors[module_key] = f"{type(exc).__name__}: {exc}"

    return report


async def prune_old_backups(
    guild_id: int,
    max_age_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """Supprime les sauvegardes plus anciennes que `max_age_days`.

    Garde toujours au moins la sauvegarde la plus recente.
    Retourne le nombre de sauvegardes supprimees.
    """
    backups = await list_backups(guild_id)
    if len(backups) <= 1:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    deleted = 0
    # Garde la plus recente (backups[0]), examine les autres
    for info in backups[1:]:
        if info.created_dt() < cutoff:
            await delete_backup(guild_id, info.backup_id)
            deleted += 1
    return deleted


async def _enforce_quota(guild_id: int) -> None:
    """Garde-fou : si plus de MAX_BACKUPS_PER_GUILD, supprime les plus anciennes."""
    backups = await list_backups(guild_id)
    if len(backups) <= MAX_BACKUPS_PER_GUILD:
        return
    excess = backups[MAX_BACKUPS_PER_GUILD:]
    for info in excess:
        await delete_backup(guild_id, info.backup_id)


# =============================================================================
# UTILITAIRES UI
# =============================================================================

def format_backup_short(info: BackupInfo) -> str:
    """Format compact pour une liste de backups."""
    age = info.age_days()
    if age < 1:
        age_str = f"il y a {int(age * 24)}h"
    elif age < 30:
        age_str = f"il y a {int(age)}j"
    else:
        age_str = f"il y a {int(age / 30)}mois"
    label = f" - **{info.label}**" if info.label else ""
    size_kb = info.size_bytes / 1024
    return f"`{info.backup_id}`{label} ({age_str}, {size_kb:.1f} KB)"


def format_backup_full(info: BackupInfo) -> str:
    """Format complet d'une fiche backup."""
    sources_str = ", ".join(info.sources) if info.sources else "(aucun module)"
    label_str = info.label or "(sans label)"
    return (
        f"**ID** : `{info.backup_id}`\n"
        f"**Label** : {label_str}\n"
        f"**Cree le** : {info.created_at}\n"
        f"**Modules** : {sources_str}\n"
        f"**Taille** : {info.size_bytes / 1024:.1f} KB"
    )


__all__ = [
    "BackupInfo",
    "RestoreReport",
    "BackupSource",
    "register_source",
    "get_source",
    "list_sources",
    "list_critical_sources",
    "create_backup",
    "list_backups",
    "load_backup",
    "delete_backup",
    "restore_backup",
    "prune_old_backups",
    "format_backup_short",
    "format_backup_full",
]
