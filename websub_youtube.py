"""websub_youtube.py — YouTube prévient le bot dès qu'une vidéo sort (19/10/2026).

« Ça a pris plus de 10 minutes à se publier… que ce soit plus rapide, que le tracking soit
puissant. » Le flux RSS de YouTube se met à jour avec retard (souvent 5 à 15 minutes, parfois
plus pour les IP de serveurs). YouTube propose WebSub (PubSubHubbub) : le bot s'abonne une fois
par chaîne auprès du hub de Google, et c'est le hub qui appelle le bot au moment où la vidéo est
publiée. Le relevé à la minute reste le filet ; `publications` empêche tout doublon entre les deux.

Sécurité : chaque notification est signée (HMAC-SHA1, secret propre au bot) et n'est lue qu'après
vérification de la signature ; elle n'est retenue que pour une chaîne réellement suivie ; corps
limité à CORPS_MAX ; une vidéo plus vieille que FRAICHEUR (simple mise à jour) est ignorée.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

HUB = "https://pubsubhubbub.appspot.com/subscribe"
BAIL = 5 * 86400
RENOUVELER = 86400
CORPS_MAX = 256 * 1024
FRAICHEUR = 3 * 86400
NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
_UC = re.compile(r"^UC[\w-]{20,}$")
_secret = b""
_base = ""
_chaines = None
_annoncer = None
_log = print
_abonnes: dict = {}
_attentes: dict = {}  # (chaîne, mode) -> heure de NOTRE demande : le hub ne confirme que celles-là
ATTENTE = 600
_taches: set = set()
_stats = {"notifications": 0, "rejetees": 0, "annonces": 0, "dernier": 0}


def setup(*, secret: str, base_url: str, chaines, annoncer, log=None):
    """`chaines()` (asynchrone) → les identifiants `UC…` suivis ; `annoncer(uc, video)`
    (asynchrone) → publie la vidéo partout où la chaîne est suivie."""
    global _secret, _base, _chaines, _annoncer, _log
    _secret, _base = str(secret).encode(), (base_url or "").rstrip("/")
    _chaines, _annoncer, _log = chaines, annoncer, log or print
    _abonnes.clear()


def actif() -> bool:
    return bool(_secret and _base.startswith("https://") and _chaines and _annoncer)


def sujet(uc: str) -> str:
    return f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={uc}"


def rappel() -> str:
    return f"{_base}/websub/youtube"


def uc_du_sujet(topic: str) -> str:
    m = re.search(r"channel_id=(UC[\w-]{20,})", str(topic or ""))
    return m.group(1) if m else ""


async def abonner(session, uc: str, mode: str = "subscribe") -> bool:
    _attentes[(uc, mode)] = time.time()
    donnees = {"hub.callback": rappel(), "hub.topic": sujet(uc), "hub.verify": "async", "hub.mode": mode,
               "hub.lease_seconds": str(BAIL), "hub.secret": _secret.decode()}
    try:
        async with session.post(HUB, data=donnees, timeout=15) as r:
            if r.status in (202, 204):
                return True
            _log("[WEBSUB][E1] abonnement refusé par le hub")
            _log(f"[WEBSUB][E1:DETAIL] {uc} {mode} HTTP {r.status}")
    except Exception as ex:  # réseau : réessayé au prochain entretien
        _log("[WEBSUB][E2] hub injoignable")
        _log(f"[WEBSUB][E2:DETAIL] {uc} {type(ex).__name__} {ex}")
    return False


async def entretenir(session, maintenant: float | None = None) -> dict:
    """Abonne les chaînes suivies (et renouvelle à un jour de l'échéance), désabonne les autres."""
    if not actif():
        return {"actif": False}
    t = maintenant or time.time()
    suivies = set(await _chaines())
    faits = 0
    for uc in sorted(suivies):
        if _abonnes.get(uc, 0) - t < RENOUVELER and await abonner(session, uc):
            _abonnes[uc] = t + BAIL
            faits += 1
    for uc in [u for u in _abonnes if u not in suivies]:
        await abonner(session, uc, "unsubscribe")
        _abonnes.pop(uc, None)
    return {"actif": True, "suivies": len(suivies), "abonnements": faits}


def lire_atom(corps: bytes) -> list[dict]:
    """Les vidéos annoncées par le hub : identifiant, chaîne, titre, dates."""
    racine = ET.fromstring(corps)
    out = []
    for e in racine.findall("atom:entry", NS):
        vid, uc = e.findtext("yt:videoId", "", NS), e.findtext("yt:channelId", "", NS)
        if not vid or not _UC.match(uc or ""):
            continue
        out.append({"video_id": vid, "uc": uc, "titre": (e.findtext("atom:title", "", NS) or "").strip(),
                    "publie": e.findtext("atom:published", "", NS), "maj": e.findtext("atom:updated", "", NS)})
    return out


def _horodatage(iso: str) -> float:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


async def verification(request):
    """Le hub vérifie que c'est bien nous qui avons demandé l'abonnement (GET)."""
    from aiohttp import web
    q = request.query
    mode, defi = q.get("hub.mode", ""), q.get("hub.challenge", "")
    uc = uc_du_sujet(q.get("hub.topic", ""))
    if not defi or not uc or len(defi) > 512 or not actif():
        return web.Response(status=400, text="")
    # Seulement ce que le bot a demandé lui-même il y a moins de ATTENTE secondes : sinon n'importe
    # qui réabonnait notre adresse avec son propre secret, et les vraies notifications étaient rejetées.
    if time.time() - _attentes.get((uc, mode), 0) > ATTENTE:
        return web.Response(status=404, text="")
    suivies = set(await _chaines())
    if (mode == "subscribe" and uc in suivies) or (mode == "unsubscribe" and uc not in suivies):
        _attentes.pop((uc, mode), None)
        if mode == "subscribe":
            bail = q.get("hub.lease_seconds", "")
            # Plafonnée : une durée gonflée empêchait tout renouvellement.
            _abonnes[uc] = time.time() + min(int(bail) if bail.isdigit() else BAIL, BAIL)
        return web.Response(text=defi, content_type="text/plain")
    return web.Response(status=404, text="")


async def notification(request, maintenant: float | None = None):
    """Une vidéo publiée (POST du hub) : signature vérifiée AVANT de lire le contenu."""
    from aiohttp import web
    if not actif() or (request.content_length or 0) > CORPS_MAX:
        return web.Response(status=413 if actif() else 404, text="")
    try:
        corps = await request.read()  # borné par le serveur (client_max_size), puis ici
    except Exception as ex:  # corps trop gros ou coupé
        _log("[WEBSUB][E5] notification illisible")
        _log(f"[WEBSUB][E5:DETAIL] {type(ex).__name__} {ex}")
        return web.Response(status=413, text="")
    signature = request.headers.get("X-Hub-Signature", "")
    attendue = "sha1=" + hmac.new(_secret, corps, hashlib.sha1).hexdigest()
    if len(corps) > CORPS_MAX or not hmac.compare_digest(signature, attendue):
        _stats["rejetees"] += 1
        _log("[WEBSUB][E3] notification non signée ignorée")
        return web.Response(status=202, text="")
    _stats["notifications"] += 1
    _stats["dernier"] = int(time.time())
    try:
        videos = lire_atom(corps)
    except ET.ParseError:
        return web.Response(status=202, text="")
    t = maintenant or time.time()
    suivies = set(await _chaines())
    for v in videos:
        quand = _horodatage(v["publie"])
        if v["uc"] not in suivies or not quand or t - quand > FRAICHEUR:
            continue
        tache = asyncio.get_running_loop().create_task(_annoncer_sans_casser(v))
        _taches.add(tache)
        tache.add_done_callback(_taches.discard)
    return web.Response(status=204, text="")


async def _annoncer_sans_casser(video: dict) -> None:
    try:
        if await _annoncer(video["uc"], video):
            _stats["annonces"] += 1
    except Exception as ex:  # la publication échoue : le relevé à la minute la rattrapera
        _log("[WEBSUB][E4] annonce impossible")
        _log(f"[WEBSUB][E4:DETAIL] {video.get('video_id')} {type(ex).__name__} {ex}")


def etat() -> dict:
    return dict(_stats, abonnes=len(_abonnes), actif=actif())
