"""Les cartes cadeaux Roblox — ce qu'une carte donne AUJOURD'HUI (29/09/2026).

DEMANDES DU PROPRIÉTAIRE
    « On achète des cartes cadeaux à chaque fois, ça change les items.
      J'aimerais aussi que tu affiches les items disponibles dans les cartes
      cadeaux. Que ce soit optimisé. »
    « On peut mettre les prochains, mais il faut que tu sois sûr de toi […]
      Tu regroupes, oui, mais tu t'assures que ça ne prenne pas trop de place
      non plus. Que ce soit compréhensible. […] tu ne dois pas non plus
      envoyer un maximum de requêtes. »

MESURÉ LE 29/09 SUR LA PAGE OFFICIELLE (roblox.com/giftcards-fr) : la liste vit
dans son script `…-GiftCards.js`, pays par pays, en hexadécimal. Pour la
France : Icarus Wings, Cap of Hermes, Helm of Ares, Minotaur Head, Medusa
Snakes. `EXTRAIT_REEL` est le morceau de ce script, recopié tel quel. Le mois
suivant n'est écrit QUE dans la description de l'article « carte en magasin »
(Sparkling Robux Shades : « … select retailers in October 2026 »), que le
relevé hors vente de 30 min lit déjà (rang 114 sur 238, mesuré le 29/09).

Ces tests n'appellent jamais le réseau.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord
import pytest

import roblox_cartes as cartes
import roblox_panneau as rp

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")

#  Le morceau réel du script de la page, relevé le 29/09/2026 (614 caractères).
EXTRAIT_REEL = (
    'w=["familymart","seven11"],j=["kkmart","cosway"],y=[0x7f0a82b787c3,'
    '0x710c5f4c38e1,0x72ab07221a41,0x65dcf7ffa48d],R=[0x7f0a82b787c3],'
    'z=[0x6f757ea12773],N=[0x7f0a82b787c3],C=[],S={};[{countries:["ae","ca",'
    '"de","es","fr","it","jp","sa","uk"],config:{bonus_items:z,cashstar_items:N,'
    'items:y}},{countries:["us"],config:{bonus_items:C,cashstar_items:C,items:y}}'
    ',{countries:["at","au","be","br","ch","fi","gr","ie","mx","nl","nz","pl",'
    '"pt","za"],config:{bonus_items:z,cashstar_items:N,items:R}},{countries:["cy"'
    ',"dk","hu","ko","lv","my","no","ro","se","sg","sk","sl","th"],config:'
    '{bonus_items:C,cashstar_items:C,items:R}}]')
ICARE, HERMES, ARES, MINOTAURE, MEDUSE = (139683119466435, 124297952377057,
                                          126078884649537, 111999727936653,
                                          122550426347379)
#  L'article de la carte en magasin d'OCTOBRE — déjà au catalogue le 29/09.
OCTOBRE = 111233368930573
FR = {"items": [ICARE, HERMES, ARES, MINOTAURE], "bonus_items": [MEDUSE],
      "cashstar_items": [ICARE]}
PAGE = ('<link rel="stylesheet" href="https://css.rbxcdn.com/7e34-GiftCards.css" />'
        '<script src="https://js.rbxcdn.com/91bb7dcef33281e011f195624d233b3b813edc'
        '589de013fcc2d9851ccfa73b3b-GiftCards.js"></script>')
MAGASIN_SEPT = ("Get this item when you redeem a Roblox Gift Card from select "
                "retailers in September 2026.")
MAGASIN_OCT = ("Get this item when you redeem a Roblox Gift Card from select "
               "retailers in October 2026.")
AMAZON = "Get this item when you redeem select Robux Digital Gift Card Codes from Amazon."
IMG = "https://tr.rbxcdn.com/180DAY-x/420/420/Hat/Png/noFilter"


# ═══════════════════════════════════════════════════════════════════════════════
#  A — lire la liste officielle
# ═══════════════════════════════════════════════════════════════════════════════

def test_A1_le_script_reel_donne_l_offre_francaise():
    assert cartes.offre_du_script(EXTRAIT_REEL) == FR


def test_A2_chaque_pays_a_sa_liste():
    assert cartes.offre_du_script(EXTRAIT_REEL, "us") == {
        "items": FR["items"], "bonus_items": [], "cashstar_items": []}
    assert cartes.offre_du_script(EXTRAIT_REEL, "th")["items"] == [ICARE]


def test_A3_les_noms_de_variables_changent_a_chaque_version():
    """Le script est minifié : `y`, `z`, `N` sont des noms de circonstance."""
    renomme = EXTRAIT_REEL
    for ancien, neuf in (("y", "Qa"), ("z", "k9"), ("N", "$b"), ("C", "Ee")):
        renomme = re.sub(r"(?<![\w$\"])" + re.escape(ancien) + r"(?=[=,}])", neuf, renomme)
    assert "Qa=[" in renomme and "items:Qa" in renomme
    assert cartes.offre_du_script(renomme) == FR


def test_A3bis_la_declaration_la_plus_proche_gagne():
    """Minifié, `y` peut désigner autre chose plus haut dans le script : seule
    la déclaration qui précède la configuration est la bonne."""
    js = "function a(){var y=[3,4]};" + EXTRAIT_REEL
    assert cartes.offre_du_script(js) == FR


def test_A4_listes_en_ligne_et_nombres_decimaux():
    js = ('{countries:["fr"],config:{bonus_items:[122550426347379],'
          'cashstar_items:[],items:[0x7f0a82b787c3,124297952377057]}}')
    assert cartes.offre_du_script(js) == {
        "items": [ICARE, HERMES], "bonus_items": [MEDUSE], "cashstar_items": []}


@pytest.mark.parametrize("js", [
    "", "rien d'utile ici",
    EXTRAIT_REEL.replace('"fr",', ""),
    EXTRAIT_REEL.replace("y=[0x7f0a82b787c3,", "yy=[0x7f0a82b787c3,"),
    '{countries:["fr"],config:{bonus_items:C,cashstar_items:C,items:C}}',
])
def test_A5_un_format_inconnu_ne_fait_rien_deviner(js):
    """Une liste inventée afficherait des articles qu'aucune carte ne donne."""
    assert cartes.offre_du_script(js) is None


def test_A6_le_script_se_trouve_dans_la_page():
    m = cartes.MOTIF_SCRIPT.search(PAGE)
    assert m and m.group(0).endswith("-GiftCards.js") and "css" not in m.group(0)


# ═══════════════════════════════════════════════════════════════════════════════
#  B — lire la page, sobrement
# ═══════════════════════════════════════════════════════════════════════════════

