"""cadeaux.py — les cadeaux (giveaways) du serveur (22/10/2026, nuit).

Demandé par le fondateur : « un salon unique… tu me le crées, après, moi, je le place où je veux. C'est
pour les cadeaux… où je peux mettre vraiment des conditions. Quel rôle peut y participer ? … combien de
messages faut qu'ils envoient… combien de temps… au moment de la création du cadeau… ils voient les
statistiques monter individuellement… à chaque cadeau, ça se réinitialise… ça nettoie toutes les données…
soit en et, soit en ou… un pourcentage de luck… je mets le rôle… un multiplicateur, je pourrais définir le
multiplicateur… Par exemple, ceux qui offrent le nitro. »

- Le salon 🎁giveaways est créé une fois, sans catégorie : le fondateur le range où il veut, le bot le suit
  par son identifiant et ne le déplace jamais.
- « 🎁 Cadeaux » (📋logs, le fondateur et la direction) : le lot, la durée, le nombre de gagnants, l'image ;
  qui peut participer (rôles) ; les conditions — messages et/ou minutes en vocal, ET ou OU ; les rôles
  chanceux et leur multiplicateur (les boosters, ×2, proposés d'office). L'aperçu exact, puis Lancer.
- Les compteurs partent du lancement, un jeu par cadeau. Un message compte s'il a 2 caractères ou plus,
  un toutes les 3 s au plus, et ne compte plus s'il est supprimé dans les 10 minutes (la modération). Le
  vocal compte hors salon AFK, casque non coupé. « 📊 Mes stats » montre sa progression en direct.
- Le tirage : parmi les inscrits qui ont encore le rôle demandé et remplissent les conditions, au hasard
  pondéré (×2 = deux fois plus de chances). Puis les compteurs et la liste des inscrits sont effacés ;
  seul le résultat reste, pour un nouveau tirage.
"""
from __future__ import annotations

import asyncio
import io
import json
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import discord
from discord.ui import Button

import visuels
from ui_v2 import LayoutView, Palette

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python sans zoneinfo
    ZoneInfo = None

NOM_SALON = "🎁giveaways"
SUJET_SALON = ("🇫🇷 Les cadeaux du serveur : « Participer », puis « Mes stats » pour voir où tu en es.\n"
               "🇬🇧 Server giveaways: “Enter”, then “My stats” to follow your progress.")
COULEUR = 0xEC4899
LOT_MAX, DETAILS_MAX = 100, 1000
GAGNANTS_MAX = 20
DUREE_MIN_S, DUREE_MAX_S = 60, 60 * 86400
MULT_MIN, MULT_MAX = 1.1, 10.0
ROLES_MAX = 5
ECART_MSG_S = 3.0          # un message compte toutes les 3 s au plus (pas de spam)
TEXTE_MIN = 2              # « a », « . » ne comptent pas
EFFACE_S = 600.0           # supprimé dans les 10 minutes (la modération) : il ne compte plus
MAJ_CARTE_S = 15.0         # le nombre d'inscrits sur la carte : réécrit au plus toutes les 15 s
GARDER_RESULTAT_S = 7 * 86400   # la liste des gagnables reste 7 jours (un nouveau tirage), puis part
IMAGE_MAX = 8 * 1024 * 1024
TYPES_IMAGE = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
TZ = "Europe/Paris"
MOTS_DUREE = (("semaines", "sem"), ("semaine", "sem"), ("weeks", "w"), ("week", "w"), ("jours", "j"),
              ("jour", "j"), ("days", "d"), ("day", "d"), ("heures", "h"), ("heure", "h"), ("hours", "h"),
              ("hour", "h"), ("minutes", "min"), ("minute", "min"), ("mins", "min"))
UNITES = {"sem": 604800, "w": 604800, "j": 86400, "d": 86400, "h": 3600, "min": 60, "m": 60}

TEXTES = {
    "introuvable": {"fr": "Ce cadeau n'existe plus.", "en": "This giveaway no longer exists."},
    "fini": {"fr": "Ce cadeau est terminé.", "en": "This giveaway has ended."},
    "reserve": {"fr": "🔒 Ce cadeau est réservé à {roles}.", "en": "🔒 This giveaway is for {roles} only."},
    "exclu": {"fr": "🚫 Ce cadeau n'est pas ouvert à {roles}.", "en": "🚫 This giveaway isn't open to {roles}."},
    "inscrit": {"fr": "🎉 **Tu participes !** Voici où tu en es :", "en": "🎉 **You're in!** Here's your progress:"},
    "quitte": {"fr": "Tu ne participes plus à ce cadeau.", "en": "You left this giveaway."},
    "tes_stats": {"fr": "tes stats", "en": "your stats"},
    "vocal": {"fr": "Vocal", "en": "Voice"},
    "les_deux": {"fr": "Il faut les deux.", "en": "Both are needed."},
    "l_un": {"fr": "L'un ou l'autre suffit.", "en": "One of the two is enough."},
    "tout": {"fr": "Il faut tout.", "en": "All are needed."},
    "une": {"fr": "Une seule suffit.", "en": "One is enough."},
    "regle_inv": {"fr": "Invitations : les personnes arrivées par tes liens et toujours là — pas les comptes de "
                         "moins de 7 jours, pas ceux qui sont partis.",
                  "en": "Invites: people who joined through your links and are still here — no accounts under 7 "
                        "days, none who left."},
    "rempli": {"fr": "✅ **Conditions remplies**", "en": "✅ **Conditions met**"},
    "pas_encore": {"fr": "⏳ **Pas encore** : continue !", "en": "⏳ **Not yet**: keep going!"},
    "sans": {"fr": "✅ Aucune condition : il suffit de participer.", "en": "✅ No condition: just enter."},
    "chance": {"fr": "🍀 Ta chance : ×{mult}", "en": "🍀 Your odds: ×{mult}"},
    "est_inscrit": {"fr": "🎟️ Inscrit ✅", "en": "🎟️ Entered ✅"},
    "pas_inscrit": {"fr": "🎟️ Pas encore inscrit : clique « Participer ».",
                    "en": "🎟️ Not entered yet: click “Enter”."},
    "tirage": {"fr": "⏳ Tirage", "en": "⏳ Draw"},
    "regles": {"fr": "Comptés depuis le lancement : un message de 2 caractères ou plus, un toutes les 3 s au "
                     "plus ; le vocal hors AFK, casque non coupé.",
               "en": "Counted since the launch: a message of 2+ characters, one every 3 s at most; voice "
                     "outside AFK, not deafened."},
    "manque": {"fr": "⛔ **Pas encore** : il te faut d'abord ceci. Reclique « Participer » quand c'est bon.",
               "en": "⛔ **Not yet**: you need this first. Click “Enter” again once it's done."},
    "pas_inscrit_cond": {"fr": "🎟️ Pas encore inscrit : remplis les conditions, puis clique « Participer ».",
                         "en": "🎟️ Not entered yet: meet the conditions, then click “Enter”."},
    "pas_encore_autre": {"fr": "⏳ **Pas encore**", "en": "⏳ **Not yet**"},
    "retiree": {"fr": "⚠️ **Ta participation a été retirée** : remplis d'abord les conditions, puis reclique "
                      "« Participer ».",
                "en": "⚠️ **Your entry was removed**: meet the conditions first, then click “Enter” again."},
    "participer": {"fr": "Participer", "en": "Enter"},
    "actualiser": {"fr": "Actualiser", "en": "Refresh"},
    "quitter": {"fr": "Ne plus participer", "en": "Leave"},
}


def tr(cle: str, langue: str = "fr", **kw) -> str:
    e = TEXTES.get(cle) or {}
    texte = e.get(langue) or e.get("fr") or cle
    return texte.format(**kw) if kw else texte


_get_db = _cfg = _db_set = _autorise = _journal = _ticket = _langue = None
_inv_un = _inv_tous = _inv_relever = None
_log = print
_mono = time.monotonic    # les horloges, remplaçables dans les tests
_mur = time.time

#  Les compteurs, en mémoire entre deux passages en base (toutes les 30 s).
_actifs: dict = {}                                # guild_id → {cadeau_id: début (_mur())}
_tampon: dict = defaultdict(lambda: [0, 0.0])     # (cadeau_id, membre_id) → [messages, secondes]
_dernier_msg: dict = {}                           # (guild_id, membre_id) → _mono()
_comptes: dict = {}                               # message_id → (guild_id, membre_id, (cadeau_id…), monotonic)
_vocal: dict = {}                                 # (guild_id, membre_id) → _mur() du début du segment
_charges: set = set()                             # les serveurs dont les cadeaux actifs sont en mémoire
_maj_prevues: dict = {}
_verrous: dict = {}
_minuteurs: dict = {}                             # cadeau_id → la tâche qui tire à la seconde près
MINUTEUR_S = 40.0     # à moins de 40 s de la fin, un minuteur exact prend le relais de la boucle (30 s)
AVIS_S = 180.0        # un mot pour soi (refus, participation retirée) s'efface après 3 minutes
ANNONCE_S = 86400     # l'annonce des gagnants s'efface au bout de 24 h : la carte, elle, les garde


def setup(*, get_db, cfg, db_set, autorise, journal, ticket=None, langue=None, log=None, invitations=None,
          invitations_tous=None, relever=None):
    """`invitations(guild_id, membre_id)` / `invitations_tous(guild_id)` (async) : le total des personnes venues
    par les liens d'un membre ; `relever(g)` (async) : un relevé frais des liens (avant un tirage)."""
    global _inv_un, _inv_tous, _inv_relever
    _inv_un, _inv_tous, _inv_relever = invitations, invitations_tous, relever
    _setup(get_db=get_db, cfg=cfg, db_set=db_set, autorise=autorise, journal=journal, ticket=ticket, langue=langue,
           log=log)


def _setup(*, get_db, cfg, db_set, autorise, journal, ticket=None, langue=None, log=None):
    """`autorise(g, membre)` (async) → le fondateur ou la direction ; `journal(g, type_, texte, **kw)`
    (async) ; `ticket(g)` → le salon des tickets (récupérer son lot) ; `langue(i)` (async) → fr | en."""
    global _get_db, _cfg, _db_set, _autorise, _journal, _ticket, _langue, _log
    _get_db, _cfg, _db_set, _autorise, _journal = get_db, cfg, db_set, autorise, journal
    _ticket, _langue = ticket, langue
    _log = log or print


def _verrou(cle):
    return _verrous.setdefault(cle, asyncio.Lock())


async def langue_de(i) -> str:
    try:
        if _langue is not None:
            return "en" if await _langue(i) == "en" else "fr"
        loc = str(getattr(getattr(i, "locale", None), "value", getattr(i, "locale", "")) or "")
        return "fr" if loc.lower().startswith("fr") else "en"
    except Exception as ex:
        _log(f"[CADEAUX:DETAIL] langue {type(ex).__name__} {ex}")
        return "fr"


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "salon_id", "message_id", "auteur_id", "lot", "details", "image", "gagnants",
             "debut", "fin", "roles", "msg_min", "voc_min", "logique", "chance_roles", "multiplicateur",
             "mention", "statut", "resultat", "roles_exclus", "inv_min", "anc_min")
_SQL_UN = ("SELECT id, guild_id, salon_id, message_id, auteur_id, lot, details, image, gagnants, debut, fin,"
           " roles, msg_min, voc_min, logique, chance_roles, multiplicateur, mention, statut, resultat, roles_exclus,"
           " inv_min, anc_min FROM cadeaux WHERE id=?")
_SQL_ACTIFS = ("SELECT id, debut FROM cadeaux WHERE guild_id=? AND statut='actif' ORDER BY id")
_SQL_RECENTS = ("SELECT id, guild_id, salon_id, message_id, auteur_id, lot, details, image, gagnants, debut, fin,"
                " roles, msg_min, voc_min, logique, chance_roles, multiplicateur, mention, statut, resultat,"
                " roles_exclus, inv_min, anc_min FROM cadeaux WHERE guild_id=? ORDER BY id DESC LIMIT ?")
