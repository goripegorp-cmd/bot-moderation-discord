"""grooming_detector.py — Détection de GROOMING / approche prédatrice (owner 2026-06-27).

Priorité n°1 : PROTÉGER LES MINEURS. On repère la MANŒUVRE d'approche d'un prédateur — pas
seulement les termes pédocriminels « après coup » (déjà couverts par _RED_KEYWORDS). Catégories :
  • âge demandé (« quel âge as-tu »)        • flatterie sur la maturité (« mûr pour ton âge »)
  • secret / isolement (« garde ça entre nous »)  • passage en privé / autre plateforme (« viens en MP »)
  • demande de photo / vidéo                 • demande d'infos perso (adresse, numéro, ville)
  • proposition de rencontre IRL             • cadeaux contre quelque chose (Robux/Nitro/argent)
  • sollicitation SEXUELLE

⚠️ Le langage de grooming RECOUPE des phrases banales → matching GRADUÉ et à COMBO :
  level 3 = sexuel + (mineur/photo/âge)   → action maximale (suppression + BAN + alerte)
  level 2 = combo prédateur clair         → suppression + gel (timeout) + alerte URGENTE owner
  level 1 = 2 signaux mous                 → suppression + alerte owner (humain tranche), PAS de ban
  level 0 = rien / 1 signal isolé          → on ne fait RIEN (anti-faux-positif)

100 % FAIL-SAFE : toute erreur → (0, [], ''). Matching sur texte brut ET normalisé (anti-leet).
Bilingue FR/EN (les prédateurs basculent souvent en anglais), quelques formes ES.
"""
from __future__ import annotations

import re

_FLAGS = re.IGNORECASE


def _rx(*pats):
    return [re.compile(p, _FLAGS) for p in pats]


