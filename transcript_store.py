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

# Bornes anti-abus (un ticket ne doit pas pouvoir remplir le disque partagé /data).
_MAX_ASSETS = 60
_MAX_ASSET_BYTES = 12 * 1024 * 1024        # 12 Mo/asset ré-hébergé (au-delà → lien CDN)
_MAX_TICKET_BYTES = 64 * 1024 * 1024       # 64 Mo TOTAL ré-hébergé par ticket
_MIN_FREE_BYTES = 300 * 1024 * 1024        # plancher d'espace libre : en-dessous → pas de ré-héberg.
# SÉCURITÉ : on ne ré-héberge QUE des images matricielles (jamais de SVG → XSS same-origin).
_ALLOWED_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


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
    # SÉCURITÉ : extension matricielle uniquement (SVG/HTML exclus → pas d'XSS same-origin).
    safe_ext = re.sub(r'[^a-z0-9]', '', (ext or '').lower())[:5]
    if safe_ext == 'jpe':
        safe_ext = 'jpg'
    if safe_ext not in _ALLOWED_EXTS:
        return None
    # Garde-fou disque : ne pas saturer le volume partagé (DB/backups vivent sur /data).
    try:
        if shutil.disk_usage(_BASE_DIR if os.path.isdir(_BASE_DIR) else '.').free < _MIN_FREE_BYTES:
            return None
    except Exception:
        pass
    _ensure(d)
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


