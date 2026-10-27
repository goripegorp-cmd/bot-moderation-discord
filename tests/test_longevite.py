"""Le site sur plusieurs années (26/10/2026) — « est-ce qu'il peut tenir le coup ? », « qu'on puisse nettoyer tout comme
on souhaite ».

Mesuré par `outils/banc_annees.py` (1, 3 et 5 ans de serveur sur le vrai site local) ; ici, chaque correction :
LV1  `recrutements._unix` : le chemin rapide rend exactement ce que rendait `strptime` (chaînes tirées au hasard).
LV2  le journal : messages et vocal ont leur propre limite (100 000) ; le reste garde ses 90 jours ; 200 000 en tout.
LV3  `registre.lire` : le serveur seul se lit à rebours (« +guild_id »), mêmes lignes ; le comptage par jour gardé
     cinq minutes, une copie, oublié au `setup`.
LV4  `annonces.resume_vues` et `suggestions.lister` : les mêmes chiffres qu'une lecture complète.
LV5  les doubles comptes : le tri préalable ne laisse jamais passer une ressemblance ≥ 85 % ; seuls les membres
     présents sont comparés.
LV6  le compactage : conversion aux heures creuses seulement (ou forcée), refus sans place, pages VRAIMENT rendues
     (un `execute` n'en rendait qu'une), une fois par nuit ; le grand nettoyage hebdomadaire passe par l'incrémental.
LV7  la mémoire du site bornée (`_elaguer`) ; l'empreinte des données calculée une fois par version.
Sur le VRAI site local (outils/site_local.py) :
LV8  `api/journal` : pages sans trou ni doublon, filtres, comptes exacts (catégories, jours de Paris, résumé), jours
     entiers de Paris (changement d'heure compris), demandes invalides refusées.
LV9  `api/tickets/fermes` et les données : FERMES_MAX au plus, le total et les mois exacts ; un mois, une date, une
     recherche.
LV10 `api/casier/membres` et le casier : MEMBRES_CASIER cases, le total exact, la suite page par page, la recherche ;
     au-delà de CASIER_LUES entrées, les mêmes chiffres qu'une lecture complète (mois de Paris compris).
LV11 la rubrique Nettoyage : chaque famille a sa règle (rangée), l'aperçu, « Nettoyer maintenant » d'une règle, la place
     prise ; les durées que le bot tenait cachées sont les plafonds.
LV12 chaque nouvelle règle efface ce qu'elle dit et rien d'autre.
LV13 les équipes du clan (27/10/2026) : un membre parti sort de son équipe, un chef parti la laisse sans chef, sans
     place orpheline ; seulement ceux qu'on a vus partir.
LV14 les plans de SQLite des lectures corrigées.
LV15 le banc lui-même (une petite taille, sans fichiers) : il construit, nettoie, mesure et écrit son rapport.
LV16 la page : ses fonctions pures (aperçu, comptes, familles, réunion des fermés).
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import os
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import annonces
import compactage
import data_cleanup
import gdpr
import questions
import recrutements
import registre
import suggestions
import tableau
import transcript_store

RACINE = Path(__file__).resolve().parent.parent
PARIS = tableau.PARIS
ARBRE_BOT = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
JOUR = 86400
FONDATEUR = 781205382923288593


def _fonction_bot(nom):
    return next(n for n in ARBRE_BOT.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


class _Espion:
    """Une connexion qui note chaque requête (pour en lire le plan)."""

    def __init__(self, db, notes):
        self._db, self._notes = db, notes

    def execute(self, sql, *a, **k):
        self._notes.append((sql, tuple(a[0]) if a else ()))
        return self._db.execute(sql, *a, **k)

    def __getattr__(self, nom):
        return getattr(self._db, nom)


def _base_espionnee(chemin, notes):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield _Espion(db, notes)
        finally:
            await db.close()
    return get_db


def _plan(chemin, sql, args=()) -> str:
    with contextlib.closing(sqlite3.connect(chemin)) as c:
        return " | ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, tuple(args)))


def _paris(*a) -> int:
    return int(datetime(*a, tzinfo=PARIS).timestamp())


def _sqlite(t) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _jour_paris(t) -> str:
    return datetime.fromtimestamp(int(t), PARIS).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════════════════════
#  LV1 — l'horodatage rapide
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV1_unix_rapide_meme_verdict_que_strptime():
    def ancien(texte):
        try:
            d = datetime.strptime(str(texte)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
        return None if d.year <= 2020 else int(d.timestamp())
    h = random.Random(26102026)
    alphabet = "0123456789-: T+Z.²٣ a２"
    cas = ["2026-10-19 14:05:00", "2020-12-31 23:59:59", "2021-01-01 00:00:00", "2026-02-29 10:00:00",
           "2028-02-29 10:00:00", "2026-10-19  1:05:00", "2026-10-19 14:05:60", "2026-10-19 24:00:00",
           "2026-10-19T14:05:00", "2026-10-19 14:05:00.123", "2026-10-19 14:05", "", None, 0, "0000-01-01 00:00:00",
           "２０２６-10-19 14:05:00", "2026-1-19 14:05:00", "2026-10-19 4:05:00"]
    for _ in range(60000):
        base = list("2026-10-19 14:05:00")
        for _k in range(h.randint(0, 3)):
            base[h.randrange(len(base))] = h.choice(alphabet)
        cas.append("".join(base))
    ecarts = [c for c in cas if recrutements._unix(c) != ancien(c)]
    assert not ecarts, ecarts[:5]
    assert recrutements._unix("2026-10-19 14:05:00") == int(datetime(2026, 10, 19, 14, 5, tzinfo=timezone.utc).timestamp())


# ═══════════════════════════════════════════════════════════════════════════════
#  LV2 — le journal : le bruit a sa limite, le reste garde ses 90 jours
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV2_journal_le_bruit_a_sa_limite_le_reste_garde_ses_90_jours(tmp_path):
    chemin = tmp_path / "r.db"
    registre.setup(get_db=_base(chemin), log=lambda *a: None)
    asyncio.run(registre.init_db())
    t = 1_793_000_000
    ins = "INSERT INTO registre (guild_id, quand, categorie, type, texte) VALUES (1, ?, ?, 'x', 'x')"
    with contextlib.closing(sqlite3.connect(chemin)) as c:
        c.executemany(ins, [(t - 31 * JOUR, "Messages"), (t - 60 * JOUR, "Modération"), (t - 91 * JOUR, "Modération")])
        bruit = registre.PLAFOND_BRUIT + 50
        c.executemany(ins, ((t - 3600 + k % 600, "Messages" if k % 2 else "Vocal") for k in range(bruit)))
        c.executemany(ins, ((t - 10 * JOUR, "Modération") for _ in range(10)))
        c.commit()
        premier_bruit = c.execute("SELECT MIN(id) FROM registre WHERE quand > ?", (t - 2 * JOUR,)).fetchone()[0]
        asyncio.run(registre.purger(t))
        compte = dict(c.execute("SELECT categorie IN ('Messages', 'Vocal'), COUNT(*) FROM registre GROUP BY 1").fetchall())
        assert compte[1] == registre.PLAFOND_BRUIT, "le bruit garde ses 100 000 lignes les plus récentes"
        assert compte[0] == 11, "les sanctions de 10 et 60 jours restent (celle de 91 jours part, le message de 31 aussi)"
        assert c.execute("SELECT MIN(id) FROM registre WHERE categorie IN ('Messages', 'Vocal')").fetchone()[0] \
            == premier_bruit + 50, "les plus anciennes du bruit partent d'abord"
        #  Le filet : PLAFOND lignes au plus en tout, les plus anciennes d'abord, quelle que soit leur catégorie.
        c.executemany(ins, ((t - 60, "Sécurité") for _ in range(registre.PLAFOND - registre.PLAFOND_BRUIT + 9)))
        c.commit()
        asyncio.run(registre.purger(t))
        total, bruit_reste, moderation = c.execute(
            "SELECT COUNT(*), SUM(categorie IN ('Messages', 'Vocal')), SUM(categorie='Modération') FROM registre").fetchone()
    assert total == registre.PLAFOND
    assert (bruit_reste, moderation) == (registre.PLAFOND_BRUIT - 19, 10), "les 20 plus anciennes : la sanction de 60 jours et 19 du bruit"


# ═══════════════════════════════════════════════════════════════════════════════
#  LV3 — lire le journal, le comptage par jour
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV3_lire_le_serveur_seul_a_rebours_et_le_comptage_par_jour_garde(tmp_path, monkeypatch):
    chemin, notes = tmp_path / "r.db", []
    get_db = _base_espionnee(chemin, notes)
    registre.setup(get_db=get_db, log=lambda *a: None)
    asyncio.run(registre.init_db())
    t = 1_793_000_000
    with contextlib.closing(sqlite3.connect(chemin)) as c:
        c.executemany("INSERT INTO registre (guild_id, quand, categorie, type, texte, membre_id, auteur_id)"
                      " VALUES (?,?,?,?,?,?,?)",
                      [(1 + (k % 7 == 0), t - k * 60, ("Messages", "Modération", "Sécurité")[k % 3], "x", f"e{k}", k % 50,
                        k % 13) for k in range(5000)])
        c.commit()
        c.execute("ANALYZE")
        attendus = [r[0] for r in c.execute("SELECT id FROM registre WHERE guild_id=1 ORDER BY id DESC LIMIT 50")]
    notes.clear()
    lus = asyncio.run(registre.lire(1, 50))
    sql, args = next(x for x in reversed(notes) if "FROM registre" in x[0])
    assert "+guild_id" in sql and "TEMP B-TREE" not in _plan(chemin, sql, args), "lu à rebours, arrêté à la limite"
    assert [e["id"] for e in lus] == attendus
    notes.clear()
    lus = asyncio.run(registre.lire(1, 30, membre_id=7))
    assert "+guild_id" not in next(x for x in reversed(notes) if "FROM registre" in x[0])[0]
    assert lus and all(7 in (e["membre_id"], e["auteur_id"]) for e in lus)
    #  Le comptage jour par jour : gardé PAR_JOUR_FRAIS secondes, rendu en copie, relu pour une date donnée, oublié au setup.
    appels = []

    async def lu(guild_id, jours, fuseau, maintenant):
        appels.append(maintenant)
        return {"2026-10-20": {"Messages": 1}}
    monkeypatch.setattr(registre, "_par_jour_lu", lu)
    a = asyncio.run(registre.par_jour(1, 30, PARIS))
    a["2026-10-20"]["Messages"] = 99
    b = asyncio.run(registre.par_jour(1, 30, PARIS))
    assert b == {"2026-10-20": {"Messages": 1}} and len(appels) == 1, "gardé, et la page ne touche pas la mémoire"
    asyncio.run(registre.par_jour(1, 30, PARIS, maintenant=t))
    assert len(appels) == 2, "une date donnée : relu"
    registre.setup(get_db=get_db, log=lambda *a: None)
    asyncio.run(registre.par_jour(1, 30, PARIS))
    assert len(appels) == 3, "setup : oublié"


# ═══════════════════════════════════════════════════════════════════════════════
#  LV4 — les « Vu » des annonces, les idées
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV4_vues_des_annonces_et_idees_les_memes_chiffres(tmp_path, monkeypatch):
    chemin = tmp_path / "a.db"
    get_db = _base(chemin)
    h = random.Random(4)
    vus = {1: [], 2: list(range(100, 105)), 3: sorted(h.sample(range(1000, 9000), 300))}
    with contextlib.closing(sqlite3.connect(chemin)) as c:
        c.execute("CREATE TABLE annonces_vues (annonce_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
                  " quand INTEGER NOT NULL, PRIMARY KEY (annonce_id, membre_id))")
        for a, l in vus.items():
            c.executemany("INSERT INTO annonces_vues VALUES (?,?,?)", [(a, m, 1_790_000_000 + k) for k, m in enumerate(l)])
        c.commit()
    monkeypatch.setattr(annonces, "_get_db", get_db)
    r = asyncio.run(annonces.resume_vues([1, 2, 3, 4], 40))
    assert r[1] == (0, []) and r[4] == (0, [])
    assert r[2][0] == 5 and sorted(r[2][1]) == vus[2]
    assert r[3][0] == 300 and len(r[3][1]) == 40 and set(r[3][1]) <= set(vus[3]), "le compte entier, 40 noms"
    assert asyncio.run(annonces.resume_vues([], 40)) == {}
    assert tableau.VUS_NOMMES == 40, "autant de noms qu'avant"

    async def cfg(_g):
        return {}

    async def db_set(*_a):
        return None
    suggestions.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None, salon_logs=None,
                      log=lambda *a: None)
    asyncio.run(suggestions.init_db())
    with contextlib.closing(sqlite3.connect(chemin)) as c:
        for k in range(95):
            c.execute("INSERT INTO suggestions_v2 (guild_id, channel_id, auteur_id, titre, cree_le) VALUES (?,?,?,?,?)",
                      (1 if k % 19 else 2, 5, 70 + k % 4, f"Idée {k}", _sqlite(1_790_000_000 + k)))
        ids = [r[0] for r in c.execute("SELECT id FROM suggestions_v2")]
        c.executemany("INSERT OR IGNORE INTO suggestions_votes VALUES (?,?,?)",
                      [(h.choice(ids), h.randint(1, 400), h.choice((1, -1))) for _ in range(1500)])
        c.commit()

        def attendu(auteur=0):
            f = "AND auteur_id=? " if auteur else ""
            rows = c.execute("SELECT id FROM suggestions_v2 WHERE guild_id=1 " + f + "ORDER BY id DESC LIMIT 60",
                             (auteur,) if auteur else ()).fetchall()
            return [(i, *c.execute("SELECT COALESCE(SUM(vote=1), 0), COALESCE(SUM(vote=-1), 0) FROM suggestions_votes"
                                   " WHERE suggestion_id=?", (i,)).fetchone()) for (i,) in rows]
        for auteur in (0, 71):
            res = asyncio.run(suggestions.lister(1, 60, auteur))
            assert [(x["id"], x["pour"], x["contre"]) for x in res["liste"]] == attendu(auteur)


# ═══════════════════════════════════════════════════════════════════════════════
#  LV5 — les doubles comptes
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV5_doubles_comptes_le_tri_ne_perd_aucune_ressemblance():
    ns = {"re": re}
    for nom in ("normalize_username", "levenshtein_distance", "username_similarity", "_nom_peut_ressembler"):
        exec(compile(ast.Module([_fonction_bot(nom)], []), "bot.py", "exec"), ns)  # noqa: S102 — code du dépôt
    sim, tri, norm = ns["username_similarity"], ns["_nom_peut_ressembler"], ns["normalize_username"]
    h = random.Random(85)
    lettres = "abcdefghijklmnopqrstuvwxyz0123456789_.-@$ABCXYZ"

    def au_hasard():
        return "".join(h.choice(lettres) for _ in range(h.randint(1, 32)))

    def voisin(n):
        l = list(n)
        for _ in range(h.randint(0, 4)):
            i = h.randrange(len(l) + 1)
            op = h.randrange(3)
            if op == 0 or not l:
                l.insert(i, h.choice(lettres))
            elif op == 1:
                del l[min(i, len(l) - 1)]
            else:
                l[min(i, len(l) - 1)] = h.choice(lettres)
        return "".join(l) or "a"
    paires = []
    for _ in range(5000):
        a = au_hasard()
        paires += [(a, au_hasard()), (a, voisin(a)), (a, norm(voisin(a)))]   # l'empreinte garde le nom normalisé
    proches = ecartes = 0
    for a, b in paires:
        s = sim(a, b)
        if s >= 85:
            proches += 1
            assert tri(a, b), (a, b, s)
        elif not tri(a, b):
            ecartes += 1
    assert proches > 1000, "assez de noms très proches dans le tirage"
    assert ecartes > len(paires) // 3, "et le tri écarte vraiment la plupart des autres"
    src = ast.unparse(_fonction_bot("detect_alt_account"))
    boucle = src[src.index("for existing_id, existing_norm in existing_users"):]
    i_sim = boucle.index("username_similarity(new_member.name, existing_norm)")
    assert boucle.index("guild.get_member(existing_id)") < i_sim and boucle.index("_nom_peut_ressembler(") < i_sim, \
        "les partis et les noms trop différents ne coûtent plus la distance complète"


# ═══════════════════════════════════════════════════════════════════════════════
#  LV6 — le compactage
# ═══════════════════════════════════════════════════════════════════════════════

def _remplir_puis_vider(chemin):
    with contextlib.closing(sqlite3.connect(chemin)) as c:
        c.execute("CREATE TABLE IF NOT EXISTS t (x BLOB)")
        c.executemany("INSERT INTO t VALUES (randomblob(16000))", [()] * 400)
        c.commit()
        c.execute("DELETE FROM t")
        c.commit()


def test_LV6_compactage_heures_creuses_place_pages_rendues_une_fois_par_nuit(tmp_path, monkeypatch):
    chemin = tmp_path / "c.db"
    get_db = _base(chemin)
    journal = []
    compactage.setup(log=journal.append)
    monkeypatch.setattr(compactage, "PAUSE_S", 0)
    monkeypatch.setattr(compactage, "_etat", {"dernier": 0, "nuit": "", "rendues": 0, "conversion": 0, "refus": "",
                                              "erreur": ""})
    _remplir_puis_vider(chemin)
    jour, nuit = _paris(2026, 11, 3, 15, 0), _paris(2026, 11, 4, 4, 0)
    avant = asyncio.run(compactage.etat(get_db))
    assert avant["mode"] == 0 and avant["part_libre"] > 0.5
    assert asyncio.run(compactage.passer(get_db, chemin, jour))["refus"] == "heures creuses"
    assert asyncio.run(compactage.etat(get_db))["mode"] == 0, "jamais de VACUUM complet en journée"
    vraie_place = compactage._place
    monkeypatch.setattr(compactage, "_place", lambda _c: 1024)
    assert asyncio.run(compactage.passer(get_db, chemin, nuit))["refus"].startswith("place insuffisante")
    assert "[COMPACTAGE][E1] place insuffisante pour la conversion" in journal and asyncio.run(compactage.etat(get_db))["mode"] == 0
    monkeypatch.setattr(compactage, "_place", vraie_place)
    r = asyncio.run(compactage.passer(get_db, chemin, nuit))
    apres = asyncio.run(compactage.etat(get_db))
    assert r["converti"] and apres["mode"] == compactage.INCREMENTAL and apres["libres"] == 0
    assert apres["octets"] < avant["octets"] / 4 and os.path.getsize(chemin) < avant["octets"] / 4
    #  Une nuit ordinaire : TOUTES les pages libres rendues (par `execute`, SQLite n'en rendait qu'une par appel).
    _remplir_puis_vider(chemin)
    libres = asyncio.run(compactage.etat(get_db))["libres"] // 4096
    assert libres > 1000
    r = asyncio.run(compactage.passer(get_db, chemin, nuit + 60))
    assert r["rendues"] == libres and asyncio.run(compactage.etat(get_db))["libres"] == 0
    #  Une fois par nuit, aux heures creuses.
    _remplir_puis_vider(chemin)
    assert asyncio.run(compactage.si_heure_creuse(get_db, chemin, jour)) is None
    assert asyncio.run(compactage.si_heure_creuse(get_db, chemin, nuit + 3600))["rendues"] > 1000
    assert "[COMPACTAGE] base compactée" in journal
    _remplir_puis_vider(chemin)
    assert asyncio.run(compactage.si_heure_creuse(get_db, chemin, nuit + 5400)) is None, "déjà passé cette nuit"
    assert asyncio.run(compactage.si_heure_creuse(get_db, chemin, _paris(2026, 11, 5, 3, 10)))["rendues"] > 1000
    #  Le grand nettoyage de la semaine : l'incrémental dès que la base y est passée, plus de VACUUM complet.
    vus = []

    async def passer(gdb, chemin_=None, maintenant=None, forcer=False):
        vus.append(forcer)
        return {}
    monkeypatch.setattr(compactage, "passer", passer)
    monkeypatch.setattr(data_cleanup, "_get_db", get_db)
    assert asyncio.run(data_cleanup.vacuum_db()) is True and vus == [True]
    autre = tmp_path / "d.db"
    _remplir_puis_vider(autre)
    monkeypatch.setattr(data_cleanup, "_get_db", _base(autre))
    assert asyncio.run(data_cleanup.vacuum_db()) is True and vus == [True], "une base pas encore convertie : VACUUM"
    assert os.path.getsize(autre) < 100_000


# ═══════════════════════════════════════════════════════════════════════════════
#  LV7 — la mémoire du site
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV7_memoire_bornee_et_empreinte_une_fois_par_version(monkeypatch):
    t = 1_793_000_000.0
    for nom in ("_sessions", "_cadence", "_requetes", "_requetes_medias", "_graves", "_empreintes_donnees"):
        monkeypatch.setattr(tableau, nom, {})
    n = tableau.MEMOIRE_MAX
    tableau._sessions.update({f"p{k}": (1, 2, t - 1) for k in range(n)} | {f"v{k}": (1, 2, t + 600) for k in range(5)})
    tableau._cadence.update({("site", k): [t - 120] for k in range(n)} | {("site", -1): [t - 5]})
    tableau._requetes.update({k: [t - 61] for k in range(n)} | {-1: [t - 1]})
    tableau._graves.update({k: [t - 700] for k in range(n)} | {-1: [t - 100]})
    tableau._elaguer(t)
    assert set(tableau._sessions) == {f"v{k}" for k in range(5)}, "les sessions expirées partent, les vivantes restent"
    assert list(tableau._cadence) == [("site", -1)] and list(tableau._requetes) == [-1] and list(tableau._graves) == [-1]
    peu = {k: [t - 999] for k in range(10)}
    tableau._cadence.update(peu)
    tableau._elaguer(t)
    assert len(tableau._cadence) == 11, "sous MEMOIRE_MAX : rien n'est parcouru"
    d = {"a": 1, "genere": 5}
    e1 = tableau._empreinte_donnees(("k", "tout"), d)
    assert tableau._empreinte_donnees(("k", "tout"), dict(d, genere=6)) == e1, "l'heure de génération ne compte pas"
    d2 = {"a": 1, "genere": 7}
    e2 = tableau._empreinte_donnees(("k", "tout"), d2)
    d2["a"] = 2
    assert tableau._empreinte_donnees(("k", "tout"), d2) == e2, "le même objet : l'empreinte n'est pas recalculée"
    assert tableau._empreinte_donnees(("k", "tout"), {"a": 2}) != e2


# ═══════════════════════════════════════════════════════════════════════════════
#  Le vrai site local, construit une fois pour ce fichier
# ═══════════════════════════════════════════════════════════════════════════════

class Local:
    def __init__(self, boucle, client, ctx):
        self.boucle, self.client, self.ctx = boucle, client, ctx
        self.cookie = None
        self.chemin = ctx.dossier / "site_local.db"

    def faire(self, coro):
        return self.boucle.run_until_complete(coro)

    async def _session(self):
        if self.cookie is None:
            r = await self.client.get("/tableau/demo", allow_redirects=False)
            self.cookie = {"Cookie": f"{tableau.COOKIE}={r.cookies[tableau.COOKIE].value}"}
        return self.cookie

    def get(self, chemin, **params):
        async def f():
            r = await self.client.get(chemin, params=params or None, headers=await self._session())
            return r.status, await r.json()
        return self.faire(f())

    def api(self, nom, **params):
        return self.get("/tableau/espace/api/" + nom, **params)

    def post(self, chemin, corps):
        async def f():
            h = dict(await self._session(), **{"X-Tableau": "1", "Origin": "http://localhost:8790"})
            r = await self.client.post(chemin, json=corps, headers=h)
            return r.status, await r.json()
        return self.faire(f())

    def donnees(self):
        tableau._cache.clear()
        return self.get("/tableau/espace/donnees")[1]

    def sql(self, requete, args=()):
        with contextlib.closing(sqlite3.connect(self.chemin, timeout=30)) as c:
            cur = c.execute(requete, args)
            rows = cur.fetchall()
            c.commit()
            return rows

    def sql_plusieurs(self, requete, lignes):
        with contextlib.closing(sqlite3.connect(self.chemin, timeout=30)) as c:
            c.executemany(requete, lignes)
            c.commit()


@pytest.fixture(scope="module")
def local(tmp_path_factory):
    import paths
    mp = pytest.MonkeyPatch()
    mp.setattr(tableau, "ROUTES", {})
    mp.setattr(tableau, "REGLES", dict(tableau.REGLES))
    mp.setattr(tableau, "_SOURCES_MEDIAS", [])
    mp.setattr(tableau, "RACINE_DONNEES", None)
    mp.setattr(tableau, "ETAT_STOCKAGE", tableau.ETAT_STOCKAGE)
    mp.setattr(transcript_store, "_BASE_DIR", transcript_store._BASE_DIR)
    mp.setattr(paths, "_RESOLVED_BASE", paths._RESOLVED_BASE)
    mp.syspath_prepend(str(RACINE / "outils"))
    import site_local
    from aiohttp.test_utils import TestClient, TestServer
    boucle = asyncio.new_event_loop()

    async def demarrer():
        app, ctx = await site_local.construire(tmp_path_factory.mktemp("longevite") / "local", 8790)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client, ctx
    client, ctx = boucle.run_until_complete(demarrer())
    try:
        import banc_annees   # les tables que bot.py crée lui-même (empreintes, invitations, audit…), avec leurs index
        b = banc_annees.Base(ctx.dossier / "site_local.db")
        banc_annees._tables_du_bot(b)
        b.fin()
        yield Local(boucle, client, ctx)
    finally:
        boucle.run_until_complete(client.close())
        boucle.close()
        mp.undo()
        for nom in ("site_local", "site_local_port", "banc_annees"):
            sys.modules.pop(nom, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  LV8 — api/journal
# ═══════════════════════════════════════════════════════════════════════════════

def _banc_journal(local) -> list:
    """600 évènements « Banc » sur trois jours, et autour du changement d'heure du 25/10/2026 ; une seule fois."""
    deja = local.sql("SELECT id, quand, gravite, membre_id, texte FROM registre WHERE categorie='Banc' ORDER BY id")
    if deja:
        return deja
    lignes = []
    for k in range(600):
        quand = _paris(2026, 10, 20, 8, 0) + k * 431
        lignes.append((1, quand, "Banc", "banc.x", (0, 1001, 1002)[k % 3], 0, 0,
                       f"Évènement {k}" + (" motclé" if k % 7 == 0 else ""), "", k % 4))
    for t in (_paris(2026, 10, 24, 23, 59, 30), _paris(2026, 10, 25, 0, 0, 10), _paris(2026, 10, 25, 1, 30),
              _paris(2026, 10, 25, 4, 0), _paris(2026, 10, 25, 23, 59), _paris(2026, 10, 26, 0, 0, 30)):
        lignes.append((1, t, "Banc", "banc.dst", 0, 0, 0, "Autour du changement d'heure", "", 0))
    lignes += [(1, _paris(2026, 10, 21, 12, 0), "Banc", "banc.p", 0, 0, 0, "Remise de 50% sur le port", "", 0),
               (1, _paris(2026, 10, 21, 12, 1), "Banc", "banc.p", 0, 0, 0, "Remise de 50x sur le port", "", 0)]
    local.sql_plusieurs("INSERT INTO registre (guild_id, quand, categorie, type, membre_id, auteur_id, salon_id, texte,"
                        " detail, gravite) VALUES (?,?,?,?,?,?,?,?,?,?)", lignes)
    return local.sql("SELECT id, quand, gravite, membre_id, texte FROM registre WHERE categorie='Banc' ORDER BY id")


