"""L'éclaireur : voir tout de suite ce qui compte, sans spam ni bruit.

═══════════════════════════════════════════════════════════════════════════════
L'HISTOIRE, MESURE PAR MESURE
═══════════════════════════════════════════════════════════════════════════════
22/09 — journal Railway : `catalogue injoignable (HTTP 200 / 429)` à CHAQUE
    passage. La réussite était jetée avec l'échec voisin : depuis son
    déploiement, l'éclaireur n'avait jamais rien détecté.
22/09 — API : `/v1/search/items` = 12 requêtes / 60 s par IP ; le seau des
    fiches (`/v2/search/items/details`) est SÉPARÉ.
23/09 — `retry-after: 5` ment (2 relances sur 2 refusées) ; le second seau,
    lui, rend la même tête et n'est pas disputé en production (44 refus sur
    44 rattrapés en 3 heures, 0 passage aveugle).
23/09 — le tri « récents » de Roblox est l'ordre de CRÉATION : la tête des
    collectionnables ne contient que des Limited NOUVEAUX (déjà en tête de la
    liste générale), et un vieil article qui passe Limited ne remonte en tête
    d'AUCUNE liste. D'où la conception actuelle :
      · UNE sonde de tête (la liste générale), à chaque passage ;
      · la SURVEILLANCE des articles retirés de la vente, à chaque passage,
        sur le seau des fiches : c'est elle qui voit les passages en Limited.
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


def _src_sync(nom: str) -> str:
    """Une fonction ORDINAIRE de bot.py, telle quelle (`_src` la rendrait
    asynchrone, et `if _second_seau_libre(E)` serait toujours vrai)."""
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _constante(nom: str):
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == nom for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError(f"{nom} introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le banc : le VRAI corps de l'éclaireur et de la surveillance
# ═══════════════════════════════════════════════════════════════════════════════

class FauxCatalogue:
    """Rend les réponses qu'on lui a écrites, et note ce qu'on lui a demandé."""

    MAX_PUBLICATIONS_PAR_PASSAGE = 12

    #  ⚠️ PIÈGE N°6 : tout ce que le vrai module porte sur ce chemin — la
    #  config des flux, la liste de surveillance, les fiches par identifiants.
    #  Valeur de BANC (pas une mesure) : ce que « Roblox » annonce au refus.
    QUOTA_REFUS = "3, 3;w=10"
    DERNIER_QUOTA_FICHES = None

    def __init__(self, reponses, flux=None, surveilles=(), bascules=(),
                 fiches_refusees=0, economie_max=None, connus=None):
        #  Ce que le relevé complet a déjà enregistré en base.
        self.connus = connus or ({1, 2}, {1})
        #  Un code (refus à chaque appel) ou une LISTE de codes consommés un
        #  par appel — 0 = accepté.
        self.fiches_refusees = fiches_refusees
        #  Combien d'articles l'économie accepte par relais avant son 429 :
        #  None = tous ; 2 = la production du 23/09 sur l'IP de Railway.
        self.economie_max = economie_max
        self.regardes_economie = []
        self.reponses = list(reponses)
        self.demandes = []
        #  `flux={}` veut dire « aucun flux » : ne pas le confondre avec
        #  « non fourni » (un `or` l'aurait remplacé par les deux allumés).
        self.cfg = dict(flux if flux is not None else
                        {"roblox_flux_nouveautes": True,
                         "roblox_flux_bascules": True})
        self.surveilles = list(surveilles)
        self.bascules_a_rendre = list(bascules)
        self.enfiles = []

    async def config(self, _gid):
        return self.cfg

    def flux_allume(self, cfg, flux):
        return bool(cfg.get(f"roblox_flux_{flux}", False))

    def catalogue_est_occupe(self):
        return False

    async def actif(self, _gid):
        return True

    async def identifiants_connus(self):
        return self.connus

    async def liste_de_surveillance(self):
        return list(self.surveilles)

    async def relever_identifiants(self, *, collectionnables=False, limite=120,
                                   seau="identifiants"):
        self.demandes.append(("collect" if collectionnables else "creations")
                             + (":fiches" if seau == "fiches" else ""))
        if self.reponses:
            return self.reponses.pop(0)
        return {"ids": set(), "bundles": set(), "code": 200, "reste": 11}

    #  Le code du dernier `fiches_par_ids` : 429 → relais par l'économie.
    DERNIER_CODE_FICHES = 200

    async def fiches_par_ids(self, ids, item_type=None):
        self.demandes.append(f"fiches:{len(ids)}")
        code = self.fiches_refusees
        if isinstance(code, list):
            code = code.pop(0) if code else 0
        if code:
            self.DERNIER_CODE_FICHES = code
            if code == 429:
                self.DERNIER_QUOTA_FICHES = self.QUOTA_REFUS
            return []
        self.DERNIER_CODE_FICHES = 200
        return [{"asset_id": i} for i in ids]

    async def verifier_par_economie(self, ids):
        """Comme la vraie : s'arrête au 429 AVANT l'article refusé, dit
        jusqu'où elle est allée (`avance`) et ce que Roblox annonçait."""
        self.demandes.append("economie:" + ",".join(str(i) for i in ids))
        n = len(ids) if self.economie_max is None else min(len(ids),
                                                             self.economie_max)
        regardes = list(ids)[:n]
        self.regardes_economie.extend(regardes)
        codes, arret = {200: n}, None
        if n < len(ids):
            codes[429] = 1
            #  Valeurs de BANC (pas une mesure) : le bilan doit les recopier.
            arret = {"code": 429, "apres": n, "limite": "1000, 1000;w=60",
                     "reste": "0", "reset": "31", "retry_after": None}
        devenus = [b for b in self.bascules_a_rendre if b["asset_id"] in regardes]
        return {"devenus": devenus, "vus": n, "avance": n, "codes": codes,
                "arret": arret}

    async def comparer_et_enregistrer(self, fiches):
        ids = {f["asset_id"] for f in fiches}
        bas = [b for b in self.bascules_a_rendre if b["asset_id"] in ids]
        if bas:
            return {"nouveaux": [], "bascules": bas}
        return {"nouveaux": fiches, "bascules": []}

    def ordonner_publication(self, lot, n):
        return list(lot)[:n]

    def age_publiable(self, _a, _flux):
        return True

    async def publiable_dans(self, _gid, _aid, _flux):
        return True

    async def enfiler(self, _gid, a, flux):
        self.enfiles.append((a["asset_id"], flux))
        return True


