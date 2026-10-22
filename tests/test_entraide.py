"""22/10/2026 : « un salon ultra bien optimisé… aide, trading de fruits, farm, boss, chill… ultra
compact… un vrai salon tout en haut de redirection… des joueurs qualifiés avec des rôles, plusieurs
sous-rôles en fonction des zones… ils pourront certifier que l'aide a bien été faite et clôturer la
demande… un nettoyage automatique ». Puis, le soir : « ça me fait trop de salons… tout mettre dans
Communautaire… que ça ne se chevauche pas… rangé par ordre de priorité ». Le parcours entier, sur un
faux serveur : forums (communautaire) et salons texte, et le regroupement de la première installation."""
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
        for k in ("archived", "locked", "name"):
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


class Rangeable:
    """Ce que les faux salons partagent : catégorie, position, rangement, édition, suppression."""
    def _init(self, monde, cid, name, kw):
        self.monde, self.id, self.name, self.kw = monde, cid, name, kw
        cat = kw.get("category")
        self.category_id = getattr(cat, "id", None)
        self.edits, self.supprime = [], False

    position = property(lambda self: self.monde.ordre.index(self.id))
    jump_url = property(lambda self: f"https://discord.com/channels/1/{self.id}")
    mention = property(lambda self: f"<#{self.id}>")

    async def edit(self, **kw):
        self.edits.append(kw)
        if "name" in kw:
            self.name = kw["name"]
        if "category" in kw:
            self.category_id = getattr(kw["category"], "id", None)
        if "available_tags" in kw:
            self._tags_ = list(kw["available_tags"])

    async def delete(self, **kw):
        self.supprime = True
        self.monde.salons.pop(self.id, None)
        self.monde.ordre.remove(self.id)

    async def move(self, **kw):
        self.monde.mouvements.append((self.name, kw))
        self.category_id = getattr(kw.get("category"), "id", self.category_id)
        self.monde.ordre.remove(self.id)
        if kw.get("beginning"):
            premiers = [i for i, x in enumerate(self.monde.ordre) if getattr(self.monde.salons.get(x), "category_id", 0)
                        == self.category_id]
            self.monde.ordre.insert(premiers[0] if premiers else len(self.monde.ordre), self.id)
        else:
            self.monde.ordre.insert(self.monde.ordre.index(kw["after"].id) + 1, self.id)


class Forum(Rangeable, discord.ForumChannel):
    def __init__(self, monde, cid, name, kw):
        self._init(monde, cid, name, kw)
        self._tags_ = list(kw.get("available_tags") or [])
        self.cartes, self.crees = [], []

    available_tags = property(lambda self: self._tags_)

    async def create_thread(self, *, name, view=None, allowed_mentions=None, applied_tags=(), reason=None):
        fil = self.monde.nouveau_fil(self, name)
        fil.applied_tags = [t.name for t in applied_tags or []]
        self.crees.append(Obj(fil=fil, view=view, allowed_mentions=allowed_mentions))
        return Obj(thread=fil, message=Obj(id=fil.id))


class Message:
    def __init__(self, salon, mid, auteur_bot=True):
        self.salon, self.id, self.author = salon, mid, Obj(bot=auteur_bot)

    async def create_thread(self, *, name, auto_archive_duration=None, reason=None):
        return self.salon.monde.nouveau_fil(self.salon, name, self.id)


class Texte(Rangeable, discord.TextChannel):
    def __init__(self, monde, cid, name, kw):
        self._init(monde, cid, name, kw)
        self.envois, self.cartes, self.historique = [], [], []

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

    def history(self, limit=None):
        async def gen():
            for m in self.historique[:limit]:
                yield m
        return gen()


class Vocal(Rangeable, discord.VoiceChannel):
    def __init__(self, monde, cid, name, kw):
        self._init(monde, cid, name, kw)


