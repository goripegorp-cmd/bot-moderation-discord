"""22/10/2026 (nuit) : « Un vrai système ultra bien concernant le jeu. Les gens, ils peuvent publier
leur équipage, que ce soit la marine ou les pirateries… » Un forum ⚓crews dans la zone Rell Seas :
un post par équipage, publié dans sa langue, carte en français · anglais ; le capitaine le modifie,
ouvre ou ferme le recrutement, le retire ; rejoindre prévient le capitaine. Sur un faux serveur."""
from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

import discord
import pytest

import equipages as Q
from conftest_discord import Obj, base
from faux_serveur import Forum, Monde, Texte, compter, ids, interaction, run, textes

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


def installe(env, forum=True):
    g = Monde(forum)
    rell = g.categorie("· Rell Seas")
    faits = run(Q.installer(g, rell))
    return g, rell, faits


def publier(g, membre, faction="pirate", valeurs=None, langue="fr"):
    i = interaction(g, membre)
    run(Q.publier(i, faction, dict(valeurs or VALEURS), langue))
    return i


def forum_de(g, env):
    return g.get_channel(env.conf["eq_forum"])


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
    assert Q.Formulaire("marine", "en").title == "⚓ Marine crew"
    assert Q.Formulaire("pirate").title == "🏴‍☠️ Équipage Pirates"
    assert [lab.text for lab in Q.Formulaire("pirate", "en").children][:2] == ["Crew name",
                                                                               "Your Roblox username (captain)"]
    assert all(set(v) == {"fr", "en"} for v in Q.TEXTES.values()), "chaque texte existe dans les deux langues"
    for item, gabarit in ((Q.BoutonPublier("marine"), r"eq:p:(?P<faction>pirate|marine)"),
                          (Q.BoutonRejoindre(3), r"eq:j:(?P<eid>\d+)"), (Q.BoutonRecrutement(3), r"eq:r:(?P<eid>\d+)"),
                          (Q.BoutonModifier(3), r"eq:m:(?P<eid>\d+)"), (Q.BoutonRetirer(3), r"eq:x:(?P<eid>\d+)")):
        assert re.fullmatch(gabarit, item.item.custom_id)
    assert [b.item.label for b in (Q.BoutonRejoindre(1), Q.BoutonRecrutement(1), Q.BoutonModifier(1),
                                   Q.BoutonRetirer(1))] == ["Rejoindre · Join", "Recrutement · Recruiting",
                                                            "Modifier · Edit", "Retirer · Remove"]


def test_Q2_un_forum_dans_la_zone_rell_seas_un_post_epingle_deux_boutons(env):
    g, rell, faits = installe(env)
    forum = forum_de(g, env)
    assert faits == ["salon ⚓crews"] and isinstance(forum, Forum) and forum.category_id == rell.id
    assert [t.name for t in forum.available_tags] == ["Pirates", "Marine", "Recrute · Recruiting", "Complet · Full"]
    droits = forum.kw["overwrites"][g.default_role]
    assert (droits.send_messages, droits.send_messages_in_threads, droits.attach_files) == (False, True, True), \
        "on publie par le bouton, on parle (et on montre) dans les fils"
    post = g.fils[env.conf["eq_panneau"]]
    assert post.name == "📌 Publier ton équipage · Post your crew" and post.flags.pinned and post.locked
    assert ids(forum.crees[0].view) == ["eq:p:pirate", "eq:p:marine"]
    t = textes(forum.crees[0].view)
    assert "🇫🇷" in t and "🇬🇧" in t and "Un équipage par capitaine · One crew per captain" in t
    assert run(Q.installer(g, rell)) == [] and len(forum.crees) == 1, "relancer ne crée rien"
    forum.category_id = g.commu.id
    run(Q.installer(g, rell))
    assert forum.category_id == rell.id and forum.edits[-1]["sync_permissions"] is False, "il revient dans sa zone"
    post.archived = True
    run(Q.assurer_panneau(g))
    assert not post.archived and post.flags.pinned


