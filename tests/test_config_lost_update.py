"""La config perdait des clés en silence — trouvé le 23/08/2026.

LE SYMPTÔME EN PRODUCTION
    [activite_passage_task] … observation=0 j (depuis 2026-08-23)
trois jours de suite, l'ancre toujours datée du jour même. Elle ne pouvait donc
jamais vieillir, `jugeable` restait faux, et le système d'activité entier
restait inerte sur 974 membres — alors que le propriétaire disait que les trois
quarts du serveur étaient inactifs.

⚠️ CE N'ÉTAIT PAS UN DÉFAUT DU SYSTÈME D'ACTIVITÉ.
Toute la configuration d'une guilde vit dans UN SEUL blob JSON
(`guild_config.data`), réécrit EN ENTIER à chaque `db_set`. Or `db_set` lisait
l'état de départ via `db_get`, c'est-à-dire via le CACHE — et `db_get` remplit
ce cache APRÈS ses `await` (acquisition du pool, puis SELECT).

L'entrelacement, reproduit de façon déterministe ci-dessous :
  1. une tâche lit la config ; son SELECT part, elle rend la main ;
  2. une autre écrit l'ancre : verrou, écriture, cache invalidé ;
  3. la première REPREND et repose dans le cache son instantané ANTÉRIEUR,
     horodaté « maintenant », donc servi comme frais pendant 30 secondes ;
  4. n'importe quelle écriture suivante repart de cet instantané périmé et
     réécrit le blob SANS la clé posée à l'étape 2.

Le verrou par guilde ne protégeait que `db_set` contre `db_set` : il ne voyait
pas passer la repopulation du cache.

⚠️ LA PORTÉE EST GÉNÉRALE. N'importe quelle clé récemment écrite pouvait
disparaître de la même façon : un salon de logs, un rôle de sanction, un
interrupteur anti-raid. L'ancre d'observation n'était que le témoin visible,
parce qu'elle est réécrite à chaque démarrage et que son absence se lit dans
les logs.

LE CORRECTIF : `db_set` relit la ligne DEPUIS LA BASE, à l'intérieur du verrou.
"""
from __future__ import annotations

import ast
import asyncio
import json
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


def _classe(nom: str):
    """Extrait une classe de bot.py sans l'importer (la CI n'a pas de token)."""
    for n in ast.parse(SRC_BOT).body:
        if isinstance(n, ast.ClassDef) and n.name == nom:
            ns = {"time": time, "asyncio": asyncio, "json": json}
            exec(ast.unparse(n), ns)          # noqa: S102 — code du dépôt
            return ns[nom]
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _fonction(nom: str) -> str:
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le banc : la VRAIE classe de cache, un magasin en mémoire
# ═══════════════════════════════════════════════════════════════════════════════

class _Banc:
    """Rejoue `db_get`/`db_set` avec le vrai `ConfigCache` du dépôt.

    `db_set_depuis_cache` est l'ANCIENNE version (celle qui perdait des clés),
    `db_set_depuis_base` la nouvelle. Les deux subissent le même entrelacement.
    """

    def __init__(self):
        self.cache = _classe("ConfigCache")(max_size=100, ttl_seconds=30)
        self.base: dict[int, str] = {}
        self.verrous: dict[int, asyncio.Lock] = {}

    def _lock(self, gid):
        return self.verrous.setdefault(gid, asyncio.Lock())

    async def db_get(self, gid):
        cle = -int(gid)
        c = self.cache.get(cle)
        if c is not None:
            return c
        await asyncio.sleep(0)                 # le await du pool
        brut = self.base.get(gid)
        await asyncio.sleep(0)                 # le await du SELECT
        data = json.loads(brut) if brut else {}
        self.cache.set(cle, data)              # ← APRÈS les await
        return data

    async def _ecrire(self, gid, data):
        self.base[gid] = json.dumps(data)
        self.cache.invalidate(gid)
        self.cache.invalidate(-int(gid))

    async def db_set_depuis_cache(self, gid, key, val):
        async with self._lock(gid):
            data = await self.db_get(gid)      # ← LE DÉFAUT
            data[key] = val
            await self._ecrire(gid, data)

    async def db_set_depuis_base(self, gid, key, val):
        async with self._lock(gid):
            await asyncio.sleep(0)             # le await du pool
            brut = self.base.get(gid)          # ← LA BASE
            data = json.loads(brut) if brut else {}
            data[key] = val
            await self._ecrire(gid, data)

    async def lecteur_en_vol(self, gid):
        """Un lecteur parti AVANT l'écriture, qui repose son instantané après."""
        cle = -int(gid)
        await asyncio.sleep(0)
        brut = self.base.get(gid)
        await asyncio.sleep(0)
        await asyncio.sleep(0.02)              # l'écriture passe pendant ce temps
        self.cache.set(cle, json.loads(brut) if brut else {})


