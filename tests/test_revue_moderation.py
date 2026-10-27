"""Revue du 24/10/2026 — modération et sécurité : « des membres et des modérateurs sont sanctionnés à
tort ». Chaque constat de l'audit devient un test qui exécute le VRAI code de `bot.py` (source lue par
`ast`, doublures pour Discord), avec ses cas positifs : l'automodération doit toujours attraper les
vrais abus."""
from __future__ import annotations

import ast
import asyncio
import builtins
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord

import insult_filter
import protection_mineurs as pm
import staff_sanction
import ui_v2
from conftest_discord import Obj, base

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
TETE = 781205382923288593          # le fondateur
DIRECTION = 827633340797681714     # la direction


def _nom(n):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
        return n.targets[0].id
    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        return n.target.id
    return None


def _executer(noms, ns):
    """Exécute, dans l'ordre du fichier, les définitions nommées de bot.py (décorateurs ôtés)."""
    voulus = set(noms)
    for n in ARBRE.body:
        if _nom(n) in voulus:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = ast.parse(ast.unparse(n)).body[0]
                n.decorator_list = []
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def _source(nom):
    return next(ast.unparse(n) for n in ast.walk(ARBRE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


def run(coro):
    return asyncio.run(coro)


class Rien:
    """Doublure universelle : appelable, attendable, fausse — pour tout ce que le test ne regarde pas."""

    def __call__(self, *a, **k):
        return Rien()

    def __getattr__(self, nom):
        if nom.startswith("__"):
            raise AttributeError(nom)
        return Rien()

    def __await__(self):
        return iter(())

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())


class _Espace(dict):
    """Espace de noms : un nom inconnu (et qui n'est pas un builtin) vaut une doublure `Rien`."""

    def __missing__(self, nom):
        if hasattr(builtins, nom):
            raise KeyError(nom)
        return Rien()


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux serveur : rôles ordonnés, membres qui gardent la trace de ce qu'on leur fait
# ═══════════════════════════════════════════════════════════════════════════════

class Role:
    def __init__(self, rid, nom, position, managed=False, defaut=False):
        self.id, self.name, self.position, self.managed, self._defaut = rid, nom, position, managed, defaut

    def is_default(self):
        return self._defaut

    def __lt__(self, autre):
        return self.position < autre.position

    def __le__(self, autre):
        return self.position <= autre.position

    def __gt__(self, autre):
        return self.position > autre.position

    def __ge__(self, autre):
        return self.position >= autre.position

    def __eq__(self, autre):
        return isinstance(autre, Role) and autre.id == self.id

    def __hash__(self):
        return hash(self.id)


class Membre:
    def __init__(self, uid, *roles, admin=False, exclu=False, pseudo=None):
        self.id, self.bot, self.mention, self.name = uid, False, f"<@{uid}>", f"m{uid}"
        self.display_name, self.nick = f"Membre{uid}", pseudo
        self.roles = list(roles)
        self.guild_permissions = Obj(administrator=admin, mention_everyone=False)
        self.display_avatar = Obj(url="https://cdn.discordapp.com/a.png")
        self.exclu, self.journal, self.guild = exclu, [], None

    @property
    def top_role(self):
        return max(self.roles, key=lambda r: r.position)

    def is_timed_out(self):
        return self.exclu

    async def timeout(self, duree, reason=None):
        self.exclu = duree is not None
        self.journal.append(("timeout", duree))

    async def add_roles(self, *roles, reason=None):
        self.roles += [r for r in roles if r not in self.roles]
        self.journal.append(("+roles", [r.name for r in roles]))

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]
        self.journal.append(("-roles", [r.name for r in roles]))

    async def edit(self, **kw):
        if "nick" in kw:
            self.nick = kw["nick"]
        self.journal.append(("edit", kw.get("nick")))

    async def send(self, *a, **k):
        self.journal.append(("mp", a[0] if a else k))


class Serveur:
    def __init__(self, *roles, owner_id=1):
        self.id, self.owner_id, self.name = 1, owner_id, "GoRP"
        self.roles = list(roles)
        self.channels = []
        self.membres = {}
        self.default_role = next((r for r in roles if r.is_default()), None)
        self.me = Obj(top_role=Role(999, "bot", 100),
                      guild_permissions=Obj(manage_roles=True, kick_members=True, ban_members=True,
                                            moderate_members=True))

    def ajouter(self, m):
        m.guild = self
        self.membres[m.id] = m
        return m

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    def get_member(self, uid):
        return self.membres.get(uid)

    async def create_role(self, name, **kw):
        r = Role(500 + len(self.roles), name, 2)
        self.roles.append(r)
        return r


def _roles():
    return (Role(0, "@everyone", 0, defaut=True), Role(10, "Membre", 5), Role(20, "Modérateur", 40),
            Role(30, "Direction", 60), Role(40, "Admin", 80), Role(50, "Vérification", 3))


# ═══════════════════════════════════════════════════════════════════════════════
#  1 — L'ANTI-PHISHING LIT LE NOM D'HÔTE, PAS LE CHEMIN, ET NE CRIE PLUS « COMPTE PIRATÉ »
# ═══════════════════════════════════════════════════════════════════════════════

