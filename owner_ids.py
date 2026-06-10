"""owner_ids.py — SOURCE UNIQUE des super-owners (fix sécu : audit revue totale).

PROBLÈME corrigé : SUPER_OWNER_ID était hardcodé avec DEUX valeurs DIVERGENTES —
bot.py:407 = 781205382923288593 (GoRipe, le vrai owner, utilisé ~60×) MAIS 5 sites de
modules (raid_detector, rate_limiter, staff_sanction, webhook_tracker) hardcodaient
1027544786068783194. Conséquence : (a) GoRipe N'était PAS protégé du kick/ban via le
panneau staff ni exempté du rate-limit / autorité raid·webhooks dans ces modules ;
(b) un ID non unifié détenait ces pouvoirs. Cette divergence est la faille fermée ici.

CENTRALISATION : les modules importent ce fichier et appellent `is_super_owner(uid)`.
UNION des deux IDs connus (personne ne perd l'accès = pas de lockout), + override par
variable d'environnement `EXTRA_OWNER_IDS` (IDs séparés par virgules) pour ajouter/gérer
des co-owners SANS toucher au code.

CONFIRMÉ PAR L'OWNER (2026-06-10) : le SEUL compte super-owner est 781205382923288593
(GoRipe). L'ID legacy 1027544786068783194 n'a PAS été reconnu par l'owner → RETIRÉ du
cercle super-owner (durcissement « le plus sécurisé » : on ne laisse aucun compte non
confirmé détenir ces pouvoirs). Pour rajouter un co-owner sans toucher au code, utiliser
la variable d'environnement `EXTRA_OWNER_IDS` (IDs séparés par virgules).
"""
from __future__ import annotations

import os

# 781205382923288593 = GoRipe — UNIQUE super-owner confirmé (cf. en-tête).
_BASE_OWNER_IDS = {781205382923288593}


def _load() -> set:
    ids = set(_BASE_OWNER_IDS)
    raw = os.getenv("EXTRA_OWNER_IDS", "") or ""
    for tok in raw.replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            ids.add(int(tok))
    return ids


SUPER_OWNER_IDS = _load()


def is_super_owner(user_id) -> bool:
    """True si user_id fait partie des super-owners (fail-safe : False sur entrée invalide)."""
    try:
        return int(user_id) in SUPER_OWNER_IDS
    except Exception:
        return False
