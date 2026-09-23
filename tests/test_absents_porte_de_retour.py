"""Les absents ne voient plus RIEN — sauf la porte, et ce que le propriétaire choisit.

═══════════════════════════════════════════════════════════════════════════════
LA DEMANDE (23/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « Quand il a ces deux rôles, je veux qu'il ne voit plus aucun salon sauf
      deux salons que je définirai moi-même dans le système d'activité. […]
      Par défaut, quand il a l'un de ces deux rôles, il ne voit plus rien.
      C'est moi qui dois donc ajouter manuellement des salons qu'il verra. […]
      Quand il redevient actif, qu'il envoie un fameux message dans ce salon,
      son message se fera automatiquement supprimer, et il gagnera les accès
      au serveur. Ça lui dira : attention, pour garder cette activité,
      n'oublie pas d'être actif […] un bonjour, un bonsoir, ou d'être actif
      sur les réactions. »

CE QUI EXISTAIT, ET QUI NE LE FAISAIT PAS
  · le salon d'annonce était ouvert D'OFFICE aux absents — rien n'était choisi ;
  · la porte de retour ne supprimait rien et ne disait rien ;
  · le salon AFK (qui, lui, supprime) était INVISIBLE aux absents ;
  · un piège latent : un salon d'annonce sans salon de retour laissait masquer
    — l'absent lisait un salon et ne pouvait plus écrire nulle part.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord
import pytest

import activite
import activite_calendrier as cal
import activite_niveaux as niv
import activite_panneau as panneau
import activite_passage as pas
import activite_textes as txt

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux fidèles — piège n°6 : tout ce que le vrai porte sur ces chemins
# ═══════════════════════════════════════════════════════════════════════════════

class R:
    def __init__(self, rid, nom, rang, managed=False, defaut=False):
        self.id, self.name, self.rang, self.managed = rid, nom, rang, managed
        self._d = defaut
        self.members = []

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


EVERY = R(777, "@everyone", 0, defaut=True)     # même id que la guilde
MEMBRE = R(50, "Membre", 20)
R_DOUX = R(10, niv.NOM_DOUX, 5)
R_N1 = R(11, niv.NOM_NIVEAU1, 6)
R_N2 = R(12, niv.NOM_NIVEAU2, 7)
R_AB = R(13, niv.NOM_ABANDON, 8)


class Perms:
    manage_roles = True
    administrator = False
    mention_everyone = True


class Moi:
    def __init__(self, top=100):
        self.guild_permissions = Perms()
        self.top_role = R(999, "bot", top)


class Salon:
    """Un salon : ses surcharges (lues ET posées), ses envois, ses droits."""

    def __init__(self, cid, public=True, gerer=True):
        self.id, self.name = cid, f"salon-{cid}"
        self.mention = f"<#{cid}>"
        self.overwrites = {}
        self.poses = {}
        self.envoyes = []
        self._public, self._gerer = public, gerer

    def overwrites_for(self, role):
        return self.poses.get(role.id, discord.PermissionOverwrite())

    async def set_permissions(self, role, overwrite=None, reason=None):
        if overwrite is None:
            self.poses.pop(role.id, None)
        else:
            self.poses[role.id] = overwrite

    def permissions_for(self, cible):
        salon = self

        class _P:
            view_channel = salon._public
            manage_messages = salon._gerer
        return _P()

    async def send(self, texte, **kw):
        self.envoyes.append((texte, kw))
        return None


class G:
    def __init__(self, salons=(), top=100):
        self.id, self.name, self.owner_id = 777, "banc", 1
        self.me = Moi(top)
        self.default_role = EVERY
        self.members = []
        self.channels = list(salons)
        self._roles = {r.id: r for r in (EVERY, MEMBRE, R_DOUX, R_N1, R_N2, R_AB)}
        self.roles = list(self._roles.values())

    def get_role(self, rid):
        return self._roles.get(int(rid or 0))

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return next((s for s in self.channels if s.id == int(cid or 0)), None)


class M:
    def __init__(self, roles, guild):
        self.id, self.bot, self.guild = 4242, False, guild
        self.roles = list(roles)
        self.name = self.display_name = "membre"
        self.joined_at = datetime.now(timezone.utc) - timedelta(days=90)
        self.guild_permissions = Perms()
        self.mps = []

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

    async def send(self, texte, **kw):
        self.mps.append(texte)


class Msg:
    def __init__(self, salon, guild, auteur, texte="coucou"):
        self.channel, self.guild, self.author = salon, guild, auteur
        self.content, self.pinned = texte, False
        self.supprime = False

    async def delete(self):
        self.supprime = True


def _j(n):
    return (cal.debut_du_jour() - timedelta(days=n)).strftime(activite.JOUR_FMT)


PORTE, ANNONCE, CHOISI, AUTRE, AFK = 500, 510, 520, 530, 540


@pytest.fixture
def banc(tmp_path, monkeypatch):
    chemin = tmp_path / "porte.db"
    cfg = {}
    journal = []

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
    pas.setup(log=lambda *a, **k: journal.append(" ".join(map(str, a))))
    panneau.setup(db_set=_db_set, log=lambda *a, **k: journal.append(" ".join(map(str, a))))
    activite._marques_du_jour.clear()
    niv._IDS_CONNUS.clear()
    niv.BLOQUES_HIERARCHIE.clear()
    pas._retours_en_cours.clear()
    sommeils = []

    async def _dort(n):
        sommeils.append(n)

    monkeypatch.setattr(pas.asyncio, "sleep", _dort)
    return {"db": _get_db, "cfg": cfg, "journal": journal, "sommeils": sommeils}


async def _monter(banc, *, porte_publique=True, gerer=True, top=100,
                  palier_roles=(R_N2,), retires=(50,), **cfg_extra):
    """Un serveur réel en miniature : un absent au palier 2, dépouillé de
    « Membre », et une porte de retour."""
    cfg = banc["cfg"]
    cfg.clear()
    cfg.update({
        "activite_enabled": True, "activite_role_doux": 10,
        "activite_role_niveau1": 11, "activite_role_niveau2": 12,
        "activite_role_abandon": 13,
        "activite_salon_annonce": ANNONCE, "activite_salon_retour": PORTE,
        "activite_afk_secondes": 8,
        "activite_observe_depuis": _j(40),
    })
    cfg.update(cfg_extra)
    await activite.init_db()
    salons = [Salon(PORTE, public=porte_publique, gerer=gerer),
              Salon(ANNONCE), Salon(CHOISI), Salon(AUTRE)]
    g = G(salons, top=top)
    m = M([EVERY, *palier_roles], g)
    g.members = [m]
    async with banc["db"]() as db:
        await db.execute(
            "INSERT INTO activite_etat(guild_id, user_id, palier, roles_retires)"
            " VALUES(?,?,2,?)", (g.id, m.id, json.dumps(list(retires))))
        await db.commit()
    niv.memoriser_ids(await activite.config(g.id))
    return g, m


async def _ecrit(g, m, salon, texte="coucou"):
    """EXACTEMENT ce que fait `on_message`, dans le même ordre (voir B8)."""
    msg = Msg(salon, g, m, texte)
    await activite.marquer_actif(g.id, m.id, activite.SOURCE_MESSAGE)
    tache = None
    if niv.porte_une_etiquette(m):
        await activite.noter_retour_demande(g.id, m.id)
        tache = asyncio.create_task(pas.retour_immediat(g, m))
    res = None
    if tache is not None and await pas.est_salon_de_retour(g.id, salon.id):
        res = await pas.accueillir_retour(msg, tache)
    elif tache is not None:
        await tache
    return msg, res


# ═══════════════════════════════════════════════════════════════════════════════
#  A — ce que voit un absent
# ═══════════════════════════════════════════════════════════════════════════════

def test_A1_par_defaut_il_ne_voit_QUE_la_porte():
    """« Par défaut, quand il a l'un de ces deux rôles, il ne voit plus rien. »
    ⚠️ Le salon d'annonce n'est PLUS ouvert d'office : il faut le choisir."""
    cfg = dict(activite.CLES_DEFAUT, activite_salon_annonce=ANNONCE,
               activite_salon_retour=PORTE)
    assert niv.salons_ouverts(G(), cfg) == {PORTE}
    assert niv._droits_voulus(ANNONCE, cfg, {PORTE}).view_channel is False