def test_LV8_journal_pages_filtres_comptes_et_jours_de_paris(local):
    rangs = _banc_journal(local)
    total = len(rangs)
    #  Les pages : sans trou ni doublon, du plus récent au plus ancien.
    vus, avant = [], None
    while True:
        st, r = local.api("journal", cat="Banc", n="200", **({"avant": avant} if avant else {}))
        assert st == 200 and r["total"] == total
        vus += [(e["quand"], e["id"]) for e in r["evenements"]]
        avant = r["suite"]
        if not avant:
            break
    assert vus == sorted(((q, i) for i, q, *_ in rangs), reverse=True) and len(set(vus)) == total
    #  Les comptes : par catégorie (le même filtre sans la catégorie : les autres puces) et par jour de Paris.
    st, r = local.api("journal", cat="Banc", n="5", comptes="1")
    assert r["par_categorie"]["Banc"] == total and len(r["par_categorie"]) > 1
    par_jour = {}
    for _i, q, *_ in rangs:
        par_jour[_jour_paris(q)] = par_jour.get(_jour_paris(q), 0) + 1
    assert r["par_jour"] == par_jour and sum(r["par_jour"].values()) == total
    #  Des jours entiers de Paris, le jour de 25 heures compris.
    for du, au in (("2026-10-25", "2026-10-25"), ("2026-10-24", "2026-10-24"), ("2026-10-24", "2026-10-26")):
        st, r = local.api("journal", cat="Banc", du=du, au=au, n="500")
        attendus = sorted(i for i, q, *_ in rangs if du <= _jour_paris(q) <= au)
        assert st == 200 and sorted(e["id"] for e in r["evenements"]) == attendus and r["total"] == len(attendus), (du, au)
    assert len([1 for _i, q, *_ in rangs if _jour_paris(q) == "2026-10-25"]) == 4
    #  Gravité, recherche (texte, nom d'un membre, caractères spéciaux), résumé.
    st, r = local.api("journal", cat="Banc", gravite="2", n="500")
    assert r["total"] == sum(1 for x in rangs if x[2] >= 2) and all(e["gravite"] >= 2 for e in r["evenements"])
    st, r = local.api("journal", cat="Banc", q="motclé", n="500")
    assert r["total"] == sum(1 for x in rangs if "motclé" in x[4])
    st, r = local.api("journal", cat="Banc", q="50%", n="500")
    assert [e["texte"] for e in r["evenements"]] == ["Remise de 50% sur le port"], "« % » cherché tel quel"
    mira = [m.id for m in local.ctx.guild.members if "mira" in m.display_name.casefold() or "mira" in m.name.casefold()]
    st, r = local.api("journal", cat="Banc", q="Mira", n="500")
    assert 1001 in mira and r["total"] == sum(1 for x in rangs if x[3] in mira or "mira" in x[4].casefold())
    st, r = local.api("journal", cat="Banc", n="1", resume="1")
    assert r["graves"] == sum(1 for x in rangs if x[2] >= 2)
    assert r["personnes_n"] == len({x[3] for x in rangs if x[3] > 0})
    for params in ({"n": "abc"}, {"avant": "12"}, {"avant": "1:x"}, {"du": "2026-13-01"}, {"depuis": "-5"}):
        st, r = local.api("journal", **params)
        assert st == 400 and r["erreur"], params


