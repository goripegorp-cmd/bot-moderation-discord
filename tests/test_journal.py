"""Le journal Railway : les vraies erreurs, chacune une fois (14/10/2026).

« Il m'affiche trop de logs […] ça affiche juste les erreurs, ou les chargements
qui ont échoué, mais les vraies erreurs. Pareil, les diagnostics […] qui ne
crée pas des milliers de mêmes messages tout le temps. »
"""
from __future__ import annotations

import ast
import builtins
import glob
import io
import logging
import sys
from pathlib import Path

import pytest

import journal

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def neuf():
    journal._vus.clear()
    journal._minute[:] = [0.0, 0, 0]
    yield
    journal._vus.clear()
    journal._minute[:] = [0.0, 0, 0]


#  Des lignes RÉELLES des journaux Railway du 13-14/10 (et du dépôt).
BRUIT = [
    "[veille_roblox_task]   accessoires : 963 lu(s) (+238 hors vente) · 0 candidat(s) · "
    "0 hors fenêtre (6 h) · 0 déjà sorti(s) · 0 mise(s) en file · 0 échec(s) d'envoi",
    "[veille_roblox_task]   éclaireur d'actualités : 22189 passage(s) à 30 s · 9 billet(s) "
    "vu(s) en premier · 9 publié(s) sur l'instant · 8 erreur(s) · dernier passage il y a 10 s",
    "[eclaireur] 4080 passage(s) · rien de nouveau · seau des identifiants 0/12",
    "⚠️ [gdpr_retention] 6 ligne(s) purgée(s) par rétention : {'raid_join_log': 6, "
    "'alt_detection_log': 0, 'error_log': 0}",
    "[DIAG] 2026-10-14T11:17:40Z WARN  social/youtube_feed :: @miranzaugc: aucun salon cible",
    "[DIAG] 2026-10-14T11:17:40Z EVENT boot/diagnostics :: actif (verbose=OFF)",
    "[insult_filter] lexique chargé : {'selfharm': 40, 'tier3': 574}",
    "🆔 Instance abc — si vous voyez DEUX identifiants différents…",
    "[STOCKAGE] base 180 Mo (+ journal 4 Mo) · copies .bak 3 = 540 Mo",
]
ALARMES = [
    "[veille_roblox_task] 🚨 UNE AUTRE INSTANCE DU BOT TOURNE EN MÊME TEMPS : x",
    "[STALL] ⚠️ boucle asyncio bloquée depuis 12.3s — stack du thread PRINCIPAL",
    "[eclaireur] ⚠️ AVEUGLE depuis 31 min (12 passage(s) refusé(s) d'affilée, HTTP 429)",
    "[backup_lite] échec : disk I/O error",
    "[DIAG] 2026-10-14T11:17:40Z ERROR social/youtube_post :: @x | err=ClientError: 403",
    "[view on_error] rblx_x : TypeError: boom",
    "[activity_vip] Impossible de remonter VIP au-dessus de X : mon rôle est trop bas",
    "❌ ERREUR: BOT_TOKEN non défini dans le fichier .env !",
    "[events_role_backfill] 12 : ÉCHEC (40 membres, 0 ajout)",
    "[VIEW ERROR] x -> y : boom",
]


@pytest.mark.parametrize("ligne", BRUIT)
def test_J1_le_bruit_se_tait(ligne):
    assert not journal.a_garder(ligne, en_exception=False), ligne


@pytest.mark.parametrize("ligne", ALARMES)
def test_J2_les_vraies_alarmes_passent(ligne):
    assert journal.a_garder(ligne, en_exception=False), ligne


def test_J3_tout_print_fait_pendant_une_exception_passe():
    assert journal.a_garder("[social_zones create voice] 403 Forbidden", True)


def test_J4_un_meme_message_une_fois_par_6_h_puis_il_dit_combien():
    assert journal.filtrer("[x] 403 sur #12", 0.0) == "[x] 403 sur #12"
    assert journal.filtrer("[x] 403 sur #57", 100.0) is None, "chiffres ignorés"
    assert journal.filtrer("[x] 403 sur #57", 200.0) is None
    revenu = journal.filtrer("[x] 403 sur #9", journal.FENETRE_S + 1)
    assert revenu == "[x] 403 sur #9  (répété 2 fois depuis le précédent)"
    assert journal.filtrer("[x] autre chose", 300.0) == "[x] autre chose"


