"""diag.py — Journal de DIAGNOSTIC structuré, lisible sur Railway (owner 2026-07-17).

BUT : quand l'owner colle les logs Railway, on voit D'UN COUP d'où vient un problème — une vidéo
qui ne se poste pas, une suppression qui échoue, un module qui rate — avec le MODULE, l'ÉVÉNEMENT
et la cause. PAS du bruit de crash aléatoire : des lignes STRUCTURÉES et FILTRABLES.

POURQUOI stderr : `_QuietStdout` (bot.py) avale les lignes « [tag] … » de stdout sauf VERBOSE_LOGS=1.
Toutes les lignes de diag vont donc sur **stderr**, TOUJOURS visibles sur Railway (déploiement + run).

FORMAT (une ligne, greppable) :
    [DIAG] <ISO-UTC> <LEVEL> <module>/<event> :: <detail>[ | err=<Type>: <msg>]
Exemples :
    [DIAG] 2026-07-17T18:50:03Z EVENT social/youtube_post :: @CaribBros → #videos (msg 123)
    [DIAG] 2026-07-17T18:50:04Z ERROR social/youtube_post :: @RellGames | err=ClientError: 403
    [DIAG] 2026-07-17T18:50:05Z WARN  game_status/roblox :: statut indéterminé (page illisible)

FILTRAGE Railway :
    grep [DIAG]                → tout le diagnostic
    grep '[DIAG].* ERROR '     → uniquement les erreurs
    grep '[DIAG] .*/social'    → un module précis

API — toutes FAIL-SAFE (ne lèvent JAMAIS, ne bloquent jamais l'appelant) :
    diag.event(module, event, detail="")           → succès/événement NOTABLE, TOUJOURS affiché
    diag.warn (module, event, detail="")           → avertissement, TOUJOURS affiché
    diag.error(module, event, detail="", exc=None)  → erreur + type/msg de l'exception (+ trace si verbose)
    diag.trace(module, event, detail="")           → debug détaillé, affiché SEULEMENT si DIAG_VERBOSE=1

⚠️ NE PAS appeler depuis un chemin CHAUD (on_message par message) — réservé aux opérations NOTABLES
(publications, suppressions, résolutions, sanctions, tâches de fond).
"""
from __future__ import annotations

import os as _os
import sys as _sys
import traceback as _traceback
from datetime import datetime, timezone

_VERBOSE = _os.getenv("DIAG_VERBOSE", "0") == "1"
_PREFIX = "[DIAG]"


def _emit(level: str, module: str, event: str, detail: str = "", exc=None) -> None:
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"{_PREFIX} {ts} {level:<5} {str(module)}/{str(event)}"
        if detail:
            line += f" :: {str(detail)[:400]}"
        if exc is not None:
            line += f" | err={type(exc).__name__}: {str(exc)[:200]}"
        print(line, file=_sys.stderr, flush=True)
        if exc is not None and _VERBOSE:
            _traceback.print_exception(type(exc), exc, exc.__traceback__, file=_sys.stderr)
    except Exception:
        # Un logger ne doit JAMAIS casser l'appelant.
        pass


def event(module: str, event_name: str, detail: str = "") -> None:
    """Événement NOTABLE et de FAIBLE volume (vidéo postée, jeu down, sanction…). Toujours affiché."""
    _emit("EVENT", module, event_name, detail)


def warn(module: str, event_name: str, detail: str = "") -> None:
    _emit("WARN", module, event_name, detail)


def error(module: str, event_name: str, detail: str = "", exc=None) -> None:
    _emit("ERROR", module, event_name, detail, exc)


def trace(module: str, event_name: str, detail: str = "") -> None:
    """Debug détaillé — affiché SEULEMENT si DIAG_VERBOSE=1 (sinon silencieux, zéro flood)."""
    if _VERBOSE:
        _emit("TRACE", module, event_name, detail)


def boot(detail: str = "") -> None:
    """Ligne de démarrage : confirme que le diagnostic est actif (visible au déploiement Railway)."""
    _emit("EVENT", "boot", "diagnostics",
          (detail + " · " if detail else "")
          + f"actif (verbose={'ON' if _VERBOSE else 'OFF'}) — filtre Railway : grep [DIAG]")


__all__ = ["event", "warn", "error", "trace", "boot"]
