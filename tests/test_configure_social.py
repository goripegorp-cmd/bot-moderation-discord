"""L'onglet « Réseaux sociaux » de /configure — atteignable, et honnête.

CE QUI ÉTAIT LE CAS
-------------------
Le système social tourne (YouTube RSS, RSSHub pour X/TikTok/Instagram) et
`SocialMediaPanelV2` existait déjà, complet, branché sur le VRAI manager par
`set_social_manager`. Mais il n'était plus atteignable : son seul point
d'entrée était `/admin`, commande retirée. Un panneau orphelin, pas un panneau
manquant — et son « ◀️ Retour » ramenait vers ce même écran mort.

CE QUE CES TESTS PROUVENT
-------------------------
1. la section existe ET se résout vers un panneau — le défaut classique étant
   une entrée de menu sans résolution, c'est-à-dire un menu qui ment ;
2. le retour injecté par bot.py remplace bien la destination morte ;
3. `_rendre` supporte une interaction DÉJÀ répondue — c'est ce qui cassait
   l'écran après un ajout ou une suppression d'abonnement ;
4. le panneau se construit et se sérialise vraiment, sous les limites de l'API.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import admin_panels_v2 as panels
import social_media

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _restaurer_etat_global(tmp_path, monkeypatch):
    """Le manager et le retour sont des globales du module : on les rend.

    Sans ça, un test qui installe un manager manuel le laisse en place pour
    toute la session pytest — et le suivant teste autre chose que ce qu'il
    croit.

    ⚠️ ET SURTOUT : `add_subscription` ÉCRIT SUR LE DISQUE. Sans la redirection
    de `DATA_DIR`, ce fichier de test crée un vrai `data/social/1234_subs.json`
    dans le dépôt — un abonnement fictif déposé au milieu des données du bot,
    qui part au commit suivant. C'est arrivé une fois ; d'où cette ligne.
    """
    monkeypatch.setattr(social_media, "DATA_DIR", tmp_path)
    manager, retour = panels._global_manager, panels._retour_configure
    yield
    panels._global_manager, panels._retour_configure = manager, retour


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Parité menu ↔ résolution, lue dans bot.py sans l'importer
#
#  ⚠️ Ce test vaut pour TOUTES les sections, pas seulement « social » : une
#  entrée ajoutée au select sans sa fabrique donne « Section indisponible »,
#  et l'inverse donne du code mort. Les deux listes doivent coïncider.
# ═══════════════════════════════════════════════════════════════════════════════

def _lire_bot() -> ast.Module:
    return ast.parse(Path(RACINE / "bot.py").read_text(encoding="utf-8"))


def _sections_du_select(arbre: ast.Module) -> list[str]:
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Assign) and n.targets
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_CONFIG_SECTIONS"):
            return [t.elts[0].value for t in n.value.elts]
    raise AssertionError("_CONFIG_SECTIONS introuvable dans bot.py")


def _sections_resolues(arbre: ast.Module) -> list[str]:
    for n in ast.walk(arbre):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_module_select":
            for sous in ast.walk(n):
                if isinstance(sous, ast.Dict) and sous.keys:
                    cles = [k.value for k in sous.keys
                            if isinstance(k, ast.Constant)]
                    if "roblox" in cles:  # le dict des panneaux, pas un autre
                        return cles
    raise AssertionError("le dict des panneaux est introuvable")


def test_chaque_section_du_menu_ouvre_un_panneau():
    arbre = _lire_bot()
    menu = _sections_du_select(arbre)
    resolues = _sections_resolues(arbre)

    manquantes = [s for s in menu if s not in resolues]
    orphelines = [s for s in resolues if s not in menu]

    assert not manquantes, (
        f"section(s) proposée(s) au menu mais sans panneau : {manquantes} — "
        f"cliquer dessus donne « Section indisponible »")
    assert not orphelines, f"panneau(x) que rien n'ouvre : {orphelines}"


def test_la_section_reseaux_sociaux_est_bien_la():
    arbre = _lire_bot()
    assert "social" in _sections_du_select(arbre)
    assert "social" in _sections_resolues(arbre)


def test_bot_injecte_le_retour_du_panneau_social():
    """Sans cette injection, « Retour » mène à l'écran mort de `/admin`."""
    src = Path(RACINE / "bot.py").read_text(encoding="utf-8")
    assert "panels2026.set_retour(_retour_vers_configure)" in src


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le retour va bien vers /configure
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_retour_injecte_remplace_la_destination_morte():
    vus = []

    async def _retour(owner, guild, interaction):
        vus.append((owner, guild, interaction))

    panels.set_retour(_retour)
    try:
        await panels._revenir("proprio", "serveur", "interaction")
    finally:
        panels.set_retour(None)

    assert vus == [("proprio", "serveur", "interaction")]


