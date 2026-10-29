"""Revue du 24/10/2026 — les cadeaux, les invitations, les vocaux : « chaque bouton, chaque interface… aucune
erreur et aucun problème ». Un test par constat corrigé (R1 → R12)."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
import pytest
from discord.ui.select import BaseSelect

import cadeaux as K
import invitations as I
import vocaux as V
from conftest_discord import Obj, base
from faux_serveur import Monde, compter, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")


def _source(nom):
    return next(ast.unparse(n) for n in ast.parse(SRC).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, _conf = base(tmp_path)
    journal, logs = [], []

    async def autorise(_g, m):
        return m.id == 1

    async def noter(_g, type_, texte, **_kw):
        journal.append((type_, texte))
    I.setup(get_db=get_db, log=lambda *a: None)
    for d in (I._photos, I._verrous, I._menages, I._perimees):
        d.clear()
    run(I.init_db())
    K.setup(get_db=get_db, cfg=cfg, db_set=db_set, autorise=autorise, journal=noter, log=logs.append,
            invitations=I.total, invitations_tous=I.totaux, relever=I.reconcilier)
    for d in (K._actifs, K._tampon, K._dernier_msg, K._rafales, K._comptes, K._vocal, K._maj_prevues, K._verrous,
              K._minuteurs, K._en_cours, K._annonces_faites):
        d.clear()
    K._charges.clear()
    monkeypatch.setattr(K, "MAJ_CARTE_S", 0)
    horloge = [5000.0]
    monkeypatch.setattr(K, "_mono", lambda: horloge[0])
    run(K.init_db())
    yield Obj(journal=journal, logs=logs, horloge=horloge, get_db=get_db)
    #  Des verrous liés à la boucle d'un test, des gestes ou une photo d'un test : rien ne passe au suivant.
    for d in (K._verrous, K._en_cours, K._annonces_faites, K._actifs, K._vocal, K._tampon, K._minuteurs,
              I._verrous, I._perimees, I._photos):
        d.clear()


def serveur():
    g = Monde()
    g.voice_channels, g.stage_channels, g.afk_channel, g.premium_subscriber_role = [], [], None, None
    return g


def _lancer(g, **kw):
    salon = run(K.salon_cadeaux(g, creer=True))
    lien, erreur = run(K.lancer(g, g.membre(1), K.Brouillon(**{"lot": "Nitro", "duree": "2h", **kw})))
    assert erreur == "" and lien
    return salon


def _ecrire(env, g, uid, n):
    K._juge.oublier()    # 29/10/2026 : un seul « bonjour » compte par jour, plus de copié-collé — des phrases variées
    for _k in range(n):
        env.horloge[0] += 5
        assert K.sur_message(Obj(id=int(env.horloge[0] * 10) + uid, guild=g, author=Obj(id=uid, bot=False),
                                 content=f"je raconte ma partie de ce soir, épisode {env.horloge[0]} !", webhook_id=None, type=discord.MessageType.default,
                                 attachments=[], stickers=[]))


def _inscrire(*uids, cid=1):
    for uid in uids:
        run(K._ecrire("INSERT INTO cadeaux_inscrits(cadeau_id, membre_id, quand) VALUES(?, ?, ?)", (cid, uid, uid)))


def _requete(sql, args=()):
    async def lire():
        async with K._get_db() as db:
            async with db.execute(sql, args) as cur:
                return await cur.fetchall()
    return run(lire())


class _Proxy:
    """Une connexion dont une requête choisie échoue (la base occupée) ou traîne (une écriture lente)."""

    def __init__(self, db, panne=None, lent=None):
        self._db, self._panne, self._lent = db, panne, lent

    def __getattr__(self, nom):
        return getattr(self._db, nom)

    def execute(self, sql, *a):
        if self._panne and self._panne(sql):
            raise sqlite3.OperationalError("database is locked")
        return self._db.execute(sql, *a)

    async def executemany(self, sql, args):
        if self._lent:
            await asyncio.sleep(self._lent)
        return await self._db.executemany(sql, args)


def _base_modifiee(get_db, **kw):
    @contextlib.asynccontextmanager
    async def g():
        async with get_db() as db:
            yield _Proxy(db, **kw)
    return g


def _vue(i):
    """Ce que voit le membre : la réponse différée, sinon la réponse directe."""
    return (i.suivis or i.response.messages)[-1][1]["view"]


def _desactives(vue) -> list:
    return [getattr(x, "item", x).disabled for x in vue.walk_children()
            if isinstance(getattr(x, "item", x), (discord.ui.Button, BaseSelect))]


def _longueur(vue) -> int:
    """Le texte d'un message Components V2, compté large : TextDisplay, libellés, textes d'aide."""
    return len(textes(vue))


# ─── R1 · S1 : « Lancer » cliqué deux fois publiait deux cadeaux ──────────────

def test_R1_double_clic_sur_lancer_un_seul_cadeau(env):
    g = serveur()
    f = g.membre(1)
    salon = run(K.salon_cadeaux(g, creer=True))
    vue = K.VueCadeau(f, g, K.Brouillon(lot="Nitro", duree="2h"))

    async def double_clic():
        i1, i2 = interaction(g, f), interaction(g, f)
        await asyncio.gather(vue._cb_lancer(i1), vue._cb_lancer(i2))
        return i1, i2
    i1, i2 = run(double_clic())
    assert len(run(K.recents(g.id, 10))) == 1 and len(salon.envois) == 2, "un cadeau, une carte (après l'accueil)"
    publication = i1.response.edits[0]["view"]
    assert "Publication du cadeau" in textes(publication) and all(_desactives(publication)), \
        "le premier clic éteint tout AVANT de publier (au lieu d'un defer)"
    assert compter(publication) <= 40
    assert i2.response.fait and not (i2.response.edits or i2.response.messages or i2.suivis), \
        "le second clic est acquitté sans rien publier"
    assert "Cadeau lancé" in textes(i1.suivis[-1][1]["view"])
    i3 = interaction(g, f)
    run(vue._cb_lancer(i3))
    run(vue._cb_mention(interaction(g, f)))
    assert len(run(K.recents(g.id, 10))) == 1 and vue.b.mention == "", "un clic resté en route : rien ne repart"


def test_R1b_publication_refusee_rien_ne_reste_on_peut_reessayer(env):
    g = serveur()
    f = g.membre(1)
    salon = run(K.salon_cadeaux(g, creer=True))
    vue = K.VueCadeau(f, g, K.Brouillon(lot="Nitro", duree="2h"))
    salon.panne = True
    i = interaction(g, f)
    run(vue._cb_lancer(i))
    refus = i.suivis[-1][1]["view"]
    assert "Discord a refusé" in textes(refus) and not _bouton(refus, "Lancer").disabled, "on peut réessayer"
    assert _requete("SELECT COUNT(*) FROM cadeaux")[0][0] == 0 and not K._actifs, "rien ne reste"
    assert not vue.b.envoi_en_cours and not vue.b.lien_publie
    salon.panne = False
    i = interaction(g, f)
    run(vue._cb_lancer(i))
    assert "Cadeau lancé" in textes(i.suivis[-1][1]["view"]) and len(run(K.recents(g.id, 10))) == 1


# ─── R2 · S0 : « Nouveau tirage » cliqué deux fois ajoutait deux gagnants ────

def _bouton(vue, debut):
    return next(b for b in vue.walk_children() if isinstance(b, discord.ui.Button) and (b.label or "").startswith(debut))


def test_R2_double_clic_nouveau_tirage_un_seul_gagnant(env):
    g = serveur()
    f = g.membre(1)
    _lancer(g)
    for uid in (21, 22, 23, 24):
        g.membre(uid)
    _inscrire(21, 22, 23, 24)
    run(K.terminer(g, 1))
    assert len(run(K.charger(1))["resultat"]["gagnants"]) == 1
    panneau = run(K.vue_un_cadeau(f, g, 1))
    relance = _bouton(panneau, "Nouveau tirage")

    async def double_clic():
        i1, i2 = interaction(g, f), interaction(g, f)
        await asyncio.gather(relance.callback(i1), relance.callback(i2))
        return i1, i2
    i1, i2 = run(double_clic())
    assert len(run(K.charger(1))["resultat"]["gagnants"]) == 2, "un clic de trop n'ajoute pas un gagnant"
    assert "Nouveau tirage…" in textes(i1.response.edits[0]["view"]), "le panneau s'éteint d'abord"
    assert "Nouveau gagnant" in textes(i1.suivis[-1][1]["view"])
    assert i2.response.fait and not (i2.response.edits or i2.suivis), "le second clic : acquitté, rien de plus"
    #  Le même bouton, resté sur un panneau d'avant (un gagnant) : refusé, et le panneau se met à jour.
    i3 = interaction(g, f)
    run(relance.callback(i3))
    assert len(run(K.charger(1))["resultat"]["gagnants"]) == 2
    assert "vient déjà d'être fait" in textes(i3.suivis[-1][1]["view"])
    nouveau, raison = run(K.relancer(g, 1, attendu=1))
    assert nouveau is None and "vient déjà" in raison
    nouveau, _r = run(K.relancer(g, 1, attendu=2))
    assert nouveau and len(run(K.charger(1))["resultat"]["gagnants"]) == 3, "le bon nombre : il tire"


def test_R2b_double_clic_sur_oui_tirer_un_seul_geste(env):
    g = serveur()
    f = g.membre(1)
    _lancer(g)
    oui = _bouton(run(K.vue_un_cadeau(f, g, 1, confirmer="tirer")), "Oui")

    async def double_clic():
        i1, i2 = interaction(g, f), interaction(g, f)
        await asyncio.gather(oui.callback(i1), oui.callback(i2))
        return i1, i2
    i1, i2 = run(double_clic())
    assert "Tirage fait" in textes(i1.suivis[-1][1]["view"]) and not i2.suivis, \
        "le panneau dit « Tirage fait », pas « n'était plus en cours »"


# ─── R3 · S1 : le tirage d'un seul coup ; l'annonce interrompue est rattrapée ──

def test_R3_le_tirage_s_ecrit_d_un_seul_coup(env, monkeypatch):
    g = serveur()
    _lancer(g, msg_min=1)
    for uid in (11, 12):
        g.membre(uid)
        _ecrire(env, g, uid, 1)
    _inscrire(11, 12)
    monkeypatch.setattr(K, "_get_db", _base_modifiee(env.get_db,
                                                     panne=lambda sql: "DELETE FROM cadeaux_inscrits" in sql))
    with pytest.raises(sqlite3.OperationalError):
        run(K.terminer(g, 1))
    monkeypatch.setattr(K, "_get_db", env.get_db)
    c = run(K.charger(1))
    assert c["statut"] == "actif" and c["resultat"] == {}, "rien d'écrit : pas de cadeau « fini » à moitié"
    assert run(K.inscrits(1)) == [11, 12] and set(run(K._stats_en_base(1))) == {11, 12}
    assert run(K.terminer(g, 1)) is not None and run(K.charger(1))["statut"] == "fini"
    assert run(K.inscrits(1)) == [] and run(K._stats_en_base(1)) == {}


def test_R3b_une_annonce_interrompue_est_refaite_une_seule_fois(env, monkeypatch):
    g = serveur()
    salon = _lancer(g)
    g.membre(11)
    _inscrire(11)
    vraie = K.maj_carte

    async def coupure(*_a, **_k):
        raise asyncio.CancelledError()   # la mise en ligne (SIGTERM) coupe le minuteur juste après le résultat
    monkeypatch.setattr(K, "maj_carte", coupure)
    with pytest.raises(asyncio.CancelledError):
        run(K.terminer(g, 1))
    monkeypatch.setattr(K, "maj_carte", vraie)
    c = run(K.charger(1))
    assert c["statut"] == "fini" and c["resultat"]["gagnants"] == [11] and c["resultat"]["annonce_id"] == 0
    assert not salon.cartes, "coupé : la carte est restée « en cours », personne n'a été pingé"
    annonces = len(salon.envois)
    run(K.tic([g]))
    c = run(K.charger(1))
    assert len(salon.envois) == annonces + 1 and c["resultat"]["annonce_id"] == salon.envois[-1][0]
    annonce = salon.envois[-1][2]
    assert "<@11>" in textes(annonce["view"]) and [u.id for u in annonce["allowed_mentions"].users] == [11]
    assert "terminé" in textes(salon.cartes[-1][1]["view"]), "la carte n'affiche plus « Participer »"
    assert any(t == "cadeaux.annonce" and "refaites" in x for t, x in env.journal)
    run(K.tic([g]))
    assert len(salon.envois) == annonces + 1, "une seule fois"


def test_R3c_annonce_impossible_un_seul_nouvel_essai_puis_c_est_dit(env):
    g = serveur()
    salon = _lancer(g)
    g.membre(11)
    _inscrire(11)
    salon.panne = True
    run(K.terminer(g, 1))
    assert run(K.charger(1))["resultat"]["annonce_id"] == 0, "ratée : à refaire"
    assert "[CADEAUX][E3] gagnants non annoncés" in env.logs
    run(K.tic([g]))
    assert run(K.charger(1))["resultat"]["annonce_id"] == -1, "un seul nouvel essai, puis c'est noté"
    assert any(t == "cadeaux.annonce" and "préviens-les" in x for t, x in env.journal)
    salon.panne = False
    envois = len(salon.envois)
    run(K.tic([g]))
    assert len(salon.envois) == envois, "plus d'essai toutes les 30 s"


def test_R3d_un_tirage_ancien_n_est_jamais_annonce_de_nouveau(env):
    """Les cadeaux finis avant ce correctif n'ont pas de note d'annonce : ils ne sont pas ré-annoncés."""
    g = serveur()
    salon = _lancer(g)
    run(K._ecrire("UPDATE cadeaux SET statut='fini', resultat=? WHERE id=1", ('{"gagnants": [11]}',)))
    envois = len(salon.envois)
    run(K.tic([g]))
    assert len(salon.envois) == envois


# ─── R4 · S2 : une purge en masse retire aussi les messages comptés ──────────

def test_R4_la_purge_en_masse_decompte_les_messages(env):
    assert 'bot.add_listener(_cadeaux_effacement_masse, "on_raw_bulk_message_delete")' in SRC
    g = serveur()
    _lancer(g)
    ids_ = []
    K._juge.oublier()
    for _k in range(3):
        env.horloge[0] += 5
        mid = int(env.horloge[0] * 10)
        ids_.append(mid)
        assert K.sur_message(Obj(id=mid, guild=g, author=Obj(id=7, bot=False), content=f"on lance le raid, étape {mid} !", webhook_id=None,
                                 type=discord.MessageType.default, attachments=[], stickers=[]))
    erreurs = []
    ns = {"cadeaux": K, "_logerr": lambda *a, **k: erreurs.append(a)}
    exec(_source("_cadeaux_effacement_masse"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["_cadeaux_effacement_masse"](Obj(message_ids={ids_[0], ids_[1], 999}, guild_id=g.id)))
    assert K._tampon[(1, 7)][0] == 1 and not erreurs, "/mod clear : les deux messages purgés ne comptent plus"


# ─── R5 · S2 : après une reconnexion, le vocal suit l'état réel ──────────────

def test_R5_le_vocal_suit_l_etat_reel_apres_une_reconnexion(env, monkeypatch):
    mur = [100_000.0]
    monkeypatch.setattr(K, "_mur", lambda: mur[0])
    g = serveur()
    salon_vocal, afk = Obj(id=50, members=[]), Obj(id=99, members=[])
    g.voice_channels, g.afk_channel = [salon_vocal, afk], afk
    _lancer(g)
    parti, arrive, sourd, en_afk = g.membre(7), g.membre(8), g.membre(9), g.membre(10)
    for m, ch, deaf in ((parti, salon_vocal, False), (sourd, salon_vocal, False)):
        m.voice = Obj(channel=ch, self_deaf=deaf, deaf=False)
        ch.members.append(m)
        K.sur_vocal(m, Obj(channel=None), m.voice)
    mur[0] += 30
    run(K.tic([g]))
    assert run(K.stats(1, 7)) == (0, 30), "compté tant qu'il est là"
    #  La coupure : discord.py reconstruit son cache, sans un mot pour ceux qui ont bougé entre-temps.
    parti.voice = None
    salon_vocal.members.remove(parti)
    sourd.voice = Obj(channel=salon_vocal, self_deaf=True, deaf=False)
    arrive.voice = Obj(channel=salon_vocal, self_deaf=False, deaf=False)
    en_afk.voice = Obj(channel=afk, self_deaf=False, deaf=False)
    salon_vocal.members.append(arrive)
    afk.members.append(en_afk)
    mur[0] += 30
    run(K.tic([g]))
    assert (g.id, 7) not in K._vocal and (g.id, 9) not in K._vocal, "parti, casque coupé : le segment s'arrête"
    assert (g.id, 8) in K._vocal and (g.id, 10) not in K._vocal, "arrivé pendant la coupure : il compte ; l'AFK non"
    for _k in range(4):
        mur[0] += 30
        run(K.tic([g]))
    assert run(K.stats(1, 7))[1] == 30, "parti : plus jamais crédité (avant : +30 s à chaque passage, sans fin)"
    assert run(K.stats(1, 8))[1] == 120


# ─── R6 · S2 : un lancement ne fige plus la liste des cadeaux en cours ───────

def test_R6_la_liste_des_cadeaux_en_cours_suit_la_base(env, monkeypatch):
    g = serveur()
    _lancer(g, lot="Un")
    _lancer(g, lot="Deux")
    K._actifs.clear()
    K._charges.clear()      # le redémarrage : la mémoire est vide
    vraie = K._SQL_ACTIFS
    monkeypatch.setattr(K, "_SQL_ACTIFS", "SELECT nope FROM cadeaux")   # la base refuse au premier passage
    run(K.tic([g]))
    assert "[CADEAUX][E4] cadeaux en cours non rechargés" in env.logs and not K._actifs
    monkeypatch.setattr(K, "_SQL_ACTIFS", vraie)
    _lancer(g, lot="Trois")
    assert set(K._actifs[g.id]) == {3}
    run(K.tic([g]))
    assert set(K._actifs[g.id]) == {1, 2, 3}, "les deux autres comptent de nouveau (et seront tirés)"
    run(K._ecrire("UPDATE cadeaux SET statut='annule' WHERE id=2", ()))
    run(K.tic([g]))
    assert set(K._actifs[g.id]) == {1, 3}, "fini ailleurs : il sort de la mémoire"
    run(K._ecrire("UPDATE cadeaux SET fin=? WHERE id=1", (int(K._mur()) - 1,)))
    assert run(K.tic([g])) == 1 and run(K.charger(1))["statut"] == "fini"


def test_R6b_la_carte_publiee_compte_meme_si_sa_note_echoue(env, monkeypatch):
    g = serveur()
    run(K.salon_cadeaux(g, creer=True))
    monkeypatch.setattr(K, "_get_db", _base_modifiee(env.get_db,
                                                     panne=lambda sql: "SET message_id" in sql))
    lien, erreur = run(K.lancer(g, g.membre(1), K.Brouillon(lot="Nitro", duree="2h")))
    monkeypatch.setattr(K, "_get_db", env.get_db)
    assert lien and erreur == "", "publié : c'est un succès (un nouveau clic publierait un second cadeau)"
    assert "[CADEAUX][E17] carte publiée non notée" in env.logs
    assert K._actifs[g.id] == {1: float(run(K.charger(1))["debut"])}, "il compte tout de suite"
    run(K.tic([g]))
    assert set(K._actifs[g.id]) == {1}


# ─── R7 · S2 : acquitter d'abord, la base ensuite ────────────────────────────

def _clic(g, membre, journal, *, ephemere=False):
    i = interaction(g, membre)
    rep = i.response
    defer, envoyer = rep.defer, rep.send_message

    async def defer_(**kw):
        journal.append(("acquitté", kw))
        await defer(**kw)

    async def envoyer_(content=None, **kw):
        journal.append(("réponse", {}))
        await envoyer(content, **kw)
    rep.defer, rep.send_message = defer_, envoyer_
    if ephemere:
        i.message = Obj(flags=Obj(ephemeral=True))
    return i


def test_R7_les_boutons_de_la_carte_repondent_avant_la_base(env, monkeypatch):
    g = serveur()
    _lancer(g, msg_min=1)
    g.membre(11)
    _ecrire(env, g, 11, 1)
    journal = []
    vraie = env.get_db

    @contextlib.asynccontextmanager
    async def espion():
        journal.append(("base", {}))
        async with vraie() as db:
            yield db
    monkeypatch.setattr(K, "_get_db", espion)
    for bouton in (K.BoutonParticiper(1), K.BoutonStats(1), K.BoutonQuitter(1), K.BoutonParticipants(1)):
        journal.clear()
        i = _clic(g, g.membre(11), journal)
        run(bouton.callback(i))
        assert journal[0] == ("acquitté", {"ephemeral": True, "thinking": True}), type(bouton).__name__
        assert i.suivis[-1][1]["ephemeral"], "depuis la carte : la réponse suit, pour soi"
    for bouton in (K.BoutonActualiser(1), K.BoutonPage(1, 0)):
        journal.clear()
        i = _clic(g, g.membre(11), journal, ephemere=True)
        run(bouton.callback(i))
        assert journal[0] == ("acquitté", {}) and i.suivis[-1][0] == "edit", "depuis un message pour soi : réécrit"
    journal.clear()
    i = _clic(g, g.membre(1), journal, ephemere=True)
    run(K.montrer_participants(i, 1, 0, nouveau=True))
    assert journal[0] == ("acquitté", {"ephemeral": True, "thinking": True}) and i.suivis[-1][0] is None
    journal.clear()
    i = _clic(g, g.membre(1), journal)
    run(K.ouvrir_gestion(i))
    assert [x for x, _k in journal][:1] == ["acquitté"] and "Nouveau cadeau" in textes(i.suivis[-1][1]["view"])


def test_R7c_une_erreur_apres_l_acquittement_repond_quand_meme(env, monkeypatch):
    """Acquitté d'abord, un bouton persistant qui échoue laisserait « … réfléchit » tourner : il répond."""
    g = serveur()
    _lancer(g)

    async def panne(_cid):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(K, "charger", panne)
    i = interaction(g, g.membre(11))
    with pytest.raises(sqlite3.OperationalError):
        run(K.BoutonParticiper(1).callback(i))
    assert "Un souci est survenu" in textes(i.suivis[-1][1]["view"]) and i.suivis[-1][1]["ephemeral"]
    assert "[CADEAUX][E19] bouton en échec" in env.logs


