"""outils/controle_imports.py — contrôle statique des modules du site (site/*.js), sans dépendance.

Pour chaque module : toute fonction APPELÉE doit être déclarée dans le module (function, const, let, paramètre,
déstructuration) ou importée, ou être une fonction globale connue du navigateur. Attrape l'oubli d'un import (une
rubrique qui plante à l'affichage). Vérifie aussi que chaque nom importé existe bien dans le module d'origine.

Lancer : python outils/controle_imports.py   (code de sortie 1 s'il y a un problème)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
GLOBALES = set("""
fetch setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame queueMicrotask structuredClone
addEventListener removeEventListener dispatchEvent getComputedStyle getSelection matchMedia scrollTo alert confirm prompt
encodeURIComponent decodeURIComponent encodeURI decodeURI isNaN isFinite parseInt parseFloat String Number Boolean Array Object Math
Date JSON Promise Map Set WeakMap WeakSet Symbol Error TypeError RangeError URL URLSearchParams Intl Blob File FileReader Response
Request Headers AbortController CustomEvent Event EventTarget DOMParser Node Element HTMLElement Proxy Reflect RegExp BigInt WebSocket
self importScripts caches clients registration atob btoa console crypto indexedDB navigator location history document window
performance visualViewport MutationObserver ResizeObserver IntersectionObserver Uint8Array Uint16Array Float32Array ArrayBuffer TextEncoder TextDecoder async of
if for while switch catch return typeof function import export new delete void await yield super this
""".split())
METHODES_SANS_OBJET = {"then", "catch", "finally"}


def declares(s: str) -> set[str]:
    noms = set()
    for m in re.finditer(r"\bimport\s*\{([^}]*)\}\s*from", s):
        for p in m.group(1).split(","):
            p = p.strip()
            if p:
                noms.add(p.split(" as ")[-1].strip())
    for m in re.finditer(r"\bimport\s+\*\s+as\s+(\w+)", s):
        noms.add(m.group(1))
    noms.update(re.findall(r"\bfunction\s*\*?\s*(\w+)", s))
    noms.update(re.findall(r"\b(?:const|let|var)\s+(\w+)", s))
    for m in re.finditer(r"\b(?:const|let|var)\s*[{\[]([^=]*?)[}\]]\s*=", s):
        for p in re.split(r"[,\s]+", m.group(1)):
            p = p.split(":")[-1].strip().lstrip(".")
            if re.fullmatch(r"\w+", p or ""):
                noms.add(p)
    # paramètres de fonctions et de flèches
    for m in re.finditer(r"\bfunction\s*\w*\s*\(([^)]*)\)", s):
        noms.update(re.findall(r"\b([A-Za-z_$][\w$]*)\b", m.group(1)))
    for m in re.finditer(r"\(([^()]*)\)\s*=>", s):
        noms.update(re.findall(r"\b([A-Za-z_$][\w$]*)\b", m.group(1)))
    noms.update(re.findall(r"\b([A-Za-z_$][\w$]*)\s*=>", s))
    noms.update(re.findall(r"\bcatch\s*\((\w+)\)", s))
    noms.update(re.findall(r"(?:^\s*|[{,]\s*)(\w+)\s*\([^()]*\)\s*\{", s, flags=re.M))  # méthodes abrégées
    noms.update(re.findall(r"(?m)^\s*(?:async\s+|static\s+)*(\w+)\s*\([^()]*\)\s*\{", s))  # méthodes d'une classe (async, static)
    noms.update(re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", s))
    return noms


def exports(s: str) -> set[str]:
    noms = set(re.findall(r"\bexport\s+(?:async\s+)?function\s*\*?\s*([\w$]+)", s))
    noms.update(re.findall(r"\bexport\s+(?:const|let|var)\s+([\w$]+)", s))
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}", s):
        noms.update(p.strip().split(" as ")[-1] for p in m.group(1).split(",") if p.strip())
    return noms


#  Après ces mots, « / » ouvre une expression régulière (pas une division).
_AVANT_REGEX = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else",
                "yield", "await"}


def sans_chaines(s: str) -> str:
    """Le code sans commentaires, chaînes, gabarits ni expressions régulières (chacun remplacé par "" ; les retours à
    la ligne gardés : les numéros de ligne restent justes). Un seul passage, comme le navigateur le lit (26/10/2026) :
    un « // » dans une chaîne (« https://… ») n'est pas un commentaire, une apostrophe dans un commentaire n'ouvre pas
    de chaîne, des guillemets dans une expression régulière non plus — l'ancien découpage par expressions régulières
    s'y trompait et inventait des fautes sur tout le reste du fichier."""
    out, i, n = [], 0, len(s)
    dernier, mot = "", ""   # le dernier caractère significatif du code, et le dernier mot (décident de « / »)
    while i < n:
        c = s[i]
        if c == "/" and s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and s.startswith("/*", i):
            j = s.find("*/", i + 2)
            fin = n if j < 0 else j + 2
            out.append(" " + "\n" * s.count("\n", i, fin))
            i = fin
            continue
        if c in "\"'`":
            j, lignes = i + 1, 0
            while j < n and s[j] != c:
                if s[j] == "\\":
                    j += 1
                elif s[j] == "\n":
                    lignes += 1
                    if c != "`":
                        break
                j += 1
            out.append('""' + "\n" * lignes)
            i, dernier, mot = j + 1, '"', ""
            continue
        if c == "/" and (not dernier or dernier in "(,=:[!&|?{};+-*%<>~^" or mot in _AVANT_REGEX):
            j, classe = i + 1, False
            while j < n and s[j] != "\n" and (s[j] != "/" or classe):
                if s[j] == "\\":
                    j += 1
                elif s[j] == "[":
                    classe = True
                elif s[j] == "]":
                    classe = False
                j += 1
            j += 1
            while j < n and s[j].isalpha():
                j += 1
            out.append('""')
            i, dernier, mot = j, '"', ""
            continue
        out.append(c)
        if not c.isspace():
            dernier = c
            mot = (mot + c) if (c.isalnum() or c in "_$") else ""
        i += 1
    return "".join(out)


