"""Revue complète du 24/10/2026 — les restes signalés par la revue des panneaux : les publications des abonnements
en carte V2, le tableau de bord de modération qui répond proprement après un acquittement."""
from __future__ import annotations

import asyncio
from pathlib import Path

import discord

import mod_dashboard
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def test_X1_les_publications_des_abonnements_sont_des_cartes():
    assert "chan.send(content, view=vue" not in SRC, "plus de message texte classique"
    assert "msg = await chan.send(view=carte_embed(e, boutons, haut=\" \".join(haut))," in SRC
    assert "e.set_image(url=str(post.thumbnail_url))" in SRC, "la vignette du post"


def test_X2_le_tableau_de_bord_repond_apres_un_acquittement(monkeypatch):
    envoyes = []

    async def suivi(**kw):
        envoyes.append(kw)

    async def interdit(**kw):
        raise AssertionError("send_message après un defer : Discord refuse")
    i = Obj(guild=Obj(id=1), response=Obj(is_done=lambda: True, send_message=interdit), followup=Obj(send=suivi))

    async def stats(_gid, days=30):
        return {}

    async def audit(_gid):
        return []
    monkeypatch.setattr(mod_dashboard, "_collect_stats", stats)
    monkeypatch.setattr(mod_dashboard, "_collect_staff_audit", audit)
    monkeypatch.setattr(mod_dashboard, "_build_layout", lambda *a, **k: None)
    assert asyncio.run(mod_dashboard.show(i)) is False
    assert envoyes == [{"ephemeral": True, "content": "❌ Tableau de bord indisponible pour le moment."}]

    def casse(*a, **k):
        raise RuntimeError("secret interne")
    monkeypatch.setattr(mod_dashboard, "_build_layout", casse)
    assert asyncio.run(mod_dashboard.show(i)) is False
    assert "secret interne" not in envoyes[-1]["content"], "aucun détail technique au membre"
    _ = discord


def test_X3_le_demarrage_par_etapes_une_erreur_n_arrete_pas_les_suivantes():
    import ast as _ast
    arbre = _ast.parse(SRC)
    boot = next(n for n in arbre.body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "_activite_boot")
    etapes = [n for n in boot.body if isinstance(n, _ast.With)]
    noms = [_ast.unparse(n.items[0].context_expr) for n in etapes]
    assert len(etapes) >= 30 and all(x.startswith("_Etape(") for x in noms)
    for module in ("cadeaux", "annonces", "sondages", "entraide", "tableau", "recrutements", "faq", "vocaux"):
        assert f"_Etape('{module}')" in noms, module
    hors = [_ast.unparse(n) for n in boot.body if not isinstance(n, (_ast.With, _ast.AsyncFunctionDef, _ast.FunctionDef))
            and not (isinstance(n, _ast.Expr) and isinstance(n.value, _ast.Constant))]
    assert hors == [], "plus rien hors d'une étape"
    ns = {"asyncio": asyncio}
    classe = next(n for n in arbre.body if isinstance(n, _ast.ClassDef) and n.name == "_Etape")
    exec(_ast.unparse(classe), ns)  # noqa: S102 — code du dépôt
    notes = []
    ns["_logerr"] = lambda ou, ex, **k: notes.append(ou)
    Etape = ns["_Etape"]
    Etape.ratees = []
    with Etape("a"):
        raise RuntimeError("base occupée")
    with Etape("b"):
        pass
    assert Etape.ratees == ["a"] and notes == ["demarrage.a"]
    try:
        with Etape("c"):
            raise asyncio.CancelledError()
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("un arrêt du bot n'est pas avalé")
    assert '"demarrage": {"etapes_ratees": list(_Etape.ratees)}' in SRC


def test_X4_recidiviste_epargne_dans_son_ticket_et_sanctionne_sans_accueil():
    import ast as _ast
    arbre = _ast.parse(SRC)
    corps = {n.name: _ast.unparse(n) for n in arbre.body if isinstance(n, _ast.AsyncFunctionDef)}
    om = corps["on_message"]
    assert "not await is_ticket_channel(msg.channel)" in om.split("recidivism_module.enforce_on_message")[0][-400:], \
        "la restriction des récidivistes ne touche pas leurs preuves dans un ticket"
    assert "_logerr('recidive.application'" in om
    arrivee = corps["on_member_join"]
    assert "if not _sanctionne:\n            await _handle_welcome(m)" in arrivee, \
        "pas de « Bienvenue » public pour un sanctionné qui revient"
