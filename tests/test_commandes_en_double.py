"""Les commandes sortaient EN DOUBLE dans le sélecteur Discord.

═══════════════════════════════════════════════════════════════════════════════
CE QUE LA CAPTURE DU 06/09/2026 MONTRE
═══════════════════════════════════════════════════════════════════════════════
    /off list   ·  /off list
    /off off    ·  /off off
    /off on     ·  /off on
    /bouclier off · /bouclier off

Chaque commande de l'arbre, deux fois.

LA CAUSE. Le démarrage faisait les DEUX enregistrements :

    await bot.tree.sync()                    → registre GLOBAL
    bot.tree.copy_global_to(guild=g)
    await bot.tree.sync(guild=g)             → registre de GUILDE

⚠️ ET LE COMMENTAIRE POSÉ À CET ENDROIT AFFIRMAIT LE CONTRAIRE : « Discord fait
primer la copie de guilde sur la globale du même nom : aucun doublon à
l'affichage ». C'est faux. Les commandes globales et les commandes de guilde
sont deux registres DISTINCTS, et le client affiche les deux. Une affirmation
confortable écrite dans un commentaire a tenu lieu de vérification pendant
trois semaines.

LA CORRECTION garde la propagation instantanée (par guilde, ajoutée le 16/08
parce que le global met jusqu'à une heure) et supprime le registre global chez
Discord.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _fonction(nom: str) -> str:
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _noeud(nom: str):
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans bot.py")


# ═══════════════════════════════════════════════════════════════════════════════
#  L'INVARIANT : plus aucun sync global, sauf celui qui PURGE
# ═══════════════════════════════════════════════════════════════════════════════

def _syncs_globaux() -> list:
    """Les `await bot.tree.sync()` SANS argument `guild=`, avec leur fonction.

    On lit l'arbre syntaxique : un `tree.sync()` cité dans un commentaire ou
    une docstring ne doit pas compter — et il y en a plusieurs maintenant.
    """
    out = []
    for f in ast.walk(ARBRE):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(f):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "sync"
                    and isinstance(n.func.value, ast.Attribute)
                    and n.func.value.attr == "tree"
                    and not n.args
                    and not any(k.arg == "guild" for k in n.keywords)):
                out.append(f.name)
    return out


def test_le_SEUL_sync_global_restant_est_celui_qui_purge():
    """⚠️ L'INVARIANT DE TOUT LE CORRECTIF. Un `tree.sync()` global recrée le
    registre qu'on vient de vider — et les doublons reviennent, sans que
    personne ne fasse le lien avec l'appel fautif."""
    fautifs = [f for f in _syncs_globaux() if f != "_purger_commandes_globales"]
    assert not fautifs, (
        f"sync global hors purge dans : {sorted(set(fautifs))} — les doublons "
        f"reviendront")
    assert "_purger_commandes_globales" in _syncs_globaux(), (
        "la purge ne pousse plus l'ensemble vide : le registre global ne sera "
        "jamais supprimé")


def test_owner_sync_ne_recree_pas_les_doublons():
    """Le bouton le plus tentant à cliquer quand on voit des doublons est
    justement celui qui les recréait."""
    corps = _fonction("sync_cmd")
    assert "copy_global_to(guild=i.guild)" in corps
    assert "sync(guild=i.guild)" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  L'ORDRE : poser d'abord, purger ensuite — jamais l'inverse
# ═══════════════════════════════════════════════════════════════════════════════

def test_on_pose_les_commandes_de_guilde_AVANT_de_purger():
    """⚠️ PURGER D'ABORD LAISSERAIT LE SERVEUR SANS AUCUNE COMMANDE — un bot
    muet à cause d'un correctif d'affichage."""
    corps = _fonction("on_ready")
    i_guilde = corps.index("sync(guild=_g)")
    i_purge = corps.index("_purger_commandes_globales()")
    assert i_guilde < i_purge, (
        "la purge passe avant la pose : le serveur perdrait ses commandes")


def test_on_ne_purge_JAMAIS_si_aucune_guilde_na_recu_les_commandes():
    """Mieux vaut un doublon qu'un bot muet."""
    corps = _fonction("on_ready")
    assert "if _doit_purger and _ok > 0:" in corps, (
        "la purge n'est pas conditionnée à une pose réussie")
    assert "aucune guilde n'a reçu les" in corps, (
        "le cas n'est pas dit dans les journaux : on chercherait à l'aveugle")


def test_le_saut_par_hash_ne_bloque_PAS_le_menage():
    """⚠️ SANS CETTE EXCEPTION, LE MÉNAGE N'AURAIT JAMAIS LIEU. L'arbre n'a pas
    changé, donc le hash non plus, donc on sauterait le bloc — et les doublons
    resteraient pour toujours, correctif déployé ou pas."""
    corps = _fonction("on_ready")
    #  `ast.unparse` parenthese les operandes : `and (not _doit_purger)`.
    assert "and (not _doit_purger)" in corps, (
        "le saut par hash ignore la présence de commandes globales")