def main() -> int:
    problemes = []
    textes = {f.name: f.read_text(encoding="utf-8") for f in sorted(SITE.glob("*.js"))}
    for nom, brut in textes.items():
        s = sans_chaines(brut)
        connus = declares(s) | GLOBALES
        for m in re.finditer(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", s):
            n = m.group(1)
            if n not in connus and n not in METHODES_SANS_OBJET:
                ligne = s[:m.start()].count("\n") + 1
                problemes.append(f"{nom}:{ligne} : « {n}( » n'est ni déclaré ni importé")
        # Un nom importé puis redéclaré dans le module (const/let/var/function, paramètre) masque l'import :
        # « nb is not a function » au premier appel (25/10 : un compteur `const nb = {}` cachait le helper `nb`).
        importes = set()
        for m in re.finditer(r"\bimport\s*\{([^}]*)\}\s*from", s):
            importes.update(p.strip().split(" as ")[-1].strip() for p in m.group(1).split(",") if p.strip())
        locaux = set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", s)) | set(re.findall(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)", s))
        for m in re.finditer(r"\b(?:const|let|var)\s+[^;=]+?,\s*([A-Za-z_$][\w$]*)\s*=", s):
            locaux.add(m.group(1))
        for m in re.finditer(r"\bfunction\s*\w*\s*\(([^)]*)\)", s):
            locaux.update(re.findall(r"\b([A-Za-z_$][\w$]*)\b", m.group(1)))
        for m in re.finditer(r"\(([^()]*)\)\s*=>", s):
            locaux.update(re.findall(r"\b([A-Za-z_$][\w$]*)\b", m.group(1)))
        locaux.update(re.findall(r"\b([A-Za-z_$][\w$]*)\s*=>", s))
        for n in sorted(importes & locaux):
            problemes.append(f"{nom} : « {n} » est importé puis redéclaré dans le module (l'import est masqué)")
        for m in re.finditer(r'\bimport\s*\{([^}]*)\}\s*from\s*"\./([\w.]+)"', brut):
            source = textes.get(m.group(2))
            if source is None:
                problemes.append(f"{nom} : importe depuis {m.group(2)}, qui n'existe pas")
                continue
            dispo = exports(sans_chaines(source))
            for p in m.group(1).split(","):
                p = p.strip().split(" as ")[0].strip()
                if p and p not in dispo:
                    problemes.append(f"{nom} : « {p} » n'est pas exporté par {m.group(2)}")
    for p in sorted(set(problemes)):
        print(p)
    print(f"{len(textes)} module(s) contrôlé(s), {len(set(problemes))} problème(s).")
    return 1 if problemes else 0


if __name__ == "__main__":
    sys.exit(main())
