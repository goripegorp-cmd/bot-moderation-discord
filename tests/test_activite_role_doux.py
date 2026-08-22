"""L'étiquette « Peu actif » — demandée le 20/08/2026, capture à l'appui.

LA DEMANDE, MOT POUR MOT
    « Il mentionne chaque personne alors que je veux que chaque personne qui
      soit inactif sur le serveur […] aient tous un rôle, un premier rôle
      d'inactivité, comme ça au lieu de mentionner 20000 personnes […] tu fais
      en sorte de mentionner un rôle qui mentionne tout le monde, comme ça les
      gens ils savent s'ils sont actifs ou inactifs. »

CE QUE MONTRAIT SA CAPTURE (salon #actif)
    « 👀 Presque · Almost » puis 30 mentions individuelles, puis « +929 ».
    959 membres listés un par un.

LA CAUSE
`activite_message.construire` savait DÉJÀ mentionner un rôle — le code le fait
pour les paliers « rappel » et « retrait ». Mais `activite_passage` câblait le
palier doux à `None` :

    _roles = {"doux": None, "rappel": _r1, "retrait": _r2}

avec ce commentaire pour le justifier : « le palier doux n'en a AUCUN […] ils
sont peu nombreux PAR CONSTRUCTION ». L'hypothèse était fausse en production.

⚠️ LES QUATRE PIÈGES DE CE CORRECTIF, tous vérifiés ici :

 1. NE PAS mettre l'étiquette douce dans `roles_afk` / `ids_afk` : ces
    fonctions pilotent le MASQUAGE des salons et le cache du retour immédiat.
    L'y verser masquerait le serveur à des centaines de membres présents, et
    remettrait leur compteur de rappels doux à zéro à leur premier message —
    rouvrant le contournement « je poste une fois par semaine ».
 2. `poser_niveau` doit rendre la POSE, jamais le retrait : c'est ce retour que
    lit le garde-fou anti-dépouillement.
 3. `retirer_niveaux` doit lire les TROIS étiquettes, sinon l'étiquette douce
    devient un cliquet qui s'accumule jusqu'à mentionner tout le serveur.
 4. `retirer_tous_les_roles` doit la GARDER, sinon elle est mémorisée comme un
    vrai rôle du membre et lui est rendue au retour.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import activite
import activite_message as msgs
import activite_niveaux as niv
import activite_textes as txt

RACINE = Path(__file__).resolve().parent.parent
SRC_PASS = (RACINE / "activite_passage.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  Doublures
# ═══════════════════════════════════════════════════════════════════════════════

class FauxRole:
    def __init__(self, rid, rang=10, managed=False, membres=0):
        self.id, self.rang, self.managed = rid, rang, managed
        self.name = f"role{rid}"
        self.members = [object()] * membres

    def __lt__(self, a):
        return self.rang < a.rang

    def __eq__(self, a):
        return isinstance(a, FauxRole) and self.id == a.id

    def __hash__(self):
        return hash(self.id)

    def is_default(self):
        return False

    @property
    def mention(self):
        return f"<@&{self.id}>"


class FauxPerms:
    manage_roles = True


class FauxMe:
    def __init__(self, top):
        self.guild_permissions = FauxPerms()
        self.top_role = top


class FauxGuild:
    def __init__(self, roles, top=100):
        self._roles = {r.id: r for r in roles}
        self.me = FauxMe(FauxRole(999, top))

    def get_role(self, rid):
        return self._roles.get(int(rid))


class FauxMembre:
    #  ⚠️ Piège n°6 du dépôt : une doublure doit porter TOUT ce que porte
    #  l'objet réel. `_ligne` lit `.mention`, et sans lui le repli « on liste »
    #  ne se testait pas du tout.
    _suivant = 1000

    def __init__(self, roles):
        FauxMembre._suivant += 1
        self.id = FauxMembre._suivant
        self.roles = list(roles)
        self.ajoutes, self.retires = [], []

    @property
    def mention(self):
        return f"<@{self.id}>"

    async def add_roles(self, *rs, reason=None):
        self.ajoutes.extend(rs)
        self.roles.extend(rs)

    async def remove_roles(self, *rs, reason=None):
        self.retires.extend(rs)
        for r in rs:
            if r in self.roles:
                self.roles.remove(r)


R0 = FauxRole(10, 5)     # « peu actif »
R1 = FauxRole(11, 6)     # palier 1
R2 = FauxRole(12, 7)     # palier 2
CFG = {"activite_role_doux": 10, "activite_role_niveau1": 11,
       "activite_role_niveau2": 12}


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Piège n°1 — masquage et retour immédiat ne voient QUE deux rôles
# ═══════════════════════════════════════════════════════════════════════════════

def test_ids_afk_ignore_letiquette_douce():
    """⚠️ LE TEST CANARI. `ids_afk` pilote le masquage : y ajouter l'étiquette
    douce poserait `view_channel=False` sur tous les salons pour des centaines
    de membres qui viennent d'écrire."""
    assert niv.ids_afk(CFG) == {11, 12}


