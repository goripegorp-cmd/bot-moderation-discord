"""19/10/2026 (audit, bot.py 23000-fin) : /mod mute répondait trop tard, /mod unmute ignorait la
quarantaine, un membre du staff pouvait effacer ses propres avertissements, le ralentissement
automatique restait pour toujours, choisir un salon de logs ramenait tous les logs dans Discord, et
quatre commandes réglaient des choses que rien ne lit."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import time
from pathlib import Path

import aiosqlite

from conftest_discord import Obj

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _fn(nom):
    return next(ast.unparse(n) for n in ast.walk(ARBRE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def test_C1_mute_repond_avant_de_travailler():
    corps = _fn("mute_cmd")
    assert corps.index("i.response.defer(") < corps.index("membre.timeout(delta")
    apres = corps[corps.index("i.response.defer("):]
    assert "i.response.send_message" not in apres, "après le defer, tout passe par followup"


def test_C2_unmute_leve_aussi_la_quarantaine():
    corps = _fn("unmute_cmd")
    assert "_QUARANTINE_ROLE_NAMES" in corps and "remove_roles(quarantaine" in corps
    assert "_QUARANTINE_ROLE_NAMES" in _fn("on_guild_channel_create"), "les nouveaux salons aussi"


def test_C3_personne_n_efface_ses_propres_avertissements():
    corps = _fn("unwarn_cmd")
    assert "membre.id == i.user.id" in corps and "membre.top_role >= i.user.top_role" in corps


def test_C4_le_ralentissement_automatique_finit_toujours_par_partir(tmp_path):
    chemin = tmp_path / "t.db"

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()
    rates = {}
    ns = {"get_db": get_db, "time": time, "_channel_msg_rates": rates}
    for n in ARBRE.body:
        if getattr(n, "name", None) == "_lever_ralentis":
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    edits = []

    class Salon:
        id, slowmode_delay = 9, 5

        async def edit(self, **kw):
            edits.append(kw)
            self.slowmode_delay = kw["slowmode_delay"]
    salon = Salon()
    g = Obj(id=1, get_channel=lambda cid: salon if cid == 9 else None)

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE auto_slow_log (id INTEGER PRIMARY KEY, guild_id INTEGER, channel_id INTEGER,"
                             " slow_delay INTEGER, cleared_at DATETIME)")
            await db.execute("INSERT INTO auto_slow_log (guild_id, channel_id, slow_delay) VALUES (1, 9, 5)")
            await db.commit()
        rates[9] = [time.time()] * 15
        await ns["_lever_ralentis"](g)
        assert not edits, "encore agité : on garde"
        rates[9] = []
        await ns["_lever_ralentis"](g)
        assert edits == [{"slowmode_delay": 0, "reason": "Auto-slow : calme revenu"}]
        await ns["_lever_ralentis"](g)
        assert len(edits) == 1, "levé une fois, plus rien à faire"
    asyncio.run(scenario())
    assert "await _lever_ralentis(g)" in _fn("server_controls_task") or "_lever_ralentis(g)" in _fn("server_controls_task")


def test_C5_choisir_un_salon_ne_ramene_pas_les_logs_dans_discord():
    src = (RACINE / "unified_logger.py").read_text(encoding="utf-8")
    fn = next(ast.unparse(n) for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "set_log_channel")
    assert "site" not in fn.split('"""')[-1], "le mode n'est plus touché"
    log = next(ast.unparse(n) for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "log_event")
    assert log.index("_consigner(") < log.index("get_enabled_categories("), "le site garde tout"


def test_C6_plus_de_commandes_qui_ne_reglent_rien():
    assert not (RACINE / "setup_wizard.py").exists() and not (RACINE / "slash_commands_2026.py").exists()
    assert "setup_all_commands" not in SRC and "setup_setup_command" not in SRC


def test_C7_aucun_module_ne_recharge_bot_py():
    """`from bot import …` depuis un module rechargeait tout bot.py (le bot tourne en __main__) :
    gel de la boucle, second objet bot, cache de configuration séparé."""
    fautifs = [f.name for f in RACINE.glob("*.py")
               if f.name != "bot.py" and "\nfrom bot import" in f.read_text(encoding="utf-8")
               or "\n        from bot import" in f.read_text(encoding="utf-8")]
    assert not fautifs, fautifs
    assert "db_set_fn=db_set" in SRC


def test_C8_a_l_edition_les_memes_exemptions_qu_a_l_envoi():
    corps = _fn("_scan_security_on_edit")
    assert "if _mod is honeypot_module and exempt:" in corps
    assert "sanctionner=not exempt" in corps
    assert "behavior_anomaly" not in SRC and "_track_toxicity" not in SRC


def test_C9_les_interdictions_de_tickets_ne_disent_plus_qui_a_agi():
    """Audit 5 #23 : « Par : @moderateur » en public (et dans le ticket du membre)."""
    import ast as _a
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    arbre = _a.parse(src)
    corps = _a.unparse(next(n for n in arbre.body if getattr(n, "name", "") == "ticketblacklist_cmd"))
    assert "i.user.mention" not in corps and "/ticketblacklist add" not in corps
    assert corps.count("ephemeral=True") >= 8 and "_au_journal" in corps
    assert 'name="Par", value=i.user.mention' not in src
