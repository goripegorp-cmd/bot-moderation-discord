"""La table d'accès du site (26/10/2026, sécurité) — CHAQUE adresse du serveur, pour CHAQUE portée.

« Seuls lui et la direction entrent dans l'administration et ses actions ; un membre du clan ou un candidat n'a que ses
propres droits de lecture. » Sur le VRAI site local (`outils/site_local.py` : le serveur du bot, tous ses modules, un
faux Discord), comme `test_site_equipage.py` :

A1 la table est complète : toute adresse du serveur du bot (aiohttp), toute adresse du registre (`ROUTES_SITE`), toute
   lecture de l'équipage est DÉCLARÉE ici — une adresse ajoutée sans être déclarée fait échouer ce test, une
   déclaration sans adresse aussi.
A2 chaque case de la table, générée du registre : sans session, « equipage », « candidat », « tout » — la réponse du
   serveur. « candidat » : la vraie portée si elle existe, sinon une portée FUTURE simulée (refusée partout où la table
   ne l'ouvre pas). Les équipes : écrites par la tête seule ; l'équipage reçoit 403 sur toute écriture et sur la lecture
   des équipes de la direction.
A3 les fichiers de `site/`, un par un : publics (l'image, la vitrine), de l'équipage, ou de la tête seule — d'après ce
   que chaque PAGE charge réellement (et non d'après la liste de tableau.py, qu'on vérifie ainsi).
A4 la WebSocket du direct : la tête seule.
A5 la vitrine publique : GET seulement (toute écriture → 405), aucun cookie lu ni posé, noindex, cadence par adresse IP
   (la PREMIÈRE de X-Forwarded-For), des champs publics seulement (jamais un identifiant ni un nom Discord).
A6 les écritures sans l'en-tête de la page, d'une autre origine, d'un autre site : refusées, rien d'écrit.
A7 corps trop gros, JSON illisible ou piégé : refusés proprement (jamais une erreur 500), rien d'écrit.
A8 les chemins de fichiers normalisés : aucun pas hors de `site/`, aucun fichier de la tête par un détour.
A9 les images au-delà des limites : refusées.
A10 les en-têtes de sécurité, sur CHAQUE réponse de la table.
A11 /stats : aucune donnée personnelle.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time

import pytest

import test_site_equipage as _socle
from test_site_equipage import KOLAX, MIRA, ORIGINE, RACINE

local = _socle.local   # le même site local que test_site_equipage.py (un à part pour ce fichier : portée « module »)

# ═══════════════════════════════════════════════════════════════════════════════
#  LA TABLE
# ═══════════════════════════════════════════════════════════════════════════════
#  Chaque adresse du serveur du bot (méthode, gabarit aiohttp ; HEAD suit GET) → sa règle :
#    public        même réponse pour tous ; une session n'y change rien (les surfaces publiques du bot)
#    vitrine       la vitrine publique : GET pour tous, aucune session lue ni posée ; toute écriture → 405 (A5)
#    entree        le lien signé du bouton : un faux lien → 403 pour tous (le bon lien : SA page, A2b)
#    renvoi        une redirection sans donnée, pour tous
#    tete          la tête seule ; sans session, « equipage », « candidat » → 403
#    tete_fichier  la tête seule ; les autres : 404, comme un fichier absent
#    websocket     la tête seule (A4)
#    registre      /tableau/espace/api/<nom> : adresse par adresse, d'après REGISTRE
#    fichiers      /tableau/espace/s/<chemin> : fichier par fichier, d'après ce que chaque page charge (A3)
#    medias        /tableau/espace/media/<id> : la tête ; l'équipage, seulement les images que SES lectures citent
#    sortie        se déconnecter : pour tous (sa propre session, rien d'autre)
#    equipage      le site de l'équipage : « equipage » et la tête
#    lectures      /tableau/equipage/api/<nom> : lecture par lecture, d'après LECTURES
#    lecture_seule POST /tableau/equipage/api/… : refusé à tous
ADRESSES = {
    ("GET", "/"): "public",
    ("GET", "/health"): "public",
    ("GET", "/stats"): "public",
    ("GET", "/t/{token}"): "public",
    ("GET", "/ta/{token}/{idx}"): "public",
    ("GET", "/v/{nom}"): "public",
    ("GET", "/websub/youtube"): "public",
    ("POST", "/websub/youtube"): "public",
    ("GET", "/equipage"): "vitrine",
    ("GET", "/equipage/"): "vitrine",
    ("GET", "/equipage/donnees"): "vitrine",
    ("GET", "/equipage/banniere.png"): "vitrine",
    ("GET", "/equipage/image/{jeton}"): "vitrine",
    ("GET", "/tableau/{jeton}"): "entree",
    ("GET", "/tableau/espace"): "renvoi",
    ("GET", "/tableau/equipage"): "renvoi",
    ("GET", "/tableau/espace/"): "tete",
    ("GET", "/tableau/espace/donnees"): "tete",
    ("GET", "/tableau/espace/membre"): "tete",
    ("GET", "/tableau/espace/recherche"): "tete",
    ("GET", "/tableau/espace/export"): "tete",
    ("GET", "/tableau/espace/conversation"): "tete",
    ("POST", "/tableau/espace/action"): "tete",
    ("POST", "/tableau/espace/sync"): "tete",
    ("GET", "/tableau/espace/sw.js"): "tete_fichier",
    ("GET", "/tableau/espace/direct"): "websocket",
    ("GET", "/tableau/espace/api/{nom}"): "registre",
    ("POST", "/tableau/espace/api/{nom}"): "registre",
    ("GET", "/tableau/espace/s/{chemin}"): "fichiers",
    ("GET", "/tableau/espace/media/{media}"): "medias",
    ("POST", "/tableau/espace/sortir"): "sortie",
    ("GET", "/tableau/equipage/"): "equipage",
    ("GET", "/tableau/equipage/api/{nom}"): "lectures",
    ("POST", "/tableau/equipage/api/{nom}"): "lecture_seule",
}
#  Le registre : chaque adresse (« MÉTHODE nom ») et la portée qui l'obtient. Aujourd'hui, la tête seule partout —
#  l'équipage lit par /tableau/equipage/api/… et n'écrit nulle part. Une adresse ajoutée au registre s'ajoute ICI,
#  avec sa portée (une autre que « tete » se décide ici, et `_verifier` doit l'ouvrir).
REGISTRE = {"tete": frozenset(x.strip() for x in """
    GET clan/apercu
    GET clan/evenements
    POST clan/annuler
    POST clan/brouillon
    POST clan/modifier
    POST clan/publier
    POST clan/supprimer_brouillon
    GET direct/etat
    POST direct/envoi
    GET equipage/equipes
    POST equipage/equipe
    POST equipage/equipe/deplacer
    POST equipage/equipe/supprimer
    POST equipage/actualite
    POST equipage/actualite/retirer
    POST equipage/bloc
    POST equipage/bloc/deplacer
    POST equipage/bloc/public
    POST equipage/bloc/supprimer
    POST equipage/bloc/visible
    POST equipage/vitrine/affiche
    POST media
    GET nettoyage
    POST nettoyage/lancer
    POST nettoyage/regle
    GET recrutement/banque
    GET recrutement/dossier
    GET recrutement/modeles
    GET recrutement/suivi
    POST recrutement/corriger
    POST recrutement/decision
    POST recrutement/etape1
    POST recrutement/liens
    POST recrutement/modele
    POST recrutement/modele/retirer
    POST recrutement/question
    POST recrutement/question/retirer
    POST recrutement/reglages
    GET rell/affiche
    GET rell/affiches
    GET rell/catalogue
    GET rell/metiers/reglages
    GET rell/roles
    POST rell/affiche
    POST rell/affiche/restaurer
    POST rell/affiche/retirer
    POST rell/avatar
    POST rell/catalogue/element
    POST rell/catalogue/retirer
    POST rell/catalogue/type
    POST rell/metiers/installer
    POST rell/metiers/reconcilier
    POST rell/metiers/reglages
    POST rell/role
    POST rell/role/renommer
    POST rell/roles/appliquer
    GET securite
    POST securite/fermer_autres
    GET textes
    GET textes/site
    POST texte
    POST texte/defaut
