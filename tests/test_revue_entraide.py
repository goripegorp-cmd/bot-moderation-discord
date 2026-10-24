"""Revue complète du 24/10/2026 (« passe en revue tous les systèmes… chaque bouton, chaque interface… aucune erreur
et aucun problème ») — l'entraide, la FAQ, les liens des jeux, les guides, le panneau ❓aide, les suppressions
différées."""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

import discord
import pytest

import entraide as E
import faq
import zones
from conftest_discord import Obj, base
from faux_serveur import Forum, Monde, interaction, run, textes
from test_entraide import demande_valeurs, env, installe, publier  # noqa: F401 — la fixture `env` est réutilisée
from test_faq_tickets import Message as MessageFaq, faq_env  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom)


@pytest.fixture(autouse=True)
def _propre():
    for d in (E._REPONSES, E._REPERES, E._CARTES, E._ACTIVITE, E._VERIFIEES):
        d.clear()
    E._SUIVI.update(reponses=0, retirees_en_direct=0)
    yield
    faq.set_hooks()


def _reponse(g, fil, membre_id, a):
    m = fil.repondre(membre_id, a)
    m.guild = g
    return m


# ─── L'entraide ──────────────────────────────────────────────────────────────

def test_R1_les_reponses_sous_une_carte_gardent_la_demande_vivante(env):
    g, posts, _f = installe(env)
    aide = g.fils[posts["entraide"]]
    publier(g, g.membre(7), "aide")                      # aide : 24 h sans activité
    d = run(E.charger(1))
    t0 = time.time()
    run(E.entretenir(g, maintenant=t0))                  # les repères des cartes ouvertes
    r1 = _reponse(g, aide, 8, d["fil_id"])
    assert run(E.sur_message(r1)) == 1, "une réponse à la carte"
    r2 = _reponse(g, aide, 9, r1.id)
    assert run(E.sur_message(r2)) == 1, "une réponse à une réponse"
    assert run(E.sur_message(_reponse(g, aide, 9, 123456))) == 0, "ailleurs : rien"
    run(E._ecrire("UPDATE entraide_demandes SET maj=? WHERE id=1", (int(t0) - 20 * 3600,)))
    E._ACTIVITE.clear()
    run(E.sur_message(_reponse(g, aide, 8, d["fil_id"])))
    assert run(E.charger(1))["maj"] >= int(t0) - 1, "la réponse a fait avancer l'activité"
    assert run(E.entretenir(g, maintenant=t0 + 5 * 3600))["expirees"] == 0, "on discute encore : elle reste"
    maj = run(E.charger(1))["maj"]
    run(E.sur_message(_reponse(g, aide, 8, d["fil_id"])))
    assert run(E.charger(1))["maj"] == maj, "une écriture toutes les 5 minutes au plus"


def test_R2_une_carte_supprimee_par_un_moderateur_part_avec_ses_mots_et_ses_reponses(env):
    g, posts, _f = installe(env)
    aide = g.fils[posts["entraide"]]
    publier(g, g.membre(7), "aide")
    run(E.rejoindre(interaction(g, g.membre(8)), 1))     # un mot du bot sous la carte
    d = run(E.charger(1))
    mot = aide.messages[-1].id
    t0 = time.time()
    run(E.entretenir(g, maintenant=t0))
    r = _reponse(g, aide, 9, d["fil_id"])
    run(E.sur_message(r))
    run(aide.get_partial_message(d["fil_id"]).delete())
    assert run(E.sur_suppression(g.id, d["fil_id"])) == 1 and run(E.charger(1))["statut"] == "retiree"
    assert run(E.sur_suppression(g.id, d["fil_id"])) == 0, "une fois"
    assert E.releve() == {"cartes_suivies": 0, "reponses": 1, "retirees_en_direct": 1}
    bilan = run(E.entretenir(g, maintenant=t0 + 120))
    assert bilan["effacees"] == 1 and {mot, r.id} <= g.effaces, "le mot du bot et la réponse partent aussi"
    assert run(E.charger(1))["supprime"] == 1


