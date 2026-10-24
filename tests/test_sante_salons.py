"""24/10/2026, revue complète : « vérifie… chacun des salons, que tout soit opérationnel ». /stats dit, sans appel
réseau, ce que le bot ne peut pas faire dans chaque salon que la configuration lui confie ; et les erreurs des
commandes slash sont comptées avec celles des boutons."""
from __future__ import annotations

import ast
from pathlib import Path

import discord

import diag
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _ns():
    ns = {"discord": discord}
    for n in ARBRE.body:
        if getattr(n, "name", None) in ("_chemins_ids", "_sante_salons") or (
                isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_BESOINS_SALON"):
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


class _Texte(discord.TextChannel):
    def __init__(self, cid, droits):
        self.id, self._droits = cid, droits

    def permissions_for(self, _m):
        return Obj(**{**dict(view_channel=True, send_messages=True, read_message_history=True), **self._droits})


class _Vocal(discord.VoiceChannel):
    def __init__(self, cid, droits):
        self.id, self._droits = cid, droits

    def permissions_for(self, _m):
        return Obj(**{**dict(view_channel=True, connect=True, move_members=True), **self._droits})


def test_S1_chaque_salon_de_la_configuration_ce_que_le_bot_ne_peut_pas_y_faire():
    ns = _ns()
    cadeaux = _Texte(111111111111111111, {})
    liens = _Texte(222222222222222222, {"send_messages": False})
    join = _Vocal(333333333333333333, {"move_members": False})
    salons = {x.id: x for x in (cadeaux, liens, join)}
    g = Obj(me=Obj(id=1), get_channel=lambda cid: salons.get(cid))
    c = {"cadeaux_salon": cadeaux.id, "game_link_salon": liens.id, "mod_log_channel": 0,
         "temp_voice_config": {"enabled": True, "hubs": {str(join.id): {"category": 5}}},
         "zones_salons": {"aide": cadeaux.id}}
    r = ns["_sante_salons"](g, c)
    assert r["verifies"] == 3, "chaque salon une fois, les Join (clés du dictionnaire) compris"
    assert r["problemes"] == ["game_link_salon (_Texte) : écrire", "temp_voice_config (_Vocal) : déplacer"]


def test_S2_les_erreurs_des_commandes_slash_comptent():
    corps = next(ast.unparse(n) for n in ARBRE.body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_app_command_error")
    assert "diag.compter('ui', f'/{cmd_name}'" in corps
    assert corps.index("diag.compter") > corps.index("CheckFailure"), "un refus normal n'est pas une erreur"
    assert '"sante_salons": next(' in SRC
    diag._COMPTES.clear()
    diag.compter("ui", "/giveaway", RuntimeError("x"))
    assert "ui//giveaway:RuntimeError" in diag.releve("ui")
