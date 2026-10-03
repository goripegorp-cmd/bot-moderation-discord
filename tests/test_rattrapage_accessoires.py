"""Le rattrapage des derniers accessoires (30/08/2026).

« Assure-toi que les derniers accessoires soient bien publiés sur le serveur. »
Mesuré le même jour : les huit derniers articles créés par Roblox avaient
**38,4 jours**, pour une fenêtre de publication de six heures. Ils ne pouvaient
PAS sortir seuls, et l'amorce les avait marqués « déjà publiés ». D'où un
rattrapage borné et volontaire.

(Ces tests vivaient dans `test_salon_afk_et_rattrapage.py`, avec ceux du salon
AFK ; le système d'activité a été retiré le 03/10/2026 — ils restent, seuls.)
"""
from __future__ import annotations

import ast
import contextlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le rattrapage des derniers accessoires
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def banc(tmp_path):
    chemin = tmp_path / "veille.db"

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    #  ⚠️ LE RATTRAPAGE REMET EN FILE DES NOUVEAUTÉS : il n'a de sens que si
    #  ce flux est allumé. Depuis le 23/09 il est éteint par défaut (« uniquement
    #  les objets qui deviennent limited ») et le bouton disparaît du panneau
    #  quand il l'est — ces tests décrivent donc le cas où on l'a rallumé.
    async def _cfg(_g):
        return {"roblox_flux_nouveautes": True}

    async def _db_set(_g, _k, _v):
        return True

    veille.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
                 log=lambda *a, **k: None)
    return chemin


def _brut(aid, jours):
    quand = (datetime.now(timezone.utc) - timedelta(days=jours))
    return {"id": aid, "name": f"Accessoire {aid}", "itemType": "Asset",
            "itemCreatedUtc": quand.isoformat().replace("+00:00", "Z"),
            "itemRestrictions": [], "price": 100, "favoriteCount": 5}


@pytest.mark.asyncio
async def test_le_rattrapage_libere_et_enfile_les_plus_recents(banc, monkeypatch):
    """⚠️ LA SITUATION EXACTE DU PROPRIÉTAIRE, REJOUÉE. Des accessoires de
    38 jours, marqués « déjà publiés » par l'amorce, et une fenêtre de six
    heures qui les empêchera toujours de sortir."""
    await veille.init_db()
    arts = [_brut(i, 38) for i in range(1, 6)]
    await veille.comparer_et_enregistrer(veille._normaliser(arts))
    for i in range(1, 6):
        await veille.marquer_publie(1, i, "nouveautes")
    assert await veille.publiable_dans(1, 1, "nouveautes") is False

    async def _faux_fiches(ids, item_type="Asset"):
        return veille._normaliser([a for a in arts if a["id"] in set(ids)])

    monkeypatch.setattr(veille, "fiches_par_ids", _faux_fiches)
    r = await veille.rattraper_nouveautes(1, combien=12)

    assert r["candidats"] == 5 and r["enfiles"] == 5
    assert await veille.publiable_dans(1, 1, "nouveautes") is True
    assert (await veille.etat_file(1))["attente"] == 5
    #  ⚠️ IL DIT L'ÂGE. Publier 38 jours d'archives en silence romprait la
    #  règle « on ne présente pas comme nouveau ce qui a des semaines ».
    assert r["plus_vieux_j"] >= 37


@pytest.mark.asyncio
async def test_le_rattrapage_refuse_les_archives(banc, monkeypatch):
    """Au-delà de `AGE_MAX_JOURS`, ce n'est plus une nouvelle : c'est une
    archive, et ROBLOX.md interdit de la déverser dans le salon."""
    await veille.init_db()
    arts = [_brut(1, veille.AGE_MAX_JOURS + 30)]
    await veille.comparer_et_enregistrer(veille._normaliser(arts))

    async def _faux_fiches(ids, item_type="Asset"):
        return veille._normaliser(arts)

    monkeypatch.setattr(veille, "fiches_par_ids", _faux_fiches)
    r = await veille.rattraper_nouveautes(1, combien=12)
    assert r["candidats"] == 0 and r["enfiles"] == 0


