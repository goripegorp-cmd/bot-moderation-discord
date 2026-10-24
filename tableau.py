"""tableau.py — le site du staff, servi par le bot (19/10/2026).

« Pas des .txt : un vrai site interactif, ultra bien fait » ; « plus de logs sur Discord, tout
sur le site, traduit par personne » ; « des zones par personne… qu'on évite de scroller
indéfiniment » ; « direction et fondateur : mis à part, pas pris pour les stats » ; « renforce
l'infrastructure du site, qu'il soit impeccable : quelqu'un qui n'a pas les accès ne l'a pas du
tout ».

L'ACCÈS
  · Les deux comptes « à la tête » (TETE_IDS : le fondateur et la direction), par identifiant, et
    personne d'autre — 24/10/2026 : le propriétaire d'un autre serveur où se trouve le bot y entrait.
  · Le bouton du salon « 📋logs » donne un lien PERSONNEL, signé, valable 24 h et À USAGE UNIQUE.
    Ouvert une fois, il devient une session (cookie HttpOnly, Secure, SameSite) et disparaît de la
    barre d'adresse : copié, photographié ou retrouvé dans l'historique, il ne sert plus à rien.
  · Chaque requête revérifie : session valide (relue en base au moins chaque minute : fermée
    ailleurs, elle est coupée), personne toujours sur le serveur et à la tête, pas suspendue.
    « Fermer toutes mes sessions » (pied de page) déconnecte tous ses navigateurs d'un coup.
  · Agir : les mêmes, revérifiés à chaque action. Trop d'actions graves en peu de temps — le signe
    d'un compte volé — est signalé au fondateur dans « 📋logs » (la tête n'est jamais suspendue ;
    tout autre compte le serait une heure).
  · Défenses : CSP à nonce (aucun script injecté ne s'exécute), en-têtes stricts, origine vérifiée
    sur les écritures (déconnexion comprise), cadence limitée par session et par adresse (faux liens
    et faux cookies : un cookie mal formé ne touche jamais la base), rien en cache, rien d'indexé.

LES DONNÉES
  Lues en direct dans la base du bot. Chaque réponse porte une empreinte (ETag) : la page qui se
  rafraîchit ne retélécharge rien quand rien n'a changé ; la version de la page fait recharger
  celle qui est périmée.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # sans base de fuseaux : l'heure UTC
    PARIS = timezone.utc

import discord

import annonces
import casier
import clan
import entraide
import owner_ids
import questions
import recrutements
import registre
import rellseas_panneau
import sondages
import suggestions
import transcript_store
import vigilance

DUREE = 24 * 3600
ESPACE = "/tableau/espace"
COOKIE = "__Host-tableau"
LIMITE_REQUETES = 240          # par minute et par session
LIMITE_ESSAIS = 30             # liens ou cookies invalides par adresse et par 10 minutes
RELIRE = 60                    # s : une session gardée en mémoire est relue en base au-delà
FORMAT_SESSION = re.compile(r"[A-Za-z0-9_-]{43}")  # ce que donne secrets.token_urlsafe(32)
LIMITES_GRAVES = {"exclusion": 5, "roles": 25, "casier": 10, "rappels": 50}  # par 10 minutes et par personne
BLOCAGE = 3600
PAGE_BRUTE = (Path(__file__).resolve().parent / "tableau_page.html").read_text(encoding="utf-8")
VERSION = hashlib.sha256(PAGE_BRUTE.encode()).hexdigest()[:12]
PAGE = PAGE_BRUTE.replace("__VERSION__", VERSION)


def _message(titre: str, texte: str) -> str:
    return ("<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{titre}</title><body style='margin:0;min-height:100vh;display:grid;place-items:center;"
            "background:#05070d;color:#e8eef8;font-family:system-ui,Segoe UI,sans-serif;text-align:center;"
            f"padding:24px'><div><h1 style='font-size:22px'>{titre}</h1><p style='color:#a7b4c8;max-width:460px'>"
            f"{texte}</p></div></body></html>")


EXPIRE = _message("Ce lien n'est plus valable",
                  "Demande un nouveau lien dans Discord : salon <b>📋logs</b> → <b>Ouvrir le tableau de bord</b>.")
DEJA = _message("Ce lien a déjà servi",
                "Chaque lien ne s'ouvre qu'une fois. Demande-en un nouveau dans Discord : salon <b>📋logs</b> → "
                "<b>Ouvrir le tableau de bord</b>.")
TROP = _message("Trop d'essais", "Réessaie dans quelques minutes.")
ENTETES = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    #  24/10/2026 (revue) : `*.discordapp.net` couvre media.discordapp.net ET le relais images-ext-* — les images
    #  d'encadré des tickets passent désormais par lui (l'IP du lecteur ne part plus chez l'hébergeur d'origine).
    "Content-Security-Policy": ("default-src 'none'; img-src 'self' https://cdn.discordapp.com "
                                "https://*.discordapp.net data:; media-src 'self' https://cdn.discordapp.com "
                                "https://*.discordapp.net; style-src 'unsafe-inline'; "
                                "script-src 'none'; connect-src 'self'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
}

_cle = b""
_base = ""
_bot = None
_radie = "🚫 Radié"
_cfg = _get_db = _mesurer_groupe = _autorise_membre = _direction = _alerte_securite = _mis_a_part = None
_tete: frozenset = frozenset()
_alertes_tete: dict = {}
_actions: dict = {}
_cadence: dict = {}
_sessions: dict = {}
_requetes: dict = {}
_essais: dict = {}
_graves: dict = {}
_blocages: dict = {}

#  Le casier mélange les sanctions décidées (staff ou escalade) et les détections du bot.
SANCTIONS = {"warn": "Avertissement", "mute": "Mute", "kick": "Expulsion", "ban": "Bannissement"}
DETECTIONS = {"insulte": "Insulte", "menace": "Menace", "discrimination": "Discrimination",
              "haine": "Haine", "incitation": "Incitation", "harcelement": "Harcèlement",
              "grooming": "Protection des mineurs", "protection": "Filtre automatique"}
GROUPES = {"warn": "Avertissements", "mute": "Mutes", "kick": "Expulsions et bans",
           "ban": "Expulsions et bans"}
MEMBRES_CASIER = 250   # cartes « par membre » envoyées à la page (les plus récents)
LISTE_PAR_MEMBRE = 12  # entrées par carte ; la fiche complète vient de /membre
EXPORT_MAX = 20000
PURGES = [("sessions du site", "DELETE FROM tableau_sessions WHERE expire_le < ?", 1, "unix"),
          ("liens du site", "DELETE FROM tableau_jetons WHERE expire_le < ?", 1, "unix"),
          ("suspensions du site", "DELETE FROM tableau_blocages WHERE jusqu < ?", 1, "unix")]
_cache: dict = {}
_log = print


def setup(*, bot, cle: str, base_url, cfg, get_db, mesurer_groupe, autorise_membre, radie=None,
          direction=None, mis_a_part=None, tete=(), actions=None, alerte_securite=None, conversation=None,
          log=None):
    """`autorise_membre(g, membre, c)` → qui entre sur le site ; `direction(g, membre, c)` → qui agit ;
    `mis_a_part(g, membre, c)` → hors statistiques et intouchable (par défaut : `direction`) ; `tete` :
    les identifiants « à la tête » (« c'est ceux-là et uniquement eux »), jamais suspendus ;
    `actions` : {nom: async (g, auteur, données) → (ok, message)} ; `alerte_securite(g, membre,
    texte, suspendu=True)` : prévient dans « 📋logs » ; `conversation(g, ticket)` → toute la conversation
    d'un ticket (ouvert : en direct ; fermé : le transcript enregistré)."""
    global _bot, _cle, _base, _cfg, _get_db, _mesurer_groupe, _autorise_membre, _log, _radie
    global _direction, _actions, _alerte_securite, _mis_a_part, _tete, _conversation
    _conversation = conversation
    _direction, _actions = direction, dict(actions or {})
    _mis_a_part, _tete = mis_a_part or direction, frozenset(int(x) for x in tete)
    _bot, _cle, _base = bot, cle.encode(), (base_url or "").rstrip("/")
    _radie = radie or _radie
    _cfg, _get_db, _mesurer_groupe, _autorise_membre = cfg, get_db, mesurer_groupe, autorise_membre
    _alerte_securite = alerte_securite
    _log = log or print
    for d in (_sessions, _requetes, _essais, _graves, _blocages, _cadence, _cache):
        d.clear()


async def init_db():
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_sessions (empreinte TEXT PRIMARY KEY, guild_id INTEGER,"
                         " user_id INTEGER, cree_le INTEGER, expire_le INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_jetons (nonce TEXT PRIMARY KEY, expire_le INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_blocages (guild_id INTEGER, user_id INTEGER, jusqu INTEGER,"
                         " raison TEXT, PRIMARY KEY (guild_id, user_id))")
        for uid in _tete:
            await db.execute("DELETE FROM tableau_blocages WHERE user_id=?", (uid,))
        await db.commit()


def a_la_tete(g, user_id: int) -> bool:
    """Le fondateur et la direction, par identifiant — eux seuls. 24/10/2026 : le propriétaire du
    serveur en faisait aussi partie ; celui d'un autre serveur où se trouve le bot n'est pas à la
    tête. `g` reste dans la signature pour les appelants."""
    return int(user_id) in _tete


# ─── Le lien personnel, à usage unique ──────────────────────────────────────

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jeton(guild_id: int, user_id: int, portee: str, maintenant: float | None = None, nonce: str | None = None) -> str:
    n = nonce or _b64(secrets.token_bytes(9))
    charge = f"{int(guild_id)}.{int(user_id)}.{portee}.{int((maintenant or time.time()) + DUREE)}.{n}"
    sig = hmac.new(_cle, charge.encode(), hashlib.sha256).digest()[:18]
    return f"{_b64(charge.encode())}.{_b64(sig)}"


def lire_jeton(j: str, maintenant: float | None = None) -> dict | None:
    try:
        a, b = str(j).split(".", 1)
        charge, sig = _unb64(a), _unb64(b)
        g, u, p, e, n = charge.decode().split(".")
        g, u, e = int(g), int(u), int(e)
    except (ValueError, UnicodeDecodeError):
        return None
    if not _cle or not hmac.compare_digest(sig, hmac.new(_cle, charge, hashlib.sha256).digest()[:18]):
        return None
    if e < (maintenant or time.time()) or p not in ("rs", "tout") or not n:
        return None
    return {"g": g, "u": u, "p": p, "e": e, "n": n}


async def suspendu(guild_id: int, user_id: int, maintenant: float | None = None) -> int:
    """L'heure de fin de suspension, ou 0. Jamais pour ceux qui sont à la tête."""
    t = maintenant or time.time()
    if a_la_tete(None, user_id):
        return 0
    jusqu = _blocages.get((guild_id, user_id))
    if jusqu is None and _get_db is not None:
        async with _get_db() as db:
            async with db.execute("SELECT jusqu FROM tableau_blocages WHERE guild_id=? AND user_id=?",
                                  (guild_id, user_id)) as cur:
                r = await cur.fetchone()
        jusqu = int(r[0]) if r else 0
        _blocages[(guild_id, user_id)] = jusqu
    return jusqu if jusqu and jusqu > t else 0


async def lien_pour(i, membre_id: int = 0) -> tuple[str | None, str]:
    """(lien personnel, "") — ou (None, la raison du refus, dite telle quelle à la personne).
    `membre_id` : le lien ouvre directement la fiche de ce membre."""
    if not _base or not _cle or i.guild is None:
        return None, "Le tableau de bord n'est pas joignable pour le moment."
    if _autorise_membre is None or not _autorise_membre(i.guild, i.user, await _cfg(i.guild.id)):
        return None, "Réservé au fondateur et à la direction."
    fin = await suspendu(i.guild.id, i.user.id)
    if fin:
        return None, (f"Ton accès au site est suspendu jusqu'à {_quand(fin)[-5:]} : trop d'actions graves "
                      "en peu de temps. Le fondateur est prévenu.")
    ancre = f"#membre={int(membre_id)}" if membre_id else ""
    return f"{_base}/tableau/{jeton(i.guild.id, i.user.id, 'tout')}{ancre}", ""


# ─── Les sessions ───────────────────────────────────────────────────────────

def _empreinte(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


async def _ouvrir_session(guild_id: int, user_id: int, expire: int, maintenant: float | None = None) -> str:
    sid = secrets.token_urlsafe(32)
    emp = _empreinte(sid)
    async with _get_db() as db:
        await db.execute("INSERT INTO tableau_sessions (empreinte, guild_id, user_id, cree_le, expire_le)"
                         " VALUES (?,?,?,?,?)", (emp, guild_id, user_id, int(maintenant or time.time()), int(expire)))
        await db.commit()
    _sessions[emp] = (guild_id, user_id, int(expire), float(maintenant or time.time()))
    return sid


async def _session(request, maintenant: float | None = None):
    """(empreinte, (serveur, membre, fin)) — ou None.

    24/10/2026 : n'importe quel cookie occupait une connexion de la base, sans limite par adresse,
    et une session effacée de la base restait ouverte jusqu'au redémarrage (cache en mémoire). Un
    cookie mal formé ne touche plus la base ; un cookie inconnu compte comme un faux lien (même
    limite par adresse, et au-delà plus aucune lecture) ; une session en mémoire est relue en base
    au-delà de RELIRE secondes."""
    t = maintenant or time.time()
    sid = request.cookies.get(COOKIE, "") if hasattr(request, "cookies") else ""
    if not sid:
        return None
    if not FORMAT_SESSION.fullmatch(sid):
        _trop_essais(request, compter=True, maintenant=t)
        return None
    emp = _empreinte(sid)
    s = _sessions.get(emp)
    if s is None or t - s[3] > RELIRE:
        if s is None and _trop_essais(request, maintenant=t):
            return None
        async with _get_db() as db:
            async with db.execute("SELECT guild_id, user_id, expire_le FROM tableau_sessions WHERE empreinte=?",
                                  (emp,)) as cur:
                r = await cur.fetchone()
        if r is None:
            if s is None:
                _trop_essais(request, compter=True, maintenant=t)
            _sessions.pop(emp, None)
            return None
        s = _sessions[emp] = (int(r[0]), int(r[1]), int(r[2]), t)
    if s[2] < t:
        return None
    return emp, s[:3]


async def fermer_sessions(guild_id: int | None, user_id: int) -> int:
    """Ferme les sessions d'une personne sur ce serveur — sur tous si `guild_id` est None —, en base
    ET en mémoire : coupées à la requête suivante. Rend leur nombre."""
    async with _get_db() as db:
        if guild_id is None:
            cur = await db.execute("DELETE FROM tableau_sessions WHERE user_id=?", (int(user_id),))
        else:
            cur = await db.execute("DELETE FROM tableau_sessions WHERE guild_id=? AND user_id=?",
                                   (int(guild_id), int(user_id)))
        n = max(cur.rowcount or 0, 0)
        await db.commit()
    for emp in [e for e, s in _sessions.items()
                if s[1] == int(user_id) and (guild_id is None or s[0] == int(guild_id))]:
        _sessions.pop(emp, None)
    return n


async def suspendre(g, membre, raison: str, maintenant: float | None = None) -> None:
    """Le signe d'un compte volé : plus d'accès au site pendant une heure, et on prévient."""
    t = int(maintenant or time.time())
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO tableau_blocages (guild_id, user_id, jusqu, raison) VALUES (?,?,?,?)",
                         (g.id, membre.id, t + BLOCAGE, raison[:200]))
        await db.commit()
    _blocages[(g.id, membre.id)] = t + BLOCAGE
    await fermer_sessions(g.id, membre.id)
    await registre.noter(g.id, "Sécurité", "site.suspendu", f"Accès au site suspendu une heure : {membre.display_name}"
                         f" — {raison}", membre_id=membre.id, gravite=2)
    if _alerte_securite is not None:
        try:
            await _alerte_securite(g, membre, raison)
        except Exception as ex:  # l'alerte ne doit pas empêcher la suspension
            _log("[TABLEAU][E6] alerte de sécurité impossible")
            _log(f"[TABLEAU][E6:DETAIL] {type(ex).__name__} {ex}")


class _Refus(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _ip(request) -> str:
    """Le client : la PREMIÈRE adresse de X-Forwarded-For. Vérifié le 20/10/2026 : le proxy de Railway
    retire l'en-tête envoyé par le client, et la DERNIÈRE adresse est celle du CDN — partagée par
    beaucoup de visiteurs (la prendre aurait mis tout le monde dans un seul compteur d'essais)."""
    fwd = request.headers.get("X-Forwarded-For", "") if hasattr(request, "headers") else ""
    return (fwd.split(",")[0].strip() or getattr(request, "remote", "") or "?")[:64]


def _trop_essais(request, compter: bool = False, maintenant: float | None = None) -> bool:
    t = maintenant or time.time()
    ip = _ip(request)
    recents = [x for x in _essais.get(ip, []) if t - x < 600]
    if compter:
        recents.append(t)
    if recents:
        _essais[ip] = recents
    else:
        _essais.pop(ip, None)
    if len(_essais) > 5000:  # les plus anciennes d'abord — tout vider remettait l'attaquant à zéro
        for k in sorted(_essais, key=lambda k: _essais[k][-1])[:1000]:
            _essais.pop(k, None)
    return len(recents) > LIMITE_ESSAIS


async def _verifier(request, maintenant: float | None = None):
    """Session valide, personne toujours fondateur ou direction, pas suspendue, cadence raisonnable."""
    t = maintenant or time.time()
    ses = await _session(request, t)
    if ses is None:
        if _trop_essais(request, maintenant=t):
            raise _Refus(429, "Trop d'essais.")
        raise _Refus(403, "Session expirée.")
    emp, (gid, uid, expire) = ses
    g = _bot.get_guild(gid) if _bot else None
    m = g.get_member(uid) if g else None
    if m is None or _autorise_membre is None or not _autorise_membre(g, m, await _cfg(g.id)):
        raise _Refus(403, "Accès retiré.")
    if await suspendu(gid, uid, t):
        raise _Refus(403, "Accès suspendu.")
    recents = [x for x in _requetes.get(emp, []) if t - x < 60]
    if len(recents) >= LIMITE_REQUETES:
        raise _Refus(429, "Trop de requêtes.")
    _requetes[emp] = recents + [t]
    return {"g": gid, "u": uid, "e": expire, "p": "tout", "emp": emp}, g


# ─── Les personnes ──────────────────────────────────────────────────────────

def _ident(g, uid, defaut="") -> dict:
    m = g.get_member(int(uid)) if uid else None
    return {"id": str(uid or ""), "nom": m.display_name if m else (defaut or "Membre parti"),
            "pseudo": m.name if m else "",
            "avatar": str(m.display_avatar.with_size(64).url) if m else ""}


def _nom(g, uid) -> str:
    if not uid:
        return ""
    m = g.get_member(int(uid))
    return m.display_name if m else "Membre parti"


class _Personnes(dict):
    """Une fiche (nom, avatar) par personne citée, envoyée une seule fois ; les listes ne portent
    que l'identifiant."""

    def __init__(self, g):
        super().__init__()
        self.g = g

    def __call__(self, uid, defaut="") -> str:
        if not uid:
            return ""
        k = str(int(uid))
        if k not in self:
            self[k] = _ident(self.g, int(uid), defaut)
        return k


def a_part(g, c) -> set:
    """« Direction et fondateur : mis à part, pas pris pour les stats. »"""
    out = {m.id for m in getattr(g, "members", []) or [] if _mis_a_part is not None and _mis_a_part(g, m, c)}
    return out | ({g.owner_id} if getattr(g, "owner_id", 0) else set())


def _quand(t) -> str:
    return datetime.fromtimestamp(int(t), PARIS).strftime("%d/%m/%Y %H:%M") if t else ""


# ─── Les données ────────────────────────────────────────────────────────────

async def _clan(g, c, apart: set) -> dict:
    role = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    if role is None:
        return {"role": "", "membres": [], "direction": []}
    tous = [m for m in role.members if not m.bot]
    membres = [m for m in tous if m.id not in apart]
    mesures = await _mesurer_groupe(g.id, membres) if _mesurer_groupe and membres else {}
    avatars = {m.id: str(m.display_avatar.with_size(64).url) for m in tous}
    try:
        rappels = await clan.rappels(g.id, {uid: (mes or {}).get("dernier") for uid, mes in mesures.items()},
                                     {m.id for m in tous})
    except Exception as ex:  # sans les rappels, la liste du clan reste lisible ; le détail part au journal
        _log("[TABLEAU][E8] rappels du clan illisibles")
        _log(f"[TABLEAU][E8:DETAIL] {type(ex).__name__} {ex}")
        rappels = {}
    for r in rappels.values():
        r["par"] = _nom(g, r["par"])
        r["salon"] = getattr(g.get_channel(int(r["salon"] or 0)), "name", "") if r["salon"] else ""
    return {"role": role.name, "role_id": str(role.id),
            "membres": [{"id": str(x["id"]), "nom": x["nom"], "pseudo": x["pseudo"], "avatar": avatars.get(x["id"], ""),
                         "statut": x["statut"], "rang": x["rang"], "jours": x["jours"], "derniere": x["derniere"],
                         "arrivee": x["arrivee"], "rappel": rappels.get(x["id"])}
                        for x in rellseas_panneau.lignes_clan(membres, mesures)],
            "direction": [_ident(g, m.id) for m in tous if m.id in apart], "salons": _salons_du_clan(g, role)}


def _salons_du_clan(g, role) -> list:
    """Où pinger les inactifs : les salons texte que le clan voit et où le bot peut écrire."""
    me, out = getattr(g, "me", None), []
    for s in getattr(g, "text_channels", None) or []:
        if me is not None and s.permissions_for(role).view_channel and s.permissions_for(me).send_messages:
            out.append({"id": str(s.id), "nom": s.name, "cat": s.category.name if s.category else ""})
    return out[:60]


async def recherche(request):
    """« Filtrer tout le serveur ou rechercher une personne en particulier » pour l'ajouter au clan."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    c = await _cfg(g.id)
    role = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    dans = {m.id for m in role.members} if role is not None else set()
    apart = a_part(g, c)
    trouves = clan.chercher(getattr(g, "members", None) or [], request.query.get("q", "")[:64], dans)
    # L'activité n'est suivie QUE pour le clan : hors du clan, un badge dirait « Jamais vu » à tort
    # (20/10/2026) — on ne mesure, et n'affiche, que les membres du clan.
    du_clan = [m for m in trouves if m.id in dans]
    try:
        mesures = await _mesurer_groupe(g.id, du_clan) if _mesurer_groupe and du_clan else {}
    except Exception as ex:  # sans mesure, la recherche reste utile ; le détail part au journal
        _log("[TABLEAU][E7] activité illisible")
        _log(f"[TABLEAU][E7:DETAIL] {type(ex).__name__} {ex}")
        mesures = {}
    lignes = {x["id"]: x for x in rellseas_panneau.lignes_clan(du_clan, mesures)}
    return _json({"role": role.name if role is not None else "", "membres": [
        dict(_ident(g, m.id), clan=m.id in dans, a_part=m.id in apart, statut=lignes.get(m.id, {}).get("statut"),
             rang=lignes.get(m.id, {}).get("rang"),
             arrivee=int(m.joined_at.timestamp()) if getattr(m, "joined_at", None) else None) for m in trouves]})


def _mediane(valeurs) -> int:
    v = sorted(x for x in valeurs if x is not None and x >= 0)
    return int(v[len(v) // 2]) if v else 0


async def _lignes_tickets(g, filtre: str = "", args: tuple = ()) -> list[dict]:
    async with _get_db() as db:
        tickets = await recrutements._lignes(
            db, "SELECT id, user_id, panel_id, claimed_by, status, created_at, channel_id FROM tickets"
                " WHERE guild_id=?" + filtre + " ORDER BY id", (g.id, *args))
        evts = await recrutements._lignes(
            db, "SELECT ticket_id, kind, actor_id, created_unix FROM ticket_log_events"
                " WHERE guild_id=? AND kind IN ('claim', 'close') ORDER BY id", (g.id,))
        audit = await recrutements._lignes(
            db, "SELECT channel_id, action, actor_id, at, detail FROM ticket_audit"
                " WHERE guild_id=? AND action IN ('claim', 'close') ORDER BY id", (g.id,))
        transcripts = dict(await recrutements._lignes(
            db, "SELECT ticket_id, url FROM ticket_transcripts WHERE guild_id=? AND url != ''", (g.id,)))
    prises, fins = {}, {}
    for tid, kind, actor, t in evts:
        (prises if kind == "claim" else fins).setdefault(tid, (int(t or 0), int(actor or 0)))
    prises_salon, fins_salon, motifs = {}, {}, {}
    for salon, action, actor, at, detail in audit:
        (prises_salon if action == "claim" else fins_salon).setdefault(
            salon, (recrutements._unix(at), int(actor or 0)))
        if action == "close" and detail:
            motifs[salon] = str(detail)[:200]
    out = []
    for tid, uid, pid, pris, statut, cree, salon in tickets:
        prise = prises.get(tid) or prises_salon.get(salon)
        fin_t = fins.get(tid) or fins_salon.get(salon)
        out.append({"ticket": tid, "uid": int(uid or 0), "panel": pid, "statut": statut, "salon": salon,
                    "ouvert": recrutements._unix(cree), "prise": prise, "fin": fin_t,
                    "pris_par": int(pris or 0) or (prise[1] if prise else 0), "motif": motifs.get(salon, ""),
                    "transcript": transcripts.get(tid, "")})
    return out


async def _tickets(g, c, apart: set, qui) -> dict:
    """Tous les tickets, triés par type : ouverts, fermés, délais réels, staff, mois."""
    panneaux = c.get("ticket_panels") or {}
    rell = rellseas_panneau.panneaux_tickets(c)
    types, ouverts, staff, staff30, mois, fermes = {}, [], {}, {}, {}, []
    maintenant = time.time()
    debut_mois = maintenant - 365 * 86400
    for x in await _lignes_tickets(g):
        nom = str((panneaux.get(x["panel"]) or {}).get("name") or "Sans type")
        est_rell = str(x["panel"] or "") in rell
        t = types.setdefault(nom, {"nom": nom, "rellseas": est_rell, "total": 0, "ouverts": 0,
                                   "fermes": 0, "sans_prise": 0, "_prise": [], "_fin": []})
        t["rellseas"] = t["rellseas"] or est_rell
        t["total"] += 1
        ouvert, prise, fin_t, pris_par = x["ouvert"], x["prise"], x["fin"], x["pris_par"]
        if pris_par and pris_par not in apart:
            staff.setdefault(pris_par, {"pris": 0, "fermes": 0})["pris"] += 1
            if prise and prise[0] and maintenant - prise[0] <= 30 * 86400:
                staff30.setdefault(pris_par, {"pris": 0, "fermes": 0})["pris"] += 1
        if x["statut"] == "open":
            t["ouverts"] += 1
            ouverts.append(dict(_ident(g, x["uid"]), ticket=x["ticket"], type=nom, rellseas=est_rell, ouvert=ouvert,
                                pris_par=_nom(g, pris_par),
                                salon=f"https://discord.com/channels/{g.id}/{x['salon']}" if x["salon"] else ""))
        else:
            t["fermes"] += 1
            if not pris_par:
                t["sans_prise"] += 1
            if fin_t and fin_t[1] and fin_t[1] not in apart:
                staff.setdefault(fin_t[1], {"pris": 0, "fermes": 0})["fermes"] += 1
                if fin_t[0] and maintenant - fin_t[0] <= 30 * 86400:
                    staff30.setdefault(fin_t[1], {"pris": 0, "fermes": 0})["fermes"] += 1
            if ouvert and fin_t and fin_t[0]:
                t["_fin"].append(fin_t[0] - ouvert)
            fermes.append((fin_t[0] if fin_t and fin_t[0] else (ouvert or 0), x, nom, est_rell))
        if ouvert and prise and prise[0]:
            t["_prise"].append(prise[0] - ouvert)
        if ouvert and ouvert >= debut_mois:
            cle_m = recrutements.cle_mois(datetime.fromtimestamp(ouvert, timezone.utc))
            groupe = "Rell Seas" if est_rell else "Tickets normaux"
            mois.setdefault(cle_m, {"Rell Seas": 0, "Tickets normaux": 0})[groupe] += 1
    for t in types.values():
        t["prise_mediane"] = _mediane(t.pop("_prise"))
        t["fermeture_mediane"] = _mediane(t.pop("_fin"))
    fermes.sort(key=lambda f: f[0], reverse=True)
    return {
        "types": sorted(types.values(), key=lambda t: (not t["rellseas"], -t["total"], t["nom"])),
        "ouverts": sorted(ouverts, key=lambda o: (not o["rellseas"], o["type"], o["ouvert"] or 0)),
        "staff": sorted(({"nom": _nom(g, k), **v} for k, v in staff.items()),
                        key=lambda x: -(x["pris"] + x["fermes"]))[:15],
        "staff30": staff30,
        "mois": dict(sorted(mois.items())[-12:]),
        "fermes": [{"id": qui(x["uid"]), "ticket": x["ticket"], "type": nom, "rellseas": est_rell,
                    "ouvert": x["ouvert"], "ferme": ferme or None,
                    "ferme_par": _nom(g, x["fin"][1] if x["fin"] else 0), "motif": x["motif"],
                    "transcript": x["transcript"]}
                   for ferme, x, nom, est_rell in fermes[:300]],
    }


def _libelle(typ: str) -> str:
    return SANCTIONS.get(typ) or DETECTIONS.get(typ) or (typ or "Autre").capitalize()


def _entree_casier(g, iid, typ, raison, duree, quand, est_auto, mod) -> dict:
    return {"sanction": iid, "type": typ, "libelle": _libelle(typ), "groupe": GROUPES.get(typ, "Détections"),
            "raison": str(raison or "")[:300], "duree": str(duree or ""), "date": quand, "auto": est_auto,
            "par": "Automatique" if est_auto else _nom(g, mod)}


async def _sanctions(g, apart: set, qui) -> dict:
    """Le casier, en chiffres et PAR MEMBRE : « quelqu'un qui a fait plusieurs avertissements, une
    case pour lui avec tous ses avertissements », et ce qui est en cours sur le serveur."""
    robot = getattr(getattr(_bot, "user", None), "id", 0) or 0
    async with _get_db() as db:
        rows = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? ORDER BY id DESC LIMIT 5000", (g.id,))
        restreints = await recrutements._lignes(
            db, "SELECT user_id, restricted_at, duration, reason, restricted_by FROM restricted_members"
                " WHERE guild_id=?", (g.id,))
    maintenant = time.time()
    par_type, mois, staff, staff30, membres = {}, {}, {}, {}, {}
    auto = manuel = recents_30 = 0
    for iid, uid, mod, typ, raison, duree, cree in rows:
        typ = str(typ or "autre").lower()
        quand = recrutements._unix(cree)
        est_auto = not mod or int(mod) == robot
        par_type[typ] = par_type.get(typ, 0) + 1
        auto, manuel = auto + est_auto, manuel + (not est_auto)
        age = maintenant - quand if quand else 10 ** 9
        recents_30 += age <= 30 * 86400
        if age <= 365 * 86400:
            cle_m = recrutements.cle_mois(datetime.fromtimestamp(quand, timezone.utc))
            mois.setdefault(cle_m, {"Avertissements": 0, "Mutes": 0, "Expulsions et bans": 0,
                                    "Détections": 0})[GROUPES.get(typ, "Détections")] += 1
        if not est_auto and int(mod) not in apart:
            st = staff.setdefault(int(mod), {"total": 0, "types": {}, "dernieres": []})
            st["total"] += 1
            st["types"][typ] = st["types"].get(typ, 0) + 1
            if age <= 30 * 86400:
                staff30[int(mod)] = staff30.get(int(mod), 0) + 1
            if len(st["dernieres"]) < 15:
                st["dernieres"].append(dict(_entree_casier(g, iid, typ, raison, duree, quand, est_auto, mod),
                                            id=qui(uid)))
        if not uid or int(uid) in apart:
            continue
        f = membres.setdefault(int(uid), {"id": qui(uid), "total": 0, "n30": 0, "n90": 0, "types": {},
                                          "derniere": 0, "liste": []})
        f["total"] += 1
        f["n30"] += age <= 30 * 86400
        f["n90"] += age <= 90 * 86400
        f["types"][typ] = f["types"].get(typ, 0) + 1
        f["derniere"] = max(f["derniere"], quand or 0)
        if len(f["liste"]) < LISTE_PAR_MEMBRE:
            f["liste"].append(_entree_casier(g, iid, typ, raison, duree, quand, est_auto, mod))
    radie = next((r for r in getattr(g, "roles", []) if r.name == _radie), None)
    mutes = [m for m in getattr(g, "members", []) if getattr(m, "is_timed_out", lambda: False)()]
    return {
        "total": len(rows), "trente_jours": recents_30, "auto": auto, "manuel": manuel,
        "libelles": {k: _libelle(k) for k in par_type},
        "types": sorted(({"type": k, "libelle": _libelle(k), "n": v, "detection": k not in SANCTIONS}
                         for k, v in par_type.items()), key=lambda t: -t["n"]),
        "mois": dict(sorted(mois.items())[-12:]),
        "staff": sorted(({"nom": _nom(g, k), "id": qui(k), **v} for k, v in staff.items()),
                        key=lambda x: -x["total"])[:15],
        "staff30": staff30,
        "membres": sorted(membres.values(), key=lambda f: -f["derniere"])[:MEMBRES_CASIER],
        "actives": {
            "mutes": [dict(_ident(g, m.id), jusqu=int(m.timed_out_until.timestamp()) if m.timed_out_until else None)
                      for m in mutes if m.id not in apart],
            "radies": [_ident(g, m.id) for m in (radie.members if radie else [])],
            "restreints": [dict(_ident(g, uid), depuis=recrutements._unix(depuis), raison=str(raison or "")[:200],
                                par=_nom(g, par)) for uid, depuis, _d, raison, par in restreints],
        },
    }


def _evenement(g, r: dict, qui) -> dict:
    lieu = None
    if r["salon_id"]:
        lieu = g.get_channel(int(r["salon_id"])) or g.get_thread(int(r["salon_id"]))
    return {"id": r["id"], "quand": r["quand"], "cat": r["categorie"] or "Autre", "type": r["type"] or "",
            "texte": r["texte"] or "", "detail": r["detail"] or "", "membre": qui(r["membre_id"]),
            "auteur": qui(r["auteur_id"]), "salon": f"#{lieu.name}" if lieu else "",
            "gravite": int(r["gravite"] or 0)}


async def _journal(g, qui, membre_id: int | None = None, limite: int = 400) -> dict:
    """« Il n'y aura plus de logs sur Discord : tout sur le site, traduit par personne. »"""
    out = {"evenements": [_evenement(g, r, qui) for r in await registre.lire(g.id, limite, membre_id)]}
    if membre_id is None:
        #  Le fuseau, pas le décalage du jour : au changement d'heure (25/10/2026), le décalage
        #  d'aujourd'hui appliqué à 30 jours d'historique faisait glisser une heure par jour sur la veille.
        out["par_jour"] = await registre.par_jour(g.id, 30, PARIS)
    return out


def _question(g, q: dict, qui) -> dict:
    salon = g.get_channel(int(q["salon_id"] or 0)) or g.get_thread(int(q["salon_id"] or 0))
    return {"question": q["id"], "id": qui(q["auteur_id"]), "texte": q["texte"], "quand": q["quand"],
            "statut": q["statut"], "libelle": questions.STATUTS.get(q["statut"], q["statut"]),
            "par": _nom(g, q["repondu_par"]), "par_id": str(q["repondu_par"] or ""),
            "par_staff": bool(q["par_staff"]), "repondu_le": q["repondu_le"],
            "salon": f"#{salon.name}" if salon else "#salon", "message": q["message"], "reponse": q["lien"] or ""}


async def _questions(g, qui) -> dict:
    d = await questions.lister(g.id)
    return {"liste": [_question(g, q, qui) for q in d["liste"]],
            "stats": dict(d["stats"], salons=[{"salon": f"#{getattr(g.get_channel(int(s or 0)), 'name', 'salon')}",
                                               "n": n} for s, n in d["stats"]["salons"]])}


async def _alertes(g, qui) -> list:
    out = []
    maintenant = time.time()
    for a in await vigilance.ouvertes(g.id):
        evts = await registre.graves(g.id, a["membre_id"], int(maintenant - vigilance.FENETRE))
        n, points = vigilance.mesure(evts)
        out.append({"id": qui(a["membre_id"]), "ouverte_le": a["ouverte_le"], "maj_le": a["maj_le"],
                    "incidents": n, "points": points,
                    "evenements": [{"quand": e["quand"], "texte": e["texte"], "gravite": e["gravite"]}
                                   for e in evts[-8:]]})
    return out


async def _casier(g, qui) -> dict:
    """Ce que chaque zone du casier effacerait, et les nettoyages des 30 derniers jours (à défaire)."""
    lots = await casier.lots(g.id)
    for x in lots:
        x["par"] = qui(int(x["par"])) if x["par"] else ""
        x["restaure_par"] = qui(int(x["restaure_par"])) if x["restaure_par"] else ""
    return {"lots": lots, "compte": await casier.comptes(g.id, getattr(getattr(_bot, "user", None), "id", 0) or 0)}


async def _suggestions(g, qui) -> dict:
    d = await suggestions.lister(g.id)
    for s in d["liste"]:
        s["auteur"] = qui(int(s["auteur"]))
        if s["decide_par"]:
            s["decide_par"] = qui(int(s["decide_par"]))
        ch = g.get_channel(int(s["salon_id"]))
        s["salon"] = f"#{ch.name}" if ch is not None else "#salon supprimé"
    return d


async def _entraide(g, qui) -> dict:
    """« Nous, on a toutes les informations des salons trade et entraide au propre » : chaque demande,
    ouverte ou close — qui, quoi, qui est venu, qui l'a certifiée, avec qui l'échange s'est fait."""
    liste = []
    for d in await entraide.recentes(g.id, 300):
        z = entraide.ZONES.get(d["zone"])
        liste.append({"id": d["id"], "zone": d["zone"], "type": z.libelle if z else d["zone"], "emoji": z.emoji if z else "",
                      "auteur": qui(d["auteur_id"]), "titre": d["titre"],
                      "champs": [[str(lib), str(v)] for lib, v in d["champs"] if str(v or "").strip()],
                      "statut": d["statut"], "libelle": entraide.STATUTS.get(d["statut"], (d["statut"], ""))[0],
                      "aidants": [qui(x) for x in d["aidants"]], "credites": [qui(x) for x in d["credites"]],
                      "certifie_par": qui(d["certifie_par"]), "partenaire": qui(d["partenaire_id"]),
                      "ferme_par": qui(d["ferme_par"]), "cree": d["cree"], "ferme": d["ferme"] or None,
                      "lien": "" if d["supprime"] else entraide.lien(g, d),
                      "transcript": transcript_store.transcript_url(d["jeton"]) if d["jeton"] else ""})
    return {"liste": liste, "stats": {"ouvertes": sum(1 for x in liste if x["statut"] in entraide.OUVERTS),
                                      "total": len(liste), "certifiees": sum(1 for x in liste if x["certifie_par"])}}


async def _annonces(g, qui) -> dict:
    """Les annonces publiées depuis 📋logs et qui a cliqué « ✅ Vu »."""
    liste = []
    for a in await annonces.recentes(g.id, 60):
        ch = g.get_channel(int(a["salon_id"])) or g.get_thread(int(a["salon_id"]))
        vus = await annonces.qui_a_vu(a["id"])
        liste.append({"id": a["id"], "titre": a["titre"], "texte": a["texte"][:1500],
                      "salon": f"#{ch.name}" if ch is not None else "#salon supprimé", "auteur": qui(a["auteur_id"]),
                      "cree": a["cree"], "vues": len(vus), "vus": [qui(m) for m, _q in vus[:40]],
                      "mention": "@everyone" if a["mention"] == "@everyone" else ("le clan" if a["mention"] else ""),
                      "lien": f"https://discord.com/channels/{g.id}/{a['salon_id']}/{a['message_id']}"})
    return {"liste": liste, "stats": {"total": len(liste), "vues": sum(x["vues"] for x in liste)}}


async def _droits_salons(g, c) -> list:
    """« Des vrais trucs bien propres par salon, qu'on comprenne bien » : chaque catégorie, chaque
    salon, ce que @everyone (et le clan) peut y faire. Lecture seule : rien ne se règle d'ici."""
    tous = g.default_role
    clan = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    sortie = []
    for categorie, salons in g.by_category():
        lignes = []
        for s in salons:
            if isinstance(s, discord.CategoryChannel):
                continue
            p = s.permissions_for(tous)
            vocal = isinstance(s, (discord.VoiceChannel, discord.StageChannel))
            pc = s.permissions_for(clan) if clan is not None else None
            if p.view_channel:
                profil = ("ouvert" if p.connect else "vitrine") if vocal else ("ouvert" if p.send_messages else "lecture")
            elif pc is not None and pc.view_channel:
                profil = "clan"
            else:
                profil = "cache"
            lignes.append({"id": str(s.id), "nom": s.name, "vocal": vocal, "profil": profil,
                           "voir": bool(p.view_channel), "ecrire": bool(p.send_messages) and not vocal,
                           "reagir": bool(p.add_reactions) and not vocal, "rejoindre": bool(p.connect) and vocal,
                           "images": bool(p.attach_files) and not vocal})
        if lignes:
            sortie.append({"categorie": categorie.name if categorie is not None else "Sans catégorie", "salons": lignes})
    return sortie


async def _sondages(g, qui) -> dict:
    """« Et qui s'affiche au propre, même sur le panel. »"""
    d = await sondages.lister(g.id)
    for s in d["liste"]:
        s["auteur"] = qui(int(s["auteur"]))
        if s["retire_par"]:
            s["retire_par"] = qui(int(s["retire_par"]))
        ch = g.get_channel(int(s["salon_id"])) or g.get_thread(int(s["salon_id"]))
        s["salon"] = f"#{ch.name}" if ch is not None else "#salon supprimé"
    return d


async def donnees(g, portee: str = "tout") -> dict:
    cle = (g.id, portee)
    deja = _cache.get(cle)
    if deja and time.time() - deja[0] < 15:
        return deja[1]
    c = await _cfg(g.id)
    apart = a_part(g, c)
    qui = _Personnes(g)
    parties = {}
    for nom, fn in (("journal", lambda: _journal(g, qui)), ("questions", lambda: _questions(g, qui)),
                    ("alertes", lambda: _alertes(g, qui)), ("sondages", lambda: _sondages(g, qui)),
                    ("casier", lambda: _casier(g, qui)), ("suggestions", lambda: _suggestions(g, qui)),
                    ("entraide", lambda: _entraide(g, qui)),
                    ("annonces", lambda: _annonces(g, qui)), ("salons", lambda: _droits_salons(g, c))):
        try:
            parties[nom] = await fn()
        except Exception as ex:  # une partie illisible n'emporte pas le reste du tableau
            _log("[TABLEAU][E4] partie illisible")
            _log(f"[TABLEAU][E4:DETAIL] {nom} {type(ex).__name__} {ex}")
            parties[nom] = [] if nom == "alertes" else {"erreur": True}
    cand = await recrutements.candidatures(g)
    candidats = [dict(_ident(g, d["candidat_id"], d["nom"]), statut=d["statut"], ticket=d["ticket"],
                      ouvert=d["ouvert"], ferme=d["ferme"], pris_par=_nom(g, d["pris_par"]),
                      ferme_par=_nom(g, d["ferme_par"]), motif=d["raison"], parti=d.get("parti", False),
                      reponses=list(d["reponses"].items()), transcript=d["transcript"] or "",
                      candidatures=d["dates"])
                 for d in cand["fiches"]]
    en_cours = [dict(_ident(g, o["candidat_id"]), statut="en_cours", ticket=o["ticket"],
                     ouvert=o["ouvert"], pris_par=_nom(g, o["pris_par"]),
                     reponses=list(o["reponses"].items()),
                     salon=f"https://discord.com/channels/{g.id}/{o['salon']}" if o["salon"] else "")
                for o in cand["en_cours"]]
    tickets = await _tickets(g, c, apart, qui)
    sanctions = await _sanctions(g, apart, qui)
    equipe: dict = {}
    for uid, v in tickets.pop("staff30").items():
        equipe.setdefault(uid, {"tickets": 0, "sanctions": 0, "questions": 0})["tickets"] += v["pris"] + v["fermes"]
    for uid, n in sanctions.pop("staff30").items():
        equipe.setdefault(uid, {"tickets": 0, "sanctions": 0, "questions": 0})["sanctions"] += n
    for q in parties["questions"].get("liste") or []:
        if q["par_staff"] and q["par_id"] and q["repondu_le"] and time.time() - q["repondu_le"] <= 30 * 86400:
            equipe.setdefault(int(q["par_id"]), {"tickets": 0, "sanctions": 0, "questions": 0})["questions"] += 1
    out = {
        "version": VERSION,
        "serveur": {"nom": g.name, "icone": str(g.icon.with_size(128).url) if g.icon else ""},
        "genere": datetime.now(timezone.utc).isoformat(),
        "portee": portee,
        "a_part": sorted(str(x) for x in apart),
        "candidats": candidats,
        "en_cours": en_cours,
        "ecartes": cand["vides"] + cand["doublons"],
        "tickets": tickets,
        "clan": await _clan(g, c, apart),
        "sanctions": sanctions,
        "equipe": sorted(({"id": qui(uid), **v} for uid, v in equipe.items() if uid not in apart),
                         key=lambda x: -(x["tickets"] + x["sanctions"] + x["questions"]))[:12],
        **parties,
        "personnes": qui,
    }
    _cache[cle] = (time.time(), out)
    return out


# ─── La fiche d'un membre : tout ce qui le concerne ─────────────────────────

async def fiche(g, uid: int, auteur) -> dict:
    """« Une case par personne… sur ce qu'il a fait tel jour et quand. » Rôles en lecture seule :
    le site ne donne aucun rôle ; seul le rôle Rell Seas peut y être retiré (direction, fondateur)."""
    c = await _cfg(g.id)
    qui = _Personnes(g)
    qui(uid)
    m = g.get_member(int(uid))
    protege = m is not None and (int(uid) == getattr(g, "owner_id", 0) or bool(_mis_a_part and _mis_a_part(g, m, c)))
    agir = (bool(_direction and auteur is not None and _direction(g, auteur, c))
            and not await suspendu(g.id, getattr(auteur, "id", 0)))
    clan = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    infos = {"present": m is not None, "a_part": bool(m is not None and (int(uid) == getattr(g, "owner_id", 0)
                                                                         or (_mis_a_part and _mis_a_part(g, m, c)))),
             "protege": protege, "bot": bool(getattr(m, "bot", False)), "roles": [], "arrivee": None, "cree": None,
             "mute_jusqu": None, "clan": bool(m is not None and clan is not None and clan in m.roles)}
    if m is not None:
        infos["roles"] = [{"nom": r.name, "couleur": f"#{r.colour.value:06x}" if getattr(r, "colour", None)
                           and r.colour.value else ""} for r in sorted(m.roles, key=lambda r: -r.position)
                          if r != getattr(g, "default_role", None)][:20]
        infos["arrivee"] = int(m.joined_at.timestamp()) if getattr(m, "joined_at", None) else None
        infos["cree"] = int(m.created_at.timestamp()) if getattr(m, "created_at", None) else None
        if getattr(m, "timed_out_until", None) and getattr(m, "is_timed_out", lambda: False)():
            infos["mute_jusqu"] = int(m.timed_out_until.timestamp())
    elif getattr(g, "fetch_ban", None) is not None:
        import discord
        try:
            await g.fetch_ban(discord.Object(id=int(uid)))
            infos["banni"] = True
        except discord.NotFound:
            infos["banni"] = False
        except discord.HTTPException as ex:
            _log("[TABLEAU][E6] bannissement illisible")
            _log(f"[TABLEAU][E6:DETAIL] {uid} {type(ex).__name__} {ex}")
    robot = getattr(getattr(_bot, "user", None), "id", 0) or 0
    async with _get_db() as db:
        rows = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 500", (g.id, int(uid)))
        par_lui = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? AND mod_id=? ORDER BY id DESC LIMIT 100", (g.id, int(uid)))
    sanctions = [_entree_casier(g, iid, str(typ or "autre").lower(), raison, duree, recrutements._unix(cree),
                                not mod or int(mod) == robot, mod)
                 for iid, _u, mod, typ, raison, duree, cree in rows]
    donnees_par_lui = [dict(_entree_casier(g, iid, str(typ or "autre").lower(), raison, duree,
                                           recrutements._unix(cree), False, mod), id=qui(u))
                       for iid, u, mod, typ, raison, duree, cree in par_lui] if int(uid) != robot else []
    panneaux = c.get("ticket_panels") or {}
    tickets = [{"ticket": x["ticket"], "type": str((panneaux.get(x["panel"]) or {}).get("name") or "Sans type"),
                "statut": "ouvert" if x["statut"] == "open" else "fermé", "ouvert": x["ouvert"],
                "ferme": x["fin"][0] if x["fin"] else None, "pris_par": _nom(g, x["pris_par"]),
                "ferme_par": _nom(g, x["fin"][1] if x["fin"] else 0), "motif": x["motif"],
                "transcript": x["transcript"],
                "salon": f"https://discord.com/channels/{g.id}/{x['salon']}" if x["statut"] == "open" and x["salon"] else ""}
               for x in reversed(await _lignes_tickets(g, " AND user_id=?", (int(uid),)))]
    candidatures = [dict(r, reponses=list(r["reponses"].items())[:20])
                    for r in await recrutements.du_candidat(g.id, int(uid))]
    journal = await _journal(g, qui, int(uid), 300)
    qs = [_question(g, q, qui) for q in await questions.du_membre(g.id, int(uid))]
    alerte = next((a for a in await _alertes(g, qui) if a["id"] == str(int(uid))), None)
    ses_sondages, ses_idees = [], []
    for nom, module in (("sondages", sondages), ("idees", suggestions)):
        try:
            liste = (await module.lister(g.id, 30, int(uid)))["liste"]
        except Exception as ex:  # l'une illisible n'emporte pas l'autre ; le détail part au journal
            _log("[TABLEAU][E9] sondages ou idées du membre illisibles")
            _log(f"[TABLEAU][E9:DETAIL] {nom} {type(ex).__name__} {ex}")
            continue
        for x in liste:
            ch = g.get_channel(int(x["salon_id"])) or g.get_thread(int(x["salon_id"]))
            x["salon"] = f"#{ch.name}" if ch is not None else "#salon supprimé"
        (ses_sondages if nom == "sondages" else ses_idees).extend(liste)
    return {"membre": dict(qui[str(int(uid))], **infos), "agir": agir and not protege, "sanctions": sanctions,
            "donnees": donnees_par_lui, "tickets": tickets, "candidatures": candidatures,
            "journal": journal["evenements"], "questions": qs, "sondages": ses_sondages, "idees": ses_idees,
            "alerte": alerte, "personnes": qui}


# ─── L'export : un fichier propre, à garder ou à m'envoyer ──────────────────

def _csv(entetes: list, lignes: list) -> bytes:
    """Point-virgule et BOM : s'ouvre proprement dans Excel en français. Une cellule qui
    commencerait par = + - @ est neutralisée (pas de formule exécutée à l'ouverture)."""
    f = io.StringIO()
    w = csv.writer(f, delimiter=";", lineterminator="\r\n")
    w.writerow(entetes)
    for ligne in lignes:
        cellules = []
        for v in ligne:
            s = "" if v is None else str(v).replace("\r", " ").replace("\n", " ")
            cellules.append("'" + s if s[:1] in ("=", "+", "-", "@", "\t") else s)
        w.writerow(cellules)
    return ("﻿" + f.getvalue()).encode("utf-8")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).casefold()).strip("-")[:40] or "serveur"