_NOMS_LIENS = (
    "_ZERO_WIDTH_RE", "_DOT_LOOKALIKE_RE", "_DEFANG_DOT_RE", "_DEFANG_SCHEME_RE", "_normalize_for_scan",
    "analyse_phishing", "check_phishing", "PHISHING_DOMAINS", "_DOMAINES_SANS_PREUVE_DE_VOL",
    "PHISHING_URL_PATTERNS", "DOMAINES_OFFICIELS", "_URL_COMPLETE", "_hote", "domaine_officiel",
    "sans_liens_officiels", "_MARQUES_IMITEES", "_DOMAINES_MARQUES", "_MOTS_APPAT", "_TLD_SUSPECTS", "_APPATS_TLD",
    "_SERVICES_LEGITIMES", "_JETONS_LEGITIMES", "_MARQUES_SANS_AUTRE_DOMAINE", "_SUFFIXES_DOUBLES",
    "_LETTRES_TROMPEUSES", "_CHIFFRES_TROMPEURS", "_HOTE_NU_RE", "_PHRASES_DE_PHISHING", "_texte_lisible",
    "_hote_lisible", "_squelette", "_SQUELETTES_OFFICIELS", "_SQUELETTES_MARQUES", "_SQUELETTES_APPAT",
    "_distance_osa", "_domaine_enregistrable", "_service_legitime", "_imitation_de_marque", "_analyse_hote",
    "_domaines_pieges_cites", "_normaliser_liens", "_phrase_de_phishing", "_vol_de_compte_prouve",
    "advanced_phishing_check", "_FREE_HOST_DOMAINS",
)


def _liens():
    return _executer(_NOMS_LIENS, {"re": re, "unicodedata": unicodedata})


LEGITIMES = [
    # Les exemples de l'audit, tous classés « phishing » avant le correctif.
    "https://discohook.app/?data=abc",
    "https://www.steamgifts.com/giveaways",
    "https://discussions.apple.com/thread/255",
    "https://support.microsoft.com/fr-fr/account-billing/manage-your-verification-code-settings-1f2b",
    "https://www.numerama.com/tech/discord-age-verification-royaume-uni",
    "https://www.lemonde.fr/pixels/article/discord-nitro-gratuit-arnaque_123.html",
    "https://www.01net.com/actualites/free-eth-arnaque.html",
    # Et les voisins honnêtes d'une marque.
    "https://disboard.org/fr/servers", "https://top.gg/bot/1", "https://discords.com/bots",
    "https://discord.me/serveur", "https://discordjs.guide/", "https://noblox.js.org/",
    "https://steamdb.info/app/730/", "https://steamcharts.com/app/730", "https://steamtrades.com/",
    "https://rolimons.com/item/1", "https://roblox.fandom.com/wiki/Robux", "https://rbxflip.com/",
    "https://roblox.github.io/roact/",
    "https://www.reddit.com/r/discordapp/comments/x/free_nitro", "https://medium.com/@x/claim-discord-nitro",
    "va voir orbit.door.com", "le site fish.store.com", "ton cadeau : discord.gift/AbCd",
]
PIEGES = [
    "https://dlscord-nitro.gift/claim", "https://discord-gift.ru/abc", "https://steamcommunlty.com/tradeoffer",
    "https://roblox.com.ru-login.xyz/login", "https://disсord.com/login",  # « с » cyrillique
    "https://d1scord.gg/x", "https://xn--dscord-pvf.com/", "https://rоblox.com/login",  # « о » cyrillique
    "https://discrodnitro.com/", "https://steamcommunity.co/id/x", "https://roblox-login.xyz/",
    "https://free-nitro.ru/", "hxxps://discord-gift[.]ru/claim", "dlscord-nitro.com/claim",
    "https://discord-nitro.pages.dev/", "https://grabify.link/AbC",
]


def test_R1_les_liens_honnetes_ne_sont_plus_du_phishing():
    ns = _liens()
    faux = [(u, ns["analyse_phishing"](u)) for u in LEGITIMES if ns["analyse_phishing"](u)[0]]
    assert not faux, faux


def test_R1_les_vrais_pieges_sont_toujours_pris():
    ns = _liens()
    rates = [u for u in PIEGES if not ns["check_phishing"](u)[0]]
    assert not rates, rates


def test_R1_seul_un_domaine_piege_connu_presume_un_compte_vole():
    ns = _liens()
    prouve = ns["_vol_de_compte_prouve"]
    assert prouve("free nitro https://steamcommunlty.com/x") and prouve("vite https://www.dlscord-nitro.com/claim")
    # Une ressemblance, un mouchard d'IP, un lien honnête, une mise en garde (domaine cité sans lien
    # cliquable, ou désamorcé) : retirés ou laissés, jamais « compte piraté ».
    for texte in ("https://roblox.com.ru-login.xyz/login", "https://d1scord.gg/x", "https://grabify.link/x",
                  "https://discohook.app/", "https://www.lemonde.fr/x/discord-nitro-gratuit-arnaque",
                  "attention à dlscord-nitro.com, c'est une arnaque", "hxxps://steamcommunlty[.]com/x"):
        assert not prouve(texte), texte


