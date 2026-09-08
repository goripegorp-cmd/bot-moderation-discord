"""Approches prédatrices — le filtre qui doit attraper sans crier au loup.

═══════════════════════════════════════════════════════════════════════════════
LE CAS RÉEL QUI A DÉCLENCHÉ CE TRAVAIL (06/09/2026)
═══════════════════════════════════════════════════════════════════════════════
Message supprimé À LA MAIN par le propriétaire, dans le salon média, parce que
le bot ne l'avait pas vu :

    « Je suis disponible pour des rencontres coquine payant sans prise de tête
      écrit moi si tu es intéressé 💗🥰 »

    « C'est un exemple parmi des milliers qui peuvent exister. »

C'est une communauté Roblox : le public est en grande partie mineur.

═══════════════════════════════════════════════════════════════════════════════
⚠️ LA MOITIÉ BASSE DE CE FICHIER COMPTE PLUS QUE LA MOITIÉ HAUTE
═══════════════════════════════════════════════════════════════════════════════
« photo », « mp », « rencontre », « quel âge » sont le quotidien d'un serveur de
jeu. Une liste de mots interdits produirait des dizaines d'alertes fausses par
jour ; au bout d'une semaine le staff coupe le filtre, et le jour où un vrai
prédateur écrit, plus personne ne regarde. **Un filtre bruyant protège moins
qu'un filtre absent.**

Le corpus « DOIT SE TAIRE » est donc le vrai garde-fou : une seule alerte
dessus est un défaut grave, pas un détail de réglage.
"""
from __future__ import annotations

import ast
from pathlib import Path

import protection_mineurs as pm

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")

#  Le cas réel, mot pour mot.
CAS_REEL = ("Je suis disponible pour des rencontres coquine payant sans prise "
            "de tête écrit moi si tu es intéressé 💗🥰")

DOIT_ATTRAPER = [
    CAS_REEL,
    #  ⚠️ LE MÊME MESSAGE MAQUILLÉ. Ces annonces sont recopiées et retouchées
    #  en boucle : un filtre qui dépend d'un seul adjectif ne tient pas.
    "je suis disponible pour des rencontres payantes, ecris moi si tu es interesse",
    "dispo pour rencontres, pas serieux s abstenir, ecrivez moi en prive",
    "je vends mes photos, tarifs sur demande en mp",
    "escort girl dispo",
    "sugar daddy recherche",
    #  Sollicitation d'images intimes.
    "send nudes",
    "envoie une photo coquine",
    "on se fait un plan cul ?",
    #  Sites adultes / rencontre.
    "va voir mon onlyfans",
    #  L'isolement — la signature du grooming.
    "surtout ne le dis a personne, ca reste entre nous",
    "supprime ce message apres l'avoir lu",
    "don't tell anyone, it's our little secret",
    #  Faisceaux : chaque moitié est banale, l'ensemble ne l'est pas.
    "salut, tu peux m'envoyer une photo de toi ? mp moi",
    "viens en mp, envoie moi une photo de toi stp",
    "t'as quel age ? tu ressembles a quoi irl",
    "ajoute mon snap on parlera mieux, t'es trop mignonne",
    "tes parents sont la ? tu veux sortir avec moi",
    "montre moi ton visage, ajoute moi sur instagram",
    "how old are you ? are you alone",
    "tu habites ou ? t'es belle",
]

