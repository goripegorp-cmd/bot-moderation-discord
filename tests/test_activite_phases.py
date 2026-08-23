"""Les 4 phases d'inactivité, le renvoi manuel, et le double ping — 20/08/2026.

DEMANDE DU PROPRIÉTAIRE, MOT POUR MOT
    « Fais en sorte que […] je puisse renvoyer le message qui pique tout le
      monde, assure toi bien que tout le monde ait bien un rôle spécifique qui
      puisse être mentionné quand ils sont inactifs. […] La première phase
      d'inactivité qui montre que les personnes sont pas trop là […] Le 2e, qui
      va donc enlever les fameux rôles et qui va les mettre en AFK […] Et le
      3e, ça va être qu'ils sont considérés comme des comptes abandonnés. »

CE QUI MANQUAIT
  · le palier « expulsion » — sa phase 3 — n'avait AUCUN rôle, donc il était
    impossible de le mentionner ;
  · il n'existait AUCUN bouton pour renvoyer les messages : l'envoi n'était
    atteignable que le jour configuré, une fois par semaine.

⚠️ ET UN DÉFAUT QUI EXISTAIT DÉJÀ — LE DOUBLE PING.
Les étiquettes sont GLOBALES au serveur, mais la boucle d'envoi tourne PAR RÔLE
SURVEILLÉ et le marqueur anti-doublon `derniere_semaine` l'est aussi. Dès qu'un
deuxième rôle est surveillé, le passage du dimanche poste deux messages
mentionnant LE MÊME rôle — et les deux marqueurs restent verts, puisqu'ils
protègent des groupes, pas une mention. Sur 959 personnes, c'est le pire échec
possible de cette fonction.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import activite
import activite_message as msgs
import activite_niveaux as niv
import activite_textes as txt

RACINE = Path(__file__).resolve().parent.parent
SRC_PASS = (RACINE / "activite_passage.py").read_text(encoding="utf-8")
SRC_PAN = (RACINE / "activite_panneau.py").read_text(encoding="utf-8")
SRC_ESC = (RACINE / "activite_escalade.py").read_text(encoding="utf-8")


def _corps(src: str, nom: str) -> str:
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable")


CFG4 = {"activite_role_doux": 10, "activite_role_niveau1": 11,
        "activite_role_niveau2": 12, "activite_role_abandon": 13}


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Les quatre phases ont chacune leur rôle
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_quatre_phases_ont_une_etiquette():
    assert niv.ids_etiquettes(CFG4) == {10, 11, 12, 13}
    assert set(niv._CLE_PAR_NIVEAU) == {0, 1, 2, 3}


def test_chaque_palier_a_un_nom_et_une_couleur():
    """⚠️ Un niveau absent de ces tables faisait créer un DOUBLON silencieux
    nommé « 💤 AFK · rôles retirés » — indiscernable du vrai dans la liste."""
    for n in niv._CLE_PAR_NIVEAU:
        assert n in niv._NOM_PAR_NIVEAU, f"palier {n} sans nom"
        assert n in niv._COULEUR_PAR_NIVEAU, f"palier {n} sans couleur"
    assert len(set(niv._NOM_PAR_NIVEAU.values())) == 4, "deux paliers homonymes"


def test_labandon_masque_mais_pas_le_peu_actif():
    """⚠️ LE PIÈGE CENTRAL. `poser_niveau` n'autorise qu'une étiquette : passer
    au palier 3 RETIRE celle du palier 2. Si l'abandon ne masquait pas, le
    membre le plus inactif du serveur — déjà dépouillé — serait le seul à
    retrouver l'accès complet."""
    assert niv.ids_afk(CFG4) == {11, 12, 13}
    assert 10 not in niv.ids_afk(CFG4), (
        "« peu actif » ne doit JAMAIS masquer : ces membres viennent d'écrire")


def test_la_phase_3_a_son_propre_titre():
    """Sans lui elle tombait dans le repli et s'affichait sous « 💤 Absents » —
    le titre d'une autre phase."""
    assert txt.T_ABANDON != txt.T_ABSENTS
    assert "·" in txt.T_ABANDON, "le titre doit rester bilingue"
    assert not txt.verifier_longueurs()


# ═══════════════════════════════════════════════════════════════════════════════
#  2. On ne masque pas quelqu'un qui n'a jamais été prévenu
# ═══════════════════════════════════════════════════════════════════════════════

def test_labandon_exige_un_palier_precedent():
    """⚠️ `verdict` teste l'expulsion EN PREMIER et le rationnement à 25 laisse
    des membres franchir 14 puis 21 jours sans être traités : ils atterrissent
    au palier 3 sans avoir jamais reçu de rappel. Leur retirer tout le serveur
    serait une sanction sans avertissement."""
    corps = _corps(SRC_ESC, "appliquer_abandon")
    assert "prealables" in corps
    assert "jamais_prevenus" in corps


