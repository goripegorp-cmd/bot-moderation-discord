"""22/10/2026 (nuit), le fondateur : « un salon unique… tu me le crées, après, moi, je le place où je veux…
pour les cadeaux… où je peux mettre vraiment des conditions. Quel rôle peut y participer ? … combien de
messages… combien de temps… au moment de la création du cadeau… ils voient les statistiques monter
individuellement… à chaque cadeau, ça se réinitialise… ça nettoie toutes les données… soit en et, soit en
ou… un multiplicateur… ceux qui offrent le nitro »."""
from __future__ import annotations

import ast
import asyncio
import random
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
import pytest

import cadeaux as K
from conftest_discord import Obj, base
from faux_serveur import Monde, compter, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
FONDATEUR = 781205382923288593


def _source(nom):
    return next(ast.unparse(n) for n in ast.parse(SRC).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal = []

    async def autorise(_g, m):
        return m.id in (1, FONDATEUR)

    async def noter(_g, type_, texte, **_kw):
        journal.append((type_, texte))
    K.setup(get_db=get_db, cfg=cfg, db_set=db_set, autorise=autorise, journal=noter, log=lambda *a: None)
    for d in (K._actifs, K._tampon, K._dernier_msg, K._rafales, K._comptes, K._vocal, K._maj_prevues, K._verrous,
              K._en_cours, K._annonces_faites, K._ecartes):
        d.clear()
    K._charges.clear()
    K._juge.oublier()   # 29/10/2026 : la mémoire du filtre de qualité (qualite.py), comme les autres compteurs
    monkeypatch.setattr(K, "MAJ_CARTE_S", 0)
    monkeypatch.setattr(K, "_mono", time.monotonic)
    monkeypatch.setattr(K, "_mur", time.time)
    run(K.init_db())
    return Obj(conf=conf, journal=journal, get_db=get_db)


def serveur():
    g = Monde()
    g.voice_channels, g.stage_channels, g.afk_channel, g.premium_subscriber_role = [], [], None, None
    return g


def _msg(g, mid, auteur, texte=None, bot=False, salon=0):
    """Une phrase complète par défaut, différente à chaque message : des messages courts à la suite feraient une rafale
    (27/10), et le même texte répété est un copié-collé qui ne compte pas (29/10, qualite.py)."""
    texte = texte if texte is not None else f"je raconte ma partie de ce soir, épisode {mid} !"
    return Obj(id=mid, guild=g, author=Obj(id=auteur, bot=bot), content=texte, webhook_id=None,
               type=discord.MessageType.default, attachments=[], stickers=[], channel=Obj(id=salon))


def _c(**kw):
    c = {"id": 1, "msg_min": 0, "voc_min": 0, "logique": "et", "roles": [], "chance_roles": [], "multiplicateur": 2.0}
    c.update(kw)
    return c


def _vue(i):
    """Ce que voit le membre : la réponse différée (acquittée d'abord, puis le message pour soi), sinon la
    réponse directe."""
    if i.suivis:
        return i.suivis[-1][1]["view"]
    return i.response.messages[-1][1]["view"]


# ─── Les règles ──────────────────────────────────────────────────────────────

def test_K1_la_duree_se_lit_comme_on_la_dit():
    t0 = 1_761_000_000
    attendus = {"30m": 1800, "2h": 7200, "2h30": 9000, "1j12h": 129600, "3 jours": 3 * 86400,
                "1 semaine": 604800, "45 min": 2700}
    for texte, secondes in attendus.items():
        assert K.lire_duree(texte, t0) == t0 + secondes, texte
    paris = ZoneInfo("Europe/Paris")
    attendu = int(datetime(2026, 10, 25, 21, 0, tzinfo=paris).timestamp())
    assert K.lire_duree("25/10/2026 21:00", t0) == attendu == K.lire_duree("25/10/2026 à 21h", t0)
    assert K.lire_duree("1/1 12:00", t0) == int(datetime(2026, 1, 1, 12, 0, tzinfo=paris).timestamp()), \
        "le 1er janvier à midi, pas le 11 à 2 h"
    for faux in ("", "demain", "2x", "12", "31/02/2026 10:00"):
        assert K.lire_duree(faux, t0) is None, faux


def test_K2_et_ou_le_role_demande_et_la_chance():
    c = _c(msg_min=50, voc_min=60)
    assert not K.remplit(c, 50, 59 * 60) and K.remplit(c, 50, 3600), "ET : les deux"
    c["logique"] = "ou"
    assert K.remplit(c, 50, 0) and K.remplit(c, 0, 3600) and not K.remplit(c, 49, 3599), "OU : l'un ou l'autre"
    assert K.remplit(_c(), 0, 0), "sans condition : il suffit de participer"
    membre, booster = Obj(roles=[Obj(id=5)]), Obj(roles=[Obj(id=9), Obj(id=5)])
    c = _c(roles=[5], chance_roles=[9], multiplicateur=2.5)
    assert K.peut_participer(c, membre) and not K.peut_participer(c, Obj(roles=[]))
    assert (K.chance(c, membre), K.chance(c, booster)) == (1.0, 2.5)


def test_K3_x2_c_est_deux_fois_plus_de_chances():
    hasard = random.Random(7)
    gagne = sum(K.tirer([(1, 1.0), (2, 2.0)], 1, hasard) == [2] for _ in range(30000))
    assert abs(gagne / 30000 - 2 / 3) < 0.015
    assert sorted(K.tirer([(1, 1.0), (2, 1.0), (3, 1.0)], 5, hasard)) == [1, 2, 3], "jamais deux fois le même"
    assert K.tirer([], 3) == []


# ─── Les compteurs ───────────────────────────────────────────────────────────

def test_K4_les_messages_comptent_sans_le_spam(env, monkeypatch):
    g = serveur()
    K._actifs[g.id] = {1: time.time() - 10}
    horloge = [1000.0]
    monkeypatch.setattr(K, "_mono", lambda: horloge[0])
    assert not K.sur_message(_msg(g, 1, 7, bot=True)), "un bot ne compte pas"
    assert not K.sur_message(_msg(g, 2, 7, "a")), "un caractère ne compte pas"
    assert K.sur_message(_msg(g, 3, 7)) and not K.sur_message(_msg(g, 4, 7)), "un toutes les 3 s"
    horloge[0] += 3
    assert K.sur_message(_msg(g, 5, 7)) and K._tampon[(1, 7)][0] == 2
    assert K.sur_suppression(5) and K._tampon[(1, 7)][0] == 1, "supprimé aussitôt (la modération) : ne compte plus"
    horloge[0] += 601
    assert not K.sur_suppression(3), "supprimé bien plus tard : il reste compté"
    autre = serveur()
    autre.id = 2
    assert not K.sur_message(_msg(autre, 6, 7)), "pas de cadeau en cours sur ce serveur : rien"


def test_K5_le_vocal_compte_hors_afk_casque_non_coupe(env, monkeypatch):
    g = serveur()
    afk, salon = Obj(id=99), Obj(id=50)
    g.afk_channel = afk
    mur = [10_000.0]
    monkeypatch.setattr(K, "_mur", lambda: mur[0])
    K._actifs[g.id] = {1: 10_100.0}       # le cadeau commence 100 s après l'arrivée en vocal
    m = g.membre(7)
    dedans = Obj(channel=salon, self_deaf=False, deaf=False)
    dehors = Obj(channel=None, self_deaf=False, deaf=False)
    sourd = Obj(channel=salon, self_deaf=True, deaf=False)
    K.sur_vocal(m, dehors, dedans)
    mur[0] = 10_400.0
    K.sur_vocal(m, dedans, sourd)
    assert K._tampon[(1, 7)][1] == 300 and (g.id, 7) not in K._vocal, "compté depuis le lancement ; casque coupé : stop"
    mur[0] = 10_500.0
    K.sur_vocal(m, sourd, dedans)
    mur[0] = 10_560.0
    K.sur_vocal(m, dedans, Obj(channel=afk, self_deaf=False, deaf=False))
    assert K._tampon[(1, 7)][1] == 360 and (g.id, 7) not in K._vocal, "le salon AFK ne compte pas"
    K.sur_vocal(g.membre(8), dehors, dedans)
    mur[0] = 10_620.0
    assert run(K.stats(1, 8)) == (0, 60), "en direct : le segment en cours compte"
    assert run(K.vider()) == 2 and run(K.stats(1, 7)) == (0, 360) and run(K.stats(1, 8)) == (0, 60)


# ─── De bout en bout ─────────────────────────────────────────────────────────

def test_K6_un_cadeau_de_bout_en_bout(env, monkeypatch):
    g = serveur()
    membre_role = run(g.create_role(name="Membre"))
    booster = run(g.create_role(name="Server Booster"))
    g.premium_subscriber_role = booster
    fondateur = g.membre(FONDATEUR)
    salon = run(K.salon_cadeaux(g, creer=True))
    assert salon.name == "🎁giveaways" and salon.category_id is None and salon.kw["position"] == 0, \
        "sans catégorie, en haut : le fondateur le range où il veut"
    assert salon.kw["overwrites"][g.default_role].send_messages is False
    assert "Les cadeaux du serveur" in textes(salon.envois[0][2]["view"])
    assert run(K.salon_cadeaux(g, creer=True)) is salon and len(g.salons) == 6, "une fois"
    b = K._brouillon_neuf(g)
    assert b.chance_roles == [booster.id] and b.multiplicateur == 2.0, "les boosters ×2 proposés d'office"
    b.lot, b.duree, b.roles, b.msg_min = "Nitro 1 mois", "2h", [membre_role.id], 2
    vue = K.VueCadeau(fondateur, g, b)
    assert compter(vue) <= 40 and "Nitro 1 mois" in textes(vue) and "Lancer" in textes(vue)
    lien, erreur = run(K.lancer(g, fondateur, b))
    assert erreur == "" and lien
    c = run(K.charger(1))
    t = textes(salon.envois[-1][2]["view"])
    assert "## 🎁 Nitro 1 mois" in t and f"<@&{membre_role.id}>" in t and "**2** messages" in t and "×2" in t
    assert c["message_id"] == salon.envois[-1][0] and K._actifs[g.id] == {1: c["debut"]}
    i = interaction(g, g.membre(10))
    run(K.participer(i, 1))
    assert "réservé" in textes(_vue(i)) and run(K.inscrits(1)) == [], "sans le rôle demandé : refusé"
    a, bb = g.membre(11, membre_role), g.membre(12, membre_role, booster)
    i = interaction(g, a)
    run(K.participer(i, 1))
    assert "Pas encore" in textes(_vue(i)) and "**0 / 2**" in textes(_vue(i)) and run(K.inscrits(1)) == [], \
        "24/10 : sans les messages demandés, refusé — et il voit ce qu'il lui faut"
    horloge = [5000.0]
    monkeypatch.setattr(K, "_mono", lambda: horloge[0])
    for mid, auteur in ((101, 11), (102, 12), (103, 11)):
        assert K.sur_message(_msg(g, mid, auteur))
        horloge[0] += 5
    i = interaction(g, a)
    run(K.participer(i, 1))
    assert "Tu participes" in textes(_vue(i))
    i = interaction(g, bb)
    run(K.participer(i, 1))
    assert "**1 / 2**" in textes(_vue(i)) and "Pas encore" in textes(_vue(i))
    run(K.participer(interaction(g, a), 1))
    assert run(K.inscrits(1)) == [11], "deux clics : une inscription ; sans les messages, aucune"
    assert "1 participant" in textes(salon.cartes[-1][1]["view"]), "la carte suit"
    i = interaction(g, a)
    run(K.montrer_stats(i, 1))
    t = textes(_vue(i))
    assert "**2 / 2**" in t and "Conditions remplies" in t and "Inscrit" in t, "ses stats montent"
    i = interaction(g, bb)
    run(K.montrer_stats(i, 1))
    t = textes(_vue(i))
    assert "**1 / 2**" in t and "Pas encore" in t and "Ta chance : ×2" in t
    run(K.terminer(g, 1, par=FONDATEUR))
    c = run(K.charger(1))
    assert c["statut"] == "fini" and c["resultat"]["gagnants"] == [11] and c["resultat"]["eligibles_n"] == 1, \
        "seul celui qui remplit les conditions gagne"
    assert run(K.inscrits(1)) == [] and run(K._stats_en_base(1)) == {}, "« ça nettoie toutes les données »"
    fin = textes(salon.cartes[-1][1]["view"])
    assert "terminé" in fin and "<@11>" in fin
    annonce = salon.envois[-1][2]
    assert "<@11>" in textes(annonce["view"]) and [u.id for u in annonce["allowed_mentions"].users] == [11]
    assert not K._actifs, "plus rien en mémoire"
    nouveau, raison = run(K.relancer(g, 1))
    assert nouveau is None and "Plus personne" in raison
    assert any("Nitro 1 mois" in x for _t, x in env.journal)


def test_K7_nouveau_tirage_et_annulation(env):
    g = serveur()
    f = g.membre(1)
    run(K.salon_cadeaux(g, creer=True))
    run(K.lancer(g, f, K.Brouillon(lot="Robux", duree="1h")))
    for uid in (21, 22, 23):
        run(K.participer(interaction(g, g.membre(uid)), 1))
    run(K.terminer(g, 1))
    premier = run(K.charger(1))["resultat"]["gagnants"]
    nouveau, _r = run(K.relancer(g, 1))
    assert nouveau not in premier and run(K.charger(1))["resultat"]["gagnants"] == premier + [nouveau]
    run(K.lancer(g, f, K.Brouillon(lot="Pass", duree="1h")))
    assert run(K.annuler(g, 2, par=1)) and run(K.charger(2))["statut"] == "annule" and not K._actifs
    assert not run(K.annuler(g, 2, par=1)), "une fois"


def test_K8_la_boucle_tire_a_l_heure_meme_apres_un_redemarrage(env):
    g = serveur()
    run(K.salon_cadeaux(g, creer=True))
    run(K.lancer(g, g.membre(1), K.Brouillon(lot="Skin", duree="1h")))
    K._actifs.clear()
    K._charges.clear()
    assert run(K.tic([g])) == 0 and K._actifs[g.id], "rechargé ; pas encore l'heure"

    async def avancer():
        await K._ecrire("UPDATE cadeaux SET fin=? WHERE id=1", (int(time.time()) - 1,))
    run(avancer())
    assert run(K.tic([g])) == 1 and run(K.charger(1))["statut"] == "fini"


def test_K9_la_gestion_reservee_au_fondateur_et_a_la_direction(env):
    g = serveur()
    i = interaction(g, g.membre(50))
    run(K.ouvrir_gestion(i))
    assert "Réservé au fondateur" in i.response.messages[-1][0]
    i = interaction(g, g.membre(1))
    run(K.ouvrir_gestion(i))
    assert "Nouveau cadeau" in textes(_vue(i))


def test_K10_branche_dans_le_bot():
    assert "cadeaux.setup(get_db=get_db" in SRC and "await cadeaux.init_db()" in SRC
    for ecoute in ('bot.add_listener(_cadeaux_message, "on_message")',
                   'bot.add_listener(_cadeaux_vocal, "on_voice_state_update")',
                   'bot.add_listener(_cadeaux_effacement, "on_raw_message_delete")'):
        assert ecoute in SRC, ecoute
    assert "bot.add_dynamic_items(cadeaux.BoutonCadeaux, cadeaux.BoutonParticiper" in SRC
    assert "cadeaux.BoutonCadeaux()" in _source("_menu_logs")
    boucle = _source("cadeaux_task")
    assert boucle.index("db_set(g.id, 'cadeaux_salon_v1'") < boucle.index("cadeaux.salon_cadeaux(g, creer=True)")
    assert "await cadeaux.tic(list(bot.guilds))" in boucle
    assert '"cadeaux_task",' in SRC, "le superviseur la démarre (sinon : aucun tirage)"
    assert '"cadeaux_salon": sum(' in SRC and '"cadeaux_en_cours": cadeaux.nb_actifs()' in SRC
    assert (RACINE / "visuels" / "cadeaux.gif").is_file()


def test_K11_le_panneau_de_creation_de_bout_en_bout(env):
    """Le fondateur : « Lot et durée », les rôles, les conditions, ET/OU, puis « Lancer »."""
    g = serveur()
    f = g.membre(1)
    run(K.salon_cadeaux(g, creer=True))
    form = K.FormulaireLot(K.VueCadeau(f, g, K.Brouillon()))
    form.lot._value, form.details._value, form.gagnants._value, form.duree._value = \
        "  Nitro   1 mois ", "Pour les actifs", "2", "3 jours"
    form.image._values = []
    i = interaction(g, f)
    run(form.on_submit(i))
    vue = i.suivis[-1][1]["view"]
    assert (vue.b.lot, vue.b.gagnants, vue.b.duree) == ("Nitro 1 mois", 2, "3 jours") and "Nitro 1 mois" in textes(vue)
    i = interaction(g, f)
    i.data = {"values": ["77"]}
    run(vue._cb_roles(i))
    assert vue.b.roles == [77]
    logique = next(b for b in vue.walk_children() if isinstance(b, discord.ui.Button) and "ET" in (b.label or ""))
    assert logique.disabled, "ET/OU : il faut deux conditions"
    fc = K.FormulaireConditions(vue)
    fc.msg._value, fc.voc._value = "10", "30"
    i = interaction(g, f)
    run(fc.on_submit(i))
    vue = i.response.edits[-1]["view"]
    assert "10 messages" in textes(vue) and "30 min" in textes(vue)
    i = interaction(g, f)
    run(vue._cb_logique(i))
    assert vue.b.logique == "ou" and "**ou · or**" in textes(i.response.edits[-1]["view"])
    form = K.FormulaireLot(vue)
    form.lot._value, form.details._value, form.gagnants._value, form.duree._value = "Nitro", "", "1", "jamais"
    form.image._values = []
    i = interaction(g, f)
    run(form.on_submit(i))
    assert "Durée illisible" in textes(i.suivis[-1][1]["view"]), "une durée illisible le dit"
    vue.b.duree = "3 jours"
    i = interaction(g, f)
    run(vue._cb_lancer(i))
    assert "Cadeau lancé" in textes(i.suivis[-1][1]["view"])
    c = run(K.charger(1))
    assert (c["roles"], c["msg_min"], c["voc_min"], c["logique"], c["gagnants"]) == ([77], 10, 30, "ou", 1)


def test_K12_ceux_qui_peuvent_et_ceux_qui_peuvent_pas(env):
    """« Que je peux blacklist un rôle, que je peux whitelist un rôle. »"""
    g = serveur()
    membre_role, puni = run(g.create_role(name="Membre")), run(g.create_role(name="Puni"))
    f = g.membre(1)
    run(K.salon_cadeaux(g, creer=True))
    b = K.Brouillon(lot="Skin", duree="1h", roles=[membre_role.id], exclus=[puni.id])
    vue = K.VueCadeau(f, g, b)
    assert compter(vue) <= 40, f"{compter(vue)} composants"
    run(K.lancer(g, f, b))
    carte = textes(g.nom("🎁giveaways").envois[-1][2]["view"])
    assert f"✅ <@&{membre_role.id}>" in carte and f"🚫 <@&{puni.id}>" in carte and "### ⏳ Fin <t:" in carte, \
        "qui peut, qui ne peut pas, et le compte à rebours en tête"
    i = interaction(g, g.membre(30, membre_role, puni))
    run(K.participer(i, 1))
    assert "n'est pas ouvert" in textes(_vue(i)) and run(K.inscrits(1)) == [], "un rôle exclu l'emporte"
    m = g.membre(31, membre_role)
    run(K.participer(interaction(g, m), 1))
    assert run(K.inscrits(1)) == [31]
    m.roles.append(puni)  # puni après s'être inscrit
    run(K.terminer(g, 1))
    assert run(K.charger(1))["resultat"]["gagnants"] == [], "au tirage, un exclu ne gagne pas"


def test_K13_le_tirage_tombe_a_la_seconde(env):
    """« Un vrai timer » : à moins de 40 s de la fin, un minuteur exact prend le relais de la boucle."""
    g = serveur()
    run(K.salon_cadeaux(g, creer=True))
    run(K.lancer(g, g.membre(1), K.Brouillon(lot="Pass", duree="1h")))

    async def bientot():
        await K._ecrire("UPDATE cadeaux SET fin=? WHERE id=1", (time.time() + 1.2,))
        assert await K.tic([g]) == 0 and 1 in K._minuteurs, "le minuteur est posé"
        await asyncio.sleep(2.5)
        return await K.charger(1)
    assert run(bientot())["statut"] == "fini" and not K._minuteurs, "tiré à l'heure, sans attendre la boucle"
    run(K.lancer(g, g.membre(1), K.Brouillon(lot="Skin", duree="1h")))

    async def annule():
        await K._ecrire("UPDATE cadeaux SET fin=? WHERE id=2", (time.time() + 30,))
        await K.tic([g])
        tache = K._minuteurs[2]
        await K.annuler(g, 2, par=1)
        await asyncio.sleep(0)
        return tache
    assert run(annule()).cancelled() and run(K.charger(2))["statut"] == "annule", "annulé : le minuteur s'arrête"


def test_K14_la_commande_giveaway(env):
    """« J'ai pas de commande pour lancer des cadeaux. »"""
    assert 'giveaway_group = app_commands.Group(' in SRC and 'name="giveaway"' in SRC
    assert '@giveaway_group.command(name="lancer"' in SRC and '@giveaway_group.command(name="gerer"' in SRC
    assert "await cadeaux.ouvrir_composeur(i)" in SRC and "bot.tree.add_command(giveaway_group)" in SRC
    g = serveur()
    i = interaction(g, g.membre(50))
    run(K.ouvrir_composeur(i))
    assert i.response.messages[-1][0] == "Réservé au fondateur et à la direction."
    i = interaction(g, g.membre(1))
    run(K.ouvrir_composeur(i))
    vue = _vue(i)
    assert isinstance(vue, K.VueCadeau) and "Rôles exclus" in textes(vue) and "Rôles autorisés" in textes(vue)


def test_K15_une_rafale_de_messages_courts_compte_pour_un(env, monkeypatch):
    """27/10, le fondateur : « si quelqu'un spam comme ça et ne sait pas faire de phrase complète, bah, tu comptes
    comme s'il avait envoyé qu'un seul message. » Entre deux messages, plus que les 3 s anti-spam : seule la
    rafale (même personne, même salon, messages courts à moins de RAFALE_S l'un de l'autre) les regroupe."""
    g = serveur()
    K._actifs[g.id] = {1: time.time() - 10}
    horloge = [1000.0]
    monkeypatch.setattr(K, "_mono", lambda: horloge[0])
    ids = iter(range(1, 10_000))
    ecart = K.ECART_MSG_S + 1
    assert ecart < K.RAFALE_S

    def ecrire(auteur, *textes, salon=50, apres=None):
        for texte in textes:
            horloge[0] += ecart if apres is None else apres
            K.sur_message(_msg(g, next(ids), auteur, texte, salon=salon))
        return K._tampon[(1, auteur)][0]

    assert K.court("le jeux") and K.court("<:pepe:123> <@45> https://tenor.com/view/chat-drole-gif-123")
    assert not K.court("je vais tenter ma chance")
    assert ecrire(7, "le jeux", "me", "tente", "pas", "dsl") == 1, "l'exemple du fondateur : un seul message"
    assert ecrire(8, "je vais tenter ma chance ce soir", "bonne chance à tout le monde") == 2, \
        "deux phrases complètes à la suite : deux messages"
    ecrire(9, "le jeux", "me")
    horloge[0] += K.RAFALE_S
    assert ecrire(9, "tente", "pas", "dsl") == 2, "une pause plus longue que la fenêtre : une nouvelle rafale"
    ecrire(10, "le jeux", salon=50)
    assert ecrire(10, "me", salon=51) == 2, "deux salons : deux rafales"
    ecrire(11, "le jeux")
    ecrire(12, "me", apres=1)
    ecrire(11, "tente", apres=ecart - 1)
    assert K._tampon[(1, 11)][0] == 1 and K._tampon[(1, 12)][0] == 1, "deux personnes : deux rafales"
    horloge[0] += K.RAFALE_S
    ecrire(13, "ok")
    assert list(K._rafales) == [(50, 13)], "les rafales finies sortent de la mémoire"
    monkeypatch.setattr(K, "RAFALES_MAX", 3)
    for uid in range(20, 30):
        ecrire(uid, "salut", apres=0)
    assert len(K._rafales) == 3, "jamais plus de RAFALES_MAX rafales suivies"
