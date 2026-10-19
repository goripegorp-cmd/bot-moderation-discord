"""19/10/2026 : « un export mensuel de tous les dossiers de recrutement, qu'on ait un aperçu,
avec un vrai système de nettoyage : qu'on ait que le filtre, pas un surplus de données »."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

import aiosqlite
import discord

import gdpr
import recrutements as R
import rellseas_panneau
from conftest_discord import Obj


def _unix(j, h=12, mois=10):
    return int(datetime(2026, mois, j, h, 0, tzinfo=timezone.utc).timestamp())


def _ev(ouvert, ferme, staff=2):
    return [("create", 7, "", ouvert), ("claim", staff, "", ouvert + 60), ("close", staff, "", ferme)]


def _part(cand, staff, cid=7):
    return [{"id": cid, "nom": "c", "bot": False, "n": cand}, {"id": 2, "nom": "s", "bot": False, "n": staff},
            {"id": 3, "nom": "bot", "bot": True, "n": 4}]


class Env:
    def __init__(self, tmp_path):
        self.base = tmp_path / "r.db"
        self.conf = {rellseas_panneau.CLE_ROLE_CIBLE: 50}
        self.envois = []

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(self.base)
            try:
                yield db
            finally:
                await db.close()

        async def cfg(_g):
            return self.conf

        async def db_set(_g, k, v):
            self.conf[k] = v

        async def salon(_g, _c):
            return Obj(send=self._envoyer)
        self.role = Obj(id=50)
        R.setup(get_db=get_db, cfg=cfg, db_set=db_set, salon=salon,
                role=lambda g, c: self.role if int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0)) == 50 else None,
                log=lambda *a: None)
        membres = {7: Obj(id=7, display_name="Kolax", roles=[self.role]),
                   8: Obj(id=8, display_name="Mira", roles=[]),
                   2: Obj(id=2, display_name="Capitaine", roles=[])}
        self.g = Obj(id=1, name="GoRP SEA", get_member=membres.get)
        asyncio.run(R.init_db())

    async def _envoyer(self, **kw):
        self.envois.append(kw)


def test_E1_les_reponses_sont_resserrees():
    r = R.resserrer({"  Pseudo   Roblox ": " Kolax_RS \n", "Vide": "  ", "Motivation": "x" * 200,
                     **{f"Q{k}": "r" for k in range(10)}})
    assert r["Pseudo Roblox"] == "Kolax_RS" and "Vide" not in r
    assert len(r["Motivation"]) == R.REPONSE_MAX and r["Motivation"].endswith("…")
    assert len(r) == R.REPONSES_MAX


def test_E2_un_candidat_une_ligne_et_les_tickets_vides_ecartes():
    lignes = [dict(candidat_id=7, nom="K", ferme=10, msg_candidat=3, reponses={}),
              dict(candidat_id=7, nom="K", ferme=20, msg_candidat=1, reponses={}),
              dict(candidat_id=8, nom="M", ferme=15, msg_candidat=0, reponses={}),
              dict(candidat_id=9, nom="Z", ferme=5, msg_candidat=2, reponses={})]
    dossiers, vides = R.nettoyer(lignes, lambda uid: "acceptes" if uid == 7 else "partis")
    assert vides == 1
    assert [(d["candidat_id"], d["ferme"], d["tickets"]) for d in dossiers] == [(9, 5, 1), (7, 20, 2)]
    assert R.resume(dossiers, vides) == "2 dossiers · Accepté 1 · Parti 1 · 1 ticket vide écarté"


def test_E3_le_mois_a_l_heure_de_paris():
    assert R.mois_precedent(datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)) == "2025-12"
    assert R.mois_precedent(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)) == "2026-10", \
        "le 1er novembre 0 h 30 à Paris est encore le 31 octobre en UTC"
    debut, fin = R.bornes("2026-10")
    assert datetime.fromtimestamp(debut, timezone.utc).hour == 22, "1er octobre 0 h à Paris"
    assert R.libelle("2026-10") == "octobre 2026"


def test_E4_bilan_filtrable_sans_surplus(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        await R.enregistrer(1, 11, 7, "Kolax", _ev(_unix(3), _unix(3, 13)),
                            {"Pseudo Roblox": "Kolax_RS"}, _part(5, 4), "https://bot/t/a")
        await R.enregistrer(1, 12, 8, "Mira", _ev(_unix(5), _unix(6)), {}, _part(2, 1, cid=8), "")
        await R.enregistrer(1, 13, 9, "Zed", _ev(_unix(7), _unix(7)), {}, _part(0, 1, cid=9), "")
        await R.enregistrer(1, 14, 9, "Zed", _ev(_unix(2, mois=9), _unix(2, mois=9)), {},
                            _part(3, 1, cid=9), "")
        return await R.bilan(env.g, "2026-10"), await R.bilan(env.g, "2026-10", "acceptes")
    (vue, fichier), (vue_a, fichier_a) = asyncio.run(scenario())
    texte = fichier.fp.getvalue().decode("utf-8")
    assert "2 dossiers · Accepté 1 · Sans le rôle 1 · 1 ticket vide écarté" in texte
    assert "Kolax" in texte and "Accepté" in texte and "1 h 00" in texte and "Capitaine" in texte
    assert "Pseudo Roblox : Kolax_RS" in texte and "https://bot/t/a" in texte
    assert "Zed" not in texte, "ticket vide en octobre, dossier de septembre hors du mois"
    assert "Mira" in texte and "Sans le rôle" in texte
    filtre = fichier_a.fp.getvalue().decode("utf-8")
    assert "Kolax" in filtre and "Mira" not in filtre and fichier_a.filename.endswith("-acceptes.txt")
    composants = list(vue.walk_children())
    assert any(isinstance(c, discord.ui.File) and c.media.url == f"attachment://{fichier.filename}"
               for c in composants)
    assert any(getattr(c, "custom_id", "") == "recr:f:2026-10" for c in composants)


def test_E5_l_export_du_mois_part_une_fois_et_jamais_vide(tmp_path):
    env = Env(tmp_path)
    novembre = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)

    async def scenario():
        vide = await R.exporter(env.g, novembre)
        env.conf.pop(R.CLE_EXPORT)
        await R.enregistrer(1, 11, 7, "Kolax", _ev(_unix(3), _unix(3, 13)), {}, _part(5, 4), "")
        return vide, await R.exporter(env.g, novembre), await R.exporter(env.g, novembre)
    vide, premier, second = asyncio.run(scenario())
    assert vide is False, "un mois sans dossier ne publie rien"
    assert premier is True and second is False and len(env.envois) == 1
    assert env.conf[R.CLE_EXPORT] == "2026-10"


def test_E6_rgpd_le_candidat_s_efface_le_staff_s_anonymise_un_an_de_retention():
    assert gdpr.DELETE_SUBJECT_KEEP_ACTOR["recrutements"] == {
        "subject": ["candidat_id"], "actor": ["ferme_par", "pris_par"]}
    assert gdpr.RETENTION["recrutements"] == ("ferme_le", 365)


def test_E7_rellseas_ouvre_le_mois_en_cours():
    v = rellseas_panneau.RellseasGestionV2.squelette()
    ids = [c.custom_id for c in v.walk_children() if hasattr(c, "custom_id")]
    assert "rellseas_g_recrutements" in ids
    assert all(len(r.children) <= 5 for r in v.walk_children() if isinstance(r, discord.ui.ActionRow))
