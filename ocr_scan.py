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


# ── Helpers prétraitement OCR (owner 2026-07-18, scam « casino MrBeast » mode sombre non lu) ──
_WORD_RX = re.compile(r"[A-Za-zÀ-ÿ0-9$€]{3,}")


def _txt_quality(t: str) -> int:
    """Richesse d'un texte OCR = nb de mots de ≥3 caractères (départage les 2 passes)."""
    try:
        return len(_WORD_RX.findall(t or ""))
    except Exception:
        return 0


def _otsu_threshold(g) -> int:
    """Seuil d'Otsu depuis l'histogramme 256 niveaux (pur Python, 256 itérations = coût nul).
    Bien plus robuste qu'un seuil fixe sur les fonds DÉGRADÉS (violet des captures casino)."""
    try:
        hist = g.histogram()
        total = sum(hist)
        if total <= 0:
            return 128
        sum_all = 0.0
        for i, c in enumerate(hist):
            sum_all += i * c
        sum_b = 0.0
        w_b = 0
        best, thr = -1.0, 128
        for i in range(256):
            w_b += hist[i]
            if w_b == 0:
                continue
            w_f = total - w_b
            if w_f == 0:
                break
            sum_b += i * hist[i]
            m_b = sum_b / w_b
            m_f = (sum_all - sum_b) / w_f
            var_between = w_b * w_f * (m_b - m_f) ** 2
            if var_between > best:
                best, thr = var_between, i
        return thr
    except Exception:
        return 128


