"""22/10/2026 : « aide, trading de fruits, farm, boss, chill… ultra compact… des joueurs qualifiés
avec des rôles… certifier que l'aide a bien été faite et clôturer la demande… un nettoyage
automatique ». Puis : « trop de salons » (deux forums) et, la nuit : « le serveur est international,
mais aussi français… les gens peuvent clôturer leur propre ticket… quand les demandes sont
clôturées, le fil se ferme aussi… un vrai système de nettoyage ultra propre… les badges SOS,
horrible ». Enfin : « deux fils seulement… plutôt que des milliers de fils » — une demande est une
carte dans le post 🛟 Help ou 🤝 Trade. Le parcours entier, sur un faux serveur (`faux_serveur.py`)."""
from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from pathlib import Path

import discord
import pytest

import entraide as E
from conftest_discord import Obj, base
from faux_serveur import ANCIENS_STATUTS, Forum, Message, Monde, Texte, compter, ids, interaction, lot_18, run, textes

RACINE = Path(__file__).resolve().parent.parent
Z = E.ZONES


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal, staff, langues, archives = [], set(), {}, []

    async def texte_refuse(_g, t):
        return "Ta demande contient une insulte." if "insulte" in t else ""

    async def controle(_m, _c):
        return ""

    async def est_staff(_g, m):
        return m.id in staff

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))

    async def langue(i):
        return langues.get(i.user.id, "fr")

    async def archiver(fil, titre):
        if langues.get("archive") == "panne":
            raise OSError("disque plein")
        archives.append((fil.id, titre))
        return f"jeton{len(archives)}"
    E._verrous.clear()
    E._creations.clear()
    E._verifies.clear()
    E.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse, controle=controle,
            est_staff=est_staff, journal=noter, langue=langue, archiver=archiver, log=lambda *a: None)
    asyncio.run(E.init_db())
    return Obj(conf=conf, journal=journal, staff=staff, langues=langues, archives=archives, get_db=get_db)


def installe(env):
    """Le serveur comme les zones le laissent : les posts 🛟 Help et 🤝 Trade du forum 🌊rell-seas ; leur
    message d'ouverture porte les boutons."""
    g = Monde()
    env.conf.update(aide_salon=g.nom("❓aide").id)
    rell = g._salon(Forum, "🌊rell-seas", {"category": g.commu})
    posts = {}
    for cle, titre in (("entraide", "🛟 Help · Entraide"), ("trade", "🤝 Trade · Échanges")):
        posts[cle] = run(rell.create_thread(name=titre)).thread.id
    env.conf.update(rs_salons=dict(posts), rs_panneaux=dict(posts), rs_ouvertures=dict(posts))
    return g, posts, run(E.installer(g, creer_salons=False))


def demande_valeurs(zone):
    return {"aide": {"titre": "Bloqué à l'île du crâne", "details": "Je ne trouve pas la clé", "pseudo": "Kolax_RS",
                     "niveau": "850"},
            "boss": {"titre": "Akuma", "pseudo": "Kolax_RS", "niveau": "1200", "joueurs": "2", "details": ""},
            "farm": {"titre": "Niveaux", "pseudo": "Kolax_RS", "niveau": "300", "duree": "1 h", "details": ""},
            "trade": {"donne": "Fruit Dragon", "cherche": "Fruit Dough", "pseudo": "Kolax_RS", "details": ""},
            "chill": {"titre": "Naviguer", "pseudo": "Kolax_RS", "quand": "ce soir", "details": ""}}[zone]


def publier(g, membre, zone, valeurs=None, langue="fr"):
    i = interaction(g, membre)
    run(E.publier(i, Z[zone], valeurs or demande_valeurs(zone), langue))
    return i


def forum_de(g, env, cle):
    return g.get_channel(env.conf["rs_salons"][cle])


def _d(zone="aide", statut="ouverte", **kw):
    d = {"id": 5, "guild_id": 1, "zone": zone, "auteur_id": 7, "titre": "t", "statut": statut, "salon_id": 0,
         "fil_id": 0, "aidants": [], "cree": 1_800_000_000, "maj": 1_800_000_000, "ferme": 0, "ferme_par": 0,
         "certifie_par": 0, "credites": [], "partenaire_id": 0, "appel_mm": 0, "supprime": 0, "jeton": "",
         "champs": [["Question", "<@123456789012345678> **piège** @everyone"]]}
    d.update(kw)
    return d


