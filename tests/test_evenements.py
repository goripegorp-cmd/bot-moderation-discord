"""25/10/2026, le fondateur : « un onglet spécifique… dans Clan GoRP, avec le salon Info… faire des annonces et
déclencher des événements pour dire « Est-ce que vous êtes disponibles à telle heure ? » avec de vrais systèmes
de timer sur le Discord… annoncer officiellement les métiers des gens… envoyer le listing complet du clan… qu'il
custom tout comme il le souhaite, mais que tu l'aides énormément. » Et : « pas d'emojis, des trucs moches ».

Sur un faux serveur (`faux_serveur.py`) : le forum du clan installé (📢 Infos, 📣 Annonces…), le rôle du clan,
des membres ; le site appelle les routes comme le registre d'API les appellera (`fn(g, auteur, requete, corps)`).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import discord
import pytest

import evenements as E
import visuels
import zones as ZN
from conftest_discord import Obj, base
from faux_serveur import Fil, Monde, compter, ids, interaction, run, textes

RACINE = Path(__file__).resolve().parent.parent
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
T0 = 1_900_000_000
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️]")
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 image"


class FauxNatif:
    """Un évènement programmé de Discord."""

    def __init__(self, ident, kw):
        self.id, self.kw, self.status, self.edits, self.gestes = ident, kw, discord.EventStatus.scheduled, [], []

    async def edit(self, **kw):
        self.edits.append(kw)

    async def cancel(self, **_kw):
        self.gestes.append("cancel")
        self.status = discord.EventStatus.canceled

    async def start(self, **_kw):
        self.gestes.append("start")
        self.status = discord.EventStatus.active

    async def end(self, **_kw):
        self.gestes.append("end")
        self.status = discord.EventStatus.completed


def courir(coro):
    """Une boucle neuve par appel (comme `run`) : les verrous d'une boucle précédente sont oubliés."""
    E._verrous.clear()
    return run(coro)


@pytest.fixture
def env(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal, langues, horloge = [], {}, {"t": float(T0)}
    fiches, catalogue, medias = [], {}, {"img1": (WEBP, "webp")}

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))

    async def langue(i):
        return langues.get(i.user.id, "fr")
    monkeypatch.setattr(E, "_mur", lambda: horloge["t"])
    monkeypatch.setattr(E, "MAJ_CARTE_S", 0)
    monkeypatch.setattr(E, "AVIS_S", 0)
    monkeypatch.setattr(E, "MINUTEUR_S", 0)
    for d in (E._maj_prevues, E._minuteurs, E._verrous, E._fils_connus):
        d.clear()
    E._purge[0] = float(T0) + 10 ** 9   # le filet de nettoyage ne passe pas pendant les tests
    #  Les messages lus depuis Discord portent leurs composants (pour retrouver une carte par sa marque).
    envoyer = Fil.send

    async def send(self, content=None, **kw):
        m = await envoyer(self, content, **kw)
        if kw.get("view") is not None:
            m.components = kw["view"].to_components()
        return m
    monkeypatch.setattr(Fil, "send", send)
    g = Monde()
    g.categorie("🦜 · GoRp_SEA")
    role = run(g.create_role(name="GoRPC"))
    conf["rellseas_role"] = role.id
    ZN.setup(cfg=cfg, db_set=db_set, log=lambda *a: None)
    run(ZN.installer_clan(g, role))
    natifs = {}

    async def creer_natif(**kw):
        ev = FauxNatif(g.nouvel_id(), kw)
        natifs[ev.id] = ev
        return ev

    async def chercher_natif(i):
        if i not in natifs:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return natifs[i]
    g.create_scheduled_event = creer_natif
    g.get_scheduled_event = natifs.get
    g.fetch_scheduled_event = chercher_natif
    E.setup(get_db=get_db, cfg=cfg, journal=noter,
            role_clan=lambda g_, c: g_.get_role(int(c.get("rellseas_role", 0) or 0)), langue=langue,
            est_tete=lambda _g, m: m.id in (FONDATEUR, DIRECTION), fiches=lambda _g: fiches,
            catalogue=lambda _g: catalogue, media=lambda mid: medias.get(mid), log=lambda *a: None)
    run(E.init_db())
    posts = conf["clan_posts"]
    return Obj(g=g, conf=conf, role=role, journal=journal, langues=langues, horloge=horloge, fiches=fiches,
               catalogue=catalogue, medias=medias, natifs=natifs, tete=g.membre(FONDATEUR),
               infos=g.fils[posts["infos"]["id"]], annonces=g.fils[posts["annonces"]["id"]])


def api(env, nom, corps=None, requete=None, auteur=None):
    route = E.ROUTES_SITE[nom]
    return courir(route["fn"](env.g, auteur or env.tete, requete or {}, corps))


def brouillon(env, **valeurs):
    statut, r = api(env, "clan/brouillon", dict(valeurs))
    assert statut == 200, r
    return r["element"]


def evenement(env, **valeurs):
    defaut = {"type": "evenement", "titre": "Sortie en mer", "quand": T0 + 3 * 3600, "lieu": "Île du Crâne"}
    return brouillon(env, **{**defaut, **valeurs})


def publier(env, e):
    statut, r = api(env, "clan/publier", {"id": e["id"], "version": e["version"]})
    assert statut == 200, r
    return r


def inter(env, membre):
    i = interaction(env.g, membre)
    i.effaces = []

    async def effacer():
        i.effaces.append(True)
    i.delete_original_response = effacer
    return i


def bouton(env, eid, choix, membre):
    i = inter(env, membre)
    courir(E.BoutonReponse(eid, choix).callback(i))
    return textes(i.suivis[-1][1]["view"]), i


def derniere_carte(post, mid):
    """La dernière version d'un message : sa dernière réécriture, sinon son envoi."""
    edits = [kw["view"] for m, kw in post.cartes if m == mid and "view" in kw]
    if edits:
        return edits[-1]
    return next(kw["view"] for m in post.messages if m.id == mid for kw in [m.kw])


def tout_texte(vue) -> str:
    """Textes, libellés ET émojis des boutons d'une vue (aucun émoji Unicode ne doit s'y cacher)."""
    out = []

    def voir(c):
        if isinstance(c, dict):
            out.extend(str(c.get(k)) for k in ("content", "label", "placeholder", "description") if c.get(k))
            if isinstance(c.get("emoji"), dict) and c["emoji"].get("name"):
                out.append(c["emoji"]["name"])
            for x in c.get("components", []) or []:
                voir(x)
            for x in c.get("items", []) or []:
                voir(x)
            if c.get("accessory"):
                voir(c["accessory"])
    for comp in vue.to_components():
        voir(comp)
    return " ".join(out)


