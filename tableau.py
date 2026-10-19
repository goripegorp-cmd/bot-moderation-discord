"""tableau.py — le tableau de bord web des recrutements Rell Seas (19/10/2026).

« Pas des .txt : un vrai site interactif, ultra bien fait, où quand on clique ça fait un
récap des candidatures Rell Seas, des tickets ouverts et tout — à chaque fois qu'un truc est
fait, de vraies infos officielles. »

Servi par le bot lui-même (`/tableau/<jeton>`), données lues en direct dans sa base à chaque
ouverture et toutes les minutes. Les données sont personnelles : un lien PERSONNEL signé,
valable 24 h. « Seulement le rôle staff et au-dessus — direction, les rôles les plus élevés » :
vérifié quand le lien est demandé ET à chaque lecture. Les tickets sont triés par type
(Rell Seas, tickets normaux) avec leurs vraies statistiques.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from pathlib import Path

import recrutements
import rellseas_panneau

DUREE = 24 * 3600
PAGE = (Path(__file__).resolve().parent / "tableau_page.html").read_text(encoding="utf-8")
EXPIRE = ("<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' "
          "content='width=device-width,initial-scale=1'><title>Lien expiré</title><body "
          "style='margin:0;min-height:100vh;display:grid;place-items:center;background:#070b14;"
          "color:#e2e8f0;font-family:Segoe UI,system-ui,sans-serif;text-align:center'><div>"
          "<h1 style='font-size:22px'>Ce lien n'est plus valable</h1><p style='color:#94a3b8'>"
          "Demande un nouveau lien dans Discord : <b>/rellseas</b> → <b>Tableau de bord</b>.</p>"
          "</div></body></html>")
ENTETES = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": ("default-src 'none'; img-src https://cdn.discordapp.com "
                                "https://media.discordapp.net data:; style-src 'unsafe-inline'; "
                                "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
}

_cle = b""
_base = ""
_bot = None
_radie = "🚫 Radié"
_cfg = _get_db = _mesurer_groupe = _autorise_membre = None

#  Le casier mélange les sanctions décidées (staff ou escalade) et les détections du bot.
SANCTIONS = {"warn": "Avertissement", "mute": "Mute", "kick": "Expulsion", "ban": "Bannissement"}
DETECTIONS = {"insulte": "Insulte", "menace": "Menace", "discrimination": "Discrimination",
              "haine": "Haine", "incitation": "Incitation", "harcelement": "Harcèlement",
              "grooming": "Protection des mineurs", "protection": "Filtre automatique"}
GROUPES = {"warn": "Avertissements", "mute": "Mutes", "kick": "Expulsions et bans",
           "ban": "Expulsions et bans"}
_cache: dict = {}
_log = print


def setup(*, bot, cle: str, base_url, cfg, get_db, mesurer_groupe, autorise_membre, radie=None,
          log=None):
    """`autorise_membre(g, membre, c)` → la personne est-elle staff ou au-dessus ?"""
    global _bot, _cle, _base, _cfg, _get_db, _mesurer_groupe, _autorise_membre, _log, _radie
    _bot, _cle, _base = bot, cle.encode(), (base_url or "").rstrip("/")
    _radie = radie or _radie
    _cfg, _get_db, _mesurer_groupe, _autorise_membre = cfg, get_db, mesurer_groupe, autorise_membre
    _log = log or print


# ─── Le lien personnel ──────────────────────────────────────────────────────

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jeton(guild_id: int, user_id: int, portee: str, maintenant: float | None = None) -> str:
    charge = f"{int(guild_id)}.{int(user_id)}.{portee}.{int((maintenant or time.time()) + DUREE)}"
    sig = hmac.new(_cle, charge.encode(), hashlib.sha256).digest()[:18]
    return f"{_b64(charge.encode())}.{_b64(sig)}"


def lire_jeton(j: str, maintenant: float | None = None) -> dict | None:
    try:
        a, b = j.split(".", 1)
        charge, sig = _unb64(a), _unb64(b)
        g, u, p, e = charge.decode().split(".")
        g, u, e = int(g), int(u), int(e)
    except (ValueError, UnicodeDecodeError):
        return None
    if not _cle or not hmac.compare_digest(sig, hmac.new(_cle, charge, hashlib.sha256).digest()[:18]):
        return None
    if e < (maintenant or time.time()) or p not in ("rs", "tout"):
        return None
    return {"g": g, "u": u, "p": p, "e": e}


async def lien_pour(i) -> tuple[str | None, str]:
    """(lien personnel, "") — ou (None, la raison du refus, dite telle quelle à la personne)."""
    if not _base or not _cle or i.guild is None:
        return None, "Le tableau de bord n'est pas joignable pour le moment."
    if _autorise_membre is None or not _autorise_membre(i.guild, i.user, await _cfg(i.guild.id)):
        return None, "Réservé au staff et aux rôles au-dessus (direction…)."
    return f"{_base}/tableau/{jeton(i.guild.id, i.user.id, 'tout')}", ""


# ─── Les données ────────────────────────────────────────────────────────────

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


async def _clan(g, c) -> dict:
    role = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    if role is None:
        return {"role": "", "membres": []}
    membres = [m for m in role.members if not m.bot]
    mesures = await _mesurer_groupe(g.id, membres) if _mesurer_groupe and membres else {}
    avatars = {m.id: str(m.display_avatar.with_size(64).url) for m in membres}
    return {"role": role.name, "membres": [
        {"id": str(x["id"]), "nom": x["nom"], "pseudo": x["pseudo"], "avatar": avatars.get(x["id"], ""),
         "statut": x["statut"], "rang": x["rang"], "jours": x["jours"], "derniere": x["derniere"],
         "arrivee": x["arrivee"]} for x in rellseas_panneau.lignes_clan(membres, mesures)]}


def _mediane(valeurs) -> int:
    v = sorted(x for x in valeurs if x is not None and x >= 0)
    return int(v[len(v) // 2]) if v else 0


async def _tickets(g, c) -> dict:
    """Tous les tickets, triés par type : ouverts, fermés, délais réels, staff, mois."""
    panneaux = c.get("ticket_panels") or {}
    rell = rellseas_panneau.panneaux_tickets(c)
    async with _get_db() as db:
        tickets = await recrutements._lignes(
            db, "SELECT id, user_id, panel_id, claimed_by, status, created_at, channel_id FROM tickets"
                " WHERE guild_id=? ORDER BY id", (g.id,))
        evts = await recrutements._lignes(
            db, "SELECT ticket_id, kind, actor_id, created_unix FROM ticket_log_events"
                " WHERE guild_id=? AND kind IN ('claim', 'close') ORDER BY id", (g.id,))
        audit = await recrutements._lignes(
            db, "SELECT channel_id, action, actor_id, at FROM ticket_audit"
                " WHERE guild_id=? AND action IN ('claim', 'close') ORDER BY id", (g.id,))
    prises, fins = {}, {}
    for tid, kind, actor, t in evts:
        (prises if kind == "claim" else fins).setdefault(tid, (int(t or 0), int(actor or 0)))
    prises_salon, fins_salon = {}, {}
    for salon, action, actor, at in audit:
        (prises_salon if action == "claim" else fins_salon).setdefault(
            salon, (recrutements._unix(at), int(actor or 0)))
    types, ouverts, staff, mois = {}, [], {}, {}
    debut_mois = time.time() - 365 * 86400
    for tid, uid, pid, pris, statut, cree, salon in tickets:
        nom = str((panneaux.get(pid) or {}).get("name") or "Sans type")
        est_rell = str(pid or "") in rell
        t = types.setdefault(nom, {"nom": nom, "rellseas": est_rell, "total": 0, "ouverts": 0,
                                   "fermes": 0, "sans_prise": 0, "_prise": [], "_fin": []})
        t["rellseas"] = t["rellseas"] or est_rell
        t["total"] += 1
        ouvert = recrutements._unix(cree)
        prise = prises.get(tid) or prises_salon.get(salon)
        fin_t = fins.get(tid) or fins_salon.get(salon)
        pris_par = int(pris or 0) or (prise[1] if prise else 0)
        if pris_par:
            staff.setdefault(pris_par, {"pris": 0, "fermes": 0})["pris"] += 1
        if statut == "open":
            t["ouverts"] += 1
            ouverts.append(dict(_ident(g, uid), ticket=tid, type=nom, rellseas=est_rell, ouvert=ouvert,
                                pris_par=_nom(g, pris_par),
                                salon=f"https://discord.com/channels/{g.id}/{salon}" if salon else ""))
        else:
            t["fermes"] += 1
            if not pris_par:
                t["sans_prise"] += 1
            if fin_t and fin_t[1]:
                staff.setdefault(fin_t[1], {"pris": 0, "fermes": 0})["fermes"] += 1
            if ouvert and fin_t and fin_t[0]:
                t["_fin"].append(fin_t[0] - ouvert)
        if ouvert and prise and prise[0]:
            t["_prise"].append(prise[0] - ouvert)
        if ouvert and ouvert >= debut_mois:
            cle_m = recrutements.cle_mois(datetime.fromtimestamp(ouvert, timezone.utc))
            groupe = "Rell Seas" if est_rell else "Tickets normaux"
            mois.setdefault(cle_m, {"Rell Seas": 0, "Tickets normaux": 0})[groupe] += 1
    for t in types.values():
        t["prise_mediane"] = _mediane(t.pop("_prise"))
        t["fermeture_mediane"] = _mediane(t.pop("_fin"))
    return {
        "types": sorted(types.values(), key=lambda t: (not t["rellseas"], -t["total"], t["nom"])),
        "ouverts": sorted(ouverts, key=lambda o: (not o["rellseas"], o["type"], o["ouvert"] or 0)),
        "staff": sorted(({"nom": _nom(g, k), **v} for k, v in staff.items()),
                        key=lambda x: -(x["pris"] + x["fermes"]))[:15],
        "mois": dict(sorted(mois.items())[-12:]),
    }


def _libelle(typ: str) -> str:
    return SANCTIONS.get(typ) or DETECTIONS.get(typ) or (typ or "Autre").capitalize()


async def _sanctions(g) -> dict:
    """Le casier, en chiffres : par type, par mois, par modérateur, automatique ou non, les
    membres qui reviennent le plus, et ce qui est en cours à l'instant sur le serveur."""
    robot = getattr(getattr(_bot, "user", None), "id", 0) or 0
    async with _get_db() as db:
        rows = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? ORDER BY id DESC LIMIT 5000", (g.id,))
        restreints = await recrutements._lignes(
            db, "SELECT user_id, restricted_at, duration, reason, restricted_by FROM restricted_members"
                " WHERE guild_id=?", (g.id,))
    maintenant = time.time()
    par_type, mois, staff, membres = {}, {}, {}, {}
    auto = manuel = recents_30 = 0
    recentes = []
    for iid, uid, mod, typ, raison, duree, cree in rows:
        typ = str(typ or "autre").lower()
        quand = recrutements._unix(cree)
        est_auto = not mod or int(mod) == robot
        par_type[typ] = par_type.get(typ, 0) + 1
        auto, manuel = auto + est_auto, manuel + (not est_auto)
        if quand and maintenant - quand <= 30 * 86400:
            recents_30 += 1
        if quand and maintenant - quand <= 365 * 86400:
            cle_m = recrutements.cle_mois(datetime.fromtimestamp(quand, timezone.utc))
            groupe = GROUPES.get(typ, "Détections")
            mois.setdefault(cle_m, {"Avertissements": 0, "Mutes": 0, "Expulsions et bans": 0,
                                    "Détections": 0})[groupe] += 1
        if not est_auto:
            st = staff.setdefault(int(mod), {"total": 0, "types": {}})
            st["total"] += 1
            st["types"][typ] = st["types"].get(typ, 0) + 1
        if quand and maintenant - quand <= 90 * 86400:
            fiche = membres.setdefault(int(uid or 0), {"total": 0, "types": {}, "historique": []})
            fiche["total"] += 1
            fiche["types"][typ] = fiche["types"].get(typ, 0) + 1
            if len(fiche["historique"]) < 12:
                fiche["historique"].append({"type": typ, "libelle": _libelle(typ), "raison": str(raison or "")[:200],
                                            "duree": str(duree or ""), "date": quand,
                                            "par": "Automatique" if est_auto else _nom(g, mod)})
        if len(recentes) < 150:
            recentes.append(dict(_ident(g, uid), sanction=iid, type=typ, libelle=_libelle(typ),
                                 groupe=GROUPES.get(typ, "Détections"), raison=str(raison or "")[:300],
                                 duree=str(duree or ""), date=quand, auto=est_auto,
                                 par="Automatique" if est_auto else _nom(g, mod)))
    a_surveiller = sorted(membres.items(), key=lambda kv: -kv[1]["total"])[:15]
    radie = next((r for r in getattr(g, "roles", []) if r.name == _radie), None)
    mutes = [m for m in getattr(g, "members", []) if getattr(m, "is_timed_out", lambda: False)()]
    return {
        "total": len(rows), "trente_jours": recents_30, "auto": auto, "manuel": manuel,
        "libelles": {k: _libelle(k) for k in par_type},
        "types": sorted(({"type": k, "libelle": _libelle(k), "n": v, "detection": k not in SANCTIONS}
                         for k, v in par_type.items()), key=lambda t: -t["n"]),
        "mois": dict(sorted(mois.items())[-12:]),
        "staff": sorted(({"nom": _nom(g, k), **v} for k, v in staff.items()), key=lambda x: -x["total"])[:15],
        "surveiller": [dict(_ident(g, uid), **f) for uid, f in a_surveiller if uid],
        "recentes": recentes,
        "actives": {
            "mutes": [dict(_ident(g, m.id), jusqu=int(m.timed_out_until.timestamp()) if m.timed_out_until else None)
                      for m in mutes],
            "radies": [_ident(g, m.id) for m in (radie.members if radie else [])],
            "restreints": [dict(_ident(g, uid), depuis=recrutements._unix(depuis), raison=str(raison or "")[:200],
                                par=_nom(g, par)) for uid, depuis, _d, raison, par in restreints],
        },
    }