async def exporter(g, quoi: str, auteur, jours: int = 30, membre: int = 0, categorie: str = "",
                   format_: str = "csv") -> tuple[bytes, str, str] | None:
    """(contenu, type, nom de fichier) — ou None si l'export n'existe pas ou n'est pas permis."""
    c = await _cfg(g.id)
    jours = max(1, min(int(jours or 30), 365))
    depuis = int(time.time() - jours * 86400)
    qui = _Personnes(g)

    def nom_id(uid) -> str:
        return f"{qui[qui(uid)]['nom']} ({uid})" if uid else ""
    if quoi == "journal":
        rows = await registre.lire(g.id, EXPORT_MAX, membre or None, depuis, categorie or None)
        entetes = ["Date", "Catégorie", "Type", "Gravité", "Membre", "Auteur", "Salon", "Texte", "Détail"]
        lignes = [[_quand(r["quand"]), r["categorie"], r["type"], r["gravite"], nom_id(r["membre_id"]),
                   nom_id(r["auteur_id"]), _evenement(g, r, qui)["salon"], r["texte"], r["detail"]] for r in rows]
        brut = [dict(r, date=_quand(r["quand"])) for r in rows]
    elif quoi == "membre" and membre:
        f = await fiche(g, int(membre), auteur)
        entetes = ["Rubrique", "Date", "Quoi", "Par", "Détail", "Lien"]
        lignes = ([["Sanction", _quand(s["date"]), s["libelle"], s["par"], s["raison"], ""] for s in f["sanctions"]]
                  + [["Ticket", _quand(t["ouvert"]), f"#{t['ticket']} {t['type']} ({t['statut']})", t["ferme_par"],
                      t["motif"], t["transcript"]] for t in f["tickets"]]
                  + [["Journal", _quand(e["quand"]), e["cat"], nom_id(int(e["auteur"])) if e["auteur"] else "",
                      e["texte"] + (f" — {e['detail']}" if e["detail"] else ""), ""] for e in f["journal"]]
                  + [["Question", _quand(q["quand"]), q["libelle"], q["par"], q["texte"], q["message"]]
                     for q in f["questions"]])
        brut = f
    elif quoi == "sanctions":
        async with _get_db() as db:
            rows = await recrutements._lignes(
                db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                    " WHERE guild_id=? ORDER BY id DESC LIMIT ?", (g.id, EXPORT_MAX))
        entetes = ["N°", "Date", "Membre", "Type", "Durée", "Par", "Raison"]
        lignes = [[iid, _quand(recrutements._unix(cree)), nom_id(uid), _libelle(str(typ or "").lower()), duree,
                   nom_id(mod), raison] for iid, uid, mod, typ, raison, duree, cree in rows]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    elif quoi == "questions":
        d = await questions.lister(g.id)
        entetes = ["Date", "Membre", "Salon", "Statut", "Répondu par", "Question", "Lien"]
        lignes = [[_quand(q["quand"]), nom_id(q["auteur_id"]), _question(g, q, qui)["salon"],
                   questions.STATUTS.get(q["statut"], q["statut"]), _nom(g, q["repondu_par"]), q["texte"],
                   q["message"]] for q in d["liste"]]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    elif quoi == "erreurs" and _direction and auteur is not None and _direction(g, auteur, c):
        #  Les erreurs de CE serveur. Celles du bot entier (sans serveur : guild_id 0) : le fondateur
        #  seul — 24/10/2026 : elles partaient vers quiconque ouvrait le site (tous serveurs confondus).
        globales = owner_ids.is_super_owner(getattr(auteur, "id", 0))
        async with _get_db() as db:
            rows = await recrutements._lignes(
                db, "SELECT occurred_at, source, error_type, message, traceback FROM error_log"
                    + (" WHERE guild_id IN (?, 0)" if globales else " WHERE guild_id=?")
                    + " ORDER BY id DESC LIMIT 2000", (g.id,))
        entetes = ["Date (UTC)", "Source", "Type", "Message", "Trace"]
        lignes = [[str(a), s, t, str(msg or "")[:1000], str(tb or "")[:4000]] for a, s, t, msg, tb in rows]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    else:
        return None
    nom = f"{quoi}-{_slug(g.name)}-{datetime.now(PARIS):%Y-%m-%d}"
    if format_ == "json":
        return (json.dumps(brut, ensure_ascii=False, indent=1, default=str).encode("utf-8"),
                "application/json", f"{nom}.json")
    return _csv(entetes, lignes), "text/csv", f"{nom}.csv"


