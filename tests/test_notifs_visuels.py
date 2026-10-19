"""19/10/2026 : « un rôle ping… personne n'est ping au début… un bouton… ils cochent » ;
« pareil sur tous les sneaks de Rell Seas » ; « un vrai motion design pour tous les menus »."""
from __future__ import annotations

import asyncio
from pathlib import Path

import discord

import notifs
import visuels
from conftest_discord import Guilde, Membre, Obj, Salon

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")


def test_N1_un_role_par_sujet_cree_a_la_demande_personne_dedans():
    conf = {}

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v
    notifs.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    salon = Salon(42, "🌊・rell-seas-news")
    g = Guilde(salon)
    r = asyncio.run(notifs.role(g, notifs.cle_salon(42)))
    assert r.name == "🔔 Rell Seas News" and conf["notif_role_salon42"] == r.id
    assert asyncio.run(notifs.role(g, "sondages")).name == "🔔 Sondages"
    assert asyncio.run(notifs.role(g, "inconnu")) is None
    assert notifs.mentions(r).roles == [r] and notifs.ping(None) == ""


def test_N2_le_bouton_donne_puis_reprend_le_role():
    conf, ajoute, retire = {}, [], []

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v
    notifs.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    g = Guilde()
    m = Membre()

    async def add_roles(r, reason=None):
        m.roles.append(r)
        ajoute.append(r)

    async def remove_roles(r, reason=None):
        m.roles.remove(r)
        retire.append(r)
    m.add_roles, m.remove_roles = add_roles, remove_roles
    suivis = []

    async def suivi(texte, **kw):
        suivis.append(texte)

    async def defer(**kw):
        return None
    for _ in range(2):
        i = Obj(guild=g, user=m, response=Obj(defer=defer), followup=Obj(send=suivi))
        asyncio.run(notifs.BoutonNotif("sondages").callback(i))
    assert suivis == ["Tu recevras les nouveaux sondages.", "Tu ne recevras plus les nouveaux sondages."]
    assert len(ajoute) == len(retire) == 1


def test_N3_chaque_publication_des_reseaux_previent_son_role_avec_le_bouton():
    assert SRC.count("await _publier_social(") == 8
    assert "webhook_send(target_channel, 'youtube', embed=e)" not in SRC
    assert "ping, role, vue = await _ping_social(chan)" in SRC


def test_V1_bandeau_anime_ou_titre_si_rien_n_est_servi(tmp_path, monkeypatch):
    visuels.setup(base_url="", log=lambda *a: None)
    assert isinstance(visuels.bandeau("sondages", "Sondages"), discord.ui.TextDisplay)
    monkeypatch.setattr(visuels, "DOSSIER", tmp_path)
    (tmp_path / "sondages.gif").write_bytes(b"GIF89a")
    visuels.setup(base_url="https://bot.example/", log=lambda *a: None)
    assert isinstance(visuels.bandeau("sondages", "Sondages"), discord.ui.TextDisplay),         "pas d'image avant d'avoir vérifié qu'elle est servie"
    monkeypatch.setattr(visuels, "_servi", True)
    b = visuels.bandeau("sondages", "Sondages")
    assert isinstance(b, discord.ui.MediaGallery)
    assert b.items[0].media.url == f"https://bot.example/v/sondages.gif?v={visuels.VERSION}"
    assert visuels.url("absent") is None


def test_V2_le_serveur_ne_sert_que_les_images_du_dossier(tmp_path, monkeypatch):
    monkeypatch.setattr(visuels, "DOSSIER", tmp_path)
    (tmp_path / "a.gif").write_bytes(b"x")
    (tmp_path / "secret.py").write_text("x")
    assert visuels.fichier("a.gif") == tmp_path / "a.gif"
    for nom in ("secret.py", "../bot.py", "..\\bot.py", ".env", "absent.png"):
        assert visuels.fichier(nom) is None, nom
    hs = (Path(__file__).resolve().parent.parent / "health_server.py").read_text(encoding="utf-8")
    assert "app.router.add_get('/v/{nom}', _visuel_handler)" in hs


def test_V3_l_adresse_publique_est_verifiee_avant_d_afficher(tmp_path, monkeypatch):
    from aiohttp import web
    monkeypatch.setattr(visuels, "DOSSIER", tmp_path)
    (tmp_path / "a.gif").write_bytes(b"GIF89a")

    async def scenario(statut):
        async def image(_r):
            if statut != 200:
                return web.Response(status=statut)
            return web.Response(body=b"GIF89a", content_type="image/gif")
        app = web.Application()
        app.router.add_get("/v/{nom}", image)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        visuels.setup(base_url=f"http://127.0.0.1:{port}", log=lambda *a: None)
        try:
            return await visuels.verifier(essais=2, pause=0)
        finally:
            await runner.cleanup()
    assert asyncio.run(scenario(200)) is True and visuels.url("a") is not None
    assert asyncio.run(scenario(404)) is False and visuels.url("a") is None
