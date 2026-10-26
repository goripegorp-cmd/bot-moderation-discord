"""securite_site.py — la sécurité du site, et ce que le site fait sur Discord (26/10/2026).

« Protège le site contre tout type d'attaque possible […] il faut aussi qu'il y ait une protection intégrée au bot qui
relève aussi les activités qui sont transmises par le site jusqu'au serveur Discord. »

LES DÉCISIONS DU FONDATEUR (26/10/2026) — « faut pas que tu fasses non plus une fausse alerte » :
  · Ce que font le fondateur et la direction n'est JAMAIS alerté (ni « nouvel appareil », ni rafale d'actions) : c'est
    VISIBLE dans la rubrique « Sécurité » du site (sessions, appareils, dernières actions).
  · Un refus ordinaire (lien expiré, robot qui sonde les adresses, membre curieux) : un compteur, ou une ligne du journal.
  · Une ALERTE dans « 📋logs », regroupée (jamais de rafale), seulement pour un signal FORT :
      a. une action privilégiée du site qui ABOUTIT pour quelqu'un hors de la tête (cela ne doit jamais arriver) ;
      b. une permission dangereuse donnée sur le serveur (Administrateur, Gérer le serveur, Gérer les rôles, Bannir,
         Expulser, Gérer les webhooks) par quelqu'un d'autre que la tête ou le bot, lue dans le journal d'audit.
  · Jamais de retrait automatique de permission ni de rôle ; jamais de blocage de la tête.
  · Le bouton d'urgence, simple : « Fermer toutes les autres sessions » (la sienne reste ouverte).

CE QUE CE MODULE TIENT
  · La trace de CHAQUE écriture du site (`tableau_actions`), écrite à la porte même (`tableau.action`,
    `tableau._executer`) : aucune action ne peut y échapper, qu'elle réussisse ou non — qui, quoi, quand, le résultat,
    depuis quel appareil.
  · Les appareils déjà vus de chaque personne (`tableau_appareils`, 180 jours) : « nouvel appareil » se lit sur la session.
  · Les compteurs des refus (en mémoire, depuis le démarrage).
  · Les alertes fortes : la première tout de suite, les suivantes regroupées en UNE carte toutes les 15 minutes au plus.
  · Le journal d'audit de Discord lu à chaque entrée (`sur_entree_audit`) et la liste de qui détient une permission
    dangereuse, par quel rôle (lecture seule).
  · La rubrique « Sécurité » (`api/securite`, `api/securite/fermer_autres`), branchée par tableau.py.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import ipaddress
import re
import time

import owner_ids
import registre

PERMISSIONS = (("administrator", "Administrateur"), ("manage_guild", "Gérer le serveur"),
               ("manage_roles", "Gérer les rôles"), ("ban_members", "Bannir"), ("kick_members", "Expulser"),
               ("manage_webhooks", "Gérer les webhooks"))
#  Sur un salon, seules deux d'entre elles se donnent (« Gérer les permissions » = manage_roles).
PERMISSIONS_SALON = ("manage_roles", "manage_webhooks")
ALERTE_DELAI = 900            # s : une carte par sorte et par serveur au plus ; ce qui suit part regroupé à la fin
ALERTE_LIGNES = 12            # lignes au plus dans une carte regroupée (le reste : « et N autres »)
ACTIONS_GARDEES = 2000        # lignes de la trace par serveur
ACTIONS_MONTREES = 60         # dans la rubrique
APPAREILS_JOURS = 180
NOUVEAU_S = 120               # une session ouverte dans les 2 min qui suivent la première vue de son appareil : « nouvel appareil »
#  Les refus comptés (rien n'est alerté) : leur libellé dans la rubrique.
REFUS = {"lien": "Liens refusés (expirés, déjà servis ou faux)",
         "cookie": "Cookies de session faux ou inconnus",
         "hors_portee": "Pages de la direction demandées par une autre session",
         "fichier": "Fichiers du site refusés (sans la bonne session)",
         "origine": "Écritures venues d'un autre site, refusées",
         "cadence": "Requêtes au-delà de la cadence",
         "websocket": "Connexions en direct refusées"}
#  Le journal du site : les lignes que la rubrique montre (alertes fortes, et faits seulement visibles).
TYPES_ALERTES = ("securite.permission", "securite.hors_tete")
TYPES_FAITS = ("site.rafale", "site.hors_portee", "site.suspendu", "site.hors_tete")
LECTURE_JOURNAL_S = 600       # une session hors de la tête qui lit la Capitainerie : une ligne par 10 minutes au plus

#  La session de la requête en cours (posée par `tableau._verifier`) : {"emp", "u", "appareil"}.
SESSION: contextvars.ContextVar = contextvars.ContextVar("session_site", default=None)

_get_db = None
_envoyer = None               # async (g, titre, texte) → bool : la carte d'alerte dans « 📋logs » (bot.py)
_log = print
_compteurs: dict = {}
_depuis = time.time()
_alertes: dict = {}           # (serveur, sorte) → {"dernier": t, "attente": [lignes], "n": int, "tache": Task | None}
_lectures: dict = {}          # empreinte de session → heure de la dernière ligne « lecture hors de la tête »
_taches: set = set()
_ecritures = 0
_ABSENT = object()


def setup(*, get_db=_ABSENT, envoyer=_ABSENT, log=_ABSENT) -> None:
    """Ne change que ce qui est donné : tableau.py branche la base, bot.py la carte d'alerte."""
    global _get_db, _envoyer, _log
    if get_db is not _ABSENT:
        _get_db = get_db
    if envoyer is not _ABSENT:
        _envoyer = envoyer
    if log is not _ABSENT:
        _log = log or print


