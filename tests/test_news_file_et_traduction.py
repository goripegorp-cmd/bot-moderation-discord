"""La file des actualités, la règle du « pointeur », et le budget de traduction.

QUATRE DÉFAUTS MESURÉS PAR L'AUDIT DU 30/08/2026, CORRIGÉS ICI.

P2 — UN BILLET NON SORTI SOUS HUIT JOURS ÉTAIT PERDU DÉFINITIVEMENT.
    `absorber_vieux` marque « publié » SANS envoyer au-delà de
    `AMORCE_GARDE_JOURS`. Il n'existait aucune étape entre « détecté » et
    « absorbé » : une source en 403 huit jours, un bot arrêté huit jours, un
    salon interdit huit jours, et l'actualité disparaissait. Pire, le bouton
    « ♻️ Tout republier » promet « ce qui est déjà connu peut de nouveau
    sortir » — faux au-delà de huit jours, puisque le relevé suivant repose la
    marque sans rien envoyer.

P3 — UNE ALERTE COURTE MAIS COMPLÈTE ÉTAIT JETÉE.
    « We are aware of an issue preventing some users from logging in… »,
    127 caractères et un lien → écartée comme « pointeur », sans un mot. C'est
    le billet qu'on a le plus besoin de voir vite.

P4 — FAMINE PAR BUDGET PARTAGÉ.
    Accessoires et actualités se partageaient 12 publications, accessoires
    d'abord. Douze fiches en file d'accessoires = zéro actualité, passage après
    passage.

M1 — 77 % DE LA TRADUCTION N'ATTEIGNAIT JAMAIS LE LECTEUR.
    Mesuré bout en bout : 2 902 caractères traduits, 687 affichés. On payait
    2 400 caractères de traduction pour en montrer 800, à chaque billet et à
    chaque relevé.
"""
from __future__ import annotations

import ast
import contextlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import roblox_news as news
import roblox_news_contenu as contenu

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
GUILDE = 555


def _boucle() -> str:
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            return ast.unparse(n)
    raise AssertionError("veille_roblox_task introuvable")


@pytest.fixture
def banc(tmp_path):
    chemin = tmp_path / "news.db"

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

    news.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set,
               log=lambda *a, **k: None)
    return chemin


def _billet(tid="4833635", titre="Release Notes for 736"):
    return {"topic_id": tid, "titre": titre, "corps": "Un contenu réel.",
            "cree_le": datetime.now(timezone.utc).isoformat()}


# ═══════════════════════════════════════════════════════════════════════════════
#  P2 — la file : détecté une fois, il n'a plus besoin d'être re-relevé
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_un_billet_enfile_survit_a_un_redemarrage(banc):
    await news.init_db()
    assert await news.enfiler_actu(GUILDE, _billet()) is True
    #  « Redémarrage » : plus rien en mémoire, on relit la base.
    attente = await news.actus_a_envoyer(GUILDE)
    assert len(attente) == 1
    assert attente[0]["billet"]["titre"] == "Release Notes for 736"


@pytest.mark.asyncio
async def test_un_meme_billet_nentre_quune_fois(banc):
    """La détection rejoue à chaque relevé : sans contrainte d'unicité, la file
    grossirait d'une ligne toutes les trente minutes."""
    await news.init_db()
    entrees = [await news.enfiler_actu(GUILDE, _billet()) for _ in range(8)]
    assert entrees.count(True) == 1
    assert (await news.etat_file_actu(GUILDE))["attente"] == 1


@pytest.mark.asyncio
async def test_deux_serveurs_ont_chacun_leur_ligne(banc):
    await news.init_db()
    assert await news.enfiler_actu(GUILDE, _billet()) is True
    assert await news.enfiler_actu(GUILDE + 1, _billet()) is True
    assert (await news.etat_file_actu(GUILDE))["attente"] == 1
    assert (await news.etat_file_actu(GUILDE + 1))["attente"] == 1


