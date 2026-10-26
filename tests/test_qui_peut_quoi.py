"""Qui peut quoi sur Discord (26/10/2026, sécurité) — chaque trou PROUVÉ par un test qui échouait avant sa correction.

« Si tu vois qu'il y a quelqu'un d'autre qui a le bouton pour modifier, ajouter des rôles, alors qu'il n'est pas censé
l'avoir, […] tu dois t'assurer déjà qu'il ne puisse pas. » Chaque clic et chaque commande est revérifié côté bot ; les
corrections n'enlèvent rien à ceux qui y ont droit (chaque test vérifie aussi que le bon niveau garde son outil).

Q1 /bouclier : la garde vit dans le code (administrateurs, propriétaire, tête), pas seulement dans l'affichage.
Q2 /off : un administrateur respecte la hiérarchie ; seul le fondateur radie la direction.
Q3 /mod undirection : on ne rend que des rôles plus bas que le sien.
Q4 panneau de sanction du staff : ni soi-même, ni la tête, ni un rang égal ou supérieur.
Q5 recours « Bannir définitivement » : seulement un membre encore radié, hiérarchie comprise.
Q6 « Annuler » la configuration des salons : « Gérer le serveur » seul ne suffit plus.
Q7 /rellseas : ni retirer le rôle du clan à la tête, ni le donner à un radié.
Q8 « Gérer le casier » : jamais son propre casier, ni celui d'un rang égal ou supérieur.
Q9 site (Capitainerie) : les rôles du fondateur ne se changent pas depuis la session de la direction.
Q10 lever une radiation (/off off, bouton du recours) : la hiérarchie d'AVANT la radiation, administrateurs compris ;
    la direction radiée ne se relève que par le fondateur.
Q11 « Bannir définitivement » un recours : la hiérarchie d'avant la radiation (radié, il ne lui reste que « Radié »).
Q12 jamais le rôle du clan à un membre sanctionné (radié, isolé, restreint) : ni « Accepter » une candidature, ni
    /rellseas « Donner ».
Q13 /mod unmute ne défait pas une restriction de la direction (/mod direction) : elle se lève par /mod undirection.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from pathlib import Path

import aiosqlite
import discord
import pytest

from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION = 781205382923288593, 827633340797681714
TETE = frozenset({FONDATEUR, DIRECTION})
#  La table des radiés telle que bot.py la crée (`_radier_membre`, colonne `saved_nick` ajoutée ensuite).
SCHEMA_RADIES = ("CREATE TABLE IF NOT EXISTS radiated_members (guild_id INTEGER, user_id INTEGER, saved_roles TEXT,"
                 " reason TEXT, by_user_id INTEGER, radiated_at DATETIME DEFAULT CURRENT_TIMESTAMP, saved_nick TEXT,"
                 " appel_utilise INTEGER DEFAULT 0, PRIMARY KEY (guild_id, user_id))")


def _noeud(nom):
    return next((n for n in ARBRE.body if getattr(n, "name", None) == nom), None)


def _charger(ns: dict, *noms, optionnels=()) -> dict:
    """Le code de bot.py (fonctions et classes de premier niveau), exécuté dans `ns` : le VRAI code, des faux autour."""
    for nom in noms:
        n = _noeud(nom)
        assert n is not None, f"{nom} absent de bot.py"
        exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    for nom in optionnels:
        n = _noeud(nom)
        if n is not None:
            exec(ast.unparse(n), ns)  # noqa: S102
    return ns


# ─── Les faux ────────────────────────────────────────────────────────────────

class Role:
    def __init__(self, rid, nom, position, permissions=None, managed=False):
        self.id, self.name, self.position, self.managed = rid, nom, position, managed
        self.permissions = permissions or discord.Permissions.none()
        self.mention = f"<@&{rid}>"
        self.members = []

    def is_default(self):
        return self.position == 0

    def is_assignable(self):
        return not self.managed and 0 < self.position < 90

    def __lt__(self, o):
        return self.position < o.position

    def __le__(self, o):
        return self.position <= o.position

    def __gt__(self, o):
        return self.position > o.position

    def __ge__(self, o):
        return self.position >= o.position

    __hash__ = object.__hash__

    def __eq__(self, o):
        return self is o


TOUS = Role(1, "@everyone", 0)


class Membre:
    def __init__(self, uid, *roles, perms=None, nom=None):
        self.id, self.bot = uid, False
        self.display_name = self.name = nom or f"membre{uid}"
        self.mention = f"<@{uid}>"
        self.roles = [TOUS, *roles]
        self.guild_permissions = perms or discord.Permissions.none()
        self.ajouts, self.retraits, self.exclusions = [], [], []
        self.display_avatar = Obj(url="https://cdn.discordapp.com/embed/avatars/0.png")

    @property
    def top_role(self):
        return max(self.roles, key=lambda r: r.position)

    async def add_roles(self, *roles, reason=None):
        self.ajouts += [r.id for r in roles]
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.retraits += [r.id for r in roles]
        self.roles = [r for r in self.roles if r not in roles]

    async def timeout(self, quand, reason=None):
        self.exclusions.append(quand)

    def is_timed_out(self):
        return bool(self.exclusions) and self.exclusions[-1] is not None

    async def edit(self, **kw):
        return None

    async def send(self, *a, **k):
        return None


class Serveur:
    def __init__(self, *membres, roles=()):
        self.id, self.name, self.owner_id = 1, "GoRP SEA", FONDATEUR
        self.default_role = TOUS
        self._roles = {r.id: r for r in (TOUS, *roles)}
        self._membres = {m.id: m for m in membres}
        self.me = Membre(999, Role(998, "GoRP Bot", 95), perms=discord.Permissions.all())
        self.bannis = []

    roles = property(lambda self: sorted(self._roles.values(), key=lambda r: r.position))

    def get_role(self, rid):
        return self._roles.get(int(rid or 0))

    def get_member(self, uid):
        return self._membres.get(int(uid or 0))

    async def ban(self, objet, **kw):
        self.bannis.append(int(objet.id))


class Reponse:
    def __init__(self):
        self.messages, self.fait = [], False

    async def defer(self, **kw):
        self.fait = True

    async def send_message(self, *a, **kw):
        self.messages.append(a[0] if a else kw)
        self.fait = True

    async def edit_message(self, **kw):
        self.messages.append(kw)
        self.fait = True

    def is_done(self):
        return self.fait


class Suivi:
    def __init__(self):
        self.messages = []

    async def send(self, *a, **kw):
        self.messages.append(a[0] if a else kw)


class Interaction:
    def __init__(self, g, user, **kw):
        self.guild, self.user = g, user
        self.response, self.followup = Reponse(), Suivi()
        self.channel = kw.get("channel")
        self.message = kw.get("message")
        self.data = kw.get("data")

    def textes(self):
        return " ".join(str(x) for x in self.response.messages + self.followup.messages)


def _base(chemin):
    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    return get_db


def _ns(**kw) -> dict:
    """L'entourage commun du code de bot.py : discord, la tête, le fondateur."""
    async def cfg(_gid):
        return kw.pop("_conf", None) or {}

    def logerr(*_a, **_k):
        return None
    ns = {"discord": discord, "asyncio": asyncio, "json": json, "TETE_IDS": TETE, "SUPER_OWNER_ID": FONDATEUR,
          "owner_ids_module": Obj(is_super_owner=lambda u: int(u) == FONDATEUR), "_logerr": logerr, "cfg": cfg,
          "visuels": Obj(icone=lambda *_a: None), "Button": discord.ui.Button, "_RADIE_ROLE_NAME": "🚫 Radié",
          "_QUARANTINE_ROLE_NAMES": ("vérification", "verification", "verify", "quarantaine")}
    ns.update(kw)
    return ns


