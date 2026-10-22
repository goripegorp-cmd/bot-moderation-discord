"""22/10/2026 : « nous, on a toutes les informations des salons trade et entraide au propre » — le site
(onglet Salons) reçoit chaque demande (qui, quoi, qui est venu, qui a certifié, avec qui), les
équipages et les annonces avec leurs « ✅ Vu »."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import annonces as A
import entraide as E
import equipages as Q
import tableau as T
from conftest_discord import Obj, base
from faux_serveur import Forum, Monde, Texte, interaction, run

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)

    async def rien(*_a, **_k):
        return ""

    async def non(*_a, **_k):
        return False
    commun = dict(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=rien, controle=rien, est_staff=non,
                  journal=rien, log=lambda *a: None)
    E.setup(**commun)
    Q.setup(**commun)
    E._creations.clear()
    monkeypatch.setattr(A, "MAJ_VUES_S", 0)
    A.setup(get_db=get_db, cfg=cfg, db_set=db_set, est_tete=lambda g, m: True, journal=rien, log=lambda *a: None)
    for module in (E, Q, A):
        asyncio.run(module.init_db())
    return Obj(conf=conf)


def test_S1_le_site_a_l_entraide_les_equipages_et_les_annonces(env):
    g = Monde()
    rell = g._salon(Forum, "🌊rell-seas", {"category": g.commu})
    posts = {cle: run(rell.create_thread(name=cle)).thread.id for cle in ("entraide", "trade", "crews")}
    env.conf.update(aide_salon=g.nom("❓aide").id, rs_salons={"entraide": posts["entraide"], "trade": posts["trade"]},
                    rs_ouvertures={"entraide": posts["entraide"], "trade": posts["trade"]},
                    rs_panneaux={"entraide": posts["entraide"], "trade": posts["trade"]},
                    eq_forum=posts["crews"], eq_panneau=posts["crews"], eq_ouverture=posts["crews"])
    run(E.installer(g, creer_salons=False))
    vendeur, acheteur = g.membre(7), g.membre(8)
    mm = g.membre(11, g.get_role(env.conf["rs_roles"]["trade"]))
    run(E.publier(interaction(g, vendeur), E.ZONES["trade"], {"donne": "Dragon", "cherche": "Dough", "pseudo": "K",
                                                               "details": ""}))
    run(E.rejoindre(interaction(g, acheteur), 1))
    run(E.certifier(g, 1, mm, [], partenaire=8))
    E._creations.clear()
    run(E.publier(interaction(g, g.membre(9)), E.ZONES["boss"], {"titre": "Akuma", "pseudo": "P", "niveau": "",
                                                                    "joueurs": "", "details": ""}))
    run(Q.publier(interaction(g, g.membre(10)), "marine", {"nom": "La Flotte", "pseudo": "Amiral", "membres": "4",
                                                            "niveau": "", "presentation": "Ordre et honneur."}))
    salon = g._salon(Texte, "📜annonce", {"category": g.categorie("· Information")})
    run(A.publier(g, g.membre(1), A.Brouillon(salon_id=salon.id, titre="Mise à jour", texte="Nouvelles îles", fil=False)))
    for uid in (7, 8):
        run(A.marquer_vu(interaction(g, g.membre(uid)), 1))
    qui = T._Personnes(g)
    d = run(T._entraide(g, qui))
    assert d["stats"] == {"ouvertes": 1, "total": 2, "certifiees": 1}
    trade = next(x for x in d["liste"] if x["id"] == 1)
    assert (trade["type"], trade["auteur"], trade["aidants"], trade["certifie_par"], trade["partenaire"]) == \
        ("Trade", "7", ["8"], "11", "8")
    assert trade["champs"][:2] == [["Je donne · I give", "Dragon"], ["Je cherche · I want", "Dough"]]
    assert trade["lien"] == f"https://discord.com/channels/1/{posts['trade']}/{run(E.charger(1))['fil_id']}"
    q = run(T._equipages(g, qui))
    flotte = q["liste"][0]
    assert (flotte["nom"], flotte["faction"], flotte["capitaine"], flotte["recrute"]) == ("La Flotte", "Marine", "10", True)
    assert flotte["champs"]["Capitaine · Captain"] == "Amiral" and flotte["presentation"] == "Ordre et honneur."
    assert flotte["lien"].startswith(f"https://discord.com/channels/1/{posts['crews']}/")
    a = run(T._annonces(g, qui))
    assert (a["liste"][0]["titre"], a["liste"][0]["vues"], a["liste"][0]["vus"]) == ("Mise à jour", 2, ["7", "8"])
    assert {"7", "8", "10", "11"} <= set(qui), "chaque personne citée a sa fiche (nom, avatar)"


def test_S2_la_page_affiche_ces_sections():
    page = (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    for morceau in ('sectionTete("Entraide et trade"', 'sectionTete("Équipages"', 'sectionTete("Annonces"',
                    "function carteDemande(x)", "function carteEquipage(x)", "function carteAnnonce(x)",
                    'entr: "ouvertes"', '"Entraide et trade en cours"'):
        assert morceau in page, morceau
    src = (RACINE / "tableau.py").read_text(encoding="utf-8")
    assert '("entraide", lambda: _entraide(g, qui))' in src and '("annonces", lambda: _annonces(g, qui))' in src
