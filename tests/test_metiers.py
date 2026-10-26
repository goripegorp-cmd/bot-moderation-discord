"""Les rôles de métier du clan GoRP (25/10/2026) — metiers.py, de bout en bout.

Le fondateur : « dès qu'il choisit un métier, j'aimerais que le métier soit créé sous forme de rôle et que ça leur soit
attribué. Une fois qu'ils ne font plus [partie du clan]… ils perdent tout leur rôle qui font partie du clan. »

M1 le premier choix crée le rôle (nom de profession, aucune permission, couleur de catégorie, juste sous le rôle du
clan) et le donne ; l'affiche est créée au minimum. M2 l'icône officielle si le serveur a les icônes de rôle. M3 changer,
retirer, « aucun métier » : jamais un autre rôle ; un rôle du même nom est relié. M4 la limite de métiers (liste, site).
M5 la liste est réservée au clan. M6 quitter le clan : tous les rôles du clan partent ; revenir : les métiers reviennent.
M7 une sanction en cours : rien ne bouge. M8 la réconciliation. M9 les adresses du site et leurs droits. M10 le guide du
clan et son sélecteur persistant. M11 l'acceptation au clan : la carte du ticket. M12 le câblage dans bot.py. M13 les
membres sous sanction (bot.py). M14 une affiche enregistrée sur le site et « Appliquer »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import aiosqlite
import discord
import pytest

import affiches
import health_server
import metiers
import registre
import rellseas_panneau
import tableau
import transcript_store
import visuels
import zones as ZN
from conftest_discord import Obj, Reponse, laisser_finir
from faux_serveur import compter, ids, textes

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
TETE = frozenset({FONDATEUR, DIRECTION})
ORIGINE = {"X-Tableau": "1", "Origin": "https://bot.exemple", "Sec-Fetch-Site": "same-origin"}
LAITON, CIRE, SAUGE, AMBRE, PRUNE = 0xB08D57, 0xC0665E, 0x6F9A5D, 0xB8742C, 0x857596
CATALOGUE = {
    "types": [{"cle": "metier", "nom": "Métiers", "nom_en": "Talents", "champ": "Métiers", "multiple": True, "ordre": 1},
              {"cle": "race", "nom": "Races", "nom_en": "Races", "champ": "identite", "multiple": False, "ordre": 2}],
    "elements": [
        {"type": "metier", "cle": "cooking", "nom": "Cuisine", "nom_en": "Cooking", "categorie": "Production · soutien",
         "statut": "confirme", "ordre": 1},
        {"type": "metier", "cle": "thieving", "nom": "Vol", "nom_en": "Thieving", "categorie": "Illégal · furtivité",
         "statut": "confirme", "ordre": 2},
        {"type": "metier", "cle": "fishing", "nom": "Pêche", "nom_en": "Fishing", "categorie": "Récolte",
         "statut": "confirme", "ordre": 3},
        {"type": "metier", "cle": "doctor", "nom": "Médecin", "nom_en": "Doctor", "categorie": "Soutien · santé",
         "statut": "confirme", "ordre": 4},
        {"type": "metier", "cle": "shipwright", "nom": "Charpentier naval", "nom_en": "Shipwright", "categorie": "Navire",
         "ordre": 5, "actif": False},
        {"type": "metier", "cle": "harponnage", "nom": "Harponnage", "nom_en": "Harpooning", "categorie": "Combat",
         "ordre": 6},
        {"type": "race", "cle": "humain", "nom": "Humain", "nom_en": "Human", "ordre": 1}]}


# ═══════════════════════════════════════════════════════════════════════════════
#  Le faux serveur : des rôles rangés (positions), des membres, la création et le rangement des rôles
# ═══════════════════════════════════════════════════════════════════════════════

class Role:
    def __init__(self, g, rid, nom, position, permissions=None, managed=False, couleur=0):
        self.guild, self.id, self.name, self.position, self.managed = g, rid, nom, position, managed
        self.permissions = permissions or discord.Permissions.none()
        self.colour = discord.Colour(couleur)
        self.mention = f"<@&{rid}>"

    def is_default(self):
        return self.id == self.guild.id

    members = property(lambda self: [m for m in self.guild.membres.values() if self in m.roles])

    def _cle(self):
        return (self.position, -self.id)

    def __lt__(self, autre):
        return self._cle() < autre._cle()

    def __ge__(self, autre):
        return self._cle() >= autre._cle()

    def __repr__(self):
        return f"<Role {self.name} {self.position}>"


class Membre:
    def __init__(self, g, uid, nom, *roles, bot=False):
        self.guild, self.id, self.display_name, self.name, self.bot = g, uid, nom, nom.lower(), bot
        self.roles = [g.default_role, *roles]
        self.mention = f"<@{uid}>"
        url = f"https://cdn.discordapp.com/avatars/{uid}.png"
        self.display_avatar = Obj(url=url, with_size=lambda _n: Obj(url=url))
        self.ajouts, self.retraits = [], []

    async def add_roles(self, *roles, reason=None):
        if self.guild.refus_roles:
            raise discord.Forbidden(Obj(status=403, reason="x"), "Missing Permissions")
        self.ajouts.append(([r.id for r in roles], reason))
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        if self.guild.refus_roles:
            raise discord.Forbidden(Obj(status=403, reason="x"), "Missing Permissions")
        self.retraits.append(([r.id for r in roles], reason))
        self.roles = [r for r in self.roles if r not in roles]


class Serveur:
    def __init__(self, features=(), decaler=True):
        self.id, self.name, self.owner_id, self.icon = 1, "GoRP SEA", FONDATEUR, None
        self.features, self.decaler, self.refus_roles, self.refus_icone = list(features), decaler, False, False
        self._roles, self.membres, self.crees, self.rangements = {}, {}, [], []
        self.default_role = self.role(1, "@everyone", 0)
        self.me = Obj(id=999, top_role=self.role(2, "GoRP Bot", 60),
                      guild_permissions=discord.Permissions(manage_roles=True))

    roles = property(lambda self: sorted(self._roles.values(), key=lambda r: (r.position, -r.id)))
    members = property(lambda self: list(self.membres.values()))

    def role(self, rid, nom, position, **kw):
        self._roles[rid] = Role(self, rid, nom, position, **kw)
        return self._roles[rid]

    def membre(self, uid, nom, *roles, bot=False):
        self.membres[uid] = Membre(self, uid, nom, *roles, bot=bot)
        return self.membres[uid]

    def get_role(self, rid):
        return self._roles.get(int(rid or 0))

    def get_member(self, uid):
        return self.membres.get(int(uid or 0))

    def ordre(self) -> list:
        """Les noms du haut vers le bas, comme Discord les montre."""
        return [r.name for r in sorted(self._roles.values(), key=lambda r: (r.position, -r.id), reverse=True)]

    async def create_role(self, **kw):
        if self.refus_icone and kw.get("display_icon"):
            raise discord.HTTPException(Obj(status=400, reason="x"), "Invalid image")
        self.crees.append(kw)
        if self.decaler:   # comme Discord : le nouveau rôle arrive tout en bas, les autres montent d'un cran
            for r in self._roles.values():
                if not r.is_default():
                    r.position += 1
        rid = 500 + len(self.crees)
        return self.role(rid, kw["name"], 1, permissions=kw.get("permissions"), couleur=kw["colour"].value)

    async def fetch_roles(self):
        return list(self._roles.values())

    async def edit_role_positions(self, positions, reason=None):
        self.rangements.append({o.id: p for o, p in positions.items()})
        for o, p in positions.items():
            self._roles[o.id].position = p
        return list(self._roles.values())


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


def run(coro):
    async def avec_taches():
        r = await coro
        await laisser_finir()
        return r
    return asyncio.run(avec_taches())


class Banc:
    """Le serveur du clan : le rôle du clan (GoRPC), un grade (Officier), un VIP, un rôle de modération, une intégration,
    un rôle au-dessus du bot ; Kolax et Mira dans le clan, Intrus hors du clan ; la tête pour le site."""

    def __init__(self, tmp_path, monkeypatch, features=(), decaler=True):
        self.tmp = tmp_path
        self.get_db = get_db = _base(tmp_path / "metiers.db")
        g = self.g = Serveur(features, decaler)
        self.membre_role = g.role(10, "Membre", 1)
        self.vip = g.role(11, "VIP", 2)
        self.officier = g.role(12, "Officier", 3, couleur=0x4A2E1A)
        self.clan = g.role(20, "GoRPC", 4, couleur=0x1F4E5A)
        self.mod = g.role(30, "Modérateur", 5, permissions=discord.Permissions(kick_members=True))
        self.integration = g.role(31, "Bot musique", 6, managed=True)
        self.haut = g.role(40, "Au-dessus du bot", 70)
        self.kolax = g.membre(7, "Kolax", self.membre_role, self.clan)
        self.mira = g.membre(8, "Mira", self.membre_role, self.clan, self.vip)
        self.intrus = g.membre(9, "Intrus", self.membre_role)
        self.robot = g.membre(3, "Robot", self.clan, bot=True)
        self.chef = g.membre(FONDATEUR, "GoRipe", self.membre_role)
        self.direction = g.membre(DIRECTION, "Direction", self.membre_role)
        self.conf = {rellseas_panneau.CLE_ROLE_CIBLE: self.clan.id}
        self.journal, self.sanctionnes, self.guides, self.journal_bot = [], set(), [], []

        async def cfg(_gid):
            return self.conf

        async def db_set(_gid, k, v):
            self.conf[k] = v

        async def journal(_g, type_, texte, **kw):
            self.journal.append((type_, texte, kw))

        async def sanctionnes(_g):
            if self.sanctionnes is None:
                raise aiosqlite.OperationalError("database is locked")
            return set(self.sanctionnes)

        async def guide(_g):
            self.guides.append(_g.id)

        def tete(_g, m, c=None):
            return m is not None and m.id in TETE

        async def alerte(*_a, **_k):
            return None
        self.cfg, self.db_set = cfg, db_set
        monkeypatch.setattr(tableau, "ROUTES", {})
        monkeypatch.setattr(tableau, "REGLES", dict(tableau.REGLES))
        monkeypatch.setattr(tableau, "_SOURCES_MEDIAS", [])
        monkeypatch.setattr(tableau, "RACINE_DONNEES", tmp_path / "donnees")
        monkeypatch.setattr(tableau, "SITE", tmp_path / "site")
        monkeypatch.setattr(transcript_store, "_BASE_DIR", str(tmp_path / "transcripts"))
        monkeypatch.setattr(visuels, "DOSSIER", tmp_path / "visuels")     # jamais les vraies icônes du dépôt
        monkeypatch.setattr(affiches, "_PRESENTES", {})
        monkeypatch.setattr(metiers, "AVIS_S", 0.0)
        monkeypatch.setattr(metiers, "DEMARRE_S", 0.0)
        monkeypatch.setattr(metiers, "PAUSE_CHOIX_S", 0.0)
        monkeypatch.setattr(metiers, "PAUSE_RECONCILIATION", 0.0)
        monkeypatch.setattr(metiers, "GUIDE_APRES_S", 0.0)
        tableau._statiques.clear()
        tableau._page_site.clear()
        tableau._cache_empreinte.update(signature=None, v="", vu=0.0)
        registre.setup(get_db=get_db, log=lambda *a: None)
        registre._derniers.clear()
        tableau.setup(bot=Obj(get_guild=lambda gid: g if gid == 1 else None, user=Obj(id=999)), cle="k",
                      base_url="https://bot.exemple", cfg=cfg, get_db=get_db, mesurer_groupe=None, autorise_membre=tete,
                      direction=tete, tete=TETE, alerte_securite=alerte, log=self.journal_bot.append)
        affiches.setup(get_db=get_db, log=self.journal_bot.append)
        metiers.setup(get_db=get_db, cfg=cfg, db_set=db_set,
                      role_clan=lambda gg, c: gg.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0)),
                      sanctionnes=sanctionnes, journal=journal, guide=guide, epargnes=lambda gg, m: m.id in TETE,
                      log=self.journal_bot.append)
        depart = tmp_path / "catalogue.json"
        depart.write_text(json.dumps(CATALOGUE, ensure_ascii=False), encoding="utf-8")

        async def preparer():
            await registre.init_db()
            await tableau.init_db()
            await affiches.init_db()
            await affiches.charger_depart(depart)
        asyncio.run(preparer())
        tableau.monter(affiches)

    # ── outils ──
    def choisir(self, membre, *valeurs):
        """Le membre choisit dans la liste du guide (le vrai composant persistant) → l'interaction."""
        i = interaction(self.g, membre, list(valeurs))

        async def faire():
            item = await metiers.ChoixMetier.from_custom_id(i, None, None)
            await item.callback(i)
        run(faire())
        return i

    def sql(self, requete, args=()):
        async def lire():
            async with self.get_db() as db:
                async with db.execute(requete, args) as cur:
                    return await cur.fetchall()
        return asyncio.run(lire())

    def affiche(self, membre):
        return asyncio.run(affiches._affiche_du_membre(self.g.id, membre.id))

    def role_nomme(self, nom):
        return next((r for r in self.g._roles.values() if r.name == nom), None)

    def lien(self, cle):
        lignes = self.sql("SELECT role_id, auto FROM rell_roles WHERE guild_id=1 AND type='metier' AND cle=?", (cle,))
        return lignes[0] if lignes else None

    def types_journal(self):
        return [t for t, _x, _k in self.journal]

    def http(self, scenario):
        from aiohttp.test_utils import TestClient, TestServer

        async def lancer():
            async with TestClient(TestServer(health_server.construire_app())) as client:
                return await scenario(client)
        return asyncio.run(lancer())

    def biscuit(self, uid=FONDATEUR) -> dict:
        jeton = asyncio.run(tableau._ouvrir_session(1, uid, int(time.time()) + 3600))
        return dict({"Cookie": f"{tableau.COOKIE}={jeton}"}, **ORIGINE)


