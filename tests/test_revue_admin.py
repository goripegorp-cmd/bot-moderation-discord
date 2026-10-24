"""24/10/2026 — revue « panneaux d'administration, publications, journaux ».

Constats corrigés (l'anti-doublon des annonces V2 est dans `test_webhook_doublon.py`) :
  2. mode site : `/logs setchannel` et `/logs categories` disaient avoir réglé ce qui ne l'était pas, et
     le salon choisi était ensuite purgé toutes les 12 h comme un salon de logs ;
  3. `/configure` → « Fermer » levait un TypeError avalé : le panneau restait ;
  4. le bouton de langue ne s'enregistrait plus si la base était occupée au démarrage ;
  5. salons de sécurité : le sélecteur était remplacé par un panneau vide, l'état restait « non défini » ;
  6. textes qui mentaient (bilan santé, panneau des réseaux) ;
  7. `/owner mod_stats` lisait jusqu'à 365 jours avant de répondre ;
  8. le rapport de minuit partait dans le salon « hub », retiré.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
import pytest
from discord.webhook.async_ import handle_message_parameters, interaction_message_response_params

import admin_panels_v2 as panels
import observability as O
import social_media
import ui_v2
import unified_logger as UL
import visuels
from conftest_discord import Obj, Salon, base
from faux_serveur import ids, textes
from ui_v2 import LayoutView, Palette, carte_embed, carte_texte

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _noeud(nom, classe=None):
    corps = ARBRE.body
    if classe:
        corps = next(n for n in ARBRE.body if isinstance(n, ast.ClassDef) and n.name == classe).body
    return next(n for n in corps if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.name == nom)


def _charger(ns, *noms, classe=None):
    """Exécute des fonctions (ou classes) de bot.py dans `ns`, sans leurs décorateurs
    (`@logs_group.command`, `@tasks.loop`…)."""
    for nom in noms:
        n = copy.deepcopy(_noeud(nom, classe))
        n.decorator_list = []
        exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def _v2_valide(kw, edition_webhook=False):
    """Comme discord.py, puis comme Discord : une carte V2 n'a ni texte libre ni embed (sinon 400)."""
    kw = dict(kw)
    kw.pop("ephemeral", None)
    p = handle_message_parameters(**kw) if edition_webhook else interaction_message_response_params(type=7, **kw)
    data = p.payload.get("data", p.payload)
    if (data.get("flags") or 0) & 32768:
        assert not data.get("content") and not data.get("embeds"), "Discord refuse une carte V2 avec du texte libre"


class Reponse:
    def __init__(self):
        self.fait, self.edits, self.messages, self.differe = False, [], [], None

    def is_done(self):
        return self.fait

    async def edit_message(self, **kw):
        if self.fait:
            raise discord.InteractionResponded(Obj())
        _v2_valide(kw)
        self.fait = True
        self.edits.append(kw)

    async def send_message(self, content=None, **kw):
        if self.fait:
            raise discord.InteractionResponded(Obj())
        self.fait = True
        self.messages.append((content, kw))

    async def defer(self, **kw):
        if self.fait:
            raise discord.InteractionResponded(Obj())
        self.fait, self.differe = True, kw


class Interaction:
    def __init__(self, guild=None, user=None):
        self.guild, self.user = guild, user or Obj(id=7)
        self.response, self.suivis, self.originaux = Reponse(), [], []
        parent = self

        class _Suivi:
            async def send(self, content=None, **kw):
                parent.suivis.append((content, kw))
        self.followup = _Suivi()

    async def edit_original_response(self, **kw):
        _v2_valide(kw, edition_webhook=True)
        self.originaux.append(kw)


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """La configuration des logs dans un dossier jetable."""
    monkeypatch.setattr(UL, "DATA_DIR", tmp_path)
    UL._CFG.clear()
    yield tmp_path
    UL._CFG.clear()


# ═══ 2. Mode site : /logs ne ment plus, et un salon choisi n'est plus purgé ══════════════════

