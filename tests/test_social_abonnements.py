"""20/10/2026 (audit 6 #16) : la memoire « deja vu » du lecteur RSS etait commune a tous les
abonnements d'un meme compte : le premier lu privait les autres de chaque nouveau post."""
from __future__ import annotations

import asyncio

import social_media as S


def _post(pid):
    return S.SocialPost(platform=S.Platform.TWITTER, handle="rell", post_id=pid, post_type=S.PostType.POST,
                        title=pid, url="https://x.com/rell/status/" + pid)


def test_A1_deux_abonnements_au_meme_compte_recoivent_chacun_le_nouveau_post():
    flux = [_post("2"), _post("1")]
    lecteur = S.RSSHubAdapter(S.Platform.TWITTER, base_url="https://rsshub.exemple")

    async def items(_handle):
        return list(flux)
    lecteur._fetch_items = items

    async def scenario():
        assert len(await lecteur.fetch_posts("rell", abonne="a")) == 2
        assert len(await lecteur.fetch_posts("rell", abonne="b")) == 2, "le second abonnement a sa base"
        flux.insert(0, _post("3"))
        return ([p.post_id for p in await lecteur.fetch_posts("rell", abonne="a")],
                [p.post_id for p in await lecteur.fetch_posts("rell", abonne="b")])
    assert asyncio.run(scenario()) == (["3"], ["3"])


def test_A2_une_alerte_par_panne_puis_reamorcee_au_retablissement():
    """20/10/2026 (audit 6 #14) : « API … indisponible » revenait toutes les 24 h, a vie."""
    import ast
    import time
    from pathlib import Path

    from conftest_discord import Obj
    alertes = []

    async def log_event(*a, **k):
        alertes.append(k.get("title_override"))
    ns = {"time": time, "_api_warning_state": {}, "_load_api_warning_state": lambda: None,
          "_save_api_warning_state": lambda: None, "bot": None, "print": print,
          "ulogger2026": Obj(log_event=log_event, EventType=Obj(BOT_INFO="bot.info"))}
    arbre = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
    for n in arbre.body:
        if getattr(n, "name", "") in ("_warn_api_dead", "_api_retablie"):
            exec(ast.unparse(n), ns)  # noqa: S102
    g = Obj(id=1)

    async def scenario():
        for _ in range(3):
            await ns["_warn_api_dead"](g, "tiktok", "bloque")
        ns["_api_retablie"](g, "tiktok")
        await ns["_warn_api_dead"](g, "tiktok", "bloque")
    asyncio.run(scenario())
    assert len(alertes) == 2, alertes
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    assert 'if not _page_live_due(f"tiktok_page:{username}", 1800):' in src


def test_A3_la_boucle_ne_lit_plus_rien_pour_rien():
    """Audit 6 #8/#15 : avatar YouTube cherche chaque minute sans rien a publier ; liens des
    createurs lus en base pour chaque serveur, meme jamais regle."""
    import ast
    from pathlib import Path
    src = ast.unparse(ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")))
    assert "yt_avatar = await fetch_avatar_url('youtube', channel_id, session) if posts_to_publish else None" in src


def test_A4_la_boucle_rend_sa_connexion_et_garde_les_modifications_du_panneau():
    """Audit 5 #25 : connexion et curseur ouverts pendant tous les appels reseau ; liste YouTube
    lue au debut du passage reecrite par-dessus une modification faite entre-temps."""
    import ast
    from pathlib import Path
    src = ast.unparse(ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")))
    boucle = src[src.index("async def check_social_feeds"):]
    boucle = boucle[:boucle.index("\nasync def ") if "\nasync def " in boucle else None]
    assert "lignes = await cursor.fetchall()" in boucle and "async for row in cursor" not in boucle
    yt = src[src.index("async def check_youtube_feeds"):]
    assert "await db_set(guild.id, 'ads_youtube_feeds', actuels)" in yt
    assert "await db_set(guild.id, 'ads_youtube_feeds', feeds)" not in yt