class FauxAsyncio:
    """Le sommeil est instantané — mais NOTÉ."""

    def __init__(self):
        self.sommeils = []

    async def sleep(self, d):
        self.sommeils.append(d)


def _banc(reponses, etat=None, flux=None, surveilles=(), bascules=(),
          fiches_refusees=0, economie_max=None, connus=None):
    journal = []
    cat = FauxCatalogue(reponses, flux=flux, surveilles=surveilles,
                        bascules=bascules, fiches_refusees=fiches_refusees,
                        economie_max=economie_max, connus=connus)
    E = {"amorce": True, "vus": {1, 2}, "vus_limited": {1},
         "tour": 0, "palier": 0, "pause_jusqu": None, "refus": 0, "reste": None,
         "rattrapes": 0, "serie": 0, "serie_max": 0, "alerte": False,
         "dernier_refus": None, "dernier_succes": datetime.now(timezone.utc),
         "secours_retenus": 0, "secours_pause_jusqu": None,
         "surveilles": 0, "verifs_surveillance": 0,
         "bascules_surveillance": 0, "erreurs_surveillance": 0,
         "refus_surveillance": 0, "verifs_economie": 0,
         "curseur_surveillance": 0,
         "arrets_economie": 0, "dernier_arret_economie": None,
         "codes_economie": {},
         "serie_refus_fiches": 0, "serie_refus_fiches_max": 0,
         "quota_fiches": None,
         "fiches_ratees": 0, "dernier_lot_rate": None, "fiches_tete": 0,
         "passages": 0, "sautes": 0, "erreurs": 0, "nouveautes": 0,
         "bascules": 0, "publies": 0,
         "dernier_passage": None, "dernier_signal": None}
    if etat:
        E.update(etat)
    faux_asyncio = FauxAsyncio()

    async def _publier(*a, **kw):
        journal.append(f"publie:{kw.get('etiquette', '?')}")
        return {"publies": 1}

    ns = {
        "roblox_module": cat,
        "bot": type("B", (), {"guilds": [type("G", (), {"id": 1})()]})(),
        "_ECLAIREUR": E,
        "_publier_file_accessoires": _publier,
        #  Le relevé complet n'est pas imminent dans ces bancs.
        "veille_roblox_task": type("L", (), {"next_iteration": None})(),
        "asyncio": faux_asyncio,
        "random": type("Rnd", (), {"uniform": staticmethod(lambda a, b: 0.5)})(),
        "_age_s": lambda _d: 10,
        "datetime": datetime, "timezone": timezone, "timedelta": timedelta,
        "print": lambda *a, **k: journal.append(" ".join(str(x) for x in a)),
    }
    for nom in ("ECLAIREUR_SECONDES", "ECLAIREUR_PAUSES", "ECLAIREUR_BATTEMENT",
                "ECLAIREUR_ALERTE_APRES_S", "ECLAIREUR_AVANT_RELEVE_S",
                "ECLAIREUR_SECOURS_RESTE_MIN", "ECLAIREUR_SECOURS_PAUSE_S",
                "ECLAIREUR_SURVEILLANCE_LEGERE", "ECLAIREUR_TRANCHE_ECONOMIE"):
        ns[nom] = _constante(nom)
    #  ⚠️ PIÈGE N°6 : les deux gardes du second seau vivent HORS de
    #  l'éclaireur depuis le 23/09 (soir). Sans elles dans le banc, chaque
    #  passage levait un NameError avalé par le `except` — 10 tests rouges.
    for nom in ("_second_seau_libre", "_noter_second_seau"):
        exec(_src_sync(nom), ns)              # noqa: S102 — code du dépôt
    exec(_src("_surveiller_retires"), ns)     # noqa: S102 — code du dépôt
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