def interaction(g, membre, valeurs):
    suivis, supprimes = [], []

    async def suivi(content=None, **kw):
        suivis.append(kw.get("view", content))

    async def supprimer():
        supprimes.append(True)
    return Obj(guild=g, user=membre, response=Reponse(), followup=Obj(send=suivi), suivis=suivis,
               data={"values": valeurs}, delete_original_response=supprimer, supprimes=supprimes)


def avis(i) -> str:
    vue = i.suivis[-1] if i.suivis else i.response.messages[-1][1]["view"]
    return textes(vue)


@pytest.fixture
def banc(tmp_path, monkeypatch):
    return Banc(tmp_path, monkeypatch)


async def _json(r):
    return r.status, json.loads(await r.text())


# ═══════════════════════════════════════════════════════════════════════════════
#  M1 — le premier choix crée le rôle et le donne
# ═══════════════════════════════════════════════════════════════════════════════

def test_M1_premier_choix_cree_le_role_sous_le_clan_sans_permission_et_le_donne(banc):
    g, kolax = banc.g, banc.kolax
    i = banc.choisir(kolax, "cooking")
    assert i.response.fait and not i.response.messages, "acquitté d'abord (defer), la réponse suit"
    cree = g.crees[0]
    assert cree["name"] == "Cuisinier", "un nom de profession, pas « Cuisine »"
    assert cree["permissions"] == discord.Permissions.none(), "AUCUNE permission"
    assert cree["colour"].value == LAITON and cree["hoist"] is False and cree["mentionable"] is False
    assert "display_icon" not in cree, "le serveur n'a pas les icônes de rôle : rien"
    cuisinier = banc.role_nomme("Cuisinier")
    assert g.ordre()[:5] == ["Au-dessus du bot", "GoRP Bot", "Bot musique", "Modérateur", "GoRPC"]
    assert g.ordre()[5] == "Cuisinier", "juste sous le rôle du clan"
    assert g.ordre()[6:] == ["Officier", "VIP", "Membre", "@everyone"], "les rôles d'en dessous gardent leur ordre"
    assert banc.lien("cooking") == (cuisinier.id, 1), "lié au métier (attribution automatique)"
    assert cuisinier in kolax.roles and kolax.ajouts == [([cuisinier.id], kolax.ajouts[0][1])]
    a = banc.affiche(kolax)
    assert (a["membre_id"], a["membre_nom"], a["attributs"], a["cree_par"]) == (7, "Kolax", {"metier": ["cooking"]}, 7), \
        "l'affiche créée au minimum : le membre, son nom, son métier"
    histo = banc.sql("SELECT action, par FROM rell_affiches_historique WHERE affiche_id=?", (a["id"],))
    assert histo == [("creee", 7)]
    t = avis(i)
    assert "C'est noté : **Cuisinier**" in t and "Noted: Cooking" in t and "rôles de métier suivent" in t
    assert i.supprimes == [True], "la réponse, pour lui seul, s'efface"
    assert banc.types_journal() == ["clan.metier_role", "clan.metiers_roles", "clan.metier_choisi"]
    assert banc.journal[0][1] == "Rôle « Cuisinier » créé pour le métier « Cuisine » (sans permission, sous le rôle du clan)"
    assert banc.journal[1][1] == "Rôles des métiers de Kolax : +Cuisinier (son choix)"
    assert banc.journal[2][1] == "Kolax a choisi son métier : Cuisinier"
    #  Un deuxième membre, le même métier : le même rôle, aucun doublon.
    banc.choisir(banc.mira, "cooking")
    assert len(g.crees) == 1 and cuisinier in banc.mira.roles


