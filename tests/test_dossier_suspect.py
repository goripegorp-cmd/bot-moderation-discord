"""19/10/2026 (audit) : les boutons du dossier « compte suspect » mouraient à chaque redéploiement —
la vue n'était jamais réenregistrée et gardait le membre en mémoire. Ils portent maintenant le membre
dans leur identifiant et sont captés au démarrage."""
from __future__ import annotations

import ast
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _gabarit(nom):
    for n in ARBRE.body:
        if isinstance(n, ast.ClassDef) and n.name == nom:
            for k in n.keywords:
                if k.arg == "template":
                    return re.compile(k.value.value)
    raise AssertionError(nom)


def test_D1_le_bouton_porte_le_membre_et_survit_au_redemarrage():
    g = _gabarit("DossierCompromisBouton")
    m = g.fullmatch("cad:ban:781205382923288593")
    assert m and m["act"] == "ban" and m["uid"] == "781205382923288593"
    assert not g.fullmatch("cad_ban"), "les anciens identifiants ont leur propre capteur"
    assert _gabarit("DossierCompromisAncien").fullmatch("cad_unfreeze")
    assert "bot.add_dynamic_items(DossierCompromisBouton, DossierCompromisAncien)" in SRC


def test_D2_la_vue_du_message_n_a_pas_d_action_propre():
    """Sinon discord.py exécute le bouton du message ET le capteur : chaque clic agirait deux fois."""
    corps = next(ast.unparse(n) for n in ARBRE.body if isinstance(n, ast.FunctionDef) and n.name == "_dossier_vue")
    assert "Button(" in corps and ".callback =" not in corps and "DossierCompromisBouton(" not in corps
    assert "custom_id=f'cad:{act}:{uid}'" in corps


def test_D3_plus_de_gel_economique_fantome():
    assert "freeze_account" not in SRC and "économie dégelée" not in SRC
