#!/bin/bash
set -e

echo "▶ Running database migrations..."
python migrate_passwords.py

echo "▶ Starting gunicorn..."
exec gunicorn \
    --bind 0.0.0.0:${PORT:-5000} \
    --timeout 120 \
    --workers 1 \
    --worker-class sync \
    --preload \
    app:app
