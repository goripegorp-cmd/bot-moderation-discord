"""`/off` — neutraliser D'ABORD, ranger ENSUITE.

═══════════════════════════════════════════════════════════════════════════════
CE QUI CLOCHAIT, ET C'ÉTAIT MESURABLE DANS LE CODE
═══════════════════════════════════════════════════════════════════════════════
L'ordre des opérations était :

    _ensure_radie_role(guild)   → pour CHAQUE salon : set_permissions + sleep(0.3)
    puis retrait des rôles
    puis timeout                ← LE COUP D'ARRÊT, EN DERNIER

Au premier usage sur un serveur, la boucle des salons s'exécute en entier.
Soixante salons = **dix-huit secondes** avant que la personne soit seulement
gênée. Pendant une attaque, c'est dix-huit secondes de dégâts en plus — et
c'est le PREMIER usage, donc exactement le jour où on en a besoin.

`member.timeout(...)` est UN appel, immédiat, et il coupe tout ce qui compte :
écrire, réagir, rejoindre un vocal, lancer une commande, partout. C'est lui qui
part en premier maintenant. Le rôle « Radié » et le verrouillage des salons —
qui masquent la vue — suivent en tâche de fond : ils rendent la radiation
propre, ils ne l'arrêtent pas.

Le propriétaire, 06/09/2026 : « qu'elle soit vraiment opérationnelle et qu'elle
interagit directement sur la personne en question […] que l'utilisateur puisse
faire la commande le plus vite possible ».
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from datetime import timedelta
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
#  Des faux FIDÈLES — piège n°6 : tout ce que le vrai porte sur ce chemin
# ═══════════════════════════════════════════════════════════════════════════════

class FauxRole:
    def __init__(self, rid, nom="r", position=1, managed=False, defaut=False):
        self.id, self.name, self.position = rid, nom, position
        self.managed, self._defaut = managed, defaut

    def is_default(self):
        return self._defaut

    def __gt__(self, autre):
        return self.position > autre.position

    def __lt__(self, autre):
        return self.position < autre.position

    #  ⚠️ PIÈGE N°6 — LE FAUX DOIT PORTER TOUT CE QUE PORTE LE VRAI.
    #  `discord.Role` est totalement ordonné ; sans `__ge__`, le `>=` de la
    #  garde de hiérarchie levait un TypeError, attrapé par le fail-closed :
    #  le test mesurait un REFUS DE PANNE en croyant mesurer la règle.
    def __ge__(self, autre):
        return self.position >= autre.position

    def __le__(self, autre):
        return self.position <= autre.position

    def __eq__(self, autre):
        return isinstance(autre, FauxRole) and autre.id == self.id

    def __hash__(self):
        return hash(self.id)


class FauxMembre:
    def __init__(self, roles, journal):
        self.id = 4242
        self.roles = list(roles)
        self.nick = "AncienPseudo"
        self.name = "cible"
        self._j = journal

    async def timeout(self, duree, reason=None):
        self._j.append("timeout")

    #  ⚠️ `nick` FAIT PARTIE DE LA VRAIE SIGNATURE. Sans lui, l appel reel
    #  levait un TypeError, le code retombait sur son repli sans pseudo, et le
    #  test mesurait le CHEMIN DE SECOURS en croyant mesurer le chemin normal.
    async def edit(self, roles=None, nick=..., reason=None):
        self._j.append("edit_roles")
        self.roles = list(roles or [])
        if nick is not ...:
            self.nick = nick
            self._j.append("nick")


class FauxGuild:
    def __init__(self, moi, roles, salons, journal):
        self.id = 1
        self.me = moi
        self.roles = list(roles)
        self.channels = list(salons)
        self._j = journal

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    async def create_role(self, **kw):
        self._j.append("create_role")
        r = FauxRole(999, kw.get("name", "🚫 Radié"), position=50)
        self.roles.append(r)
        return r


class FauxSalon:
    def __init__(self, journal):
        self._j = journal

    def overwrites_for(self, role):
        class _O:
            view_channel = None
            send_messages = None
            connect = None
        return _O()

    async def set_permissions(self, role, overwrite=None, reason=None):
        self._j.append("salon")


class FauxMoi:
    top_role = FauxRole(500, "bot", position=100)


class FauxAuteur:
    id = 7


def _faux_recours(journal, ok=True):
    async def _f(guild, membre, raison):
        journal.append("dm_recours")
        return ok
    return _f


def _espace(journal, db_ok=True, dm_ok=True):
    """L'espace de noms minimal pour exécuter le VRAI code du dépôt."""
    @contextlib.asynccontextmanager
    async def _get_db():
        if not db_ok:
            raise RuntimeError("base indisponible")

        class _DB:
            async def execute(self, *a, **k):
                journal.append("db")

            async def commit(self):
                pass
        yield _DB()

    class _FauxDiscord:
        class utils:
            @staticmethod
            def get(seq, **kw):
                for x in seq:
                    if all(getattr(x, k, None) == v for k, v in kw.items()):
                        return x
                return None

        class Color:
            @staticmethod
            def dark_red():
                return 0

    ns = {
        "asyncio": asyncio, "json": json, "timedelta": timedelta,
        "discord": _FauxDiscord, "get_db": _get_db,
        "_RADIE_ROLE_NAME": "🚫 Radié",
        "_radie_overwrite": lambda: object(),
        "_VERROUS_RADIATION": set(),
        "print": lambda *a, **k: None,
        #  Le message privé de recours : on note QUAND il part, c'est tout ce
        #  qui nous intéresse ici (son contenu a ses propres tests).
        "_envoyer_recours_radie": _faux_recours(journal, dm_ok),
    }
    #  ⚠️ LE VRAI `_radie_pseudo`, PAS UN SUBSTITUT. Absent de l espace de
    #  noms, l appel levait un NameError avale par le repli : le test mesurait
    #  le chemin de SECOURS en croyant mesurer le chemin normal.
    exec(_src("_radie_pseudo"), ns)               # noqa: S102 — code du dépôt
    exec(_src("_verrouiller_salons_radie"), ns)   # noqa: S102 — code du dépôt
    exec(_src("_radier_membre"), ns)              # noqa: S102 — code du dépôt
    return ns


