"""Les cartes cadeaux Roblox — ce qu'une carte donne AUJOURD'HUI (29/09/2026).

DEMANDE DU PROPRIÉTAIRE
    « On achète des cartes cadeaux à chaque fois, ça change les items.
      J'aimerais aussi que tu affiches les items disponibles dans les cartes
      cadeaux. Que ce soit optimisé. »

MESURÉ LE 29/09 SUR LA PAGE OFFICIELLE (roblox.com/giftcards-fr) : la liste vit
dans son script `…-GiftCards.js`, pays par pays, en hexadécimal. Pour la
France : Icarus Wings, Cap of Hermes, Helm of Ares, Minotaur Head, Medusa
Snakes. `EXTRAIT_REEL` est le morceau de ce script, recopié tel quel.

Ces tests n'appellent jamais le réseau.
"""
from __future__ import annotations

import ast
import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
FR = {"items": [ICARE, HERMES, ARES, MINOTAURE], "bonus_items": [MEDUSE],
      "cashstar_items": [ICARE]}
PAGE = ('<link rel="stylesheet" href="https://css.rbxcdn.com/7e34-GiftCards.css" />'
        '<script src="https://js.rbxcdn.com/91bb7dcef33281e011f195624d233b3b813edc'
        '589de013fcc2d9851ccfa73b3b-GiftCards.js"></script>')


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
            "economie": {}}

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

    async def _dodo(_s):
        return None

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
        (ICARE, None): {"Name": "Icarus Wings", "Description": "… in September 2026."},
        (ICARE, "fr-fr"): {"Name": "Ailes d'Icarus", "Description": "… en septembre 2026."},
        (MEDUSE, None): {"Name": "Medusa Snakes", "Description": "bonus code"},
    }
    arts = asyncio.run(cartes.fiches({"items": [ICARE], "bonus_items": [MEDUSE],
                                      "cashstar_items": []}))
    assert [a["asset_id"] for a in arts] == [ICARE, MEDUSE]
    assert arts[0]["nom"] == "Icarus Wings" and arts[0]["nom_fr"] == "Ailes d'Icarus"
    assert arts[1]["nom"] == "Medusa Snakes" and "nom_fr" not in arts[1]


# ═══════════════════════════════════════════════════════════════════════════════
#  C — dire quelle carte, et quel mois
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("aid,desc,attendu", [
    (MEDUSE, "Redeemed via bonus code included with gift cards", "Code bonus"),
    (HERMES, "select Robux Digital Gift Card Codes from Amazon.", "Amazon"),
    (HERMES, "codes de carte cadeau numérique Robux sélectionnés sur Amazon.", "Amazon"),
    (ICARE, "a Roblox Gift Card from select retailers in September 2026.",
     "en magasin ou carte numérique"),
    (ARES, "une carte cadeau Roblox auprès de certains détaillants", "en magasin"),
])
def test_C1_chaque_article_dit_quelle_carte_le_donne(aid, desc, attendu):
    assert attendu in cartes.source_de({"asset_id": aid, "description": desc}, FR)


def test_C1bis_un_article_seulement_numerique():
    offre = {"items": [5], "bonus_items": [], "cashstar_items": [5]}
    assert "numérique" in cartes.source_de({"asset_id": 5}, offre)


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


# ═══════════════════════════════════════════════════════════════════════════════
#  D — la fiche
# ═══════════════════════════════════════════════════════════════════════════════

def _texte(vue) -> str:
    return str(vue.to_components())


def _composants(n) -> int:
    if isinstance(n, dict):
        return (1 if "type" in n else 0) + sum(_composants(v) for v in n.values())
    if isinstance(n, list):
        return sum(_composants(v) for v in n)
    return 0


def _articles():
    return [
        {"asset_id": ICARE, "item_type": "Asset", "nom": "Icarus Wings",
         "nom_fr": "Ailes d'Icarus",
         "description": "Get this item … select retailers in September 2026."},
        {"asset_id": HERMES, "item_type": "Asset", "nom": "Cap of Hermes",
         "description": "select Robux Digital Gift Card Codes from Amazon."},
        {"asset_id": MEDUSE, "item_type": "Asset", "nom": "Medusa Snakes",
         "description": "Redeemed via bonus code included with gift cards"},
    ]