def _vue_de(i):
    """La vue de la dernière réponse éphémère (envoyée ou réécrite)."""
    for contenu, kw in reversed(i.suivis):
        if isinstance(kw, dict) and kw.get("view") is not None:
            return kw["view"]
    return i.response.messages[-1][1]["view"]


# ─── Les types, en français · anglais ────────────────────────────────────────

def test_E1_cinq_types_deux_forums_des_formulaires_dans_les_deux_langues():
    assert [k for k, z in Z.items() if z.jeu == "rell"] == ["aide", "boss", "farm", "chill", "trade"]
    assert [k for k, z in Z.items() if z.jeu == "clover"] == ["cl_aide", "cl_boss", "cl_farm", "cl_chill", "cl_trade"],         "Clover RPG : les mêmes types, à lui"
    assert [z.salon for z in Z.values() if z.echange] == ["trade", "cl_trade"] and Z["cl_aide"].libelle ==         "Aide · Help · Clover RPG"
    assert [z.cle for z in E.types_du_salon("entraide")] == ["aide", "boss", "farm", "chill"]
    assert [z.cle for z in E.types_du_salon("trade")] == ["trade"] and list(E.SALONS) == ["entraide", "trade", "cl_entraide", "cl_trade"]
    assert [v[0] for v in E.SALONS.values()] == ["🛟help", "🤝trade", "🛟help-clover", "🤝trade-clover"],         "au style du serveur : l'émoji collé au nom"
    assert Z["aide"].emoji == "🛟", "plus de badge 🆘"
    for z in Z.values():
        assert 1 <= len(z.champs) <= 5 and any(c.cle == "pseudo" for c in z.champs)
        assert bool(z.role) == bool(z.certif) and z.bouton and " · " in z.rejoindre and " · " in z.annonce
        assert E.titre_de(z, {c.cle: "x" for c in z.champs})
        for langue, fin in (("fr", "nouvelle demande"), ("en", "new request")):
            f = E.Formulaire(z, langue)
            assert len(f.title) <= 45 and f.title.endswith(fin) and len(f.children) == len(z.champs)
            assert [lab.text for lab in f.children] == [c.libelle(langue) for c in z.champs]
            assert all(len(c.libelle(langue)) <= 45 and len(c.exemple(langue)) <= 100 for c in z.champs)
    assert [lab.text for lab in E.Formulaire(Z["trade"], "en").children][:2] == ["I give", "I want"]
    tags = [t.name for t in E.tags_du_salon("entraide")]
    assert tags == ["Aide · Help", "Boss", "Farm", "Chill", "Ouverte · Open", "En cours · Ongoing",
                    "Terminée · Done", "Fermée · Closed"]
    assert [t.name for t in E.tags_du_salon("trade")] == tags[4:]
    assert all(len(t) <= 20 for t in tags), "Discord refuse une étiquette de plus de 20 caractères"
    assert all(set(v) == {"fr", "en"} for v in E.TEXTES.values()), "chaque texte existe dans les deux langues"
    assert E.tr("publiee", "en", lien="L") == "Request posted: L" and E.tr("publiee", "xx", lien="L") == \
        "Demande publiée : L", "une langue inconnue retombe sur le français"
    for item, gabarit in ((E.BoutonNouvelle("boss"), r"rs:n:(?P<zone>[a-z]+)"),
                          (E.BoutonRejoindre(5), r"rs:j:(?P<did>\d+)"), (E.BoutonCertifier(5), r"rs:c:(?P<did>\d+)"),
                          (E.BoutonFermer(5), r"rs:f:(?P<did>\d+)"), (E.BoutonMiddleman(5), r"rs:m:(?P<did>\d+)")):
        assert re.fullmatch(gabarit, item.item.custom_id)
    assert E.BoutonNouvelle("trade").item.label == "Proposer · Post a trade"
    assert E.BoutonFermer(5).item.label == "Clôturer · Close" and E.BoutonCertifier(5).item.label == \
        "Certifier · Certify"


