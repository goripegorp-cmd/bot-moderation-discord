"""Un rôle de ping par type d'annonce Roblox — demandé le 19/08/2026.

LA DEMANDE, MOT POUR MOT
    « Sous chacune des annonces Roblox […] un petit rôle pour le ping […] ils
      ont juste à cliquer une fois sur le bouton, ça leur donnera le rôle et ils
      se feront ping […] Ils auront juste à rappuyer dessus pour ne plus
      recevoir les notifications. […] Tu fais la même pour le côté accessoires
      […] qui deviennent limited ou alors pour les accessoires qui viennent
      juste de sortir. »

⚠️ CE QUI PEUT CASSER ICI SANS QUE RIEN NE LE DISE
Trois raccords, trois pannes muettes, toutes déjà vécues dans ce dépôt :

  1. LE CUSTOM_ID ↔ LE GABARIT. Le bouton est posé par `roblox_panneau`, le
     clic est capté par `RobloxPingButton` dans `bot.py`. Si le gabarit ne
     matche plus le `custom_id` émis, le bouton s'affiche et ne répond jamais
     — « GoRp n'a pas répondu à temps », en public. C'est le défaut du bouton
     langue, réparé le matin même.
  2. LE DOMAINE ↔ LA CATÉGORIE. Les clés de `CLE_PAR_DOMAINE` sont les
     `domaine` RÉELS de `roblox_news.SOURCES`. Un domaine renommé là-bas sans
     l'être ici retombe sur « aucun ping », sans erreur.
  3. LA MENTION ↔ L'AUTORISATION. Les rôles sont créés `mentionable=False`.
     Sans `allowed_mentions` explicite, le `<@&id>` s'affiche en jolie
     pastille et ne notifie PERSONNE. Un ping silencieux est indiscernable
     d'un ping réussi.

Ces tests verrouillent les trois. Ils n'importent pas `bot.py` (la CI n'a pas
de token) : le raccord n°1 est vérifié par AST, comme le reste du dépôt.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import roblox_news as news
import roblox_panneau as rp
import roblox_pings as pings

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le raccord custom_id ↔ gabarit du DynamicItem
# ═══════════════════════════════════════════════════════════════════════════════

def _gabarit_du_bouton() -> str:
    """Le `template=` déclaré par `RobloxPingButton`, lu dans bot.py."""
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.ClassDef) and n.name == "RobloxPingButton":
            for k in n.keywords:
                if k.arg == "template" and isinstance(k.value, ast.Constant):
                    return k.value.value
    raise AssertionError("RobloxPingButton ou son template introuvable dans bot.py")


@pytest.mark.parametrize("cle", sorted(pings.CATEGORIES))
def test_chaque_categorie_est_captee_par_le_gabarit(cle):
    """⚠️ LE TEST QUI COMPTE. Une catégorie dont le custom_id ne matche pas le
    gabarit donne un bouton définitivement muet, en public."""
    gabarit = re.compile(_gabarit_du_bouton())
    cid = pings.custom_id(cle)
    m = gabarit.fullmatch(cid)
    assert m is not None, f"« {cid} » n'est pas capté par « {gabarit.pattern} »"
    assert m.group("cle") == cle, (
        "le gabarit extrait une autre clé que celle émise")


def test_le_bouton_pose_par_le_panneau_porte_bien_ce_custom_id():
    """Le panneau et le bouton doivent parler du même identifiant — c'est la
    raison d'être de `pings.custom_id`, source unique."""
    b = rp._bouton_ping("studio")
    assert b is not None
    assert b.custom_id == pings.custom_id("studio") == "rbxping:studio"


def test_une_categorie_inconnue_ne_pose_aucun_bouton():
    """Mieux vaut pas de bouton qu'un bouton qui ne mène nulle part."""
    assert rp._bouton_ping(None) is None
    assert rp._bouton_ping("categorie_inventee") is None


def test_le_bouton_est_reenregistre_au_boot():
    """⚠️ Sans ce réenregistrement, tous les boutons déjà posés dans
    l'historique du salon deviennent muets au premier redémarrage."""
    assert "bot.add_dynamic_items(RobloxPingButton)" in SRC_BOT


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le raccord domaine ↔ catégorie
# ═══════════════════════════════════════════════════════════════════════════════

def test_chaque_source_dactualite_a_une_categorie():
    """⚠️ Un domaine sans catégorie publie SANS ping, sans erreur. Ce test est
    la seule chose qui le dira si `roblox_news.SOURCES` bouge."""
    manquants = [s["domaine"] for s in news.SOURCES
                 if s["domaine"] not in pings.CLE_PAR_DOMAINE]
    assert not manquants, f"domaines sans rôle de ping : {manquants}"


def test_les_categories_visees_existent_vraiment():
    """L'inverse : une table qui pointe vers une catégorie supprimée."""
    for domaine, cle in pings.CLE_PAR_DOMAINE.items():
        assert cle in pings.CATEGORIES, f"{domaine} → « {cle} » inconnue"
    for flux, cle in pings.CLE_PAR_FLUX.items():
        assert cle in pings.CATEGORIES, f"{flux} → « {cle} » inconnue"