def mesure_reelle(vue) -> tuple:
    contenus = []

    def voir(c):
        if c.get("type") == 10:
            contenus.append(c["content"])
        for x in c.get("components", []) or []:
            voir(x)
        if c.get("accessory"):
            voir(c["accessory"])
    for comp in vue.to_components():
        voir(comp)
    return compter(vue), sum(len(x) for x in contenus)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le contrat avec le site
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV1_le_contrat_des_routes():
    attendu = {"clan/evenements": ("GET", False), "clan/apercu": ("GET", False), "clan/brouillon": ("POST", True),
               "clan/supprimer_brouillon": ("POST", True), "clan/publier": ("POST", False),
               "clan/modifier": ("POST", False), "clan/annuler": ("POST", False)}
    assert set(E.ROUTES_SITE) == set(attendu)
    for nom, (methode, hors_ligne) in attendu.items():
        r = E.ROUTES_SITE[nom]
        assert set(r) == {"methode", "fn", "ecriture", "hors_ligne", "corps_max", "grave"}, nom
        assert (r["methode"], r["hors_ligne"], r["ecriture"]) == (methode, hors_ligne, methode == "POST"), nom
        assert inspect.iscoroutinefunction(r["fn"]) and list(inspect.signature(r["fn"]).parameters) == \
            ["g", "auteur", "requete", "corps"], nom
    hors_ligne = [n for n, r in E.ROUTES_SITE.items() if r["hors_ligne"]]
    assert hors_ligne == ["clan/brouillon", "clan/supprimer_brouillon"], \
        "seuls les brouillons se rejouent hors ligne : publier, modifier, annuler touchent Discord"


def test_EV2_l_onglet_destinations_modeles_droits(env):
    statut, r = api(env, "clan/evenements")
    assert statut == 200
    dests = r["destinations"]
    assert dests[0] == {"id": str(env.infos.id), "nom": "Infos · Info", "defaut": True}, "📢 Infos par défaut"
    assert [d["nom"] for d in dests] == ["Infos · Info", "Annonces · Announcements", "Chat", "Taverne · Tavern"], "le guide n'en est pas"
    assert not any(EMOJI.search(d["nom"]) for d in dests), "aucun émoji sur le site"
    assert {m["type"] for m in r["modeles"]} == set(E.TYPES) and r["modeles"][0]["cle"] == "dispo"
    assert r["droits"] == {"discord_event": False, "role_clan": True, "role_clan_nom": "GoRPC", "fiches": True}
    assert r["brouillons"] == r["a_venir"] == r["passes"] == [] and r["limites"]["composants"] == 40
    assert set(r["defauts"]) == set(E.TYPES) and r["defauts"]["evenement"]["couleur"] == "#a8823f"
    assert api(env, "clan/evenements", auteur=env.g.membre(5)) == (403, {"erreur": "Réservé au fondateur et à la "
                                                                                "direction."})


def test_EV3_brouillon_versions_conflits_et_cle_client(env):
    e = evenement(env)
    assert (e["statut"], e["version"], e["phase"]) == ("brouillon", 1, "a_venir")
    v = e["valeurs"]
    assert (v["duree_min"], v["rappels"], v["mention"], v["reponses"], v["reserve_clan"], v["places"]) == \
        (60, [60], "inscrits", True, True, 0), "des réglages par défaut qui aident"
    assert e["destination"] == {"id": str(env.infos.id), "nom": "Infos · Info"}
    statut, r = api(env, "clan/brouillon", {"id": e["id"], "version": 1, "titre": "  Sortie   au Kraken  ",
                                            "rappels": [10, 1440, 10]})
    assert statut == 200 and r["element"]["version"] == 2
    assert (r["element"]["titre"], r["element"]["valeurs"]["rappels"]) == ("Sortie au Kraken", [1440, 10])
    statut, r = api(env, "clan/brouillon", {"id": e["id"], "version": 1, "titre": "Ancienne version"})
    assert statut == 409 and r["conflit"] is True and r["actuelle"]["titre"] == "Sortie au Kraken", \
        "deux onglets : rien n'est écrasé, les deux versions sont montrées"
    assert api(env, "clan/brouillon", {"id": e["id"], "titre": "x"})[0] == 400, "la version est demandée"
    #  Hors ligne : la même création rejouée (même `cle_client`) ne fait pas deux brouillons ; la suite la modifie.
    a = brouillon(env, type="annonce", cle_client="page-1234-abcd", titre="Bienvenue")
    b = brouillon(env, type="annonce", cle_client="page-1234-abcd", texte="Le texte")
    assert a["id"] == b["id"] and (b["titre"], b["valeurs"]["texte"], b["version"]) == ("Bienvenue", "Le texte", 2)
    statut, r = api(env, "clan/evenements")
    assert [x["id"] for x in r["brouillons"]] == [b["id"], e["id"]] and r["a_venir"] == []
    #  Changer de type garde le commun, et reste cohérent.
    c = brouillon(env, id=e["id"], version=2, type="annonce")
    assert (c["type"], c["titre"], c["valeurs"]["mention"]) == ("annonce", "Sortie au Kraken", "aucune")
    assert "quand" not in c["valeurs"] and "rappels" not in c["valeurs"]
    assert any(t == "clan.evenement.brouillon" for t, _x, _k in env.journal), "le journal du site"


@pytest.mark.parametrize("champ, valeur, morceau", [
    ("titre", "x" * 101, "100 caractères"),
    ("titre", 12, "texte est attendu"),
    ("texte", "x" * 2001, "2000 caractères"),
    ("quand", "demain", "horodatage"),
    ("quand", T0 + 400 * 86400, "Un an"),
    ("duree_min", 99999, "0 à 10080"),
    ("duree_min", True, "0 à 10080"),
    ("rappels", [1, 2, 3, 4, 5, 6], "5 rappels"),
    ("rappels", [-5], "minutes avant"),
    ("rappels", "60", "minutes avant"),
    ("couleur", "rouge", "#RRGGBB"),
    ("mention", "everyone", "aucune, clan ou inscrits"),
    ("destination", "123", "destination"),
    ("reponses", "oui", "Vrai ou faux"),
    ("places", 501, "0 à 500"),
    ("image", "../secret", "média invalide"),
    ("image", "absente", "Image introuvable"),
    ("groupement", "pirate", "metier, grade ou race"),
    ("champs", ["age"], "metiers, grade, race"),
    ("vitesse", 3, "Champ inconnu"),
])
def test_EV4_chaque_champ_est_verifie(env, champ, valeur, morceau):
    statut, r = api(env, "clan/brouillon", {"type": "evenement", champ: valeur})
    assert statut == 400 and morceau in r["champs"][champ], r