@pytest.mark.asyncio
async def test_deux_tireurs_ne_publient_pas_le_meme_billet(banc):
    """La boucle et le bouton « Relever maintenant » peuvent tirer la même
    ligne. Sans réservation, le salon reçoit tout en double."""
    await news.init_db()
    await news.enfiler_actu(GUILDE, _billet())
    a = (await news.actus_a_envoyer(GUILDE))[0]
    b = (await news.actus_a_envoyer(GUILDE))[0]
    assert a["id"] == b["id"]
    pris = [await news.reserver_actu(a["id"], a["essais"]),
            await news.reserver_actu(b["id"], b["essais"])]
    assert pris.count(True) == 1


@pytest.mark.asyncio
async def test_un_echec_garde_le_billet_puis_l_abandonne(banc):
    await news.init_db()
    await news.enfiler_actu(GUILDE, _billet())
    ligne = (await news.actus_a_envoyer(GUILDE))[0]
    await news.noter_echec_actu(ligne["id"], "salon interdit")
    assert (await news.etat_file_actu(GUILDE))["attente"] == 1, (
        "un envoi raté ne doit pas faire disparaître le billet")
    for _ in range(news.MAX_ESSAIS_ACTU):
        await news.noter_echec_actu(ligne["id"], "salon interdit")
    etat = await news.etat_file_actu(GUILDE)
    assert etat["attente"] == 0 and etat["abandonnees"] == 1


@pytest.mark.asyncio
async def test_le_bouton_tout_republier_ramene_vraiment_les_abandonnees(banc):
    """⚠️ LE BOUTON PROMETTAIT « ce qui est déjà connu peut de nouveau
    sortir ». C'était faux : `oublier_publies` n'a jamais touché cette file."""
    await news.init_db()
    await news.enfiler_actu(GUILDE, _billet())
    ligne = (await news.actus_a_envoyer(GUILDE))[0]
    for _ in range(news.MAX_ESSAIS_ACTU + 1):
        await news.noter_echec_actu(ligne["id"], "salon interdit")
    assert await news.actus_a_envoyer(GUILDE) == []

    assert await news.relancer_actus_abandonnees(GUILDE) == 1
    assert len(await news.actus_a_envoyer(GUILDE)) == 1


def test_le_bouton_appelle_les_deux_relances():
    pan = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
    assert "veille.relancer_abandonnees(" in pan
    assert "news.relancer_actus_abandonnees(" in pan, (
        "le bouton ne relance que les accessoires : sa promesse reste fausse "
        "pour les actualités")


@pytest.mark.asyncio
async def test_la_purge_nefface_jamais_ce_qui_attend(banc):
    await news.init_db()
    await news.enfiler_actu(GUILDE, _billet())
    vieux = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    async with news._get_db() as db:
        await db.execute("UPDATE roblox_news_file SET detecte_le=?", (vieux,))
        await db.commit()
    await news.purger_file_actu()
    assert (await news.etat_file_actu(GUILDE))["attente"] == 1, (
        "la purge a effacé un billet qui n'était jamais parti")


@pytest.mark.asyncio
async def test_la_purge_efface_ce_qui_est_parti(banc):
    await news.init_db()
    await news.enfiler_actu(GUILDE, _billet())
    ligne = (await news.actus_a_envoyer(GUILDE))[0]
    assert await news.marquer_actu_envoyee(ligne["id"], 42) is True
    vieux = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    async with news._get_db() as db:
        await db.execute("UPDATE roblox_news_file SET envoye_le=?", (vieux,))
        await db.commit()
    assert await news.purger_file_actu() == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  P4 — la famine par budget partagé
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_actualites_ont_leur_propre_budget():
    """⚠️ DOUZE FICHES D'ACCESSOIRES = ZÉRO ACTUALITÉ, passage après passage.
    L'envoi doit tirer sur le plafond des actualités, pas sur le budget commun."""
    corps = _boucle()
    assert "roblox_news_module.actus_a_envoyer(" in corps, (
        "la boucle n'envoie pas depuis la file d'actualités")
    bloc = corps.split("actus_a_envoyer(")[1].split("purger_file_actu")[0]
    assert "_budget" not in bloc, (
        "l'envoi des actualités consomme encore le budget des accessoires")
    assert "MAX_BILLETS_PAR_PASSAGE" in corps


