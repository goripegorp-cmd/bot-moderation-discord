"""dessins_site.py — les dessins du site « La Capitainerie » (25/10/2026).

Tout est dessiné ici, par le code, dans un seul style : la gravure à l'encre d'un livre de
bord ancien (traits nets, pleins d'encre, petites hachures, deux tons au plus).

  site/icones/ui.svg            sprite : <symbol id="i-<nom>" viewBox="0 0 32 32"> (ICONES_REQUISES vérifiées)
  site/ornements/*.svg          coin, cadre (border-image), corde (x et y), sceaux, tampons, rubans,
                                rose des vents, filet, clou, étiquette, signe ฿, affiche « WANTED »
  site/ornements/affiche.json   dimensions, calques et zones de l'affiche (le texte est posé par la page)
  site/ornements/planche.html   planche de contrôle (non servie : .html hors liste blanche)
  site/textures/*.webp          parchemin(_fonce), bois, papier_affiche, carte_marine, vignette,
                                grain_tampon (noms alignés sur l'interface ; < 120 Ko chacune)
  site/polices/                 woff2 OFL + polices.css (commande « polices », seule en réseau)
  site/LICENCES.md              section balisée « dessins_site » (le reste du fichier est préservé)
  visuels/icones/<nom>.png      émojis d'application 128 px (Discord) ; un nom déjà pris garde son
                                fichier et l'icône prend le préfixe ev_ ; un PNG non signé par ce
                                script n'est jamais écrasé

Règles : aucun attribut style="…" (la CSP du site les bloque) ; dans le sprite, ni masque, ni
dégradé, ni filtre (il est lu par <use>) ; encre = currentColor, second ton =
var(--ton2, #a8823f). Chaque SVG est vérifié (XML valide, pas de « -- » en commentaire).
Les PNG sont rendus par Pillow à partir des MÊMES tracés (pair-impair et non-nul exacts).
Tout est déterministe (graines fixes) : deux fabrications donnent les mêmes fichiers.
Les textures demandent numpy ; le reste, Pillow seul.

Usage :
  python outils/dessins_site.py                  tout (sauf « polices »)
  python outils/dessins_site.py icones ornements textures png planche
  python outils/dessins_site.py apercu <f.png> [noms…] [--zoom 2]   planche-contact Pillow
  python outils/dessins_site.py polices          télécharge les woff2 (Google Fonts, OFL)
  python outils/dessins_site.py glyphes <ttf>…   réimprime la table GLYPHES (maintenance)
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

try:
    import numpy as np
except ImportError:  # seules les textures en ont besoin
    np = None

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "site"
D_ICONES = SITE / "icones"
D_ORNEMENTS = SITE / "ornements"
D_TEXTURES = SITE / "textures"
D_POLICES = SITE / "polices"
D_PNG = RACINE / "visuels" / "icones"

# Palette de la spécification (§4).
ENCRE = "#2b1d12"
PARCHEMIN = "#efe2c4"
PARCHEMIN2 = "#e4d2a6"
BOIS = "#4a2e1a"
BOIS2 = "#2f1d10"
LAITON = "#a8823f"
CORDE = "#b99a6b"
MER = "#1f4e5a"
CIRE = "#8e2a24"
VERT = "#3f6b3a"
AMBRE = "#a8641c"

TON2_SVG = "var(--ton2, #a8823f)"


def hexa(c: str, a: int = 255) -> tuple:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), a


def n(v: float) -> str:
    """Nombre court pour le SVG (2 décimales au plus)."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "", "-") else s


def n1(v: float) -> str:
    """Une décimale : géométrie calculée (hachures, traits à la plume) ; écart ≤ 0,05 unité."""
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "", "-") else s


# ════════════════════════════════════════════════════════════════════════════════════════
#  Géométrie : transformations, chemins SVG, aplatissement
# ════════════════════════════════════════════════════════════════════════════════════════

ID = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def m_mul(m1, m2):
    """m1 ∘ m2 (m2 d'abord), matrices SVG (a b c d e f)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def m_app(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def m_rot(deg, cx=0.0, cy=0.0):
    a = math.radians(deg)
    co, si = math.cos(a), math.sin(a)
    return m_mul(m_mul((1, 0, 0, 1, cx, cy), (co, si, -si, co, 0, 0)), (1, 0, 0, 1, -cx, -cy))


_TF = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")


def m_svg(tf):
    m = ID
    for nom, args in _TF.findall(tf or ""):
        v = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if nom == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif nom == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif nom == "rotate":
            t = m_rot(v[0], *(v[1:3] if len(v) == 3 else (0, 0)))
        elif nom == "matrix":
            t = tuple(v)
        elif nom == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        else:
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        m = m_mul(m, t)
    return m


def m_echelle(m):
    return math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))


_JETON = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def _jetons(d):
    return [c if c else float(v) for c, v in _JETON.findall(d)]


def _arc(x0, y0, rx, ry, phi, fa, fs, x1, y1, pas):
    if rx == 0 or ry == 0 or (x0 == x1 and y0 == y1):
        return [(x1, y1)]
    phi = math.radians(phi)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    rx, ry = abs(rx), abs(ry)
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x0 + x1) / 2
    cy = sp * cxp + cp * cyp + (y0 + y1) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dt > 0:
        dt -= 2 * math.pi
    elif fs and dt < 0:
        dt += 2 * math.pi
    k = max(2, int(math.ceil(abs(dt) * max(rx, ry) / pas)))
    pts = []
    for i in range(1, k + 1):
        t = t1 + dt * i / k
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        pts.append((cp * ex - sp * ey + cx, sp * ex + cp * ey + cy))
    pts[-1] = (x1, y1)
    return pts


def _bezier(pts, pas):
    lg = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    k = max(2, min(400, int(math.ceil(lg / pas))))
    out = []
    for i in range(1, k + 1):
        t = i / k
        u = 1 - t
        if len(pts) == 4:
            c = (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)
        else:
            c = (u * u, 2 * u * t, t * t)
        out.append((sum(ci * p[0] for ci, p in zip(c, pts)), sum(ci * p[1] for ci, p in zip(c, pts))))
    return out


def aplatir(d: str, pas: float = 0.25):
    """Chemin SVG → [(points, fermé)] ; courbes découpées en segments de longueur ≈ pas."""
    toks = _jetons(d)
    i, cmd = 0, None
    x = y = sx = sy = 0.0
    ctl = None          # dernier point de contrôle (S/T)
    dern = ""           # dernière commande (majuscule)
    sous, cur = [], None

    def lire(k):
        nonlocal i
        v = toks[i:i + k]
        i += k
        return v

    while i < len(toks):
        t = toks[i]
        if isinstance(t, str):
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur is not None:
                    cur[1] = True
                x, y, cur, dern = sx, sy, None, "Z"
                continue
        if cmd is None:
            raise ValueError("chemin sans commande")
        rel, C = cmd.islower(), cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if C == "M":
            px, py = lire(2)
            x = sx = px + ox
            y = sy = py + oy
            cur = [[(x, y)], False]
            sous.append(cur)
            cmd, dern = ("l" if rel else "L"), "M"
            continue
        if cur is None:
            cur = [[(x, y)], False]
            sous.append(cur)
        if C == "L":
            px, py = lire(2)
            x, y = px + ox, py + oy
            cur[0].append((x, y))
        elif C == "H":
            (px,) = lire(1)
            x = px + ox
            cur[0].append((x, y))
        elif C == "V":
            (py,) = lire(1)
            y = py + oy
            cur[0].append((x, y))
        elif C in "CS":
            if C == "C":
                x1, y1, x2, y2, px, py = lire(6)
                c1 = (x1 + ox, y1 + oy)
            else:
                x2, y2, px, py = lire(4)
                c1 = (2 * x - ctl[0], 2 * y - ctl[1]) if dern in "CS" and ctl else (x, y)
            c2 = (x2 + ox, y2 + oy)
            fin = (px + ox, py + oy)
            cur[0].extend(_bezier([(x, y), c1, c2, fin], pas))
            ctl, (x, y) = c2, fin
        elif C in "QT":
            if C == "Q":
                x1, y1, px, py = lire(4)
                c1 = (x1 + ox, y1 + oy)
            else:
                px, py = lire(2)
                c1 = (2 * x - ctl[0], 2 * y - ctl[1]) if dern in "QT" and ctl else (x, y)
            fin = (px + ox, py + oy)
            cur[0].extend(_bezier([(x, y), c1, fin], pas))
            ctl, (x, y) = c1, fin
        elif C == "A":
            rx, ry, phi, fa, fs, px, py = lire(7)
            fin = (px + ox, py + oy)
            cur[0].extend(_arc(x, y, rx, ry, phi, int(fa), int(fs), fin[0], fin[1], pas))
            x, y = fin
        else:
            raise ValueError(f"commande inconnue {cmd}")
        dern = C
    return [(p, f) for p, f in sous if len(p) > 1]


def chemin_transforme(d: str, m) -> str:
    """Applique une matrice à un chemin absolu M/L/H/V/Q/C/Z (contours de lettres)."""
    toks = _jetons(d)
    out, i, cmd, x, y = [], 0, None, 0.0, 0.0
    while i < len(toks):
        if isinstance(toks[i], str):
            cmd = toks[i]
            i += 1
            if cmd == "Z":
                out.append("Z")
                continue
        k = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "C": 6}[cmd]
        v = toks[i:i + k]
        i += k
        if cmd == "H":
            v, c = [v[0], y], "L"
        elif cmd == "V":
            v, c = [x, v[0]], "L"
        else:
            c = cmd
        pts = [m_app(m, v[j], v[j + 1]) for j in range(0, len(v), 2)]
        x, y = v[-2], v[-1]
        out.append(c + " ".join(f"{n(a)} {n(b)}" for a, b in pts))
        if cmd == "M":
            cmd = "L"
    return "".join(out)


# Formes simples (chemins SVG) ------------------------------------------------------------

def cercle(cx, cy, r):
    return (f"M{n(cx - r)} {n(cy)}a{n(r)} {n(r)} 0 1 0 {n(2 * r)} 0"
            f"a{n(r)} {n(r)} 0 1 0 {n(-2 * r)} 0Z")


def ellipse(cx, cy, rx, ry):
    return (f"M{n(cx - rx)} {n(cy)}a{n(rx)} {n(ry)} 0 1 0 {n(2 * rx)} 0"
            f"a{n(rx)} {n(ry)} 0 1 0 {n(-2 * rx)} 0Z")


def rect(x, y, l, h, r=0.0):
    if r <= 0:
        return f"M{n(x)} {n(y)}h{n(l)}v{n(h)}h{n(-l)}Z"
    r = min(r, l / 2, h / 2)
    return (f"M{n(x + r)} {n(y)}h{n(l - 2 * r)}a{n(r)} {n(r)} 0 0 1 {n(r)} {n(r)}v{n(h - 2 * r)}"
            f"a{n(r)} {n(r)} 0 0 1 {n(-r)} {n(r)}h{n(-(l - 2 * r))}a{n(r)} {n(r)} 0 0 1 {n(-r)} {n(-r)}"
            f"v{n(-(h - 2 * r))}a{n(r)} {n(r)} 0 0 1 {n(r)} {n(-r)}Z")


def poly(pts, ferme=True, prec=2):
    f = n if prec == 2 else n1
    s = "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts)
    return s + ("Z" if ferme else "")


def ligne(x1, y1, x2, y2):
    return f"M{n(x1)} {n(y1)}L{n(x2)} {n(y2)}"


def arc_pts(cx, cy, r, a0, a1, k=24, ry=None):
    """Points d'un arc (degrés, 0 = droite, sens horaire à l'écran)."""
    ry = r if ry is None else ry
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / k)),
             cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / k))) for i in range(k + 1)]


def etoile_pts(cx, cy, r1, r2, branches=5, rot=-90.0):
    pts = []
    for i in range(branches * 2):
        r = r1 if i % 2 == 0 else r2
        a = math.radians(rot + 180.0 * i / branches)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ════════════════════════════════════════════════════════════════════════════════════════
#  Régions et hachures (découpées exactement dans les formes, comme un graveur)
# ════════════════════════════════════════════════════════════════════════════════════════

def _iv_union(a, b):
    tout = sorted(a + b)
    out = []
    for x0, x1 in tout:
        if out and x0 <= out[-1][1]:
            out[-1][1] = max(out[-1][1], x1)
        else:
            out.append([x0, x1])
    return [tuple(v) for v in out]


def _iv_inter(a, b):
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        x0, x1 = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if x0 < x1:
            out.append((x0, x1))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _iv_diff(a, b):
    out = []
    for x0, x1 in a:
        cur = x0
        for y0, y1 in b:
            if y1 <= cur or y0 >= x1:
                continue
            if y0 > cur:
                out.append((cur, y0))
            cur = max(cur, y1)
        if cur < x1:
            out.append((cur, x1))
    return out


class Forme:
    """Région pair-impair d'un chemin fermé ; se combine par & | - pour placer des hachures."""

    def __init__(self, d=None, op=None, g=None, h=None, tf=None):
        self.d, self.op, self.g, self.h, self.tf = d, op, g, h, tf
        self._polys = None

    def __and__(self, o):
        return Forme(op="&", g=self, h=o)

    def __or__(self, o):
        return Forme(op="|", g=self, h=o)

    def __sub__(self, o):
        return Forme(op="-", g=self, h=o)

    def _preparer(self, m):
        if self.op:
            self.g._preparer(m)
            self.h._preparer(m)
            return
        mm = m_mul(m, m_svg(self.tf)) if self.tf else m
        self._polys = []
        for pts, _ in aplatir(self.d, 0.08):
            q = [m_app(mm, x, y) for x, y in pts]
            if q[0] != q[-1]:
                q.append(q[0])
            self._polys.append(q)

    def _boite(self):
        if self.op:
            b1, b2 = self.g._boite(), self.h._boite()
            if self.op == "&":
                return max(b1[0], b2[0]), min(b1[1], b2[1])
            if self.op == "-":
                return b1
            return min(b1[0], b2[0]), max(b1[1], b2[1])
        ys = [p[1] for q in self._polys for p in q]
        return min(ys), max(ys)

    def intervalles(self, y):
        if self.op:
            a, b = self.g.intervalles(y), self.h.intervalles(y)
            return {"&": _iv_inter, "|": _iv_union, "-": _iv_diff}[self.op](a, b)
        xs = []
        for q in self._polys:
            for (x0, y0), (x1, y1) in zip(q, q[1:]):
                if (y0 <= y < y1) or (y1 <= y < y0):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xs.sort()
        return [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2) if xs[k + 1] > xs[k]]


def hachures(forme: Forme, angle=45.0, pas=2.0, marge=0.45, lmin=0.6, phase=0.5,
             centre=(16.0, 16.0), retrait=0.0):
    """Segments parallèles (angle en degrés, 0 = horizontal) découpés dans la forme.
    `retrait` raccourcit chaque segment d'un côté (fin de trait en biseau du graveur)."""
    m_inv = m_rot(-angle, *centre)
    m_dir = m_rot(angle, *centre)
    forme._preparer(m_inv)
    y0, y1 = forme._boite()
    k0 = math.floor((y0 - centre[1]) / pas) - 1
    segs = []
    k = k0
    while True:
        y = centre[1] + (k + phase) * pas
        k += 1
        if y > y1:
            break
        if y < y0:
            continue
        for a, b in forme.intervalles(y):
            a, b = a + marge, b - marge - retrait
            if b - a >= lmin:
                segs.append((m_app(m_dir, a, y), m_app(m_dir, b, y)))
    return "".join(f"M{n1(p[0])} {n1(p[1])}L{n1(q[0])} {n1(q[1])}" for p, q in segs)


# ════════════════════════════════════════════════════════════════════════════════════════
#  Dessin : une liste de tracés (remplissage et/ou contour), partagée SVG ↔ Pillow
# ════════════════════════════════════════════════════════════════════════════════════════

@dataclass
class Trace:
    d: str
    fill: str | None = None       # "encre" | "ton2" | "#rrggbb" | None
    stroke: str | None = None
    sw: float = 0.0
    cap: str = "round"
    join: str = "round"
    eo: bool = False              # règle pair-impair (trous)
    tf: str | None = None         # transformation SVG
    op: float = 1.0               # opacité (ornements seulement)


class Dessin:
    def __init__(self, l=32.0, h=32.0):
        self.l, self.h = l, h
        self.traces: list[Trace] = []

    def trait(self, d, sw=2.0, c="encre", cap="round", join="round", tf=None, op=1.0):
        if d:
            self.traces.append(Trace(d, None, c, sw, cap, join, False, tf, op))
        return self

    def plein(self, d, c="encre", eo=False, tf=None, op=1.0):
        if d:
            self.traces.append(Trace(d, c, None, 0.0, "round", "round", eo, tf, op))
        return self

    def ton(self, d, eo=False, tf=None):
        return self.plein(d, "ton2", eo, tf)

    def ton_trait(self, d, sw=2.0, eo=False, tf=None, c="ton2"):
        self.traces.append(Trace(d, c, "encre", sw, "round", "round", eo, tf))
        return self

    def hach(self, forme, angle=45.0, pas=2.0, sw=0.9, c="encre", **kw):
        return self.trait(hachures(forme, angle, pas, **kw), sw, c, cap="round")


# ── Rendu Pillow (sur-échantillonné) ─────────────────────────────────────────────────────

def _couleur(c, couleurs):
    if c in couleurs:
        return couleurs[c]
    return hexa(c)


def rasteriser(dessin: Dessin, l_px: int, h_px: int | None = None, couleurs=None, sur=None,
               fond=None, cadrage=None):
    """Rendu RGBA d'un dessin : chaque tracé est rempli puis contouré à ×sur, puis réduit par
    moyenne de boîte (en alpha prémultiplié). `cadrage` = (x, y, l, h) dans le repère du dessin."""
    couleurs = couleurs or {"encre": hexa(ENCRE), "ton2": hexa(LAITON)}
    cx, cy, cl, ch = cadrage or (0, 0, dessin.l, dessin.h)
    h_px = h_px or round(l_px * ch / cl)
    sur = sur or max(4, min(16, math.ceil(512 / max(l_px, h_px))))
    W, H = l_px * sur, h_px * sur
    s = W / cl
    vue = (s, 0, 0, s, -cx * s, -cy * s)
    toile = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if fond:
        toile.paste(_couleur(fond, couleurs), (0, 0, W, H))
    for t in dessin.traces:
        m = m_mul(vue, m_svg(t.tf)) if t.tf else vue
        e = m_echelle(m)
        sous = [([m_app(m, x, y) for x, y in pts], f) for pts, f in aplatir(t.d, 1.25 / e)]
        if t.fill:
            _composer(toile, _masque_rempli(sous, W, H, t.eo), _couleur(t.fill, couleurs), t.op)
        if t.stroke and t.sw > 0:
            masque = Image.new("L", (W, H), 0)
            dr = ImageDraw.Draw(masque)
            w = max(1, round(t.sw * e))
            for pts, ferme in sous:
                q = list(pts)
                if ferme:
                    q = q + [q[0], q[1]] if len(q) > 1 else q
                dr.line(q, fill=255, width=w, joint="curve")
                if not ferme and t.cap in ("round", "square"):
                    r = w / 2
                    for (ax, ay), (bx, by) in ((q[0], q[1]), (q[-1], q[-2])):
                        if t.cap == "round":
                            dr.ellipse((ax - r, ay - r, ax + r, ay + r), fill=255)
                        else:
                            lg = math.hypot(ax - bx, ay - by) or 1
                            ux, uy = (ax - bx) / lg * r, (ay - by) / lg * r
                            dr.polygon([(ax - uy, ay + ux), (ax - uy + ux, ay + ux + uy),
                                        (ax + uy + ux, ay - ux + uy), (ax + uy, ay - ux)], fill=255)
            _composer(toile, masque, _couleur(t.stroke, couleurs), t.op)
    return toile.convert("RGBa").resize((l_px, h_px), Image.BOX).convert("RGBA")


def _masque_rempli(sous, W, H, eo):
    """Masque d'un remplissage, fidèle au SVG : pair-impair, ou non-nul (nombre d'enroulement :
    chaque contour ajoute ±1 selon son sens, la zone est pleine là où la somme n'est pas nulle)."""
    polys = [pts for pts, _ in sous if len(pts) >= 3]
    masque = Image.new("L", (W, H), 0)
    if eo or len(polys) < 2:
        for pts in polys:
            calque = Image.new("L", (W, H), 0)
            ImageDraw.Draw(calque).polygon(pts, fill=255)
            masque = ImageChops.difference(masque, calque) if eo else ImageChops.lighter(masque, calque)
        return masque
    aires = [sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1] for i in range(len(q)))
             for q in polys]
    if np is None:  # sans numpy : les contours du sens du plus grand ajoutent, les autres creusent
        sens = 1 if aires[max(range(len(aires)), key=lambda i: abs(aires[i]))] > 0 else -1
        creux = Image.new("L", (W, H), 0)
        for q, a in zip(polys, aires):
            ImageDraw.Draw(masque if a * sens > 0 else creux).polygon(q, fill=255)
        return ImageChops.subtract(masque, creux)
    enroulement = np.zeros((H, W), np.int16)
    for q, a in zip(polys, aires):
        x0 = max(0, int(min(p[0] for p in q)) - 1)
        y0 = max(0, int(min(p[1] for p in q)) - 1)
        x1 = min(W, int(max(p[0] for p in q)) + 2)
        y1 = min(H, int(max(p[1] for p in q)) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        cal = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(cal).polygon([(x - x0, y - y0) for x, y in q], fill=1)
        enroulement[y0:y1, x0:x1] += np.asarray(cal, np.int16) * (1 if a > 0 else -1)
    return Image.fromarray(((enroulement != 0) * 255).astype(np.uint8), "L")


def _composer(toile, masque, couleur, op=1.0):
    r, g, b = couleur[:3]
    a = couleur[3] if len(couleur) > 3 else 255
    a = int(a * op)
    if a < 255:
        masque = masque.point(lambda v: v * a // 255)
    calque = Image.new("RGBA", toile.size, (r, g, b, 0))
    calque.putalpha(masque)
    toile.alpha_composite(calque)


# ── Écriture SVG ─────────────────────────────────────────────────────────────────────────

SPRITE_COULEURS = {"encre": "currentColor", "ton2": TON2_SVG}
SPRITE_DEFAUT = {"stroke": "currentColor", "stroke-width": "2", "stroke-linecap": "round",
                 "stroke-linejoin": "round"}


def _attrs(t: Trace, couleurs, defaut):
    a = [("fill", couleurs.get(t.fill, t.fill) if t.fill else "none")]
    if t.stroke:
        a += [("stroke", couleurs.get(t.stroke, t.stroke)), ("stroke-width", n(t.sw)),
              ("stroke-linecap", t.cap), ("stroke-linejoin", t.join)]
    elif "stroke" in defaut:
        a.append(("stroke", "none"))
    if t.eo:
        a.append(("fill-rule", "evenodd"))
    if t.tf:
        a.append(("transform", t.tf))
    if t.op < 1:
        a.append(("opacity", n(t.op)))
    return " ".join(f'{k}="{v}"' for k, v in a if not (t.stroke and defaut.get(k) == v))


def svg_corps(dessin: Dessin, couleurs, defaut):
    return "".join(f'<path d="{t.d}" {_attrs(t, couleurs, defaut)}/>'.replace(" />", "/>")
                   for t in dessin.traces)


def svg_document(dessin: Dessin, couleurs=None, titre=None, vb=None):
    """SVG autonome (ornements) : couleurs figées, attributs de présentation seulement."""
    couleurs = couleurs or {"encre": ENCRE, "ton2": LAITON}
    vb = vb or (0, 0, dessin.l, dessin.h)
    t = f"<title>{titre}</title>" if titre else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(n(v) for v in vb)}" '
            f'width="{n(vb[2])}" height="{n(vb[3])}">{t}{svg_corps(dessin, couleurs, {})}</svg>\n')


# ── Outils de gravure : traits masqués, contours gonflés, tirets ─────────────────────────

def _d_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dans(forme: Forme):
    """Prédicat : le point est-il dans la région ?"""
    forme._preparer(ID)
    return lambda x, y: any(a <= x <= b for a, b in forme.intervalles(y))


def pres(d: str, r: float):
    """Prédicat : le point est-il à moins de r du tracé d ?"""
    segs = []
    for pts, ferme in aplatir(d, 0.1):
        q = pts + [pts[0]] if ferme else pts
        segs += [(a[0], a[1], b[0], b[1]) for a, b in zip(q, q[1:])]
    return lambda x, y: any(_d_seg(x, y, *s) <= r for s in segs)


def ou(*preds):
    return lambda x, y: any(p(x, y) for p in preds)


def et(*preds):
    return lambda x, y: all(p(x, y) for p in preds)


def _simplifier(pts, eps=0.03):
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    dmax, k = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = _d_seg(pts[i][0], pts[i][1], a[0], a[1], b[0], b[1])
        if d > dmax:
            dmax, k = d, i
    if dmax <= eps:
        return [a, b]
    return _simplifier(pts[:k + 1], eps)[:-1] + _simplifier(pts[k:], eps)


def masquer(d: str, cache, pas=0.12):
    """Le tracé d privé de ses parties cachées (cache(x, y) → True) : un objet passe derrière
    un autre avec le liseré blanc du graveur."""
    morceaux = []
    for pts, ferme in aplatir(d, pas):
        q = pts + [pts[0]] if ferme else pts
        cur = []
        for (x0, y0), (x1, y1) in zip(q, q[1:]):
            k = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / pas))
            for i in range(k):
                ax, ay = x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k
                bx, by = x0 + (x1 - x0) * (i + 1) / k, y0 + (y1 - y0) * (i + 1) / k
                if cache((ax + bx) / 2, (ay + by) / 2):
                    if len(cur) > 1:
                        morceaux.append(cur)
                    cur = []
                else:
                    if not cur:
                        cur = [(ax, ay)]
                    cur.append((bx, by))
        if len(cur) > 1:
            morceaux.append(cur)
    out = []
    for m in morceaux:
        m = _simplifier(m)
        if sum(math.dist(a, b) for a, b in zip(m, m[1:])) > 0.25:
            out.append("M" + "L".join(f"{n1(x)} {n1(y)}" for x, y in m))
    return "".join(out)


def gonfler(d: str, g: float, pas=0.15):
    """Contour décalé de g vers l'extérieur (formes lisses : têtes, bustes, ovales)."""
    out = []
    for pts, _ in aplatir(d, pas):
        if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        aire = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))
        s = 1 if aire > 0 else -1
        q = []
        for i in range(len(pts)):
            (ax, ay), (bx, by) = pts[i - 1], pts[(i + 1) % len(pts)]
            tx, ty = bx - ax, by - ay
            lg = math.hypot(tx, ty) or 1
            q.append((pts[i][0] + s * ty / lg * g, pts[i][1] - s * tx / lg * g))
        out.append(poly(q))
    return "".join(out)


def tirets(d: str, plein=1.2, vide=1.0, depart=0.0, pas=0.08):
    """Le tracé d en pointillés (segments séparés, sans stroke-dasharray)."""
    out = []
    for pts, ferme in aplatir(d, pas):
        q = pts + [pts[0]] if ferme else pts
        pos, cur = -depart, []
        periode = plein + vide
        for (x0, y0), (x1, y1) in zip(q, q[1:]):
            lg = math.hypot(x1 - x0, y1 - y0)
            k = max(1, math.ceil(lg / pas))
            for i in range(k):
                t = (i + 0.5) / k
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                visible = (pos % periode) < plein
                if visible:
                    cur.append((x, y))
                elif len(cur) > 1:
                    out.append(cur)
                    cur = []
                else:
                    cur = []
                pos += lg / k
        if len(cur) > 1:
            out.append(cur)
    return "".join("M" + "L".join(f"{n1(x)} {n1(y)}" for x, y in _simplifier(c)) for c in out)


def vague(x0, x1, y, amp=1.2, periode=6.0, phase=0.0):
    """Ligne de vagues (arcs de sinus approchés par des cubiques)."""
    pts = []
    k = max(8, int((x1 - x0) / periode * 12))
    for i in range(k + 1):
        x = x0 + (x1 - x0) * i / k
        pts.append((x, y - amp * math.sin(2 * math.pi * (x - x0) / periode + phase)))
    return "M" + "L".join(f"{n(a)} {n(b)}" for a, b in pts)


# ════════════════════════════════════════════════════════════════════════════════════════
#  Icônes du site — gravures 32 × 32 (encre = currentColor, ton2 = laiton/cire)
# ════════════════════════════════════════════════════════════════════════════════════════

ICONES: dict = {}


def icone(*noms):
    def deco(f):
        for nm in noms:
            ICONES[nm] = f
        return f
    return deco


def dessin_icone(nom: str) -> Dessin:
    d = Dessin(32, 32)
    ICONES[nom](d)
    return d


F = Forme


