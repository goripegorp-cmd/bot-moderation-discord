"""Les mentions du rappel hebdomadaire, l'horaire, et le nettoyage du salon.

CAPTURE DU PROPRIÉTAIRE, 30/08/2026 — deux cartes côte à côte :
  « 👀 Presque · Almost » → `39 membre(s) concerné(s)`, AUCUNE mention
  « 💤 Absents · Away »   → `@💤 AFK`, puis `25 membre(s) concerné(s)`

Sa question : « est-ce que ça mentionne vraiment les gens ? » — et sa demande :
« tu dois faire en sorte que chaque personne ait un rôle, que tout le monde ait
bien un rôle ».

TROIS DÉFAUTS DERRIÈRE CETTE SEULE CAPTURE :

1. LE RÔLE N'EXISTAIT PAS. `construire` passe en mode muet dès que le rôle vaut
   `None`, et affiche alors le compte seul — exactement la carte « Presque ».
   `creer_role` n'était appelé QUE depuis un bouton du panneau : un serveur où
   personne ne clique n'a jamais ses étiquettes, et le système paraît cassé
   alors qu'il attend un geste que rien ne réclame.

2. LA MENTION POUVAIT NE NOTIFIER PERSONNE. Ces rôles sont créés
   `mentionable=False` à dessein. Dans ce cas `allowed_mentions(roles=True)` ne
   suffit PAS : il faut « Mentionner tous les rôles ». Sans elle la mention
   s'affiche à l'identique et ne réveille personne — et rien ne le disait.

3. « DIMANCHE 00H00 PILE ». La boucle tournait toutes les 6 h À PARTIR DU
   DÉMARRAGE : sur Railway, le rappel du dimanche partait jusqu'à six heures
   après minuit, à une heure qui changeait à chaque redéploiement.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import activite
import activite_message as msgs
import activite_niveaux as niv
import activite_passage as passage

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Chaque palier a son rôle, créé au besoin
# ═══════════════════════════════════════════════════════════════════════════════

class _Perms:
    def __init__(self, manage_roles=True, mention_everyone=True):
        self.manage_roles = manage_roles
        self.mention_everyone = mention_everyone
        self.view_channel = self.send_messages = self.manage_messages = True


class _Moi:
    def __init__(self, **kw):
        self.id = 999
        self.guild_permissions = _Perms(**kw)


class _Role:
    def __init__(self, rid, nom="role"):
        self.id, self.name, self.members = rid, nom, []
        self.mention = f"<@&{rid}>"


class _Guild:
    def __init__(self, roles=None, **kw):
        self.id, self.name = 1, "Serveur"
        self.me = _Moi(**kw)
        self._roles = {r.id: r for r in (roles or [])}
        self.crees = []

    def get_role(self, rid):
        return self._roles.get(int(rid))


@pytest.mark.asyncio
async def test_le_role_manquant_est_cree_au_lieu_d_attendre_un_clic(monkeypatch):
    """⚠️ LE DÉFAUT EXACT DE LA CAPTURE. Sans rôle, la carte « Presque »
    affiche 39 membres et ne mentionne personne."""
    g = _Guild()
    ecrits = {}

    async def _faux_creer(guild, niveau):
        r = _Role(1000 + niveau, f"niveau{niveau}")
        guild._roles[r.id] = r
        guild.crees.append(niveau)
        return r

    async def _faux_set(gid, cle, val):
        ecrits[cle] = val
        return True

    monkeypatch.setattr(niv, "creer_role", _faux_creer)
    monkeypatch.setattr(activite, "_db_set", _faux_set)

    r = await passage._role_ou_creer(g, {}, "activite_role_doux", 0)
    assert r is not None, "le rôle du palier doux n'a pas été créé"
    assert ecrits["activite_role_doux"] == r.id, (
        "l'identifiant n'est pas mémorisé : un second rôle serait créé au "
        "prochain passage")


@pytest.mark.asyncio
async def test_un_role_deja_present_nest_pas_recree(monkeypatch):
    g = _Guild(roles=[_Role(77, "deja la")])
    appels = []

    async def _faux_creer(guild, niveau):
        appels.append(niveau)
        return _Role(1, "nouveau")

    monkeypatch.setattr(niv, "creer_role", _faux_creer)
    r = await passage._role_ou_creer(g, {"activite_role_doux": 77},
                                     "activite_role_doux", 0)
    assert r.id == 77 and appels == []


@pytest.mark.asyncio
async def test_sans_gerer_les_roles_on_le_DIT(monkeypatch):
    """Sinon l'API refuse à chaque passage et le journal se remplit d'erreurs
    au lieu d'un diagnostic."""
    g = _Guild(manage_roles=False)
    dits = []
    monkeypatch.setattr(passage, "_log", lambda m: dits.append(str(m)))
    r = await passage._role_ou_creer(g, {}, "activite_role_doux", 0)
    assert r is None
    assert any("Gérer les rôles" in d for d in dits)


@pytest.mark.asyncio
async def test_la_config_non_ecrite_annule_la_creation(monkeypatch):
    """⚠️ SINON ON CRÉE UN RÔLE PAR PASSAGE. Le rôle existe, la config ne le
    sait pas : au tour suivant on en créerait un second, puis un troisième."""
    g = _Guild()
    supprimes = []

    class _R(_Role):
        async def delete(self, reason=None):
            supprimes.append(self.id)

    async def _faux_creer(guild, niveau):
        return _R(500, "orphelin")

    async def _set_qui_echoue(gid, cle, val):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(niv, "creer_role", _faux_creer)
    monkeypatch.setattr(activite, "_db_set", _set_qui_echoue)
    monkeypatch.setattr(passage, "_log", lambda m: None)
    r = await passage._role_ou_creer(g, {}, "activite_role_doux", 0)
    assert r is None and supprimes == [500]


