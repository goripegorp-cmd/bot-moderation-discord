"""La présence en direct et les verrous d'édition (26/10/2026) — le serveur, de bout en bout.

D1 la porte de la WebSocket : session, origine, personne retirée, une vraie WebSocket. D2 la présence : l'état à
l'arrivée, puis seulement des deltas (present, page, absent). D3 les verrous : accordé, refusé, réentrant (deux onglets),
lâché. D4 le bail : échu sans battement, renouvelé par le battement, long quand l'onglet est caché. D5 la fermeture : la
grâce garde la présence et les verrous (un rechargement), puis tout tombe ; D5b une socket fantôme ne fait pas de bruit
(au repos : zéro message). D6 « Demander la main ». D7 le serveur fait
respecter les verrous : 423 du registre (`_executer`), de la file hors ligne (`sync` : jamais gardé comme refus, rejoué
après la libération) et des actions ; « ecrit » diffusé. D8 une session finie ou fermée ailleurs coupe la socket (4401),
revérifiée aussi à chaque prise de verrou. D9 des messages bornés (clé, titre, taille, cadence, onglets). D10 le repli
sans WebSocket (interrogation) et le passage de ses verrous à la socket. D11 « a changé pendant ta pause » (compteur
d'écritures). D12 la table des clés colle aux routes réelles ; une route ne déclare un verrou que pour une écriture."""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

import aiohttp
import aiosqlite
import pytest

import health_server
import registre
import tableau
from conftest_discord import Obj

FONDATEUR, DIRECTION, INTRUS = 781205382923288593, 827633340797681714, 9
TETE = frozenset({FONDATEUR, DIRECTION})
BASE = "https://bot.exemple"
RACINE = Path(__file__).resolve().parent.parent


class Membre:
    def __init__(self, uid, nom):
        self.id, self.display_name, self.name, self.bot = uid, nom, nom.lower(), False
        url = f"https://cdn.discordapp.com/avatars/{uid}.png"
        self.display_avatar = Obj(url=url, with_size=lambda _n: Obj(url=url))


class Serveur:
    def __init__(self):
        self.id, self.name, self.owner_id, self.icon = 1, "GoRP SEA", FONDATEUR, None
        self.membres = {uid: Membre(uid, nom) for uid, nom in ((FONDATEUR, "GoRipe"), (DIRECTION, "Mira"), (INTRUS, "Intrus"))}

    def get_member(self, uid):
        return self.membres.get(int(uid or 0))


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


class Monde:
    """Le site comme dans bot.py (la tête seule entre et agit), des délais du direct raccourcis pour les tests."""

    def __init__(self, tmp_path, monkeypatch):
        self.journal = []
        self.get_db = _base(tmp_path / "direct.db")
        self.g = Serveur()
        self.tete = set(TETE)
        self.actions_faites = []
        for nom, valeur in (("DIRECT_RONDE", 0.05), ("DIRECT_GRACE", 0.4), ("DIRECT_BAIL", 60), ("DIRECT_BAIL_CACHE", 330),
                            ("DIRECT_VERIFIER", 60)):
            monkeypatch.setattr(tableau, nom, valeur)
        monkeypatch.setattr(tableau, "ROUTES", {})

        async def cfg(_g):
            return {}

        def tete(g, m, c=None):
            return m is not None and m.id in self.tete

        async def ticket_fermer(g, auteur, corps):
            self.actions_faites.append(corps)
            return True, "Ticket fermé."
        registre.setup(get_db=self.get_db, log=lambda *a: None)
        registre._derniers.clear()
        tableau.setup(bot=Obj(get_guild=lambda gid: self.g if gid == 1 else None, user=Obj(id=999)), cle="k",
                      base_url=BASE, cfg=cfg, get_db=self.get_db, mesurer_groupe=None, autorise_membre=tete,
                      direction=tete, tete=TETE, actions={"ticket_fermer": ticket_fermer}, log=self.journal.append)

        async def preparer():
            await registre.init_db()
            await tableau.init_db()
        asyncio.run(preparer())

    def biscuit(self, uid=FONDATEUR) -> dict:
        sid = asyncio.run(tableau._ouvrir_session(1, uid, int(time.time()) + 3600))
        return {"Cookie": f"{tableau.COOKIE}={sid}"}

    def http(self, scenario):
        from aiohttp.test_utils import TestClient, TestServer

        async def lancer():
            async with TestClient(TestServer(health_server.construire_app())) as client:
                return await scenario(client)
        return asyncio.run(lancer())


@pytest.fixture
def monde(tmp_path, monkeypatch):
    return Monde(tmp_path, monkeypatch)


async def _socket(c, biscuit, page="port/apercu", origine=BASE, bonjour=True, onglet=None):
    ws = await c.ws_connect("/tableau/espace/direct", headers=dict(biscuit, Origin=origine))
    if bonjour:
        m = {"t": "bonjour", "page": page}
        if onglet:
            m["onglet"] = onglet
        await ws.send_json(m)
        etat = await _attendre(ws, "etat")
        ws.etat = etat
    return ws


async def _attendre(ws, genre, delai=3.0, objet=None):
    """Le prochain message de ce genre (les autres sont gardés dans `ws.vus`)."""
    fin = time.monotonic() + delai
    while True:
        reste = fin - time.monotonic()
        if reste <= 0:
            raise AssertionError(f"pas de message « {genre} » (vus : {[m.get('t') for m in getattr(ws, 'vus', [])]})")
        msg = await ws.receive(timeout=reste)
        if msg.type != aiohttp.WSMsgType.TEXT:
            raise AssertionError(f"socket fermée ({msg.type}, {ws.close_code}) en attendant « {genre} »")
        m = json.loads(msg.data)
        ws.vus = getattr(ws, "vus", []) + [m]
        if m.get("t") == genre and (objet is None or m.get("o") == objet or (m.get("v") or {}).get("o") == objet):
            return m