def test_EV5_les_regles_qui_tiennent_ensemble(env):
    statut, r = api(env, "clan/brouillon", {"type": "evenement", "places": 10, "reponses": False})
    assert statut == 400 and "boutons de réponse" in r["champs"]["places"]
    statut, r = api(env, "clan/brouillon", {"type": "annonce", "mention": "inscrits"})
    assert statut == 400 and "événement" in r["champs"]["mention"]
    statut, r = api(env, "clan/brouillon", {"type": "metiers", "groupement": "race"})
    assert statut == 400 and "par métier" in r["champs"]["groupement"]
    assert api(env, "clan/brouillon", {"type": "concert"})[0] == 400
    assert api(env, "clan/brouillon", ["pas", "un", "objet"])[0] == 400
    #  Un champ d'un autre type (des rappels sur une annonce) : vérifié, puis laissé de côté.
    a = brouillon(env, type="annonce", titre="A", rappels=[60], couleur="#112233")
    assert "rappels" not in a["valeurs"] and a["valeurs"]["couleur"] == "#112233"


def test_EV6_supprimer_un_brouillon_idempotent(env):
    e = evenement(env)
    assert api(env, "clan/supprimer_brouillon", {"id": e["id"], "version": 1}) == (200, {"ok": True})
    assert api(env, "clan/supprimer_brouillon", {"id": e["id"]}) == (200, {"ok": True, "deja": True}), \
        "rejouée au retour de la connexion : déjà fait"
    p = evenement(env)
    publier(env, p)
    statut, r = api(env, "clan/supprimer_brouillon", {"id": p["id"]})
    assert statut == 409 and "annule" in r["erreur"]


# ═══════════════════════════════════════════════════════════════════════════════
#  L'aperçu fidèle
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV7_l_apercu_dit_tout_ce_que_discord_montrera(env):
    e = evenement(env, quand=None, texte="On part du port à l'heure dite.", places=12, discord_event=True,
                  image="img1", rappels=[1440, 60, 0])
    statut, r = api(env, "clan/apercu", requete={"id": str(e["id"])})
    assert statut == 200 and r["publiable"] is False and "Il faut une date de début." in r["erreurs"]
    e = brouillon(env, id=e["id"], version=e["version"], quand=T0 + 2 * 3600)
    statut, r = api(env, "clan/apercu", requete={"id": str(e["id"])})
    assert r["publiable"] is True and r["erreurs"] == []
    assert any("Créer des évènements" in a for a in r["avertissements"]), "sans la permission, le site le dit"
    assert any("1 j avant" in a for a in r["avertissements"]), "le rappel de la veille est déjà passé"
    assert [x["minutes"] for x in r["rappels"]] == [1440, 60, 0] and r["rappels"][0]["passe"] is True
    [carte] = r["cartes"]
    assert carte["couleur"] == "#a8823f" and carte["composants"] <= 40 and carte["caracteres"] <= 4000
    types = [b["type"] for b in carte["blocs"]]
    assert types[0] == "image" and carte["blocs"][0]["url"] == "media/img1"
    assert types.count("boutons") == 1 and "separateur" in types
    lignes = [ln for b in carte["blocs"] if b["type"] == "texte" for ln in b["lignes"]]
    md = "\n".join(ln["md"] for ln in lignes)
    assert f"<t:{T0 + 7200}:F>" in md and f"<t:{T0 + 7200}:R>" in md, "la date en clair et le minuteur vivant"
    assert "RELL Seas · Île du Crâne" in md and "**Disponibles · Available — 0 / 12 places · spots**" in md
    assert "**Durée · Duration** 1 h" in md
    assert {ln["icone"] for ln in lignes} >= {"calendrier", "minuteur", "lieu", "horloge", "valider", "ancre",
                                              "cloche"}, "les icônes maison, par leur nom (le site dessine les siennes)"
    boutons = next(b for b in carte["blocs"] if b["type"] == "boutons")["boutons"]
    assert [(x["label"], x["icone"], x["desactive"]) for x in boutons] == [
        ("Disponible · Available", "valider", False), ("Peut-être · Maybe", "peut_etre", False),
        ("Pas disponible · Unavailable", "annuler", False)]
    assert not EMOJI.search(json.dumps(r, ensure_ascii=False)), "aucun émoji dans l'aperçu"
    assert api(env, "clan/apercu", requete={"id": "abc"})[0] == 400
    assert api(env, "clan/apercu", requete={"id": "999"})[0] == 404


# ═══════════════════════════════════════════════════════════════════════════════
#  Publier : une fois, jamais deux
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV8_publier_un_evenement_dans_infos(env):
    e = evenement(env, texte="Rendez-vous au port.", rappels=[1440, 60])
    r = publier(env, e)
    m = env.infos.messages[-1]
    assert r["lien"] == f"https://discord.com/channels/1/{env.infos.id}/{m.id}" and r["ok"] is True
    assert r["element"]["statut"] == "publie" and r["element"]["phase"] == "a_venir"
    assert r["element"]["rappels_faits"] == [1440], "trois heures avant, le rappel de la veille ne partira jamais"
    vue = m.kw["view"]
    assert ids(vue) == [f"ev:r:{e['id']}:d", f"ev:r:{e['id']}:p", f"ev:r:{e['id']}:n"]
    assert m.kw["allowed_mentions"].everyone is False and m.kw["allowed_mentions"].roles is False
    t = textes(vue)
    assert "## Sortie en mer" in t and "Rendez-vous au port." in t and f"<t:{T0 + 3 * 3600}:R>" in t
    assert "Personne pour l'instant · Nobody yet" in t
    assert "Rappels · Reminders : 1 h avant · before\n-# Les rappels mentionnent les disponibles" in t, \
        "la carte ne promet que les rappels à venir"
    conteneur = next(c for c in vue.to_components() if c["type"] == 17)
    assert conteneur["id"] == E.MARQUE + e["id"], "la marque qui retrouve la carte après une erreur d'envoi"
    type_, texte, kw = env.journal[-1]
    assert type_ == "clan.evenement.publie" and "Sortie en mer" in texte and kw["salon_id"] == env.infos.id
    statut, r2 = api(env, "clan/publier", {"id": e["id"]})
    assert statut == 409 and r2["lien"] == r["lien"] and len(env.infos.messages) == 1, "déjà publiée"
    statut, r3 = api(env, "clan/brouillon", {"id": e["id"], "version": r["element"]["version"], "titre": "x"})
    assert statut == 409 and r3["publie"] is True, "une publication se modifie en ligne, jamais par le brouillon"


def test_EV9_un_double_clic_ne_publie_qu_une_fois(env):
    e = evenement(env)
    route = E.ROUTES_SITE["clan/publier"]["fn"]

    async def deux_clics():
        return await asyncio.gather(route(env.g, env.tete, {}, {"id": e["id"], "version": 1}),
                                    route(env.g, env.tete, {}, {"id": e["id"], "version": 1}))
    a, b = courir(deux_clics())
    assert sorted([a[0], b[0]]) == [200, 409] and len(env.infos.messages) == 1


