"""22/10/2026 : « un salon ultra bien optimisé ou une catégorie qui regroupe plusieurs sous-salons…
aide, trading de fruits, farm, boss, chill, une zone discussion… ultra compact… un vrai salon tout en
haut de redirection… des joueurs qualifiés avec des rôles, plusieurs sous-rôles en fonction des
zones… ils pourront certifier que l'aide a bien été faite et clôturer la demande… un nettoyage
automatique ». Le parcours entier, sur un faux serveur : forum (communautaire) et salons texte."""
from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from pathlib import Path

import discord
import pytest

import entraide as E
from conftest_discord import Obj, Reponse, base, laisser_finir

RACINE = Path(__file__).resolve().parent.parent
Z = E.ZONES


# ─── Un faux serveur ─────────────────────────────────────────────────────────

class Partiel:
    def __init__(self, porteur, mid):
        self.porteur, self.id = porteur, mid

    async def edit(self, **kw):
        if self.id in self.porteur.monde.effaces:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        self.porteur.cartes.append((self.id, kw))

    async def delete(self):
        self.porteur.monde.effaces.add(self.id)


class Fil:
    def __init__(self, monde, tid, parent, name):
        self.monde, self.id, self.parent, self.name = monde, tid, parent, name
        self.envois, self.edits, self.membres, self.cartes = [], [], [], []
        self.archived = self.locked = False
        self.flags = Obj(pinned=False)
        self.last_message_id = None
        self.jump_url = f"https://discord.com/channels/1/{tid}"
        self.applied_tags = []

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))

    async def edit(self, **kw):
        self.edits.append(kw)
        for k in ("archived", "locked"):
            if k in kw:
                setattr(self, k, kw[k])
        if "pinned" in kw:
            self.flags.pinned = kw["pinned"]
        if "applied_tags" in kw:
            self.applied_tags = [t.name for t in kw["applied_tags"]]

    async def add_user(self, m):
        self.membres.append(m.id)

    async def delete(self):
        self.monde.fils.pop(self.id, None)
        self.monde.effaces.add(self.id)

    def get_partial_message(self, mid):
        return Partiel(self, mid)


class Forum(discord.ForumChannel):
    def __init__(self, monde, cid, name, kw):
        self.monde, self.id, self.name, self.kw = monde, cid, name, kw
        self._tags_ = list(kw.get("available_tags") or [])
        self.cartes, self.crees = [], []

    available_tags = property(lambda self: self._tags_)
    jump_url = property(lambda self: f"https://discord.com/channels/1/{self.id}")
    mention = property(lambda self: f"<#{self.id}>")

    async def create_thread(self, *, name, view=None, allowed_mentions=None, applied_tags=(), reason=None):
        fil = self.monde.nouveau_fil(self, name)
        fil.applied_tags = [t.name for t in applied_tags or []]
        self.crees.append(Obj(fil=fil, view=view, allowed_mentions=allowed_mentions))
        return Obj(thread=fil, message=Obj(id=fil.id))


class Message:
    def __init__(self, salon, mid):
        self.salon, self.id = salon, mid

    async def create_thread(self, *, name, auto_archive_duration=None, reason=None):
        return self.salon.monde.nouveau_fil(self.salon, name, self.id)


class Texte(discord.TextChannel):
    def __init__(self, monde, cid, name, kw):
        self.monde, self.id, self.name, self.kw = monde, cid, name, kw
        self.envois, self.cartes = [], []

    jump_url = property(lambda self: f"https://discord.com/channels/1/{self.id}")
    mention = property(lambda self: f"<#{self.id}>")

    async def send(self, content=None, **kw):
        mid = self.monde.nouvel_id()
        self.envois.append((mid, content, kw))
        return Message(self, mid)

    def get_partial_message(self, mid):
        return Partiel(self, mid)

    async def fetch_message(self, mid):
        if mid in self.monde.effaces or not any(e[0] == mid for e in self.envois):
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return Message(self, mid)


