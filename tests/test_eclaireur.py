"""L'éclaireur — savoir à l'instant, sans relevé complet.

═══════════════════════════════════════════════════════════════════════════════
DEMANDE DU PROPRIÉTAIRE (14/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « ça prend beaucoup plus de temps que d'autres serveurs et il faut que ce
      soit sur l'instant t […] dès qu'un item passe Limited, dès qu'il y a une
      news, on est directement au courant […] sans que ça envoie trop de
      demandes »

CE QUI COÛTAIT DU TEMPS — MESURÉ DANS LE CODE, PAS SUPPOSÉ. Un seul rythme
servait à tout : le passage de 30 minutes paginait 9 à 12 pages à 8 s de pause
chacune (~100 s), puis attendait 60 s avant les fiches. Une création tombant
juste après un passage attendait jusqu'à 33 minutes. Les actualités du forum
suivaient une cadence de 30 à 120 minutes par source, lue seulement au passage.

LE PRINCIPE : séparer DÉTECTER (bon marché, fréquent) de RELEVER (coûteux,
rare). Mesuré le 14/09 sur l'API réelle :
  · `/v1/search/items` (identifiants seuls) a SON PROPRE quota de 12/min,
    distinct de celui des fiches ; il accepte 120 identifiants par requête et
    ne pèse que quelques kilo-octets ;
  · le forum Discourse en JSON pèse 88 Ko par catégorie, contre 285 Ko pour
    son RSS et 560 Ko pour la salle de presse.

⚠️ LE POINT QUI COMPTE LE PLUS : les éclaireurs publient par LES MÊMES
fonctions que le passage complet (`_publier_file_accessoires`,
`_enfiler_billets`, `_publier_file_actualites`), extraites de la boucle pour
l'occasion. Une copie aurait divergé à la première correction — et la première
chose à diverger aurait été la réservation avant envoi, donc les doublons.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path

import aiosqlite
import pytest

import roblox_news as news
import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC_BOT)


def _fn(nom: str) -> str:
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _constante(nom: str):
    """La valeur d'une constante du module, quel que soit son type.

    ⚠️ Rendait `int()` seulement : `ECLAIREUR_ACTU_CHAUDES` (un tuple) faisait
    échouer la recherche avec « introuvable » — un faux négatif qui accuse le
    code alors que c'est la sonde du test qui ne sait pas lire.
    """
    for n in ast.walk(ARBRE):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and getattr(n.targets[0], "id", "") == nom):
            try:
                return ast.literal_eval(n.value)
            except (ValueError, SyntaxError):
                continue
    raise AssertionError(f"{nom} introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le relevé d'identifiants — la requête de l'éclaireur, exécutée pour de vrai
# ═══════════════════════════════════════════════════════════════════════════════

class _Reponse:
    def __init__(self, status, data, reste="11"):
        self.status = status
        self.headers = {"x-ratelimit-remaining": reste}
        self._data = data

    async def json(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    """Un faux `aiohttp.ClientSession` qui NOTE ce qu'on lui demande."""
    def __init__(self, status=200, data=None, journal=None):
        self.status, self.data = status, data or {"data": []}
        self.journal = journal if journal is not None else []

    def get(self, url, params=None, **kw):
        self.journal.append((url, dict(params or {})))
        return _Reponse(self.status, self.data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_le_releve_d_identifiants_frappe_le_bon_point_avec_les_bons_parametres(monkeypatch):
    """⚠️ LE CHEMIN EST LA MOITIÉ DE L'OPTIMISATION. `/v1/search/items` a son
    propre quota ; `/v1/search/items/details` est celui que le passage complet
    épuise. Se tromper de chemin remettrait l'éclaireur en concurrence avec le
    relevé — et le 429 mesuré le 16/08 reviendrait."""
    j = []
    monkeypatch.setattr(veille, "_ouvrir",
                        lambda: _Session(data={"data": [{"id": 5, "itemType": "Asset"}]},
                                         journal=j))
    r = await veille.relever_identifiants()
    assert r["code"] == 200 and r["ids"] == {5}
    url, p = j[0]
    assert url == veille.API_IDENTIFIANTS
    assert url.endswith("/v1/search/items"), "ce n'est pas le point « identifiants seuls »"
    assert "/details" not in url, "on frappe le point des FICHES : même quota que le relevé"
    assert p["CreatorTargetId"] == veille.CREATEUR_ROBLOX
    assert p["SortType"] == 3
    assert p["IncludeNotForSale"] == "true", (
        "sans ce drapeau, une création hors vente (Sakura Antlers, 30/08) reste invisible")
    assert p["Limit"] <= 120, "la v1 refuse au-delà de 120"
    assert "SalesTypeFilter" not in p


@pytest.mark.asyncio
async def test_le_filtre_collectionnables_ne_change_QUE_ce_parametre(monkeypatch):
    """Même question, même tri, même créateur — un seul paramètre en plus.
    Deux requêtes qui divergeraient ailleurs mesureraient deux choses."""
    j = []
    monkeypatch.setattr(veille, "_ouvrir", lambda: _Session(journal=j))
    await veille.relever_identifiants(collectionnables=False)
    await veille.relever_identifiants(collectionnables=True)
    p1, p2 = j[0][1], j[1][1]
    assert p2.pop("SalesTypeFilter") == 2
    assert p1 == p2


@pytest.mark.asyncio
async def test_les_bundles_sont_distingues_des_assets(monkeypatch):
    """⚠️ Un bundle demandé comme asset ne revient jamais, et l'identifiant —
    déjà marqué « vu » — ne serait plus jamais redemandé : le bundle
    n'existerait pas pour l'éclaireur."""
    monkeypatch.setattr(veille, "_ouvrir", lambda: _Session(data={"data": [
        {"id": 1, "itemType": "Asset"}, {"id": 2, "itemType": "Bundle"},
        {"id": 3, "itemType": "Asset"}]}))
    r = await veille.relever_identifiants()
    assert r["ids"] == {1, 2, 3}
    assert r["bundles"] == {2}


@pytest.mark.asyncio
async def test_une_panne_rend_le_code_et_aucun_identifiant(monkeypatch):
    """Sur 429 ou 5xx, l'éclaireur doit SAVOIR et attendre — pas croire que le
    catalogue est vide et « oublier » 120 identifiants."""
    monkeypatch.setattr(veille, "_ouvrir", lambda: _Session(status=429))
    r = await veille.relever_identifiants()
    assert r["code"] == 429 and r["ids"] == set()


@pytest.mark.asyncio
async def test_le_releve_ne_leve_jamais(monkeypatch):
    class _Casse:
        def get(self, *a, **k):
            raise RuntimeError("réseau")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(veille, "_ouvrir", lambda: _Casse())
    r = await veille.relever_identifiants()
    assert r["ids"] == set() and r["code"] is None


# ═══════════════════════════════════════════════════════════════════════════════
#  L'amorce — sur une VRAIE base, pas un faux
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def banc(tmp_path):
    chemin = tmp_path / "ecl.db"

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return {}

    async def _db_set(_g, _k, _v):
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set, log=lambda *a, **k: None)
    news.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set, log=lambda *a, **k: None)
    return _get_db


