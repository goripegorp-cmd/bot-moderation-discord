"""Audit static AST de bot.py pour trouver les bugs de navigation V2/V1
et les listes truncatees.

Cherche :
1. Classes LayoutView et leurs callbacks (_cb_*, async def)
2. Appels qui mixent V2 (render_to) et V1 (.embed())
3. Hardcoded [:25], [:24] sur listes de membres/roles/channels
4. Selectors sans pagination si > 25 elements possibles
5. References a des classes inexistantes
"""
import ast
import re
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

src_path = Path("bot.py")
src = src_path.read_text(encoding="utf-8")
tree = ast.parse(src)

# Index : class -> {bases, methods, line}
classes = {}
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        bases = []
        for b in node.bases:
            if isinstance(b, ast.Name):
                bases.append(b.id)
            elif isinstance(b, ast.Attribute):
                bases.append(b.attr)
        methods = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[item.name] = item.lineno
        classes[node.name] = {"bases": bases, "methods": methods, "line": node.lineno, "node": node}


# === Heuristique V2 vs V1 ===
def is_v2_panel(name):
    """V2 si herite de LayoutView ou nom finit en V2."""
    if name not in classes:
        return False
    cls = classes[name]
    if "LayoutView" in cls["bases"]:
        return True
    if name.endswith("V2"):
        return True
    return False


def is_v1_panel(name):
    if name not in classes:
        return None
    cls = classes[name]
    if "View" in cls["bases"] and not is_v2_panel(name):
        return True
    return False


# Liste des panels V2 et V1
v2_panels = [n for n in classes if is_v2_panel(n)]
v1_panels = [n for n in classes if is_v1_panel(n)]

print(f"=== Inventaire des panels ===")
print(f"V2 (LayoutView): {len(v2_panels)}")
print(f"V1 (View)      : {len(v1_panels)}")


# === Recherche des appels de classes V1 dans des panels V2 ===
print(f"\n=== V1 panels referenced from V2 panels (BUG potentiel) ===")
issues_v1_in_v2 = []
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_node = cls["node"]
    cls_src = ast.get_source_segment(src, cls_node) or ""
    for v1_name in v1_panels:
        # Ne signaler que les pattern X(...) ou X.qqchose(
        # Eviter faux positifs sur substrings (ex: AdsPanel match dans AdsPanelV2)
        # On cherche le mot exact suivi de '('
        pattern = r"\b" + re.escape(v1_name) + r"\("
        for m in re.finditer(pattern, cls_src):
            # Calcul du numero de ligne dans le fichier
            line_in_class = cls_src[:m.start()].count("\n")
            line_no = cls["line"] + line_in_class
            issues_v1_in_v2.append((v2_name, v1_name, line_no))

# Filtre les self/_get_return fonctions hors-classe
shown = 0
for v2_name, v1_name, line_no in issues_v1_in_v2[:30]:
    print(f"  L{line_no}: {v2_name} -> {v1_name}(...)")
    shown += 1
if shown == 0:
    print("  Aucun.")
elif len(issues_v1_in_v2) > 30:
    print(f"  ... et {len(issues_v1_in_v2) - 30} autres")


# === Recherche des appels .embed() dans panels V2 ===
print(f"\n=== Appels '.embed()' dans panels V2 (V1 pattern dans V2 - BUG) ===")
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    # Pattern: await xxx.embed() ou v.embed() suivi de view= dans edit_message
    for m in re.finditer(r"\.embed\(\)", cls_src):
        line_in_class = cls_src[:m.start()].count("\n")
        line_no = cls["line"] + line_in_class
        # Snippet
        snippet_start = max(0, m.start() - 60)
        snippet_end = min(len(cls_src), m.end() + 30)
        snippet = cls_src[snippet_start:snippet_end].replace("\n", " ")[:100]
        print(f"  L{line_no} {v2_name}: ...{snippet}...")


# === Recherche des hardcoded [:25] ou [:24] sur listes ===
print(f"\n=== Hardcoded [:25] ou [:24] (limites Discord) ===")
patterns = [r"\[\:25\]", r"\[\:24\]", r"\[0\:25\]", r"\[0\:24\]"]
for pat in patterns:
    for m in re.finditer(pat, src):
        line = src[:m.start()].count("\n") + 1
        # Get the surrounding context
        line_start = src.rfind("\n", 0, m.start()) + 1
        line_end = src.find("\n", m.end())
        line_src = src[line_start:line_end].strip()
        # Filtre si c'est explicite intentionnel (limit, max)
        if any(k in line_src.lower() for k in ["limit", "max", "page"]):
            continue
        print(f"  L{line}: {line_src[:120]}")


# === Recherche des selectors non-paginated sur >25 ===
# (heuristique : Select(...placeholder=...) avec opts qui peuvent etre > 25)
print(f"\n=== Select sans pagination ===")
# pattern Select(...) tout court (pas Paginated, pas RoleSelect, etc.)
sel_pattern = re.compile(r"\bSelect\s*\(")
sel_pat = re.compile(r"\bSelect\s*\(\s*placeholder", re.MULTILINE)
count_select = 0
for m in sel_pat.finditer(src):
    count_select += 1
print(f"  Total Select() trouves: {count_select} (note: c'est OK si feeds limited a 25)")


# === Buttons et leurs callbacks ===
print(f"\n=== Boutons V2 et leurs callbacks ===")
button_callback_pattern = re.compile(r"(\w+)\.callback\s*=\s*self\.(\w+)")
callback_count = 0
broken_callbacks = []
for m in button_callback_pattern.finditer(src):
    btn_var, cb_method = m.groups()
    callback_count += 1
print(f"  Total Button.callback = self._cb_xxx attaches: {callback_count}")