def test_A2_les_salons_CHOISIS_sont_visibles_en_LECTURE_seule():
    """« C'est moi qui dois donc ajouter manuellement des salons qu'il verra. »
    Lecture seule, fils compris : répondre dans un fil serait une seconde
    porte que personne n'a ouverte."""
    cfg = dict(activite.CLES_DEFAUT, activite_salon_retour=PORTE,
               activite_salons_visibles=[CHOISI])
    ouverts = niv.salons_ouverts(G(), cfg)
    assert ouverts == {PORTE, CHOISI}
    lu = niv._droits_voulus(CHOISI, cfg, ouverts)
    assert lu.view_channel is True and lu.read_message_history is True
    assert lu.send_messages is False and lu.add_reactions is False
    assert lu.send_messages_in_threads is False
    assert lu.create_public_threads is False and lu.create_private_threads is False
    porte = niv._droits_voulus(PORTE, cfg, ouverts)
    assert porte.view_channel is True and porte.send_messages is True


def test_A3_le_salon_AFK_est_une_PORTE():
    """Le salon où l'on écrit « je suis là » était invisible aux absents —
    précisément ceux qui en ont besoin."""
    cfg = dict(activite.CLES_DEFAUT, activite_salon_afk=AFK)
    assert niv.salons_de_retour(cfg) == {AFK}
    assert niv._droits_voulus(AFK, cfg, niv.salons_ouverts(G(), cfg)).send_messages is True