def test_L1_en_mode_site_le_journal_n_a_aucun_salon_meme_pose_apres_coup(journal):
    asyncio.run(UL.activer_site(1, 77))
    asyncio.run(UL.set_log_channel(1, 88))  # l'ancien `/logs setchannel #annonces`, après le passage au site
    assert asyncio.run(UL.mode_site(1)) is True
    assert asyncio.run(UL.get_log_channel(1)) is None, "le repli des alertes d'escalade n'y écrit plus"
    assert UL.salons_de_logs(1) == set(), "plus rien à purger dans ce salon"
    asyncio.run(UL.set_log_channel(2, 55))  # hors mode site : rien ne change
    assert asyncio.run(UL.get_log_channel(2)) == 55 and UL.salons_de_logs(2) == {55}


def test_L2_le_menage_des_12_h_ne_touche_plus_au_salon_choisi_en_mode_site(journal):
    asyncio.run(UL.activer_site(1, 77))
    asyncio.run(UL.set_log_channel(1, 88))
    annonces, logs = Salon(88, "📢annonces"), Salon(77, "📋logs")
    g = Obj(id=1, get_channel={88: annonces, 77: logs}.get)
    conf = {"log_anti_raid": 77, "ticket_log": 0}
    purges = []

    async def cfg(_g):
        return conf

    async def noter(salon, *_a, **_k):
        purges.append(salon.id)
        return 0

    async def rien(*_a, **_k):
        return set()
    ns = _charger({"ulogger2026": UL, "cfg": cfg, "discord": discord, "bot": Obj(guilds=[g], user=Obj(id=9)),
                   "nettoyage": Obj(supprimer_vieux_fils=noter, purger_salon=noter), "_salons_de_flux": rien,
                   "suggestions": Obj(assurer_panneau=rien), "boosts": Obj(synchroniser=rien),
                   "_logerr": lambda *a, **k: purges.append(("ERREUR", a))},
                  "_salons_de_logs", "menage_salons_task")
    asyncio.run(ns["menage_salons_task"]())
    assert 88 not in purges, "le salon d'annonces n'est pas un salon de logs"
    assert purges == [77, 77], "les alertes du salon 📋logs gardent leur ménage de 30 jours"


def _espace_logs(ul, cfg=None):
    async def _cfg(_g):
        return cfg or {}
    return _charger({"ulogger2026": ul, "SUPER_OWNER_ID": 0, "discord": discord, "cfg": _cfg, "now": datetime.now,
                     "carte_embed": carte_embed, "print": lambda *a, **k: None, "bot": None,
                     "View": ui_v2.View, "LogsCategoriesSelect": None},
                    "_logs_sur_le_site", "logs_setchannel", "logs_categories", "logs_status")


def _proprio():
    alertes = Obj(id=77, mention="<#77>")
    return Obj(id=1, owner_id=5, get_channel={77: alertes}.get), Obj(id=5)


def test_L3_en_mode_site_setchannel_et_categories_disent_vrai_et_n_enregistrent_rien(journal):
    asyncio.run(UL.activer_site(1, 77))
    ns = _espace_logs(UL)
    g, proprio = _proprio()
    annonces = Obj(id=88, mention="<#88>", permissions_for=lambda _m: Obj(send_messages=True, embed_links=True))
    for appel in (lambda i: ns["logs_setchannel"](i, annonces), lambda i: ns["logs_setchannel"](i, None),
                  ns["logs_categories"]):
        i = Interaction(g, proprio)
        asyncio.run(appel(i))
        texte, kw = i.response.messages[-1]
        assert "sur le site" in texte and "rien n'a été changé" in texte and "<#77>" in texte
        assert "view" not in kw and kw.get("ephemeral") is True, "ni menu des catégories, ni réglage"
        assert "défini" not in texte and "activé" not in texte
    brut = UL._lire(1)
    assert brut["channel_id"] == 0 and "enabled_categories" not in brut, "rien n'a été enregistré"


def test_L4_hors_mode_site_setchannel_regle_toujours_le_salon():
    poses = []

    async def faux(*_a, **_k):
        return False

    async def poser(gid, cid):
        poses.append((gid, cid))

    async def rien(*_a, **_k):
        return None
    ul = Obj(mode_site=faux, set_log_channel=poser, log_event=rien, EventType=Obj(CONFIG_CHANGE="cfg"))
    ns = _espace_logs(ul)
    g, proprio = _proprio()
    i = Interaction(g, proprio)
    salon = Obj(id=88, mention="<#88>", permissions_for=lambda _m: Obj(send_messages=True, embed_links=True))
    g.me = Obj(id=9)
    asyncio.run(ns["logs_setchannel"](i, salon))
    assert poses == [(1, 88)] and "défini sur <#88>" in i.response.messages[-1][0]