# ═══════════════════════════════════════════════════════════════════════════════
#  2. « Est-ce que ça mentionne vraiment ? »
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_la_permission_qui_decide_est_verifiee():
    """⚠️ LA RÉPONSE N'EST PAS DANS LE MESSAGE, ELLE EST DANS UNE PERMISSION.
    Les rôles sont `mentionable=False` : sans « Mentionner tous les rôles », la
    mention s'affiche exactement pareil et ne notifie PERSONNE."""
    assert await passage.peut_mentionner_un_role(_Guild()) is True
    assert await passage.peut_mentionner_un_role(
        _Guild(mention_everyone=False)) is False


def test_les_roles_restent_non_mentionnables_par_les_membres():
    """`mentionable=True` laisserait n'importe qui réveiller des centaines de
    gens. C'est le bot qui ping, en le demandant explicitement."""
    src = inspect.getsource(niv.creer_role)
    assert "mentionable=False" in src


def test_l_envoi_autorise_les_roles_mais_jamais_everyone():
    src = inspect.getsource(msgs.remplacer)
    assert "roles=True" in src, (
        "sans cela la mention s'afficherait sans notifier personne")
    assert "everyone=False" in src, (
        "le rappel ne doit toucher que les absents, jamais le serveur entier")


def test_la_mention_muette_est_remontee_au_staff():
    """Une permission manquante visible seulement dans les journaux n'est
    jamais vue : à l'écran, le rappel a l'air parfait."""
    src = inspect.getsource(passage.envoyer_rappels)
    ast.parse(src.lstrip())
    assert "peut_mentionner_un_role" in src
    assert "mention_muette" in src
    assert "Mentionner tous les rôles" in src, (
        "le message doit nommer la permission exacte, sinon il est inutile")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Dimanche 00h00, heure française
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_passage_est_ancre_sur_l_horloge_pas_sur_le_demarrage():
    """⚠️ `@tasks.loop(hours=6)` COMPTE DEPUIS LE LANCEMENT. Sur Railway, un
    redéploiement à 3 h 17 fait passer la boucle à 3 h 17, 9 h 17… et le rappel
    du dimanche partait jusqu'à six heures après minuit, à une heure qui
    changeait à chaque déploiement."""
    assert "_HEURES_PASSAGE_ACTIVITE" in SRC_BOT
    assert 'ZoneInfo("Europe/Paris")' in SRC_BOT
    for n in ast.walk(ast.parse(SRC_BOT)):
        if (isinstance(n, ast.AsyncFunctionDef)
                and n.name == "activite_passage_task"):
            deco = " ".join(ast.unparse(d) for d in n.decorator_list)
            assert "tasks.loop" in deco, (
                "la boucle a perdu son décorateur : elle ne tournera jamais")
            assert "_HEURES_PASSAGE_ACTIVITE" in deco, (
                "la boucle est repassée à un intervalle relatif")
            return
    raise AssertionError("activite_passage_task introuvable")


def test_le_repli_garde_un_decorateur_valide():
    """⚠️ PIÈGE N°1 DU DÉPÔT : une boucle sans décorateur ne tourne JAMAIS. Si
    `zoneinfo` manque, on doit retomber sur l'ancien rythme, pas sur rien."""
    assert '{"hours": 6}' in SRC_BOT, (
        "aucun repli si zoneinfo est absent : la boucle serait décorée avec "
        "time=None")


def test_le_jour_de_rappel_reste_le_dimanche():
    assert activite.CLES_DEFAUT["activite_jour_rappel"] == 6, (
        "0 = lundi … 6 = dimanche")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le salon est remis au propre
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_salon_est_nettoye_avant_de_republier():
    """⚠️ LA MÉMOIRE NE COUVRE QUE LE DERNIER ENVOI DE CE RÔLE SURVEILLÉ. Tout
    le reste survivait : envois d'un autre rôle, cartes d'un redémarrage qui a
    perdu la mémoire, essais du bouton manuel. Le salon accumulait des semaines
    d'annonces contradictoires."""
    src = inspect.getsource(msgs.remplacer)
    ast.parse(src.lstrip())
    assert "salon.purge(" in src, "aucun nettoyage large du salon"
    i_purge = src.index("salon.purge(")
    i_envoi = src.index("salon.send(")
    assert i_purge < i_envoi, (
        "on nettoie AVANT de republier, sinon on efface ce qu'on vient de "
        "poster")


def test_le_nettoyage_nefface_que_nos_messages_et_jamais_les_epingles():
    """Un `purge()` aveugle emporterait les consignes humaines du staff."""
    src = inspect.getsource(msgs.remplacer)
    assert "m.author.id == guild.me.id" in src, (
        "le nettoyage effacerait les messages des membres")
    assert "not m.pinned" in src, (
        "le nettoyage emporterait les messages épinglés du staff")


def test_on_ne_vide_pas_un_salon_qu_on_ne_republiera_pas():
    """Vider sans rien remettre laisserait le staff devant une page blanche."""
    src = inspect.getsource(msgs.remplacer)
    bloc = src.split("salon.purge(")[0]
    assert "if a_poster:" in bloc[-400:], (
        "le nettoyage n'est pas conditionné à la présence de quelque chose "
        "à republier")


def test_un_nettoyage_rate_nempeche_pas_le_rappel():
    """Mieux vaut un salon en désordre qu'un salon muet."""
    src = inspect.getsource(msgs.remplacer)
    apres = src[src.index("salon.purge("):]
    assert "except Exception" in apres[:900]
