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

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.demandes = []

    def catalogue_est_occupe(self):
        return False

    async def actif(self, _gid):
        return True

    async def identifiants_connus(self):
        return {1, 2}, {1}

    async def relever_identifiants(self, *, collectionnables=False, limite=120):
        self.demandes.append("collect" if collectionnables else "creations")
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


def _banc(reponses, etat=None):
    journal = []
    cat = FauxCatalogue(reponses)
    E = {"amorce": True, "vus": {1, 2}, "vus_limited": {1},
         "tour": 0, "palier": 0, "pause_jusqu": None, "refus": 0, "reste": None,
         "passages": 0, "sautes": 0, "erreurs": 0, "nouveautes": 0,
         "bascules": 0, "publies": 0,
         "dernier_passage": None, "dernier_signal": None}
    if etat:
        E.update(etat)

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
        "_publier_file_accessoires": _publier,
        "_age_s": lambda _d: 10,
        "datetime": datetime, "timezone": timezone, "timedelta": timedelta,
        "print": lambda *a, **k: journal.append(" ".join(str(x) for x in a)),
    }
    exec(_src("eclaireur_task"), ns)          # noqa: S102 — code du dépôt
    return ns, E, cat, journal


def _tick(ns):
    asyncio.run(ns["eclaireur_task"]())


def _ok(ids, reste=11, bundles=None):
    return {"ids": set(ids), "bundles": set(bundles or ()), "code": 200,
            "reste": reste}


def _refus(code=429):
    return {"ids": set(), "bundles": set(), "code": code, "reste": 0}


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
    ns, E, _cat, journal = _banc([_refus(), _refus(), _refus()])
    _tick(ns)
    assert E["palier"] == 1 and E["pause_jusqu"] is not None
    assert E["refus"] == 1
    #  Le passage suivant est SAUTÉ tant que la pause dure.
    avant = E["passages"]
    _tick(ns)
    assert E["passages"] == avant, "il a retenté pendant la pause"
    assert E["sautes"] >= 1


def test_E6_la_MEME_ligne_n_est_pas_repetee_a_chaque_passage():
    """⚠️ 1 152 LIGNES PAR JOUR. C'est dans ce bruit qu'une vraie panne passe
    inaperçue — et c'est la plainte du propriétaire sur les erreurs Railway."""
    ns, E, _cat, journal = _banc([_refus() for _ in range(6)])
    for _ in range(6):
        E["pause_jusqu"] = None            # on force les passages à s'enchaîner
        _tick(ns)
    lignes = [l for l in journal if "refusé" in l]
    assert len(lignes) <= len(ns["ECLAIREUR_PAUSES"]), (
        f"le journal répète la même ligne : {len(lignes)} fois")


def test_E7_la_premiere_REUSSITE_rend_la_cadence_normale():
    """Un ralentissement qui ne se relâche pas est une panne de plus."""
    ns, E, _cat, journal = _banc([_refus(), _ok([1], reste=3)])
    _tick(ns)
    assert E["palier"] == 1
    E["pause_jusqu"] = None
    _tick(ns)
    assert E["palier"] == 0 and E["pause_jusqu"] is None
    assert any("de nouveau joignable" in l for l in journal), journal


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
