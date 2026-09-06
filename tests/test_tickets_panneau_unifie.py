"""Le panneau de tickets UNIFIÉ — et le bouton mort qu'il a fallu réparer.

═══════════════════════════════════════════════════════════════════════════════
LA PANNE TROUVÉE EN OUVRANT LE DOSSIER (06/09/2026)
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire demandait un panneau unique « qui fonctionne, pas d'échec de
l'interaction ». En cherchant où brancher le menu, j'ai trouvé pourquoi il y
avait des échecs :

    TicketCreateButton porte custom_id=f"ticket_create_{pid}"
    sur une LayoutView(timeout=None)  →  bouton PERSISTANT
    …et AUCUN bot.add_view / add_dynamic_items ne le recaptait au démarrage.

Sur les seize gabarits dynamiques du fichier, un seul concernait les tickets
(`ticket_toggle_`). Conséquence : après CHAQUE redéploiement Railway — donc
plusieurs fois par jour — la vue en mémoire disparaît, plus personne n'écoute
ce custom_id, Discord attend trois secondes et affiche « Cette interaction a
échoué ». Le bouton « Créer un ticket » de tous les panneaux déjà postés était
mort jusqu'au prochain repostage.

⚠️ LE VÉRIFICATEUR DU DÉPÔT NE POUVAIT PAS LE VOIR : un custom_id construit en
f-string est classé « non vérifiable » et compté à part (11 dans son rapport).
C'est un angle mort de l'outil, pas un oubli de sa part — et c'est exactement
pour ça que les tests ci-dessous visent le NOM des gabarits, pas le compte.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import discord
import pytest

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _classe(nom: str) -> ast.ClassDef:
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.ClassDef) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _fonction(nom: str) -> str:
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _gabarits() -> dict:
    """{nom de classe: motif du template} pour tous les DynamicItem du fichier.

    On lit l'ARBRE plutôt que le texte : un `template=` en commentaire ou dans
    une chaîne ne doit pas compter comme un capteur.
    """
    out = {}
    for n in ast.walk(ARBRE):
        if not isinstance(n, ast.ClassDef):
            continue
        for kw in n.keywords:
            if kw.arg == "template" and isinstance(kw.value, ast.Constant):
                out[n.name] = kw.value.value
    return out


def _enregistres() -> set:
    """Les classes réellement passées à `bot.add_dynamic_items(...)`."""
    out = set()
    for n in ast.walk(ARBRE):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_dynamic_items"):
            for a in n.args:
                if isinstance(a, ast.Name):
                    out.add(a.id)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  LA RÉPARATION : le bouton « Créer un ticket » avait perdu son capteur
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_bouton_creer_un_ticket_a_ENFIN_un_capteur_au_boot():
    """⚠️ LE DÉFAUT D'ORIGINE. Sans ce gabarit, tout panneau posté avant le
    dernier redémarrage a un bouton mort — et Railway redémarre à chaque
    déploiement."""
    gab = _gabarits()
    assert "TicketCreateDynamic" in gab, (
        "aucun capteur pour `ticket_create_*` : le bouton des panneaux déjà "
        "postés reste mort après un redémarrage")
    motif = re.compile(gab["TicketCreateDynamic"])
    assert motif.match("ticket_create_support"), (
        f"le gabarit {gab['TicketCreateDynamic']!r} ne capte pas un "
        f"custom_id réel")
    assert "TicketCreateDynamic" in _enregistres(), (
        "le gabarit existe mais n'est jamais enregistré : classe morte")


def test_le_gabarit_ne_capte_pas_le_toggle_par_erreur():
    """⚠️ CONTRE-ÉPREUVE. `ticket_create_(?P<pid>.+)` et
    `ticket_toggle_(?P<pid>.+)` cohabitent : un gabarit trop large happerait
    les clics de l'autre, et le fondateur ouvrirait un ticket en croyant
    éteindre le panneau."""
    gab = _gabarits()
    creer = re.compile(gab["TicketCreateDynamic"])
    toggle = re.compile(gab["TicketToggleDynamic"])
    assert not creer.match("ticket_toggle_support")
    assert not toggle.match("ticket_create_support")


def test_le_bouton_historique_delegue_au_chemin_unique():
    """Un seul corps pour toutes les portes : sinon la blacklist, les horaires
    ou le maximum divergent — et c'est la blacklist qui se contourne en
    premier."""
    corps = ast.unparse(_classe("TicketCreateButton"))
    assert "_ticket_ouvrir(i, self.pid)" in corps
    #  Les règles ne doivent PAS être recopiées dans le bouton.
    for regle in ("blacklist", "_ticket_hours_allows", "count_user_tickets"):
        assert regle not in corps, (
            f"« {regle} » est réimplémenté dans le bouton : deux chemins qui "
            f"vont diverger")


def test_le_chemin_unique_applique_TOUTES_les_regles():
    """La contre-épreuve de la précédente : si le bouton ne les porte plus,
    le chemin extrait DOIT les porter."""
    corps = _fonction("_ticket_ouvrir")
    for regle in ("blacklist", "_ticket_hours_allows", "count_user_tickets",
                  "disabled"):
        assert regle in corps, f"« {regle} » a disparu du chemin d'ouverture"


# ═══════════════════════════════════════════════════════════════════════════════
#  LE PANNEAU UNIFIÉ
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_deux_composants_du_hub_sont_persistants_ET_enregistres():
    gab, enr = _gabarits(), _enregistres()
    for cls, cid in (("TicketHubOpenDynamic", "tickethub:open"),
                     ("TicketHubTypeDynamic", "tickethub:type")):
        assert cls in gab, f"{cls} n'est pas un DynamicItem"
        assert re.compile(gab[cls]).match(cid), (
            f"le gabarit de {cls} ne capte pas {cid}")
        assert cls in enr, (
            f"{cls} n'est jamais enregistré : après un redémarrage, le menu "
            f"affiche « Cette interaction a échoué »")


def test_les_deux_gabarits_du_hub_ne_se_marchent_pas_dessus():
    gab = _gabarits()
    ouvre = re.compile(gab["TicketHubOpenDynamic"])
    typ = re.compile(gab["TicketHubTypeDynamic"])
    assert not ouvre.match("tickethub:type")
    assert not typ.match("tickethub:open")


def test_les_vues_portent_le_composant_NU_pas_le_DynamicItem():
    """⚠️ LE DOUBLE AIGUILLAGE, ET C'EST LE PIÈGE LE PLUS SUBTIL DU LOT.

    `ViewStore.dispatch_view` (discord.py 2.7) appelle `dispatch_dynamic_items`
    PUIS cherche l'item dans la vue en mémoire : LES DEUX CHEMINS PARTENT.
    Mettre le DynamicItem lui-même dans la vue ferait donc exécuter son
    callback DEUX FOIS — deux formulaires, ou une réponse suivie d'une
    « interaction déjà répondue ». Avec `.item` (le composant nu), le doublon
    retombe sur le callback par défaut, qui ne fait rien.
    """
    hub = _fonction("_build_ticket_hub_view")
    assert "TicketHubOpenDynamic().item" in hub, (
        "la vue porte le DynamicItem : son callback partira deux fois")
    vue = ast.unparse(_classe("TicketHubTypeView"))
    assert ".item" in vue and "add_item(TicketHubTypeDynamic(types).item)" in vue


def test_un_seul_type_ne_fait_pas_choisir_dans_une_liste_dun_element():
    """Un clic pour rien est un risque d'expiration de plus — et le
    propriétaire a demandé que ce soit optimisé."""
    corps = ast.unparse(_classe("TicketHubOpenDynamic"))
    assert "len(types) == 1" in corps
    assert "_ticket_ouvrir(i, types[0][0])" in corps


def test_zero_type_ne_laisse_JAMAIS_un_bouton_mort():
    """Un bouton qui répond « rien à proposer » à chaque clic est le « menu qui
    ment » qu'interdit UI.md. Le panneau le dit à l'écran, et le bouton du
    panneau admin est grisé."""
    hub = _fonction("_build_ticket_hub_view")
    assert "Aucun type de ticket n'est disponible" in hub
    #  Et le clic, si un vieux panneau traîne, répond proprement.
    ouvre = ast.unparse(_classe("TicketHubOpenDynamic"))
    assert "Aucun type de ticket n'est disponible" in ouvre


def test_le_menu_lit_la_charge_de_linteraction_pas_ses_propres_options():
    """⚠️ SUR LE CHEMIN « RECAPTÉ APRÈS REDÉMARRAGE », l'instance vient d'être
    fabriquée par `from_custom_id` et ses options sont factices. Lire
    `self.item.values` y renverrait du vide — le menu paraîtrait cassé
    précisément dans le cas qu'on cherche à couvrir."""
    corps = ast.unparse(_classe("TicketHubTypeDynamic"))
    assert "i.data" in corps and "'values'" in corps
    assert "self.item.values" not in corps