# ═══════════════════════════════════════════════════════════════════════════════
#  LV9 — les tickets fermés
# ═══════════════════════════════════════════════════════════════════════════════

def _banc_tickets(local) -> dict:
    """Des tickets fermés en juillet et août 2026 (mois de Paris : un à la frontière), deux ouverts."""
    if local.sql("SELECT 1 FROM tickets WHERE id=50001"):
        return local.banc_tickets
    fermes = {}
    tickets, evts = [], []
    for k in range(20):
        tid = 50001 + k
        fin = _paris(2026, 7, 3, 10) + k * 2 * JOUR if k < 12 else _paris(2026, 8, 2, 10) + (k - 12) * 2 * JOUR
        if k == 11:
            fin = int(datetime(2026, 7, 31, 22, 30, tzinfo=timezone.utc).timestamp())   # 1er août, 0 h 30 à Paris
        tickets.append((tid, 1, 960000 + tid, 1001 if k % 2 else 1002, "p2", 0, "closed", "{}", _sqlite(fin - 3 * 3600)))
        evts.append((1, tid, "close", FONDATEUR, "", fin))
        fermes[tid] = fin
    for k in range(2):
        tid = 50101 + k
        tickets.append((tid, 1, 960000 + tid, 1001, "p2", 0, "open", "{}", _sqlite(time.time() - 3600)))
    local.sql_plusieurs("INSERT INTO tickets (id, guild_id, channel_id, user_id, panel_id, claimed_by, status, answers,"
                        " created_at) VALUES (?,?,?,?,?,?,?,?,?)", tickets)
    local.sql_plusieurs("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, detail, created_unix)"
                        " VALUES (?,?,?,?,?,?)", evts)
    local.banc_tickets = fermes
    return fermes