@pytest.mark.asyncio
async def test_le_rattrapage_ne_touche_pas_a_une_bascule_deja_sortie(banc, monkeypatch):
    """Un article déjà annoncé comme passé Limited ne doit pas ressortir en
    « nouveauté » : ce serait un doublon, et une régression de flux."""
    await veille.init_db()
    arts = [_brut(1, 10)]
    await veille.comparer_et_enregistrer(veille._normaliser(arts))
    await veille.marquer_publie(1, 1, "bascules")

    async def _faux_fiches(ids, item_type="Asset"):
        return veille._normaliser(arts)

    monkeypatch.setattr(veille, "fiches_par_ids", _faux_fiches)
    r = await veille.rattraper_nouveautes(1, combien=12)
    assert r["enfiles"] == 0


def test_le_rattrapage_est_borne_et_volontaire():
    """⚠️ IL NE DOIT PAS ÊTRE AUTOMATIQUE. Déclenché tout seul, il déverserait
    le catalogue au premier démarrage — exactement ce que l'amorce existe pour
    empêcher. Et il ne touche PAS à `FENETRE_DIRECTE_HEURES` : la règle du
    propriétaire (« pas d'il y a un jour, deux jours ») reste intacte."""
    src = inspect.getsource(veille.rattraper_nouveautes)
    noeud = ast.parse(src.lstrip()).body[0]
    assert "min(int(combien), 30)" in src, "le rattrapage n'est pas borné"
    #  ⚠️ ON JUGE LE CODE, PAS LA DOCUMENTATION. La docstring CITE la fenêtre
    #  pour expliquer pourquoi le rattrapage existe ; un `in src` naïf tombait
    #  donc sur son propre commentaire. On retire la docstring avant de juger.
    corps = ast.unparse(ast.Module(body=noeud.body[1:], type_ignores=[]))
    assert "FENETRE_DIRECTE_HEURES" not in corps, (
        "le rattrapage touche à la fenêtre : la règle du 18/08 doit rester "
        "intacte, le rattrapage est un geste séparé")
    pan = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
    assert 'custom_id="rblx_rattraper"' in pan, "aucun bouton"
    assert "b_rattrap.callback = self._cb_rattraper" in pan, (
        "le bouton n'est branché sur rien — il afficherait « échec de "
        "l'interaction »")
    assert "veille.rattraper_nouveautes(" in pan


def test_les_fiches_sont_redemandees_en_UN_appel():
    """« Assure-toi de ne pas spammer en boucle une recherche qui sert à
    rien. » Le point de détails accepte 120 articles par requête : en faire
    douze serait gaspiller douze fois."""
    src = inspect.getsource(veille.rattraper_nouveautes)
    assert "fiches_par_ids(" in src, (
        "le rattrapage interroge Roblox article par article")
    lot = inspect.getsource(veille.fiches_par_ids)
    assert "propres[:120]" in lot


# ═══════════════════════════════════════════════════════════════════════════════
#  Le second clic, et l'ordre de sortie — signalés par le propriétaire le 30/08
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_second_clic_dit_DEJA_FAIT_et_pas_un_echec(banc, monkeypatch):
    """⚠️ LE MESSAGE ACCUSAIT LE CODE À TORT. Capture du propriétaire :
    « 0 accessoire(s) remis en file sur 12 retenu(s) », qu'il a lu comme une
    panne. C'était l'inverse : son premier clic avait réussi, les douze fiches
    attendaient en file, et `enfiler` les ignorait — c'est le rôle de la
    contrainte d'unicité. Un compteur qui ne distingue pas « échoué » de
    « déjà fait » fait chercher un défaut là où il n'y en a pas."""
    await veille.init_db()
    arts = [_brut(i, 38) for i in range(1, 6)]
    await veille.comparer_et_enregistrer(veille._normaliser(arts))

    async def _faux_fiches(ids, item_type="Asset"):
        return veille._normaliser([a for a in arts if a["id"] in set(ids)])

    monkeypatch.setattr(veille, "fiches_par_ids", _faux_fiches)

    r1 = await veille.rattraper_nouveautes(1, combien=12)
    assert r1["enfiles"] == 5 and r1["deja_en_file"] == 0

    r2 = await veille.rattraper_nouveautes(1, combien=12)
    assert r2["candidats"] == 5, "les articles restent des candidats"
    assert r2["enfiles"] == 0
    assert r2["deja_en_file"] == 5, (
        "le second clic doit dire « déjà en file », pas laisser croire à un "
        "échec")
    #  Et rien n'a été perdu ni dupliqué.
    assert (await veille.etat_file(1))["attente"] == 5


