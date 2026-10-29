"""29/10/2026 : le wiki public de RELL Seas (`/wiki`) — le vérifié seulement, FR · EN, preuves, crédits."""
import json
import re
from pathlib import Path

import health_server
import site_wiki as W

RACINE = Path(__file__).resolve().parent.parent


def test_WIKI_seulement_le_verifie_avec_un_texte_releu_en_deux_langues():
    d = W.contenu()
    cat = json.loads((RACINE / "donnees_jeu" / "rell_catalogue.json").read_text(encoding="utf-8"))
    statut = {f"{e['type']}.{e['cle']}": e["statut"] for e in cat["elements"]}
    assert len(d["entrees"]) >= 100
    for e in d["entrees"]:
        assert e["fr"] and e["en"], e["cle"]
        assert statut.get(e["cle"], "confirme") == "confirme", e["cle"]
        #  aucune supposition dans un texte public
        assert not re.search(r"(?i)à vérifier|supposée?|non détaillé|to be confirmed|rumou?r|lorem|placeholder",
                             e["fr"] + " " + e["en"]), e["cle"]


def test_WIKI_tout_le_confirme_du_catalogue_a_son_texte():
    cat = json.loads((RACINE / "donnees_jeu" / "rell_catalogue.json").read_text(encoding="utf-8"))
    pub = json.loads((RACINE / "donnees_jeu" / "wiki_public.json").read_text(encoding="utf-8"))
    manque = [f"{e['type']}.{e['cle']}" for e in cat["elements"]
              if e["statut"] == "confirme" and e.get("actif", True) and f"{e['type']}.{e['cle']}" not in pub["textes"]]
    assert manque == []


def test_WIKI_hors_catalogue_seulement_avec_une_preuve_officielle():
    for e in W.contenu()["entrees"]:
        if "." in e["cle"] and e["type"] in ("boss", "lieu", "systeme"):
            assert e["preuves"] and e["preuves"][0]["url"].startswith("https://youtu.be/"), e["cle"]


def test_WIKI_credits_fondateur_direction_et_discord():
    class R:
        def __init__(self, i, membres): self.id, self.members, self.managed, self.name = i, membres, False, "Direction"
        def is_default(self): return False

    class M:
        def __init__(self, i, nom, bot=False): self.id, self.display_name, self.bot = i, nom, bot

    proprio = M(1, "GoRipe")
    dirn = R(next(iter(W.acces_direction.DIRECTION_ROLE_IDS)), [proprio, M(2, "Barbe"), M(3, "Robot", True)])
    g = type("G", (), {"owner": proprio, "owner_id": 1, "name": "GoRP SEA", "roles": [dirn]})()
    c = W.credits(g)
    assert c["fondateur"] == "GoRipe" and c["direction"] == ["Barbe"] and c["discord"].startswith("https://discord.gg/")


def test_WIKI_adresses_publiques_en_lecture():
    routes = {(r.method, r.resource.canonical) for r in health_server.construire_app().router.routes()}
    assert {("GET", "/wiki"), ("GET", "/wiki/donnees"), ("GET", "/wiki/banniere.png")} <= routes
    assert not any(m == "POST" and p.startswith("/wiki") for m, p in routes)


def test_WIKI_page_et_freins():
    html = (RACINE / "site" / "wiki.html").read_text(encoding="utf-8")
    js = (RACINE / "site" / "wiki.js").read_text(encoding="utf-8")
    assert "noindex" in html and "{{OG_TITRE}}" in html and "wiki.js" in html
    assert '"contextmenu"' in js and "f12" in js and "backgroundImage" in js
    assert "RELL Games" in js and "© ${c}" in js       # le jeu à RELL Games, le wiki au clan


def test_WIKI_vivant_fonds_officiels_et_banniere():
    d = W.contenu()
    assert len(d["heros"]) >= 3 and all(h["fond"].startswith("s/wiki/fonds/") for h in d["heros"])
    assert all((RACINE / "site" / "wiki" / "fonds" / (h["fond"].rsplit("/", 1)[-1] + "_p.webp")).exists() for h in d["heros"])
    assert any(t["fond"] for t in d["types"]) and any(v["fond"] for v in d["videos"])
    png = W.dessiner_banniere(dict(d, credits={"clan": "GoRP SEA", "discord": "https://discord.gg/HM9JpXrZqJ"}))
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 50_000


def test_WIKI_fichiers_publics_seulement_les_siens():
    import tableau
    assert tableau.lecteurs_statique("wiki.js") is None and tableau.lecteurs_statique("wiki/fonds/x.webp") is None
    assert tableau.lecteurs_statique("app.js") is not None        # le code de la Capitainerie reste à la tête
