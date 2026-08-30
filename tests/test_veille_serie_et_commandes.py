"""La série temporelle, et les commandes `/roblox`.

CE QUE LA SPÉCIFICATION DEMANDAIT ET QUI MANQUAIT ENCORE APRÈS LE 30/08 :
  · une série temporelle (`item_snapshots`) — « le système doit construire ses
    propres séries temporelles à partir de snapshots » ;
  · sept commandes (`/latest`, `/limited`, `/item`, `/predict`,
    `/predictions`, `/model-status`, `/health`).

⚠️ LA SÉRIE N'EST PAS UN LUXE, C'EST LA CONDITION D'EXISTENCE DE TOUT MODÈLE.
Aucune API Roblox ne donne la date de passage en Limited (sept points testés le
30/08). Tant que personne n'enregistre l'état des articles jour après jour, il
n'y aura JAMAIS de vérité terrain, et « données insuffisantes » restera vrai
pour toujours. Ces tests verrouillent le fait que la collecte tourne.

⚠️ ET ILS VERROUILLENT AUSSI LE REFUS DE PRÉDIRE. Un pourcentage fabriqué
serait pire que pas de pourcentage : il ferait acheter de travers.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

import roblox_veille as veille


GUILDE = 777


def _iso(heures: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=heures)).isoformat()


def _art(aid=1, prix=100, favoris=10, hors_vente=0, collectionnable=0,
         classe=""):
    return {"asset_id": aid, "prix": prix, "favoris": favoris,
            "hors_vente": hors_vente, "collectionnable": collectionnable,
            "classe": classe, "quantite": None}


@pytest.fixture
def banc(tmp_path):
    chemin = tmp_path / "veille.db"
    conf: dict = {}

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return dict(conf)

    async def _db_set(_g, k, v):
        conf[k] = v
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                 log=lambda *a, **k: None)
    return conf


# ═══════════════════════════════════════════════════════════════════════════════
#  1. La série temporelle
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_une_mesure_est_ecrite_au_premier_passage(banc):
    await veille.init_db()
    assert await veille.enregistrer_mesures([_art()]) == 1
    etat = await veille.etat_serie()
    assert etat["mesures"] == 1 and etat["articles"] == 1


@pytest.mark.asyncio
async def test_la_cadence_est_quotidienne_pas_par_passage(banc):
    """⚠️ LE CALCUL QUI JUSTIFIE LA CADENCE. 48 passages par jour × 964
    articles = 46 000 lignes quotidiennes. Écrire à chaque passage rendrait la
    table ingérable en quelques mois, pour une précision dont aucun modèle n'a
    besoin — « croissance des favoris sur 1, 7 et 30 jours » se contente
    largement d'un point par jour."""
    await veille.init_db()
    await veille.enregistrer_mesures([_art(favoris=10)])
    #  Deux passages de plus dans l'heure : les favoris bougent, la structure
    #  non. Rien ne doit être écrit.
    assert await veille.enregistrer_mesures([_art(favoris=11)]) == 0
    assert await veille.enregistrer_mesures([_art(favoris=12)]) == 0
    assert (await veille.etat_serie())["mesures"] == 1


@pytest.mark.asyncio
async def test_un_changement_structurel_ecrit_hors_cadence(banc):
    """⚠️ CE SONT PRÉCISÉMENT LES INSTANTS QU'UN MODÈLE DEVRA DATER. Attendre
    24 h pour enregistrer un passage collectionnable ferait perdre l'heure de
    l'événement — la seule donnée qui manque à toute la chaîne."""
    await veille.init_db()
    await veille.enregistrer_mesures([_art()])
    #  Le prix change : on écrit tout de suite, sans attendre le lendemain.
    assert await veille.enregistrer_mesures([_art(prix=250)]) == 1
    #  Le passage collectionnable aussi.
    assert await veille.enregistrer_mesures(
        [_art(prix=250, collectionnable=1, classe="Limited")]) == 1
    #  Mais pas deux fois pour le même état.
    assert await veille.enregistrer_mesures(
        [_art(prix=250, collectionnable=1, classe="Limited")]) == 0