def test_E2_la_carte_bilingue_montre_ce_qu_il_faut_et_seulement_les_boutons_utiles():
    assert ids(E.vue_carte(_d("aide"), Z["aide"])) == ["rs:j:5", "rs:c:5", "rs:f:5"]
    assert ids(E.vue_carte(_d("trade"), Z["trade"], rep=3)) == ["rs:j:5", "rs:m:5", "rs:c:5", "rs:f:5"]
    assert ids(E.vue_carte(_d("chill"), Z["chill"])) == ["rs:j:5", "rs:f:5"], "le chill ne se certifie pas"
    t = textes(E.vue_carte(_d("aide"), Z["aide"], ping="<@&9>"))
    assert "<@123456789012345678>" not in t and "@everyone" not in t, "le texte d'un membre ne mentionne personne"
    assert "Guides prévenus · Guides notified : <@&9>" in t and "personne pour l'instant · nobody yet" in t
    assert "J'aide · I'll help" in t and "🛟 Aide · Help · n°5" in t
    t = textes(E.vue_carte(_d("trade"), Z["trade"], rep=3))
    assert "3 échange(s) certifié(s) · certified trade(s)" in t and "never give first" in t
    assert "Intéressé · Interested" in t
    close = E.vue_carte(_d("aide", "terminee", ferme=1_800_000_100, certifie_par=10, credites=[8]), Z["aide"])
    assert ids(close) == [], "une demande close n'a plus de bouton"
    t = textes(close)
    assert "Aide certifiée · Help certified" in t and "<@10>" in t and "Ont aidé · Helped : <@8>" in t
    assert "Fil fermé · Thread closed" in t
    t = textes(E.vue_carte(_d("trade", "terminee", ferme=1_800_000_100, partenaire_id=8), Z["trade"]))
    assert "Échange conclu · Trade done" in t and "Avec · With <@8>" in t, "clos par l'auteur, sans middleman"
    assert "Résolue · Solved" in textes(E.vue_carte(_d("aide", "terminee", ferme=1_800_000_100), Z["aide"]))
    assert compter(E.vue_carte(_d("trade"), Z["trade"], avatar="https://x/a.png", ping="<@&9>", rep=2)) <= 40


# ─── Les posts 🛟 Help et 🤝 Trade : une carte par demande ─────────────────────

def test_E3_une_demande_est_une_carte_dans_le_post_help_le_panneau_redescend(env):
    g, posts, faits = installe(env)
    assert sorted(faits) == sorted(f"rôle {z.role}" for z in Z.values() if z.role), "les rôles ; aucun salon créé"
    aide = g.fils[posts["entraide"]]
    assert ids(aide.cartes[-1][1]["view"]) == ["rs:n:aide", "rs:n:boss", "rs:n:farm", "rs:n:chill"], \
        "le message d'ouverture du post porte les boutons"
    kolax = g.membre(7)
    i = publier(g, kolax, "boss")
    d = run(E.charger(1))
    carte = aide.messages[0]
    assert (d["mode"], d["salon_id"], d["fil_id"]) == ("carte", aide.id, carte.id)
    assert ids(carte.kw["view"]) == ["rs:j:1", "rs:c:1", "rs:f:1"] and "Boss" in textes(carte.kw["view"])
    assert i.suivis[0][0] == f"Demande publiée : https://discord.com/channels/1/{aide.id}/{carte.id}"
    guide = g.get_role(env.conf["rs_roles"]["boss"])
    assert carte.kw["allowed_mentions"].roles == [guide] and "Guides prévenus" in textes(carte.kw["view"])
    panneau = aide.messages[1]
    assert ids(panneau.kw["view"]) == ["rs:n:aide", "rs:n:boss", "rs:n:farm", "rs:n:chill"]
    assert env.conf["rs_panneaux"]["entraide"] == panneau.id and aide.id not in g.effaces, \
        "le panneau redescend sous la carte ; le message d'ouverture reste"
    assert len(g.fils) == 2, "aucun fil de plus : « plutôt que des milliers de fils »"
    assert env.journal[-1][0] == "entraide.demande"
    E._creations.clear()
    i2 = publier(g, kolax, "boss")
    assert f"https://discord.com/channels/1/{aide.id}/{carte.id}" in i2.response.messages[0][0], \
        "« déjà une demande ici » mène à sa carte"
    E._creations.clear()
    publier(g, kolax, "farm")
    assert panneau.id in g.effaces and aide.messages[-1].id == env.conf["rs_panneaux"]["entraide"]
    env.langues[9] = "en"
    i = interaction(g, g.membre(9))
    run(E.BoutonNouvelle("farm").callback(i))
    assert i.response.modals[0].title == "🌾 Farm · new request"
    i = publier(g, g.membre(9), "trade", {"donne": "", "cherche": "x", "pseudo": "y", "details": ""}, "en")
    assert "“I give” is required." in textes(i.response.messages[0][1]["view"])
    i = publier(g, g.membre(9), "trade", langue="en")
    assert i.suivis[0][0].startswith(f"Request posted: https://discord.com/channels/1/{posts['trade']}/")
    i3 = publier(g, g.membre(8), "boss", {"titre": "Une insulte", "pseudo": "x", "niveau": "", "joueurs": "",
                                          "details": ""})
    assert "insulte" in textes(i3.response.messages[0][1]["view"]), "le texte est filtré, on peut corriger"


