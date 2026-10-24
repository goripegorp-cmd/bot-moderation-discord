"""24/10/2026, revue complète : aucun texte littéral d'interface ne dépasse les limites de Discord (un bouton, un
menu, un formulaire ou un titre trop long fait échouer l'envoi — l'interface ne s'affiche pas)."""
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def test_LIM1_aucune_interface_ne_depasse_les_limites_de_discord():
    r = subprocess.run([sys.executable, str(RACINE / "outils" / "verif_limites_ui.py")], capture_output=True,
                       text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0 and "0 dépassement" in r.stdout, r.stdout + r.stderr
