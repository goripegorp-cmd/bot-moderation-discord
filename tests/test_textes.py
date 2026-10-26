"""26/10/2026 — « Textes & noms » (textes.py) : la direction réécrit les textes du bot et les noms du site.

Le fondateur : « s'il y a un rôle qui lui plaît pas, s'il y a un texte qui lui plaît pas, qu'il puisse modifier à sa
sauce et que ça s'enregistre… même pour le clan… le système de recrutement et tout… Avec de vrais boutons de
modification et d'enregistrement, et ça prend bien en compte. »

T1 déclarer : une faute de câblage se voit au démarrage. T2 les variables : seules les déclarées, jamais `str.format`.
T3 sans base : le texte d'origine. T4 écrire : nettoyé, borné, vide refusé, une ligne, le texte d'origine recopié.
T5 conflit par version, « Revenir au texte d'origine », avertissements. T6 le cache : relu à l'écriture et au
démarrage ; une base en panne donne l'origine (une seule tentative par minute). T7 RGPD. T8 les adresses du site
(origine, hors ligne par sync — une seule fois —, verrou déclaré, rôle renommé compté « grave »). T9 le recrutement
emploie les textes enregistrés (accueil, étape 2, boutons, formulaires, refus, merci, dossier). T10 les annonces et
événements (boutons, carte, réponses aux clics, rappels, nouvel horaire, annulation, aperçu, « Publiées »).
T11 les métiers (guide du clan réécrit au changement, carte de l'acceptation, ligne du MP). T12 renommer un rôle :
droits, refus, nom gardé pour le recréer. T13 les noms du site sont ceux de la page (noyau.js, affiche.js, les
sous-onglets, la fiche). T14 chaque clé écrite dans le code est déclarée. T15 le câblage (bot.py, site local, page hors
ligne). 26/10, « même ce qui existe déjà » : T16 la carte de l'équipe dans le ticket, ses boutons, le formulaire du
refus. T17 les réponses au choix du métier. T18 le listing et l'annonce des métiers. T19 le guide du clan (chaque
ligne, chaque bouton ; réécrit quand un texte change). T20 les sous-onglets renommés, une famille nommée par un module.
T21 la présence en direct : un texte que quelqu'un d'autre modifie n'est pas écrit (423), ni par la file hors ligne
tant qu'il est tenu ; l'éditeur de la page prend le verrou « texte:<clé> »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import re
import time
from pathlib import Path

import aiosqlite
import discord
import pytest

import affiches
import evenements as E
import gdpr
import health_server
import metiers
import questionnaire as Q
import registre
import site_equipage  # noqa: F401 — le site de l'équipage déclare sa famille de textes à l'import (T1)
import tableau
import textes
import transcript_store
import zones as ZN
from conftest_discord import Obj, laisser_finir
from faux_serveur import ids, textes as textes_vue
from test_evenements import api as api_ev, courir, env, evenement, inter, publier, T0  # noqa: F401 — `env` : la fixture
from test_metiers import Banc as BancMetiers, interaction as interaction_metier, avis as avis_metier
from test_questionnaire import Banc as BancQuestionnaire, _cliquer, _ouvrir_avec_carte, _soumettre, _vues_du_fil, \
    _modal_textes, CANDIDAT, FONDATEUR as FONDATEUR_Q

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
TETE = frozenset({FONDATEUR, DIRECTION})
ORIGINE = {"X-Tableau": "1", "Origin": "https://bot.exemple", "Sec-Fetch-Site": "same-origin"}


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


@pytest.fixture
def registre_textes(tmp_path, monkeypatch):
    """Le registre sur une base neuve ; ses déclarations d'essai et ses écouteurs oubliés après, et le registre
    débranché (les autres tests gardent les textes d'origine)."""
    monkeypatch.setattr(textes, "_DECLARES", dict(textes._DECLARES))
    monkeypatch.setattr(textes, "_ecouteurs", list(textes._ecouteurs))
    monkeypatch.setattr(textes, "GROUPES", dict(textes.GROUPES))
    journal = []
    get_db = _base(tmp_path / "textes.db")
    textes.setup(get_db=get_db, log=journal.append)
    asyncio.run(textes.init_db())
    yield Obj(get_db=get_db, journal=journal)
    textes.setup(get_db=None)


G1 = Obj(id=1, get_member=lambda uid: Obj(id=uid, display_name="GoRipe") if uid == FONDATEUR else None)


def ecrire(cle, valeur, version=None, g=G1, auteur=None):
    v = textes.item(g, cle)["version"] if version is None else version
    return asyncio.run(textes.ecrire(g, auteur or Obj(id=FONDATEUR), {"cle": cle, "valeur": valeur, "version": v}))


def remettre(cle, version=None, g=G1):
    corps = {"cle": cle} if version is None else {"cle": cle, "version": version}
    return asyncio.run(textes.remettre(g, Obj(id=FONDATEUR), corps))


def dans_une_boucle(coro_fn):
    """Le geste et ce qu'il planifie (le guide du clan réécrit en fond), dans la même boucle : `asyncio.run`
    annulerait sinon la tâche planifiée avant qu'elle ne s'exécute."""
    async def faire():
        r = await coro_fn()
        await laisser_finir(3.0)
        return r
    return asyncio.run(faire())


def libelles_boutons(vue) -> list:
    """Les libellés des boutons d'une vue (Components V2), persistants compris, dans l'ordre."""
    out = []

    def tout(c):
        if isinstance(c, dict):
            if c.get("type") == 2 and c.get("label"):
                out.append(c["label"])
            for x in c.get("components", []) or []:
                tout(x)
            if c.get("accessory"):
                tout(c["accessory"])
    for comp in vue.to_components():
        tout(comp)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  T1 – T3 : le registre
# ═══════════════════════════════════════════════════════════════════════════════

def test_T1_declarer_refuse_les_fautes_de_cablage(registre_textes):
    d = textes.declarer
    with pytest.raises(ValueError):
        d("Mauvaise Clé", "x", groupe="essai", titre="t")
    with pytest.raises(ValueError):
        d("essai.long", "x" * 11, groupe="essai", titre="t", max_=10)
    with pytest.raises(ValueError):
        d("essai.variable", "Bonjour {nom}", groupe="essai", titre="t")          # variable non déclarée
    with pytest.raises(ValueError):
        d("essai.ligne", "a\nb", groupe="essai", titre="t", lignes=False)
    with pytest.raises(ValueError):
        d("essai.vide", "  ", groupe="essai", titre="t")
    with pytest.raises(ValueError):
        d("essai.double", "x {a}", groupe="essai", titre="t", variables=("a", "a"))
    assert d("essai.ok", "Salut {nom}", groupe="essai", titre="Essai", variables=(("nom", "le nom"),)) == "Salut {nom}"
    assert textes.declare("essai.ok") and textes.defaut("essai.ok") == "Salut {nom}"
    assert len(textes._DECLARES) > 230, "recrutement, métiers, guide, annonces & événements, le site : tout est déclaré"
    familles = {x["groupe"] for x in textes._DECLARES.values()} - {"essai"}
    assert familles == {"recrutement", "metiers", "guide", "evenements", "site", "equipage_site"}, familles


def test_T2_seules_les_variables_declarees_sont_remplacees(registre_textes):
    textes.declarer("essai.vars", "A {nombre} B", groupe="essai", titre="E", variables=("nombre",))
    #  Écrit sur le site, avec des accolades de toutes sortes : rien ne casse, rien d'autre n'est remplacé.
    assert ecrire("essai.vars", "A {nombre} B {autre} {nombre:>3} { nombre } {0} {")[0] == 200
    assert textes.texte_cache(1, "essai.vars", nombre=10, autre="X") == "A 10 B {autre} {nombre:>3} { nombre } {0} {"
    assert textes.texte_cache(1, "essai.vars") == "A {nombre} B {autre} {nombre:>3} { nombre } {0} {", \
        "une variable non fournie reste visible (jamais un KeyError)"
    assert textes.texte_cache(1, "essai.vars", nombre="{nombre}{autre}").startswith("A {nombre}{autre} B"), \
        "un seul passage : une valeur n'est jamais relue"
    assert asyncio.run(textes.texte(G1, "essai.vars", nombre=4)).startswith("A 4 B"), "un serveur ou son id"


def test_T3_sans_base_le_texte_d_origine(registre_textes):
    textes.setup(get_db=None, log=registre_textes.journal.append)
    assert textes.texte_cache(1, "recrutement.merci") == Q.MERCI
    assert asyncio.run(textes.texte(1, "recrutement.refus_etape1")) == Q.REFUS_ETAPE1
    assert textes.texte_cache(1, "rien.du.tout") == "rien.du.tout", "une clé jamais déclarée : visible, jamais vide"
    assert "[TEXTES][E1] texte non déclaré demandé" in registre_textes.journal, "le message stable"
    assert any(x.startswith("[TEXTES][E1:DETAIL]") and "rien.du.tout" in x for x in registre_textes.journal)


# ═══════════════════════════════════════════════════════════════════════════════
#  T4 – T6 : écrire, conflits, cache
# ═══════════════════════════════════════════════════════════════════════════════

def test_T4_ecrire_nettoie_borne_et_garde(registre_textes):
    st, r = ecrire("recrutement.merci", "  Merci beaucoup !\r\n-# Thanks!​  ")
    assert st == 200 and r["texte"]["valeur"] == "Merci beaucoup !\n-# Thanks!" and r["texte"]["modifie"]
    assert r["texte"]["version"] == 1 and r["texte"]["maj_par"] == {"id": str(FONDATEUR), "nom": "GoRipe"}
    assert r["_journal"]["texte"] == "Textes & noms : « Merci, après ses réponses » modifié"
    assert textes.texte_cache(1, "recrutement.merci") == "Merci beaucoup !\n-# Thanks!", "employé tout de suite"
    assert textes.texte_cache(2, "recrutement.merci") == Q.MERCI, "un autre serveur garde le sien"
    #  Une ligne : les retours à la ligne deviennent des espaces.
    assert ecrire("evenements.bouton.dispo", "Je\nviens  ·  Coming")[1]["texte"]["valeur"] == "Je viens · Coming"
    #  Bornes : trop long, vide (requis), inconnu, mal formé, version absente.
    assert ecrire("evenements.bouton.dispo", "x" * 81) == (400, {"erreur": "80 caractères au plus (81 écrits)."})
    st, r = ecrire("recrutement.merci", "   ")
    assert st == 400 and "ne peut pas être vide" in r["erreur"]
    assert ecrire("recrutement.wiki", "")[0] == 200, "un texte facultatif peut être vidé (la phrase disparaît)"
    assert asyncio.run(textes.ecrire(G1, Obj(id=1), {"cle": "inconnu.texte", "valeur": "x", "version": 0}))[0] == 404
    assert asyncio.run(textes.ecrire(G1, Obj(id=1), {"cle": "<b>", "valeur": "x", "version": 0}))[0] == 400
    assert asyncio.run(textes.ecrire(G1, Obj(id=1), {"cle": "recrutement.merci", "valeur": "x"}))[0] == 400
    assert asyncio.run(textes.ecrire(G1, Obj(id=1), {"cle": "recrutement.merci", "valeur": 5, "version": 1}))[0] == 400
    #  Le texte d'origine recopié : rien de « modifié ».
    st, r = ecrire("recrutement.merci", Q.MERCI)
    assert st == 200 and not r["texte"]["modifie"] and r["texte"]["version"] == 2
    assert r["_journal"]["texte"].endswith("remis au texte d'origine")


def test_T5_conflit_par_version_et_retour_a_l_origine(registre_textes):
    assert ecrire("recrutement.refus_etape1", "Refus A")[0] == 200
    st, r = ecrire("recrutement.refus_etape1", "Refus B", version=0)       # lu avant la modification d'un autre
    assert st == 409 and r["conflit"] and r["erreur"] == "Ce texte a changé entre-temps."
    assert r["actuelle"]["valeur"] == "Refus A" and r["actuelle"]["version"] == 1
    assert textes.texte_cache(1, "recrutement.refus_etape1") == "Refus A", "rien d'écrasé"
    assert ecrire("recrutement.refus_etape1", "Refus B", version=1)[0] == 200
    assert remettre("recrutement.refus_etape1", version=1)[0] == 409, "une version périmée ne remet rien"
    st, r = remettre("recrutement.refus_etape1", version=2)
    assert st == 200 and not r["texte"]["modifie"] and r["texte"]["version"] == 3
    assert textes.texte_cache(1, "recrutement.refus_etape1") == Q.REFUS_ETAPE1
    st, r = remettre("recrutement.refus_etape1")
    assert st == 200 and r["deja"] and r["_journal"] is None, "déjà d'origine : rien à faire, rien au journal"
    #  Les avertissements : une variable qui disparaît, une variable inconnue.
    st, r = ecrire("recrutement.accueil.etapes", "Deux étapes, {total} questions.")
    assert st == 200 and r["avertissements"] == [
        "{nombre} n'apparaît plus : le nombre de questions de l'étape 2 (« 10 questions ») ne s'affichera pas.",
        "{nombre_en} n'apparaît plus : le même nombre, en anglais (« 10-question ») ne s'affichera pas.",
        "{total} n'est pas une variable de ce texte : il s'affichera tel quel."]


def test_T5b_un_module_prevenu_apres_l_ecriture(registre_textes):
    vus = []

    async def asynchrone(g, cle):
        vus.append(("a", g.id, cle))

    def en_panne(_g, _cle):
        raise RuntimeError("module en panne")
    textes.quand_change("recrutement.", asynchrone)
    textes.quand_change("recrutement.", en_panne)
    textes.quand_change("evenements.", lambda g, cle: vus.append(("e", cle)))
    assert ecrire("recrutement.merci", "Merci !")[0] == 200, "un module prévenu en échec ne défait rien"
    assert vus == [("a", 1, "recrutement.merci")]
    assert "[TEXTES][E4] module non prévenu d'un texte changé" in registre_textes.journal
    assert remettre("recrutement.merci")[0] == 200 and vus[-1] == ("a", 1, "recrutement.merci")


def test_T6_cache_relu_au_demarrage_et_base_en_panne(registre_textes):
    ecrire("evenements.bouton.dispo", "Présent · Here")
    textes.setup(get_db=registre_textes.get_db, log=registre_textes.journal.append)      # ⟳ redémarrage
    assert textes.texte_cache(1, "evenements.bouton.dispo") == "Disponible · Available", "cache vidé"
    assert asyncio.run(textes.texte(1, "evenements.bouton.dispo")) == "Présent · Here", "rechargé au premier texte"
    textes.setup(get_db=registre_textes.get_db, log=registre_textes.journal.append)
    asyncio.run(textes.init_db())
    assert textes.texte_cache(1, "evenements.bouton.dispo") == "Présent · Here", "chargé au démarrage"
    #  Une base qui ne répond pas : le texte d'origine, dit au journal, pas de nouvel essai avant une minute.
    essais = []

    @contextlib.asynccontextmanager
    async def panne():
        essais.append(1)
        raise aiosqlite.OperationalError("database is locked")
        yield  # noqa — jamais atteint
    textes.setup(get_db=panne, log=registre_textes.journal.append)
    assert asyncio.run(textes.texte(1, "evenements.bouton.dispo")) == "Disponible · Available"
    assert asyncio.run(textes.texte(1, "evenements.bouton.dispo")) == "Disponible · Available"
    assert essais == [1], "une seule tentative par minute"
    assert "[TEXTES][E2] textes du site illisibles : textes d'origine employés" in registre_textes.journal


# ═══════════════════════════════════════════════════════════════════════════════
#  T7 : RGPD
# ═══════════════════════════════════════════════════════════════════════════════

def test_T7_rgpd_l_auteur_est_neutralise_le_texte_reste(registre_textes):
    assert ecrire("recrutement.merci", "Merci, matelot !", auteur=Obj(id=555))[0] == 200
    assert gdpr.ANONYMIZE["site_textes"] == {"ids": ["maj_par"], "redact": []}

    async def purger():
        async with registre_textes.get_db() as db:
            resume = await gdpr.purge_user(db, 1, 555)
            carte = await gdpr.validate_map(db)
            async with db.execute("SELECT valeur, maj_par FROM site_textes WHERE cle='recrutement.merci'") as cur:
                return resume, carte, await cur.fetchone()
    resume, carte, ligne = asyncio.run(purger())
    assert ligne == ("Merci, matelot !", 0), "le texte du serveur reste, son auteur ne se lit plus"
    assert ("site_textes", "maj_par") not in carte["missing_columns"] and "site_textes" not in carte["missing_tables"]


# ═══════════════════════════════════════════════════════════════════════════════
#  T8 : les adresses du site (comme dans bot.py)
# ═══════════════════════════════════════════════════════════════════════════════

class Role:
    def __init__(self, rid, nom, position, permissions=None, managed=False):
        self.id, self.name, self.position, self.managed = rid, nom, position, managed
        self.permissions = permissions or discord.Permissions.none()
        self.colour = discord.Colour(0x1F4E5A)
        self.edits, self.refus = [], False

    def is_default(self):
        return self.position == 0

    async def edit(self, *, name=None, reason=None):
        if self.refus:
            raise discord.Forbidden(Obj(status=403, reason="x"), "Missing Permissions")
        self.edits.append((name, reason))
        self.name = name


class Site:
    def __init__(self, tmp_path, monkeypatch):
        self.get_db = get_db = _base(tmp_path / "site.db")
        self.roles = {1: Role(1, "@everyone", 0), 20: Role(20, "Cuisinier", 3), 21: Role(21, "VIP", 4),
                      22: Role(22, "Officier", 5)}
        membres = {uid: Obj(id=uid, display_name=nom, roles=[]) for uid, nom in ((FONDATEUR, "GoRipe"), (7, "Kolax"))}
        self.g = Obj(id=1, name="GoRP", get_member=lambda uid: membres.get(int(uid or 0)),
                     get_role=lambda rid: self.roles.get(int(rid or 0)), roles=list(self.roles.values()), members=[],
                     me=Obj(id=999, top_role=Role(2, "Bot", 50), guild_permissions=discord.Permissions(manage_roles=True)))
        self.conf, self.journal = {}, []

        async def cfg(_g):
            return self.conf

        async def db_set(_g, k, v):
            self.conf[k] = v

        def tete(g, m, c=None):
            return m is not None and m.id in TETE
        monkeypatch.setattr(tableau, "ROUTES", {})
        monkeypatch.setattr(tableau, "REGLES", dict(tableau.REGLES))
        monkeypatch.setattr(tableau, "_SOURCES_MEDIAS", [])
        monkeypatch.setattr(tableau, "RACINE_DONNEES", tmp_path / "donnees")
        monkeypatch.setattr(transcript_store, "_BASE_DIR", str(tmp_path / "transcripts"))
        registre.setup(get_db=get_db, log=lambda *a: None)
        registre._derniers.clear()
        tableau.setup(bot=Obj(get_guild=lambda gid: self.g if gid == 1 else None, user=Obj(id=999)), cle="k",
                      base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=None, autorise_membre=tete,
                      direction=tete, tete=TETE, log=self.journal.append)
        affiches.setup(get_db=get_db, log=self.journal.append)
        metiers.setup(get_db=get_db, cfg=cfg, db_set=db_set, role_clan=lambda g, c: None, log=self.journal.append)
        textes.setup(get_db=get_db, log=self.journal.append)

        async def preparer():
            await registre.init_db()
            await tableau.init_db()
            await affiches.init_db()
            await textes.init_db()
            async with get_db() as db:
                await db.execute("INSERT INTO rell_roles (guild_id, type, cle, role_id, auto, maj_le, maj_par)"
                                 " VALUES (1, 'metier', 'cooking', 20, 1, 0, 0)")
                await db.commit()
        asyncio.run(preparer())
        tableau.monter(textes)

    def biscuit(self) -> dict:
        jeton = asyncio.run(tableau._ouvrir_session(1, FONDATEUR, int(time.time()) + 3600))
        return dict({"Cookie": f"{tableau.COOKIE}={jeton}"}, **ORIGINE)

    def http(self, scenario):
        from aiohttp.test_utils import TestClient, TestServer

        async def lancer():
            async with TestClient(TestServer(health_server.construire_app())) as client:
                return await scenario(client)
        return asyncio.run(lancer())


async def _json(r):
    return r.status, json.loads(await r.text())


def test_T8_les_adresses_du_site(tmp_path, monkeypatch, registre_textes):
    site = Site(tmp_path, monkeypatch)
    h = site.biscuit()
    lecture = {"Cookie": h["Cookie"]}

    async def scenario(c):
        out = {}
        out["liste"] = await _json(await c.get("/tableau/espace/api/textes", headers=lecture))
        out["sans_origine"] = await _json(await c.post("/tableau/espace/api/texte", headers=lecture,
                                                       json={"cle": "site.cat.port.titre", "valeur": "X", "version": 0}))
        out["ecrit"] = await _json(await c.post("/tableau/espace/api/texte", headers=h,
                                                json={"cle": "site.cat.port.titre", "valeur": "La Taverne", "version": 0}))
        out["recrutement"] = await _json(await c.post("/tableau/espace/api/texte", headers=h,
                                                      json={"cle": "recrutement.merci", "valeur": "Merci !", "version": 0}))
        out["site"] = await _json(await c.get("/tableau/espace/api/textes/site", headers=lecture))
        op = {"op_id": "op-textes-0001", "api": "texte", "corps": {"cle": "evenements.bouton.vu", "valeur": "Lu · Read",
                                                                      "version": 0}}
        out["sync1"] = await _json(await c.post("/tableau/espace/sync", headers=h, json={"ops": [op]}))
        out["sync2"] = await _json(await c.post("/tableau/espace/sync", headers=h, json={"ops": [op]}))
        out["defaut"] = await _json(await c.post("/tableau/espace/api/texte/defaut", headers=h,
                                                 json={"cle": "site.cat.port.titre"}))
        out["site2"] = await _json(await c.get("/tableau/espace/api/textes/site", headers=lecture))
        out["renomme"] = await _json(await c.post("/tableau/espace/api/rell/role/renommer", headers=h,
                                                  json={"role_id": "20", "nom": "Maître-coq"}))
        out["renomme_hors_ligne"] = await _json(await c.post("/tableau/espace/sync", headers=h, json={"ops": [
            {"op_id": "op-textes-0002", "api": "rell/role/renommer", "corps": {"role_id": "20", "nom": "Non"}}]}))
        return out
    out = site.http(scenario)
    st, liste = out["liste"]
    assert st == 200 and [g["nom"] for g in liste["groupes"]] == ["Recrutement", "Métiers", "Le guide du clan",
                                                                    "Annonces & événements", "Le site",
                                                                    "Le site de l'équipage"]
    t = liste["groupes"][0]["textes"][0]
    assert set(t) >= {"cle", "titre", "aide", "defaut", "valeur", "modifie", "version", "max", "lignes", "variables",
                      "maj_le", "maj_par", "partie"}
    assert out["sans_origine"][0] == 400, "une écriture vient de la page elle-même"
    assert out["ecrit"][0] == 200 and out["ecrit"][1]["texte"]["valeur"] == "La Taverne"
    assert "_journal" not in out["ecrit"][1], "la phrase du journal ne sort jamais"
    assert out["site"] == (200, {"valeurs": {"site.cat.port.titre": "La Taverne"}}), "les noms du site seuls"
    assert out["sync1"][1]["resultats"][0]["status"] == 200 and out["sync2"] == out["sync1"], "rejouée : une seule fois"
    assert textes.texte_cache(1, "evenements.bouton.vu") == "Lu · Read"
    assert textes.item(G1, "evenements.bouton.vu")["version"] == 1
    assert out["defaut"][0] == 200 and out["site2"] == (200, {"valeurs": {}})
    assert out["renomme"][0] == 200 and site.roles[20].name == "Maître-coq"
    assert out["renomme_hors_ligne"][1]["resultats"][0]["status"] == 400, "un rôle ne se renomme jamais hors ligne"
    assert site.conf[metiers.CLE_NOMS] == {"cooking": "Maître-coq"}, "le nom servira à recréer le rôle du métier"
    journal = [x["texte"] for x in asyncio.run(registre.lire(1, 50))]
    assert any("Textes & noms : « Le Port · le nom » modifié" in x for x in journal)
    assert any("Rôle « Cuisinier » renommé « Maître-coq »" in x for x in journal)
    assert len(tableau._graves.get((1, FONDATEUR, "roles"), [])) == 1, "renommer un rôle compte parmi les gestes graves"
    #  Le verrou d'édition (équipe Présence) et les définitions.
    assert textes.ROUTES_SITE["texte"]["verrou"]({"cle": "recrutement.merci"}) == "texte:recrutement.merci"
    assert textes.ROUTES_SITE["texte/defaut"]["verrou"]({"cle": "site.cat.port.titre"}) == "texte:site.cat.port.titre"
    assert textes.ROUTES_SITE["texte"]["hors_ligne"] and textes.ROUTES_SITE["texte/defaut"]["hors_ligne"]
    assert textes.ROUTES_SITE["rell/role/renommer"]["grave"] == "roles"
    assert not textes.ROUTES_SITE["rell/role/renommer"].get("hors_ligne")


# ═══════════════════════════════════════════════════════════════════════════════
#  T9 : le recrutement emploie les textes enregistrés
# ═══════════════════════════════════════════════════════════════════════════════

def test_T9_le_recrutement_emploie_les_textes_enregistres(tmp_path, monkeypatch, registre_textes):
    monkeypatch.setattr(Q, "DELAI_FERMETURE", 0.0)
    monkeypatch.setattr(Q, "AVIS_S", 0)
    monkeypatch.setattr(Q, "PAGE_S", 0)
    for cle, valeur in (("recrutement.accueil.titre", "### Ahoy · Ahoy"),
                        ("recrutement.accueil.etapes", "Deux étapes, puis **{nombre}** · {nombre_en} quiz."),
                        ("recrutement.wiki", ""),
                        ("recrutement.liens.titre", "**Les pages utiles**"),
                        ("recrutement.refus_etape1", "Pas cette fois, moussaillon.\n-# Not this time."),
                        ("recrutement.etape2.titre", "## À toi de jouer — {nombre}"),
                        ("recrutement.bouton.repondre", "J'y vais · Go"),
                        ("recrutement.formulaire.titre", "Page {page} sur {pages}"),
                        ("recrutement.formulaire.reponse", "Écris ici"),
                        ("recrutement.page_enregistree", "Gardée ({page}/{pages}), la suite : {suivante}."),
                        ("recrutement.bouton.continuer", "Suite {page}/{pages}"),
                        ("recrutement.merci", "Bien reçu, merci !")):
        assert ecrire(cle, valeur)[0] == 200, cle
    b = BancQuestionnaire(tmp_path)

    async def scenario():
        await b.preparer()
        accueil, n = await Q.vue_accueil(b.g, "", "Rell Seas")
        t1, fil1 = await _ouvrir_avec_carte(b)
        dossier_avant = await Q.dossier(b.g, t1)
        refus = await Q.refuser(b.g, t1, b.fondateur, depuis="etape1")
        await laisser_finir()
        t2, fil2 = await _ouvrir_avec_carte(b)
        await _cliquer(b, Q.BoutonEtape1("e", t2), b.fondateur, fil2)
        eid = (await Q._suivi(b.g.id, t2))["envoi_id"]
        page1 = await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil2)
        modal = page1.response.modals[0]
        reponses = {int(q["rang"]): "réponse" for q in (await Q._envoi(eid))["questions"]}
        apres1 = await _soumettre(b, modal, b.candidat, reponses, fil2)
        modal2 = (await _cliquer(b, Q.BoutonRepondre(eid), b.candidat, fil2)).response.modals[0]
        fin = await _soumettre(b, modal2, b.candidat, reponses, fil2)
        return accueil, n, fil1, dossier_avant, refus, fil2, eid, modal, apres1, fin
    accueil, n, fil1, dossier_avant, refus, fil2, eid, modal, apres1, fin = asyncio.run(scenario())
    ta = textes_vue(accueil)
    assert "### Ahoy · Ahoy" in ta and f"Deux étapes, puis **{n} questions** · {n}-question quiz." in ta
    assert "**Les pages utiles**" in ta and "Toutes les réponses se trouvent sur le wiki" not in ta, \
        "le texte vidé disparaît, les liens restent"
    assert dossier_avant["message_refus_etape1"] == "Pas cette fois, moussaillon.\n-# Not this time.", \
        "la page montre avant de refuser le texte exact qui partira"
    assert refus[0] == 200
    message = textes_vue(_vues_du_fil(fil1)[-1])
    assert "Pas cette fois, moussaillon." in message and "Tes réponses ne correspondent pas" not in message
    carte = next(v for v in _vues_du_fil(fil2) if "À toi de jouer" in textes_vue(v))
    assert f"## À toi de jouer — {n} questions" in textes_vue(carte)
    assert libelles_boutons(carte) == ["J'y vais · Go"] and ids(carte) == [f"rq:rep:{eid}"], \
        "le libellé change, le bouton persistant reste le même"
    assert modal.title == "Page 1 sur 2" and "Écris ici" in _modal_textes(modal)
    assert "Gardée (1/2), la suite : 2." in apres1.texte() and ids(apres1.vues()[-1]) == [f"rq:pg:{eid}:2"]
    assert [x for v in apres1.vues() for x in libelles_boutons(v)] == ["Suite 2/2"]
    assert "Bien reçu, merci !" in fin.texte() and Q.MERCI.split("\n")[0] not in fin.texte()


