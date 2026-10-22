"""Un faux serveur Discord pour les tests de l'entraide, des équipages et des zones : catégories,
salons texte, forums, vocaux, fils, rôles, membres ; rangement (`move`), édition, suppression."""
from __future__ import annotations

import asyncio

import discord

from conftest_discord import Obj, Reponse, laisser_finir


class Partiel:
    def __init__(self, porteur, mid):
        self.porteur, self.id = porteur, mid

    async def edit(self, **kw):
        if self.id in self.porteur.monde.effaces:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        self.porteur.cartes.append((self.id, kw))

    async def delete(self):
        self.porteur.monde.effaces.add(self.id)


class Fil(discord.Thread):
    """Un fil (ou un post de forum) : un vrai `discord.Thread` pour les `isinstance` du bot."""
    parent = jump_url = flags = applied_tags = None   # masquent les propriétés de discord.Thread

    def __init__(self, monde, tid, parent, name, contenu=None):
        self.monde, self.id, self.parent, self.name, self.contenu = monde, tid, parent, name, contenu
        self.envois, self.edits, self.membres, self.cartes = [], [], [], []
        self.archived = self.locked = False
        self.flags = Obj(pinned=False)
        self.last_message_id = None
        self.jump_url = f"https://discord.com/channels/1/{tid}"
        self.applied_tags = []
        self.messages = []

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))
        m = Message(self, self.monde.nouvel_id())
        m.content, m.kw = content, kw
        ref = kw.get("reference")
        m.reference = Obj(message_id=getattr(ref, "id", None)) if ref is not None else None
        self.messages.append(m)
        return m

    def repondre(self, membre_id: int, a: int, texte: str = "ok"):
        """Un membre répond à un message du post (une carte, un mot du bot)."""
        m = Message(self, self.monde.nouvel_id(), auteur_bot=False)
        m.content, m.kw, m.reference = texte, {}, Obj(message_id=a)
        m.author.id = membre_id
        self.messages.append(m)
        return m

    def visibles(self) -> list:
        return [m for m in self.messages if m.id not in self.monde.effaces]

    async def fetch_message(self, mid):
        if mid in self.monde.effaces or not (mid == self.id or any(m.id == mid for m in self.messages)):
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return next((m for m in self.messages if m.id == mid), Message(self, mid))

    def history(self, limit=None, after=None):
        async def gen():
            n = 0
            for m in self.visibles():
                if after is not None and m.id <= after.id:
                    continue
                yield m
                n += 1
                if limit and n >= limit:
                    return
        return gen()

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
        self.edits, self.supprime, self.permissions = [], False, []
        self.topic = kw.get("topic")

    def overwrites_for(self, cible):
        o = (self.kw.get("overwrites") or {}).get(cible)
        return discord.PermissionOverwrite(**dict(o)) if o is not None else discord.PermissionOverwrite()

    async def set_permissions(self, cible, *, overwrite=None, reason=None):
        self.kw.setdefault("overwrites", {})[cible] = overwrite
        self.permissions.append((cible, overwrite))

    position = property(lambda self: self.monde.ordre.index(self.id))
    category = property(lambda self: self.monde.get_channel(self.category_id) if self.category_id else None)
    jump_url = property(lambda self: f"https://discord.com/channels/1/{self.id}")
    mention = property(lambda self: f"<#{self.id}>")

    async def edit(self, **kw):
        self.edits.append(kw)
        if "name" in kw:
            self.name = kw["name"]
        if "topic" in kw:
            self.topic = kw["topic"]
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

    async def create_thread(self, *, name, view=None, content=None, allowed_mentions=None, applied_tags=(),
                            reason=None, **_kw):
        fil = self.monde.nouveau_fil(self, name, contenu=content)
        fil.applied_tags = [t.name for t in applied_tags or []]
        self.crees.append(Obj(fil=fil, view=view, content=content, allowed_mentions=allowed_mentions))
        return Obj(thread=fil, message=Obj(id=fil.id))


