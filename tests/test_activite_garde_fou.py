"""Le garde-fou du 12/08 était contournable — trouvé le 19/08 par un audit adverse.

LA QUESTION QUI A TOUT DÉCLENCHÉ, DU PROPRIÉTAIRE
    « Est-ce que le système de vérification pour les AFK est bien opérationnel
      sur le serveur, qui vérifie bien par semaine ceux qui sont vraiment
      inactifs ? »

⚠️ DÉFAUT 1 — UN MEMBRE POUVAIT PERDRE TOUS SES RÔLES SANS ÉTIQUETTE.
`activite_escalade.py` refuse le dépouillement quand `poser_niveau` rend
False — garde-fou posé le 12/08/2026, commentaire explicite : « mieux vaut un
palier qui n'agit pas qu'un membre dépouillé que personne ne peut rhabiller ».

Il était contournable. Dans `poser_niveau(niveau=2)` :

    cible = None                       # rôle de palier 2 non configuré,
                                       # supprimé, ou au-dessus du bot
    a_retirer = [r for r in voulus if cible is None or r.id != cible.id]
    ...
    if a_retirer:
        await member.remove_roles(*a_retirer)
        fait = True                    # ← True SANS avoir posé d'étiquette
    return fait

Un membre au palier 2 porte déjà le rôle de palier 1. `a_retirer` n'était donc
pas vide, `remove_roles` réussissait, la fonction rendait True, et le garde-fou
laissait passer `retirer_tous_les_roles`. Résultat : zéro rôle, aucune
étiquette AFK, aucun masquage — exactement l'accident que le garde-fou déclare
interdire, et il suffisait qu'UN des deux rôles manque.

⚠️ DÉFAUT 2 — LE RAPPEL HEBDOMADAIRE POUVAIT ÊTRE BRÛLÉ SANS PARTIR.
`activite_passage.py` marquait la semaine comme faite dans TOUS les cas, y
compris quand l'envoi avait levé (salon interdit, message trop long). Le
journal notait l'exception, puis la semaine passait pour traitée : le rappel ne
partait jamais, et ça se répétait chaque semaine.

Ces deux défauts ne sont attrapés ni par `ast.parse`, ni par `import bot`, ni
par les tests existants : le code est valide, il fait simplement autre chose
que ce que son commentaire promet.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import activite_niveaux as niv

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PASS = (RACINE / "activite_passage.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  Doublures — un rôle Discord se compare, et c'est tout le sujet ici
# ═══════════════════════════════════════════════════════════════════════════════

class FauxRole:
    def __init__(self, rid, rang, managed=False):
        self.id, self.rang, self.managed = rid, rang, managed
        self.name = f"role{rid}"

    def __lt__(self, autre):
        return self.rang < autre.rang

    def __eq__(self, autre):
        return isinstance(autre, FauxRole) and self.id == autre.id

    def __hash__(self):
        return hash(self.id)


class FauxPerms:
    manage_roles = True


class FauxMe:
    def __init__(self, top):
        self.guild_permissions = FauxPerms()
        self.top_role = top


class FauxGuild:
    def __init__(self, roles):
        self._roles = {r.id: r for r in roles}
        self.me = FauxMe(FauxRole(999, 100))

    def get_role(self, rid):
        return self._roles.get(int(rid))


class FauxMembre:
    def __init__(self, roles):
        self.id = 42
        self.roles = list(roles)
        self.ajoutes, self.retires = [], []

    async def add_roles(self, *rs, reason=None):
        self.ajoutes.extend(rs)
        self.roles.extend(rs)

    async def remove_roles(self, *rs, reason=None):
        self.retires.extend(rs)
        for r in rs:
            if r in self.roles:
                self.roles.remove(r)


R1 = FauxRole(1, 10)   # rôle « palier 1 » — sous le bot, utilisable
R2 = FauxRole(2, 20)   # rôle « palier 2 »


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le cas nominal doit continuer de marcher
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_les_deux_roles_configures_le_palier_2_se_pose():
    g = FauxGuild([R1, R2])
    m = FauxMembre([R1])                      # il est au palier 1
    cfg = {"activite_role_niveau1": 1, "activite_role_niveau2": 2}
    assert await niv.poser_niveau(g, m, 2, cfg) is True
    assert R2 in m.ajoutes, "l'étiquette du palier 2 doit être posée"
    assert R1 in m.retires, "l'étiquette du palier 1 doit être enlevée"


@pytest.mark.asyncio
async def test_un_seul_role_dinactivite_a_la_fois():
    g = FauxGuild([R1, R2])
    m = FauxMembre([R1])
    cfg = {"activite_role_niveau1": 1, "activite_role_niveau2": 2}
    await niv.poser_niveau(g, m, 2, cfg)
    assert R1 not in m.roles and R2 in m.roles


# ═══════════════════════════════════════════════════════════════════════════════
#  2. LE DÉFAUT : palier 2 impossible → on refuse, et on ne touche à RIEN
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_palier_2_non_configure_refuse_et_ne_retire_rien():
    """⚠️ LE TEST QUI COMPTE. Sans lui, le membre perdait son étiquette de
    palier 1, `poser_niveau` rendait True, et le garde-fou laissait dépouiller."""
    g = FauxGuild([R1])
    m = FauxMembre([R1])
    cfg = {"activite_role_niveau1": 1, "activite_role_niveau2": 0}   # ← non configuré
    assert await niv.poser_niveau(g, m, 2, cfg) is False, (
        "sans étiquette posable, poser_niveau DOIT rendre False — c'est ce "
        "retour qui arme le garde-fou anti-dépouillement")
    assert m.retires == [], (
        "il ne doit RIEN retirer : enlever le palier 1 sans pouvoir poser le "
        "palier 2 laisse le membre sans étiquette")
    assert R1 in m.roles


@pytest.mark.asyncio
async def test_role_de_palier_supprime_du_serveur_refuse_aussi():
    """Le rôle est configuré mais n'existe plus : `roles_afk` ne le rend pas,
    donc `cible` reste None. Même refus."""
    g = FauxGuild([R1])                       # R2 n'existe plus sur le serveur
    m = FauxMembre([R1])
    cfg = {"activite_role_niveau1": 1, "activite_role_niveau2": 2}
    assert await niv.poser_niveau(g, m, 2, cfg) is False
    assert m.retires == []


@pytest.mark.asyncio
async def test_aucun_role_configure_refuse():
    g = FauxGuild([])
    m = FauxMembre([])
    assert await niv.poser_niveau(
        g, m, 2, {"activite_role_niveau1": 0, "activite_role_niveau2": 0}) is False


@pytest.mark.asyncio
async def test_le_garde_fou_de_lescalade_lit_bien_ce_retour():
    """Le refus ne sert à rien si l'appelant ne le regarde pas."""
    src = (RACINE / "activite_escalade.py").read_text(encoding="utf-8")
    assert "if not await niv.poser_niveau(guild, member, 2, cfg_act):" in src
    #  … et il doit sortir SANS dépouiller.
    bloc = src.split("if not await niv.poser_niveau(guild, member, 2, cfg_act):")[1][:400]
    assert "continue" in bloc
    assert bloc.index("continue") < (bloc.index("retirer_tous_les_roles")
                                     if "retirer_tous_les_roles" in bloc else 10**6)


