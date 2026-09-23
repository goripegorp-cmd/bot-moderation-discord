"""L'éclaireur ne détectait RIEN, et le disait 1 152 fois par jour.

═══════════════════════════════════════════════════════════════════════════════
LA PREUVE, DANS LES JOURNAUX RAILWAY DU 22/09 (18:14 → 18:34)
═══════════════════════════════════════════════════════════════════════════════
    [eclaireur] catalogue injoignable (HTTP 200 / 429) — nouvel essai dans 75 s

répété à CHAQUE passage, sans exception. `200` = la requête des créations
RÉUSSIT. `429` = celle des collectionnables est refusée. Et le code jetait le
passage ENTIER parce qu'une des deux avait échoué :

    if r1["code"] != 200 or r2["code"] != 200:
        ...
        return                          ← les identifiants reçus, jetés

Conséquence : depuis son déploiement, l'éclaireur n'a jamais détecté une seule
création. Tout retombait sur le relevé complet — 30 minutes. C'est exactement
la lenteur signalée par le propriétaire, et la même ligne d'erreur toutes les
75 s est exactement le « spam d'erreurs Railway » qu'il demande de couper.

═══════════════════════════════════════════════════════════════════════════════
CE QUE L'API DIT VRAIMENT (mesuré le 22/09)
═══════════════════════════════════════════════════════════════════════════════
  · `/v1/search/items` : `x-ratelimit-limit: 12, 12;w=60` → 12 requêtes par
    60 s glissantes, `retry-after: 5` au refus ;
  · deux requêtes collées passent parfaitement depuis une IP libre → le refus
    de production ne vient PAS d'une règle de rafale mais d'un seau d'IP
    PARTAGÉE (Railway) vidé par le voisinage ;
  · `/v1/search/items` et `/v2/search/items/details` ont des seaux SÉPARÉS
    (mesuré : 1 requête d'identifiants = −1 sur son compteur seul, 3 requêtes
    de fiches = −3 sur l'autre) : le relevé complet n'affame pas l'éclaireur.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _src(nom: str) -> str:
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            #  Le corps SEUL : les décorateurs (`@tasks.loop`) transformeraient
            #  la fonction en boucle qu'on ne pourrait plus appeler.
            n = ast.copy_location(
                ast.AsyncFunctionDef(name=n.name, args=n.args, body=n.body,
                                     decorator_list=[], returns=None,
                                     type_comment=None, type_params=[]), n)
            return ast.unparse(ast.fix_missing_locations(n))
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _constante(nom: str):
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == nom for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(f"{nom} introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le banc : le VRAI corps de l'éclaireur, avec un faux catalogue
# ═══════════════════════════════════════════════════════════════════════════════

class FauxCatalogue:
    """Rend les réponses qu'on lui a écrites, et note ce qu'on lui a demandé."""

    MAX_PUBLICATIONS_PAR_PASSAGE = 12

    #  ⚠️ PIÈGE N°6 : depuis le 23/09 l'éclaireur lit la configuration des
    #  flux pour savoir QUOI regarder. Par défaut ici : les deux flux allumés,
    #  le cas où l'alternance a un sens — c'est lui que ces tests décrivent.
    def __init__(self, reponses, flux=None):
        self.reponses = list(reponses)
        self.demandes = []
        self.cfg = dict(flux or {"roblox_flux_nouveautes": True,
                                 "roblox_flux_bascules": True})

    async def config(self, _gid):
        return self.cfg

    def flux_allume(self, cfg, flux):
        return bool(cfg.get(f"roblox_flux_{flux}", False))

    def catalogue_est_occupe(self):
        return False

    async def actif(self, _gid):
        return True

    async def identifiants_connus(self):
        return {1, 2}, {1}

    #  ⚠️ PIÈGE N°6 : la VRAIE signature, `seau` compris — sans lui, l'appel
    #  de secours lèverait un TypeError et le test mesurerait une panne.
    async def relever_identifiants(self, *, collectionnables=False, limite=120,
                                   seau="identifiants"):
        self.demandes.append(("collect" if collectionnables else "creations")
                             + (":fiches" if seau == "fiches" else ""))
        if self.reponses:
            return self.reponses.pop(0)
        return {"ids": set(), "bundles": set(), "code": 200, "reste": 11}

    async def fiches_par_ids(self, ids, item_type=None):
        return [{"asset_id": i} for i in ids]

    async def comparer_et_enregistrer(self, fiches):
        return {"nouveaux": fiches, "bascules": []}

    def ordonner_publication(self, lot, n):
        return list(lot)[:n]

    def age_publiable(self, _a, _flux):
        return True

    async def publiable_dans(self, _gid, _aid, _flux):
        return True

    async def enfiler(self, _gid, _a, _flux):
        return True


class FauxAsyncio:
    """Le sommeil est instantané — mais NOTÉ : c'est lui qu'on vérifie quand
    on prétend écouter `retry-after`."""

    def __init__(self):
        self.sommeils = []

    async def sleep(self, d):
        self.sommeils.append(d)


def _banc(reponses, etat=None, flux=None):
    journal = []
    cat = FauxCatalogue(reponses, flux=flux)
    E = {"amorce": True, "vus": {1, 2}, "vus_limited": {1},
         "tour": 0, "palier": 0, "pause_jusqu": None, "refus": 0, "reste": None,
         "rattrapes": 0, "serie": 0, "serie_max": 0, "alerte": False,
         "dernier_refus": None, "dernier_succes": datetime.now(timezone.utc),
         "secours_retenus": 0, "secours_pause_jusqu": None,
         "passages": 0, "sautes": 0, "erreurs": 0, "nouveautes": 0,
         "bascules": 0, "publies": 0,
         "dernier_passage": None, "dernier_signal": None}
    if etat:
        E.update(etat)
    faux_asyncio = FauxAsyncio()

    async def _publier(*a, **kw):
        journal.append("publie")
        return {"publies": 1}

    ns = {
        "roblox_module": cat,
        "bot": type("B", (), {"guilds": [type("G", (), {"id": 1})()]})(),
        "_ECLAIREUR": E,
        "ECLAIREUR_SECONDES": _constante("ECLAIREUR_SECONDES"),
        "ECLAIREUR_PAUSES": _constante("ECLAIREUR_PAUSES"),
        "ECLAIREUR_RESTE_CONFORTABLE": _constante("ECLAIREUR_RESTE_CONFORTABLE"),
        "ECLAIREUR_BATTEMENT": _constante("ECLAIREUR_BATTEMENT"),
        "ECLAIREUR_SOBRIETE_S": _constante("ECLAIREUR_SOBRIETE_S"),
        "ECLAIREUR_ALERTE_APRES_S": _constante("ECLAIREUR_ALERTE_APRES_S"),
        #  ⚠️ PIÈGE N°6 : les trois réglages de la garde de marge. Absents, le
        #  `NameError` était avalé par la boucle et le test mesurait une panne.
        "ECLAIREUR_AVANT_RELEVE_S": _constante("ECLAIREUR_AVANT_RELEVE_S"),
        "ECLAIREUR_SECOURS_RESTE_MIN": _constante("ECLAIREUR_SECOURS_RESTE_MIN"),
        "ECLAIREUR_SECOURS_PAUSE_S": _constante("ECLAIREUR_SECOURS_PAUSE_S"),
        "asyncio": faux_asyncio,
        "random": type("Rnd", (), {"uniform": staticmethod(lambda a, b: 0.5)})(),
        "_publier_file_accessoires": _publier,
        #  Le relevé complet n'est pas imminent dans ces bancs : la garde de
        #  marge (75 s avant lui) ne doit pas retenir le secours.
        "veille_roblox_task": type("L", (), {"next_iteration": None})(),
        "_age_s": lambda _d: 10,
        "datetime": datetime, "timezone": timezone, "timedelta": timedelta,
        "print": lambda *a, **k: journal.append(" ".join(str(x) for x in a)),
    }
    exec(_src("eclaireur_task"), ns)          # noqa: S102 — code du dépôt
    ns["_sommeils"] = faux_asyncio.sommeils
    return ns, E, cat, journal


def _tick(ns):
    asyncio.run(ns["eclaireur_task"]())


def _ok(ids, reste=11, bundles=None):
    return {"ids": set(ids), "bundles": set(bundles or ()), "code": 200,
            "reste": reste}


def _refus(code=429, retry=5.0):
    return {"ids": set(), "bundles": set(), "code": code, "reste": 0,
            "retry": retry}


# ═══════════════════════════════════════════════════════════════════════════════
#  LE DÉFAUT DE PRODUCTION
# ═══════════════════════════════════════════════════════════════════════════════

def test_E1_une_reussite_n_est_PLUS_jetee_a_cause_d_un_refus_voisin():
    """⚠️ LE DÉFAUT MESURÉ EN PRODUCTION. 200 puis 429 : l'ancien code jetait
    les identifiants REÇUS et ne détectait donc jamais rien."""
    #  Passage 1 : créations OK avec un quota large → la 2e requête part et
    #  se fait refuser. La nouveauté 77 doit quand même être vue.
    ns, E, cat, journal = _banc([_ok([1, 2, 77], reste=11), _refus()])
    _tick(ns)
    assert 77 in E["vus"], "l'identifiant reçu a été jeté"
    assert any("🔔" in l for l in journal), (
        f"aucune publication déclenchée : {journal}")


def test_E2_les_deux_files_ont_chacune_SA_memoire():
    """Verser des créations dans la mémoire des collectionnables masquerait
    une bascule Limited pour toujours."""
    ns, E, cat, journal = _banc([_ok([1, 2, 55], reste=2),    # quota serré
                                 _ok([1, 88], reste=2)])
    _tick(ns)                                   # tour pair → créations
    assert 55 in E["vus"] and 55 not in E["vus_limited"]
    _tick(ns)                                   # tour impair → collectionnables
    assert 88 in E["vus_limited"], "la bascule n'est pas mémorisée là où il faut"
    assert 88 not in E["vus"], (
        "un collectionnable versé dans la mémoire des créations : la prochaine "
        "bascule Limited de cet article serait invisible pour toujours")
    assert cat.demandes == ["creations", "collect"], cat.demandes


def test_E3_la_SECONDE_requete_ne_part_que_si_le_quota_le_permet():
    """Une requête qu'on sait condamnée est une requête gâchée — et un 429 de
    plus dans les journaux."""
    ns, _E, cat, _j = _banc([_ok([1], reste=2)])
    _tick(ns)
    assert cat.demandes == ["creations"], "requête gâchée malgré un quota bas"
    ns, _E, cat, _j = _banc([_ok([1], reste=11), _ok([1], reste=10)])
    _tick(ns)
    assert cat.demandes == ["creations", "collect"], cat.demandes


def test_E4_l_alternance_regarde_les_DEUX_files_a_tour_de_role():
    """Avec une seule requête par passage, la bascule Limited ne doit pas être
    oubliée : elle passe au tour suivant."""
    ns, _E, cat, _j = _banc([_ok([1], reste=2), _ok([1], reste=2)])
    _tick(ns)
    _tick(ns)
    assert cat.demandes == ["creations", "collect"], cat.demandes


# ═══════════════════════════════════════════════════════════════════════════════
#  LE SILENCE ET LE RALENTISSEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def test_E5_un_refus_RALENTIT_au_lieu_de_marteler():
    """Marteler une IP saturée ne rend pas un quota : ça le garde vide."""
    #  429, puis 429 encore après `retry-after` : là seulement le passage
    #  est perdu et on ralentit.
    ns, E, _cat, journal = _banc([_refus(), _refus(), _refus()])
    _tick(ns)
    assert E["palier"] == 1 and E["pause_jusqu"] is not None
    assert E["refus"] == 2, "les deux refus du passage doivent être comptés"
    #  Le passage suivant est SAUTÉ tant que la pause dure.
    avant = E["passages"]
    _tick(ns)
    assert E["passages"] == avant, "il a retenté pendant la pause"
    assert E["sautes"] >= 1


def test_E6_la_MEME_ligne_n_est_pas_repetee_a_chaque_passage():
    """⚠️ 1 152 LIGNES PAR JOUR. C'est dans ce bruit qu'une vraie panne passe
    inaperçue — et c'est la plainte du propriétaire sur les erreurs Railway."""
    #  ⚠️ RÉFUTÉ PAR LA PRODUCTION LE 22/09 : « une ligne au changement
    #  d'état » donnait encore une ligne par passage, parce que l'état
    #  basculait à chaque fois (refusé → joignable → refusé…). Des refus
    #  passagers ne doivent produire AUCUNE ligne.
    ns, E, _cat, journal = _banc([_refus() for _ in range(12)])
    for _ in range(6):
        E["pause_jusqu"] = None            # on force les passages à s'enchaîner
        _tick(ns)
    assert not [l for l in journal if "[eclaireur]" in l], (
        f"des refus passagers ont écrit dans le journal : {journal}")
    assert E["serie"] == 6 and E["serie_max"] == 6


