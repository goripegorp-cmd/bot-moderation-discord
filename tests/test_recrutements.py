"""19/10/2026 : « les fiches de toutes celles et ceux qui ont candidaté, acceptés et refusés…
un vrai système de nettoyage : qu'on ait que le filtre, pas un surplus de données »."""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone

import aiosqlite
import discord

import gdpr
import recrutements as R
import rellseas_panneau
from conftest_discord import Obj


def _unix(j, h=12, mois=10):
    return int(datetime(2026, mois, j, h, 0, tzinfo=timezone.utc).timestamp())


def _ev(ouvert, ferme, staff=2, motif=""):
    return [("create", 7, "", ouvert), ("claim", staff, "", ouvert + 60), ("close", staff, motif, ferme)]


def _part(cand, staff, cid=7):
    return [{"id": cid, "nom": "c", "bot": False, "n": cand}, {"id": 2, "nom": "s", "bot": False, "n": staff},
            {"id": 3, "nom": "bot", "bot": True, "n": 4}]


class Env:
    def __init__(self, tmp_path):
        self.base = tmp_path / "r.db"
        self.conf = {rellseas_panneau.CLE_ROLE_CIBLE: 50,
                     "ticket_panels": {"p1": {"name": "Rellseas"}, "p2": {"name": "Support"}}}
        self.envois = []

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(self.base)
            try:
                yield db
            finally:
                await db.close()
        self.get_db = get_db

        async def cfg(_g):
            return self.conf

        async def db_set(_g, k, v):
            self.conf[k] = v

        async def salon(_g, _c):
            return Obj(send=self._envoyer)
        self.role = Obj(id=50)
        R.setup(get_db=get_db, cfg=cfg, db_set=db_set, salon=salon,
                role=lambda g, c: self.role, panneaux=rellseas_panneau.panneaux_tickets,
                log=lambda *a: None)
        membres = {7: Obj(id=7, display_name="Kolax", roles=[self.role]),
                   8: Obj(id=8, display_name="Mira", roles=[]),
                   2: Obj(id=2, display_name="Capitaine", roles=[])}
        self.g = Obj(id=1, name="GoRP SEA", get_member=membres.get)
        asyncio.run(R.init_db())

    async def _envoyer(self, **kw):
        self.envois.append(kw)


def test_E1_reponses_gardees_entieres_mais_bornees():
    r = R.garder({"  Pseudo   Roblox ": " Kolax_RS ", "Vide": "  ", "Motivation": "x" * 900,
                  **{f"Q{k}": "r" for k in range(20)}})
    assert r["Pseudo Roblox"] == "Kolax_RS" and "Vide" not in r
    assert len(r["Motivation"]) == R.REPONSE_MAX and r["Motivation"].endswith("…")
    assert len(r) == R.REPONSES_MAX


def test_E2_seules_les_decisions_claires_comptent():
    """« Garder uniquement les personnes qui ont été acceptées ou refusées »."""
    assert R.decision(True, "") == "acceptes", "porte le rôle du clan"
    assert R.decision(False, "Refusé : niveau trop bas") == "refuses"
    assert R.decision(False, "Accepté, bienvenue dans l'équipage") == "acceptes"
    assert R.decision(False, "Pas de réponse de l'utilisateur") is None, "sans suite : écarté"
    assert R.decision(False, "Résolu") is None


def test_E3_une_fiche_par_candidat_vides_et_doublons_ecartes():
    lignes = [dict(candidat_id=7, nom="K", ferme=10, msg_candidat=3, reponses={}, raison=""),
              dict(candidat_id=7, nom="K", ferme=20, msg_candidat=None, reponses={}, raison="Résolu"),
              dict(candidat_id=8, nom="M", ferme=15, msg_candidat=0, reponses={}, raison=""),
              dict(candidat_id=9, nom="Z", ferme=5, msg_candidat=2, reponses={}, raison="Doublon d'un autre ticket"),
              dict(candidat_id=6, nom="A", ferme=8, msg_candidat=None, reponses={}, raison="")]
    fiches, vides, doublons = R.nettoyer(lignes, lambda uid, raison: "acceptes" if uid == 7 else
                                          ("refuses" if uid == 6 else None))
    assert (vides, doublons) == (1, 1)
    assert [(d["candidat_id"], d["ferme"], d["dates"]) for d in fiches] == [(7, 20, [10, 20]), (6, 8, [8])]
    assert [d["statut"] for d in fiches] == ["acceptes", "refuses"]


def test_E4_le_mois_a_l_heure_de_paris():
    assert R.mois_precedent(datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)) == "2025-12"
    assert R.mois_precedent(datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)) == "2026-10"
    debut, _fin = R.bornes("2026-10")
    assert datetime.fromtimestamp(debut, timezone.utc).hour == 22
    assert R.bornes("tout")[0] == 0 and R.libelle("tout") == "depuis le début"