def test_l_envoi_ne_depend_plus_qu_une_source_reponde():
    """⚠️ L'envoi vivait DANS la boucle des sources : sans réponse d'une source,
    rien ne se vidait — même ce qui attendait depuis des jours."""
    corps = _boucle()
    i_sources = corps.index("for src in roblox_news_module.SOURCES")
    i_envoi = corps.index("roblox_news_module.actus_a_envoyer(")
    bloc_sources = corps[i_sources:i_envoi]
    assert "actus_a_envoyer" not in bloc_sources


def test_on_enfile_avant_de_tronquer():
    corps = _boucle()
    assert corps.index("roblox_news_module.enfiler_actu(") < corps.index(
        "roblox_news_module.actus_a_envoyer(")


def test_le_bilan_dit_enfin_les_ecartes_et_la_file():
    """⚠️ `grep -c pointeur bot.py` rendait 0. Le compteur existait dans le
    module, n'était lu que par le bouton manuel, et le bilan automatique n'en
    disait rien. Trois semaines de notes de version ont disparu sans une ligne."""
    #  ⚠️  NORMALISE LES GUILLEMETS : chercher la forme
    #  double-quote contre du source réécrit échouerait toujours.
    corps = _boucle().replace(chr(34), chr(39))
    assert "rel.get('pointeurs')" in corps, (
        "le bilan ne ramasse toujours pas le compteur des écartés")
    bilan = corps.split('passage terminé')[-1]
    assert 'allez voir ce' in bilan, 'les écartés ne sont pas imprimés'
    assert "file d'actualités" in bilan


# ═══════════════════════════════════════════════════════════════════════════════
#  P3 — la règle du « pointeur » ne jette plus les alertes
# ═══════════════════════════════════════════════════════════════════════════════

_LIEN = '<a href="https://create.roblox.com/docs/x">ici</a>'


def test_une_vraie_note_de_version_reste_un_pointeur():
    html = ("<p>Hi all, release notes for 734 is here! Have a great rest of "
            "your week.</p>" + _LIEN)
    assert contenu.est_pointeur(contenu._texte(html), html) is True


def test_une_alerte_courte_mais_complete_nest_plus_jetee():
    """⚠️ LE BILLET QU'ON A LE PLUS BESOIN DE VOIR VITE. 127 caractères et un
    lien vers la page d'état : écarté sans un mot avant le 30/08."""
    html = ("<p>We are aware of an issue preventing some users from logging in "
            "to Roblox. Our team is actively investigating and we will share "
            "an update shortly.</p>" + _LIEN)
    assert contenu.est_pointeur(contenu._texte(html), html) is False


def test_une_annonce_breve_mais_factuelle_passe():
    html = ("<p>Starting today, group payouts settle within 24 hours instead "
            "of 7 days for all verified creators in the EU region.</p>" + _LIEN)
    assert contenu.est_pointeur(contenu._texte(html), html) is False


def test_un_billet_sans_lien_nest_jamais_un_pointeur():
    """Un billet court SANS lien n'a nulle part où renvoyer : c'est une
    annonce brève, pas un panneau indicateur."""
    html = "<p>Court mais complet.</p>"
    assert contenu.est_pointeur(contenu._texte(html), html) is False


def test_un_billet_long_nest_jamais_un_pointeur():
    html = "<p>" + ("a" * 400) + " read more </p>" + _LIEN
    assert contenu.est_pointeur(contenu._texte(html), html) is False


