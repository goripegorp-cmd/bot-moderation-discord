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

import asyncio
import os
import time
from typing import TYPE_CHECKING

import discord

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


async def start(bot_instance, port: int = 8000) -> bool:
    """Démarre le serveur HTTP en background.

    Returns:
        True si démarré avec succès, False sinon.
    """
    global _bot, _server_runner, _started_at
    _bot = bot_instance
    _started_at = time.time()

    if not _AIOHTTP_OK:
        print("⚠️  [health_server] aiohttp non installé, skip")
        return False

    try:
        app = web.Application()
        app.router.add_get('/', _root_handler)
        app.router.add_get('/health', _health_handler)
        app.router.add_get('/stats', _stats_handler)
        app.router.add_get('/t/{token}', _transcript_handler)       # Phase 281 : page transcript
        app.router.add_get('/ta/{token}/{idx}', _asset_handler)      # assets ré-hébergés

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


async def stop():
    """Arrête le serveur HTTP (à appeler dans bot.close si nécessaire)."""
    global _server_runner
    if _server_runner is not None:
        try:
            await _server_runner.cleanup()
            _server_runner = None
            print("🌐 [health_server] stopped")
        except Exception as ex:
            print(f"[health_server stop] {ex}")


__all__ = ["start", "stop"]