def test_J5_jamais_plus_de_30_lignes_par_minute():
    #  40 messages VRAIMENT différents (les chiffres, eux, sont ignorés).
    sorties = [journal.filtrer(f"[x] erreur {chr(97 + k % 26)}{chr(97 + k // 26)}", 1.0)
               for k in range(40)]
    assert sum(s is not None for s in sorties) == journal.PLAFOND_MINUTE
    suivante = journal.filtrer("[y] nouvelle", 61.0)
    assert suivante.startswith("[journal] 10 ligne(s) tue(s) la minute précédente")


def test_J6_imprimer_decide_par_le_contexte(capsys):
    journal.imprimer("[veille] bilan de routine")
    try:
        raise ValueError("x")
    except ValueError:
        journal.imprimer("[module fonction] boom")
    fichier = io.StringIO()
    journal.imprimer("vers un fichier : jamais filtré", file=fichier)
    assert capsys.readouterr().out == "[module fonction] boom\n"
    assert fichier.getvalue() == "vers un fichier : jamais filtré\n"


def test_J7_une_trace_d_erreur_sort_en_un_bloc_une_fois(capsys):
    for _ in range(3):
        try:
            {}["absent"]
        except KeyError as ex:
            journal._print_exception(type(ex), ex, ex.__traceback__, file=sys.stderr)
    try:
        int("x")
    except ValueError as ex:
        journal._print_exception(type(ex), ex, ex.__traceback__, file=sys.stderr)
    err = capsys.readouterr().err
    #  Trois fois la même trace → une ; une AUTRE trace → entière, en-tête compris
    #  (ligne par ligne, son « Traceback » aurait été pris pour un doublon).
    assert err.count("Traceback (most recent call last):") == 2
    assert "KeyError: 'absent'" in err and "ValueError: invalid literal" in err


def test_J8_logging_meme_deduplication():
    f = journal.FiltreLogging()

    def rec(msg, exc=None):
        return logging.LogRecord("discord.gateway", logging.WARNING, "x", 1, msg,
                                 None, exc)
    assert f.filter(rec("Can't keep up, 12s behind")) is True
    assert f.filter(rec("Can't keep up, 30s behind")) is False
    try:
        raise OSError("a")
    except OSError:
        e1 = sys.exc_info()
    try:
        raise KeyError("b")
    except KeyError:
        e2 = sys.exc_info()
    assert f.filter(rec("Ignoring exception", e1)) is True
    assert f.filter(rec("Ignoring exception", e2)) is True, "deux exceptions = deux messages"


def test_J9_installe_seulement_en_production(monkeypatch):
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "class _QuietStdout" not in src and "_QuietStdout(_sys.stdout)" not in src
    assert 'if __name__ == "__main__":\n    _journal.installer()' in src.replace("\r\n", "\n")
    assert "log_handler=_gestionnaire" in src and "root_logger=True" in src
    monkeypatch.setenv("VERBOSE_LOGS", "1")
    avant = builtins.print
    assert journal.installer() is False and builtins.print is avant


def _prints_hors_except():
    """(fichier, ligne, texte littéral) de chaque print écrit HORS d'un `except`."""
    out = []
    for p in glob.glob(str(RACINE / "*.py")):
        arbre = ast.parse(Path(p).read_text(encoding="utf-8"))

        def visiter(n, dans_except):
            for e in ast.iter_child_nodes(n):
                if isinstance(e, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visiter(e, False)
                elif isinstance(e, ast.ExceptHandler):
                    visiter(e, True)
                else:
                    if (isinstance(e, ast.Call) and isinstance(e.func, ast.Name)
                            and e.func.id == "print" and not dans_except):
                        t = "".join(s.value for a in e.args for s in ast.walk(a)
                                    if isinstance(s, ast.Constant) and isinstance(s.value, str))
                        out.append((Path(p).name, e.lineno, t))
                    visiter(e, dans_except)
        visiter(arbre, False)
    return out


def test_J10_les_alertes_hors_except_du_depot_portent_leur_marqueur():
    """⚠️ GARDE : ces messages-là disent une vraie panne ; sans marqueur, le
    journal les tairait. ([STALL] se construit dans une liste : vu en J2.)"""
    vitales = ("UNE AUTRE INSTANCE", "AVEUGLE", "RESSUSCITÉ",
               "dérive de schéma", "salon d'alerte introuvable", "permissions manquantes dans #",
               "aiohttp non installé", "[nsfw_scan] désactivé", "Aucun volume persistant",
               "VACUUM échoué", "[VIEW ERROR]", "[MODAL ERROR]", "[APP CMD ERROR]")
    trouvees = set()
    for f, ligne, t in _prints_hors_except():
        for v in vitales:
            if v in t:
                trouvees.add(v)
                assert journal.ALARME.search(t), f"{f}:{ligne} {t[:80]!r}"
    assert trouvees == set(vitales), set(vitales) - trouvees