def test_les_tournures_de_renvoi_sont_reconnues_en_deux_langues():
    for phrase in ("The full details are available.", "Read more about it.",
                   "Check it out.", "Retrouvez tout ici.",
                   "Plus de détails sur la page."):
        html = f"<p>{phrase} {'x' * 90}</p>{_LIEN}"
        assert contenu.est_pointeur(contenu._texte(html), html) is True, phrase


# ═══════════════════════════════════════════════════════════════════════════════
#  M1 — on ne paie plus une traduction qu'on jette
# ═══════════════════════════════════════════════════════════════════════════════

def test_on_ne_traduit_plus_trois_fois_ce_qu_on_affiche():
    """⚠️ MESURÉ BOUT EN BOUT : 2 902 caractères traduits, 687 affichés. Sur
    DeepL c'est du quota jeté ; sur MyMemory c'est du débit gaspillé vers un
    service gratuit qui finit par refuser."""
    src = inspect.getsource(contenu.enrichir_billet)
    ast.parse(src.lstrip())
    assert "BUDGET_CORPS_TRADUIT" in src, (
        "on envoie encore BUDGET_CORPS entier à la traduction")
    assert contenu.BUDGET_CORPS_TRADUIT < contenu.BUDGET_CORPS


def test_la_marge_couvre_l_expansion_du_francais():
    """Le français est plus long que l'anglais de 15 à 20 %. Traduire
    exactement ce qu'on affiche couperait une phrase au milieu."""
    pan = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
    for ligne in pan.splitlines():
        if ligne.startswith("BUDGET_FR_AFFICHE"):
            affiche = int(ligne.split("=")[1].strip())
            break
    else:
        raise AssertionError("BUDGET_FR_AFFICHE introuvable")
    assert contenu.BUDGET_CORPS_TRADUIT >= affiche, (
        "on traduirait moins que ce qu'on affiche : la fiche serait tronquée")
    assert contenu.BUDGET_CORPS_TRADUIT <= affiche * 2, (
        "la marge est redevenue du gaspillage")


def test_le_corps_original_reste_entier():
    """`BUDGET_CORPS` borne le corps ORIGINAL, qui sert à la mise en relation
    avec les accessoires et à l'extrait de vérification. Le réduire ferait
    perdre des rapprochements."""
    assert contenu.BUDGET_CORPS >= 2400


# ═══════════════════════════════════════════════════════════════════════════════
#  LA RÉGRESSION DU 30/08 — deux sources sur sept ne pouvaient plus rien publier
# ═══════════════════════════════════════════════════════════════════════════════
#
#  `enfiler_actu` faisait `int(billet["topic_id"])`. Or DEUX des sept sources
#  n'ont pas d'identifiant numérique : le newsroom fabrique « newsroom:{slug} »
#  (roblox_news.py:605) et la presse « presse:{slug} » (:454). Le `int()`
#  levait, on rendait False EN SILENCE, et la boucle — qui depuis le matin
#  n'envoie plus QUE depuis la file — ne les publiait jamais. Huit jours plus
#  tard `absorber_vieux` les marquait publiées sans les envoyer : perdues POUR
#  TOUJOURS, sans une ligne de journal.
#
#  ⚠️ LA SOURCE FRANÇAISE OFFICIELLE ÉTAIT LA PREMIÈRE TOUCHÉE — elle est
#  placée en tête de `SOURCES` exprès, pour gagner la déduplication.
#  ⚠️ ET LA COLONNE ÉTAIT DÉJÀ `TEXT` : le code contredisait son propre schéma.
#
#  Aucun test ne l'a vu : `_billet()` de ce fichier utilisait `tid="4833635"`,
#  une chaîne NUMÉRIQUE, qui passe `int()` sans broncher.

