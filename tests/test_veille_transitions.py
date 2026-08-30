"""Les dix contrôles exigés par la spécification du 30/08/2026.

CE QUE LE PROPRIÉTAIRE A SIGNALÉ CE JOUR-LÀ
    « les accessoires qui sont nouveaux et les accessoires qui viennent de
     passer Limited ne marchent pas. »

CE QUE L'ENQUÊTE A TROUVÉ — deux causes différentes, toutes deux mesurées.

  1. LES BASCULES. `amorcer()` marquait les TROIS flux « déjà publié » au
     premier allumage, `bascules` compris. Or elle n'épargne que les articles
     de moins de six heures, et le compte Roblox n'avait rien créé depuis
     38 jours : les 964 articles du catalogue étaient donc marqués, et
     `publiable_dans(..., "bascules")` les refusait TOUS pendant 180 jours.
     La porte était condamnée avant que le premier Limited n'existe.

  2. LES NOUVEAUTÉS. Deux choses se cumulaient : le compte Roblox n'a
     rien créé depuis 38 jours (0 article sur 964 dans la fenêtre de six
     heures — ce n'est pas une panne), ET la tranche `_TRANCHE_FLUX` coupait
     le lot AVANT publication alors que l'article venait d'être écrit en base.
     Rejoué en exécution : 20 nouveautés éligibles → 5 publiées, puis 0, puis
     0. Quinze perdues pour toujours, sous un journal qui imprimait
     « Rien n'est perdu. »

⚠️ CES TESTS TOURNENT SUR UNE VRAIE BASE SQLite, PAS SUR DES DOUBLURES.
C'est délibéré : ce qu'on éprouve ici est justement le comportement de la
BASE — une contrainte d'unicité, une transaction, une reprise après coupure.
Une doublure en mémoire prouverait seulement que la doublure fonctionne.
"""
from __future__ import annotations

import ast
import contextlib
import json
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

import roblox_veille as veille


# ═══════════════════════════════════════════════════════════════════════════════
#  Le banc
# ═══════════════════════════════════════════════════════════════════════════════

GUILDE = 4242


def _iso(heures: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=heures)).isoformat()


def _brut(aid: int, *, restrictions=None, age_h: float = 24.0, nom=None):
    """Un article tel que l'API le rend. Mêmes champs que la vraie réponse.

    ⚠️ Les noms de champs viennent d'une réponse RÉELLE mesurée le 30/08 :
    `itemCreatedUtc`, `itemRestrictions`, `favoriteCount`… S'en écarter ferait
    passer le test sur des données que `_normaliser` n'aurait jamais vues.
    """
    return {
        "id": aid,
        "name": nom or f"Accessoire {aid}",
        "itemType": "Asset",
        "itemCreatedUtc": _iso(age_h).replace("+00:00", "Z"),
        "itemRestrictions": list(restrictions or []),
        "price": 100,
        "favoriteCount": 7,
        "creatorTargetId": 1,
        "creatorType": "User",
    }


@pytest.fixture
def banc(tmp_path, monkeypatch):
    """Branche le module sur une base SQLite jetable. Rend la config vivante."""
    chemin = tmp_path / "veille.db"
    conf: dict = {}

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_gid):
        return dict(conf)

    async def _db_set(_gid, cle, val):
        conf[cle] = val
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                 log=lambda *a, **k: None)
    return conf


async def _preparer(banc):
    await veille.init_db()
    return banc


async def _voir(bruts: list) -> dict:
    """Un passage de détection complet, comme la boucle le fait."""
    return await veille.comparer_et_enregistrer(veille._normaliser(bruts))


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 1 — un article DÉJÀ Limited à l'amorce ne déclenche rien
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_1_un_limited_present_a_lamorce_ne_declenche_rien(banc):
    await _preparer(banc)
    evts = await _voir([_brut(1, restrictions=["Limited"])])

    #  Il est « nouveau » au sens de la base (jamais vu), mais ce n'est PAS
    #  une bascule : on ne l'a jamais connu non collectionnable.
    assert [a["asset_id"] for a in evts["nouveaux"]] == [1]
    assert evts["bascules"] == []
    #  Et le flux « bascules » le refuse, quel que soit son âge.
    assert veille.age_publiable(evts["nouveaux"][0], "bascules") is False


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 2 — normal → Limited produit UNE annonce, et une seule
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_2_normal_puis_limited_produit_exactement_une_annonce(banc):
    await _preparer(banc)
    await _voir([_brut(1)])                          # vu non collectionnable
    evts = await _voir([_brut(1, restrictions=["Limited"])])

    assert [a["asset_id"] for a in evts["bascules"]] == [1]
    a = evts["bascules"][0]
    assert a["bascule_detectee"] is True
    assert veille.age_publiable(a, "bascules") is True

    #  ⚠️ ET LA PORTE DOIT ÊTRE OUVERTE. C'est ici que le défaut du 30/08 se
    #  serait vu : avec l'ancienne amorce, cette assertion rendait False.
    assert await veille.publiable_dans(GUILDE, 1, "bascules") is True

    #  Une seule entrée en file, même si la détection la revoit.
    assert await veille.enfiler(GUILDE, a, "bascules") is True
    assert await veille.enfiler(GUILDE, a, "bascules") is False
    file = await veille.etat_file(GUILDE)
    assert file["attente"] == 1


