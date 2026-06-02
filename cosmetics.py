"""cosmetics.py — Phase 249 : SINK économique (titres de profil cosmétiques).

Objectif (rétention long terme = valeur owner #1) : donner aux joueurs une raison
de **DÉPENSER** leurs pièces, sinon l'économie gonfle et les coins ne valent plus
rien. Ici : des **titres de profil** purement cosmétiques (affichés dans /profile).

Règles respectées :
- 100 % COSMÉTIQUE — aucun impact combat / stats, aucun avantage de jeu.
- Pas de P2P (on achète au « serveur », pas à un autre joueur).
- Prix **volontairement DURS en haut** (le « Mythe vivant » = chase de très long
  terme) → vrai puits anti-inflation, jamais « j'ai tout fini ».
- Achat ATOMIQUE (vérif solde + débit + possession dans la MÊME transaction → pas
  de double-dépense). FAIL-OPEN sur la lecture, FAIL-CLOSED sur l'achat (en cas
  d'erreur on ne donne rien et on ne débite rien).

Module autonome : `setup(get_db)` au boot (même patron que activity_system).
"""

import json

_get_db = None

# (key, emoji, label, prix en pièces). Escalade volontairement très dure en haut.
TITLES = [
    ("apprenti", "🌱", "Apprenti",          1_000),
    ("veteran",  "⚔️", "Vétéran",           8_000),
    ("aguerri",  "🔥", "Vétéran aguerri",   25_000),
    ("elite",    "💎", "Élite",             75_000),
    ("legende",  "🌟", "Légende",          250_000),
    ("mythe",    "👑", "Mythe vivant",   1_000_000),
]
_BY_KEY = {t[0]: t for t in TITLES}


def setup(get_db_fn):
    global _get_db
    _get_db = get_db_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_cosmetics ("
                "guild_id INTEGER, user_id INTEGER, owned TEXT DEFAULT '[]', "
                "active TEXT DEFAULT '', PRIMARY KEY (guild_id, user_id))"
            )
            await db.commit()
    except Exception as ex:
        print(f"[cosmetics init_db] {ex}")


def title_label(key) -> str:
    t = _BY_KEY.get(key or "")
    return f"{t[1]} {t[2]}" if t else ""


def price_of(key) -> int:
    t = _BY_KEY.get(key or "")
    return int(t[3]) if t else 0


async def _read(db, gid, uid):
    """(owned_list, active_key) depuis la table (connexion fournie)."""
    async with db.execute(
        "SELECT owned, active FROM user_cosmetics WHERE guild_id=? AND user_id=?",
        (gid, uid),
    ) as c:
        r = await c.fetchone()
    owned, active = [], ""
    if r:
        try:
            owned = json.loads(r[0] or "[]")
        except Exception:
            owned = []
        active = r[1] or ""
    return owned, active


async def get_state(guild_id, user_id):
    """(owned_keys: list, active_key: str). FAIL-OPEN → ([], '')."""
    if _get_db is None:
        return [], ""
    try:
        async with _get_db() as db:
            return await _read(db, int(guild_id), int(user_id))
    except Exception:
        return [], ""


async def active_label(guild_id, user_id) -> str:
    """Libellé du titre équipé (ou '' si aucun). Pour /profile. FAIL-OPEN."""
    try:
        _owned, active = await get_state(guild_id, user_id)
        return title_label(active) if active else ""
    except Exception:
        return ""


async def buy(guild_id, user_id, key):
    """Achète un titre (ATOMIQUE). Retourne (ok: bool, msg: str)."""
    t = _BY_KEY.get(key or "")
    if not t or _get_db is None:
        return False, "Titre introuvable."
    gid, uid, price = int(guild_id), int(user_id), int(t[3])
    try:
        async with _get_db() as db:
            owned, _active = await _read(db, gid, uid)
            if key in owned:
                return False, "Tu possèdes déjà ce titre."
            # Solde
            async with db.execute(
                "SELECT coins FROM economy WHERE guild_id=? AND user_id=?",
                (gid, uid),
            ) as c:
                rr = await c.fetchone()
            bal = int(rr[0]) if rr and rr[0] else 0
            if bal < price:
                return False, f"Il te manque `{price - bal:,}` 🪙 (prix : `{price:,}` 🪙)."
            # Débit + possession + équipe — MÊME transaction (pas de double-dépense)
            owned.append(key)
            await db.execute(
                "UPDATE economy SET coins = coins - ? WHERE guild_id=? AND user_id=?",
                (price, gid, uid),
            )
            await db.execute(
                "INSERT INTO user_cosmetics(guild_id, user_id, owned, active) "
                "VALUES(?,?,?,?) ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "owned=excluded.owned, active=excluded.active",
                (gid, uid, json.dumps(owned), key),
            )
            await db.commit()
        return True, f"Titre **{title_label(key)}** acheté et équipé ! (`-{price:,}` 🪙)"
    except Exception as ex:
        print(f"[cosmetics buy] {ex}")
        return False, "Erreur lors de l'achat (rien n'a été débité)."


async def set_active(guild_id, user_id, key):
    """Équipe un titre possédé, ou '' pour le retirer. Retourne (ok, msg)."""
    if _get_db is None:
        return False, "Indisponible."
    gid, uid = int(guild_id), int(user_id)
    key = key or ""
    try:
        async with _get_db() as db:
            owned, _active = await _read(db, gid, uid)
            if key and key not in owned:
                return False, "Tu ne possèdes pas ce titre."
            await db.execute(
                "INSERT INTO user_cosmetics(guild_id, user_id, owned, active) "
                "VALUES(?,?,?,?) ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "active=excluded.active",
                (gid, uid, json.dumps(owned), key),
            )
            await db.commit()
        return True, (f"Titre **{title_label(key)}** équipé !" if key
                      else "Titre cosmétique retiré.")
    except Exception as ex:
        print(f"[cosmetics set_active] {ex}")
        return False, "Erreur."
