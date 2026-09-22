"""« Il écrit, et le rôle AFK ne part pas » — les quatre pièges, et la sortie.

═══════════════════════════════════════════════════════════════════════════════
LE SIGNALEMENT (22/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « Certains renvoient un message dans le truc d'activité et quand ils
      envoient un message alors qu'ils ont été AFK, le rôle ne leur est pas
      enlevé. Ce qui fait qu'ils restent toujours AFK indéfiniment. »

Le rejeu du code d'avant (vrais modules, vraie base) l'a confirmé : 4 scénarios
sur 4 laissaient le membre masqué après UN message et DEUX passages. Aucun ne
levait d'erreur — c'est ce qui les rendait invisibles.

  F1  ÉTIQUETTE ORPHELINE. Le panneau permet de désigner n'importe quel rôle
      comme étiquette d'un palier. Redésigné, l'ancien rôle n'était plus
      reconnu NULLE PART : ni par le déclencheur du retrait sur message, ni par
      le retrait, ni par le rattrapage au passage.
  F2  RETRAIT SUR MESSAGE RATÉ, MEMBRE MASQUÉ PAR CUMUL DE RAPPELS DOUX. Le
      passage le rejugeait sans savoir qu'il avait écrit : présence trop faible
      + compteur plein → « rappel » → masqué, tant qu'il n'était pas venu trois
      jours sur sept. Personne ne réessaie après un message resté sans effet.
  F3  PALIER 2 HORS PÉRIMÈTRE. Le palier 2 retire TOUS les rôles, y compris le
      rôle surveillé : le membre sortait du suivi, plus aucun passage ne le
      voyait. Seul le retrait sur message pouvait encore le sauver.
  F4  RÔLE AFK AU-DESSUS DU BOT. Non retirable, et `retirer_niveaux` rendait
      `False` sans un mot.

LA SORTIE : une marque durable « a écrit en étant masqué », posée par
`on_message` AVANT la tentative ; le passage libère tout membre marqué ; la
reconnaissance des étiquettes couvre les anciennes (registre) et les
orphelines (noms standard) ; le refus de la hiérarchie est compté et dit.
"""
from __future__ import annotations

import ast
import contextlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

import activite
import activite_calendrier as cal
import activite_escalade as esc
import activite_niveaux as niv
import activite_passage as pas

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux fidèles — piège n°6 : tout ce que le vrai porte sur ces chemins
# ═══════════════════════════════════════════════════════════════════════════════

class R:
    def __init__(self, rid, nom, rang, managed=False, defaut=False):
        self.id, self.name, self.rang, self.managed = rid, nom, rang, managed
        self._d = defaut

    def is_default(self):
        return self._d

    def __lt__(self, o):
        return self.rang < o.rang

    def __gt__(self, o):
        return self.rang > o.rang

    def __eq__(self, o):
        return isinstance(o, R) and o.id == self.id

    def __hash__(self):
        return hash(self.id)

    @property
    def mention(self):
        return f"<@&{self.id}>"


EVERY = R(1, "@everyone", 0, defaut=True)
MEMBRE = R(50, "Membre", 20)
R_DOUX = R(10, niv.NOM_DOUX, 5)
R_N1 = R(11, niv.NOM_NIVEAU1, 6)
R_N2 = R(12, niv.NOM_NIVEAU2, 7)
R_AB = R(13, niv.NOM_ABANDON, 8)


class Perms:
    manage_roles = True
    administrator = False


class Moi:
    def __init__(self, top=100):
        self.guild_permissions = Perms()
        self.top_role = R(999, "bot", top)


class G:
    def __init__(self, top=100, extra=()):
        self.id, self.name, self.owner_id = 777, "banc", 1
        self.me = Moi(top)
        self.members = []
        self._roles = {r.id: r for r in (EVERY, MEMBRE, R_DOUX, R_N1, R_N2, R_AB, *extra)}
        self.roles = list(self._roles.values())

    def get_role(self, rid):
        return self._roles.get(int(rid))

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return None


class M:
    def __init__(self, roles, guild):
        self.id, self.bot, self.guild = 4242, False, guild
        self.roles = list(roles)
        self.name = self.display_name = "membre"
        self.joined_at = datetime.now(timezone.utc) - timedelta(days=90)
        self.guild_permissions = Perms()

    @property
    def mention(self):
        return f"<@{self.id}>"

    async def add_roles(self, *rs, reason=None):
        for r in rs:
            if r not in self.roles:
                self.roles.append(r)

    async def remove_roles(self, *rs, reason=None):
        for r in rs:
            if r in self.roles:
                self.roles.remove(r)

    async def edit(self, roles=None, reason=None, **kw):
        if roles is not None:
            self.roles = list(roles)