class Categorie(discord.CategoryChannel):
    def __init__(self, monde, cid, name):
        self.monde, self.id, self.name, self.supprime = monde, cid, name, False

    channels = property(lambda self: sorted((s for s in self.monde.salons.values()
                                             if getattr(s, "category_id", None) == self.id),
                                            key=lambda s: s.position))

    async def delete(self, **kw):
        self.supprime = True
        self.monde.categories_.remove(self)


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
    def __init__(self, forum=True, communautaire=True):
        self.id, self.features = 1, ["COMMUNITY"] if forum else []
        self.salons, self.fils, self.roles, self.membres, self.effaces = {}, {}, {}, {}, set()
        self.ordre, self.categories_, self.mouvements = [], [], []
        self.default_role = Obj(id=1)
        self.me = Obj(id=999, guild_permissions=Obj(manage_channels=True, manage_roles=True, mention_everyone=True))
        self._n = 1000
        self.commu = None
        if communautaire:
            self.commu = self.categorie("・Communautaire")
            for classe, nom in ((Texte, "💬chat"), (Texte, "💡suggestions"), (Texte, "🚀boosts"),
                                (Texte, "❓aide"), (Vocal, "🔊Join")):
                self._salon(classe, nom, {"category": self.commu})

    def nouvel_id(self):
        self._n += 1
        return self._n

    def categorie(self, nom):
        c = Categorie(self, self.nouvel_id(), nom)
        self.categories_.append(c)
        return c

    def _salon(self, classe, nom, kw):
        s = classe(self, self.nouvel_id(), nom, kw)
        self.salons[s.id] = s
        self.ordre.append(s.id)
        return s

    def nom(self, nom):
        return next(s for s in self.salons.values() if s.name == nom)

    def nouveau_fil(self, parent, name, tid=None):
        fil = Fil(self, tid or self.nouvel_id(), parent, name)
        self.fils[fil.id] = fil
        return fil

    def membre(self, uid, *roles):
        m = Membre(uid, *roles)
        m.guild = self
        self.membres[uid] = m
        return m

    categories = property(lambda self: list(self.categories_))
    text_channels = property(lambda self: [s for s in self.salons.values() if isinstance(s, Texte)])

    def get_channel(self, cid):
        cid = int(cid or 0)
        return self.salons.get(cid) or next((c for c in self.categories_ if c.id == cid), None)

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
        return self.categorie(name)

    async def create_role(self, *, name, **kw):
        r = Role(self.nouvel_id(), name, kw)
        self.roles[r.id] = r
        return r

    async def create_text_channel(self, name, **kw):
        return self._salon(Texte, name, kw)

    async def create_forum(self, name, **kw):
        return self._salon(Forum, name, kw)


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
    env.conf.update(aide_salon=g.nom("❓aide").id, suggestions_salon=g.nom("💡suggestions").id,
                    boosts_salon=g.nom("🚀boosts").id)
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


def forum_de(g, env, cle):
    return g.get_channel(env.conf["rs_salons"][cle])


# ─── Les types ───────────────────────────────────────────────────────────────

def test_E1_cinq_types_deux_forums_des_formulaires_valides():
    assert list(Z) == ["aide", "boss", "farm", "chill", "trade"]
    assert [z.cle for z in E.types_du_salon("entraide")] == ["aide", "boss", "farm", "chill"]
    assert [z.cle for z in E.types_du_salon("trade")] == ["trade"] and list(E.SALONS) == ["entraide", "trade"]
    for z in Z.values():
        assert 1 <= len(z.champs) <= 5 and len(f"{z.emoji} {z.nom} · nouvelle demande") <= 45
        assert all(len(c.libelle) <= 45 and len(c.aide) <= 100 for c in z.champs)
        assert any(c.cle == "pseudo" for c in z.champs), "le pseudo Roblox, pour se retrouver en jeu"
        assert E.titre_de(z, {c.cle: "x" for c in z.champs}) and z.bouton
        assert len(E.Formulaire(z).children) == len(z.champs)
        assert bool(z.role) == bool(z.certif), "un type certifié a son rôle de guide"
    assert [t.name for t in E.tags_du_salon("entraide")] == ["Aide", "Boss", "Farm", "Chill", "Ouverte", "En cours",
                                                             "Terminée", "Fermée"]
    assert [t.name for t in E.tags_du_salon("trade")] == ["Ouverte", "En cours", "Terminée", "Fermée"]
    for item, gabarit in ((E.BoutonNouvelle("boss"), r"rs:n:(?P<zone>[a-z]+)"),
                          (E.BoutonRejoindre(5), r"rs:j:(?P<did>\d+)"), (E.BoutonCertifier(5), r"rs:c:(?P<did>\d+)"),
                          (E.BoutonFermer(5), r"rs:f:(?P<did>\d+)"), (E.BoutonMiddleman(5), r"rs:m:(?P<did>\d+)")):
        assert re.fullmatch(gabarit, item.item.custom_id)
    assert E.BoutonNouvelle("trade").item.label == "Proposer un échange"


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