# ─── Les routes (servies par health_server) ─────────────────────────────────

def _json(corps, status: int = 200, etag: str | None = None):
    from aiohttp import web
    entetes = dict(ENTETES, **({"ETag": etag} if etag else {}))
    r = web.Response(body=json.dumps(corps, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"),
                     status=status, content_type="application/json", headers=entetes)
    r.enable_compression()
    return r


def _html(texte: str, status: int = 200, nonce: str | None = None):
    from aiohttp import web
    entetes = dict(ENTETES)
    if nonce:
        entetes["Content-Security-Policy"] = ENTETES["Content-Security-Policy"].replace(
            "script-src 'none'", f"script-src 'nonce-{nonce}'")
    r = web.Response(text=texte, status=status, content_type="text/html", headers=entetes)
    r.enable_compression()
    return r


async def entree(request):
    """Le lien du bouton : vérifié, consommé, changé en session — puis l'adresse propre."""
    from aiohttp import web
    if _trop_essais(request):
        return _html(TROP, 429)
    j = lire_jeton(request.match_info.get("jeton", ""))
    g = _bot.get_guild(j["g"]) if j and _bot else None
    m = g.get_member(j["u"]) if g else None
    if m is None or _autorise_membre is None or not _autorise_membre(g, m, await _cfg(g.id)) \
            or await suspendu(g.id, m.id):
        _trop_essais(request, compter=True)
        return _html(EXPIRE, 403)
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO tableau_jetons (nonce, expire_le) VALUES (?,?)", (j["n"], j["e"]))
        await db.commit()
        neuf = bool(cur.rowcount)
    if not neuf:
        ses = await _session(request)
        if ses is not None and ses[1][:2] == (j["g"], j["u"]):
            return web.Response(status=303, headers=dict(ENTETES, Location=ESPACE))
        _trop_essais(request, compter=True)
        return _html(DEJA, 403)
    sid = await _ouvrir_session(j["g"], j["u"], j["e"])
    r = web.Response(status=303, headers=dict(ENTETES, Location=ESPACE))
    r.set_cookie(COOKIE, sid, max_age=max(60, j["e"] - int(time.time())), path="/", secure=True, httponly=True,
                 samesite="Lax")
    await registre.noter(g.id, "Accès", "site.ouvert", f"Site ouvert par {m.display_name}", auteur_id=m.id)
    return r


async def page(request):
    try:
        await _verifier(request)
    except _Refus as r:
        return _html(EXPIRE if r.status != 429 else TROP, r.status)
    nonce = _b64(secrets.token_bytes(16))
    return _html(PAGE.replace("__NONCE__", nonce), nonce=nonce)


async def api(request):
    from aiohttp import web
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    c = await _cfg(g.id)
    moi = g.get_member(j["u"])
    droits = {"actions": bool(_direction and _direction(g, moi, c)), "staff": True, "moi": str(j["u"])}
    try:
        d = await donnees(g, j["p"])
    except Exception as ex:  # la page affiche l'erreur ; le détail part au journal
        _log("[TABLEAU][E1] données indisponibles")
        _log(f"[TABLEAU][E1:DETAIL] {type(ex).__name__} {ex}")
        return _json({"erreur": "données indisponibles"}, 500)
    corps = dict(d, expire=j["e"], droits=droits)
    empreinte = dict(corps)
    empreinte.pop("genere", None)
    etag = '"' + hashlib.sha256(json.dumps(empreinte, sort_keys=True, default=str).encode()).hexdigest()[:20] + '"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=dict(ENTETES, ETag=etag))
    return _json(corps, etag=etag)


async def membre(request):
    """La fiche d'une personne : sanctions, tickets, candidatures, journal, questions, rôles."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    uid = request.query.get("id", "")
    if not uid.isdigit() or len(uid) > 20:
        return _json({"erreur": "membre invalide"}, 400)
    try:
        return _json(await fiche(g, int(uid), g.get_member(j["u"])))
    except Exception as ex:  # la page le dit ; le détail part au journal du bot
        _log("[TABLEAU][E3] fiche indisponible")
        _log(f"[TABLEAU][E3:DETAIL] {type(ex).__name__} {ex}")
        return _json({"erreur": "fiche indisponible"}, 500)


_conversation = None


async def conversation(request):
    """Toute la conversation d'un ticket (20/10/2026 : « on n'a que le questionnaire »)."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    ticket = request.query.get("ticket", "")
    if not ticket.isdigit() or len(ticket) > 12 or _conversation is None:
        return _json({"erreur": "ticket invalide"}, 400)
    try:
        return _json(await _conversation(g, int(ticket)))
    except Exception as ex:  # la page le dit ; le détail part au journal du bot
        _log("[TABLEAU][E10] conversation indisponible")
        _log(f"[TABLEAU][E10:DETAIL] {ticket} {type(ex).__name__} {ex}")
        return _json({"erreur": "conversation indisponible"}, 500)