def test_R7b_le_refus_pour_soi_s_efface_toujours(env, monkeypatch):
    monkeypatch.setattr(K, "AVIS_S", 0)
    g = serveur()
    _lancer(g, msg_min=3)
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
    assert "Pas encore" in textes(_vue(i)) and effaces == ["refus"]


# ─── R8 · S3 : les courses du tirage ─────────────────────────────────────────

def test_R8_le_tirage_attend_les_compteurs_en_route(env, monkeypatch):
    g = serveur()
    _lancer(g, msg_min=2)
    g.membre(11)
    _ecrire(env, g, 11, 2)            # en mémoire, pas encore en base
    _inscrire(11)
    monkeypatch.setattr(K, "_get_db", _base_modifiee(env.get_db, lent=0.2))

    async def scenario():
        en_route = asyncio.create_task(K.vider())   # le passage de la boucle : sorti de la mémoire, en écriture
        await asyncio.sleep(0.05)
        c = await K.terminer(g, 1)
        await en_route
        return c
    c = run(scenario())
    monkeypatch.setattr(K, "_get_db", env.get_db)
    assert c["resultat"]["gagnants"] == [11], "ses deux messages étaient en route : le tirage les a attendus"
    assert _requete("SELECT COUNT(*) FROM cadeaux_stats")[0][0] == 0, "aucune ligne orpheline après le ménage"


