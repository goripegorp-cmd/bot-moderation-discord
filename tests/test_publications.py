"""19/10/2026 : « le bot publie deux fois les annonces… ça a pris plus de 10 minutes… revois
entièrement le système de publication des réseaux sociaux, que le tracking soit puissant »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import hmac
import json
from pathlib import Path

import aiosqlite

import publications as PUB
import social_media
import tracking_layer
import websub_youtube as W
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
UC = "UC" + "a" * 22


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def _base(tmp_path, instance="A"):
    chemin = tmp_path / "p.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    PUB.setup(get_db=get_db, instance=instance, log=lambda *a: None)
    asyncio.run(PUB.init_db())
    return get_db


def test_P1_une_seule_publication_meme_a_plusieurs(tmp_path):
    _base(tmp_path)
    t = 2_000_000_000

    async def scenario():
        en_meme_temps = await asyncio.gather(*(PUB.reserver(1, "youtube", "vid1", "rss", t) for _ in range(5)))
        autre_chemin = await PUB.reserver(1, "youtube", "yt:video:vid1", "abonnement", t + 1)
        await PUB.annuler(1, "youtube", "vid1")
        apres_echec = await PUB.reserver(1, "youtube", "vid1", "websub", t + 2)
        await PUB.confirmer(1, "youtube", "vid1", 555, 77)
        confirme = await PUB.reserver(1, "youtube", "vid1", "rss", t + 9999)
        await PUB.annuler(1, "youtube", "vid1")
        toujours = await PUB.deja(1, "youtube", "vid1")
        bloque = await PUB.reserver(1, "youtube", "vid2", "rss", t)
        repris_trop_tot = await PUB.reserver(1, "youtube", "vid2", "rss", t + 60)
        repris = await PUB.reserver(1, "youtube", "vid2", "rss", t + PUB.REPRISE + 1)
        await PUB.reserver(1, "youtube", "vieille", "ancienne", t)
        await PUB.confirmer(1, "youtube", "vieille", 0, 0)
        await PUB.annuler(1, "youtube", "vieille")
        vieille = await PUB.deja(1, "youtube", "vieille")
        return en_meme_temps, autre_chemin, apres_echec, confirme, toujours, bloque, repris_trop_tot, repris, vieille
    r = asyncio.run(scenario())
    en_meme_temps, autre_chemin, apres_echec, confirme, toujours, bloque, repris_trop_tot, repris, vieille = r
    assert sorted(en_meme_temps) == [False] * 4 + [True], "cinq boucles en même temps : une seule envoie"
    assert not autre_chemin, "le gestionnaire (yt:video:…) et le panneau (…) : le même post"
    assert apres_echec, "un envoi raté rend la place : le passage suivant réessaie"
    assert not confirme and toujours, "un post confirmé n'est jamais republié ni rendu"
    assert bloque and not repris_trop_tot and repris, "une instance arrêtée en plein envoi : reprise après 10 min"
    assert vieille, "une vieille vidéo notée sans message reste notée"


def test_P2_deux_instances_partagent_la_base(tmp_path):
    get_db = _base(tmp_path, "instance-A")

    async def scenario():
        a = await PUB.reserver(1, "youtube", "vid9", "rss")
        PUB.setup(get_db=get_db, instance="instance-B", log=lambda *x: None)
        b = await PUB.reserver(1, "youtube", "vid9", "websub")
        return a, b
    assert asyncio.run(scenario()) == (True, False), "pendant un redéploiement, la seconde instance passe son tour"


class Requete:
    def __init__(self, methode="GET", query=None, corps=b"", entetes=None):
        self.method, self.query, self._corps = methode, dict(query or {}), corps
        self.headers = dict(entetes or {})
        self.content_length = len(corps)

    async def read(self):
        return self._corps


def _atom(vid, uc, publie):
    return (f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
            f"<entry><id>yt:video:{vid}</id><yt:videoId>{vid}</yt:videoId><yt:channelId>{uc}</yt:channelId>"
            f"<title>Nouvelle vidéo Rell Seas</title><published>{publie}</published><updated>{publie}</updated></entry></feed>").encode()


def test_P3_notification_instantanee_signee(tmp_path):
    annonces = []

    async def chaines():
        return {UC}

    async def annoncer(uc, video):
        annonces.append((uc, video["video_id"], video["titre"]))
        return True
    W.setup(secret="s3cret", base_url="https://bot.exemple", chaines=chaines, annoncer=annoncer, log=lambda *a: None)
    signe = lambda corps: "sha1=" + hmac.new(b"s3cret", corps, hashlib.sha1).hexdigest()
    t = 2_000_000_000
    frais, vieux = _atom("vidA", UC, "2033-05-18T03:30:00+00:00"), _atom("vidB", UC, "2020-01-01T00:00:00+00:00")
    inconnue = _atom("vidC", "UC" + "b" * 22, "2033-05-18T03:30:00+00:00")

    async def scenario():
        r = {}
        r["verif_ok"] = await W.verification(Requete(query={"hub.mode": "subscribe", "hub.topic": W.sujet(UC),
                                                             "hub.challenge": "abc123", "hub.lease_seconds": "432000"}))
        r["verif_inconnue"] = await W.verification(Requete(query={"hub.mode": "subscribe", "hub.topic": W.sujet("UC" + "b" * 22),
                                                                   "hub.challenge": "abc"}))
        r["sans_signature"] = await W.notification(Requete("POST", corps=frais), maintenant=t)
        r["fausse"] = await W.notification(Requete("POST", corps=frais, entetes={"X-Hub-Signature": "sha1=00"}), maintenant=t)
        r["vieille"] = await W.notification(Requete("POST", corps=vieux, entetes={"X-Hub-Signature": signe(vieux)}), maintenant=t)
        r["autre"] = await W.notification(Requete("POST", corps=inconnue, entetes={"X-Hub-Signature": signe(inconnue)}), maintenant=t)
        r["bonne"] = await W.notification(Requete("POST", corps=frais, entetes={"X-Hub-Signature": signe(frais)}), maintenant=t)
        await asyncio.sleep(0.05)
        return r
    r = asyncio.run(scenario())
    assert r["verif_ok"].status == 200 and r["verif_ok"].text == "abc123", "le hub vérifie l'abonnement"
    assert r["verif_inconnue"].status == 404, "une chaîne qu'on ne suit pas : refusée"
    assert r["sans_signature"].status == 202 and r["fausse"].status == 202
    assert r["vieille"].status == 204 and r["autre"].status == 204 and r["bonne"].status == 204
    assert annonces == [(UC, "vidA", "Nouvelle vidéo Rell Seas")], "seule la vraie notification, fraîche et suivie"
    assert W.etat()["rejetees"] == 2


def test_P4_abonnements_entretenus(tmp_path):
    envois = []

    class Session:
        def post(self, url, data, timeout):
            envois.append((url, data["hub.mode"], data["hub.topic"], data["hub.callback"]))

            class R:
                status = 202

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False
            return R()
    suivies = {UC}

    async def chaines():
        return set(suivies)
    W.setup(secret="s", base_url="https://bot.exemple", chaines=chaines, annoncer=lambda *a: None, log=lambda *a: None)

    async def scenario():
        a = await W.entretenir(Session(), maintenant=1000)
        b = await W.entretenir(Session(), maintenant=2000)
        c = await W.entretenir(Session(), maintenant=1000 + W.BAIL - 3600)
        suivies.clear()
        d = await W.entretenir(Session(), maintenant=5000)
        return a, b, c, d
    a, b, c, d = asyncio.run(scenario())
    assert (a["abonnements"], b["abonnements"], c["abonnements"]) == (1, 0, 1), "abonné, puis renouvelé un jour avant l'échéance"
    assert envois[0] == (W.HUB, "subscribe", W.sujet(UC), "https://bot.exemple/websub/youtube")
    assert envois[-1][1] == "unsubscribe" and d["suivies"] == 0, "une chaîne plus suivie : désabonnée"
    W.setup(secret="s", base_url="http://local", chaines=chaines, annoncer=lambda *a: None)
    assert not W.actif(), "sans adresse publique en https : rien n'est tenté"


def test_P5_annonce_unique_et_envoi_incertain_verifie(tmp_path):
    _base(tmp_path)
    envois, records, echecs = [], [], {"n": 0}

    class Salon:
        id, name = 77, "sneak-rellseas"

        def __init__(self):
            self.historique = []

        def history(self, limit=15):
            async def gen():
                for m in self.historique:
                    yield m
            return gen()
    salon = Salon()

    async def publier(s, profil, e):
        envois.append(e.url)
        if echecs["n"]:
            echecs["n"] -= 1
            if echecs.get("arrive"):
                s.historique.append(Obj(id=999, embeds=[Obj(url=e.url)], content=""))
            return None
        return Obj(id=1000 + len(envois))

    async def faux(*a, **k):
        return False

    async def record(*a, **k):
        records.append(a)
    import discord
    ns = {"tracking2026": Obj(was_posted=faux, record_post=record, prune_to_max=record), "publications": PUB,
          "discord": discord, "_YT_ICON": "", "now": lambda: None, "_publier_social": publier,
          "_logerr": lambda *a, **k: None, "_avertir_une_fois_par_jour": lambda c: False,
          "diag": Obj(event=lambda *a: None, warn=lambda *a: None), "bot": None}
    for nom in ("_deja_dans_le_salon", "_annoncer_video_youtube"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    annoncer = ns["_annoncer_video_youtube"]
    feed = {"id": UC, "name": "Rell Seas"}
    g = Obj(id=1)

    async def scenario():
        r = [await annoncer(g, feed, salon, "v1", "Titre", chemin="websub"),
             await annoncer(g, feed, salon, "v1", "Titre", chemin="rss")]
        echecs["n"] = 1
        r.append(await annoncer(g, feed, salon, "v2", "Titre"))
        r.append(await annoncer(g, feed, salon, "v2", "Titre"))
        echecs.update(n=1, arrive=True)
        r.append(await annoncer(g, feed, salon, "v3", "Titre"))
        r.append(await annoncer(g, feed, salon, "v3", "Titre"))
        return r
    r = asyncio.run(scenario())
    assert r == [True, False, False, True, True, False]
    assert envois.count("https://www.youtube.com/watch?v=v1") == 1, "la notification et le relevé : un seul message"
    assert envois.count("https://www.youtube.com/watch?v=v2") == 2, "un envoi raté est réessayé"
    assert envois.count("https://www.youtube.com/watch?v=v3") == 1, "arrivé malgré l'erreur : vu dans le salon, jamais renvoyé"


def test_P6_le_gestionnaire_reserve_aussi(tmp_path, monkeypatch):
    _base(tmp_path)
    monkeypatch.setattr(social_media, "DATA_DIR", tmp_path)
    mgr = social_media.SocialMediaManager()
    envoyes = []

    async def poster(sub, post):
        envoyes.append(post.post_id)
        return 42
    mgr.set_post_callback(poster)
    mgr.set_reservation(PUB.reserver, PUB.confirmer, PUB.annuler)
    post = social_media.SocialPost(platform=social_media.Platform.YOUTUBE, handle="rell", post_id="yt:video:vX",
                                   post_type=social_media.PostType.VIDEO, title="t", url="u")

    class Adaptateur:
        platform = social_media.Platform.YOUTUBE

        async def fetch_posts(self, handle):
            return [post]
    mgr.register_adapter(Adaptateur())
    sub = Obj(platform=social_media.Platform.YOUTUBE, handle="rell", guild_id=1, target_channel_id=77,
              matches=lambda p: True, sub_id="s1")

    async def scenario():
        mgr._loaded_guilds.add(1)
        mgr._anns[1] = {}
        await PUB.reserver(1, "youtube", "vX", "websub")
        await PUB.confirmer(1, "youtube", "vX", 7, 77)
        return await mgr.poll_subscription(sub)
    assert asyncio.run(scenario()) == 0 and envoyes == [], "déjà publiée par un autre chemin : le gestionnaire passe son tour"


def test_P7_historique_ecrit_d_un_bloc(tmp_path, monkeypatch):
    monkeypatch.setattr(tracking_layer, "DATA_DIR", tmp_path)
    tracking_layer._cache.clear()
    tracking_layer._loaded_guilds.clear()

    async def scenario():
        await tracking_layer.record_post(5, "youtube", UC, "v1", channel_id=1, message_id=2)
        return await tracking_layer.was_posted(5, "youtube", UC, "v1")
    assert asyncio.run(scenario())
    fichier = tmp_path / "5.json"
    assert json.loads(fichier.read_text(encoding="utf-8"))[0]["post_id"] == "v1"
    assert not (tmp_path / "5.json.tmp").exists(), "fichier temporaire, puis remplacement : jamais de JSON tronqué"
    assert "_ecrire_atomique" in Path(tracking_layer.__file__).read_text(encoding="utf-8")


def test_P8_les_adresses_websub_par_http():
    from aiohttp.test_utils import TestClient, TestServer

    import health_server
    annonces = []

    async def chaines():
        return {UC}

    async def annoncer(uc, video):
        annonces.append(video["video_id"])
        return True
    W.setup(secret="k", base_url="https://bot.exemple", chaines=chaines, annoncer=annoncer, log=lambda *a: None)
    corps = _atom("vidH", UC, "2099-01-01T00:00:00+00:00".replace("2099", "2026"))

    async def scenario():
        async with TestClient(TestServer(health_server.construire_app())) as client:
            v = await client.get("/websub/youtube", params={"hub.mode": "subscribe", "hub.topic": W.sujet(UC), "hub.challenge": "xyz"})
            texte = await v.text()
            n = await client.post("/websub/youtube", data=corps,
                                  headers={"X-Hub-Signature": "sha1=" + hmac.new(b"k", corps, hashlib.sha1).hexdigest(),
                                           "Content-Type": "application/atom+xml"})
            await asyncio.sleep(0.05)
            return v.status, texte, n.status
    statut, texte, n = asyncio.run(scenario())
    assert (statut, texte) == (200, "xyz") and n == 204
