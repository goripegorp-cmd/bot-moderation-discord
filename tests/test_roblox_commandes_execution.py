"""Les commandes `/roblox` sont-elles seulement EXÉCUTABLES ?

═══════════════════════════════════════════════════════════════════════════════
LE TROU QUE LA RÉFUTATION DU 30/08 A MESURÉ
═══════════════════════════════════════════════════════════════════════════════
    roblox_commandes : 0 / 7 fonctions exécutées par un test
    les 8 sous-commandes /roblox : 0 exécution
    mutation « raise RuntimeError en 1ʳᵉ ligne de /roblox sante » : 0 échec

Autrement dit : les tests vérifiaient que les commandes EXISTENT et que leur
source contient les bons mots, jamais qu'elles TOURNENT. Une commande qui
plante à la première ligne passait toute la suite au vert.

C'est exactement la règle du propriétaire prise en défaut : « une fonction non
appelée n'est pas opérationnelle, même parfaite ». Ces tests l'appellent.

⚠️ CE FICHIER N'EST PAS UN TEST D'AFFICHAGE. Il ne juge pas la beauté des
fiches : il vérifie que chaque commande va jusqu'au bout sans lever, qu'elle
répond TOUJOURS (une interaction sans réponse affiche « Échec de
l'interaction », qui se lit comme une panne), et qu'un refus de droits répond
lui aussi.
"""
from __future__ import annotations

import contextlib

import aiosqlite
import pytest

import roblox_commandes as cmds
import roblox_marche as marche
import roblox_veille as veille


# ═══════════════════════════════════════════════════════════════════════════════
#  Les doublures Discord — elles portent ce que porte le vrai
# ═══════════════════════════════════════════════════════════════════════════════

class _Reponse:
    def __init__(self):
        self.faite = False
        self.messages = []

    def is_done(self):
        return self.faite

    async def defer(self, ephemeral=False):
        self.faite = True

    async def send_message(self, contenu=None, *, view=None, ephemeral=False):
        self.faite = True
        self.messages.append(contenu if contenu is not None else view)


class _Followup:
    def __init__(self, sac):
        self._sac = sac

    async def send(self, contenu=None, *, view=None, ephemeral=False):
        self._sac.append(contenu if contenu is not None else view)


class _Perms:
    administrator = True
    manage_guild = True


class _User:
    id = 7
    guild_permissions = _Perms()


class _Guild:
    id = 4242
    name = "Serveur"
    owner_id = 7

    def get_channel(self, _cid):
        return None


class _Interaction:
    """⚠️ ELLE DOIT PORTER TOUT CE QUE PORTE LA VRAIE. Une doublure plus pauvre
    ferait passer un test sur du code qui plante en production — c'est le
    piège n°6 du dépôt, et il a déjà frappé quatre fois aujourd'hui."""

    def __init__(self):
        self.envois = []
        self.response = _Reponse()
        self.followup = _Followup(self.envois)
        self.guild = _Guild()
        self.user = _User()

    @property
    def tout(self):
        return self.envois + self.response.messages


@pytest.fixture
def banc(tmp_path, monkeypatch):
    """Une base réelle, et le réseau coupé : on éprouve le CODE, pas Roblox."""
    chemin = tmp_path / "cmd.db"

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    conf = {"roblox_veille_enabled": True, "roblox_salon_nouveautes": 99}

    async def _cfg(_g):
        return dict(conf)

    async def _db_set(_g, k, v):
        conf[k] = v
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                 log=lambda *a, **k: None)
    marche.brancher_base(_get_db)
    marche.setup(log=lambda *a, **k: None)
    cmds.setup(autorise=None, log=lambda *a, **k: None)
    return conf


async def _prep(banc):
    await veille.init_db()
    await marche.init_db()


class _RepVide:
    status = 200

    async def json(self):
        return {"data": [], "nextPageCursor": None}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _SessVide:
    def get(self, url, params=None):
        return _RepVide()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Chaque commande va au bout, et répond
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("nom", ["sante", "recents", "limited", "predictions",
                                 "modele"])
async def test_chaque_commande_sans_argument_va_au_bout(banc, monkeypatch, nom):
    """⚠️ LE TEST QUI MANQUAIT. Une mutation `raise RuntimeError` en première
    ligne de `/roblox sante` ne faisait échouer AUCUN test."""
    await _prep(banc)
    monkeypatch.setattr(marche, "_ouvrir", lambda: _SessVide())
    cmd = next(c for c in cmds.groupe.commands if c.name == nom)
    i = _Interaction()
    await cmd.callback(i)
    assert i.tout, f"/roblox {nom} n'a RIEN répondu — « Échec de l'interaction »"


@pytest.mark.asyncio
async def test_la_commande_marche_va_au_bout(banc, monkeypatch):
    await _prep(banc)
    monkeypatch.setattr(marche, "_ouvrir", lambda: _SessVide())
    cmd = next(c for c in cmds.groupe.commands if c.name == "marche")
    i = _Interaction()
    await cmd.callback(i, combien=5)
    assert i.tout


@pytest.mark.asyncio
async def test_article_refuse_proprement_un_identifiant_absurde(banc):
    """Et il RÉPOND : un refus muet se lit comme une panne du bot."""
    await _prep(banc)
    cmd = next(c for c in cmds.groupe.commands if c.name == "article")
    i = _Interaction()
    await cmd.callback(i, identifiant="pas un nombre")
    assert i.tout and "identifiant" in str(i.tout[0]).lower()


@pytest.mark.asyncio
async def test_prediction_refuse_de_predire_et_le_DIT(banc, monkeypatch):
    """Le refus de fabriquer un pourcentage est la meilleure décision de la
    journée. Il doit être EXÉCUTABLE, pas seulement écrit."""
    await _prep(banc)
    monkeypatch.setattr(marche, "_ouvrir", lambda: _SessVide())
    cmd = next(c for c in cmds.groupe.commands if c.name == "prediction")
    i = _Interaction()
    await cmd.callback(i, identifiant="123456789")
    assert i.tout


@pytest.mark.asyncio
async def test_une_commande_refusee_repond_quand_meme(banc):
    """⚠️ TOUJOURS RÉPONDRE AVANT DE REFUSER. Une interaction sans réponse
    affiche « Échec de l'interaction », qui se lit comme une panne et non
    comme un refus. Ce piège a coûté une session entière sur `/rellseas`."""
    async def _refuse_tout(_i):
        return False

    cmds.setup(autorise=_refuse_tout, log=lambda *a, **k: None)
    try:
        cmd = next(c for c in cmds.groupe.commands if c.name == "sante")
        i = _Interaction()
        await cmd.callback(i)
        assert i.tout, "le refus est muet : le membre croira à une panne"
        assert "réservée" in str(i.tout[0])
    finally:
        cmds.setup(autorise=None, log=lambda *a, **k: None)


@pytest.mark.asyncio
async def test_une_panne_de_base_ne_fait_pas_planter_la_commande(banc, monkeypatch):
    """Une commande de DIAGNOSTIC qui plante quand la base tombe est celle qui
    servait justement à comprendre pourquoi la base est tombée."""
    await _prep(banc)
    monkeypatch.setattr(marche, "_ouvrir", lambda: _SessVide())

    @contextlib.asynccontextmanager
    async def _base_cassee():
        raise RuntimeError("base indisponible")
        yield  # pragma: no cover

    monkeypatch.setattr(veille, "_get_db", _base_cassee)
    cmd = next(c for c in cmds.groupe.commands if c.name == "sante")
    i = _Interaction()
    await cmd.callback(i)
    assert i.tout, "la commande n'a rien répondu alors que la base est tombée"
