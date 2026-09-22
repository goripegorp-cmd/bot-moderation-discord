"""Ce qui devait être cliqué à la main, et que le bot fait maintenant seul.

═══════════════════════════════════════════════════════════════════════════════
LE CONTEXTE (22/09/2026) — « fait tout le reste »
═══════════════════════════════════════════════════════════════════════════════
Trois livraisons étaient PARFAITES ET MUETTES, faute d'un clic dans le panneau :

  · le flux UGC (03/09) n'a jamais publié une fiche : il exige un salon et n'a
    pas de repli, exprès ;
  · le panneau unifié de tickets (06/09) était posté nulle part, les anciens
    panneaux par type restaient seuls en place ;
  · trois manques ne peuvent PAS être réparés par un bot — une permission
    absente, un rôle placé au-dessus du sien, un rôle Direction que personne
    n'a désigné — et ils n'étaient dits que dans mes messages.

⚠️ ET UN PIÈGE ATTRAPÉ EN COURS DE ROUTE, qui aurait tout éteint : en insérant
`_installer_salon_ugc` juste avant `veille_roblox_task`, le décorateur
`@tasks.loop(minutes=30)` s'est retrouvé sur la NOUVELLE fonction. La veille
Roblox n'était plus une boucle du tout — `.start()` aurait levé, et plus une
seule publication ne serait partie. `test_L1` verrouille ça pour toujours.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _src(nom: str) -> str:
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


# ═══════════════════════════════════════════════════════════════════════════════
#  L — les boucles sont bien des boucles
# ═══════════════════════════════════════════════════════════════════════════════

def _decorateurs(nom: str) -> list:
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return [ast.unparse(d) for d in n.decorator_list]
    raise AssertionError(f"{nom} introuvable")


def test_L1_toutes_les_boucles_supervisees_portent_leur_decorateur():
    """⚠️ LE PIÈGE RÉEL DU JOUR. Une fonction insérée entre un décorateur et sa
    fonction déplace le décorateur : la boucle n'en est plus une, et
    `.start()` échoue au démarrage — bot silencieux, aucune erreur de syntaxe,
    aucun test classique ne le voit."""
    i = SRC.index("_SUPERVISED_LOOP_NAMES")
    bloc = SRC[i:SRC.index("]", i) + 1]
    noms = [m.strip().strip('"\'') for m in bloc.split("[", 1)[1].rstrip("]").split(",")]
    noms = [n for n in noms if n and not n.startswith("#")]
    assert noms, "liste des boucles supervisées introuvable"
    for nom in noms:
        try:
            decos = _decorateurs(nom)
        except AssertionError:
            continue                       # boucle définie dans un module
        assert any("tasks.loop" in d for d in decos), (
            f"{nom} est supervisée mais n'est plus décorée par @tasks.loop : "
            f"décorateurs = {decos}")


def test_L2_la_veille_roblox_est_une_boucle_de_30_minutes():
    """Elle a perdu son décorateur pendant cette session. Jamais deux fois."""
    assert any("tasks.loop(minutes=30)" in d
               for d in _decorateurs("veille_roblox_task"))
    assert not _decorateurs("_installer_salon_ugc"), (
        "_installer_salon_ugc a récupéré un décorateur qui ne lui appartient pas")


# ═══════════════════════════════════════════════════════════════════════════════
#  T — les panneaux de tickets
# ═══════════════════════════════════════════════════════════════════════════════

class FauxComposant:
    """Un bouton enfoui comme en Components V2 : Container → Section → accessory."""

    def __init__(self, custom_id=None, children=(), accessory=None):
        self.custom_id = custom_id
        self.children = list(children)
        self.accessory = accessory


class FauxMessage:
    def __init__(self, mid, auteur_id, composants, journal):
        self.id, self.components = mid, list(composants)
        self.author = type("A", (), {"id": auteur_id})()
        self._j = journal

    async def delete(self):
        self._j.append(f"supprime:{self.id}")


class FauxPerms:
    view_channel = read_message_history = True
    send_messages = manage_channels = True


class FauxSalon:
    def __init__(self, cid, messages, journal, envoi_casse=False):
        self.id, self.name, self._m = cid, f"salon{cid}", list(messages)
        self._j, self._casse = journal, envoi_casse
        self.category = None

    def permissions_for(self, _me):
        return FauxPerms()

    def history(self, limit=50):
        msgs = self._m[:limit]

        class _It:
            def __aiter__(self_inner):
                self_inner._i = iter(msgs)
                return self_inner

            async def __anext__(self_inner):
                try:
                    return next(self_inner._i)
                except StopIteration:
                    raise StopAsyncIteration
        return _It()

    async def send(self, *a, **kw):
        if self._casse:
            raise RuntimeError("envoi refusé")
        self._j.append(f"poste:{self.id}")
        return type("M", (), {"id": 1})()


class FauxGuild:
    def __init__(self, salons, me=None):
        self.id = 777
        self.text_channels = list(salons)
        self.me = me
        self.name = "banc"

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == cid), None)


def _espace_tickets(config, journal, types=(("clan", {"name": "Clan"}),)):
    ecrits = {}

    async def _cfg(_gid):
        return dict(config)

    async def _db_set(_gid, k, v):
        ecrits[k] = v
        config[k] = v

    async def _hub(_guild):
        return "VUE_HUB"

    ns = {
        "cfg": _cfg, "db_set": _db_set, "asyncio": asyncio,
        "_build_ticket_hub_view": _hub,
        "_types_tickets": lambda c: list(types),
        "bot": type("B", (), {"user": type("U", (), {"id": 99})()})(),
        "discord": type("D", (), {"Forbidden": type("F", (), {})})(),
        "_logerr": lambda *a, **k: None,
        "print": lambda *a, **k: None,
    }
    exec(_src("_custom_ids_du_message"), ns)     # noqa: S102 — code du dépôt
    exec(_src("_migrer_panneaux_tickets"), ns)   # noqa: S102 — code du dépôt
    return ns, ecrits


def test_T1_un_bouton_ENFOUI_en_V2_est_bien_trouve():
    """⚠️ SANS RÉCURSION, LA MIGRATION NE VOIT RIEN. En V2 le bouton vit sous
    un Container → Section → accessory : un parcours à plat conclurait qu'il
    n'y a aucun ancien panneau, et la migration ne ferait jamais rien."""
    ns, _ = _espace_tickets({}, [])
    msg = FauxMessage(1, 99, [FauxComposant(children=[
        FauxComposant(accessory=FauxComposant(custom_id="ticket_create_clan"))])], [])
    assert "ticket_create_clan" in ns["_custom_ids_du_message"](msg)