def _j(n):
    return (cal.debut_du_jour() - timedelta(days=n)).strftime(activite.JOUR_FMT)


@pytest.fixture
def banc(tmp_path):
    chemin = tmp_path / "afk.db"
    cfg = {}

    @contextlib.asynccontextmanager
    async def _get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def _cfg(_g):
        return cfg

    async def _db_set(_g, k, v):
        cfg[k] = v

    async def _imm(_m):
        return False

    activite.setup(get_db=_get_db, cfg=_cfg, db_set=_db_set, est_immunise=_imm,
                   log=lambda *a, **k: None)
    niv.setup(log=lambda *a, **k: None)
    activite._marques_du_jour.clear()
    niv._IDS_CONNUS.clear()
    niv.BLOQUES_HIERARCHIE.clear()
    return {"db": _get_db, "cfg": cfg}


async def _monter(banc, *, roles, doux=0, jours=(10, 11), tout_le_monde=None,
                  top=100, extra=()):
    cfg = banc["cfg"]
    cfg.clear()
    cfg.update({
        "activite_enabled": True, "activite_role_doux": 10,
        "activite_role_niveau1": 11, "activite_role_niveau2": 12,
        "activite_role_abandon": 13,
        "activite_roles": {"50": {"rappel": 7, "retrait": 14, "expulsion": 21,
                                  "doux_max": 3}},
        "activite_observe_depuis": _j(40),
    })
    if tout_le_monde is not None:
        cfg["activite_tout_le_monde"] = tout_le_monde
    await activite.init_db()
    g = G(top=top, extra=extra)
    m = M(roles, g)
    g.members = [m]
    async with banc["db"]() as db:
        for n in jours:
            await db.execute("INSERT OR IGNORE INTO activite_jours(guild_id, user_id,"
                             " jour, sources) VALUES(?,?,?,?)", (g.id, m.id, _j(n), "m"))
        await db.execute("INSERT INTO activite_etat(guild_id, user_id, doux,"
                         " derniere_semaine_doux) VALUES(?,?,?,?)",
                         (g.id, m.id, doux, "2026-W30"))
        await db.commit()
    niv.memoriser_ids(await activite.config(g.id))
    return g, m


async def _ecrit(g, m, *, chemin_rapide=True):
    """EXACTEMENT ce que fait `on_message`, dans le même ordre."""
    await activite.marquer_actif(g.id, m.id, activite.SOURCE_MESSAGE)
    if niv.porte_une_etiquette(m):
        await activite.noter_retour_demande(g.id, m.id)
        if chemin_rapide:
            await pas.retour_immediat(g, m)


async def _passage(g):
    cl = await esc.classer(g)
    for f in cl["revenus"]:
        await esc.traiter_retour(g, f, await activite.config(g.id))
    return cl


def _escalade(cl, m):
    return [k for k in ("rappel", "retrait", "expulsion")
            if any(f["member"].id == m.id for f in cl[k])]


# ═══════════════════════════════════════════════════════════════════════════════
#  F1 — l'étiquette orpheline
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F1_une_etiquette_orpheline_part_au_message(banc):
    """L'ancien « 💤 AFK » (id 21) alors que le panneau désigne l'id 11 : le
    code d'avant ne le reconnaissait nulle part, ni au message ni au passage."""
    vieux = R(21, niv.NOM_NIVEAU1, 6)
    g, m = await _monter(banc, roles=[EVERY, MEMBRE, vieux], extra=(vieux,))
    assert niv.porte_une_etiquette(m), "le message ne déclenche pas le retrait"
    await _ecrit(g, m)
    assert vieux not in m.roles, "l'étiquette orpheline est restée"


@pytest.mark.asyncio
async def test_F1b_une_ancienne_etiquette_au_nom_PERSONNALISE_part_aussi(banc):
    """Le filet par le nom ne couvre que les rôles créés par le bot. Un rôle
    choisi par le propriétaire puis remplacé est couvert par le REGISTRE, que
    chaque passage tient à jour."""
    perso = R(30, "Endormis", 6)
    g, m = await _monter(banc, roles=[EVERY, MEMBRE, perso], extra=(perso,))
    banc["cfg"]["activite_role_niveau1"] = 30
    await esc.classer(g)                       # inscrit 30 au registre
    banc["cfg"]["activite_role_niveau1"] = 11  # le propriétaire en désigne un autre
    assert 30 in niv.ids_historiques(banc["cfg"], masquants_seulement=True)
    niv._IDS_CONNUS.clear()                    # un redémarrage
    niv.memoriser_ids(await activite.config(g.id))
    await _ecrit(g, m)
    assert perso not in m.roles, "l'ancien rôle personnalisé est resté"


