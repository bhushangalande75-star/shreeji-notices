#!/bin/bash
echo "▶ Running password migration..."
python migrate_passwords.py

echo "▶ Pre-loading embedding model (may take a few minutes on first deploy)..."
python - <<'EOF'
from vector_kb import _get_embedder
try:
    _get_embedder()
    print("[KB] Embedding model ready ✅")
except Exception as e:
    print(f"[KB] WARNING: Could not pre-load model: {e}")
    print("[KB] Model will be loaded on first request instead.")
EOF

echo "▶ Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --timeout 120 --workers 1 app:app