def _jouer(db_ok=True, salons=6, dm_ok=True):
    journal = []
    moi = FauxMoi()
    radie = FauxRole(999, "🚫 Radié", position=50)
    porte = [FauxRole(0, "@everyone", position=0, defaut=True),
             FauxRole(1, "Membre", position=5),
             FauxRole(2, "Booster", position=6, managed=True)]
    m = FauxMembre(porte, journal)
    g = FauxGuild(moi, [radie] + porte, [FauxSalon(journal) for _ in range(salons)],
                  journal)
    ns = _espace(journal, db_ok=db_ok, dm_ok=dm_ok)

    async def _run():
        r = await ns["_radier_membre"](g, m, FauxAuteur(), "test")
        #  On laisse la tâche de fond aller au bout pour observer son effet.
        await asyncio.sleep(0)
        for t in list(ns["_VERROUS_RADIATION"]):
            await t
        return r

    return asyncio.run(_run()), journal, m


# ═══════════════════════════════════════════════════════════════════════════════
#  LE POINT CENTRAL : le silence part AVANT tout le reste
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_silence_est_la_TOUTE_PREMIERE_action():
    """⚠️ LE CŒUR DU CORRECTIF. Avant, le verrouillage des salons passait en
    premier : soixante salons × 0,3 s = dix-huit secondes pendant lesquelles
    l'attaquant continuait tranquillement."""
    _res, journal, _m = _jouer()
    assert journal[0] == "timeout", (
        f"la première action n'est pas la réduction au silence : {journal[:4]}")


def test_les_salons_ne_sont_JAMAIS_sur_le_chemin_critique():
    """Le verrouillage doit venir APRÈS le retrait des rôles, jamais avant."""
    _res, journal, _m = _jouer(salons=6)
    assert "salon" in journal, "le verrouillage n'a pas eu lieu du tout"
    assert journal.index("timeout") < journal.index("salon")
    assert journal.index("edit_roles") < journal.index("salon"), (
        "les salons passent avant le retrait des rôles : on est revenu au "
        "défaut d'origine")


