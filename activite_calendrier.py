"""activite_calendrier.py — Les bornes de temps du système d'activité.

Isolé dans son propre module parce que c'est ici que se cachent les erreurs les
plus coûteuses d'un système de présence : une journée mal bornée, et un membre
actif le dimanche soir est compté sur le mauvais jour ; une semaine mal ancrée,
et le rappel part quatre fois ou pas du tout.

═══════════════════════════════════════════════════════════════════════════════
POURQUOI PAS UTC
═══════════════════════════════════════════════════════════════════════════════
Le serveur est francophone. Quand le propriétaire dit « lundi 00h00 », il parle
de MINUIT CHEZ LUI, pas de minuit à Greenwich. En heure d'été, minuit à Paris
c'est 22h00 UTC la veille : un système calé sur UTC ferait basculer la journée
en plein pic d'activité du dimanche soir, et un message envoyé à 00h30 lundi
serait compté sur le dimanche.

Tout est donc calé sur `Europe/Paris`, changements d'heure compris — c'est le
seul réglage qui correspond à ce que voit un humain.

Si la base de fuseaux est absente (image minimale sans `tzdata`), on retombe sur
UTC en le DISANT bruyamment, plutôt que de décaler silencieusement toutes les
bornes d'une ou deux heures.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

FUSEAU_NOM = "Europe/Paris"
JOUR_FMT = "%Y-%m-%d"
SEMAINE_FMT = "%G-S%V"      # ISO : « 2026-S33 ». %G/%V, pas %Y/%W — voir plus bas.
MOIS_FMT = "%Y-%m"

try:
    from zoneinfo import ZoneInfo
    FUSEAU = ZoneInfo(FUSEAU_NOM)
    FUSEAU_DISPONIBLE = True
except Exception as _ex:      # pragma: no cover - dépend de l'image
    FUSEAU = timezone.utc
    FUSEAU_DISPONIBLE = False
    print(f"[activite_calendrier] ⚠️ {FUSEAU_NOM} indisponible ({_ex}) — "
          f"repli sur UTC. Les bornes de journée seront décalées de 1 à 2 h. "
          f"Installez `tzdata` pour corriger.")


def maintenant() -> datetime:
    """L'instant présent, dans le fuseau de référence."""
    return datetime.now(FUSEAU)


# ═══════════════════════════════════════════════════════════════════════════════
#  JOUR
# ═══════════════════════════════════════════════════════════════════════════════

def jour(dt: datetime | None = None) -> str:
    """Identifiant de la journée : 'YYYY-MM-DD', bornée minuit → minuit à Paris."""
    return (dt or maintenant()).astimezone(FUSEAU).strftime(JOUR_FMT)


def debut_du_jour(dt: datetime | None = None) -> datetime:
    d = (dt or maintenant()).astimezone(FUSEAU)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def jours_entre(depuis: str, jusqua: str | None = None) -> int | None:
    """Nombre de jours entre deux identifiants de journée.

    None si l'un des deux est illisible — jamais 0 par défaut : un 0 muet
    ferait passer une date inconnue pour « aujourd'hui ».
    """
    try:
        a = datetime.strptime(depuis, JOUR_FMT).date()
        b = (datetime.strptime(jusqua, JOUR_FMT).date() if jusqua
             else maintenant().date())
    except Exception:
        return None
    return max(0, (b - a).days)


# ═══════════════════════════════════════════════════════════════════════════════
#  SEMAINE — du lundi 00h00 au lundi 00h00
# ═══════════════════════════════════════════════════════════════════════════════

def debut_de_semaine(dt: datetime | None = None) -> datetime:
    """Le lundi 00h00 de la semaine contenant `dt`, heure de Paris."""
    d = debut_du_jour(dt)
    return d - timedelta(days=d.weekday())          # weekday() : lundi = 0


def fin_de_semaine(dt: datetime | None = None) -> datetime:
    """Le lundi 00h00 SUIVANT — borne haute exclue."""
    return debut_de_semaine(dt) + timedelta(days=7)


def semaine(dt: datetime | None = None) -> str:
    """Identifiant unique de la semaine : '2026-S33'.

    ⚠️ On utilise `%G-S%V` (année ISO + semaine ISO) et NON `%Y-S%W`. Autour du
    Nouvel An, l'année civile (`%Y`) et l'année ISO (`%G`) diffèrent : le 1er
    janvier peut appartenir à la dernière semaine de l'année précédente. Avec
    `%Y`, deux semaines distinctes porteraient le même identifiant, et le rappel
    hebdomadaire sauterait une semaine une année sur deux.
    """
    return debut_de_semaine(dt).strftime(SEMAINE_FMT)


def prochain_jour_de_semaine(cible: int, dt: datetime | None = None) -> datetime:
    """Prochaine occurrence de ce jour (0=lundi … 6=dimanche) à 00h00."""
    d = debut_du_jour(dt)
    ecart = (int(cible) - d.weekday()) % 7
    if ecart == 0:
        ecart = 7
    return d + timedelta(days=ecart)


# ═══════════════════════════════════════════════════════════════════════════════
#  MOIS — du 1er 00h00 au 1er du mois suivant
# ═══════════════════════════════════════════════════════════════════════════════

def debut_de_mois(dt: datetime | None = None) -> datetime:
    return debut_du_jour(dt).replace(day=1)


def fin_de_mois(dt: datetime | None = None) -> datetime:
    """Le 1er du mois suivant à 00h00 — borne haute exclue.

    Calculé par report d'année plutôt qu'en ajoutant 30 ou 31 jours : ajouter un
    nombre fixe de jours décale le mois dès février, et double-compte en octobre
    lors du changement d'heure.
    """
    d = debut_de_mois(dt)
    return (d.replace(year=d.year + 1, month=1) if d.month == 12
            else d.replace(month=d.month + 1))


def mois(dt: datetime | None = None) -> str:
    """Identifiant du mois : '2026-08'."""
    return debut_de_mois(dt).strftime(MOIS_FMT)


def jours_du_mois(dt: datetime | None = None) -> int:
    """Nombre de jours du mois courant (28, 29, 30 ou 31)."""
    return (fin_de_mois(dt) - debut_de_mois(dt)).days


def description() -> str:
    """Une phrase lisible pour le panneau : où en est-on dans le calendrier."""
    n = maintenant()
    ds = debut_de_semaine(n)
    zone = FUSEAU_NOM if FUSEAU_DISPONIBLE else "UTC (⚠️ repli)"
    return (f"🗓️ Semaine `{semaine(n)}` — du {ds.strftime('%d/%m à %Hh%M')} "
            f"au {fin_de_semaine(n).strftime('%d/%m à %Hh%M')} · "
            f"mois `{mois(n)}` ({jours_du_mois(n)} j) · fuseau `{zone}`")