async def export(request):
    from aiohttp import web
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    q = request.query
    membre_ = q.get("membre", "")
    jours = q.get("jours", "30")
    if (membre_ and (not membre_.isdigit() or len(membre_) > 20)) or not jours.isdigit() or len(jours) > 3:
        return _json({"erreur": "demande invalide"}, 400)
    try:
        res = await exporter(g, q.get("quoi", ""), g.get_member(j["u"]), int(jours), int(membre_ or 0),
                             q.get("cat", "")[:40], "json" if q.get("format") == "json" else "csv")
    except Exception as ex:
        _log("[TABLEAU][E5] export impossible")
        _log(f"[TABLEAU][E5:DETAIL] {type(ex).__name__} {ex}")
        return _json({"erreur": "export impossible"}, 500)
    if res is None:
        return _json({"erreur": "export inconnu ou réservé"}, 404)
    contenu, type_, nom = res
    r = web.Response(body=contenu, content_type=type_, charset="utf-8",
                     headers=dict(ENTETES, **{"Content-Disposition": f'attachment; filename="{nom}"'}))
    r.enable_compression()
    return r


def _origine_ok(request) -> bool:
    """Une écriture vient de la page elle-même : en-tête maison, même origine, même site."""
    h = request.headers
    if h.get("X-Tableau") != "1":
        return False
    if h.get("Sec-Fetch-Site", "same-origin") != "same-origin":
        return False
    origine = h.get("Origin")
    if origine is None:
        return True
    attendue = _base.split("/", 3)[:3] if _base else None
    attendue = "/".join(attendue) if attendue else f"{getattr(request, 'scheme', 'https')}://{getattr(request, 'host', '')}"
    return origine == attendue


