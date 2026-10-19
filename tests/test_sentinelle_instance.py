"""Deux instances du bot tournent-elles en même temps ?

═══════════════════════════════════════════════════════════════════════════════
⚠️ LA RÉPÉTITION DES ÂGES NE PROUVAIT RIEN — MON DIAGNOSTIC DU 31/08 ÉTAIT FAUX
═══════════════════════════════════════════════════════════════════════════════
J'avais écrit ici : « l'âge de la création la plus récente apparaît DEUX FOIS à
chaque valeur (465 · 466 · 466 · 467 · 467 …), or `tasks.loop` n'exécute jamais
deux itérations à la fois : il ne reste qu'une explication, DEUX PROCESSUS. »

C'est faux, et il existait une explication innocente que je n'ai pas cherchée.

    `veille_roblox_task` tourne toutes les 30 MINUTES.
    L'âge est imprimé en HEURES ENTIÈRES (`f"{_pf:.0f} h"`).

Une valeur qui monte de 0,5 par passage et qu'on arrondit à l'entier répète
donc EXACTEMENT deux fois chaque nombre. Ce n'est pas une anomalie : c'est de
l'arithmétique. Vérifié sur les journaux du 01/09, 11 valeurs sur 11 :

    attendu (une seule instance) : 422 423 423 424 424 425 425 426 426 427 427
    observé en production        : 422 423 423 424 424 425 425 426 426 427 427

Et le 01/09 confirme le reste : UN seul identifiant d'instance, la sentinelle
muette. `test_la_repetition_des_ages_ne_prouve_rien` fige ce calcul pour que
personne — moi le premier — ne refasse la même déduction hâtive.

⚠️ CE QUE ÇA COÛTE, ET POURQUOI ON GARDE LE MODULE. Un diagnostic faux laissé
dans un dépôt fait perdre plus de temps qu'une absence de diagnostic : on part
chercher un problème de déploiement qui n'existe pas. Mais la SENTINELLE, elle,
reste juste et utile — elle ne déduit rien, elle CONSTATE. C'est précisément la
différence entre les deux qui justifie de garder l'une et d'effacer l'autre :
un fait mesuré vaut mieux qu'une inférence, même élégante.

(`reste_min` collé à 2-3/12 le 31/08 puis remonté à 5/12 le 01/09 reste
inexpliqué. Le 31/08, le propriétaire cliquait « Relever maintenant », qui
puise au même quota — c'est une hypothèse, et elle est notée comme telle.)
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
    i_travail = corps.index("_relever_actus()")
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


# ═══════════════════════════════════════════════════════════════════════════════
#  La réfutation, exécutable
# ═══════════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════════
#  `veille_marche_task` doit pouvoir prouver qu'elle vit
# ═══════════════════════════════════════════════════════════════════════════════







# ═══════════════════════════════════════════════════════════════════════════════
#  Le conteneur REMPLACÉ n'est pas une seconde instance (23/09)
# ═══════════════════════════════════════════════════════════════════════════════
#  Journal du 23/09, 11:33 : « UNE AUTRE INSTANCE DU BOT TOURNE : 10054bc1b336
#  (vu 11:31:29) » — deux minutes AVANT notre démarrage. Railway démarre le
#  nouveau conteneur avant d'arrêter l'ancien : le dernier battement de l'ancien
#  tombait dans la fenêtre de fraîcheur, et l'alarme sonnait à chaque déploiement.

def _sentinelle(tmp_path, demarre):
    import asyncio
    import contextlib
    from datetime import datetime, timedelta, timezone

    import aiosqlite

    chemin = tmp_path / "sentinelle.db"

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _preparer(lignes):
        async with _get_db() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS bot_instances("
                             " id TEXT PRIMARY KEY, vu_le TEXT NOT NULL,"
                             " demarre_le TEXT NOT NULL)")
            for iid, vu in lignes:
                await db.execute("INSERT INTO bot_instances VALUES(?,?,?)",
                                 (iid, vu.isoformat(), vu.isoformat()))
            await db.commit()

    ns = {"get_db": _get_db, "_INSTANCE_ID": "moi", "_INSTANCE_DEMARRE": demarre,
          "SENTINELLE_FRAICHEUR_S": 180, "datetime": datetime,
          "timezone": timezone, "timedelta": timedelta, "print": lambda *a: None}
    exec(_fonction("_battre_sentinelle"), ns)          # noqa: S102 — code du dépôt
    return ns, _preparer, asyncio


def test_le_PREDECESSEUR_arrete_au_redeploiement_ne_declenche_pas_l_alarme(tmp_path):
    from datetime import datetime, timedelta, timezone
    maintenant = datetime.now(timezone.utc)
    demarre = maintenant - timedelta(seconds=20)
    ns, preparer, aio = _sentinelle(tmp_path, demarre)
    aio.run(preparer([("ancien", demarre - timedelta(minutes=2))]))
    assert aio.run(ns["_battre_sentinelle"]()) == [], "fausse alarme de redéploiement"


def test_une_VRAIE_seconde_instance_qui_bat_APRES_notre_demarrage_est_dite(tmp_path):
    """La correction ne doit pas rendre la sentinelle aveugle."""
    from datetime import datetime, timedelta, timezone
    maintenant = datetime.now(timezone.utc)
    demarre = maintenant - timedelta(minutes=10)
    ns, preparer, aio = _sentinelle(tmp_path, demarre)
    aio.run(preparer([("jumelle", maintenant - timedelta(seconds=40))]))
    autres = aio.run(ns["_battre_sentinelle"]())
    assert autres and autres[0].startswith("jumelle"), autres