def test_roles_afk_ignore_letiquette_douce():
    assert [r.id for r in niv.roles_afk(FauxGuild([R0, R1, R2]), CFG)] == [11, 12]


def test_le_cache_du_retour_immediat_ignore_letiquette_douce():
    """S'il la connaissait, le premier message d'un membre « peu actif »
    déclencherait `retour_immediat` → `remettre_doux` : son compteur
    retomberait à zéro chaque semaine et il ne monterait jamais d'un palier."""
    niv.memoriser_ids(CFG)
    assert 10 not in niv._IDS_CONNUS
    assert {11, 12} <= niv._IDS_CONNUS


def test_les_etiquettes_sont_bien_trois_et_dans_lordre():
    assert niv.ids_etiquettes(CFG) == {10, 11, 12}
    assert [r.id for r in niv.roles_etiquettes(FauxGuild([R0, R1, R2]), CFG)] == [10, 11, 12]


# ═══════════════════════════════════════════════════════════════════════════════
#  2. La pose du palier 0
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_palier_0_pose_letiquette_douce():
    g, m = FauxGuild([R0, R1, R2]), FauxMembre([])
    assert await niv.poser_niveau(g, m, 0, CFG) is True
    assert R0 in m.roles


@pytest.mark.asyncio
async def test_passer_de_doux_au_palier_1_echange_les_etiquettes():
    """Jamais deux étiquettes à la fois : elles diraient deux choses
    contradictoires sur le même membre."""
    g, m = FauxGuild([R0, R1, R2]), FauxMembre([R0])
    assert await niv.poser_niveau(g, m, 1, CFG) is True
    assert R1 in m.roles and R0 not in m.roles


@pytest.mark.asyncio
async def test_deja_etiquette_rend_vrai_sans_ecrire():
    """Sinon chaque passage réécrirait le même rôle sur des centaines de
    membres — et consommerait tout le budget de débit pour rien."""
    g, m = FauxGuild([R0]), FauxMembre([R0])
    assert await niv.poser_niveau(g, m, 0, CFG) is True
    assert m.ajoutes == []


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Piège n°2 — le retour de `poser_niveau` reflète la POSE
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cible_au_dessus_du_bot_refuse_et_ne_retire_rien():
    """⚠️ LE GARDE-FOU. Un rôle plus haut que le bot est intouchable. L'ancien
    code retirait quand même l'étiquette précédente et rendait True sur ce seul
    retrait : le garde-fou anti-dépouillement laissait alors passer."""
    haut = FauxRole(12, 500)                      # palier 2 au-dessus du bot
    g = FauxGuild([R0, R1, haut], top=100)
    m = FauxMembre([R0])
    assert await niv.poser_niveau(g, m, 2, CFG) is False
    assert m.retires == [], "il ne doit RIEN retirer s'il ne peut pas étiqueter"
    assert R0 in m.roles


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Pièges n°3 et n°4 — le retrait et la sauvegarde
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_le_retour_retire_aussi_letiquette_douce():
    """⚠️ Sans ça le rôle est un cliquet : il s'accumule semaine après semaine
    sur des gens redevenus actifs, et le ping finit par mentionner tout le
    serveur — exactement ce que le propriétaire veut tuer."""
    g, m = FauxGuild([R0, R1, R2]), FauxMembre([R0])
    assert await niv.retirer_niveaux(g, m, CFG) is True
    assert R0 not in m.roles