def test_LV9_tickets_fermes_par_mois_date_recherche_et_donnees_bornees(local, monkeypatch):
    fermes = _banc_tickets(local)
    juillet = {t for t, f in fermes.items() if datetime.fromtimestamp(f, PARIS).month == 7}
    aout = set(fermes) - juillet
    assert 50012 in aout and len(juillet) == 11, "le ticket fermé le 31/07 à 22 h 30 UTC est d'août, à Paris"
    st, r = local.api("tickets/fermes", mois="2026-08")
    assert st == 200 and {x["ticket"] for x in r["fermes"]} >= aout and not {x["ticket"] for x in r["fermes"]} & juillet
    st, r = local.api("tickets/fermes", mois="2026-07")
    assert {x["ticket"] for x in r["fermes"]} >= juillet and not {x["ticket"] for x in r["fermes"]} & aout
    assert [x["ferme"] for x in r["fermes"]] == sorted((x["ferme"] for x in r["fermes"]), reverse=True)
    borne = fermes[50015]
    st, r = local.api("tickets/fermes", depuis=str(borne))
    assert all(x["ferme"] >= borne for x in r["fermes"]) and {50015, 50016} <= {x["ticket"] for x in r["fermes"]}
    st, r = local.api("tickets/fermes", q="#50007")
    assert 50007 in {x["ticket"] for x in r["fermes"]} and not {50101, 50102} & {x["ticket"] for x in r["fermes"]}
    for params in ({}, {"mois": "2026-7"}, {"depuis": "x"}):
        assert local.api("tickets/fermes", **params)[0] == 400, params
    #  Les données : FERMES_MAX au plus (les plus récents), le total et les mois exacts.
    monkeypatch.setattr(tableau, "FERMES_MAX", 5)
    tk = local.donnees()["tickets"]
    n_fermes = local.sql("SELECT COUNT(*) FROM tickets WHERE guild_id=1 AND status!='open'")[0][0]
    assert len(tk["fermes"]) == 5 and tk["fermes_total"] == n_fermes > 5
    assert sum(x["n"] for x in tk["fermes_mois"]) == n_fermes
    mois = {}
    for x in tk["fermes_mois"]:
        mois[x["mois"]] = mois.get(x["mois"], 0) + x["n"]
    assert mois.get("2026-07", 0) >= 11 and mois.get("2026-08", 0) >= 9
    tous = local.api("tickets/fermes", depuis="1")[1]["fermes"]
    assert [x["ticket"] for x in tk["fermes"]] == [x["ticket"] for x in tous[:5]], "les plus récents"


# ═══════════════════════════════════════════════════════════════════════════════
#  LV10 — le casier
# ═══════════════════════════════════════════════════════════════════════════════