# ═══════════════════════════════════════════════════════════════════════════════
#  T10 : les annonces et événements emploient les textes enregistrés
# ═══════════════════════════════════════════════════════════════════════════════

def _carte_de(env_, m_id):
    """La carte telle qu'elle est maintenant (sa dernière réécriture)."""
    reecrites = [kw["view"] for mid, kw in env_.infos.cartes if mid == m_id]
    return reecrites[-1] if reecrites else env_.infos.messages[0].kw["view"]


def test_T10_les_evenements_emploient_les_textes_enregistres(env, registre_textes):
    for cle, valeur in (("evenements.bouton.dispo", "Présent · Here"), ("evenements.bouton.peut_etre", "Je verrai"),
                        ("evenements.carte.lieu", "**Où** {lieu}"), ("evenements.carte.duree", "**Combien** {duree}"),
                        ("evenements.carte.disponibles", "Présents"), ("evenements.carte.sous_titre", "Sortie du clan"),
                        ("evenements.carte.rappels", "On vous le rappelle : {quand}"),
                        ("evenements.rappel.titre", "Hissez les voiles"),
                        ("evenements.rappel.texte", "{titre} arrive {quand}"),
                        ("evenements.horaire.titre", "Changement de cap"),
                        ("evenements.annulation.titre", "Sortie annulée"),
                        ("evenements.annulation.texte", "Pas de {titre} ce soir."),
                        ("evenements.avis.ok.fr", "Bien noté : **{choix}** !"),
                        ("evenements.bouton.voir", "La carte")):
        assert ecrire(cle, valeur)[0] == 200, cle
    e = evenement(env, rappels=[60], duree_min=90, mention="inscrits")
    st, apercu = api_ev(env, "clan/apercu", requete={"id": str(e["id"])})
    lignes = [ln["md"] for c in apercu["cartes"] for b in c["blocs"] for ln in b.get("lignes") or []]
    assert st == 200 and "**Où** Île du Crâne" in lignes, lignes
    assert "**Combien** 1 h 30" in lignes and "Sortie du clan" in lignes
    assert [x["label"] for c in apercu["cartes"] for b in c["blocs"] if b["type"] == "boutons" for x in b["boutons"]] == \
        ["Présent · Here", "Je verrai", "Pas disponible · Unavailable"], "l'aperçu du site = la carte de Discord"
    st, liste = api_ev(env, "clan/evenements")
    assert liste["libelles"]["evenements.bouton.dispo"] == "Présent · Here", "l'aperçu pendant la saisie suit aussi"
    assert not any(k.startswith("evenements.avis.") for k in liste["libelles"])
    r = publier(env, e)
    m = env.infos.messages[0]
    t = textes_vue(m.kw["view"])
    assert "Présent · Here" in t and "Disponible · Available" not in t and "On vous le rappelle : 1 h avant · before" in t
    #  Le clic : la réponse dit le bouton tel qu'il est écrit.
    membre = env.g.membre(31, env.role)
    i = inter(env, membre)
    courir(E.BoutonReponse(e["id"], "d").callback(i))
    assert textes_vue(i.suivis[-1][1]["view"]).startswith("Bien noté : **Présent** !")
    courir(laisser_finir())
    assert "**Présents — 1**" in textes_vue(_carte_de(env, m.id))
    #  Le rappel (une heure avant) : le titre et le texte réécrits.
    env.horloge["t"] = e["quand"] - 3600 + 5
    courir(E.tic([env.g]))
    rappel = textes_vue(env.infos.messages[-1].kw["view"])
    assert "Hissez les voiles" in rappel and f"Sortie en mer arrive <t:{e['quand']}:R>" in rappel and "La carte" in rappel
    #  L'annulation : le message dans le post.
    st, rep = api_ev(env, "clan/annuler", {"id": e["id"]})
    assert st == 200
    annulation = textes_vue(env.infos.messages[-1].kw["view"])
    assert "Sortie annulée" in annulation and "Pas de Sortie en mer ce soir." in annulation
    assert r["ok"]