def test_R1_la_riposte_compte_pirate_est_reservee_a_la_preuve():
    corps = _source("on_message")
    i = corps.index("await _compromised_riposte(msg, 'phishing')")
    assert "if _vol_de_compte_prouve(ct):" in corps[i - 80:i]
    j = corps.index("await _compromised_riposte(msg, 'phishing (embed)')")
    assert "if _vol_de_compte_prouve(emb_url):" in corps[j - 80:j]
    assert "_compromised_riposte(msg, 'lien masqué')" not in corps
    assert corps.count("_compromised_riposte(") == 2


# ═══════════════════════════════════════════════════════════════════════════════
#  2 — LE STAFF ET LA TÊTE NE SONT JAMAIS SANCTIONNÉS PAR L'AUTOMODÉRATION
# ═══════════════════════════════════════════════════════════════════════════════

def _on_message(staff, config=None):
    journal = {"infractions": [], "hooks": []}

    async def cfg(_gid):
        return dict({"anti_insults": 1, "anti_threat": 1, "anti_doxxing": 0, "anti_shortener": 0,
                     "anti_red_keywords": 0, "anti_scam_image": 0, "anti_grooming": 0, "trust_system": 0},
                    **(config or {}))

    async def faux(*_a, **_k):
        return False

    async def immunite_staff(_m):
        return staff

    async def noter(*a, **_k):
        journal["infractions"].append(a[2])

    async def tache(*_a, **_k):
        return None

    async def piege(msg):
        journal["hooks"].append("honeypot")
        return False
    ns = _Espace(discord=discord, asyncio=asyncio, re=re, timedelta=timedelta, insult_filter=insult_filter,
                 cfg=cfg, is_immune=faux, is_fully_immune=immunite_staff, _record_infraction=noter,
                 update_realsy_activity=tache, _questions_hook=tache, _TACHES_QUESTIONS=set(),
                 _normalize_for_scan=lambda t: t, honeypot_module=Obj(on_message_hook=piege))
    _executer(("_URL_INMSG_RE", "_GAMING_CTX_RE", "_deobfuscate_for_insult", "_OBF_PUNCT", "_OBF_SEP",
               "_ZERO_WIDTH_RE", "on_message"), ns)
    return ns, journal


def _message(contenu, auteur, salon_id=5):
    async def supprimer():
        auteur.journal.append(("supprimé",))
    return Obj(guild=Obj(id=1, owner_id=1), author=auteur, content=contenu, channel=Obj(id=salon_id, mention="#x"),
               role_mentions=[], mention_everyone=False, mentions=[], message_snapshots=[], attachments=[],
               embeds=[], reference=None, delete=supprimer)


def test_R2_un_modo_n_est_plus_exclu_pour_une_phrase_que_l_automod_croit_menacante():
    for staff, attendu in ((True, []), (False, ["supprimé", "timeout"])):
        ns, journal = _on_message(staff)
        auteur = Membre(77, Role(20, "Modérateur", 40))
        run(ns["on_message"](_message("je sais où tu habites", auteur)))
        assert [e[0] for e in auteur.journal] == attendu, (staff, auteur.journal)
        assert journal["infractions"] == ([] if staff else ["menace"])


def test_R2_a_l_edition_la_meme_exemption():
    corps = _source("_scan_security_on_edit")
    assert "if await is_immune(author, 'general', after.channel) or await is_fully_immune(author):" in corps
    envoi = _source("on_message")
    assert "user_immune = _immunite_reglee or await is_fully_immune(msg.author)" in envoi
    # Les scanners de secrets gardent leur propre logique : exemption calculée à part, jetons retirés.
    assert "sanctionner=not await is_fully_immune(msg.author)" in envoi
    assert "sanctionner=not exempt" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  3 · 9 — LA QUARANTAINE GARDE LES RÔLES, LES REND, ET REFUSE TOUT ; /mod unmute À SA PLACE
# ═══════════════════════════════════════════════════════════════════════════════

_NOMS_ISOLEMENT = ("_QUARANTINE_ROLE_NAMES", "_ISOLATION_TIMEOUT_DAYS", "_quarantaine_overwrite",
                   "_VERROUS_QUARANTAINE", "_verrouiller_salons_quarantaine", "_lancer_verrou_quarantaine",
                   "_ensure_quarantine_role", "_SQL_ISOLEMENTS", "_noter_isolement", "_isolement_actif",
                   "_rendre_roles_isolement", "isolate_member", "lift_isolation")


def _isolement(tmp_path, **extra):
    get_db, _cfg, _set, _conf = base(tmp_path)
    ns = _Espace(discord=discord, asyncio=asyncio, json=json, aiosqlite=aiosqlite, timedelta=timedelta,
                 get_db=get_db, _logerr=lambda *a, **k: None, _is_sensitive_role=lambda r: not r.is_default(),
                 **extra)
    return _executer(_NOMS_ISOLEMENT, ns), get_db