# ── Objets de bord ───────────────────────────────────────────────────────────────────────

@icone("ancre")
def _ancre(I):
    verge = poly([(15.0, 7.2), (17.0, 7.2), (17.6, 25.8), (14.4, 25.8)])
    reflet = poly([(15.55, 11.2), (15.95, 11.2), (15.7, 23.4), (15.25, 23.4)])
    I.plein(verge + reflet, eo=True)
    # cordage lâche passé dans l'organeau, qui s'enroule autour de la verge
    corde = "M18.3 4.9C24.6 6.6 23.6 13.2 17.2 14.1C11.4 15 10.6 20.6 15.2 22.6"
    I.trait(masquer(corde, dans(F(gonfler(verge, 0.9)) & F(rect(0, 15.6, 32, 4)))), 1.15)
    I.trait("M5.4 17.2C5.9 23.3 10.3 27.3 16 27.3C21.7 27.3 26.1 23.3 26.6 17.2", 2.3)
    I.plein(poly([(14.3, 26.2), (17.7, 26.2), (16, 29.6)]))
    for s in (1, -1):  # pattes (en fer de flèche)
        x = 16 - s * 10.6
        I.plein(poly([(x, 12.9), (x - s * 2.9, 19.3), (x + s * 0.2, 17.6), (x + s * 3.2, 18.9)]))
    I.ton_trait(rect(8.7, 8.3, 14.6, 2.6, 1.3), 1.4)
    I.plein(cercle(8.1, 9.6, 1.45))
    I.plein(cercle(23.9, 9.6, 1.45))
    I.trait(cercle(16, 4.5, 2.35), 1.8)


@icone("boussole")
def _boussole(I):
    c = (16, 18)
    I.trait(cercle(16, 3.5, 1.55), 1.5)
    I.plein(rect(14.9, 5.1, 2.2, 1.5, 0.3))
    I.ton(cercle(*c, 11.7) + cercle(*c, 9.3), eo=True)
    I.hach(F(cercle(*c, 11.7)) - F(cercle(*c, 9.3)) & F(rect(16, 18, 14, 14)), 45, 1.6)
    I.trait(cercle(*c, 11.7), 2)
    I.trait(cercle(*c, 9.3), 1.2)
    for k in range(16):
        a = math.radians(k * 22.5)
        r0 = 6.4 if k % 4 == 0 else 7.6
        I.trait(ligne(16 + r0 * math.sin(a), 18 - r0 * math.cos(a),
                      16 + 8.6 * math.sin(a), 18 - 8.6 * math.cos(a)), 1.1 if k % 4 == 0 else 0.8)
    tf = "rotate(28 16 18)"
    I.plein(poly([(16, 10.4), (18.3, 18), (13.7, 18)]), tf=tf)
    I.trait(poly([(13.7, 18), (16, 25.6), (18.3, 18)]), 1.2, tf=tf)
    I.ton_trait(cercle(16, 18, 1.35), 1)


@icone("longue_vue")
def _longue_vue(I):
    tf = "rotate(-38 16 16)"
    I.plein(rect(2.1, 13.9, 2.7, 4.2, 0.8), tf=tf)
    for x, l, r in ((4.6, 6.6, 2.15), (12.9, 6.7, 2.75), (21.3, 6.3, 3.45)):
        tube = rect(x, 16 - r, l, 2 * r)
        I.hach(F(tube, tf=tf) & F(rect(0, 16.5, 32, 8), tf=tf), -38, 1.3, sw=0.75, marge=0.35)
        I.trait(tube, 1.65, tf=tf)
    for x, l, r in ((11, 2, 3.05), (19.4, 2, 3.75), (27.4, 2.4, 4.4)):
        I.ton_trait(rect(x, 16 - r, l, 2 * r, 0.5), 1.4, tf=tf)


@icone("cloche")
def _cloche(I):
    I.trait("M13.4 6.5C13.4 2.5 18.6 2.5 18.6 6.5", 1.8)
    I.plein(rect(12.8, 5.9, 6.4, 2.3, 0.7))
    corps = ("M10.7 9.1C12.6 7.6 19.4 7.6 21.3 9.1C22.4 10.4 22.6 15 23 19C23.3 21.4 24.6 22.6 26.4 23.4"
             "L26.4 25.3L5.6 25.3L5.6 23.4C7.4 22.6 8.7 21.4 9 19C9.4 15 9.6 10.4 10.7 9.1Z")
    I.ton(corps)
    I.hach(F(corps) & F(rect(18.6, 7, 10, 19)), 78, 1.55, sw=0.8)
    I.trait("M9.9 11.6C13.5 12.7 18.5 12.7 22.1 11.6", 1.1)
    I.trait("M8.9 20.3C13 21.5 19 21.5 23.1 20.3", 1.1)
    I.trait(corps, 1.9)
    I.plein(cercle(16, 27.5, 1.75))


@icone("navire")
def _navire(I):
    I.trait(vague(1.6, 30.4, 28.2, 0.9, 5.6), 1.35)
    coque = "M3.1 18.3L28.9 18.3C27.7 21.8 25.4 24.4 21.8 25.2L9.6 25.2C6.6 24.6 4.3 22.4 3.1 18.3Z"
    I.plein(coque)
    I.ton(poly([(3.65, 19.7), (28.35, 19.7), (27.85, 20.85), (4.05, 20.85)]))
    I.trait(rect(3.1, 15.3, 6.6, 3), 1.4)
    I.trait(ligne(27.6, 18.4, 31, 15.2), 1.4)
    I.trait(ligne(15.6, 18.3, 15.6, 2.8), 1.4)
    I.trait(ligne(23.4, 18.3, 23.4, 6.6), 1.4)
    I.trait(ligne(6.6, 15.3, 6.6, 9), 1.2)
    grand = "M10.4 5.4L20.6 5.4C21.7 8.9 21.7 12 20.6 15.4L10.4 15.4C11.5 12 11.5 8.9 10.4 5.4Z"
    misaine = "M20.9 8.6L26.3 8.6C27.2 11 27.2 13.3 26.3 15.7L20.9 15.7C21.8 13.3 21.8 11 20.9 8.6Z"
    for v, x0 in ((grand, 18.8), (misaine, 25)):
        I.hach(F(v) & F(rect(x0, 0, 10, 20)), 90, 1.25, sw=0.6, marge=0.5)
        I.trait(v, 1.45)
    I.trait(poly([(24.4, 7.4), (30.3, 16.3), (24.4, 16.3)], False), 1.15)
    I.plein(poly([(15.6, 2.6), (20.6, 3.7), (15.6, 4.8)]))


@icone("drapeau")
def _drapeau(I):
    I.trait(ligne(6, 3.4, 6, 29.6), 2)
    I.plein(cercle(6, 2.7, 1.35))
    toile = ("M7 4.4C11.5 2.9 15 6 19.5 4.8C23 3.9 26 3.6 28.7 4.6L28.7 18.2"
             "C26 17.2 23 17.6 19.5 18.6C15 19.8 11.5 17 7 18.4Z")
    I.plein(toile)
    for a, b in (((13.7, 12.9), (21.7, 16.6)), ((21.7, 12.9), (13.7, 16.6))):
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        lg = math.dist(a, b)
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        I.ton(rect(cx - lg / 2, cy - 0.55, lg, 1.1, 0.5), tf=f"rotate({n(ang)} {n(cx)} {n(cy)})")
        for p in (a, b):
            I.ton(cercle(p[0], p[1] - 0.5, 0.75))
            I.ton(cercle(p[0], p[1] + 0.5, 0.75))
    I.ton("M14.4 10C14.4 7.9 15.9 6.6 17.7 6.6C19.5 6.6 21 7.9 21 10C21 11.2 20.5 11.9 19.8 12.3"
          "L19.8 13.9L15.6 13.9L15.6 12.3C14.9 11.9 14.4 11.2 14.4 10Z")
    I.plein(cercle(16.4, 10.1, 0.95))
    I.plein(cercle(19, 10.1, 0.95))
    I.plein(poly([(17.7, 11.3), (18.2, 12.4), (17.2, 12.4)]))


@icone("sabre")
def _sabre(I):
    tf = "rotate(-40 16 16)"
    lame = "M11.6 14.6C17 14.2 23.5 13.1 29.6 11.2C28.6 13.6 26.8 15.6 24.4 16.8C20 18.2 15.6 18.2 11.6 18Z"
    I.trait(lame, 1.55, tf=tf)
    I.trait("M12.6 15.6C17.2 15.3 22.2 14.4 26.8 13", 0.8, tf=tf)
    I.trait("M10.8 21C8.3 23.7 4.1 23.3 2.7 19.3", 1.4, tf=tf)
    poignee = rect(4.3, 14.5, 6.1, 3.9, 1.4)
    I.hach(F(poignee, tf=tf), 30, 1.25, sw=0.75, marge=0.2)
    I.trait(poignee, 1.4, tf=tf)
    I.ton_trait("M11.8 11.4C13.5 13.3 13.5 19.7 11.8 21.6L10.1 21.6C11.2 19.7 11.2 13.3 10.1 11.4Z", 1.3, tf=tf)
    I.ton_trait(cercle(3.2, 16.45, 1.75), 1.2, tf=tf)


@icone("canon")
def _canon(I):
    affut = poly([(4.4, 25.2), (4.4, 21.4), (9, 21.4), (9, 18.9), (13.6, 18.9), (13.6, 16.8),
                  (24.4, 18.4), (26.4, 25.2)])
    I.ton(affut)
    I.hach(F(affut) & F(rect(0, 21.6, 32, 4)), 45, 1.5, sw=0.75)
    I.trait(affut, 1.5)
    tf = "translate(7 14.4) rotate(-12)"
    fut = ("M0 -3.3L20.4 -2.25L20.4 -2.9L23.4 -2.9L23.4 2.9L20.4 2.9L20.4 2.25L0 3.3"
           "C-1.9 3.1 -1.9 -3.1 0 -3.3Z")
    I.plein(fut, tf=tf)
    I.plein(cercle(-2.7, 0, 1.3), tf=tf)
    I.ton(rect(5.2, -3.15, 1.1, 6.3), tf=tf)
    I.ton(rect(13.4, -2.75, 1, 5.5), tf=tf)
    for x in (10.2, 22.4):
        I.ton_trait(cercle(x, 25.4, 3.1), 1.7)
        I.plein(cercle(x, 25.4, 0.95))


@icone("coffre")
def _coffre(I):
    couvercle = "M4 14L4 11C4 6.5 8 4.6 16 4.6C24 4.6 28 6.5 28 11L28 14Z"
    caisse = rect(4, 14, 24, 14)

    def haut(x):
        ys = []
        for pts, _ in aplatir(couvercle, 0.1):
            for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
                if min(x0, x1) <= x <= max(x0, x1) and x0 != x1:
                    ys.append(y0 + (x - x0) * (y1 - y0) / (x1 - x0))
        return min(ys)

    I.hach(F(couvercle) & F(rect(19.4, 0, 13, 32)), 45, 1.5, sw=0.75)
    I.hach(F(caisse) & F(rect(19.4, 14, 13, 15)), 45, 1.5, sw=0.75)
    I.trait(couvercle, 1.9)
    I.trait(caisse, 1.9)
    for x in (7.6, 22):
        pts = [(x + i * 0.6, haut(x + i * 0.6)) for i in range(5)]
        I.ton_trait(poly(pts + [(x + 2.4, 28), (x, 28)]), 1.15)
    I.ton_trait("M13.3 12.3H18.7V17.3C18.7 19.2 17.4 20 16 20.7C14.6 20 13.3 19.2 13.3 17.3Z", 1.25)
    I.plein("M15.3 18.6L15.75 16.5A1.15 1.15 0 1 1 16.25 16.5L16.7 18.6Z")


@icone("cle")
def _cle(I):
    tf = "rotate(40 16 16)"
    for a in (125, 180, 235):
        x, y = 7.2 + 4.3 * math.cos(math.radians(a)), 16 + 4.3 * math.sin(math.radians(a))
        I.ton_trait(cercle(x, y, 1.5), 1.1, tf=tf)
    I.ton(cercle(7.2, 16, 4.4) + cercle(7.2, 16, 2.1), eo=True, tf=tf)
    I.trait(cercle(7.2, 16, 4.4), 1.8, tf=tf)
    I.trait(cercle(7.2, 16, 2.1), 1.2, tf=tf)
    I.trait(ligne(11.6, 16, 27.2, 16), 2.3, tf=tf)
    I.ton_trait(rect(11.6, 14.4, 1.8, 3.2, 0.5), 1.1, tf=tf)
    I.plein(rect(14.1, 14.9, 1.1, 2.2, 0.3), tf=tf)
    I.plein("M22.6 16.4V21.8H24.4V19.9H25.7V21.8H27.5V16.4Z", tf=tf)
    I.plein(cercle(27.8, 16, 1.05), tf=tf)


@icone("cadenas")
def _cadenas(I):
    I.trait("M10.6 15V10.2A5.4 5.4 0 0 1 21.4 10.2V15", 2.7)
    corps = rect(6.4, 13.2, 19.2, 15.6, 3.4)
    I.ton(corps)
    I.hach(F(corps) & F(rect(19.8, 13, 8, 17)), 60, 1.45, sw=0.75)
    I.trait(corps, 1.9)
    I.plein("M14.25 25L15.15 20.9A1.95 1.95 0 1 1 16.85 20.9L17.75 25Z")
    for x, y in ((9.2, 16), (22.8, 16), (9.2, 26), (22.8, 26)):
        I.plein(cercle(x, y, 0.75))


@icone("minuteur")
def _minuteur(I):
    I.trait(ligne(8.4, 6, 8.4, 26), 1.3)
    I.trait(ligne(23.6, 6, 23.6, 26), 1.3)
    I.plein("M12.3 10.6H19.7C18.9 12.6 16.8 13.9 16.3 15.7L15.7 15.7C15.2 13.9 13.1 12.6 12.3 10.6Z")
    I.trait(ligne(16, 15.9, 16, 22), 0.75)
    I.plein("M11.7 25.7C12.6 22.7 14.6 21.7 16 21.5C17.4 21.7 19.4 22.7 20.3 25.7Z")
    I.trait("M11 6.2C11 11.5 15 13.4 15 16C15 18.6 11 20.5 11 25.8", 1.5)
    I.trait("M21 6.2C21 11.5 17 13.4 17 16C17 18.6 21 20.5 21 25.8", 1.5)
    I.ton_trait(rect(5.8, 3, 20.4, 3.3, 1), 1.4)
    I.ton_trait(rect(5.8, 25.7, 20.4, 3.3, 1), 1.4)



# ── Courbes organiques (sceaux, taches, côtes) ───────────────────────────────────────────

def lisse(pts, ferme=True):
    """Courbe de Catmull-Rom passant par les points, écrite en cubiques SVG."""
    k = len(pts)
    if k < 3:
        return poly(pts, ferme)
    out = [f"M{n(pts[0][0])} {n(pts[0][1])}"]
    der = k if ferme else k - 1
    for i in range(der):
        p0 = pts[(i - 1) % k] if (ferme or i > 0) else pts[0]
        p1, p2 = pts[i], pts[(i + 1) % k]
        p3 = pts[(i + 2) % k] if (ferme or i + 2 < k) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        out.append(f"C{n(c1[0])} {n(c1[1])} {n(c2[0])} {n(c2[1])} {n(p2[0])} {n(p2[1])}")
    return "".join(out) + ("Z" if ferme else "")


def cachet_pts(cx, cy, r, graine=3, lobes=7, amp=0.07, k=28):
    """Contour d'une cire coulée : un cercle aux bords bosselés, irrégulier mais stable."""
    rnd = random.Random(graine)
    ph = [rnd.uniform(0, 2 * math.pi) for _ in range(3)]
    pts = []
    for i in range(k):
        a = 2 * math.pi * i / k
        f = (1 + amp * math.sin(lobes * a + ph[0]) + amp * 0.55 * math.sin((lobes + 4) * a + ph[1])
             + amp * 0.35 * math.sin(3 * a + ph[2]))
        pts.append((cx + r * f * math.cos(a), cy + r * f * math.sin(a)))
    return pts


def cachet(cx, cy, r, graine=3, lobes=7, amp=0.07):
    return lisse(cachet_pts(cx, cy, r, graine, lobes, amp))


# ── Papiers, livres et écritures ─────────────────────────────────────────────────────────

@icone("parchemin")
def _parchemin(I):
    feuille = poly([(9.4, 7), (22.6, 7), (22.6, 25), (9.4, 25)])
    I.hach(F(feuille) & F(rect(0, 7.6, 32, 2.2)), 0, 0.9, sw=0.6, marge=0.2)
    I.trait(ligne(9.4, 7.6, 9.4, 24.6), 1.6)
    I.trait(ligne(22.6, 7.6, 22.6, 24.6), 1.6)
    for y, x1 in ((12, 20.4), (15, 19.4), (18, 20.4), (21, 17.2)):
        I.trait(ligne(11.8, y, x1, y), 1.05)
    haut = rect(8.8, 3.4, 17, 4.6, 2.3)
    bas = rect(6.2, 24, 17, 4.6, 2.3)
    for r in (haut, bas):
        I.hach(F(r) & F(rect(0, 5.7 if r is haut else 26.3, 32, 3)), 0, 0.95, sw=0.6, marge=0.3)
        I.trait(r, 1.6)
    for cx, cy in ((8.8, 5.7), (23.2, 26.3)):
        I.ton_trait(cercle(cx, cy, 2.3), 1.5)
        I.trait(f"M{n(cx)} {n(cy - 1)}A1 1 0 1 1 {n(cx - 0.9)} {n(cy + 0.4)}", 0.9)


@icone("plume")
def _plume(I):
    tf = "translate(11.6 19.4) rotate(-47)"
    barbe = "M5.6 0C9.6 -4.2 17 -5.6 24.6 -0.6C18.2 1.7 11 2.4 5.6 0Z"
    I.hach(F(barbe, tf=tf), -10, 1.25, sw=0.7, marge=0.35)
    I.trait(barbe, 1.4, tf=tf)
    I.trait("M-1.5 0L24.4 -0.5", 1.25, tf=tf)
    I.trait("M9.5 -2.7L8.7 -3.9M15 -4L14.6 -5.1", 1, tf=tf)
    encrier = ("M6.1 29.2H17.3C18.1 29.2 18.5 28.6 18.3 27.8L16.9 22.2C16.7 21.6 16.2 21.2 15.6 21.2"
               "H7.8C7.2 21.2 6.7 21.6 6.5 22.2L5.1 27.8C4.9 28.6 5.3 29.2 6.1 29.2Z")
    I.plein(encrier + poly([(7.6, 23.2), (8.3, 23.2), (7.6, 27.4), (6.9, 27.4)]), eo=True)
    I.ton_trait(rect(8.7, 18.5, 6, 2.9, 0.7), 1.2)


@icone("carte")
def _carte(I):
    feuille = poly([(3.4, 7.2), (11.2, 4.8), (19.8, 7.6), (28.6, 5.2), (28.6, 25.4), (19.8, 27.8),
                    (11.2, 25.2), (3.4, 27.6)])
    I.hach(F(poly([(11.2, 4.8), (19.8, 7.6), (19.8, 27.8), (11.2, 25.2)])), 60, 1.6, sw=0.7)
    I.trait(ligne(11.2, 4.8, 11.2, 25.2), 1.1)
    I.trait(ligne(19.8, 7.6, 19.8, 27.8), 1.1)
    I.trait(feuille, 1.8)
    I.trait(tirets("M6.4 22.6C8.6 15.6 12.6 21.4 15.4 14.8S20.8 11.6 22.6 15.2", 1.3, 1.05), 1.25)
    I.trait("M22.7 16.4L26.5 20.2M26.5 16.4L22.7 20.2", 2.1)


@icone("journal")
def _journal(I):
    I.trait("M25.2 4.2H26.7V29.5H8.2V28.2", 1.3)
    couv = rect(6.4, 2.6, 18.8, 25.6, 1.3)
    I.trait(couv, 1.9)
    I.plein("M9.9 2.6V28.2H7.7C6.98 28.2 6.4 27.62 6.4 26.9V3.9C6.4 3.18 6.98 2.6 7.7 2.6Z")
    I.trait(rect(12.4, 7.2, 9, 5.4, 0.6), 1.15)
    I.trait(ligne(14.2, 9.9, 19.6, 9.9), 1)
    I.ton_trait(poly([(20.4, 2.6), (25.2, 2.6), (25.2, 7.4)]), 1.1)
    I.ton_trait(poly([(25.2, 23.4), (25.2, 28.2), (20.4, 28.2)]), 1.1)
    I.ton_trait(rect(20.2, 14, 7, 3.8, 0.8), 1.3)
    I.plein(cercle(23.8, 15.9, 0.75))


@icone("repertoire")
def _repertoire(I):
    for y in (5.6, 12.6, 19.6):
        I.ton_trait(f"M23.6 {n(y)}H27.2A1.3 1.3 0 0 1 28.5 {n(y + 1.3)}V{n(y + 2.5)}"
                    f"A1.3 1.3 0 0 1 27.2 {n(y + 3.8)}H23.6Z", 1.2)
    livre = rect(4.6, 3.2, 19.6, 25.6, 1.3)
    I.trait(livre, 1.9)
    I.plein("M8 3.2V28.8H5.9C5.18 28.8 4.6 28.22 4.6 27.5V4.5C4.6 3.78 5.18 3.2 5.9 3.2Z")
    I.trait("M11.2 21.4L15.6 9L20 21.4M12.7 17.3H18.5", 2)


@icone("catalogue")
def _catalogue(I):
    g = "M16 8.3C12.6 6.4 8 6.1 3.3 7.5V25.3C8 23.9 12.6 24.2 16 26.1Z"
    d = "M16 8.3C19.4 6.4 24 6.1 28.7 7.5V25.3C24 23.9 19.4 24.2 16 26.1Z"
    I.trait("M3.3 25.3V27.1C8 25.7 12.6 26 16 27.9C19.4 26 24 25.7 28.7 27.1V25.3", 1.35)
    I.hach(F(d) & F(rect(16, 0, 2.6, 32)), 90, 0.9, sw=0.6, marge=0.4)
    I.trait(g, 1.7)
    I.trait(d, 1.7)
    for i, (x, y) in enumerate(((6, 10.6), (10.6, 10.4), (6, 15.4), (10.6, 15.2))):
        r = rect(x, y, 3.5, 3.5, 0.6)
        if i == 1:
            I.ton_trait(r, 1.1)
        else:
            I.trait(r, 1.1)
    I.trait(ligne(6, 21.6, 13.6, 21.2), 1)
    for y in (11.2, 14.2, 17.2, 20.2):
        I.trait(ligne(18.8, y, 26.2 if y != 20.2 else 22.6, y - 0.25), 1)


@icone("fiches")
def _fiches(I):
    devant = rect(4, 9, 18.6, 19.6, 1.2)
    der = rect(10, 3.6, 18.6, 19.6, 1.2)
    I.hach(F(der) - F(gonfler(devant, 1.1)), 45, 1.55, sw=0.7)
    I.trait(masquer(der, dans(F(gonfler(devant, 1.1)))), 1.6)
    I.trait(devant, 1.9)
    I.trait(rect(6.8, 12, 6.8, 7.4, 0.5), 1.2)
    I.plein(cercle(10.2, 14.6, 1.65))
    I.plein("M7.7 19.4C7.9 17.5 8.9 16.8 10.2 16.8C11.5 16.8 12.5 17.5 12.7 19.4Z")
    for x0, y, x1 in ((15.6, 13.2, 20.2), (15.6, 16.1, 19.6), (15.6, 19, 20.2), (6.8, 22.6, 20.2),
                      (6.8, 25.3, 16.2)):
        I.trait(ligne(x0, y, x1, y), 1.05)


@icone("candidatures")
def _candidatures(I):
    env = rect(3.4, 7.6, 25.2, 17.6, 1)
    I.hach(F(poly([(3.8, 24.8), (12.6, 17.2), (19.4, 17.2), (28.2, 24.8)])), 45, 1.6, sw=0.7)
    I.trait("M3.9 24.7L12.6 17.1M28.1 24.7L19.4 17.1", 1.1)
    I.trait("M3.9 8.1L16 18L28.1 8.1", 1.5)
    I.trait(env, 1.9)
    s = cachet(16, 18.2, 3.9, graine=11)
    I.ton_trait(s, 1.4)
    I.trait(cercle(16, 18.2, 2.1), 0.9)
    I.plein(poly(etoile_pts(16, 18.2, 1.25, 0.55, 5)))


@icone("affiches")
def _affiches(I):
    tf = "rotate(-4 16 16)"
    papier = "M6.2 3.6H25.8V24.6L24.3 25.5L25.1 26.8L23.2 28.3L21.4 27.6L19.8 28.6H6.2Z"
    I.hach(F("M25.8 24.6L24.3 25.5L25.1 26.8L23.2 28.3L21.4 27.6L19.8 28.6H25.8Z", tf=tf), 45, 1.1, sw=0.6, marge=0.2)
    I.trait(papier, 1.9, tf=tf)
    I.plein(rect(9.2, 7, 13.6, 3.4, 0.4), tf=tf)
    I.trait(rect(10, 12.2, 12, 9.2), 1.2, tf=tf)
    I.plein(cercle(16, 15.5, 2.15), tf=tf)
    I.plein("M12.2 21.4C12.6 18.8 14 18 16 18C18 18 19.4 18.8 19.8 21.4Z", tf=tf)
    I.trait(ligne(9.6, 24, 21, 24), 1.7, tf=tf)
    I.trait(ligne(11.6, 26.4, 18.4, 26.4), 1, tf=tf)
    for x in (8.4, 23.6):
        I.ton_trait(cercle(x, 5.3, 1.05), 0.8, tf=tf)


@icone("calendrier")
def _calendrier(I):
    I.trait(rect(4, 6, 24, 22.6, 2), 1.9)
    I.plein("M4 11.6V8A2 2 0 0 1 6 6H26A2 2 0 0 1 28 8V11.6Z")
    for x in (9.2, 20.6):
        I.ton_trait(rect(x, 2.8, 2.2, 5.8, 1.1), 1.1)
    for j, y in enumerate((14.2, 18.6, 23)):
        for i, x in enumerate((7.3, 12.1, 16.9, 21.7)):
            r = rect(x, y, 2.9, 2.9, 0.5)
            if (i, j) == (2, 1):
                I.ton_trait(rect(x - 0.4, y - 0.4, 3.7, 3.7, 0.7), 1.1)
            else:
                I.plein(r)


@icone("copier")
def _copier(I):
    devant = "M4.4 9H17.6L21.6 13V28.6H4.4Z"
    der = rect(10.4, 3.4, 17.2, 19.6, 1.2)
    I.hach(F(der) - F(gonfler(devant, 1.1)), 45, 1.55, sw=0.7)
    I.trait(masquer(der, dans(F(gonfler(devant, 1.1)))), 1.6)
    I.trait(devant, 1.9)
    I.ton_trait("M17.6 9V13H21.6Z", 1.1)
    for y, x1 in ((17, 18.4), (20.5, 17.4), (24, 18.4)):
        I.trait(ligne(7.4, y, x1, y), 1.05)


@icone("tickets")
def _tickets(I):
    tf = "rotate(-35 16 15)"
    flacon = ("M4 11.4H19.2C21 11.4 21.8 13.4 23.4 13.9H26.4V18.1H23.4C21.8 18.6 21 20.6 19.2 20.6"
              "H4C2.6 20.6 1.8 19.6 1.8 18.2V13.8C1.8 12.4 2.6 11.4 4 11.4Z")
    rouleau = rect(5, 13.5, 13.4, 5, 2.5)
    I.hach(F(flacon, tf=tf) & F(rect(0, 18.4, 30, 4), tf=tf) - F(gonfler(rouleau, 0.6), tf=tf),
           55, 1.3, sw=0.65, marge=0.3)
    I.trait("M4.4 12.9H18", 0.8, tf=tf)
    I.trait(rouleau, 1.25, tf=tf)
    I.ton(rect(10.8, 13.1, 1.9, 5.8, 0.3), tf=tf)
    I.trait(rect(10.8, 13.1, 1.9, 5.8, 0.3), 0.9, tf=tf)
    I.trait(flacon, 1.8, tf=tf)
    I.plein(rect(26.3, 13.2, 1.5, 5.6, 0.5), tf=tf)
    I.ton_trait(rect(27.7, 13.8, 2.9, 4.4, 0.7), 1.1, tf=tf)
    I.trait(vague(2, 13, 28.6, 0.8, 5.5), 1.2)


# ── Gens, lieux et rubriques ─────────────────────────────────────────────────────────────

