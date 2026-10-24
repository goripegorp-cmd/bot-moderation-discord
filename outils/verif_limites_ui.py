# -*- coding: utf-8 -*-
"""outils/verif_limites_ui.py — contrôle statique des limites Discord dans tout le bot : un texte littéral trop long dans un bouton, un menu,
un formulaire ou un titre fait échouer l'envoi (400) — l'interface ne s'affiche pas, souvent sans bruit.
Les f-strings sont mesurées par leurs parties fixes (une borne basse) ; un découpage [:N] protège."""
import ast
import io
import os
import sys

RAC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# (nom de l'appel, argument) → limite
LIMITES = {
    ("Button", "label"): 80, ("SelectOption", "label"): 100, ("SelectOption", "description"): 100,
    ("SelectOption", "value"): 100, ("Select", "placeholder"): 150, ("RoleSelect", "placeholder"): 150,
    ("ChannelSelect", "placeholder"): 150, ("UserSelect", "placeholder"): 150,
    ("MentionableSelect", "placeholder"): 150, ("TextInput", "label"): 45, ("TextInput", "placeholder"): 100,
    ("Label", "text"): 45, ("Label", "description"): 100, ("Modal", "title"): 45,
    ("Button", "custom_id"): 100, ("Select", "custom_id"): 100,
}


def longueur(n):
    """Longueur minimale connue d'une expression texte ; None si inconnue ou protégée par un découpage."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return len(n.value)
    if isinstance(n, ast.JoinedStr):
        return sum(len(v.value) for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        a, b = longueur(n.left), longueur(n.right)
        return (a or 0) + (b or 0) if (a is not None or b is not None) else None
    return None  # variable, appel, découpage [:N]…


def nom_appel(f):
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


fautes = []
for racine, _d, fichiers in os.walk(RAC):
    if any(x in racine for x in ("worktrees", "__pycache__", ".git", os.sep + "tests")):
        continue
    for f in fichiers:
        if not f.endswith(".py"):
            continue
        chemin = os.path.join(racine, f)
        try:
            arbre = ast.parse(io.open(chemin, encoding="utf-8").read())
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            if isinstance(n, ast.Call):
                nom = nom_appel(n.func)
                # super().__init__(title=...) dans une classe Modal : vérifié à part ci-dessous
                for kw in n.keywords:
                    lim = LIMITES.get((nom, kw.arg))
                    if lim is None:
                        continue
                    L = longueur(kw.value)
                    if L is not None and L > lim:
                        fautes.append((os.path.relpath(chemin, RAC), n.lineno, nom, kw.arg, L, lim))
            if isinstance(n, ast.ClassDef) and any("Modal" in ast.unparse(b) for b in n.bases):
                for kw in n.keywords:          # class X(discord.ui.Modal, title="…")
                    if kw.arg == "title":
                        L = longueur(kw.value)
                        if L is not None and L > 45:
                            fautes.append((os.path.relpath(chemin, RAC), n.lineno, n.name, "title", L, 45))
                for m in ast.walk(n):          # super().__init__(title="…")
                    if isinstance(m, ast.Call) and nom_appel(m.func) == "__init__":
                        for kw in m.keywords:
                            if kw.arg == "title":
                                L = longueur(kw.value)
                                if L is not None and L > 45:
                                    fautes.append((os.path.relpath(chemin, RAC), m.lineno, n.name, "title", L, 45))
print(f"{len(fautes)} dépassement(s)")
for x in sorted(set(fautes)):
    print(" ", x)

sys.exit(1 if fautes else 0)
