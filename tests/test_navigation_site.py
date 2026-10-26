"""27/10/2026 — la navigation regroupée du site (« La Capitainerie ») : moins d'onglets, rien de perdu.

Le fondateur : simplifier énormément, regrouper tous les onglets, « pas des milliers de sous-onglets ». L'Aperçu est dans
l'accueil, les tickets du clan dans Tickets (« Clan · RELL Seas »), les fiches techniques dans Équipage (une vue),
Textes & noms et Nettoyage dans La Capitainerie › Réglages.

N1 chaque ancienne adresse mène au bon endroit (`site/noyau.js` exécuté par node) ; `aller()` les suit aussi.
N2 chaque rubrique a son rendu (app.js), chaque rendu sa rubrique ; une rubrique d'avant gardée en mémoire est suivie.
N3 plus aucune ancienne adresse dans la page, les outils de contrôle ni le bot (hors la table des alias et ses essais).
N4 au plus cinq rubriques par catégorie et cinq sous-onglets par rubrique ; le catalogue choisit son type dans une liste.
N5 un nom choisi par la direction pour une rubrique déplacée la suit (une fois, sans écraser ; trop long : refusé, dit).
N6 Réglages : un sous-onglet = une ligne ; les compteurs, la recherche et la présence en direct suivent les rubriques.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import aiosqlite
import pytest

import textes

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "site"
#  Les rubriques d'avant (26/10) et leur place d'aujourd'hui : [catégorie, rubrique, sous-page].
ANCIENNES = {
    "#port/apercu": ["accueil", "attente", ""],
    "#port/nettoyage": ["capitainerie", "reglages", "nettoyage"],
    "#capitainerie/textes": ["capitainerie", "reglages", "textes"],
    "#equipage/fiches": ["equipage", "membres", "fiches"],
    "#equipage/tickets": ["port", "tickets", "clan"],
    "#equipage/candidatures/questionnaire": ["capitainerie", "recrutement", "questions"],
}
_RE_ANCIENNES = re.compile(r"port/apercu|port/nettoyage|equipage/fiches|equipage/tickets|capitainerie/textes")


def _noeud(script: str, *args) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent : la navigation n'est pas exécutée")
    r = subprocess.run([node, "--input-type=module", "-e", script, *args], capture_output=True, text=True, timeout=60,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


#  noyau.js tel quel, dans node : une adresse posée, `lireAncre()` relu ; `aller()` vers une rubrique d'avant.
SCRIPT_ANCRES = r"""
globalThis.location = { hash: "" };
const n = await import(process.argv[1]);
const out = {};
for (const a of JSON.parse(process.argv[2])) {
  location.hash = a;
  const r = n.lireAncre();
  out[a] = { route: [r.cat, r.rub, r.sous], alias: r.alias, membre: r.membre };
}
const allers = {};
for (const [c, r, s] of [["port", "nettoyage"], ["capitainerie", "textes"], ["equipage", "fiches"], ["equipage", "tickets"], ["port", "apercu"], ["port", "salons", "sondages"]]) {
  location.hash = "#depart";
  n.aller(c, r, s);
  allers[[c, r, s].filter(Boolean).join("/")] = location.hash;
}
console.log(JSON.stringify({ out, allers, cats: n.CATEGORIES.map((c) => [c.cle, c.rubriques.map((r) => r.cle)]) }));
"""


def _navigation(ancres) -> dict:
    return _noeud(SCRIPT_ANCRES, (SITE / "noyau.js").as_uri(), json.dumps(ancres))


def test_N1_les_anciennes_adresses_menent_au_bon_endroit():
    d = _navigation([*ANCIENNES, "#port/apercu&membre=123456789", "#port/journal", "#port/salons/sondages",
                     "#capitainerie/reglages/nettoyage", "#equipage/membres/fiches", "#port/tickets/clan"])
    out, cats = d["out"], dict((c, set(r)) for c, r in d["cats"])
    for ancre, (cat, rub, sous) in ANCIENNES.items():
        assert out[ancre]["route"] == [cat, rub, sous], (ancre, out[ancre])
        assert out[ancre]["alias"] is True, f"{ancre} : l'adresse est réécrite (la nouvelle reste dans la barre)"
        assert rub in cats[cat], (ancre, cat, rub)
    assert out["#port/apercu&membre=123456789"] == {"route": ["accueil", "attente", ""], "alias": True, "membre": "123456789"}, \
        "la fiche ouverte suit l'adresse réécrite"
    for ancre in ("#port/journal", "#port/salons/sondages", "#capitainerie/reglages/nettoyage", "#equipage/membres/fiches",
                  "#port/tickets/clan"):
        assert out[ancre]["alias"] is False and out[ancre]["route"] == ancre[1:].split("/") + [""] * (3 - len(ancre[1:].split("/"))), \
            (ancre, out[ancre])
    assert d["allers"] == {"port/nettoyage": "#capitainerie/reglages/nettoyage", "capitainerie/textes": "#capitainerie/reglages/textes",
                           "equipage/fiches": "#equipage/membres/fiches", "equipage/tickets": "#port/tickets/clan",
                           "port/apercu": "#accueil/attente", "port/salons/sondages": "#port/salons/sondages"}, d["allers"]
    #  Les adresses du site v1 (`#onglet=apercu`) : app.js les range aussi (l'Aperçu : l'accueil).
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert 'apercu: ["accueil", "attente"]' in app


def test_N2_chaque_rubrique_a_son_rendu():
    cats = _navigation([])["cats"]
    attendues = {f"{c}/{r}" for c, rs in cats for r in rs}
    app = (SITE / "app.js").read_text(encoding="utf-8")
    rendus = app[app.index("const RENDUS = {"):app.index("};", app.index("const RENDUS = {"))]
    cles = set(re.findall(r'"(\w+/\w+)":', rendus))
    assert cles == attendues, (sorted(cles - attendues), sorted(attendues - cles))
    autonomes = set(re.findall(r'"(\w+/\w+)"', app[app.index("const AUTONOMES"):app.index("]);", app.index("const AUTONOMES"))]))
    assert autonomes <= attendues and "capitainerie/reglages" in autonomes
    #  Une rubrique d'avant gardée en mémoire (sessionStorage, page rouverte sans adresse) : suivie, pas perdue.
    assert "suivreAlias([mem.cat, mem.rub]" in app
    #  Une autre vue de la même rubrique : la rubrique la montre elle-même (`ctrl.sous`), sans tout redessiner.
    assert "if (lireRoute(false) && !changerSousEnPlace())" in app and "c.sous(sous) === false" in app


def test_N3_plus_aucune_ancienne_adresse():
    fautes = []
    fichiers = [*SITE.glob("*.js"), *SITE.glob("*.html"), *(RACINE / "outils").glob("*.mjs"),
                *(f for f in RACINE.glob("*.py")), RACINE / "tableau_page.html"]
    for f in fichiers:
        if f.name == "noyau.js":
            continue   # la table des alias elle-même
        for i, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if _RE_ANCIENNES.search(ligne) and "ANCIENNES" not in ligne and not re.search(r"anciennes? adresses?", ligne):
                fautes.append(f"{f.name}:{i}: {ligne.strip()[:140]}")
    assert not fautes, "\n".join(fautes)
    noyau = (SITE / "noyau.js").read_text(encoding="utf-8")
    for ancre, (cat, rub, sous) in ANCIENNES.items():
        assert f'"{ancre[1:].rsplit("/", 1)[0] if ancre.count("/") > 1 else ancre[1:]}": ["{cat}", "{rub}"' in noyau, ancre


def test_N4_cinq_onglets_au_plus():
    cats = _navigation([])["cats"]
    assert all(len(rs) <= 5 for _c, rs in cats), cats
    assert [len(rs) for _c, rs in cats] == [1, 5, 2, 5], "Accueil 1 · Le Port 5 · L'Équipage 2 · La Capitainerie 5"
    lignes = {}
    for f in SITE.glob("*.js"):
        src = f.read_text(encoding="utf-8")
        for prefixe, corps in re.findall(r'nommerOnglets\("site\.sous\.([a-z.]+)", \[(.*?)\]\);', src, re.S):
            lignes[prefixe] = re.findall(r'\["([\w-]+)", "[^"]+", "\w+"', corps)
    assert set(lignes) == {"port.tickets", "port.salons", "equipage.membres", "capitainerie.recrutement", "equipage.annonces",
                           "capitainerie.reglages"}, sorted(lignes)
    #  Salons & questions nomme sept choses, mais n'a que cinq onglets : « Idées & sondages » réunit deux vues.
    dis = (SITE / "discord.js").read_text(encoding="utf-8")
    onglets = json.loads(re.search(r"const ONGLETS_SALONS = (\[.*?\]);", dis).group(1))
    vues = json.loads(re.search(r"const VUES_AVIS = (\[.*?\]);", dis).group(1))
    assert onglets == ["questions", "avis", "entraide", "annonces", "droits"] and vues == ["idees", "sondages"]
    assert set(lignes["port.salons"]) == set(onglets) | set(vues)
    for prefixe, cles in lignes.items():
        if prefixe != "port.salons":
            assert len(cles) <= 5, (prefixe, cles)
    #  Le catalogue : plus de rangée d'onglets (un par type) ; le type se choisit dans une liste.
    cap = (SITE / "capitainerie.js").read_text(encoding="utf-8")
    catalogue = cap[cap.index("export function catalogue("):cap.index("function creditsRell(")]
    assert "sous-onglets" not in catalogue and 'label: "Type"' in catalogue and "typeL.options(" in catalogue


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


def test_N5_un_nom_choisi_suit_sa_rubrique_deplacee(tmp_path):
    journal = []
    get_db = _base(tmp_path / "textes.db")
    textes.setup(get_db=get_db, log=journal.append)
    try:
        asyncio.run(textes.init_db())   # la table, vide

        async def poser(lignes):
            async with get_db() as db:
                for gid, cle, valeur in lignes:
                    await db.execute("INSERT INTO site_textes (guild_id, cle, valeur, version, maj_le, maj_par) VALUES (?,?,?,3,?,?)",
                                     (gid, cle, valeur, 1_700_000_000, 42))
                await db.commit()
        asyncio.run(poser([
            (1, "site.rub.port.nettoyage.titre", "Grand ménage"),                 # → Réglages › Nettoyage
            (1, "site.rub.equipage.tickets.titre", "Tickets RELL"),               # → Tickets › Clan · RELL Seas
            (1, "site.rub.equipage.fiches.titre", "Les affiches"),                # la nouvelle place a déjà son nom
            (1, "site.sous.equipage.membres.fiches", "Mes fiches"),
            (1, "site.rub.capitainerie.textes.titre", "Les textes du bot et les noms du site"),   # 37 > 30 : trop long
            (2, "site.rub.port.nettoyage.titre", None),                           # remis à l'origine : rien à reprendre
            (2, "site.rub.port.apercu.titre", "Coup d'œil"),                      # absorbé par l'accueil : rien à reprendre
        ]))
        asyncio.run(textes.init_db())
        asyncio.run(textes.init_db())   # une seconde fois : rien ne change (une seule reprise)
        v1, v2 = textes.valeurs_site(1), textes.valeurs_site(2)
        assert v1["site.sous.capitainerie.reglages.nettoyage"] == "Grand ménage"
        assert v1["site.sous.port.tickets.clan"] == "Tickets RELL"
        assert v1["site.sous.equipage.membres.fiches"] == "Mes fiches", "un nom déjà choisi à la nouvelle place n'est jamais écrasé"
        assert "site.sous.capitainerie.reglages.textes" not in v1, "trop long pour un sous-onglet : le nom d'origine reste"
        assert not any(k.startswith("site.sous.") for k in v2), v2
        #  Les anciennes clés ne sont plus des noms du site (plus déclarées) : la page ne les reçoit plus.
        assert not any(k.startswith(("site.rub.port.nettoyage", "site.rub.equipage.tickets", "site.rub.port.apercu")) for k in v1)
        it = textes.item(type("G", (), {"id": 1, "get_member": lambda self, uid: None})(), "site.sous.capitainerie.reglages.nettoyage")
        assert it["modifie"] and it["version"] == 1 and it["maj_le"] == 1_700_000_000, "repris avec sa date, en version 1"
        assert "[TEXTES][E7] nom déplacé non repris : le nom d'origine reste" in journal, "le refus est dit (message stable)"
        assert sum(x.startswith("[TEXTES][E7:DETAIL]") for x in journal) == 2, "une fois par démarrage, le détail à part"
        assert "[TEXTES] noms déplacés repris (navigation regroupée)" in journal
        n = asyncio.run(_compter(get_db))
        assert n == 7 + 2, "deux noms repris, une seule fois"
    finally:
        textes.setup(get_db=None)


async def _compter(get_db) -> int:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM site_textes") as cur:
            return (await cur.fetchone())[0]


def test_N6_reglages_une_ligne_et_ce_qui_suit_les_rubriques():
    reg = (SITE / "reglages.js").read_text(encoding="utf-8")
    ligne = re.search(r'export const SOUS_REGLAGES = nommerOnglets\("site\.sous\.capitainerie\.reglages", \[(.*)\]\);', reg).group(1)
    assert re.findall(r'\["(\w+)", "[^"]+", "\w+", (\w+)\]', ligne) == [("textes", "textes"), ("nettoyage", "nettoyage")], \
        "un sous-onglet = [clé, nom, icône, rendu] : une ligne pour en ajouter un (« Sécurité »)"
    assert ("capitainerie", "reglages", (("textes", "Textes & noms"), ("nettoyage", "Nettoyage"))) in textes.SITE_SOUS
    sw = (SITE / "sw.js").read_text(encoding="utf-8")
    assert '"reglages.js"' in sw, "gardé hors ligne"
    app = (SITE / "app.js").read_text(encoding="utf-8")
    assert '"capitainerie/reglages": reglages.reglages' in app
    #  Les compteurs : les alertes de l'Aperçu sur le Répertoire, plus d'étiquette disparue.
    compteurs = app[app.index("function compteurs()"):app.index("function majCompteurs()")]
    assert '"port/repertoire": [alertes' in compteurs and '"port/apercu"' not in compteurs and '"equipage/tickets"' not in compteurs
    #  La recherche trouve les anciennes rubriques sous leur nom (renommable) et celui d'avant.
    rech = (SITE / "recherche.js").read_text(encoding="utf-8")
    for morceau in ('["capitainerie", "reglages", "nettoyage", nomDans(SOUS_REGLAGES, "nettoyage")', '["port", "tickets", "clan"',
                    '["equipage", "membres", "fiches", nomDans(VUES_EQUIPAGE, "fiches")', '"aperçu tendances"'):
        assert morceau in rech, morceau
    #  La présence en direct (« où est chacun ») : les nouvelles sous-pages ont un nom, une page d'avant est dite à sa place.
    direct = (SITE / "direct.js").read_text(encoding="utf-8")
    for sous in ("fiches", "equipes", "clan", "normaux", "textes", "nettoyage", "sondages"):
        assert re.search(r"\b" + sous + r': "', direct), sous
    assert "suivreAlias(bruts.filter(Boolean))" in direct
