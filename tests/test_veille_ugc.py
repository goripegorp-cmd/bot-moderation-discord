"""Le flux UGC — les accessoires créés par les AUTRES joueurs.

═══════════════════════════════════════════════════════════════════════════════
POURQUOI CE FLUX EXISTE (mesuré le 03/09/2026)
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire, trois fois en quatre jours : « il y a des nouveaux accessoires
qui ont été créés sur roblox, ils sont toujours pas publiés, on sait pas
pourquoi ». Le bot répondait « création la plus récente il y a 17,6 jours ».

La même question posée deux fois au catalogue, en ne changeant QUE le créateur :

    CreatorTargetId=1  (ce que suivait le bot)  →  plus récent : 19,8 JOURS
    sans CreatorTargetId (tous créateurs)       →  plus récent :  1,2 HEURE

Aucun des deux ne mentait : ce sont DEUX CATALOGUES. Roblox publie par fournées
espacées de semaines ; les joueurs publient en continu.

═══════════════════════════════════════════════════════════════════════════════
LES TROIS MESURES QUI COMMANDENT LA CONCEPTION
═══════════════════════════════════════════════════════════════════════════════
  1. `favoriteCount` vaut 0 sur **99/99** accessoires fraîchement créés. Un
     filtre sur les favoris — le réflexe évident — viderait ce flux POUR
     TOUJOURS, et personne ne saurait pourquoi.
  2. Sur les 12 accessoires les plus récents, **un seul** est en vente avec un
     prix (« Hatter's Domain teacup hat », 95 R$). Les onze autres sont des
     dépôts : « desi », « 6 », « tyskirtredblack ». C'est là qu'est la ligne.
  3. `SortType=3` n'est pas chronologique d'une PAGE à l'autre : page 1 à
     1,2 h, pages 2-3 à 271 h. Paginer ne rapporte rien et brûle du quota.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_VEILLE = (RACINE / "roblox_veille.py").read_text(encoding="utf-8")
SRC_PANNEAU = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")

CFG = {"roblox_ugc_prix_min": 1, "roblox_ugc_verifie_seul": True}


def _art(**kw):
    """Un article NORMALISÉ, portant tout ce que le vrai porte — piège n°6."""
    base = {"asset_id": 42, "nom": "Un chapeau", "asset_type": 8,
            "type_article": "Chapeau", "item_type": "Asset",
            "prix": 95, "favoris": 0, "hors_vente": 0,
            "createur_nom": "Pierrette", "createur_id": 777,
            "createur_verifie": 1, "cree_le": "2026-09-03T10:00:00Z"}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
#  Le filtre de qualité
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_accessoire_vendu_par_un_createur_verifie_passe():
    ok, motif = veille.qualite_ugc(_art(), CFG)
    assert ok is True and motif == "retenu"


def test_un_depot_sans_prix_est_ecarte():
    """⚠️ LE CAS MAJORITAIRE, ET LE PLUS UTILE. Onze des douze accessoires les
    plus récents mesurés le 03/09 sont dans ce cas : « desi », « 6 »,
    « tyskirtredblack ». Un article sans prix n'est pas un produit publié,
    c'est un téléversement."""
    ok, motif = veille.qualite_ugc(_art(prix=None), CFG)
    assert ok is False and "sans prix" in motif


def test_un_fond_d_ecran_nest_pas_un_accessoire():
    """assetType 92 = Background. Il occupe régulièrement la tête du
    classement et n'est pas portable."""
    ok, motif = veille.qualite_ugc(_art(asset_type=92), CFG)
    assert ok is False and "accessoire" in motif


def test_un_article_hors_vente_est_ecarte():
    ok, motif = veille.qualite_ugc(_art(hors_vente=1), CFG)
    assert ok is False and "vente" in motif


def test_le_createur_non_verifie_est_ecarte_quand_on_le_demande():
    ok, motif = veille.qualite_ugc(_art(createur_verifie=0), CFG)
    assert ok is False and "vérifié" in motif