def _banc_casier(local) -> list:
    if local.sql("SELECT 1 FROM infractions WHERE user_id BETWEEN 7000001 AND 7000099 LIMIT 1"):
        return local.sql("SELECT id, user_id FROM infractions WHERE user_id BETWEEN 7000001 AND 7000099")
    maintenant = time.time()
    lignes = []
    h = random.Random(10)
    for k in range(30):
        uid = 7_000_001 + k
        for j in range(1 + k % 3):
            age = h.randint(2, 360) * JOUR + h.randint(0, 80000)
            typ, mod = h.choice((("warn", 1002), ("mute", 1002), ("badword", 999), ("spam", 999), ("kick", 1004)))
            lignes.append((1, uid, mod, typ, f"Motif {k}-{j}" + (" pirate-unique" if k == 17 else ""), "", _sqlite(maintenant - age)))
    #  La fin du mois dernier : 23 h 30 UTC, c'est déjà ce mois-ci à Paris (été comme hiver) ; 21 h 30 UTC, encore l'autre.
    dernier = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    for heure in (23, 21):
        lignes.append((1, 7_000_031, 1002, "warn", "Fin de mois", "", dernier.replace(hour=heure, minute=30).strftime("%Y-%m-%d %H:%M:%S")))
    local.sql_plusieurs("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", lignes)
    return local.sql("SELECT id, user_id FROM infractions WHERE user_id BETWEEN 7000001 AND 7000099")


def test_LV10_casier_cases_bornees_total_exact_suite_et_chiffres_au_dela_de_la_lecture(local, monkeypatch):
    _banc_casier(local)
    monkeypatch.setattr(tableau, "MEMBRES_CASIER", 5)
    s = local.donnees()["sanctions"]
    apart = tableau.a_part(local.ctx.guild, local.ctx.conf)
    attendu = len({u for (u,) in local.sql("SELECT DISTINCT user_id FROM infractions WHERE guild_id=1 AND user_id > 0")
                   if u not in apart})
    assert len(s["membres"]) == 5 and s["membres_total"] == attendu
    st, tout = local.api("casier/membres", n="500")
    assert st == 200 and tout["total"] == attendu and tout["suite"] is None
    assert [m["id"] for m in tout["membres"][:5]] == [m["id"] for m in s["membres"]], "la suite continue la même liste"
    st, page = local.api("casier/membres", apres="5", n="5")
    assert [m["id"] for m in page["membres"]] == [m["id"] for m in tout["membres"][5:10]] and page["suite"] == 10
    st, r = local.api("casier/membres", q="pirate-unique")
    assert [m["id"] for m in r["membres"]] == ["7000018"]
    #  Au-delà de CASIER_LUES entrées : les mêmes chiffres qu'une lecture complète, mois de Paris compris.
    def chiffres(d):
        x = d["sanctions"]
        return ({k: x[k] for k in ("total", "trente_jours", "auto", "manuel", "mois")},
                {t["type"]: t["n"] for t in x["types"]}, {p["id"]: (p["total"], p["types"]) for p in x["staff"]},
                d["equipe"])   # les sanctions de 30 jours de chacun (le staff30 du casier) vont dans « l'équipe »
    monkeypatch.setattr(tableau, "CASIER_LUES", 10 ** 6)
    complet = chiffres(local.donnees())
    monkeypatch.setattr(tableau, "CASIER_LUES", 10)
    groupe = chiffres(local.donnees())
    assert groupe == complet
    ce_mois = datetime.now(PARIS).strftime("%Y-%m")
    assert complet[0]["mois"].get(ce_mois, {}).get("Avertissements", 0) >= 1, "23 h 30 UTC le dernier jour : ce mois-ci à Paris"


# ═══════════════════════════════════════════════════════════════════════════════
#  LV11 — la rubrique Nettoyage
# ═══════════════════════════════════════════════════════════════════════════════

NOUVELLES = {"tickets_fermes", "questions", "casier_detections", "casier_sanctions", "actualites", "portraits", "sondages",
             "idees", "entraide", "empreintes", "invitations", "audit_staff", "orphelins", "candidatures", "equipes_partis"}


def test_LV11_nettoyage_regles_rangees_apercu_lancer_une_regle_et_place_prise(local):
    st, n = local.api("nettoyage")
    assert st == 200
    regles = {r["cle"]: r for r in n["regles"]}
    assert NOUVELLES <= set(regles), NOUVELLES - set(regles)
    assert all(isinstance(r["ordre"], int) for r in n["regles"])
    assert [r["ordre"] for r in n["regles"]] == sorted(r["ordre"] for r in n["regles"])
    assert all(isinstance(n["partiront"].get(k), int) for k in NOUVELLES if regles[k]["auto"]), n["partiront"]
    st_ = n["stockage"]
    assert st_["base"] > 0 and set(st_["dossiers"]) == {"transcripts", "images", "portraits", "copies"}
    assert st_["volume"]["total"] and st_["volume"]["libre"] is not None
    #  Les durées que le bot tenait cachées sont les plafonds (jamais plus tard que lui) ; ce qui n'en avait pas : prudent.
    plafonds = {"journal_messages": registre.JOURS_COURTS, "journal": registre.JOURS,
                "transcripts": transcript_store._RETENTION_DAYS, "questions": questions.JOURS,
                "sondages": next(j for t, _c, j in data_cleanup.CLEANUP_RULES if t == "sondages"),
                "tickets_fermes": next(j for nom, _s, j, _f in data_cleanup.PURGES_CIBLEES if nom == "tickets fermés"),
                "casier_detections": next(j for nom, _s, j, _f in data_cleanup.PURGES_CIBLEES if nom == "casier : détections"),
                "casier_sanctions": next(j for nom, _s, j, _f in data_cleanup.PURGES_CIBLEES if nom == "casier : sanctions"),
                "candidatures": gdpr.RETENTION["recrutements"][1]}
    for cle, jours in plafonds.items():
        assert regles[cle]["max"] == jours and regles[cle]["defaut"] == jours, (cle, regles[cle], jours)
    assert gdpr.RETENTION["questions"][1] == questions.JOURS
    #  L'aperçu d'une autre durée ; les demandes invalides.
    assert local.api("nettoyage/apercu", cle="inconnue", jours="10")[0] == 404
    assert local.api("nettoyage/apercu", cle="journal", jours="5")[0] == 400
    st, r = local.api("nettoyage/apercu", cle="journal", jours="30")
    assert st == 200 and isinstance(r["partiront"], int)
    #  « Nettoyer maintenant » d'une règle : elle seule, notée au journal ; une fois par minute.
    st, r = local.post("/tableau/espace/api/nettoyage/lancer", {"cle": "questions"})
    assert st == 200 and set(r["retires"]) == {"questions"}
    assert local.sql("SELECT COUNT(*) FROM registre WHERE type='site.nettoyage' AND texte LIKE ?",
                     ("Nettoyage du site — Questions relevées lancé par %",))[0][0] == 1
    assert local.post("/tableau/espace/api/nettoyage/lancer", {"cle": "questions"})[0] == 429
    assert local.post("/tableau/espace/api/nettoyage/lancer", {"cle": "tickets_archives"})[0] == 404, "un rangement n'efface rien"
    assert local.post("/tableau/espace/api/nettoyage/lancer", {"cle": "inconnue"})[0] == 404


# ═══════════════════════════════════════════════════════════════════════════════
#  LV12 — chaque règle efface ce qu'elle dit, et rien d'autre
# ═══════════════════════════════════════════════════════════════════════════════

def _regle(local, cle, jours, t=None):
    r = tableau.REGLES[cle]
    t = t or time.time()
    avant = local.faire(r["apercu"](1, jours, t))
    n = local.faire(r["fn"](1, jours, t))
    return avant, n, local.faire(r["apercu"](1, jours, t))