async def _rien(ws, delai=0.25):
    """Aucun message pendant `delai` (la page au repos ne reçoit rien)."""
    try:
        msg = await ws.receive(timeout=delai)
    except asyncio.TimeoutError:
        return True
    raise AssertionError(f"message inattendu : {msg.data if msg.type == aiohttp.WSMsgType.TEXT else msg.type}")


async def _fermeture(ws, delai=3.0):
    msg = await ws.receive(timeout=delai)
    while msg.type == aiohttp.WSMsgType.TEXT:
        msg = await ws.receive(timeout=delai)
    return ws.close_code


# ═══════════════════════════════════════════════════════════════════════════════
#  D1 — la porte
# ═══════════════════════════════════════════════════════════════════════════════

def test_D1_la_porte_de_la_websocket(monde):
    tete, intrus, direction = monde.biscuit(FONDATEUR), monde.biscuit(INTRUS), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        for nom, entetes in (("sans_session", {"Origin": BASE}), ("mauvaise_origine", dict(tete, Origin="https://autre.site")),
                             ("sans_origine", tete), ("autre_site", dict(tete, Origin=BASE, **{"Sec-Fetch-Site": "cross-site"})),
                             ("intrus", dict(intrus, Origin=BASE))):
            try:
                ws = await c.ws_connect("/tableau/espace/direct", headers=entetes)
                out[nom] = "ouverte"
                await ws.close()
            except aiohttp.WSServerHandshakeError as ex:
                out[nom] = ex.status
        r = await c.get("/tableau/espace/direct", headers=dict(tete, Origin=BASE))
        out["pas_websocket"] = r.status
        ws = await _socket(c, tete, page="capitainerie/affiches")
        out["etat"] = ws.etat
        #  Une personne retirée de la tête entre-temps : plus de nouvelle socket.
        monde.tete.discard(DIRECTION)
        try:
            await c.ws_connect("/tableau/espace/direct", headers=dict(direction, Origin=BASE))
            out["retiree"] = "ouverte"
        except aiohttp.WSServerHandshakeError as ex:
            out["retiree"] = ex.status
        await ws.close()
        return out
    out = monde.http(scenario)
    assert out["sans_session"] == 403 and out["intrus"] == 403 and out["retiree"] == 403
    assert out["mauvaise_origine"] == 400 and out["sans_origine"] == 400 and out["autre_site"] == 400
    assert out["pas_websocket"] == 400, "une simple requête n'ouvre rien"
    e = out["etat"]
    assert e["t"] == "etat" and e["moi"] == str(FONDATEUR) and e["v"] == []
    assert [p["id"] for p in e["p"]] == [str(FONDATEUR)] and e["p"][0]["nom"] == "GoRipe"
    assert e["p"][0]["pages"][0][0] == "capitainerie/affiches" and e["p"][0]["av"].startswith("https://cdn.discordapp.com/")
    assert e["cfg"] == {"bat": 20, "bail": 60, "inactif": 300, "tour": 10}


# ═══════════════════════════════════════════════════════════════════════════════
#  D2 — la présence : l'état, puis des deltas
# ═══════════════════════════════════════════════════════════════════════════════

