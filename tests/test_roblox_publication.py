"""L'ENVOI de la veille Roblox — le maillon que personne n'avait observé.

Le HANDOFF le disait mot pour mot : « JAMAIS VÉRIFIÉ : qu'un message atterrisse
réellement dans un salon Discord. C'est le seul maillon non observé. » Il y avait
bien un défaut dedans, et ces tests l'enferment.

CE QUI ÉTAIT CASSÉ
------------------
`roblox_panneau.publier()` appelait `webhook_send(...)` puis rendait `True` sans
regarder le retour. Or `webhook_send` (bot.py) n'a aucun chemin qui lève : elle
attrape Forbidden / HTTPException / tout le reste, journalise, tente son propre
repli `channel.send`, et rend `None` quand plus rien n'est possible.

Conséquence mesurable : sur un salon mal permissionné, le bouton annonçait
« 3 fiches publiées » alors que le salon n'avait rien reçu — et l'appelant
enchaînait sur `marquer_publie()`, marquant l'article SORTI POUR TOUJOURS sans
qu'il ait jamais été vu.

CE QUE CES TESTS PROUVENT
-------------------------
1. `publier()` rend le VRAI résultat de l'envoi (donc la marque définitive n'est
   plus écrite sur un échec) ;
2. le compte-rendu du bouton nomme la cause au lieu de la ranger sous
   « c'est normal » ;
3. la fiche produite est un payload Components V2 réellement sérialisable par
   discord.py, sous les limites dures de l'API.

Le point 3 est le plus proche d'un « effet réel » atteignable sans serveur de
test : c'est l'octet près du fil, pas l'intention.
"""
from __future__ import annotations

import discord
import pytest

import roblox_panneau


# ═══════════════════════════════════════════════════════════════════════════════
#  Les faux objets
#
#  ⚠️ PIÈGE DU DÉPÔT — « un faux objet de test doit porter TOUT ce que le vrai
#  porte ». Un `_Guild` sans `get_channel` avait rendu la CI rouge un jour sur
#  sept. Ces doublures portent donc les attributs que le code de publication
#  touche vraiment : `id`, `name`, `send`, et le `mention` que lit le panneau.
# ═══════════════════════════════════════════════════════════════════════════════

class FauxSalon:
    """Un salon texte, qui compte ce qu'on lui envoie."""

    def __init__(self, salon_id: int = 4242, envoi_leve: Exception | None = None):
        self.id = salon_id
        self.name = "veille-roblox"
        self.mention = f"<#{salon_id}>"
        self.envois: list = []
        self._envoi_leve = envoi_leve

    async def send(self, **kwargs):
        if self._envoi_leve is not None:
            raise self._envoi_leve
        self.envois.append(kwargs)
        return object()  # un vrai `Message`, côté Discord


class FauxWebhookSend:
    """La doublure de `bot.webhook_send`.

    Elle reproduit le contrat EXACT du vrai : elle n'a aucun chemin qui lève,
    elle rend un objet en cas de succès et `None` en cas d'échec.
    """

    def __init__(self, retour="message-parti"):
        self.retour = retour
        self.appels: list = []

    async def __call__(self, salon, plateforme, **kwargs):
        self.appels.append((salon, plateforme, kwargs))
        if isinstance(self.retour, Exception):
            raise self.retour
        return self.retour


ARTICLE = {
    "asset_id": 12345678,
    "nom": "Tricolor Ladoo Hat",
    "nom_fr": "Chapeau Ladoo tricolore",
    "type_article": "Accessoire",
    "item_type": "Asset",
    "cree_le": "2026-08-14T10:00:00Z",
    "prix": 350,
    "favoris": 1200,
    "collectionnable": False,
    "hors_vente": False,
}


