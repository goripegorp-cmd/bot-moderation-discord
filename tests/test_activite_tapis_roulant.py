"""Le tapis roulant : 25 « étiquettes appliquées » toutes les 6 h, aux MÊMES 25.

═══════════════════════════════════════════════════════════════════════════════
CE QUE LES DEUX CARTES DU 03/09/2026 MONTRENT (06 h 02, puis 12 h 02)
═══════════════════════════════════════════════════════════════════════════════
    Situation — 919 à étiqueter  ·  Appliqué — 25 étiquette(s)  ·  894 reportés
    Situation — 919 à étiqueter  ·  Appliqué — 25 étiquette(s)  ·  894 reportés

Six heures, deux passages, RIEN n'a bougé. 919 aurait dû tomber à 894.

LA CAUSE, en trois maillons dont aucun n'est faux tout seul :
  1. `classer` trie `rappel` du plus ancien au plus récent et n'écarte JAMAIS
     ceux qui portent déjà l'étiquette de leur palier ;
  2. le quota prend `cl["rappel"][:25]` — donc les 25 MÊMES à chaque passage ;
  3. `poser_niveau` rend True quand l'étiquette est déjà là, SANS rien écrire
     (`pose = cible in member.roles`). C'est voulu : le garde-fou du 12/08 lit
     ce retour comme « ce membre est-il étiqueté ? » avant d'autoriser un
     dépouillement. Mais `appliquer_rappels` le compte comme `faits += 1`.

Le compteur annonçait donc 25 poses réelles là où il n'y en avait aucune, et
894 membres n'auraient JAMAIS eu leur étiquette. Le propriétaire l'a dit
exactement : « il dit à étiqueter, mais il le fait pas de lui-même ».

⚠️ CE QU'IL NE FALLAIT SURTOUT PAS FAIRE : rendre False depuis `poser_niveau`
sur un no-op. Le garde-fou du 12/08 refuserait alors de dépouiller un membre
déjà étiqueté — pour toujours. La correction est EN AMONT : un membre pour qui
il ne reste rien à faire ne consomme plus le quota.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import activite_niveaux as niv

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PASSAGE = (RACINE / "activite_passage.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  Des faux FIDÈLES — piège n°6 du dépôt : un faux doit porter TOUT ce que
#  porte le vrai. `utilisable` lit `guild.me.guild_permissions.manage_roles`,
#  compare le rôle à `guild.me.top_role` (donc `__lt__`) et lit `.managed`.
#  `retirer_tous_les_roles` lit en plus `.is_default()`.
# ═══════════════════════════════════════════════════════════════════════════════

class FauxRole:
    def __init__(self, rid, nom="r", position=1, managed=False, defaut=False):
        self.id = rid
        self.name = nom
        self.position = position
        self.managed = managed
        self._defaut = defaut

    def is_default(self):
        return self._defaut

    def __lt__(self, autre):
        return self.position < autre.position

    def __eq__(self, autre):
        return isinstance(autre, FauxRole) and autre.id == self.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"<Role {self.name}#{self.id}>"


class FauxPerms:
    manage_roles = True


class FauxMoi:
    guild_permissions = FauxPerms()
    top_role = FauxRole(999, "bot", position=100)


class FauxGuild:
    def __init__(self, roles):
        self.id = 1
        self.me = FauxMoi()
        self._roles = {r.id: r for r in roles}

    def get_role(self, rid):
        return self._roles.get(int(rid))


class FauxMembre:
    def __init__(self, mid, roles):
        self.id = mid
        #  @everyone est TOUJOURS dans `member.roles` chez discord.py — l'omettre
        #  ferait passer le test là où la production échoue.
        self.roles = [EVERYONE] + list(roles)


EVERYONE = FauxRole(0, "@everyone", position=0, defaut=True)
R_DOUX = FauxRole(10, "peu actif", position=5)
R_N1 = FauxRole(11, "AFK", position=5)
R_N2 = FauxRole(12, "AFK dépouillé", position=5)
R_VRAI = FauxRole(20, "Membre", position=6)
R_INTEG = FauxRole(21, "Booster", position=7, managed=True)

CFG = {"activite_role_doux": 10, "activite_role_niveau1": 11,
       "activite_role_niveau2": 12, "activite_role_abandon": 0}

GUILD = FauxGuild([EVERYONE, R_DOUX, R_N1, R_N2, R_VRAI, R_INTEG])


# ═══════════════════════════════════════════════════════════════════════════════
#  `reste_a_faire` — le prédicat qui casse le tapis roulant
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_membre_deja_etiquete_na_plus_rien_a_recevoir():
    """LE CŒUR. Sans ce False, il reprend un tour de quota toutes les 6 h,
    éternellement, pendant que 894 autres attendent."""
    m = FauxMembre(1, [R_N1])
    assert niv.reste_a_faire(GUILD, m, 1, CFG) is False


def test_un_membre_sans_etiquette_en_a_besoin():
    m = FauxMembre(2, [R_VRAI])
    assert niv.reste_a_faire(GUILD, m, 1, CFG) is True


def test_une_etiquette_dun_AUTRE_palier_reste_a_retirer():
    """⚠️ `poser_niveau` ne fait pas que poser : il retire l'étiquette du palier
    précédent. Un membre qui porte les deux a encore du travail en attente —
    l'écarter le laisserait afficher deux états contradictoires pour toujours."""
    m = FauxMembre(3, [R_N1, R_DOUX])
    assert niv.reste_a_faire(GUILD, m, 1, CFG) is True