def _fonction_de(fichier: str, nom: str) -> str:
    """Le corps d'une fonction, isolé par l'AST.

    ⚠️ Pas par découpe de chaîne : la première version de ce test prenait les
    1600 premiers caractères après le `def`, et le docstring les mangeait
    entièrement. Un test qui échoue pour une raison qui n'est pas celle qu'il
    surveille est pire qu'un test absent.
    """
    src = (RACINE / fichier).read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans {fichier}")


def test_le_depouillement_garde_les_trois_etiquettes():
    """⚠️ `retirer_tous_les_roles` mémorise ce qu'il retire pour le rendre plus
    tard. Si l'étiquette douce y entrait, on la RENDRAIT au membre le jour de
    son retour, comme si c'était un de ses vrais rôles."""
    corps = _fonction_de("activite_niveaux.py", "retirer_tous_les_roles")
    assert "ids_etiquettes(cfg_act)" in corps, (
        "le dépouillement doit épargner les TROIS étiquettes")
    assert "ids_afk(cfg_act)" not in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  5. Le seuil suit la fenêtre réellement observée
# ═══════════════════════════════════════════════════════════════════════════════

CONF = {"expulsion": 21, "retrait": 14, "rappel": 7, "presence": 3, "doux_max": 3}


def _mesure(presents, fenetre, voulue=7, silence=0):
    return {"silence": silence, "presents": presents, "fenetre": fenetre,
            "fenetre_voulue": voulue, "jugeable": True}


def test_fenetre_pleine_le_seuil_ne_bouge_pas():
    assert activite.verdict(_mesure(3, 7), CONF) == "actif"
    assert activite.verdict(_mesure(2, 7), CONF) == "doux"


def test_fenetre_courte_le_seuil_est_mis_a_lechelle():
    """⚠️ LA CAUSE DES 959. Observé depuis 3 jours, le seuil de 3 exigeait une
    présence PARFAITE 3/3. Un membre venu 2 jours sur 3 — très présent — était
    étiqueté « peu actif ». Étiqueter des gens actifs discrédite tout."""
    assert activite.verdict(_mesure(1, 3), CONF) == "actif"
    assert activite.verdict(_mesure(2, 3), CONF) == "actif"


def test_un_seul_jour_observe_un_seul_jour_suffit():
    assert activite.verdict(_mesure(1, 1), CONF) == "actif"
    assert activite.verdict(_mesure(0, 1), CONF) == "doux"


def test_zero_presence_reste_doux_quelle_que_soit_la_fenetre():
    """Ceux de la capture — vus 0 jour — restent bien classés."""
    for f in (1, 3, 7):
        assert activite.verdict(_mesure(0, f), CONF) == "doux"


def test_presence_renvoie_la_fenetre_voulue():
    """Sans elle, `verdict` ne peut pas mettre le seuil à l'échelle."""
    src = (RACINE / "activite.py").read_text(encoding="utf-8")
    assert '"fenetre_voulue": fenetre_voulue' in src


# ═══════════════════════════════════════════════════════════════════════════════
#  6. Le message : un rôle, pas 959 pseudos
# ═══════════════════════════════════════════════════════════════════════════════

def _fiches(n, presents=0, fenetre=3):
    return [{"member": FauxMembre([]), "presents": presents, "fenetre": fenetre,
             "jours": 0, "seuils": CONF} for _ in range(n)]


