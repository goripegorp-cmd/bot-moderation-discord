"""25/10/2026 — l'onglet « Annonces & événements » du site v2 (`site/annonces.js`) contre le VRAI serveur.

La page avait été écrite contre une maquette qui inventait ses propres formes ; seul le vrai serveur l'a montré :
les rappels suggérés envoyés en paires « minutes, libellé » (relus comme des nombres, puis renvoyés et refusés), le
post d'un brouillon rouvert renvoyé comme l'objet { id, nom } (refusé : « Ce post n'est pas une destination… »),
l'annonce des métiers proposée « par grade » (refusée), les styles de boutons « succes » et « secondaire » inconnus
de la feuille de style, les annonces publiées rangées dans « Passés » sans geste pour les modifier ni les retirer,
l'heure saisie lue dans le fuseau de l'appareil au lieu de Paris, et le vrai site local sans forum du clan (rien ne
s'y publiait).

ES1 la maquette répond EXACTEMENT comme le serveur — statuts, clés, types, messages d'erreur — sur le même parcours
(brouillon, conflit, refus, aperçu, publier, publication incertaine puis forcée, modifier, actualiser, annuler, image,
annonce retirée, listing, supprimer) : un contrôle fait sur la maquette dit vrai. ES2 le vrai site local a le forum
du clan, l'évènement Discord et des exemples dans chaque liste. ES3 les fonctions de la page (heure de Paris, durées
des cartes, extraits sans Markdown) donnent ce que le serveur donne (exécutées par Node, s'il est là)."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
import pytest

import evenements as E
import paths
import tableau
import transcript_store
from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
PORT = 8790


@pytest.fixture
def sites(tmp_path, monkeypatch):
    """Le vrai site local et la maquette, en mémoire ; l'état global du site et du module restauré après (comme V16)."""
    monkeypatch.setattr(tableau, "ROUTES", {})
    monkeypatch.setattr(tableau, "REGLES", dict(tableau.REGLES))
    monkeypatch.setattr(tableau, "_SOURCES_MEDIAS", [])
    monkeypatch.setattr(tableau, "RACINE_DONNEES", None)
    monkeypatch.setattr(transcript_store, "_BASE_DIR", transcript_store._BASE_DIR)
    monkeypatch.setattr(paths, "_RESOLVED_BASE", paths._RESOLVED_BASE)
    for nom in ("_get_db", "_cfg", "_journal", "_role_clan", "_langue", "_est_tete", "_log", "_fiches", "_catalogue",
                "_media", "_mur"):
        monkeypatch.setattr(E, nom, getattr(E, nom))
    E._verrous.clear()
    monkeypatch.syspath_prepend(str(RACINE / "outils"))
    import site_local
    import site_maquette
    monkeypatch.setattr(site_maquette, "MONDE", site_maquette.Monde(7))
    yield Obj(local=site_local, maquette=site_maquette, dossier=tmp_path)
    E._verrous.clear()
    for m in ("site_local", "site_maquette"):
        sys.modules.pop(m, None)


class Client:
    """Les gestes de la page : GET api, POST api, une opération rejouée par sync."""

    def __init__(self, c, lire: dict, ecrire: dict):
        self.c, self.lire, self.ecrire = c, lire, ecrire

    async def get(self, nom, **params):
        r = await self.c.get("/tableau/espace/api/" + nom, params=params, headers=self.lire)
        return r.status, await r.json()

    async def post(self, nom, corps):
        r = await self.c.post("/tableau/espace/api/" + nom, json=corps, headers=self.ecrire)
        return r.status, await r.json()

    async def sync(self, api, corps):
        r = await self.c.post("/tableau/espace/sync", json={"ops": [{"op_id": str(uuid.uuid4()), "api": api, "corps": corps}]},
                              headers=self.ecrire)
        res = (await r.json())["resultats"][0]
        return res["status"], res["corps"]


def _png() -> str:
    from PIL import Image
    f = io.BytesIO()
    Image.new("RGB", (64, 32), (31, 78, 90)).save(f, "PNG")
    return base64.b64encode(f.getvalue()).decode()