def test_E4_rejoindre_un_mot_sous_la_carte_puis_tout_part_avec_elle(env):
    g, posts, _f = installe(env)
    aide = g.fils[posts["entraide"]]
    kolax, ami = g.membre(7), g.membre(8)
    guide = g.membre(10, g.get_role(env.conf["rs_roles"]["boss"]))
    publier(g, kolax, "boss")
    carte = aide.messages[0]
    i = interaction(g, kolax)
    run(E.rejoindre(i, 1))
    assert "C'est ta demande" in i.suivis[0][0]
    env.langues[8] = "en"
    i = interaction(g, ami)
    run(E.rejoindre(i, 1))
    assert i.suivis[0][0] == f"Got it, see you in the thread. https://discord.com/channels/1/{aide.id}/{carte.id}"
    mot = aide.messages[-1]
    assert mot.content == "🙋 <@8> vient t'aider · is coming to help — <@7>" and mot.reference.message_id == carte.id
    assert [u.id for u in mot.kw["allowed_mentions"].users] == [7] and mot.kw["mention_author"] is False
    assert run(E._notes(1)) == [mot.id]
    d = run(E.charger(1))
    assert (d["statut"], d["aidants"]) == ("prise", [8])
    assert aide.cartes[-1][0] == carte.id and "en route · on the way : <@8>" in textes(aide.cartes[-1][1]["view"])
    merci = aide.repondre(7, mot.id, "merci !")
    question = aide.repondre(9, carte.id, "je peux venir ?")
    bavard = aide.repondre(9, None, "quelqu'un pour farmer ?")
    vue = E.VueCertifier(d, Z["boss"], guide)
    run(vue._cb_ok(interaction(g, guide)))
    d = run(E.charger(1))
    assert (d["statut"], d["certifie_par"], d["credites"]) == ("terminee", 10, [8])
    assert ids(aide.cartes[-1][1]["view"]) == [] and "Aide certifiée · Help certified" in textes(aide.cartes[-1][1]["view"])
    assert env.archives == [], "une carte n'a pas de fil à enregistrer : la base garde tout pour le site"
    bilan = run(E.entretenir(g, maintenant=time.time() + 61))
    assert bilan["effacees"] == 1
    assert {carte.id, mot.id, merci.id, question.id} <= g.effaces, "la carte, le mot du bot, les réponses"
    assert bavard.id not in g.effaces and aide.id not in g.effaces, "le reste du post ne bouge pas"
    assert run(E.charger(1))["supprime"] == 1 and run(E._notes(1)) == []
    assert run(E.certifier(g, 1, guide, [])) == "Cette demande est déjà close."


def test_E5_echange_le_middleman_sous_la_carte_seul_lui_fait_la_confiance(env):
    g, posts, _f = installe(env)
    trade = g.fils[posts["trade"]]
    vendeur, acheteur, curieux = g.membre(7), g.membre(8), g.membre(9)
    mm = g.membre(11, g.get_role(env.conf["rs_roles"]["trade"]))
    publier(g, vendeur, "trade")
    carte = trade.messages[0]
    assert ids(carte.kw["view"]) == ["rs:j:1", "rs:m:1", "rs:c:1", "rs:f:1"]
    run(E.rejoindre(interaction(g, acheteur), 1))
    assert trade.messages[-1].content == "💬 <@8> est intéressé · is interested — <@7>"
    i = interaction(g, curieux)
    run(E.appeler_middleman(i, 1))
    assert "Seuls l'auteur et les intéressés" in i.suivis[0][0]
    i = interaction(g, vendeur)
    run(E.appeler_middleman(i, 1))
    role = g.get_role(env.conf["rs_roles"]["trade"])
    appel = trade.messages[-1]
    assert appel.content.startswith(f"🛡️ {role.mention}") and appel.kw["allowed_mentions"].roles == [role]
    assert appel.reference.message_id == carte.id and i.suivis[-1][0].startswith("Middlemen prévenus")
    i = interaction(g, acheteur)
    run(E.appeler_middleman(i, 1))
    assert "déjà été appelé" in i.suivis[0][0], "un appel par quart d'heure"
    assert run(E.certifier(g, 1, mm, [], partenaire=8)) == ""
    assert run(E.reputation(1, 7)) == 1 and run(E.reputation(1, 8)) == 1 and run(E.reputation(1, 9)) == 0
    assert "Échange certifié · Trade certified" in textes(trade.cartes[-1][1]["view"])
    E._creations.clear()
    publier(g, vendeur, "trade")
    run(E.rejoindre(interaction(g, acheteur), 2))
    assert run(E.resoudre(g, 2, vendeur, partenaire=8)) == ""
    d = run(E.charger(2))
    assert (d["statut"], d["certifie_par"], d["partenaire_id"]) == ("terminee", 0, 8)
    assert run(E.reputation(1, 7)) == 1, "conclu par l'auteur : ça ne compte pas dans la confiance"
    assert "Échange conclu · Trade done" in textes(trade.cartes[-1][1]["view"])
    assert env.journal[-1][0] == "entraide.resolue"