def test_palier2_reste_a_faire_tant_quun_vrai_role_subsiste():
    """Au palier 2, le vrai travail est le dépouillement. L'étiquette posée ne
    suffit pas à déclarer le membre traité."""
    m = FauxMembre(4, [R_N2, R_VRAI])
    assert niv.reste_a_faire(GUILD, m, 2, CFG) is True


def test_palier2_termine_quand_il_ne_reste_que_lintouchable():
    """@everyone, les rôles d'intégration et les étiquettes elles-mêmes ne
    partent jamais — `retirer_tous_les_roles` les garde explicitement. Les
    compter comme « du travail restant » recréerait le tapis roulant au
    palier 2."""
    m = FauxMembre(5, [R_N2, R_INTEG])
    assert niv.reste_a_faire(GUILD, m, 2, CFG) is False


def test_sans_role_configure_on_ne_saute_JAMAIS_le_membre():
    """⚠️ LE DÉFAUT INVERSE, ET IL EST PIRE. Écarter du quota un membre pour
    qui il restait du travail, c'est l'oublier en silence. Dans le doute, on
    rend True et on laisse le palier refuser lui-même — lui, il journalise."""
    cfg_vide = dict(CFG, activite_role_niveau1=0)
    m = FauxMembre(6, [R_N1])
    assert niv.reste_a_faire(GUILD, m, 1, cfg_vide) is True


def test_un_role_au_dessus_du_bot_ne_fait_pas_sauter_le_membre():
    """Un rôle intouchable est une PANNE de configuration, pas un membre
    traité. Le confondre masquerait la panne pour toujours."""
    haut = FauxRole(30, "AFK trop haut", position=200)
    g = FauxGuild([EVERYONE, haut])
    m = FauxMembre(7, [haut])
    assert niv.reste_a_faire(g, m, 1, dict(CFG, activite_role_niveau1=30)) is True


def test_reste_a_faire_ne_leve_jamais():
    """Il est appelé une fois par membre suivi — 983 fois par passage. Une
    exception y arrêterait le passage entier."""
    class Casse:
        id = 8

        @property
        def roles(self):
            raise RuntimeError("cache de rôles indisponible")

    assert niv.reste_a_faire(GUILD, Casse(), 1, CFG) is True