def remettre_a_zero() -> None:
    """Tests : compteurs et alertes en attente oubliés (les tâches en cours sont annulées)."""
    global _depuis
    _compteurs.clear()
    for e in _alertes.values():
        if e.get("tache") is not None and not e["tache"].done():
            e["tache"].cancel()
    _alertes.clear()
    _lectures.clear()
    _depuis = time.time()


async def creer_tables(db) -> None:
    """Appelé par `tableau.init_db` (même connexion)."""
    await db.execute("CREATE TABLE IF NOT EXISTS tableau_actions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                     " guild_id INTEGER NOT NULL, quand INTEGER NOT NULL, user_id INTEGER NOT NULL, quoi TEXT NOT NULL,"
                     " statut INTEGER NOT NULL, texte TEXT NOT NULL DEFAULT '', appareil TEXT NOT NULL DEFAULT '')")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_tableau_actions ON tableau_actions(guild_id, id)")
    await db.execute("CREATE TABLE IF NOT EXISTS tableau_appareils (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,"
                     " cle TEXT NOT NULL, appareil TEXT NOT NULL DEFAULT '', adresse TEXT NOT NULL DEFAULT '',"
                     " premier INTEGER NOT NULL, dernier INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id, cle))")


# ─── L'appareil et l'adresse approximative ──────────────────────────────────

def appareil(ua) -> str:
    """« Windows · Edge », « iPhone · Safari »… depuis l'en-tête User-Agent (rien d'autre n'est gardé de lui)."""
    ua = str(ua or "")[:512]
    systeme = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android" if "Android" in ua
               else "Windows" if "Windows" in ua else "Mac" if ("Macintosh" in ua or "Mac OS X" in ua)
               else "ChromeOS" if "CrOS" in ua else "Linux" if "Linux" in ua else "")
    nav = ("Discord" if "discord/" in ua.lower() else "Edge" if re.search(r"Edg(A|iOS)?/", ua) else "Opera" if "OPR/" in ua
           else "Firefox" if ("Firefox/" in ua or "FxiOS/" in ua) else "Chrome" if ("Chrome/" in ua or "CriOS/" in ua)
           else "Safari" if "Safari/" in ua else "")
    return " · ".join(x for x in (systeme, nav) if x) or "Appareil inconnu"


def adresse_approx(ip) -> str:
    """L'adresse, tronquée : « 86.245.12.x » (IPv4), « 2a01:cb00:1234:: /48 » (IPv6) — jamais l'adresse entière."""
    try:
        a = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return ""
    if a.version == 6 and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    if a.version == 4:
        return ".".join(str(a).split(".")[:3]) + ".x"
    return str(ipaddress.ip_network(f"{a}/48", strict=False).network_address) + " /48"


def cle_appareil(app: str, adr: str) -> str:
    return hashlib.sha256(f"{app}\x00{adr}".encode("utf-8")).hexdigest()[:16]


