"""22/10/2026 (nuit) : « Les gens peuvent publier leur équipage, que ce soit la marine ou les
pirateries… un vrai système ultra complet », puis « deux fils seulement… plutôt que des milliers de
fils ». Le post ⚓ Crews du forum 🌊rell-seas : une carte par équipage, publiée dans sa langue ; le
capitaine la modifie, ouvre ou ferme le recrutement, la retire ; rejoindre le prévient sous sa
carte. Sur un faux serveur."""
from __future__ import annotations

import ast
import asyncio
import re
import time
from pathlib import Path

import discord
import pytest

import equipages as Q
from conftest_discord import Obj, base
from faux_serveur import Forum, Monde, compter, ids, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
VALEURS = {"nom": "Les Requins Rouges", "pseudo": "Kolax_RS", "membres": "6 / 10", "niveau": "500",
           "presentation": "On chasse les boss le soir."}


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal, staff, langues = [], set(), {}

    async def texte_refuse(_g, t):
        return "Ton texte contient une insulte." if "insulte" in t else ""

    async def controle(_m, _c):
        return ""

    async def est_staff(_g, m):
        return m.id in staff

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))

    async def langue(i):
        return langues.get(i.user.id, "fr")
    Q._verrous.clear()
    Q._demandes.clear()
    Q.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse, controle=controle,
            est_staff=est_staff, journal=noter, langue=langue, log=lambda *a: None)
    asyncio.run(Q.init_db())
    return Obj(conf=conf, journal=journal, staff=staff, langues=langues)


def installe(env):
    """Comme les zones le laissent : le post ⚓ Crews (verrouillé) du forum 🌊rell-seas ; son message
    d'ouverture porte « Pirates » et « Marine »."""
    g = Monde()
    rell = g._salon(Forum, "🌊rell-seas", {"category": g.commu})
    crews = run(rell.create_thread(name="⚓ Crews · Équipages")).thread
    crews.locked = True
    env.conf.update(eq_forum=crews.id, eq_panneau=crews.id, eq_ouverture=crews.id)
    assert run(Q.installer(g, creer=False)) == [], "les zones donnent le post : rien à créer"
    return g, crews


def publier(g, membre, faction="pirate", valeurs=None, langue="fr"):
    i = interaction(g, membre)
    run(Q.publier(i, faction, dict(valeurs or VALEURS), langue))
    return i


def _vue_de(i):
    for _contenu, kw in reversed(i.suivis):
        if isinstance(kw, dict) and kw.get("view") is not None:
            return kw["view"]
    return i.response.messages[-1][1]["view"]


def test_Q1_deux_factions_un_formulaire_court_dans_les_deux_langues():
    assert list(Q.FACTIONS) == ["pirate", "marine"] and Q.NOM_FORUM == "⚓crews"
    assert all(len(n) <= 20 for n, _e in Q.TAGS), "Discord refuse une étiquette de plus de 20 caractères"
    assert len(Q.CHAMPS) <= 5 and [c.cle for c in Q.CHAMPS if c.requis] == ["nom", "pseudo", "presentation"]
    for faction in Q.FACTIONS:
        for langue in ("fr", "en"):
            f = Q.Formulaire(faction, langue)
            assert len(f.title) <= 45 and len(f.children) == len(Q.CHAMPS)
            assert all(len(lab.text) <= 45 for lab in f.children)
    assert Q.Formulaire("marine", "en").title == "⚓ Marine crew" and Q.Formulaire("pirate").title == \
        "🏴‍☠️ Équipage Pirates"
    assert all(set(v) == {"fr", "en"} for v in Q.TEXTES.values()), "chaque texte existe dans les deux langues"
    for item, gabarit in ((Q.BoutonPublier("marine"), r"eq:p:(?P<faction>pirate|marine)"),
                          (Q.BoutonRejoindre(3), r"eq:j:(?P<eid>\d+)"), (Q.BoutonRecrutement(3), r"eq:r:(?P<eid>\d+)"),
                          (Q.BoutonModifier(3), r"eq:m:(?P<eid>\d+)"), (Q.BoutonRetirer(3), r"eq:x:(?P<eid>\d+)")):
        assert re.fullmatch(gabarit, item.item.custom_id)