def test_R3_le_refus_couvre_fils_forums_reactions_et_vocal_mais_laisse_lire():
    ow = _executer(("_quarantaine_overwrite",), {"discord": discord})["_quarantaine_overwrite"]()
    refuse = {k for k, v in ow if v is False}
    assert refuse == {"send_messages", "send_messages_in_threads", "create_public_threads",
                      "create_private_threads", "add_reactions", "connect", "speak"}
    assert ow.view_channel is None and ow.read_message_history is None, "un isolement n'est pas une radiation"
    assert "overwrite=_quarantaine_overwrite()" in _source("on_guild_channel_create"), "les salons créés ensuite"


def test_R3_les_roles_retires_sont_gardes_puis_rendus(tmp_path):
    ns, get_db = _isolement(tmp_path)
    roles = _roles()
    g = Serveur(*roles)
    m = g.ajouter(Membre(42, roles[0], roles[1], roles[2], pseudo="Max"))

    async def scenario():
        res = await ns["isolate_member"](m, "Kick d'un modérateur changé en isolement")
        assert res["isolated"] and res["method"] == "role+timeout", res
        assert {r.name for r in m.roles} == {"@everyone", "Vérification"}
        # Un second isolement ne remplace pas les rôles gardés (il n'en reste plus à retirer).
        await ns["isolate_member"](m, "encore")
        assert (await ns["_isolement_actif"](1, 42)) == {"roles": [10, 20], "genre": "securite"}
        assert await ns["lift_isolation"](m)
        assert {r.name for r in m.roles} == {"@everyone", "Membre", "Modérateur"}, "les rôles sont rendus"
        assert not m.exclu
        assert (await ns["_isolement_actif"](1, 42)) is None, "la fiche est effacée"
        await asyncio.sleep(0)
    run(scenario())


def _unmute(tmp_path, auteur, membre, g):
    ns, get_db = _isolement(tmp_path)
    reponses = []

    async def oui(*_a, **_k):
        return True

    async def dire(texte=None, **_k):
        reponses.append(texte)

    async def rien(*_a, **_k):
        return None
    ns.update(check_mod_perm=oui, C=Obj(GREEN=0x2ECC71), now=lambda: datetime.now(timezone.utc),
              _announce_sanction_public=rien, send_mod_log=rien)
    _executer(("TETE_IDS", "_a_la_tete", "_RADIE_ROLE_NAME", "unmute_cmd"), ns)
    i = Obj(guild=g, user=auteur, response=Obj(send_message=dire, defer=rien), followup=Obj(send=dire))
    return ns, i, reponses


def test_R9_un_isolement_de_securite_n_est_leve_que_par_la_tete(tmp_path):
    roles = _roles()
    g = Serveur(*roles)
    cible = g.ajouter(Membre(42, roles[0], roles[1], roles[2]))
    modo = g.ajouter(Membre(7, roles[0], roles[3]))   # Direction par son rôle, mais pas la tête
    ns, i, reponses = _unmute(tmp_path, modo, cible, g)

    async def scenario():
        await ns["isolate_member"](cible, "raid")
        await ns["unmute_cmd"](i, cible, "test")
        assert "isolement de sécurité" in reponses[-1] and cible.exclu, "le staff ne le lève pas"
        i.user = g.ajouter(Membre(TETE, roles[0], roles[1]))
        await ns["unmute_cmd"](i, cible, "faux positif")
        assert not cible.exclu and {r.name for r in cible.roles} >= {"Membre", "Modérateur"}
        assert "Rôles rendus" in reponses[-1]
    run(scenario())


def test_R9_le_mute_permanent_des_recidivistes_reste_levable_par_le_staff(tmp_path):
    roles = _roles()
    g = Serveur(*roles)
    cible = g.ajouter(Membre(42, roles[0], roles[1], roles[5], exclu=True))
    modo = g.ajouter(Membre(7, roles[0], roles[2]))
    ns, i, reponses = _unmute(tmp_path, modo, cible, g)

    async def scenario():
        await ns["_noter_isolement"](1, 42, [], "Blacklist (7 infractions en 14 j)", "escalade")
        await ns["unmute_cmd"](i, cible, "il a compris")
        assert not cible.exclu and "Vérification" not in {r.name for r in cible.roles}, reponses
    run(scenario())


def test_R9_hierarchie_et_radiation(tmp_path):
    roles = _roles()
    g = Serveur(*roles)
    modo = g.ajouter(Membre(7, roles[0], roles[2]))
    chef = g.ajouter(Membre(8, roles[0], roles[3], exclu=True))
    ns, i, reponses = _unmute(tmp_path, modo, chef, g)
    run(ns["unmute_cmd"](i, chef, "x"))
    assert "rang égal ou supérieur" in reponses[-1] and chef.exclu
    radie = g.ajouter(Membre(9, roles[0], Role(60, "🚫 Radié", 1), exclu=True))
    run(ns["unmute_cmd"](i, radie, "x"))
    assert "/off off" in reponses[-1] and radie.exclu