def _sondes(cat):
    """Les requêtes de SONDE (pas les fiches)."""
    return [d for d in cat.demandes if not d.startswith("fiches:")]


# ═══════════════════════════════════════════════════════════════════════════════
#  E — la sonde de tête
# ═══════════════════════════════════════════════════════════════════════════════

def test_E1_une_reussite_est_UTILISEE():
    """⚠️ LE DÉFAUT DU 22/09 : la réussite était jetée avec l'échec voisin."""
    ns, E, cat, journal = _banc([_ok([1, 2, 77])])
    _tick(ns)
    assert 77 in E["vus"], "l'identifiant reçu a été jeté"
    assert any("🔔" in l for l in journal), journal


def test_E2_UNE_seule_sonde_de_tete_jamais_celle_des_collectionnables():
    """⚠️ MESURÉ LE 23/09 : le tri est l'ordre de CRÉATION. La tête des
    collectionnables ne montre que des Limited NOUVEAUX — déjà en tête de la
    liste générale — et jamais un vieil article qui vient de passer Limited.
    La regarder coûtait une requête sur deux pour rien."""
    ns, _E, cat, _j = _banc([_ok([1]), _ok([1]), _ok([1])])
    for _ in range(3):
        _tick(ns)
    assert _sondes(cat) == ["creations"] * 3, cat.demandes


def test_E3_plus_de_seconde_sonde_meme_avec_un_quota_large():
    """Un quota confortable n'est pas une raison de dépenser une requête qui
    n'apprend rien."""
    ns, _E, cat, _j = _banc([_ok([1], reste=12)])
    _tick(ns)
    assert _sondes(cat) == ["creations"], cat.demandes


def test_E5_un_refus_des_deux_seaux_RALENTIT():
    """Marteler une IP saturée ne rend pas un quota."""
    ns, E, _cat, _j = _banc([_refus(), _refus(), _refus()])
    _tick(ns)
    assert E["palier"] == 1 and E["pause_jusqu"] is not None
    assert E["refus"] == 2
    avant = E["passages"]
    _tick(ns)
    assert E["passages"] == avant and E["sautes"] >= 1