def test_LV12_tickets_fermes_et_leurs_conversations_sauf_celle_d_une_candidature(local):
    now = time.time()
    base = transcript_store._BASE_DIR
    Path(base).mkdir(parents=True, exist_ok=True)
    jetons = {k: f"jetonBancLongevite{k}xx" for k in "ABE"}
    for k, j in jetons.items():
        Path(base, j + ".html").write_text("<html></html>", encoding="utf-8")
        Path(base, "a_" + j).mkdir(exist_ok=True)
        (Path(base, "a_" + j) / "img.webp").write_bytes(b"RIFF0000WEBP")
    vieux = now - 400 * JOUR
    local.sql_plusieurs("INSERT INTO tickets (id, guild_id, channel_id, user_id, panel_id, claimed_by, status, answers,"
                        " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        [(60001, 1, 960601, 1001, "p2", 0, "closed", "{}", _sqlite(vieux - JOUR)),
                         (60002, 1, 960602, 1002, "p1", 0, "closed", "{}", _sqlite(vieux - JOUR)),
                         (60003, 1, 960603, 1001, "p2", 0, "closed", "{}", _sqlite(now - 12 * JOUR)),
                         (60004, 1, 960604, 1001, "p2", 0, "open", "{}", _sqlite(now - 500 * JOUR)),
                         (60005, 1, 960605, 1002, "p2", 0, "closed", "{}", _sqlite(vieux))])
    local.sql_plusieurs("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, detail, created_unix)"
                        " VALUES (?,?,?,?,?,?)", [(1, 60001, "close", FONDATEUR, "", int(vieux)),
                                                  (1, 60002, "close", FONDATEUR, "", int(vieux)),
                                                  (1, 60003, "close", FONDATEUR, "", int(now - 10 * JOUR))])
    local.sql_plusieurs("INSERT INTO ticket_transcripts (guild_id, ticket_id, user_id, user_name, panel, url, closed_at,"
                        " jeton) VALUES (?,?,?,?,?,?,?,?)",
                        [(1, 60001, 1001, "Mira", "p2", f"https://x/t/{jetons['A']}", _sqlite(vieux), jetons["A"]),
                         (1, 60002, 1002, "Calico", "p1", f"https://x/t/{jetons['B']}", _sqlite(vieux), jetons["B"]),
                         (1, 60005, 1002, "Calico", "p2", f"https://x/t/{jetons['E']}", _sqlite(vieux), jetons["E"])])
    local.sql("INSERT INTO ticket_audit (guild_id, channel_id, action, actor_id, at, detail) VALUES (1, 960601, 'close', 1, ?, '')",
              (_sqlite(vieux),))
    local.sql("INSERT INTO ticket_log_msgs (guild_id, ticket_id, message_id) VALUES (1, 60001, 5)")
    local.sql("INSERT INTO ticket_extras (channel_id, priority) VALUES (960601, 'normal')")
    local.sql("INSERT INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom, ferme_le, transcript)"
              " VALUES (1, 60002, 1002, 'Calico', ?, ?)", (int(vieux), f"https://x/t/{jetons['B']}"))
    avant, n, apres = _regle(local, "tickets_fermes", 365)
    assert avant >= 3 and n >= 3 and apres == 0
    restants = {r[0] for r in local.sql("SELECT id FROM tickets WHERE id BETWEEN 60001 AND 60005")}
    assert restants == {60003, 60004}, "le fermé récent et l'ouvert restent"
    for table, col, val in (("ticket_log_events", "ticket_id", 60001), ("ticket_transcripts", "ticket_id", 60001),
                            ("ticket_audit", "channel_id", 960601), ("ticket_log_msgs", "ticket_id", 60001),
                            ("ticket_extras", "channel_id", 960601)):
        assert not local.sql(f"SELECT 1 FROM {table} WHERE {col}=?", (val,)), table
    assert not Path(base, jetons["A"] + ".html").exists() and not Path(base, "a_" + jetons["A"]).exists()
    assert not Path(base, jetons["E"] + ".html").exists()
    assert Path(base, jetons["B"] + ".html").exists(), "la conversation d'une candidature reste avec sa fiche"


def test_LV12_casier_annulable_sans_les_bannissements(local):
    import casier
    now = time.time()
    lignes = [(1, 7_100_001, 999, "badword", "Insulte", "", _sqlite(now - 400 * JOUR)),
              (1, 7_100_001, 1002, "warn", "Spam", "", _sqlite(now - 400 * JOUR)),
              (1, 7_100_002, 1002, "warn", "Flood", "", _sqlite(now - 800 * JOUR)),
              (1, 7_100_002, 1002, "ban", "Arnaque", "", _sqlite(now - 800 * JOUR)),
              (1, 7_100_003, 1002, "warn", "Hors sujet", "", _sqlite(now - 100 * JOUR))]
    local.sql_plusieurs("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration, created_at)"
                        " VALUES (?,?,?,?,?,?,?)", lignes)

    def reste():
        return sorted((u, t) for u, t in local.sql("SELECT user_id, type FROM infractions WHERE user_id BETWEEN 7100001 AND 7100003"))
    _a, n, _p = _regle(local, "casier_detections", 365)
    assert n >= 1 and (7_100_001, "badword") not in reste() and (7_100_001, "warn") in reste()
    lot = local.sql("SELECT lot FROM infractions_archive WHERE user_id=7100001 AND type='badword'")[0][0]
    assert local.sql("SELECT n FROM casier_lots WHERE lot=?", (lot,))[0][0] >= 1, "un nettoyage du casier, annulable"
    _a, n, _p = _regle(local, "casier_sanctions", 730)
    assert reste() == [(7_100_001, "warn"), (7_100_002, "ban"), (7_100_003, "warn")], "le bannissement reste"
    local.faire(casier.restaurer(1, lot, 0))
    assert (7_100_001, "badword") in reste(), "défait : l'entrée revient"


def test_LV12_salons_clan_membres_audit(local, monkeypatch):
    now = time.time()
    v = now - 400 * JOUR
    #  Les idées : décidées ou retirées depuis plus longtemps (et leurs votes) ; jamais une ouverte ni une récente.
    ids = []
    for statut, decide, retire in (("acceptee", _sqlite(v), 0), ("attente", None, 0), ("attente", None, int(v)),
                                   ("refusee", _sqlite(now - 10 * JOUR), 0)):
        local.sql("INSERT INTO suggestions_v2 (guild_id, channel_id, auteur_id, titre, cree_le, statut, decide_le, retire_le)"
                  " VALUES (1, 5, 1001, 'Idée de banc', ?, ?, ?, ?)", (_sqlite(v - JOUR), statut, decide, retire))
        ids.append(local.sql("SELECT MAX(id) FROM suggestions_v2")[0][0])
    local.sql_plusieurs("INSERT OR IGNORE INTO suggestions_votes VALUES (?,?,?)", [(ids[0], u, 1) for u in range(3)])
    _regle(local, "idees", 365)
    assert {r[0] for r in local.sql(f"SELECT id FROM suggestions_v2 WHERE id IN ({','.join(map(str, ids))})")} == {ids[1], ids[3]}
    assert not local.sql("SELECT 1 FROM suggestions_votes WHERE suggestion_id=?", (ids[0],))
    #  L'entraide : une demande close dont le fil est parti ; jamais un échange certifié, ni une demande ouverte.
    ent = []
    for statut, fil, supprime, certifie in (("terminee", 0, 1, 0), ("terminee", 0, 1, 1002), ("ouverte", 5, 0, 0),
                                            ("annulee", 55, 0, 0), ("annulee", 0, 0, 0)):
        local.sql("INSERT INTO entraide_demandes (guild_id, zone, auteur_id, titre, statut, fil_id, cree, maj, ferme,"
                  " certifie_par, supprime) VALUES (1, 'trade', 1001, 'Banc', ?, ?, ?, ?, ?, ?, ?)",
                  (statut, fil, int(v), int(v), 0 if statut == "ouverte" else int(v), certifie, supprime))
        ent.append(local.sql("SELECT MAX(id) FROM entraide_demandes")[0][0])
    local.sql("INSERT INTO entraide_notes (demande_id, message_id) VALUES (?, 1)", (ent[0],))
    _regle(local, "entraide", 365)
    assert {r[0] for r in local.sql(f"SELECT id FROM entraide_demandes WHERE id IN ({','.join(map(str, ent))})")} \
        == {ent[1], ent[2], ent[3]}, "certifiée, ouverte et fil encore là : gardées"
    assert not local.sql("SELECT 1 FROM entraide_notes WHERE demande_id=?", (ent[0],))
    #  Les actualités : jamais une épinglée.
    local.sql_plusieurs("INSERT INTO equipage_actualites (guild_id, id, titre, epingle, cree_le, maj_le) VALUES (1,?,?,?,?,?)",
                        [("banc-n1", "Vieille", 0, int(v), int(v)), ("banc-n2", "Épinglée", 1, int(v), int(v)),
                         ("banc-n3", "Récente", 0, int(now), int(now))])
    _regle(local, "actualites", 365)
    assert {r[0] for r in local.sql("SELECT id FROM equipage_actualites WHERE id LIKE 'banc-n%'")} == {"banc-n2", "banc-n3"}
    #  Les portraits : jamais celui d'une affiche, ni un récent ; son fichier part avec lui.
    avatars = tableau.dossier_site("avatars")
    for rid, age in ((8_100_001, 200), (8_100_002, 200), (8_100_003, 10)):
        local.sql("INSERT OR REPLACE INTO rell_avatars (roblox_id, nom, nom_cle, maj_le) VALUES (?, 'p', 'p', ?)",
                  (rid, int(now - age * JOUR)))
        (avatars / f"{rid}.webp").write_bytes(b"RIFF0000WEBP")
    local.sql("INSERT INTO rell_affiches (guild_id, id, roblox_id, cree_le, maj_le) VALUES (1, 'banc-aff', 8100002, ?, ?)",
              (int(now), int(now)))
    _regle(local, "portraits", 90)
    assert {r[0] for r in local.sql("SELECT roblox_id FROM rell_avatars WHERE roblox_id BETWEEN 8100001 AND 8100003")} \
        == {8_100_002, 8_100_003}
    assert not (avatars / "8100001.webp").exists() and (avatars / "8100002.webp").exists()
    #  Les empreintes : seulement celles des partis, seulement quand la liste des membres est complète.
    local.sql_plusieurs("INSERT OR REPLACE INTO user_fingerprints (guild_id, user_id, username_normalized, updated_at)"
                        " VALUES (1, ?, 'x', ?)", [(8_200_001, _sqlite(now - 200 * JOUR)), (1001, _sqlite(now - 200 * JOUR)),
                                                    (8_200_002, _sqlite(now - 10 * JOUR))])
    g = local.ctx.guild
    monkeypatch.setattr(g, "chunked", False)
    assert _regle(local, "empreintes", 90)[1] == 0, "liste des membres incomplète : rien"
    monkeypatch.setattr(g, "chunked", True)
    _regle(local, "empreintes", 90)
    assert {r[0] for r in local.sql("SELECT user_id FROM user_fingerprints WHERE user_id IN (8200001, 1001, 8200002)")} \
        == {1001, 8_200_002}
    #  Les invitations des partis ; l'audit du staff ; les questions.
    local.sql_plusieurs("INSERT OR REPLACE INTO invitations_arrivees (guild_id, membre_id, auteur_id, code, arrive, compte_cree,"
                        " parti) VALUES (1, ?, 1001, 'c', ?, ?, ?)",
                        [(8_300_001, int(v), int(v), int(now - 200 * JOUR)), (8_300_002, int(v), int(v), 0),
                         (8_300_003, int(v), int(v), int(now - 10 * JOUR))])
    _regle(local, "invitations", 180)
    assert {r[0] for r in local.sql("SELECT membre_id FROM invitations_arrivees WHERE membre_id BETWEEN 8300001 AND 8300003")} \
        == {8_300_002, 8_300_003}
    local.sql_plusieurs("INSERT INTO staff_audit_log (guild_id, actor_id, target_id, action, detail, surface, created_at)"
                        " VALUES (1, 1002, ?, 'warn', '', 'site', ?)", [(8_400_001, _sqlite(v)), (8_400_002, _sqlite(now - 10 * JOUR))])
    _regle(local, "audit_staff", 365)
    assert {r[0] for r in local.sql("SELECT target_id FROM staff_audit_log WHERE target_id IN (8400001, 8400002)")} == {8_400_002}


