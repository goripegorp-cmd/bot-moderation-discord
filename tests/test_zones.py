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
import io
from pathlib import Path

import discord
import pytest

import annonces as A
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
POSTS_RELL = [t for _c, t, _v, _x in ZN.POSTS_RELL]
POSTS_CLOVER = [t for _c, t, _v, _x in ZN.POSTS_CLOVER]
SALONS_COMMU = ["❓aide", "💬discussion", "📸médias", "💡suggestions", "🚀boosts", "🤖commandes"]


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


def serveur_v2(env):
    """Le serveur tel que les lots 21 à 27 l'ont laissé : 💬communautaire et 🌊rell-seas (deux forums) puis
    🔊Join dans Communautaire ; une idée en vote dans 💡 Suggestions ; des réglages qui visent les posts ;
    les rôles des guides de Rell Seas."""
    g = Monde()
    c = env.conf
    _clan_et_vocaux(g, c)
    for nom in ("💬chat", "💡suggestions", "🚀boosts", "❓aide"):  # partis avec les archives, le 22/10
        run(g.nom(nom).delete())
    commu = g._salon(Forum, "💬communautaire", {"category": g.commu})
    rell = g._salon(Forum, "🌊rell-seas", {"category": g.commu})
    posts = {}
    for forum, defs in ((commu, (("aide", "❓ Aide · Help"), ("chat", "💬 Chat"), ("medias", "📸 Médias · Media"),
                                 ("suggestions", "💡 Suggestions"), ("boosts", "🚀 Boosts"),
                                 ("commandes", "🤖 Commandes · Commands"))),
                        (rell, (("guide", "🧭 Guide · Rell Seas"), ("rell_chat", "🌊 Chat Rell Seas"),
                                ("help", "🛟 Help · Entraide"), ("trade", "🤝 Trade · Échanges")))):
        for cle, titre in defs:
            fil = run(forum.create_thread(name=titre)).thread
            posts[cle] = {"id": fil.id, "ouverture": fil.id}
    roles = {cle: run(g.create_role(name=nom)).id for cle, nom in (("aide", "🛟 Guide Aide"), ("boss", "⚔️ Guide Boss"),
                                                                   ("farm", "🌾 Guide Farm"), ("trade", "🛡️ Middleman"))}
    c.update(zones_v2=1, zones_demenage=1, rs_actif=1, rs_v2=1, zones_forum_commu=commu.id, zones_forum_rell=rell.id,
             zones_posts=posts, aide_salon=posts["aide"]["id"], aide_message=posts["aide"]["id"],
             suggestions_salon=posts["suggestions"]["id"], suggestions_panneau=posts["suggestions"]["id"],
             boosts_salon=posts["boosts"]["id"], boosts_entete=posts["boosts"]["id"], rs_roles=roles,
             rs_salons={"entraide": posts["help"]["id"], "trade": posts["trade"]["id"]},
             rs_ouvertures={"entraide": posts["help"]["id"], "trade": posts["trade"]["id"]},
             rs_panneaux={"entraide": 4242, "trade": posts["trade"]["id"]},
             link_allowed_channels=[posts["chat"]["id"]], image_allowed_channels=[posts["medias"]["id"]],
             welcome_channel=posts["chat"]["id"])

    async def idee():
        async with env.get_db() as db:
            await db.execute("INSERT INTO suggestions_v2(guild_id, channel_id, message_id, auteur_id, titre, cree_le)"
                             " VALUES(1, ?, 5, 9, 'Un mode PvP', '2026-10-23 18:00:00')", (posts["suggestions"]["id"],))
            await db.execute("INSERT INTO suggestions_votes(suggestion_id, user_id, vote) VALUES(1, 4, 1)")
            await db.commit()
    run(idee())
    return g, commu, rell


def noms(cat):
    return [s.name for s in cat.channels]


# ─── Communautaire en salons simples, un forum par jeu ──────────────────────