def test_M1b_le_rangement_tient_aussi_quand_discord_ne_decale_pas_les_roles(tmp_path, monkeypatch):
    """Discord peut laisser le rôle neuf à la position 1, À ÉGALITÉ avec le plus bas : le rangement renumérote, et
    remonte au-dessus du nouveau rôle tant que deux positions se touchent — jamais jusqu'au bot."""
    banc = Banc(tmp_path, monkeypatch, decaler=False)
    banc.choisir(banc.kolax, "cooking", "fishing")
    assert banc.g.ordre() == ["Au-dessus du bot", "GoRP Bot", "Bot musique", "Modérateur", "GoRPC", "Pêcheur",
                              "Cuisinier", "Officier", "VIP", "Membre", "@everyone"], "le dernier créé juste sous le clan"
    positions = [r.position for r in sorted(banc.g._roles.values(), key=lambda r: (r.position, -r.id))]
    assert all(a < b for a, b in zip(positions[1:], positions[2:])), "plus aucune égalité sous le bot"
    assert all(banc.g.me.top_role.id not in x for x in banc.g.rangements), "le rôle du bot n'est jamais déplacé"


def test_M1c_noms_et_couleurs_des_metiers():
    e = lambda cle, nom, cat="": {"cle": cle, "nom": nom, "categorie": cat}  # noqa: E731
    attendus = {("cooking", "Cuisine"): "Cuisinier", ("thieving", "Vol"): "Voleur", ("navigation", "Navigation"): "Navigateur",
                ("fishing", "Pêche"): "Pêcheur", ("crafting", "Artisanat"): "Artisan",
                ("woodcutting", "Bûcheronnage"): "Bûcheron", ("doctor", "Médecin"): "Médecin",
                ("mining", "Minage"): "Mineur", ("shipwright", "Charpentier naval"): "Charpentier naval",
                ("peche", "Pêche"): "Pêcheur", ("harponnage", "Harponnage"): "Harponnage",
                ("charpentier", "Charpentier"): "Charpentier"}
    for (cle, nom), role in attendus.items():
        assert metiers.nom_du_role(e(cle, nom)) == role, (cle, nom)
    assert metiers.nom_du_role({"cle": "x1", "nom": "Cuisine de bord", "nom_en": "Cooking"}) == "Cuisinier",         "renommé sur le site : reconnu par son nom anglais"
    for cat, couleur in (("Production · soutien", LAITON), ("Soutien · santé", CIRE), ("Récolte", SAUGE),
                         ("Combat", AMBRE), ("Illégal · furtivité", PRUNE), ("Équipage", metiers.COULEUR_DEFAUT),
                         ("", metiers.COULEUR_DEFAUT)):
        assert metiers.couleur_du_role(e("x", "X", cat)) == couleur, cat


# ═══════════════════════════════════════════════════════════════════════════════
#  M2 — l'icône officielle (ROLE_ICONS)
# ═══════════════════════════════════════════════════════════════════════════════

def _image(fmt="WEBP", taille=(300, 200)) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGBA", taille, (168, 130, 63, 255)).save(b, fmt)
    return b.getvalue()


def test_M2_icone_officielle_si_le_serveur_a_les_icones_de_role(tmp_path, monkeypatch):
    banc = Banc(tmp_path, monkeypatch, features=("ROLE_ICONS",))
    dossier = tmp_path / "site" / "icones" / "rell" / "metier"
    dossier.mkdir(parents=True)
    (dossier / "cooking.webp").write_bytes(_image())
    tableau._statiques.clear()
    chef = banc.chef
    st, _rep = asyncio.run(affiches._route_element(banc.g, chef, {}, {"type": "metier", "cle": "cooking", "version": 1,
                                                                       "nom": "Cuisine", "nom_en": "Cooking",
                                                                       "categorie": "Production · soutien",
                                                                       "icone": "s/icones/rell/metier/cooking.webp"}))
    assert st == 200
    banc.choisir(banc.kolax, "cooking", "fishing")
    icone = banc.g.crees[0]["display_icon"]
    from PIL import Image
    with Image.open(io.BytesIO(icone)) as im:
        assert (im.format, im.size) == ("PNG", (128, 128)) and len(icone) <= 256 * 1024, "PNG carré, 256 Ko au plus"
    assert "display_icon" not in banc.g.crees[1], "pas d'icône officielle pour la pêche : rien (jamais un émoji)"
    (tmp_path / "visuels" / "icones").mkdir(parents=True)
    (tmp_path / "visuels" / "icones" / "rell_metier_thieving.png").write_bytes(_image("PNG", (512, 512)))
    banc.choisir(banc.mira, "thieving")
    with Image.open(io.BytesIO(banc.g.crees[2]["display_icon"])) as im:
        assert (banc.g.crees[2]["name"], im.size) == ("Voleur", (128, 128)), "l'icône de l'émoji d'application du jeu"
    #  Discord refuse l'image : le rôle est créé quand même, sans icône.
    banc.g.refus_icone = True
    banc.choisir(banc.mira, "cooking")
    assert len(banc.g.crees) == 3, "le Cuisinier existait déjà : aucun rôle neuf"
    (dossier / "doctor.webp").write_bytes(_image("PNG"))
    tableau._statiques.clear()
    asyncio.run(affiches._route_element(banc.g, chef, {}, {"type": "metier", "cle": "doctor", "version": 1,
                                                           "nom": "Médecin", "nom_en": "Doctor", "categorie": "Soutien · santé",
                                                           "icone": "s/icones/rell/metier/doctor.webp"}))
    banc.choisir(banc.mira, "doctor")
    assert banc.g.crees[-1]["name"] == "Médecin" and "display_icon" not in banc.g.crees[-1]
    assert "[METIERS][E5] icône du rôle refusée : rôle créé sans icône" in banc.journal_bot
    assert banc.role_nomme("Médecin") in banc.mira.roles


# ═══════════════════════════════════════════════════════════════════════════════
#  M3 — changer, retirer, « aucun métier », un rôle du même nom
# ═══════════════════════════════════════════════════════════════════════════════

def test_M3_changer_de_metier_retire_l_ancien_role_et_jamais_un_autre(banc):
    g, mira = banc.g, banc.mira
    pecheur_existant = g.role(13, "Pêcheur", 1)          # un rôle du même nom, déjà là (un lien défait sur le site)
    banc.choisir(mira, "cooking")
    cuisinier = banc.role_nomme("Cuisinier")
    i = banc.choisir(mira, "fishing")
    assert banc.lien("fishing")[0] == pecheur_existant.id and len(g.crees) == 1, "relié, pas de doublon"
    assert pecheur_existant in mira.roles and cuisinier not in mira.roles
    assert banc.vip in mira.roles and banc.clan in mira.roles, "le VIP et le rôle du clan ne bougent jamais"
    assert "Rôle « Pêcheur » relié au métier « Pêche »" in [x for _t, x, _k in banc.journal]
    assert "C'est noté : **Pêcheur**" in avis(i)
    #  Le même choix : rien ne change, rien n'est appelé.
    appels = len(mira.ajouts) + len(mira.retraits)
    i = banc.choisir(mira, "fishing")
    assert "C'est déjà ton choix" in avis(i) and len(mira.ajouts) + len(mira.retraits) == appels
    #  « Aucun métier » : ses rôles de métier partent, son affiche n'en a plus.
    i = banc.choisir(mira, metiers.AUCUN)
    assert pecheur_existant not in mira.roles and banc.vip in mira.roles
    assert "metier" not in banc.affiche(mira)["attributs"] and "plus de métier" in avis(i)
    assert banc.journal[-1][1] == "Mira n'a plus de métier"
    #  « Aucun » mêlé à un métier : le métier l'emporte.
    banc.choisir(mira, metiers.AUCUN, "thieving")
    assert banc.affiche(mira)["attributs"] == {"metier": ["thieving"]} and banc.role_nomme("Voleur") in mira.roles


def test_M3b_choisir_garde_les_autres_attributs_et_suit_les_versions(banc):
    chef, kolax = banc.chef, banc.kolax
    st, rep = asyncio.run(affiches._route_affiche(banc.g, chef, {}, {"membre_id": "7", "surnom": "Le Requin", "prime": 500,
                                                                       "attributs": {"race": ["humain"]}}))
    assert st == 200
    version = rep["affiche"]["version"]
    banc.choisir(kolax, "doctor")
    a = banc.affiche(kolax)
    assert a["attributs"] == {"race": ["humain"], "metier": ["doctor"]} and a["surnom"] == "Le Requin" and a["prime"] == 500
    assert a["version"] == version + 1 and a["maj_par"] == kolax.id
    #  L'écran du site, resté sur l'ancienne version : un conflit, jamais une modification écrasée.
    st, rep = asyncio.run(affiches._route_affiche(banc.g, chef, {}, {"id": a["id"], "version": version, "membre_id": "7",
                                                                       "surnom": "Autre"}))
    assert st == 409 and rep["conflit"] and rep["actuelle"]["attributs"]["metier"] == ["doctor"]


# ═══════════════════════════════════════════════════════════════════════════════
#  M4 — la limite de métiers
# ═══════════════════════════════════════════════════════════════════════════════