class Message:
    def __init__(self, salon, mid, auteur_bot=True):
        self.salon, self.id, self.author = salon, mid, Obj(bot=auteur_bot)
        self.jump_url = f"https://discord.com/channels/1/{salon.id}/{mid}"

    async def create_thread(self, *, name, auto_archive_duration=None, reason=None):
        return self.salon.monde.nouveau_fil(self.salon, name, self.id)


class Droits:
    """Les droits du bot dans un salon : tous, sauf ceux qu'un test retire."""
    def __init__(self, refus=()):
        self.refus = set(refus)

    def __getattr__(self, nom):
        return nom not in self.refus


class Texte(Rangeable, discord.TextChannel):
    def __init__(self, monde, cid, name, kw):
        self._init(monde, cid, name, kw)
        self.envois, self.cartes, self.historique, self.refus, self.panne = [], [], [], set(), False

    def permissions_for(self, _membre):
        return Droits(self.refus)

    async def send(self, content=None, **kw):
        if self.panne:
            raise discord.HTTPException(Obj(status=500, reason="x"), "panne")
        mid = self.monde.nouvel_id()
        self.envois.append((mid, content, kw))
        return Message(self, mid)

    def get_partial_message(self, mid):
        return Partiel(self, mid)

    async def fetch_message(self, mid):
        if mid in self.monde.effaces or not any(e[0] == mid for e in self.envois):
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        return Message(self, mid)

    def history(self, limit=None, after=None):
        async def gen():
            n = 0
            for m in self.historique:
                if after is not None and m.id <= after.id:
                    continue
                if m.id in self.monde.effaces:
                    continue
                yield m
                n += 1
                if limit and n >= limit:
                    return
        return gen()

    async def create_thread(self, *, name, type=None, auto_archive_duration=None, reason=None):
        return self.monde.nouveau_fil(self, name)


class Vocal(Rangeable, discord.VoiceChannel):
    def __init__(self, monde, cid, name, kw):
        self._init(monde, cid, name, kw)


class Categorie(discord.CategoryChannel):
    def __init__(self, monde, cid, name):
        self.monde, self.id, self.name, self.supprime, self.edits = monde, cid, name, False, []

    #  Comme discord.py (et l'appli) : les vocaux sous les salons texte, puis par position.
    channels = property(lambda self: sorted((s for s in self.monde.salons.values()
                                             if getattr(s, "category_id", None) == self.id),
                                            key=lambda s: (isinstance(s, Vocal), s.position)))
    position = property(lambda self: self.monde.categories_.index(self))

    async def edit(self, **kw):
        self.edits.append(kw)
        if "position" in kw:
            self.monde.categories_.remove(self)
            self.monde.categories_.insert(min(kw["position"], len(self.monde.categories_)), self)

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
        self.id, self.mention, self.display_name, self.name = uid, f"<@{uid}>", f"Pirate{uid}", f"pirate{uid}"
        self.display_avatar = Obj(url=f"https://cdn.discordapp.com/avatars/{uid}.png")
        self.display_avatar.with_size = lambda _n: self.display_avatar
        self.roles, self.guild_permissions, self.bot = list(roles), Obj(administrator=False), False
        for r in roles:
            r.members.append(self)

    def is_timed_out(self):
        return False


class Monde:
    def __init__(self, forum=True, communautaire=True):
        self.id, self.name, self.features = 1, "GoRP SEA", ["COMMUNITY"] if forum else []
        self.premium_subscription_count, self.premium_tier, self.members, self.chunked = 0, 0, [], True
        self.salons, self.fils, self.roles, self.membres, self.effaces = {}, {}, {}, {}, set()
        self.ordre, self.categories_, self.mouvements = [], [], []
        self.default_role = Obj(id=1)
        self.me = Obj(id=999, guild_permissions=Obj(manage_channels=True, manage_roles=True, mention_everyone=True))
        self.owner_id = 781205382923288593
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

    def nouveau_fil(self, parent, name, tid=None, contenu=None):
        fil = Fil(self, tid or self.nouvel_id(), parent, name, contenu)
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
        c = self.categorie(name)
        c.kw = kw
        return c

    async def create_role(self, *, name, **kw):
        r = Role(self.nouvel_id(), name, kw)
        self.roles[r.id] = r
        return r

    async def create_text_channel(self, name, **kw):
        return self._salon(Texte, name, kw)

    async def create_forum(self, name, **kw):
        return self._salon(Forum, name, kw)

    async def create_voice_channel(self, name, **kw):
        return self._salon(Vocal, name, kw)