def test_EV10_ce_qui_empeche_de_publier_le_dit(env):
    e = evenement(env, quand=T0 + 30)
    statut, r = api(env, "clan/publier", {"id": e["id"]})
    assert statut == 400 and "futur" in r["erreur"] and env.infos.messages == []
    e = evenement(env)
    statut, r = api(env, "clan/publier", {"id": e["id"], "version": 7})
    assert statut == 409 and r["conflit"] is True, "on ne publie pas une version qu'on n'a pas vue"
    env.infos.parent.refus = {"send_messages_in_threads"}
    statut, r = api(env, "clan/publier", {"id": e["id"]})
    assert statut == 400 and "droit d'écrire" in r["erreur"]
    env.infos.parent.refus = set()
    a = brouillon(env, type="annonce", titre="Sans texte")
    assert api(env, "clan/publier", {"id": a["id"]})[1]["erreur"] == "Il faut un texte."


def test_EV11_une_erreur_d_envoi_relit_le_post_avant_de_conclure(env, monkeypatch):
    e = evenement(env)
    vrai = Fil.send

    async def arrive_puis_erreur(self, content=None, **kw):
        await vrai(self, content, **kw)
        raise discord.HTTPException(Obj(status=503, reason="x"), "délai")
    monkeypatch.setattr(Fil, "send", arrive_puis_erreur)
    statut, r = api(env, "clan/publier", {"id": e["id"]})
    assert statut == 200 and r["element"]["statut"] == "publie" and len(env.infos.messages) == 1, \
        "partie malgré l'erreur : gardée, jamais republiée"

    async def refus(self, content=None, **kw):
        raise discord.HTTPException(Obj(status=500, reason="x"), "panne")
    monkeypatch.setattr(Fil, "send", refus)
    f = evenement(env, titre="Autre")
    statut, r = api(env, "clan/publier", {"id": f["id"]})
    assert statut == 502 and "rien n'est parti" in r["erreur"]
    assert courir(E.charger(f["id"]))["statut"] == "brouillon", "rien n'est parti : on peut réessayer"

    def illisible(self, limit=None, after=None):
        raise discord.HTTPException(Obj(status=500, reason="x"), "panne")
    monkeypatch.setattr(Fil, "history", illisible)
    statut, r = api(env, "clan/publier", {"id": f["id"]})
    assert statut == 502 and r["incertain"] is True and courir(E.charger(f["id"]))["statut"] == "incertain"
    assert api(env, "clan/publier", {"id": f["id"]})[0] == 409, "incertaine : jamais republiée sans le dire"


