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

# Step 1: CPU-only PyTorch — must come FIRST before sentence-transformers
# so it never pulls in the 800MB CUDA build as a dependency.
RUN pip install --no-cache-dir \
    torch==2.2.2 \
    --index-url https://download.pytorch.org/whl/cpu

# Step 2: Everything else (sentence-transformers pinned in requirements.txt)
RUN pip install --no-cache-dir -r requirements.txt

# ── App files ─────────────────────────────────────────────────────────────────
COPY . .

# ── Pre-download the embedding model at build time ────────────────────────────
# Bakes weights into the image — zero download delay at runtime.
RUN python3 -c "\
import torch; \
print('torch version:', torch.__version__); \
print('torch.nn ok:', torch.nn.Linear); \
from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('all-MiniLM-L6-v2'); \
print('Model cached OK'); \
"

EXPOSE 5000

CMD ["bash", "start.sh"]