def test_les_deux_salles_de_presse_partagent_un_seul_role():
    """Même contenu, dédupliqué en amont : deux rôles pingeraient deux fois
    pour un seul article."""
    assert (pings.CLE_PAR_DOMAINE["Salle de presse (FR)"]
            == pings.CLE_PAR_DOMAINE["Newsroom Roblox"] == "presse")


def test_les_deux_flux_daccessoires_ont_chacun_le_leur():
    """Demande explicite : « qui deviennent limited OU alors qui viennent juste
    de sortir » — deux publics distincts, deux rôles."""
    assert pings.cle_du_flux("bascules") == "limited"
    assert pings.cle_du_flux("nouveautes") == "nouveaux"
    assert pings.cle_du_flux("bascules") != pings.cle_du_flux("nouveautes")


def test_un_flux_inconnu_ne_ping_personne():
    assert pings.cle_du_flux("surveiller") is None
    assert pings.cle_du_billet({"domaine": "Blog d'un inconnu"}) is None


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le raccord mention ↔ autorisation
# ═══════════════════════════════════════════════════════════════════════════════

class _FauxRole:
    def __init__(self, rid=777):
        self.id = rid


def test_la_mention_est_un_vrai_ping_pas_du_texte():
    """`@Rôle` écrit en texte ne notifie personne et en donne l'illusion."""
    assert pings.mention(_FauxRole(123)) == "<@&123>"
    assert pings.mention(None) == ""


def test_sans_role_aucune_ligne_de_mention_nest_ecrite():
    assert rp._ligne_mention(None) is None
    assert "<@&777>" in rp._ligne_mention(_FauxRole())


def test_lautorisation_ouvre_le_role_et_ferme_le_reste():
    """⚠️ Le rôle est `mentionable=False` : sans cette autorisation explicite,
    le ping ne part pas. Et `everyone` doit rester fermé, toujours."""
    r = _FauxRole()
    am = rp._autorisation_mention(r)
    assert am.everyone is False
    assert am.users is False
    assert am.roles == [r]


def test_sans_role_on_ferme_tout():
    am = rp._autorisation_mention(None)
    assert am.everyone is False and am.roles is False