@pytest.mark.asyncio
async def test_le_registre_SURVIT_a_config_et_s_ACCUMULE(banc):
    """⚠️ DÉFAUT RÉEL TROUVÉ PENDANT CETTE CORRECTION. `activite.config()` ne
    rend que les clés de `CLES_DEFAUT` : sans la déclarer, le registre était
    écrit puis perdu à la lecture suivante, et chaque passage l'aurait réécrit
    avec le SEUL identifiant courant. Il se serait détruit lui-même."""
    g, _m = await _monter(banc, roles=[EVERY, MEMBRE])
    await esc.classer(g)                          # inscrit 11
    banc["cfg"]["activite_role_niveau1"] = 31     # redésignation dans le panneau
    await esc.classer(g)                          # doit inscrire 31 SANS perdre 11
    hist = (await activite.config(g.id))[niv.CLE_HISTORIQUE]
    assert {11, 31} <= set(hist.get("activite_role_niveau1", [])), (
        f"le registre ne s'accumule pas : {hist}")


def test_le_registre_ne_rapetisse_JAMAIS():
    """Un identifiant périmé coûte une comparaison ; un identifiant oublié laisse
    quelqu'un masqué pour toujours."""
    cfg = {"activite_role_niveau1": 11,
           niv.CLE_HISTORIQUE: {"activite_role_niveau1": [30]}}
    neuf = niv.registre_a_jour(cfg)
    assert neuf["activite_role_niveau1"] == [30, 11]
    cfg[niv.CLE_HISTORIQUE] = neuf
    assert niv.registre_a_jour(cfg) is None, "une écriture inutile à chaque passage"


# ═══════════════════════════════════════════════════════════════════════════════
#  F2 — le retrait sur message a raté
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F2_le_passage_libere_celui_qui_a_ecrit_meme_si_le_message_a_rate(banc):
    """⚠️ LE CAS LE PLUS PROBABLE EN PRODUCTION. Masqué par cumul de rappels
    doux (doux=2), il écrit ; le retrait sur message rate. L'ancien passage le
    reclassait « rappel » et le gardait masqué."""
    g, m = await _monter(banc, roles=[EVERY, MEMBRE, R_N1], doux=2, jours=(6, 13, 20))
    await _ecrit(g, m, chemin_rapide=False)
    assert R_N1 in m.roles, "la situation de départ n'est pas reproduite"
    await _passage(g)
    assert R_N1 not in m.roles, "le passage ne l'a pas libéré"
    etat = await activite.lire_etat(g.id, m.id)
    assert etat["doux"] == 0, "l'ardoise n'est pas effacée : il serait remasqué"
    assert not etat["retour_demande"], "marque restée : immunité permanente"
    cl = await esc.classer(g)
    assert not _escalade(cl, m), "le passage d'APRÈS le remasque"


# ═══════════════════════════════════════════════════════════════════════════════
#  F3 — le palier 2 sorti du périmètre
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F3_un_palier_2_hors_perimetre_est_libere_et_recupere_ses_roles(banc):
    """« Tout le serveur » décoché : le rôle surveillé lui a été retiré avec les
    autres, il n'était plus dans aucun passage."""
    g, m = await _monter(banc, roles=[EVERY, R_N2], jours=(16, 17), tout_le_monde=False)
    async with banc["db"]() as db:
        await db.execute("UPDATE activite_etat SET roles_retires='[50]', palier=2"
                         " WHERE guild_id=? AND user_id=?", (g.id, m.id))
        await db.commit()
    await _ecrit(g, m, chemin_rapide=False)
    cl = await _passage(g)
    assert cl["hors_perimetre"] == 1
    assert R_N2 not in m.roles and MEMBRE in m.roles


@pytest.mark.asyncio
async def test_F3b_hors_perimetre_mais_SILENCIEUX_on_ne_l_escalade_pas(banc):
    """Repris pour être LIBÉRÉ, jamais pour être jugé : un membre hors
    périmètre et toujours absent ne doit entrer dans aucune liste
    d'escalade."""
    g, m = await _monter(banc, roles=[EVERY, R_N2], jours=(30,), tout_le_monde=False)
    cl = await esc.classer(g)
    assert not _escalade(cl, m)


@pytest.mark.asyncio
async def test_F3c_les_intouchables_hors_perimetre_le_restent(banc):
    g, m = await _monter(banc, roles=[EVERY, R_N2], jours=(16,), tout_le_monde=False)
    m.guild_permissions = type("P", (), {"administrator": True, "manage_roles": True})()
    assert await esc._liberable_hors_perimetre(m, banc["cfg"]) is False