# ═══════════════════════════════════════════════════════════════════════════════
#  Q1 — /bouclier
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q1_bouclier_reserve_aux_administrateurs_dans_le_code():
    """Le trou : `default_permissions` ne règle que l'AFFICHAGE ; un administrateur peut ouvrir la commande à n'importe
    quel rôle (Paramètres → Intégrations) — et le code ne vérifiait rien : verrouiller tout le serveur, ou lever le
    bouclier en plein raid."""
    faits = []

    async def verrouiller(g):
        faits.append("verrou")
        return 3

    async def rouvrir(g):
        faits.append("ouverture")
        return 3, 0

    async def lockdown(g, n):
        return {"invites_disabled": True}

    async def fin_lockdown(g):
        return True

    async def journal(*a, **k):
        return None

    class Groupe:
        def command(self, **kw):
            return lambda f: f
    ns = _charger(_ns(_shield_lock=verrouiller, _shield_unlock=rouvrir, bouclier_group=Groupe(), bot=None,
                      raid_module=Obj(run_lockdown=lockdown, end_lockdown=fin_lockdown),
                      ulogger2026=Obj(log_event=journal, EventType=Obj(SEC_ESCALATION="x"))),
                  "bouclier_on", "bouclier_off", optionnels=("_refus_bouclier",))
    modo = Membre(5, Role(40, "Modération", 40), perms=discord.Permissions(manage_messages=True, kick_members=True))
    admin = Membre(6, Role(41, "Admin", 60), perms=discord.Permissions(administrator=True))
    g = Serveur(modo, admin)

    async def scenario(qui):
        i_on, i_off = Interaction(g, qui), Interaction(g, qui)
        await ns["bouclier_on"](i_on)
        await ns["bouclier_off"](i_off)
        return i_on.textes() + " " + i_off.textes()
    refus = asyncio.run(scenario(modo))
    assert faits == [], "un modérateur à qui l'on a ouvert la commande ne verrouille ni ne lève rien"
    assert "administrateurs" in refus
    asyncio.run(scenario(admin))
    assert faits == ["verrou", "ouverture"], "un administrateur garde son bouclier"
    for nom in ("bouclier_on", "bouclier_off", "bouclier_secours"):
        assert "_refus_bouclier(i)" in ast.unparse(_noeud(nom)), f"{nom} : la garde dans le code"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q2 — /off (radiation)
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q2_radiation_hierarchie_des_administrateurs_et_direction_protegee():
    """Le trou : un administrateur, même tout en bas, radiait un administrateur plus haut que lui (ou le compte de la
    direction) : tous ses rôles retirés, réduit au silence 28 jours — ce que Discord lui-même interdit."""
    conf = {"direction_allowed_role": 50}
    ns = _charger(_ns(_conf=None), "_autorise_radiation", "_refus_radiation")

    async def cfg(_gid):
        return conf
    ns["cfg"] = cfg
    direction_r, admin_bas_r, admin_haut_r = Role(50, "Direction", 70), Role(30, "Admin bas", 30), Role(80, "Admin haut", 80)
    admin_bas = Membre(30, admin_bas_r, perms=discord.Permissions(administrator=True))
    admin_haut = Membre(80, admin_haut_r, perms=discord.Permissions(administrator=True))
    direction = Membre(DIRECTION, direction_r)
    fondateur = Membre(FONDATEUR, direction_r)
    simple = Membre(7, Role(5, "Membre", 5))
    g = Serveur(admin_bas, admin_haut, direction, fondateur, simple)
    g.owner_id = 4242   # le fondateur n'est pas forcément le propriétaire du serveur : ses droits viennent de son identifiant

    async def droit(qui, cible):
        return await ns["_autorise_radiation"](Interaction(g, qui), cible)
    assert asyncio.run(droit(admin_bas, admin_haut)), "un administrateur ne radie pas plus haut que lui"
    assert ns["_refus_radiation"](g, direction, admin_bas), "la direction : seul le fondateur la radie"
    assert ns["_refus_radiation"](g, direction, Membre(81, Role(82, "Admin très haut", 85),
                                                       perms=discord.Permissions(administrator=True)))
    #  Ceux qui y ont droit le gardent.
    assert asyncio.run(droit(admin_bas, simple)) is None, "un administrateur radie un membre plus bas"
    assert asyncio.run(droit(direction, simple)) is None, "la direction radie un membre plus bas"
    assert asyncio.run(droit(fondateur, admin_haut)) is None and ns["_refus_radiation"](g, direction, fondateur) is None, \
        "le fondateur passe outre (un compte de direction compromis s'arrête)"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q3 — /mod undirection
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q3_undirection_ne_rend_que_des_roles_plus_bas_que_le_sien(tmp_path):
    """Le trou : le fondateur restreint un administrateur ; un porteur du rôle Direction, plus bas que lui, lance
    /mod undirection : le rôle Administrateur revient — une escalade de droits."""
    get_db = _base(tmp_path / "b.db")
    admin_r, membre_r, direction_r = Role(80, "Admin", 80), Role(10, "Membre", 10), Role(50, "Direction", 50)
    restreint_r = Role(2, "🔒 Restricted", 2)
    cible = Membre(30, restreint_r)
    direction = Membre(40, direction_r)
    fondateur = Membre(FONDATEUR, direction_r)
    g = Serveur(cible, direction, fondateur, roles=(admin_r, membre_r, direction_r, restreint_r))
    envois = []

    async def journal(*a, **k):
        envois.append(a)

    class Groupe:
        def command(self, **kw):
            return lambda f: f
    ns = _charger(_ns(_conf={"direction_allowed_role": 50}, get_db=get_db, mod_group=Groupe(),
                      app_commands=Obj(describe=lambda **kw: (lambda f: f)), carte_embed=lambda e: e,
                      send_mod_log=journal, now=lambda: None), "undirection_cmd")
    conf = {"direction_allowed_role": 50}

    async def cfg(_gid):
        return conf
    ns["cfg"] = cfg

    async def scenario(qui, sauves=(80, 10)):
        async with get_db() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS restricted_members (guild_id INTEGER, user_id INTEGER,"
                             " roles_backup TEXT, restricted_at TEXT, duration INTEGER, reason TEXT, restricted_by INTEGER)")
            await db.execute("DELETE FROM restricted_members")
            await db.execute("INSERT INTO restricted_members VALUES (1, 30, ?, '', 0, 'x', ?)",
                             (json.dumps(list(sauves)), FONDATEUR))
            await db.commit()
        cible.roles, cible.ajouts, cible.retraits = [TOUS, restreint_r], [], []
        await ns["undirection_cmd"](Interaction(g, qui), cible)
        async with get_db() as db:
            async with db.execute("SELECT COUNT(*) FROM restricted_members") as cur:
                reste = (await cur.fetchone())[0]
        return list(cible.ajouts), reste
    ajoutes, reste = asyncio.run(scenario(direction))
    assert 80 not in ajoutes, "la direction ne rend pas un rôle plus haut que le sien (l'Administrateur)"
    assert (ajoutes, reste, restreint_r in cible.roles) == ([], 1, True), \
        "rien ne bouge : la restriction et sa sauvegarde restent pour le fondateur"
    assert asyncio.run(scenario(direction, sauves=(10,))) == ([10], 0), \
        "la direction lève toujours la restriction d'un membre plus bas"
    assert asyncio.run(scenario(fondateur)) == ([80, 10], 0), "le fondateur rend tout"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q4 — le panneau de sanction du staff (staff_sanction.py)
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q4_panneau_du_staff_ni_soi_meme_ni_la_tete_ni_plus_haut(tmp_path, monkeypatch):
    """Le trou : un panneau s'ouvre aussi pour la tête (fuite de jeton, webhook…) ; un modérateur qui a « Gérer les
    messages » cliquait « Mute 1h » sur la direction, inscrivait un avertissement à son casier, ou classait « faux
    positif » le panneau qui le visait lui-même."""
    import staff_sanction
    get_db = _base(tmp_path / "s.db")
    avertis = []

    async def avertir(g, uid, mod, raison):
        avertis.append(uid)
        return 1, None
    monkeypatch.setattr(staff_sanction, "_ratelimit", None)
    try:
        staff_sanction.setup(None, get_db, None, {}, avertir=avertir, tete=TETE)
    except TypeError:   # le code d'avant la correction ne connaissait pas la tête : le test prouve le trou quand même
        staff_sanction.setup(None, get_db, None, {}, avertir=avertir)
    modo_r = Role(40, "Modération", 40)
    modo = Membre(5, modo_r)
    chef_modo = Membre(6, Role(45, "Chef modo", 45))
    direction = Membre(DIRECTION, Role(70, "Direction", 70))
    simple = Membre(7, Role(5, "Membre", 5))
    g = Serveur(modo, chef_modo, direction, simple)
    salon = Obj(permissions_for=lambda u: discord.Permissions(manage_messages=True))

    async def clic(qui, cible, action):
        await staff_sanction.init_db()
        async with get_db() as db:
            cur = await db.execute("INSERT INTO staff_sanction_log (guild_id, target_user_id, reason) VALUES (1, ?, 'x')",
                                   (cible.id,))
            sid = cur.lastrowid
            await db.commit()
        i = Interaction(g, qui, channel=salon, message=None)
        await staff_sanction._handle_sanction_click(i, sid, action)
        async with get_db() as db:
            async with db.execute("SELECT final_action FROM staff_sanction_log WHERE id=?", (sid,)) as cur:
                return (await cur.fetchone())[0], i.textes()
    fait, texte = asyncio.run(clic(modo, direction, "mute_1h"))
    assert fait is None and not direction.exclusions and "protég" in texte, "la direction ne se mute pas d'un clic"
    assert asyncio.run(clic(modo, direction, "warn"))[0] is None and not avertis, "ni un avertissement à son casier"
    assert asyncio.run(clic(modo, modo, "ignore"))[0] is None, "on ne classe pas le panneau qui nous vise"
    assert asyncio.run(clic(modo, chef_modo, "mute_1h"))[0] is None and not chef_modo.exclusions, \
        "ni un rang égal ou supérieur"
    #  Le modérateur garde son outil.
    assert asyncio.run(clic(modo, simple, "mute_1h"))[0] == "muted_1h" and simple.exclusions
    assert asyncio.run(clic(modo, simple, "warn"))[0] == "warned" and avertis == [7]