def test_le_compteur_de_refus_est_remonte():
    """Sinon on remplace un masquage silencieux par un refus silencieux."""
    corps = _corps(SRC_PASS, "passage")
    assert "appliquer_abandon" in corps
    assert '"abandon"' in corps or "'abandon'" in corps


def test_le_budget_est_chaine_entre_les_deux_poses():
    """⚠️ Deux appels partant chacun de 240 s doubleraient le débit réel."""
    corps = _corps(SRC_PASS, "passage")
    assert '_ab["budget"]' in corps or "_ab['budget']" in corps


def test_labandon_passe_avant_le_doux():
    """Si le doux passait en premier, il brûlerait le budget sur des centaines
    de membres et l'étiquette d'abandon ne serait jamais posée."""
    corps = _corps(SRC_PASS, "passage")
    assert corps.index("appliquer_abandon") < corps.index("appliquer_doux")


def test_lexpulsion_nentre_pas_dans_le_quota_destructeur():
    """Les anciennetés d'expulsion ne décroissent JAMAIS : les compter
    rejouerait l'interblocage du 12/08, `quota_atteint` allumé pour toujours."""
    corps = _corps(SRC_PASS, "passage")
    ligne = [l for l in corps.splitlines() if "applicables = " in l]
    assert ligne and "expulsion" not in ligne[0]


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le double ping — le pire échec possible
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_role_nest_mentionne_quune_fois_par_passage():
    """⚠️ Le verrou intra-passage : deux rôles surveillés = deux groupes, mais
    une seule mention par étiquette."""
    corps = _corps(SRC_PASS, "envoyer_rappels")
    assert "_pingues" in corps
    assert "muet=" in corps


def test_le_marqueur_de_guilde_ferme_le_ping_entre_declencheurs():
    """Sans lui, un renvoi manuel le mercredi puis le rappel du dimanche
    pinguent deux fois la même semaine."""
    corps = _corps(SRC_PASS, "envoyer_rappels")
    assert "activite_derniere_semaine" in corps


def test_le_mode_muet_ne_retombe_pas_sur_la_liste():
    """⚠️ Passer simplement `role_ping=None` ferait mentionner jusqu'à 30
    membres NOMMÉMENT, avec `users=True` à l'envoi : on remplacerait un ping de
    rôle par trente pings de personnes."""
    class _M:
        id = 1

        @property
        def mention(self):
            return "<@1>"

    fiches = [{"member": _M(), "presents": 0, "fenetre": 3, "fenetre_voulue": 7,
               "jours": 0, "seuils": {"presence": 3}} for _ in range(40)]
    v = msgs.construire(fiches, palier="doux", muet=True)
    brut = str(v.to_components())
    assert "<@1>" not in brut, "le mode muet ne doit mentionner PERSONNE"
    assert "40" in brut, "il doit tout de même annoncer le nombre"


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le renvoi manuel ne détruit rien
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_renvoi_ne_purge_pas_quand_il_na_rien_a_poster():
    """⚠️ `remplacer` supprime AVANT de poster. Sans ce garde, cliquer
    « renvoyer » un jour calme viderait le salon en rapportant « 0 envoyé »."""
    corps = _corps(SRC_PASS, "envoyer_rappels")
    assert "purger_si_vide=not forcer" in corps


def test_remplacer_rend_ses_echecs():
    """Elle avalait ses exceptions et rendait un entier : un envoi refusé à
    100 % était indiscernable de « personne à relancer »."""
    corps = _corps((RACINE / "activite_message.py").read_text(encoding="utf-8"),
                   "remplacer")
    assert '"echecs"' in corps or "'echecs'" in corps
    assert "permissions_for" in corps, (
        "le bot doit vérifier qu'il peut poster AVANT de supprimer")


def test_lecran_de_renvoi_existe_et_reutilise_le_meme_chemin():
    """⚠️ Une seconde implémentation d'envoi divergerait au premier correctif."""
    assert "class ActiviteRenvoiPanelV2" in SRC_PAN
    corps = _corps(SRC_PAN, "_cb_envoyer")
    assert "envoyer_rappels" in corps
    assert "forcer=True" in corps


def test_le_bouton_de_renvoi_est_atteignable():
    assert 'custom_id="act_renvoi"' in SRC_PAN
    assert "_cb_renvoi" in SRC_PAN
    assert "ActiviteRenvoiPanelV2(self.u, self.g)" in SRC_PAN


def test_lecran_de_renvoi_dit_pourquoi_zero():
    """« 0 envoyé » sans motif ferait chercher une panne là où il n'y a
    personne à relancer."""
    corps = _corps(SRC_PAN, "_cb_envoyer")
    assert "personne à relancer" in corps or "motifs" in corps


def test_les_rangees_tiennent_dans_la_limite_de_discord():
    """Une ActionRow accepte 5 composants au plus."""
    for ligne in SRC_PAN.splitlines():
        if "ActionRow(" in ligne and "*" not in ligne:
            n = ligne.count(",") + 1 if "ActionRow(" in ligne else 0
            assert n <= 6, f"rangée trop chargée : {ligne.strip()[:80]}"
