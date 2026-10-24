"""24/10/2026 — revue « systèmes restants » : annonces, casier, notifications, boosts, récidivistes,
sondages, pings Roblox, ménage des salons, actualités Roblox.

Constats corrigés (chaque test échoue sur le code d'avant) :
   1. « Publier » deux fois = deux annonces (deux @everyone) ; « réessaie » après une erreur alors
      que l'annonce était partie ;
   2. « 🎉 Bienvenue dans l'équipage » publique pour un rôle du clan qui REVIENT ; plus de 100
      arrivées d'une minute = message refusé, personne d'accueilli ;
   3. une amnistie défaite ne tenait pas 24 h ;
   4. le ménage des 30 jours retirait les annonces publiées dans les salons de flux ;
   5. « Modifier » impossible quand les liens pré-remplis dépassaient 800 caractères ;
   6. une actualité Roblox publiée deux fois (passages simultanés) ;
   7. « Me prévenir » qui désabonne ;
   8. « Mention : le clan » qui ne notifie personne sans le dire ;
   9. chaque départ relisait le salon des boosts (et l'erreur d'un post supprimé) ;
  10. une erreur de base libérait un récidiviste ; un rôle retiré à la main laissait l'état incohérent ;
  11. réponses fausses : catégorie de ping retirée, sondage d'un post archivé « retiré » sans l'être ;
  12. écarts aux règles : ping du clan en texte, avis des sondages en texte, démontage hors du site ;
  13. réponses garanties (notifications) et acquittement avant la base (annonces).
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord
import pytest
from discord.components import _component_factory

import annonces as A
import boosts as B
import casier
import nettoyage
import notifs
import recidivism as R
import registre
import roblox_news as news
import roblox_pings as pings
import sondages as S
import zones as ZN
from conftest_discord import Guilde, Obj, base
from faux_serveur import Message, Monde, Texte, Vocal, ids, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR = 781205382923288593
JOUR = 86400


def _source(nom):
    n = copy.deepcopy(next(n for n in ARBRE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.name == nom))
    n.decorator_list = []  # `@tasks.loop`…
    return ast.unparse(n)


def _absent():
    return discord.NotFound(Obj(status=404, reason="x"), "absent")


def bouton(vue, debut):
    return next(b for b in vue.walk_children() if isinstance(b, discord.ui.Button) and (b.label or "").startswith(debut))


def _texte_v2(vue) -> str:
    return " ".join(c.content for c in vue.walk_children() if isinstance(c, discord.ui.TextDisplay))


# ═══ Annonces : le banc de `test_annonces.py` ══════════════════════════════════════════════════

@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal, clan = [], {}

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))

    async def langue(_i):
        return "fr"
    monkeypatch.setattr(A, "MAJ_VUES_S", 0)
    monkeypatch.setattr(A, "ARRIVEES_S", 0)
    A._maj_prevues.clear()
    A._arrivees.clear()
    A.setup(get_db=get_db, cfg=cfg, db_set=db_set, est_tete=lambda g, m: m.id == FONDATEUR, journal=noter,
            role_clan=lambda g, c: clan.get("role"), langue=langue, log=lambda *a: None)
    asyncio.run(A.init_db())
    ZN.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    return Obj(conf=conf, journal=journal, clan=clan, get_db=get_db)


def serveur(env):
    g = Monde()
    info = g.categorie("· Information")
    g._salon(Texte, "📜annonce", {"category": info})
    sneak = g.categorie("· Sneak Peek")
    g._salon(Texte, "📀sneak-rellseas", {"category": sneak})
    clan = g.categorie("🦜 · GoRp_SEA")
    g._salon(Texte, "📢▷・info-gorp", {"category": clan})
    g._salon(Texte, "✍▷・chat-gorpsea", {"category": clan})
    g._salon(Vocal, "🔊Join", {"category": clan})
    role = run(g.create_role(name="GoRPC"))
    env.clan["role"] = role
    env.conf["rellseas_role"] = role.id
    return g


def _message_recu(g, salon, kw):
    """Le message tel que Discord l'a reçu (relu dans l'historique), boutons V2 compris."""
    m = Message(salon, g.nouvel_id())
    m.author = Obj(id=g.me.id, bot=True)
    m.components = [_component_factory(d) for d in kw["view"].to_components()]
    return m


# ═══ 1. « Publier » : une seule annonce ═══════════════════════════════════════════════════════

def test_R1_deux_clics_sur_publier_une_seule_annonce(env):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    salon = g.nom("📜annonce")
    envoyer = salon.send

    async def lent(content=None, **kw):  # Discord met un instant à répondre
        await asyncio.sleep(0.05)
        return await envoyer(content, **kw)
    salon.send = lent
    apercu = A.VueApercu(tete, g, A.Brouillon(salon_id=salon.id, titre="Grande nouvelle", texte="Ce soir.",
                                              mention="everyone"), (), env.conf)
    i1, i2 = interaction(g, tete), interaction(g, tete)

    async def deux_clics():
        await asyncio.gather(bouton(apercu, "Publier").callback(i1), bouton(apercu, "Publier").callback(i2))
    run(deux_clics())
    assert len(salon.envois) == 1, "un seul @everyone"
    attente = i1.response.edits[0]["view"]
    assert ids(attente) == [] and "Publication en cours" in textes(attente), "le bouton disparaît AVANT l'envoi"
    assert i2.response.messages[0][0] == "⏳ La publication est en cours."
    assert "✅ Annonce publiée" in textes(i1.suivis[-1][1]["view"])
    for nom in ("Publier", "Annuler", "Modifier"):  # un client resté sur l'ancien aperçu
        i = interaction(g, tete)
        run(bouton(apercu, nom).callback(i))
        assert i.response.messages[0][0].startswith("✅ Cette annonce est déjà publiée : https://"), nom
        assert not i.response.edits and not i.response.modals, "ni « abandonnée », ni formulaire"
    assert len(salon.envois) == 1


def test_R1_une_erreur_apres_l_envoi_ne_fait_pas_republier(env):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    salon = g.nom("📜annonce")

    async def recue_puis_erreur(content=None, **kw):  # un 503 alors que Discord a reçu l'annonce
        salon.historique.insert(0, _message_recu(g, salon, kw))
        raise discord.HTTPException(Obj(status=503, reason="x"), "indisponible")
    salon.send = recue_puis_erreur
    lien, erreur = run(A.publier(g, tete, A.Brouillon(salon_id=salon.id, titre="Maj", texte="Texte.")))
    m = salon.historique[0]
    assert erreur == "" and lien == m.jump_url, "partie : on ne dit pas « réessaie »"
    a = run(A.charger(1))
    assert a["message_id"] == m.id and a["fil_id"] in g.fils, "son message et son fil sont notés"
    assert env.journal[-1][0] == "annonce.publiee"

    async def refus(content=None, **kw):
        raise discord.HTTPException(Obj(status=500, reason="x"), "panne")
    salon.send = refus
    b = A.Brouillon(salon_id=salon.id, titre="Autre", texte="Texte.")
    apercu = A.VueApercu(tete, g, b, (), env.conf)
    i = interaction(g, tete)
    run(bouton(apercu, "Publier").callback(i))
    revue = i.suivis[-1][1]["view"]
    assert isinstance(revue, A.VueApercu) and "rien n'est parti, réessaie" in textes(revue)
    assert not bouton(revue, "Publier").disabled and b.etat == "", "rien n'est parti : l'aperçu revient, on réessaie"
    assert run(A.charger(2)) is None

    async def illisible(**_k):
        raise discord.HTTPException(Obj(status=503, reason="x"), "indisponible")
        yield  # noqa — un générateur asynchrone qui lève
    salon.history = illisible
    b = A.Brouillon(salon_id=salon.id, titre="Troisième", texte="Texte.")
    apercu = A.VueApercu(tete, g, b, (), env.conf)
    i = interaction(g, tete)
    run(bouton(apercu, "Publier").callback(i))
    carte = i.suivis[-1][1]["view"]
    assert b.etat == "incertaine" and ids(carte) == [] and "regarde le salon" in textes(carte), \
        "peut-être partie : pas de « Publier » à côté"
    assert run(A.charger(3))["message_id"] == 0, "la ligne reste : son « ✅ Vu » répondra si elle est partie"


def test_R1_apres_l_envoi_plus_rien_ne_fait_echouer(env, monkeypatch):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    salon = g.nom("📜annonce")

    async def journal_en_panne(*_a, **_k):
        raise aiosqlite.OperationalError("database is locked")
    monkeypatch.setattr(A, "_journal", journal_en_panne)
    lien, erreur = run(A.publier(g, tete, A.Brouillon(salon_id=salon.id, titre="Maj", texte="Texte.")))
    assert erreur == "" and lien and len(salon.envois) == 1 and run(A.charger(1))["message_id"] == salon.envois[0][0]


# ═══ 2. Le clan : un rôle qui revient n'est pas une arrivée ═══════════════════════════════════

def test_R2_un_role_du_clan_rendu_ne_dit_pas_bienvenue(env):
    g = serveur(env)
    role = env.clan["role"]
    run(ZN.installer_clan(g, role))
    salon = g.get_channel_or_thread(env.conf["clan_annonces"])
    n = len(salon.envois)
    run(A.sur_maj_membre(g.membre(60, role), g.membre(60)))      # radié : le rôle part…
    run(A.sur_maj_membre(g.membre(60), g.membre(60, role)))      # … et revient à la levée
    assert len(salon.envois) == n, "pas de « Bienvenue » pour qui était déjà dans le clan"

    async def il_y_a_31_jours():
        async with env.get_db() as db:
            await db.execute("UPDATE annonces_clan_retraits SET quand=?", (int(time.time()) - 31 * JOUR,))
            await db.commit()
    run(il_y_a_31_jours())
    run(A.sur_maj_membre(g.membre(60), g.membre(60, role)))
    assert len(salon.envois) == n + 1, "revenu au clan après plus de 30 jours : accueilli"
    avant, apres = g.membre(61), g.membre(61, role)
    apres.joined_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    run(A.sur_maj_membre(avant, apres))
    assert len(salon.envois) == n + 1, "rôles rendus à l'arrivée sur le serveur : pas une arrivée au clan"
    run(A.sur_maj_membre(g.membre(62), g.membre(62, role)))
    assert len(salon.envois) == n + 2 and "<@62> rejoint le clan" in textes(salon.envois[-1][-1]["view"])


def test_R2_cent_vingt_arrivees_accueillies_par_lots(env):
    g = serveur(env)
    role = env.clan["role"]
    run(ZN.installer_clan(g, role))
    salon = g.get_channel_or_thread(env.conf["clan_annonces"])
    n = len(salon.envois)
    for uid in range(1000, 1120):
        g.membre(uid, role)
    g.membre(1120)  # rôle repris dans la minute : plus à accueillir
    A._arrivees[g.id] = list(range(1000, 1121))
    run(A._annoncer_arrivees(g))
    cartes = salon.envois[n:]
    accueillis = [u.id for _c, kw in cartes for u in kw["allowed_mentions"].users]
    assert len(cartes) == 5 and all(len(kw["allowed_mentions"].users) <= A.ACCUEIL_LOT for _c, kw in cartes)
    assert accueillis == list(range(1000, 1120)), "tout le monde, une fois, et jamais qui n'a plus le rôle"


# ═══ 3. Une amnistie défaite tient ════════════════════════════════════════════════════════════

class Casier:
    def __init__(self, tmp_path):
        chemin = tmp_path / "c.db"

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(chemin)
            try:
                yield db
            finally:
                await db.close()
        self.get_db = get_db
        casier.setup(get_db=get_db, log=lambda *a: None)

        async def creer():
            async with get_db() as db:
                await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                                 " user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, duration TEXT,"
                                 " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
                await db.commit()
            await casier.init_db()
        asyncio.run(creer())

    def ajouter(self, uid, type_, jours):
        async def f():
            async with self.get_db() as db:
                await db.execute("INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, created_at)"
                                 " VALUES (1,?,2,?,'',?)", (uid, type_, (datetime.now(timezone.utc) - timedelta(
                                     days=jours)).strftime("%Y-%m-%d %H:%M:%S")))
                await db.commit()
        asyncio.run(f())

    def de(self, uid):
        async def f():
            async with self.get_db() as db:
                async with db.execute("SELECT type FROM infractions WHERE user_id=? ORDER BY id", (uid,)) as cur:
                    return [r[0] for r in await cur.fetchall()]
        return asyncio.run(f())


def test_R3_une_amnistie_defaite_ne_revient_pas_le_lendemain(tmp_path):
    c = Casier(tmp_path)
    c.ajouter(10, "warn", 120)
    c.ajouter(10, "mute", 100)
    bilan = asyncio.run(casier.amnistie(1, {10}, {}))
    assert c.de(10) == []
    asyncio.run(casier.restaurer(1, bilan["lot"], 3))
    assert c.de(10) == ["warn", "mute"]
    for jours in (1, 2, 30):
        assert asyncio.run(casier.amnistie(1, {10}, {}, maintenant=time.time() + jours * JOUR))["n"] == 0
    assert c.de(10) == ["warn", "mute"], "défaite, elle tient"
    c.ajouter(10, "warn", 100)  # une nouvelle entrée, puis trois mois sans rien : elle, elle part
    assert asyncio.run(casier.amnistie(1, {10}, {}))["n"] == 1 and c.de(10) == ["warn", "mute"]
    assert asyncio.run(casier.effacer_membre(1, 10, "tout", 3))["n"] == 2, "à la main, on efface tout"
    c.ajouter(20, "warn", 120)  # un nettoyage de zone défait : l'amnistie s'applique comme avant
    r = asyncio.run(casier.nettoyer(1, "warns", 0, 3, 999))
    asyncio.run(casier.restaurer(1, r["lot"], 3))
    assert c.de(20) == ["warn"] and asyncio.run(casier.amnistie(1, {20}, {}))["n"] == 1 and c.de(20) == []


# ═══ 4. Le ménage des 30 jours épargne les annonces ═══════════════════════════════════════════

class MsgVieux:
    def __init__(self, mid, auteur, vue=None):
        self.id, self.author, self.webhook_id, self.pinned = mid, Obj(id=auteur), None, False
        self.created_at = datetime.now(timezone.utc) - timedelta(days=60)
        self.components = [_component_factory(d) for d in vue.to_components()] if vue else []
        self.supprime = False

    async def delete(self):
        self.supprime = True


class SalonFlux:
    def __init__(self, messages):
        self.id, self._msgs = 70, messages

    async def webhooks(self):
        return []

    def history(self, **_k):
        async def gen():
            for m in self._msgs:
                yield m
        return gen()


def test_R4_le_menage_epargne_les_annonces(env, monkeypatch):
    style = A.STYLE_DEFAUT
    annonce = MsgVieux(1, 9, A.vue_annonce({"id": 5, "titre": "T", "texte": "X", "cree": 0}, style))
    connue = MsgVieux(2, 9)            # listée en base (son bouton a pu changer)
    actu = MsgVieux(3, 9)              # une vieille publication de flux : elle part
    membre = MsgVieux(4, 7)
    vrai_sommeil = asyncio.sleep
    monkeypatch.setattr(nettoyage.asyncio, "sleep", lambda _s: vrai_sommeil(0))
    n = asyncio.run(nettoyage.purger_salon(SalonFlux([annonce, connue, actu, membre]), 9, garder=frozenset({2})))
    assert n == 1 and actu.supprime and not (annonce.supprime or connue.supprime or membre.supprime)
    #  Le ménage lit les annonces publiées une fois par serveur et les passe aux deux purges.
    g = serveur(env)
    salon = g.nom("📀sneak-rellseas")
    run(A.publier(g, g.membre(FONDATEUR), A.Brouillon(salon_id=salon.id, titre="Sneak", texte="Texte.", fil=False)))
    assert run(A.messages_publies(g.id)) == frozenset({salon.envois[0][0]})
    appels = []

    async def purger(ch, bot_id, **kw):
        appels.append((ch, kw.get("garder")))
        return 0

    async def rien(*_a, **_k):
        return None

    async def flux(_g, _c):
        return {salon}

    async def logs(_g, _c):
        return set()

    async def cfg(_g):
        return {}
    ns = {"bot": Obj(guilds=[g], user=Obj(id=999)), "cfg": cfg, "annonces": A, "discord": discord,
          "nettoyage": Obj(purger_salon=purger, supprimer_vieux_fils=rien), "_salons_de_logs": logs,
          "_salons_de_flux": flux, "suggestions": Obj(assurer_panneau=rien), "boosts": Obj(synchroniser=rien),
          "_logerr": lambda *a, **k: appels.append(("ERREUR", a))}
    exec(_source("menage_salons_task"), ns)  # noqa: S102 — code du dépôt
    run(ns["menage_salons_task"]())
    assert appels == [(salon, frozenset({salon.envois[0][0]}))]


# ═══ 5. « Modifier » : le formulaire tient toujours ═══════════════════════════════════════════

def test_R5_modifier_une_annonce_aux_longs_liens():
    tapes = "\n".join(f"https://www.exemple-{k}.fr/" + "p" * 127 for k in range(5))  # le cas mesuré
    liens, _erreurs = A.lire_liens(tapes)
    assert len(tapes) <= 800 < len(A.liens_texte(liens))
    longs = [(f"Lien {k} " + "x" * 73, "https://exemple.fr/" + "a" * 490 + str(k)) for k in range(5)]  # 80 · 510
    for jeu in (liens, longs):
        form = A.FormulaireAnnonce(Obj(b=A.Brouillon(titre="T", texte="X", liens=jeu)))
        assert form.liens.max_length <= 4000 and len(form.liens.default) <= form.liens.max_length
        assert A.lire_liens(form.liens.default)[0] == jeu, "les mêmes liens reviennent, entiers"
    court = A.liens_texte(longs, 1300)
    assert A.lire_liens(court) == (longs[:2], []), "ce qui ne tient pas est laissé entier, jamais coupé"


# ═══ 6. Une actualité Roblox ne part qu'une fois ═══════════════════════════════════════════════

def _publieur(tmp_path, verrou):
    tmp_path.mkdir()
    get_db, cfg, db_set, conf = base(tmp_path)
    conf["roblox_news_salon"] = 77
    news.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None)
    asyncio.run(news.init_db())
    asyncio.run(news.enfiler_actu(1, {"topic_id": "t1", "titre": "Notes de version 700"}))
    envois, autres = [], []
    g = Obj(id=1, get_channel=lambda cid: Obj(id=cid))

    async def publier_actu(_g, _salon, b):
        premier = not autres
        if premier:  # pendant ce premier envoi, l'éclaireur et « Relever maintenant » passent à leur tour
            autres.extend(asyncio.create_task(ns["_publier_file_actualites"]([g])) for _ in range(2))
        await asyncio.sleep(0.3 if premier else 0.01)  # Discord met un instant à répondre
        envois.append(b["topic_id"])
        return True

    async def dormir(_s):
        await asyncio.sleep(0)
    ns = {"roblox_news_module": news, "roblox_ui": Obj(publier_actu=publier_actu), "asyncio": Obj(sleep=dormir),
          "_page_live_due": lambda *_a: False, "_VERROU_ACTUS": verrou}
    exec(_source("_publier_file_actualites"), ns)  # noqa: S102 — code du dépôt

    async def trois_passages():  # la veille, l'éclaireur et « Relever maintenant »
        bilans = [await ns["_publier_file_actualites"]([g])]
        return bilans + list(await asyncio.gather(*autres))
    return envois, asyncio.run(trois_passages())


class _SansVerrou:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


def test_R6_trois_passages_simultanes_une_seule_actualite(tmp_path):
    envois, _ = _publieur(tmp_path / "a", _SansVerrou())
    assert len(envois) > 1, "sans verrou, la ligne réservée en cours d'envoi repartait (le constat)"
    envois, bilans = _publieur(tmp_path / "b", asyncio.Lock())
    assert envois == ["t1"] and sum(b["publies"] for b in bilans) == 1
    assert "_VERROU_ACTUS = asyncio.Lock()" in SRC and "async with _VERROU_ACTUS:" in _source("_publier_file_actualites")


# ═══ 7. et 13. « Me prévenir · arrêter » : il dit ce qu'il fait, et répond toujours ════════════

def test_R7_le_bouton_de_notification_dit_qu_il_bascule_et_repond_toujours(monkeypatch):
    b = notifs.BoutonNotif("suggestions")
    assert b.item.label == "Me prévenir · arrêter" and b.item.custom_id == "notif:suggestions", \
        "même custom_id : les boutons déjà posés répondent toujours"
    suivis = []

    async def suivi(texte, **kw):
        suivis.append((texte, kw))

    async def defer(**_k):
        return None

    async def cfg_en_panne(_g):
        raise aiosqlite.OperationalError("database is locked")
    monkeypatch.setattr(notifs, "_cfg", cfg_en_panne)
    monkeypatch.setattr(notifs, "_log", lambda *a: None)
    i = Obj(guild=Guilde(), user=Obj(id=7, roles=[]), response=Obj(defer=defer), followup=Obj(send=suivi))
    asyncio.run(b.callback(i))
    assert suivis == [("Impossible pour le moment.", {"ephemeral": True})], "une réponse, même après une panne"


# ═══ 8. « Mention : le clan » qui ne notifiera personne : l'aperçu le dit ═════════════════════

def test_R8_la_mention_du_clan_qui_ne_partira_pas_est_annoncee(env):
    g = serveur(env)
    role = env.clan["role"]
    run(ZN.installer_clan(g, role))
    post = g.get_channel_or_thread(env.conf["clan_annonces"])
    tete = g.membre(FONDATEUR)
    b = A.Brouillon(salon_id=post.id, titre="Réunion", texte="Ce soir.", mention="clan")
    post.parent.refus = {"mention_everyone"}
    assert "personne ne sera notifié" in textes(A.VueApercu(tete, g, b, (), env.conf))
    role.mentionable = True
    assert "personne ne sera notifié" not in textes(A.VueApercu(tete, g, b, (), env.conf))
    role.mentionable, post.parent.refus = False, set()
    assert "personne ne sera notifié" not in textes(A.VueApercu(tete, g, b, (), env.conf))


# ═══ 9. Un départ sans carte de boost ne touche pas Discord ═══════════════════════════════════

def test_R9_un_depart_sans_carte_ne_relit_pas_le_salon_des_boosts(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    B._verrous.clear()
    B.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None)
    asyncio.run(B.init_db())
    conf["boosts_salon"] = 555
    appels = []

    async def post_supprime(cid):
        appels.append(cid)
        raise _absent()
    g = Obj(id=1, get_channel_or_thread=lambda _i: None, fetch_channel=post_supprime)
    assert asyncio.run(B.retirer(g, 42)) is False and appels == [], "pas de carte : Discord n'est pas dérangé"
    asyncio.run(B._noter(1, 42, 9000, "a"))
    assert asyncio.run(B.retirer(g, 42)) is True and appels == [555]
    assert conf["boosts_salon"] == 0, "le post supprimé est oublié : plus d'erreur à chaque départ"
    asyncio.run(B._noter(1, 43, 9001, "a"))
    assert asyncio.run(B.retirer(g, 43)) is True and appels == [555]


# ═══ 10. Récidivistes : une erreur ne libère personne, la ligne et le rôle disent la même chose ═

class Rang:
    def __init__(self, rid):
        self.id = rid

    def __eq__(self, autre):
        return getattr(autre, "id", None) == self.id

    def __hash__(self):
        return self.id


class MembreR:
    def __init__(self, uid, roles=()):
        self.id, self.bot, self.roles, self.faits = uid, False, list(roles), []

    async def add_roles(self, r, reason=None):
        self.roles.append(r)
        self.faits.append(("ajout", reason))

    async def remove_roles(self, r, reason=None):
        self.roles.remove(r)
        self.faits.append(("retrait", reason))


@pytest.fixture
def recidive(tmp_path):
    get_db, _cfg, _db_set, _conf = base(tmp_path)
    role = Rang(321)
    conf = {"recidivism_role": role.id, "recidivism_t1": 1, "recidivism_t2": 6, "recidivism_t3": 10}

    async def db_get(_g):
        return conf

    async def jamais(_m):
        return False

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                             " user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, duration TEXT,"
                             " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            for jours in (0, 1):  # deux jours d'infractions automatiques : palier 1
                await db.execute("INSERT INTO infractions(guild_id, user_id, mod_id, type, created_at) VALUES"
                                 " (1, 50, 999, 'insulte', datetime('now', ?))", (f"-{jours} days",))
            await db.commit()
        await R.init_db()
        await registre.init_db()
    R.setup(Obj(user=Obj(id=999)), get_db, db_get, jamais, lambda _u: False, db_set_fn=_db_set)
    registre.setup(get_db=get_db, log=lambda *a: None)
    registre._derniers.clear()
    R._restricted.clear()
    R._locks.clear()
    asyncio.run(preparer())
    g = Obj(id=1, me=Obj(guild_permissions=Obj(manage_roles=True)), get_role=lambda rid: role if rid == 321 else None)
    return Obj(get_db=get_db, g=g, role=role)


def test_R10_une_base_illisible_ne_libere_personne(recidive):
    m = MembreR(50)
    asyncio.run(R.recompute(recidive.g, m))
    assert R.tier_of(1, 50) == 1 and recidive.role in m.roles

    async def casse():
        async with recidive.get_db() as db:
            await db.execute("DROP TABLE infractions")
            await db.commit()
    asyncio.run(casse())
    asyncio.run(R.recompute(recidive.g, m))
    assert R.tier_of(1, 50) == 1 and recidive.role in m.roles, "score illisible : rien ne change"

    async def ligne():
        async with recidive.get_db() as db:
            async with db.execute("SELECT tier FROM member_restrictions WHERE user_id=50") as cur:
                return await cur.fetchone()
    assert asyncio.run(ligne()) == (1,), "la ligne reste"


def test_R10_le_role_retire_mais_la_ligne_restreinte_le_role_est_repose(recidive):
    m = MembreR(50)
    asyncio.run(R.recompute(recidive.g, m))
    m.roles.remove(recidive.role)  # aussitôt après : le membre en mémoire n'a pas encore le rôle
    asyncio.run(R.recompute(recidive.g, m))
    assert recidive.role in m.roles and not asyncio.run(registre.lire(1)), "reposé, sans bruit au journal"

    async def il_y_a_une_heure():
        async with recidive.get_db() as db:
            await db.execute("UPDATE member_restrictions SET applied_at=datetime('now', '-1 hour')")
            await db.commit()
    asyncio.run(il_y_a_une_heure())
    m.roles.remove(recidive.role)  # retiré à la main (ou par /off, /mod direction)
    asyncio.run(R.recompute(recidive.g, m))
    assert recidive.role in m.roles and R.tier_of(1, 50) == 1, "la ligne et le rôle disent la même chose"
    (entree,) = asyncio.run(registre.lire(1))
    assert entree["type"] == "recidive.role_repose" and "effacer son casier" in entree["texte"]


# ═══ 11. Plus de réponse fausse ════════════════════════════════════════════════════════════════

def test_R11_un_bouton_de_categorie_retiree_le_dit():
    etat, role = asyncio.run(pings.basculer(Obj(id=1), Obj(roles=[]), "ugc"))
    assert (etat, role) == (pings.INCONNUE, None)
    assert pings.phrase(etat, "ugc") == "❌ Cette catégorie n'existe plus."
    assert "réessaie" in pings.phrase(pings.ERREUR, "studio"), "une vraie panne garde son message"


class PostArchive(discord.Thread):
    parent = None

    def __init__(self, tid, rouvrable=True):
        self.id, self.archived, self.rouvrable, self.etats, self.supprimes = tid, True, rouvrable, [], []

    async def edit(self, *, archived):
        if not self.rouvrable:
            raise discord.Forbidden(Obj(status=403, reason="x"), "verrouillé")
        self.archived = archived
        self.etats.append(archived)

    def get_partial_message(self, mid):
        post = self

        class Partiel:
            async def delete(self):
                if post.archived:
                    raise discord.HTTPException(Obj(status=400, reason="x"), "Thread is archived")
                post.supprimes.append(mid)
        return Partiel()


@pytest.fixture
def sondage(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    S.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=None, controle=None, log=lambda *a: None)
    registre.setup(get_db=get_db, log=lambda *a: None)
    registre._derniers.clear()

    async def preparer():
        await S.init_db()
        await registre.init_db()
        async with get_db() as db:
            await db.execute("INSERT INTO sondages(message_id, guild_id, channel_id, auteur_id, question, cree_le,"
                             " fin_le) VALUES (8001, 1, 600, 7, 'Quelle île ?', '2026-10-20 10:00:00',"
                             " '2026-10-30 10:00:00')")
            await db.commit()
    asyncio.run(preparer())
    g = Guilde()
    g.get_thread = lambda _i: None  # un post archivé n'est pas en mémoire
    return g


def test_R11_un_sondage_dans_un_post_archive_est_vraiment_retire(sondage):
    post = PostArchive(600, rouvrable=False)

    async def lire(cid):
        return post
    sondage.fetch_channel = lire
    chef = Obj(id=3, display_name="Chef")
    ok, msg = asyncio.run(S.retirer(sondage, 1, chef))
    assert not ok and "post archivé" in msg and asyncio.run(S.lister(1))["liste"][0]["statut"] != "retire", \
        "rien n'a été retiré : le site ne dit pas le contraire"
    post.rouvrable = True
    assert asyncio.run(S.retirer(sondage, 1, chef)) == (True, "Sondage retiré du salon.")
    assert post.supprimes == [8001] and post.etats == [False, True], "réveillé le temps du retrait, puis rendormi"
    assert asyncio.run(S.lister(1))["liste"][0]["statut"] == "retire"


# ═══ 12. Les règles : cartes V2, journal du site ═══════════════════════════════════════════════

def test_R12_les_avis_des_sondages_sont_des_cartes_qui_s_effacent():
    envois = []

    class Salon:
        async def send(self, content=None, **kw):
            envois.append((content, kw))
    membre = Obj(id=7, mention="<@7>")
    asyncio.run(S._dire(Salon(), "<@7> Sondage retiré : mot interdit.", membre))
    ((contenu, kw),) = envois
    assert contenu is None and "Sondage retiré" in _texte_v2(kw["view"]) and kw["delete_after"] == 12
    m = kw["allowed_mentions"]
    assert m.users == [membre] and m.everyone is False and m.roles is False


def test_R12_le_rappel_d_inactivite_du_clan_est_une_carte():
    corps = _source("_action_clan_prevenir")
    assert "salon.send(clan.texte_salon(" not in corps and "await salon.send(view=v, allowed_mentions=" in corps


def test_R12_en_mode_site_le_demontage_va_au_journal():
    envois, journal = [], []

    class SalonLog:
        async def send(self, *a, **k):
            envois.append(a)

    async def demonter(_g, **_k):
        return {"deja": False, "membres": 2, "rendus": 5}

    async def cfg(_g):
        return {"mod_log_channel": 4, "logs_sur_site_v1": "2026-10-20"}

    async def au_journal(_g, categorie, type_, texte, **_k):
        journal.append((categorie, type_, texte))
    ns = {"cfg": cfg, "get_db": None, "db_set": None, "discord": discord, "print": lambda *a, **k: None,
          "_logerr": lambda *a, **k: envois.append(("ERREUR", a)), "_au_journal": au_journal,
          "activite_demontage_module": Obj(demonter=demonter, bilan_texte=lambda _r: "2 membre(s) · 5 rôle(s)",
                                           a_agi=lambda _r: True)}
    exec(_source("_demonter_activite"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["_demonter_activite"](Obj(id=1, name="GoRP", get_channel=lambda _c: SalonLog())))
    assert envois == [] and journal == [("Config", "activite.demontage",
                                         "Système d'activité retiré : plus de rôle AFK ni de salon masqué. "
                                         "2 membre(s) · 5 rôle(s)")]


# ═══ 13. Annonces : acquittées avant la base ═══════════════════════════════════════════════════

def test_R13_vu_et_nouvelle_annonce_acquittent_avant_la_base(env, monkeypatch):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    salon = g.nom("📜annonce")
    run(A.publier(g, tete, A.Brouillon(salon_id=salon.id, titre="T", texte="X", fil=False)))
    i = interaction(g, g.membre(7))
    vraie_base, vraie_cfg = A._get_db, A._cfg

    def base_gardee():
        assert i.response.is_done(), "acquitté avant la base"
        return vraie_base()

    async def cfg_gardee(gid):
        assert i.response.is_done(), "acquitté avant la base"
        return await vraie_cfg(gid)
    monkeypatch.setattr(A, "_get_db", base_gardee)
    monkeypatch.setattr(A, "_cfg", cfg_gardee)
    run(A.BoutonVu(1).callback(i))
    assert i.suivis[-1] == ("✅ C'est noté, merci d'avoir lu.", {"ephemeral": True})
    i = interaction(g, tete)
    run(A.BoutonComposer().callback(i))
    assert isinstance(i.suivis[-1][1]["view"], A.VueComposer) and i.suivis[-1][1]["ephemeral"] is True