def test_E7_la_premiere_REUSSITE_rend_la_cadence_normale():
    """Un ralentissement qui ne se relâche pas est une panne de plus."""
    ns, E, _cat, journal = _banc([_refus(), _refus(), _ok([1], reste=3)])
    _tick(ns)
    assert E["palier"] == 1
    E["pause_jusqu"] = None
    _tick(ns)
    assert E["palier"] == 0 and E["pause_jusqu"] is None
    assert E["serie"] == 0
    #  Pas d'alerte → pas de ligne de fin non plus : c'est la bascule
    #  refusé/joignable qui faisait le bruit en production.
    assert not [l for l in journal if "[eclaireur]" in l], journal


def test_E9_le_SECOND_SEAU_sauve_le_passage_sans_attendre():
    """⚠️ LE LEVIER MESURÉ. Refus sur le seau des identifiants → même question
    au seau des fiches, qui a son propre compteur (mesuré), rend la même tête
    (10/10, 8/8) et n'est pas disputé en production (relevé complet : 429=0).
    Aucune attente : on ne perd ni le passage ni 90 s de détection."""
    ns, E, cat, journal = _banc([_refus(), _ok([1, 2, 99], reste=3)])
    _tick(ns)
    assert 99 in E["vus"], "le passage n'a pas été sauvé"
    assert E["rattrapes"] == 1 and E["palier"] == 0
    assert cat.demandes == ["creations", "creations:fiches"], cat.demandes
    assert ns["_sommeils"] == [], "on a dormi alors que l'autre seau répondait"


