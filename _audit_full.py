"""Audit complet - tous les bugs potentiels dans bot.py."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import ast
import re
from pathlib import Path
from collections import defaultdict

src = Path("bot.py").read_text(encoding="utf-8")
tree = ast.parse(src)

# Index des classes
classes = {}
funcs = {}
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        bases = [
            b.id if isinstance(b, ast.Name)
            else b.attr if isinstance(b, ast.Attribute)
            else "?"
            for b in node.bases
        ]
        classes[node.name] = {"bases": bases, "line": node.lineno, "node": node}
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        funcs[node.name] = node.lineno


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
# AUDIT 1 : V2 panels referencing V1 panels (NOT just selectors)
# ============================================================================
# Heuristique : si un V2 panel cree un autre objet dont la classe est V1 ET
# que cet objet est un PANEL (pas un selector / modal / view utilitaire),
# c'est un bug potentiel.

PANEL_KEYWORDS = ('Panel', 'PanelV')  # classes qui ressemblent a des panels

bugs_v2_to_v1_panel = []
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    for v1_name in v1_views:
        if not any(kw in v1_name for kw in PANEL_KEYWORDS):
            continue  # skip selectors/modals
        # Find calls v1_name(... that are NOT v1_name(self.u, self.g, opts) (which is selector pattern)
        pattern = re.compile(r'\b' + re.escape(v1_name) + r'\s*\(')
        for m in pattern.finditer(cls_src):
            line_in_class = cls_src[:m.start()].count("\n")
            line_no = cls["line"] + line_in_class
            line = src.splitlines()[line_no - 1].strip()
            bugs_v2_to_v1_panel.append((v2_name, v1_name, line_no, line[:120]))

print("=" * 80)
print(f"AUDIT 1 : V2 panel referencant un V1 'Panel' (probable bug nav)")
print("=" * 80)
for v2_name, v1_name, line_no, line in bugs_v2_to_v1_panel[:30]:
    print(f"L{line_no} {v2_name} -> {v1_name}")
    print(f"   {line}")
print()


# ============================================================================
# AUDIT 2 : .embed() utilise dans V2 panels
# ============================================================================
print("=" * 80)
print("AUDIT 2 : .embed() dans V2 panels (V1 pattern - V2 doit utiliser render_to)")
print("=" * 80)
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    for m in re.finditer(r'\.embed\(\)', cls_src):
        line_in_class = cls_src[:m.start()].count("\n")
        line_no = cls["line"] + line_in_class
        line = src.splitlines()[line_no - 1].strip()
        # Filtrer si c'est dans un context legitime (V2 -> V1 transition explicite)
        if 'attachments=' in line or 'asyncio.iscoroutinefunction' in line:
            continue
        print(f"L{line_no} {v2_name}: {line[:120]}")
print()


# ============================================================================
# AUDIT 3 : edit_message sans attachments=[] depuis V2
# ============================================================================
print("=" * 80)
print("AUDIT 3 : edit_message(..., view=v) dans V2 panels SANS attachments=[]")
print("=" * 80)
for v2_name in v2_panels:
    cls = classes[v2_name]
    cls_src = ast.get_source_segment(src, cls["node"]) or ""
    # Look for edit_message calls
    pattern = re.compile(
        r'await\s+\w+\.response\.edit_message\([^)]*?view=[^)]*?\)',
        re.DOTALL,
    )
    for m in pattern.finditer(cls_src):
        snippet = m.group(0)
        line_in_class = cls_src[:m.start()].count("\n")
        line_no = cls["line"] + line_in_class
        if 'attachments' not in snippet:
            line = src.splitlines()[line_no - 1].strip()
            # Filtrer les cas ou view=None ou view=self (resend du meme view)
            if 'view=None' in snippet or 'view=self' in snippet:
                continue
            print(f"L{line_no} {v2_name}: {line[:120]}")
print()


# ============================================================================
# AUDIT 4 : commandes slash sans try/except global
# ============================================================================
print("=" * 80)
print("AUDIT 4 : Slash commands sans defer() initial (risk de timeout 3s)")
print("=" * 80)
slash_pattern = re.compile(
    r'@bot\.tree\.command\(name="([^"]+)"[^)]*\)\s*(?:@[^\n]+\n\s*)*async def (\w+)\(([^)]*)\):',
    re.MULTILINE,
)
slow_commands = []
for m in slash_pattern.finditer(src):
    cmd_name, fn_name, params = m.group(1), m.group(2), m.group(3)
    # Find the function body
    fn_start = src.find(f"async def {fn_name}", m.start())
    if fn_start == -1:
        continue
    # Get lines 0-25 of the function body
    fn_end = src.find("\nasync def ", fn_start + 1)
    if fn_end == -1:
        fn_end = src.find("\ndef ", fn_start + 1)
    if fn_end == -1:
        fn_end = fn_start + 3000
    body = src[fn_start:min(fn_start + 2000, fn_end)]
    has_defer = 'response.defer' in body
    has_send_first = 'response.send_message' in body[:300]
    # If no defer and uses DB or async stuff, risky
    has_db = 'await get_db' in body or 'await db_set' in body or 'await cfg' in body
    has_db_in_first_500 = 'await get_db' in body[:500] or 'await db_set' in body[:500]
    if not has_defer and has_db_in_first_500:
        line_no = src[:fn_start].count("\n") + 1
        slow_commands.append((cmd_name, fn_name, line_no))

for cmd_name, fn_name, line_no in slow_commands[:20]:
    print(f"L{line_no} /{cmd_name} ({fn_name}) - utilise DB tot sans defer")
print(f"\nTotal slash commands sans defer + utilisent DB: {len(slow_commands)}")
print()


# ============================================================================
# AUDIT 5 : callbacks button sync (qui pourraient bloquer)
# ============================================================================
print("=" * 80)
print("AUDIT 5 : Button callbacks utilisant des fonctions sync DB ou file IO")
print("=" * 80)
# Pattern: defining a callback that uses .read_text() or .write_text() or open()
sync_io_pattern = re.compile(
    r'async def\s+\w+\([^)]*\):\s*\n((?:.*\n){0,30}?)\s*(?=async|class|\Z)',
    re.MULTILINE,
)
sync_io_count = 0
for m in re.finditer(r'(\.read_text\(|\.write_text\(|json\.load\(open\()', src):
    line_no = src[:m.start()].count("\n") + 1
    # Find enclosing function
    fn_start = max(
        src.rfind("async def ", 0, m.start()),
        src.rfind("def ", 0, m.start()),
    )
    if fn_start == -1:
        continue
    fn_line = src[:fn_start].count("\n") + 1
    if abs(line_no - fn_line) > 50:  # not in this fn
        continue
    fn_name_m = re.match(r'(?:async )?def (\w+)', src[fn_start:fn_start+100])
    fn_name = fn_name_m.group(1) if fn_name_m else "?"
    sync_io_count += 1
    if sync_io_count <= 10:
        print(f"L{line_no} dans {fn_name}() : {m.group(1)}")
print(f"\nTotal sync IO ops: {sync_io_count}")
print()
