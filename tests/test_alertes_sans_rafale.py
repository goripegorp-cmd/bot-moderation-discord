"""28/10/2026 — le fondateur : « les comptes doubles… ça crée des gros warnings dans un salon et ça spamme tout. Ça fait
des gros messages partout. S'assurer que tout soit bien protégé là-dessus. » Le journal du site garde chaque détection ;
les salons reçoivent peu, court, jamais en rafale."""
from __future__ import annotations

import ast
import re
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _fonctions(*noms):
    ns = {"time": time, "re": re}
    for n in ARBRE.body:
        nom = n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else (
            getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else
            getattr(n.target, "id", None) if isinstance(n, ast.AnnAssign) else None)
        if nom in noms:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def test_S1_comptes_doubles_une_ligne_par_compte_principal_et_par_jour():
    ns = _fonctions("_ALT_ALERTES", "_alt_alerte_permise")
    f = ns["_alt_alerte_permise"]
    assert f(1, 100, t=0) and not f(1, 100, t=60), "le même compte principal : une fois"
    assert f(1, 100, t=86401), "le lendemain : de nouveau"
    ns["_ALT_ALERTES"].clear()
    assert [f(2, u, t=10) for u in range(5)] == [True, True, True, False, False], "3 par serveur en 10 minutes"
    assert f(2, 99, t=700), "10 minutes plus tard : de nouveau"


def test_S2_les_cartes_de_protection_sans_rafale():
    ns = _fonctions("_CARTES_PROTECTION", "_carte_protection_permise")
    f = ns["_carte_protection_permise"]
    assert f(1, "anti_spam", 7, t=0) and not f(1, "anti_spam", 7, t=100), "même protection, même membre : 10 minutes"
    assert f(1, "anti_link", 7, t=100), "une autre protection passe"
    ns["_CARTES_PROTECTION"].clear()
    assert sum(f(3, "anti_raid", u, t=5) for u in range(20)) == 6, "un raid : 6 cartes au plus en 5 minutes"


def test_S3_profil_a_surveiller_au_journal_jamais_en_alerte():
    src = ast.unparse(next(n for n in ARBRE.body if getattr(n, "name", "") == "_flag_dangerous_profile"))
    assert "SEC_ESCALATION" not in src and "'sec.profil'" in src
    alt = SRC[SRC.index("if c.get('anti_alt'):"):SRC.index("# Appliquer l'action automatique si activée")]
    assert "discord.Embed(" not in alt and "_alt_alerte_permise(m.guild.id, main_id)" in alt
    assert "logs_sur_site_v1" in alt, "journaux sur le site : rien dans le salon"
