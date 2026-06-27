"""nsfw_scan.py — Détection d'IMAGES sexuelles explicites par IA (owner 2026-06-27).

Protection des mineurs : repère une photo nue / sexuellement explicite (que l'OCR, qui ne lit que
le TEXTE, ne peut pas voir). Moteur : nudenet (onnxruntime, modèle ONNX léger).

⚠️ ANTI-CRASH / ANTI-OOM (priorité : ne JAMAIS faire tomber le bot de sécurité) :
  • GARDE MÉMOIRE : on ne CHARGE le modèle que si la RAM disponible ≥ `_MIN_FREE_MB` (sinon on se
    désactive proprement — pas d'OOM). Lecture de /proc/meminfo (Linux/Railway).
  • LAZY : le modèle n'est chargé qu'au 1er scan (ou au boot via available()), une seule fois.
  • 100 % FAIL-SAFE : tout échec (import, téléchargement du modèle, RAM, inférence) → désactivé,
    le bot continue normalement.
  • Inférence SYNCHRONE et CPU → l'appelant DOIT l'exécuter dans un thread (run_in_executor).
"""
from __future__ import annotations

import io  # noqa: F401  (réservé)
import os

_DETECTOR = None
_AVAILABLE = None       # cache: True / False
_MIN_FREE_MB = 500      # ne charge pas le modèle si moins de RAM dispo (marge anti-OOM)

# Labels nudenet « explicites » qui justifient une action (on IGNORE covered/face/feet/belly…).
_EXPLICIT = {
    "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED", "BUTTOCKS_EXPOSED",
}
_SCORE_THRESHOLD = 0.60   # confiance mini pour agir


def _free_mem_mb():
    """RAM disponible en Mo (MemAvailable), ou None si illisible (≠ Linux)."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return None


def _load() -> bool:
    global _DETECTOR, _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    fm = _free_mem_mb()
    if fm is not None and fm < _MIN_FREE_MB:
        _AVAILABLE = False
        print(f"[nsfw_scan] désactivé : RAM dispo {fm} Mo < {_MIN_FREE_MB} Mo (anti-OOM) — "
              f"détection NSFW OFF (le reste tourne). Augmente la RAM Railway pour l'activer.")
        return False
    try:
        from nudenet import NudeDetector
        _DETECTOR = NudeDetector()      # télécharge + charge le modèle ONNX (1 fois)
        _AVAILABLE = True
        print(f"[nsfw_scan] prêt (nudenet, RAM dispo {fm if fm is not None else '?'} Mo)")
    except Exception as ex:
        _AVAILABLE = False
        print(f"[nsfw_scan] indisponible ({ex}) — détection NSFW désactivée (fail-safe)")
    return _AVAILABLE


def available() -> bool:
    return _load()


def is_nsfw(image_bytes):
    """SYNC (à lancer via run_in_executor). Renvoie (is_nsfw: bool, label: str, score: float).
    FAIL-SAFE → (False, '', 0.0)."""
    if not _load() or _DETECTOR is None:
        return False, "", 0.0
    import tempfile
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(image_bytes)
            path = tf.name
        dets = _DETECTOR.detect(path) or []
        best, label = 0.0, ""
        for d in dets:
            try:
                cls = str(d.get("class") or d.get("label") or "").upper()
                sc = float(d.get("score") or d.get("confidence") or 0.0)
            except Exception:
                continue
            if cls in _EXPLICIT and sc > best:
                best, label = sc, cls
        return (best >= _SCORE_THRESHOLD), label, best
    except Exception:
        return False, "", 0.0
    finally:
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass
