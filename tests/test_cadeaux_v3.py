"""24/10/2026, le fondateur, pendant son premier vrai cadeau :
- « que les gens ne puissent pas cliquer ou que ça leur envoie un message d'erreur leur disant qu'ils n'ont pas
  les statistiques, et combien ils ont » → les conditions d'abord, un message pour soi avec ses chiffres ;
- « ceux qui participent et qui n'ont pas les messages, tu les retires et ça envoie un message… pas en privé,
  mais en dessous » → l'élagage, une fois, et un mot sous la carte ;
- « voir la liste des participants exacts… une belle liste déroulante… sans limite… optimisé » → 👥 ;
et les compteurs enregistrés à l'arrêt, les erreurs des boutons comptées pour /stats."""
from __future__ import annotations

import ast
import asyncio
import logging

import discord
import pytest

import cadeaux as K
import diag
from conftest_discord import Obj, base
from faux_serveur import Monde, ids, interaction, run, textes

from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, _conf = base(tmp_path)
    journal = []

    async def autorise(_g, m):
        return m.id in (1, 781205382923288593)

    async def noter(_g, type_, texte, **_kw):
        journal.append((type_, texte))
    K.setup(get_db=get_db, cfg=cfg, db_set=db_set, autorise=autorise, journal=noter, log=lambda *a: None)
    for d in (K._actifs, K._tampon, K._dernier_msg, K._rafales, K._comptes, K._vocal, K._maj_prevues, K._verrous,
              K._en_cours, K._annonces_faites, K._ecartes):
        d.clear()
    K._charges.clear()
    K._juge.oublier()   # 29/10/2026 : la mémoire du filtre de qualité (qualite.py), comme les autres compteurs
    monkeypatch.setattr(K, "MAJ_CARTE_S", 0)
    horloge = [5000.0]
    monkeypatch.setattr(K, "_mono", lambda: horloge[0])
    run(K.init_db())
    return Obj(journal=journal, horloge=horloge)


def serveur():
    g = Monde()
    g.voice_channels, g.stage_channels, g.afk_channel, g.premium_subscriber_role = [], [], None, None
    return g


def _lancer(g, **kw):
    salon = run(K.salon_cadeaux(g, creer=True))
    lien, erreur = run(K.lancer(g, g.membre(1), K.Brouillon(lot="Nitro", duree="2h", **kw)))
    assert erreur == "" and lien
    return salon


def _ecrire(env, g, uid, n):
    for _k in range(n):
        env.horloge[0] += 5
        assert K.sur_message(Obj(id=int(env.horloge[0] * 10) + uid, guild=g, author=Obj(id=uid, bot=False),
                                 content=f"je raconte ma partie de ce soir, épisode {env.horloge[0]} !", webhook_id=None,
                                 type=discord.MessageType.default,
                                 attachments=[], stickers=[]))


def _select(v):
    """La liste déroulante d'une vue (un DynamicItem enveloppe le Select)."""
    return next(getattr(x, "item", x) for x in v.walk_children()
                if isinstance(getattr(x, "item", x), discord.ui.Select))


def _vue(i):
    """Ce que voit le membre : la réponse différée (acquittée d'abord, puis réécrite ou envoyée pour soi),
    sinon la réponse directe."""
    if i.suivis:
        return i.suivis[-1][1]["view"]
    return (i.response.edits or [m[1] for m in i.response.messages])[-1]["view"]


def test_L1_les_conditions_d_abord_le_refus_dit_ce_qu_il_faut_et_ou_on_en_est(env):
    g = serveur()
    _lancer(g, msg_min=3, voc_min=10, logique="ou")
    m = g.membre(11)
    _ecrire(env, g, 11, 1)
    i = interaction(g, m)
    run(K.participer(i, 1))
    t = textes(_vue(i))
    assert "Pas encore" in t and "**1 / 3**" in t and "0 min / 10 min" in t and "remplis les conditions" in t
    assert ids(_vue(i)) == ["cd:r:1", "cd:p:1"], "Actualiser, et Participer pour recliquer"
    assert run(K.inscrits(1)) == []
    _ecrire(env, g, 11, 2)
    i = interaction(g, m)
    run(K.participer(i, 1))
    assert "Tu participes" in textes(_vue(i)) and run(K.inscrits(1)) == [11], "l'un ou l'autre suffit"
    #  Une inscription d'avant la règle, sans les conditions : un clic la retire.
    run(K._ecrire("INSERT INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(1, 12, 1)", ()))
    i = interaction(g, g.membre(12))
    run(K.participer(i, 1))
    assert "Pas encore" in textes(_vue(i)) and run(K.inscrits(1)) == [11]