class _Reponse:
    def __init__(self, status, texte="", donnees=None):
        self.status, self._t, self._d = status, texte, donnees
        self.headers = {}

    async def text(self):
        return self._t

    async def json(self, content_type=None):
        return self._d

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def toile(monkeypatch):
    """La page et le script de Roblox, simulés ; chaque demande est notée."""
    etat = {"page": (200, PAGE), "script": (200, EXTRAIT_REEL), "demandes": [],
            "economie": {}, "pauses": []}

    class _Session:
        def get(self, url, params=None, headers=None):
            etat["demandes"].append(url)
            if url == cartes.PAGE:
                return _Reponse(*etat["page"])
            if url.endswith("-GiftCards.js"):
                return _Reponse(*etat["script"])
            aid = int(url.rstrip("/").split("/")[-2])
            langue = (headers or {}).get("Accept-Language")
            d = etat["economie"].get((aid, langue))
            return _Reponse(200 if d else 404, donnees=d)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    async def _dodo(s):
        etat["pauses"].append(s)

    monkeypatch.setattr(cartes.veille, "_ouvrir", lambda: _Session())
    monkeypatch.setattr(cartes.asyncio, "sleep", _dodo)
    return etat


def _lire(etat_memoire):
    return asyncio.run(cartes.lire_offre(etat_memoire))


def test_B1_le_script_n_est_relu_que_si_son_empreinte_change(toile):
    """« Que ce soit optimisé » : ~170 Ko seulement quand Roblox le change."""
    memoire = {}
    r = _lire(memoire)
    assert r["offre"] == FR and r["script_relu"] is True
    r = _lire(memoire)
    assert r["offre"] == FR and r["script_relu"] is False
    assert [u for u in toile["demandes"] if u.endswith(".js")].__len__() == 1
    toile["page"] = (200, PAGE.replace("91bb7dce", "0000aaaa"))
    r = _lire(memoire)
    assert r["script_relu"] is True


@pytest.mark.parametrize("page", [(403, ""), (202, ""), (429, ""), (200, "<html></html>")])
def test_B2_une_page_refusee_ou_vide_ne_casse_rien(toile, page):
    toile["page"] = page
    r = _lire({})
    assert r["offre"] is None and r["motif"]
    assert not [u for u in toile["demandes"] if u.endswith(".js")]


def test_B3_un_script_illisible_n_empoisonne_pas_la_memoire(toile):
    toile["script"] = (200, "function(){}")
    memoire = {}
    r = _lire(memoire)
    assert r["offre"] is None and "format" in r["motif"]
    assert "script" not in memoire, "on relira le script au prochain passage"


def test_B4_les_fiches_viennent_de_l_economie_en_deux_langues(toile):
    toile["economie"] = {
        (ICARE, None): {"Name": "Icarus Wings", "Description": MAGASIN_SEPT},
        (ICARE, "fr-fr"): {"Name": "Ailes d'Icarus", "Description": "… en septembre 2026."},
        (MEDUSE, None): {"Name": "Medusa Snakes", "Description": "bonus code"},
    }
    annonce = {"asset_id": OCTOBRE, "nom": "Sparkling Robux Shades",
               "description": MAGASIN_OCT}
    arts = asyncio.run(cartes.fiches({"items": [ICARE], "bonus_items": [MEDUSE],
                                      "cashstar_items": []}, en_plus=[annonce]))
    assert [a["asset_id"] for a in arts] == [ICARE, MEDUSE, OCTOBRE]
    assert arts[0]["nom"] == "Icarus Wings" and arts[0]["nom_fr"] == "Ailes d'Icarus"
    assert arts[1]["nom"] == "Medusa Snakes" and "nom_fr" not in arts[1]
    #  L'économie n'a pas répondu pour l'annonce : elle garde ce que le relevé
    #  savait d'elle — nom ET description (donc son mois).
    assert arts[2]["nom"] == "Sparkling Robux Shades"
    assert cartes.mois_annonce(arts[2]) == (2026, 10)


def test_B5_deux_requetes_par_article_pas_une_de_plus(toile):
    """« Tu ne dois pas envoyer un maximum de requêtes » : 3 articles, 6 appels
    à l'économie, zéro lecture de page."""
    asyncio.run(cartes.fiches({"items": [ICARE], "bonus_items": [MEDUSE]},
                              en_plus=[{"asset_id": OCTOBRE, "nom": "x"},
                                       {"asset_id": ICARE, "nom": "doublon"}]))
    assert len(toile["demandes"]) == 6
    assert cartes.PAGE not in toile["demandes"]


def test_B6_sans_nom_de_roblox_l_article_le_dit_et_on_va_doucement(toile):
    """L'économie se tait pour Icare (ni anglais ni français) : `nom_lu` le dit,
    l'appelant attendra plutôt que d'afficher « Article 1396… ». Le français
    seul suffit. Et une requête par seconde au plus : l'éclaireur date ses
    articles sur le même point d'API."""
    toile["economie"] = {(MEDUSE, "fr-fr"): {"Name": "Serpents Méduse",
                                             "Description": "code bonus"}}
    arts = asyncio.run(cartes.fiches(
        {"items": [ICARE], "bonus_items": [MEDUSE]},
        en_plus=[{"asset_id": OCTOBRE, "nom": "Sparkling Robux Shades"}]))
    assert {a["asset_id"]: a["nom_lu"] for a in arts} == {
        ICARE: False, MEDUSE: True, OCTOBRE: True}
    assert cartes.nom_affiche(arts[1]) == "Serpents Méduse"
    assert toile["pauses"] and min(toile["pauses"]) >= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
#  C — dire quelle carte, quel mois, et ce qui est sûr
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("aid,desc,attendu", [
    (MEDUSE, "Redeemed via bonus code included with gift cards",
     "🎟️ **Bonus des cartes achetées sur roblox.com**"),
    (HERMES, AMAZON, "🟠 **Code Amazon**"),
    (HERMES, "codes de carte cadeau numérique Robux sélectionnés sur Amazon.",
     "🟠 **Code Amazon**"),
    (ICARE, MAGASIN_SEPT, "🛒 **Carte en magasin ou numérique**"),
    (ARES, "une carte cadeau Roblox auprès de certains détaillants",
     "🛒 **Carte en magasin**"),
])
def test_C1_chaque_article_dit_quelle_carte_le_donne(aid, desc, attendu):
    assert cartes.source_de({"asset_id": aid, "description": desc}, FR) == attendu


def test_C1bis_un_article_seulement_numerique():
    offre = {"items": [], "bonus_items": [], "cashstar_items": [5]}
    assert "numérique" in cartes.source_de({"asset_id": 5}, offre)