async def donnees(g, portee: str = "tout") -> dict:
    cle = (g.id, portee)
    deja = _cache.get(cle)
    if deja and time.time() - deja[0] < 15:
        return deja[1]
    c = await _cfg(g.id)
    cand = await recrutements.candidatures(g)
    candidats = [dict(_ident(g, d["candidat_id"], d["nom"]), statut=d["statut"], ticket=d["ticket"],
                      ouvert=d["ouvert"], ferme=d["ferme"], pris_par=_nom(g, d["pris_par"]),
                      ferme_par=_nom(g, d["ferme_par"]), motif=d["raison"],
                      reponses=list(d["reponses"].items()), transcript=d["transcript"] or "",
                      candidatures=d["dates"])
                 for d in cand["fiches"]]
    en_cours = [dict(_ident(g, o["candidat_id"]), statut="en_cours", ticket=o["ticket"],
                     ouvert=o["ouvert"], pris_par=_nom(g, o["pris_par"]),
                     reponses=list(o["reponses"].items()),
                     salon=f"https://discord.com/channels/{g.id}/{o['salon']}" if o["salon"] else "")
                for o in cand["en_cours"]]
    out = {
        "serveur": {"nom": g.name, "icone": str(g.icon.with_size(128).url) if g.icon else ""},
        "genere": datetime.now(timezone.utc).isoformat(),
        "portee": portee,
        "candidats": candidats,
        "en_cours": en_cours,
        "ecartes": cand["vides"] + cand["doublons"],
        "tickets": await _tickets(g, c),
        "clan": await _clan(g, c),
        "sanctions": await _sanctions(g),
    }
    _cache[cle] = (time.time(), out)
    return out