def test_A4_le_salon_de_retour_d_un_ROLE_est_une_porte_son_annonce_non():
    cfg = dict(activite.CLES_DEFAUT, activite_salon_retour=PORTE,
               activite_roles={"42": {"salon_annonce": 610, "salon_retour": 620}})
    assert niv.salons_de_retour(cfg) == {PORTE, 620}
    assert 610 not in niv.salons_ouverts(G(), cfg)


def test_A4b_une_config_BRUTE_aux_roles_serialises_est_lue():
    """Le bilan de santé de bot.py lit la configuration sans `activite.config`."""
    brut = {"activite_roles": json.dumps({"42": {"salon_retour": 620}}),
            "activite_salons_visibles": json.dumps([CHOISI])}
    assert niv.salons_de_retour(brut) == {620}
    assert niv.salons_visibles(brut) == {CHOISI}


@pytest.mark.asyncio
async def test_A5_SANS_PORTE_le_masquage_est_REFUSE_meme_avec_des_salons_lisibles():
    """⚠️ LE PIÈGE LATENT, ET ÉLARGI : l'ancien garde-fou (`if not ouverts`)
    laissait masquer un serveur qui n'avait qu'un salon d'annonce. L'absent le
    lisait, et ne pouvait plus écrire nulle part — bannissement de fait."""
    salons = [Salon(ANNONCE), Salon(CHOISI), Salon(AUTRE)]
    g = G(salons)
    cfg = dict(activite.CLES_DEFAUT, activite_role_niveau1=11,
               activite_salon_annonce=ANNONCE, activite_salons_visibles=[CHOISI])
    res = await niv.appliquer_masquage(g, cfg)
    assert "masquage REFUSÉ" in res["raison"], res
    assert all(not s.poses for s in salons), "un droit a été posé sans porte"
    assert await niv.masquer_nouveau_salon(g, Salon(999), cfg) is False