@pytest.mark.asyncio
async def test_2bis_lamorce_ne_condamne_plus_le_flux_des_bascules(banc, monkeypatch):
    """⚠️ LA PREUVE DU DÉFAUT PRINCIPAL, ET DE SA RÉPARATION.

    Sans ce test, le correctif ne prouve rien. On rejoue exactement la
    situation du propriétaire : un catalogue entier trop vieux pour la fenêtre
    de six heures, une amorce, puis un article qui passe Limited.
    """
    await _preparer(banc)
    catalogue = [_brut(i, age_h=900.0) for i in range(1, 6)]

    async def _faux_releve(limite=120):
        return {"articles": veille._normaliser(catalogue), "code": 200,
                "echecs": 0}

    #  ⚠️ `monkeypatch`, PAS UNE AFFECTATION SUIVIE D'UN `del`. La version
    #  précédente faisait `veille.relever_nouveautes = _faux` puis
    #  `del veille.relever_nouveautes` : le `del` supprime le nom du MODULE,
    #  donc la vraie fonction disparaissait pour tout le reste de la session
    #  de test. Le défaut est resté invisible jusqu'à ce qu'un test suivant
    #  la référence — il a alors levé un AttributeError sur du code sain.
    monkeypatch.setattr(veille, "relever_nouveautes", _faux_releve)
    absorbes = await veille.amorcer(GUILDE)

    #  Tous absorbés : aucun n'a moins de six heures.
    assert absorbes == 5
    #  Les flux d'ÉTAT sont bien marqués…
    assert await veille.publiable_dans(GUILDE, 1, "nouveautes") is False
    #  … mais PAS le flux d'ÉVÉNEMENT. C'était tout le défaut.
    assert await veille.publiable_dans(GUILDE, 1, "bascules") is True, (
        "l'amorce a de nouveau condamné les bascules : le propriétaire ne "
        "verrait plus jamais un passage en Limited")


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 3 — Limited → Limited ne produit rien
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_3_limited_vers_limited_ne_produit_rien(banc):
    await _preparer(banc)
    await _voir([_brut(1, restrictions=["Limited"])])
    evts = await _voir([_brut(1, restrictions=["Limited"])])

    assert evts["bascules"] == []
    assert evts["nouveaux"] == []


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 4 — normal → Collectible est classé UGC Limited
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_4_normal_vers_collectible_est_classe_ugc_limited(banc):
    await _preparer(banc)
    await _voir([_brut(1)])
    evts = await _voir([_brut(1, restrictions=["Collectible"])])

    assert len(evts["bascules"]) == 1
    a = evts["bascules"][0]
    assert a["classe"] == veille.CLASSE_COLLECTIBLE
    assert veille.libelle_classe(a["classe"]) == "UGC LIMITED"
    #  Il reste « collectionnable » pour la détection : c'est bien un
    #  événement, seule l'ÉTIQUETTE change.
    assert a["collectionnable"] == 1


@pytest.mark.asyncio
async def test_4bis_les_trois_classes_sont_distinguees(banc):
    """⚠️ L'ORDRE DES TESTS DE CLASSE EST LA RÈGLE. « LimitedUnique » contient
    « limited » : chercher « Limited » d'abord classerait tous les Limited U
    comme de simples Limited, en silence."""
    assert veille._classe_collection(["Limited"]) == veille.CLASSE_LIMITED
    assert veille._classe_collection(["LimitedUnique"]) == veille.CLASSE_LIMITED_U
    assert veille._classe_collection(["Collectible"]) == veille.CLASSE_COLLECTIBLE
    assert veille._classe_collection([]) == ""
    #  Le cas qui piège : les deux présentes à la fois.
    assert veille._classe_collection(
        ["Limited", "LimitedUnique"]) == veille.CLASSE_LIMITED_U
    #  Et trois libellés DIFFÉRENTS, sinon distinguer ne sert à rien.
    libelles = {veille.libelle_classe(c) for c in (
        veille.CLASSE_LIMITED, veille.CLASSE_LIMITED_U,
        veille.CLASSE_COLLECTIBLE)}
    assert len(libelles) == 3


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 5 — un même article n'est JAMAIS annoncé deux fois
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_5_la_contrainte_dunicite_tient_meme_sous_rafale(banc):
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]

    entrees = [await veille.enfiler(GUILDE, a, "bascules") for _ in range(10)]
    assert entrees.count(True) == 1, (
        "dix détections de la même transition doivent produire UNE ligne")

    async with veille._get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM roblox_transitions WHERE asset_id=1") as cur:
            assert (await cur.fetchone())[0] == 1