def test_la_purge_est_idempotente():
    """On lit d'abord ce que Discord a vraiment ; une fois le ménage fait, les
    démarrages suivants ne repurgent rien et ne brûlent pas de quota."""
    corps = _fonction("on_ready")
    assert "fetch_commands()" in corps
    assert "_doit_purger = bool(_globales)" in corps


# ═══════════════════════════════════════════════════════════════════════════════
#  LE DANGER RÉEL : la purge vide l'arbre — elle DOIT le remettre
# ═══════════════════════════════════════════════════════════════════════════════

class _FauxArbre:
    """Reproduit ce dont la purge se sert, et RIEN de plus — piège n°6 : un
    faux doit porter tout ce que porte le vrai sur le chemin testé."""

    def __init__(self, commandes):
        self._cmds = list(commandes)
        self.syncs = []

    def get_commands(self, *, guild=None):
        return list(self._cmds)

    def clear_commands(self, *, guild=None):
        self._cmds = []

    def add_command(self, cmd, *, guild=None, override=False):
        self._cmds.append(cmd)

    async def sync(self, *, guild=None):
        self.syncs.append(guild)
        return list(self._cmds)


class _FauxArbreQuiCasse(_FauxArbre):
    async def sync(self, *, guild=None):
        raise RuntimeError("Discord indisponible")


class _FauxBot:
    def __init__(self, arbre):
        self.tree = arbre


def _purge(arbre):
    """Exécute la VRAIE fonction du dépôt sur un arbre factice."""
    ns = {"bot": _FauxBot(arbre), "print": lambda *a, **k: None}
    exec(_fonction("_purger_commandes_globales"), ns)   # noqa: S102 — code du dépôt
    return asyncio.run(ns["_purger_commandes_globales"]())


def test_la_purge_pousse_bien_un_ensemble_VIDE():
    """C'est la seule façon de dire à Discord « plus aucune commande
    globale »."""
    a = _FauxArbre(["off", "bouclier", "mod"])
    vus = {}
    _sync = a.sync

    async def _espion(*, guild=None):
        vus["taille"] = len(a.get_commands())
        return await _sync(guild=guild)

    a.sync = _espion
    assert _purge(a) is True
    assert vus["taille"] == 0, (
        "l'arbre n'était pas vide au moment du sync : Discord garderait les "
        "commandes globales, donc les doublons")


def test_la_purge_REMET_l_arbre_apres_coup():
    """⚠️ LE DÉGÂT QU'ON ÉVITE, ET IL EST GRAVE. Si l'arbre restait vide, le
    prochain `copy_global_to(guild=…)` — celui d'`on_guild_join`, par exemple —
    copierait le VIDE et EFFACERAIT les commandes de ce serveur."""
    a = _FauxArbre(["off", "bouclier", "mod"])
    _purge(a)
    assert a.get_commands() == ["off", "bouclier", "mod"], (
        "l'arbre local est resté vide : le prochain sync de guilde effacerait "
        "les commandes de ce serveur")


def test_l_arbre_revient_MEME_SI_le_sync_echoue():
    """Une panne réseau pendant la purge ne doit pas laisser le bot avec un
    arbre vide jusqu'au redémarrage — c'est le pire des deux mondes."""
    a = _FauxArbreQuiCasse(["off", "bouclier"])
    assert _purge(a) is False, "une purge ratée doit se dire, pas se taire"
    assert a.get_commands() == ["off", "bouclier"], (
        "l'arbre n'a pas été restauré après l'échec : `finally` manquant")


def test_la_restauration_est_dans_un_finally():
    """La contre-épreuve statique : c'est la structure qui garantit le retour,
    pas la chance."""
    n = _noeud("_purger_commandes_globales")
    essais = [x for x in ast.walk(n) if isinstance(x, ast.Try)]
    assert essais, "aucun try/finally dans la purge"
    assert any("add_command" in ast.unparse(ast.Module(body=e.finalbody,
                                                       type_ignores=[]))
               for e in essais), (
        "la restauration de l'arbre n'est pas dans un `finally` : une "
        "exception la sauterait")


# ═══════════════════════════════════════════════════════════════════════════════
#  La régression que la purge introduirait sans ce raccord
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_nouveau_serveur_recoit_ses_commandes():
    """⚠️ SANS REGISTRE GLOBAL, une commande n'existe que là où on l'a posée.
    Un serveur qui invite le bot n'aurait AUCUNE commande jusqu'au prochain
    redémarrage — et « le bot ne répond à rien » ne ressemble pas à sa cause."""
    corps = _fonction("on_guild_join")
    assert "copy_global_to(guild=guild)" in corps
    assert "sync(guild=guild)" in corps
    assert "except Exception" in corps, (
        "une erreur de sync empêcherait l'arrivée sur le serveur")
