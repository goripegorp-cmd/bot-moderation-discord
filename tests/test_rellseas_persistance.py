"""« Échec de l'interaction » sur /rellseas — corrigé le 23/08/2026.

LA PLAINTE, MOT POUR MOT
    « quand on interagit avec les boutons, ça ne marche pas. Il nous met échec
      de l'interaction, on peut rien faire dans ce menu »

LA CAUSE, PROUVÉE DANS discord.py 2.7.1
`ViewStore.dispatch_view` cherche l'item par message, puis sans message, et
s'il ne trouve rien fait `return` : AUCUN accusé de réception n'est envoyé.
Discord attend trois secondes et affiche « Échec de l'interaction ». Aucune
ligne de journal n'est écrite — c'est pour ça que rien ne se voyait.

Le panneau était une vue ÉPHÉMÈRE avec `timeout=600` et des callbacks attachés
en mémoire, enregistrée nulle part. Deux chemins y menaient : un redéploiement
(plusieurs par jour ici) et dix minutes d'inactivité.

⚠️ `timeout=None` NE SUFFIT PAS, ET C'EST LE PIÈGE.
`InteractionResponse.send_message` contient :
    if ephemeral and view.timeout is None:
        view.timeout = 15 * 60.0
Toute vue éphémère se voit imposer quinze minutes. Seul `bot.add_view` — qui
range la vue dans le créneau `message_id=None`, jamais purgé — survit.

DEUXIÈME CHEMIN MUET : `View._scheduled_task` fait `if not allow: return` sans
rien envoyer quand `interaction_check` rend `False`, et n'appelle PAS
`on_error`. Un refus sans réponse produit donc le même échec.

CE QUE ÇA IMPOSE : une vue enregistrée est UNE instance partagée par tout le
staff. Rien de personnel ne peut vivre sur `self`.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import discord
import pytest

import rellseas_panneau as panneau

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PAN = (RACINE / "rellseas_panneau.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Les deux faits de la bibliothèque — si l'un change, tout le design bouge
# ═══════════════════════════════════════════════════════════════════════════════

def test_discordpy_abandonne_silencieusement_une_vue_inconnue():
    """⚠️ LA CAUSE. Si un jour la bibliothèque répondait quelque chose, ce
    correctif deviendrait inutile — et ce test le dirait."""
    src = inspect.getsource(discord.ui.view.ViewStore.dispatch_view)
    assert "if item is None:" in src and "return" in src, (
        "dispatch_view ne rend plus la main en silence : revoir le correctif")


def test_une_vue_ephemere_ne_peut_pas_vivre_sans_enregistrement():
    """⚠️ LE PIÈGE. `timeout=None` seul est écrasé à 15 minutes."""
    src = inspect.getsource(discord.InteractionResponse.send_message)
    assert "view.timeout = 15 * 60.0" in src, (
        "discord.py n'impose plus 15 min aux vues éphémères — le commentaire "
        "du correctif doit être mis à jour")


def test_un_refus_de_check_ne_declenche_pas_on_error():
    """C'est pour ça qu'un `return False` muet produit l'échec visible."""
    src = inspect.getsource(discord.ui.view.BaseView._scheduled_task)
    assert "if not allow:" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le panneau est persistant, et enregistré
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_vue_est_persistante():
    v = panneau.RellseasGestionV2()
    assert v.timeout is None, "timeout=600 = panneau mort au redéploiement"


def test_le_squelette_porte_tous_les_custom_id():
    """`bot.add_view` n'inscrit que les composants présents à cet instant : un
    custom_id absent du squelette reste muet à vie."""
    v = panneau.RellseasGestionV2.squelette()
    trouves = set()

    def descendre(o):
        cid = getattr(o, "custom_id", None)
        if isinstance(cid, str):
            trouves.add(cid)
        for e in (getattr(o, "children", None) or []):
            descendre(e)
    descendre(v)
    attendus = {"rellseas_membres", "rellseas_resultats", "rellseas_g_chercher",
                "rellseas_g_donner", "rellseas_g_retirer",
                "rellseas_g_activite", "rellseas_g_vider"}
    manquants = attendus - trouves
    assert not manquants, f"custom_id absents du squelette : {manquants}"


def test_le_squelette_est_accepte_comme_vue_persistante():
    """discord.py refuse `add_view` sur une vue non persistante : on vérifie la
    condition exacte qu'il teste."""
    v = panneau.RellseasGestionV2.squelette()
    assert v.is_persistent(), (
        "add_view refuserait cette vue — timeout ou custom_id manquant")


def test_la_vue_est_enregistree_au_demarrage():
    """⚠️ LA LIGNE QUI RÉPARE. Sans elle, tout le reste est décoratif."""
    assert "bot.add_view(rellseas_ui.RellseasGestionV2.squelette())" in SRC_BOT


