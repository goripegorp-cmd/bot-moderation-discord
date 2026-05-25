"""Fix tous les self.parent dans les Select classes : rename en self.parent_view."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import re
from pathlib import Path

src = Path("bot.py").read_text(encoding="utf-8")

# Strategy: trouve chaque "class XxxSelect/Menu(Select)", et dans son corps,
# remplace TOUS les self.parent par self.parent_view.
# La portee de la classe est de "class X..." jusqu'au prochain "class Y" au top-level.

class_pat = re.compile(r'^class (\w+)\((\w*Select|\w*Menu)\b', re.MULTILINE)

# Liste des classes affectees
matches = list(class_pat.finditer(src))
print(f"Classes Select/Menu trouvees: {len(matches)}")

# Trouve les bornes de chaque classe
class_bounds = []
for i, m in enumerate(matches):
    start = m.start()
    # Fin = debut de la prochaine classe top-level (peu importe son type) ou EOF
    next_match = re.search(r'^class \w+', src[m.end():], re.MULTILINE)
    end = m.end() + next_match.start() if next_match else len(src)
    class_bounds.append((m.group(1), start, end))

# Pour chaque classe Select/Menu qui contient `self.parent = parent`, on rename
fixed_classes = []
new_src = ""
last_end = 0
for cls_name, start, end in class_bounds:
    cls_src = src[start:end]
    if 'self.parent = parent' not in cls_src and 'self.parent=parent' not in cls_src:
        # pas concernee, on garde tel quel
        new_src += src[last_end:end]
        last_end = end
        continue
    # Rename TOUS les self.parent en self.parent_view dans cette classe
    new_cls_src = re.sub(r'\bself\.parent\b', 'self.parent_view', cls_src)
    new_src += src[last_end:start] + new_cls_src
    last_end = end
    fixed_classes.append(cls_name)

# Ajoute le reste apres la derniere classe
new_src += src[last_end:]

print(f"\nClasses fixees : {len(fixed_classes)}")
for c in fixed_classes:
    print(f"  - {c}")

if new_src == src:
    print("\nAucun changement effectue.")
else:
    Path("bot.py").write_text(new_src, encoding="utf-8")
    print(f"\nbot.py mis a jour. {src.count('self.parent') - new_src.count('self.parent') + new_src.count('self.parent_view')} occurrences renommees.")
