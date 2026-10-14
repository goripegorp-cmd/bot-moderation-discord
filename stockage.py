"""stockage.py — ce que le bot garde sur le disque, et sa limite (14/10/2026).

« Tu vérifies bien la consommation du bot. On n'arrive pas à échéance sur
Railway avec des surdonnées monstrueuses à stocker. » Les tables sont bornées
(rétentions de `data_cleanup`, `gdpr`, `db_optimizer_task`) ; deux postes, eux,
pouvaient grossir sans limite sur le volume :
  · les copies COMPLÈTES de la base (`db_backup` : 7 × la taille de la base) ;
  · les transcripts de tickets (jusqu'à 64 Mo d'images par ticket, 120 jours).
Chacun a désormais une PART du volume ; au-delà, le plus ancien part d'abord.
Et une ligne par jour dit l'état RÉEL : base, copies, transcripts, place
libre, mémoire, tables les plus lourdes.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone

PART_COPIES = 0.30        # copies .bak : au plus 30 % du volume…
COPIES_MIN = 2            # …mais toujours les deux plus récentes
PART_TRANSCRIPTS = 0.25   # transcripts de tickets : au plus 25 % du volume
SEUIL_LIBRE = 0.20        # moins de 20 % libres : alarme dans le journal

#  Le dernier relevé, en POURCENTAGES du volume + la mémoire : exposé par
#  /health (endpoint public — aucune taille absolue, aucune identité).
#  Le journal, lui, ne parle du stockage que pour une ALARME (journal.py).
DERNIER: dict = {}


def taille(chemin) -> int:
    """Octets d'un fichier, ou d'un dossier entier. 0 s'il n'existe pas."""
    try:
        if os.path.isfile(chemin):
            return os.path.getsize(chemin)
        total = 0
        for racine, _d, fichiers in os.walk(chemin):
            for f in fichiers:
                try:
                    total += os.path.getsize(os.path.join(racine, f))
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def volume(chemin) -> tuple:
    """(taille totale, place libre) du disque qui porte `chemin`, ou (None, None)."""
    try:
        u = shutil.disk_usage(chemin)
        return u.total, u.free
    except OSError:
        return None, None


def a_retirer(du_plus_recent: list, budget, garder_min: int = 0) -> list:
    """`du_plus_recent` : [(chemin, octets)], le plus récent d'abord. Rend les
    chemins qui dépassent le budget — les plus ANCIENS. Les `garder_min` plus
    récents restent toujours. Sans budget connu, rien ne part."""
    if budget is None:
        return []
    cumul, out = 0, []
    for n, (chemin, octets) in enumerate(du_plus_recent):
        cumul += octets
        if n >= garder_min and cumul > budget:
            out.append(chemin)
    return out


def plafonner_dossier(dossier, part: float) -> int:
    """Chaque entrée de `dossier` (fichier ou sous-dossier) au plus `part` du
    volume, ensemble ; les plus anciennes (date de modification) partent."""
    if not os.path.isdir(dossier):
        return 0
    total, _libre = volume(dossier)
    if not total:
        return 0
    entrees = []
    for nom in os.listdir(dossier):
        p = os.path.join(dossier, nom)
        try:
            entrees.append((os.path.getmtime(p), p, taille(p)))
        except OSError:
            continue
    entrees.sort(reverse=True)
    partis = 0
    for p in a_retirer([(p, o) for _m, p, o in entrees], total * part):
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            partis += 1
        except OSError as ex:
            print(f"[STOCKAGE] suppression impossible ({os.path.basename(p)}) : {ex}")
    return partis


def memoire_mo():
    """Mémoire vive du processus (Linux), en Mo ; None ailleurs."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for ligne in f:
                if ligne.startswith("VmRSS:"):
                    return int(ligne.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _mo(octets) -> str:
    if octets is None:
        return "?"
    if octets >= 1024 ** 3:
        return f"{octets / 1024 ** 3:.1f} Go".replace(".", ",")
    return f"{octets / 1024 ** 2:.0f} Mo"


async def tables_lourdes(get_db, n: int = 5) -> list:
    """Les tables qui comptent le plus de lignes, d'après `sqlite_stat1`
    (tenue à jour par l'ANALYZE quotidien) : zéro balayage de table."""
    try:
        async with get_db() as db:
            async with db.execute("SELECT tbl, stat FROM sqlite_stat1") as cur:
                lignes = await cur.fetchall()
    except Exception as ex:
        print(f"[STOCKAGE] sqlite_stat1 illisible : {ex}")
        return []
    par_table = {}
    for tbl, stat in lignes:
        try:
            nb = int(str(stat).split()[0])
        except (ValueError, IndexError):
            continue
        par_table[tbl] = max(par_table.get(tbl, 0), nb)
    return sorted(par_table.items(), key=lambda x: -x[1])[:n]


def _releve_disque(db_path, dossier_copies, dossier_transcripts) -> dict:
    copies = []
    try:
        copies = [os.path.join(dossier_copies, f) for f in os.listdir(dossier_copies)
                  if f.endswith(".bak")]
    except OSError:
        pass
    total, libre = volume(os.path.dirname(os.path.abspath(db_path)) or ".")
    return {
        "base": taille(db_path),
        "wal": taille(f"{db_path}-wal"),
        "copies_n": len(copies),
        "copies": sum(taille(c) for c in copies),
        "transcripts": taille(dossier_transcripts),
        "total": total, "libre": libre,
        "memoire": memoire_mo(),
    }


async def bilan(get_db, db_path, dossier_copies, dossier_transcripts,
                purges: str = "") -> str:
    r = await asyncio.to_thread(_releve_disque, db_path, dossier_copies,
                                dossier_transcripts)
    lourdes = await tables_lourdes(get_db)
    mem = r["memoire"]
    total, libre = r["total"], r["libre"]
    alarme = bool(total) and libre is not None and libre / total < SEUIL_LIBRE
    if total:
        DERNIER.clear()
        DERNIER.update({
            "volume_pct": round(100 * (total - (libre or 0)) / total, 1),
            "base_pct": round(100 * (r["base"] + r["wal"]) / total, 1),
            "copies_pct": round(100 * r["copies"] / total, 1),
            "transcripts_pct": round(100 * r["transcripts"] / total, 1),
            "memoire_mo": round(mem) if mem is not None else None,
            "releve_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        })
    return (("🚨 [STOCKAGE] volume presque plein — " if alarme else "[STOCKAGE] ")
            + f"base {_mo(r['base'])} (+ journal {_mo(r['wal'])}) · "
            f"copies .bak {r['copies_n']} = {_mo(r['copies'])} · "
            f"transcripts {_mo(r['transcripts'])} · "
            f"volume {_mo(r['libre'])} libres sur {_mo(r['total'])} · "
            f"mémoire {f'{mem:.0f} Mo' if mem is not None else '?'}"
            + (" · plus grosses tables : "
               + ", ".join(f"{t} {n:,}".replace(",", " ") for t, n in lourdes)
               if lourdes else "")
            + (f" · {purges}" if purges else ""))