def test_EV12_une_publication_interrompue_par_un_redemarrage(env, monkeypatch):
    e = evenement(env)
    publier(env, e)
    courir(E._ecrire("UPDATE clan_evenements SET statut='envoi', envoi_le=?, messages='[]' WHERE id=?",
                     (T0 - 600, e["id"])))
    f = evenement(env, titre="Jamais partie")
    courir(E._ecrire("UPDATE clan_evenements SET statut='envoi', envoi_le=? WHERE id=?", (T0 - 600, f["id"])))
    courir(E.tic([env.g]))
    e2, f2 = courir(E.charger(e["id"])), courir(E.charger(f["id"]))
    assert (e2["statut"], e2["messages"]) == ("publie", [env.infos.messages[0].id]), "partie : retrouvée par sa marque"
    assert f2["statut"] == "brouillon" and "rien n'est parti" in f2["note"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Les réponses
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV13_une_reponse_par_membre_qu_il_peut_changer(env):
    e = evenement(env)
    publier(env, e)
    mid = env.infos.messages[0].id
    pirates = [env.g.membre(uid, env.role) for uid in (11, 12, 13)]
    t, i = bouton(env, e["id"], "d", pirates[0])
    env.horloge["t"] += 1
    assert "C'est noté : **Disponible**." in t and f"Début <t:{T0 + 3 * 3600}:R>" in t
    assert "Les rappels te mentionneront." in t and i.effaces == [True], "un mot pour soi, qui s'efface"
    assert i.response.fait and i.suivis[-1][1]["ephemeral"] is True
    t, _i = bouton(env, e["id"], "d", pirates[0])
    assert "Tu as déjà répondu **Disponible**." in t
    for k, (pirate, choix) in enumerate(((pirates[1], "p"), (pirates[2], "d"), (pirates[0], "n"))):
        env.horloge["t"] = T0 + 10 + k                # l'ordre des réponses : celui des clics
        bouton(env, e["id"], choix, pirate)           # le premier change d'avis
    env.langues[12] = "en"
    env.horloge["t"] = T0 + 20
    t, _i = bouton(env, e["id"], "d", pirates[1])
    assert t.startswith("Noted: **Available**.")
    rep = courir(E._reponses(e["id"]))
    assert (rep["d"], rep["p"], rep["n"]) == ([13, 12], [], [11])
    carte = textes(derniere_carte(env.infos, mid))
    assert "**Disponibles · Available — 2**" in carte and "<@13>, <@12>" in carte
    assert "**Peut-être · Maybe — 0**" in carte and "**Pas disponibles · Unavailable — 1**" in carte
    edits = [kw for m, kw in env.infos.cartes if m == mid]
    assert all(kw["allowed_mentions"].users is False and kw["allowed_mentions"].roles is False for kw in edits), \
        "les noms des disponibles, jamais un ping"
    statut, r = api(env, "clan/evenements")
    assert r["a_venir"][0]["reponses"] == {"disponibles": 2, "peut_etre": 0, "pas_disponibles": 1, "vus": 0}


def test_EV14_les_places_le_clan_et_l_etat(env):
    e = evenement(env, places=2)
    publier(env, e)
    a, b, c = (env.g.membre(uid, env.role) for uid in (21, 22, 23))
    bouton(env, e["id"], "d", a)
    bouton(env, e["id"], "d", b)
    t, _i = bouton(env, e["id"], "d", c)
    assert "Complet : les 2 places sont déjà prises." in t and courir(E._reponses(e["id"]))["d"] == [21, 22]
    carte = derniere_carte(env.infos, env.infos.messages[0].id)
    gris = [b for b in carte.walk_children() if isinstance(b, discord.ui.Button) and b.disabled]
    assert "Complet · Full" in textes(carte) and [b.label for b in gris] == ["Complet · Full"], \
        "le bouton « Complet » est grisé"
    assert [x for x in ids(carte) if x.startswith("ev:")] == [f"ev:r:{e['id']}:p", f"ev:r:{e['id']}:n"]
    t, _i = bouton(env, e["id"], "p", env.g.membre(40))
    assert t == "Cet événement est réservé aux membres du clan."
    t, _i = bouton(env, e["id"], "p", env.g.membre(DIRECTION))
    assert "C'est noté" in t, "la direction répond même sans le rôle du clan"
    f = evenement(env, reserve_clan=False, titre="Ouvert")
    publier(env, f)
    assert "C'est noté" in bouton(env, f["id"], "d", env.g.membre(41))[0]
    t, _i = bouton(env, 999, "d", a)
    assert t == "Cet événement n'existe plus."
    env.horloge["t"] = T0 + 10 * 3600
    t, _i = bouton(env, e["id"], "d", a)
    assert "terminé" in t


def test_EV15_une_rafale_de_clics_une_seule_reecriture(env, monkeypatch):
    e = evenement(env)
    publier(env, e)
    monkeypatch.setattr(E, "MAJ_CARTE_S", 1.5)      # large : la rafale tient dedans même sur une machine chargée
    mid = env.infos.messages[0].id
    n = len([1 for m, _kw in env.infos.cartes if m == mid])

    async def rafale():
        for uid in range(100, 110):
            i = inter(env, env.g.membre(uid, env.role))
            await E.repondre(i, e["id"], "d")
    courir(rafale())
    reecritures = [kw for m, kw in env.infos.cartes if m == mid]
    assert len(reecritures) == n + 1 and "— 10**" in textes(reecritures[-1]["view"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Les rappels et les états (la boucle)
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV16_les_rappels_mentionnent_les_disponibles_et_jamais_deux_fois(env):
    e = evenement(env, rappels=[60, 15, 0], quand=T0 + 3 * 3600)
    publier(env, e)
    for uid, choix in ((31, "d"), (32, "d"), (33, "p")):
        bouton(env, e["id"], choix, env.g.membre(uid, env.role))
    n = len(env.infos.messages)
    courir(E.tic([env.g]))
    assert len(env.infos.messages) == n, "trop tôt : rien"
    env.horloge["t"] = T0 + 2 * 3600 + 1     # une heure avant
    courir(E.tic([env.g]))
    rappel = env.infos.messages[-1]
    assert len(env.infos.messages) == n + 1
    t = textes(rappel.kw["view"])
    assert t.startswith("<@31> <@32>") and "Rappel · Reminder" in t and f"<t:{T0 + 3 * 3600}:R>" in t
    assert [u.id for u in rappel.kw["allowed_mentions"].users] == [31, 32], "seulement les « Disponible »"
    assert rappel.kw["allowed_mentions"].roles is False and rappel.kw["allowed_mentions"].everyone is False
    assert "ev:" not in " ".join(ids(rappel.kw["view"])) and \
        all(c.get("id") != E.MARQUE + e["id"] for c in rappel.kw["view"].to_components()), "un rappel n'est pas une carte"
    #  Redémarrage : la mémoire du module est vide, la base dit ce qui est parti.
    E._verrous.clear()
    E._maj_prevues.clear()
    courir(E.tic([env.g]))
    assert len(env.infos.messages) == n + 1, "après un redémarrage, rien ne repart deux fois"
    assert courir(E.charger(e["id"]))["rappels_faits"] == [60]
    #  Le bot était arrêté pendant le rappel de 15 min : au retour, seul le plus proche du début part.
    env.horloge["t"] = T0 + 3 * 3600 + 30
    courir(E.tic([env.g]))
    assert len(env.infos.messages) == n + 2 and "C'est l'heure · It's time" in textes(env.infos.messages[-1].kw["view"])
    assert courir(E.charger(e["id"]))["rappels_faits"] == [0, 15, 60]
    carte = textes(derniere_carte(env.infos, env.infos.messages[0].id))
    assert "En cours · Live now" in carte and f"Fin · Ends <t:{T0 + 4 * 3600}:R>" in carte


def test_EV17_a_venir_en_cours_termine(env):
    e = evenement(env, duree_min=90, rappels=[])
    publier(env, e)
    mid = env.infos.messages[0].id
    env.horloge["t"] = T0 + 3 * 3600 + 5
    courir(E.tic([env.g]))
    assert courir(E.charger(e["id"]))["phase"] == "en_cours" and "En cours · Live now" in \
        textes(derniere_carte(env.infos, mid))
    env.horloge["t"] = T0 + 5 * 3600
    courir(E.tic([env.g]))
    e2 = courir(E.charger(e["id"]))
    carte = derniere_carte(env.infos, mid)
    assert e2["phase"] == "termine" and e2["archive_le"] == T0 + 5 * 3600
    assert "Terminé · Ended" in textes(carte) and ids(carte) == [], "les réponses sont closes : plus de boutons"
    assert "Étaient disponibles · Were available" in textes(carte)
    statut, r = api(env, "clan/evenements")
    assert r["a_venir"] == [] and r["passes"][0]["id"] == e["id"]
    n = len(env.infos.cartes)
    courir(E.tic([env.g]))
    assert len(env.infos.cartes) == n, "un état déjà affiché ne se réécrit pas"


def test_EV18_le_minuteur_exact_a_l_approche(env, monkeypatch):
    """« De vrais timers » : à moins d'une minute du début, l'état change à la seconde, pas au passage suivant de
    la boucle (une minute plus tard)."""
    e = evenement(env, rappels=[])
    publier(env, e)
    monkeypatch.setattr(E, "MINUTEUR_S", 65.0)
    depart, debut = time.monotonic(), T0 + 3 * 3600 - 0.5     # une demi-seconde avant le début
    monkeypatch.setattr(E, "_mur", lambda: debut + time.monotonic() - depart)
    courir(E.tic([env.g]))
    assert courir(E.charger(e["id"]))["phase"] == "en_cours", "le minuteur a fait passer l'état à l'heure dite"
    assert "En cours · Live now" in textes(derniere_carte(env.infos, env.infos.messages[0].id))
    assert E._minuteurs == {}, "le minuteur a fini son travail"


# ═══════════════════════════════════════════════════════════════════════════════
#  L'évènement programmé natif de Discord
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV19_l_evenement_discord_suit_le_notre(env):
    env.g.me.guild_permissions.create_events = True
    e = evenement(env, discord_event=True, duree_min=120, texte="Le Kraken attend.", image="img1")
    r = publier(env, e)
    [natif] = env.natifs.values()
    kw = natif.kw
    assert kw["location"] == "RELL Seas · Île du Crâne" and kw["name"] == "Sortie en mer"
    assert kw["entity_type"] == discord.EntityType.external and kw["privacy_level"] == discord.PrivacyLevel.guild_only
    assert int(kw["start_time"].timestamp()) == T0 + 3 * 3600 and int(kw["end_time"].timestamp()) == T0 + 5 * 3600
    assert r["lien"] in kw["description"] and kw["image"] == WEBP
    assert r["element"]["discord_event"] == {"id": str(natif.id),
                                             "lien": f"https://discord.com/events/1/{natif.id}"}
    bouton(env, e["id"], "d", env.g.membre(51, env.role))
    n = len(env.infos.messages)
    el = courir(E.charger(e["id"]))
    statut, r = api(env, "clan/modifier", {"id": e["id"], "version": el["version"], "quand": T0 + 6 * 3600})
    assert statut == 200 and int(natif.edits[-1]["start_time"].timestamp()) == T0 + 6 * 3600
    notice = env.infos.messages[-1]
    assert len(env.infos.messages) == n + 1 and "Nouvel horaire · New time" in textes(notice.kw["view"])
    assert [u.id for u in notice.kw["allowed_mentions"].users] == [51], "les disponibles prévenus du nouvel horaire"
    env.horloge["t"] = T0 + 6 * 3600 + 5
    courir(E.tic([env.g]))
    assert natif.gestes == ["start"]
    statut, r = api(env, "clan/annuler", {"id": e["id"]})
    assert statut == 200 and r["element"]["statut"] == "annule" and natif.gestes == ["start", "end"]
    carte = textes(derniere_carte(env.infos, env.infos.messages[0].id))
    assert "Annulé · Cancelled" in carte and "Annulé · Cancelled" in textes(env.infos.messages[-1].kw["view"])
    assert api(env, "clan/annuler", {"id": e["id"]})[1]["deja"] is True


def test_EV20_sans_permission_le_site_le_dit(env):
    e = evenement(env, discord_event=True)
    r = publier(env, e)
    assert any("Créer des évènements" in a for a in r["avertissements"]) and env.natifs == {}
    assert "Créer des évènements" in r["element"]["note"] and r["element"]["discord_event"] is None
    assert len(env.infos.messages) == 1, "la carte, elle, est publiée"


def test_EV21_annuler_un_evenement_a_venir_previent_les_disponibles(env):
    env.g.me.guild_permissions.create_events = True
    e = evenement(env, discord_event=True)
    publier(env, e)
    [natif] = env.natifs.values()
    statut, r = api(env, "clan/annuler", {"id": e["id"]})
    assert statut == 200 and natif.gestes == ["cancel"] and len(env.infos.messages) == 1, \
        "personne n'était disponible : pas de message d'annulation inutile"
    t = textes(derniere_carte(env.infos, env.infos.messages[0].id))
    assert "Annulé · Cancelled" in t and ids(derniere_carte(env.infos, env.infos.messages[0].id)) == []
    t, _i = bouton(env, e["id"], "d", env.g.membre(52, env.role))
    assert t == "Cet événement est annulé."
    assert any(x[0] == "clan.evenement.annule" for x in env.journal)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'annonce
# ═══════════════════════════════════════════════════════════════════════════════

def test_EV22_l_annonce_vue_et_son_compteur(env):
    env.medias["img2"] = (b"\x89PNG\r\n\x1a\nimage", "png")
    a = brouillon(env, type="annonce", titre="Le clan recrute", texte="**Ouvert** à tous les pirates.",
                  image="img2", mention="clan")
    r = publier(env, a)
    assert r["avertissements"] == [], "le bot peut mentionner le clan ici"
    m = env.infos.messages[-1]
    assert m.kw["file"].filename == f"clan_{a['id']}.png"
    vue = m.kw["view"]
    t = textes(vue)
    assert t.startswith(env.role.mention) and "## Le clan recrute" in t and "**Ouvert** à tous les pirates." in t
    assert m.kw["allowed_mentions"].roles == [env.role] and m.kw["allowed_mentions"].users is False
    assert ids(vue) == [f"ev:vu:{a['id']}"]
    galerie = next(c for c in next(c for c in vue.to_components() if c["type"] == 17)["components"]
                   if c["type"] == 12)
    assert galerie["items"][0]["media"]["url"] == f"attachment://clan_{a['id']}.png"
    reponses = []
    for uid in (61, 62, 61):
        i = inter(env, env.g.membre(uid, env.role))
        courir(E.BoutonVu(a["id"]).callback(i))
        reponses.append(textes(i.suivis[-1][1]["view"]))
    assert reponses == ["C'est noté, merci d'avoir lu.", "C'est noté, merci d'avoir lu.", "Déjà noté."]
    derniere = derniere_carte(env.infos, m.id)
    assert "Vu · Seen · 2" in textes(derniere)
    galerie = next(c for c in next(c for c in derniere.to_components() if c["type"] == 17)["components"]
                   if c["type"] == 12)
    assert galerie["items"][0]["media"]["url"] == f"attachment://clan_{a['id']}.png", \
        "réécrite, la carte garde sa pièce jointe (même nom, même extension)"
    assert "attachments" not in [kw for mid, kw in env.infos.cartes if mid == m.id][-1], "l'image reste en place"
    statut, r2 = api(env, "clan/evenements")
    #  26/10/2026 : une annonce en ligne est rangée dans « Publiées » (plus avec les passés).
    assert r2["publiees"][0]["reponses"]["vus"] == 2 and not any(x["id"] == a["id"] for x in r2["passes"])
    statut, r3 = api(env, "clan/annuler", {"id": a["id"]})
    assert statut == 200 and r3["element"]["statut"] == "retire" and m.id in env.g.effaces
    statut, r4 = api(env, "clan/evenements")
    assert r4["passes"][0]["id"] == a["id"] and r4["publiees"] == [], "retirée, elle passe dans « Passés »"
    i = inter(env, env.g.membre(63))
    courir(E.BoutonVu(a["id"]).callback(i))
    assert textes(i.suivis[-1][1]["view"]) == "Cette annonce n'existe plus."


def test_EV23_l_annonce_sans_image_porte_le_bandeau_du_clan(env, monkeypatch):
    monkeypatch.setattr(visuels, "_servi", True)
    monkeypatch.setattr(visuels, "_base", "https://bot.exemple")
    a = brouillon(env, type="annonce", titre="Titre", texte="Texte")
    statut, r = api(env, "clan/apercu", requete={"id": str(a["id"])})
    assert r["cartes"][0]["blocs"][0] == {"type": "bandeau", "cle": "an_clan", "titre": "Annonce du clan",
                                          "url": "/v/an_clan.gif?v=1"}
    publier(env, a)
    vue = env.infos.messages[-1].kw["view"]
    assert "https://bot.exemple/v/an_clan.gif" in json.dumps(vue.to_components()), "le style du clan d'annonces.py"


def test_EV24_modifier_une_annonce_publiee(env):
    a = brouillon(env, type="annonce", titre="Titre", texte="Texte avec une fote")
    r = publier(env, a)
    mid = env.infos.messages[-1].id
    v = r["element"]["version"]
    statut, r = api(env, "clan/modifier", {"id": a["id"], "version": v, "texte": "Texte corrigé"})
    assert statut == 200 and "Texte corrigé" in textes(derniere_carte(env.infos, mid))
    assert api(env, "clan/modifier", {"id": a["id"], "version": v, "texte": "x"})[1]["conflit"] is True
    assert api(env, "clan/modifier", {"id": a["id"], "version": r["element"]["version"],
                                      "destination": str(env.annonces.id)})[0] == 400, "pas de changement de post"
    assert api(env, "clan/modifier", {"id": a["id"], "version": r["element"]["version"], "type": "listing"})[0] == 400
    assert api(env, "clan/modifier", {"id": a["id"], "version": 1, "nimporte": 1})[0] == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  L'annonce officielle des métiers et le listing complet du clan
# ═══════════════════════════════════════════════════════════════════════════════

def _equipage(env, n=6):
    env.catalogue.update({
        "metier": {"charpentier": {"nom": "Charpentier", "icone_emoji": "<:rell_charpentier_v1:123456789012345678>"},
                   "cuisinier": {"nom": "Cuisinier", "icone_emoji": "🍳"}, "navigateur": {"nom": "Navigateur"}},
        "grade": {"capitaine": {"nom": "Capitaine"}, "matelot": {"nom": "Matelot"}},
        "race": {"humain": {"nom": "Humain"}, "triton": {"nom": "Triton"}}})
    metiers = [["charpentier"], ["cuisinier", "charpentier"], ["navigateur"], [], ["cuisinier"], []]
    grades = ["capitaine", "matelot", "matelot", "", "matelot", "matelot"]
    for k in range(n):
        uid = 700 + k
        env.g.membre(uid, env.role)
        if k < 5:
            env.fiches.append({"membre_id": uid, "nom": f"Pirate{uid}", "metiers": metiers[k % 6],
                               "grade": grades[k % 6], "race": "humain" if k % 2 else "triton"})


def test_EV25_l_annonce_officielle_des_metiers(env):
    _equipage(env)
    m = brouillon(env, type="metiers", texte="Voici qui fait quoi à bord.")
    statut, r = api(env, "clan/apercu", requete={"id": str(m["id"])})
    assert r["publiable"] is True
    publier(env, m)
    t = textes(env.infos.messages[-1].kw["view"])
    assert "## Les métiers de l'équipage" in t and "Voici qui fait quoi à bord." in t
    assert "Charpentier — 2\n<@700> · Capitaine\n<@701> · Matelot" in t, "chaque métier, qui l'exerce, son grade"
    assert "### <:rell_charpentier_v1:123456789012345678> Charpentier — 2" in t, "l'icône officielle du métier"
    assert t.index("Charpentier — 2") < t.index("Cuisinier — 2") < t.index("Navigateur — 1"), "l'ordre du catalogue"
    assert "Sans métier" not in t and "**4 membres · members** · **3 métiers · trades**" in t
    assert "🍳" not in t, "une icône du jeu qui serait un émoji Unicode n'est jamais posée"
    assert env.infos.messages[-1].kw["allowed_mentions"].users is False, "mentions sans ping"
    env.fiches.clear()
    vide = brouillon(env, type="metiers")
    statut, r = api(env, "clan/publier", {"id": vide["id"]})
    assert statut == 400 and "métier" in r["erreur"]


def test_EV26_le_listing_par_grade_race_ou_metier(env):
    _equipage(env)
    for groupement, attendus in (("grade", ["Capitaine — 1", "Matelot — 3", "Sans grade · No rank — 2"]),
                                 ("race", ["Humain — 2", "Triton — 3", "Race non renseignée · Race not set — 1"]),
                                 ("metier", ["Charpentier — 2", "Cuisinier — 2", "Navigateur — 1",
                                             "Sans métier · No trade — 2"])):
        lst = brouillon(env, type="listing", groupement=groupement)
        statut, r = api(env, "clan/apercu", requete={"id": str(lst["id"])})
        md = "\n".join(ln["md"] for c in r["cartes"] for b in c["blocs"] if b["type"] == "texte" for ln in b["lignes"])
        positions = [md.index(x) for x in attendus]
        assert positions == sorted(positions), (groupement, md)
        assert "**6 membres · members**" in md and r["personnes"]["700"] == "Pirate700"
    jeu = [ln for c in r["cartes"] for b in c["blocs"] if b["type"] == "texte" for ln in b["lignes"] if ln["jeu"]]
    assert jeu[0]["jeu"] == {"type": "metier", "cle": "charpentier"}, "le site pose l'icône officielle du métier"


def test_EV27_un_grand_clan_se_decoupe_en_cartes_sous_les_limites(env, monkeypatch):
    monkeypatch.setattr(visuels, "_icones", {**visuels._icones, **{
        nom: discord.PartialEmoji(name=f"{nom}_v1", id=900000000000000000 + k) for k, nom in enumerate(E.ICONES)}})
    env.catalogue["metier"] = {f"m{k}": {"nom": f"Métier numéro {k}",
                                         "icone_emoji": f"<:rell_m{k}_v1:12345678901234567{k % 10}>"}
                               for k in range(30)}
    for k in range(180):
        uid = 10_000_000_000_000_000 + k
        env.g.membre(uid, env.role)
        env.fiches.append({"membre_id": uid, "metiers": [f"m{k % 30}", f"m{(k * 7) % 30}"], "grade": "matelot",
                           "race": "humain"})
    lst = brouillon(env, type="listing", groupement="metier", champs=["grade", "race", "metiers"],
                    texte="L" * 1400)
    r = publier(env, lst)
    envoyes = env.infos.messages
    assert len(envoyes) >= 3 and r["element"]["cartes"] == len(envoyes)
    for k, m in enumerate(envoyes):
        n, c = mesure_reelle(m.kw["view"])
        assert n <= 40 and c <= 4000, (k, n, c)
        assert m.kw["allowed_mentions"].users is False
        if k:
            assert f"suite · continued ({k + 1}/{len(envoyes)})" in textes(m.kw["view"])
    toutes = " ".join(textes(m.kw["view"]) for m in envoyes)
    assert all(f"<@{10_000_000_000_000_000 + k}>" in toutes for k in range(180)), "personne n'est perdu au découpage"
    assert "<:rell_m0_v1:123456789012345670>" in toutes, "l'icône officielle du métier, émoji d'application"
    #  Actualiser (modifier sans rien changer) : réécrites ; moins de membres → les cartes en trop partent.
    del env.fiches[60:]
    for uid in [m for m in list(env.g.membres) if 10_000_000_000_000_060 <= m < 10_000_000_000_000_180]:
        env.role.members.remove(env.g.membres.pop(uid))
    statut, r2 = api(env, "clan/modifier", {"id": lst["id"], "version": r["element"]["version"]})
    assert statut == 200 and 1 <= r2["element"]["cartes"] < len(envoyes)
    assert len([m for m in envoyes if m.id in env.g.effaces]) == len(envoyes) - r2["element"]["cartes"]


# ═══════════════════════════════════════════════════════════════════════════════
#  « Pas d'emojis » ; les boutons persistants ; le nettoyage ; le branchement dans le bot
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("icones", [False, True])
def test_EV28_aucun_emoji_unicode_dans_les_cartes(env, monkeypatch, icones):
    if icones:
        monkeypatch.setattr(visuels, "_icones", {**visuels._icones, **{
            nom: discord.PartialEmoji(name=f"{nom}_v1", id=900000000000000000 + k)
            for k, nom in enumerate(E.ICONES)}})
    else:   # les icônes maison pas encore installées : le repli de `visuels` (✅, 🔔…) ne doit jamais sortir
        monkeypatch.setattr(visuels, "_icones", {n: discord.PartialEmoji(name=r) for n, r in visuels.REPLI.items()})
    _equipage(env)
    e = evenement(env, places=3, texte="Texte")
    publier(env, e)
    bouton(env, e["id"], "d", env.g.get_member(700))
    for type_ in ("annonce", "metiers", "listing"):
        publier(env, brouillon(env, type=type_, titre="Titre", texte="Texte", mention="clan"))
    env.horloge["t"] = T0 + 2 * 3600 + 5
    courir(E.tic([env.g]))
    vues = [m.kw["view"] for m in env.infos.messages] + [kw["view"] for _m, kw in env.infos.cartes]
    assert len(vues) >= 6
    for v in vues:
        t = tout_texte(v)
        assert not EMOJI.search(t), t
        boutons = [getattr(b, "item", b) for b in v.walk_children()]
        emojis = [b.emoji for b in boutons if isinstance(b, discord.ui.Button) and b.emoji]
        assert all(x.id for x in emojis), "une icône de bouton est toujours un émoji d'application"
        if icones:
            assert emojis or "ev:" not in " ".join(ids(v)), "installées, les icônes maison sont sur les boutons"


def test_EV29_chaque_bouton_pose_a_son_capteur():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "bot.add_dynamic_items(evenements.BoutonReponse, evenements.BoutonVu)" in src
    for cid, classe in (("ev:r:12:d", E.BoutonReponse), ("ev:r:12:p", E.BoutonReponse),
                        ("ev:r:12:n", E.BoutonReponse), ("ev:vu:7", E.BoutonVu)):
        m = classe.__discord_ui_compiled_template__.fullmatch(cid)
        assert m is not None
        item = asyncio.run(classe.from_custom_id(None, None, m))
        assert item.item.custom_id == cid
    autres = [c for c in (E.BoutonReponse, E.BoutonVu)
              if c.__discord_ui_compiled_template__.fullmatch("an:v:3") or
              c.__discord_ui_compiled_template__.fullmatch("cd:p:3")]
    assert autres == [], "aucun gabarit ne capte les boutons d'un autre module"


def test_EV30_le_nettoyage_des_evenements_passes(env):
    e = evenement(env)
    publier(env, e)
    bouton(env, e["id"], "d", env.g.membre(81, env.role))
    a = brouillon(env, type="annonce", titre="A", texte="B")
    publier(env, a)
    garde = evenement(env, titre="Brouillon gardé")
    courir(E.annuler(env.g, env.tete, e["id"], prevenir=False))
    env.horloge["t"] = T0 + 61 * 86400
    assert courir(E.purger(60)) == 1
    assert courir(E.charger(e["id"])) is None and courir(E._reponses(e["id"]))["d"] == []
    assert courir(E.charger(a["id"])) is not None and courir(E.charger(garde["id"])) is not None, \
        "les brouillons et les annonces publiées restent (leur « Vu » répond)"
    nom, sql, jours, fmt = E.PURGES[0]
    assert sql.startswith("DELETE FROM clan_evenements WHERE archive_le > 0") and (jours, fmt) == (60, "unix")


def test_EV31_branche_dans_le_bot():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    assert re.search(r"^import evenements\b", src, re.M)
    boot = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_activite_boot")
    assert "with _Etape('evenements'):" in boot and "evenements.setup(" in boot and "await evenements.init_db()" \
        in boot
    monter = boot.split("with _Etape('evenements'):")[1].split("with _Etape(")[0]
    assert "if hasattr(tableau, 'monter'):" in monter and "tableau.monter(evenements.ROUTES_SITE)" in monter, \
        "les routes du site montées dans le registre d'API (quand il existe)"
    assert "est_tete=_a_la_tete" in boot.split("evenements.setup(")[1].split(")")[0]
    boucle = next(n for n in arbre.body if getattr(n, "name", "") == "evenements_task")
    assert ast.unparse(boucle.decorator_list[0]) == "tasks.loop(minutes=1)"
    assert "await evenements.tic(list(bot.guilds))" in ast.unparse(boucle)
    sup = next(n for n in arbre.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") ==
               "_SUPERVISED_LOOP_NAMES")
    assert "evenements_task" in ast.literal_eval(sup.value), "sans le superviseur, la boucle ne démarre jamais"
    etat = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_etat_public")
    assert "'evenements': evenements.releve()" in etat


def test_EV33_ce_que_le_site_doit_savoir_pour_son_nettoyage_et_ses_formulaires(env):
    """Les médias cités (le nettoyage des « médias inutilisés » ne doit pas vider un brouillon) ; les lieux du jeu
    tirés du catalogue (îles, zones) pour aider à remplir « lieu »."""
    evenement(env, image="img1")
    publier(env, brouillon(env, type="annonce", titre="A", texte="B", image="img1"))
    env.medias["img3"] = (WEBP, "webp")
    brouillon(env, type="annonce", image="img3")
    assert courir(E.medias_utilises()) == {"img1", "img3"}
    env.catalogue.update({"ile": {"crane": {"nom": "Île du Crâne"}}, "zone": {"abysses": {"nom": "Les Abysses"}}})
    statut, r = api(env, "clan/evenements")
    assert r["lieux"] == [{"type": "ile", "cle": "crane", "nom": "Île du Crâne"},
                          {"type": "zone", "cle": "abysses", "nom": "Les Abysses"}]


def test_EV34_republier_une_publication_incertaine_seulement_si_on_le_dit(env):
    e = evenement(env)
    courir(E._ecrire("UPDATE clan_evenements SET statut='incertain' WHERE id=?", (e["id"],)))
    statut, r = api(env, "clan/publier", {"id": e["id"]})
    assert statut == 409 and env.infos.messages == [], "incertaine : on ne republie pas sans le dire"
    statut, r = api(env, "clan/publier", {"id": e["id"], "forcer": True})
    assert statut == 200 and len(env.infos.messages) == 1, "« j'ai regardé le post, publie » : elle part"
    assert api(env, "clan/annuler", {"id": evenement(env)["id"]})[0] == 409, "un brouillon se supprime"
    env.horloge["t"] = T0 + 10 * 3600
    courir(E.tic([env.g]))
    v = courir(E.charger(e["id"]))["version"]
    assert api(env, "clan/modifier", {"id": e["id"], "version": v, "titre": "Trop tard"})[0] == 409
    assert api(env, "clan/annuler", {"id": e["id"]})[0] == 409, "un événement terminé ne s'annule plus"


def test_EV35_sans_role_du_clan_personne_n_est_exclu_par_erreur(env):
    e = evenement(env)
    publier(env, e)
    env.conf["rellseas_role"] = 0
    assert "C'est noté" in bouton(env, e["id"], "d", env.g.membre(90))[0]


def test_EV32_les_verificateurs_restent_verts():
    for outil, cibles in (("verif_boutons_persistants.py", ["bot.py", "evenements.py"]), ("verif_boucles.py", ["bot.py"])):
        r = subprocess.run([sys.executable, str(RACINE / "outils" / outil), *cibles], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(RACINE))
        assert r.returncode == 0, r.stdout + r.stderr