def _buste(cx, tete_y, r, epaule_y, larg, bas=29.2):
    tete = cercle(cx, tete_y, r)
    epaules = (f"M{n(cx - larg)} {n(bas)}C{n(cx - larg)} {n(epaule_y + 3.6)} {n(cx - larg * 0.55)} "
               f"{n(epaule_y)} {n(cx)} {n(epaule_y)}C{n(cx + larg * 0.55)} {n(epaule_y)} {n(cx + larg)} "
               f"{n(epaule_y + 3.6)} {n(cx + larg)} {n(bas)}Z")
    return tete, epaules


def _graver_buste(I, tete, epaules, cx, ombre=1.4, cache=None, sw=1.9):
    for f in (tete, epaules):
        zone = F(f) & F(rect(cx + ombre, 0, 30, 40))
        if cache is not None:
            zone = zone - cache
        I.hach(zone, 45, 1.5, sw=0.75)
    for f in (tete, epaules):
        I.trait(f if cache is None else masquer(f, dans(cache)), sw)


@icone("personne")
def _personne(I):
    tete, epaules = _buste(16, 10.6, 5.3, 18.8, 10.8)
    _graver_buste(I, tete, epaules, 16)
    I.trait("M13.2 19.1L16 22.4L18.8 19.1", 1.25)


@icone("membres")
def _membres(I):
    t1, e1 = _buste(12, 12.6, 4.5, 20.4, 9.4)
    t2, e2 = _buste(21.6, 8.8, 3.9, 15.8, 8.2, bas=25.4)
    devant = F(gonfler(t1, 1.1)) | F(gonfler(e1, 1.1))
    _graver_buste(I, t2, e2, 21.6, 1.2, cache=devant, sw=1.6)
    _graver_buste(I, t1, e1, 12)


@icone("equipage")
def _equipage(I):
    t1, e1 = _buste(12.2, 15.8, 4.1, 21.3, 9.4, bas=29.4)
    t2, e2 = _buste(21.8, 10.2, 3.7, 16.9, 7.8, bas=25.2)
    chapeau = ("M3.6 9C6.5 10 9.4 11.4 12.2 13.3C15 11.4 17.9 10 20.8 9C19.4 7.5 17.8 6.8 16.3 6.8"
               "C15.7 5.1 14.1 4.3 12.2 4.3C10.3 4.3 8.7 5.1 8.1 6.8C6.6 6.8 5 7.5 3.6 9Z")
    devant = F(gonfler(t1, 1.05)) | F(gonfler(e1, 1.05)) | F(gonfler(chapeau, 1.05))
    _graver_buste(I, t2, e2, 21.8, 1.1, cache=devant, sw=1.6)
    foulard = "M17.9 10C18.1 7.1 19.7 5.9 21.8 5.9C23.9 5.9 25.5 7.1 25.7 10C24.2 9.1 19.4 9.1 17.9 10Z"
    noeud = poly([(25.2, 8.6), (28, 7.4), (27.3, 9.3), (28.2, 11)])
    for f in (foulard, noeud):
        I.ton(f)
        I.trait(masquer(f, dans(devant)), 1.1)
    _graver_buste(I, t1, e1, 12.2)
    I.plein(chapeau)
    I.ton("M5.6 9.5C8 10.3 10.2 11.4 12.2 12.7C14.2 11.4 16.4 10.3 18.8 9.5C16.6 9.7 14.3 10.6 12.2 11.9C10.1 10.6 7.8 9.7 5.6 9.5Z")


@icone("capitainerie")
def _capitainerie(I):
    c = 16
    for k in range(8):
        a = math.radians(k * 45 - 90)
        co, si = math.cos(a), math.sin(a)
        I.trait(ligne(c + 2.6 * co, c + 2.6 * si, c + 8.6 * co, c + 8.6 * si), 1.5)
        I.trait(ligne(c + 9.6 * co, c + 9.6 * si, c + 12.3 * co, c + 12.3 * si), 2.4)
        I.plein(cercle(c + 13.25 * co, c + 13.25 * si, 1.3))
    jante = cercle(c, c, 9.5) + cercle(c, c, 7.3)
    I.ton(jante, eo=True)
    I.hach(F(cercle(c, c, 9.5)) - F(cercle(c, c, 7.3)) & F(rect(c, c - 2, 14, 14)), 45, 1.3, sw=0.7)
    I.trait(cercle(c, c, 9.5), 1.8)
    I.trait(cercle(c, c, 7.3), 1.2)
    I.ton_trait(cercle(c, c, 2.8), 1.4)
    I.plein(cercle(c, c, 0.95))


@icone("port")
def _port(I):
    def bord(y, cote):
        t = (y - 11.4) / (25.6 - 11.4)
        return (12.8 + (11 - 12.8) * t) if cote < 0 else (19.2 + (21 - 19.2) * t)
    tour = poly([(11, 25.6), (21, 25.6), (19.2, 11.4), (12.8, 11.4)])
    I.hach(F(tour) & F(rect(17.6, 0, 10, 32)), 45, 1.4, sw=0.7)
    for y0, y1 in ((14, 17), (20, 23)):
        I.plein(poly([(bord(y0, -1), y0), (bord(y0, 1), y0), (bord(y1, 1), y1), (bord(y1, -1), y1)]))
    I.trait(tour, 1.8)
    I.trait("M14.8 25.6V23.7A1.2 1.2 0 0 1 17.2 23.7V25.6", 1.1)
    rochers = ("M2.8 29.6C3.8 27.1 5.9 26.4 7.9 26.8C9 25.4 11 25 12.6 25.6H19.4C21 25 23 25.4 24.1 26.8"
               "C26.1 26.4 28.2 27.1 29.2 29.6Z")
    I.hach(F(rochers) & F(rect(0, 27.4, 32, 4)), 45, 1.3, sw=0.7)
    I.trait(rochers, 1.5)
    I.plein(rect(11.1, 10.1, 9.8, 1.7, 0.4))
    I.ton_trait(rect(13.3, 5.9, 5.4, 4.3), 1.35)
    I.trait(ligne(15.1, 6.2, 15.1, 9.9), 0.85)
    I.trait(ligne(16.9, 6.2, 16.9, 9.9), 0.85)
    I.plein("M12.5 6.1L16 2.5L19.5 6.1Z")
    I.plein(cercle(16, 2.2, 0.8))
    for s in (-1, 1):
        for y0, y1 in ((6.9, 5.2), (8.1, 8.1), (9.3, 11)):
            I.trait(ligne(16 + s * 4.4, y0, 16 + s * 9, y1), 1.1)


@icone("apercu")
def _apercu(I):
    c = 16
    I.trait(cercle(c, c, 10.2), 0.85)
    for k in range(8):
        a = math.radians(k * 45 - 90 + 45)
        if k % 2 == 1:
            continue
        lg, lw = 8.4, 2.1
        _pointe_rose(I, c, a, lg, lw, court=True)
    for k in range(4):
        _pointe_rose(I, c, math.radians(k * 90 - 90), 13.6, 2.7)
    I.ton_trait(cercle(c, c, 1.6), 1.1)


def _pointe_rose(I, c, a, lg, lw, court=False):
    co, si = math.cos(a), math.sin(a)
    pointe = (c + lg * co, c + lg * si)
    g = (c - lw * si, c + lw * co)
    d = (c + lw * si, c - lw * co)
    if court:
        I.ton(poly([pointe, (c, c), g]))
        I.plein(poly([pointe, (c, c), d]))
    else:
        I.plein(poly([pointe, (c, c), g]))
        I.ton(poly([pointe, (c, c), d]))
    I.trait(poly([pointe, g, (c, c), d]), 1.15)


@icone("salons")
def _salons(I):
    def bord(y, cote):
        t = (y - 10) / (28.4 - 10)
        return (7.2 + (6.4 - 7.2) * t) if cote < 0 else (20.8 + (21.6 - 20.8) * t)
    corps = "M7.2 10H20.8L21.6 27.2C21.6 27.9 21.1 28.4 20.4 28.4H7.6C6.9 28.4 6.4 27.9 6.4 27.2Z"
    I.trait("M21 13.4C27.6 12.8 28.4 23.4 21.4 24.2", 2.5)
    I.hach(F(corps) & F(rect(17.4, 0, 10, 32)), 45, 1.4, sw=0.7)
    for x in (10.6, 14, 17.4):
        I.trait(ligne(x, 15.2, x - 0.1 * (x - 14), 22.6), 0.85)
    for y0, y1 in ((12.2, 14.4), (23.4, 25.6)):
        I.ton_trait(poly([(bord(y0, -1), y0), (bord(y0, 1), y0), (bord(y1, 1), y1), (bord(y1, -1), y1)]), 1.1)
    I.trait(corps, 1.8)
    mousse = ("M6.6 10.2C5.2 9.8 4.9 7.9 6.2 7.2C6 5.2 8.3 4.3 9.7 5.5C10.6 3.8 13.5 3.8 14.5 5.5"
              "C15.7 4.3 18.4 4.6 18.8 6.6C20.6 6.4 22 8.1 21.4 10.1")
    I.trait(mousse, 1.6)
    I.trait("M17.2 10.2C17.4 11.8 17 12.6 16.3 12.6C15.6 12.6 15.3 11.8 15.5 10.4", 1.15)


@icone("annonces")
def _annonces(I):
    cone = "M5.2 14.4L20.6 8C22.6 12.4 22.6 19.6 20.6 24L5.2 17.6Z"
    I.trait("M8.6 18.9C8.4 22.6 13.6 22.8 13.4 19.9", 1.5)
    I.ton(cone)
    I.hach(F(cone) & F(rect(0, 16.6, 30, 10)), 75, 1.4, sw=0.7)
    I.trait(ligne(10.2, 12.5, 10.2, 19.5), 1.1)
    I.trait(cone, 1.7)
    I.trait(ellipse(21.2, 16, 1.9, 8.2), 1.5)
    I.plein(ellipse(21.5, 16, 1.05, 6.8))
    I.plein(rect(2.4, 14.6, 3.1, 2.8, 0.6))
    I.trait("M25.2 12.5C26.6 14.7 26.6 17.3 25.2 19.5", 1.5)
    I.trait("M27.9 10.2C30.1 13.6 30.1 18.4 27.9 21.8", 1.5)


@icone("evenements")
def _evenements(I):
    # un rendez-vous : la page du calendrier et le fanion de ralliement planté à côté
    I.trait(rect(3.2, 9.6, 19.8, 19.2, 1.8), 1.8)
    I.plein("M3.2 14.4V11.4A1.8 1.8 0 0 1 5 9.6H21.2A1.8 1.8 0 0 1 23 11.4V14.4Z")
    for x in (7.2, 16):
        I.ton_trait(rect(x, 6.8, 2.1, 5.2, 1.05), 1.05)
    for j, y in enumerate((17.4, 22.4)):
        for i, x in enumerate((6.4, 11.2, 16)):
            if (i, j) == (2, 1):
                I.ton_trait(rect(x - 0.4, y - 0.4, 3.6, 3.6, 0.7), 1.05)
            else:
                I.plein(rect(x, y, 2.8, 2.8, 0.5))
    I.trait(ligne(26.2, 28.6, 26.2, 3.2), 1.7)
    I.trait(ligne(23.8, 29.2, 28.6, 29.2), 1.4)
    fanion = poly([(26.9, 3.4), (31, 4.9), (29.2, 6.9), (31, 8.9), (26.9, 10.2)])
    I.ton(fanion)
    I.trait(fanion, 1.2)


@icone("roles")
def _roles(I):
    ruban = "M10.4 2.6H21.6L19.4 13.6H12.6Z"
    I.plein(ruban)
    I.ton(poly([(14.6, 2.6), (17.4, 2.6), (16.9, 13.6), (15.1, 13.6)]))
    I.trait(ruban, 1.3)
    I.plein(rect(14.4, 12.8, 3.2, 2, 0.5))
    I.ton(cercle(16, 21.6, 7.4))
    I.hach(F(cercle(16, 21.6, 7.4)) & F(rect(17.4, 14, 10, 16)) - F(cercle(16, 21.6, 5.6)), 45, 1.3, sw=0.7)
    I.trait(cercle(16, 21.6, 7.4), 1.8)
    I.trait(cercle(16, 21.6, 5.5), 0.9)
    I.plein(poly(etoile_pts(16, 21.8, 3.7, 1.55, 5)))


@icone("sanctions")
def _sanctions(I):
    # boulet de forçat : le boulet, sa chaîne, le fer de cheville
    I.trait(cercle(24.6, 7.4, 4.3), 2.3)
    I.hach(F(cercle(24.6, 7.4, 5.4)) - F(cercle(24.6, 7.4, 3.2)) & F(rect(24.6, 7.4, 8, 8)), 45, 1.1, sw=0.6, marge=0.15)
    I.ton_trait(rect(19.6, 9.6, 3.4, 2.6, 0.5), 1.1, tf="rotate(-45 21.3 10.9)")
    I.trait(ellipse(18.4, 13.8, 1.9, 1.1), 1.3, tf="rotate(-45 18.4 13.8)")
    I.trait(ellipse(16.6, 15.6, 1.8, 0.5), 1.3, tf="rotate(45 16.6 15.6)")
    boulet = cercle(11.2, 21.2, 7.6)
    reflet = ellipse(8.4, 18.2, 1.9, 1.05)
    I.plein(boulet + chemin_rot(reflet, -42, 8.4, 18.2), eo=True)
    I.trait("M5.6 25.6C7.2 27.4 9.6 28.2 12.2 28", 0.9, c="ton2")


@icone("nettoyage")
def _nettoyage(I):
    I.trait(ligne(27.8, 3.4, 15.4, 15.8), 2.6)
    I.ton_trait(rect(14.2, 14.4, 3.4, 2.8, 0.5), 1.15, tf="rotate(45 15.9 15.8)")
    paille = "M15 16.8C13.6 21.2 9.8 26.6 3.2 29.2C4.4 23 8.6 18.6 13.4 15.4Z"
    I.hach(F(paille), 132, 1.15, sw=0.7, marge=0.3)
    I.trait(paille, 1.6)
    I.trait("M2.8 30.4H13.4", 1.1)


# ── Traits à la plume (pleins et déliés) ─────────────────────────────────────────────────

def _catmull(ctrl, k):
    pts = []
    m = len(ctrl)
    for i in range(m - 1):
        p0 = ctrl[i - 1] if i > 0 else ctrl[i]
        p1, p2 = ctrl[i], ctrl[i + 1]
        p3 = ctrl[i + 2] if i + 2 < m else p2
        for j in range(k):
            t = j / k
            t2, t3 = t * t, t * t * t
            pts.append(tuple(0.5 * (2 * p1[c] + (-p0[c] + p2[c]) * t
                                    + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2
                                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3) for c in (0, 1)))
    pts.append(tuple(ctrl[-1]))
    return pts


def calame(ctrl, larg, k=12, bouts=("rond", "rond")):
    """Trait plein-délié : une ligne médiane (Catmull-Rom) et une largeur par point de
    contrôle ; rendu comme une forme pleine, donc identique dans le SVG et dans Pillow."""
    pts = _catmull(ctrl, k)
    ws = []
    for i in range(len(ctrl) - 1):
        ws += [larg[i] + (larg[i + 1] - larg[i]) * j / k for j in range(k)]
    ws.append(larg[-1])
    g, d = [], []
    for i, (x, y) in enumerate(pts):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        lg = math.hypot(tx, ty) or 1
        nx, ny = -ty / lg, tx / lg
        h = ws[i] / 2
        g.append((x + nx * h, y + ny * h))
        d.append((x - nx * h, y - ny * h))

    def bout(p, q, w, genre):
        if genre != "rond" or w < 0.3:
            return []
        ang = math.atan2(p[1] - q[1], p[0] - q[0])
        return [(p[0] + w / 2 * math.cos(ang + math.pi / 2 - math.pi * j / 6),
                 p[1] + w / 2 * math.sin(ang + math.pi / 2 - math.pi * j / 6)) for j in range(1, 6)]

    fin = bout(pts[-1], pts[-2], ws[-1], bouts[1])
    debut = bout(pts[0], pts[1], ws[0], bouts[0])
    g, d = _simplifier(g, 0.012), _simplifier(d, 0.012)
    return poly(g + fin + d[::-1] + debut, prec=1)


def pointe(x, y, ang, lg=5.6, larg=5.4, creux=1.5):
    """Fer de flèche plein, pointe en (x, y), dirigé selon ang (degrés)."""
    a = math.radians(ang)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    bx, by = x - ux * lg, y - uy * lg
    return poly([(x, y), (bx + vx * larg / 2, by + vy * larg / 2), (x - ux * (lg - creux), y - uy * (lg - creux)),
                 (bx - vx * larg / 2, by - vy * larg / 2)])


def poly_arrondi(pts, r):
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % k]
        a = math.atan2(p0[1] - p1[1], p0[0] - p1[0])
        b = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        out.append((p1[0] + r * math.cos(a), p1[1] + r * math.sin(a)))
        out.append(("Q", p1, (p1[0] + r * math.cos(b), p1[1] + r * math.sin(b))))
    s = f"M{n(out[0][0])} {n(out[0][1])}"
    for e in out[1:]:
        if e[0] == "Q":
            s += f"Q{n(e[1][0])} {n(e[1][1])} {n(e[2][0])} {n(e[2][1])}"
        else:
            s += f"L{n(e[0])} {n(e[1])}"
    return s + "Z"


def _coche(I, x=0.0, y=0.0, e=1.0, c="encre"):
    def P(px, py):
        return (x + px * e, y + py * e)
    I.plein(calame([P(5.4, 16.6), P(9.2, 19.6), P(12.6, 24.6)], [1.3 * e, 2.6 * e, 3.3 * e]), c)
    I.plein(calame([P(12.4, 24.8), P(16.6, 16.8), P(21.6, 10.4), P(27, 6)],
                   [3.3 * e, 2.6 * e, 1.7 * e, 0.8 * e], bouts=("rond", "pointe")), c)


def _croix(I, cx=16.0, cy=16.0, r=9.6, c="encre", e=1.0):
    I.plein(calame([(cx - r, cy - r), (cx, cy), (cx + r, cy + r)], [1.2 * e, 3.1 * e, 1.6 * e]), c)
    I.plein(calame([(cx + r, cy - r), (cx, cy), (cx - r, cy + r)], [1.1 * e, 2.6 * e, 1.4 * e]), c)


def _chevron(I, ang):
    tf = f"rotate({ang} 16 16)"
    I.plein(calame([(19.8, 5.2), (14.4, 11), (10, 16)], [1.1, 2.4, 3.2]), tf=tf)
    I.plein(calame([(10, 16), (14.4, 21), (19.8, 26.8)], [3.2, 2.4, 1.1]), tf=tf)


def _anneau(I):
    I.trait(cercle(16, 16, 12.9), 1.9)
    I.trait(cercle(16, 16, 11.1), 0.7)


# ── Glyphes d'interface ──────────────────────────────────────────────────────────────────

@icone("valider")
def _valider(I):
    _coche(I)


@icone("coche")
def _icone_coche(I):
    _coche(I, -0.6, 0.2, 1.06)


@icone("fermer")
def _fermer(I):
    _croix(I)


@icone("ajouter")
def _ajouter(I):
    _anneau(I)
    I.plein(calame([(9.6, 16), (16, 15.8), (22.4, 16)], [2, 2.6, 2]))
    I.plein(calame([(16, 9.6), (15.8, 16), (16, 22.4)], [2, 2.6, 2]))


@icone("annuler")
def _annuler(I):
    _anneau(I)
    _croix(I, r=5.6, e=0.92)


@icone("plus")
def _plus(I):
    I.plein(calame([(5.8, 16), (16, 15.7), (26.2, 16)], [2.3, 2.9, 2.3]))
    I.plein(calame([(16, 5.8), (15.7, 16), (16, 26.2)], [2.3, 2.9, 2.3]))


@icone("moins")
def _moins(I):
    I.plein(calame([(5.8, 16), (16, 15.7), (26.2, 16)], [2.3, 2.9, 2.3]))


@icone("gauche")
def _gauche(I):
    _chevron(I, 0)


@icone("droite")
def _droite(I):
    _chevron(I, 180)


@icone("haut")
def _haut(I):
    _chevron(I, 90)


@icone("bas")
def _bas(I):
    _chevron(I, -90)


@icone("menu")
def _menu(I):
    for y, d in ((8.6, 0.25), (16, -0.2), (23.4, 0.2)):
        I.plein(calame([(5.4, y + d), (16, y - d), (26.6, y + d)], [2.1, 2.7, 1.9]))


@icone("rechercher")
def _rechercher(I):
    c = (13.2, 13.2)
    I.hach(F(cercle(*c, 7)) & F(poly([(4, 30), (30, 4), (30, 30)])), 45, 1.7, sw=0.6, marge=0.5)
    I.trait("M8.6 11.6A5 5 0 0 1 11.6 8.6", 1.2)
    I.plein(calame([(19.6, 19.6), (24, 24), (27.4, 27.4)], [2.4, 3.2, 3.6]))
    I.ton(cercle(*c, 9) + cercle(*c, 7), eo=True)
    I.trait(cercle(*c, 9), 1.8)
    I.trait(cercle(*c, 7), 1.1)
    I.ton_trait(rect(19, 18.3, 3.3, 2.2, 0.4), 1.05, tf="rotate(45 20.65 19.4)")


@icone("filtrer")
def _filtrer(I):
    cone = "M4.6 7.4H27.4L17.6 19.6V27.6C17.6 28.4 16.9 29 16 29C15.1 29 14.4 28.4 14.4 27.6V19.6Z"
    I.ton(cone)
    I.hach(F(cone) & F(rect(17.2, 0, 14, 32)), 60, 1.35, sw=0.7)
    I.trait(cone, 1.8)
    I.trait(ellipse(16, 7.4, 11.4, 2.7), 1.6)
    I.plein(ellipse(16, 7.9, 9.2, 1.55))
    I.trait(ligne(14.4, 19.6, 17.6, 19.6), 1.1)


@icone("exporter")
def _exporter(I):
    caisse = rect(4.8, 17.4, 22.4, 11.4, 1)
    I.hach(F(caisse) & F(rect(18, 0, 14, 32)), 45, 1.45, sw=0.7)
    I.trait(ligne(4.8, 23.1, 12.6, 23.1), 1)
    I.trait(ligne(19.4, 23.1, 27.2, 23.1), 1)
    I.trait("M12.6 17.4V28.8M19.4 17.4V28.8", 1)
    I.trait(caisse, 1.9)
    I.plein(rect(12.7, 16.6, 6.6, 1.6, 0.3), "ton2")
    I.plein(calame([(16, 23.4), (16, 13), (16, 8.4)], [3.2, 2.4, 2]))
    I.plein(pointe(16, 2.6, -90, 6.4, 7.6, 1.8))


@icone("ouvrir")
def _ouvrir(I):
    I.trait("M13.6 6.4H7.6C6.5 6.4 5.6 7.3 5.6 8.4V24.4C5.6 25.5 6.5 26.4 7.6 26.4H23.6C24.7 26.4 25.6 25.5 25.6 24.4V18.4", 1.9)
    I.plein(calame([(13.4, 18.6), (19.6, 12.4), (23.2, 8.8)], [3, 2.3, 2]))
    I.plein(pointe(27.4, 4.6, -45, 6.6, 7.4, 1.8))


@icone("lien")
def _lien(I):
    m1 = rect(4.1, 17.2, 15, 6.4, 3.2)
    m2 = rect(12.9, 8.4, 15, 6.4, 3.2)
    t1, t2 = "rotate(-45 11.6 20.4)", "rotate(-45 20.4 11.6)"
    d1 = chemin_rot(m1, -45, 11.6, 20.4)
    d2 = chemin_rot(m2, -45, 20.4, 11.6)
    I.trait(masquer(d1, et(lambda x, y: x + y > 32, pres(d2, 1.9))), 2.3)
    I.trait(masquer(d2, et(lambda x, y: x + y < 32, pres(d1, 1.9))), 2.3)
    _ = (t1, t2)


def chemin_rot(d, ang, cx, cy):
    """Un chemin tourné, aplati en polyligne (pour les masques et croisements)."""
    m = m_rot(ang, cx, cy)
    return "".join(poly([m_app(m, x, y) for x, y in pts], ferme)
                   for pts, ferme in aplatir(d, 0.15))


@icone("deconnexion")
def _deconnexion(I):
    porte = rect(4.4, 4, 9.8, 24.4, 0.9)
    I.ton(porte)
    I.hach(F(porte) & F(rect(10.6, 0, 6, 32)), 45, 1.3, sw=0.65)
    I.trait(ligne(7.7, 4.6, 7.7, 27.8), 0.9)
    I.trait(ligne(10.9, 4.6, 10.9, 27.8), 0.9)
    I.trait(porte, 1.8)
    I.plein(cercle(12.2, 16.6, 0.85))
    I.plein(calame([(15.2, 16), (21.4, 16), (24.6, 16)], [2.2, 2.6, 2.4]))
    I.plein(pointe(29.6, 16, 0, 6.2, 7, 1.7))


@icone("synchro")
def _synchro(I):
    for a0, a1 in ((200, 318), (20, 138)):
        pts = arc_pts(16, 16, 10.4, a0, a1, 8)
        I.plein(calame(pts, [1.3 + 1.6 * math.sin(math.pi * i / 8) for i in range(9)]))
        fin = math.radians(a1 + 9)
        x, y = 16 + 10.4 * math.cos(fin), 16 + 10.4 * math.sin(fin)
        I.plein(pointe(x, y, a1 + 9 + 90, 6, 6.4, 1.6))


def _lanterne(I, allumee=True):
    I.trait("M13.3 5.6A2.7 2.7 0 0 1 18.7 5.6", 1.5)
    verre = rect(10.9, 9.6, 10.2, 13.4)
    if not allumee:
        I.hach(F(verre), 45, 1.25, sw=0.7, marge=0.3)
    else:
        flamme = "M16 12C17.9 14.5 18.8 16.4 18.4 18.4C18 20.3 17 21.1 16 21.1C15 21.1 14 20.3 13.6 18.4C13.2 16.4 14.1 14.5 16 12Z"
        I.ton_trait(flamme, 1)
        I.plein("M16 15.8C16.8 17 17.1 18 16.9 18.9C16.7 19.6 16.4 19.9 16 19.9C15.6 19.9 15.3 19.6 15.1 18.9C14.9 18 15.2 17 16 15.8Z")
        for s in (-1, 1):
            for (x0, y0), (x1, y1) in (((8.4, 12.4), (6, 10.6)), ((8, 16.4), (4.8, 16.4)), ((8.4, 20.4), (6, 22.2))):
                I.trait(ligne(16 + s * (x0 - 16), y0, 16 + s * (x1 - 16), y1), 1.25)
    I.trait(verre, 1.7)
    I.plein("M10.2 9.8H21.8L19.4 6.2H12.6Z")
    I.plein(rect(9.6, 22.8, 12.8, 2.7, 0.6))
    I.plein(rect(11.8, 25.3, 8.4, 1.7, 0.4))
    if not allumee:
        I.trait(ligne(16, 21.4, 16, 19.4), 1.2)
        I.trait("M21.6 5.4C23.4 4.4 21.8 3.2 23.6 2.2", 1.05)


@icone("en_ligne")
def _en_ligne(I):
    _lanterne(I, True)


@icone("hors_ligne")
def _hors_ligne(I):
    _lanterne(I, False)


def _exclamation(I, cx=16.0, haut=9.4, bas=20.4, y_point=24.2, e=1.0):
    I.plein(calame([(cx, haut), (cx, (haut + bas) / 2), (cx, bas)], [3.2 * e, 2.6 * e, 1.5 * e]))
    I.plein(cercle(cx, y_point, 1.65 * e))


@icone("attention")
def _attention(I):
    tri = poly_arrondi([(16, 3.4), (29.4, 27.6), (2.6, 27.6)], 2.4)
    I.ton(tri)
    I.hach(F(tri) & F(poly([(16, 3), (30, 28), (22, 28)])), 60, 1.4, sw=0.65)
    I.trait(tri, 1.9)
    _exclamation(I, 16, 11.2, 20.2, 23.8, 0.95)


@icone("info")
def _info(I):
    _anneau(I)
    I.plein(cercle(16, 9.8, 1.75))
    I.plein("M13.4 13.6H17.4V21.8H19.2V23.6H12.8V21.8H14.6V15.4H13.4Z")


@icone("succes")
def _succes(I):
    sceau = cachet(16, 16, 12.6, graine=5, lobes=9, amp=0.055)
    I.ton(sceau)
    I.trait(sceau, 1.8)
    I.trait(cercle(16, 16, 9.6), 0.8)
    _coche(I, 16 - 16 * 0.62, 16.6 - 16 * 0.62, 0.62)


@icone("erreur")
def _erreur(I):
    tige = calame([(16, 8.6), (16, 14.4), (16, 19.6)], [3.4, 2.7, 1.6])
    I.plein(cercle(16, 16, 13) + tige + cercle(16, 23.6, 1.8), eo=True)


@icone("peut_etre")
def _peut_etre(I):
    _anneau(I)
    _interrogation(I)