def test_E10_l_aveuglement_PROLONGE_est_dit_une_fois_et_sa_fin_aussi():
    """Le silence ne doit pas cacher une vraie panne : dix minutes sans rien
    voir, c'en est une. Une ligne au début, une à la fin, pas une de plus."""
    il_y_a_11_min = datetime.now(timezone.utc) - timedelta(minutes=11)
    ns, E, _cat, journal = _banc(
        [_refus() for _ in range(6)] + [_ok([1], reste=3)],
        etat={"dernier_succes": il_y_a_11_min})
    for _ in range(3):
        E["pause_jusqu"] = None
        _tick(ns)
    alertes = [l for l in journal if "AVEUGLE" in l]
    assert len(alertes) == 1, f"alerte absente ou répétée : {journal}"
    E["pause_jusqu"] = None
    _tick(ns)
    fins = [l for l in journal if "de nouveau lisible" in l]
    assert len(fins) == 1, f"fin d'aveuglement absente ou répétée : {journal}"


def test_E11_apres_un_refus_on_ne_prend_QUE_le_strict_necessaire():
    """Quand l'IP est disputée, la seconde requête du passage — même avec un
    quota annoncé confortable — reprendrait le jeton qu'un voisin attend, et
    nous vaudrait le refus suivant."""
    ns, _E, cat, _j = _banc([_refus(), _ok([1], reste=11), _ok([1], reste=10)])
    _tick(ns)
    assert cat.demandes == ["creations", "creations:fiches"], (
        f"seconde requête envoyée malgré un refus récent : {cat.demandes}")