def test_M4_limite_de_metiers_liste_et_site(banc):
    kolax, chef = banc.kolax, banc.chef
    i = banc.choisir(kolax, "cooking", "fishing", "doctor")
    assert "2 métier(s) au plus" in avis(i) and banc.affiche(kolax) is None and not banc.g.crees, "rien n'est enregistré"
    banc.conf[metiers.CLE_MAX] = 3
    banc.choisir(kolax, "cooking", "fishing", "doctor")
    assert banc.affiche(kolax)["attributs"]["metier"] == ["cooking", "fishing", "doctor"]
    assert {"Cuisinier", "Pêcheur", "Médecin"} <= {r.name for r in kolax.roles}
    #  La limite abaissée : les rôles des deux premiers métiers seulement (la réconciliation l'applique).
    banc.conf[metiers.CLE_MAX] = 2
    bilan = asyncio.run(metiers.reconcilier(banc.g))
    assert bilan["retires"] == 1 and banc.role_nomme("Médecin") not in kolax.roles
    assert {"Cuisinier", "Pêcheur"} <= {r.name for r in kolax.roles}
    #  Le site : la limite vaut aussi pour une affiche — seulement quand ses métiers changent.
    a = banc.affiche(kolax)
    st, rep = asyncio.run(affiches._route_affiche(banc.g, chef, {}, {"id": a["id"], "version": a["version"],
                                                                       "membre_id": "7", "prime": 1000,
                                                                       "attributs": a["attributs"]}))
    assert st == 200 and (rep["roles"]["ajoutes"], rep["roles"]["retires"]) == ([], []), \
        "une affiche d'avant l'abaissement reste modifiable pour le reste"
    st, rep = asyncio.run(affiches._route_affiche(banc.g, chef, {}, {"id": a["id"], "version": a["version"] + 1,
                                                                       "membre_id": "7",
                                                                       "attributs": {"metier": ["cooking", "fishing",
                                                                                                "thieving"]}}))
    assert (st, rep) == (400, {"erreur": "2 métier(s) au plus par membre (réglage « Rôles & métiers »).",
                               "champ": "attributs"})


# ═══════════════════════════════════════════════════════════════════════════════
#  M5 — la liste est réservée au clan
# ═══════════════════════════════════════════════════════════════════════════════

def test_M5_la_liste_est_reservee_au_clan(banc, monkeypatch):
    i = banc.choisir(banc.intrus, "cooking")
    assert "Réservé aux membres du clan GoRP" in avis(i) and "clan members only" in avis(i)
    assert banc.affiche(banc.intrus) is None and not banc.g.crees and i.supprimes == [True]
    i = banc.choisir(banc.kolax, "shipwright")
    assert "plus proposé" in avis(i), "un métier retiré du catalogue"
    i = banc.choisir(banc.kolax, "astronaute")
    assert "plus proposé" in avis(i)
    del banc.conf[rellseas_panneau.CLE_ROLE_CIBLE]
    i = banc.choisir(banc.kolax, "cooking")
    assert "pas encore ouvert" in avis(i) and not banc.g.crees
    monkeypatch.setattr(metiers, "_get_db", None)
    i = banc.choisir(banc.kolax, "cooking")
    assert "Le bot démarre" in textes(i.response.messages[-1][1]["view"]) and i.response.messages[-1][1]["ephemeral"]


def test_M5b_deux_choix_d_affilee_et_une_panne_repondent_toujours(banc, monkeypatch):
    monkeypatch.setattr(metiers, "PAUSE_CHOIX_S", 60.0)
    banc.choisir(banc.kolax, "cooking")
    i = banc.choisir(banc.kolax, "fishing")
    assert "Doucement" in avis(i) and banc.affiche(banc.kolax)["attributs"]["metier"] == ["cooking"]

    async def panne(*_a, **_k):
        raise RuntimeError("base verrouillée")
    monkeypatch.setattr(affiches, "definir_metiers", panne)
    with pytest.raises(RuntimeError):
        i = interaction(banc.g, banc.mira, ["cooking"])
        asyncio.run(metiers.ChoixMetier().callback(i))
    assert "Un souci est survenu" in avis(i), "une erreur répond quand même, pour soi"
    assert "[METIERS][E9] choix du métier en échec" in banc.journal_bot


# ═══════════════════════════════════════════════════════════════════════════════
#  M6 — quitter le clan, y revenir
# ═══════════════════════════════════════════════════════════════════════════════

def _quitte(banc, membre, *partants, ajoute=()):
    avant = copy.copy(membre)
    avant.roles = list(membre.roles)
    membre.roles = [r for r in membre.roles if r not in partants] + list(ajoute)
    run(metiers.sur_maj_membre(avant, membre))


def test_M6_perdre_le_role_du_clan_retire_tous_les_roles_du_clan(banc):
    mira = banc.mira
    banc.conf[metiers.CLE_RATTACHES] = [banc.officier.id]
    mira.roles.append(banc.officier)
    banc.choisir(mira, "cooking", "fishing")
    cuisinier, pecheur = banc.role_nomme("Cuisinier"), banc.role_nomme("Pêcheur")
    _quitte(banc, mira, banc.clan)            # retiré par un modérateur, par le site, l'inactivité… peu importe
    assert cuisinier not in mira.roles and pecheur not in mira.roles and banc.officier not in mira.roles
    assert banc.vip in mira.roles and banc.membre_role in mira.roles, "jamais un autre rôle"
    type_, texte, kw = banc.journal[-1]
    assert type_ == "clan.roles_depart" and kw["membre_id"] == mira.id
    assert texte.startswith("Mira n'est plus dans le clan : rôles du clan retirés (")
    assert set(texte.split("(")[1].rstrip(")").split(", ")) == {"Cuisinier", "Pêcheur", "Officier"}
    assert banc.affiche(mira)["attributs"]["metier"] == ["cooking", "fishing"], "son affiche garde ses métiers"
    #  Il revient (le rôle du clan rendu) : ses métiers reviennent — pas le grade (la direction le redonne).
    _quitte(banc, mira, ajoute=[banc.clan])
    assert cuisinier in mira.roles and pecheur in mira.roles and banc.officier not in mira.roles
    assert banc.journal[-1][1] == "Rôles des métiers de Mira : +Cuisinier, +Pêcheur (retour dans le clan)"
    #  Un changement qui ne touche pas au rôle du clan : rien.
    n = len(mira.ajouts) + len(mira.retraits)
    _quitte(banc, mira, banc.vip)
    assert len(mira.ajouts) + len(mira.retraits) == n


def test_M6b_attribution_automatique_non_rien_n_est_rendu_mais_tout_part(banc):
    kolax = banc.kolax
    banc.choisir(kolax, "cooking")
    banc.conf[metiers.CLE_AUTO] = False
    _quitte(banc, kolax, banc.clan)
    assert banc.role_nomme("Cuisinier") not in kolax.roles, "quitter le clan : les rôles partent, réglage ou non"
    _quitte(banc, kolax, ajoute=[banc.clan])
    assert banc.role_nomme("Cuisinier") not in kolax.roles, "attribution automatique NON : rien n'est rendu"
    i = banc.choisir(kolax, "fishing")
    assert "la direction attribue les rôles des métiers" in avis(i) and banc.role_nomme("Pêcheur") is None
    assert banc.affiche(kolax)["attributs"]["metier"] == ["fishing"]


def test_M6c_discord_refuse_le_retrait_c_est_dit_au_journal(banc):
    banc.choisir(banc.kolax, "cooking")
    banc.g.refus_roles = True
    _quitte(banc, banc.kolax, banc.clan)
    assert banc.journal[-1][0] == "clan.roles_erreur" and banc.journal[-1][2]["gravite"] == 1
    assert "[METIERS][E2] rôles du clan non retirés" in banc.journal_bot


# ═══════════════════════════════════════════════════════════════════════════════
#  M7 — une sanction en cours : rien ne bouge
# ═══════════════════════════════════════════════════════════════════════════════

def test_M7_sanction_en_cours_rien_n_est_retire_ni_rendu(banc):
    kolax = banc.kolax
    banc.choisir(kolax, "cooking")
    cuisinier = banc.role_nomme("Cuisinier")
    #  Isolement : la quarantaine retire le rôle du clan (rôle « sensible ») et le garde ; le Cuisinier reste.
    banc.sanctionnes = {kolax.id}
    _quitte(banc, kolax, banc.clan)
    assert cuisinier in kolax.roles, "pendant la sanction, ses rôles ne bougent pas"
    bilan = asyncio.run(metiers.reconcilier(banc.g))
    assert cuisinier in kolax.roles and bilan["sanctions"] == 1 and bilan["retires"] == 0
    #  La levée rend le rôle du clan (la fiche n'est pas encore effacée) : on ne se bat pas avec elle.
    _quitte(banc, kolax, ajoute=[banc.clan])
    assert kolax.ajouts[-1][0] == [cuisinier.id] and len(kolax.ajouts) == 1, "aucun rôle donné par-dessus la levée"
    #  Radiation : tout est retiré d'un coup (la sanction garde les rôles) ; le retour pendant la sanction : rien.
    kolax.roles = [banc.g.default_role]
    _quitte(banc, kolax, ajoute=[banc.clan])
    assert cuisinier not in kolax.roles
    i = banc.choisir(kolax, "fishing")
    assert "Indisponible" in avis(i) and banc.affiche(kolax)["attributs"]["metier"] == ["cooking"]
    #  Les sanctions illisibles (base occupée) : dans le doute, rien n'est touché.
    banc.sanctionnes = None
    _quitte(banc, kolax, banc.clan)
    bilan = asyncio.run(metiers.reconcilier(banc.g))
    assert bilan["erreurs"] == 1 and "Sanctions illisibles" in bilan["raison"]
    assert "[METIERS][E7] sanctions illisibles : rôles du clan laissés tels quels" in banc.journal_bot


