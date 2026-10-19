"""19/10/2026 (audit) : le verrouillage anti-raid notait le niveau « d'avant » à chaque déclenchement
— au 2e raid, c'était déjà le maximum — et le rétablissait par une tâche en mémoire, perdue au
redémarrage. Le serveur pouvait rester verrouillé pour toujours."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord

from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


class Horloge:
    t = 1_000_000.0

    @classmethod
    def time(cls):
        return cls.t


def _fonctions(conf):
    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v
    ns = {"discord": discord, "cfg": cfg, "db_set": db_set, "time": Horloge, "print": lambda *a: None,
          "_logerr": lambda *a, **k: None}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in ("VERROU_RAID_MINUTES", "_verrou_raid", "_lever_verrou_raid"):
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def test_R1_deux_raids_puis_un_redemarrage_le_niveau_d_avant_revient():
    conf = {}
    ns = _fonctions(conf)
    edits = []

    class Serveur:
        id = 1
        verification_level = discord.VerificationLevel.medium

        async def edit(self, *, verification_level, reason):
            edits.append(verification_level)
            self.verification_level = verification_level
    g = Serveur()

    async def scenario():
        await ns["_verrou_raid"](g)
        Horloge.t += 120
        await ns["_verrou_raid"](g)  # 2e vague pendant le verrou
        assert conf["antiraid_niveau_avant"] == discord.VerificationLevel.medium.value
        await ns["_lever_verrou_raid"](g)
        assert g.verification_level is discord.VerificationLevel.highest, "pas avant l'échéance"
        Horloge.t += ns["VERROU_RAID_MINUTES"] * 60 + 1  # (même après un redémarrage : tout est en base)
        await ns["_lever_verrou_raid"](g)
        assert g.verification_level is discord.VerificationLevel.medium and conf["antiraid_verrou_actif"] == 0
        await ns["_lever_verrou_raid"](g)
    asyncio.run(scenario())
    assert edits == [discord.VerificationLevel.highest, discord.VerificationLevel.medium], edits


def test_R2_un_membre_isole_par_le_raid_ne_poursuit_pas_son_arrivee():
    corps = next(ast.unparse(n) for n in ARBRE.body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_antiraid_join")
    assert "return member.id in isoles" in corps
    assert "_lever_verrou_raid(g)" in next(ast.unparse(n) for n in ARBRE.body
                                                 if getattr(n, "name", "") == "server_controls_task")
    assert "_restore_lockdown" not in corps, "plus de rétablissement en mémoire"


def test_R3_un_compte_recent_toujours_la_poursuit_son_arrivee():
    """Surveillé, exclu, ou expulsion refusée : l'empreinte et l'anti-double-compte passent quand même."""
    corps = next(ast.unparse(n) for n in ARBRE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_member_join")
    i = corps.index("if act == 'kick':")
    bloc = corps[i:i + 700]
    assert "if await _kick_young_account(" in bloc and "Ne pas continuer" not in corps
    assert corps.index("save_user_fingerprint") > i


def test_R4_couper_son_micro_dans_le_hub_ne_cree_pas_de_salon():
    corps = next(ast.unparse(n) for n in ARBRE.body
                 if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_voice_state_update")
    assert "if after.channel and (before.channel is None or before.channel.id != after.channel.id):" in corps


def test_R5_l_anti_nuke_vise_la_bonne_entree_d_audit():
    """Sans la cible, le dernier membre du staff passé par là était compté pour un vocal du bot."""
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "_audit_actor(guild, act, target_id=cible_id, within_sec=12)" in src
    assert "await _antinuke_check(channel.guild, 'channel', channel.id)" in src
    assert "if channel.id not in temp_voice_channels:" in src
