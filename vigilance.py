"""vigilance.py — un membre qui cumule les évènements graves (19/10/2026).

« Une alerte dans les logs quand un membre cumule plusieurs événements graves… et après, ça
s'enlève une fois qu'on a géré. »

Un incident = des évènements graves à moins de GROUPE_SECONDES l'un de l'autre (une détection et
sa sanction automatique ne comptent qu'une fois, avec la gravité la plus haute). Alerte dès
SEUIL_INCIDENTS incidents ou SEUIL_POINTS points sur FENETRE. Une seule carte par membre : mise à
jour tant qu'elle est ouverte, retirée par « Géré » ; seuls comptent ensuite les évènements
arrivés après.
"""
from __future__ import annotations

import asyncio
import time

import discord

import registre

FENETRE = 24 * 3600
GROUPE_SECONDES = 10
SEUIL_INCIDENTS = 3
SEUIL_POINTS = 4
ATTENTE = 3.0  # laisse arriver la sanction qui suit une détection avant de compter
_get_db = None
_bot = None
_salon = None
_carte = None
_epargne = None
_log = print
_en_attente: dict = {}
_verrous: dict = {}
_taches: set = set()


def setup(*, get_db, salon, carte, bot=None, epargne=None, log=None):
    """`salon(g)` → le salon des alertes ; `carte(g, membre_id, incidents, points, evenements)` →
    la vue de l'alerte ; `epargne(g, membre_id)` (asynchrone) → vrai pour la direction et le fondateur."""
    global _get_db, _salon, _carte, _bot, _epargne, _log
    _get_db, _salon, _carte, _bot, _epargne, _log = get_db, salon, carte, bot, epargne, log or print


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS vigilance (guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " message_id INTEGER DEFAULT 0, salon_id INTEGER DEFAULT 0, ouverte_le INTEGER DEFAULT 0,"
            " maj_le INTEGER DEFAULT 0, base_le INTEGER DEFAULT 0, gere_par INTEGER DEFAULT 0,"
            " PRIMARY KEY (guild_id, membre_id))")
        await db.commit()


def incidents(evenements: list[dict]) -> list[list[dict]]:
    """Les évènements (du plus ancien au plus récent) regroupés en incidents."""
    out: list[list[dict]] = []
    for e in evenements:
        if out and int(e["quand"]) - int(out[-1][-1]["quand"]) <= GROUPE_SECONDES:
            out[-1].append(e)
        else:
            out.append([e])
    return out


def mesure(evenements: list[dict]) -> tuple[int, int]:
    """(incidents, points) ; un incident vaut la gravité la plus haute de ses évènements."""
    groupes = incidents(evenements)
    return len(groupes), sum(max(int(e["gravite"] or 0) for e in g) for g in groupes)


def alerte_due(evenements: list[dict]) -> bool:
    n, points = mesure(evenements)
    return n >= SEUIL_INCIDENTS or points >= SEUIL_POINTS


async def _etat(guild_id: int, membre_id: int):
    async with _get_db() as db:
        async with db.execute("SELECT message_id, salon_id, ouverte_le, base_le FROM vigilance"
                              " WHERE guild_id=? AND membre_id=?", (guild_id, membre_id)) as cur:
            return await cur.fetchone()


def planifier(guild_id: int, membre_id: int) -> None:
    """Appelé par le registre à chaque évènement grave : un seul examen à la fois par membre."""
    cle = (int(guild_id), int(membre_id))
    if cle in _en_attente or _get_db is None:
        return
    t = asyncio.get_running_loop().create_task(_examiner_plus_tard(cle))
    _en_attente[cle] = t
    _taches.add(t)
    t.add_done_callback(_taches.discard)


async def _examiner_plus_tard(cle) -> None:
    try:
        await asyncio.sleep(ATTENTE)
    finally:
        _en_attente.pop(cle, None)
    await examiner(*cle)


