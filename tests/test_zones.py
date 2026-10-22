"""22/10/2026 (nuit) : « le serveur est international, mais aussi français… une zone communautaire… un
espèce de fil… médias pour les photos, commandes pour les bots… boost et suggestions… une zone Rell
Seas, avec un chat dédié au jeu et leur propre système vocal… séparer les deux compartiments au
propre… limiter les salons ». Puis la capture du serveur : quatre catégories vides (🤝 Échanges,
👥 Groupes, 🎟⋮Rell Seas, 🎟⋮Ticket) — « est-ce qu'ils servent à quelque chose ? ». Sur un faux serveur."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
import pytest

import config_salons
import entraide as E
import equipages as Q
import i18n
import visuels
import zones as ZN
from conftest_discord import Obj, base
from faux_serveur import Forum, Monde, Texte, Vocal, compter, ids, lot_18, run, textes
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
COMMU = ["❓aide", "💬chat", "🧵discussions", "💡suggestions", "🚀boosts", "🔊Join"]
RELL = ["🌊chat-rellseas", "🛟help", "🤝trade", "⚓crews", "🔊Join"]


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.ClassDef))
                and (getattr(n, "name", "") == nom
                     or any(getattr(t, "id", "") == nom for t in getattr(n, "targets", []))))


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal = []

    async def rien(*_a, **_k):
        return ""

    async def non(*_a, **_k):
        return False

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))
    E._verrous.clear()
    E._creations.clear()
    E._verifies.clear()
    Q._verrous.clear()
    commun = dict(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=rien, controle=rien, est_staff=non,
                  journal=noter, log=lambda *a: None)
    E.setup(**commun)
    Q.setup(**commun)
    ZN.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    asyncio.run(E.init_db())
    asyncio.run(Q.init_db())
    return Obj(conf=conf, journal=journal, cfg=cfg, db_set=db_set)


def _clan_et_vocaux(g, conf):
    """Le reste du serveur de la capture : le clan (son Join réservé), la Taverne, et le Join de la
    communauté déclaré comme tel."""
    clan = g.categorie("🦜 · GoRp_SEA")
    g._salon(Texte, "📢▷・info-gorp", {"category": clan})
    g._salon(Texte, "✍▷・chat-gorpsea", {"category": clan})
    hub_clan = g._salon(Vocal, "🔊Join", {"category": clan})
    taverne = g.categorie("· Taverne")
    g._salon(Vocal, "🌴taverne🌴", {"category": taverne})
    join = next(s for s in g.commu.channels if s.name == "🔊Join")
    conf["temp_voice_config"] = {"enabled": True, "hubs": {
        str(join.id): {"category": g.commu.id, "required_role": 0, "default_name": "🔊 Vocal de {user}"},
        str(hub_clan.id): {"category": clan.id, "required_role": 77, "default_name": "🦜 {user}"}}}
    return join, hub_clan


def serveur(env):
    g = Monde()
    env.conf.update(aide_salon=g.nom("❓aide").id, suggestions_salon=g.nom("💡suggestions").id,
                    boosts_salon=g.nom("🚀boosts").id)
    _clan_et_vocaux(g, env.conf)
    return g


def noms(cat):
    return [s.name for s in cat.channels]


# ─── Installation ────────────────────────────────────────────────────────────

def test_Z1_deux_compartiments_au_propre(env):
    g = serveur(env)
    faits = run(ZN.installer(g))
    rell = g.get_channel(env.conf["zones_rell"])
    assert rell.name == "· Rell Seas", "au style du serveur : « · Nom »"
    assert g.categories.index(rell) == g.categories.index(g.commu) + 1, "juste après Communautaire"
    assert noms(g.commu) == COMMU and noms(rell) == RELL, "rangés par priorité, les vocaux en bas"
    chat = g.get_channel(env.conf["zones_chat"])
    droits = chat.kw["overwrites"][g.default_role]
    assert droits.send_messages and droits.attach_files and droits.embed_links, "on parle, on montre, comme au 💬chat"
    assert chat.kw["slowmode_delay"] == 2 and "🇫🇷" in chat.kw["topic"] and "🇬🇧" in chat.kw["topic"]
    vocal = g.get_channel(env.conf["zones_vocal"])
    assert isinstance(vocal, Vocal) and vocal.kw["overwrites"][g.default_role].connect
    voix = env.conf["temp_voice_config"]
    assert voix["hubs"][str(vocal.id)] == {"category": rell.id, "default_name": "🌊 {user}"} and voix["enabled"]
    assert len(voix["hubs"]) == 3 and voix["hubs"][str(g.nom("🔊Join").id)]["category"] == g.commu.id, \
        "les autres Join restent tels quels ; chacun entre où il veut"
    forum = g.get_channel(env.conf["zones_forum"])
    assert isinstance(forum, Forum) and forum.category_id == g.commu.id
    assert forum.kw["overwrites"][g.default_role].send_messages, "chacun peut ouvrir un sujet"
    assert [c.fil.name for c in forum.crees] == ["📸 Médias · Media", "🤖 Commandes · Commands"]
    assert all("🇫🇷" in c.content and "🇬🇧" in c.content for c in forum.crees), "des fils déjà prêts, expliqués"
    assert env.conf["zones_v1"] == 1
    assert faits == ["catégorie · Rell Seas", "salon 🌊chat-rellseas", "vocal 🔊Join", "rôle 🛟 Guide Aide",
                     "rôle ⚔️ Guide Boss", "rôle 🌾 Guide Farm", "rôle 🛡️ Middleman", "salon 🛟help", "salon 🤝trade",
                     "salon ⚓crews", "salon 🧵discussions", "fil 📸 Médias · Media", "fil 🤖 Commandes · Commands"]
    n_salons, n_mouv, n_fils = len(g.salons), len(g.mouvements), len(g.fils)
    assert run(ZN.installer(g)) == [], "relancer ne crée rien"
    assert (len(g.salons), len(g.mouvements), len(g.fils)) == (n_salons, n_mouv, n_fils), "… et ne déplace rien"


def test_Z2_depuis_le_lot_18_les_forums_rejoignent_rell_seas_sans_rien_perdre(env):
    g, entr, trade, p1, _p2 = lot_18(env.conf)
    _clan_et_vocaux(g, env.conf)
    avant = set(g.salons)
    demande = g.nouveau_fil(entr, "Akuma · Pirate7")
    demande.applied_tags = ["Boss", "Ouverte"]
    faits = run(ZN.installer(g))
    rell = g.get_channel(env.conf["zones_rell"])
    assert avant <= set(g.salons) and demande.id in g.fils, "rien n'est supprimé : les demandes en cours restent"
    assert (entr.name, trade.name, entr.category_id, trade.category_id) == ("🛟help", "🤝trade", rell.id, rell.id)
    assert noms(g.commu) == COMMU and noms(rell) == RELL
    assert "🛟help mis à niveau" in faits and "salon 🛟help" not in faits, "les forums existants sont gardés"
    assert [(t.name, str(t.emoji)) for t in entr.available_tags][0] == ("Aide · Help", "🛟"), "plus de badge 🆘"
    assert p1.name == "📌 Publier une demande · Ask for help"


def test_Z3_sans_categorie_communautaire_le_forum_va_avec_le_salon_aide(env):
    g = Monde(communautaire=False)
    accueil = g.categorie("· Accueil")
    aide = g._salon(Texte, "❓aide", {"category": accueil})
    env.conf.update(aide_salon=aide.id)
    run(ZN.installer(g))
    assert g.get_channel(env.conf["zones_forum"]).category_id == accueil.id
    assert noms(g.get_channel(env.conf["zones_rell"])) == RELL


def test_Z4_sans_communaute_discord_des_salons_et_des_fils(env):
    g = Monde(forum=False)
    env.conf.update(aide_salon=g.nom("❓aide").id)
    run(ZN.installer(g))
    discussions = g.get_channel(env.conf["zones_forum"])
    assert isinstance(discussions, Texte) and [e[1].split("\n")[0] for e in discussions.envois] == [
        "**📸 Médias · Media**", "**🤖 Commandes · Commands**"]
    assert set(env.conf["zones_fils"]) == {"medias", "commandes"}


def test_Z5_les_fils_prets_restent_ouverts_et_reviennent_s_ils_sont_effaces(env):
    g = serveur(env)
    run(ZN.installer(g))
    medias = g.fils[env.conf["zones_fils"]["medias"]]
    medias.archived = True
    run(ZN.entretenir(g))
    assert not medias.archived, "Discord archive un fil calme : on le réveille"
    run(medias.delete())
    assert run(ZN.installer(g)) == ["fil 📸 Médias · Media"] and env.conf["zones_fils"]["medias"] != medias.id


def test_Z6_le_panneau_aide_par_compartiment_une_ligne_par_salon_qui_existe(env):
    g = serveur(env)
    run(ZN.installer(g))
    c = env.conf
    cfz, cfe, cfq = run(ZN.conf(g)), run(E.conf(g)), run(Q.conf(g))
    groupes = ZN.lignes_aide(g, c, cfz, cfe, cfq)
    assert list(groupes) == ["Communautaire · Community", "Rell Seas"]
    assert {k: [s.name for s, _t, _b in v] for k, v in groupes.items()} == {
        "Communautaire · Community": ["💬chat", "🧵discussions", "💡suggestions"],
        "Rell Seas": ["🌊chat-rellseas", "🛟help", "🤝trade", "⚓crews"]}
    join = next(s for s in g.commu.channels if s.name == "🔊Join")
    assert groupes["Communautaire · Community"][0][1].endswith(f"🔊 <#{join.id}>"), "le Join de la communauté"
    assert groupes["Rell Seas"][0][1].endswith(f"🔊 <#{c['zones_vocal']}>"), "… et celui de Rell Seas, pas du clan"
    assert all(" · " in t and " · " in b for v in groupes.values() for _s, t, b in v), "tout en français · anglais"
    del g.salons[c["eq_forum"]]
    assert ZN.lignes_aide(g, c, cfz, cfe, cfq)["Rell Seas"][3][0] is None, "un salon effacé : sa ligne disparaît"
    assert {c["zones_rell"], c["zones_chat"], c["zones_vocal"], c["zones_forum"], c["eq_forum"],
            *c["rs_salons"].values()} <= ZN.ids_salons(c), "aucun réglage de masse ne touche à leurs droits"


# ─── Le panneau ❓ aide (bot.py) ───────────────────────────────────────────────

def _vue_aide_ns():
    ns = {"discord": discord, "Button": discord.ui.Button, "LayoutView": LayoutView, "Palette": Palette,
          "visuels": visuels, "zones": ZN, "entraide": E, "equipages": Q, "config_salons": config_salons,
          "rellseas_ui": Obj(panneaux_tickets=lambda _c: True), "i18n_module": i18n}
    for nom in ("AIDE_VERSION", "_salon_par_nom", "_salon_des_tickets", "LangSelectButton", "_vue_aide"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def test_Z7_le_panneau_aide_bilingue_la_langue_d_un_clic_moins_de_40_composants(env):
    g = serveur(env)
    run(ZN.installer(g))
    tickets = g.categorie("🎫 TICKETS")
    g._salon(Texte, "🏷ticket", {"category": tickets})
    g.rules_channel = g._salon(Texte, "☑info", {"category": g.categorie("· log")})
    ns = _vue_aide_ns()
    vue, signature = run(ns["_vue_aide"](g, env.conf))
    t = textes(vue)
    assert compter(vue) <= 37, f"{compter(vue)} composants : Discord en refuse plus de 40, on garde de la marge"
    assert "Serveur international" in t and "International server" in t
    assert ids(vue)[:2] == ["i18n_setlang:fr", "i18n_setlang:en"], "le choix de la langue, en tête"
    for titre in ("### Communautaire · Community", "### Rell Seas", "### Staff"):
        assert titre in t
    assert t.index("### Communautaire") < t.index("### Rell Seas") < t.index("### Staff")
    assert f"<#{g.rules_channel.id}>" in t, "le salon de règles officiel du serveur (ici « info »)"
    assert "rejoindre le clan · a question, a problem, join the clan" in t and "Équipages · Crews" in t
    assert signature.startswith(f"{ns['AIDE_VERSION']}|") and ns["AIDE_VERSION"] >= 3
    del g.salons[env.conf["eq_forum"]]
    vue2, signature2 = run(ns["_vue_aide"](g, env.conf))
    assert signature2 != signature and "Équipages · Crews" not in textes(vue2), "aucun bouton qui ment"


# ─── Ménage des catégories vides (bot.py) ────────────────────────────────────

def _menage_ns(env, g, tickets):
    erreurs, journal = [], []

    async def _categorie_tickets(_g):
        return tickets

    async def _au_journal(_g, categorie, type_, texte, **kw):
        journal.append((categorie, type_, texte))

    def _logerr(cle, ex, **kw):
        erreurs.append((cle, ex))
    ns = {"discord": discord, "config_salons": config_salons, "cfg": env.cfg, "db_set": env.db_set,
          "_categorie_tickets": _categorie_tickets, "_au_journal": _au_journal, "_logerr": _logerr}
    for nom in ("MENAGE_MOTS", "EMOJI_ANCIEN_TICKET", "_menage_categories"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns, journal, erreurs


def test_Z8_les_categories_vides_et_inutiles_partent_rien_qui_contient_un_salon(env):
    g = serveur(env)
    run(ZN.installer(g))
    rell = g.get_channel(env.conf["zones_rell"])
    echanges, groupes = g.categorie("🤝 Échanges"), g.categorie("👥 Groupes")
    rs_tickets, tickets_vieux = g.categorie("🎟⋮Rell Seas"), g.categorie("🎟⋮Ticket")
    plein = g.categorie("🎟⋮Archives")
    g._salon(Texte, "vieux-ticket", {"category": plein})
    divers = g.categorie("📦 Divers")
    tickets = g.categorie("🎫 TICKETS")
    g._salon(Texte, "🏷ticket", {"category": tickets})
    env.conf["ticket_panels"] = {"1": {"name": "Rell Seas", "category": rs_tickets.id, "questions": []},
                                 "2": {"name": "Serveur", "category": tickets_vieux.id, "max": 1},
                                 "3": {"name": "Neuf", "category": tickets.id}}
    ns, journal, erreurs = _menage_ns(env, g, tickets)
    retirees = run(ns["_menage_categories"](g))
    assert retirees == ["🤝 Échanges", "👥 Groupes", "🎟⋮Rell Seas", "🎟⋮Ticket"] and not erreurs
    for cat in (echanges, groupes, rs_tickets, tickets_vieux):
        assert cat.supprime
    for cat in (plein, divers, tickets, rell, g.commu):
        assert not cat.supprime, cat.name
    assert {p["category"] for p in env.conf["ticket_panels"].values()} == {tickets.id}, \
        "les panneaux de tickets ouvrent dans 🎫 TICKETS"
    assert env.conf["ticket_panels"]["2"]["max"] == 1, "le reste du panneau ne bouge pas"
    assert journal == [("Config", "serveur.menage", "Panneaux de tickets rebranchés sur « 🎫 TICKETS ». "
                                                   "Catégories vides retirées : 🤝 Échanges, 👥 Groupes, 🎟⋮Rell Seas, "
                                                   "🎟⋮Ticket.")]
    assert run(ns["_menage_categories"](g)) == [] and len(journal) == 1, "une fois suffit"


def test_Z9_les_zones_se_reposent_si_l_installation_casse_trois_essais(env):
    essais, ecrits = [], {}

    async def casse(_g):
        essais.append(1)
        raise discord.HTTPException(Obj(status=500, reason="x"), "panne")

    async def db_set(_gid, k, v):
        ecrits[k] = v
        env.conf[k] = v

    async def rien(*_a, **_k):
        return None
    ns = {"discord": discord, "zones": Obj(installer=casse), "db_set": db_set, "now": lambda: Obj(isoformat=lambda: "t"),
          "_logerr": lambda *a, **k: None, "_entraide_journal": rien, "_salon_aide": rien}
    for nom in ("ZONES_ESSAIS", "_installer_zones"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1)
    for n in (1, 2):
        run(ns["_installer_zones"](g, dict(env.conf)))
        assert env.conf["zones_v1"] == "" and env.conf["zones_essais"] == n, "le passage suivant réessaie"
    run(ns["_installer_zones"](g, dict(env.conf)))
    assert env.conf["zones_v1"] == "t" and env.conf["zones_essais"] == 3, "au troisième échec, on arrête"
    assert len(essais) == 3


def test_Z10_branche_dans_le_bot():
    assert "zones.setup(cfg=cfg, db_set=db_set, log=print)" in SRC
    boucle = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "entraide_task")
    assert "g.owner_id in TETE_IDS and c.get('rs_actif') and (not c.get('zones_v1'))" in boucle
    assert "g.owner_id in TETE_IDS and c.get('zones_v1') and (not c.get('menage_v1'))" in boucle
    assert boucle.index("db_set(g.id, 'menage_v1'") < boucle.index("_menage_categories(g)"), "témoin d'abord"
    assert "await zones.entretenir(g)" in boucle
    installer = _source("_installer_zones")
    assert installer.index("db_set(g.id, 'zones_v1'") < installer.index("zones.installer(g)")
    assert '"zones": any(' in SRC and '"menage": any(' in SRC, "/stats dit ce qui est en place"
    assert all((RACINE / "visuels" / f"{k}.gif").is_file() for k in ("orientation", "rs_crews"))