@pytest.fixture
def panneau():
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


def test_D1_la_fiche_montre_tout_ce_qu_une_carte_donne(panneau):
    img = {ICARE: "https://tr.rbxcdn.com/180DAY-x/420/420/Hat/Png/noFilter"}
    vue = rp.construire_cartes(_articles(), FR, img, ping_cle=None)
    t = _texte(vue)
    assert "CARTES CADEAUX ROBLOX · offerts en septembre 2026" in t
    for nom in ("Ailes d'Icarus", "Icarus Wings", "Cap of Hermes", "Medusa Snakes"):
        assert nom in t
    assert "en magasin" in t and "Amazon" in t and "Code bonus" in t
    assert "https://www.roblox.com/redeem" in t and cartes.PAGE in t
    assert f"https://www.roblox.com/catalog/{MEDUSE}/" in t
    assert _composants(vue.to_components()) <= 40


def test_D2_sans_image_ni_mois_la_fiche_part_quand_meme(panneau):
    arts = [dict(a, description="") for a in _articles()]
    t = _texte(rp.construire_cartes(arts, FR, {}))
    assert "offerts en ce moment" in t and "Medusa Snakes" in t


def test_D3_une_longue_liste_tient_dans_une_fiche_et_le_dit(panneau):
    """⚠️ Trouvé par ce test le 29/09 : dix articles avec image et bouton
    demandaient 51 composants — Discord refuse au-delà de 40, la fiche ne
    serait jamais partie."""
    arts = [{"asset_id": 10 ** 10 + k, "item_type": "Asset", "nom": f"A{k}",
             "nom_fr": f"B{k}", "description": "x"} for k in range(12)]
    img = {a["asset_id"]: "https://tr.rbxcdn.com/180DAY-y/420/420/Hat/Png/noFilter"
           for a in arts}
    offre = {"items": [a["asset_id"] for a in arts]}
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)
    vue = rp.construire_cartes(arts, offre, img, ping_cle="nouveaux",
                               ping_role=type("R", (), {"id": 5, "mention": "<@&5>"})())
    assert _composants(vue.to_components()) <= 40
    t = _texte(vue)
    assert "autre(s) sur la page officielle" in t
    assert "Me prévenir" in t, "le bouton d'abonnement n'est jamais sacrifié"


def test_D4_cinq_articles_tiennent_en_entier(panneau):
    """Le cas réel du 29/09 : cinq articles, tous avec image et lien."""
    arts = [{"asset_id": i, "item_type": "Asset", "nom": str(i), "description": "x"}
            for i in (ICARE, HERMES, ARES, MINOTAURE, MEDUSE)]
    img = {a["asset_id"]: "https://tr.rbxcdn.com/180DAY-z/420/420/Hat/Png/noFilter"
           for a in arts}
    t = _texte(rp.construire_cartes(arts, FR, img, ping_cle="nouveaux"))
    assert "autre(s)" not in t
    assert t.count("https://www.roblox.com/catalog/") == 5


# ═══════════════════════════════════════════════════════════════════════════════
#  E — le branchement : une lecture toutes les 3 h, une fiche par changement
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