def test_R8b_un_clic_a_la_derniere_seconde_n_est_pas_un_faux_tu_participes(env, monkeypatch):
    g = serveur()
    _lancer(g)
    vraie = K._stats_en_base

    async def lente(cid):
        await asyncio.sleep(0.2)          # le tirage a lu les inscrits, il calcule
        return await vraie(cid)
    monkeypatch.setattr(K, "_stats_en_base", lente)

    async def scenario():
        tirage = asyncio.create_task(K.terminer(g, 1))
        await asyncio.sleep(0.05)
        i = interaction(g, g.membre(30))
        await K.participer(i, 1)
        await tirage
        return i
    i = run(scenario())
    assert "terminé" in textes(_vue(i)) and "Tu participes" not in textes(_vue(i))
    assert _requete("SELECT COUNT(*) FROM cadeaux_inscrits")[0][0] == 0, "aucune inscription orpheline"


# ─── R9 · S3 : une arrivée ignorée rend la photo des liens périmée ───────────

def _serveur_liens(liens):
    g = serveur()
    g.me.guild_permissions.manage_guild = True
    g.lectures, g.refus = 0, False

    async def invites():
        g.lectures += 1
        if g.refus:
            raise discord.HTTPException(Obj(status=500, reason="x"), "panne")
        return [Obj(code=c, inviter=Obj(id=a), uses=n, max_uses=0) for c, a, n in liens]
    g.invites = invites
    return g


