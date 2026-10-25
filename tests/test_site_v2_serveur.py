"""Site v2 « La Capitainerie » (25/10/2026) — le serveur, de bout en bout.

V1 le registre des adresses (`monter`) vérifie tout avant de brancher. V2 la porte de chaque adresse :
session, méthode, origine, taille, corps, erreurs génériques, journal, ETag. V3 cadence et limites graves.
V4 un corps envoyé par morceaux est borné. V5 les fichiers de `site/` : types, cache, aucun pas hors du
dossier. V6 la page v2 (CSP, empreinte) et le service worker. V7 les images refaites (Pillow), les
fichiers piégés refusés. V8 la synchronisation hors ligne, appliquée une seule fois. V9-V10 le catalogue
RELL Seas (départ, modifications, conflits, validation). V11 les affiches. V12 les portraits Roblox
(serveur seulement, CDN seulement). V13 les rôles des métiers. V14 le nettoyage. V15 le câblage dans
bot.py. V16 l'entrée de démonstration n'existe que dans `outils/site_local.py`. V17 adresses et en-têtes."""
from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import io
import json
import os
import shutil
import time
from pathlib import Path

import aiosqlite
import discord
import pytest

import affiches
import health_server
import recrutements
import registre
import tableau
import transcript_store
from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
EXEMPLE = Path(__file__).resolve().parent / "donnees" / "rell_catalogue_exemple.json"
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
TETE = frozenset({FONDATEUR, DIRECTION})
ORIGINE = {"X-Tableau": "1", "Origin": "https://bot.exemple", "Sec-Fetch-Site": "same-origin"}
CSP_SPEC = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data: blob: "
            "https://cdn.discordapp.com https://*.discordapp.net; media-src 'self' https://cdn.discordapp.com "
            "https://*.discordapp.net; connect-src 'self'; worker-src 'self'; manifest-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le faux serveur et le site branché comme dans bot.py
# ═══════════════════════════════════════════════════════════════════════════════

class Role:
    def __init__(self, rid, nom, position, permissions=None, managed=False, couleur=0):
        self.id, self.name, self.position, self.managed = rid, nom, position, managed
        self.permissions = permissions or discord.Permissions.none()
        self.colour = discord.Colour(couleur)
        self.members = []

    def is_default(self):
        return self.position == 0


class Membre:
    def __init__(self, uid, nom, *roles):
        self.id, self.display_name, self.name, self.bot, self.joined_at = uid, nom, nom.lower(), False, None
        self.roles = list(roles)
        url = f"https://cdn.discordapp.com/avatars/{uid}.png"
        self.display_avatar = Obj(url=url, with_size=lambda _n: Obj(url=url))
        self.ajouts, self.retraits = [], []

    async def add_roles(self, *roles, reason=None):
        self.ajouts.append([r.id for r in roles])
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.retraits.append([r.id for r in roles])
        self.roles = [r for r in self.roles if r not in roles]


class Serveur:
    def __init__(self):
        self.id, self.name, self.owner_id, self.icon = 1, "GoRP SEA", FONDATEUR, None
        self.default_role = Role(1, "@everyone", 0)
        self._roles = {1: self.default_role}
        self.membres, self.crees = {}, []
        self.me = Obj(id=999, top_role=Role(2, "GoRP Bot", 50), guild_permissions=discord.Permissions(manage_roles=True))

    roles = property(lambda self: list(self._roles.values()))
    members = property(lambda self: list(self.membres.values()))

    def role(self, rid, nom, position, **kw):
        self._roles[rid] = Role(rid, nom, position, **kw)
        return self._roles[rid]

    def get_role(self, rid):
        return self._roles.get(int(rid or 0))

    def get_member(self, uid):
        return self.membres.get(int(uid or 0))

    async def create_role(self, **kw):
        self.crees.append(kw)
        return self.role(500 + len(self.crees), kw["name"], 3)


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


class Site:
    """Le site comme dans bot.py : la tête seule entre et agit ; les affiches branchées par `monter`."""

    def __init__(self, tmp_path, monkeypatch, peut_agir=None):
        self.tmp, self.journal_bot, self.alertes = tmp_path, [], []
        self.get_db = get_db = _base(tmp_path / "site.db")
        self.g = Serveur()
        for uid, nom in ((FONDATEUR, "GoRipe"), (DIRECTION, "Direction"), (7, "Kolax"), (8, "Mira"), (9, "Intrus")):
            self.g.membres[uid] = Membre(uid, nom)
        self.conf = {}

        async def cfg(_g):
            return self.conf

        async def alerte(g, m, raison, suspendu=True):
            self.alertes.append((m.id, raison, suspendu))

        def tete(g, m, c=None):
            return m is not None and (m.id in TETE or (peut_agir is not None and m.id in peut_agir))
        monkeypatch.setattr(tableau, "ROUTES", {})
        monkeypatch.setattr(tableau, "REGLES", dict(tableau.REGLES))
        monkeypatch.setattr(tableau, "_SOURCES_MEDIAS", [])
        monkeypatch.setattr(tableau, "RACINE_DONNEES", tmp_path / "donnees")
        monkeypatch.setattr(tableau, "SITE", tmp_path / "site")
        monkeypatch.setattr(transcript_store, "_BASE_DIR", str(tmp_path / "transcripts"))
        tableau._statiques.clear()
        tableau._page_site.clear()
        tableau._cache_empreinte.update(signature=None, v="", vu=0.0)
        registre.setup(get_db=get_db, log=lambda *a: None)
        registre._derniers.clear()
        tableau.setup(bot=Obj(get_guild=lambda gid: self.g if gid == 1 else None, user=Obj(id=999)), cle="k",
                      base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=None, autorise_membre=tete,
                      direction=tete, tete=TETE, alerte_securite=alerte, log=self.journal_bot.append)
        affiches.setup(get_db=get_db, log=self.journal_bot.append)
        recrutements.setup(get_db=get_db, cfg=cfg, db_set=None, salon=None, role=lambda g, c: None, panneaux=None,
                           log=lambda *a: None)

        async def preparer():
            await registre.init_db()
            await tableau.init_db()
            await affiches.init_db()
            await recrutements.init_db()
        asyncio.run(preparer())
        tableau.monter(affiches)

    def session(self, uid=FONDATEUR) -> str:
        return asyncio.run(tableau._ouvrir_session(1, uid, int(time.time()) + 3600))

    def biscuit(self, uid=FONDATEUR, origine=True) -> dict:
        h = {"Cookie": f"{tableau.COOKIE}={self.session(uid)}"}
        return dict(h, **ORIGINE) if origine else h

    def http(self, scenario):
        from aiohttp.test_utils import TestClient, TestServer

        async def lancer():
            async with TestClient(TestServer(health_server.construire_app())) as client:
                return await scenario(client)
        return asyncio.run(lancer())

    def catalogue(self):
        return asyncio.run(affiches.charger_depart(EXEMPLE))

    def journal(self):
        return asyncio.run(registre.lire(1, 500))

    def sql(self, requete, args=()):
        async def lire():
            async with self.get_db() as db:
                async with db.execute(requete, args) as cur:
                    return await cur.fetchall()
        return asyncio.run(lire())

    def ecrire(self, requete, args=()):
        async def faire():
            async with self.get_db() as db:
                await db.execute(requete, args)
                await db.commit()
        asyncio.run(faire())


@pytest.fixture
def site(tmp_path, monkeypatch):
    return Site(tmp_path, monkeypatch)


async def _json(r):
    return r.status, json.loads(await r.text())


def _png(largeur=40, hauteur=30, couleur=(142, 42, 36), mode="RGB", format_="PNG", **kw) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new(mode, (largeur, hauteur), couleur).save(b, format_, **kw)
    return b.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ═══════════════════════════════════════════════════════════════════════════════
#  V1 — le registre des adresses
# ═══════════════════════════════════════════════════════════════════════════════

def test_V1_monter_verifie_tout_avant_de_brancher(monkeypatch):
    monkeypatch.setattr(tableau, "ROUTES", {})
    monkeypatch.setattr(tableau, "REGLES", dict(tableau.REGLES))
    monkeypatch.setattr(tableau, "_SOURCES_MEDIAS", [])

    async def lire(g, auteur, requete, corps):
        return 200, {}

    async def ecrire(g, auteur, requete, corps):
        return 200, {}
    mauvaises = [
        {"Mauvais Nom": {"methode": "GET", "fn": lire}},
        {"a/../b": {"methode": "GET", "fn": lire}},
        {"x": {"methode": "DELETE", "fn": lire}},
        {"x": {"methode": "GET", "fn": "pas une fonction"}},
        {"x": {"methode": "GET", "fn": lire, "ecriture": True}},
        {"x": {"methode": "POST", "fn": ecrire, "ecriture": False, "hors_ligne": True}},
        {"x": {"methode": "POST", "fn": ecrire, "corps_max": -1}},
        {"x": {"methode": "POST", "fn": ecrire, "corps_max": 50 * 1024 * 1024}},
        {"x": {"methode": "POST", "fn": ecrire, "grave": "tout"}},
        {"x": [{"methode": "GET", "fn": lire}, {"methode": "GET", "fn": lire}]},
        {"media": {"methode": "POST", "fn": ecrire}},          # une adresse de tableau.py
        {"ok": {"methode": "GET", "fn": lire}, "nettoyage": {"methode": "GET", "fn": lire}},
    ]
    for table in mauvaises:
        with pytest.raises(ValueError):
            tableau.monter(table)
        assert tableau.ROUTES == {}, f"rien n'est branché quand une seule adresse est fausse : {table}"
    assert tableau.monter({"a/b": [{"methode": "GET", "fn": lire}, {"methode": "POST", "fn": ecrire, "hors_ligne": True}]}) == 2
    assert tableau.monter({"a/b": [{"methode": "GET", "fn": lire}]}) == 1, "rebrancher la même fonction ne change rien"

    async def autre(g, auteur, requete, corps):
        return 200, {}
    with pytest.raises(ValueError, match="double"):
        tableau.monter({"a/b": {"methode": "POST", "fn": autre}})
    d = tableau.ROUTES["a/b"]["POST"]
    assert (d["ecriture"], d["hors_ligne"], d["corps_max"], d["grave"]) == (True, True, tableau.CORPS_DEFAUT, None)
    #  Un module : ses adresses, ses règles de nettoyage et ses images utilisées.

    class Module:
        ROUTES_SITE = {"m/x": {"methode": "GET", "fn": lire}}
        REGLES_NETTOYAGE = [{"cle": "m_regle", "nom": "Règle M", "quoi": "…", "garde_jours": 10, "min": 5, "max": 20,
                             "fn": ecrire}]

        @staticmethod
        async def medias_utilises(gid):
            return set()
    tableau.monter(Module)
    assert "m/x" in tableau.ROUTES and tableau.REGLES["m_regle"]["max"] == 20
    assert Module.medias_utilises in tableau._SOURCES_MEDIAS

    class Pirate:
        ROUTES_SITE = {}
        REGLES_NETTOYAGE = [{"cle": "journal", "garde_jours": 1, "min": 1, "max": 1}]
    with pytest.raises(ValueError):
        tableau.monter(Pirate)  # une règle de tableau.py ne se remplace pas
    for regle in ({"cle": "r", "garde_jours": 5, "min": 6, "max": 9}, {"cle": "r", "garde_jours": True, "min": 0, "max": 9}):
        with pytest.raises(ValueError):
            tableau._normaliser_regle(regle)


# ═══════════════════════════════════════════════════════════════════════════════
#  V2 — la porte de chaque adresse
# ═══════════════════════════════════════════════════════════════════════════════