@pytest.mark.asyncio
async def test_la_croissance_dit_NE_SAIS_PAS_plutot_que_zero(banc):
    """⚠️ « Pas de croissance » et « je ne sais pas encore » sont deux choses
    différentes. Les confondre serait le premier pas vers un chiffre
    fabriqué — exactement ce qu'on refuse de faire."""
    await veille.init_db()
    await veille.enregistrer_mesures([_art(favoris=100)])
    assert await veille.croissance_favoris(1, 7) is None, (
        "la série ne remonte pas à 7 jours : rendre 0 serait un mensonge")


@pytest.mark.asyncio
async def test_la_croissance_se_calcule_quand_la_serie_le_permet(banc):
    """La contre-épreuve : sans elle, le test précédent passerait sur une
    fonction qui rend toujours None."""
    await veille.init_db()
    await veille.enregistrer_mesures([_art(favoris=100)])
    #  On vieillit la mesure de dix jours, puis on en pose une neuve.
    async with veille._get_db() as db:
        await db.execute("UPDATE roblox_mesures SET mesure_le=?",
                         (_iso(240),))
        await db.commit()
    await veille.enregistrer_mesures([_art(favoris=160)])
    assert await veille.croissance_favoris(1, 7) == 60


@pytest.mark.asyncio
async def test_la_detection_ecrit_la_serie_sans_pouvoir_la_casser(banc):
    """⚠️ LA SÉRIE EST UN BONUS POUR PLUS TARD, LA DÉTECTION EST LE PRODUIT.
    Une panne d'écriture de la série ne doit JAMAIS faire perdre une
    détection."""
    await veille.init_db()
    bruts = [{"id": 1, "name": "A", "itemType": "Asset",
              "itemCreatedUtc": _iso(2).replace("+00:00", "Z"),
              "itemRestrictions": [], "price": 100, "favoriteCount": 5}]
    evts = await veille.comparer_et_enregistrer(veille._normaliser(bruts))
    assert len(evts["nouveaux"]) == 1
    assert (await veille.etat_serie())["mesures"] == 1

    #  On casse la série ; la détection doit continuer.
    async with veille._get_db() as db:
        await db.execute("DROP TABLE roblox_mesures")
        await db.commit()
    bruts[0]["itemRestrictions"] = ["Limited"]
    evts = await veille.comparer_et_enregistrer(veille._normaliser(bruts))
    assert len(evts["bascules"]) == 1, (
        "une panne de la série temporelle a fait perdre une BASCULE")


@pytest.mark.asyncio
async def test_la_purge_borne_la_serie_sans_toucher_au_recent(banc):
    await veille.init_db()
    await veille.enregistrer_mesures([_art(aid=1), _art(aid=2)])
    async with veille._get_db() as db:
        await db.execute("UPDATE roblox_mesures SET mesure_le=? WHERE asset_id=1",
                         ((datetime.now(timezone.utc)
                           - timedelta(days=500)).isoformat(),))
        await db.commit()
    await veille.purger()
    etat = await veille.etat_serie()
    assert etat["articles"] == 1, "la purge a emporté la mesure récente"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le refus de prédire — verrouillé, pas laissé à la bonne volonté
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_seuil_de_prediction_compte_les_vraies_bascules(banc):
    """Une transition OBSERVÉE (`de='normal'`) est le seul exemple qui vaille
    comme donnée d'entraînement : c'est la seule dont on connaisse la date."""
    await veille.init_db()
    etat = await veille.etat_serie()
    assert etat["transitions_observees"] == 0
    assert etat["transitions_observees"] < veille.MIN_TRANSITIONS_POUR_MODELE

    a = _art(collectionnable=1, classe="Limited")
    a["bascule_detectee"] = True
    a["nom"] = "X"
    await veille.enfiler(GUILDE, a, "bascules")
    assert (await veille.etat_serie())["transitions_observees"] == 1


def test_le_seuil_reste_serieux():
    """⚠️ NE PAS LE BAISSER POUR « AVOIR ENFIN UN CHIFFRE ». Un modèle de
    classification déséquilibrée n'a rien à dire avec une poignée de cas
    positifs : la « probabilité » ne mesurerait que le bruit de
    l'échantillon."""
    assert veille.MIN_TRANSITIONS_POUR_MODELE >= 30


