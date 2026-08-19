"""La famine du rang 6 — trouvée le 19/08/2026, prouvée puis corrigée.

CE QUI SE PASSAIT
La publication des actualités TRONQUAIT avant de DÉDUPLIQUER :

    lot = ordonner_publication(billets, 5)      # les 5 plus récents
    for b in lot:
        if await deja_publie(...): continue     # ← trop tard

Un billet déjà sorti occupait donc une des cinq places à CHAQUE passage,
indéfiniment. Et comme la sélection est purement déterministe — tri par date,
`[:5]` — un billet tombé au rang 6 n'y remontait JAMAIS. Les deux seuls
retraits du lot (épinglage, `FRAICHEUR_MAX_JOURS` = 30 j) frappent toujours le
plus VIEUX d'abord, donc le vieillissement jouait contre lui. Aucune file
d'attente, aucun rattrapage nulle part dans le dépôt : le billet était perdu.

⚠️ ET LE JOURNAL AFFIRMAIT LE CONTRAIRE — « repris au prochain passage ».
C'est ce mensonge qui a déclenché l'enquête : la phrase avait été écrite le
matin même, en toute bonne foi, sans vérifier le mécanisme.

POURQUOI ÇA NE SE VOYAIT PAS
En régime calme, un billet neuf est rang 1 au relevé suivant sa création : il
passe. Le défaut ne mordait que sur une rafale de plus de cinq sujets d'une
même source dans un créneau de cadence, un arrêt du bot le temps que cinq
sujets s'accumulent, un budget de publication épuisé, ou des archives de 8 à
30 jours jamais absorbées par l'amorce.

LE CORRECTIF, EN TROIS ÉTAPES ORDONNÉES
  1. dédupliquer sur TOUT le lot — le déjà-sorti ne prend plus de place ;
  2. absorber les trop vieux (marqués sortis, jamais envoyés) — sinon on
     déverserait trois semaines d'archives, interdit par le propriétaire ;
  3. tronquer en dernier — et « repris au prochain passage » devient vrai.

Ces tests simulent DIX passages successifs avec les vraies fonctions de tri,
et exigent qu'aucun billet frais ne reste indéfiniment coincé.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import roblox_news as news
import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PAN = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")


def _billet(tid: int, jours: float):
    from datetime import datetime, timedelta, timezone
    return {"topic_id": tid, "titre": f"Billet {tid}",
            "cree_le": (datetime.now(timezone.utc)
                        - timedelta(days=jours)).isoformat()}


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le mécanisme de famine, reproduit puis interdit
# ═══════════════════════════════════════════════════════════════════════════════

def _simuler(dedup_avant: bool, passages: int = 10) -> set:
    """Rend l'ensemble des `topic_id` publiés après N passages.

    `dedup_avant=False` reproduit l'ANCIEN ordre (troncature d'abord),
    `True` le nouveau. Même lot d'entrée, mêmes fonctions de tri.
    """
    #  Onze billets frais d'une même source, comme le lot observé en production.
    lot = [_billet(100 + i, jours=i * 0.1) for i in range(11)]
    publies: set = set()
    for _ in range(passages):
        if dedup_avant:
            candidats = [b for b in lot if b["topic_id"] not in publies]
            tranche = veille.ordonner_publication(
                candidats, news.MAX_BILLETS_PAR_PASSAGE)
            for b in tranche:
                publies.add(b["topic_id"])
        else:
            tranche = veille.ordonner_publication(
                lot, news.MAX_BILLETS_PAR_PASSAGE)
            for b in tranche:
                if b["topic_id"] in publies:
                    continue
                publies.add(b["topic_id"])
    return publies


def test_lancien_ordre_affamait_vraiment_le_rang_six():
    """⚠️ LA PREUVE DU DÉFAUT. Dix passages, onze billets frais : l'ancien
    ordre n'en publie que cinq, et les six autres ne sortiront jamais."""
    publies = _simuler(dedup_avant=False, passages=10)
    assert len(publies) == news.MAX_BILLETS_PAR_PASSAGE, (
        f"attendu {news.MAX_BILLETS_PAR_PASSAGE} publiés (les 5 plus récents), "
        f"obtenu {len(publies)}")
    #  Ce sont bien les CINQ PLUS RÉCENTS, et les plus anciens sont affamés.
    assert publies == {100, 101, 102, 103, 104}
    assert not (publies & {105, 106, 107, 108, 109, 110}), (
        "les rangs 6+ n'auraient jamais dû sortir sous l'ancien ordre")


def test_le_nouvel_ordre_finit_par_tout_publier():
    """Le même lot, le même nombre de passages : plus personne n'est coincé."""
    publies = _simuler(dedup_avant=True, passages=10)
    assert len(publies) == 11, (
        f"onze billets frais doivent tous sortir, obtenu {len(publies)}")


def test_le_nouvel_ordre_draine_a_la_vitesse_du_quota():
    """Et il les sort par tranches de 5 — le quota reste un quota, il ne
    devient pas un déversoir."""
    assert len(_simuler(dedup_avant=True, passages=1)) == 5
    assert len(_simuler(dedup_avant=True, passages=2)) == 10
    assert len(_simuler(dedup_avant=True, passages=3)) == 11