def test_les_roles_sont_sauvegardes_AVANT_d_etre_retires():
    """⚠️ L'ORDRE EST NON NÉGOCIABLE. Retirer d'abord et écrire ensuite fait
    perdre la liste si l'écriture échoue — et des rôles perdus ne se devinent
    pas. `/off off` deviendrait un mensonge."""
    _res, journal, _m = _jouer()
    assert journal.index("db") < journal.index("edit_roles")


def test_un_role_dintegration_nest_ni_retire_ni_promis():
    """⚠️ L'API REFUSE TOUT L'APPEL si on demande de retirer un rôle `managed`
    (boost, bot, abonnement). Et le compter ferait promettre à `/off off` de
    rendre un rôle qu'on n'a jamais pris."""
    res, _journal, m = _jouer()
    assert res["roles_retires"] == 1, (
        f"attendu 1 rôle retiré (Membre), obtenu {res['roles_retires']} — "
        f"le rôle d'intégration a été compté")
    noms = {r.name for r in m.roles}
    assert "Booster" in noms, "un rôle d'intégration a été retiré : l'appel "\
                              "entier aurait échoué en production"
    assert "@everyone" in noms
    assert "🚫 Radié" in noms, "l'étiquette n'a pas été posée"
    assert "Membre" not in noms


def test_un_echec_de_sauvegarde_narrete_PAS_la_neutralisation():
    """⚠️ ON NE S'ARRÊTE PAS AU PREMIER ÉCHEC. Si la base tombe, la personne
    doit quand même être réduite au silence — c'est l'urgence. Mais on le DIT."""
    res, journal, _m = _jouer(db_ok=False)
    assert journal[0] == "timeout"
    assert res["timeout"] is True
    assert res["sauvegarde"] is False
    assert any("sauvegarde" in x for x in res["manques"])


def test_la_tache_de_fond_est_RETENUE():
    """⚠️ SANS RÉFÉRENCE, le ramasse-miettes peut collecter une tâche
    `create_task` avant sa fin : le verrouillage s'arrêterait au milieu, sans
    erreur et sans trace."""
    corps = _src("_radier_membre")
    assert "_VERROUS_RADIATION.add(" in corps
    assert "add_done_callback" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  RAPIDITÉ D'USAGE — « pas qu'il se complique la vie »
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_raison_est_FACULTATIVE():
    """Elle était obligatoire : en pleine attaque, il fallait taper une phrase
    avant de pouvoir valider. Le champ reste pour qui veut documenter."""
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "off_on_cmd":
            args = n.args
            noms = [a.arg for a in args.args]
            assert "raison" in noms
            #  Autant de défauts que d'arguments après le premier sans défaut :
            #  `raison` doit en avoir un.
            i = noms.index("raison")
            sans_defaut = len(noms) - len(args.defaults)
            assert i >= sans_defaut, (
                "`raison` n'a pas de valeur par défaut : elle reste "
                "obligatoire, et bloque en urgence")
            return
    raise AssertionError("off_on_cmd introuvable")


def test_il_existe_un_chemin_SANS_RIEN_TAPER():
    """⚠️ LE CHEMIN D'URGENCE. Passer par `/off on` demande d'ouvrir la barre,
    taper, attendre l'autocomplétion et choisir dans une liste — plusieurs
    secondes sous stress, et un risque réel de désigner un homonyme. Un menu
    contextuel désigne la personne du message sur lequel on a cliqué."""
    trouve = False
    for n in ast.walk(ARBRE):
        if (isinstance(n, ast.AsyncFunctionDef)
                and n.name == "radier_menu_contextuel"):
            trouve = True
            deco = ast.unparse(ast.Module(body=[
                ast.Expr(d) for d in n.decorator_list], type_ignores=[]))
            assert "context_menu" in deco, "ce n'est pas un menu contextuel"
            assert "default_permissions" in deco, (
                "le menu est ouvert à tout le monde")
            assert "guild_only" in deco
    assert trouve, "aucun menu contextuel : le chemin rapide n'existe pas"


def test_le_menu_contextuel_partage_le_MEME_corps():
    """Deux copies divergeraient, et c'est la sauvegarde des rôles qui
    manquerait à l'une — donc des rôles perdus pour toujours."""
    corps = _src("radier_menu_contextuel")
    for appel in ("_refus_radiation(", "_radier_membre(",
                  "_compte_rendu_radiation(", "_journal_radiation("):
        assert appel in corps, f"le menu contextuel n'appelle pas {appel}"