# ═══════════════════════════════════════════════════════════════════════════════
#  F4 — la hiérarchie
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_F4_un_role_au_dessus_du_bot_est_COMPTE_et_la_marque_gardee(banc):
    """Le bot ne peut pas le réparer seul : il doit le DIRE. Et la marque
    reste, pour que le membre soit libéré dès que le propriétaire remonte le
    rôle du bot — sans avoir à réécrire."""
    haut = R(11, niv.NOM_NIVEAU1, 150)
    g, m = await _monter(banc, roles=[EVERY, MEMBRE, haut], extra=(haut,), top=100)
    await _ecrit(g, m)
    assert niv.BLOQUES_HIERARCHIE.get(g.id, {}).get(11, 0) >= 1, "blocage silencieux"
    assert (await activite.lire_etat(g.id, m.id))["retour_demande"]


def test_F4_le_compte_rendu_dit_quoi_faire():
    """Le seul cas que le bot ne répare pas : la carte doit nommer le rôle et
    l'action du propriétaire."""
    txt = (RACINE / "activite_passage.py").read_text(encoding="utf-8")
    assert "ne peuvent PAS être libérés" in txt
    assert "remontez le rôle du bot" in txt
    assert "NON LIBÉRABLES" in SRC_BOT


# ═══════════════════════════════════════════════════════════════════════════════
#  Pas d'immunité permanente, pas de remasquage immédiat
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_une_marque_PERIMEE_ne_donne_aucune_immunite(banc):
    """⚠️ LA MARQUE BLOQUE LA POSE. Laissée en place sur un membre qui n'est plus
    masqué, il deviendrait impossible à remasquer — le contraire de la règle
    du propriétaire, « s'il redevient inactif, on le redétecte »."""
    g, m = await _monter(banc, roles=[EVERY, MEMBRE], jours=(10, 11))
    await activite.noter_retour_demande(g.id, m.id)
    cl = await esc.classer(g)
    assert not (await activite.lire_etat(g.id, m.id))["retour_demande"]
    await esc.appliquer_rappels(g, cl["rappel"], banc["cfg"])
    assert R_N1 in m.roles, "il n'a pas pu être remasqué"


@pytest.mark.asyncio
async def test_il_ecrit_entre_le_classement_et_la_pose(banc):
    """Un passage sur 900 membres dure des minutes. Celui qui écrit entre le
    classement et la pose était remasqué juste après avoir été libéré."""
    g, m = await _monter(banc, roles=[EVERY, MEMBRE], jours=(10, 11))
    cl = await esc.classer(g)
    m.roles.append(R_N1)
    await _ecrit(g, m)
    await activite.noter_retour_demande(g.id, m.id)
    r = await esc.appliquer_rappels(g, cl["rappel"], banc["cfg"])
    assert R_N1 not in m.roles
    assert r.get("revenus_entre_temps") == 1


@pytest.mark.asyncio
async def test_le_chemin_normal_reste_intact(banc):
    """Contre-épreuve : le retrait sur message qui MARCHE libère tout de suite,
    et le passage suivant ne le remasque pas."""
    g, m = await _monter(banc, roles=[EVERY, MEMBRE, R_N1], jours=(10, 11))
    await _ecrit(g, m)
    assert R_N1 not in m.roles
    cl = await esc.classer(g)
    assert not _escalade(cl, m)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le câblage — une fonction non appelée n'est pas opérationnelle
# ═══════════════════════════════════════════════════════════════════════════════

def _on_message() -> str:
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_message":
            return ast.unparse(n)
    raise AssertionError("on_message introuvable")


def test_on_message_pose_la_marque_AVANT_de_tenter_le_retrait():
    """L'inverse ferait perdre exactement le cas qu'elle doit couvrir."""
    c = _on_message()
    assert c.index("noter_retour_demande(") < c.index("retour_immediat(")


def test_la_tache_du_retrait_est_RETENUE():
    """Sans référence, une tâche peut être ramassée en plein `await`."""
    c = _on_message()
    assert "_TACHES_RETOUR_AFK.add(" in c and "add_done_callback" in c


def test_la_reconnaissance_elargie_ne_sert_QU_A_RETIRER():
    """⚠️ Poser ou masquer à partir des anciens rôles étiquetterait des gens
    avec un rôle que le propriétaire a cessé d'utiliser."""
    src = (RACINE / "activite_niveaux.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in (
                "poser_niveau", "roles_afk", "appliquer_masquage", "ids_afk"):
            corps = ast.unparse(n)
            for interdit in ("est_etiquette", "etiquettes_portees",
                             "ids_historiques", "NOMS_MASQUANTS"):
                assert interdit not in corps, f"{n.name} utilise {interdit}"
