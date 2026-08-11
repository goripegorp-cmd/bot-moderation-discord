"""Tests du VERDICT — la regle qui decide qui recoit quoi.

`activite.verdict` est une fonction PURE : elle prend deux mesures et une
configuration, elle rend un palier. C'est volontaire, et c'est ce qui rend ce
fichier possible — une regle qui ne se teste qu'avec un vrai serveur Discord
derriere n'est jamais testee, et c'est exactement le genre de regle qui finit
par expulser quelqu'un par erreur.

Les scenarios ci-dessous sont ceux DECRITS PAR LE PROPRIETAIRE, repris mot pour
mot dans les docstrings. Si l'un d'eux casse un jour, ce n'est pas le test qu'il
faut ajuster : c'est que le systeme ne fait plus ce qui a ete demande.
"""
import pytest

import activite


#  Une configuration de reference : les valeurs par defaut du systeme.
CONF = {
    "rappel": 7, "retrait": 14, "expulsion": 21,
    "presence": 3, "doux_max": 3,
}


def _mesure(silence, presents, fenetre=7, jugeable=True):
    return {"silence": silence, "presents": presents,
            "fenetre": fenetre, "jugeable": jugeable}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les scenarios exacts du proprietaire
# ═══════════════════════════════════════════════════════════════════════════════

def test_message_mardi_puis_silence_jusqu_au_ping():
    """« Ils envoient un message le mardi, mais ils sont inactifs le mercredi,
    jeudi, vendredi jusqu'au jour ou il y a le Ping. Alors le Ping va dire qu'il
    est inactif parce qu'il a pas ete actif. »

    Trois jours de silence, ce n'est pas assez pour le role AFK (seuil a 7).
    Mais une seule journee vue sur sept, c'est sous l'exigence de presence : il
    est nomme. C'est bien ce que demande le proprietaire — il APPARAIT au ping.
    """
    assert activite.verdict(_mesure(silence=3, presents=1), CONF) == "doux"


def test_message_le_samedi_apres_une_semaine_creuse():
    """« S'il envoie un message le samedi alors qu'il a pas ete actif depuis
    toute la semaine, ca va quand meme le prevenir en lui disant : attention, tu
    as ete actif que la. Essaye la prochaine fois d'etre un peu plus actif. »

    Silence de 1 jour : il vient de parler. Mais 1 jour vu sur 7 → prevention.
    """
    assert activite.verdict(_mesure(silence=1, presents=1), CONF) == "doux"


def test_le_malin_du_vendredi_finit_par_basculer():
    """« Si il est malin et qui se dit OK, le Ping pour dire quand on est AFK,
    c'est tous les vendredis, alors je vais faire expres d'envoyer un message
    tous les vendredis. […] Eh Ben non. »

    Son silence ne depasse jamais le seuil : compter les jours d'absence ne
    l'attrape PAS. C'est le compteur de rappels doux qui le fait — trois
    semaines de 1/7 d'affilee et il bascule au premier palier comme un absent.
    """
    m = _mesure(silence=2, presents=1)
    assert activite.verdict(m, CONF, doux_deja=0) == "doux"
    assert activite.verdict(m, CONF, doux_deja=1) == "doux"
    #  3e semaine consecutive : le contournement se referme.
    assert activite.verdict(m, CONF, doux_deja=2) == "rappel"
    assert activite.verdict(m, CONF, doux_deja=9) == "rappel"


def test_un_membre_present_assez_souvent_n_est_jamais_inquiete():
    """« S'il a envoye un certain nombre de messages et qu'il actif, OK, pas de
    souci. »"""
    assert activite.verdict(_mesure(silence=0, presents=7), CONF) == "actif"
    assert activite.verdict(_mesure(silence=1, presents=3), CONF) == "actif"
    #  Meme avec un historique de rappels doux : la presence redevenue bonne
    #  suffit, sinon une mauvaise passe condamnerait a vie.
    assert activite.verdict(_mesure(silence=1, presents=5), CONF,
                            doux_deja=9) == "actif"


# ═══════════════════════════════════════════════════════════════════════════════
#  Les paliers de silence
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_trois_paliers_tombent_au_bon_jour():
    """« Au bout d'une semaine, il a le premier role, 2 semaines […] il perdra
    tous ses roles […] 3 semaines, il sera kick. »"""
    assert activite.verdict(_mesure(6, 0), CONF) == "doux"     # pas encore
    assert activite.verdict(_mesure(7, 0), CONF) == "rappel"
    assert activite.verdict(_mesure(13, 0), CONF) == "rappel"
    assert activite.verdict(_mesure(14, 0), CONF) == "retrait"
    assert activite.verdict(_mesure(20, 0), CONF) == "retrait"
    assert activite.verdict(_mesure(21, 0), CONF) == "expulsion"
    assert activite.verdict(_mesure(400, 0), CONF) == "expulsion"