class Categorie(discord.CategoryChannel):
    def __init__(self, cid, name):
        self.id, self.name = cid, name


class Role:
    def __init__(self, rid, name, kw=None):
        self.id, self.name, self.kw = rid, name, kw or {}
        self.mention, self.mentionable, self.managed, self.members = f"<@&{rid}>", False, False, []

    def is_default(self):
        return False


class Membre:
    def __init__(self, uid, *roles):
        self.id, self.mention, self.display_name = uid, f"<@{uid}>", f"Pirate{uid}"
        self.display_avatar = Obj(url=f"https://cdn.discordapp.com/avatars/{uid}.png")
        self.roles, self.guild_permissions, self.bot = list(roles), Obj(administrator=False), False
        for r in roles:
            r.members.append(self)

    def is_timed_out(self):
        return False


class Monde:
    def __init__(self, forum=True):
        self.id, self.features = 1, ["COMMUNITY"] if forum else []
        self.salons, self.fils, self.roles, self.membres, self.effaces = {}, {}, {}, {}, set()
        self.default_role = Obj(id=1)
        self.me = Obj(id=999, guild_permissions=Obj(manage_channels=True, manage_roles=True, mention_everyone=True))
        self._n = 1000

    def nouvel_id(self):
        self._n += 1
        return self._n

    def nouveau_fil(self, parent, name, tid=None):
        fil = Fil(self, tid or self.nouvel_id(), parent, name)
        self.fils[fil.id] = fil
        return fil

    def membre(self, uid, *roles):
        m = Membre(uid, *roles)
        m.guild = self
        self.membres[uid] = m
        return m

    text_channels = property(lambda self: [s for s in self.salons.values() if isinstance(s, Texte)])

    def get_channel(self, cid):
        return self.salons.get(int(cid or 0))

    def get_channel_or_thread(self, cid):
        return self.salons.get(int(cid or 0)) or self.fils.get(int(cid or 0))

    async def fetch_channel(self, cid):
        x = self.get_channel_or_thread(cid)
        if x is None:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return x

    def get_member(self, uid):
        return self.membres.get(int(uid))

    def get_role(self, rid):
        return self.roles.get(int(rid or 0))

    async def create_category(self, name, **kw):
        c = Categorie(self.nouvel_id(), name)
        self.salons[c.id] = c
        return c

    async def create_role(self, *, name, **kw):
        r = Role(self.nouvel_id(), name, kw)
        self.roles[r.id] = r
        return r

    async def create_text_channel(self, name, **kw):
        s = Texte(self, self.nouvel_id(), name, kw)
        self.salons[s.id] = s
        return s

    async def create_forum(self, name, **kw):
        s = Forum(self, self.nouvel_id(), name, kw)
        self.salons[s.id] = s
        return s


def interaction(g, membre):
    suivis, reponse = [], Reponse()

    async def suivi(content=None, **kw):
        suivis.append((content, kw))

    async def editer(**kw):
        suivis.append(("edit", kw))
    return Obj(guild=g, user=membre, response=reponse, followup=Obj(send=suivi), suivis=suivis,
               edit_original_response=editer)


def run(coro):
    async def _avec_taches():
        r = await coro
        await laisser_finir()
        return r
    return asyncio.run(_avec_taches())


def textes(vue) -> str:
    def tout(c):
        if isinstance(c, dict):
            for k in ("content", "label", "placeholder"):
                if c.get(k):
                    yield str(c[k])
            for x in c.get("components", []) or []:
                yield from tout(x)
            if c.get("accessory"):
                yield from tout(c["accessory"])
    return " ".join(t for comp in vue.to_components() for t in tout(comp))


def ids(vue) -> list:
    out = []

    def tout(c):
        if isinstance(c, dict):
            if c.get("custom_id"):
                out.append(c["custom_id"])
            for x in c.get("components", []) or []:
                tout(x)
    for comp in vue.to_components():
        tout(comp)
    return out