def test_le_refus_est_instantane_et_dit_quoi_faire():
    """⚠️ AUCUN APPEL RÉSEAU DANS LE REFUS. En pleine attaque, un refus doit
    revenir tout de suite — et surtout nommer la permission manquante, sinon
    on cherche pendant que le serveur brûle."""
    corps = _src("_refus_radiation")
    assert "await" not in corps, "le refus fait un appel réseau"
    assert "Modérer les membres" in corps
    assert "Gérer les rôles" in corps
    assert "au-dessus du mien" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  HONNÊTETÉ DU COMPTE RENDU
# ═══════════════════════════════════════════════════════════════════════════════

def _rendu(res):
    ns = {}
    exec(_src("_compte_rendu_radiation"), ns)     # noqa: S102 — code du dépôt

    class _M:
        mention = "@cible"
    return ns["_compte_rendu_radiation"](_M(), res)


def test_un_echec_de_silence_ne_passe_PAS_pour_une_reussite():
    """⚠️ UNE RADIATION PARTIELLE ANNONCÉE COMME TOTALE EST PIRE QU'UN ÉCHEC :
    on croit le serveur protégé et on passe à autre chose."""
    txt = _rendu({"timeout": False, "roles_retires": 3, "role_pose": True,
                  "sauvegarde": True, "verrou": True, "manques": []})
    assert "n'a PAS pu être réduit au silence" in txt
    assert "Modérer les membres" in txt


def test_une_sauvegarde_ratee_est_criee():
    """Sans cet avertissement, on découvre à `/off off` que les rôles sont
    perdus — et personne ne s'en souvient."""
    txt = _rendu({"timeout": True, "roles_retires": 3, "role_pose": True,
                  "sauvegarde": False, "verrou": True,
                  "manques": ["sauvegarde des rôles échouée (x)"]})
    assert "n'ont PAS été sauvegardés" in txt
    assert "`/off off`" in txt


def test_le_cas_nominal_dit_ce_qui_est_fait_et_ce_qui_continue():
    txt = _rendu({"timeout": True, "roles_retires": 3, "role_pose": True,
                  "sauvegarde": True, "verrou": True, "manques": []})
    assert "est neutralisé" in txt
    assert "3` rôle(s) retiré(s)" in txt
    assert "Verrouillage des salons en cours" in txt, (
        "rien ne dit que le masquage continue : on croirait à un travail "
        "inachevé")
    assert "PAS" not in txt.replace("n'a PAS", "")


# ═══════════════════════════════════════════════════════════════════════════════
#  Non-régression sur la levée
# ═══════════════════════════════════════════════════════════════════════════════

def test_off_off_leve_bien_le_silence():
    """⚠️ LE TIMEOUT EST MAINTENANT L'ACTION PRINCIPALE, plus un filet. Si la
    levée ne l'annulait pas, un membre « réintégré » resterait muet 28 jours
    avec tous ses rôles rendus — et personne ne comprendrait pourquoi."""
    corps = _src("off_off_cmd")
    assert "timeout(None" in corps, (
        "`/off off` n'annule pas la réduction au silence")


def test_les_cibles_interdites_le_restent():
    """Contre-épreuve : la puissance ne doit pas déborder sur le propriétaire,
    le super-owner, les bots, ni sur soi-même."""
    corps = _src("_refus_radiation")
    for garde in ("membre.bot", "guild.owner_id", "is_super_owner",
                  "membre.id == auteur.id"):
        assert garde in corps, f"garde-fou manquant : {garde}"


# ═══════════════════════════════════════════════════════════════════════════════
#  LE RECOURS — un seul, et jamais avant d'avoir neutralisé
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_recours_part_APRES_la_neutralisation():
    """⚠️ PRÉVENIR QUELQU'UN QU'ON VA LE RADIER LUI LAISSE LE TEMPS DE FAIRE
    DES DÉGÂTS. Le message privé ne part qu'une fois la personne muette et
    dépouillée."""
    _res, journal, _m = _jouer()
    assert "dm_recours" in journal, "aucun droit de recours n'est ouvert"
    assert journal.index("timeout") < journal.index("dm_recours")
    assert journal.index("edit_roles") < journal.index("dm_recours")