def test_D2_presence_et_deltas(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wa = await _socket(c, a, page="port/apercu")
        wb = await _socket(c, b, page="equipage/annonces")
        out["present"] = await _attendre(wa, "present")
        out["etat_b"] = wb.etat
        await wb.send_json({"t": "page", "page": "capitainerie/affiches"})
        out["page_a"] = await _attendre(wa, "page")
        out["page_b"] = await _attendre(wb, "page")   # chacun reçoit la page (ses onglets disent tous la vérité)
        await wb.send_json({"t": "page", "page": "Pas Une Page !"})   # refusée : rien ne part
        out["repos"] = await _rien(wa, 0.3)
        await wb.close()
        out["pendant_grace"] = await _rien(wa, 0.2)
        out["absent"] = await _attendre(wa, "absent", 2)
        await wa.close()
        return out
    out = monde.http(scenario)
    assert out["present"]["p"]["id"] == str(DIRECTION) and out["present"]["p"]["nom"] == "Mira"
    assert out["present"]["p"]["pages"][0][0] == "equipage/annonces"
    assert {p["id"] for p in out["etat_b"]["p"]} == {str(FONDATEUR), str(DIRECTION)}
    assert out["page_a"]["id"] == str(DIRECTION) and out["page_a"]["pages"][0][0] == "capitainerie/affiches"
    assert out["page_b"] == out["page_a"]
    assert out["repos"] and out["pendant_grace"], "rien pendant la grâce : un rechargement ne fait pas clignoter"
    assert out["absent"] == {"t": "absent", "id": str(DIRECTION)}


# ═══════════════════════════════════════════════════════════════════════════════
#  D3 — les verrous
# ═══════════════════════════════════════════════════════════════════════════════

def test_D3_verrous_accorde_refuse_reentrant_lache(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wa = await _socket(c, a)
        wb = await _socket(c, b)
        await wa.send_json({"t": "prendre", "o": "affiche:demo-1", "ti": "l'affiche de Kolax"})
        out["pris"] = await _attendre(wa, "pris")
        out["vu_par_b"] = await _attendre(wb, "verrou")
        await wb.send_json({"t": "prendre", "o": "affiche:demo-1", "ti": "l'affiche de Kolax"})
        out["refuse"] = await _attendre(wb, "refuse")
        #  Le même fondateur, un second onglet : le verrou est à lui (réentrant).
        wa2 = await _socket(c, a)
        out["etat_a2"] = wa2.etat
        await wa2.send_json({"t": "prendre", "o": "affiche:demo-1", "ti": "l'affiche de Kolax"})
        out["pris2"] = await _attendre(wa2, "pris")
        out["nb2"] = (await _attendre(wb, "verrou"))["v"]["nb"]
        await wa.send_json({"t": "lacher", "o": "affiche:demo-1"})
        out["nb1"] = (await _attendre(wb, "verrou"))["v"]["nb"]
        await wa2.send_json({"t": "lacher", "o": "affiche:demo-1"})
        out["libre"] = await _attendre(wb, "libre")
        await wb.send_json({"t": "prendre", "o": "affiche:demo-1", "ti": "l'affiche de Kolax"})
        out["pris_b"] = await _attendre(wb, "pris")
        for w in (wa, wa2, wb):
            await w.close()
        return out
    out = monde.http(scenario)
    assert out["pris"]["o"] == "affiche:demo-1" and out["pris"]["n"] == 0 and out["pris"]["ch"] is False
    assert out["pris"]["v"] == {"o": "affiche:demo-1", "ti": "l'affiche de Kolax", "id": str(FONDATEUR),
                                "d": out["pris"]["v"]["d"], "nb": 1}
    assert out["vu_par_b"]["v"]["id"] == str(FONDATEUR) and out["vu_par_b"]["v"]["ti"] == "l'affiche de Kolax"
    assert out["refuse"] == {"t": "refuse", "o": "affiche:demo-1", "par": str(FONDATEUR), "nom": "GoRipe"}
    assert out["etat_a2"]["v"][0]["o"] == "affiche:demo-1", "un nouvel onglet voit les verrous dès son arrivée"
    assert out["pris2"]["v"]["nb"] == 2 and out["nb2"] == 2 and out["nb1"] == 1
    assert out["libre"]["o"] == "affiche:demo-1" and out["pris_b"]["v"]["id"] == str(DIRECTION)


# ═══════════════════════════════════════════════════════════════════════════════
#  D4 — le bail
# ═══════════════════════════════════════════════════════════════════════════════

def test_D4_bail_echu_renouvele_et_onglet_cache(monde, monkeypatch):
    monkeypatch.setattr(tableau, "DIRECT_BAIL", 0.35)
    monkeypatch.setattr(tableau, "DIRECT_BAIL_CACHE", 1.2)
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wa = await _socket(c, a)
        wb = await _socket(c, b)
        #  Sans battement : le bail tombe.
        await wa.send_json({"t": "prendre", "o": "question:q-1", "ti": "la question 1"})
        await _attendre(wa, "pris")
        t0 = time.monotonic()
        out["libre_sans_battement"] = await _attendre(wb, "libre", 2, objet="question:q-1")
        out["delai"] = time.monotonic() - t0
        #  Avec battement : il tient.
        await wa.send_json({"t": "prendre", "o": "question:q-2", "ti": "la question 2"})
        await _attendre(wa, "pris")
        for _ in range(8):
            await asyncio.sleep(0.12)
            await wa.send_json({"t": "vivant"})
        out["tenu"] = "question:q-2" in tableau._direct_salles[1].verrous
        #  Onglet caché (aucun battement) : un bail long.
        await wa.send_json({"t": "vivant", "cache": True})
        await asyncio.sleep(0.7)
        out["tenu_cache"] = "question:q-2" in tableau._direct_salles[1].verrous
        out["libre_cache"] = await _attendre(wb, "libre", 2, objet="question:q-2")
        await wa.close()
        await wb.close()
        return out
    out = monde.http(scenario)
    assert out["libre_sans_battement"]["o"] == "question:q-1" and out["delai"] < 1.5
    assert out["tenu"], "le battement renouvelle le bail"
    assert out["tenu_cache"], "caché : le bail est long (pas de battement)"
    assert out["libre_cache"]["o"] == "question:q-2"


# ═══════════════════════════════════════════════════════════════════════════════
#  D5 — la fermeture et sa grâce
# ═══════════════════════════════════════════════════════════════════════════════

def test_D5_grace_a_la_fermeture_puis_liberation(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wb = await _socket(c, b)
        #  Un rechargement : la socket se ferme, une autre revient dans la grâce et reprend la main.
        wa = await _socket(c, a)
        await wa.send_json({"t": "prendre", "o": "affiche:demo-2", "ti": "l'affiche de Mira"})
        await _attendre(wa, "pris")
        await _attendre(wb, "verrou")
        debut = len(wb.vus)   # (l'arrivée du fondateur et son verrou sont déjà lus)
        await wa.close()
        await wb.send_json({"t": "prendre", "o": "affiche:demo-2"})
        out["refuse_pendant_grace"] = (await _attendre(wb, "refuse"))["par"]
        wa2 = await _socket(c, a)
        await wa2.send_json({"t": "prendre", "o": "affiche:demo-2", "ti": "l'affiche de Mira"})
        out["repris"] = (await _attendre(wa2, "pris"))["o"]
        await asyncio.sleep(0.8)   # la grâce de l'ancienne socket est finie
        out["toujours_tenu"] = tableau._direct_salles[1].verrous["affiche:demo-2"].uid == FONDATEUR
        out["pas_absent"] = all(m.get("t") != "absent" for m in getattr(wb, "vus", []))
        out["rien_de_neuf"] = [m.get("t") for m in wb.vus[debut:] if m.get("t") in ("page", "present", "absent")]
        #  Une vraie fermeture : après la grâce, le verrou tombe et la personne part.
        await wa2.close()
        out["libre"] = (await _attendre(wb, "libre", 2))["o"]
        out["absent"] = (await _attendre(wb, "absent", 2))["id"]
        await wb.close()
        return out
    out = monde.http(scenario)
    assert out["refuse_pendant_grace"] == str(FONDATEUR), "la grâce garde le verrou (un rechargement)"
    assert out["repris"] == "affiche:demo-2" and out["toujours_tenu"] and out["pas_absent"]
    assert out["rien_de_neuf"] == [], "un rechargement sur la même page ne dit rien aux autres (ni present, ni page)"
    assert out["libre"] == "affiche:demo-2" and out["absent"] == str(FONDATEUR)


def test_D5b_une_socket_fantome_ne_fait_pas_de_bruit(monde):
    """Le rechargement qui arrive sur une autre page (l'ancienne n'avait pas encore dit la sienne) : UN delta « page »,
    la vraie nouvelle ; la socket fantôme qui s'en va après sa grâce ne dit plus rien (au repos : zéro message). Un
    onglet fermé pour de bon, la personne en gardant un autre : un delta après la grâce, n = 1, la page restante."""
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wb = await _socket(c, b)
        wa = await _socket(c, a, page="port/apercu")
        await _attendre(wb, "present")
        await wa.close()                                            # un rechargement…
        await asyncio.sleep(0.05)
        wa2 = await _socket(c, a, page="capitainerie/affiches")     # … qui arrive sur une autre page
        out["page"] = await _attendre(wb, "page")
        await asyncio.sleep(0.8)                                    # la grâce de la socket fantôme est finie
        out["fantome_parti"] = await _rien(wb, 0.2)
        wa3 = await _socket(c, a, page="equipage/annonces")         # un second onglet…
        out["deux"] = await _attendre(wb, "page")
        await wa2.close()                                           # … et le premier fermé pour de bon
        await asyncio.sleep(0.05)
        out["pendant_grace"] = await _rien(wb, 0.2)
        out["un"] = await _attendre(wb, "page", 2)
        out["apres"] = await _rien(wb, 0.6)
        await wa3.close()
        await wb.close()
        return out
    out = monde.http(scenario)
    pages = lambda m: [p for p, _t in m["pages"]]  # noqa: E731
    assert pages(out["page"]) == ["capitainerie/affiches"] and out["page"]["n"] == 1, "la page d'un onglet fermé n'est plus dite"
    assert out["fantome_parti"], "la socket fantôme qui s'en va après sa grâce ne dit rien"
    assert pages(out["deux"]) == ["equipage/annonces", "capitainerie/affiches"] and out["deux"]["n"] == 2
    assert out["pendant_grace"], "pendant la grâce, rien (un rechargement ne fait pas clignoter)"
    assert pages(out["un"]) == ["equipage/annonces"] and out["un"]["n"] == 1
    assert out["apres"]


# ═══════════════════════════════════════════════════════════════════════════════
#  D6 — Demander la main
# ═══════════════════════════════════════════════════════════════════════════════

def test_D6_demander_la_main(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wa = await _socket(c, a)
        wb = await _socket(c, b)
        await wa.send_json({"t": "prendre", "o": "dossier:42", "ti": "le dossier de Kolax"})
        await _attendre(wa, "pris")
        await wb.send_json({"t": "demande", "o": "dossier:42"})
        out["demandee"] = await _attendre(wb, "demandee")
        out["demande"] = await _attendre(wa, "demande")
        await wb.send_json({"t": "demande", "o": "dossier:42"})
        out["deja"] = await _attendre(wb, "demandee")
        out["une_seule"] = await _rien(wa, 0.3)
        await wb.send_json({"t": "demande", "o": "dossier:99"})
        out["rien_a_demander"] = await _attendre(wb, "libre")
        await wa.close()
        await wb.close()
        return out
    out = monde.http(scenario)
    assert out["demandee"] == {"t": "demandee", "o": "dossier:42"}
    assert out["demande"] == {"t": "demande", "o": "dossier:42", "par": str(DIRECTION), "nom": "Mira"}
    assert out["deja"] == {"t": "demandee", "o": "dossier:42", "deja": 1} and out["une_seule"]
    assert out["rien_a_demander"]["o"] == "dossier:99"


# ═══════════════════════════════════════════════════════════════════════════════
#  D7 — le serveur fait respecter les verrous (423)
# ═══════════════════════════════════════════════════════════════════════════════

def test_D7_le_serveur_refuse_d_ecrire_un_objet_pris_ailleurs(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)
    ecrits = []

    async def ecrire(g, auteur, requete, corps):
        ecrits.append((auteur.id, corps.get("id"), corps.get("v")))
        return 200, {"ok": True}
    tableau.monter({"t/affiche": {"methode": "POST", "fn": ecrire, "hors_ligne": True,
                                  "verrou": lambda c: f"affiche:{c.get('id')}"}})
    ecrire_a = dict(a, **{"X-Tableau": "1", "Origin": BASE})
    ecrire_b = dict(b, **{"X-Tableau": "1", "Origin": BASE})

    async def scenario(c):
        out = {}
        wa = await _socket(c, a)
        wb = await _socket(c, b)
        await wa.send_json({"t": "prendre", "o": "affiche:7", "ti": "l'affiche de Kolax"})
        await _attendre(wa, "pris")
        r = await c.post("/tableau/espace/api/t/affiche", json={"id": 7, "v": "b"}, headers=ecrire_b)
        out["b"] = (r.status, await r.json())
        r = await c.post("/tableau/espace/api/t/affiche", json={"id": 8, "v": "b"}, headers=ecrire_b)
        out["b_autre"] = r.status
        r = await c.post("/tableau/espace/api/t/affiche", json={"id": 7, "v": "a"}, headers=ecrire_a)
        out["a"] = r.status
        out["ecrit"] = [await _attendre(wb, "ecrit"), await _attendre(wb, "ecrit")]   # la sienne (8), celle du fondateur (7)
        #  La file hors ligne : le refus n'est jamais gardé — la même opération repart après la libération.
        op = {"op_id": "op-direct-0001", "api": "t/affiche", "corps": {"id": 7, "v": "hors ligne"}}
        r = await c.post("/tableau/espace/sync", json={"ops": [op]}, headers=ecrire_b)
        out["sync_423"] = (await r.json())["resultats"][0]
        async with monde.get_db() as db:
            async with db.execute("SELECT COUNT(*) FROM tableau_ops WHERE op_id=?", (op["op_id"],)) as cur:
                out["garde"] = (await cur.fetchone())[0]
        await wa.send_json({"t": "lacher", "o": "affiche:7"})
        await _attendre(wb, "libre")
        r = await c.post("/tableau/espace/sync", json={"ops": [op]}, headers=ecrire_b)
        out["sync_ok"] = (await r.json())["resultats"][0]["status"]
        await wa.close()
        await wb.close()
        return out
    out = monde.http(scenario)
    assert out["b"] == (423, {"erreur": "En cours de modification par GoRipe.",
                              "verrou": {"objet": "affiche:7", "par": str(FONDATEUR), "nom": "GoRipe"}})
    assert out["b_autre"] == 200 and out["a"] == 200, "un autre objet, ou le détenteur lui-même : l'écriture passe"
    assert [(e["o"], e["id"]) for e in out["ecrit"]] == [(["affiche:8"], str(DIRECTION)), (["affiche:7"], str(FONDATEUR))],         "chaque écriture faite est dite à la salle : les autres pages relisent"
    assert out["sync_423"]["status"] == 423 and out["sync_423"]["corps"]["verrou"]["nom"] == "GoRipe"
    assert out["garde"] == 0, "un 423 n'est jamais gardé : l'opération reste dans la file de la page"
    assert out["sync_ok"] == 200
    assert ecrits == [(DIRECTION, 8, "b"), (FONDATEUR, 7, "a"), (DIRECTION, 7, "hors ligne")]
    assert tableau._resultat_garde(423) is False and tableau._resultat_garde(409) is True


def test_D7b_les_actions_historiques_et_les_cles_des_vraies_routes(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wa = await _socket(c, a)
        await wa.send_json({"t": "prendre", "o": "dossier:5", "ti": "le dossier de Kolax"})
        await _attendre(wa, "pris")
        r = await c.post("/tableau/espace/action", json={"action": "ticket_fermer", "ticket": 5},
                         headers=dict(b, **{"X-Tableau": "1", "Origin": BASE}))
        out["b"] = (r.status, await r.json())
        r = await c.post("/tableau/espace/action", json={"action": "ticket_fermer", "ticket": 6},
                         headers=dict(b, **{"X-Tableau": "1", "Origin": BASE}))
        out["autre"] = r.status
        await wa.close()
        return out
    out = monde.http(scenario)
    assert out["b"] == (423, {"ok": False, "message": "En cours de modification par GoRipe."})
    assert out["autre"] == 200 and monde.actions_faites == [{"action": "ticket_fermer", "ticket": 6}]
    #  Les clés que la page prend : les mêmes que celles du serveur (site/direct.js, capitainerie.js, recrutement.js…).
    v = tableau.VERROUS_ROUTES
    assert v["rell/affiche"]({"id": "abc", "version": 3, "membre_id": "1000"}) == ["affiche:abc"]
    assert v["rell/affiche"]({"id": "neuve-01", "membre_id": "1000"}) == ["affiche:neuve-01", "affiche-membre:1000"]
    assert v["rell/catalogue/element"]({"type": "metier", "cle": "navigation"}) == "element:metier:navigation"
    assert v["rell/catalogue/element"]({"type": "metier", "nom": "Nouveau"}) is None, "une création n'a rien à verrouiller"
    assert v["clan/brouillon"]({"id": 12}) == "brouillon:12" and v["clan/brouillon"]({"cle_client": "x" * 12}) is None
    assert v["clan/publier"]({"id": 12}) == ["brouillon:12", "evenement:12"] and v["clan/modifier"]({"id": 12}) == "evenement:12"
    assert v["recrutement/decision"]({"ticket": 44}) == "dossier:44" and v["recrutement/liens"]({}) == "questionnaire:liens"
    assert v["nettoyage/regle"]({"cle": "medias"}) == "nettoyage:medias" and v["rell/role"]({"type": "metier", "cle": "x"}) == "role:metier:x"


# ═══════════════════════════════════════════════════════════════════════════════
#  D8 — une session finie coupe la socket
# ═══════════════════════════════════════════════════════════════════════════════

def test_D8_session_finie_ou_fermee_ailleurs_coupe_la_socket(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def scenario(c):
        out = {}
        wb = await _socket(c, b)
        wa = await _socket(c, a)
        await wa.send_json({"t": "prendre", "o": "affiche:9", "ti": "l'affiche 9"})
        await _attendre(wa, "pris")
        await tableau.fermer_sessions(None, FONDATEUR)   # « Fermer toutes mes sessions », ailleurs
        out["code"] = await _fermeture(wa)
        out["libre"] = (await _attendre(wb, "libre", 2))["o"]   # sans grâce : la session est finie
        #  À la prise d'un verrou, la session est relue en base (même entre deux rondes).
        async with monde.get_db() as db:
            await db.execute("DELETE FROM tableau_sessions WHERE user_id=?", (DIRECTION,))
            await db.commit()
        await wb.send_json({"t": "prendre", "o": "affiche:10"})
        out["code_prise"] = await _fermeture(wb)
        out["salle"] = (len(tableau._direct_salles[1].prises), len(tableau._direct_salles[1].verrous))
        return out
    out = monde.http(scenario)
    assert out["code"] == tableau.CODE_SESSION and out["libre"] == "affiche:9"
    assert out["code_prise"] == tableau.CODE_SESSION
    assert out["salle"] == (0, 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  D9 — des messages bornés
# ═══════════════════════════════════════════════════════════════════════════════

def test_D9_messages_bornes(monde, monkeypatch):
    a = monde.biscuit(FONDATEUR)

    async def scenario(c):
        out = {}
        ws = await _socket(c, a)
        await ws.send_json({"t": "prendre", "o": "Pas Une Clé", "ti": "x"})
        out["cle"] = await _attendre(ws, "refuse")
        await ws.send_json({"t": "prendre", "o": "affiche:t", "ti": "l'affiche‮\x07 de\n\n  Kolax" + "x" * 300})
        out["titre"] = (await _attendre(ws, "pris"))["v"]["ti"]
        await ws.send_json({"t": "prendre", "o": "element:" + "a" * 60 + ":" + "b" * 60})
        out["longue"] = (await _attendre(ws, "pris"))["o"]
        await ws.send_str("x" * 2000)
        out["trop_gros"] = await _fermeture(ws)
        ws = await _socket(c, a)
        await ws.send_str("{pas du json")
        out["illisible"] = await _fermeture(ws)
        ws = await c.ws_connect("/tableau/espace/direct", headers=dict(a, Origin=BASE))
        await ws.send_json({"t": "page", "page": "port/apercu"})   # rien avant « bonjour »
        out["avant_bonjour"] = await _rien(ws, 0.2)
        for _ in range(130):
            await ws.send_json({"t": "vivant"})
        out["cadence"] = await _fermeture(ws)
        #  Huit onglets au plus par personne : le neuvième est refusé (4429), les autres restent.
        socks = [await _socket(c, a) for _ in range(tableau.DIRECT_ONGLETS)]
        de_trop = await c.ws_connect("/tableau/espace/direct", headers=dict(a, Origin=BASE))
        out["onglets"] = await _fermeture(de_trop)
        for s in socks:
            await s.close()
        return out
    out = monde.http(scenario)
    assert out["cle"] == {"t": "refuse", "o": "Pas Une Clé", "err": "objet"}
    assert out["titre"].startswith("l'affiche de Kolax") and len(out["titre"]) == tableau.DIRECT_TITRE
    assert len(out["longue"]) == 100 and out["longue"] == tableau.objet_direct("element:" + "a" * 60 + ":" + "b" * 60)
    assert out["trop_gros"] == aiohttp.WSCloseCode.MESSAGE_TOO_BIG and out["illisible"] == tableau.CODE_MESSAGE
    assert out["avant_bonjour"] and out["cadence"] == tableau.CODE_TROP and out["onglets"] == tableau.CODE_TROP


def test_D9b_la_cle_raccourcie_est_la_meme_que_celle_de_la_page():
    """`objet_direct` (serveur) et `cleObjet` (site/direct.js) : le même FNV-1a, le même découpage."""
    longue = "element:" + "a" * 60 + ":" + "b" * 60
    assert tableau.objet_direct(longue) == "element:" + "a" * 60 + ":" + "b" * 22 + "~6c6b3a5b"
    js = (RACINE / "site" / "direct.js").read_text(encoding="utf-8")
    assert 'o.slice(0, 91) + "~" + fnv(o).toString(16).padStart(8, "0")' in js and "0x811c9dc5" in js and "0x01000193" in js
    assert tableau.FORMAT_OBJET.pattern.replace("{0,29}", "") in js.replace("\\", "").replace("{0,29}", "") or \
        "[a-z][a-z0-9_-]{0,29}:[A-Za-z0-9_.:@~-]{1,270}" in js


# ═══════════════════════════════════════════════════════════════════════════════
#  D10 — sans WebSocket : l'interrogation
# ═══════════════════════════════════════════════════════════════════════════════

def test_D10_repli_par_interrogation_puis_retour_de_la_socket(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)
    lire_a = dict(a, **{"X-Tableau": "1"})
    ecrire_a = dict(a, **{"X-Tableau": "1", "Origin": BASE})
    envoi = "/tableau/espace/api/direct/envoi"

    async def scenario(c):
        out = {}
        wb = await _socket(c, b)
        r = await c.get("/tableau/espace/api/direct/etat?onglet=onglet-http-01&page=capitainerie/affiches", headers=lire_a)
        out["etat"] = (r.status, await r.json())
        out["present"] = await _attendre(wb, "present")
        out["inconnu"] = (await c.post(envoi, headers=ecrire_a, json={"onglet": "onglet-jamais-vu", "t": "lacher", "o": "x:1"})).status
        out["sans_entete"] = (await c.post(envoi, headers=a, json={"onglet": "onglet-http-01", "t": "lacher", "o": "x:1"})).status
        r = await c.post(envoi, headers=ecrire_a, json={"onglet": "onglet-http-01", "t": "prendre", "o": "affiche:demo-3",
                                                        "ti": "l'affiche de Kolax"})
        out["prendre"] = (r.status, await r.json())
        out["vu_par_b"] = (await _attendre(wb, "verrou"))["v"]["id"]
        #  Une demande de la main attend dans la boîte de l'onglet jusqu'à son tour suivant.
        await wb.send_json({"t": "demande", "o": "affiche:demo-3"})
        await _attendre(wb, "demandee")
        r = await c.get("/tableau/espace/api/direct/etat?onglet=onglet-http-01&page=capitainerie/affiches", headers=lire_a)
        out["boite"] = (await r.json())["msgs"]
        #  La WebSocket revient pour ce même onglet : ses verrous passent à la socket, l'interrogation s'arrête.
        wa = await _socket(c, a, page="capitainerie/affiches", onglet="onglet-http-01")
        salle = tableau._direct_salles[1]
        socket_a = [p.id for p in salle.prises.values() if p.uid == FONDATEUR]
        out["passage"] = (len(socket_a), any(i.startswith("h-") for i in socket_a),
                          list(salle.verrous["affiche:demo-3"].prises) == socket_a)
        out["pas_absent"] = all(m.get("t") != "absent" for m in getattr(wb, "vus", []))
        await wa.close()
        out["libre"] = (await _attendre(wb, "libre", 2))["o"]
        await wb.close()
        return out
    out = monde.http(scenario)
    st, e = out["etat"]
    assert st == 200 and e["t"] == "etat" and {p["id"] for p in e["p"]} == {str(FONDATEUR), str(DIRECTION)} and e["msgs"] == []
    assert out["present"]["p"]["id"] == str(FONDATEUR)
    assert out["inconnu"] == 409 and out["sans_entete"] == 400, "une écriture qui ne vient pas de la page : refusée"
    assert out["prendre"][0] == 200 and out["prendre"][1]["r"][0]["t"] == "pris" and out["vu_par_b"] == str(FONDATEUR)
    assert out["boite"] == [{"t": "demande", "o": "affiche:demo-3", "par": str(DIRECTION), "nom": "Mira"}]
    assert out["passage"] == (1, False, True), "plus d'onglet en interrogation ; le verrou est à la socket"
    assert out["pas_absent"]
    assert out["libre"] == "affiche:demo-3"


# ═══════════════════════════════════════════════════════════════════════════════
#  D11 — « a changé pendant ta pause » : le compteur d'écritures
# ═══════════════════════════════════════════════════════════════════════════════

def test_D11_la_reprise_dit_si_quelqu_un_d_autre_a_ecrit_entre_temps(monde):
    a, b = monde.biscuit(FONDATEUR), monde.biscuit(DIRECTION)

    async def ecrire(g, auteur, requete, corps):
        return 200, {"ok": True}
    tableau.monter({"t/question": {"methode": "POST", "fn": ecrire, "verrou": lambda c: f"question:{c.get('id')}"}})
    ecrire_a = dict(a, **{"X-Tableau": "1", "Origin": BASE})
    ecrire_b = dict(b, **{"X-Tableau": "1", "Origin": BASE})

    async def prendre(ws, n=None):
        m = {"t": "prendre", "o": "question:q1", "ti": "la question 1"}
        if n is not None:
            m["n"] = n
        await ws.send_json(m)
        return await _attendre(ws, "pris")

    async def lacher(ws, autre):
        await ws.send_json({"t": "lacher", "o": "question:q1"})
        await _attendre(autre, "libre")

    async def scenario(c):
        out = {}
        wa = await _socket(c, a)
        wb = await _socket(c, b)
        p = await prendre(wa)
        out["debut"] = (p["n"], p["ch"])
        await c.post("/tableau/espace/api/t/question", json={"id": "q1"}, headers=ecrire_a)
        await lacher(wa, wb)
        #  La pause du fondateur : il ne connaît que le compteur 1. La direction écrit (2), puis rend la main.
        p = await prendre(wb)
        out["direction"] = (p["n"], p["ch"])
        await c.post("/tableau/espace/api/t/question", json={"id": "q1"}, headers=ecrire_b)
        await lacher(wb, wa)
        p = await prendre(wa, n=1)
        out["reprise_apres_autre"] = (p["n"], p["ch"])
        #  Ses propres écritures ne comptent pas : il écrit (3), rend la main, la reprend en connaissant 2.
        await c.post("/tableau/espace/api/t/question", json={"id": "q1"}, headers=ecrire_a)
        await lacher(wa, wb)
        p = await prendre(wa, n=2)
        out["reprise_apres_soi"] = (p["n"], p["ch"])
        await wa.close()
        await wb.close()
        return out
    out = monde.http(scenario)
    assert out["debut"] == (0, False) and out["direction"] == (1, False)
    assert out["reprise_apres_autre"] == (2, True), "quelqu'un d'autre a écrit : la page relira la dernière version"
    assert out["reprise_apres_soi"] == (3, False), "ses propres écritures : rien à relire"
    #  Une histoire perdue (compteur effacé, serveur redémarré) : prudence, « a changé ».
    tableau._direct_ecrits.clear()
    assert tableau._ecrit_depuis(1, "question:q1", 3, FONDATEUR) is True
    assert tableau._ecrit_depuis(1, "question:q1", 0, FONDATEUR) is False and tableau._ecrit_depuis(1, "question:q1", None, 1) is False
    tableau._direct_ecrits[(1, "x:1")] = {"n": 20, "h": [(k, DIRECTION) for k in range(13, 21)]}
    assert tableau._ecrit_depuis(1, "x:1", 5, FONDATEUR) is True, "trop vieux pour l'histoire gardée : a changé"


# ═══════════════════════════════════════════════════════════════════════════════
#  D12 — la table des clés et les routes réelles
# ═══════════════════════════════════════════════════════════════════════════════

def test_D12_les_cles_collent_aux_routes_reelles_et_une_lecture_ne_verrouille_rien():
    import affiches
    import evenements
    import questionnaire
    ecritures = {}
    for source in (affiches.ROUTES_SITE, questionnaire.ROUTES_SITE, evenements.ROUTES_SITE,
                   {n: list(d.values()) for n, d in tableau._INTERNES.items()}):
        for nom, d in source.items():
            for x in (d if isinstance(d, list) else [d]):
                r = x if "nom" in x else tableau._normaliser_route(nom, x)
                if r["ecriture"]:
                    ecritures[nom] = r
    inconnues = sorted(set(tableau.VERROUS_ROUTES) - set(ecritures))
    assert not inconnues, f"une clé de verrou pour une écriture qui n'existe pas : {inconnues}"
    #  Les écritures qui modifient un objet que la page ouvre dans un éditeur ont toutes leur clé.
    for nom in ("rell/affiche", "rell/catalogue/element", "rell/catalogue/type", "recrutement/question", "recrutement/modele",
                "recrutement/liens", "recrutement/reglages", "recrutement/corriger", "recrutement/decision", "recrutement/etape1",
                "clan/brouillon", "clan/modifier", "clan/annuler", "rell/metiers/reglages", "rell/role", "nettoyage/regle"):
        assert nom in tableau.VERROUS_ROUTES, nom
    assert set(tableau.VERROUS_ACTIONS) <= set(("ticket_fermer", "candidature"))

    def lire(g, a, r, c):
        return 200, {}
    with pytest.raises(ValueError):
        tableau._normaliser_route("x/y", {"methode": "GET", "fn": lire, "verrou": lambda c: "a:1"})
    with pytest.raises(ValueError):
        tableau._normaliser_route("x/y", {"methode": "POST", "fn": lire, "verrou": "affiche:1"})
    assert tableau._normaliser_route("x/y", {"methode": "POST", "fn": lire})["verrou"] is None
    #  La route `direct/envoi` : un POST qui n'est pas une écriture (ni journal, ni cadence d'écriture, ni cache vidé).
    r = tableau._INTERNES["direct/envoi"]["POST"]
    assert r["ecriture"] is False and r["hors_ligne"] is False and r["corps_max"] == tableau.DIRECT_MSG_MAX


def test_D13_la_page_est_branchee():
    """Le direct est chargé, stylé, gardé hors ligne, et branché dans les éditeurs (les mêmes clés que le serveur)."""
    site = RACINE / "site"
    index = (site / "index.html").read_text(encoding="utf-8")
    sw = (site / "sw.js").read_text(encoding="utf-8")
    app = (site / "app.js").read_text(encoding="utf-8")
    assert '/tableau/espace/s/direct.css?v={{V}}' in index
    assert '"direct.js"' in sw and '"direct.css"' in sw and r"api\/(?!direct\/)" in sw, "le direct n'est jamais servi de mémoire"
    assert 'import { demarrerDirect } from "./direct.js";' in app and "demarrerDirect();" in app
    hl = (site / "hors_ligne.js").read_text(encoding="utf-8")
    assert "st === 423" in hl and 'emettre("file:verrou"' in hl
    cap = (site / "capitainerie.js").read_text(encoding="utf-8")
    rec = (site / "recrutement.js").read_text(encoding="utf-8")
    ann = (site / "annonces.js").read_text(encoding="utf-8")
    dis = (site / "discord.js").read_text(encoding="utf-8")
    for texte, cles in ((cap, ('"affiche:" + a.id', '"affiche-membre:"', '"element:" + e.type + ":" + e.cle', '"catalogue:types"',
                              '"metiers:reglages"', '"role:" + t.cle + ":" + e.cle')),
                        (rec, ('"dossier:" + ticket', '"question:" + q.id', '"modele:" + m.id', '"questionnaire:liens"',
                               '"questionnaire:reglages"')),
                        (ann, ('"evenement:" : "brouillon:"', '"brouillon:" : "evenement:"')), (dis, ('"nettoyage:" + r.cle',))):
        for cle in cles:
            assert cle in texte, cle
    for texte in (cap, rec):
        assert "protegerEditeur(p," in texte
    assert "protegerZone(zone" in ann and "protegerZone(carte" in dis
    #  Pas de style en ligne (CSP), pas de classe qui en écrase une autre (« .verrou » est celle du défilement bloqué).
    direct = (site / "direct.js").read_text(encoding="utf-8")
    css = (site / "direct.css").read_text(encoding="utf-8")
    assert "innerHTML" not in direct and ".style =" not in direct and "setAttribute(\"style\"" not in direct
    assert not any(ligne.lstrip().startswith(".verrou") for ligne in css.splitlines())


# ═══════════════════════════════════════════════════════════════════════════════
#  D14 — une autre portée de session n'entre pas dans le direct
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("portee", ["equipage", None])
def test_D14_seules_les_sessions_de_la_tete_entrent_dans_le_direct(monde, monkeypatch, portee):
    """Une session « equipage » (les membres du clan, en lecture seule) — ou sans portée dite — : la socket est refusée
    proprement (4406, la page s'arrête sans bruit), l'interrogation aussi (403) ; rien n'entre dans la salle."""
    vrai = tableau._verifier

    async def autre_portee(request, *args, **kw):
        j, g = await vrai(request, *args, **kw)
        j = {k: v for k, v in j.items() if k != "p"}
        if portee is not None:
            j["p"] = portee
        return j, g
    a = monde.biscuit(FONDATEUR)

    async def scenario(c):
        monkeypatch.setattr(tableau, "_verifier", autre_portee)
        ws = await c.ws_connect("/tableau/espace/direct", headers=dict(a, Origin=BASE))
        code = await _fermeture(ws)
        r = await c.get("/tableau/espace/api/direct/etat?onglet=onglet-equipage-1", headers=dict(a, **{"X-Tableau": "1"}))
        r2 = await c.post("/tableau/espace/api/direct/envoi", json={"onglet": "onglet-equipage-1", "t": "prendre", "o": "affiche:1"},
                          headers=dict(a, **{"X-Tableau": "1", "Origin": BASE}))
        monkeypatch.setattr(tableau, "_verifier", vrai)
        salle = tableau._direct_salles.get(1)
        return code, r.status, (await r.json())["erreur"], r2.status, len(salle.prises) if salle else 0
    code, st, erreur, st2, n = monde.http(scenario)
    assert code == tableau.CODE_PORTEE == 4406
    assert (st, st2) == (403, 403) and erreur == "Réservé au fondateur et à la direction."
    assert n == 0
    js = (RACINE / "site" / "direct.js").read_text(encoding="utf-8")
    assert "code === 4406" in js and "horsPortee()" in js, "la page s'arrête sans bruit (ni reconnexion, ni interrogation)"
