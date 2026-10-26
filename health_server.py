"""
health_server.py — HTTP endpoint léger pour monitoring Railway (Phase 126).

Expose :
- GET /         → "Bot is alive" (200 OK)
- GET /health   → JSON {status, uptime_sec, guilds, members, latency_ms}
- GET /stats    → JSON métriques détaillées (DB, cache, tasks)

Démarre un aiohttp server léger en parallèle du bot (sur PORT env ou 8000).
Railway utilise cet endpoint pour son auto-healing : si le bot ne répond plus,
il redéploie automatiquement.

Sécurité :
- Pas de POST/PATCH/DELETE → read-only
- Pas de données sensibles exposées (juste counts et latency)
- Try/except englobant : ne crash jamais le bot

Usage dans bot.py :
    import health_server
    # Dans on_ready ou setup_hook :
    await health_server.start(bot, port=int(os.environ.get('PORT', 8000)))
"""
from __future__ import annotations

import os
import re
import time
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from discord.ext import commands

try:
    from aiohttp import web
    _AIOHTTP_OK = True
except ImportError:
    _AIOHTTP_OK = False
    print("⚠️  [health_server] aiohttp not available, server disabled")


# Référence au bot (set par start())
_bot: "commands.Bot | None" = None
_started_at: float = time.time()
_server_runner = None


async def _root_handler(request):
    """GET / → Simple alive check, retourne 200 OK."""
    return web.Response(text="✅ Bot is alive", content_type="text/plain")


async def _health_handler(request):
    """GET /health → JSON avec status + métriques minimales."""
    try:
        uptime = int(time.time() - _started_at)
        data = {
            "status": "ok",
            "uptime_sec": uptime,
        }
        if _bot is not None:
            try:
                # FIX sécu P2-3 : endpoint PUBLIC (Railway) → on ne divulgue PAS
                # l'identité du bot ni l'échelle de déploiement à un scanner anonyme.
                # On garde uniquement la latence (signe de vie), pas user/guilds.
                data["latency_ms"] = round(_bot.latency * 1000, 1)
            except Exception:
                pass
        return web.json_response(data)
    except Exception as ex:  # 24/10/2026 : adresse PUBLIQUE — le texte de l'exception va au journal, jamais dehors
        print("[HEALTH][E2] /health en échec")
        print(f"[HEALTH][E2:DETAIL] {type(ex).__name__} {ex}")
        return web.json_response({"status": "error", "error": "erreur interne"}, status=500)


#  Les travaux uniques passés (oui/non), posés par le bot : vérifier un déploiement sans Railway.
ETAT_PUBLIC: dict = {}

#  26/10/2026 (sécurité) : /stats est PUBLIQUE. Elle ne montre que des nombres, des oui/non et des dates — jamais un nom,
#  un identifiant, un texte, une mention ni le contenu d'un cadeau. Ce que le bot pose dans ETAT_PUBLIC passe par
#  `_epure` (une donnée ajoutée demain sans y penser n'en sort pas plus) : un texte devient « il y en a un », une liste
#  son nombre, une clé d'identifiant disparaît. Seules exceptions : les étapes ratées du démarrage (des noms d'étape) et
#  les erreurs comptées (`diag.releve` : « module/endroit:Type » → [nombre, heure], les identifiants déjà remplacés).
STATS_RETIRES = frozenset({"cadeaux_detail",   # les conditions et les comptes de chaque cadeau
                           "membres"})         # la taille du serveur (déjà retirée de /health le 24/10)
_STATS_LISTES = frozenset({"etapes_ratees"})
_STATS_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.]{5,15}(?:Z|[+-]\d{2}:?\d{2})?)?")
_STATS_MOT = re.compile(r"[a-z0-9_]{1,40}")
_SNOWFLAKE = 10 ** 15


def _cle_id(k: str) -> bool:
    k = k.lower()
    return k in ("id", "ids", "ticket", "message", "salon", "membre", "auteur") or k.endswith(("_id", "_ids"))


def _epure(valeur, cle: str = "", profondeur: int = 0):
    """Ce que /stats peut montrer d'une valeur de ETAT_PUBLIC (voir plus haut)."""
    if valeur is None or isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (int, float)):
        return None if abs(valeur) >= _SNOWFLAKE else valeur      # un identifiant Discord n'est pas un compte
    if profondeur > 6:
        return None
    if isinstance(valeur, str):
        return valeur if _STATS_DATE.fullmatch(valeur) else bool(valeur)
    if isinstance(valeur, dict):
        return {str(k)[:80]: _epure(v, str(k), profondeur + 1) for k, v in valeur.items()
                if str(k) not in STATS_RETIRES and not str(k).isdigit() and not (_cle_id(str(k)) and not isinstance(v, bool))}
    if isinstance(valeur, (list, tuple, set)):
        valeur = list(valeur)
        if cle in _STATS_LISTES and all(isinstance(x, str) and _STATS_MOT.fullmatch(x) for x in valeur):
            return valeur[:50]
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < _SNOWFLAKE for x in valeur):
            return valeur[:50]                                     # [nombre, heure] des erreurs comptées
        return len(valeur)
    return None