def test_la_vue_na_plus_didentite_dans_son_constructeur():
    """Une instance partagée par tout le staff ne peut pas porter un `self.u`."""
    sig = inspect.signature(panneau.RellseasGestionV2.__init__)
    assert list(sig.parameters) == ["self"], (
        f"le constructeur porte encore {list(sig.parameters)[1:]}")


def test_letat_vit_hors_de_la_vue():
    """Sinon la sélection d'un membre du staff écraserait celle d'un autre."""
    assert hasattr(panneau, "_SELECTIONS")
    corps = _corps("RellseasGestionV2")
    assert "self._membres" not in corps
    assert "self.g" not in corps and "self.u" not in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Un refus n'est jamais muet
# ═══════════════════════════════════════════════════════════════════════════════

def _corps(nom: str) -> str:
    for n in ast.walk(ast.parse(SRC_PAN)):
        if isinstance(n, ast.ClassDef) and n.name == nom:
            return ast.unparse(n)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable")


def test_le_check_repond_avant_de_refuser():
    """⚠️ `if not allow: return` — un refus sans réponse EST l'échec visible."""
    corps = _corps("RellseasGestionV2")
    bloc = corps.split("async def interaction_check")[1].split("async def")[0]
    i_envoi = bloc.index("send_message")
    i_refus = bloc.rindex("return False")
    assert i_envoi < i_refus, (
        "il faut répondre AVANT de rendre False, sinon Discord affiche l'échec")


def test_les_callbacks_navalent_plus_leurs_erreurs():
    """Les `try/except` muets court-circuitaient le filet `on_error` d'ui_v2 et
    transformaient chaque incident en bouton muet de plus."""
    corps = _corps("RellseasGestionV2")
    for nom in ("_cb_donner", "_cb_retirer", "_cb_vider", "_cb_membres"):
        bloc = corps.split(f"async def {nom}")[1].split("async def")[0]
        assert "except Exception" not in bloc, (
            f"{nom} avale encore ses erreurs : l'incident deviendra un bouton muet")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. La sélection s'accumule — la demande « ajout multiple »
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_menu_reaffiche_la_selection_en_cours():
    """⚠️ SANS `default_values`, LE CUMUL EST IMPOSSIBLE : le client ne renvoie
    que ce qui est coché, donc un menu rouvert vide écrase tout."""
    corps = _corps("RellseasGestionV2")
    assert "default_values=" in corps


def test_le_menu_est_tronque_a_25():
    """Plus de 25 `default_values` = HTTP 400 et le panneau ne s'affiche PLUS
    DU TOUT — panne totale au lieu d'un cumul."""
    corps = _corps("RellseasGestionV2")
    assert "ids[:MAX_MEMBRES]" in corps


def test_la_selection_fusionne_au_lieu_decraser():
    corps = _corps("RellseasGestionV2")
    bloc = corps.split("async def _cb_membres")[1].split("async def")[0]
    assert "hors_menu" in bloc, "les membres au-delà de 25 seraient perdus"


def test_les_doublons_sont_ecartes():
    """Deux passes de recherche peuvent proposer la même personne ; la compter
    deux fois fausserait le nombre affiché sur les boutons."""
    class _I:
        guild = type("G", (), {"id": 1})()
        user = type("U", (), {"id": 2})()
    panneau._poser(_I(), [5, 5, 7, 5])
    assert panneau._SELECTIONS[(1, 2)] == [5, 7]


# ═══════════════════════════════════════════════════════════════════════════════
#  5. La recherche par lettres
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_recherche_ignore_accents_et_casse():
    """« rené » doit se trouver en tapant « RENE »."""
    assert panneau._sans_accents("RENÉ") == panneau._sans_accents("rene")
    assert "rene" in panneau._sans_accents("Renée Dupont")


def test_la_recherche_existe_et_ouvre_une_modale():
    corps = _corps("RellseasGestionV2")
    assert "send_modal" in corps
    assert "class _ChercheModal" in SRC_PAN


def test_la_modale_a_son_propre_filet():
    """Sans lui, une erreur laisse l'utilisateur devant un formulaire figé."""
    corps = _corps("_ChercheModal")
    assert "async def on_error" in corps


def test_la_recherche_regarde_les_trois_noms():
    """Pseudo du serveur, nom global, nom de compte : chercher sur un seul
    raterait la moitié des gens."""
    corps = _corps("_ChercheModal")
    for champ in ("display_name", "global_name", "m.name"):
        assert champ in corps, f"la recherche ignore {champ}"


# ═══════════════════════════════════════════════════════════════════════════════
#  6. Coller un identifiant — le chemin qui marche toujours (24/08)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("saisie", [
    "123456789012345678",
    " 123456789012345678 ",
    "<@123456789012345678>",
    "<@!123456789012345678>",
])
def test_un_identifiant_est_reconnu_sous_toutes_ses_formes(saisie):
    """⚠️ On colle ce qu'on a sous la main. Exiger un nettoyage manuel, c'est
    remplacer une recherche qui échoue par une saisie qui échoue."""
    assert panneau._extraire_id(saisie) == 123456789012345678