_SQL_VIDER = ("INSERT INTO cadeaux_stats(cadeau_id, membre_id, messages, vocal_s) VALUES(?,?,?,?)"
              " ON CONFLICT(cadeau_id, membre_id) DO UPDATE SET messages=MAX(0, messages+excluded.messages),"
              " vocal_s=vocal_s+excluded.vocal_s")


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS cadeaux (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
            " salon_id INTEGER NOT NULL, message_id INTEGER NOT NULL DEFAULT 0, auteur_id INTEGER NOT NULL,"
            " lot TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',"
            " gagnants INTEGER NOT NULL DEFAULT 1, debut INTEGER NOT NULL, fin INTEGER NOT NULL,"
            " roles TEXT NOT NULL DEFAULT '[]', msg_min INTEGER NOT NULL DEFAULT 0, voc_min INTEGER NOT NULL DEFAULT 0,"
            " logique TEXT NOT NULL DEFAULT 'et', chance_roles TEXT NOT NULL DEFAULT '[]',"
            " multiplicateur REAL NOT NULL DEFAULT 1, mention TEXT NOT NULL DEFAULT '',"
            " statut TEXT NOT NULL DEFAULT 'actif', resultat TEXT NOT NULL DEFAULT '{}',"
            " roles_exclus TEXT NOT NULL DEFAULT '[]')")
        async with db.execute("PRAGMA table_info(cadeaux)") as cur:
            colonnes = {r[1] for r in await cur.fetchall()}
        if "roles_exclus" not in colonnes:  # la table du 24/10 au matin
            await db.execute("ALTER TABLE cadeaux ADD COLUMN roles_exclus TEXT NOT NULL DEFAULT '[]'")
        if "inv_min" not in colonnes:  # 24/10 au soir : les invitations
            await db.execute("ALTER TABLE cadeaux ADD COLUMN inv_min INTEGER NOT NULL DEFAULT 0")
        if "anc_min" not in colonnes:  # 24/10 au soir : l'ancienneté sur le serveur (jours)
            await db.execute("ALTER TABLE cadeaux ADD COLUMN anc_min INTEGER NOT NULL DEFAULT 0")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS cadeaux_inscrits (cadeau_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " quand INTEGER NOT NULL, PRIMARY KEY (cadeau_id, membre_id))")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS cadeaux_stats (cadeau_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " messages INTEGER NOT NULL DEFAULT 0, vocal_s INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY (cadeau_id, membre_id))")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS cadeaux_retires (cadeau_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " quand INTEGER NOT NULL, PRIMARY KEY (cadeau_id, membre_id))")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS cadeaux_messages (message_id INTEGER PRIMARY KEY, salon_id INTEGER NOT NULL,"
            " effacer_a INTEGER NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_cadeaux_guild ON cadeaux(guild_id, statut)")
        await db.commit()


def _ligne(r) -> dict:
    c = dict(zip(_COLONNES, r))
    for cle, defaut in (("roles", []), ("chance_roles", []), ("resultat", {}), ("roles_exclus", [])):
        try:
            c[cle] = json.loads(c[cle] or json.dumps(defaut))
        except (TypeError, ValueError):
            c[cle] = defaut
    c["roles"] = [int(x) for x in c["roles"]]
    c["chance_roles"] = [int(x) for x in c["chance_roles"]]
    c["roles_exclus"] = [int(x) for x in c["roles_exclus"]]
    c["multiplicateur"] = float(c["multiplicateur"] or 1)
    c["inv_min"] = int(c.get("inv_min") or 0)
    c["anc_min"] = int(c.get("anc_min") or 0)
    return c


async def charger(cid: int):
    async with _get_db() as db:
        async with db.execute(_SQL_UN, (int(cid),)) as cur:
            r = await cur.fetchone()
    return _ligne(r) if r else None


async def recents(guild_id: int, limite: int = 10) -> list:
    async with _get_db() as db:
        async with db.execute(_SQL_RECENTS, (int(guild_id), int(limite))) as cur:
            return [_ligne(r) for r in await cur.fetchall()]


async def _ecrire(sql: str, args: tuple) -> int:
    async with _get_db() as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.lastrowid


async def inscrits(cid: int) -> list:
    async with _get_db() as db:
        async with db.execute("SELECT membre_id FROM cadeaux_inscrits WHERE cadeau_id=? ORDER BY quand",
                              (int(cid),)) as cur:
            return [int(r[0]) for r in await cur.fetchall()]


async def inscrits_quand(cid: int) -> list:
    """[(membre, heure d'inscription)], dans l'ordre d'inscription."""
    async with _get_db() as db:
        async with db.execute("SELECT membre_id, quand FROM cadeaux_inscrits WHERE cadeau_id=? "
                              "ORDER BY quand, membre_id", (int(cid),)) as cur:
            return [(int(u), int(q or 0)) for u, q in await cur.fetchall()]


async def _retirer_inscriptions(cid: int, uids: list) -> int:
    """Retire ces membres d'un cadeau, en une écriture. Rend le nombre retiré."""
    if not uids:
        return 0
    async with _get_db() as db:
        n = 0
        for uid in uids:
            cur = await db.execute("DELETE FROM cadeaux_inscrits WHERE cadeau_id=? AND membre_id=?",
                                   (int(cid), int(uid)))
            n += max(0, cur.rowcount or 0)
        await db.commit()
    return n


async def _noter_retires(cid: int, uids: list) -> None:
    """Ceux dont la participation est retirée : ils le liront en cliquant, pour eux seuls."""
    if not uids:
        return
    async with _get_db() as db:
        await db.executemany("INSERT OR REPLACE INTO cadeaux_retires(cadeau_id, membre_id, quand) VALUES(?,?,?)",
                             [(int(cid), int(u), int(_mur())) for u in uids])
        await db.commit()


async def _vu_retire(cid: int, uid: int) -> bool:
    """Ce membre a-t-il été retiré de ce cadeau ? Il le lit une fois : la note part."""
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM cadeaux_retires WHERE cadeau_id=? AND membre_id=?", (int(cid), int(uid)))
        await db.commit()
        return (cur.rowcount or 0) > 0


async def nb_inscrits(cid: int) -> int:
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM cadeaux_inscrits WHERE cadeau_id=?", (int(cid),)) as cur:
            return int((await cur.fetchone())[0])


async def est_inscrit(cid: int, uid: int) -> bool:
    async with _get_db() as db:
        async with db.execute("SELECT 1 FROM cadeaux_inscrits WHERE cadeau_id=? AND membre_id=?",
                              (int(cid), int(uid))) as cur:
            return await cur.fetchone() is not None


async def _stats_en_base(cid: int) -> dict:
    async with _get_db() as db:
        async with db.execute("SELECT membre_id, messages, vocal_s FROM cadeaux_stats WHERE cadeau_id=?",
                              (int(cid),)) as cur:
            return {int(u): (int(m), float(s)) for u, m, s in await cur.fetchall()}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les compteurs : messages et vocal, depuis le lancement de chaque cadeau
# ═══════════════════════════════════════════════════════════════════════════════

def nb_actifs() -> int:
    return sum(len(d) for d in _actifs.values())


def sur_message(message) -> bool:
    """Un message du serveur : il compte pour chaque cadeau en cours (rien de lourd ici : c'est appelé
    pour chaque message). Rend True s'il a compté."""
    g = getattr(message, "guild", None)
    actifs = _actifs.get(getattr(g, "id", 0))
    auteur = getattr(message, "author", None)
    if not actifs or auteur is None or getattr(auteur, "bot", False) or getattr(message, "webhook_id", None):
        return False
    if getattr(message, "type", discord.MessageType.default) not in (discord.MessageType.default,
                                                                      discord.MessageType.reply):
        return False
    texte = (getattr(message, "content", "") or "").strip()
    if len(texte) < TEXTE_MIN and not (getattr(message, "attachments", None) or getattr(message, "stickers", None)):
        return False
    t = _mono()
    cle = (g.id, auteur.id)
    if t - _dernier_msg.get(cle, -1e9) < ECART_MSG_S:
        return False
    _dernier_msg[cle] = t
    cids = tuple(actifs)
    for cid in cids:
        _tampon[(cid, auteur.id)][0] += 1
    _comptes[message.id] = (g.id, auteur.id, cids, t)
    if len(_comptes) > 5000:
        _elaguer(t)
    return True


def sur_suppression(message_id: int) -> bool:
    """Un message supprimé dans les 10 minutes (la modération, un regret) ne compte plus."""
    x = _comptes.pop(int(message_id), None)
    if x is None or _mono() - x[3] > EFFACE_S:
        return False
    _gid, uid, cids, _t = x
    for cid in cids:
        _tampon[(cid, uid)][0] -= 1
    return True


def _elaguer(maintenant: float) -> None:
    for mid in [m for m, x in _comptes.items() if maintenant - x[3] > EFFACE_S]:
        _comptes.pop(mid, None)
    for cle in [k for k, t in _dernier_msg.items() if maintenant - t > 60]:
        _dernier_msg.pop(cle, None)


def compte_en_vocal(g, etat) -> bool:
    """Dans un salon vocal, hors salon AFK, casque non coupé."""
    ch = getattr(etat, "channel", None)
    if ch is None:
        return False
    afk = getattr(g, "afk_channel", None)
    if afk is not None and ch.id == afk.id:
        return False
    return not (getattr(etat, "self_deaf", False) or getattr(etat, "deaf", False))


def _crediter(gid: int, uid: int, depuis: float, jusqu_a: float) -> None:
    for cid, debut in (_actifs.get(gid) or {}).items():
        s = jusqu_a - max(depuis, debut)
        if s > 0:
            _tampon[(cid, uid)][1] += s


def sur_vocal(membre, avant, apres) -> None:
    """Le segment vocal en cours se crédite ; un nouveau commence s'il compte."""
    g = getattr(membre, "guild", None)
    if g is None or getattr(membre, "bot", False):
        return
    cle = (g.id, membre.id)
    maintenant = _mur()
    if cle in _vocal:
        _crediter(g.id, membre.id, _vocal.pop(cle), maintenant)
    if _actifs.get(g.id) and compte_en_vocal(g, apres):
        _vocal[cle] = maintenant


def _demarrer_vocaux(g) -> int:
    """Ceux qui sont déjà en vocal au lancement (ou au redémarrage) comptent à partir de maintenant."""
    n = 0
    maintenant = _mur()
    salons = list(getattr(g, "voice_channels", []) or []) + list(getattr(g, "stage_channels", []) or [])
    for ch in salons:
        for m in getattr(ch, "members", []) or []:
            if not getattr(m, "bot", False) and compte_en_vocal(g, getattr(m, "voice", None)):
                if (g.id, m.id) not in _vocal:
                    _vocal[(g.id, m.id)] = maintenant
                    n += 1
    return n


async def vider() -> int:
    """Les compteurs en mémoire vont en base ; les segments vocaux en cours sont crédités jusqu'à
    maintenant (les stats montent en direct). Rend le nombre de lignes écrites."""
    maintenant = _mur()
    for (gid, uid), depuis in list(_vocal.items()):
        _crediter(gid, uid, depuis, maintenant)
        _vocal[(gid, uid)] = maintenant
    actifs = {cid for d in _actifs.values() for cid in d}
    lignes = []
    for cle in list(_tampon):
        cid, uid = cle
        m, s = _tampon.pop(cle)
        if cid not in actifs:
            continue
        entier = int(s)
        if s - entier > 0:
            _tampon[cle][1] += s - entier   # la fraction de seconde attend le prochain passage
        if m or entier:
            lignes.append((cid, uid, m, entier))
    if lignes:
        try:
            async with _get_db() as db:
                await db.executemany(_SQL_VIDER, lignes)
                await db.commit()
        except Exception as ex:
            _log("[CADEAUX][E1] compteurs non enregistrés")
            _log(f"[CADEAUX][E1:DETAIL] {len(lignes)} ligne(s) {type(ex).__name__} {ex}")
            for cid, uid, m, s in lignes:  # rien n'est perdu : ils repartent au prochain passage
                _tampon[(cid, uid)][0] += m
                _tampon[(cid, uid)][1] += s
            return 0
    return len(lignes)


async def stats(cid: int, uid: int) -> tuple:
    """(messages, secondes en vocal) d'un membre pour un cadeau, à l'instant : la base, ce qui attend en
    mémoire et le segment vocal en cours."""
    async with _get_db() as db:
        async with db.execute("SELECT messages, vocal_s FROM cadeaux_stats WHERE cadeau_id=? AND membre_id=?",
                              (int(cid), int(uid))) as cur:
            r = await cur.fetchone()
    m, s = (int(r[0]), float(r[1])) if r else (0, 0.0)
    t = _tampon.get((int(cid), int(uid)))
    if t:
        m, s = m + t[0], s + t[1]
    maintenant = _mur()
    for (gid, u), depuis in _vocal.items():
        debut = (_actifs.get(gid) or {}).get(int(cid))
        if u == int(uid) and debut is not None:
            s += max(0.0, maintenant - max(depuis, debut))
    return max(0, m), s


