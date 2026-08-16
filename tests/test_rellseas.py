"""`/rellseas` — une commande, un panneau, des lots.

FORME DEMANDÉE LE 16/08
    « Je veux que l'utilisateur utilise la commande officielle, et qu'à
    l'intérieur il y ait un panneau […] Il peut en donner à plusieurs personnes
    d'un coup. Retirer à plusieurs personnes d'un seul coup. »

Les sous-commandes `donner` / `retirer` / `activite` ont donc disparu : elles
traitaient un membre par appel. Ces tests vérifient la forme ET le fond :

1. UNE commande, qui contrôle la permission elle-même ;
2. la garde lit une LISTE de rôles — « on peut être plusieurs » ;
3. le lot agit sur tout le monde, et rend compte de CHAQUE échec ;
4. la mesure d'activité reste celle du système d'activité, sans second compteur.

⚠️ Ces tests n'importent PAS bot.py : la CI ne fournit pas de DISCORD_TOKEN.
Le câblage se vérifie par `ast` — on cherche des appels, pas un comportement.
"""
from __future__ import annotations

import ast
from pathlib import Path

import discord
import pytest

import rellseas_panneau as panneau

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _fonction(nom: str):
    for n in ast.walk(ARBRE):
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
#  1. UNE commande, et elle est bien branchée
# ═══════════════════════════════════════════════════════════════════════════════

def test_une_seule_commande_qui_ouvre_le_panneau():
    corps = ast.unparse(_fonction("rellseas_cmd"))
    assert "RellseasGestionV2" in corps, (
        "la commande doit ouvrir le panneau de gestion")
    assert "_rellseas_autorise" in _appels(_fonction("rellseas_cmd")), (
        "la commande doit contrôler la permission elle-même")


def test_la_commande_est_enregistree_dans_larbre():
    """Une commande écrite mais jamais enregistrée n'existe pas.

    Même famille de défaut que `@tasks.loop` sans `.start()`.
    """
    deco = [ast.unparse(d) for d in _fonction("rellseas_cmd").decorator_list]
    assert any('bot.tree.command' in d and 'rellseas' in d for d in deco)


def test_les_anciennes_sous_commandes_ont_disparu():
    """Elles traitaient UN membre par appel — c'est ce qu'on remplace."""
    for mort in ("rellseas_donner", "rellseas_retirer", "rellseas_activite",
                 "rellseas_group"):
        assert f"async def {mort}" not in SRC and f"{mort} = " not in SRC, (
            f"{mort} subsiste : deux chemins pour le même geste")


def test_le_panneau_recoit_la_garde_pour_la_revverifier():
    """Une vue vit 10 minutes ; un droit peut être retiré entre-temps."""
    corps = ast.unparse(_fonction("rellseas_cmd"))
    assert "autorise=_rellseas_autorise" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  2. « On peut être plusieurs » — la garde lit une LISTE
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_reglage_accepte_plusieurs_roles():
    assert panneau.MAX_ROLES > 1, "un seul rôle autorisé = la demande non tenue"
    assert panneau.MAX_ROLES <= 25, "25 est la limite dure de Discord"


def test_la_garde_accepte_nimporte_lequel_des_roles_autorises():
    c = {"rellseas_roles_autorises": [10, 20, 30]}
    assert panneau.roles_autorises(c) == [10, 20, 30]


def test_roles_autorises_tolere_les_formats_anciens():
    assert panneau.roles_autorises({"rellseas_roles_autorises": ["3", "4"]}) == [3, 4]
    assert panneau.roles_autorises({"rellseas_roles_autorises": 5}) == [5]


def test_roles_autorises_ignore_ce_quil_ne_comprend_pas():
    """Fail-closed : on n'autorise jamais par accident."""
    sale = {"rellseas_roles_autorises": [1, "abc", None, {}, -5, 0, "7"]}
    assert panneau.roles_autorises(sale) == [1, 7]
    assert panneau.roles_autorises({}) == []