def test_E6_l_auteur_cloture_lui_meme_un_guide_sans_certifier_un_passant_non(env):
    g, posts, _f = installe(env)
    aide = g.fils[posts["entraide"]]
    auteur, ami, passant = g.membre(7), g.membre(8), g.membre(9)
    guide = g.membre(10, g.get_role(env.conf["rs_roles"]["aide"]))
    publier(g, auteur, "aide")
    run(E.rejoindre(interaction(g, ami), 1))
    i = interaction(g, passant)
    run(E.BoutonFermer(1).callback(i))
    assert i.response.messages[0][0] == E.tr("clore_reserve", "fr")
    i = interaction(g, guide)
    run(E.BoutonFermer(1).callback(i))
    assert "Clôturer sans certifier" in textes(i.response.messages[0][1]["view"])
    env.langues[7] = "en"
    i = interaction(g, auteur)
    run(E.BoutonFermer(1).callback(i))
    vue = i.response.messages[0][1]["view"]
    assert "Solved" in textes(vue) and "Cancel my request" in textes(vue)
    j = interaction(g, auteur)
    run(vue._cb_regle(j))
    assert "Request closed ✅" in textes(_vue_de(j))
    d = run(E.charger(1))
    assert (d["statut"], d["certifie_par"], d["credites"], d["ferme_par"]) == ("terminee", 0, [8], 7)
    assert ids(aide.cartes[-1][1]["view"]) == [] and "Résolue · Solved" in textes(aide.cartes[-1][1]["view"])
    E._creations.clear()
    publier(g, auteur, "chill")
    vue = E.VueCloturer(run(E.charger(2)), Z["chill"], auteur, "fr", True)
    run(vue._cb_annuler(interaction(g, auteur)))
    assert run(E.charger(2))["statut"] == "fermee"
    E._creations.clear()
    publier(g, auteur, "trade")
    run(E.rejoindre(interaction(g, ami), 3))
    vue = E.VueCloturer(run(E.charger(3)), Z["trade"], auteur, "fr", True)
    assert any(isinstance(c, discord.ui.UserSelect) for c in vue.walk_children()), "avec qui l'échange s'est fait"
    run(vue._cb_regle(interaction(g, auteur)))
    assert run(E.charger(3))["partenaire_id"] == 8, "par défaut, le joueur intéressé"


def test_E7_fermer_l_auteur_sans_bruit_le_staff_au_journal(env):
    g, _p, _f = installe(env)
    a, b = g.membre(7), g.membre(8)
    env.staff.add(12)
    g.membre(12)
    publier(g, a, "aide")
    E._creations.clear()
    publier(g, b, "chill")
    n = len(env.journal)
    assert run(E.fermer(g, 1, 7, "fermee"))
    assert len(env.journal) == n, "fermer sa propre demande ne remplit pas le journal"
    assert run(E.fermer(g, 2, 12, "fermee"))
    assert env.journal[-1][0] == "entraide.fermee"
    assert not run(E.fermer(g, 2, 12)), "déjà close"


