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
    except Exception as ex:
        return web.json_response({"status": "error", "error": str(ex)}, status=500)


#  Les travaux uniques passés (oui/non), posés par le bot : vérifier un déploiement sans Railway.
ETAT_PUBLIC: dict = {}


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
                data["stockage"] = dict(stockage.DERNIER)
        except Exception:
            pass
        if ETAT_PUBLIC:
            data["travaux"] = dict(ETAT_PUBLIC)
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
    except Exception as ex:
        return web.json_response({"status": "error", "error": str(ex)}, status=500)


async def _transcript_handler(request):
    """GET /t/<token> → sert la PAGE HTML rendue du transcript de ticket (Phase 281).
    Rendu inline (text/html) → le navigateur affiche la vraie page, pas du code brut."""
    token = request.match_info.get('token', '')
    try:
        import transcript_store
        p = transcript_store.transcript_path(token)
        if not p or not os.path.isfile(p):
            return web.Response(
                text="Transcript introuvable ou expiré.", status=404, content_type="text/plain")
        return web.FileResponse(p, headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # défense en profondeur : autorise images + CSS inline, bloque TOUT script/objet.
            "Content-Security-Policy": (
                "default-src 'none'; img-src * data:; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'"),
        })
    except Exception as ex:
        print(f"[health_server transcript] {ex}")
        return web.Response(text="Erreur.", status=500, content_type="text/plain")


async def _asset_handler(request):
    """GET /ta/<token>/<idx> → sert un asset ré-hébergé (image/GIF) d'un transcript."""
    token = request.match_info.get('token', '')
    idx = request.match_info.get('idx', '')
    try:
        import transcript_store
        p = transcript_store.asset_file(token, idx)
        if not p or not os.path.isfile(p):
            return web.Response(status=404, text="404")
        return web.FileResponse(p, headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        })
    except Exception as ex:
        print(f"[health_server asset] {ex}")
        return web.Response(status=500, text="err")


async def _visuel_handler(request):
    """GET /v/<nom> → un bandeau ou une icône de `visuels/` (images publiques, cache long)."""
    try:
        import visuels
        f = visuels.fichier(request.match_info.get('nom', ''))
        if f is None:
            return web.Response(status=404, text="404")
        return web.FileResponse(f, headers={
            "Cache-Control": "public, max-age=604800",
            "X-Content-Type-Options": "nosniff",
        })
    except Exception as ex:
        print(f"[health_server visuel] {ex}")
        return web.Response(status=500, text="err")


async def _tableau(request):
    """Le site du staff : `tableau` sert chaque adresse (lien à usage unique, puis session)."""
    import tableau
    nom = request.match_info.route.name or ""
    return await getattr(tableau, nom.split(":", 1)[1])(request)


async def _websub(request):
    """YouTube (hub WebSub) : vérification d'abonnement (GET) et vidéos publiées (POST)."""
    import websub_youtube
    if request.method == "POST":
        return await websub_youtube.notification(request)
    return await websub_youtube.verification(request)


def construire_app():
    """Toutes les adresses servies par le bot (testées telles quelles)."""
    app = web.Application()
    app.router.add_get('/', _root_handler)
    app.router.add_get('/health', _health_handler)
    app.router.add_get('/stats', _stats_handler)
    app.router.add_get('/t/{token}', _transcript_handler)       # Phase 281 : page transcript
    app.router.add_get('/ta/{token}/{idx}', _asset_handler)      # assets ré-hébergés
    app.router.add_get('/v/{nom}', _visuel_handler)               # bandeaux et icônes
    app.router.add_get('/websub/youtube', _websub)                # YouTube : vidéo publiée, à la seconde
    app.router.add_post('/websub/youtube', _websub)
    #  Site du staff : l'espace (session) AVANT le lien à usage unique, sinon « espace » serait
    #  pris pour un jeton.
    app.router.add_get('/tableau/espace', _tableau, name="tableau:page")
    app.router.add_get('/tableau/espace/donnees', _tableau, name="tableau:api")
    app.router.add_get('/tableau/espace/membre', _tableau, name="tableau:membre")
    app.router.add_get('/tableau/espace/recherche', _tableau, name="tableau:recherche")
    app.router.add_get('/tableau/espace/export', _tableau, name="tableau:export")
    app.router.add_post('/tableau/espace/action', _tableau, name="tableau:action")
    app.router.add_post('/tableau/espace/sortir', _tableau, name="tableau:sortir")
    app.router.add_get('/tableau/{jeton}', _tableau, name="tableau:entree")
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