@pytest.mark.asyncio
async def test_la_file_sort_du_plus_VIEUX_au_plus_RECENT(banc, monkeypatch):
    """⚠️ DEMANDE EXPLICITE DU PROPRIÉTAIRE, 30/08 : « il publie du plus vieux
    au plus récent, ça veut dire qu'on a vraiment à la fin le dernier des
    derniers ». Discord empile vers le bas : envoyer le plus ancien d'abord
    fait que la DERNIÈRE fiche du salon est la création la plus récente.

    ⚠️ CE TEST A DÛ ÊTRE REFAIT. La première version donnait la MÊME date à
    tous les articles : `dates == sorted(dates)` passait alors trivialement et
    n'éprouvait rien du tout."""
    await veille.init_db()
    #  Dates DISTINCTES : l'article 1 est le plus vieux, le 12 le plus récent.
    arts = [_brut(i, 40 - i) for i in range(1, 13)]
    await veille.comparer_et_enregistrer(veille._normaliser(arts))

    async def _faux_fiches(ids, item_type="Asset"):
        return veille._normaliser([a for a in arts if a["id"] in set(ids)])

    monkeypatch.setattr(veille, "fiches_par_ids", _faux_fiches)
    await veille.rattraper_nouveautes(1, combien=12)

    lot = await veille.a_envoyer(1, limite=12)
    dates = [e["article"]["cree_le"] for e in lot]
    assert len(set(dates)) == len(dates), (
        "le banc doit donner des dates DISTINCTES, sinon il ne prouve rien")
    assert dates == sorted(dates), (
        "la file ne sort pas du plus ancien au plus récent : la dernière fiche "
        "du salon ne serait pas la création la plus récente")
    assert lot[-1]["article"]["asset_id"] == 12, (
        "le dernier envoyé doit être l'article le plus récemment créé")


def test_le_bouton_annonce_qu_il_va_etre_long():
    """⚠️ QUATRE MINUTES SANS UN MOT SE LISENT COMME UNE PANNE — et c'est ce
    que le propriétaire a conclu. Les pauses sont obligatoires (deux relevés
    paginés, la pause entre eux, la respiration avant les fiches) : on ne les
    raccourcit pas, on prévient."""
    #  ⚠️ TRANCHE DE 2500 CARACTÈRES SUPPRIMÉE. Elle a cassé dès que le corps
    #  a grandi (ajout du troisième relevé le 30/08) — une tranche fixe casse
    #  toujours pour une raison étrangère à la propriété testée. On borne sur
    #  la FONCTION, par l'arbre syntaxique.
    src = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
    bloc = next(ast.unparse(n) for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "_cb_relever")
    assert "Relevé en cours" in bloc, (
        "le bouton ne dit pas qu'il travaille : le panneau reste figé")
    i_attente = bloc.index("Relevé en cours")
    i_travail = bloc.index("veille.relever_nouveautes(")
    assert i_attente < i_travail, (
        "le message d'attente est affiché APRÈS le travail : il ne sert à rien")
    #  Et il fait bien les TROIS relevés : sans le troisième il serait aveugle
    #  aux créations hors vente — celles-là mêmes qu'il existe pour montrer —
    #  puis conclurait « rien à publier, c'est normal ».
    assert "veille.relever_hors_vente(" in bloc, (
        "le bouton ne fait que deux relevés sur trois : il ne verra aucune "
        "création retirée de la vente")