def test_E8_le_nettoyage_ferme_l_inactif_efface_le_clos_rattrape_l_oublie(env):
    g, posts, _f = installe(env)
    aide = g.fils[posts["entraide"]]
    for uid, zone in ((7, "boss"), (8, "aide"), (9, "farm")):
        E._creations.clear()
        publier(g, g.membre(uid), zone)
    t0 = time.time()
    carte_farm = run(E.charger(3))["fil_id"]
    run(aide.get_partial_message(carte_farm).delete())  # effacée à la main par le staff
    run(E._ecrire("INSERT INTO entraide_demandes(guild_id, zone, auteur_id, titre, cree, maj) VALUES(1,'aide',5,'x',?,?)",
                  (int(t0) - 3600, int(t0) - 3600)))
    bilan = run(E.entretenir(g, maintenant=t0 + 7 * 3600))  # boss : 6 h ; aide : 24 h
    assert bilan == {"expirees": 1, "retirees": 1, "effacees": 0}, "la carte close reste le temps d'être vue"
    assert [run(E.charger(n))["statut"] for n in (1, 2, 3)] == ["expiree", "ouverte", "retiree"]
    assert run(E.charger(4)) is None, "une publication interrompue ne bloque personne"
    carte_boss = run(E.charger(1))["fil_id"]
    derniere = [k for mid, k in aide.cartes if mid == carte_boss][-1]
    assert ids(derniere["view"]) == [] and "plus d'activité · no activity" in textes(derniere["view"])
    bilan = run(E.entretenir(g, maintenant=t0 + 7 * 3600 + 61))
    #  24/10/2026 (revue) : la demande dont la carte a été effacée à la main part aussi au passage suivant, avec
    #  les mots du bot et les réponses (avant, elle était marquée effacée sans que rien ne soit retiré).
    assert bilan == {"expirees": 0, "retirees": 0, "effacees": 2} and carte_boss in g.effaces
    assert run(E.charger(1))["supprime"] == 1 and run(E.charger(3))["supprime"] == 1
    assert run(E.charger(2))["statut"] == "ouverte", "la base garde la trace"
    run(E._regler(g, "garder_h", 24))
    run(E.fermer(g, 2, 8, "fermee", maintenant=t0 + 8 * 3600))
    assert run(E.entretenir(g, maintenant=t0 + 9 * 3600))["effacees"] == 0, "réglé à 24 h : elle reste"
    assert run(E.entretenir(g, maintenant=t0 + 33 * 3600))["effacees"] == 1


def test_E9_un_membre_qui_part_ferme_ses_demandes(env):
    g, _p, _f = installe(env)
    m = g.membre(7)
    publier(g, m, "aide")
    assert run(E.sur_depart(m)) == 1 and run(E.charger(1))["statut"] == "fermee"


def test_E10_seule_sans_les_zones_des_salons_avec_les_memes_cartes(env):
    g = Monde(forum=False)
    env.conf.update(aide_salon=g.nom("❓aide").id)
    faits = run(E.installer(g))
    salon = g.get_channel(env.conf["rs_salons"]["entraide"])
    assert isinstance(salon, Texte) and salon.category_id == g.commu.id and "salon 🛟help" in faits
    assert len(salon.envois) == 1 and ids(salon.envois[0][2]["view"]) == ["rs:n:aide", "rs:n:boss", "rs:n:farm",
                                                                           "rs:n:chill"]
    ancien = env.conf["rs_panneaux"]["entraide"]
    publier(g, g.membre(7), "aide")
    d = run(E.charger(1))
    assert d["mode"] == "carte" and any(e[0] == d["fil_id"] for e in salon.envois) and len(g.fils) == 0
    assert ancien in g.effaces and env.conf["rs_panneaux"]["entraide"] != ancien, "le panneau redescend"
    run(E.fermer(g, 1, 7, "fermee"))
    assert salon.cartes[-1][0] == d["fil_id"]
    run(E.entretenir(g, maintenant=time.time() + 120))
    assert d["fil_id"] in g.effaces, "la carte close disparaît"


def test_E11_l_ancienne_installation_un_post_par_demande_marche_toujours(env):
    """Les demandes déjà ouvertes dans les anciens forums (avant les deux forums) se ferment
    proprement : historique enregistré pour le site, post verrouillé puis effacé."""
    g = Monde(forum=True)
    env.conf.update(aide_salon=g.nom("❓aide").id)
    rell = g.categorie("· Rell Seas")
    assert run(E.installer(g, categorie=rell)) and isinstance(forum_de(g, env, "entraide"), Forum)
    publier(g, g.membre(7), "boss")
    forum = forum_de(g, env, "entraide")
    post = forum.crees[-1]
    d = run(E.charger(1))
    assert d["mode"] == "" and post.fil.applied_tags == ["Boss", "Ouverte · Open"] and post.fil.membres == [7]
    run(E.rejoindre(interaction(g, g.membre(8)), 1))
    assert post.fil.applied_tags == ["Boss", "En cours · Ongoing"]
    env.langues["archive"] = "panne"
    assert run(E.fermer(g, 1, 7, "fermee", "🔒 fin"))
    assert run(E.charger(1))["jeton"] == "" and post.fil.locked and post.fil.archived, \
        "une panne d'enregistrement ne bloque pas la clôture"
    del env.langues["archive"]
    E._creations.clear()
    publier(g, g.membre(9), "aide")
    assert run(E.fermer_anciennes(g, "🔒 L'entraide déménage")) == 1
    fil = forum.crees[-1].fil
    assert fil.envois[-1][0] == "🔒 L'entraide déménage" and run(E.charger(2))["jeton"] == "jeton1"
    run(E.entretenir(g, maintenant=time.time() + 120))
    assert fil.id not in g.fils and post.fil.id not in g.fils, "les posts clos disparaissent"


