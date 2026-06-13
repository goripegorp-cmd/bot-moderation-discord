"""
translate.py — Traduction à la demande via MyMemory (API GRATUITE, anonyme).

🎯 OBJECTIF (serveur MULTI-GAMING INTERNATIONAL) : permettre à un membre de
traduire d'UN CLIC le message d'un autre membre rédigé dans une langue qu'il ne
parle pas. Déclenché par une réaction 🌐 (cf. bot.py on_raw_reaction_add) ; la
traduction est postée DANS LE SALON (jamais en MP) et s'auto-supprime.

Module AUTONOME et FAIL-SAFE : aucune exception ne sort de translate().
Toute erreur (timeout / HTTP / quota / JSON invalide / API en panne) → None,
l'appelant se contente alors de ne rien faire.

API publique :
- async translate(text, target_lang, source_lang=None, *, timeout=6) -> str|None
- set_enabled(bool) / is_enabled() -> on/off lu par l'appelant
- setup(session_factory=None)   # injecte éventuellement une ClientSession partagée
- stats() -> dict               # diagnostic (cache/quota), facultatif

⚠️ VIE PRIVÉE : translate() envoie le texte à MyMemory (tiers). C'est OPT-IN
(un membre réagit volontairement 🌐) et DÉSACTIVABLE (toggle entraide_enabled +
cfg translate_enabled côté bot, plus set_enabled() ici). À documenter côté UI.

Limites MyMemory (free / anonyme) :
- ~500 caractères par requête → on TRONQUE à MAX_CHARS (480) pour rester sous la barre.
- quota quotidien limité côté MyMemory → on s'auto-plafonne (DAILY_CAP) AVANT
  d'appeler, pour ne jamais se faire bannir et rester poli avec le service gratuit.
- source REQUISE par MyMemory (langpair=src|tgt). L'appelant fournit la source
  (langue de l'auteur, ou langue principale du serveur). On refuse si src manque.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

try:
    import aiohttp  # déjà une dépendance du bot (cf. usages ClientSession ailleurs)
except Exception:  # pragma: no cover — fail-safe import
    aiohttp = None

# ─── Paramètres ──────────────────────────────────────────────────────────────
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MAX_CHARS = 480              # tronque sous la limite ~500 du tier anonyme
DEFAULT_TIMEOUT = 6         # timeout court : chemin déclenché par une réaction
CACHE_MAX = 1000            # borne du cache mémoire (évite de retraduire / fuite mémoire)
DAILY_CAP = 800             # plafond GLOBAL prudent d'appels réseau / jour (free tier)

# Codes supportés côté bot (calque i18n.SUPPORTED_LANGS). On valide localement
# pour ne jamais envoyer un langpair absurde à MyMemory.
_SUPPORTED = ("fr", "en", "es", "de", "it", "pt")

# ─── État interne ────────────────────────────────────────────────────────────
_enabled = True                          # on/off lu par l'appelant (toggle global)
_session_factory = None                  # éventuelle fabrique de ClientSession partagée
_cache: dict = {}                        # (hash(text), source, target) -> str
_cache_order: list = []                  # FIFO pour borner le cache
_calls_today = 0                         # compteur d'appels réseau effectifs (anti-abus)
_calls_day = None                        # jour (date ISO) du compteur courant
_lock = asyncio.Lock()                   # protège compteur quotidien (réinit atomique)


def setup(session_factory=None):
    """Injecte (optionnellement) une fabrique de ClientSession partagée.

    Si non fournie, translate() ouvre une session jetable par appel (acceptable
    sur ce chemin froid déclenché à la main par un membre). FAIL-SAFE."""
    global _session_factory
    if session_factory is not None:
        _session_factory = session_factory


def set_enabled(value: bool):
    """Active/désactive globalement la traduction (l'appelant lit is_enabled())."""
    global _enabled
    _enabled = bool(value)


def is_enabled() -> bool:
    return _enabled


def stats() -> dict:
    """Diagnostic léger (jamais d'exception)."""
    return {
        "enabled": _enabled,
        "cache_size": len(_cache),
        "calls_today": _calls_today,
        "calls_day": _calls_day,
        "daily_cap": DAILY_CAP,
    }


def _norm(lang) -> str | None:
    """Normalise un code langue vers un code supporté (sinon None). FAIL-SAFE."""
    try:
        s = str(getattr(lang, "value", lang) or "").strip().lower()
        if not s:
            return None
        if s in _SUPPORTED:
            return s
        root = s.split("-", 1)[0]
        return root if root in _SUPPORTED else None
    except Exception:
        return None


def _cache_get(key):
    return _cache.get(key)


def _cache_put(key, value):
    """Insère dans le cache borné (FIFO). FAIL-SAFE."""
    try:
        if key in _cache:
            return
        _cache[key] = value
        _cache_order.append(key)
        while len(_cache_order) > CACHE_MAX:
            old = _cache_order.pop(0)
            _cache.pop(old, None)
    except Exception:
        pass


async def _bump_quota() -> bool:
    """Incrémente le compteur quotidien d'appels réseau ; renvoie False si le
    plafond GLOBAL du jour est atteint (→ l'appelant doit renoncer). Réinit auto
    à chaque changement de jour (UTC). FAIL-SAFE : True (ne bloque pas) si pépin."""
    global _calls_today, _calls_day
    try:
        async with _lock:
            today = datetime.now(timezone.utc).date().isoformat()
            if _calls_day != today:
                _calls_day = today
                _calls_today = 0
            if _calls_today >= DAILY_CAP:
                return False
            _calls_today += 1
            return True
    except Exception:
        return True


async def translate(text, target_lang, source_lang=None, *, timeout=DEFAULT_TIMEOUT):
    """Traduit `text` vers `target_lang` (source `source_lang`) via MyMemory.

    Renvoie la chaîne traduite, ou None en cas d'impossibilité (désactivé, texte
    vide, langues invalides, source==cible, quota atteint, timeout, HTTP/JSON KO,
    aiohttp indisponible…). N'EXPLOSE JAMAIS.

    - text          : message à traduire (TRONQUÉ à MAX_CHARS).
    - target_lang   : langue cible (code supporté).
    - source_lang   : langue source (REQUISE par MyMemory : si None → None).
    - timeout       : secondes (timeout court, chemin réaction).
    """
    try:
        if not _enabled or aiohttp is None:
            return None

        # Validation texte
        raw = (text or "").strip()
        if not raw:
            return None
        raw = raw[:MAX_CHARS]

        # Validation langues
        tgt = _norm(target_lang)
        src = _norm(source_lang)
        if tgt is None or src is None:
            return None  # MyMemory exige une source ; cible doit être supportée
        if src == tgt:
            return None  # rien à traduire

        # Cache (évite de retaper l'API pour un texte déjà vu)
        key = (hash(raw), src, tgt)
        cached = _cache_get(key)
        if cached is not None:
            return cached or None  # "" mis en cache = échec connu → None

        # Anti-abus : plafond quotidien GLOBAL (free tier) AVANT l'appel réseau
        if not await _bump_quota():
            return None

        params = {"q": raw, "langpair": f"{src}|{tgt}"}
        to = aiohttp.ClientTimeout(total=max(2, int(timeout)))

        async def _do(session) -> str | None:
            async with session.get(MYMEMORY_URL, params=params, timeout=to) as resp:
                if resp.status != 200:
                    return None
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    return None
                if not isinstance(data, dict):
                    return None
                rd = data.get("responseData") or {}
                translated = rd.get("translatedText")
                # MyMemory renvoie parfois un message d'erreur dans translatedText
                # avec un responseStatus != 200 → on s'aligne sur le status logique.
                status = data.get("responseStatus")
                try:
                    status = int(status)
                except Exception:
                    status = 200
                if status != 200:
                    return None
                if not isinstance(translated, str) or not translated.strip():
                    return None
                return translated.strip()

        try:
            if _session_factory is not None:
                session = _session_factory()
                # La fabrique peut renvoyer une session partagée (à NE PAS fermer)
                # ou un context manager. On gère les deux prudemment.
                if hasattr(session, "__aenter__"):
                    async with session as s:
                        result = await _do(s)
                else:
                    result = await _do(session)
            else:
                async with aiohttp.ClientSession() as s:
                    result = await _do(s)
        except (asyncio.TimeoutError, aiohttp.ClientError):
            return None
        except Exception:
            return None

        # Mémorise même l'échec ("") pour ne pas marteler l'API sur un texte KO.
        _cache_put(key, result or "")
        return result or None

    except Exception:
        return None


__all__ = [
    "translate",
    "set_enabled",
    "is_enabled",
    "setup",
    "stats",
    "MAX_CHARS",
    "DAILY_CAP",
]