# ═══════════════════════════════════════════════════════════════════════════════
#  M8 — la réconciliation
# ═══════════════════════════════════════════════════════════════════════════════

def test_M8_reconciliation_rattrape_ce_qu_un_redemarrage_a_manque(banc):
    g = banc.g
    banc.conf[metiers.CLE_RATTACHES] = [banc.officier.id]
    banc.choisir(banc.kolax, "cooking")
    banc.choisir(banc.mira, "thieving")
    cuisinier, voleur = banc.role_nomme("Cuisinier"), banc.role_nomme("Voleur")
    #  Pendant que le bot dormait : Kolax a quitté le clan, Intrus a gardé un grade, Mira a gagné un métier sur le
    #  site (rien n'a été appliqué), Bob est dans le clan sans affiche avec un rôle donné à la main, un ancien membre
    #  sanctionné garde son rôle, un robot du clan.
    banc.kolax.roles.remove(banc.clan)
    banc.intrus.roles += [banc.officier, banc.vip]
    asyncio.run(affiches.definir_metiers(g, banc.mira, ["thieving", "fishing"], FONDATEUR))
    bob = g.membre(11111, "Bob", banc.clan, voleur)
    puni = g.membre(22222, "Puni", cuisinier)
    banc.sanctionnes = {puni.id}
    banc.robot.roles.append(cuisinier)
    bilan = asyncio.run(metiers.reconcilier(g))
    assert cuisinier not in banc.kolax.roles and banc.officier not in banc.intrus.roles and banc.vip in banc.intrus.roles
    assert {"Voleur", "Pêcheur"} <= {r.name for r in banc.mira.roles}, "son nouveau métier : rôle créé et donné"
    assert voleur in bob.roles, "sans affiche, rien n'est décidé pour lui"
    assert cuisinier in puni.roles and cuisinier in banc.robot.roles, "sanction en cours, robot : jamais touchés"
    assert (bilan["actif"], bilan["retires"], bilan["anciens"], bilan["rendus"], bilan["membres"], bilan["crees"],
            bilan["sanctions"]) == (True, 2, 2, 1, 1, 1, 1)
    ligne = next(x for t, x, _k in banc.journal if t == "clan.roles_reconciliation")
    assert ligne == ("Rôles du clan remis en ordre : 2 rôle(s) retiré(s) à 2 ancien(s) membre(s), 1 rôle(s) de métier "
                     "donné(s), 1 membre(s) du clan remis à jour, 1 membre(s) sous sanction laissé(s) tel(s) quel(s)")
    assert banc.conf[metiers.CLE_BILAN]["retires"] == 2 and banc.conf[metiers.CLE_BILAN]["quand"] > 0
    #  Deuxième passage : tout est juste — aucun appel à Discord, aucune ligne au journal.
    n = sum(len(m.ajouts) + len(m.retraits) for m in g.members)
    lignes = len(banc.journal)
    bilan = asyncio.run(metiers.reconcilier(g))
    assert (bilan["retires"], bilan["rendus"]) == (0, 0) and sum(len(m.ajouts) + len(m.retraits) for m in g.members) == n
    assert len(banc.journal) == lignes


def test_M8b_reconciliation_attribution_non_et_sans_role_du_clan(banc):
    banc.choisir(banc.kolax, "cooking")
    cuisinier = banc.role_nomme("Cuisinier")
    banc.conf[metiers.CLE_AUTO] = False
    asyncio.run(affiches.definir_metiers(banc.g, banc.mira, ["cooking"], FONDATEUR))
    banc.intrus.roles.append(cuisinier)
    bilan = asyncio.run(metiers.reconcilier(banc.g))
    assert cuisinier not in banc.intrus.roles and cuisinier not in banc.mira.roles, "NON : retirés, jamais rendus"
    assert (bilan["retires"], bilan["rendus"]) == (1, 0)
    del banc.conf[rellseas_panneau.CLE_ROLE_CIBLE]
    banc.intrus.roles.append(cuisinier)
    bilan = asyncio.run(metiers.reconcilier(banc.g))
    assert not bilan["actif"] and cuisinier in banc.intrus.roles, "sans rôle du clan réglé : rien n'est touché"


def test_M8c_une_panne_persistante_n_ecrit_qu_une_ligne(banc):
    banc.choisir(banc.kolax, "cooking")
    cuisinier = banc.role_nomme("Cuisinier")
    cuisinier.position = 80                                   # passé au-dessus du bot : il ne peut plus le donner
    banc.kolax.roles.remove(cuisinier)
    for _ in range(3):
        asyncio.run(metiers.reconcilier(banc.g))
    assert banc.types_journal().count("clan.metiers_erreur") == 1, "la même panne : une ligne, pas une toutes les 30 min"


# ═══════════════════════════════════════════════════════════════════════════════
#  M9 — les adresses du site et leurs droits
# ═══════════════════════════════════════════════════════════════════════════════

def test_M9_adresses_reglages_installer_reconcilier_et_droits(banc):
    g = banc.g
    avec, direction = banc.biscuit(), banc.biscuit(DIRECTION)
    intrus = banc.biscuit(9)

    async def post(c, api, corps, h=avec):
        return await _json(await c.post(f"/tableau/espace/api/{api}", json=corps, headers=h))

    async def scenario(c):
        out = {"lire": await _json(await c.get("/tableau/espace/api/rell/metiers/reglages", headers=avec))}
        out["anonyme"] = (await c.get("/tableau/espace/api/rell/metiers/reglages")).status
        out["intrus"] = (await c.post("/tableau/espace/api/rell/metiers/reglages", json={"auto": False},
                                      headers=intrus)).status
        out["regler"] = await post(c, "rell/metiers/reglages", {"auto": False, "max_metiers": 3,
                                                                "rattaches": [str(banc.officier.id)]})
        out["refus"] = [await post(c, "rell/metiers/reglages", corps) for corps in (
            {"max_metiers": 6}, {"max_metiers": 0}, {"auto": "oui"}, {"rattaches": [str(banc.mod.id)]},
            {"rattaches": [str(banc.clan.id)]}, {"rattaches": [str(banc.haut.id)]}, {"rattaches": ["abc"]},
            {"rattaches": ["123456"]}, {"rattaches": "12"}, {})]
        out["installer"] = await post(c, "rell/metiers/installer", {}, direction)
        out["encore"] = await post(c, "rell/metiers/installer", {})
        out["lire2"] = await _json(await c.get("/tableau/espace/api/rell/metiers/reglages", headers=avec))
        out["hors_ligne"] = await _json(await c.post("/tableau/espace/sync", json={"ops": [
            {"op_id": "op-metiers-1", "api": "rell/metiers/reglages", "corps": {"auto": True}},
            {"op_id": "op-metiers-2", "api": "rell/metiers/reconcilier", "corps": {}}]}, headers=avec))
        banc.intrus.roles.append(banc.officier)
        out["reconcilier"] = await post(c, "rell/metiers/reconcilier", {})
        return out
    out = banc.http(scenario)
    st, lu = out["lire"]
    assert st == 200 and (lu["auto"], lu["max_metiers"], lu["rattaches"], lu["icones_roles"], lu["actif"]) == \
        (True, 2, [], False, True)
    assert lu["role_clan"] == {"id": "20", "nom": "GoRPC", "couleur": "#1f4e5a", "position": 4}
    assert [r["nom"] for r in lu["roles_disponibles"]] == ["Officier", "VIP", "Membre"], \
        "ni le clan, ni la modération, ni une intégration, ni au-dessus du bot, ni @everyone"
    assert set(lu["roles_disponibles"][0]) == {"id", "nom", "couleur", "position"}
    assert [(m["cle"], m["role_nom"], m["actif"], m["role"]) for m in lu["metiers"]][:2] == \
        [("cooking", "Cuisinier", True, None), ("thieving", "Voleur", True, None)]
    assert out["anonyme"] == 403 and out["intrus"] == 403
    st, rep = out["regler"]
    assert st == 200 and (rep["auto"], rep["max_metiers"], rep["rattaches"]) == (False, 3, [str(banc.officier.id)])
    assert banc.conf[metiers.CLE_AUTO] is False and banc.conf[metiers.CLE_MAX] == 3 and \
        banc.conf[metiers.CLE_RATTACHES] == [banc.officier.id]
    assert [x[0] for x in out["refus"]] == [400] * 10
    assert [x[1].get("champ") for x in out["refus"][:9]] == ["max_metiers", "max_metiers", "auto"] + ["rattaches"] * 6
    assert "modération" in out["refus"][3][1]["erreur"] and "rôle du clan" in out["refus"][4][1]["erreur"]
    st, inst = out["installer"]
    assert st == 200 and [x["nom"] for x in inst["crees"]] == ["Cuisinier", "Voleur", "Pêcheur", "Médecin", "Harponnage"]
    assert set(inst) == {"ok", "crees", "message"}, "les comptes que lit la page, sans zéro ni liste vide"
    assert inst["message"].startswith("Attribution automatique sur NON") and not any(c.isdigit() for c in inst["message"])
    assert "Charpentier naval" not in [r.name for r in g._roles.values()], "un métier retiré n'a pas de rôle"
    ordre = g.ordre()
    i = ordre.index("GoRPC")
    assert ordre[i + 1:i + 6] == ["Cuisinier", "Voleur", "Pêcheur", "Médecin", "Harponnage"], \
        "sous le rôle du clan, dans l'ordre du catalogue"
    assert not any(m.ajouts for m in g.members), "installés, donnés à personne"
    st, encore = out["encore"]
    assert st == 200 and "crees" not in encore and len(encore["deja"]) == 5
    assert [m["role"]["nom"] for m in out["lire2"][1]["metiers"] if m["role"]][:2] == ["Cuisinier", "Voleur"]
    assert [x["status"] for x in out["hors_ligne"][1]["resultats"]] == [400, 400], "jamais rejoué hors ligne"
    st, rec = out["reconcilier"]
    assert st == 200 and rec["bilan"] == {"verifies": 5, "retires": 1} and banc.officier not in banc.intrus.roles,         "le bilan dans les mots de la page (vérifiés, retirés…), sans zéro"
    assert rec["detail"]["anciens"] == 1 and rec["message"] == ""
    site = [x["texte"] for x in asyncio.run(registre.lire(1, 200)) if x["categorie"] == "Site"]
    assert any(t.startswith("Rôles & métiers : attribution automatique NON, 3 métier(s) au plus") for t in site)
    assert any(t.startswith("Rôles des métiers installés : 5 créé(s), 0 relié(s), 0 déjà là, 0 donné(s)") for t in site)
    assert banc.guides, "le guide du clan se réécrit (la liste suit les réglages)"