def test_un_MP_ferme_est_SIGNALE_au_moderateur():
    """⚠️ SANS CE SIGNAL, ON CROIRAIT LUI AVOIR LAISSÉ UNE PORTE. La personne
    ne voit plus aucun salon : le message privé était son unique chemin."""
    res, _journal, _m = _jouer(dm_ok=False)
    assert res["recours_envoye"] is False
    assert any("recours" in x for x in res["manques"])
    txt = _rendu(res)
    assert "aucun chemin pour se défendre" in txt


def test_le_pseudo_de_serveur_est_detruit():
    """« Que leur pseudo soit complètement détruit » — celui du serveur, pas
    celui du compte Discord, qu'aucun bot ne peut changer."""
    res, _journal, _m = _jouer()
    assert res["pseudo_detruit"] is True
    corps = _src("_radier_membre")
    assert "nick=_nick" in corps, "le pseudo n'est pas modifié"
    assert "roles=garder, nick=_nick" in corps, (
        "pseudo et rôles doivent partir dans le MÊME appel : sinon deux "
        "entrées d'audit et un instant où le membre est dépouillé mais porte "
        "encore son nom")


def test_un_echec_de_pseudo_ne_fait_pas_perdre_le_retrait_des_roles():
    """⚠️ LA PERMISSION « Gérer les pseudos » peut manquer alors que « Gérer
    les rôles » est là. Abandonner tout l'appel laisserait la personne AVEC
    tous ses rôles — l'inverse du but."""
    corps = _src("_radier_membre")
    assert corps.count("await membre.edit(roles=garder") >= 1
    assert "Gérer les pseudos" in corps, (
        "le repli sans pseudo n'existe pas, ou ne dit pas ce qui manque")


def test_le_nom_saffiche_en_NOIR_et_pas_en_couleur_par_defaut():
    """⚠️ 0x000000 EST TRAITÉ PAR DISCORD COMME « aucune couleur » : le pseudo
    reprendrait la couleur du rôle suivant. 0x010101 est visuellement noir et
    compte comme une vraie couleur."""
    assert "_RADIE_COULEUR = 0x010101" in SRC, (
        "la couleur du rôle Radié n'est pas un noir valide")
    corps = _src("_radier_membre")
    assert "discord.Colour(_RADIE_COULEUR)" in corps
    assert "role.colour.value != _RADIE_COULEUR" in corps, (
        "un rôle « Radié » créé par une version antérieure garderait son "
        "ancienne couleur : les anciens radiés ne seraient pas en noir")


def test_le_droit_de_recours_est_UNIQUE_et_vit_en_base():
    """« Ils peuvent en créer qu'un seul ». Un compteur en mémoire se
    remettrait à zéro au premier redémarrage."""
    corps = _src("_recours_deja_utilise")
    assert "appel_utilise" in corps
    assert "radiated_members" in corps


def test_une_base_muette_REFUSE_le_recours():
    """⚠️ FAIL-CLOSED, ET LE SENS COMPTE. Fail-open laisserait un radié rouvrir
    un recours à chaque panne de base — donc autant de tickets qu'il veut,
    exactement ce qu'on interdit."""
    corps = _src("_recours_deja_utilise")
    i_exc = corps.index("except Exception")
    assert "return True" in corps[i_exc:], (
        "en cas d'erreur, la fonction n'interdit pas le recours")


def test_le_recours_nest_consomme_QU_APRES_la_creation_du_ticket():
    """L'inverse ferait perdre le droit de recours sur une simple panne de
    salon — et il n'y en a qu'un."""
    corps = _src("_ouvrir_ticket_recours")
    i_creation = corps.index("create_text_channel")
    i_marque = corps.index("appel_utilise=1")
    assert i_creation < i_marque


def test_le_salon_de_recours_nest_PAS_visible_par_le_radie():
    """« Ils ne voient plus aucun salon, mais vraiment plus aucun. » Et de
    toute façon, en timeout, il ne pourrait pas y écrire."""
    corps = _src("_ouvrir_ticket_recours")
    assert "default_role: discord.PermissionOverwrite(view_channel=False)" in corps
    assert "membre: discord.PermissionOverwrite" not in corps, (
        "le radié reçoit un accès au salon de recours : il verrait un salon, "
        "et il ne pourrait pas y écrire de toute façon")