def _genre_grave(nom: str, corps: dict) -> tuple[str, int] | None:
    if nom == "moderer" and corps.get("sanction") in ("kick", "ban"):
        return "exclusion", 1
    if nom in ("clan_retirer", "clan_ajouter"):
        return "roles", 1
    if nom == "clan_prevenir":
        return "rappels", len(corps.get("membres") or [])
    if nom == "clan_retirer_lot":
        return "roles", len(corps.get("membres") or [])
    if nom in ("casier_effacer", "casier_restaurer"):
        return "casier", 1
    if nom == "casier_serveur":
        return "casier", 5
    if nom == "debannir":
        return "exclusion", 1
    return None


async def action(request):
    """« Seulement le fondateur et le rôle direction » : chaque action est revérifiée ici, inscrite
    au journal, et refusée si elle ne vient pas de la page elle-même. Trop d'actions graves : accès
    suspendu."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"ok": False, "message": r.message}, r.status)
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    try:
        corps = await request.json() if request.content_length and request.content_length <= 4096 else {}
    except ValueError:
        corps = {}
    if not isinstance(corps, dict):
        corps = {}
    nom = str(corps.get("action") or "")
    fn = _actions.get(nom)
    if fn is None:
        return _json({"ok": False, "message": "Action inconnue."}, 400)
    auteur = g.get_member(j["u"])
    if _direction is None or not _direction(g, auteur, await _cfg(g.id)):
        return _json({"ok": False, "message": "Réservé au fondateur et à la direction."}, 403)
    maintenant = time.time()
    recents = [t for t in _cadence.get(auteur.id, []) if maintenant - t < 60]
    if len(recents) >= 20:
        return _json({"ok": False, "message": "Trop d'actions d'un coup, attends une minute."}, 429)
    _cadence[auteur.id] = recents + [maintenant]
    grave = _genre_grave(nom, corps)
    if grave is not None:
        genre, n = grave
        cle = (g.id, auteur.id, genre)
        faits = [t for t in _graves.get(cle, []) if maintenant - t < 600]
        if len(faits) + n > LIMITES_GRAVES[genre]:
            raison = f"{len(faits) + n} actions graves ({genre}) en moins de 10 minutes"
            if not a_la_tete(g, auteur.id):
                await suspendre(g, auteur, raison)
                return _json({"ok": False, "message": "Trop d'actions graves en peu de temps : accès au site suspendu "
                                                      "une heure, le fondateur est prévenu."}, 403)
            #  « Si tu es suspendu alors que je suis le fondateur, il y a un petit problème » : jamais de
            #  suspension pour la tête ; la direction est seulement signalée au fondateur, une fois.
            cle_alerte = (g.id, auteur.id, genre)
            if _alerte_securite is not None and maintenant - _alertes_tete.get(cle_alerte, 0) > 600:
                _alertes_tete[cle_alerte] = maintenant
                try:
                    await _alerte_securite(g, auteur, raison, suspendu=False)
                except Exception as ex:  # l'alerte ne bloque jamais l'action
                    _log("[TABLEAU][E6] alerte de sécurité impossible")
                    _log(f"[TABLEAU][E6:DETAIL] {type(ex).__name__} {ex}")
        _graves[cle] = faits + [maintenant] * n
    try:
        ok, message = await fn(g, auteur, corps)
    except Exception as ex:  # l'action échoue : la page le dit, le détail part au journal
        _log("[TABLEAU][E2] action impossible")
        _log(f"[TABLEAU][E2:DETAIL] {nom} {type(ex).__name__} {ex}")
        ok, message = False, "L'action n'a pas pu être faite."
    for cle in [k for k in _cache if k[0] == g.id]:
        _cache.pop(cle, None)
    return _json({"ok": bool(ok), "message": str(message)})


async def sortir(request):
    """Se déconnecter : la session de ce navigateur est effacée — avec `?partout=1`, TOUTES les
    sessions de la personne (« Fermer toutes mes sessions » : une session volée est coupée).

    Une écriture comme les autres : elle doit venir de la page elle-même, sinon rien n'est touché,
    pas même le cookie (24/10/2026 : un autre site pouvait déconnecter de force)."""
    from aiohttp import web
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    ses = await _session(request)
    if getattr(request, "query", {}).get("partout") == "1":
        if ses is None:
            return _json({"ok": False, "message": "Session expirée."}, 403)
        _emp, (gid, uid, _fin) = ses
        n = await fermer_sessions(None, uid)
        g = _bot.get_guild(gid) if _bot is not None else None
        m = g.get_member(uid) if g is not None else None
        await registre.noter(gid, "Accès", "site.sessions_fermees",
                             f"Toutes les sessions du site fermées par {getattr(m, 'display_name', None) or uid}",
                             auteur_id=uid, detail=f"{n} session(s) fermée(s)")
        r = _json({"ok": True, "message": "Toutes tes sessions sont fermées."})
    else:
        if ses is not None:
            async with _get_db() as db:
                await db.execute("DELETE FROM tableau_sessions WHERE empreinte=?", (ses[0],))
                await db.commit()
            _sessions.pop(ses[0], None)
        r = web.Response(status=204, headers=ENTETES)
    r.del_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")  # __Host- exige Secure
    return r