# ═══════════════════════════════════════════════════════════════════════════════
#  Q5 — le recours d'un radié : « Bannir définitivement »
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q5_bannir_un_recours_seulement_s_il_est_encore_radie(tmp_path):
    """Le trou : la carte du recours garde ses boutons après une levée par /off off ; un porteur du rôle Direction
    bannissait alors définitivement un membre réintégré — même plus haut que lui (aucune hiérarchie)."""
    get_db = _base(tmp_path / "r.db")
    direction_r = Role(50, "Direction", 50)
    porteur = Membre(40, direction_r)
    reintegre = Membre(33, Role(60, "Ancien", 60))
    radie = Membre(34, Role(3, "🚫 Radié", 3))
    g = Serveur(porteur, reintegre, radie)
    conf = {"direction_allowed_role": 50}

    async def cfg(_gid):
        return conf

    async def rien(*a, **k):
        return None
    ns = _charger(_ns(get_db=get_db, _prevenir_radie=rien, _carte_recours_decidee=rien, _fermer_recours=rien,
                      _lever_radiation=rien, time=__import__("time")),
                  "_autorise_radiation", "RadieDecisionButton", optionnels=("_refus_rang_radie",))
    ns["cfg"] = cfg

    async def bannir(uid):
        async with get_db() as db:
            await db.execute(SCHEMA_RADIES)
            await db.execute("DELETE FROM radiated_members")
            await db.execute("INSERT INTO radiated_members (guild_id, user_id, saved_roles) VALUES (1, 34, '[]')")
            await db.commit()
        i = Interaction(g, porteur, message=None, channel=None)
        await ns["RadieDecisionButton"]("bannir", uid).callback(i)
        return i.textes()
    texte = asyncio.run(bannir(33))
    assert 33 not in g.bannis, "un membre dont la radiation est levée ne se bannit plus d'un clic"
    asyncio.run(bannir(34))
    assert g.bannis == [34], "un membre encore radié, plus bas : le recours rejeté le bannit (le droit reste)"
    assert texte