# ── Signes, monnaie, marques ─────────────────────────────────────────────────────────────

def baht(x, y, h, epais=1.0):
    """Le signe ฿ (prime) en forme pleine : un B à empattements, barré verticalement.
    (x, y) = coin haut-gauche du B, h = hauteur du B. Rend (contour pair-impair, barre)."""
    s = h / 14.0

    def P(px, py):
        return f"{n(x + px * s)} {n(y + py * s)}"
    e = epais
    corps = (f"M{P(-1.3, 0)}H{n(x + 5.6 * s)}C{P(8.6, 0)} {P(9.8, 1.6)} {P(9.8, 3.5)}"
             f"C{P(9.8, 5.2)} {P(8.8, 6.3)} {P(7.3, 6.75)}C{P(9.2, 7.1)} {P(10.5, 8.5)} {P(10.5, 10.3)}"
             f"C{P(10.5, 12.6)} {P(8.8, 14)} {P(5.9, 14)}H{n(x - 1.3 * s)}V{n(y + (14 - 1.1 * e) * s)}"
             f"H{n(x + 0.4 * s)}V{n(y + 1.1 * e * s)}H{n(x - 1.3 * s)}Z")
    trous = (f"M{P(2.6 + 0.3 * (e - 1), 2 * e)}H{n(x + 5.1 * s)}C{P(6.5, 2 * e)} {P(7, 2.8)} {P(7, 3.75)}"
             f"C{P(7, 4.8)} {P(6.4, 5.6)} {P(5.1, 5.6)}H{n(x + (2.6 + 0.3 * (e - 1)) * s)}Z"
             f"M{P(2.6 + 0.3 * (e - 1), 7.9)}H{n(x + 5.5 * s)}C{P(7, 7.9)} {P(7.6, 8.8)} {P(7.6, 10.05)}"
             f"C{P(7.6, 11.3)} {P(6.9, 14 - 2 * e)} {P(5.4, 14 - 2 * e)}H{n(x + (2.6 + 0.3 * (e - 1)) * s)}Z")
    barre = rect(x + 3.9 * s, y - 2.3 * s, 1.7 * s, 18.6 * s, 0.4 * s)
    return corps + trous, barre


@icone("oeil")
def _oeil(I):
    iris = cercle(16, 16.2, 5.5)
    I.ton(iris)
    I.hach(F(iris) & F(poly([(10, 24), (24, 10), (24, 24)])), 45, 1.3, sw=0.65)
    I.trait(iris, 1.3)
    I.plein(cercle(16, 16.2, 2.5) + cercle(15, 15.2, 0.8), eo=True)
    I.trait("M2.8 16.6C7.6 8.4 24.4 8.4 29.2 16.6", 2)
    I.trait("M2.8 16.6C7.6 23.8 24.4 23.8 29.2 16.6", 1.6)


@icone("masquer")
def _masquer(I):
    I.trait("M3.2 7.6C9.4 10.8 19.4 13.8 28.8 13", 1.7)
    I.trait("M3.6 18.4C5.6 19.8 7.8 20.5 10.2 20.6", 1.5)
    I.trait("M23.8 20.4C25.8 20 27.4 19.2 28.6 17.8", 1.5)
    bandeau = "M10.4 13.4C13.4 11.7 21.4 11.6 24 13.6C25.3 17.8 22.2 23.4 17.2 23.8C12.2 23.4 9.1 17.8 10.4 13.4Z"
    I.plein(bandeau + poly([(13.2, 15.4), (14.2, 14.6), (13.2, 19), (12.6, 18.2)]), eo=True)


@icone("etoile")
def _etoile(I):
    c = (16, 17)
    ext = etoile_pts(*c, 13.8, 5.5, 5)
    for i in range(0, 10, 2):
        pointe_ = ext[i]
        g, d = ext[i - 1], ext[(i + 1) % 10]
        I.plein(poly([c, pointe_, g]))
        I.ton(poly([c, pointe_, d]))
        I.trait(ligne(c[0], c[1], pointe_[0], pointe_[1]), 0.9)
    I.trait(poly(ext), 1.6)


@icone("prime")
def _prime(I):
    pile = "M16 13.8V25.4C16 26.7 19 27.8 22.6 27.8C26.2 27.8 29.2 26.7 29.2 25.4V13.8Z"
    I.ton(pile)
    I.hach(F(pile) & F(rect(24, 0, 8, 32)), 80, 1.3, sw=0.65)
    for y in (17.6, 21.4):
        I.trait(f"M16 {n(y)}C16 {n(y + 1.3)} 19 {n(y + 2.4)} 22.6 {n(y + 2.4)}C26.2 {n(y + 2.4)} 29.2 {n(y + 1.3)} 29.2 {n(y)}", 0.95)
    I.trait("M16 13.8V25.4C16 26.7 19 27.8 22.6 27.8C26.2 27.8 29.2 26.7 29.2 25.4V13.8", 1.5)
    I.ton_trait(ellipse(22.6, 13.8, 6.6, 2.3), 1.4)
    I.ton(cercle(12.4, 18.6, 9.2))
    I.hach(F(cercle(12.4, 18.6, 9.2)) - F(cercle(12.4, 18.6, 7.4)) & F(rect(12, 18, 12, 12)), 45, 1.2, sw=0.6, marge=0.2)
    I.trait(cercle(12.4, 18.6, 9.2), 1.9)
    I.trait(cercle(12.4, 18.6, 7.4), 0.8)
    corps, barre = baht(9.6, 14.4, 8.6, 1.1)
    I.plein(corps, eo=True)
    I.plein(barre)


@icone("berry")
def _berry(I):
    corps, barre = baht(9.4, 6.2, 19.6, 1)
    I.plein(corps, eo=True)
    I.plein(barre)


@icone("lieu")
def _lieu(I):
    epingle = "M16 29.6C12.4 23.8 7 19.2 7 12.6A9 9 0 0 1 25 12.6C25 19.2 19.6 23.8 16 29.6Z"
    I.ton(epingle + cercle(16, 12.6, 3.4), eo=True)
    I.hach(F(epingle) & F(rect(18.4, 0, 10, 32)) - F(cercle(16, 12.6, 4.2)), 45, 1.4, sw=0.7)
    I.trait(epingle, 1.9)
    I.trait(cercle(16, 12.6, 3.4), 1.35)
    I.trait("M10.6 29.2C12.2 30.6 19.8 30.6 21.4 29.2", 1.1)


@icone("discord")
def _discord(I):
    corps = ("M26.4 7.6C24.4 6.7 22.3 6 20.1 5.7L19.4 7.1C17.1 6.8 14.9 6.8 12.6 7.1L11.9 5.7C9.7 6 7.6 6.7 5.6 7.6"
             "C1.9 13.1 0.9 18.5 1.4 23.8C3.9 25.6 6.3 26.7 8.7 27.4L10.3 24.8C9.3 24.4 8.4 24 7.6 23.5L8.2 23"
             "C12.9 25.2 19.1 25.2 23.8 23L24.4 23.5C23.6 24 22.7 24.4 21.7 24.8L23.3 27.4C25.7 26.7 28.1 25.6 30.6 23.8"
             "C31.2 17.7 29.6 12.3 26.4 7.6Z")
    I.plein(corps + ellipse(11.6, 17.8, 2.35, 2.65) + ellipse(20.4, 17.8, 2.35, 2.65), eo=True)


@icone("roblox")
def _roblox(I):
    m = m_rot(-15, 16, 16)
    ext = [m_app(m, x, y) for x, y in ((5, 5), (27, 5), (27, 27), (5, 27))]
    trou = [m_app(m, x, y) for x, y in ((12.7, 12.7), (19.3, 12.7), (19.3, 19.3), (12.7, 19.3))]
    I.plein(poly(ext) + poly(trou), eo=True)


@icone("crane")
def _crane(I):
    for a, b in (((5.4, 19.4), (26.6, 29)), ((26.6, 19.4), (5.4, 29))):
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        lg = math.dist(a, b)
        I.ton_trait(rect(cx - lg / 2, cy - 1.15, lg, 2.3, 1), 1.2, tf=f"rotate({n(ang)} {n(cx)} {n(cy)})")
        for p in (a, b):
            for s in (-1, 1):
                ux = -math.sin(math.radians(ang)) * 1.2 * s
                uy = math.cos(math.radians(ang)) * 1.2 * s
                I.ton_trait(cercle(p[0] + ux, p[1] + uy, 1.45), 1.1)
    crane = ("M8.6 13.4C8.6 8.2 12 4.6 16 4.6C20 4.6 23.4 8.2 23.4 13.4C23.4 16.4 22.2 18.2 20.6 19.1V22.4"
             "C20.6 23.1 20.1 23.6 19.4 23.6H12.6C11.9 23.6 11.4 23.1 11.4 22.4V19.1C9.8 18.2 8.6 16.4 8.6 13.4Z")
    I.ton(crane)
    I.hach(F(crane) & F(rect(18.6, 0, 10, 30)), 45, 1.35, sw=0.65)
    I.trait(crane, 1.8)
    I.plein(ellipse(12.9, 13.6, 2.25, 2.45))
    I.plein(ellipse(19.1, 13.6, 2.25, 2.45))
    I.plein(poly([(16, 16.4), (17.1, 18.6), (14.9, 18.6)]))
    for x in (14, 16, 18):
        I.trait(ligne(x, 20.4, x, 23.4), 0.9)


@icone("epingle")
def _epingle(I):
    tf = "rotate(45 16 16)"
    I.plein(poly([(7, 14.7), (21.6, 15.3), (28.6, 16), (21.6, 16.7), (7, 17.3)]), tf=tf)
    tete = ellipse(5.4, 16, 2.4, 6)
    I.ton(tete, tf=tf)
    I.hach(F(tete, tf=tf) & F(rect(0, 16.6, 30, 8), tf=tf), 0, 1.15, sw=0.6, marge=0.3)
    I.trait(tete, 1.6, tf=tf)


@icone("image")
def _image(I):
    I.trait(rect(3.4, 5.6, 25.2, 20.8, 1), 1.9)
    I.trait(rect(6.2, 8.4, 19.6, 15.2), 0.9)
    I.ton_trait(cercle(21.4, 12.4, 2.1), 0.9)
    I.plein("M8 18.6C9.2 15.6 12.2 14.2 15 15.8C16 14.8 18.2 15 19 16.8C20.2 16.8 21.2 17.6 21.6 18.6Z")
    I.trait(ligne(6.6, 18.7, 25.4, 18.7), 0.9)
    I.trait(vague(8, 24, 21.4, 0.55, 4), 0.85)


@icone("historique")
def _historique(I):
    c = (16.4, 16.6)
    I.trait(cercle(*c, 8.6), 0.75)
    for k in range(12):
        a = math.radians(k * 30)
        r0 = 6.6 if k % 3 == 0 else 7.4
        I.trait(ligne(c[0] + r0 * math.sin(a), c[1] - r0 * math.cos(a), c[0] + 8.2 * math.sin(a),
                      c[1] - 8.2 * math.cos(a)), 1 if k % 3 == 0 else 0.7)
    I.plein(calame([c, (c[0], c[1] - 3), (c[0], c[1] - 5.6)], [2.2, 1.7, 1.1]))
    I.plein(calame([c, (c[0] + 2.4, c[1] + 1.2), (c[0] + 4.2, c[1] + 2.1)], [2, 1.5, 1]))
    I.ton_trait(cercle(*c, 1.2), 0.8)
    pts = arc_pts(*c, 11.6, 205, 515, 30)
    I.plein(calame(pts, [2.2] * len(pts), k=4))
    a = math.radians(205 - 10)
    I.plein(pointe(c[0] + 11.6 * math.cos(a), c[1] + 11.6 * math.sin(a), 205 - 10 - 90, 6, 6.4, 1.6))


@icone("restaurer")
def _restaurer(I):
    I.plein(calame([(25.6, 26), (26.2, 17.6), (22.2, 11.4), (15.2, 10.6), (9.6, 12.2)],
                   [1.5, 2.4, 2.8, 2.6, 2.3], k=8))
    I.plein(pointe(4.2, 14.4, 160, 6.4, 7.2, 1.8))


@icone("tri")
def _tri(I):
    I.plein(calame([(11, 27.2), (11, 18), (11, 9.6)], [1.8, 2.4, 2.6]))
    I.plein(pointe(11, 3.6, -90, 6.4, 7.4, 1.8))
    I.plein(calame([(21, 4.8), (21, 14), (21, 22.4)], [1.8, 2.4, 2.6]))
    I.plein(pointe(21, 28.4, 90, 6.4, 7.4, 1.8))


@icone("grade")
def _grade(I):
    for i, y in enumerate((4, 11.2, 18.4)):
        ch = poly([(4.8, y + 6.4), (16, y), (27.2, y + 6.4), (27.2, y + 9.8), (16, y + 3.4), (4.8, y + 9.8)])
        if i == 0:
            I.plein(ch)
            I.trait(ch, 1.2)
        else:
            I.ton_trait(ch, 1.3)


# ════════════════════════════════════════════════════════════════════════════════════════
#  Lettres dessinées (contours tirés des polices OFL du site, pour les ornements-images)
# ════════════════════════════════════════════════════════════════════════════════════════

# Un ornement affiché comme image ne peut pas charger de police : les quelques lettres utiles
# (WANTED, tampons, sous-titre, « RELL Seas ») sont donc des contours, extraits une fois par
# `python outils/dessins_site.py glyphes <rye.ttf> <alegreya-sc-700.ttf> <pirata-one.ttf>`.
LETTRES_VOULUES = {
    "Rye": "WANTED",
    "Alegreya SC": "VUTRAIÉCHFSPDEL'QG",
    "Pirata One": "RELSeas",
}


def imprimer_glyphes(ttfs):
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont
    table = {}
    for f in ttfs:
        t = TTFont(f)
        fam = t["name"].getDebugName(1)
        if fam not in LETTRES_VOULUES:
            continue
        cmap, gs = t.getBestCmap(), t.getGlyphSet()
        upm = t["head"].unitsPerEm
        hhea = t["hhea"]
        lettres = {}
        for ch in LETTRES_VOULUES[fam]:
            nom = cmap[ord(ch)]
            pen = SVGPathPen(gs, lambda v: str(int(round(v))))
            gs[nom].draw(pen)
            lettres[ch] = [gs[nom].width, pen.getCommands()]
        table[fam] = {"upm": upm, "asc": hhea.ascent, "desc": hhea.descent, "lettres": lettres}
    print("GLYPHES = " + json.dumps(table, ensure_ascii=False, indent=None, separators=(",", ":")))