def test_Q3_publier_son_equipage_carte_etiquettes_un_par_capitaine(env):
    g, _r, _f = installe(env)
    kolax = g.membre(7)
    i = publier(g, kolax)
    assert i.suivis[0][0].startswith("Équipage publié : https://discord.com/channels/1/")
    forum = forum_de(g, env)
    post = forum.crees[-1]
    assert post.fil.name == "🏴‍☠️ Les Requins Rouges · Pirate7" and post.fil.membres == [7]
    assert post.fil.applied_tags == ["Pirates", "Recrute · Recruiting"]
    assert ids(post.view) == ["eq:j:1", "eq:r:1", "eq:m:1", "eq:x:1"]
    t = textes(post.view)
    assert "## 🏴‍☠️ Les Requins Rouges" in t and "**Capitaine · Captain** · Kolax\\_RS" in t
    assert "📣 **Recrute · Recruiting**" in t and "On chasse les boss le soir." in t
    assert compter(post.view) <= 40
    assert env.journal[-1][0] == "equipage.publie" and env.journal[-1][2]["membre_id"] == 7
    e = run(Q.charger(1))
    assert (e["faction"], e["recrute"], e["fil_id"], e["nom"]) == ("pirate", 1, post.fil.id, "Les Requins Rouges")
    i = publier(g, kolax, "marine")
    assert i.suivis[0][0].startswith("Tu as déjà un équipage"), "un équipage par capitaine"
    i = interaction(g, kolax)
    run(Q.BoutonPublier("marine").callback(i))
    assert i.response.messages[0][0].startswith("Tu as déjà un équipage") and not i.response.modals
    env.langues[8] = "en"
    i = interaction(g, g.membre(8))
    run(Q.BoutonPublier("marine").callback(i))
    assert i.response.modals[0].title == "⚓ Marine crew"
    i = publier(g, g.membre(8), "marine", dict(VALEURS, nom=""), "en")
    assert i.response.messages[0][0] == "“Crew name” is required."
    i = publier(g, g.membre(8), "marine", dict(VALEURS, nom="Navy insulte"), "en")
    assert "insulte" in i.response.messages[0][0], "le texte passe le même filtre que le reste"
    i = publier(g, g.membre(8), "marine", dict(VALEURS, nom="Blue Navy", presentation="<@123456789012345678> @everyone"),
                "en")
    assert i.suivis[0][0].startswith("Crew posted: https://")
    assert forum.crees[-1].fil.applied_tags == ["Marine", "Recrute · Recruiting"]
    t = textes(forum.crees[-1].view)
    assert "<@123456789012345678>" not in t and "@everyone" not in t, "le texte d'un membre ne mentionne personne"
    assert forum.crees[-1].allowed_mentions.everyone is False


def test_Q4_demander_a_rejoindre_previent_le_capitaine_une_fois(env):
    g, _r, _f = installe(env)
    cap, matelot = g.membre(7), g.membre(8)
    publier(g, cap)
    fil = forum_de(g, env).crees[-1].fil
    i = interaction(g, cap)
    run(Q.BoutonRejoindre(1).callback(i))
    assert i.suivis[0][0] == "C'est ton équipage."
    i = interaction(g, matelot)
    run(Q.BoutonRejoindre(1).callback(i))
    assert i.suivis[0][0].startswith("Le capitaine est prévenu, rendez-vous dans le fil.")
    assert fil.envois[-1][0] == "🙋 <@8> veut rejoindre l'équipage · wants to join — <@7>" and 8 in fil.membres
    assert [u.id for u in fil.envois[-1][1]["allowed_mentions"].users] == [7], "seul le capitaine est notifié"
    n = len(fil.envois)
    i = interaction(g, matelot)
    run(Q.BoutonRejoindre(1).callback(i))
    assert "déjà demandé" in i.suivis[0][0] and len(fil.envois) == n, "pas de rafale de notifications"
    fil.archived = True
    env.langues[9] = "en"
    i = interaction(g, g.membre(9))
    run(Q.BoutonRejoindre(1).callback(i))
    assert not fil.archived and i.suivis[0][0].startswith("The captain has been notified"), \
        "un post endormi se réveille pour la demande"


