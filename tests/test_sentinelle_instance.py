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


# ═══════════════════════════════════════════════════════════════════════════════
#  La tempête de reconnexions du 31/08 — 116 lignes pour un seul incident
# ═══════════════════════════════════════════════════════════════════════════════

def _classe_resumeur():
    """Extrait `_ResumeurPasserelle` de bot.py SANS l'importer.

    ⚠️ LA CI N'A PAS DE JETON DISCORD, et `import bot` s'y comporte de façon
    imprévisible — c'est pourquoi AUCUN test du dépôt ne l'importe. On reprend
    donc le motif déjà éprouvé (`test_config_lost_update.py`) : on lit la
    classe dans l'arbre syntaxique et on l'exécute dans un espace de noms
    minimal. Le code testé reste EXACTEMENT celui du dépôt.
    """
    import logging as _l
    from datetime import datetime as _dt, timezone as _tz
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.ClassDef) and n.name == "_ResumeurPasserelle":
            ns = {"logging": _l, "datetime": _dt, "timezone": _tz}
            exec(ast.unparse(n), ns)          # noqa: S102 — code du dépôt
            return ns["_ResumeurPasserelle"]
    raise AssertionError("_ResumeurPasserelle introuvable dans bot.py")


def _fabriquer_record(exc, message="Attempting a reconnect in 1.61s"):
    import logging as _l
    try:
        raise exc
    except Exception:
        import sys
        return _l.LogRecord("discord.client", _l.ERROR, __file__, 1, message,
                            (), sys.exc_info())


def test_un_echec_de_passerelle_perd_sa_pile_et_gagne_un_compteur():
    """⚠️ MESURÉ LE 31/08 : la passerelle Discord a rendu des 503 pendant une
    minute. `discord.py` a réessayé correctement (1,6 · 2,3 · 5,4 · 10,1 s),
    mais chaque tentative crachait quinze lignes de pile — **116 lignes pour un
    seul incident**, entrelacées au point d'être illisibles, et rien nulle part
    ne disait que la cause était chez Discord."""
    class _Handshake(Exception):
        status = 503
    _Handshake.__name__ = "WSServerHandshakeError"

    f = _classe_resumeur()()
    r1 = _fabriquer_record(_Handshake("Invalid response status"))
    assert f.filter(r1) is True, "l'événement ne doit pas être MASQUÉ, résumé"
    assert r1.exc_info is None, "la pile de quinze lignes est toujours là"
    assert "503" in r1.msg and "1 tentative" in r1.msg
    assert "DISCORD, pas côté bot" in r1.msg, (
        "sans cette phrase, on cherche le défaut dans le bot pendant une heure")

    #  Le compteur monte : une reconnexion isolée est la vie normale d'un bot,
    #  cinquante en une minute sont un incident. C'est la DIFFÉRENCE qui doit
    #  se voir, et une pile de traceback la noie.
    r2 = _fabriquer_record(_Handshake("Invalid response status"))
    f.filter(r2)
    assert "2 tentative" in r2.msg


def test_une_VRAIE_erreur_garde_sa_pile_entiere():
    """⚠️ LA CONTRE-ÉPREUVE, ET ELLE COMPTE PLUS QUE L'AUTRE. Un résumeur trop
    large avalerait le défaut qu'on cherche. Tout ce qui n'est pas un échec de
    poignée de main garde sa pile."""
    f = _classe_resumeur()()
    r = _fabriquer_record(ValueError("un vrai défaut du bot"), "autre chose")
    assert f.filter(r) is True
    assert r.exc_info is not None, "la pile d'un vrai défaut a été jetée"
    assert r.msg == "autre chose", "le message d'un vrai défaut a été réécrit"


def test_l_identite_est_imprimee_AVANT_la_connexion():
    """⚠️ LA SENTINELLE NE PEUT RIEN DIRE TANT QUE LE BOT N'EST PAS CONNECTÉ :
    elle bat dans `veille_roblox_task`, qui attend `wait_until_ready`. Le
    31/08, pendant la minute de 503, la question « y a-t-il deux instances ? »
    est restée sans réponse. Cette ligne-ci sort TOUJOURS."""
    bloc = SRC.split('if __name__ == "__main__":')[-1]
    assert "_INSTANCE_ID" in bloc, (
        "l'identité n'est pas imprimée au démarrage : en cas de panne de "
        "connexion, on ne peut pas trancher")
    i_id = bloc.index("_INSTANCE_ID")
    i_run = bloc.index("bot.run(")
    assert i_id < i_run, "l'identité est imprimée après la connexion"
    assert "_installer_resumeur_passerelle()" in bloc
    assert bloc.index("_installer_resumeur_passerelle()") < i_run, (
        "le résumeur est installé après `bot.run` : la tempête serait déjà "
        "passée en clair")