# ═══════════════════════════════════════════════════════════════════════════════
#  4 — QUITTER PUIS REVENIR N'EFFACE AUCUNE SANCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _retour(tmp_path):
    ns, get_db = _isolement(tmp_path, datetime=datetime, timezone=timezone,
                            now=lambda: datetime.now(timezone.utc), _VERROUS_RADIATION=set())
    _executer(("_RADIE_ROLE_NAME", "_RADIE_COULEUR", "_radie_pseudo", "_verrouiller_salons_radie",
               "_radie_overwrite", "_reposer_sanction_au_retour"), ns)
    return ns, get_db


def test_R4_un_radie_qui_revient_retrouve_sa_radiation_et_aucun_role(tmp_path):
    ns, get_db = _retour(tmp_path)
    roles = _roles() + (Role(60, "🚫 Radié", 1),)
    g = Serveur(*roles)

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE radiated_members (guild_id INTEGER, user_id INTEGER, saved_roles TEXT, "
                             "reason TEXT, by_user_id INTEGER, saved_nick TEXT, appel_utilise INTEGER)")
            await db.execute("INSERT INTO radiated_members VALUES (1, 42, '[10]', 'attaque', 8, '', 0)")
            await db.commit()
        radie = g.ajouter(Membre(42, roles[0]))
        assert await ns["_reposer_sanction_au_retour"](radie) == "radiation"
        assert "🚫 Radié" in {r.name for r in radie.roles} and radie.nick.startswith("⛔ RADIÉ-")
        libre = g.ajouter(Membre(43, roles[0]))
        assert await ns["_reposer_sanction_au_retour"](libre) == "" and libre.journal == []
    run(scenario())


def test_R4_isolement_et_restriction_aussi_mais_pas_une_restriction_echue(tmp_path):
    ns, get_db = _retour(tmp_path)
    roles = _roles() + (Role(70, "🔒 Restricted", 1),)
    g = Serveur(*roles)

    async def scenario():
        await ns["_noter_isolement"](1, 42, [10], "raid")
        isole = g.ajouter(Membre(42, roles[0]))
        assert await ns["_reposer_sanction_au_retour"](isole) == "isolement"
        assert "Vérification" in {r.name for r in isole.roles}
        async with get_db() as db:
            await db.execute("CREATE TABLE restricted_members (guild_id INTEGER, user_id INTEGER, roles_backup TEXT, "
                             "restricted_at TEXT, duration INTEGER, reason TEXT, restricted_by INTEGER)")
            maintenant = datetime.now(timezone.utc)
            await db.execute("INSERT INTO restricted_members VALUES (1, 50, '[]', ?, 0, 'x', 8)",
                             (maintenant.isoformat(),))
            await db.execute("INSERT INTO restricted_members VALUES (1, 51, '[]', ?, 60, 'x', 8)",
                             ((maintenant - timedelta(hours=3)).isoformat(),))
            await db.commit()
        restreint = g.ajouter(Membre(50, roles[0]))
        assert await ns["_reposer_sanction_au_retour"](restreint) == "restriction"
        assert "🔒 Restricted" in {r.name for r in restreint.roles}
        echu = g.ajouter(Membre(51, roles[0]))
        assert await ns["_reposer_sanction_au_retour"](echu) == "" and echu.journal == []
        await asyncio.sleep(0)
    run(scenario())


def test_R4_la_sanction_passe_avant_tout_role_d_arrivee():
    corps = _source("on_member_join")
    i_sanction = corps.index("_reposer_sanction_au_retour(m)")
    assert i_sanction < corps.index("_rendre_roles_au_retour(m)") < corps.index("welcome_autorole")
    assert corps.count("not m.bot and (not _sanctionne)") == 3, "anciens rôles, auto-rôle, rôle de langue"
    assert "_handle_welcome(m)" in corps, "l'accueil n'est pas touché"


# ═══════════════════════════════════════════════════════════════════════════════
#  5 — L'ANTI-QR NE PUNIT PLUS QUI MET EN GARDE
# ═══════════════════════════════════════════════════════════════════════════════

def test_R5_une_mise_en_garde_n_est_pas_une_arnaque():
    qr = _executer(("_QR_SUPPORT_RE", "check_qr_code_scam"), {"re": re})["check_qr_code_scam"]
    assert not qr("ne scannez jamais un QR code qu'on vous envoie")[0]
    assert not qr("attention, ne scanne pas le qr code que ce mec envoie en mp")[0]
    assert qr("scannez ce qr pour vérifier votre compte https://discord-verify.xyz/qr")[0]
    assert qr("scan the qr code to claim your nitro discord.gg/abcd")[0]
    assert qr("scan this qr code to get free robux", True)[0], "une image à scanner"


def test_R5_par_defaut_on_supprime_sans_exclure():
    assert "'qrcode_action': 'delete'" in SRC and "'qrcode_action': 'mute'" not in SRC
    table = next(n for n in ARBRE.body if _nom(n) == "_PROT_DEFAULT_ACTIONS")
    assert ast.literal_eval(table.value)["anti_qrcode"] == "delete"
    corps = _source("on_message")
    assert "check_qr_code_scam(ct, _msg_has_image(msg))" in corps
    assert "c.get('qrcode_action', 'delete')" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  6 — LE LEXIQUE : « FERME LA PORTE » N'EST PAS UNE INSULTE, LA HAINE RESTE LA HAINE
