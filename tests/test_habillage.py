"""19/10/2026 : « un vrai motion design vraiment custom pour absolument tous les menus, pas tout
sous forme d'emoji » — chaque menu a son bandeau, chaque bouton son icône maison."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import discord

import visuels

RACINE = Path(__file__).resolve().parent.parent
MENUS = ["bot.py", "admin_panels_v2.py", "error_logger.py",
         "mod_dashboard.py", "observability.py", "raid_detector.py", "rellseas_panneau.py",
         "roblox_panneau.py", "staff_sanction.py", "tickets_enhance.py", "webhook_tracker.py",
         "social_zones.py", "sondages.py", "suggestions.py", "notifs.py"]
EMOJI = re.compile(r"^[\U0001F000-\U0001F1E5\U0001F200-\U0001FAFF☀-➿⬀-⯿"
                   r"←-⇿⌀-⏿]")
ETATS = set("🟢🔴🟠🟡⚪🔵🟣⚫✅❌⚠🔘")


def _sources():
    return {m: (RACINE / m).read_text(encoding="utf-8") for m in MENUS}


def _cles_du_generateur(nom):
    arbre = ast.parse((RACINE / "outils" / "visuels.py").read_text(encoding="utf-8"))
    for n in arbre.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets):
            return {k.value for k in n.value.keys}
    raise AssertionError(nom)


def test_H1_chaque_bandeau_appele_existe():
    cles = set()
    for src in _sources().values():
        cles |= set(re.findall(r'visuels\.bandeau\("([a-z_]+)"', src))
    assert len(cles) >= 40
    generes = _cles_du_generateur("BANDEAUX")
    for c in sorted(cles):
        assert (RACINE / "visuels" / f"{c}.gif").is_file(), c
        assert c in generes, c


def test_H2_chaque_icone_appelee_existe_et_a_un_repli():
    noms = set()
    for src in _sources().values():
        noms |= set(re.findall(r'visuels\.icone\("([a-z_]+)"', src))
    assert len(noms) >= 40
    generees = _cles_du_generateur("ICONES")
    for n in sorted(noms):
        assert n in visuels.REPLI, n
        assert n in generees, n
        assert (RACINE / "visuels" / "icones" / f"{n}.png").is_file(), n
    assert set(visuels.REPLI) == generees, "chaque icône générée a son émoji de repli"


def test_H3_plus_de_titre_ni_de_bouton_en_emoji():
    fautes = []
    for nom, src in _sources().items():
        for n in ast.walk(ast.parse(src)):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            appel = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            textes = []
            if appel in ("v2_title", "title") and n.args:
                textes.append(n.args[0])
            if appel in ("Button", "button", "SelectOption"):
                textes += [k.value for k in n.keywords if k.arg == "label"]
            for t in textes:
                v = t.value if isinstance(t, ast.Constant) else (
                    t.values[0].value if isinstance(t, ast.JoinedStr) and t.values
                    and isinstance(t.values[0], ast.Constant) else None)
                if isinstance(v, str) and EMOJI.match(v) and v[0] not in ETATS:
                    fautes.append(f"{nom}:{n.lineno} {v[:40]!r}")
    assert not fautes, fautes


def test_H4_une_icone_est_un_objet_partage_qui_devient_maison_sur_place(monkeypatch):
    monkeypatch.setattr(visuels, "_icones", {n: visuels._partage(n) for n in visuels.REPLI})
    bouton = discord.ui.Button(label="Retour", emoji=visuels.icone("retour"))
    option = discord.SelectOption(label="Retour", emoji=visuels.icone("retour"))
    assert bouton.to_component_dict()["emoji"]["name"] == "◀️"
    visuels._monter("retour", discord.PartialEmoji(name="retour_v1", id=42))
    assert bouton.to_component_dict()["emoji"] == {"id": 42, "name": "retour_v1"}
    assert option.to_dict()["emoji"]["id"] == 42
    assert visuels.icone("inconnue", "🔔") == "🔔" and visuels.icone("inconnue") is None


def test_H5_les_icones_connues_reviennent_au_demarrage(tmp_path, monkeypatch):
    memoire = tmp_path / "visuels_icones.json"
    monkeypatch.setattr(visuels, "_memoire", lambda: memoire)
    memoire.write_text(json.dumps({"version": visuels.VERSION, "icones": {"cloche": 7}}), encoding="utf-8")
    assert visuels._lire_memoire() == {"cloche": 7}
    memoire.write_text(json.dumps({"version": "ancienne", "icones": {"cloche": 7}}), encoding="utf-8")
    assert visuels._lire_memoire() == {}, "une autre version d'icônes n'est jamais reprise"
    memoire.write_text("pas du json", encoding="utf-8")
    assert visuels._lire_memoire() == {}


def test_H6_logs_et_alertes_sans_emoji_decoratif():
    import unified_logger as U
    e = U.build_log_embed(next(iter(U.EVENT_META)), user=None, reason="test", content="x")
    assert not EMOJI.match(e.author.name or ""), e.author.name
    assert all(not EMOJI.match(f.name) for f in e.fields)
    publics = {"_handle_boost_stopped", "_handle_boost_started",
               "_handle_welcome", "birthday_announcer", "check_twitch_feeds", "check_youtube_feeds",
               "check_tiktok_feeds", "check_twitter_feeds", "check_reddit_feeds",
               "check_creator_spotlight_feeds", "relay_discord_message", "handle_auto_help",
               "on_interaction", "_flush_welcome_raid_recap", "_envoyer_recours_radie"}
    fautes = []
    arbre = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name in publics:
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(("Embed", "set_author", "add_field")):
                for k in n.keywords:
                    if k.arg in ("title", "name") and isinstance(k.value, ast.Constant) \
                            and isinstance(k.value.value, str) and EMOJI.match(k.value.value) \
                            and k.value.value[0] not in ETATS:
                        fautes.append(f"{fn.name}:{n.lineno} {k.value.value[:30]!r}")
    assert not fautes, fautes