def test_T10b_les_annonces_publiees_sont_rangees_a_part(env, registre_textes):
    assert ecrire("evenements.bouton.vu", "Lu · Read")[0] == 200
    a = api_ev(env, "clan/brouillon", {"type": "annonce", "titre": "Nouvelles règles", "texte": "Lisez-les.",
                                       "mention": "aucune"})[1]["element"]
    publier(env, a)
    assert "Lu · Read" in textes_vue(env.infos.messages[-1].kw["view"])
    e = evenement(env)
    publier(env, e)
    st, liste = api_ev(env, "clan/evenements")
    assert [x["titre"] for x in liste["publiees"]] == ["Nouvelles règles"] and liste["publiees_total"] == 1
    assert [x["titre"] for x in liste["a_venir"]] == ["Sortie en mer"] and liste["passes"] == []
    api_ev(env, "clan/annuler", {"id": a["id"]})
    st, liste = api_ev(env, "clan/evenements")
    assert liste["publiees"] == [] and [x["statut"] for x in liste["passes"]] == ["retire"], "retirée : dans les passés"


# ═══════════════════════════════════════════════════════════════════════════════
#  T11 – T12 : les métiers, renommer un rôle
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def banc_metiers(tmp_path, monkeypatch, registre_textes):
    b = BancMetiers(tmp_path, monkeypatch)
    #  Les rôles du faux serveur se renomment (comme `discord.Role.edit`) ; « refus_edit » : Discord refuse.
    renommes = []

    async def edit(self, *, name=None, reason=None):
        if getattr(self, "refus_edit", False):
            raise discord.HTTPException(Obj(status=403, reason="x"), "Missing Permissions")
        renommes.append((self.id, name))
        self.name = name
    monkeypatch.setattr(type(b.clan), "edit", edit, raising=False)
    b.renommes, b.journal_textes = renommes, registre_textes.journal
    return b


