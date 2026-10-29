"""acces_direction.py — la DIRECTION et le FONDATEUR dans les vocaux que le bot
crée (14/10/2026).

« Le rôle fondateur ou le rôle direction ne peuvent pas déplacer dans d'autres
voc […] alors que pourtant c'est des staffs de direction. » Un vocal créé par
le bot reçoit ses PROPRES permissions : il ne reprend pas celles de la
catégorie, où le staff tient d'ordinaire « Déplacer des membres ». On les lui
donne explicitement : voir, rejoindre, parler, déplacer.

Rôle Direction : son identifiant (donné par le propriétaire), surchargeable par
la variable `DIRECTION_ROLE_IDS` (« id1,id2 »). Rôle Fondateur : par son NOM
exact (« Fondateur », « 👑・Fondatrice », « Co-fondateur »…) — son identifiant
n'est pas connu du bot. Un rôle géré (intégration) n'est jamais pris.
"""
from __future__ import annotations

import os
import unicodedata

import discord

DIRECTION_DEFAUT = "1089228169028046988"
try:
    DIRECTION_ROLE_IDS = frozenset(
        int(x) for x in (os.environ.get("DIRECTION_ROLE_IDS") or DIRECTION_DEFAUT)
        .replace(";", ",").split(",") if x.strip())
except ValueError:
    print("[acces_direction] DIRECTION_ROLE_IDS illisible — identifiant par défaut")
    DIRECTION_ROLE_IDS = frozenset({int(DIRECTION_DEFAUT)})

NOMS_FONDATEUR = frozenset({"fondateur", "fondatrice", "fondateurs",
                            "cofondateur", "cofondatrice", "cofondateurs"})


def _nom(role) -> str:
    """Les lettres seules, sans accents ni majuscules : « 👑・Co-Fondateur »
    → « cofondateur »."""
    s = unicodedata.normalize("NFKD", str(getattr(role, "name", "") or ""))
    return "".join(c for c in s if c.isalpha() and not unicodedata.combining(c)).casefold()


def roles(guild) -> list:
    out = []
    for r in getattr(guild, "roles", None) or []:
        if r.is_default() or r.managed:
            continue
        if r.id in DIRECTION_ROLE_IDS or _nom(r) in NOMS_FONDATEUR:
            out.append(r)
    return out


def permission(perms_du_bot) -> discord.PermissionOverwrite:
    """Voir, rejoindre, parler — et déplacer, si le bot le peut lui-même
    (sinon Discord refuse TOUTE la création : 403, voir Phase 221)."""
    ow = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
    if getattr(perms_du_bot, "move_members", False):
        ow.move_members = True
    #  29/10/2026 : « les staffs peuvent bouger ou mute les gens s'ils font des bêtises dans les VOC créés ».
    if getattr(perms_du_bot, "mute_members", False):
        ow.mute_members = True
    if getattr(perms_du_bot, "manage_messages", False):
        ow.manage_messages = True
    return ow
