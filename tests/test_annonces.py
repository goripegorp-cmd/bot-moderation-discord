"""22/10/2026 : « des annonces ultra bien faites, custom, avec une magnifique image… juste à mettre un
texte… un système de coche verte pour que les gens aient vu l'annonce… ranger par fil » et « un salon
des annonces du clan… automatisé, propre… cliquer sur un bouton, remplir le texte ». Sur un faux
serveur (`faux_serveur.py`) qui reprend la capture : Information, Sneak Peek, le clan."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import discord
import pytest

import annonces as A
import zones as ZN
from conftest_discord import Obj, base
from faux_serveur import Monde, Texte, Vocal, compter, ids, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
FONDATEUR = 781205382923288593


class FauxPiece:
    """Une image envoyée dans le formulaire."""
    def __init__(self, type_="image/png", octets=b"\x89PNG\r\n\x1a\nimage", taille=None):
        self.content_type, self.octets = type_, octets
        self.size = len(octets) if taille is None else taille

    async def read(self):
        return self.octets


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal, langues, clan = [], {}, {}

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))

    async def langue(i):
        return langues.get(i.user.id, "fr")
    monkeypatch.setattr(A, "MAJ_VUES_S", 0)
    monkeypatch.setattr(A, "ARRIVEES_S", 0)
    A._maj_prevues.clear()
    A._arrivees.clear()
    A.setup(get_db=get_db, cfg=cfg, db_set=db_set, est_tete=lambda g, m: m.id == FONDATEUR, journal=noter,
            role_clan=lambda g, c: clan.get("role"), langue=langue, log=lambda *a: None)
    asyncio.run(A.init_db())
    ZN.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    return Obj(conf=conf, journal=journal, langues=langues, clan=clan)


def serveur(env):
    """La capture du 22/10 : Information, Sneak Peek, puis le clan (info, chat, Join)."""
    g = Monde()
    info = g.categorie("· Information")
    for nom in ("📜annonce", "🟢target-roblox", "🟠ambrebois", "🧾sneak-fix"):
        g._salon(Texte, nom, {"category": info})
    sneak = g.categorie("· Sneak Peek")
    for nom in ("🎥goripe", "🔔sneak-news-roblox", "📀sneak-rellseas"):
        g._salon(Texte, nom, {"category": sneak})
    clan = g.categorie("🦜 · GoRp_SEA")
    g._salon(Texte, "📢▷・info-gorp", {"category": clan})
    g._salon(Texte, "✍▷・chat-gorpsea", {"category": clan})
    g._salon(Vocal, "🔊Join", {"category": clan})
    role = run(g.create_role(name="GoRPC"))
    env.clan["role"] = role
    env.conf["rellseas_role"] = role.id
    return g


def bouton(vue, debut):
    return next(b for b in vue.walk_children() if isinstance(b, discord.ui.Button) and (b.label or "").startswith(debut))


def test_N1_les_salons_d_annonces_et_leur_bandeau(env):
    g = serveur(env)
    run(ZN.installer_clan(g, env.clan["role"]))
    salons = A.destinations(g, env.conf)
    assert [s.name for s in salons] == ["📜annonce", "🟢target-roblox", "🟠ambrebois", "🧾sneak-fix", "🎥goripe",
                                        "📀sneak-rellseas", "📣 Annonces · Announcements"],         "les actus Roblox arrivent seules ; le post 📣 Annonces du forum du clan en dernier"
    styles = {s.name: A.style_de(s, env.conf)[0] for s in salons}
    assert styles == {"📜annonce": "an_annonce", "🟢target-roblox": "an_target", "🟠ambrebois": "an_ambrebois",
                      "🧾sneak-fix": "an_sneakfix", "🎥goripe": "an_goripe", "📀sneak-rellseas": "an_rellseas",
                      "📣 Annonces · Announcements": "an_clan"}
    assert all((RACINE / "visuels" / f"{k}.gif").is_file() for k in styles.values()), "chaque bandeau existe"


def test_N2_les_liens_un_par_ligne_cinq_au_plus():
    liens, erreurs = A.lire_liens("Twitch | https://twitch.tv/goripe\nhttps://www.youtube.com/@goripe\npas un lien\n")
    assert liens == [("Twitch", "https://twitch.tv/goripe"), ("youtube.com", "https://www.youtube.com/@goripe")]
    assert len(erreurs) == 1 and "pas un lien" in erreurs[0]
    liens, erreurs = A.lire_liens("\n".join(f"L{n} | https://exemple.fr/{n}" for n in range(7)))
    assert len(liens) == 5 and "Cinq liens au plus" in erreurs[0]


def test_N3_un_clic_un_formulaire_l_apercu_exact_puis_publier(env):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    i = interaction(g, g.membre(5))
    run(A.BoutonComposer().callback(i))
    assert i.response.messages[0][0] == "Réservé au fondateur et à la direction.", "le bouton ne sert qu'à eux"
    i = interaction(g, tete)
    run(A.BoutonComposer().callback(i))
    composer = i.response.messages[0][1]["view"]
    assert isinstance(composer, A.VueComposer) and "Nouvelle annonce" in textes(composer)
    salon = g.nom("📜annonce")
    j = interaction(g, tete)
    j.data = {"values": [str(salon.id)]}
    run(next(c for c in composer.walk_children() if isinstance(c, discord.ui.Select)).callback(j))
    form = j.response.modals[0]
    assert isinstance(form, A.FormulaireAnnonce) and len(form.children) == 4
    form.titre._value = "La mise à jour 2.4 est là"
    form.texte._value = "Nouvelles îles, nouveaux boss.\n**Rendez-vous ce soir !**"
    form.liens._value = "Notes de version | https://exemple.fr/notes"
    form.image._values = [FauxPiece()]
    k = interaction(g, tete)
    run(form.on_submit(k))
    contenu, kw = k.suivis[-1]
    apercu = kw["view"]
    assert contenu == "edit" and isinstance(apercu, A.VueApercu) and kw["attachments"][0].filename == "annonce.png"
    t = textes(apercu)
    assert "## La mise à jour 2.4 est là" in t and "Rendez-vous ce soir" in t and "Notes de version" in t
    assert "Aperçu : toi seul le vois" in t and compter(apercu) <= 40
    m = interaction(g, tete)
    run(bouton(apercu, "Mention").callback(m))
    apercu = m.response.edits[-1]["view"]
    assert "@everyone" in textes(apercu) and "Mention : @everyone" in textes(apercu)
    p = interaction(g, tete)
    run(bouton(apercu, "Publier").callback(p))
    assert "✅ Annonce publiée : https://discord.com/channels/1/" in textes(p.suivis[-1][1]["view"])
    mid, _c, envoi = salon.envois[-1]
    assert envoi["file"].filename == "annonce.png" and envoi["allowed_mentions"].everyone is True
    vue = envoi["view"]
    assert ids(vue) == ["an:v:1"] and "@everyone" in textes(vue) and "## La mise à jour 2.4 est là" in textes(vue)
    assert "📣 GoRP SEA" in textes(vue) and compter(vue) <= 40
    fil = g.fils[mid]
    assert fil.name == "📌 La mise à jour 2.4 est là", "la suite se range dans son fil"
    a = run(A.charger(1))
    assert (a["message_id"], a["fil_id"], a["image"], a["mention"]) == (mid, mid, "annonce.png", "@everyone")
    assert env.journal[-1][0] == "annonce.publiee"


def test_N4_la_coche_verte_une_fois_par_membre_le_compteur_suit(env, monkeypatch):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    salon = g.nom("🟢target-roblox")
    lien, erreur = run(A.publier(g, tete, A.Brouillon(salon_id=salon.id, titre="Objectif atteint",
                                                      texte="Merci à tous !", fil=False)))
    assert erreur == "" and lien.startswith("https://") and salon.envois[-1][-1].get("file") is None
    assert "Target Roblox" in str(salon.envois[-1][-1]["view"].to_components()), "le bandeau du salon"
    env.langues[8] = "en"
    reponses = []
    for uid in (7, 8, 7):
        i = interaction(g, g.membre(uid))
        run(A.BoutonVu(1).callback(i))
        reponses.append(i.response.messages[0][0])
    assert reponses == ["✅ C'est noté, merci d'avoir lu.", "✅ Noted, thanks for reading.", "Déjà noté ✅"]
    assert run(A.compter_vues(1)) == 2 and [m for m, _q in run(A.qui_a_vu(1))] == [7, 8]
    mid = salon.envois[-1][0]
    assert salon.cartes[-1][0] == mid and "Vu · Seen · 2" in textes(salon.cartes[-1][1]["view"])
    monkeypatch.setattr(A, "MAJ_VUES_S", 0.5)
    n = len(salon.cartes)

    async def rafale():
        for uid in range(20, 30):
            await A.marquer_vu(interaction(g, g.membre(uid)), 1)
    run(rafale())
    assert len(salon.cartes) == n + 1 and "Vu · Seen · 12" in textes(salon.cartes[-1][1]["view"]), \
        "une rafale de clics : une seule réécriture"
    i = interaction(g, g.membre(9))
    run(A.BoutonVu(99).callback(i))
    assert i.response.messages[0][0] == "Cette annonce n'existe plus."


def test_N5_les_annonces_du_clan_le_clan_mentionne_les_arrivees_annoncees(env, monkeypatch):
    g = serveur(env)
    role = env.clan["role"]
    run(ZN.installer_clan(g, role))
    salon = g.get_channel_or_thread(env.conf["clan_annonces"])  # le post 📣 Annonces du forum du clan
    tete = g.membre(FONDATEUR)
    b = A.Brouillon(salon_id=salon.id, titre="Réunion du clan", texte="Ce soir, 21 h.", mention="clan")
    vue = A.VueApercu(tete, g, b, (), env.conf)
    assert vue.options_mention == ["", "everyone", "clan"] and "Mention : le clan" in textes(vue)
    assert run(A.publier(g, tete, b))[1] == ""
    envoi = salon.envois[-1][-1]
    assert envoi["allowed_mentions"].roles == [role] and role.mention in textes(envoi["view"])
    assert "Annonce du clan" in str(envoi["view"].to_components())
    n = len(salon.envois)
    run(A.sur_maj_membre(g.membre(40), g.membre(40, role)))
    carte = salon.envois[-1][-1]
    assert len(salon.envois) == n + 1 and "Bienvenue dans l'équipage · Welcome aboard" in textes(carte["view"])
    assert "<@40> rejoint le clan GoRP" in textes(carte["view"]) and [u.id for u in carte["allowed_mentions"].users] == [40]
    monkeypatch.setattr(A, "ARRIVEES_S", 0.3)

    async def deux():
        await A.sur_maj_membre(g.membre(41), g.membre(41, role))
        await A.sur_maj_membre(g.membre(42), g.membre(42, role))
    run(deux())
    assert len(salon.envois) == n + 2 and "<@41>, <@42> rejoignent" in textes(salon.envois[-1][-1]["view"]), \
        "les arrivées d'une minute partagent une carte"
    run(A.sur_maj_membre(g.membre(40, role), g.membre(40, role)))
    assert len(salon.envois) == n + 2, "un rôle déjà là n'annonce rien"


def test_N6_ce_qui_ne_peut_pas_partir_le_dit(env):
    g = serveur(env)
    tete = g.membre(FONDATEUR)
    salon = g.nom("🧾sneak-fix")
    b = A.Brouillon(salon_id=salon.id, titre="Correctif", texte="Le bug des quêtes est réglé.", mention="everyone")
    salon.refus = {"mention_everyone"}
    assert "personne ne sera notifié" in textes(A.VueApercu(tete, g, b, (), env.conf)), "aucun bouton qui ment"
    salon.refus = {"send_messages"}
    assert "Je ne peux pas publier" in run(A.publier(g, tete, b))[1]
    salon.refus, salon.panne = set(), True
    assert "Discord a refusé" in run(A.publier(g, tete, b))[1] and run(A.charger(1)) is None, "rien n'est gardé"
    salon.panne = False
    form = A.FormulaireAnnonce(A.VueComposer(tete, g, A.destinations(g, env.conf), A.Brouillon(salon_id=salon.id)))
    form.titre._value, form.texte._value = "Correctif", "Texte"
    form.image._values = [FauxPiece("application/pdf")]
    k = interaction(g, tete)
    run(form.on_submit(k))
    assert "PNG, un JPG, un GIF ou un WebP" in textes(k.suivis[-1][1]["view"]) and k.suivis[-1][1]["attachments"] == []


def test_N7_branche_dans_le_bot():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    assert "bot.add_dynamic_items(annonces.BoutonComposer, annonces.BoutonVu)" in src
    assert "await annonces.init_db()" in src and "est_tete=_a_la_tete" in src
    menu = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_menu_logs")
    assert "annonces.BoutonComposer()" in menu, "le bouton est dans 📋logs, que seule la direction voit"
    maj = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "on_member_update")
    assert "annonces.sur_maj_membre(before, after)" in maj
    boucle = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "entraide_task")
    assert "_installer_clan(g, c)" in boucle and '"clan_zone": any(' in src
