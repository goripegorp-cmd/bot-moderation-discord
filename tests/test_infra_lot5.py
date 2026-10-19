"""19/10/2026 (audit de l'infrastructure) : sauvegardes réduites à quelques heures d'historique,
détecteurs d'images chargés sur la boucle, rétention RGPD qui ne purgeait rien, cookie du site qui
survivait à la déconnexion, site qui affichait « 0 » quand la base était occupée, sondages coincés."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import aiosqlite
import pytest

import db_backup
import gdpr
import nsfw_scan
import ocr_scan
import recrutements
import sondages
from conftest_discord import Obj, base

RACINE = Path(__file__).resolve().parent.parent


def test_I1_une_copie_par_jour_sept_jours_et_quatre_semaines(tmp_path, monkeypatch):
    monkeypatch.setattr(db_backup, "_resolve_backup_dir", lambda: tmp_path)
    maintenant = time.time()
    for j in range(60):  # une copie par jour pendant 60 jours
        f = tmp_path / f"bot.db.{j:03d}.bak"
        f.write_bytes(b"x")
        os.utime(f, (maintenant - j * 86400, maintenant - j * 86400))
    db_backup._rotate_old_backups_sync()
    restes = sorted(maintenant - f.stat().st_mtime for f in tmp_path.glob("*.bak"))
    assert len(restes) <= db_backup.RETENTION_COUNT + db_backup.SEMAINES
    assert all(r < 7 * 86400 for r in restes[:7]), "les 7 plus récentes"
    assert max(restes) > 14 * 86400, "et des semaines plus anciennes"
    assert db_backup.copie_recente() is True, "un redémarrage ne refait pas de copie"
    for f in tmp_path.glob("*.bak"):
        os.utime(f, (maintenant - 30 * 3600, maintenant - 30 * 3600))
    assert db_backup.copie_recente() is False


def test_I2_les_detecteurs_d_images_ne_se_chargent_jamais_sur_la_boucle(monkeypatch):
    for module in (nsfw_scan, ocr_scan):
        monkeypatch.setattr(module, "_AVAILABLE", None)

        def interdit():
            raise AssertionError("chargement sur la boucle")
        monkeypatch.setattr(module, "_load", interdit)
        assert module.available() is False, module.__name__
        monkeypatch.setattr(module, "_AVAILABLE", True)
        assert module.available() is True
    assert ocr_scan.etat() is True
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "run_in_executor(None, nsfw_scan.charger)" in src and "run_in_executor(None, ocr_scan.charger)" in src


def test_I3_la_retention_purge_vraiment(tmp_path):
    chemin = tmp_path / "r.db"

    async def scenario():
        async with aiosqlite.connect(chemin) as db:
            await db.execute("CREATE TABLE phishing_log (guild_id INTEGER, user_id INTEGER, detected_at TEXT)")
            await db.execute("CREATE TABLE daily_join_log (guild_id INTEGER, user_id INTEGER, joined_day TEXT, left_day TEXT)")
            vieux, recent = "2020-01-01 10:00:00", time.strftime("%Y-%m-%d %H:%M:%S")
            await db.executemany("INSERT INTO phishing_log VALUES (1, 7, ?)", [(vieux,), (recent,)])
            await db.executemany("INSERT INTO daily_join_log VALUES (1, 7, ?, ?)",
                                 [("2020-01-01", None), (None, "2020-01-02"), (recent[:10], None)])
            await db.commit()
            out = await gdpr.run_retention(db)
            async with db.execute("SELECT COUNT(*) FROM phishing_log") as c:
                phishing = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM daily_join_log") as c:
                arrivees = (await c.fetchone())[0]
            return out, phishing, arrivees
    out, phishing, arrivees = asyncio.run(scenario())
    assert phishing == 1 and arrivees == 1, (out, phishing, arrivees)
    assert gdpr.RETENTION["phishing_log"] == ("detected_at", 90)


def test_I4_la_deconnexion_efface_vraiment_le_cookie():
    src = (RACINE / "tableau.py").read_text(encoding="utf-8")
    assert 'del_cookie(COOKIE, path="/", secure=True' in src


def test_I5_une_base_occupee_n_est_pas_une_fiche_vide(tmp_path):
    chemin = tmp_path / "l.db"

    async def scenario():
        async with aiosqlite.connect(chemin) as db:
            assert await recrutements._lignes(db, "SELECT * FROM table_absente", ()) == []
            with pytest.raises(sqlite3.OperationalError):
                await recrutements._lignes(db, "SELECT colonne_absente FROM sqlite_master", ())
    asyncio.run(scenario())


def test_I6_un_sondage_sans_salon_n_est_plus_relu_pour_toujours(tmp_path):
    get_db, cfg, db_set, _conf = base(tmp_path)
    marques = []

    async def marquer(sid, **kw):
        marques.append((sid, kw))
    ancien = sondages._marquer
    sondages._marquer = marquer
    try:
        g = Obj(get_channel=lambda cid: None, get_thread=lambda cid: None)
        asyncio.run(sondages.rafraichir(g, {"id": 5, "channel_id": "9", "message_id": "1", "retire_le": 0}))
    finally:
        sondages._marquer = ancien
    assert marques == [(5, {"termine": 1})]
