"""19/10/2026 : « la direction et le fondateur peuvent ajouter le rôle RILSI… filtrer tout le serveur
ou rechercher une personne… soit via le panel, soit via la commande… ping dans un salon spécifique ou
un message en privé : attention, vous êtes inactif, vous allez être expulsé du clan d'ici une
semaine… le site va nous rappeler… et proposer la sanction : retirer le rôle »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord

import activite_calendrier as cal
import clan
import rellseas_panneau
from conftest_discord import Obj
from ui_v2 import LayoutView, Palette

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
JOUR = 86400


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise KeyError(nom)


def _base(tmp_path):
    chemin = tmp_path / "k.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    clan.setup(get_db=get_db, log=lambda *a: None)
    asyncio.run(clan.init_db())
    return get_db


def test_K1_rappel_echu_revenu_retire_annule(tmp_path):
    _base(tmp_path)
    t0 = time.time() - 8 * JOUR
    asyncio.run(clan.prevenir(1, [10, 11, 12, 13], 3, "mp", maintenant=t0))
    jour_rappel = cal.jour(datetime.fromtimestamp(t0, timezone.utc))
    r = asyncio.run(clan.rappels(1, {10: "2020-01-01", 11: jour_rappel}, {10, 11, 13}))
    assert r[10]["statut"] == "echu", "une semaine passée, toujours inactif : à décider"
    assert r[11]["statut"] == "revenu", "actif le jour du rappel ou après : résolu seul"
    assert r[12]["statut"] == "retire", "sorti du clan entre-temps"
    asyncio.run(clan.clore(1, 13, "annule", 3))
    r = asyncio.run(clan.rappels(1, {}, {10, 11, 13}))
    assert 13 not in r and r[11]["statut"] == "revenu", "un rappel annulé disparaît ; un statut résolu reste"
    asyncio.run(clan.prevenir(1, [10], 3, "salon", 77))
    r = asyncio.run(clan.rappels(1, {}, {10}))
    assert r[10]["statut"] == "en_attente" and r[10]["mode"] == "salon" and r[10]["salon"] == 77, "le nouveau rappel remplace l'ancien"


def test_K2_chercher_dans_tout_le_serveur():
    def m(uid, nom, pseudo, jours, bot=False):
        return Obj(id=uid, display_name=nom, name=pseudo, bot=bot, joined_at=datetime.now(timezone.utc) - timedelta(days=jours))
    gens = [m(1, "Mira", "mira_rs", 3), m(2, "Kolax", "kolax", 1), m(3, "Mirabelle", "belle", 9), m(4, "Bot", "bot", 1, bot=True),
            m(5, "Amira", "amira", 2)]
    assert [x.id for x in clan.chercher(gens, "", {2})] == [5, 1, 3, 2], "hors clan d'abord, arrivées récentes ensuite"
    assert [x.id for x in clan.chercher(gens, "mira", set())] == [1, 3, 5], "le nom qui commence par la recherche d'abord"
    assert [x.id for x in clan.chercher(gens, "3", set())] == [3] and not clan.chercher(gens, "bot", set())


class Membre:
    def __init__(self, uid, haut=5, roles=(), mp=True):
        self.id, self.top_role, self.roles, self.bot, self._mp = uid, haut, list(roles), False, mp
        self.display_name, self.mention, self.mps = f"M{uid}", f"<@{uid}>", []

    def __str__(self):
        return self.display_name

    async def add_roles(self, role, reason=None):
        self.roles.append(role)

    async def send(self, view=None, **kw):
        if not self._mp:
            raise discord.Forbidden(Obj(status=403, reason="x"), "MP fermés")
        self.mps.append(view)


class Salon(discord.TextChannel):
    def __init__(self):
        self.id, self.name, self.envois = 77, "chat-gorpsea", []

    def permissions_for(self, _m):
        return Obj(send_messages=True)

    async def send(self, content=None, **kw):
        self.envois.append((content, kw))


class Role(int):
    name = "Rell Seas"


CLAN = Role(50)


def _monde(tmp_path, membres):
    _base(tmp_path)
    journal, suivis = [], []
    conf = {rellseas_panneau.CLE_ROLE_CIBLE: CLAN}
    salon = Salon()

    async def cfg(_g):
        return conf

    async def noter(*a, **k):
        journal.append((a, k))

    async def immunise(_m):
        return False

    async def suivi(gid, uid):
        suivis.append(uid)

    async def dormir(_s):
        return None
    g = Obj(id=1, name="GoRP SEA", owner_id=99, me=Obj(top_role=60, guild_permissions=Obj(manage_roles=True)),
            get_member=membres.get, get_role=lambda rid: CLAN if rid == CLAN else None,
            get_channel=lambda cid: salon if cid == 77 else None)
    ns = {"cfg": cfg, "discord": discord, "rellseas_ui": Obj(CLE_ROLE_CIBLE=rellseas_panneau.CLE_ROLE_CIBLE, _marquer_suivi=suivi),
          "owner_ids_module": Obj(is_super_owner=lambda uid: False), "is_fully_immune": immunise, "TETE_IDS": frozenset(),
          "_direction_ou_plus": lambda _g, m, _c: m.id in (3, 99), "_logerr": lambda *a, **k: None,
          "_journal_rellseas": noter, "log_staff_action": noter, "_au_journal": noter, "clan": clan, "time": time,
          "LayoutView": LayoutView, "Palette": Palette, "asyncio": Obj(sleep=dormir), "_heure_courte": lambda t: "26/10 20:00"}
    for nom in ("_cible_site", "_action_clan_ajouter", "_action_clan_prevenir", "_action_clan_rappel_annuler"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    return ns, g, salon, journal, suivis


def test_K3_ajouter_au_clan_seulement_ce_role(tmp_path):
    gens = {3: Membre(3, haut=30), 7: Membre(7), 8: Membre(8, roles=[CLAN]), 9: Membre(9, haut=35), 99: Membre(99, haut=50)}
    ns, g, _s, journal, suivis = _monde(tmp_path, gens)
    faire = lambda uid: asyncio.run(ns["_action_clan_ajouter"](g, gens[3], {"membre": uid}))
    ok, msg = faire(7)
    assert ok and gens[7].roles == [CLAN] and suivis == [7] and "rejoint le clan" in msg
    assert faire(8) == (False, "M8 est déjà dans le clan.")
    assert not faire(99)[0] and not faire(9)[0], "jamais le fondateur, jamais un rôle au-dessus de l'auteur"
    source = _source("_action_clan_ajouter")
    assert source.count("add_roles(") == 1 and "CLE_ROLE_CIBLE" in source, "le seul rôle que le site donne : celui du clan"


def test_K4_prevenir_par_message_prive_ou_ping(tmp_path):
    gens = {3: Membre(3, haut=30, roles=[CLAN]), 10: Membre(10, roles=[CLAN]), 11: Membre(11, roles=[CLAN], mp=False),
            12: Membre(12)}
    ns, g, salon, journal, _ = _monde(tmp_path, gens)
    ok, msg = asyncio.run(ns["_action_clan_prevenir"](g, gens[3], {"membres": [10, 11, 12, 3], "mode": "mp"}))
    texte = " ".join(c.content for c in gens[10].mps[0].walk_children() if isinstance(c, discord.ui.TextDisplay))
    assert "Attention, vous êtes inactif : vous allez être expulsé du clan d'ici une semaine" in texte
    assert ok and msg.startswith("2 membre(s) prévenu(s)") and "1 message(s) privé(s) refusé(s)" in msg
    r = asyncio.run(clan.rappels(1, {}, {10, 11}))
    assert set(r) == {10, 11} and r[10]["remis"] and not r[11]["remis"], "hors clan et direction : jamais prévenus"
    ok, msg = asyncio.run(ns["_action_clan_prevenir"](g, gens[3], {"membres": [10, 11], "mode": "salon", "salon": 77}))
    (contenu, kw), = salon.envois
    #  24/10/2026 (revue) : une carte V2, la mention dans la carte.
    texte = " ".join(c.content for c in kw["view"].walk_children() if isinstance(c, discord.ui.TextDisplay))
    assert contenu is None and ok and texte.startswith("<@10> <@11>") and "vous serez expulsés du clan" in texte
    assert kw["allowed_mentions"].everyone is False and kw["allowed_mentions"].roles is False
    assert asyncio.run(ns["_action_clan_prevenir"](g, gens[3], {"membres": [10], "mode": "salon", "salon": 5}))[0] is False
    assert asyncio.run(ns["_action_clan_rappel_annuler"](g, gens[3], {"membre": 10}))[0]
    assert 10 not in asyncio.run(clan.rappels(1, {}, {10, 11}))


def test_K5_branchements():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "_direction_ou_plus(i.guild, i.user, c)" in _source("_rellseas_autorise"), "/rellseas : la direction aussi"
    assert '"clan_ajouter": _action_clan_ajouter' in src and '"clan_prevenir": _action_clan_prevenir' in src
    assert "await clan.clore(g.id, membre.id, 'retire', auteur.id)" in _source("_retirer_du_clan")
    assert "tableau:recherche" in (RACINE / "health_server.py").read_text(encoding="utf-8")
    page = (RACINE / "tableau_page.html").read_text(encoding="utf-8")
    assert 'action: "clan_ajouter"' in page and '"clan_prevenir"' in page and "À décider" in page and "/recherche?q=" in page
    import tableau
    assert tableau._genre_grave("clan_ajouter", {}) == ("roles", 1)
    assert tableau._genre_grave("clan_prevenir", {"membres": [1, 2]}) == ("rappels", 2)


def test_K6_pas_de_badge_d_activite_hors_du_clan():
    """Audit 3 #6 : l'activite n'est suivie que pour le clan ; hors du clan, le badge disait « Jamais vu »."""
    import ast as _a
    from pathlib import Path as _P
    arbre = _a.parse((_P(__file__).resolve().parent.parent / "tableau.py").read_text(encoding="utf-8"))
    corps = _a.unparse(next(n for n in arbre.body if getattr(n, "name", "") == "recherche"))
    assert "_mesurer_groupe(g.id, du_clan)" in corps and "lignes_clan(du_clan, mesures)" in corps
    assert "lignes.get(m.id, {}).get('statut')" in corps
