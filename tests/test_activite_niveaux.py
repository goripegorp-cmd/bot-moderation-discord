"""Tests des roles d'inactivite, du masquage, et des textes bilingues.

Ce fichier couvre l'action la plus destructrice du bot : retirer TOUS les roles
d'un membre et lui masquer le serveur entier. On ne se contente pas de verifier
que ca marche — on verifie surtout ce que ca NE DOIT PAS toucher.
"""
import asyncio
import json

import pytest

import activite
import activite_calendrier as cal
import activite_niveaux as niv
import activite_textes as txt


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════════════
#  Les textes — courts, et dans les deux langues
# ═══════════════════════════════════════════════════════════════════════════════

def test_aucune_ligne_n_est_un_pave():
    """« Les gens detestent lire. » Contrainte tenue mecaniquement, pas de bonne
    volonte : le jour ou quelqu'un rajoute « juste une petite precision », ce
    test le refuse."""
    trop = txt.verifier_longueurs()
    assert trop == [], f"lignes trop longues : {trop}"


def test_tout_est_dit_en_francais_et_en_anglais():
    """« Le serveur doit etre traduit en langue internationale. »

    Une annonce qu'une moitie des membres ne comprend pas produit exactement
    l'inactivite que le systeme combat.
    """
    for bloc in (txt.revenir(), txt.vu_trop_peu(1, 7), txt.apres_expulsion(),
                 txt.retour_tout_revient(), *txt.regles(7, 14, 21)):
        assert txt.FR in bloc, bloc
        assert txt.EN in bloc, bloc
        #  Deux lignes exactement : la francaise et l'anglaise, l'une sous
        #  l'autre. Trois lignes voudrait dire qu'une langue en a deux.
        assert len(bloc.split("\n")) == 2, bloc


def test_les_regles_affichent_les_vrais_seuils():
    """Une annonce qui annonce des seuils faux est pire que pas d'annonce : elle
    rend le systeme illegitime le jour ou il agit."""
    lignes = "\n".join(txt.regles(3, 30, 90))
    assert "3 " in lignes and "30 " in lignes and "90 " in lignes
    assert "7 jours" not in lignes, "seuils ecrits en dur"


def test_aucun_jargon_dans_les_textes_membres():
    """« Sans termes techniques et complexes. » Un membre lit « 7 jours sans
    rien », pas « palier 1 atteint »."""
    tout = " ".join([txt.revenir(), txt.vu_trop_peu(1, 7), txt.apres_expulsion(),
                     txt.retour_tout_revient(), *txt.regles(7, 14, 21)]).lower()
    for mot in ("palier", "escalade", "seuil", "fenetre", "fenêtre",
                "restitution", "verdict"):
        assert mot not in tout, f"jargon dans un texte membre : {mot}"


# ═══════════════════════════════════════════════════════════════════════════════
#  La fenetre de presence — ce que « 7 derniers jours » veut dire exactement
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_fenetre_exclut_le_jour_en_cours():
    """A 9 h du matin, personne n'a encore parle.

    Compter la journee en cours ferait dependre le verdict de l'heure du
    passage : le meme membre serait « present » a 23 h et « absent » a 8 h.
    """
    assert niv is not None                      # module charge sans discord manquant
    assert activite._jour_decale(0) == cal.jour()
    assert activite._jour_decale(1) < cal.jour(), "la borne haute doit etre hier"


def test_la_fenetre_couvre_exactement_sept_jours_complets():
    """De j-7 a j-1 inclus : sept journees terminees, jamais huit ni six."""
    from datetime import datetime
    haut = datetime.strptime(activite._jour_decale(1), activite.JOUR_FMT)
    bas = datetime.strptime(activite._jour_decale(7), activite.JOUR_FMT)
    assert (haut - bas).days == 6, "sept jours inclus = six jours d'ecart"


# ═══════════════════════════════════════════════════════════════════════════════
#  Faux objets Discord — juste assez pour eprouver la selection des roles
# ═══════════════════════════════════════════════════════════════════════════════

class _Role:
    def __init__(self, rid, nom, managed=False, defaut=False, rang=1):
        self.id, self.name, self.managed, self.rang = rid, nom, managed, rang
        self._defaut = defaut

    def is_default(self):
        return self._defaut

    def __lt__(self, autre):
        return self.rang < autre.rang

    def __ge__(self, autre):
        return self.rang >= autre.rang

    def __repr__(self):
        return f"<{self.name}>"


class _Perms:
    manage_roles = True


class _Moi:
    guild_permissions = _Perms()
    top_role = _Role(999, "bot", rang=100)


class _Guild:
    id = 1
    me = _Moi()

    def __init__(self, roles=(), salons=()):
        self._roles = {r.id: r for r in roles}
        self.channels = list(salons)

    def get_role(self, rid):
        return self._roles.get(int(rid))


class _Membre:
    id = 7

    def __init__(self, roles):
        self.roles = list(roles)
        self.edits = []

    async def edit(self, roles=None, reason=None):
        self.edits.append(list(roles or []))
        self.roles = list(roles or [])