@pytest.mark.asyncio
async def test_A6_le_VRAI_masquage_pose_exactement_ce_qui_est_demande():
    """Le serveur après passage : annonce fermée, porte en écriture, salon
    choisi en lecture, le reste fermé."""
    salons = [Salon(PORTE), Salon(ANNONCE), Salon(CHOISI), Salon(AUTRE)]
    g = G(salons)
    cfg = dict(activite.CLES_DEFAUT, activite_role_niveau2=12,
               activite_role_abandon=13, activite_salon_annonce=ANNONCE,
               activite_salon_retour=PORTE, activite_salons_visibles=[CHOISI])
    res = await niv.appliquer_masquage(g, cfg)
    assert not res["raison"] and res["modifies"] == 8, res
    vu = {s.id: s.poses[12] for s in salons}
    assert vu[AUTRE].view_channel is False and vu[ANNONCE].view_channel is False
    assert vu[PORTE].view_channel is True and vu[PORTE].send_messages is True
    assert vu[CHOISI].view_channel is True and vu[CHOISI].send_messages is False
    assert {s.id: s.poses[13].view_channel for s in salons} == {
        PORTE: True, ANNONCE: False, CHOISI: True, AUTRE: False}, (
        "le compte abandonné ne suit pas la même règle")
    #  Relancer ne réécrit rien : c'est ce qui rend le choix du panneau gratuit.
    assert (await niv.appliquer_masquage(g, cfg))["modifies"] == 0


@pytest.mark.asyncio
async def test_A7_la_cle_est_DECLAREE_et_survit_a_la_serialisation(banc):
    """`config()` jette toute clé absente de `CLES_DEFAUT` : non déclarée, le
    choix du propriétaire disparaîtrait au premier relu."""
    assert activite.CLES_DEFAUT["activite_salons_visibles"] == []
    banc["cfg"]["activite_salons_visibles"] = json.dumps([CHOISI, 521])
    assert (await activite.config(777))["activite_salons_visibles"] == [CHOISI, 521]


# ═══════════════════════════════════════════════════════════════════════════════
#  B — la porte : le message s'efface, l'accès revient, le rappel est dit
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_B1_l_absent_ecrit_dans_la_porte_TOUT_se_passe(banc):
    """Le chemin entier, vrais modules, vraie base : il retrouve ses rôles et
    la vue du serveur, lit le rappel, et son message s'efface."""
    g, m = await _monter(banc)
    porte = g.get_channel(PORTE)
    msg, res = await _ecrit(g, m, porte, "je suis là")

    assert R_N2 not in m.roles, "l'étiquette est restée : il ne voit toujours rien"
    assert MEMBRE in m.roles, "ses rôles ne sont pas revenus"
    assert res["etat"] == "libere" and res["mot"] and res["efface"], res
    assert msg.supprime is True, "« son message se fera automatiquement supprimer »"
    assert banc["sommeils"] == [8], "le message part avant d'avoir pu lire le mot"

    assert len(porte.envoyes) == 1
    texte, kw = porte.envoyes[0]
    c = await activite.config(g.id)
    exige = activite.config_du_role(c, "50")["presence"]
    for attendu in (m.mention, "Bon retour", "Welcome back", "bonjour",
                    "bonsoir", "réaction", f"{exige} jours sur {c['activite_fenetre']}",
                    "s'efface"):
        assert attendu in texte, (attendu, texte)
    assert kw.get("delete_after") == float(pas.SECONDES_MOT_DE_RETOUR)
    assert kw.get("allowed_mentions") is not None
    assert m.mps == [], "une porte publique n'a pas besoin de message privé"
    #  La preuve dans les journaux Railway : une ligne, le chemin entier.
    assert "[activite porte] retour libere · mot posté · message effacé" in \
        banc["journal"], banc["journal"]


@pytest.mark.asyncio
async def test_B2_rôles_a_VALIDER_par_le_staff_le_mot_ne_les_promet_pas(banc):
    """⚠️ UN MOT QUI MENT : « tu as retrouvé l'accès » alors que ses rôles
    attendent le staff. Il dit ce qui s'est vraiment passé."""
    g, m = await _monter(banc, activite_roles={"*": {"restitution_auto": False}})
    msg, res = await _ecrit(g, m, g.get_channel(PORTE))
    texte = g.get_channel(PORTE).envoyes[0][0]
    assert R_N2 not in m.roles and MEMBRE not in m.roles
    assert "le staff te rendra tes rôles" in texte, texte
    assert "retrouvé l'accès" not in texte
    assert msg.supprime is True