def test_E12_langue_preference_sinon_discord_sinon_francais(env):
    g = Monde()
    m = g.membre(7)
    env.langues[7] = "en"
    assert run(E.langue_de(interaction(g, m))) == "en"
    E._langue = None
    i = interaction(g, m)
    i.locale = "en-US"
    assert run(E.langue_de(i)) == "en"
    i.locale = discord.Locale.french
    assert run(E.langue_de(i)) == "fr"

    async def casse(_i):
        raise RuntimeError("base indisponible")
    E._langue = casse
    assert run(E.langue_de(i)) == "fr"


# ─── Mise à niveau (lot 18 → nuit du 22/10) ──────────────────────────────────

def test_E13_mise_a_niveau_noms_bilingues_etiquettes_renommees_plus_de_badge_sos(env):
    g, entr, trade, p1, p2 = lot_18(env.conf)
    rell = g.categorie("· Rell Seas")
    faits = run(E.mettre_a_niveau(g, categorie=rell))
    assert faits == ["🛟help mis à niveau", "🤝trade mis à niveau"]
    assert (entr.name, trade.name) == ("🛟help", "🤝trade") and entr.category_id == trade.category_id == rell.id
    noms = [(t.name, str(t.emoji), t.id) for t in entr.available_tags]
    assert noms[0] == ("Aide · Help", "🛟", 500), "même étiquette (les posts la gardent), plus de badge 🆘"
    assert [n for n, _e, _i in noms] == [t.name for t in E.tags_du_salon("entraide")], "types puis statuts, sans doublon"
    assert noms[4] == ("Ouverte · Open", "🟢", 504)
    assert [t.name for t in trade.available_tags] == [t.name for t in E.tags_du_salon("trade")]
    droits = entr.overwrites_for(g.default_role)
    assert droits.attach_files and droits.send_messages is False, "@everyone gagne les captures, garde ses refus"
    assert p1.name == "📌 Publier une demande · Ask for help" and p2.name == "📌 Proposer un échange · Post a trade"
    assert "🇬🇧" in textes(p1.cartes[-1][1]["view"]), "le post épinglé est réécrit"
    assert all(k.get("sync_permissions") is False for k in entr.edits if "category" in k), "les droits restent"
    n, m = len(entr.edits), len(entr.permissions)
    assert run(E.mettre_a_niveau(g, categorie=rell)) == []
    assert (len(entr.edits), len(entr.permissions)) == (n, m), "relancer ne touche à rien"


# ─── Regroupement de la toute première installation ──────────────────────────

def _premiere_installation(env, membre_a_parle=False):
    g = Monde(forum=True)
    env.conf.update(aide_salon=g.nom("❓aide").id, suggestions_salon=g.nom("💡suggestions").id,
                    boosts_salon=g.nom("🚀boosts").id)
    vieille = g.categorie("🏴‍☠️ RELL SEAS")
    salons = {"orientation": g._salon(Texte, "🧭・orientation", {"category": vieille})}
    for cle, nom in (("aide", "🆘・aide"), ("boss", "⚔️・boss"), ("farm", "🌾・farm"), ("trade", "🤝・trade"),
                     ("chill", "🌴・chill")):
        salons[cle] = g._salon(Forum, nom, {"category": vieille, "available_tags": [
            discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in ANCIENS_STATUTS]})
    salons["discussion"] = g._salon(Texte, "💬・discussion", {"category": vieille})
    salons["discussion"].historique = [Message(salons["discussion"], 1, auteur_bot=not membre_a_parle)]
    panneaux = {}
    for cle in ("aide", "boss", "farm", "trade", "chill"):
        panneaux[cle] = g.nouveau_fil(salons[cle], f"📌 Publier une demande · {cle}").id
    env.conf.update(rs_actif=1, rs_categorie=vieille.id, rs_salons={k: s.id for k, s in salons.items()},
                    rs_panneaux=panneaux, rs_roles={})
    return g, vieille, salons