# ═══════════════════════════════════════════════════════════════════════════════
#  Q6 — « Annuler » la configuration des salons
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q6_annuler_la_configuration_des_salons_pas_avec_gerer_le_serveur(tmp_path):
    """Le trou : « Gérer le serveur » seul suffisait pour remettre d'un clic les permissions de salons d'avant — dont les
    refus « 🚫 Radié » levés ; le message dit pourtant « Réservé au fondateur et à la direction »."""
    get_db = _base(tmp_path / "c.db")
    restaures = []

    async def restaurer(g, avant):
        restaures.append(avant)
        return 2
    ns = _charger(_ns(get_db=get_db, config_salons=Obj(restaurer=restaurer)), "_direction_ou_plus",
                  "BoutonAnnulerConfig")
    conf = {"direction_allowed_role": 50}

    async def cfg(_gid):
        return conf
    ns["cfg"] = cfg
    gerant = Membre(5, Role(20, "Gérant", 20), perms=discord.Permissions(manage_guild=True))
    admin = Membre(6, Role(21, "Admin", 21), perms=discord.Permissions(administrator=True))
    direction_r = Role(50, "Direction", 50)
    direction = Membre(DIRECTION, direction_r)
    g = Serveur(gerant, admin, direction, roles=(direction_r,))

    async def annuler(qui):
        async with get_db() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS config_salons_historique (id INTEGER PRIMARY KEY, guild_id INTEGER,"
                             " avant TEXT)")
            await db.execute("INSERT OR REPLACE INTO config_salons_historique VALUES (7, 1, '{}')")
            await db.commit()

        class Msg:
            async def edit(self, **kw):
                return None
        await ns["BoutonAnnulerConfig"](7).callback(Interaction(g, qui, message=Msg()))
    asyncio.run(annuler(gerant))
    assert restaures == [], "« Gérer le serveur » seul ne remet rien"
    asyncio.run(annuler(admin))
    asyncio.run(annuler(direction))
    assert len(restaures) == 2, "un administrateur et la direction gardent « Annuler »"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q7 — /rellseas (rellseas_panneau.py)
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q7_rellseas_ni_la_tete_ni_un_radie(monkeypatch):
    """Le trou : un équipier du panneau /rellseas (même avec le rôle réglé le plus bas) retirait le rôle du clan au
    fondateur ou à la direction, ou le donnait à un radié (le rôle du clan l'emporte sur le refus « Radié » : il
    revoyait le forum du clan). Comme dans Discord, le rang du membre visé ne compte pas pour un rôle : l'équipier
    garde tout son geste sur les autres (un officier plus haut que lui compris)."""
    import rellseas_panneau as R
    ns = _charger(_ns(), optionnels=("_refus_cible_rellseas",))
    clan_r, radie_r = Role(30, "Rell Seas", 30), Role(3, "🚫 Radié", 3)
    equipier = Membre(5, Role(20, "Recruteur", 20))
    fondateur = Membre(FONDATEUR, Role(70, "Direction", 70), clan_r)
    haut = Membre(8, Role(25, "Officier", 25), clan_r)
    recrue = Membre(9, Role(4, "Membre", 4))
    radie = Membre(10, radie_r)
    ancien = Membre(11, Role(4, "Membre", 4), clan_r)
    g = Serveur(equipier, fondateur, haut, recrue, radie, ancien, roles=(clan_r, radie_r))
    conf = {R.CLE_ROLE_CIBLE: clan_r.id}

    async def cfg(_gid):
        return conf

    async def rien(*a, **k):
        return None
    try:
        R.setup(cfg=cfg, db_set=None, autorise=None, cible=ns.get("_refus_cible_rellseas"), log=lambda *a: None)
    except TypeError:   # le code d'avant la correction : aucune garde sur la cible — le test prouve le trou quand même
        R.setup(cfg=cfg, db_set=None, autorise=None, log=lambda *a: None)
    monkeypatch.setattr(R.RellseasGestionV2, "render_to", rien)
    monkeypatch.setattr(R.RellseasGestionV2, "_journal", rien)

    async def agir(ids, donner):
        i = Interaction(g, equipier)
        R._SELECTIONS[R._cle(i)] = list(ids)
        await R.RellseasGestionV2()._agir(i, donner)
        return R._DERNIER.get(R._cle(i), "")
    bilan = asyncio.run(agir([FONDATEUR, 8, 11], donner=False))
    assert clan_r in fondateur.roles, "jamais la tête"
    assert clan_r not in ancien.roles and clan_r not in haut.roles, \
        "l'équipier retire toujours le rôle aux autres membres (comme dans Discord, quel que soit leur rang)"
    assert "protég" in bilan
    asyncio.run(agir([10, 9], donner=True))
    assert clan_r not in radie.roles, "un radié ne reçoit pas le rôle du clan"
    assert clan_r in recrue.roles, "l'équipier donne toujours le rôle à une recrue"
    assert "cible=_refus_cible_rellseas" in SRC, "bot.py branche la garde sur le panneau"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q8 — « Gérer le casier » (/mod infractions)
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q8_gerer_le_casier_jamais_le_sien_ni_plus_haut():
    """Le trou : un modérateur ouvrait /mod infractions sur LUI-MÊME → « Gérer le casier » → effaçait ses propres
    avertissements (et remettait son escalade à zéro) ; ou le casier d'un rang supérieur. /mod unwarn l'interdit déjà."""
    async def permis(i, cle):
        return True
    ns = _charger(_ns(check_mod_perm=permis, LayoutView=discord.ui.LayoutView, Palette=Obj(WARNING=0, DANGER=0),
                      _CASIER_TYPE_EMOJI={}), "_CasierManageView")
    modo = Membre(5, Role(40, "Modération", 40))
    chef = Membre(6, Role(45, "Chef modo", 45))
    simple = Membre(7, Role(5, "Membre", 5))
    g = Serveur(modo, chef, simple)

    def vue(staff, membre):
        v = ns["_CasierManageView"].__new__(ns["_CasierManageView"])
        v.staff_id, v.member, v.guild = staff.id, membre, g
        return v

    async def essai(staff, membre):
        return await vue(staff, membre).interaction_check(Interaction(g, staff))
    assert asyncio.run(essai(modo, modo)) is False, "jamais son propre casier"
    assert asyncio.run(essai(modo, chef)) is False, "ni celui d'un rang égal ou supérieur"
    assert asyncio.run(essai(modo, simple)) is True, "le modérateur garde le casier des membres"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q9 — le site : les rôles du fondateur (affiches.py)
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q9_site_les_roles_du_fondateur_ne_bougent_pas_depuis_la_direction(tmp_path, monkeypatch):
    """Le trou : une session de la direction (ou une session volée) liait « 🔒 Restricted » — un rôle sans permission —
    à un élément du catalogue et l'appliquait à l'affiche du fondateur : muet partout. « Fondateur et direction
    protégés » (bot.py, `_cible_site`) ne valait pas pour les rôles des affiches."""
    import affiches
    import tableau
    get_db = _base(tmp_path / "a.db")
    restreint = Role(12, "Muselière", 12)   # un rôle sans permission (refusé dans chaque salon, par exemple)
    g = Serveur(roles=(restreint,))
    fondateur = Membre(FONDATEUR, Role(70, "Direction", 70))
    direction = Membre(DIRECTION, Role(70, "Direction", 70))
    simple = Membre(7, Role(5, "Membre", 5))
    g._membres.update({FONDATEUR: fondateur, DIRECTION: direction, 7: simple})
    monkeypatch.setattr(tableau, "_tete", TETE)
    affiches.setup(get_db=get_db, log=lambda *a: None)

    async def scenario():
        await affiches.init_db()
        async with get_db() as db:
            await db.execute("INSERT INTO rell_roles (guild_id, type, cle, role_id, auto, maj_le, maj_par)"
                             " VALUES (1, 'grade', 'mousse', 12, 1, 0, 0)")
            await db.commit()
        out = {}
        for nom, auteur, cible in (("direction→fondateur", direction, fondateur), ("direction→membre", direction, simple),
                                   ("fondateur→direction", fondateur, direction)):
            out[nom] = await affiches.appliquer_roles(g, auteur, cible, {"grade": ["mousse"]})
        return out
    out = asyncio.run(scenario())
    assert restreint not in fondateur.roles, "la direction ne change pas les rôles du fondateur depuis le site"
    assert "protég" in str(out["direction→fondateur"].get("erreur", "")), "et le site le dit"
    #  Ceux qui y ont droit le gardent : la direction pour les membres, le fondateur pour tout le monde.
    assert restreint in simple.roles and restreint in direction.roles


