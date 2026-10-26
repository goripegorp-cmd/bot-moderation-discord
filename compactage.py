"""compactage.py — la base rend sa place au disque, la nuit (26/10/2026).

« Imagine-toi que le site peut aussi tourner sur plusieurs années… est-ce qu'il peut tenir le coup ? »

Ce que les nettoyages effacent laisse des pages LIBRES dans le fichier de SQLite : la base ne rétrécit jamais seule,
et ses copies quotidiennes (`db_backup`, jusqu'à onze) recopient ces pages vides. Avant ce module : un VACUUM complet
le dimanche à 4 h (`data_cleanup.weekly_cleanup_task`, seulement après une grosse purge ou au-delà de 20 % de pages
libres), au démarrage au-delà de 20 %, et un autre prévu le lundi (`db_optimizer_task`, qui ne tombe presque jamais
dans sa fenêtre : sa boucle tourne toutes les 24 h depuis le démarrage). Un VACUUM complet bloque toute la base pendant
qu'il la recopie (1,2 s mesurée à 5 ans sur un PC ; davantage sur le volume de Railway) et demande deux fois sa place
sur le disque ; entre deux passages, jusqu'à 20 % du fichier restait vide — et recopié dans chaque copie.

Maintenant :
  · une seule fois, aux heures creuses (3 h – 6 h, heure de Paris), la base passe en `auto_vacuum = INCREMENTAL` —
    un VACUUM complet, seulement s'il reste sur le volume 2,2 fois la taille de la base (il la recopie) ;
  · ensuite, chaque nuit, `PRAGMA incremental_vacuum` rend les pages libres au disque par paquets de PAQUET pages
    (quelques millisecondes chacun : la base n'est jamais bloquée longtemps), et le journal WAL est reversé ;
  · `etat()` dit la taille, les pages libres, le mode et le dernier passage (rubrique « Nettoyage » du site).
Le grand nettoyage hebdomadaire (`data_cleanup.vacuum_db`) passe par l'incrémental dès que la base y est passée.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import time
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except (ImportError, KeyError):  # sans base de fuseaux (ZoneInfoNotFoundError est une KeyError) : l'heure UTC
    from datetime import timezone
    PARIS = timezone.utc

HEURES_CREUSES = (3, 6)   # [3 h, 6 h[, heure de Paris
PAQUET = 2000             # pages rendues par pas (8 Mo en pages de 4 Ko)
PAUSE_S = 0.05            # entre deux pas : les écritures du bot passent
PAS_MAX = 50              # pas par nuit au plus (≈ 400 Mo)
PART_MIN = 0.02           # en dessous de 2 % de pages libres : rien à rendre
MARGE = 2.2               # place libre exigée pour la conversion (VACUUM recopie la base)
INCREMENTAL = 2
_etat = {"dernier": 0, "nuit": "", "rendues": 0, "conversion": 0, "refus": "", "erreur": ""}
_log = print


def setup(*, log=None) -> None:
    global _log
    _log = log or print


async def _pragma(db, nom: str):
    async with db.execute(f"PRAGMA {nom}") as cur:
        r = await cur.fetchone()
    return r[0] if r else None


async def etat(get_db) -> dict:
    """{octets, libres (octets), part_libre, mode (0 aucun, 1 complet, 2 incrémental), dernier, rendues, conversion}."""
    async with get_db() as db:
        pages = int(await _pragma(db, "page_count") or 0)
        taille = int(await _pragma(db, "page_size") or 4096)
        libres = int(await _pragma(db, "freelist_count") or 0)
        mode = int(await _pragma(db, "auto_vacuum") or 0)
    return {"octets": pages * taille, "libres": libres * taille, "part_libre": round(libres / pages, 4) if pages else 0.0,
            "mode": mode, "dernier": int(_etat["dernier"]), "rendues": int(_etat["rendues"]) * taille,
            "conversion": int(_etat["conversion"]), "refus": _etat["refus"], "erreur": _etat["erreur"]}


def heure_creuse(maintenant: float | None = None) -> bool:
    h = datetime.fromtimestamp(maintenant or time.time(), PARIS).hour
    return HEURES_CREUSES[0] <= h < HEURES_CREUSES[1]


def _place(chemin) -> int | None:
    try:
        return shutil.disk_usage(os.path.dirname(os.path.abspath(chemin)) or ".").free
    except OSError as ex:   # la conversion se tente alors (SQLite refuse proprement un disque plein)
        _log("[COMPACTAGE][E5] place du volume illisible")
        _log(f"[COMPACTAGE][E5:DETAIL] {type(ex).__name__} {ex}")
        return None


async def passer(get_db, chemin=None, maintenant: float | None = None, forcer: bool = False) -> dict:
    """Un passage : la conversion en incrémental si la base n'y est pas encore (aux heures creuses, ou `forcer`), puis
    les pages libres rendues par paquets. Rend {"converti", "rendues" (pages), "avant", "apres" (octets)}."""
    t = maintenant or time.time()
    avant = await etat(get_db)
    out = {"converti": False, "rendues": 0, "avant": avant["octets"], "apres": avant["octets"], "refus": ""}
    _etat["erreur"] = ""
    if avant["mode"] != INCREMENTAL:
        if not (forcer or heure_creuse(t)):
            out["refus"] = "heures creuses"
            return out
        place = _place(chemin) if chemin else None
        if place is not None and place < MARGE * avant["octets"]:
            out["refus"] = _etat["refus"] = "place insuffisante pour recopier la base"
            _log("[COMPACTAGE][E1] place insuffisante pour la conversion")
            _log(f"[COMPACTAGE][E1:DETAIL] libre={place} base={avant['octets']}")
            return out
        try:
            async with get_db() as db:
                await db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                await db.execute("VACUUM")
        except Exception as ex:  # base occupée : réessayé la nuit suivante ; le détail au journal
            _etat["erreur"] = type(ex).__name__
            _log("[COMPACTAGE][E2] conversion en incrémental impossible")
            _log(f"[COMPACTAGE][E2:DETAIL] {type(ex).__name__} {ex}")
            return out
        _etat["conversion"], _etat["refus"] = int(t), ""
        out["converti"] = True
    elif avant["part_libre"] >= PART_MIN or forcer:
        for _ in range(PAS_MAX):
            try:
                async with get_db() as db:
                    libres = int(await _pragma(db, "freelist_count") or 0)
                    if not libres:
                        break
                    #  `executescript` : le pragma va au bout de ses pages. Par `execute`, SQLite n'en rendait
                    #  qu'UNE par appel (mesuré le 26/10/2026 : 1 600 pages libres → 1 599).
                    await db.executescript(f"PRAGMA incremental_vacuum({min(PAQUET, libres)});")
                    reste = int(await _pragma(db, "freelist_count") or 0)
                out["rendues"] += max(0, libres - reste)
                if reste >= libres:   # plus rien ne se rend : la suite la nuit prochaine
                    break
            except Exception as ex:  # base occupée : la suite la nuit prochaine ; le détail au journal
                _etat["erreur"] = type(ex).__name__
                _log("[COMPACTAGE][E3] pages libres non rendues")
                _log(f"[COMPACTAGE][E3:DETAIL] {type(ex).__name__} {ex}")
                break
            await asyncio.sleep(PAUSE_S)
        try:
            async with get_db() as db:
                await db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception as ex:  # le journal WAL sera reversé par la boucle quotidienne du bot
            _log("[COMPACTAGE][E4] journal WAL non reversé")
            _log(f"[COMPACTAGE][E4:DETAIL] {type(ex).__name__} {ex}")
    _etat["dernier"] = int(t)
    _etat["rendues"] = out["rendues"]
    out["apres"] = (await etat(get_db))["octets"]
    return out


async def si_heure_creuse(get_db, chemin=None, maintenant: float | None = None) -> dict | None:
    """La boucle horaire du site : un passage par nuit, aux heures creuses. None : pas maintenant."""
    t = maintenant or time.time()
    if not heure_creuse(t):
        return None
    nuit = datetime.fromtimestamp(t, PARIS).strftime("%Y-%m-%d")
    if _etat["nuit"] == nuit:
        return None
    _etat["nuit"] = nuit
    res = await passer(get_db, chemin, t)
    if res["converti"] or res["rendues"]:
        _log("[COMPACTAGE] base compactée")
        _log(f"[COMPACTAGE:DETAIL] {res['avant'] // 1048576} Mo → {res['apres'] // 1048576} Mo"
             + (" (passée en compactage incrémental)" if res["converti"] else f", {res['rendues']} page(s) rendue(s)"))
    return res