# ═══════════════════════════════════════════════════════════════════════════════
#  3. La semaine ne se brûle que si l'envoi a abouti
# ═══════════════════════════════════════════════════════════════════════════════

def _corps_envoyer_rappels() -> str:
    """Le corps de `envoyer_rappels`, isolé par l'AST."""
    for n in ast.walk(ast.parse(SRC_PASS)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "envoyer_rappels":
            return ast.unparse(n)
    raise AssertionError("envoyer_rappels introuvable dans activite_passage.py")


def test_la_semaine_nest_marquee_que_si_lenvoi_a_abouti():
    """⚠️ Marquer la semaine après un envoi raté la fait passer pour faite : le
    rappel ne part jamais, et ça se répète chaque semaine.

    ⚠️ LA GARANTIE S'EST RENFORCÉE LE 20/08. La première version ne mettait
    `abouti = False` que si `remplacer` LEVAIT. Or elle avalait ses exceptions
    et rendait un simple entier : un envoi refusé à 100 % (salon interdit)
    passait donc pour un succès. Elle rend désormais ses échecs, et `abouti`
    les lit."""
    #  ⚠️ PAR L'AST, PAS PAR DÉCOUPE DE CHAÎNE. La première version prenait
    #  1200 caractères après le `abouti = False` : les commentaires du bloc les
    #  mangeaient et le test échouait pour une raison qui n'était pas la sienne.
    bloc = _corps_envoyer_rappels()
    assert "abouti = not _res['echecs']" in bloc.replace('"', "'"), (
        "un envoi refusé doit compter comme un échec, pas seulement une exception")
    i_garde = bloc.index("if abouti and")
    i_ecrit = bloc.index("derniere_semaine=semaine_courante")
    assert i_garde < i_ecrit, (
        "l'écriture du marqueur doit être SOUS la garde `abouti`")


def test_zero_message_envoye_reste_un_succes():
    """« Personne n'est absent » n'est pas un échec : `remplacer` rend une
    liste vide SANS échec, et on marque la semaine — sinon on retenterait à
    chaque passage de la journée."""
    apres = _corps_envoyer_rappels().split("msgs.remplacer")[1][:400]
    assert "abouti = not _res['echecs']" in apres.replace('"', "'")
    assert "if envoyes" not in apres, (
        "le nombre d'envois ne doit pas décider du succès")


def test_un_renvoi_manuel_ne_consomme_pas_le_rappel_du_dimanche():
    """⚠️ Sinon cliquer « renvoyer » un mercredi ferait sauter le rappel
    automatique de la semaine."""
    bloc = _corps_envoyer_rappels().replace('"', "'")
    assert "maintenant.weekday() == conf['jour_rappel']" in bloc


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Le bilan par passage — sans lui, la question du propriétaire est sans réponse
# ═══════════════════════════════════════════════════════════════════════════════

def _fonction(nom: str):
    for n in ast.parse(SRC_BOT).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable")


BOUCLE = ast.unparse(_fonction("activite_passage_task"))


def test_la_boucle_dit_pourquoi_elle_ne_fait_rien():
    """⚠️ « éteint », « allumé et parfait » et « allumé mais inerte » donnaient
    exactement les mêmes logs : aucun. C'est pour ça que le propriétaire a dû
    demander si le système marchait."""
    assert "interrupteur éteint" in BOUCLE
    assert "AUCUNE cible" in BOUCLE


def test_la_boucle_publie_un_bilan_par_serveur():
    for champ in ("suivis=", "actifs=", "rappel=", "retrait=", "observation="):
        assert champ in BOUCLE, f"le bilan doit porter « {champ} »"


def test_le_compteur_de_depouillements_refuses_est_enfin_lu():
    """`sans_etiquette` était écrit et lu NULLE PART : le résumé annonçait
    « N à dépouiller » puis « 0 dépouillé(s) » sans jamais dire pourquoi."""
    assert "sans_etiquette" in BOUCLE
    assert "REFUSÉ" in BOUCLE


def test_le_suivi_muet_est_signale():
    """Sinon « personne n'est absent » et « les sondes ne captent rien » se
    ressemblent — et la seconde est une panne."""
    assert "suivi_muet" in BOUCLE