def _ecrire_puis_attendre(g, cle, valeur):
    """Écrire un texte et laisser tourner ce qu'il planifie (le guide du clan réécrit), dans la même boucle."""
    corps = {"cle": cle, "valeur": valeur, "version": textes.item(g, cle)["version"]}
    return dans_une_boucle(lambda: textes.ecrire(g, Obj(id=FONDATEUR), corps))


def test_T11_le_guide_du_clan_et_l_acceptation(banc_metiers):
    b = banc_metiers
    for cle, valeur in (("metiers.guide.titre", "Ton poste · Your post"),
                        ("metiers.guide.texte_auto", "Prends {combien} ({combien_en})."),
                        ("metiers.guide.liste", "Ton poste ?"), ("metiers.guide.aucun", "Aucun poste"),
                        ("metiers.carte.auto", "### Bienvenue {membre} !"), ("metiers.carte.bouton", "Au guide"),
                        ("metiers.mp_lien", "ton poste : {lien}")):
        assert _ecrire_puis_attendre(b.g, cle, valeur)[0] == 200, cle
    composants, signature = asyncio.run(metiers.section_guide(b.g, b.conf))
    t = " ".join(x.content for x in composants if isinstance(x, discord.ui.TextDisplay))
    assert "Ton poste · Your post" in t and "Prends jusqu'à **2** métiers (up to 2 jobs)." in t
    choix = composants[1].children[0].item
    assert choix.placeholder == "Ton poste ?" and choix.options[-1].label == "Aucun poste"
    #  Un texte du guide change : le guide se réécrit (planifié), et sa signature change.
    b.guides.clear()
    assert _ecrire_puis_attendre(b.g, "metiers.guide.titre", "Ton métier, matelot")[0] == 200
    assert b.guides == [1], "le guide du clan est réécrit quand un de ses textes change"
    assert asyncio.run(metiers.section_guide(b.g, b.conf))[1] != signature
    assert _ecrire_puis_attendre(b.g, "metiers.carte.bouton", "Vers le guide")[0] == 200
    assert b.guides == [1], "un texte hors du guide ne le réécrit pas"
    #  La carte de l'acceptation, et la ligne du message privé.
    b.conf["clan_posts"] = {"guide": {"id": 777, "ouverture": 778}}
    envois = []

    class Ticket:
        id = 77

        async def send(self, content=None, **kw):
            envois.append(kw)
    lien = asyncio.run(metiers.inviter_au_choix(b.g, Ticket(), b.kolax))
    vue = envois[-1]["view"]
    assert lien and "### Bienvenue <@7> !" in textes_vue(vue)
    assert libelles_boutons(vue) == ["Vers le guide"]
    assert asyncio.run(textes.texte(b.g.id, "metiers.mp_lien", lien=lien)) == f"ton poste : {lien}"