async def noter_appareil(db, guild_id: int, user_id: int, app: str, adr: str, t: float) -> bool:
    """Cet appareil (et cette adresse approximative) pour cette personne : True s'il n'avait jamais été vu. Même
    connexion que l'ouverture de la session ; les appareils plus vus depuis 180 jours sont oubliés au passage."""
    t = int(t)
    cle = cle_appareil(app, adr)
    async with db.execute("SELECT premier FROM tableau_appareils WHERE guild_id=? AND user_id=? AND cle=?",
                          (int(guild_id), int(user_id), cle)) as cur:
        deja = await cur.fetchone()
    if deja is None:
        await db.execute("INSERT OR IGNORE INTO tableau_appareils (guild_id, user_id, cle, appareil, adresse, premier,"
                         " dernier) VALUES (?,?,?,?,?,?,?)", (int(guild_id), int(user_id), cle, app[:80], adr[:60], t, t))
    else:
        await db.execute("UPDATE tableau_appareils SET dernier=? WHERE guild_id=? AND user_id=? AND cle=?",
                         (t, int(guild_id), int(user_id), cle))
    await db.execute("DELETE FROM tableau_appareils WHERE dernier < ?", (t - APPAREILS_JOURS * 86400,))
    return deja is None


# ─── Les refus : des compteurs, jamais une alerte ───────────────────────────

def compter(sorte: str) -> None:
    if sorte in REFUS:
        _compteurs[sorte] = _compteurs.get(sorte, 0) + 1


def compteurs() -> dict:
    return {"depuis": int(_depuis), "refus": [{"cle": k, "libelle": v, "n": int(_compteurs.get(k, 0))}
                                              for k, v in REFUS.items()]}


# ─── La trace des écritures du site ─────────────────────────────────────────

async def noter_action(g, auteur, quoi: str, statut: int, texte: str = "") -> None:
    """Une écriture du site, appliquée (réussie ou non) : gardée. Ne lève jamais (la trace ne bloque pas l'action),
    mais son échec est journalisé."""
    global _ecritures
    if _get_db is None or g is None:
        return
    s = SESSION.get() or {}
    try:
        async with _get_db() as db:
            await db.execute("INSERT INTO tableau_actions (guild_id, quand, user_id, quoi, statut, texte, appareil)"
                             " VALUES (?,?,?,?,?,?,?)", (int(g.id), int(time.time()), int(getattr(auteur, "id", 0) or 0),
                                                        str(quoi)[:60], int(statut), str(texte or "")[:300],
                                                        str(s.get("appareil") or "")[:80]))
            _ecritures += 1
            if _ecritures % 50 == 0:
                await db.execute("DELETE FROM tableau_actions WHERE guild_id=? AND id <= (SELECT id FROM tableau_actions"
                                 " WHERE guild_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)",
                                 (int(g.id), int(g.id), ACTIONS_GARDEES))
            await db.commit()
    except Exception as ex:  # la trace manque ; l'action, elle, est faite — on le dit au journal du bot
        _log("[SECURITE][E1] trace d'une action du site non écrite")
        _log(f"[SECURITE][E1:DETAIL] {quoi} {type(ex).__name__} {ex}")


def texte_journal(journal, defaut: str) -> str:
    """La phrase d'une écriture (`_journal` d'une adresse du site), sinon `defaut`."""
    if isinstance(journal, dict):
        return str(journal.get("texte") or defaut)
    if isinstance(journal, str) and journal:
        return journal
    return defaut


async def lecture_hors_tete(g, membre, emp: str, chemin: str, t: float | None = None) -> None:
    """La porte de la direction a laissé LIRE quelqu'un hors de la tête (cela n'arrive jamais avec le bot tel qu'il est) :
    un fait du journal (Sécurité), visible dans la rubrique — une ligne par session et par 10 minutes, jamais une alerte
    (l'alerte est pour une action qui aboutit). Ne lève jamais."""
    t = float(t or time.time())
    if t - _lectures.get(emp, 0.0) < LECTURE_JOURNAL_S:
        return
    _lectures[emp] = t
    if len(_lectures) > 5000:
        for k in sorted(_lectures, key=_lectures.get)[:1000]:
            _lectures.pop(k, None)
    uid = int(getattr(membre, "id", 0) or 0)
    try:
        await registre.noter(int(getattr(g, "id", 0) or 0), "Sécurité", "site.hors_tete",
                             f"Capitainerie lue hors de la tête : {_nom(membre, str(uid))}", auteur_id=uid,
                             detail=str(chemin or "")[:120], gravite=1)
    except Exception as ex:  # le fait manque au journal ; la requête, elle, continue
        _log("[SECURITE][E5] lecture hors de la tête non notée")
        _log(f"[SECURITE][E5:DETAIL] {type(ex).__name__} {ex}")