def test_C1ter_sans_description_rien_n_est_deduit():
    """Icare est en magasin ET en carte numérique : sans sa description, le
    dire « numérique » seul serait faux."""
    assert cartes.source_de({"asset_id": ICARE}, FR) == "🎁 **Carte cadeau**"


@pytest.mark.parametrize("arts,attendu", [
    ([{"description": "Get this item … select retailers in September 2026."}],
     "septembre 2026"),
    ([{"description_fr": "… auprès de certains détaillants en octobre 2026."}],
     "octobre 2026"),
    ([{"description": "limited-time exclusive item"}], None),
])
def test_C2_le_mois_vient_de_roblox(arts, attendu):
    assert cartes.mois_de(arts) == attendu


def test_C3_la_signature_ignore_l_ordre_et_voit_le_changement():
    a = cartes.signature(FR)
    b = cartes.signature({"items": list(reversed(FR["items"])),
                          "bonus_items": [MEDUSE], "cashstar_items": []})
    assert a == b
    assert cartes.signature(dict(FR, bonus_items=[1])) != a
    assert cartes.ids_de(FR) == [ICARE, HERMES, ARES, MINOTAURE, MEDUSE]
    assert len(cartes.ids_de({"items": list(range(1, 50))})) == cartes.MAX_ARTICLES


def test_C4_les_mois():
    assert cartes.mois_annonce({"description": MAGASIN_OCT}) == (2026, 10)
    assert cartes.mois_annonce({"description": AMAZON}) is None
    assert cartes.mois_suivant(2026, 9) == (2026, 10)
    assert cartes.mois_suivant(2026, 12) == (2027, 1)
    assert cartes.mois_seul(2026, 10) == "octobre"
    assert cartes.nom_du_mois(2027, 1) == "janvier 2027"


@pytest.mark.parametrize("article,annonce", [
    ({"asset_id": OCTOBRE, "description": MAGASIN_OCT}, (2026, 10)),
    ({"asset_id": 7, "description_fr": "Obtiens-le avec une carte cadeau Roblox "
                                        "en novembre 2026."}, (2026, 11)),
    #  Amazon et le code bonus n'écrivent pas leur mois : jamais annoncés.
    ({"asset_id": HERMES, "description": AMAZON}, None),
    #  Un mois SANS carte cadeau n'est pas une annonce de carte.
    ({"asset_id": 8, "description": "Available in October 2026 during the event."},
     None),
    ({"asset_id": 0, "description": MAGASIN_OCT}, None),
    ({"asset_id": 9, "description": None}, None),
])
def test_C5_on_n_annonce_que_ce_que_roblox_ecrit(article, annonce):
    """« Il faut que tu sois sûr de toi » : une carte cadeau ET un mois, dans
    la description de Roblox — sinon rien."""
    trouves = cartes.annonces_dans([article])
    assert ([(a["annee"], a["mois"]) for a in trouves] or [None]) == [annonce]


def test_C6_la_suite_porte_la_presentation_et_le_mois_suivant(monkeypatch):
    vide = cartes.signature_suite([])
    assert vide == f"v{cartes.VERSION_FICHE}:" and vide != "", \
        "la fiche du matin (suite « ») doit passer au format court"
    a = cartes.signature_suite([{"asset_id": 3}, {"asset_id": 1}])
    assert a == cartes.signature_suite([{"asset_id": 1}, {"asset_id": 3}])
    assert a != vide
    monkeypatch.setattr(cartes, "VERSION_FICHE", cartes.VERSION_FICHE + 1)
    assert cartes.signature_suite([]) != vide


@pytest.mark.parametrize("article,attendu", [
    ({"nom": "Icarus Wings", "nom_fr": "Ailes d'Icare"}, "Ailes d'Icare"),
    ({"nom": "Icarus Wings"}, "Icarus Wings"),
    ({"nom": "[LIMITED] Cool_Hat *2*"}, "LIMITED CoolHat 2"),
    ({"nom": "", "asset_id": 42}, "Article 42"),
    ({"nom": "A" * 80}, "A" * 47 + "…"),
])
def test_C7_le_nom_montre_ne_casse_pas_la_ligne(article, attendu):
    assert cartes.nom_affiche(article) == attendu


def test_C8_regroupe_par_carte_dans_l_ordre_de_la_page():
    arts = [{"asset_id": ICARE, "description": MAGASIN_SEPT},
            {"asset_id": HERMES, "description": AMAZON},
            {"asset_id": MEDUSE, "description": ""},
            {"asset_id": ARES, "description": AMAZON}]
    g = cartes.groupes(arts, FR)
    assert [e for e, _ in g] == ["🛒 **Carte en magasin ou numérique**",
                                 "🟠 **Code Amazon**",
                                 "🎟️ **Bonus des cartes achetées sur roblox.com**"]
    assert [a["asset_id"] for a in g[1][1]] == [HERMES, ARES]


# ═══════════════════════════════════════════════════════════════════════════════
#  M — la mémoire : annonces et fiche affichée (vraie base SQLite)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def base(tmp_path):
    chemin = tmp_path / "cartes.db"
    cfg = {}
    journal = []

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return cfg

    async def _db_set(_g, k, v):
        cfg[k] = v
        return True

    cartes.veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                        log=lambda *a, **k: journal.append(" ".join(map(str, a))))
    asyncio.run(cartes.veille.init_db())
    return {"cfg": cfg, "journal": journal}


RELEVE = [
    {"asset_id": OCTOBRE, "nom": "Sparkling Robux Shades", "description": MAGASIN_OCT},
    {"asset_id": ICARE, "nom": "Icarus Wings", "description": MAGASIN_SEPT},
    {"asset_id": HERMES, "nom": "Cap of Hermes", "description": AMAZON},
    {"asset_id": 5, "nom": "Pumpkin Hat",
     "description": "Available in October 2026 during the event."},
    {"asset_id": 6, "nom": "Sans description", "description": None},
]


def test_M1_les_annonces_du_releve_donnent_le_mois_et_la_suite(base):
    assert asyncio.run(cartes.noter_annonces(RELEVE)) == 2
    suite = asyncio.run(cartes.annonces_du_mois(2026, 10))
    assert [(p["asset_id"], p["nom"]) for p in suite] == [
        (OCTOBRE, "Sparkling Robux Shades")]
    assert asyncio.run(cartes.mois_de_l_offre(FR)) == (2026, 9)
    assert asyncio.run(cartes.annonces_du_mois(2026, 11)) == []