@pytest.mark.parametrize("saisie", ["rell", "", "12", "abc123", "<@rell>"])
def test_ce_qui_nest_pas_un_identifiant_part_en_recherche(saisie):
    """Sinon « 12 » serait pris pour un identifiant et ne chercherait rien."""
    assert panneau._extraire_id(saisie) is None


def test_lidentifiant_est_essaye_avant_la_recherche():
    """Un identifiant est EXACT : il ne dépend ni du pseudo, ni des accents,
    ni du cache. C'est pour ça qu'il passe en premier."""
    corps = _corps("_ChercheModal")
    i_id = corps.index("_extraire_id")
    i_nom = corps.index("_sans_accents")
    assert i_id < i_nom


def test_un_membre_hors_cache_est_cherche_sur_discord():
    """⚠️ `get_member` ne lit QUE le cache : sans ce repli, un membre existant
    mais non chargé serait déclaré introuvable."""
    corps = _corps("_ChercheModal")
    assert "fetch_member" in corps


def test_la_recherche_dit_combien_de_membres_elle_a_fouilles():
    """Un cache vide rendrait « aucun résultat » pour TOUT — et on chercherait
    la panne dans la recherche au lieu du cache."""
    corps = _corps("_ChercheModal")
    assert "membres fouillés" in corps or "vus" in corps


def test_le_rendu_a_un_repli_si_ledition_echoue():
    """Un échec silencieux ici donne l'impression que la recherche « ne fait
    rien » — exactement la plainte du 24/08."""
    corps = _corps("_ChercheModal")
    assert "followup.send" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  7. Le raccourci « membres de ce salon » — les tickets (24/08)
# ═══════════════════════════════════════════════════════════════════════════════

class _FauxSalon:
    def __init__(self, membres):
        self.members = list(membres)


class _FauxM:
    def __init__(self, uid, bot=False):
        self.id, self.bot = uid, bot
        self.display_name = f"Membre{uid}"
        self.name = f"m{uid}"


class _FauxG:
    id = 1

    def get_member(self, uid):
        return _FauxM(uid)


class _FauxI:
    def __init__(self, salon):
        self.guild, self.channel = _FauxG(), salon
        self.user = type("U", (), {"id": 9})()


def test_un_ticket_propose_ses_participants():
    """⚠️ LA DEMANDE. Dans un ticket, les gens concernés sont déjà là."""
    i = _FauxI(_FauxSalon([_FauxM(1), _FauxM(2), _FauxM(3)]))
    assert [m.id for m in panneau._membres_du_salon(i)] == [1, 2, 3]


def test_les_bots_ne_sont_pas_proposes():
    i = _FauxI(_FauxSalon([_FauxM(1), _FauxM(2, bot=True)]))
    assert [m.id for m in panneau._membres_du_salon(i)] == [1]


def test_un_salon_public_ne_propose_rien():
    """⚠️ Sans ce plafond, le raccourci listerait tout le serveur et
    n'aiderait personne. Il n'apparaît QUE là où il sert."""
    i = _FauxI(_FauxSalon([_FauxM(x) for x in range(60)]))
    assert panneau._membres_du_salon(i) == []


def test_un_fil_rend_des_thread_members_et_on_les_resout():
    """⚠️ `Thread.members` rend des `ThreadMember`, PAS des `Member` : pas de
    `.display_name`, pas de `.bot`. On repasse par `guild.get_member`."""
    class _TM:
        def __init__(self, uid):
            self.id = uid
    i = _FauxI(_FauxSalon([_TM(4), _TM(5)]))
    trouves = panneau._membres_du_salon(i)
    assert [m.id for m in trouves] == [4, 5]
    assert all(hasattr(m, "display_name") for m in trouves)


def test_sans_salon_on_ne_plante_pas():
    i = _FauxI(None)
    assert panneau._membres_du_salon(i) == []


def test_le_raccourci_salon_est_enregistre_au_boot():
    """⚠️ Un custom_id absent du squelette n'est jamais capté après un
    redéploiement — le défaut qu'on vient de corriger."""
    v = panneau.RellseasGestionV2.squelette()
    trouves = set()

    def descendre(o):
        cid = getattr(o, "custom_id", None)
        if isinstance(cid, str):
            trouves.add(cid)
        for e in (getattr(o, "children", None) or []):
            descendre(e)
    descendre(v)
    assert "rellseas_salon" in trouves


def test_une_seule_mecanique_de_bascule():
    """Résultats de recherche et membres du salon doivent se comporter
    pareil : deux mécaniques divergeraient au premier correctif."""
    corps = _corps("RellseasGestionV2")
    assert corps.count("async def _basculer") == 1
    for cb in ("_cb_resultat", "_cb_salon"):
        bloc = corps.split(f"async def {cb}")[1].split("async def")[0]
        assert "_basculer" in bloc
