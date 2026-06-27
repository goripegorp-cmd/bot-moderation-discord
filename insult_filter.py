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

# ── Niveau 4 : INCITATION AU SUICIDE / À LA MORT dirigée vers AUTRUI (owner 2026-06-21) ──
# UNIQUEMENT les formes DIRIGÉES (kill yourSELF, va te pendre…) = une ATTAQUE. On n'inclut
# JAMAIS les formes à la 1re personne (« kms », « je veux mourir », « i wanna die ») :
# exprimer SA PROPRE détresse n'est pas une attaque et ne doit pas être sanctionné (au
# contraire). L'appelant applique l'action la plus forte (suppression + exclusion + alerte).
_SELFHARM_TERMS = frozenset({
    "kys", "kys urself", "kys yourself", "kill yourself", "kill urself", "kill ur self",
    "kill your self", "go kill yourself", "you should kill yourself", "you should kys",
    "you need to kill yourself", "neck yourself", "neck urself", "rope yourself",
    "hang yourself", "off yourself", "end yourself", "unalive yourself",
    "you should die", "you deserve to die", "an hero", "kys now",
    "va te pendre", "pends toi", "pends-toi", "suicide toi", "suicide-toi", "tue toi",
    "tue-toi", "va te tuer", "va te suicider", "va te foutre en l'air", "va te flinguer",
    "tu devrais mourir", "tu devrais te tuer", "tu devrais te suicider",
    "matate", "mátate", "suicidate", "suicídate", "bring dich um", "ammazzati",
})
_RE_SH = (None, None)

# ── Harcèlement / manque de respect CIBLÉ moderne (phrases dirigées, owner 2026-06-21) ──
# Traitées au NIVEAU 2 → supprimées seulement quand ça VISE quelqu'un (elles contiennent
# de toute façon une 2e personne). Le banter (ratio, L, skill issue, ez…) reste LIBRE.
_HARASS_TERMS = frozenset({
    "personne t'aime", "personne ne t'aime", "t'as pas d'amis", "tu as pas d'amis",
    "tu sers a rien", "tu sers à rien", "tu vaux rien", "tu fais pitié", "tu es pathétique",
    "tu es un raté", "t'es un raté", "personne va te regretter", "personne te calcule",
    "le monde se porterait mieux sans toi", "nobody likes you", "no one likes you",
    "you have no friends", "u have no friends", "you have no life", "you're worthless",
    "youre worthless", "you are worthless", "you're a waste", "you are nothing",
    "you're nothing", "everyone hates you", "nobody wants you here",
})

# ── RABAISSEMENT / dévalorisation CIBLÉE (owner 2026-06-27 : « t nul » = juger qqn de nul,
# c'est rabaisser/discriminer). NIVEAU 2 — phrases INTRINSÈQUEMENT dirigées (2e personne) →
# l'appelant les traite comme ciblées (les formes SMS « t nul » sont ajoutées à _INSULT_TARGET_RE
# côté bot.py). On NE met PAS « nul » nu (« c'est nul » = expression, jamais une insulte à qqn).
_BELITTLE_TERMS = frozenset({
    "t'es nul", "tes nul", "t es nul", "tu es nul", "t nul", "t'es nuls", "vous etes nuls",
    "vous êtes nuls", "t'es trop nul", "t'es qu'un nul", "tu n'es qu'un nul", "t'es naze",
    "t'es nase", "t'es un naze", "t'es un boulet", "t'es un loser", "t'es minable", "tu es minable",
    "t'es un minable", "t'es bon à rien", "t'es bon a rien", "tu es bon à rien", "t'es un moins que rien",
    "t'es un déchet", "t'es un dechet", "tu es un déchet", "t'es insignifiant", "t'es une sous merde",
    "t'es un sous homme", "t'es un raté", "t'es une raté", "t'es vraiment nul", "t'es trop mauvais",
    "you're a loser", "you are a loser", "ur a loser", "you're trash", "you are trash", "ur trash",
    "you're garbage", "you suck", "you're a failure", "you're a nobody", "you're pathetic",
    "you're so bad", "you are useless", "ur useless",
})

# ── Insultes/aggressions CIBLÉES FR courantes (owner 2026-06-21 : « TG / ta gueule = une
# vraie insulte qui mérite un warn »). NIVEAU 2 — ces tournures sont INTRINSÈQUEMENT dirigées
# (on les DIT à quelqu'un) → l'appelant les traite comme ciblées (« tg »/« ta gueule » sont
# aussi dans _INSULT_TARGET_RE) → suppression + warn → mute en cas de récidive.
_TIER2_EXTRA = frozenset({
    "ta gueule", "tagueule", "ta geule", "ta gueule sale", "ferme ta gueule",
    "ferme ta grande gueule", "ferme ta bouche", "ferme-la", "ferme la", "ferme sa gueule",
    "vos gueules", "fermez vos gueules", "ferme ta gueule toi", "nique ta race",
    "ta gueule connard", "grosse merde toi",
})
# Abréviations de 2 lettres SANS ambiguïté (échappent au plancher de 3 lettres). « tg » =
# « ta gueule » dans le chat FR. Matching FRONTIÈRE DE MOT strict → ne touche jamais un mot.
_TIER2_ABBR = frozenset({"tg"})
_RE2_ABBR = None

