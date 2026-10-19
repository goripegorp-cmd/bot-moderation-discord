"""19/10/2026 (audit) : le verrouillage anti-raid supprimait TOUS les liens d'invitation (jamais
recréés, alors que « /bouclier off » annonçait « arrivées rétablies »), et sa fin supprimait tout rôle
« Vérification » — le rôle de quarantaine : chaque membre isolé était libéré d'un coup."""
from __future__ import annotations

import asyncio

import raid_detector as R
from conftest_discord import base


class Serveur:
    id = 1

    def __init__(self):
        self.edits, self.supprimes, self.crees = [], [], []
        self.me = type("Moi", (), {"guild_permissions": type("P", (), {"manage_guild": True})()})()
        self.roles = [type("Role", (), {"name": "Vérification", "delete": self._sup})()]
        self.channels = []

    async def _sup(self, **k):
        self.supprimes.append("role")

    async def edit(self, **kw):
        self.edits.append(kw.get("invites_disabled"))

    async def invites(self):
        raise AssertionError("on ne touche plus aux liens d'invitation")

    async def create_role(self, **kw):
        self.crees.append(kw)


def test_B1_les_invitations_sont_en_pause_puis_reprennent_et_la_quarantaine_reste(tmp_path):
    get_db, *_ = base(tmp_path)
    R.setup(None, get_db, None, {})

    async def scenario():
        await R.init_db()
        g = Serveur()
        out = await R.run_lockdown(g, 30)
        assert out["invites_disabled"] is True and not out["errors"]
        assert await R.end_lockdown(g)
        return g
    g = asyncio.run(scenario())
    assert g.edits == [True, False], "pause, puis reprise"
    assert not g.crees and not g.supprimes, "aucun rôle créé ni supprimé (la quarantaine reste)"


# ── /bouclier on / off (19/10/2026, audit #6) ─────────────────────────────────────────────────
import ast as _ast
import json as _json
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path as _Path

import discord

from conftest_discord import Obj

_ARBRE = _ast.parse((_Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
_SANS_PAUSE = Obj(sleep=lambda *_a: _rien())


async def _rien():
    return None


def _bouclier(get_db, erreurs):
    ns = {"discord": discord, "json": _json, "asyncio": _SANS_PAUSE, "get_db": get_db,
          "now": lambda: _dt.now(_tz.utc), "_logerr": lambda ou, ex, **k: erreurs.append(ou)}
    for n in _ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, _ast.Assign) else None)
        if nom in ("_BOUCLIER_DROITS", "_bouclier_lire", "_bouclier_ecrire", "_shield_lock", "_shield_unlock"):
            exec(_ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


class _Salon:
    def __init__(self, cid, refuse=None, **droits):
        self.id, self.refuse = cid, set(refuse or ())
        self.ow = discord.PermissionOverwrite(**droits)

    def overwrites_for(self, _role):
        return discord.PermissionOverwrite(**dict(self.ow))

    def permissions_for(self, _membre):
        return Obj(manage_roles=True)

    async def set_permissions(self, _role, *, overwrite, reason):
        if "toujours" in self.refuse or self.refuse and self.refuse.pop():
            raise discord.HTTPException(Obj(status=403, reason="x"), "refus")
        self.ow = overwrite


class _Guilde:
    id = 7
    default_role = Obj(name="@everyone")
    me = Obj(name="bot")

    def __init__(self, *salons):
        self.text_channels = list(salons)

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == cid), None)


def _note(get_db):
    async def lire():
        async with get_db() as db:
            async with db.execute("SELECT channels FROM raid_shield WHERE guild_id=7") as cur:
                row = await cur.fetchone()
        return _json.loads(row[0]) if row else None
    return lire


def test_B2_un_second_bouclier_n_efface_pas_le_premier_et_tout_revient_tel_quel(tmp_path):
    get_db, *_ = base(tmp_path)
    ns, erreurs = _bouclier(get_db, []), []
    reactions = _Salon(1, add_reactions=False)        # réactions refusées EXPRÈS
    neutre = _Salon(2)
    muet = _Salon(3, send_messages=False)             # déjà en lecture seule : pas à nous
    g = _Guilde(reactions, neutre, muet)

    async def scenario():
        assert await ns["_shield_lock"](g) == 2
        neutre.ow.send_messages = True                # quelqu'un le rouvre à la main pendant le raid
        assert await ns["_shield_lock"](g) == 1, "le second bouclier le referme"
        assert set(await _note(get_db)()) == {"1", "2"}, "la liste du premier est gardée"
        assert await ns["_shield_unlock"](g) == (2, 0)
        return await _note(get_db)()
    assert asyncio.run(scenario()) is None, "plus rien à rouvrir"
    assert reactions.ow.add_reactions is False and reactions.ow.send_messages is None, "le refus exprès reste"
    assert neutre.ow.is_empty(), "les droits d'AVANT le premier bouclier, pas l'état bricolé pendant"
    assert muet.ow.send_messages is False and not erreurs