def test_E3_deux_forums_dans_communautaire_rangee_par_priorite(env):
    g, faits = installe(env, forum=True)
    assert len(g.categories) == 1, "aucune catégorie en plus"
    entr, trade = forum_de(g, env, "entraide"), forum_de(g, env, "trade")
    assert (entr.name, trade.name) == ("🆘・entraide", "🤝・trade")
    assert entr.category_id == trade.category_id == g.commu.id
    assert len(faits) == 4 + 2, faits
    assert sorted(r.name for r in g.roles.values()) == sorted(z.role for z in Z.values() if z.role)
    droits = entr.kw["overwrites"][g.default_role]
    assert (droits.send_messages, droits.send_messages_in_threads, droits.create_public_threads) == (False, True, False)
    assert droits.view_channel is None, "la visibilité reste celle du serveur"
    assert [t.name for t in entr.available_tags][:4] == ["Aide", "Boss", "Farm", "Chill"]
    post = g.fils[env.conf["rs_panneaux"]["entraide"]]
    assert post.name == "📌 Publier une demande" and post.flags.pinned and post.locked
    assert ids(entr.crees[0].view) == ["rs:n:aide", "rs:n:boss", "rs:n:farm", "rs:n:chill"], "un bouton par type"
    assert ids(trade.crees[0].view) == ["rs:n:trade"] and g.fils[env.conf["rs_panneaux"]["trade"]].name == \
        "📌 Proposer un échange"
    assert [s.name for s in g.commu.channels] == ["❓aide", "💬chat", "🆘・entraide", "🤝・trade", "💡suggestions",
                                                  "🚀boosts", "🔊Join"], "par ordre de priorité, les vocaux en bas"
    n = len(g.mouvements)
    assert run(E.installer(g)) == [] and len(g.mouvements) == n, "relancer ne crée ni ne déplace rien"
    del g.salons[env.conf["rs_salons"]["trade"]]
    g.ordre.remove(env.conf["rs_salons"]["trade"])
    assert run(E.installer(g)) == ["salon 🤝・trade"], "un forum effacé à la main revient, à sa place"
    assert [s.name for s in g.commu.channels][3] == "🤝・trade"


# ─── Publier, rejoindre, certifier ───────────────────────────────────────────

def test_E4_publier_un_boss_previent_ses_guides_etiquette_type_et_statut(env):
    g, _ = installe(env)
    kolax = g.membre(7)
    i = publier(g, kolax, "boss")
    assert i.suivis[0][0].startswith("Demande publiée : https://discord.com/channels/1/")
    forum = forum_de(g, env, "entraide")
    post = forum.crees[-1]
    assert post.fil.name == "Boss Akuma · Pirate7" and post.fil.applied_tags == ["Boss", "Ouverte"]
    guide = g.get_role(env.conf["rs_roles"]["boss"])
    assert post.allowed_mentions.roles == [guide] and "Guides prévenus" in textes(post.view)
    assert post.fil.membres == [7], "l'auteur suit son fil"
    d = run(E.charger(1))
    assert (d["zone"], d["statut"], d["fil_id"]) == ("boss", "ouverte", post.fil.id)
    assert env.journal[-1][0] == "entraide.demande" and env.journal[-1][2]["membre_id"] == 7
    E._creations.clear()
    i2 = publier(g, kolax, "boss")
    assert "déjà une demande ouverte ici" in str(i2.response.messages) + str(i2.suivis), "une à la fois par type"
    E._creations.clear()
    publier(g, kolax, "farm")
    assert forum.crees[-1].fil.applied_tags == ["Farm", "Ouverte"], "un autre type, dans le même forum"
    i3 = publier(g, g.membre(8), "boss", {"titre": "Une insulte", "pseudo": "x", "niveau": "", "joueurs": "",
                                          "details": ""})
    assert "insulte" in str(i3.response.messages[0][1]["view"].to_components()), "le texte est filtré, on peut corriger"