def test_et_passe_quand_on_ne_le_demande_pas():
    """Le réglage doit VRAIMENT faire quelque chose : un interrupteur sans
    effet est un menu qui ment."""
    ok, _ = veille.qualite_ugc(_art(createur_verifie=0),
                               dict(CFG, roblox_ugc_verifie_seul=False))
    assert ok is True


def test_le_prix_plancher_mord():
    assert veille.qualite_ugc(_art(prix=10),
                              dict(CFG, roblox_ugc_prix_min=50))[0] is False
    assert veille.qualite_ugc(_art(prix=60),
                              dict(CFG, roblox_ugc_prix_min=50))[0] is True


def test_un_prix_de_zero_est_ecarte_par_le_plancher_par_defaut():
    """Le plancher vaut 1 par défaut : un article « gratuit » est presque
    toujours un dépôt de test, et le distinguer coûte un seul R$."""
    assert veille.qualite_ugc(_art(prix=0), CFG)[0] is False


def test_le_filtre_rend_TOUJOURS_un_motif_meme_en_acceptant():
    """⚠️ SANS MOTIF, UN FLUX MUET EST INDISCERNABLE D'UN CATALOGUE CALME.
    C'est le défaut qui a caché le blocage de l'amorce pendant des semaines :
    les bascules étaient détectées puis rangées sous « déjà sorti », sans que
    rien ne le dise."""
    for a in (_art(), _art(prix=None), _art(asset_type=92),
              _art(hors_vente=1), _art(createur_verifie=0)):
        ok, motif = veille.qualite_ugc(a, CFG)
        assert isinstance(motif, str) and motif.strip(), (
            f"{'accepté' if ok else 'refusé'} sans motif")


def test_le_filtre_est_fail_closed():
    """Un défaut ici ne doit pas ouvrir les vannes sur un catalogue de
    plusieurs milliers d'articles par jour."""
    class Piege(dict):
        def get(self, *a, **k):
            raise RuntimeError("article corrompu")

    ok, motif = veille.qualite_ugc(Piege(), CFG)
    assert ok is False and "erreur" in motif