class _FauxCurseur:
    def __init__(self, ligne):
        self._ligne = ligne

    async def fetchone(self):
        return self._ligne

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FauxDB:
    def __init__(self, ligne=None):
        self.ligne = ligne
        self.ecrits = []

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("SELECT"):
            return _FauxCurseur(self.ligne)
        self.ecrits.append((sql, params))

        class _Rien:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False

            def __await__(self_inner):
                async def _n():
                    return None
                return _n().__await__()
        return _Rien()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  « Tu enleves bien TOUS les roles » — et ce qu'on n'a pas le droit d'enlever
# ═══════════════════════════════════════════════════════════════════════════════

def test_retire_tous_les_roles_ordinaires():
    """Exigence du proprietaire, mot pour mot : « Quand tu enleves les roles, tu
    l'enleves bien tous les roles. »"""
    everyone = _Role(1, "@everyone", defaut=True, rang=0)
    a, b, c = _Role(2, "Clan", rang=5), _Role(3, "Actif", rang=4), _Role(4, "Fun", rang=3)
    g = _Guild(roles=[a, b, c])
    m = _Membre([everyone, a, b, c])
    db = _FauxDB()
    ancien = activite._get_db
    activite._get_db = lambda: db
    try:
        res = _run(niv.retirer_tous_les_roles(g, m, {}))
    finally:
        activite._get_db = ancien

    assert res["ok"] is True
    assert sorted(res["retires"]) == ["Actif", "Clan", "Fun"]
    #  Il ne lui reste que @everyone, qui n'est pas un role qu'on porte.
    assert m.roles == []


def test_ne_touche_jamais_aux_roles_qu_on_ne_peut_pas_retirer():
    """Les exceptions sont imposees par Discord, pas choisies par nous.

    Demander a l'API de retirer un role d'integration ou un role au-dessus du
    bot fait echouer l'appel ENTIER — le membre resterait alors avec tous ses
    roles, y compris ceux qu'on pouvait retirer.
    """
    everyone = _Role(1, "@everyone", defaut=True, rang=0)
    boost = _Role(2, "Nitro Booster", managed=True, rang=5)
    admin = _Role(3, "Fondateur", rang=500)          # au-dessus du bot
    afk = _Role(4, "AFK", rang=2)
    normal = _Role(5, "Membre", rang=3)
    g = _Guild(roles=[boost, admin, afk, normal])
    m = _Membre([everyone, boost, admin, afk, normal])
    db = _FauxDB()
    ancien = activite._get_db
    activite._get_db = lambda: db
    try:
        res = _run(niv.retirer_tous_les_roles(
            g, m, {"activite_role_niveau1": 4}))
    finally:
        activite._get_db = ancien

    assert res["retires"] == ["Membre"]
    assert set(res["gardes"]) == {"Nitro Booster", "Fondateur", "AFK"}
    assert afk in m.roles, "l'etiquette d'absence porte le masquage : elle reste"


def test_la_liste_est_ecrite_avant_d_appeler_discord():
    """Un retrait dont on a perdu la liste, personne ne peut le defaire.

    On ecrit d'abord, on agit ensuite : dans le pire des cas on a memorise un
    retrait qui n'a pas eu lieu — anodin, la restitution ne trouvera rien a
    rendre. L'inverse serait irreversible.
    """
    import pathlib
    src = pathlib.Path("activite_niveaux.py").read_text(encoding="utf-8")
    bloc = src.split("async def retirer_tous_les_roles(")[1]
    assert bloc.index("roles_retires=?") < bloc.index("await member.edit(")


def test_les_roles_retires_sont_memorises_pour_le_retour():
    everyone = _Role(1, "@everyone", defaut=True, rang=0)
    a = _Role(2, "Clan", rang=5)
    g = _Guild(roles=[a])
    m = _Membre([everyone, a])
    db = _FauxDB()
    ancien = activite._get_db
    activite._get_db = lambda: db
    try:
        _run(niv.retirer_tous_les_roles(g, m, {}))
    finally:
        activite._get_db = ancien

    ecrit = [p for sql, p in db.ecrits if "roles_retires" in sql]
    assert ecrit, "aucune memorisation"
    assert 2 in json.loads(ecrit[0][2])


def test_le_retour_rend_tout_en_un_seul_appel():
    """Dix roles rendus un par un, c'est dix chances de s'arreter au milieu."""
    everyone = _Role(1, "@everyone", defaut=True, rang=0)
    a, b = _Role(2, "Clan", rang=5), _Role(3, "Actif", rang=4)
    g = _Guild(roles=[a, b])
    m = _Membre([everyone])
    db = _FauxDB(ligne=(json.dumps([2, 3]),))
    ancien = activite._get_db
    activite._get_db = lambda: db
    try:
        res = _run(niv.rendre_tous_les_roles(g, m, {}))
    finally:
        activite._get_db = ancien

    assert sorted(res["rendus"]) == ["Actif", "Clan"]
    assert len(m.edits) == 1, "un seul appel a l'API"