@pytest.mark.asyncio
async def test_B3_etiquette_INTOUCHABLE_le_mot_ne_ment_pas(banc):
    """Le rôle AFK au-dessus du bot : il ne peut pas partir. Dire « bon
    retour » à quelqu'un qui ne voit toujours rien le ferait réécrire en
    boucle. Le mot dit « noté, je réessaie » — et c'est vrai : la marque
    posée par `on_message` fait réessayer le passage."""
    haut = R(12, niv.NOM_NIVEAU2, 150)
    g, m = await _monter(banc, palier_roles=(haut,))
    g._roles[12] = haut
    msg, res = await _ecrit(g, m, g.get_channel(PORTE))
    texte = g.get_channel(PORTE).envoyes[0][0]
    assert res["etat"] == "bloque", res
    assert "Bon retour" not in texte and "Ton retour est noté" in texte, texte
    assert msg.supprime is True


@pytest.mark.asyncio
async def test_B3b_DEUX_etiquettes_dont_une_intouchable_reste_bloque(banc):
    """Une étiquette ancienne (redésignée) et une actuelle : la première part,
    la seconde est au-dessus du bot. Le retrait « a réussi » — mais il voit
    toujours rien. Seul l'état AVANT le retrait permet de le savoir, le cache
    de discord.py n'étant mis à jour qu'à l'événement de la passerelle."""
    haut = R(12, niv.NOM_NIVEAU2, 150)
    vieux = R(21, niv.NOM_NIVEAU1, 6)
    g, m = await _monter(banc, palier_roles=(vieux, haut))
    g._roles[12], g._roles[21] = haut, vieux
    msg, res = await _ecrit(g, m, g.get_channel(PORTE))
    assert vieux not in m.roles, "l'étiquette retirable n'est pas partie"
    assert res["etat"] == "bloque", res
    assert "Bon retour" not in g.get_channel(PORTE).envoyes[0][0]


@pytest.mark.asyncio
async def test_B4_une_RAFALE_un_seul_mot_tous_les_messages_effaces(banc):
    """« Un membre qui revient écrit rarement une seule ligne. » Le second
    message tombe sur le retour en cours : pas de second mot, mais il s'efface
    aussi — le salon reste propre."""
    g, m = await _monter(banc)
    porte = g.get_channel(PORTE)
    await activite.marquer_actif(g.id, m.id, activite.SOURCE_MESSAGE)
    await activite.noter_retour_demande(g.id, m.id)
    t1 = asyncio.create_task(pas.retour_immediat(g, m))
    t2 = asyncio.create_task(pas.retour_immediat(g, m))
    m1, m2 = Msg(porte, g, m, "salut"), Msg(porte, g, m, "je suis là")
    r1, r2 = await asyncio.gather(pas.accueillir_retour(m1, t1),
                                  pas.accueillir_retour(m2, t2))
    assert {r1["etat"], r2["etat"]} == {"libere", "en_cours"}, (r1, r2)
    assert len(porte.envoyes) == 1, "deux mots pour un seul retour"
    assert m1.supprime and m2.supprime


@pytest.mark.asyncio
async def test_B5_systeme_ETEINT_rien_n_est_fait_rien_n_est_promis(banc):
    g, m = await _monter(banc, activite_enabled=False)
    msg, res = await _ecrit(g, m, g.get_channel(PORTE))
    assert res["etat"] == "eteint"
    assert g.get_channel(PORTE).envoyes == [] and msg.supprime is False


@pytest.mark.asyncio
async def test_B6_une_porte_PRIVEE_le_rappel_part_aussi_en_prive(banc):
    """Une porte réservée aux absents disparaît de son écran dès qu'il est
    libéré : le mot posté dedans ne serait jamais lu."""
    g, m = await _monter(banc, porte_publique=False)
    await _ecrit(g, m, g.get_channel(PORTE))
    assert len(m.mps) == 1 and "Bon retour" in m.mps[0] and "bonsoir" in m.mps[0]