@pytest.fixture(autouse=True)
def _rebrancher_module():
    """Chaque test repart d'un module propre — l'état est global."""
    roblox_panneau.setup(db_set=None, webhook_send=None, log=lambda *a: None)
    yield
    roblox_panneau.setup(db_set=None, webhook_send=None, log=print)


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le résultat de `publier()` dit la vérité
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_publier_rend_faux_quand_le_webhook_na_rien_envoye():
    """LE défaut. `webhook_send` rend None ⇔ rien n'est parti ⇒ `publier` = False.

    Si ce test repasse au rouge, la marque « déjà publié » redeviendra écrite
    sur des envois fantômes, et les articles concernés seront perdus pour de bon.
    """
    wh = FauxWebhookSend(retour=None)  # Forbidden avalé par le vrai webhook_send
    roblox_panneau.setup(db_set=None, webhook_send=wh, log=lambda *a: None)
    salon = FauxSalon()

    ok = await roblox_panneau.publier(None, salon, ARTICLE, "nouveautes")

    assert ok is False, "un envoi qui n'a rien envoyé ne doit jamais rendre True"
    assert wh.appels, "le webhook devait bien être tenté"
    assert salon.envois == [], (
        "pas de seconde tentative : webhook_send a déjà essayé channel.send")


@pytest.mark.asyncio
async def test_publier_rend_vrai_quand_le_message_est_parti():
    wh = FauxWebhookSend(retour="WebhookMessage")
    roblox_panneau.setup(db_set=None, webhook_send=wh, log=lambda *a: None)

    ok = await roblox_panneau.publier(None, FauxSalon(), ARTICLE, "nouveautes")

    assert ok is True
    salon, plateforme, kwargs = wh.appels[0]
    #  Le nom du flux vient du PROFIL, pas d'un `username=` — la signature du
    #  vrai `webhook_send` ne l'accepte pas, et le lui passer levait un
    #  TypeError qui rendait le webhook inutilisable.
    assert plateforme == "roblox_nouveautes"
    assert "username" not in kwargs
    assert isinstance(kwargs["view"], discord.ui.LayoutView)


@pytest.mark.asyncio
async def test_publier_retombe_sur_le_salon_si_le_webhook_leve():
    """Un défaut de webhook ne doit pas faire taire le flux."""
    wh = FauxWebhookSend(retour=RuntimeError("webhook cassé"))
    roblox_panneau.setup(db_set=None, webhook_send=wh, log=lambda *a: None)
    salon = FauxSalon()

    ok = await roblox_panneau.publier(None, salon, ARTICLE, "nouveautes")

    assert ok is True
    assert len(salon.envois) == 1, "le repli channel.send devait partir"


@pytest.mark.asyncio
async def test_publier_rend_faux_si_tout_echoue():
    wh = FauxWebhookSend(retour=RuntimeError("webhook cassé"))
    roblox_panneau.setup(db_set=None, webhook_send=wh, log=lambda *a: None)
    salon = FauxSalon(envoi_leve=discord.DiscordException("pas la permission"))

    assert await roblox_panneau.publier(None, salon, ARTICLE, "nouveautes") is False


@pytest.mark.asyncio
async def test_publier_sans_salon_ne_pretend_rien():
    assert await roblox_panneau.publier(None, None, ARTICLE, "nouveautes") is False


@pytest.mark.asyncio
async def test_publier_actu_suit_le_meme_contrat():
    """L'actualité passait par le même défaut — même contrat, même preuve."""
    billet = {"topic_id": 987654, "domaine": "Roblox Studio",
              "titre": "Notes de version", "cree_le": "2026-08-15T09:00:00Z",
              "tags": ["studio"], "extrait": "Correctifs divers."}

    wh = FauxWebhookSend(retour=None)
    roblox_panneau.setup(db_set=None, webhook_send=wh, log=lambda *a: None)
    assert await roblox_panneau.publier_actu(None, FauxSalon(), billet) is False

    wh_ok = FauxWebhookSend(retour="WebhookMessage")
    roblox_panneau.setup(db_set=None, webhook_send=wh_ok, log=lambda *a: None)
    assert await roblox_panneau.publier_actu(None, FauxSalon(), billet) is True
    assert wh_ok.appels[0][1] == "roblox_actu"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le compte-rendu nomme la cause
# ═══════════════════════════════════════════════════════════════════════════════

def _motifs(**kw):
    base = {"sans_salon": 0, "salon_introuvable": 0, "age": 0, "seuil": 0,
            "deja": 0, "envoi": 0}
    base.update(kw)
    return base