def test_Z1_communautaire_en_salons_simples_l_ancien_forum_part(env):
    """24/10 : « refais tout l'onglet communautaire… avec des salons simples… un salon discussion, média…
    Boost, Suggestion… en dehors » — et l'ancien forum supprimé (« Le supprimer », choix du fondateur)."""
    g, commu, _rell = serveur_v2(env)
    c = env.conf
    anciens = dict(c["zones_posts"])
    faits = run(ZN.installer(g))
    salons = c["zones_salons"]
    assert noms(g.commu) == SALONS_COMMU + ["🌊rell-seas", "🍀clover-rpg", "🔊Join"], \
        "des salons simples, les forums des jeux, puis le vocal"
    assert commu.supprime and c["zones_forum_commu"] == 0 and "💬communautaire supprimé" in faits
    assert set(c["zones_posts"]) == {"guide", "rell_chat", "help", "trade", "cl_guide", "cl_chat", "cl_help", "cl_trade"}
    assert (c["aide_salon"], c["aide_message"]) == (salons["aide"], 0), "le panneau ❓ aide se repose dans son salon"
    assert c["suggestions_salon"] == salons["suggestions"] and c["boosts_salon"] == salons["boosts"]
    assert c["link_allowed_channels"] == [anciens["chat"]["id"], salons["discussion"]], "les réglages suivent"
    assert c["image_allowed_channels"] == [anciens["medias"]["id"], salons["medias"]]
    assert c["welcome_channel"] == salons["discussion"]
    assert c["zones_correspondances"][str(anciens["commandes"]["id"])] == salons["commandes"], "l'immunité suivra"
    s, pour, _contre = run(S.charger(1))
    assert s["channel_id"] == salons["suggestions"] and pour == 1, "l'idée en vote passe dans 💡suggestions, avec son vote"

    def parole(nom):
        return g.nom(nom).kw["overwrites"][g.default_role].send_messages
    assert parole("💬discussion") and parole("📸médias") and parole("🤖commandes")
    assert not parole("❓aide") and not parole("💡suggestions") and not parole("🚀boosts"), "on y lit, on clique"
    clover = g.nom("🍀clover-rpg")
    assert [x.fil.name for x in clover.crees][::-1] == POSTS_CLOVER, "créés du dernier au premier : dans l'ordre"
    posts = c["zones_posts"]
    assert {k: g.fils[posts[k]["id"]].locked for k in ("cl_guide", "cl_chat", "cl_help", "cl_trade")} == \
        {"cl_guide": True, "cl_chat": False, "cl_help": False, "cl_trade": False}
    assert c["rs_salons"] == {"entraide": posts["help"]["id"], "trade": posts["trade"]["id"],
                              "cl_entraide": posts["cl_help"]["id"], "cl_trade": posts["cl_trade"]["id"]}
    assert c["rs_panneaux"]["entraide"] == 4242, "le panneau de Rell Seas, sous sa dernière carte, ne bouge pas"
    roles = c["rs_roles"]
    assert g.get_role(roles["cl_trade"]).name == "🛡️ Middleman · Clover" and {"cl_aide", "cl_boss", "cl_farm"} <= set(roles)
    n = (len(g.salons), len(g.fils), len(g.roles))
    assert run(ZN.installer(g)) == [] and (len(g.salons), len(g.fils), len(g.roles)) == n, "relancer : rien"


def test_Z2_chaque_fonction_marche_a_sa_place(env):
    g, _c, _r = serveur_v2(env)
    run(ZN.installer(g))
    c = env.conf
    posts = c["zones_posts"]
    E._creations.clear()
    run(E.publier(interaction(g, g.membre(20)), E.ZONES["cl_farm"], {"titre": "Niveaux", "pseudo": "P", "niveau": "",
                                                                        "duree": "", "details": ""}))
    aide = g.fils[posts["cl_help"]["id"]]
    d = run(E.charger(1))
    assert (d["mode"], d["salon_id"]) == ("carte", aide.id) and d["fil_id"] == aide.messages[0].id, \
        "une demande Clover RPG : une carte dans 🛟 Help de Clover"
    run(E.publier(interaction(g, g.membre(21)), E.ZONES["cl_trade"], {"donne": "Épée", "cherche": "Bouclier",
                                                                         "pseudo": "P", "details": ""}))
    assert run(E.charger(2))["salon_id"] == posts["cl_trade"]["id"]
    assert run(E.reputation(1, 21, "cl_trade")) == 0 and run(E.reputation(1, 21, "trade")) == 0
    assert run(S.salon_de(g)).id == c["zones_salons"]["suggestions"]
    assert run(boosts.salon_de(g)).id == c["zones_salons"]["boosts"]


def test_Z3_un_serveur_neuf_tout_est_cree(env):
    g = Monde(communautaire=False)
    faits = run(ZN.installer(g))
    cat = g.get_channel(g.nom("💬discussion").category_id)
    assert cat.name == "· Communautaire" and faits[0] == "catégorie · Communautaire"
    assert noms(cat) == SALONS_COMMU + ["🌊rell-seas", "🍀clover-rpg"] and "zones_categorie_archives" not in env.conf, \
        "jamais d'archives"