# ─── Catégories de signaux (regex). On vise des FORMULATIONS, pas des mots nus banals. ───
_CATS = {
    # Demander l'âge (surtout sous forme de question directe à la personne).
    'age': _rx(
        r"\bquel\s+age\s+(as[- ]?tu|t'?as|tu\s+as)\b",
        r"\bt'?as\s+quel\s+age\b",
        r"\btu\s+as\s+quel\s+age\b",
        r"\bton\s+age\b\s*\?*",
        r"\bt'?es\s+(mineur|majeur|au\s+coll[eè]ge|au\s+lyc[eé]e|en\s+(6|5|4|3)e)\b",
        r"\bhow\s+old\s+are\s+you\b",
        r"\bwhat'?s?\s+your\s+age\b",
        r"\bare\s+you\s+(1[0-7]|a\s+minor|under\s?age)\b",
        r"\bare\s+you\s+in\s+(middle|high)\s+school\b",
        r"\bcu[aá]ntos\s+a[nñ]os\s+tienes\b",
    ),
    # Flatterie sur la maturité (mécanisme classique de mise en confiance).
    'flatter': _rx(
        r"\bm[uû]r(e)?\s+pour\s+ton\s+age\b",
        r"\btu\s+fais\s+plus\s+(vieux|[aâ]g[eé])\b",
        r"\btu\s+parais\s+plus\s+(vieux|[aâ]g[eé]|grand)\b",
        r"\bmature\s+for\s+your\s+age\b",
        r"\byou\s+(act|seem|look)\s+(older|so\s+mature)\b",
        r"\bt'?es\s+(pas\s+comme\s+les\s+autres|sp[eé]cial(e)?|diff[eé]rent(e)?)\b",
    ),
    # Secret / isolement (« ne dis à personne »).
    'secret': _rx(
        r"\bgarde\s+(ça|ca|cela)\s+(entre\s+nous|pour\s+toi|secret)\b",
        r"\bentre\s+nous\s+(deux)?\b",
        r"\bne\s+(le\s+)?dis\s+(à|a)\s+personne\b",
        r"\bdis\s+(le\s+)?(à|a)\s+personne\b",
        r"\bc'?est\s+notre\s+secret\b",
        r"\btu\s+gardes\s+le\s+secret\b",
        r"\bdon'?t\s+tell\s+(anyone|anybody|your\s+(parents|mom|dad))\b",
        r"\bkeep\s+(this|it)\s+(between\s+us|secret|a\s+secret|private)\b",
        r"\bour\s+(little\s+)?secret\b",
    ),
    # Passage en privé / sur une autre plateforme (sortir du salon modéré).
    'dm': _rx(
        r"\b(viens|passe|on\s+(parle|continue)|parle[- ]?moi)\s+(en\s+)?(priv[eé]|dm|mp)\b",
        r"\b(ajoute|add)[- ]?moi\s+(sur|on)?\b",
        r"\brejoins?[- ]?moi\s+sur\b",
        r"\b(dm|mp)\s+me\b",
        r"\bmessage\s+me\s+(privately|on)\b",
        r"\blet'?s\s+(talk|chat|continue)\s+(in\s+)?(private|dms?|elsewhere)\b",
        r"\b(snap|snapchat|telegram|insta|instagram|whats\s?app|kik|discord\s+priv[eé]|tiktok)\b.{0,20}\b(toi|you|priv|dm|ajoute|add)\b",
        r"\bton\s+(snap|snapchat|telegram|insta|kik|tel|num[eé]ro)\b",
    ),
    # Demande de photo / vidéo de la personne.
    'photo': _rx(
        r"\benvoie([- ]?moi)?\s+(une|ta|des|ta\s+vraie)\s+(photo|tof|vid[eé]o|selfie|image)\b",
        r"\bune\s+(photo|vid[eé]o)\s+de\s+toi\b",
        r"\bmontre[- ]?(toi|moi)\b",
        r"\btu\s+ressembles\s+(à|a)\s+quoi\b",
        r"\bsend\s+(me\s+)?(a\s+)?(pic|picture|photo|selfie|video|vid)\b",
        r"\bshow\s+me\s+(your|a\s+pic|yourself)\b",
        r"\bpic\s+of\s+you\b",
        r"\bcam\b.{0,10}\b(toi|you|on)\b",
    ),
    # Demande d'infos perso identifiantes.
    'pii': _rx(
        r"\btu\s+(habites|vis)\s+(o[uù]|dans\s+quelle)\b",
        r"\bt'?es\s+de\s+quelle\s+ville\b",
        r"\bton\s+(adresse|num[eé]ro|t[eé]l[eé]?phone|tel|num)\b",
        r"\bwhere\s+do\s+you\s+live\b",
        r"\bwhat'?s?\s+your\s+(address|number|phone|city|real\s+name)\b",
        r"\bquelle\s+(ville|r[eé]gion|[eé]cole|coll[eè]ge|lyc[eé]e)\b",
        r"\bwhat\s+(school|city)\b.{0,15}\byou\b",
    ),
    # Proposition de rencontre IRL.
    'irl': _rx(
        r"\bon\s+(se\s+(voit|rencontre|retrouve)|peut\s+se\s+voir)\b",
        r"\bse\s+(voir|rencontrer)\s+(en\s+vrai|irl|en\s+r[eé]el)\b",
        r"\bje\s+peux\s+(venir|passer)\s+(te\s+voir|chez\s+toi)\b",
        r"\b(want\s+to|wanna|do\s+you\s+want\s+to)\s+meet(\s+up|\s+irl|\s+in\s+person)?\b",
        r"\bmeet\s+(up\s+)?(irl|in\s+person|in\s+real\s+life)\b",
        r"\bje\s+t'?emm[eè]ne\b",
    ),
    # Cadeaux / récompense contre quelque chose (leurre).
    'gift': _rx(
        r"\bje\s+t'?(ach[eè]te|offre|donne)\s+(des\s+)?(robux|nitro|skins?|v[- ]?bucks|argent|cadeau)\b",
        r"\b(robux|nitro|skins?|v[- ]?bucks|argent|gift\s?cards?)\s+(si|contre|pour)\s+(tu|toi|une\s+photo)\b",
        r"\bi'?ll\s+(buy|give|gift)\s+you\b.{0,20}\b(if|for)\b",
        r"\bi'?ll\s+pay\s+you\s+(if|for)\b",
    ),
    # Sollicitation SEXUELLE EXPLICITE uniquement (demande de nudes / d'actes / de contenu du corps).
    # ⚠️ On EXCLUT volontairement le flirt banal (« tu me plais », « t'es sexy/mignon ») : entre
    # ados c'est courant → ne JAMAIS bannir là-dessus. Ici, seulement le sans-ambiguïté.
    'sexual': _rx(
        r"\benvoie([- ]?moi)?\s+(un(e)?\s+)?(nude|nudes|photo\s+nue|photo\s+sexy|photo\s+de\s+tes\s+(seins|fesses|parties))\b",
        r"\b(montre|envoie)([- ]?moi)?\s+(tes\s+(seins|fesses|parties\s+intimes|t[eé]tons)|ton\s+(corps|cul|sexe))\b",
        r"\bsend\s+(me\s+)?(nudes?|a\s+nude|sexy\s+pics?|naked\s+pics?|pics?\s+of\s+your\s+(body|boobs|ass))\b",
        r"\bshow\s+me\s+your\s+(body|boobs|tits|ass|naked)\b",
        r"\bdo\s+you\s+(touch|play\s+with)\s+yourself\b",
        r"\b(tu\s+es|t'?es)\s+(encore\s+)?vierge\b\s*\?*",
        r"\bon\s+(se\s+)?fait\s+un\s+(call|appel|sexe)\s+(coquin|hot|sexy)\b",
        r"\b(sext(ing)?|cyber(sexe|sex))\b",
        r"\benvoie([- ]?moi)?\s+une\s+(vid[eé]o|photo)\s+(hot|coquine|sexy)\b",
    ),
}