def test_L5_le_statut_et_le_panneau_ne_promettent_plus_un_tri_par_categorie(journal):
    asyncio.run(UL.activer_site(1, 77))
    ns = _espace_logs(UL, cfg={"logs_sur_site_v1": "2026-10-19"})
    g, proprio = _proprio()
    i = Interaction(g, proprio)
    asyncio.run(ns["logs_status"](i))
    t = textes(i.response.messages[-1][1]["view"])
    assert "sur le site" in t and "Sans effet : le site garde tout" in t and "/logs categories" not in t

    async def cfg(_g):
        return {"tableau_salon": 0}
    espace = {"LayoutView": LayoutView, "cfg": cfg, "visuels": visuels, "Button": discord.ui.Button,
              "discord": discord, "Palette": Palette, "ulogger2026": UL,
              "v2_container": ui_v2.container, "v2_subtitle": ui_v2.subtitle, "v2_divider": ui_v2.divider,
              "v2_body": ui_v2.body, "v2_title": ui_v2.title}
    _charger(espace, "_afficher_panneau", "LogsPanelV2")
    vue = espace["LogsPanelV2"](proprio, Obj(id=1, get_channel=lambda _c: None))
    i = Interaction()
    asyncio.run(vue.render_to(i, edit=True))
    t = textes(i.response.edits[-1]["view"])
    assert "logsv2_cats" not in ids(vue), "le bouton « Catégories » ne changeait rien en mode site"
    assert "Catégories" not in t and "Détail par évènement" in t and "Rôles épargnés" in t
    assert set(ids(vue)) == {"logsv2_evts", "logsv2_excl", "logsv2_sec", "logsv2_back"}


# ═══ 3. /configure → « Fermer » ═══════════════════════════════════════════════════════════════

def test_F1_fermer_ferme_vraiment_le_panneau():
    erreurs, arrets = [], []
    ns = _charger({"carte_texte": carte_texte, "discord": discord,
                   "_logerr": lambda *a, **k: erreurs.append(a)}, "_close", classe="MainPanelV2")
    moi = Obj(stop=lambda: arrets.append(1))
    i = Interaction(guild=Obj(id=1))
    asyncio.run(ns["_close"](moi, i))
    assert erreurs == [] and arrets == [1]
    assert "Configuration fermée" in textes(i.response.edits[-1]["view"])
    i = Interaction(guild=Obj(id=1))
    i.response.fait = True  # déjà acquittée : on passe par la réponse d'origine
    asyncio.run(ns["_close"](moi, i))
    assert "Configuration fermée" in textes(i.originaux[-1]["view"]) and erreurs == []
    with pytest.raises(TypeError, match="Cannot mix embed and embeds"):  # l'ancien appel, reproduit
        _v2_valide(dict(content="✅", embed=None, embeds=[], view=None, attachments=[]))


# ═══ 4. Le bouton de langue survit à une base occupée au démarrage ═══════════════════════════

def test_I1_le_bouton_de_langue_est_enregistre_avant_et_hors_de_l_init_i18n():
    fn = next(n for n in ARBRE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_ready"
              and "i18n_module.init_db()" in ast.unparse(n))
    appel = "bot.add_dynamic_items(LangSelectButton)"
    porteurs = [t for t in ast.walk(fn) if isinstance(t, ast.Try)
                and any(ast.unparse(s) == appel for s in t.body)]
    assert len(porteurs) == 1, "un try à lui"
    assert [ast.unparse(s) for s in porteurs[0].body] == [appel], "rien d'autre dans ce try"
    corps = ast.unparse(fn)
    assert corps.index(appel) < corps.index("await i18n_module.init_db()"), "le bouton d'abord"


# ═══ 5. Salons de sécurité : le panneau revient, à jour ═══════════════════════════════════════

