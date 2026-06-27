"""ocr_scan.py — Détection d'ARNAQUES EN IMAGE par OCR (owner 2026-06-27).

But : lire le texte ÉCRIT DANS une image (capture de faux gains crypto, « MrBeast giveaway »,
« withdrawal success », code promo, casino crypto…) que le détecteur basé sur la LÉGENDE ne peut
pas voir. On extrait le texte avec Tesseract puis on le passe à un scoreur HAUTE PRÉCISION.

100 % FAIL-SAFE : si Tesseract/pytesseract/Pillow ne sont pas dispo (binaire absent sur l'hôte),
`available()` renvoie False et tout le module devient un no-op — le bot tourne normalement.

Perf : `image_text()` est SYNCHRONE (Tesseract = CPU bloquant) → l'appelant DOIT l'exécuter dans
un thread (`loop.run_in_executor`) pour ne pas geler la boucle asyncio.
"""
from __future__ import annotations

import io
import re

_PYTESS = None          # module pytesseract (chargé paresseusement)
_AVAILABLE = None       # cache: True / False (évite de re-tester le binaire à chaque image)


def _load() -> bool:
    global _PYTESS, _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        import pytesseract
        from PIL import Image  # noqa: F401  (utilisé dans image_text)
        _ = pytesseract.get_tesseract_version()   # lève si le binaire tesseract est absent
        _PYTESS = pytesseract
        _AVAILABLE = True
        print(f"[ocr_scan] OCR prêt (tesseract {_})")
    except Exception as ex:
        _AVAILABLE = False
        print(f"[ocr_scan] OCR indisponible ({ex}) — scan d'image OCR désactivé (fail-safe)")
    return _AVAILABLE


def available() -> bool:
    return _load()


def image_text(image_bytes: bytes) -> str:
    """SYNC (à lancer via run_in_executor). Texte OCR de l'image, ou '' si KO. FAIL-SAFE."""
    if not _load():
        return ""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes))
        # Downscale les images énormes (perf) sans casser la lisibilité du texte.
        try:
            if (im.width * im.height) > 4_000_000:
                im.thumbnail((2200, 2200))
        except Exception:
            pass
        if im.mode not in ("L", "RGB"):
            im = im.convert("RGB")
        return _PYTESS.image_to_string(im) or ""
    except Exception:
        return ""


# ─── Scoreur scam HAUTE PRÉCISION sur le texte OCR ───────────────────────────────
# Ces captures d'arnaque sont un MUR de mots-clés argent/crypto/giveaway. On exige un FAISCEAU
# de signaux (≥ threshold ET ≥2 signaux distincts) → une image normale qui montre juste un prix
# (« win $100 ») ne déclenche PAS. Anglais surtout (ces scams sont en anglais), quelques FR.
_MONEY = re.compile(r"(\$\s?\d{2,}|\d{2,}\s?\$|\d{2,}\s?usd|\d{2,}\s?€|\d{1,3}\s?%)", re.I)
_SIGNALS = [
    (re.compile(r"mr\.?\s?beast", re.I), 3),
    (re.compile(r"crypto(currency)?\s+casino|crypto\s+casino", re.I), 3),
    (re.compile(r"withdraw(al)?\b|cash\s?out|cashout", re.I), 2),
    (re.compile(r"promo\s?code|promocode|code\s+promo", re.I), 2),
    (re.compile(r"giv(e|ing)\s+away|giveaway", re.I), 2),
    (re.compile(r"claim\s+(your|now|the|you)", re.I), 2),
    (re.compile(r"\bbonus\b", re.I), 2),
    (re.compile(r"free\s+(money|cash|crypto|nitro|robux|vbucks|bitcoin|btc|usdt|gift)", re.I), 2),
    (re.compile(r"wallet\s+address|withdraw\s+method|withdrawal\s+success|\busdt\b|tether", re.I), 2),
    (re.compile(r"register(s|ed)?\b|sign\s?up|who\s+registers", re.I), 1),
    (re.compile(r"t\.me/|telegram|\bdm\s+me\b|whats\s?app|wa\.me/", re.I), 2),
    (re.compile(r"airdrop|double\s+your|guaranteed\s+(profit|return)|passive\s+income", re.I), 2),
    (re.compile(r"luzewin|vyro", re.I), 3),
    (re.compile(r"argent\s+facile|gains?\s+garantis?|revenus?\s+passifs?", re.I), 2),
]


def scan_scam(text: str, threshold: int = 5):
    """(is_scam, reason, score). HAUTE PRÉCISION : score ≥ threshold ET ≥2 signaux distincts."""
    try:
        if not text:
            return False, "", 0
        t = text.lower()
        score = 0
        hits = []
        for rx, w in _SIGNALS:
            if rx.search(t):
                score += w
                hits.append(rx.pattern.split("|")[0].split("\\")[0][:16].strip())
        if _MONEY.search(t):
            score += 1
        if score >= threshold and len(hits) >= 2:
            return True, "signaux: " + ", ".join(hits[:6]), score
        return False, "", score
    except Exception:
        return False, "", 0