""".strip().splitlines())}
#  Les lectures du site de l'équipage (`monter_equipage`) : « equipage » et la tête.
LECTURES = {"accueil": "equipage", "depart": "equipage", "equipage": "equipage"}
#  Les ÉQUIPES du clan (27/10/2026) : écrites par la tête seule ; la portée « equipage » reçoit 403 partout ici.
EQUIPES = ("GET equipage/equipes", "POST equipage/equipe", "POST equipage/equipe/supprimer", "POST equipage/equipe/deplacer")
#  Le site local seulement (jamais dans le bot : tests/test_site_v2_serveur.py, V16) — hors de la table.
DEMO = {("GET", "/tableau/demo"), ("GET", "/tableau/demo/discord")}
#  Les refus de la porte (`tableau._verifier`) : un « tout » ne doit JAMAIS les lire.
REFUS_PORTE = {"Session expirée.", "Réservé au fondateur et à la direction.", "Accès retiré.", "Accès suspendu."}
#  L'image du site : publique (le navigateur lit le manifeste et ses icônes sans cookie).
IMAGE_PUBLIQUE = ("polices/", "icones/", "textures/", "ornements/", "logos/")
FICHIERS_PUBLICS = ("app-192.png", "app-512.png", "manifest.webmanifest")
ENTETES_PARTOUT = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                   "Strict-Transport-Security": "max-age=31536000"}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les portées et les outils
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cadences_libres(monkeypatch):
    """La table fait des centaines de requêtes d'une même session : les cadences ont leurs propres tests."""
    import site_vitrine
    import tableau
    for nom in ("LIMITE_REQUETES", "LIMITE_ECRITURES", "LIMITE_STATIQUES", "LIMITE_MEDIAS"):
        monkeypatch.setattr(tableau, nom, 10 ** 6)
    tableau._essais.clear()
    tableau._cadence.clear()
    site_vitrine._passages.clear()
    yield
    tableau._essais.clear()
    tableau._cadence.clear()
    site_vitrine._passages.clear()


@pytest.fixture
def portees(local, monkeypatch):
    """{portée : en-têtes} — sans session, l'équipage (Kolax), un candidat, la tête (le fondateur). « candidat » : la
    vraie portée si elle existe ; sinon une portée FUTURE, ajoutée ici le temps du test (refusée partout par défaut)."""
    import tableau
    if "candidat" not in tableau.PORTEES:
        monkeypatch.setattr(tableau, "PORTEES", tuple(tableau.PORTEES) + ("candidat",))
    tete, _a = local.entrer("/tableau/demo")
    equipage, arrivee = local.entrer("/tableau/demo?qui=equipage")
    assert arrivee == "/tableau/equipage/"
    sid = local.faire(tableau._ouvrir_session(1, MIRA, int(time.time()) + 3600, portee="candidat"))
    return {"anonyme": {}, "equipage": equipage, "candidat": {"Cookie": f"{tableau.COOKIE}={sid}"}, "tout": tete}