@pytest.fixture
def env(tmp_path):
    get_db, cfg, db_set, conf = base(tmp_path)
    journal, staff = [], set()

    async def texte_refuse(_g, t):
        return "Ta demande contient une insulte." if "insulte" in t else ""

    async def controle(_m, _c):
        return ""

    async def est_staff(_g, m):
        return m.id in staff

    async def noter(_g, type_, texte, **kw):
        journal.append((type_, texte, kw))
    E._verrous.clear()
    E._creations.clear()
    E._verifies.clear()
    E.setup(get_db=get_db, cfg=cfg, db_set=db_set, texte_refuse=texte_refuse, controle=controle,
            est_staff=est_staff, journal=noter, salon_ticket=lambda g: None, log=lambda *a: None)
    asyncio.run(E.init_db())
    return Obj(conf=conf, journal=journal, staff=staff, get_db=get_db)


def installe(env, forum=True):
    g = Monde(forum)
    faits = run(E.installer(g))
    return g, faits


def demande_valeurs(zone):
    return {"aide": {"titre": "Bloqué à l'île du crâne", "details": "Je ne trouve pas la clé", "pseudo": "Kolax_RS",
                     "niveau": "850"},
            "boss": {"titre": "Akuma", "pseudo": "Kolax_RS", "niveau": "1200", "joueurs": "2", "details": ""},
            "farm": {"titre": "Niveaux", "pseudo": "Kolax_RS", "niveau": "300", "duree": "1 h", "details": ""},
            "trade": {"donne": "Fruit Dragon", "cherche": "Fruit Dough", "pseudo": "Kolax_RS", "details": ""},
            "chill": {"titre": "Naviguer", "pseudo": "Kolax_RS", "quand": "ce soir", "details": ""}}[zone]


def publier(g, membre, zone, valeurs=None):
    i = interaction(g, membre)
    run(E.publier(i, Z[zone], valeurs or demande_valeurs(zone)))
    return i


def ligne(env, did):
    return run(E.charger(did))


# ─── Les zones ───────────────────────────────────────────────────────────────

def test_E1_cinq_zones_des_formulaires_valides_et_des_boutons_qui_se_retrouvent():
    assert list(Z) == ["aide", "boss", "farm", "trade", "chill"]
    for z in Z.values():
        assert 1 <= len(z.champs) <= 5 and len(f"{z.emoji} {z.nom} · nouvelle demande") <= 45
        assert all(len(c.libelle) <= 45 and len(c.aide) <= 100 for c in z.champs)
        assert any(c.cle == "pseudo" for c in z.champs), "le pseudo Roblox, pour se retrouver en jeu"
        assert E.titre_de(z, {c.cle: "x" for c in z.champs})
        assert len(E.Formulaire(z).children) == len(z.champs)
        assert bool(z.role) == bool(z.certif), "une zone certifiée a son rôle de guide"
    assert Z["trade"].certif == "middleman" and Z["chill"].certif == ""
    for item, gabarit in ((E.BoutonNouvelle("boss"), r"rs:n:(?P<zone>[a-z]+)"),
                          (E.BoutonRejoindre(5), r"rs:j:(?P<did>\d+)"), (E.BoutonCertifier(5), r"rs:c:(?P<did>\d+)"),
                          (E.BoutonFermer(5), r"rs:f:(?P<did>\d+)"), (E.BoutonMiddleman(5), r"rs:m:(?P<did>\d+)")):
        assert re.fullmatch(gabarit, item.item.custom_id)


def _d(zone="aide", statut="ouverte", **kw):
    d = {"id": 5, "guild_id": 1, "zone": zone, "auteur_id": 7, "titre": "t", "statut": statut, "salon_id": 0,
         "fil_id": 0, "aidants": [], "cree": 1_800_000_000, "maj": 1_800_000_000, "ferme": 0, "ferme_par": 0,
         "certifie_par": 0, "credites": [], "partenaire_id": 0, "appel_mm": 0, "supprime": 0,
         "champs": [["Ton problème", "<@123456789012345678> **piège** @everyone"]]}
    d.update(kw)
    return d


