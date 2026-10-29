"""29/10/2026 : le savoir de RELL Seas (savoir.py) et les trois familles de questions — Jeu, Site, Studio."""
import re

import reponses_auto as R
import savoir as S


def test_SAVOIR_une_vraie_question_sur_un_terme_du_jeu_recoit_sa_fiche():
    for q, nom in (("c'est quoi Yahu ?", "Yahu"), ("comment avoir Flash Dash ?", "Flash Dash"),
                   ("what is the Sloop?", "Sloop"), ("c'est quoi le fruit Magma ?", "Magma")):
        f = S.trouver(q)
        assert f is not None and f["nom_en"] == nom, q


def test_SAVOIR_un_mot_courant_seul_ne_declenche_rien():
    for q in ("t'as vu la light ?", "c'est quoi ce fire ?", "gg les gars", "où est le poison ?"):
        assert S.trouver(q) is None, q
    assert S.trouver("c'est quoi le fruit Light ?") is not None      # avec son nom de famille, si


def test_SAVOIR_la_fiche_dit_d_ou_vient_ce_qu_elle_affirme():
    titre, corps, boutons = S.reponse(S.trouver("c'est quoi Yahu ?")["cle"], "fr")
    assert "Yahu" in titre and "**Confirmé**" in corps and "Vu dans « RELL Seas" in corps
    assert not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", titre + corps + "".join(l for l, _u in boutons))
    assert boutons[0][1].startswith("https://youtu.be/") and "?t=" in boutons[0][1]
    assert any(u.startswith("https://rellseas.fandom.com/wiki/") for _l, u in boutons)
    f = next(f for f in S.fiches().values() if f["statut"] == "a_verifier" and not f["preuves"])
    assert "pas encore montré officiellement" in S.reponse(f["cle"], "fr")[1]


def test_SAVOIR_trois_familles():
    assert set(S.DOMAINES) == {"jeu", "site", "studio"}
    assert S.domaine("jeu:fruit.magma") == "jeu" and S.domaine("aide") == "jeu"
    assert S.domaine("ticket") == "studio" and S.domaine("clan") == "studio"
    assert S.domaine(texte="comment me connecter au site ?") == "site"
    assert S.domaine(texte="comment ouvrir un ticket sur le discord ?") == "studio"
    assert S.domaine(texte="c'est quoi Yahu ?") == "jeu"


def test_SAVOIR_branche_dans_les_reponses_du_bot():
    assert R.classer("c'est quoi Yahu ?")[:2] == ("savoir", "jeu:" + S.trouver("c'est quoi Yahu ?")["cle"])
    assert R.classer("qui peut m'aider à battre Yahu ?")[0] == "aide"          # une demande d'aide reste une demande
    assert R.classer("comment ouvrir un ticket ?")[0] == "faq"
    assert R._libelle("jeu:" + S.trouver("c'est quoi Yahu ?")["cle"], "") == "Jeu · Yahu"


def test_SAVOIR_famille_site_le_wiki_et_la_vitrine():
    assert R.classer("y a un wiki ?")[:2] == ("savoir", "site:wiki")
    assert R.classer("où trouver des infos sur rell seas ?")[:2] == ("savoir", "site:wiki")
    assert R.classer("c'est quoi le lien du site du clan ?")[:2] == ("savoir", "site:vitrine")
    assert R.classer("comment rejoindre le clan ?")[:2] == ("faq", "clan")            # rien ne change pour le reste
    assert R.classer("le wiki est trop bien")[0] == ""                                 # pas une question
    titre, corps, boutons = S.reponse_site("wiki", "fr", "https://exemple.fr")
    assert boutons == [("Ouvrir le wiki", "https://exemple.fr/wiki")] and "vérifié" in corps
    assert S.reponse_site("wiki", "fr", "") is None                                    # sans adresse : pas de bouton qui ment
    assert S.domaine("site:wiki") == "site" and R._libelle("site:wiki", "") == "Site · Le wiki"


def test_SAVOIR_les_reponses_prennent_les_textes_relus():
    titre, corps, _b = S.reponse(S.trouver("comment avoir Flash Dash ?")["cle"], "fr")
    assert corps.startswith("Poster Agile") and "Dit dans" not in corps
    assert S.reponse(S.trouver("what is the Sloop?")["cle"], "en")[1].startswith("Ship shown in Movie 3")