def _panneau_securite(conf, salons):
    async def db_get(_g):
        return dict(conf)

    async def db_set(_g, k, v):
        conf[k] = v
        return True
    verrous = []

    async def verrouiller(ch):
        verrous.append(ch.id)
        return {"success": True, "errors": []}
    erreurs = []
    ns = {"LayoutView": LayoutView, "db_get": db_get, "db_set": db_set, "visuels": visuels,
          "Button": discord.ui.Button, "discord": discord, "honeypot_module": Obj(apply_honeypot_perms=verrouiller),
          "_logerr": lambda *a, **k: erreurs.append(a), "LogsPanelV2": None,
          "v2_container": ui_v2.container, "v2_subtitle": ui_v2.subtitle, "v2_divider": ui_v2.divider,
          "v2_body": ui_v2.body}
    _charger(ns, "_afficher_panneau", "SecurityChannelsPanelV2")
    g = Obj(id=1, get_channel=salons.get)
    return ns["SecurityChannelsPanelV2"](Obj(id=7), g), verrous, erreurs


def _choisir(panneau, cle, salon_id):
    i = Interaction()
    asyncio.run(panneau.render_to(i, edit=True))
    bouton = next(b for b in panneau.walk_children()
                  if isinstance(b, discord.ui.Button) and b.custom_id == f"secch_set_{cle}")
    clic = Interaction()
    asyncio.run(bouton.callback(clic))
    choix = clic.response.edits[-1]["view"]
    sel = next(x for x in choix.walk_children() if isinstance(x, discord.ui.ChannelSelect))
    assert "Choisis le salon" in textes(choix), "le sélecteur s'affiche à la place du panneau"
    sel._values = [Obj(id=salon_id)]
    pick = Interaction()
    asyncio.run(sel.callback(pick))
    return pick


def test_S1_apres_le_choix_le_vrai_panneau_revient_avec_le_salon():
    conf = {}
    sanction = Obj(id=55, mention="<#55>")
    panneau, _v, erreurs = _panneau_securite(conf, {55: sanction})
    pick = _choisir(panneau, "staff_sanction_channel_id", 55)
    assert conf["staff_sanction_channel_id"] == 55 and pick.response.differe == {}
    assert "défini : <#55>" in pick.suivis[-1][0]
    retour = pick.originaux[-1]["view"]
    t = textes(retour)
    assert "🔘 **🚨 Staff Sanction** · <#55>" in t and "Choisis le salon" not in t
    assert {"secch_set_honeypot_channel_id", "secch_set_staff_sanction_channel_id", "secch_back"} <= set(ids(retour))
    assert erreurs == []


def test_S2_un_salon_piege_refuse_laisse_le_panneau_a_son_etat_reel():
    conf = {}

    class Habite:
        id, mention = 66, "<#66>"

        def history(self, limit=50):
            async def gen():
                yield Obj(author=Obj(bot=False), webhook_id=None)
            return gen()
    panneau, verrous, erreurs = _panneau_securite(conf, {66: Habite()})
    pick = _choisir(panneau, "honeypot_channel_id", 66)
    assert "honeypot_channel_id" not in conf and verrous == []
    assert "Des membres ont déjà écrit" in pick.suivis[-1][0]
    t = textes(pick.originaux[-1]["view"])
    assert "🍯 Honeypot** · _non défini_" in t, "le panneau revient, sans mentir"
    assert erreurs == []


# ═══ 6. Textes qui mentaient ══════════════════════════════════════════════════════════════════

def test_T1_le_bilan_sante_ne_parle_plus_d_ugc_ni_d_un_ecran_qui_ne_gere_pas_ces_flux():
    conf = {"direction_allowed_role": 1, "ads_youtube_feeds": [{"id": "UCx", "name": "@ancien"}]}
    erreurs = []

    async def cfg(_g):
        return conf
    ns = _charger({"cfg": cfg, "_logerr": lambda *a, **k: erreurs.append(a)}, "_bilan_sante_serveur")
    droits = Obj(manage_nicknames=True, ban_members=True, moderate_members=True, manage_roles=True,
                 manage_channels=False)
    g = Obj(id=1, me=Obj(guild_permissions=droits), get_channel=lambda _c: None)
    manques = asyncio.run(ns["_bilan_sante_serveur"](g))
    salons = next(m for m in manques if "Gérer les salons" in m)
    assert "UGC" not in salons and "vocaux temporaires" in salons and "mode lent" in salons
    flux = next(m for m in manques if "Flux YouTube" in m)
    assert "@ancien" in flux and "ancien réglage" in flux and "Ajouter un abonnement" in flux
    assert erreurs == []