# ─── Les alertes fortes, regroupées ─────────────────────────────────────────

async def signal_fort(g, sorte: str, titre: str, ligne: str, *, auteur_id: int = 0) -> None:
    """Un signal FORT (a. une action privilégiée hors de la tête, b. une permission dangereuse donnée hors de la tête) :
    une ligne au journal (Sécurité) et une carte dans « 📋logs ». La première part tout de suite ; celles qui suivent
    dans les ALERTE_DELAI secondes partent ensemble, en UNE carte, à la fin du délai. Ne lève jamais."""
    gid = int(getattr(g, "id", 0) or 0)
    e = _alertes.setdefault((gid, sorte), {"dernier": 0.0, "attente": [], "n": 0, "tache": None})
    t = time.time()
    if t - e["dernier"] >= ALERTE_DELAI and e["tache"] is None:
        e["dernier"] = t
        await _publier(g, sorte, titre, [ligne], 1, auteur_id)
        return
    e["n"] += 1
    if len(e["attente"]) < ALERTE_LIGNES:
        e["attente"].append(ligne)
    if e["tache"] is None:
        try:
            e["tache"] = asyncio.get_running_loop().create_task(_plus_tard(g, sorte, titre, max(0.0, e["dernier"] + ALERTE_DELAI - t)))
        except RuntimeError as ex:  # aucune boucle (appel hors du bot) : la ligne reste en attente
            _log("[SECURITE][E2] alerte regroupée non programmée")
            _log(f"[SECURITE][E2:DETAIL] {type(ex).__name__} {ex}")
            return
        _taches.add(e["tache"])
        e["tache"].add_done_callback(_taches.discard)


async def _plus_tard(g, sorte: str, titre: str, attente: float) -> None:
    try:
        await asyncio.sleep(attente)
    except asyncio.CancelledError:
        return
    e = _alertes.get((int(getattr(g, "id", 0) or 0), sorte))
    if e is None:
        return
    lignes, n = e["attente"], e["n"]
    e.update(attente=[], n=0, tache=None, dernier=time.time())
    if n:
        await _publier(g, sorte, titre, lignes, n, 0)


async def _publier(g, sorte: str, titre: str, lignes: list, n: int, auteur_id: int) -> None:
    gid = int(getattr(g, "id", 0) or 0)
    texte = "\n".join(f"· {x}" for x in lignes) + (f"\n· … et {n - len(lignes)} de plus" if n > len(lignes) else "")
    try:
        await registre.noter(gid, "Sécurité", f"securite.{sorte}"[:40],
                             lignes[0] if n == 1 else f"{titre} : {n} signaux regroupés",
                             auteur_id=int(auteur_id or 0), detail=texte[:600], gravite=2)
    except Exception as ex:  # le journal manque ; la carte part quand même
        _log("[SECURITE][E3] alerte non notée au journal")
        _log(f"[SECURITE][E3:DETAIL] {type(ex).__name__} {ex}")
    if _envoyer is None:
        return
    try:
        await _envoyer(g, titre, texte)
    except Exception as ex:  # la carte n'est pas partie : la ligne du journal reste, visible dans « Sécurité »
        _log("[SECURITE][E4] alerte non envoyée")
        _log(f"[SECURITE][E4:DETAIL] {type(ex).__name__} {ex}")


# ─── Les permissions dangereuses : qui les a, qui les donne ─────────────────

def _perms(p, noms=None) -> list:
    return [lib for attr, lib in PERMISSIONS if (noms is None or attr in noms) and bool(getattr(p, attr, False))]


def _ajoutees(avant, apres, noms=None) -> list:
    """Les permissions dangereuses présentes dans `apres` et absentes de `avant` (deux `discord.Permissions` ou None)."""
    deja = set(_perms(avant, noms)) if avant is not None else set()
    return [x for x in (_perms(apres, noms) if apres is not None else []) if x not in deja]


def _nom(objet, defaut: str = "?") -> str:
    return str(getattr(objet, "display_name", None) or getattr(objet, "name", None) or defaut)[:60]


