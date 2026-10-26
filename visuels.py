"""visuels.py — l'identité visuelle : bandeaux animés des menus, icônes des boutons (19/10/2026).

Les images sont rendues hors ligne par `outils/visuels.py` dans `visuels/`, servies par le
serveur du bot (`/v/<nom>`, cache long) et affichées par Discord dans les menus. Les icônes
deviennent des émojis de l'application, installés une fois. Sans domaine public ou sans
fichier, chaque menu retombe sur un titre texte.

Une icône est UN objet partagé par tous les boutons qui la portent : un bouton construit au
chargement du module (décorateur, vue persistante) l'a déjà, sous sa forme de repli ; dès que
les émojis de l'application sont connus, l'objet devient l'icône maison, sur place.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp

import discord

import paths

DOSSIER = Path(__file__).resolve().parent / "visuels"
VERSION = "1"
_base = ""
_servi = None
_log = print

#  L'émoji d'avant, tant que l'icône maison n'est pas installée.
REPLI = {
    "retour": "◀️", "fermer": "✖️", "actualiser": "🔄", "ajouter": "➕", "supprimer": "🗑️",
    "modifier": "✏️", "valider": "✅", "annuler": "↩️", "reglages": "⚙️", "cloche": "🔔",
    "cloche_off": "🔕", "idee": "💡", "pour": "👍", "contre": "👎", "terminer": "⏹️",
    "pause": "⏸️", "activer": "▶️", "salon": "💬", "membre": "👤", "membres": "👥",
    "recherche": "🔎", "bouclier": "🛡️", "ticket": "🎫", "journal": "📋", "stats": "📊",
    "exporter": "📤", "lien": "🔗", "verrou": "🔒", "deverrou": "🔓", "avertir": "⚠️",
    "info": "ℹ️", "aide": "❓", "horloge": "⏱️", "calendrier": "📅", "balai": "🧹",
    "epingle": "📌", "envoyer": "📩", "sondage": "📊", "actu": "📰", "navire": "🚢",
    "globe": "🌐", "cle": "🔑", "sanction": "⚖️", "muet": "🔇", "etoile": "⭐",
    "expulser": "👢", "interdit": "🚫", "son": "🔊", "musique": "🎵", "alerte": "🚨",
    "dossier": "📁", "clavier": "⌨️", "heriter": "↪️", "video": "🎬", "diagnostic": "🩺",
    "cible": "🎯", "sommeil": "😴", "suivant": "⏭️", "palette": "🎨", "accueil": "👋",
    "numero": "🔢", "role": "🎭", "staff": "👮", "robot": "🤖", "image": "🖼️",
    "position": "📍", "detail": "🔬", "curseurs": "🎛️", "drapeau": "🚩", "etiquette": "🏷️",
    "retirer": "➖",
}


def _memoire() -> Path:
    return paths.base_data_dir() / "visuels_icones.json"


def _lire_memoire() -> dict:
    """Les identifiants des icônes installées au démarrage précédent : les boutons créés au
    chargement les portent tout de suite."""
    try:
        brut = json.loads(_memoire().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(brut, dict) or brut.get("version") != VERSION:
        return {}
    return {n: int(i) for n, i in (brut.get("icones") or {}).items() if str(i).isdigit()}


def _partage(nom: str, ident=None) -> discord.PartialEmoji:
    if ident:
        return discord.PartialEmoji(name=f"{nom}_v{VERSION}", id=int(ident))
    return discord.PartialEmoji(name=REPLI[nom])


_connus = _lire_memoire()
_icones: dict = {nom: _partage(nom, _connus.get(nom)) for nom in REPLI}


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


def url_image(nom: str):
    """L'adresse publique d'une image servie par le bot (un .png ou un .gif de `visuels/` : la bannière de l'affiche
    d'un ticket de recrutement) — None tant que l'adresse publique n'est pas vérifiée."""
    if _servi and _base and fichier(nom) is not None:
        return f"{_base}/v/{nom}?v={VERSION}"
    return None


def bandeau(cle: str, titre: str):
    """En tête de menu : le bandeau animé, ou le titre si l'image n'est pas servie."""
    u = url(cle)
    if u:
        return discord.ui.MediaGallery(discord.MediaGalleryItem(u, description=titre))
    return discord.ui.TextDisplay(f"## {titre}")


def icone(nom: str, repli=None):
    """L'icône maison (ou son émoji de repli) : le même objet pour tous les boutons."""
    return _icones.get(nom) or repli


def _monter(nom: str, emoji) -> None:
    """L'objet partagé devient l'icône maison, sur place : tous ses boutons suivent."""
    pe = _icones.get(nom)
    if pe is None:
        _icones[nom] = _partage(nom, emoji.id)
        return
    pe.name, pe.id, pe.animated = emoji.name, emoji.id, False


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
        _monter(f.stem, e)
    try:
        _memoire().write_text(json.dumps({"version": VERSION, "icones": {
            n: pe.id for n, pe in _icones.items() if pe.id}}), encoding="utf-8")
    except OSError as ex:
        _log(f"[VISUELS] mémoire des icônes : {ex}")
    for nom, e in existants.items():
        base, _, v = nom.rpartition("_v")
        if base and v != VERSION and (dossier / f"{base}.png").is_file():
            try:
                await e.delete()
            except discord.HTTPException as ex:
                _log(f"[VISUELS] ancien émoji {nom} : {ex}")
    return crees