def test_Q9b_lier_un_role_a_un_metier_ne_le_pousse_pas_au_fondateur(tmp_path, monkeypatch):
    """Le même trou par un autre chemin : lier un rôle sans permission à un métier le donne aussitôt à tout le clan qui a
    ce métier (`metiers.donner_aux_affiches`) — affiche du fondateur comprise, depuis la session de la direction."""
    import affiches
    import metiers
    from test_metiers import Banc, run
    banc = Banc(tmp_path, monkeypatch)
    g = banc.g
    banc.chef.roles.append(banc.clan)
    for qui in (banc.chef, banc.kolax):
        asyncio.run(affiches.definir_metiers(g, qui, ["cooking"], FONDATEUR))
    muse = g.role(15, "Muselière", 3)
    st, _rep = run(affiches._route_role(g, banc.direction, {}, {"type": "metier", "cle": "cooking", "auto": True,
                                                               "role_id": "15"}))
    assert st == 200 and muse in banc.kolax.roles, "le rôle lié part toujours aux membres du clan qui ont le métier"
    assert muse not in banc.chef.roles, "jamais au fondateur depuis la session de la direction"
    #  Le fondateur, lui, le fait pour tout le monde (lui compris).
    st, _rep = run(metiers.route_installer(g, banc.chef, {}, {}))
    assert st == 200
    #  Et un rôle de sanction ne se lie jamais au catalogue.
    restreint, radie = g.role(16, "🔒 Restricted", 2), g.role(17, "🚫 Radié", 2)
    assert "sanction" in str(affiches.refus_role(g, restreint)) and "sanction" in str(affiches.refus_role(g, radie))
    assert metiers.planifier_attribution.__code__.co_argcount == 3, "l'auteur suit jusqu'à la distribution en masse"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q10 — lever une radiation (/off off, bouton « Lever la radiation » du recours)