def test_Q2_publier_une_carte_dans_le_post_crews_le_bouton_redescend(env):
    g, crews = installe(env)
    kolax = g.membre(7)
    i = publier(g, kolax)
    e = run(Q.charger(1))
    carte = crews.messages[0]
    assert (e["mode"], e["fil_id"]) == ("carte", carte.id) and len(g.fils) == 1, "une carte, pas un fil"
    assert i.suivis[0][0] == f"Équipage publié : https://discord.com/channels/1/{crews.id}/{carte.id}"
    assert ids(carte.kw["view"]) == ["eq:j:1", "eq:r:1", "eq:m:1", "eq:x:1"] and compter(carte.kw["view"]) <= 40
    t = textes(carte.kw["view"])
    assert "## 🏴‍☠️ Les Requins Rouges" in t and "**Capitaine · Captain** · Kolax\\_RS" in t
    assert "📣 **Recrute · Recruiting**" in t and carte.kw["allowed_mentions"].everyone is False
    panneau = crews.messages[1]
    assert ids(panneau.kw["view"]) == ["eq:p:pirate", "eq:p:marine"] and env.conf["eq_panneau"] == panneau.id
    assert crews.id not in g.effaces, "le message d'ouverture du post reste"
    assert env.journal[-1][0] == "equipage.publie"
    i = publier(g, kolax, "marine")
    assert f"https://discord.com/channels/1/{crews.id}/{carte.id}" in i.suivis[0][0], "un équipage par capitaine"
    env.langues[8] = "en"
    i = interaction(g, g.membre(8))
    run(Q.BoutonPublier("marine").callback(i))
    assert i.response.modals[0].title == "⚓ Marine crew"
    i = publier(g, g.membre(8), "marine", dict(VALEURS, nom=""), "en")
    assert i.response.messages[0][0] == "“Crew name” is required."
    i = publier(g, g.membre(8), "marine", dict(VALEURS, nom="Blue Navy", presentation="<@123456789012345678> @everyone"),
                "en")
    assert i.suivis[0][0].startswith("Crew posted: https://")
    t = textes(crews.messages[-2].kw["view"])
    assert "<@123456789012345678>" not in t and "@everyone" not in t, "le texte d'un membre ne mentionne personne"
    assert panneau.id in g.effaces, "le bouton redescend sous la dernière carte"


def test_Q3_rejoindre_un_mot_sous_la_carte_qui_previent_le_capitaine(env):
    g, crews = installe(env)
    cap, matelot = g.membre(7), g.membre(8)
    publier(g, cap)
    carte = crews.messages[0]
    i = interaction(g, cap)
    run(Q.BoutonRejoindre(1).callback(i))
    assert i.suivis[0][0] == "C'est ton équipage."
    i = interaction(g, matelot)
    run(Q.BoutonRejoindre(1).callback(i))
    assert i.suivis[0][0] == f"Le capitaine est prévenu, rendez-vous dans le fil. " \
                             f"https://discord.com/channels/1/{crews.id}/{carte.id}"
    mot = crews.messages[-1]
    assert mot.content == "🙋 <@8> veut rejoindre l'équipage · wants to join — <@7>" and mot.reference.message_id == carte.id
    assert [u.id for u in mot.kw["allowed_mentions"].users] == [7], "seul le capitaine est notifié"
    n = len(crews.messages)
    i = interaction(g, matelot)
    run(Q.BoutonRejoindre(1).callback(i))
    assert "déjà demandé" in i.suivis[0][0] and len(crews.messages) == n, "pas de rafale de notifications"
    assert run(Q._effacer_mots(g, maintenant=time.time() + 23 * 3600)) == 0
    assert run(Q._effacer_mots(g, maintenant=time.time() + 25 * 3600)) == 1 and mot.id in g.effaces, \
        "le mot du bot part après un jour"


def test_Q4_le_capitaine_ferme_rouvre_modifie_sa_carte_suit(env):
    g, crews = installe(env)
    cap, autre = g.membre(7), g.membre(8)
    publier(g, cap)
    carte = crews.messages[0]
    i = interaction(g, autre)
    run(Q.BoutonRecrutement(1).callback(i))
    assert i.response.messages[0][0] == "Réservé au capitaine de l'équipage."
    i = interaction(g, cap)
    run(Q.BoutonRecrutement(1).callback(i))
    assert i.suivis[0][0] == "Recrutement fermé."
    assert crews.cartes[-1][0] == carte.id and ids(crews.cartes[-1][1]["view"]) == ["eq:r:1", "eq:m:1", "eq:x:1"]
    i = interaction(g, autre)
    run(Q.BoutonRejoindre(1).callback(i))
    assert i.suivis[0][0] == "Cet équipage ne recrute pas pour le moment."
    i = interaction(g, cap)
    run(Q.BoutonModifier(1).callback(i))
    modal = i.response.modals[0]
    assert modal.eid == 1 and modal.entrees["nom"].default == "Les Requins Rouges", "le formulaire est pré-rempli"
    i = interaction(g, cap)
    run(Q.modifier(i, 1, dict(VALEURS, nom="Les Requins Noirs", membres="8 / 10"), "fr"))
    assert i.suivis[0][0] == "Équipage mis à jour."
    t = textes(crews.cartes[-1][1]["view"])
    assert "Les Requins Noirs" in t and "8 / 10" in t and crews.name == "⚓ Crews · Équipages", "le post ne bouge pas"
    i = interaction(g, cap)
    run(Q.modifier(i, 1, dict(VALEURS, nom="Les insulte"), "fr"))
    assert "insulte" in i.response.messages[0][0] and run(Q.charger(1))["nom"] == "Les Requins Noirs"