def _banc(offre=FR, publie=True, simulation=False, motif=None):
    etat = {"affichee": {}, "publies": [], "journal": [], "lectures": 0}

    class FauxCartes:
        HEURES_ENTRE_LECTURES = cartes.HEURES_ENTRE_LECTURES
        signature = staticmethod(cartes.signature)
        ids_de = staticmethod(cartes.ids_de)
        mois_de = staticmethod(cartes.mois_de)

        @staticmethod
        async def lire_offre(_m):
            etat["lectures"] += 1
            return {"offre": etat.get("offre", offre), "motif": motif}

        @staticmethod
        async def deja_affichee(gid, sig):
            return etat["affichee"].get(gid) == sig

        @staticmethod
        async def noter_affichee(gid, sig):
            etat["affichee"][gid] = sig

        @staticmethod
        async def fiches(o):
            return [{"asset_id": i, "nom": str(i)} for i in cartes.ids_de(o)]

    class FauxVeille:
        @staticmethod
        async def config(_g):
            return {"roblox_veille_simulation": simulation}

        @staticmethod
        def salon_du_flux(_c, flux):
            return 99 if flux == "nouveautes" else 0

        @staticmethod
        async def vignettes(_a):
            return {}

    class FauxUI:
        @staticmethod
        async def publier_cartes(g, salon, arts, o, imgs):
            etat["publies"].append((g.id, len(arts)))
            return publie

    ns = {"roblox_cartes_module": FauxCartes, "roblox_module": FauxVeille,
          "roblox_ui": FauxUI, "_CARTES": {"script": None, "offre": None,
                                           "lu_le": None, "dit": None},
          "datetime": datetime, "timezone": timezone,
          "print": lambda *a, **k: etat["journal"].append(" ".join(map(str, a)))}
    exec(_fonction("_cartes_cadeaux"), ns)          # noqa: S102 — code du dépôt
    return ns, etat


def _tick(ns, guildes):
    return asyncio.run(ns["_cartes_cadeaux"](guildes))


def test_E1_la_liste_s_affiche_une_fois_et_pas_deux():
    ns, etat = _banc()
    r = _tick(ns, [_Guilde(1)])
    assert r["publies"] == 1 and etat["publies"] == [(1, 5)]
    assert etat["affichee"][1] == cartes.signature(FR)
    ns["_CARTES"]["lu_le"] = datetime.now(timezone.utc) - timedelta(hours=4)
    r = _tick(ns, [_Guilde(1)])
    assert r["lu"] is True and r["publies"] == 0 and len(etat["publies"]) == 1


def test_E2_pas_plus_d_une_lecture_toutes_les_trois_heures():
    ns, etat = _banc()
    _tick(ns, [_Guilde(1)])
    r = _tick(ns, [_Guilde(1)])
    assert r["lu"] is False and etat["lectures"] == 1


def test_E3_une_nouvelle_liste_fait_une_nouvelle_fiche():
    ns, etat = _banc()
    _tick(ns, [_Guilde(1)])
    etat["offre"] = dict(FR, bonus_items=[106083349330631])
    ns["_CARTES"]["lu_le"] = datetime.now(timezone.utc) - timedelta(hours=4)
    _tick(ns, [_Guilde(1)])
    assert len(etat["publies"]) == 2


def test_E4_un_envoi_rate_n_est_pas_note_affiche():
    ns, etat = _banc(publie=False)
    _tick(ns, [_Guilde(1)])
    assert etat["affichee"] == {}, "sinon la liste ne serait jamais réessayée"


def test_E5_la_simulation_ne_publie_rien_et_ne_note_rien():
    ns, etat = _banc(simulation=True)
    _tick(ns, [_Guilde(1)])
    assert etat["publies"] == [] and etat["affichee"] == {}
    assert any("SIMULATION" in l for l in etat["journal"])


def test_E6_une_page_illisible_le_dit_une_fois():
    ns, etat = _banc(offre=None, motif="HTTP 403")
    _tick(ns, [_Guilde(1)])
    ns["_CARTES"]["lu_le"] = datetime.now(timezone.utc) - timedelta(hours=4)
    _tick(ns, [_Guilde(1)])
    assert etat["publies"] == []
    assert sum("illisible" in l for l in etat["journal"]) == 1


def test_E7_sans_salon_rien_ne_part():
    ns, etat = _banc()
    _tick(ns, [_Guilde(1, salon=False)])
    assert etat["publies"] == [] and etat["affichee"] == {}


def test_E8_le_releve_de_30_min_appelle_les_cartes_apres_le_catalogue():
    boucle = _fonction("veille_roblox_task")
    i_rendu = boucle.index("roblox_module.catalogue_occupe(False)")
    i_cartes = boucle.index("await _cartes_cadeaux(guildes_items)")
    assert i_rendu < i_cartes, "les cartes ne doivent pas tenir le chemin du catalogue"
