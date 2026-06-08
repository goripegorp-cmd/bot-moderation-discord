#!/usr/bin/env python3
"""generate_index.py — build INDEX.md, a grep-able symbol map of the whole repo.

WHY THIS EXISTS
---------------
bot.py is ~84k lines and the project has ~90 sibling modules. "Where is symbol X
defined?" is the single most common navigation question. This script walks every
.py file with the `ast` module and emits INDEX.md: for each file, every top-level
class / function (and each class' methods) with its line number and a compact
signature, plus a flat alphabetical lookup at the end.

It is run by .github/workflows/index.yml on every push that touches a .py file,
and the refreshed INDEX.md is committed back. It is intentionally DETERMINISTIC
(sorted output, NO timestamps) so an unchanged codebase produces a byte-identical
INDEX.md and the CI diff-guard skips the commit (no commit loop).

You can also run it locally:  python generate_index.py
"""
from __future__ import annotations

import ast
import os
import sys

# Directories never worth indexing.
_SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", ".github", "node_modules", ".mypy_cache", ".ruff_cache"}
_OUT = "INDEX.md"


def _sig(node: ast.AST) -> str:
    """Compact, robust argument list — names only (no annotations/defaults)."""
    a = node.args
    parts: list[str] = []
    for arg in getattr(a, "posonlyargs", []) or []:
        parts.append(arg.arg)
    if getattr(a, "posonlyargs", None):
        parts.append("/")
    for arg in a.args:
        parts.append(arg.arg)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    for arg in a.kwonlyargs:
        parts.append(arg.arg)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return ", ".join(parts)


def _decorator(node: ast.AST) -> str:
    """Short label for the first decorator, e.g. '@tasks.loop' or '@app_commands.command'."""
    for dec in getattr(node, "decorator_list", []) or []:
        target = dec.func if isinstance(dec, ast.Call) else dec
        try:
            name = ast.unparse(target)
        except Exception:
            name = getattr(target, "id", None) or getattr(target, "attr", "")
        if name:
            return "@" + name
    return ""


def _kind(node: ast.AST) -> str:
    return "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"


def _walk_file(path: str):
    """Return (classes, funcs) where each entry is a dict of metadata."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as exc:  # pragma: no cover - unreadable file
        return None, f"unreadable: {exc}"
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as exc:
        return None, f"SyntaxError L{exc.lineno}: {exc.msg}"

    classes: list[dict] = []
    funcs: list[dict] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    pass
            methods = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        "name": sub.name,
                        "line": sub.lineno,
                        "kind": _kind(sub),
                        "sig": _sig(sub),
                        "dec": _decorator(sub),
                    })
            methods.sort(key=lambda m: m["line"])
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": bases,
                "dec": _decorator(node),
                "methods": methods,
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append({
                "name": node.name,
                "line": node.lineno,
                "kind": _kind(node),
                "sig": _sig(node),
                "dec": _decorator(node),
            })
    classes.sort(key=lambda c: c["line"])
    funcs.sort(key=lambda f: f["line"])
    return {"classes": classes, "funcs": funcs, "lines": src.count("\n") + 1}, None


def _iter_py(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    files = sorted(_iter_py(root))
    # Skip indexing this generator's own output and itself? keep itself (it's a real file).

    parsed: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for rel in files:
        data, err = _walk_file(os.path.join(root, rel))
        if err:
            errors[rel] = err
        else:
            parsed[rel] = data

    out: list[str] = []
    out.append("# INDEX.md — auto-generated symbol map")
    out.append("")
    out.append("> **DO NOT EDIT BY HAND.** Regenerated by `generate_index.py` "
               "(CI workflow `.github/workflows/index.yml`) on every push touching a `.py` file.")
    out.append("> Line numbers are a *hint* — they drift between edits. Use `Grep` for the live location; "
               "use this file to learn **which module** owns a symbol.")
    out.append("")

    # --- Summary table -----------------------------------------------------
    out.append("## Summary")
    out.append("")
    out.append("| file | lines | classes | funcs |")
    out.append("| --- | ---: | ---: | ---: |")
    total_lines = total_cls = total_fn = 0
    for rel in files:
        if rel not in parsed:
            continue
        d = parsed[rel]
        nc, nf = len(d["classes"]), len(d["funcs"])
        total_lines += d["lines"]
        total_cls += nc
        total_fn += nf
        out.append(f"| `{rel}` | {d['lines']} | {nc} | {nf} |")
    out.append(f"| **TOTAL ({len(parsed)} files)** | **{total_lines}** | **{total_cls}** | **{total_fn}** |")
    out.append("")
    if errors:
        out.append("### ⚠️ Files that failed to parse")
        out.append("")
        for rel, err in sorted(errors.items()):
            out.append(f"- `{rel}` — {err}")
        out.append("")

    # --- Flat alphabetical lookup -----------------------------------------
    flat: list[tuple[str, str]] = []  # (symbol_lower, line_text)
    for rel in files:
        d = parsed.get(rel)
        if not d:
            continue
        for f in d["funcs"]:
            flat.append((f["name"].lower(), f"`{f['name']}` — `{rel}`:{f['line']}  ({f['kind']})"))
        for c in d["classes"]:
            flat.append((c["name"].lower(), f"`{c['name']}` — `{rel}`:{c['line']}  (class)"))
            for m in c["methods"]:
                flat.append((m["name"].lower(),
                             f"`{c['name']}.{m['name']}` — `{rel}`:{m['line']}  (method)"))
    flat.sort(key=lambda t: (t[0], t[1]))
    out.append(f"## Alphabetical lookup ({len(flat)} symbols)")
    out.append("")
    for _, line in flat:
        out.append(f"- {line}")
    out.append("")

    # --- Per-file detail ---------------------------------------------------
    out.append("## Per-file detail")
    out.append("")
    for rel in files:
        d = parsed.get(rel)
        if not d:
            continue
        if not d["classes"] and not d["funcs"]:
            continue
        out.append(f"### `{rel}`")
        out.append("")
        for f in d["funcs"]:
            dec = f" {f['dec']}" if f["dec"] else ""
            out.append(f"- L{f['line']}  `{f['kind']} {f['name']}({f['sig']})`{dec}")
        for c in d["classes"]:
            base = f"({', '.join(c['bases'])})" if c["bases"] else ""
            dec = f" {c['dec']}" if c["dec"] else ""
            out.append(f"- L{c['line']}  `class {c['name']}{base}`{dec}")
            for m in c["methods"]:
                mdec = f" {m['dec']}" if m["dec"] else ""
                out.append(f"    - L{m['line']}  `{m['kind']} {m['name']}({m['sig']})`{mdec}")
        out.append("")

    with open(os.path.join(root, _OUT), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"OK: wrote {_OUT} — {len(parsed)} files, {total_cls} classes, {total_fn} funcs, {len(flat)} symbols")
    if errors:
        print(f"NOTE: {len(errors)} file(s) failed to parse (listed in {_OUT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
