"""pet_eggs.py — Phase 235.26 : ŒUFS de familiers à faire éclore.

Réponse au #1 reproche owner sur les familiers : « on ne savait pas comment en
avoir ». L'acquisition passe désormais par des ŒUFS gagnés via events/quêtes,
qui ÉCLOSENT après X temps (l'incubation monte avec la rareté) → familier
ALÉATOIRE selon la rareté de l'œuf.

Réutilise l'existant (PAS de système parallèle) :
- catalogue : `engagement41.PETS` (étendu à ~50, familiers d'œuf = `egg_only`).
- collection : table `user_pets` (1 ligne/pet, `is_active` = équipé). On y
  insère le familier éclos. 1 SEUL équipé (géré par le /pet existant).

Équilibrage MAÎTRE (rétention long terme) : œufs rares = drop minuscule,
incubation longue, bonus modestes. Familier déjà possédé → on ne duplique pas
(PK user_pets) : compensation en pièces.

Module AUTONOME : deps injectées via setup() (get_db, add_coins). Tout défensif.
"""

import random
from datetime import datetime, timezone, timedelta

import engagement41 as _e41

# ─── deps injectées ───
_get_db = None
_add_coins = None

# Incubation (heures) — monte avec la rareté
INCUBATION_HOURS = {
    'common': 2, 'rare': 6, 'epic': 12, 'legendary': 24, 'mythic': 48,
}
# Poids de tirage quand on accorde un œuf SANS rareté précise (très dur en haut)
EGG_WEIGHTS = {
    'common': 60.0, 'rare': 28.0, 'epic': 9.0, 'legendary': 2.5, 'mythic': 0.5,
}
# Compensation pièces si le familier tiré est déjà possédé (modeste)
_DUPLICATE_COINS = {
    'common': 50, 'rare': 150, 'epic': 400, 'legendary': 1000, 'mythic': 2500,
}
RARITY_META = {
    'common': ('🟢', 'Commun'),
    'rare': ('🔵', 'Rare'),
    'epic': ('🟣', 'Épique'),
    'legendary': ('🟠', 'Légendaire'),
    'mythic': ('🌈', 'Mythique'),
}


def setup(get_db_fn, add_coins_fn=None):
    global _get_db, _add_coins
    _get_db = get_db_fn
    _add_coins = add_coins_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS pet_eggs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "guild_id INTEGER, user_id INTEGER, "
                "rarity TEXT, source TEXT, "
                "obtained_at TEXT, hatch_at TEXT, "
                "hatched INTEGER DEFAULT 0, result_pet_id TEXT)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pet_eggs_user "
                "ON pet_eggs(guild_id, user_id, hatched)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[pet_eggs init_db] {ex}")


def rarity_label(rarity: str) -> str:
    emo, name = RARITY_META.get(rarity, ('🥚', rarity or '?'))
    return f"{emo} {name}"


# Phase 248c : poids par TIER de source — plus l'event est rare, MEILLEURS sont
# les œufs (mais le mythique reste toujours rarissime). 'base' = drops courants
# (mob/trésor/quête), 'boss' = boss du jour/raid, 'grand' = world boss/climax.
_TIER_WEIGHTS = {
    "base":  EGG_WEIGHTS,
    "boss":  {'common': 30.0, 'rare': 40.0, 'epic': 22.0, 'legendary': 6.0, 'mythic': 2.0},
    "grand": {'common': 10.0, 'rare': 30.0, 'epic': 38.0, 'legendary': 17.0, 'mythic': 5.0},
}


def roll_egg_rarity(tier: str = "base") -> str:
    """Tire une rareté d'œuf (pondéré). `tier` : base / boss / grand — plus l'event
    est rare, meilleurs les œufs. Mythique toujours rarissime."""
    weights = _TIER_WEIGHTS.get(tier, EGG_WEIGHTS)
    total = sum(weights.values())
    r = random.uniform(0, total)
    acc = 0.0
    for rar, w in weights.items():
        acc += w
        if r <= acc:
            return rar
    return 'common'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime:
    """Parse un timestamp ISO en datetime AWARE (UTC). Défensif."""
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return _now()


async def grant_egg(guild_id, user_id, rarity=None, source="event"):
    """Donne un œuf (rareté précise ou tirée). Renvoie (rarity, hatch_at_iso) ou None."""
    if _get_db is None:
        return None
    try:
        rar = rarity if rarity in INCUBATION_HOURS else roll_egg_rarity()
        now = _now()
        hatch_at = now + timedelta(hours=INCUBATION_HOURS.get(rar, 2))
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO pet_eggs "
                "(guild_id, user_id, rarity, source, obtained_at, hatch_at, hatched) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (int(guild_id), int(user_id), rar, str(source),
                 now.isoformat(), hatch_at.isoformat()),
            )
            await db.commit()
        return (rar, hatch_at.isoformat())
    except Exception as ex:
        print(f"[pet_eggs grant_egg] {ex}")
        return None