def test_E6_des_refus_PASSAGERS_n_ecrivent_rien():
    """⚠️ RÉFUTÉ PAR LA PRODUCTION LE 22/09 : l'état basculait à chaque passage
    et « une ligne au changement d'état » faisait ~1 100 lignes par jour."""
    ns, E, _cat, journal = _banc([_refus() for _ in range(12)])
    for _ in range(6):
        E["pause_jusqu"] = None
        _tick(ns)
    assert not [l for l in journal if "[eclaireur]" in l], journal
    assert E["serie"] == 6


def test_E7_la_premiere_reussite_rend_la_cadence_sans_bruit():
    ns, E, _cat, journal = _banc([_refus(), _refus(), _ok([1], reste=3)])
    _tick(ns)
    E["pause_jusqu"] = None
    _tick(ns)
    assert E["palier"] == 0 and E["serie"] == 0
    assert not [l for l in journal if "[eclaireur]" in l], journal


def test_E8_la_cadence_et_les_paliers_sont_ceux_qu_on_a_mesures():
    """45 s, une requête : 1,3/min sur un seau mesuré à 12/min."""
    assert _constante("ECLAIREUR_SECONDES") == 45
    paliers = _constante("ECLAIREUR_PAUSES")
    assert paliers[0] == 0 and paliers[-1] >= 300
    assert list(paliers) == sorted(paliers)


def test_E9_le_SECOND_SEAU_sauve_le_passage_sans_attendre():
    """Refus du premier seau → même question au seau des fiches, tout de suite."""
    ns, E, cat, _j = _banc([_refus(), _ok([1, 2, 99], reste=9)])
    _tick(ns)
    assert 99 in E["vus"] and E["rattrapes"] == 1
    assert _sondes(cat) == ["creations", "creations:fiches"], cat.demandes
    assert ns["_sommeils"] == []


def test_E10_l_aveuglement_PROLONGE_est_dit_une_fois_et_sa_fin_aussi():
    il_y_a_11_min = datetime.now(timezone.utc) - timedelta(minutes=11)
    ns, E, _cat, journal = _banc(
        [_refus() for _ in range(6)] + [_ok([1], reste=3)],
        etat={"dernier_succes": il_y_a_11_min})
    for _ in range(3):
        E["pause_jusqu"] = None
        _tick(ns)
    assert len([l for l in journal if "AVEUGLE" in l]) == 1, journal
    E["pause_jusqu"] = None
    _tick(ns)
    assert len([l for l in journal if "de nouveau lisible" in l]) == 1, journal


def test_E12_on_ne_dort_PAS_sur_retry_after_la_mesure_l_a_refute():
    ns, _E, cat, _j = _banc([_refus(retry=5.0), _refus(retry=5.0)])
    _tick(ns)
    assert ns["_sommeils"] == []
    assert _sondes(cat) == ["creations", "creations:fiches"], cat.demandes


def test_E13_nouveautes_eteintes_AUCUNE_sonde_de_tete():
    """La tête ne sert qu'aux nouveautés : éteintes, on ne l'interroge plus.
    La surveillance, elle, continue."""
    ns, _E, cat, _j = _banc([_ok([1])], flux={"roblox_flux_bascules": True},
                            surveilles=[500])
    _tick(ns)
    assert _sondes(cat) == [], cat.demandes
    assert "fiches:1" in cat.demandes, "la surveillance ne tourne plus"


def test_E14_aucun_flux_AUCUNE_requete():
    ns, _E, cat, _j = _banc([_ok([1])], flux={}, surveilles=[500])
    _tick(ns)
    assert cat.demandes == [], cat.demandes