def test_la_garde_est_fail_closed_si_la_config_est_illisible():
    corps = ast.unparse(_fonction("_rellseas_autorise"))
    apres_except = corps.split("except", 1)[1]
    assert "return False" in apres_except, (
        "sur config illisible, la garde doit refuser, pas laisser passer")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le lot — les faux objets portent TOUT ce que les vrais portent
# ═══════════════════════════════════════════════════════════════════════════════

class FauxRole:
    def __init__(self, rid=7, position=1):
        self.id = rid
        self.name = "Rellseas"
        self.mention = f"<@&{rid}>"
        self.position = position
        self.members = []

    #  ⚠️ `role >= moi.top_role` est la vérification de hiérarchie : sans ces
    #  comparateurs, le faux rôle ne reproduit pas le vrai et le test passerait
    #  à côté du cas « rôle au-dessus du bot ».
    def __ge__(self, autre):
        return self.position >= autre.position

    def __lt__(self, autre):
        return self.position < autre.position


class FauxPerms:
    def __init__(self, manage_roles=True):
        self.manage_roles = manage_roles
        self.administrator = False


class FauxMembre:
    def __init__(self, uid, roles=None, refuse=False):
        self.id = uid
        self.mention = f"<@{uid}>"
        self.roles = list(roles or [])
        self.guild_permissions = FauxPerms()
        self._refuse = refuse
        self.gestes = []

    async def add_roles(self, role, reason=None):
        if self._refuse:
            raise discord.Forbidden(_FausseReponseHTTP(), "hiérarchie")
        self.gestes.append(("add", role.id))
        self.roles.append(role)

    async def remove_roles(self, role, reason=None):
        if self._refuse:
            raise discord.Forbidden(_FausseReponseHTTP(), "hiérarchie")
        self.gestes.append(("remove", role.id))
        self.roles = [r for r in self.roles if r.id != role.id]


class _FausseReponseHTTP:
    status = 403
    reason = "Forbidden"


class FauxMoi:
    def __init__(self, position=100, manage_roles=True):
        self.top_role = FauxRole(999, position)
        self.guild_permissions = FauxPerms(manage_roles)


class FauxGuild:
    def __init__(self, membres=None, role=None, moi=None):
        self.id = 1234
        self.name = "Serveur"
        self.icon = None
        self._membres = {m.id: m for m in (membres or [])}
        self._role = role
        self.me = moi if moi is not None else FauxMoi()

    def get_member(self, uid):
        return self._membres.get(uid)

    def get_role(self, rid):
        return self._role if (self._role and rid == self._role.id) else None

    def get_channel(self, cid):
        return None


class FauxUser:
    id = 42
    display_name = "staff"
    mention = "<@42>"


class FausseReponse:
    def __init__(self):
        self.appels = []
        self._done = False

    def is_done(self):
        return self._done

    async def defer(self, **kw):
        self._done = True

    async def edit_message(self, **kw):
        self.appels.append(kw)
        self._done = True

    async def send_message(self, *a, **kw):
        self.appels.append(kw)
        self._done = True


class FausseInteraction:
    def __init__(self, values=None):
        self.response = FausseReponse()
        self.data = {"values": list(values or [])}
        self.user = FauxUser()

    async def edit_original_response(self, **kw):
        self.response.appels.append(kw)


def _brancher(role=None, mesurer=None, suivi=None):
    async def _cfg(gid):
        return {"rellseas_role": role.id if role else 0,
                "rellseas_log_channel": 0}
    panneau.setup(cfg=_cfg, db_set=None, mesurer=mesurer,
                  marquer_suivi=suivi, log=lambda *a: None)


@pytest.mark.asyncio
async def test_donner_agit_sur_TOUT_le_lot():
    role = FauxRole(7, position=5)
    membres = [FauxMembre(1), FauxMembre(2), FauxMembre(3)]
    g = FauxGuild(membres, role)
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1, 2, 3]
    await vue._agir(FausseInteraction(), donner=True)

    assert all(m.gestes == [("add", 7)] for m in membres), (
        "les trois membres devaient recevoir le rôle")
    assert "`3`" in vue._dernier


