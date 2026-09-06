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

    def __eq__(self, autre):
        return isinstance(autre, FauxRole) and autre.id == self.id

    def __hash__(self):
        return hash(self.id)


class FauxMembre:
    def __init__(self, roles, journal):
        self.id = 4242
        self.roles = list(roles)
        self._j = journal

    async def timeout(self, duree, reason=None):
        self._j.append("timeout")

    async def edit(self, roles=None, reason=None):
        self._j.append("edit_roles")
        self.roles = list(roles or [])


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


def _espace(journal, db_ok=True):
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
    }
    exec(_src("_verrouiller_salons_radie"), ns)   # noqa: S102 — code du dépôt
    exec(_src("_radier_membre"), ns)              # noqa: S102 — code du dépôt
    return ns


def _jouer(db_ok=True, salons=6):
    journal = []
    moi = FauxMoi()
    radie = FauxRole(999, "🚫 Radié", position=50)
    porte = [FauxRole(0, "@everyone", position=0, defaut=True),
             FauxRole(1, "Membre", position=5),
             FauxRole(2, "Booster", position=6, managed=True)]
    m = FauxMembre(porte, journal)
    g = FauxGuild(moi, [radie] + porte, [FauxSalon(journal) for _ in range(salons)],
                  journal)
    ns = _espace(journal, db_ok=db_ok)

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