def test_T2_le_panneau_unifie_est_POSTE_avant_que_l_ancien_parte():
    """Supprimer d'abord laisserait un salon d'ouverture de tickets sans
    aucun bouton si l'envoi rate — un service coupé sans que personne le voie."""
    journal = []
    vieux = FauxMessage(10, 99, [FauxComposant(custom_id="ticket_create_clan")], journal)
    g = FauxGuild([FauxSalon(5, [vieux], journal)])
    ns, ecrits = _espace_tickets({}, journal)
    res = asyncio.run(ns["_migrer_panneaux_tickets"](g))
    assert journal == ["poste:5", "supprime:10"], journal
    assert res["postes"] == 1 and res["supprimes"] == 1
    assert ecrits.get("ticket_hub_migre"), "le marqueur n'a pas été écrit"


def test_T3_si_l_envoi_RATE_on_ne_supprime_RIEN():
    """La règle qui protège le service : poster d'abord, supprimer ensuite."""
    journal = []
    vieux = FauxMessage(10, 99, [FauxComposant(custom_id="ticket_create_clan")], journal)
    g = FauxGuild([FauxSalon(5, [vieux], journal, envoi_casse=True)])
    ns, _ = _espace_tickets({}, journal)
    res = asyncio.run(ns["_migrer_panneaux_tickets"](g))
    assert journal == [], f"un panneau a été supprimé sans remplaçant : {journal}"
    assert res["supprimes"] == 0


def test_T4_un_salon_qui_a_DEJA_le_panneau_unifie_n_en_recoit_pas_un_second():
    """Deux panneaux identiques dans le même salon, c'est le désordre qu'on
    vient de supprimer."""
    journal = []
    vieux = FauxMessage(10, 99, [FauxComposant(custom_id="ticket_create_clan")], journal)
    hub = FauxMessage(11, 99, [FauxComposant(custom_id="tickethub:open")], journal)
    g = FauxGuild([FauxSalon(5, [hub, vieux], journal)])
    ns, _ = _espace_tickets({}, journal)
    res = asyncio.run(ns["_migrer_panneaux_tickets"](g))
    assert res["postes"] == 0 and res["supprimes"] == 1
    assert journal == ["supprime:10"]


