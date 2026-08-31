"""Deux instances du bot tournent-elles en même temps ?

═══════════════════════════════════════════════════════════════════════════════
CE QUE LES JOURNAUX DU 31/08 MONTRENT
═══════════════════════════════════════════════════════════════════════════════
L'âge de la création Roblox la plus récente, dans l'ordre des passages :

    465 · 466 · 466 · 467 · 467 · 468 · 468 · 469 · 469 · 470 · 470 h

Chaque valeur apparaît DEUX FOIS. Et deux lignes « actualités : … » se suivent
sans « passage terminé » entre elles, avec des compteurs différents (12 puis
14). Or `tasks.loop` n'exécute jamais deux itérations à la fois, et le
superviseur ne relance que les boucles ARRÊTÉES (`if not lo.is_running()`).
Il ne reste qu'une explication : DEUX PROCESSUS.

⚠️ CONSÉQUENCE MESURABLE : le débit vers le catalogue est doublé, ce qui colle
`reste_min` à 2-3/12 au lieu de 5. Et tous les compteurs du bilan comptent en
double, ce qui fausse chaque diagnostic bâti dessus.

⚠️ CE MODULE NE CORRIGE RIEN, ET C'EST VOULU. La cause est côté déploiement —
deux conteneurs actifs — et le bot ne peut pas s'en occuper. Ce qu'il peut
faire, et qui vaut bien plus qu'une hypothèse de ma part, c'est le CONSTATER
et le dire. « Ne me dis jamais qu'une chose marche sans avoir suivi la chaîne
jusqu'à un effet réel » vaut aussi pour les diagnostics : celui-ci s'écrit
tout seul, dans les journaux, la prochaine fois que ça se produit.
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


def _fonction(nom: str) -> str:
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


def test_chaque_processus_a_une_identite_qui_change_au_demarrage():
    """Deux conteneurs, deux identités — sinon la sentinelle ne verrait rien.
    ⚠️ Elle ne doit PAS être dérivée d'une chose stable (nom d'hôte, id de
    déploiement) : deux conteneurs d'un même déploiement partageraient alors
    la même, et le doublon resterait invisible."""
    assert "_INSTANCE_ID = uuid.uuid4()" in SRC, (
        "l'identité n'est pas tirée au hasard à chaque démarrage")


def test_la_sentinelle_est_appelee_AVANT_le_travail():
    """Un diagnostic imprimé après cinq minutes de relevés arriverait après
    les requêtes qu'il sert à expliquer."""
    corps = _fonction("veille_roblox_task")
    i_sent = corps.index("_battre_sentinelle()")
    i_travail = corps.index("relever_nouveautes(")
    assert i_sent < i_travail, (
        "la sentinelle bat après le travail : son avertissement arriverait "
        "trop tard pour expliquer le débit doublé")


def test_l_avertissement_nomme_la_cause_ET_l_effet():
    """⚠️ UN AVERTISSEMENT QUI NE DIT PAS QUOI FAIRE EST UN AVERTISSEMENT
    IGNORÉ. Il doit dire que c'est un problème de déploiement, sinon on
    cherchera dans le code — ce qui est exactement le temps qu'on veut
    économiser."""
    corps = _fonction("veille_roblox_task")
    assert "AUTRE INSTANCE" in corps
    assert "DÉPLOIEMENT" in corps, (
        "l'avertissement ne dit pas où est la cause : on chercherait dans le "
        "code pendant des jours")
    assert "DOUBLÉ" in corps, "l'effet mesurable n'est pas nommé"


def test_la_sentinelle_ne_peut_pas_casser_le_passage():
    """Une sentinelle qui fait tomber la boucle qu'elle surveille serait pire
    que pas de sentinelle. Les deux fonctions attrapent tout."""
    for nom in ("_init_sentinelle", "_battre_sentinelle"):
        corps = _fonction(nom)
        assert "except Exception" in corps, f"{nom} peut lever"


def test_la_table_ne_grossit_pas_sans_fin():
    """Un redéploiement par jour pendant un an ferait 365 lignes mortes. La
    sentinelle doit oublier les instances éteintes depuis longtemps."""
    corps = _fonction("_battre_sentinelle")
    assert "DELETE FROM bot_instances" in corps


def test_seules_les_instances_RECENTES_comptent():
    """Sinon toute instance ayant jamais tourné déclencherait l'alarme, y
    compris celle d'avant le redéploiement d'il y a une seconde — et une
    alarme qui se déclenche toujours ne veut plus rien dire."""
    corps = _fonction("_battre_sentinelle")
    assert "vu_le>=?" in corps.replace(" ", "") or "vu_le >= ?" in corps
    assert "SENTINELLE_FRAICHEUR_S" in SRC
    #  Assez large pour couvrir un passage lent (mesuré ~4 min), assez étroit
    #  pour qu'une instance vraiment morte disparaisse vite.
    for ligne in SRC.splitlines():
        if ligne.startswith("SENTINELLE_FRAICHEUR_S"):
            valeur = int(ligne.split("=")[1].split("#")[0].strip())
            assert 120 <= valeur <= 600, (
                "trop court : un passage lent ferait croire l'autre instance "
                "morte ; trop long : une instance éteinte alarmerait encore")
            return
    raise AssertionError("SENTINELLE_FRAICHEUR_S introuvable")