GLYPHES = {"Rye":{"upm":2048,"asc":2020,"desc":-540,"lettres":{"W":[2161,"M1876 880Q1876 826 1973 797Q1891 764 1859 735Q1798 678 1763 587L1589 87Q1533 -55 1504 -73Q1495 -79 1483 -79Q1471 -79 1463 -72L1122 919L809 87Q753 -53 724 -73Q715 -79 703 -79Q691 -79 683 -72L360 655Q336 712 309 736Q267 772 199 797Q285 846 283 888Q283 915 263 963L235 1031L99 1398Q47 1434 8 1434Q-30 1434 -55 1417Q-66 1425 -66 1447Q-66 1469 -59 1488Q-52 1506 -37 1520Q-5 1550 56 1550Q117 1550 164 1515Q214 1550 282 1550Q351 1550 395 1516Q448 1550 494 1550Q540 1550 568 1544Q596 1537 617 1524Q662 1498 664 1452Q664 1424 653 1417Q626 1434 598 1434Q535 1434 500 1410L825 502L1046 1139L957 1399Q906 1434 868 1434Q830 1434 805 1417Q794 1425 794 1447Q794 1469 801 1488Q808 1506 823 1520Q855 1550 916 1550Q977 1550 1024 1515Q1074 1550 1142 1550Q1211 1550 1255 1516Q1308 1550 1354 1550Q1400 1550 1428 1544Q1456 1537 1477 1524Q1522 1498 1524 1452Q1524 1424 1513 1417Q1486 1434 1458 1434Q1393 1434 1359 1409L1626 572L1896 1407Q1864 1439 1804 1439Q1744 1439 1715 1422Q1705 1437 1705 1469Q1705 1501 1732 1526Q1759 1550 1809 1550Q1859 1550 1895 1524Q1927 1550 1973 1550Q2019 1550 2050 1528Q2094 1550 2138 1550Q2182 1550 2208 1522Q2235 1493 2235 1448Q2235 1425 2224 1417Q2198 1434 2161 1434Q2093 1434 2046 1383L1910 1008Q1876 914 1876 880ZM1154 1254Q1139 1233 1139 1191Q1139 1149 1156 1100L1192 993L1463 265Q1468 271 1466 286Q1465 301 1465 330Q1465 358 1462 380Q1459 401 1454 424Q1447 464 1430 514ZM318 1250Q298 1238 298 1212Q298 1187 300 1174Q302 1161 308 1140Q321 1087 342 1028Q362 970 369 946Q376 921 380 904Q383 887 384 876Q385 865 386 852Q388 825 324 799Q365 791 388 785Q412 779 422 762Q432 746 450 708Q469 670 490 622L533 520Q555 467 572 422Q588 377 602 348Q617 320 630 302Q655 271 688 265Q633 400 584 532Q536 663 486 786Q436 908 398 1024Q361 1140 318 1250Z"],"A":[1458,"M119 7Q82 -20 34 -20Q-13 -20 -42 4Q-70 29 -70 61Q-70 93 -60 108Q-31 91 12 91Q54 91 76 102Q97 114 117 134L259 555L279 624Q288 655 288 681Q288 772 202 797Q281 827 313 862Q363 917 392 1007L502 1376Q470 1419 426 1419Q382 1419 344 1400Q334 1418 334 1440Q334 1463 344 1483Q353 1503 370 1518Q408 1550 478 1550Q548 1550 597 1508Q647 1550 722 1550Q796 1550 840 1510Q904 1550 970 1550Q1036 1550 1072 1525Q1109 1500 1109 1457Q1109 1437 1097 1422Q1074 1439 1043 1439Q976 1439 956 1348L1084 939Q1108 862 1204 819Q1231 807 1259 797Q1159 764 1159 698Q1159 673 1167 654L1358 142Q1402 96 1447 96Q1492 96 1517 113Q1528 105 1528 83Q1528 61 1521 42Q1514 24 1499 10Q1467 -20 1405 -20Q1343 -20 1297 14Q1245 -20 1180 -20Q1114 -20 1067 13Q1022 -20 961 -20Q900 -20 860 6Q820 31 818 78Q818 106 829 113Q856 96 884 96Q943 96 967 120L891 375H350L284 154Q325 91 384 91Q442 91 471 108Q482 90 482 58Q482 27 451 4Q420 -20 371 -20Q322 -20 281 5Q245 -20 198 -20Q152 -20 119 7ZM850 510 618 1281 390 510ZM1041 265Q1059 265 1059 305Q1059 375 1038 441L1000 558Q960 690 960 724Q959 780 1009 798Q940 812 925 841Q918 853 914 860Q909 867 904 876Q900 886 894 901Q888 916 878 944L816 1131Q794 1201 751 1237Q738 1248 727 1250Q794 1008 815 940Q960 494 989 411ZM1336 175 1338 169Z"],"N":[1658,"M254 7Q217 -20 170 -20Q122 -20 94 4Q65 29 65 61Q65 93 75 108Q104 91 166 91Q229 91 270 176V656Q270 703 250 726Q220 762 148 797Q221 832 240 855Q270 893 270 940V1362Q236 1439 147 1439Q113 1439 91 1422Q80 1437 80 1457Q80 1477 90 1494Q100 1511 116 1524Q151 1550 210 1550Q270 1550 312 1517Q340 1550 389 1550Q438 1550 468 1516Q497 1550 528 1550Q558 1550 574 1544Q589 1538 600 1528Q616 1515 636 1477L1256 360V665Q1256 709 1237 730Q1208 761 1134 797Q1203 831 1223 852Q1256 887 1256 930V1349Q1233 1391 1200 1415Q1166 1439 1124 1439Q1081 1439 1052 1422Q1041 1440 1041 1472Q1041 1503 1072 1526Q1103 1550 1153 1550Q1203 1550 1242 1524Q1277 1550 1322 1550Q1368 1550 1403 1523Q1442 1550 1489 1550Q1536 1550 1564 1526Q1593 1501 1593 1469Q1593 1437 1583 1422Q1554 1439 1490 1439Q1426 1439 1388 1353V930Q1388 887 1406 867Q1436 834 1510 797Q1429 753 1413 736Q1388 709 1388 665L1406 157Q1442 91 1519 91Q1553 91 1575 108Q1586 93 1586 73Q1586 53 1576 36Q1566 19 1550 6Q1515 -20 1465 -20Q1415 -20 1375 0Q1296 -45 1214 7Q1182 -20 1153 -20Q1124 -20 1110 -15Q1096 -10 1084 3Q1065 22 1025 98L410 1158V176Q451 91 514 91Q577 91 606 108Q617 90 617 58Q617 27 586 4Q555 -20 506 -20Q457 -20 416 5Q380 -20 334 -20Q287 -20 254 7ZM1036 265Q1043 274 1043 294Q1043 313 1038 338Q1032 362 1022 390Q1001 446 967 510L543 1250Q536 1239 536 1210Q536 1148 621 993Z"],"T":[1510,"M871 13Q819 -20 756 -20Q692 -20 638 13Q583 -20 537 -20Q491 -20 463 -12Q435 -5 414 8Q371 34 371 73Q371 93 382 108Q404 91 440 91Q477 91 514 110Q552 129 571 169V656Q571 702 552 724Q522 761 449 797Q517 828 537 852Q571 891 571 940V1404Q538 1416 492 1416Q447 1416 397 1392Q347 1368 307 1322Q218 1218 218 1050Q218 953 250 907Q238 882 205 882Q172 882 146 897Q120 912 101 938Q62 990 62 1050Q62 1110 84 1152Q47 1196 47 1252Q47 1307 77 1343Q35 1388 35 1464Q35 1552 116 1582Q140 1591 158 1591Q192 1591 209 1576Q202 1552 202 1542Q202 1502 230 1502Q245 1502 261 1506L306 1519Q423 1550 501 1550Q579 1550 638 1516Q689 1550 754 1550Q819 1550 872 1516Q929 1550 990 1550Q1087 1550 1160 1530L1249 1506Q1265 1502 1280 1502Q1308 1502 1308 1542Q1308 1552 1301 1576Q1318 1591 1344 1591Q1370 1591 1394 1582Q1418 1573 1436 1556Q1475 1521 1475 1456Q1475 1390 1433 1343Q1463 1307 1463 1252Q1463 1197 1425 1152Q1448 1111 1448 1070Q1448 1029 1438 996Q1428 963 1409 938Q1368 882 1306 882Q1272 882 1260 907Q1292 953 1292 1046Q1292 1138 1268 1206Q1243 1275 1203 1322Q1122 1416 1012 1416Q970 1416 939 1404V940Q939 891 960 867Q993 828 1061 797Q988 761 968 738Q939 702 939 656V169Q957 129 994 110Q1032 91 1069 91Q1106 91 1128 108Q1139 93 1139 74Q1139 54 1128 37Q1116 20 1096 8Q1050 -20 988 -20Q927 -20 871 13ZM667 265Q717 284 722 396Q728 508 728 706Q728 904 728 970Q727 1035 726 1075Q723 1193 704 1218Q684 1242 667 1250Q667 902 655 854Q641 814 587 797Q647 776 655 746Q667 698 667 395Z"],"E":[1441,"M450 -20Q384 -20 333 12Q282 -20 238 -20Q195 -20 167 -12Q139 -5 118 8Q75 34 75 73Q75 93 86 108Q108 91 142 91Q231 91 265 167V656Q265 702 246 724Q216 761 143 797Q211 828 231 852Q265 891 265 940V1362Q231 1439 142 1439Q108 1439 86 1422Q75 1437 75 1456Q75 1476 86 1493Q98 1510 118 1522Q164 1550 224 1550Q283 1550 333 1517Q385 1550 452 1550Q519 1550 574 1511Q680 1550 819 1550Q922 1550 995 1530L1084 1506Q1100 1502 1115 1502Q1143 1502 1143 1542Q1143 1552 1136 1576Q1164 1581 1207 1581Q1250 1581 1280 1552Q1310 1524 1310 1470Q1310 1417 1291 1392Q1318 1352 1318 1294Q1318 1237 1279 1198Q1291 1168 1291 1140Q1291 1111 1282 1088Q1272 1064 1258 1048Q1230 1019 1201 1019Q1159 1019 1125 1037Q1137 1061 1137 1108Q1137 1218 1082 1301Q1007 1415 857 1415Q781 1415 720 1378Q658 1341 633 1272V885Q668 863 698 863Q729 863 744 864Q760 865 776 868Q817 874 839 884Q881 904 881 982Q881 1026 860 1050Q880 1064 910 1064Q977 1064 1007 1010Q1018 991 1018 968Q1018 945 1006 911Q1047 864 1047 800Q1047 735 1006 688Q1018 654 1018 626Q1018 599 1007 574Q996 549 980 534Q949 506 910 506Q882 506 860 522Q881 557 881 604Q881 697 830 719Q785 737 727 737Q669 737 633 716V216Q691 114 857 114Q1045 114 1113 230Q1192 363 1192 515Q1192 559 1184 583Q1209 608 1236 608Q1263 608 1277 600Q1291 593 1302 582Q1326 555 1326 527L1320 478Q1320 459 1330 447Q1350 426 1350 408Q1350 389 1338 363Q1361 350 1380 324Q1398 299 1398 272Q1398 215 1350 170Q1371 140 1371 84Q1371 27 1338 -12Q1306 -52 1254 -52Q1226 -52 1196 -46Q1200 -24 1200 -2Q1200 44 1158 44Q1111 44 1064 25Q953 -20 812 -20Q670 -20 571 17Q519 -20 450 -20ZM361 265Q411 284 416 396Q422 508 422 706Q422 904 422 970Q421 1035 420 1075Q417 1193 398 1218Q378 1242 361 1250Q361 902 349 854Q335 814 281 797Q341 776 349 746Q361 698 361 395ZM613 275Q613 272 614 270Z"],"D":[1590,"M450 -20Q384 -20 333 12Q282 -20 238 -20Q195 -20 167 -12Q139 -5 118 8Q75 34 75 73Q75 93 86 108Q108 91 142 91Q231 91 265 167V656Q265 702 246 724Q216 761 143 797Q211 828 231 852Q265 891 265 940V1362Q231 1439 142 1439Q108 1439 86 1422Q75 1437 75 1456Q75 1476 86 1493Q98 1510 118 1522Q164 1550 224 1550Q283 1550 333 1517Q385 1550 444 1550Q502 1550 552 1525Q670 1560 771 1560Q872 1560 950 1549Q1028 1538 1099 1510Q1170 1483 1232 1437Q1295 1391 1344 1322Q1448 1177 1477 938Q1483 879 1502 855Q1534 816 1589 797Q1531 775 1513 752Q1483 714 1477 656Q1444 324 1254 144Q1071 -30 779 -30Q662 -30 569 6Q524 -20 450 -20ZM633 157Q681 103 760 103Q840 103 898 134Q957 166 997 232Q1078 367 1078 656Q1078 719 1058 742Q1031 774 969 797Q1030 818 1048 839Q1078 875 1078 930Q1078 986 1070 1041Q1062 1096 1044 1150Q1027 1204 1000 1254Q974 1303 937 1341Q856 1424 746 1424Q712 1424 680 1422Q648 1421 633 1403ZM1130 1250Q1205 1041 1205 892Q1205 841 1196 832Q1188 823 1178 816Q1160 804 1139 797Q1199 770 1202 745Q1204 734 1204 723V698Q1204 563 1176 436Q1148 310 1134 265Q1179 278 1200 324Q1220 371 1234 424Q1249 478 1258 538Q1278 661 1278 795Q1278 1035 1207 1182Q1176 1240 1130 1250ZM361 265Q411 284 416 396Q422 508 422 706Q422 904 422 970Q421 1035 420 1075Q417 1193 398 1218Q378 1242 361 1250Q361 902 349 854Q335 814 281 797Q341 776 349 746Q361 698 361 395Z"]}},"Alegreya SC":{"upm":1000,"asc":1016,"desc":-345,"lettres":{"V":[624,"M72 517Q63 548 46 562Q28 577 -3 578L-7 585L0 644Q14 644 51 643Q88 642 126 642Q171 642 224 646Q278 649 294 650L299 642L295 583Q260 579 244 576Q228 572 222 565Q217 558 217 544Q217 522 256 356Q295 189 310 129H325Q349 190 401 358Q453 526 453 548Q453 565 442 572Q430 579 401 579H361L357 586L363 647Q377 646 424 644Q472 642 511 642Q551 642 584 643Q616 644 627 644L620 579Q595 575 585 566Q575 556 565 527L380 5L221 -15Q206 41 158 219Q109 397 72 517Z"],"U":[657,"M86 204V524Q86 557 80 568Q73 578 53 578Q43 578 34 577Q24 576 21 576L19 580L28 645Q42 644 82 643Q123 642 169 642Q195 642 235 644Q275 647 288 648L281 582Q249 578 238 566Q226 555 224 528L217 236Q217 160 250 118Q282 77 343 77Q468 77 468 209Q468 286 466 385Q465 484 464 524Q463 557 457 568Q451 578 432 578Q422 578 412 577Q402 576 398 576L396 580L405 645Q418 645 452 644Q487 642 521 642Q553 642 590 644Q628 647 639 648L633 583Q606 577 594 572Q582 567 578 558Q574 549 574 531V220Q574 108 508 48Q442 -12 317 -12Q86 -12 86 204Z"],"T":[567,"M117 59Q163 63 183 71Q203 79 210 99Q217 119 217 165V566Q159 564 136 556Q112 548 103 524Q94 499 87 435L5 429Q12 512 17 642L28 653L127 642H439L540 653L551 642Q553 522 561 435L479 429Q471 497 462 522Q454 547 432 556Q411 564 356 566Q351 492 348 365Q344 238 344 134Q344 97 357 81Q370 65 399 65Q424 65 452 68L456 63L447 -4Q341 0 275 0Q223 0 109 -6Z"],"R":[641,"M405 77 318 253H247L245 140Q245 105 250 90Q255 74 269 69Q283 64 317 63L320 57L311 -4Q293 -3 248 -2Q203 -1 165 -1Q128 -1 89 -3Q50 -5 38 -6L47 60Q89 65 104 82Q118 99 118 142V529Q118 558 112 568Q105 578 86 578Q75 578 65 577Q55 576 52 576L46 584L55 644Q69 644 106 643Q144 642 180 642Q220 642 266 644Q313 645 331 646Q445 646 506 602Q566 558 566 475Q566 416 531 367Q496 318 431 285L519 142Q547 96 573 76Q599 56 631 56L638 47L631 -5L514 -16Q449 -16 405 77ZM427 457Q427 512 390 539Q353 566 276 566Q266 566 262 562Q259 558 258 544Q252 441 250 340L340 330Q373 344 400 372Q427 399 427 457Z"],"A":[625,"M331 0 336 59Q370 62 386 66Q401 69 407 76Q413 82 413 95Q413 107 408 130L387 207Q335 209 295 209Q277 209 220 204L199 202L174 125Q168 103 168 94Q168 76 178 69Q189 62 215 62H258L263 55L256 -6Q242 -5 196 -2Q150 0 110 0Q68 0 34 -1Q1 -2 -10 -3L-3 62Q20 66 35 81Q50 96 63 130L242 637L395 653L406 648Q421 591 468 414Q516 238 550 131Q561 95 578 80Q595 65 629 62L633 55L626 -3Q613 -2 577 -1Q541 0 504 0Q451 0 400 -4Q350 -7 336 -8ZM295 286Q306 286 369 289L310 512H297L223 286Z"],"I":[365,"M44 55Q88 64 103 80Q118 97 118 139V526Q118 557 111 568Q104 578 82 578L47 577L42 585L50 643L188 642Q221 642 328 649L323 583Q285 578 272 568Q260 557 258 529Q245 293 245 132Q245 91 253 77Q261 63 284 63Q295 63 328 66L332 60L323 -3L287 -2L176 0Q130 0 38 -9Z"],"É":[596,"M557 189Q541 111 530 4L520 -7Q329 0 209 0Q125 0 38 -10L45 57Q87 63 102 81Q117 99 117 143L118 524Q118 557 112 568Q106 578 86 578Q73 578 55 576L49 585L57 645H77Q148 642 238 642Q461 642 542 654L550 643Q542 606 536 555Q529 504 527 462L438 456L440 496Q440 526 432 538Q423 551 398 556Q372 560 312 560Q286 560 276 558Q266 556 262 549Q259 542 258 526L251 369L345 368Q366 368 398 370Q429 373 461 377L469 368L455 283Q442 283 435 284Q365 286 324 286Q293 286 247 280L245 137Q245 109 250 97Q254 85 266 81Q279 77 310 77Q376 77 406 84Q435 92 448 115Q461 138 468 191L550 198ZM244 706 231 751Q298 781 366 814Q433 846 453 856L465 851L490 776L485 763Q465 758 396 740Q328 721 257 698Z"],"C":[616,"M29 303Q29 409 72 488Q115 567 194 610Q274 654 379 654Q416 654 458 648Q501 643 531 637Q561 631 569 629L575 616Q573 609 568 584Q563 559 557 517Q551 475 548 428L453 422Q453 426 454 440Q455 455 455 474Q455 518 428 538Q401 559 343 559Q264 559 222 503Q181 447 181 338Q181 215 226 147Q270 79 350 79Q405 79 436 112Q467 146 479 219L575 225Q572 208 564 150Q557 92 555 40L545 28Q545 27 512 16Q478 6 430 -3Q381 -12 326 -12Q235 -12 168 26Q101 64 65 135Q29 206 29 303Z"],"H":[747,"M46 55Q89 63 104 80Q118 97 118 139V526Q118 557 111 568Q104 578 82 578L52 577L47 585L54 643L173 642Q212 642 322 649L316 583Q290 579 278 572Q267 566 262 553Q258 540 256 511L250 367L381 365Q433 365 500 372V526Q500 557 493 568Q486 578 464 578L433 577L428 585L436 643L562 642Q595 642 707 649L702 584Q665 579 654 568Q642 558 640 529Q635 441 632 327Q628 213 628 136Q628 94 636 79Q645 64 669 64Q680 64 707 67L711 60L702 -3Q688 -3 681 -2Q605 0 558 0L420 -2L428 62Q457 63 472 71Q488 79 494 98Q500 118 500 155V284L390 285Q368 285 330 282Q292 279 248 275L245 132Q245 91 253 77Q261 63 284 63Q294 63 321 66L326 60L317 -3Q245 0 197 0Q163 0 114 -3Q64 -6 39 -9Z"],"F":[531,"M45 56Q88 63 102 81Q117 99 117 143L118 524Q118 556 112 567Q105 578 86 578Q76 578 67 577Q58 576 55 576L49 585L57 645Q75 644 126 643Q178 642 238 642Q443 642 519 654L527 643Q524 627 516 572Q509 518 506 460L417 455Q417 460 418 472Q419 484 419 496Q419 525 412 538Q404 551 382 556Q361 560 312 560Q286 560 276 558Q266 556 262 549Q259 542 258 526L251 352L345 351Q364 351 401 355Q438 359 450 360L457 351L443 266Q431 267 396 268Q362 269 324 269Q288 269 248 262L245 140Q245 102 254 89Q262 76 288 76Q304 76 325 78Q346 80 353 81L362 71L351 -4Q334 -3 288 -2Q241 0 195 0Q149 0 100 -4Q52 -9 38 -11Z"],"S":[539,"M45 26 37 40Q38 47 42 70Q45 94 49 134Q53 173 53 210L135 216Q135 160 145 130Q155 100 178 88Q202 75 246 75Q294 75 323 96Q352 117 352 154Q352 187 322 210Q291 233 227 264Q223 266 204 275Q129 311 87 351Q45 391 45 455Q45 512 79 558Q113 603 174 628Q234 654 311 654Q355 654 392 648Q430 642 452 636Q475 629 481 627L488 614Q487 608 482 584Q477 559 472 521Q467 483 464 443L390 437L381 443Q381 446 382 456Q383 465 383 479Q383 524 360 543Q338 562 285 562Q242 562 214 542Q187 521 187 489Q187 465 204 446Q222 426 246 412Q271 398 318 375Q374 348 410 326Q447 304 472 270Q497 236 497 189Q497 129 462 84Q428 38 366 13Q303 -12 220 -12Q174 -12 135 -4Q96 5 70 15Q45 25 45 26Z"],"P":[576,"M49 58Q90 65 104 82Q118 99 118 142V524Q118 556 112 567Q105 578 86 578Q75 578 65 577Q55 576 52 576L46 584L54 643L180 642Q218 642 264 644Q311 645 330 646Q458 646 514 592Q570 538 570 455Q570 396 536 344Q503 291 448 260Q393 228 331 228H247L245 152Q245 113 248 95Q252 77 262 70Q271 64 292 64Q306 64 319 65Q332 66 337 66L340 61L331 -3Q317 -3 280 -2Q242 0 207 0Q173 0 116 -3Q60 -6 41 -8ZM431 440Q431 504 395 534Q359 563 281 563Q267 563 264 560Q260 558 259 546Q253 456 249 316L338 303Q431 323 431 440Z"],"D":[694,"M167 0Q134 0 93 -4Q52 -8 40 -10L46 57Q89 64 104 82Q119 100 119 142V523Q119 555 113 566Q107 577 88 577Q77 577 67 576Q57 575 54 575L49 584L57 645Q71 645 109 644Q147 642 183 642Q227 642 275 644Q323 645 341 646Q441 646 514 610Q587 574 626 507Q665 440 665 347Q665 243 620 161Q576 79 497 34Q418 -12 318 -12Q302 -10 252 -5Q203 0 167 0ZM258 538Q245 259 245 145Q245 115 252 100Q259 84 278 78Q296 72 331 72Q419 72 466 134Q512 196 512 316Q512 443 456 502Q401 562 287 562Q271 562 265 557Q259 552 258 538Z"],"E":[596,"M557 189Q541 111 530 4L520 -7Q329 0 209 0Q125 0 38 -10L45 57Q87 63 102 81Q117 99 117 143L118 524Q118 557 112 568Q106 578 86 578Q73 578 55 576L49 585L57 645H77Q148 642 238 642Q461 642 542 654L550 643Q542 606 536 555Q529 504 527 462L438 456L440 496Q440 526 432 538Q423 551 398 556Q372 560 312 560Q286 560 276 558Q266 556 262 549Q259 542 258 526L251 369L345 368Q366 368 398 370Q429 373 461 377L469 368L455 283Q442 283 435 284Q365 286 324 286Q293 286 247 280L245 137Q245 109 250 97Q254 85 266 81Q279 77 310 77Q376 77 406 84Q435 92 448 115Q461 138 468 191L550 198Z"],"L":[530,"M51 57Q89 63 103 81Q117 99 117 143L118 526Q118 557 111 568Q104 578 82 578L51 577L46 585L54 643L188 642Q216 642 270 645Q323 648 340 649L333 580Q299 576 284 568Q268 561 264 548Q259 534 257 505Q246 355 246 138Q246 111 251 98Q256 86 269 82Q282 77 309 77Q359 77 384 88Q408 99 420 130Q432 161 440 228L521 237L528 227Q525 208 516 142Q508 75 502 2L492 -8Q465 -7 375 -4Q285 0 212 0Q157 0 107 -4Q57 -8 43 -10Z"],"'":[176,"M47 282 48 327Q48 388 44 442Q41 495 40 510L139 524L147 514Q144 495 134 430Q123 364 109 298L62 279Z"],"Q":[680,"M315 -12Q227 -12 162 26Q98 65 64 136Q29 207 29 304Q29 408 70 487Q111 566 186 610Q260 654 357 654Q447 654 512 616Q578 579 612 508Q647 438 647 341Q647 226 591 138Q535 51 442 14V5Q525 -53 591 -80Q657 -108 712 -108Q741 -108 766 -104Q790 -100 797 -98L804 -104L815 -145Q807 -151 780 -171Q754 -191 725 -210Q696 -228 684 -228Q638 -228 596 -212Q555 -196 493 -152Q431 -107 315 -12ZM494 289Q494 420 451 490Q408 559 329 559Q258 559 218 502Q179 446 179 343Q179 212 222 142Q264 73 341 73Q413 73 454 130Q494 186 494 289Z"],"G":[654,"M29 303Q29 411 72 490Q115 569 195 612Q275 654 384 654Q423 654 467 648Q511 643 542 637Q573 631 582 629L589 616Q587 610 582 586Q577 561 572 520Q566 480 563 434L467 427Q468 431 469 446Q470 461 470 482Q470 524 444 542Q419 559 360 559Q269 559 224 504Q179 450 179 337Q179 214 224 146Q270 79 351 79Q378 79 400 85Q422 91 434 98Q447 104 450 106V201Q450 230 441 240Q432 249 405 249H353L348 257L358 328Q382 328 399 327Q455 325 497 325Q528 325 558 327Q588 329 597 330L604 292Q587 281 578 264Q570 248 567 218Q564 187 564 128Q564 68 571 41L562 29Q562 28 528 17Q495 6 442 -3Q390 -12 327 -12Q235 -12 168 26Q101 64 65 135Q29 206 29 303Z"]}},"Pirata One":{"upm":1000,"asc":1006,"desc":-279,"lettres":{"R":[432,"M209 672Q191 672 170 657V332Q196 332 228 348Q260 365 260 383V598Q260 672 209 672ZM50 102V620Q50 681 9 689V711L110 768Q130 760 150 739Q170 718 170 701Q280 768 296 768Q312 768 346 727Q381 686 381 653V372Q381 364 272 321Q318 166 380 112Q408 89 437 89V59Q344 0 319 0Q286 0 236 124Q185 248 181 288L170 285V154Q170 117 178 101Q186 85 211 85V54L6 -32L-10 0Q12 0 32 26Q50 51 50 102Z"],"E":[404,"M188 673Q178 673 170 663V399H311V375L261 350H170V250Q170 139 192 120Q225 92 264 88Q303 84 348 84V55Q343 55 274 28Q205 0 190 0Q159 0 104 48Q50 96 50 152V678Q50 685 164 728Q279 770 296 770Q302 770 310 741Q318 712 328 671Q339 630 350 610Q362 591 394 591V571Q372 561 320 536Q267 510 263 510Q248 510 225 592Q202 673 188 673Z"],"L":[368,"M50 151V585Q50 622 42 638Q34 654 9 654V685L214 771L230 739Q208 739 188 713Q170 688 170 637V228Q170 148 184 132Q208 102 231 96Q284 84 348 84V56Q215 0 196 0Q178 0 146 16Q114 33 82 70Q50 107 50 151Z"],"S":[425,"M111 319Q86 319 68 357Q50 395 50 450V658Q50 677 155 724Q260 770 276 770Q288 770 310 730Q315 720 324 703Q334 686 340 675Q353 651 373 651V631Q357 624 330 610Q267 575 262 575Q247 575 224 634Q202 693 188 693Q170 693 170 663V440Q170 400 188 400Q192 400 250 426Q308 452 320 452Q344 452 362 414Q381 375 381 315V102Q381 83 266 36Q152 -10 135 -10Q128 -10 119 7Q110 24 96 56Q81 87 70 108Q58 129 38 129V149Q54 156 80 170Q144 205 149 205Q164 205 192 136Q219 67 233 67Q243 67 252 75Q261 83 261 97V322Q261 367 236 367Q228 367 173 343Q118 319 111 319Z"],"e":[425,"M295 570Q300 570 320 554Q340 539 360 512Q380 484 380 458V290Q380 272 327 246Q274 220 224 204Q175 187 171 187Q171 110 238 92Q271 84 317 84V55Q153 0 142 0Q112 0 81 42Q50 85 50 142V478Q50 485 164 528Q278 570 295 570ZM170 463V232Q260 257 260 340V411Q260 439 247 458Q234 478 214 478Q194 478 170 463Z"],"a":[410,"M360 438V155Q360 118 372 104Q384 89 409 83V61L300 0Q278 9 259 30Q240 50 240 67L115 0Q112 2 106 6Q100 9 86 20Q71 32 60 45Q30 78 30 120V284Q30 300 82 325Q134 350 186 366L239 383Q239 440 209 462Q179 485 93 485V515Q248 570 267 570Q300 570 330 527Q360 484 360 438ZM240 112V338Q215 329 202 323Q190 317 176 304Q150 280 150 221V156Q150 130 166 114Q181 97 200 97Q219 97 240 112Z"],"s":[405,"M96 219Q71 219 53 257Q35 295 35 350V458Q35 477 140 524Q245 570 261 570Q270 570 277 560Q284 549 288 542Q292 536 300 520Q309 505 315 495Q328 471 348 471V451Q332 444 306 430Q242 395 237 395Q222 395 204 444Q187 493 173 493Q155 493 155 463V340Q155 300 173 300Q177 300 235 326Q293 352 305 352Q329 352 348 314Q366 275 366 215V102Q366 83 252 36Q137 -10 120 -10Q113 -10 106 2Q100 15 88 41Q77 67 66 85Q53 109 33 109V129Q49 136 76 150Q139 185 144 185Q159 185 182 126Q204 67 218 67Q228 67 237 75Q246 83 246 97V222Q246 267 221 267Q213 267 158 243Q103 219 96 219Z"]}}}


def mot(texte, famille, taille, x=0.0, y=0.0, approche=0.0):
    """Contours d'un mot sur la ligne de base y, à partir de x → (chemin, avance)."""
    g = GLYPHES[famille]
    s = taille / g["upm"]
    cx, out = x, []
    for i, ch in enumerate(texte):
        if ch == " ":
            cx += 0.27 * taille
            continue
        av, d = g["lettres"][ch]
        out.append(chemin_transforme(d, (s, 0, 0, -s, cx, y)))
        cx += av * s + (approche * taille if i < len(texte) - 1 else 0)
    return "".join(out), cx - x


def boite_chemin(d, pas=0.4):
    xs, ys = [], []
    for pts, _ in aplatir(d, pas):
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def mot_centre(texte, famille, cx, y, largeur=None, taille=None, approche=0.0):
    """Mot centré (encre réelle) sur cx ; `largeur` fixe la largeur d'encre voulue."""
    taille = taille or 100.0
    d, _ = mot(texte, famille, taille, 0, 0, approche)
    x0, _, x1, _ = boite_chemin(d)
    if largeur:
        taille *= largeur / (x1 - x0)
        d, _ = mot(texte, famille, taille, 0, 0, approche)
        x0, _, x1, _ = boite_chemin(d)
    return mot(texte, famille, taille, cx - (x0 + x1) / 2, y, approche)[0], taille


# ════════════════════════════════════════════════════════════════════════════════════════
#  Ornements (SVG autonomes, couleurs figées ; un seul ton = utilisable en mask-image)
# ════════════════════════════════════════════════════════════════════════════════════════

def melange(c1, c2, t):
    a, b = hexa(c1), hexa(c2)
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))


def ecrire_ornement(nom, dessin, couleurs=None, titre=None, vb=None):
    D_ORNEMENTS.mkdir(parents=True, exist_ok=True)
    texte = svg_document(dessin, couleurs, titre, vb)
    verifier_svg(texte, nom)
    (D_ORNEMENTS / nom).write_text(texte, encoding="utf-8", newline="\n")
    return len(texte.encode())


def deplacer(dessin, tf):
    """Le même dessin sous une transformation de plus (appliquée en dernier)."""
    out = Dessin(dessin.l, dessin.h)
    for t in dessin.traces:
        out.traces.append(Trace(t.d, t.fill, t.stroke, t.sw, t.cap, t.join, t.eo,
                                f"{tf} {t.tf}" if t.tf else tf, t.op))
    return out


# ── Fleuron d'angle, cadre ───────────────────────────────────────────────────────────────

def fleuron(D, ox=0.0, oy=0.0, e=1.0, c="encre", sx=1, sy=1):
    """Fleuron gravé d'un coin (le coin est en (ox, oy) ; sx/sy = ±1 pour les autres coins)."""
    def P(x, y):
        return (ox + sx * x * e, oy + sy * y * e)

    for inv in (False, True):
        def Q(x, y, inv=inv):
            return P(y, x) if inv else P(x, y)
        D.plein(calame([Q(9.6, 6.4), Q(17, 4.6), Q(25.6, 5.2), Q(32, 8.2), Q(33.4, 13), Q(30, 16), Q(26.4, 14.2),
                        Q(27, 10.8), Q(29.4, 10.6)],
                       [x * e for x in (2.5, 2.3, 2.0, 1.7, 1.4, 1.1, 0.85, 0.6, 0.4)], k=10), c)
        D.plein(calame([Q(28, 5.6), Q(37, 4.2), Q(46.5, 5)], [1.15 * e, 0.75 * e, 0.3 * e],
                       bouts=("rond", "pointe")), c)
        D.plein(cercle(*Q(48.6, 5.3), 0.95 * e), c)
        D.plein(calame([Q(10.6, 9.2), Q(14.6, 10.6), Q(17.6, 14), Q(19.4, 18.4)], [0.4 * e, 1.5 * e, 1.2 * e, 0.3 * e],
                       bouts=("pointe", "pointe")), c)
    D.plein(calame([P(19.8, 19.8), P(22.2, 22.2), P(24.4, 24.4)], [0.4 * e, 2.3 * e, 0.3 * e],
                   bouts=("pointe", "pointe")), c)
    D.plein(cercle(*P(26.4, 26.4), 0.8 * e), c)
    D.plein(poly(etoile_pts(*P(6.4, 6.4), 6 * e, 1.5 * e, 4, rot=45)), c)
    D.plein(cercle(*P(6.4, 6.4), 1.5 * e), c)


def dessin_coin():
    D = Dessin(52, 52)
    fleuron(D, 1.5, 1.5)
    return D


def dessin_cadre():
    """Cadre complet pour border-image : tranches de 40, bords uniformes (étirables)."""
    D = Dessin(120, 120)
    D.trait(rect(3, 3, 114, 114), 2.2)
    D.trait(rect(8.2, 8.2, 103.6, 103.6), 0.8)
    for (ox, sx), (oy, sy) in (((10, 1), (10, 1)), ((110, -1), (10, 1)), ((10, 1), (110, -1)), ((110, -1), (110, -1))):
        fleuron(D, ox, oy, 0.62, sx=sx, sy=sy)
    return D


# ── Corde ───────────────────────────────────────────────────────────────────────────────

def dessin_corde():
    """Corde torse à trois torons, raccord horizontal parfait (période 8, tuile 24 × 12)."""
    D = Dessin(24, 12)
    y0, y1, p = 1.0, 11.0, 8.0
    rainure = f"M0 {n(y1)}C0.3 {n(y1 - 3.8)} 5.9 {n(y0 + 3.8)} 6.2 {n(y0)}"
    brin = (f"M0 {n(y1)}C0.3 {n(y1 - 3.8)} 5.9 {n(y0 + 3.8)} 6.2 {n(y0)}L{n(p + 6.2)} {n(y0)}"
            f"C{n(p + 5.9)} {n(y0 + 3.8)} {n(p + 0.3)} {n(y1 - 3.8)} {n(p)} {n(y1)}Z")
    centre = (0.0, 0.0)
    creux = hachures(F(brin) - F(brin, tf="translate(-2.3 0)"), -58, 0.62, marge=0.12, lmin=0.3, centre=centre)
    dessous = hachures(F(brin) & F(rect(-2, 7.4, 22, 5)) & F(brin, tf="translate(-2.3 0)"), -58, 1.05,
                       marge=0.2, lmin=0.3, centre=centre)
    reflet = masquer(rainure, lambda x, y: y > 7.6)
    for k in range(-2, 4):
        tf = f"translate({n(k * p)} 0)"
        D.plein(brin, CORDE, tf=tf)
        for dx in (3.2, 5.2):
            D.trait(rainure, 0.4, "#86693f", tf=f"translate({n(k * p + dx)} 0)", op=0.75)
        D.trait(reflet, 0.65, "#ead9b1", tf=f"translate({n(k * p + 1.5)} 0)", op=0.9)
        D.trait(creux, 0.42, "encre", tf=tf, op=0.85)
        D.trait(dessous, 0.45, "encre", tf=tf, op=0.7)
        D.trait(rainure, 1.0, tf=tf)
    D.trait(ligne(-1, y0, 25, y0), 0.95)
    D.trait(ligne(-1, y1, 25, y1), 0.95)
    return D


# ── Sceaux de cire ──────────────────────────────────────────────────────────────────────

def dessin_sceau(base, graine=7):
    D = Dessin(64, 64)
    fonce, clair = melange(base, "#000000", 0.38), melange(base, "#ffffff", 0.28)
    c = (32, 32.4)
    contour = cachet(*c, 27.2, graine, lobes=9, amp=0.06)
    D.plein(contour, "#1a0f08", tf="translate(1.3 1.7)", op=0.28)
    D.plein(contour, base)
    bord = gonfler(contour, -2.1)
    D.trait(masquer(bord, lambda x, y: x + y > 61), 1.7, clair, op=0.75)
    D.trait(masquer(bord, lambda x, y: x + y < 67), 1.9, fonce, op=0.6)
    D.plein(cercle(*c, 19.4), fonce, op=0.32)
    anneau = cercle(*c, 19.4)
    D.trait(masquer(anneau, lambda x, y: x + y > 66), 2.1, fonce, op=0.85)
    D.trait(masquer(anneau, lambda x, y: x + y < 62), 1.5, clair, op=0.8)
    D.trait(cercle(*c, 16.6), 0.8, fonce, op=0.6)
    for k in range(28):
        a = 2 * math.pi * k / 28
        D.plein(cercle(c[0] + 18 * math.cos(a), c[1] + 18 * math.sin(a), 0.55), fonce, op=0.55)
    return D


# ── Tampons d'encre ─────────────────────────────────────────────────────────────────────

class _Bruit:
    """Bruit lisse déterministe (somme de sinus) pour faire trembler les contours."""

    def __init__(self, graine, ondes=((7, 0.55), (13, 0.32), (3.2, 0.18))):
        rnd = random.Random(graine)
        self.t = []
        for lg, amp in ondes:
            for _ in range(3):
                a = rnd.uniform(0, math.pi)
                k = 2 * math.pi / (lg * rnd.uniform(0.8, 1.25))
                self.t.append((k * math.cos(a), k * math.sin(a), rnd.uniform(0, 6.3), amp / 1.7))

    def __call__(self, x, y):
        return sum(a * math.sin(kx * x + ky * y + ph) for kx, ky, ph, a in self.t)


def _trembler(d, bruit, amp, pas=0.7):
    """Polygones du chemin, chaque sommet poussé le long de sa normale par le bruit."""
    out = []
    for pts, _ in aplatir(d, pas):
        if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        q = []
        for i in range(len(pts)):
            (ax, ay), (bx, by) = pts[i - 1], pts[(i + 1) % len(pts)]
            tx, ty = bx - ax, by - ay
            lg = math.hypot(tx, ty) or 1
            v = bruit(*pts[i]) * amp
            q.append((pts[i][0] + ty / lg * v, pts[i][1] - tx / lg * v))
        out.append(q)
    return out


def dessin_tampon(texte, forme="rect", angle=-8.0, graine=1, couleur=CIRE):
    """Tampon encreur : cadre double, lettres capitales, encre irrégulière (bords qui
    tremblent, manques d'encre, éclaboussures), incliné. Une seule couleur."""
    lettres, _ = mot_centre(texte, "Alegreya SC", 0, 0, taille=40.0, approche=0.06)
    x0, y0, x1, y1 = boite_chemin(lettres)
    hl, hh = (x1 - x0) / 2, (y1 - y0) / 2
    cy = (y0 + y1) / 2
    morceaux = [(lettres, None, "nz")]
    if forme == "rond":
        R = max(hl + 13, 34.0)
        morceaux.append((cercle(0, cy, R) + cercle(0, cy, R - 4.6), None, "eo"))
        morceaux.append((cercle(0, cy, R - 7.4) + cercle(0, cy, R - 9.1), None, "eo"))
        for s in (-1, 1):
            morceaux.append((poly(etoile_pts(0, cy + s * (R - 15.4), 3.1, 1.3, 5)), None, "eo"))
    else:
        L, H = hl + 15, hh + 12
        morceaux.append((rect(-L, cy - H, 2 * L, 2 * H, 6) + rect(-L + 4.4, cy - H + 4.4, 2 * L - 8.8, 2 * H - 8.8, 2.6),
                         None, "eo"))
        morceaux.append((rect(-L + 7, cy - H + 7, 2 * L - 14, 2 * H - 14, 1.2)
                         + rect(-L + 8.6, cy - H + 8.6, 2 * L - 17.2, 2 * H - 17.2, 0.6), None, "eo"))
    m = m_rot(angle, 0, cy)
    polys = encrer([(d, m, mode) for d, _, mode in morceaux], graine, angle=angle)
    rnd = random.Random(graine * 5 + 1)
    xs = [p[0] for q in polys for p in q]
    ys = [p[1] for q in polys for p in q]
    cx_, cy_ = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    rx_, ry_ = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
    gouttes = []
    for _ in range(9):
        a = rnd.uniform(0, 2 * math.pi)
        dd = rnd.uniform(1.03, 1.12)
        gouttes.append(cercle(cx_ + rx_ * dd * math.cos(a), cy_ + ry_ * dd * math.sin(a), rnd.uniform(0.35, 0.8)))
    vb = (math.floor(min(xs)) - 3, math.floor(min(ys)) - 3)
    vb = vb + (math.ceil(max(xs)) + 3 - vb[0], math.ceil(max(ys)) + 3 - vb[1])
    D = Dessin(vb[2], vb[3])
    D.plein(_polys_d(polys), couleur)
    D.plein("".join(gouttes), couleur)
    return D, vb