def test_la_decision_est_HUMAINE_et_reservee_au_staff():
    """« C'est pas le bot qui va décider, c'est moi. » Le bot instruit le
    dossier ; un humain tranche."""
    corps = _src("callback")  # premier callback trouvé — on vise la classe
    src_cls = SRC
    assert "class RadieDecisionButton" in src_cls
    i = src_cls.index("class RadieDecisionButton")
    bloc = src_cls[i:i + 4000]
    assert "guild_permissions.administrator" in bloc
    assert "ticket_staff" in bloc
    assert "Décision réservée au staff" in bloc


def test_on_previent_AVANT_de_bannir():
    """⚠️ APRÈS LE BANNISSEMENT, PLUS AUCUN SERVEUR EN COMMUN : le message
    privé ne partirait jamais. La personne apprendrait son bannissement en
    ne trouvant plus le serveur."""
    #  ⚠️ ON BORNE SUR LA BRANCHE "bannir" SEULE. La branche "lever" appelle
    #  aussi `_prevenir_radie` et EN PREMIER : chercher dans tout le bloc
    #  trouvait cet appel-la et le test passait alors que le bannissement
    #  precedait bien son avertissement. Mutation testee, defaut reel.
    i = SRC.index("class RadieDecisionButton")
    bloc = SRC[i:i + 4000]
    i_ban = bloc.index("guild.ban(")
    branche = bloc[bloc.index("else:", 0, i_ban):i_ban]
    assert "_prevenir_radie(" in branche, (
        "on bannit avant de prévenir : le message ne partira jamais")


def test_la_levee_rend_le_pseudo():
    """Laisser « ⛔ RADIÉ-1234 » sur quelqu'un dont on vient de reconnaître le
    bon droit serait une sanction qui survit à sa levée."""
    corps = _src("off_off_cmd")
    assert "saved_nick" in corps
    assert "nick=_ancien" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  QUI A LE DROIT — 22/09/2026
# ═══════════════════════════════════════════════════════════════════════════════
#  La commande était `default_permissions = administrator` : une Direction non
#  administratrice ne la VOYAIT même pas, sauf à l'autoriser dans Paramètres du
#  serveur → Intégrations — une étape qu'aucun bot ne peut faire à la place du
#  propriétaire (l'API Discord la réserve à un jeton d'utilisateur), et que
#  personne ne fait AVANT l'attaque.
#
#  Pire : `direction_allowed_role` était LUE par `/mod direction` et écrite
#  NULLE PART. Aucune interface. Elle valait donc 0 pour toujours — le piège
#  n°4 du dépôt, mot pour mot : « clé de config sans interface donc toujours à
#  zéro ».
#
#  L'affichage descend donc à « Exclure temporairement » (le pouvoir même
#  qu'exerce la commande), et le DROIT se décide dans le code.


class FauxPerms:
    def __init__(self, administrator=False):
        self.administrator = administrator


class FauxUtilisateur:
    def __init__(self, uid, roles=(), admin=False, rang=10):
        self.id = uid
        self.roles = list(roles)
        self.guild_permissions = FauxPerms(admin)
        self.top_role = FauxRole(900 + uid, "rang", position=rang)


class FauxCible:
    def __init__(self, rang=5):
        self.top_role = FauxRole(800, "cible", position=rang)


class FauxInteraction:
    def __init__(self, user, owner_id=1):
        self.user = user
        self.guild = type("G", (), {"id": 777, "owner_id": owner_id})()


def _espace_droit(role_dir=0, user_dir=0, base_morte=False):
    async def _cfg(_gid):
        if base_morte:
            raise RuntimeError("base morte")
        return {"direction_allowed_role": role_dir,
                "direction_allowed_user": user_dir}

    ns = {
        "cfg": _cfg,
        "_logerr": lambda *a, **k: None,
        "owner_ids_module": type("O", (), {
            "is_super_owner": staticmethod(lambda uid: uid == 9)})(),
    }
    exec(_src("_autorise_radiation"), ns)      # noqa: S102 — code du dépôt
    return ns


