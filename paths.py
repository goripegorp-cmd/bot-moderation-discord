"""
paths.py - Helpers de chemins compatibles local + Railway/Heroku.

Sur les hosts qui utilisent un volume persistant (ex: Railway monte /data),
on stocke les donnees JSON dans /data/<module>/. Sinon (dev local), on
utilise ./data/<module>/.

DEFENSIVE : si rien n'est ecrivable, on retombe sur /tmp pour ne JAMAIS
crash le bot au boot. Les donnees seront perdues au redemarrage mais le
bot reste fonctionnel.

API:
    base_data_dir() -> Path  : racine "data" persistante
    module_dir(name) -> Path : sous-dossier du module (cree si absent)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


_RESOLVED_BASE: Path | None = None


def _try_dir(p: Path) -> bool:
    """Test si un repertoire est ecrivable (et cree-le)."""
    try:
        p.mkdir(parents=True, exist_ok=True)
        # Test d'ecriture reel
        test_file = p / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return True
    except (OSError, PermissionError):
        return False


def base_data_dir() -> Path:
    """Retourne le repertoire racine pour la persistance.

    Cascade defensive :
    1. /data (Railway volume) si existe ET ecrivable
    2. ./data (cwd) si ecrivable
    3. /tmp/bot_data (fallback systeme)
    """
    global _RESOLVED_BASE
    if _RESOLVED_BASE is not None:
        return _RESOLVED_BASE

    # 1. /data Railway
    persistent = Path("/data")
    if persistent.exists() and persistent.is_dir() and _try_dir(persistent):
        _RESOLVED_BASE = persistent
        return _RESOLVED_BASE

    # 2. ./data local
    local_data = Path("data")
    if _try_dir(local_data):
        _RESOLVED_BASE = local_data.resolve()
        return _RESOLVED_BASE

    # 3. /tmp fallback (ephemere mais ne crash pas)
    tmp_data = Path(tempfile.gettempdir()) / "bot_data"
    if _try_dir(tmp_data):
        print(f"⚠️  [PATHS] Aucun volume persistant ecrivable, fallback sur {tmp_data}. "
              f"Les donnees seront PERDUES au redemarrage.")
        _RESOLVED_BASE = tmp_data
        return _RESOLVED_BASE

    # 4. Dernier recours : cwd direct
    _RESOLVED_BASE = Path(".").resolve()
    print(f"⚠️  [PATHS] Cas extreme : utilisation de {_RESOLVED_BASE}")
    return _RESOLVED_BASE


def module_dir(name: str) -> Path:
    """Retourne (et cree au besoin) un sous-dossier d'un module.

    Defensive : si la creation echoue, retourne le path quand meme.
    Les modules doivent gerer les erreurs d'IO en aval.
    """
    p = base_data_dir() / name
    try:
        p.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as ex:
        print(f"⚠️  [PATHS] mkdir {p} echoue : {ex}")
    return p


__all__ = ["base_data_dir", "module_dir"]
