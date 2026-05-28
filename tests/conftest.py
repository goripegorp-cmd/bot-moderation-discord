"""Fixtures partagées pour les tests Phase 164.3.

On évite d'importer bot.py directement (trop lourd, ~73k lignes).
On teste les modules isolés via stubs de get_db + db_get.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path

import pytest

# Permet aux tests d'importer les modules racine
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _StubCursor:
    """Cursor in-memory minimal pour les tests."""

    def __init__(self, rows=None):
        self._rows = list(rows or [])
        self.rowcount = 0
        self.lastrowid = 1

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class StubDB:
    """Connexion DB in-memory minimaliste pour les tests.

    Ne fait pas de vrai SQL — retourne juste des rows pré-configurés
    selon le pattern de la query. Suffit pour vérifier que les modules
    n'explosent pas + que la logique pure (calculs, dicts) fonctionne.
    """

    def __init__(self):
        self._next_rows: list = []
        self._executed: list[tuple[str, tuple]] = []

    def queue_rows(self, rows):
        """Pré-charge les prochaines rows à retourner sur execute()."""
        self._next_rows = list(rows)

    async def execute(self, query: str, params: tuple = ()):
        self._executed.append((query, params))
        rows = self._next_rows
        self._next_rows = []
        return _StubCursor(rows)

    async def commit(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def stub_db():
    """Renvoie une factory async-with qui produit StubDB."""
    db = StubDB()

    @contextlib.asynccontextmanager
    async def _factory():
        yield db

    return db, _factory


@pytest.fixture
def stub_cfg():
    """Stub pour db_get(guild_id) → renvoie un dict de config."""
    store = {}

    async def _db_get(gid: int) -> dict:
        return dict(store.get(int(gid), {}))

    return store, _db_get


@pytest.fixture
def event_loop():
    """Boucle asyncio dédiée par test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