async def _stats_handler(request):
    """GET /stats → métriques détaillées (DB, cache, tasks)."""
    try:
        uptime = int(time.time() - _started_at)
        data = {
            "status": "ok",
            "uptime_sec": uptime,
        }
        if _bot is not None:
            try:
                # FIX sécu P2-3 : endpoint PUBLIC → pas de divulgation de l'échelle
                # (total_members sommé sur tous les serveurs) ni de l'identité du bot.
                # On garde la latence seule (signe de vie). Évite aussi le recalcul
                # O(guilds) à chaque hit (petit vecteur DoS).
                data["latency_ms"] = round(_bot.latency * 1000, 1)
            except Exception:
                pass
        #  14/10/2026 : la consommation, en POURCENTAGES du volume + la mémoire
        #  (dernier relevé quotidien de `stockage.bilan`, rien de recalculé ici)
        #  — aucune taille absolue, rien qui identifie le bot.
        try:
            import stockage
            if stockage.DERNIER:
                data["stockage"] = _epure(dict(stockage.DERNIER))
        except Exception as ex:  # adresse PUBLIQUE : le détail au journal, jamais dehors
            print("[HEALTH][E4] relevé du stockage illisible")
            print(f"[HEALTH][E4:DETAIL] {type(ex).__name__} {ex}")
        if ETAT_PUBLIC:
            data["travaux"] = _epure(dict(ETAT_PUBLIC))
        #  20/10/2026 : la notification instantanée YouTube — des compteurs seulement.
        try:
            import websub_youtube
            e = websub_youtube.etat()
            data["websub"] = {k: (bool(e.get(k)) if k == "actif" else int(e.get(k) or 0))
                              for k in ("actif", "abonnes", "notifications", "annonces", "rejetees")}
        except Exception as ex:
            print("[HEALTH][E1] état WebSub illisible")
            print(f"[HEALTH][E1:DETAIL] {type(ex).__name__} {ex}")
        return web.json_response(data)
    except Exception as ex:  # 24/10/2026 : adresse PUBLIQUE — le texte de l'exception va au journal, jamais dehors
        print("[HEALTH][E3] /stats en échec")
        print(f"[HEALTH][E3:DETAIL] {type(ex).__name__} {ex}")
        return web.json_response({"status": "error", "error": "erreur interne"}, status=500)


#  24/10/2026 (revue) : les médias d'un transcript viennent de chez nous (images ré-hébergées) ou de Discord,
#  jamais d'ailleurs — `img-src *` laissait l'hébergeur d'une image d'encadré voir l'adresse IP du lecteur
#  (le fondateur). `*.discordapp.net` couvre media.discordapp.net et le relais images-ext-*.
_MEDIAS_TRANSCRIPT = "'self' https://cdn.discordapp.com https://*.discordapp.net"
CSP_TRANSCRIPT = (f"default-src 'none'; img-src {_MEDIAS_TRANSCRIPT} data:; media-src {_MEDIAS_TRANSCRIPT}; "
                  "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
#  Un transcript est privé : jamais dans un moteur de recherche, même si son lien circule.
NON_INDEXE = "noindex, nofollow, noarchive"


async def _transcript_handler(request):
    """GET /t/<token> → sert la PAGE HTML rendue du transcript de ticket (Phase 281).
    Rendu inline (text/html) → le navigateur affiche la vraie page, pas du code brut."""
    token = request.match_info.get('token', '')
    try:
        import transcript_store
        p = transcript_store.transcript_path(token)
        if not p or not os.path.isfile(p):
            return web.Response(
                text="Transcript introuvable ou expiré.", status=404, content_type="text/plain",
                headers={"X-Robots-Tag": NON_INDEXE})
        return web.FileResponse(p, headers={
            #  26/10/2026 (sécurité) : une conversation de ticket est personnelle — jamais gardée en cache (ni par le
            #  navigateur d'un poste partagé, ni par un proxy).
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": NON_INDEXE,
            # défense en profondeur : images, vidéos et CSS inline, de chez nous ou de Discord ; aucun script.
            "Content-Security-Policy": CSP_TRANSCRIPT,
        })
    except Exception as ex:  # adresse PUBLIQUE : message stable, le détail à part
        print("[HEALTH][E5] transcript en échec")
        print(f"[HEALTH][E5:DETAIL] {type(ex).__name__} {ex}")
        return web.Response(text="Erreur.", status=500, content_type="text/plain")


async def _asset_handler(request):
    """GET /ta/<token>/<idx> → sert un asset ré-hébergé (image/GIF) d'un transcript."""
    token = request.match_info.get('token', '')
    idx = request.match_info.get('idx', '')
    try:
        import transcript_store
        p = transcript_store.asset_file(token, idx)
        if not p or not os.path.isfile(p):
            return web.Response(status=404, text="404", headers={"X-Robots-Tag": NON_INDEXE})
        return web.FileResponse(p, headers={
            "Cache-Control": "private, no-store",   # 26/10/2026 : l'image d'un ticket, personnelle comme lui
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "X-Robots-Tag": NON_INDEXE,
            "Content-Security-Policy": "default-src 'none'; sandbox",
        })
    except Exception as ex:  # adresse PUBLIQUE : message stable, le détail à part
        print("[HEALTH][E6] image de transcript en échec")
        print(f"[HEALTH][E6:DETAIL] {type(ex).__name__} {ex}")
        return web.Response(status=500, text="err")


#  26/10/2026 (sécurité) : un visuel est un nom simple (lettres, chiffres, « _ », « - ») et une extension d'image — rien
#  qui ressemble à un chemin (« C:… », « %00 », « .. »), et le fichier résolu reste dans `visuels/`.
_NOM_VISUEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}\.(?:gif|png)")


