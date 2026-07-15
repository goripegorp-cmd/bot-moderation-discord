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
# (guild_id, user_id) -> epoch jusqu'auquel la confiance est GELÉE (le membre a fait une
# bêtise → il doit re-mériter l'accès). owner 2026-06-21 : « s'ils font pas de bêtises ».
_frozen: dict = {}


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def freeze(gid, uid, hours: float = 24.0):
    """Gèle la confiance d'un membre pour `hours` (appelé quand il est sanctionné) → il
    repasse en accès limité (texte seulement) et doit re-mériter. Borné, FAIL-SAFE."""
    try:
        _frozen[(int(gid), int(uid))] = _now() + max(0.0, float(hours)) * 3600.0
        if len(_frozen) > 20000:
            n = _now()
            for k in [k for k, t in list(_frozen.items()) if t < n]:
                _frozen.pop(k, None)
    except Exception:
        pass


def is_frozen(gid, uid) -> bool:
    try:
        return _frozen.get((int(gid), int(uid)), 0) > _now()
    except Exception:
        return False

_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
_INVITE_RE = re.compile(r'(?:discord\.gg/|discord(?:app)?\.com/invite/|discord\.gg\s*/)\s*[\w-]+', re.IGNORECASE)
# Hôtes d'images/GIF autorisés (le GIF « pour rigoler » reste permis). Liste ÉLARGIE
# (owner 2026-07-11 : des GIFs légitimes étaient censurés car leur hôte manquait ici).
# NB : match par SOUS-CHAÎNE → « tenor.com » couvre aussi media.tenor.com, c.tenor.com, etc.
_MEDIA_HOST_RE = re.compile(
    r'(?:tenor\.com|tenor\.co|giphy\.com|gph\.is|gfycat\.com|redgifs\.com|gifyourgame\.|'
    r'imgflip\.com|imgur\.com|i\.redd\.it|v\.redd\.it|preview\.redd\.it|gyazo\.com|'
    r'prnt\.sc|ibb\.co|postimg\.(?:cc|org)|pbs\.twimg\.com|media\.tumblr\.com|'
    r'cdn\.discordapp\.com|media\.discordapp\.net|images-ext-\d+\.discordapp\.net)',
    re.IGNORECASE)
_MEDIA_EXT_RE = re.compile(r'\.(?:gif|gifv|png|jpe?g|webp|bmp|apng)(?:[?#]\S*)?', re.IGNORECASE)
# Indice « c'est un GIF » DANS l'URL (au-delà de l'hôte/extension) : tenor /view/…-gif-123,
# giphy /gifs/… , …/name.gif … Le « gif » doit être BORNÉ par des séparateurs d'URL → évite
# le faux positif « gift-card » (owner 2026-07-12 : autoriser TOUT type de GIF, quel que soit le site).
_GIF_HINT_RE = re.compile(r'[/\-_.=]gifs?(?:[/\-_.=?&]|$)', re.IGNORECASE)


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


def is_trusted(member, *, age_hours: int = 24, fast_hours: int = 2, fast_msgs: int = 12,
               min_account_days: int = 7) -> bool:
    """Le membre peut-il poster images/GIFs ? (owner/staff/immunisés déjà exemptés par
    l'appelant). RELIABILITÉ = (pas de bêtise récente) ET (compte Discord pas trop jeune) ET
    (assez de temps/activité sur le serveur). FAIL-OPEN : données illisibles → True."""
    try:
        # 1) Bêtise récente → confiance GELÉE : il doit re-mériter l'accès (texte seulement).
        if is_frozen(getattr(member.guild, 'id', 0), getattr(member, 'id', 0)):
            return False
        now = datetime.now(timezone.utc)
        # 2) FIABILITÉ DU COMPTE : un compte Discord TRÈS JEUNE reste limité tant que le COMPTE
        #    lui-même n'a pas atteint min_account_days (owner 2026-06-21 : « est-ce que le
        #    compte est super jeune »). Les comptes anciens passent direct à l'étape 3.
        created = getattr(member, 'created_at', None)
        if created is not None and int(min_account_days) > 0:
            if (now - created).days < int(min_account_days):
                return False
        # 3) TEMPS sur le serveur / ACTIVITÉ.
        joined = getattr(member, 'joined_at', None)
        if joined is None:
            return True
        age = (now - joined).total_seconds()
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


def has_non_media_link(text: str, whitelist=None) -> bool:
    """True s'il y a un lien qui N'est PAS une image/GIF (les invitations sont gérées à part).
    AUTORISÉ : hôte média (tenor/giphy/cdn…), extension média (.gif/.png…), « gif » dans l'URL
    (tout site), OU un domaine présent dans la whitelist owner (`link_whitelist`)."""
    try:
        _wl = [str(w).lower() for w in (whitelist or []) if w]
        for u in _URL_RE.findall(text or ''):
            ul = u.lower()
            if _INVITE_RE.search(ul):
                continue                              # invitation → traitée séparément
            if _MEDIA_HOST_RE.search(ul) or _MEDIA_EXT_RE.search(ul) or _GIF_HINT_RE.search(ul):
                continue                              # image/GIF (hôte, extension, ou 'gif' dans l'URL) → OK
            if _wl and any(w in ul for w in _wl):
                continue                              # domaine autorisé par l'owner → permis
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
