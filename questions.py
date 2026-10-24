"""questions.py — les questions posées dans le serveur, et si quelqu'un y a répondu (19/10/2026).

« Un onglet Questions : les questions posées dans les salons, restées sans réponse du staff. »

Seulement les salons publics (lisibles et écrits par @everyone, fils compris) : jamais les
tickets ni les salons du staff. Une question : un message d'un membre (pas du staff) qui contient
« ? » ou commence par un mot interrogatif ; le bavardage (« ça va ? », une réponse à un autre
membre, une mention d'un autre membre) est écarté. Elle devient « répondue » quand le staff lui
répond (réponse, mention de l'auteur, fil ouvert sur elle, message dans les 10 minutes) ou qu'un
membre lui répond directement, « résolue » quand l'auteur dit merci ou que c'est bon, « traitée »
ou « ignorée » depuis le site. Conservée 30 jours.
"""
from __future__ import annotations

import re
import time

import discord

INTERROGATIFS = re.compile(
    r"^(comment|pourquoi|quand|o[uù]|qui|quel(le)?s?|combien|est[- ]ce|c'?est quoi|quoi|peut[- ]on|on peut"
    r"|je peux|puis[- ]je|y a[- ]t[- ]il|il y a|y'?a|sait[- ]on|qqn sait|quelqu'?un sait|how|what|why|when"
    r"|where|who|which|can|could|is there|are there|does|do|should"
    #  24/10/2026 : « il y a plusieurs types de langues… l'international » — espagnol, portugais, allemand, italien.
    r"|d[oó]nde|c[oó]mo|cu[aá]ndo|cu[aá]l|onde|quando|qual|wo|wie|wann|warum|welche[rsn]?|gibt es"
    r"|dove|perch[eé])\b", re.I)
BAVARDAGE = re.compile(
    r"^(ça|ca|sa|cv|tu|t'?es|tes|vous|wsh|slt|salut|yo|hey|re|bjr|bonjour|bonsoir|hello|hi|mdr|ptdr|lol)\b"
    r".{0,25}$|\b(ça va|ca va|tu fais quoi|vous faites quoi|t'?es o[uù]|qui (joue|veut jouer|est co|est l[aà])"
    r"|quelqu'?un (pour|veut) (jouer|voc|vocal)|on joue)\b", re.I)
RESOLU = re.compile(r"\b(merci|thanks|thx|c'?est bon|r[ée]solu|trouv[ée]|[çc]a marche|nickel|parfait)\b", re.I)
MIN_CARACTERES = 15
MIN_MOTS = 3
STAFF_DELAI = 600      # un message du staff dans les 10 minutes suit la question : réponse
FENETRE = 2 * 3600     # au-delà, plus de détection automatique (le site garde la question)
FUSION = 180           # deux questions d'affilée du même membre ne font qu'une
JOURS = 30
STATUTS = {"ouverte": "Sans réponse", "repondue": "Répondue", "resolue": "Résolue",
           "traitee": "Traitée", "ignoree": "Pas une question"}
PURGES = [("questions", "DELETE FROM questions WHERE quand < ?", JOURS, "unix")]
_COLS = ("id", "salon_id", "message_id", "auteur_id", "texte", "quand", "statut", "repondu_par",
         "repondu_le", "par_staff", "lien")
_get_db = None
_est_staff = None
_log = print
_ouvertes: dict = {}
_charges: set = set()


def setup(*, get_db, est_staff, log=None):
    """`est_staff(g, membre, c)` : staff ou au-dessus."""
    global _get_db, _est_staff, _log
    _get_db, _est_staff, _log = get_db, est_staff, log or print
    _ouvertes.clear()
    _charges.clear()


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
            " salon_id INTEGER, message_id INTEGER UNIQUE, auteur_id INTEGER, texte TEXT, quand INTEGER,"
            " statut TEXT DEFAULT 'ouverte', repondu_par INTEGER DEFAULT 0, repondu_le INTEGER DEFAULT 0,"
            " par_staff INTEGER DEFAULT 0, lien TEXT DEFAULT '')")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_questions_guild ON questions(guild_id, statut, quand)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_questions_auteur ON questions(guild_id, auteur_id)")
        await db.commit()