async def _visuel_handler(request):
    """GET /v/<nom> → un bandeau ou une icône de `visuels/` (images publiques, cache long ; montrées par Discord)."""
    try:
        import visuels
        nom = request.match_info.get('nom', '')
        f = visuels.fichier(nom) if _NOM_VISUEL.fullmatch(nom) else None
        if f is not None:
            try:
                if not os.path.realpath(f).startswith(os.path.realpath(visuels.DOSSIER) + os.sep):
                    f = None
            except (OSError, ValueError):
                f = None
        if f is None:
            return web.Response(status=404, text="404")
        return web.FileResponse(f, headers={
            "Cache-Control": "public, max-age=604800",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "cross-origin",   # une image publique, lue par Discord
        })
    except Exception as ex:  # adresse PUBLIQUE : message stable, le détail à part
        print("[HEALTH][E7] visuel en échec")
        print(f"[HEALTH][E7:DETAIL] {type(ex).__name__} {ex}")
        return web.Response(status=500, text="err")


async def _tableau(request):
    """Le site du staff : `tableau` sert chaque adresse (lien à usage unique, puis session)."""
    import tableau
    nom = request.match_info.route.name or ""
    return await getattr(tableau, nom.split(":", 1)[1])(request)


async def _vitrine(request):
    """La vitrine PUBLIQUE de l'équipage (`site_vitrine`) : sans session, lecture seule, données publiques seulement."""
    import site_vitrine
    nom = request.match_info.route.name or ""
    return await getattr(site_vitrine, nom.split(":", 1)[1])(request)


async def _websub(request):
    """YouTube (hub WebSub) : vérification d'abonnement (GET) et vidéos publiées (POST)."""
    import websub_youtube
    if request.method == "POST":
        return await websub_youtube.notification(request)
    return await websub_youtube.verification(request)


#  26/10/2026 (sécurité) : les en-têtes de base de TOUTE réponse, même celles qu'aiohttp fabrique seul (404 d'une adresse
#  inconnue, 405) et celles des adresses publiques (/, /health, /stats, /t/, /v/, /websub). Ceux qu'une adresse pose
#  elle-même passent avant (`setdefault`). Le nom et la version du serveur ne sortent plus (« Server »).
ENTETES_BASE = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Resource-Policy": "same-origin",
}
#  Des politiques de DOCUMENT (une page HTML) : sur un script, une image ou du JSON, elles ne protègent rien et
#  alourdissaient chaque fichier du site (mesuré : ≈ 120 octets × 60 fichiers à chaque ouverture).
ENTETES_DOCUMENT = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}


async def _entetes_securite(request, response) -> None:
    for k, v in ENTETES_BASE.items():
        response.headers.setdefault(k, v)
    if "text/html" in (response.headers.get("Content-Type") or ""):
        for k, v in ENTETES_DOCUMENT.items():
            response.headers.setdefault(k, v)
    response.headers["Server"] = "capitainerie"
    #  Une erreur fabriquée par aiohttp (404, 405…) : jamais gardée en cache, jamais indexée.
    if response.status >= 400:
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")


