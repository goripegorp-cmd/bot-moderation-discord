"""Trouve les boutons qui MENTENT : persistants à l'écran, morts au clic.

⚠️ LA FAMILLE DE PANNES QUE CET OUTIL FERME
Un bouton Discord posé sur un message durable ne « contient » pas son code : au
redémarrage, la bibliothèque ne sait le rattacher que si sa classe a été
réenregistrée au boot, par `bot.add_view(...)` (custom_id fixe) ou
`bot.add_dynamic_items(...)` (custom_id à gabarit). Sinon le bouton reste
affiché, cliquable, et ne répond JAMAIS : Discord attend trois secondes puis
affiche « n'a pas répondu à temps ». En public, sous les yeux des membres.

Ça n'a rien d'hypothétique — c'est arrivé deux fois dans ce dépôt :
  · 16/08 : les onglets de /configure sans `defer` → « L'interaction a échoué ».
  · 19/08 : le bouton « 🌍 Ma langue / My language » de la carte d'accueil.
    La purge d'animation avait remplacé `bot.add_view(OnboardingView())` par
    `pass  # bloc vidé (module détaché)` et emporté la classe. Le bouton, lui,
    était reposé sur CHAQUE nouvelle carte d'accueil. Constaté par le
    propriétaire, capture à l'appui, après un nombre inconnu de nouveaux
    membres tombés dessus.

Aucun test ne pouvait le voir : le bouton est bien construit, la carte bien
envoyée, `import bot` passe, les 385 tests passent. Le défaut ne vit que dans
le RACCORD entre un custom_id émis et un enregistrement au boot — donc ici.

LA RÈGLE VÉRIFIÉE, ET POURQUOI ELLE EST SÛRE
`timeout=None` sur une View est une DÉCLARATION D'INTENTION de persistance :
l'auteur dit que ce bouton doit survivre aux redémarrages. On exige alors que
son custom_id soit capté par quelque chose de réenregistré au boot. Une vue à
timeout fini (`View(timeout=180)`) reste vivante en mémoire le temps de son
usage : elle n'a rien à enregistrer, on ne la regarde pas.

Sont acceptés comme capteurs :
  · une classe passée à `bot.add_view(...)` — on lit les custom_id littéraux
    déclarés dans son corps (décorateurs `@discord.ui.button/select`, et
    `custom_id=` des items qu'elle construit) ;
  · un `DynamicItem` passé à `bot.add_dynamic_items(...)` — on compile son
    `template=` et on teste le custom_id contre.

⚠️ CONSERVATEUR EXPRÈS. On ne juge que les custom_id LITTÉRAUX : un custom_id
calculé (f-string, concaténation) est signalé « non vérifiable » et compté à
part, jamais en échec — mieux vaut un outil qu'on croit qu'un outil qui crie.

Usage :
    PYTHONIOENCODING=utf-8 python outils/verif_boutons_persistants.py bot.py
Sortie : code 1 s'il existe au moins un bouton persistant orphelin.
"""
from __future__ import annotations

import ast
import re
import sys


# ═══════════════════════════════════════════════════════════════════════════════
#  Lecture de l'arbre
# ═══════════════════════════════════════════════════════════════════════════════

def _litteral(n):
    """La valeur si c'est une chaîne littérale, sinon None (= non vérifiable)."""
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


def _kw(appel: ast.Call, nom: str):
    for k in appel.keywords:
        if k.arg == nom:
            return k.value
    return None


def _classes(arbre) -> dict:
    return {n.name: n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)}


def _enregistrees(arbre) -> tuple[set, set]:
    """(classes passées à add_view, classes passées à add_dynamic_items)."""
    vues, dynamiques = set(), set()
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        cible = vues if n.func.attr == "add_view" else (
            dynamiques if n.func.attr == "add_dynamic_items" else None)
        if cible is None:
            continue
        for a in n.args:
            #  add_view(MaVue())  →  Call dont func est un Name
            if isinstance(a, ast.Call) and isinstance(a.func, ast.Name):
                cible.add(a.func.id)
            #  add_dynamic_items(MonBouton)  →  Name nu
            elif isinstance(a, ast.Name):
                cible.add(a.id)
    return vues, dynamiques