def test_L2_le_cadeau_en_cours_est_elague_chacun_le_lit_pour_lui_seul(env):
    g = serveur()
    salon = _lancer(g, msg_min=2)
    envois = len(salon.envois)
    for uid, n in ((11, 2), (12, 1), (13, 0)):
        _ecrire(env, g, uid, n)
        g.membre(uid)
        run(K._ecrire("INSERT INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(1, ?, ?)", (uid, uid)))
    assert run(K.elaguer(g)) == 2
    assert run(K.inscrits(1)) == [11], "seul celui qui a ses messages reste"
    assert len(salon.envois) == envois, "24/10 : aucun message public — personne n'est nommé devant tout le monde"
    assert "1 participant" in textes(salon.cartes[-1][1]["view"]), "la carte suit"
    assert any(type_ == "cadeaux.retires" for type_, _x in env.journal)
    i = interaction(g, g.membre(12))
    run(K.montrer_stats(i, 1))
    t = textes(_vue(i))
    assert "Ta participation a été retirée" in t and "**1 / 2**" in t and i.suivis[-1][1]["ephemeral"]
    i = interaction(g, g.membre(12))
    run(K.montrer_stats(i, 1))
    assert "retirée" not in textes(_vue(i)), "lu une fois : le mot part"
    i = interaction(g, g.membre(13))
    run(K.participer(i, 1))
    assert "Ta participation a été retirée" in textes(_vue(i)) and "**0 / 2**" in textes(_vue(i))
    assert run(K.elaguer(g)) == 0, "plus personne à retirer"


def test_L2b_l_avis_public_part_ses_membres_notes_les_annonces_s_effacent(env):
    from discord import components as C
    g = serveur()
    salon = _lancer(g, msg_min=2)
    carte = run(K.charger(1))["message_id"]
    v = discord.ui.LayoutView()
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(
        "### ⚠️ Participation retirée · Entry removed\n<@12> : 💬 1/2\n<@13> : 💬 0/2")))
    effaces = []

    def message(mid, auteur, composants, ref=None):
        m = Obj(id=mid, author=Obj(id=auteur), components=composants, reference=ref)

        async def delete():
            effaces.append(mid)
        m.delete = delete
        return m
    avis = message(501, g.me.id, [C._component_factory(d) for d in v.to_components()], Obj(message_id=carte))
    salon.historique = [message(500, 77, []), avis]
    assert run(K.nettoyer_avis(g)) == {"lus": 2, "du_bot": 1, "effaces": 1} and effaces == [501], \
        "seul l'avis du bot part ; le relevé dit ce qui a été lu"
    i = interaction(g, g.membre(13))
    run(K.montrer_stats(i, 1))
    assert "Ta participation a été retirée" in textes(_vue(i)), "ceux qu'il nommait le liront en cliquant"
    #  L'annonce des gagnants s'efface au bout de 24 h ; la carte garde les gagnants.
    run(K.terminer(g, 1))
    annonce = salon.envois[-1][0]
    assert run(K.purger(g)) == 0 and annonce not in g.effaces, "pas avant 24 h"
    run(K._ecrire("UPDATE cadeaux_messages SET effacer_a=0", ()))
    assert run(K.purger(g)) == 1 and annonce in g.effaces


def test_L2c_le_mot_pour_soi_s_efface_tout_seul(env, monkeypatch):
    monkeypatch.setattr(K, "AVIS_S", 0)
    g = serveur()
    _lancer(g, msg_min=2)
    effaces = []

    async def scenario():
        i = interaction(g, g.membre(12))

        async def supprimer():
            effaces.append("refus")
        i.delete_original_response = supprimer
        await K.participer(i, 1)
        await asyncio.sleep(0.05)
        return i
    i = asyncio.run(scenario())
    assert "Pas encore" in textes(_vue(i)) and effaces == ["refus"], "« après, ça s'enlève tout seul »"


def test_L3_la_liste_des_participants_sans_limite_25_par_page(env):
    g = serveur()
    salon = _lancer(g, msg_min=1)
    for uid in range(100, 160):
        g.membre(uid)
        _ecrire(env, g, uid, 1 if uid % 2 == 0 else 0)
        run(K._ecrire("INSERT INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(1, ?, ?)", (uid, uid)))
    assert ids(salon.envois[-1][2]["view"]) == ["cd:p:1", "cd:s:1", "cd:l:1"], "👥 sur la carte"
    c = run(K.charger(1))
    v = run(K.vue_participants(g, c, 0))
    t = textes(v)
    assert "60 participants" in t and "✅ 30 remplissent les conditions" in t and "page 1/3" in t
    choix = _select(v)
    assert len(choix.options) == 25 and choix.options[0].label == "1. Pirate100" and choix.options[0].value == "100"
    assert choix.options[0].description == "💬 1/1" and str(choix.options[0].emoji) == "✅"
    assert str(choix.options[1].emoji) == "⏳" and "1–25 sur 60" in choix.placeholder
    assert ids(v) == ["cd:ls:1:0", "cd:lx:1:a", "cd:lx:1:p", "cd:lp:1:1", "cd:lq:1"]
    v = run(K.vue_participants(g, c, 2))
    choix = _select(v)
    assert len(choix.options) == 10 and choix.options[0].label.startswith("51. ") and "page 3/3" in textes(v)
    assert ids(v) == ["cd:ls:1:2", "cd:lp:1:1", "cd:lx:1:p", "cd:lx:1:b", "cd:lq:1"]
    assert "page 3/3" in textes(run(K.vue_participants(g, c, 99))), "une page trop loin : la dernière"
    v = run(K.vue_participants(g, c, 0, "pirate15"))
    t = textes(v)
    assert "10 sur 60" in t and ids(v)[-2:] == ["cd:lp:1:0", "cd:lq:1"], "🔎 : les noms qui contiennent"
    assert "Aucun participant" in textes(run(K.vue_participants(g, c, 0, "zzz")))