def test_T12_renommer_un_role_droits_refus_et_nom_garde(banc_metiers):
    b = banc_metiers
    g, chef = b.g, b.chef
    b.choisir(b.kolax, "cooking")                       # le rôle « Cuisinier » est créé et lié
    cuisinier = b.role_nomme("Cuisinier")
    assert cuisinier is not None and b.lien("cooking")[0] == cuisinier.id

    def renommer(role_id, nom):
        return dans_une_boucle(lambda: textes.renommer_role(g, chef, {"role_id": str(role_id), "nom": nom}))
    assert renommer(999, "X") == (404, {"erreur": "Ce rôle n'existe plus sur le serveur."})
    st, r = renommer(b.vip.id, "Grand VIP")
    assert st == 403 and "rattachés au clan" in r["erreur"], "un rôle ni lié ni rattaché ne se renomme pas d'ici"
    b.conf[metiers.CLE_RATTACHES] = [b.haut.id, b.integration.id, b.mod.id, b.officier.id]
    assert renommer(b.haut.id, "Plus haut")[0] == 400 and b.haut.name == "Au-dessus du bot", "au-dessus du bot"
    assert renommer(b.integration.id, "Musique")[0] == 400, "un rôle géré par une intégration"
    assert renommer(b.mod.id, "Gardien")[0] == 400, "un rôle à droits de modération : jamais depuis le site"
    assert renommer(cuisinier.id, "  ")[0] == 400 and renommer(cuisinier.id, "x" * 101)[0] == 400
    assert renommer(cuisinier.id, "@everyone")[0] == 400
    assert b.renommes == [], "aucun refus ne touche Discord"
    #  Le grade rattaché au clan se renomme ; Discord qui refuse est dit (502) et journalisé.
    st, r = renommer(b.officier.id, "Second")
    assert st == 200 and b.officier.name == "Second" and r["metiers"] == [] and metiers.CLE_NOMS not in b.conf
    b.officier.refus_edit = True
    assert renommer(b.officier.id, "Capitaine")[0] == 502 and b.officier.name == "Second"
    assert "[TEXTES][E5] rôle non renommé : Discord a refusé" in b.journal_textes
    #  Le rôle du métier : renommé, et ce nom servira s'il faut le recréer (et dans la liste du guide).
    b.guides.clear()
    st, r = renommer(cuisinier.id, "Maître-coq")
    assert st == 200 and cuisinier.name == "Maître-coq" and r["metiers"] == ["cooking"]
    assert r["_journal"] == "Rôle « Cuisinier » renommé « Maître-coq »" and r["message"] == "Rôle renommé « Maître-coq »."
    assert b.conf[metiers.CLE_NOMS] == {"cooking": "Maître-coq"}
    assert b.guides == [1], "le guide du clan suit (sa liste porte le nom du rôle)"
    assert asyncio.run(metiers.options_selecteur(g))[0]["label"] == "Maître-coq · Cooking"
    assert renommer(cuisinier.id, "Maître-coq")[1]["deja"], "le même nom : rien à faire"
    #  Le rôle supprimé sur Discord : recréé sous le nom choisi.
    del g._roles[cuisinier.id]
    role, quoi = asyncio.run(metiers.role_du_metier(g, "cooking", creer=True, auteur=chef))
    assert quoi == "cree" and role.name == "Maître-coq"
    #  Sans la permission « Gérer les rôles » : refusé.
    g.me.guild_permissions = discord.Permissions.none()
    assert renommer(role.id, "Cuistot") == (403, {"erreur": "Il me manque la permission « Gérer les rôles »."})