def test_V2_adresses_portes_erreurs_journal_et_etag(site):
    appels = []

    async def plante(g, auteur, requete, corps):
        raise RuntimeError("chemin secret /data/bot.db")

    async def mal_formee(g, auteur, requete, corps):
        return "oui"

    async def note(g, auteur, requete, corps):
        appels.append((auteur.id, requete, corps))
        return 200, {"ok": True, "_journal": {"texte": "Essai noté", "membre_id": 7, "detail": "détail"},
                     "_cache": "jamais vu"}

    async def lire(g, auteur, requete, corps):
        appels.append(("lu", requete))
        return 200, {"valeur": 42}
    tableau.monter({"t/plante": {"methode": "POST", "fn": plante}, "t/mal": {"methode": "GET", "fn": mal_formee},
                    "t/note": {"methode": "POST", "fn": note}, "t/lire": {"methode": "GET", "fn": lire}})
    avec = site.biscuit()
    sans_origine = site.biscuit(origine=False)

    async def scenario(c):
        out = {}
        out["anonyme"] = await _json(await c.get("/tableau/espace/api/t/lire"))
        out["inconnue"] = await _json(await c.get("/tableau/espace/api/t/rien", headers=avec))
        out["inconnue_anonyme"] = (await c.get("/tableau/espace/api/t/rien")).status
        r = await c.get("/tableau/espace/api/t/note", headers=avec)
        out["methode"] = (r.status, r.headers.get("Allow"))
        out["sans_entete"] = (await c.post("/tableau/espace/api/t/note", json={}, headers=sans_origine)).status
        out["croise"] = (await c.post("/tableau/espace/api/t/note", json={},
                                      headers=dict(avec, **{"Sec-Fetch-Site": "cross-site"}))).status
        out["autre_site"] = (await c.post("/tableau/espace/api/t/note", json={},
                                          headers=dict(avec, Origin="https://pirate.exemple"))).status
        out["trop_gros"] = (await c.post("/tableau/espace/api/t/note", data="x" * (tableau.CORPS_DEFAUT + 1),
                                         headers=avec)).status
        out["illisible"] = (await c.post("/tableau/espace/api/t/note", data="{pas du json", headers=avec)).status
        out["liste"] = (await c.post("/tableau/espace/api/t/note", data="[1, 2]", headers=avec)).status
        out["plante"] = await _json(await c.post("/tableau/espace/api/t/plante", json={}, headers=avec))
        out["mal"] = await _json(await c.get("/tableau/espace/api/t/mal", headers=avec))
        out["note"] = await _json(await c.post("/tableau/espace/api/t/note?x=1", json={"a": 1}, headers=avec))
        r = await c.get("/tableau/espace/api/t/lire?y=2", headers=avec)
        out["lire"] = (r.status, r.headers.get("ETag"), r.headers.get("Cache-Control"))
        out["304"] = (await c.get("/tableau/espace/api/t/lire?y=2",
                                  headers=dict(avec, **{"If-None-Match": r.headers["ETag"]}))).status
        return out
    out = site.http(scenario)
    assert out["anonyme"] == (403, {"erreur": "Session expirée."})
    assert out["inconnue"][0] == 404 and out["inconnue_anonyme"] == 403, "sans session, on n'apprend même pas ce qui existe"
    assert out["methode"] == (405, "POST")
    assert out["sans_entete"] == out["croise"] == out["autre_site"] == 400, "une écriture vient de la page elle-même"
    assert out["trop_gros"] == 413 and out["illisible"] == 400 and out["liste"] == 400
    assert out["plante"] == (500, {"erreur": "Indisponible pour le moment."}) and out["mal"][0] == 500
    assert "secret" not in json.dumps(out), "jamais le texte d'une exception vers la page"
    assert "[TABLEAU][E11] adresse du site en échec" in site.journal_bot
    assert any("t/plante RuntimeError chemin secret" in x for x in site.journal_bot), "le détail part au journal du bot"
    assert out["note"] == (200, {"ok": True}), "les clés « _… » ne sortent jamais"
    assert appels[0] == (FONDATEUR, {"x": "1"}, {"a": 1})
    ligne = next(x for x in site.journal() if x["type"] == "site.t.note")
    assert (ligne["categorie"], ligne["texte"], ligne["membre_id"], ligne["auteur_id"], ligne["detail"]) == \
        ("Site", "Essai noté (par GoRipe)", 7, FONDATEUR, "détail")
    assert out["lire"][0] == 200 and out["lire"][1] and out["lire"][2] == "no-store" and out["304"] == 304
    assert not [x for x in site.journal() if x["type"] == "site.t.lire"], "une lecture n'est pas notée"


def test_V3_cadence_et_limites_graves(tmp_path, monkeypatch):
    site = Site(tmp_path, monkeypatch, peut_agir={9})
    faits = []

    async def role(g, auteur, requete, corps):
        faits.append(auteur.id)
        return 200, {"ok": True, "_journal": None}
    tableau.monter({"t/role": {"methode": "POST", "fn": role, "grave": "roles"},
                    "t/ecrire": {"methode": "POST", "fn": role}})
    monkeypatch.setattr(tableau, "LIMITE_ECRITURES", 5)
    tete, intrus = site.biscuit(DIRECTION), site.biscuit(9)

    async def scenario(c):
        cadence = [(await c.post("/tableau/espace/api/t/ecrire", json={}, headers=tete)).status for _ in range(6)]
        monkeypatch.setattr(tableau, "LIMITE_ECRITURES", 1000)
        tableau._cadence.clear()
        graves_tete = [(await c.post("/tableau/espace/api/t/role", json={}, headers=tete)).status for _ in range(27)]
        graves_intrus = [(await c.post("/tableau/espace/api/t/role", json={}, headers=intrus)).status for _ in range(26)]
        apres = (await c.get("/tableau/espace/api/rell/catalogue", headers=intrus)).status
        return cadence, graves_tete, graves_intrus, apres
    cadence, graves_tete, graves_intrus, apres = site.http(scenario)
    assert cadence == [200] * 5 + [429], "120 écritures par minute et par personne (5 ici)"
    assert graves_tete == [200] * 27, "la tête n'est jamais suspendue…"
    assert site.alertes[0] == (DIRECTION, "26 actions graves (roles) en moins de 10 minutes", False),         "…mais signalée, une fois"
    assert site.alertes[1:] == [(9, "26 actions graves (roles) en moins de 10 minutes", True)], "l'autre : suspendu"
    assert graves_intrus == [200] * 25 + [403] and apres == 403, "tout autre compte : suspendu, sessions fermées"
    assert faits.count(9) == 25


def test_V4_un_corps_envoye_par_morceaux_est_borne(site):
    vus = []

    async def note(g, auteur, requete, corps):
        vus.append(corps)
        return 200, {"ok": True}
    tableau.monter({"t/note": {"methode": "POST", "fn": note, "corps_max": 1000}})
    avec = site.biscuit()

    async def morceaux(n):
        for _ in range(n):
            yield b" " * 100

    async def scenario(c):
        gros = await c.post("/tableau/espace/api/t/note", data=morceaux(20), headers=avec)  # sans Content-Length
        petit = await c.post("/tableau/espace/api/t/note", data=morceaux(3), headers=avec)
        return gros.status, petit.status
    assert site.http(scenario) == (413, 200) and vus == [{}], "lu jusqu'à la borne, jamais au-delà"


# ═══════════════════════════════════════════════════════════════════════════════
#  V5 — les fichiers de `site/`
# ═══════════════════════════════════════════════════════════════════════════════

def _site_v2(dossier: Path) -> None:
    (dossier / "icones").mkdir(parents=True)
    (dossier / "index.html").write_text('<!doctype html><link rel="stylesheet" href="s/style.css?v={{V}}">'
                                        '<script type="module" src="s/app.js?v={{V}}"></script>', encoding="utf-8")
    (dossier / "app.js").write_text("export const A = 1;\n" * 50, encoding="utf-8")
    (dossier / "style.css").write_text("body{color:#2b1d12}\n" * 50, encoding="utf-8")
    (dossier / "sw.js").write_text("const V = '{{V}}';\n", encoding="utf-8")
    (dossier / "manifest.webmanifest").write_text('{"name":"Capitainerie"}', encoding="utf-8")
    (dossier / "icones" / "ui.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><symbol id='i-ancre'/></svg>",
                                               encoding="utf-8")
    (dossier / "LICENCES.md").write_text("OFL", encoding="utf-8")
    (dossier / ".env").write_text("TOKEN=secret", encoding="utf-8")


def test_V5_fichiers_du_site_types_cache_et_aucun_pas_dehors(site):
    _site_v2(site.tmp / "site")
    (site.tmp / "secret.js").write_text("le secret d'à côté", encoding="utf-8")
    lien_possible = True
    try:
        os.symlink(site.tmp / "secret.js", site.tmp / "site" / "fuite.js")
    except (OSError, NotImplementedError):
        lien_possible = False

    async def scenario(c):
        out = {}
        for nom, chemin in (("js", "/tableau/espace/s/app.js?v=abc"), ("css", "/tableau/espace/s/style.css"),
                            ("svg", "/tableau/espace/s/icones/ui.svg?v=1"), ("manif", "/tableau/espace/s/manifest.webmanifest")):
            r = await c.get(chemin)
            out[nom] = (r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control"), r.headers.get("ETag"),
                        r.headers.get("X-Content-Type-Options"), r.headers.get("Cross-Origin-Resource-Policy"),
                        r.headers.get("Content-Security-Policy"), await r.text())
        out["304"] = (await c.get("/tableau/espace/s/app.js?v=abc", headers={"If-None-Match": out["js"][3]})).status
        refuses = {}
        for chemin in ("../tableau.py", "%2e%2e/tableau.py", "..%2Ftableau.py", "icones/../../tableau.py",
                       "icones/%2e%2e/%2e%2e/tableau.py", ".env", "index.html", "LICENCES.md", "app.js%00.png",
                       "..\\tableau.py", "icones//ui.svg", "%2Fetc%2Fpasswd", "C:/Windows/win.ini", "rien.js",
                       "app.JS.", "fuite.js"):
            r = await c.get("/tableau/espace/s/" + chemin)
            refuses[chemin] = (r.status, await r.text())
        return out, refuses
    out, refuses = site.http(scenario)
    assert out["js"][:3] == (200, "text/javascript; charset=utf-8", "public, max-age=31536000, immutable")
    assert out["css"][:3] == (200, "text/css; charset=utf-8", "no-cache"), "sans ?v= : revalidé à chaque fois"
    assert out["svg"][1] == "image/svg+xml" and out["manif"][1] == "application/manifest+json; charset=utf-8"
    for x in (out["js"], out["css"], out["svg"], out["manif"]):
        assert x[4] == "nosniff" and x[5] == "same-origin", "servi sans session, mais protégé"
    assert out["svg"][6] == out["css"][6] == tableau.CSP_STATIQUE, "un SVG ouvert seul : aucun script"
    assert out["js"][6] == tableau.CSP_SW, "un script lancé en Web Worker : ses requêtes restent chez nous"
    assert out["304"] == 304
    for chemin, (status, texte) in refuses.items():
        assert status in (400, 404) and "secret" not in texte and "import" not in texte, f"servi à tort : {chemin}"
    if lien_possible:
        assert tableau._lire_statique("fuite.js") is None, "un lien qui sort du dossier n'est jamais suivi"


def test_V5b_chemins_refuses_par_la_normalisation():
    for brut in ("", "../a.js", "a/../b.js", "./a.js", "a//b.js", "/a.js", ".a.js", "a.py", "a", "a.js:$DATA",
                 "a b.js", "é.js", "a.js?", "x" * 301 + ".js", "/".join(["d"] * 9) + "/a.js", "a\\b.js", "a\x00.js"):
        assert tableau._chemin_statique(brut) is None, brut
    assert tableau._chemin_statique("icones/rell/metier/charpentier.webp") == ("icones/rell/metier/charpentier.webp", "webp")
    assert tableau._chemin_statique("polices/Pirata-One.WOFF2") == ("polices/Pirata-One.WOFF2", "woff2")


# ═══════════════════════════════════════════════════════════════════════════════
#  V6 — la page v2, son empreinte, le service worker
# ═══════════════════════════════════════════════════════════════════════════════