def test_E2_la_carte_montre_ce_qu_il_faut_et_seulement_les_boutons_utiles():
    assert ids(E.vue_carte(_d("aide"), Z["aide"])) == ["rs:j:5", "rs:c:5", "rs:f:5"]
    assert ids(E.vue_carte(_d("trade"), Z["trade"], rep=3)) == ["rs:j:5", "rs:m:5", "rs:c:5", "rs:f:5"]
    assert ids(E.vue_carte(_d("chill"), Z["chill"])) == ["rs:j:5", "rs:f:5"], "le chill ne se certifie pas"
    t = textes(E.vue_carte(_d("aide"), Z["aide"], ping="<@&9>"))
    assert "<@123456789012345678>" not in t and "@everyone" not in t, "le texte d'un membre ne mentionne personne"
    assert "Guides prévenus : <@&9>" in t and "personne pour l'instant" in t
    t = textes(E.vue_carte(_d("trade"), Z["trade"], rep=3))
    assert "3 échange(s) certifié(s)" in t and "middleman" in t
    close = E.vue_carte(_d("aide", "terminee", ferme=1_800_000_100, certifie_par=10, credites=[8]), Z["aide"])
    assert ids(close) == [], "une demande close n'a plus de bouton"
    t = textes(close)
    assert "Aide certifiée" in t and "<@10>" in t and "Ont aidé : <@8>" in t
    assert f"<t:{1_800_000_100 + E.GARDER_H * 3600}:R>" in t, "on annonce quand le fil disparaît"


# ─── Installation ────────────────────────────────────────────────────────────

def test_E3_l_installation_cree_tout_une_fois_sans_jamais_rien_supprimer(env):
    g, faits = installe(env, forum=True)
    noms = [s.name for s in g.salons.values()]
    assert noms[0] == E.CATEGORIE and E.ORIENTATION in noms and E.DISCUSSION in noms
    zones = {k: g.get_channel(v) for k, v in env.conf["rs_salons"].items()}
    assert all(isinstance(zones[z], Forum) for z in Z), "serveur communautaire : des forums"
    assert len(faits) == 1 + 4 + 7, faits
    assert sorted(r.name for r in g.roles.values()) == sorted(z.role for z in Z.values() if z.role)
    droits = zones["boss"].kw["overwrites"][g.default_role]
    assert (droits.send_messages, droits.send_messages_in_threads, droits.create_public_threads) == (False, True, False)
    assert droits.view_channel is None, "la visibilité reste celle du serveur"
    assert [t.name for t in zones["boss"].available_tags] == ["Ouverte", "En cours", "Terminée", "Fermée"]
    orient = zones["orientation"]
    assert orient.kw["overwrites"][g.default_role].send_messages is False and len(orient.envois) == 1
    assert zones["discussion"].kw.get("slowmode_delay") == 2
    for z in Z:
        panneau = g.fils[env.conf["rs_panneaux"][z]]
        assert panneau.flags.pinned and panneau.locked, "le post « Publier une demande » est épinglé, en tête"
        assert f"rs:n:{z}" in ids(zones[z].crees[0].view)
    t = textes(orient.envois[0][2]["view"])
    assert all(z.nom in t for z in Z.values()) and "Discussion" in t and t.count("Y aller") == 6
    assert run(E.installer(g)) == [], "relancer ne crée rien de plus"
    del g.salons[env.conf["rs_salons"]["farm"]]
    assert run(E.installer(g)) == ["salon 🌾・farm"], "un salon effacé à la main revient"


# ─── Publier, rejoindre, certifier ───────────────────────────────────────────