def _textes(vue) -> str:
    out = []

    def descendre(noeuds):
        for x in noeuds:
            if isinstance(x, dict):
                if x.get("content"):
                    out.append(x["content"])
                for c in ("components", "component"):
                    v = x.get(c)
                    if isinstance(v, list):
                        descendre(v)
                    elif isinstance(v, dict):
                        descendre([v])
    descendre(vue.to_components())
    return "\n".join(out)


def test_avec_un_role_le_message_ne_liste_personne():
    """⚠️ LE CŒUR DE LA DEMANDE."""
    role = FauxRole(10, membres=959)
    t = _textes(msgs.construire(_fiches(959), palier="doux", role_ping=role))
    assert "<@&10>" in t, "le rôle doit être mentionné"
    assert "+" not in t.split("membre(s) concerné")[0], (
        "plus de « +929 » : personne n'est listé")
    assert "959" in t


def test_le_message_annonce_ce_que_le_role_touche():
    """⚠️ Pendant l'écoulement, le rôle porte moins de monde que le classement
    n'en compte. Annoncer `len(fiches)` promettrait une portée qu'on n'a pas."""
    role = FauxRole(10, membres=240)
    t = _textes(msgs.construire(_fiches(959), palier="doux", role_ping=role))
    assert "240" in t and "959" not in t


def test_avec_un_role_on_annonce_la_regle_pas_le_chiffre_dun_seul():
    """Le palier doux couvre 0/3, 1/3 et 2/3 : afficher « Vu 0 jour sur 3 »
    serait faux pour la plupart, et il n'y a plus de ligne par membre pour
    rétablir la vérité."""
    role = FauxRole(10, membres=5)
    t = _textes(msgs.construire(_fiches(5, presents=0), palier="doux", role_ping=role))
    assert "Vu 0 jour" not in t
    assert "au moins" in t


def test_sans_role_on_liste_encore_borne():
    """Repli inchangé quand aucun rôle n'est configuré : mieux vaut une liste
    bornée que rien du tout."""
    t = _textes(msgs.construire(_fiches(40), palier="doux"))
    assert "+" in t


def test_le_texte_de_regle_est_bilingue_et_court():
    s = txt.presence_demandee(3, 7)
    assert "🇫🇷" in s and "🇬🇧" in s
    assert not txt.verifier_longueurs()


# ═══════════════════════════════════════════════════════════════════════════════
#  7. Le câblage — sans lui, rien de tout ça ne sert
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_passage_donne_enfin_un_role_au_palier_doux():
    assert '"doux": _r0' in SRC_PASS
    assert '"doux": None' not in SRC_PASS, (
        "le palier doux ne doit plus être câblé à None")


def test_le_passage_pose_les_etiquettes_avec_un_budget():
    assert "appliquer_doux" in SRC_PASS
    assert "BUDGET_ETIQUETTES_PAR_PASSAGE" in SRC_PASS


def test_le_doux_nentre_pas_dans_le_quota_destructeur():
    """⚠️ Avec 959 fiches, `quota_atteint` et `anormal` seraient vrais à chaque
    passage — on retrouverait le bruit « 941 actions » du 12/08."""
    arbre = ast.parse(SRC_PASS)
    for n in ast.walk(arbre):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "passage":
            corps = ast.unparse(n)
            ligne = [l for l in corps.splitlines() if "applicables = " in l]
            assert ligne, "la ligne du quota a disparu"
            assert "doux" not in ligne[0]
            return
    raise AssertionError("passage introuvable")


def test_le_compteur_doux_recoit_toujours_la_liste_complete():
    """Le compteur est l'horloge de l'escalade : le faire dépendre d'un budget
    d'appels ferait avancer les paliers à des vitesses différentes."""
    assert "noter_rappels_doux(guild, cl[\"doux\"])" in SRC_PASS
