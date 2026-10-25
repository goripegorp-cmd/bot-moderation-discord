"""25/10/2026, le fondateur : « Il y a des gens qui créent des tickets, mais je ne les vois pas sur le serveur…
vérifie les tickets qui sont actifs et ceux que je ne vois pas. »

Un ticket est un fil privé : Discord ne le montre dans la liste des salons qu'à ses membres. Le bot n'y ajoutait que
l'ouvreur. Désormais le fondateur, la direction et l'équipe du type y entrent, sans notification."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord

from conftest_discord import Obj
from faux_serveur import Fil, Monde, run, textes
from ui_v2 import LayoutView, Palette

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)


class FilTicket(Fil):
    """Un fil privé qui sait dire ses membres ; la mention d'une modification y fait entrer (ou non)."""
    entrer_par_mention = True

    def __init__(self, monde, tid, parent, name):
        super().__init__(monde, tid, parent, name)
        self.dedans, self.ajouts, self.cartes_equipe = set(), [], []

    async def send(self, content=None, **kw):
        fil = self

        class Msg:
            async def edit(self, **k):
                fil.cartes_equipe.append(k)
                if fil.entrer_par_mention:
                    am = k["allowed_mentions"]
                    for u in am.users or []:
                        fil.dedans.add(u.id)
                    for r in am.roles or []:
                        fil.dedans.update(m.id for m in r.members)
        fil.cartes_equipe.append(kw)
        return Msg()

    async def fetch_members(self):
        return [Obj(id=x) for x in self.dedans]

    async def add_user(self, m):
        self.ajouts.append(m.id)
        self.dedans.add(m.id)


def _ns(g, staff, extras=()):
    ns = {"discord": discord, "LayoutView": LayoutView, "Palette": Palette, "TETE_IDS": {FONDATEUR, DIRECTION},
          "EQUIPE_TICKET_MAX": 30, "_logerr": lambda *a, **k: None, "_COMPTES_SUPPRIMES": set()}
    for nom in ("_equipe_a_voir", "_carte_equipe", "_faire_voir_ticket", "_echec", "_SansCarte"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt

    async def cfg(_gid):
        return {}

    async def sans_attente(_s):
        return None
    ns.update(cfg=cfg, _equipe_du_type=lambda g_, c, pid: (staff, list(extras), ""),
              asyncio=Obj(sleep=sans_attente))
    return ns


def _serveur():
    g = Monde()
    fondateur, direction = g.membre(FONDATEUR), g.membre(DIRECTION)
    staff = Obj(id=500, mention="<@&500>", is_default=lambda: False, members=[g.membre(31), g.membre(32)])
    for m in staff.members + [fondateur, direction]:
        m.bot = False
    return g, staff


def test_V1_le_fondateur_la_direction_et_l_equipe_entrent_sans_notification():
    g, staff = _serveur()
    ns = _ns(g, staff)
    fil = FilTicket(g, 9001, None, "ticket-x")
    r = run(ns["_faire_voir_ticket"](g, fil, "1", ouvreur_id=31))
    assert {FONDATEUR, DIRECTION, 32} <= fil.dedans and 31 not in fil.ajouts, "l'ouvreur y est déjà"
    envoi, modif = fil.cartes_equipe
    assert envoi["allowed_mentions"].users is False or not envoi["allowed_mentions"].users, \
        "la carte part SANS mention : personne n'est notifié"
    assert "<@&500>" in textes(modif["view"]) and f"<@{FONDATEUR}>" in textes(modif["view"])
    assert r == {"cibles": 3, "par_mention": 3, "un_par_un": 0, "erreurs": 0, "inconnus": 0, "detail": []}


def test_V2_si_la_mention_ne_suffit_pas_chacun_est_ajoute_un_par_un():
    g, staff = _serveur()
    ns = _ns(g, staff)
    fil = FilTicket(g, 9002, None, "ticket-y")
    fil.entrer_par_mention = False
    r = run(ns["_faire_voir_ticket"](g, fil, "1", ouvreur_id=0))
    assert sorted(fil.ajouts) == sorted([FONDATEUR, DIRECTION, 31, 32]) and r["un_par_un"] == 4


def test_V3_un_ticket_en_salon_classique_n_est_pas_touche_et_c_est_branche():
    g, staff = _serveur()
    ns = _ns(g, staff)
    r = run(ns["_faire_voir_ticket"](g, g.nom("💬chat"), "1"))
    assert r["cibles"] == 0
    assert "_faire_voir_plus_tard(i.guild, ch, pid, i.user.id, tid)" in _source("_create_ticket_corps")
    boucle = _source("entraide_task")
    assert "db_set(g.id, 'tickets_vus_v1'" in boucle and "await _verifier_tickets_ouverts(g)" in boucle
    assert '"tickets_vus": dict(_TICKETS_VUS) or None' in SRC
    _ = asyncio


def test_V4_une_passe_sans_carte_et_l_echec_dit_ce_qui_casse_sans_identifiant():
    g, staff = _serveur()
    ns = _ns(g, staff)
    fil = FilTicket(g, 9003, None, "ticket-z")
    fil.entrer_par_mention = False

    async def refus(m):
        raise discord.Forbidden(Obj(status=403, reason="x"), {"code": 50013, "message": "Missing Permissions"})
    fil.add_user = refus
    r = run(ns["_faire_voir_ticket"](g, fil, "1", ouvreur_id=0, carte=False))
    assert fil.cartes_equipe == [], "aucune carte en plus dans un ticket déjà suivi"
    assert r["erreurs"] == 4 and r["detail"][:2] == ["ajout:Forbidden:403:50013:fondateur", "ajout:Forbidden:403:50013:direction"]
    assert all(str(FONDATEUR) not in d and str(DIRECTION) not in d for d in r["detail"])
    assert "diag.compter('bot', where, ex)" in _source("_logerr") and '"erreurs_bot": diag.releve("bot")' in SRC
    boucle = _source("entraide_task")
    assert "db_set(g.id, 'tickets_vus_v2'" in boucle and "carte=False, cle='verification_2'" in boucle


def test_V5_un_compte_supprime_n_est_ni_une_erreur_ni_retente():
    g, staff = _serveur()
    ns = _ns(g, staff)
    fil = FilTicket(g, 9004, None, "ticket-w")
    fil.entrer_par_mention = False
    ajouts = []

    async def inconnu(m):
        if m.id == 32:
            raise discord.NotFound(Obj(status=404, reason="x"), {"code": 10013, "message": "Unknown User"})
        ajouts.append(m.id)
    fil.add_user = inconnu
    r = run(ns["_faire_voir_ticket"](g, fil, "1", ouvreur_id=0))
    assert r["inconnus"] == 1 and r["erreurs"] == 0 and sorted(ajouts) == sorted([FONDATEUR, DIRECTION, 31])
    assert 32 in ns["_COMPTES_SUPPRIMES"]
    gens, _roles = ns["_equipe_a_voir"](g, {}, "1")
    assert 32 not in [m.id for m in gens], "plus jamais retenté"
