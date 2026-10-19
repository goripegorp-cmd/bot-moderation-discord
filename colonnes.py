"""colonnes.py — texte à colonnes fixes pour les fichiers exportés (liste du clan, recrutements).

Collé dans un bloc-notes ou ouvert sur téléphone, chaque valeur reste dans sa colonne : un
émoji ou un idéogramme compte pour deux.
"""
from __future__ import annotations

import unicodedata


def largeur(t: str) -> int:
    """Colonnes occupées à l'écran : un émoji ou un idéogramme en prend deux."""
    n = 0
    for ch in t:
        if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def cadrer(t: str, n: int) -> str:
    """Le texte tient dans `n` colonnes : coupé (…) ou complété d'espaces."""
    t = "".join(ch for ch in str(t) if ch.isprintable()).replace("`", "ˋ").strip()
    if largeur(t) > n:
        coupe = ""
        for ch in t:
            if largeur(coupe + ch) > n - 1:
                break
            coupe += ch
        t = coupe + "…"
    return t + " " * (n - largeur(t))


def ligne(valeurs, colonnes) -> str:
    """Une ligne du tableau : chaque valeur cadrée sur la largeur de sa colonne."""
    return "".join(cadrer(v, w) + " " for v, (_t, w) in zip(valeurs, colonnes)).rstrip()


def entete(colonnes) -> list[str]:
    tete = ligne([t for t, _w in colonnes], colonnes)
    return [tete, "-" * largeur(tete)]