class ReponseV2(Reponse):
    """La réponse d'une interaction, qui sait aussi réécrire le message du bouton."""
    def __init__(self):
        super().__init__()
        self.edits = []

    async def edit_message(self, **kw):
        self.fait = True
        self.edits.append(kw)


def interaction(g, membre):
    suivis, reponse = [], ReponseV2()

    async def suivi(content=None, **kw):
        suivis.append((content, kw))

    async def editer(**kw):
        suivis.append(("edit", kw))
    return Obj(guild=g, user=membre, response=reponse, followup=Obj(send=suivi), suivis=suivis,
               edit_original_response=editer, locale="fr")


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
            if c.get("accessory"):
                tout(c["accessory"])
    for comp in vue.to_components():
        tout(comp)
    return out


def compter(vue) -> int:
    """Le nombre de composants d'un message Components V2 (Discord en accepte 40)."""
    def tout(c):
        n = 1
        for x in c.get("components", []) or []:
            n += tout(x)
        if c.get("accessory"):
            n += 1
        return n
    return sum(tout(c) for c in vue.to_components())


ANCIENS_STATUTS = (("Ouverte", "🟢"), ("En cours", "🟡"), ("Terminée", "✅"), ("Fermée", "🔒"))


def lot_18(conf: dict, forum=True):
    """Le serveur tel que le lot 18 l'a laissé : deux forums dans Communautaire, noms et étiquettes en
    français, badge 🆘 sur l'étiquette « Aide », posts épinglés d'alors."""
    g = Monde(forum=forum)
    conf.update(aide_salon=g.nom("❓aide").id, suggestions_salon=g.nom("💡suggestions").id,
                boosts_salon=g.nom("🚀boosts").id)
    types = [discord.ForumTag(name=n, emoji=e, moderated=True)
             for n, e in (("Aide", "🆘"), ("Boss", "⚔️"), ("Farm", "🌾"), ("Chill", "🌴"))]
    statuts = [discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in ANCIENS_STATUTS]
    for n, t in enumerate(types + statuts):
        t.id = 500 + n
    entr = g._salon(Forum, "🆘・entraide", {"category": g.commu, "available_tags": types + statuts, "overwrites": {
        g.default_role: discord.PermissionOverwrite(send_messages=False, send_messages_in_threads=True)}})
    trade = g._salon(Forum, "🤝・trade", {"category": g.commu, "available_tags": [
        discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in ANCIENS_STATUTS]})
    #  Rangés comme au lot 18 : ❓aide, 💬chat, 🆘・entraide, 🤝・trade, 💡suggestions, 🚀boosts, 🔊Join
    ordre = ([g.nom(n).id for n in ("❓aide", "💬chat")] + [entr.id, trade.id]
             + [g.nom(n).id for n in ("💡suggestions", "🚀boosts", "🔊Join")])
    g.ordre = ordre + [x for x in g.ordre if x not in ordre]
    p1, p2 = g.nouveau_fil(entr, "📌 Publier une demande"), g.nouveau_fil(trade, "📌 Proposer un échange")
    for p in (p1, p2):
        p.flags.pinned, p.locked = True, True
    conf.update(rs_actif=1, rs_v2=1, rs_salons={"entraide": entr.id, "trade": trade.id},
                rs_panneaux={"entraide": p1.id, "trade": p2.id}, rs_roles={})
    return g, entr, trade, p1, p2
