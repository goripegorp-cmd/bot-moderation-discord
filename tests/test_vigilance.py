"""19/10/2026 : « une alerte dans les logs quand un membre cumule plusieurs événements graves… et
après, ça s'enlève une fois qu'on a géré »."""
from __future__ import annotations

import asyncio
import contextlib

import aiosqlite
import discord

import registre
import vigilance as V
from conftest_discord import Obj


def _evt(t, g):
    return {"quand": t, "gravite": g, "texte": f"évènement {t}"}


def test_V1_incidents_et_points():
    evts = [_evt(100, 1), _evt(105, 3), _evt(300, 1), _evt(800, 2)]
    assert [len(i) for i in V.incidents(evts)] == [2, 1, 1], "une détection et sa sanction = un incident"
    assert V.mesure(evts) == (3, 6), "un incident vaut sa gravité la plus haute"
    assert V.alerte_due(evts)
    assert not V.alerte_due([_evt(100, 1), _evt(500, 1)]), "deux avertissements : pas encore"
    assert V.alerte_due([_evt(100, 3), _evt(900, 1)]), "4 points suffisent"


class Monde:
    def __init__(self, tmp_path):
        chemin = tmp_path / "v.db"

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(chemin)
            try:
                yield db
            finally:
                await db.close()
        self.get_db = get_db
        self.envois, self.edits, self.messages, self.cartes, self.vus = [], [], {}, [], []
        monde = self

        class Message:
            def __init__(self, mid, salon):
                self.id, self.channel = mid, salon

            async def edit(self, **kw):
                monde.edits.append(kw)

        class Salon:
            id = 77

            async def send(self, **kw):
                m = Message(1000 + len(monde.envois), self)
                monde.envois.append(kw)
                monde.messages[m.id] = m
                return m

            async def fetch_message(self, mid):
                if mid not in monde.messages:
                    raise discord.NotFound(Obj(status=404, reason="x"), "x")
                return monde.messages[mid]
        self.salon = Salon()
        self.g = Obj(id=1, get_channel=lambda cid: self.salon if cid == 77 else None)

        async def salon(_g):
            return self.salon

        async def epargne(_g, membre_id):
            return membre_id == 3

        def carte(g, membre_id, n, points, evts):
            self.cartes.append((membre_id, n, points, len(evts)))
            return ("carte", membre_id, n)
        registre.setup(get_db=get_db, log=lambda *a: None, apres_grave=lambda g, m: self.vus.append((g, m)))
        registre._derniers.clear()
        V.setup(get_db=get_db, salon=salon, carte=carte, bot=Obj(get_guild=lambda gid: self.g), epargne=epargne,
                log=lambda *a: None)
        asyncio.run(registre.init_db())
        asyncio.run(V.init_db())

    async def ecrire(self, membre, t, type_, g):
        async with self.get_db() as db:
            await db.execute("INSERT INTO registre (guild_id, quand, categorie, type, membre_id, texte, gravite)"
                             " VALUES (1,?,?,?,?,?,?)", (t, "Modération", type_, membre, f"{type_} à {t}", g))
            await db.commit()


def test_V2_une_carte_mise_a_jour_puis_retiree_par_gere(tmp_path):
    m = Monde(tmp_path)
    t = 2_000_000_000

    async def scenario():
        await m.ecrire(7, t, "mod.warn", 1)
        await m.ecrire(7, t + 100, "mod.warn", 1)
        rien = await V.examiner(1, 7, maintenant=t + 200)
        await m.ecrire(7, t + 300, "mod.mute", 2)
        premiere = await V.examiner(1, 7, maintenant=t + 400)
        apres_premiere = (len(m.envois), len(m.edits))
        await m.ecrire(7, t + 500, "mod.warn", 1)
        maj = await V.examiner(1, 7, maintenant=t + 600)
        apres_maj = (len(m.envois), len(m.edits))
        ouvertes = await V.ouvertes(1)
        geree = await V.gerer(1, 7, 2, maintenant=t + 700)
        apres = await V.examiner(1, 7, maintenant=t + 800)
        for k in range(3):
            await m.ecrire(7, t + 1000 + k * 100, "mod.warn", 1)
        nouvelle = await V.examiner(1, 7, maintenant=t + 1400)
        await m.ecrire(3, t, "mod.ban", 3)
        await m.ecrire(3, t + 50, "mod.ban", 3)
        direction = await V.examiner(1, 3, maintenant=t + 100)
        return rien, premiere, apres_premiere, maj, apres_maj, ouvertes, geree, apres, nouvelle, direction
    rien, premiere, apres_premiere, maj, apres_maj, ouvertes, geree, apres, nouvelle, direction = asyncio.run(scenario())
    assert rien is None, "deux avertissements : pas d'alerte"
    assert premiere is not None and apres_premiere == (1, 0) and m.envois[0]["view"] == ("carte", 7, 3)
    assert maj.id == premiere.id and apres_maj == (1, 1), "une seule carte, mise à jour"
    assert [o["membre_id"] for o in ouvertes] == [7]
    assert geree == (77, premiere.id), "« Géré » rend la carte à retirer"
    assert apres is None, "le compteur repart de zéro"
    assert nouvelle is not None and nouvelle.id != premiere.id and m.cartes[-1][1:3] == (3, 3), "seuls les nouveaux comptent"
    assert direction is None, "direction et fondateur : mis à part"


def test_V3_le_journal_previent_pour_le_grave_seulement(tmp_path):
    m = Monde(tmp_path)

    async def scenario():
        await registre.noter(1, "Membres", "member.join", "Arrivée", membre_id=7)
        await registre.noter(1, "Modération", "mod.warn", "Avertissement", membre_id=7, auteur_id=2)
        await registre.noter(1, "Modération", "mod.warn", "Avertissement sans membre")
        rows = await registre.lire(1)
        return rows
    rows = asyncio.run(scenario())
    assert m.vus == [(1, 7)], "seul un évènement grave qui vise un membre déclenche l'examen"
    assert {r["type"]: r["gravite"] for r in rows} == {"mod.warn": 1, "member.join": 0}


def test_V4_un_seul_examen_a_la_fois_par_membre(tmp_path, monkeypatch):
    Monde(tmp_path)
    appels = []

    async def examiner(g, membre):
        appels.append((g, membre))
    monkeypatch.setattr(V, "examiner", examiner)
    monkeypatch.setattr(V, "ATTENTE", 0.01)

    async def scenario():
        V.planifier(1, 7)
        V.planifier(1, 7)
        V.planifier(1, 8)
        await asyncio.sleep(0.05)
        V.planifier(1, 7)
        await asyncio.sleep(0.05)
    asyncio.run(scenario())
    assert sorted(appels) == [(1, 7), (1, 7), (1, 8)], "les rafales d'un même instant ne font qu'un examen"