def test_AUCUN_filtre_sur_les_favoris_nulle_part():
    """⚠️ LE PIÈGE MESURÉ : `favoriteCount` vaut 0 sur 99/99 accessoires
    fraîchement créés. N'importe quel seuil, même 1, viderait ce flux pour
    toujours — et le symptôme serait « le bot ne publie rien », c'est-à-dire
    exactement la plainte qu'on est en train de corriger."""
    for n in ast.walk(ast.parse(SRC_VEILLE)):
        if isinstance(n, ast.FunctionDef) and n.name == "qualite_ugc":
            corps = ast.unparse(n)
            assert "favoris" not in corps, (
                "un filtre sur les favoris rendrait le flux UGC "
                "définitivement vide")
            return
    raise AssertionError("qualite_ugc introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  La requête : un seul paramètre change, et il change tout
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_releve_ugc_n_impose_AUCUN_createur(monkeypatch):
    """C'est LA différence avec le flux officiel, et la raison d'être du
    module. La laisser filer ramènerait le flux à 19,8 jours d'ancienneté."""
    vu = {}

    async def _faux(params, source, max_pages=None, curseur_depart=None):
        vu["params"], vu["source"] = params, source
        vu["max_pages"] = max_pages
        return {"articles": [], "code": 200}

    monkeypatch.setattr(veille, "_relever_catalogue", _faux)
    await veille.relever_ugc(limite=30)

    assert "CreatorTargetId" not in vu["params"], (
        "le relevé UGC filtre sur un créateur : il ne verrait que Roblox")
    assert "CreatorType" not in vu["params"]
    assert vu["params"]["SortType"] == 3
    assert vu["source"] == "ugc", (
        "la santé de ce flux doit se suivre séparément : un flux mort "
        "ressemble exactement à un flux calme")


@pytest.mark.asyncio
async def test_une_seule_page_et_c_est_mesure(monkeypatch):
    """⚠️ Page 1 à 1,2 h, pages 2-3 à 271 h (mesuré le 03/09). Le tri n'est
    pas chronologique d'une page à l'autre : paginer ne rapporte AUCUN article
    plus frais et brûle du quota sur un chemin déjà serré (12 req/min)."""
    vu = {}

    async def _faux(params, source, max_pages=None, curseur_depart=None):
        vu["max_pages"] = max_pages
        return {"articles": [], "code": 200}

    monkeypatch.setattr(veille, "_relever_catalogue", _faux)
    await veille.relever_ugc()
    assert vu["max_pages"] == 1, (
        f"le flux UGC pagine ({vu['max_pages']}) : quota brûlé pour rien")
    assert veille.MAX_PAGES_UGC == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  Le salon : aucun repli, et c'est le point le plus important
# ═══════════════════════════════════════════════════════════════════════════════

def test_l_ugc_n_a_AUCUN_salon_de_repli():
    """⚠️ LE DÉGÂT QU'ON ÉVITE. Les trois flux officiels retombent sur le
    premier salon réglé — commodité voulue. Appliquée à l'UGC, elle
    déverserait le catalogue entier dans le salon des nouveautés Roblox à la
    seconde où le propriétaire allume l'interrupteur, sans qu'il l'ait
    demandé. Pas de salon = flux muet, et c'est le bon choix."""
    cfg = {"roblox_salon_nouveautes": 111, "roblox_salon_bascules": 222,
           "roblox_salon_surveiller": 333, "roblox_salon_ugc": 0}
    assert veille.salon_du_flux(cfg, "ugc") == 0, (
        "l'UGC est retombé sur un salon officiel")
    assert veille.salon_du_flux(cfg, "nouveautes") == 111
    cfg["roblox_salon_ugc"] = 444
    assert veille.salon_du_flux(cfg, "ugc") == 444


def test_un_salon_ugc_regle_ne_deborde_pas_sur_les_autres():
    """La contre-épreuve : si l'UGC est le SEUL salon réglé, les flux
    officiels ne doivent pas y atterrir."""
    cfg = {"roblox_salon_nouveautes": 0, "roblox_salon_bascules": 0,
           "roblox_salon_surveiller": 0, "roblox_salon_ugc": 444}
    assert veille.salon_du_flux(cfg, "nouveautes") == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  L'âge, l'isolement, et l'entonnoir
# ═══════════════════════════════════════════════════════════════════════════════

def test_l_ugc_suit_la_fenetre_de_six_heures():
    """⚠️ SANS CETTE LIGNE, « ugc » TOMBAIT DANS LA BRANCHE « surveiller »,
    qui exige un âge MINIMUM de plusieurs jours — le flux n'aurait jamais rien
    publié, en silence, sur un catalogue qui produit en continu."""
    from datetime import datetime, timedelta, timezone
    frais = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    vieux = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    assert veille.age_publiable({"cree_le": frais}, "ugc") is True
    assert veille.age_publiable({"cree_le": vieux}, "ugc") is False
    assert veille.age_publiable({"cree_le": None}, "ugc") is False, (
        "date illisible : on ne peut pas prouver « récent », on se tait")


def test_l_ugc_ne_pollue_JAMAIS_la_base_des_articles_roblox():
    """⚠️ LE DÉGÂT COLLATÉRAL À NE PAS CRÉER. Verser des milliers d'articles
    UGC par jour dans `comparer_et_enregistrer` gonflerait `roblox_articles`,
    fausserait la détection de bascules, et surtout ferait mentir la ligne
    « création la plus récente » — celle qui répond à « Roblox est-il calme,
    ou le bot est-il cassé ? ». Elle afficherait 0 h en permanence."""
    #  ⚠️ ON BORNE SUR LA SOURCE BRUTE, PAS SUR `ast.unparse` : celui-ci
    #  SUPPRIME LES COMMENTAIRES, donc « ÉTAPE 2 » y est introuvable et le
    #  test se serait tu en croyant juger. Piège déjà rencontré dans ce dépôt.
    lignes = SRC_BOT.splitlines()
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            bloc = lignes[n.lineno - 1:n.end_lineno]
            i_ugc = next(k for k, l in enumerate(bloc) if "relever_ugc(" in l)
            i_fin = next(k for k, l in enumerate(bloc)
                         if k > i_ugc and "a_envoyer(" in l)
            suite = chr(10).join(bloc[i_ugc:i_fin])
            assert "comparer_et_enregistrer" not in suite, (
                "l'UGC passe par la détection des articles Roblox : la ligne "
                "« création la plus récente » va mentir")
            return
    raise AssertionError("veille_roblox_task introuvable")


def test_le_compte_rendu_nomme_la_marche_ou_chaque_article_tombe():
    """« 30 lus · 0 retenus » sans le détail, c'est le défaut le plus coûteux
    de ce dépôt, commis deux fois : on ne peut pas distinguer un seuil trop
    strict d'un catalogue calme."""
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            corps = ast.unparse(n)
            assert "UGC (tous créateurs)" in corps
            assert "écartés" in corps, "les motifs de refus ne sont pas dits"
            assert "le filtre a tout écarté" in corps, (
                "le cas « zéro retenu » n'est pas signalé : il passerait pour "
                "un catalogue calme")
            return
    raise AssertionError("veille_roblox_task introuvable")


def test_le_normalisateur_garde_ce_dont_le_filtre_a_besoin():
    """Sans `asset_type` numérique et `createur_verifie`, `qualite_ugc` ne
    peut rien juger — il laisserait tout passer ou tout refuser."""
    for n in ast.walk(ast.parse(SRC_VEILLE)):
        if isinstance(n, ast.FunctionDef) and n.name == "_normaliser":
            corps = ast.unparse(n)
            for cle in ("asset_type", "createur_verifie", "createur_nom"):
                assert f"'{cle}'" in corps, f"_normaliser perd {cle}"
            return
    raise AssertionError("_normaliser introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  Les réglages doivent EXISTER, sinon le compte rendu ment
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_panneau_expose_le_salon_l_interrupteur_et_LES_DEUX_seuils():
    """⚠️ LE COMPTE RENDU DIT « desserrez le créateur vérifié ou le prix
    plancher dans le panneau ». Si ces réglages n'y sont pas, cette phrase est
    un mensonge — et UI.md l'interdit. Ils se livrent ensemble ou pas du
    tout."""
    assert "roblox_salon_ugc" in SRC_PANNEAU
    assert "rblx_toggle_ugc" in SRC_PANNEAU
    assert "roblox_ugc_prix_min" in SRC_PANNEAU, "le prix plancher est irréglable"
    assert "roblox_ugc_verifie_seul" in SRC_PANNEAU, (
        "« créateurs vérifiés seulement » est irréglable")


def test_allumer_sans_salon_le_dit_tout_de_suite():
    """Ce flux n'a pas de repli : un interrupteur allumé sans salon resterait
    muet en affichant « allumé »."""
    assert "aucun salon n'est réglé" in SRC_PANNEAU


@pytest.mark.asyncio
async def test_actif_ugc_exige_les_trois(monkeypatch):
    """Interrupteur maître, interrupteur UGC, ET salon. Il en manque un, le
    flux ne tourne pas — et `actif_ugc` doit le dire, pas le laisser croire."""
    etat = {}

    async def _cfg(_g):
        return etat

    monkeypatch.setattr(veille, "_cfg", _cfg)
    complet = {"roblox_veille_enabled": True, "roblox_ugc_enabled": True,
               "roblox_salon_ugc": 9}
    etat.update(complet)
    assert await veille.actif_ugc(1) is True
    for cle in complet:
        etat.clear()
        etat.update(complet)
        etat[cle] = 0 if cle == "roblox_salon_ugc" else False
        assert await veille.actif_ugc(1) is False, (
            f"actif_ugc rend True alors que {cle} est éteint")