@pytest.mark.asyncio
async def test_l_amorce_repart_de_ce_que_le_releve_complet_connait(banc):
    """⚠️ SANS AMORCE, le premier passage verrait 120 identifiants « jamais
    vus » et irait chercher 120 fiches pour rien — à chaque redémarrage."""
    await veille.init_db()
    async with banc() as db:
        await db.execute(
            "INSERT INTO roblox_articles(asset_id, nom, collectionnable, hors_vente, favoris, vu_le)"
            " VALUES(?,?,?,?,?,?)", (10, "a", 0, 0, 0, "2026-09-14T00:00:00+00:00"))
        await db.execute(
            "INSERT INTO roblox_articles(asset_id, nom, collectionnable, hors_vente, favoris, vu_le)"
            " VALUES(?,?,?,?,?,?)", (11, "b", 1, 0, 0, "2026-09-14T00:00:00+00:00"))
        await db.commit()
    tous, lim = await veille.identifiants_connus()
    assert tous == {10, 11}
    assert lim == {11}, "les collectionnables doivent être amorcés à part"


@pytest.mark.asyncio
async def test_l_amorce_des_actualites_melange_les_deux_tables_en_TEXTE(banc):
    """`roblox_news_file.topic_id` est TEXT (slugs du newsroom),
    `roblox_news_publies.topic_id` INTEGER. Un ensemble mixte ne comparerait
    rien : tout doit sortir en chaîne."""
    await news.init_db()
    async with banc() as db:
        await db.execute("INSERT INTO roblox_news_publies(guild_id, topic_id, publie_le)"
                         " VALUES(1, 4833635, '2026-09-14')")
        await db.execute("INSERT INTO roblox_news_file(guild_id, topic_id, charge, detecte_le)"
                         " VALUES(1, 'newsroom:2026/09/x', '{}', '2026-09-14')")
        await db.commit()
    vus = await news.identifiants_connus_actus()
    assert vus == {"4833635", "newsroom:2026/09/x"}
    assert all(isinstance(x, str) for x in vus)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'éclaireur d'accessoires — structure, ordre, économie
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_cadence_est_rapide_ET_economique():
    """« sur l'instant t » ET « pas trop de demandes ».

    ⚠️ RÉÉCRIT LE 22/09 : la borne portait sur l'INTERVALLE, or ce qui compte
    est le DÉBIT. Depuis le correctif du 429, l'éclaireur n'envoie qu'UNE
    requête par passage (alternance créations/collectionnables) et n'ajoute la
    seconde que si l'en-tête de quota annonce de la place. À 45 s, c'est
    1,3 requête/min sur un seau MESURÉ à `12, 12;w=60` — et jusqu'à 2,7 quand
    le quota est libre, toujours sous le quart du plafond.
    """
    s = _constante("ECLAIREUR_SECONDES")
    assert 30 <= s <= 300, f"cadence hors de raison : {s} s"
    #  Le pire cas : les deux requêtes à chaque passage (quota confortable).
    assert 2 * 60 / s <= 4, "plus de 4 requêtes/min : ce n'est plus un éclaireur"
    #  Le cas normal : une seule requête par passage.
    assert 60 / s <= 2, "plus de 2 requêtes/min en régime normal"