async def _scenario(ecrire) -> dict:
    """Écrit une clé, laisse un lecteur périmé repeupler le cache, puis écrit
    autre chose. Rend l'état FINAL de la base."""
    b, gid = _Banc(), 42
    b.base[gid] = json.dumps({"activite_enabled": True})
    b.cache.clear()
    t = asyncio.create_task(b.lecteur_en_vol(gid))
    await asyncio.sleep(0.005)
    await ecrire(b)(gid, "activite_observe_depuis", "2026-08-20")
    await t
    await ecrire(b)(gid, "activite_salon_staff", 123456789)
    return json.loads(b.base[gid])


@pytest.mark.asyncio
async def test_lancienne_version_perdait_bien_la_cle():
    """⚠️ LA PREUVE DU DÉFAUT. Sans elle, le correctif ne prouve rien : un test
    qui passe sur le code corrigé ne dit pas qu'il aurait attrapé le bug."""
    final = await _scenario(lambda b: b.db_set_depuis_cache)
    assert "activite_observe_depuis" not in final, (
        "l'ancienne version devait perdre la clé — le banc ne reproduit plus "
        "l'entrelacement, il faut le réparer avant de faire confiance au reste")


@pytest.mark.asyncio
async def test_la_nouvelle_version_garde_la_cle():
    final = await _scenario(lambda b: b.db_set_depuis_base)
    assert final.get("activite_observe_depuis") == "2026-08-20"
    assert final.get("activite_salon_staff") == 123456789
    assert final.get("activite_enabled") is True


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le vrai `db_set` du dépôt applique bien la règle
# ═══════════════════════════════════════════════════════════════════════════════

def test_db_set_relit_la_base_et_pas_le_cache():
    """⚠️ LA LIGNE QUI COMPTE. `data = await db_get(gid)` réintroduirait le
    défaut d'un seul mot."""
    corps = _fonction("db_set")
    assert "SELECT data FROM guild_config WHERE guild_id=?" in corps, (
        "db_set doit relire la base à l'intérieur du verrou")
    assert "await db_get(gid)" not in corps, (
        "db_set ne doit JAMAIS repartir du cache : c'est le défaut du 23/08")


def test_la_relecture_est_dans_le_verrou():
    corps = _fonction("db_set")
    i_verrou = corps.index("_get_config_lock")
    i_lecture = corps.index("SELECT data FROM guild_config")
    assert i_verrou < i_lecture, (
        "relire hors du verrou rouvrirait la course entre deux db_set")


def test_le_cache_reste_invalide_des_deux_cotes():
    """`db_get` et `cfg` utilisent deux clés de cache distinctes ; oublier
    l'une des deux servirait une config périmée pendant 30 s."""
    corps = _fonction("db_set")
    assert "_config_cache.invalidate(gid)" in corps
    assert "_config_cache.invalidate(-int(gid))" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Une écriture refusée ne doit plus être muette
# ═══════════════════════════════════════════════════════════════════════════════

def test_lecriture_de_lancre_verifie_son_retour():
    """`db_set` rend `False` sans lever quand elle refuse d'écrire. Jeter ce
    retour rendait « jamais écrite » indiscernable de « écrite puis effacée »."""
    src = (RACINE / "activite.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "observation_jours":
            corps = ast.unparse(n)
            assert "_ok = await _db_set" in corps
            assert "REFUSÉE" in corps
            return
    raise AssertionError("observation_jours introuvable")


def test_le_rearmement_manuel_est_journalise():
    """C'est le seul geste volontaire qui remet l'ancre à aujourd'hui. Sans
    trace, un clic du staff et une perte accidentelle sont indiscernables."""
    src = (RACINE / "activite_panneau.py").read_text(encoding="utf-8")
    assert "RÉARMEMENT" in src
