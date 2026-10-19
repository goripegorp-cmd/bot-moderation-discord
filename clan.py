"""clan.py — le clan Rell Seas géré depuis le site (19/10/2026).

« La direction et le fondateur peuvent ajouter le rôle RILSI… filtrer tout le serveur ou rechercher
une personne en particulier et l'ajouter… soit via le panel, soit via la commande… Envoyer ou ping
celles et ceux qui ne sont plus présents… dans un salon spécifique… ou un message en privé : attention,
vous êtes inactif, vous allez être expulsé du clan d'ici une semaine. Et si ça n'a pas été résolu,
le site va nous rappeler que la semaine est écoulée… et proposer la sanction : retirer le rôle. »

Ici : les rappels d'inactivité (envoyés, échus, résolus) et la recherche dans tout le serveur. Les
gestes sur Discord (rôle, message privé, ping) sont faits par bot.py.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import activite_calendrier as cal

DELAI = 7 * 86400
MAX_LOT = 25
GARDE_JOURS = 90
STATUTS = ("en_attente", "revenu", "retire", "annule")
PURGES = [("rappels du clan", "DELETE FROM clan_rappels WHERE envoye_le < ?", GARDE_JOURS, "unix")]
_get_db = None
_log = print


def setup(*, get_db, log=None):
    global _get_db, _log
    _get_db, _log = get_db, log or print


async def init_db():
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS clan_rappels (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                         " membre_id INTEGER, envoye_le INTEGER, echeance INTEGER, par INTEGER, mode TEXT, salon_id INTEGER"
                         " DEFAULT 0, remis INTEGER DEFAULT 1, statut TEXT DEFAULT 'en_attente', resolu_le INTEGER DEFAULT 0,"
                         " resolu_par INTEGER DEFAULT 0)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_clan_rappels ON clan_rappels(guild_id, membre_id, statut)")
        await db.commit()


def texte_mp(serveur: str, role: str, echeance: int) -> str:
    """Le message privé, aux mots du fondateur."""
    return (f"### ⚠️ Inactivité dans le clan {role}\n"
            f"Attention, vous êtes inactif : vous allez être expulsé du clan d'ici une semaine, le <t:{echeance}:D>.\n"
            f"-# Un message, un vocal ou une réaction sur {serveur} avant cette date suffit pour rester.")


def texte_salon(mentions: list[str], role: str, echeance: int) -> str:
    seul = len(mentions) == 1
    return (" ".join(mentions) + f"\n⚠️ Attention, {'tu es inactif' if seul else 'vous êtes inactifs'} dans le clan "
            f"{role} : sans activité d'ici une semaine, le <t:{echeance}:D>, "
            f"{'tu seras expulsé' if seul else 'vous serez expulsés'} du clan.")


async def prevenir(guild_id: int, membres: list[int], par: int, mode: str, salon_id: int = 0,
                   remis: dict | None = None, maintenant: float | None = None) -> int:
    """Un rappel par membre ; un nouveau rappel remplace celui en attente (nouvelle échéance)."""
    t = int(maintenant or time.time())
    remis = remis or {}
    async with _get_db() as db:
        for uid in membres:
            await db.execute("UPDATE clan_rappels SET statut='annule', resolu_le=?, resolu_par=? WHERE guild_id=?"
                             " AND membre_id=? AND statut='en_attente'", (t, int(par), guild_id, int(uid)))
            await db.execute("INSERT INTO clan_rappels (guild_id, membre_id, envoye_le, echeance, par, mode, salon_id, remis)"
                             " VALUES (?,?,?,?,?,?,?,?)", (guild_id, int(uid), t, t + DELAI, int(par), mode,
                                                           int(salon_id or 0), int(bool(remis.get(uid, True)))))
        await db.commit()
    return t + DELAI


async def clore(guild_id: int, membre_id: int, statut: str, par: int = 0, maintenant: float | None = None) -> bool:
    if statut not in STATUTS[1:]:
        raise ValueError(statut)
    async with _get_db() as db:
        cur = await db.execute("UPDATE clan_rappels SET statut=?, resolu_le=?, resolu_par=? WHERE guild_id=? AND"
                               " membre_id=? AND statut='en_attente'",
                               (statut, int(maintenant or time.time()), int(par), guild_id, int(membre_id)))
        await db.commit()
        return bool(cur.rowcount)


async def rappels(guild_id: int, derniers: dict | None = None, dans_le_clan: set | None = None,
                  maintenant: float | None = None) -> dict:
    """Le dernier rappel de chaque membre (30 jours). Avant de répondre, le rappel d'un membre
    revenu (actif le jour du rappel ou après) se ferme seul, celui d'un membre sorti du clan aussi.
    `derniers` : {membre: dernier jour actif 'AAAA-MM-JJ'}."""
    t = maintenant or time.time()
    derniers = derniers or {}
    async with _get_db() as db:
        async with db.execute("SELECT id, membre_id, envoye_le, echeance, par, mode, salon_id, remis, statut, resolu_le,"
                              " resolu_par FROM clan_rappels WHERE guild_id=? AND envoye_le>=? ORDER BY id",
                              (guild_id, int(t) - 30 * 86400)) as cur:
            lignes = await cur.fetchall()
        out = {}
        for rid, uid, envoye, echeance, par, mode, salon, remis, statut, resolu_le, resolu_par in lignes:
            if statut == "en_attente":
                vu = derniers.get(uid)
                if vu and vu >= cal.jour(datetime.fromtimestamp(envoye, timezone.utc)):
                    statut, resolu_le = "revenu", int(t)
                elif dans_le_clan is not None and uid not in dans_le_clan:
                    statut, resolu_le = "retire", int(t)
                if statut != "en_attente":
                    await db.execute("UPDATE clan_rappels SET statut=?, resolu_le=? WHERE id=?", (statut, resolu_le, rid))
            if statut == "annule":
                out.pop(uid, None)
                continue
            out[uid] = {"envoye_le": envoye, "echeance": echeance, "par": par, "mode": mode, "salon": salon,
                        "remis": bool(remis), "statut": "echu" if statut == "en_attente" and echeance <= t else statut,
                        "resolu_le": resolu_le or None, "resolu_par": resolu_par}
        await db.commit()
    return out


def chercher(membres, requete: str, dans_le_clan: set, limite: int = 30) -> list:
    """« Filtrer tout le serveur ou rechercher une personne en particulier » : nom, pseudo ou
    identifiant ; sans requête, les arrivées les plus récentes. Jamais les bots."""
    q = (requete or "").strip().casefold()
    trouves = []
    for m in membres:
        if getattr(m, "bot", False):
            continue
        if q and not (q in str(m.id) or q in (m.display_name or "").casefold() or q in (m.name or "").casefold()):
            continue
        trouves.append(m)
    debut = (lambda m: not (m.display_name or "").casefold().startswith(q)) if q else (lambda m: 0)
    arrivee = lambda m: -(m.joined_at.timestamp() if getattr(m, "joined_at", None) else 0)
    trouves.sort(key=lambda m: (m.id in dans_le_clan, debut(m), arrivee(m)))
    return trouves[:limite]