def _requete(local, methode, chemin, h=None, data=None, entetes=None, json_=None):
    """(statut, corps en octets, en-têtes) — corps brut (`data`) ou JSON."""
    async def f():
        r = await local.client.request(methode, chemin, headers=dict(h or {}, **(entetes or {})), data=data, json=json_,
                                       allow_redirects=False)
        return r.status, await r.read(), r.headers
    return local.faire(f())


def _erreur(corps) -> str:
    try:
        d = json.loads(corps)
    except ValueError:
        return ""
    return str(d.get("erreur") or d.get("message") or "") if isinstance(d, dict) else ""


def _routeur():
    """(méthode, gabarit) de chaque adresse du serveur du BOT (HEAD suit GET)."""
    import health_server
    return {(r.method, r.resource.canonical) for r in health_server.construire_app().router.routes()
            if r.method in ("GET", "POST")}


def _registre() -> set:
    import tableau
    return {f"{m} {n}" for n, par in {**tableau.ROUTES, **tableau._INTERNES}.items() for m in par}


def _charge_par(page: str) -> set:
    """Ce que `site/<page>` charge : ses scripts, leur graphe d'imports statiques, ses feuilles de style."""
    import tableau
    texte = (tableau.SITE / page).read_text(encoding="utf-8")

    def deps(f):
        t = (tableau.SITE / f).read_text(encoding="utf-8")
        return set(re.findall(r'from\s+"\./([^"]+)"', t)) | set(re.findall(r'import\s+"\./([^"]+)"', t))
    vus, pile = set(), list(re.findall(r'<script[^>]+src="/tableau/espace/s/([A-Za-z0-9_.-]+\.js)', texte))
    while pile:
        f = pile.pop()
        if f not in vus:
            vus.add(f)
            pile.extend(deps(f))
    return vus | set(re.findall(r'/tableau/espace/s/([A-Za-z0-9_-]+\.css)', texte))


def _lecteurs_attendus(rel: str) -> set:
    """Qui DOIT lire ce fichier de `site/`, d'après ce que chaque page charge (indépendamment de tableau.py)."""
    if rel.startswith(IMAGE_PUBLIQUE) or rel in FICHIERS_PUBLICS or rel in _charge_par("vitrine.html"):
        return {"anonyme", "equipage", "candidat", "tout"}
    if rel in _charge_par("equipage.html"):
        return {"equipage", "tout"}
    return {"tout"}


def _verifier_entetes(chemin, st, entetes, vus: list):
    """A10 : les en-têtes de base, sur chaque réponse."""
    for k, v in ENTETES_PARTOUT.items():
        assert entetes.get(k) == v, f"{chemin} ({st}) : {k} = {entetes.get(k)!r}"
    assert entetes.get("X-Frame-Options") == "DENY", f"{chemin} : X-Frame-Options"
    assert entetes.get("Cross-Origin-Resource-Policy") in ("same-origin", "cross-origin"), chemin
    assert entetes.get("Server") == "capitainerie", f"{chemin} : le serveur dit son nom ou sa version"
    if "text/html" in (entetes.get("Content-Type") or ""):
        csp = entetes.get("Content-Security-Policy") or ""
        assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp, f"{chemin} : CSP d'une page HTML"
    vus.append(chemin)


# ═══════════════════════════════════════════════════════════════════════════════
#  A1 — la table est complète
# ═══════════════════════════════════════════════════════════════════════════════

def test_A1_toute_adresse_du_serveur_est_declaree(local):
    import tableau
    routeur = _routeur()
    assert DEMO.isdisjoint(routeur), "l'entrée de démonstration n'existe que dans outils/site_local.py"
    sans_regle = sorted(routeur - set(ADRESSES))
    assert not sans_regle, (f"adresse(s) du serveur sans règle dans la table d'accès : {sans_regle} — la déclarer dans "
                            "ADRESSES (tests/test_acces_site.py) avec ce que chaque portée doit en obtenir")
    assert not sorted(set(ADRESSES) - routeur), f"règle(s) sans adresse : {sorted(set(ADRESSES) - routeur)}"
    declares = set().union(*REGISTRE.values())
    assert not sorted(_registre() - declares), (f"adresse(s) du registre non déclarée(s) : {sorted(_registre() - declares)}"
                                                " — l'ajouter à REGISTRE avec la portée qui l'obtient")
    assert not sorted(declares - _registre()), f"déclarée(s) sans adresse : {sorted(declares - _registre())}"
    assert set(tableau.ROUTES_EQUIPAGE) == set(LECTURES), f"lectures de l'équipage : {sorted(tableau.ROUTES_EQUIPAGE)}"
    assert set(EQUIPES) <= declares, "les équipes du clan sont dans le registre"
    #  Le site local monte EXACTEMENT les adresses du bot, plus sa seule entrée de démonstration.
    assert {(r.method, r.resource.canonical) for r in local.client.server.app.router.routes()
            if r.method in ("GET", "POST")} == routeur | DEMO


# ═══════════════════════════════════════════════════════════════════════════════
#  A2 — chaque case de la table
# ═══════════════════════════════════════════════════════════════════════════════