async def stats_de_tous(cid: int) -> dict:
    """{membre: (messages, secondes en vocal)} pour tout un cadeau, d'une seule lecture : la base, ce qui
    attend en mémoire et les segments vocaux en cours (comme `stats`, pour toute la liste)."""
    tous = await _stats_en_base(cid)
    for (c_, uid), (m, s) in list(_tampon.items()):
        if c_ == int(cid):
            m0, s0 = tous.get(uid, (0, 0.0))
            tous[uid] = (m0 + m, s0 + s)
    maintenant = _mur()
    for (gid, uid), depuis in list(_vocal.items()):
        debut = (_actifs.get(gid) or {}).get(int(cid))
        if debut is not None:
            m0, s0 = tous.get(uid, (0, 0.0))
            tous[uid] = (m0, s0 + max(0.0, maintenant - max(depuis, debut)))
    return {u: (max(0, m), s) for u, (m, s) in tous.items()}


async def charger_actifs(g) -> int:
    """Au démarrage : les cadeaux en cours reviennent en mémoire, les membres en vocal recommencent à compter."""
    async with _get_db() as db:
        async with db.execute(_SQL_ACTIFS, (g.id,)) as cur:
            lignes = await cur.fetchall()
    _actifs[g.id] = {int(cid): float(debut) for cid, debut in lignes}
    if not _actifs[g.id]:
        _actifs.pop(g.id, None)
    else:
        _demarrer_vocaux(g)
    _charges.add(g.id)
    return len(lignes)


