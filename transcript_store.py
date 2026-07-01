"""
transcript_store.py — Phase 281 : stockage + service web des transcripts de tickets.

POURQUOI (owner 2026-07-01) : le transcript de ticket était envoyé en pièce jointe `.html`
→ Discord l'affiche en CODE BRUT (il ne rend jamais le HTML des attachments). L'owner veut
un LIEN cliquable qui ouvre la VRAIE page rendue, avec TOUT le contenu (texte, images, GIFs).

COMMENT : on écrit le HTML rendu + les IMAGES ré-hébergées sur le volume persistant Railway
(`/data`), et le petit serveur HTTP déjà présent (`health_server.py`, port public Railway) sert
`GET /t/<token>` (page rendue) et `GET /ta/<token>/<idx>` (asset). Le lien est donc self-hosted
(zéro service tiers → conforme vie privée) et permanent (jusqu'à la purge de rétention).

SÉCURITÉ :
- token URL-safe non devinable (secrets) → pas d'énumération des tickets (transcripts = PII).
- validation stricte du token (regex) → ZÉRO path traversal (jamais de segment utilisateur brut
  dans un chemin).
- rétention : purge des transcripts plus vieux que TRANSCRIPT_RETENTION_DAYS (RGPD-friendly).
- lecture seule ; aucune écriture via HTTP.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import time

# Répertoire persistant (même logique que DB_PATH dans bot.py : /data sur Railway).
_BASE_DIR = '/data/transcripts' if os.path.isdir('/data') else os.path.join('.', 'data', 'transcripts')
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{16,86}$')
try:
    _RETENTION_DAYS = max(1, int(os.environ.get('TRANSCRIPT_RETENTION_DAYS', '120') or 120))
except Exception:
    _RETENTION_DAYS = 120

# Bornes anti-abus (un ticket ne doit pas pouvoir remplir le disque).
_MAX_ASSETS = 60
_MAX_ASSET_BYTES = 12 * 1024 * 1024   # 12 Mo/asset ré-hébergé (au-delà → lien CDN)


def base_dir() -> str:
    return _BASE_DIR


def new_token() -> str:
    return secrets.token_urlsafe(16)


def _valid(token: str) -> bool:
    return bool(token) and bool(_TOKEN_RE.match(token))


def _ensure(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def transcript_path(token: str):
    """Chemin ABSOLU du fichier HTML pour ce token, ou None si token invalide (anti-traversal)."""
    if not _valid(token):
        return None
    return os.path.join(_BASE_DIR, token + '.html')


def _asset_dir(token: str):
    if not _valid(token):
        return None
    return os.path.join(_BASE_DIR, 'a_' + token)


def asset_file(token: str, idx):
    """Trouve le fichier d'asset `<idx>.<ext>` (ext inconnue) pour le service HTTP. None si absent."""
    d = _asset_dir(token)
    if d is None:
        return None
    try:
        i = int(idx)
    except Exception:
        return None
    if i < 0 or i > 100000:
        return None
    try:
        prefix = f'{i}.'
        for name in os.listdir(d):
            if name.startswith(prefix) and '/' not in name and '\\' not in name:
                return os.path.join(d, name)
    except Exception:
        return None
    return None


def save_html(token: str, html: str):
    """Écrit le HTML du transcript (sync — appeler via asyncio.to_thread). Retourne le chemin ou None."""
    p = transcript_path(token)
    if not p or html is None:
        return None
    _ensure(_BASE_DIR)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(html)
        return p
    except Exception as ex:
        print(f"[transcript_store save_html] {ex}")
        return None


def save_asset(token: str, idx: int, data: bytes, ext: str):
    """Écrit un asset ré-hébergé (image/gif). Sync. Retourne le CHEMIN URL servi (/ta/..) ou None."""
    d = _asset_dir(token)
    if d is None or not data:
        return None
    if len(data) > _MAX_ASSET_BYTES:
        return None
    _ensure(d)
    safe_ext = re.sub(r'[^a-z0-9]', '', (ext or 'bin').lower())[:5] or 'bin'
    try:
        i = int(idx)
    except Exception:
        return None
    p = os.path.join(d, f'{i}.{safe_ext}')
    try:
        with open(p, 'wb') as f:
            f.write(data)
        return f'/ta/{token}/{i}'
    except Exception as ex:
        print(f"[transcript_store save_asset] {ex}")
        return None


def public_base_url():
    """URL publique de base (sans slash final), ou None si aucun domaine configuré.
    Priorité : TRANSCRIPT_BASE_URL (manuel) puis RAILWAY_PUBLIC_DOMAIN (auto Railway)."""
    dom = (os.environ.get('TRANSCRIPT_BASE_URL') or os.environ.get('RAILWAY_PUBLIC_DOMAIN') or '').strip()
    if not dom:
        return None
    dom = dom.rstrip('/')
    if not dom.lower().startswith(('http://', 'https://')):
        dom = 'https://' + dom
    return dom


def transcript_url(token: str):
    """URL publique du transcript, ou None si pas de domaine (→ l'appelant retombe sur la pièce jointe)."""
    if not _valid(token):
        return None
    b = public_base_url()
    return f'{b}/t/{token}' if b else None


def purge_old(max_age_days: int = None) -> int:
    """Supprime transcripts + assets plus vieux que la rétention. Retourne le nb d'éléments purgés.
    Sync (appeler via to_thread). FAIL-SAFE."""
    days = _RETENTION_DAYS if max_age_days is None else max(1, int(max_age_days))
    removed = 0
    try:
        if not os.path.isdir(_BASE_DIR):
            return 0
        cutoff = time.time() - days * 86400
        for name in list(os.listdir(_BASE_DIR)):
            p = os.path.join(_BASE_DIR, name)
            try:
                if os.path.getmtime(p) >= cutoff:
                    continue
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
                removed += 1
            except Exception:
                continue
    except Exception as ex:
        print(f"[transcript_store purge_old] {ex}")
    return removed
