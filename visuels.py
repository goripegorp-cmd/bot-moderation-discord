"""visuels.py — l'identité visuelle : bandeaux animés des menus, icônes des boutons (19/10/2026).

Les images sont rendues hors ligne par `outils/visuels.py` dans `visuels/`, servies par le
serveur du bot (`/v/<nom>`, cache long) et affichées par Discord dans les menus. Les icônes
deviennent des émojis de l'application, installés une fois. Sans domaine public ou sans
fichier, chaque menu retombe sur un titre texte.
"""
from __future__ import annotations

from pathlib import Path

import discord

DOSSIER = Path(__file__).resolve().parent / "visuels"
VERSION = "1"
_base = ""
_icones: dict = {}
_log = print


def setup(*, base_url, log=None):
    global _base, _log
    _base = (base_url or "").rstrip("/")
    _log = log or print


def url(cle: str):
    if _base and (DOSSIER / f"{cle}.gif").is_file():
        return f"{_base}/v/{cle}.gif?v={VERSION}"
    return None


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