def test_E15_le_secours_se_RETIENT_juste_avant_le_releve_complet():
    """Mesuré : un secours dans la minute qui précède le relevé lui coûtait sa
    marge (reste_min 3 → 1)."""
    ns, E, cat, _j = _banc([_refus(), _ok([1], reste=9)])
    ns["veille_roblox_task"] = type("L", (), {
        "next_iteration": datetime.now(timezone.utc) + timedelta(seconds=30)})()
    _tick(ns)
    assert _sondes(cat) == ["creations"], cat.demandes
    assert E["secours_retenus"] == 1


def test_E16_un_second_seau_presque_vide_est_laisse_tranquille():
    ns, E, cat, _j = _banc([_refus(), _ok([1], reste=2), _refus()])
    _tick(ns)
    assert E["secours_pause_jusqu"] is not None
    E["pause_jusqu"] = None
    _tick(ns)
    assert cat.demandes.count("creations:fiches") == 1, cat.demandes


# ═══════════════════════════════════════════════════════════════════════════════
#  S — la surveillance des articles retirés de la vente
# ═══════════════════════════════════════════════════════════════════════════════
#  « en vente, retirés de la vente, et d'un seul coup ils passent Limited »

def test_S1_un_article_retire_qui_PASSE_Limited_sort_tout_de_suite():
    """⚠️ LE CŒUR DE LA DEMANDE. Aucune sonde de tête ne le voit (tri par
    création) : la surveillance le regarde, lui, à chaque passage."""
    b = {"asset_id": 500, "nom": "Arcane Fedora", "bascule_detectee": True,
         "collectionnable": 1}
    ns, E, cat, journal = _banc([_ok([1])], surveilles=[500, 501],
                                bascules=[b])
    _tick(ns)
    assert (500, "bascules") in cat.enfiles, cat.enfiles
    assert "publie:surveillance" in journal, journal
    assert any("💎" in l and "surveillance" in l for l in journal), journal
    assert E["bascules_surveillance"] == 1


def test_S2_la_surveillance_passe_MEME_si_la_sonde_est_refusee():
    """Deux seaux différents : une IP saturée côté identifiants ne doit pas
    rendre les passages en Limited invisibles."""
    ns, E, cat, _j = _banc([_refus(), _refus()], surveilles=[500])
    _tick(ns)
    assert "fiches:1" in cat.demandes, cat.demandes
    assert E["verifs_surveillance"] == 1


def test_S3_une_liste_LONGUE_est_verifiee_un_passage_sur_deux():
    """Au-delà de 40 articles, la réponse grossit et le seau des fiches sert
    aussi aux nouveautés : on espace."""
    longue = list(range(1000, 1000 + _constante("ECLAIREUR_SURVEILLANCE_LEGERE") + 5))
    ns, E, cat, _j = _banc([_ok([1]), _ok([1])], surveilles=longue)
    _tick(ns)
    _tick(ns)
    assert sum(1 for d in cat.demandes if d.startswith("fiches:")) == 1, cat.demandes


def test_S4_une_liste_VIDE_ne_coute_aucune_requete():
    ns, _E, cat, _j = _banc([_ok([1])], surveilles=[])
    _tick(ns)
    assert not [d for d in cat.demandes if d.startswith("fiches:")], cat.demandes


def test_S5_un_article_surveille_qui_n_a_PAS_bouge_ne_publie_rien():
    """Le cas de tous les passages : 28 articles regardés, aucun n'a changé."""
    ns, _E, cat, journal = _banc([_ok([1])], surveilles=[500, 501])
    _tick(ns)
    assert not cat.enfiles and "publie:surveillance" not in journal


def test_S6_seau_des_fiches_REFUSE_l_economie_prend_le_relais():
    """⚠️ MESURÉ EN PRODUCTION LE 23/09 : `HTTP 429 pour 27 identifiant(s)`
    à deux passages de suite. L'économie a son propre quota (1000/min,
    mesuré) : une tranche de 9 est vérifiée à sa place, et un passage en
    Limited trouvé ainsi sort comme les autres."""
    ids = list(range(500, 527))
    b = {"asset_id": 503, "nom": "Arcane Fedora", "bascule_detectee": True,
         "collectionnable": 1}
    ns, E, cat, journal = _banc([_ok([1])], surveilles=ids, bascules=[b],
                                fiches_refusees=429)
    _tick(ns)
    eco = [d for d in cat.demandes if d.startswith("economie:")]
    assert eco == ["economie:" + ",".join(str(i) for i in ids[:9])], cat.demandes
    assert E["refus_surveillance"] == 1 and E["verifs_economie"] == 9
    assert (503, "bascules") in cat.enfiles and "publie:surveillance" in journal