def _custom_ids_de_classe(cls: ast.ClassDef) -> set:
    """Les custom_id littéraux qu'une classe de vue déclare (décorateurs inclus)."""
    out = set()
    for n in ast.walk(cls):
        if isinstance(n, ast.Call):
            cid = _kw(n, "custom_id")
            if cid is not None and _litteral(cid):
                out.add(_litteral(cid))
    return out


def _gabarits_dynamiques(cls: ast.ClassDef) -> list:
    """Le `template=` d'un DynamicItem, compilé. Déclaré dans les mots-clés de
    classe : `class X(DynamicItem[Button], template=r"…")`."""
    out = []
    for k in getattr(cls, "keywords", []):
        if k.arg == "template" and _litteral(k.value):
            try:
                out.append(re.compile(_litteral(k.value)))
            except re.error:
                pass
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Les émissions : custom_id posés sur une View(timeout=None)
# ═══════════════════════════════════════════════════════════════════════════════

def _emissions_persistantes(arbre, classes: dict) -> list:
    """(custom_id|None, ligne, contexte) pour chaque item ajouté à une vue dont
    l'auteur a déclaré `timeout=None`."""
    out = []

    def scanner_portee(noeud, nom_portee: str):
        #  Les variables de cette portée qui tiennent une View(timeout=None).
        persistantes = set()
        for n in ast.walk(noeud):
            if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
                continue
            f = n.value.func
            appel_vue = (isinstance(f, ast.Attribute) and f.attr == "View") or (
                isinstance(f, ast.Name) and f.id == "View")
            if not appel_vue:
                continue
            to = _kw(n.value, "timeout")
            if isinstance(to, ast.Constant) and to.value is None:
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        persistantes.add(t.id)
        if not persistantes:
            return
        #  Les `X.add_item(...)` sur ces variables.
        for n in ast.walk(noeud):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "add_item"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id in persistantes):
                for a in n.args:
                    if isinstance(a, ast.Call):
                        cid = _kw(a, "custom_id")
                        if cid is None:
                            continue  # bouton lien (url=) → pas de dispatch, sain
                        out.append((_litteral(cid), a.lineno, nom_portee))

    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            #  Une méthode de classe enregistrée est déjà couverte par sa classe.
            scanner_portee(n, n.name)
    return out


def main() -> int:
    fichier = sys.argv[1] if len(sys.argv) > 1 else "bot.py"
    src = open(fichier, encoding="utf-8").read()
    arbre = ast.parse(src)

    classes = _classes(arbre)
    vues, dynamiques = _enregistrees(arbre)

    captes = set()
    for nom in vues:
        cls = classes.get(nom)
        if cls is not None:
            captes |= _custom_ids_de_classe(cls)
    gabarits = []
    for nom in dynamiques:
        cls = classes.get(nom)
        if cls is not None:
            gabarits += _gabarits_dynamiques(cls)

    orphelins, incalculables = [], []
    for cid, ligne, portee in _emissions_persistantes(arbre, classes):
        if cid is None:
            incalculables.append((ligne, portee))
            continue
        if cid in captes or any(g.fullmatch(cid) or g.match(cid) for g in gabarits):
            continue
        orphelins.append((cid, ligne, portee))

    print(f"  {fichier}")
    print(f"    vues réenregistrées au boot   : {len(vues)}")
    print(f"    gabarits dynamiques           : {len(gabarits)}")
    print(f"    custom_id captés              : {len(captes)}")
    if incalculables:
        print(f"    custom_id calculés (non jugés): {len(incalculables)}")

    if not orphelins:
        print("    ✅ aucun bouton persistant orphelin.")
        return 0

    print(f"\n  ❌ {len(orphelins)} bouton(s) PERSISTANT(S) SANS CAPTEUR — "
          f"ils s'afficheront et ne répondront pas :\n")
    lignes = src.splitlines()
    for cid, ligne, portee in sorted(orphelins, key=lambda x: x[1]):
        print(f"    custom_id « {cid} »  —  l.{ligne} dans {portee}()")
        print(f"        {lignes[ligne - 1].strip()[:88]}")
    print("\n  → soit une classe de vue réenregistrée par bot.add_view(...) au boot,")
    print("    soit un DynamicItem passé à bot.add_dynamic_items(...).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