def _arrivant(g, uid):
    m = g.membre(uid)
    m.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    return m


def test_R9_l_arrivee_d_apres_n_est_pas_creditee_au_mauvais_lien(env):
    liens = [["aaa", 7, 0], ["bbb", 8, 0]]
    g = _serveur_liens(liens)
    run(I.photographier(g))

    async def scenario():
        async with I._verrou(g.id):           # une arrivée en cours (sa lecture des liens est faite)
            liens[0][2] = 1                    # pendant ce temps, Y arrive par « aaa »…
            assert await I.sur_arrivee(_arrivant(g, 30)) == 0     # …ignoré : la rafale
        return await I.sur_arrivee(_arrivant(g, 31))           # Z arrive par le lien personnalisé
    assert asyncio.run(scenario()) == 0 and run(I.total(g.id, 7)) == 0, \
        "Z n'est pas crédité au propriétaire de « aaa » (le lien de Y)"
    liens[1][2] = 1
    assert run(I.sur_arrivee(_arrivant(g, 32))) == 8, "la photo est neuve : l'arrivée suivante compte"
    g.refus = True
    assert run(I.sur_arrivee(_arrivant(g, 33))) == 0
    g.refus = False
    liens[0][2] = 2                            # 33 était arrivé par « aaa » pendant la panne
    assert run(I.sur_arrivee(_arrivant(g, 34))) == 0, "liens illisibles : la comparaison suivante ne devine pas"
    assert run(I.total(g.id, 7)) == 0