# ─── Les routes (servies par health_server) ─────────────────────────────────

async def _acces(request):
    """Le lien est signé ET la personne est encore staff ou au-dessus — revérifié à chaque fois."""
    j = lire_jeton(request.match_info.get("jeton", ""))
    g = _bot.get_guild(j["g"]) if j and _bot else None
    m = g.get_member(j["u"]) if g else None
    if m is None or _autorise_membre is None or not _autorise_membre(g, m, await _cfg(g.id)):
        return None, None
    return j, g


async def page(request):
    from aiohttp import web
    j, _g = await _acces(request)
    if j is None:
        return web.Response(status=403, text=EXPIRE, content_type="text/html", headers=ENTETES)
    return web.Response(text=PAGE, content_type="text/html", headers=ENTETES)


async def api(request):
    from aiohttp import web
    j, g = await _acces(request)
    if j is None:
        return web.json_response({"erreur": "lien expiré"}, status=403, headers=ENTETES)
    try:
        d = await donnees(g, j["p"])
    except Exception as ex:  # la page affiche l'erreur ; le détail part au journal
        _log("[TABLEAU][E1] données indisponibles")
        _log(f"[TABLEAU][E1:DETAIL] {type(ex).__name__} {ex}")
        return web.json_response({"erreur": "données indisponibles"}, status=500, headers=ENTETES)
    return web.json_response(dict(d, expire=j["e"]), headers=ENTETES)