def test_E14_la_premiere_installation_devient_deux_forums(env):
    g, vieille, anciens = _premiere_installation(env)
    run(E._ecrire("INSERT INTO entraide_demandes(guild_id, zone, auteur_id, titre, salon_id, fil_id, cree, maj)"
                  " VALUES(1, 'boss', 7, 'Akuma', ?, ?, ?, ?)",
                  (anciens["boss"].id, g.nouveau_fil(anciens["boss"], "Akuma").id, int(time.time()), int(time.time()))))
    faits = run(E.migrer_v2(g))
    for cle in ("boss", "farm", "chill", "orientation", "discussion"):
        assert anciens[cle].supprime, cle
    assert vieille.supprime and len(g.categories) == 1, "plus de catégorie à part"
    entr, trade = anciens["aide"], anciens["trade"]
    assert (entr.name, entr.category_id, trade.category_id) == ("🛟help", g.commu.id, g.commu.id)
    assert [t.name for t in entr.available_tags] == [t.name for t in E.tags_du_salon("entraide")]
    assert env.conf["rs_salons"] == {"entraide": entr.id, "trade": trade.id} and env.conf["rs_v2"]
    assert run(E.charger(1))["statut"] == "fermee", "la demande d'un forum retiré est fermée proprement"
    post = g.fils[env.conf["rs_panneaux"]["entraide"]]
    assert post.name == "📌 Publier une demande · Ask for help" and "rs:n:farm" in ids(post.cartes[-1][1]["view"])
    assert any("retiré" in f for f in faits) and run(E.migrer_v2(g)) == [], "une seule fois"


def test_E15_une_discussion_ou_des_membres_ont_ecrit_n_est_pas_effacee(env):
    g, vieille, anciens = _premiere_installation(env, membre_a_parle=True)
    faits = run(E.migrer_v2(g))
    disc = anciens["discussion"]
    assert not disc.supprime and disc.category_id == g.commu.id, "rangée, pas effacée"
    assert any("gardé" in f for f in faits) and vieille.supprime


# ─── Branchement dans le bot ─────────────────────────────────────────────────

def test_E16_branche_dans_le_bot():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    for nom in ("BoutonNouvelle", "BoutonRejoindre", "BoutonCertifier", "BoutonFermer", "BoutonMiddleman"):
        assert f"entraide.{nom}" in src, f"{nom} doit être réenregistré au démarrage"
    arbre = ast.parse(src)
    sup = next(n for n in arbre.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_SUPERVISED_LOOP_NAMES")
    assert "entraide_task" in ast.literal_eval(sup.value)
    assert "'entraide':    lambda: entraide.EntraidePanelV2(self.u, self.g)" in src
    assert "await entraide.sur_depart(m)" in src and "ids_prives |= zones.ids_salons(c)" in src
    assert 'await _texte_refuse_pour(g, texte, "une demande", "Ta demande")' in src
    assert "langue=_langue_membre, archiver=_archiver_fil" in src and "entraide.set_installateur(zones.installer)" in src
    boucle = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "entraide_task")
    assert "g.owner_id in TETE_IDS and (not c.get('rs_installation_auto'))" in boucle
    assert boucle.index("db_set(g.id, 'rs_installation_auto'") < boucle.index("zones.installer(g)")
    assert boucle.index("entraide.migrer_v2(g)") < boucle.index("_installer_zones(g, c)"), \
        "la toute première installation est regroupée avant de poser les zones"
    assert "await entraide.entretenir(g)" in boucle and "await zones.entretenir(g)" in boucle
    archiver = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_archiver_fil")
    assert "transcript_store.save_html" in archiver and "titre=titre" in archiver
    assert all((RACINE / "visuels" / f"{k}.gif").is_file() for k in ("rs_port", "rs_entraide", "rs_trade"))
    assert not (RACINE / "visuels" / "rs_boss.gif").exists(), "plus de bandeau pour un salon qui n'existe plus"
    assert '"Entraide": "#84cc16"' in (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert json.dumps(sorted(E.ids_salons({"rs_salons": {"a": 5, "b": "6"}, "rs_categorie": 4}))) == "[4, 5, 6]"