def test_M2_une_annonce_revue_est_mise_a_jour_pas_doublee(base):
    asyncio.run(cartes.noter_annonces(RELEVE))
    corrige = dict(RELEVE[0], description=MAGASIN_OCT.replace("October", "November"))
    asyncio.run(cartes.noter_annonces([corrige]))
    assert asyncio.run(cartes.annonces_du_mois(2026, 10)) == []
    assert [p["asset_id"] for p in asyncio.run(cartes.annonces_du_mois(2026, 11))] \
        == [OCTOBRE]


def test_M3_le_mois_de_l_offre(base):
    assert asyncio.run(cartes.mois_de_l_offre(FR)) is None, "rien de mémorisé"
    asyncio.run(cartes.noter_annonces(RELEVE))
    melange = {"items": [OCTOBRE, ICARE]}
    assert asyncio.run(cartes.mois_de_l_offre(melange)) == (2026, 10), \
        "la page déjà passée au mois suivant : le plus récent gagne"
    assert asyncio.run(cartes.mois_de_l_offre({"items": [HERMES]})) is None


def test_M4_ce_que_le_serveur_montre(base):
    assert asyncio.run(cartes.etat_affiche(1)) == {"signature": "", "suite": "",
                                                   "message": 0}
    asyncio.run(cartes.noter_affichee(1, "a,b", "v2:9", 555))
    assert asyncio.run(cartes.etat_affiche(1)) == {"signature": "a,b",
                                                   "suite": "v2:9", "message": 555}
    asyncio.run(cartes.noter_affichee(1, "c"))
    assert asyncio.run(cartes.etat_affiche(1))["suite"] == "v2:9"
    assert asyncio.run(cartes.etat_affiche(1))["message"] == 555
    #  Une fiche neuve partie sans identifiant : l'ancien est EFFACÉ, sinon on
    #  modifierait la fiche du mois d'avant.
    asyncio.run(cartes.noter_affichee(1, "d", "v2:", 0))
    assert asyncio.run(cartes.etat_affiche(1))["message"] == 0


def test_M5_une_base_en_panne_ne_casse_pas_la_veille(base):
    @contextlib.asynccontextmanager
    async def _panne():
        raise RuntimeError("disque plein")
        yield  # pragma: no cover

    cartes.veille.setup(get_db=_panne, cfg=None, db_set=None,
                        log=lambda *a, **k: base["journal"].append(" ".join(map(str, a))))
    assert asyncio.run(cartes.noter_annonces(RELEVE)) == 0
    assert asyncio.run(cartes.annonces_du_mois(2026, 10)) == []
    assert asyncio.run(cartes.mois_de_l_offre(FR)) is None
    assert any("noter_annonces" in l for l in base["journal"])


# ═══════════════════════════════════════════════════════════════════════════════
#  D — la fiche : courte, regroupée, compréhensible
# ═══════════════════════════════════════════════════════════════════════════════

def _textes(n, out=None) -> list:
    out = [] if out is None else out
    if isinstance(n, dict):
        if n.get("type") == 10:
            out.append(n["content"])
        for v in n.values():
            _textes(v, out)
    elif isinstance(n, list):
        for v in n:
            _textes(v, out)
    return out


def _texte(vue) -> str:
    return "\n".join(_textes(vue.to_components()))


def _composants(n) -> int:
    if isinstance(n, dict):
        return (1 if "type" in n else 0) + sum(_composants(v) for v in n.values())
    if isinstance(n, list):
        return sum(_composants(v) for v in n)
    return 0


def _types(n, t) -> int:
    if isinstance(n, dict):
        return (1 if n.get("type") == t else 0) + sum(_types(v, t) for v in n.values())
    if isinstance(n, list):
        return sum(_types(v, t) for v in n)
    return 0


def _articles():
    return [
        {"asset_id": ICARE, "item_type": "Asset", "nom": "Icarus Wings",
         "nom_fr": "Ailes d'Icarus", "description": MAGASIN_SEPT},
        {"asset_id": HERMES, "item_type": "Asset", "nom": "Cap of Hermes",
         "description": AMAZON},
        {"asset_id": ARES, "item_type": "Asset", "nom": "Helm of Ares",
         "description": AMAZON},
        {"asset_id": MINOTAURE, "item_type": "Asset", "nom": "Minotaur Head",
         "description": AMAZON},
        {"asset_id": MEDUSE, "item_type": "Asset", "nom": "Medusa Snakes",
         "description": "Redeemed via bonus code included with gift cards"},
    ]


def _octobre():
    return [{"asset_id": OCTOBRE, "item_type": "Asset",
             "nom": "Sparkling Robux Shades", "description": MAGASIN_OCT}]


def _lien(aid) -> str:
    return f"(https://www.roblox.com/catalog/{aid}/)"


@pytest.fixture
def panneau():
    rp.setup(db_set=None, webhook_send=None, webhook_edit=None, log=lambda *a: None)


def test_D1_une_ligne_par_carte_les_noms_en_liens(panneau):
    """Le cas réel du 29/09 : cinq articles, TROIS lignes."""
    vue = rp.construire_cartes(_articles(), FR, {ICARE: IMG}, ping_cle="nouveaux")
    t = _texte(vue)
    assert "### 🎁 CARTES CADEAUX ROBLOX · septembre 2026" in t
    assert ("🛒 **Carte en magasin ou numérique** · [Ailes d'Icarus]"
            + _lien(ICARE)) in t
    assert ("🟠 **Code Amazon** · [Cap of Hermes]" + _lien(HERMES)
            + " · [Helm of Ares]" + _lien(ARES)
            + " · [Minotaur Head]" + _lien(MINOTAURE)) in t
    assert ("🎟️ **Bonus des cartes achetées sur roblox.com** · [Medusa Snakes]"
            + _lien(MEDUSE)) in t
    d = vue.to_components()
    assert _types(d, 11) == 1, "UNE image pour toute la fiche"
    assert _types(d, 1) == 1, "UNE rangée de boutons"
    assert _composants(d) <= 12
    s = str(d)
    assert cartes.PAGE_ECHANGE in s and cartes.PAGE in s and "Me prévenir" in s
    assert "🔜" not in t, "pas de mois suivant sans annonce"


def test_D2_sans_image_ni_mois_la_fiche_part_quand_meme(panneau):
    arts = [dict(a, description="") for a in _articles()]
    vue = rp.construire_cartes(arts, FR, {})
    t = _texte(vue)
    assert "CARTES CADEAUX ROBLOX · en ce moment" in t and "Medusa Snakes" in t
    assert _types(vue.to_components(), 11) == 0