def test_Q5_le_capitaine_ferme_et_rouvre_le_recrutement(env):
    g, _r, _f = installe(env)
    cap, autre = g.membre(7), g.membre(8)
    publier(g, cap)
    fil = forum_de(g, env).crees[-1].fil
    i = interaction(g, autre)
    run(Q.BoutonRecrutement(1).callback(i))
    assert i.response.messages[0][0] == "Réservé au capitaine de l'équipage."
    i = interaction(g, cap)
    run(Q.BoutonRecrutement(1).callback(i))
    assert i.suivis[0][0] == "Recrutement fermé." and fil.applied_tags == ["Pirates", "Complet · Full"]
    vue = fil.cartes[-1][1]["view"]
    assert ids(vue) == ["eq:r:1", "eq:m:1", "eq:x:1"] and "🔒 **Complet · Full**" in textes(vue)
    i = interaction(g, autre)
    run(Q.BoutonRejoindre(1).callback(i))
    assert i.suivis[0][0] == "Cet équipage ne recrute pas pour le moment."
    i = interaction(g, cap)
    run(Q.BoutonRecrutement(1).callback(i))
    assert i.suivis[0][0] == "Recrutement ouvert." and fil.applied_tags == ["Pirates", "Recrute · Recruiting"]
    assert ids(fil.cartes[-1][1]["view"])[0] == "eq:j:1"


def test_Q6_modifier_renomme_le_post_et_refait_la_carte(env):
    g, _r, _f = installe(env)
    cap = g.membre(7)
    publier(g, cap)
    fil = forum_de(g, env).crees[-1].fil
    i = interaction(g, g.membre(8))
    run(Q.BoutonModifier(1).callback(i))
    assert i.response.messages[0][0] == "Réservé au capitaine de l'équipage."
    i = interaction(g, cap)
    run(Q.BoutonModifier(1).callback(i))
    modal = i.response.modals[0]
    assert modal.eid == 1 and modal.entrees["nom"].default == "Les Requins Rouges", "le formulaire est pré-rempli"
    i = interaction(g, cap)
    run(Q.modifier(i, 1, dict(VALEURS, nom="Les Requins Noirs", membres="8 / 10"), "fr"))
    assert i.suivis[0][0] == "Équipage mis à jour."
    assert fil.name == "🏴‍☠️ Les Requins Noirs · Pirate7"
    t = textes(fil.cartes[-1][1]["view"])
    assert "Les Requins Noirs" in t and "8 / 10" in t and run(Q.charger(1))["nom"] == "Les Requins Noirs"
    i = interaction(g, cap)
    run(Q.modifier(i, 1, dict(VALEURS, nom="Les insulte"), "fr"))
    assert "insulte" in i.response.messages[0][0] and run(Q.charger(1))["nom"] == "Les Requins Noirs"