def test_compte_rendu_ne_range_pas_une_panne_sous_cest_normal():
    """Le cœur du bouton qui mentait : 0 publiée, cause « aucun salon »."""
    txt = roblox_panneau.RobloxPanelV2._compte_rendu(
        30, 0, _motifs(sans_salon=4), [])

    assert "aucun salon" in txt.lower()
    assert "c'est normal" not in txt.lower(), (
        "une case vide n'est pas « Roblox publie peu »")
    assert txt.startswith("🔴"), "une panne se voit à l'icône"


def test_compte_rendu_distingue_salon_absent_et_salon_introuvable():
    txt = roblox_panneau.RobloxPanelV2._compte_rendu(
        30, 0, _motifs(salon_introuvable=2), ["555"])

    assert "introuvable" in txt.lower()
    assert "555" in txt, "l'identifiant fautif doit être affiché"


def test_compte_rendu_dit_quand_discord_a_refuse():
    txt = roblox_panneau.RobloxPanelV2._compte_rendu(30, 1, _motifs(envoi=2), [])

    assert "refusée" in txt.lower() and "permission" in txt.lower()
    #  ⚠️ LE MOT A CHANGÉ LE 30/08, LA GARANTIE S'EST RENFORCÉE.
    #  Le texte promettait « ces articles ressortiront au prochain relevé ».
    #  C'était FAUX : l'article était déjà écrit en base, la tranche l'écartait,
    #  et il ne revenait jamais. Depuis la file d'attente, la ligne survit à
    #  l'échec et au redémarrage — on exige donc la promesse, pas le mot.
    assert "file" in txt.lower() and "réessay" in txt.lower(), (
        "l'utilisateur doit savoir que la fiche est conservée et retentée")
    assert txt.startswith("🔴")


def test_compte_rendu_calme_quand_tout_va_bien():
    """Un salon calme est normal — là, et seulement là, on le dit."""
    txt = roblox_panneau.RobloxPanelV2._compte_rendu(30, 0, _motifs(), [])

    assert txt.startswith("⚪")
    assert "c'est normal" in txt.lower()


def test_compte_rendu_succes():
    txt = roblox_panneau.RobloxPanelV2._compte_rendu(30, 3, _motifs(deja=2), [])

    assert txt.startswith("🟢")
    assert "3" in txt and "republier" in txt.lower()


# ═══════════════════════════════════════════════════════════════════════════════
#  3. La fiche est un payload que Discord accepterait
#
#  `to_components()` est la mécanique RÉELLE de discord.py : c'est ce dictionnaire
#  qui part sur le fil. Le valider ici attrape les 400 (trop de composants,
#  `content` interdit) avant qu'ils ne tombent en production.
# ═══════════════════════════════════════════════════════════════════════════════

def _compter(payload) -> int:
    n = 0
    for c in payload:
        n += 1
        n += _compter(c.get("components", []) or [])
    return n


@pytest.mark.parametrize("flux", ["nouveautes", "bascules", "surveiller"])
def test_la_fiche_se_serialise_sous_les_limites_de_lapi(flux):
    vue = roblox_panneau.construire_fiche(
        ARTICLE, flux, image="https://tr.rbxcdn.com/abc/420/420/Hat/Png")
    payload = vue.to_components()

    assert payload, "une vue sans aucun composant est refusée par Discord"
    assert _compter(payload) <= 40, "40 composants maximum par message"
    assert vue.has_components_v2(), "Components V2 attendu, jamais un embed hérité"


def test_le_lien_de_la_fiche_est_reconstruit_pas_recopie():
    """Règle de sécurité ROBLOX.md §1 : domaine en dur + identifiant validé."""
    empoisonne = dict(ARTICLE, asset_id="12345678'><script>")
    vue = roblox_panneau.construire_fiche(empoisonne, "nouveautes")
    liens = [c.get("url", "") for row in vue.to_components()
             for c in row.get("components", []) or []
             for c in ([c] + (c.get("components", []) or []))]

    assert not any("script" in (u or "") for u in liens), (
        "un identifiant illisible doit donner une fiche SANS lien")


def test_la_fiche_dactualite_se_serialise_aussi():
    billet = {"topic_id": 987654, "domaine": "UGC", "titre": "Nouveau programme",
              "cree_le": "2026-08-15T09:00:00Z", "tags": ["ugc", "créateurs"],
              "extrait": "Ouverture élargie."}
    vue = roblox_panneau.construire_actu(billet)

    assert _compter(vue.to_components()) <= 40
    assert vue.has_components_v2()
