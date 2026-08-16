"""`/rellseas` — la commande, et surtout sa garde.

Le propriétaire a posé la condition mot pour mot : « contrôler la permission
DANS la commande, pas seulement à l'affichage ». Un panneau qui masque un
bouton n'empêche personne de taper la commande — ces tests vérifient que
chacune des trois sous-commandes appelle bien la garde.

Ils vérifient aussi la promesse de mesure : l'activité passe par
`activite.presence()`, pas par un second compteur. C'est ce doublon qui avait
été retiré le 12/08, avec un message privé qui annonçait un retrait de rôle que
le bot ne faisait jamais.

⚠️ Ces tests n'importent PAS bot.py : la CI ne fournit pas de DISCORD_TOKEN, et
le module en exige un à l'import. Le câblage se vérifie donc par `ast`, ce qui
suffit largement — on cherche des appels, pas un comportement d'exécution.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import rellseas_panneau as panneau

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)

SOUS_COMMANDES = ["rellseas_donner", "rellseas_retirer", "rellseas_activite"]


def _fonction(nom: str):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _appels(noeud) -> set[str]:
    out = set()
    for n in ast.walk(noeud):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  1. La garde est DANS la commande
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("nom", SOUS_COMMANDES)
def test_chaque_sous_commande_controle_la_permission(nom):
    assert "_rellseas_autorise" in _appels(_fonction(nom)), (
        f"{nom} ne vérifie pas la permission — un panneau n'est pas une garde")


def test_la_commande_est_enregistree_dans_larbre():
    """Une commande définie mais jamais ajoutée à l'arbre n'existe pas.

    C'est la même famille de défaut que `@tasks.loop` sans `.start()` : le code
    est parfait, il ne s'exécute jamais.
    """
    assert "bot.tree.add_command(rellseas_group)" in SRC


@pytest.mark.parametrize("nom", SOUS_COMMANDES)
def test_chaque_sous_commande_est_bien_accrochee_au_groupe(nom):
    deco = [ast.unparse(d) for d in _fonction(nom).decorator_list]
    assert any("rellseas_group.command" in d for d in deco), (
        f"{nom} n'est pas accrochée au groupe : elle ne sera jamais proposée")


def test_la_section_rellseas_ouvre_son_panneau():
    assert '("rellseas",' in SRC, "section absente du menu /configure"
    assert "'rellseas':    lambda: rellseas_ui.RellseasPanelV2" in SRC, (
        "section proposée au menu mais sans panneau — « Section indisponible »")


# ═══════════════════════════════════════════════════════════════════════════════
#  2. La mesure d'activité est celle du serveur, pas une seconde
# ═══════════════════════════════════════════════════════════════════════════════

def test_lactivite_reutilise_presence_et_ne_compte_rien_elle_meme():
    corps = _fonction("rellseas_activite")
    appels = _appels(corps)

    assert "presence" in appels, (
        "la vérification doit passer par activite.presence() — c'est la "
        "condition posée après le doublon retiré le 12/08")
    #  Un second compteur se reconnaîtrait à une requête SQL directe.
    assert "execute" not in appels, (
        "aucune requête directe ici : le comptage appartient au système "
        "d'activité, et à lui seul")


def test_la_fenetre_est_bien_dune_semaine():
    corps = ast.unparse(_fonction("rellseas_activite"))
    assert "activite_fenetre" in corps and "7" in corps, (
        "« sur une semaine au propre » — la fenêtre doit être forcée à 7 jours")


def test_les_gestes_refuses_par_discord_ne_sont_pas_annonces():
    """Le défaut qui avait fait retirer l'ancienne escalade : annoncer un
    retrait de rôle que le bot ne faisait pas."""
    for nom in ("rellseas_donner", "rellseas_retirer"):
        corps = ast.unparse(_fonction(nom))
        assert "Forbidden" in corps, f"{nom} n'attrape pas le refus de Discord"
        assert "Rien n'a été fait" in corps, (
            f"{nom} doit dire explicitement que rien n'a été fait")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. La lecture du réglage — fail-closed
# ═══════════════════════════════════════════════════════════════════════════════

def test_roles_autorises_tolere_les_formats_anciens():
    assert panneau.roles_autorises({"rellseas_roles_autorises": [1, 2]}) == [1, 2]
    assert panneau.roles_autorises({"rellseas_roles_autorises": ["3", "4"]}) == [3, 4]
    assert panneau.roles_autorises({"rellseas_roles_autorises": 5}) == [5]
    assert panneau.roles_autorises({"rellseas_roles_autorises": "6"}) == [6]


def test_roles_autorises_ignore_ce_quil_ne_comprend_pas():
    """Fail-closed : on n'autorise jamais par accident."""
    sale = {"rellseas_roles_autorises": [1, "abc", None, {}, -5, 0, "7"]}
    assert panneau.roles_autorises(sale) == [1, 7]


def test_roles_autorises_sur_config_vide():
    assert panneau.roles_autorises({}) == []
    assert panneau.roles_autorises({"rellseas_roles_autorises": None}) == []


def test_la_garde_est_fail_closed_si_la_config_est_illisible():
    """Une erreur de base ne doit jamais ÉLARGIR un droit."""
    corps = ast.unparse(_fonction("_rellseas_autorise"))
    #  Le `except` autour de la lecture de config doit rendre False.
    assert "return False" in corps
    apres_except = corps.split("except", 1)[1]
    assert "return False" in apres_except, (
        "sur config illisible, la garde doit refuser, pas laisser passer")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le panneau se construit
# ═══════════════════════════════════════════════════════════════════════════════

class FauxRole:
    def __init__(self, rid=7):
        self.id = rid
        self.name = "Rellseas"
        self.mention = f"<@&{rid}>"


class FauxGuild:
    id = 1234
    name = "Serveur"
    icon = None

    def get_role(self, rid):
        return FauxRole(rid) if rid else None

    def get_channel(self, cid):
        return None


class FauxUser:
    id = 42
    display_name = "proprio"


class FausseReponse:
    def __init__(self):
        self.appels = []
        self._done = False

    def is_done(self):
        return self._done

    async def edit_message(self, **kw):
        self.appels.append(kw)
        self._done = True

    async def send_message(self, *a, **kw):
        self.appels.append(kw)
        self._done = True


class FausseInteraction:
    def __init__(self):
        self.response = FausseReponse()

    async def edit_original_response(self, **kw):
        self.response.appels.append(kw)


@pytest.mark.asyncio
async def test_le_panneau_se_construit_et_se_serialise():
    async def _cfg(gid):
        return {"rellseas_role": 7, "rellseas_roles_autorises": [11, 12]}

    panneau.setup(cfg=_cfg, db_set=None, log=lambda *a: None)
    vue = panneau.RellseasPanelV2(FauxUser(), FauxGuild())
    i = FausseInteraction()
    await vue.render_to(i)

    payload = vue.to_components()
    assert payload, "une vue sans composant est refusée par Discord"
    assert vue.has_components_v2
    assert i.response.appels, "le panneau devait s'afficher"


@pytest.mark.asyncio
async def test_le_panneau_souvre_meme_si_la_config_est_cassee():
    """Fail-open sur la disponibilité (UI.md §6) : un panneau doit s'ouvrir."""
    async def _cfg(gid):
        raise RuntimeError("base indisponible")

    panneau.setup(cfg=_cfg, db_set=None, log=lambda *a: None)
    vue = panneau.RellseasPanelV2(FauxUser(), FauxGuild())
    i = FausseInteraction()
    await vue.render_to(i)

    assert i.response.appels, "le panneau devait s'ouvrir malgré la panne"