#  ⚠️ CHAQUE LIGNE EST UNE PHRASE QU'UN MEMBRE ÉCRIT VRAIMENT.
DOIT_SE_TAIRE = [
    "un petit jeu sans prise de tete pour ce soir ?",
    "je vends mes UGC, ecris moi si tu es interesse",
    "je suis dispo ce soir pour jouer",
    "regarde ma photo de mon UGC il est trop beau",
    "mp moi pour le trade svp",
    "quelqu'un veut faire un trade ? mp moi",
    "t'as quel age dans le jeu ?",
    "j'ai gagne mon premier limited, photo dans le salon",
    "on s'est rencontres sur Adopt Me il y a 2 ans",
    "ajoute moi sur roblox, mon pseudo c'est GoRP",
    "montre ton avatar il est stylé",
    "viens en vocal on joue ensemble",
    "je te kiff en tant qu'ami, t'es un bon joueur",
    "t'es belle ta tenue roblox",
    "quel age a ce jeu ?",
    "envoie la photo du bug s'il te plait",
    "supprime ce message il est en double",
    "c'est un secret, j'ai prepare une surprise pour l'event",
    "tu habites quelle region du serveur minecraft ?",
    "mon insta est dans ma bio si tu veux voir mes dessins",
    "on parle en prive pour organiser l'event du serveur",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Ce qu'il DOIT attraper
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_cas_reel_du_serveur_est_attrape():
    """Le message que le propriétaire a dû supprimer à la main."""
    r = pm.analyser(CAS_REEL)
    assert r["touche"] is True
    assert r["gravite"] == "forte", (
        "ce message ne devrait pas dépendre d'un faisceau : il est explicite")


def test_le_meme_message_MAQUILLE_est_attrape():
    """⚠️ SANS CE TEST, LE FILTRE NE TIENT QU'À UN ADJECTIF. Retirez
    « coquine » de l'annonce réelle et elle passait. Or c'est le même compte,
    le même but, et ces textes sont recopiés et retouchés en boucle."""
    r = pm.analyser("je suis disponible pour des rencontres payantes, "
                    "ecris moi si tu es interesse")
    assert r["touche"] is True and r["gravite"] == "forte"


def test_tout_le_corpus_hostile_est_attrape():
    rates = [t for t in DOIT_ATTRAPER if not pm.analyser(t)["touche"]]
    assert not rates, f"{len(rates)} cas manqués : {rates}"


def test_l_obfuscation_ne_sauve_pas():
    """« t3s p h o t o de toi » — chiffres, espaces intercalés. C'est la
    première parade, et elle est mécanique."""
    assert pm.analyser("t3s p h o t o de toi stp mp moi")["touche"] is True
    assert pm.analyser("s3nd nud3s")["touche"] is True


def test_l_apostrophe_ne_sauve_pas():
    """⚠️ QUATRE CAS RÉELS MANQUÉS AU CALIBRAGE à cause d'elle. « t'as quel
    âge » doit se lire comme « tas quel age »."""
    assert "tas quel age" in pm.normaliser("t'as quel âge")
    assert "tes belle" in pm.normaliser("t’es belle")   # apostrophe courbe


# ═══════════════════════════════════════════════════════════════════════════════
#  ⚠️ CE QU'IL NE DOIT SURTOUT PAS ATTRAPER — la partie qui compte
# ═══════════════════════════════════════════════════════════════════════════════

def test_AUCUNE_phrase_ordinaire_ne_declenche():
    """Une seule alerte ici est un défaut grave : c'est ce qui fait couper le
    filtre par le staff, et le rend inutile le jour où il servirait."""
    faux = [(t, pm.analyser(t)["motif"]) for t in DOIT_SE_TAIRE
            if pm.analyser(t)["touche"]]
    assert not faux, f"{len(faux)} faux positif(s) : {faux}"


def test_une_famille_FAIBLE_seule_ne_declenche_JAMAIS():
    """« mp moi » = un échange normal. « photo de toi » demandé par un ami du
    même âge aussi. C'est le CUMUL qui parle, jamais l'un des deux."""
    for seul in ("mp moi", "envoie moi une photo de toi", "t'as quel age",
                 "tu me plais", "sans prise de tete", "supprime ce message"):
        r = pm.analyser(seul)
        assert r["touche"] is False, (
            f"« {seul} » déclenche seul (familles : {r['motif']}) — c'est la "
            f"porte ouverte aux alertes en masse")


def test_le_mot_photo_seul_nest_dans_AUCUNE_famille_forte():
    """Dans un serveur Roblox, une photo est neuf fois sur dix une capture
    d'écran. « photo » nu dans une famille forte inonderait le staff."""
    assert pm.analyser("regarde cette photo")["touche"] is False
    assert pm.analyser("photo")["touche"] is False


def test_le_seuil_combine_est_bien_de_DEUX():
    corps = (RACINE / "protection_mineurs.py").read_text(encoding="utf-8")
    assert "SEUIL_COMBINE = 2" in corps, (
        "un seuil à 1 transformerait chaque famille faible en alerte")


# ═══════════════════════════════════════════════════════════════════════════════
#  Robustesse
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_filtre_est_FAIL_OPEN():
    """⚠️ UN DÉFAUT DE FILTRE NE DOIT RIEN BLOQUER. Fail-closed ici
    supprimerait les messages d'un serveur entier sur une exception."""
    for entree in (None, "", 12345, object()):
        r = pm.analyser(entree)          # type: ignore[arg-type]
        assert r["touche"] is False


def test_le_resume_cite_les_EXTRAITS_pas_seulement_les_familles():
    """Sans le texte exact, le staff ne peut pas juger — et un modérateur qui
    ne peut pas juger finit par tout ignorer."""
    r = pm.analyser(CAS_REEL)
    txt = pm.resume(r)
    assert "«" in txt and "»" in txt
    assert "rencontre" in txt.lower()


def test_un_texte_sain_ne_produit_AUCUN_resume():
    assert pm.resume(pm.analyser("bonjour tout le monde")) == ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Le câblage — « une fonction non appelée n'est pas opérationnelle »
# ═══════════════════════════════════════════════════════════════════════════════

def _on_message() -> str:
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_message":
            return ast.unparse(n)
    raise AssertionError("on_message introuvable")


def test_le_filtre_est_reellement_appele():
    corps = _on_message()
    assert "pmineurs.analyser(" in corps, "le module n'est jamais appelé"


def test_il_tourne_AUSSI_dans_les_tickets():
    """⚠️ UN TICKET EST UN SALON PRIVÉ — exactement le genre d'endroit où une
    approche se poursuit à l'abri des regards. `on_message` retourne tôt sur
    `is_ticket` : le filtre doit passer AVANT."""
    corps = _on_message()
    i_filtre = corps.index("pmineurs.analyser(")
    i_sortie = corps.index("if user_immune or is_ticket:")
    assert i_filtre < i_sortie, (
        "le filtre est placé après le retour sur les tickets : une approche "
        "en ticket ne serait jamais vue")


def test_le_staff_est_exempte():
    """Il doit pouvoir CITER un message pour instruire un dossier sans se
    faire sanctionner par le filtre qu'il utilise."""
    corps = _on_message()
    i = corps.index("pmineurs.analyser(")
    avant = corps[max(0, i - 400):i]
    assert "not user_immune" in avant


def test_le_palier_COMBINE_ne_sanctionne_pas_tout_seul():
    """⚠️ ACCUSER À TORT QUELQU'UN D'APPROCHE PRÉDATRICE EST UNE ACCUSATION
    GRAVE, publique et difficile à défaire. Sur un faisceau d'indices banals
    pris isolément, c'est un humain qui doit trancher — le bot supprime et
    alerte."""
    assert "'grooming_action_combine': 'alerte'" in SRC_BOT, (
        "le palier combiné sanctionne automatiquement par défaut")


def test_le_palier_FORT_coupe_tout_de_suite():
    """Sollicitation sexuelle, site adulte, rencontre tarifée : aucun usage
    innocent. Attendre un modérateur laisserait le message agir."""
    assert "'grooming_action': 'mute'" in SRC_BOT


def test_la_protection_est_ALLUMEE_par_defaut():
    """⚠️ CONTRAIREMENT À LA PLUPART DES PROTECTIONS DE CE DÉPÔT. Une
    protection de l'enfance qu'il faut penser à activer ne protège personne le
    jour où elle aurait servi."""
    assert "'anti_grooming': 1" in SRC_BOT


def test_le_message_est_supprime_et_le_staff_averti():
    corps = _on_message()
    i = corps.index("pmineurs.analyser(")
    bloc = corps[i:i + 2500]
    assert "msg.delete()" in bloc
    assert "send_log(" in bloc
    assert "pmineurs.resume(" in bloc, (
        "le journal ne cite pas les extraits : le staff ne pourra pas juger")