# ═══════════════════════════════════════════════════════════════════════════════

def _vise(texte, reponse=False):
    ns = _executer(("_INSULT_TARGET_RE", "_MENTION_ECRITE_RE", "_insulte_visee"), {"re": re})
    return ns["_insulte_visee"](Obj(content=texte, reference=object() if reponse else None), texte)


def test_R6_ferme_la_seulement_dans_un_message_court():
    for texte in ("ferme la porte tu laisses entrer le froid", "ferme la porte", "ferme la fenêtre stp",
                  "tu peux fermer la porte ? ferme la vite on a froid ici dans la base"):
        assert insult_filter.scan(texte)[0] < 2, texte
    for texte in ("ferme la", "ferme-la", "ferme la toi", "oh ferme la toi", "ferme-la tu saoules"):
        assert insult_filter.scan(texte)[0] == 2, texte
    assert _vise("ferme la toi") and _vise("ferme la", reponse=True)
    assert insult_filter.scan("ferme ta gueule")[0] == 2, "les vraies formes restent"


def test_R6_le_lexique_de_haine_n_a_plus_ces_mots_de_jeu():
    lex = json.loads((RACINE / "insult_lexicon.json").read_text(encoding="utf-8"))
    for mot in ("cripple", "mudblood", "ostfront", "subnormal"):
        assert mot not in lex["tier3"], mot
    for texte in ("you cripple their economy with this build", "le mudblood du jeu harry potter",
                  "l'ostfront dans hearts of iron", "un float subnormal en ieee-754"):
        assert insult_filter.scan(texte)[0] < 3, texte
    assert insult_filter.scan("sale bamboula")[0] == 3, "la haine reste de la haine"


# ═══════════════════════════════════════════════════════════════════════════════
#  7 — LE SALON-PIÈGE JUGE AUSSI LES MESSAGES SANS TEXTE
# ═══════════════════════════════════════════════════════════════════════════════

def test_R7_une_image_seule_dans_le_salon_piege_passe_par_le_piege():
    ns, journal = _on_message(staff=False)
    auteur = Membre(77, Role(10, "Membre", 5))
    run(ns["on_message"](_message("", auteur)))
    assert journal["hooks"] == ["honeypot"], "le piège voit les messages sans texte"
    corps = _source("_scan_security_on_edit")
    assert "if _mod is not honeypot_module and (not after.content):" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  8 — LEVER UNE RADIATION : SEULEMENT S'IL Y EN A UNE, ET DANS LA HIÉRARCHIE
# ═══════════════════════════════════════════════════════════════════════════════

def _levee(tmp_path, avec_table=True):
    get_db, *_ = base(tmp_path)
    ns = _Espace(discord=discord, json=json, aiosqlite=aiosqlite, get_db=get_db,
                 owner_ids_module=Obj(is_super_owner=lambda uid: uid == TETE),
                 TETE_IDS=frozenset({TETE, 827633340797681714}))
    _executer(("_RADIE_ROLE_NAME", "_refus_rang_radie", "_lever_radiation"), ns)   # 26/10/2026 : la hiérarchie partagée

    async def creer():
        async with get_db() as db:
            await db.execute("CREATE TABLE radiated_members (guild_id INTEGER, user_id INTEGER, saved_roles TEXT, "
                             "reason TEXT, by_user_id INTEGER, saved_nick TEXT, appel_utilise INTEGER)")
            await db.execute("INSERT INTO radiated_members VALUES (1, 42, '[10, 40]', 'x', 8, 'Max', 0)")
            await db.commit()
    if avec_table:
        run(creer())
    return ns, get_db


def test_R8_rien_a_lever_sans_radiation(tmp_path):
    roles = _roles()
    for avec_table in (False, True):
        (tmp_path / str(avec_table)).mkdir()
        ns, _ = _levee(tmp_path / str(avec_table), avec_table)
        g = Serveur(*roles)
        muet = g.ajouter(Membre(99, roles[0], roles[1], exclu=True, pseudo="Pseudo"))
        erreur = run(ns["_lever_radiation"](g, muet, g.ajouter(Membre(TETE, roles[0], roles[4])), "x"))
        assert erreur and "pas radié" in erreur
        assert muet.journal == [] and muet.exclu and muet.nick == "Pseudo", "le mute d'un autre modo reste"


def test_R8_la_hierarchie_compte_les_roles_d_avant_la_radiation(tmp_path):
    roles = _roles() + (Role(60, "🚫 Radié", 1),)
    ns, get_db = _levee(tmp_path)
    g = Serveur(*roles)
    radie = g.ajouter(Membre(42, roles[0], roles[6], exclu=True))   # avait Admin (80) avant
    direction = g.ajouter(Membre(8, roles[0], roles[3]))
    erreur = run(ns["_lever_radiation"](g, radie, direction, "recours"))
    assert erreur and "propriétaire" in erreur and radie.exclu
    assert run(ns["_lever_radiation"](g, radie, g.ajouter(Membre(1, roles[0])), "recours")) is None  # le propriétaire
    assert not radie.exclu and {r.name for r in radie.roles} == {"@everyone", "Membre", "Admin"}
    assert radie.nick == "Max"