def _cases(local):
    """(règle, méthode, chemin, corps JSON) : chaque adresse concrète de la table, générée du registre."""
    import tableau
    jeton_faux = tableau.jeton(1, KOLAX, "equipage") + "x"
    out = [
        ("public", "GET", "/", None), ("public", "GET", "/health", None), ("public", "GET", "/stats", None),
        ("public", "GET", "/t/" + "A" * 22, None), ("public", "GET", "/ta/" + "A" * 22 + "/0", None),
        ("public", "GET", "/v/inconnu.png", None), ("public", "GET", "/websub/youtube", None),
        ("public", "POST", "/websub/youtube", {}),
        ("vitrine", "GET", "/equipage", None), ("vitrine", "GET", "/equipage/", None),
        ("vitrine", "GET", "/equipage/donnees", None), ("vitrine", "GET", "/equipage/banniere.png", None),
        ("vitrine", "GET", "/equipage/image/" + "A" * 22, None),
        ("entree", "GET", "/tableau/" + jeton_faux, None),
        ("renvoi", "GET", "/tableau/espace", None), ("renvoi", "GET", "/tableau/equipage", None),
        ("tete", "GET", "/tableau/espace/", None), ("tete", "GET", "/tableau/espace/donnees", None),
        ("tete", "GET", f"/tableau/espace/membre?id={KOLAX}", None), ("tete", "GET", "/tableau/espace/recherche?q=a", None),
        ("tete", "GET", "/tableau/espace/export?quoi=journal", None), ("tete", "GET", "/tableau/espace/conversation?ticket=1", None),
        ("tete", "POST", "/tableau/espace/action", {"action": "inconnue"}), ("tete", "POST", "/tableau/espace/sync", {"ops": []}),
        ("tete_fichier", "GET", "/tableau/espace/sw.js", None),
        ("equipage", "GET", "/tableau/equipage/", None),
        ("lecture_seule", "POST", "/tableau/equipage/api/equipage", {}),
        ("lecture_seule", "POST", "/tableau/equipage/api/accueil", {"type": "texte"}),
    ]
    for portee, adresses in REGISTRE.items():
        for a in sorted(adresses):
            m, nom = a.split(" ", 1)
            out.append(("registre:" + portee, m, f"/tableau/espace/api/{nom}", {} if m == "POST" else None))
    out.append(("registre:tete", "GET", "/tableau/espace/api/inconnue/x", None))   # même une adresse inconnue : la porte d'abord
    for nom, portee in LECTURES.items():
        out.append(("lectures:" + portee, "GET", f"/tableau/equipage/api/{nom}", None))
    out.append(("lectures:equipage", "GET", "/tableau/equipage/api/inconnue", None))
    return out


def _admis(qui, regle) -> bool:
    """La règle ouvre-t-elle l'adresse à cette portée ?"""
    if regle in ("public", "vitrine", "entree", "renvoi", "sortie"):
        return True
    if regle in ("tete", "tete_fichier", "websocket", "registre:tete"):
        return qui == "tout"
    if regle in ("equipage", "lectures:equipage"):
        return qui in ("equipage", "tout")
    if regle == "lecture_seule":
        return False
    raise AssertionError(f"règle inconnue : {regle}")


def test_A2_chaque_case_de_la_table(local, portees):
    vus, statuts = [], {}
    for regle, methode, chemin, corps in _cases(local):
        par_portee = {}
        for qui, h in portees.items():
            st, rep, e = _requete(local, methode, chemin, h, entetes=ORIGINE if methode == "POST" else None, json_=corps)
            par_portee[qui] = st
            texte = rep.decode("utf-8", "replace")
            _verifier_entetes(chemin, st, e, vus)
            assert st < 500, f"{qui} {methode} {chemin} → {st} : {texte[:200]}"
            if regle in ("public", "vitrine", "entree", "renvoi"):
                assert "Set-Cookie" not in e or regle == "entree", f"{chemin} pose un cookie"
                continue
            if _admis(qui, regle):
                assert st not in (401, 403) and _erreur(rep) not in REFUS_PORTE, \
                    f"{qui} {methode} {chemin} → {st} « {_erreur(rep)} » : la règle {regle} lui ouvre l'adresse"
            else:
                attendu = (404,) if regle == "tete_fichier" else (403,)
                assert st in attendu, f"{qui} {methode} {chemin} → {st} : la règle {regle} le lui ferme ({texte[:160]})"
                assert len(rep) < 4096 and "Kolax_RS" not in texte and _socle.SECRET not in texte, \
                    f"{qui} {methode} {chemin} : un refus qui laisse passer des données"
        statuts[(methode, chemin)] = par_portee
        if regle in ("public", "vitrine", "entree", "renvoi"):
            assert len(set(par_portee.values())) == 1, f"{methode} {chemin} : la session y change la réponse {par_portee}"
    #  Les équipes (le coordinateur, 27/10) : écrites par la tête seule ; l'équipage reçoit 403 sur toute écriture ET sur
    #  la lecture des équipes de la direction.
    for a in EQUIPES:
        m, nom = a.split(" ", 1)
        st = statuts[(m, f"/tableau/espace/api/{nom}")]
        assert st["equipage"] == st["candidat"] == st["anonyme"] == 403 and st["tout"] not in (401, 403), (a, st)
    assert statuts[("GET", "/tableau/espace/")] == {"anonyme": 403, "equipage": 403, "candidat": 403, "tout": 200}
    assert statuts[("GET", "/tableau/equipage/")] == {"anonyme": 403, "equipage": 200, "candidat": 403, "tout": 200}
    assert statuts[("GET", "/equipage")] == {"anonyme": 200, "equipage": 200, "candidat": 200, "tout": 200}
    assert len(vus) >= 4 * 90, len(vus)