def test_E12_on_ne_dort_PAS_sur_retry_after_la_mesure_l_a_refute():
    """⚠️ RÉFUTÉ LE 23/09 SUR L'API RÉELLE : saturer le seau, attendre le
    `retry-after: 5` annoncé, réessayer → 429, deux essais sur deux. L'en-tête
    ment ; c'est la fenêtre de 60 s qui décide. Dormir dessus, c'était une
    requête de plus, refusée, à chaque refus."""
    ns, _E, cat, _j = _banc([_refus(retry=5.0), _refus(retry=5.0)])
    _tick(ns)
    assert ns["_sommeils"] == [], f"relance sur retry-after : {ns['_sommeils']}"
    assert cat.demandes == ["creations", "creations:fiches"], cat.demandes
    corps = _src("eclaireur_task")
    assert "retry" not in corps.replace("retry-after", "").lower() or \
        "sleep(_att" not in corps, "la relance sur retry-after est revenue"


def test_E8_la_cadence_et_les_paliers_sont_ceux_qu_on_a_mesures():
    """45 s × alternance = 1,3 requête/min sur un seau de 12/min mesuré."""
    assert _constante("ECLAIREUR_SECONDES") == 45
    paliers = _constante("ECLAIREUR_PAUSES")
    assert paliers[0] == 0 and paliers[-1] >= 300
    assert list(paliers) == sorted(paliers), "les paliers doivent croître"


# ═══════════════════════════════════════════════════════════════════════════════
#  LA SONDE D'ACTUALITÉS
# ═══════════════════════════════════════════════════════════════════════════════

