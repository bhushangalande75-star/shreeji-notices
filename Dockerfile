# ── Base ──────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── System deps: LibreOffice for DOCX generation ──────────────────────────────
RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-writer \
    fonts-dejavu \
    fonts-liberation \
    --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps ───────────────────────────────────────────────────────────────
# fastembed uses ONNX runtime — no torch, no CUDA, no version conflicts.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── App files ─────────────────────────────────────────────────────────────────
COPY . .

# ── Pre-download the embedding model at build time ────────────────────────────
# Bakes model weights into the image — zero download delay at runtime.
RUN python3 -c "\
from fastembed import TextEmbedding; \
m = TextEmbedding('sentence-transformers/all-MiniLM-L6-v2'); \
vecs = list(m.embed(['warmup'])); \
print('fastembed model cached OK, dim =', len(vecs[0])); \
"

EXPOSE 5000

CMD ["bash", "start.sh"]