def nettoyer(texte: str) -> str:
    t = re.sub(r"https?://\S+", " ", str(texte or ""))
    t = re.sub(r"<a?:\w+:\d+>|<@[!&]?\d+>|<#\d+>", " ", t)
    t = re.sub(r"[*_`~|>]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def est_question(texte: str) -> bool:
    """FONCTION PURE : une vraie question, pas du bavardage."""
    t = nettoyer(texte)
    if len(t) < MIN_CARACTERES or len(t.split()) < MIN_MOTS or t[0] in "/!.$?":
        return False
    if BAVARDAGE.search(t):
        return False
    return "?" in t or bool(INTERROGATIFS.match(t))


def salon_public(ch) -> bool:
    """Lisible et écrit par @everyone (fils des salons publics compris) — jamais un ticket."""
    g = getattr(ch, "guild", None)
    if g is None:
        return False
    fil = isinstance(ch, discord.Thread)
    base = ch.parent if fil else ch
    if base is None or (fil and ch.is_private()):
        return False
    if getattr(base, "is_nsfw", lambda: False)():
        return False
    p = base.permissions_for(g.default_role)
    return bool(p.view_channel and (p.send_messages_in_threads if fil else p.send_messages))


def _staff(g, membre, c) -> bool:
    if membre is None or getattr(membre, "bot", False) or not hasattr(membre, "roles"):
        return False
    try:
        return bool(_est_staff(g, membre, c))
    except (AttributeError, TypeError, ValueError):
        return False


async def _charger(guild_id: int, salon_id: int, t: float) -> None:
    async with _get_db() as db:
        async with db.execute("SELECT id, message_id, auteur_id, quand, texte FROM questions WHERE guild_id=?"
                              " AND salon_id=? AND statut='ouverte' AND quand>=?",
                              (guild_id, salon_id, int(t - FENETRE))) as cur:
            rows = await cur.fetchall()
    _ouvertes[salon_id] = [{"id": r[0], "message_id": r[1], "auteur_id": r[2], "quand": r[3], "texte": r[4]}
                           for r in rows]
    _charges.add(salon_id)


async def _clore(q: dict, statut: str, par: int, par_staff: bool, lien: str, t: float) -> None:
    async with _get_db() as db:
        await db.execute("UPDATE questions SET statut=?, repondu_par=?, repondu_le=?, par_staff=?, lien=?"
                         " WHERE id=? AND statut='ouverte'", (statut, int(par), int(t), int(par_staff), lien, q["id"]))
        await db.commit()


async def sur_message(msg, c, maintenant: float | None = None) -> str | None:
    """Rend ce qui s'est passé (« question », « reponse », « fusion ») ou None."""
    g, auteur, ch = msg.guild, msg.author, msg.channel
    if g is None or getattr(auteur, "bot", False) or getattr(msg, "webhook_id", None) or _get_db is None:
        return None
    if not salon_public(ch):
        return None
    t = maintenant or time.time()
    staff = _staff(g, auteur, c)
    fil = isinstance(ch, discord.Thread)
    salons = [ch.id] + ([ch.parent_id] if fil and ch.parent_id else [])
    for sid in salons:
        if sid not in _charges:
            await _charger(g.id, sid, t)
        _ouvertes[sid] = [q for q in _ouvertes.get(sid, []) if t - q["quand"] <= FENETRE]
    ref = getattr(getattr(msg, "reference", None), "message_id", None)
    mentions = set(getattr(msg, "raw_mentions", []) or [])
    lien = getattr(msg, "jump_url", "") or ""
    fait = None
    for sid in salons:
        for q in list(_ouvertes[sid]):
            ici = sid == ch.id
            vise = ref == q["message_id"] or (fil and ch.id == q["message_id"]) or q["auteur_id"] in mentions
            if q["auteur_id"] == auteur.id:
                if ici and RESOLU.search(msg.content or "") and ref != q["message_id"]:
                    await _clore(q, "resolue", auteur.id, False, lien, t)
                    _ouvertes[sid].remove(q)
                continue
            if (staff and (vise or (ici and t - q["quand"] <= STAFF_DELAI))) or (not staff and ref == q["message_id"]):
                await _clore(q, "repondue", auteur.id, staff, lien, t)
                _ouvertes[sid].remove(q)
                fait = "reponse"
    if staff or not est_question(msg.content):
        return fait
    resolu = getattr(getattr(msg, "reference", None), "resolved", None)
    cible = getattr(resolu, "author", None)
    if cible is not None and cible.id != auteur.id and not getattr(cible, "bot", False) and not _staff(g, cible, c):
        return fait
    if any(not u.bot and u.id != auteur.id and not _staff(g, u, c) for u in getattr(msg, "mentions", []) or []):
        return fait
    texte = nettoyer(msg.content)[:500]
    prec = next((q for q in reversed(_ouvertes[ch.id]) if q["auteur_id"] == auteur.id and t - q["quand"] <= FUSION),
                None)
    async with _get_db() as db:
        if prec is not None:
            prec["texte"] = f"{prec['texte']} · {texte}"[:500]
            await db.execute("UPDATE questions SET texte=? WHERE id=?", (prec["texte"], prec["id"]))
            await db.commit()
            return "fusion"
        cur = await db.execute("INSERT OR IGNORE INTO questions (guild_id, salon_id, message_id, auteur_id, texte,"
                               " quand) VALUES (?,?,?,?,?,?)", (g.id, ch.id, msg.id, auteur.id, texte, int(t)))
        await db.commit()
        if cur.rowcount:
            _ouvertes[ch.id].append({"id": cur.lastrowid, "message_id": msg.id, "auteur_id": auteur.id,
                                     "quand": int(t), "texte": texte})
    return "question"


async def marquer(guild_id: int, qid: int, statut: str, par: int, maintenant: float | None = None) -> bool:
    if statut not in STATUTS:
        return False
    t = int(maintenant or time.time())
    async with _get_db() as db:
        cur = await db.execute("UPDATE questions SET statut=?, repondu_par=?, repondu_le=? WHERE id=? AND guild_id=?",
                               (statut, int(par), t if statut != "ouverte" else 0, int(qid), int(guild_id)))
        await db.commit()
    for liste in _ouvertes.values():
        for q in list(liste):
            if q["id"] == int(qid):
                liste.remove(q)
    return bool(cur.rowcount)


async def _lignes(sql: str, args: tuple) -> list[dict]:
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            return [dict(zip(_COLS, r)) for r in await cur.fetchall()]


def _lien(guild_id: int, q: dict) -> str:
    return f"https://discord.com/channels/{guild_id}/{q['salon_id']}/{q['message_id']}"


async def lister(guild_id: int, maintenant: float | None = None) -> dict:
    """Pour le site : les 500 dernières questions (30 jours), et leurs chiffres."""
    t = maintenant or time.time()
    rows = await _lignes(f"SELECT {', '.join(_COLS)} FROM questions WHERE guild_id=? AND quand>=?"
                         " ORDER BY quand DESC LIMIT 500", (int(guild_id), int(t - JOURS * 86400)))
    for q in rows:
        q["message"] = _lien(guild_id, q)
    repondues_7 = [q for q in rows if q["statut"] != "ouverte" and q["repondu_le"] and t - q["repondu_le"] <= 7 * 86400]
    delais = sorted(q["repondu_le"] - q["quand"] for q in rows if q["par_staff"] and q["repondu_le"] >= q["quand"])
    salons: dict = {}
    for q in rows:
        salons[q["salon_id"]] = salons.get(q["salon_id"], 0) + 1
    return {"liste": rows,
            "stats": {"ouvertes": sum(q["statut"] == "ouverte" for q in rows),
                      "repondues_7": len(repondues_7),
                      "delai_median": delais[len(delais) // 2] if delais else 0,
                      "salons": sorted(salons.items(), key=lambda kv: -kv[1])[:6]}}


async def du_membre(guild_id: int, membre_id: int) -> list[dict]:
    rows = await _lignes(f"SELECT {', '.join(_COLS)} FROM questions WHERE guild_id=? AND auteur_id=?"
                         " ORDER BY quand DESC LIMIT 200", (int(guild_id), int(membre_id)))
    for q in rows:
        q["message"] = _lien(guild_id, q)
    return rows