def test_un_type_supprime_entre_l_affichage_et_le_clic_est_refuse():
    """Sinon on ouvre un ticket rattaché à un panneau qui n'existe plus : ni
    catégorie, ni staff, ni blacklist — un ticket fantôme."""
    corps = ast.unparse(_classe("TicketHubTypeDynamic"))
    assert "n'existe plus" in corps
    assert "ticket_panels" in corps, (
        "le type n'est pas revérifié dans la configuration au moment du clic")


def test_les_types_desactives_ne_sont_pas_proposes():
    """Le toggle fondateur doit garder son sens dans le menu unifié : un type
    éteint ne doit pas apparaître, sinon le clic se fait refuser après coup."""
    corps = _fonction("_types_tickets")
    assert "disabled" in corps


def test_l_ordre_des_types_est_STABLE():
    """⚠️ PAS DE TRI. Un tri par nom ferait sauter les entrées d'un menu à
    l'autre dès qu'un panneau est renommé — et un membre qui clique de mémoire
    ouvrirait le mauvais type."""
    corps = _fonction("_types_tickets")
    assert "sorted(" not in corps and ".sort(" not in corps


def test_chaque_option_a_une_description():
    """Un menu dont les lignes n'ont qu'un nom ne s'utilise pas : le membre ne
    sait pas lequel choisir, et ouvre au hasard."""
    corps = _fonction("_resume_type")
    assert "Ouvrir un ticket de ce type." in corps, (
        "pas de repli : une description vide donnerait une ligne muette")