def test_Z4_sans_communaute_discord_des_salons_et_leurs_fils(env):
    g = Monde(forum=False, communautaire=False)
    run(ZN.installer(g))
    salon = g.nom("🍀clover-rpg")
    assert isinstance(salon, Texte)
    aide = env.conf["zones_posts"]["cl_help"]
    fil = g.fils[aide["id"]]
    assert fil.parent is salon and aide["ouverture"] == fil.messages[0].id != fil.id, "l'ouverture : son 1er message"
    assert env.conf["rs_panneaux"]["cl_entraide"] == aide["ouverture"]


def test_Z5_l_entretien_reveille_reverrouille_jamais_ne_deverrouille(env):
    g = Monde(communautaire=False)
    run(ZN.installer(g))
    posts = env.conf["zones_posts"]
    chat, guide = g.fils[posts["cl_chat"]["id"]], g.fils[posts["cl_guide"]["id"]]
    chat.archived, chat.locked = True, True  # le staff a verrouillé le chat (un raid)
    guide.locked = False
    run(ZN.entretenir(g))
    assert not chat.archived and chat.locked, "réveillé, et toujours verrouillé : c'est le choix du staff"
    assert guide.locked, "le guide se reverrouille"


def test_Z6_le_panneau_aide_un_groupe_par_compartiment(env):
    g = Monde()
    join, _hub = _clan_et_vocaux(g, env.conf)
    run(ZN.installer(g))
    c = env.conf
    c["cadeaux_salon"] = g._salon(Texte, "🎁giveaways", {}).id
    groupes = ZN.groupes_aide(g, c, run(ZN.conf(g)))
    assert [titre for titre, _p, _b in groupes] == ["Communautaire · Community", "🌊 Rell Seas", "🍀 Clover RPG"]
    _t, phrase, boutons = groupes[0]
    assert [b for _x, b in boutons] == ["💬 Discussion", "📸 Médias", "💡 Suggestions", "🤖 Commandes", "🎁 Cadeaux"]
    assert f"🔊 <#{join.id}>" in phrase, "le vocal de la communauté, pas celui du clan"
    posts = c["zones_posts"]
    assert [x.id for x, _b in groupes[2][2]] == [posts[k]["id"] for k in ("cl_guide", "cl_chat", "cl_help", "cl_trade")]
    assert "💬chat" in noms(g.commu), "un ancien salon qu'on ne sait pas reprendre reste là : rien n'est supprimé"