# ── VALIDISME / condition utilisée comme insulte (owner 2026-06-27) ──────────────────────
# « autiste », « mongol », « trisomique »… utilisés pour rabaisser/juger. BLOQUÉ MÊME en
# AUTO-RÉFÉRENCE (« je suis autiste ») : owner « ça porte à confusion aujourd'hui, bloque-le
# quand même ». Action GRADUÉE côté bot (suppression + escalade cumulative, pas un mute brutal
# au 1er écart). Frontière de mot stricte → « Mongolie », « autisme » (le nom clinique),
# « download », « en retard » NE matchent PAS. Slurs à ~zéro usage innocent sur un serveur
# gaming/chill. FR + EN + ES. Owner peut élargir/retirer via badwords_whitelist (court-circuit).
_ABLEIST_TERMS = frozenset({
    # FR
    "autiste", "autistes", "autisto", "trisomique", "trisomiques", "triso", "trisos",
    "mongolien", "mongoliens", "mongolienne", "mongoliennes", "mongol", "mongols", "mongolo",
    "mongole", "mongoloïde", "mongoloide", "handicapé mental", "handicapée mentale",
    "handicapé du cerveau", "déficient mental", "débile mental", "attardé mental",
    # EN
    "autistic", "retarded", "mongoloid", "downie", "window licker", "sped kid",
    # ES
    "subnormal", "mongólico", "mongolico", "retrasado", "retrasada",
})
_RE_ABLEIST = (None, None)


def _compile_abbr(terms):
    """Compile des termes COURTS (≥2) en frontière de mot stricte (pour « tg » & co.)."""
    terms = sorted({(t or "").lower().strip() for t in terms if t and len((t or "").strip()) >= 2},
                   key=len, reverse=True)
    if not terms:
        return None
    try:
        return re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in terms) + r')(?!\w)',
                          re.IGNORECASE | re.UNICODE)
    except Exception:
        return None


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
    global _TIER3, _TIER2, _TIER1, _RE3, _RE2, _RE1, _RE_SH, _RE2_ABBR, _RE_ABLEIST
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
    # Le harcèlement ciblé moderne + les aggressions FR (ta gueule…) + le rabaissement ciblé
    # (« t'es nul »…) rejoignent le niveau 2 (gated par le ciblage côté appelant).
    _TIER2 = frozenset(_TIER2 | _HARASS_TERMS | _TIER2_EXTRA | _BELITTLE_TERMS)
    _RE_SH = _compile_pair(_SELFHARM_TERMS)
    _RE2_ABBR = _compile_abbr(_TIER2_ABBR)
    _RE3 = _compile_pair(_TIER3)
    _RE2 = _compile_pair(_TIER2)
    _RE1 = _compile_pair(_TIER1)
    _RE_ABLEIST = _compile_pair(_ABLEIST_TERMS)   # validisme : toujours bloqué (même auto-réf.)
    n = {"selfharm": len(_SELFHARM_TERMS), "tier3": len(_TIER3),
         "tier2": len(_TIER2), "tier1": len(_TIER1), "ableist": len(_ABLEIST_TERMS)}
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
        h = _hit(_RE_SH, v)
        if h:
            return 4, h                    # incitation au suicide/mort = priorité absolue
        h = _hit(_RE3, v)
        if h:
            return 3, h                    # haine = max → court-circuit immédiat
        if best < 2:
            h = _hit(_RE2, v)
            if h:
                best, term = 2, h
            elif _RE2_ABBR is not None:                # abréviations courtes (« tg »…)
                try:
                    m = _RE2_ABBR.search(v)
                    if m:
                        best, term = 2, m.group(0)
                except Exception:
                    pass
        if best < 1:
            h = _hit(_RE1, v)
            if h:
                best, term = 1, h
    return best, term


def ableist_hit(raw: str, normalized: str | None = None):
    """Renvoie le terme de VALIDISME trouvé (« autiste », « mongol », « trisomique »…), ou None.
    À bloquer MÊME en auto-référence (owner 2026-06-27). Scan brut + plié + normalisé, frontière
    de mot. FAIL-SAFE → None."""
    try:
        if not raw:
            return None
        variants = [raw]
        fr = _fold(raw)
        if fr != raw:
            variants.append(fr)
        if normalized and normalized != raw:
            variants.append(normalized)
            fn = _fold(normalized)
            if fn != normalized:
                variants.append(fn)
        for v in variants:
            if not v:
                continue
            h = _hit(_RE_ABLEIST, v)
            if h:
                return h
    except Exception:
        return None
    return None


# Chargé à l'import (le module est importé une fois au boot).
_STATS = _load()