def _droit(utilisateur, cible=None, **kw):
    ns = _espace_droit(**kw)
    return asyncio.run(ns["_autorise_radiation"](
        FauxInteraction(utilisateur), cible))


def test_la_DIRECTION_peut_radier_sans_passer_par_Integrations():
    """⚠️ LE POINT DE LA CORRECTION. Sans lui, la commande restait invisible
    pour la Direction le jour de l'attaque."""
    dir_role = FauxRole(42, "Direction", position=30)
    membre_dir = FauxUtilisateur(2, roles=[dir_role], rang=30)
    assert _droit(membre_dir, FauxCible(rang=5), role_dir=42) is None


def test_un_membre_ordinaire_est_REFUSE():
    """L'affichage est descendu à « Exclure temporairement » : sans ce
    contrôle, tous les modérateurs pourraient radier."""
    refus = _droit(FauxUtilisateur(3), FauxCible(), role_dir=42)
    assert refus and "Direction" in refus


def test_sans_role_Direction_configure_le_refus_DIT_ou_le_regler():
    """Un refus qui ne dit pas quoi faire envoie chercher dans les réglages
    Discord — là où, précisément, ça ne se règle pas."""
    refus = _droit(FauxUtilisateur(3), FauxCible())
    assert refus and "Sanctions" in refus and "Rôle Direction" in refus


def test_la_Direction_ne_peut_PAS_radier_plus_haut_qu_elle():
    """Escalade de privilège : la garde existait sur `/mod direction`, pas
    sur `/off` — qui n'était ouverte qu'aux administrateurs."""
    dir_role = FauxRole(42, "Direction", position=30)
    membre_dir = FauxUtilisateur(2, roles=[dir_role], rang=30)
    refus = _droit(membre_dir, FauxCible(rang=30), role_dir=42)
    assert refus and "supérieur" in refus


def test_le_proprietaire_et_le_super_owner_passent_toujours():
    """Sinon plus personne ne peut arrêter un compte de direction compromis."""
    assert _droit(FauxUtilisateur(1), FauxCible(rang=99)) is None
    assert _droit(FauxUtilisateur(9), FauxCible(rang=99)) is None


def test_un_administrateur_garde_son_acces():
    """Le comportement d'avant ne doit pas être retiré en chemin."""
    assert _droit(FauxUtilisateur(4, admin=True), FauxCible(rang=99)) is None


def test_une_panne_de_configuration_REFUSE_la_radiation():
    """Fail-closed. L'inverse ouvrirait la radiation à tout le serveur le jour
    où la base ne répond pas — exactement le jour d'une attaque."""
    refus = _droit(FauxUtilisateur(3), FauxCible(), base_morte=True)
    assert refus and "refusée" in refus


def test_l_affichage_descend_a_EXCLURE_et_pas_plus_bas():
    """`administrator` cachait la commande à la Direction ; sans plancher du
    tout, les 900 membres du serveur la verraient dans leur barre."""
    assert "default_permissions=discord.Permissions(moderate_members=True)" in SRC
    assert "@app_commands.default_permissions(moderate_members=True)" in SRC
    i = SRC.index("off_group = app_commands.Group(")
    assert "administrator=True" not in SRC[i:i + 900], (
        "le groupe /off est encore réservé aux administrateurs")


def test_les_QUATRE_portes_controlent_le_droit():
    """`/off on`, le clic droit, `/off off` et `/off list` : une porte oubliée
    et le contrôle ne vaut rien."""
    for nom in ("off_on_cmd", "radier_menu_contextuel", "off_off_cmd",
                "off_list_cmd"):
        assert "_autorise_radiation" in _src(nom), f"{nom} ne contrôle rien"


def test_le_picker_du_role_Direction_EXISTE():
    """⚠️ LA CLÉ ÉTAIT LUE ET ÉCRITE NULLE PART. Sans interface, elle reste à
    zéro pour toujours et tout ce qui précède ne sert à rien."""
    assert "'direction_allowed_role', " in SRC or '"direction_allowed_role", ' in SRC
    assert "_cb_set_direction" in SRC and "mpv2_set_direction" in SRC
    i = SRC.index("async def _cb_set_direction")
    assert "direction_allowed_role" in SRC[i:i + 400]
