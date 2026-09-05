# EnergiPro Intelligence Platform (Enterprise) — single-container build
#
# Full v6.x platform (governance/trust/market/revenue/win-strategy/prediction/
# presentation-builder engines) with the AI Sales Assistant left in its
# built-in rule-based fallback mode (no ANTHROPIC_API_KEY set) — see .env.
FROM python:3.11-slim
WORKDIR /app

# tesseract-ocr + poppler-utils: OCR fallback path for scanned-image PDF DDR
# uploads (engines/ocr_pipeline.py, pdf2image). Degrades gracefully if ever
# missing, but both are cheap to include for full fidelity.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Security: run as non-root (matches the original trial-package Dockerfile)
RUN groupadd -r eip && useradd -r -g eip eip
RUN mkdir -p /data && chown eip:eip /data

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY frontend/ ./frontend/
RUN chown -R eip:eip /app

USER eip
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
