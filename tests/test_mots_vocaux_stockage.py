"""14/10/2026 — trois demandes du propriétaire, une preuve chacune.

  · « Damn c'est magnifique ✨ » supprimé comme mot interdit : les exclamations
    sortent de la liste, et la détection ne recolle plus les mots voisins ;
  · « le rôle fondateur ou le rôle direction ne peuvent pas déplacer » dans les
    vocaux créés par le bot ;
  · « pas de surdonnées monstrueuses à stocker » : chaque gros poste a sa part
    du volume, et une ligne par jour dit l'état réel.
"""
from __future__ import annotations

import ast
import contextlib
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

import acces_direction
import data_cleanup
import db_backup
import mots_interdits as mi
import stockage

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_ZONES = (RACINE / "social_zones.py").read_text(encoding="utf-8")


def _fonction(src, nom):
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


# ═══ Mots interdits ════════════════════════════════════════════════════════════

def test_M1_la_capture_du_14_10_damn_est_une_exclamation():
    assert mi.est_exclamation_libre("Damn") and mi.est_exclamation_libre(" FLÛTE ")
    gardes, retires = mi.trier_liste(["fdp", "damn", "pute", "Zut"])
    assert gardes == ["fdp", "pute"] and retires == ["damn", "Zut"]
    assert mi.cherche("Damn c'est magnifique ✨", gardes) == (False, None)


@pytest.mark.parametrize("phrase", [
    "j'ai pu te répondre hier",          # « pute » recollé
    "la mer de glace est magnifique",    # « merde » recollé
    "ni que toi ni que moi",             # « nique » recollé
    "Ah, c'est magnifique, c'est bien",
    "le contenu du salon",               # « con » au début d'un mot
    "un sandwich au bacon",              # « con » à la fin d'un mot
    "j'ai 55 ans et 1312 abonnés",       # des chiffres ne sont pas des lettres
])
def test_M2_aucun_mot_recolle_ni_mot_dans_un_mot(phrase):
    liste = ["pute", "merde", "nique", "con", "ss"]
    assert mi.cherche(phrase, liste) == (False, None), phrase


@pytest.mark.parametrize("phrase,mot", [
    ("t'es un con", "con"), ("CON !", "con"), ("espèce de c0n", "con"),
    ("c.o.n", "con"), ("p u t e", "pute"), ("pu-te va", "pute"),
    ("sale $alope", "salope"), ("fils   de pute", "fils de pute"),
    ("un encule", "enculé"), ("un ENCULÉ", "enculé"),
])
def test_M3_les_vrais_mots_et_leurs_contournements_restent_vus(phrase, mot):
    assert mi.cherche(phrase, ["fils de pute", "con", "pute", "salope", "enculé"]) \
        == (True, mot), phrase


def test_M4_la_liste_blanche_gagne_toujours():
    assert mi.cherche("quel con", ["con"], ["CON"]) == (False, None)


def test_M5_un_message_hostile_ne_gele_pas_le_bot():
    """Anti-ReDoS : séparateurs disjoints des lettres, longueurs bornées."""
    mot = "abcdefghijklmnopqrstuvwxyzabcdefghijklmn"          # 40 lettres
    piege = ("a . " * 2000) + "!"
    t0 = time.perf_counter()
    mi.cherche(piege, [mot, "i" * 40, "s" * 40])
    #  ~10 ms en vrai ; un retour arrière explosif prendrait des minutes. 5 s : marge
    #  pour une machine de CI partagée (1,36 s mesurées le 19/10).
    assert time.perf_counter() - t0 < 5.0


def test_M6_branchement_dans_le_bot():
    assert "return mots_interdits.cherche(ct, words, whitelist)" in _fonction(
        SRC_BOT, "check_badwords")
    ajout = next(ast.unparse(n) for n in ast.walk(ast.parse(SRC_BOT))
                 if isinstance(n, ast.ClassDef) and n.name == "_BadwordsAddListModal")
    assert "new, refuses = mots_interdits.trier_liste(new)" in ajout
    demarrage = _fonction(SRC_BOT, "_travaux_de_demarrage")
    assert "await _retirer_exclamations(g)" in demarrage
    assert "gardes, retires = mots_interdits.trier_liste(mots)" in _fonction(
        SRC_BOT, "_retirer_exclamations")


