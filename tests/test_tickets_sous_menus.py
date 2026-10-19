"""19/10/2026 (audit) : /configure → Tickets → un type de ticket → Catégorie, Questions, Liste noire
répondaient « Erreur 400 » (un message V2 édité avec un embed). Les sous-menus sont en V2 de bout en
bout ; ces tests construisent les composants tels que Discord les reçoit."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
from discord.ui import Button

import visuels
from ui_v2 import LayoutView, Palette, body, container, subtitle, title
from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


def _classes(conf: dict, affiches: list):
    async def cfg(_gid):
        return conf

    async def db_set(_gid, k, v):
        conf[k] = v

    async def afficher(vue, _i, _edit):
        affiches.append(vue)
    ns = {"discord": discord, "Button": Button, "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels,
          "v2_title": title, "v2_body": body, "v2_subtitle": subtitle, "v2_container": container,
          "cfg": cfg, "db_set": db_set, "_afficher_panneau": afficher, "PanelEditViewV2": object, "AddQModal": object}
    for n in ARBRE.body:
        if isinstance(n, ast.ClassDef) and n.name in ("PanelBlacklistView", "PanelQsView"):
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def _membre(uid, admin=False, bot=False):
    return Obj(id=uid, bot=bot, mention=f"<@{uid}>", display_name=f"Membre{uid}",
               guild_permissions=Obj(administrator=admin))


def _textes(vue):
    def tout(c):
        for k in ("content", "label", "placeholder"):
            if c.get(k):
                yield c[k]
        for x in c.get("components", []) or []:
            yield from tout(x)
    return " ".join(t for c in vue.to_components() for t in tout(c))


def test_T1_liste_noire_en_v2_avec_pages_ajout_et_retrait():
    conf = {"ticket_panels": {"p1": {"name": "Support", "blacklist": list(range(100, 112))}}}
    affiches = []
    ns = _classes(conf, affiches)
    g = Obj(id=1, owner_id=1, get_member=lambda uid: None)
    vue = ns["PanelBlacklistView"](Obj(id=5), g, "p1")
    asyncio.run(vue.render_to(object()))
    texte = _textes(affiches[-1])
    assert "Liste noire (12)" in texte and "Page 1/2" in texte
    assert "Ajouter des membres…" in texte and "Retirer de la liste…" in texte and "Préc." in texte
    assert all(c.get("type") != 1 or c.get("components") for c in affiches[-1].to_components())

    async def suivre(_m, **k):
        pass
    i = Obj(followup=Obj(send=suivre))
    sel = Obj(values=[_membre(7), _membre(8, admin=True), _membre(9, bot=True)])
    asyncio.run(vue._cb_ajout(i, sel))
    assert conf["ticket_panels"]["p1"]["blacklist"][-1] == 7 and 8 not in conf["ticket_panels"]["p1"]["blacklist"]
    asyncio.run(vue._cb_retrait(i, Obj(values=["100", "101"])))
    assert 100 not in conf["ticket_panels"]["p1"]["blacklist"] and len(conf["ticket_panels"]["p1"]["blacklist"]) == 11
    asyncio.run(vue.render_to(object(), confirmer=True))
    assert "Oui, retirer les 11" in _textes(affiches[-1])


def test_T2_questions_en_v2_cinq_au_plus():
    qs = [{"title": f"Q{n}", "question": "?"} for n in range(5)]
    conf = {"ticket_panels": {"p1": {"questions": qs}}}
    affiches = []
    ns = _classes(conf, affiches)
    asyncio.run(ns["PanelQsView"](Obj(id=5), Obj(id=1), "p1").render_to(object()))
    composants = affiches[-1].to_components()
    boutons = [b for c in composants for r in c["components"] if r.get("type") == 1 for b in r["components"]]
    assert [b["label"] for b in boutons] == ["Ajouter", "Tout supprimer", "Retour"]
    assert boutons[0].get("disabled") is True, "5 questions : on n'en ajoute plus"


def test_T3_plus_aucun_sous_menu_des_tickets_en_embed():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    for nom in ("_cb_cat", "_cb_qs", "_cb_blacklist"):
        corps = next(ast.unparse(n) for n in ast.walk(ARBRE)
                     if isinstance(n, ast.AsyncFunctionDef) and n.name == nom and "PanelEditViewV2" in ast.unparse(n)
                     or isinstance(n, ast.AsyncFunctionDef) and n.name == nom and "self.pid" in ast.unparse(n))
        assert "embed=" not in corps, nom
    assert "PanelCatPaginatedView" not in src and "BlacklistAddModal" not in src


def test_T4_un_clic_sur_ouvrir_un_ticket_ne_repond_qu_une_fois():
    """Le gabarit dynamique ET une vue enregistrée captaient le même bouton : discord.py exécute les
    deux, le second échouait et affichait une fausse erreur."""
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "class TicketCreateButton" not in src and "TicketCreateView(" not in src
    assert 'custom_id=f"ticket_create_{pid}"' in src


def test_T5_retirer_une_seule_immunite_en_v2():
    """« Erreur 400 » en retirant UNE immunité (menu V2 édité avec un embed) ; seul « Tout effacer »
    marchait, et le retrait ne vidait pas le cache (30 s d'immunité en plus)."""
    affiches = []

    async def afficher(vue, _i, _edit):
        affiches.append(vue)
    ns = {"discord": discord, "Button": Button, "LayoutView": LayoutView, "Palette": Palette, "visuels": visuels,
          "v2_title": title, "v2_container": container, "_afficher_panneau": afficher}
    for n in ARBRE.body:
        if isinstance(n, ast.ClassDef) and n.name == "PaginatedImmuneRemoveView":
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
            corps = ast.unparse(n)
    g = Obj(get_role=lambda x: None)
    asyncio.run(ns["PaginatedImmuneRemoveView"](Obj(id=5), g, "role", list(range(30))).render_to(object()))
    texte = _textes(affiches[-1])
    assert "Retirer un rôle immunisé (30)" in texte and "1/2" in texte and "Retour" in texte
    assert "_invalidate_immunity(self.g.id)" in corps