def test_R3_une_carte_n_est_relue_sur_discord_qu_une_fois_par_demi_heure(env, monkeypatch):
    g, posts, _f = installe(env)
    for uid, zone in ((7, "aide"), (8, "boss")):
        E._creations.clear()
        publier(g, g.membre(uid), zone)
    lectures = []
    vrai = E._existe

    async def compte(g_, d):
        lectures.append(d["id"])
        return await vrai(g_, d)
    monkeypatch.setattr(E, "_existe", compte)
    t0 = time.time()
    run(E.entretenir(g, maintenant=t0))
    run(E.entretenir(g, maintenant=t0 + 300))
    run(E.entretenir(g, maintenant=t0 + 600))
    assert sorted(lectures) == [1, 2], "deux cartes, lues une fois en 10 minutes (au lieu de six lectures)"
    run(E.entretenir(g, maintenant=t0 + E.VERIF_S + 1))
    assert sorted(lectures) == [1, 1, 2, 2]


def test_R4_certifier_ni_soi_meme_ni_un_echange_dont_on_est_partie(env):
    g, posts, _f = installe(env)
    guide = g.membre(10, g.get_role(env.conf["rs_roles"]["aide"]))
    publier(g, g.membre(7), "aide")
    run(E.rejoindre(interaction(g, guide), 1))
    run(E.rejoindre(interaction(g, g.membre(8)), 1))
    assert run(E.certifier(g, 1, guide, [10, 8])) == ""
    assert run(E.charger(1))["credites"] == [8], "le guide ne se crédite pas lui-même"
    mm = g.membre(11, g.get_role(env.conf["rs_roles"]["trade"]))
    E._creations.clear()
    publier(g, g.membre(7), "trade")
    run(E.rejoindre(interaction(g, mm), 2))
    assert run(E.certifier(g, 2, mm, [], partenaire=11)) == E.tr("certif_partie", "fr")
    assert run(E.charger(2))["statut"] in E.OUVERTS, "refusé : la demande reste ouverte"
    v = E.VueCertifier(run(E.charger(2)), E.ZONES["trade"], mm)
    choix = next(c for c in v.walk_children() if isinstance(c, discord.ui.UserSelect))
    assert [o.id for o in choix.default_values] == [], "le middleman n'est pas proposé comme partenaire"
    assert "carte et les réponses s'effacent" in E.tr("clore_texte", "fr") and "historique" not in E.tr("clore_texte", "fr")


# ─── La FAQ ──────────────────────────────────────────────────────────────────

def test_R5_la_faq_se_tait_dans_help_et_trade_et_un_membre_retenu_ne_bloque_pas_le_salon(faq_env):
    g, chat = faq_env.g, faq_env.chat
    effaces = []

    async def plus_tard(m, s):
        effaces.append(s)
    faq.set_hooks(exclus=lambda _g, _c: {chat.id}, effacer_plus_tard=plus_tard)
    assert not run(faq.sur_message(MessageFaq(chat, g.membre(7), "comment on peut faire du trading ?"), maintenant=1.0))
    faq.set_hooks(exclus=lambda _g, _c: set(), effacer_plus_tard=plus_tard)
    q = "comment on peut faire du trading ?"
    m = MessageFaq(chat, g.membre(7), q)

    async def reponse(**kw):
        m.reponses.append(kw)
        return Obj(id=1)
    m.reply = reponse
    assert run(faq.sur_message(m, maintenant=10.0)) and effaces == [faq.EFFACER_S], "l'effacement survit au redémarrage"
    autre = MessageFaq(chat, g.membre(7), q)
    assert not run(faq.sur_message(autre, maintenant=10.0 + faq.SALON_S + 1)), "le même membre attend"
    assert run(faq.sur_message(MessageFaq(chat, g.membre(8), q), maintenant=10.0 + faq.SALON_S + 2)), \
        "un autre membre, juste après : le salon n'a pas été pris par la question retenue"


