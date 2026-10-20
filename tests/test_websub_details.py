"""20/10/2026 (audit 6 #20) : l'annonce WebSub partait sans description ni avatar de la chaine."""
from __future__ import annotations

import ast
import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
FLUX = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
 xmlns:media="http://search.yahoo.com/mrss/"><entry><yt:videoId>abc</yt:videoId><title>Maj</title>
<media:group><media:description>Nouvelle mise a jour du jeu !
Abonne-toi pour plus</media:description></media:group></entry></feed>"""


def _ns(**autres):
    ns = {"ET": ET, "_SOCIAL": {}, **autres}
    for n in ARBRE.body:
        nom = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in ("_NS_YT", "_description_entree", "_annoncer_websub"):
            exec(ast.unparse(n), ns)  # noqa: S102
    return ns


def test_W1_la_description_du_flux_sans_les_appels_a_s_abonner():
    ns = _ns()
    entree = ET.fromstring(FLUX).find("atom:entry", ns["_NS_YT"])
    assert ns["_description_entree"](entree, ns["_NS_YT"]) == "Nouvelle mise a jour du jeu !"


def test_W2_websub_lit_les_details_une_fois_et_les_passe_a_chaque_serveur():
    lectures, annonces = [], []

    async def feeds():
        return [("g1", {"id": "UC1"}, "c1"), ("g2", {"id": "UC1"}, "c2"), ("g3", {"id": "UC2"}, "c3")]

    async def details(uc, vid):
        lectures.append((uc, vid))
        return "desc", "avatar.png"

    async def annoncer(guild, feed, cible, vid, titre, description="", chemin="", avatar=None):
        annonces.append((guild, description, avatar, chemin))
        return True
    ns = _ns(_feeds_youtube=feeds, _details_websub=details, _annoncer_video_youtube=annoncer,
             _matches_keyword_filter=lambda t, f: True)
    assert asyncio.run(ns["_annoncer_websub"]("UC1", {"video_id": "abc", "titre": "Maj"}))
    assert lectures == [("UC1", "abc")]
    assert annonces == [("g1", "desc", "avatar.png", "websub"), ("g2", "desc", "avatar.png", "websub")]


def test_W3_les_abonnements_du_panneau_ont_aussi_l_annonce_instantanee():
    """Audit 6 #4 : WebSub ne couvrait que l'ancienne configuration."""
    import social_media as S
    recus = []
    sub = S.Subscription(sub_id="s1", guild_id=1, platform=S.Platform.YOUTUBE, handle="@RellGames",
                         display_name="Rell", target_channel_id=5)

    class Mgr:
        def abonnements_youtube(self):
            return [("UC1", sub), ("UC9", sub)]

        async def publier_post(self, s, post):
            recus.append((s.sub_id, post.post_id, post.handle, s.matches(post)))
            return True

    async def feeds():
        return []
    ns = _ns(_feeds_youtube=feeds, social2026=S)
    ns["_SOCIAL"]["mgr"] = Mgr()
    assert asyncio.run(ns["_annoncer_websub"]("UC1", {"video_id": "abc", "titre": "Maj"}))
    assert recus == [("s1", "yt:video:abc", "@RellGames", True)]


def test_W4_seules_les_chaines_deja_resolues_sont_suivies_sans_requete():
    import social_media as S
    m = S.SocialMediaManager()
    lecteur = S.YouTubeRSSAdapter()
    lecteur._cid["rellgames"] = "UCabcdefghijklmnopqrstuv"
    m.register_adapter(lecteur)
    subs = [S.Subscription(sub_id=f"s{i}", guild_id=1, platform=S.Platform.YOUTUBE, handle=h,
                           display_name=h, target_channel_id=5)
            for i, h in enumerate(("@RellGames", "@inconnu", "UCzzzzzzzzzzzzzzzzzzzzzz"))]
    m._subs = {1: {s.sub_id: s for s in subs}}
    assert sorted(uc for uc, _ in m.abonnements_youtube()) == ["UCabcdefghijklmnopqrstuv",
                                                              "UCzzzzzzzzzzzzzzzzzzzzzz"]


def test_W5_stats_montre_l_etat_de_websub_sans_rien_d_identifiant():
    import json as _json

    import health_server as H
    reponse = asyncio.run(H._stats_handler(None))
    donnees = _json.loads(reponse.body)
    assert set(donnees["websub"]) == {"actif", "abonnes", "notifications", "annonces", "rejetees"}
    assert all(isinstance(v, (bool, int)) for v in donnees["websub"].values())
