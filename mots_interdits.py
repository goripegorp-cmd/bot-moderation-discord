"""mots_interdits.py — la liste de mots interdits du serveur : ce qui en est un,
et ce qui n'en est JAMAIS un (14/10/2026).

« Damn c'est magnifique ✨ » : message supprimé, compté comme mot interdit
(avertissement automatique au seuil). Le propriétaire : « des gens qui disent
“c'est magnifique, c'est bien” sont considérés comme des mots interdits […]
ils ne peuvent même plus s'exprimer ». Deux défauts :

  · la liste du serveur contenait « damn » — une EXCLAMATION, pas une insulte.
    Le filtre d'insultes gradué (21/06) la laissait déjà passer (niveau 1 =
    expression → rien) ; la liste, elle, la punissait. Les exclamations
    ci-dessous ne peuvent plus y entrer, et en sont retirées au démarrage ;

  · la détection « anti-contournement » RECOLLAIT les mots : « j'ai pu te
    répondre » lu « pute », « la mer de glace » lu « merde », « ni que » lu
    « nique » (une seule coupure suffisait). Et elle retirait les espaces de
    tout le message, si bien que « c0n » au milieu d'une phrase n'était PAS vu.
    Désormais : le mot tel quel, en leet ou coupé DANS le même mot (« c0n »,
    « $alope », « c.on », « pu-te »), ou épelé avec un séparateur entre CHAQUE
    lettre (« c o n », « p u t e ») — jamais deux morceaux de mots voisins.
"""
from __future__ import annotations

import functools
import re
import unicodedata

#  Des exclamations : jamais une insulte, jamais dirigées contre quelqu'un.
#  Clés sans accents ni majuscules (voir `_cle`).
EXCLAMATIONS_LIBRES = frozenset({
    "damn", "dammit", "damnit", "damn it", "goddamn", "god damn", "crap",
    "crikey", "heck", "gosh", "oof", "omg", "oh my god",
    "mince", "zut", "flute", "punaise", "puree", "sacrebleu", "saperlipopette",
    "sapristi", "fichtre", "bon sang", "nom de zeus", "nom d'un chien",
})

#  Ce qui peut remplacer une lettre (leet) — la lettre elle-même comprise.
_LEET = {
    "a": "a@4", "e": "e3€", "i": "i1!|", "o": "o0", "s": "s$5", "t": "t7",
    "l": "l£",
}
#  Coupure DANS un même mot (« c.on », « pu-te ») : jamais d'espace, sinon
#  « j'ai pu te répondre » redevient « pute ».
_SEP_COLLE = r"[.\-_*]{0,3}"
#  Mot épelé : un séparateur entre CHAQUE lettre (« c o n », « p.u.t.e »).
#  ⚠️ Séparateurs DISJOINTS des classes de lettres (« | » et « ! » valent
#  « i ») : aucune ambiguïté, donc aucun retour arrière explosif (ReDoS).
_SEP_EPELE = r"[\s.\-_*]{1,3}"
#  Ni lettre ni chiffre juste avant / juste après : « con » ne matche pas « content ».
_AVANT = r"(?<![^\W_])"
_APRES = r"(?![^\W_])"


def _sans_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _cle(mot) -> str:
    return " ".join(_sans_accents(str(mot or "")).casefold().split())


def est_exclamation_libre(mot) -> bool:
    return _cle(mot) in EXCLAMATIONS_LIBRES


def trier_liste(mots) -> tuple[list, list]:
    """(gardés, retirés) : les exclamations sortent, l'ordre reste."""
    gardes, retires = [], []
    for m in mots or []:
        (retires if est_exclamation_libre(m) else gardes).append(m)
    return gardes, retires


def _classe(c: str) -> str:
    return "[" + re.escape(_LEET[c]) + "]" if c in _LEET else re.escape(c)


@functools.lru_cache(maxsize=4096)
def _motifs(cle: str) -> tuple:
    """(le mot, le mot épelé lettre par lettre) — compilés une fois par mot."""
    if " " in cle:
        #  Une expression de plusieurs mots : ses mots, dans l'ordre ; elle ne
        #  s'épelle pas.
        entier = re.compile(_AVANT + "".join(
            r"\s+" if c == " " else _classe(c) for c in cle) + _APRES)
        return entier, None
    entier = re.compile(_AVANT + _SEP_COLLE.join(_classe(c) for c in cle) + _APRES)
    epele = None
    if 2 <= len(cle) <= 40:
        epele = re.compile(_AVANT + _SEP_EPELE.join(_classe(c) for c in cle) + _APRES)
    return entier, epele


def cherche(texte, mots, liste_blanche=None):
    """(True, mot) au premier mot interdit trouvé, sinon (False, None).
    Un mot de la liste blanche n'est jamais bloqué."""
    if not mots or not texte:
        return False, None
    blancs = {_cle(w) for w in (liste_blanche or []) if str(w).strip()}
    t = _sans_accents(str(texte)).casefold()
    for brut in mots:
        cle = _cle(brut)
        if not cle or cle in blancs:
            continue
        #  Un mot fait de lettres ne se trouve pas dans des CHIFFRES seuls :
        #  « j'ai 55 ans » n'est pas « ss ».
        lettre = any(c.isalpha() for c in cle)
        for motif in _motifs(cle):
            if motif is None:
                continue
            for m in motif.finditer(t):
                if not lettre or any(c.isalpha() for c in m.group(0)):
                    return True, str(brut).strip().lower()
    return False, None