# ═══════════════════════════════════════════════════════════════════════════════
#  10 — « T'ES SEUL ? » N'EST UNE APPROCHE QUE « CHEZ TOI »
# ═══════════════════════════════════════════════════════════════════════════════

def test_R10_chercher_un_coequipier_n_est_pas_une_approche():
    for texte in ("t'es seul ? mp moi on fait le donjon", "are you alone ? dm me lets do the dungeon",
                  "tu es seule ou en team ? viens en mp", "t'es tout seul sur la map, mp moi"):
        r = pm.analyser(texte)
        assert not r["touche"], (texte, r["motif"])


def test_R10_les_vraies_approches_restent_attrapees():
    for texte in ("t'es seul chez toi ? mp moi", "tu es seule dans ta chambre ? envoie une photo de toi",
                  "how old are you ? are you alone", "are you home alone ? dm me",
                  "t'as quel age ? t'es seul ?", "tes parents sont pas la ? ajoute mon snap"):
        assert pm.analyser(texte)["touche"], texte


# ═══════════════════════════════════════════════════════════════════════════════
#  11 — KICK/BAN DEPUIS LA FICHE : LE MESSAGE PRIVÉ DIT CE QUI EST VRAIMENT FAIT
# ═══════════════════════════════════════════════════════════════════════════════

def _fiche(tmp_path, *, fondateur, applique):
    tmp_path.mkdir(parents=True, exist_ok=True)
    get_db, *_ = base(tmp_path)
    faits = []

    async def oui(*_a, **_k):
        return True

    async def dm(cible, guild, titre, raison, duration_text=None):
        faits.append(("mp", titre))

    async def sanction(cible, action, minutes, raison, guild, actor_id=None):
        faits.append(("sanction", action))
        return applique

    async def rien(*_a, **_k):
        return None
    ns = _Espace(discord=discord, get_db=get_db, check_mod_perm=oui, _dm_sanction=dm, sanction=sanction,
                 _staff_sanction_guard=lambda *a: (True, None), send_mod_log=rien, _logerr=lambda *a, **k: None,
                 owner_ids_module=Obj(is_super_owner=lambda uid: fondateur), _format_warn_id=str)
    _executer(("_STAFF_SANCTION_META", "_StaffSanctionModal"), ns)
    return ns, faits, get_db


def _soumettre(ns, action, cible, faits):
    reponses = []

    async def suivre(texte=None, **_k):
        reponses.append(texte)

    async def rien(*_a, **_k):
        return None
    g = Serveur(*_roles())
    g.ajouter(cible)

    async def scenario():
        async with ns["get_db"]() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY, guild_id INTEGER, "
                             "user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, duration TEXT)")
            await db.commit()
        modal = ns["_StaffSanctionModal"](action, cible)
        modal.reason_in = Obj(value="spam de liens")
        if action == "mute":
            modal.duration_in = Obj(value="60")

        async def mp(*a, **_k):
            faits.append(("correction", a[0] if a else ""))
        cible.send = mp
        i = Obj(guild=g, user=Membre(7, Role(20, "Modérateur", 40)),
                response=Obj(is_done=lambda: False, defer=rien), followup=Obj(send=suivre))
        await modal.on_submit(i)
    run(scenario())
    return reponses


def test_R11_un_kick_de_modo_devient_un_isolement_et_le_mp_le_dit_apres(tmp_path):
    ns, faits, _ = _fiche(tmp_path, fondateur=False, applique=True)
    reponses = _soumettre(ns, "kick", Membre(42, Role(10, "Membre", 5)), faits)
    assert faits == [("sanction", "kick"), ("mp", "Isolement 🛡️ (en attente de la décision du fondateur)")]
    assert "isolé" in reponses[-1]


def test_R11_une_action_ratee_n_est_jamais_annoncee(tmp_path):
    ns, faits, _ = _fiche(tmp_path / "a", fondateur=False, applique=False)
    _soumettre(ns, "mute", Membre(42, Role(10, "Membre", 5)), faits)
    assert faits == [("sanction", "mute")], "pas de « Mute » annoncé pour un mute raté"
    ns, faits, _ = _fiche(tmp_path / "b", fondateur=True, applique=False)
    _soumettre(ns, "ban", Membre(43, Role(10, "Membre", 5)), faits)
    assert [f[0] for f in faits] == ["mp", "sanction", "correction"], "prévenu avant, corrigé après l'échec"


def test_R11_le_mute_reussi_part_apres(tmp_path):
    ns, faits, _ = _fiche(tmp_path, fondateur=False, applique=True)
    _soumettre(ns, "mute", Membre(42, Role(10, "Membre", 5)), faits)
    assert faits == [("sanction", "mute"), ("mp", "Mute 🔇")]


