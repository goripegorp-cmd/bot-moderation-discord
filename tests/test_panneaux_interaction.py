"""« L'interaction a échoué » — le défaut signalé en production le 16/08.

LE SYMPTÔME, MOT POUR MOT
    « Le panel il est HS, quand je tape ça met échec de l'interaction. »

LA CAUSE
Discord donne 3 secondes pour acquitter une interaction. Aucun panneau de
`bot.py` ne faisait `defer` : chacun lisait la base AVANT de répondre. L'onglet
🎮 Veille Roblox est le plus lourd — quatre lectures (`veille.config`,
`news.config`, `veille.diagnostic`, `veille.actif`). Sur un démarrage à froid,
les 3 secondes tombent et Discord refuse tout.

LE CORRECTIF EST EN DEUX MOITIÉS INSÉPARABLES
  1. `_module_select` fait `defer()` avant de construire le panneau ;
  2. tous les panneaux passent par `_afficher_panneau()`, qui bascule sur
     `edit_original_response` quand la réponse est déjà consommée.

Sans (2), (1) casserait les onze onglets avec `InteractionResponded`. Ces tests
verrouillent les deux, et vérifient que le panneau Roblox s'affiche VRAIMENT
dans les deux états d'interaction.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import roblox_panneau as rp

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _fonction(nom: str):
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans bot.py")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Les deux moitiés du correctif sont là
# ═══════════════════════════════════════════════════════════════════════════════

def test_module_select_acquitte_avant_de_travailler():
    """Sans ce `defer`, tout panneau lent donne « L'interaction a échoué »."""
    corps = ast.unparse(_fonction("_module_select"))
    avant_fabrique = corps.split("fabrique = panneaux.get")[0]
    assert "response.defer()" in avant_fabrique, (
        "le defer doit venir AVANT la construction du panneau, pas après")


def test_le_helper_daffichage_existe_et_gere_les_deux_etats():
    corps = ast.unparse(_fonction("_afficher_panneau"))
    assert "is_done()" in corps
    assert "edit_original_response" in corps, (
        "sans lui, un panneau après defer lève InteractionResponded")
    assert "followup.send" in corps


def test_plus_aucun_panneau_ne_repond_en_direct():
    """Le chemin `response.edit_message(...view=self...)` doit avoir disparu.

    S'il revient, il reviendra APRÈS le defer de `_module_select` — donc il
    lèvera `InteractionResponded` et l'onglet sera muet.
    """
    interdit = "await interaction.response.edit_message(content=None, view=self"
    assert interdit not in SRC, (
        "un panneau répond encore en direct : il cassera après le defer")


def test_la_sync_par_guilde_existe_pour_la_propagation_immediate():
    """Une commande globale met jusqu'à 1 h à apparaître côté Discord.

    C'est ce qui faisait dire « je ne vois pas /rellseas » alors qu'elle était
    bien dans l'arbre. Le sync par guilde est instantané.
    """
    assert "copy_global_to(guild=" in SRC
    assert "await bot.tree.sync(guild=" in SRC
    assert "_sync_effectue" in SRC, (
        "la propagation par guilde ne doit partir que si un sync a eu lieu")


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le panneau Roblox s'affiche VRAIMENT, dans les deux états
# ═══════════════════════════════════════════════════════════════════════════════

class FausseReponse:
    def __init__(self, deja: bool):
        self._deja = deja
        self.appels = []

    def is_done(self):
        return self._deja

    async def defer(self, **kw):
        self._deja = True

    async def edit_message(self, **kw):
        assert not self._deja, "edit_message sur une interaction déjà acquittée"
        self.appels.append(kw)
        self._deja = True

    async def send_message(self, *a, **kw):
        assert not self._deja, "send_message sur une interaction déjà acquittée"
        self.appels.append(kw)
        self._deja = True


