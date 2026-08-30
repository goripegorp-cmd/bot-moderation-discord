"""Le salon AFK, l'échelle d'inactivité, et le rattrapage des accessoires.

TROIS DEMANDES DU PROPRIÉTAIRE, LE 30/08/2026.

1. LE SALON AFK. « Il y a un salon où les gens sont AFK, ils doivent écrire
   dedans […] le message s'auto supprime automatiquement, ça évite de laisser
   des pavés de messages. Ça permet à l'utilisateur d'envoyer un message. Le
   message supprimé, OK, il est redevenu actif. »
   ⚠️ CE QUI EXISTAIT DÉJÀ, ET QU'IL FAUT DIRE : écrire N'IMPORTE OÙ marquait
   déjà l'activité ET rendait déjà ses rôles à un membre étiqueté
   (`marquer_actif` + `retour_immediat`, bot.py). Le salon AFK n'ajoute donc
   AUCUN pouvoir de retour — il ajoute un endroit prévu pour ça, qui se
   nettoie. Prétendre le contraire ferait croire qu'écrire ailleurs ne compte
   pas.

2. L'ÉCHELLE. « Si y a aucun message dans la semaine, on leur dira d'être
   actif ; au bout de la 2e semaine, pas de messages, et ben on les met AFK
   avec le système de rôle. » Le rôle AFK arrivait à 7 jours ; il arrive
   désormais à 14. Le changement ne peut qu'ADOUCIR : personne n'est sanctionné
   plus tôt qu'avant.

3. LES DERNIERS ACCESSOIRES. « Assure-toi que les derniers accessoires soient
   bien publiés sur le serveur. » Mesuré le même jour : les huit derniers
   articles créés par Roblox ont **38,4 jours**, pour une fenêtre de
   publication de six heures. Ils ne peuvent PAS sortir seuls, et l'amorce les
   a marqués « déjà publiés ». D'où un rattrapage borné et volontaire.
"""
from __future__ import annotations

import ast
import contextlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import activite
import activite_passage as passage
import roblox_veille as veille

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. L'échelle d'inactivité correspond à celle qui a été décrite
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_role_afk_n_arrive_qu_a_la_deuxieme_semaine():
    """⚠️ LE RÔLE AFK MASQUE TOUT LE SERVEUR. Le poser dès la première semaine
    de silence, alors que le propriétaire décrit un simple avertissement à ce
    stade, punit une semaine trop tôt."""
    assert activite.SEUIL_RAPPEL_DEFAUT == 14, (
        "le rôle AFK revient à 7 jours : la première semaine de silence ne "
        "doit être qu'un avertissement")


def test_l_echelle_reste_strictement_croissante():
    """Deux paliers à la même valeur en rendraient un inatteignable — et le
    système sauterait silencieusement une étape."""
    assert (activite.SEUIL_RAPPEL_DEFAUT
            < activite.SEUIL_RETRAIT_DEFAUT
            < activite.SEUIL_EXPULSION_DEFAUT)


def test_le_posteur_hebdomadaire_finit_par_basculer():
    """« S'ils envoient un message une semaine… l'autre semaine aussi… on les
    considère comme AFK. » C'est le compteur de rappels doux consécutifs qui
    referme ce contournement, et il doit rester fini."""
    assert 2 <= activite.DOUX_MAX_DEFAUT <= 4
    assert activite.SEUIL_PRESENCE_DEFAUT >= 2, (
        "un seul jour de présence par semaine ne doit pas suffire, sinon "
        "poster le vendredi met le compteur à zéro toute l'année")


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le salon AFK
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_salon_afk_est_reglable():
    """Une clé de configuration que personne ne peut régler est du code mort."""
    assert "activite_salon_afk" in activite.CLES_DEFAUT
    assert activite.CLES_DEFAUT["activite_salon_afk"] == 0
    src = (RACINE / "activite_panneau.py").read_text(encoding="utf-8")
    assert '"activite_salon_afk"' in src, (
        "le salon AFK n'apparaît pas dans le panneau : impossible à régler")


def test_le_delai_laisse_voir_l_accuse():
    """⚠️ ZÉRO SECONDE N'EST PAS UN BON RÉGLAGE. Le membre doit voir que c'est
    passé, sinon il réécrit — et on obtient l'inverse du salon propre visé."""
    assert activite.CLES_DEFAUT["activite_afk_secondes"] >= 3