class _Lecteur:
    """Relit un transcript écrit par `_render_ticket_transcript_html` (bot.py) : div.msg > img.avatar
    + div.mbody > [div.mhead > span.author, span.bot, span.ts] + div.content + div.embed (div.etitle,
    div, div.efield > b, div.efooter, img.att) + img.att | video.att | div > a. Le texte du message
    est échappé à l'écriture : rien dedans ne peut passer pour une balise."""

    _VIDES = {"img", "br", "video", "source", "meta", "link", "hr", "input"}

    def __init__(self):
        from html.parser import HTMLParser
        lecteur = self

        class _P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                lecteur._ouvre(tag, dict(attrs))

            def handle_startendtag(self, tag, attrs):
                lecteur._ouvre(tag, dict(attrs))

            def handle_endtag(self, tag):
                lecteur._ferme(tag)

            def handle_data(self, data):
                lecteur._texte(data)
        self._p = _P(convert_charrefs=True)
        self.messages: list = []
        self._m = None
        self._e = None
        self._pile: list = []  # [(balise, rôle)]

    def lire(self, html: str) -> list:
        self._p.feed(html)
        self._p.close()
        for m in self.messages:
            m["texte"] = m["texte"].strip()
            if m["texte"] == "[média]":
                m["texte"] = ""
            m["auteur"] = m["auteur"].strip()
            ts = m.pop("_ts").strip()
            if m["quand"] is None and ts:
                try:  # anciens transcripts : l'heure UTC de Discord, sans attribut
                    from datetime import datetime, timezone
                    m["quand"] = int(datetime.strptime(ts, "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc).timestamp())
                except ValueError:
                    m["quand"] = None
            for e in m["embeds"]:
                e["titre"], e["texte"], e["pied"] = e["titre"].strip(), e["texte"].strip(), e["pied"].strip()
                e["champs"] = [[n.strip(), v.strip()] for n, v in e["champs"]]
            m["embeds"] = [e for e in m["embeds"] if e["titre"] or e["texte"] or e["champs"] or e["pied"]]
            for f in m["fichiers"]:
                f["nom"] = f["nom"].replace("📎", "").strip() or "fichier"
        return self.messages

    def _role(self):
        for _tag, role in reversed(self._pile):
            if role:
                return role
        return None

    def _ouvre(self, tag, a):
        classes = set((a.get("class") or "").split())
        if tag == "br":
            self._texte("\n")
            return
        m = self._m
        if tag == "img":
            src = a.get("src") or ""
            if m is not None and "avatar" in classes:
                m["avatar"] = src
            elif m is not None and src:
                m["images"].append(src)
            return
        if tag == "video":
            if m is not None and a.get("src"):
                m["videos"].append(a["src"])
            return
        if tag in self._VIDES:
            return
        role = None
        if tag == "div" and "msg" in classes:
            t = a.get("data-t")
            self._m = m = {"auteur": "", "avatar": "", "bot": False,
                           "quand": int(t) if t and t.isdigit() else None, "texte": "", "images": [],
                           "videos": [], "fichiers": [], "embeds": [], "_ts": ""}
            self._e = None
            self.messages.append(m)
            role = "msg"
        elif m is not None:
            parent = self._role()
            if tag == "span" and "author" in classes:
                role = "auteur"
            elif tag == "span" and "bot" in classes:
                m["bot"], role = True, "muet"
            elif tag == "span" and "ts" in classes:
                role = "ts"
            elif tag == "div" and "content" in classes:
                role = "texte"
            elif tag == "div" and "embed" in classes:
                self._e = {"titre": "", "texte": "", "champs": [], "pied": ""}
                m["embeds"].append(self._e)
                role = "embed"
            elif tag == "div" and "etitle" in classes:
                role = "etitre"
            elif tag == "div" and "efield" in classes:
                if self._e is not None:
                    self._e["champs"].append(["", ""])
                role = "echamp"
            elif tag == "b" and parent == "echamp":
                role = "echamp_nom"
            elif tag == "div" and "efooter" in classes:
                role = "epied"
            elif tag == "div" and parent == "embed":
                role = "etexte"
            elif tag == "a" and a.get("href"):
                m["fichiers"].append({"nom": "", "url": a["href"]})
                role = "fichier"
            elif tag == "i" and parent == "texte":
                role = "muet"
        self._pile.append((tag, role))

    def _ferme(self, tag):
        for k in range(len(self._pile) - 1, -1, -1):
            if self._pile[k][0] == tag:
                role = self._pile[k][1]
                del self._pile[k:]
                if role == "msg":
                    self._m, self._e = None, None
                elif role == "embed":
                    self._e = None
                return

    def _texte(self, data):
        m, role = self._m, self._role()
        if m is None or role in (None, "msg", "muet", "embed"):
            return
        if role == "auteur":
            m["auteur"] += data
        elif role == "ts":
            m["_ts"] += data
        elif role == "texte":
            m["texte"] += data
        elif role == "fichier" and m["fichiers"]:
            m["fichiers"][-1]["nom"] += data
        elif self._e is not None:
            if role == "etitre":
                self._e["titre"] += data
            elif role == "etexte":
                self._e["texte"] += data
            elif role == "epied":
                self._e["pied"] += data
            elif role == "echamp_nom" and self._e["champs"]:
                self._e["champs"][-1][0] += data
            elif role == "echamp" and self._e["champs"]:
                self._e["champs"][-1][1] += data


def lire_conversation(token: str):
    """Les messages d'un transcript enregistré (liste de dicts), ou None s'il n'existe plus (purge
    de rétention) ou si le jeton est invalide. Sync (via to_thread) — lecture d'un fichier."""
    p = transcript_path(token)
    if not p or not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return _Lecteur().lire(f.read())


def jeton_de(url: str):
    """Le jeton d'une adresse de transcript (« …/t/<jeton> »), ou None."""
    jeton = str(url or "").rstrip("/").rsplit("/t/", 1)[-1] if "/t/" in str(url or "") else ""
    return jeton if _valid(jeton) else None


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


def plafonner() -> int:
    """14/10 : au plus `stockage.PART_TRANSCRIPTS` du volume ; au-delà, les plus
    anciens transcripts partent d'abord (jusqu'à 64 Mo d'images par ticket :
    120 jours de tickets pouvaient remplir le volume). Sync (via to_thread)."""
    try:
        import stockage
        return stockage.plafonner_dossier(_BASE_DIR, stockage.PART_TRANSCRIPTS)
    except Exception as ex:
        print(f"[transcript_store plafonner] {ex}")
        return 0


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