async def parcours(s: Client, incertain) -> dict:
    """Le même parcours sur un site ; `incertain(actif)` : la prochaine publication part sans confirmation de Discord."""
    out = {}
    cle = lambda: "essai-" + uuid.uuid4().hex[:12]  # noqa: E731
    st, ev = await s.get("clan/evenements")
    out["evenements"] = (st, ev)
    dest = ev["destinations"][1]["id"]
    q = int(time.time()) + 3 * 86400
    st, r = await s.sync("clan/brouillon", {"type": "evenement", "cle_client": cle(), "titre": "Forme", "quand": q, "lieu": "Île",
                                            "rappels": [1440, 60, 0], "places": 5, "destination": dest, "mention": "clan",
                                            "discord_event": True})
    out["brouillon_cree"] = (st, r)
    e = r["element"]
    st, r = await s.sync("clan/brouillon", {"id": e["id"], "version": e["version"], "type": "evenement", "texte": "**Gras**"})
    out["brouillon_modifie"] = (st, r)
    e = r["element"]
    out["brouillon_conflit"] = await s.sync("clan/brouillon", {"id": e["id"], "version": e["version"] - 1, "type": "evenement", "titre": "x"})
    out["brouillon_champ_inconnu"] = await s.sync("clan/brouillon", {"id": e["id"], "version": e["version"], "type": "evenement", "x": 1})
    #  Ce que la page envoyait avant : le post en objet, des rappels en paires, les métiers rangés par grade.
    out["brouillon_post_objet"] = await s.sync("clan/brouillon", {"id": e["id"], "version": e["version"], "type": "evenement",
                                                                  "destination": {"id": dest, "nom": "Annonces"}})
    out["brouillon_rappels_paires"] = await s.sync("clan/brouillon", {"id": e["id"], "version": e["version"], "type": "evenement",
                                                                      "rappels": [[60, "1 h avant"]]})
    out["brouillon_metiers_par_grade"] = await s.sync("clan/brouillon", {"type": "metiers", "groupement": "grade", "cle_client": cle()})
    out["apercu_brouillon"] = await s.get("clan/apercu", id=e["id"])
    out["publier_conflit"] = await s.post("clan/publier", {"id": e["id"], "version": e["version"] + 5})
    incertain(True)
    out["publier_incertain"] = await s.post("clan/publier", {"id": e["id"], "version": e["version"]})
    incertain(False)
    st, ev = await s.get("clan/evenements")
    e = next(x for x in ev["a_venir"] if x["id"] == e["id"])
    out["liste_incertain"] = (st, e)
    out["publier_sans_forcer"] = await s.post("clan/publier", {"id": e["id"], "version": e["version"]})
    st, r = await s.post("clan/publier", {"id": e["id"], "version": e["version"], "forcer": True})
    out["publier_force"] = (st, r)
    e = r["element"]
    out["publier_deja"] = await s.post("clan/publier", {"id": e["id"], "version": e["version"]})
    out["apercu_publie"] = await s.get("clan/apercu", id=e["id"])
    st, r = await s.post("clan/modifier", {"id": e["id"], "version": e["version"], "lieu": "Autre île"})
    out["modifier"] = (st, r)
    e = r["element"]
    out["modifier_conflit"] = await s.post("clan/modifier", {"id": e["id"], "version": e["version"] - 1, "lieu": "x"})
    out["modifier_post"] = await s.post("clan/modifier", {"id": e["id"], "version": e["version"], "destination": ev["destinations"][0]["id"]})
    out["modifier_passe"] = await s.post("clan/modifier", {"id": e["id"], "version": e["version"], "quand": int(time.time()) - 60})
    out["actualiser"] = await s.post("clan/modifier", {"id": e["id"], "version": e["version"]})
    out["annuler"] = await s.post("clan/annuler", {"id": e["id"], "prevenir": False})
    out["annuler_deja"] = await s.post("clan/annuler", {"id": e["id"], "prevenir": False})
    out["modifier_annule"] = await s.post("clan/modifier", {"id": e["id"], "version": e["version"] + 2, "lieu": "x"})
    st, m = await s.post("media", {"nom": "essai.png", "type": "image/png", "base64": _png()})
    out["media"] = (st, m)
    out["media_refusee"] = await s.post("media", {"nom": "x.txt", "base64": base64.b64encode(b"pas une image").decode()})
    st, r = await s.sync("clan/brouillon", {"type": "annonce", "cle_client": cle(), "titre": "Annonce", "texte": "Texte", "image": m["id"]})
    a = r["element"]
    out["apercu_annonce"] = await s.get("clan/apercu", id=a["id"])
    st, r = await s.post("clan/publier", {"id": a["id"], "version": a["version"]})
    out["publier_annonce"] = (st, r)
    out["retirer"] = await s.post("clan/annuler", {"id": r["element"]["id"]})
    st, r = await s.sync("clan/brouillon", {"type": "listing", "cle_client": cle(), "titre": "Listing", "groupement": "race",
                                            "champs": ["metiers"]})
    out["apercu_listing"] = await s.get("clan/apercu", id=r["element"]["id"])
    out["supprimer"] = await s.sync("clan/supprimer_brouillon", {"id": r["element"]["id"], "version": r["element"]["version"]})
    out["supprimer_deja"] = await s.sync("clan/supprimer_brouillon", {"id": r["element"]["id"]})
    st, r = await s.sync("clan/brouillon", {"type": "annonce", "cle_client": cle()})
    out["publier_sans_titre"] = await s.post("clan/publier", {"id": r["element"]["id"]})
    out["evenements_apres"] = await s.get("clan/evenements")
    return out