def test_V6_la_page_v2_son_empreinte_et_le_service_worker(site):
    sans = site.biscuit(origine=False)

    async def lire(c):
        p = await c.get("/tableau/espace/", headers=sans)
        sw = await c.get("/tableau/espace/sw.js")
        barre = await c.get("/tableau/espace", headers=sans, allow_redirects=False)
        anonyme = await c.get("/tableau/espace/")
        return (p.status, dict(p.headers), await p.text(), sw.status, dict(sw.headers), await sw.text(),
                barre.status, barre.headers.get("Location"), anonyme.status)
    #  Sans `site/index.html` : l'ancienne page, son nonce ; pas de service worker.
    st, h, texte, sw_st, _swh, _sw, barre, ou, anonyme = site.http(lire)
    assert st == 200 and "script-src 'nonce-" in h["Content-Security-Policy"] and "Espace direction" in texte
    assert sw_st == 404 and barre == 303 and ou == "/tableau/espace/" and anonyme == 403
    assert tableau.version_page() == tableau.VERSION
    #  Avec `site/` : la page v2, `{{V}}` remplacé par l'empreinte, la CSP de la spécification.
    _site_v2(site.tmp / "site")
    tableau._cache_empreinte["vu"] = 0  # l'empreinte est relue au plus toutes les 2 s : on n'attend pas
    st, h, texte, sw_st, swh, sw, *_r = site.http(lire)
    v = tableau.empreinte_site()
    assert len(v) == 12 and tableau.version_page() == v
    assert st == 200 and h["Content-Security-Policy"] == CSP_SPEC == tableau.CSP_SITE
    assert "{{V}}" not in texte and f"s/app.js?v={v}" in texte and "nonce" not in texte
    assert h["Cache-Control"] == "no-store" and "noindex" in h["X-Robots-Tag"] and h["X-Frame-Options"] == "DENY"
    assert sw_st == 200 and sw == f"const V = '{v}';\n" and swh["Cache-Control"] == "no-cache"
    assert swh["Content-Type"] == "text/javascript; charset=utf-8" and swh["Content-Security-Policy"] == tableau.CSP_SW
    assert swh["Service-Worker-Allowed"] == "/tableau/espace/"
    #  Un fichier change : nouvelle empreinte, nouvelles adresses.
    time.sleep(0.01)
    (site.tmp / "site" / "app.js").write_text("export const A = 2;\n", encoding="utf-8")
    tableau._cache_empreinte["vu"] = 0
    assert tableau.empreinte_site() != v
    avant = tableau.empreinte_site(time.time() + 10)
    (site.tmp / "site" / ".cache").write_text("caché", encoding="utf-8")
    assert tableau.empreinte_site(time.time() + 20) == avant, "un fichier caché ne compte pas"


# ═══════════════════════════════════════════════════════════════════════════════
#  V7 — les images envoyées : refaites, jamais servies telles quelles
# ═══════════════════════════════════════════════════════════════════════════════

