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
Request Headers AbortController CustomEvent Event EventTarget DOMParser Node Element HTMLElement Proxy Reflect RegExp BigInt
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
    return noms


def exports(s: str) -> set[str]:
    noms = set(re.findall(r"\bexport\s+(?:async\s+)?function\s*\*?\s*([\w$]+)", s))
    noms.update(re.findall(r"\bexport\s+(?:const|let|var)\s+([\w$]+)", s))
    for m in re.finditer(r"\bexport\s*\{([^}]*)\}", s):
        noms.update(p.strip().split(" as ")[-1] for p in m.group(1).split(",") if p.strip())
    return noms


def sans_chaines(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"(?m)//.*$", " ", s)
    s = re.sub(r"`(?:\\.|[^`\\])*`", '""', s)
    s = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', s)
    s = re.sub(r"'(?:\\.|[^'\\\n])*'", '""', s)
    return s


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
