"""19/10/2026 : « supprimer le code mort du combat et des événements… je t'autorise même à
faire un nettoyage complet » ; « Gardes-tu les rôles VIP, VIP+ ? Non. Pareil pour le système
de level » ; « tout le système d'activité… ne sert strictement à rien »."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import discord

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _source(nom):
    return next(ast.unparse(n) for n in ARBRE.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def _tables_mortes():
    noeud = next(n for n in ARBRE.body if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], "id", "") == "_TABLES_MORTES")
    return set(ast.literal_eval(noeud.value.args[0]))


def test_C1_aucune_table_morte_n_est_encore_lue_ni_ecrite():
    mortes = _tables_mortes()
    assert {"economy", "level_rewards", "activity_tracking", "events", "vip_status",
            "player_inventory", "world_bosses", "ui_usage"} <= mortes
    assert "polls" in mortes, "l'ancien sondage à boutons est remplacé par les sondages natifs"
    assert not mortes & {"infractions", "tickets", "guild_config", "live_announcements",
                         "realsy_tracking", "health_check_log", "shop_purchases", "sondages"}
    sql = re.compile(r"\b(?:INTO|FROM|JOIN|UPDATE|TABLE IF NOT EXISTS|ON)\s+(\w+)")
    trouves = []
    for f in sorted(RACINE.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                trouves += [(f.name, n.lineno, t) for t in sql.findall(n.value) if t in mortes]
    lus_une_fois = {"level_rewards", "polls"}       # lus avant d'être retirés
    assert [t for f, ligne, t in trouves if t not in lus_une_fois] == [], trouves


def test_C2_les_tables_mortes_partent_les_autres_restent(tmp_path):
    p = tmp_path / "b.db"
    with sqlite3.connect(p) as c:
        for t in ("economy", "level_rewards", "infractions", "tickets"):
            c.execute(f"CREATE TABLE {t}(x)")

    import aiosqlite

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(p)
        try:
            yield db
        finally:
            await db.close()

    erreurs, vacuums = [], []

    async def part_libre():
        return 0.5

    async def vacuum_db():
        vacuums.append(1)
        return True

    ns = {"get_db": get_db, "_TABLES_MORTES": _tables_mortes(),
          "_logerr": lambda *a, **k: erreurs.append(a),
          "cleanup_module": Obj(part_libre=part_libre, vacuum_db=vacuum_db)}
    exec(_source("_retirer_tables_mortes"), ns)  # noqa: S102 — code du dépôt
    asyncio.run(ns["_retirer_tables_mortes"]())
    asyncio.run(ns["_retirer_tables_mortes"]())
    with sqlite3.connect(p) as c:
        restantes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert restantes == {"infractions", "tickets"} and not erreurs
    assert vacuums, "la place des tables retirées est rendue tout de suite"


def test_C3_roles_vip_niveaux_ugc_partent_jamais_un_role_d_equipe():
    supprimes, ecrits = [], {}

    class Role:
        def __init__(self, rid, nom, rang, gere=False, admin=False, defaut=False):
            self.id, self.name, self.rang, self.managed = rid, nom, rang, gere
            self.permissions = Obj(administrator=admin)
            self._defaut = defaut

        def is_default(self):
            return self._defaut

        def __lt__(self, autre):
            return self.rang < autre.rang

        async def delete(self, reason=None):
            supprimes.append(self.name)

    haut = Role(1, "Bot", 100)
    roles = [Role(10, "🌟 VIP", 5), Role(11, "💎 VIP+", 6), Role(12, "🛒 Collectionneur UGC", 7),
             Role(13, "Niveau 10", 8), Role(14, "Niveau 20 (modo)", 9),
             Role(15, "Niveau 30", 10, admin=True), Role(16, "🔔 Boss", 11),
             Role(17, "Membre", 3), Role(18, "@everyone", 0, defaut=True),
             Role(19, "🌟 VIP", 150)]
    conf = {"mod_role": 14, "panneaux": [{"role": "14"}]}
    g = Obj(id=1, roles=roles, me=Obj(guild_permissions=Obj(manage_roles=True), top_role=haut))

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        ecrits[k] = v

    class Curseur:
        def __init__(self, lignes):
            self.lignes = lignes

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def fetchone(self):
            return self.lignes[0] if self.lignes else None

        async def fetchall(self):
            return self.lignes

    class Db:
        def execute(self, sql, params=()):
            if "sqlite_master" in sql:
                return Curseur([("level_rewards",)])
            return Curseur([(13,), (14,), (15,), (None,)])

    @contextlib.asynccontextmanager
    async def get_db():
        yield Db()

    async def dormir(_s):
        return None

    ns = {"cfg": cfg, "db_set": db_set, "discord": discord, "get_db": get_db, "re": re,
          "asyncio": Obj(sleep=dormir), "now": lambda: datetime(2026, 10, 19),
          "_logerr": lambda *a, **k: supprimes.append(("ERREUR", a)),
          "_ROLES_OBSOLETES": frozenset({"🔔 Boss"})}
    for nom in ("_ids_configures", "_role_supprimable", "_menage_v2"):
        exec(_source(nom), ns)  # noqa: S102 — code du dépôt
    for nom in ("_ROLES_RETIRES_V2", "_PERMS_STAFF"):
        noeud = next(n for n in ARBRE.body if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == nom)
        exec(ast.unparse(noeud), ns)  # noqa: S102
    asyncio.run(ns["_menage_v2"](g))
    assert supprimes == ["🌟 VIP", "💎 VIP+", "🛒 Collectionneur UGC", "Niveau 10", "🔔 Boss"], supprimes
    assert "menage_v2" in ecrits
    supprimes.clear()
    conf["menage_v2"] = "fait"
    asyncio.run(ns["_menage_v2"](g))
    assert supprimes == [], "une seule fois"


def test_C4_plus_aucun_menu_ni_bouton_des_systemes_retires():
    for absent in ("EventNotifyButton", "AdventClaimView", "MentorVolunteerButton",
                   "_check_easter_eggs", "_check_game_night", "add_coins", "get_user_economy",
                   "_boot_cleanup_active_events", "handle_recovery_message", "_hard_reset_member_stats",
                   "stream_watch_channel_id", "combat_arena_channel_id", "controls_min_level",
                   "boost_reward_coins", "activity_vip_module", "ui_usage_module", "matplotlib"):
        assert absent not in SRC, absent
    for f in ("activity_vip.py", "antiscam.py", "birthday_panel.py", "delegations.py",
              "help_faq.py", "panels_helpers.py", "stream_schedule.py", "ui_usage.py"):
        assert not (RACINE / f).exists(), f
    assert "matplotlib" not in (RACINE / "requirements.txt").read_text(encoding="utf-8")
    export = (RACINE / "owner_export.py").read_text(encoding="utf-8")
    assert "economy" not in export and "activity_score" not in export
    assert "bloc vidé (module détaché)" not in SRC


def test_C5_chaque_boucle_supervisee_existe_et_chaque_boucle_tourne():
    noms = {n.name for n in ARBRE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    sup = next(n for n in ARBRE.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_SUPERVISED_LOOP_NAMES")
    surveilles = set(ast.literal_eval(sup.value))
    assert surveilles <= noms, surveilles - noms
    boucles = {n.name for n in ARBRE.body if isinstance(n, ast.AsyncFunctionDef)
               and any(ast.unparse(d).startswith("tasks.loop") for d in n.decorator_list)}
    for b in boucles:
        assert f"{b}.start()" in SRC or b in surveilles, f"{b} ne démarre jamais"


def test_C6_chaque_module_supervise_est_importe():
    imports = set(re.findall(r"^import [a-z_0-9]+ as ([a-z_0-9]+)", SRC, re.M)) |         set(re.findall(r"^import ([a-z_0-9]+)\s*(?:#|$)", SRC, re.M))
    sup = next(n for n in ARBRE.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_SUPERVISED_MODULE_LOOPS")
    absents = [e.elts[0].value for e in sup.value.elts if e.elts[0].value not in imports]
    assert absents == [], absents


def test_C7_aucune_definition_morte_dans_bot_py():
    """Atteignabilité : racines = code exécuté au chargement, commandes, événements, noms
    cités dans une chaîne, noms importés de bot.py par les modules. Une boucle n'est vivante
    que si on la cite ; `@X.before_loop` vit avec X."""
    def cites(noeud):
        out = set()
        for x in ast.walk(noeud):
            if isinstance(x, ast.Name):
                out.add(x.id)
            elif isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value.isidentifier():
                out.add(x.value)
        return out

    defs, racines, attache = {}, set(), {}
    for f in RACINE.glob("*.py"):
        if f.name != "bot.py":
            for groupe in re.findall(r"from bot import ([\w, ]+)", f.read_text(encoding="utf-8")):
                racines |= {x.strip() for x in groupe.split(",")}
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms = [n.name]
        elif isinstance(n, ast.Assign):
            noms = [t.id for t in n.targets if isinstance(t, ast.Name)]
        else:
            noms = []
        if not noms:
            racines |= cites(n)
            continue
        for nom in noms:
            defs.setdefault(nom, []).append(n)
        for d in getattr(n, "decorator_list", []):
            cible = d.func if isinstance(d, ast.Call) else d
            texte = ast.unparse(cible)
            if isinstance(cible, ast.Attribute) and cible.attr in ("before_loop", "after_loop", "error") \
                    and isinstance(cible.value, ast.Name):
                attache.setdefault(cible.value.id, set()).add(n.name)
                continue
            if not (texte.startswith("tasks.loop") or texte.startswith("app_commands.")
                    and texte.split(".")[-1] not in ("command", "context_menu")):
                racines.add(n.name)
            racines |= cites(d) - {n.name}
    vivants, pile = set(), [r for r in racines if r in defs]
    while pile:
        nom = pile.pop()
        if nom in vivants:
            continue
        vivants.add(nom)
        for n in defs[nom]:
            pile += [c for c in cites(n) if c in defs and c not in vivants]
        pile += [f for f in attache.get(nom, ()) if f not in vivants]
    morts = sorted(set(defs) - vivants)
    assert morts == [], morts
