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

⚠️ OWNER : si l'un de ces 2 IDs de base n'est PAS un compte de confiance à toi, retire-le
de `_BASE_OWNER_IDS` ci-dessous (1 ligne) — la revue n'a pas pu vérifier que
1027544786068783194 est bien à toi.
"""
from __future__ import annotations

import os

# 781205382923288593  = GoRipe (référence canonique de bot.py:407)
# 1027544786068783194 = super-owner historique présent dans 5 modules
_BASE_OWNER_IDS = {781205382923288593, 1027544786068783194}


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