def test_lenvoi_transmet_bien_lautorisation():
    """Le chemin complet : `_envoyer` doit passer `allowed_mentions` au
    webhook. Sans ça, tout le reste est décoratif."""
    corps = ast.unparse(ast.parse(
        (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")))
    assert "allowed_mentions=_autorisation_mention(ping_role)" in corps


def test_webhook_send_accepte_et_transmet_allowed_mentions():
    arbre = ast.parse(SRC_BOT)
    for n in ast.walk(arbre):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "webhook_send":
            args = [a.arg for a in n.args.args] + [a.arg for a in n.args.kwonlyargs]
            assert "allowed_mentions" in args, (
                "webhook_send n'accepte pas allowed_mentions : le ping ne partira pas")
            corps = ast.unparse(n)
            assert "kw['allowed_mentions'] = allowed_mentions" in corps
            return
    raise AssertionError("webhook_send introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. La bascule — et surtout ses échecs, qui ne doivent pas mentir
# ═══════════════════════════════════════════════════════════════════════════════

class _FauxPerms:
    def __init__(self, manage_roles=True):
        self.manage_roles = manage_roles


class _FauxMe:
    def __init__(self, manage_roles=True, top=100):
        self.guild_permissions = _FauxPerms(manage_roles)
        self.top_role = _FauxRoleRang(top)


class _FauxRoleRang:
    """Un rôle comparable, comme les vrais (`role >= me.top_role`)."""

    def __init__(self, rang, rid=777, managed=False):
        self.rang, self.id, self.managed = rang, rid, managed

    def __ge__(self, autre):
        return self.rang >= autre.rang

    def __eq__(self, autre):
        return isinstance(autre, _FauxRoleRang) and self.id == autre.id

    def __hash__(self):
        return hash(self.id)


class _FauxGuild:
    def __init__(self, role=None, manage_roles=True, top=100):
        self.id = 1
        self._role = role
        self.me = _FauxMe(manage_roles, top)

    def get_role(self, rid):
        return self._role if (self._role and self._role.id == rid) else None


class _FauxMembre:
    def __init__(self, roles=None):
        self.roles = list(roles or [])
        self.ajoutes, self.retires = [], []

    async def add_roles(self, r, reason=None):
        self.roles.append(r)
        self.ajoutes.append(r)

    async def remove_roles(self, r, reason=None):
        self.roles.remove(r)
        self.retires.append(r)


@pytest.fixture
def branche(monkeypatch):
    """Injecte cfg/db_set comme le fait bot.py au boot."""
    ecrits = {}

    async def _cfg(gid):
        return {"roblox_ping_role_studio": 777}

    async def _db_set(gid, k, v):
        ecrits[k] = v

    monkeypatch.setattr(pings, "_cfg", _cfg)
    monkeypatch.setattr(pings, "_db_set", _db_set)
    return ecrits


@pytest.mark.asyncio
async def test_un_clic_donne_le_role(branche):
    role = _FauxRoleRang(10)
    g, m = _FauxGuild(role), _FauxMembre()
    etat, r = await pings.basculer(g, m, "studio")
    assert etat == pings.ACTIVE
    assert r in m.roles and m.ajoutes == [role]


@pytest.mark.asyncio
async def test_un_second_clic_le_retire(branche):
    role = _FauxRoleRang(10)
    g, m = _FauxGuild(role), _FauxMembre([role])
    etat, _ = await pings.basculer(g, m, "studio")
    assert etat == pings.RETIRE
    assert role not in m.roles and m.retires == [role]


@pytest.mark.asyncio
async def test_sans_permission_on_le_dit_au_lieu_de_faire_semblant(branche):
    """⚠️ LE CAS QUI FAIT MENTIR LES BOUTONS. Pas de « Gérer les rôles » → on
    ne répond JAMAIS « c'est fait »."""
    g = _FauxGuild(_FauxRoleRang(10), manage_roles=False)
    etat, _ = await pings.basculer(g, _FauxMembre(), "studio")
    assert etat == pings.SANS_PERMISSION
    assert "permission" in pings.phrase(etat, "studio").lower()


@pytest.mark.asyncio
async def test_role_au_dessus_du_bot_est_un_echec_distinct(branche):
    """Le plus vicieux : le rôle EXISTE, tout a l'air normal, et l'attribution
    échoue. Il doit avoir sa propre phrase."""
    g = _FauxGuild(_FauxRoleRang(500), top=100)   # rôle au-dessus du bot
    etat, _ = await pings.basculer(g, _FauxMembre(), "studio")
    assert etat == pings.TROP_HAUT
    assert pings.phrase(etat, "studio") != pings.phrase(pings.SANS_PERMISSION, "studio")


@pytest.mark.asyncio
async def test_aucune_phrase_dechec_ne_ressemble_a_un_succes(branche):
    for etat in (pings.SANS_PERMISSION, pings.TROP_HAUT, pings.ERREUR):
        p = pings.phrase(etat, "studio")
        assert p.startswith("❌"), f"« {p[:40]} » ne se lit pas comme un échec"
    assert pings.phrase(pings.ACTIVE, "studio").startswith("🔔")
    assert pings.phrase(pings.RETIRE, "studio").startswith("🔕")


@pytest.mark.asyncio
async def test_le_role_nest_pas_mentionnable_a_la_creation(branche):
    """⚠️ Sinon n'importe quel membre s'en sert pour réveiller le serveur."""
    cree = {}

    class _G(_FauxGuild):
        async def create_role(self, **kw):
            cree.update(kw)
            return _FauxRoleRang(10)

    g = _G(None)
    await pings.role_de(g, "limited")
    assert cree.get("mentionable") is False
    assert cree.get("hoist") is False


@pytest.mark.asyncio
async def test_sans_permission_on_ne_tente_meme_pas_lappel_api(branche):
    """Sinon un serveur mal réglé produirait un appel raté à CHAQUE annonce."""
    appels = []

    class _G(_FauxGuild):
        async def create_role(self, **kw):
            appels.append(kw)
            raise AssertionError("ne doit pas être appelé")

    g = _G(None, manage_roles=False)
    assert await pings.role_de(g, "limited") is None
    assert appels == []


# ═══════════════════════════════════════════════════════════════════════════════
#  5. La fiche réelle porte bien le bouton
# ═══════════════════════════════════════════════════════════════════════════════

def _custom_ids(vue) -> list:
    trouves = []

    def descendre(o):
        cid = getattr(o, "custom_id", None)
        if isinstance(cid, str):
            trouves.append(cid)
        for enfant in (getattr(o, "children", None) or []):
            descendre(enfant)
    descendre(vue)
    return trouves


def test_la_fiche_daccessoire_porte_le_bouton():
    v = rp.construire_fiche(
        {"asset_id": 123, "nom": "Chapeau", "prix": 84, "cree_le": None},
        "bascules", ping_cle="limited", ping_role=_FauxRole())
    assert "rbxping:limited" in _custom_ids(v)


def test_la_fiche_dactualite_porte_le_bouton():
    v = rp.construire_actu(
        {"topic_id": 42, "titre": "Notes", "domaine": "Studio & moteur",
         "corps": "x", "cree_le": None},
        ping_cle="studio", ping_role=_FauxRole())
    assert "rbxping:studio" in _custom_ids(v)


def test_sans_categorie_la_fiche_reste_publiable():
    """Une catégorie inconnue ne doit pas empêcher l'annonce de sortir."""
    v = rp.construire_actu({"topic_id": 42, "titre": "T", "domaine": "?",
                            "corps": "x", "cree_le": None})
    assert not [c for c in _custom_ids(v) if c.startswith("rbxping:")]
    assert v is not None