# ═══════════════════════════════════════════════════════════════════════════════

def _ns_radiation(get_db, **kw) -> dict:
    """L'entourage de `_lever_radiation` et du bouton du recours : la base, le journal des sanctions."""
    async def journal(*a, **k):
        return None
    return _ns(get_db=get_db, aiosqlite=aiosqlite, bot=None,
               ulogger2026=Obj(log_event=journal, EventType=Obj(SEC_ESCALATION="x")), **kw)


def test_Q10_lever_une_radiation_suit_la_hierarchie_d_avant(tmp_path):
    """Le trou : `_lever_radiation` dispensait TOUT administrateur de la hiérarchie. Le plus bas des administrateurs levait
    la radiation d'un administrateur plus haut que lui — ou celle du compte de la direction, radié par le fondateur (un
    compte volé) — et lui rendait tous ses rôles gardés, même au-dessus des siens. Radier suit la hiérarchie (Q2) : lever
    aussi, sur le rang d'AVANT la radiation."""
    get_db = _base(tmp_path / "l.db")
    radie_r, membre_r = Role(3, "🚫 Radié", 3), Role(5, "Membre", 5)
    admin_bas_r, admin_haut_r, direction_r = Role(30, "Admin bas", 30), Role(80, "Admin haut", 80), Role(50, "Direction", 50)
    admin_bas = Membre(30, admin_bas_r, perms=discord.Permissions(administrator=True))
    admin_tres_haut = Membre(81, Role(85, "Admin très haut", 85), perms=discord.Permissions(administrator=True))
    porteur = Membre(40, direction_r)
    fondateur = Membre(FONDATEUR, direction_r)
    cible = Membre(80, radie_r)      # radiée : il ne lui reste que « 🚫 Radié »
    g = Serveur(admin_bas, admin_tres_haut, porteur, fondateur, cible,
                roles=(radie_r, membre_r, admin_bas_r, admin_haut_r, direction_r))
    ns = _charger(_ns_radiation(get_db), "_lever_radiation", optionnels=("_refus_rang_radie",))

    async def lever(qui, uid, sauves):
        cible.id = uid
        cible.roles, cible.ajouts = [TOUS, radie_r], []
        async with get_db() as db:
            await db.execute(SCHEMA_RADIES)
            await db.execute("DELETE FROM radiated_members")
            await db.execute("INSERT INTO radiated_members (guild_id, user_id, saved_roles, saved_nick) VALUES (1, ?, ?, '')",
                             (uid, json.dumps(list(sauves))))
            await db.commit()
        erreur = await ns["_lever_radiation"](g, cible, qui, "essai")
        return erreur, list(cible.ajouts)
    erreur, ajouts = asyncio.run(lever(admin_bas, 80, (80,)))
    assert erreur and ajouts == [], "le plus bas des administrateurs ne relève pas un administrateur plus haut que lui"
    erreur, ajouts = asyncio.run(lever(admin_tres_haut, DIRECTION, (50,)))
    assert erreur and ajouts == [], "la direction radiée (par le fondateur) : seul le fondateur la relève"
    #  Ceux qui y ont droit le gardent.
    assert asyncio.run(lever(admin_bas, 7, (5,))) == (None, [5]), "un administrateur relève un membre plus bas"
    assert asyncio.run(lever(porteur, 7, (5,))) == (None, [5]), "la direction relève un membre plus bas"
    assert asyncio.run(lever(admin_tres_haut, 80, (80,))) == (None, [80]), "un administrateur plus haut relève"
    assert asyncio.run(lever(fondateur, DIRECTION, (50,))) == (None, [50]), "le fondateur relève la direction"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q11 — « Bannir définitivement » un recours : le rang d'avant la radiation
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q11_bannir_un_recours_suit_le_rang_d_avant_la_radiation(tmp_path):
    """Le trou (le reste de Q5) : la hiérarchie se lisait sur le rang ACTUEL du radié — il ne lui reste que
    « 🚫 Radié », tout en bas. Un porteur du rôle Direction bannissait définitivement un administrateur radié plus haut
    que lui ; et sans aucune hiérarchie quand le radié avait quitté le serveur."""
    get_db = _base(tmp_path / "b.db")
    direction_r, radie_r, admin_r, membre_r = Role(50, "Direction", 50), Role(3, "🚫 Radié", 3), Role(80, "Admin", 80), \
        Role(5, "Membre", 5)
    porteur = Membre(40, direction_r)
    admin_radie, simple_radie = Membre(35, radie_r), Membre(36, radie_r)
    g = Serveur(porteur, admin_radie, simple_radie, roles=(direction_r, radie_r, admin_r, membre_r))
    conf = {"direction_allowed_role": 50}

    async def cfg(_gid):
        return conf

    async def rien(*a, **k):
        return None
    ns = _charger(_ns_radiation(get_db, _prevenir_radie=rien, _carte_recours_decidee=rien, _fermer_recours=rien,
                                _lever_radiation=rien, time=__import__("time")),
                  "_autorise_radiation", "RadieDecisionButton", optionnels=("_refus_rang_radie",))
    ns["cfg"] = cfg

    async def bannir(uid, sauves):
        async with get_db() as db:
            await db.execute(SCHEMA_RADIES)
            await db.execute("DELETE FROM radiated_members")
            await db.execute("INSERT INTO radiated_members (guild_id, user_id, saved_roles) VALUES (1, ?, ?)",
                             (uid, json.dumps(list(sauves))))
            await db.commit()
        i = Interaction(g, porteur, message=None, channel=None)
        await ns["RadieDecisionButton"]("bannir", uid).callback(i)
        return i.textes()
    texte = asyncio.run(bannir(35, (80,)))
    assert 35 not in g.bannis, "un administrateur radié, plus haut que la direction, ne se bannit pas d'un clic"
    assert "égal ou supérieur" in texte
    asyncio.run(bannir(37, (80,)))   # parti du serveur : sa fiche dit encore son rang
    assert 37 not in g.bannis, "parti du serveur, le rang d'avant compte toujours"
    asyncio.run(bannir(36, (5,)))
    assert g.bannis == [36], "un radié plus bas : le recours rejeté le bannit (le droit reste)"