def test_T5_aucun_type_de_ticket_configure_on_NE_TOUCHE_A_RIEN():
    """Remplacer un panneau qui marche par un panneau qui annonce qu'il ne
    sert à rien serait une régression."""
    journal = []
    vieux = FauxMessage(10, 99, [FauxComposant(custom_id="ticket_create_clan")], journal)
    g = FauxGuild([FauxSalon(5, [vieux], journal)])
    ns, _ = _espace_tickets({}, journal, types=())
    res = asyncio.run(ns["_migrer_panneaux_tickets"](g))
    assert res["raison"] == "aucun type de ticket configuré"
    assert journal == []


def test_T6_la_migration_n_a_lieu_QU_UNE_FOIS():
    """Railway redéploie plusieurs fois par jour : sans marqueur, chaque
    redémarrage reposterait un panneau de plus."""
    journal = []
    vieux = FauxMessage(10, 99, [FauxComposant(custom_id="ticket_create_clan")], journal)
    g = FauxGuild([FauxSalon(5, [vieux], journal)])
    ns, _ = _espace_tickets({"ticket_hub_migre": "1/1"}, journal)
    res = asyncio.run(ns["_migrer_panneaux_tickets"](g))
    assert res["raison"] == "déjà fait" and journal == []


def test_T7_les_messages_des_AUTRES_ne_sont_jamais_touches():
    """Un membre peut avoir copié une capture du panneau : supprimer le
    message de quelqu'un d'autre serait une faute irréparable."""
    journal = []
    autre = FauxMessage(10, 12345,
                        [FauxComposant(custom_id="ticket_create_clan")], journal)
    g = FauxGuild([FauxSalon(5, [autre], journal)])
    ns, _ = _espace_tickets({}, journal)
    res = asyncio.run(ns["_migrer_panneaux_tickets"](g))
    assert res["supprimes"] == 0 and journal == []


# ═══════════════════════════════════════════════════════════════════════════════
#  B — le bilan de santé
# ═══════════════════════════════════════════════════════════════════════════════

class FauxPermsGuild:
    def __init__(self, **kw):
        for a in ("manage_nicknames", "ban_members", "moderate_members",
                  "manage_roles", "manage_channels"):
            setattr(self, a, kw.get(a, True))


class FauxMoi:
    def __init__(self, perms=None, rang=100):
        self.guild_permissions = perms or FauxPermsGuild()
        self.top_role = type("R", (), {"id": 1, "name": "bot", "rang": rang})()

    def __le__(self, _autre):
        return False


def _espace_bilan(config, perms=None, etiquettes=(), me_sous_role=False):
    envois = []

    async def _cfg(_gid):
        return dict(config)

    async def _db_set(_gid, k, v):
        config[k] = v

    class _Role:
        def __init__(self, nom):
            self.name = nom

    class _Top:
        def __le__(self, _r):
            return me_sous_role

    me = type("Me", (), {"guild_permissions": perms or FauxPermsGuild(),
                         "top_role": _Top()})()

    class _Salon:
        id = 4
        async def send(self, texte):
            envois.append(texte)

    guild = type("G", (), {"id": 777, "me": me,
                           "get_channel": lambda self, cid: _Salon() if cid else None})()

    async def _cfg_act(_gid):
        return {}

    ns = {
        "cfg": _cfg, "db_set": _db_set, "_logerr": lambda *a, **k: None,
        "print": lambda *a, **k: None,
        "activite_module": type("A", (), {"config": staticmethod(_cfg_act)}),
        "activite_niv": type("N", (), {
            "roles_etiquettes": staticmethod(
                lambda g, c: [_Role(n) for n in etiquettes])}),
        "datetime": __import__("datetime").datetime,
        "timezone": __import__("datetime").timezone,
    }
    exec(_src("_bilan_sante_serveur"), ns)    # noqa: S102 — code du dépôt
    exec(_src("_publier_bilan_sante"), ns)    # noqa: S102 — code du dépôt
    return ns, guild, envois, config


def test_B1_une_permission_manquante_est_NOMMEE_avec_sa_consequence():
    """« Il manque une permission » n'aide personne : il faut dire laquelle et
    ce qui casse sans elle."""
    ns, g, _e, _c = _espace_bilan(
        {'direction_allowed_role': 1, 'activite_salon_retour': 1},
        perms=FauxPermsGuild(manage_nicknames=False))
    manques = asyncio.run(ns["_bilan_sante_serveur"](g))
    assert any("Gérer les pseudos" in m and "pseudo" in m for m in manques), manques


