#!/bin/bash
echo "▶ Running password migration..."
python migrate_passwords.py
echo "▶ Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --timeout 300 --workers 1 app:app