def _vue_aide_ns():
    ns = {"discord": discord, "Button": discord.ui.Button, "LayoutView": LayoutView, "Palette": Palette,
          "visuels": visuels, "zones": ZN, "entraide": E, "equipages": Q, "config_salons": config_salons,
          "rellseas_ui": Obj(panneaux_tickets=lambda _c: True), "i18n_module": i18n}
    for nom in ("AIDE_VERSION", "_salon_par_nom", "_salon_des_tickets", "LangSelectButton", "_vue_aide"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns


def test_Z7_le_panneau_aide_bilingue_des_rangees_de_boutons(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    run(ZN.installer(g))
    tickets = g.categorie("🎫 TICKETS")
    g._salon(Texte, "🏷ticket", {"category": tickets})
    g.rules_channel = g._salon(Texte, "☑info", {"category": g.categorie("· log")})
    ns = _vue_aide_ns()
    vue, signature = run(ns["_vue_aide"](g, env.conf))
    t = textes(vue)
    assert compter(vue) <= 40, f"{compter(vue)} composants : Discord en refuse plus de 40"
    assert "Serveur international" in t and "International server" in t
    assert ids(vue)[:2] == ["i18n_setlang:fr", "i18n_setlang:en"], "le choix de la langue, en tête"
    assert t.index("### Communautaire") < t.index("### 🌊 Rell Seas") < t.index("### 🍀 Clover RPG") < t.index("### Staff")
    assert f"<#{g.rules_channel.id}>" in t and "join the clan" in t and "Crews" not in t
    liens = [b.url for b in vue.walk_children() if isinstance(b, discord.ui.Button) and b.url]
    assert len(liens) == 4 + 4 + 4 + 1, "Communautaire, Rell Seas, Clover RPG, le ticket"
    assert signature.startswith(f"{ns['AIDE_VERSION']}|")


def _archives_d_avant(env):
    """Les archives du 22/10 (supprimées depuis, à la demande du fondateur) : la fonction reste — on la
    garde vérifiée sur neuf anciens salons rangés à la main."""
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    cat = g.categorie("📦 Archives")
    ranges = []
    for nom in ("❓aide", "💬chat", "💡suggestions", "🚀boosts", "🧵discussions", "🌊chat-rellseas", "🛟help", "🤝trade",
                "⚓crews"):
        ch = g.nom(nom) if nom in ("❓aide", "💬chat", "💡suggestions", "🚀boosts") else g._salon(Texte, nom, {})
        ch.category_id = cat.id
        ranges.append(ch.id)
    env.conf.update(zones_archives=ranges, zones_categorie_archives=cat.id)
    return g


def test_Z8_les_archives_le_fondateur_choisit_ce_qui_part(env):
    g = _archives_d_avant(env)
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
    g = _archives_d_avant(env)
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


def test_Z11_l_installation_reprend_si_elle_casse_trois_essais(env):
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
        assert env.conf["zones_v3"] == "" and env.conf["zones_v3_essais"] == n, "le passage suivant réessaie"
    run(ns["_installer_zones"](g, dict(env.conf)))
    assert env.conf["zones_v3"] == "t" and env.conf["zones_v3_essais"] == 3, "au troisième échec, on arrête"
    assert len(essais) == 3


def test_Z13_branche_dans_le_bot():
    assert "zones.setup(cfg=cfg, db_set=db_set, lecteurs=_lecteurs_archives, ticket=_salon_des_tickets," in SRC
    boucle = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "entraide_task")
    assert "g.owner_id in TETE_IDS and c.get('rs_actif') and (not c.get('zones_v3'))" in boucle
    assert boucle.index("db_set(g.id, 'menage_v1'") < boucle.index("_menage_categories(g)"), "témoin d'abord"
    assert "await zones.entretenir(g)" in boucle
    installer = _source("_installer_zones")
    assert installer.index("db_set(g.id, 'zones_v3'") < installer.index("zones.installer(g)")
    assert "bot.add_dynamic_items(BoutonArchives, TicketHubGererDynamic)" in SRC
    assert "BoutonArchives(len(archives))" in _source("_menu_logs")
    aide = _source("_salon_aide")
    assert "get_channel_or_thread(aide_id)" in aide and "c.get('zones_v2')" in aide, "le panneau vit dans son post"
    assert '"deux_forums": any(' in SRC and '"menage": any(' in SRC, "/stats dit ce qui est en place"
    for etat in ('"commu_salons": max(', '"forum_commu": any(', '"forum_clover": any('):
        assert etat in SRC, etat
    assert all((RACINE / "visuels" / f"{k}.gif").is_file() for k in ("orientation", "cl_guide", "cl_entraide", "cl_trade"))


def _v1_du_clan(g, conf):
    """La zone du clan telle que le lot 20 l'avait laissée : 📣 annonces et 🧵 discussions en plus."""
    clan = ZN.categorie_clan(g)
    v1_annonces = g._salon(Texte, "📣▷・annonces-gorp", {"category": clan})
    v1_forum = g._salon(Forum, "🧵▷・discussions-gorp", {"category": clan})
    conf.update(clan_annonces=v1_annonces.id, clan_forum=v1_forum.id, clan_v1=1)
    return clan, v1_annonces, v1_forum


def test_Z12_la_zone_du_clan_un_seul_forum(env):
    """« Un seul forum (Recommandé) » : 🦜▷・clan-gorp, guide, infos, annonces, chat, économie, trade du
    clan, taverne ; le 🔊 Join reste."""
    g = Monde()
    _join, hub_clan = _clan_et_vocaux(g, env.conf)
    role = run(g.create_role(name="GoRPC"))
    staff = run(g.create_role(name="Staff"))
    assert run(ZN.installer_clan(g, None)) == [], "sans rôle du clan, rien"
    clan, v1_annonces, v1_forum = _v1_du_clan(g, env.conf)
    faits = run(ZN.installer_clan(g, role, [staff]))
    c = env.conf
    forum = g.get_channel(c["clan_forum_v2"])
    assert forum.name == "🦜▷・clan-gorp" and forum.category_id == clan.id and faits[0] == "salon 🦜▷・clan-gorp"
    assert [x.fil.name for x in forum.crees][::-1] == [t for _c, t, _v, _x in ZN.CLAN_POSTS], \
        "créés du dernier au premier : le forum les montre dans l'ordre"
    ows = forum.kw["overwrites"]
    assert ows[g.default_role].view_channel is False
    assert (ows[role].send_messages, ows[role].send_messages_in_threads) == (False, True), \
        "le clan écrit dans les posts, il n'en crée pas"
    assert ows[staff].manage_threads, "le staff écrit aussi dans les posts verrouillés"
    posts = c["clan_posts"]
    assert {k: g.fils[p["id"]].locked for k, p in posts.items()} == {
        "guide": True, "infos": True, "annonces": True, "chat": False, "economie": False, "trade": False,
        "taverne": False}
    assert c["clan_annonces"] == posts["annonces"]["id"], "les annonces du clan visent leur post"
    assert c["clan_anciens"] == {"annonces": v1_annonces.id, "forum": v1_forum.id} and c["clan_v2"] == 1
    assert not hub_clan.supprime and hub_clan.category_id == clan.id, "le Join ne bouge pas"
    n = (len(g.salons), len(g.fils))
    assert run(ZN.installer_clan(g, role, [staff])) == [] and (len(g.salons), len(g.fils)) == n, "relancer : rien"
    assert c["clan_anciens"]["annonces"] == v1_annonces.id, "l'ancien salon des annonces reste noté"
    assert c["clan_forum_v2"] in ZN.ids_salons(c)
    eco, ann = g.fils[posts["economie"]["id"]], g.fils[posts["annonces"]["id"]]
    eco.archived, ann.locked = True, False
    run(ZN.entretenir(g))
    assert not eco.archived and ann.locked, "réveillé ; le post des annonces se reverrouille"


class Piece:
    def __init__(self, nom, taille=10):
        self.filename, self.size = nom, taille

    async def to_file(self):
        return discord.File(io.BytesIO(b"x"), filename=self.filename)


def _message(mid, texte="", pieces=(), type_=discord.MessageType.default, components=()):
    return Obj(id=mid, content=texte, embeds=[], attachments=list(pieces), components=list(components),
               stickers=[], poll=None, type=type_)


def _annonces_pretes(env, monkeypatch, role=None):
    monkeypatch.setattr(A, "MAJ_VUES_S", 0)
    monkeypatch.setattr(A, "ARRIVEES_S", 0)
    A._fils_connus.clear()
    A._arrivees.clear()

    async def noter(*_a, **_k):
        return None
    A.setup(get_db=env.get_db, cfg=env.cfg, db_set=env.db_set, est_tete=lambda g, m: True, journal=noter,
            role_clan=lambda g, c: role, log=lambda *a: None)
    run(A.init_db())


def test_Z18_les_quatre_anciens_salons_partent_info_est_recopie(env, monkeypatch):
    """« Les 4 salons actuels sont supprimés : le texte d'info-gorp est recopié dans 📢 Infos,
    l'historique du chat est perdu. »"""
    g = Monde()
    _join, hub_clan = _clan_et_vocaux(g, env.conf)
    info, chat = g.nom("📢▷・info-gorp"), g.nom("✍▷・chat-gorpsea")
    info.historique = [_message(11, "Bienvenue dans le clan !"), _message(12, pieces=[Piece("regles.png")]),
                       _message(13, "x" * 1500 + "\n" + "y" * 1000),
                       _message(14, type_=discord.MessageType.pins_add)]
    clan, v1_annonces, v1_forum = _v1_du_clan(g, env.conf)
    env.conf.update(link_allowed_channels=[chat.id], zones_correspondances={"5": 6})
    role = run(g.create_role(name="GoRPC"))
    _annonces_pretes(env, monkeypatch, role)
    run(A.publier(g, g.membre(1), A.Brouillon(salon_id=v1_annonces.id, titre="Sortie", texte="Ce soir 21 h", fil=False)))
    run(A.marquer_vu(interaction(g, g.membre(7)), 1))
    run(ZN.installer_clan(g, role, []))
    faits = run(ZN.demenager_clan(g, deplacer_annonces=A.deplacer))
    c = env.conf
    posts = c["clan_posts"]
    infos = g.fils[posts["infos"]["id"]]
    assert [x for x, _kw in infos.envois] == ["Bienvenue dans le clan !", None, "x" * 1500, "y" * 1000], \
        "dans l'ordre ; le texte long coupé à la ligne ; l'épinglage ignoré"
    assert infos.envois[1][1]["files"][0].filename == "regles.png", "l'image suit"
    assert all(ch.supprime for ch in (info, chat, v1_annonces, v1_forum)), "les quatre anciens salons partent"
    assert [s.name for s in clan.channels] == ["🦜▷・clan-gorp", "🔊Join"] and not hub_clan.supprime
    fil = g.fils[posts["annonces"]["id"]]
    a = run(A.charger(1))
    assert (a["salon_id"], a["message_id"]) == (fil.id, fil.messages[-1].id) and run(A.compter_vues(1)) == 1, \
        "l'annonce passe dans 📣 Annonces avec son « ✅ Vu »"
    assert c["link_allowed_channels"] == [chat.id, posts["chat"]["id"]], "les réglages suivent le chat"
    assert c["zones_correspondances"]["5"] == 6 and c["zones_correspondances"][str(info.id)] == posts["infos"]["id"]
    assert "3 message(s) d'info recopié(s) dans 📢 Infos" in faits and c["clan_demenage_v2"] == 1
    assert run(ZN.demenager_clan(g, deplacer_annonces=A.deplacer)) == [], "une fois"


def test_Z18b_une_recopie_incomplete_garde_info_gorp(env, monkeypatch):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    info, chat = g.nom("📢▷・info-gorp"), g.nom("✍▷・chat-gorpsea")
    info.historique = [_message(11, "Règles"), _message(12, components=["un panneau de bot"])]
    role = run(g.create_role(name="GoRPC"))
    _annonces_pretes(env, monkeypatch, role)
    run(ZN.installer_clan(g, role, []))
    faits = run(ZN.demenager_clan(g, deplacer_annonces=A.deplacer))
    assert not info.supprime and chat.supprime, "rien n'est perdu : info-gorp reste"
    assert any("📢▷・info-gorp gardé : 1 message(s)" in x for x in faits)
    assert env.conf["clan_infos_dernier"] == 12, "reprendrait après le dernier message lu"


def test_Z19_le_guide_du_clan_en_tete_du_forum(env):
    g = Monde()
    _join, hub_clan = _clan_et_vocaux(g, env.conf)
    ticket = g._salon(Texte, "🏷ticket", {"category": g.categorie("🎫 TICKETS")})
    ZN.setup(cfg=env.cfg, db_set=env.db_set, lecteurs=lambda g, c: [], ticket=lambda _g: ticket, log=lambda *a: None)
    role = run(g.create_role(name="GoRPC"))
    run(ZN.installer_clan(g, role, []))
    c = env.conf
    posts = c["clan_posts"]
    forum = g.get_channel(c["clan_forum_v2"])
    guide = posts["guide"]
    assert forum.crees[-1].fil.id == guide["id"], "le plus récent : en tête du forum"
    fil = g.fils[guide["id"]]
    assert fil.locked and fil.name == "🧭 Guide du clan · Clan guide"
    vue = [k for mid, k in fil.cartes if mid == guide["ouverture"]][-1]["view"]
    t = textes(vue)
    for morceau in ("Bienvenue dans l'équipage", "Welcome aboard", "### 📢 Infos · Info", "### 📣 Annonces",
                    "### 💬 Chat", f"🔊 <#{hub_clan.id}>", "### 💰 Économie", "### 🤝 Trade du clan",
                    "### 🍺 Taverne", "### 🎫 Une question"):
        assert morceau in t, morceau
    liens = [b.url for b in vue.walk_children() if isinstance(b, discord.ui.Button) and b.url]
    assert liens == [f"https://discord.com/channels/1/{posts[k]['id']}"
                     for k in ("infos", "annonces", "chat", "economie", "trade", "taverne")] + [ticket.jump_url]
    assert compter(vue) <= 40 and c["clan_guide_v"].startswith(f"{ZN.GUIDE_CLAN_VERSION}|")
    assert not run(ZN.assurer_guide_clan(g)), "rien n'a changé : pas de réécriture"
    del g.fils[posts["taverne"]["id"]]
    posts.pop("taverne")
    assert run(ZN.assurer_guide_clan(g)) and "Taverne" not in textes(fil.cartes[-1][1]["view"]), \
        "un post parti : sa ligne part (aucun bouton qui ment)"


def test_Z20_les_annonces_du_clan_vivent_dans_leur_post(env, monkeypatch):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    role = run(g.create_role(name="GoRPC"))
    _annonces_pretes(env, monkeypatch, role)
    run(ZN.installer_clan(g, role, []))
    fil = g.fils[env.conf["clan_posts"]["annonces"]["id"]]
    assert fil in A.destinations(g, env.conf), "le post 📣 Annonces est proposé"
    vue = A.VueApercu(g.membre(1), g, A.Brouillon(salon_id=fil.id, titre="t", texte="x"), (), env.conf)
    assert not any("Fil de suite" in (getattr(b, "label", "") or "") for b in vue.walk_children()), \
        "pas de fil dans un fil : le bouton n'est pas proposé"
    fil.archived = True
    lien, erreur = run(A.publier(g, g.membre(1), A.Brouillon(salon_id=fil.id, titre="Raid", texte="Ce soir", fil=True)))
    a = run(A.charger(1))
    assert erreur == "" and not fil.archived, "le post endormi se rouvre"
    assert (a["salon_id"], a["fil_id"]) == (fil.id, 0) and "Raid" in textes(fil.messages[-1].kw["view"])
    nouveau = g.membre(50)
    avant = Obj(roles=[])
    nouveau.roles = [role]
    run(A.sur_maj_membre(avant, nouveau))
    assert "Bienvenue dans l'équipage" in textes(fil.messages[-1].kw["view"]), "l'arrivée s'annonce dans le post"


def test_Z21_branche_dans_le_bot():
    boucle = _source("entraide_task")
    assert "not c.get('clan_v2')" in boucle and "await _installer_clan(g, c)" in boucle
    assert "c.get('clan_v2') and (not c.get('clan_demenage_v2'))" in boucle and "await _demenager_clan(g, c)" in boucle
    assert "zones.demenager_clan(g, deplacer_annonces=annonces.deplacer)" in _source("_demenager_clan")
    assert "_reporter_immunites(g, await cfg(g.id))" in _source("_demenager_clan"), "l'immunité suit aussi"
    for cle in ('"clan_forum": any(', '"clan_propre": any(', '"post_crews": any(', '"porteurs_sans_direction": sum(',
                '"clan_anciens_salons": sum('):
        assert cle in SRC, cle
    assert (RACINE / "visuels" / "clan_guide.gif").is_file() and (RACINE / "visuels" / "cadeaux.gif").is_file()


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


def test_Z15_le_guide_de_rell_seas_en_tete_du_forum(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    tickets = g.categorie("🎫 TICKETS")
    ticket = g._salon(Texte, "🏷ticket", {"category": tickets})
    ZN.setup(cfg=env.cfg, db_set=env.db_set, lecteurs=lambda g, c: [], ticket=lambda _g: ticket, log=lambda *a: None)
    run(ZN.installer(g))
    c = env.conf
    rell = g.nom("🌊rell-seas")
    guide = c["zones_posts"]["guide"]
    assert rell.crees[-1].fil.id == guide["id"], "le plus récent : en tête du forum"
    fil = g.fils[guide["id"]]
    assert fil.locked and fil.name == "🧭 Guide · Rell Seas"
    vue = [k for mid, k in fil.cartes if mid == guide["ouverture"]][-1]["view"]
    t = textes(vue)
    for morceau in ("Bienvenue à bord", "Welcome aboard", "### 🌊 Discuter · Talk", "### 🛟 S'entraider · Get help",
                    "### 🤝 Échanger · Trade", "### 🏅 Qui certifie", "### 🏴‍☠️ Le clan GoRP",
                    "ne donne jamais en premier"):
        assert morceau in t, morceau
    assert "Équipages" not in t and "Crews" not in t and "crew" not in t, "plus d'équipages"
    roles = c["rs_roles"]
    assert f"<@&{roles['boss']}>" in t and f"<@&{roles['trade']}>" in t, "les rôles qui certifient sont cités"
    liens = [b.url for b in vue.walk_children() if isinstance(b, discord.ui.Button) and b.url]
    assert liens == [f"https://discord.com/channels/1/{c['zones_posts'][k]['id']}" for k in ("rell_chat", "help", "trade")
                     ] + [ticket.jump_url]
    assert compter(vue) <= 40 and c["zones_guide_v"].startswith(f"{ZN.GUIDE_VERSION}|")
    assert not run(ZN.assurer_guide(g)), "rien n'a changé : pas de réécriture"
    del g.fils[c["zones_posts"]["trade"]["id"]]
    c["zones_posts"].pop("trade")
    assert run(ZN.assurer_guide(g)) and "Échanger · Trade" not in textes(fil.cartes[-1][1]["view"]),         "un post parti : sa ligne part (aucun bouton qui ment)"


def test_Z15b_le_guide_de_clover_rpg_le_meme_sans_le_clan(env):
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    ticket = g._salon(Texte, "🏷ticket", {"category": g.categorie("🎫 TICKETS")})
    ZN.setup(cfg=env.cfg, db_set=env.db_set, lecteurs=lambda g, c: [], ticket=lambda _g: ticket, log=lambda *a: None)
    run(ZN.installer(g))
    c = env.conf
    guide = c["zones_posts"]["cl_guide"]
    assert g.nom("🍀clover-rpg").crees[-1].fil.id == guide["id"], "le plus récent : en tête du forum"
    fil = g.fils[guide["id"]]
    assert fil.locked and fil.name == "🧭 Guide · Clover RPG"
    vue = [k for mid, k in fil.cartes if mid == guide["ouverture"]][-1]["view"]
    t = textes(vue)
    for morceau in ("Bienvenue sur Clover RPG", "Welcome to Clover RPG", "### 🍀 Discuter · Talk", "quêtes, objets",
                    "### 🛟 S'entraider · Get help", "### 🤝 Échanger · Trade", "### 🏅 Qui certifie",
                    "### 🎫 Une question ?"):
        assert morceau in t, morceau
    roles = c["rs_roles"]
    assert "Le clan GoRP" not in t, "le clan, c'est Rell Seas"
    assert f"<@&{roles['cl_boss']}>" in t and f"<@&{roles['cl_trade']}>" in t and f"<@&{roles['boss']}>" not in t, \
        "les guides de Clover RPG, pas ceux de Rell Seas"
    liens = [b.url for b in vue.walk_children() if isinstance(b, discord.ui.Button) and b.url]
    assert liens == [f"https://discord.com/channels/1/{c['zones_posts'][k]['id']}"
                     for k in ("cl_chat", "cl_help", "cl_trade")] + [ticket.jump_url]
    assert compter(vue) <= 40 and c["zones_guide_v_clover"].startswith(f"{ZN.GUIDE_VERSION}|")


def test_Z16_plus_d_archives_tout_part_meme_si_discord_tarde(env):
    g = _archives_d_avant(env)
    c = env.conf
    archives = ZN.archives(g, c)
    cat = g.get_channel(c["zones_categorie_archives"])
    assert len(archives) == 9 and cat is not None
    for ch in archives:  # Discord efface, mais son cache garde encore le salon un instant

        async def effacer_sans_cache(ch=ch, **_k):
            ch.supprime = True
        ch.delete = effacer_sans_cache
    tableau, journal = [], []

    async def _salon_tableau(_g):
        tableau.append(1)

    async def _au_journal(*a, **_k):
        journal.append(a)
    ns = {"zones": ZN, "cfg": env.cfg, "_au_journal": _au_journal, "_salon_tableau": _salon_tableau}
    exec(_source("_supprimer_toutes_archives"), ns)  # noqa: S102 — code du dépôt
    assert run(ns["_supprimer_toutes_archives"](g)) == 9
    assert all(ch.supprime for ch in archives) and cat.supprime, "les salons et la catégorie : plus d'archive"
    assert c["zones_archives"] == [] and c["zones_categorie_archives"] == 0 and tableau
    assert "Archives supprimées à la demande du fondateur (9)" in journal[-1][3]
    boucle = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "entraide_task")
    assert boucle.index("db_set(g.id, 'archives_supprimees_v1'") < boucle.index("_supprimer_toutes_archives(g)"),         "une fois, témoin d'abord"


def test_Z17_les_equipages_partent_une_fois_et_ne_reviennent_pas(env):
    """« Le crew équipage… pour éviter que les gens fassent leur pub… c'est une mauvaise idée. »"""
    g = Monde()
    _clan_et_vocaux(g, env.conf)
    run(ZN.installer(g))
    c = env.conf
    rell = g.nom("🌊rell-seas")
    crews = run(rell.create_thread(name="⚓ Crews · Équipages")).thread  # le post d'avant, s'il restait
    c["zones_posts"]["crews"] = {"id": crews.id, "ouverture": crews.id}
    c.update(eq_forum=crews.id, eq_panneau=crews.id, eq_ouverture=crews.id)
    run(Q.publier(interaction(g, g.membre(22)), "marine", {"nom": "La Flotte", "pseudo": "P", "membres": "",
                                                            "niveau": "", "presentation": "Ordre et honneur."}))
    journal, aides = [], []

    async def _au_journal(*a, **_k):
        journal.append(a)

    async def _salon_aide(_g):
        aides.append(1)
    ns = {"cfg": env.cfg, "db_set": env.db_set, "zones": ZN, "equipages": Q, "discord": discord,
          "_au_journal": _au_journal, "_salon_aide": _salon_aide, "_logerr": lambda *a, **k: None}
    exec(_source("_retirer_equipages"), ns)  # noqa: S102 — code du dépôt
    assert run(ns["_retirer_equipages"](g)) == 1
    assert crews.id not in g.fils and "crews" not in c["zones_posts"], "le post ⚓ part"
    assert (c["eq_forum"], c["eq_panneau"], c["eq_ouverture"]) == (0, 0, 0) and run(Q.lister(1)) == []
    assert "Équipages retirés" in journal[-1][3] and aides, "noté au journal ; ❓ aide réécrit"
    run(ZN.entretenir(g))
    assert not any("⚓" in f.name for f in g.fils.values()), "l'entretien ne le recrée pas"
    boucle = next(ast.unparse(n) for n in ARBRE.body if getattr(n, "name", "") == "entraide_task")
    assert boucle.index("db_set(g.id, 'equipages_retires_v1'") < boucle.index("_retirer_equipages(g)"), "une fois"
    assert "equipages.entretenir" not in boucle and '"crews"' not in _source("_faq_destinations")