def test_E5_rejoindre_puis_certifier_par_un_guide_du_type(env):
    g, _ = installe(env)
    kolax, ami, curieux = g.membre(7), g.membre(8), g.membre(9)
    guide = g.membre(10, g.get_role(env.conf["rs_roles"]["boss"]))
    publier(g, kolax, "boss")
    fil = forum_de(g, env, "entraide").crees[-1].fil
    i = interaction(g, kolax)
    run(E.rejoindre(i, 1))
    assert "C'est ta demande" in i.suivis[0][0]
    run(E.rejoindre(interaction(g, ami), 1))
    d = run(E.charger(1))
    assert (d["statut"], d["aidants"]) == ("prise", [8]) and fil.applied_tags == ["Boss", "En cours"]
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
    assert fil.locked and fil.archived and fil.applied_tags == ["Boss", "Terminée"]
    assert fil.envois[-1][0] == "✅ Aide certifiée par <@10> — merci à <@8> !"
    assert ids(fil.cartes[-1][1]["view"]) == [], "la carte close n'a plus de bouton"
    assert env.journal[-1][0] == "entraide.certifiee" and env.journal[-1][2] == {"membre_id": 7, "auteur_id": 10}
    assert run(E.certifier(g, 1, guide, [])) == "Cette demande est déjà close."


def test_E6_un_echange_certifie_par_un_middleman_compte_pour_les_deux(env):
    g, _ = installe(env)
    vendeur, acheteur, curieux = g.membre(7), g.membre(8), g.membre(9)
    mm = g.membre(11, g.get_role(env.conf["rs_roles"]["trade"]))
    publier(g, vendeur, "trade")
    fil = forum_de(g, env, "trade").crees[-1].fil
    assert fil.name == "Fruit Dragon ⇄ Fruit Dough · Pirate7" and fil.applied_tags == ["Ouverte"]
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
    assert fil_boss.applied_tags == ["Boss", "Fermée"]
    bilan = run(E.entretenir(g, maintenant=t0 + 7 * 3600 + E.GARDER_H * 3600 + 60))
    assert bilan == {"expirees": 1, "retirees": 0, "effacees": 1}, bilan
    assert fil_boss.id not in g.fils, "le fil clos disparaît après le délai"
    assert run(E.charger(1))["supprime"] == 1 and run(E.charger(2))["statut"] == "expiree", "la base garde la trace"


def test_E9_un_membre_qui_part_ferme_ses_demandes(env):
    g, _ = installe(env)
    m = g.membre(7)
    publier(g, m, "aide")
    assert run(E.sur_depart(m)) == 1 and run(E.charger(1))["statut"] == "fermee"


def test_E10_sans_communaute_des_salons_et_des_fils_le_panneau_reste_en_bas(env):
    g, _ = installe(env, forum=False)
    salon = forum_de(g, env, "entraide")
    assert isinstance(salon, Texte) and len(salon.envois) == 1
    assert ids(salon.envois[0][2]["view"]) == ["rs:n:aide", "rs:n:boss", "rs:n:farm", "rs:n:chill"]
    ancien = env.conf["rs_panneaux"]["entraide"]
    publier(g, g.membre(7), "aide")
    d = run(E.charger(1))
    carte = next(e for e in salon.envois if e[0] == d["fil_id"])
    assert "rs:j:1" in ids(carte[2]["view"]) and g.fils[d["fil_id"]].parent is salon
    assert ancien in g.effaces and env.conf["rs_panneaux"]["entraide"] != ancien, "le panneau est reposé sous la carte"
    run(E.fermer(g, 1, 7, "fermee"))
    assert salon.cartes[-1][0] == d["fil_id"], "hors forum, la carte se met à jour dans le salon"
    run(E.entretenir(g, maintenant=time.time() + E.GARDER_H * 3600 + 60))
    assert d["fil_id"] in g.effaces, "le fil et sa carte disparaissent"


def test_E11_le_panneau_aide_mene_aux_deux_forums(env):
    g, _ = installe(env)
    cf = run(E.conf(g))
    lignes = E.lignes_aide(g, cf)
    assert [ch.name for ch, _t, _b in lignes] == ["🆘・entraide", "🤝・trade"]
    assert [b for _c, _t, b in lignes] == ["Demander", "Échanger"]
    del g.salons[env.conf["rs_salons"]["trade"]]
    assert E.lignes_aide(g, cf)[1][0] is None, "un forum effacé : sa ligne disparaît du panneau"
    cf["actif"] = False
    assert E.lignes_aide(g, cf) == []


# ─── Regroupement de la première installation ────────────────────────────────