def forme(x):
    """Types et clés ; un dictionnaire indexé par identifiant (personnes, rôles) : la forme de ses valeurs ; une liste :
    son premier élément, ou un exemple de chaque type de bloc."""
    if isinstance(x, dict):
        if x and all(str(k).isdigit() for k in x):
            return {"<id>": forme(next(iter(x.values())))}
        return {k: forme(v) for k, v in sorted(x.items())}
    if isinstance(x, list):
        if not x:
            return ["vide"]
        if all(isinstance(e, dict) and "type" in e for e in x):
            par = {}
            for e in x:
                par.setdefault(e["type"], forme(e))
            return ["blocs", par]
        return [forme(x[0])]
    if x is None:
        return "None"
    if isinstance(x, bool):
        return "bool"
    return "nombre" if isinstance(x, (int, float)) else type(x).__name__


def ecarts(a, b, chemin="") -> list:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{chemin}.{k} : seulement {'dans la maquette' if k not in a else 'sur le serveur'}")
            else:
                out += ecarts(a[k], b[k], f"{chemin}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if a and b and a[0] == "blocs" == b[0]:
            return [x for t in sorted(set(a[1]) & set(b[1])) for x in ecarts(a[1][t], b[1][t], f"{chemin}[{t}]")]
        return ecarts(a[0], b[0], chemin + "[0]") if a != ["vide"] and b != ["vide"] else []
    return [f"{chemin} : {a} (serveur) ≠ {b} (maquette)"] if a != b and "None" not in (a, b) else []


def test_ES1_la_maquette_repond_comme_le_serveur(sites):
    from aiohttp.test_utils import TestClient, TestServer

    async def scenario():
        app, ctx = await sites.local.construire(sites.dossier / "local", PORT)
        maquette = sites.maquette.MONDE
        posts = {int(x["id"]): ctx.guild.fils[int(x["id"])] for x in ctx.conf["clan_posts"].values()}
        envoyer = {k: f.send for k, f in posts.items()}

        def panne(actif):
            """Discord ne confirme pas l'envoi et le post ne se relit pas : la publication est « incertaine »."""
            for k, f in posts.items():
                if actif:
                    async def refus(*_a, **_k):
                        raise discord.HTTPException(Obj(status=503, reason="x"), "panne")

                    def illisible(*_a, **_k):
                        raise discord.HTTPException(Obj(status=503, reason="x"), "panne")
                    f.send, f.history = refus, illisible
                else:
                    f.send = envoyer[k]
                    f.__dict__.pop("history", None)

        def incertaine(actif):
            maquette.prochaine_incertaine = actif
        async with TestClient(TestServer(app)) as c1, TestClient(TestServer(sites.maquette.application())) as c2:
            r = await c1.get("/tableau/demo", allow_redirects=False)
            h = {"Cookie": f"{tableau.COOKIE}={r.cookies[tableau.COOKIE].value}"}
            serveur = await parcours(Client(c1, h, dict(h, **{"X-Tableau": "1", "Origin": f"http://localhost:{PORT}"})), panne)
            copie = await parcours(Client(c2, {}, {"X-Tableau": "1"}), incertaine)
        return serveur, copie
    serveur, copie = asyncio.run(scenario())
    assert serveur.keys() == copie.keys()
    fautes = []
    for k in serveur:
        (sa, ca), (sb, cb) = serveur[k], copie[k]
        if sa != sb:
            fautes.append(f"{k} : statut {sa} (serveur) ≠ {sb} (maquette)")
        fautes += [f"{k} {x}" for x in ecarts(forme(ca), forme(cb))]
        if isinstance(ca, dict) and isinstance(cb, dict) and ca.get("erreur") != cb.get("erreur"):
            fautes.append(f"{k} : erreur {ca.get('erreur')!r} (serveur) ≠ {cb.get('erreur')!r} (maquette)")
    assert not fautes, "\n".join(fautes)
    #  Le parcours a bien éprouvé ce qu'il dit (et ce que la page doit savoir lire).
    st, r = serveur["brouillon_post_objet"]
    assert st == 400 and "destination" in r["champs"], "un post en objet est refusé : la page envoie son identifiant"
    assert serveur["brouillon_rappels_paires"][0] == 400 and serveur["brouillon_metiers_par_grade"][0] == 400
    assert serveur["publier_incertain"] == (502, {"erreur": "Discord n'a pas confirmé la publication et je n'ai pas pu "
                                                            "relire le post : regarde-le avant de republier.",
                                                  "incertain": True})
    assert serveur["liste_incertain"][1]["statut"] == "incertain" and serveur["publier_sans_forcer"][0] == 409
    assert serveur["publier_force"][0] == 200 and serveur["publier_force"][1]["element"]["discord_event"]
    ev = serveur["evenements"][1]
    assert all(isinstance(x, list) and len(x) == 2 for x in ev["rappels_suggeres"] + ev["couleurs"]), "des paires"
    assert isinstance(ev["limites"]["texte"], dict) and isinstance(serveur["brouillon_cree"][1]["element"]["destination"], dict)
    styles = {b["style"] for c in serveur["apercu_brouillon"][1]["cartes"] for bl in c["blocs"] if bl["type"] == "boutons"
              for b in bl["boutons"]}
    assert styles == {"succes", "secondaire"}, "les styles du serveur, que la page traduit pour sa feuille de style"
    apres = serveur["evenements_apres"][1]
    publiee = next(x for x in apres["passes"] if x["titre"] == "Annonce")
    assert publiee["statut"] == "retire", "une annonce publiée (puis retirée) est rangée dans « passes »"


def test_ES2_le_site_local_a_le_forum_du_clan_et_des_exemples(sites):
    from aiohttp.test_utils import TestClient, TestServer

    async def scenario():
        app, ctx = await sites.local.construire(sites.dossier / "local", PORT)
        async with TestClient(TestServer(app)) as c:
            r = await c.get("/tableau/demo", allow_redirects=False)
            h = {"Cookie": f"{tableau.COOKIE}={r.cookies[tableau.COOKIE].value}"}
            s = Client(c, h, dict(h, **{"X-Tableau": "1", "Origin": f"http://localhost:{PORT}"}))
            st, ev = await s.get("clan/evenements")
            b = next(x for x in ev["brouillons"] if x["type"] == "evenement")
            pub = await s.post("clan/publier", {"id": b["id"], "version": b["version"]})
            return st, ev, pub
    st, ev, (st_pub, pub) = asyncio.run(scenario())
    assert st == 200
    assert [d["nom"] for d in ev["destinations"]][:2] == ["Infos · Info", "Annonces · Announcements"]
    assert ev["destinations"][0]["defaut"] and ev["droits"]["discord_event"] and ev["droits"]["role_clan"]
    assert {x["type"] for x in ev["brouillons"]} == {"evenement", "annonce", "metiers"}
    a_venir = ev["a_venir"][0]
    assert a_venir["statut"] == "publie" and a_venir["reponses"]["disponibles"] == 6 and a_venir["discord_event"]
    assert {(x["type"], x["statut"]) for x in ev["passes"]} >= {("evenement", "annule"), ("annonce", "publie"),
                                                                  ("evenement", "publie")}
    termine = next(x for x in ev["passes"] if x["statut"] == "publie" and x["type"] == "evenement")
    assert termine["phase"] == "termine"
    annonce = next(x for x in ev["passes"] if x["type"] == "annonce")
    assert annonce["reponses"]["vus"] == 9 and annonce["valeurs"]["image"], "l'annonce de démonstration a son image"
    #  Les heures de démonstration sont rondes, à Paris (21:00 pour la sortie en mer).
    assert datetime.fromtimestamp(next(x for x in ev["brouillons"] if x["type"] == "evenement")["quand"],
                                  ZoneInfo("Europe/Paris")).strftime("%H:%M") == "21:00"
    assert st_pub == 200 and pub["lien"] and pub["element"]["discord_event"], "un brouillon d'exemple se publie"


def test_ES3_les_fonctions_de_la_page_donnent_ce_que_le_serveur_donne(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node n'est pas installé : les fonctions de la page ne s'exécutent pas ici")
    harnais = tmp_path / "harnais.mjs"
    harnais.write_text(r"""
import { readFileSync } from "node:fs";
const src = readFileSync(process.argv[2], "utf8");
const extraire = (nom) => {
  const i = src.indexOf("function " + nom + "(");
  if (i < 0) throw new Error("absente : " + nom);
  let n = 0, j = src.indexOf("{", i);
  for (; j < src.length; j++) { if (src[j] === "{") n++; else if (src[j] === "}" && !--n) break; }
  return src.slice(i, j + 1);
};
const date = (t) => new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(t * 1000));
const minutes = (x) => Math.max(0, Math.round(Number(Array.isArray(x) ? x[0] : x) || 0));
const deux = (n) => String(n).padStart(2, "0");
const FMT_PARIS = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const code = ["texteSimple", "dureeTxt", "partiesParis", "depuisParis"].map(extraire).join("\n").replace(/export /g, "");
const f = new Function("date", "minutes", "deux", "FMT_PARIS", code + "\nreturn { texteSimple, dureeTxt, partiesParis, depuisParis };")(date, minutes, deux, FMT_PARIS);
const q = JSON.parse(readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify({
  durees: q.durees.map((m) => f.dureeTxt(m)),
  paris: q.paris.map(([a, m, j, H, M]) => f.depuisParis(a, m, j, H, M)),
  parties: q.instants.map((t) => f.partiesParis(t)),
  extraits: q.extraits.map((x) => f.texteSimple(x)),
}));
""", encoding="utf-8")
    durees = [0, 5, 10, 45, 60, 61, 90, 120, 180, 1439, 1440, 1450, 1500, 2880, 10080, 20160]
    paris = [(2026, 10, 28, 20, 45), (2026, 7, 14, 21, 0), (2026, 10, 25, 1, 30), (2026, 10, 25, 3, 30),
             (2027, 3, 28, 1, 30), (2027, 3, 28, 3, 30), (2026, 12, 31, 23, 59), (2027, 1, 1, 0, 0)]
    instants = [1793131200, 1784055600, 1792884600, 1803778200]
    extraits = ["Rendez-vous au port **un quart d'heure avant**.\n> Les absents passent leur tour.",
                "Kolax_RS et _italique_ et __souligné__ ~~barré~~ `code`", "### Titre\n- un\n-# petit <@123>"]
    entrees = tmp_path / "entrees.json"
    entrees.write_text(json.dumps({"durees": durees, "paris": paris, "instants": instants, "extraits": extraits}), encoding="utf-8")
    sortie = subprocess.run([node, str(harnais), str(RACINE / "site" / "annonces.js"), str(entrees)], capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    assert sortie.returncode == 0, sortie.stderr
    vu = json.loads(sortie.stdout)
    assert vu["durees"] == [E._duree_txt(m) for m in durees], "les durées de l'aperçu sont celles des cartes Discord"
    paris_tz = ZoneInfo("Europe/Paris")
    assert vu["paris"] == [int(datetime(a, m, j, H, M, tzinfo=paris_tz).timestamp()) for a, m, j, H, M in paris], \
        "l'heure saisie est celle de Paris, changements d'heure compris"
    for t, p in zip(instants, vu["parties"]):
        d = datetime.fromtimestamp(t, paris_tz)
        assert (p["a"], p["m"], p["j"], p["H"], p["M"]) == (d.year, d.month, d.day, d.hour, d.minute)
    assert vu["extraits"] == ["Rendez-vous au port un quart d'heure avant. Les absents passent leur tour.",
                              "Kolax_RS et italique et souligné barré code", "Titre un petit @…"]