def test_D3_une_longue_liste_reste_courte_et_le_dit(panneau):
    arts = [{"asset_id": 10 ** 10 + k, "item_type": "Asset", "nom": f"A{k}",
             "nom_fr": f"B{k}", "description": "x"} for k in range(12)]
    offre = {"items": [a["asset_id"] for a in arts]}
    vue = rp.construire_cartes(arts, offre, {a["asset_id"]: IMG for a in arts},
                               ping_cle="nouveaux",
                               ping_role=type("R", (), {"id": 5, "mention": "<@&5>"})())
    d = vue.to_components()
    t = _texte(vue)
    assert "… et 2 autre(s) sur la page officielle" in t
    assert t.count("https://www.roblox.com/catalog/") == cartes.MAX_ARTICLES
    assert "Me prévenir" in str(d), "le bouton d'abonnement n'est jamais sacrifié"
    assert "<@&5>" in t
    assert _composants(d) <= 40 and _types(d, 11) == 1


def test_D4_le_mois_suivant_tient_en_une_ligne(panneau):
    vue = rp.construire_cartes(_articles(), FR, {ICARE: IMG}, prochains=_octobre(),
                               mois="septembre 2026", mois_prochain="octobre")
    t = _texte(vue)
    assert ("🔜 **En octobre** · 🛒 Carte en magasin · [Sparkling Robux Shades]"
            + _lien(OCTOBRE)) in t
    assert "annoncé par Roblox" in t
    assert t.count("\n🔜") == 1


def test_D5_le_pire_cas_tient_dans_un_message(panneau):
    """Discord : 4 000 caractères et 40 composants. Noms immenses, liste
    pleine, trop d'annonces : la fiche part quand même."""
    arts = [{"asset_id": 10 ** 14 + k, "item_type": "Asset", "nom": "N" * 200,
             "nom_fr": "F" * 200, "description": AMAZON if k % 2 else MAGASIN_SEPT}
            for k in range(cartes.MAX_ARTICLES + 5)]
    suite = [{"asset_id": 10 ** 13 + k, "item_type": "Asset", "nom": "S" * 200,
              "description": MAGASIN_OCT} for k in range(9)]
    vue = rp.construire_cartes(arts, {"items": [a["asset_id"] for a in arts]},
                               {a["asset_id"]: IMG for a in arts}, prochains=suite,
                               mois="septembre 2026", mois_prochain="octobre",
                               ping_cle="nouveaux",
                               ping_role=type("R", (), {"id": 5, "mention": "<@&5>"})())
    d = vue.to_components()
    assert sum(len(x) for x in _textes(d)) < 4000
    assert _composants(d) <= 40
    assert _texte(vue).count("https://www.roblox.com/catalog/") \
        == cartes.MAX_ARTICLES + cartes.MAX_PROCHAINS


def test_D6_un_nom_a_crochets_ne_casse_pas_le_lien(panneau):
    arts = [{"asset_id": HERMES, "item_type": "Asset",
             "nom": "[LIMITED] Cap_of *Hermes*", "description": AMAZON}]
    t = _texte(rp.construire_cartes(arts, FR, {}))
    assert "[LIMITED Capof Hermes]" + _lien(HERMES) in t
    assert re.findall(r"\[([^\[\]]+)\]\(https://www\.roblox\.com/catalog/\d+/\)", t) \
        == ["LIMITED Capof Hermes"]


# ═══════════════════════════════════════════════════════════════════════════════
#  F — publier, modifier sur place, retrouver la fiche du matin
# ═══════════════════════════════════════════════════════════════════════════════

class _Role:
    id = 5
    mention = "<@&5>"


@pytest.fixture
def roles(monkeypatch):
    appels = []

    async def _role_de(guild, cle, creer=True):
        appels.append({"cle": cle, "creer": creer})
        return _Role()

    monkeypatch.setattr(rp.pings, "role_de", _role_de)
    return appels


def test_F1_modifier_passe_par_le_webhook_qui_a_poste(roles):
    appels = []

    async def _edit(channel, platform, message_id, embed=None, content=None, view=None):
        appels.append((platform, message_id, view))
        return object()

    rp.setup(db_set=None, webhook_send=None, webhook_edit=_edit, log=lambda *a: None)
    ok = asyncio.run(rp.editer_cartes(object(), object(), 555, _articles(), FR, {},
                                      prochains=_octobre(), mois_prochain="octobre"))
    assert ok is True
    (plateforme, mid, vue), = appels
    assert plateforme == rp.PLATEFORME["nouveautes"] and mid == 555
    assert isinstance(vue, rp.LayoutView) and "🔜 **En octobre**" in _texte(vue)
    assert roles == [{"cle": "nouveaux", "creer": False}], \
        "on ne crée jamais un rôle pour une modification"


def test_F2_une_modification_refusee_le_dit(roles):
    journal = []

    async def _rien(*a, **k):
        return None

    async def _boum(*a, **k):
        raise RuntimeError("403")

    for fn, attendu in ((_rien, "introuvable"), (_boum, "RuntimeError")):
        rp.setup(db_set=None, webhook_send=None, webhook_edit=fn, log=journal.append)
        assert asyncio.run(rp.editer_cartes(object(), object(), 555, _articles(),
                                            FR)) is False
        assert attendu in journal[-1]
    rp.setup(db_set=None, webhook_send=None, webhook_edit=None, log=journal.append)
    assert asyncio.run(rp.editer_cartes(object(), object(), 555, _articles(), FR)) is False
    assert asyncio.run(rp.editer_cartes(object(), object(), 0, _articles(), FR)) is False


class _Msg:
    def __init__(self, mid, composants, webhook_id=None, auteur=1):
        self.id, self.components, self.webhook_id = mid, composants, webhook_id
        self.author = type("A", (), {"id": auteur})()


class _SalonHisto:
    name, id = "roblox", 99

    def __init__(self, messages, erreur=None):
        self._m, self._e, self.limites = messages, erreur, []
        self.guild = type("G", (), {"me": type("M", (), {"id": 1000})()})()

    def history(self, limit=100):
        self.limites.append(limit)

        async def _gen():
            if self._e:
                raise self._e
            for m in self._m[:limit]:
                yield m
        return _gen()


def _vrais_composants(vue):
    """Ce que discord.py rend dans `Message.components` pour ce message."""
    return [discord.components._component_factory(c) for c in vue.to_components()]