def test_le_plus_ancien_part_en_premier_a_lenvoi():
    """Le correctif ne doit pas casser l'ordre de lecture du salon : Discord
    empile vers le bas, donc on envoie le plus ancien d'abord."""
    lot = [_billet(200 + i, jours=i) for i in range(5)]
    envoi = veille.ordonner_publication(lot, 5)
    dates = [b["cree_le"] for b in envoi]
    assert dates == sorted(dates), "l'envoi doit aller du plus ancien au plus récent"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. L'absorption des trop vieux — le garde-fou anti-déversement
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def base(monkeypatch):
    marques = set()

    async def _marquer(gid, tid):
        marques.add(tid)
    monkeypatch.setattr(news, "marquer_publie", _marquer)
    return marques


@pytest.mark.asyncio
async def test_les_trop_vieux_sont_marques_sans_etre_envoyes(base):
    """⚠️ SANS CE FILTRE, LE CORRECTIF DEVIENT UN DÉFAUT. Dédupliquer avant de
    tronquer rend publiable tout ce qui n'est jamais sorti — y compris des
    billets de trois semaines. Les envoyer serait « déverser l'historique dans
    le salon », interdit (ROBLOX.md)."""
    lot = [_billet(1, jours=1), _billet(2, jours=30), _billet(3, jours=8)]
    frais, absorbes = await news.absorber_vieux(1, lot)
    assert absorbes == 2
    assert [b["topic_id"] for b in frais] == [1]
    #  Marqués sortis → ils ne reviendront pas au passage suivant.
    assert base == {2, 3}


@pytest.mark.asyncio
async def test_labsorption_utilise_le_seuil_de_lamorce(base):
    """Même décision, même constante : au-delà, ce n'est plus une nouvelle.

    ⚠️ LE SEUIL SE COMPTE EN JOURS PLEINS. `_trop_vieux` fait
    `(now - d).days > jours`, et `.days` TRONQUE : un billet de 7 j 12 h donne
    `.days == 7`, donc `7 > 7` est faux — il reste frais. Le seuil effectif est
    « strictement plus de 7 jours pleins », c'est-à-dire 8 jours révolus. Ce
    n'est pas un défaut : c'est la même règle partout (fraîcheur à 30 j,
    amorce à 7 j), et la borne est du côté généreux — dans le doute on publie
    plutôt que d'absorber en silence."""
    frais, _ = await news.absorber_vieux(
        1, [_billet(1, jours=news.AMORCE_GARDE_JOURS + 0.5)])
    assert len(frais) == 1, "7 j et demi tient dans « 7 jours pleins » — encore frais"
    frais, _ = await news.absorber_vieux(
        1, [_billet(2, jours=news.AMORCE_GARDE_JOURS + 1.5)])
    assert frais == [], "au-delà de 8 jours révolus, on absorbe"


@pytest.mark.asyncio
async def test_en_cas_de_doute_on_garde_plutot_que_de_marquer(base, monkeypatch):
    """Rater une publication est réparable ; marquer sorti à tort est
    définitif. Une date illisible ne doit donc pas faire disparaître un
    billet en silence."""
    async def _explose(gid, tid):
        raise RuntimeError("base indisponible")
    monkeypatch.setattr(news, "marquer_publie", _explose)
    frais, absorbes = await news.absorber_vieux(1, [_billet(9, jours=99)])
    assert absorbes == 0
    assert [b["topic_id"] for b in frais] == [9], (
        "un échec d'écriture ne doit pas perdre le billet")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Les deux chemins de publication appliquent le MÊME ordre
# ═══════════════════════════════════════════════════════════════════════════════

def _corps(src: str, nom: str) -> str:
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable")


def test_la_boucle_deduplique_avant_de_tronquer():
    corps = _corps(SRC_BOT, "veille_roblox_task")
    bloc = corps.split("for src in roblox_news_module.SOURCES")[-1]
    i_dedup = bloc.index("deja_publie")
    i_tronque = bloc.index("_lot_b = ")
    assert i_dedup < i_tronque, (
        "la déduplication doit précéder la troncature, sinon le rang 6 est affamé")


def test_la_boucle_absorbe_les_trop_vieux():
    corps = _corps(SRC_BOT, "veille_roblox_task")
    assert "absorber_vieux" in corps


def test_le_bouton_relever_maintenant_applique_le_meme_ordre():
    """⚠️ DEUX CHEMINS QUI DIVERGENT = un défaut corrigé d'un côté et vivant
    de l'autre. Le bouton manuel doit suivre exactement la même règle."""
    assert "absorber_vieux" in SRC_PAN
    bloc = SRC_PAN.split("_neufs = []")[-1][:900]
    i_dedup = bloc.index("deja_publie")
    i_tronque = bloc.index("ordonner_publication")
    assert i_dedup < i_tronque


def test_le_journal_ne_promet_le_retour_que_pour_ce_qui_revient():
    """La phrase « repris au prochain passage » n'est vraie que depuis le
    correctif. Elle doit rester accolée aux billets FRAIS et NON PUBLIÉS."""
    corps = _corps(SRC_BOT, "veille_roblox_task")
    bilan = corps.split("passage terminé")[-1]
    assert "absorbé(s)" in bilan, "les absorbés doivent être comptés à part"
    assert "frais et non" in bilan, (
        "le quota doit dire de QUOI il parle, sinon la promesse de retour ment")