# ═══════════════════════════════════════════════════════════════════════════════
#  Q12 — jamais le rôle du clan à un membre sanctionné
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q12_jamais_le_role_du_clan_a_un_membre_sanctionne(monkeypatch):
    """Le trou : « Accepter » une candidature (carte du ticket, et le site) donnait le rôle du clan sans regarder les
    sanctions — un radié revoyait le forum du clan, le cas que Q7 ferme sur /rellseas ; et /rellseas « Donner » ne
    regardait que « 🚫 Radié » : un membre isolé (quarantaine) ou restreint (/mod direction) recevait le rôle, dont les
    autorisations l'emportent sur les refus de sa sanction dans les salons du clan."""
    import rellseas_panneau as R
    clan_r, radie_r = Role(30, "Rell Seas", 30), Role(3, "🚫 Radié", 3)
    restreint_r, quarantaine_r = Role(2, "🔒 Restricted", 2), Role(4, "Quarantaine", 4)
    recruteur = Membre(5, Role(20, "Recruteur", 20))
    radie, restreint, isole = Membre(10, radie_r), Membre(11, restreint_r), Membre(12, quarantaine_r)
    recrue, recrue2 = Membre(13, Role(6, "Membre", 6)), Membre(14, Role(6, "Membre", 6))
    g = Serveur(recruteur, radie, restreint, isole, recrue, recrue2, roles=(clan_r, radie_r, restreint_r, quarantaine_r))
    conf = {"rellseas_role": clan_r.id, R.CLE_ROLE_CIBLE: clan_r.id}

    async def cfg(_gid):
        return conf

    async def rien(*a, **k):
        return None

    async def texte(*a, **k):
        return ""
    tickets = {}

    async def ticket_ouvert(_g, tid):
        return Obj(id=900 + tid), {"user": tickets[tid], "id": tid}
    ns = _charger(_ns(_ticket_ouvert=ticket_ouvert, rellseas_ui=Obj(CLE_ROLE_CIBLE="rellseas_role"),
                      textes=Obj(texte=texte), metiers=Obj(inviter_au_choix=rien), _fermer_en_fond=lambda c: c.close(),
                      _fermer_ticket=rien, _journal_rellseas=rien, log_staff_action=rien),
                  "_decision_recrutement", optionnels=("_refus_cible_rellseas",))
    ns["cfg"] = cfg

    async def accepter(membre):
        tickets[membre.id] = membre.id
        return await ns["_decision_recrutement"](g, membre.id, recruteur, True)
    for sanctionne in (radie, restreint, isole):
        ok, _message = asyncio.run(accepter(sanctionne))
        assert not ok and clan_r not in sanctionne.roles, f"« Accepter » ne donne pas le rôle du clan à {sanctionne.name}"
    assert asyncio.run(accepter(recrue))[0] and clan_r in recrue.roles, "une recrue est toujours acceptée"
    #  /rellseas « Donner » : la même règle, membre par membre.
    try:
        R.setup(cfg=cfg, db_set=None, autorise=None, cible=ns.get("_refus_cible_rellseas"), log=lambda *a: None)
    except TypeError:   # le code d'avant Q7 : aucune garde sur la cible — le test prouve le trou quand même
        R.setup(cfg=cfg, db_set=None, autorise=None, log=lambda *a: None)
    monkeypatch.setattr(R.RellseasGestionV2, "render_to", rien)
    monkeypatch.setattr(R.RellseasGestionV2, "_journal", rien)

    async def donner(ids):
        i = Interaction(g, recruteur)
        R._SELECTIONS[R._cle(i)] = list(ids)
        await R.RellseasGestionV2()._agir(i, True)
        return R._DERNIER.get(R._cle(i), "")
    bilan = asyncio.run(donner([11, 12, 14]))
    assert clan_r not in restreint.roles and clan_r not in isole.roles, "ni un restreint, ni un isolé"
    assert clan_r in recrue2.roles, "l'équipier donne toujours le rôle à une recrue"
    assert "sanction" in bilan