@pytest.mark.asyncio
async def test_retirer_agit_sur_TOUT_le_lot():
    role = FauxRole(7, position=5)
    membres = [FauxMembre(1, [role]), FauxMembre(2, [role])]
    g = FauxGuild(membres, role)
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1, 2]
    await vue._agir(FausseInteraction(), donner=False)

    assert all(m.gestes == [("remove", 7)] for m in membres)


@pytest.mark.asyncio
async def test_un_refus_de_discord_est_dit_et_nempeche_pas_les_autres():
    """LA règle du dépôt : on n'annonce jamais un geste que Discord a refusé."""
    role = FauxRole(7, position=5)
    ok1, ko, ok2 = FauxMembre(1), FauxMembre(2, refuse=True), FauxMembre(3)
    g = FauxGuild([ok1, ko, ok2], role)
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1, 2, 3]
    await vue._agir(FausseInteraction(), donner=True)

    assert ok1.gestes and ok2.gestes, "un échec ne doit pas arrêter le lot"
    assert ko.gestes == []
    assert "`2`" in vue._dernier and "refusé par Discord" in vue._dernier
    assert "`1`" in vue._dernier, "l'échec doit être compté, pas masqué"


@pytest.mark.asyncio
async def test_membre_qui_avait_deja_le_role_est_signale_pas_compte_comme_fait():
    role = FauxRole(7, position=5)
    deja = FauxMembre(1, [role])
    g = FauxGuild([deja], role)
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1]
    await vue._agir(FausseInteraction(), donner=True)

    assert deja.gestes == []
    assert "l'avait déjà" in vue._dernier


@pytest.mark.asyncio
async def test_rien_nest_tente_si_le_role_est_au_dessus_du_bot():
    """Vérifier AVANT le lot évite 25 refus identiques."""
    role = FauxRole(7, position=500)          # au-dessus du top_role du bot
    m = FauxMembre(1)
    g = FauxGuild([m], role, moi=FauxMoi(position=100))
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1]
    await vue._agir(FausseInteraction(), donner=True)

    assert m.gestes == [], "aucune tentative ne devait partir"
    assert "Rien n'a été fait" in vue._dernier
    assert "au-dessus" in vue._dernier


@pytest.mark.asyncio
async def test_rien_nest_tente_sans_permission_gerer_les_roles():
    role = FauxRole(7, position=5)
    m = FauxMembre(1)
    g = FauxGuild([m], role, moi=FauxMoi(manage_roles=False))
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1]
    await vue._agir(FausseInteraction(), donner=True)

    assert m.gestes == []
    assert "Gérer les rôles" in vue._dernier


@pytest.mark.asyncio
async def test_sans_role_cible_le_lot_ne_pretend_rien():
    m = FauxMembre(1)
    g = FauxGuild([m], None)
    _brancher(None)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1]
    await vue._agir(FausseInteraction(), donner=True)

    assert m.gestes == []
    assert "Rien n'a été fait" in vue._dernier


@pytest.mark.asyncio
async def test_le_suivi_dactivite_demarre_a_lattribution():
    """Sans ça, `last_activity` reste vide et le membre paraît inactif."""
    role = FauxRole(7, position=5)
    vus = []

    async def _suivi(gid, uid):
        vus.append((gid, uid))

    g = FauxGuild([FauxMembre(1), FauxMembre(2)], role)
    _brancher(role, suivi=_suivi)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1, 2]
    await vue._agir(FausseInteraction(), donner=True)

    assert vus == [(1234, 1), (1234, 2)]


# ═══════════════════════════════════════════════════════════════════════════════
#  4. La mesure vient du système d'activité, pas d'un second compteur
# ═══════════════════════════════════════════════════════════════════════════════