def test_F3_la_fiche_du_matin_se_retrouve_dans_l_historique(panneau):
    carte = _vrais_composants(rp.construire_cartes(_articles(), FR, {ICARE: IMG}))
    autre = _vrais_composants(rp.construire_fiche(
        {"asset_id": HERMES, "nom": "Cap of Hermes", "item_type": "Asset"}, "nouveautes"))
    salon = _SalonHisto([
        #  Un membre qui recopie le titre : jamais pris pour la fiche.
        _Msg(1, [type("T", (), {"content": "CARTES CADEAUX ROBLOX lol"})()], auteur=7),
        _Msg(2, autre, webhook_id=31),
        _Msg(3, carte, webhook_id=31),
        _Msg(4, carte, webhook_id=31),
    ])
    assert asyncio.run(rp.retrouver_carte(salon)) == 3, "la plus récente"
    assert salon.limites == [50]
    #  Publiée par le bot lui-même (repli sans webhook) : trouvée aussi.
    salon = _SalonHisto([_Msg(8, carte, auteur=1000)])
    assert asyncio.run(rp.retrouver_carte(salon)) == 8
    assert asyncio.run(rp.retrouver_carte(_SalonHisto([_Msg(2, autre, 31)]))) is None


def test_F4_sans_droit_de_lire_l_historique(panneau):
    journal = []
    rp.setup(db_set=None, log=journal.append)
    salon = _SalonHisto([], erreur=discord.Forbidden(
        type("R", (), {"status": 403, "reason": "Forbidden"})(), "Missing Access"))
    assert asyncio.run(rp.retrouver_carte(salon)) is None
    assert "Forbidden" in journal[-1]


def test_F5_une_fiche_reposee_ne_reveille_personne(roles):
    envois = []

    async def _send(channel, platform, view=None, allowed_mentions=None, **k):
        envois.append((view, allowed_mentions))
        return type("M", (), {"id": 777})()

    rp.setup(db_set=None, webhook_send=_send, log=lambda *a: None)
    trace = {}
    assert asyncio.run(rp.publier_cartes(object(), object(), _articles(), FR, {},
                                         trace=trace, ping=False)) is True
    vue, mentions = envois[-1]
    assert roles == [] and "<@&" not in _texte(vue) and mentions.roles is False
    assert trace["message_id"] == 777
    assert "Me prévenir" in str(vue.to_components()), "le bouton reste"
    assert asyncio.run(rp.publier_cartes(object(), object(), _articles(), FR, {},
                                         ping=True)) is True
    vue, mentions = envois[-1]
    assert "<@&5>" in _texte(vue) and [r.id for r in mentions.roles] == [5]


def test_F6_le_repli_sans_webhook_note_aussi_le_message(panneau):
    class _Salon:
        name, id = "roblox", 99

        async def send(self, view=None, allowed_mentions=None):
            return type("M", (), {"id": 888})()

    async def _casse(*a, **k):
        raise RuntimeError("webhook cassé")

    rp.setup(db_set=None, webhook_send=_casse, log=lambda *a: None)
    trace = {}
    assert asyncio.run(rp.publier_cartes(object(), _Salon(), _articles(), FR, {},
                                         trace=trace, ping=False)) is True
    assert trace["message_id"] == 888


# ═══════════════════════════════════════════════════════════════════════════════
#  E — le branchement : une lecture toutes les 3 h, une fiche par liste,
#      complétée sur place
# ═══════════════════════════════════════════════════════════════════════════════

def _fonction(nom: str) -> str:
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


class _Guilde:
    def __init__(self, gid, salon=True):
        self.id = gid
        self._salon = type("S", (), {"name": "roblox", "id": 99})() if salon else None

    def get_channel(self, _cid):
        return self._salon


def _comme(vraie, *a, **k):
    """Le faux refuse ce que le vrai refuserait (piège n° 6)."""
    b = inspect.signature(vraie).bind(*a, **k)
    b.apply_defaults()
    return b.arguments


ANNONCE_OCT = {"asset_id": OCTOBRE, "nom": "Sparkling Robux Shades",
               "description": MAGASIN_OCT, "item_type": "Asset"}


def _banc(offre=FR, publie=True, simulation=False, motif=None, annonces=None,
          mois_offre=(2026, 9), edite=True, retrouve=4242, fiches_ok=True,
          sans_nom=False):
    etat = {"affichee": {}, "suite": {}, "message": {}, "publies": [],
            "editees": [], "retrouvees": 0, "journal": [], "lectures": 0,
            "notees": [], "fiches": 0, "vignettes": [],
            "annonces": ({(2026, 10): [ANNONCE_OCT]} if annonces is None else annonces),
            "mois_offre": mois_offre}

    class FauxCartes:
        HEURES_ENTRE_LECTURES = cartes.HEURES_ENTRE_LECTURES
        MAX_PROCHAINS = cartes.MAX_PROCHAINS
        ESSAIS_NOMS = cartes.ESSAIS_NOMS
        signature = staticmethod(cartes.signature)
        ids_de = staticmethod(cartes.ids_de)
        mois_de = staticmethod(cartes.mois_de)
        mois_suivant = staticmethod(cartes.mois_suivant)
        mois_seul = staticmethod(cartes.mois_seul)
        nom_du_mois = staticmethod(cartes.nom_du_mois)
        signature_suite = staticmethod(cartes.signature_suite)

        @staticmethod
        async def noter_annonces(*a, **k):
            vus = _comme(cartes.noter_annonces, *a, **k)["articles"]
            etat["notees"].append(len(list(vus or [])))
            return len(cartes.annonces_dans(vus))

        @staticmethod
        async def lire_offre(*a, **k):
            _comme(cartes.lire_offre, *a, **k)
            etat["lectures"] += 1
            return {"offre": etat.get("offre", offre), "motif": motif}

        @staticmethod
        async def mois_de_l_offre(*a, **k):
            _comme(cartes.mois_de_l_offre, *a, **k)
            return etat["mois_offre"]

        @staticmethod
        async def annonces_du_mois(*a, **k):
            x = _comme(cartes.annonces_du_mois, *a, **k)
            return [dict(p) for p in etat["annonces"].get((x["annee"], x["mois"]), [])]

        @staticmethod
        async def etat_affiche(*a, **k):
            gid = _comme(cartes.etat_affiche, *a, **k)["guild_id"]
            return {"signature": etat["affichee"].get(gid, ""),
                    "suite": etat["suite"].get(gid, ""),
                    "message": etat["message"].get(gid, 0)}

        @staticmethod
        async def noter_affichee(*a, **k):
            x = _comme(cartes.noter_affichee, *a, **k)
            etat["affichee"][x["guild_id"]] = x["sig"]
            if x["suite"] is not None:
                etat["suite"][x["guild_id"]] = x["suite"]
            if x["message_id"] is not None:
                etat["message"][x["guild_id"]] = int(x["message_id"] or 0)

        @staticmethod
        async def fiches(*a, **k):
            x = _comme(cartes.fiches, *a, **k)
            etat["fiches"] += 1
            if not fiches_ok:
                return []
            ids = cartes.ids_de(x["offre"])
            #  Comme le vrai (piège n° 6 — ce faux-là ne dédoublonnait pas, et
            #  une mutation a survécu) : une annonce déjà dans la liste n'est
            #  pas redemandée.
            arts = ([{"asset_id": i, "nom": str(i), "description": "", "nom_lu": True}
                     for i in ids]
                    + [dict(p, nom_lu=True) for p in x["en_plus"]
                       if p["asset_id"] not in ids])
            if sans_nom:
                arts[0]["nom_lu"] = False
            return arts

    class FauxVeille:
        @staticmethod
        async def config(_g):
            return {"roblox_veille_simulation": simulation}

        @staticmethod
        def salon_du_flux(_c, flux):
            return 99 if flux == "nouveautes" else 0

        @staticmethod
        async def vignettes(arts):
            etat["vignettes"].append(len(arts))
            return {}

    class FauxUI:
        @staticmethod
        async def publier_cartes(*a, **k):
            x = _comme(rp.publier_cartes, *a, **k)
            etat["publies"].append({
                "g": x["guild"].id, "n": len(x["articles"]), "ping": x["ping"],
                "prochains": [p["asset_id"] for p in x["prochains"]],
                "mois": x["mois"], "mois_prochain": x["mois_prochain"]})
            if publie and x["trace"] is not None:
                x["trace"]["message_id"] = 777
            return publie

        @staticmethod
        async def editer_cartes(*a, **k):
            x = _comme(rp.editer_cartes, *a, **k)
            etat["editees"].append({
                "g": x["guild"].id, "mid": x["message_id"],
                "prochains": [p["asset_id"] for p in x["prochains"]]})
            return edite

        @staticmethod
        async def retrouver_carte(*a, **k):
            _comme(rp.retrouver_carte, *a, **k)
            etat["retrouvees"] += 1
            return retrouve

    ns = {"roblox_cartes_module": FauxCartes, "roblox_module": FauxVeille,
          "roblox_ui": FauxUI, "_CARTES": {"script": None, "offre": None,
                                           "lu_le": None, "dit": None},
          "datetime": datetime, "timezone": timezone,
          "print": lambda *a, **k: etat["journal"].append(" ".join(map(str, a)))}
    exec(_fonction("_cartes_cadeaux"), ns)          # noqa: S102 — code du dépôt
    return ns, etat


