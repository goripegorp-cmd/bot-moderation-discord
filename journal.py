"""journal.py — le journal Railway : les VRAIES erreurs, et chacune une fois.

14/10/2026, le propriétaire : « il m'affiche trop de logs […] ça affiche juste
les erreurs, ou les chargements qui ont échoué, mais les vraies erreurs.
Pareil, les diagnostics, ils ne servent à rien […] un vrai système propre et
optimisé, qui ne crée pas des milliers de mêmes messages tout le temps. »

L'ancien filtre (Phase 251, `_QuietStdout`) devinait d'après le TEXTE et
laissait passer toute ligne inconnue : ~15 lignes de bilan de veille toutes les
30 min, et « 0 échec(s) » pris pour une erreur.

LA RÈGLE — décidée par le CONTEXTE du print, pas par ses mots :
  1. un print fait PENDANT le traitement d'une exception (dans un `except` :
     `sys.exc_info()`) est une erreur → affiché. Mesuré : 875 des 1 104 print
     du dépôt sont dans un `except` ;
  2. hors `except`, seulement une ALARME explicite (`ALARME` : 🚨, ❌,
     Traceback, [STALL], ERREUR/ERROR/ÉCHEC en capitales, « erreur : »,
     « impossible »…) — les huit vraies alertes du dépôt en portent une ;
  3. tout le reste se tait : bilans, compteurs, démarrage, [DIAG] EVENT/WARN.
Puis : un même message (chiffres ignorés) au plus une fois par 6 h — il dit,
au retour, combien de fois il s'est répété — et au plus 30 lignes par minute.
Une trace d'erreur sort en UN bloc (sinon la déduplication la couperait).

VERBOSE_LOGS=1 → aucun filtre (diagnostic ponctuel). Installé par bot.py
seulement quand il est le programme principal : les tests n'en voient rien.
"""
from __future__ import annotations

import builtins
import hashlib
import logging
import re
import sys
import threading
import time
import traceback
from collections import OrderedDict

FENETRE_S = 6 * 3600
PLAFOND_MINUTE = 30
MAX_CLES = 4000

ALARME = re.compile(
    r"🚨|❌|Traceback|\[STALL\]|STARVATION|\bon_error\b"
    r"|\b(?:ERREUR|ERROR|ÉCHEC|ECHEC|IMPOSSIBLE|INTROUVABLE|FATAL|CRITICAL|AVEUGLE|FAILED)\b"
    r"|(?i:\b(?:erreur|error|échec|echec|failed)\s*:)|(?i:\bimpossible\b)")

_print_original = builtins.print
_print_exception_original = traceback.print_exception
_verrou = threading.Lock()
_vus: OrderedDict = OrderedDict()      # empreinte → [dernier affichage, répétitions tues]
_minute = [0.0, 0, 0]                  # début de la minute, affichées, tues


def a_garder(message: str, en_exception: bool) -> bool:
    return en_exception or bool(ALARME.search(message))


def _empreinte(message: str) -> str:
    """Le message entier, chiffres ignorés : « 403 sur #12 » = « 403 sur #57 »,
    mais deux traces d'erreur différentes restent deux messages."""
    norme = re.sub(r"\d+", "#", " ".join(message.split()))
    return hashlib.blake2b(norme.encode("utf-8", "replace"), digest_size=12).hexdigest()


def filtrer(message: str, maintenant: float):
    """Le texte à écrire, ou None : déjà dit il y a moins de 6 h, ou plafond de
    la minute atteint."""
    cle = _empreinte(message)
    with _verrou:
        e = _vus.get(cle)
        if e is not None and maintenant - e[0] < FENETRE_S:
            e[1] += 1
            return None
        entete = ""
        if maintenant - _minute[0] >= 60:
            if _minute[2]:
                entete = (f"[journal] {_minute[2]} ligne(s) tue(s) la minute "
                          f"précédente (trop de messages d'un coup)\n")
            _minute[0], _minute[1], _minute[2] = maintenant, 0, 0
        if _minute[1] >= PLAFOND_MINUTE:
            _minute[2] += 1
            return None
        _minute[1] += 1
        repetes = e[1] if e is not None else 0
        _vus[cle] = [maintenant, 0]
        _vus.move_to_end(cle)
        while len(_vus) > MAX_CLES:
            _vus.popitem(last=False)
    return entete + message + (f"  (répété {repetes} fois depuis le précédent)"
                               if repetes else "")


def _console(f) -> bool:
    return f is None or f in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)


def imprimer(*args, sep=" ", end="\n", file=None, flush=False):
    """Remplace `print` : vers un fichier, rien ne change ; vers la console, la
    règle du module."""
    if not _console(file):
        return _print_original(*args, sep=sep, end=end, file=file, flush=flush)
    try:
        message = (" " if sep is None else sep).join(str(a) for a in args)
    except Exception:
        return _print_original(*args, sep=sep, end=end, file=file, flush=flush)
    if not a_garder(message, sys.exc_info()[0] is not None):
        return None
    texte = filtrer(message, time.monotonic())
    if texte is not None:
        _print_original(texte, end="\n" if end is None else end, file=file, flush=True)
    return None


def _print_exception(*a, **k):
    """Une trace d'erreur en UN bloc, dédupliquée comme le reste."""
    if not _console(k.get("file")):
        return _print_exception_original(*a, **k)
    try:
        sans = {c: v for c, v in k.items() if c != "file"}
        bloc = "".join(traceback.format_exception(*a, **sans)).rstrip("\n")
    except Exception:
        return _print_exception_original(*a, **k)
    imprimer(bloc, file=k.get("file") or sys.stderr)


class FiltreLogging(logging.Filter):
    """discord.py, asyncio, aiohttp : la même déduplication."""

    def filter(self, record):
        try:
            message = f"{record.name}: {record.getMessage()}"
            if record.exc_info:
                #  Deux exceptions différentes sous le même message restent deux.
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
        except Exception:
            return True
        return filtrer(message, time.monotonic()) is not None


def installer() -> bool:
    import os
    if os.getenv("VERBOSE_LOGS", "0") == "1":
        return False
    builtins.print = imprimer
    traceback.print_exception = _print_exception
    return True
