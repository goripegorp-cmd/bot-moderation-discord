"""qualite.py — un message « construit », ou du remplissage ? (29/10/2026)

Le fondateur : « ils vont dire bonjour à tous les messages qu'ils voient… il y en a, ils vont juste mettre plein de gifs,
sans discussion… si tu regardes l'historique de quelqu'un, c'est que des gifs, que des bonjours, mais il peut participer
au cadeau… c'est pas construit. Je te parle pour les cadeaux, mais aussi pour plein d'autres fonctionnalités du bot. »

Un message NE compte PAS (rend sa raison) quand :
  · « vide »    — aucun mot : un GIF ou un lien seul, des émojis, un sticker, une image sans texte ;
  · « salut »   — rien qu'une salutation (« bonjour », « cc », « yo », « gm »…), sauf la première de la journée (12 h) ;
  · « doublon » — le même texte (ou presque) qu'un de ses 10 derniers messages des 2 dernières heures ;
  · « plafond » — déjà `PLAFOND_HEURE` messages comptés dans l'heure (on ne rattrape pas tout en spammant à la fin).
Sinon "" : il compte. `reponse` (il répond à quelqu'un d'autre, avec une vraie phrase) : `poids` 2 — la discussion
compte plus qu'un message dans le vide. Fonctions pures sur une mémoire bornée (`Juge`), aucune base, aucun réseau.
"""
from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict, deque

SALUT_S = 12 * 3600
DOUBLON_S = 2 * 3600
DOUBLONS_SUIVIS = 10
PLAFOND_HEURE = 60
MEMOIRE_MAX = 5000
RAISONS = {"vide": "GIF, lien, émojis ou image sans texte", "salut": "salutations répétées",
           "doublon": "copiés-collés", "plafond": "plus de 60 par heure"}

_BALISES = re.compile(r"<[^<>\s]*>|https?://\S+")   # émojis du serveur, mentions, liens (un GIF) : pas des mots
_MOT = re.compile(r"[^\W\d_]+")
SALUTATIONS = frozenset("""
bonjour bonsoir salut slt cc coucou yo hey hello hi hii bjr bsr re rebonjour resalut wesh wsh bonne nuit journee
soiree matinee aprem gm gn good morning night evening afternoon hola buenos dias ola ciao tout le monde monde a
tous toutes vous les gars la team mes amis everyone guys all y
""".split())


def plier(texte: str) -> str:
    """Minuscules, sans accents, lettres répétées ramenées à deux au plus (« bonjourrrr » → « bonjourr »)."""
    t = unicodedata.normalize("NFKD", str(texte or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"(.)\1{2,}", r"\1\1", t)


def mots(texte: str) -> list:
    return _MOT.findall(plier(_BALISES.sub(" ", str(texte or ""))))


def salutation_seule(m: list) -> bool:
    """Rien que des mots de salutation (« bonjour tout le monde », « cc », « gm ») ; « bonjourr » compte aussi."""
    return bool(m) and all(re.sub(r"(.)\1+", r"\1", x) in SALUTATIONS or x in SALUTATIONS for x in m)


class Juge:
    """La mémoire de chaque membre : sa dernière salutation comptée, ses derniers textes, ses comptés de l'heure."""

    def __init__(self):
        self._m: OrderedDict = OrderedDict()

    def _de(self, cle):
        e = self._m.get(cle)
        if e is None:
            e = self._m[cle] = {"salut": -1e12, "textes": deque(maxlen=DOUBLONS_SUIVIS), "heure": deque()}
            if len(self._m) > MEMOIRE_MAX:
                self._m.popitem(last=False)
        else:
            self._m.move_to_end(cle)
        return e

    def juger(self, cle, texte: str, t: float, *, reponse: bool = False) -> tuple:
        """(raison, poids) : raison "" si le message compte (poids 1, ou 2 pour une vraie réponse à quelqu'un)."""
        m = mots(texte)
        if not m:
            return "vide", 0
        e = self._de(cle)
        while e["heure"] and t - e["heure"][0] >= 3600:
            e["heure"].popleft()
        if len(e["heure"]) >= PLAFOND_HEURE:
            return "plafond", 0
        if salutation_seule(m):
            if t - e["salut"] < SALUT_S:
                return "salut", 0
            e["salut"] = t
        else:
            empreinte = " ".join(re.findall(r"\w+", plier(_BALISES.sub(" ", str(texte or "")))))   # chiffres compris
            if any(x == empreinte and t - q < DOUBLON_S for x, q in e["textes"]):
                return "doublon", 0
            e["textes"].append((empreinte, t))
        e["heure"].append(t)
        return "", (2 if reponse and len(m) > 3 and not salutation_seule(m) else 1)

    def oublier(self) -> None:
        self._m.clear()