def test_bot_injecte_presence_et_force_une_semaine():
    corps = ast.unparse(_fonction("_rellseas_mesurer"))
    assert "presence" in corps, "la mesure doit passer par activite.presence()"
    assert "activite_fenetre" in corps and "7" in corps


@pytest.mark.asyncio
async def test_le_panneau_nappelle_aucun_compteur_a_lui():
    """Il appelle `_mesurer`, injecté. Aucune requête, aucun calcul local."""
    appels = []

    async def _mesurer(gid, membre):
        appels.append(membre.id)
        return {"presents": 5, "fenetre": 7, "jugeable": True, "silence": 0}

    role = FauxRole(7, position=5)
    g = FauxGuild([FauxMembre(1), FauxMembre(2)], role)
    _brancher(role, mesurer=_mesurer)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1, 2]
    await vue._cb_activite(FausseInteraction())

    assert appels == [1, 2]
    assert "compteur séparé" in vue._dernier


@pytest.mark.parametrize("mesure,attendu", [
    ({"presents": 6, "fenetre": 7, "jugeable": True, "silence": 0}, "🟢"),
    ({"presents": 1, "fenetre": 7, "jugeable": True, "silence": 3}, "🟠"),
    ({"presents": 0, "fenetre": 7, "jugeable": True, "silence": 9}, "🔴"),
    ({"presents": 0, "fenetre": 7, "jugeable": False, "observables": 2}, "⚪"),
    ({"presents": 0, "fenetre": 7, "jugeable": True, "silence": None}, "⚪"),
])
def test_letiquette_ne_confond_pas_absent_et_pas_observe(mesure, attendu):
    """« Pas encore jugeable » n'est PAS « absent » : reprocher une absence sur
    des journées qu'on n'a pas observées serait un verdict fabriqué."""
    assert panneau._etiquette_activite(mesure).startswith(attendu)


# ═══════════════════════════════════════════════════════════════════════════════
#  5. Le compte-rendu, et les deux panneaux
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_bilan_ne_masque_jamais_les_echecs():
    txt = panneau._bilan("**Rôle donné**", ["<@1>"], ["<@2> — refusé"])
    assert "`1`" in txt and "`1`" in txt and "refusé" in txt


def test_le_bilan_dit_quand_il_ny_a_rien_a_faire():
    assert "Rien à faire" in panneau._bilan("**Test**", [], [])


@pytest.mark.asyncio
async def test_le_panneau_de_gestion_se_serialise():
    role = FauxRole(7, position=5)
    g = FauxGuild([FauxMembre(1)], role)
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    vue._membres = [1]
    i = FausseInteraction()
    await vue.render_to(i)

    assert vue.to_components(), "une vue sans composant est refusée par Discord"
    assert vue.has_components_v2()
    assert i.response.appels


@pytest.mark.asyncio
async def test_les_boutons_daction_sont_desactives_sans_selection():
    """Un bouton sans effet possible est `disabled`, pas absent (UI.md §3)."""
    role = FauxRole(7, position=5)
    g = FauxGuild([], role)
    _brancher(role)

    vue = panneau.RellseasGestionV2(FauxUser(), g)
    await vue.render_to(FausseInteraction())
    texte = str(vue.to_components())

    assert "'disabled': True" in texte or '"disabled": true' in texte.lower()


@pytest.mark.asyncio
async def test_le_panneau_de_reglage_souvre_meme_si_la_config_est_cassee():
    """Fail-open sur la disponibilité (UI.md §6)."""
    async def _cfg(gid):
        raise RuntimeError("base indisponible")

    panneau.setup(cfg=_cfg, db_set=None, log=lambda *a: None)
    vue = panneau.RellseasPanelV2(FauxUser(), FauxGuild())
    i = FausseInteraction()
    await vue.render_to(i)

    assert i.response.appels, "le panneau devait s'ouvrir malgré la panne"