def test_L4_tout_se_clique_la_liste_les_pages_la_fiche_la_recherche(env):
    g = serveur()
    _lancer(g, msg_min=1)
    for uid in range(100, 130):
        g.membre(uid)
        _ecrire(env, g, uid, 1)
        run(K._ecrire("INSERT INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(1, ?, ?)", (uid, uid)))
    i = interaction(g, g.membre(7))
    run(K.BoutonParticipants(1).callback(i))
    contenu, kw = i.suivis[-1]
    assert kw["ephemeral"] and "30 participants" in textes(kw["view"]), "depuis la carte : un message pour soi"

    def clic():   # chaque clic est une nouvelle interaction, depuis le message pour soi
        j = interaction(g, g.membre(7))
        j.message = Obj(flags=Obj(ephemeral=True))
        return j
    i = clic()
    run(K.BoutonPage(1, 1).callback(i))
    assert i.suivis[-1][0] == "edit" and "page 2/2" in textes(i.suivis[-1][1]["view"]), "◀ ▶ réécrivent la liste"
    i = clic()
    i.data = {"values": ["127"]}
    run(K.ChoixParticipant(1, 1).callback(i))
    fiche = i.suivis[-1][1]["view"]
    assert "28. <@127>" in textes(fiche) and "Inscrit <t:" in textes(fiche) and "**1 / 1**" in textes(fiche)
    assert ids(fiche) == ["cd:lp:1:1"], "◀ Retour à la liste, à la même page"
    i = clic()
    run(K.BoutonChercher(1).callback(i))
    formulaire = i.response.modals[-1]
    i = clic()
    formulaire.q._value = "pirate12"
    run(formulaire.on_submit(i))
    assert "10 sur 30" in textes(i.suivis[-1][1]["view"])


def test_L5_branche_dans_le_bot_l_etat_et_l_arret_propre(env):
    assert all(f"cadeaux.{x}" in SRC for x in ("BoutonParticipants", "BoutonPage", "ChoixParticipant",
                                                 "BoutonChercher"))
    assert "await cadeaux.elaguer(g)" in SRC and "'cadeaux_elagage_v1'" in SRC
    assert '"cadeaux_detail"' in SRC and '"erreurs_ui": diag.releve("ui")' in SRC
    #  24/10/2026 (revue) : le démarrage se fait par étapes (`_Etape`) — l'arrêt propre a la sienne, après les cadeaux.
    plat = SRC.replace("\r\n", "\n")
    assert plat.index("await cadeaux.init_db()") < plat.index('with _Etape("arret_propre"):\n        _installer_arret_propre()')
    g = serveur()
    _lancer(g, msg_min=2)
    _ecrire(env, g, 11, 3)
    run(K._ecrire("INSERT INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(1, 11, 1)", ()))
    e = run(K.etat(g))[0]
    assert e["inscrits"] == 1 and e["remplissent"] == 1 and e["messages"] == 3 and e["membres_comptes"] == 1
    #  L'arrêt : les compteurs en base d'abord, puis la fermeture.
    arbre = ast.parse(SRC)
    src = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_arret_propre")
    ordre = []

    async def vider():
        ordre.append("vider")
        return 1

    async def close():
        ordre.append("close")
    ns = {"cadeaux": Obj(vider=vider), "bot": Obj(close=close), "_logerr": lambda *a, **k: None}
    exec(src, ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["_arret_propre"]())
    assert ordre == ["vider", "close"]


def test_L6_les_erreurs_des_boutons_sont_comptees_pour_stats():
    diag._COMPTES.clear()
    arbre = ast.parse(SRC)
    src = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_ErreursInteractions")
    ns = {"logging": logging, "discord": discord, "diag": diag}
    exec(src, ns)  # noqa: S102 — code du dépôt
    h = ns["_ErreursInteractions"]()
    bouton = discord.ui.Button(label="x", custom_id="rs:n:farm")
    try:
        raise RuntimeError("panne")
    except RuntimeError:
        import sys
        rec = logging.LogRecord("discord.ui.view", logging.ERROR, __file__, 1,
                                "Ignoring exception in view %r for item %r", (object(), bouton),
                                sys.exc_info())
    h.emit(rec)
    h.emit(rec)
    assert diag.releve("ui") == {"ui/rs:n:farm:RuntimeError": [2, diag._COMPTES["ui/rs:n:farm:RuntimeError"][1]]}
    diag.compter("ui", "radiedec:lever:781205382923288593", ValueError())
    assert "ui/radiedec:lever:#:ValueError" in diag.releve("ui"), "aucun identifiant"