@pytest.mark.asyncio
async def test_B7_sans_GERER_LES_MESSAGES_le_mot_part_et_la_cause_est_ecrite(banc):
    g, m = await _monter(banc, gerer=False)
    msg, res = await _ecrit(g, m, g.get_channel(PORTE))
    assert res["mot"] is True and msg.supprime is False
    assert any("Gérer les messages" in l for l in banc["journal"]), banc["journal"]
    assert any("message NON effacé" in l for l in banc["journal"]), banc["journal"]


@pytest.mark.asyncio
async def test_B7b_ailleurs_que_dans_la_porte_ni_mot_ni_suppression(banc):
    """Palier 1 : un salon rouvert par un autre de ses rôles. Il revient —
    c'est la règle — mais son message n'est pas celui d'une porte."""
    g, m = await _monter(banc, palier_roles=(R_N1,), retires=())
    autre = g.get_channel(AUTRE)
    msg, res = await _ecrit(g, m, autre)
    assert res is None and R_N1 not in m.roles
    assert autre.envoyes == [] and msg.supprime is False


def _on_message():
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_message":
            return n
    raise AssertionError("on_message introuvable")


def test_B8_on_message_branche_la_porte_sur_la_MEME_tache_de_retour():
    """⚠️ Un second `retour_immediat` tomberait sur `_retours_en_cours` et
    rendrait « en cours » : le mot dirait que rien ne s'est passé. La porte
    attend la tâche déjà lancée — et le salon AFK devient un `elif`."""
    corps = ast.unparse(_on_message())
    assert corps.count("retour_immediat(") == 1, "deux retours lancés"
    assert "activite_pass.accueillir_retour(msg, _retour_afk)" in corps
    assert corps.index("activite_module.marquer_actif") < corps.index(
        "accueillir_retour"), "le message s'efface avant d'être compté"
    for n in ast.walk(_on_message()):
        if isinstance(n, ast.If) and "est_salon_de_retour" in ast.unparse(n.test):
            assert "_retour_afk is not None" in ast.unparse(n.test), (
                "la porte doit ne coûter rien aux membres non étiquetés")
            suite = " ".join(ast.unparse(x) for x in n.orelse)
            assert "est_salon_afk" in suite, "le salon AFK n'est plus un `elif`"
            break
    else:
        raise AssertionError("la porte n'est pas branchée dans on_message")


# ═══════════════════════════════════════════════════════════════════════════════
#  C — le mot lui-même
# ═══════════════════════════════════════════════════════════════════════════════

def test_C1_le_mot_reprend_la_demande_court_bilingue_sans_jargon():
    mot = txt.mot_de_retour("libere", exige=2, fenetre=7)
    for attendu in ("🇫🇷", "🇬🇧", "bonjour", "bonsoir", "réaction",
                    "2 jours sur 7", "2 days out of 7"):
        assert attendu in mot, (attendu, mot)
    assert txt.verifier_longueurs() == [], "une ligne dépasse la limite de lecture"
    tout = " ".join([mot, txt.mot_de_retour("bloque"),
                     txt.mot_de_retour("libere", a_valider=True)]).lower()
    for mot_interdit in ("palier", "seuil", "restitution", "escalade", "fenêtre"):
        assert mot_interdit not in tout, mot_interdit


def test_C2_hors_liberation_le_mot_ne_dit_JAMAIS_bon_retour():
    for etat in ("bloque", "erreur"):
        assert "Bon retour" not in txt.mot_de_retour(etat)


# ═══════════════════════════════════════════════════════════════════════════════
#  D — le panneau : le choix existe, il est pré-rempli, il est POSÉ
# ═══════════════════════════════════════════════════════════════════════════════

