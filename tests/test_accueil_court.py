"""24/10/2026, le fondateur : « quand quelqu'un arrive… ça fait un gros message énorme. Fais en sorte que ça fasse un
petit texte… ça mentionne la personne, bienvenue dans le serveur sous forme de texte par le bot, c'est tout. Avec le
nombre de membres qu'on a au total. »"""
from __future__ import annotations

import ast
from pathlib import Path

import discord

import i18n
from conftest_discord import Obj
from faux_serveur import Monde, run

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _ns(conf, envoyes):
    ns = {"discord": discord, "i18n_module": i18n, "print": lambda *a, **k: None}
    for n in ARBRE.body:
        if getattr(n, "name", None) in ("_handle_welcome", "_nombre_membres"):
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt

    async def cfg(_gid):
        return conf

    async def suivre(gid, cid, mid):
        envoyes.append((gid, cid, mid))

    async def langue(*_a, **_k):
        return "fr"
    ns.update(cfg=cfg, _track_welcome_msg=suivre, _defer_welcome_during_raid=lambda *a: False,
              _logerr=lambda *a, **k: None)
    i18n_lang = i18n.lang_of
    i18n.lang_of = langue
    return ns, i18n_lang


def test_A1_une_ligne_de_texte_mention_bienvenue_nombre_de_membres():
    g = Monde()
    g.member_count = 1234
    chat = g.nom("💬chat")
    suivis = []
    ns, remettre = _ns({"welcome_enabled": True, "welcome_channel": chat.id}, suivis)
    try:
        m = g.membre(21)
        run(ns["_handle_welcome"](m))
    finally:
        i18n.lang_of = remettre
    (mid, contenu, kw), = chat.envois
    assert contenu == "👋 Bienvenue <@21> sur le serveur ! Nous sommes maintenant **1 234** membres."
    assert "\n" not in contenu, "une seule ligne"
    assert "view" not in kw and "embed" not in kw, "pas de carte, pas de bouton : du texte"
    am = kw["allowed_mentions"]
    assert am.users == [m] and am.everyone is False and am.roles is False, "lui seul est mentionné"
    assert suivis == [(g.id, chat.id, mid)], "la ligne est retirée plus tard par la purge"


def test_A2_dans_un_post_de_forum_aussi_et_rien_si_l_accueil_est_coupe():
    g = Monde()
    g.member_count = 7
    post = g.nouveau_fil(g.nom("💬chat"), "Chat")
    ns, remettre = _ns({"welcome_enabled": True, "welcome_channel": post.id}, [])
    try:
        run(ns["_handle_welcome"](g.membre(22)))
        assert post.envois and "**7** membres" in post.envois[-1][0]
        ns2, _ = _ns({"welcome_enabled": False, "welcome_channel": post.id}, [])
        avant = len(post.envois)
        run(ns2["_handle_welcome"](g.membre(23)))
        assert len(post.envois) == avant
    finally:
        i18n.lang_of = remettre


def test_A3_la_traduction_dans_les_six_langues_et_le_reste_branche():
    for lang in ("fr", "en", "es", "de", "it", "pt"):
        t = i18n.t("welcome.short", lang, user="<@1>", count="9")
        assert "<@1>" in t and "**9**" in t and "\n" not in t, lang
        assert "**3**" in i18n.t("welcome.wave", lang, n=3, count="9"), lang
    assert "_welcome_quick_buttons" not in SRC, "plus de boutons sous l'accueil"
    purge = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "welcome_cleanup_task")
    assert "get_channel_or_thread" in purge, "la purge retrouve une ligne postée dans un post de forum"
    assert '"welcome_cleanup_task",' in SRC.split("_SUPERVISED_LOOP_NAMES = [", 1)[1].split("]", 1)[0]
    assert "bot.add_view(AccueilLangueView())" in SRC, "les anciennes cartes gardent leur bouton vivant"
    _ = Obj
