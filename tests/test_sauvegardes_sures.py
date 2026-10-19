"""19/10/2026 (audit des réseaux sociaux) : un fichier illisible était lu comme VIDE, puis la sauvegarde
suivante l'écrasait — abonnements perdus, historique effacé et vidéos republiées. Et le relais X
publiait ce que renvoyaient des miroirs Nitter inconnus."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

import social_media as S
import stockage
import tracking_layer as T

RACINE = Path(__file__).resolve().parent.parent


def test_S1_un_fichier_abime_n_est_jamais_lu_comme_vide(tmp_path):
    f = tmp_path / "a.json"
    stockage.ecrire_json_sur(f, "[1, 2]")
    stockage.ecrire_json_sur(f, "[1, 2, 3]")
    assert stockage.lire_json_sur(f) == [1, 2, 3]
    f.write_text("{tronqué", encoding="utf-8")
    assert stockage.lire_json_sur(f) == [1, 2], "la version d'avant prend le relais"
    (tmp_path / "a.json.bak").write_text("{abîmé", encoding="utf-8")
    with pytest.raises(stockage.Illisible):
        stockage.lire_json_sur(f)
    assert stockage.lire_json_sur(tmp_path / "absent.json") is None
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob("*.baktmp"))


def test_S2_historique_illisible_rien_n_est_republie_ni_reecrit(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "DATA_DIR", tmp_path)
    for ens in (T._loaded_guilds, T._illisibles):
        ens.discard(9)
    T._cache.pop(9, None)
    (tmp_path / "9.json").write_text("{abîmé", encoding="utf-8")
    assert asyncio.run(T.was_posted(9, "youtube", "chaine", "abc")) is True, "dans le doute, on ne republie rien"
    asyncio.run(T._save_guild(9))
    assert (tmp_path / "9.json").read_text(encoding="utf-8") == "{abîmé", "rien n'est écrit par-dessus"


def test_S3_abonnements_illisibles_jamais_ecrases(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_subs_path", lambda gid: tmp_path / f"subs_{gid}.json")
    monkeypatch.setattr(S, "_anns_path", lambda gid: tmp_path / f"anns_{gid}.json")
    (tmp_path / "subs_9.json").write_text("{abîmé", encoding="utf-8")
    mgr = S.SocialMediaManager()
    asyncio.run(mgr.load_guild(9))
    assert 9 not in mgr._loaded_guilds and 9 in mgr._illisibles
    with pytest.raises(stockage.Illisible):
        asyncio.run(mgr._save_subs(9))
    assert (tmp_path / "subs_9.json").read_text(encoding="utf-8") == "{abîmé"


def test_S4_le_relais_x_ne_publie_rien_tel_quel_venu_d_un_tiers():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    fn = next(ast.unparse(n) for n in ast.parse(src).body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "check_twitter_feeds")
    assert "NITTER" not in src and "syndication.twitter.com/srv" not in fn
    assert "f'https://x.com/{username}/status/{tweet_id}'" in fn, "lien reconstruit depuis l'identifiant"
    assert "_escape_md(tweet_text" in fn and "pbs.twimg.com" in fn


def test_S5_une_reservation_inachevee_ne_bloque_pas_le_post(tmp_path):
    import publications as PUB
    from conftest_discord import base
    get_db, *_ = base(tmp_path)
    PUB.setup(get_db=get_db, log=lambda *a: None)

    async def scenario():
        await PUB.init_db()
        assert await PUB.reserver(1, "tiktok", "v1", "page")
        assert not await PUB.deja(1, "tiktok", "v1"), "réservée mais jamais envoyée : à republier"
        await PUB.confirmer(1, "tiktok", "v1", 55, 9)
        assert await PUB.deja(1, "tiktok", "v1")
    asyncio.run(scenario())


def test_S6_toute_publication_passe_par_la_reservation():
    arbre = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
    appelants = set()
    for fn in ast.walk(arbre):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_publier_social":
                    appelants.add(fn.name)
    assert appelants == {"_publier_reserve", "_annoncer_video_youtube"}, appelants


def test_S7_une_panne_twitch_ne_supprime_pas_l_annonce_d_un_live(tmp_path, monkeypatch):
    class Reponse:
        status = 503

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        def get(self, *a, **k):
            return Reponse()
    tw = S.TwitchAdapter(client_id="id", client_secret="secret")
    tw._session, tw._token, tw._token_expires_at = Session(), "jeton", 10 ** 12
    with pytest.raises(RuntimeError):
        asyncio.run(tw.fetch_posts("streamer"))
    live = S.SocialPost(platform=S.Platform.TWITCH, handle="streamer", post_id="42", post_type=S.PostType.LIVE,
                        title="", url="")
    assert asyncio.run(tw.is_post_active(live)) is True, "une panne n'est pas « fin du live »"

    monkeypatch.setattr(S, "_anns_path", lambda gid: tmp_path / f"anns_{gid}.json")
    supprimees = []

    async def supprimer(ann):
        supprimees.append(ann.post_id)
        return True

    class Termine:
        async def is_post_active(self, post):
            return False
    mgr = S.SocialMediaManager(delete_callback=supprimer)
    mgr._adapters[S.Platform.TWITCH] = Termine()
    ann = S.Announcement(sub_id="s", post_id="42", platform=S.Platform.TWITCH, handle="streamer", guild_id=9,
                         discord_channel_id=1, discord_message_id=2, post_url="", post_title="",
                         post_type=S.PostType.LIVE, posted_at="", last_checked_at="")
    asyncio.run(mgr.cleanup_announcement(ann, sauver=False))
    assert not supprimees, "un seul constat d'absence ne suffit pas"
    asyncio.run(mgr.cleanup_announcement(ann, sauver=False))
    assert supprimees == ["42"]