# Paires « clairement prédatrices » → level 2 (combo). (cat, set_of_partners)
# NB : « photo+dm » seul (« envoie une photo en MP ») est EXCLU des paires fortes (trop banal entre
# amis) → il ne monte en level 2 que via un 3e signal (≥3 catégories). On garde les combos sans
# ambiguïté (photo+secret, photo+âge, IRL+quoi que ce soit, secret+privé…).
_STRONG_PAIRS = [
    ('photo', {'secret', 'pii', 'age', 'irl', 'gift'}),
    ('irl',   {'photo', 'pii', 'age', 'gift', 'secret', 'dm'}),
    ('age',   {'photo', 'pii', 'secret', 'irl'}),
    ('secret', {'dm', 'photo', 'pii', 'irl'}),
    ('gift',  {'photo', 'irl', 'secret'}),
]


def _norm(s):
    try:
        return (s or "").lower()
    except Exception:
        return ""


def scan(raw, normalized=None):
    """Renvoie (level, cats_matched:list, terms:list). FAIL-SAFE → (0, [], [])."""
    try:
        cands = []
        r = _norm(raw)
        if r:
            cands.append(r)
        if normalized:
            n = _norm(normalized)
            if n and n != r:
                cands.append(n)
        if not cands:
            return 0, [], []
        cats = set()
        terms = []
        for cat, regexes in _CATS.items():
            for rx in regexes:
                hit = None
                for cand in cands:
                    m = rx.search(cand)
                    if m:
                        hit = m.group(0)
                        break
                if hit is not None:
                    cats.add(cat)
                    terms.append(f"{cat}:{hit[:40]}")
                    break
        if not cats:
            return 0, [], []
        # ── NIVEAUX ──
        # 3 : sexuel + (mineur/photo/âge/secret) = quasi sans ambiguïté.
        if 'sexual' in cats and (cats & {'age', 'photo', 'secret', 'pii', 'irl'}):
            return 3, sorted(cats), terms
        # 2 : sollicitation sexuelle seule, OU combo prédateur clair (paire forte), OU ≥3 signaux.
        if 'sexual' in cats:
            return 2, sorted(cats), terms
        for cat, partners in _STRONG_PAIRS:
            if cat in cats and (cats & partners):
                return 2, sorted(cats), terms
        if len(cats) >= 3:
            return 2, sorted(cats), terms
        # 1 : 2 signaux mous = suspect → alerte humaine (pas de ban auto).
        if len(cats) >= 2:
            return 1, sorted(cats), terms
        return 0, sorted(cats), terms
    except Exception:
        return 0, [], []