def test_le_plus_grave_gagne_toujours():
    """Un membre ne doit apparaitre que dans UNE liste.

    Sans cet ordre, quelqu'un a 21 jours de silence recevrait a la fois « tu es
    un peu juste » et « tu vas etre expulse » — deux messages contradictoires
    dans le meme salon.
    """
    #  Meme avec une presence parfaite (donnee incoherente, mais possible si la
    #  base est trafiquee), le silence l'emporte.
    assert activite.verdict(_mesure(21, 7), CONF) == "expulsion"
    assert activite.verdict(_mesure(14, 7), CONF) == "retrait"


# ═══════════════════════════════════════════════════════════════════════════════
#  Les garde-fous — ce qui protege les innocents
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_membre_trop_recent_n_est_jamais_accuse():
    """Arrive avant-hier, il n'a pas de semaine a montrer.

    Sans ce garde-fou, tout nouveau venu est « 1 jour sur 7 » des son
    inscription et recoit un rappel avant d'avoir dit bonjour — la meilleure
    facon de vider un serveur qu'on essayait de remplir.
    """
    assert activite.verdict(_mesure(1, 1, jugeable=False), CONF) == "actif"
    assert activite.verdict(_mesure(0, 0, jugeable=False), CONF) == "actif"


def test_un_silence_prolonge_compte_meme_chez_un_nouveau():
    """Le garde-fou protege de la PRESENCE, pas du SILENCE.

    Quelqu'un inscrit il y a trois semaines et qui n'a jamais rien fait n'est
    pas un « nouveau a menager » : c'est exactement le compte fantome que le
    systeme cherche. Le silence, lui, reste opposable.
    """
    assert activite.verdict(_mesure(21, 0, jugeable=False), CONF) == "expulsion"


def test_silence_inconnu_ne_declenche_rien():
    """On ne devine pas. Une mesure absente ne doit jamais valoir une accusation."""
    assert activite.verdict(_mesure(None, 0), CONF) == "actif"


def test_la_fenetre_reduite_ne_penalise_pas():
    """Suivi allume depuis 4 jours : la fenetre vaut 4, pas 7.

    Le verdict compare `presents` a l'exigence, pas a la fenetre. Un membre vu
    3 jours sur 4 est en regle, comme il le serait 3 jours sur 7.
    """
    assert activite.verdict(_mesure(1, 3, fenetre=4), CONF) == "actif"
    assert activite.verdict(_mesure(1, 2, fenetre=4), CONF) == "doux"


# ═══════════════════════════════════════════════════════════════════════════════
#  Coherence des reglages par defaut
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_defauts_sont_coherents_entre_eux():
    """Exiger plus de jours que la fenetre n'en contient rendrait TOUT LE MONDE
    fautif en permanence, y compris quelqu'un present chaque jour."""
    assert activite.SEUIL_PRESENCE_DEFAUT <= activite.FENETRE_PRESENCE_DEFAUT
    assert (activite.SEUIL_RAPPEL_DEFAUT
            < activite.SEUIL_RETRAIT_DEFAUT
            < activite.SEUIL_EXPULSION_DEFAUT)
    assert activite.DOUX_MAX_DEFAUT >= 1
    assert activite.ANCIENNETE_MINIMALE >= 1


def test_la_config_expose_bien_les_nouvelles_cles():
    for cle in ("activite_role_niveau1", "activite_role_niveau2",
                "activite_masquer_salons", "activite_fenetre",
                "activite_seuil_presence", "activite_doux_max",
                "activite_message_retour"):
        assert cle in activite.CLES_DEFAUT, cle


def test_le_systeme_reste_eteint_par_defaut():
    """Un systeme qui retire tous les roles ne s'allume jamais tout seul."""
    assert activite.CLES_DEFAUT["activite_enabled"] is False


def test_masquage_actif_par_defaut_mais_sans_role_il_ne_fait_rien():
    """Le masquage est a `True` par defaut, ce qui pourrait inquieter — mais
    sans rôle d'inactivite designe, il n'a rien a poser. Les deux ids valent 0."""
    assert activite.CLES_DEFAUT["activite_masquer_salons"] is True
    assert activite.CLES_DEFAUT["activite_role_niveau1"] == 0
    assert activite.CLES_DEFAUT["activite_role_niveau2"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Seuils par role : l'independance doit tenir aussi sur les nouvelles cles
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_role_peut_exiger_plus_de_presence_que_le_serveur():
    """Un role de clan peut demander 5 jours sur 7 la ou le serveur en veut 3."""
    cfg = {"activite_seuil_presence": 3, "activite_doux_max": 3,
           "activite_roles": {"42": {"presence": 5, "doux_max": 1}}}
    conf = activite.config_du_role(cfg, 42)
    assert conf["presence"] == 5
    assert conf["doux_max"] == 1
    assert "presence" in conf["_propres"]

    #  Un autre role, sans reglage propre, garde bien celui du serveur.
    autre = activite.config_du_role(cfg, 99)
    assert autre["presence"] == 3
    assert "presence" not in autre["_propres"]


def test_presence_exigeante_rend_le_verdict_plus_severe():
    """Le meme membre, juge par deux roles differents, n'a pas le meme sort."""
    m = _mesure(silence=1, presents=4)
    souple = dict(CONF, presence=3)
    exigeant = dict(CONF, presence=5)
    assert activite.verdict(m, souple) == "actif"
    assert activite.verdict(m, exigeant) == "doux"