def test_A2b_le_bon_lien_ouvre_SA_page_et_aucune_autre(local):
    """Le lien signé : « tout » pour la tête → la Capitainerie ; « equipage » pour un membre du clan → SON site ; un lien
    « tout » pour quelqu'un hors de la tête, ou de l'équipage pour quelqu'un hors du clan → refusé."""
    import tableau
    from test_site_equipage import BARBE, DIRECTION, FONDATEUR
    for uid, portee, attendu in ((FONDATEUR, "tout", (303, tableau.ESPACE)), (DIRECTION, "tout", (303, tableau.ESPACE)),
                                 (KOLAX, "equipage", (303, tableau.EQUIPAGE)), (KOLAX, "tout", (403, None)),
                                 (BARBE, "equipage", (403, None)), (BARBE, "tout", (403, None))):
        st, _c, e = _requete(local, "GET", "/tableau/" + tableau.jeton(1, uid, portee))
        assert (st, e.get("Location")) == attendu, (uid, portee, st)
        assert ("Set-Cookie" in e) == (st == 303), "un cookie seulement pour un lien valable"


# ═══════════════════════════════════════════════════════════════════════════════
#  A3 — les fichiers de site/, un par un
# ═══════════════════════════════════════════════════════════════════════════════

def test_A3_chaque_fichier_du_site_a_ses_lecteurs(local, portees):
    import tableau
    fichiers = [rel for rel, _p, _t, _d in tableau._fichiers_site() if rel.rsplit(".", 1)[-1].lower() in tableau.TYPES_STATIQUES]
    assert len(fichiers) >= 60 and "app.js" in fichiers and "vitrine.js" in fichiers, len(fichiers)
    vus, comptes = [], {"public": 0, "equipage": 0, "tete": 0}
    for rel in fichiers:
        lecteurs = _lecteurs_attendus(rel)
        comptes["public" if "anonyme" in lecteurs else "equipage" if "equipage" in lecteurs else "tete"] += 1
        for qui, h in portees.items():
            st, rep, e = _requete(local, "GET", f"/tableau/espace/s/{rel}?v=1", h)
            _verifier_entetes(rel, st, e, vus)
            if qui in lecteurs:
                assert st == 200, f"{qui} ne lit pas {rel} ({st})"
                cache = e.get("Cache-Control", "")
                assert cache.startswith("public" if "anonyme" in lecteurs else "private"), (rel, cache)
            else:
                assert (st, rep) == (404, b"Introuvable."), f"{qui} lit {rel} ({st})"
    #  Le code PROPRE à la Capitainerie ne sort jamais de la tête ; la vitrine et l'image sont publiques.
    assert comptes["tete"] >= 15 and comptes["public"] >= 30 and comptes["equipage"] >= 1, comptes
    for propre in ("app.js", "securite.js", "discord.js", "clan.js", "recrutement.js", "fiche.js", "textes.js", "direct.js",
                   "equipes_admin.js", "capitainerie.js", "annonces.js", "accueil.js", "recherche.js", "rangement.js", "mode.js"):
        assert _lecteurs_attendus(propre) == {"tout"}, propre
    #  Les pages ne sont JAMAIS servies comme des fichiers (seulement par leur adresse, avec leur porte).
    for page in ("index.html", "equipage.html", "vitrine.html"):
        for qui, h in portees.items():
            assert _requete(local, "GET", f"/tableau/espace/s/{page}", h)[0] == 404, (page, qui)


# ═══════════════════════════════════════════════════════════════════════════════
#  A4 — la WebSocket du direct
# ═══════════════════════════════════════════════════════════════════════════════

def test_A4_la_websocket_du_direct_la_tete_seule(local, portees):
    import aiohttp

    async def essai(h):
        try:
            ws = await local.client.ws_connect("/tableau/espace/direct", headers=h, origin="http://localhost:8790")
        except aiohttp.WSServerHandshakeError as ex:
            return ex.status
        await ws.close()
        return 101
    out = {qui: local.faire(essai(h)) for qui, h in portees.items()}
    assert out == {"anonyme": 403, "equipage": 403, "candidat": 403, "tout": 101}, out
    #  Même la tête : d'une autre origine, refusée.
    async def ailleurs():
        try:
            await local.client.ws_connect("/tableau/espace/direct", headers=portees["tout"], origin="https://pirate.exemple")
        except aiohttp.WSServerHandshakeError as ex:
            return ex.status
        return 101
    assert local.faire(ailleurs()) == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  A5 — la vitrine publique
# ═══════════════════════════════════════════════════════════════════════════════

VITRINE = ("/equipage", "/equipage/", "/equipage/donnees", "/equipage/banniere.png", "/equipage/image/" + "A" * 22)


def test_A5_la_vitrine_get_seulement_sans_cookie_noindex(local, portees):
    for chemin in VITRINE:
        for methode in ("POST", "PUT", "DELETE", "PATCH"):
            for qui, h in portees.items():
                st, _c, e = _requete(local, methode, chemin, h, entetes=ORIGINE, json_={})
                assert st == 405, (methode, chemin, qui, st)
                assert "noindex" in e.get("X-Robots-Tag", "") and "Set-Cookie" not in e
        reponses = {}
        for qui, h in portees.items():
            st, corps, e = _requete(local, "GET", chemin, h)
            assert "noindex" in e.get("X-Robots-Tag", ""), (chemin, qui)
            assert "Set-Cookie" not in e, f"{chemin} pose un cookie ({qui})"
            reponses[qui] = (st, hashlib.sha256(corps).hexdigest() if chemin.endswith("donnees") else None)
        assert len(set(reponses.values())) == 1, f"{chemin} : une session y change quelque chose {reponses}"
    assert _requete(local, "GET", "/equipage/donnees")[0] == 200


