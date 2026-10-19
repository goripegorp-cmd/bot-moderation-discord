"""19/10/2026 (revue complète) : « ça expulse des gens qui n'ont rien fait ». Chaque phrase normale de
joueur qu'un filtre automatique punissait devient un test : elle ne doit plus jamais l'être. Les vrais
cas, eux, doivent toujours être pris."""
from __future__ import annotations

import ast
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


def _extraire(*noms, ns=None):
    ns = dict(ns or {}, re=re)
    voulus = set(noms)
    for n in ARBRE.body:
        nom = n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else (
            getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in voulus:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def _filtres_liens():
    ns = _extraire("DOMAINES_OFFICIELS", "_URL_COMPLETE", "_hote", "domaine_officiel", "sans_liens_officiels",
                   "PHISHING_DOMAINS", "PHISHING_URL_PATTERNS", "advanced_phishing_check", "_SCAM_SANS_LIEN",
                   "SCAM_KEYWORDS", "_FREE_HOST_DOMAINS", "_FREE_HOST_SCAM_RE", "advanced_scam_check",
                   "COMPROMISED_PATTERNS", ns={"_normalize_for_scan": lambda t: t})
    ns["SCAM_PATTERNS"] = [re.compile(p, re.IGNORECASE) for p in ns["COMPROMISED_PATTERNS"]]
    return _extraire("check_phishing", "check_scam", ns=ns)


def test_F1_liens_officiels_et_phrases_de_jeu_jamais_pris_pour_du_phishing():
    ns = _filtres_liens()
    innocents = [
        "regarde https://cdn.discordapp.com/attachments/1/2/image.png",
        "https://media.discordapp.net/attachments/1/2/clip.gif",
        "https://discordapp.com/channels/1/2/3",
        "voilà ton cadeau https://discord.gift/AbCdEf123",
        "https://steamcommunity.com/tradeoffer/new/?partner=123&token=abc",
        "https://support.discord.com/hc/fr/articles/How-to-Verify-Age-Group",
        "gg félicitations tu as gagné la partie !",
        "congratulations you won the game gg",
        "OMG regardez https://www.roblox.com/games/123/jeu",
        "venez tester mon game https://www.roblox.com/games/456",
        "check this https://youtu.be/abc",
        "wonderful https://www.youtube.com/watch?v=x",
        "viens vite tester mon jeu",
    ]
    for texte in innocents:
        assert not ns["check_phishing"](texte)[0], texte
        assert not ns["check_scam"](texte)[0], texte


def test_F2_les_vrais_liens_piege_sont_toujours_pris():
    ns = _filtres_liens()
    assert ns["check_phishing"]("free nitro https://discord-nitro.gift/claim")[0]
    assert ns["check_phishing"]("claim ton cadeau https://disc0rd-gift.ru/nitro")[0]
    assert ns["check_phishing"]("@everyone free nitro https://discordnitro.com/x")[0]
    assert ns["check_scam"]("free nitro gift https://nitro-drop.xyz/claim now")[0]
    assert ns["check_scam"]("send your seed phrase and wallet address to receive double your crypto")[0]
