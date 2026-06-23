"""insult_filter.py — filtre d'insultes / haine GRADUÉ et multilingue (owner 2026-06-21).

But : PROTÉGER sans RESTREINDRE. On gradue par NIVEAU (le ciblage est décidé par l'appelant
dans bot.py, qui a accès au message — mentions, réponse, tournure 2e personne) :

  niveau 3 = haine / slurs GRAVES (racisme, homophobie, antisémitisme, validisme…),
             quasi AUCUN usage innocent → l'appelant applique une action forte.
  niveau 2 = insulte (rabaisse) → action surtout si ça CIBLE quelqu'un.
  niveau 1 = juron léger (expression) → réponse minimale.

Le lexique vit dans `insult_lexicon.json` (généré + DOUBLE revue adverse anti-faux-positifs :
revue par-groupe puis passe globale inter-langues qui a retiré les collisions du type
« tard » FR, « eta », « negro » ES/PT…). On le charge au démarrage et on le compile en regex :
- termes latins/cyrilliques/arabes → FRONTIÈRE DE MOT (anti-Scunthorpe : « merde » ne matche
  pas « merder », mais matche « c'est merde »),
- termes CJK (sans espaces) → sous-chaîne (la frontière de mot n'a pas de sens en CJK).

Scan sur le texte BRUT + une variante « pliée » (leet : c0nnard→connard, b!te→bite). 100%
FAIL-SAFE : toute erreur → (0, None), ne lève jamais, ne casse jamais on_message.
"""
from __future__ import annotations

import json
import os
import re

_TIER3: frozenset = frozenset()
_TIER2: frozenset = frozenset()
_TIER1: frozenset = frozenset()

# (regex_frontière, regex_sous-chaîne_CJK) par niveau.
_RE3 = (None, None)
_RE2 = (None, None)
_RE1 = (None, None)

# leet → lettre (attrape c0nnard, conn4rd, b!te, $alope…). On NE supprime PAS les séparateurs
# (ça casserait les frontières de mot) : l'évasion par espacement reste partiellement couverte
# par la normalisation amont (NFKC) côté appelant.
_LEET = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '8': 'b',
    '@': 'a', '$': 's', '€': 'e', '£': 'l', '!': 'i', '|': 'i',
})

# Plages CJK (kana, CJK unifié, hangul) : pas d'espaces → match en sous-chaîne, pas en frontière.
_CJK_RE = re.compile(r'[぀-ヿ㐀-鿿가-힯]')


def _fold(s: str) -> str:
    try:
        return s.translate(_LEET)
    except Exception:
        return s


def _is_cjk(t: str) -> bool:
    try:
        return bool(_CJK_RE.search(t))
    except Exception:
        return False


def _compile_pair(terms):
    """Renvoie (regex_frontière_latin, regex_sous-chaîne_CJK) pour un niveau."""
    bnd, cjk = [], []
    for x in terms:
        t = (x or "").lower().strip()
        if not t:
            continue
        if _is_cjk(t):
            if len(t) >= 2:
                cjk.append(t)
        elif len(t) >= 3:                 # latin/cyrillique/arabe : min 3 (anti-bruit)
            bnd.append(t)
    re_bnd = None
    if bnd:
        bnd.sort(key=len, reverse=True)
        try:
            re_bnd = re.compile(
                r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in bnd) + r')(?!\w)',
                re.IGNORECASE | re.UNICODE)
        except Exception:
            re_bnd = None
    re_cjk = None
    if cjk:
        cjk.sort(key=len, reverse=True)
        try:
            re_cjk = re.compile('|'.join(re.escape(t) for t in cjk))
        except Exception:
            re_cjk = None
    return (re_bnd, re_cjk)


def _load():
    global _TIER3, _TIER2, _TIER1, _RE3, _RE2, _RE1
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "insult_lexicon.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _TIER3 = frozenset(data.get("tier3", []) or [])
        _TIER2 = frozenset(data.get("tier2", []) or [])
        _TIER1 = frozenset(data.get("tier1", []) or [])
    except Exception as ex:
        print(f"[insult_filter] lexique non chargé : {ex}")
        _TIER3 = _TIER2 = _TIER1 = frozenset()
    _RE3 = _compile_pair(_TIER3)
    _RE2 = _compile_pair(_TIER2)
    _RE1 = _compile_pair(_TIER1)
    n = {"tier3": len(_TIER3), "tier2": len(_TIER2), "tier1": len(_TIER1)}
    print(f"[insult_filter] lexique chargé : {n}")
    return n


def _hit(pair, text):
    """pair = (regex_frontière, regex_cjk). Renvoie le terme trouvé ou None."""
    rb, rc = pair
    try:
        if rb is not None:
            m = rb.search(text)
            if m:
                return m.group(0)
        if rc is not None:
            m = rc.search(text)
            if m:
                return m.group(0)
    except Exception:
        return None
    return None


def scan(raw: str, normalized: str | None = None):
    """Renvoie (niveau, terme) le PLUS GRAVE trouvé (3 > 2 > 1) sur le texte, ou (0, None).

    `normalized` : version dé-obfusquée (anti-homoglyphes/zero-width) fournie par l'appelant
    (bot._normalize_for_scan) — scannée EN PLUS du brut (defense in depth). FAIL-SAFE."""
    if not raw:
        return 0, None
    variants = [raw]
    fr = _fold(raw)
    if fr != raw:
        variants.append(fr)
    if normalized and normalized != raw:
        variants.append(normalized)
        fn = _fold(normalized)
        if fn != normalized:
            variants.append(fn)

    best, term = 0, None
    for v in variants:
        if not v:
            continue
        h = _hit(_RE3, v)
        if h:
            return 3, h                    # haine = max → court-circuit immédiat
        if best < 2:
            h = _hit(_RE2, v)
            if h:
                best, term = 2, h
        if best < 1:
            h = _hit(_RE1, v)
            if h:
                best, term = 1, h
    return best, term


# Chargé à l'import (le module est importé une fois au boot).
_STATS = _load()