def test_S7_le_relais_TOURNE_sur_toute_la_liste():
    """Neuf par passage, en rotation : 27 articles revus en trois passages,
    jamais les neuf mêmes."""
    ids = list(range(500, 527))
    ns, E, cat, _j = _banc([_ok([1]), _ok([1]), _ok([1])], surveilles=ids,
                           fiches_refusees=429)
    for _ in range(3):
        _tick(ns)
    vus = [d.split(":")[1] for d in cat.demandes if d.startswith("economie:")]
    assert [v.split(",")[0] for v in vus] == ["500", "509", "518"], vus


def test_S8_une_autre_panne_que_le_429_ne_declenche_PAS_le_relais():
    """Le relais répond à un seau refusé, pas à n'importe quelle erreur."""
    ns, E, cat, _j = _banc([_ok([1])], surveilles=[500], fiches_refusees=500)
    _tick(ns)
    assert not [d for d in cat.demandes if d.startswith("economie:")]
    assert E["erreurs_surveillance"] == 1


def _bilan_economie():
    """La VRAIE `_bilan_economie` de bot.py (fonction ordinaire, pas `_src`,
    qui la rendrait asynchrone)."""
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.FunctionDef) and n.name == "_bilan_economie":
            ns = {}
            exec(ast.unparse(n), ns)          # noqa: S102 — code du dépôt
            return ns["_bilan_economie"]
    raise AssertionError("_bilan_economie introuvable dans bot.py")


def test_S9_a_DEUX_articles_par_relais_TOUTE_la_liste_est_revue():
    """⚠️ LA PRODUCTION DU 23/09 (Railway, 3 heures) : « 9 refus du seau des
    fiches → 18 vérification(s) par l'économie », puis 18 → 36, 27 → 54…
    L'économie s'arrêtait au 3ᵉ article ; le curseur sautait quand même de 9.
    27 = 3 × 9 : les tranches étaient toujours les trois mêmes, et 21 articles
    sur 27 n'étaient JAMAIS regardés par le relais. Le curseur avance
    maintenant de ce qui a été vu : en 14 relais, les 27 y passent."""
    ids = list(range(500, 527))
    ns, E, cat, _j = _banc([], surveilles=ids, fiches_refusees=429,
                           economie_max=2)
    for _ in range(14):
        _tick(ns)
    manquants = sorted(set(ids) - set(cat.regardes_economie))
    assert not manquants, f"{len(manquants)} article(s) jamais regardé(s) : {manquants}"
    departs = [d.split(":")[1].split(",")[0] for d in cat.demandes
               if d.startswith("economie:")]
    assert departs[:4] == ["500", "502", "504", "506"], departs
    assert E["verifs_economie"] == 28 and E["arrets_economie"] == 14


def test_S10_le_bilan_dit_POURQUOI_l_economie_s_arrete():
    """Le bilan disait « 18 vérification(s) par l'économie » sans dire
    pourquoi pas 81. Il recopie ce que Roblox annonçait au moment du refus :
    c'est ce qui départagera « l'IP partagée a vidé le quota » d'« une autre
    limite pour les hébergeurs »."""
    ns, E, _cat, _j = _banc([], surveilles=list(range(500, 527)),
                            fiches_refusees=429, economie_max=2)
    _tick(ns)
    assert E["arrets_economie"] == 1 and E["dernier_arret_economie"]["apres"] == 2
    ligne = _bilan_economie()(E)
    assert "arrêtée 1 fois par un 429" in ligne, ligne
    assert "après 2 article(s)" in ligne and "« 1000, 1000;w=60 »" in ligne, ligne
    assert "reste 0" in ligne, ligne
    assert _bilan_economie()({"arrets_economie": 0, "codes_economie": {200: 9}}) == ""