def test_Q5_retirer_la_carte_et_ses_mots_partent_le_depart_aussi(env):
    g, crews = installe(env)
    a, b, c = g.membre(7), g.membre(8), g.membre(9)
    env.staff.add(12)
    g.membre(12)
    publier(g, a)
    publier(g, b, "marine")
    publier(g, c)
    carte_a = run(Q.charger(1))["fil_id"]
    run(Q.BoutonRejoindre(1).callback(interaction(g, b)))
    mot = crews.messages[-1]
    i = interaction(g, c)
    run(Q.BoutonRetirer(1).callback(i))
    assert i.response.messages[0][0] == "Réservé au capitaine de l'équipage."
    i = interaction(g, a)
    run(Q.BoutonRetirer(1).callback(i))
    vue = i.response.messages[0][1]["view"]
    oui = next(x for x in vue.walk_children() if isinstance(x, discord.ui.Button) and x.label == "Oui, retirer")
    n = len(env.journal)
    j = interaction(g, a)
    run(oui.callback(j))
    assert "Équipage retiré." in textes(_vue_de(j)) and {carte_a, mot.id} <= g.effaces and len(env.journal) == n
    assert run(Q.charger(1))["supprime"] == 1 and not run(Q.retirer(g, 1, 7)), "déjà retiré"
    assert run(Q.retirer(g, 2, 12)) and env.journal[-1][0] == "equipage.retire", "le staff, au journal"
    assert run(Q.sur_depart(c)) == 1 and run(Q.charger(3))["supprime"] == 1, "il part avec son capitaine"
    assert publier(g, a).suivis[0][0].startswith("Équipage publié"), "après l'avoir retiré, on peut en republier un"


def test_Q6_l_entretien_oublie_les_cartes_effacees_pas_sur_une_panne(env):
    g, crews = installe(env)
    publier(g, g.membre(7))
    publier(g, g.membre(8))
    run(crews.get_partial_message(run(Q.charger(2))["fil_id"]).delete())  # effacée à la main
    run(Q.entretenir(g))
    assert run(Q.charger(2))["supprime"] == 1 and run(Q.charger(1))["supprime"] == 0
    del g.fils[crews.id]  # plus en mémoire : il faut demander à Discord, qui ne répond pas

    async def panne(_cid):
        raise discord.HTTPException(Obj(status=503, reason="x"), "panne")
    g.fetch_channel = panne
    run(Q.entretenir(g))
    assert run(Q.charger(1))["supprime"] == 0, "une panne réseau ne retire pas un équipage"
    assert not run(Q.retirer(g, 1, 7)) and run(Q.charger(1))["supprime"] == 0, "ni un retrait qui n'a pas abouti"


def test_Q7_l_ancien_forum_un_post_par_equipage_demenage_en_cartes(env):
    g = Monde()
    rell = g.categorie("· Rell Seas")
    assert run(Q.installer(g, rell)) == ["salon ⚓crews"]
    forum = g.get_channel(env.conf["eq_forum"])
    assert isinstance(forum, Forum) and [t.name for t in forum.available_tags] == [
        "Pirates", "Marine", "Recrute · Recruiting", "Complet · Full"]
    publier(g, g.membre(7))
    ancien = forum.crees[-1].fil
    assert ancien.applied_tags == ["Pirates", "Recrute · Recruiting"] and run(Q.charger(1))["mode"] == ""
    run(Q.BoutonRecrutement(1).callback(interaction(g, g.membre(7))))
    assert ancien.applied_tags == ["Pirates", "Complet · Full"]
    neuf = g._salon(Forum, "🌊rell-seas", {"category": g.commu})
    crews = run(neuf.create_thread(name="⚓ Crews · Équipages")).thread
    env.conf.update(eq_forum=crews.id, eq_panneau=crews.id, eq_ouverture=crews.id)
    assert run(Q.demenager(g)) == 1
    e = run(Q.charger(1))
    assert e["mode"] == "carte" and e["fil_id"] == crews.messages[0].id and e["recrute"] == 0, "rien n'est perdu"
    assert "Les Requins Rouges" in textes(crews.messages[0].kw["view"])
    assert run(Q.demenager(g)) == 0, "une fois"


def test_Q8_branche_dans_le_bot():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    for nom in ("BoutonPublier", "BoutonRejoindre", "BoutonRecrutement", "BoutonModifier", "BoutonRetirer"):
        assert f"equipages.{nom}" in src, f"{nom} doit être réenregistré au démarrage"
    assert "await equipages.init_db()" in src and "await equipages.sur_depart(m)" in src
    boucle = next(ast.unparse(n) for n in ast.parse(src).body if getattr(n, "name", "") == "entraide_task")
    assert "await equipages.entretenir(g)" in boucle
    assert (RACINE / "visuels" / "rs_crews.gif").is_file()