def test_M9b_sans_role_du_clan_ni_module_les_adresses_le_disent(banc):
    del banc.conf[rellseas_panneau.CLE_ROLE_CIBLE]
    avec = banc.biscuit()

    async def scenario(c):
        out = [await _json(await c.post(f"/tableau/espace/api/{api}", json={}, headers=avec))
               for api in ("rell/metiers/installer", "rell/metiers/reconcilier")]
        affiches.brancher_metiers(None)
        out.append(await _json(await c.get("/tableau/espace/api/rell/metiers/reglages", headers=avec)))
        return out
    installer, reconcilier, absent = banc.http(scenario)
    assert installer[0] == 409 and "rôle du clan" in installer[1]["erreur"]
    assert reconcilier[0] == 409 and "Aucun rôle du clan" in reconcilier[1]["erreur"]
    assert absent[0] == 503
    assert not banc.g.crees


def test_M9c_installer_et_creer_un_role_donnent_aussitot_a_ceux_qui_ont_le_metier(banc):
    """Ce que la page annonce (« … puis donné à ceux qui ont ce métier ») : avec l'attribution automatique, le rôle
    installé ou créé sur le site part tout de suite aux membres du clan dont l'affiche porte ce métier."""
    g, chef = banc.g, banc.chef
    asyncio.run(affiches.definir_metiers(g, banc.kolax, ["cooking", "fishing"], FONDATEUR))
    asyncio.run(affiches.definir_metiers(g, banc.mira, ["thieving"], FONDATEUR))
    asyncio.run(affiches.definir_metiers(g, banc.intrus, ["cooking"], FONDATEUR))
    banc.sanctionnes = {banc.mira.id}
    st, rep = run(metiers.route_installer(g, chef, {}, {}))
    assert st == 200 and rep["donnes"] == 2 and len(rep["crees"]) == 5 and "deja" not in rep and rep["message"] == ""
    assert {"Cuisinier", "Pêcheur"} <= {r.name for r in banc.kolax.roles}
    assert banc.role_nomme("Voleur") not in banc.mira.roles, "une sanction en cours : rien"
    assert banc.role_nomme("Cuisinier") not in banc.intrus.roles, "hors du clan : rien"
    assert not banc.kolax.retraits, "l'installation ne retire rien"
    #  « Créer le rôle… » sur le site, pour un métier ajouté plus tard : rangé sous le clan, donné tout de suite.
    banc.conf[metiers.CLE_MAX] = 3
    st, _r = run(affiches._route_element(g, chef, {}, {"type": "metier", "nom": "Plongée", "nom_en": "Diving",
                                                      "categorie": "Récolte"}))
    asyncio.run(affiches.definir_metiers(g, banc.kolax, ["cooking", "fishing", "plongee"], FONDATEUR))
    st, rep = run(affiches._route_role(g, chef, {}, {"type": "metier", "cle": "plongee", "auto": True,
                                                    "creer": {"nom": "Plongeur", "couleur": "#3F6B3A"}}))
    plongeur = banc.role_nomme("Plongeur")
    assert st == 200 and plongeur in banc.kolax.roles
    assert banc.g.ordre()[banc.g.ordre().index("GoRPC") + 1] == "Plongeur", "juste sous le rôle du clan"
    #  Attribution automatique NON : installé, donné à personne — et la réponse le dit (sans chiffre : la page l'affiche).
    banc.conf[metiers.CLE_AUTO] = False
    asyncio.run(affiches.definir_metiers(g, banc.direction, ["doctor"], FONDATEUR))
    banc.direction.roles.append(banc.clan)
    st, rep = run(metiers.route_installer(g, chef, {}, {}))
    assert st == 200 and "donnes" not in rep and banc.role_nomme("Médecin") not in banc.direction.roles
    assert rep["message"].startswith("Attribution automatique sur NON")


# ═══════════════════════════════════════════════════════════════════════════════
#  M10 — le guide du clan et son sélecteur persistant
# ═══════════════════════════════════════════════════════════════════════════════

class Fil:
    def __init__(self, fid):
        self.id, self.archived, self.cartes = fid, False, []

    def get_partial_message(self, mid):
        fil = self

        class Partiel:
            async def edit(self, **kw):
                fil.cartes.append((mid, kw))
        return Partiel()

    async def edit(self, **kw):
        self.archived = kw.get("archived", self.archived)


def test_M10_le_guide_du_clan_porte_le_choix_du_metier(banc, monkeypatch):
    g = banc.g
    fil = Fil(777)
    g.get_channel_or_thread = lambda cid: fil if int(cid) == 777 else None
    g.get_channel = lambda cid: None
    ZN.setup(cfg=banc.cfg, db_set=banc.db_set, lecteurs=lambda gg, c: [], log=lambda *a: None)
    assert ZN._section_metiers is None, "zones.setup remet le branchement à zéro"
    ZN.brancher_metiers(metiers.section_guide)
    banc.conf["clan_posts"] = {"guide": {"id": 777, "ouverture": 778}, "infos": {"id": 779}}
    monkeypatch.setitem(visuels._icones, "rell_metier_cooking", discord.PartialEmoji(name="rell_metier_cooking_v1",
                                                                              id=1300000000000004242))
    assert run(ZN.assurer_guide_clan(g))
    vue = fil.cartes[-1][1]["view"]
    selecteurs = [x for x in vue.walk_children() if isinstance(x, metiers.ChoixMetier)]
    assert len(selecteurs) == 1
    s = selecteurs[0].item
    assert s.custom_id == "mt:choix" and metiers.ChoixMetier.__discord_ui_compiled_template__.fullmatch(s.custom_id)
    assert s.placeholder == "Choisis ton métier · Pick your job" and (s.min_values, s.max_values) == (1, 2)
    assert [o.label for o in s.options] == ["Cuisinier · Cooking", "Voleur · Thieving", "Pêcheur · Fishing",
                                           "Médecin · Doctor", "Harponnage · Harpooning", "Aucun métier · No job"], \
        "les métiers ACTIFS, dans l'ordre du catalogue"
    assert s.options[0].emoji.id == 1300000000000004242 and all(o.emoji is None for o in s.options[1:]), \
        "l'émoji d'application officiel s'il existe — jamais un émoji Unicode"
    assert s.options[0].description == "Production · soutien"
    t = textes(vue)
    assert "Ton métier · Your job" in t and "jusqu'à **2** métiers" in t and "tes rôles de métier suivent" in t
    assert all(any(p.fullmatch(cid) for p in (metiers.ChoixMetier.__discord_ui_compiled_template__,)) for cid in ids(vue))
    assert all(isinstance(x, discord.ui.DynamicItem) or not x.is_dispatchable() for x in vue.walk_children()), \
        "une vue mixte effacerait, en expirant, le gabarit global"
    assert compter(vue) <= 40
    signature = banc.conf["clan_guide_v"]
    assert not run(ZN.assurer_guide_clan(g)), "rien n'a changé : pas de réécriture"
    #  Le réglage change (attribution NON, 1 métier) : la liste et son texte suivent.
    banc.conf[metiers.CLE_AUTO], banc.conf[metiers.CLE_MAX] = False, 1
    assert run(ZN.assurer_guide_clan(g)) and banc.conf["clan_guide_v"] != signature
    vue = fil.cartes[-1][1]["view"]
    s = next(x for x in vue.walk_children() if isinstance(x, metiers.ChoixMetier)).item
    assert s.max_values == 1 and "Choisis ton métier dans la liste" in textes(vue) and "la direction attribue" in textes(vue)
    #  Sans rôle du clan : pas de liste qui ment.
    del banc.conf[rellseas_panneau.CLE_ROLE_CIBLE]
    assert run(ZN.assurer_guide_clan(g))
    assert not any(isinstance(x, metiers.ChoixMetier) for x in fil.cartes[-1][1]["view"].walk_children())
    #  La base fait défaut : le guide reste tel quel (jamais réécrit sans la liste, puis avec).
    banc.conf[rellseas_panneau.CLE_ROLE_CIBLE] = banc.clan.id
    n = len(fil.cartes)

    async def panne(*_a):
        raise aiosqlite.OperationalError("database is locked")
    monkeypatch.setattr(affiches, "_catalogue", panne)
    assert not run(ZN.assurer_guide_clan(g)) and len(fil.cartes) == n


