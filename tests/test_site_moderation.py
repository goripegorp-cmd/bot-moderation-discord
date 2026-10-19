"""19/10/2026 : « un vrai système de modération intégré » — « si quelqu'un se fait voler son compte,
il n'a aucune interaction sur nous-mêmes, fondateur ou direction » — « ils ne peuvent attribuer de
rôle à personne : juste une gestion de rôle pour le système Rell Seas »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

import registre
import rellseas_panneau
from conftest_discord import Obj

SRC = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


class Role(int):
    name = "Rell Seas"


CLAN = Role(10)


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom:
            return ast.unparse(n)
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets):
            return ast.unparse(n)
    raise KeyError(nom)


class Membre:
    def __init__(self, uid, haut=5, roles=(CLAN,), bot=False, mute=False):
        self.id, self.top_role, self.roles, self.bot = uid, haut, list(roles), bot
        self.display_name, self.mention, self.faits, self._mute = f"M{uid}", f"<@{uid}>", [], mute

    def __str__(self):
        return self.display_name

    def is_timed_out(self):
        return self._mute

    async def timeout(self, duree, reason=None):
        self.faits.append(("timeout", duree))

    async def kick(self, reason=None):
        self.faits.append(("kick", reason))

    async def remove_roles(self, role, reason=None):
        self.roles.remove(role)
        self.faits.append(("retire", role))


class Monde:
    def __init__(self, tmp_path, perms=True):
        chemin = tmp_path / "m.db"

        @contextlib.asynccontextmanager
        async def get_db():
            db = await aiosqlite.connect(chemin)
            try:
                yield db
            finally:
                await db.close()

        async def creer():
            async with get_db() as db:
                await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,"
                                 " mod_id INTEGER, type TEXT, reason TEXT, duration TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
                await db.commit()
        asyncio.run(creer())
        self.get_db = get_db
        self.journal = []
        self.membres = {k: m for k, m in {
            99: Membre(99, haut=40), 42: Membre(42, haut=6), 3: Membre(3, haut=30), 2: Membre(2, haut=20),
            7: Membre(7), 8: Membre(8), 9: Membre(9, bot=True), 11: Membre(11), 12: Membre(12, haut=35)}.items()}
        self.bans = []
        moi = Obj(top_role=32, guild_permissions=Obj(moderate_members=perms, kick_members=perms, ban_members=perms,
                                                      manage_roles=perms))

        async def ban(m, reason=None, delete_message_seconds=None):
            self.bans.append(m.id)
        self.g = Obj(id=1, owner_id=99, me=moi, get_member=self.membres.get, ban=ban,
                     get_role=lambda rid: CLAN if rid == CLAN else None)
        conf = {rellseas_panneau.CLE_ROLE_CIBLE: CLAN}

        async def cfg(_g):
            return conf

        async def immunise(m):
            return m.id == 11

        async def enregistre(*a, **k):
            self.journal.append((a, k))
            return "🔇 **Mute automatique : 10 minutes** (palier **3 warns**)." if a and a[-1] == 3 else None

        async def rien(*a, **k):
            self.journal.append((a, k))

        async def dormir(_s):
            return None
        self.ns = {
            "cfg": cfg, "get_db": get_db, "is_fully_immune": immunise, "timedelta": timedelta, "registre": registre,
            "owner_ids_module": Obj(is_super_owner=lambda uid: uid == 42),
            "_direction_ou_plus": lambda g, m, c: m.id in (3, 99, 42),
            "_staff_ou_plus": lambda g, m, c: m.id in (2, 3, 99, 42),
            "_dm_sanction": rien, "_escalade_warns": enregistre, "send_mod_log": rien, "log_staff_action": rien,
            "_journal_rellseas": rien, "_logerr": lambda *a, **k: None, "rellseas_ui": rellseas_panneau,
            "ulogger2026": Obj(log_member_escalation=rien), "bot": None, "asyncio": Obj(sleep=dormir),
            "_decision_recrutement": rien, "now": lambda: datetime.now(timezone.utc),
        }
        for nom in ("_cible_site", "_retirer_du_clan", "_action_clan_retirer", "_action_clan_retirer_lot", "_SANCTIONS_SITE",
                    "_DUREES_MUTE", "_inscrire_sanction", "_format_warn_id", "_action_moderer", "_action_candidature"):
            exec(_source(nom), self.ns)  # noqa: S102 — code du dépôt

    def faire(self, nom, auteur, corps):
        return asyncio.run(self.ns[nom](self.g, self.membres[auteur], corps))


def test_S1_fondateur_et_direction_intouchables_le_staff_sanctionnable(tmp_path):
    m = Monde(tmp_path)
    cible = lambda auteur, uid: asyncio.run(m.ns["_cible_site"](m.g, m.membres[auteur], uid, {}))
    for uid, mot in ((99, "fondateur"), (42, "fondateur"), (3, "fondateur"), (9, "bot"), (11, "immunisé"),
                     (12, "rôle"), (555, "plus sur le serveur")):
        membre, refus = cible(3, uid)
        assert membre is None and mot in refus.lower(), (uid, refus)
    membre, refus = cible(3, 7)
    assert membre is m.membres[7] and refus is None
    assert cible(3, 2)[0] is m.membres[2], "« sanctions directes par le panel en fonction de tout » : le staff aussi"
    m.membres[2].top_role = 30
    assert "rôle" in cible(3, 2)[1], "jamais un rôle égal ou supérieur au sien"
    m.membres[7].top_role = 33
    assert "sous le sien" in cible(99, 7)[1], "jamais au-dessus du bot"


def test_S2_aucun_role_donne_depuis_le_site(tmp_path):
    m = Monde(tmp_path)
    ok, message = m.faire("_action_candidature", 3, {"ticket": 5, "decision": "accepter"})
    assert not ok and "aucun rôle" in message and not m.journal, "accepter (qui donne le rôle) n'est jamais exécuté"
    m.faire("_action_candidature", 3, {"ticket": 5, "decision": "refuser", "motif": "niveau"})
    assert m.journal[-1][0][2:] == (m.membres[3], False, "niveau"), "refuser passe, sans rôle"
    actions = [n for n in ("_action_ticket_fermer", "_action_candidature", "_action_clan_retirer", "_action_clan_retirer_lot",
                           "_action_fiche_retirer", "_action_sanction_retirer", "_action_moderer", "_action_question",
                           "_action_alerte_geree", "_retirer_du_clan", "_cible_site")]
    assert not any("add_roles" in _source(n) for n in actions), "aucune action du site n'ajoute de rôle"
    assert "add_roles" in _source("_decision_recrutement"), "seul l'acceptation Discord (dans le ticket) donne le rôle"


def test_S3_retirer_le_role_du_clan_seulement_et_par_lots(tmp_path):
    m = Monde(tmp_path)
    ok, msg = m.faire("_action_clan_retirer", 3, {"membre": 7})
    assert ok and m.membres[7].faits == [("retire", CLAN)]
    ok, msg = m.faire("_action_clan_retirer", 3, {"membre": 2})
    assert ok and CLAN not in m.membres[2].roles, "le staff sous l'auteur se gère aussi depuis le site"
    lot = list(range(100, 140))
    for uid in lot:
        m.membres[uid] = Membre(uid)
    ok, msg = m.faire("_action_clan_retirer_lot", 3, {"membres": [8, 99, 3] + lot})
    assert ok and msg.startswith("23 membre(s) retiré(s)") and "2 refus" in msg, msg
    assert CLAN in m.membres[99].roles and CLAN in m.membres[3].roles, "fondateur et direction jamais touchés"
    assert sum(1 for uid in lot if CLAN not in m.membres[uid].roles) == 22, "25 au plus d'un coup"


def test_S4_moderer_avec_le_meme_circuit_que_les_commandes(tmp_path):
    m = Monde(tmp_path)
    sans_motif = m.faire("_action_moderer", 3, {"membre": 7, "sanction": "warn", "motif": " "})
    assert not sans_motif[0] and "motif" in sans_motif[1]
    for _ in range(3):
        ok, msg = m.faire("_action_moderer", 3, {"membre": 7, "sanction": "warn", "motif": "Spam"})
    assert ok and msg.startswith("Avertissement enregistré (3 au total).") and "Mute automatique" in msg

    async def lire():
        async with m.get_db() as db:
            async with db.execute("SELECT user_id, mod_id, type FROM infractions") as cur:
                return await cur.fetchall()
    assert asyncio.run(lire()) == [(7, 3, "warn")] * 3, "au casier, au nom de son auteur"
    mute = m.faire("_action_moderer", 3, {"membre": 8, "sanction": "mute", "motif": "Flood", "duree": 60})
    assert mute[0] and m.membres[8].faits == [("timeout", timedelta(minutes=60))]
    assert not m.faire("_action_moderer", 3, {"membre": 8, "sanction": "mute", "motif": "Flood", "duree": 99})[0]
    assert not m.faire("_action_moderer", 3, {"membre": 8, "sanction": "unmute"})[0], "pas muté : rien à lever"
    assert m.faire("_action_moderer", 3, {"membre": 7, "sanction": "ban", "motif": "Raid"})[0] and m.bans == [7]
    protege = m.faire("_action_moderer", 3, {"membre": 99, "sanction": "ban", "motif": "Compte volé ?"})
    assert not protege[0] and m.bans == [7], "même la direction ne peut rien contre le fondateur depuis le site"
    inconnue = m.faire("_action_moderer", 3, {"membre": 7, "sanction": "role", "motif": "xxx"})
    assert not inconnue[0]


def test_S5_sans_permission_le_bot_le_dit(tmp_path):
    m = Monde(tmp_path, perms=False)
    for sanction in ("mute", "kick", "ban"):
        ok, msg = m.faire("_action_moderer", 3, {"membre": 7, "sanction": sanction, "motif": "Test", "duree": 60})
        assert not ok and "permission" in msg
    assert not m.bans and not m.membres[7].faits


def test_S6_une_seule_regle_d_escalade():
    assert "_auto_txt = await _escalade_warns(i.guild, membre, warn_count)" in _source("warn_cmd")
    helper = _source("_escalade_warns")
    assert "i.guild" not in helper and "warn_count == 3" in helper and "return _auto_txt" in helper
