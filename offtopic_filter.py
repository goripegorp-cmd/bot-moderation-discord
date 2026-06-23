"""offtopic_filter.py — filtre « serveur gaming / chill SANS politique, religion, militantisme »
(owner 2026-06-21).

Le serveur est multi-gaming et chill. L'owner veut retirer les SLOGANS politiques/religieux/
militants (free palestine, from the river to the sea, black lives matter, antifa, qanon,
prosélytisme…), Y COMPRIS dans les GIFs : un GIF Tenor/Giphy a un *slug* dans son URL
(ex. `tenor.com/view/free-palestine-gif-25839`) → on lit ce slug et on bloque le GIF SANS
même voir l'image.

PRÉCISION ABSOLUE : on ne touche PAS au vocabulaire gaming/casual. Le lexique
(offtopic_lexicon.json) ne contient QUE des SLOGANS (2+ mots) et des noms de mouvements/
orgs/hashtags SANS AMBIGUÏTÉ, après DOUBLE revue adverse anti-faux-positifs orientée chat
gaming (on a écarté tout ce qui contient free / god / war / raid / vote / cross… isolés).

Matching à la FRONTIÈRE DE MOT (« free palestine » matche, « free » seul JAMAIS). Scan du
texte brut + normalisé + des SLUGS d'URL (GIF & liens descriptifs). 100% FAIL-SAFE.
"""
from __future__ import annotations

import json
import os
import re

_TERMS: frozenset = frozenset()
_RE = None

_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)


def _compile(terms):
    terms = sorted({(t or "").lower().strip() for t in terms if t and len((t or "").strip()) >= 4},
                   key=len, reverse=True)
    if not terms:
        return None
    try:
        return re.compile(
            r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in terms) + r')(?!\w)',
            re.IGNORECASE | re.UNICODE)
    except Exception:
        return None


def _url_slugs(text: str):
    """Extrait les « slugs » des URLs (segments à tirets) → mots de recherche d'un GIF Tenor/
    Giphy ou d'un lien descriptif. `tenor.com/view/free-palestine-gif-25839` → 'free palestine
    gif 25839'. Permet de bloquer un GIF militant sans analyser l'image."""
    slugs = []
    try:
        for um in _URL_RE.finditer(text or ""):
            url = um.group(0).lower()
            for seg in re.split(r'[/?#&=]', url):
                if len(seg) >= 6 and ('-' in seg or '_' in seg):
                    slugs.append(seg.replace('-', ' ').replace('_', ' '))
    except Exception:
        pass
    return slugs


def _load():
    global _TERMS, _RE
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offtopic_lexicon.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # accepte {"slogans":[...]} OU une liste brute
        terms = data.get("slogans", data) if isinstance(data, dict) else data
        _TERMS = frozenset(terms or [])
    except Exception as ex:
        print(f"[offtopic_filter] lexique non chargé : {ex}")
        _TERMS = frozenset()
    _RE = _compile(_TERMS)
    print(f"[offtopic_filter] lexique chargé : {len(_TERMS)} slogans")
    return len(_TERMS)


def scan(raw: str, normalized: str | None = None):
    """Renvoie le SLOGAN trouvé (politique/religieux/militant) ou None. Scanne le texte brut,
    sa version normalisée (anti-homoglyphes), ET les slugs d'URL (GIF Tenor/Giphy inclus).
    FAIL-SAFE : toute erreur → None, ne lève jamais."""
    if _RE is None or not raw:
        return None
    variants = [raw]
    if normalized and normalized != raw:
        variants.append(normalized)
    variants.extend(_url_slugs(raw))
    if normalized and normalized != raw:
        variants.extend(_url_slugs(normalized))
    for v in variants:
        if not v:
            continue
        try:
            m = _RE.search(v)
            if m:
                return m.group(0)
        except Exception:
            continue
    return None


_COUNT = _load()
