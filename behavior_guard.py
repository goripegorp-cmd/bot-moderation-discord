"""behavior_guard.py — abus techniques (owner 2026-06-21) :
  #8 anti-crash : texte « zalgo » (diacritiques empilés) / caractères invisibles en masse
                  qui font ramer/planter les clients ;
  #9 anti-spam inter-salons : le MÊME message copié dans plusieurs salons en quelques s ;
  #10 anti-automation : rafale de messages à vitesse INHUMAINE (selfbot/script).

Pur (sans dépendance à bot.py). Détections conçues ANTI-FAUX-POSITIFS (seuils élevés ; le
zalgo se distingue d'un script légitime arabe/indien par un RATIO de combinants élevé).
100% FAIL-SAFE : toute erreur → résultat « rien », ne lève jamais.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timezone

# #8
_ZALGO_MAX = 45        # nb absolu de diacritiques combinants
_ZALGO_RATIO = 0.40    # ET proportion de combinants > 40% (un texte arabe/hindi légitime
                       # reste bien en dessous → pas de faux positif sur ces langues)
_INVIS_MAX = 15        # nb de caractères invisibles / zero-width

# #9
XCHAN_CHANNELS = 3     # même message dans ≥ 3 salons distincts…
XCHAN_WINDOW = 20.0    # …en 20 s
# #10
AUTO_BURST = 10        # ≥ 10 messages…
AUTO_WINDOW = 3.0      # …en 3 s = inhumain

_xchan: dict = {}      # (gid,uid) -> [(chan_id, hash, ts)]
_auto: dict = {}       # (gid,uid) -> [ts]

_INVIS = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x180E, 0x2061, 0x2062, 0x2063}


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def is_crash_text(content: str):
    """Renvoie 'zalgo' / 'invisible' si le message est un texte conçu pour faire ramer, sinon
    None. Seuils élevés + ratio → pas de faux positif sur les langues à diacritiques."""
    try:
        if not content:
            return None
        combining = invisible = 0
        for ch in content:
            cat = unicodedata.category(ch)
            if cat in ('Mn', 'Mc', 'Me'):
                combining += 1
            elif cat == 'Cf' or ord(ch) in _INVIS:
                invisible += 1
        total = len(content)
        if combining >= _ZALGO_MAX and total and (combining / total) > _ZALGO_RATIO:
            return 'zalgo'
        if invisible >= _INVIS_MAX:
            return 'invisible'
    except Exception:
        return None
    return None


def track_xchannel(gid, uid, chan_id, content) -> bool:
    """True si le MÊME contenu apparaît dans ≥ XCHAN_CHANNELS salons distincts en XCHAN_WINDOW."""
    try:
        body = (content or '').strip().lower()
        if len(body) < 3:
            return False
        h = hash(body[:200])
        n = _now()
        k = (int(gid), int(uid))
        lst = [(c, hh, t) for (c, hh, t) in _xchan.get(k, []) if n - t < XCHAN_WINDOW]
        lst.append((int(chan_id), h, n))
        _xchan[k] = lst[-40:]
        if len(_xchan) > 20000:
            for kk in list(_xchan.keys())[:5000]:
                _xchan.pop(kk, None)
        chans = {c for (c, hh, t) in lst if hh == h}
        return len(chans) >= XCHAN_CHANNELS
    except Exception:
        return False


def track_automation(gid, uid) -> bool:
    """True si ≥ AUTO_BURST messages en AUTO_WINDOW (vitesse inhumaine = bot/selfbot)."""
    try:
        n = _now()
        k = (int(gid), int(uid))
        lst = [t for t in _auto.get(k, []) if n - t < AUTO_WINDOW]
        lst.append(n)
        _auto[k] = lst[-40:]
        if len(_auto) > 20000:
            for kk in list(_auto.keys())[:5000]:
                _auto.pop(kk, None)
        return len(lst) >= AUTO_BURST
    except Exception:
        return False
