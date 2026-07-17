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

# ═══════════════════════════════════════════════════════════════════════════════
#  🔗 ANALYSE D'URL — on raisonne sur l'HÔTE et le CHEMIN, jamais sur la chaîne brute
# ═══════════════════════════════════════════════════════════════════════════════
# FAILLE CORRIGÉE (revue 2026-07-17, feu vert owner) : ces tests étaient des `search` sur
# l'URL COMPLÈTE (hôte + chemin + query). Deux contournements triviaux en découlaient :
#   • `https://evil.tld/steam-login?redirect=logo.png` → le « .png » de la QUERY exemptait tout ;
#   • `https://tenor.com.evil.tld/vol-de-token`        → « tenor.com » matchait en SOUS-CHAÎNE.
# Coût pour l'attaquant : ajouter `?x=.png` à son lien. On parse donc l'URL et on teste
# l'extension sur le CHEMIN SEUL et les hôtes en SUFFIXE EXACT.
# ⚠️ La LARGEUR reste voulue (décision owner 2026-07-12 « autoriser TOUS les GIFs, on modère à
# la main ») : un chemin contenant « gif » sur N'IMPORTE quel site passe toujours — c'est la
# décision, pas la faille. Le filtre anti-phishing/anti-scam, lui, n'a jamais été concerné.
from urllib.parse import urlsplit

# Hôtes d'images/GIF autorisés — testés en SUFFIXE EXACT sur l'hôte (« tenor.com » couvre
# media.tenor.com / c.tenor.com, mais PAS tenor.com.evil.tld).
_MEDIA_HOSTS = (
    'tenor.com', 'tenor.co', 'giphy.com', 'gph.is', 'gfycat.com', 'redgifs.com',
    'gifyourgame.com', 'gifyourgame.gg', 'klipy.com', 'imgflip.com', 'imgur.com', 'redd.it',
    'gyazo.com', 'prnt.sc', 'ibb.co', 'postimg.cc', 'postimg.org', 'twimg.com',
    'tumblr.com', 'discordapp.com', 'discordapp.net',
)
_MEDIA_EXTS = ('.gif', '.gifv', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.apng')
# Indice « c'est un GIF » dans le CHEMIN (jamais la query) : tenor /view/…-gif-123, giphy
# /gifs/… Le « gif » est BORNÉ par des séparateurs → pas de faux positif sur « gift-card ».
_GIF_PATH_RE = re.compile(r'(?:^|[/\-_.])gifs?(?:[/\-_.]|$)', re.IGNORECASE)


def _split_url(u) -> tuple:
    """(hôte, chemin) en minuscules — ('','') si illisible.

    ⚠️ Tolère une URL SANS schéma : `check_link` (bot.py) passe le GROUPE CAPTURÉ
    (« domaine/chemin?query »), alors que `has_non_media_link` passe l'URL complète.
    Les deux formats DOIVENT marcher.
    """
    try:
        s = str(u or '').strip().lower()
        if not s:
            return '', ''
        if not s.startswith(('http://', 'https://')):
            s = 'http://' + s
        sp = urlsplit(s)
        return (sp.hostname or ''), (sp.path or '')
    except Exception:
        return '', ''


def _host_in(host: str, domains) -> bool:
    """Suffixe EXACT. « tenor.com » couvre media.tenor.com — jamais tenor.com.evil.tld."""
    return bool(host) and any(host == d or host.endswith('.' + d) for d in domains)


def _host_allowed(host: str, entries) -> bool:
    """Whitelist OWNER (`link_whitelist`) : le domaine et ses sous-domaines, RIEN d'autre.

    Corrige le même piège côté config : c'était `any(w in url)`, donc whitelister « youtube.com »
    autorisait aussi `https://evil.tld/?ref=youtube.com`. L'owner croit autoriser un domaine —
    il autorisait une sous-chaîne. Tolère une entrée sans TLD (« youtube ») en la comparant au
    domaine de 2e niveau, pour ne pas casser les configs existantes.
    """
    if not host:
        return False
    labels = host.split('.')
    for d in entries:
        d = re.sub(r'^https?://', '', str(d or '').strip().lower()).split('/')[0].strip('/. ')
        if not d:
            continue
        if host == d or host.endswith('.' + d):
            return True
        if '.' not in d and len(labels) >= 2 and labels[-2] == d:
            return True
    return False


def _media_host_or_ext(u) -> bool:
    """Hôte média OU extension média sur le CHEMIN (sans l'indice « gif » du chemin)."""
    host, path = _split_url(u)
    return _host_in(host, _MEDIA_HOSTS) or path.endswith(_MEDIA_EXTS)


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
        _wl = [w for w in (whitelist or []) if w]
        for u in _URL_RE.findall(text or ''):
            ul = u.lower()
            if _INVITE_RE.search(ul):
                continue                              # invitation → traitée séparément
            if is_media_url(ul):
                continue                              # image/GIF → OK (décision owner)
            if _wl and _host_allowed(_split_url(ul)[0], _wl):
                continue                              # domaine autorisé par l'owner → permis
            return True
    except Exception:
        return False
    return False


def is_media_url(u) -> bool:
    """True si l'URL est une image/GIF : hôte média (tenor/giphy/klipy/…), extension média
    (.gif/.png/…) sur le CHEMIN, OU « gif » dans le CHEMIN. Point d'entrée UNIQUE pour EXEMPTER
    les GIFs de TOUS les filtres de liens (trust + anti_link classique). owner 2026-07-12 :
    « autoriser TOUS les GIFs » — Discord source les GIFs depuis plein de fournisseurs
    (klipy, tenor, giphy…).

    ⚠️ Ce qui est testé sur le CHEMIN ne l'est JAMAIS sur la query : sinon `?x=.png` suffirait à
    exempter n'importe quel lien de phishing (faille corrigée le 2026-07-17). Les hôtes sont
    testés en suffixe exact → `tenor.com.evil.tld` ne passe pas.
    """
    try:
        host, path = _split_url(u)
        if not host:
            return False
        if _host_in(host, _MEDIA_HOSTS) or path.endswith(_MEDIA_EXTS):
            return True
        return bool(_GIF_PATH_RE.search(path))
    except Exception:
        return False


def has_media(msg, text: str) -> bool:
    """True si le message porte une image/GIF/fichier (pièce jointe OU lien média OU embed
    média). Sert à bloquer ces contenus pour un membre PAS encore de confiance."""
    try:
        if getattr(msg, 'attachments', None):
            return True
        for u in _URL_RE.findall(text or ''):
            if _media_host_or_ext(u.lower()):
                return True
        for e in (getattr(msg, 'embeds', None) or []):
            if getattr(e, 'type', '') in ('image', 'gifv', 'video'):
                return True
    except Exception:
        return False
    return False