def test_A5b_la_vitrine_cadence_par_la_premiere_adresse_ip(local, monkeypatch):
    import site_vitrine
    monkeypatch.setitem(site_vitrine.LIMITES, "donnees", 3)
    ip = {"X-Forwarded-For": "203.0.113.9, 10.1.1.1"}
    assert [_requete(local, "GET", "/equipage/donnees", ip)[0] for _ in range(3)] == [200, 200, 200]
    st, _c, e = _requete(local, "GET", "/equipage/donnees", ip)
    assert st == 429 and "noindex" in e.get("X-Robots-Tag", "")
    assert _requete(local, "GET", "/equipage/donnees", {"X-Forwarded-For": "203.0.113.9, 10.7.7.7"})[0] == 429, \
        "la PREMIÈRE adresse compte (la dernière est celle du relais, partagée)"
    assert _requete(local, "GET", "/equipage/donnees", {"X-Forwarded-For": "198.51.100.4, 10.1.1.1"})[0] == 200
    #  Une session ne contourne pas la cadence (aucun cookie n'est lu).
    tete, _a = local.entrer("/tableau/demo")
    assert _requete(local, "GET", "/equipage/donnees", dict(tete, **ip))[0] == 429


def _chaines(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v)
    elif isinstance(x, (str, int, float)) and not isinstance(x, bool):
        yield str(x)


def test_A5c_la_vitrine_ne_montre_que_des_champs_publics(local):
    st, corps, _e = _requete(local, "GET", "/equipage/donnees")
    assert st == 200
    d = json.loads(corps)
    chaines = list(_chaines(d))
    tout = "\n".join(chaines)
    assert not re.search(r"\d{15,}", tout), "un identifiant Discord (ou tout nombre de 15 chiffres) dans la vitrine"
    for discord_ in ("discordapp", "cdn.discord", "media.discord"):
        assert discord_ not in tout.lower(), "un avatar ou une image de Discord dans la vitrine"
    for cle in ("membre_id", "notes", "cree_par", "maj_par", "historique", "roblox_id"):
        assert f"\n{cle}\n" not in f"\n{tout}\n", cle
    #  Aucun nom Discord. Là où paraissent des personnes (affiches, équipes, accueil), aucune valeur n'est le nom Discord
    #  d'un membre — sauf s'il est AUSSI un champ public de son affiche (pseudo Roblox, surnom, grade) ; et nulle part
    #  un nom Discord en deux mots (« Capitaine Direction », « Anne Bonny »…), qui ne se confond avec rien.
    publics = {str(s) for a in d.get("affiches", [])
               for s in (a.get("surnom"), (a.get("roblox") or {}).get("nom"), a.get("grade")) if s}
    noms = {n for m in local.g.members for n in (m.display_name, m.name) if n}
    personnes = set(_chaines({k: d.get(k) for k in ("affiches", "equipes", "accueil")}))
    fuites = sorted((personnes & noms) - publics)
    assert not fuites, f"nom(s) Discord sur la vitrine : {fuites}"
    for nom in noms:
        if " " in nom.strip():
            assert nom not in tout, f"le nom Discord « {nom} » sort sur la vitrine"
    for a in d.get("affiches", []):
        assert set(a) == {"id", "roblox", "surnom", "prime", "niveau", "grade", "statut", "attributs"}, sorted(a)


# ═══════════════════════════════════════════════════════════════════════════════
#  A6 — les écritures : l'en-tête de la page, la même origine, le même site
# ═══════════════════════════════════════════════════════════════════════════════

def _empreinte(local) -> dict:
    """{table : empreinte} — sauf ce qu'une simple visite change (sessions, appareils, liens, journal, suspensions).
    Prise une fois la base au calme : les travaux de fond des tests d'avant (rôles des métiers…) finissent d'abord."""
    import asyncio

    def prendre():
        out = {}
        for (table,) in local.sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if table in ("tableau_sessions", "tableau_appareils", "tableau_jetons", "registre", "tableau_blocages"):
                continue
            out[table] = hashlib.sha256(json.dumps(local.sql(f"SELECT * FROM {table} ORDER BY rowid"), default=str)
                                        .encode()).hexdigest()
        return out
    avant = prendre()
    for _ in range(10):
        local.faire(asyncio.sleep(0.3))
        maintenant = prendre()
        if maintenant == avant:
            return maintenant
        avant = maintenant
    return avant


def _ecritures() -> list:
    """Chaque adresse qui écrit : le registre (POST), les actions, la synchronisation, la déconnexion."""
    out = [f"/tableau/espace/api/{a.split(' ', 1)[1]}" for a in sorted(set().union(*REGISTRE.values())) if a.startswith("POST ")]
    return out + ["/tableau/espace/action", "/tableau/espace/sync", "/tableau/espace/sortir"]