# ═══════════════════════════════════════════════════════════════════════════════
#  T16 – T20 : « même ce qui existe déjà » (le fondateur, 26/10)
# ═══════════════════════════════════════════════════════════════════════════════

def test_T16_la_carte_de_l_equipe_ses_boutons_et_le_formulaire_du_refus(tmp_path, monkeypatch, registre_textes):
    monkeypatch.setattr(Q, "AVIS_S", 0)
    for cle, valeur in (("recrutement.equipe.decision", "### À toi de trancher\n{combien}par défaut."),
                        ("recrutement.equipe.bouton.envoyer", "Lancer l'étape 2"),
                        ("recrutement.equipe.bouton.refuser", "Recaler"),
                        ("recrutement.equipe.envoye", "### C'est parti\n{par} {quand} : {questions}."),
                        ("recrutement.equipe.bouton.ouvrir", "Voir sur le site"),
                        ("recrutement.equipe.refus.titre", "Recaler ce candidat"),
                        ("recrutement.equipe.refus.note", "Pourquoi ?"),
                        ("recrutement.equipe.refus.exemple", "Réponses vides"),
                        ("recrutement.equipe.reserve", "Pas pour toi, matelot.")):
        assert ecrire(cle, valeur)[0] == 200, cle
    b = BancQuestionnaire(tmp_path)

    async def scenario():
        await b.preparer()
        tid, fil = await _ouvrir_avec_carte(b)
        carte = _vues_du_fil(fil)[-1]
        intrus = await _cliquer(b, Q.BoutonEtape1("e", tid), b.candidat, fil)
        refus = await _cliquer(b, Q.BoutonEtape1("r", tid), b.fondateur, fil)
        await _cliquer(b, Q.BoutonEtape1("e", tid), b.fondateur, fil)
        await laisser_finir()
        return tid, fil, carte, intrus, refus, await Q._suivi(b.g.id, tid)
    tid, fil, carte, intrus, refus, s = asyncio.run(scenario())
    assert "### À toi de trancher\n10 questions, par défaut." in textes_vue(carte)
    assert libelles_boutons(carte) == ["Lancer l'étape 2", "Choisir sur le site", "Recaler"]
    assert ids(carte) == [f"rq:e1:e:{tid}", f"rq:e1:s:{tid}", f"rq:e1:r:{tid}"], "les boutons persistants restent"
    assert "Pas pour toi, matelot." in intrus.texte() and Q.RESERVE not in intrus.texte()
    modal = refus.response.modals[0]
    assert modal.title == "Recaler ce candidat"
    assert "Pourquoi ?" in _modal_textes(modal) and "Réponses vides" in _modal_textes(modal)
    vue_envoyee = [kw["view"] for mid, kw in fil.cartes if mid == s["carte_id"]][-1]
    envoyee = textes_vue(vue_envoyee)
    assert "### C'est parti" in envoyee and f"<@{FONDATEUR_Q}>" in envoyee and "**10 questions**." in envoyee
    assert libelles_boutons(vue_envoyee) == ["Voir sur le site"]
    #  Les textes d'origine, mot pour mot, sans rien d'enregistré (un autre serveur).
    t0 = textes_vue(Q.carte_etape1(7, nombre=3, guild_id=2))
    assert "### Étape 1 · décision" in t0 and "(3 questions, la sélection par défaut du site)" in t0


def test_T17_les_reponses_au_choix_du_metier(banc_metiers):
    b = banc_metiers
    for cle, valeur in (("metiers.avis.reserve", "Le clan d'abord, matelot."),
                        ("metiers.avis.trop", "Pas plus de {n}, matelot."),
                        ("metiers.choix.note_auto", "Va pour {metiers} ({metiers_en})."),
                        ("metiers.choix.aucun_auto", "Plus de métier, c'est noté.")):
        assert ecrire(cle, valeur, g=b.g)[0] == 200, cle
    assert avis_metier(b.choisir(b.intrus, "cooking")).startswith("Le clan d'abord, matelot.")
    assert avis_metier(b.choisir(b.kolax, "cooking", "thieving", "fishing")).startswith("Pas plus de 2, matelot.")
    assert avis_metier(b.choisir(b.kolax, "cooking")).startswith("Va pour **Cuisinier** (Cooking).")
    assert avis_metier(b.choisir(b.kolax, metiers.AUCUN)).startswith("Plus de métier, c'est noté.")
    #  Ce qui n'a pas été réécrit garde le texte d'origine.
    assert "Rien n'a été choisi" in avis_metier(b.choisir(b.kolax))


def test_T18_le_listing_et_l_annonce_des_metiers(registre_textes):
    for cle, valeur in (("evenements.liste.titre.listing", "L'équipage au complet"),
                        ("evenements.liste.resume_listing", "{membres} matelots, rangés par {groupe}"),
                        ("evenements.liste.sans.grade", "Mousses sans grade"),
                        ("evenements.liste.suite", "{titre} (suite {page}/{pages})"),
                        ("evenements.liste.resume_metiers", "{membres} matelots · {metiers} métier(s)"),
                        ("evenements.liste.personne", "Personne encore.")):
        assert ecrire(cle, valeur)[0] == 200, cle
    membres = [Obj(id=10 ** 17 + k, display_name=f"Matelot {k}") for k in range(900)]
    fiches = {m.id: {"metiers": ["cooking"], "grade": "capitaine" if k % 2 else ""} for k, m in enumerate(membres)}
    catalogue = {"metier": {"cooking": {"nom": "Cuisinier", "nom_en": "Cooking"}},
                 "grade": {"capitaine": {"nom": "Capitaine"}}}
    eq = {"membres": membres, "fiches": fiches, "catalogue": catalogue}

    def liste(type_, eq_):
        e = {"id": 5, "guild_id": 1, "type": type_, "statut": "brouillon", "publie": 0,
             "valeurs": {"titre": "", "texte": "", "groupement": "grade", "champs": [], "mention": "aucune"}}
        cartes = E._cartes_liste(e, eq_, "")
        return cartes, [ln["md"] for c in cartes for b in c["blocs"] for ln in b.get("lignes") or []]
    cartes, lignes = liste("listing", eq)
    assert "L'équipage au complet" in lignes and "900 matelots, rangés par grade" in lignes
    assert "Mousses sans grade — 450" in lignes, "le groupe des membres sans grade"
    assert len(cartes) > 1 and f"L'équipage au complet (suite 2/{len(cartes)})" in lignes, "la suite d'une longue liste"
    _c, lignes = liste("metiers", eq)
    assert "Annonce des métiers" in lignes and "900 matelots · 1 métier(s)" in lignes, \
        "le titre d'origine, le résumé réécrit"
    _c, lignes = liste("metiers", {"membres": [], "fiches": {}, "catalogue": catalogue})
    assert "Personne encore." in lignes


