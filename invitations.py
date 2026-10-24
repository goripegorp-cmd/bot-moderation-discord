"""invitations.py — Qui a fait venir qui (24/10/2026, le fondateur : « des conditions pour que les gens invitent
des gens… combien ils doivent avoir d'invitations », puis : « attention aux faux comptes, les comptes doubles,
il faut vraiment que ce soit sûr. Les gens qui sont invités puis qui quittent directement, il faut que ce soit
bien enlevé des statistiques »).

À chaque arrivée, les compteurs des liens d'invitation sont comparés à ceux d'avant : le lien qui a pris UNE
utilisation, et lui seul, est celui de l'arrivant — son auteur l'a invité. Rien n'est deviné : deux liens qui
bougent (deux arrivées à la fois), aucun lien qui bouge (le lien personnalisé du serveur), un lien épuisé qui
disparaît, une rafale d'arrivées, pas de photo d'avant (le démarrage) — l'arrivée n'est rattachée à personne.

Une invitation compte seulement si l'invité est TOUJOURS sur le serveur (un départ l'enlève aussitôt, et le
ménage horaire rattrape ceux partis pendant une coupure), que son compte Discord avait au moins COMPTE_MIN_J
jours à son arrivée (les faux comptes sont neufs), que ce n'est ni un bot ni l'auteur lui-même. Un membre ne
compte qu'une fois : revenu par un autre lien, il compte pour le dernier. Comptées depuis le 24/10/2026.
Il faut au bot « Gérer le serveur » pour lire les liens.
"""
from __future__ import annotations

import asyncio
import time

import discord

COMPTE_MIN_J = 7          # un compte Discord plus jeune à son arrivée ne compte pas (faux compte)
MENAGE_S = 3600.0         # les départs manqués (bot coupé) sont rattrapés toutes les heures

_get_db = None
_log = print
_photos: dict = {}        # guild_id → {code: (auteur_id, utilisations, max_utilisations)}
_perimees: set = set()    # guild_id dont la photo a pu manquer une arrivée : la suivante ne crédite personne
_verrous: dict = {}
_menages: dict = {}       # guild_id → time.monotonic() du dernier ménage


def setup(*, get_db, log=None):
    global _get_db, _log
    _get_db, _log = get_db, log or print


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS invitations_arrivees (guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " auteur_id INTEGER NOT NULL, code TEXT NOT NULL, arrive INTEGER NOT NULL, compte_cree INTEGER NOT NULL,"
            " parti INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, membre_id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_invitations_auteur ON invitations_arrivees(guild_id, auteur_id)")
        await db.commit()


def _verrou(gid: int) -> asyncio.Lock:
    return _verrous.setdefault(int(gid), asyncio.Lock())


async def _ecrire(sql: str, args: tuple) -> int:
    async with _get_db() as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return int(cur.rowcount or 0)


async def _lire_liens(g):
    """{code: (auteur, utilisations, maximum)} ; None si le bot n'a pas « Gérer le serveur » ou si Discord ne
    répond pas."""
    me = getattr(g, "me", None)
    if me is None or not me.guild_permissions.manage_guild:
        return None
    try:
        liens = await g.invites()
    except discord.HTTPException as ex:
        _log("[INVITES][E1] liens d'invitation non lus")
        _log(f"[INVITES][E1:DETAIL] guild={g.id} {type(ex).__name__} {ex}")
        return None
    return {str(x.code): (int(getattr(x.inviter, "id", 0) or 0), int(x.uses or 0), int(x.max_uses or 0))
            for x in liens}


def lien_utilise(avant: dict, apres: dict):
    """Le code du lien qui a servi à UNE arrivée, ou None dès que ce n'est pas sûr. Fonction pure."""
    servis = []
    for code, (_auteur, n, _mx) in apres.items():
        n0 = avant[code][1] if code in avant else 0
        if n - n0 == 1:
            servis.append(code)
        elif n - n0 > 1:
            return None          # plusieurs arrivées par ce lien depuis la photo : on ne sait pas laquelle
    return servis[0] if len(servis) == 1 else None


async def photographier(g) -> int:
    """La photo des liens, point de départ des comparaisons (au démarrage). Rend le nombre de liens, -1 sinon."""
    async with _verrou(g.id):
        _perimees.discard(g.id)   # la photo qui suit est neuve (une arrivée pendant la lecture la re-marque)
        photo = await _lire_liens(g)
        if photo is None:
            return -1
        _photos[g.id] = photo
        return len(photo)


