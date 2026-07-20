# ─────────────────────────────────────────────────────────────────────────────
# Build DÉTERMINISTE du bot (owner 2026-07-20).
#
# POURQUOI : nixpacks n'installait PAS le binaire `tesseract` (ni via aptPkgs ni via
# nixPkgs) → l'OCR anti-scam était MORT en prod (le [DIAG] security/scanners a craché
# « TesseractNotFoundError » deux boots de suite) → les captures d'arnaque « casino
# MrBeast » passaient. Un Dockerfile = contrôle TOTAL des binaires système, 100 %
# reproductible sur Railway (qui priorise le Dockerfile sur nixpacks).
#
# Python 3.13 = version RÉELLE du runtime nixpacks (Railway affichait python@3.13.14 ; nixpacks
# ignorait le nixPkgs=python311, d'où aussi le tesseract jamais installé). `audioop-lts` exige
# Python >=3.13 → un Dockerfile en 3.11 échouait à `pip install` (No matching distribution).
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm

# Binaires / libs système requis (aucun n'est installable via pip) :
#   • tesseract-ocr + tesseract-ocr-eng : moteur OCR + langue anglaise (anti-scam image)
#   • libzbar0                          : décodage des QR codes (pyzbar, anti-scam)
#   • libgl1 libglib2.0-0 libgomp1      : runtime onnxruntime/opencv (nudenet = NSFW image)
#   • libsm6 libxext6 libxrender1       : libs X d'opencv (au cas où nudenet tire opencv non-headless)
# --no-install-recommends + purge des listes apt = image légère.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libzbar0 \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python d'abord (couche Docker mise en cache tant que requirements.txt ne change pas),
# puis le code — un simple push de code ne réinstalle pas tout pip.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Secrets (TOKEN, RSSHUB_BASE_URL, YOUTUBE_API_KEY, DIAG_VERBOSE…) = variables d'env Railway.
# Le volume persistant (/data) est monté par Railway. health_server écoute sur $PORT.
# PYTHONUNBUFFERED : les prints/stderr (dont [DIAG]) sortent en direct dans les Deploy Logs.
ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