def test_T19_le_guide_du_clan_a_la_sauce_de_la_direction(registre_textes, monkeypatch):
    for cle, valeur in (("guide.bienvenue", "**Ahoy !** Le clan se retrouve ici."),
                        ("guide.infos.texte", "### 📢 Le tableau\nÀ lire en premier."),
                        ("guide.infos.bouton", "Lire le tableau"),
                        ("guide.chat.vocal", "Le vocal : {salon}"),
                        ("guide.ticket.bouton", "Ouvrir un ticket"),
                        ("guide.securite", "-# Jamais ton mot de passe.")):
        assert ecrire(cle, valeur)[0] == 200, cle
    posts = {k: {"id": 100 + n} for n, k in enumerate(("guide", "infos", "annonces", "chat", "economie", "trade",
                                                         "taverne"))}
    monkeypatch.setattr(ZN, "_vocal_clan", lambda g_, c, contexte="clan": Obj(id=5) if contexte == "clan" else None)
    monkeypatch.setattr(ZN, "_ticket", lambda g_: Obj(id=6, jump_url="https://discord.com/channels/1/6"))
    monkeypatch.setattr(ZN, "_boutons_langue", None)
    vue, signature = ZN.vue_guide_clan(G1, {}, posts, None)
    t = textes_vue(vue)
    assert "**Ahoy !** Le clan se retrouve ici." in t and "### 📢 Le tableau\nÀ lire en premier." in t
    assert "Le chat du clan, entre nous. Le vocal : <#5>." in t and "-# Jamais ton mot de passe." in t
    assert "Bienvenue dans l'équipage" not in t and "Personne du staff" not in t
    assert libelles_boutons(vue) == ["Lire le tableau", "Lire · Read", "Ouvrir · Open", "Ouvrir · Open",
                                     "Échanger · Trade", "Entrer · Enter", "Ouvrir un ticket"]
    #  Un texte changé change la signature (le guide posté est réécrit) ; le même texte, la même signature.
    assert ZN.vue_guide_clan(G1, {}, posts, None)[1] == signature
    assert ecrire("guide.taverne.bouton", "Trinquer")[0] == 200
    assert ZN.vue_guide_clan(G1, {}, posts, None)[1] != signature
    #  Enregistrer un texte du guide le fait réécrire ; une rafale de changements : une seule réécriture.
    appels = []

    async def assurer(g):
        appels.append(g.id)
        return True
    monkeypatch.setattr(ZN, "assurer_guide_clan", assurer)
    monkeypatch.setattr(ZN, "GUIDE_TEXTE_APRES_S", 0.0)
    monkeypatch.setattr(ZN, "_guides_clan_prevus", {})
    monkeypatch.setattr(ZN, "_cfg", lambda gid: {})
    corps = {"cle": "guide.securite", "valeur": "-# Garde ton mot de passe.",
             "version": textes.item(G1, "guide.securite")["version"]}
    assert dans_une_boucle(lambda: textes.ecrire(G1, Obj(id=FONDATEUR), corps))[0] == 200
    assert appels == [1], "le guide du clan est réécrit quand un de ses textes change"

    async def rafale():
        for _ in range(3):
            ZN._texte_du_guide_change(G1, "guide.securite")
        await laisser_finir()
    asyncio.run(rafale())
    assert appels == [1, 1], "trois changements d'affilée : une seule réécriture"
    assert dans_une_boucle(lambda: textes.ecrire(G1, Obj(id=FONDATEUR), {
        "cle": "metiers.carte.bouton", "valeur": "Au guide", "version": 0}))[0] == 200
    assert appels == [1, 1], "un texte hors du guide : rien"


def test_T20_les_sous_onglets_renommes_et_une_famille_nommee(registre_textes):
    st, r = ecrire("site.sous.equipage.annonces.publiees", "Déjà parues")
    assert st == 200 and textes.valeurs_site(1)["site.sous.equipage.annonces.publiees"] == "Déjà parues"
    assert ecrire("site.fiche.onglet.chrono", "Fil des jours")[0] == 200
    assert ecrire("site.sous.port.salons.droits", "x" * 31)[0] == 400, "un onglet reste court (30 au plus)"
    assert set(textes.valeurs_site(1)) == {"site.sous.equipage.annonces.publiees", "site.fiche.onglet.chrono"}
    #  Une autre équipe déclare ses textes dans le registre, sous sa propre famille, nommée et placée.
    textes.nommer_groupe("equipage_site", "Le site de l'équipage", 50)
    textes.declarer("equipage_site.accueil.titre", "Bienvenue à bord", groupe="equipage_site", titre="Le titre",
                    max_=80, lignes=False)
    familles = [(x["cle"], x["nom"]) for x in textes.groupes(G1)]
    assert familles[-1] == ("equipage_site", "Le site de l'équipage") and familles[-2][0] == "site"
    with pytest.raises(ValueError):
        textes.nommer_groupe("Mauvais Nom", "x")


def test_T21_un_texte_en_cours_de_modification_ailleurs_est_refuse_423(tmp_path, monkeypatch, registre_textes):
    """Le fondateur modifie « Merci, après ses réponses » (il tient « texte:recrutement.merci ») : la direction ne peut
    ni l'écrire ni le remettre à l'origine (423, qui le tient) — un autre texte, oui ; sa file hors ligne attend, puis
    passe quand il est libéré."""
    from test_direct import Monde as MondeDirect, _socket, _attendre, BASE as BASE_DIRECT
    monde = MondeDirect(tmp_path, monkeypatch)
    tableau.monter(textes)
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)
    ecrire_a = dict(a, **{"X-Tableau": "1", "Origin": BASE_DIRECT})
    ecrire_b = dict(b, **{"X-Tableau": "1", "Origin": BASE_DIRECT})
    objet = "texte:recrutement.merci"

    async def scenario(c):
        out = {}
        wa = await _socket(c, a, page="capitainerie/textes")
        wb = await _socket(c, b, page="capitainerie/textes")
        await wa.send_json({"t": "prendre", "o": objet, "ti": "le texte « Merci, après ses réponses »"})
        await _attendre(wa, "pris")

        async def poster(chemin, corps, entetes):
            r = await c.post("/tableau/espace/api/" + chemin, json=corps, headers=entetes)
            return r.status, await r.json()
        out["b"] = await poster("texte", {"cle": "recrutement.merci", "valeur": "Merci !", "version": 0}, ecrire_b)
        out["b_defaut"] = await poster("texte/defaut", {"cle": "recrutement.merci"}, ecrire_b)
        out["b_autre"] = await poster("texte", {"cle": "recrutement.deja", "valeur": "Déjà reçu.", "version": 0}, ecrire_b)
        out["a"] = await poster("texte", {"cle": "recrutement.merci", "valeur": "Merci, matelot.", "version": 0}, ecrire_a)
        op = {"op_id": "op-textes-0423", "api": "texte",
              "corps": {"cle": "recrutement.merci", "valeur": "Merci (hors ligne).", "version": 1}}
        r = await c.post("/tableau/espace/sync", json={"ops": [op]}, headers=ecrire_b)
        out["sync"] = (await r.json())["resultats"][0]
        await wa.send_json({"t": "lacher", "o": objet})
        await _attendre(wb, "libre", objet=objet)
        r = await c.post("/tableau/espace/sync", json={"ops": [op]}, headers=ecrire_b)
        out["sync_apres"] = (await r.json())["resultats"][0]["status"]
        await wa.close()
        await wb.close()
        return out
    out = monde.http(scenario)
    st, corps = out["b"]
    assert st == 423 and corps["verrou"] == {"objet": objet, "par": str(FONDATEUR), "nom": "GoRipe"}, out["b"]
    assert corps["erreur"] == "En cours de modification par GoRipe."
    assert out["b_defaut"][0] == 423, "« Revenir au texte d'origine » aussi"
    assert out["b_autre"][0] == 200 and out["a"][0] == 200, "un autre texte, ou celui qui le tient : l'écriture passe"
    assert out["sync"]["status"] == 423, "la file hors ligne attend que le texte soit libre"
    assert out["sync_apres"] == 200
    assert textes.item(monde.g, "recrutement.merci")["valeur"] == "Merci (hors ligne)."
    #  La page : l'éditeur prend « texte:<clé> » (lecture seule s'il est pris) ; la liste porte le cadenas.
    page = (RACINE / "site" / "textes.js").read_text(encoding="utf-8")
    assert 'protegerEditeur(p, "texte:" + t.cle,' in page and 'avecVerrou(h("li", { classe: "texte-ligne"' in page
    assert textes.ROUTES_SITE["texte"]["verrou"]({"cle": "a.b"}) == "texte:a.b"
    assert textes.ROUTES_SITE["texte/defaut"]["verrou"] is textes.ROUTES_SITE["texte"]["verrou"]