def test_LV12_fichiers_orphelins(local):
    import longevite
    now = time.time()
    vieux = now - 3 * JOUR
    medias, avatars, tr = tableau.dossier_site("medias"), tableau.dossier_site("avatars"), Path(transcript_store._BASE_DIR)
    fichiers = {"orphelin": medias / "OrphelinBanc0001.webp", "recent": medias / "RecentBanc000001.webp",
                "cite": medias / "CiteBanc00000001.webp", "reste": medias / "x.tmp", "portrait": avatars / "8900001.webp"}
    for nom, p in fichiers.items():
        p.write_bytes(b"RIFF0000WEBP")
        if nom != "recent":
            os.utime(p, (vieux, vieux))
    local.sql("INSERT INTO tableau_medias (id, guild_id, auteur_id, nom, type, octets, largeur, hauteur, cree_le)"
              " VALUES ('CiteBanc00000001', 1, 1, 'i', 'image/webp', 12, 1, 1, ?)", (int(vieux),))
    local.sql("INSERT INTO tableau_medias (id, guild_id, auteur_id, nom, type, octets, largeur, hauteur, cree_le)"
              " VALUES ('PerdueBanc000001', 1, 1, 'i', 'image/webp', 12, 1, 1, ?)", (int(vieux),))
    seul, garde = tr / "a_jetonOrphelinBanc0001", tr / "a_jetonGardeBanc000001"
    for d in (seul, garde):
        d.mkdir(parents=True, exist_ok=True)
        os.utime(d, (vieux, vieux))
    (tr / "jetonGardeBanc000001.html").write_text("<html></html>", encoding="utf-8")
    local.sql_plusieurs("INSERT OR REPLACE INTO equipage_vitrine (guild_id, affiche_id, maj_le, maj_par) VALUES (1, ?, ?, 0)",
                        [("banc-effacee", int(now)), ("banc-aff", int(now))])   # « banc-aff » existe (LV12)
    longevite._orphelins_vus.update(t=0.0, n=None)
    avant, n, _apres = _regle(local, "orphelins", 1, now)
    assert n == avant >= 6
    assert [r[0] for r in local.sql("SELECT affiche_id FROM equipage_vitrine WHERE affiche_id LIKE 'banc-%'")] == ["banc-aff"], \
        "le réglage d'une affiche effacée part ; celui d'une affiche qui existe reste"
    assert not fichiers["orphelin"].exists() and not fichiers["reste"].exists() and not fichiers["portrait"].exists()
    assert fichiers["recent"].exists() and fichiers["cite"].exists(), "récent ou cité : gardé"
    assert not seul.exists() and garde.exists()
    assert not local.sql("SELECT 1 FROM tableau_medias WHERE id='PerdueBanc000001'"), "une image sans fichier"
    assert local.sql("SELECT 1 FROM tableau_medias WHERE id='CiteBanc00000001'")


# ═══════════════════════════════════════════════════════════════════════════════
#  LV13 — les équipes du clan : un membre parti sort de son équipe
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV13_equipes_un_parti_sort_de_son_equipe_sans_orphelin(local, monkeypatch):
    import longevite
    now = int(time.time())
    local.sql_plusieurs("INSERT INTO equipes (guild_id, id, nom, type, chef_id, ordre, version, cree_le, maj_le, maj_par)"
                        " VALUES (1, ?, ?, '', ?, 90, 1, ?, ?, 0)",
                        [("banc-e1", "Banc 1", 1011, now, now), ("banc-e2", "Banc 2", 8_500_009, now, now)])
    local.sql_plusieurs("INSERT INTO equipes_membres (guild_id, equipe_id, membre_id) VALUES (1, ?, ?)",
                        [("banc-e1", 1012), ("banc-e1", 8_500_001), ("banc-e2", 1013), ("banc-e2", 8_500_002),
                         ("banc-supprimee", 8_500_003)])

    def etat():
        membres = sorted(local.sql("SELECT equipe_id, membre_id FROM equipes_membres WHERE equipe_id LIKE 'banc-%'"))
        chefs = dict(local.sql("SELECT id, chef_id FROM equipes WHERE id LIKE 'banc-e%'"))
        versions = dict(local.sql("SELECT id, version FROM equipes WHERE id LIKE 'banc-e%'"))
        return membres, chefs, versions
    #  Au départ (on_member_remove) : sa place, et rien d'autre.
    assert local.faire(longevite.membre_parti(1, 8_500_001)) == 1
    membres, chefs, versions = etat()
    assert ("banc-e1", 8_500_001) not in membres and ("banc-e1", 1012) in membres and versions["banc-e1"] == 2
    assert local.faire(longevite.membre_parti(1, 424242)) == 0, "sans équipe : rien"
    #  Le rattrapage de chaque jour : seulement quand la liste des membres est complète.
    g = local.ctx.guild
    monkeypatch.setattr(g, "chunked", False)
    assert local.faire(tableau.REGLES["equipes_partis"]["apercu"](1, 0, now)) == 1, "seule la place orpheline"
    monkeypatch.setattr(g, "chunked", True)
    avant, n, apres = _regle(local, "equipes_partis", 0)
    assert avant == n == 3 and apres == 0, "le membre parti, le chef parti, la place d'une équipe effacée"
    membres, chefs, versions = etat()
    assert membres == [("banc-e1", 1012), ("banc-e2", 1013)]
    assert chefs == {"banc-e1": 1011, "banc-e2": 0}, "un chef parti : l'équipe reste, sans chef"
    assert versions["banc-e2"] == 2, "une saisie ouverte sur le site voit le changement"
    #  Le bot l'appelle à chaque départ.
    src = ast.unparse(_fonction_bot("on_member_remove"))
    assert "await longevite.membre_parti(m.guild.id, m.id)" in src
    #  Les lectures des équipes passent par les clés (le serveur, l'équipe, le membre) : aucune table parcourue.
    for sql in ("SELECT equipe_id, membre_id FROM equipes_membres WHERE guild_id=1",
                "SELECT id FROM equipes WHERE guild_id=1 ORDER BY ordre, cree_le, id",
                "DELETE FROM equipes_membres WHERE guild_id=1 AND membre_id IN (5)",
                "SELECT 1 FROM equipes_membres WHERE guild_id=1 AND equipe_id='x'"):
        assert "SCAN" not in _plan(local.chemin, sql).replace("SCAN CONSTANT", ""), (sql, _plan(local.chemin, sql))