def test_un_role_hors_de_portee_reste_en_memoire():
    """Si le proprietaire redescend le role sous le bot, le prochain retour le
    rendra. L'oublier serait une perte definitive et silencieuse."""
    everyone = _Role(1, "@everyone", defaut=True, rang=0)
    haut = _Role(2, "Fondateur", rang=500)
    g = _Guild(roles=[haut])
    m = _Membre([everyone])
    db = _FauxDB(ligne=(json.dumps([2]),))
    ancien = activite._get_db
    activite._get_db = lambda: db
    try:
        res = _run(niv.rendre_tous_les_roles(g, m, {}))
    finally:
        activite._get_db = ancien

    assert res["rendus"] == []
    assert res["impossibles"] == [2]
    garde = [p for sql, p in db.ecrits if "roles_retires" in sql]
    assert json.loads(garde[0][0]) == [2]


# ═══════════════════════════════════════════════════════════════════════════════
#  Le masquage — ce qui reste visible, et ce qui ne l'est plus
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_deux_salons_d_activite_restent_ouverts():
    """« Uniquement le salon qui permet de voir ceux qui sont inactifs et le
    salon qui permet d'ecrire pour etre actif. »"""
    cfg = {"activite_salon_annonce": 10, "activite_salon_retour": 20,
           "activite_roles": {}}
    g = _Guild()
    assert niv.salons_ouverts(g, cfg) == {10, 20}


def test_les_salons_propres_a_chaque_role_restent_ouverts_aussi():
    """Masquer le salon de retour d'un autre groupe enfermerait ses membres
    sans issue — l'erreur qui transforme une mise en veille en bannissement."""
    cfg = {"activite_salon_annonce": 10, "activite_salon_retour": 20,
           "activite_roles": {"42": {"salon_annonce": 30, "salon_retour": 40}}}
    assert niv.salons_ouverts(_Guild(), cfg) == {10, 20, 30, 40}


def test_un_salon_ordinaire_devient_invisible():
    cfg = {"activite_salon_annonce": 10, "activite_salon_retour": 20,
           "activite_roles": {}}
    ow = niv._droits_voulus(99, cfg, niv.salons_ouverts(_Guild(), cfg))
    assert ow.view_channel is False


def test_le_salon_d_annonce_est_visible_mais_muet():
    """Cent absents qui repondent sous la liste la rendraient illisible."""
    cfg = {"activite_salon_annonce": 10, "activite_salon_retour": 20,
           "activite_roles": {}}
    ow = niv._droits_voulus(10, cfg, niv.salons_ouverts(_Guild(), cfg))
    assert ow.view_channel is True
    assert ow.send_messages is False


def test_le_salon_de_retour_est_le_seul_ou_l_absent_peut_ecrire():
    """C'est sa porte de sortie. Sans elle, le systeme est un piege."""
    cfg = {"activite_salon_annonce": 10, "activite_salon_retour": 20,
           "activite_roles": {}}
    ow = niv._droits_voulus(20, cfg, niv.salons_ouverts(_Guild(), cfg))
    assert ow.view_channel is True
    assert ow.send_messages is True


def test_le_masquage_ne_fait_rien_sans_role_designe():
    """Etat par defaut : masquage a `True`, mais aucun role → aucune action."""
    g = _Guild(salons=[])
    res = _run(niv.appliquer_masquage(g, dict(activite.CLES_DEFAUT)))
    assert res["modifies"] == 0
    assert "aucun rôle" in res["raison"]


def test_le_masquage_se_desactive_completement():
    cfg = dict(activite.CLES_DEFAUT)
    cfg["activite_masquer_salons"] = False
    res = _run(niv.appliquer_masquage(_Guild(), cfg))
    assert res["modifies"] == 0
    assert "désactivé" in res["raison"]


def test_le_masquage_est_annulable():
    """Un systeme de masquage qu'on ne peut pas defaire d'un clic ne devrait
    jamais etre allume. La fonction de retour arriere doit exister."""
    assert hasattr(niv, "retirer_masquage")


def test_le_pied_de_page_ne_double_pas_le_prefixe_discord():
    """`v2_subtitle` ajoute deja `-#`. Le remettre ici affichait `-# -#`,
    visible par tous les membres du serveur."""
    from datetime import datetime
    d = datetime(2026, 8, 10)
    f = datetime(2026, 8, 17)
    assert not txt.semaine_du(d, f).startswith("-#")
    assert txt.semaine_du(d, f) == "10/08 → 17/08"


def test_les_ids_afk_survivent_a_la_suppression_du_role():
    """Un role supprime cote Discord doit tout de meme etre exclu de la liste a
    memoriser, sinon on le rendrait a un membre qui ne l'a jamais eu."""
    assert niv.ids_afk({"activite_role_niveau1": 5,
                        "activite_role_niveau2": 0}) == {5}
    assert niv.ids_afk({}) == set()