# ── Ruban, rose des vents, filet, clou, étiquette ────────────────────────────────────────

def dessin_ruban(devant=PARCHEMIN, dos="#d2bb8a", pli="#a88f62", filet=ENCRE):
    """Ruban de titre (240 × 64) pour border-image : tranches 48 | 144 | 48, milieu uniforme."""
    D = Dessin(240, 64)
    for s in (1, -1):
        def X(x):
            return x if s == 1 else 240 - x
        queue = poly([(X(2), 22), (X(46), 22), (X(46), 58), (X(2), 58), (X(13.5), 40)])
        D.plein(queue, dos)
        D.hach(F(queue), 90 + 20 * s, 2.2, sw=0.6, marge=0.6, centre=(120, 32))
        D.trait(queue, 1.5, filet)
        D.plein(poly([(X(34), 50), (X(46), 50), (X(46), 58)]), pli)
        D.trait(poly([(X(34), 50), (X(46), 50), (X(46), 58)]), 1.2, filet)
    D.plein(rect(34, 8, 172, 42), devant)
    D.trait(ligne(34, 8, 206, 8), 1.6, filet)
    D.trait(ligne(34, 50, 206, 50), 1.6, filet)
    D.trait(ligne(34, 8, 34, 50), 1.6, filet)
    D.trait(ligne(206, 8, 206, 50), 1.6, filet)
    D.trait(ligne(38, 12.4, 202, 12.4), 0.7, filet)
    D.trait(ligne(38, 45.6, 202, 45.6), 0.7, filet)
    return D


def _pointe_rose_grande(D, c, a, lg, lw, op_clair=0.22):
    co, si = math.cos(a), math.sin(a)
    tip = (c[0] + lg * co, c[1] + lg * si)
    g = (c[0] - lw * si, c[1] + lw * co)
    d = (c[0] + lw * si, c[1] - lw * co)
    D.plein(poly([tip, c, g]), "encre")
    D.plein(poly([tip, c, d]), "encre", op=op_clair)
    D.trait(poly([tip, g, c, d]), 1.1)


def dessin_rose():
    D = Dessin(400, 400)
    c = (200.0, 200.0)
    D.trait(cercle(*c, 194), 2.4)
    D.trait(cercle(*c, 186), 0.9)
    D.trait(cercle(*c, 172), 0.7)
    for k in range(180):
        a = math.radians(k * 2)
        r0 = 176 if k % 5 else 172
        D.trait(ligne(c[0] + r0 * math.cos(a), c[1] + r0 * math.sin(a), c[0] + 186 * math.cos(a),
                      c[1] + 186 * math.sin(a)), 0.9 if k % 5 else 1.3)
    for k in range(32):
        a = math.radians(k * 11.25)
        D.trait(ligne(c[0] + 64 * math.cos(a), c[1] + 64 * math.sin(a), c[0] + 172 * math.cos(a),
                      c[1] + 172 * math.sin(a)), 0.5, op=0.6)
    D.trait(cercle(*c, 112), 0.8)
    D.trait(cercle(*c, 64), 0.8)
    for nb, lg, lw, dec in ((16, 98, 7.5, 11.25), (8, 128, 11, 22.5), (4, 150, 17, 45), (4, 176, 23, 0)):
        for k in range(nb):
            a = math.radians(dec + k * 360 / nb - 90)
            _pointe_rose_grande(D, c, a, 124 if (lg == 176 and k == 0) else lg, lw)
    fleur_de_lys(D, 200, 31, 45)
    D.plein(cercle(*c, 7))
    D.trait(cercle(*c, 11), 1.2)
    return D


def dessin_filet():
    D = Dessin(320, 24)
    c = (160.0, 12.0)
    for s in (-1, 1):
        D.plein(calame([(c[0] + s * 14, 12), (c[0] + s * 60, 12), (c[0] + s * 124, 12)], [2.4, 1.4, 0.3],
                       bouts=("rond", "pointe")))
        for v in (-1, 1):
            D.plein(calame([(c[0] + s * 15, 12 + v * 0.4), (c[0] + s * 21.5, 12 + v * 3.4), (c[0] + s * 28.2, 12 + v * 5.4),
                            (c[0] + s * 32, 12 + v * 3.6), (c[0] + s * 31, 12 + v * 0.9), (c[0] + s * 28.4, 12 + v * 1.4),
                            (c[0] + s * 28.6, 12 + v * 2.9)],
                           [1.8, 1.5, 1.2, 0.95, 0.75, 0.55, 0.35], k=8))
        D.plein(cercle(c[0] + s * 129, 12, 1.4))
    D.plein(poly(etoile_pts(*c, 9.6, 2.2, 4)))
    D.plein(poly(etoile_pts(*c, 5.4, 1.4, 4, rot=-45)))
    D.trait(cercle(*c, 4.2), 0.8)
    return D


def dessin_clou():
    D = Dessin(24, 24)
    tete = cachet(11.6, 11.6, 7.6, graine=4, lobes=5, amp=0.045)
    D.plein(tete, "#120b06", tf="translate(1.2 1.5)", op=0.35)
    D.plein(tete, "#3b332b")
    bord = gonfler(tete, -1.3)
    D.trait(masquer(bord, lambda x, y: x + y > 22.4), 1.7, "#7a6c5d", op=0.9)
    D.trait(masquer(bord, lambda x, y: x + y < 24.6), 1.5, "#1d1712", op=0.9)
    D.trait("M8.6 9.4L13.6 8.4M9.4 13.8L15 11.6", 0.7, "#24201b")
    D.plein(ellipse(9.2, 8.8, 1.5, 1), "#a8998a", op=0.85)
    return D


def dessin_etiquette():
    """Étiquette de malle (160 × 48) pour onglets : border-image 0 16 0 40, milieu uniforme."""
    D = Dessin(160, 48)
    corps = "M19 4H153A5 5 0 0 1 158 9V39A5 5 0 0 1 153 44H19L5 30V18Z"
    D.trait("M15.4 22.6C9 14.6 4.6 11 -2 9.6", 1.6, CORDE)
    D.plein(corps + cercle(17, 24, 2.6), "#ead8ad", eo=True)
    D.trait(corps, 1.6)
    D.trait("M41 8.6H150.6A3.2 3.2 0 0 1 153.6 11.8V36.2A3.2 3.2 0 0 1 150.6 39.4H41", 0.7, op=0.8)
    D.plein(cercle(17, 24, 5) + cercle(17, 24, 2.6), "ton2", eo=True)
    D.trait(cercle(17, 24, 5), 1.1)
    D.trait(cercle(17, 24, 2.6), 0.9)
    return D


def dessin_symbole_prime():
    D = Dessin(12.6, 19.4)
    corps, barre = baht(1.6, 2.6, 14, 1)
    D.plein(corps, eo=True)
    D.plein(barre)
    return D


def ecrire_ornements():
    t = {}
    t["coin.svg"] = ecrire_ornement("coin.svg", dessin_coin())
    t["cadre.svg"] = ecrire_ornement("cadre.svg", dessin_cadre())
    corde = dessin_corde()
    t["corde.svg"] = ecrire_ornement("corde.svg", corde)
    v = deplacer(corde, "matrix(0 1 -1 0 12 0)")
    v.l, v.h = 12, 24
    t["corde-v.svg"] = ecrire_ornement("corde-v.svg", v)
    for nom, base, g in (("rouge", CIRE, 7), ("vert", VERT, 8), ("ambre", AMBRE, 9)):
        t[f"sceau-{nom}.svg"] = ecrire_ornement(f"sceau-{nom}.svg", dessin_sceau(base, g))
    for nom, texte, forme, angle, graine, coul in (
            ("vu", "VU", "rond", -10, 3, MER), ("traite", "TRAITÉ", "rect", -7, 5, ENCRE),
            ("archive", "ARCHIVÉ", "rect", 5, 8, AMBRE), ("refuse", "REFUSÉ", "rect", -9, 11, CIRE),
            ("accepte", "ACCEPTÉ", "rect", -6, 13, VERT)):
        D, vb = dessin_tampon(texte, forme, angle, graine, coul)
        t[f"tampon-{nom}.svg"] = ecrire_ornement(f"tampon-{nom}.svg", D, vb=vb)
    t["ruban.svg"] = ecrire_ornement("ruban.svg", dessin_ruban())
    t["ruban-cire.svg"] = ecrire_ornement("ruban-cire.svg", dessin_ruban("#9a3027", "#77231c", "#561914"))
    t["rose-des-vents.svg"] = ecrire_ornement("rose-des-vents.svg", dessin_rose())
    t["filet.svg"] = ecrire_ornement("filet.svg", dessin_filet())
    t["clou.svg"] = ecrire_ornement("clou.svg", dessin_clou())
    t["etiquette.svg"] = ecrire_ornement("etiquette.svg", dessin_etiquette())
    t["symbole-prime.svg"] = ecrire_ornement("symbole-prime.svg", dessin_symbole_prime())
    if "ecrire_affiche" in globals():
        t.update(ecrire_affiche())
    for nom, o in t.items():
        print(f"[DESSINS] ornements/{nom} : {o // 1024 or 1} Ko")


def fleur_de_lys(D, cx, haut, h, c="encre"):
    s = h / 44.0
    D.plein(calame([(cx, haut + 30 * s), (cx, haut + 17 * s), (cx, haut + 7 * s), (cx, haut)],
                   [2.4 * s, 8.6 * s, 6 * s, 0.4 * s], bouts=("rond", "pointe")), c)
    for g in (-1, 1):
        D.plein(calame([(cx + g * 2 * s, haut + 29 * s), (cx + g * 7.5 * s, haut + 24 * s), (cx + g * 12.5 * s, haut + 15 * s),
                        (cx + g * 16.5 * s, haut + 12.5 * s), (cx + g * 18.4 * s, haut + 16.5 * s),
                        (cx + g * 15.6 * s, haut + 20 * s)],
                       [3.2 * s, 4.6 * s, 4.4 * s, 3 * s, 1.6 * s, 0.5 * s], k=10), c)
        D.plein(calame([(cx + g * 1.6 * s, haut + 34 * s), (cx + g * 6.5 * s, haut + 38 * s), (cx + g * 10.5 * s, haut + 37.4 * s),
                        (cx + g * 11 * s, haut + 35 * s)], [2.6 * s, 2.4 * s, 1.4 * s, 0.4 * s]), c)
    D.plein(rect(cx - 8.5 * s, haut + 30 * s, 17 * s, 3.6 * s, 1 * s), c)
    D.plein(calame([(cx, haut + 33.6 * s), (cx, haut + 40 * s), (cx, haut + 44 * s)], [3 * s, 2.2 * s, 0.4 * s],
                   bouts=("rond", "pointe")), c)


# ════════════════════════════════════════════════════════════════════════════════════════
#  Textures (numpy) : synthèse spectrale périodique → raccords invisibles
# ════════════════════════════════════════════════════════════════════════════════════════

def _np():
    if np is None:
        raise SystemExit("[DESSINS] les textures demandent numpy (pip install numpy)")
    return np


def bruit(h, w, graine, beta=2.0, fmin=1.0, fmax=None, aniso=(1.0, 1.0)):
    """Bruit fractal périodique (spectre en 1/f^beta), moyenne 0, écart-type 1."""
    _np()
    rng = np.random.default_rng(graine)
    fy = np.fft.fftfreq(h)[:, None] * h
    fx = np.fft.rfftfreq(w)[None, :] * w
    f = np.sqrt((fx * aniso[0]) ** 2 + (fy * aniso[1]) ** 2)
    m = f >= fmin
    if fmax:
        m &= f <= fmax
    amp = np.zeros_like(f)
    amp[m] = f[m] ** (-beta / 2)
    spec = (rng.standard_normal(f.shape) + 1j * rng.standard_normal(f.shape)) * amp
    x = np.fft.irfft2(spec, s=(h, w))
    return (x - x.mean()) / (x.std() + 1e-9)


