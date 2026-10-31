"""31/10/2026, le fondateur : « S'il commet l'infraction une fois, tu le préviens. Deux fois, tu le mutes. Et s'il la
commet une troisième fois juste après son mute, tu le mutes indéfiniment et c'est nous qui décidons… un seul message
dans Logs… on veut savoir ce qu'il a commis… et pas les sanctions dans le salon commande. »"""
from __future__ import annotations

import ast
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _source(nom):
    for n in ARBRE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == nom:
            return ast.unparse(n)
    raise KeyError(nom)


class Membre:
    def __init__(self):
        self.id, self.mention, self.timed_out_until, self.mutes = 7, "<@7>", None, []

    async def timeout(self, duree, reason=""):
        self.mutes.append(duree)
        self.timed_out_until = datetime.now(timezone.utc) + duree


def test_E1_echelle_prevenu_puis_30_min_puis_jusqu_a_decision(tmp_path):
    chemin = tmp_path / "e.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def preparer():
        async with get_db() as db:
            await db.execute("CREATE TABLE infractions (guild_id INT, user_id INT, mod_id INT, type TEXT, reason TEXT,"
                             " duration TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            await db.commit()
    asyncio.run(preparer())
    traces = {"dm": [], "notes": [], "panneau": [], "inscrit": []}

    async def ajouter(typ="warn"):
        async with get_db() as db:
            await db.execute("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (1, 7, 999, ?, 'x')", (typ,))
            await db.commit()

    async def faux_dm(m, g, titre, texte, *a):
        traces["dm"].append(titre)

    async def faux_inscrire(gid, uid, typ, raison, duree=""):
        traces["inscrit"].append((typ, duree))

    async def immune(_m):
        return False

    async def calme(_c, texte):
        traces["notes"].append(texte)

    async def examiner(gid, mid, forcer=False):
        traces["panneau"].append(forcer)

    class Bot:
        user = type("U", (), {"id": 999})()

    ns = {"get_db": get_db, "bot": Bot(), "is_fully_immune": immune, "_dm_sanction": faux_dm, "_warn_calm_down": calme,
          "_record_infraction": faux_inscrire, "timedelta": timedelta, "now": lambda: datetime.now(timezone.utc),
          "vigilance": type("V", (), {"examiner": staticmethod(examiner)}), "_logerr": lambda *a, **k: None}
    exec("ECHELLE_FENETRE_H = 24\nECHELLE_MUTE_MIN = 30\nECHELLE_DECISION_J = 28\n" + _source("_cumulative_offense_sanction"), ns)
    f, g, m, salon = ns["_cumulative_offense_sanction"], type("G", (), {"id": 1})(), Membre(), object()

    asyncio.run(ajouter())
    asyncio.run(f(g, m, salon, "spam", "aaaa"))
    assert m.mutes == [] and traces["dm"] == ["Avertissement ⚠️"], "1re fois : il est prévenu, pas muté"
    asyncio.run(ajouter())
    asyncio.run(f(g, m, salon, "spam", "bbbb"))
    assert m.mutes == [timedelta(minutes=30)] and traces["inscrit"][-1] == ("mute", "30 minutes"), "2e fois : 30 min"
    asyncio.run(ajouter())
    asyncio.run(f(g, m, salon, "spam", "cccc"))
    assert m.mutes[-1] == timedelta(days=28) and traces["inscrit"][-1] == ("mute", "jusqu'à décision")
    assert traces["panneau"] == [True], "3e fois : muet jusqu'à décision, le panneau est forcé dans 📋logs"
    asyncio.run(ajouter())
    asyncio.run(f(g, m, salon, "spam", "dddd"))
    assert len(m.mutes) == 2 and traces["panneau"] == [True, True], "déjà muet : pas de nouveau mute, le panneau se met à jour"
    assert sum(1 for t in traces["dm"] if "décision" in t) == 1, "un seul MP « jusqu'à décision »"
    #  Les mutes ne comptent pas comme infractions ; les infractions d'un autre jour non plus.
    assert "type NOT IN ('mute','unmute','ban','kick')" in _source("_cumulative_offense_sanction")


def test_E2_toute_sanction_automatique_passe_par_l_echelle():
    corps = _source("sanction")
    i = corps.index("_offense_tick")
    assert "_cumulative_offense_sanction(m.guild, m, None" in corps[i:] and "return True" in corps[i:i + 900]
    assert "if action in ('delete', 'mute'):" in corps
    #  Spam et mentions : plus d'échelle à part ni d'alerte « Escalade… Décision requise ».
    assert 'palier="spam-mentions"' not in SRC and 'palier="spam-warn"' not in SRC
    assert "Spam toxique répété (malgré {strikes - 1} rappels) — « {_extrait} »" in SRC
    assert "Spam de mentions répété ({mention_count} mentions dans un message)" in SRC


def test_E3_un_seul_panneau_par_joueur_avec_la_decision():
    carte = _source("_carte_vigilance")
    for cle in ("warn", "mute7", "kick", "ban", "unmute"):
        assert f'BoutonDecision("{cle}", int(membre_id))' in carte.replace("'", '"')
    assert "Ce qu'il a fait" in carte and "décision requise" in carte
    assert "BoutonGere, BoutonDecision, BoutonFicheSite" in SRC, "le bouton survit aux redémarrages"
    decider = _source("_decider")
    assert "_action_moderer(i.guild, i.user" in decider and "vigilance.gerer" in decider
    assert "_direction_ou_plus(i.guild, i.user" in _source("BoutonDecision")
    #  Ce qu'il a fait : chaque infraction automatique va au journal avec son motif (gravité 1 → le panneau la lit).
    assert "'auto.infraction'" in _source("_record_infraction") and "gravite=1" in _source("_record_infraction")
    import unified_logger
    assert asyncio.run(unified_logger.log_member_escalation(None, None, None, 3, "spam")) is None


def test_E4_vigilance_forcee_et_aucune_carte_publique():
    import vigilance
    import inspect
    assert "forcer" in inspect.signature(vigilance.examiner).parameters
    assert "not alerte_due(evts) and not forcer" in inspect.getsource(vigilance._examiner)
    assert _source("_announce_sanction_public").split('"""')[2].strip().startswith("return None")
    fiche = (RACINE / "site" / "fiche.js").read_text(encoding="utf-8")
    assert "function resumeSanctions(" in fiche and "Ce qu'il a commis" in fiche