def test_E4_publier_une_demande_de_boss_previent_les_guides_et_l_auteur_suit_son_fil(env):
    g, _ = installe(env)
    kolax = g.membre(7)
    i = publier(g, kolax, "boss")
    assert i.suivis[0][0].startswith("Demande publiée : https://discord.com/channels/1/")
    forum = g.get_channel(env.conf["rs_salons"]["boss"])
    post = forum.crees[-1]
    assert post.fil.name == "Boss Akuma · Pirate7" and post.fil.applied_tags == ["Ouverte"]
    guide = g.get_role(env.conf["rs_roles"]["boss"])
    assert post.allowed_mentions.roles == [guide] and "Guides prévenus" in textes(post.view)
    assert post.fil.membres == [7], "l'auteur suit son fil"
    d = run(E.charger(1))
    assert (d["zone"], d["statut"], d["fil_id"]) == ("boss", "ouverte", post.fil.id)
    assert env.journal[-1][0] == "entraide.demande" and env.journal[-1][2]["membre_id"] == 7
    E._creations.clear()
    i2 = publier(g, kolax, "boss")
    assert "déjà une demande ouverte ici" in str(i2.response.messages) + str(i2.suivis), \
        "une demande à la fois par zone"
    assert len(forum.crees) == 2, "le post épinglé et une seule demande"
    i3 = publier(g, g.membre(8), "boss", {"titre": "Une insulte", "pseudo": "x", "niveau": "", "joueurs": "",
                                          "details": ""})
    assert "insulte" in str(i3.response.messages[0][1]["view"].to_components()), "le texte est filtré, on peut corriger"


def test_E5_rejoindre_puis_certifier_par_un_guide_de_la_zone(env):
    g, _ = installe(env)
    kolax, ami, curieux = g.membre(7), g.membre(8), g.membre(9)
    guide = g.membre(10, g.get_role(env.conf["rs_roles"]["boss"]))
    publier(g, kolax, "boss")
    fil = g.get_channel(env.conf["rs_salons"]["boss"]).crees[-1].fil
    i = interaction(g, kolax)
    run(E.rejoindre(i, 1))
    assert "C'est ta demande" in i.suivis[0][0]
    run(E.rejoindre(interaction(g, ami), 1))
    d = run(E.charger(1))
    assert (d["statut"], d["aidants"]) == ("prise", [8]) and fil.applied_tags == ["En cours"]
    assert fil.envois[-1][0] == "🙋 <@8> vient t'aider, <@7> !" and 8 in fil.membres
    i = interaction(g, ami)
    run(E.rejoindre(i, 1))
    assert "déjà dessus" in i.suivis[0][0]
    assert "Réservé aux guides de la zone Boss" in run(E.peut_certifier(g, curieux, d))
    assert run(E.peut_certifier(g, guide, d)) == ""
    vue = E.VueCertifier(d, Z["boss"], guide)
    run(vue._cb_ok(interaction(g, guide)))  # la liste pré-cochée (les aidants) est gardée telle quelle
    d = run(E.charger(1))
    assert (d["statut"], d["certifie_par"], d["credites"]) == ("terminee", 10, [8])
    assert fil.locked and fil.archived and fil.applied_tags == ["Terminée"]
    assert fil.envois[-1][0] == "✅ Aide certifiée par <@10> — merci à <@8> !"
    assert ids(fil.cartes[-1][1]["view"]) == [], "la carte close n'a plus de bouton"
    assert env.journal[-1][0] == "entraide.certifiee" and env.journal[-1][2] == {"membre_id": 7, "auteur_id": 10}
    assert run(E.certifier(g, 1, guide, [])) == "Cette demande est déjà close."


