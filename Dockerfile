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
COPY requirements.txt .

# Install CPU-only PyTorch FIRST (saves ~500 MB vs default CUDA build).
# Must be installed before sentence-transformers so it does not pull CUDA torch.
RUN pip install --no-cache-dir \
    torch==2.2.2 \
    --index-url https://download.pytorch.org/whl/cpu

# Install everything else
RUN pip install --no-cache-dir -r requirements.txt

# ── App files ─────────────────────────────────────────────────────────────────
COPY . .

# ── Pre-download the embedding model at build time ────────────────────────────
# Bakes the model weights into the image so there is no cold-start download.
RUN python3 -c "\
from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('all-MiniLM-L6-v2'); \
print('Model cached OK')" || echo "WARNING: model pre-download failed"

EXPOSE 5000

# start.sh handles migrations + gunicorn
CMD ["bash", "start.sh"]