def _tick(ns, guildes, vus=()):
    return asyncio.run(ns["_cartes_cadeaux"](guildes, vus))


def _plus_tard(ns, heures=4):
    ns["_CARTES"]["lu_le"] = datetime.now(timezone.utc) - timedelta(hours=heures)


SUITE_OCT = cartes.signature_suite([{"asset_id": OCTOBRE}])


def test_E0_le_bot_ne_lit_que_ce_que_les_vrais_modules_ont():
    """Piège n° 6 : un faux qui n'a pas ce que le vrai a (ou l'inverse) cache
    un NameError — c'est déjà arrivé à l'éclaireur."""
    arbre = ast.parse(_fonction("_cartes_cadeaux"))
    lus = {(n.value.id, n.attr) for n in ast.walk(arbre)
           if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    ns, _ = _banc()
    vrais = {"C": cartes, "roblox_cartes_module": cartes, "roblox_ui": rp,
             "roblox_module": cartes.veille}
    faux = {"C": ns["roblox_cartes_module"], "roblox_cartes_module":
            ns["roblox_cartes_module"], "roblox_ui": ns["roblox_ui"],
            "roblox_module": ns["roblox_module"]}
    vus = [(nom, attr) for nom, attr in lus if nom in vrais]
    assert len(vus) >= 15
    for nom, attr in vus:
        assert hasattr(vrais[nom], attr), f"{nom}.{attr} n'existe pas"
        assert hasattr(faux[nom], attr), f"le banc n'a pas {nom}.{attr}"


def test_E1_la_liste_s_affiche_une_fois_avec_le_mois_suivant():
    ns, etat = _banc()
    r = _tick(ns, [_Guilde(1)])
    assert r["publies"] == 1 and etat["editees"] == []
    (p,) = etat["publies"]
    assert p == {"g": 1, "n": 5, "ping": True, "prochains": [OCTOBRE],
                 "mois": "septembre 2026", "mois_prochain": "octobre"}
    assert etat["affichee"][1] == cartes.signature(FR)
    assert etat["suite"][1] == SUITE_OCT and etat["message"][1] == 777
    assert etat["vignettes"] == [1], "une seule image sur la fiche, une seule demandée"
    dit = list(etat["journal"])
    _plus_tard(ns)
    r = _tick(ns, [_Guilde(1)])
    assert r["lu"] is True and r["publies"] == 0 and len(etat["publies"]) == 1
    assert etat["fiches"] == 1 and etat["editees"] == []
    assert etat["journal"] == dit, "une ligne par CHANGEMENT d'état, pas toutes les 3 h"


def test_E2_la_page_au_plus_toutes_les_trois_heures_les_annonces_a_chaque_passage():
    ns, etat = _banc()
    _tick(ns, [_Guilde(1)], vus=[ANNONCE_OCT])
    r = _tick(ns, [_Guilde(1)], vus=[ANNONCE_OCT, {"asset_id": 3}])
    assert r["lu"] is False and etat["lectures"] == 1
    assert etat["notees"] == [1, 2], "le relevé nourrit les annonces à chaque passage"
    assert r["annonces"] == 1


def test_E3_une_nouvelle_liste_fait_une_nouvelle_fiche_avec_ping():
    ns, etat = _banc()
    _tick(ns, [_Guilde(1)])
    etat["offre"] = dict(FR, bonus_items=[106083349330631])
    _plus_tard(ns)
    _tick(ns, [_Guilde(1)])
    assert len(etat["publies"]) == 2 and etat["publies"][1]["ping"] is True
    assert etat["editees"] == [] and etat["retrouvees"] == 0


def test_E4_un_envoi_rate_n_est_pas_note_affiche():
    ns, etat = _banc(publie=False)
    _tick(ns, [_Guilde(1)])
    assert etat["affichee"] == {}, "sinon la liste ne serait jamais réessayée"


def test_E5_la_simulation_ne_publie_rien_et_ne_note_rien():
    ns, etat = _banc(simulation=True)
    _tick(ns, [_Guilde(1)])
    assert etat["publies"] == [] and etat["affichee"] == {} and etat["editees"] == []
    assert any("SIMULATION" in l for l in etat["journal"])


def test_E6_une_page_illisible_le_dit_une_fois():
    ns, etat = _banc(offre=None, motif="HTTP 403")
    _tick(ns, [_Guilde(1)])
    _plus_tard(ns)
    _tick(ns, [_Guilde(1)])
    assert etat["publies"] == []
    assert sum("illisible" in l for l in etat["journal"]) == 1


def test_E7_sans_salon_rien_ne_part():
    ns, etat = _banc()
    _tick(ns, [_Guilde(1, salon=False)])
    assert etat["publies"] == [] and etat["affichee"] == {} and etat["fiches"] == 0


def test_E8_le_releve_de_30_min_nourrit_les_cartes_apres_le_catalogue():
    boucle = _fonction("veille_roblox_task")
    i_rendu = boucle.index("roblox_module.catalogue_occupe(False)")
    i_cartes = boucle.index("await _cartes_cadeaux(guildes_items, _vus_cartes)")
    assert i_rendu < i_cartes, "les cartes ne doivent pas tenir le chemin du catalogue"
    i_def = boucle.index("_vus_cartes = list(rel.get('articles') or [])")
    i_hv = boucle.index("_vus_cartes += list(relhv.get('articles') or [])")
    assert i_def < i_hv < i_cartes, \
        "les articles des cartes du mois suivant vivent dans le relevé HORS VENTE"


def test_E9_la_fiche_du_matin_est_retrouvee_et_completee_sur_place():
    """État réel du 29/09 : liste notée, suite jamais notée, identifiant
    inconnu. Pas de message de plus, pas de ping de plus."""
    ns, etat = _banc()
    etat["affichee"][1] = cartes.signature(FR)
    r = _tick(ns, [_Guilde(1)])
    assert etat["retrouvees"] == 1 and etat["publies"] == []
    assert etat["editees"] == [{"g": 1, "mid": 4242, "prochains": [OCTOBRE]}]
    assert r["completees"] == 1
    assert etat["suite"][1] == SUITE_OCT and etat["message"][1] == 4242
    assert any("complétée(s) sur place" in l for l in etat["journal"])
    _plus_tard(ns)
    _tick(ns, [_Guilde(1)])
    assert len(etat["editees"]) == 1 and etat["retrouvees"] == 1, "une seule fois"


def test_E9bis_meme_sans_mois_suivant_la_fiche_du_matin_passe_au_format_court():
    ns, etat = _banc(annonces={})
    etat["affichee"][1] = cartes.signature(FR)
    _tick(ns, [_Guilde(1)])
    assert etat["editees"] == [{"g": 1, "mid": 4242, "prochains": []}]
    assert etat["suite"][1] == cartes.signature_suite([])


def test_E10_une_annonce_nouvelle_modifie_la_fiche_notee():
    ns, etat = _banc(annonces={})
    _tick(ns, [_Guilde(1)])
    assert etat["message"][1] == 777 and etat["suite"][1] == cartes.signature_suite([])
    etat["annonces"] = {(2026, 10): [ANNONCE_OCT]}
    _plus_tard(ns)
    _tick(ns, [_Guilde(1)])
    assert etat["retrouvees"] == 0, "identifiant connu : pas d'historique lu"
    assert etat["editees"] == [{"g": 1, "mid": 777, "prochains": [OCTOBRE]}]
    assert len(etat["publies"]) == 1


@pytest.mark.parametrize("edite,retrouve,editions", [(False, 4242, 1), (True, None, 0)])
def test_E11_introuvable_ou_refusee_elle_est_reposee_sans_ping(edite, retrouve, editions):
    ns, etat = _banc(edite=edite, retrouve=retrouve)
    etat["affichee"][1] = cartes.signature(FR)
    r = _tick(ns, [_Guilde(1)])
    assert len(etat["editees"]) == editions
    (p,) = etat["publies"]
    assert p["ping"] is False and p["prochains"] == [OCTOBRE]
    assert r["reposees"] == 1 and r["publies"] == 0
    assert etat["message"][1] == 777 and etat["suite"][1] == SUITE_OCT
    assert any("reposée(s) sans ping" in l for l in etat["journal"])


def test_E12_sans_mois_ecrit_par_roblox_pas_de_mois_suivant():
    """« Il faut que tu sois sûr de toi » : jamais l'horloge. Des annonces
    existent pour octobre ET novembre ; sans mois de l'offre, aucune."""
    ns, etat = _banc(mois_offre=None,
                     annonces={(2026, 10): [ANNONCE_OCT],
                               (2026, 11): [dict(ANNONCE_OCT, asset_id=9)]})
    _tick(ns, [_Guilde(1)])
    assert etat["publies"][0]["prochains"] == []
    assert etat["suite"][1] == cartes.signature_suite([])


def test_E13_une_annonce_deja_dans_la_liste_n_est_pas_repetee():
    """La page déjà passée au mois suivant : son article est dans la liste ET
    annoncé. Il ne compte qu'une fois — sinon la fiche attendrait un nom qui
    ne viendra jamais (« noms incomplets » à chaque lecture)."""
    ns, etat = _banc(annonces={(2026, 10): [dict(ANNONCE_OCT, asset_id=ICARE)]})
    r = _tick(ns, [_Guilde(1)])
    assert r["publies"] == 1 and etat["publies"][0]["prochains"] == []
    assert etat["suite"][1] == cartes.signature_suite([])
    assert not any("annoncé(s)" in l for l in etat["journal"])


def test_E14_des_noms_incomplets_ne_partent_pas():
    ns, etat = _banc(fiches_ok=False)
    r = _tick(ns, [_Guilde(1)])
    assert etat["publies"] == [] and etat["affichee"] == {}
    assert r["motif"] == "noms incomplets"
    assert any("noms incomplets" in l for l in etat["journal"])


def test_E15_un_envoi_rate_ne_redemande_pas_les_noms():
    """Trois heures plus tard, on réessaie l'envoi — pas les douze appels à
    l'économie."""
    ns, etat = _banc(publie=False)
    _tick(ns, [_Guilde(1)])
    _plus_tard(ns)
    _tick(ns, [_Guilde(1)])
    assert len(etat["publies"]) == 2 and etat["fiches"] == 1


def test_E16_un_nom_introuvable_attend_puis_part_avec_son_lien():
    """« Article 1396… » ne s'affiche pas : on attend la lecture suivante, au
    plus `ESSAIS_NOMS` fois ; ensuite la fiche part — le lien, lui, est sûr."""
    ns, etat = _banc(sans_nom=True)
    for _ in range(cartes.ESSAIS_NOMS - 1):
        r = _tick(ns, [_Guilde(1)])
        assert r["motif"] == "noms incomplets" and etat["publies"] == []
        assert etat["affichee"] == {}
        _plus_tard(ns)
    r = _tick(ns, [_Guilde(1)])
    assert r["publies"] == 1 and etat["fiches"] == cartes.ESSAIS_NOMS
    assert any("toujours indisponible" in l for l in etat["journal"])