def test_E6_un_echange_certifie_par_un_middleman_compte_pour_les_deux(env):
    g, _ = installe(env)
    vendeur, acheteur, curieux = g.membre(7), g.membre(8), g.membre(9)
    mm = g.membre(11, g.get_role(env.conf["rs_roles"]["trade"]))
    publier(g, vendeur, "trade")
    fil = g.get_channel(env.conf["rs_salons"]["trade"]).crees[-1].fil
    assert fil.name == "Fruit Dragon ⇄ Fruit Dough · Pirate7"
    run(E.rejoindre(interaction(g, acheteur), 1))
    assert fil.envois[-1][0] == "💬 <@8> est intéressé par ton échange, <@7> !"
    i = interaction(g, curieux)
    run(E.appeler_middleman(i, 1))
    assert "Seuls l'auteur et les intéressés" in i.suivis[0][0]
    run(E.appeler_middleman(interaction(g, vendeur), 1))
    role = g.get_role(env.conf["rs_roles"]["trade"])
    assert fil.envois[-1][0].startswith(f"🛡️ {role.mention}") and fil.envois[-1][1]["allowed_mentions"].roles == [role]
    i = interaction(g, acheteur)
    run(E.appeler_middleman(i, 1))
    assert "déjà été appelé" in i.suivis[0][0], "un appel par quart d'heure"
    assert run(E.certifier(g, 1, mm, [], partenaire=8)) == ""
    assert run(E.reputation(1, 7)) == 1 and run(E.reputation(1, 8)) == 1 and run(E.reputation(1, 9)) == 0
    assert fil.envois[-1][0] == "✅ Échange certifié par <@11> — avec <@8>."


def test_E7_fermer_l_auteur_sans_bruit_le_staff_au_journal(env):
    g, _ = installe(env)
    a, b = g.membre(7), g.membre(8)
    env.staff.add(12)
    g.membre(12)
    publier(g, a, "aide")
    E._creations.clear()
    publier(g, b, "chill")
    n = len(env.journal)
    assert run(E.fermer(g, 1, 7, "fermee", "🔒 Demande fermée par son auteur."))
    assert len(env.journal) == n, "fermer sa propre demande ne remplit pas le journal"
    assert run(E.fermer(g, 2, 12, "fermee", "🔒 Demande fermée par <@12>."))
    assert env.journal[-1][0] == "entraide.fermee"
    assert not run(E.fermer(g, 2, 12)), "déjà close"


# ─── Nettoyage ───────────────────────────────────────────────────────────────

def test_E8_le_nettoyage_ferme_l_inactif_efface_le_clos_et_rattrape_l_oublie(env):
    g, _ = installe(env)
    for uid, zone in ((7, "boss"), (8, "aide"), (9, "farm")):
        E._creations.clear()
        publier(g, g.membre(uid), zone)
    t0 = time.time()
    fil_farm = g.fils[run(E.charger(3))["fil_id"]]
    run(fil_farm.delete())  # supprimé à la main par le staff
    run(E._ecrire("INSERT INTO entraide_demandes(guild_id, zone, auteur_id, titre, cree, maj) VALUES(1,'aide',5,'x',?,?)",
                  (int(t0) - 3600, int(t0) - 3600)))
    bilan = run(E.entretenir(g, maintenant=t0 + 7 * 3600))  # boss : 6 h ; aide : 24 h
    assert bilan == {"expirees": 1, "retirees": 1, "effacees": 0}
    assert [run(E.charger(n))["statut"] for n in (1, 2, 3)] == ["expiree", "ouverte", "retiree"]
    assert run(E.charger(4)) is None, "une publication interrompue ne bloque personne"
    fil_boss = g.fils[run(E.charger(1))["fil_id"]]
    assert fil_boss.locked and "Fermée faute d'activité depuis 6 h" in fil_boss.envois[-1][0]
    assert fil_boss.applied_tags == ["Fermée"]
    bilan = run(E.entretenir(g, maintenant=t0 + 7 * 3600 + E.GARDER_H * 3600 + 60))
    assert bilan == {"expirees": 1, "retirees": 0, "effacees": 1}, bilan
    assert fil_boss.id not in g.fils, "le fil clos disparaît après le délai"
    assert run(E.charger(1))["supprime"] == 1 and run(E.charger(2))["statut"] == "expiree", "la base garde la trace"