async def grant_event_egg(guild_id, user_id, source="event", tier="base"):
    """Donne un œuf dont la rareté est tirée selon le TIER de la source — les
    events rares (boss/grand) donnent de meilleurs œufs. Renvoie (rarity, hatch_at)
    ou None. Convenience par-dessus grant_egg."""
    return await grant_egg(guild_id, user_id,
                           rarity=roll_egg_rarity(tier), source=source)


async def list_eggs(guild_id, user_id):
    """Liste les œufs NON éclos du joueur, avec drapeau prêt + secondes restantes."""
    if _get_db is None:
        return []
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, rarity, hatch_at, obtained_at FROM pet_eggs "
                "WHERE guild_id=? AND user_id=? AND hatched=0 "
                "ORDER BY hatch_at ASC",
                (int(guild_id), int(user_id)),
            ) as cur:
                rows = await cur.fetchall()
        now = _now()
        for r in rows:
            hatch_dt = _parse(r[2])
            remaining = int((hatch_dt - now).total_seconds())
            out.append({
                'id': int(r[0]),
                'rarity': r[1],
                'hatch_at': r[2],
                'hatch_ts': int(hatch_dt.timestamp()),
                'ready': remaining <= 0,
                'remaining': max(0, remaining),
            })
    except Exception as ex:
        print(f"[pet_eggs list_eggs] {ex}")
    return out


async def ready_count(guild_id, user_id) -> int:
    eggs = await list_eggs(guild_id, user_id)
    return sum(1 for e in eggs if e['ready'])


async def _owned_pet_ids(db, guild_id, user_id) -> set:
    async with db.execute(
        "SELECT pet_id FROM user_pets WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    ) as cur:
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def hatch_egg(guild_id, user_id, egg_id):
    """Fait éclore un œuf PRÊT. Renvoie un dict résultat :
      {'ok': True, 'pet': {...}}                        → nouveau familier
      {'ok': True, 'duplicate': True, 'coins': N, 'pet': {...}} → déjà possédé → pièces
      {'error': '...'}                                  → pas prêt / introuvable
    """
    if _get_db is None:
        return {'error': "Système indisponible."}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT rarity, hatch_at, hatched FROM pet_eggs "
                "WHERE id=? AND guild_id=? AND user_id=?",
                (int(egg_id), int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
            if not row:
                return {'error': "Œuf introuvable."}
            rarity, hatch_at, hatched = row[0], row[1], int(row[2] or 0)
            if hatched:
                return {'error': "Cet œuf a déjà éclos."}
            if _parse(hatch_at) > _now():
                return {'error': "Cet œuf n'est pas encore prêt à éclore."}

            # Tirage du familier : parmi la rareté, on PRIORISE les non-possédés.
            pool = _e41.pets_by_rarity(rarity)
            owned = await _owned_pet_ids(db, guild_id, user_id)
            fresh = [p for p in pool if p['id'] not in owned]
            duplicate = False
            if fresh:
                pet = random.choice(fresh)
            elif pool:
                pet = random.choice(pool)
                duplicate = True
            else:
                # rareté sans familier défini → compensation
                pet = None

            # Marque l'œuf éclos
            await db.execute(
                "UPDATE pet_eggs SET hatched=1, result_pet_id=? WHERE id=?",
                ((pet['id'] if pet else None), int(egg_id)),
            )

            if pet and not duplicate:
                # Active automatiquement SEULEMENT si le joueur n'a aucun pet actif.
                async with db.execute(
                    "SELECT COUNT(*) FROM user_pets "
                    "WHERE guild_id=? AND user_id=? AND is_active=1",
                    (int(guild_id), int(user_id)),
                ) as cur:
                    arow = await cur.fetchone()
                has_active = bool(arow and arow[0])
                await db.execute(
                    "INSERT OR IGNORE INTO user_pets "
                    "(guild_id, user_id, pet_id, level, xp, hunger, is_active) "
                    "VALUES (?, ?, ?, 1, 0, 100, ?)",
                    (int(guild_id), int(user_id), pet['id'],
                     0 if has_active else 1),
                )
                await db.commit()
                return {'ok': True, 'pet': pet, 'rarity': rarity,
                        'activated': not has_active}

            # Doublon (ou pool vide) → compensation pièces
            coins = _DUPLICATE_COINS.get(rarity, 50)
            await db.commit()
            if _add_coins is not None:
                try:
                    await _add_coins(int(guild_id), int(user_id), coins)
                except Exception:
                    pass
            return {'ok': True, 'duplicate': True, 'coins': coins,
                    'rarity': rarity, 'pet': pet}
    except Exception as ex:
        print(f"[pet_eggs hatch_egg] {ex}")
        return {'error': "Erreur pendant l'éclosion."}