def test_A6_une_ecriture_d_ailleurs_est_refusee_et_rien_n_est_ecrit(local):
    tete, _a = local.entrer("/tableau/demo")
    avant = _empreinte(local)
    variantes = {
        "sans l'en-tête de la page": {"Origin": "http://localhost:8790", "Sec-Fetch-Site": "same-origin"},
        "d'une autre origine": dict(ORIGINE, Origin="https://pirate.exemple"),
        "d'un autre site": dict(ORIGINE, **{"Sec-Fetch-Site": "cross-site"}),
        "d'un sous-domaine": dict(ORIGINE, Origin="http://pirate.localhost:8790"),
        "origine nulle": dict(ORIGINE, Origin="null"),
    }
    corps = {"action": "moderer", "membre": str(KOLAX), "sanction": "ban", "ops": [], "id": "x", "nom": "Pirates"}
    n = 0
    for chemin in _ecritures():
        for nom, entetes in variantes.items():
            st, rep, _e = _requete(local, "POST", chemin, tete, entetes=entetes, json_=corps)
            assert st == 400, f"{chemin} {nom} → {st} {rep[:120]!r}"
            n += 1
    assert n >= 5 * 40, n
    assert _empreinte(local) == avant, "une écriture refusée a laissé une trace en base"
    #  La session est toujours là (la déconnexion refusée n'a rien coupé).
    assert _requete(local, "GET", "/tableau/espace/donnees", tete)[0] == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  A7 — corps trop gros, JSON illisible ou piégé
# ═══════════════════════════════════════════════════════════════════════════════