def test_N1_la_sonde_demande_CINQ_billets_et_pas_trente():
    """Mesuré le 22/09, en régime établi et avec le vrai code du dépôt :
    70,0 Ko par passage contre 708,4 Ko — 10,1× moins — et 297 ms contre
    9 265 ms sur la catégorie « annonces ». Les cinq plus récents sont
    IDENTIQUES, catégorie par catégorie."""
    src = (RACINE / "roblox_news.py").read_text(encoding="utf-8")
    assert 'url = source["url"] + ("&per_page=5" if leger else "")' in src
    i = src.index("async def relever(")
    assert "leger: bool = False" in src[i:i + 400]


def test_N2_l_eclaireur_d_actualites_UTILISE_la_sonde_legere():
    """Une option jamais passée n'optimise rien."""
    corps = _src("eclaireur_actu_task")
    assert "leger=True" in corps, "la sonde légère n'est pas utilisée"


def test_N3_les_categories_CHAUDES_sont_regardees_a_chaque_passage():
    """Les notes de version n'ont jamais d'annonce chaude : les interroger
    toutes les 30 s, c'est tripler les requêtes pour un délai que personne ne
    remarque."""
    assert _constante("ECLAIREUR_ACTU_SECONDES") == 30
    chaudes = _constante("ECLAIREUR_ACTU_CHAUDES")
    assert "annonces" in chaudes and "alertes" in chaudes
    corps = _src("eclaireur_actu_task")
    assert "ECLAIREUR_ACTU_CHAUDES" in corps


def test_N4_le_battement_reste_a_30_minutes():
    """Le rythme du bilan ne doit pas suivre la cadence : trois fois plus de
    passages ne doit pas faire trois fois plus de lignes."""
    assert (_constante("ECLAIREUR_ACTU_SECONDES")
            * _constante("ECLAIREUR_ACTU_BATTEMENT")) == 1800


# ═══════════════════════════════════════════════════════════════════════════════
#  « UNIQUEMENT LES OBJETS QUI DEVIENNENT LIMITED » (23/09)
# ═══════════════════════════════════════════════════════════════════════════════

def test_E13_nouveautes_eteintes_on_ne_regarde_QUE_les_Limited_a_chaque_passage():
    """Interroger les créations ne publierait rien : c'était une requête sur
    deux pour rien. Les Limited sont alors regardés À CHAQUE passage — deux
    fois plus vite, pour le même débit."""
    ns, _E, cat, _j = _banc([_ok([1], reste=11), _ok([1], reste=11),
                             _ok([1], reste=11)],
                            flux={"roblox_flux_bascules": True})
    for _ in range(3):
        _tick(ns)
    assert cat.demandes == ["collect", "collect", "collect"], cat.demandes


def test_E14_aucun_flux_que_l_eclaireur_sache_regarder_AUCUNE_requete():
    """Rien à publier = rien à demander. « Ne pas spammer une recherche qui
    ne sert à rien. »"""
    ns, _E, cat, _j = _banc([_ok([1])], flux={"roblox_flux_surveiller": True})
    _tick(ns)
    assert cat.demandes == [], cat.demandes


def test_E15_le_secours_se_RETIENT_juste_avant_le_releve_complet():
    """Mesuré en production : un secours dans la minute qui précède le relevé
    lui coûtait sa marge (reste_min 3 → 1). Dans les 75 s qui le précèdent,
    on ne prend pas le second seau — le relevé regardera lui-même."""
    ns, E, cat, _j = _banc([_refus(), _ok([1], reste=9)])
    ns["veille_roblox_task"] = type("L", (), {
        "next_iteration": datetime.now(timezone.utc) + timedelta(seconds=30)})()
    _tick(ns)
    assert cat.demandes == ["creations"], (
        f"secours pris juste avant le relevé : {cat.demandes}")
    assert E["secours_retenus"] == 1


def test_E16_un_second_seau_presque_vide_est_laisse_tranquille():
    """Le relevé complet et le suivi de marché en dépendent : s'il annonce 3
    jetons ou moins, on le laisse souffler une minute."""
    ns, E, cat, _j = _banc([_refus(), _ok([1], reste=2), _refus()])
    _tick(ns)
    assert E["secours_pause_jusqu"] is not None
    E["pause_jusqu"] = None
    _tick(ns)
    assert cat.demandes.count("creations:fiches") + cat.demandes.count(
        "collect:fiches") == 1, cat.demandes
