"""28/10/2026 — « de belles annonces, pas des trucs moches avec des textes pourris » : les modèles d'annonce sont écrits
et mis en forme, dans les limites du serveur, et la barre de mise en forme sert aussi sur le site de l'équipage."""
from __future__ import annotations

from pathlib import Path

import evenements as EV

RACINE = Path(__file__).resolve().parent.parent


def test_A1_les_modeles_d_annonce_sont_ecrits_et_dans_les_limites():
    ecrits = [m for m in EV.MODELES if m["type"] == "annonce" and m["valeurs"].get("texte")]
    assert len(ecrits) >= 6, "recrutement, nouveautés, félicitations, code, bienvenue, pause"
    for m in ecrits:
        v = m["valeurs"]
        assert v["titre"] and len(v["titre"]) <= EV.TITRE_MAX, m["cle"]
        assert len(v["texte"]) <= EV.TEXTE_MAX["annonce"], m["cle"]
        assert v["texte"].lstrip().startswith("## "), "un vrai titre en tête : " + m["cle"]
        assert "\n-# " in v["texte"], "la ligne anglaise : " + m["cle"]
        assert v["mention"] in EV.MENTIONS, m["cle"]
    assert len({m["cle"] for m in EV.MODELES}) == len(EV.MODELES), "des clés uniques"


def test_A2_la_barre_de_mise_en_forme_sur_le_site_de_l_equipage():
    assert "export function barreMarkdown(" in (RACINE / "site" / "annonces.js").read_text(encoding="utf-8")
    assert "m.barreMarkdown(texte," in (RACINE / "site" / "equipage_publication.js").read_text(encoding="utf-8")