def test_l_eclaireur_ne_touche_pas_au_quota_des_fiches_tant_que_rien_ne_bouge():
    """Deux relevés d'identifiants, puis RIEN si l'ensemble n'a pas changé —
    c'est ce qui rend la cadence tenable."""
    c = _fn("eclaireur_task")
    assert c.count("relever_identifiants(") == 2
    #  ⚠️ L'ALTERNANCE (22/09) : plus de `False`/`True` en dur. Le passage
    #  interroge UNE file, et l'autre seulement si le quota le permet — c'est
    #  ce qui a mis fin au 429 systématique mesuré en production.
    assert "collectionnables=collect" in c and "collectionnables=not collect" in c
    i_neufs = c.index("if not neufs:")
    i_fiches = c.index("fiches_par_ids(")
    assert i_neufs < i_fiches, "les fiches partent avant de savoir si quelque chose a bougé"


def test_l_eclaireur_cede_la_place_au_releve_complet():
    """Le passage complet tient le chemin des fiches ; s'y superposer, c'est le
    429 mesuré le 16/08. Au pire 4 minutes de retard toutes les 30, jamais un
    doublon."""
    c = _fn("eclaireur_task")
    assert "catalogue_est_occupe()" in c
    assert c.index("catalogue_est_occupe()") < c.index("relever_identifiants(")


def test_l_eclaireur_publie_par_le_MEME_corps_que_le_passage():
    """⚠️ LE POINT QUI COMPTE LE PLUS. Réservation avant envoi, marquage après
    succès, simulation, budget équitable : tout ça vit dans
    `_publier_file_accessoires`, et NULLE PART AILLEURS."""
    c = _fn("eclaireur_task")
    assert "_publier_file_accessoires(" in c
    assert "pause_fiches=0" in c, (
        "l'éclaireur n'a fait que deux requêtes sur un autre quota : la "
        "respiration de 60 s du passage complet n'a aucun sens ici")
    for interdit in ("roblox_module.reserver(", "roblox_ui.publier(",
                     "marquer_envoye("):
        assert interdit not in c, f"{interdit} recopié dans l'éclaireur : deux corps"


def test_l_eclaireur_applique_les_MEMES_filtres_que_l_etape_1():
    """Fenêtre d'âge puis « déjà sorti » puis unicité en base — dans cet ordre.
    Sans `age_publiable`, le premier passage après un vide de base
    déverserait l'historique."""
    c = _fn("eclaireur_task")
    i_age = c.index("age_publiable(")
    i_deja = c.index("publiable_dans(")
    i_enf = c.index("enfiler(")
    assert i_age < i_deja < i_enf


def test_un_echec_de_fiches_rend_les_identifiants_a_jamais_vus():
    """⚠️ Sinon un échec de fiches les ferait passer pour traités, et le seul
    rattrapage serait le passage complet — 30 minutes, le délai qu'on chasse."""
    c = _fn("eclaireur_task")
    i_vide = c.index("if not fiches:")
    bloc = c[i_vide:i_vide + 700]
    assert "E['vus'] -= neufs" in bloc and "E['vus_limited'] -= neufs" in bloc


def test_l_eclaireur_a_une_ligne_de_vie():
    """La leçon de `veille_marche_task`, muet cinq heures : une boucle qui ne
    parle que quand quelque chose bouge est indiscernable d'une boucle morte."""
    c = _fn("eclaireur_task")
    assert "ECLAIREUR_BATTEMENT" in c
    b = _constante("ECLAIREUR_BATTEMENT")
    s = _constante("ECLAIREUR_SECONDES")
    assert 10 * 60 <= b * s <= 60 * 60, "battement absurde (viser ~30 min)"
    bilan = _fn("veille_roblox_task")
    assert "ÉCLAIREUR MUET" in bilan, (
        "le bilan de 30 min ne dénonce pas un éclaireur mort : le délai "
        "reviendrait à 30 min sans que rien ne le dise")