def flou(a, sigma):
    """Flou gaussien périodique (le raccord reste parfait)."""
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    g = np.exp(-2 * (np.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.fft.irfft2(np.fft.rfft2(a) * g, s=(h, w))


def colorer(v, paliers):
    """Valeurs → RVB par paliers [(position, '#hex')]."""
    pos = [p for p, _ in paliers]
    out = np.zeros(v.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(v, pos, [hexa(h)[c] for _, h in paliers])
    return out


def fibres(h, w, graine, nombre, longueur=(5, 22), direction=0.25, dispersion=0.9, epais=(1, 1, 2)):
    """Fibres courtes et courbes, dessinées avec recouvrement des bords (tuile)."""
    rnd = random.Random(graine)
    S = 2
    im = Image.new("L", (w * S, h * S), 0)
    dr = ImageDraw.Draw(im)
    for _ in range(nombre):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        a = rnd.gauss(direction, dispersion)
        lg = rnd.uniform(*longueur)
        k = rnd.uniform(-0.06, 0.06)
        pts = []
        px, py = x, y
        for i in range(7):
            pts.append((px, py))
            ang = a + k * i
            px += math.cos(ang) * lg / 6
            py += math.sin(ang) * lg / 6
        v = rnd.randint(70, 255)
        e = rnd.choice(epais)
        for dx in (-w, 0, w):
            for dy in (-h, 0, h):
                if min(p[0] for p in pts) + dx > w + 2 or max(p[0] for p in pts) + dx < -2:
                    continue
                if min(p[1] for p in pts) + dy > h + 2 or max(p[1] for p in pts) + dy < -2:
                    continue
                dr.line([((p[0] + dx) * S, (p[1] + dy) * S) for p in pts], fill=v, width=e)
    return np.asarray(im.resize((w, h), Image.BOX), np.float32) / 255.0


def taches_rondes(h, w, graine, nombre, rayon=(1.5, 5), periodique=True):
    """Petites rousseurs (piqûres brunes) avec un halo."""
    rnd = random.Random(graine)
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    for _ in range(nombre):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        r = rnd.uniform(*rayon)
        v = rnd.randint(90, 255)
        for dx in ((-w, 0, w) if periodique else (0,)):
            for dy in ((-h, 0, h) if periodique else (0,)):
                dr.ellipse((x + dx - r, y + dy - r * rnd.uniform(0.7, 1), x + dx + r, y + dy + r), fill=v)
    a = np.asarray(im, np.float32) / 255.0
    return 0.6 * a + 0.8 * flou(a, 2.5) if periodique else a


def ecrire_webp(nom, rgb, alpha=None, qualite=82, alpha_q=80, limite=120 * 1024, sans_perte=False):
    D_TEXTURES.mkdir(parents=True, exist_ok=True)
    arr = np.clip(rgb, 0, 255).astype(np.uint8)
    im = Image.fromarray(arr, "RGB")
    if alpha is not None:
        im.putalpha(Image.fromarray(np.clip(alpha * 255, 0, 255).astype(np.uint8), "L"))
    q = qualite
    while True:
        chemin = D_TEXTURES / nom
        if sans_perte:  # dessin au trait : le sans-perte est plus léger et exact
            im.save(chemin, "WEBP", lossless=True, quality=100, method=6)
        else:
            im.save(chemin, "WEBP", quality=q, method=6, alpha_quality=alpha_q)
        taille = chemin.stat().st_size
        if taille <= limite or q <= 50 or sans_perte:
            break
        q -= 4
    mode = "sans perte" if sans_perte else f"q={q}"
    print(f"[DESSINS] textures/{nom} : {im.width}×{im.height}, {taille // 1024} Ko ({mode})")
    return taille


def texture_parchemin(taille=768, graine=11, fonce=False):
    h = w = taille
    marbre = bruit(h, w, graine, beta=3.1, fmin=1, fmax=48)
    moyen = bruit(h, w, graine + 1, beta=1.6, fmin=24, fmax=260)
    fin = flou(np.random.default_rng(graine + 2).standard_normal((h, w)), 0.55)
    fin /= fin.std()
    clairs = fibres(h, w, graine + 3, 1700 if not fonce else 1300)
    sombres = fibres(h, w, graine + 4, 900, longueur=(4, 14), direction=0.4)
    t = bruit(h, w, graine + 5, beta=3.4, fmin=1, fmax=20)
    seuil = 1.45 if not fonce else 1.3
    tache = np.clip((t - seuil) * (1.6 if not fonce else 1.1), 0, 1)
    aureole = np.clip(1 - np.abs(t - seuil) * 9, 0, 1)
    rousseurs = taches_rondes(h, w, graine + 6, 26 if not fonce else 40)
    v = (0.835 + 0.030 * marbre + 0.016 * moyen + 0.016 * fin + 0.05 * clairs - 0.06 * sombres
         - (0.07 if not fonce else 0.05) * tache - (0.045 if not fonce else 0.03) * aureole - 0.05 * rousseurs)
    if fonce:
        v -= 0.075 + 0.018 * marbre
    paliers = [(0.50, "#8e6a3a"), (0.62, "#b8955c"), (0.70, "#d6bd8a"), (0.78, "#e6d4ab"),
               (0.84, "#efe2c4"), (0.92, "#f7eedb")]
    return colorer(v, paliers)


def texture_bois(w=1024, h=512, graine=21):
    rng = random.Random(graine)
    planches = [118, 134, 126, 134]
    lent = bruit(h, w, graine, beta=3.0, fmin=1, fmax=12, aniso=(3.0, 1.0))
    ondule = bruit(h, w, graine + 1, beta=2.4, fmin=2, fmax=48, aniso=(9.0, 1.0))
    pores = bruit(h, w, graine + 2, beta=1.1, fmin=6, fmax=480, aniso=(36.0, 1.0))
    grain = flou(np.random.default_rng(graine + 3).standard_normal((h, w)), 0.6)
    grain /= grain.std()
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
    phi = np.zeros((h, w), np.float32)
    ton = np.zeros((h, w), np.float32)
    bords = np.zeros((h, w), np.float32)
    joints = np.zeros((h, w), np.float32)
    y_a = 0
    for i, hp in enumerate(planches):
        y_b = y_a + hp
        dans = (Y >= y_a) & (Y < y_b)
        anneaux = rng.uniform(5.5, 8.5)
        local = (Y - y_a) / hp
        p = local * anneaux + 1.9 * lent + 0.55 * ondule + rng.uniform(0, 10)
        for _ in range(rng.choice((0, 1, 1))):
            kx, ky = rng.uniform(0, w), y_a + rng.uniform(0.3, 0.7) * hp
            dx = (X - kx + w / 2) % w - w / 2
            dy = Y - ky
            sx, sy = rng.uniform(20, 32), rng.uniform(9, 14)
            r2 = (dx / sx) ** 2 + (dy / sy) ** 2
            p = p + 2.6 * np.exp(-r2 * 0.55) * np.sign(dy + 0.01)
            ton = ton - dans * 0.10 * np.exp(-r2 * 2.2)
            phi_k = np.sqrt(r2) * 3.2
            ton = ton - dans * 0.10 * np.exp(-r2 * 0.8) * (0.5 + 0.5 * np.cos(phi_k * 2 * np.pi))
        phi = np.where(dans, p, phi)
        ton = ton + dans * rng.uniform(-0.07, 0.07)
        d_haut, d_bas = Y - y_a, y_b - 1 - Y
        bords = np.maximum(bords, dans * (np.exp(-np.minimum(d_haut, d_bas) / 5.0)))
        jx = rng.uniform(0, w)
        dj = np.abs((X - jx + w / 2) % w - w / 2)
        joints = np.maximum(joints, dans * np.exp(-dj / 1.6))
        y_a = y_b
    r = phi - np.floor(phi)
    tardif = np.exp(-((r - 0.86) / 0.07) ** 2)
    initial = 0.5 + 0.5 * np.cos(2 * np.pi * r)
    v = (0.62 + 0.08 * initial - 0.28 * tardif + 0.07 * pores + 0.035 * grain + ton
         - 0.32 * bords - 0.5 * joints)
    for y_c in np.cumsum([0] + planches[:-1]):
        d = np.abs((Y - y_c + h / 2) % h - h / 2)
        v = v - 0.75 * np.exp(-(d / 1.3) ** 2)
        v = v + 0.10 * np.exp(-((Y - y_c - 2.6) % h / 1.4) ** 2)
    rayures = fibres(h, w, graine + 7, 140, longueur=(10, 60), direction=0.0, dispersion=0.25)
    v = v + 0.06 * rayures
    paliers = [(-0.2, "#0f0804"), (0.2, "#24150b"), (0.42, "#3a2414"), (0.58, "#4a2e1a"),
               (0.72, "#5d3b22"), (0.9, "#734c2e")]
    return colorer(v, paliers)


def _bord_dechire(h, w, graine, marge=(10, 26)):
    """Masque d'une feuille aux bords irréguliers et déchirés (1 dedans, 0 dehors)."""
    rnd = np.random.default_rng(graine)
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)

    def profil(n, ech):
        b = np.zeros(n)
        for k, a in ((3, 5.0), (9, 2.4), (27, 1.2), (81, 0.6), (240, 0.35)):
            ph = rnd.uniform(0, 2 * np.pi, 3)
            t = np.arange(n) / n
            b += a * (np.sin(2 * np.pi * k * t + ph[0]) * 0.6 + np.sin(2 * np.pi * (k * 1.7) * t + ph[1]) * 0.4)
        return b * ech
    g = marge[0] + 4 + profil(h, 1.0)[:, None]
    d = w - marge[0] - 4 - profil(h, 1.0)[:, None]
    hh = marge[0] + 4 + profil(w, 1.0)[None, :]
    bb = h - marge[0] - 4 - profil(w, 1.0)[None, :]
    m = (X > g) & (X < d) & (Y > hh) & (Y < bb)
    m = m.astype(np.float32)
    for _ in range(7):  # petites déchirures en V
        cote = rnd.integers(4)
        pos = rnd.uniform(0.12, 0.88)
        prof, larg = rnd.uniform(10, marge[1]), rnd.uniform(6, 16)
        if cote in (0, 1):
            cx = pos * w
            cy = 0 if cote == 0 else h
            dist = np.abs(X - cx) / larg + np.abs(Y - cy) / prof
        else:
            cy = pos * h
            cx = 0 if cote == 2 else w
            dist = np.abs(Y - cy) / larg + np.abs(X - cx) / prof
        m = m * (dist > 1.0)
    coin = np.clip(((w - X) + (h - Y) - 54 + 5 * np.sin(X / 7.0) * np.cos(Y / 5.0)) / 1.5, 0, 1)
    m = m * coin
    a = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    return np.asarray(a, np.float32) / 255.0


def texture_papier_affiche(w=840, h=1176, graine=31):
    marbre = bruit(h, w, graine, beta=3.0, fmin=1, fmax=40)
    moyen = bruit(h, w, graine + 1, beta=1.5, fmin=30, fmax=300)
    fin = flou(np.random.default_rng(graine + 2).standard_normal((h, w)), 0.5)
    fin /= fin.std()
    clairs = fibres(h, w, graine + 3, 2600, longueur=(3, 12), dispersion=1.6)
    t = bruit(h, w, graine + 5, beta=3.3, fmin=1, fmax=16)
    tache = np.clip((t - 1.35) * 1.4, 0, 1)
    aureole = np.clip(1 - np.abs(t - 1.35) * 8, 0, 1)
    rousseurs = taches_rondes(h, w, graine + 6, 60, (1.2, 4), periodique=False)
    rousseurs = flou(rousseurs, 1.2) * 1.6 + rousseurs * 0.4
    masque = _bord_dechire(h, w, graine + 8)
    # brûlure des bords : distance (approchée) au bord par flou du masque
    m_flou = flou(masque, 26)
    brule = np.clip(1 - m_flou * 1.18, 0, 1) ** 1.35
    brule = brule * (0.75 + 0.35 * bruit(h, w, graine + 9, beta=2.2, fmin=4, fmax=90))
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
    vign = ((X / w - 0.5) ** 2 + (Y / h - 0.5) ** 2)
    # plis : un vertical, un horizontal, et quelques froissures
    pli_v = np.exp(-((X - w * 0.5 - 1.6 * bruit(h, w, graine + 10, 3, 1, 4)) / 1.5) ** 2)
    pli_h = np.exp(-((Y - h * 0.44 - 1.6 * bruit(h, w, graine + 11, 3, 1, 4)) / 1.5) ** 2)
    ombre_pli = (np.exp(-np.clip(X - w * 0.5, 0, None) / 22) * (X > w * 0.5)
                 + np.exp(-np.clip(Y - h * 0.44, 0, None) / 22) * (Y > h * 0.44))
    v = (0.80 + 0.035 * marbre + 0.018 * moyen + 0.02 * fin + 0.04 * clairs - 0.10 * tache
         - 0.05 * aureole - 0.06 * rousseurs - 0.42 * brule - 0.12 * vign
         - 0.10 * (pli_v + pli_h) - 0.03 * ombre_pli)
    v = v + 0.05 * np.exp(-((X - w * 0.5 + 2.4) / 1.4) ** 2) + 0.05 * np.exp(-((Y - h * 0.44 + 2.4) / 1.4) ** 2)
    paliers = [(0.30, "#4a2c12"), (0.45, "#7c5528"), (0.58, "#b08848"), (0.68, "#d2b47a"),
               (0.76, "#e2cb98"), (0.84, "#ecdbb2"), (0.92, "#f4e8c9")]
    return colorer(v, paliers), masque


def texture_vignette(taille=512, graine=41):
    h = w = taille
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = np.abs(X / (w - 1) * 2 - 1), np.abs(Y / (h - 1) * 2 - 1)
    d = (u ** 6 + v ** 6) ** (1 / 6)
    n = bruit(h, w, graine, beta=3.0, fmin=1, fmax=10)
    a = np.clip((d - 0.5 + 0.025 * n) / 0.5, 0, 1) ** 2.2 * 0.27
    a = a + 0.06 * np.clip((d - 0.9 + 0.015 * n) / 0.1, 0, 1)
    rgb = np.zeros((h, w, 3), np.float32) + np.array(hexa("#3a2210")[:3], np.float32)
    return rgb, np.clip(a, 0, 0.6)


def texture_carte_marine(w=1600, h=1000, graine=51):
    """Carte marine en filigrane : îles, lignes d'eau, rhumbs, rose, graduations (alpha)."""
    terre = bruit(h, w, graine, beta=3.6, fmin=1.5, fmax=60)
    terre = terre + 0.7 * bruit(h, w, graine + 1, beta=2.0, fmin=20, fmax=200) * 0.25
    iles = (terre > 1.55).astype(np.float32)
    lisse_ = np.asarray(Image.fromarray((iles * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)),
                        np.float32) / 255.0
    traits = np.zeros((h, w), np.float32)
    eau = np.zeros((h, w), np.float32)
    cote = np.clip(1 - np.abs(lisse_ - 0.5) * 5, 0, 1)
    traits = np.maximum(traits, cote)
    for rayon, niveau, poids in ((6, 0.22, 0.75), (12, 0.12, 0.55), (20, 0.06, 0.4)):
        b = np.asarray(Image.fromarray((iles * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(rayon)),
                       np.float32) / 255.0
        ligne_ = np.clip(1 - np.abs(b - niveau) / (0.012 + niveau * 0.05), 0, 1) * (1 - iles)
        eau = np.maximum(eau, ligne_ * poids)
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    for k in range(-h, w, 9):
        dr.line([(k, h), (k + h, 0)], fill=110, width=1)
    hach = (np.asarray(im, np.float32) / 255.0) * (lisse_ > 0.6)
    traits = np.maximum(traits, hach * 0.8)
    rh = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(rh)
    for cx, cy in ((w * 0.30, h * 0.62), (w * 0.78, h * 0.30)):
        for k in range(32):
            a = 2 * math.pi * k / 32
            dr.line([(cx, cy), (cx + 3000 * math.cos(a), cy + 3000 * math.sin(a))],
                    fill=170 if k % 4 == 0 else 95, width=1)
    rhumbs = np.asarray(rh, np.float32) / 255.0 * (1 - iles)
    rose = rasteriser(dessin_rose(), 300, couleurs={"encre": (255, 255, 255, 255), "ton2": (255, 255, 255, 255)})
    ra = np.zeros((h, w), np.float32)
    rx, ry = int(w * 0.30 - 150), int(h * 0.62 - 150)
    ra[ry:ry + 300, rx:rx + 300] = np.asarray(rose.getchannel("A"), np.float32) / 255.0
    cadre = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(cadre)
    dr.rectangle((14, 14, w - 15, h - 15), outline=255, width=2)
    dr.rectangle((24, 24, w - 25, h - 25), outline=200, width=1)
    for i, x in enumerate(range(24, w - 24, 20)):
        if (i // 5) % 2 == 0:
            dr.rectangle((x, 15, x + 20, 23), fill=170)
            dr.rectangle((x, h - 24, x + 20, h - 16), fill=170)
    for i, y in enumerate(range(24, h - 24, 20)):
        if (i // 5) % 2 == 0:
            dr.rectangle((15, y, 23, y + 20), fill=170)
            dr.rectangle((w - 24, y, w - 16, y + 20), fill=170)
    cad = np.asarray(cadre, np.float32) / 255.0
    encre = np.clip(np.maximum.reduce([traits * 0.9, rhumbs * 0.35, ra * 0.7, cad * 0.6]), 0, 1)
    mer = np.clip(eau, 0, 1)
    a_tot = np.clip(encre + mer * (1 - encre), 0, 1)
    ce, cm = np.array(hexa(ENCRE)[:3], np.float32), np.array(hexa(MER)[:3], np.float32)
    poids = encre / (a_tot + 1e-6)
    rgb = ce * poids[..., None] + cm * (1 - poids[..., None])
    rgb[a_tot < 0.02] = cm  # couleur unie sous la transparence : le fichier compresse mieux
    return rgb, a_tot * 0.42


def texture_grain_tampon(taille=256, graine=61):
    """Masque de grain d'encre pour les tampons en CSS (mask-image) : opaque, piqué de manques."""
    h = w = taille
    fin = flou(np.random.default_rng(graine).standard_normal((h, w)), 0.7)
    fin /= fin.std()
    moyen = bruit(h, w, graine + 1, beta=2.0, fmin=8, fmax=90)
    traine = bruit(h, w, graine + 2, beta=1.6, fmin=6, fmax=160, aniso=(5.0, 1.0))
    vide = np.clip((fin - 2.0) * 1.6, 0, 1) + np.clip((moyen - 1.9) * 2.2, 0, 1) + np.clip((traine - 2.3) * 1.5, 0, 1)
    a = np.clip(1 - vide, 0, 1) * (0.9 + 0.1 * np.clip(moyen, -1, 1))
    rgb = np.zeros((h, w, 3), np.float32)
    return rgb, np.clip(a, 0, 1)


def ecrire_textures():
    """Noms alignés sur ceux qu'emploie l'interface (tirets bas)."""
    _np()
    for vieux in ("parchemin-clair.webp", "parchemin-fonce.webp", "papier-affiche.webp", "mer-carte.webp"):
        (D_TEXTURES / vieux).unlink(missing_ok=True)
    t = {}
    t["parchemin.webp"] = ecrire_webp("parchemin.webp", texture_parchemin(768, 11))
    t["parchemin_fonce.webp"] = ecrire_webp("parchemin_fonce.webp", texture_parchemin(768, 12, fonce=True))
    t["bois.webp"] = ecrire_webp("bois.webp", texture_bois())
    rgb, a = texture_papier_affiche()
    t["papier_affiche.webp"] = ecrire_webp("papier_affiche.webp", rgb, a, qualite=80)
    rgb, a = texture_vignette()
    t["vignette.webp"] = ecrire_webp("vignette.webp", rgb, a, qualite=70)
    rgb, a = texture_carte_marine()
    t["carte_marine.webp"] = ecrire_webp("carte_marine.webp", rgb, a, sans_perte=True)
    rgb, a = texture_grain_tampon()
    t["grain_tampon.webp"] = ecrire_webp("grain_tampon.webp", rgb, a, qualite=60, alpha_q=72)
    return t


@icone("horloge")
def _horloge(I):
    c = (16, 18)
    I.trait(cercle(16, 3.3, 1.9), 1.45)
    I.ton_trait(rect(14.6, 5, 2.8, 2.5, 0.6), 1.1)
    boitier = cercle(*c, 11.6)
    I.ton(boitier + cercle(*c, 9.4), eo=True)
    I.hach(F(boitier) - F(cercle(*c, 9.4)) & F(rect(16, 18, 14, 14)), 45, 1.5, sw=0.65)
    I.trait(boitier, 1.9)
    I.trait(cercle(*c, 9.4), 1.1)
    for k in range(12):
        a = math.radians(k * 30)
        r0 = 6 if k % 3 == 0 else 7.1
        I.trait(ligne(c[0] + r0 * math.sin(a), c[1] - r0 * math.cos(a), c[0] + 8.3 * math.sin(a),
                      c[1] - 8.3 * math.cos(a)), 1.15 if k % 3 == 0 else 0.75)
    I.plein(calame([c, (c[0] - 2.2, c[1] - 1.6), (c[0] - 4.1, c[1] - 3)], [2.3, 1.8, 1.1]))
    I.plein(calame([c, (c[0] + 1.6, c[1] - 3.2), (c[0] + 2.9, c[1] - 6)], [2, 1.4, 0.8]))
    I.ton_trait(cercle(*c, 1.25), 0.85)


def _aire(q):
    return sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1] for i in range(len(q))) / 2


def _dedans(x, y, q):
    c = False
    for (x0, y0), (x1, y1) in zip(q, q[1:] + q[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def _orienter_eo(polys):
    """Contours imbriqués lus en pair-impair → orientés pour la règle non-nulle
    (profondeur paire : sens positif ; impaire : sens négatif)."""
    out = []
    for i, q in enumerate(polys):
        prof = sum(1 for j, r in enumerate(polys) if j != i and _dedans(q[0][0], q[0][1], r))
        pos = _aire(q) > 0
        out.append(q if pos == (prof % 2 == 0) else q[::-1])
    return out


def encrer(morceaux, graine, amp=0.55, trous=((0.55, 2600), (1.2, 900), (2.0, 260)), ech=4.0,
           densite=0.55, angle=0.0, pas=0.7, simplifier=0.0):
    """Encre d'imprimerie : contours tremblés + manques d'encre placés bien à l'intérieur.
    morceaux = [(chemin, matrice | None, "eo" | "nz")] → polygones orientés (règle non-nulle)."""
    bruit, fin = _Bruit(graine), _Bruit(graine + 99, ((2.2, 0.5), (1.1, 0.3)))
    polys = []
    for d, m, mode in morceaux:
        if m:
            d = "".join(poly([m_app(m, x, y) for x, y in pts], ferme) for pts, ferme in aplatir(d, 0.5 / m_echelle(m)))
        q = _trembler(d, lambda x, y: bruit(x, y) + 0.45 * fin(x, y), amp, pas)
        if simplifier:
            q = [r for r in (_simplifier(r + r[:1], simplifier)[:-1] for r in q) if len(r) > 2]
        polys += _orienter_eo(q) if mode == "eo" else q
    xs = [p[0] for q in polys for p in q]
    ys = [p[1] for q in polys for p in q]
    x0, y0 = min(xs) - 3, min(ys) - 3
    W, H = int((max(xs) + 3 - x0) * ech) + 1, int((max(ys) + 3 - y0) * ech) + 1
    pos = Image.new("L", (W, H), 0)
    neg = Image.new("L", (W, H), 0)
    for q in polys:
        cible = pos if _aire(q) > 0 else neg
        ImageDraw.Draw(cible).polygon([((x - x0) * ech, (y - y0) * ech) for x, y in q], fill=255)
    masque = ImageChops.subtract(pos, neg)
    rnd = random.Random(graine * 7 + 3)
    vides = []
    for rayon, essais in trous:
        erosion = int(2 * (rayon * 1.25 + 0.45) * ech) | 1
        sur = masque.filter(ImageFilter.MinFilter(min(erosion, 61)))
        px = sur.load()
        for _ in range(essais):
            x, y = rnd.uniform(x0, x0 + W / ech), rnd.uniform(y0, y0 + H / ech)
            u, v = int((x - x0) * ech), int((y - y0) * ech)
            if not (0 <= u < W and 0 <= v < H) or px[u, v] != 255 or rnd.random() > densite:
                continue
            r = rayon * rnd.uniform(0.6, 1.0)
            allonge = rnd.uniform(1, 2.2) if rayon < 1 else rnd.uniform(1, 1.5)
            a0 = math.radians(angle + rnd.uniform(-20, 20))
            pts = []
            for j in range(7):
                t = 2 * math.pi * j / 7
                rr = r * rnd.uniform(0.75, 1.15)
                ex, ey = rr * allonge * math.cos(t), rr * math.sin(t)
                pts.append((x + ex * math.cos(a0) - ey * math.sin(a0), y + ex * math.sin(a0) + ey * math.cos(a0)))
            contenant = [q for q in polys if _dedans(x, y, q)]
            if not contenant:
                continue
            interieur = min(contenant, key=lambda q: abs(_aire(q)))
            if (_aire(pts) > 0) == (_aire(interieur) > 0):
                pts = pts[::-1]
            vides.append(pts)
            bb = (u - r * allonge * ech - 7, v - r * allonge * ech - 7, u + r * allonge * ech + 7, v + r * allonge * ech + 7)
            ImageDraw.Draw(sur).ellipse(bb, fill=0)
            ImageDraw.Draw(masque).ellipse(bb, fill=0)
    return polys + vides


def _polys_d(polys, prec=1):
    f = (lambda v: f"{v:.{prec}f}".rstrip("0").rstrip(".") or "0")
    return "".join("M" + "L".join(f"{f(x)} {f(y)}" for x, y in q) + "Z" for q in polys)




# ── Affiche « WANTED » ──────────────────────────────────────────────────────────────────

AFFICHE = (600, 840)
AFFICHE_ZONES = {
    # zones où l'interface pose le contenu (unités du viewBox 600 × 840)
    "portrait": (120, 206, 360, 324),
    "grade": (232, 527, 136, 24),
    "surnom": (80, 562, 440, 30),
    "nom": (56, 592, 488, 60),
    "prime": (90, 668, 420, 54),
    "icones": (120, 730, 360, 40),
}
AFFICHE_DESSINE = {"titre": (60, 44, 480, 100), "sous_titre": (90, 162, 420, 34), "mention": (190, 774, 220, 30)}


def _anneau_rect(x, y, l, h, e, r=0.0):
    return rect(x - e / 2, y - e / 2, l + e, h + e, r + e / 2 if r else 0) + rect(x + e / 2, y + e / 2, l - e, h - e,
                                                                                  max(0.0, r - e / 2))


def dessin_affiche():
    """Cadre de l'affiche, à poser sur papier-affiche.webp (même rapport 5:7) et sur le
    portrait ; l'interface écrit surnom, nom, prime, grade et pose les icônes (affiche.json)."""
    L, H = AFFICHE
    mor = []
    mor.append((_anneau_rect(26, 26, L - 52, H - 52, 4.6), None, "eo"))
    mor.append((_anneau_rect(34.5, 34.5, L - 69, H - 69, 1.3), None, "eo"))
    tmp = Dessin(L, H)
    for (ox, sx), (oy, sy) in (((40, 1), (40, 1)), ((L - 40, -1), (40, 1)), ((40, 1), (H - 40, -1)),
                               ((L - 40, -1), (H - 40, -1))):
        fleuron(tmp, ox, oy, 1.0, sx=sx, sy=sy)
    titre, _ = mot_centre("WANTED", "Rye", L / 2, 140, largeur=468)
    mor.append((titre, None, "nz"))
    mor.append((rect(72, 151, L - 144, 2.4) + rect(104, 156.6, L - 208, 1), None, "eo"))
    sous, _ = mot_centre("AVIS DE L'ÉQUIPAGE", "Alegreya SC", L / 2, 191, largeur=286)
    mor.append((sous, None, "nz"))
    for s in (-1, 1):
        cx = L / 2 + s * 178
        tmp.plein(poly([(cx - 5, 182.5), (cx, 178), (cx + 5, 182.5), (cx, 187)]))
        tmp.plein(calame([(cx + s * 8, 182.5), (cx + s * 24, 182.5), (cx + s * 44, 182.5)], [1.8, 1.2, 0.3],
                         bouts=("rond", "pointe")))
    # portrait : filet épais, filet fin sur le bord de l'image, coins en losange
    px, py, pl, ph = AFFICHE_ZONES["portrait"]
    mor.append((_anneau_rect(px - 8, py - 8, pl + 16, ph + 16, 4), None, "eo"))
    mor.append((_anneau_rect(px, py, pl, ph, 1.6), None, "eo"))
    for cx, cy in ((px - 8, py - 8), (px + pl + 8, py - 8), (px - 8, py + ph + 8), (px + pl + 8, py + ph + 8)):
        tmp.plein(poly([(cx - 8, cy), (cx, cy - 8), (cx + 8, cy), (cx, cy + 8)]))
        tmp.plein(cercle(cx, cy, 2.2), "#000000")
    # séparateur au-dessus de la prime, filets au-dessous
    fil = dessin_filet()
    for t in fil.traces:
        mor.append((t.d, (0.86, 0, 0, 0.86, L / 2 - 160 * 0.86, 658 - 12 * 0.86), "nz"))
    mor.append((rect(150, 725, L - 300, 1.8) + rect(186, 729.4, L - 372, 0.9), None, "eo"))
    mention, _ = mot_centre("RELL Seas", "Pirata One", L / 2, 797, largeur=120)
    mor.append((mention, None, "nz"))
    for s in (-1, 1):
        x0 = L / 2 + s * 74
        pts = [(x0 + s * k * 2.2, 789 - 2.2 * math.sin(k * 0.62)) for k in range(0, 29)]
        mor.append((calame(pts, [0.3 + 1.3 * math.sin(math.pi * k / 28) for k in range(29)], k=3), None, "nz"))
    for t in tmp.traces:
        if t.fill == "encre":
            mor.append((t.d, m_svg(t.tf) if t.tf else None, "nz"))
    polys = encrer(mor, 77, amp=0.42, trous=((0.6, 5200), (1.3, 1700), (2.2, 480)), densite=0.5, pas=0.95,
                   simplifier=0.05)
    D = Dessin(L, H)
    D.plein(_polys_d(polys), "encre", op=0.94)
    # plaque de laiton du grade, posée sur le bas du portrait
    gx, gy, gl, gh = AFFICHE_ZONES["grade"]
    plaque = poly([(gx - 12, gy - 4), (gx + gl + 12, gy - 4), (gx + gl + 5, gy + gh / 2), (gx + gl + 12, gy + gh + 4),
                   (gx - 12, gy + gh + 4), (gx - 5, gy + gh / 2)])
    D.plein(plaque, "ton2")
    D.hach(F(plaque) & F(rect(0, gy + gh * 0.62, L, gh)), 60, 2.2, sw=0.7, centre=(300, 400))
    D.trait(plaque, 1.8)
    D.trait(rect(gx - 4, gy - 0.5, gl + 8, gh + 1, 1.5), 0.7, op=0.8)
    for x in (gx - 5.5, gx + gl + 5.5):
        D.plein(cercle(x, gy + gh / 2, 2.4))
        D.trait(ligne(x - 1.5, gy + gh / 2 - 1.5, x + 1.5, gy + gh / 2 + 1.5), 0.6, "ton2")
    return D


def ecrire_affiche():
    L, H = AFFICHE
    taille = ecrire_ornement("affiche.svg", dessin_affiche())

    def zone(x, y, l, h, **plus):
        z = {"x": x, "y": y, "l": l, "h": h,
             "pct": {"left": round(100 * x / L, 3), "top": round(100 * y / H, 3),
                     "width": round(100 * l / L, 3), "height": round(100 * h / H, 3)}}
        z.update(plus)
        return z

    Z = AFFICHE_ZONES
    data = {
        "version": 1,
        "viewBox": [0, 0, L, H],
        "ratio": "5 / 7",
        "calques": [
            {"ordre": 1, "role": "papier", "fichier": "../textures/papier_affiche.webp",
             "pose": "fond 100 % × 100 % ; bords déchirés déjà transparents"},
            {"ordre": 2, "role": "portrait", "zone": "portrait",
             "pose": "image en object-fit: cover (avatar Roblox ou média), sous le cadre"},
            {"ordre": 3, "role": "cadre", "fichier": "affiche.svg",
             "pose": "100 % × 100 % par-dessus le portrait ; mix-blend-mode: multiply conseillé"},
            {"ordre": 4, "role": "textes", "zones": ["grade", "surnom", "nom", "prime", "icones"]},
        ],
        "zones": {
            "portrait": zone(*Z["portrait"], ajustement="cover", rapport=round(Z["portrait"][2] / Z["portrait"][3], 3)),
            "grade": zone(*Z["grade"], police="Alegreya SC", graisse=700, taille=0.03, align="center",
                          couleur=ENCRE, note="sur la plaque de laiton ; une ligne, ellipse"),
            "surnom": zone(*Z["surnom"], police="Alegreya", style="italic", taille=0.042, align="center",
                           couleur=ENCRE, note="entre guillemets « » ; une ligne"),
            "nom": zone(*Z["nom"], police="Rye", taille=0.078, align="center", couleur=ENCRE,
                        note="une ligne ; réduire la taille si le nom déborde"),
            "prime": zone(*Z["prime"], police="Rye", taille=0.072, align="center", couleur=ENCRE,
                          symbole="symbole-prime.svg", note="le ฿ est un dessin (aucune police du site n'a ce signe) : "
                          "l'insérer avant le nombre, haut de 0,8 em ; chiffres groupés par espaces fines"),
            "icones": zone(*Z["icones"], taille_icone=0.06, max=6, ecart=0.016, align="center",
                           note="icônes officielles (métier, race, faction…) en ligne, centrées"),
        },
        "dessines": {k: zone(*v) for k, v in AFFICHE_DESSINE.items()},
        "textes_dessines": {"titre": "WANTED (Rye)", "sous_titre": "AVIS DE L'ÉQUIPAGE (Alegreya SC 700)",
                            "mention": "RELL Seas (Pirata One)"},
        "tailles": "« taille » = fraction de la largeur de l'affiche (ex. font-size: calc(0.078 * 100cqw) "
                   "avec container-type: inline-size sur l'affiche)",
        "couleurs": {"encre": ENCRE, "laiton": LAITON, "cire": CIRE},
    }
    (D_ORNEMENTS / "affiche.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8", newline="\n")
    return {"affiche.svg": taille, "affiche.json": (D_ORNEMENTS / "affiche.json").stat().st_size}


# ════════════════════════════════════════════════════════════════════════════════════════
#  Polices (OFL) : la seule commande qui utilise le réseau
# ════════════════════════════════════════════════════════════════════════════════════════

POLICES_API = ("https://fonts.googleapis.com/css2?family=Alegreya:ital,wght@0,400;0,700;1,400"
               "&family=Alegreya+SC:wght@400;700&family=Pirata+One&family=Rye&display=swap")
POLICES_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36")
POLICES_SOUS_ENSEMBLES = ("latin", "latin-ext")
POLICES_AUTEURS = {
    "Pirata One": ("Rodrigo Fuenzalida, Nicolás Massi (Typonauta / TAIP)",
                   "Copyright (c) 2012, Rodrigo Fuenzalida, Nicolas Massi (www.taip.com.ar / abc.taip.com.ar), "
                   "with Reserved Font Name 'Pirata'", "titres"),
    "Rye": ("Nicole Fally (Sorkin Type)",
            "Copyright (c) 2011 by Sorkin Type Co (www.sorkintype.com), with Reserved Font Name \"Rye\".",
            "affiches (avis de recherche)"),
    "Alegreya": ("Juan Pablo del Peral (Huerta Tipográfica)",
                 "Copyright 2011 The Alegreya Project Authors (https://github.com/huertatipografica/Alegreya)",
                 "texte courant (400, 400 italique, 700)"),
    "Alegreya SC": ("Juan Pablo del Peral (Huerta Tipográfica)",
                    "Copyright 2011 The Alegreya Project Authors (https://github.com/huertatipografica/Alegreya)",
                    "petites capitales (400, 700)"),
}


def _telecharger(url, entetes=None):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": POLICES_UA, **(entetes or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def ecrire_polices():
    css = _telecharger(POLICES_API).decode("utf-8")
    blocs = re.findall(r"/\* ([\w-]+) \*/\s*@font-face \{(.*?)\}", css, re.S)
    faces = {}
    for sous, corps in blocs:
        if sous not in POLICES_SOUS_ENSEMBLES:
            continue
        fam = re.search(r"font-family: '([^']+)'", corps).group(1)
        style = re.search(r"font-style: (\w+)", corps).group(1)
        poids = int(re.search(r"font-weight: (\d+)", corps).group(1))
        url = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", corps).group(1)
        plage = re.search(r"unicode-range: ([^;]+);", corps).group(1).strip()
        cle = (fam, style, sous, url)
        f = faces.setdefault(cle, {"poids": [], "plage": plage})
        f["poids"].append(poids)
    par_famille = {}
    for (fam, style, sous, url) in faces:
        par_famille.setdefault((fam, style, sous), set()).add(url)
    D_POLICES.mkdir(parents=True, exist_ok=True)
    regles, fichiers = [], []
    for (fam, style, sous, url), f in sorted(faces.items(), key=lambda kv: (kv[0][0], kv[0][1], min(kv[1]["poids"]), kv[0][2])):
        poids = sorted(set(f["poids"]))
        plusieurs = len(par_famille[(fam, style, sous)]) > 1
        nom = _slug(fam) + ("-italique" if style == "italic" else "")
        nom += (f"-{poids[0]}" if plusieurs else "") + f"-{sous}.woff2"
        donnees = _telecharger(url)
        if donnees[:4] != b"wOF2":
            raise SystemExit(f"[DESSINS] {nom} : ce n'est pas du woff2")
        (D_POLICES / nom).write_bytes(donnees)
        fichiers.append((nom, len(donnees)))
        graisse = f"{poids[0]} {poids[-1]}" if len(poids) > 1 else str(poids[0])
        regles.append(f"/* {fam} — {sous} */\n@font-face {{\n  font-family: '{fam}';\n  font-style: {style};\n"
                      f"  font-weight: {graisse};\n  font-display: swap;\n  src: url({nom}) format('woff2');\n"
                      f"  unicode-range: {f['plage']};\n}}\n")
    entete = ("/* Polices du site, hébergées ici (OFL 1.1 — voir ../LICENCES.md).\n"
              "   Fabriqué par outils/dessins_site.py polices — Google Fonts, sous-ensembles latin + latin-ext.\n"
              "   Alegreya est variable : un seul fichier sert 400 et 700. */\n\n")
    (D_POLICES / "polices.css").write_text(entete + "\n".join(regles), encoding="utf-8", newline="\n")
    for nom, t in fichiers:
        print(f"[DESSINS] polices/{nom} : {t // 1024} Ko")
    ecrire_licences()


def ecrire_licences():
    """site/LICENCES.md : polices (OFL) et dessins maison. Le texte de l'OFL est repris tel quel du
    fichier OFL.txt distribué avec ces polices ; ce fichier peut recevoir d'autres sections
    (icônes officielles, logos) : seules les sections balisées « dessins_site » sont réécrites."""
    chemin = SITE / "LICENCES.md"
    debut, fin = "<!-- dessins_site:debut -->", "<!-- dessins_site:fin -->"
    lignes = [debut, "## Polices (SIL Open Font License 1.1)", "",
              "Hébergées dans `site/polices/` (woff2, sous-ensembles latin + latin-ext, servies telles quelles, "
              "sans modification). Source : Google Fonts.", "",
              "| Famille | Auteurs | Usage | Mention de droits |", "|---|---|---|---|"]
    for fam, (auteurs, droits, usage) in POLICES_AUTEURS.items():
        lignes.append(f"| {fam} | {auteurs} | {usage} | {droits} |")
    lignes += ["", "Quelques lettres de ces polices (« WANTED », « AVIS DE L'ÉQUIPAGE », « RELL Seas », les mots des "
               "tampons) sont aussi converties en contours dans les ornements SVG : un dessin réalisé avec une police "
               "OFL n'est pas un « logiciel de police » et reste libre d'usage.", "",
               "## Dessins maison", "",
               "Icônes (`site/icones/ui.svg`), ornements (`site/ornements/`), textures (`site/textures/`) et icônes "
               "Discord (`visuels/icones/*.png` fabriquées par `outils/dessins_site.py`) : dessinés par le code du "
               "projet, aucun élément tiers. Les marques Discord et Roblox (icônes `discord`, `roblox`) appartiennent "
               "à leurs propriétaires et ne servent qu'à désigner ces services.", "",
               "## Texte de la licence SIL OFL 1.1", "", "```", OFL_TEXTE.strip("\n"), "```", fin]
    bloc = "\n".join(lignes) + "\n"
    if chemin.exists():
        ancien = chemin.read_text(encoding="utf-8")
        if debut in ancien and fin in ancien:
            nouveau = ancien[:ancien.index(debut)] + bloc.rstrip("\n") + ancien[ancien.index(fin) + len(fin):]
        else:
            nouveau = ancien.rstrip("\n") + "\n\n" + bloc
    else:
        nouveau = "# Licences du site\n\n" + bloc
    chemin.write_text(nouveau, encoding="utf-8", newline="\n")
    print("[DESSINS] LICENCES.md écrit")


# Texte officiel de la licence (fichier OFL.txt distribué avec ces polices, tel quel).
OFL_TEXTE = r"""
This Font Software is licensed under the SIL Open Font License, Version 1.1.
This license is copied below, and is also available with a FAQ at:
http://scripts.sil.org/OFL


-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded, 
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
"""


@icone("modifier")
def _modifier(I):
    # la plume taillée qui écrit : le bec au bout de la ligne déjà tracée
    tf = "translate(11.4 25.2) rotate(-47)"
    barbe = "M5.2 0C9.4 -5 16.4 -6.4 24.2 -0.8C18 1.9 11 2.8 5.2 0Z"
    I.hach(F(barbe, tf=tf), -12, 1.3, sw=0.75, marge=0.35)
    I.trait(barbe, 1.6, tf=tf)
    I.trait("M1.4 0L24 -0.6", 1.4, tf=tf)
    I.trait("M8.8 -3.2L7.9 -4.6M13.8 -4.8L13.3 -6.1", 1.1, tf=tf)
    I.plein("M-0.8 0.1L2.8 -1.6L3.3 1.3Z", tf=tf)
    I.plein(calame([(1.8, 28.2), (4.6, 26.2), (6.8, 28), (9.2, 26.4), (11, 25.8)],
                   [0.6, 2, 1.6, 1.8, 1.2], bouts=("pointe", "rond")))


@icone("supprimer")
def _supprimer(I):
    # le seau à ordures du bord : couvercle soulevé, douelles, cercles de laiton
    def bord(y, s):
        t = (y - 11.4) / 16.2
        return 6.6 + 1.8 * t if s < 0 else 25.4 - 1.8 * t
    I.trait("M12.8 6.2V4.6C12.8 3.9 13.3 3.4 14 3.4H18C18.7 3.4 19.2 3.9 19.2 4.6V6.2", 1.5)
    I.ton_trait(rect(4.4, 6.1, 23.2, 3.1, 1.2), 1.5)
    seau = "M6.6 11.4H25.4L23.6 27.6C23.5 28.4 22.9 29 22.1 29H9.9C9.1 29 8.5 28.4 8.4 27.6Z"
    I.hach(F(seau) & F(rect(19.6, 0, 10, 32)), 60, 1.45, sw=0.7)
    for x0, x1 in ((11.8, 12.4), (16, 16), (20.2, 19.6)):
        I.trait(ligne(x0, 16.4, x1, 22.6), 0.95)
    for y0, y1 in ((12.6, 14.8), (23.6, 25.8)):
        I.ton_trait(poly([(bord(y0, -1), y0), (bord(y0, 1), y0), (bord(y1, 1), y1), (bord(y1, -1), y1)]), 1.1)
    I.trait(seau, 1.8)


def _interrogation(I, c="encre"):
    I.plein(calame([(11.2, 12), (12.6, 8.4), (16.2, 7.2), (19.8, 8.4), (20.6, 11.6), (18.4, 14.6),
                    (16.3, 16.6), (16, 19.8)], [1.6, 2.2, 2.6, 2.8, 2.8, 2.5, 2.1, 1.7], k=8), c)
    I.plein(cercle(16, 23.6, 1.7), c)


# ════════════════════════════════════════════════════════════════════════════════════════
#  Icônes Discord (émojis d'application, 128 px, fond transparent)
# ════════════════════════════════════════════════════════════════════════════════════════

# nom de l'émoji → (fichier, icône du sprite, présentation). Six noms étaient déjà pris dans
# visuels/icones/ (membres, valider, annuler, cloche, drapeau, navire) : ceux-là prennent le préfixe ev_.
PNG_DISCORD = {
    "minuteur": ("minuteur", "minuteur", "medaillon"), "lieu": ("lieu", "lieu", "medaillon"),
    "membres": ("ev_membres", "membres", "medaillon"), "valider": ("ev_valider", "valider", ("sceau", VERT)),
    "annuler": ("ev_annuler", "fermer", ("sceau", CIRE)), "peut_etre": ("peut_etre", "?", ("sceau", AMBRE)),
    "cloche": ("ev_cloche", "cloche", "medaillon"), "ancre": ("ancre", "ancre", "medaillon"),
    "boussole": ("boussole", "boussole", "medaillon"), "drapeau": ("ev_drapeau", "drapeau", "medaillon"),
    "prime": ("prime", "prime", "medaillon"), "navire": ("ev_navire", "navire", "medaillon"),
}
PNG_SIGNATURE = "outils/dessins_site.py"


def copier_traces(src, dst, tf, couleur=None):
    for t in src.traces:
        dst.traces.append(Trace(t.d, couleur if (couleur and t.fill) else t.fill,
                                couleur if (couleur and t.stroke) else t.stroke, t.sw, t.cap, t.join, t.eo,
                                f"{tf} {t.tf}" if t.tf else tf, t.op))


def dessin_png(icone_, presentation):
    D = Dessin(128, 128)
    if presentation == "medaillon":
        D.plein(cercle(64, 65.5, 60), "#120b06", op=0.35)
        D.plein(cercle(64, 64, 60), PARCHEMIN)
        D.hach(F(cercle(64, 64, 56.2)) - F(cercle(58.6, 58.6, 56.2)), 45, 3.2, sw=1.1, centre=(64, 64))
        D.trait(cercle(64, 64, 58.4), 4.4)
        D.trait(cercle(64, 64, 53.2), 1.4)
        src = dessin_icone(icone_)
        copier_traces(src, D, "translate(18.6 18.6) scale(2.84)")
        return D
    _, base = presentation
    fonce, clair = melange(base, "#000000", 0.4), melange(base, "#ffffff", 0.3)
    contour = cachet(64, 64, 58.5, graine=17, lobes=9, amp=0.05)
    D.plein(contour, "#120b06", tf="translate(1.5 2.5)", op=0.4)
    D.plein(contour, base)
    bord = gonfler(contour, -4.2)
    D.trait(masquer(bord, lambda x, y: x + y > 124, pas=0.5), 3.2, clair, op=0.8)
    D.trait(masquer(bord, lambda x, y: x + y < 132, pas=0.5), 3.6, fonce, op=0.7)
    D.plein(cercle(64, 64, 43), fonce, op=0.32)
    D.trait(masquer(cercle(64, 64, 43), lambda x, y: x + y > 132, pas=0.5), 3.6, fonce, op=0.9)
    D.trait(masquer(cercle(64, 64, 43), lambda x, y: x + y < 124, pas=0.5), 2.6, clair, op=0.85)
    glyphe = Dessin(32, 32)
    if icone_ == "?":
        _interrogation(glyphe)
    else:
        ICONES[icone_](glyphe)
    copier_traces(glyphe, D, "translate(64 64) scale(2.45) translate(-16 -16.2)", "#f6ecd4")
    return D


def ecrire_png():
    """Écrit les PNG ; n'écrase jamais un fichier qui n'a pas été signé par ce script."""
    from PIL.PngImagePlugin import PngInfo
    D_PNG.mkdir(parents=True, exist_ok=True)
    ecrits = []
    for nom, (fichier, icone_, pres) in PNG_DISCORD.items():
        chemin = D_PNG / f"{fichier}.png"
        if chemin.exists():
            with Image.open(chemin) as ancien:
                if ancien.info.get("Software") != PNG_SIGNATURE:
                    print(f"[DESSINS] {chemin.name} existe déjà (pas de ce script) : laissé tel quel")
                    continue
        img = rasteriser(dessin_png(icone_, pres), 128, couleurs={"encre": hexa(ENCRE), "ton2": hexa(LAITON)})
        info = PngInfo()
        info.add_text("Software", PNG_SIGNATURE)
        img.save(chemin, optimize=True, pnginfo=info)
        ecrits.append(fichier)
        print(f"[DESSINS] visuels/icones/{fichier}.png ({chemin.stat().st_size // 1024} Ko)")
    return ecrits


# ════════════════════════════════════════════════════════════════════════════════════════
#  Planche de contrôle (site/ornements/planche.html — .html n'est pas servi par le bot)
# ════════════════════════════════════════════════════════════════════════════════════════

def ecrire_planche():
    import html as _h
    noms = list(ICONES)
    try:
        aff = json.loads((D_ORNEMENTS / "affiche.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        aff = {"zones": {}, "dessines": {}}
    png = [f for f, _, _ in PNG_DISCORD.values()]
    zcss = []
    for nom, z in list(aff.get("zones", {}).items()) + [("d-" + k, v) for k, v in aff.get("dessines", {}).items()]:
        p = z["pct"]
        zcss.append(f".z-{nom}{{left:{p['left']}%;top:{p['top']}%;width:{p['width']}%;height:{p['height']}%}}")

    def ico(nom, cl=""):
        return f'<svg class="ico {cl}" aria-hidden="true"><use href="../icones/ui.svg#i-{nom}"/></svg>'

    cartes = []
    for nom in noms:
        cartes.append(
            f'<figure class="carte"><figcaption>{nom}</figcaption>'
            f'<div class="sur-parchemin">{ico(nom, "t16")}{ico(nom, "t24")}{ico(nom, "t32")}{ico(nom, "t64")}</div>'
            f'<div class="sur-bois">{ico(nom, "t16")}{ico(nom, "t24")}{ico(nom, "t32")}</div></figure>')
    rangee_cire = "".join(ico(nm, "t32") for nm in noms)
    ornements = [("coin.svg", "Coin gravé", "orn-coin"), ("cadre.svg", "Cadre (border-image, tranches 40)", "orn-cadre"),
                 ("corde.svg", "Corde (répétée en x)", "orn-corde"), ("corde-v.svg", "Corde verticale", "orn-cordev"),
                 ("sceau-rouge.svg", "Sceau de cire rouge", "orn-sceau"), ("sceau-vert.svg", "Sceau vert", "orn-sceau"),
                 ("sceau-ambre.svg", "Sceau ambre", "orn-sceau"), ("ruban.svg", "Ruban de titre", "orn-ruban"),
                 ("ruban-cire.svg", "Ruban de cire", "orn-ruban"), ("rose-des-vents.svg", "Rose des vents", "orn-rose"),
                 ("filet.svg", "Filet (séparateur)", "orn-filet"), ("clou.svg", "Clou", "orn-clou"),
                 ("etiquette.svg", "Étiquette de malle", "orn-etiquette"),
                 ("symbole-prime.svg", "Signe ฿ (prime)", "orn-berry")]
    orn_html = "".join(f'<figure class="orn"><img class="{c}" src="{f}" alt=""><figcaption>{_h.escape(t)} '
                       f'<code>{f}</code></figcaption></figure>' for f, t, c in ornements)
    tampons = "".join(f'<img class="tampon-img" src="tampon-{t}.svg" alt="{t}">' for t in
                      ("vu", "traite", "archive", "refuse", "accepte"))
    textures = [("parchemin.webp", "tx-parchemin"), ("parchemin_fonce.webp", "tx-fonce"), ("bois.webp", "tx-bois"),
                ("carte_marine.webp", "tx-carte"), ("vignette.webp", "tx-vignette"), ("grain_tampon.webp", "tx-grain")]
    tx_html = "".join(f'<figure class="tx {c}"><figcaption><code>{f}</code></figcaption></figure>' for f, c in textures)
    png_html = "".join(
        f'<figure class="png"><img src="../../visuels/icones/{n}.png" alt="{n}" class="p128">'
        f'<div class="discord-sombre"><img src="../../visuels/icones/{n}.png" alt="" class="p22">'
        f'<span>Dispo</span><img src="../../visuels/icones/{n}.png" alt="" class="p32"></div>'
        f'<div class="discord-clair"><img src="../../visuels/icones/{n}.png" alt="" class="p22"><span>Dispo</span>'
        f'<img src="../../visuels/icones/{n}.png" alt="" class="p32"></div><figcaption>{n}.png</figcaption></figure>'
        for n in png)

    def affiche(cl, vide=False):
        zones = "" if not vide else "".join(f'<div class="zone z-{k}"><span>{k}</span></div>'
                                            for k in list(aff.get("zones", {})) + ["d-" + k for k in aff.get("dessines", {})])
        contenu = "" if vide else (
            f'<div class="portrait z-portrait">{ico("personne", "portrait-ico")}</div>'
            '<img class="cadre-affiche" src="affiche.svg" alt="">'
            '<div class="txt grade z-grade">Quartier-maître</div>'
            '<div class="txt surnom z-surnom">« Le Requin des Abysses »</div>'
            '<div class="txt nom z-nom">Barbe-Rousse</div>'
            '<div class="txt prime z-prime"><img class="berry" src="symbole-prime.svg" alt="฿">1 250 000 000</div>'
            f'<div class="txt icones z-icones">{ico("ancre")}{ico("sabre")}{ico("boussole")}{ico("canon")}</div>')
        cadre = '<img class="cadre-affiche" src="affiche.svg" alt="">' if vide else ""
        return (f'<div class="affiche {cl}"><img class="papier" src="../textures/papier_affiche.webp" alt="">'
                f'{contenu}{cadre}{zones}</div>')

    css = PLANCHE_CSS + "\n".join(zcss)
    page = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planche des dessins</title>
<link rel="stylesheet" href="../polices/polices.css">
<style>
{css}
</style>
</head>
<body>
<header class="tete"><h1>Planche des dessins du site</h1>
<p>Fabriquée par <code>outils/dessins_site.py</code> — {len(noms)} icônes, ornements, textures, affiche, icônes Discord.
Ouvrir par un serveur local (le sprite externe ne se charge pas en file://).</p></header>

<section><h2>Icônes — 16, 24, 32, 64 px sur parchemin ; 16, 24, 32 px sur bois</h2>
<div class="grille">{''.join(cartes)}</div></section>

<section><h2>Second ton recoloré : --ton2 en cire rouge, puis en vert</h2>
<div class="rangee cire">{rangee_cire}</div><div class="rangee verte">{rangee_cire}</div></section>

<section><h2>Ornements</h2><div class="ornements">{orn_html}</div>
<h3>Mises en situation</h3>
<div class="situations">
<div class="demo-cadre"><p class="demo-titre">Fiche technique</p><p>Le cadre gravé posé en <code>border-image</code>.</p></div>
<div class="demo-ruban"><span>Les Annonces</span></div>
<div class="demo-ruban rouge"><span>Capitainerie</span></div>
<div class="demo-etiquettes"><span class="etiquette">Journal</span><span class="etiquette">Sanctions</span><span class="etiquette">Tickets</span></div>
<div class="demo-pancarte"><span class="clou g"></span><span class="clou d"></span><span class="pancarte-texte">Le Port</span></div>
<div class="demo-sceaux"><span class="sceau r">{ico("succes", "dans-sceau")}</span><span class="sceau v">{ico("valider", "dans-sceau")}</span><span class="sceau a">{ico("attention", "dans-sceau")}</span></div>
<div class="demo-carte-coins"><span class="coin hg"></span><span class="coin hd"></span><span class="coin bg"></span><span class="coin bd"></span><p>Carte-parchemin aux coins gravés, vignettage étiré par-dessus.</p><img class="demo-filet" src="filet.svg" alt=""></div>
</div>
<h3>Tampons</h3><div class="tampons">{tampons}<span class="tampon-css">Vu par la direction</span></div></section>

<section><h2>Textures</h2><div class="textures">{tx_html}</div>
<div class="tx-grand"><p>Parchemin en grand (tuile 768 px affichée à 384 px), carte marine en filigrane et vignettage par-dessus.</p></div></section>

<section><h2>Affiche « WANTED » — papier + portrait + cadre + textes (zones d'affiche.json)</h2>
<div class="affiches">{affiche("a600")}{affiche("a300")}{affiche("a300", vide=True)}</div></section>

<section><h2>Icônes Discord (128 px ; dans un message sombre et clair à 22 et 32 px)</h2>
<div class="pngs">{png_html}</div></section>

<section><h2>Polices</h2><div class="polices">
<p class="f-pirata">Pirata One — La Capitainerie de l'Équipage</p>
<p class="f-rye">Rye — Avis de recherche : 1 250 000</p>
<p class="f-alegreya">Alegreya 400 — Le capitaine consigne à bâbord chaque manœuvre ; « où est passé l'équipage ? »</p>
<p class="f-alegreya i">Alegreya italique — Une plume trempée dans l'encre brune, à la lueur d'une lanterne.</p>
<p class="f-alegreya b">Alegreya 700 — Sanctions, tickets, répertoire : tout est rangé.</p>
<p class="f-sc">Alegreya SC 400 — Fiches techniques du clan</p>
<p class="f-sc b">Alegreya SC 700 — Rôles et métiers · Movie 3</p>
</div></section>
</body>
</html>
"""
    (D_ORNEMENTS / "planche.html").write_text(page, encoding="utf-8", newline="\n")
    print("[DESSINS] ornements/planche.html écrite")


PLANCHE_CSS = """
:root { --encre:#2b1d12; --parchemin:#efe2c4; --parchemin2:#e4d2a6; --bois:#4a2e1a; --bois2:#2f1d10;
  --laiton:#a8823f; --cire:#8e2a24; --vert:#3f6b3a; --mer:#1f4e5a; --ambre:#a8641c; }
* { box-sizing: border-box; }
body { margin: 0; background: #2f1d10 url(../textures/bois.webp); background-size: 512px auto; color: var(--encre);
  font: 16px/1.5 'Alegreya', Georgia, serif; }
img, svg { max-width: 100%; }
.tete, section { margin: 18px auto; max-width: 1480px; padding: 18px clamp(10px, 3vw, 22px); background: var(--parchemin) url(../textures/parchemin.webp);
  background-size: 384px auto; box-shadow: 0 6px 18px rgba(0,0,0,.45); }
h1 { font: 400 40px/1.1 'Pirata One', serif; margin: 0 0 6px; }
h2 { font: 400 28px/1.2 'Pirata One', serif; margin: 0 0 12px; }
h3 { font: 700 18px/1.2 'Alegreya SC', serif; margin: 22px 0 10px; }
code { font: 13px/1.2 Consolas, monospace; background: rgba(43,29,18,.08); padding: 0 3px; }
.ico { display: inline-block; fill: var(--ton2, #a8823f); color: var(--encre); flex: none; }
.t16 { width: 16px; height: 16px; } .t24 { width: 24px; height: 24px; } .t32 { width: 32px; height: 32px; }
.t64 { width: 64px; height: 64px; }
.grille { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(210px, 100%), 1fr)); gap: 10px; }
.carte { margin: 0; border: 1px solid rgba(43,29,18,.25); background: rgba(255,255,255,.18); }
.carte figcaption { font: 700 13px/1 'Alegreya SC', serif; padding: 5px 7px 2px; }
.sur-parchemin, .sur-bois { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 6px 8px; min-height: 76px; }
.sur-bois { background: #3b2416 url(../textures/bois.webp); background-size: 300px auto; color: var(--parchemin); min-height: 44px; }
.sur-bois .ico { color: var(--parchemin); }
.rangee { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px; }
.rangee.cire .ico { --ton2: #8e2a24; } .rangee.verte .ico { --ton2: #3f6b3a; }
.ornements { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-end; }
.orn { margin: 0; text-align: center; font-size: 13px; }
.orn img { display: block; margin: 0 auto 4px; }
.orn-coin { width: 104px; } .orn-cadre { width: 160px; } .orn-corde { width: 240px; height: 18px; object-fit: cover; }
.orn-cordev { height: 120px; } .orn-sceau { width: 72px; } .orn-ruban { width: 300px; } .orn-rose { width: 260px; }
.orn-filet { width: 320px; } .orn-clou { width: 36px; } .orn-etiquette { width: 200px; } .orn-berry { height: 48px; }
.situations { display: flex; flex-wrap: wrap; gap: 22px; align-items: center; }
.demo-cadre { width: min(300px, 100%); padding: 26px 30px; border: 40px solid transparent; border-image: url(cadre.svg) 40 / 30px stretch;
  background: var(--parchemin) url(../textures/parchemin.webp) padding-box; background-size: 384px auto; }
.demo-titre { font: 400 24px/1 'Pirata One', serif; margin: 0 0 6px; }
.demo-ruban { height: 64px; max-width: 100%; display: grid; place-items: center; padding: 0 56px 10px;
  border-style: solid; border-width: 0 48px; border-image: url(ruban.svg) 0 48 fill / 0 48px stretch;
  font: 400 26px/1 'Pirata One', serif; }
.demo-ruban.rouge { border-image-source: url(ruban-cire.svg); color: var(--parchemin); }
.demo-etiquettes { display: flex; flex-wrap: wrap; gap: 8px; }
.etiquette { display: inline-flex; align-items: center; height: 44px; padding: 0 18px 2px 46px; border-style: solid;
  border-width: 0 16px 0 40px; border-image: url(etiquette.svg) 0 16 0 40 fill / 0 16px 0 40px stretch;
  font: 700 15px/1 'Alegreya SC', serif; margin-left: -6px; }
.demo-pancarte { position: relative; width: min(260px, 100%); height: 86px; display: grid; place-items: center;
  background: #4a2e1a url(../textures/bois.webp); background-size: 300px auto; border-radius: 6px;
  box-shadow: inset 0 0 0 2px rgba(0,0,0,.4), 0 8px 14px rgba(0,0,0,.4); }
.pancarte-texte { font: 400 34px/1 'Pirata One', serif; color: var(--parchemin); text-shadow: 0 2px 0 rgba(0,0,0,.5); }
.clou { position: absolute; top: 10px; width: 20px; height: 20px; background: url(clou.svg) center / contain no-repeat; }
.clou.g { left: 12px; } .clou.d { right: 12px; }
.demo-sceaux { display: flex; gap: 12px; }
.sceau { width: 72px; height: 72px; display: grid; place-items: center; background: center / contain no-repeat; }
.sceau.r { background-image: url(sceau-rouge.svg); } .sceau.v { background-image: url(sceau-vert.svg); }
.sceau.a { background-image: url(sceau-ambre.svg); }
.dans-sceau { width: 30px; height: 30px; color: #f3e6c8; --ton2: transparent; }
.demo-carte-coins { position: relative; width: min(340px, 100%); padding: 34px 40px 24px; background: url(../textures/vignette.webp) 0 0 / 100% 100%,
  var(--parchemin) url(../textures/parchemin.webp); background-size: 100% 100%, 384px auto; }
.coin { position: absolute; width: 46px; height: 46px; background: url(coin.svg) center / contain no-repeat; }
.coin.hg { left: 6px; top: 6px; } .coin.hd { right: 6px; top: 6px; transform: scaleX(-1); }
.coin.bg { left: 6px; bottom: 6px; transform: scaleY(-1); } .coin.bd { right: 6px; bottom: 6px; transform: scale(-1); }
.demo-filet { width: 260px; display: block; margin: 8px auto 0; }
.tampons { display: flex; flex-wrap: wrap; gap: 26px; align-items: center; padding: 16px; background: var(--parchemin2) url(../textures/parchemin.webp); background-size: 384px auto; }
.tampon-img { height: 92px; mix-blend-mode: multiply; opacity: .9; }
.tampon-css { display: inline-block; padding: 2px 10px; border: 2px solid currentColor; border-radius: 3px; color: var(--cire);
  font: 700 15px/1.4 'Alegreya SC', serif; letter-spacing: .1em; text-transform: uppercase; transform: rotate(-4deg); opacity: .9;
  -webkit-mask-image: url(../textures/grain_tampon.webp); mask-image: url(../textures/grain_tampon.webp); -webkit-mask-size: 160px auto; mask-size: 160px auto; }
.textures { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 12px; }
.tx { margin: 0; height: 240px; display: flex; align-items: flex-end; border: 1px solid rgba(0,0,0,.3); }
.tx figcaption { background: rgba(239,226,196,.85); padding: 2px 6px; }
.tx-parchemin { background: url(../textures/parchemin.webp); background-size: 384px auto; }
.tx-fonce { background: url(../textures/parchemin_fonce.webp); background-size: 384px auto; }
.tx-bois { background: url(../textures/bois.webp); background-size: 512px auto; }
.tx-carte { background: var(--parchemin) url(../textures/carte_marine.webp) center / cover; }
.tx-vignette { background: url(../textures/vignette.webp) 0 0 / 100% 100%, url(../textures/parchemin.webp); background-size: 100% 100%, 384px auto; }
.tx-grain { background: #8e2a24; -webkit-mask-image: url(../textures/grain_tampon.webp); mask-image: url(../textures/grain_tampon.webp); -webkit-mask-size: 160px auto; mask-size: 160px auto; }
.tx-grand { margin-top: 14px; min-height: 520px; padding: 24px; background: url(../textures/vignette.webp) 0 0 / 100% 100%,
  url(../textures/carte_marine.webp) center / cover, url(../textures/parchemin.webp); background-size: 100% 100%, cover, 384px auto; }
.affiches { display: flex; flex-wrap: wrap; gap: 30px; align-items: flex-start; }
.affiche { position: relative; aspect-ratio: 5 / 7; container-type: inline-size; filter: drop-shadow(0 8px 10px rgba(0,0,0,.45)); }
.affiche.a600 { width: min(600px, 100%); } .affiche.a300 { width: min(300px, 100%); }
.affiche > * { position: absolute; }
.papier, .cadre-affiche { left: 0; top: 0; width: 100%; height: 100%; }
.cadre-affiche { mix-blend-mode: multiply; }
.portrait { display: grid; place-items: center; background: #c9b17f; color: rgba(43,29,18,.55); }
.portrait-ico { width: 60%; height: 60%; --ton2: transparent; }
.txt { display: flex; align-items: center; justify-content: center; text-align: center; white-space: nowrap; overflow: hidden; color: var(--encre); }
.grade { font: 700 calc(0.03 * 100cqw)/1 'Alegreya SC', serif; }
.surnom { font: italic 400 calc(0.042 * 100cqw)/1 'Alegreya', serif; }
.nom { font: 400 calc(0.078 * 100cqw)/1 'Rye', serif; }
.prime { font: 400 calc(0.072 * 100cqw)/1 'Rye', serif; gap: 0.25em; }
.berry { position: static; height: 0.8em; }
.icones { gap: 1.6cqw; } .icones .ico { width: 6cqw; height: 6cqw; }
.zone { outline: 1px dashed #8e2a24; background: rgba(142,42,36,.08); display: flex; align-items: flex-start; }
.zone span { font: 11px/1 Consolas, monospace; color: #8e2a24; background: rgba(255,255,255,.7); }
.pngs { display: flex; flex-wrap: wrap; gap: 16px; }
.png { margin: 0; display: grid; gap: 6px; justify-items: center; font-size: 13px; }
.p128 { width: 128px; height: 128px; } .p22 { width: 22px; height: 22px; } .p32 { width: 32px; height: 32px; }
.discord-sombre, .discord-clair { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 4px;
  font: 600 14px/1 'Segoe UI', sans-serif; }
.discord-sombre { background: #313338; color: #dbdee1; } .discord-clair { background: #ffffff; color: #313338; border: 1px solid #ddd; }
.polices p { margin: 6px 0; }
.f-pirata { font: 400 34px/1.2 'Pirata One', serif; } .f-rye { font: 400 30px/1.2 'Rye', serif; }
.f-alegreya { font: 400 19px/1.4 'Alegreya', serif; } .f-alegreya.i { font-style: italic; } .f-alegreya.b { font-weight: 700; }
.f-sc { font: 400 20px/1.4 'Alegreya SC', serif; } .f-sc.b { font-weight: 700; }
"""

# ════════════════════════════════════════════════════════════════════════════════════════
#  Sprite et planche-contact
# ════════════════════════════════════════════════════════════════════════════════════════

# Les noms promis par la spécification (§4) et ceux que le bot demande : le sprite doit tous les avoir.
ICONES_REQUISES = (
    "port equipage capitainerie apercu journal sanctions tickets repertoire salons nettoyage membres fiches "
    "candidatures annonces evenements affiches catalogue roles ajouter modifier supprimer fermer valider "
    "annuler rechercher filtrer exporter copier lien ouvrir plus moins gauche droite haut bas menu deconnexion "
    "en_ligne hors_ligne synchro attention info succes erreur minuteur calendrier lieu prime drapeau navire "
    "ancre boussole longue_vue cloche parchemin plume cadenas cle coffre sabre canon carte etoile oeil "
    "personne discord roblox peut_etre horloge").split()


def verifier_svg(texte, quoi):
    """Un SVG doit être du XML valide, sans attribut style (CSP) ni « -- » dans un commentaire."""
    import xml.etree.ElementTree as ET
    if "style=" in texte:
        raise SystemExit(f"[DESSINS] {quoi} : attribut style interdit")
    for c in re.findall(r"<!--(.*?)-->", texte, re.S):
        if "--" in c:
            raise SystemExit(f"[DESSINS] {quoi} : « -- » dans un commentaire (XML invalide)")
    ET.fromstring(texte)


def ecrire_sprite():
    manquantes = [nm for nm in ICONES_REQUISES if nm not in ICONES]
    if manquantes:
        raise SystemExit(f"[DESSINS] icônes manquantes : {', '.join(manquantes)}")
    g = " ".join(f'{k}="{v}"' for k, v in SPRITE_DEFAUT.items())
    lignes = ['<svg xmlns="http://www.w3.org/2000/svg">',
              "<!-- Icônes du site, gravées par outils/dessins_site.py. Encre : currentColor ; second ton : "
              "la propriété personnalisée ton2 (laiton par défaut ; repli : la couleur fill héritée). "
              "Usage : un symbole par nom, identifiant i-nom, viewBox 0 0 32 32. -->"]
    for nom in ICONES:
        corps = svg_corps(dessin_icone(nom), SPRITE_COULEURS, SPRITE_DEFAUT)
        lignes.append(f'<symbol id="i-{nom}" viewBox="0 0 32 32"><g {g}>{corps}</g></symbol>')
    lignes.append("</svg>")
    D_ICONES.mkdir(parents=True, exist_ok=True)
    texte = "\n".join(lignes) + "\n"
    verifier_svg(texte, "ui.svg")
    (D_ICONES / "ui.svg").write_text(texte, encoding="utf-8", newline="\n")
    print(f"[DESSINS] ui.svg : {len(ICONES)} icônes, {len(texte.encode()) // 1024} Ko")


def _police_label(taille):
    for f in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def apercu_icones(chemin, noms=None, zoom=1):
    """Planche-contact Pillow : chaque icône à 16/20/24/32/48 px sur parchemin, 16/24/32 sur bois."""
    noms = noms or list(ICONES)
    tp, tb = (16, 20, 24, 32, 48), (16, 24, 32)
    cl, ch, cols = 330, 80, 4
    lignes = math.ceil(len(noms) / cols)
    img = Image.new("RGB", (cols * cl, lignes * ch), (246, 242, 233))
    dr = ImageDraw.Draw(img)
    fonte = _police_label(12)
    c_p = {"encre": hexa(ENCRE), "ton2": hexa(LAITON)}
    c_b = {"encre": hexa(PARCHEMIN), "ton2": hexa(LAITON)}
    for i, nom in enumerate(noms):
        x0, y0 = (i % cols) * cl, (i // cols) * ch
        dr.text((x0 + 6, y0 + 2), nom, font=fonte, fill=(70, 45, 25))
        dr.rectangle((x0 + 4, y0 + 20, x0 + 202, y0 + 76), fill=hexa(PARCHEMIN)[:3])
        dr.rectangle((x0 + 206, y0 + 20, x0 + 326, y0 + 76), fill=hexa("#3b2416")[:3])
        dessin = dessin_icone(nom)
        x = x0 + 9
        for t in tp:
            r = rasteriser(dessin, t, couleurs=c_p)
            img.paste(r, (x, y0 + 20 + (56 - t) // 2), r)
            x += t + 7
        x = x0 + 212
        for t in tb:
            r = rasteriser(dessin, t, couleurs=c_b)
            img.paste(r, (x, y0 + 20 + (56 - t) // 2), r)
            x += t + 10
    if zoom > 1:
        img = img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)
    img.save(chemin)
    print(f"[DESSINS] aperçu : {chemin}")


# ════════════════════════════════════════════════════════════════════════════════════════
#  Commandes
# ════════════════════════════════════════════════════════════════════════════════════════

def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = argv[1:]
    if args and args[0] == "apercu":
        zoom = 1
        if "--zoom" in args:
            k = args.index("--zoom")
            zoom = int(args[k + 1])
            del args[k:k + 2]
        apercu_icones(args[1], args[2:] or None, zoom)
        return 0
    if args and args[0] == "glyphes":
        imprimer_glyphes(args[1:])
        return 0
    taches = {"icones": ecrire_sprite}
    for nom in ("ornements", "textures", "png", "planche", "polices"):
        f = globals().get(f"ecrire_{nom}")
        if f:
            taches[nom] = f
    demandees = args or [t for t in ("icones", "ornements", "textures", "png", "planche") if t in taches]
    for t in demandees:
        if t not in taches:
            print(f"commande inconnue : {t} (connues : {', '.join(taches)})")
            return 2
        taches[t]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