@pytest.mark.asyncio
async def test_est_salon_afk_ne_confond_pas_les_salons(monkeypatch):
    conf = {"activite_salon_afk": 4242}

    async def _cfg(_g):
        return dict(activite.CLES_DEFAUT, **conf)

    monkeypatch.setattr(activite, "config", _cfg)
    assert await passage.est_salon_afk(1, 4242) is True
    assert await passage.est_salon_afk(1, 9999) is False
    #  Salon non réglé : aucun salon ne doit être pris pour le salon AFK.
    conf["activite_salon_afk"] = 0
    assert await passage.est_salon_afk(1, 4242) is False
    assert await passage.est_salon_afk(1, 0) is False


class _Salon:
    def __init__(self, peut_gerer=True):
        self.id, self.name = 4242, "afk"
        self._peut = peut_gerer
        self.envoyes = []

    def permissions_for(self, _membre):
        class _P:
            manage_messages = self._peut
        _P.manage_messages = self._peut
        return _P()

    async def send(self, contenu, **kw):
        self.envoyes.append(contenu)
        return _Message(self, "accuse")


class _Message:
    def __init__(self, salon, texte="coucou", pinned=False):
        self.channel, self.guild = salon, _Guild()
        self.pinned = pinned
        self.content = texte
        self.author = type("A", (), {"mention": "@moi", "bot": False})()
        self.supprime = False

    async def delete(self):
        self.supprime = True


class _Guild:
    id = 1
    me = object()


@pytest.mark.asyncio
async def test_le_message_afk_est_efface_et_confirme(monkeypatch):
    async def _cfg(_g):
        return dict(activite.CLES_DEFAUT, activite_afk_secondes=0)

    monkeypatch.setattr(activite, "config", _cfg)
    salon = _Salon()
    msg = _Message(salon)
    assert await passage.nettoyer_message_afk(msg) is True
    assert msg.supprime is True
    assert salon.envoyes, "aucun accusé : le membre croira que ça n'a pas marché"
    assert "actif" in salon.envoyes[0]


@pytest.mark.asyncio
async def test_sans_la_permission_on_le_DIT_au_lieu_d_echouer_en_boucle(monkeypatch):
    """⚠️ SANS CE CONTRÔLE, chaque message du salon lèverait une erreur
    attrapée plus bas : le journal se remplirait d'une ligne par message au
    lieu d'un diagnostic, et le salon se remplirait en silence."""
    async def _cfg(_g):
        return dict(activite.CLES_DEFAUT, activite_afk_secondes=0)

    monkeypatch.setattr(activite, "config", _cfg)
    dits = []
    monkeypatch.setattr(passage, "_log", lambda m: dits.append(str(m)))
    msg = _Message(_Salon(peut_gerer=False))
    assert await passage.nettoyer_message_afk(msg) is False
    assert msg.supprime is False
    assert any("Gérer les messages" in d for d in dits), (
        "la cause exacte doit être journalisée")


@pytest.mark.asyncio
async def test_un_message_epingle_nest_pas_efface(monkeypatch):
    """Un message épinglé est une consigne du staff, pas un « je suis là »."""
    async def _cfg(_g):
        return dict(activite.CLES_DEFAUT)

    monkeypatch.setattr(activite, "config", _cfg)
    msg = _Message(_Salon(), pinned=True)
    assert await passage.nettoyer_message_afk(msg) is False
    assert msg.supprime is False


def test_le_nettoyage_passe_APRES_le_marquage_dans_on_message():
    """⚠️ L'ORDRE EST LE CŒUR DE LA CHOSE. Effacer le message avant de compter
    l'activité perdrait exactement la preuve qui vient de sauver le membre."""
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_message":
            corps = ast.unparse(n)
            break
    else:
        raise AssertionError("on_message introuvable")
    assert "activite_pass.nettoyer_message_afk" in corps, (
        "le nettoyage n'est branché nulle part : le salon ne se videra jamais")
    i_marque = corps.index("activite_module.marquer_actif")
    i_nettoie = corps.index("activite_pass.nettoyer_message_afk")
    assert i_marque < i_nettoie, (
        "le message est effacé AVANT d'être compté comme activité")
    #  Et en tâche détachée : l'attente ne doit pas geler tout on_message.
    assert "asyncio.create_task(\n                    activite_pass.nettoyer_message_afk" in corps \
        or "create_task" in corps.split("nettoyer_message_afk")[0][-120:], (
        "le nettoyage bloque on_message pendant son délai d'attente")


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

    async def _cfg(_g):
        return {}

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
    src = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
    bloc = src.split("async def _cb_relever")[1][:2500]
    assert "Relevé en cours" in bloc, (
        "le bouton ne dit pas qu'il travaille : le panneau reste figé")
    i_attente = bloc.index("Relevé en cours")
    i_travail = bloc.index("veille.relever_nouveautes(")
    assert i_attente < i_travail, (
        "le message d'attente est affiché APRÈS le travail : il ne sert à rien")