def test_les_deux_eclaireurs_sont_supervises_et_demarres():
    """Piège n°2 du dépôt : le superviseur relance PAR NOM. Absents de la
    liste, ils meurent à la première exception jusqu'au redémarrage."""
    for nom in ("eclaireur_task", "eclaireur_actu_task"):
        assert f'"{nom}",' in SRC_BOT, f"{nom} n'est pas supervisé"
        assert f"{nom}.start()" in SRC_BOT, f"{nom} n'est jamais démarré"
        assert f"@{nom}.before_loop" in SRC_BOT, f"{nom} ne attend pas la connexion"


# ═══════════════════════════════════════════════════════════════════════════════
#  L'éclaireur d'actualités
# ═══════════════════════════════════════════════════════════════════════════════

def test_l_eclaireur_d_actualites_ne_lit_que_le_forum():
    """Les salles de presse pèsent 560 Ko pour deux articles par mois (mesuré) :
    les relire toutes les 90 s serait précisément « spammer une recherche qui
    sert à rien »."""
    c = _fn("eclaireur_actu_task")
    assert "!= 'discourse'" in c or '!= "discourse"' in c
    assert "forcer=True" in c, "sans `forcer`, la cadence de 30-120 min bloque tout"


def test_l_eclaireur_d_actualites_respire_entre_les_sources():
    c = _fn("eclaireur_actu_task")
    assert "asyncio.sleep(2)" in c


def test_l_eclaireur_d_actualites_passe_par_les_corps_partages():
    c = _fn("eclaireur_actu_task")
    assert "_enfiler_billets(" in c and "_publier_file_actualites(" in c
    for interdit in ("reserver_actu(", "publier_actu(", "absorber_vieux("):
        assert interdit not in c, f"{interdit} recopié : deux corps"


def test_la_cadence_des_actualites_est_raisonnable():
    """⚠️ RÉÉCRIT LE 22/09, APRÈS MESURE. La sonde ne lit plus 30 billets par
    catégorie mais 5 : 70,0 Ko par passage contre 708,4 Ko, et 297 ms contre
    9 265 ms sur « annonces » (vrai code, vraies URL, cache chaud). Trois fois
    plus souvent coûte donc deux fois moins cher — et seules les deux
    catégories chaudes tournent à chaque passage.
    """
    s = _constante("ECLAIREUR_ACTU_SECONDES")
    assert 20 <= s <= 300
    chaudes = len(_constante("ECLAIREUR_ACTU_CHAUDES"))
    #  chaudes à chaque passage + les 3 autres un passage sur trois.
    req_min = (chaudes + 3 / 3) * 60 / s
    assert req_min <= 8, f"{req_min:.1f} req/min vers le forum : trop"


# ═══════════════════════════════════════════════════════════════════════════════
#  La boucle de 30 min n'a plus de copie : UN corps, trois fonctions
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_boucle_complete_publie_par_les_fonctions_partagees():
    c = _fn("veille_roblox_task")
    for f in ("_publier_file_accessoires(", "_enfiler_billets(",
              "_publier_file_actualites("):
        assert f in c, f"la boucle n'appelle pas {f}"
    for inline in ("roblox_module.reserver(", "reserver_actu(",
                   "marquer_envoye(", "marquer_actu_envoyee("):
        assert inline not in c, f"{inline} encore inline : deux corps"


def test_le_corps_partage_reserve_AVANT_d_envoyer_et_marque_APRES():
    """Le contrat mesuré le 30/08 (6 messages pour une file de 3 sans
    réservation) doit survivre à l'extraction."""
    c = _fn("_publier_file_accessoires")
    assert c.index("reserver(") < c.index("roblox_ui.publier(") < c.index("marquer_envoye(")
    c2 = _fn("_publier_file_actualites")
    assert c2.index("reserver_actu(") < c2.index("publier_actu(") < c2.index("marquer_actu_envoyee(")


def test_le_corps_partage_respecte_la_simulation():
    for f in ("_publier_file_accessoires", "_publier_file_actualites"):
        assert "roblox_veille_simulation" in _fn(f), f"{f} ignore la simulation"


def test_la_respiration_ne_s_applique_que_si_demandee():
    """Le passage complet la garde (429 mesuré le 16/08) ; l'éclaireur passe 0."""
    c = _fn("_publier_file_accessoires")
    assert "pause_fiches > 0" in c
    boucle = _fn("veille_roblox_task")
    assert "pause_fiches=roblox_module.PAUSE_AVANT_FICHES" in boucle