def test_S11_la_plus_longue_serie_de_refus_des_fiches_est_comptee():
    """Le pire retard de la surveillance, c'est la plus longue série de
    passages où la requête groupée est refusée."""
    ns, E, _cat, _j = _banc([], surveilles=[500, 501],
                            fiches_refusees=[429, 429, 429, 0, 429])
    for _ in range(5):
        _tick(ns)
    assert (E["serie_refus_fiches_max"], E["serie_refus_fiches"]) == (3, 1), E
    assert E["refus_surveillance"] == 4


def test_S12_un_autre_code_de_l_economie_n_est_plus_avale():
    """Un 404 était sauté sans un mot. Il est compté, et dit au bilan ; et le
    curseur avance de ce qui a eu une réponse, 404 compris."""
    ns, E, cat, _j = _banc([], surveilles=[500, 501, 502], fiches_refusees=429)

    async def _eco(tranche):
        cat.demandes.append("economie:" + ",".join(map(str, tranche)))
        return {"devenus": [], "vus": 1, "avance": 2,
                "codes": {200: 1, 404: 1}, "arret": None}
    cat.verifier_par_economie = _eco
    _tick(ns)
    assert E["codes_economie"] == {200: 1, 404: 1}
    assert E["curseur_surveillance"] == 2
    assert "HTTP 404 ×1" in _bilan_economie()(E)


def test_S13_le_bilan_de_30_min_BRANCHE_le_relais():
    """Une fonction jamais appelée n'informe personne."""
    blocs = [ast.unparse(n) for n in ast.walk(ARBRE)
             if isinstance(n, ast.IfExp)
             and "refus du seau des fiches" in ast.unparse(n)]
    assert blocs, "la ligne du bilan sur les refus des fiches a disparu"
    assert any("_bilan_economie(_E)" in b and "serie_refus_fiches_max" in b
               for b in blocs), blocs


def test_S14_le_quota_annonce_au_refus_de_la_requete_groupee_est_GARDE():
    """C'est ce que le bilan de l'économie a appris (« 2, 2;w=1 ») : la même
    question, pour la requête groupée — celle qui échouait 60 fois en 1 h 15."""
    ns, E, _cat, _j = _banc([_ok([1])], surveilles=[500], fiches_refusees=429)
    _tick(ns)
    assert E["quota_fiches"] == FauxCatalogue.QUOTA_REFUS
    assert any("quota_fiches" in b for b in (
        ast.unparse(n) for n in ast.walk(ARBRE) if isinstance(n, ast.IfExp)
        and "refus du seau des fiches" in ast.unparse(n))), "le bilan ne le dit pas"


# ═══════════════════════════════════════════════════════════════════════════════
#  T — les nouveautés : la fiche d'abord là où elle est déjà
# ═══════════════════════════════════════════════════════════════════════════════
#  JOURNAL RAILWAY DU 23/09 (soir) : « 5 identifiant(s) jamais vu(s) mais
#  aucune fiche obtenue — nouvel essai dans 45 s », 60 fois en 1 h 15. La même
#  requête passe 12 fois sur 12 depuis un poste résidentiel.

def _ok_fiches(ids, fiches, reste=9):
    """La tête du SECOND seau : les identifiants ET leurs fiches, comme le vrai
    `relever_identifiants(seau="fiches")` depuis le 23/09."""
    r = _ok(ids, reste=reste)
    r["fiches"] = [dict(f) for f in fiches]
    return r


def test_T1_les_fiches_DEJA_EN_MAIN_servent_sans_requete_groupee():
    f = {"asset_id": 777, "nom": "Canon à confettis", "hors_vente": 0}
    ns, E, cat, _j = _banc([_refus(), _ok_fiches([1, 2, 777], [f])])
    _tick(ns)
    assert (777, "nouveautes") in cat.enfiles, cat.enfiles
    assert not [d for d in cat.demandes if d.startswith("fiches:")], (
        "la fiche était déjà là : une requête groupée pour rien", cat.demandes)