def test_B3_un_salon_que_discord_refuse_de_rouvrir_reste_note_pour_la_fois_suivante(tmp_path):
    get_db, *_ = base(tmp_path)
    erreurs = []
    ns = _bouclier(get_db, erreurs)
    tetu, docile = _Salon(1), _Salon(2)
    g = _Guilde(tetu, docile)

    async def scenario():
        assert await ns["_shield_lock"](g) == 2
        tetu.refuse.add("une fois")
        assert await ns["_shield_unlock"](g) == (1, 1)
        assert set(await _note(get_db)()) == {"1"}
        assert await ns["_shield_unlock"](g) == (1, 0)
        return await _note(get_db)()
    assert asyncio.run(scenario()) is None
    assert tetu.ow.is_empty() and docile.ow.is_empty() and erreurs == ["bouclier.retrait"]


def test_B4_un_salon_qu_on_n_a_pas_pu_fermer_n_est_pas_note(tmp_path):
    get_db, *_ = base(tmp_path)
    erreurs = []
    ns = _bouclier(get_db, erreurs)
    g = _Guilde(_Salon(1), _Salon(2, refuse={"toujours"}))

    async def scenario():
        assert await ns["_shield_lock"](g) == 1
        return await _note(get_db)()
    assert set(asyncio.run(scenario())) == {"1"} and erreurs == ["bouclier.verrou"]


def test_B5_l_ancien_format_une_simple_liste_se_rouvre_encore(tmp_path):
    get_db, *_ = base(tmp_path)
    ns = _bouclier(get_db, [])
    ferme = _Salon(5, send_messages=False, add_reactions=False)
    g = _Guilde(ferme)

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE raid_shield(guild_id INTEGER PRIMARY KEY, channels TEXT, started_at TEXT)")
            await db.execute("INSERT INTO raid_shield VALUES(7, '[5]', '')")
            await db.commit()
        return await ns["_shield_unlock"](g)
    assert asyncio.run(scenario()) == (1, 0) and ferme.ow.is_empty()


def test_B6_les_messages_ne_promettent_que_ce_qui_a_ete_fait(tmp_path):
    """« arrivées rétablies » seulement si Discord a accepté ; sinon le message le dit."""
    get_db, *_ = base(tmp_path)
    R.setup(None, get_db, None, {})

    class Refuse(Serveur):
        async def edit(self, **kw):
            raise discord.HTTPException(Obj(status=403, reason="x"), "refus")

    async def scenario():
        await R.init_db()
        return await R.end_lockdown(Refuse())
    assert asyncio.run(scenario()) is False
    corps = {n.name: _ast.unparse(n) for n in _ARBRE.body if isinstance(n, _ast.AsyncFunctionDef)
             and n.name in ("bouclier_on", "bouclier_off")}
    assert "'arrivées en pause' if pause" in corps["bouclier_on"]
    assert "'arrivées rétablies' if reprise" in corps["bouclier_off"]
    assert "except Exception:\n        pass" not in corps["bouclier_on"] + corps["bouclier_off"]


def test_B7_un_pseudo_ordinaire_n_est_plus_suspect():
    """Audit 2 #17 : la branche CamelCase sans casse notait +3 « goripe », « minecraft »."""
    for nom in ("goripe", "minecraft", "theoaventurier", "lea.martin"):
        assert R._score_pseudo(nom) == 0, nom
    for nom in ("user12345", "abcdefgh12345", "xxdarkxx", "aaaaaa"):
        assert R._score_pseudo(nom) == R.SCORE_BOT_PATTERN, nom


def test_B8_les_arrivants_jumeaux_sont_reperes_et_une_alerte_ignoree_ne_revient_pas(tmp_path):
    get_db, *_ = base(tmp_path)
    R.setup(None, get_db, None, {})

    class Membre:
        def __init__(self, uid, nom):
            self.id, self.name, self.bot, self.avatar = uid, nom, False, None
            self.created_at = _dt.now(_tz.utc)
            self.guild = Obj(id=1)

    async def scenario():
        await R.init_db()
        await R.on_member_join(Membre(1, "nitroboost1"))
        recents = await R._get_recent_joins(1, 10)
        assert recents[0]["racine"] == "nitrob" and "name" not in recents[0], "la racine, pas le pseudo"
        assert R._detect_pseudo_twins(recents, "nitroboost77", 2) == R.SCORE_PSEUDO_TWIN
        assert R._detect_pseudo_twins(recents, "nitroboost1", 1) == 0, "pas jumeau de soi-même"
        async with get_db() as db:
            await db.execute("INSERT INTO raid_alerts(guild_id, status) VALUES(1, 'false_positive')")
            await db.commit()
        return await R._has_recent_alert(1, 30)
    assert asyncio.run(scenario()) is True, "« Ignorer » ne relance pas l'alerte à chaque arrivée"