async def sur_arrivee(membre) -> int:
    """Rattache l'arrivée à son lien, si c'est sûr. Rend l'auteur (0 : personne). Une arrivée pendant qu'une
    autre est en cours n'interroge pas Discord : la rafale n'est rattachée à personne (raid, faux comptes).

    Ignorée, elle rend aussi la photo « périmée » : la lecture en cours a pu se faire avant elle, et la
    comparaison suivante verrait son lien bouger — l'arrivée d'après (lien personnalisé, Discovery…) serait
    créditée au propriétaire de ce lien. La comparaison suivante ne crédite donc personne et repart d'une
    photo neuve. Même chose quand les liens n'ont pas pu être lus."""
    g = getattr(membre, "guild", None)
    if g is None or getattr(membre, "bot", False) or _get_db is None:
        return 0                  # avant le branchement (le démarrage) : rien n'est suivi encore
    verrou = _verrou(g.id)
    if verrou.locked():
        _perimees.add(g.id)
        return 0
    async with verrou:
        #  Lu AVANT la lecture des liens : une arrivée ignorée pendant cette lecture re-marque la photo.
        perimee = g.id in _perimees
        _perimees.discard(g.id)
        avant, apres = _photos.get(g.id), await _lire_liens(g)
        if apres is None:
            _perimees.add(g.id)
            return 0
        _photos[g.id] = apres
        code = lien_utilise(avant, apres) if avant is not None and not perimee else None
        auteur = apres[code][0] if code else 0
        if not auteur or auteur == membre.id:
            return 0
        cree = getattr(membre, "created_at", None)
        await _ecrire("INSERT OR REPLACE INTO invitations_arrivees(guild_id, membre_id, auteur_id, code, arrive,"
                      " compte_cree, parti) VALUES(?,?,?,?,?,?,0)",
                      (g.id, membre.id, auteur, code, int(time.time()),
                       int(cree.timestamp()) if cree is not None else int(time.time())))
        return auteur


async def sur_depart(membre) -> None:
    """Un invité qui part ne compte plus — tout de suite."""
    g = getattr(membre, "guild", None)
    if g is not None and _get_db is not None:   # avant le branchement : le ménage horaire rattrapera
        await _ecrire("UPDATE invitations_arrivees SET parti=? WHERE guild_id=? AND membre_id=? AND parti=0",
                      (int(time.time()), g.id, membre.id))


def sur_lien(invite) -> None:
    """Un lien créé entre dans la photo, avec ses utilisations."""
    g = getattr(invite, "guild", None)
    photo = _photos.get(getattr(g, "id", 0))
    if photo is not None:
        photo[str(invite.code)] = (int(getattr(invite.inviter, "id", 0) or 0), int(invite.uses or 0),
                                   int(invite.max_uses or 0))


async def reconcilier(g) -> int:
    """Les invités qui ne sont plus sur le serveur (partis pendant une coupure du bot) sont enlevés. Rend le
    nombre enlevé."""
    if not getattr(g, "chunked", True):
        return 0                 # la liste des membres n'est pas encore complète : on ne conclut rien
    async with _get_db() as db:
        async with db.execute("SELECT membre_id FROM invitations_arrivees WHERE guild_id=? AND parti=0",
                              (g.id,)) as cur:
            absents = [int(r[0]) for r in await cur.fetchall() if g.get_member(int(r[0])) is None]
        if absents:
            t = int(time.time())
            await db.executemany("UPDATE invitations_arrivees SET parti=? WHERE guild_id=? AND membre_id=?",
                                 [(t, g.id, u) for u in absents])
            await db.commit()
    return len(absents)


async def entretenir(g) -> None:
    """Appelé souvent (la boucle des cadeaux) : la photo au premier passage, le ménage toutes les heures."""
    if g.id not in _photos:
        await photographier(g)
    if time.monotonic() - _menages.get(g.id, -1e9) > MENAGE_S:
        _menages[g.id] = time.monotonic()
        await reconcilier(g)


_VALIDE = "parti=0 AND arrive - compte_cree >= ?"


async def total(guild_id: int, membre_id: int) -> int:
    """Les invités de ce membre qui comptent : toujours là, comptes de COMPTE_MIN_J jours et plus."""
    async with _get_db() as db:
        async with db.execute(f"SELECT COUNT(*) FROM invitations_arrivees WHERE guild_id=? AND auteur_id=? AND {_VALIDE}",
                              (int(guild_id), int(membre_id), COMPTE_MIN_J * 86400)) as cur:
            return int((await cur.fetchone())[0] or 0)


async def totaux(guild_id: int) -> dict:
    """{membre: invités qui comptent} pour tout le serveur, d'une seule lecture."""
    async with _get_db() as db:
        async with db.execute(f"SELECT auteur_id, COUNT(*) FROM invitations_arrivees WHERE guild_id=? AND {_VALIDE}"
                              " GROUP BY auteur_id", (int(guild_id), COMPTE_MIN_J * 86400)) as cur:
            return {int(u): int(n) for u, n in await cur.fetchall()}


async def releve(guild_id: int) -> dict:
    """Pour /stats (des chiffres) : arrivées rattachées, celles qui comptent, partis, comptes trop neufs."""
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*), SUM(parti=0 AND arrive - compte_cree >= ?), SUM(parti>0),"
                              " SUM(parti=0 AND arrive - compte_cree < ?) FROM invitations_arrivees WHERE guild_id=?",
                              (COMPTE_MIN_J * 86400, COMPTE_MIN_J * 86400, int(guild_id))) as cur:
            n, ok, partis, neufs = await cur.fetchone()
    return {"rattachees": int(n or 0), "comptent": int(ok or 0), "parties": int(partis or 0),
            "comptes_neufs": int(neufs or 0), "photo": int(guild_id) in _photos}
