"""Le chien de garde du gel se tait quand le bot s'arrête (27/10/2026).

Journal Railway du 27/10, 10 h 29 (mise en ligne) : « [STALL] ⚠️ boucle asyncio bloquée depuis 3.5s — stack du thread
PRINCIPAL … threading._shutdown » puis « Stopping Container ». La boucle s'était arrêtée VOLONTAIREMENT (SIGTERM) et
Python attendait ses derniers fils : le chien de garde, qui ne savait pas que le bot s'arrêtait, criait au gel — une
fausse alarme à chaque mise en ligne. Désormais : battement annulé → drapeau « arret » → le chien de garde se termine.
"""
from __future__ import annotations

import ast
import asyncio
import io
import os
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


def _espace(battement: dict) -> dict:
    """Les deux fonctions de bot.py, telles quelles, dans un espace qui a ce qu'elles lisent."""
    ns = {"asyncio": asyncio, "_time_mod": time, "_threading_mod": threading, "_sys": sys, "os": os,
          "_LOOP_BEAT": battement, "_STALL_THRESHOLD": 3.0, "_STALL_COOLDOWN": 20.0}
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ("_loop_heartbeat", "_stall_watchdog"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "bot.py", "exec"), ns)
    return ns


def test_A1_battement_annule_pose_le_drapeau_d_arret():
    battement = {"t": 0.0}
    ns = _espace(battement)

    async def scenario():
        tache = asyncio.create_task(ns["_loop_heartbeat"]())
        await asyncio.sleep(0.25)
        assert battement["t"] > 0, "le battement doit battre tant que la boucle tourne"
        tache.cancel()
        try:
            await tache
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert battement.get("arret") is True


def test_A2_chien_de_garde_se_tait_et_se_termine_a_l_arret(monkeypatch):
    # Battement arrêté depuis 10 s (bien au-delà du seuil de 3 s) MAIS bot en train de s'arrêter :
    # aucune alarme, et le fil se termine au lieu de tourner jusqu'à la fin du processus.
    battement = {"t": time.monotonic() - 10.0, "arret": True}
    ns = _espace(battement)
    sortie = io.StringIO()
    monkeypatch.setattr(sys, "stderr", sortie)
    fil = threading.Thread(target=ns["_stall_watchdog"], daemon=True)
    fil.start()
    fil.join(3.0)
    assert not fil.is_alive(), "le chien de garde doit se terminer quand le bot s'arrête"
    assert "[STALL]" not in sortie.getvalue()


def test_A3_le_releve_des_fils_suit_bot_run():
    # Après bot.run, le relevé nomme les fils non « daemon » qui retardent la sortie (message stable + détail).
    source = (RACINE / "bot.py").read_text(encoding="utf-8")
    apres = source.split("bot.run(TOKEN", 1)[1]
    assert '"[BOOT] arrêt : des fils retardent la sortie"' in apres
    assert "not t.daemon" in apres