def construire_app():
    """Toutes les adresses servies par le bot (testées telles quelles)."""
    app = web.Application()
    app.on_response_prepare.append(_entetes_securite)
    app.router.add_get('/', _root_handler)
    app.router.add_get('/health', _health_handler)
    app.router.add_get('/stats', _stats_handler)
    app.router.add_get('/t/{token}', _transcript_handler)       # Phase 281 : page transcript
    app.router.add_get('/ta/{token}/{idx}', _asset_handler)      # assets ré-hébergés
    app.router.add_get('/v/{nom}', _visuel_handler)               # bandeaux et icônes
    app.router.add_get('/websub/youtube', _websub)                # YouTube : vidéo publiée, à la seconde
    app.router.add_post('/websub/youtube', _websub)
    #  Site du staff : l'espace (session) AVANT le lien à usage unique, sinon « espace » serait
    #  pris pour un jeton. 25/10/2026 (site v2) : la page est à `/tableau/espace/` (barre finale : ses
    #  adresses relatives et la portée du service worker) ; sans la barre, on y renvoie.
    app.router.add_get('/tableau/espace', _tableau, name="tableau:vers_espace")
    app.router.add_get('/tableau/espace/', _tableau, name="tableau:page")
    app.router.add_get('/tableau/espace/sw.js', _tableau, name="tableau:service_worker")
    app.router.add_get('/tableau/espace/s/{chemin:.+}', _tableau, name="tableau:statique")
    app.router.add_get('/tableau/espace/media/{media:.+}', _tableau, name="tableau:media")
    app.router.add_route('GET', '/tableau/espace/api/{nom:.+}', _tableau, name="tableau:api_site")
    app.router.add_route('POST', '/tableau/espace/api/{nom:.+}', _tableau, name="tableau:api_site_post")
    app.router.add_post('/tableau/espace/sync', _tableau, name="tableau:sync")
    app.router.add_get('/tableau/espace/direct', _tableau, name="tableau:direct")   # la présence en direct (WebSocket)
    app.router.add_get('/tableau/espace/donnees', _tableau, name="tableau:api")
    app.router.add_get('/tableau/espace/membre', _tableau, name="tableau:membre")
    app.router.add_get('/tableau/espace/recherche', _tableau, name="tableau:recherche")
    app.router.add_get('/tableau/espace/export', _tableau, name="tableau:export")
    app.router.add_get('/tableau/espace/conversation', _tableau, name="tableau:conversation")
    app.router.add_post('/tableau/espace/action', _tableau, name="tableau:action")
    app.router.add_post('/tableau/espace/sortir', _tableau, name="tableau:sortir")
    #  26/10/2026 : le site de l'équipage (les membres du rôle du clan, en lecture seule ; la tête y compose l'accueil).
    #  Avant le lien à usage unique, sinon « equipage » serait pris pour un jeton. AUCUNE écriture n'y entre.
    app.router.add_get('/tableau/equipage', _tableau, name="tableau:vers_equipage")
    app.router.add_get('/tableau/equipage/', _tableau, name="tableau:page_equipage")
    app.router.add_get('/tableau/equipage/api/{nom:.+}', _tableau, name="tableau:api_equipage")
    app.router.add_post('/tableau/equipage/api/{nom:.+}', _tableau, name="tableau:api_equipage_refus")
    app.router.add_get('/tableau/{jeton}', _tableau, name="tableau:entree")
    #  27/10/2026 : la vitrine PUBLIQUE de l'équipage (le lien officiel à partager) — ces cinq adresses, en lecture.
    app.router.add_get('/equipage', _vitrine, name="vitrine:page")
    app.router.add_get('/equipage/', _vitrine, name="vitrine:vers_vitrine")
    app.router.add_get('/equipage/donnees', _vitrine, name="vitrine:donnees")
    app.router.add_get('/equipage/banniere.png', _vitrine, name="vitrine:banniere")
    app.router.add_get('/equipage/image/{jeton}', _vitrine, name="vitrine:image")
    return app


async def start(bot_instance, port: int = 8000) -> bool:
    """Démarre le serveur HTTP en background.

    Returns:
        True si démarré avec succès, False sinon.
    """
    global _bot, _server_runner, _started_at
    _bot = bot_instance
    if _server_runner is not None:  # déjà démarré : ni second serveur, ni compteur remis à zéro
        return True
    _started_at = time.time()

    if not _AIOHTTP_OK:
        print("🚨 [health_server] aiohttp non installé : /health ne répondra pas")
        return False

    try:
        app = construire_app()

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        _server_runner = runner

        print(f"🌐 [health_server] HTTP endpoint started on :{port} (/health, /stats)")
        return True
    except OSError as ex:
        # Port déjà utilisé : pas critique, on log et on continue
        print(f"⚠️  [health_server] port {port} unavailable: {ex} — bot continues normally")
        return False
    except Exception as ex:
        print(f"⚠️  [health_server] failed to start: {ex}")
        return False


__all__ = ["start"]
