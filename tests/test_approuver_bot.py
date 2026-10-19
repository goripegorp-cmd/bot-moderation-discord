"""20/10/2026 (audit 1 #8) : l'anti-bot-voyou renvoyait vers un reglage `approved_bots` que rien
n'ecrivait ; un bot voulu ne pouvait jamais entrer."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
from discord.ui import Button

import visuels
from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
NOMS = ("TETE_IDS", "_a_la_tete", "_BOTS_REFUSES", "_vue_alerte", "BoutonApprouverBot", "BoutonGere",
        "BoutonFicheSite")


def _ns(conf, ecrits, journal):
    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits.append((k, v))
        conf[k] = v
        return True

    async def au_journal(*a, **k):
        journal.append(a[2])
    ns = {"discord": discord, "Button": Button, "visuels": visuels, "cfg": cfg, "db_set": db_set,
          "_au_journal": au_journal, "_logerr": lambda *a, **k: None}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else
                                           getattr(getattr(n, "target", None), "id", None))
        if nom in NOMS:
            exec(ast.unparse(n), ns)  # noqa: S102
    return ns


def _ids(vue):
    return [c.custom_id for c in vue.children]


def test_B1_l_alerte_d_un_bot_arrete_porte_le_bouton_approuver():
    ns = _ns({}, [], [])
    ns["_BOTS_REFUSES"][55] = 1.0
    assert _ids(ns["_vue_alerte"](55)) == ["alerte:botok:55", "alerte:gere:55"]
    assert _ids(ns["_vue_alerte"](7)) == ["alerte:fiche:7", "alerte:gere:7"]


def test_B2_seule_la_tete_approuve_et_l_approbation_est_ecrite():
    conf, ecrits, journal = {"approved_bots": [11]}, [], []
    ns = _ns(conf, ecrits, journal)
    ns["_BOTS_REFUSES"][55] = 1.0
    recus = []

    async def envoyer(texte, **k):
        recus.append(texte)

    async def rien(*a, **k):
        return None

    def inter(uid):
        return Obj(guild=Obj(id=1, owner_id=0), user=Obj(id=uid, display_name="x"),
                   response=Obj(send_message=envoyer, defer=rien), followup=Obj(send=envoyer),
                   message=Obj(edit=rien))
    bouton = ns["BoutonApprouverBot"](55)
    asyncio.run(bouton.callback(inter(123)))
    assert ecrits == [] and "Réservé" in recus[-1], "un membre du staff ne fait pas entrer un bot"
    asyncio.run(bouton.callback(inter(781205382923288593)))
    assert ecrits == [("approved_bots", [11, 55])] and recus[-1].startswith("✅")
    assert 55 not in ns["_BOTS_REFUSES"] and journal == ["bot.approuve"]


def test_B3_le_texte_ne_renvoie_plus_vers_un_reglage_fantome():
    src = ast.unparse(ARBRE)
    assert "puis ré-ajoute-le._" not in src.replace("sous cette alerte, puis ré-ajoute-le._", "")
    assert "BoutonFicheSite, BoutonApprouverBot)" in src


def _confirmation(isoles, fondateur=False):
    import ui_v2
    faits = []

    async def isolate_member(m, motif):
        faits.append(("isoler", m.id))
        return {"isolated": m.id in isoles}

    async def update_alt_status(*a):
        faits.append(("alt", a[1]))
    ns = {"discord": discord, "Button": Button, "visuels": visuels, "LayoutView": ui_v2.LayoutView,
          "v2_container": ui_v2.container, "v2_body": ui_v2.body, "Palette": ui_v2.Palette,
          "owner_ids_module": Obj(is_super_owner=lambda uid: fondateur), "isolate_member": isolate_member,
          "update_alt_status": update_alt_status, "_logerr": lambda *a, **k: None}
    exec(next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "ConfirmerIsolementV2"), ns)  # noqa: S102
    return ns["ConfirmerIsolementV2"], faits


def _texte(vue):
    return " ".join(getattr(x, "content", "") for x in vue.walk_children())


def test_B4_l_isolement_de_masse_ne_compte_que_ce_qui_a_ete_fait():
    """Audit 1 #9 : « N isole(s) » sans verifier ; les boutons disaient « kick … irreversible »."""
    Classe, faits = _confirmation(isoles={1})
    recus = []

    async def rien(*a, **k):
        recus.append(k.get("view"))
    cibles = [{"member": Obj(id=1), "confidence": 90}, {"member": Obj(id=2), "confidence": 85}]
    vue = Classe(Obj(id=9), Obj(id=5), cibles, "alts")
    assert "Isoler 2 compte(s)" in _texte(vue) and "irréversible" not in _texte(vue)
    i = Obj(user=Obj(id=9), response=Obj(edit_message=rien), edit_original_response=rien)
    asyncio.run(vue._confirmer(i))
    assert "**1** isolé(s) · **1** échec(s)" in _texte(vue)
    assert faits == [("isoler", 1), ("alt", 1), ("isoler", 2)], "le compte non isole n'est pas note traite"


def test_B5_renvoyer_des_bots_est_reserve_au_fondateur():
    Classe, _ = _confirmation(isoles=set())
    renvoyes, recus = [], []

    async def kick(**k):
        renvoyes.append(1)

    async def dire(texte=None, **k):
        recus.append(texte)
    vue = Classe(Obj(id=9), Obj(id=5), [{"member": Obj(id=3, kick=kick)}], "bots")
    i = Obj(user=Obj(id=9), response=Obj(send_message=dire, edit_message=dire), edit_original_response=dire)
    asyncio.run(vue._confirmer(i))
    assert renvoyes == [] and "fondateur" in recus[-1]
    Classe2, _ = _confirmation(isoles=set(), fondateur=True)
    vue = Classe2(Obj(id=9), Obj(id=5), [{"member": Obj(id=3, kick=kick)}], "bots")
    asyncio.run(vue._confirmer(i))
    assert renvoyes == [1] and "**1** renvoyé(s)" in _texte(vue)