# ─── R10 · S3 : avant le branchement (le démarrage), rien n'échoue ───────────

def test_R10_avant_setup_les_boutons_le_disent_les_ecouteurs_se_taisent(env, monkeypatch):
    monkeypatch.setattr(K, "DEMARRE_S", 0)
    for nom in ("_get_db", "_cfg", "_db_set", "_autorise", "_journal", "_langue"):
        monkeypatch.setattr(K, nom, None)
    g = serveur()
    boutons = [K.BoutonParticiper(1), K.BoutonStats(1), K.BoutonActualiser(1), K.BoutonQuitter(1),
               K.BoutonCadeaux(), K.BoutonParticipants(1), K.BoutonPage(1, 0), K.ChoixParticipant(1, 0),
               K.BoutonChercher(1)]

    async def cliquer(bouton):
        i = interaction(g, g.membre(11))
        i.data = {"values": ["11"]}
        effaces = []

        async def supprimer():
            effaces.append(1)
        i.delete_original_response = supprimer
        await bouton.callback(i)
        await asyncio.sleep(0.02)
        return i, effaces
    for bouton in boutons:
        i, effaces = asyncio.run(cliquer(bouton))
        _c, kw = i.response.messages[-1]
        assert kw["ephemeral"] and "Le bot démarre, réessaie dans quelques secondes." in textes(kw["view"]), \
            type(bouton).__name__
        assert effaces == [1], "le mot pour soi s'efface"
    for f in (K.ouvrir_composeur, K.ouvrir_gestion):
        i = interaction(g, g.membre(1))
        run(f(i))
        assert "Le bot démarre" in textes(i.response.messages[-1][1]["view"])
    #  Les écouteurs : rien à faire, rien d'écrit, aucune erreur.
    erreurs = []
    ns = {"cadeaux": K, "invitations": I, "_logerr": lambda *a, **k: erreurs.append(a)}
    for nom in ("_cadeaux_message", "_cadeaux_vocal", "_cadeaux_effacement", "_cadeaux_effacement_masse",
                "_invitations_lien", "_invitations_arrivee", "_invitations_depart"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    monkeypatch.setattr(I, "_get_db", None)
    liens_lus = []

    async def invites():
        liens_lus.append(1)
        return []
    g.invites = invites
    m = _arrivant(g, 40)
    message = Obj(id=1, guild=g, author=Obj(id=40, bot=False), content="salut, je découvre le serveur", webhook_id=None,
                  type=discord.MessageType.default, attachments=[], stickers=[])

    async def ecouter():
        await ns["_cadeaux_message"](message)
        await ns["_cadeaux_vocal"](m, Obj(channel=None), Obj(channel=Obj(id=5), self_deaf=False, deaf=False))
        await ns["_cadeaux_effacement"](Obj(message_id=1, guild_id=g.id))
        await ns["_cadeaux_effacement_masse"](Obj(message_ids={1, 2}, guild_id=g.id))
        await ns["_invitations_lien"](Obj(guild=g, code="x", inviter=Obj(id=1), uses=0, max_uses=0))
        await ns["_invitations_arrivee"](m)
        await ns["_invitations_depart"](m)
    asyncio.run(ecouter())
    assert not erreurs and not liens_lus and not (K._tampon or K._vocal or K._comptes)
    V._renommages.clear()
    monkeypatch.setattr(V, "_proprio", None)
    i = interaction(g, g.membre(7))
    run(V.choisir(i, 77, "farm"))
    _c, kw = i.response.messages[-1]
    assert kw["ephemeral"] and kw["delete_after"] and "Le bot démarre" in textes(kw["view"])


# ─── R11 · S3 : les limites de Discord, au pire cas ──────────────────────────

def test_R11_les_vues_tiennent_dans_les_limites_au_pire_cas(env):
    g = serveur()
    f = g.membre(1)
    run(K.salon_cadeaux(g, creer=True))
    grand = 10 ** 18
    b = K.Brouillon(lot="L" * K.LOT_MAX, details="D" * K.DETAILS_MAX, gagnants=20, duree="2h", image=b"x",
                    image_ext="png", roles=[grand + k for k in range(5)], exclus=[grand + 10 + k for k in range(5)],
                    msg_min=100000, voc_min=100000, inv_min=99999, anc_min=9999, logique="ou",
                    chance_roles=[grand + 20 + k for k in range(5)], multiplicateur=9.99, mention="everyone")
    pires = [K.VueCadeau(f, g, b, ["E" * 300, "F" * 300])]
    b.envoi_en_cours = True
    pires.append(K.VueCadeau(f, g, b))
    b.envoi_en_cours = False
    for n in range(8):
        lien, _e = run(K.lancer(g, f, K.Brouillon(lot=f"{n}" * K.LOT_MAX, details="D" * K.DETAILS_MAX,
                                                    duree="2h", gagnants=20, roles=[grand + k for k in range(5)],
                                                    exclus=[grand + 10 + k for k in range(5)], msg_min=5, voc_min=5,
                                                    inv_min=5, anc_min=5)))
        assert lien
    gagnants = [grand + 100 + k for k in range(80)]
    for cid in range(1, 9):
        run(K._ecrire("UPDATE cadeaux SET statut='fini', resultat=? WHERE id=?",
                      (K.json.dumps({"gagnants": gagnants, "inscrits": 500, "eligibles_n": 400, "fini": 1}), cid)))
    pires.append(run(K.vue_gestion(f, g)))
    pires.append(run(K.vue_un_cadeau(f, g, 1)))
    pires.append(run(K.vue_un_cadeau(f, g, 1, note="⚠️ " + "N" * 200)))
    pires.append(K.vue_carte(run(K.charger(1)), 0))
    c_actif = dict(run(K.charger(1)), statut="actif", chance_roles=[grand + 20 + k for k in range(5)],
                   multiplicateur=9.99, mention="@everyone")
    pires.append(K.vue_carte(c_actif, 10 ** 6))
    pires.append(K.vue_stats(c_actif, g.membre(5), 10 ** 6, 10 ** 9, True, "fr", entete=K.tr("retiree"),
                             invitations=10 ** 5))
    pires.append(K.vue_gagnants(run(K.charger(1)), gagnants[:20], ticket=Obj(jump_url="https://discord.com/x")))
    for uid in range(100, 160):
        g.membre(uid)
        _inscrire(uid, cid=1)
    run(K._ecrire("UPDATE cadeaux SET statut='actif' WHERE id=1", ()))
    pires.append(run(K.vue_participants(g, run(K.charger(1)), 0)))
    for v in pires:
        assert compter(v) <= 40, (type(v).__name__, compter(v))
        assert _longueur(v) <= 4000, (type(v).__name__, _longueur(v))
    t = textes(pires[2])
    assert "+77" in t and t.count("<@") <= 8 * 3, "trois gagnants nommés par ligne, puis « +N »"
    assert "+55" in textes(pires[3]), "Gérer : 25 gagnants nommés"


# ─── R12 · S3 : le ménage n'oublie plus les annonces d'un salon disparu ──────

def test_R12_le_menage_oublie_les_annonces_d_un_salon_supprime(env, monkeypatch):
    g = serveur()
    salon = _lancer(g)
    g.membre(11)
    _inscrire(11)
    run(K.terminer(g, 1))
    #  Une annonce d'un autre serveur (son cadeau y est) : elle attend le passage de son serveur.
    run(K._ecrire("INSERT INTO cadeaux(guild_id, salon_id, auteur_id, lot, debut, fin, statut) "
                  "VALUES(2, 777, 1, 'Ailleurs', 0, 0, 'fini')", ()))
    run(K._ecrire("INSERT INTO cadeaux_messages(message_id, salon_id, effacer_a) VALUES(4242, 777, 0)", ()))
    run(K._ecrire("UPDATE cadeaux_messages SET effacer_a=0", ()))
    run(salon.delete())
    assert run(K.purger(g)) == 0
    assert [r[0] for r in _requete("SELECT message_id FROM cadeaux_messages")] == [4242], \
        "le salon supprimé : sa ligne part ; l'autre serveur garde la sienne"