# ═══════════════════════════════════════════════════════════════════════════════
#  3. `_rendre` survit à une interaction déjà répondue
# ═══════════════════════════════════════════════════════════════════════════════

class FausseReponse:
    def __init__(self, deja: bool):
        self._deja = deja
        self.appels = []

    def is_done(self):
        return self._deja

    async def edit_message(self, **kw):
        if self._deja:
            raise AssertionError("edit_message sur une interaction déjà répondue")
        self.appels.append(("edit_message", kw))
        self._deja = True

    async def send_message(self, *a, **kw):
        if self._deja:
            raise AssertionError("send_message sur une interaction déjà répondue")
        self.appels.append(("send_message", kw))
        self._deja = True


class FausseInteraction:
    """⚠️ Porte TOUT ce que le vrai porte sur ce chemin : `response`,
    `followup`, et `edit_original_response`."""

    def __init__(self, deja_repondue: bool = False):
        self.response = FausseReponse(deja_repondue)
        self.suites = []
        self.editions = []

        parent = self

        class _Followup:
            async def send(self, *a, **kw):
                parent.suites.append(kw)

        self.followup = _Followup()

    async def edit_original_response(self, **kw):
        self.editions.append(kw)


@pytest.mark.asyncio
async def test_rendre_edite_quand_linteraction_est_neuve():
    i = FausseInteraction(deja_repondue=False)
    await panels._rendre("vue", i, True)
    assert i.response.appels[0][0] == "edit_message"


@pytest.mark.asyncio
async def test_rendre_passe_par_edit_original_quand_deja_repondu():
    """LE cas qui cassait : confirmation envoyée, puis réaffichage."""
    i = FausseInteraction(deja_repondue=True)
    await panels._rendre("vue", i, True)
    assert i.editions, "il fallait passer par edit_original_response"


@pytest.mark.asyncio
async def test_rendre_passe_par_followup_en_envoi_quand_deja_repondu():
    i = FausseInteraction(deja_repondue=True)
    await panels._rendre("vue", i, False)
    assert i.suites, "il fallait passer par followup.send"


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le panneau se construit et se sérialise pour de vrai
# ═══════════════════════════════════════════════════════════════════════════════

class FauxSalon:
    def __init__(self, cid=99):
        self.id = cid
        self.name = "annonces"
        self.mention = f"<#{cid}>"


class FauxGuild:
    """⚠️ `get_channel` OBLIGATOIRE — un `_Guild` sans lui avait rendu la CI
    rouge un jour sur sept."""

    def __init__(self):
        self.id = 1234
        self.name = "Serveur de test"
        self.icon = None

    def get_channel(self, cid):
        return FauxSalon(cid) if cid else None


class FauxUser:
    id = 781205382923288593
    display_name = "proprio"


@pytest.mark.asyncio
async def test_le_panneau_social_se_construit_et_se_serialise():
    mgr = social_media.SocialMediaManager()
    for p in social_media.Platform:
        mgr.register_adapter(social_media.ManualAdapter(p))
    await mgr.add_subscription(
        guild_id=1234, platform=social_media.Platform.YOUTUBE,
        handle="MrBeast", target_channel_id=99, display_name="MrBeast")
    panels.set_social_manager(mgr)

    vue = panels.SocialMediaPanelV2(FauxUser(), FauxGuild())
    i = FausseInteraction()
    await vue.render_to(i)

    payload = vue.to_components()
    assert payload, "une vue sans composant est refusée par Discord"
    assert vue.has_components_v2(), "Components V2 attendu"
    assert i.response.appels, "le panneau devait s'afficher"


@pytest.mark.asyncio
async def test_le_panneau_previent_quand_le_releve_nest_pas_branche():
    """Un manager non injecté liste des abonnements que personne n'interroge.

    L'écran a l'air normal et il est faux : il doit le DIRE.
    """
    mgr = social_media.SocialMediaManager()
    for p in social_media.Platform:
        mgr.register_adapter(social_media.ManualAdapter(p))
    panels.set_social_manager(mgr)

    assert panels.manager_injecte() is False

    vue = panels.SocialMediaPanelV2(FauxUser(), FauxGuild())
    await vue.render_to(FausseInteraction())
    texte = str(vue.to_components())

    assert "n'est pas branché" in texte
