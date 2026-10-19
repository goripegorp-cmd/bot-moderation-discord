"""19/10/2026 (BUG) : « quelqu'un a rejoint un vocal et ça a écrit anti-hop channel alors qu'il n'a
rien fait. Ça a juste créé un salon pour lui… ça l'a kick… ça expulse des gens qui n'ont rien fait »."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
HUB, PERSO, A, B = 100, 200, 300, 400


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and any(
                getattr(t, "id", "") == nom for t in (n.targets if isinstance(n, ast.Assign) else [n.target])):
            return ast.unparse(n)
    raise KeyError(nom)


class Monde:
    def __init__(self, audit=True, deplacements=()):
        self.t = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)
        self.sanctions, self.alertes, self.deplacements = [], [], list(deplacements)
        moi = Obj(guild_permissions=Obj(view_audit_log=audit))

        def audit_logs(limit=25, action=None, after=None):
            async def gen():
                for e in self.deplacements:
                    yield e
            return gen()
        self.g = Obj(id=1, me=moi, audit_logs=audit_logs)
        self.membre = Obj(id=7, bot=False, guild=self.g, mention="<@7>")

        async def move_to(salon, reason=None):
            self.sanctions.append(("deconnecte", salon))

        async def timeout(duree, reason=None):
            self.sanctions.append(("exclu", duree))
        self.membre.move_to, self.membre.timeout = move_to, timeout

        async def cfg(_g):
            return {"temp_voice_config": {"enabled": True, "hubs": {str(HUB): {}}}}

        async def jamais_immunise(_m):
            return False

        async def alerte(*_a, **k):
            self.alertes.append(k)
        self.ns = {"cfg": cfg, "is_fully_immune": jamais_immunise, "now": lambda: self.t, "timedelta": timedelta,
                   "discord": discord, "_logerr": lambda *a, **k: None, "bot": Obj(user=Obj(id=999)),
                   "_register_protection_strike": lambda *a: 1,
                   "ulogger2026": Obj(log_event=alerte, EventType=Obj(SEC_ESCALATION="sec.escalation"))}
        for nom in ("_voice_hop_tracker", "_VOICE_HOP_MAX", "_VOICE_HOP_WINDOW", "_salons_hub", "_geste_vocal",
                    "_sauts_imposes", "_voice_hop_listener"):
            exec(_source(nom), self.ns)  # noqa: S102 — code du dépôt

    def passe(self, avant, apres, secondes=1.0):
        self.t += timedelta(seconds=secondes)
        etat = lambda sid: Obj(channel=Obj(id=sid) if sid else None)
        asyncio.run(self.ns["_voice_hop_listener"](self.membre, etat(avant), etat(apres)))


def test_H1_creer_son_vocal_n_est_jamais_un_saut():
    """Join → le bot le déplace dans son salon → il ressort → recommence : jamais sanctionné."""
    m = Monde()
    for _ in range(5):
        m.passe(None, HUB)
        m.passe(HUB, PERSO, 0.5)
        m.passe(PERSO, None, 0.5)
    assert not m.sanctions and not m.alertes


def test_H2_entrer_et_sortir_en_boucle_est_freine():
    m = Monde()
    for _ in range(6):
        m.passe(None, A)
        m.passe(A, None)
    assert m.sanctions == [("deconnecte", None)], m.sanctions
    assert len(m.alertes) == 1 and "6 entrée(s)" in m.alertes[0]["extra"]["⏱️ Gestes"]


def test_H3_deplace_par_le_staff_jamais_sanctionne():
    deplacements = [Obj(user_id=2, extra=Obj(channel=Obj(id=s), count=1)) for s in (A, B, A, B, A, B)]
    m = Monde(deplacements=deplacements)
    m.passe(None, A)
    for s in (B, A, B, A, B):
        m.passe(A if s == B else B, s)
    assert not m.sanctions and not m.alertes, "les déplacements du staff ne sont pas ses gestes"


def test_H4_sauter_seul_de_salon_en_salon_est_freine():
    m = Monde()
    m.passe(None, A)
    for s in (B, A, B, A, B):
        m.passe(A if s == B else B, s)
    assert m.sanctions == [("deconnecte", None)] and len(m.alertes) == 1


def test_H5_sans_journal_d_audit_seules_les_entrees_comptent():
    m = Monde(audit=False)
    m.passe(None, A)
    for s in (B, A, B, A, B):
        m.passe(A if s == B else B, s)
    assert not m.sanctions, "un saut impossible à vérifier ne sanctionne personne"
    for _ in range(6):
        m.passe(B, None)
        m.passe(None, B)
    assert m.sanctions == [("deconnecte", None)], "des entrées, toujours de lui, oui"


def test_H6_les_sorties_seules_ne_comptent_pas():
    m = Monde()
    for _ in range(4):
        m.passe(None, A, 3)
        m.passe(A, None, 0.2)
    assert not m.sanctions, "4 allers-retours en 13 s : en dessous du seuil"