def test_T2_le_panneau_social_ne_promet_plus_un_nettoyage_qui_n_existe_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(social_media, "DATA_DIR", tmp_path)
    monkeypatch.setattr(panels, "_global_manager", None)
    mgr = social_media.SocialMediaManager()
    for p in social_media.Platform:
        mgr.register_adapter(social_media.ManualAdapter(p))
    panels.set_social_manager(mgr)
    vue = panels.SocialMediaPanelV2(Obj(id=1, display_name="proprio"), Obj(id=1, name="S", get_channel=lambda c: None))
    i = Interaction()
    asyncio.run(vue.render_to(i))
    t = textes(vue)
    assert "auto-clean" not in t and "source supprime" not in t
    assert "Une seule annonce par post" in t and "live" in t
    #  Ce que le texte promet est ce que fait `cleanup_all` : seuls les lives sont revérifiés.
    assert "if not ann.is_currently_live:" in Path(social_media.__file__).read_text(encoding="utf-8")


# ═══ 7. /owner mod_stats acquitte avant de lire ═══════════════════════════════════════════════

def test_M1_mod_stats_acquitte_avant_les_lectures():
    vus = []

    async def montrer(i, days):
        vus.append((i.response.is_done(), days))
    ns = _charger({"SUPER_OWNER_ID": 0, "mod_dashboard_module": Obj(show=montrer), "discord": discord,
                   "_global_rl_active": lambda: False, "_arm_global_rl_backoff": lambda ex: None,
                   "_logerr": lambda *a, **k: None, "print": lambda *a, **k: None},
                  "_safe_defer", "_safe_followup", "owner_mod_stats_cmd")
    i = Interaction(Obj(id=1, owner_id=5), Obj(id=5))
    asyncio.run(ns["owner_mod_stats_cmd"](i, 900))
    assert vus == [(True, 365)], "acquittée AVANT les lectures, période bornée"
    assert i.response.differe == {"ephemeral": True}


# ═══ 8. Le rapport de minuit ne part plus dans un salon ═══════════════════════════════════════

def test_R1_le_rapport_de_minuit_est_capture_sans_rien_poster(tmp_path, monkeypatch):
    get_db, cfg, db_set, conf = base(tmp_path)
    conf["hub_channel"] = 42  # vieux réglage jamais remis à zéro
    envois = []

    class Hub:
        id = 42

        async def send(self, *a, **kw):
            envois.append(kw)
    g = Obj(id=1, name="S", member_count=10, get_channel=lambda cid: Hub() if cid == 42 else None)
    aides = {"LayoutView": LayoutView, "v2_title": ui_v2.title, "v2_subtitle": ui_v2.subtitle,
             "v2_body": ui_v2.body, "v2_divider": ui_v2.divider, "v2_container": ui_v2.container}
    for nom, val in (("_bot", Obj(guilds=[g])), ("_get_db", get_db), ("_db_get", cfg), ("_db_set", db_set),
                     ("_v2_helpers", aides), ("_tables_initialized", False)):
        monkeypatch.setattr(O, nom, val)

    class Minuit(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 24, 0, 10, tzinfo=O._PARIS_TZ)
    monkeypatch.setattr(O, "datetime", Minuit)

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE infractions(id INTEGER PRIMARY KEY, guild_id, user_id, created_at)")
            await db.execute("CREATE TABLE tickets(id INTEGER PRIMARY KEY, guild_id, status, created_at)")
            await db.commit()
        await O.daily_snapshot_task.coro()
        return await O.get_recent_snapshots(1, days=3)
    jours = [s["day"] for s in asyncio.run(scenario())]
    assert envois == [], "plus aucun rapport posté dans un salon"
    assert jours == ["2026-10-23"] and conf["obs_report_last_day"] == "2026-10-24", "la journée d'hier est gardée"