@pytest.mark.asyncio
async def test_5bis_deux_serveurs_recoivent_chacun_la_leur(banc):
    """L'unicité est PAR SERVEUR : deux guildes doivent chacune voir passer
    l'annonce, sinon la seconde serait muette sans raison."""
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]

    assert await veille.enfiler(GUILDE, a, "bascules") is True
    assert await veille.enfiler(GUILDE + 1, a, "bascules") is True
    assert (await veille.etat_file(GUILDE))["attente"] == 1
    assert (await veille.etat_file(GUILDE + 1))["attente"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 6 — un redémarrage ne perd aucun événement
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_6_une_coupure_avant_lenvoi_ne_perd_rien(banc):
    """⚠️ LE SCÉNARIO RAILWAY. Le redéploiement tue le processus entre la
    détection et l'envoi. Avant la file, tout ce qui était détecté et pas
    encore parti disparaissait avec la mémoire."""
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")

    #  « Redémarrage » : plus rien en mémoire, on relit la base.
    attente = await veille.a_envoyer(GUILDE, limite=12)
    assert len(attente) == 1
    #  La charge suffit à publier sans redemander quoi que ce soit à Roblox.
    assert attente[0]["article"]["asset_id"] == 1
    assert attente[0]["flux"] == "bascules"
    assert attente[0]["article"]["nom"] == "Accessoire 1"

    #  Envoi réussi → la fiche quitte la file, avec l'identifiant du message.
    await veille.marquer_envoye(attente[0]["id"], 987654321)
    assert (await veille.etat_file(GUILDE))["attente"] == 0
    async with veille._get_db() as db:
        async with db.execute(
            "SELECT message_id FROM roblox_transitions WHERE id=?",
                (attente[0]["id"],)) as cur:
            assert (await cur.fetchone())[0] == 987654321


@pytest.mark.asyncio
async def test_6bis_une_fiche_non_envoyee_reste_en_file(banc):
    """Et surtout : elle ne sort pas de la file tant qu'elle n'est pas partie.
    L'ordre des deux écritures est le correctif lui-même."""
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")

    ligne = (await veille.a_envoyer(GUILDE))[0]
    await veille.noter_echec_envoi(ligne["id"], "salon interdit")
    assert (await veille.etat_file(GUILDE))["attente"] == 1, (
        "un envoi raté ne doit PAS faire disparaître la fiche")

    #  Mais pas indéfiniment : au-delà du plafond, on abandonne, sinon un
    #  salon supprimé ferait grossir la file sans fin.
    for _ in range(veille.MAX_ESSAIS_ENVOI):
        await veille.noter_echec_envoi(ligne["id"], "salon interdit")
    etat = await veille.etat_file(GUILDE)
    assert etat["attente"] == 0 and etat["abandonnees"] == 1


@pytest.mark.asyncio
async def test_6ter_la_purge_nefface_jamais_ce_qui_attend(banc):
    """Purger une ligne en attente la remettrait en file au passage suivant —
    donc la republierait. La contrainte d'unicité ne protège que tant que la
    ligne existe."""
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")

    #  On vieillit artificiellement la ligne de deux ans.
    vieux = (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
    async with veille._get_db() as db:
        await db.execute(
            "UPDATE roblox_transitions SET detecte_le=?", (vieux,))
        await db.commit()

    await veille.purger()
    assert (await veille.etat_file(GUILDE))["attente"] == 1, (
        "la purge a effacé une fiche qui n'était jamais partie")


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 7 — un 429 est correctement réessayé
# ═══════════════════════════════════════════════════════════════════════════════

def test_7_le_repli_est_exponentiel_et_disperse():
    """⚠️ MESURE DU 30/08 : sur `catalog/v1/catalog/items/details`, le 429 rend
    `retry-after: 5` ET `x-ratelimit-reset: 12` — deux valeurs qui se
    contredisent, et un corps vide. Attendre 5 s ne suffisait pas."""
    entetes = {"Retry-After": "5", "x-ratelimit-reset": "12"}
    assert veille._attente_429(entetes) == pytest.approx(14.0), (
        "on doit prendre la PLUS GRANDE des annonces, pas la première trouvée")

    #  La reprise s'allonge, et deux applications sur la même IP partagée ne
    #  repartent pas à la même seconde.
    t1 = [veille._attente_429_progressive(entetes, 1) for _ in range(40)]
    t2 = [veille._attente_429_progressive(entetes, 2) for _ in range(40)]
    assert min(t1) < max(t1), "sans aléa, deux clients se resynchronisent"
    assert sum(t2) / len(t2) > sum(t1) / len(t1), (
        "la seconde reprise doit attendre plus longtemps que la première")
    #  Et jamais hors des bornes, dans un sens comme dans l'autre.
    for v in t1 + t2:
        assert veille.ATTENTE_429_MIN <= v <= veille.ATTENTE_429_MAX


def test_7bis_le_nombre_de_reprises_est_borne():
    """Insister sans fin garderait l'IP partagée de Railway sous le mur."""
    assert veille.MAX_TENTATIVES_429 == 3
    import ast
    import inspect
    src = inspect.getsource(veille._appel_avec_reprise)
    assert "MAX_TENTATIVES_429" in src, (
        "la boucle de reprise doit lire la constante, pas un chiffre en dur")
    ast.parse(src.lstrip())


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLE 8 — un ancien article MODIFIÉ n'est pas présenté comme nouveau
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_8_un_vieil_article_remonte_nest_pas_annonce_comme_nouveau(banc):
    """⚠️ LE PIÈGE QUE LA SPÉCIFICATION NOMME. Le tri du catalogue peut faire
    remonter un article ancien simplement modifié. Il est « jamais vu » du
    point de vue de la base — mais il n'a pas été créé aujourd'hui, et le dire
    serait faux."""
    await _preparer(banc)
    evts = await _voir([_brut(1, age_h=900.0)])       # 37 jours

    assert [a["asset_id"] for a in evts["nouveaux"]] == [1]
    assert veille.age_publiable(evts["nouveaux"][0], "nouveautes") is False, (
        "un article de 37 jours ne doit pas être annoncé comme une nouveauté")


@pytest.mark.asyncio
async def test_8bis_la_date_de_creation_vient_de_roblox_jamais_de_nous(banc):
    """`first_seen_at` ne doit JAMAIS être présenté comme la date de création.
    Ici : `cree_le` vient de `itemCreatedUtc`, `vu_le` est à nous, et les deux
    ne se confondent pas."""
    await _preparer(banc)
    await _voir([_brut(1, age_h=900.0)])
    async with veille._get_db() as db:
        async with db.execute(
            "SELECT cree_le, vu_le FROM roblox_articles WHERE asset_id=1") as cur:
            cree, vu = await cur.fetchone()
    assert veille._jours_depuis(cree) >= 36
    assert veille._jours_depuis(vu) == 0
    assert cree != vu


@pytest.mark.asyncio
async def test_8ter_une_date_illisible_ne_publie_pas_de_nouveaute(banc):
    """Ne pas pouvoir prouver « récent » n'autorise pas à l'affirmer."""
    await _preparer(banc)
    sans_date = _brut(1)
    sans_date.pop("itemCreatedUtc")
    evts = await _voir([sans_date])
    assert veille.age_publiable(evts["nouveaux"][0], "nouveautes") is False


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRÔLES 9 et 10 — aucune probabilité n'est fabriquée
# ═══════════════════════════════════════════════════════════════════════════════

def test_9_aucune_variable_posterieure_ne_sert_a_predire():
    """⚠️ LA FUITE DE DONNÉES QUE LA SPÉCIFICATION INTERDIT.

    `lowestResalePrice`, `hasResellers` et la présence actuelle de `Limited`
    n'existent QU'APRÈS le passage en Limited. S'en servir pour estimer un
    passage FUTUR, c'est prédire le passé : le score paraîtrait excellent et
    ne vaudrait rien.

    ⚠️ CE QUE CE TEST A TROUVÉ, ET QU'IL FAUT DIRE PLUTÔT QUE MASQUER.
    `veille.indice()` s'appuie BEL ET BIEN sur `prix_revente`, `revendeurs` et
    `collectionnable` — les trois variables que la spécification nomme comme
    fuites. Ce n'est pas une catastrophe aujourd'hui, pour une raison
    vérifiable : `indice()` n'est appelé par AUCUN chemin de publication du
    bot (seul `outils/verif_veille_roblox.py` s'en sert), et le flux
    « surveiller » qui le portait ne publie plus depuis le 18/08.

    Ce test verrouille donc les deux moitiés de la vérité :
      · aucun score contaminé n'atteint un salon ;
      · et le jour où quelqu'un rebranchera `indice()` ou bâtira un vrai
        modèle, ce test tombera et rappellera pourquoi.
    """
    import ast
    import inspect
    import pathlib

    corps = inspect.getsource(veille.indice)
    ast.parse(corps.lstrip())
    contaminees = [f for f in ("prix_revente", "revendeurs", "collectionnable")
                   if f in corps]
    if not contaminees:
        return          # quelqu'un l'a assaini : tant mieux, rien à garder

    #  Puisque l'indice est contaminé, il ne doit toucher AUCUN salon.
    racine = pathlib.Path(__file__).resolve().parent.parent
    for fichier in ("bot.py", "roblox_panneau.py", "roblox_news.py"):
        src = (racine / fichier).read_text(encoding="utf-8")
        assert "veille.indice(" not in src and "roblox_module.indice(" not in src, (
            f"{fichier} rebranche `indice()`, qui s'appuie sur "
            f"{contaminees} — des variables qui n'existent qu'APRÈS le "
            f"passage en Limited. Prédire avec elles, c'est prédire le passé : "
            f"le score paraîtrait excellent et ne vaudrait rien.")

    #  Et le flux qui le portait doit rester muet.
    assert veille.PRIORITE_FLUX.get("surveiller") is not None
    src_bot = (racine / "bot.py").read_text(encoding="utf-8")
    assert '"surveiller"' not in src_bot.split(
        "async def veille_roblox_task")[-1].split("\nasync def ")[0], (
        "le flux « surveiller » republie : il porte un indice contaminé")


def test_10_aucune_probabilite_nest_affichee_sans_horizon_ni_modele():
    """⚠️ CE QU'ON REFUSE DE PROMETTRE, ET POURQUOI C'EST LA BONNE RÉPONSE.

    La spécification demande une probabilité calibrée à 30 et 90 jours. Mesuré
    le 30/08 : `offSaleDeadline` est nul sur 1 784 articles, `itemStatus` est
    vide sur 159 sur 159, et sept points d'API testés ne donnent AUCUNE date de
    passage en Limited. Il n'existe donc aucune vérité terrain pour calibrer
    quoi que ce soit — et la spécification elle-même tranche : « Si les données
    sont insuffisantes, afficher "données insuffisantes" au lieu de fabriquer
    un pourcentage. »

    Ce test verrouille ce refus : tant qu'aucune série temporelle n'est
    constituée, le module ne doit pas produire de pourcentage.
    """
    assert not hasattr(veille, "probabilite_limited"), (
        "une probabilité est apparue sans jeu d'entraînement : elle serait "
        "fabriquée, et la spécification l'interdit explicitement")
    #  L'indice, lui, existe — mais il n'est PAS un pourcentage, et il ne
    #  s'affiche qu'au-dessus d'un seuil élevé, faute de quoi il se lirait
    #  comme un verdict alors qu'il n'est qu'une absence de signal.
    assert veille.SEUIL_INDICE_AFFICHE >= 60


# ═══════════════════════════════════════════════════════════════════════════════
#  La rotation du curseur — 24 % du flux Limited était lu, et toujours le même
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_la_rotation_du_curseur_finit_par_tout_couvrir(banc, monkeypatch):
    """⚠️ MESURÉ LE 30/08 : le flux Limited compte 998 articles en 9 pages ;
    le relevé n'en lisait que 2, TOUJOURS LES MÊMES — 238 sur 998, soit 24 %.
    Les 76 % restants n'étaient jamais comparés à leur état antérieur, donc
    leur passage en Limited ne pouvait pas être vu."""
    await _preparer(banc)
    TOTAL, PAR_PAGE = 900, 120
    servies = []

    async def _faux(params, source, max_pages=None, curseur_depart=None):
        debut = int(curseur_depart or 0)
        pages, ids = 0, []
        while pages < (max_pages or 99) and debut < TOTAL:
            fin = min(debut + PAR_PAGE, TOTAL)
            ids += list(range(debut + 1, fin + 1))
            debut, pages = fin, pages + 1
        servies.append(list(ids))
        return {"articles": [{"asset_id": i} for i in ids], "code": 200,
                "echecs": 0, "curseur_suivant": (str(debut) if debut < TOTAL
                                                 else None),
                "curseur_refuse": False}

    monkeypatch.setattr(veille, "_relever_catalogue", _faux)

    vus = set()
    for _ in range(5):
        out = await veille.relever_collectionnables(limite=120)
        vus |= {a["asset_id"] for a in out["articles"]}

    assert len(vus) == TOTAL, (
        f"cinq passages ne couvrent que {len(vus)} articles sur {TOTAL} — "
        f"la rotation du curseur ne tourne pas")
    #  Le coût par passage n'a PAS bougé : c'est toute la raison du dispositif.
    assert all(len(s) <= 2 * PAR_PAGE for s in servies)
    #  Et le premier passage ne relit pas ce que le deuxième a lu.
    assert servies[0] != servies[1]


@pytest.mark.asyncio
async def test_un_curseur_perime_ne_bloque_pas_le_flux_pour_toujours(banc, monkeypatch):
    """Un curseur mémorisé expire. Sans repli, le relevé resterait coincé
    dessus à CHAQUE passage, muet pour toujours."""
    await _preparer(banc)
    await veille._curseur_ecrit("collectionnables", "curseur_mort", 0)

    async def _faux(params, source, max_pages=None, curseur_depart=None):
        return {"articles": [], "code": 400, "echecs": 1,
                "curseur_suivant": None, "curseur_refuse": True}

    monkeypatch.setattr(veille, "_relever_catalogue", _faux)
    await veille.relever_collectionnables(limite=120)

    curseur, tours = await veille._curseur_lu("collectionnables")
    assert curseur is None, "le curseur périmé doit être oublié"
    assert tours == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  La réparation des données déjà écrites
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_la_migration_efface_les_marques_posees_a_tort(banc):
    """⚠️ UN CORRECTIF DE CODE NE RÉPARE PAS UNE BASE. Les marques posées par
    l'ancienne amorce vivent en production : sans cette migration, le
    propriétaire garderait un flux muet malgré le correctif."""
    await _preparer(banc)
    #  ⚠️ `init_db` a DÉJÀ joué la migration sur cette base neuve — c'est
    #  précisément ce qu'on veut en production (elle tourne au démarrage,
    #  avant tout le reste). Ici on rejoue donc l'histoire à l'envers : on
    #  remet le dépôt dans l'état d'AVANT, marque de migration comprise.
    async with veille._get_db() as db:
        await db.execute("DELETE FROM roblox_migrations")
        await db.commit()
    for aid in range(1, 6):
        await veille.marquer_publie(GUILDE, aid, "bascules")
        await veille.marquer_publie(GUILDE, aid, "nouveautes")
    assert await veille.publiable_dans(GUILDE, 1, "bascules") is False

    efface = await veille._migrer_amorce_bascules()
    assert efface == 5
    assert await veille.publiable_dans(GUILDE, 1, "bascules") is True
    #  Les autres flux ne sont PAS touchés : on répare une erreur précise.
    assert await veille.publiable_dans(GUILDE, 1, "nouveautes") is False

    #  Et elle ne se rejoue pas : sinon elle effacerait de vraies marques.
    for aid in range(1, 6):
        await veille.marquer_publie(GUILDE, aid, "bascules")
    assert await veille._migrer_amorce_bascules() == 0
    assert await veille.publiable_dans(GUILDE, 1, "bascules") is False


@pytest.mark.asyncio
async def test_effacer_les_marques_ne_peut_rien_republier(banc):
    """⚠️ LA DÉFENSE DE LA MIGRATION, ET IL FAUT POUVOIR LA TENIR.

    Effacer une marque de publication fait normalement courir un risque de
    doublon. Pas ici : publier dans « bascules » exige DEUX autorisations, et
    la seconde — `bascule_detectee` — n'est jamais posée sur un article déjà
    Limited, quoi qu'on efface.
    """
    await _preparer(banc)
    evts = await _voir([_brut(1, restrictions=["Limited"])])   # déjà Limited
    await veille._migrer_amorce_bascules()

    assert await veille.publiable_dans(GUILDE, 1, "bascules") is True
    assert veille.age_publiable(evts["nouveaux"][0], "bascules") is False, (
        "la porte est ouverte, mais l'article n'a pas de bascule observée : "
        "rien ne peut sortir, et c'est ce qui rend la migration sans risque")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le mode simulation — éprouver une transition sans fausse annonce publique
# ═══════════════════════════════════════════════════════════════════════════════

def _corps_boucle() -> str:
    import ast as _ast
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    for n in _ast.walk(_ast.parse(src)):
        if isinstance(n, _ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            return _ast.unparse(n)
    raise AssertionError("veille_roblox_task introuvable")


def test_simulation_le_reglage_existe_et_est_eteint_par_defaut():
    """Un mode qui retient les envois ne doit JAMAIS être actif par accident."""
    assert veille.CLES_DEFAUT["roblox_veille_simulation"] is False


def test_simulation_la_boucle_sarrete_avant_lenvoi():
    """⚠️ LA GARDE DOIT ÊTRE AVANT `publier`, pas après. Après, l'annonce
    serait partie — c'est exactement ce que le mode existe pour empêcher."""
    corps = _corps_boucle()
    assert "roblox_veille_simulation" in corps, (
        "la boucle ne lit pas l'interrupteur : le mode n'existe pas")
    i_garde = corps.index("if _simu:")
    i_envoi = corps.index("roblox_ui.publier(")
    assert i_garde < i_envoi, (
        "la garde de simulation passe APRÈS l'envoi : la fausse annonce "
        "serait déjà partie")


def test_simulation_ne_marque_rien_comme_envoye():
    """La fiche doit RESTER en file : éteindre l'interrupteur doit la faire
    partir pour de bon. La marquer envoyée la perdrait silencieusement."""
    corps = _corps_boucle()
    bloc = corps.split("if _simu:")[1].split("continue")[0]
    for interdit in ("marquer_envoye", "marquer_publie"):
        assert interdit not in bloc, (
            f"le mode simulation appelle `{interdit}` : la fiche serait "
            f"consommée sans jamais avoir été publiée")


def test_simulation_a_un_bouton_et_un_capteur():
    """⚠️ « Une fonction non appelée n'est pas opérationnelle, même parfaite. »
    Une clé de configuration que personne ne peut basculer est du code mort."""
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent
           / "roblox_panneau.py").read_text(encoding="utf-8")
    assert 'custom_id="rblx_toggle_simu"' in src, "aucun bouton"
    assert "b_simu.callback = self._cb_toggle_simulation" in src, (
        "le bouton n'est branché sur rien — il afficherait « échec de "
        "l'interaction »")
    assert "async def _cb_toggle_simulation" in src, "le capteur n'existe pas"
    #  Et le chemin manuel doit l'honorer aussi, sinon le bouton « Relever
    #  maintenant » contournerait la simulation.
    assert 'c.get("roblox_veille_simulation")' in src, (
        "le relevé manuel ignore la simulation : il publierait quand même")


def test_le_bouton_manuel_passe_par_la_file_lui_aussi():
    """Il avait EXACTEMENT la même famine : il tronquait à 10 et 5 alors que
    `comparer_et_enregistrer` venait d'écrire les articles en base."""
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent
           / "roblox_panneau.py").read_text(encoding="utf-8")
    assert "veille.enfiler(" in src, "le bouton manuel ne met rien en file"
    assert "veille.a_envoyer(" in src, "le bouton manuel ne tire pas de la file"
    assert "10 if cle == \"bascules\" else 5" not in src, (
        "la tranche du bouton manuel est revenue")
    assert src.index("veille.enfiler(") < src.index("veille.a_envoyer("), (
        "on met en file d'abord, on tire ensuite")


# ═══════════════════════════════════════════════════════════════════════════════
#  Les défauts trouvés en RÉFUTATION ADVERSE le 30/08 — chacun verrouillé
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_B4_deux_tireurs_ne_publient_pas_la_meme_fiche(banc):
    """⚠️ LE DÉFAUT QUE J'AVAIS DÉCLARÉ IMPOSSIBLE.

    J'avais écrit que la contrainte UNIQUE garantissait « jamais deux
    annonces ». Faux : elle empêche d'ENFILER deux fois, pas d'ENVOYER deux
    fois. `a_envoyer` n'était qu'un SELECT, sans réservation — la boucle et le
    bouton « Relever maintenant » pouvaient tirer les mêmes lignes pendant les
    ~2 minutes où la boucle enrichit et publie. Rejoué en réfutation :
    6 messages pour une file de 3.
    """
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")

    #  Les deux chemins tirent la MÊME ligne : c'est le cas réel.
    boucle = (await veille.a_envoyer(GUILDE))[0]
    bouton = (await veille.a_envoyer(GUILDE))[0]
    assert boucle["id"] == bouton["id"]

    pris = [await veille.reserver(boucle["id"], boucle["essais"]),
            await veille.reserver(bouton["id"], bouton["essais"])]
    assert pris.count(True) == 1, (
        "deux tireurs ont réservé la même fiche : le salon la recevra en "
        "double")


@pytest.mark.asyncio
async def test_B4bis_une_fiche_deja_envoyee_ne_se_reserve_plus(banc):
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")
    ligne = (await veille.a_envoyer(GUILDE))[0]

    assert await veille.marquer_envoye(ligne["id"], 111) is True
    assert await veille.reserver(ligne["id"], ligne["essais"]) is False


@pytest.mark.asyncio
async def test_G3_une_bascule_passe_devant_un_arriere_de_nouveautes(banc):
    """⚠️ `PRIORITE_FLUX` dit qu'une bascule est l'information la plus forte,
    mais la file se vidait par ordre chronologique pur : un arriéré de
    nouveautés la faisait attendre. Mesuré en réfutation : 49 fiches devant
    elle, soit 2 h 30 de retard sur un événement dont tout l'intérêt est
    d'être frais."""
    await _preparer(banc)
    #  Vingt nouveautés entrent en file AVANT la bascule.
    evts = await _voir([_brut(i, age_h=1.0) for i in range(1, 21)])
    for x in evts["nouveaux"]:
        await veille.enfiler(GUILDE, x, "nouveautes")
    await _voir([_brut(99)])
    b = (await _voir([_brut(99, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, b, "bascules")

    lot = await veille.a_envoyer(GUILDE, limite=5)
    assert lot[0]["flux"] == "bascules", (
        "la bascule attend derrière l'arriéré : elle sera annoncée en retard")
    assert lot[0]["article"]["asset_id"] == 99


@pytest.mark.asyncio
async def test_G1_les_abandonnees_finissent_par_etre_purgees(banc):
    """Une ligne à essais >= MAX n'est ni partie ni en attente : rien ne
    l'effaçait. Mesurée en réfutation encore présente après dix ans simulés."""
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")
    ligne = (await veille.a_envoyer(GUILDE))[0]
    for _ in range(veille.MAX_ESSAIS_ENVOI + 1):
        await veille.noter_echec_envoi(ligne["id"], "salon supprimé")
    assert (await veille.etat_file(GUILDE))["abandonnees"] == 1

    #  Fraîche : on la garde (le staff peut encore la relancer).
    await veille.purger()
    assert (await veille.etat_file(GUILDE))["abandonnees"] == 1

    #  Vieille de deux ans : elle part avec le reste.
    vieux = (datetime.now(timezone.utc) - timedelta(days=730)).isoformat()
    async with veille._get_db() as db:
        await db.execute("UPDATE roblox_transitions SET detecte_le=?", (vieux,))
        await db.commit()
    await veille.purger()
    assert (await veille.etat_file(GUILDE))["abandonnees"] == 0


@pytest.mark.asyncio
async def test_G1bis_le_staff_peut_relancer_une_fiche_abandonnee(banc):
    """⚠️ SANS CE CHEMIN, LA PANNE RÉPARÉE LAISSAIT LA FICHE MORTE. `enfiler`
    refuse de réinsérer (unicité) et « ♻️ Tout republier » n'efface que
    `roblox_publies` : rien ne ramenait une ligne abandonnée."""
    await _preparer(banc)
    await _voir([_brut(1)])
    a = (await _voir([_brut(1, restrictions=["Limited"])]))["bascules"][0]
    await veille.enfiler(GUILDE, a, "bascules")
    ligne = (await veille.a_envoyer(GUILDE))[0]
    for _ in range(veille.MAX_ESSAIS_ENVOI + 1):
        await veille.noter_echec_envoi(ligne["id"], "salon supprimé")
    assert await veille.a_envoyer(GUILDE) == []

    assert await veille.relancer_abandonnees(GUILDE) == 1
    assert len(await veille.a_envoyer(GUILDE)) == 1


@pytest.mark.asyncio
async def test_B2_un_releve_tronque_ne_rembobine_pas_le_curseur(banc, monkeypatch):
    """⚠️ LE DÉFAUT LE PLUS SOURNOIS DE LA RÉFUTATION.

    Le 429 est requalifié en 200 (à raison), mais la sortie par 429 laissait
    `curseur_suivant` à None — ce que l'appelant lisait comme « tour terminé ».
    La rotation REMBOBINAIT au début du flux, et les pages suivantes n'étaient
    jamais atteintes tant que le 429 retombait au même rang. Le bilan imprimait
    pourtant « reprise au prochain passage ».
    """
    await _preparer(banc)
    await veille._curseur_ecrit("collectionnables", "page_5", 0)

    async def _tronque(params, source, max_pages=None, curseur_depart=None):
        #  Ce que rend `_relever_catalogue` quand un 429 coupe la pagination :
        #  code requalifié en 200, `tronque` posé, et la page ratée à rejouer.
        return {"articles": [{"asset_id": 1}], "code": 200, "echecs": 0,
                "tronque": True, "curseur_suivant": curseur_depart,
                "curseur_refuse": False}

    monkeypatch.setattr(veille, "_relever_catalogue", _tronque)
    await veille.relever_collectionnables(limite=120)

    curseur, tours = await veille._curseur_lu("collectionnables")
    assert curseur == "page_5", (
        "le curseur a été rembobiné : les pages suivantes du flux Limited ne "
        "seront jamais atteintes")
    assert tours == 0, (
        "un relevé tronqué a été compté comme un tour complet — on croirait "
        "avoir couvert les 998 articles")


@pytest.mark.asyncio
async def test_B2bis_un_tour_reellement_fini_avance_le_compteur(banc, monkeypatch):
    """La contre-épreuve : sans elle, le test ci-dessus passerait sur un code
    qui n'avance JAMAIS le compteur."""
    await _preparer(banc)

    async def _fini(params, source, max_pages=None, curseur_depart=None):
        return {"articles": [{"asset_id": 1}], "code": 200, "echecs": 0,
                "tronque": False, "curseur_suivant": None,
                "curseur_refuse": False}

    monkeypatch.setattr(veille, "_relever_catalogue", _fini)
    await veille.relever_collectionnables(limite=120)
    curseur, tours = await veille._curseur_lu("collectionnables")
    assert curseur is None and tours == 1


def test_B3_le_vidage_de_la_file_survit_a_une_panne_de_releve():
    """⚠️ SURVIVRE À UNE PANNE DE RELEVÉ EST LA RAISON D'ÊTRE D'UNE FILE.

    Les trois étapes étaient DANS le test du code HTTP — un 429 terminal sur
    le relevé du catalogue général, celui qui pagine neuf pages, et rien ne se
    vidait. Test STRUCTUREL (AST), pas un grep : on vérifie que l'appel de
    tirage n'est pas un descendant de cette garde.
    """
    import ast as _ast
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    boucle = next(n for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, _ast.AsyncFunctionDef)
                  and n.name == "veille_roblox_task")

    gardes = [n for n in _ast.walk(boucle)
              if isinstance(n, _ast.If)
              and 'rel["code"] == 200' in _ast.unparse(n.test).replace("'", '"')]
    assert gardes, "la garde sur le code HTTP a disparu — test à revoir"
    for garde in gardes:
        dedans = "".join(_ast.unparse(x) for x in garde.body)
        assert "a_envoyer(" not in dedans, (
            "le tirage de la file est enfermé dans le test du code HTTP : une "
            "panne de relevé empêcherait de vider la file, ce qu'elle existe "
            "précisément pour éviter")
        assert "etat_file(" not in dedans, (
            "l'état de la file ne serait pas imprimé quand le relevé échoue — "
            "le bilan dirait « 0 publication » sans dire que N fiches "
            "attendent")


def test_M4_le_hasard_n_abrege_jamais_l_attente_annoncee():
    """⚠️ LE COMMENTAIRE DISAIT L'INVERSE DU CODE. Le tirage allait de 0,75 à
    1,25 : au-delà d'une annonce de 6 s, le tirage bas rendait une attente PLUS
    COURTE que ce que Roblox venait d'exiger — on repartait droit dans le mur
    en croyant faire mieux."""
    entetes = {"x-ratelimit-reset": "40"}
    annonce = veille._attente_429(entetes)
    for _ in range(400):
        v = veille._attente_429_progressive(entetes, 1)
        assert v >= min(annonce, veille.ATTENTE_429_MAX) - 1e-9, (
            f"attente {v:.1f} s alors que Roblox en annonce {annonce:.1f}")


def test_M5_le_429_terminal_est_compte_lui_aussi():
    """L'incrément vivait sous la condition de reprise : le 429 qui coûte
    vraiment une page n'était jamais compté, et « 429=0 » pouvait s'afficher
    sur un passage tronqué."""
    import ast as _ast
    import inspect
    src = inspect.getsource(veille._appel_avec_reprise)
    _ast.parse(src.lstrip())
    corps = src.replace(" ", "")
    i_compte = corps.index('stats["n429"]=int(stats.get("n429")or0)+1')
    i_reprise = corps.index("tentative<MAX_TENTATIVES_429")
    assert i_compte < i_reprise, (
        "le comptage du 429 est de nouveau sous la condition de reprise")


def test_G4_la_simulation_ne_mange_pas_le_budget_des_autres_serveurs():
    """Un serveur en simulation placé en tête consommait les douze unités du
    passage sans jamais rien publier : le suivant recevait zéro fiche,
    définitivement."""
    import ast as _ast
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    boucle = next(_ast.unparse(n) for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, _ast.AsyncFunctionDef)
                  and n.name == "veille_roblox_task")
    bloc = boucle.split("if _simu:")[1].split("continue")[0]
    assert "_budget -= 1" not in bloc, (
        "la simulation consomme le budget du passage : les autres serveurs "
        "seront affamés sans qu'une seule fiche ne parte")
    #  Et la part est bien calculée par serveur, pas premier arrivé premier servi.
    assert "_part = max(1" in boucle and "limite=min(_part, _reste)" in boucle, (
        "le budget est de nouveau distribué au premier arrivé")


def test_B5_la_simulation_couvre_aussi_les_actualites():
    """Elle ne gardait que les accessoires, pendant que le panneau affirmait
    sans réserve « rien ne part dans un salon » : simulation allumée, les
    billets partaient quand même."""
    import ast as _ast
    import pathlib as _pl
    racine = _pl.Path(__file__).resolve().parent.parent
    boucle = next(_ast.unparse(n) for n in _ast.walk(
        _ast.parse((racine / "bot.py").read_text(encoding="utf-8")))
        if isinstance(n, _ast.AsyncFunctionDef) and n.name == "veille_roblox_task")
    #  La garde doit précéder l'envoi du billet, sinon il est déjà parti.
    i_garde = boucle.index("if _simu_n:")
    i_envoi = boucle.index("roblox_ui.publier_actu(")
    assert i_garde < i_envoi, (
        "la garde de simulation passe après l'envoi du billet")
    #  Et le même chemin dans le bouton manuel.
    pan = (racine / "roblox_panneau.py").read_text(encoding="utf-8")
    assert "if _simu_actu:" in pan and pan.index("if _simu_actu:") < pan.index(
        "if await publier_actu("), (
        "le bouton « Relever maintenant » publie les actualités malgré la "
        "simulation")


# ═══════════════════════════════════════════════════════════════════════════════
#  Les créations RETIRÉES DE LA VENTE — signalées par le propriétaire le 30/08
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Ses mots : « il y a des accessoires qui sont en vente et d'autres qui ne sont
#  pas en vente […] ce ne sont pas les derniers accessoires qui sont créés sur
#  la plateforme. Assure-toi que ton calcul soit vraiment très très bon et qu'il
#  affiche bien les derniers créés. »
#
#  IL AVAIT RAISON, ET C'EST MESURÉ CONTRE L'API RÉELLE LE MÊME JOUR :
#    · relevé du bot                 → 964 articles, le plus récent du 22/07
#    · avec `IncludeNotForSale=true` → 952 articles, le plus récent du **12/08**
#    · articles de moins de 30 jours → **0 sans le drapeau, 2 avec**
#  Les deux dernières créations de Roblox — « Sakura Antlers » (18 j) et
#  « Gold Crown of Ozymandias » (19 j) — sont HORS VENTE. Le bot montrait les
#  derniers accessoires DU MARCHÉ, pas les derniers CRÉÉS.

def test_le_releve_hors_vente_demande_le_bon_drapeau():
    """C'est CE paramètre, et lui seul, qui fait apparaître les créations
    récentes retirées de la vente. Sans lui, elles n'existent pas."""
    import inspect
    src = inspect.getsource(veille.relever_hors_vente)
    ast.parse(src.lstrip())
    assert '"IncludeNotForSale": "true"' in src
    assert '"CreatorTargetId": CREATEUR_ROBLOX' in src, (
        "sans le filtre de créateur, le flux se remplirait d'UGC tiers")
    assert "SortType" in src


@pytest.mark.asyncio
async def test_le_releve_hors_vente_reste_a_deux_pages(monkeypatch):
    """⚠️ « NE PAS SPAMMER UNE RECHERCHE QUI SERT À RIEN. » Paginer ce flux en
    entier doublerait le relevé du catalogue (9 pages de plus toutes les
    30 min) pour un recouvrement de 95 % avec ce qu'on lit déjà. Les créations
    récentes sont en tête de la page 1 — mesuré."""
    vu = {}

    async def _faux(params, source, max_pages=None, curseur_depart=None):
        vu["params"], vu["source"], vu["max_pages"] = params, source, max_pages
        return {"articles": [], "code": 200, "echecs": 0,
                "curseur_suivant": None, "curseur_refuse": False}

    monkeypatch.setattr(veille, "_relever_catalogue", _faux)
    await veille.relever_hors_vente(limite=120)
    assert vu["max_pages"] == veille.MAX_PAGES_HORS_VENTE == 2
    assert vu["source"] == "hors_vente", (
        "la santé de ce relevé doit être suivie SÉPARÉMENT : un flux mort "
        "ressemble à un flux calme")


def test_la_boucle_fusionne_les_NOUVEAUTES_pas_seulement_les_bascules():
    """⚠️ LE POINT QUI COMPTE. C'est précisément dans ce relevé que vivent les
    créations récentes que l'autre ne voit pas : ne fusionner que les bascules
    laisserait « Sakura Antlers » invisible malgré la requête payée."""
    import ast as _ast
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    corps = next(_ast.unparse(n) for n in _ast.walk(_ast.parse(src))
                 if isinstance(n, _ast.AsyncFunctionDef)
                 and n.name == "veille_roblox_task")
    assert "roblox_module.relever_hors_vente(" in corps, (
        "le troisième relevé n'est pas branché : le bot montre encore les "
        "derniers accessoires du marché, pas les derniers créés")

    #  ⚠️ CE TEST ÉTAIT VIDE, ET UNE MUTATION L'A PROUVÉ.
    #  Il découpait sur « CE QUE LA DÉTECTION », qui est un COMMENTAIRE :
    #  `ast.unparse` les supprime tous. Le « bloc » examiné faisait donc 13 000
    #  caractères — tout le corps de la boucle — et contenait « nouveaux »
    #  quoi qu'il arrive. Mutation posée le 30/08 (retirer « nouveaux » de la
    #  boucle de fusion) : **731 tests verts**. Un test qui ne peut pas
    #  échouer est pire qu'un test absent : il fabrique de la confiance.
    #
    #  On lit donc le VRAI nœud : la boucle `for _cle in (...)`.
    boucles = [n for n in _ast.walk(_ast.parse(src))
               if isinstance(n, _ast.For)
               and getattr(n.target, "id", None) == "_cle"]
    assert boucles, "la boucle de fusion `for _cle in (...)` a disparu"
    cles = set()
    for b in boucles:
        try:
            cles |= set(_ast.literal_eval(b.iter))
        except Exception:
            pass
    assert "nouveaux" in cles, (
        "seules les bascules sont fusionnées : les créations hors vente "
        "resteraient invisibles, et la requête serait payée pour rien")
    assert "bascules" in cles


def test_l_age_du_plus_recent_est_calcule_sur_les_DEUX_releves():
    """⚠️ Le calculer sur le seul relevé général annoncerait « 38 jours » alors
    qu'une création de 18 jours existe, retirée de la vente — soit exactement
    le mensonge que le propriétaire a repéré."""
    import ast as _ast
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parent.parent / "bot.py").read_text(
        encoding="utf-8")
    corps = next(_ast.unparse(n) for n in _ast.walk(_ast.parse(src))
                 if isinstance(n, _ast.AsyncFunctionDef)
                 and n.name == "veille_roblox_task")
    bloc = corps.split("_sa['plus_frais_h']")[0][-500:]
    assert "relhv" in bloc, (
        "l'âge du plus récent ignore le relevé hors vente : le bilan mentira")


def test_la_fiche_dit_si_l_article_est_achetable():
    """Depuis que le bot voit les créations retirées de la vente, une fiche
    sans cette ligne enverrait le lecteur sur une page où il ne peut rien
    acheter, sans l'avoir prévenu. Le prix seul ne le dit pas : un article
    hors vente garde son prix affiché."""
    import pathlib as _pl
    pan = (_pl.Path(__file__).resolve().parent.parent
           / "roblox_panneau.py").read_text(encoding="utf-8")
    assert "**Disponibilité**" in pan
    assert "retiré de la vente" in pan


def test_les_trois_releves_ont_des_sources_de_sante_distinctes():
    """Un flux mort ressemble trait pour trait à un flux calme. Trois relevés
    qui partagent un compteur masqueraient la panne de l'un des trois."""
    import inspect
    for fn, attendu in ((veille.relever_nouveautes, "catalogue"),
                        (veille.relever_collectionnables, "collectionnables"),
                        (veille.relever_hors_vente, "hors_vente")):
        src = inspect.getsource(fn)
        assert f'"{attendu}"' in src, f"{fn.__name__} n'étiquette pas sa santé"