# ═══ Vocaux créés : Direction et Fondateur ═════════════════════════════════════

class _Role(SimpleNamespace):
    def is_default(self):
        return self.id == 1


def test_V1_qui_est_direction_ou_fondateur():
    g = SimpleNamespace(roles=[
        _Role(id=1, name="@everyone", managed=False),
        _Role(id=1089228169028046988, name="Direction", managed=False),
        _Role(id=10, name="👑・Fondateur", managed=False),
        _Role(id=11, name="Co-Fondatrice", managed=False),
        _Role(id=12, name="Fondateurs du lore RP", managed=False),
        _Role(id=13, name="Fondateur", managed=True),       # rôle d'intégration
        _Role(id=14, name="Modérateur", managed=False),
    ])
    assert [r.id for r in acces_direction.roles(g)] == [1089228169028046988, 10, 11]


def test_V2_deplacer_seulement_si_le_bot_le_peut():
    ow = acces_direction.permission(SimpleNamespace(move_members=True))
    assert (ow.view_channel, ow.connect, ow.speak, ow.move_members) == (True,) * 4
    ow = acces_direction.permission(SimpleNamespace(move_members=False))
    assert ow.move_members is None, "sinon Discord refuse toute la création (403)"


def test_V3_les_deux_vocaux_crees_par_le_bot_les_recoivent():
    i_acces = SRC_BOT.index("overwrites[_r] = acces_direction.permission(_me_perms)")
    i_creer = SRC_BOT.index("new_channel = await member.guild.create_voice_channel(")
    assert i_acces < i_creer, "les permissions doivent partir AVEC la création"
    assert SRC_ZONES.index("acces_direction.roles(guild)") < SRC_ZONES.index(
        "vc = await guild.create_voice_channel(")


# ═══ Stockage ══════════════════════════════════════════════════════════════════

def test_S1_le_budget_garde_les_plus_recents():
    f = [("a", 100), ("b", 100), ("c", 100), ("d", 100)]
    assert stockage.a_retirer(f, 250) == ["c", "d"]
    assert stockage.a_retirer(f, 50, garder_min=2) == ["c", "d"]
    assert stockage.a_retirer(f, None) == [], "volume inconnu : rien ne part"


def _fichiers(dossier, n, octets, suffixe=".bak"):
    for k in range(n):
        p = dossier / f"bot.db.2026-10-0{k + 1}_0400{suffixe}"
        p.write_bytes(b"x" * octets)
        os.utime(p, (1_000_000 + k, 1_000_000 + k))      # k grand = récent


def test_S2_les_copies_bak_tiennent_dans_leur_part_du_volume(tmp_path, monkeypatch):
    _fichiers(tmp_path, 7, 1000)
    monkeypatch.setattr(db_backup, "_resolve_backup_dir", lambda: tmp_path)
    monkeypatch.setattr(stockage, "volume", lambda _c: (10_000, 5_000))   # 30 % = 3 000
    assert db_backup._rotate_old_backups_sync() == 4
    assert sorted(p.name[7:17] for p in tmp_path.glob("*.bak")) == [
        "2026-10-05", "2026-10-06", "2026-10-07"]
    monkeypatch.setattr(stockage, "volume", lambda _c: (1_000, 500))      # 300 octets
    db_backup._rotate_old_backups_sync()
    assert len(list(tmp_path.glob("*.bak"))) == stockage.COPIES_MIN


def test_S3_les_transcripts_aussi(tmp_path, monkeypatch):
    for k in range(5):
        d = tmp_path / f"ticket{k}"
        d.mkdir()
        (d / "index.html").write_bytes(b"x" * 1000)
        os.utime(d, (1_000_000 + k, 1_000_000 + k))
    monkeypatch.setattr(stockage, "volume", lambda _c: (8_000, 1))       # 25 % = 2 000
    assert stockage.plafonner_dossier(tmp_path, 0.25) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ticket3", "ticket4"]