def test_A7_corps_trop_gros_et_json_pieges_refuses_proprement(local):
    import tableau
    tete, _a = local.entrer("/tableau/demo")
    avant = _empreinte(local)
    routes = {nom: d["POST"] for nom, d in {**tableau.ROUTES, **tableau._INTERNES}.items() if "POST" in d}
    assert len(routes) >= 40
    for nom, route in sorted(routes.items()):
        chemin = f"/tableau/espace/api/{nom}"
        trop = json.dumps({"x": "a" * route["corps_max"]}).encode()
        st, rep, _e = _requete(local, "POST", chemin, tete, data=trop, entetes=dict(ORIGINE, **{"Content-Type": "application/json"}))
        assert st == 413, f"{nom} : un corps de {len(trop)} octets (max {route['corps_max']}) → {st}"
        profondeur = max(1, min(3000, (route["corps_max"] - 2) // 2))
        for brut in (b"{pas du json", b"[1, 2]", b'"texte"', b"\xff\xfe\x00{", b"{" * 10, b"[" * profondeur + b"]" * profondeur,
                     b'{"a": ' * 2000 + b"1" + b"}" * 2000):
            if len(brut) > route["corps_max"]:
                continue
            st, rep, _e = _requete(local, "POST", chemin, tete, data=brut, entetes=dict(ORIGINE, **{"Content-Type": "application/json"}))
            assert st == 400 and _erreur(rep) == "Corps illisible.", f"{nom} {brut[:12]!r} → {st} {rep[:100]!r}"
    #  Un corps envoyé par morceaux (sans longueur annoncée) : borné pareil.
    blocs = routes["texte"]["corps_max"] // 1024 + 16

    async def morceaux():
        for _ in range(blocs):
            yield b"a" * 1024
    st, _r, _e = _requete(local, "POST", "/tableau/espace/api/texte", tete, data=morceaux(), entetes=ORIGINE)
    assert st == 413
    #  La synchronisation et les actions.
    st, _r, _e = _requete(local, "POST", "/tableau/espace/sync", tete, data=b"{" * 5000 + b"}" * 5000,
                          entetes=dict(ORIGINE, **{"Content-Type": "application/json"}))
    assert st == 400
    st, _r, _e = _requete(local, "POST", "/tableau/espace/sync", tete, data=b"x" * (tableau.SYNC_CORPS_MAX + 1),
                          entetes=dict(ORIGINE, **{"Content-Type": "application/json"}))
    assert st == 413
    for brut in (b"[" * 5000 + b"]" * 5000, b"{pas du json", json.dumps({"action": "moderer", "x": "a" * 5000}).encode()):
        st, rep, _e = _requete(local, "POST", "/tableau/espace/action", tete, data=brut,
                               entetes=dict(ORIGINE, **{"Content-Type": "application/json"}))
        assert st == 400 and json.loads(rep)["ok"] is False, (brut[:12], st)
    assert _empreinte(local) == avant, "un corps refusé a laissé une trace en base"


# ═══════════════════════════════════════════════════════════════════════════════
#  A8 — les chemins de fichiers normalisés
# ═══════════════════════════════════════════════════════════════════════════════

DETOURS = ("../tableau.py", "%2e%2e/tableau.py", "..%2Ftableau.py", "%2e%2e%2ftableau.py", "....//tableau.py",
           "icones/../../tableau.py", "icones/%2e%2e/%2e%2e/tableau.py", "..\\tableau.py", "..%5Ctableau.py",
           "%2Fetc%2Fpasswd", "C:/Windows/win.ini", "C:%5CWindows%5Cwin.ini", ".env", "LICENCES.md", "app.js%00.png",
           "app.js::$DATA", "./app.js", "app.js/", "icones//ui.svg",
           #  Un fichier de la tête par un détour PUBLIC :
           "icones/../app.js", "polices/..%2Fapp.js", "polices%2F..%2Fsecurite.js", "textures/./../discord.js",
           "logos/%2e%2e/clan.js", "icones/%252e%252e/app.js")


def test_A8_aucun_pas_hors_du_dossier_ni_detour_vers_le_code(local, portees):
    """Rien hors de `site/`, pour personne ; et jamais un fichier de la tête à une autre portée par un détour (un
    préfixe public, un encodage). Pour la tête, un détour qui retombe sur un fichier de `site/` (le client réduit
    parfois « a/../b ») n'est pas une fuite : seul compte que rien d'AUTRE ne sorte."""
    dehors = [(RACINE / "tableau.py").read_text(encoding="utf-8")[:300],
              (RACINE / "health_server.py").read_text(encoding="utf-8")[:300]]
    app_js = (RACINE / "site" / "app.js").read_text(encoding="utf-8")[:300]
    for chemin in DETOURS:
        for qui, h in portees.items():
            st, rep, _e = _requete(local, "GET", "/tableau/espace/s/" + chemin, h)
            texte = rep.decode("utf-8", "replace")
            assert not any(x[:120] in texte for x in dehors) and "[fonts]" not in texte, f"{qui} {chemin} : hors de site/"
            if qui != "tout":
                assert st in (400, 404) and app_js[:120] not in texte, f"{qui} {chemin} → {st} : le code de la tête"
            else:
                assert st in (200, 400, 404), f"{chemin} → {st}"
    import tableau
    for brut in ("..", "a/../b.js", "./a.js", "a//b.js", "/a.js", ".a.js", "a.py", "a.js:$DATA", "a\\b.js", "a\x00.js",
                 "icones/../app.js", "%2e%2e/app.js"):
        assert tableau._chemin_statique(brut) is None, brut


# ═══════════════════════════════════════════════════════════════════════════════
#  A9 — les images au-delà des limites
# ═══════════════════════════════════════════════════════════════════════════════

def test_A9_les_images_au_dela_des_limites_sont_refusees(local):
    from PIL import Image
    import tableau
    tete, _a = local.entrer("/tableau/demo")

    def envoyer(octets, typ="image/png"):
        corps = {"nom": "essai.png", "type": typ, "base64": base64.b64encode(octets).decode()}
        st, rep, _e = _requete(local, "POST", "/tableau/espace/api/media", tete, entetes=ORIGINE, json_=corps)
        return st, json.loads(rep)

    def png(taille, mode="RGB"):
        b = io.BytesIO()
        Image.new(mode, taille).save(b, "PNG", optimize=True)
        return b.getvalue()
    avant = local.sql("SELECT COUNT(*) FROM tableau_medias")[0][0]
    bombe = png((7000, 7000), "1")   # 49 millions de pixels, quelques Ko : une bombe de décompression
    assert len(bombe) < 200_000 and 7000 * 7000 > tableau.MEDIA_PIXELS
    refus = {
        "bombe de décompression": envoyer(bombe),
        "texte déguisé en PNG": envoyer(b"<?php echo 'x'; ?>" * 10),
        "SVG": envoyer(b"<svg xmlns='http://www.w3.org/2000/svg' onload='alert(1)'/>", "image/svg+xml"),
        "PNG tronqué": envoyer(png((64, 64))[:40]),
        "trop lourde": envoyer(b"\x89PNG\r\n\x1a\n" + b"\x00" * (tableau.MEDIA_MAX + 1)),
    }
    for nom, (st, rep) in refus.items():
        assert st in (400, 413, 415) and not rep.get("ok"), f"{nom} → {st} {rep}"
    assert refus["trop lourde"][0] == 413 and refus["bombe de décompression"][0] == 415
    assert local.sql("SELECT COUNT(*) FROM tableau_medias")[0][0] == avant, "une image refusée a été gardée"
    #  Une vraie image passe, refaite (jamais le fichier reçu tel quel).
    st, rep = envoyer(png((300, 200)))
    assert st == 200 and rep["largeur"] == 300 and rep["type"] in ("image/webp", "image/png")


# ═══════════════════════════════════════════════════════════════════════════════
#  A10 + A11 — les en-têtes partout ; /stats sans donnée personnelle ; les médias
# ═══════════════════════════════════════════════════════════════════════════════

def test_A10_les_medias_et_les_entetes_partout(local, portees):
    """Une image envoyée par la tête et qu'aucune lecture de l'équipage ne cite : la tête seule ; une image citée par
    l'équipage : l'équipage aussi. Les en-têtes de base sur chaque réponse (même un 404 d'une adresse inconnue)."""
    import site_equipage
    local.tete = portees["tout"]   # une session de la tête vivante (« Fermer les autres sessions » a pu passer avant)
    privee = local.png("privee.png")
    citees = sorted(x for x in local.faire(site_equipage.medias_permis(local.g)) if re.fullmatch(r"[A-Za-z0-9_-]{16}", x))
    assert privee not in citees and citees, "la démonstration cite au moins une image (le bandeau de l'accueil)"
    vus = []
    for ident, lecteurs in ((privee, {"tout"}), (citees[0], {"equipage", "tout"}), ("A" * 16, set())):
        for qui, h in portees.items():
            st, _r, e = _requete(local, "GET", f"/tableau/espace/media/{ident}", h)
            _verifier_entetes(ident, st, e, vus)
            if qui in lecteurs:
                assert st == 200 and e["Cache-Control"] == "no-store", (ident, qui, st)
            else:
                assert st in (403, 404), (ident, qui, st)
    for chemin in ("/rien/du/tout", "/tableau/espace/rien", "/equipage/rien", "/tableau/espace/s/rien.js"):
        st, _r, e = _requete(local, "GET", chemin)
        _verifier_entetes(chemin, st, e, vus)
        assert st in (403, 404) and e.get("Cache-Control") == "no-store", (chemin, st)


def test_A11_stats_sans_donnee_personnelle(local):
    st, corps, e = _requete(local, "GET", "/stats")
    assert st == 200 and "Set-Cookie" not in e
    texte = corps.decode("utf-8")
    assert not re.search(r"\d{15,}", texte), "un identifiant Discord dans /stats"
    for m in local.g.members:
        if len(m.display_name) >= 4:
            assert m.display_name not in texte, f"le nom « {m.display_name} » dans /stats"
    st, corps, _e = _requete(local, "GET", "/health")
    assert st == 200 and not re.search(r"\d{15,}", corps.decode("utf-8"))
