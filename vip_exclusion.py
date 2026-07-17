"""vip_exclusion.py — Privation des récompenses VIP / d'activité (owner 2026-07-12).

DÉCISION OWNER : « si un utilisateur enfreint le règlement (spam pour farmer le VIP, sanction,
warn d'un staff), il est privé de tout rôle VIP ou autre gagné par son activité pendant plus
d'un mois. Si ça continue, ça se multiplie : plusieurs mois, puis une année. »

ÉCHELLE VALIDÉE (elle DOUBLE) : 1 mois → 2 mois → 4 mois → 8 mois → 1 an (puis reste à 1 an).
DÉCLENCHEUR VALIDÉ : les VRAIES sanctions (mute / kick / ban AUTOMATIQUES) + les warns du STAFF.
  → Une maladresse (lien supprimé, simple rappel) NE déclenche RIEN (règle n°1 : ne jamais punir
    un innocent). C'est l'appelant qui filtre : ce module ne fait qu'appliquer ce qu'on lui donne.

GARDE-FOUS :
- Owner / super-owner / admins / immunisés : JAMAIS exclus (l'appelant filtre AVANT — cf. bot.py).
- 100 % FAIL-OPEN : la moindre erreur → on n'exclut personne / on ne bloque aucun rôle.
- OUBLI APRÈS UNE ANNÉE PROPRE : si la dernière privation est terminée depuis > 365 j, le compteur
  repart à zéro (on ne traîne pas une bêtise unique à vie). La mémoire reste longue, pas éternelle.
- Levée MANUELLE possible via `pardon()` (bouton/commande owner).

Module PUR : aucune dépendance à bot.py (pas d'import circulaire). `get_db` est injecté par setup().
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

_get_db = None

# Échelle : index = nombre de bêtises déjà commises (strikes-1) → durée en JOURS.
# 1 mois → 2 mois → 4 mois → 8 mois → 1 an. Au-delà du dernier palier, on reste à 1 an.
STRIKE_DAYS = [30, 60, 120, 240, 365]
_CLEAN_RESET_DAYS = 365          # une année propre après la fin d'une privation → compteur à 0


def setup(get_db_fn) -> None:
    """Injecte l'accès DB (appelé depuis bot.py au boot)."""
    global _get_db
    _get_db = get_db_fn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> Optional[datetime]:
    """Parse un timestamp DB en datetime aware. None si illisible (→ fail-open)."""
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def init_db() -> None:
    """Crée la table. FAIL-SAFE."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS vip_exclusions (
                    guild_id   INTEGER NOT NULL,
                    user_id    INTEGER NOT NULL,
                    until_ts   TEXT    NOT NULL,
                    strikes    INTEGER NOT NULL DEFAULT 1,
                    reason     TEXT    DEFAULT '',
                    updated_at TEXT    NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[vip_exclusion init_db] {ex}")


def days_for(strikes: int) -> int:
    """Durée (jours) pour la N-ième bêtise. Plafonnée au dernier palier (1 an)."""
    try:
        idx = max(1, int(strikes)) - 1
        return STRIKE_DAYS[min(idx, len(STRIKE_DAYS) - 1)]
    except Exception:
        return STRIKE_DAYS[0]


def human(days: int) -> str:
    """Durée lisible en français (pour les messages au membre / au staff)."""
    if days >= 365:
        return "1 an"
    if days % 30 == 0 and days >= 30:
        m = days // 30
        return "1 mois" if m == 1 else f"{m} mois"
    return f"{days} jours"


async def status(guild_id: int, user_id: int) -> Optional[dict]:
    """État courant : {'until': dt, 'strikes': int, 'reason': str, 'active': bool} ou None."""
    if _get_db is None:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT until_ts, strikes, reason FROM vip_exclusions WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        until = _parse(row[0])
        if until is None:
            return None
        return {
            'until': until,
            'strikes': int(row[1] or 0),
            'reason': str(row[2] or ''),
            'active': until > _now(),
        }
    except Exception as ex:
        print(f"[vip_exclusion status] {ex}")
        return None


async def is_excluded(guild_id: int, user_id: int) -> bool:
    """Le membre est-il actuellement privé de VIP ? FAIL-OPEN → False au moindre doute."""
    try:
        st = await status(guild_id, user_id)
        return bool(st and st['active'])
    except Exception:
        return False


async def punish(guild_id: int, user_id: int, reason: str = "") -> Optional[dict]:
    """Applique/aggrave la privation. Renvoie {'strikes','days','until','text'} ou None.

    L'appelant DOIT avoir filtré en amont (immunisés, bots, sanctions non-réelles).
    Si une privation court déjà, la nouvelle durée part de MAINTENANT et on garde la date la
    PLUS LOINTAINE (jamais de réduction de peine).
    """
    if _get_db is None:
        return None
    try:
        prev = await status(guild_id, user_id)
        strikes = 1
        if prev:
            # Oubli après une année PROPRE (privation finie depuis > 365 j) → on repart à zéro.
            if (not prev['active']) and (_now() - prev['until']).days > _CLEAN_RESET_DAYS:
                strikes = 1
            else:
                strikes = int(prev['strikes']) + 1
        days = days_for(strikes)
        until = _now() + timedelta(days=days)
        if prev and prev['until'] > until:
            until = prev['until']          # jamais de remise de peine
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO vip_exclusions(guild_id, user_id, until_ts, strikes, reason, updated_at) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "until_ts=excluded.until_ts, strikes=excluded.strikes, "
                "reason=excluded.reason, updated_at=excluded.updated_at",
                (int(guild_id), int(user_id), until.isoformat(), int(strikes),
                 str(reason or '')[:200], _now().isoformat()),
            )
            await db.commit()
        return {
            'strikes': strikes,
            'days': days,
            'until': until,
            'text': human(days),
        }
    except Exception as ex:
        print(f"[vip_exclusion punish] {ex}")
        return None


async def pardon(guild_id: int, user_id: int) -> bool:
    """Levée MANUELLE (owner/staff) : efface la privation ET le compteur. True si effacé."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM vip_exclusions WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            )
            await db.commit()
            return getattr(cur, "rowcount", 0) > 0
    except Exception as ex:
        print(f"[vip_exclusion pardon] {ex}")
        return False


async def excluded_ids(guild_id: int) -> set:
    """Tous les user_id actuellement privés (pour un balayage en masse côté activity_vip)."""
    if _get_db is None:
        return set()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, until_ts FROM vip_exclusions WHERE guild_id=?",
                (int(guild_id),),
            ) as cur:
                rows = await cur.fetchall()
        out = set()
        _n = _now()
        for uid, until in rows:
            d = _parse(until)
            if d and d > _n:
                out.add(int(uid))
        return out
    except Exception as ex:
        print(f"[vip_exclusion excluded_ids] {ex}")
        return set()