def test_B2_un_role_AU_DESSUS_du_bot_est_signale_avec_son_nom():
    """Le seul cas de l'AFK que le bot ne peut pas réparer seul."""
    ns, g, _e, _c = _espace_bilan(
        {'direction_allowed_role': 1, 'activite_salon_retour': 1},
        etiquettes=("💤 AFK",), me_sous_role=True)
    manques = asyncio.run(ns["_bilan_sante_serveur"](g))
    assert any("💤 AFK" in m and "au-dessus" in m for m in manques), manques


def test_B3_un_serveur_SAIN_ne_reçoit_aucun_message():
    """« C'est très relou » : pas de message quand tout va bien."""
    ns, g, envois, _c = _espace_bilan(
        {'direction_allowed_role': 1, 'activite_salon_retour': 1,
         'mod_log_channel': 4})
    assert asyncio.run(ns["_bilan_sante_serveur"](g)) == []
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is False
    assert envois == []


def test_B4_un_seul_message_par_JOUR_malgre_les_redeploiements():
    """Railway redémarre plusieurs fois par jour. Sans la date, ce bilan
    deviendrait exactement le bruit que le propriétaire a demandé de couper."""
    ns, g, envois, config = _espace_bilan(
        {'mod_log_channel': 4, 'activite_salon_retour': 1},
        perms=FauxPermsGuild(ban_members=False))
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is True
    assert len(envois) == 1 and "Bannir des membres" in envois[0]
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is False
    assert len(envois) == 1, "deux bilans le même jour"


def test_B4b_une_liste_INCHANGEE_se_tait_une_semaine():
    """⚠️ « C'EST TRÈS RELOU. » Un rappel identique chaque jour finit par ne
    plus être lu — le jour où il compte. Tant que rien ne change, on se tait
    une semaine ; un manque NOUVEAU, lui, est dit le jour même."""
    import datetime as _dt
    config = {'mod_log_channel': 4, 'activite_salon_retour': 1}
    ns, g, envois, config = _espace_bilan(
        config, perms=FauxPermsGuild(ban_members=False))
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is True
    #  Le lendemain, même liste : silence.
    config['bilan_sante_jour'] = (
        _dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=1)
    ).strftime("%Y-%m-%d")
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is False
    assert len(envois) == 1
    #  Huit jours plus tard, toujours pareil : on le redit.
    config['bilan_sante_jour'] = (
        _dt.datetime.now(_dt.timezone.utc).date() - _dt.timedelta(days=8)
    ).strftime("%Y-%m-%d")
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is True
    assert len(envois) == 2


def test_B4c_un_manque_NOUVEAU_est_dit_le_jour_meme():
    """Se taire une semaine sur une liste qui a changé cacherait le manque
    qui vient d'apparaître — celui qui casse quelque chose aujourd'hui."""
    import datetime as _dt
    config = {'mod_log_channel': 4, 'activite_salon_retour': 1,
              'bilan_sante_jour': _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d"),
              'bilan_sante_signature': "un-manque-qui-n-existe-plus"}
    ns, g, envois, config = _espace_bilan(
        config, perms=FauxPermsGuild(ban_members=False))
    assert asyncio.run(ns["_publier_bilan_sante"](g)) is True
    assert len(envois) == 1


def test_B5_le_bilan_est_APPELE_au_demarrage():
    """Une fonction non appelée n'est pas opérationnelle."""
    corps = _src("_travaux_de_demarrage")
    assert "_migrer_panneaux_tickets" in corps and "_publier_bilan_sante" in corps
    assert "_travaux_de_demarrage()" in SRC.split("async def _travaux_de_demarrage")[0] \
        or "asyncio.create_task(_travaux_de_demarrage())" in SRC
    assert "_TACHES_DEMARRAGE.add(" in SRC, "tâche non retenue : ramassable en plein await"


# ═══════════════════════════════════════════════════════════════════════════════
#  U — le flux UGC s'installe seul
# ═══════════════════════════════════════════════════════════════════════════════