def _premiere_installation(env, membre_a_parle=False):
    g = Monde(forum=True)
    env.conf.update(aide_salon=g.nom("❓aide").id, suggestions_salon=g.nom("💡suggestions").id,
                    boosts_salon=g.nom("🚀boosts").id)
    vieille = g.categorie("🏴‍☠️ RELL SEAS")
    salons = {"orientation": g._salon(Texte, "🧭・orientation", {"category": vieille})}
    for cle, nom in (("aide", "🆘・aide"), ("boss", "⚔️・boss"), ("farm", "🌾・farm"), ("trade", "🤝・trade"),
                     ("chill", "🌴・chill")):
        salons[cle] = g._salon(Forum, nom, {"category": vieille, "available_tags": [
            discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in E.TAGS]})
    salons["discussion"] = g._salon(Texte, "💬・discussion", {"category": vieille})
    salons["discussion"].historique = [Message(salons["discussion"], 1, auteur_bot=not membre_a_parle)]
    panneaux = {}
    for cle in ("aide", "boss", "farm", "trade", "chill"):
        panneaux[cle] = g.nouveau_fil(salons[cle], f"📌 Publier une demande · {cle}").id
    env.conf.update(rs_actif=1, rs_categorie=vieille.id, rs_salons={k: s.id for k, s in salons.items()},
                    rs_panneaux=panneaux, rs_roles={})
    return g, vieille, salons


def test_E12_trop_de_salons_la_premiere_installation_devient_deux_forums_dans_communautaire(env):
    g, vieille, anciens = _premiere_installation(env)
    run(E._ecrire("INSERT INTO entraide_demandes(guild_id, zone, auteur_id, titre, salon_id, fil_id, cree, maj)"
                  " VALUES(1, 'boss', 7, 'Akuma', ?, ?, ?, ?)",
                  (anciens["boss"].id, g.nouveau_fil(anciens["boss"], "Akuma").id, int(time.time()), int(time.time()))))
    faits = run(E.migrer_v2(g))
    for cle in ("boss", "farm", "chill", "orientation", "discussion"):
        assert anciens[cle].supprime, cle
    assert vieille.supprime and len(g.categories) == 1, "plus de catégorie à part"
    entr, trade = anciens["aide"], anciens["trade"]
    assert (entr.name, entr.category_id, trade.category_id) == ("🆘・entraide", g.commu.id, g.commu.id)
    assert [t.name for t in entr.available_tags][:4] == ["Aide", "Boss", "Farm", "Chill"]
    assert env.conf["rs_salons"] == {"entraide": entr.id, "trade": trade.id} and env.conf["rs_v2"]
    assert run(E.charger(1))["statut"] == "fermee", "la demande d'un forum retiré est fermée proprement"
    post = g.fils[env.conf["rs_panneaux"]["entraide"]]
    assert post.name == "📌 Publier une demande" and "rs:n:farm" in ids(post.cartes[-1][1]["view"])
    assert [s.name for s in g.commu.channels] == ["❓aide", "💬chat", "🆘・entraide", "🤝・trade", "💡suggestions",
                                                  "🚀boosts", "🔊Join"]
    assert any("retiré" in f for f in faits) and run(E.migrer_v2(g)) == [], "une seule fois"


def test_E13_une_discussion_ou_des_membres_ont_ecrit_n_est_pas_effacee(env):
    g, vieille, anciens = _premiere_installation(env, membre_a_parle=True)
    faits = run(E.migrer_v2(g))
    disc = anciens["discussion"]
    assert not disc.supprime and disc.category_id == g.commu.id, "rangée, pas effacée"
    assert any("gardé" in f for f in faits) and vieille.supprime


# ─── Branchement dans le bot ─────────────────────────────────────────────────

def test_E14_branche_dans_le_bot():
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
    vue_aide = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "_vue_aide")
    assert vue_aide.index("*entraide.lignes_aide(g, cf_entraide)") < vue_aide.index("Ouvrir un ticket"), \
        "le panneau ❓ aide est l'orientation : l'entraide en tête"
    boucle = next(ast.unparse(n) for n in arbre.body if getattr(n, "name", "") == "entraide_task")
    assert "g.owner_id in TETE_IDS and (not c.get('rs_installation_auto'))" in boucle
    assert boucle.index("db_set(g.id, 'rs_installation_auto'") < boucle.index("entraide.installer(g)")
    assert "await entraide.migrer_v2(g)" in boucle and "await _salon_aide(g)" in boucle
    assert all((RACINE / "visuels" / f"{k}.gif").is_file() for k in ("rs_port", "rs_entraide", "rs_trade"))
    assert not (RACINE / "visuels" / "rs_boss.gif").exists(), "plus de bandeau pour un salon qui n'existe plus"
    assert '"Entraide": "#84cc16"' in (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert json.dumps(sorted(E.ids_salons({"rs_salons": {"a": 5, "b": "6"}, "rs_categorie": 4}))) == "[4, 5, 6]"