# ═══════════════════════════════════════════════════════════════════════════════
#  12 — LE PANNEAU D'ACTION STAFF : PAS DE PING, ET « WARN » INSCRIT AU CASIER
# ═══════════════════════════════════════════════════════════════════════════════

def test_R12_la_carte_du_panneau_ne_pingue_pas_la_cible(tmp_path):
    get_db, *_ = base(tmp_path)
    envois = []

    class Salon:
        id = 66

        async def send(self, **kw):
            envois.append(kw)
            return Obj(id=900)

    async def config(_gid):
        return {"staff_sanction_channel_id": 66}
    helpers = {"v2_title": ui_v2.title, "v2_subtitle": ui_v2.subtitle, "v2_body": ui_v2.body,
               "v2_divider": ui_v2.divider, "v2_container": ui_v2.container, "LayoutView": ui_v2.LayoutView}
    staff_sanction.setup(None, get_db, config, helpers)
    g = Obj(id=1, get_channel=lambda cid: Salon() if cid == 66 else None, text_channels=[])

    async def scenario():
        await staff_sanction.init_db()
        await staff_sanction.create_sanction_panel(g, Obj(id=42, mention="<@42>", name="cible"), "jeton posté")
    try:
        run(scenario())
    finally:
        staff_sanction.setup(None, None, None, None)
    assert envois and envois[-1]["allowed_mentions"].users is False


def test_R12_warn_inscrit_l_avertissement_au_casier(tmp_path):
    get_db, *_ = base(tmp_path)
    avertis, suivis = [], []

    async def avertir(guild, membre_id, mod_id, raison):
        avertis.append((membre_id, mod_id, raison))
        return 3, "🔇 Mute automatique : 10 minutes"

    async def config(_gid):
        return {}
    staff_sanction.setup(None, get_db, config, {}, avertir=avertir)

    async def suivre(texte=None, **_k):
        suivis.append(texte)

    async def rien(*_a, **_k):
        return None

    async def scenario():
        await staff_sanction.init_db()
        async with get_db() as db:
            await db.execute("INSERT INTO staff_sanction_log (guild_id, target_user_id, reason) VALUES (1, 42, 'insultes')")
            await db.commit()
        cible = Membre(42, Role(10, "Membre", 5))
        #  26/10/2026 (sécurité) : le membre du staff qui clique a un rang (le panneau refuse une cible égale ou plus haute).
        i = Obj(guild=Obj(id=1, owner_id=1, get_member=lambda uid: cible if uid == 42 else None),
                user=Obj(id=7, top_role=Role(40, "Modération", 40)),
                channel=Obj(permissions_for=lambda _u: Obj(manage_messages=True)),
                response=Obj(defer=rien, send_message=rien, is_done=lambda: True), followup=Obj(send=suivre),
                message=Obj(delete=rien))
        await staff_sanction._handle_sanction_click(i, 1, "warn")
        async with get_db() as db:
            async with db.execute("SELECT final_action FROM staff_sanction_log WHERE id=1") as cur:
                assert (await cur.fetchone())[0] == "warned"
    try:
        run(scenario())
    finally:
        staff_sanction.setup(None, None, None, None)
    assert avertis == [(42, 7, "insultes")]
    assert "inscrit au casier (3 au total)" in suivis[-1] and "Mute automatique" in suivis[-1]
    assert "avertir=_avertissement_staff" in SRC


def test_R12_l_avertissement_du_panneau_suit_le_circuit_de_mod_warn(tmp_path):
    get_db, *_ = base(tmp_path)
    paliers = []

    async def escalade(g, membre, total):
        paliers.append(total)
        return None
    ns = _Espace(get_db=get_db, _escalade_warns=escalade)
    _executer(("_inscrire_sanction", "_avertissement_staff"), ns)
    g = Serveur(*_roles())
    g.ajouter(Membre(42, Role(10, "Membre", 5)))

    async def scenario():
        async with get_db() as db:
            await db.execute("CREATE TABLE infractions (id INTEGER PRIMARY KEY, guild_id INTEGER, user_id INTEGER, "
                             "mod_id INTEGER, type TEXT, reason TEXT, duration TEXT)")
            await db.commit()
        assert await ns["_avertissement_staff"](g, 42, 7, "insultes") == (1, None)
        assert await ns["_avertissement_staff"](g, 42, 7, "encore") == (2, None)
        async with get_db() as db:
            async with db.execute("SELECT user_id, mod_id, type FROM infractions") as cur:
                assert await cur.fetchall() == [(42, 7, "warn"), (42, 7, "warn")]
    run(scenario())
    assert paliers == [1, 2]


# ═══════════════════════════════════════════════════════════════════════════════
#  13 — LES CARTES V2 RESTENT DES CARTES V2
# ═══════════════════════════════════════════════════════════════════════════════

def test_R13_fermer_le_scanner_ne_met_pas_de_texte_sur_une_carte_v2():
    classe = next(n for n in ARBRE.body if _nom(n) == "SuspectScanPanelV2")
    fermer = next(ast.unparse(f) for f in classe.body if getattr(f, "name", "") == "_cb_close")
    assert "content=" not in fermer and "view=carte_texte(" in fermer
