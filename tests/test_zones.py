"""22/10/2026 (nuit), le fondateur : « je veux une catégorie… tu enlèves tout ce qui est dans
Communautaire et dans Rell Seas… un fil communautaire et un fil Rell Seas… dans le fil communautaire,
le chat, médias… c'est les salons dans un fil… dans le fil Rell Seas, trade, crew… il n'y a que deux
fils… le vocal, tu le laisses tel qu'il est… toutes les fonctionnalités qui sont liées à ça
fonctionnent, et ça cible bien les salons. » Puis la capture : quatre catégories vides — « est-ce
qu'ils servent à quelque chose ? ». Et la zone du clan GoRP. Sur un faux serveur qui reprend le
serveur tel qu'il est ce soir."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
import pytest

import boosts
import config_salons
import entraide as E
import equipages as Q
import i18n
import suggestions as S
import visuels
import zones as ZN
from conftest_discord import Obj, base
from faux_serveur import Forum, Monde, Texte, Vocal, compter, ids, interaction, run, textes
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
POSTS_COMMU = [t for _c, t, _v, _x in ZN.POSTS_COMMU]
POSTS_RELL = [t for _c, t, _v, _x in ZN.POSTS_RELL]


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
    ZN._verrous.clear()
    commun = dict(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=rien, controle=rien, journal=noter,
                  log=lambda *a: None)
    E.setup(est_staff=non, **commun)
    Q.setup(est_staff=non, **commun)
    S.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=rien, controle=rien, salon_logs=rien,
            log=lambda *a: None)
    boosts.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None)
    ZN.setup(cfg=cfg, db_set=db_set, lecteurs=lambda g, c: [], log=lambda *a: None)
    for module in (E, Q, S, boosts):
        asyncio.run(module.init_db())
    return Obj(conf=conf, journal=journal, cfg=cfg, db_set=db_set, get_db=get_db)


def _clan_et_vocaux(g, conf):
    """Le reste du serveur de la capture : le clan (son Join réservé), la Taverne, le Join de la
    communauté."""
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


def serveur_de_ce_soir(env):
    """Le serveur tel que le lot 19 l'a laissé : Communautaire (❓aide, 💬chat, 🧵discussions, 💡suggestions,
    🚀boosts, 🔊Join) et la zone · Rell Seas (🌊chat-rellseas, 🛟help, 🤝trade, ⚓crews, 🔊Join) — avec une
    demande ouverte, un équipage et une idée en vote."""
    g = Monde()
    c = env.conf
    c.update(aide_salon=g.nom("❓aide").id, suggestions_salon=g.nom("💡suggestions").id,
             boosts_salon=g.nom("🚀boosts").id, rs_installation_auto="x", zones_v1=1, menage_v1="x")
    join, _hub_clan = _clan_et_vocaux(g, c)
    c["zones_forum"] = g._salon(Forum, "🧵discussions", {"category": g.commu}).id
    rell = g.categorie("· Rell Seas")
    c["zones_rell"] = rell.id
    c["zones_chat"] = g._salon(Texte, "🌊chat-rellseas", {"category": rell}).id
    vocal = g._salon(Vocal, "🔊Join", {"category": rell})
    c["zones_vocal"] = vocal.id
    c["temp_voice_config"]["hubs"][str(vocal.id)] = {"category": rell.id, "default_name": "🌊 {user}"}
    run(E.installer(g, categorie=rell))
    run(Q.installer(g, rell))
    run(E.publier(interaction(g, g.membre(7)), E.ZONES["boss"], {"titre": "Akuma", "pseudo": "K", "niveau": "",
                                                                    "joueurs": "", "details": ""}))
    run(Q.publier(interaction(g, g.membre(8)), "pirate", {"nom": "Les Requins", "pseudo": "K", "membres": "",
                                                           "niveau": "", "presentation": "On navigue."}))

    async def idee():
        async with env.get_db() as db:
            await db.execute("INSERT INTO suggestions_v2(guild_id, channel_id, message_id, auteur_id, titre, cree_le)"
                             " VALUES(1, ?, 5, 9, 'Un mode PvP', '2026-10-22 18:00:00')", (c["suggestions_salon"],))
            await db.execute("INSERT INTO suggestions_votes(suggestion_id, user_id, vote) VALUES(1, 4, 1)")
            await db.commit()
    run(idee())
    return g, join, vocal, rell


def noms(cat):
    return [s.name for s in cat.channels]


# ─── Les deux forums ─────────────────────────────────────────────────────────

def test_Z1_ce_soir_tout_passe_dans_deux_forums_le_vocal_reste(env):
    g, join, vocal_rell, rell = serveur_de_ce_soir(env)
    anciens = {n: g.nom(n) for n in ("❓aide", "💬chat", "💡suggestions", "🚀boosts", "🧵discussions",
                                     "🌊chat-rellseas", "🛟help", "🤝trade", "⚓crews")}
    vieux_chat = anciens["💬chat"].id
    env.conf.update(link_allowed_channels=[vieux_chat], image_allowed_channels=[vieux_chat, 999],
                    welcome_channel=vieux_chat)
    faits = run(ZN.installer(g))
    c = env.conf
    chat_post = c["zones_posts"]["chat"]["id"]
    assert c["link_allowed_channels"] == [vieux_chat, chat_post] and c["image_allowed_channels"] ==         [vieux_chat, 999, chat_post] and c["welcome_channel"] == chat_post, "les réglages suivent le chat dans son post"
    assert c["zones_correspondances"][str(anciens["🛟help"].id)] == c["zones_posts"]["help"]["id"]
    assert noms(g.commu) == ["💬communautaire", "🌊rell-seas", "🔊Join"], "une catégorie : deux forums et le vocal"
    assert join.category_id == g.commu.id and str(join.id) in c["temp_voice_config"]["hubs"], "le vocal reste tel quel"
    commu, rell_forum = g.nom("💬communautaire"), g.nom("🌊rell-seas")
    assert [x.fil.name for x in commu.crees][::-1] == POSTS_COMMU and [x.fil.name for x in rell_forum.crees][::-1] == \
        POSTS_RELL, "créés du dernier au premier : le forum les montre dans l'ordre"
    droits = commu.kw["overwrites"][g.default_role]
    assert (droits.send_messages, droits.send_messages_in_threads) == (False, True), \
        "on écrit dans les posts, on n'en crée pas"
    posts = c["zones_posts"]
    verrous = {cle: g.fils[p["id"]].locked for cle, p in posts.items()}
    assert verrous == {"aide": True, "chat": False, "medias": False, "suggestions": True, "boosts": True,
                       "commandes": False, "rell_chat": False, "help": False, "trade": False, "crews": True}
    assert (c["aide_salon"], c["aide_message"]) == (posts["aide"]["id"], posts["aide"]["id"])
    assert c["suggestions_salon"] == posts["suggestions"]["id"]
    assert c["suggestions_panneau"] == g.fils[posts["suggestions"]["id"]].messages[-1].id,         "sous l'idée déménagée, le bouton « Proposer » redescend"
    assert (c["boosts_salon"], c["boosts_entete"]) == (posts["boosts"]["id"],) * 2
    assert c["rs_salons"] == {"entraide": posts["help"]["id"], "trade": posts["trade"]["id"]} == c["rs_ouvertures"]
    assert (c["eq_forum"], c["eq_ouverture"]) == (posts["crews"]["id"],) * 2, "chaque fonction vise son post"
    archives = g.get_channel(c["zones_categorie_archives"])
    assert archives.name == "📦 Archives" and archives.kw["overwrites"][g.default_role].view_channel is False
    for nom, ch in anciens.items():
        assert ch.id in g.salons and ch.category_id == archives.id, f"{nom} : caché aux archives, pas effacé"
        assert ch.edits[-1]["sync_permissions"] is True, "il prend les droits de la catégorie cachée"
    assert sorted(c["zones_archives"]) == sorted(ch.id for ch in anciens.values())
    assert vocal_rell.supprime and str(vocal_rell.id) not in c["temp_voice_config"]["hubs"], "un seul vocal"
    assert rell.supprime and rell not in g.categories
    d = run(E.charger(1))
    assert d["statut"] == "fermee" and "republie ta demande dans 🌊rell-seas" in g.fils[d["fil_id"]].envois[-1][0]
    e = run(Q.charger(1))
    crews = g.fils[posts["crews"]["id"]]
    assert e["mode"] == "carte" and e["fil_id"] == crews.messages[0].id, "l'équipage devient une carte"
    s, pour, _contre = run(S.charger(1))
    idees = g.fils[posts["suggestions"]["id"]]
    assert s["channel_id"] == idees.id and s["message_id"] == idees.messages[0].id and pour == 1, \
        "l'idée en vote passe dans le post, avec ses votes"
    assert c["zones_v2"] == 1 and "1 équipage(s) passé(s) en cartes" in faits
    n_salons, n_fils = len(g.salons), len(g.fils)
    assert run(ZN.installer(g)) == [] and (len(g.salons), len(g.fils)) == (n_salons, n_fils), "relancer : rien"


def test_Z2_les_fonctions_marchent_dans_leurs_posts(env):
    g, _join, _v, _r = serveur_de_ce_soir(env)
    run(ZN.installer(g))
    posts = env.conf["zones_posts"]
    aide, trade, crews = (g.fils[posts[k]["id"]] for k in ("help", "trade", "crews"))
    E._creations.clear()
    run(E.publier(interaction(g, g.membre(20)), E.ZONES["farm"], {"titre": "Niveaux", "pseudo": "P", "niveau": "",
                                                                     "duree": "", "details": ""}))
    d = run(E.charger(2))
    assert (d["mode"], d["salon_id"]) == ("carte", aide.id) and d["fil_id"] == aide.messages[0].id
    run(E.publier(interaction(g, g.membre(21)), E.ZONES["trade"], {"donne": "A", "cherche": "B", "pseudo": "P",
                                                                      "details": ""}))
    assert run(E.charger(3))["salon_id"] == trade.id
    run(Q.publier(interaction(g, g.membre(22)), "marine", {"nom": "La Flotte", "pseudo": "P", "membres": "",
                                                            "niveau": "", "presentation": "Ordre et honneur."}))
    assert run(Q.charger(2))["mode"] == "carte" and "La Flotte" in textes(crews.messages[-2].kw["view"])
    assert run(S.salon_de(g)).id == posts["suggestions"]["id"] and run(boosts.salon_de(g)).id == posts["boosts"]["id"]


def test_Z3_un_serveur_neuf_la_categorie_est_creee(env):
    g = Monde(communautaire=False)
    faits = run(ZN.installer(g))
    cat = g.get_channel(g.nom("💬communautaire").category_id)
    assert cat.name == "· Communautaire" and faits[0] == "catégorie · Communautaire"
    assert noms(cat) == ["💬communautaire", "🌊rell-seas"] and "zones_categorie_archives" not in env.conf, \
        "rien à archiver"


def test_Z4_sans_communaute_discord_des_salons_et_leurs_fils(env):
    g = Monde(forum=False, communautaire=False)
    run(ZN.installer(g))
    salon = g.nom("💬communautaire")
    assert isinstance(salon, Texte)
    aide = env.conf["zones_posts"]["aide"]
    fil = g.fils[aide["id"]]
    assert fil.parent is salon and aide["ouverture"] == fil.messages[0].id != fil.id, "l'ouverture : son 1er message"
    assert env.conf["rs_panneaux"]["entraide"] == env.conf["zones_posts"]["help"]["ouverture"]


def test_Z5_l_entretien_reveille_reverrouille_jamais_ne_deverrouille(env):
    g = Monde(communautaire=False)
    run(ZN.installer(g))
    posts = env.conf["zones_posts"]
    chat, aide = g.fils[posts["chat"]["id"]], g.fils[posts["aide"]["id"]]
    chat.archived, chat.locked = True, True  # le staff a verrouillé le chat (un raid)
    aide.locked = False
    run(ZN.entretenir(g))
    assert not chat.archived and chat.locked, "réveillé, et toujours verrouillé : c'est le choix du staff"
    assert aide.locked, "le post ❓ Aide se reverrouille"


def test_Z6_le_panneau_aide_mene_aux_posts(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    run(ZN.installer(g))
    c = env.conf
    groupes = ZN.lignes_aide(g, c, run(ZN.conf(g)))
    assert list(groupes) == ["Communautaire · Community", "Rell Seas"]
    posts = c["zones_posts"]
    assert [p.id for p, _t, _b in groupes["Rell Seas"]] == [posts[k]["id"] for k in ("rell_chat", "help", "trade",
                                                                                     "crews")]
    assert groupes["Communautaire · Community"][0][0].jump_url == f"https://discord.com/channels/1/{posts['chat']['id']}"
    join = next(s for s in g.commu.channels if s.name == "🔊Join")
    assert groupes["Communautaire · Community"][0][1].endswith(f"🔊 <#{join.id}>"), "le vocal, pas celui du clan"
    assert all(" · " in t and " · " in b for v in groupes.values() for _p, t, b in v), "tout en français · anglais"


def _vue_aide_ns():
    ns = {"discord": discord, "Button": discord.ui.Button, "LayoutView": LayoutView, "Palette": Palette,
          "visuels": visuels, "zones": ZN, "entraide": E, "equipages": Q, "config_salons": config_salons,
          "rellseas_ui": Obj(panneaux_tickets=lambda _c: True), "i18n_module": i18n}
    for nom in ("AIDE_VERSION", "_salon_par_nom", "_salon_des_tickets", "LangSelectButton", "_vue_aide"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def test_Z7_le_panneau_aide_bilingue_la_langue_d_un_clic_de_la_marge(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
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
    assert t.index("### Communautaire") < t.index("### Rell Seas") < t.index("### Staff")
    assert f"<#{g.rules_channel.id}>" in t and "join the clan" in t and "Équipages · Crews" in t
    assert signature.startswith(f"{ns['AIDE_VERSION']}|")


def test_Z8_les_archives_le_fondateur_choisit_ce_qui_part(env):
    g, _join, _v, _r = serveur_de_ce_soir(env)
    run(ZN.installer(g))
    c = env.conf
    archives = ZN.archives(g, c)
    assert len(archives) == 9
    chat = g.nom("💬chat")
    assert run(ZN.supprimer_archives(g, [x.id for x in archives if x.id != chat.id])) == 8
    assert ZN.archives(g, c) == [chat] and not chat.supprime and g.get_channel(c["zones_categorie_archives"]), \
        "décoché : gardé"
    assert run(ZN.supprimer_archives(g, [chat.id])) == 1
    assert c["zones_categorie_archives"] == 0 and c["zones_archives"] == [], "la catégorie vide part aussi"


def test_Z9_le_bouton_des_archives_est_au_fondateur_seul(env):
    g, _join, _v, _r = serveur_de_ce_soir(env)
    run(ZN.installer(g))
    tableau = []

    async def _salon_tableau(_g):
        tableau.append(1)

    async def _au_journal(*a, **k):
        env.journal.append(("journal", a, k))
    ns = {"discord": discord, "Button": discord.ui.Button, "LayoutView": LayoutView, "Palette": Palette,
          "visuels": visuels, "zones": ZN, "entraide": E, "cfg": env.cfg, "_salon_tableau": _salon_tableau,
          "_au_journal": _au_journal}
    for nom in ("BoutonArchives", "ConfirmerArchives"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    i = interaction(g, g.membre(827633340797681714))
    run(ns["BoutonArchives"]().callback(i))
    assert i.response.messages[0][0] == "Réservé au fondateur.", "la direction voit, le fondateur décide"
    i = interaction(g, g.membre(g.owner_id))
    run(ns["BoutonArchives"]().callback(i))
    vue = i.response.messages[0][1]["view"]
    assert "Irréversible : leur historique (le chat compris) part avec eux." in textes(vue)
    j = interaction(g, g.membre(g.owner_id))
    run(vue._supprimer(j))
    assert ZN.archives(g, env.conf) == [] and tableau and "9 salon(s) supprimé(s)." in textes(j.suivis[-1][1]["view"])


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


def test_Z10_les_categories_vides_et_inutiles_partent_rien_qui_contient_un_salon(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    rell = g.categorie("· Rell Seas")
    g._salon(Texte, "🌊chat-rellseas", {"category": rell})
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


def test_Z11_les_deux_forums_se_reposent_si_l_installation_casse_trois_essais(env):
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
          "_logerr": lambda *a, **k: None, "_entraide_journal": rien, "_salon_aide": rien,
          "_salon_tableau": rien}
    for nom in ("ZONES_ESSAIS", "_installer_zones"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    g = Obj(id=1)
    for n in (1, 2):
        run(ns["_installer_zones"](g, dict(env.conf)))
        assert env.conf["zones_v2"] == "" and env.conf["zones_v2_essais"] == n, "le passage suivant réessaie"
    run(ns["_installer_zones"](g, dict(env.conf)))
    assert env.conf["zones_v2"] == "t" and env.conf["zones_v2_essais"] == 3, "au troisième échec, on arrête"
    assert len(essais) == 3


def test_Z13_branche_dans_le_bot():
    assert "zones.setup(cfg=cfg, db_set=db_set, lecteurs=_lecteurs_archives, log=print)" in SRC
    boucle = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "entraide_task")
    assert "g.owner_id in TETE_IDS and c.get('rs_actif') and (not c.get('zones_v2'))" in boucle
    assert boucle.index("db_set(g.id, 'menage_v1'") < boucle.index("_menage_categories(g)"), "témoin d'abord"
    assert "await zones.entretenir(g)" in boucle
    installer = _source("_installer_zones")
    assert installer.index("db_set(g.id, 'zones_v2'") < installer.index("zones.installer(g)")
    assert "bot.add_dynamic_items(BoutonArchives, TicketHubGererDynamic)" in SRC
    assert "BoutonArchives(len(archives))" in _source("_menu_logs")
    aide = _source("_salon_aide")
    assert "get_channel_or_thread(aide_id)" in aide and "c.get('zones_v2')" in aide, "le panneau vit dans son post"
    assert '"deux_forums": any(' in SRC and '"menage": any(' in SRC, "/stats dit ce qui est en place"
    assert all((RACINE / "visuels" / f"{k}.gif").is_file() for k in ("orientation", "rs_crews"))


def test_Z12_la_zone_du_clan_annonces_et_discussions_reservees_au_clan(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    role = run(g.create_role(name="GoRPC"))
    staff = run(g.create_role(name="Staff"))
    assert run(ZN.installer_clan(g, None)) == [], "sans rôle du clan, rien"
    faits = run(ZN.installer_clan(g, role, [staff]))
    clan = ZN.categorie_clan(g)
    assert noms(clan) == ["📢▷・info-gorp", "📣▷・annonces-gorp", "✍▷・chat-gorpsea", "🧵▷・discussions-gorp", "🔊Join"]
    annonces = g.get_channel(env.conf["clan_annonces"])
    ows = annonces.kw["overwrites"]
    assert ows[g.default_role].view_channel is False and ows[role].view_channel and ows[role].send_messages is False
    assert ows[staff].send_messages, "le staff écrit, le clan lit"
    forum = g.get_channel(env.conf["clan_forum"])
    assert forum.kw["overwrites"][role].send_messages and forum.kw["overwrites"][g.default_role].view_channel is False
    assert [c.fil.name for c in forum.crees] == ["💰 Économie · Economy", "🤝 Trade du clan · Clan trade",
                                                 "🍺 Taverne · Tavern"]
    assert faits == ["salon 📣▷・annonces-gorp", "salon 🧵▷・discussions-gorp", "fil 💰 Économie · Economy",
                     "fil 🤝 Trade du clan · Clan trade", "fil 🍺 Taverne · Tavern"] and env.conf["clan_v1"] == 1
    assert run(ZN.installer_clan(g, role, [staff])) == [], "relancer ne crée rien"
    eco = g.fils[env.conf["clan_fils"]["economie"]]
    eco.archived = True
    run(ZN.entretenir(g))
    assert not eco.archived, "les fils du clan restent ouverts"
    assert {env.conf["clan_annonces"], env.conf["clan_forum"]} <= ZN.ids_salons(env.conf)


def test_Z14_un_salon_immunise_son_post_l_est_aussi(env):
    caches = {1: "ancien"}

    async def remplir():
        async with env.get_db() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS immune_channels(guild_id INTEGER, channel_id INTEGER,"
                             " PRIMARY KEY(guild_id, channel_id))")
            await db.execute("INSERT INTO immune_channels VALUES(1, 50)")
            await db.commit()

    async def lire():
        async with env.get_db() as db:
            async with db.execute("SELECT channel_id FROM immune_channels ORDER BY channel_id") as cur:
                return [r[0] for r in await cur.fetchall()]
    run(remplir())
    ns = {"get_db": env.get_db, "_immunity_cache": caches}
    exec(_source("_reporter_immunites"), ns)  # noqa: S102 — code du dépôt
    c = {"zones_correspondances": {"50": 500, "60": 600}}
    assert run(ns["_reporter_immunites"](Obj(id=1), c)) == 1 and run(lire()) == [50, 500]
    assert caches == {}, "le cache des immunités est vidé : effet immédiat"
    assert run(ns["_reporter_immunites"](Obj(id=1), c)) == 0, "une fois"