def examiner_entree(entry, tete, bot_id: int = 0):
    """La phrase d'une entrée du journal d'audit qui DONNE une permission dangereuse, faite par quelqu'un hors de la tête
    et du bot — None sinon (toute autre entrée, ou faite par la tête ou le bot)."""
    import discord
    uid = int(getattr(entry, "user_id", 0) or 0)
    if not uid or uid in set(int(x) for x in tete) or uid == int(bot_id or 0):
        return None
    A = discord.AuditLogAction
    g = entry.guild
    avant, apres = entry.changes.before, entry.changes.after
    auteur = getattr(entry, "user", None) or g.get_member(uid)
    qui = f"{_nom(auteur, str(uid))} ({uid})"
    if entry.action in (A.role_update, A.role_create):
        perms = _ajoutees(getattr(avant, "permissions", None), getattr(apres, "permissions", None))
        if not perms:
            return None
        role = entry.target
        porteurs = len([m for m in getattr(role, "members", None) or [] if not getattr(m, "bot", False)])
        return (f"{qui} a donné « {', '.join(perms)} » au rôle {_nom(role)}"
                + (f" ({porteurs} membre(s) le portent)" if porteurs else "") + ".")
    if entry.action == A.member_role_update:
        cible = entry.target
        donnes = []
        for r in getattr(apres, "roles", None) or []:
            role = g.get_role(int(getattr(r, "id", 0) or 0)) or r
            perms = _perms(getattr(role, "permissions", None))
            if perms:
                donnes.append(f"{_nom(role)} ({', '.join(perms)})")
        if not donnes:
            return None
        return f"{qui} a donné le rôle {' et '.join(donnes)} à {_nom(cible, str(getattr(cible, 'id', '?')))}."
    if entry.action in (A.overwrite_create, A.overwrite_update):
        perms = _ajoutees(getattr(avant, "allow", None), getattr(apres, "allow", None), PERMISSIONS_SALON)
        if not perms:
            return None
        salon, pour = entry.target, getattr(entry, "extra", None)
        return f"{qui} a donné « {', '.join(perms)} » dans #{_nom(salon)} à {_nom(pour)}."
    return None


async def sur_entree_audit(entry, tete) -> str | None:
    """Une entrée du journal d'audit (bot.py, `on_audit_log_entry_create`) : une permission dangereuse donnée hors de la
    tête → un signal fort. Rend la phrase (ou None). Jamais rien de retiré ni de bloqué."""
    g = getattr(entry, "guild", None)
    me = getattr(g, "me", None)
    phrase = examiner_entree(entry, tete, int(getattr(me, "id", 0) or 0))
    if phrase:
        await signal_fort(g, "permission", "Une permission dangereuse a été donnée", phrase,
                          auteur_id=int(getattr(entry, "user_id", 0) or 0))
    return phrase


def porteurs(g) -> dict:
    """Qui détient une permission dangereuse, et par quel rôle (lecture seule, depuis le cache du bot)."""
    roles = []
    for r in sorted(getattr(g, "roles", None) or [], key=lambda x: -int(getattr(x, "position", 0) or 0)):
        perms = _perms(getattr(r, "permissions", None))
        if not perms:
            continue
        membres = list(getattr(r, "members", None) or [])
        humains = [m for m in membres if not getattr(m, "bot", False)]
        couleur = getattr(getattr(r, "colour", None), "value", 0) or 0
        roles.append({"id": str(r.id), "nom": str(getattr(r, "name", "") or "")[:80], "couleur": f"#{couleur:06x}" if couleur else "",
                      "permissions": perms, "membres": [str(m.id) for m in humains[:40]], "n": len(humains),
                      "bots": len(membres) - len(humains), "gere": bool(getattr(r, "managed", False)),
                      "tous": bool(getattr(r, "is_default", lambda: False)())})
    me = getattr(g, "me", None)
    droits = getattr(me, "guild_permissions", None)
    return {"roles": roles, "proprietaire": str(getattr(g, "owner_id", "") or ""),
            "audit": bool(getattr(droits, "view_audit_log", False))}


# ─── La rubrique « Sécurité » (`api/securite`) ──────────────────────────────