class FausseInteraction:
    def __init__(self, deja: bool = False):
        self.response = FausseReponse(deja)
        self.editions = []
        parent = self

        class _F:
            async def send(self, *a, **kw):
                parent.editions.append(kw)

        self.followup = _F()

    async def edit_original_response(self, **kw):
        self.editions.append(kw)

    @property
    def affiche(self) -> bool:
        return bool(self.response.appels or self.editions)


class FauxSalon:
    def __init__(self, cid):
        self.id = cid
        self.name = f"salon-{cid}"
        self.mention = f"<#{cid}>"


class FauxGuild:
    id = 1
    name = "Serveur"
    icon = None

    def get_channel(self, cid):
        return FauxSalon(cid) if cid else None


class FauxUser:
    id = 1
    display_name = "proprio"


@pytest.fixture
def veille_branchee(monkeypatch):
    """Remplace les quatre lectures que fait le panneau. Ce sont ELLES qui
    faisaient dépasser les 3 secondes en production."""
    async def _cfg(gid):
        return {"roblox_veille_enabled": True, "roblox_salon_nouveautes": 11,
                "roblox_salon_bascules": 12, "roblox_salon_surveiller": 13,
                "roblox_news_salon": 14, "roblox_veille_amorcee": True}

    async def _diag():
        return {"sources": [{"source": "catalogue", "code": 200, "echecs": 0}],
                "articles_connus": 110}

    async def _actif(gid):
        return True

    monkeypatch.setattr(rp.veille, "config", _cfg)
    monkeypatch.setattr(rp.news, "config", _cfg)
    monkeypatch.setattr(rp.veille, "diagnostic", _diag)
    monkeypatch.setattr(rp.veille, "actif", _actif)
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


def _compter(payload) -> int:
    n = 0
    for c in payload:
        n += 1
        n += _compter(c.get("components", []) or [])
    return n


@pytest.mark.asyncio
@pytest.mark.parametrize("deja_acquittee", [False, True])
async def test_le_panneau_roblox_saffiche_dans_les_deux_etats(
        veille_branchee, deja_acquittee):
    """`True` est le cas RÉEL depuis le correctif : `_module_select` defer."""
    vue = rp.RobloxPanelV2(FauxUser(), FauxGuild())
    i = FausseInteraction(deja=deja_acquittee)

    await vue.render_to(i)

    assert i.affiche, "le panneau ne s'est pas affiché"
    payload = vue.to_components()
    assert payload, "une vue sans composant est refusée par Discord"
    assert _compter(payload) <= 40, "40 composants maximum — au-delà, HTTP 400"
    assert vue.has_components_v2(), "Components V2 attendu"


@pytest.mark.asyncio
async def test_le_panneau_roblox_reste_sous_la_limite_avec_un_message_detat(
        veille_branchee):
    """Le compte-rendu de relevé ajoute un bloc : il ne doit pas faire déborder."""
    vue = rp.RobloxPanelV2(FauxUser(), FauxGuild())
    vue._dernier = vue._compte_rendu(
        30, 2, {"sans_salon": 1, "salon_introuvable": 1, "age": 3,
                "seuil": 2, "deja": 4, "envoi": 1}, ["555"])

    await vue.render_to(FausseInteraction())

    assert _compter(vue.to_components()) <= 40


@pytest.mark.asyncio
async def test_le_panneau_roblox_souvre_meme_si_le_diagnostic_casse(monkeypatch):
    """Fail-open sur la disponibilité : une panne de base ne ferme pas l'écran."""
    async def _boum(*a, **kw):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(rp.veille, "config", _boum)
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)

    vue = rp.RobloxPanelV2(FauxUser(), FauxGuild())
    i = FausseInteraction()
    await vue.render_to(i)

    #  Il doit se passer QUELQUE CHOSE — panneau ou message d'erreur — jamais
    #  un silence, qui donnerait « L'interaction a échoué » côté client.
    assert i.affiche or i.response.appels