def test_T2_requete_groupee_REFUSEE_la_tete_du_second_seau_la_remplace():
    """Le cas du 23/09 : le premier seau voit la nouveauté, la requête
    groupée est refusée — la tête AVEC ses fiches la rattrape au même passage."""
    f = {"asset_id": 888, "nom": "Nouveau", "hors_vente": 0}
    ns, E, cat, journal = _banc([_ok([1, 2, 888]), _ok_fiches([1, 2, 888], [f])],
                                fiches_refusees=429)
    _tick(ns)
    assert cat.demandes == ["creations", "fiches:1", "creations:fiches"], cat.demandes
    assert (888, "nouveautes") in cat.enfiles and E["fiches_tete"] == 1
    assert not [l for l in journal if "sans fiche" in l], journal


def test_T3_sans_fiche_UNE_ligne_par_lot_pas_une_par_passage():
    """⚠️ LA MÊME LIGNE 60 FOIS EN 1 H 15. Une ligne pour le lot ; les essais
    suivants se font en silence, comptés au bilan — et l'identifiant reste
    « jamais vu » pour être réessayé."""
    ns, E, _cat, journal = _banc(
        [_ok([1, 2, 999]), _refus(), _ok([1, 2, 999]), _refus(),
         _ok([1, 2, 999]), _refus()], fiches_refusees=429)
    for _ in range(3):
        _tick(ns)
    assert len([l for l in journal if "sans fiche" in l]) == 1, journal
    assert E["fiches_ratees"] == 3
    assert 999 not in E["vus"], "plus jamais réessayé : il attendrait le relevé"


def test_T4_ce_que_le_releve_a_DEJA_enregistre_n_est_plus_redemande():
    """Le relevé complet l'a vu, et publié s'il le fallait : le redemander à
    chaque passage était la boucle du 23/09."""
    ns, E, _cat, journal = _banc([_ok([1, 2, 555]), _refus()], fiches_refusees=429,
                                 connus=({1, 2, 555}, {1}))
    _tick(ns)
    assert 555 in E["vus"] and E["fiches_ratees"] == 0
    assert not [l for l in journal if "sans fiche" in l], journal


def test_T5_la_tete_de_secours_respecte_les_gardes_du_second_seau():
    """Pas dans les 75 s qui précèdent le relevé complet : sa marge d'abord."""
    ns, _E, cat, _j = _banc([_ok([1, 2, 444])], fiches_refusees=429)
    ns["veille_roblox_task"] = type("L", (), {
        "next_iteration": datetime.now(timezone.utc) + timedelta(seconds=30)})()
    _tick(ns)
    assert "creations:fiches" not in cat.demandes, cat.demandes


# ═══════════════════════════════════════════════════════════════════════════════
#  N — la sonde d'actualités
# ═══════════════════════════════════════════════════════════════════════════════

def test_N1_la_sonde_demande_CINQ_billets_et_pas_trente():
    """Mesuré le 22/09 avec le vrai code : 70,0 Ko contre 708,4 Ko par passage,
    297 ms contre 9 265 ms sur « annonces », cinq plus récents identiques."""
    src = (RACINE / "roblox_news.py").read_text(encoding="utf-8")
    assert 'url = source["url"] + ("&per_page=5" if leger else "")' in src
    i = src.index("async def relever(")
    assert "leger: bool = False" in src[i:i + 400]


def test_N2_l_eclaireur_d_actualites_UTILISE_la_sonde_legere():
    assert "leger=True" in _src("eclaireur_actu_task")


def test_N3_les_categories_CHAUDES_sont_regardees_a_chaque_passage():
    assert _constante("ECLAIREUR_ACTU_SECONDES") == 30
    chaudes = _constante("ECLAIREUR_ACTU_CHAUDES")
    assert "annonces" in chaudes and "alertes" in chaudes
    assert "ECLAIREUR_ACTU_CHAUDES" in _src("eclaireur_actu_task")


def test_N4_le_battement_reste_a_30_minutes():
    assert (_constante("ECLAIREUR_ACTU_SECONDES")
            * _constante("ECLAIREUR_ACTU_BATTEMENT")) == 1800