def test_M10b_un_metier_change_sur_le_site_le_guide_suit(banc):
    st, _r = run(affiches._route_element(banc.g, banc.chef, {}, {"type": "metier", "nom": "Plongée", "nom_en": "Diving",
                                                                  "categorie": "Récolte"}))
    assert st == 200 and banc.guides == [1]
    st, _r = run(affiches._route_element(banc.g, banc.chef, {}, {"type": "race", "nom": "Triton"}))
    assert st == 200 and banc.guides == [1], "une race ne touche pas au guide du clan"
    run(affiches._route_retirer_element(banc.g, banc.chef, {}, {"type": "metier", "cle": "plongee"}))
    assert banc.guides == [1, 1]


def test_M10c_le_selecteur_est_capte_au_demarrage_et_le_detecteur_est_vert():
    assert "bot.add_dynamic_items(metiers.ChoixMetier)" in SRC
    r = subprocess.run([sys.executable, str(RACINE / "outils" / "verif_boutons_persistants.py"),
                        str(RACINE / "bot.py"), str(RACINE / "zones.py"), str(RACINE / "metiers.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(RACINE))
    assert r.returncode == 0, r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════════
#  M11 — l'acceptation au clan : la carte dans le ticket, le lien dans le MP
# ═══════════════════════════════════════════════════════════════════════════════

def _source(nom):
    for n in ARBRE.body:
        cible = getattr(n, "name", None) or (getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else
                                              getattr(getattr(n, "target", None), "id", None))
        if cible == nom:
            return ast.unparse(n)
    raise AssertionError(nom)


class Ticket:
    def __init__(self):
        self.id, self.envois = 77, []

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))


def _decision(banc, **plus):
    fermetures, erreurs, journal = [], [], []
    ch = Ticket()
    tk = {"id": 5, "user": banc.intrus.id, "claimed": 0, "answers": {}, "panel_id": "p1"}

    async def ouvert(_g, _tid):
        return ch, tk

    async def fermer(*a, **k):
        fermetures.append((a, k))

    async def journaliser(_g, texte, **_k):
        journal.append(texte)

    async def rien(*_a, **_k):
        return None
    import textes as module_textes   # le registre des textes (bot.py : `import textes`) ; `textes` ici lit les vues
    ns = {"discord": discord, "asyncio": asyncio, "metiers": metiers, "rellseas_ui": rellseas_panneau, "cfg": banc.cfg,
          "textes": module_textes,
          "_ticket_ouvert": ouvert, "_fermer_ticket": fermer, "_journal_rellseas": journaliser, "log_staff_action": rien,
          "_logerr": lambda ou, ex, guild_id=0: erreurs.append((ou, type(ex).__name__))}
    ns.update(plus)
    for nom in ("_TACHES_FERMETURE", "_fermer_en_fond", "_decision_recrutement"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt

    async def scenario():
        r = await ns["_decision_recrutement"](banc.g, 5, banc.chef, True)
        await asyncio.sleep(0)
        return r
    return asyncio.run(scenario()), ch, fermetures, erreurs


def test_M11_accepte_au_clan_la_carte_du_metier_avant_la_fermeture(banc):
    banc.conf["clan_posts"] = {"guide": {"id": 777, "ouverture": 778}}
    (ok, message), ch, fermetures, erreurs = _decision(banc)
    assert ok and message == "Candidature acceptée : rôle donné, ticket fermé." and banc.clan in banc.intrus.roles
    (_c, kw), = ch.envois
    t = textes(kw["view"])
    assert "Bienvenue dans l'équipage · Welcome aboard" in t and "<@9>, dernière étape : choisis ton métier" in t
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.users is False and am.roles is False, "aucune mention qui sonne"
    boutons = [b for b in kw["view"].walk_children() if isinstance(b, discord.ui.Button)]
    assert [(b.label, b.url) for b in boutons] == [("Choisir mon métier · Pick my job", "https://discord.com/channels/1/777")]
    (args, kwf), = fermetures
    assert kwf["public"] == ("Candidature acceptée · choisis ton métier dans le guide du clan (pick your job) : "
                             "https://discord.com/channels/1/777"), "le lien suit dans le MP (le ticket part en 5 s)"
    assert args[4] == "Accepté" and not erreurs


def test_M11b_sans_guide_rien_n_est_promis_et_une_panne_ne_bloque_pas(banc, monkeypatch):
    (ok, _m), ch, fermetures, erreurs = _decision(banc)
    assert ok and not ch.envois and fermetures[0][1]["public"] == "Candidature acceptée", "pas de guide : pas de carte"

    async def panne(*_a, **_k):
        raise RuntimeError("catalogue illisible")
    banc.intrus.roles.remove(banc.clan)
    (ok, _m), ch, fermetures, erreurs = _decision(banc, metiers=Obj(inviter_au_choix=panne))
    assert ok and fermetures and fermetures[0][1]["public"] == "Candidature acceptée"
    assert erreurs == [("recrutement.metier", "RuntimeError")], "journalisée, et la fermeture suit son cours"


# ═══════════════════════════════════════════════════════════════════════════════
#  M12 — le câblage dans bot.py
# ═══════════════════════════════════════════════════════════════════════════════

def _fonction(nom):
    return next(n for n in ARBRE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def test_M12_cablage_etape_ecouteur_boucle_supervisee():
    assert "import metiers" in SRC
    boot = ast.unparse(_fonction("_activite_boot"))
    etape = boot[boot.index("with _Etape('metiers'):"):]
    etape = etape[:etape.index("with _Etape(", 10)]
    for morceau in ("metiers.setup(get_db=get_db, cfg=cfg, db_set=db_set", "rellseas_ui.CLE_ROLE_CIBLE",
                    "sanctionnes=_membres_sanctionnes", "epargnes=_a_la_tete", "_au_journal(g, 'Clan', type_, texte, **kw)",
                    "guide=zones.assurer_guide_clan", "zones.brancher_metiers(metiers.section_guide)"):
        assert morceau in etape, morceau
    for avant in ("with _Etape('affiches'):", "with _Etape('zones'):"):
        assert boot.index(avant) < boot.index("with _Etape('metiers'):"), f"leur setup remet les branchements à zéro : {avant}"
    assert 'bot.add_listener(_metiers_membre, "on_member_update")' in SRC
    boucle = _fonction("metiers_task")
    assert any("loop" in ast.unparse(d) and "minutes=30" in ast.unparse(d) for d in boucle.decorator_list)
    noms = next(ast.literal_eval(n.value) for n in ARBRE.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "_SUPERVISED_LOOP_NAMES" for t in n.targets))
    assert "metiers_task" in noms, "sans le superviseur, la boucle ne démarre jamais"
    #  Le corps de la boucle et l'écouteur : une erreur est journalisée, les autres serveurs continuent.
    vus, erreurs = [], []

    async def reconcilier(g):
        vus.append(g.id)
        if g.id == 1:
            raise RuntimeError("base verrouillée")

    async def sur_maj(_a, _b):
        raise RuntimeError("panne")
    import copy as _copie
    corps = _copie.deepcopy(boucle)
    corps.name, corps.decorator_list = "corps", []
    ns = {"bot": Obj(guilds=[Obj(id=1), Obj(id=2)]), "metiers": Obj(reconcilier=reconcilier, sur_maj_membre=sur_maj),
          "_logerr": lambda ou, ex, guild_id=0: erreurs.append((ou, type(ex).__name__, guild_id))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[corps], type_ignores=[])), "bot.py", "exec"), ns)  # noqa: S102
    exec(_source("_metiers_membre"), ns)  # noqa: S102
    asyncio.run(ns["corps"]())
    asyncio.run(ns["_metiers_membre"](Obj(), Obj(guild=Obj(id=2))))
    assert vus == [1, 2] and erreurs == [("metiers.reconciliation", "RuntimeError", 1), ("metiers.membre", "RuntimeError", 2)]
    for outil in ("verif_boucles.py", "verif_evenements.py"):
        r = subprocess.run([sys.executable, str(RACINE / "outils" / outil), str(RACINE / "bot.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(RACINE))
        assert r.returncode == 0, outil + r.stdout + r.stderr


# ═══════════════════════════════════════════════════════════════════════════════
#  M13 — les membres sous sanction (bot.py)
# ═══════════════════════════════════════════════════════════════════════════════

def test_M13_membres_sanctionnes_par_la_base_ou_par_le_role(tmp_path):
    get_db = _base(tmp_path / "bot.db")
    g = Serveur()

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE radiated_members (guild_id INTEGER, user_id INTEGER, saved_roles TEXT)")
            await db.execute("CREATE TABLE isolements (guild_id INTEGER, user_id INTEGER, saved_roles TEXT)")
            await db.executemany("INSERT INTO radiated_members VALUES (?,?,'[]')", [(1, 101), (2, 999)])
            await db.execute("INSERT INTO isolements VALUES (1, 102, '[]')")
            await db.commit()
    asyncio.run(preparer())
    radie, quarantaine, restreint = g.role(60, "🚫 Radié", 1), g.role(61, "Vérification", 1), g.role(62, "🔒 Restricted", 1)
    for uid, role in ((103, radie), (104, quarantaine), (105, restreint), (106, None)):
        g.membre(uid, f"M{uid}", *([role] if role else []))
    ns = {"get_db": get_db, "aiosqlite": aiosqlite, "_RADIE_ROLE_NAME": "🚫 Radié",
          "_QUARANTINE_ROLE_NAMES": ("vérification", "verification", "verify", "quarantaine")}
    exec(_source("_membres_sanctionnes"), ns)  # noqa: S102
    assert asyncio.run(ns["_membres_sanctionnes"](g)) == {101, 102, 103, 104, 105}, \
        "la fiche de ce serveur (pas d'un autre), ou le rôle de la sanction ; une table absente : personne"


# ═══════════════════════════════════════════════════════════════════════════════
#  M14 — une affiche enregistrée sur le site, « Appliquer »
# ═══════════════════════════════════════════════════════════════════════════════

def test_M14_affiche_du_site_et_appliquer_suivent_le_clan(banc):
    g, chef = banc.g, banc.chef
    st, rep = asyncio.run(affiches._route_affiche(g, chef, {}, {"membre_id": "8", "surnom": "L'Écume",
                                                                 "attributs": {"metier": ["fishing"]}}))
    pecheur = banc.role_nomme("Pêcheur")
    assert st == 200 and pecheur in banc.mira.roles and rep["roles"]["ajoutes"] == [{"id": str(pecheur.id), "nom": "Pêcheur"}]
    assert rep["roles"]["crees"] == [{"id": str(pecheur.id), "nom": "Pêcheur"}]
    #  Hors du clan : son affiche peut porter un métier, mais il n'en porte pas le rôle.
    banc.intrus.roles.append(pecheur)
    st, rep = asyncio.run(affiches._route_affiche(g, chef, {}, {"membre_id": "9", "attributs": {"metier": ["fishing"]}}))
    assert st == 200 and pecheur not in banc.intrus.roles and rep["roles"]["retires"][0]["nom"] == "Pêcheur"
    #  « Appliquer » : la même règle (et N métiers au plus).
    banc.intrus.roles.append(pecheur)
    a = banc.affiche(banc.intrus)
    st, rep = asyncio.run(affiches._route_appliquer(g, chef, {}, {"affiche_id": a["id"]}))
    assert st == 200 and pecheur not in banc.intrus.roles
    banc.sanctionnes = {banc.mira.id}
    banc.mira.roles.remove(pecheur)
    a = banc.affiche(banc.mira)
    st, rep = asyncio.run(affiches._route_appliquer(g, chef, {}, {"affiche_id": a["id"]}))
    assert st == 200 and pecheur not in banc.mira.roles and rep["message"].startswith("Rien à changer"), \
        "une sanction en cours : ses rôles de métier ne bougent pas"
    #  Les liens « automatiques » des autres types gardent leur règle d'avant.
    humain = g.role(14, "Humain", 1)
    asyncio.run(affiches._route_role(g, chef, {}, {"type": "race", "cle": "humain", "role_id": str(humain.id), "auto": True}))
    banc.sanctionnes = set()
    st, rep = asyncio.run(affiches._route_affiche(g, chef, {}, {"id": a["id"], "version": a["version"], "membre_id": "8",
                                                                 "attributs": {"metier": ["fishing"], "race": ["humain"]}}))
    assert st == 200 and humain in banc.mira.roles and pecheur in banc.mira.roles


# ═══════════════════════════════════════════════════════════════════════════════
#  M15 — deux garde-fous : le rôle du clan n'est jamais le rôle d'un métier ; la tête n'est jamais dépouillée
# ═══════════════════════════════════════════════════════════════════════════════

def test_M15_le_role_du_clan_n_est_jamais_le_role_d_un_metier(banc):
    st, rep = asyncio.run(affiches._route_role(banc.g, banc.chef, {}, {"type": "metier", "cle": "cooking",
                                                                        "role_id": str(banc.clan.id)}))
    assert (st, rep["champ"]) == (400, "role_id") and "rôle du clan" in rep["erreur"]
    #  Lié quand même (une base d'avant) : changer de métier ne sort jamais le membre du clan.
    async def lier():
        async with banc.get_db() as db:
            await db.execute("INSERT INTO rell_roles (guild_id, type, cle, role_id, auto) VALUES (1, 'metier', 'cooking',"
                             " ?, 1)", (banc.clan.id,))
            await db.commit()
    asyncio.run(lier())
    i = banc.choisir(banc.kolax, "fishing")
    assert banc.clan in banc.kolax.roles and banc.role_nomme("Pêcheur") in banc.kolax.roles
    i = banc.choisir(banc.mira, "cooking")
    assert banc.clan in banc.mira.roles and "un rôle n'a pas pu être posé" in avis(i)


def test_M15b_le_fondateur_et_la_direction_ne_sont_jamais_depouilles(banc):
    banc.conf[metiers.CLE_RATTACHES] = [banc.officier.id]
    banc.chef.roles += [banc.clan, banc.officier]
    banc.choisir(banc.chef, "cooking")
    cuisinier = banc.role_nomme("Cuisinier")
    _quitte(banc, banc.chef, banc.clan)
    assert cuisinier in banc.chef.roles and banc.officier in banc.chef.roles, "le départ du clan : rien ne lui est retiré"
    banc.direction.roles += [banc.officier, cuisinier]
    bilan = asyncio.run(metiers.reconcilier(banc.g))
    assert banc.officier in banc.direction.roles and cuisinier in banc.direction.roles and bilan["retires"] == 0
    a = banc.affiche(banc.chef)
    st, rep = asyncio.run(affiches._route_appliquer(banc.g, banc.chef, {}, {"affiche_id": a["id"]}))
    assert st == 200 and cuisinier in banc.chef.roles, "« Appliquer » non plus"


def test_M10d_installer_la_zone_du_clan_pose_le_guide_avec_le_choix_du_metier(tmp_path):
    """Le vrai chemin : `zones.installer_clan` crée le forum du clan et ses posts, puis le guide — avec la liste."""
    from conftest_discord import base
    from faux_serveur import Monde
    get_db, cfg, db_set, conf = base(tmp_path)
    g = Monde()
    g.categorie("🦜 · GoRp_SEA")
    clan = run(g.create_role(name="GoRPC"))
    conf[rellseas_panneau.CLE_ROLE_CIBLE] = clan.id
    affiches.setup(get_db=get_db, log=lambda *a: None)
    metiers.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None,
                  role_clan=lambda gg, c: gg.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0)))
    ZN.setup(cfg=cfg, db_set=db_set, lecteurs=lambda gg, c: [], log=lambda *a: None)
    ZN.brancher_metiers(metiers.section_guide)
    depart = tmp_path / "catalogue.json"
    depart.write_text(json.dumps(CATALOGUE, ensure_ascii=False), encoding="utf-8")

    async def preparer():
        await affiches.init_db()
        await affiches.charger_depart(depart)
    asyncio.run(preparer())
    run(ZN.installer_clan(g, clan, []))
    guide = conf["clan_posts"]["guide"]
    fil = g.fils[guide["id"]]
    vue = [k for mid, k in fil.cartes if mid == guide["ouverture"]][-1]["view"]
    assert sum(isinstance(x, metiers.ChoixMetier) for x in vue.walk_children()) == 1
    assert "Ton métier · Your job" in textes(vue) and compter(vue) <= 40
    assert conf["clan_guide_v"].startswith(f"{ZN.GUIDE_CLAN_VERSION}|") and "|m" in conf["clan_guide_v"]