# ═══════════════════════════════════════════════════════════════════════════════
#  Les composants se construisent VRAIMENT (pas seulement à la lecture)
# ═══════════════════════════════════════════════════════════════════════════════

def _construire(nom_classe):
    """Exécute la classe extraite de bot.py dans un espace de noms minimal.

    ⚠️ LA CI N'A PAS DE JETON DISCORD et aucun test du dépôt n'importe `bot`.
    On reprend le motif éprouvé de `test_sentinelle_instance.py` : le code
    exécuté est EXACTEMENT celui du dépôt.
    """
    ns = {"discord": discord, "Button": discord.ui.Button,
          "View": discord.ui.View, "_resume_type": lambda p: "desc"}
    exec(ast.unparse(_classe(nom_classe)), ns)      # noqa: S102 — code du dépôt
    return ns[nom_classe]


def test_le_bouton_du_hub_se_construit_sans_lever():
    """`DynamicItem.__init__` REFUSE un custom_id qui ne colle pas au gabarit
    (`ValueError`) et un composant non dispatchable (`TypeError`). Cette
    construction est donc une vraie vérification, pas une formalité."""
    b = _construire("TicketHubOpenDynamic")()
    assert b.item.custom_id == "tickethub:open"
    assert b.item.is_dispatchable()


def test_le_menu_du_hub_se_construit_avec_ET_sans_types():
    """Le chemin `from_custom_id` fabrique l'instance SANS types : un Select
    sans option lèverait, et le menu serait mort au premier redémarrage."""
    Cls = _construire("TicketHubTypeDynamic")
    vide = Cls()
    assert vide.item.custom_id == "tickethub:type"
    assert len(vide.item.options) >= 1, "un Select sans option est refusé"

    plein = Cls([("support", {"name": "Support"}),
                 ("clan", {"name": "Rejoindre un clan"})])
    assert [o.value for o in plein.item.options] == ["support", "clan"]
    assert [o.label for o in plein.item.options] == ["Support", "Rejoindre un clan"]


def test_le_menu_tient_la_limite_de_25_options_de_Discord():
    """⚠️ AU-DELÀ DE 25, DISCORD REFUSE LE MESSAGE ENTIER. Un serveur qui
    créerait trente types verrait le bouton échouer — pas le menu se tronquer.
    Mieux vaut couper que ne rien afficher."""
    Cls = _construire("TicketHubTypeDynamic")
    v = Cls([(f"p{k}", {"name": f"Type {k}"}) for k in range(40)])
    assert len(v.item.options) == 25


# ═══════════════════════════════════════════════════════════════════════════════
#  Le panneau doit être POSTABLE, sinon tout ça est du code mort
# ═══════════════════════════════════════════════════════════════════════════════

def test_l_admin_peut_reellement_poster_le_panneau_unifie():
    """« Une fonction non appelée n'est pas opérationnelle, même parfaite. »"""
    corps = ast.unparse(_classe("TicketMainPanelV2"))
    assert "tmpv2_hub" in corps, "aucun bouton pour poster le panneau unifié"
    assert "_cb_hub" in corps
    assert "SendPanelPaginatedView(self.u, self.g, HUB_PID)" in corps
    #  `ast.unparse` rend `disabled=(not panels)` en `disabled=not panels`.
    assert "disabled=not panels" in corps, (
        "le bouton reste cliquable sans aucun type : il posterait un panneau "
        "vide")


def test_l_envoi_distingue_le_hub_d_un_type():
    corps = ast.unparse(_classe("SendPanelPaginatedView"))
    assert "_build_ticket_hub_view" in corps
    assert "HUB_PID" in corps


def test_le_retour_depuis_le_hub_ne_montre_pas_un_editeur_vide():
    """`HUB_PID` n'est pas un panneau : ouvrir son éditeur afficherait une
    fiche vide et des boutons sans effet."""
    corps = ast.unparse(_classe("SendPanelPaginatedView"))
    assert "if self.pid == HUB_PID:" in corps


def test_le_hub_ne_casse_pas_les_panneaux_par_type():
    """⚠️ « Tu gardes les autres fonctionnalités qui sont là. » Les panneaux
    par type restent construits, postables et fonctionnels."""
    assert "_build_ticket_panel_view" in SRC
    corps = ast.unparse(_classe("SendPanelPaginatedView"))
    assert "_build_ticket_panel_view(i.guild, self.pid)" in corps