def image_text(image_bytes: bytes) -> str:
    """SYNC (à lancer via run_in_executor). Texte OCR de l'image, ou '' si KO. FAIL-SAFE.

    STRATÉGIE 2 PASSES (owner 2026-07-18 — captures scam « casino MrBeast » en MODE SOMBRE
    passées sous les radars : Tesseract binarise par Otsu GLOBAL → sur fond noir/violet
    dégradé + JPEG, la segmentation de page rate, et tessedit_do_invert, qui n'agit que par
    LIGNE déjà détectée, ne rescue rien) :
      • passe 1 = image INTACTE (comportement historique exact — les captures claires
        continuent de lire comme avant, zéro régression possible) ; si la lecture est déjà
        riche (≥ 25 mots), on s'arrête là → coût CPU inchangé sur les images normales ;
      • passe 2 (sinon) = prétraitement « mode sombre / petit texte UI » en Pillow PUR :
        gris → upscale ×2 LANCZOS si petite image → inversion si luminance moyenne sombre
        → autocontrast → binarisation Otsu. On rend le texte le plus riche des deux.
    Borne CPU : ≤ 2 runs Tesseract/image (timeout 20 s chacun), image ≤ 2200 px de côté
    (downscale conservé) ; l'appelant garde sémaphore 2 + plafond d'images/message."""
    if not _load():
        return ""
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(image_bytes))
        # Downscale les images énormes (perf) sans casser la lisibilité du texte.
        # LANCZOS préserve mieux les contours de texte que le BICUBIC par défaut.
        try:
            if (im.width * im.height) > 4_000_000:
                im.thumbnail((2200, 2200), Image.LANCZOS)
        except Exception:
            pass
        if im.mode not in ("L", "RGB"):
            im = im.convert("RGB")

        # ── Passe 1 : image telle quelle (comportement historique) ──
        try:
            t1 = _PYTESS.image_to_string(im, timeout=20) or ""
        except Exception:
            t1 = ""
        q1 = _txt_quality(t1)
        if q1 >= 25:               # lecture déjà riche → inutile de payer une 2e passe
            return t1

        # ── Passe 2 : prétraitement mode sombre / petit texte (Pillow pur) ──
        try:
            g = im.convert("L")
            # Petit texte UI antialiasé + JPEG : ×2 LANCZOS si l'image est petite
            # (plafond de pixels pour rester borné CPU/RAM).
            if max(g.width, g.height) < 1600 and (g.width * g.height) <= 1_100_000:
                g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
            # Inversion si l'image est majoritairement SOMBRE (texte clair sur fond
            # noir/violet) → on redonne à Tesseract son cas nominal noir-sur-blanc,
            # au niveau PAGE (tessedit_do_invert n'agit qu'au niveau ligne).
            hist = g.histogram()
            npx = float(g.width * g.height) or 1.0
            mean = sum(i * c for i, c in enumerate(hist)) / npx
            if mean < 140:
                g = ImageOps.invert(g)
            g = ImageOps.autocontrast(g, cutoff=1)
            thr = _otsu_threshold(g)
            bw = g.point(lambda p, _t=thr: 255 if p > _t else 0, "L")
            t2 = _PYTESS.image_to_string(bw, timeout=20) or ""
        except Exception:
            t2 = ""

        # Départage par richesse : la passe 2 ne peut jamais DÉGRADER une image claire —
        # au pire son texte est plus pauvre et on garde celui de la passe 1.
        return t2 if _txt_quality(t2) > q1 else t1
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
    # ═══ SPLIT (owner 2026-07-18, incident mabewin) : l'ancien méga-signal
    # (wallet|method|success|usdt) ne comptait qu'UNE fois même quand l'image contenait les
    # 4 termes → une capture « Withdrawal Success » SEULE scorait 5 < 6 et passait. Scindé en
    # 3 signaux distincts + termes d'UI « caisse » casino. Node-testé 18/18 (0 FP sur 14
    # captures légitimes gaming, max légitime = 2 vs seuil 6).
    (re.compile(r"wallet\s+address|withdraw\s+method", re.I), 2),
    (re.compile(r"withdrawal\s+success|was\s+successfully", re.I), 2),
    (re.compile(r"\busdt\b|tether", re.I), 2),
    (re.compile(r"bank\s?card|network\s+fee", re.I), 1),
    (re.compile(r"register(s|ed)?\b|sign\s?up|who\s+registers", re.I), 1),
    (re.compile(r"t\.me/|telegram|\bdm\s+me\b|whats\s?app|wa\.me/", re.I), 2),
    (re.compile(r"airdrop|double\s+your|guaranteed\s+(profit|return)|passive\s+income", re.I), 2),
    # Famille de domaines du scam « casino MrBeast » : luzewin → vyro → mabewin (ils tournent).
    (re.compile(r"luzewin|vyro|mabewin", re.I), 3),
    (re.compile(r"\brake\s?back\b", re.I), 3),   # « rakeback » = terme 100 % casino en ligne
    # ═══ VEILLE 2026 (RaidProtect, vague confirmée : 160k comptes piratés/juin) : la vague
    # « casino crypto » tourne les CÉLÉBRITÉS (MrBeast → Elon Musk → Andrew Tate) et usurpe
    # Kick/Stake. ⚠️ anti-FP : « kick »/« stake » NUS interdits (kick du groupe, staking de
    # jeu) → domaines/expressions casino uniquement. « casino » seul = 1 (GTA a un casino).
    # « free spins » = 2 pas 3 (Coin Master l'affiche). Node-testé 24/24, 0 FP (pire cas
    # légitime : Coin Master = 4 < 6).
    (re.compile(r"elon\s?musk|andrew\s?tate", re.I), 2),
    (re.compile(r"stake\.com|stake\s+casino|kick\.com", re.I), 2),
    (re.compile(r"\bcasino\b", re.I), 1),
    (re.compile(r"free\s+spins?", re.I), 2),
    (re.compile(r"connect\s+(your\s+)?wallet|link\s+(your\s+)?wallet", re.I), 2),
    (re.compile(r"argent\s+facile|gains?\s+garantis?|revenus?\s+passifs?", re.I), 2),
]


def qr_payloads(image_bytes: bytes):
    """Décode les QR codes présents dans une image → liste des chaînes encodées (souvent des
    URLs). Un QR = destination MASQUÉE → vecteur d'arnaque (faux Nitro, token grabber…).
    Nécessite pyzbar + la lib système libzbar0 ; FAIL-SAFE → [] si absent."""
    try:
        from pyzbar.pyzbar import decode
        from PIL import Image
        im = Image.open(io.BytesIO(image_bytes))
        out = []
        for d in decode(im):
            try:
                out.append((d.data or b"").decode("utf-8", "replace").strip())
            except Exception:
                continue
        return [p for p in out if p]
    except Exception:
        return []


def scan_scam(text: str, threshold: int = 6):   # 6 = seuil réel de l'appelant (bot.py:8684)
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