async def route_securite(g, auteur, requete, corps):
    """`GET api/securite` : les sessions du site (appareil, adresse approximative — les siennes, et toutes pour le
    fondateur —, dernière activité), les dernières écritures du site, les refus comptés, les alertes et faits notés, qui
    détient une permission dangereuse."""
    import tableau
    t = int(time.time())
    moi = (SESSION.get() or {}).get("emp", "")
    fondateur = owner_ids.is_super_owner(getattr(auteur, "id", 0))
    qui = tableau._Personnes(g)
    async with tableau._get_db() as db:
        async with db.execute("SELECT empreinte, user_id, cree_le, expire_le, portee, appareil, adresse, vu_le"
                              " FROM tableau_sessions WHERE guild_id=? AND expire_le>=? ORDER BY vu_le DESC, cree_le DESC",
                              (int(g.id), t)) as cur:
            lignes = await cur.fetchall()
        async with db.execute("SELECT user_id, cle, premier FROM tableau_appareils WHERE guild_id=?", (int(g.id),)) as cur:
            vus = {(int(u), str(c)): int(p) for u, c, p in await cur.fetchall()}
        async with db.execute("SELECT quand, user_id, quoi, statut, texte, appareil FROM tableau_actions WHERE guild_id=?"
                              " ORDER BY id DESC LIMIT ?", (int(g.id), ACTIONS_MONTREES)) as cur:
            actions = [{"quand": int(q), "qui": qui(int(u)), "quoi": str(quoi), "statut": int(s), "texte": str(tx or ""),
                        "appareil": str(ap or "")} for q, u, quoi, s, tx, ap in await cur.fetchall()]
    sessions, equipage = [], 0
    for emp, uid, cree, fin, portee, app, adr, vu in lignes:
        if str(portee or "") != "tout":
            equipage += 1
            continue
        uid, app, adr = int(uid), str(app or ""), str(adr or "")
        premier = vus.get((uid, cle_appareil(app, adr))) if app else None
        voit = fondateur or uid == getattr(auteur, "id", 0)
        sessions.append({"id": str(emp)[:12], "qui": qui(uid), "moi": emp == moi, "appareil": app or "Appareil inconnu",
                         "adresse": adr if voit else "", "ouverte": int(cree or 0), "vue": int(vu or cree or 0),
                         "fin": int(fin or 0),
                         "nouveau": bool(premier is not None and int(cree or 0) - NOUVEAU_S <= premier)})
    evenements = []
    for r in await registre.lire(g.id, 300, categorie="Sécurité"):
        if r["type"] in TYPES_ALERTES or r["type"] in TYPES_FAITS:
            evenements.append({"quand": r["quand"], "type": r["type"], "alerte": r["type"] in TYPES_ALERTES,
                               "texte": r["texte"], "detail": r["detail"], "qui": qui(r["auteur_id"]) if r["auteur_id"] else ""})
        if len(evenements) >= 40:
            break
    perms = porteurs(g)
    for role in perms["roles"]:
        for uid in role["membres"]:
            qui(int(uid))
    if perms["proprietaire"].isdigit():
        qui(int(perms["proprietaire"]))
    return 200, {"sessions": sessions, "equipage": equipage, "fondateur": fondateur, "actions": actions,
                 "evenements": evenements, **compteurs(), "permissions": perms, "personnes": dict(qui)}


async def route_fermer_autres(g, auteur, requete, corps):
    """`POST api/securite/fermer_autres` : le bouton d'urgence. Toutes les AUTRES sessions du site de la direction sont
    fermées — celles de tout le monde pour le fondateur, les siennes pour la direction ; la sienne reste ouverte."""
    import tableau
    moi = (SESSION.get() or {}).get("emp", "")
    if not moi:
        return 400, {"erreur": "Session introuvable."}
    fondateur = owner_ids.is_super_owner(getattr(auteur, "id", 0))
    async with tableau._get_db() as db:
        if fondateur:
            async with db.execute("SELECT empreinte FROM tableau_sessions WHERE guild_id=? AND portee='tout'"
                                  " AND empreinte != ?", (int(g.id), moi)) as cur:
                fermees = [str(r[0]) for r in await cur.fetchall()]
        else:
            async with db.execute("SELECT empreinte FROM tableau_sessions WHERE user_id=? AND portee='tout'"
                                  " AND empreinte != ?", (int(auteur.id), moi)) as cur:
                fermees = [str(r[0]) for r in await cur.fetchall()]
        if fermees:
            await db.execute(f"DELETE FROM tableau_sessions WHERE empreinte IN ({','.join('?' * len(fermees))})",
                             tuple(fermees))
            await db.commit()
    for emp in fermees:
        tableau._sessions.pop(emp, None)   # coupées à la requête suivante ; le direct les coupe à sa ronde (5 s)
    n = len(fermees)
    return 200, {"ok": True, "fermees": n,
                 "_journal": {"texte": ("Toutes les autres sessions du site fermées : " + str(n)) if n
                              else "Aucune autre session ouverte"}}


ROUTES_INTERNES = {
    "securite": {"methode": "GET", "fn": route_securite},
    "securite/fermer_autres": {"methode": "POST", "fn": route_fermer_autres, "ecriture": True, "corps_max": 1024},
}