def test_R6_les_motifs_trop_larges():
    def sujet(q):
        return getattr(faq.reconnaitre(q)[0], "cle", None)
    assert sujet("combien de lives j'ai dans le jeu ?") is None, "les vies d'un jeu"
    assert sujet("can you suggest a good build?") is None
    assert sujet("le live de goripe c'est quand ?") == "videos"
    assert sujet("il est en live là ?") == "videos"
    assert sujet("how do I suggest an idea?") == "suggestion"
    assert sujet("comment faire une suggestion ?") == "suggestion"


# ─── Les guides : un post supprimé sort de la configuration ──────────────────

def test_R7_un_post_supprime_ne_laisse_plus_de_bouton_qui_ment(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)
    zones.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    g = Monde()
    rell = g._salon(Forum, "🌊rell-seas", {"category": g.commu})
    vivant = run(rell.create_thread(name="🛟 Help")).thread
    conf.update(zones_posts={"rell_help": {"id": vivant.id}, "rell_trade": {"id": 987654321}},
                clan_posts={"annonces": {"id": 987654322}})

    async def rien(_g):
        return False
    monkeypatch.setattr(zones, "assurer_guide", rien)
    monkeypatch.setattr(zones, "assurer_guide_clan", rien)
    run(zones.entretenir(g))
    assert conf["zones_posts"] == {"rell_help": {"id": vivant.id}} and conf["clan_posts"] == {}


# ─── bot.py ──────────────────────────────────────────────────────────────────

def test_R8_le_panneau_aide_ne_depasse_jamais_quarante_composants():
    ns = {"discord": discord, "Button": discord.ui.Button, "AIDE_VERSION": "v", "print": lambda *a: None}
    exec(_source("_vue_aide"), ns)  # noqa: S102 — code du dépôt

    class Lien:
        def __init__(self, n):
            self.jump_url = f"https://discord.com/channels/1/{n}"

    async def conf(_g):
        return {}
    groupes = [(f"Jeu {n}", "phrase", [(Lien(n * 10 + k), f"B{k}") for k in range(5)]) for n in range(6)]
    from ui_v2 import LayoutView, Palette
    ns.update(LayoutView=LayoutView, Palette=Palette, _salon_des_tickets=lambda g: Obj(id=5, jump_url="https://x/5"),
              rellseas_ui=Obj(panneaux_tickets=lambda c: []), _salon_par_nom=lambda g, n: None,
              visuels=Obj(bandeau=lambda cle, titre: discord.ui.TextDisplay(titre)),
              LangSelectButton=lambda l: discord.ui.Button(label=l, custom_id=f"lang:{l}"),
              zones=Obj(groupes_aide=lambda g, c, cfz: groupes, conf=conf))
    v, _sig = asyncio.run(ns["_vue_aide"](Obj(rules_channel=None), {}))
    assert v.total_children_count <= 40, v.total_children_count
    assert "Staff" in textes(v), "le staff garde sa place"


def test_R9_branche_dans_le_bot():
    assert 'bot.add_listener(_entraide_message, "on_message")' in SRC
    assert 'bot.add_listener(_entraide_effacement, "on_raw_message_delete")' in SRC
    assert 'bot.add_listener(_entraide_effacement_masse, "on_raw_bulk_message_delete")' in SRC
    assert "faq.set_hooks(exclus=" in SRC and '_register_for_cleanup(m, secondes, "faq")' in SRC
    assert "if _dans_entraide(msg.channel, c):" in _source("_questions_hook")
    boucle = _source("entraide_task")
    assert boucle.index("suggestions.assurer_panneau(g)") < boucle.index("zones.entretenir(g)")
    nettoyage = _source("_run_persistent_cleanup_once")
    assert "get_channel_or_thread" in nettoyage and "fetch_channel" in nettoyage, "un post de forum, même endormi"
    assert "ENTRAIDE : détection d'appel à l'aide en chat" not in SRC and "ZONES SOCIALES : détection TRADE" not in SRC
    assert '"accueil": dict(_DERNIER_ACCUEIL) or None' in SRC and '"entraide_suivi": entraide.releve()' in SRC
