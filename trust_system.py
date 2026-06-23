"""trust_system.py — Confiance progressive des nouveaux + politique liens/invitations
(owner 2026-06-21).

Décision owner : PAS de sas de vérification (accès direct au serveur), MAIS :
- les **invitations** Discord sont interdites pour tous (sauf immunisés/staff) ;
- les **liens** sont interdits pour tous, SAUF les liens d'**image/GIF** (tenor, giphy,
  cdn Discord, .gif/.png/.jpg…) — ceux-là restent autorisés ;
- les **images / GIFs / fichiers** sont bloqués pour un **nouveau** membre tant qu'il n'est
  pas « de confiance » ; une fois la confiance acquise, il poste images & GIFs librement.

« De confiance » = présent depuis `age_hours` (défaut 24 h) OU actif (présent depuis
`fast_hours` ET ≥ `fast_msgs` messages). L'appelant (bot.py) exempte owner/staff/immunisés
AVANT d'appeler ce module. 100% FAIL-OPEN (dans le doute → on n'empêche rien).

Pur, sans dépendance à bot.py (pas d'import circulaire). Le compteur de messages est en
mémoire (accélérateur ; s'il se vide au reboot, la confiance par ANCIENNETÉ prend le relais).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# (guild_id, user_id) -> nb de messages (accélérateur de confiance, borné).
_msg_counts: dict = {}

_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
_INVITE_RE = re.compile(r'(?:discord\.gg/|discord(?:app)?\.com/invite/|discord\.gg\s*/)\s*[\w-]+', re.IGNORECASE)
# Hôtes d'images/GIF autorisés (le GIF Tenor/Giphy reste permis).
_MEDIA_HOST_RE = re.compile(
    r'(?:tenor\.com|giphy\.com|gfycat\.com|gifyourgame\.|cdn\.discordapp\.com|'
    r'media\.discordapp\.net|images-ext-\d+\.discordapp\.net|imgur\.com|i\.redd\.it)',
    re.IGNORECASE)
_MEDIA_EXT_RE = re.compile(r'\.(?:gif|gifv|png|jpe?g|webp|bmp|apng)(?:[?#]\S*)?', re.IGNORECASE)


def bump(gid, uid) -> int:
    """Incrémente le compteur de messages du membre (borné). Renvoie le nouveau total."""
    try:
        k = (int(gid), int(uid))
        _msg_counts[k] = _msg_counts.get(k, 0) + 1
        if len(_msg_counts) > 50000:                 # borne mémoire (éviction grossière)
            for kk in list(_msg_counts.keys())[:10000]:
                _msg_counts.pop(kk, None)
        return _msg_counts[k]
    except Exception:
        return 0


def msg_count(gid, uid) -> int:
    try:
        return _msg_counts.get((int(gid), int(uid)), 0)
    except Exception:
        return 0


def is_trusted(member, *, age_hours: int = 24, fast_hours: int = 2, fast_msgs: int = 12) -> bool:
    """Le membre peut-il poster images/GIFs ? (owner/staff/immunisés déjà exemptés par
    l'appelant). FAIL-OPEN : ancienneté illisible → True (on ne bloque pas)."""
    try:
        joined = getattr(member, 'joined_at', None)
        if joined is None:
            return True
        age = (datetime.now(timezone.utc) - joined).total_seconds()
        if age >= age_hours * 3600:
            return True
        if age >= fast_hours * 3600 and msg_count(member.guild.id, member.id) >= fast_msgs:
            return True
        return False
    except Exception:
        return True


def has_invite(text: str) -> bool:
    try:
        return bool(_INVITE_RE.search(text or ''))
    except Exception:
        return False


def has_non_media_link(text: str) -> bool:
    """True s'il y a un lien qui N'est PAS une image/GIF (les invitations sont gérées à
    part). Un lien Tenor/Giphy/cdn ou se terminant par .gif/.png… est AUTORISÉ."""
    try:
        for u in _URL_RE.findall(text or ''):
            ul = u.lower()
            if _INVITE_RE.search(ul):
                continue                              # invitation → traitée séparément
            if _MEDIA_HOST_RE.search(ul) or _MEDIA_EXT_RE.search(ul):
                continue                              # lien image/GIF → autorisé
            return True
    except Exception:
        return False
    return False


def has_media(msg, text: str) -> bool:
    """True si le message porte une image/GIF/fichier (pièce jointe OU lien média OU embed
    média). Sert à bloquer ces contenus pour un membre PAS encore de confiance."""
    try:
        if getattr(msg, 'attachments', None):
            return True
        for u in _URL_RE.findall(text or ''):
            ul = u.lower()
            if _MEDIA_HOST_RE.search(ul) or _MEDIA_EXT_RE.search(ul):
                return True
        for e in (getattr(msg, 'embeds', None) or []):
            if getattr(e, 'type', '') in ('image', 'gifv', 'video'):
                return True
    except Exception:
        return False
    return False