def test_Q7_retirer_le_capitaine_sans_bruit_le_staff_au_journal_le_depart_aussi(env):
    g, _r, _f = installe(env)
    a, b, c = g.membre(7), g.membre(8), g.membre(9)
    env.staff.add(12)
    g.membre(12)
    publier(g, a)
    publier(g, b, "marine")
    publier(g, c)
    fil_a = g.fils[run(Q.charger(1))["fil_id"]]
    i = interaction(g, c)
    run(Q.BoutonRetirer(1).callback(i))
    assert i.response.messages[0][0] == "Réservé au capitaine de l'équipage."
    i = interaction(g, a)
    run(Q.BoutonRetirer(1).callback(i))
    vue = i.response.messages[0][1]["view"]
    assert "Retirer cet équipage ? Son post disparaît." in textes(vue)
    oui = next(x for x in vue.walk_children() if isinstance(x, discord.ui.Button) and x.label == "Oui, retirer")
    n = len(env.journal)
    j = interaction(g, a)
    run(oui.callback(j))
    assert "Équipage retiré." in textes(_vue_de(j)) and fil_a.id not in g.fils and len(env.journal) == n
    assert run(Q.charger(1))["supprime"] == 1 and not run(Q.retirer(g, 1, 7)), "déjà retiré"
    i = interaction(g, g.membre(12))
    run(Q.BoutonRetirer(2).callback(i))
    assert "Retirer cet équipage" in textes(i.response.messages[0][1]["view"]), "le staff peut retirer"
    assert run(Q.retirer(g, 2, 12)) and env.journal[-1][0] == "equipage.retire"
    assert run(Q.sur_depart(c)) == 1 and run(Q.charger(3))["supprime"] == 1, "il part avec son capitaine"
    assert publier(g, a).suivis[0][0].startswith("Équipage publié"), "après l'avoir retiré, on peut en republier un"


def test_Q8_l_entretien_reveille_les_posts_oublie_les_disparus_pas_sur_une_panne(env):
    g, _r, _f = installe(env)
    publier(g, g.membre(7))
    publier(g, g.membre(8))
    f1, f2 = (g.fils[run(Q.charger(n))["fil_id"]] for n in (1, 2))
    f1.archived = True
    run(f2.delete())  # supprimé à la main
    assert run(Q.entretenir(g)) == 1 and not f1.archived
    assert run(Q.charger(2))["supprime"] == 1 and run(Q.charger(1))["supprime"] == 0
    del g.fils[f1.id]  # plus dans le cache : il faut le demander à Discord, qui ne répond pas

    async def panne(_cid):
        raise discord.HTTPException(Obj(status=503, reason="x"), "panne")
    g.fetch_channel = panne
    run(Q.entretenir(g))
    assert run(Q.charger(1))["supprime"] == 0, "une panne réseau ne retire pas un équipage"
    assert not run(Q.retirer(g, 1, 7)) and run(Q.charger(1))["supprime"] == 0, "ni un retrait qui n'a pas abouti"


def test_Q9_sans_communaute_un_salon_des_cartes_et_le_bouton_en_bas(env):
    g, _r, faits = installe(env, forum=False)
    salon = forum_de(g, env)
    assert isinstance(salon, Texte) and faits == ["salon ⚓crews"] and len(salon.envois) == 1
    ancien = env.conf["eq_panneau"]
    publier(g, g.membre(7))
    e = run(Q.charger(1))
    carte = next(x for x in salon.envois if x[0] == e["fil_id"])
    assert ids(carte[2]["view"])[0] == "eq:j:1" and g.fils[e["fil_id"]].parent is salon
    assert ancien in g.effaces and env.conf["eq_panneau"] != ancien, "le bouton redescend sous la carte"
    run(Q.BoutonRecrutement(1).callback(interaction(g, g.membre(7))))
    assert salon.cartes[-1][0] == e["fil_id"], "la carte se met à jour dans le salon, pas dans le fil"
    run(Q.assurer_panneau(g))
    assert len([x for x in salon.envois if ids(x[2].get("view")) == ["eq:p:pirate", "eq:p:marine"]]) == 2, \
        "un bouton toujours là n'est pas reposé"
    assert run(Q.retirer(g, 1, 7)) and e["fil_id"] in g.effaces


def test_Q10_branche_dans_le_bot():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    for nom in ("BoutonPublier", "BoutonRejoindre", "BoutonRecrutement", "BoutonModifier", "BoutonRetirer"):
        assert f"equipages.{nom}" in src, f"{nom} doit être réenregistré au démarrage"
    assert "await equipages.init_db()" in src and "await equipages.sur_depart(m)" in src
    arbre = ast.parse(src)
    boucle = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "entraide_task")
    assert "await equipages.entretenir(g)" in boucle
    assert (RACINE / "visuels" / "rs_crews.gif").is_file()
