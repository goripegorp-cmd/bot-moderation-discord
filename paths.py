"""
paths.py - Helpers de chemins compatibles local + Railway/Heroku.

Sur les hosts qui utilisent un volume persistant (ex: Railway monte /data),
on stocke les donnees JSON dans /data/<module>/. Sinon (dev local), on
utilise ./data/<module>/.

API:
    base_data_dir() -> Path  : racine "data" persistante
    module_dir(name) -> Path : sous-dossier du module (cree si absent)
"""
from __future__ import annotations

from pathlib import Path


def base_data_dir() -> Path:
    """Retourne le repertoire racine pour la persistance.

    - Si /data existe (volume monte par Railway/etc.), on l'utilise.
    - Sinon, ./data dans le cwd.
    """
    persistent = Path("/data")
    if persistent.exists() and persistent.is_dir():
        return persistent
    return Path("data")


def module_dir(name: str) -> Path:
    """Retourne (et cree au besoin) un sous-dossier d'un module."""
    p = base_data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


__all__ = ["base_data_dir", "module_dir"]
