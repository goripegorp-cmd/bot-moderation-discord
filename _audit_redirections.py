"""
Audit complet des redirections / navigation V2.

Cherche :
1. V2 panels appelant V1 panels (Panel/View) avec edit_message + .embed()
   sans attachments=[]
2. V2 panels appelant V1 panels avec render_to manquant
3. Modal.on_submit dans contexte V2 qui font edit_message avec embed sans
   attachments=[]
4. Callbacks de boutons sans try/except (echecs silencieux)
5. V2 panels qui n'ont pas de methode render_to (bug fondamental)
6. Boutons custom_id stale (peuvent crasher au reload du bot)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import ast
import re
from pathlib import Path

src = Path("bot.py").read_text(encoding="utf-8")
tree = ast.parse(src)

# Index des classes
classes = {}
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        bases = [
            b.id if isinstance(b, ast.Name)
            else (b.attr if isinstance(b, ast.Attribute) else "?")
            for b in node.bases
        ]
        methods = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[item.name] = item.lineno
        classes[node.name] = {"bases": bases, "methods": methods, "line": node.lineno, "node": node}


def is_v2(name):
    if name not in classes:
        return False
    return ("LayoutView" in classes[name]["bases"]) or name.endswith("V2")


def is_v1(name):
    if name not in classes:
        return False
    return ("View" in classes[name]["bases"]) and not is_v2(name)


v2_panels = [n for n in classes if is_v2(n)]
v1_views = [n for n in classes if is_v1(n)]

print(f"V2 LayoutView: {len(v2_panels)}")
print(f"V1 View      : {len(v1_views)}")
print()


# ============================================================================
# AUDIT 1 : V2 panels SANS render_to method
# ============================================================================
print("=" * 70)
print("AUDIT 1 : V2 panels SANS methode render_to")
print("=" * 70)
for name in v2_panels:
    methods = classes[name]["methods"]
    if "render_to" not in methods:
        print(f"  L{classes[name]['line']} {name} : pas de render_to !")
print()


# ============================================================================
# AUDIT 2 : edit_message avec embed= sans attachments=[]
# ============================================================================
print("=" * 70)
print("AUDIT 2 : edit_message(embed=..., view=v1) SANS attachments=[]")
print("(Probable cause 'Echec de l'interaction')")
print("=" * 70)
# Pattern : await ...edit_message( ... embed= ... view= ... )
issues = []
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    # Match edit_message blocks
    for m in re.finditer(
        r'await\s+\w+\.response\.edit_message\(\s*([^)]*?)\)', cls_src, re.DOTALL,
    ):
        args = m.group(1)
        if 'embed=' in args and 'view=' in args and 'attachments' not in args:
            line_in_class = cls_src[:m.start()].count('\n')
            line_no = cls["line"] + line_in_class
            # Get the line content
            line_content = src.splitlines()[line_no - 1].strip()
            issues.append((v2_name, line_no, line_content[:120]))

for cls_name, ln, content in issues[:30]:
    print(f"  L{ln} {cls_name}")
    print(f"       {content}")
if len(issues) > 30:
    print(f"   ... et {len(issues) - 30} autres")
print(f"   Total : {len(issues)}")
print()


# ============================================================================
# AUDIT 3 : Modal.on_submit dans V2 context qui appelle .embed()
# ============================================================================
print("=" * 70)
print("AUDIT 3 : Modal.on_submit avec .embed() (V1 pattern dans V2)")
print("=" * 70)
modal_pat = re.compile(r'^class (\w+)\(Modal', re.MULTILINE)
modal_issues = []
for m in modal_pat.finditer(src):
    mod_name = m.group(1)
    mod_line = src[:m.start()].count('\n') + 1
    # Find next class
    next_cls = re.search(r'^class \w+', src[m.end():], re.MULTILINE)
    cls_end = m.end() + (next_cls.start() if next_cls else 3000)
    cls_src = src[m.start():cls_end]
    if '.embed()' in cls_src:
        # Check if it's a V2 context (returns to V2 panel)
        # We look for v.render_to vs v.embed()
        if 'await v.embed()' in cls_src and 'render_to' not in cls_src:
            modal_issues.append((mod_name, mod_line))

for name, ln in modal_issues[:20]:
    print(f"  L{ln} {name}")
print(f"   Total : {len(modal_issues)}")
print()


# ============================================================================
# AUDIT 4 : Button callbacks sans try/except
# ============================================================================
print("=" * 70)
print("AUDIT 4 : Callbacks de boutons V2 sans try/except wrapper")
print("=" * 70)
# Pattern : async def _cb_X(self, i): puis pas de try: dans les 5 lignes
callback_pat = re.compile(
    r'async def (_cb_\w+|cb_\w+)\(self, i.*?\):\s*\n((?:.*\n){1,15})',
    re.MULTILINE,
)
cb_issues = []
for cls_name in v2_panels:
    cls = classes[cls_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    for m in callback_pat.finditer(cls_src):
        cb_name = m.group(1)
        body = m.group(2)
        # Skip if has try: in early body
        if 'try:' in body[:600]:
            continue
        # Skip if just calls await render_to (low risk)
        if body.strip().count('\n') < 3 and 'render_to' in body:
            continue
        line_in_class = cls_src[:m.start()].count('\n')
        line_no = cls["line"] + line_in_class
        cb_issues.append((cls_name, cb_name, line_no))

for cls_name, cb_name, ln in cb_issues[:25]:
    print(f"  L{ln} {cls_name}.{cb_name}")
print(f"   Total : {len(cb_issues)}")
print()


# ============================================================================
# AUDIT 5 : V1 views referenced from V2 panels (besoin de check render_to vs .embed)
# ============================================================================
print("=" * 70)
print("AUDIT 5 : V2 -> V1 references avec embed manquant ou render_to manquant")
print("=" * 70)
problem_classes = []
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    # Find lines like : v = SomeView(...) followed by edit_message(embed=...)
    # If "SomeView" is V1 (not V2), and the edit_message uses .embed() without attachments=[]
    for v1_name in v1_views:
        # Skip selectors and small utility classes (those are usually OK as transient)
        if any(kw in v1_name for kw in ("Modal", "Confirm")):
            continue
        # Find usage in this V2 class
        usage_pat = re.compile(r'\b' + re.escape(v1_name) + r'\s*\(')
        for m in usage_pat.finditer(cls_src):
            line_in_class = cls_src[:m.start()].count('\n')
            line_no = cls["line"] + line_in_class
            line_content = src.splitlines()[line_no - 1].strip() if line_no - 1 < len(src.splitlines()) else ""
            # On garde uniquement si la ligne suivante (ou dans les 5 lignes) fait edit_message
            after_lines = cls_src.split('\n')[line_in_class:line_in_class + 6]
            after_block = '\n'.join(after_lines)
            if 'edit_message' in after_block:
                if 'attachments' not in after_block:
                    problem_classes.append((v2_name, v1_name, line_no))

# Dedup
seen = set()
deduped = []
for x in problem_classes:
    if x not in seen:
        seen.add(x)
        deduped.append(x)

for v2, v1, ln in deduped[:30]:
    print(f"  L{ln} {v2} -> {v1}() (edit sans attachments=[])")
print(f"   Total : {len(deduped)}")