# ═══════════════════════════════════════════════════════════════════════════════
#  Q13 — /mod unmute ne défait pas une restriction de la direction
# ═══════════════════════════════════════════════════════════════════════════════

def test_Q13_unmute_ne_defait_pas_une_restriction_de_la_direction():
    """Le trou : `/mod direction` restreint un membre (rôle « 🔒 Restricted », tout en bas, et une exclusion) ; un
    modérateur qui n'a que le rôle du mute tapait `/mod unmute` : la hiérarchie passait (il ne reste au membre que
    « Restricted »), l'exclusion tombait — une sanction de la direction défaite au niveau du mute. Comme une radiation
    (`/off off`), une restriction se lève par `/mod undirection`."""
    restreint_r = Role(2, "🔒 Restricted", 2)
    modo = Membre(5, Role(40, "Modération", 40))
    restreint, muet = Membre(30, restreint_r), Membre(31, Role(10, "Membre", 10))
    for m in (restreint, muet):
        m.exclusions = ["jusqu'à demain"]
    g = Serveur(modo, restreint, muet, roles=(restreint_r,))

    async def permis(i, cle):
        return True

    async def rien(*a, **k):
        return None

    class Groupe:
        def command(self, **kw):
            return lambda f: f
    ns = _charger(_ns(check_mod_perm=permis, mod_group=Groupe(), app_commands=Obj(describe=lambda **kw: (lambda f: f)),
                      _a_la_tete=lambda g, m, c=None: m is not None and m.id in TETE, _isolement_actif=rien,
                      _rendre_roles_isolement=rien, C=Obj(GREEN=0), now=lambda: None, _announce_sanction_public=rien,
                      send_mod_log=rien), "unmute_cmd")
    i = Interaction(g, modo)
    asyncio.run(ns["unmute_cmd"](i, restreint))
    assert restreint.is_timed_out(), "une restriction de la direction ne se défait pas par /mod unmute"
    assert "undirection" in i.textes()
    asyncio.run(ns["unmute_cmd"](Interaction(g, modo), muet))
    assert not muet.is_timed_out(), "le modérateur garde son /mod unmute pour un mute ordinaire"
