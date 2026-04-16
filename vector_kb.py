"""
vector_kb.py — Document processing pipeline for SocietyNotice Pro Vector KB.

Responsibilities:
  1. Extract text from PDF / DOCX / XLSX / TXT
  2. Chunk text into overlapping segments
  3. Embed chunks using sentence-transformers (local, FREE, no API key needed)
  4. Store in Neon pgvector

Embedding model: all-MiniLM-L6-v2
  - Dimension: 384
  - Size: ~80MB (downloads once on first use)
  - Runs locally on Render — zero cost, zero API key
"""

import os, io, re

EMBED_MODEL = "all-MiniLM-L6-v2"
EMBED_DIM   = 384   # dimension for this model

# Lazy-load the model — downloaded once, cached on disk
_embedder = None

def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        print(f"[KB] Loading embedding model {EMBED_MODEL}...")
        _embedder = SentenceTransformer(EMBED_MODEL)
        print(f"[KB] Model loaded ✅")
    return _embedder

CHUNK_SIZE     = 500   # characters (not tokens) — safe for 8192 token model
CHUNK_OVERLAP  = 80    # characters overlap between consecutive chunks


# ── Text Extraction ────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages  = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t.strip())
        return "\n\n".join(pages)
    except Exception as e:
        raise ValueError(f"PDF extraction failed: {e}")


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes using python-docx."""
    try:
        from docx import Document
        doc  = Document(io.BytesIO(file_bytes))
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paras.append(row_text)
        return "\n\n".join(paras)
    except Exception as e:
        raise ValueError(f"DOCX extraction failed: {e}")


def extract_text_from_excel(file_bytes: bytes) -> str:
    """Extract text from Excel bytes using pandas."""
    try:
        import pandas as pd
        dfs = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
        sections = []
        for sheet_name, df in dfs.items():
            df = df.fillna("").astype(str)
            rows = []
            # Header row
            rows.append(" | ".join(str(c) for c in df.columns))
            rows.append("-" * 60)
            for _, row in df.iterrows():
                line = " | ".join(str(v).strip() for v in row.values)
                if any(v.strip() for v in row.values if v.strip() not in ("nan", "")):
                    rows.append(line)
            sections.append(f"Sheet: {sheet_name}\n" + "\n".join(rows))
        return "\n\n".join(sections)
    except Exception as e:
        raise ValueError(f"Excel extraction failed: {e}")


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Route to correct extractor based on file extension."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return extract_text_from_docx(file_bytes)
    elif ext in ("xlsx", "xls"):
        return extract_text_from_excel(file_bytes)
    elif ext == "txt":
        return file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: .{ext}")


# ── Chunking ───────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks of ~chunk_size characters.
    Tries to break at sentence/paragraph boundaries.
    """
    # Normalise whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []

    chunks = []
    start  = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            # Last chunk
            chunks.append(text[start:].strip())
            break
        # Try to break at paragraph boundary
        para_break = text.rfind("\n\n", start, end)
        if para_break > start + overlap:
            end = para_break
        else:
            # Try sentence boundary
            sent_break = max(
                text.rfind(". ", start + overlap, end),
                text.rfind("। ", start + overlap, end),  # Devanagari full stop
                text.rfind("\n",  start + overlap, end),
            )
            if sent_break > start + overlap:
                end = sent_break + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap  # overlap so context carries over

    return chunks


# ── Embedding ──────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts using sentence-transformers (local, no API key).
    Returns list of embedding vectors (dim=384).
    """
    if not texts:
        return []
    model  = _get_embedder()
    # encode() returns numpy array — convert to plain Python list
    vecs   = model.encode(texts, batch_size=32, show_progress_bar=False,
                          convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def embed_query(query: str) -> list[float]:
    """Embed a single query string."""
    model = _get_embedder()
    vec   = model.encode([query], convert_to_numpy=True)
    return vec[0].tolist()


# ── Full pipeline ──────────────────────────────────────────────

def process_document(file_bytes: bytes, filename: str) -> tuple[list[str], list[list[float]]]:
    """
    Full pipeline: extract → chunk → embed.
    Returns (chunks, embeddings).
    """
    text   = extract_text(file_bytes, filename)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No text could be extracted from this document.")
    embeddings = embed_texts(chunks)
    return chunks, embeddings