async def examiner(guild_id: int, membre_id: int, g=None, maintenant: float | None = None):
    """Compte, puis poste ou met à jour la carte d'alerte. Rend le message, ou None."""
    async with _verrous.setdefault((guild_id, membre_id), asyncio.Lock()):
        try:
            return await _examiner(guild_id, membre_id, g, maintenant)
        except discord.HTTPException as ex:
            _log("[VIGILANCE][E1] alerte impossible")
            _log(f"[VIGILANCE][E1:DETAIL] {guild_id} {membre_id} {type(ex).__name__} {ex}")
            return None


async def _examiner(guild_id, membre_id, g, maintenant):
    t = int(maintenant or time.time())
    guild = g if g is not None else _guild(guild_id)
    if guild is None or (_epargne is not None and await _epargne(guild, membre_id)):
        return None
    etat = await _etat(guild_id, membre_id)
    message_id, salon_id, ouverte_le, base_le = etat or (0, 0, 0, 0)
    evts = await registre.graves(guild_id, membre_id, max(t - FENETRE, int(base_le or 0)))
    if not alerte_due(evts):
        return None
    n, points = mesure(evts)
    vue = _carte(guild, membre_id, n, points, evts)
    msg = None
    if ouverte_le and message_id:
        salon = guild.get_channel(int(salon_id))
        if salon is not None:
            try:
                msg = await salon.fetch_message(int(message_id))
                await msg.edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                msg = None
    if msg is None:
        salon = await _salon(guild)
        if salon is None:
            return None
        msg = await salon.send(view=vue, allowed_mentions=discord.AllowedMentions.none())
        ouverte_le = t
    async with _get_db() as db:
        await db.execute("INSERT INTO vigilance (guild_id, membre_id, message_id, salon_id, ouverte_le, maj_le,"
                         " base_le) VALUES (?,?,?,?,?,?,?) ON CONFLICT(guild_id, membre_id) DO UPDATE SET"
                         " message_id=excluded.message_id, salon_id=excluded.salon_id,"
                         " ouverte_le=excluded.ouverte_le, maj_le=excluded.maj_le",
                         (guild_id, membre_id, msg.id, msg.channel.id, ouverte_le, t, int(base_le or 0)))
        await db.commit()
    return msg


def _guild(guild_id: int):
    return _bot.get_guild(int(guild_id)) if _bot is not None else None


async def gerer(guild_id: int, membre_id: int, par: int, maintenant: float | None = None):
    """« Ça s'enlève une fois qu'on a géré » : la carte part, le compteur repart de zéro.
    Rend (salon_id, message_id) de la carte qui était ouverte, ou None."""
    t = int(maintenant or time.time())
    etat = await _etat(int(guild_id), int(membre_id))
    async with _get_db() as db:
        await db.execute("INSERT INTO vigilance (guild_id, membre_id, base_le, gere_par) VALUES (?,?,?,?)"
                         " ON CONFLICT(guild_id, membre_id) DO UPDATE SET message_id=0, ouverte_le=0,"
                         " base_le=excluded.base_le, gere_par=excluded.gere_par",
                         (int(guild_id), int(membre_id), t, int(par)))
        await db.commit()
    if etat and etat[2] and etat[0]:
        return int(etat[1]), int(etat[0])
    return None


async def ouvertes(guild_id: int) -> list[dict]:
    """Les alertes encore ouvertes (pour le site)."""
    async with _get_db() as db:
        async with db.execute("SELECT membre_id, ouverte_le, maj_le, salon_id, message_id FROM vigilance"
                              " WHERE guild_id=? AND ouverte_le>0 ORDER BY maj_le DESC", (int(guild_id),)) as cur:
            rows = await cur.fetchall()
    return [{"membre_id": r[0], "ouverte_le": r[1], "maj_le": r[2], "salon_id": r[3], "message_id": r[4]}
            for r in rows]


PURGES = [("vigilance", "DELETE FROM vigilance WHERE ouverte_le=0 AND base_le < ?", 30, "unix")]