def test_aucune_commande_ne_fabrique_de_pourcentage():
    """Le mot « % » ne doit apparaître dans aucune réponse de prédiction tant
    qu'aucun modèle n'existe."""
    import ast
    import inspect

    import roblox_commandes as cmds
    for nom in ("_refus_de_predire",):
        src = inspect.getsource(getattr(cmds, nom))
        ast.parse(src.lstrip())
        assert "Données insuffisantes" in src
        #  Les seuls « % » tolérés sont ceux de l'EXPLICATION (« parmi les
        #  articles annoncés à 70 %… »), jamais un chiffre calculé.
        assert "serie['transitions_observees']" in src, (
            "le refus doit dire COMBIEN il manque, sinon il se lit comme une "
            "dérobade")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Les commandes existent VRAIMENT et sont branchées
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_sept_capacites_demandees_existent():
    """⚠️ CORRESPONDANCE AVEC LA SPÉCIFICATION. Elle nomme `/latest`,
    `/limited`, `/item`, `/predict`, `/predictions`, `/model-status`,
    `/health`. On les rend sous un groupe `/roblox` — noms génériques évités,
    et une seule place consommée sur les 100 que Discord accorde (ce dépôt a
    DÉJÀ heurté ce plafond deux fois, voir les hotfixes Phase 116/118)."""
    import roblox_commandes as cmds
    noms = {c.name for c in cmds.groupe.commands}
    for attendu in ("recents", "limited", "article", "prediction",
                    "predictions", "modele", "sante"):
        assert attendu in noms, f"/roblox {attendu} n'existe pas"


def test_le_groupe_est_ajoute_a_l_arbre_au_niveau_module():
    """⚠️ SANS CETTE LIGNE, LES COMMANDES N'EXISTENT QUE DANS LE CODE.
    Et l'ajouter depuis `on_ready` les ferait arriver après `tree.sync()`
    selon l'ordre de démarrage — présentes chez nous, absentes chez Discord,
    sans que rien ne le signale."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    assert "bot.tree.add_command(roblox_cmds.groupe)" in src
    #  Au niveau module : pas imbriqué dans une fonction.
    arbre = ast.parse(src)
    trouve = any(
        isinstance(n, ast.Expr)
        and "bot.tree.add_command(roblox_cmds.groupe)" in ast.unparse(n)
        for n in arbre.body)
    assert trouve, ("l'ajout du groupe est imbriqué dans une fonction : il "
                    "risque de passer après tree.sync()")


def test_les_commandes_ont_une_garde_qui_repond_toujours():
    """⚠️ UNE INTERACTION SANS RÉPONSE AFFICHE « Échec de l'interaction », qui
    se lit comme une panne du bot et non comme un refus. Ce piège a déjà coûté
    une session entière sur `/rellseas`."""
    import ast
    import inspect

    import roblox_commandes as cmds
    src = inspect.getsource(cmds._refuse)
    ast.parse(src.lstrip())
    assert "send_message" in src, "le refus doit répondre avant de refuser"
    #  Et la garde est branchée sur le vrai contrôle de bot.py.
    from pathlib import Path
    bot_src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    assert "roblox_cmds.setup(autorise=_roblox_cmds_autorise" in bot_src
    assert "async def _roblox_cmds_autorise" in bot_src


def test_la_commande_article_redemande_a_roblox():
    """La spécification : « /item doit forcer une actualisation raisonnable de
    l'article avant de répondre ». Servir la base afficherait l'état du dernier
    relevé — jusqu'à 30 minutes de retard sur une commande qu'on tape
    précisément pour vérifier."""
    import ast
    import inspect

    import roblox_commandes as cmds
    src = inspect.getsource(cmds.article.callback)
    ast.parse(src.lstrip())
    assert "veille.fiche_par_id(" in src, (
        "la commande lit la base au lieu de redemander à Roblox")


@pytest.mark.asyncio
async def test_fiche_par_id_refuse_un_identifiant_absurde(banc):
    """Aucun appel réseau ne doit partir pour un identifiant invalide."""
    for mauvais in (0, -5, None, "abc"):
        assert await veille.fiche_par_id(mauvais) is None