# ═══════════════════════════════════════════════════════════════════════════════
#  LA PREUVE QUI COMPTE : la file s'écoule vraiment
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_file_de_919_secoule_au_lieu_de_pietiner():
    """⚠️ LA RÉPRODUCTION EXACTE DU DÉFAUT, PUIS SA CORRECTION.

    919 absents, 25 par passage. Avant : `[:25]` reprenait les mêmes, donc le
    reste ne bougeait pas — deux cartes identiques à six heures d'écart. Après :
    ceux qui portent déjà l'étiquette sortent du quota, et la file descend.
    """
    QUOTA = 25
    membres = [FauxMembre(100 + i, [R_VRAI]) for i in range(919)]

    #  ── Le comportement d'AVANT, rejoué pour prouver qu'il piétinait ──
    file = list(membres)
    for _ in range(3):
        lot = file[:QUOTA]                       # aucun filtre : les mêmes
        for m in lot:
            if R_N1 not in m.roles:
                m.roles.append(R_N1)
    assert len(file) == 919, "la reproduction du défaut ne piétine pas"
    assert sum(1 for m in membres if R_N1 in m.roles) == QUOTA, (
        "trois passages n'ont touché que les 25 mêmes — c'est bien le défaut")

    #  ── Le comportement d'APRÈS ──
    for m in membres:
        m.roles = [EVERYONE, R_VRAI]             # on repart à zéro
    file = list(membres)
    vus = []
    for _ in range(4):
        file = [m for m in file if niv.reste_a_faire(GUILD, m, 1, CFG)]
        vus.append(len(file))
        for m in file[:QUOTA]:
            m.roles.append(R_N1)

    assert vus == [919, 894, 869, 844], f"la file ne s'écoule pas : {vus}"
    assert sum(1 for m in membres if R_N1 in m.roles) == 4 * QUOTA, (
        "quatre passages doivent avoir étiqueté quatre lots DIFFÉRENTS")


