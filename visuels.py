"""visuels.py — l'identité visuelle : bandeaux animés des menus, icônes des boutons (19/10/2026).

Les images sont rendues hors ligne par `outils/visuels.py` dans `visuels/`, servies par le
serveur du bot (`/v/<nom>`, cache long) et affichées par Discord dans les menus. Les icônes
deviennent des émojis de l'application, installés une fois. Sans domaine public ou sans
fichier, chaque menu retombe sur un titre texte.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp

import discord

DOSSIER = Path(__file__).resolve().parent / "visuels"
VERSION = "1"
_base = ""
_servi = None
_icones: dict = {}
_log = print


def setup(*, base_url, log=None):
    global _base, _log, _servi
    _base = (base_url or "").rstrip("/")
    _servi = None
    _log = log or print


def url(cle: str):
    if _servi and _base and (DOSSIER / f"{cle}.gif").is_file():
        return f"{_base}/v/{cle}.gif?v={VERSION}"
    return None


async def verifier(essais: int = 10, pause: float = 30.0) -> bool:
    """Les bandeaux ne s'affichent qu'une fois l'adresse publique vérifiée de l'extérieur :
    une image cassée dans un menu ment. Au déploiement, l'ancienne instance répond encore
    quelques instants — d'où les essais espacés."""
    global _servi
    temoin = next(iter(sorted(DOSSIER.glob("*.gif"))), None) if DOSSIER.is_dir() else None
    if not _base or temoin is None:
        _servi = False
        return False
    adresse = f"{_base}/v/{temoin.name}?v={VERSION}"
    for n in range(max(1, essais)):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.get(adresse) as r:
                    if r.status == 200 and r.headers.get("Content-Type", "").startswith("image/"):
                        _servi = True
                        _log("[VISUELS] bandeaux servis")
                        return True
                    _log(f"[VISUELS:DETAIL] statut={r.status} essai={n + 1}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
            _log(f"[VISUELS:DETAIL] {type(ex).__name__} essai={n + 1}")
        if n + 1 < essais:
            await asyncio.sleep(pause)
    _servi = False
    _log("[VISUELS][E1] bandeaux injoignables, titres en texte")
    return False


def bandeau(cle: str, titre: str):
    """En tête de menu : le bandeau animé, ou le titre si l'image n'est pas servie."""
    u = url(cle)
    if u:
        return discord.ui.MediaGallery(discord.MediaGalleryItem(u, description=titre))
    return discord.ui.TextDisplay(f"## {titre}")


def icone(nom: str):
    return _icones.get(nom)


def fichier(nom: str):
    """Chemin d'un visuel servi, ou None (seulement .gif/.png du dossier, pas de remontée)."""
    if "/" in nom or "\\" in nom or nom.startswith(".") or not nom.endswith((".gif", ".png")):
        return None
    f = DOSSIER / nom
    return f if f.is_file() else None


async def installer_icones(bot) -> int:
    """Chaque `visuels/icones/<nom>.png` devient l'émoji d'application `<nom>_v<VERSION>`."""
    dossier = DOSSIER / "icones"
    if not dossier.is_dir():
        return 0
    try:
        existants = {e.name: e for e in await bot.fetch_application_emojis()}
    except discord.HTTPException as ex:
        _log(f"[VISUELS] lecture des émojis : {ex}")
        return 0
    crees = 0
    for f in sorted(dossier.glob("*.png")):
        nom = f"{f.stem}_v{VERSION}"
        e = existants.get(nom)
        if e is None:
            try:
                e = await bot.create_application_emoji(name=nom, image=f.read_bytes())
                crees += 1
            except discord.HTTPException as ex:
                _log(f"[VISUELS] émoji {nom} : {ex}")
                continue
        _icones[f.stem] = e
    for nom, e in existants.items():
        base, _, v = nom.rpartition("_v")
        if base and v != VERSION and (dossier / f"{base}.png").is_file():
            try:
                await e.delete()
            except discord.HTTPException as ex:
                _log(f"[VISUELS] ancien émoji {nom} : {ex}")
    return crees