@pytest.mark.asyncio
async def test_un_identifiant_TEXTUEL_entre_bien_en_file(banc):
    """Le cas exact des sources hors forum. C'est le test qui manquait."""
    await news.init_db()
    for tid in ("newsroom:roblox-annonce-quelque-chose",
                "presse:resultats-du-trimestre",
                "4833635"):
        assert await news.enfiler_actu(GUILDE, _billet(tid=tid)) is True, tid
    assert (await news.etat_file_actu(GUILDE))["attente"] == 3

    #  Et ils ressortent intacts : un identifiant tronqué ou converti ferait
    #  échouer `marquer_publie` plus loin, sans un mot.
    lus = {e["billet"]["topic_id"] for e in await news.actus_a_envoyer(GUILDE)}
    assert "newsroom:roblox-annonce-quelque-chose" in lus


@pytest.mark.asyncio
async def test_un_billet_sans_identifiant_est_refuse_ET_journalise(banc, monkeypatch):
    """⚠️ UN REFUS MUET EST CE QUI A RENDU CE DÉFAUT INVISIBLE PENDANT UNE
    JOURNÉE ENTIÈRE DE LIVRAISONS. Le refus doit laisser une trace."""
    await news.init_db()
    dits = []
    monkeypatch.setattr(news, "_log", lambda m: dits.append(str(m)))
    assert await news.enfiler_actu(GUILDE, {"titre": "Sans identifiant"}) is False
    assert dits, "le refus n'a laissé aucune trace"
    assert (await news.etat_file_actu(GUILDE))["attente"] == 0


@pytest.mark.asyncio
async def test_les_slugs_de_deux_sources_ne_se_telescopent_pas(banc):
    """Les préfixes « newsroom: » et « presse: » existent précisément pour ça.
    Sans eux, un même slug publié des deux côtés n'entrerait qu'une fois."""
    await news.init_db()
    assert await news.enfiler_actu(GUILDE, _billet(tid="newsroom:meme-slug")) is True
    assert await news.enfiler_actu(GUILDE, _billet(tid="presse:meme-slug")) is True
    assert (await news.etat_file_actu(GUILDE))["attente"] == 2


def test_les_sources_hors_forum_fabriquent_bien_des_identifiants_textuels():
    """Si un jour elles passaient au numérique, ces tests deviendraient
    trompeurs : ils prouveraient une robustesse dont plus personne n'aurait
    besoin, en laissant croire que le vrai cas est couvert."""
    src = (RACINE / "roblox_news.py").read_text(encoding="utf-8")
    assert 'f"newsroom:{slug}"' in src or "newsroom:{slug}" in src
    assert 'f"presse:{slug}"' in src or "presse:{slug}" in src
    #  Et la colonne doit rester TEXT, sinon SQLite convertirait en silence.
    assert "topic_id TEXT NOT NULL" in src


def test_le_bouton_manuel_ne_publie_plus_hors_file():
    """⚠️ MESURÉ EN RÉFUTATION : 3 doublons sur 8 billets frais. Le bouton
    appelait `publier_actu` directement pendant que la boucle publiait depuis
    la file sans revérifier `deja_publie`. Le bouton des ACCESSOIRES avait été
    corrigé le matin même — la correction n'avait pas été portée ici."""
    import ast as _ast
    pan = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")
    corps = next(_ast.unparse(n) for n in _ast.walk(_ast.parse(pan))
                 if isinstance(n, _ast.AsyncFunctionDef)
                 and n.name == "_relever_actualites")
    assert "news.enfiler_actu(" in corps, "le bouton n'enfile pas"
    assert "news.reserver_actu(" in corps, (
        "le bouton publie sans réserver : il doublera la boucle")
    #  L'envoi doit venir de la file, pas de la liste fraîche.
    assert "news.actus_a_envoyer(" in corps
    i_enfile = corps.index("news.enfiler_actu(")
    i_tire = corps.index("news.actus_a_envoyer(")
    assert i_enfile < i_tire, "on enfile d'abord, on tire ensuite"
