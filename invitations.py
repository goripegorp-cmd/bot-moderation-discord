"""invitations.py — Les invitations de chaque membre (24/10/2026, le fondateur : « des conditions pour que les
gens invitent des gens sur le serveur, et combien ils doivent avoir d'invitations au total sur leur lien… de
vrais systèmes de conditions qui valorisent le serveur »).

Discord donne, pour chaque lien d'invitation, son auteur et son nombre d'utilisations. Un lien expiré ou
supprimé disparaît avec son compteur : on garde donc, par lien, le plus haut nombre vu. Le total d'un membre
= la somme de ses liens. Relevé toutes les 5 minutes, et 10 s après une arrivée (une rafale d'arrivées n'en
fait qu'un). Il faut au bot « Gérer le serveur » pour lire les liens.
"""
from __future__ import annotations

import asyncio
import time

import discord

RELEVE_S = 300.0      # un relevé toutes les 5 minutes…
APRES_ARRIVEE_S = 10.0  # …et 10 s après une arrivée

_get_db = None
_log = print
_derniers: dict = {}   # guild_id → time.monotonic() du dernier relevé
_prevus: dict = {}     # guild_id → la tâche du relevé qui suit une arrivée


def setup(*, get_db, log=None):
    global _get_db, _log
    _get_db, _log = get_db, log or print


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS invitations_liens (guild_id INTEGER NOT NULL, code TEXT NOT NULL,"
            " auteur_id INTEGER NOT NULL, utilisations INTEGER NOT NULL DEFAULT 0, vu INTEGER NOT NULL,"
            " PRIMARY KEY (guild_id, code))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_invitations_auteur ON invitations_liens(guild_id, auteur_id)")
        await db.commit()


_SQL = ("INSERT INTO invitations_liens(guild_id, code, auteur_id, utilisations, vu) VALUES(?,?,?,?,?)"
        " ON CONFLICT(guild_id, code) DO UPDATE SET utilisations=MAX(utilisations, excluded.utilisations),"
        " auteur_id=excluded.auteur_id, vu=excluded.vu")


async def _ecrire(lignes: list) -> None:
    if not lignes:
        return
    async with _get_db() as db:
        await db.executemany(_SQL, lignes)
        await db.commit()


async def relever(g, *, forcer: bool = False) -> int:
    """Les liens du serveur et leurs utilisations. Rend le nombre de liens lus ; 0 si ce n'est pas encore
    l'heure ; -1 si Discord refuse (droits) ou ne répond pas."""
    maintenant = time.monotonic()
    if not forcer and maintenant - _derniers.get(g.id, -1e9) < RELEVE_S:
        return 0
    _derniers[g.id] = maintenant
    me = getattr(g, "me", None)
    if me is None or not me.guild_permissions.manage_guild:
        return -1
    try:
        liens = await g.invites()
    except discord.HTTPException as ex:
        _log("[INVITES][E1] liens d'invitation non lus")
        _log(f"[INVITES][E1:DETAIL] guild={g.id} {type(ex).__name__} {ex}")
        return -1
    t = int(time.time())
    lignes = [(g.id, str(x.code), int(x.inviter.id), int(x.uses or 0), t) for x in liens
              if getattr(x, "inviter", None) is not None and not getattr(x.inviter, "bot", False)]
    await _ecrire(lignes)
    return len(lignes)


async def sur_lien(invite) -> None:
    """Un lien créé : il entre dans le relevé tout de suite (avec 0 utilisation)."""
    g, auteur = getattr(invite, "guild", None), getattr(invite, "inviter", None)
    if g is None or auteur is None or getattr(auteur, "bot", False):
        return
    await _ecrire([(g.id, str(invite.code), int(auteur.id), int(invite.uses or 0), int(time.time()))])


def planifier(g) -> None:
    """Une arrivée : un relevé dans 10 s. Une rafale d'arrivées (un raid) n'en fait qu'un."""
    if g.id in _prevus:
        return

    async def _plus_tard():
        try:
            await asyncio.sleep(APRES_ARRIVEE_S)
            await relever(g, forcer=True)
        finally:
            _prevus.pop(g.id, None)
    _prevus[g.id] = asyncio.create_task(_plus_tard())


async def total(guild_id: int, membre_id: int) -> int:
    """Toutes les personnes venues par les liens de ce membre (le plus haut compteur vu de chaque lien)."""
    async with _get_db() as db:
        async with db.execute("SELECT COALESCE(SUM(utilisations), 0) FROM invitations_liens"
                              " WHERE guild_id=? AND auteur_id=?", (int(guild_id), int(membre_id))) as cur:
            return int((await cur.fetchone())[0] or 0)


async def totaux(guild_id: int) -> dict:
    """{membre: total} pour tout le serveur, d'une seule lecture."""
    async with _get_db() as db:
        async with db.execute("SELECT auteur_id, SUM(utilisations) FROM invitations_liens WHERE guild_id=?"
                              " GROUP BY auteur_id", (int(guild_id),)) as cur:
            return {int(u): int(n or 0) for u, n in await cur.fetchall()}


async def nb_liens(guild_id: int) -> int:
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM invitations_liens WHERE guild_id=?", (int(guild_id),)) as cur:
            return int((await cur.fetchone())[0] or 0)