def test_le_passage_appelle_vraiment_le_predicat():
    """Un prédicat parfait qui n'est appelé nulle part n'a rien corrigé."""
    for n in ast.walk(ast.parse(SRC_PASSAGE)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "passage":
            corps = ast.unparse(n)
            assert "niv.reste_a_faire(" in corps, (
                "le passage ne filtre pas : le tapis roulant tourne encore")
            i_filtre = corps.index("niv.reste_a_faire(")
            i_quota = corps.index("PLAFOND_ACTIONS_PAR_PASSAGE")
            assert i_filtre < i_quota, (
                "le filtre passe APRÈS le quota : les déjà-traités auraient "
                "déjà pris les 25 places")
            return
    raise AssertionError("activite_passage.passage introuvable")


def test_les_deja_etiquetes_restent_nommes_dans_le_rappel_hebdomadaire():
    """⚠️ L'EFFET DE BORD À NE PAS CRÉER. Le rappel hebdomadaire se construit
    sur `cl["groupes"]`, que le quota filtre sur les membres retenus. Sortir
    les déjà-étiquetés du quota SANS les remettre ici les effacerait de
    l'annonce — or ce sont précisément les absents qu'elle doit nommer."""
    for n in ast.walk(ast.parse(SRC_PASSAGE)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "passage":
            corps = ast.unparse(n)
            assert "ids_deja" in corps
            i_def = corps.index("ids_deja = ")
            i_use = corps.index("| ids_deja")
            assert i_def < i_use
            return
    raise AssertionError("activite_passage.passage introuvable")


def test_poser_niveau_garde_son_contrat_de_garde_fou():
    """⚠️ CONTRE-ÉPREUVE. La correction facile aurait été de rendre False sur
    un no-op dans `poser_niveau`. Le garde-fou du 12/08 refuserait alors de
    dépouiller un membre DÉJÀ étiqueté — c'est-à-dire tous, au palier 2, pour
    toujours. Ce test interdit cette « simplification »."""
    src = (RACINE / "activite_niveaux.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "poser_niveau":
            corps = ast.unparse(n)
            assert "pose = cible in member.roles" in corps, (
                "le retour de poser_niveau ne reflète plus la seule présence "
                "de l'étiquette : le garde-fou du 12/08 est cassé")
            return
    raise AssertionError("poser_niveau introuvable")


# ═══════════════════════════════════════════════════════════════════════════════
#  « Un seul message toutes les fins de semaine »
# ═══════════════════════════════════════════════════════════════════════════════

def _boucle_activite() -> str:
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "activite_passage_task":
            return ast.unparse(n)
    raise AssertionError("activite_passage_task introuvable")


def test_la_carte_ne_part_que_le_jour_du_bilan():
    """Demandé le 03/09 : « qu'il ne m'envoie qu'un seul message toutes les
    fins de semaine ». Quatre cartes par jour, c'est ce qui a fait dire au
    propriétaire que le bot était « très relou »."""
    corps = _boucle_activite()
    assert "activite_jour_rappel" in corps, (
        "la carte ne consulte pas le jour de bilan configuré")
    assert "weekday()" in corps
    #  ⚠️ ON EXIGE LE GARDE-FOU LUI-MÊME, PAS SA VARIABLE. Une mutation qui
    #  supprimait le `continue` en laissant l'affectation passait ce test.
    assert "if not _casse and (not _est_jour_bilan)" in corps, (
        "la carte ne s'arrête plus hors du jour de bilan")
    i_garde = corps.index("if not _casse and (not _est_jour_bilan)")
    i_envoi = corps.index("resume_texte")
    assert i_garde < i_envoi, "le garde-fou est posé après l'envoi"


def test_le_travail_garde_sa_cadence():
    """⚠️ LE CONTRESENS À ÉVITER. Espacer le TRAVAIL au lieu de l'ANNONCE
    ferait passer l'écoulement des 919 de 9 jours à 37 semaines."""
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "activite_passage_task":
            heures = {d.value for d in ast.walk(n) if isinstance(d, ast.Constant)}
            break
    assert "_HEURES_PASSAGE_ACTIVITE = [" in SRC_BOT
    bloc = SRC_BOT.split("_HEURES_PASSAGE_ACTIVITE = [")[1][:200]
    assert "(0, 6, 12, 18)" in bloc, (
        "la cadence du passage a changé : le travail ne doit PAS ralentir, "
        "seule la carte devient hebdomadaire")


def test_un_suivi_mort_ne_se_tait_pas_six_jours():
    """⚠️ LA SEULE EXCEPTION, ET ELLE EST NÉCESSAIRE. `suivi_muet` veut dire
    que les sondes ne captent plus rien. Attendre dimanche pour le dire
    laisserait un système en panne passer pour un serveur calme."""
    corps = _boucle_activite()
    assert "_casse" in corps
    assert "suivi_muet" in corps
    i_casse = corps.index("_casse = ")
    i_garde = corps.index("if not _casse")
    assert i_casse < i_garde


def test_un_seul_message_meme_les_quatre_passages_du_dimanche():
    """Le jour du bilan, la boucle passe quatre fois. Sans marqueur, ce serait
    quatre cartes le dimanche au lieu de quatre par jour — à peine mieux."""
    corps = _boucle_activite()
    assert "activite_jour_alerte" in corps
    i_lu = corps.index("c.get('activite_jour_alerte')")
    i_ecrit = corps.index("'activite_jour_alerte'", i_lu + 1)
    assert i_lu < i_ecrit, "le marqueur est écrit avant d'être lu"


def test_la_carte_distingue_le_pose_du_deja_en_place():
    """« Appliqué — 25 » était indistinguable de « 25 personnes viennent d'être
    étiquetées ». C'étaient les 25 mêmes, recomptées à chaque passage."""
    for n in ast.walk(ast.parse(SRC_PASSAGE)):
        if isinstance(n, ast.FunctionDef) and n.name == "resume_texte":
            corps = ast.unparse(n)
            assert "Déjà en place" in corps
            assert "deja_au_palier" in corps
            return
    raise AssertionError("resume_texte introuvable")