def test_V7_images_refaites_et_fichiers_pieges_refuses(site, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image
    avec, sans = site.biscuit(), site.biscuit(origine=False)
    im = Image.new("RGB", (64, 48), (31, 78, 90))
    exif = Image.Exif()
    exif[0x010F] = "Fabricant secret"
    exif[0x0112] = 6  # à pivoter d'un quart de tour
    b = io.BytesIO()
    im.save(b, "JPEG", exif=exif.tobytes())
    jpeg = b.getvalue()
    assert b"Fabricant secret" in jpeg

    async def envoyer(c, data, nom="image.png", type_="image/png", entetes=avec):
        r = await c.post("/tableau/espace/api/media", json={"nom": nom, "type": type_, "base64": data}, headers=entetes)
        return await _json(r)

    async def scenario(c):
        out = {"png": await envoyer(c, _b64(_png(3000, 100))),
               "jpeg": await envoyer(c, "data:image/jpeg;base64," + _b64(jpeg), "photo.jpg", "image/jpeg"),
               "gif": await envoyer(c, _b64(_png(10, 10, format_="GIF")), "anim.gif", "image/gif"),
               "transparent": await envoyer(c, _b64(_png(10, 10, (0, 0, 0, 0), "RGBA")), "t.png"),
               "svg": await envoyer(c, _b64(b"<svg onload=alert(1)>"), "x.svg", "image/svg+xml"),
               "html": await envoyer(c, _b64(b"<html><script>alert(1)</script>"), "x.png"),
               "faux_png": await envoyer(c, _b64(b"\x89PNG\r\n\x1a\n" + b"pas une image" * 10), "f.png"),
               "tronque": await envoyer(c, _b64(_png(200, 200)[:60]), "t.png"),
               "base64": await envoyer(c, "!!pas du base64!!"),
               "vide": await envoyer(c, ""),
               "nom": await envoyer(c, _b64(_png()), nom=["liste"]),
               "sans_origine": await envoyer(c, _b64(_png()), entetes=sans)}
        monkeypatch.setattr(tableau, "MEDIA_PIXELS", 1000)
        out["bombe"] = await envoyer(c, _b64(_png(40, 30)))
        monkeypatch.setattr(tableau, "MEDIA_MAX", 10)
        out["lourde"] = await envoyer(c, _b64(_png(40, 30)))
        ident = out["png"][1]["id"]
        r = await c.get(f"/tableau/espace/media/{ident}", headers=sans)
        out["lire"] = (r.status, dict(r.headers), await r.read())
        r = await c.get(f"/tableau/espace/media/{out['jpeg'][1]['id']}", headers=sans)
        out["lire_jpeg"] = await r.read()
        out["anonyme"] = (await c.get(f"/tableau/espace/media/{ident}")).status
        out["inconnue"] = [(await c.get(f"/tableau/espace/media/{x}", headers=sans)).status
                           for x in ("A" * 16, "../site.db", "avatar/12", "avatar/../x", ident + ".webp", "avatar/12.webp")]
        return out
    out = site.http(scenario)
    st, rep = out["png"]
    assert st == 200 and rep["url"] == f"media/{rep['id']}" and (rep["largeur"], rep["hauteur"]) == (2048, 68)
    assert rep["type"] in ("image/webp", "image/png") and tableau.FORMAT_MEDIA.fullmatch(rep["id"])
    assert out["jpeg"][0] == 200 and (out["jpeg"][1]["largeur"], out["jpeg"][1]["hauteur"]) == (48, 64), \
        "l'orientation appliquée, puis oubliée"
    assert out["gif"][0] == 200 and out["transparent"][0] == 200
    for cle in ("svg", "html", "faux_png", "tronque", "bombe"):
        assert out[cle][0] == 415, cle
    assert out["base64"][0] == 400 and out["vide"][0] == 400 and out["nom"] == (400, {"erreur": "Nom de fichier invalide.",
                                                                                        "champ": "nom"})
    assert out["sans_origine"][0] == 400 and out["lourde"][0] == 413
    st, h, data = out["lire"]
    assert st == 200 and h["Content-Type"] == rep["type"] and h["Cache-Control"] == "no-store"
    assert h["Content-Security-Policy"] == "default-src 'none'; sandbox" and h["X-Content-Type-Options"] == "nosniff"
    assert Image.open(io.BytesIO(data)).size == (2048, 68)
    assert b"Fabricant secret" not in out["lire_jpeg"] and not Image.open(io.BytesIO(out["lire_jpeg"])).getexif(), \
        "aucune métadonnée ne survit"
    assert out["anonyme"] == 403 and all(s in (400, 404) for s in out["inconnue"]), out["inconnue"]
    lignes = site.sql("SELECT id, guild_id, auteur_id, nom FROM tableau_medias ORDER BY rowid")
    assert len(lignes) == 4 and lignes[0][1:] == (1, FONDATEUR, "image.png")
    assert any(x["texte"] == "Image ajoutée au site : image.png (par GoRipe)" for x in site.journal())


# ═══════════════════════════════════════════════════════════════════════════════
#  V8 — hors ligne : chaque opération appliquée une seule fois
# ═══════════════════════════════════════════════════════════════════════════════

def test_V8_synchronisation_idempotente_ordonnee_et_bornee(site, monkeypatch):
    site.catalogue()
    avec, sans = site.biscuit(), site.biscuit(origine=False)
    autre = site.biscuit(DIRECTION)
    creer = {"op_id": "op-creer-0001", "api": "rell/affiche",
             "corps": {"id": "hors-ligne-01", "version": 0, "membre_id": "7", "surnom": "Le Requin",
                       "attributs": {"metier": ["navigateur"]}}}
    modifier = {"op_id": "op-modifier-02", "api": "rell/affiche",
                "corps": {"id": "hors-ligne-01", "version": 1, "membre_id": "7", "surnom": "Le Grand Requin",
                          "attributs": {"metier": ["navigateur", "canonnier"]}}}
    perime = {"op_id": "op-perime-0003", "api": "rell/affiche",
              "corps": {"id": "hors-ligne-01", "version": 1, "membre_id": "7", "surnom": "Version périmée"}}

    async def sync(c, ops, entetes=avec):
        r = await c.post("/tableau/espace/sync", json={"ops": ops}, headers=entetes)
        return await _json(r)

    async def scenario(c):
        out = {"premier": await sync(c, [creer, modifier, perime])}
        out["rejoue"] = await sync(c, [creer, modifier, perime])
        out["ensemble"] = await asyncio.gather(*(sync(c, [{"op_id": "op-ensemble-04", "api": "rell/affiche/retirer",
                                                            "corps": {"id": "hors-ligne-01", "version": 2}}])
                                                  for _ in range(3)))
        out["autre_compte"] = await sync(c, [creer], autre)
        out["refusees"] = await sync(c, [{"op_id": "op-role-00005", "api": "rell/role", "corps": {}},
                                         {"op_id": "op-get-000006", "api": "rell/catalogue", "corps": {}},
                                         {"op_id": "op-inconnue-7", "api": "../action", "corps": {}},
                                         {"op_id": "court", "api": "rell/affiche", "corps": {}},
                                         {"op_id": "op-corps-0008", "api": "rell/affiche", "corps": [1]},
                                         "pas une opération"])
        out["trop"] = await sync(c, [creer] * 51)
        out["pas_liste"] = await sync(c, {"op_id": "x"})
        out["sans_origine"] = await sync(c, [creer], sans)
        out["anonyme"] = (await c.post("/tableau/espace/sync", json={"ops": [creer]}, headers=ORIGINE)).status
        monkeypatch.setattr(tableau, "LIMITE_ECRITURES", 1)
        tableau._cadence.clear()
        out["cadence"] = await sync(c, [{"op_id": f"op-cadence-{k:03}", "api": "rell/affiche",
                                         "corps": {"version": 0, "surnom": f"Nouvelle {k}"}} for k in range(3)])
        return out
    out = site.http(scenario)
    st, rep = out["premier"]
    assert st == 200 and [x["status"] for x in rep["resultats"]] == [200, 200, 409]
    assert rep["resultats"][1]["corps"]["affiche"]["surnom"] == "Le Grand Requin"
    assert rep["resultats"][2]["corps"]["conflit"] and rep["resultats"][2]["corps"]["actuelle"]["version"] == 2
    assert out["rejoue"] == out["premier"], "renvoyées : les mêmes réponses, rien de refait"
    historique = site.sql("SELECT action FROM rell_affiches_historique WHERE affiche_id='hors-ligne-01' ORDER BY id")
    assert [h[0] for h in historique] == ["creee", "modifiee", "retiree"], "chaque opération UNE fois"
    assert len({json.dumps(x) for x in out["ensemble"]}) == 1 and out["ensemble"][0][1]["resultats"][0]["status"] == 200
    assert out["autre_compte"][1]["resultats"][0]["status"] == 409, "l'opération d'un autre compte n'est pas rejouée"
    assert [x["status"] for x in out["refusees"][1]["resultats"]] == [400] * 6
    assert out["trop"][0] == out["pas_liste"][0] == out["sans_origine"][0] == 400 and out["anonyme"] == 403
    assert [x["status"] for x in out["cadence"][1]["resultats"]] == [200, 429, 429], "après la cadence : plus tard, dans l'ordre"
    gardees = {r[0]: r[1] for r in site.sql("SELECT op_id, status FROM tableau_ops")}
    assert gardees["op-perime-0003"] == 409 and "op-cadence-001" not in gardees and "op-role-00005" in gardees


def test_V8b_trace_en_echec_l_operation_n_est_jamais_appliquee_deux_fois(site, monkeypatch):
    site.catalogue()
    avec = site.biscuit()

    async def trace_impossible(*a, **k):
        raise RuntimeError("base verrouillée")
    monkeypatch.setattr(tableau, "_garder_op", trace_impossible)
    op = {"op_id": "op-trace-perdue", "api": "rell/affiche", "corps": {"version": 0, "surnom": "Une seule fois"}}

    async def scenario(c):
        return [await _json(await c.post("/tableau/espace/sync", json={"ops": [op]}, headers=avec)) for _ in range(2)]
    premier, second = site.http(scenario)
    assert premier == second and premier[1]["resultats"][0]["status"] == 200, "la vraie réponse, deux fois"
    assert len(site.sql("SELECT id FROM rell_affiches WHERE surnom='Une seule fois'")) == 1, "appliquée UNE fois"
    assert "[TABLEAU][E18] trace d'une opération hors ligne non gardée" in site.journal_bot


# ═══════════════════════════════════════════════════════════════════════════════
#  V9 — V10 : le catalogue RELL Seas
# ═══════════════════════════════════════════════════════════════════════════════

def test_V9_catalogue_de_depart_ajoute_suit_et_ne_remplace_jamais_le_site(site, tmp_path):
    assert site.catalogue() == {"types": 4, "elements": 9, "mis_a_jour": 0, "gardes": 0, "refuses": 0}
    assert site.catalogue() == {"types": 0, "elements": 0, "mis_a_jour": 0, "gardes": 0, "refuses": 0}, "rien deux fois"
    chef = site.g.get_member(FONDATEUR)

    async def modifier():
        return await affiches._route_element(site.g, chef, {}, {"type": "metier", "cle": "cuisinier", "version": 1,
                                                                "nom": "Coq du navire", "statut": "confirme"})
    assert asyncio.run(modifier())[0] == 200
    depart = json.loads(EXEMPLE.read_text(encoding="utf-8"))
    for e in depart["elements"]:
        if e["cle"] in ("cuisinier", "navigateur"):
            e["nom"] = e["nom"] + " (corrigé)"
    depart["types"][0]["nom"] = "Race du joueur"
    depart["elements"].append({"type": "metier", "cle": "medecin", "nom": "Médecin", "statut": "a_verifier"})
    depart["elements"] += [{"type": "inconnu", "cle": "x", "nom": "X"}, {"type": "metier", "cle": "Pas Bon", "nom": "Y"},
                           {"type": "metier", "cle": "z", "nom": "Z", "source": "javascript:alert(1)"}]
    fichier = tmp_path / "depart.json"
    fichier.write_text(json.dumps(depart), encoding="utf-8")
    bilan = asyncio.run(affiches.charger_depart(fichier))
    assert bilan == {"types": 0, "elements": 1, "mis_a_jour": 2, "gardes": 1, "refuses": 3}
    cat = asyncio.run(affiches.catalogue())
    par_cle = {e["cle"]: e for e in cat["elements"]}
    assert par_cle["cuisinier"]["nom"] == "Coq du navire" and par_cle["cuisinier"]["modifie"], "modifié sur le site : gardé"
    assert par_cle["navigateur"]["nom"] == "Navigateur (corrigé)" and par_cle["navigateur"]["version"] == 2
    assert par_cle["medecin"]["statut"] == "a_verifier" and "x" not in par_cle and "z" not in par_cle
    assert cat["types"][0]["nom"] == "Race du joueur"
    assert asyncio.run(affiches.charger_depart(tmp_path / "absent.json"))["absent"]
    (tmp_path / "abime.json").write_text("{pas du json", encoding="utf-8")
    assert asyncio.run(affiches.charger_depart(tmp_path / "abime.json"))["illisible"]
    assert "[AFFICHES][E1] catalogue de départ illisible" in site.journal_bot


def test_V10_catalogue_sur_le_site_versions_conflits_et_validation(site):
    site.catalogue()
    avec = site.biscuit()

    async def post(c, api, corps):
        return await _json(await c.post(f"/tableau/espace/api/{api}", json=corps, headers=avec))

    async def scenario(c):
        out = {"get": await _json(await c.get("/tableau/espace/api/rell/catalogue", headers=avec))}
        out["creer"] = await post(c, "rell/catalogue/element", {"type": "metier", "cle": "pecheur", "version": 0,
                                                               "nom": "Pêcheur", "nom_en": "Fisher",
                                                               "nouveau_movie3": True, "statut": "a_verifier"})
        out["modifier"] = await post(c, "rell/catalogue/element", {"type": "metier", "cle": "pecheur", "version": 1,
                                                                  "nom": "Pêcheur", "statut": "confirme",
                                                                  "source": "https://exemple.org/wiki/Pecheur"})
        out["identique"] = await post(c, "rell/catalogue/element", {"type": "metier", "cle": "pecheur", "version": 2,
                                                                   "nom": "Pêcheur", "statut": "confirme",
                                                                   "source": "https://exemple.org/wiki/Pecheur"})
        out["perime"] = await post(c, "rell/catalogue/element", {"type": "metier", "cle": "pecheur", "version": 1,
                                                                "nom": "Autre"})
        out["deja_cree"] = await post(c, "rell/catalogue/element", {"type": "metier", "cle": "pecheur", "nom": "Doublon"})
        erreurs = {}
        for champ, corps in (("type", {"type": "fruit", "cle": "a", "nom": "A"}),
                             ("cle", {"type": "metier", "cle": "Avec Espace", "nom": "A"}),
                             ("nom", {"type": "metier", "cle": "a", "nom": "   "}),
                             ("nom", {"type": "metier", "cle": "a", "nom": "x" * 81}),
                             ("statut", {"type": "metier", "cle": "a", "nom": "A", "statut": "peut-etre"}),
                             ("source", {"type": "metier", "cle": "a", "nom": "A", "source": "javascript:alert(1)"}),
                             ("source", {"type": "metier", "cle": "a", "nom": "A", "source": "data:text/html,x"}),
                             ("icone", {"type": "metier", "cle": "a", "nom": "A", "icone": "https://pirate.exemple/x.png"}),
                             ("icone", {"type": "metier", "cle": "a", "nom": "A", "icone": "s/icones/../../tableau.py"}),
                             ("icone", {"type": "metier", "cle": "a", "nom": "A", "icone": "media/AAAAAAAAAAAAAAAA"}),
                             ("ordre", {"type": "metier", "cle": "a", "nom": "A", "ordre": "beaucoup"}),
                             ("actif", {"type": "metier", "cle": "a", "nom": "A", "actif": "oui"}),
                             ("description", {"type": "metier", "cle": "a", "nom": "A", "description": ["x"]})):
            st, rep = await post(c, "rell/catalogue/element", corps)
            erreurs.setdefault(champ, []).append((st, rep.get("champ")))
        out["erreurs"] = erreurs
        out["retirer_perime"] = await post(c, "rell/catalogue/retirer", {"type": "metier", "cle": "pecheur", "version": 1})
        out["retirer"] = await post(c, "rell/catalogue/retirer", {"type": "metier", "cle": "pecheur", "version": 2})
        out["retirer_encore"] = await post(c, "rell/catalogue/retirer", {"type": "metier", "cle": "pecheur", "version": 3})
        out["type"] = await post(c, "rell/catalogue/type", {"cle": "navire", "nom": "Navire", "multiple": False})
        out["type_perime"] = await post(c, "rell/catalogue/type", {"cle": "navire", "nom": "Navires", "version": 5})
        out["invisible"] = await post(c, "rell/catalogue/element", {"type": "navire", "cle": "galion", "nom": "Ga\u202elion\u200b"})
        out["sans_cle"] = await post(c, "rell/catalogue/element", {"type": "metier", "nom": "Maître d'équipage"})
        out["sans_cle_vide"] = await post(c, "rell/catalogue/element", {"type": "metier", "nom": "!!!"})
        return out
    out = site.http(scenario)
    st, cat = out["get"]
    assert st == 200 and [t["cle"] for t in cat["types"]] == ["race", "metier", "faction", "arme"]
    e = next(x for x in cat["elements"] if x["cle"] == "canonnier")
    assert set(e) >= {"type", "cle", "nom", "nom_en", "description", "categorie", "rarete", "icone", "statut", "source",
                      "ordre", "actif", "nouveau_movie3", "version"} and e["nouveau_movie3"] and e["statut"] == "a_verifier"
    assert e["icone"] == "s/icones/rell/metier/canonnier.webp" and cat["maj"]
    assert out["creer"][0] == 200 and out["creer"][1]["element"]["version"] == 1 and out["creer"][1]["element"]["nouveau_movie3"]
    assert out["modifier"][1]["element"]["version"] == 2 and out["modifier"][1]["element"]["statut"] == "confirme"
    assert out["identique"][1]["element"]["version"] == 2, "rien de changé : aucune nouvelle version"
    assert out["perime"][0] == 409 and out["perime"][1]["actuelle"]["version"] == 2
    assert out["deja_cree"][0] == 409, "deux créations de la même clé : la seconde est un conflit"
    for champ, resultats in out["erreurs"].items():
        assert all(r == (400, champ) for r in resultats), (champ, resultats)
    assert out["retirer_perime"][0] == 409 and out["retirer"][1]["element"]["actif"] is False
    assert out["retirer_encore"][0] == 200
    assert out["type"][0] == 200 and out["type"][1]["type"]["multiple"] is False and out["type_perime"][0] == 409
    assert out["invisible"][1]["element"]["nom"] == "Galion", "les caractères invisibles et de direction sont retirés"
    assert out["sans_cle"][1]["element"]["cle"] == "maitre-d-equipage", "sans clé : celle du nom"
    assert out["sans_cle_vide"] == (400, {"erreur": "Clé invalide : minuscules, chiffres, « - » et « _ » (64 au plus).",
                                          "champ": "cle"})
    journal = [x["texte"] for x in site.journal()]
    assert "Catalogue RELL Seas : « Pêcheur » (Métier) ajouté (par GoRipe)" in journal
    assert sum("Pêcheur" in x for x in journal) == 3, "créé, modifié, retiré : trois lignes ; l'identique n'en fait pas"


# ═══════════════════════════════════════════════════════════════════════════════
#  V11 — les affiches
# ═══════════════════════════════════════════════════════════════════════════════

def test_V11_affiches_une_par_membre_versions_corbeille_historique(site):
    site.catalogue()
    avec = site.biscuit()

    async def post(c, api, corps):
        return await _json(await c.post(f"/tableau/espace/api/{api}", json=corps, headers=avec))

    async def scenario(c):
        out = {"creer": await post(c, "rell/affiche", {"membre_id": "7", "roblox_nom": "Kolax_RS", "roblox_id": 4242,
                                                       "surnom": "Le Requin", "prime": "1500000", "niveau": 72,
                                                       "grade": "Second", "statut": "actif",
                                                       "attributs": {"race": "humain", "metier": ["navigateur",
                                                                                                  "canonnier", "navigateur"]},
                                                       "notes": "Ligne 1\r\nLigne 2"})}
        ident = out["creer"][1]["affiche"]["id"]
        out["doublon"] = await post(c, "rell/affiche", {"membre_id": 7, "surnom": "Encore lui"})
        erreurs = {}
        for champ, corps in (("membre_id", {"membre_id": "123456"}), ("membre_id", {"membre_id": "abc"}),
                             ("membre_id", {"surnom": ""}),
                             ("attributs", {"surnom": "A", "attributs": {"metier": ["astronaute"]}}),
                             ("attributs", {"surnom": "A", "attributs": {"race": ["humain", "triton"]}}),
                             ("attributs", {"surnom": "A", "attributs": {"fruit": ["x"]}}),
                             ("attributs", {"surnom": "A", "attributs": ["metier"]}),
                             ("prime", {"surnom": "A", "prime": -5}), ("prime", {"surnom": "A", "prime": 10 ** 13}),
                             ("niveau", {"surnom": "A", "niveau": True}), ("notes", {"surnom": "A", "notes": "x" * 4001}),
                             ("roblox_nom", {"surnom": "A", "roblox_nom": "pas valide !"}),
                             ("id", {"id": "../../x", "surnom": "A"}), ("surnom", {"surnom": {"a": 1}})):
            st, rep = await post(c, "rell/affiche", corps)
            erreurs.setdefault(champ, []).append((st, rep.get("champ")))
        out["erreurs"] = erreurs
        out["modifier"] = await post(c, "rell/affiche", {"id": ident, "version": 1, "membre_id": "7", "roblox_nom": "Kolax_RS",
                                                         "roblox_id": "4242", "surnom": "Le Requin", "prime": 2000000,
                                                         "niveau": 72, "grade": "Capitaine", "statut": "actif",
                                                         "attributs": {"race": ["humain"], "metier": ["navigateur",
                                                                                                      "canonnier"]},
                                                         "notes": "Ligne 1\nLigne 2"})
        out["identique"] = await post(c, "rell/affiche", dict(out["modifier"][1]["affiche"], membre_id="7",
                                                              roblox_nom="Kolax_RS", roblox_id="4242",
                                                              version=2))
        out["perime"] = await post(c, "rell/affiche", {"id": ident, "version": 1, "membre_id": "7", "surnom": "Vieux"})
        out["fantome"] = await post(c, "rell/affiche", {"id": "nexiste-pas", "version": 3, "surnom": "X"})
        out["sans_membre"] = await post(c, "rell/affiche", {"roblox_nom": "Mira_RS", "surnom": "L'Écume"})
        out["retirer"] = await post(c, "rell/affiche/retirer", {"id": ident, "version": 2})
        out["sur_retiree"] = await post(c, "rell/affiche", {"id": ident, "version": 3, "membre_id": "7", "surnom": "X"})
        out["remplace"] = await post(c, "rell/affiche", {"membre_id": "7", "surnom": "Nouvelle affiche"})
        out["restaurer_doublon"] = await post(c, "rell/affiche/restaurer", {"id": ident})
        out["liste"] = await _json(await c.get("/tableau/espace/api/rell/affiches", headers=avec))
        out["fiche"] = await _json(await c.get(f"/tableau/espace/api/rell/affiche?id={ident}", headers=avec))
        out["fiche_inconnue"] = (await c.get("/tableau/espace/api/rell/affiche?id=inconnue-01", headers=avec)).status
        autre = out["sans_membre"][1]["affiche"]["id"]
        out["retirer_sans_version"] = await post(c, "rell/affiche/retirer", {"id": autre})
        out["restaurer_par_retirer"] = await post(c, "rell/affiche/retirer", {"id": autre, "restaurer": True})
        out["fiche_invalide"] = (await c.get("/tableau/espace/api/rell/affiche?id=../x", headers=avec)).status
        return out, ident
    out, ident = site.http(scenario)
    st, rep = out["creer"]
    a = rep["affiche"]
    assert st == 200 and a["version"] == 1 and a["membre"] == {"id": "7", "nom": "Kolax", "present": True,
                                                                "avatar": "https://cdn.discordapp.com/avatars/7.png"}
    assert a["roblox"] == {"nom": "Kolax_RS", "id": "4242", "avatar": ""} and a["prime"] == 1500000
    assert a["attributs"] == {"race": ["humain"], "metier": ["navigateur", "canonnier"]}, "doublons retirés, ordre gardé"
    assert a["notes"] == "Ligne 1\nLigne 2" and a["cree_par"] == {"id": str(FONDATEUR), "nom": "GoRipe"}
    assert out["doublon"][0] == 409 and out["doublon"][1]["doublon"] and out["doublon"][1]["actuelle"]["id"] == ident
    for champ, resultats in out["erreurs"].items():
        assert all(r == (400, champ) for r in resultats), (champ, resultats)
    assert out["modifier"][1]["affiche"]["version"] == 2 and out["modifier"][1]["affiche"]["grade"] == "Capitaine"
    assert out["identique"][1]["affiche"]["version"] == 2, "rien de changé : ni version ni historique"
    assert out["perime"][0] == 409 and out["perime"][1]["actuelle"]["grade"] == "Capitaine"
    assert out["fantome"] == (409, {"conflit": True, "actuelle": None})
    assert out["sans_membre"][0] == 200 and out["sans_membre"][1]["affiche"]["membre"]["id"] == ""
    assert out["retirer"][1]["affiche"]["retire_le"] and out["sur_retiree"][1]["retiree"]
    assert out["remplace"][0] == 200, "à la corbeille, l'ancienne affiche ne bloque plus le membre"
    assert out["restaurer_doublon"][0] == 409 and out["restaurer_doublon"][1]["doublon"]
    st, liste = out["liste"]
    assert [x["surnom"] for x in liste["affiches"]] == ["L'Écume", "Nouvelle affiche"]
    assert [x["id"] for x in liste["corbeille"]] == [ident]
    assert liste["stats"]["total"] == 2 and liste["stats"]["corbeille"] == 1 and liste["stats"]["sans_membre"] == 1
    st, fiche = out["fiche"]
    assert fiche["id"] == ident and fiche["affiche"]["id"] == ident and fiche["surnom"] == "Le Requin"
    assert [h["action"] for h in fiche["historique"]] == ["retiree", "modifiee", "creee"], "du plus récent au plus ancien"
    assert [(h["qui"], h["quoi"]) for h in fiche["historique"]] == [
        ("GoRipe", "Mise à la corbeille"), ("GoRipe", "Prime : 1\u202f500\u202f000 → 2\u202f000\u202f000 · Grade : Second → Capitaine"),
        ("GoRipe", "Affiche créée")]
    champs = {c["champ"]: c for c in fiche["historique"][1]["changements"]}
    assert set(champs) == {"prime", "grade"} and champs["grade"] == {"champ": "grade", "avant": "Second", "apres": "Capitaine"}
    assert fiche["historique"][1]["par"] == {"id": str(FONDATEUR), "nom": "GoRipe"}
    assert out["fiche_inconnue"] == 404 and out["fiche_invalide"] == 400
    assert out["retirer_sans_version"][1]["affiche"]["retire_le"], "sans version : retirée sans contrôle"
    assert out["restaurer_par_retirer"][1]["affiche"]["retire_le"] is None, "« restaurer » : sortie de la corbeille"
    journal = [x for x in site.journal() if x["type"] == "site.rell.affiche"]
    assert journal[-1]["texte"] == "Affiche « Le Requin » créée (par GoRipe)" and journal[-1]["membre_id"] == 7


# ═══════════════════════════════════════════════════════════════════════════════
#  V12 — les portraits Roblox : demandés par le serveur, pris au CDN de Roblox seulement
# ═══════════════════════════════════════════════════════════════════════════════

def test_V12_portraits_roblox_serveur_seulement(site, monkeypatch):
    pytest.importorskip("PIL")
    avec = site.biscuit()
    appels, etat = [], {"portrait": "https://tr.rbxcdn.com/30DAY-AvatarHeadshot-ABC/420/420/AvatarHeadshot/Png/noFilter",
                        "pending": 0, "panne": False}

    async def faux_json(methode, url, *, params=None, json_=None):
        appels.append(("json", methode, url, params, json_))
        if etat["panne"]:
            raise OSError("connexion refusée par 10.0.0.1")
        if url == affiches.ROBLOX_UTILISATEURS:
            nom = json_["usernames"][0]
            return 200, {"data": [] if nom == "Personne_Ici" else
                         [{"requestedUsername": nom, "id": 4242, "name": "Kolax_RS", "displayName": "Kolax"}]}
        if etat["pending"]:
            etat["pending"] -= 1
            return 200, {"data": [{"targetId": 4242, "state": "Pending", "imageUrl": None}]}
        return 200, {"data": [{"targetId": 4242, "state": "Completed", "imageUrl": etat["portrait"]}]}

    async def faux_octets(url, maximum):
        appels.append(("octets", url))
        return 200, _png(420, 420, (31, 78, 90))
    monkeypatch.setattr(affiches, "_http_json", faux_json)
    monkeypatch.setattr(affiches, "_http_octets", faux_octets)
    monkeypatch.setattr(affiches, "PORTRAIT_ATTENTE", 0)

    async def avatar(c, nom):
        return await _json(await c.post("/tableau/espace/api/rell/avatar", json={"roblox_nom": nom}, headers=avec))

    async def scenario(c):
        out = {"premier": await avatar(c, "kolax_rs")}
        n = len(appels)
        out["cache"] = await avatar(c, "KOLAX_RS")
        out["appels_cache"] = len(appels) - n
        r = await c.get("/tableau/espace/media/avatar/4242", headers=avec)
        out["image"] = (r.status, r.headers.get("Content-Type"), r.headers.get("Cache-Control"))
        out["inconnu"] = await avatar(c, "Personne_Ici")
        out["invalide"] = await avatar(c, "a b")
        etat["panne"] = True
        out["panne"] = await avatar(c, "Autre_Joueur")
        etat["panne"], etat["portrait"] = False, "https://pirate.exemple/x.png"
        n = len([a for a in appels if a[0] == "octets"])
        out["hors_cdn"] = await avatar(c, "Troisieme")
        out["octets_hors_cdn"] = len([a for a in appels if a[0] == "octets"]) - n
        return out
    out = site.http(scenario)
    assert out["premier"] == (200, {"ok": True, "roblox_id": "4242", "nom": "Kolax_RS", "avatar": "media/avatar/4242"})
    assert appels[0][1:] == ("POST", affiches.ROBLOX_UTILISATEURS, None, {"usernames": ["kolax_rs"], "excludeBannedUsers": False})
    assert appels[1][3] == {"userIds": "4242", "size": "420x420", "format": "Png", "isCircular": "false"}
    assert out["cache"][0] == 200 and out["appels_cache"] == 0, "déjà connu : Roblox n'est pas redemandé"
    assert out["image"] == (200, out["image"][1], "no-store") and out["image"][1] in ("image/webp", "image/png")
    assert out["inconnu"][0] == 404 and out["invalide"][0] == 400
    assert out["panne"] == (502, {"erreur": "Roblox ne répond pas : réessaie dans un instant."})
    assert "10.0.0.1" not in json.dumps(out) and "[AFFICHES][E2] Roblox injoignable (nom)" in site.journal_bot
    assert out["hors_cdn"][0] == 200 and out["octets_hors_cdn"] == 0, "une image hors du CDN de Roblox n'est jamais téléchargée"
    assert not [x for x in site.journal() if "avatar" in x["type"]], "une recherche de portrait n'encombre pas le journal"
    #  « Pending » : redemandé une fois.
    etat.update(pending=1, portrait="https://tr.rbxcdn.com/y/420/420/AvatarHeadshot/Png")
    assert asyncio.run(affiches._portrait(4242)) == "media/avatar/4242"
    etat.update(pending=2)
    assert asyncio.run(affiches._portrait(4242)) == ""
    for url, ok in (("https://tr.rbxcdn.com/a.png", True), ("https://rbxcdn.com/a", True), ("http://tr.rbxcdn.com/a", False),
                    ("https://rbxcdn.com.pirate.exemple/a", False), ("https://pirate@tr.rbxcdn.com/a", False),
                    ("https://tr.rbxcdn.com:8443/a", False), ("https://evilrbxcdn.com/a", False), (None, False)):
        assert affiches._adresse_cdn(url) is ok, url


def test_V12b_cadence_des_recherches_roblox(site, monkeypatch):
    avec = site.biscuit()

    async def faux_json(methode, url, *, params=None, json_=None):
        return 200, {"data": []}
    monkeypatch.setattr(affiches, "_http_json", faux_json)
    monkeypatch.setattr(affiches, "ROBLOX_PAR_MINUTE", 3)

    async def scenario(c):
        return [(await c.post("/tableau/espace/api/rell/avatar", json={"roblox_nom": f"Joueur_{k}"}, headers=avec)).status
                for k in range(4)]
    assert site.http(scenario) == [404, 404, 404, 429]


# ═══════════════════════════════════════════════════════════════════════════════
#  V13 — les rôles des métiers
# ═══════════════════════════════════════════════════════════════════════════════

def test_V13_roles_des_metiers_lies_crees_appliques_jamais_un_autre(site):
    site.catalogue()
    g = site.g
    navigateur = g.role(20, "Navigateur", 10, couleur=0x1F4E5A)
    canonnier = g.role(21, "Canonnier", 11)
    g.role(22, "Modérateur", 12, permissions=discord.Permissions(kick_members=True))
    g.role(23, "Bot musique", 13, managed=True)
    g.role(24, "Au-dessus du bot", 70)
    vip = g.role(25, "VIP", 14)
    kolax = g.get_member(7)
    kolax.roles = [vip, canonnier]
    avec = site.biscuit()

    async def post(c, api, corps):
        return await _json(await c.post(f"/tableau/espace/api/{api}", json=corps, headers=avec))

    async def scenario(c):
        out = {"liste": await _json(await c.get("/tableau/espace/api/rell/roles", headers=avec))}
        out["lier"] = await post(c, "rell/role", {"type": "metier", "cle": "navigateur", "role_id": "20"})
        out["lier2"] = await post(c, "rell/role", {"type": "metier", "cle": "canonnier", "role_id": 21})
        out["refus"] = [await post(c, "rell/role", {"type": "metier", "cle": "charpentier", "role_id": str(rid)})
                        for rid in (22, 23, 24, 1, 999)]
        out["inconnu"] = await post(c, "rell/role", {"type": "metier", "cle": "astronaute", "role_id": "20"})
        out["creer"] = await post(c, "rell/role", {"type": "metier", "cle": "charpentier", "auto": True,
                                                   "creer": {"nom": "Charpentier", "couleur": "#A8823F"}})
        out["couleur"] = await post(c, "rell/role", {"type": "metier", "cle": "cuisinier", "creer": {"nom": "C",
                                                                                                    "couleur": "rouge"}})
        out["affiche"] = await post(c, "rell/affiche", {"membre_id": "7", "surnom": "Le Requin",
                                                        "attributs": {"metier": ["navigateur", "charpentier"]}})
        out["appliquer"] = await post(c, "rell/roles/appliquer", {"affiche_id": out["affiche"][1]["affiche"]["id"]})
        out["encore"] = await post(c, "rell/roles/appliquer", {"affiche_id": out["affiche"][1]["affiche"]["id"]})
        out["sans_membre"] = await post(c, "rell/affiche", {"surnom": "Personne"})
        out["appliquer_sans"] = await post(c, "rell/roles/appliquer", {"affiche_id": out["sans_membre"][1]["affiche"]["id"]})
        out["delier"] = await post(c, "rell/role", {"type": "metier", "cle": "canonnier", "retirer": True})
        g.me.guild_permissions = discord.Permissions.none()
        out["sans_droit"] = await post(c, "rell/role", {"type": "arme", "cle": "sabre", "creer": {"nom": "S"}})
        out["hors_ligne"] = await _json(await c.post("/tableau/espace/sync", json={"ops": [
            {"op_id": "op-role-hors-ligne", "api": "rell/roles/appliquer", "corps": {}}]}, headers=avec))
        return out
    out = site.http(scenario)
    st, liste = out["liste"]
    assert st == 200 and liste["gestion"] and liste["liens"] == []
    assert [r["nom"] for r in liste["roles"]] == ["VIP", "Canonnier", "Navigateur"], \
        "ni modération, ni intégration, ni au-dessus du bot, ni @everyone"
    assert out["lier"][0] == 200 and out["lier"][1]["lien"]["role_nom"] == "Navigateur"
    assert out["lier"][1]["lien"]["couleur"] == "#1f4e5a" and out["lier2"][0] == 200
    assert [x[0] for x in out["refus"]] == [400, 400, 400, 400, 400]
    assert "modération" in out["refus"][0][1]["erreur"] and "au-dessus" in out["refus"][2][1]["erreur"]
    assert out["inconnu"][0] == 404
    assert out["creer"][0] == 200 and out["creer"][1]["lien"]["auto"]
    cree = g.crees[0]
    assert cree["name"] == "Charpentier" and cree["permissions"] == discord.Permissions.none(), "créé SANS aucune permission"
    assert cree["colour"].value == 0xA8823F and cree["mentionable"] is False and cree["hoist"] is False
    assert out["couleur"] == (400, {"erreur": "Couleur attendue : #RRVVBB.", "champ": "couleur"})
    #  « Automatique » : à l'enregistrement de l'affiche, le rôle du charpentier (lien auto) est donné.
    assert out["affiche"][1]["roles"]["ajoutes"] == [{"id": "501", "nom": "Charpentier"}]
    st, rep = out["appliquer"]
    assert st == 200 and rep["ajoutes"] == [{"id": "20", "nom": "Navigateur"}]
    assert rep["retires"] == [{"id": "21", "nom": "Canonnier"}], "un métier qu'il n'a plus : son rôle part"
    assert {r.id for r in kolax.roles} == {25, 20, 501}, "le VIP n'est jamais touché"
    assert out["encore"][1]["ajoutes"] == [] and out["encore"][1]["retires"] == []
    assert out["appliquer_sans"][0] == 409
    assert out["delier"][0] == 200 and [x["cle"] for x in out["delier"][1]["liens"]] == ["charpentier", "navigateur"]
    assert out["sans_droit"][0] == 403
    assert out["hors_ligne"][1]["resultats"][0]["status"] == 400, "les rôles ne se rejouent jamais hors ligne"
    textes = [x["texte"] for x in site.journal()]
    assert "Rôles des métiers de Kolax : +Navigateur, −Canonnier (par GoRipe)" in textes
    assert "Rôles des métiers de Kolax : +Charpentier (automatique)" in textes


# ═══════════════════════════════════════════════════════════════════════════════
#  V14 — le nettoyage
# ═══════════════════════════════════════════════════════════════════════════════

def test_V14_nettoyage_regles_bornees_et_bilan(site):
    site.catalogue()
    avec = site.biscuit()
    t = int(time.time())
    vieux, recent = t - 40 * 86400, t - 2 * 86400
    #  Affiches : une vieille à la corbeille, une récente ; un vieil historique.
    for ident, retire in (("vieille-corbeille", vieux), ("recente-corbeille", recent), ("active-affiche", 0)):
        site.ecrire("INSERT INTO rell_affiches (guild_id, id, surnom, cree_le, maj_le, retire_le) VALUES (1,?,?,?,?,?)",
                    (ident, ident, vieux, vieux, retire))
    site.ecrire("INSERT INTO rell_affiches_historique (guild_id, affiche_id, quand, action) VALUES (1,'active-affiche',?,'creee')",
                (t - 400 * 86400,))
    site.ecrire("INSERT INTO rell_affiches_historique (guild_id, affiche_id, quand, action) VALUES (1,'active-affiche',?,'modifiee')",
                (recent,))
    #  Opérations hors ligne, images (utilisée par le catalogue, oubliée, récente), candidatures.
    site.ecrire("INSERT INTO tableau_ops VALUES ('op-vieille-001', 1, ?, 'rell/affiche', 200, '{}', ?)", (FONDATEUR, vieux))
    site.ecrire("INSERT INTO tableau_ops VALUES ('op-recente-002', 1, ?, 'rell/affiche', 200, '{}', ?)", (FONDATEUR, recent))
    dossier = tableau.dossier_site("medias")
    for ident, cree in (("utiliseeAAAAAAAA", vieux), ("oublieeBBBBBBBBB", vieux), ("recenteCCCCCCCCC", recent)):
        (dossier / f"{ident}.webp").write_bytes(b"x")
        site.ecrire("INSERT INTO tableau_medias VALUES (?,1,?,'',?,1,1,1,?,?)", (ident, FONDATEUR, "image/webp", cree, cree))
    chef = site.g.get_member(FONDATEUR)
    assert asyncio.run(affiches._route_element(site.g, chef, {}, {"type": "metier", "cle": "cuisinier", "version": 1,
                                                                  "nom": "Cuisinier", "icone": "media/utiliseeAAAAAAAA"}))[0] == 200
    for tid, decision, ferme in ((1, "refuses", t - 200 * 86400), (2, "acceptes", t - 200 * 86400),
                                 (3, "refuses", recent), (4, "", t - 200 * 86400)):
        site.ecrire("INSERT INTO recrutements (guild_id, ticket_id, candidat_id, ferme_le, raison, decision)"
                    " VALUES (1,?,?,?,?,?)", (tid, 100 + tid, ferme, "Non admis" if tid == 4 else "", decision))
    site.ecrire("INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (1,?,'Messages','message.delete','vieux')",
                (vieux,))

    async def post(c, api, corps):
        return await _json(await c.post(f"/tableau/espace/api/{api}", json=corps, headers=avec))

    async def scenario(c):
        out = {"avant": await _json(await c.get("/tableau/espace/api/nettoyage", headers=avec))}
        out["regle"] = await post(c, "nettoyage/regle", {"cle": "affiches_corbeille", "garde_jours": 20})
        out["hors_bornes"] = await post(c, "nettoyage/regle", {"cle": "affiches_corbeille", "garde_jours": 5})
        out["texte"] = await post(c, "nettoyage/regle", {"cle": "affiches_corbeille", "garde_jours": "20"})
        out["fixe"] = await post(c, "nettoyage/regle", {"cle": "journal", "garde_jours": 90})
        out["inconnue"] = await post(c, "nettoyage/regle", {"cle": "tout", "garde_jours": 9})
        out["lancer"] = await post(c, "nettoyage/lancer", {})
        out["encore"] = await post(c, "nettoyage/lancer", {})
        return out
    out = site.http(scenario)
    st, avant = out["avant"]
    cles = [r["cle"] for r in avant["regles"]]
    assert st == 200 and cles == ["journal_messages", "journal", "tickets_archives", "transcripts", "candidatures_refusees",
                                  "affiches_corbeille", "affiches_historique", "medias", "ops", "sessions"]
    r = {x["cle"]: x for x in avant["regles"]}
    assert set(r["journal"]) == {"cle", "nom", "quoi", "garde_jours", "defaut", "min", "max", "reglable", "auto"}
    assert (r["journal"]["garde_jours"], r["journal"]["reglable"]) == (90, False)
    assert (r["affiches_corbeille"]["min"], r["affiches_corbeille"]["max"], r["affiches_corbeille"]["reglable"]) == (7, 90, True)
    assert r["tickets_archives"]["auto"] is False, "les archives de la liste : un rangement, rien n'est effacé"
    assert avant["compteurs"]["affiches_corbeille"] == 2 and avant["compteurs"]["medias"] == 3 and avant["dernier"] is None
    assert out["regle"][0] == 200 and {x["cle"]: x for x in out["regle"][1]["regles"]}["affiches_corbeille"]["garde_jours"] == 20
    assert out["regle"][1]["ok"] and out["regle"][1]["regle"]["garde_jours"] == 20
    assert out["hors_bornes"] == (400, {"erreur": "Entre 7 et 90 jours.", "champ": "garde_jours"})
    assert out["texte"][0] == 400 and out["fixe"][0] == 400 and out["inconnue"][0] == 404
    st, apres = out["lancer"]
    bilan = apres["bilan"]
    assert st == 200 and apres["dernier"] and apres["par"] == str(FONDATEUR)
    assert (bilan["affiches_corbeille"], bilan["affiches_historique"], bilan["ops"], bilan["medias"],
            bilan["candidatures_refusees"], bilan["journal_messages"]) == (1, 1, 1, 1, 2, 1)
    restantes = {x[0] for x in site.sql("SELECT id FROM rell_affiches")}
    assert restantes == {"recente-corbeille", "active-affiche"}
    assert {x[0] for x in site.sql("SELECT id FROM tableau_medias")} == {"utiliseeAAAAAAAA", "recenteCCCCCCCCC"}
    assert not (dossier / "oublieeBBBBBBBBB.webp").exists() and (dossier / "utiliseeAAAAAAAA.webp").exists()
    assert {x[0] for x in site.sql("SELECT ticket_id FROM recrutements")} == {2, 3}, \
        "refusées depuis plus de 180 jours (décision ou motif) ; acceptées et récentes gardées"
    assert out["encore"][0] == 429
    assert [(b["total"], b["par"]) for b in apres["bilans"]] == [(7, str(FONDATEUR))] and "Affiches en corbeille 1" in \
        apres["bilans"][0]["detail"], "chaque passage reste lisible (les 10 derniers)"
    ligne = next(x for x in site.journal() if x["type"] == "site.nettoyage")
    assert ligne["texte"] == "Nettoyage du site lancé par GoRipe : 7 élément(s) retiré(s)" and ligne["auteur_id"] == FONDATEUR
    assert "Affiches en corbeille : 1" in ligne["detail"]
    assert any(x["texte"].startswith("Règle de nettoyage « Affiches en corbeille » : 20 jours (avant : 30)")
               for x in site.journal())


def test_V14b_la_boucle_quotidienne_et_une_regle_en_echec(site, monkeypatch):
    async def casse(gid, jours, t):
        raise RuntimeError("disque plein")
    tableau.REGLES["casse"] = tableau._normaliser_regle({"cle": "casse", "nom": "Règle cassée", "garde_jours": 1,
                                                          "min": 1, "max": 1, "fn": casse})
    t = time.time()

    async def scenario():
        premier = await tableau.nettoyer_si_du(site.g, t)
        second = await tableau.nettoyer_si_du(site.g, t + 3600)
        lendemain = await tableau.nettoyer_si_du(site.g, t + 24 * 3600)
        return premier, second, lendemain
    premier, second, lendemain = asyncio.run(scenario())
    assert premier is not None and premier["casse"] == -1 and premier["ops"] == 0, "les autres règles passent quand même"
    assert second is None and lendemain is not None, "une fois par jour, même après un redémarrage"
    ligne = next(x for x in site.journal() if x["type"] == "site.nettoyage")
    assert ligne["texte"] == "Nettoyage du site (automatique) : rien à retirer" and ligne["gravite"] == 1
    assert "en échec : Règle cassée" in ligne["detail"]
    assert "[TABLEAU][E17] règle de nettoyage en échec" in site.journal_bot


def test_V14c_les_tickets_archives_suivent_la_regle(site):
    async def scenario():
        avant = await tableau.jours_regle(1, "tickets_archives")
        async with site.get_db() as db:
            await db.execute("INSERT INTO tableau_nettoyage VALUES (1, 'tickets_archives', 500, 0, 0)")
            await db.commit()
        return avant, await tableau.jours_regle(1, "tickets_archives"), await tableau.jours_regle(1, "journal")
    assert asyncio.run(scenario()) == (30, 90, 90), "une valeur hors bornes en base est ramenée dans les bornes"


def test_V14d_journal_sessions_transcripts_et_archives_des_tickets(site):
    """Les règles fixes : le journal (90 jours, 30 pour messages et vocal — d'un seul serveur), les sessions et liens
    expirés, les transcripts (rétention du stockage) ; le compteur des tickets rangés aux archives."""
    t = int(time.time())
    for quand, cat, guild in ((t - 100 * 86400, "Modération", 1), (t - 100 * 86400, "Modération", 2),
                              (t - 40 * 86400, "Modération", 1), (t - 40 * 86400, "Vocal", 1)):
        site.ecrire("INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (?,?,?,'x','x')", (guild, quand, cat))
    site.ecrire("INSERT INTO tableau_sessions VALUES ('perimee', 1, ?, ?, ?)", (FONDATEUR, t - 90000, t - 10))
    site.ecrire("INSERT INTO tableau_jetons VALUES ('vieux-nonce', ?)", (t - 10,))
    vivante = site.session()
    dossier = Path(transcript_store._BASE_DIR)
    dossier.mkdir(parents=True)
    vieux, neuf = dossier / ("a" * 22 + ".html"), dossier / ("b" * 22 + ".html")
    for f in (vieux, neuf):
        f.write_text("<div class='msg'></div>", encoding="utf-8")
    os.utime(vieux, (t - 400 * 86400, t - 400 * 86400))
    site.ecrire("CREATE TABLE tickets (id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER, user_id INTEGER,"
                " panel_id TEXT, claimed_by INTEGER, status TEXT, answers TEXT, created_at DATETIME)")
    site.ecrire("CREATE TABLE ticket_log_events (id INTEGER PRIMARY KEY, guild_id INTEGER, ticket_id INTEGER, kind TEXT,"
                " actor_id INTEGER, detail TEXT, created_unix INTEGER)")
    for tid, statut, ferme in ((1, "closed", t - 40 * 86400), (2, "closed", t - 3 * 86400), (3, "open", 0)):
        site.ecrire("INSERT INTO tickets VALUES (?, 1, ?, 7, 'p1', 0, ?, '{}', '2026-09-01 10:00:00')", (tid, 900 + tid, statut))
        if ferme:
            site.ecrire("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, created_unix)"
                        " VALUES (1, ?, 'close', 2, ?)", (tid, ferme))

    async def scenario():
        avant = await tableau.etat_nettoyage(1, t)
        bilan = await tableau.nettoyer(site.g, None, t)
        return avant, bilan
    avant, bilan = asyncio.run(scenario())
    assert avant["compteurs"]["tickets_archives"] == 1, "fermé depuis 40 jours (règle : 30) — l'ouvert et le récent non"
    assert avant["compteurs"]["transcripts"] == 2 and avant["compteurs"]["sessions"] == 1
    assert bilan["journal"] == 1 and bilan["journal_messages"] == 1, "ce serveur seulement, chacun sa durée"
    assert sorted(r[0] for r in site.sql("SELECT guild_id FROM registre WHERE quand < ?", (t - 30 * 86400,))) == [1, 2]
    assert bilan["sessions"] == 2 and bilan["transcripts"] == 1
    assert not vieux.exists() and neuf.exists()
    assert site.sql("SELECT COUNT(*) FROM tableau_sessions")[0][0] == 1, "la session en cours reste"
    assert asyncio.run(tableau._session(Obj(cookies={tableau.COOKIE: vivante}, headers={}, remote="1.2.3.4"))) is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  V15 — le câblage dans bot.py
# ═══════════════════════════════════════════════════════════════════════════════

def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise KeyError(nom)


def test_V15_cablage_bot_etape_boucle_supervisee():
    boot = ast.unparse(_source("_activite_boot"))
    etape = boot[boot.index("with _Etape('affiches'):"):]
    etape = etape[:etape.index("with _Etape(", 10)]
    for morceau in ("affiches.setup(get_db=get_db", "await affiches.init_db()", "await affiches.charger_depart()",
                    "tableau.monter(affiches)"):
        assert morceau in etape, morceau
    assert boot.index("with _Etape('tableau'):") < boot.index("with _Etape('affiches'):"), "le site est prêt avant"
    boucle = _source("nettoyage_site_task")
    assert any("loop" in ast.unparse(d) for d in boucle.decorator_list)
    noms = next(ast.literal_eval(n.value) for n in ARBRE.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "_SUPERVISED_LOOP_NAMES" for t in n.targets))
    assert "nettoyage_site_task" in noms, "sans le superviseur, la boucle ne démarre jamais"
    #  Le corps de la boucle : un serveur en échec n'arrête pas les autres.
    vus, erreurs = [], []

    async def nettoyer_si_du(g):
        vus.append(g.id)
        if g.id == 1:
            raise RuntimeError("base verrouillée")
    import copy
    corps = copy.deepcopy(boucle)
    corps.name, corps.decorator_list = "corps", []
    corps = ast.Module(body=[corps], type_ignores=[])
    ns = {"bot": Obj(guilds=[Obj(id=1), Obj(id=2)]), "tableau": Obj(nettoyer_si_du=nettoyer_si_du),
          "_logerr": lambda ou, ex, guild_id=0: erreurs.append((ou, type(ex).__name__, guild_id))}
    exec(compile(ast.fix_missing_locations(corps), "bot.py", "exec"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["corps"]())
    assert vus == [1, 2] and erreurs == [("site.nettoyage", "RuntimeError", 1)]
    assert "import affiches" in SRC


# ═══════════════════════════════════════════════════════════════════════════════
#  V16 — l'entrée de démonstration n'existe que dans `outils/site_local.py`
# ═══════════════════════════════════════════════════════════════════════════════

def test_V16_entree_de_demo_seulement_dans_le_site_local(tmp_path, monkeypatch):
    chemins = [r.resource.canonical for r in health_server.construire_app().router.routes()]
    assert not any("demo" in c for c in chemins), "le bot n'expose jamais d'entrée sans lien"
    for fichier in ("bot.py", "tableau.py", "health_server.py", "affiches.py"):
        texte = (RACINE / fichier).read_text(encoding="utf-8")
        assert "/tableau/demo" not in texte and "site_local" not in texte, fichier
    monkeypatch.setattr(tableau, "ROUTES", {})
    monkeypatch.setattr(tableau, "REGLES", dict(tableau.REGLES))
    monkeypatch.setattr(tableau, "_SOURCES_MEDIAS", [])
    monkeypatch.setattr(tableau, "RACINE_DONNEES", None)
    monkeypatch.setattr(tableau, "SITE", tmp_path / "pas_de_site")
    monkeypatch.setattr(transcript_store, "_BASE_DIR", transcript_store._BASE_DIR)
    import paths
    monkeypatch.setattr(paths, "_RESOLVED_BASE", paths._RESOLVED_BASE)
    import sys
    monkeypatch.syspath_prepend(str(RACINE / "outils"))
    import site_local
    from aiohttp.test_utils import TestClient, TestServer

    async def scenario():
        app, ctx = await site_local.construire(tmp_path / "local", 8790)
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/tableau/demo", allow_redirects=False)
            h = {"Cookie": f"{tableau.COOKIE}={r.cookies[tableau.COOKIE].value}"}
            ecrire = dict(h, **{"X-Tableau": "1", "Origin": "http://localhost:8790"})
            out = {"demo": (r.status, r.headers["Location"])}
            for nom, chemin in (("page", "/tableau/espace/"), ("donnees", "/tableau/espace/donnees"),
                                ("catalogue", "/tableau/espace/api/rell/catalogue"),
                                ("affiches", "/tableau/espace/api/rell/affiches"), ("roles", "/tableau/espace/api/rell/roles"),
                                ("nettoyage", "/tableau/espace/api/nettoyage"), ("fiche", "/tableau/espace/membre?id=1000")):
                r = await c.get(chemin, headers=h)
                out[nom] = (r.status, await r.text())
            r = await c.post("/tableau/espace/api/rell/affiche", headers=ecrire, json={"membre_id": "1005", "surnom": "Essai"})
            out["ecrire"] = r.status
            return out
    out = asyncio.run(scenario())
    assert out["demo"] == (303, "/tableau/espace/")
    assert all(v[0] == 200 for k, v in out.items() if k not in ("demo", "ecrire")), {k: v[0] for k, v in out.items()}
    d = json.loads(out["donnees"][1])
    assert d["tickets"]["types"] and d["sanctions"]["total"] and d["candidats"] and d["journal"]["evenements"]
    assert d["clan"]["membres"] and d["tickets"]["archives_jours"] == 30 and "erreur" not in d["salons"]
    assert len(json.loads(out["affiches"][1])["affiches"]) == 3 and json.loads(out["catalogue"][1])["elements"]
    assert out["ecrire"] == 200
    del sys.modules["site_local"]


# ═══════════════════════════════════════════════════════════════════════════════
#  V17 — les adresses du serveur HTTP et les en-têtes qui ne bougent pas
# ═══════════════════════════════════════════════════════════════════════════════

def test_V17_adresses_http_et_entetes():
    routes = {(r.method, r.resource.canonical) for r in health_server.construire_app().router.routes()}
    for attendue in (("GET", "/tableau/espace"), ("GET", "/tableau/espace/"), ("GET", "/tableau/espace/sw.js"),
                     ("GET", "/tableau/espace/s/{chemin}"), ("GET", "/tableau/espace/media/{media}"),
                     ("GET", "/tableau/espace/api/{nom}"), ("POST", "/tableau/espace/api/{nom}"),
                     ("POST", "/tableau/espace/sync"), ("GET", "/tableau/espace/donnees"), ("POST", "/tableau/espace/action"),
                     ("POST", "/tableau/espace/sortir"), ("GET", "/tableau/{jeton}"), ("GET", "/t/{token}")):
        assert attendue in routes, attendue
    assert tableau.CSP_SITE == CSP_SPEC
    assert tableau.ENTETES["Cache-Control"] == "no-store" and tableau.ENTETES["X-Robots-Tag"] == "noindex, nofollow"
    assert "script-src 'none'" in tableau.ENTETES["Content-Security-Policy"], "les pages d'erreur et le JSON : aucun script"
    assert tableau.ESPACE == "/tableau/espace/"
    #  Le contrat : chaque adresse d'affiches.py, sa méthode, et ce qui se rejoue hors ligne.
    attendu = {"rell/catalogue": {"GET": False}, "rell/catalogue/element": {"POST": True},
               "rell/catalogue/retirer": {"POST": True}, "rell/catalogue/type": {"POST": True},
               "rell/affiches": {"GET": False}, "rell/affiche": {"GET": False, "POST": True},
               "rell/affiche/retirer": {"POST": True}, "rell/affiche/restaurer": {"POST": True},
               "rell/avatar": {"POST": False}, "rell/roles": {"GET": False}, "rell/role": {"POST": False},
               "rell/roles/appliquer": {"POST": False},
               #  25/10/2026 : les rôles des métiers du clan (metiers.py) — jamais rejoués hors ligne.
               "rell/metiers/reglages": {"GET": False, "POST": False}, "rell/metiers/installer": {"POST": False},
               "rell/metiers/reconcilier": {"POST": False}}
    vu = {nom: {x["methode"]: x["hors_ligne"] for x in tableau._definitions(nom, d)}
          for nom, d in affiches.ROUTES_SITE.items()}
    assert vu == attendu
    assert {nom: [x["grave"] for x in tableau._definitions(nom, d)] for nom, d in affiches.ROUTES_SITE.items()
            if any(x["grave"] for x in tableau._definitions(nom, d))} == {"rell/role": ["roles"],
                                                                         "rell/roles/appliquer": ["roles"],
                                                                         "rell/metiers/reglages": [None, "roles"],
                                                                         "rell/metiers/installer": ["roles"],
                                                                         "rell/metiers/reconcilier": ["roles"]}


# ═══════════════════════════════════════════════════════════════════════════════
#  V18 — le module des événements se branche tel qu'il est écrit
# ═══════════════════════════════════════════════════════════════════════════════

def test_V18_la_forme_des_evenements_se_branche_et_ses_images_sont_gardees(site):
    """Ses lectures déclarent `corps_max: 0`, `grave: None` ; ses images utilisées viennent de
    `medias_utilises()` SANS argument : rien ne doit casser à la fusion."""
    vus = []

    async def lire(g, auteur, requete, corps):
        vus.append(requete)
        return 200, {"brouillons": []}

    async def brouillon(g, auteur, requete, corps):
        return 200, {"ok": True}

    class Evenements:
        ROUTES_SITE = {
            "clan/evenements": {"methode": "GET", "fn": lire, "ecriture": False, "hors_ligne": False, "corps_max": 0,
                                "grave": None},
            "clan/brouillon": {"methode": "POST", "fn": brouillon, "ecriture": True, "hors_ligne": True,
                               "corps_max": 32768, "grave": None}}

        @staticmethod
        async def medias_utilises():
            return {"evenementDDDDDDD"}
    assert tableau.monter(Evenements) == 2 and tableau.monter(Evenements.ROUTES_SITE) == 2, "les deux formes, sans conflit"
    t = int(time.time())
    dossier = tableau.dossier_site("medias")
    for ident in ("evenementDDDDDDD", "oublieeEEEEEEEEE"):
        (dossier / f"{ident}.webp").write_bytes(b"x")
        site.ecrire("INSERT INTO tableau_medias VALUES (?,1,?,'',?,1,1,1,?,?)", (ident, FONDATEUR, "image/webp",
                                                                               t - 90 * 86400, t - 90 * 86400))
    bilan = asyncio.run(tableau.nettoyer(site.g, None, t))
    assert bilan["medias"] == 1 and {x[0] for x in site.sql("SELECT id FROM tableau_medias")} == {"evenementDDDDDDD"}
    assert asyncio.run(tableau.lire_media("evenementDDDDDDD")) == (b"x", "webp")
    assert asyncio.run(tableau.lire_media("../site")) is None and asyncio.run(tableau.lire_media("absentFFFFFFFFFF")) is None
    avec = site.biscuit()

    async def scenario(c):
        r = await c.get("/tableau/espace/api/clan/evenements?x=1", headers=avec)
        return r.status
    assert site.http(scenario) == 200 and vus == [{"x": "1"}]


def test_V19_fiches_et_catalogue_pour_les_annonces_du_clan(site):
    site.catalogue()
    chef = site.g.get_member(FONDATEUR)

    async def scenario():
        await affiches._route_affiche(site.g, chef, {}, {"membre_id": "7", "surnom": "Le Requin", "grade": "Second",
                                                         "attributs": {"metier": ["navigateur", "canonnier"],
                                                                       "race": ["triton"], "faction": ["pirates"]}})
        await affiches._route_affiche(site.g, chef, {}, {"roblox_nom": "Sans_Membre", "surnom": "Personne"})
        st, rep = await affiches._route_affiche(site.g, chef, {}, {"membre_id": "8", "surnom": "Retirée"})
        await affiches._route_affiche_retirer(site.g, chef, {}, {"id": rep["affiche"]["id"]})
        return await affiches.fiches_clan(site.g), await affiches.catalogue_clan(site.g)
    fiches, cat = asyncio.run(scenario())
    assert [(f["membre_id"], f["nom"], f["metiers"], f["race"], f["faction"], f["grade"]) for f in fiches] == \
        [("7", "Kolax", ["navigateur", "canonnier"], "triton", "pirates", "Second")], \
        "une fiche par membre qui a son affiche (ni sans membre, ni à la corbeille)"
    assert set(cat) == {"race", "metier", "faction", "arme"}
    assert cat["metier"]["canonnier"] == {"nom": "Canonnier", "nom_en": "Gunner", "icone": "s/icones/rell/metier/canonnier.webp",
                                          "icone_emoji": "", "actif": True}
    assert list(cat["metier"]) == ["charpentier", "navigateur", "canonnier", "cuisinier"], "dans l'ordre du catalogue"


def test_V20_l_etape_du_bot_branche_les_evenements_s_ils_sont_la(site, monkeypatch):
    import copy
    import sys
    import types
    boot = _source("_activite_boot")
    bloc = next(n for n in boot.body if isinstance(n, ast.With)
                and ast.unparse(n.items[0].context_expr) == "_Etape('affiches')")
    fonction = ast.parse("async def etape():\n    pass").body[0]
    fonction.body = copy.deepcopy(bloc.body)
    code = compile(ast.fix_missing_locations(ast.Module(body=[fonction], type_ignores=[])), "bot.py", "exec")
    branche, purges = {}, []
    faux = types.ModuleType("evenements")
    faux.ROUTES_SITE = {}

    def brancher(**kw):
        branche.update(kw)

    async def purger(jours=60):
        purges.append(jours)
        return 3
    faux.brancher, faux.purger = brancher, purger

    async def get_db_inutile():
        raise AssertionError("jamais appelé ici")
    ns = {"affiches": Obj(setup=lambda **kw: None, init_db=_rien, charger_depart=_rien, ROUTES_SITE=affiches.ROUTES_SITE,
                          brancher_evenements=affiches.brancher_evenements),
          "tableau": tableau, "get_db": get_db_inutile, "log_staff_action": None}
    exec(code, ns)  # noqa: S102 — code du dépôt
    monkeypatch.setitem(sys.modules, "evenements", None)  # absent : rien n'est branché, rien ne casse
    asyncio.run(ns["etape"]())
    assert not branche and "evenements_passes" not in tableau.REGLES
    monkeypatch.setitem(sys.modules, "evenements", faux)
    asyncio.run(ns["etape"]())
    assert branche == {"fiches": affiches.fiches_clan, "catalogue": affiches.catalogue_clan, "media": tableau.lire_media}
    regle = tableau.REGLES["evenements_passes"]
    assert (regle["garde_jours"], regle["min"], regle["max"]) == (60, 14, 365)
    assert asyncio.run(regle["fn"](1, 45, time.time())) == 3 and purges == [45], "la durée réglée sur le site est passée"


async def _rien(*a, **k):
    return None


def test_V21_les_purges_et_les_images_des_evenements_dans_le_nettoyage(site):
    """Un module des événements qui ne donne que `PURGES` (le format du grand nettoyage) : la règle « Événements
    passés » les applique avec la durée réglée sur le site ; ses images citées par un brouillon restent."""
    import types
    module = types.ModuleType("evenements")
    module.ROUTES_SITE, module.GARDE_JOURS = {}, 30
    module.PURGES = [("événements passés du clan", "DELETE FROM clan_evenements WHERE archive_le > 0 AND archive_le < ?",
                      30, "unix"),
                     ("réponses aux événements du clan", "DELETE FROM clan_evenements_reponses WHERE evenement_id NOT IN "
                                                         "(SELECT id FROM clan_evenements)", None, None)]

    async def medias_utilises():
        return {"brouillonGGGGGGG"}
    module.medias_utilises = medias_utilises
    affiches.brancher_evenements(module)
    regle = tableau.REGLES["evenements_passes"]
    assert (regle["garde_jours"], regle["min"], regle["max"]) == (30, 14, 365)
    t = int(time.time())
    site.ecrire("CREATE TABLE clan_evenements (id INTEGER PRIMARY KEY, archive_le INTEGER)")
    site.ecrire("CREATE TABLE clan_evenements_reponses (evenement_id INTEGER, membre_id INTEGER)")
    for eid, archive in ((1, t - 50 * 86400), (2, t - 20 * 86400), (3, 0)):
        site.ecrire("INSERT INTO clan_evenements VALUES (?, ?)", (eid, archive))
        site.ecrire("INSERT INTO clan_evenements_reponses VALUES (?, 7)", (eid,))
    dossier = tableau.dossier_site("medias")
    for ident in ("brouillonGGGGGGG", "perdueHHHHHHHHHH"):
        (dossier / f"{ident}.png").write_bytes(b"x")
        site.ecrire("INSERT INTO tableau_medias VALUES (?,1,?,'',?,1,1,1,?,?)", (ident, FONDATEUR, "image/png",
                                                                               t - 90 * 86400, t - 90 * 86400))
    bilan = asyncio.run(tableau.nettoyer(site.g, None, t))
    assert bilan["evenements_passes"] == 2, "l'événement archivé depuis 50 jours et sa réponse"
    assert [r[0] for r in site.sql("SELECT id FROM clan_evenements ORDER BY id")] == [2, 3]
    assert [r[0] for r in site.sql("SELECT evenement_id FROM clan_evenements_reponses ORDER BY 1")] == [2, 3]
    assert bilan["medias"] == 1 and {x[0] for x in site.sql("SELECT id FROM tableau_medias")} == {"brouillonGGGGGGG"}
    assert (dossier / "brouillonGGGGGGG.png").exists() and not (dossier / "perdueHHHHHHHHHH.png").exists()
    #  Rebranché (le bot redémarre l'étape) : rien en double, la règle déjà réglée reste.
    affiches.brancher_evenements(module)
    assert list(tableau.REGLES).count("evenements_passes") == 1
