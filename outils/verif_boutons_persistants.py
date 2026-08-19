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

#  Les constructeurs de vue dont `timeout=None` déclare une intention de
#  persistance. `LayoutView` est le patron des Components V2 : les fiches de la
#  veille Roblox en sont, et leurs boutons vivent dans un `ActionRow` glissé
#  dans un conteneur — jamais en `v.add_item(Button(...))` direct.
VUES = ("View", "LayoutView")


def _emissions_persistantes(arbre, classes: dict) -> list:
    """(custom_id|None, ligne, contexte) pour chaque composant cliquable d'une
    vue dont l'auteur a déclaré `timeout=None`.

    ⚠️ DEUX FORMES, ET IL FAUT LES DEUX.
      · classique  : `v = View(timeout=None)` puis `v.add_item(Button(...))` ;
      · V2         : `v = LayoutView(timeout=None)` puis
                     `v.add_item(container(*items))`, où `items` contient un
                     `ActionRow(*boutons)`. Les boutons ne passent JAMAIS par
                     `v.add_item` — les chercher là ne trouverait rien.
    Pour la seconde, on considère que TOUT `custom_id` littéral construit dans
    une fonction qui fabrique une vue persistante finira sur cette vue. C'est
    volontairement large : rater un bouton persistant coûte « n'a pas répondu
    à temps » en public, en signaler un de trop coûte une ligne à lire.
    """
    out = []

    def scanner_portee(noeud, nom_portee: str):
        persistantes = set()      # variables tenant une vue persistante
        callback_lie = set()      # variables recevant `.callback = …`
        calls_nommes = {}         # id(Call) → nom de la variable assignée

        for n in ast.walk(noeud):
            if not isinstance(n, ast.Assign):
                continue
            #  `btn.callback = …` → ce bouton porte son propre gestionnaire.
            for t in n.targets:
                if (isinstance(t, ast.Attribute) and t.attr == "callback"
                        and isinstance(t.value, ast.Name)):
                    callback_lie.add(t.value.id)
            if not isinstance(n.value, ast.Call):
                continue
            for t in n.targets:
                if isinstance(t, ast.Name):
                    calls_nommes[id(n.value)] = t.id
            f = n.value.func
            nom = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if nom not in VUES:
                continue
            to = _kw(n.value, "timeout")
            if isinstance(to, ast.Constant) and to.value is None:
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        persistantes.add(t.id)
        if not persistantes:
            return

        def retenir(appel):
            cid = _kw(appel, "custom_id")
            if cid is None:
                return  # bouton lien (url=) → aucun dispatch, sain
            #  ⚠️ EXEMPTION — LE CALLBACK ATTACHÉ EN DIRECT.
            #  `btn = Button(custom_id=…)` puis `btn.callback = …` : le bouton
            #  porte son gestionnaire, la vue n'a rien à faire enregistrer au
            #  boot. C'est le patron des panneaux ÉPHÉMÈRES (réponse de slash
            #  command), et il est légitime. Sans cette exemption l'outil criait
            #  sur les cinq boutons de `/infractions`, tous corrects et
            #  documentés comme tels.
            if calls_nommes.get(id(appel)) in callback_lie:
                return
            out.append((_litteral(cid), appel.lineno, nom_portee))

        vus = set()
        #  Forme classique : `X.add_item(Button(custom_id=…))`.
        for n in ast.walk(noeud):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "add_item"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id in persistantes):
                for a in n.args:
                    if isinstance(a, ast.Call):
                        vus.add(id(a))
                        retenir(a)
        #  Forme V2 : tout `custom_id=` construit dans cette fonction.
        for n in ast.walk(noeud):
            if isinstance(n, ast.Call) and id(n) not in vus:
                retenir(n)

    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            #  Une méthode de classe enregistrée est déjà couverte par sa classe.
            scanner_portee(n, n.name)
    return out


def main() -> int:
    #  ⚠️ PLUSIEURS FICHIERS, ET C'EST NÉCESSAIRE. Un bouton peut être POSÉ dans
    #  un module (les fiches de la veille vivent dans `roblox_panneau.py`) et
    #  ENREGISTRÉ dans un autre (`bot.py`). Juger un fichier seul déclarerait
    #  orphelin tout ce qui est capté ailleurs — un faux positif garanti.
    fichiers = sys.argv[1:] or ["bot.py"]
    sources, arbres = {}, {}
    for f in fichiers:
        sources[f] = open(f, encoding="utf-8").read()
        arbres[f] = ast.parse(sources[f])

    #  Les capteurs sont mis EN COMMUN sur tous les fichiers donnés.
    captes, gabarits = set(), []
    for f, arbre in arbres.items():
        classes = _classes(arbre)
        vues, dynamiques = _enregistrees(arbre)
        for nom in vues:
            cls = classes.get(nom)
            if cls is not None:
                captes |= _custom_ids_de_classe(cls)
        for nom in dynamiques:
            cls = classes.get(nom)
            if cls is not None:
                gabarits += _gabarits_dynamiques(cls)
        arbres[f] = (arbre, classes)

    orphelins, incalculables = [], []
    for f, (arbre, classes) in arbres.items():
        for cid, ligne, portee in _emissions_persistantes(arbre, classes):
            if cid is None:
                incalculables.append((f, ligne, portee))
                continue
            if cid in captes or any(g.fullmatch(cid) or g.match(cid) for g in gabarits):
                continue
            orphelins.append((cid, f, ligne, portee))

    print(f"  {' · '.join(fichiers)}")
    print(f"    custom_id captés par une vue   : {len(captes)}")
    print(f"    gabarits dynamiques            : {len(gabarits)}")
    if incalculables:
        print(f"    custom_id calculés (non jugés) : {len(incalculables)}")

    if not orphelins:
        print("    ✅ aucun bouton persistant orphelin.")
        return 0

    print(f"\n  ❌ {len(orphelins)} bouton(s) PERSISTANT(S) SANS CAPTEUR — "
          f"ils s'afficheront et ne répondront pas :\n")
    for cid, f, ligne, portee in sorted(orphelins, key=lambda x: (x[1], x[2])):
        print(f"    custom_id « {cid} »  —  {f}:{ligne} dans {portee}()")
        print(f"        {sources[f].splitlines()[ligne - 1].strip()[:88]}")
    print("\n  → soit une classe de vue réenregistrée par bot.add_view(...) au boot,")
    print("    soit un DynamicItem passé à bot.add_dynamic_items(...).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