def _oublier(gid: int, cid: int) -> None:
    t = _minuteurs.pop(int(cid), None)
    if t is not None and t is not asyncio.current_task():
        t.cancel()
    d = _actifs.get(gid) or {}
    d.pop(int(cid), None)
    for cle in [k for k in _tampon if k[0] == int(cid)]:
        _tampon.pop(cle, None)
    if not d:
        _actifs.pop(gid, None)
        for cle in [k for k in _vocal if k[0] == gid]:
            _vocal.pop(cle, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Les règles : qui peut participer, qui remplit les conditions, qui a plus de chances
# ═══════════════════════════════════════════════════════════════════════════════

def nb_conditions(c: dict) -> int:
    return sum(1 for cle in ("msg_min", "voc_min", "inv_min", "anc_min") if int(c.get(cle) or 0) > 0)


def jours_sur_serveur(membre) -> float:
    """Depuis combien de jours ce membre est sur le serveur (0 si on ne sait pas)."""
    arrive = getattr(membre, "joined_at", None)
    if arrive is None:
        return 0.0
    return max(0.0, (_mur() - arrive.timestamp()) / 86400)


async def invitations_de(c: dict, uid: int) -> int:
    """Le total des invitations d'un membre — lu seulement si le cadeau en demande."""
    if not c.get("inv_min") or _inv_un is None:
        return 0
    return int(await _inv_un(c["guild_id"], uid))


async def invitations_tous(c: dict) -> dict:
    if not c.get("inv_min") or _inv_tous is None:
        return {}
    return await _inv_tous(c["guild_id"])


def remplit(c: dict, messages: int, secondes: float, invitations: int = 0, membre=None) -> bool:
    besoins = []
    if c["msg_min"] > 0:
        besoins.append(messages >= c["msg_min"])
    if c["voc_min"] > 0:
        besoins.append(secondes >= c["voc_min"] * 60)
    if c.get("inv_min", 0) > 0:
        besoins.append(invitations >= c["inv_min"])
    if c.get("anc_min", 0) > 0:
        besoins.append(jours_sur_serveur(membre) >= c["anc_min"])
    if not besoins:
        return True
    return all(besoins) if c["logique"] == "et" else any(besoins)


def _ids_roles(membre) -> set:
    return {r.id for r in getattr(membre, "roles", []) or []}


def exclu(c: dict, membre) -> bool:
    """« Ceux qui peuvent pas » : un rôle de la liste noire suffit à exclure."""
    return bool(_ids_roles(membre) & set(c.get("roles_exclus") or []))


def peut_participer(c: dict, membre) -> bool:
    """« Ceux qui peuvent » : sans liste blanche, tout le monde ; jamais un rôle de la liste noire."""
    return not exclu(c, membre) and (not c["roles"] or bool(_ids_roles(membre) & set(c["roles"])))


def chance(c: dict, membre) -> float:
    return c["multiplicateur"] if _ids_roles(membre) & set(c["chance_roles"]) else 1.0


def tirer(eligibles: list, n: int, hasard=None) -> list:
    """Au hasard pondéré, sans remise (Efraimidis–Spirakis) : à chaque place, un poids ×2 a deux fois plus
    de chances. `eligibles` = [(membre_id, poids)]."""
    hasard = hasard or random.SystemRandom()
    cles = sorted(((hasard.random() ** (1.0 / p), uid) for uid, p in eligibles if p > 0), reverse=True)
    return [uid for _k, uid in cles[:max(0, int(n))]]


def lire_duree(texte: str, maintenant: float):
    """« 30m », « 2h », « 2h30 », « 3j », « 1j12h », « 1 semaine », « 3 jours »… ou une date, heure de Paris :
    « 25/10 21:00 », « 25/10/2026 21h ». Rend la fin (horodatage) ou None si illisible."""
    t = (texte or "").strip().lower().replace(",", ".")
    #  La date d'abord, espaces compris : « 1/1 12:00 » est le 1er janvier à midi, pas le 11 à 2 h.
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(?:à\s*)?(\d{1,2})(?:\s*[h:]\s*(\d{2})?)?", t)
    if m:
        if ZoneInfo is None:
            return None
        jour, mois, an, h, mi = m.groups()
        tz = ZoneInfo(TZ)
        annee = (int(an) + (2000 if len(an) == 2 else 0)) if an else datetime.fromtimestamp(maintenant, tz).year
        try:
            d = datetime(annee, int(mois), int(jour), int(h), int(mi or 0), tzinfo=tz)
        except ValueError:
            return None
        if not an and d.timestamp() < maintenant:
            d = d.replace(year=d.year + 1)
        return int(d.timestamp())
    for mot, unite in MOTS_DUREE:
        t = t.replace(mot, unite)
    t = re.sub(r"\s+", "", t)
    m = re.fullmatch(r"(\d+)h(\d{1,2})", t)
    if m:
        return int(maintenant + int(m.group(1)) * 3600 + int(m.group(2)) * 60)
    morceaux = re.findall(r"(\d+(?:\.\d+)?)(sem|min|w|j|d|h|m)", t)
    if not morceaux or "".join(n + u for n, u in morceaux) != t:
        return None
    return int(maintenant + sum(float(n) * UNITES[u] for n, u in morceaux))


def _nombre(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def duree_txt(minutes: int) -> str:
    h, mi = divmod(int(minutes), 60)
    if not h:
        return f"{mi} min"
    return f"{h} h" + (f" {mi:02d}" if mi else "")


def barre(fait: float, total: float, cases: int = 10) -> str:
    if total <= 0:
        return ""
    n = max(0, min(cases, int(cases * fait / total + 1e-9)))
    return "▰" * n + "▱" * (cases - n)


# ═══════════════════════════════════════════════════════════════════════════════
#  Les boutons (persistants : ils marchent après un redémarrage)
# ═══════════════════════════════════════════════════════════════════════════════

class BoutonParticiper(discord.ui.DynamicItem[Button], template=r"cd:p:(?P<cid>\d+)"):
    def __init__(self, cid: int, label: str = "Participer · Enter"):
        self.cid = int(cid)
        super().__init__(Button(label=label, emoji="🎉", style=discord.ButtonStyle.success,
                                custom_id=f"cd:p:{int(cid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await participer(i, self.cid)


class BoutonStats(discord.ui.DynamicItem[Button], template=r"cd:s:(?P<cid>\d+)"):
    def __init__(self, cid: int):
        self.cid = int(cid)
        super().__init__(Button(label="Mes stats · My stats", emoji="📊", style=discord.ButtonStyle.secondary,
                                custom_id=f"cd:s:{int(cid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await montrer_stats(i, self.cid)


class BoutonActualiser(discord.ui.DynamicItem[Button], template=r"cd:r:(?P<cid>\d+)"):
    def __init__(self, cid: int, label: str = "Actualiser"):
        self.cid = int(cid)
        super().__init__(Button(label=label, emoji="🔄", style=discord.ButtonStyle.secondary,
                                custom_id=f"cd:r:{int(cid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await montrer_stats(i, self.cid)


class BoutonQuitter(discord.ui.DynamicItem[Button], template=r"cd:q:(?P<cid>\d+)"):
    def __init__(self, cid: int, label: str = "Ne plus participer"):
        self.cid = int(cid)
        super().__init__(Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"cd:q:{int(cid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await quitter(i, self.cid)


class BoutonCadeaux(discord.ui.DynamicItem[Button], template=r"cd:menu"):
    """Dans le menu de 📋logs : « 🎁 Cadeaux » (le fondateur et la direction)."""

    def __init__(self):
        super().__init__(Button(label="Cadeaux", emoji="🎁", style=discord.ButtonStyle.primary, custom_id="cd:menu"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        await ouvrir_gestion(i)


class BoutonParticipants(discord.ui.DynamicItem[Button], template=r"cd:l:(?P<cid>\d+)"):
    """« Qui participe ? » : la liste exacte, ouverte à tous (24/10/2026)."""

    def __init__(self, cid: int):
        self.cid = int(cid)
        super().__init__(Button(label="Participants", emoji="👥", style=discord.ButtonStyle.secondary,
                                custom_id=f"cd:l:{int(cid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await montrer_participants(i, self.cid, 0)


class BoutonPage(discord.ui.DynamicItem[Button], template=r"cd:lp:(?P<cid>\d+):(?P<page>\d+)"):
    """◀ ▶ dans la liste, et « Retour à la liste » depuis la fiche d'un participant."""

    def __init__(self, cid: int, page: int, label: str = "", emoji=None):
        self.cid, self.page = int(cid), int(page)
        super().__init__(Button(label=label or None, emoji=emoji, style=discord.ButtonStyle.secondary,
                                custom_id=f"cd:lp:{int(cid)}:{int(page)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]), int(match["page"]))

    async def callback(self, i: discord.Interaction):
        await montrer_participants(i, self.cid, self.page)


class ChoixParticipant(discord.ui.DynamicItem[discord.ui.Select], template=r"cd:ls:(?P<cid>\d+):(?P<page>\d+)"):
    """La liste déroulante : 25 participants par page ; en choisir un ouvre sa fiche."""

    def __init__(self, cid: int, page: int, options=None, placeholder: str = "Voir un participant"):
        self.cid, self.page = int(cid), int(page)
        super().__init__(discord.ui.Select(custom_id=f"cd:ls:{int(cid)}:{int(page)}", placeholder=placeholder[:150],
                                           options=options or [discord.SelectOption(label="—", value="0")],
                                           min_values=1, max_values=1))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]), int(match["page"]))

    async def callback(self, i: discord.Interaction):
        valeurs = (getattr(i, "data", None) or {}).get("values") or []
        uid = int(valeurs[0]) if valeurs and str(valeurs[0]).isdigit() else 0
        await montrer_participant(i, self.cid, uid, self.page)


class BoutonChercher(discord.ui.DynamicItem[Button], template=r"cd:lq:(?P<cid>\d+)"):
    """🔎 Un nom (ou un identifiant) parmi tous les participants."""

    def __init__(self, cid: int):
        self.cid = int(cid)
        super().__init__(Button(label="Chercher", emoji="🔎", style=discord.ButtonStyle.secondary,
                                custom_id=f"cd:lq:{int(cid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["cid"]))

    async def callback(self, i: discord.Interaction):
        await i.response.send_modal(FormulaireRecherche(self.cid))


class FormulaireRecherche(discord.ui.Modal):
    def __init__(self, cid: int):
        super().__init__(title="🔎 Chercher un participant", timeout=600)
        self.cid = int(cid)
        self.q = discord.ui.TextInput(max_length=32, placeholder="Un bout du pseudo, ou l'identifiant")
        self.add_item(discord.ui.Label(text="Pseudo ou identifiant", component=self.q))

    async def on_submit(self, i: discord.Interaction):
        await montrer_participants(i, self.cid, 0, str(self.q.value or "").strip())


# ═══════════════════════════════════════════════════════════════════════════════
#  La carte du cadeau (publique), les stats (éphémères), les gagnants
# ═══════════════════════════════════════════════════════════════════════════════

def texte_conditions(c: dict) -> str:
    lignes = ["**🎟️ Pour participer · To enter**"]
    if c["roles"]:
        lignes.append("• ✅ " + " ".join(f"<@&{r}>" for r in c["roles"]) + " — rôle demandé · role required")
    if c.get("roles_exclus"):
        lignes.append("• 🚫 " + " ".join(f"<@&{r}>" for r in c["roles_exclus"]) + " — exclus · excluded")
    besoins = []
    if c["msg_min"]:
        besoins.append(f"💬 **{c['msg_min']}** messages")
    if c["voc_min"]:
        besoins.append(f"🔊 **{duree_txt(c['voc_min'])}** en vocal · in voice")
    if c.get("inv_min"):
        besoins.append(f"📨 **{c['inv_min']}** invitation{'s' if c['inv_min'] > 1 else ''} · invite"
                       f"{'s' if c['inv_min'] > 1 else ''}")
    if c.get("anc_min"):
        besoins.append(f"📅 **{c['anc_min']}** jour{'s' if c['anc_min'] > 1 else ''} sur le serveur · day"
                       f"{'s' if c['anc_min'] > 1 else ''} on the server")
    if besoins:
        lien = " **et · and** " if c["logique"] == "et" else " **ou · or** "
        lignes.append("• " + lien.join(besoins))
        if c["msg_min"] or c["voc_min"]:
            lignes.append("-# Messages et vocal comptés depuis le lancement, sur tout le serveur ; puis "
                          "« Participer » · Counted since the launch, server-wide; then “Enter”")
        if c.get("inv_min"):
            lignes.append("-# Invitations : les personnes venues par tes liens et toujours là, sans les faux comptes"
                          " · Invites: people who joined through your links and stayed, no fake accounts")
    if not c["roles"] and not besoins:
        lignes.append("• Ouvert à tous : clique « Participer » · Open to everyone: click “Enter”")
    return "\n".join(lignes)


def composants_carte(c: dict, nb: int, *, apercu: bool = False) -> list:
    """La carte : l'image (ou le bandeau), le lot, les détails, gagnants et fin, les conditions, la chance,
    les inscrits, « Participer » et « Mes stats ». Terminé : les gagnants. La mention, au-dessus."""
    items = [discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{c['image']}")) if c.get("image")
             else visuels.bandeau("cadeaux", "Cadeaux")]
    statut = c.get("statut", "actif")
    suffixe = {"fini": " — terminé · ended", "annule": " — annulé · cancelled"}.get(statut, "")
    items.append(discord.ui.TextDisplay(f"## 🎁 {c['lot']}{suffixe}"))
    if c.get("details"):
        items.append(discord.ui.TextDisplay(c["details"]))
    items.append(discord.ui.Separator())
    if statut == "actif":
        #  « Un vrai timer » : Discord fait défiler ce compte à rebours chez chacun, dans sa langue.
        items.append(discord.ui.TextDisplay(
            f"### ⏳ Fin <t:{int(c['fin'])}:R>\n-# Fin · Ends : <t:{int(c['fin'])}:F> · 🏆 {c['gagnants']} "
            f"gagnant{'s' if c['gagnants'] > 1 else ''} · winner{'s' if c['gagnants'] > 1 else ''}"))
        items.append(discord.ui.TextDisplay(texte_conditions(c)))
        if c["chance_roles"] and c["multiplicateur"] > 1:
            items.append(discord.ui.TextDisplay(
                "🍀 **Plus de chances · Better odds** : " + " ".join(f"<@&{r}>" for r in c["chance_roles"])
                + f" ×{_nombre(c['multiplicateur'])}"))
        items.append(discord.ui.Separator())
        items.append(discord.ui.TextDisplay(f"-# 🎟️ {nb} participant{'s' if nb > 1 else ''}"))
        if apercu:
            boutons = [Button(label="Participer · Enter", emoji="🎉", style=discord.ButtonStyle.success, disabled=True),
                       Button(label="Mes stats · My stats", emoji="📊", style=discord.ButtonStyle.secondary,
                              disabled=True),
                       Button(label="Participants", emoji="👥", style=discord.ButtonStyle.secondary, disabled=True)]
        else:
            boutons = [BoutonParticiper(c["id"]), BoutonStats(c["id"]), BoutonParticipants(c["id"])]
        items.append(discord.ui.ActionRow(*boutons))
    elif statut == "fini":
        r = c.get("resultat") or {}
        gagnants = r.get("gagnants") or []
        items.append(discord.ui.TextDisplay(
            ("🏆 **Gagnant" + ("s" if len(gagnants) > 1 else "") + " · Winner" + ("s" if len(gagnants) > 1 else "")
             + "** : " + ", ".join(f"<@{u}>" for u in gagnants)) if gagnants
            else "🏆 Personne ne remplissait les conditions · Nobody met the conditions"))
        items.append(discord.ui.TextDisplay(
            f"-# 🎟️ {r.get('inscrits', 0)} participant(s) · {r.get('eligibles_n', len(r.get('eligibles') or []))}"
            f" rempli(ssai)ent les conditions · met the conditions · <t:{int(r.get('fini') or c['fin'])}:f>"))
    else:
        items.append(discord.ui.TextDisplay("-# Ce cadeau a été annulé · This giveaway was cancelled"))
    haut = [discord.ui.TextDisplay(c["mention"])] if c.get("mention") and statut == "actif" else []
    return haut + [discord.ui.Container(*items, accent_color=discord.Color(COULEUR))]


def vue_carte(c: dict, nb: int, **kw) -> LayoutView:
    v = LayoutView(timeout=None)
    for x in composants_carte(c, nb, **kw):
        v.add_item(x)
    return v


def progres(c: dict, messages: int, secondes: float, invitations: int = 0, membre=None) -> str:
    """« 💬 12/50 · 🔊 3 min/30 min · 📨 2/5 » : où en est un membre, en une ligne (vide sans condition)."""
    morceaux = []
    if c["msg_min"]:
        morceaux.append(f"💬 {messages}/{c['msg_min']}")
    if c["voc_min"]:
        morceaux.append(f"🔊 {duree_txt(int(secondes // 60))}/{duree_txt(c['voc_min'])}")
    if c.get("inv_min"):
        morceaux.append(f"📨 {invitations}/{c['inv_min']}")
    if c.get("anc_min"):
        morceaux.append(f"📅 {int(jours_sur_serveur(membre))}/{c['anc_min']} j")
    return " · ".join(morceaux)


def lignes_progres(c: dict, messages: int, secondes: float, langue: str = "fr", *, soi: bool = True,
                   invitations: int = 0, membre=None) -> list:
    """Où en est un membre : les barres des messages et du vocal, puis rempli ou pas encore."""
    lignes = []
    if c["msg_min"]:
        pct = min(100, int(100 * messages / c["msg_min"]))
        lignes.append(f"💬 Messages : **{messages} / {c['msg_min']}**  {barre(messages, c['msg_min'])} {pct} %")
    if c["voc_min"]:
        pct = min(100, int(100 * secondes / (c["voc_min"] * 60)))
        lignes.append(f"🔊 {tr('vocal', langue)} : **{duree_txt(int(secondes // 60))} / {duree_txt(c['voc_min'])}**"
                      f"  {barre(secondes, c['voc_min'] * 60)} {pct} %")
    if c.get("inv_min"):
        pct = min(100, int(100 * invitations / c["inv_min"]))
        lignes.append(f"📨 Invitations : **{invitations} / {c['inv_min']}**  {barre(invitations, c['inv_min'])} {pct} %")
    if c.get("anc_min"):
        jours = jours_sur_serveur(membre)
        pct = min(100, int(100 * jours / c["anc_min"]))
        lignes.append(f"📅 Ancienneté · Seniority : **{int(jours)} / {c['anc_min']} j**  {barre(jours, c['anc_min'])} {pct} %")
    n = nb_conditions(c)
    if n >= 2:
        lignes.append("-# " + tr(("les_deux" if c["logique"] == "et" else "l_un") if n == 2
                                 else ("tout" if c["logique"] == "et" else "une"), langue))
    if n:
        lignes.append(tr("rempli" if remplit(c, messages, secondes, invitations, membre)
                         else ("pas_encore" if soi else "pas_encore_autre"), langue))
    else:
        lignes.append(tr("sans", langue))
    return lignes


def vue_stats(c: dict, membre, messages: int, secondes: float, inscrit: bool, langue: str = "fr",
              entete: str = "", invitations: int = 0) -> LayoutView:
    lignes = ([entete] if entete else []) + [f"### 🎁 {c['lot']} — {tr('tes_stats', langue)}"]
    lignes += lignes_progres(c, messages, secondes, langue, invitations=invitations, membre=membre)
    mult = chance(c, membre)
    if mult > 1:
        lignes.append(tr("chance", langue, mult=_nombre(mult)))
    lignes.append(tr("est_inscrit", langue) if inscrit
                  else tr("pas_inscrit" if remplit(c, messages, secondes, invitations, membre) else "pas_inscrit_cond",
                          langue))
    lignes.append(f"{tr('tirage', langue)} <t:{int(c['fin'])}:R>")
    lignes.append("-# " + tr("regles", langue))
    if c.get("inv_min"):
        lignes.append("-# " + tr("regle_inv", langue))
    boutons = [BoutonActualiser(c["id"], tr("actualiser", langue))]
    boutons.append(BoutonQuitter(c["id"], tr("quitter", langue)) if inscrit
                   else BoutonParticiper(c["id"], tr("participer", langue)))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lignes)), discord.ui.ActionRow(*boutons),
                                    accent_color=discord.Color(COULEUR)))
    return v


def _vue_message(texte: str, couleur=Palette.NEUTRAL) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=couleur))
    return v


async def _repondre(i, vue) -> None:
    """Depuis un message éphémère (les stats) : on le réécrit ; depuis la carte : un message pour soi."""
    msg = getattr(i, "message", None)
    if msg is not None and getattr(getattr(msg, "flags", None), "ephemeral", False):
        await i.response.edit_message(view=vue)
    else:
        await i.response.send_message(view=vue, ephemeral=True)


_taches: set = set()


def _effacer_plus_tard(i, delai: float | None = None) -> None:
    """Un mot pour soi s'efface tout seul (24/10/2026 : « après, ça s'enlève tout seul »)."""
    supprimer = getattr(i, "delete_original_response", None)
    if supprimer is None:
        return

    async def _plus_tard():
        await asyncio.sleep(AVIS_S if delai is None else delai)
        try:
            await supprimer()
        except discord.HTTPException:
            pass  # déjà fermé par le membre, ou le jeton de l'interaction a expiré : il n'y a rien à faire
    t = asyncio.create_task(_plus_tard())
    _taches.add(t)
    t.add_done_callback(_taches.discard)


async def participer(i, cid: int) -> None:
    langue = await langue_de(i)
    c = await charger(cid)
    if c is None or i.guild is None or c["guild_id"] != i.guild.id:
        return await _repondre(i, _vue_message(tr("introuvable", langue)))
    if c["statut"] != "actif":
        return await _repondre(i, _vue_message(tr("fini", langue)))
    if exclu(c, i.user):
        roles = " ".join(f"<@&{r}>" for r in c["roles_exclus"])
        return await _repondre(i, _vue_message(tr("exclu", langue, roles=roles), Palette.WARNING))
    if not peut_participer(c, i.user):
        roles = " ".join(f"<@&{r}>" for r in c["roles"])
        return await _repondre(i, _vue_message(tr("reserve", langue, roles=roles), Palette.WARNING))
    messages, secondes = await stats(cid, i.user.id)
    inv = await invitations_de(c, i.user.id)
    retire = await _vu_retire(cid, i.user.id)
    if not remplit(c, messages, secondes, inv, i.user):
        #  24/10/2026, le fondateur : sans les messages (ou le vocal) demandés, on ne participe pas — et on
        #  voit tout de suite ce qu'il faut, et où on en est. Une inscription d'avant la règle part aussi.
        #  Ce mot n'est que pour lui, et il s'efface.
        if await _retirer_inscriptions(cid, [i.user.id]):
            planifier_maj(i.guild, cid)
            retire = True
        await _repondre(i, vue_stats(c, i.user, messages, secondes, False, langue,
                                     entete=tr("retiree" if retire else "manque", langue), invitations=inv))
        return _effacer_plus_tard(i)
    cur_id = await _ecrire("INSERT OR IGNORE INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(?,?,?)",
                           (int(cid), i.user.id, int(_mur())))
    await _repondre(i, vue_stats(c, i.user, messages, secondes, True, langue, entete=tr("inscrit", langue),
                                 invitations=inv))
    if cur_id:
        planifier_maj(i.guild, cid)


async def quitter(i, cid: int) -> None:
    langue = await langue_de(i)
    c = await charger(cid)
    if c is None or i.guild is None or c["guild_id"] != i.guild.id:
        return await _repondre(i, _vue_message(tr("introuvable", langue)))
    await _ecrire("DELETE FROM cadeaux_inscrits WHERE cadeau_id=? AND membre_id=?", (int(cid), i.user.id))
    if c["statut"] != "actif":
        return await _repondre(i, _vue_message(tr("fini", langue)))
    messages, secondes = await stats(cid, i.user.id)
    await _repondre(i, vue_stats(c, i.user, messages, secondes, False, langue, entete=tr("quitte", langue),
                                 invitations=await invitations_de(c, i.user.id)))
    planifier_maj(i.guild, cid)


async def montrer_stats(i, cid: int) -> None:
    langue = await langue_de(i)
    c = await charger(cid)
    if c is None or i.guild is None or c["guild_id"] != i.guild.id:
        return await _repondre(i, _vue_message(tr("introuvable", langue)))
    if c["statut"] != "actif":
        return await _repondre(i, _vue_message(tr("fini", langue)))
    messages, secondes = await stats(cid, i.user.id)
    retire = await _vu_retire(cid, i.user.id)
    await _repondre(i, vue_stats(c, i.user, messages, secondes, await est_inscrit(cid, i.user.id), langue,
                                 entete=tr("retiree", langue) if retire else "",
                                 invitations=await invitations_de(c, i.user.id)))
    if retire:
        _effacer_plus_tard(i)


PAR_PAGE = 25          # une liste déroulante Discord : 25 choix ; au-delà, des pages


def _nom(g, uid: int) -> str:
    m = g.get_member(int(uid))
    return m.display_name if m is not None else f"parti · {uid}"


async def montrer_participants(i, cid: int, page: int = 0, recherche: str = "", *, nouveau: bool = False) -> None:
    """La liste exacte des participants (24/10/2026 : « une belle liste déroulante… sans limite »)."""
    langue = await langue_de(i)
    c = await charger(cid)
    if c is None or i.guild is None or c["guild_id"] != i.guild.id:
        return await _repondre(i, _vue_message(tr("introuvable", langue)))
    vue = await vue_participants(i.guild, c, page, recherche)
    if nouveau:
        await i.response.send_message(view=vue, ephemeral=True)
    else:
        await _repondre(i, vue)


async def vue_participants(g, c: dict, page: int = 0, recherche: str = "") -> LayoutView:
    """25 par page dans une liste déroulante (le rang, le nom, où il en est), ◀ ▶ pour les pages, 🔎 pour un
    nom. Deux lectures de la base par page, quel que soit le nombre de participants."""
    cid = int(c["id"])
    liste = await inscrits_quand(cid)
    conditions = bool(nb_conditions(c))
    tous = await stats_de_tous(cid) if conditions else {}
    invs = await invitations_tous(c)
    rangs = {u: k_ + 1 for k_, (u, _q) in enumerate(liste)}
    lignes = [f"### 👥 Participants · {c['lot']}"]
    boutons: list = []
    if recherche:
        q = recherche.casefold()

        def trouve(u):
            m = g.get_member(u)
            noms = (_nom(g, u), getattr(m, "name", "") or "", getattr(m, "global_name", "") or "")
            return q == str(u) or any(q in str(n).casefold() for n in noms)
        choisis = [x for x in liste if trouve(x[0])]
        tranche, page = choisis[:PAR_PAGE], 0
        lignes.append(f"-# 🔎 « {discord.utils.escape_markdown(recherche)} » : {len(choisis)} sur {len(liste)}"
                      + (" · les 25 premiers : précise la recherche" if len(choisis) > PAR_PAGE else ""))
        boutons = [BoutonPage(cid, 0, "Toute la liste", "📋"), BoutonChercher(cid)]
    else:
        pages = max(1, -(-len(liste) // PAR_PAGE))
        page = min(max(0, int(page)), pages - 1)
        tranche = liste[page * PAR_PAGE:(page + 1) * PAR_PAGE]
        ok = (sum(1 for u, _q in liste if remplit(c, *tous.get(u, (0, 0.0)), invs.get(u, 0), g.get_member(u)))
              if conditions else len(liste))
        lignes.append(f"-# 🎟️ {len(liste)} participant{'s' if len(liste) > 1 else ''}"
                      + (f" · ✅ {ok} rempli{'ssent' if ok > 1 else 't'} les conditions" if conditions else "")
                      + (f" · page {page + 1}/{pages}" if pages > 1 else ""))
        if pages > 1:
            boutons = [BoutonPage(cid, page - 1, emoji="◀") if page > 0
                       else Button(emoji="◀", style=discord.ButtonStyle.secondary, disabled=True,
                                   custom_id=f"cd:lx:{cid}:a"),
                       Button(label=f"{page + 1} / {pages}", style=discord.ButtonStyle.secondary, disabled=True,
                              custom_id=f"cd:lx:{cid}:p"),
                       BoutonPage(cid, page + 1, emoji="▶") if page + 1 < pages
                       else Button(emoji="▶", style=discord.ButtonStyle.secondary, disabled=True,
                                   custom_id=f"cd:lx:{cid}:b")]
        boutons.append(BoutonChercher(cid))
    items = [discord.ui.TextDisplay("\n".join(lignes))]
    if tranche:
        options = []
        for u, _quand in tranche:
            m_, s_ = tous.get(u, (0, 0.0))
            membre = g.get_member(u)
            mult = chance(c, membre) if membre is not None else 1.0
            desc = " · ".join(x for x in (progres(c, m_, s_, invs.get(u, 0), membre),
                                          f"🍀 ×{_nombre(mult)}" if mult > 1 else "") if x)
            options.append(discord.SelectOption(
                label=f"{rangs[u]}. {_nom(g, u)}"[:100], value=str(u), description=(desc or "Inscrit")[:100],
                emoji=("✅" if remplit(c, m_, s_, invs.get(u, 0), membre) else "⏳") if conditions else "🎟️"))
        debut = rangs[tranche[0][0]]
        espace = (f"{debut}–{rangs[tranche[-1][0]]} sur {len(liste)}" if not recherche
                  else f"{len(tranche)} résultat{'s' if len(tranche) > 1 else ''}")
        items.append(discord.ui.ActionRow(ChoixParticipant(cid, page, options,
                                                           f"Voir un participant · {espace}")))
    else:
        items.append(discord.ui.TextDisplay("Personne pour l'instant." if not recherche else "Aucun participant à ce nom."))
    if boutons:
        items.append(discord.ui.ActionRow(*boutons))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(COULEUR)))
    return v


async def montrer_participant(i, cid: int, uid: int, page: int = 0) -> None:
    """La fiche d'un participant : son rang, depuis quand, ses messages et son vocal, sa chance."""
    langue = await langue_de(i)
    c = await charger(cid)
    if c is None or i.guild is None or c["guild_id"] != i.guild.id:
        return await _repondre(i, _vue_message(tr("introuvable", langue)))
    liste = await inscrits_quand(cid)
    rang = next((k_ + 1 for k_, (u, _q) in enumerate(liste) if u == int(uid)), 0)
    quand = next((q for u, q in liste if u == int(uid)), 0)
    messages, secondes = await stats(cid, uid)
    membre = i.guild.get_member(int(uid))
    lignes = [f"### {f'{rang}. ' if rang else ''}<@{int(uid)}>",
              f"🎟️ Inscrit <t:{quand}:R>" if rang and quand else "🎟️ N'est plus inscrit"]
    lignes += lignes_progres(c, messages, secondes, langue, soi=False, invitations=await invitations_de(c, uid),
                             membre=membre)
    mult = chance(c, membre) if membre is not None else 1.0
    if mult > 1:
        lignes.append(f"🍀 Chance : ×{_nombre(mult)}")
    tete = discord.ui.TextDisplay("\n".join(lignes))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.Section(tete, accessory=discord.ui.Thumbnail(membre.display_avatar.url)) if membre is not None
        else tete,
        discord.ui.ActionRow(BoutonPage(cid, page, "Retour à la liste", "◀")),
        accent_color=discord.Color(COULEUR)))
    await _repondre(i, v)


async def elaguer(g) -> int:
    """24/10/2026, le fondateur : « s'il y a des gens qui participent et qui n'ont pas les messages, tu les
    retires » — puis : « je veux que ce soit vu individuellement… quand ils cliquent ». Pour les cadeaux en
    cours : ceux qui ne remplissent pas les conditions sont retirés et notés ; chacun le lit en cliquant,
    pour lui seul. Aucun message public. Rend le nombre retiré."""
    total = 0
    for cid in list(_actifs.get(g.id) or {}):
        c = await charger(cid)
        if c is None or c["statut"] != "actif" or not nb_conditions(c):
            continue
        async with _verrou(("cadeau", cid)):
            tous, invs = await stats_de_tous(cid), await invitations_tous(c)
            retires = [(u, *tous.get(u, (0, 0.0))) for u in await inscrits(cid)
                       if not remplit(c, *tous.get(u, (0, 0.0)), invs.get(u, 0), g.get_member(u))]
            await _retirer_inscriptions(cid, [u for u, _m, _s in retires])
        await maj_carte(g, cid)
        if not retires:
            continue
        total += len(retires)
        await _noter_retires(cid, [u for u, _m, _s in retires])
        await _journal(g, "cadeaux.retires", f"🎁 « {c['lot']} » : {len(retires)} participation(s) retirée(s), "
                       "conditions pas encore remplies — chacun le lit en cliquant, pour lui seul.")
    return total


def _texte_composants(m) -> str:
    """Le texte d'un message Components V2 (ses TextDisplay)."""
    out = []

    def parcourir(c):
        if getattr(c, "type", None) == discord.ComponentType.text_display:
            out.append(str(getattr(c, "content", "") or ""))
        for x in getattr(c, "children", None) or []:
            parcourir(x)
    for c in getattr(m, "components", None) or []:
        parcourir(c)
    return "\n".join(out)


async def nettoyer_avis(g) -> dict:
    """L'avis public « Participation retirée » part du salon ; les membres qu'il nommait sont notés et le
    liront en cliquant, pour eux seuls. Rend le relevé : messages lus, ceux du bot, avis effacés."""
    salon = await salon_cadeaux(g)
    moi = getattr(getattr(g, "me", None), "id", 0)
    releve = {"lus": 0, "du_bot": 0, "effaces": 0}
    if salon is None:
        return releve
    async for m in salon.history(limit=100):
        releve["lus"] += 1
        if getattr(m.author, "id", 0) != moi:
            continue
        releve["du_bot"] += 1
        texte = _texte_composants(m)
        if "Participation retirée" not in texte:
            continue
        carte = getattr(getattr(m, "reference", None), "message_id", None)
        if carte:
            async with _get_db() as db:
                async with db.execute("SELECT id FROM cadeaux WHERE message_id=?", (int(carte),)) as cur:
                    r = await cur.fetchone()
            if r is not None:
                await _noter_retires(int(r[0]), [int(u) for u in re.findall(r"<@!?(\d+)>", texte)])
        try:
            await m.delete()
            releve["effaces"] += 1
        except discord.HTTPException as ex:
            _log("[CADEAUX][E9] avis non effacé")
            _log(f"[CADEAUX][E9:DETAIL] message={m.id} {type(ex).__name__} {ex}")
    return releve


async def etat(g) -> list:
    """Pour /stats (des chiffres, aucun nom) : chaque cadeau en cours, ses conditions, ses inscrits, combien
    les remplissent, et ce qui a été compté — la preuve que le comptage tourne."""
    out = []
    for cid in list(_actifs.get(g.id) or {}):
        c = await charger(cid)
        if c is None or c["statut"] != "actif":
            continue
        tous, liste, invs = await stats_de_tous(cid), await inscrits(cid), await invitations_tous(c)
        out.append({"msg_min": c["msg_min"], "voc_min": c["voc_min"], "inv_min": c["inv_min"], "anc_min": c["anc_min"],
                    "logique": c["logique"],
                    "inscrits": len(liste),
                    "remplissent": sum(1 for u in liste
                                       if remplit(c, *tous.get(u, (0, 0.0)), invs.get(u, 0), g.get_member(u))),
                    "membres_comptes": len(tous), "messages": sum(m for m, _s in tous.values()),
                    "vocal_min": int(sum(s for _m, s in tous.values()) // 60),
                    "fin_dans_min": max(0, int((c["fin"] - _mur()) // 60))})
    return out


def planifier_maj(g, cid: int) -> None:
    """Le nombre d'inscrits se réécrit une fois pour toute une rafale de clics."""
    if cid not in _maj_prevues:
        _maj_prevues[cid] = asyncio.create_task(_maj_apres(g, cid))


async def _maj_apres(g, cid: int) -> None:
    try:
        await asyncio.sleep(MAJ_CARTE_S)
    finally:
        _maj_prevues.pop(cid, None)
    await maj_carte(g, cid)


async def _salon(g, sid):
    ch = g.get_channel_or_thread(int(sid or 0)) if sid else None
    if ch is not None or not sid:
        return ch
    try:
        return await g.fetch_channel(int(sid))
    except discord.NotFound:
        return None
    except discord.HTTPException as ex:
        _log(f"[CADEAUX:DETAIL] salon {sid} {type(ex).__name__} {ex}")
        return None


async def maj_carte(g, cid: int) -> bool:
    c = await charger(cid)
    salon = await _salon(g, c["salon_id"]) if c else None
    if c is None or salon is None or not c["message_id"]:
        return False
    try:
        await salon.get_partial_message(int(c["message_id"])).edit(
            view=vue_carte(c, await nb_inscrits(cid)), allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.NotFound:
        return False
    except discord.HTTPException as ex:
        _log("[CADEAUX][E2] carte non mise à jour")
        _log(f"[CADEAUX][E2:DETAIL] cadeau={cid} {type(ex).__name__} {ex}")
        return False


def vue_gagnants(c: dict, gagnants: list, *, relance: bool = False, ticket=None) -> LayoutView:
    if gagnants:
        noms = ", ".join(f"<@{u}>" for u in gagnants)
        plus = len(gagnants) > 1
        texte = (f"### {'🔁' if relance else '🎉'} {noms}\n"
                 f"🇫🇷 Bravo ! {'Vous remportez' if plus else 'Tu remportes'} **{c['lot']}**.\n"
                 f"🇬🇧 Congratulations! You win **{c['lot']}**.")
    else:
        texte = (f"### 🎁 {c['lot']}\n🇫🇷 Personne ne remplissait les conditions : pas de gagnant.\n"
                 "🇬🇧 Nobody met the conditions: no winner.")
    items = []
    if gagnants and ticket is not None:
        items.append(discord.ui.Section(
            discord.ui.TextDisplay(texte + "\n-# Pour recevoir le lot : ouvre un ticket · To claim it: open a ticket"),
            accessory=Button(label="Ticket", emoji="🎫", url=ticket.jump_url)))
    else:
        items.append(discord.ui.TextDisplay(texte))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(COULEUR)))
    return v


async def _annoncer(g, c: dict, gagnants: list, *, relance: bool = False) -> bool:
    salon = await _salon(g, c["salon_id"])
    if salon is None:
        return False
    ticket = _ticket(g) if _ticket else None
    envoi = {"view": vue_gagnants(c, gagnants, relance=relance, ticket=ticket),
             "allowed_mentions": discord.AllowedMentions(everyone=False, roles=False,
                                                         users=[discord.Object(u) for u in gagnants])}
    if c["message_id"]:
        envoi["reference"] = discord.MessageReference(message_id=int(c["message_id"]), channel_id=salon.id,
                                                      fail_if_not_exists=False)
    try:
        msg = await salon.send(**envoi)
        await _ecrire("INSERT OR REPLACE INTO cadeaux_messages(message_id, salon_id, effacer_a) VALUES(?,?,?)",
                      (int(msg.id), int(salon.id), int(_mur() + ANNONCE_S)))
        return True
    except discord.HTTPException as ex:
        _log("[CADEAUX][E3] gagnants non annoncés")
        _log(f"[CADEAUX][E3:DETAIL] cadeau={c['id']} {type(ex).__name__} {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Le tirage, un nouveau tirage, l'annulation
# ═══════════════════════════════════════════════════════════════════════════════

async def terminer(g, cid: int, *, par: int = 0):
    """Le tirage. Puis « ça nettoie toutes les données » : compteurs et inscrits effacés ; le résultat
    reste (les gagnables gardés 7 jours pour un nouveau tirage)."""
    async with _verrou(("cadeau", cid)):
        c = await charger(cid)
        if c is None or c["statut"] != "actif":
            return None
        await vider()
        if c.get("inv_min") and _inv_relever is not None:
            await _inv_relever(g)   # les invités partis ne comptent plus, à l'instant du tirage
        liste, compteurs, invs = await inscrits(cid), await _stats_en_base(cid), await invitations_tous(c)
        eligibles = []
        for uid in liste:
            m = g.get_member(uid)
            if m is None or getattr(m, "bot", False) or not peut_participer(c, m):
                continue
            messages, secondes = compteurs.get(uid, (0, 0.0))
            if remplit(c, messages, secondes, invs.get(uid, 0), m):
                eligibles.append((uid, chance(c, m)))
        gagnants = tirer(eligibles, c["gagnants"])
        resultat = {"gagnants": gagnants, "eligibles": [[u, p] for u, p in eligibles], "eligibles_n": len(eligibles),
                    "inscrits": len(liste), "fini": int(_mur()), "par": int(par)}
        await _ecrire("UPDATE cadeaux SET statut='fini', resultat=? WHERE id=?", (json.dumps(resultat), int(cid)))
        await _ecrire("DELETE FROM cadeaux_stats WHERE cadeau_id=?", (int(cid),))
        await _ecrire("DELETE FROM cadeaux_inscrits WHERE cadeau_id=?", (int(cid),))
        _oublier(g.id, cid)
    c = await charger(cid)
    await maj_carte(g, cid)
    await _annoncer(g, c, gagnants)
    noms = ", ".join(f"<@{u}>" for u in gagnants) or "personne (aucun ne remplissait les conditions)"
    await _journal(g, "cadeaux.tirage", f"🎁 « {c['lot']} » : {len(liste)} participant(s), {len(eligibles)} "
                   f"rempli(ssai)ent les conditions — gagnant(s) : {noms}.", auteur_id=int(par))
    return c


async def relancer(g, cid: int, *, par: int = 0) -> tuple:
    """Un nouveau tirage (un gagnant absent, un lot en plus) : un gagnant de plus parmi les gagnables qui
    n'ont pas encore gagné. Rend (gagnant ou None, raison)."""
    async with _verrou(("cadeau", cid)):
        c = await charger(cid)
        if c is None or c["statut"] != "fini":
            return None, "Ce cadeau n'est pas terminé."
        r = dict(c["resultat"] or {})
        deja = set(r.get("gagnants") or [])
        reste = [(int(u), float(p)) for u, p in r.get("eligibles") or [] if int(u) not in deja
                 and g.get_member(int(u)) is not None]
        if not reste:
            return None, "Plus personne à tirer : tous les gagnables ont gagné (ou sont partis)."
        nouveau = tirer(reste, 1)[0]
        r["gagnants"] = list(r.get("gagnants") or []) + [nouveau]
        await _ecrire("UPDATE cadeaux SET resultat=? WHERE id=?", (json.dumps(r), int(cid)))
    c = await charger(cid)
    await maj_carte(g, cid)
    await _annoncer(g, c, [nouveau], relance=True)
    await _journal(g, "cadeaux.relance", f"🎁 « {c['lot']} » : nouveau tirage — <@{nouveau}>.", auteur_id=int(par))
    return nouveau, ""


async def annuler(g, cid: int, *, par: int = 0) -> bool:
    async with _verrou(("cadeau", cid)):
        c = await charger(cid)
        if c is None or c["statut"] != "actif":
            return False
        await _ecrire("UPDATE cadeaux SET statut='annule' WHERE id=?", (int(cid),))
        await _ecrire("DELETE FROM cadeaux_stats WHERE cadeau_id=?", (int(cid),))
        await _ecrire("DELETE FROM cadeaux_inscrits WHERE cadeau_id=?", (int(cid),))
        _oublier(g.id, cid)
    await maj_carte(g, cid)
    await _journal(g, "cadeaux.annule", f"🎁 « {c['lot']} » annulé par <@{par}>.", auteur_id=int(par))
    return True


async def purger(g) -> int:
    """Le ménage, toutes les heures : l'annonce des gagnants s'efface après 24 h (la carte les garde) ; les
    notes des retirés d'un cadeau fini partent ; après 7 jours, la liste des gagnables d'un cadeau terminé
    part aussi : il ne reste que le lot et ses gagnants."""
    n = 0
    async with _get_db() as db:
        async with db.execute("SELECT message_id, salon_id FROM cadeaux_messages WHERE effacer_a<=?",
                              (int(_mur()),)) as cur:
            echus = [(int(a), int(b)) for a, b in await cur.fetchall()]
        await db.execute("DELETE FROM cadeaux_retires WHERE cadeau_id NOT IN "
                         "(SELECT id FROM cadeaux WHERE statut='actif')")
        await db.commit()
    for mid, sid in echus:
        salon = g.get_channel(sid)
        if salon is None:
            continue   # un autre serveur (ou un salon disparu : la ligne part ci-dessous)
        try:
            await salon.get_partial_message(mid).delete()
            n += 1
        except discord.NotFound:
            pass
        except discord.HTTPException as ex:
            _log("[CADEAUX][E10] annonce non effacée")
            _log(f"[CADEAUX][E10:DETAIL] message={mid} {type(ex).__name__} {ex}")
            continue
        await _ecrire("DELETE FROM cadeaux_messages WHERE message_id=?", (mid,))
    for c in await recents(g.id, 50):
        r = c["resultat"] or {}
        if c["statut"] == "fini" and r.get("eligibles") and _mur() - int(r.get("fini") or 0) > GARDER_RESULTAT_S:
            r = dict(r, eligibles=[])
            await _ecrire("UPDATE cadeaux SET resultat=? WHERE id=?", (json.dumps(r), c["id"]))
            n += 1
    return n


async def tic(guilds) -> int:
    """Toutes les 30 s : les compteurs en base ; un cadeau arrivé à sa fin est tiré. Rend le nombre tiré."""
    for g in guilds:
        if g.id not in _charges:
            try:
                await charger_actifs(g)
            except Exception as ex:
                _log("[CADEAUX][E4] cadeaux en cours non rechargés")
                _log(f"[CADEAUX][E4:DETAIL] {g.id} {type(ex).__name__} {ex}")
    await vider()
    _elaguer(_mono())
    tires = 0
    maintenant = _mur()
    for g in guilds:
        for cid in list(_actifs.get(g.id) or {}):
            c = await charger(cid)
            if c is None or c["statut"] != "actif":
                _oublier(g.id, cid)
            elif c["fin"] <= maintenant:
                try:
                    if await terminer(g, cid) is not None:
                        tires += 1
                except Exception as ex:
                    _log("[CADEAUX][E5] tirage en échec")
                    _log(f"[CADEAUX][E5:DETAIL] cadeau={cid} {type(ex).__name__} {ex}")
            elif c["fin"] - maintenant <= MINUTEUR_S and cid not in _minuteurs:
                _minuteurs[cid] = asyncio.create_task(_minuteur(g, cid, float(c["fin"])))
    return tires


async def _minuteur(g, cid: int, fin: float) -> None:
    """« Un vrai timer » : le tirage tombe à la seconde de la fin, pas au passage suivant de la boucle."""
    try:
        await asyncio.sleep(max(0.0, fin - _mur()))
        await terminer(g, cid)
    except asyncio.CancelledError:
        raise
    except Exception as ex:
        _log("[CADEAUX][E7] minuteur en échec")
        _log(f"[CADEAUX][E7:DETAIL] cadeau={cid} {type(ex).__name__} {ex}")
    finally:
        _minuteurs.pop(cid, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le salon 🎁giveaways
# ═══════════════════════════════════════════════════════════════════════════════

def vue_accueil() -> LayoutView:
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau("cadeaux", "Cadeaux"),
        discord.ui.TextDisplay(
            "🇫🇷 **Les cadeaux du serveur.** Sur chaque cadeau : « 🎉 Participer », puis « 📊 Mes stats » pour voir "
            "où tu en es. Les conditions (messages, vocal) se comptent depuis le lancement du cadeau ; le tirage se "
            "fait au hasard parmi ceux qui les remplissent.\n🇬🇧 **Server giveaways.** On each giveaway: “🎉 Enter”, "
            "then “📊 My stats” to follow your progress. Conditions (messages, voice) count from the giveaway's "
            "launch; winners are drawn at random among those who meet them."),
        discord.ui.TextDisplay(
            "-# 💬 Un message compte s'il a 2 caractères ou plus, un toutes les 3 s au plus · 🔊 le vocal compte hors "
            "AFK, casque non coupé · 🍀 un rôle chanceux ×2 a deux fois plus de chances."),
        accent_color=discord.Color(COULEUR)))
    return v


def droits_salon(g) -> dict:
    return {g.default_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                                                        send_messages=False, add_reactions=False,
                                                        create_public_threads=False, create_private_threads=False,
                                                        send_messages_in_threads=False),
            g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                              attach_files=True, read_message_history=True, manage_messages=True,
                                              mention_everyone=True)}


async def salon_cadeaux(g, *, creer: bool = False):
    """Le salon des cadeaux, suivi par son identifiant (le fondateur le range où il veut). `creer` : s'il
    n'existe plus, il est recréé — sans catégorie, en haut, à ranger."""
    c = await _cfg(g.id)
    ch = g.get_channel(int(c.get("cadeaux_salon", 0) or 0))
    if isinstance(ch, discord.TextChannel) or not creer:
        return ch if isinstance(ch, discord.TextChannel) else None
    ch = await g.create_text_channel(NOM_SALON, topic=SUJET_SALON, overwrites=droits_salon(g), position=0,
                                     reason="Les cadeaux : un salon, à ranger où tu veux")
    await _db_set(g.id, "cadeaux_salon", ch.id)
    try:
        await ch.send(view=vue_accueil(), allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as ex:
        _log(f"[CADEAUX:DETAIL] accueil non posé {type(ex).__name__} {ex}")
    return ch


# ═══════════════════════════════════════════════════════════════════════════════
#  Lancer un cadeau (le fondateur et la direction)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Brouillon:
    lot: str = ""
    details: str = ""
    gagnants: int = 1
    duree: str = "1j"
    image: bytes = b""
    image_ext: str = ""
    roles: list = field(default_factory=list)
    exclus: list = field(default_factory=list)
    msg_min: int = 0
    voc_min: int = 0
    inv_min: int = 0
    anc_min: int = 0
    logique: str = "et"
    chance_roles: list = field(default_factory=list)
    multiplicateur: float = 2.0
    mention: str = ""            # "" · "everyone"

    @property
    def image_nom(self) -> str:
        return f"cadeau.{self.image_ext}" if self.image else ""

    def fichier(self):
        return discord.File(io.BytesIO(self.image), filename=self.image_nom) if self.image else None

    def comme_cadeau(self, fin: int) -> dict:
        return {"id": 0, "lot": self.lot or "(le lot)", "details": self.details, "image": self.image_nom,
                "gagnants": self.gagnants, "fin": fin, "roles": list(self.roles),
                "roles_exclus": list(self.exclus), "msg_min": self.msg_min,
                "voc_min": self.voc_min, "inv_min": self.inv_min, "anc_min": self.anc_min, "logique": self.logique,
                "chance_roles": list(self.chance_roles),
                "multiplicateur": self.multiplicateur, "statut": "actif",
                "mention": "@everyone" if self.mention == "everyone" else "", "resultat": {}}


async def lancer(g, auteur, b: Brouillon) -> tuple:
    """Publie le cadeau dans 🎁giveaways (recréé s'il a disparu). Rend (lien, "") ou ("", raison)."""
    if not b.lot:
        return "", "Il faut un lot."
    maintenant = int(_mur())
    fin = lire_duree(b.duree, maintenant)
    if fin is None or not DUREE_MIN_S <= fin - maintenant <= DUREE_MAX_S:
        return "", "La durée est illisible ou hors limites (1 minute à 60 jours)."
    try:
        salon = await salon_cadeaux(g, creer=True)
    except discord.HTTPException as ex:
        _log(f"[CADEAUX:DETAIL] salon non recréé {type(ex).__name__} {ex}")
        salon = None
    if salon is None:
        return "", "Le salon des cadeaux n'existe plus et je ne peux pas le recréer (droits)."
    droits = salon.permissions_for(g.me)
    if not (droits.send_messages and droits.embed_links and (droits.attach_files or not b.image)):
        return "", f"Je ne peux pas publier dans {salon.mention} (droits du salon)."
    mention = "@everyone" if b.mention == "everyone" else ""
    cid = await _ecrire(
        "INSERT INTO cadeaux(guild_id, salon_id, auteur_id, lot, details, image, gagnants, debut, fin, roles,"
        " msg_min, voc_min, logique, chance_roles, multiplicateur, mention, roles_exclus, inv_min, anc_min)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (g.id, salon.id, auteur.id, b.lot, b.details, b.image_nom, int(b.gagnants), maintenant, fin,
         json.dumps(b.roles), int(b.msg_min), int(b.voc_min), b.logique, json.dumps(b.chance_roles),
         float(b.multiplicateur), mention, json.dumps(b.exclus), int(b.inv_min), int(b.anc_min)))
    c = await charger(cid)
    envoi = {"view": vue_carte(c, 0),
             "allowed_mentions": discord.AllowedMentions(everyone=bool(mention), users=False, roles=False)}
    if b.image:
        envoi["file"] = b.fichier()
    try:
        msg = await salon.send(**envoi)
    except discord.HTTPException as ex:
        _log("[CADEAUX][E6] cadeau non publié")
        _log(f"[CADEAUX][E6:DETAIL] salon={salon.id} {type(ex).__name__} {ex}")
        await _ecrire("DELETE FROM cadeaux WHERE id=?", (cid,))
        return "", "Discord a refusé la publication : réessaie dans un instant."
    await _ecrire("UPDATE cadeaux SET message_id=? WHERE id=?", (msg.id, cid))
    _actifs.setdefault(g.id, {})[cid] = float(maintenant)
    _charges.add(g.id)
    _demarrer_vocaux(g)
    await _journal(g, "cadeaux.lance", f"{auteur.mention} a lancé le cadeau « {b.lot} » dans {salon.mention} "
                   f"(fin <t:{fin}:f>).", auteur_id=auteur.id)
    return msg.jump_url, ""


class FormulaireLot(discord.ui.Modal):
    def __init__(self, porteur):
        super().__init__(title="🎁 Le cadeau", timeout=1800)
        self.porteur, b = porteur, porteur.b
        self.lot = discord.ui.TextInput(max_length=LOT_MAX, default=b.lot or None, placeholder="Ex. Nitro 1 mois")
        self.details = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=DETAILS_MAX, required=False,
                                            default=b.details or None, placeholder="Facultatif : ce qu'il faut savoir")
        self.gagnants = discord.ui.TextInput(max_length=2, default=str(b.gagnants), placeholder="1")
        self.duree = discord.ui.TextInput(max_length=40, default=b.duree or "1j",
                                          placeholder="30m · 2h · 3j · 1 semaine · ou 25/10 21:00")
        self.image = discord.ui.FileUpload(required=False, max_values=1)
        self.add_item(discord.ui.Label(text="Le lot · Prize", component=self.lot))
        self.add_item(discord.ui.Label(text="Détails (facultatif)", component=self.details))
        self.add_item(discord.ui.Label(text="Gagnants (1 à 20)", component=self.gagnants))
        self.add_item(discord.ui.Label(text="Durée", component=self.duree,
                                       description="Ou la date de fin, heure de Paris : 25/10 21:00"))
        self.add_item(discord.ui.Label(text="Image (facultatif)", component=self.image,
                                       description="Garde l'image actuelle si tu n'en mets pas." if b.image
                                       else "Sinon, le bandeau des cadeaux."))

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer()
        p = self.porteur
        b, erreurs = p.b, []
        b.lot = " ".join(str(self.lot.value or "").split())[:LOT_MAX]
        b.details = str(self.details.value or "").strip()[:DETAILS_MAX]
        try:
            b.gagnants = max(1, min(GAGNANTS_MAX, int(str(self.gagnants.value or "1").strip())))
        except ValueError:
            erreurs.append("Le nombre de gagnants doit être un nombre (1 à 20).")
        b.duree = str(self.duree.value or "").strip()
        fin = lire_duree(b.duree, _mur())
        if fin is None or not DUREE_MIN_S <= fin - _mur() <= DUREE_MAX_S:
            erreurs.append("Durée illisible ou hors limites : 30m, 2h, 3j, 1 semaine, ou 25/10 21:00 (1 minute à "
                           "60 jours).")
        pieces = list(getattr(self.image, "values", None) or [])
        if pieces:
            piece = pieces[0]
            ext = TYPES_IMAGE.get(str(piece.content_type or "").split(";")[0].strip().lower())
            if ext is None:
                erreurs.append("L'image doit être un PNG, un JPG, un GIF ou un WebP.")
            elif int(piece.size or 0) > IMAGE_MAX:
                erreurs.append("L'image dépasse 8 Mo.")
            else:
                try:
                    b.image, b.image_ext = await piece.read(), ext
                except discord.HTTPException as ex:
                    _log(f"[CADEAUX:DETAIL] image illisible {type(ex).__name__} {ex}")
                    erreurs.append("Impossible de lire l'image : renvoie-la.")
        piece_jointe = b.fichier()
        await i.edit_original_response(view=VueCadeau(p.auteur, p.g, b, erreurs),
                                       attachments=[piece_jointe] if piece_jointe else [])


class FormulaireConditions(discord.ui.Modal):
    def __init__(self, porteur):
        super().__init__(title="📊 Les conditions", timeout=1800)
        self.porteur, b = porteur, porteur.b
        self.msg = discord.ui.TextInput(max_length=6, default=str(b.msg_min), placeholder="0")
        self.voc = discord.ui.TextInput(max_length=6, default=str(b.voc_min), placeholder="0")
        self.inv = discord.ui.TextInput(max_length=5, default=str(b.inv_min), placeholder="0")
        self.anc = discord.ui.TextInput(max_length=4, default=str(b.anc_min), placeholder="0")
        self.add_item(discord.ui.Label(text="Messages à envoyer (0 : aucun)", component=self.msg,
                                       description="Comptés depuis le lancement, sur tout le serveur."))
        self.add_item(discord.ui.Label(text="Minutes en vocal (0 : aucune)", component=self.voc,
                                       description="Hors salon AFK, casque non coupé."))
        self.add_item(discord.ui.Label(text="Invitations (0 : aucune)", component=self.inv,
                                       description="Venues par ses liens, toujours là, pas de faux comptes."))
        self.add_item(discord.ui.Label(text="Jours sur le serveur (0 : aucun)", component=self.anc,
                                       description="Son ancienneté sur le serveur."))

    async def on_submit(self, i: discord.Interaction):
        p, erreurs = self.porteur, []
        for cle, champ, nom in (("msg_min", self.msg, "messages"), ("voc_min", self.voc, "minutes"),
                                ("inv_min", self.inv, "invitations"), ("anc_min", self.anc, "jours")):
            try:
                setattr(p.b, cle, max(0, min(100000, int(str(champ.value or "0").strip() or 0))))
            except ValueError:
                erreurs.append(f"Le nombre de {nom} doit être un nombre entier.")
        await i.response.edit_message(view=VueCadeau(p.auteur, p.g, p.b, erreurs))


class FormulaireChance(discord.ui.Modal):
    def __init__(self, porteur):
        super().__init__(title="🍀 Le multiplicateur", timeout=1800)
        self.porteur = porteur
        self.mult = discord.ui.TextInput(max_length=5, default=_nombre(porteur.b.multiplicateur), placeholder="2")
        self.add_item(discord.ui.Label(text="Multiplicateur (1,1 à 10)", component=self.mult,
                                       description="×2 : deux fois plus de chances que les autres."))

    async def on_submit(self, i: discord.Interaction):
        p, erreurs = self.porteur, []
        try:
            p.b.multiplicateur = round(max(MULT_MIN, min(MULT_MAX, float(str(self.mult.value).replace(",", ".")))), 2)
        except ValueError:
            erreurs.append("Le multiplicateur doit être un nombre, par exemple 2 ou 1,5.")
        await i.response.edit_message(view=VueCadeau(p.auteur, p.g, p.b, erreurs))


class VueCadeau(LayoutView):
    """Le panneau de création (seul l'auteur le voit) : l'aperçu exact, puis les réglages et « Lancer »."""

    def __init__(self, auteur, g, b: Brouillon, erreurs=()):
        super().__init__(timeout=1800)
        self.auteur, self.g, self.b = auteur, g, b
        fin = lire_duree(b.duree, _mur()) or int(_mur()) + 86400
        for x in composants_carte(b.comme_cadeau(fin), 0, apercu=True):
            self.add_item(x)
        qui = discord.ui.RoleSelect(placeholder="✅ Rôles autorisés (vide : tout le monde)", min_values=0,
                                    max_values=ROLES_MAX, default_values=[discord.Object(r) for r in b.roles])
        qui.callback = self._cb_roles
        pas = discord.ui.RoleSelect(placeholder="🚫 Rôles exclus (vide : personne)", min_values=0,
                                    max_values=ROLES_MAX, default_values=[discord.Object(r) for r in b.exclus])
        pas.callback = self._cb_exclus
        chanceux = discord.ui.RoleSelect(placeholder="Rôles chanceux ? Vide : aucun", min_values=0,
                                         max_values=ROLES_MAX,
                                         default_values=[discord.Object(r) for r in b.chance_roles])
        chanceux.callback = self._cb_chance
        conditions = []
        if b.msg_min:
            conditions.append(f"💬 {b.msg_min} messages")
        if b.voc_min:
            conditions.append(f"🔊 {duree_txt(b.voc_min)} en vocal")
        if b.inv_min:
            conditions.append(f"📨 {b.inv_min} invitation{'s' if b.inv_min > 1 else ''}")
        if b.anc_min:
            conditions.append(f"📅 {b.anc_min} jour{'s' if b.anc_min > 1 else ''} sur le serveur")
        modifier = Button(label="Modifier", style=discord.ButtonStyle.secondary, emoji="✏️")
        modifier.callback = self._cb_conditions
        logique = Button(label="ET : les deux" if b.logique == "et" else "OU : l'un ou l'autre",
                         style=discord.ButtonStyle.secondary, emoji="🔀", disabled=len(conditions) < 2)
        logique.callback = self._cb_logique
        mult = Button(label=f"×{_nombre(b.multiplicateur)}", style=discord.ButtonStyle.secondary, emoji="🍀")
        mult.callback = self._cb_mult
        lancer_b = Button(label="Lancer", style=discord.ButtonStyle.success, emoji="🚀", disabled=not b.lot)
        lancer_b.callback = self._cb_lancer
        lot = Button(label="Lot et durée", style=discord.ButtonStyle.primary, emoji="🎁")
        lot.callback = self._cb_lot
        mention = Button(label="Mention : @everyone" if b.mention == "everyone" else "Mention : personne",
                         style=discord.ButtonStyle.secondary, emoji="🔔" if b.mention else "🔕")
        mention.callback = self._cb_mention
        annuler_b = Button(label="Annuler", style=discord.ButtonStyle.secondary)
        annuler_b.callback = self._cb_annuler
        items = [discord.ui.TextDisplay("### ⚙️ Réglages · seul toi vois ce panneau\n**Qui peut participer** — "
                                        "les rôles autorisés, puis les rôles exclus"),
                 discord.ui.ActionRow(qui),
                 discord.ui.ActionRow(pas),
                 discord.ui.Section(discord.ui.TextDisplay(
                     "**📊 Conditions** — messages et vocal depuis le lancement ; invitations et ancienneté\n"
                     + (" · ".join(conditions) if conditions else "Aucune : il suffit de participer.")),
                     accessory=modifier),
                 discord.ui.Section(discord.ui.TextDisplay(
                     "**🍀 Plus de chances** pour ces rôles"
                     + ("" if b.chance_roles else " — aucun choisi")), accessory=mult),
                 discord.ui.ActionRow(chanceux),
                 discord.ui.Separator(),
                 discord.ui.ActionRow(lancer_b, lot, logique, mention, annuler_b)]
        if erreurs:
            items.append(discord.ui.TextDisplay("\n".join(f"⚠️ {e}" for e in erreurs)))
        self.add_item(discord.ui.Container(*items, accent_color=Palette.NEUTRAL))

    async def interaction_check(self, i):
        return i.user.id == self.auteur.id

    async def _reafficher(self, i, erreurs=()):
        await i.response.edit_message(view=VueCadeau(self.auteur, self.g, self.b, erreurs))

    async def _cb_roles(self, i):
        self.b.roles = [int(v) for v in (i.data or {}).get("values") or []][:ROLES_MAX]
        await self._reafficher(i)

    async def _cb_exclus(self, i):
        self.b.exclus = [int(v) for v in (i.data or {}).get("values") or []][:ROLES_MAX]
        await self._reafficher(i)

    async def _cb_chance(self, i):
        self.b.chance_roles = [int(v) for v in (i.data or {}).get("values") or []][:ROLES_MAX]
        await self._reafficher(i)

    async def _cb_conditions(self, i):
        await i.response.send_modal(FormulaireConditions(self))

    async def _cb_logique(self, i):
        self.b.logique = "ou" if self.b.logique == "et" else "et"
        await self._reafficher(i)

    async def _cb_mult(self, i):
        await i.response.send_modal(FormulaireChance(self))

    async def _cb_lot(self, i):
        await i.response.send_modal(FormulaireLot(self))

    async def _cb_mention(self, i):
        self.b.mention = "" if self.b.mention else "everyone"
        await self._reafficher(i)

    async def _cb_annuler(self, i):
        await i.response.edit_message(view=_vue_message("Cadeau abandonné : rien n'a été publié."), attachments=[])

    async def _cb_lancer(self, i):
        await i.response.defer()
        lien, erreur = await lancer(self.g, self.auteur, self.b)
        if erreur:
            return await i.edit_original_response(view=VueCadeau(self.auteur, self.g, self.b, [erreur]))
        await i.edit_original_response(view=_vue_message(f"✅ Cadeau lancé : {lien}", Palette.SUCCESS), attachments=[])


# ═══════════════════════════════════════════════════════════════════════════════
#  La gestion (📋logs → 🎁 Cadeaux) : nouveau, en cours, terminés
# ═══════════════════════════════════════════════════════════════════════════════

def _brouillon_neuf(g) -> Brouillon:
    """Les boosters ×2, proposés d'office (« par exemple, ceux qui offrent le nitro ») : on les retire d'un clic."""
    booster = getattr(g, "premium_subscriber_role", None)
    return Brouillon(chance_roles=[booster.id] if booster is not None else [])


async def ouvrir_composeur(i) -> None:
    """/giveaway lancer : le panneau de création, tout de suite (les boosters ×2 proposés d'office)."""
    g = i.guild
    if g is None or not await _autorise(g, i.user):
        return await i.response.send_message("Réservé au fondateur et à la direction.", ephemeral=True)
    await i.response.send_message(view=VueCadeau(i.user, g, _brouillon_neuf(g)), ephemeral=True)


async def ouvrir_gestion(i) -> None:
    g = i.guild
    if g is None or not await _autorise(g, i.user):
        return await i.response.send_message("Réservé au fondateur et à la direction.", ephemeral=True)
    await i.response.send_message(view=await vue_gestion(i.user, g), ephemeral=True)


async def vue_gestion(auteur, g) -> LayoutView:
    v = LayoutView(timeout=1800)
    salon = await salon_cadeaux(g)
    nouveau = Button(label="Nouveau cadeau", style=discord.ButtonStyle.success, emoji="➕")

    async def _nouveau(i):
        await i.response.edit_message(view=VueCadeau(auteur, g, _brouillon_neuf(g)))
    nouveau.callback = _nouveau
    items = [visuels.bandeau("cadeaux", "Cadeaux"),
             discord.ui.TextDisplay("### 🎁 Les cadeaux\nLance un cadeau avec ses conditions, suis ceux en cours, "
                                    "refais un tirage. " + (f"Ils partent dans {salon.mention}." if salon is not None
                                                            else "Le salon sera recréé au premier cadeau.")),
             discord.ui.ActionRow(nouveau)]
    liste = await recents(g.id, 8)
    if liste:
        items.append(discord.ui.Separator())
    for c in liste:
        if c["statut"] == "actif":
            ligne = f"**{c['lot']}** — fin <t:{c['fin']}:R> · 🎟️ {await nb_inscrits(c['id'])} inscrit(s)"
        elif c["statut"] == "fini":
            gagnants = (c["resultat"] or {}).get("gagnants") or []
            ligne = f"**{c['lot']}** — terminé · " + (", ".join(f"<@{u}>" for u in gagnants) or "pas de gagnant")
        else:
            ligne = f"**{c['lot']}** — annulé"
        b = Button(label="Gérer", style=discord.ButtonStyle.secondary, disabled=c["statut"] == "annule")
        b.callback = _gerer(auteur, g, c["id"])
        items.append(discord.ui.Section(discord.ui.TextDisplay(ligne), accessory=b))
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(COULEUR)))
    return v


def _gerer(auteur, g, cid):
    async def _cb(i):
        if i.user.id != auteur.id:
            return await i.response.send_message("Ce panneau n'est pas le tien.", ephemeral=True)
        await i.response.edit_message(view=await vue_un_cadeau(auteur, g, cid))
    return _cb


async def vue_un_cadeau(auteur, g, cid: int, *, confirmer: str = "", note: str = "") -> LayoutView:
    """Un cadeau : en cours → tirer maintenant, annuler ; terminé → nouveau tirage. Les gestes sans retour
    demandent une confirmation (en bas)."""
    c = await charger(cid)
    v = LayoutView(timeout=1800)
    if c is None:
        v.add_item(discord.ui.Container(discord.ui.TextDisplay("Ce cadeau n'existe plus."),
                                        accent_color=Palette.NEUTRAL))
        return v
    lien = f"https://discord.com/channels/{g.id}/{c['salon_id']}/{c['message_id']}"
    lignes = [f"### 🎁 {c['lot']}", f"[Voir la carte]({lien}) · {c['gagnants']} gagnant(s)"]
    if c["statut"] == "actif":
        lignes.append(f"⏳ Fin <t:{c['fin']}:R> · 🎟️ {await nb_inscrits(cid)} inscrit(s)")
        lignes.append(texte_conditions(c))
    elif c["statut"] == "fini":
        r = c["resultat"] or {}
        lignes.append("🏆 " + (", ".join(f"<@{u}>" for u in r.get("gagnants") or []) or "pas de gagnant"))
        lignes.append(f"-# {r.get('inscrits', 0)} participant(s) · {r.get('eligibles_n', 0)} rempli(ssai)ent les "
                      "conditions")
    if note:
        lignes.append(note)
    boutons = []

    def bouton(label, style, action, emoji=None):
        b = Button(label=label, style=style, emoji=emoji)

        async def _cb(i):
            if i.user.id != auteur.id:
                return await i.response.send_message("Ce panneau n'est pas le tien.", ephemeral=True)
            await action(i)
        b.callback = _cb
        boutons.append(b)

    async def retour(i):
        await i.response.edit_message(view=await vue_gestion(auteur, g))

    if confirmer:
        async def oui(i):
            await i.response.defer()
            if confirmer == "tirer":
                fait = await terminer(g, cid, par=auteur.id)
                note_ = "✅ Tirage fait." if fait is not None else "Ce cadeau n'était plus en cours."
            else:
                note_ = "✅ Cadeau annulé." if await annuler(g, cid, par=auteur.id) else "Ce cadeau n'était plus en cours."
            await i.edit_original_response(view=await vue_un_cadeau(auteur, g, cid, note=note_))

        async def non(i):
            await i.response.edit_message(view=await vue_un_cadeau(auteur, g, cid))
        quoi = "Tirer au sort maintenant" if confirmer == "tirer" else "Annuler ce cadeau (sans gagnant)"
        lignes.append(f"**{quoi} ?** C'est définitif.")
        bouton("Oui", discord.ButtonStyle.danger if confirmer == "annuler" else discord.ButtonStyle.success, oui)
        bouton("Non", discord.ButtonStyle.secondary, non)
    elif c["statut"] == "actif":
        async def tirer_cb(i):
            await i.response.edit_message(view=await vue_un_cadeau(auteur, g, cid, confirmer="tirer"))

        async def annuler_cb(i):
            await i.response.edit_message(view=await vue_un_cadeau(auteur, g, cid, confirmer="annuler"))
        async def participants_cb(i):
            await montrer_participants(i, cid, 0, nouveau=True)
        bouton("Tirer maintenant", discord.ButtonStyle.success, tirer_cb, "🎲")
        bouton("Participants", discord.ButtonStyle.secondary, participants_cb, "👥")
        bouton("Annuler le cadeau", discord.ButtonStyle.danger, annuler_cb)
        bouton("Retour", discord.ButtonStyle.secondary, retour)
    else:
        async def relancer_cb(i):
            await i.response.defer()
            nouveau, raison = await relancer(g, cid, par=auteur.id)
            note_ = f"✅ Nouveau gagnant : <@{nouveau}>." if nouveau else f"⚠️ {raison}"
            await i.edit_original_response(view=await vue_un_cadeau(auteur, g, cid, note=note_))
        if c["statut"] == "fini":
            bouton("Nouveau tirage (+1 gagnant)", discord.ButtonStyle.primary, relancer_cb, "🔁")
        bouton("Retour", discord.ButtonStyle.secondary, retour)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(lignes)), discord.ui.ActionRow(*boutons),
                                    accent_color=discord.Color(COULEUR)))
    return v