# ═══════════════════════════════════════════════════════════════════════════════
#  LV14 — les plans de SQLite
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV14_plans_des_lectures_corrigees(local, monkeypatch):
    import longevite
    _banc_journal(local)
    with contextlib.closing(sqlite3.connect(local.chemin)) as c:
        c.execute("ANALYZE")
    notes = []
    monkeypatch.setattr(longevite, "_get_db", _base_espionnee(local.chemin, notes))
    g = local.ctx.guild
    for requete in ({"cat": "Banc", "n": "50"}, {"n": "50"}, {"depuis": str(_paris(2026, 10, 20)), "cat": "Modération"}):
        notes.clear()
        st, r = local.faire(longevite._route_journal(g, None, requete, None))
        assert st == 200
        sql, args = next(x for x in notes if "ORDER BY quand DESC" in x[0])
        plan = _plan(local.chemin, sql, args)
        assert "SCAN registre" not in plan and "TEMP B-TREE" not in plan, (requete, plan)
    for sql, args in (("SELECT COUNT(*) FROM registre WHERE guild_id=? AND categorie IN ('Messages', 'Vocal')", (1,)),
                      ("SELECT COUNT(*) FROM registre WHERE guild_id=? AND categorie NOT IN ('Messages', 'Vocal')", (1,))):
        assert "COVERING INDEX idx_registre_categorie" in _plan(local.chemin, sql, args), sql
    for sql, args in (("SELECT annonce_id, membre_id FROM annonces_vues WHERE annonce_id=? LIMIT ?", (1, 40)),
                      ("SELECT * FROM suggestions_votes v WHERE v.suggestion_id=?", (1,))):
        assert "SCAN" not in _plan(local.chemin, sql, args), sql


# ═══════════════════════════════════════════════════════════════════════════════
#  LV15 — le banc lui-même
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV15_le_banc_construit_nettoie_mesure_et_ecrit_son_rapport(tmp_path):
    with socket.socket() as s:
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
    sortie = tmp_path / "taille.json"
    r = subprocess.run([sys.executable, "-X", "utf8", str(RACINE / "outils" / "banc_annees.py"), "--annees", "0.08",
                        "--sans-fichiers", "--port", str(port), "--json", str(sortie)], cwd=str(RACINE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    rapport = json.loads(sortie.read_text(encoding="utf-8"))
    assert {"base", "routes", "regles", "boucles", "demarrage", "memoire", "compactage", "rattrapage"} <= set(rapport)
    assert all(v["statut"] == 200 for v in rapport["routes"].values()), {k: v["statut"] for k, v in rapport["routes"].items()}
    assert "vitrine : données" in rapport["routes"] and "équipes (direction)" in rapport["routes"]
    assert rapport["compactage"]["passage"]["rendues"] * 4096 >= rapport["compactage"]["nuit_libres"] - 4096
    sys.path.insert(0, str(RACINE / "outils"))
    try:
        import banc_annees
        texte = banc_annees.markdown([rapport], "Banc d'essai")
    finally:
        sys.path.remove(str(RACINE / "outils"))
        sys.modules.pop("banc_annees", None)
    for titre in ("# Banc d'essai", "## Les réponses du site", "### La vitrine publique", "## Le compactage",
                  "### La rubrique « Nettoyage », règle par règle", "## Les hypothèses"):
        assert titre in texte, titre


# ═══════════════════════════════════════════════════════════════════════════════
#  LV16 — les fonctions pures de la page
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV16_fonctions_de_la_page(tmp_path):
    src = (RACINE / "site" / "longevite.js").read_text(encoding="utf-8")
    #  Les familles : chaque règle du serveur dans la sienne.
    familles = [(int(a), int(b), t) for a, b, t in re.findall(r'\[(\d+), (\d+), "([^"]+)", "[a-z]+"\]', src)]
    assert familles and familles[0][0] == 0 and all(familles[k][1] == familles[k + 1][0] for k in range(len(familles) - 1))

    def famille(ordre):
        return next(t for a, b, t in familles if a <= ordre < b)
    attendu = {"journal_messages": "Le journal", "journal": "Le journal", "tickets_archives": "Les tickets",
               "transcripts": "Les tickets", "tickets_fermes": "Les tickets", "candidatures": "Le recrutement",
               "casier_detections": "Le casier", "casier_sanctions": "Le casier", "actualites": "Le clan",
               "equipes_partis": "Le clan", "portraits": "Les affiches", "empreintes": "Les membres",
               "invitations": "Les membres", "audit_staff": "Les membres", "questions": "Les salons", "sondages": "Les salons",
               "idees": "Les salons", "entraide": "Les salons", "orphelins": "Le site et ses fichiers"}
    import longevite
    ordres = {r["cle"]: r["ordre"] for r in longevite.REGLES_NETTOYAGE} | {"journal_messages": 10, "journal": 11,
                                                                            "tickets_archives": 20, "transcripts": 21,
                                                                            "candidatures": 32}
    for cle, titre in attendu.items():
        assert famille(ordres[cle]) == titre, cle
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node n'est pas installé : les fonctions de la page ne s'exécutent pas ici")
    dom = (RACINE / "site" / "dom.js").read_text(encoding="utf-8")
    harnais = tmp_path / "harnais.mjs"
    harnais.write_text(r"""
import { readFileSync } from "node:fs";
const src = readFileSync(process.argv[2], "utf8"), dom = readFileSync(process.argv[3], "utf8");
const extraire = (texte, nom) => {
  const i = texte.indexOf("function " + nom + "(");
  if (i < 0) throw new Error("absente : " + nom);
  let n = 0, j = texte.indexOf("{", i);
  for (; j < texte.length; j++) { if (texte[j] === "{") n++; else if (texte[j] === "}" && !--n) break; }
  return texte.slice(i, j + 1);
};
const ligne = (texte, debut) => { const i = texte.indexOf(debut); return texte.slice(i, texte.indexOf("\n", i)).replace(/^export /, ""); };
const code = [ligne(dom, "export const accord ="), ligne(dom, "export const quantite ="),
  ...["texteApercu", "comptesParCategorie", "reunirFermes"].map((n) => extraire(src, n))].join("\n").replace(/export /g, "");
const nombre = (n) => String(n), JOUR = 86400;
const cleJour = (t) => new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(t * 1000));
const f = new Function("nombre", "JOUR", "cleJour", code + "\nreturn { texteApercu, comptesParCategorie, reunirFermes };")(nombre, JOUR, cleJour);
const n = Date.UTC(2026, 9, 26, 12) / 1000;
console.log(JSON.stringify({
  apercus: [f.texteApercu(undefined), f.texteApercu(null), f.texteApercu(0), f.texteApercu(1), f.texteApercu(3),
            f.texteApercu(0, 45), f.texteApercu(1, 45), f.texteApercu(12, 45)],
  comptes7: f.comptesParCategorie({ "2026-10-26": { A: 2 }, "2026-10-20": { A: 1, B: 4 }, "2026-10-19": { A: 100 } }, "7", n),
  comptes90: f.comptesParCategorie({ "2026-10-26": { A: 2 } }, "90", n),
  fermes: f.reunirFermes([{ ticket: 1, ferme: 10 }, { ticket: 2, ferme: 30 }], [{ ticket: 1, ferme: 10 }, { ticket: 3, ferme: 20 }]).map((t) => t.ticket),
}));
""", encoding="utf-8")
    sortie = subprocess.run([node, str(harnais), str(RACINE / "site" / "longevite.js"), str(RACINE / "site" / "dom.js")],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert sortie.returncode == 0, sortie.stderr
    vu = json.loads(sortie.stdout)
    assert vu["apercus"] == ["", "aperçu indisponible", "rien ne partira au prochain passage",
                             "1 élément partira au prochain passage", "3 éléments partiront au prochain passage",
                             "avec 45 j : rien ne partirait", "avec 45 j : 1 élément partirait",
                             "avec 45 j : 12 éléments partiraient"]
    assert vu["comptes7"] == {"A": 3, "B": 4} and vu["comptes90"] is None, "sept jours de Paris, aujourd'hui compris"
    assert vu["fermes"] == [2, 3, 1], "sans doublon, les plus récents d'abord"


# ═══════════════════════════════════════════════════════════════════════════════
#  LV17 — chaque module de la page se lit comme un module ES
# ═══════════════════════════════════════════════════════════════════════════════

def test_LV17_chaque_module_de_la_page_se_lit_comme_un_module_es():
    """27/10/2026 : une fusion avait déclaré `familleDe` deux fois dans discord.js (l'import des règles du Nettoyage et
    les familles des tickets) — tout le Port ne s'ouvrait plus, et aucun test ne le voyait (`node --check` seul lit un
    .js comme un script)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node n'est pas installé : les modules de la page ne se vérifient pas ici")
    fautes = []
    for f in sorted((RACINE / "site").glob("*.js")):
        r = subprocess.run([node, "--input-type=module", "--check"], input=f.read_text(encoding="utf-8"), capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            fautes.append(f"{f.name} : {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    assert not fautes, fautes