def test_E9_un_membre_qui_part_ferme_ses_demandes(env):
    g, _ = installe(env)
    m = g.membre(7)
    publier(g, m, "aide")
    assert run(E.sur_depart(m)) == 1 and run(E.charger(1))["statut"] == "fermee"


def test_E10_sans_communaute_des_salons_texte_et_des_fils_le_panneau_reste_en_bas(env):
    g, _ = installe(env, forum=False)
    salon = g.get_channel(env.conf["rs_salons"]["aide"])
    assert isinstance(salon, Texte) and len(salon.envois) == 1
    ancien = env.conf["rs_panneaux"]["aide"]
    publier(g, g.membre(7), "aide")
    d = run(E.charger(1))
    carte = next(e for e in salon.envois if e[0] == d["fil_id"])
    assert "rs:j:1" in ids(carte[2]["view"]) and g.fils[d["fil_id"]].parent is salon
    assert ancien in g.effaces and env.conf["rs_panneaux"]["aide"] != ancien, "le panneau est reposé sous la carte"
    run(E.fermer(g, 1, 7, "fermee"))
    assert salon.cartes[-1][0] == d["fil_id"], "hors forum, la carte se met à jour dans le salon"
    run(E.entretenir(g, maintenant=time.time() + E.GARDER_H * 3600 + 60))
    assert d["fil_id"] in g.effaces, "le fil et sa carte disparaissent"


def test_E11_orientation_une_ligne_par_salon_qui_existe_et_les_compteurs(env):
    g, _ = installe(env)
    publier(g, g.membre(7), "boss")
    run(E.entretenir(g))
    orient = g.get_channel(env.conf["rs_salons"]["orientation"])
    t = textes(orient.cartes[-1][1]["view"])
    assert "1 demande(s) en cours" in t and "aucune demande en cours" in t
    del g.salons[env.conf["rs_salons"]["chill"]]
    vue, _sig = E.vue_orientation(g, run(E.conf(g)))
    assert "Chill" not in textes(vue), "aucun bouton qui mène nulle part"


# ─── Branchement dans le bot ─────────────────────────────────────────────────

def test_E12_branche_dans_le_bot():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    for nom in ("BoutonNouvelle", "BoutonRejoindre", "BoutonCertifier", "BoutonFermer", "BoutonMiddleman"):
        assert f"entraide.{nom}" in src, f"{nom} doit être réenregistré au démarrage"
    arbre = ast.parse(src)
    sup = next(n for n in arbre.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_SUPERVISED_LOOP_NAMES")
    assert "entraide_task" in ast.literal_eval(sup.value)
    assert "'entraide':    lambda: entraide.EntraidePanelV2(self.u, self.g)" in src
    assert "await entraide.sur_depart(m)" in src and "ids_prives |= entraide.ids_salons(c)" in src
    assert 'await _texte_refuse_pour(g, texte, "une demande", "Ta demande")' in src
    assert "entraide.salon(g, cf_entraide, \"orientation\")" in src, "le panneau d'aide mène à l'entraide"
    boucle = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "entraide_task")
    assert "g.owner_id in TETE_IDS and (not c.get('rs_installation_auto'))" in boucle, \
        "installée d'elle-même, une fois, sur le serveur du fondateur seulement"
    assert boucle.index("db_set(g.id, 'rs_installation_auto'") < boucle.index("entraide.installer(g)"), \
        "le drapeau d'abord : un échec ne relance pas l'installation en boucle"
    assert (RACINE / "visuels" / "rs_port.gif").is_file() and all(
        (RACINE / "visuels" / f"rs_{z}.gif").is_file() for z in Z)
    assert '"Entraide": "#84cc16"' in (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert json.dumps(sorted(E.ids_salons({"rs_salons": {"a": 5, "b": "6"}, "rs_categorie": 4}))) == "[4, 5, 6]"