@pytest.mark.asyncio
async def test_S4_la_ligne_quotidienne_dit_l_etat_reel(tmp_path):
    base = tmp_path / "bot.db"
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE grosse(x)")
        c.executemany("INSERT INTO grosse VALUES (?)", [(i,) for i in range(500)])
        c.execute("CREATE TABLE petite(x)")
        c.execute("INSERT INTO petite VALUES (1)")
        c.execute("ANALYZE")
    copies = tmp_path / "backups"
    copies.mkdir()
    (copies / "bot.db.x.bak").write_bytes(b"x" * 2048)

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()

    import unittest.mock as um
    #  Un volume sain, fixé : le disque du poste qui lance les tests n'y est pour rien.
    with um.patch.object(stockage, "volume", lambda _c: (10 * 1024 ** 3, 6 * 1024 ** 3)):
        ligne = await stockage.bilan(get_db, str(base), str(copies),
                                     str(tmp_path / "transcripts"), purges="2 purgés")
    assert ligne.startswith("[STOCKAGE] base ")
    assert "copies .bak 1 = 0 Mo" in ligne and "transcripts 0 Mo" in ligne
    assert "libres sur" in ligne and "plus grosses tables : grosse 500, petite 1" in ligne
    assert ligne.endswith(" · 2 purgés")
    #  14/10 (soir) : le journal tait cette ligne… sauf quand le volume est
    #  presque plein ; les pourcentages, eux, partent sur /stats.
    import journal
    assert not journal.a_garder(ligne, en_exception=False)
    assert set(stockage.DERNIER) == {"volume_pct", "base_pct", "copies_pct",
                                     "transcripts_pct", "memoire_mo", "releve_utc"}
    import unittest.mock as um
    with um.patch.object(stockage, "volume", lambda _c: (1000, 100)):
        plein = await stockage.bilan(get_db, str(base), str(copies), str(tmp_path / "t"))
    assert plein.startswith("🚨 [STOCKAGE] volume presque plein — base ")
    assert journal.a_garder(plein, en_exception=False)
    assert stockage.DERNIER["volume_pct"] == 90.0


@pytest.mark.asyncio
async def test_S4bis_stats_donne_les_pourcentages_jamais_de_taille():
    import json
    import health_server
    stockage.DERNIER.clear()
    stockage.DERNIER.update({"volume_pct": 12.5, "base_pct": 3.0, "copies_pct": 9.0,
                             "transcripts_pct": 0.5, "memoire_mo": 410,
                             "releve_utc": "2026-10-14 15:00"})
    try:
        r = await health_server._stats_handler(None)
        assert json.loads(r.text)["stockage"]["volume_pct"] == 12.5
        r = await health_server._health_handler(None)
        assert "stockage" not in json.loads(r.text), "/health reste minimal"
    finally:
        stockage.DERNIER.clear()


@pytest.mark.asyncio
async def test_S5_les_deux_tables_sans_fin_ont_une_retention(tmp_path):
    regles = {t: (c, j) for t, c, j in data_cleanup.CLEANUP_RULES}
    assert regles["activite_jours"] == ("jour", 90)
    assert regles["health_check_log"] == ("check_at", 30)
    base = tmp_path / "b.db"
    with sqlite3.connect(base) as c:
        c.execute("CREATE TABLE activite_jours(guild_id, user_id, jour, sources)")
        c.executemany("INSERT INTO activite_jours VALUES (1, 2, ?, '')",
                      [("2020-01-01",), ("2999-01-01",)])

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(base)
        try:
            yield db
        finally:
            await db.close()

    data_cleanup.setup(None, get_db)
    try:
        assert await data_cleanup._purge_table("activite_jours", "jour", 90) == 1
    finally:
        data_cleanup.setup(None, None)


def test_S6_le_bilan_part_chaque_jour():
    corps = _fonction(SRC_BOT, "db_optimizer_task")
    assert "await asyncio.to_thread(transcript_store.plafonner)" in corps
    assert "print(await stockage_module.bilan(" in corps