# ═══════════════════════════════════════════════════════════════════════════════
#  T13 – T15 : les noms du site, les clés, le câblage
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_les_noms_du_site_sont_ceux_de_la_page():
    noyau = (RACINE / "site" / "noyau.js").read_text(encoding="utf-8")
    cats = re.findall(r'cle: "(\w+)", titre: "([^"]+)", court: "([^"]+)", sous: "([^"]+)"', noyau)
    rubs = re.findall(r'\{ cle: "(\w+)", titre: "([^"]+)", icone: "\w+", phrase: "([^"]+)" \}', noyau)
    attendu = [(c, t, court, s) for c, t, court, s, _r in textes.SITE_CATEGORIES]
    assert cats == attendu, "les trois catégories : mêmes clés, mêmes noms que la page"
    assert rubs == [r for *_x, rs in textes.SITE_CATEGORIES for r in rs], "chaque rubrique : même nom, même phrase"
    affiche = (RACINE / "site" / "affiche.js").read_text(encoding="utf-8")
    statuts = dict(re.findall(r'(\w+): "([^"]+)"', affiche[affiche.index("STATUTS_AFFICHE = "):].split("\n")[0]))
    tampons = dict(re.findall(r'(\w+): "([^"]+)"', affiche[affiche.index("const TAMPONS = "):].split("\n")[0]))
    assert statuts == dict(textes.SITE_STATUTS) and tampons == dict(textes.SITE_TAMPONS)
    for c, *_x, rs in textes.SITE_CATEGORIES:
        for champ in ("titre", "court", "sous"):
            assert textes.declare(f"site.cat.{c}.{champ}")
        for r, *_y in rs:
            assert textes.declare(f"site.rub.{c}.{r}.titre") and textes.declare(f"site.rub.{c}.{r}.phrase")
    #  Le nom choisi suit partout : les catégories et les rubriques lisent leurs noms par `libelle`.
    assert "export function libelle(" in noyau and "nommer(c, \"site.cat.\" + c.cle" in noyau
    assert 'nomme("site.affiche.statut."' in affiche and 'nomme("site.affiche.tampon."' in affiche
    #  Les sous-onglets et les onglets de la fiche : les mêmes clés et les mêmes noms que la page, lus par `libelle`.
    vus = []
    for f in ("discord.js", "recrutement.js", "annonces.js", "fiche.js"):
        src = (RACINE / "site" / f).read_text(encoding="utf-8")
        for prefixe, corps in re.findall(r'nommerOnglets\("([a-z.]+)", \[(.*?)\]\);', src, re.S):
            vus.append((prefixe, [(k.replace("-", "_"), nom)
                                  for k, nom in re.findall(r'\["([\w-]+)", "([^"]+)", "\w+"\]', corps)]))
    attendu = [(f"site.sous.{c}.{r}", list(o)) for c, r, o in textes.SITE_SOUS] + \
        [("site.fiche.onglet", list(textes.SITE_FICHE))]
    assert sorted(vus) == sorted(attendu), vus
    for prefixe, onglets in attendu:
        for k, _nom in onglets:
            assert textes.declare(f"{prefixe}.{k}"), (prefixe, k)
    assert "export function nommerOnglets(" in noyau


def _cles_appelees(source: str, noms) -> set:
    """Les clés du registre écrites dans les appels `noms(…)` d'une source (ternaires comprises)."""
    cles = set()
    for m in re.finditer(r"\b(?:%s)\(" % "|".join(map(re.escape, noms)), source):
        i = j = m.end()
        n = 1
        while j < len(source) and n:
            n += {"(": 1, ")": -1}.get(source[j], 0)
            j += 1
        cles |= set(re.findall(r"[\"']((?:recrutement|evenements|metiers|guide|site)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)[\"']",
                               source[i:j]))
    return cles


def test_T14_chaque_cle_ecrite_dans_le_code_est_declaree():
    """Une clé mal écrite donnerait la clé elle-même sur Discord : chaque appel est vérifié ici."""
    appels = {"questionnaire.py": ("_t", "texte"), "evenements.py": ("_t", "texte"), "metiers.py": ("_t", "texte"),
              "zones.py": ("_t",), "bot.py": ("texte",), "site/annonces.js": ("L",),
              "site/recrutement.js": ("messageAuto", "modifierTexte")}
    par_fichier = {f: _cles_appelees((RACINE / f).read_text(encoding="utf-8"), noms) for f, noms in appels.items()}
    inconnues = {c: f for f, cles in par_fichier.items() for c in cles if not textes.declare(c)}
    assert not inconnues, inconnues
    assert len(set().union(*par_fichier.values())) >= 90
    assert all(par_fichier.values()), {f: len(c) for f, c in par_fichier.items()}


def test_T15_cablage_bot_site_local_et_page():
    assert "import textes" in SRC
    boot = ast.unparse(next(n for n in ARBRE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_activite_boot"))
    etape = boot[boot.index("with _Etape('textes'):"):]
    etape = etape[:etape.index("with _Etape(", 10)]
    for morceau in ("textes.setup(get_db=get_db, log=print)", "await textes.init_db()", "tableau.monter(textes)"):
        assert morceau in etape, morceau
    assert boot.index("with _Etape('textes'):") < boot.index("with _Etape('questionnaire'):"), \
        "les textes sont chargés avant les modules qui posent des cartes"
    decision = ast.unparse(next(n for n in ARBRE.body if getattr(n, "name", "") == "_decision_recrutement"))
    assert "textes.texte(g.id, 'recrutement.fermeture.acceptee' if accepte else 'recrutement.fermeture.refusee')" in decision
    assert "textes.texte(g.id, 'metiers.mp_lien', lien=guide)" in decision
    local = (RACINE / "outils" / "site_local.py").read_text(encoding="utf-8")
    assert "tableau.monter(textes)" in local and "/tableau/demo/discord" in local, "le site local et son faux Discord lu"
    for f in ("bot.py", "tableau.py", "health_server.py", "affiches.py", "textes.py"):
        assert "/tableau/demo" not in (RACINE / f).read_text(encoding="utf-8"), f
    sw = (RACINE / "site" / "sw.js").read_text(encoding="utf-8")
    page = (RACINE / "site" / "index.html").read_text(encoding="utf-8")
    assert '"textes.js"' in sw and '"textes.css"' in sw and "s/textes.css?v={{V}}" in page, "la page hors ligne"
    hl = (RACINE / "site" / "hors_ligne.js").read_text(encoding="utf-8")
    assert '"texte", "texte/defaut"' in hl and '"type", "texte"]' in hl, "une modification gardée hors ligne repart"