def _espace_ugc(config, cree_casse=False, manage_channels=True):
    journal = []

    async def _cfg(_gid):
        return dict(config)

    async def _db_set(_gid, k, v):
        config[k] = v
        journal.append(f"cfg:{k}")

    class _Salon:
        id, name = 77, "🎨・nouveautes-ugc"

        async def send(self, _t):
            journal.append("message")

    class _Ref:
        id, category = 5, "CAT"

    async def _create(nom, category=None, topic=None, reason=None):
        if cree_casse:
            raise RuntimeError("refus")
        journal.append(f"cree:{nom}:{category}")
        return _Salon()

    me = type("Me", (), {"guild_permissions": type(
        "P", (), {"manage_channels": manage_channels})()})()
    guild = type("G", (), {
        "id": 777, "me": me,
        "get_channel": lambda self, cid: _Ref() if cid == 5 else None,
        "create_text_channel": staticmethod(_create)})()

    ns = {"cfg": _cfg, "db_set": _db_set, "_logerr": lambda *a, **k: None,
          "print": lambda *a, **k: None}
    exec(_src("_installer_salon_ugc"), ns)     # noqa: S102 — code du dépôt
    return ns, guild, journal, config


def test_U1_le_salon_UGC_est_cree_a_cote_du_salon_officiel_et_le_flux_allume():
    """Le flux est livré depuis le 03/09 et n'a jamais rien publié : il exige
    un salon et n'a pas de repli. Sans cette installation, il reste muet."""
    ns, g, journal, config = _espace_ugc(
        {"roblox_veille_enabled": True, "roblox_salon_nouveautes": 5})
    assert asyncio.run(ns["_installer_salon_ugc"](g)) is True
    assert any(j.startswith("cree:") and j.endswith(":CAT") for j in journal), journal
    assert config["roblox_salon_ugc"] == 77
    assert config["roblox_ugc_enabled"] is True
    assert "message" in journal, "un salon vide ressemble à une erreur"


def test_U2_on_n_installe_RIEN_sans_veille_allumee_ni_salon_officiel():
    """Sans repère, on ne saurait ni où créer le salon, ni si le serveur veut
    du Roblox."""
    ns, g, journal, _c = _espace_ugc({"roblox_veille_enabled": False,
                                      "roblox_salon_nouveautes": 5})
    assert asyncio.run(ns["_installer_salon_ugc"](g)) is False and journal == []
    ns, g, journal, _c = _espace_ugc({"roblox_veille_enabled": True})
    assert asyncio.run(ns["_installer_salon_ugc"](g)) is False and journal == []


def test_U3_une_installation_DEJA_faite_ne_recommence_pas():
    """Sans marqueur, chaque passage de 30 minutes créerait un salon de plus."""
    ns, g, journal, _c = _espace_ugc({"roblox_veille_enabled": True,
                                      "roblox_salon_nouveautes": 5,
                                      "roblox_ugc_installe": "77"})
    assert asyncio.run(ns["_installer_salon_ugc"](g)) is False and journal == []


def test_U4_un_salon_regle_A_LA_MAIN_est_respecte():
    """Le propriétaire a pu choisir son salon : on ne le double pas."""
    ns, g, journal, _c = _espace_ugc({"roblox_veille_enabled": True,
                                      "roblox_salon_nouveautes": 5,
                                      "roblox_salon_ugc": 123})
    assert asyncio.run(ns["_installer_salon_ugc"](g)) is False and journal == []


def test_U5_sans_la_permission_on_le_DIT_et_on_ne_retente_pas_en_boucle():
    """Retenter toutes les 30 minutes une création qui ne peut pas aboutir,
    c'est une erreur répétée 48 fois par jour dans les logs."""
    ns, g, journal, config = _espace_ugc(
        {"roblox_veille_enabled": True, "roblox_salon_nouveautes": 5},
        manage_channels=False)
    assert asyncio.run(ns["_installer_salon_ugc"](g)) is False
    assert config.get("roblox_ugc_installe") == "refus:permission"


def test_U6_la_cle_du_marqueur_est_DECLAREE_dans_le_module():
    """`roblox_veille.config()` ne rend que les clés de `CLES_DEFAUT` : une clé
    non déclarée serait perdue et l'installation recommencerait sans fin."""
    src = (RACINE / "roblox_veille.py").read_text(encoding="utf-8")
    assert '"roblox_ugc_installe"' in src


def test_U7_l_installation_est_APPELEE_dans_la_boucle_de_veille():
    """Une fonction non appelée n'est pas opérationnelle, même parfaite."""
    corps = _src("veille_roblox_task")
    assert "_installer_salon_ugc(g)" in corps