def test_E5_rattrapage_des_tickets_fermes_avant_le_suivi(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        async with env.get_db() as db:
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
                             " user_id INTEGER, panel_id TEXT, claimed_by INTEGER, status TEXT, answers TEXT,"
                             " created_at DATETIME)")
            await db.execute("CREATE TABLE ticket_audit(id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
                             " actor_id INTEGER, action TEXT, detail TEXT, at DATETIME)")
            await db.executemany("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)", [
                (11, 1, 900, 7, "p1", 2, "closed", json.dumps({"Pseudo Roblox": "Kolax_RS"}), "2026-09-03 10:00:00"),
                (12, 1, 901, 8, "p1", 0, "closed", "{}", "2026-09-05 10:00:00"),
                (13, 1, 902, 8, "p2", 2, "closed", "{}", "2026-09-06 10:00:00"),
                (14, 1, 903, 9, "p1", 0, "open", json.dumps({"Pseudo Roblox": "Zed"}), "2026-10-18 10:00:00")])
            await db.executemany("INSERT INTO ticket_audit(guild_id, channel_id, actor_id, action, detail, at)"
                                 " VALUES (?,?,?,?,?,?)", [
                (1, 900, 2, "close", "Accepté, bienvenue dans l'équipage", "2026-09-03 12:30:00"),
                (1, 901, 2, "close", "Refusé : trop jeune", "2026-09-06 09:00:00")])
            await db.commit()
        n = await R.rattraper(env.g)
        deux = await R.rattraper(env.g)
        return n, deux, await R.candidatures(env.g)
    n, deux, donnees = asyncio.run(scenario())
    assert (n, deux) == (2, 0), "les tickets Support ne sont pas des candidatures ; une seule fois"
    fiches = {d["candidat_id"]: d for d in donnees["fiches"]}
    assert fiches[7]["statut"] == "acceptes" and fiches[7]["reponses"] == {"Pseudo Roblox": "Kolax_RS"}
    assert fiches[7]["ferme"] - fiches[7]["ouvert"] == 9000, "ouvert 10 h, fermé 12 h 30"
    assert fiches[8]["statut"] == "refuses" and fiches[8]["raison"].startswith("Refusé")
    assert not fiches[8]["parti"]
    assert [o["candidat_id"] for o in donnees["en_cours"]] == [9]
    assert donnees["en_cours"][0]["reponses"] == {"Pseudo Roblox": "Zed"}


def test_E6_enregistrement_a_la_cloture_avec_le_motif(tmp_path):
    env = Env(tmp_path)

    async def scenario():
        await R.enregistrer(1, 11, 7, "Kolax", _ev(_unix(3), _unix(3, 13), motif="Accepté"),
                            {"Pseudo Roblox": "Kolax_RS"}, _part(5, 4), "https://bot/t/a")
        await R.enregistrer(1, 12, 9, "Zed", _ev(_unix(7), _unix(7)), {}, _part(0, 1, cid=9), "")
        return await R.lire(1, "2026-10")
    lignes = asyncio.run(scenario())
    assert lignes[0]["raison"] == "Accepté" and lignes[0]["pris_par"] == 2 and lignes[0]["transcript"]
    assert lignes[1]["msg_candidat"] == 0, "ticket vide, compté puis écarté du bilan"


def test_E7_recap_et_bilan_publies_une_fois_jamais_vides(tmp_path):
    env = Env(tmp_path)
    novembre = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)

    async def scenario():
        vide = await R.publier_recap(env.g), await R.exporter(env.g, novembre)
        env.conf.pop(R.CLE_EXPORT)
        await R.enregistrer(1, 11, 7, "Kolax", _ev(_unix(3), _unix(3, 13)), {}, _part(5, 4), "")
        return vide, await R.publier_recap(env.g), await R.publier_recap(env.g), \
            await R.exporter(env.g, novembre), await R.exporter(env.g, novembre)
    vide, recap, recap2, bilan, bilan2 = asyncio.run(scenario())
    assert vide == (False, False)
    assert (recap, recap2, bilan, bilan2) == (True, False, True, False) and len(env.envois) == 2
    composants = list(env.envois[0]["view"].walk_children())
    assert any(getattr(c, "custom_id", "") == "recr:web" for c in composants), "le bouton du tableau de bord"
    assert "file" not in env.envois[0], "plus de fichier texte : le tableau de bord le remplace"


def test_E8_rgpd_et_rellseas():
    assert gdpr.DELETE_SUBJECT_KEEP_ACTOR["recrutements"] == {
        "subject": ["candidat_id"], "actor": ["ferme_par", "pris_par"]}
    assert gdpr.RETENTION["recrutements"] == ("ferme_le", 365)
    v = rellseas_panneau.RellseasGestionV2.squelette()
    ids = [c.custom_id for c in v.walk_children() if hasattr(c, "custom_id")]
    assert "rellseas_g_tableau" in ids and "rellseas_g_recrutements" not in ids
    assert all(len(r.children) <= 5 for r in v.walk_children() if isinstance(r, discord.ui.ActionRow))