class _Reponse:
    def __init__(self):
        self._fait = False

    def is_done(self):
        return self._fait

    async def defer(self, **kw):
        self._fait = True

    async def edit_message(self, **kw):
        self._fait = True

    async def send_message(self, *a, **kw):
        self._fait = True


class _Inter:
    def __init__(self, valeurs=None):
        self.response = _Reponse()
        self.data = {"values": [str(v) for v in (valeurs or [])]}
        self.editions = []
        self.user = type("U", (), {"id": 1})()

        class _F:
            async def send(self, *a, **kw):
                pass
        self.followup = _F()

    async def edit_original_response(self, **kw):
        self.editions.append(kw)


def _compter(payload) -> int:
    n = 0
    for c in payload:
        n += 1
        n += _compter(c.get("components", []) or [])
    return n


def _trouver(payload, cid):
    for c in payload:
        if c.get("custom_id") == cid:
            return c
        t = _trouver(c.get("components", []) or [], cid)
        if t:
            return t
    return None


def _textes(payload) -> str:
    out = []
    for c in payload:
        if c.get("content"):
            out.append(c["content"])
        out.append(_textes(c.get("components", []) or []))
    return "\n".join(x for x in out if x)


@pytest.mark.asyncio
async def test_D1_le_panneau_montre_la_porte_les_choisis_et_le_MENU_pre_rempli(banc):
    g, _m = await _monter(banc, activite_salons_visibles=[CHOISI])
    vue = panneau.ActiviteRolesAfkPanelV2(type("U", (), {"id": 1})(), g)
    await vue.render_to(_Inter(), edit=False)
    payload = vue.to_components()
    assert _compter(payload) <= 40, "au-delà de 40 composants, Discord refuse"
    menu = _trouver(payload, "act_afk_visibles")
    assert menu is not None, "le choix des salons visibles n'est pas affiché"
    assert menu["min_values"] == 0 and menu["max_values"] == niv.MAX_SALONS_VISIBLES
    assert [int(d["id"]) for d in menu.get("default_values", [])] == [CHOISI], (
        "menu vide : chaque choix effacerait les précédents")
    t = _textes(payload)
    assert "La porte" in t and f"<#{PORTE}>" in t
    assert "Choisis par vous" in t and f"<#{CHOISI}>" in t
    assert "Le salon d'annonce n'y est pas" in t, (
        "le propriétaire ne saurait pas que l'annonce est désormais fermée")


@pytest.mark.asyncio
async def test_D2_choisir_des_salons_les_ENREGISTRE_et_les_POSE(banc):
    """Un choix affiché mais pas posé serait un menu qui ment pendant six
    heures, jusqu'au passage suivant."""
    g, _m = await _monter(banc)
    vue = panneau.ActiviteRolesAfkPanelV2(type("U", (), {"id": 1})(), g)
    await vue._cb_visibles(_Inter([CHOISI, ANNONCE]))
    assert banc["cfg"]["activite_salons_visibles"] == sorted([CHOISI, ANNONCE])
    assert g.get_channel(CHOISI).poses[12].view_channel is True
    assert g.get_channel(ANNONCE).poses[12].view_channel is True
    assert g.get_channel(AUTRE).poses[12].view_channel is False
    assert "enregistré(s) et posé(s)" in vue._dernier, vue._dernier
    #  Tout retirer est un choix : l'annonce se referme.
    await vue._cb_visibles(_Inter([]))
    assert banc["cfg"]["activite_salons_visibles"] == []
    assert g.get_channel(ANNONCE).poses[12].view_channel is False


@pytest.mark.asyncio
async def test_D3_la_carte_principale_dit_le_VRAI_nombre_de_salons(banc):
    g, _m = await _monter(banc, activite_salons_visibles=[CHOISI])
    src = (RACINE / "activite_panneau.py").read_text(encoding="utf-8")
    assert "les absents ne voient plus que 2 salons" not in src, (
        "le « 2 » écrit en dur est revenu")
    ouverts = [s for s in niv.salons_ouverts(g, await activite.config(g.id))
               if g.get_channel(s)]
    assert len(ouverts) == 2          # la porte + le salon choisi
