"""qualite.py — un message « construit », ou du remplissage ? (29/10/2026)

Le fondateur : « ils vont dire bonjour à tous les messages qu'ils voient… il y en a, ils vont juste mettre plein de gifs,
sans discussion… si tu regardes l'historique de quelqu'un, c'est que des gifs, que des bonjours, mais il peut participer
au cadeau… c'est pas construit. Je te parle pour les cadeaux, mais aussi pour plein d'autres fonctionnalités du bot. »

Un message NE compte PAS (rend sa raison) quand :
  · « vide »    — aucun mot : un GIF ou un lien seul, des émojis, un sticker, une image sans texte ;
  · « salut »   — rien qu'une salutation (« bonjour », « cc », « yo », « gm »…), sauf la première de la journée (12 h) ;
  · « doublon » — le même texte (ou presque) qu'un de ses 10 derniers messages des 2 dernières heures ;
  · « plafond » — déjà `PLAFOND_HEURE` messages comptés dans l'heure (on ne rattrape pas tout en spammant à la fin).
  · « duo »     — deux membres seuls dans un salon s'échangent 12 messages ou plus en 10 min, presque tous très courts
                  (« mdr », « ouais », « grave ») : leurs messages de 3 mots ou moins ne comptent plus. Leurs vraies phrases,
                  si (deux personnes qui discutent vraiment ne perdent rien de ce qui est construit).
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
DUO_FENETRE_S = 600
DUO_MIN = 12
COURT = 3                 # mots
BONUS_MAX_HEURE = 10      # réponses comptées double vers la MÊME personne, par heure
MEMOIRE_MAX = 5000
RAISONS = {"vide": "GIF, lien, émojis ou image sans texte", "salut": "salutations répétées",
           "doublon": "copiés-collés", "plafond": "plus de 60 par heure", "duo": "échanges très courts à deux"}

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
        self._salons: OrderedDict = OrderedDict()   # salon → derniers messages (t, auteur, court)

    def _de(self, cle):
        e = self._m.get(cle)
        if e is None:
            e = self._m[cle] = {"salut": -1e12, "textes": deque(maxlen=DOUBLONS_SUIVIS), "heure": deque(),
                                "bonus": deque()}
            if len(self._m) > MEMOIRE_MAX:
                self._m.popitem(last=False)
        else:
            self._m.move_to_end(cle)
        return e

    def _duo_ferme(self, salon, qui, t: float, court: bool) -> tuple:
        """(fermé, ping-pong) : seuls deux membres parlent dans ce salon depuis 10 min (12 messages ou plus) ; ping-pong
        si en plus 70 % de ces messages sont très courts."""
        if salon is None:
            return False, False
        d = self._salons.get(salon)
        if d is None:
            d = self._salons[salon] = deque(maxlen=20)
            if len(self._salons) > MEMOIRE_MAX:
                self._salons.popitem(last=False)
        d.append((t, qui, court))
        recents = [x for x in d if t - x[0] < DUO_FENETRE_S]
        auteurs = {x[1] for x in recents}
        ferme = len(recents) >= DUO_MIN and len(auteurs) == 2
        return ferme, ferme and sum(x[2] for x in recents) >= 0.7 * len(recents)

    def juger(self, cle, texte: str, t: float, *, reponse: bool = False, salon=None, cible=None) -> tuple:
        """(raison, poids) : raison "" si le message compte (poids 1, ou 2 pour une vraie réponse à quelqu'un)."""
        m = mots(texte)
        if not m:
            return "vide", 0
        e = self._de(cle)
        qui = cle[-1] if isinstance(cle, tuple) else cle
        ferme, ping_pong = self._duo_ferme(salon, qui, t, len(m) <= COURT)
        if ping_pong and len(m) <= COURT:
            return "duo", 0
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
        if not (reponse and len(m) > COURT and not ferme):
            return "", 1
        while e["bonus"] and t - e["bonus"][0][0] >= 3600:
            e["bonus"].popleft()
        if sum(1 for _q, c in e["bonus"] if c == cible) >= BONUS_MAX_HEURE:
            return "", 1
        e["bonus"].append((t, cible))
        return "", 2

    def oublier(self) -> None:
        self._m.clear()
        self._salons.clear()
